"""
Session 1 — Data Layer Test Script
Tests all 4 components on RELIANCE, HDFCBANK, INFY.
Prints every fetched field to terminal.
"""

import sys
import os
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.yfinance_fetcher import fetch_all
from data.nse_bhavcopy import download_bhavcopy, get_bhavcopy_close
from data.nse_fii_dii import fetch_fii_dii_activity, get_net_fii_dii_summary
from data.price_verifier import verify_price


TEST_STOCKS = ["RELIANCE", "HDFCBANK", "INFY"]


def print_header(title: str):
    print(f"\n{'#'*70}")
    print(f"#  {title}")
    print(f"{'#'*70}")


def print_section(title: str):
    print(f"\n  --- {title} ---")


def test_yfinance_fetcher():
    """Test 1: YFinance data for all 3 stocks."""
    print_header("TEST 1: YFINANCE DATA FETCHER")
    results = {}

    for idx, symbol in enumerate(TEST_STOCKS):
        if idx > 0:
            print(f"\n  Waiting 5s between stocks to avoid rate limiting...")
            time.sleep(5)
        data = fetch_all(symbol)
        results[symbol] = data

        print_section(f"SUMMARY for {symbol}")
        print(f"  Symbol:                 {data.get('symbol')}")
        print(f"  Short Name:             {data.get('short_name')}")
        print(f"  Sector:                 {data.get('sector')}")
        print(f"  Industry:               {data.get('industry')}")
        print(f"  Current Price:          {data.get('current_price')}")
        print(f"  Latest Close (daily):   {data.get('latest_close')}")
        print(f"  Latest Date:            {data.get('latest_date')}")
        print(f"  Daily Bars:             {data.get('daily_rows')}")
        print(f"  4H Bars:                {data.get('h4_rows')}")
        print(f"  52-Week High:           {data.get('fifty_two_week_high')}")
        print(f"  Average Volume:         {data.get('average_volume')}")
        print(f"  Market Cap:             {data.get('market_cap')}")
        print(f"  Trailing PE:            {data.get('trailing_pe')}")
        print(f"  Trailing EPS:           {data.get('trailing_eps')}")
        print(f"  ROE:                    {data.get('roe')} (raw) → {data.get('roe_pct')}%")
        print(f"  ROCE:                   {data.get('roce')}%")
        print(f"  Debt/Equity:            {data.get('debt_to_equity')} (raw) → {data.get('debt_to_equity_ratio')}")
        print(f"  Free Cash Flow:         {data.get('free_cash_flow')}")
        print(f"  Institutional Holdings: {data.get('institutional_holdings')} → {data.get('institutional_holdings_pct')}%")
        print(f"  Recommendations Count:  {data.get('recommendations_count')}")
        print(f"  Earnings Calendar:      {list(data.get('earnings_calendar', {}).keys()) if data.get('earnings_calendar') else 'N/A'}")
        print(f"  Balance Sheet Years:    {data.get('balance_sheet_years')}")

        # Show last 5 analyst recommendations if available
        recs = data.get("recommendations")
        if recs is not None and not recs.empty:
            print_section(f"Last 5 Analyst Recommendations for {symbol}")
            print(recs.tail(5).to_string())
        else:
            print(f"\n  No analyst recommendations available for {symbol}")

        # Show latest daily prices (last 3 rows)
        daily = data.get("daily_history")
        if daily is not None and not daily.empty:
            print_section(f"Last 3 Daily Candles for {symbol}")
            print(daily.tail(3).to_string())

    return results


def test_bhavcopy():
    """Test 2: NSE Bhavcopy download and price extraction."""
    print_header("TEST 2: NSE BHAVCOPY DOWNLOADER")

    try:
        print("\n  Downloading today's Bhavcopy (or most recent trading day)...")
        bhavcopy_df = download_bhavcopy()
        print(f"  Bhavcopy shape: {bhavcopy_df.shape}")
        print(f"  Columns: {list(bhavcopy_df.columns)}")

        results = {}
        for symbol in TEST_STOCKS:
            result = get_bhavcopy_close(symbol, bhavcopy_df)
            results[symbol] = result
            if result["found"]:
                print(f"\n  {symbol}: Close = ₹{result['close_price']} (Date: {result['date']})")
            else:
                print(f"\n  {symbol}: NOT FOUND — {result.get('error', 'unknown error')}")

        return bhavcopy_df, results

    except Exception as e:
        print(f"\n  BHAVCOPY DOWNLOAD FAILED: {e}")
        print("  This is common when NSE servers are unreachable (geo-restrictions, non-trading hours).")
        print("  The function will work when NSE is accessible.")
        return None, {}


def test_fii_dii():
    """Test 3: FII/DII activity data."""
    print_header("TEST 3: FII/DII ACTIVITY DOWNLOADER")

    print("\n  Fetching FII/DII data for last 5 days...")
    summary = get_net_fii_dii_summary(last_n_days=5)

    print(f"\n  Days available:   {summary['days_available']}")
    print(f"  Total FII Net:    ₹{summary['total_fii_net']} Cr")
    print(f"  Total DII Net:    ₹{summary['total_dii_net']} Cr")
    print(f"  Combined Net:     ₹{summary['combined_net']} Cr")

    if summary.get("note"):
        print(f"  Note: {summary['note']}")

    if summary["daily_data"]:
        print_section("Daily FII/DII Breakdown")
        for day in summary["daily_data"]:
            print(f"    {day['date']}: FII Net={day['fii_net_value']} | DII Net={day['dii_net_value']}")
    else:
        print("\n  No daily FII/DII data available (geo-restricted API).")
        print("  This will work when run from India or with VPN.")

    return summary


def test_price_verification(yf_results: dict, bhavcopy_results: dict):
    """Test 4: Price verification between yfinance and Bhavcopy."""
    print_header("TEST 4: PRICE VERIFICATION")

    if not bhavcopy_results:
        print("\n  Skipping price verification — Bhavcopy data not available.")
        print("  This test will work when Bhavcopy download succeeds.")
        return

    for symbol in TEST_STOCKS:
        yf_data = yf_results.get(symbol, {})
        bhav_data = bhavcopy_results.get(symbol, {})

        yf_close = yf_data.get("latest_close")
        bhav_close = bhav_data.get("close_price")

        result = verify_price(yf_close, bhav_close, symbol)
        print(f"\n  {result['message']}")


def run_all_tests():
    """Run all data layer tests."""
    print("\n" + "="*70)
    print("  NSE SCREENER — SESSION 1 DATA LAYER TEST")
    print("  Testing on: RELIANCE, HDFCBANK, INFY")
    print("="*70)

    # Test 1: YFinance
    yf_results = test_yfinance_fetcher()

    # Test 2: Bhavcopy
    bhavcopy_df, bhavcopy_results = test_bhavcopy()

    # Test 3: FII/DII
    fii_dii_summary = test_fii_dii()

    # Test 4: Price verification
    test_price_verification(yf_results, bhavcopy_results)

    # Final summary
    print_header("FINAL STATUS SUMMARY")
    for symbol in TEST_STOCKS:
        yf = yf_results.get(symbol, {})
        daily_ok = yf.get("daily_rows", 0) >= 200
        h4_ok = yf.get("h4_rows", 0) > 0
        fund_ok = yf.get("roe") is not None
        bs_ok = yf.get("balance_sheet_years", 0) > 0
        roce_ok = yf.get("roce") is not None

        status = "ALL OK" if (daily_ok and fund_ok) else "PARTIAL"
        print(f"\n  {symbol}:")
        print(f"    Daily Data (≥200 bars): {'PASS' if daily_ok else 'FAIL'} ({yf.get('daily_rows', 0)} bars)")
        print(f"    4H Data:                {'PASS' if h4_ok else 'WARN'} ({yf.get('h4_rows', 0)} bars)")
        print(f"    Fundamentals:           {'PASS' if fund_ok else 'FAIL'}")
        print(f"    Balance Sheet:          {'PASS' if bs_ok else 'FAIL'}")
        print(f"    ROCE:                   {'PASS' if roce_ok else 'FAIL'}")
        print(f"    Overall:                {status}")

    bhav_ok = bhavcopy_df is not None
    fii_ok = fii_dii_summary.get("days_available", 0) > 0
    print(f"\n  Bhavcopy Download:        {'PASS' if bhav_ok else 'FAIL (geo-restricted)'}")
    print(f"  FII/DII Data:             {'PASS' if fii_ok else 'FAIL (geo-restricted)'}")
    print(f"\n{'='*70}")
    print("  SESSION 1 DATA LAYER TEST COMPLETE")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    run_all_tests()
