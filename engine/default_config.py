"""
Default Filter Configuration
Every single parameter is a variable. Nothing is hardcoded.
Change any value here or pass overrides at runtime via JSON.
"""


def get_default_config() -> dict:
    """
    Returns the complete default filter configuration.
    Every filter has:
      - enabled: True/False — if False, filter is completely skipped
      - All parameters with default values
    """
    return {
        # ============================================================
        # STAGE 1 — SMOOTH SWING BASE FILTERS
        # ============================================================

        # --- TECHNICAL FILTERS ---

        "ema": {
            "enabled": True,
            "fast_ema_period": 50,
            "slow_ema_period": 200,
        },
        "rsi": {
            "enabled": True,
            "rsi_period": 14,
            "rsi_min": 50,
            "rsi_max": 65,
        },
        "macd": {
            "enabled": True,
            "macd_fast": 12,
            "macd_slow": 26,
            "macd_signal": 9,
        },
        "volume_surge": {
            "enabled": True,
            "volume_surge_multiplier": 1.5,
            "volume_lookback": 20,
        },
        "sector_performance": {
            "enabled": True,
            "sector_lookback": 30,
        },
        "anchored_vwap": {
            "enabled": True,
            "vwap_anchor": "auto",
            "swing_lookback": 50,
        },
        "hidden_divergence": {
            "enabled": True,
            "divergence_timeframe": "4H",
            "divergence_indicator": "RSI",
            "divergence_lookback": 30,
            "rsi_period": 14,
        },
        "pivot_levels": {
            "enabled": True,
            "pivot_type": "both",
        },
        "awesome_oscillator": {
            "enabled": True,
            "ao_fast": 5,
            "ao_slow": 34,
            "ao_timeframe": "daily",
        },
        "supertrend": {
            "enabled": True,
            "supertrend_period": 7,
            "supertrend_multiplier": 3.0,
        },
        "adx": {
            "enabled": True,
            "adx_period": 14,
            "adx_minimum": 20,
        },
        "obv": {
            "enabled": True,
            "obv_lookback": 20,
            "obv_direction": "rising",
        },
        "cmf": {
            "enabled": True,
            "cmf_period": 20,
            "cmf_minimum": 0.1,
        },
        "roc": {
            "enabled": True,
            "roc_period": 20,
            "roc_minimum": 0,
        },
        # Relative Strength rank gate — hard pre-filter (OF3 turns this on)
        "rs_rank": {
            "enabled": False,           # off by default; OF3 preset sets to True
            "min_rs_percentile": 70,    # only stocks ranked ≥70/99 pass Stage 1
        },

        # --- PRECISION / HIDDEN GEM INDICATORS ---

        "fisher_transform": {
            "enabled": True,
            "fisher_period": 10,
            "fisher_signal_period": 1,
        },
        "klinger_oscillator": {
            "enabled": True,
            "kvo_fast": 34,
            "kvo_slow": 55,
            "kvo_signal": 13,
        },
        "chande_momentum": {
            "enabled": True,
            "cmo_period": 14,
            "cmo_min": 10,
            "cmo_max": 50,
        },
        "force_index": {
            "enabled": True,
            "efi_period": 13,
        },
        "vortex": {
            "enabled": True,
            "vortex_period": 14,
            "vi_threshold": 0.05,
        },

        # --- FUNDAMENTAL FILTERS ---

        "roe": {
            "enabled": True,
            "roe_minimum": 12,
        },
        "roce": {
            "enabled": True,
            "roce_minimum": 10,
        },
        "debt_to_equity": {
            "enabled": True,
            "de_maximum": 1.0,
            "exclude_psu_infra": True,
        },
        "eps": {
            "enabled": True,
            "eps_minimum": 0,
            "eps_trend": "positive",
        },
        "free_cash_flow": {
            "enabled": True,
            "fcf_trend": "positive_growth",
        },
        "institutional_holdings": {
            "enabled": True,
            "institutional_trend": "rising_or_stable",
        },
        "analyst_ratings": {
            "enabled": True,
            "analyst_buy_minimum": 3,
        },
        "earnings_blackout": {
            "enabled": True,
            "earnings_blackout_days": 7,
        },
        "pe_ratio": {
            "enabled": True,
            "pe_maximum": 40,
        },

        # --- LIQUIDITY FILTERS ---

        "daily_turnover": {
            "enabled": True,
            "turnover_minimum": 5,  # in crore
        },
        "free_float": {
            "enabled": True,
            "freefloat_minimum": 30,
        },

        # --- LATE ENTRY CORRECTION (STAGE 1) ---

        "late_entry_stage1": {
            "enabled": True,
            "max_extension_from_breakout": 6,
            "max_expansion_candles_without_pause": 2,
            "entry_proximity_max": 3,
        },

        # ============================================================
        # STAGE 2 — BREAKOUT EXECUTION FILTERS
        # ============================================================

        "breakout_proximity": {
            "enabled": True,
            "breakout_proximity_max": 5,
        },
        "breakout_volume": {
            "enabled": True,
            "breakout_volume_multiplier": 2.0,
        },
        "breakout_rsi": {
            "enabled": True,
            "breakout_rsi_min": 55,
            "breakout_rsi_max": 70,
            "breakout_rsi_reject": 75,
        },
        "supply_zone": {
            "enabled": True,
            "upside_clear_minimum": 5,
        },
        "institutional_flow": {
            "enabled": True,
            "fii_dii_sessions": 5,
        },
        "breakout_candle": {
            "enabled": True,
            "candle_close_quality": 70,
        },
        "bb_squeeze": {
            "enabled": True,
            "bb_period": 20,
            "bb_multiplier": 2.0,
            "kc_multiplier": 1.5,
        },
        "stochastic_rsi": {
            "enabled": True,
            "stochrsi_rsi_period": 14,
            "stochrsi_stoch_period": 14,
            "stochrsi_oversold": 20,
            "stochrsi_overbought": 80,
        },
        "williams_r": {
            "enabled": True,
            "williams_period": 14,
            "williams_min": -40,
            "williams_max": -10,
        },
        "vwap_bands": {
            "enabled": True,
            "vwap_sigma": 1.0,
            "vwap_period": 20,
        },
        "ichimoku": {
            "enabled": True,
            "ichimoku_tenkan": 9,
            "ichimoku_kijun": 26,
            "ichimoku_senkou": 52,
        },

        # --- LATE ENTRY CORRECTION (STAGE 2) ---

        "late_entry_stage2": {
            "enabled": True,
            "stage2_max_extension": 4,
            "stale_breakout_sessions": 2,
        },

        # --- RISK MANAGEMENT ---

        "risk_management": {
            "enabled": True,
            "sl_atr_period": 14,
            "sl_atr_multiplier": 1.3,
            "target_atr_multiplier": 1.8,
        },

        # ============================================================
        # SCORING WEIGHTS (out of 100)
        # ============================================================

        "scoring": {
            "technical_weight": 40,
            "fundamental_weight": 30,
            "breakout_weight": 20,
            "liquidity_weight": 10,
        },
    }


# Map from config keys to indicator registry names
CONFIG_TO_INDICATOR = {
    "ema": "EMA",
    "rsi": "RSI",
    "macd": "MACD",
    "volume_surge": "Volume Surge",
    "sector_performance": "Sector Performance",
    "anchored_vwap": "Anchored VWAP",
    "hidden_divergence": "Hidden Bullish Divergence",
    "pivot_levels": "Pivot Levels",
    "awesome_oscillator": "Awesome Oscillator",
    "supertrend": "Supertrend",
    "adx": "ADX",
    "obv": "OBV",
    "cmf": "CMF",
    "roc": "ROC",
    "fisher_transform": "Ehlers Fisher Transform",
    "klinger_oscillator": "Klinger Volume Oscillator",
    "chande_momentum": "Chande Momentum Oscillator",
    "force_index": "Elder Force Index",
    "vortex": "Vortex Indicator",
    "bb_squeeze": "Bollinger Band Squeeze",
    "stochastic_rsi": "Stochastic RSI",
    "williams_r": "Williams %R",
    "vwap_bands": "VWAP Bands",
    "ichimoku": "Ichimoku Cloud",
    "risk_management": "ATR",
}
