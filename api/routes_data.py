"""
GET  /data/status     — Check daily download status
POST /data/download   — Trigger batch download for specific symbols
GET  /data/dates      — List available download dates
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import threading

from data.batch_downloader import (
    get_downloaded_symbols, get_available_dates,
    is_today_downloaded, run_batch_download
)
from data.nse_symbols import NIFTY_500_FALLBACK, get_nifty500_live

router = APIRouter()

# Track fundamental sync state
_fa_sync = {"running": False, "done": 0, "total": 0, "complete": False}

# Track if a download is in progress
_download_in_progress = False
_download_stats = None


@router.get("/data/status")
def data_status():
    """Check today's data download status with date info."""
    from data.nse_history import get_history_stats
    from datetime import date

    symbols = get_downloaded_symbols()
    hist = get_history_stats()
    dates = get_available_dates()

    # Filter out non-date folder names
    real_dates = [d for d in dates if d[:4].isdigit()]
    latest_price_date = hist.get("latest_date", "N/A")

    # data_as_of = most recent actual date we have data for
    if latest_price_date and latest_price_date != "N/A":
        data_as_of = latest_price_date
    elif real_dates:
        data_as_of = real_dates[0]
    else:
        data_as_of = "No data"

    history_count = hist.get("total_symbols", 0)
    total_stocks = max(len(symbols), history_count)

    # Check actual bar count — need minimum 200 bars for EMA 200
    bars_sufficient = False
    if history_count > 0:
        from data.nse_history import load_history
        sample_sym = hist.get("symbols", [])[0] if hist.get("symbols") else None
        if sample_sym:
            sample = load_history(sample_sym)
            bars_sufficient = sample is not None and len(sample) >= 200

    ready = total_stocks > 50 and bars_sufficient
    bar_count = len(sample) if sample_sym and load_history(sample_sym) is not None else 0

    return {
        "today_downloaded": total_stocks,
        "ready_for_screening": ready,
        "needs_history": not bars_sufficient and total_stocks > 0,
        "bars_per_stock": bar_count,
        "download_in_progress": _download_in_progress,
        "last_download": _download_stats,
        "available_dates": real_dates[:5],
        "today_date": date.today().isoformat(),
        "data_as_of": data_as_of,
        "history_latest_date": latest_price_date,
        "history_symbols": history_count,
    }


@router.get("/data/search")
def search_symbols(q: str = ""):
    """Search symbols by partial match. Returns up to 15 results."""
    if not q or len(q) < 1:
        return {"results": []}
    q_upper = q.strip().upper()

    # Get symbols from history pickle files
    import os
    hist_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store", "history")
    if os.path.exists(hist_dir):
        symbols = [f.replace('.pkl','') for f in os.listdir(hist_dir) if f.endswith('.pkl')]
    else:
        symbols = list(get_downloaded_symbols())

    # Try to load cached fundamentals for company names
    import os, pickle
    fund_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store", "fundamentals")
    results = []
    for sym in sorted(symbols):
        name = sym
        # Check if partial match on symbol
        if q_upper in sym:
            # Try cached fundamentals for company name
            try:
                fpath = os.path.join(fund_dir, f"{sym}.pkl")
                if os.path.exists(fpath):
                    with open(fpath, "rb") as f:
                        fund = pickle.load(f)
                    name = fund.get("short_name", sym)
            except Exception:
                pass
            results.append({"symbol": sym, "name": name})
            if len(results) >= 15:
                break

    # If few results by symbol, also search by company name
    if len(results) < 10:
        q_lower = q.strip().lower()
        for sym in sorted(symbols):
            if any(r["symbol"] == sym for r in results):
                continue
            try:
                fpath = os.path.join(fund_dir, f"{sym}.pkl")
                if os.path.exists(fpath):
                    with open(fpath, "rb") as f:
                        fund = pickle.load(f)
                    name = fund.get("short_name", "")
                    if q_lower in name.lower():
                        results.append({"symbol": sym, "name": name})
                        if len(results) >= 15:
                            break
            except Exception:
                continue

    return {"results": results}


class DownloadRequest(BaseModel):
    symbols: Optional[list[str]] = None
    use_fallback: bool = False


@router.post("/data/download")
def trigger_download(request: DownloadRequest):
    """
    Trigger a batch download. Runs in background.
    If no symbols provided, downloads the curated ~150 stock list.
    """
    global _download_in_progress, _download_stats

    if _download_in_progress:
        raise HTTPException(409, "A download is already in progress")

    if request.symbols:
        symbols = [s.strip().upper() for s in request.symbols]
    elif request.use_fallback:
        symbols = list(NIFTY_500_FALLBACK)
    else:
        symbols = list(NIFTY_500_FALLBACK)

    def _bg_download():
        global _download_in_progress, _download_stats
        _download_in_progress = True
        try:
            _download_stats = run_batch_download(symbols=symbols)
        except Exception as e:
            _download_stats = {"error": str(e)}
        finally:
            _download_in_progress = False

    thread = threading.Thread(target=_bg_download, daemon=True)
    thread.start()

    return {
        "status": "started",
        "symbols_count": len(symbols),
        "message": "Download running in background. Check /data/status for progress.",
    }


class HistoryRequest(BaseModel):
    days: int = 370


@router.post("/data/setup")
def trigger_history_setup(request: HistoryRequest):
    """
    Download historical NSE Bhavcopies + screener.in fundamentals.
    This is the full setup — downloads price history for ALL stocks.
    Runs in background. No terminal needed.
    """
    global _download_in_progress, _download_stats

    if _download_in_progress:
        raise HTTPException(409, "A download is already in progress")

    def _bg_setup():
        global _download_in_progress, _download_stats
        _download_in_progress = True
        try:
            from setup_data import download_historical_prices, download_all_fundamentals
            from data.nse_symbols import NIFTY_500_FALLBACK

            # Step 1: Historical prices from NSE
            price_stats = download_historical_prices(days=request.days)

            # Step 2: Fundamentals from screener.in
            fund_stats = download_all_fundamentals(list(NIFTY_500_FALLBACK))

            _download_stats = {
                "type": "full_setup",
                "prices": price_stats,
                "fundamentals": fund_stats,
            }
        except Exception as e:
            _download_stats = {"error": str(e)}
        finally:
            _download_in_progress = False

    thread = threading.Thread(target=_bg_setup, daemon=True)
    thread.start()

    return {
        "status": "started",
        "days": request.days,
        "message": "Full setup running in background. Check /data/status for progress.",
    }


@router.post("/data/catchup")
def trigger_catchup():
    """
    Smart catch-up: detects gap between latest data and today,
    downloads only the missing days from NSE. No terminal needed.
    """
    global _download_in_progress, _download_stats

    if _download_in_progress:
        raise HTTPException(409, "A download is already in progress")

    # Calculate how many days to catch up
    from data.nse_history import get_history_stats
    from datetime import date, datetime

    hist = get_history_stats()
    latest = hist.get("latest_date", None)
    total_symbols = hist.get("total_symbols", 0)

    # Check if any stock has enough history bars
    needs_full_setup = False
    if total_symbols > 0:
        from data.nse_history import load_history
        # Sample a stock to check bar count
        sample_sym = hist.get("symbols", ["RELIANCE"])[0]
        sample_hist = load_history(sample_sym)
        if sample_hist is None or len(sample_hist) < 200:
            needs_full_setup = True
    else:
        needs_full_setup = True

    if latest and latest != "N/A" and not needs_full_setup:
        try:
            latest_dt = datetime.strptime(latest, "%Y-%m-%d").date()
            gap_days = (date.today() - latest_dt).days
        except Exception:
            gap_days = 30
    elif needs_full_setup:
        gap_days = 400  # force full 1-year download
    else:
        gap_days = 400

    if gap_days <= 0:
        return {
            "status": "up_to_date",
            "data_as_of": latest,
            "message": "Data is already current. No catch-up needed.",
        }

    # Ensure minimum 370 days for full indicator coverage
    fetch_days = max(gap_days + 5, 375) if needs_full_setup else gap_days + 5

    def _bg_catchup():
        global _download_in_progress, _download_stats
        _download_in_progress = True
        try:
            from setup_data import download_historical_prices, download_all_fundamentals
            from data.nse_symbols import NIFTY_500_FALLBACK

            price_stats = download_historical_prices(days=fetch_days)
            fund_stats = download_all_fundamentals(list(NIFTY_500_FALLBACK))

            _download_stats = {
                "type": "catchup",
                "gap_days": gap_days,
                "fetched_days": fetch_days,
                "prices": price_stats,
                "fundamentals": fund_stats,
            }
        except Exception as e:
            _download_stats = {"error": str(e)}
        finally:
            _download_in_progress = False

    thread = threading.Thread(target=_bg_catchup, daemon=True)
    thread.start()

    return {
        "status": "started",
        "gap_days": gap_days,
        "fetching_days": fetch_days,
        "last_data": latest,
        "message": f"Catching up {gap_days} days of missing data. Check /data/status.",
    }


@router.get("/data/dates")
def list_dates():
    """List all dates that have downloaded data."""
    dates = get_available_dates()
    real_dates = [d for d in dates if d[:4].isdigit()]
    result = []
    for d in real_dates:
        count = len(get_downloaded_symbols(d))
        result.append({"date": d, "stocks": count})
    return {"dates": result}
