"""
NSE Corporate Events fetcher (earnings, dividends, splits, bonuses).

Uses curl_cffi (Chrome-131 impersonation) because NSE's edge has tightened
against plain requests — homepage returns 403 and API endpoints time out
without TLS/JA3 fingerprint spoofing.

Two-tier cache:
  - fresh cache (≤24h): served directly, no network.
  - stale cache (≤7d):  served when NSE is blocking us. Still better than
                        an empty page, with a flag so the UI can show a
                        "last updated N hours ago" hint.
"""

import os
import time
import pickle
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple, Optional

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store", "events")
os.makedirs(CACHE_DIR, exist_ok=True)
FRESH_TTL = 48 * 3600        # 48h — fresh, skip network entirely (events rarely change within 2 days)
STALE_TTL = 7 * 24 * 3600    # 7d  — serve as fallback when NSE is blocking

_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-event-calendar",
    "X-Requested-With": "XMLHttpRequest",
}


def _cache_path(name: str) -> str:
    return os.path.join(CACHE_DIR, f"{name}.pkl")


def _read_cache(name: str) -> Tuple[Optional[list], Optional[float]]:
    """Return (data, age_seconds) or (None, None) if missing."""
    p = _cache_path(name)
    if not os.path.exists(p):
        return None, None
    try:
        age = time.time() - os.path.getmtime(p)
        data = pickle.load(open(p, "rb"))
        return data, age
    except Exception:
        return None, None


def _save_cache(name: str, data):
    try:
        pickle.dump(data, open(_cache_path(name), "wb"))
    except Exception:
        pass


def _fetch_live(days_ahead: int) -> List[Dict[str, Any]]:
    """Hit NSE APIs with Chrome impersonation. Returns [] on any failure."""
    try:
        from curl_cffi import requests as cf
    except Exception:
        return []

    events: List[Dict[str, Any]] = []
    try:
        s = cf.Session(impersonate="chrome131")
        # Prime cookies via the actual calendar page (not just homepage — that
        # isn't enough with NSE's current protection).
        try:
            s.get("https://www.nseindia.com", timeout=6)
        except Exception:
            pass
        try:
            s.get("https://www.nseindia.com/companies-listing/corporate-filings-event-calendar",
                  timeout=8)
        except Exception:
            pass

        s.headers.update(_HEADERS)
        today = datetime.utcnow()
        from_d = today.strftime("%d-%m-%Y")
        to_d = (today + timedelta(days=days_ahead)).strftime("%d-%m-%Y")

        # 1. Event calendar (earnings, board meetings)
        try:
            r = s.get(
                f"https://www.nseindia.com/api/event-calendar?from={from_d}&to={to_d}",
                timeout=10,
            )
            if r.ok:
                raw = r.json()
                items = raw if isinstance(raw, list) else raw.get("data", [])
                for item in items or []:
                    events.append({
                        "symbol": item.get("symbol", ""),
                        "company": item.get("company", ""),
                        "event": item.get("purpose", "Event"),
                        "date": item.get("date", ""),
                        "bm_date": item.get("bm_date", ""),
                    })
        except Exception:
            pass

        # 2. Corporate actions (dividends, splits, bonuses)
        try:
            r2 = s.get(
                f"https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date={from_d}&to_date={to_d}",
                timeout=10,
            )
            if r2.ok:
                raw2 = r2.json()
                items2 = raw2 if isinstance(raw2, list) else raw2.get("data", [])
                for item in items2 or []:
                    events.append({
                        "symbol": item.get("symbol", ""),
                        "company": item.get("comp", ""),
                        "event": item.get("subject", "Corporate Action"),
                        "date": item.get("exDate") or item.get("recDate", ""),
                        "bm_date": "",
                    })
        except Exception:
            pass
    except Exception:
        return []

    return events


def fetch_nse_events(days_ahead: int = 14) -> List[Dict[str, Any]]:
    """Return upcoming corporate events. Shape: list of {symbol, company, event, date, bm_date}.
    If NSE fetch fails and a cache ≤7d old exists, serves that. If the cache
    itself is error-shaped (legacy format), ignores it."""
    cached, age = _read_cache("events")
    # Ignore legacy error payloads ([{"error": "..."}]) in cache.
    def _valid(d):
        return isinstance(d, list) and all(
            isinstance(x, dict) and "error" not in x for x in d
        )

    # Fresh cache → return as-is.
    if cached is not None and age is not None and age <= FRESH_TTL and _valid(cached):
        return cached

    live = _fetch_live(days_ahead)
    if live:
        _save_cache("events", live)
        return live

    # Live failed. Serve stale cache if it's within the 7-day grace window.
    if cached is not None and age is not None and age <= STALE_TTL and _valid(cached):
        return cached

    return []


def events_for_symbol(symbol: str) -> List[Dict[str, Any]]:
    sym = symbol.upper()
    return [e for e in fetch_nse_events() if e.get("symbol", "").upper() == sym]
