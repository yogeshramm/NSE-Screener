"""
Real Sim — portfolio simulator that runs a formula AND the research layer
day by day, exactly the way the manual process works.

Per formula, two independent books off one screening pass:
    RAW   — buy the formula's top N. No research, no veto.
    BRAIN — same candidates, each must clear the research template; weak
            setups are skipped and the cash stays in cash.

Comparing the two answers the real question: does the research overlay add
anything, or is it costing money?

── No-lookahead guarantees ────────────────────────────────────────────────
  • Screening on day D sees `df.loc[:D]` only — the identical code path as
    the live screener (`run_full_screen`), not a re-implementation.
  • Entries fill at the NEXT session's open. A signal from D's close can
    never fill at D's price.
  • RS rank is recomputed point-in-time from price history, never read from
    today's snapshot.
  • Exits walk bar by bar; when stop and target are both touched inside one
    bar the stop is assumed first.
  • No LLM anywhere in the replay loop — nothing here has knowledge of what
    happened after the as-of bar.

Known soft leaks (printed in every run's leak audit, never hidden):
  • Fundamentals (ROE / D:E / EPS) are current snapshots, not point-in-time.
  • Index membership is today's Nifty list → mild survivorship bias.
  • Earnings-blackout filter is disabled (needs forward-looking dates).
  • News and event-edge checks are unavailable (no historical archive), so
    the template scores out of 8 rather than 10.
"""

from __future__ import annotations

import json
import math
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from engine import sim_db
from engine.screener import run_full_screen
from engine.sim_research import build_dossier, build_series, decide, exit_signal

# India equity delivery costs — same model as the practice game
BROKER_PCT = 0.001      # 0.1% each side
STT_PCT = 0.00025       # 0.025% on sell

FORMULA_CODES = {
    "neo_radar": "NEOR",
    "neo_extended": "NEOX",
    "delay_f_rsi68": "DF68",
    "delay_f_rsi70": "DF70",
    "original_formula": "OF1",
    "original_formula_3": "OF3",
}


def formula_code(name: str) -> str:
    return FORMULA_CODES.get(name, name.upper()[:4])


DEFAULTS = {
    "purse": 100000.0,
    "max_positions": 3,
    "top_n": 3,              # candidates the formula puts forward per day
    "candidate_pool": 10,    # how deep BRAIN researches before filling slots
    "max_hold_bars": 30,
    "buy_threshold": 0.65,
    "high_threshold": 0.80,
    "decay_threshold": 0.40,
    "size_high": 1.0,        # fraction of a slot for HIGH conviction
    "size_medium": 0.70,
}


# ────────────────────────────── book ──────────────────────────────

class Book:
    """One formula + one arm: cash, up to N open positions, trade log."""

    def __init__(self, run_id: str, formula: str, arm: str, cfg: Dict[str, Any]):
        self.run_id = run_id
        self.formula = formula
        self.code = formula_code(formula)
        self.arm = arm
        self.book_id = f"{run_id}/{self.code}/{arm}"
        self.cfg = cfg
        self.start_cash = float(cfg["purse"])
        self.cash = self.start_cash
        self.positions: Dict[str, Dict[str, Any]] = {}
        self.trades: List[Dict[str, Any]] = []
        self.equity_rows: List[Dict[str, Any]] = []
        self.decisions: List[Dict[str, Any]] = []
        self.vetoed = 0
        self._seq: Dict[str, int] = {}

    # -- helpers --
    def slots_free(self) -> int:
        return self.cfg["max_positions"] - len(self.positions)

    def _trade_id(self, symbol: str, date: str) -> str:
        key = f"{symbol}/{date}"
        self._seq[key] = self._seq.get(key, 0) + 1
        return f"{self.book_id}/{symbol}/{date.replace('-', '')}-{self._seq[key]}"

    def equity(self, price_of: Callable[[str], Optional[float]]) -> Tuple[float, float]:
        pv = 0.0
        for sym, p in self.positions.items():
            px = price_of(sym) or p["entry_price"]
            pv += px * p["qty"]
        return self.cash, pv

    # -- trading --
    def buy(self, symbol: str, date: str, price: float, sl: float, tgt: float,
            conviction: str, dossier: Optional[Dict[str, Any]],
            reasons: List[str], formula_score: Optional[float],
            equity_now: float) -> bool:
        slot = equity_now / self.cfg["max_positions"]
        frac = self.cfg["size_high"] if conviction == "HIGH" else self.cfg["size_medium"]
        alloc = min(self.cash, slot * (frac if self.arm == "BRAIN" else 1.0))
        qty = int(alloc // (price * (1 + BROKER_PCT)))
        if qty < 1:
            return False
        cost = qty * price
        charges = cost * BROKER_PCT
        self.cash -= (cost + charges)
        self.positions[symbol] = {
            "trade_id": self._trade_id(symbol, date),
            "symbol": symbol, "entry_date": date, "entry_price": price,
            "qty": qty, "stop_loss": sl, "target": tgt,
            "entry_charges": charges, "bars_held": 0,
            "conviction": conviction, "formula_score": formula_score,
            "template_score": (dossier or {}).get("checks_passed"),
            "template_max": (dossier or {}).get("checks_available"),
            "entry_reasons": "\n".join(reasons or []),
        }
        return True

    def sell(self, symbol: str, date: str, price: float, reason: str,
             detail: str = "") -> None:
        p = self.positions.pop(symbol)
        gross = p["qty"] * price
        charges = gross * (BROKER_PCT + STT_PCT) + p["entry_charges"]
        self.cash += gross - gross * (BROKER_PCT + STT_PCT)
        cost = p["qty"] * p["entry_price"]
        net = gross - cost - charges
        risk = p["entry_price"] - p["stop_loss"] if p["stop_loss"] else 0
        self.trades.append({
            "run_id": self.run_id, "book_id": self.book_id,
            "trade_id": p["trade_id"], "symbol": symbol, "side": "long",
            "entry_date": p["entry_date"], "entry_price": round(p["entry_price"], 2),
            "qty": p["qty"], "stop_loss": p["stop_loss"], "target": p["target"],
            "rr": round((p["target"] - p["entry_price"]) / risk, 2) if risk > 0 and p["target"] else None,
            "exit_date": date, "exit_price": round(price, 2), "exit_reason": reason,
            "gross_pnl": round(gross - cost, 2), "charges": round(charges, 2),
            "net_pnl": round(net, 2),
            "pnl_pct": round((price - p["entry_price"]) / p["entry_price"] * 100, 2),
            "r_multiple": round((price - p["entry_price"]) / risk, 2) if risk > 0 else None,
            "bars_held": p["bars_held"],
            "formula_score": p["formula_score"],
            "template_score": p["template_score"], "template_max": p["template_max"],
            "conviction": p["conviction"],
            "entry_reasons": p["entry_reasons"], "exit_reasons": detail,
        })

    def log_decision(self, date: str, symbol: str, action: str,
                     dossier: Optional[Dict[str, Any]], verdict: str,
                     conviction: str, reasons: List[str]) -> None:
        self.decisions.append({
            "run_id": self.run_id, "book_id": self.book_id,
            "decision_date": date, "symbol": symbol, "action": action,
            "template_score": (dossier or {}).get("checks_passed"),
            "template_max": (dossier or {}).get("checks_available"),
            "pct": (dossier or {}).get("pct"),
            "conviction": conviction, "verdict": verdict,
            "checks_json": json.dumps((dossier or {}).get("checks", [])),
            "dossier_json": json.dumps(dossier or {}, default=str),
            "reasons": "\n".join(reasons or []),
        })


# ────────────────────────────── metrics ──────────────────────────────

def compute_metrics(book: Book) -> Dict[str, Any]:
    eq = [r["equity"] for r in book.equity_rows] or [book.start_cash]
    trades = book.trades
    wins = [t for t in trades if (t["net_pnl"] or 0) > 0]
    losses = [t for t in trades if (t["net_pnl"] or 0) <= 0]
    gross_win = sum(t["net_pnl"] for t in wins)
    gross_loss = abs(sum(t["net_pnl"] for t in losses))

    peak, mdd = eq[0], 0.0
    for v in eq:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak * 100)

    rets = pd.Series(eq).pct_change().dropna()
    sharpe = None
    if len(rets) > 5 and rets.std() > 0:
        sharpe = float(rets.mean() / rets.std() * math.sqrt(252))

    end_equity = eq[-1]
    return {
        "end_cash": round(book.cash, 2),
        "end_equity": round(end_equity, 2),
        "total_trades": len(trades),
        "wins": len(wins), "losses": len(losses),
        "pnl": round(end_equity - book.start_cash, 2),
        "pnl_pct": round((end_equity - book.start_cash) / book.start_cash * 100, 2),
        "max_dd_pct": round(mdd, 2),
        "sharpe": round(sharpe, 2) if sharpe is not None else None,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else None,
        "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else 0.0,
        "vetoed_count": book.vetoed,
        "avg_win": round(gross_win / len(wins), 2) if wins else 0,
        "avg_loss": round(-gross_loss / len(losses), 2) if losses else 0,
        "exit_breakdown": _counts([t["exit_reason"] for t in trades]),
    }


def _counts(xs: List[str]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for x in xs:
        out[x] = out.get(x, 0) + 1
    return out


# ────────────────────────────── universe prep ──────────────────────────────

def load_universe(symbols: List[str], min_bars: int = 260,
                  log: Callable[[str], None] = print) -> Dict[str, Dict[str, Any]]:
    """Load each symbol's history + fundamentals once, and precompute the
    research series over the FULL history (read positionally later)."""
    from api.data_helper import get_stock_bundle

    uni: Dict[str, Dict[str, Any]] = {}
    skipped = 0
    for n, sym in enumerate(symbols, 1):
        try:
            b = get_stock_bundle(sym)
        except Exception:
            b = None
        if not b or b.get("daily_df") is None or len(b["daily_df"]) < min_bars:
            skipped += 1
            continue
        df = b["daily_df"]
        df = df[~df.index.duplicated(keep="last")].sort_index()
        uni[sym] = {
            "df": df,
            "stock_data": b["stock_data"],
            "series": build_series(df),
            "pos": {d: i for i, d in enumerate(df.index)},
        }
        if n % 50 == 0:
            log(f"    loaded {n}/{len(symbols)} ({len(uni)} usable)")
    log(f"    universe ready: {len(uni)} symbols, {skipped} skipped (short history / no data)")
    return uni


def build_calendar(uni: Dict[str, Dict[str, Any]], start: str, end: str) -> List[pd.Timestamp]:
    """Trading days = dates present in the majority of the universe."""
    counts: Dict[pd.Timestamp, int] = {}
    for u in uni.values():
        for d in u["df"].index:
            counts[d] = counts.get(d, 0) + 1
    need = max(3, len(uni) // 3)
    days = sorted(d for d, c in counts.items() if c >= need)
    lo, hi = pd.Timestamp(start), pd.Timestamp(end)
    return [d for d in days if lo <= d <= hi]


def rs_ranks_for_day(uni: Dict[str, Dict[str, Any]], day: pd.Timestamp) -> Dict[str, int]:
    """Point-in-time relative strength: percentile of 6-month return, as of `day`."""
    vals: Dict[str, float] = {}
    for sym, u in uni.items():
        i = u["pos"].get(day)
        if i is None:
            continue
        try:
            v = float(u["series"]["ret_126"].iloc[i])
        except Exception:
            continue
        if not math.isnan(v):
            vals[sym] = v
    if not vals:
        return {}
    order = sorted(vals.items(), key=lambda kv: kv[1])
    n = len(order)
    return {sym: max(1, min(99, int(round((idx + 1) / n * 99))))
            for idx, (sym, _) in enumerate(order)}


# ────────────────────────────── the run ──────────────────────────────

def run_sim(symbols: List[str], formulas: Dict[str, Dict[str, Any]],
            start: str, end: str, mode: str = "replay",
            cfg: Optional[Dict[str, Any]] = None,
            universe_name: str = "nifty200",
            log: Callable[[str], None] = print,
            persist: bool = True) -> Dict[str, Any]:
    """Run every formula × {RAW, BRAIN} over [start, end]. Returns a summary."""
    conf = {**DEFAULTS, **(cfg or {})}
    t0 = time.time()

    log("Loading universe…")
    uni = load_universe(symbols, log=log)
    if not uni:
        raise RuntimeError("no usable symbols in universe")

    calendar = build_calendar(uni, start, end)
    if len(calendar) < 5:
        raise RuntimeError(f"only {len(calendar)} trading days in {start}..{end}")
    log(f"Calendar: {len(calendar)} trading days "
        f"{calendar[0].date()} → {calendar[-1].date()}")

    run_id = sim_db.next_run_id(mode, datetime.now().strftime("%Y%m%d")) if persist \
        else f"RS-DRY-{mode.upper()}"

    leak_audit = {
        "point_in_time_clean": ["OHLCV bars", "all indicators", "Neo score",
                                "optimal levels", "RS rank (recomputed)",
                                "research template"],
        "soft_leaks": [
            "Fundamentals (ROE/D:E/EPS) are current snapshots, not point-in-time",
            "Index membership is today's Nifty list — mild survivorship bias",
        ],
        "disabled_in_replay": [
            "earnings blackout filter (needs forward-looking dates)",
            "news impact check (no historical news archive)",
            "event edge check (module lands in a later phase)",
        ],
        "template_denominator": 8 if mode == "replay" else 10,
        "entry_fill": "next session open",
        "same_bar_stop_and_target": "stop assumed first (conservative)",
    }

    if persist:
        sim_db.create_run(run_id, mode, universe_name, start, end,
                          list(formulas), conf["purse"], conf, leak_audit)

    books: List[Book] = []
    for fname in formulas:
        for arm in ("RAW", "BRAIN"):
            b = Book(run_id, fname, arm, conf)
            books.append(b)
            if persist:
                sim_db.create_book(run_id, b.book_id, fname, b.code, arm, b.start_cash)
    log(f"Run {run_id} — {len(books)} books ({len(formulas)} formulas × 2 arms)")

    # ── day loop ──
    for di, day in enumerate(calendar):
        dstr = str(day.date())
        nxt = calendar[di + 1] if di + 1 < len(calendar) else None

        # symbols with a bar today
        today: Dict[str, int] = {}
        for sym, u in uni.items():
            i = u["pos"].get(day)
            if i is not None:
                today[sym] = i

        def price_at(sym: str, when: pd.Timestamp, field: str = "Close") -> Optional[float]:
            u = uni.get(sym)
            if not u:
                return None
            i = u["pos"].get(when)
            if i is None:
                return None
            return float(u["df"][field].iloc[i])

        # 1 ── exits first, on today's bar
        for b in books:
            for sym in list(b.positions.keys()):
                p = b.positions[sym]
                i = today.get(sym)
                if i is None:
                    continue
                u = uni[sym]
                bar = u["df"].iloc[i]
                o, h, l, c = (float(bar["Open"]), float(bar["High"]),
                              float(bar["Low"]), float(bar["Close"]))
                p["bars_held"] += 1
                sl, tgt = p["stop_loss"], p["target"]

                if sl and o <= sl:                      # gap through the stop
                    b.sell(sym, dstr, o, "stop_gap", f"Gapped below stop at {o:.2f}")
                    continue
                if sl and l <= sl and tgt and h >= tgt:  # both — stop first
                    b.sell(sym, dstr, sl, "stop_first_same_bar",
                           "Stop and target both touched; stop assumed first")
                    continue
                if sl and l <= sl:
                    b.sell(sym, dstr, sl, "stop", f"Stop {sl:.2f} hit")
                    continue
                if tgt and h >= tgt:
                    b.sell(sym, dstr, tgt, "target", f"Target {tgt:.2f} hit")
                    continue
                if p["bars_held"] >= conf["max_hold_bars"]:
                    b.sell(sym, dstr, c, "hold_expiry",
                           f"Held {p['bars_held']} bars without resolution")
                    continue
                if b.arm == "BRAIN":
                    sig = exit_signal(u["series"], i, p, None, conf["decay_threshold"])
                    if sig:
                        b.sell(sym, dstr, c, sig["reason"], sig["detail"])

        # 2 ── entries: screen once per formula, share across both arms
        need_entries = any(b.slots_free() > 0 for b in books)
        if need_entries and nxt is not None:
            stocks_data = []
            rs_map = rs_ranks_for_day(uni, day)
            for sym, i in today.items():
                u = uni[sym]
                sd = dict(u["stock_data"])
                px = float(u["df"]["Close"].iloc[i])
                sd["latest_close"] = px
                sd["current_price"] = px
                sd["latest_date"] = dstr
                sd["rs_rank"] = rs_map.get(sym)
                stocks_data.append({
                    "symbol": sym,
                    "daily_df": u["df"].iloc[: i + 1],
                    "stock_data": sd,
                    "df_4h": None,
                })

            for fname, fconf in formulas.items():
                arms = [b for b in books if b.formula == fname]
                if not any(b.slots_free() > 0 for b in arms):
                    continue
                try:
                    res = run_full_screen(stocks_data, fconf)
                except Exception as e:                     # a bad day must not kill the run
                    log(f"  ! screen failed {fname} {dstr}: {e}")
                    continue
                passers = [r for r in res["stage2_results"] if r.get("passed")]
                passers.sort(key=lambda r: r.get("score") or 0, reverse=True)

                for b in arms:
                    if b.slots_free() <= 0:
                        continue
                    cash, pv = b.equity(lambda s: price_at(s, day))
                    eq_now = cash + pv

                    if b.arm == "RAW":
                        for r in passers[: conf["top_n"]]:
                            if b.slots_free() <= 0:
                                break
                            sym = r["symbol"]
                            if sym in b.positions:
                                continue
                            fill = price_at(sym, nxt, "Open")
                            if not fill or not r.get("stop_loss") or not r.get("target"):
                                continue
                            b.buy(sym, str(nxt.date()), fill, r["stop_loss"], r["target"],
                                  "RAW", None, [f"Formula rank {r.get('rank')} · "
                                                f"score {r.get('score')}"],
                                  r.get("score"), eq_now)
                        continue

                    # BRAIN — research the pool, buy only what convinces
                    for r in passers[: conf["candidate_pool"]]:
                        if b.slots_free() <= 0:
                            break
                        sym = r["symbol"]
                        if sym in b.positions:
                            continue
                        u = uni[sym]
                        i = today[sym]
                        dossier = build_dossier(sym, u["df"].iloc[: i + 1], u["series"],
                                                i, r, rs_map.get(sym), mode=mode)
                        verdict = decide(dossier, conf["buy_threshold"],
                                         conf["high_threshold"])
                        b.log_decision(dstr, sym, verdict["action"], dossier,
                                       verdict["verdict"], verdict["conviction"],
                                       verdict["reasons"])
                        if verdict["action"] != "BUY":
                            b.vetoed += 1
                            continue
                        fill = price_at(sym, nxt, "Open")
                        if not fill:
                            continue
                        b.buy(sym, str(nxt.date()), fill, r["stop_loss"], r["target"],
                              verdict["conviction"], dossier,
                              [verdict["verdict"]] + verdict["reasons"],
                              r.get("score"), eq_now)

        # 3 ── mark to market
        for b in books:
            cash, pv = b.equity(lambda s: price_at(s, day))
            b.equity_rows.append({
                "run_id": b.run_id, "book_id": b.book_id, "date": dstr,
                "cash": round(cash, 2), "positions_value": round(pv, 2),
                "equity": round(cash + pv, 2), "open_positions": len(b.positions),
            })

        if di % 10 == 0 or di == len(calendar) - 1:
            log(f"  [{di + 1}/{len(calendar)}] {dstr}  "
                + " ".join(f"{b.code}:{b.arm[0]}="
                           f"{b.equity_rows[-1]['equity'] / b.start_cash * 100 - 100:+.1f}%"
                           for b in books))

    # ── close out anything still open at the final bar ──
    last = calendar[-1]
    for b in books:
        for sym in list(b.positions.keys()):
            px = None
            u = uni.get(sym)
            if u:
                i = u["pos"].get(last)
                if i is not None:
                    px = float(u["df"]["Close"].iloc[i])
            b.sell(sym, str(last.date()), px or b.positions[sym]["entry_price"],
                   "run_end", "Position still open when the simulation ended")

    # ── persist + summarise ──
    summary = {"run_id": run_id, "mode": mode, "universe": universe_name,
               "start": start, "end": end, "days": len(calendar),
               "symbols": len(uni), "leak_audit": leak_audit, "books": []}

    for b in books:
        m = compute_metrics(b)
        if persist:
            sim_db.update_book_metrics(b.book_id, m)
            for t in b.trades:
                sim_db.insert_trade(t)
            for d in b.decisions:
                sim_db.insert_decision(d)
            sim_db.insert_equity_rows(b.equity_rows)
        summary["books"].append({
            "book_id": b.book_id, "formula": b.formula, "code": b.code,
            "arm": b.arm, **m,
        })

    if persist:
        sim_db.finish_run(run_id, "done")
    summary["elapsed_s"] = round(time.time() - t0, 1)
    log(f"Done in {summary['elapsed_s']}s — run {run_id}")
    return summary
