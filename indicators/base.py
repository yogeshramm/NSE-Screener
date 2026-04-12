"""
Base Indicator Class
Every indicator in the screener extends this base class.
Adding a new indicator = creating one new file with one class. Nothing else changes.
"""

from abc import ABC, abstractmethod
import pandas as pd


class BaseIndicator(ABC):
    """
    Base class for all indicators.

    Every indicator must define:
      - name: human-readable name
      - indicator_type: "technical" or "fundamental" or "breakout"
      - default_params: dict of parameter names and default values
      - compute(): takes OHLCV DataFrame + params, returns computed Series/value
      - check(): takes computed values + params, returns PASS/FAIL/BORDERLINE + details
    """

    name: str = "Base Indicator"
    indicator_type: str = "technical"  # "technical", "fundamental", "breakout"
    description: str = ""

    # Precision/efficiency tiers — helps user pick the best indicators
    # "most_precise": Top 5 most precise indicators for swing trading
    # "hidden_gem":   Top 5 underrated/efficient indicators
    # None:           Standard indicator
    precision_tier: str | None = None

    # Extra highlight — user's top 3 preferred indicators for replacement
    highlighted: bool = False

    @property
    @abstractmethod
    def default_params(self) -> dict:
        """Return dict of default parameters for this indicator."""
        pass

    @abstractmethod
    def compute(self, df: pd.DataFrame, params: dict) -> dict:
        """
        Compute the indicator values.

        Args:
            df: OHLCV DataFrame with columns Open, High, Low, Close, Volume
            params: dict of parameter values (merged with defaults)

        Returns:
            dict with computed values (indicator-specific keys)
        """
        pass

    @abstractmethod
    def check(self, computed: dict, params: dict) -> dict:
        """
        Check if the stock passes this indicator's filter.

        Args:
            computed: dict from compute()
            params: dict of parameter values

        Returns:
            dict with:
              - status: "PASS" | "FAIL" | "BORDERLINE"
              - value: the actual computed value
              - threshold: the required threshold
              - details: human-readable explanation
        """
        pass

    def get_params(self, user_params: dict | None = None) -> dict:
        """Merge user-provided params with defaults."""
        params = dict(self.default_params)
        if user_params:
            params.update(user_params)
        return params

    def evaluate(self, df: pd.DataFrame, user_params: dict | None = None) -> dict:
        """
        Full evaluation: compute + check.
        Returns the complete inspector result for this indicator.
        """
        params = self.get_params(user_params)
        computed = self.compute(df, params)
        result = self.check(computed, params)
        result["indicator"] = self.name
        result["type"] = self.indicator_type
        result["params"] = params
        result["computed"] = computed
        return result
