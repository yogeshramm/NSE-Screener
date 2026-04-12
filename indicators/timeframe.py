"""
Timeframe Resampler Utility
Converts daily OHLCV data to weekly, monthly, or any custom timeframe.
All indicators can use this to compute on different timeframes without errors.
"""

import pandas as pd


def resample_ohlcv(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """
    Resample OHLCV data to a different timeframe.

    Args:
        df: Daily OHLCV DataFrame with DatetimeIndex
        timeframe: One of "daily", "weekly", "monthly", "4H"
                   Also supports pandas offset aliases: "W", "ME", "QE"

    Returns:
        Resampled OHLCV DataFrame
    """
    timeframe = timeframe.strip().lower()

    # Map friendly names to pandas offset aliases
    tf_map = {
        "daily": None,       # no resampling needed
        "1d": None,
        "weekly": "W",
        "1w": "W",
        "monthly": "ME",
        "1m": "ME",
        "quarterly": "QE",
        "1q": "QE",
        "4h": "4h",
    }

    offset = tf_map.get(timeframe, timeframe)

    if offset is None:
        return df.copy()

    # Strip timezone for resampling if present
    original_tz = None
    if hasattr(df.index, 'tz') and df.index.tz is not None:
        original_tz = df.index.tz
        df = df.copy()
        df.index = df.index.tz_localize(None)

    resampled = df.resample(offset).agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum",
    }).dropna()

    if original_tz is not None:
        resampled.index = resampled.index.tz_localize(original_tz)

    return resampled


def get_timeframe_data(df: pd.DataFrame, timeframe: str, min_bars: int = 20) -> pd.DataFrame:
    """
    Get data for a specific timeframe with minimum bar validation.

    Args:
        df: Daily OHLCV DataFrame
        timeframe: Desired timeframe
        min_bars: Minimum number of bars required

    Returns:
        Resampled DataFrame

    Raises:
        ValueError if insufficient data after resampling
    """
    resampled = resample_ohlcv(df, timeframe)

    if len(resampled) < min_bars:
        raise ValueError(
            f"Insufficient data for {timeframe} timeframe: "
            f"got {len(resampled)} bars, need at least {min_bars}"
        )

    return resampled


def validate_dataframe(df: pd.DataFrame) -> tuple[bool, str]:
    """
    Validate an OHLCV DataFrame has all required columns and sufficient data.

    Returns:
        (is_valid, error_message)
    """
    required_cols = ["Open", "High", "Low", "Close", "Volume"]

    for col in required_cols:
        if col not in df.columns:
            return False, f"Missing required column: {col}"

    if len(df) == 0:
        return False, "DataFrame is empty"

    if len(df) < 5:
        return False, f"Insufficient data: only {len(df)} bars (need at least 5)"

    if df["Close"].isna().all():
        return False, "All Close values are NaN"

    return True, "OK"
