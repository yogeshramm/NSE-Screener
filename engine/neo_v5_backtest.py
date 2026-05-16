"""
Neo v5 vs DELAY-F RSI70 — Head-to-Head Backtest  (O(N) per symbol)
Precomputes all indicator series once, then scans bars in a single pass.

Exit logic (same for both):
  SL = 2x ATR(14) below entry
  TP = 4x ATR(14) above entry
  Timeout = 30 bars

Usage:  python3 -m engine.neo_v5_backtest
"""
from __future__ import annotations
import math, pickle, statistics
from pathlib import Path
import numpy as np
import pandas as pd

HISTORY_DIR = Path(__file__).parent.parent / "data_store" / "history"
NIFTY500    = Path(__file__).parent.parent / "data" / "nifty500_live.txt"

TIMELINES = [
    ("2024-04-01", "2024-12-31", "TL1  Apr–Dec 2024"),
    ("2025-01-01", "2025-12-31", "TL2  Jan–Dec 2025"),
]
SL_ATR  = 2.0
TP_ATR  = 4.0
HOLD    = 30


# ── indicator series (computed once per symbol) ───────────────────────────────

def _rsi(c, p=14):
    d = c.diff()
    g = d.where(d>0,0.).ewm(alpha=1/p,min_periods=p,adjust=False).mean()
    l = (-d).where(d<0,0.).ewm(alpha=1/p,min_periods=p,adjust=False).mean()
    return 100 - 100/(1 + g/l.replace(0,np.nan))

def _macd(c):
    m = c.ewm(span=12,adjust=False).mean() - c.ewm(span=26,adjust=False).mean()
    s = m.ewm(span=9,adjust=False).mean()
    return m.values, s.values, (m-s).values  # macd, signal, hist

def _ao(h,l):
    med = (h+l)/2
    return (med.rolling(5).mean() - med.rolling(34).mean()).values

def _vortex(h,l,c,p=14):
    hp,lp,cp = h.shift(1),l.shift(1),c.shift(1)
    tr  = pd.concat([(h-l).abs(),(h-cp).abs(),(l-cp).abs()],axis=1).max(axis=1)
    vip = (h-lp).abs().rolling(p).sum() / tr.rolling(p).sum()
    vim = (l-hp).abs().rolling(p).sum() / tr.rolling(p).sum()
    return vip.values, vim.values

def _atr(h,l,c,p=14):
    cp = c.shift(1)
    tr = pd.concat([(h-l).abs(),(h-cp).abs(),(l-cp).abs()],axis=1).max(axis=1)
    return tr.ewm(alpha=1/p,min_periods=p,adjust=False).mean().values

def _supertrend(h,l,c,period=7,mult=3.0):
    cp  = c.shift(1)
    tr  = pd.concat([(h-l).abs(),(h-cp).abs(),(l-cp).abs()],axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/period,min_periods=period,adjust=False).mean().values
    hl2 = ((h+l)/2).values; cv = c.values; n = len(c)
    upper = hl2 + mult*atr; lower = hl2 - mult*atr
    fu = upper.copy(); fl = lower.copy()
    dir_ = np.ones(n,dtype=int); stv = np.full(n,np.nan)
    for i in range(1,n):
        if math.isnan(atr[i]): dir_[i]=dir_[i-1]; continue
        if not math.isnan(fu[i-1]):
            fu[i] = min(upper[i],fu[i-1]) if cv[i-1]<=fu[i-1] else upper[i]
        if not math.isnan(fl[i-1]):
            fl[i] = max(lower[i],fl[i-1]) if cv[i-1]>=fl[i-1] else lower[i]
        prev = dir_[i-1]
        if   prev== 1 and cv[i]<fl[i]: dir_[i]=-1
        elif prev==-1 and cv[i]>fu[i]: dir_[i]= 1
        else: dir_[i]=prev
        stv[i] = fl[i] if dir_[i]==1 else fu[i]
    return dir_, stv   # both np arrays


# ── signal arrays (True/False per bar after warmup) ──────────────────────────

def _build_neo_v5(df: pd.DataFrame):
    h,l,c = df["High"],df["Low"],df["Close"]
    n = len(df)

    st_dir, st_val = _supertrend(h,l,c)
    macd,sig,hist  = _macd(c)
    ao             = _ao(h,l)
    vip,vim        = _vortex(h,l,c)
    rsi            = _rsi(c).values
    atr            = _atr(h,l,c)
    cv             = c.values

    signals = np.zeros(n, dtype=bool)
    scores  = np.zeros(n, dtype=int)
    timings = np.zeros(n, dtype=int)

    for i in range(50, n):
        # C1: ST flipped +1 within 2 bars AND proximity < 10%
        c1 = False
        if st_dir[i] == 1:
            bars_since = None
            for j in range(i,max(i-5,-1),-1):
                if j>0 and st_dir[j-1]==-1:
                    bars_since = i-j+1; break
            if bars_since is not None and bars_since <= 2:
                if not math.isnan(st_val[i]) and st_val[i]>0:
                    prox = (cv[i]-st_val[i])/cv[i]
                    c1 = (prox <= 0.10)

        # C2: histogram positive + most recent hist neg→pos crossover was while macd<0
        # Look back 50 bars for crossover; if none found but macd currently ≤0, also valid.
        c2 = False
        if not math.isnan(hist[i]) and hist[i]>0:
            found_cross = False
            for j in range(i,max(i-50,-1),-1):
                if j>0 and hist[j]>0 and hist[j-1]<=0:
                    c2 = (not math.isnan(macd[j]) and macd[j]<0)
                    found_cross = True
                    break
            if not found_cross and not math.isnan(macd[i]) and macd[i]<=0:
                c2 = True

        # C3: AO crossed zero within ±2 bars OR slim-red rising
        c3 = False
        for j in range(i, max(i-3,-1), -1):
            if j>0 and not math.isnan(ao[j]) and not math.isnan(ao[j-1]):
                if ao[j]>0 and ao[j-1]<=0: c3=True; break
        if not c3 and i>0 and not math.isnan(ao[i]) and not math.isnan(ao[i-1]):
            if ao[i]<0 and ao[i]>ao[i-1] and abs(ao[i])<=abs(ao[i-1])*0.4:
                c3 = True

        # C4: VI+ crossed above VI- within ±1 bar, currently VI+>VI-
        c4 = False
        if (not math.isnan(vip[i]) and not math.isnan(vim[i]) and vip[i]>vim[i]):
            for j in range(i, max(i-2,-1), -1):
                if j>0 and not math.isnan(vip[j-1]) and not math.isnan(vim[j-1]):
                    if vip[j-1]<=vim[j-1]: c4=True; break

        # C5: RSI 48–60
        c5 = (not math.isnan(rsi[i]) and 48<=rsi[i]<=60)

        score = int(c1)+int(c2)+int(c3)+int(c4)+int(c5)
        if score < 4: continue

        # Timing score (max 10)
        t = 0
        if c1:
            bs = None
            for j in range(i,max(i-5,-1),-1):
                if j>0 and st_dir[j-1]==-1: bs=i-j+1; break
            t += 2 if bs==1 else 1
        if c2:
            t += 2 if (i>0 and hist[i-1]<=0) else 1
        if c3:
            t += 2 if (i>0 and ao[i]>0 and ao[i-1]<=0) else 1
        if c4:
            t += 2 if (i>0 and vip[i-1]<=vim[i-1] and vip[i]>vim[i]) else 1
        if c5:
            t += 2 if 50<=rsi[i]<=56 else 1

        signals[i] = True
        scores[i]  = score
        timings[i] = t

    return signals, scores, timings, atr


def _build_delay_f(df: pd.DataFrame):
    c   = df["Close"]
    n   = len(df)
    rsi = _rsi(c).values
    atr = _atr(df["High"],df["Low"],c)
    sig = np.zeros(n, dtype=bool)
    for i in range(20,n):
        rv = rsi[i]
        if math.isnan(rv) or not (52<=rv<=70): continue
        if math.isnan(rsi[i-1]) or rsi[i-1]>=52: continue  # no crossover
        window = rsi[max(0,i-16):i-1]
        if not any(not math.isnan(v) and v<50 for v in window): continue
        sig[i] = True
    return sig, atr


# ── trade simulation (single pass) ───────────────────────────────────────────

def _simulate(df: pd.DataFrame, signals: np.ndarray, atr: np.ndarray,
              start: str, end: str):
    cv = df["Close"].values; hv = df["High"].values; lv = df["Low"].values
    dates = df.index

    # date mask
    mask = (dates >= start) & (dates <= end)
    idx  = np.where(mask)[0]
    if len(idx) < 5: return []

    trades = []
    in_pos = False; ep=sl=tp=0.0; entry_bar=0; entry_date=None

    for i in idx:
        if not in_pos:
            if signals[i]:
                a = atr[i]
                if math.isnan(a) or a<=0: continue
                ep = cv[i]; sl = ep-SL_ATR*a; tp = ep+TP_ATR*a
                entry_bar=i; entry_date=dates[i]; in_pos=True
        else:
            xp=xr=None
            if lv[i]<=sl:              xp,xr=sl,"SL"
            elif hv[i]>=tp:            xp,xr=tp,"TP"
            elif (i-entry_bar)>=HOLD:  xp,xr=cv[i],"TO"
            if xp is not None:
                pnl=(xp-ep)/ep*100
                trades.append({"pnl":round(pnl,2),"reason":xr,
                                "hold":i-entry_bar,"entry":str(entry_date.date())})
                in_pos=False
    return trades


def _metrics(trades):
    if not trades:
        return dict(n=0,wr=0,avg=0,ev=0,aw=0,al=0,mdd=0,sh=0)
    pp=[t["pnl"] for t in trades]
    ws=[p for p in pp if p>0]; ls=[p for p in pp if p<=0]
    wr=len(ws)/len(pp)*100
    aw=statistics.mean(ws) if ws else 0
    al=statistics.mean(ls) if ls else 0
    ev=(wr/100*aw)+((1-wr/100)*al)
    cum=pk=1.0; mdd=0.0
    for p in pp:
        cum*=(1+p/100); pk=max(pk,cum)
        mdd=max(mdd,(pk-cum)/pk*100)
    sh=0
    try:
        if len(pp)>=2:
            sd=statistics.pstdev(pp)
            if sd>0: sh=round(statistics.mean(pp)/sd,2)
    except: pass
    return dict(n=len(pp),wr=round(wr,1),avg=round(statistics.mean(pp),2),
                ev=round(ev,2),aw=round(aw,2),al=round(al,2),
                mdd=round(mdd,1),sh=sh)


# ── main ──────────────────────────────────────────────────────────────────────

def run():
    syms = [s.strip() for s in open(NIFTY500).readlines() if s.strip()]
    print(f"Loaded {len(syms)} symbols\n")

    for (start,end,label) in TIMELINES:
        print(f"{'='*60}")
        print(f"  {label}  ({start} → {end})")
        print(f"{'='*60}")
        neo_trades=[]; df_trades=[]; skip=0; proc=0

        for sym in syms:
            p = HISTORY_DIR/f"{sym}.pkl"
            if not p.exists(): skip+=1; continue
            try:
                df = pickle.load(open(p,"rb"))
                df = df[~df.index.duplicated(keep="last")].sort_index()
                if len(df)<60: skip+=1; continue
            except: skip+=1; continue

            proc+=1
            neo_sig,neo_sc,neo_ti,neo_atr = _build_neo_v5(df)
            df_sig,df_atr               = _build_delay_f(df)

            neo_trades += _simulate(df, neo_sig, neo_atr, start, end)
            df_trades  += _simulate(df, df_sig,  df_atr,  start, end)

            if proc % 100 == 0:
                print(f"  ... {proc}/{len(syms)} processed")

        nm=_metrics(neo_trades); dm=_metrics(df_trades)
        print(f"\n{'Metric':<20} {'Neo v5':>10} {'DELAY-F RSI70':>14}")
        print(f"{'-'*46}")
        print(f"{'Total Trades':<20} {nm['n']:>10} {dm['n']:>14}")
        print(f"{'Win Rate %':<20} {nm['wr']:>10} {dm['wr']:>14}")
        print(f"{'Avg Return %':<20} {nm['avg']:>10} {dm['avg']:>14}")
        print(f"{'Avg Win %':<20} {nm['aw']:>10} {dm['aw']:>14}")
        print(f"{'Avg Loss %':<20} {nm['al']:>10} {dm['al']:>14}")
        print(f"{'EV per trade %':<20} {nm['ev']:>10} {dm['ev']:>14}")
        print(f"{'Max Drawdown %':<20} {nm['mdd']:>10} {dm['mdd']:>14}")
        print(f"{'Sharpe-ish':<20} {nm['sh']:>10} {dm['sh']:>14}")
        print(f"\n  Processed: {proc}  Skipped: {skip}")
        print()

if __name__=="__main__":
    run()
