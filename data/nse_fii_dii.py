"""
NSE FII/DII Activity Downloader
Downloads daily FII (Foreign Institutional Investors) and DII (Domestic Institutional Investors)
net buy/sell data from NSE.
"""

import requests
import pandas as pd
from datetime import datetime, timedelta


NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.nseindia.com/",
}


def _get_nse_session() -> requests.Session:
    """Create a session that first visits NSE homepage to get cookies."""
    session = requests.Session()
    session.headers.update(NSE_HEADERS)
    try:
        session.get("https://www.nseindia.com/", timeout=10)
    except Exception:
        pass
    return session


def fetch_fii_dii_activity(last_n_days: int = 10) -> pd.DataFrame:
    """
    Fetch FII/DII daily activity data for the last N days.

    Uses the NSE API endpoint that returns JSON data.

    Returns DataFrame with columns:
      - date
      - fii_buy_value (crore)
      - fii_sell_value (crore)
      - fii_net_value (crore)
      - dii_buy_value (crore)
      - dii_sell_value (crore)
      - dii_net_value (crore)
    """
    session = _get_nse_session()

    # NSE JSON API for FII/DII data
    url = "https://www.nseindia.com/api/fiidiiTradeReact"

    try:
        resp = session.get(url, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            return _parse_fii_dii_json(data, last_n_days)
    except Exception as e:
        print(f"  [WARN] FII/DII JSON API failed: {e}")

    # Fallback: try the NSDL/depository data endpoint
    try:
        url2 = "https://www.nseindia.com/api/fiiDiiTurnover"
        resp2 = session.get(url2, timeout=15)
        if resp2.status_code == 200:
            data2 = resp2.json()
            return _parse_fii_dii_turnover(data2, last_n_days)
    except Exception as e:
        print(f"  [WARN] FII/DII turnover API also failed: {e}")

    # Final fallback: return empty with message
    print("  [INFO] FII/DII data from NSE API not accessible (common outside India).")
    print("  [INFO] Returning empty DataFrame. Data will be available when run from India IP.")
    return pd.DataFrame(columns=[
        "date", "fii_buy_value", "fii_sell_value", "fii_net_value",
        "dii_buy_value", "dii_sell_value", "dii_net_value"
    ])


def _parse_fii_dii_json(data: list | dict, last_n_days: int) -> pd.DataFrame:
    """Parse the fiidiiTradeReact JSON response."""
    rows = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("data", data.get("results", []))
    else:
        return pd.DataFrame()

    for item in items:
        category = item.get("category", "").upper()
        date_str = item.get("date", "")
        buy_val = _parse_crore(item.get("buyValue", 0))
        sell_val = _parse_crore(item.get("sellValue", 0))
        net_val = _parse_crore(item.get("netValue", buy_val - sell_val))

        rows.append({
            "date": date_str,
            "category": category,
            "buy_value": buy_val,
            "sell_value": sell_val,
            "net_value": net_val,
        })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # Pivot so FII and DII are separate columns
    fii = df[df["category"].str.contains("FII|FPI", case=False, na=False)].copy()
    dii = df[df["category"].str.contains("DII", case=False, na=False)].copy()

    if fii.empty and dii.empty:
        return pd.DataFrame()

    result_rows = []
    all_dates = sorted(df["date"].unique(), reverse=True)[:last_n_days]

    for date in all_dates:
        row = {"date": date}
        fii_day = fii[fii["date"] == date]
        dii_day = dii[dii["date"] == date]

        if not fii_day.empty:
            row["fii_buy_value"] = fii_day.iloc[0]["buy_value"]
            row["fii_sell_value"] = fii_day.iloc[0]["sell_value"]
            row["fii_net_value"] = fii_day.iloc[0]["net_value"]
        else:
            row["fii_buy_value"] = row["fii_sell_value"] = row["fii_net_value"] = 0

        if not dii_day.empty:
            row["dii_buy_value"] = dii_day.iloc[0]["buy_value"]
            row["dii_sell_value"] = dii_day.iloc[0]["sell_value"]
            row["dii_net_value"] = dii_day.iloc[0]["net_value"]
        else:
            row["dii_buy_value"] = row["dii_sell_value"] = row["dii_net_value"] = 0

        result_rows.append(row)

    return pd.DataFrame(result_rows)


def _parse_fii_dii_turnover(data: dict, last_n_days: int) -> pd.DataFrame:
    """Parse the fiiDiiTurnover JSON response (alternative format)."""
    rows = []
    for key in ["fpiData", "diiData"]:
        items = data.get(key, [])
        for item in items:
            rows.append({
                "category": "FII" if "fpi" in key.lower() else "DII",
                "date": item.get("date", ""),
                "buy_value": _parse_crore(item.get("buyValue", 0)),
                "sell_value": _parse_crore(item.get("sellValue", 0)),
                "net_value": _parse_crore(item.get("netValue", 0)),
            })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    return _pivot_fii_dii(df, last_n_days)


def _pivot_fii_dii(df: pd.DataFrame, last_n_days: int) -> pd.DataFrame:
    """Pivot raw FII/DII rows into a unified table."""
    result_rows = []
    all_dates = sorted(df["date"].unique(), reverse=True)[:last_n_days]

    for date in all_dates:
        row = {"date": date}
        for cat, prefix in [("FII", "fii"), ("DII", "dii")]:
            cat_day = df[(df["date"] == date) & (df["category"] == cat)]
            if not cat_day.empty:
                row[f"{prefix}_buy_value"] = cat_day.iloc[0]["buy_value"]
                row[f"{prefix}_sell_value"] = cat_day.iloc[0]["sell_value"]
                row[f"{prefix}_net_value"] = cat_day.iloc[0]["net_value"]
            else:
                row[f"{prefix}_buy_value"] = row[f"{prefix}_sell_value"] = row[f"{prefix}_net_value"] = 0
        result_rows.append(row)

    return pd.DataFrame(result_rows)


def _parse_crore(value) -> float:
    """Parse a value that might be string with commas, or already numeric."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return float(value.replace(",", "").replace(" ", ""))
    return 0.0


def get_net_fii_dii_summary(last_n_days: int = 5) -> dict:
    """
    Get a summary of net FII and DII activity over last N days.
    Returns dict with total net values and daily breakdown.
    """
    df = fetch_fii_dii_activity(last_n_days)

    if df.empty:
        return {
            "days_available": 0,
            "total_fii_net": 0,
            "total_dii_net": 0,
            "combined_net": 0,
            "daily_data": [],
            "note": "FII/DII data unavailable (likely geo-restricted)",
        }

    return {
        "days_available": len(df),
        "total_fii_net": round(df["fii_net_value"].sum(), 2),
        "total_dii_net": round(df["dii_net_value"].sum(), 2),
        "combined_net": round(df["fii_net_value"].sum() + df["dii_net_value"].sum(), 2),
        "daily_data": df.to_dict("records"),
    }
