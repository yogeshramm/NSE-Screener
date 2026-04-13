"""
AI Insights Engine
Generates human-readable analysis of what indicators mean for a stock.
Rule-based reasoning: interprets PASS/FAIL patterns and explains
what's likely to happen with the stock.
"""


def generate_insights(symbol: str, stage1_result: dict,
                      stage2_result: dict | None = None) -> dict:
    """
    Generate AI insights for a stock based on its screening results.

    Returns:
        dict with:
          - overall_outlook: "Bullish" / "Bearish" / "Neutral" / "Cautious"
          - confidence: "High" / "Medium" / "Low"
          - summary: 1-2 sentence summary
          - strengths: list of bullish signals with reasoning
          - weaknesses: list of bearish/caution signals
          - action: recommended action
          - risk_factors: key risks
          - indicator_insights: per-indicator interpretation
    """
    indicators = {r["indicator"]: r for r in stage1_result.get("indicator_results", [])}
    fundamentals = stage1_result.get("fundamental_results", {})
    scores = stage1_result.get("scores", {})
    late_entry = stage1_result.get("late_entry", {})

    strengths = []
    weaknesses = []
    indicator_insights = []

    # --- TREND ANALYSIS ---
    ema = indicators.get("EMA", {})
    supertrend = indicators.get("Supertrend", {})
    ichimoku = indicators.get("Ichimoku Cloud", {})

    if ema.get("status") == "PASS":
        strengths.append("Price is above both EMA 50 and EMA 200 — confirmed uptrend on daily timeframe")
        indicator_insights.append({
            "indicator": "EMA",
            "interpretation": "Both short-term and long-term moving averages are below price, indicating strong bullish structure. Institutions typically accumulate above EMA 200.",
            "signal": "bullish",
        })
    elif ema.get("status") == "BORDERLINE":
        weaknesses.append("Price is above only one EMA — trend is transitioning, not fully confirmed")
        indicator_insights.append({
            "indicator": "EMA",
            "interpretation": "Mixed EMA signal. Price may be attempting a trend change but hasn't confirmed yet. Wait for both EMAs to align.",
            "signal": "neutral",
        })
    elif ema.get("status") == "FAIL":
        weaknesses.append("Price is below both EMAs — stock is in a downtrend")
        indicator_insights.append({
            "indicator": "EMA",
            "interpretation": "Bearish structure. Price below both key moving averages suggests selling pressure. Not ideal for swing long entries.",
            "signal": "bearish",
        })

    if supertrend.get("status") == "PASS":
        strengths.append("Supertrend confirms bullish trend — price above the Supertrend line")
        indicator_insights.append({
            "indicator": "Supertrend",
            "interpretation": "ATR-based trend indicator confirms upward momentum. Supertrend flip to bullish often marks the start of a sustained move.",
            "signal": "bullish",
        })
    elif supertrend.get("status") == "FAIL":
        weaknesses.append("Supertrend is bearish — trend reversal or pullback likely")

    # --- MOMENTUM ANALYSIS ---
    rsi = indicators.get("RSI", {})
    macd = indicators.get("MACD", {})
    ao = indicators.get("Awesome Oscillator", {})
    adx = indicators.get("ADX", {})

    rsi_val = rsi.get("computed", {}).get("rsi")
    if rsi.get("status") == "PASS" and rsi_val:
        strengths.append(f"RSI at {rsi_val} — in the sweet spot (not overbought, not weak)")
        indicator_insights.append({
            "indicator": "RSI",
            "interpretation": f"RSI {rsi_val} indicates momentum is positive but not stretched. This is the ideal zone for swing entries — room to run before hitting overbought territory.",
            "signal": "bullish",
        })
    elif rsi_val and rsi_val > 70:
        weaknesses.append(f"RSI at {rsi_val} — overbought, pullback risk is elevated")
        indicator_insights.append({
            "indicator": "RSI",
            "interpretation": f"RSI {rsi_val} is in overbought territory. While strong stocks can stay overbought, the risk of a mean-reversion pullback increases significantly here.",
            "signal": "bearish",
        })
    elif rsi_val and rsi_val < 40:
        weaknesses.append(f"RSI at {rsi_val} — weak momentum, not ready for swing entry")

    if macd.get("status") == "PASS":
        strengths.append("MACD shows bullish crossover with expanding histogram — momentum accelerating")
        indicator_insights.append({
            "indicator": "MACD",
            "interpretation": "MACD line crossed above signal line with expanding histogram bars. This indicates increasing buying momentum — one of the strongest confirmation signals for swing trades.",
            "signal": "bullish",
        })
    elif macd.get("status") == "FAIL":
        weaknesses.append("MACD is bearish — momentum is fading or turning negative")

    adx_val = adx.get("computed", {}).get("adx")
    if adx.get("status") == "PASS" and adx_val:
        strengths.append(f"ADX at {adx_val} — strong trending market (not choppy)")
        indicator_insights.append({
            "indicator": "ADX",
            "interpretation": f"ADX {adx_val} confirms this is a trending market. ADX above 20 means directional moves are reliable. Swing strategies work best in trending conditions.",
            "signal": "bullish",
        })
    elif adx_val and adx_val < 15:
        weaknesses.append(f"ADX at {adx_val} — choppy/sideways market, swing setups unreliable")

    # --- VOLUME ANALYSIS ---
    vol = indicators.get("Volume Surge", {})
    obv = indicators.get("OBV", {})
    cmf = indicators.get("CMF", {})
    kvo = indicators.get("Klinger Volume Oscillator", {})

    if vol.get("status") == "PASS":
        strengths.append("Volume surge detected — institutional interest or breakout confirmation")
        indicator_insights.append({
            "indicator": "Volume Surge",
            "interpretation": "Volume significantly above average. High volume validates price moves — it means large players are participating, making the move more likely to sustain.",
            "signal": "bullish",
        })

    if obv.get("status") == "PASS":
        strengths.append("OBV rising — smart money accumulation before breakout")

    if cmf.get("status") == "PASS":
        strengths.append("Chaikin Money Flow positive — consistent buying pressure")
    elif cmf.get("status") == "FAIL":
        weaknesses.append("CMF negative — money flowing out of the stock")

    # --- PRECISION INDICATORS ---
    fisher = indicators.get("Ehlers Fisher Transform", {})
    vortex = indicators.get("Vortex Indicator", {})

    if fisher.get("status") == "PASS":
        strengths.append("Fisher Transform bullish — precise turning point signal detected")
        indicator_insights.append({
            "indicator": "Ehlers Fisher Transform",
            "interpretation": "Fisher Transform uses Gaussian distribution to identify exact turning points. A bullish signal here has high precision — one of the most reliable timing indicators.",
            "signal": "bullish",
        })

    if vortex.get("status") == "PASS":
        strengths.append("Vortex Indicator confirms bullish trend direction (+VI > -VI)")
        indicator_insights.append({
            "indicator": "Vortex Indicator",
            "interpretation": "Positive vortex movement exceeds negative — bulls are in control. This underrated indicator captures the true essence of trend direction.",
            "signal": "bullish",
        })

    # --- FUNDAMENTAL ANALYSIS ---
    roe_r = fundamentals.get("roe", {})
    roce_r = fundamentals.get("roce", {})
    pe_r = fundamentals.get("pe_ratio", {})
    de_r = fundamentals.get("debt_to_equity", {})
    eps_r = fundamentals.get("eps", {})

    if roe_r.get("status") == "PASS":
        strengths.append(f"ROE {roe_r.get('value', '')} — company generates strong returns on equity")

    if roce_r.get("status") == "PASS":
        strengths.append(f"ROCE {roce_r.get('value', '')} — efficient use of capital")

    if pe_r.get("status") == "PASS":
        strengths.append(f"PE ratio {pe_r.get('value', '')} — reasonably valued")
        indicator_insights.append({
            "indicator": "PE Ratio",
            "interpretation": f"PE {pe_r.get('value', '')} is within acceptable range. Stock is not excessively overvalued, reducing the risk of a valuation-driven correction.",
            "signal": "bullish",
        })
    elif pe_r.get("status") == "FAIL":
        weaknesses.append(f"PE ratio {pe_r.get('value', '')} — potentially overvalued")
        indicator_insights.append({
            "indicator": "PE Ratio",
            "interpretation": f"PE {pe_r.get('value', '')} exceeds the threshold. High PE means the market expects high growth — if earnings disappoint, the stock could correct sharply.",
            "signal": "bearish",
        })

    if de_r.get("status") == "FAIL":
        weaknesses.append(f"Debt to Equity {de_r.get('value', '')} — high leverage increases risk")

    # --- BREAKOUT ANALYSIS (Stage 2) ---
    if stage2_result:
        brk_results = stage2_result.get("breakout_results", {})
        prox = brk_results.get("breakout_proximity", {})
        brk_vol = brk_results.get("breakout_volume", {})
        candle = brk_results.get("breakout_candle", {})

        if prox.get("status") == "PASS":
            strengths.append("Stock near 52-week high — breakout territory")
            indicator_insights.append({
                "indicator": "Breakout Proximity",
                "interpretation": "Price is within striking distance of 52-week high. Stocks breaking to new highs with volume tend to continue — there's no overhead resistance from trapped sellers.",
                "signal": "bullish",
            })

        if brk_vol.get("status") == "PASS":
            strengths.append("Breakout volume confirmed — 2x+ average volume on breakout candle")

        if candle.get("status") == "PASS":
            strengths.append("Strong breakout candle — close near high of day, bullish conviction")

        sl = stage2_result.get("stop_loss")
        target = stage2_result.get("target")
        rr = stage2_result.get("risk_reward")
        if sl and target and rr:
            indicator_insights.append({
                "indicator": "Risk Management",
                "interpretation": f"ATR-based levels: Stop Loss ₹{sl}, Target ₹{target}, Risk:Reward 1:{rr}. A R:R above 1.3 means the potential profit justifies the risk.",
                "signal": "bullish" if rr >= 1.3 else "neutral",
            })

    # --- TIMING ANALYSIS ---
    if late_entry.get("status") == "PASS":
        strengths.append("Entry timing is clean — not chasing an extended move")
    elif late_entry.get("status") == "FAIL":
        weaknesses.append("Late entry warning — stock may already be extended from breakout zone")
        indicator_insights.append({
            "indicator": "Late Entry Check",
            "interpretation": "The stock has already moved significantly from its breakout point. Entering now increases risk of a pullback. Wait for a retest of the breakout level or VWAP.",
            "signal": "bearish",
        })

    # --- OVERALL ASSESSMENT ---
    total_score = scores.get("total_score", 0)
    bull_count = len(strengths)
    bear_count = len(weaknesses)

    if total_score >= 70 and bull_count > bear_count * 2:
        outlook = "Bullish"
        confidence = "High"
    elif total_score >= 55 and bull_count > bear_count:
        outlook = "Bullish"
        confidence = "Medium"
    elif total_score >= 40 and bull_count >= bear_count:
        outlook = "Neutral"
        confidence = "Medium"
    elif bear_count > bull_count:
        outlook = "Bearish"
        confidence = "Medium" if bear_count > bull_count * 2 else "Low"
    else:
        outlook = "Cautious"
        confidence = "Low"

    # Action recommendation
    if outlook == "Bullish" and confidence == "High" and stage1_result.get("passed"):
        action = "Strong candidate for swing entry. Consider entering on next session open or on a small pullback to VWAP/EMA support."
    elif outlook == "Bullish" and stage1_result.get("passed"):
        action = "Watchlist candidate. Wait for volume confirmation or a clean retest of support before entering."
    elif outlook == "Neutral":
        action = "Hold off on new entries. Monitor for trend confirmation — need more indicators to align before committing capital."
    else:
        action = "Avoid for swing long positions. Look for better setups or wait for trend reversal signals."

    # Risk factors
    risk_factors = []
    earnings = fundamentals.get("earnings_blackout", {})
    if earnings.get("status") == "FAIL":
        risk_factors.append("Earnings event approaching — high volatility expected, avoid holding through earnings")
    if bear_count >= 3:
        risk_factors.append(f"{bear_count} indicators showing weakness — higher probability of pullback")
    if adx_val and adx_val < 20:
        risk_factors.append("Low ADX suggests choppy market — stop losses may get triggered more often")

    # Summary
    if outlook == "Bullish":
        summary = f"{symbol} shows {bull_count} bullish signals with a score of {total_score}/100. Trend structure is positive with momentum confirming."
    elif outlook == "Bearish":
        summary = f"{symbol} has {bear_count} weakness signals against {bull_count} strengths. Current setup does not favor swing entries."
    else:
        summary = f"{symbol} is mixed with {bull_count} strengths and {bear_count} weaknesses. Score: {total_score}/100. Wait for clearer signal."

    return {
        "symbol": symbol,
        "overall_outlook": outlook,
        "confidence": confidence,
        "score": total_score,
        "summary": summary,
        "action": action,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "risk_factors": risk_factors,
        "indicator_insights": indicator_insights,
        "bull_count": bull_count,
        "bear_count": bear_count,
    }
