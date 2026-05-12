"""
NSE IPO fetcher — Upcoming, Currently Open, and Recently Listed IPOs.

Uses curl_cffi with Chrome impersonation (same approach as nse_events.py)
to bypass NSE's TLS/JA3 fingerprint protection.

Two-tier cache:
  - fresh cache (≤6h):  served directly
  - stale cache (≤7d):  served as fallback if NSE blocks us
"""

import os
import re
import time
import pickle
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store", "ipo")
os.makedirs(CACHE_DIR, exist_ok=True)

FRESH_TTL = 6 * 3600        # 6h fresh
STALE_TTL = 7 * 24 * 3600   # 7d stale fallback

_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8",
    "Referer": "https://www.nseindia.com/market-data/all-upcoming-issues-ipo",
    "X-Requested-With": "XMLHttpRequest",
}


def _cache_path(name: str) -> str:
    return os.path.join(CACHE_DIR, f"{name}.pkl")


def _read_cache(name: str) -> Tuple[Optional[list], Optional[float]]:
    """Return (data, age_seconds) or (None, None)."""
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


def _num(s) -> Optional[float]:
    """Best-effort parse of price/lot strings like '₹1,200', '1200-1230', '100'."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    txt = str(s).replace(",", "").replace("₹", "").strip()
    # If it's a range like "1200-1230", return the upper bound
    if "-" in txt:
        parts = [p.strip() for p in txt.split("-") if p.strip()]
        try:
            return float(parts[-1])
        except Exception:
            return None
    m = re.search(r"-?\d+\.?\d*", txt)
    if not m:
        return None
    try:
        return float(m.group(0))
    except Exception:
        return None


def _date_iso(s) -> Optional[str]:
    """Normalise to ISO YYYY-MM-DD. Accepts dd-MMM-YYYY, dd/MM/YYYY, dd-MM-YYYY."""
    if not s:
        return None
    txt = str(s).strip()
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d %b %Y"):
        try:
            return datetime.strptime(txt, fmt).date().isoformat()
        except Exception:
            continue
    return None


def _normalise(items: List[Dict[str, Any]], section: str) -> List[Dict[str, Any]]:
    """Pull common fields out of NSE's idiosyncratic response shapes."""
    out: List[Dict[str, Any]] = []
    for it in items or []:
        try:
            row = {
                "symbol": (it.get("symbol") or it.get("symbolName") or "").strip().upper(),
                "company": (it.get("companyName") or it.get("name") or it.get("issuer", "")).strip(),
                "open_date": _date_iso(it.get("issueStartDate") or it.get("openDate") or it.get("issueOpenDate")),
                "close_date": _date_iso(it.get("issueEndDate") or it.get("closeDate") or it.get("issueCloseDate")),
                "listing_date": _date_iso(it.get("listingDate") or it.get("expectedListingDate")),
                "price_band": (it.get("issuePrice") or it.get("priceRange") or it.get("priceBand") or "").strip() if isinstance(it.get("issuePrice") or it.get("priceRange") or it.get("priceBand"), str) else "",
                "min_invest": _num(it.get("minimumAmount") or it.get("minAmount")),
                "lot_size": _num(it.get("lotSize") or it.get("marketLot")),
                "issue_size": (it.get("issueSize") or it.get("size") or "").strip() if isinstance(it.get("issueSize") or it.get("size"), str) else "",
                "subscription": _num(it.get("subscriptionTimes")) if it.get("subscriptionTimes") is not None else None,
                "status": (it.get("status") or "").strip(),
                "series": (it.get("series") or "EQ").strip().upper(),
                "section": section,
            }
            # Drop entries with no usable identifiers
            if not row["symbol"] and not row["company"]:
                continue
            out.append(row)
        except Exception:
            continue
    return out


def _fetch_section(s, url: str) -> List[Dict[str, Any]]:
    """Pull a single NSE endpoint, return its raw list."""
    try:
        r = s.get(url, timeout=10)
        if not r.ok:
            return []
        raw = r.json()
        if isinstance(raw, dict):
            return raw.get("data") or raw.get("Data") or []
        return raw if isinstance(raw, list) else []
    except Exception:
        return []


def _fetch_live() -> Dict[str, List[Dict[str, Any]]]:
    """Hit NSE IPO endpoints with Chrome impersonation. Returns dict of buckets."""
    try:
        from curl_cffi import requests as cf
    except Exception:
        return {"open": [], "upcoming": [], "recent": []}

    out = {"open": [], "upcoming": [], "recent": []}
    try:
        s = cf.Session(impersonate="chrome131")
        # Prime cookies
        try:
            s.get("https://www.nseindia.com", timeout=6)
        except Exception:
            pass
        try:
            s.get("https://www.nseindia.com/market-data/all-upcoming-issues-ipo", timeout=8)
        except Exception:
            pass
        s.headers.update(_HEADERS)

        # Currently open
        out["open"] = _normalise(
            _fetch_section(s, "https://www.nseindia.com/api/ipo-current-issue"),
            "open",
        )
        # Upcoming
        out["upcoming"] = _normalise(
            _fetch_section(
                s, "https://www.nseindia.com/api/all-upcoming-issues?category=ipo"
            ),
            "upcoming",
        )
        # Recently listed
        out["recent"] = _normalise(
            _fetch_section(
                s, "https://www.nseindia.com/api/public-past-issues?index=equities"
            ),
            "recent",
        )
    except Exception:
        pass

    return out


def fetch_ipos() -> Dict[str, Any]:
    """Public entry — returns {open: [...], upcoming: [...], recent: [...], cached: bool, age_hours: float}.

    Two-tier cache: serve fresh (<6h) directly; otherwise fetch live; fall
    back to stale (<7d) on any error.
    """
    cache_name = "ipo_all"
    cached, age = _read_cache(cache_name)
    if cached is not None and age is not None and age < FRESH_TTL:
        cached["cached"] = True
        cached["age_hours"] = round(age / 3600, 1)
        return cached

    live = _fetch_live()
    total = sum(len(v) for v in live.values())
    if total > 0:
        live["cached"] = False
        live["age_hours"] = 0.0
        _save_cache(cache_name, live)
        return live

    # Live failed — fall back to stale cache if within 7d
    if cached is not None and age is not None and age < STALE_TTL:
        cached["cached"] = True
        cached["age_hours"] = round(age / 3600, 1)
        cached["stale"] = True
        return cached

    return {"open": [], "upcoming": [], "recent": [], "cached": False, "age_hours": 0.0, "stale": False}
