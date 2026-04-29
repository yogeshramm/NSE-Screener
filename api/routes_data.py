"""
GET  /data/status     — Check daily download status
POST /data/download   — Trigger batch download for specific symbols
GET  /data/dates      — List available download dates
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import threading

from data.batch_downloader import (
    get_downloaded_symbols, get_available_dates, run_batch_download
)
from data.nse_symbols import NIFTY_500_FALLBACK, get_nifty500_live


_CRON_STATUS_FILE = Path(__file__).parent.parent / "data_store" / "cron_status.json"
_INTEGRITY_REPORT_FILE = Path(__file__).parent.parent / "data_store" / "integrity_report.json"
# >48h with no successful run = stale. Cron is daily (~24h cadence); one missed
# run leaves room for a one-day NSE holiday before alarming.
_CRON_STALE_HOURS = 48.0
# >10 days without an integrity check = stale (it's weekly).
_INTEGRITY_STALE_DAYS = 10.0


def _read_integrity_summary() -> dict:
    if not _INTEGRITY_REPORT_FILE.exists():
        return {"integrity_seen": False, "integrity_stale": True,
                "integrity_with_issues": None, "integrity_total": None,
                "integrity_issue_counts": None, "integrity_checked_at": None,
                "integrity_age_days": None}
    try:
        rep = json.loads(_INTEGRITY_REPORT_FILE.read_text())
        checked = rep.get("checked_at")
        checked_dt = datetime.fromisoformat(checked) if checked else None
        age_days = ((datetime.now(timezone.utc) - checked_dt).total_seconds() / 86400.0
                    if checked_dt else None)
        return {
            "integrity_seen": True,
            "integrity_stale": age_days is None or age_days > _INTEGRITY_STALE_DAYS,
            "integrity_with_issues": rep.get("with_issues"),
            "integrity_total": rep.get("total_symbols"),
            "integrity_issue_counts": rep.get("issue_counts"),
            "integrity_checked_at": checked,
            "integrity_age_days": round(age_days, 1) if age_days is not None else None,
            "integrity_load_errors": rep.get("load_errors"),
        }
    except Exception as e:
        return {"integrity_seen": False, "integrity_stale": True,
                "integrity_with_issues": None, "integrity_total": None,
                "integrity_issue_counts": None, "integrity_checked_at": None,
                "integrity_age_days": None,
                "integrity_error": f"unreadable: {e}"}


def _read_cron_status() -> dict:
    """Return cron freshness summary. Never raises — UI reads this on every page load."""
    if not _CRON_STATUS_FILE.exists():
        return {"cron_seen": False, "cron_stale": True, "cron_hours_since": None,
                "cron_last_ok": None, "cron_last_error": None}
    try:
        data = json.loads(_CRON_STATUS_FILE.read_text())
        completed = data.get("completed_at")
        completed_dt = datetime.fromisoformat(completed) if completed else None
        hours = ((datetime.now(timezone.utc) - completed_dt).total_seconds() / 3600.0
                 if completed_dt else None)
        ok = bool(data.get("ok"))
        return {
            "cron_seen": True,
            "cron_stale": (hours is None) or (hours > _CRON_STALE_HOURS) or (not ok),
            "cron_hours_since": round(hours, 1) if hours is not None else None,
            "cron_last_ok": ok,
            "cron_last_completed_at": completed,
            "cron_last_error": (data.get("error") or "")[:300] if not ok else None,
            "cron_duration_s": data.get("duration_s"),
        }
    except Exception as e:
        return {"cron_seen": False, "cron_stale": True, "cron_hours_since": None,
                "cron_last_ok": None, "cron_last_error": f"unreadable: {e}"}

router = APIRouter()

# Track fundamental sync state
_fa_sync = {"running": False, "done": 0, "total": 0, "complete": False}

# Track if a download is in progress
_download_in_progress = False
_download_stats = None
_download_lock = threading.Lock()  # serialise catchup trigger checks
_last_catchup_attempt = 0.0       # epoch — used to back off failed catchups
_CATCHUP_COOLDOWN = 300            # 5 min — don't retry catchup if it just ran


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
        **_read_cron_status(),
        **_read_integrity_summary(),
    }


@router.get("/data/integrity")
def integrity_report():
    """Return the latest integrity check report (full detail). 404 if never run."""
    if not _INTEGRITY_REPORT_FILE.exists():
        raise HTTPException(404, "Integrity check has not run yet.")
    try:
        return json.loads(_INTEGRITY_REPORT_FILE.read_text())
    except Exception as e:
        raise HTTPException(500, f"Could not read report: {e}")


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

    with _download_lock:
        if _download_in_progress:
            raise HTTPException(409, "A download is already in progress")
        _download_in_progress = True   # claim flag inside the lock

    if request.symbols:
        symbols = [s.strip().upper() for s in request.symbols]
    elif request.use_fallback:
        symbols = list(NIFTY_500_FALLBACK)
    else:
        symbols = list(NIFTY_500_FALLBACK)

    def _bg_download():
        global _download_in_progress, _download_stats
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

    with _download_lock:
        if _download_in_progress:
            raise HTTPException(409, "A download is already in progress")
        _download_in_progress = True   # claim flag inside the lock

    def _bg_setup():
        global _download_in_progress, _download_stats
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
    global _download_in_progress, _download_stats, _last_catchup_attempt
    import time as _time

    # Atomic in-progress check + cooldown to prevent race-condition stampede
    with _download_lock:
        if _download_in_progress:
            return {"status": "in_progress", "message": "A download is already in progress"}
        if _time.time() - _last_catchup_attempt < _CATCHUP_COOLDOWN:
            wait_s = int(_CATCHUP_COOLDOWN - (_time.time() - _last_catchup_attempt))
            return {"status": "cooldown", "message": f"Recently ran. Try again in {wait_s}s."}
        _last_catchup_attempt = _time.time()
        _download_in_progress = True   # claim the flag here, before background thread starts

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
        # _download_in_progress already True (set in trigger_catchup with the lock)
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


# ============ FUNDAMENTAL SYNC (screener.in) ============

@router.get("/data/fa-status")
def fa_status():
    """Check fundamental data sync status."""
    import os
    fund_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store", "fundamentals")
    fund_count = len([f for f in os.listdir(fund_dir) if f.endswith('.pkl')]) if os.path.exists(fund_dir) else 0

    try:
        nifty500 = get_nifty500_live()
    except Exception:
        nifty500 = list(NIFTY_500_FALLBACK)

    fund_syms = set(f.replace('.pkl','') for f in os.listdir(fund_dir) if f.endswith('.pkl')) if os.path.exists(fund_dir) else set()
    missing = [s for s in nifty500 if s not in fund_syms]

    return {
        "nifty500_count": len(nifty500),
        "fundamentals_count": fund_count,
        "missing_count": len(missing),
        "sync_running": _fa_sync["running"],
        "sync_done": _fa_sync["done"],
        "sync_total": _fa_sync["total"],
        "sync_complete": _fa_sync["complete"] or len(missing) == 0,
    }


@router.post("/data/fa-sync")
def fa_sync():
    """Start fetching missing fundamental data from screener.in for Nifty 500."""
    if _fa_sync["running"]:
        return {"message": "Already running", "done": _fa_sync["done"], "total": _fa_sync["total"]}

    import os
    fund_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store", "fundamentals")
    os.makedirs(fund_dir, exist_ok=True)
    fund_syms = set(f.replace('.pkl','') for f in os.listdir(fund_dir) if f.endswith('.pkl'))

    try:
        nifty500 = get_nifty500_live()
    except Exception:
        nifty500 = list(NIFTY_500_FALLBACK)

    missing = [s for s in nifty500 if s not in fund_syms]
    if not missing:
        _fa_sync["complete"] = True
        return {"message": "All Nifty 500 fundamentals are up to date", "missing": 0}

    _fa_sync["running"] = True
    _fa_sync["done"] = 0
    _fa_sync["total"] = len(missing)
    _fa_sync["complete"] = False

    def _run_sync():
        import pickle
        from data.screener_in import fetch_from_screener
        import time

        for i, sym in enumerate(missing):
            try:
                data = fetch_from_screener(sym, use_cache=False)
                if data and "error" not in data:
                    fpath = os.path.join(fund_dir, f"{sym}.pkl")
                    with open(fpath, "wb") as f:
                        pickle.dump(data, f)
                _fa_sync["done"] = i + 1
            except Exception as e:
                print(f"  FA sync error for {sym}: {e}")
                _fa_sync["done"] = i + 1
            if i < len(missing) - 1:
                time.sleep(1.0)

        _fa_sync["running"] = False
        _fa_sync["complete"] = True
        print(f"  FA sync complete: {_fa_sync['done']}/{_fa_sync['total']}")

    thread = threading.Thread(target=_run_sync, daemon=True)
    thread.start()

    return {"message": f"Syncing {len(missing)} stocks from screener.in", "missing": len(missing)}
