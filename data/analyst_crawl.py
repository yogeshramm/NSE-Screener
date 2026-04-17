"""
Analyst data via crawl4ai (headless Chromium w/ stealth).
Handles JS-protected sites: Moneycontrol, Tickertape, Trendlyne.
ET Markets stays on curl_cffi (faster, already works).

Design: keep one warm browser crawler per process (module-level singleton),
run multi-site fetches in parallel via asyncio.gather.
"""
import re, asyncio, threading
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
    if not m: return None  # need mapping — degrade gracefully
    ind, name, sc = m
    url = f"https://www.moneycontrol.com/india/stockpricequote/{ind}/{name}/{sc}"
    try:
        c = await _get_crawler()
        r = await c.arun(url=url, config=_run_cfg())
        if not r.success or not r.html: return None
        h = r.html
        out: Dict[str, Any] = {"source_url": url}
        # Target price (multiple possible labels)
        for pat in [r"target\s*price[^<>]{0,100}(?:rs\.?|₹)\s*([\d,]+\.?\d*)",
                   r"consensus[^<>]{0,100}(?:rs\.?|₹)\s*([\d,]+\.?\d*)",
                   r'"targetPrice"\s*:\s*"?([\d,\.]+)']:
            mm = re.search(pat, h, re.I)
            if mm:
                out["target_price"] = _num(mm.group(1)); break
        # Broker buy/hold/sell counts inside broker-reco block
        blk_m = re.search(r"broker[\s\S]{0,15000}?(?=</section|</div>\s*<section|$)", h, re.I)
        blk = blk_m.group(0) if blk_m else h[:20000]
        out["buy"] = len(re.findall(r"\bbuy\b", blk, re.I))
        out["hold"] = len(re.findall(r"\bhold\b", blk, re.I))
        out["sell"] = len(re.findall(r"\bsell\b", blk, re.I))
        if out.get("target_price") is None and out["buy"] + out["hold"] + out["sell"] < 3:
            return None
        return out
    except Exception: return None


# ---------- Tickertape via crawl4ai ----------
async def fetch_tickertape(symbol: str) -> Optional[Dict[str, Any]]:
    # Tickertape slug format: company-name-SYMBOLSHORT (e.g. reliance-industries-RELI)
    # Use their search API to resolve canonical slug
    try:
        c = await _get_crawler()
        # Try common slug with full symbol first (often works for shorter tickers)
        candidates = [
            f"https://www.tickertape.in/stocks/{symbol.lower()}",
            f"https://www.tickertape.in/stocks/{symbol}",
        ]
        if symbol == "RELIANCE": candidates.insert(0, "https://www.tickertape.in/stocks/reliance-industries-RELI")
        if symbol == "TCS": candidates.insert(0, "https://www.tickertape.in/stocks/tata-consultancy-services-TCS")
        if symbol == "INFY": candidates.insert(0, "https://www.tickertape.in/stocks/infosys-INFY")
        if symbol == "HDFCBANK": candidates.insert(0, "https://www.tickertape.in/stocks/hdfc-bank-HDBK")
        if symbol == "ITC": candidates.insert(0, "https://www.tickertape.in/stocks/itc-ITC")

        for url in candidates:
            r = await c.arun(url=url, config=_run_cfg())
            if r.success and r.html and len(r.html) > 20000 and "Analyst" in r.html:
                h = r.html
                out: Dict[str, Any] = {"source_url": url}
                for pat in [r"target\s*price[^<>]{0,80}(?:rs\.?|₹)\s*([\d,]+\.?\d*)",
                           r"analyst\s*target[^<>]{0,120}([\d,]+\.?\d*)",
                           r'"consensusTarget[^"]*"\s*:\s*"?([\d,\.]+)']:
                    mm = re.search(pat, h, re.I)
                    if mm:
                        out["target_price"] = _num(mm.group(1)); break
                mm = re.search(r"(\d+)\s*analysts?", h, re.I)
                if mm: out["analysts"] = int(mm.group(1))
                # Scope buy/hold/sell counting to the analyst-rating section only
                # Tickertape block format: "Forecasts" or "Analysts say" around rating distribution
                blk_m = re.search(r"(?:forecast|analysts?\s*(?:say|rating)|consensus)[\s\S]{0,3000}", h, re.I)
                blk = blk_m.group(0) if blk_m else ""
                if blk:
                    for rk in ["strong buy", "buy", "hold", "sell", "strong sell"]:
                        k = rk.replace(" ", "_")
                        cnt = len(re.findall(rf"\b{rk}\b", blk, re.I))
                        # sanity cap — any count above 20 is suspicious/phantom
                        if 0 < cnt <= 20: out[k] = cnt
                if out.get("target_price") or out.get("analysts"):
                    return out
    except Exception: pass
    return None


# ---------- Trendlyne via crawl4ai ----------
async def fetch_trendlyne(symbol: str) -> Optional[Dict[str, Any]]:
    try:
        c = await _get_crawler()
        # Trendlyne URL: /equity/<tid>/<SYM>/<slug>/
        # Without a TID map we use their search-redirect URL which takes plain symbol
        url = f"https://trendlyne.com/equity/share-price/{symbol}/"
        r = await c.arun(url=url, config=_run_cfg())
        if not r.success or not r.html or len(r.html) < 20000: return None
        h = r.html
        out: Dict[str, Any] = {"source_url": url}
        for pat in [r"analyst\s*target[^<>]{0,100}(?:rs\.?|₹)?\s*([\d,]+\.?\d*)",
                   r"consensus\s*target[^<>]{0,100}(?:rs\.?|₹)?\s*([\d,]+\.?\d*)",
                   r"target\s*price[^<>]{0,100}(?:rs\.?|₹)?\s*([\d,]+\.?\d*)",
                   r'"meanTarget"\s*:\s*"?([\d,\.]+)']:
            mm = re.search(pat, h, re.I)
            if mm:
                out["target_price"] = _num(mm.group(1)); break
        mm = re.search(r"(\d+)\s*analysts?", h, re.I)
        if mm: out["analysts"] = int(mm.group(1))
        # DVM score is Trendlyne-unique; capture for reference
        mm = re.search(r"DVM[\s\S]{0,200}?(\d{1,3})\s*/\s*100", h)
        if mm: out["dvm_score"] = int(mm.group(1))
        blk_m = re.search(r"(?:broker\s*reco|analyst\s*(?:view|rating|call)|consensus)[\s\S]{0,3000}", h, re.I)
        blk = blk_m.group(0) if blk_m else ""
        if blk:
            for rk in ["strong buy", "buy", "hold", "sell", "strong sell"]:
                k = rk.replace(" ", "_")
                cnt = len(re.findall(rf"\b{rk}\b", blk, re.I))
                if 0 < cnt <= 20: out[k] = cnt
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
