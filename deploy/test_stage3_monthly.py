#!/usr/bin/env python3
"""
Backtest: Does adding a Stage 3 Monthly Filter improve accuracy?

Stage 1+2 Entry Signal (RSI70 formula — technical gates only):
  - Price > EMA50 > EMA200
  - ADX >= 20
  - MACD histogram > 0
  - Supertrend bullish (period=10, mult=3.0)
  - OBV rising (OBV > 15-bar avg)
  - Vortex bullish (VI+ > VI-, delta > 0.07)
  - RSI dipped < 50 in last 15 bars, now 52–70
  - Candle closes in top 50% of bar range
  - Volume >= 1.1× 20-day avg

Stage 3 Monthly Filter (NEW — what we're testing):
  - Monthly price > rising 10-month SMA
  - Monthly RSI > 50
  - Monthly MACD histogram > 0
  - Monthly Supertrend bullish (period=3, mult=2.0)

Exit: RSI > 70  OR  60-bar time stop

Output: Side-by-side stats for Stage 1+2 vs Stage 1+2+3
"""

import os, sys, pickle, time
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore")

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)
os.chdir(PROJECT)

HIST     = os.path.join(PROJECT, "data_store", "history")
N500_TXT = os.path.join(PROJECT, "data", "nifty500_live.txt")

# ── Daily indicator helpers ───────────────────────────────────────────────────

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
    return macd - _ema(macd, sig)

def _supertrend(df, period=10, mult=3.0):
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
        pu = float(upper.iloc[i-1]); pl = float(lower.iloc[i-1])
        cc = float(c.iloc[i]);       pc_ = float(c.iloc[i-1])
        lower.iloc[i] = float(lower.iloc[i]) if float(lower.iloc[i]) < pl or pc_ < pl else pl
        upper.iloc[i] = float(upper.iloc[i]) if float(upper.iloc[i]) > pu or pc_ > pu else pu
        if   trend.iloc[i-1] and cc < float(lower.iloc[i]): trend.iloc[i] = False
        elif not trend.iloc[i-1] and cc > float(upper.iloc[i]): trend.iloc[i] = True
        else: trend.iloc[i] = trend.iloc[i-1]
    return trend

def _obv_rising(vol, close, lookback=15):
    sign = np.sign(close.diff().fillna(0))
    obv  = (sign * vol).cumsum()
    return obv > obv.rolling(lookback).mean()

def _vortex_bullish(df, period=14, threshold=0.07):
    h = df["High"].astype(float); l = df["Low"].astype(float); c = df["Close"].astype(float)
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    vm_plus  = (h - l.shift(1)).abs()
    vm_minus = (l - h.shift(1)).abs()
    vi_plus  = vm_plus.rolling(period).sum()  / tr.rolling(period).sum().replace(0, np.nan)
    vi_minus = vm_minus.rolling(period).sum() / tr.rolling(period).sum().replace(0, np.nan)
    return (vi_plus > vi_minus) & ((vi_plus - vi_minus) > threshold)

def _adx_s(df, period=14):
    h = df["High"].astype(float); l = df["Low"].astype(float); c = df["Close"].astype(float)
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

# ── Monthly indicator helpers ─────────────────────────────────────────────────

def _build_monthly(df):
    """Resample daily OHLCV → monthly bars."""
    return df.resample('ME').agg(
        Open=('Open', 'first'), High=('High', 'max'),
        Low=('Low', 'min'),   Close=('Close', 'last'),
        Volume=('Volume', 'sum')
    ).dropna(subset=['Close'])

def _monthly_supertrend(mdf, period=3, mult=2.0):
    """Supertrend on monthly bars (faster settings — each bar = 1 month)."""
    h = mdf["High"].astype(float); l = mdf["Low"].astype(float); c = mdf["Close"].astype(float)
    hl2 = (h + l) / 2; pc = c.shift(1)
    tr  = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    upper = hl2 + mult * atr; lower = hl2 - mult * atr
    trend = pd.Series(True, index=c.index)
    for i in range(1, len(c)):
        pu = float(upper.iloc[i-1]); pl = float(lower.iloc[i-1])
        cc = float(c.iloc[i]);       pc_ = float(c.iloc[i-1])
        lower.iloc[i] = float(lower.iloc[i]) if float(lower.iloc[i]) < pl or pc_ < pl else pl
        upper.iloc[i] = float(upper.iloc[i]) if float(upper.iloc[i]) > pu or pc_ > pu else pu
        if   trend.iloc[i-1] and cc < float(lower.iloc[i]): trend.iloc[i] = False
        elif not trend.iloc[i-1] and cc > float(upper.iloc[i]): trend.iloc[i] = True
        else: trend.iloc[i] = trend.iloc[i-1]
    return trend

def _check_stage3(mdf_full, as_of_date):
    """
    Returns True if all monthly Stage 3 conditions pass.
    Uses only COMPLETED monthly bars strictly before as_of_date.
    """
    m = mdf_full[mdf_full.index < as_of_date]
    if len(m) < 14:          # need enough bars for indicators
        return False

    c = m["Close"].astype(float)

    # 1. Price above rising 10-month SMA
    sma10 = c.rolling(10).mean()
    if sma10.iloc[-1] != sma10.iloc[-1]:   # NaN guard
        return False
    if float(c.iloc[-1]) <= float(sma10.iloc[-1]):
        return False
    if float(sma10.iloc[-1]) <= float(sma10.iloc[-2]):   # SMA must be rising
        return False

    # 2. Monthly RSI > 50
    if float(_rsi_s(c).iloc[-1]) <= 50:
        return False

    # 3. Monthly MACD histogram > 0
    if float(_macd_hist(c).iloc[-1]) <= 0:
        return False

    # 4. Monthly Supertrend bullish
    if not bool(_monthly_supertrend(m).iloc[-1]):
        return False

    return True

# ── Stage 1+2 daily entry detection ──────────────────────────────────────────

def detect_entries(df):
    if len(df) < 250:
        return []
    c   = df["Close"].astype(float)
    h   = df["High"].astype(float)
    l   = df["Low"].astype(float)
    vol = df["Volume"].astype(float) if "Volume" in df.columns else pd.Series(1.0, index=df.index)
    rsi   = _rsi_s(c)
    e50   = _ema(c, 50);  e200 = _ema(c, 200)
    adx   = _adx_s(df)
    mhist = _macd_hist(c)
    st    = _supertrend(df, period=10, mult=3.0)
    obv_r = _obv_rising(vol, c, lookback=15)
    vbull = _vortex_bullish(df)
    v_avg = vol.rolling(20).mean()
    entries = []
    for i in range(220, len(df)):
        ci = float(c.iloc[i])
        if not (ci > float(e50.iloc[i]) > float(e200.iloc[i])): continue
        if float(adx.iloc[i]) < 20:                             continue
        if float(mhist.iloc[i]) <= 0:                           continue
        if not bool(st.iloc[i]):                                continue
        if not bool(obv_r.iloc[i]):                             continue
        if not bool(vbull.iloc[i]):                             continue
        cr = float(rsi.iloc[i])
        if not (52 <= cr <= 70):                                continue
        if not (rsi.iloc[max(0,i-15):i] < 50).any():           continue
        br = float(h.iloc[i]) - float(l.iloc[i])
        if br > 0 and (ci - float(l.iloc[i])) / br * 100 < 50: continue
        av = float(v_avg.iloc[i])
        if av > 0 and float(vol.iloc[i]) < av * 1.1:           continue
        entries.append(i)
    return entries

# ── Trade simulator ───────────────────────────────────────────────────────────

def simulate(df, entry_idx, rsi_s, exit_rsi=70.0, max_hold=60):
    c = df["Close"].astype(float); n = len(df)
    if entry_idx + 1 >= n: return None
    ep = float(c.iloc[entry_idx])
    if ep <= 0: return None
    for hold in range(1, max_hold + 1):
        idx = entry_idx + hold
        if idx >= n: break
        cp = float(c.iloc[idx]); cr = float(rsi_s.iloc[idx])
        if cr >= exit_rsi:
            return {"outcome": "target_hit", "hold": hold,
                    "pnl_pct": round((cp - ep) / ep * 100, 3)}
    idx = min(entry_idx + max_hold, n - 1)
    return {"outcome": "time_stop", "hold": max_hold,
            "pnl_pct": round((float(c.iloc[idx]) - ep) / ep * 100, 3)}

# ── Per-symbol runner ─────────────────────────────────────────────────────────

def run_sym(sym):
    p = os.path.join(HIST, f"{sym}.pkl")
    if not os.path.exists(p):
        return [], []
    try:
        df = pickle.load(open(p, "rb"))
        if not isinstance(df, pd.DataFrame) or len(df) < 300:
            return [], []
        if not isinstance(df.index, pd.DatetimeIndex):
            return [], []

        c       = df["Close"].astype(float)
        rsi     = _rsi_s(c)
        entries = detect_entries(df)
        mdf     = _build_monthly(df)          # monthly bars — built once per symbol

        base_trades = []; filt_trades = []
        last_b = -1;      last_f = -1

        for ei in entries:
            # ── Baseline: Stage 1+2 only ──
            if ei > last_b + 5:
                r = simulate(df, ei, rsi)
                if r:
                    base_trades.append(r)
                    last_b = ei + r["hold"]

            # ── Filtered: Stage 1+2+3 ──
            if ei > last_f + 5:
                entry_date = df.index[ei]
                if _check_stage3(mdf, entry_date):
                    r = simulate(df, ei, rsi)
                    if r:
                        filt_trades.append(r)
                        last_f = ei + r["hold"]

        return base_trades, filt_trades
    except Exception:
        return [], []

# ── Stats printer ─────────────────────────────────────────────────────────────

def stats(trades, label):
    if not trades:
        print(f"  {label}: no trades found")
        return None, None
    n      = len(trades)
    wins   = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] <= 0]
    hits   = [t for t in trades if t["outcome"] == "target_hit"]
    ev     = sum(t["pnl_pct"] for t in trades) / n
    wr     = len(wins) / n * 100
    thr    = len(hits)  / n * 100
    aw     = sum(t["pnl_pct"] for t in wins)   / len(wins)   if wins   else 0
    al     = sum(t["pnl_pct"] for t in losses) / len(losses) if losses else 0
    ah     = sum(t["hold"]    for t in trades) / n
    print(f"\n  ── {label} ──")
    print(f"  Total Trades : {n}")
    print(f"  Win Rate     : {wr:.1f}%   (closed with PnL > 0)")
    print(f"  Target Hit   : {thr:.1f}%   (RSI > 70 exit — actual target reached)")
    print(f"  Avg Win      : +{aw:.2f}%")
    print(f"  Avg Loss     : {al:.2f}%")
    print(f"  Exp Value    : {ev:+.3f}%/trade  ({'✓ POSITIVE' if ev > 0 else '✗ NEGATIVE'})")
    print(f"  Avg Hold     : {ah:.1f} bars (~{ah/5:.1f} weeks)")
    return wr, ev

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    # Load Nifty 500 list
    if os.path.exists(N500_TXT):
        with open(N500_TXT) as f:
            syms = [ln.strip() for ln in f if ln.strip()]
        print(f"Symbols  : Nifty 500 ({len(syms)} stocks)")
    else:
        syms = [f[:-4] for f in os.listdir(HIST) if f.endswith(".pkl")]
        syms = [s for s in syms if len(s) >= 3 and not any(
            s.endswith(x) for x in ('BEES','ETF','GOLD','SILVER','BOND','N50','N100'))]
        print(f"Symbols  : All available ({len(syms)} stocks — nifty500_live.txt not found)")

    print(f"Strategy : RSI70 formula (Stage 1+2) vs RSI70 + Monthly filter (Stage 1+2+3)")
    print(f"Entry    : EMA trend + ADX>=20 + MACD hist + Supertrend + OBV + Vortex + RSI dip-cross + vol")
    print(f"Stage 3  : Monthly 10m-SMA rising + RSI>50 + MACD>0 + Supertrend green")
    print(f"Exit     : RSI > 70 (target)  OR  60-bar time stop")
    print(f"{'─'*60}")

    t0 = time.time()
    all_base = []; all_filt = []

    for i, sym in enumerate(syms):
        if (i + 1) % 100 == 0:
            elapsed = time.time() - t0
            eta = elapsed / (i + 1) * (len(syms) - i - 1)
            print(f"  … {i+1}/{len(syms)}  base={len(all_base)}  filt={len(all_filt)}  "
                  f"({elapsed:.0f}s elapsed, ~{eta:.0f}s remaining)")
        b, f = run_sym(sym)
        all_base.extend(b)
        all_filt.extend(f)

    elapsed = time.time() - t0
    print(f"\nCompleted in {elapsed:.0f}s")

    # ── Results ──────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  STAGE 3 MONTHLY FILTER — BACKTEST RESULTS")
    print(f"  Nifty 500 · Full history · All market conditions")
    print(f"{'='*60}")

    wr_b, ev_b = stats(all_base, "Stage 1+2 only (baseline)        ")
    wr_f, ev_f = stats(all_filt, "Stage 1+2 + Stage 3 monthly filter")

    if wr_b is not None and wr_f is not None:
        n_b = len(all_base); n_f = len(all_filt)
        filtered_out = n_b - n_f
        pct_filtered = filtered_out / n_b * 100 if n_b else 0
        print(f"\n{'='*60}")
        print(f"  VERDICT")
        print(f"{'='*60}")
        print(f"  Trades (baseline)      : {n_b}")
        print(f"  Trades (with Stage 3)  : {n_f}  ({pct_filtered:.1f}% filtered out)")
        print(f"  Win rate change        : {wr_f - wr_b:+.1f}%  ({wr_b:.1f}% → {wr_f:.1f}%)")
        print(f"  Exp value change       : {ev_f - ev_b:+.3f}%/trade")
        print(f"{'─'*60}")
        if wr_f > wr_b + 2:
            print(f"  ✓ Stage 3 IMPROVES accuracy by {wr_f - wr_b:.1f}% win rate")
            print(f"    Worth adding — filters low-quality setups effectively")
        elif wr_f > wr_b:
            print(f"  ~ Stage 3 has marginal improvement ({wr_f - wr_b:.1f}%)")
            print(f"    Consider if trade reduction ({pct_filtered:.0f}% fewer) is acceptable")
        else:
            print(f"  ✗ Stage 3 does NOT improve accuracy ({wr_f - wr_b:+.1f}% change)")
            print(f"    Monthly filter filters valid trades without improving quality")
        print(f"{'='*60}")

if __name__ == "__main__":
    main()
