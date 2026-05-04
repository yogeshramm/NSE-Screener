"""Market analytics API: RS + sector heatmap + movers."""
import pickle
import time
from pathlib import Path
from fastapi import APIRouter
from engine.market_analytics import compute_rs_ranks, sector_heatmap

router = APIRouter()

_CACHE_DIR = Path(__file__).parent.parent / "data_store" / "market_cache"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)
_TTL = 6 * 3600  # 6 hours
_MOVERS_TTL = 300  # 5 min — movers refresh quickly during market hours


def _cache_get(key: str):
    p = _CACHE_DIR / f"{key}.pkl"
    if not p.exists():
        return None
    if time.time() - p.stat().st_mtime > _TTL:
        return None
    try:
        with open(p, "rb") as f:
            return pickle.load(f)
    except Exception:
        return None


def _cache_set(key: str, data):
    try:
        p = _CACHE_DIR / f"{key}.pkl"
        tmp = p.with_suffix(".tmp")
        with open(tmp, "wb") as f:
            pickle.dump(data, f, protocol=4)
        tmp.replace(p)
    except Exception:
        pass


def _get_universe_syms(universe: str):
    from data.nse_symbols import get_nifty500_live, NIFTY_500_FALLBACK
    import os
    HIST = str(Path(__file__).parent.parent / "data_store" / "history")
    all_h = sorted(f.replace(".pkl", "") for f in os.listdir(HIST) if f.endswith(".pkl")) if os.path.exists(HIST) else []
    try:
        nifty = set(get_nifty500_live())
    except Exception:
        nifty = set(NIFTY_500_FALLBACK)
    if universe == "nifty500":
        return [s for s in all_h if s in nifty]
    if universe == "next500":
        return [s for s in all_h if s not in nifty]
    return all_h


@router.get("/market/rs")
def market_rs(universe: str = "nifty500"):
    """RS percentile rank (1-99) for all stocks in the universe. Cached 6h."""
    key = f"rs_{universe}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    syms = _get_universe_syms(universe)
    ranks = compute_rs_ranks(syms)
    result = {"universe": universe, "count": len(ranks), "rs": ranks}
    _cache_set(key, result)
    return result


@router.get("/market/sector-heatmap")
def market_sector_heatmap(universe: str = "nifty500"):
    """Sector rotation heatmap. Cached 6h."""
    key = f"heatmap_{universe}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    syms = _get_universe_syms(universe)
    result = {"universe": universe, "sectors": sector_heatmap(syms)}
    _cache_set(key, result)
    return result


@router.get("/market/movers")
def market_movers():
    """
    Top 7 gainers + top 7 losers (Nifty 200 live during market hours, EOD
    change otherwise) + top 10 stocks nearest their 52-week high (breakout
    watch) from Nifty 500 historical pkl data.
    Cached 5 min during market hours, 30 min otherwise.
    """
    from data.angel_ltp import is_market_open, get_ltp_bulk, inject_live_candle
    from data.nse_symbols import get_nifty500_live, NIFTY_500_FALLBACK
    from data.sector_map import get_sector
    from setup_data import HISTORY_DIR
    import pandas as pd

    mkt_open = is_market_open()
    cache_ttl = _MOVERS_TTL if mkt_open else 1800
    cache_key = "movers_live" if mkt_open else "movers_eod"

    cached = _cache_get(cache_key)
    if cached is not None and time.time() - cached.get("_ts", 0) < cache_ttl:
        return cached

    try:
        nifty500 = list(get_nifty500_live())
    except Exception:
        nifty500 = list(NIFTY_500_FALLBACK)

    nifty200 = nifty500[:200]

    # ── Step 1: gather per-stock metrics from pkl files ────────────────────────
    rows = []
    near_ath = []   # for breakout watch panel

    for sym in nifty500:
        pkl = HISTORY_DIR / f"{sym}.pkl"
        if not pkl.exists():
            continue
        try:
            import pickle as pk
            with open(pkl, "rb") as f:
                df = pk.load(f)
            if df is None or len(df) < 20:
                continue
            close = df["Close"]
            last = float(close.iloc[-1])
            prev = float(close.iloc[-2]) if len(close) >= 2 else last
            eod_chg = round((last - prev) / prev * 100, 2) if prev else 0

            # 52-week high from the last 252 trading days
            w52 = close.iloc[-252:] if len(close) >= 252 else close
            high52 = float(w52.max())
            pct_from_high = round((last - high52) / high52 * 100, 2) if high52 else 0

            sector = get_sector(sym) or "Other"
            entry = {
                "symbol": sym,
                "price": round(last, 2),
                "change_pct": eod_chg,
                "sector": sector,
                "pct_from_high": pct_from_high,
                "52w_high": round(high52, 2),
            }
            if sym in set(nifty200):
                rows.append(entry)
            near_ath.append({"symbol": sym, "price": round(last, 2),
                             "pct_from_high": pct_from_high,
                             "52w_high": round(high52, 2), "sector": sector})
        except Exception:
            continue

    # ── Step 2: inject live prices for Nifty 200 during market hours ──────────
    if mkt_open and rows:
        syms_200 = [r["symbol"] for r in rows]
        live = get_ltp_bulk(syms_200)
        for r in rows:
            p = live.get(r["symbol"])
            if p and p.get("ltp") and p.get("change_pct") is not None:
                r["price"] = p["ltp"]
                r["change_pct"] = p["change_pct"]

    # ── Step 3: sort + slice ───────────────────────────────────────────────────
    rows.sort(key=lambda x: x["change_pct"], reverse=True)
    gainers = [{"symbol": r["symbol"], "price": r["price"],
                "change_pct": r["change_pct"], "sector": r["sector"]}
               for r in rows[:7]]
    losers  = [{"symbol": r["symbol"], "price": r["price"],
                "change_pct": r["change_pct"], "sector": r["sector"]}
               for r in rows[-7:][::-1]]

    # Breakout watch: nearest to 52W high but not already at it (pct_from_high in [-3, -0.1])
    breakout_watch = sorted(
        [r for r in near_ath if -3.0 <= r["pct_from_high"] < -0.1],
        key=lambda x: x["pct_from_high"], reverse=True  # closest first
    )[:10]

    result = {
        "market_open": mkt_open,
        "gainers": gainers,
        "losers": losers,
        "breakout_watch": breakout_watch,
        "_ts": time.time(),
    }
    _cache_set(cache_key, result)
    return result
