"""
POST /screen — Run full screening with filter config JSON.
"""

import json
import math

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional

from engine.default_config import get_default_config
from engine.screener import run_full_screen
from api.data_helper import get_stock_bundle

router = APIRouter()


def _json_safe(o):
    """Fallback for json.dumps default= — handles numpy/pandas leftovers.
    FastAPI's jsonable_encoder is a recursive walk that's pathologically slow
    on 2-3 MB nested results (~120s observed). Returning a Response with
    stdlib json.dumps cuts that to ~50ms."""
    if hasattr(o, "item"):  # numpy scalar
        try:
            return o.item()
        except Exception:
            pass
    if hasattr(o, "isoformat"):  # datetime / Timestamp
        return o.isoformat()
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    return str(o)


class ScreenRequest(BaseModel):
    symbols: Optional[list[str]] = None
    config: Optional[dict] = None
    stage2: bool = True
    scan_all: bool = False
    scope: str = "nifty500"  # "nifty200", "nifty500", "all"
    min_price: float = 50.0
    min_volume: int = 100000


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
    config = get_default_config()
    if request.config:
        for key, value in request.config.items():
            if key in config and isinstance(config[key], dict) and isinstance(value, dict):
                config[key].update(value)
            else:
                config[key] = value

    # Determine which symbols to screen
    if request.scan_all or not request.symbols:
        from data.nse_history import get_history_stats, load_history
        from data.nse_symbols import NIFTY_500_FALLBACK, get_nifty500_live
        from setup_data import FUNDAMENTALS_DIR

        hist = get_history_stats()
        all_symbols = set(hist.get("symbols", []))
        fund_symbols = set()
        if FUNDAMENTALS_DIR.exists():
            fund_symbols = {f.stem for f in FUNDAMENTALS_DIR.glob("*.pkl")}

        # Resolve Nifty 500 — prefer live NSE list (500 symbols); the
        # hardcoded NIFTY_500_FALLBACK is actually a curated 187-symbol
        # subset and was never the real index.
        try:
            nifty500_list = list(get_nifty500_live())
        except Exception:
            nifty500_list = list(NIFTY_500_FALLBACK)
        # Nifty 200 — first 200 of the live Nifty 500 (index constituents
        # are market-cap ordered). Falls back to first 120 of the fallback
        # list if live fetch failed.
        nifty200_list = nifty500_list[:200] if len(nifty500_list) >= 200 else list(NIFTY_500_FALLBACK[:120])

        # Choose scope
        if request.scope == "nifty200":
            candidates = [s for s in nifty200_list if s in all_symbols]
        elif request.scope == "nifty500":
            candidates = [s for s in nifty500_list if s in all_symbols]
        else:  # "all"
            candidates = sorted(fund_symbols & all_symbols) + sorted(all_symbols - fund_symbols)

        # Pre-filter + fetch in one pass: load each history pickle ONCE,
        # check price/volume, then build the bundle from the already-loaded
        # df + only the fundamentals pickle. Previously this loop loaded
        # history once for the gate, and get_stock_bundle() loaded it AGAIN
        # via load_stock_full() — doubling disk reads on every scan. After
        # the Angel backfill the per-stock pkl grew from ~480 rows to ~2477,
        # so the double-load went from annoying to 100s+.
        import pickle
        from setup_data import FUNDAMENTALS_DIR

        symbols = []
        prefetched: dict[str, dict] = {}
        skipped = 0
        for sym in candidates:
            hist_df = load_history(sym)
            if hist_df is None or len(hist_df) < 50:
                skipped += 1
                continue
            last_close = hist_df["Close"].iloc[-1]
            avg_vol = hist_df["Volume"].mean()
            if last_close < request.min_price:
                skipped += 1
                continue
            if avg_vol < request.min_volume:
                skipped += 1
                continue
            symbols.append(sym)

            stock_data = {
                "symbol": sym,
                "daily_history": hist_df,
                "daily_rows": len(hist_df),
                "latest_close": round(float(last_close), 2),
                "latest_date": str(hist_df.index[-1].date()),
                "average_volume": int(avg_vol),
            }
            fund_path = FUNDAMENTALS_DIR / f"{sym}.pkl"
            if fund_path.exists():
                try:
                    with open(fund_path, "rb") as f:
                        stock_data.update(pickle.load(f))
                except Exception:
                    pass
            prefetched[sym] = {
                "symbol": sym,
                "daily_df": hist_df,
                "stock_data": stock_data,
                "df_4h": None,
                "source": "nse+screener.in",
            }

        if not symbols:
            raise HTTPException(400, f"No stocks passed pre-filter (price > ₹{request.min_price}, volume > {request.min_volume:,}). Try a broader scope.")
    else:
        symbols = [s.strip().upper() for s in request.symbols]
        prefetched = {}

    # Fetch data for all symbols (use prefetched bundles when available)
    stocks = []
    errors = []
    for symbol in symbols:
        try:
            bundle = prefetched.get(symbol) or get_stock_bundle(symbol)
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

    payload = {
        "total_screened": result["total_screened"],
        "stage1_passed": result["stage1_passed"],
        "stage2_passed": result["stage2_passed"],
        "stage1_results": stage1,
        "stage2_results": stage2,
        "fetch_errors": errors,
    }
    # Bypass FastAPI's jsonable_encoder (pathologically slow on this payload —
    # 120s+ on 2-3 MB nested dicts). Pre-serialize with stdlib json.dumps.
    body = json.dumps(payload, default=_json_safe, allow_nan=False).encode()
    return Response(content=body, media_type="application/json")
