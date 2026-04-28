"""
Main Screening Engine
Orchestrates Stage 1 and Stage 2 screening across all NSE stocks.
"""

import pandas as pd
from engine.default_config import get_default_config, CONFIG_TO_INDICATOR
from engine.fundamental_checker import check_fundamentals
from engine.indicator_cache import load_cached, save_cached
from engine.late_entry import check_stage1_late_entry, check_stage2_late_entry
from engine.scorer import compute_score
from indicators.registry import run_all_indicators


def _merge_config(base: dict, overrides: dict) -> dict:
    """Deep merge overrides into base config."""
    merged = {}
    for key, value in base.items():
        if key in overrides:
            if isinstance(value, dict) and isinstance(overrides[key], dict):
                merged[key] = {**value, **overrides[key]}
            else:
                merged[key] = overrides[key]
        else:
            merged[key] = value
    # Add any keys in overrides not in base
    for key in overrides:
        if key not in merged:
            merged[key] = overrides[key]
    return merged


def _build_indicator_inputs(config: dict) -> tuple[dict, dict]:
    """
    Convert config into enabled_indicators and params dicts
    that the indicator registry expects.
    """
    enabled = {}
    params = {}

    for config_key, indicator_name in CONFIG_TO_INDICATOR.items():
        cfg = config.get(config_key, {})
        enabled[indicator_name] = cfg.get("enabled", True)

        # Pass all params except 'enabled'
        indicator_params = {k: v for k, v in cfg.items() if k != "enabled"}
        if indicator_params:
            params[indicator_name] = indicator_params

    return enabled, params


def screen_stock_stage1(symbol: str, daily_df: pd.DataFrame, stock_data: dict,
                        config: dict | None = None, df_4h: pd.DataFrame | None = None) -> dict:
    """
    Run Stage 1 screening on a single stock.

    Args:
        symbol: stock symbol
        daily_df: daily OHLCV DataFrame
        stock_data: dict from yfinance_fetcher.fetch_all()
        config: filter config (uses defaults if None)
        df_4h: optional 4H data for hidden divergence

    Returns:
        dict with all screening results, scores, and inspector data
    """
    if config is None:
        config = get_default_config()

    # Guard: skip stocks with insufficient history (newly-listed IPOs etc.)
    # Below 50 bars most indicators (SMA 50, RSI-14 stability, ATR-14) are
    # meaningless — scoring returns noise. Fail fast rather than waste compute.
    if daily_df is None or len(daily_df) < 50:
        return {
            "symbol": symbol, "stage": 1, "passed": False,
            "score": 0, "scores": {"total_score": 0},
            "price": stock_data.get("latest_close") or stock_data.get("current_price"),
            "sector": stock_data.get("sector"),
            "indicator_results": [], "fundamental_results": {},
            "late_entry": {"status": "SKIPPED", "value": "N/A", "threshold": "N/A",
                           "details": f"Insufficient history ({len(daily_df) if daily_df is not None else 0} bars)"},
            "tech_pass": 0, "tech_fail": 0, "fund_pass": 0, "fund_fail": 0,
            "insufficient_history": True,
        }

    # Build indicator inputs from config
    enabled, params = _build_indicator_inputs(config)

    # Run technical indicators (cache-first)
    sector = stock_data.get("sector")
    last_bar_date = str(daily_df.index[-1].date())
    indicator_results = load_cached(symbol, config, sector, last_bar_date)
    if indicator_results is None:
        indicator_results = run_all_indicators(
            daily_df,
            enabled_indicators=enabled,
            params=params,
            sector=sector,
            df_4h=df_4h,
        )
        save_cached(symbol, config, sector, last_bar_date, indicator_results)

    # Run fundamental checks
    fundamental_results = check_fundamentals(stock_data, config)

    # Late entry correction
    late_entry = check_stage1_late_entry(daily_df, config)

    # Compute score
    scores = compute_score(indicator_results, fundamental_results, config)

    # Count passes/fails
    tech_pass = sum(1 for r in indicator_results if r["status"] == "PASS")
    tech_fail = sum(1 for r in indicator_results if r["status"] == "FAIL")
    fund_pass = sum(1 for r in fundamental_results.values() if r["status"] == "PASS")
    fund_fail = sum(1 for r in fundamental_results.values() if r["status"] == "FAIL")

    # Determine overall stage 1 pass/fail
    # A stock passes Stage 1 if it has a reasonable score and no critical failures
    critical_fails = 0
    for name in ["ema", "rsi", "supertrend"]:
        ind_name = CONFIG_TO_INDICATOR.get(name)
        if ind_name:
            r = next((r for r in indicator_results if r["indicator"] == ind_name), None)
            if r and r["status"] == "FAIL" and config.get(name, {}).get("enabled", True):
                critical_fails += 1

    stage1_pass = scores["total_score"] >= 40 and critical_fails <= 1

    return {
        "symbol": symbol,
        "stage": 1,
        "passed": stage1_pass,
        "score": scores["total_score"],
        "scores": scores,
        "price": stock_data.get("latest_close") or stock_data.get("current_price"),
        "sector": sector,
        "pe": stock_data.get("trailing_pe"),
        "roe": stock_data.get("roe_pct"),
        "roce": stock_data.get("roce"),
        "debt_equity": stock_data.get("debt_to_equity_ratio"),
        "indicator_results": indicator_results,
        "fundamental_results": fundamental_results,
        "late_entry": late_entry,
        "tech_pass": tech_pass,
        "tech_fail": tech_fail,
        "fund_pass": fund_pass,
        "fund_fail": fund_fail,
    }


def screen_stock_stage2(symbol: str, daily_df: pd.DataFrame, stock_data: dict,
                        stage1_result: dict, config: dict | None = None) -> dict:
    """
    Run Stage 2 breakout screening on a stock that passed Stage 1.

    Args:
        symbol: stock symbol
        daily_df: daily OHLCV DataFrame
        stock_data: dict from yfinance_fetcher.fetch_all()
        stage1_result: result from screen_stock_stage1()
        config: filter config

    Returns:
        dict with Stage 2 screening results
    """
    if config is None:
        config = get_default_config()

    close = daily_df["Close"].iloc[-1]
    high = daily_df["High"]

    results = {}

    # --- Breakout Proximity ---
    cfg = config.get("breakout_proximity", {})
    if cfg.get("enabled", True):
        high_52w = high.iloc[-252:].max() if len(high) >= 252 else high.max()
        proximity = ((high_52w - close) / high_52w) * 100
        max_prox = cfg.get("breakout_proximity_max", 5)
        results["breakout_proximity"] = {
            "status": "PASS" if proximity <= max_prox else "FAIL",
            "value": f"{proximity:.1f}% from 52W high",
            "threshold": f"<= {max_prox}%",
            "details": f"52W High={round(high_52w, 2)}, Close={round(close, 2)}",
        }
    else:
        results["breakout_proximity"] = {"status": "SKIPPED", "value": "N/A", "threshold": "N/A", "details": "Disabled"}

    # --- Breakout Volume ---
    cfg = config.get("breakout_volume", {})
    if cfg.get("enabled", True):
        avg_vol = daily_df["Volume"].iloc[-21:-1].mean()
        latest_vol = daily_df["Volume"].iloc[-1]
        mult = cfg.get("breakout_volume_multiplier", 2.0)
        ratio = latest_vol / avg_vol if avg_vol > 0 else 0
        results["breakout_volume"] = {
            "status": "PASS" if ratio >= mult else "FAIL",
            "value": f"{ratio:.1f}x avg",
            "threshold": f">= {mult}x",
            "details": f"Latest={latest_vol:,}, Avg20={int(avg_vol):,}",
        }
    else:
        results["breakout_volume"] = {"status": "SKIPPED", "value": "N/A", "threshold": "N/A", "details": "Disabled"}

    # --- Breakout RSI ---
    cfg = config.get("breakout_rsi", {})
    if cfg.get("enabled", True):
        # Get RSI from stage 1 indicator results
        rsi_result = next((r for r in stage1_result["indicator_results"]
                          if r["indicator"] == "RSI"), None)
        if rsi_result and rsi_result.get("computed", {}).get("rsi") is not None:
            rsi_val = rsi_result["computed"]["rsi"]
            rsi_min = cfg.get("breakout_rsi_min", 55)
            rsi_max = cfg.get("breakout_rsi_max", 70)
            rsi_reject = cfg.get("breakout_rsi_reject", 75)
            if rsi_val > rsi_reject:
                status = "FAIL"
            elif rsi_min <= rsi_val <= rsi_max:
                status = "PASS"
            else:
                status = "FAIL"
            results["breakout_rsi"] = {
                "status": status, "value": f"{rsi_val}",
                "threshold": f"{rsi_min}-{rsi_max} (reject > {rsi_reject})",
                "details": f"RSI = {rsi_val}",
            }
        else:
            results["breakout_rsi"] = {
                "status": "FAIL", "value": "N/A",
                "threshold": "RSI data needed", "details": "No RSI computed",
            }
    else:
        results["breakout_rsi"] = {"status": "SKIPPED", "value": "N/A", "threshold": "N/A", "details": "Disabled"}

    # --- Breakout Candle Quality ---
    cfg = config.get("breakout_candle", {})
    if cfg.get("enabled", True):
        last = daily_df.iloc[-1]
        candle_range = last["High"] - last["Low"]
        quality_min = cfg.get("candle_close_quality", 70)
        if candle_range > 0:
            close_pct = ((last["Close"] - last["Low"]) / candle_range) * 100
            bullish_engulf = (last["Close"] > last["Open"] and
                            last["Close"] > daily_df["High"].iloc[-2] and
                            last["Open"] < daily_df["Low"].iloc[-2])
            if close_pct >= quality_min or bullish_engulf:
                status = "PASS"
            elif close_pct >= quality_min * 0.8:
                status = "BORDERLINE"
            else:
                status = "FAIL"
            results["breakout_candle"] = {
                "status": status,
                "value": f"Close at {close_pct:.0f}% of range",
                "threshold": f">= {quality_min}%",
                "details": f"Engulfing: {bullish_engulf}",
            }
        else:
            results["breakout_candle"] = {
                "status": "FAIL", "value": "Doji",
                "threshold": f">= {quality_min}%", "details": "Zero range candle",
            }
    else:
        results["breakout_candle"] = {"status": "SKIPPED", "value": "N/A", "threshold": "N/A", "details": "Disabled"}

    # --- Supply Zone (clear upside) ---
    cfg = config.get("supply_zone", {})
    if cfg.get("enabled", True):
        min_upside = cfg.get("upside_clear_minimum", 5)
        high_52w = high.iloc[-252:].max() if len(high) >= 252 else high.max()
        upside = ((high_52w - close) / close) * 100
        # If stock is near ATH, upside is potentially unlimited
        if upside < 1:
            upside = min_upside + 5  # at ATH = clear upside
        results["supply_zone"] = {
            "status": "PASS" if upside >= min_upside else "FAIL",
            "value": f"{upside:.1f}% clear upside",
            "threshold": f">= {min_upside}%",
            "details": f"Next resistance near {round(high_52w, 2)}",
        }
    else:
        results["supply_zone"] = {"status": "SKIPPED", "value": "N/A", "threshold": "N/A", "details": "Disabled"}

    # Late entry stage 2
    late_entry = check_stage2_late_entry(daily_df, config)

    # Combine breakout results with stage 1 breakout indicators
    breakout_indicator_results = [r for r in stage1_result["indicator_results"]
                                  if r.get("type") == "breakout"]

    # Score stage 2
    all_breakout_results = {**results}
    for r in breakout_indicator_results:
        all_breakout_results[r["indicator"]] = r

    scores = compute_score(stage1_result["indicator_results"],
                          {**stage1_result["fundamental_results"], **results},
                          config)

    # Count
    brk_pass = sum(1 for r in results.values() if r["status"] == "PASS")
    brk_pass += sum(1 for r in breakout_indicator_results if r["status"] == "PASS")
    brk_fail = sum(1 for r in results.values() if r["status"] == "FAIL")
    brk_fail += sum(1 for r in breakout_indicator_results if r["status"] == "FAIL")

    stage2_pass = brk_pass > brk_fail and late_entry["status"] != "FAIL"

    # ATR-based stop loss / target
    atr_result = next((r for r in stage1_result["indicator_results"]
                       if r["indicator"] == "ATR"), None)
    stop_loss = atr_result["computed"].get("stop_loss") if atr_result else None
    target = atr_result["computed"].get("target") if atr_result else None
    rr_ratio = atr_result["computed"].get("risk_reward_ratio") if atr_result else None
    atr_val = atr_result["computed"].get("atr") if atr_result else None

    return {
        "symbol": symbol,
        "stage": 2,
        "passed": stage2_pass,
        "score": scores["total_score"],
        "scores": scores,
        "price": round(close, 2),
        "stop_loss": stop_loss,
        "target": target,
        "risk_reward": rr_ratio,
        "atr": atr_val,
        "breakout_results": results,
        "breakout_indicator_results": breakout_indicator_results,
        "late_entry": late_entry,
        "brk_pass": brk_pass,
        "brk_fail": brk_fail,
    }


def run_full_screen(stocks_data: list[dict], config: dict | None = None) -> dict:
    """
    Run the complete 2-stage screening on a list of stocks.

    Args:
        stocks_data: list of dicts, each containing:
            - symbol, daily_df, stock_data, (optional) df_4h
        config: filter configuration (uses defaults if None)

    Returns:
        dict with:
          - stage1_results: list of Stage 1 results, sorted by score
          - stage2_results: list of Stage 2 results, sorted by score
          - stage1_passed: list of symbols that passed Stage 1
          - stage2_passed: list of symbols that passed Stage 2
    """
    if config is None:
        config = get_default_config()

    stage1_results = []
    stage2_results = []

    for stock in stocks_data:
        symbol = stock["symbol"]
        daily_df = stock["daily_df"]
        stock_data = stock["stock_data"]
        df_4h = stock.get("df_4h")

        # Stage 1
        s1 = screen_stock_stage1(symbol, daily_df, stock_data, config, df_4h)
        stage1_results.append(s1)

        # Stage 2 only if Stage 1 passed
        if s1["passed"]:
            s2 = screen_stock_stage2(symbol, daily_df, stock_data, s1, config)
            stage2_results.append(s2)

    # Sort by score descending and assign ranks
    stage1_results.sort(key=lambda x: x["score"], reverse=True)
    for i, r in enumerate(stage1_results):
        r["rank"] = i + 1

    stage2_results.sort(key=lambda x: x["score"], reverse=True)
    for i, r in enumerate(stage2_results):
        r["rank"] = i + 1

    return {
        "stage1_results": stage1_results,
        "stage2_results": stage2_results,
        "stage1_passed": [r["symbol"] for r in stage1_results if r["passed"]],
        "stage2_passed": [r["symbol"] for r in stage2_results if r["passed"]],
        "total_screened": len(stocks_data),
        "config": config,
    }
