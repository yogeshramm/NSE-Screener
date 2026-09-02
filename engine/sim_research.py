"""
Real Sim — Tier 1 research agent (deterministic, point-in-time safe).

This is the automation of the manual research done AFTER a formula has
filtered the universe: favourite indicators, multi-timeframe agreement,
trend structure, money flow, relative strength and risk sanity.

Design rules that make it honest in replay:
  • Every series is computed once per symbol over full history, then only
    values at index <= the as-of bar are ever read. No forward slicing.
  • No LLM, no network, no snapshot data that post-dates the as-of bar.
  • Anything unavailable at the as-of date scores NEUTRAL and is EXCLUDED
    from the denominator, so a card reads 6/8 rather than a fake 6/10.

Live mode later adds two more checks (news impact, event edge) — the
denominator grows to 10 and nothing else changes.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

# ── check weights (weighted score); every check also counts 1 toward "x/y" ──
WEIGHTS = {
    "neo":           2.0,   # AO + RSI + MACD + Vortex + Supertrend inflection
    "stochrsi":      1.0,
    "not_extended":  1.0,   # don't chase
    "mtf":           1.5,   # 1D / 1W / 1M agreement
    "trend":         1.5,   # MA stack + slope
    "flow":          1.0,   # OBV / volume behaviour
    "rs":            1.5,   # relative strength vs universe (point-in-time)
    "risk_rr":       1.0,   # R:R and ATR sanity
    "news":          1.0,   # live only
    "event":         1.0,   # live only
}

LABELS = {
    "neo":          "Neo inflection (AO/RSI/MACD/Vortex/Supertrend)",
    "stochrsi":     "Stochastic RSI",
    "not_extended": "Not extended / not chasing",
    "mtf":          "Multi-timeframe agreement",
    "trend":        "Trend structure",
    "flow":         "Money flow (OBV + volume)",
    "rs":           "Relative strength",
    "risk_rr":      "Risk / reward",
    "news":         "News impact",
    "event":        "Event edge",
}

PASS, FAIL, NEUTRAL, NA = "PASS", "FAIL", "NEUTRAL", "NA"
_SCORE = {PASS: 1.0, NEUTRAL: 0.5, FAIL: 0.0}


# ─────────────────────────── vectorised series ───────────────────────────

def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def _rsi(c: pd.Series, n: int = 14) -> pd.Series:
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, min_periods=n).mean()
    dn = (-d).clip(lower=0).ewm(alpha=1 / n, min_periods=n).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _stoch_rsi(c: pd.Series, n: int = 14, k: int = 3, d: int = 3):
    r = _rsi(c, n)
    lo = r.rolling(n).min()
    hi = r.rolling(n).max()
    raw = (r - lo) / (hi - lo).replace(0, np.nan)
    kk = raw.rolling(k).mean()
    dd = kk.rolling(d).mean()
    return kk, dd


def _macd(c: pd.Series):
    m = _ema(c, 12) - _ema(c, 26)
    sig = m.ewm(span=9, adjust=False).mean()
    return m, sig, m - sig


def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["High"], df["Low"], df["Close"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, min_periods=n).mean()


def _supertrend_dir(df: pd.DataFrame, period: int = 7, mult: float = 3.0) -> pd.Series:
    """+1 bullish / -1 bearish, computed iteratively (same convention as the app)."""
    atr = _atr(df, period)
    hl2 = (df["High"] + df["Low"]) / 2
    upper = hl2 + mult * atr
    lower = hl2 - mult * atr
    c = df["Close"].to_numpy()
    up = upper.to_numpy()
    lo = lower.to_numpy()
    n = len(df)
    fu = np.full(n, np.nan)
    fl = np.full(n, np.nan)
    d = np.ones(n)
    for i in range(1, n):
        fu[i] = up[i] if (np.isnan(fu[i - 1]) or up[i] < fu[i - 1] or c[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = lo[i] if (np.isnan(fl[i - 1]) or lo[i] > fl[i - 1] or c[i - 1] < fl[i - 1]) else fl[i - 1]
        if not np.isnan(fu[i]) and c[i] > fu[i]:
            d[i] = 1
        elif not np.isnan(fl[i]) and c[i] < fl[i]:
            d[i] = -1
        else:
            d[i] = d[i - 1]
    return pd.Series(d, index=df.index)


def _obv(df: pd.DataFrame) -> pd.Series:
    sign = np.sign(df["Close"].diff().fillna(0))
    return (sign * df["Volume"]).cumsum()


def _tf_score(close: pd.Series) -> int:
    """-3..+3 for one timeframe: RSI band, MA stack, higher-highs, close vs MA20."""
    if len(close) < 25:
        return 0
    s = 0
    r = _rsi(close).iloc[-1]
    if not np.isnan(r):
        s += 1 if 45 <= r <= 70 else (-1 if r < 40 or r > 80 else 0)
    ma20 = close.rolling(20).mean().iloc[-1]
    if not np.isnan(ma20):
        s += 1 if close.iloc[-1] > ma20 else -1
    if len(close) >= 12:
        s += 1 if close.iloc[-1] > close.iloc[-11] else -1
    return int(max(-3, min(3, s)))


# ─────────────────────────── per-symbol prep ───────────────────────────

def build_series(df: pd.DataFrame) -> Dict[str, Any]:
    """Compute every research series ONCE for a symbol's full history.

    Returned arrays are index-aligned with `df`; the sim reads position i
    (the as-of bar) and never beyond it.
    """
    c = df["Close"]
    k, d = _stoch_rsi(c)
    macd, sig, hist = _macd(c)
    obv = _obv(df)
    return {
        "index": df.index,
        "close": c,
        "rsi": _rsi(c),
        "stoch_k": k,
        "stoch_d": d,
        "macd": macd,
        "macd_hist": hist,
        "ema21": _ema(c, 21),
        "ema50": _ema(c, 50),
        "sma200": c.rolling(200).mean(),
        "atr": _atr(df),
        "st_dir": _supertrend_dir(df),
        "obv": obv,
        "obv_ma": obv.rolling(20).mean(),
        "vol": df["Volume"],
        "vol_ma": df["Volume"].rolling(20).mean(),
        "ret_126": c.pct_change(126) * 100,
    }


def _v(series: pd.Series, i: int) -> Optional[float]:
    try:
        x = float(series.iloc[i])
        return None if np.isnan(x) else x
    except Exception:
        return None


# ─────────────────────────── the checks ───────────────────────────

def _chk(key: str, status: str, detail: str) -> Dict[str, Any]:
    return {"key": key, "label": LABELS[key], "status": status,
            "detail": detail, "weight": WEIGHTS[key]}


def _check_neo(s2: Dict[str, Any]) -> Dict[str, Any]:
    neo = (s2 or {}).get("neo") or {}
    ext = (s2 or {}).get("neo_extended") or {}
    pend = (s2 or {}).get("neo_pending") or {}
    score = max(int(neo.get("score") or 0), int(ext.get("score") or 0))
    miss = neo.get("missing") or ext.get("missing") or []
    if score >= 5:
        return _chk("neo", PASS, f"5/5 perfect inflection — all five indicators flipped together")
    if score == 4:
        return _chk("neo", PASS, f"4/5 inflection (missing: {', '.join(miss) if miss else 'n/a'})")
    if pend.get("is_pending"):
        return _chk("neo", NEUTRAL, "Pending — pre-flip alignment, Supertrend not yet bullish")
    if score == 3:
        return _chk("neo", NEUTRAL, f"3/5 — partial alignment (missing: {', '.join(miss) if miss else 'n/a'})")
    return _chk("neo", FAIL, f"{score}/5 — indicators not aligned")


def _check_stochrsi(S, i) -> Dict[str, Any]:
    k, d = _v(S["stoch_k"], i), _v(S["stoch_d"], i)
    if k is None or d is None:
        return _chk("stochrsi", NA, "insufficient history")
    # A fresh breakout/inflection legitimately runs a hot StochRSI, so a high
    # %K is only bearish once it TURNS DOWN. Penalising elevated-but-rising
    # would veto every momentum setup the formulas are built to find.
    if k > d:
        if k < 0.85:
            zone = "from oversold" if k < 0.35 else "mid-range"
            return _chk("stochrsi", PASS, f"%K {k:.2f} > %D {d:.2f}, turning up {zone}")
        return _chk("stochrsi", NEUTRAL,
                    f"%K {k:.2f} > %D {d:.2f} — hot but still rising")
    if k > 0.75:
        return _chk("stochrsi", FAIL, f"%K {k:.2f} rolling over from overbought")
    if k < 0.25:
        return _chk("stochrsi", NEUTRAL, f"%K {k:.2f} — washed out, no turn up yet")
    return _chk("stochrsi", FAIL, f"%K {k:.2f} < %D {d:.2f} — momentum fading")


def _check_not_extended(S, i) -> Dict[str, Any]:
    c, e21, r = _v(S["close"], i), _v(S["ema21"], i), _v(S["rsi"], i)
    if c is None or e21 is None or r is None:
        return _chk("not_extended", NA, "insufficient history")
    ext = (c - e21) / e21 * 100
    if r > 78 or ext > 12:
        return _chk("not_extended", FAIL, f"RSI {r:.0f}, {ext:+.1f}% above EMA21 — chasing")
    if r > 72 or ext > 8:
        return _chk("not_extended", NEUTRAL, f"RSI {r:.0f}, {ext:+.1f}% above EMA21 — slightly extended")
    return _chk("not_extended", PASS, f"RSI {r:.0f}, {ext:+.1f}% from EMA21 — healthy entry zone")


def _check_mtf(df_upto: pd.DataFrame) -> Dict[str, Any]:
    if len(df_upto) < 60:
        return _chk("mtf", NA, "insufficient history")
    c = df_upto["Close"]
    dly = _tf_score(c)
    wk = _tf_score(c.resample("W").last().dropna())
    mo = _tf_score(c.resample("ME").last().dropna()) if len(c) >= 200 else 0
    tot = dly + wk + mo
    parts = f"1D {dly:+d} · 1W {wk:+d} · 1M {mo:+d} = {tot:+d}/9"
    if tot >= 4:
        return _chk("mtf", PASS, f"Aligned bullish — {parts}")
    if tot >= 1:
        return _chk("mtf", NEUTRAL, f"Mildly positive — {parts}")
    return _chk("mtf", FAIL, f"Timeframes disagree — {parts}")


def _check_trend(S, i) -> Dict[str, Any]:
    c, e21, e50 = _v(S["close"], i), _v(S["ema21"], i), _v(S["ema50"], i)
    s200 = _v(S["sma200"], i)
    e50p = _v(S["ema50"], i - 20) if i >= 20 else None
    if c is None or e21 is None or e50 is None:
        return _chk("trend", NA, "insufficient history")
    rising50 = e50p is not None and e50 > e50p
    stacked = c > e21 > e50
    above200 = s200 is not None and c > s200
    if stacked and rising50 and (above200 or s200 is None):
        return _chk("trend", PASS, "Close > EMA21 > EMA50, EMA50 rising"
                                   + (", above SMA200" if above200 else ""))
    if c > e50 and rising50:
        return _chk("trend", NEUTRAL, "Above EMA50 and rising, stack not clean")
    return _chk("trend", FAIL, "MA stack not supportive")


def _check_flow(S, i) -> Dict[str, Any]:
    o, om = _v(S["obv"], i), _v(S["obv_ma"], i)
    vol, vma = _v(S["vol"], i), _v(S["vol_ma"], i)
    if o is None or om is None or vma is None or not vma:
        return _chk("flow", NA, "insufficient history")
    ratio = vol / vma if vol else 0
    if o > om and ratio >= 1.3:
        return _chk("flow", PASS, f"OBV above its 20d mean, volume {ratio:.1f}× average")
    if o > om:
        return _chk("flow", NEUTRAL, f"OBV rising but volume only {ratio:.1f}× average")
    return _chk("flow", FAIL, f"OBV below 20d mean — distribution (vol {ratio:.1f}×)")


def _check_rs(rs_pct: Optional[int]) -> Dict[str, Any]:
    if rs_pct is None:
        return _chk("rs", NA, "not computable")
    if rs_pct >= 70:
        return _chk("rs", PASS, f"RS {rs_pct}/99 — outperforming the universe")
    if rs_pct >= 45:
        return _chk("rs", NEUTRAL, f"RS {rs_pct}/99 — in line with the market")
    return _chk("rs", FAIL, f"RS {rs_pct}/99 — lagging the market")


def _check_risk(entry: float, sl: Optional[float], tgt: Optional[float],
                atr: Optional[float]) -> Dict[str, Any]:
    if not sl or not tgt or sl <= 0 or sl >= entry:
        return _chk("risk_rr", FAIL, "no valid stop from the formula")
    risk = entry - sl
    rr = (tgt - entry) / risk if risk > 0 else 0
    risk_pct = risk / entry * 100
    atr_pct = (atr / entry * 100) if atr else None
    bits = f"R:R {rr:.2f}, risk {risk_pct:.1f}%"
    if atr_pct:
        bits += f", ATR {atr_pct:.1f}%"
    if rr >= 2.0 and risk_pct <= 8:
        return _chk("risk_rr", PASS, bits)
    if rr >= 1.5 and risk_pct <= 12:
        return _chk("risk_rr", NEUTRAL, bits)
    return _chk("risk_rr", FAIL, bits + " — poor asymmetry")


# ─────────────────────────── the dossier ───────────────────────────

def build_dossier(symbol: str, df_upto: pd.DataFrame, S: Dict[str, Any], i: int,
                  s2: Dict[str, Any], rs_pct: Optional[int],
                  mode: str = "replay") -> Dict[str, Any]:
    """Assemble the full research dossier for one candidate on one day.

    `i` is the positional index of the as-of bar inside the FULL series in S.
    `df_upto` is the history slice ending at that bar. Nothing later is read.
    """
    entry = float(df_upto["Close"].iloc[-1])
    checks = [
        _check_neo(s2),
        _check_stochrsi(S, i),
        _check_not_extended(S, i),
        _check_mtf(df_upto),
        _check_trend(S, i),
        _check_flow(S, i),
        _check_rs(rs_pct),
        _check_risk(entry, s2.get("stop_loss"), s2.get("target"), _v(S["atr"], i)),
    ]
    if mode == "live":
        # Placeholders — wired to the news/event agents when live mode ships.
        checks.append(_chk("news", NA, "live-mode agent not yet wired"))
        checks.append(_chk("event", NA, "live-mode agent not yet wired"))

    available = [c for c in checks if c["status"] != NA]
    wsum = sum(c["weight"] * _SCORE[c["status"]] for c in available)
    wmax = sum(c["weight"] for c in available) or 1.0
    pct = wsum / wmax
    passed = sum(1 for c in available if c["status"] == PASS)

    return {
        "symbol": symbol,
        "as_of": str(df_upto.index[-1].date()),
        "price": round(entry, 2),
        "checks": checks,
        "checks_passed": passed,
        "checks_available": len(available),
        "weighted": round(wsum, 2),
        "weighted_max": round(wmax, 2),
        "pct": round(pct, 4),
        "formula_score": s2.get("score"),
        "stop_loss": s2.get("stop_loss"),
        "target": s2.get("target"),
        "rr": s2.get("risk_reward"),
        "neo_score": (s2.get("neo") or {}).get("score"),
    }


def decide(dossier: Dict[str, Any], buy_threshold: float = 0.65,
           high_threshold: float = 0.80) -> Dict[str, Any]:
    """BUY / SKIP with conviction and English reasons. Hard vetoes override score."""
    checks = {c["key"]: c for c in dossier["checks"]}
    vetoes: List[str] = []

    if checks.get("risk_rr", {}).get("status") == FAIL:
        vetoes.append(f"Risk veto — {checks['risk_rr']['detail']}")
    if checks.get("not_extended", {}).get("status") == FAIL:
        vetoes.append(f"Chase veto — {checks['not_extended']['detail']}")
    if checks.get("neo", {}).get("status") == FAIL and \
       checks.get("trend", {}).get("status") == FAIL:
        vetoes.append("Setup veto — neither indicator inflection nor trend structure supports entry")

    pct = dossier["pct"]
    reasons = [f"{'✓' if c['status'] == PASS else '~' if c['status'] == NEUTRAL else '✗'} "
               f"{c['label']}: {c['detail']}"
               for c in dossier["checks"] if c["status"] != NA]

    if vetoes:
        return {"action": "SKIP", "conviction": "NONE",
                "verdict": vetoes[0],
                "reasons": vetoes + reasons}
    if pct >= high_threshold:
        conv = "HIGH"
    elif pct >= buy_threshold:
        conv = "MEDIUM"
    else:
        return {"action": "SKIP", "conviction": "NONE",
                "verdict": (f"Not convincing — {dossier['checks_passed']}/"
                            f"{dossier['checks_available']} checks, "
                            f"{pct * 100:.0f}% weighted (need {buy_threshold * 100:.0f}%)"),
                "reasons": reasons}

    return {"action": "BUY", "conviction": conv,
            "verdict": (f"{conv} conviction — {dossier['checks_passed']}/"
                        f"{dossier['checks_available']} checks, {pct * 100:.0f}% weighted"),
            "reasons": reasons}


def exit_signal(S: Dict[str, Any], i: int, pos: Dict[str, Any],
                dossier: Optional[Dict[str, Any]],
                decay_threshold: float = 0.40) -> Optional[Dict[str, str]]:
    """Non-price exit triggers: thesis decay, Supertrend flip, momentum roll-over.

    SL / target / max-hold are handled by the price walk in real_sim.
    """
    st = _v(S["st_dir"], i)
    if st is not None and st < 0:
        prev = _v(S["st_dir"], i - 1) if i > 0 else None
        if prev is not None and prev > 0:
            return {"reason": "supertrend_flip",
                    "detail": "Supertrend flipped bearish — trend thesis broken"}

    if dossier is not None and dossier["pct"] < decay_threshold:
        return {"reason": "thesis_decay",
                "detail": (f"Research score decayed to {dossier['checks_passed']}/"
                           f"{dossier['checks_available']} "
                           f"({dossier['pct'] * 100:.0f}%) — below "
                           f"{decay_threshold * 100:.0f}% floor")}

    k, d = _v(S["stoch_k"], i), _v(S["stoch_d"], i)
    r = _v(S["rsi"], i)
    if k is not None and d is not None and r is not None and k < d and k > 0.75 and r > 70:
        return {"reason": "momentum_rollover",
                "detail": f"StochRSI rolled over from overbought (%K {k:.2f}, RSI {r:.0f})"}

    return None
