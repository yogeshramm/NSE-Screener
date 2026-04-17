"""
Analyst data via crawl4ai (Chromium stealth) + cloudscraper (Cloudflare bypass).
JS-protected sites: Moneycontrol, Tickertape, Trendlyne.

Tickertape: parse __NEXT_DATA__ JSON (cleaner than regex on HTML).
Trendlyne:  cloudscraper bypasses their Cloudflare in ~1s — no browser.
Moneycontrol: crawl4ai + hardcoded SC_ID map (8 large caps).
"""
import re, json, asyncio, threading
from typing import Optional, Dict, Any, List

_CRAWLER = None
_LOCK = threading.Lock()


async def _get_crawler():
    global _CRAWLER
    if _CRAWLER is None:
        from crawl4ai import AsyncWebCrawler, BrowserConfig
        bcfg = BrowserConfig(
            headless=True, browser_type="chromium",
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport_width=1920, viewport_height=1080,
        )
        _CRAWLER = AsyncWebCrawler(config=bcfg, verbose=False)
        await _CRAWLER.__aenter__()
    return _CRAWLER


def _run_cfg():
    from crawl4ai import CrawlerRunConfig
    return CrawlerRunConfig(
        magic=True, wait_until="networkidle", page_timeout=25000,
        simulate_user=True, override_navigator=True,
    )


def _num(s):
    try: return float(str(s).replace(",", "").strip())
    except Exception: return None


# ---------- Moneycontrol via crawl4ai ----------
_MC_INDUSTRY_MAP = {
    "RELIANCE": ("refineries", "relianceindustries", "RI"),
    "TCS": ("computerssoftware", "tataconsultancyservices", "TCS"),
    "INFY": ("computerssoftware", "infosys", "IT"),
    "HDFCBANK": ("banks-private-sector", "hdfcbank", "HDF01"),
    "ICICIBANK": ("banks-private-sector", "icicibank", "ICI02"),
    "ITC": ("cigarettes", "itc", "ITC"),
    "WIPRO": ("computerssoftware", "wipro", "W"),
    "SBIN": ("banks-public-sector", "statebankindia", "SBI"),
}


async def fetch_mc(symbol: str) -> Optional[Dict[str, Any]]:
    m = _MC_INDUSTRY_MAP.get(symbol)
    if not m: return None
    ind, name, sc = m
    url = f"https://www.moneycontrol.com/india/stockpricequote/{ind}/{name}/{sc}"
    try:
        c = await _get_crawler()
        r = await c.arun(url=url, config=_run_cfg())
        if not r.success or not r.html: return None
        h = r.html
        out: Dict[str, Any] = {"source_url": url}
        for pat in [r"target\s*price[^<>]{0,100}(?:rs\.?|₹)\s*([\d,]+\.?\d*)",
                   r"consensus[^<>]{0,100}(?:rs\.?|₹)\s*([\d,]+\.?\d*)",
                   r'"targetPrice"\s*:\s*"?([\d,\.]+)']:
            mm = re.search(pat, h, re.I)
            if mm:
                out["target_price"] = _num(mm.group(1)); break
        blk_m = re.search(r"broker[\s\S]{0,15000}?(?=</section|</div>\s*<section|$)", h, re.I)
        blk = blk_m.group(0) if blk_m else ""
        if blk:
            for rk in ["strong buy", "buy", "hold", "sell", "strong sell"]:
                k = rk.replace(" ", "_")
                cnt = len(re.findall(rf"\b{rk}\b", blk, re.I))
                if 0 < cnt <= 20: out[k] = cnt
        if out.get("target_price") is None and not any(out.get(k, 0) for k in ["strong_buy","buy","hold","sell","strong_sell"]):
            return None
        return out
    except Exception: return None


# ---------- Tickertape via crawl4ai, parse __NEXT_DATA__ ----------
_TT_SLUG_OVERRIDES = {
    "RELIANCE": "reliance-industries-RELI",
    "TCS": "tata-consultancy-services-TCS",
    "INFY": "infosys-INFY",
    "HDFCBANK": "hdfc-bank-HDBK",
    "ITC": "itc-ITC",
    "ICICIBANK": "icici-bank-ICIB",
    "WIPRO": "wipro-WIPR",
    "SBIN": "state-bank-of-india-SBI",
    "HINDUNILVR": "hindustan-unilever-HUL",
    "LT": "larsen-and-toubro-LT",
    "BAJFINANCE": "bajaj-finance-BAF",
    "BHARTIARTL": "bharti-airtel-BRTI",
    "ASIANPAINT": "asian-paints-API",
    "MARUTI": "maruti-suzuki-india-MRTI",
    "HCLTECH": "hcl-technologies-HCLT",
    "AXISBANK": "axis-bank-AXBK",
    "KOTAKBANK": "kotak-mahindra-bank-KMB",
    "SUNPHARMA": "sun-pharmaceutical-industries-SUN",
    "TATAMOTORS": "tata-motors-TAMO",
    "NESTLEIND": "nestle-india-NEST",
    "TATAPOWER": "tata-power-company-TTPW",
    "ULTRACEMCO": "ultratech-cement-ULTC",
    "TITAN": "titan-company-TITN",
    "ADANIENT": "adani-enterprises-APSE",
    "POWERGRID": "power-grid-corporation-of-india-PGRD",
    "NTPC": "ntpc-NTPC",
    "ONGC": "oil-and-natural-gas-corporation-ONGC",
    "COALINDIA": "coal-india-COAL",
    "TECHM": "tech-mahindra-TEML",
    "M&M": "mahindra-and-mahindra-MAHM",
}


async def fetch_tickertape(symbol: str) -> Optional[Dict[str, Any]]:
    slug = _TT_SLUG_OVERRIDES.get(symbol)
    candidates = []
    if slug: candidates.append(f"https://www.tickertape.in/stocks/{slug}")
    # Fallback: lowercase symbol (rare hit)
    candidates.append(f"https://www.tickertape.in/stocks/{symbol.lower()}")
    try:
        c = await _get_crawler()
        for url in candidates:
            r = await c.arun(url=url, config=_run_cfg())
            if not (r.success and r.html and len(r.html) > 50000): continue
            h = r.html
            # Parse __NEXT_DATA__ JSON — authoritative source
            mj = re.search(r'<script id="__NEXT_DATA__"[^>]*>({.*?})</script>', h, re.S)
            if not mj: continue
            try: data = json.loads(mj.group(1))
            except Exception: continue
            pp = data.get("props", {}).get("pageProps", {})
            ss = pp.get("securitySummary", {})
            fc = ss.get("forecast") or {}
            out = {"source_url": url}
            tot = fc.get("totalReco")
            pct_buy = fc.get("percBuyReco")
            if isinstance(tot, (int, float)) and tot > 0:
                out["analysts"] = int(tot)
                # Derive buy/hold/sell from percBuy: high pct → dominantly buy
                if isinstance(pct_buy, (int, float)):
                    buy = int(round(tot * pct_buy / 100))
                    out["buy"] = buy
                    out["hold"] = tot - buy
                    out["perc_buy"] = round(pct_buy, 1)
            # Note: forecastsHistory.price contains historical price-at-date, not forward
            # analyst target. Tickertape's target isn't in the public JSON, so we skip it.
            if out.get("analysts") or out.get("target_price"):
                return out
    except Exception: pass
    return None


# ---------- Trendlyne via cloudscraper (Cloudflare bypass, no browser) ----------
_TL_ID_MAP = {
    "RELIANCE": 1257, "TCS": 783, "INFY": 630, "HDFCBANK": 576, "ICICIBANK": 651,
    "ITC": 670, "WIPRO": 1549, "SBIN": 1378, "HINDUNILVR": 611, "LT": 834,
    "BAJFINANCE": 239, "BHARTIARTL": 278, "ASIANPAINT": 170, "MARUTI": 921,
    "HCLTECH": 571, "AXISBANK": 204, "KOTAKBANK": 810,
}
_TL_SLUG_MAP = {
    "RELIANCE": "reliance-industries-ltd", "TCS": "tata-consultancy-services-ltd",
    "INFY": "infosys-ltd", "HDFCBANK": "hdfc-bank-ltd", "ICICIBANK": "icici-bank-ltd",
    "ITC": "itc-ltd", "WIPRO": "wipro-ltd", "SBIN": "state-bank-of-india",
    "HINDUNILVR": "hindustan-unilever-ltd", "LT": "larsen--toubro-ltd",
    "BAJFINANCE": "bajaj-finance-ltd", "BHARTIARTL": "bharti-airtel-ltd",
    "ASIANPAINT": "asian-paints-ltd", "MARUTI": "maruti-suzuki-india-ltd",
    "HCLTECH": "hcl-technologies-ltd", "AXISBANK": "axis-bank-ltd",
    "KOTAKBANK": "kotak-mahindra-bank-ltd",
}


async def fetch_trendlyne(symbol: str) -> Optional[Dict[str, Any]]:
    tid = _TL_ID_MAP.get(symbol); slug = _TL_SLUG_MAP.get(symbol)
    if not tid or not slug: return None
    try:
        # Run cloudscraper in thread-executor (it's blocking)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _tl_sync, tid, symbol, slug)
    except Exception: return None


def _tl_sync(tid, symbol, slug) -> Optional[Dict[str, Any]]:
    try:
        import cloudscraper
        s = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "darwin", "desktop": True})
        url = f"https://trendlyne.com/equity/{tid}/{symbol}/{slug}/"
        r = s.get(url, timeout=15)
        if r.status_code != 200 or len(r.text) < 50000: return None
        t = r.text
        out = {"source_url": url}
        # DVM Score (Durability / Valuation / Momentum) — Trendlyne unique
        for pat in [r'"dvmScore"\s*:\s*"?(\d+)',
                   r'DVM\s*[sS]core[\s\S]{0,200}?(\d{1,3})\s*/\s*100',
                   r'class="dvm-score[^"]*"[^>]*>(\d+)']:
            m = re.search(pat, t)
            if m:
                out["dvm_score"] = int(m.group(1)); break
        # Target price — look in any data attributes or inline JSON
        for pat in [r'"targetPrice"\s*:\s*"?([\d,\.]+)',
                   r'"consensusTarget"\s*:\s*"?([\d,\.]+)',
                   r'data-target-price="([\d,\.]+)"',
                   r'[Cc]onsensus\s*Target[^<>]{0,80}(?:Rs\.?|₹)\s*([\d,]+\.?\d*)']:
            m = re.search(pat, t)
            if m:
                v = _num(m.group(1))
                if v and v > 10: out["target_price"] = v; break
        # Analyst count — only trust if >= 3 (avoids phantom "1 analyst" noise from
        # random mentions like "Top 1 Analyst pick")
        m = re.search(r"(\d+)\s*[Aa]nalysts?", t)
        if m:
            n = int(m.group(1))
            if 3 <= n < 100: out["analysts"] = n
        # Any broker distribution counts in a bounded block
        blk_m = re.search(r"[Bb]roker\s*[Rr]ecom[\s\S]{0,3000}", t)
        blk = blk_m.group(0) if blk_m else ""
        if blk:
            for rk in ["strong buy", "buy", "hold", "sell", "strong sell"]:
                k = rk.replace(" ", "_")
                cnt = len(re.findall(rf"\b{rk}\b", blk, re.I))
                if 0 < cnt <= 20: out[k] = cnt
        # Only return if we got something meaningful
        if out.get("target_price") or out.get("analysts") or out.get("dvm_score"):
            return out
    except Exception: pass
    return None


async def fetch_all_crawl_sources(symbol: str) -> Dict[str, Any]:
    """Parallel fetch MC + Tickertape + Trendlyne. Returns dict with each key present (None if failed)."""
    try:
        mc, tt, tl = await asyncio.gather(
            fetch_mc(symbol), fetch_tickertape(symbol), fetch_trendlyne(symbol),
            return_exceptions=False,
        )
        return {"moneycontrol": mc, "tickertape": tt, "trendlyne": tl}
    except Exception as e:
        return {"moneycontrol": None, "tickertape": None, "trendlyne": None, "_error": str(e)}
