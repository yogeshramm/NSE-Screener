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

    return {
        "today_downloaded": len(symbols),
        "ready_for_screening": len(symbols) > 50,
        "download_in_progress": _download_in_progress,
        "last_download": _download_stats,
        "available_dates": real_dates[:5],
        "today_date": date.today().isoformat(),
        "data_as_of": data_as_of,
        "history_latest_date": latest_price_date,
        "history_symbols": hist.get("total_symbols", 0),
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


@router.get("/data/dates")
def list_dates():
    """List all dates that have downloaded data."""
    dates = get_available_dates()
    result = []
    for d in dates:
        count = len(get_downloaded_symbols(d))
        result.append({"date": d, "stocks": count})
    return {"dates": result}
