"""
Chat Agent — Rule-based intent parser and action executor.
Parses natural language into structured actions the frontend can execute.
"""

import re
from engine.default_config import get_default_config, CONFIG_TO_INDICATOR
from engine.presets import list_presets, load_preset, save_preset
from engine.watchlist import load_watchlist
from engine.insights import generate_insights
from engine.screener import screen_stock_stage1, screen_stock_stage2


# ── All known filter keys ──
ALL_FILTERS = set(get_default_config().keys()) - {"scoring"}

TECHNICAL_KEYS = [
    "ema", "rsi", "macd", "volume_surge", "supertrend", "adx", "obv", "cmf",
    "roc", "awesome_oscillator", "anchored_vwap", "pivot_levels",
    "hidden_divergence", "sector_performance", "fisher_transform",
    "klinger_oscillator", "chande_momentum", "force_index", "vortex",
]
FUNDAMENTAL_KEYS = [
    "roe", "roce", "debt_to_equity", "eps", "free_cash_flow",
    "institutional_holdings", "analyst_ratings", "earnings_blackout",
    "pe_ratio", "daily_turnover", "free_float",
]
BREAKOUT_KEYS = [
    "breakout_proximity", "breakout_volume", "breakout_rsi", "breakout_candle",
    "supply_zone", "institutional_flow", "bb_squeeze", "stochastic_rsi",
    "williams_r", "vwap_bands", "ichimoku", "late_entry_stage1",
    "late_entry_stage2", "risk_management",
]

# ── Aliases for fuzzy matching ──
FILTER_ALIASES = {
    "rsi": "rsi", "relative strength": "rsi", "relative strength index": "rsi",
    "ema": "ema", "moving average": "ema", "exponential moving average": "ema",
    "macd": "macd",
    "volume": "volume_surge", "volume surge": "volume_surge",
    "supertrend": "supertrend", "super trend": "supertrend",
    "adx": "adx", "average directional": "adx",
    "obv": "obv", "on balance volume": "obv",
    "cmf": "cmf", "chaikin money flow": "cmf",
    "roc": "roc", "rate of change": "roc",
    "awesome oscillator": "awesome_oscillator", "ao": "awesome_oscillator",
    "anchored vwap": "anchored_vwap", "vwap": "anchored_vwap",
    "pivot": "pivot_levels", "pivot levels": "pivot_levels",
    "hidden divergence": "hidden_divergence", "divergence": "hidden_divergence",
    "sector": "sector_performance", "sector performance": "sector_performance",
    "fisher": "fisher_transform", "fisher transform": "fisher_transform",
    "klinger": "klinger_oscillator", "klinger oscillator": "klinger_oscillator",
    "chande": "chande_momentum", "chande momentum": "chande_momentum", "cmo": "chande_momentum",
    "force index": "force_index", "elder force": "force_index",
    "vortex": "vortex", "vortex indicator": "vortex",
    "bb squeeze": "bb_squeeze", "bollinger squeeze": "bb_squeeze", "squeeze": "bb_squeeze",
    "stochastic rsi": "stochastic_rsi", "stoch rsi": "stochastic_rsi",
    "williams": "williams_r", "williams %r": "williams_r", "williams r": "williams_r",
    "vwap bands": "vwap_bands",
    "ichimoku": "ichimoku", "ichimoku cloud": "ichimoku",
    "risk": "risk_management", "risk management": "risk_management", "atr": "risk_management",
    "roe": "roe", "return on equity": "roe",
    "roce": "roce", "return on capital": "roce",
    "debt": "debt_to_equity", "debt to equity": "debt_to_equity", "d/e": "debt_to_equity",
    "eps": "eps", "earnings per share": "eps",
    "fcf": "free_cash_flow", "free cash flow": "free_cash_flow", "cash flow": "free_cash_flow",
    "institutional": "institutional_holdings", "institutional holdings": "institutional_holdings",
    "fii": "institutional_holdings", "dii": "institutional_holdings",
    "analyst": "analyst_ratings", "analyst ratings": "analyst_ratings",
    "earnings blackout": "earnings_blackout", "blackout": "earnings_blackout",
    "pe": "pe_ratio", "pe ratio": "pe_ratio", "p/e": "pe_ratio",
    "turnover": "daily_turnover", "daily turnover": "daily_turnover",
    "free float": "free_float", "float": "free_float",
    "breakout proximity": "breakout_proximity",
    "breakout volume": "breakout_volume",
    "breakout rsi": "breakout_rsi",
    "breakout candle": "breakout_candle",
    "supply zone": "supply_zone",
    "institutional flow": "institutional_flow",
    "late entry": "late_entry_stage1",
}

# ── Indicator explanations ──
INDICATOR_HELP = {
    "rsi": "**RSI (Relative Strength Index)** measures momentum on a 0-100 scale. Above 50 = bullish momentum. 30-50 = neutral/consolidating. Above 70 = overbought (may pullback). Below 30 = oversold (may bounce). Our screener looks for RSI between 50-65 — the sweet spot for swing entries.",
    "ema": "**EMA (Exponential Moving Average)** smooths price data. We use EMA 50 (medium-term trend) and EMA 200 (long-term trend). Price above both = strong uptrend. EMA 50 crossing above EMA 200 = 'Golden Cross' — very bullish.",
    "macd": "**MACD** shows trend direction and momentum. When the MACD line crosses above the signal line = bullish. Histogram growing = strengthening momentum. We look for fresh bullish crossovers.",
    "supertrend": "**Supertrend** is a trend-following overlay. Green = uptrend, Red = downtrend. It adapts to volatility using ATR. One of our ⭐ highlighted indicators — very reliable for swing trading.",
    "adx": "**ADX (Average Directional Index)** measures trend strength (not direction). Above 20 = trending. Above 40 = strong trend. Below 20 = ranging/choppy. We want ADX > 20 to confirm a real trend.",
    "obv": "**OBV (On Balance Volume)** tracks cumulative volume flow. Rising OBV = buying pressure. Falling OBV = selling pressure. We look for rising OBV to confirm price moves are backed by volume.",
    "cmf": "**CMF (Chaikin Money Flow)** measures buying/selling pressure over 20 periods. Above 0 = money flowing in. Above 0.1 = strong accumulation. Negative = distribution (selling).",
    "vortex": "**Vortex Indicator** identifies trend direction and reversals. When VI+ > VI- = uptrend. The gap between them shows trend strength. One of our ⭐ highlighted indicators.",
    "vwap_bands": "**VWAP Bands** show price relative to the Volume Weighted Average Price. Price above VWAP = bullish. Bands show standard deviations. One of our ⭐ highlighted indicators.",
    "volume_surge": "**Volume Surge** detects unusual volume spikes. Volume > 1.5x the 20-day average suggests institutional interest. Big moves need big volume to be sustainable.",
    "bb_squeeze": "**Bollinger Band Squeeze** detects low-volatility periods before explosive moves. When Bollinger Bands squeeze inside Keltner Channels, a big breakout is coming.",
    "stochastic_rsi": "**Stochastic RSI** applies the Stochastic formula to RSI values. More sensitive than regular RSI. Below 20 = oversold, above 80 = overbought. Good for timing entries.",
    "williams_r": "**Williams %R** is a momentum oscillator (-100 to 0). Above -20 = overbought. Below -80 = oversold. We look for the -40 to -10 range for entries.",
    "ichimoku": "**Ichimoku Cloud** provides support/resistance, trend direction, and momentum in one indicator. Price above the cloud = bullish. Tenkan crossing Kijun = signal.",
    "roe": "**ROE (Return on Equity)** measures how efficiently a company uses shareholders' money. Above 15% = excellent. Above 12% = good. Our filter requires minimum 12%.",
    "roce": "**ROCE (Return on Capital Employed)** measures overall capital efficiency including debt. Above 15% = excellent. More comprehensive than ROE.",
    "pe_ratio": "**PE Ratio** compares stock price to earnings. Lower PE = cheaper relative to earnings. Our filter caps at PE 40 to avoid overvalued stocks. Industry comparison matters.",
    "debt_to_equity": "**Debt to Equity** ratio shows financial leverage. Below 1.0 = conservative. Above 2.0 = risky. Our filter allows up to 1.0 (with exceptions for PSU/infra).",
}

# ── Strategy templates for script creation ──
STRATEGY_TEMPLATES = {
    "momentum": {
        "description": "High momentum stocks with strong trends",
        "enable": ["rsi", "ema", "macd", "supertrend", "adx", "volume_surge", "vortex"],
        "params": {"rsi": {"rsi_min": 55, "rsi_max": 75}, "adx": {"adx_minimum": 25}},
    },
    "value": {
        "description": "Fundamentally strong undervalued stocks",
        "enable": ["roe", "roce", "debt_to_equity", "eps", "pe_ratio", "free_cash_flow", "ema"],
        "params": {"pe_ratio": {"pe_maximum": 25}, "roe": {"roe_minimum": 15}},
    },
    "breakout": {
        "description": "Stocks near breakout with volume confirmation",
        "enable": ["breakout_proximity", "breakout_volume", "breakout_rsi", "bb_squeeze",
                   "supply_zone", "volume_surge", "supertrend"],
        "params": {"breakout_proximity": {"breakout_proximity_max": 3}},
    },
    "swing": {
        "description": "Balanced swing trading setup",
        "enable": ["ema", "rsi", "supertrend", "volume_surge", "roe", "pe_ratio",
                   "breakout_proximity", "risk_management"],
        "params": {},
    },
    "conservative": {
        "description": "Low-risk picks with strong fundamentals",
        "enable": ["ema", "rsi", "roe", "roce", "debt_to_equity", "eps", "pe_ratio",
                   "free_cash_flow", "free_float"],
        "params": {"rsi": {"rsi_min": 45, "rsi_max": 60}, "pe_ratio": {"pe_maximum": 20},
                   "debt_to_equity": {"de_maximum": 0.5}},
    },
    "aggressive": {
        "description": "High-risk, high-reward momentum plays",
        "enable": ["rsi", "macd", "supertrend", "adx", "volume_surge", "bb_squeeze",
                   "breakout_proximity", "breakout_volume", "stochastic_rsi", "vortex"],
        "params": {"rsi": {"rsi_min": 60, "rsi_max": 80}, "adx": {"adx_minimum": 30}},
    },
}


def _extract_symbols(text: str) -> list[str]:
    """Extract stock symbols from text (uppercase words, 3-15 chars, common patterns)."""
    # Look for explicit symbols after keywords
    patterns = [
        r'(?:check|screen|scan|analyze|analyse|look at|show|add|watch)\s+(.+)',
        r'(?:for|about|on)\s+([A-Z][A-Z0-9,\s]+)',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            chunk = m.group(1)
            syms = [s.strip().upper() for s in re.split(r'[,\s]+', chunk)
                    if re.match(r'^[A-Z]{2,15}$', s.strip().upper()) and len(s.strip()) >= 2]
            if syms:
                return syms

    # Fallback: find any uppercase words that look like stock symbols
    words = re.findall(r'\b([A-Z]{3,15})\b', text)
    stopwords = {"THE", "AND", "FOR", "ALL", "NSE", "ARE", "NOT", "CAN", "HOW",
                 "WHY", "DID", "HAS", "GET", "SET", "ADD", "USE", "RUN", "RSI",
                 "EMA", "OBV", "CMF", "ROC", "ADX", "ROE", "EPS", "ATR", "MACD",
                 "NIFTY", "STAGE", "PASS", "FAIL", "ENABLE", "DISABLE", "WHAT",
                 "WHICH", "SHOW", "LIST", "LOAD", "SAVE", "DELETE", "CREATE",
                 "SCREEN", "CHECK", "ABOUT", "WITH", "FROM", "ONLY", "JUST",
                 "WATCHLIST", "WATCH", "PRESET", "STRATEGY", "ALERT", "FILTER",
                 "FILTERS", "STOCK", "STOCKS", "SCAN", "FIND", "SEARCH",
                 "PLEASE", "COULD", "WOULD", "SHOULD", "INTO", "TELL", "GIVE",
                 "WANT", "NEED", "LIKE", "ALSO", "THEN", "THIS", "THAT",
                 "TURN", "SWITCH", "ACTIVATE", "APPLY", "ANALYZE", "ANALYSE"}
    return [w for w in words if w not in stopwords]


def _extract_filters(text: str) -> list[str]:
    """Extract filter names from text using aliases."""
    text_lower = text.lower()
    found = []
    # Try longest alias first
    for alias in sorted(FILTER_ALIASES.keys(), key=len, reverse=True):
        if alias in text_lower:
            key = FILTER_ALIASES[alias]
            if key not in found:
                found.append(key)
            # Remove matched text to avoid double-matching
            text_lower = text_lower.replace(alias, " ")
    return found


def _detect_intent(text: str) -> dict:
    """Detect the user's intent from their message."""
    t = text.lower().strip()

    # ── Enable/Disable filters ──
    if re.search(r'\b(enable|turn on|activate|switch on)\b.*\b(all|every)\b', t):
        return {"intent": "enable_all"}
    if re.search(r'\b(disable|turn off|deactivate|switch off)\b.*\b(all|every)\b', t):
        return {"intent": "disable_all"}
    if re.search(r'\b(enable|turn on|activate|add|switch on)\b', t) and not re.search(r'\b(alert|watchlist|preset)\b', t):
        filters = _extract_filters(t)
        if filters:
            return {"intent": "enable_filters", "filters": filters}
    if re.search(r'\b(disable|turn off|deactivate|remove|switch off)\b', t) and not re.search(r'\b(alert|watchlist)\b', t):
        filters = _extract_filters(t)
        if filters:
            return {"intent": "disable_filters", "filters": filters}
    if re.search(r'\b(enable|use|keep)\s+only\b', t):
        filters = _extract_filters(t)
        if filters:
            return {"intent": "enable_only", "filters": filters}

    # ── Create strategy/script/preset ──
    if re.search(r'\b(create|build|make|design|generate)\b.*\b(strategy|script|preset|setup|config|profile)\b', t):
        # Check for template match
        for name, template in STRATEGY_TEMPLATES.items():
            if name in t:
                return {"intent": "create_strategy", "template": name, "name": None}
        # Check for filter mentions
        filters = _extract_filters(t)
        return {"intent": "create_strategy", "template": None, "filters": filters, "name": None}

    # ── Load/apply preset ──
    if re.search(r'\b(load|apply|use|switch to|activate)\b.*\b(preset|strategy|config|profile)\b', t):
        presets = list_presets()
        for p in presets:
            if p.lower() in t:
                return {"intent": "load_preset", "name": p}
        return {"intent": "list_presets"}

    # ── Save preset ──
    if re.search(r'\b(save|store|keep)\b.*\b(preset|strategy|config|as)\b', t):
        m = re.search(r'(?:as|called|named|name)\s+["\']?(\w+)["\']?', t)
        name = m.group(1) if m else None
        return {"intent": "save_preset", "name": name}

    # ── Screen/scan stocks ──
    if re.search(r'\b(screen|scan|find|search|run|check|analyze|analyse)\b', t):
        # Check scope first (before symbol extraction, since "Nifty" could be parsed as symbol)
        scope = None
        if "nifty 200" in t or "nifty200" in t:
            scope = "nifty200"
        elif "nifty 500" in t or "nifty500" in t:
            scope = "nifty500"
        elif "all nse" in t or "all stocks" in t:
            scope = "all"
        if scope:
            return {"intent": "screen_scope", "scope": scope}
        symbols = _extract_symbols(text)  # Use original case
        if symbols:
            return {"intent": "screen_symbols", "symbols": symbols}
        return {"intent": "screen_scope", "scope": "nifty500"}

    # ── Explain indicator ──
    if re.search(r'\b(what|explain|describe|how|tell me about|meaning|define)\b', t):
        filters = _extract_filters(t)
        if filters:
            return {"intent": "explain", "filter": filters[0]}
        # Check if asking about a stock
        symbols = _extract_symbols(text)
        if symbols:
            return {"intent": "stock_info", "symbol": symbols[0]}
        return {"intent": "explain_general"}

    # ── Watchlist ──
    if re.search(r'\b(watchlist|watch list|watching)\b', t):
        if re.search(r'\b(add|put|include)\b', t):
            # Extract symbols more carefully — strip watchlist keywords
            cleaned = re.sub(r'\b(add|put|include|to|into|in|my|the|watchlist|watch list)\b', ' ', text, flags=re.IGNORECASE)
            symbols = _extract_symbols(cleaned)
            if symbols:
                return {"intent": "watchlist_add", "symbols": symbols}
        if re.search(r'\b(check|alerts?|status)\b', t):
            return {"intent": "watchlist_check"}
        if re.search(r'\b(show|list|view|see)\b', t):
            return {"intent": "watchlist_list"}
        return {"intent": "watchlist_list"}

    # ── List presets ──
    if re.search(r'\b(list|show|what)\b.*\b(preset|strategy|strategies|presets)\b', t):
        return {"intent": "list_presets"}

    # ── Stock-specific question ──
    symbols = _extract_symbols(text)
    if symbols:
        if re.search(r'\b(why|fail|pass|status|insight)\b', t):
            return {"intent": "stock_info", "symbol": symbols[0]}
        return {"intent": "screen_symbols", "symbols": symbols}

    # ── Greeting ──
    if re.search(r'^(hi|hello|hey|sup|yo|good morning|good evening)\b', t):
        return {"intent": "greeting"}

    # ── Help ──
    if re.search(r'\b(help|what can you|commands|how to use)\b', t):
        return {"intent": "help"}

    # ── Fallback ──
    return {"intent": "unknown"}


def process_message(message: str, get_bundle_fn=None, current_config: dict | None = None) -> dict:
    """
    Process a chat message and return a response with optional frontend actions.

    Returns: {
        "reply": str,           # Text response to show
        "actions": list[dict],  # Actions for frontend to execute
        "data": dict | None,    # Any data payload
    }
    """
    intent = _detect_intent(message)
    actions = []
    data = None

    match intent["intent"]:

        case "greeting":
            reply = "Hey! I'm your Yointell assistant. I can help you:\n" \
                    "• **Enable/disable filters** — \"enable only RSI and Supertrend\"\n" \
                    "• **Screen stocks** — \"screen Nifty 200\" or \"check RELIANCE, TCS\"\n" \
                    "• **Create strategies** — \"create a momentum strategy\"\n" \
                    "• **Manage presets** — \"load aggressive preset\" or \"save as my_setup\"\n" \
                    "• **Manage watchlist** — \"add SBIN to watchlist\" or \"check alerts\"\n" \
                    "• **Explain indicators** — \"what is RSI?\" or \"explain Supertrend\"\n" \
                    "Ask me anything!"

        case "help":
            reply = "Here's what I can do:\n\n" \
                    "**Filters:** enable RSI, disable fundamentals, enable only supertrend and vortex, enable all, disable all\n\n" \
                    "**Screen:** screen Nifty 200, check RELIANCE TCS INFY, scan all NSE\n\n" \
                    "**Strategies:** create momentum strategy, create conservative preset, build breakout script\n\n" \
                    "**Presets:** list presets, load aggressive, save as my_setup\n\n" \
                    "**Watchlist:** add SBIN to watchlist, check alerts, show watchlist\n\n" \
                    "**Learn:** what is RSI?, explain Supertrend, how does MACD work?"

        case "enable_all":
            actions.append({"type": "toggle_all", "enabled": True})
            reply = "All 44 filters enabled. Your screening will be comprehensive but stricter — fewer stocks will pass all checks."

        case "disable_all":
            actions.append({"type": "toggle_all", "enabled": False})
            reply = "All filters disabled. Enable specific ones to start screening."

        case "enable_filters":
            filters = intent["filters"]
            for f in filters:
                actions.append({"type": "toggle_filter", "key": f, "enabled": True})
            names = [f.replace("_", " ").upper() for f in filters]
            reply = f"Enabled **{', '.join(names)}**. {len(filters)} filter(s) turned on."

        case "disable_filters":
            filters = intent["filters"]
            for f in filters:
                actions.append({"type": "toggle_filter", "key": f, "enabled": False})
            names = [f.replace("_", " ").upper() for f in filters]
            reply = f"Disabled **{', '.join(names)}**."

        case "enable_only":
            filters = intent["filters"]
            actions.append({"type": "toggle_all", "enabled": False})
            for f in filters:
                actions.append({"type": "toggle_filter", "key": f, "enabled": True})
            names = [f.replace("_", " ").upper() for f in filters]
            reply = f"Enabled **only** {', '.join(names)}. All other filters disabled."

        case "create_strategy":
            template_name = intent.get("template")
            if template_name and template_name in STRATEGY_TEMPLATES:
                template = STRATEGY_TEMPLATES[template_name]
                # Build config: disable all, enable template filters, set params
                config = get_default_config()
                for key in config:
                    if isinstance(config[key], dict) and "enabled" in config[key]:
                        config[key]["enabled"] = key in template["enable"]
                for key, params in template.get("params", {}).items():
                    if key in config:
                        config[key].update(params)

                preset_name = template_name
                save_preset(preset_name, config)
                actions.append({"type": "load_preset", "name": preset_name})
                reply = f"Created **{template_name}** strategy: {template['description']}.\n\n" \
                        f"Enabled {len(template['enable'])} filters: {', '.join(f.replace('_',' ').upper() for f in template['enable'])}.\n\n" \
                        f"Saved as preset **{preset_name}** and applied to your screener."
            else:
                # Custom strategy from mentioned filters
                filters = intent.get("filters", [])
                if filters:
                    config = get_default_config()
                    for key in config:
                        if isinstance(config[key], dict) and "enabled" in config[key]:
                            config[key]["enabled"] = key in filters
                    actions.append({"type": "set_config", "config": config})
                    names = [f.replace("_", " ").upper() for f in filters]
                    reply = f"Created custom strategy with {len(filters)} filters: {', '.join(names)}.\n\n" \
                            f"Use \"save as <name>\" to save this as a preset."
                else:
                    templates = ", ".join(f"**{n}** ({t['description']})" for n, t in STRATEGY_TEMPLATES.items())
                    reply = f"I can create these pre-built strategies:\n\n{templates}\n\n" \
                            f"Or say something like \"create strategy with RSI, Supertrend, and ROE\"."

        case "load_preset":
            name = intent["name"]
            actions.append({"type": "load_preset", "name": name})
            reply = f"Applied preset **{name}**. Filter panel updated."

        case "save_preset":
            name = intent.get("name")
            if name:
                actions.append({"type": "save_preset", "name": name})
                reply = f"Saved current filter config as preset **{name}**."
            else:
                reply = "What should I name this preset? Say \"save as **name**\"."

        case "list_presets":
            presets = list_presets()
            if presets:
                reply = f"**{len(presets)} saved presets:**\n" + "\n".join(f"• {p}" for p in presets)
                reply += "\n\nSay \"load <name>\" to apply one."
            else:
                reply = "No presets saved yet. Use \"save as <name>\" to create one."

        case "screen_symbols":
            symbols = intent["symbols"]
            actions.append({"type": "screen", "symbols": symbols})
            reply = f"Screening **{', '.join(symbols)}** with current filters..."

        case "screen_scope":
            scope = intent["scope"]
            scope_label = {"nifty200": "Nifty 200", "nifty500": "Nifty 500", "all": "All NSE"}.get(scope, scope)
            actions.append({"type": "screen_all", "scope": scope})
            reply = f"Screening **{scope_label}** with current filters..."

        case "explain":
            filter_key = intent["filter"]
            if filter_key in INDICATOR_HELP:
                reply = INDICATOR_HELP[filter_key]
            elif filter_key in CONFIG_TO_INDICATOR:
                name = CONFIG_TO_INDICATOR[filter_key]
                reply = f"**{name}** ({filter_key.replace('_',' ').upper()}) — This is one of the 44 filters in the screener. Enable it to include it in your screening. Check the Indicators tab for full details."
            else:
                reply = f"**{filter_key.replace('_',' ').upper()}** is a screening filter. Enable it in the filter panel to use it."

        case "explain_general":
            reply = "What would you like to know about? I can explain any of the 25 indicators " \
                    "(RSI, MACD, Supertrend, etc.) or any fundamental filter (ROE, PE ratio, etc.)."

        case "stock_info":
            symbol = intent["symbol"]
            actions.append({"type": "open_insights", "symbol": symbol})
            reply = f"Opening insights for **{symbol}**..."

        case "watchlist_add":
            symbols = intent["symbols"]
            actions.append({"type": "watchlist_add", "symbols": symbols})
            reply = f"Adding **{', '.join(symbols)}** to watchlist."

        case "watchlist_check":
            actions.append({"type": "watchlist_check"})
            reply = "Checking all watchlist alerts..."

        case "watchlist_list":
            items = load_watchlist()
            if items:
                lines = [f"• **{i['symbol']}** — {len(i.get('alerts', []))} alerts" for i in items]
                reply = f"**Watchlist ({len(items)} stocks):**\n" + "\n".join(lines)
            else:
                reply = "Watchlist is empty. Say \"add RELIANCE to watchlist\" to start."

        case _:
            reply = "I'm not sure what you mean. Try:\n" \
                    "• \"enable RSI and Supertrend\"\n" \
                    "• \"screen Nifty 200\"\n" \
                    "• \"what is MACD?\"\n" \
                    "• \"create momentum strategy\"\n" \
                    "• \"add TCS to watchlist\"\n\n" \
                    "Type **help** for full list of commands."

    return {"reply": reply, "actions": actions, "data": data}
