"""
Simple backtester: runs a rule-based strategy on one symbol's history.

Strategy spec:
- entry: {indicator, condition, value}   e.g. {"indicator":"rsi","condition":"below","value":30}
- exit:  same shape OR None (use fixed SL/TP)
- sl_pct, tp_pct: optional percent-based stop/target
- hold_bars: max bars to hold before forced exit (default 20)

Returns: list of trades + aggregate metrics (win rate, total P&L, max DD, Sharpe-ish, avg hold).
"""

import os
import pickle
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional


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


# ---------- Indicator computation (kept minimal) ----------
def _rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    d = closes.diff()
    g = d.where(d > 0, 0.0).ewm(alpha=1/period, min_periods=period).mean()
    l = (-d).where(d < 0, 0.0).ewm(alpha=1/period, min_periods=period).mean()
    rs = g / l.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _sma(closes: pd.Series, period: int) -> pd.Series:
    return closes.rolling(period).mean()


def _ema(closes: pd.Series, period: int) -> pd.Series:
    return closes.ewm(span=period, adjust=False).mean()


def _macd(closes: pd.Series):
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd, signal


def _build_indicator_series(df: pd.DataFrame, indicator: str) -> pd.Series:
    c = df["Close"]
    if indicator == "rsi":           return _rsi(c, 14)
    if indicator == "price_vs_sma20": return (c / _sma(c, 20) - 1) * 100
    if indicator == "price_vs_sma50": return (c / _sma(c, 50) - 1) * 100
    if indicator == "price_vs_ema50": return (c / _ema(c, 50) - 1) * 100
    if indicator == "macd":          return _macd(c)[0]
    if indicator == "macd_hist":     return _macd(c)[0] - _macd(c)[1]
    if indicator == "pct_change":
        return c.pct_change() * 100
    if indicator == "volume_ratio":
        return df["Volume"] / df["Volume"].rolling(20).mean()
    if indicator == "close":         return c
    # Default: close
    return c


def _cond_met(prev_v, curr_v, condition: str, value: float) -> bool:
    try:
        if pd.isna(curr_v):
            return False
        if condition == "above":       return curr_v > value
        if condition == "below":       return curr_v < value
        if condition == "cross_above": return not pd.isna(prev_v) and prev_v <= value < curr_v
        if condition == "cross_below": return not pd.isna(prev_v) and prev_v >= value > curr_v
    except Exception:
        return False
    return False


def run_backtest(symbol: str, entry_rule: Dict[str, Any], exit_rule: Optional[Dict[str, Any]] = None,
                 sl_pct: Optional[float] = None, tp_pct: Optional[float] = None,
                 hold_bars: int = 20, start_date: Optional[str] = None,
                 end_date: Optional[str] = None) -> Dict[str, Any]:
    df = _load(symbol)
    if df is None or len(df) < 50:
        return {"error": f"Insufficient history for {symbol}"}

    if start_date:
        df = df[df.index >= start_date]
    if end_date:
        df = df[df.index <= end_date]
    if len(df) < 30:
        return {"error": "Date range too narrow (need ≥30 bars)"}

    entry_ind = entry_rule.get("indicator", "rsi")
    exit_ind = (exit_rule or {}).get("indicator")
    entry_series = _build_indicator_series(df, entry_ind)
    exit_series = _build_indicator_series(df, exit_ind) if exit_ind else None

    closes = df["Close"].values
    highs = df["High"].values
    lows = df["Low"].values
    idx = df.index

    trades: List[Dict[str, Any]] = []
    in_pos = False
    entry_price = 0.0
    entry_bar = -1
    entry_idx_date = None

    for i in range(1, len(df)):
        if not in_pos:
            ev = entry_series.iloc[i] if not isinstance(entry_series, np.ndarray) else entry_series[i]
            pv = entry_series.iloc[i - 1] if not isinstance(entry_series, np.ndarray) else entry_series[i - 1]
            if _cond_met(pv, ev, entry_rule.get("condition", "below"), float(entry_rule.get("value", 30))):
                in_pos = True
                entry_price = float(closes[i])
                entry_bar = i
                entry_idx_date = idx[i]
        else:
            exit_now = False
            exit_reason = None
            exit_price = float(closes[i])

            # SL / TP intra-bar (pessimistic: SL first)
            if sl_pct is not None:
                sl_level = entry_price * (1 - sl_pct / 100)
                if lows[i] <= sl_level:
                    exit_now, exit_reason, exit_price = True, "SL", sl_level
            if not exit_now and tp_pct is not None:
                tp_level = entry_price * (1 + tp_pct / 100)
                if highs[i] >= tp_level:
                    exit_now, exit_reason, exit_price = True, "TP", tp_level

            # Exit rule
            if not exit_now and exit_series is not None:
                ev = exit_series.iloc[i]
                pv = exit_series.iloc[i - 1]
                if _cond_met(pv, ev, exit_rule.get("condition", "above"), float(exit_rule.get("value", 70))):
                    exit_now, exit_reason = True, "Rule"

            # Hold-bar timeout
            if not exit_now and (i - entry_bar) >= hold_bars:
                exit_now, exit_reason = True, "Timeout"

            if exit_now:
                pnl_pct = (exit_price - entry_price) / entry_price * 100
                trades.append({
                    "entry_date": entry_idx_date.strftime("%Y-%m-%d") if hasattr(entry_idx_date, "strftime") else str(entry_idx_date),
                    "exit_date": idx[i].strftime("%Y-%m-%d") if hasattr(idx[i], "strftime") else str(idx[i]),
                    "entry_price": round(entry_price, 2),
                    "exit_price": round(float(exit_price), 2),
                    "hold_bars": i - entry_bar,
                    "pnl_pct": round(pnl_pct, 2),
                    "reason": exit_reason,
                })
                in_pos = False

    # Metrics
    if not trades:
        return {"symbol": symbol, "trades": [], "total_trades": 0, "message": "No trades triggered."}

    pcts = [t["pnl_pct"] for t in trades]
    wins = [p for p in pcts if p > 0]
    total_pct = sum(pcts)
    # Running cumulative return (compounded)
    cumulative = 1.0
    peak = 1.0
    max_dd = 0.0
    for p in pcts:
        cumulative *= (1 + p / 100)
        if cumulative > peak:
            peak = cumulative
        dd = (peak - cumulative) / peak * 100
        if dd > max_dd:
            max_dd = dd
    # Buy-and-hold comparison
    bh_pct = (closes[-1] - closes[0]) / closes[0] * 100 if closes[0] else 0
    # Sharpe-ish
    import statistics
    sharpe = None
    try:
        if len(pcts) >= 2:
            sd = statistics.pstdev(pcts)
            if sd > 0:
                sharpe = round(statistics.mean(pcts) / sd, 2)
    except Exception:
        pass

    return {
        "symbol": symbol,
        "total_trades": len(trades),
        "winning_trades": len(wins),
        "win_rate": round(len(wins) / len(trades) * 100, 1),
        "total_pnl_pct": round(total_pct, 2),
        "compounded_return_pct": round((cumulative - 1) * 100, 2),
        "avg_pnl_pct": round(sum(pcts) / len(pcts), 2),
        "best_trade_pct": round(max(pcts), 2),
        "worst_trade_pct": round(min(pcts), 2),
        "avg_hold_bars": round(sum(t["hold_bars"] for t in trades) / len(trades), 1),
        "max_drawdown_pct": round(max_dd, 2),
        "buy_hold_pct": round(bh_pct, 2),
        "alpha_pct": round(total_pct - bh_pct, 2),
        "sharpe": sharpe,
        "trades": trades,
    }
