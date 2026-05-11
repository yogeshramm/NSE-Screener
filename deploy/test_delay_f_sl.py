#!/usr/bin/env python3
"""
Backtest: DELAY-F RSI70 formula — compare three stop-loss variants.

Entry signal mirrors delay_f_rsi70.json as closely as possible using
only technical indicators (fundamentals can't be backtested from snapshots):
  - Price > EMA50 > EMA200
  - ADX >= 20
  - MACD histogram > 0 (histogram_mode=True)
  - Supertrend bullish (period=10, mult=3.0)
  - OBV rising (OBV > OBV 15-bar avg)
  - Vortex: VI+ > VI-  AND  VI+ delta > 0.07
  - RSI dipped < 50 in last 15 bars, now 52–70
  - Candle closes in top 50% of bar range
  - Volume >= 1.1× 20-day avg

Exit: RSI > 70  OR  60-bar time stop

Variants tested:
  Baseline : no stop
  A        : also exit if RSI < 40  (RSI-based stop)
  B        : also exit if price drops 8%  (price stop)
"""

import os, sys, pickle, time
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore")

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)
os.chdir(PROJECT)

HIST = os.path.join(PROJECT, "data_store", "history")

# ── Indicator helpers ────────────────────────────────────────────────────────

def _ema(s, span):
    return s.ewm(span=span, adjust=False).mean()

def _rsi_s(close, period=14):
    d = close.diff()
    g = d.where(d > 0, 0.0).rolling(period, min_periods=period).mean()
    l = (-d.where(d < 0, 0.0)).rolling(period, min_periods=period).mean()
    rs = g / l.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)

def _macd_hist(close, fast=12, slow=26, sig=9):
    macd = _ema(close, fast) - _ema(close, slow)
    signal = _ema(macd, sig)
    return macd - signal          # histogram

def _supertrend(df, period=10, mult=3.0):
    """Returns boolean Series: True = bullish."""
    h = df["High"].astype(float)
    l = df["Low"].astype(float)
    c = df["Close"].astype(float)
    hl2 = (h + l) / 2
    pc  = c.shift(1)
    tr  = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    upper = hl2 + mult * atr
    lower = hl2 - mult * atr

    trend = pd.Series(True, index=c.index)
    for i in range(1, len(c)):
        prev_upper = float(upper.iloc[i-1])
        prev_lower = float(lower.iloc[i-1])
        cur_close  = float(c.iloc[i])
        prev_close = float(c.iloc[i-1])

        # Adjust bands
        if float(lower.iloc[i]) < prev_lower or prev_close < prev_lower:
            lower.iloc[i] = float(lower.iloc[i])
        else:
            lower.iloc[i] = prev_lower

        if float(upper.iloc[i]) > prev_upper or prev_close > prev_upper:
            upper.iloc[i] = float(upper.iloc[i])
        else:
            upper.iloc[i] = prev_upper

        # Trend
        if trend.iloc[i-1] and cur_close < float(lower.iloc[i]):
            trend.iloc[i] = False
        elif not trend.iloc[i-1] and cur_close > float(upper.iloc[i]):
            trend.iloc[i] = True
        else:
            trend.iloc[i] = trend.iloc[i-1]
    return trend

def _obv_rising(vol, close, lookback=15):
    """Returns boolean Series: True if OBV > OBV 15-bar avg."""
    sign = np.sign(close.diff().fillna(0))
    obv  = (sign * vol).cumsum()
    return obv > obv.rolling(lookback).mean()

def _vortex_bullish(df, period=14, threshold=0.07):
    """Returns boolean Series: True if VI+ > VI-  AND  (VI+ - VI-) > threshold."""
    h = df["High"].astype(float)
    l = df["Low"].astype(float)
    c = df["Close"].astype(float)
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    vm_plus  = (h - l.shift(1)).abs()
    vm_minus = (l - h.shift(1)).abs()
    vi_plus  = vm_plus.rolling(period).sum()  / tr.rolling(period).sum().replace(0, np.nan)
    vi_minus = vm_minus.rolling(period).sum() / tr.rolling(period).sum().replace(0, np.nan)
    return (vi_plus > vi_minus) & ((vi_plus - vi_minus) > threshold)

def _adx_s(df, period=14):
    h = df["High"].astype(float)
    l = df["Low"].astype(float)
    c = df["Close"].astype(float)
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    up = h.diff(); dn = -l.diff()
    pdm = ((up > dn) & (up > 0)) * up
    ndm = ((dn > up) & (dn > 0)) * dn
    atr = tr.rolling(period).mean()
    pdi = 100 * pdm.rolling(period).mean() / atr.replace(0, np.nan)
    ndi = 100 * ndm.rolling(period).mean() / atr.replace(0, np.nan)
    dx  = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
    return dx.rolling(period).mean().fillna(0)

# ── Entry signal ─────────────────────────────────────────────────────────────

def detect_entries(df):
    if len(df) < 250:
        return []

    c   = df["Close"].astype(float)
    h   = df["High"].astype(float)
    l   = df["Low"].astype(float)
    vol = df["Volume"].astype(float) if "Volume" in df.columns else pd.Series(1.0, index=df.index)

    rsi   = _rsi_s(c)
    e50   = _ema(c, 50)
    e200  = _ema(c, 200)
    adx   = _adx_s(df)
    mhist = _macd_hist(c)
    st    = _supertrend(df, period=10, mult=3.0)
    obv_r = _obv_rising(vol, c, lookback=15)
    vbull = _vortex_bullish(df, period=14, threshold=0.07)
    v_avg = vol.rolling(20).mean()

    entries = []
    for i in range(220, len(df)):
        close_i = float(c.iloc[i])

        # 1. Uptrend: price > EMA50 > EMA200
        if not (close_i > float(e50.iloc[i]) > float(e200.iloc[i])):
            continue
        # 2. ADX >= 20
        if float(adx.iloc[i]) < 20:
            continue
        # 3. MACD histogram > 0
        if float(mhist.iloc[i]) <= 0:
            continue
        # 4. Supertrend bullish
        if not bool(st.iloc[i]):
            continue
        # 5. OBV rising
        if not bool(obv_r.iloc[i]):
            continue
        # 6. Vortex bullish
        if not bool(vbull.iloc[i]):
            continue
        # 7. RSI in 52–70 range
        cur_rsi = float(rsi.iloc[i])
        if not (52 <= cur_rsi <= 70):
            continue
        # 8. RSI dipped below 50 in last 15 bars
        rsi_window = rsi.iloc[max(0, i - 15):i]
        if not (rsi_window < 50).any():
            continue
        # 9. Candle quality: close in top 50% of bar range
        bar_range = float(h.iloc[i]) - float(l.iloc[i])
        if bar_range > 0:
            quality = (close_i - float(l.iloc[i])) / bar_range * 100
            if quality < 50:
                continue
        # 10. Volume >= 1.1× 20-day avg
        avg_v = float(v_avg.iloc[i])
        if avg_v > 0 and float(vol.iloc[i]) < avg_v * 1.1:
            continue

        entries.append(i)
    return entries

# ── Trade simulator ───────────────────────────────────────────────────────────

def simulate(df, entry_idx, rsi_s, stop_rsi=None, stop_pct=None,
             exit_rsi=70.0, max_hold=60):
    c = df["Close"].astype(float)
    n = len(df)
    if entry_idx + 1 >= n:
        return None
    ep = float(c.iloc[entry_idx])
    if ep <= 0:
        return None
    stop_price = ep * (1 - stop_pct / 100) if stop_pct else None

    for hold in range(1, max_hold + 1):
        idx = entry_idx + hold
        if idx >= n:
            break
        cp  = float(c.iloc[idx])
        cr  = float(rsi_s.iloc[idx])

        if stop_price and cp <= stop_price:
            return {"outcome": "price_stop", "hold": hold,
                    "pnl_pct": round((cp - ep) / ep * 100, 3)}
        if stop_rsi and cr < stop_rsi:
            return {"outcome": "rsi_stop", "hold": hold,
                    "pnl_pct": round((cp - ep) / ep * 100, 3)}
        if cr >= exit_rsi:
            return {"outcome": "rsi_exit", "hold": hold,
                    "pnl_pct": round((cp - ep) / ep * 100, 3)}

    idx = min(entry_idx + max_hold, n - 1)
    cp  = float(c.iloc[idx])
    return {"outcome": "time_stop", "hold": max_hold,
            "pnl_pct": round((cp - ep) / ep * 100, 3)}

# ── Per-symbol runner ─────────────────────────────────────────────────────────

def run_sym(sym, stop_rsi=None, stop_pct=None):
    p = os.path.join(HIST, f"{sym}.pkl")
    if not os.path.exists(p):
        return []
    try:
        df  = pickle.load(open(p, "rb"))
        if not isinstance(df, pd.DataFrame) or len(df) < 300:
            return []
        c   = df["Close"].astype(float)
        rsi = _rsi_s(c)
        entries = detect_entries(df)
        trades  = []
        last    = -1
        for ei in entries:
            if ei <= last + 5:
                continue
            r = simulate(df, ei, rsi, stop_rsi=stop_rsi, stop_pct=stop_pct)
            if r:
                trades.append(r)
                last = ei + r["hold"]
        return trades
    except Exception:
        return []

# ── Stats printer ─────────────────────────────────────────────────────────────

def stats(trades, label):
    if not trades:
        print(f"  {label}: no trades found")
        return
    n     = len(trades)
    wins  = [t for t in trades if t["pnl_pct"] > 0]
    losses= [t for t in trades if t["pnl_pct"] <= 0]
    ev    = sum(t["pnl_pct"] for t in trades) / n
    wr    = len(wins) / n * 100
    aw    = sum(t["pnl_pct"] for t in wins)   / len(wins)   if wins   else 0
    al    = sum(t["pnl_pct"] for t in losses) / len(losses) if losses else 0
    ah    = sum(t["hold"]    for t in trades) / n
    by_o  = {}
    for t in trades:
        by_o[t["outcome"]] = by_o.get(t["outcome"], 0) + 1

    print(f"\n  ── {label} ──")
    print(f"  Trades    : {n}")
    print(f"  Win Rate  : {wr:.1f}%")
    print(f"  Avg Win   : +{aw:.2f}%")
    print(f"  Avg Loss  : {al:.2f}%")
    print(f"  Exp Value : {ev:+.3f}%/trade  ({'✓ POSITIVE' if ev > 0 else '✗ NEGATIVE'})")
    print(f"  Avg Hold  : {ah:.1f} bars")
    print(f"  Outcomes  : {dict(sorted(by_o.items()))}")
    return ev

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    syms = [f[:-4] for f in os.listdir(HIST) if f.endswith(".pkl")]
    syms = [s for s in syms if len(s) >= 3 and not any(
        s.endswith(x) for x in ('BEES','ETF','GOLD','SILVER','BOND','N50','N100'))]

    print(f"Running full DELAY-F technical signal on {len(syms)} symbols …")
    print("Filters: EMA trend + ADX + MACD hist + Supertrend + OBV + Vortex + RSI dip/cross + vol + candle")

    t0  = time.time()
    b_t = []; a_t = []; p_t = []

    for i, sym in enumerate(syms):
        if (i + 1) % 500 == 0:
            print(f"  … {i+1}/{len(syms)}  ({time.time()-t0:.0f}s)")
        b_t.extend(run_sym(sym))
        a_t.extend(run_sym(sym, stop_rsi=40.0))
        p_t.extend(run_sym(sym, stop_pct=8.0))

    print(f"\nDone in {time.time()-t0:.0f}s  |  Entry signals (baseline): {len(b_t)}")
    print(f"\n{'='*58}")
    print(f"  DELAY-F RSI70 — FULL TECHNICAL SIGNAL — SL COMPARISON")
    print(f"{'='*58}")
    print(f"  (Fundamentals excluded — only technical gates applied)")

    ev_b = stats(b_t, "Baseline   (no stop)          ")
    ev_a = stats(a_t, "Variant A  (RSI < 40 stop)    ")
    ev_p = stats(p_t, "Variant B  (price -8% stop)   ")

    print(f"\n{'='*58}")
    if ev_b is not None and ev_a is not None and ev_p is not None:
        print(f"  RSI stop vs baseline  : {ev_a - ev_b:+.3f}%/trade")
        print(f"  Price stop vs baseline: {ev_p - ev_b:+.3f}%/trade")

if __name__ == "__main__":
    main()
