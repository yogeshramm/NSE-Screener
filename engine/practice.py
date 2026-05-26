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
MAX_DAYS_DEFAULT = 60
MIN_HISTORY = 120  # conservative floor; real min = 60 warmup + requested max_days
# India equity delivery costs (round-trip approximation)
BROKER_PCT = 0.001   # 0.1% brokerage applied on both buy and sell
STT_PCT = 0.00025    # 0.025% STT on sell side only


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


def start_round(symbol=None, universe="nifty500", max_days=MAX_DAYS_DEFAULT, mode="free", start_idx_override=None):
    """
    Start a new practice round.
    mode: "free" (random), "daily" (deterministic from today's date), or "replay".
    start_idx_override: when replaying, the exact start_idx from a prior round.
    """
    # Clamp max_days to allowed values
    try:
        max_days = int(max_days)
    except Exception:
        max_days = MAX_DAYS_DEFAULT
    if max_days not in (30, 60, 90):
        max_days = MAX_DAYS_DEFAULT

    # 260 warmup bars so the frontend has enough data to evaluate 150/200-DMA,
    # 52W high/low, and 6-month return at game day 0 (needed for the Minervini
    # pre-entry checklist). Every Nifty-500 stock has 538 bars on disk so 260
    # + 90 = 350 is comfortably inside that budget.
    warmup_bars = 260
    needed = warmup_bars + max_days

    # For daily challenge, seed the RNG from date+universe+max_days so all players get the same setup.
    # Use a local Random instance so we don't poison the global RNG.
    rng = random
    if mode == "daily":
        seed_str = f"{datetime.utcnow().strftime('%Y%m%d')}|{universe}|{max_days}"
        rng = random.Random(seed_str)

    stocks = get_available_stocks(universe)
    if not stocks:
        return {"error": "No stocks available for practice"}

    # Pick random stock if not specified
    if not symbol:
        shuffled = list(stocks)
        rng.shuffle(shuffled)
        symbol = None
        for s in shuffled:
            try:
                df = _load_history(s)
                if df is not None and len(df) >= needed:
                    symbol = s
                    break
            except Exception:
                continue
        if not symbol:
            return {"error": f"No stocks with enough history ({needed} bars) found"}
    else:
        symbol = symbol.upper()

    df = _load_history(symbol)
    if df is None or len(df) < needed:
        return {"error": f"{symbol} has insufficient history ({len(df) if df is not None else 0} bars, need {needed})"}

    # Pick random start point (need warmup bars before + max_days game bars after)
    max_start = len(df) - max_days - 1
    min_start = warmup_bars
    if max_start <= min_start:
        return {"error": f"{symbol} doesn't have enough data for a {max_days}-day game"}

    if start_idx_override is not None:
        try:
            start_idx = int(start_idx_override)
            start_idx = max(min_start, min(max_start, start_idx))
        except Exception:
            start_idx = rng.randint(min_start, max_start)
    else:
        start_idx = rng.randint(min_start, max_start)

    # Build warmup candles (visible from start) + hidden future candles
    warmup = _build_candles(df, start_idx - warmup_bars, start_idx)
    all_future = _build_candles(df, start_idx, min(start_idx + max_days, len(df)))

    # Compute indicators for warmup candles
    warmup_df = df.iloc[start_idx - warmup_bars:start_idx]
    indicators = _compute_indicators(warmup_df)

    difficulty = _compute_difficulty(df, start_idx)
    briefing = _build_briefing(symbol, df, start_idx)

    return {
        "symbol": symbol,
        "universe": universe,
        "difficulty": difficulty,
        "briefing": briefing,
        "mode": mode,
        "start_idx": start_idx,
        "purse": PURSE_SIZE,
        "max_days": max_days,
        "day": 0,
        "warmup_candles": warmup,
        "warmup_volumes": _build_volumes(df, start_idx - warmup_bars, start_idx),
        "indicators": indicators,
        "future_candles": all_future,  # Server holds this — NOT sent to frontend
        "future_volumes": _build_volumes(df, start_idx, min(start_idx + max_days, len(df))),
        "trades": [],
        "position": None,  # {entry_price, qty, entry_day, sl, tp}
        "cash": PURSE_SIZE,
        "total_commissions": 0.0,
        "start_idx": start_idx,
        "total_bars": len(all_future),
    }


def next_day(game_state):
    """
    Reveal next candle. Returns the new candle + updated indicators + auto-exit info.
    """
    day = game_state["day"]
    if day >= len(game_state["future_candles"]):
        return {"error": "No more days available", "game_over": True}

    candle = game_state["future_candles"][day]
    volume = game_state["future_volumes"][day]
    game_state["day"] = day + 1

    auto_exit = None
    pos = game_state.get("position")
    if pos:
        sl = pos.get("sl"); tp = pos.get("tp")
        high = candle["high"]; low = candle["low"]
        side = pos.get("side", "long")
        exit_price = None; exit_reason = None
        if side == "short":
            # Short: SL above entry (high >= SL), TP below entry (low <= TP)
            if sl is not None and high >= sl:
                exit_price = sl; exit_reason = "SL hit"
            if tp is not None and low <= tp and exit_reason is None:
                exit_price = tp; exit_reason = "Target hit"
        else:
            if sl is not None and low <= sl:
                exit_price = sl; exit_reason = "SL hit"
            if tp is not None and high >= tp and exit_reason is None:
                exit_price = tp; exit_reason = "Target hit"
        if exit_reason is not None:
            # Force-sell at exit_price
            trade_result = _sell_at_price(game_state, exit_price, auto=True, reason=exit_reason)
            auto_exit = {
                "reason": exit_reason,
                "price": exit_price,
                **trade_result,
            }

    return {
        "candle": candle,
        "volume": volume,
        "day": game_state["day"],
        "days_remaining": game_state["total_bars"] - game_state["day"],
        "game_over": game_state["day"] >= game_state["total_bars"],
        "auto_exit": auto_exit,
    }


def _sell_at_price(game_state, price, auto=False, reason=None):
    """Internal: close position at given price, apply costs, record trade. Handles long+short."""
    pos = game_state["position"]
    if not pos:
        return {"error": "No position"}
    qty = pos["qty"]
    side = pos.get("side", "long")
    gross = qty * price
    broker = gross * BROKER_PCT
    stt = gross * STT_PCT
    costs = round(broker + stt, 2)
    if side == "short":
        # Short: P&L = (entry - exit) * qty - costs. "Cost" was collateral = entry*qty + entry-side broker.
        pnl = round((pos["entry_price"] - price) * qty - costs, 2)
        proceeds = round(pos["cost"] + pnl, 2)  # return collateral + pnl
    else:
        proceeds = round(gross - costs, 2)
        pnl = round(proceeds - pos["cost"], 2)
    pnl_pct = round((pnl / pos["cost"]) * 100, 2) if pos["cost"] else 0.0
    holding_days = game_state["day"] - pos["entry_day"]

    trade = {
        "entry_price": pos["entry_price"],
        "exit_price": price,
        "qty": qty,
        "entry_day": pos["entry_day"],
        "exit_day": game_state["day"],
        "holding_days": holding_days,
        "pnl": pnl,
        "pnl_pct": pnl_pct,
        "cost": pos["cost"],
        "proceeds": proceeds,
        "costs": costs,
        "auto": auto,
        "reason": reason,
        "side": side,
        "sl": pos.get("sl"),
        "tp": pos.get("tp"),
        "note": pos.get("note"),
        "conviction": pos.get("conviction"),
    }
    game_state["trades"].append(trade)
    game_state["cash"] = round(game_state["cash"] + proceeds, 2)
    game_state["total_commissions"] = round(game_state.get("total_commissions", 0) + costs, 2)
    game_state["position"] = None

    return {
        "action": "sell",
        "price": price,
        "qty": qty,
        "proceeds": proceeds,
        "pnl": pnl,
        "pnl_pct": pnl_pct,
        "holding_days": holding_days,
        "cash_remaining": game_state["cash"],
        "day": game_state["day"],
        "costs": costs,
    }


def execute_trade(game_state, action, qty=None, sl=None, tp=None, note=None, conviction=None, side="long"):
    """
    Execute BUY or SELL.
    BUY:
      qty: optional integer shares (defaults to max affordable with cash).
      sl / tp: optional stop-loss / target prices for auto-exit.
      note / conviction: journal fields stored with position.
    SELL: discretionary exit at current close.
    """
    day = game_state["day"]
    if day == 0:
        return {"error": "Advance at least one day before trading"}

    current_candle = game_state["future_candles"][day - 1]
    price = current_candle["close"]

    if action == "buy":
        if game_state["position"]:
            return {"error": "Already holding a position. Sell first."}

        # Determine qty
        cash = game_state["cash"]
        # Max shares considering buy-side brokerage: qty * price * (1 + BROKER_PCT) <= cash
        max_qty = math.floor(cash / (price * (1 + BROKER_PCT)))
        if max_qty < 1:
            return {"error": "Not enough cash to buy even 1 share"}

        if qty is None:
            q = max_qty
        else:
            try:
                q = int(qty)
            except Exception:
                return {"error": "Invalid qty"}
            if q < 1:
                return {"error": "Qty must be at least 1"}
            if q > max_qty:
                return {"error": f"Not enough cash for {q} shares (max {max_qty})"}

        gross = q * price
        broker = gross * BROKER_PCT
        cost = round(gross + broker, 2)

        # Validate SL/TP (for LONG: SL<price, TP>price; for SHORT: SL>price, TP<price)
        sl_val = float(sl) if sl not in (None, "") else None
        tp_val = float(tp) if tp not in (None, "") else None
        if side == "short":
            if sl_val is not None and sl_val <= price: sl_val = None
            if tp_val is not None and tp_val >= price: tp_val = None
        else:
            if sl_val is not None and sl_val >= price: sl_val = None
            if tp_val is not None and tp_val <= price: tp_val = None

        game_state["position"] = {
            "entry_price": price,
            "qty": q,
            "entry_day": day,
            "cost": cost,
            "side": side,
            "sl": sl_val,
            "tp": tp_val,
            "note": (note or "")[:200] or None,
            "conviction": int(conviction) if conviction not in (None, "") else None,
        }
        game_state["cash"] = round(cash - cost, 2)
        game_state["total_commissions"] = round(game_state.get("total_commissions", 0) + broker, 2)

        return {
            "action": "buy",
            "price": price,
            "qty": q,
            "cost": cost,
            "broker": round(broker, 2),
            "cash_remaining": game_state["cash"],
            "day": day,
            "sl": sl_val,
            "tp": tp_val,
        }

    elif action == "sell":
        if not game_state["position"]:
            return {"error": "No position to sell"}
        return _sell_at_price(game_state, price, auto=False, reason="Manual")

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
    total_pnl_pct = round((total_pnl / PURSE_SIZE) * 100, 2) if PURSE_SIZE else 0
    winning = [t for t in trades if t["pnl"] > 0]
    losing = [t for t in trades if t["pnl"] <= 0]
    win_rate = round(len(winning) / len(trades) * 100, 1) if trades else 0
    avg_holding = round(sum(t["holding_days"] for t in trades) / len(trades), 1) if trades else 0

    # Benchmark: buy-and-hold over the revealed window
    benchmark_pct = _compute_benchmark(game_state)
    alpha = round(total_pnl_pct - benchmark_pct, 2) if benchmark_pct is not None else None

    # Pro metrics
    pro = _compute_pro_metrics(trades)

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
        "benchmark_pct": benchmark_pct,
        "alpha": alpha,
        "total_commissions": round(game_state.get("total_commissions", 0), 2),
        "sharpe": pro["sharpe"],
        "max_drawdown": pro["max_drawdown"],
        "profit_factor": pro["profit_factor"],
        "avg_win": pro["avg_win"],
        "avg_loss": pro["avg_loss"],
        "best_trade": max(trades, key=lambda t: t["pnl"]) if trades else None,
        "worst_trade": min(trades, key=lambda t: t["pnl"]) if trades else None,
        "trades": trades,
        "mistakes": mistakes,
    }


def _compute_benchmark(game_state):
    """Buy-and-hold % return over the game window (day 1 close to last revealed close)."""
    revealed = game_state["future_candles"][:game_state["day"]]
    if len(revealed) < 2:
        return None
    first = revealed[0]["close"]
    last = revealed[-1]["close"]
    if first == 0:
        return None
    return round((last - first) / first * 100, 2)


def _compute_pro_metrics(trades):
    """Sharpe-ish ratio from trade pnl_pct sequence, max drawdown, profit factor."""
    if not trades:
        return {"sharpe": None, "max_drawdown": 0.0, "profit_factor": None, "avg_win": 0.0, "avg_loss": 0.0}

    import statistics
    pcts = [t["pnl_pct"] for t in trades]
    # Sharpe-ish: mean / stdev (per-trade, not annualized)
    if len(pcts) >= 2:
        try:
            sd = statistics.pstdev(pcts)
            sharpe = round(statistics.mean(pcts) / sd, 2) if sd > 0 else None
        except Exception:
            sharpe = None
    else:
        sharpe = None

    # Max drawdown on running P&L
    running = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in trades:
        running += t["pnl"]
        if running > peak:
            peak = running
        dd = peak - running
        if dd > max_dd:
            max_dd = dd

    wins = [t["pnl"] for t in trades if t["pnl"] > 0]
    losses = [t["pnl"] for t in trades if t["pnl"] < 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = round(gross_win / gross_loss, 2) if gross_loss > 0 else None
    avg_win = round(statistics.mean(wins), 2) if wins else 0.0
    avg_loss = round(statistics.mean(losses), 2) if losses else 0.0

    return {
        "sharpe": sharpe,
        "max_drawdown": round(max_dd, 2),
        "profit_factor": profit_factor,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
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


def _build_briefing(symbol, df, start_idx):
    """Stock briefing computed ONLY from history visible up to start_idx. No future leak."""
    try:
        # Visible window for briefing: last 252 bars before game start
        lookback = min(252, start_idx)
        window = df.iloc[start_idx - lookback:start_idx]
        if len(window) < 5:
            return None
        closes = window["Close"]
        highs = window["High"]
        lows = window["Low"]
        vols = window["Volume"]
        last_close = float(closes.iloc[-1])
        w52_high = float(highs.max())
        w52_low = float(lows.min())
        pct_from_high = round((last_close - w52_high) / w52_high * 100, 1)
        pct_from_low = round((last_close - w52_low) / w52_low * 100, 1)
        avg_vol = int(vols.mean()) if len(vols) else 0
        # 30-day volatility
        if len(closes) >= 20:
            returns = closes.pct_change().dropna().tail(30)
            vol_pct = round(float(returns.std() * 100), 2) if len(returns) else None
        else:
            vol_pct = None

        # Sector from static map; market cap from fundamentals
        sector = None
        market_cap = None
        try:
            from data.sector_map import get_sector as _gs
            s = _gs(symbol)
            if s and s != "Other":
                sector = s
        except Exception:
            pass
        try:
            import pickle as _pickle
            fa_path = os.path.join(os.path.dirname(HISTORY_DIR), "fundamentals", f"{symbol}.pkl")
            if os.path.exists(fa_path):
                with open(fa_path, "rb") as f:
                    fa = _pickle.load(f)
                if isinstance(fa, dict):
                    if not sector:
                        sector = fa.get("sector") or fa.get("industry")
                    market_cap = fa.get("market_cap") or fa.get("mcap")
        except Exception:
            pass

        return {
            "symbol": symbol,
            "last_close": round(last_close, 2),
            "w52_high": round(w52_high, 2),
            "w52_low": round(w52_low, 2),
            "pct_from_high": pct_from_high,
            "pct_from_low": pct_from_low,
            "avg_volume": avg_vol,
            "volatility_30d": vol_pct,
            "sector": sector,
            "market_cap": market_cap,
        }
    except Exception:
        return None


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
