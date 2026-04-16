"""
NSE Corporate Events fetcher (earnings, dividends, splits, bonuses).

Uses NSE's public corporate-actions endpoint with realistic browser headers.
Cached to disk for 24h to avoid repeated hits.
"""

import os
import json
import time
import pickle
from datetime import datetime, timedelta
from typing import List, Dict, Any
import requests


CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store", "events")
os.makedirs(CACHE_DIR, exist_ok=True)
CACHE_TTL = 24 * 3600  # 24h

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-IN,en;q=0.9",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-event-calendar",
}


def _cache_path(name: str) -> str:
    return os.path.join(CACHE_DIR, f"{name}.pkl")


def _load_cache(name: str):
    p = _cache_path(name)
    if not os.path.exists(p):
        return None
    try:
        age = time.time() - os.path.getmtime(p)
        if age > CACHE_TTL:
            return None
        return pickle.load(open(p, "rb"))
    except Exception:
        return None


def _save_cache(name: str, data):
    try:
        pickle.dump(data, open(_cache_path(name), "wb"))
    except Exception:
        pass


def fetch_nse_events(days_ahead: int = 14) -> List[Dict[str, Any]]:
    """Fetch upcoming corporate events from NSE. Returns list of {symbol, event, date, purpose}."""
    cached = _load_cache("events")
    if cached:
        return cached

    events: List[Dict[str, Any]] = []
    session = requests.Session()
    session.headers.update(_HEADERS)
    try:
        # Prime cookies
        session.get("https://www.nseindia.com", timeout=10)
        # Fetch corporate events
        today = datetime.utcnow()
        from_date = today.strftime("%d-%m-%Y")
        to_date = (today + timedelta(days=days_ahead)).strftime("%d-%m-%Y")
        url = f"https://www.nseindia.com/api/event-calendar?from={from_date}&to={to_date}"
        r = session.get(url, timeout=15)
        if r.ok:
            raw = r.json()
            for item in raw if isinstance(raw, list) else raw.get("data", []):
                events.append({
                    "symbol": item.get("symbol", ""),
                    "company": item.get("company", ""),
                    "event": item.get("purpose", "Event"),
                    "date": item.get("date", ""),
                    "bm_date": item.get("bm_date", ""),
                })
        # Also try corporate actions (dividends, splits, bonuses)
        url2 = f"https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date={from_date}&to_date={to_date}"
        r2 = session.get(url2, timeout=15)
        if r2.ok:
            for item in r2.json() if isinstance(r2.json(), list) else r2.json().get("data", []):
                events.append({
                    "symbol": item.get("symbol", ""),
                    "company": item.get("comp", ""),
                    "event": item.get("subject", "Corporate Action"),
                    "date": item.get("exDate") or item.get("recDate", ""),
                    "bm_date": "",
                })
    except Exception as e:
        return [{"error": f"NSE fetch failed: {e}"}]

    _save_cache("events", events)
    return events


def events_for_symbol(symbol: str) -> List[Dict[str, Any]]:
    events = fetch_nse_events()
    sym = symbol.upper()
    return [e for e in events if e.get("symbol", "").upper() == sym]
