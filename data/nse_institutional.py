"""
Institutional Radar data: bulk deals, block deals, delivery % leaderboard, breadth.

NSE public JSON endpoints + local history pickles. 24h disk cache.
Gracefully degrades if NSE is geo-restricted.
"""
import os, pickle, time, csv, io, requests
from datetime import datetime, timedelta
from typing import List, Dict, Any

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store", "institutional")
os.makedirs(CACHE_DIR, exist_ok=True)
TTL = 24 * 3600
STALE_TTL = 7 * 24 * 3600

# Rolling-window CSVs on archives.nseindia.com — no auth, no cookies, ~30 days
# back. The /api/historical/cm/bulk endpoint consistently 404s, so the archives
# path is the reliable server-side source. BSE's equivalent redirects to an
# error page.
BULK_ARCHIVE = "https://archives.nseindia.com/content/equities/bulk.csv"
BLOCK_ARCHIVE = "https://archives.nseindia.com/content/equities/block.csv"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-IN,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}


def _cp(name): return os.path.join(CACHE_DIR, f"{name}.pkl")


def _lc(name):
    p = _cp(name)
    if not os.path.exists(p): return None
    try:
        if time.time() - os.path.getmtime(p) > TTL: return None
        return pickle.load(open(p, "rb"))
    except Exception: return None


def _sc(name, data):
    try: pickle.dump(data, open(_cp(name), "wb"))
    except Exception: pass


def _session():
    s = requests.Session(); s.headers.update(_HEADERS)
    try: s.get("https://www.nseindia.com/", timeout=10)
    except Exception: pass
    return s


def _fetch_json(url, sess=None, tries=2):
    sess = sess or _session()
    for _ in range(tries):
        try:
            r = sess.get(url, timeout=15)
            if r.status_code == 200:
                return r.json()
        except Exception: pass
    return None


def _nifty500_set() -> set:
    """Live Nifty 500 with fallback — the game is Nifty-only so non-Nifty
    deals are noise we drop."""
    try:
        from data.nse_symbols import get_nifty500_live, NIFTY_500_FALLBACK
        try: return set(get_nifty500_live())
        except Exception: return set(NIFTY_500_FALLBACK)
    except Exception: return set()


def _parse_archive_csv(text: str) -> List[Dict[str, Any]]:
    """Parse archives.nseindia.com bulk/block CSV. Columns: Date, Symbol,
    Security Name, Client Name, Buy/Sell, Quantity Traded, Trade Price /
    Wght. Avg. Price, Remarks."""
    rows: List[Dict[str, Any]] = []
    try:
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            sym = (row.get("Symbol") or "").strip().upper()
            if not sym or sym == "NO RECORDS": continue
            try: qty = int((row.get("Quantity Traded") or "0").replace(",", ""))
            except Exception: qty = 0
            try: price = float((row.get("Trade Price / Wght. Avg. Price") or "0").replace(",", ""))
            except Exception: price = 0.0
            rows.append({
                "date": (row.get("Date") or "").strip(),
                "symbol": sym,
                "company": (row.get("Security Name") or "").strip(),
                "client": (row.get("Client Name") or "").strip(),
                "action": (row.get("Buy/Sell") or "").strip().upper(),
                "qty": qty,
                "price": price,
                "remarks": (row.get("Remarks") or "").strip() or None,
            })
    except Exception: return []
    return rows


def _fetch_archive(url: str) -> List[Dict[str, Any]]:
    try:
        r = requests.get(url, headers={"User-Agent": _HEADERS["User-Agent"]}, timeout=10)
        if not r.ok or len(r.content) < 80: return []
        return _parse_archive_csv(r.text)
    except Exception: return []


def _read_cache_tier(name: str):
    """(data, age_seconds) or (None, None). Don't auto-drop past TTL — caller
    decides fresh vs stale."""
    p = _cp(name)
    if not os.path.exists(p): return None, None
    try:
        age = time.time() - os.path.getmtime(p)
        return pickle.load(open(p, "rb")), age
    except Exception: return None, None


def fetch_bulk_deals(days: int = 7, nifty_only: bool = True) -> List[Dict[str, Any]]:
    """Rolling ~30-day bulk deals from archives.nseindia.com. `days` is kept
    for backward-compat with callers that filter by age client-side; the
    underlying archive always returns the full rolling window."""
    cached, age = _read_cache_tier("bulk_archive")
    if cached is not None and age is not None and age <= TTL and isinstance(cached, list):
        return _apply_filter_deals(cached, days, nifty_only)
    live = _fetch_archive(BULK_ARCHIVE)
    if live:
        _sc("bulk_archive", live)
        return _apply_filter_deals(live, days, nifty_only)
    # Stale-cache fallback when archive is unreachable
    if cached is not None and age is not None and age <= STALE_TTL and isinstance(cached, list):
        return _apply_filter_deals(cached, days, nifty_only)
    return []


def fetch_block_deals(days: int = 7, nifty_only: bool = True) -> List[Dict[str, Any]]:
    cached, age = _read_cache_tier("block_archive")
    if cached is not None and age is not None and age <= TTL and isinstance(cached, list):
        return _apply_filter_deals(cached, days, nifty_only)
    live = _fetch_archive(BLOCK_ARCHIVE)
    # Block CSV can legitimately be empty ("NO RECORDS"); only persist if we
    # parsed anything, otherwise keep the previous cache (even if stale).
    if live:
        _sc("block_archive", live)
        return _apply_filter_deals(live, days, nifty_only)
    if cached is not None and age is not None and age <= STALE_TTL and isinstance(cached, list):
        return _apply_filter_deals(cached, days, nifty_only)
    return []


def _apply_filter_deals(rows: List[Dict[str, Any]], days: int, nifty_only: bool) -> List[Dict[str, Any]]:
    """Apply the Nifty-500 filter + a days-old cutoff. Date parsing is best
    effort — archive uses '17-APR-2026' format."""
    out = rows
    if nifty_only:
        nifty = _nifty500_set()
        if nifty:
            out = [r for r in out if r.get("symbol") in nifty]
    if days and days > 0:
        cutoff = datetime.now() - timedelta(days=days + 1)
        def _parse(d: str):
            for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d"):
                try: return datetime.strptime(d, fmt)
                except Exception: continue
            return None
        filtered = []
        for r in out:
            dt = _parse(r.get("date", ""))
            if dt is None or dt >= cutoff:
                filtered.append(r)
        out = filtered
    return out


def deals_for_symbol(symbol: str) -> Dict[str, List[Dict[str, Any]]]:
    """Both bulk + block deals for one symbol from the rolling archive.
    Used by the per-stock institutional endpoint + future Practice review
    overlay (when the game window overlaps with the last 30 days)."""
    sym = (symbol or "").upper()
    return {
        "bulk": [r for r in fetch_bulk_deals(days=0, nifty_only=False) if r.get("symbol") == sym],
        "block": [r for r in fetch_block_deals(days=0, nifty_only=False) if r.get("symbol") == sym],
    }


def fetch_delivery_leaders(top_n: int = 25) -> List[Dict[str, Any]]:
    """High-delivery-% stocks today (conviction signal). NSE security-wise delivery."""
    cached = _lc("delivery")
    if cached is not None: return cached[:top_n]
    url = "https://www.nseindia.com/api/snapshot-capital-market-delivery"
    data = _fetch_json(url)
    out = []
    if data and isinstance(data, dict):
        items = data.get("data", [])
        for r in items:
            try:
                dp = float(str(r.get("deliveryToTradedQuantity", r.get("deliveryPercent", 0))).replace(",", "") or 0)
                if dp <= 0: continue
                out.append({
                    "symbol": r.get("symbol", ""),
                    "deliv_pct": round(dp, 2),
                    "deliv_qty": int(float(str(r.get("deliveryQuantity", 0)).replace(",", "") or 0)),
                    "traded_qty": int(float(str(r.get("tradedQuantity", 0)).replace(",", "") or 0)),
                    "ltp": float(str(r.get("lastPrice", 0)).replace(",", "") or 0),
                    "pchange": float(str(r.get("pChange", 0)).replace(",", "") or 0),
                })
            except Exception: continue
        out.sort(key=lambda x: x["deliv_pct"], reverse=True)
    _sc("delivery", out)
    return out[:top_n]


def compute_market_breadth() -> Dict[str, Any]:
    """From local history: % above 200-DMA, 52W H/L counts, advance/decline."""
    cached = _lc("breadth")
    if cached is not None: return cached
    HIST = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store", "history")
    if not os.path.exists(HIST):
        return {"total": 0, "above_200dma": 0, "above_200dma_pct": 0, "new_52w_high": 0, "new_52w_low": 0, "advances": 0, "declines": 0}
    total = above = hi = lo = adv = dec = 0
    for f in os.listdir(HIST):
        if not f.endswith(".pkl"): continue
        try:
            df = pickle.load(open(os.path.join(HIST, f), "rb"))
            if len(df) < 200: continue
            total += 1
            c = df["Close"]
            last = float(c.iloc[-1]); prev = float(c.iloc[-2])
            if last > c.tail(200).mean(): above += 1
            w52 = c.tail(252)
            if last >= w52.max() * 0.999: hi += 1
            if last <= w52.min() * 1.001: lo += 1
            if last > prev: adv += 1
            elif last < prev: dec += 1
        except Exception: continue
    out = {
        "total": total,
        "above_200dma": above,
        "above_200dma_pct": round(above / total * 100, 1) if total else 0,
        "new_52w_high": hi,
        "new_52w_low": lo,
        "advances": adv,
        "declines": dec,
        "ad_ratio": round(adv / dec, 2) if dec else 0,
    }
    _sc("breadth", out)
    return out
