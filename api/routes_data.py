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
    """Check today's data download status."""
    symbols = get_downloaded_symbols()
    return {
        "today_downloaded": len(symbols),
        "ready_for_screening": len(symbols) > 50,
        "download_in_progress": _download_in_progress,
        "last_download": _download_stats,
        "available_dates": get_available_dates()[:5],
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
