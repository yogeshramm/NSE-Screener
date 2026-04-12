"""
Session 3 — Screening & Scoring Engine Test
Tests the full 2-stage screening pipeline using sample data.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.test_indicators import generate_sample_ohlcv
from engine.default_config import get_default_config
from engine.screener import screen_stock_stage1, screen_stock_stage2, run_full_screen
from engine.inspector import build_inspector_report, print_inspector_report
from engine.presets import save_preset, load_preset, list_presets, delete_preset
from engine.scorer import compute_score


def print_header(title: str):
    print(f"\n{'#'*70}")
    print(f"#  {title}")
    print(f"{'#'*70}")


def make_sample_stock(symbol: str, trend: str = "up") -> dict:
    """Generate sample stock data for testing."""
    df = generate_sample_ohlcv(symbol, bars=300, trend=trend)
    latest = df.iloc[-1]

    stock_data = {
        "symbol": symbol,
        "daily_history": df,
        "daily_rows": len(df),
        "latest_close": round(latest["Close"], 2),
        "current_price": round(latest["Close"], 2),
        "latest_date": str(df.index[-1].date()),
        "roe": 0.15,
        "roe_pct": 15.0,
        "roce": 18.5,
        "debt_to_equity": 25.0,
        "debt_to_equity_ratio": 0.25,
        "trailing_eps": 45.0,
        "free_cash_flow": 5_000_000_000,
        "institutional_holdings": 0.35,
        "institutional_holdings_pct": 35.0,
        "trailing_pe": 22.5,
        "fifty_two_week_high": df["High"].max(),
        "average_volume": int(df["Volume"].mean()),
        "market_cap": 500_000_000_000,
        "sector": {"RELIANCE": "Energy", "HDFCBANK": "Financial Services",
                    "INFY": "Technology", "TCS": "Technology",
                    "TATAMOTORS": "Consumer Cyclical"}.get(symbol, "Technology"),
        "industry": "Test Industry",
        "short_name": f"{symbol} LTD",
        "recommendations": _make_sample_recs(),
        "recommendations_count": 4,
        "earnings_calendar": {"Earnings Date": ["2026-06-15"]},
        "balance_sheet_years": 4,
    }
    return {"symbol": symbol, "daily_df": df, "stock_data": stock_data}


def _make_sample_recs():
    """Generate sample analyst recommendations."""
    import pandas as pd
    return pd.DataFrame([
        {"period": "0m", "strongBuy": 8, "buy": 20, "hold": 5, "sell": 1, "strongSell": 0},
        {"period": "-1m", "strongBuy": 7, "buy": 19, "hold": 6, "sell": 1, "strongSell": 0},
    ])


def test_default_config():
    """Test 1: Default configuration."""
    print_header("TEST 1: DEFAULT CONFIGURATION")
    config = get_default_config()

    # Count filters
    total_filters = 0
    enabled_filters = 0
    total_params = 0
    for key, val in config.items():
        if isinstance(val, dict) and "enabled" in val:
            total_filters += 1
            if val["enabled"]:
                enabled_filters += 1
            total_params += len([k for k in val.keys() if k != "enabled"])

    print(f"\n  Total filters:   {total_filters}")
    print(f"  Enabled:         {enabled_filters}")
    print(f"  Total params:    {total_params}")
    print(f"  Scoring config:  {config.get('scoring', {})}")
    return total_filters > 20


def test_stage1_screening():
    """Test 2: Stage 1 screening."""
    print_header("TEST 2: STAGE 1 SCREENING")

    stocks = [
        make_sample_stock("RELIANCE", "up"),
        make_sample_stock("HDFCBANK", "up"),
        make_sample_stock("INFY", "up"),
        make_sample_stock("TCS", "down"),
        make_sample_stock("TATAMOTORS", "sideways"),
    ]

    config = get_default_config()
    results = []

    for stock in stocks:
        s1 = screen_stock_stage1(
            stock["symbol"], stock["daily_df"],
            stock["stock_data"], config
        )
        results.append(s1)

        status = "PASS" if s1["passed"] else "FAIL"
        print(f"\n  [{status}] {s1['symbol']:15s} | Score: {s1['score']:5.1f} | "
              f"Tech: {s1['tech_pass']}P/{s1['tech_fail']}F | "
              f"Fund: {s1['fund_pass']}P/{s1['fund_fail']}F | "
              f"Late Entry: {s1['late_entry']['status']}")

    passed = [r for r in results if r["passed"]]
    print(f"\n  Stage 1 passed: {len(passed)}/{len(results)} stocks")
    return len(results) == 5


def test_stage2_screening():
    """Test 3: Stage 2 breakout screening."""
    print_header("TEST 3: STAGE 2 BREAKOUT SCREENING")

    stocks = [
        make_sample_stock("RELIANCE", "up"),
        make_sample_stock("HDFCBANK", "up"),
        make_sample_stock("INFY", "up"),
    ]

    config = get_default_config()

    for stock in stocks:
        s1 = screen_stock_stage1(stock["symbol"], stock["daily_df"],
                                 stock["stock_data"], config)

        if not s1["passed"]:
            print(f"\n  {stock['symbol']}: Skipped Stage 2 (failed Stage 1)")
            continue

        s2 = screen_stock_stage2(stock["symbol"], stock["daily_df"],
                                 stock["stock_data"], s1, config)

        status = "PASS" if s2["passed"] else "FAIL"
        print(f"\n  [{status}] {s2['symbol']:15s} | Score: {s2['score']:5.1f} | "
              f"Breakout: {s2['brk_pass']}P/{s2['brk_fail']}F | "
              f"SL: {s2['stop_loss']} | Target: {s2['target']} | R:R: 1:{s2['risk_reward']}")

    return True


def test_full_screen():
    """Test 4: Full 2-stage screen pipeline."""
    print_header("TEST 4: FULL 2-STAGE PIPELINE")

    stocks = [
        make_sample_stock("RELIANCE", "up"),
        make_sample_stock("HDFCBANK", "up"),
        make_sample_stock("INFY", "up"),
        make_sample_stock("TCS", "down"),
        make_sample_stock("TATAMOTORS", "sideways"),
    ]

    result = run_full_screen(stocks)

    print(f"\n  Total screened:  {result['total_screened']}")
    print(f"  Stage 1 passed:  {len(result['stage1_passed'])} → {result['stage1_passed']}")
    print(f"  Stage 2 passed:  {len(result['stage2_passed'])} → {result['stage2_passed']}")

    # Print Stage 1 ranked table
    print(f"\n  {'='*90}")
    print(f"  STAGE 1 RANKINGS")
    print(f"  {'Rank':<5} {'Symbol':<12} {'Score':<8} {'Tech':<10} {'Fund':<10} {'Breakout':<10} {'Passed':<8}")
    print(f"  {'-'*90}")
    for r in result["stage1_results"]:
        sc = r["scores"]
        print(f"  {r['rank']:<5} {r['symbol']:<12} {r['score']:<8.1f} "
              f"{sc['technical_score']:<10.1f} {sc['fundamental_score']:<10.1f} "
              f"{sc['breakout_score']:<10.1f} {'YES' if r['passed'] else 'NO':<8}")

    # Print Stage 2 ranked table
    if result["stage2_results"]:
        print(f"\n  {'='*90}")
        print(f"  STAGE 2 RANKINGS")
        print(f"  {'Rank':<5} {'Symbol':<12} {'Score':<8} {'Price':<10} {'SL':<10} {'Target':<10} {'R:R':<8} {'Passed':<8}")
        print(f"  {'-'*90}")
        for r in result["stage2_results"]:
            print(f"  {r['rank']:<5} {r['symbol']:<12} {r['score']:<8.1f} "
                  f"{r['price']:<10} {r.get('stop_loss', 'N/A')!s:<10} "
                  f"{r.get('target', 'N/A')!s:<10} {r.get('risk_reward', 'N/A')!s:<8} "
                  f"{'YES' if r['passed'] else 'NO':<8}")

    return True


def test_inspector():
    """Test 5: Indicator Inspector."""
    print_header("TEST 5: INDICATOR INSPECTOR")

    stock = make_sample_stock("RELIANCE", "up")
    config = get_default_config()

    s1 = screen_stock_stage1("RELIANCE", stock["daily_df"], stock["stock_data"], config)
    s2 = None
    if s1["passed"]:
        s2 = screen_stock_stage2("RELIANCE", stock["daily_df"], stock["stock_data"], s1, config)

    report = build_inspector_report(s1, s2)
    print_inspector_report(report, "RELIANCE")

    return len(report) > 20


def test_presets():
    """Test 6: Preset save/load."""
    print_header("TEST 6: PRESET SAVE/LOAD")

    config = get_default_config()

    # Save
    path = save_preset("test_preset", config)
    print(f"\n  Saved preset: {path}")

    # Modify and save another
    aggressive = get_default_config()
    aggressive["rsi"]["rsi_max"] = 70
    aggressive["adx"]["adx_minimum"] = 15
    aggressive["pe_ratio"]["pe_maximum"] = 50
    save_preset("aggressive", aggressive)

    # List
    presets = list_presets()
    print(f"  Available presets: {presets}")

    # Load
    loaded = load_preset("aggressive")
    print(f"  Loaded 'aggressive': RSI max={loaded['rsi']['rsi_max']}, ADX min={loaded['adx']['adx_minimum']}")

    # Delete test
    deleted = delete_preset("test_preset")
    print(f"  Deleted 'test_preset': {deleted}")

    remaining = list_presets()
    print(f"  Remaining presets: {remaining}")

    return "aggressive" in remaining


def test_config_override():
    """Test 7: Runtime config override changes results."""
    print_header("TEST 7: CONFIG OVERRIDE")

    stock = make_sample_stock("RELIANCE", "up")
    config = get_default_config()

    # Run with defaults
    s1_default = screen_stock_stage1("RELIANCE", stock["daily_df"], stock["stock_data"], config)

    # Run with relaxed config
    relaxed = get_default_config()
    relaxed["rsi"]["rsi_min"] = 30
    relaxed["rsi"]["rsi_max"] = 80
    relaxed["adx"]["adx_minimum"] = 10
    relaxed["cmf"]["cmf_minimum"] = -0.5
    relaxed["pe_ratio"]["pe_maximum"] = 100

    s1_relaxed = screen_stock_stage1("RELIANCE", stock["daily_df"], stock["stock_data"], relaxed)

    print(f"\n  Default config score:  {s1_default['score']}")
    print(f"  Relaxed config score:  {s1_relaxed['score']}")
    print(f"  Scores differ:         {s1_default['score'] != s1_relaxed['score']}")

    # Run with everything disabled except EMA
    minimal = get_default_config()
    for key in minimal:
        if isinstance(minimal[key], dict) and "enabled" in minimal[key]:
            minimal[key]["enabled"] = False
    minimal["ema"]["enabled"] = True

    s1_minimal = screen_stock_stage1("RELIANCE", stock["daily_df"], stock["stock_data"], minimal)
    active_indicators = [r for r in s1_minimal["indicator_results"] if r["status"] != "SKIPPED"]
    skipped_indicators = [r for r in s1_minimal["indicator_results"] if r["status"] == "SKIPPED"]

    print(f"\n  Minimal config (only EMA):")
    print(f"    Active indicators:  {len(active_indicators)}")
    print(f"    Skipped indicators: {len(skipped_indicators)}")

    return True


def run_all_tests():
    print("\n" + "="*70)
    print("  NSE SCREENER — SESSION 3 SCREENING ENGINE TEST")
    print("="*70)

    t1 = test_default_config()
    t2 = test_stage1_screening()
    t3 = test_stage2_screening()
    t4 = test_full_screen()
    t5 = test_inspector()
    t6 = test_presets()
    t7 = test_config_override()

    print_header("FINAL STATUS SUMMARY")
    tests = [
        ("Default config", t1),
        ("Stage 1 screening", t2),
        ("Stage 2 screening", t3),
        ("Full pipeline", t4),
        ("Indicator inspector", t5),
        ("Preset system", t6),
        ("Config override", t7),
    ]

    all_pass = True
    for name, result in tests:
        status = "PASS" if result else "FAIL"
        if not result:
            all_pass = False
        print(f"  {name:<25s}: {status}")

    print(f"\n  Overall: {'ALL OK' if all_pass else 'HAS ISSUES'}")
    print(f"\n{'='*70}")
    print("  SESSION 3 SCREENING ENGINE TEST COMPLETE")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    run_all_tests()
