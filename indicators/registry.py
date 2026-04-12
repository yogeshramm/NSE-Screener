"""
Indicator Registry — Auto-discovers all indicator classes.
Adding a new indicator = creating one new .py file in indicators/.
The registry automatically picks it up. Nothing else changes.
"""

import importlib
import pkgutil
import inspect
from pathlib import Path
from indicators.base import BaseIndicator


def _discover_indicators() -> dict:
    """
    Auto-discover all BaseIndicator subclasses in the indicators/ directory.
    Returns dict mapping indicator name -> indicator class.
    """
    registry = {}
    indicators_dir = Path(__file__).parent

    for module_info in pkgutil.iter_modules([str(indicators_dir)]):
        if module_info.name in ("base", "registry", "__init__"):
            continue
        try:
            module = importlib.import_module(f"indicators.{module_info.name}")
            for attr_name, attr in inspect.getmembers(module, inspect.isclass):
                if issubclass(attr, BaseIndicator) and attr is not BaseIndicator:
                    registry[attr.name] = attr
        except Exception as e:
            print(f"  [WARN] Failed to load indicator module '{module_info.name}': {e}")

    return registry


# Global registry — populated on import
INDICATOR_REGISTRY: dict[str, type[BaseIndicator]] = _discover_indicators()

# Custom indicators added at runtime
CUSTOM_INDICATORS: dict[str, type[BaseIndicator]] = {}


def get_all_indicators() -> dict[str, type[BaseIndicator]]:
    """Get all available indicators (built-in + custom)."""
    return {**INDICATOR_REGISTRY, **CUSTOM_INDICATORS}


def get_indicator(name: str) -> type[BaseIndicator] | None:
    """Get a specific indicator class by name."""
    all_indicators = get_all_indicators()
    return all_indicators.get(name)


def list_indicators() -> list[dict]:
    """List all available indicators with metadata."""
    result = []
    for name, cls in get_all_indicators().items():
        instance = cls()
        result.append({
            "name": name,
            "type": instance.indicator_type,
            "description": instance.description,
            "default_params": instance.default_params,
            "is_custom": name in CUSTOM_INDICATORS,
            "precision_tier": getattr(instance, "precision_tier", None),
            "highlighted": getattr(instance, "highlighted", False),
        })
    return sorted(result, key=lambda x: (x["type"], x["name"]))


def register_custom_indicator(indicator_class: type[BaseIndicator]):
    """Register a custom indicator at runtime."""
    if not issubclass(indicator_class, BaseIndicator):
        raise ValueError("Custom indicator must extend BaseIndicator")
    CUSTOM_INDICATORS[indicator_class.name] = indicator_class
    return indicator_class.name


def run_all_indicators(df, enabled_indicators: dict | None = None,
                       params: dict | None = None, sector: str = None,
                       timeframes: dict | None = None,
                       df_weekly: "pd.DataFrame | None" = None,
                       df_monthly: "pd.DataFrame | None" = None,
                       df_4h: "pd.DataFrame | None" = None) -> list[dict]:
    """
    Run all enabled indicators on a DataFrame.

    Args:
        df: Daily OHLCV DataFrame
        enabled_indicators: dict of {indicator_name: True/False}
                           If None, all indicators are enabled.
        params: dict of {indicator_name: {param_name: value}}
        sector: stock sector (needed for Sector Performance indicator)
        timeframes: dict of {indicator_name: "daily"|"weekly"|"monthly"|"4H"}
                   Override timeframe for specific indicators.
        df_weekly: Pre-resampled weekly data (auto-generated if needed)
        df_monthly: Pre-resampled monthly data (auto-generated if needed)
        df_4h: 4-hour data from yfinance (optional)

    Returns:
        list of indicator results (each is a dict from evaluate())
    """
    from indicators.timeframe import resample_ohlcv, validate_dataframe

    if params is None:
        params = {}
    if enabled_indicators is None:
        enabled_indicators = {name: True for name in get_all_indicators()}
    if timeframes is None:
        timeframes = {}

    # Pre-generate weekly/monthly if not provided
    tf_cache = {"daily": df}
    if df_weekly is not None:
        tf_cache["weekly"] = df_weekly
    if df_monthly is not None:
        tf_cache["monthly"] = df_monthly
    if df_4h is not None:
        tf_cache["4h"] = df_4h

    def _get_tf_data(timeframe: str):
        """Get data for a timeframe, resampling and caching if needed."""
        tf = timeframe.lower()
        if tf in tf_cache:
            return tf_cache[tf]
        resampled = resample_ohlcv(df, tf)
        tf_cache[tf] = resampled
        return resampled

    results = []
    for name, cls in get_all_indicators().items():
        is_enabled = enabled_indicators.get(name, True)

        if not is_enabled:
            results.append({
                "indicator": name,
                "type": cls.indicator_type,
                "status": "SKIPPED",
                "value": "N/A",
                "threshold": "N/A",
                "details": "Filter disabled",
                "params": {},
                "computed": {},
            })
            continue

        try:
            instance = cls()
            indicator_params = params.get(name, {})

            # Determine which timeframe data to use
            tf = timeframes.get(name, "daily")
            indicator_df = _get_tf_data(tf)

            # Validate the data
            valid, msg = validate_dataframe(indicator_df)
            if not valid:
                results.append({
                    "indicator": name,
                    "type": cls.indicator_type,
                    "status": "ERROR",
                    "value": f"Data validation failed: {msg}",
                    "threshold": "N/A",
                    "details": f"Timeframe: {tf}",
                    "params": {},
                    "computed": {},
                })
                continue

            # Sector Performance needs sector as extra arg
            if name == "Sector Performance":
                merged_params = instance.get_params(indicator_params)
                computed = instance.compute(indicator_df, merged_params, sector=sector)
                result = instance.check(computed, merged_params)
                result["indicator"] = name
                result["type"] = instance.indicator_type
                result["params"] = merged_params
                result["computed"] = computed
            else:
                result = instance.evaluate(indicator_df, indicator_params)

            result["timeframe"] = tf
            results.append(result)
        except Exception as e:
            results.append({
                "indicator": name,
                "type": cls.indicator_type if hasattr(cls, 'indicator_type') else "unknown",
                "status": "ERROR",
                "value": str(e),
                "threshold": "N/A",
                "details": f"Computation failed: {e}",
                "params": {},
                "computed": {},
            })

    return results
