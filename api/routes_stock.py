"""
GET /stock/{symbol} — Indicator inspector breakdown for a single stock.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from engine.default_config import get_default_config
from engine.screener import screen_stock_stage1, screen_stock_stage2
from engine.inspector import build_inspector_report
from engine.insights import generate_insights
from api.data_helper import get_stock_bundle, prepare_stock_result

router = APIRouter()


@router.get("/stock/{symbol}")
def get_stock_inspector(
    symbol: str,
    include_stage2: bool = Query(True, description="Include Stage 2 breakout analysis"),
    config: Optional[str] = Query(None, description="JSON config override (URL-encoded)"),
):
    """
    Get full indicator inspector breakdown for a single stock.
    Shows every filter's status, actual value, threshold, and whether enabled.
    """
    symbol = symbol.strip().upper()

    # Parse config override if provided
    screen_config = get_default_config()
    if config:
        import json
        try:
            overrides = json.loads(config)
            for key, value in overrides.items():
                if key in screen_config and isinstance(screen_config[key], dict) and isinstance(value, dict):
                    screen_config[key].update(value)
                else:
                    screen_config[key] = value
        except json.JSONDecodeError:
            raise HTTPException(400, "Invalid JSON in config parameter")

    # Fetch data
    try:
        bundle = get_stock_bundle(symbol)
    except Exception as e:
        raise HTTPException(502, f"Could not fetch data for {symbol}: {e}")

    daily_df = bundle["daily_df"]
    stock_data = bundle["stock_data"]
    df_4h = bundle.get("df_4h")

    # Run Stage 1
    s1 = screen_stock_stage1(symbol, daily_df, stock_data, screen_config, df_4h)

    # Run Stage 2 if requested and Stage 1 passed
    s2 = None
    if include_stage2 and s1["passed"]:
        s2 = screen_stock_stage2(symbol, daily_df, stock_data, s1, screen_config)

    # Build inspector report
    report = build_inspector_report(s1, s2)

    # Build response
    inspector_items = []
    for r in report:
        inspector_items.append({
            "filter_name": r["filter_name"],
            "category": r["category"],
            "status": r["status"],
            "actual_value": str(r["actual_value"]),
            "threshold": str(r["threshold"]),
            "enabled": r["enabled"],
            "details": r.get("details", ""),
            "timeframe": r.get("timeframe", "daily"),
        })

    # Summary counts
    total = len(report)
    passes = sum(1 for r in report if r["status"] == "PASS")
    fails = sum(1 for r in report if r["status"] == "FAIL")
    borderlines = sum(1 for r in report if r["status"] == "BORDERLINE")
    skipped = sum(1 for r in report if r["status"] == "SKIPPED")

    # Stock info
    stock_info = prepare_stock_result(stock_data)

    response = {
        "symbol": symbol,
        "stock_info": stock_info,
        "stage1_passed": s1["passed"],
        "stage1_score": s1["score"],
        "scores": {
            "total": s1["scores"]["total_score"],
            "technical": s1["scores"]["technical_score"],
            "fundamental": s1["scores"]["fundamental_score"],
            "breakout": s1["scores"]["breakout_score"],
            "liquidity": s1["scores"]["liquidity_score"],
        },
        "inspector": inspector_items,
        "summary": {
            "total_filters": total,
            "pass": passes,
            "fail": fails,
            "borderline": borderlines,
            "skipped": skipped,
        },
    }

    if s2:
        response["stage2_passed"] = s2["passed"]
        response["stage2_score"] = s2["score"]
        response["stop_loss"] = s2.get("stop_loss")
        response["target"] = s2.get("target")
        response["risk_reward"] = s2.get("risk_reward")

    # AI Insights
    insights = generate_insights(symbol, s1, s2)
    response["insights"] = insights

    return response


@router.get("/stock/{symbol}/insights")
def get_stock_insights(symbol: str):
    """
    Get AI-powered insights for a stock.
    Analyzes all indicators and explains what they mean,
    what's likely to happen, and recommended action.
    """
    symbol = symbol.strip().upper()
    config = get_default_config()

    try:
        bundle = get_stock_bundle(symbol)
    except Exception as e:
        raise HTTPException(502, f"Could not fetch data for {symbol}: {e}")

    s1 = screen_stock_stage1(symbol, bundle["daily_df"], bundle["stock_data"], config)
    s2 = None
    if s1["passed"]:
        s2 = screen_stock_stage2(symbol, bundle["daily_df"], bundle["stock_data"], s1, config)

    insights = generate_insights(symbol, s1, s2)
    return insights


@router.get("/stock/{symbol}/optimal-levels")
def get_optimal_levels(symbol: str):
    """
    Optimal Entry / Stop / Target trade plan for a single stock.

    Synthesizes:
      • Trend regime (EMA21/50/200) + ADX strength
      • ATR-based stop placement
      • 2.0R baseline target (capped near 52W high)
      • VCP / Bull Flag / Cup-and-Handle / Pivot Breakout pattern detection
      • Multi-Factor Score percentile
      • Multi-Timeframe (1D/1W/1M) confluence
      • Bulk + block deal institutional flows
      • Volume contraction quality
      • Exhaustion penalty (60d return + RSI)

    Returns a 0-100 confidence score with a full breakdown and rationale.
    Educational tool — not investment advice.
    """
    from engine.optimal_levels import compute_optimal_levels
    symbol = symbol.strip().upper()
    plan = compute_optimal_levels(symbol)
    if plan is None:
        raise HTTPException(404, f"Insufficient history for {symbol} (need 60+ bars)")
    return plan
