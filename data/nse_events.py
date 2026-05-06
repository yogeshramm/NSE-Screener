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
import re
import time
import pickle
from datetime import datetime, timedelta, date as _date
from typing import List, Dict, Any, Tuple, Optional

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store", "events")
os.makedirs(CACHE_DIR, exist_ok=True)
FRESH_TTL     = 48 * 3600        # 48h — fresh NSE cache
STALE_TTL     = 7 * 24 * 3600   # 7d  — NSE fallback window
BSE_FRESH_TTL = 4 * 3600        # 4h  — BSE supplement cache

# Regex to extract scheduled meeting date from BSE HEADLINE
_BSE_DATE_RE = re.compile(r'scheduled\s+on\s+(\d{1,2}/\d{1,2}/\d{4})', re.I)

# Module-level BSE token→NSE symbol map (built once)
_BSE_TOKEN_MAP: Dict[int, str] = {}
_BSE_MAP_READY: bool = False

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


# ── BSE supplement ────────────────────────────────────────────────────────────

def _get_bse_token_map() -> Dict[int, str]:
    """Build {bse_scrip_code: nse_symbol} for stocks cross-listed on both exchanges."""
    global _BSE_TOKEN_MAP, _BSE_MAP_READY
    if _BSE_MAP_READY:
        return _BSE_TOKEN_MAP
    try:
        from data.angel_master import get_master_df, get_nse_equity_df
        df = get_master_df()
        bse = df[(df["exch_seg"] == "BSE") & (df["instrumenttype"] == "")]
        nse_syms = set(
            get_nse_equity_df()["symbol"].str.replace("-EQ", "", regex=False).str.upper()
        )
        # Only keep BSE stocks whose ticker also exists on NSE (cross-listed)
        cross = bse[bse["symbol"].str.upper().isin(nse_syms)]
        _BSE_TOKEN_MAP = {
            int(row["token"]): row["symbol"].upper()
            for _, row in cross.iterrows()
        }
    except Exception:
        pass
    _BSE_MAP_READY = True
    return _BSE_TOKEN_MAP


def _fetch_bse_events() -> List[Dict[str, Any]]:
    """
    Fetch BSE board-meeting intimations (Board Meeting + Result categories).
    Parses the scheduled date from the HEADLINE field, maps BSE scrip codes to
    NSE symbols via Angel master — only cross-listed stocks are kept.
    """
    try:
        from curl_cffi import requests as cf
    except Exception:
        return []

    today = datetime.utcnow()
    # Look 7 days back (catch recently filed intimations for near-future meetings)
    from_d = (today - timedelta(days=7)).strftime("%Y%m%d")
    to_d   = (today + timedelta(days=14)).strftime("%Y%m%d")
    tok_map = _get_bse_token_map()

    s = cf.Session(impersonate="chrome131")
    try:
        s.get("https://www.bseindia.com/", timeout=6)
    except Exception:
        pass
    s.headers.update({"Accept": "application/json, */*", "Referer": "https://www.bseindia.com/"})

    events: List[Dict[str, Any]] = []

    def _scrape(cat: str) -> None:
        for page in range(1, 8):   # up to 350 announcements per category
            try:
                r = s.get(
                    f"https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
                    f"?strCat={cat}&strPrevDate={from_d}&strScrip=&strSearch=P"
                    f"&strToDate={to_d}&strType=C&subcategory=-1&strFrom={page}",
                    timeout=10,
                )
                items = r.json().get("Table", []) if r.ok else []
                if not items:
                    break
                for it in items:
                    scrip_cd = int(it.get("SCRIP_CD", 0) or 0)
                    nse_sym = tok_map.get(scrip_cd)
                    if not nse_sym:
                        continue
                    # Skip "Outcome of Board Meeting" — those already happened
                    subcat = (it.get("SUBCATNAME") or "").lower()
                    if "outcome" in subcat:
                        continue
                    # Extract the meeting date from HEADLINE
                    m = _BSE_DATE_RE.search(it.get("HEADLINE") or "")
                    if not m:
                        continue
                    parts = m.group(1).split("/")
                    day, mon, yr = parts[0].zfill(2), parts[1].zfill(2), parts[2]
                    date_iso = f"{yr}-{mon}-{day}"   # YYYY-MM-DD
                    subj = (it.get("NEWSSUB") or "").lower()
                    ev_type = "Financial Results" if "result" in subj else "Board Meeting"
                    events.append({
                        "symbol":  nse_sym,
                        "company": it.get("SLONGNAME", ""),
                        "event":   ev_type,
                        "date":    date_iso,
                        "bm_date": "",
                        "_src":    "BSE",
                    })
                if len(items) < 50:
                    break
            except Exception:
                break

    _scrape("Board+Meeting")
    _scrape("Result")
    return events


# ── Event badge helper ─────────────────────────────────────────────────────────

def get_event_badge(
    symbol: str,
    events: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Return a badge dict if the symbol has an event within [-1, +3] days from today.
    days > 0  = days until event  →  "-3d", "-2d", "Tomorrow"
    days == 0 = event is today    →  "Today"
    days == -1= event was yesterday → "+1d"
    Returns None if no event in window.
    """
    today = _date.today()
    if events is None:
        events = fetch_nse_events()

    sym = symbol.upper().strip()
    best: Optional[Dict] = None
    best_delta: Optional[int] = None

    for e in events:
        if e.get("symbol", "").upper() != sym:
            continue
        date_str = (e.get("date") or "").strip()
        if not date_str:
            continue
        try:
            ev_date = None
            for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d"):
                try:
                    ev_date = datetime.strptime(date_str[:11], fmt).date()
                    break
                except ValueError:
                    continue
            if ev_date is None:
                continue
            delta = (ev_date - today).days
            if -1 <= delta <= 3:
                if best_delta is None or abs(delta) < abs(best_delta):
                    best_delta = delta
                    best = e
        except Exception:
            continue

    if best is None or best_delta is None:
        return None

    raw = (best.get("event") or "Event").lower()
    if any(k in raw for k in ("financial result", "quarterly result", "result")):
        label = "Results"
    elif "dividend" in raw:
        label = "Dividend"
    elif "split" in raw:
        label = "Split"
    elif "bonus" in raw:
        label = "Bonus"
    elif "buyback" in raw:
        label = "Buyback"
    elif "rights" in raw:
        label = "Rights Issue"
    elif "agm" in raw or "annual general" in raw:
        label = "AGM"
    elif "board" in raw:
        label = "Board Mtg"
    elif "fund raising" in raw:
        label = "Fund Raise"
    else:
        label = best.get("event", "Event")[:15].strip()

    if best_delta == 0:
        text = f"* {label} Today"
    elif best_delta == -1:
        text = f"* {label} +1d"
    elif best_delta == 1:
        text = f"* {label} Tomorrow"
    else:
        text = f"* {label} -{best_delta}d"

    return {"label": label, "days": best_delta, "text": text}


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

    # Supplement with BSE events for symbols not already covered by NSE
    try:
        bse_cached, bse_age = _read_cache("bse_events")
        if bse_cached is not None and bse_age is not None and bse_age < BSE_FRESH_TTL:
            bse_events = bse_cached
        else:
            bse_events = _fetch_bse_events()
            if bse_events:
                _save_cache("bse_events", bse_events)
        if bse_events:
            nse_covered = {e["symbol"].upper() for e in live}
            for be in bse_events:
                if be["symbol"].upper() not in nse_covered:
                    live.append(be)
    except Exception:
        pass

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
