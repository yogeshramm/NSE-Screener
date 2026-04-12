"""
Scoring System — 100 Points Total
Computes a score for each stock based on indicator results.

Technical Strength: up to 40 points
Fundamental Quality: up to 30 points
Breakout Quality: up to 20 points
Liquidity & Market Structure: up to 10 points
"""

# Which indicators contribute to which scoring category
TECHNICAL_INDICATORS = [
    "EMA", "RSI", "MACD", "Supertrend", "ADX", "Awesome Oscillator",
    "OBV", "CMF", "ROC", "Anchored VWAP", "Pivot Levels",
    "Hidden Bullish Divergence",
    "Ehlers Fisher Transform", "Klinger Volume Oscillator",
    "Chande Momentum Oscillator", "Elder Force Index", "Vortex Indicator",
]

FUNDAMENTAL_INDICATORS = [
    "roe", "roce", "debt_to_equity", "eps", "free_cash_flow",
    "institutional_holdings", "analyst_ratings", "pe_ratio",
]

BREAKOUT_INDICATORS = [
    "Bollinger Band Squeeze", "Stochastic RSI", "Williams %R",
    "VWAP Bands", "Ichimoku Cloud", "ATR",
    "breakout_proximity", "breakout_volume", "breakout_rsi",
    "breakout_candle", "supply_zone",
]

LIQUIDITY_INDICATORS = [
    "Volume Surge", "Sector Performance",
    "daily_turnover", "free_float",
]


def compute_score(indicator_results: list[dict], fundamental_results: dict,
                  config: dict) -> dict:
    """
    Compute the total score for a stock.

    Args:
        indicator_results: list of dicts from run_all_indicators()
        fundamental_results: dict of fundamental filter results
        config: the filter configuration (for scoring weights)

    Returns:
        dict with:
          - total_score: 0-100
          - technical_score: 0-40
          - fundamental_score: 0-30
          - breakout_score: 0-20
          - liquidity_score: 0-10
          - breakdown: detailed per-indicator scores
    """
    weights = config.get("scoring", {})
    tech_weight = weights.get("technical_weight", 40)
    fund_weight = weights.get("fundamental_weight", 30)
    breakout_weight = weights.get("breakout_weight", 20)
    liq_weight = weights.get("liquidity_weight", 10)

    # Build lookup from indicator results
    ind_lookup = {}
    for r in indicator_results:
        ind_lookup[r["indicator"]] = r

    breakdown = {}

    # --- Technical Score ---
    tech_pass = 0
    tech_total = 0
    tech_borderline = 0
    for name in TECHNICAL_INDICATORS:
        r = ind_lookup.get(name)
        if r is None or r.get("status") == "SKIPPED":
            continue
        tech_total += 1
        if r["status"] == "PASS":
            tech_pass += 1
            breakdown[name] = "PASS"
        elif r["status"] == "BORDERLINE":
            tech_borderline += 1
            breakdown[name] = "BORDERLINE"
        else:
            breakdown[name] = "FAIL"

    if tech_total > 0:
        technical_score = (tech_pass / tech_total) * tech_weight
        # Borderline gets half credit
        technical_score += (tech_borderline / tech_total) * tech_weight * 0.5
    else:
        technical_score = 0

    # --- Fundamental Score ---
    fund_pass = 0
    fund_total = 0
    fund_borderline = 0
    for name in FUNDAMENTAL_INDICATORS:
        r = fundamental_results.get(name)
        if r is None or r.get("status") == "SKIPPED":
            continue
        fund_total += 1
        if r["status"] == "PASS":
            fund_pass += 1
            breakdown[name] = "PASS"
        elif r["status"] == "BORDERLINE":
            fund_borderline += 1
            breakdown[name] = "BORDERLINE"
        else:
            breakdown[name] = "FAIL"

    if fund_total > 0:
        fundamental_score = (fund_pass / fund_total) * fund_weight
        fundamental_score += (fund_borderline / fund_total) * fund_weight * 0.5
    else:
        fundamental_score = 0

    # --- Breakout Score ---
    brk_pass = 0
    brk_total = 0
    brk_borderline = 0
    for name in BREAKOUT_INDICATORS:
        # Check indicator results
        r = ind_lookup.get(name) or fundamental_results.get(name)
        if r is None or r.get("status") == "SKIPPED":
            continue
        brk_total += 1
        if r["status"] == "PASS":
            brk_pass += 1
            breakdown[name] = "PASS"
        elif r["status"] == "BORDERLINE":
            brk_borderline += 1
            breakdown[name] = "BORDERLINE"
        else:
            breakdown[name] = "FAIL"

    if brk_total > 0:
        breakout_score = (brk_pass / brk_total) * breakout_weight
        breakout_score += (brk_borderline / brk_total) * breakout_weight * 0.5
    else:
        breakout_score = 0

    # --- Liquidity Score ---
    liq_pass = 0
    liq_total = 0
    liq_borderline = 0
    for name in LIQUIDITY_INDICATORS:
        r = ind_lookup.get(name) or fundamental_results.get(name)
        if r is None or r.get("status") == "SKIPPED":
            continue
        liq_total += 1
        if r["status"] == "PASS":
            liq_pass += 1
            breakdown[name] = "PASS"
        elif r["status"] == "BORDERLINE":
            liq_borderline += 1
            breakdown[name] = "BORDERLINE"
        else:
            breakdown[name] = "FAIL"

    if liq_total > 0:
        liquidity_score = (liq_pass / liq_total) * liq_weight
        liquidity_score += (liq_borderline / liq_total) * liq_weight * 0.5
    else:
        liquidity_score = 0

    total = technical_score + fundamental_score + breakout_score + liquidity_score

    return {
        "total_score": round(total, 1),
        "technical_score": round(technical_score, 1),
        "fundamental_score": round(fundamental_score, 1),
        "breakout_score": round(breakout_score, 1),
        "liquidity_score": round(liquidity_score, 1),
        "breakdown": breakdown,
    }
