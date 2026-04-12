"""
POST /screen — Run full screening with filter config JSON.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from engine.default_config import get_default_config
from engine.screener import screen_stock_stage1, screen_stock_stage2, run_full_screen
from api.data_helper import get_stock_bundle, prepare_stock_result

router = APIRouter()


class ScreenRequest(BaseModel):
    symbols: list[str]
    config: Optional[dict] = None
    stage2: bool = True


def _clean_result(result: dict) -> dict:
    """Remove non-serializable objects from screening result."""
    clean = {}
    skip_keys = {"indicator_results", "fundamental_results",
                 "breakout_indicator_results"}

    for k, v in result.items():
        if k in skip_keys:
            # Summarize indicator results
            if k == "indicator_results":
                clean["indicators"] = [
                    {
                        "name": r.get("indicator", ""),
                        "type": r.get("type", ""),
                        "status": r.get("status", ""),
                        "value": str(r.get("value", "")),
                        "threshold": str(r.get("threshold", "")),
                        "timeframe": r.get("timeframe", "daily"),
                    }
                    for r in v
                ]
            elif k == "fundamental_results":
                clean["fundamentals"] = {
                    name: {
                        "status": r.get("status", ""),
                        "value": str(r.get("value", "")),
                        "threshold": str(r.get("threshold", "")),
                    }
                    for name, r in v.items()
                }
            elif k == "breakout_results":
                clean["breakout_filters"] = {
                    name: {
                        "status": r.get("status", ""),
                        "value": str(r.get("value", "")),
                    }
                    for name, r in v.items()
                }
            continue
        if hasattr(v, 'to_dict'):
            continue
        clean[k] = v

    # Clean nested dicts
    if "late_entry" in clean:
        le = clean["late_entry"]
        clean["late_entry"] = {
            "status": le.get("status"),
            "value": le.get("value"),
            "details": le.get("details"),
        }

    if "scores" in clean:
        clean["scores"] = {k: v for k, v in clean["scores"].items()
                          if k != "breakdown"}

    return clean


@router.post("/screen")
def run_screen(request: ScreenRequest):
    """
    Run the full 2-stage screening on a list of stock symbols.

    Pass a config JSON to override any filter parameter.
    If no config is provided, defaults are used.
    """
    if not request.symbols:
        raise HTTPException(400, "At least one symbol required")

    if len(request.symbols) > 50:
        raise HTTPException(400, "Maximum 50 symbols per request")

    config = get_default_config()
    if request.config:
        # Deep merge user config into defaults
        for key, value in request.config.items():
            if key in config and isinstance(config[key], dict) and isinstance(value, dict):
                config[key].update(value)
            else:
                config[key] = value

    # Fetch data for all symbols
    stocks = []
    errors = []
    for symbol in request.symbols:
        try:
            bundle = get_stock_bundle(symbol.strip().upper())
            stocks.append(bundle)
        except Exception as e:
            errors.append({"symbol": symbol, "error": str(e)})

    if not stocks:
        raise HTTPException(502, f"Could not fetch data for any symbol. Errors: {errors}")

    # Run screening
    result = run_full_screen(stocks, config)

    # Clean results for JSON serialization
    stage1 = [_clean_result(r) for r in result["stage1_results"]]
    stage2 = [_clean_result(r) for r in result["stage2_results"]]

    return {
        "total_screened": result["total_screened"],
        "stage1_passed": result["stage1_passed"],
        "stage2_passed": result["stage2_passed"],
        "stage1_results": stage1,
        "stage2_results": stage2,
        "fetch_errors": errors,
    }
