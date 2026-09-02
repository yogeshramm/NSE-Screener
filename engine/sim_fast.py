"""Pass 2 — portfolio simulator over the cached screen.

Reads data_store/sim_cache/{formula}.pkl (built by deploy/build_screen_cache.py)
and runs a real 3-slot book day by day. Because the expensive screening is
already done, a full 284-day run takes seconds, so entry filters, stop policies
and hold limits can be swept properly instead of guessed at.

Everything the earlier per-trade studies could not model is modelled here:
  • slot contention — only `max_positions` trades can be open at once
  • capital — position size comes from current equity, not a notional
  • ranking — when more candidates pass than there are slots, the highest
    formula score wins, same as the live screener

Entries fill at the NEXT session's open. Stops are checked before targets
within a bar. No bar after the decision date is ever read.
"""

from __future__ import annotations

import math
import os
import pickle
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(ROOT, "data_store", "sim_cache")
# Fills and exits must read the SAME series the screen was built from. Raw
# prices step at every bonus and split, so a position held through one books a
# loss that never happened. Adjusted is used whenever it exists.
_ADJ_DIR = os.path.join(ROOT, "data_store", "history_adjusted")
HIST_DIR = _ADJ_DIR if os.path.isdir(_ADJ_DIR) else os.path.join(ROOT, "data_store", "history")

BROKER_PCT = 0.001
STT_PCT = 0.00025

DEFAULTS: Dict[str, Any] = {
    "purse": 100000.0,
    "max_positions": 3,
    "top_n": 3,
    # ---- exit policy ----
    "stop_mode": "formula",     # formula | flat | atr_mult | none
    "stop_flat_pct": 20.0,      # used when stop_mode == "flat"
    "stop_atr_mult": 3.0,       # multiplies the formula's stop DISTANCE
    "use_target": True,
    "max_hold_bars": 30,
    # ---- entry filters ----
    # ---- conviction gate: an ABSOLUTE bar, not a ranking. Every candidate that
    # clears it is bought (up to max_positions); a day where nothing clears buys
    # NOTHING. This is what makes 0/1/2/3 positions emerge instead of always 3.
    "min_score": None,            # e.g. 55  → skip weak composite scores
    "min_neo": None,              # e.g. 4   → conditions-met floor
    "neo_field": "neo",           # "neo" | "neo_ext"
    "min_rs_rank": None,          # e.g. 60  → only relative-strength leaders
    # ---- sizing cap ----
    "max_alloc_pct": None,        # e.g. 50.0 → never put more than this % of the
                                  # CURRENT book in one name. On a 1L purse 50%
                                  # is "max Rs50k", and it stays 50% as the book
                                  # grows rather than drifting into huge bets.
    "min_alloc": 5000.0,          # skip an entry that can only be funded with a
                                  # meaningless sliver of cash (we saw Rs67 fills)
    "min_pct_below_52wh": None,   # e.g. 5.0 → skip names hugging the high
    "min_atr_pct": None,          # e.g. 3.5 → only volatile names
    "max_prior_6m": None,         # e.g. 20.0 → skip names that already ran
    "max_rs_rank": None,          # e.g. 80  → skip the most extended leaders
    "regime_gate": False,
    "regime_lookback": 63,
    # ---- early exit ----
    "dud_exit_bars": None,        # e.g. 5 → cut if no progress after N bars
    "dud_exit_pct": 0.0,
    # ---- sizing ----
    "fixed_sizing": False,        # True → every position sized off the STARTING
                                  # purse, so gains are never reinvested. Models
                                  # withdrawing profit rather than compounding it.
}


def load_cache(formula: str) -> Dict[str, Any]:
    with open(os.path.join(CACHE_DIR, f"{formula}.pkl"), "rb") as f:
        return pickle.load(f)


_HIST: Dict[str, Optional[pd.DataFrame]] = {}


def hist(sym: str) -> Optional[pd.DataFrame]:
    if sym not in _HIST:
        p = os.path.join(HIST_DIR, f"{sym}.pkl")
        if not os.path.exists(p):
            _HIST[sym] = None
        else:
            d = pickle.load(open(p, "rb"))
            _HIST[sym] = d[~d.index.duplicated(keep="last")].sort_index()
    return _HIST[sym]


_POS: Dict[str, Dict[Any, int]] = {}


def pos(sym: str) -> Dict[Any, int]:
    if sym not in _POS:
        d = hist(sym)
        _POS[sym] = {} if d is None else {t: i for i, t in enumerate(d.index)}
    return _POS[sym]


def prior_6m(sym: str, day: pd.Timestamp) -> Optional[float]:
    d = hist(sym)
    i = pos(sym).get(day)
    if d is None or i is None or i < 126:
        return None
    past = float(d["Close"].iloc[i - 126])
    if past <= 0:
        return None
    return (float(d["Close"].iloc[i]) - past) / past * 100


def run(formula: str, start: str, end: str, cfg: Optional[Dict[str, Any]] = None,
        regime: Optional[Dict[Any, Dict[str, Any]]] = None) -> Dict[str, Any]:
    c = {**DEFAULTS, **(cfg or {})}
    cache = load_cache(formula)
    days_map = cache["days"]

    dates = sorted(d for d in days_map if start <= d <= end)
    if len(dates) < 10:
        raise RuntimeError(f"only {len(dates)} cached days in {start}..{end}")
    cal = [pd.Timestamp(d) for d in dates]

    cash = float(c["purse"])
    positions: Dict[str, Dict[str, Any]] = {}
    trades: List[Dict[str, Any]] = []
    equity_curve: List[float] = []
    skipped = 0

    def px(sym, day, field="Close"):
        d = hist(sym)
        i = pos(sym).get(day)
        if d is None or i is None:
            return None
        return float(d[field].iloc[i])

    for di, day in enumerate(cal):
        nxt = cal[di + 1] if di + 1 < len(cal) else None

        # ---- 1. exits on today's bar ----
        for sym in list(positions):
            p = positions[sym]
            d = hist(sym)
            i = pos(sym).get(day)
            if d is None or i is None:
                continue
            bar = d.iloc[i]
            o, h, l, cl = (float(bar["Open"]), float(bar["High"]),
                           float(bar["Low"]), float(bar["Close"]))
            p["bars"] += 1
            sl, tg = p["stop"], p["target"]
            out = None
            if sl and o <= sl:
                out = (o, "stop_gap")
            elif sl and l <= sl and tg and h >= tg:
                out = (sl, "stop_first_same_bar")
            elif sl and l <= sl:
                out = (sl, "stop")
            elif tg and h >= tg:
                out = (tg, "target")
            elif c["dud_exit_bars"] and p["bars"] >= c["dud_exit_bars"] \
                    and (cl - p["entry"]) / p["entry"] * 100 <= c["dud_exit_pct"]:
                out = (cl, "dud_exit")
            elif p["bars"] >= c["max_hold_bars"]:
                out = (cl, "hold_expiry")
            if out is None:
                continue
            exit_px, reason = out
            positions.pop(sym)
            gross = p["qty"] * exit_px
            charges = (p["entry"] * p["qty"] * BROKER_PCT
                       + gross * (BROKER_PCT + STT_PCT))
            cash += gross - gross * (BROKER_PCT + STT_PCT)
            trades.append({
                "symbol": sym, "entry_date": p["entry_date"], "entry": p["entry"],
                "qty": p["qty"], "exit_date": str(day.date()), "exit": exit_px,
                "reason": reason, "bars": p["bars"],
                "net": gross - p["entry"] * p["qty"] - charges,
                "pct": (exit_px - p["entry"]) / p["entry"] * 100,
                "score": p["score"], "atr_pct": p["atr_pct"], "prox52": p["prox52"],
            })

        # ---- 2. entries ----
        free = c["max_positions"] - len(positions)
        if free > 0 and nxt is not None:
            blocked = False
            if c["regime_gate"] and regime is not None:
                r = regime.get(day) or {}
                if r.get("spread") is not None and r["spread"] <= 0:
                    blocked = True
            if not blocked:
                rows = [r for r in days_map[str(day.date())]["rows"] if r.get("passed")]
                rows.sort(key=lambda r: r.get("score") or 0, reverse=True)
                taken = 0
                for r in rows:
                    if taken >= free or taken >= c["top_n"]:
                        break
                    sym = r["symbol"]
                    if sym in positions:
                        continue
                    price = r.get("price")
                    if not price or not r.get("stop_loss"):
                        continue
                    atrp = (r["atr"] / price * 100) if r.get("atr") else None
                    # ---- conviction gate ----
                    if c["min_score"] is not None:
                        if (r.get("score") or 0) < c["min_score"]:
                            skipped += 1
                            continue
                    if c["min_neo"] is not None:
                        if (r.get(c["neo_field"]) or 0) < c["min_neo"]:
                            skipped += 1
                            continue
                    if c["min_rs_rank"] is not None:
                        if r.get("rs_rank") is None or r["rs_rank"] < c["min_rs_rank"]:
                            skipped += 1
                            continue
                    # ---- filters ----
                    if c["min_pct_below_52wh"] is not None:
                        if r.get("prox52") is None or r["prox52"] < c["min_pct_below_52wh"]:
                            skipped += 1
                            continue
                    if c["min_atr_pct"] is not None:
                        if atrp is None or atrp < c["min_atr_pct"]:
                            skipped += 1
                            continue
                    if c["max_rs_rank"] is not None:
                        if r.get("rs_rank") is not None and r["rs_rank"] > c["max_rs_rank"]:
                            skipped += 1
                            continue
                    if c["max_prior_6m"] is not None:
                        p6 = prior_6m(sym, day)
                        if p6 is not None and p6 > c["max_prior_6m"]:
                            skipped += 1
                            continue

                    fill = px(sym, nxt, "Open")
                    if not fill or fill <= 0:
                        continue
                    # ---- stop ----
                    if c["stop_mode"] == "flat":
                        stop = fill * (1 - c["stop_flat_pct"] / 100)
                    elif c["stop_mode"] == "atr_mult":
                        stop = fill - (price - r["stop_loss"]) * c["stop_atr_mult"]
                    elif c["stop_mode"] == "none":
                        stop = None
                    else:
                        stop = r["stop_loss"]
                    target = r.get("target") if c["use_target"] else None

                    if c["fixed_sizing"]:
                        base = float(c["purse"])
                    else:
                        base = cash + sum(
                            (px(s, day) or positions[s]["entry"]) * positions[s]["qty"]
                            for s in positions)
                    alloc = min(cash, base / c["max_positions"])
                    if c["max_alloc_pct"] is not None:
                        alloc = min(cash, base * c["max_alloc_pct"] / 100.0)
                    if c["min_alloc"] and alloc < c["min_alloc"]:
                        skipped += 1
                        continue
                    qty = int(alloc // (fill * (1 + BROKER_PCT)))
                    if qty < 1:
                        continue
                    cash -= qty * fill * (1 + BROKER_PCT)
                    positions[sym] = {"entry": fill, "qty": qty, "stop": stop,
                                      "target": target, "bars": 0,
                                      "entry_date": str(nxt.date()),
                                      "score": r.get("score"), "atr_pct": atrp,
                                      "prox52": r.get("prox52")}
                    taken += 1

        # ---- 3. mark to market ----
        pv = sum((px(s, day) or positions[s]["entry"]) * positions[s]["qty"]
                 for s in positions)
        equity_curve.append(cash + pv)

    # close out
    last = cal[-1]
    for sym in list(positions):
        p = positions.pop(sym)
        exit_px = px(sym, last) or p["entry"]
        gross = p["qty"] * exit_px
        charges = p["entry"] * p["qty"] * BROKER_PCT + gross * (BROKER_PCT + STT_PCT)
        cash += gross - gross * (BROKER_PCT + STT_PCT)
        trades.append({"symbol": sym, "entry_date": p["entry_date"], "entry": p["entry"],
                       "qty": p["qty"], "exit_date": str(last.date()), "exit": exit_px,
                       "reason": "run_end", "bars": p["bars"],
                       "net": gross - p["entry"] * p["qty"] - charges,
                       "pct": (exit_px - p["entry"]) / p["entry"] * 100,
                       "score": p["score"], "atr_pct": p["atr_pct"], "prox52": p["prox52"]})
    if equity_curve:
        equity_curve[-1] = cash

    return _metrics(formula, c, trades, equity_curve, cal, skipped)


def _metrics(formula, c, trades, eq, cal, skipped):
    start_cash = float(c["purse"])
    eq = eq or [start_cash]
    nets = np.array([t["net"] for t in trades]) if trades else np.array([0.0])
    wins = nets[nets > 0]
    losses = nets[nets <= 0]
    peak, mdd = eq[0], 0.0
    for v in eq:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak * 100)
    rets = pd.Series(eq).pct_change().dropna()
    sharpe = float(rets.mean() / rets.std() * math.sqrt(252)) if len(rets) > 5 and rets.std() > 0 else None
    exposure = sum(t["bars"] for t in trades) / (c["max_positions"] * len(cal)) * 100
    from collections import Counter
    return {
        "formula": formula, "trades": len(trades),
        "pnl": eq[-1] - start_cash,
        "pnl_pct": (eq[-1] - start_cash) / start_cash * 100,
        "win_rate": float((nets > 0).mean() * 100) if trades else 0.0,
        "max_dd": mdd, "sharpe": sharpe,
        "profit_factor": float(wins.sum() / abs(losses.sum())) if len(losses) and losses.sum() < 0 else None,
        "avg_bars": float(np.mean([t["bars"] for t in trades])) if trades else 0,
        "exposure_pct": exposure, "skipped": skipped,
        "exits": dict(Counter(t["reason"] for t in trades)),
        "equity": eq, "trade_list": trades,
        "t_stat": float(nets.mean() / (nets.std(ddof=1) / math.sqrt(len(nets)))) if len(nets) > 3 and nets.std(ddof=1) > 0 else None,
    }


def benchmark(start: str, end: str, symbols: List[str]) -> float:
    """Equal-weight buy-and-hold of the universe over the window."""
    rs = []
    for s in symbols:
        d = hist(s)
        if d is None:
            continue
        w = d.loc[start:end]
        if len(w) < 30:
            continue
        a, b = float(w["Close"].iloc[0]), float(w["Close"].iloc[-1])
        if a > 0:
            rs.append((b - a) / a * 100)
    return float(np.mean(rs)) if rs else 0.0
