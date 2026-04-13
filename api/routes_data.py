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
from data.nse_symbols import NIFTY_500_FALLBACK

router = APIRouter()

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
    ready = total_stocks > 50

    return {
        "today_downloaded": total_stocks,
        "ready_for_screening": ready,
        "download_in_progress": _download_in_progress,
        "last_download": _download_stats,
        "available_dates": real_dates[:5],
        "today_date": date.today().isoformat(),
        "data_as_of": data_as_of,
        "history_latest_date": latest_price_date,
        "history_symbols": history_count,
    }


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

    if latest and latest != "N/A":
        try:
            latest_dt = datetime.strptime(latest, "%Y-%m-%d").date()
            gap_days = (date.today() - latest_dt).days
        except Exception:
            gap_days = 30
    else:
        gap_days = 370  # no data at all — full setup

    if gap_days <= 0:
        return {
            "status": "up_to_date",
            "data_as_of": latest,
            "message": "Data is already current. No catch-up needed.",
        }

    # Add buffer for weekends/holidays
    fetch_days = gap_days + 5

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
