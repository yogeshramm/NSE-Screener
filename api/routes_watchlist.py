"""
GET    /watchlist                      — List all watchlist items
POST   /watchlist/add                  — Add symbol(s) with optional alerts
DELETE /watchlist/{symbol}             — Remove from watchlist
POST   /watchlist/{symbol}/alert       — Add alert to a stock
DELETE /watchlist/{symbol}/alert/{idx} — Remove alert
GET    /watchlist/check                — Check all alerts against latest data
"""

import json
import numpy as np

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

from engine.watchlist import (
    load_watchlist, add_to_watchlist, remove_from_watchlist,
    add_alert, remove_alert, check_single_alert,
)
from engine.presets import load_preset
from engine.default_config import get_default_config
from engine.screener import screen_stock_stage1, screen_stock_stage2
from api.data_helper import get_stock_bundle

router = APIRouter()


def _sanitize(obj):
    """Convert numpy types to native Python for JSON serialization."""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


class AddWatchlistRequest(BaseModel):
    symbols: list[str]
    alerts: Optional[list[dict]] = None


class AddAlertRequest(BaseModel):
    type: str  # "indicator", "price", "preset"
    indicator: Optional[str] = None
    condition: Optional[str] = None
    value: Optional[float] = None
    preset_name: Optional[str] = None
    enabled: bool = True


@router.get("/watchlist")
def list_watchlist():
    items = load_watchlist()
    return {"total": len(items), "items": items}


@router.post("/watchlist/add")
def add_symbols(request: AddWatchlistRequest):
    added = []
    for sym in request.symbols:
        item = add_to_watchlist(sym.strip().upper(), request.alerts)
        added.append(item)
    return {"added": len(added), "items": added}


@router.delete("/watchlist/{symbol}")
def remove_symbol(symbol: str):
    removed = remove_from_watchlist(symbol)
    if not removed:
        raise HTTPException(404, f"{symbol} not in watchlist")
    return {"status": "removed", "symbol": symbol.upper()}


@router.post("/watchlist/{symbol}/alert")
def add_stock_alert(symbol: str, request: AddAlertRequest):
    alert_dict = request.model_dump(exclude_none=True)
    result = add_alert(symbol, alert_dict)
    if result is None:
        raise HTTPException(404, f"{symbol} not in watchlist")
    return {"status": "alert_added", "item": result}


@router.delete("/watchlist/{symbol}/alert/{idx}")
def remove_stock_alert(symbol: str, idx: int):
    result = remove_alert(symbol, idx)
    if result is None:
        raise HTTPException(404, f"{symbol} not in watchlist or alert index invalid")
    return {"status": "alert_removed", "item": result}


@router.get("/watchlist/check")
def check_alerts():
    """Check all watchlist alerts against latest data."""
    items = load_watchlist()
    if not items:
        return {"total": 0, "total_triggered": 0, "results": []}

    default_config = get_default_config()
    results = []

    for item in items:
        symbol = item["symbol"]
        alerts = item.get("alerts", [])
        stock_result = {
            "symbol": symbol,
            "price": None,
            "score": None,
            "stage1_passed": False,
            "alerts_checked": 0,
            "alerts_triggered": 0,
            "alert_results": [],
            "error": None,
        }

        try:
            bundle = get_stock_bundle(symbol)
            daily_df = bundle["daily_df"]
            stock_data = bundle["stock_data"]
            df_4h = bundle.get("df_4h")
            stock_result["price"] = stock_data.get("latest_close") or stock_data.get("current_price")

            # Screen with default config
            s1 = screen_stock_stage1(symbol, daily_df, stock_data, default_config, df_4h)
            s2 = None
            if s1["passed"]:
                s2 = screen_stock_stage2(symbol, daily_df, stock_data, s1, default_config)

            stock_result["stage1_passed"] = s1["passed"]
            stock_result["score"] = s1.get("score", 0)

            for i, alert in enumerate(alerts):
                if alert.get("type") == "preset":
                    # Screen with the preset's config instead
                    preset_name = alert.get("preset_name", "")
                    try:
                        preset_config = load_preset(preset_name)
                        ps1 = screen_stock_stage1(symbol, daily_df, stock_data, preset_config, df_4h)
                        ps2 = None
                        if ps1["passed"]:
                            ps2 = screen_stock_stage2(symbol, daily_df, stock_data, ps1, preset_config)
                        ar = check_single_alert(alert, stock_data, ps1, ps2)
                    except FileNotFoundError:
                        ar = {"triggered": False, "message": f"Preset '{preset_name}' not found", "details": ""}
                else:
                    ar = check_single_alert(alert, stock_data, s1, s2)

                ar["alert_index"] = i
                ar["alert"] = alert
                stock_result["alert_results"].append(ar)
                stock_result["alerts_checked"] += 1
                if ar["triggered"]:
                    stock_result["alerts_triggered"] += 1

        except Exception as e:
            stock_result["error"] = str(e)

        results.append(stock_result)

    total_triggered = sum(r["alerts_triggered"] for r in results)
    return JSONResponse(_sanitize({
        "total": len(results),
        "total_triggered": total_triggered,
        "results": results,
    }))
