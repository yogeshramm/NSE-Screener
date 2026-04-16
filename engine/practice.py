"""
Practice Game Engine — Candle-by-candle trading simulation with real historical data.
Purse: ₹1,00,000 per session. Max 60 days per round.
"""

import os
import pickle
import random
import math
from datetime import datetime


HISTORY_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store", "history")
PURSE_SIZE = 100000  # ₹1,00,000
MAX_DAYS = 60
MIN_HISTORY = 120  # Need at least 120 bars (60 for warmup + 60 for game)


def get_available_stocks(universe="nifty500"):
    """Get stock symbols available for practice."""
    from data.nse_symbols import get_nifty500_live, NIFTY_500_FALLBACK

    # All stocks with history
    all_hist = set()
    if os.path.exists(HISTORY_DIR):
        all_hist = {f.replace('.pkl', '') for f in os.listdir(HISTORY_DIR) if f.endswith('.pkl')}

    if universe == "nifty500":
        try:
            nifty = set(get_nifty500_live())
        except Exception:
            nifty = set(NIFTY_500_FALLBACK)
        return sorted(all_hist & nifty)
    else:
        # "next500" — stocks NOT in Nifty 500 but in our history
        try:
            nifty = set(get_nifty500_live())
        except Exception:
            nifty = set(NIFTY_500_FALLBACK)
        return sorted(all_hist - nifty)


def start_round(symbol=None, universe="nifty500"):
    """
    Start a new practice round.
    Returns: game state dict with first batch of warmup candles.
    """
    stocks = get_available_stocks(universe)
    if not stocks:
        return {"error": "No stocks available for practice"}

    # Pick random stock if not specified
    if not symbol:
        random.shuffle(stocks)
        symbol = None
        for s in stocks:
            try:
                df = _load_history(s)
                if df is not None and len(df) >= MIN_HISTORY:
                    symbol = s
                    break
            except Exception:
                continue
        if not symbol:
            return {"error": "No stocks with enough history found"}
    else:
        symbol = symbol.upper()

    df = _load_history(symbol)
    if df is None or len(df) < MIN_HISTORY:
        return {"error": f"{symbol} has insufficient history ({len(df) if df is not None else 0} bars, need {MIN_HISTORY})"}

    # Pick random start point (need 60 warmup bars before + 60 game bars after)
    max_start = len(df) - MAX_DAYS - 1
    warmup_bars = 60
    min_start = warmup_bars
    if max_start <= min_start:
        return {"error": f"{symbol} doesn't have enough data for a full game"}

    start_idx = random.randint(min_start, max_start)

    # Build warmup candles (visible from start) + hidden future candles
    warmup = _build_candles(df, start_idx - warmup_bars, start_idx)
    all_future = _build_candles(df, start_idx, min(start_idx + MAX_DAYS, len(df)))

    # Compute indicators for warmup candles
    warmup_df = df.iloc[start_idx - warmup_bars:start_idx]
    indicators = _compute_indicators(warmup_df)

    difficulty = _compute_difficulty(df, start_idx)

    return {
        "symbol": symbol,
        "universe": universe,
        "difficulty": difficulty,
        "purse": PURSE_SIZE,
        "max_days": MAX_DAYS,
        "day": 0,
        "warmup_candles": warmup,
        "warmup_volumes": _build_volumes(df, start_idx - warmup_bars, start_idx),
        "indicators": indicators,
        "future_candles": all_future,  # Server holds this — NOT sent to frontend
        "future_volumes": _build_volumes(df, start_idx, min(start_idx + MAX_DAYS, len(df))),
        "trades": [],
        "position": None,  # {entry_price, qty, entry_day}
        "cash": PURSE_SIZE,
        "start_idx": start_idx,
        "total_bars": len(all_future),
    }


def next_day(game_state):
    """
    Reveal next candle. Returns the new candle + updated indicators.
    """
    day = game_state["day"]
    if day >= len(game_state["future_candles"]):
        return {"error": "No more days available", "game_over": True}

    candle = game_state["future_candles"][day]
    volume = game_state["future_volumes"][day]
    game_state["day"] = day + 1

    # Recompute indicators including this new candle
    # (We send all visible candles' indicator data)
    all_visible = game_state["warmup_candles"] + game_state["future_candles"][:game_state["day"]]
    all_volumes = game_state["warmup_volumes"] + game_state["future_volumes"][:game_state["day"]]

    return {
        "candle": candle,
        "volume": volume,
        "day": game_state["day"],
        "days_remaining": game_state["total_bars"] - game_state["day"],
        "game_over": game_state["day"] >= game_state["total_bars"],
    }


def execute_trade(game_state, action):
    """
    Execute BUY or SELL.
    action: "buy" or "sell"
    Returns updated position and purse.
    """
    day = game_state["day"]
    if day == 0:
        return {"error": "Advance at least one day before trading"}

    # Current price = close of last revealed candle
    current_candle = game_state["future_candles"][day - 1]
    price = current_candle["close"]

    if action == "buy":
        if game_state["position"]:
            return {"error": "Already holding a position. Sell first."}

        qty = math.floor(game_state["cash"] / price)
        if qty == 0:
            return {"error": "Not enough cash to buy even 1 share"}

        cost = round(qty * price, 2)
        game_state["position"] = {
            "entry_price": price,
            "qty": qty,
            "entry_day": day,
            "cost": cost,
        }
        game_state["cash"] = round(game_state["cash"] - cost, 2)

        return {
            "action": "buy",
            "price": price,
            "qty": qty,
            "cost": cost,
            "cash_remaining": game_state["cash"],
            "day": day,
        }

    elif action == "sell":
        if not game_state["position"]:
            return {"error": "No position to sell"}

        pos = game_state["position"]
        proceeds = round(pos["qty"] * price, 2)
        pnl = round(proceeds - pos["cost"], 2)
        pnl_pct = round((pnl / pos["cost"]) * 100, 2)
        holding_days = day - pos["entry_day"]

        trade = {
            "entry_price": pos["entry_price"],
            "exit_price": price,
            "qty": pos["qty"],
            "entry_day": pos["entry_day"],
            "exit_day": day,
            "holding_days": holding_days,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "cost": pos["cost"],
            "proceeds": proceeds,
        }
        game_state["trades"].append(trade)
        game_state["cash"] = round(game_state["cash"] + proceeds, 2)
        game_state["position"] = None

        return {
            "action": "sell",
            "price": price,
            "qty": trade["qty"],
            "proceeds": proceeds,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "holding_days": holding_days,
            "cash_remaining": game_state["cash"],
            "day": day,
        }

    return {"error": f"Unknown action: {action}"}


def end_round(game_state):
    """
    End the round. Auto-sell if position open. Return summary.
    """
    # Auto-sell if still holding
    if game_state["position"]:
        execute_trade(game_state, "sell")

    trades = game_state["trades"]
    if not trades:
        return {
            "symbol": game_state["symbol"],
            "total_trades": 0,
            "total_pnl": 0,
            "total_pnl_pct": 0,
            "message": "No trades made this round",
            "mistakes": [],
        }

    total_pnl = sum(t["pnl"] for t in trades)
    total_cost = sum(t["cost"] for t in trades)
    total_pnl_pct = round((total_pnl / PURSE_SIZE) * 100, 2) if PURSE_SIZE else 0
    winning = [t for t in trades if t["pnl"] > 0]
    losing = [t for t in trades if t["pnl"] <= 0]
    win_rate = round(len(winning) / len(trades) * 100, 1) if trades else 0
    avg_holding = round(sum(t["holding_days"] for t in trades) / len(trades), 1) if trades else 0

    # Mistake analysis
    mistakes = _analyze_mistakes(game_state)

    return {
        "symbol": game_state["symbol"],
        "total_trades": len(trades),
        "winning_trades": len(winning),
        "losing_trades": len(losing),
        "win_rate": win_rate,
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": total_pnl_pct,
        "final_purse": round(game_state["cash"], 2),
        "avg_holding_days": avg_holding,
        "best_trade": max(trades, key=lambda t: t["pnl"]) if trades else None,
        "worst_trade": min(trades, key=lambda t: t["pnl"]) if trades else None,
        "trades": trades,
        "mistakes": mistakes,
    }


def _compute_supertrend_direction(highs, lows, closes, period=7, mult=3.0):
    """Compute Supertrend direction at the final bar (1=bullish, -1=bearish). Returns None if insufficient data."""
    import pandas as pd
    n = len(closes)
    if n < period + 1:
        return None
    h, l, c = pd.Series(highs), pd.Series(lows), pd.Series(closes)
    hl2 = (h + l) / 2
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/period, min_periods=period).mean()
    bu = hl2 + mult * atr
    bl = hl2 - mult * atr
    fu, fl = bu.copy(), bl.copy()
    direction = [1] * n
    for i in range(period, n):
        fl.iloc[i] = bl.iloc[i] if (bl.iloc[i] > fl.iloc[i-1] or c.iloc[i-1] < fl.iloc[i-1]) else fl.iloc[i-1]
        fu.iloc[i] = bu.iloc[i] if (bu.iloc[i] < fu.iloc[i-1] or c.iloc[i-1] > fu.iloc[i-1]) else fu.iloc[i-1]
        if i == period:
            direction[i] = 1 if c.iloc[i] > fu.iloc[i] else -1
        elif direction[i-1] == 1:
            direction[i] = -1 if c.iloc[i] < fl.iloc[i] else 1
        else:
            direction[i] = 1 if c.iloc[i] > fu.iloc[i] else -1
    return direction[-1]


def _analyze_mistakes(game_state):
    """Check indicators at each trade entry point for mistakes or confirmations."""
    mistakes = []
    all_candles = game_state["warmup_candles"] + game_state["future_candles"][:game_state["day"]]
    # Volumes aligned with all_candles
    all_volumes = game_state["warmup_volumes"] + game_state["future_volumes"][:game_state["day"]]

    for trade in game_state["trades"]:
        entry_idx = len(game_state["warmup_candles"]) + trade["entry_day"] - 1
        details = []
        is_win = trade["pnl"] >= 0

        if 0 < entry_idx < len(all_candles):
            import pandas as pd

            # Use up to 60 prior bars + entry bar for indicator context
            start = max(0, entry_idx - 60)
            visible = all_candles[start:entry_idx + 1]
            closes = [c["close"] for c in visible]
            highs = [c["high"] for c in visible]
            lows = [c["low"] for c in visible]
            vols = [v.get("value", 0) for v in all_volumes[start:entry_idx + 1]]

            # RSI
            rsi_val = None
            if len(closes) >= 15:
                delta = pd.Series(closes).diff()
                gain = delta.where(delta > 0, 0.0)
                loss = (-delta).where(delta < 0, 0.0)
                avg_g = gain.ewm(alpha=1/14, min_periods=14).mean()
                avg_l = loss.ewm(alpha=1/14, min_periods=14).mean()
                rs = avg_g / avg_l
                rsi_val = float(100 - (100 / (1 + rs.iloc[-1])))
                if is_win:
                    if rsi_val < 40:
                        details.append(f"RSI was {rsi_val:.0f} at entry — oversold/low, good buy zone")
                    elif 40 <= rsi_val <= 60:
                        details.append(f"RSI was {rsi_val:.0f} at entry — neutral, momentum in your favor")
                else:
                    if rsi_val > 70:
                        details.append(f"RSI was {rsi_val:.0f} at entry — overbought (>70), reversal risk")
                    elif rsi_val < 30:
                        details.append(f"RSI was {rsi_val:.0f} at entry — oversold but price continued falling")

            # SMA 20
            if len(closes) >= 20:
                sma20 = sum(closes[-20:]) / 20
                above = closes[-1] >= sma20
                if is_win and above:
                    details.append(f"Price was above SMA 20 ({sma20:.0f}) — bullish structure")
                elif not is_win and not above:
                    details.append(f"Price was below SMA 20 ({sma20:.0f}) at entry — bearish position")

            # Supertrend direction at entry bar
            st_dir = _compute_supertrend_direction(highs, lows, closes)
            if st_dir is not None:
                if is_win and st_dir == 1:
                    details.append("Supertrend was bullish at entry — trend in your favor")
                elif not is_win and st_dir == -1:
                    details.append("Supertrend was bearish at entry — you bought against the trend")

            # Volume check (entry bar vs avg of last 20)
            if len(vols) >= 20:
                avg_vol = sum(vols[-20:]) / 20
                last_vol = vols[-1]
                if avg_vol > 0:
                    ratio = last_vol / avg_vol
                    if is_win and ratio > 1.3:
                        details.append(f"Volume was {ratio:.1f}x average — strong conviction")
                    elif not is_win and ratio < 0.7:
                        details.append("Volume was below average at entry — weak conviction")

        if is_win:
            if not details:
                details.append("Trade worked out — but no clear indicator signal supported this entry")
            mistakes.append({
                "trade": f"BUY@{trade['entry_price']} → SELL@{trade['exit_price']}",
                "type": "good",
                "pnl": trade["pnl"],
                "message": f"Good trade! +₹{trade['pnl']:,.0f} ({trade['pnl_pct']:+.1f}%)",
                "details": details,
            })
        else:
            if not details:
                details.append("Probable external event factor — no indicator signaled against this trade")
            mistakes.append({
                "trade": f"BUY@{trade['entry_price']} → SELL@{trade['exit_price']}",
                "type": "loss",
                "pnl": trade["pnl"],
                "message": f"Loss: -₹{abs(trade['pnl']):,.0f} ({trade['pnl_pct']:+.1f}%)",
                "details": details,
            })

    return mistakes


def _compute_difficulty(df, start_idx, lookback=30):
    """Compute difficulty from price volatility. Returns 'Easy', 'Medium', or 'Hard'."""
    try:
        window = df.iloc[max(0, start_idx - lookback):start_idx]
        if len(window) < 5:
            return "Medium"
        returns = window["Close"].pct_change().dropna()
        if len(returns) < 3:
            return "Medium"
        vol = float(returns.std() * 100)  # daily % stdev
        if vol < 1.5:
            return "Easy"
        elif vol < 3.0:
            return "Medium"
        else:
            return "Hard"
    except Exception:
        return "Medium"


def _load_history(symbol):
    """Load historical data from pickle file."""
    fpath = os.path.join(HISTORY_DIR, f"{symbol}.pkl")
    if not os.path.exists(fpath):
        return None
    try:
        with open(fpath, "rb") as f:
            df = pickle.load(f)
        # Deduplicate
        df = df[~df.index.duplicated(keep='last')]
        return df
    except Exception:
        return None


def _build_candles(df, start, end):
    """Build candle list from dataframe slice."""
    candles = []
    for idx, row in df.iloc[start:end].iterrows():
        t = int(idx.timestamp()) if hasattr(idx, 'timestamp') else 0
        candles.append({
            "time": t,
            "open": round(row["Open"], 2),
            "high": round(row["High"], 2),
            "low": round(row["Low"], 2),
            "close": round(row["Close"], 2),
        })
    return candles


def _build_volumes(df, start, end):
    """Build volume list from dataframe slice."""
    volumes = []
    for idx, row in df.iloc[start:end].iterrows():
        t = int(idx.timestamp()) if hasattr(idx, 'timestamp') else 0
        color = "rgba(38,166,154,0.5)" if row["Close"] >= row["Open"] else "rgba(239,83,80,0.5)"
        volumes.append({"time": t, "value": int(row["Volume"]), "color": color})
    return volumes


def _compute_indicators(df):
    """Compute basic indicators for visible data. Returns dict of indicator arrays."""
    import pandas as pd
    import numpy as np

    result = {}

    # RSI
    if len(df) >= 14:
        delta = df["Close"].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_g = gain.ewm(alpha=1/14, min_periods=14).mean()
        avg_l = loss.ewm(alpha=1/14, min_periods=14).mean()
        rs = avg_g / avg_l
        rsi = 100 - (100 / (1 + rs))
        result["rsi"] = [{"time": int(idx.timestamp()), "value": round(v, 2)}
                         for idx, v in rsi.items() if not pd.isna(v)]

    # SMA 20
    if len(df) >= 20:
        sma = df["Close"].rolling(20).mean()
        result["sma20"] = [{"time": int(idx.timestamp()), "value": round(v, 2)}
                           for idx, v in sma.items() if not pd.isna(v)]

    # Bollinger Bands
    if len(df) >= 20:
        bb_mid = df["Close"].rolling(20).mean()
        bb_std = df["Close"].rolling(20).std()
        result["bb_upper"] = [{"time": int(idx.timestamp()), "value": round(v, 2)}
                              for idx, v in (bb_mid + 2 * bb_std).items() if not pd.isna(v)]
        result["bb_lower"] = [{"time": int(idx.timestamp()), "value": round(v, 2)}
                              for idx, v in (bb_mid - 2 * bb_std).items() if not pd.isna(v)]
        result["bb_mid"] = [{"time": int(idx.timestamp()), "value": round(v, 2)}
                            for idx, v in bb_mid.items() if not pd.isna(v)]

    # Supertrend
    if len(df) >= 14:
        period, mult = 7, 3.0
        hl2 = (df["High"] + df["Low"]) / 2
        tr = pd.concat([df["High"] - df["Low"],
                        (df["High"] - df["Close"].shift()).abs(),
                        (df["Low"] - df["Close"].shift()).abs()], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1/period, min_periods=period).mean()
        basic_upper = hl2 + mult * atr
        basic_lower = hl2 - mult * atr
        final_upper = basic_upper.copy()
        final_lower = basic_lower.copy()
        st = pd.Series(index=df.index, dtype=float)
        direction = pd.Series(1, index=df.index)
        for i in range(period, len(df)):
            if basic_lower.iloc[i] > final_lower.iloc[i-1] or df["Close"].iloc[i-1] < final_lower.iloc[i-1]:
                final_lower.iloc[i] = basic_lower.iloc[i]
            else:
                final_lower.iloc[i] = final_lower.iloc[i-1]
            if basic_upper.iloc[i] < final_upper.iloc[i-1] or df["Close"].iloc[i-1] > final_upper.iloc[i-1]:
                final_upper.iloc[i] = basic_upper.iloc[i]
            else:
                final_upper.iloc[i] = final_upper.iloc[i-1]
            if i == period:
                direction.iloc[i] = 1 if df["Close"].iloc[i] > final_upper.iloc[i] else -1
            elif direction.iloc[i-1] == 1:
                direction.iloc[i] = -1 if df["Close"].iloc[i] < final_lower.iloc[i] else 1
            else:
                direction.iloc[i] = 1 if df["Close"].iloc[i] > final_upper.iloc[i] else -1
            st.iloc[i] = final_lower.iloc[i] if direction.iloc[i] == 1 else final_upper.iloc[i]

        result["supertrend"] = [{"time": int(st.index[i].timestamp()), "value": round(st.iloc[i], 2),
                                 "direction": int(direction.iloc[i])}
                                for i in range(len(st)) if not pd.isna(st.iloc[i])]

    return result
