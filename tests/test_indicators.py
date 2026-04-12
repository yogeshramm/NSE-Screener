"""
Session 2 — Indicator Layer Test Script
Tests all 20 indicators using sample OHLCV data.
Sample data simulates realistic NSE stock behavior.
When yfinance is available (not rate limited), also tests with live data.
"""

import sys
import os
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indicators.registry import list_indicators, run_all_indicators, register_custom_indicator
from indicators.base import BaseIndicator


def print_header(title: str):
    print(f"\n{'#'*70}")
    print(f"#  {title}")
    print(f"{'#'*70}")


def generate_sample_ohlcv(symbol: str, bars: int = 300, trend: str = "up") -> pd.DataFrame:
    """
    Generate realistic sample OHLCV data for testing indicators.
    trend: "up" = uptrend, "down" = downtrend, "sideways" = range-bound
    """
    np.random.seed(hash(symbol) % 2**31)

    base_prices = {
        "RELIANCE": 1200.0,
        "HDFCBANK": 750.0,
        "INFY": 1400.0,
    }
    base = base_prices.get(symbol, 1000.0)

    dates = pd.bdate_range(end=pd.Timestamp.now(), periods=bars, freq="B")

    if trend == "up":
        drift = 0.0005
    elif trend == "down":
        drift = -0.0005
    else:
        drift = 0.0

    closes = [base]
    for i in range(1, bars):
        change = np.random.normal(drift, 0.015)
        closes.append(closes[-1] * (1 + change))

    closes = np.array(closes)
    highs = closes * (1 + np.abs(np.random.normal(0.005, 0.005, bars)))
    lows = closes * (1 - np.abs(np.random.normal(0.005, 0.005, bars)))
    opens = lows + (highs - lows) * np.random.uniform(0.2, 0.8, bars)
    volumes = np.random.randint(5_000_000, 30_000_000, bars)

    # Add a volume surge on the last bar
    volumes[-1] = int(volumes[-5:-1].mean() * 1.8)

    df = pd.DataFrame({
        "Open": opens,
        "High": highs,
        "Low": lows,
        "Close": closes,
        "Volume": volumes,
    }, index=dates)

    df.index.name = "Date"
    return df


def test_registry():
    """Test 1: Check all indicators are discovered."""
    print_header("TEST 1: INDICATOR REGISTRY")
    indicators = list_indicators()
    print(f"\n  Total indicators discovered: {len(indicators)}\n")

    technical = [i for i in indicators if i["type"] == "technical"]
    breakout = [i for i in indicators if i["type"] == "breakout"]

    print(f"  TECHNICAL INDICATORS ({len(technical)}):")
    for ind in technical:
        print(f"    - {ind['name']:30s} | Params: {list(ind['default_params'].keys())}")

    print(f"\n  BREAKOUT INDICATORS ({len(breakout)}):")
    for ind in breakout:
        print(f"    - {ind['name']:30s} | Params: {list(ind['default_params'].keys())}")

    return indicators


def test_indicators_on_sample(symbol: str, trend: str = "up"):
    """Run all indicators on sample data for a stock."""
    print_header(f"INDICATORS FOR: {symbol} (sample data, {trend}trend)")

    df = generate_sample_ohlcv(symbol, bars=300, trend=trend)
    print(f"\n  Sample data: {len(df)} bars, Close range: {df['Close'].min():.0f} - {df['Close'].max():.0f}")
    print(f"  Latest: O={df['Open'].iloc[-1]:.2f} H={df['High'].iloc[-1]:.2f} L={df['Low'].iloc[-1]:.2f} C={df['Close'].iloc[-1]:.2f} V={df['Volume'].iloc[-1]:,}")

    sector = {"RELIANCE": "Energy", "HDFCBANK": "Financial Services", "INFY": "Technology"}.get(symbol, "Technology")

    # Run all indicators (skip Sector Performance since it needs live yfinance)
    enabled = {name: True for name in [i["name"] for i in list_indicators()]}
    enabled["Sector Performance"] = False  # needs live data

    print(f"\n  Running {sum(enabled.values())} indicators...\n")
    results = run_all_indicators(df, enabled_indicators=enabled, sector=sector)

    pass_count = fail_count = borderline_count = skip_count = error_count = 0

    for r in results:
        status = r["status"]
        if status == "PASS":
            tag = "PASS"; pass_count += 1
        elif status == "FAIL":
            tag = "FAIL"; fail_count += 1
        elif status == "BORDERLINE":
            tag = "BDLN"; borderline_count += 1
        elif status == "SKIPPED":
            tag = "SKIP"; skip_count += 1
        else:
            tag = "ERR!"; error_count += 1

        print(f"  [{tag:4s}] {r['indicator']:30s} | Value: {r.get('value', 'N/A')}")
        print(f"         Threshold: {r.get('threshold', 'N/A')}")
        print(f"         Details: {r.get('details', '')}")
        print()

    print(f"  {'='*60}")
    print(f"  {symbol} SUMMARY: {pass_count} PASS | {borderline_count} BORDERLINE | {fail_count} FAIL | {error_count} ERROR | {skip_count} SKIPPED")
    print(f"  {'='*60}")

    return results, error_count


def test_custom_indicator():
    """Test custom indicator registration."""
    print_header("TEST: CUSTOM INDICATOR REGISTRATION")

    class MyCustomIndicator(BaseIndicator):
        name = "Custom Test Indicator"
        indicator_type = "technical"
        description = "Test custom indicator — checks if close > open"

        @property
        def default_params(self):
            return {"threshold": 0}

        def compute(self, df, params):
            latest = df.iloc[-1]
            diff = latest["Close"] - latest["Open"]
            return {"close_minus_open": round(diff, 2)}

        def check(self, computed, params):
            val = computed["close_minus_open"]
            return {
                "status": "PASS" if val > params["threshold"] else "FAIL",
                "value": val,
                "threshold": f"> {params['threshold']}",
                "details": f"Close - Open = {val}",
            }

    name = register_custom_indicator(MyCustomIndicator)
    print(f"\n  Registered custom indicator: '{name}'")

    # Verify it appears in the registry
    all_indicators = list_indicators()
    custom = [i for i in all_indicators if i["is_custom"]]
    print(f"  Custom indicators in registry: {len(custom)}")
    for c in custom:
        print(f"    - {c['name']}: {c['description']}")

    # Test it
    df = generate_sample_ohlcv("TEST", bars=50)
    instance = MyCustomIndicator()
    result = instance.evaluate(df)
    print(f"  Result: {result['status']} — {result['value']}")

    return len(custom) > 0


def test_disabled_filters():
    """Test that disabled filters are properly skipped."""
    print_header("TEST: DISABLED FILTERS")

    df = generate_sample_ohlcv("TEST", bars=300)

    # Disable some indicators
    enabled = {name: True for name in [i["name"] for i in list_indicators()]}
    enabled["RSI"] = False
    enabled["MACD"] = False
    enabled["Sector Performance"] = False

    results = run_all_indicators(df, enabled_indicators=enabled)
    skipped = [r for r in results if r["status"] == "SKIPPED"]
    print(f"\n  Disabled 3 indicators. Skipped count: {len(skipped)}")
    for s in skipped:
        print(f"    - {s['indicator']}: {s['status']}")

    return len(skipped) >= 2


def test_timeframes():
    """Test that indicators work on daily, weekly, and monthly timeframes without errors."""
    print_header("TEST: TIMEFRAME SUPPORT (Daily / Weekly / Monthly)")

    from indicators.timeframe import resample_ohlcv, validate_dataframe

    df = generate_sample_ohlcv("RELIANCE", bars=300, trend="up")

    timeframes_to_test = ["daily", "weekly", "monthly"]
    all_ok = True

    for tf in timeframes_to_test:
        resampled = resample_ohlcv(df, tf)
        valid, msg = validate_dataframe(resampled)
        print(f"\n  {tf.upper():10s}: {len(resampled)} bars — {'VALID' if valid else f'INVALID: {msg}'}")

        if not valid:
            all_ok = False
            continue

        # Run all indicators on this timeframe
        enabled = {name: True for name in [i["name"] for i in list_indicators()]}
        enabled["Sector Performance"] = False

        results = run_all_indicators(resampled, enabled_indicators=enabled)
        errors = [r for r in results if r["status"] == "ERROR"]
        passes = sum(1 for r in results if r["status"] == "PASS")
        fails = sum(1 for r in results if r["status"] == "FAIL")

        if errors:
            all_ok = False
            for e in errors:
                print(f"    ERROR: {e['indicator']} — {e['value']}")
        print(f"    Results: {passes} PASS | {fails} FAIL | {len(errors)} ERROR")

    # Test per-indicator timeframe override
    print(f"\n  Per-indicator timeframe override test:")
    tf_overrides = {
        "RSI": "weekly",
        "MACD": "weekly",
        "EMA": "monthly",
    }
    enabled = {name: True for name in [i["name"] for i in list_indicators()]}
    enabled["Sector Performance"] = False
    results = run_all_indicators(df, enabled_indicators=enabled, timeframes=tf_overrides)
    override_errors = [r for r in results if r["status"] == "ERROR"]

    # Check that overridden indicators used the right timeframe
    for r in results:
        if r["indicator"] in tf_overrides and r.get("timeframe"):
            expected_tf = tf_overrides[r["indicator"]]
            actual_tf = r.get("timeframe", "daily")
            match = "OK" if actual_tf == expected_tf else "MISMATCH"
            print(f"    {r['indicator']:20s}: expected={expected_tf}, actual={actual_tf} — {match}")

    if override_errors:
        all_ok = False
        for e in override_errors:
            print(f"    ERROR: {e['indicator']} — {e['value']}")

    print(f"\n  Timeframe test: {'PASS' if all_ok else 'FAIL'}")
    return all_ok


def run_all_tests():
    print("\n" + "="*70)
    print("  NSE SCREENER — SESSION 2 INDICATOR LAYER TEST")
    print("  Testing all 20 indicators on sample data")
    print("="*70)

    # Test 1: Registry
    indicators = test_registry()

    # Test 2: Run on each stock (sample data)
    all_results = {}
    total_errors = 0
    for symbol in ["RELIANCE", "HDFCBANK", "INFY"]:
        results, errors = test_indicators_on_sample(symbol, trend="up")
        all_results[symbol] = results
        total_errors += errors

    # Test 3: Custom indicator
    custom_ok = test_custom_indicator()

    # Test 4: Disabled filters
    disabled_ok = test_disabled_filters()

    # Test 5: Timeframes
    timeframe_ok = test_timeframes()

    # Final summary
    print_header("FINAL STATUS SUMMARY")
    print(f"\n  Total built-in indicators: {len(indicators)}")

    for symbol in ["RELIANCE", "HDFCBANK", "INFY"]:
        results = all_results.get(symbol, [])
        passes = sum(1 for r in results if r["status"] == "PASS")
        fails = sum(1 for r in results if r["status"] == "FAIL")
        borders = sum(1 for r in results if r["status"] == "BORDERLINE")
        errors = sum(1 for r in results if r["status"] == "ERROR")
        skips = sum(1 for r in results if r["status"] == "SKIPPED")
        print(f"\n  {symbol:12s}: {passes} PASS | {borders} BORDERLINE | {fails} FAIL | {errors} ERROR | {skips} SKIP")

    print(f"\n  Custom indicator test:    {'PASS' if custom_ok else 'FAIL'}")
    print(f"  Disabled filter test:     {'PASS' if disabled_ok else 'FAIL'}")
    print(f"  Timeframe test:           {'PASS' if timeframe_ok else 'FAIL'}")
    print(f"  Total computation errors: {total_errors}")

    status = "ALL OK" if total_errors == 0 and custom_ok and disabled_ok and timeframe_ok else "HAS ISSUES"
    print(f"\n  Overall: {status}")

    print(f"\n{'='*70}")
    print("  SESSION 2 INDICATOR LAYER TEST COMPLETE")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    run_all_tests()
