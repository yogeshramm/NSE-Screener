"""
Breakout scanner — 4 modes targeted at swing traders.

pre_breakout : consolidating, near 52W high, volume dry-up — about to breakout
fresh        : broke out TODAY (52W high / BB upper) with volume spike
pullback     : recently broke out, now pulling back to SMA 20 / 50 support
peg          : Power Earnings Gap (O'Neil) — big up move on earnings with volume
"""

import os
import pickle
import pandas as pd
import numpy as np
from typing import List, Dict, Any


HISTORY_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store", "history")


def _load(sym: str):
    fpath = os.path.join(HISTORY_DIR, f"{sym}.pkl")
    if not os.path.exists(fpath):
        return None
    try:
        df = pickle.load(open(fpath, "rb"))
        df = df[~df.index.duplicated(keep="last")]
        return df
    except Exception:
        return None


def _atr(df, period=14):
    high, low, close = df["High"], df["Low"], df["Close"]
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, min_periods=period).mean()


def _rsi(closes, period=14):
    d = closes.diff()
    g = d.where(d > 0, 0.0).ewm(alpha=1/period, min_periods=period).mean()
    l = (-d).where(d < 0, 0.0).ewm(alpha=1/period, min_periods=period).mean()
    rs = g / l.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _adx(df, period=14):
    high, low, close = df["High"], df["Low"], df["Close"]
    up = high.diff()
    down = -low.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr = pd.Series(tr).ewm(alpha=1/period, min_periods=period).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1/period, min_periods=period).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1/period, min_periods=period).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1/period, min_periods=period).mean()


def _metrics(df):
    closes = df["Close"]
    n = len(df)
    if n < 60:
        return None
    last = float(closes.iloc[-1])
    # 52W stats (use last 252 bars)
    w = df.tail(252)
    w52_high = float(w["High"].max())
    w52_low = float(w["Low"].min())
    pct_from_high = (last - w52_high) / w52_high * 100
    pct_from_low = (last - w52_low) / w52_low * 100
    # Averages
    avg_vol = float(df["Volume"].tail(20).mean())
    last_vol = float(df["Volume"].iloc[-1])
    vol_ratio = last_vol / avg_vol if avg_vol > 0 else 1.0
    # Bollinger 20,2
    sma20 = closes.rolling(20).mean()
    std20 = closes.rolling(20).std()
    bb_upper = sma20 + 2 * std20
    bb_width = ((bb_upper - (sma20 - 2 * std20)) / sma20).iloc[-1]
    bb_width_avg = ((bb_upper - (sma20 - 2 * std20)) / sma20).tail(20).mean()
    sma50 = closes.rolling(50).mean() if n >= 50 else None
    # RSI & ADX
    rsi14 = _rsi(closes).iloc[-1]
    adx14 = _adx(df).iloc[-1] if n >= 28 else None
    return {
        "last": last,
        "w52_high": w52_high,
        "w52_low": w52_low,
        "pct_from_high": pct_from_high,
        "pct_from_low": pct_from_low,
        "avg_vol": avg_vol,
        "last_vol": last_vol,
        "vol_ratio": vol_ratio,
        "bb_upper": float(bb_upper.iloc[-1]) if not pd.isna(bb_upper.iloc[-1]) else None,
        "bb_width": float(bb_width) if not pd.isna(bb_width) else None,
        "bb_width_avg": float(bb_width_avg) if not pd.isna(bb_width_avg) else None,
        "sma20": float(sma20.iloc[-1]) if not pd.isna(sma20.iloc[-1]) else None,
        "sma50": float(sma50.iloc[-1]) if sma50 is not None and not pd.isna(sma50.iloc[-1]) else None,
        "rsi14": float(rsi14) if not pd.isna(rsi14) else None,
        "adx14": float(adx14) if adx14 is not None and not pd.isna(adx14) else None,
    }


def scan(mode: str, symbols: List[str]) -> List[Dict[str, Any]]:
    """Scan for a given mode and return a ranked list of hits."""
    results = []
    for sym in symbols:
        df = _load(sym)
        if df is None or len(df) < 60:
            continue
        try:
            m = _metrics(df)
            if not m:
                continue
            hit = None
            score = 0

            if mode == "pre_breakout":
                # Within 4% of 52W high, BB width contracting, volume drying up, RSI 55-70, ADX rising
                if m["pct_from_high"] >= -4.0 and m["pct_from_high"] <= 0:
                    if m["bb_width"] is not None and m["bb_width_avg"] is not None and m["bb_width"] < m["bb_width_avg"] * 0.8:
                        if m["vol_ratio"] < 0.85 and 50 <= (m["rsi14"] or 0) <= 70:
                            score = int(100 * (1 + m["pct_from_high"] / 4) * (m["bb_width_avg"] / max(m["bb_width"], 0.001)) * 0.4)
                            hit = {
                                "symbol": sym,
                                "close": round(m["last"], 2),
                                "pct_from_high": round(m["pct_from_high"], 2),
                                "bb_squeeze": round((1 - m["bb_width"] / m["bb_width_avg"]) * 100, 1) if m["bb_width_avg"] else None,
                                "vol_ratio": round(m["vol_ratio"], 2),
                                "rsi": round(m["rsi14"], 1) if m["rsi14"] else None,
                                "score": score,
                            }
            elif mode == "fresh":
                # Broke 52W high in last 3 bars OR broke BB upper with 1.3x+ volume today
                last3_high = float(df["High"].iloc[-3:].max())
                prev_w52_high = float(df["High"].iloc[-255:-3].max()) if len(df) >= 255 else m["w52_high"]
                broke_52w = last3_high > prev_w52_high and m["pct_from_high"] >= -0.5
                broke_bb = m["bb_upper"] is not None and m["last"] > m["bb_upper"] * 0.995 and m["vol_ratio"] >= 1.3
                if broke_52w or broke_bb:
                    tag = "52W High" if broke_52w else "BB Upper"
                    score = int(m["vol_ratio"] * 30 + (50 if broke_52w else 25))
                    hit = {
                        "symbol": sym,
                        "close": round(m["last"], 2),
                        "trigger": tag,
                        "w52_high": round(m["w52_high"], 2),
                        "vol_ratio": round(m["vol_ratio"], 2),
                        "rsi": round(m["rsi14"], 1) if m["rsi14"] else None,
                        "score": score,
                    }
            elif mode == "pullback":
                # Broke 52W high sometime in last 20 bars, now pulled back toward SMA 20 (within 3%)
                last20_high = float(df["High"].iloc[-20:].max())
                older_high = float(df["High"].iloc[-252:-20].max()) if len(df) >= 252 else m["w52_high"]
                had_breakout = last20_high > older_high * 0.99
                if had_breakout and m["sma20"]:
                    dist_to_sma = (m["last"] - m["sma20"]) / m["sma20"] * 100
                    if -1.0 <= dist_to_sma <= 3.0 and m["last"] >= m["sma20"] * 0.97:
                        score = int(100 - abs(dist_to_sma) * 10 - max(0, (60 - (m["rsi14"] or 50))) * 0.5)
                        hit = {
                            "symbol": sym,
                            "close": round(m["last"], 2),
                            "recent_high": round(last20_high, 2),
                            "sma20": round(m["sma20"], 2),
                            "dist_to_sma20": round(dist_to_sma, 2),
                            "rsi": round(m["rsi14"], 1) if m["rsi14"] else None,
                            "score": max(0, score),
                        }
            elif mode == "peg":
                # Power Earnings Gap: today's move >= 4%, volume >= 2x avg
                if len(df) >= 2:
                    prev_close = float(df["Close"].iloc[-2])
                    move_pct = (m["last"] - prev_close) / prev_close * 100
                    if move_pct >= 4.0 and m["vol_ratio"] >= 2.0:
                        score = int(move_pct * 5 + m["vol_ratio"] * 15)
                        hit = {
                            "symbol": sym,
                            "close": round(m["last"], 2),
                            "move_pct": round(move_pct, 2),
                            "vol_ratio": round(m["vol_ratio"], 2),
                            "rsi": round(m["rsi14"], 1) if m["rsi14"] else None,
                            "score": score,
                        }

            if hit:
                results.append(hit)
        except Exception:
            continue

    results.sort(key=lambda h: h.get("score", 0), reverse=True)
    return results[:100]
