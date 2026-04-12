"""Pivot Levels — Price must be above both monthly and quarterly pivot levels."""

import pandas as pd
from indicators.base import BaseIndicator


class PivotLevelsIndicator(BaseIndicator):
    name = "Pivot Levels"
    indicator_type = "technical"
    description = "Price must be above monthly and quarterly pivot levels"

    @property
    def default_params(self) -> dict:
        return {"pivot_type": "both"}  # "monthly", "quarterly", "both"

    def _compute_pivot(self, high: float, low: float, close: float) -> dict:
        """Standard pivot point calculation."""
        pivot = (high + low + close) / 3
        r1 = 2 * pivot - low
        s1 = 2 * pivot - high
        r2 = pivot + (high - low)
        s2 = pivot - (high - low)
        return {
            "pivot": round(pivot, 2),
            "r1": round(r1, 2), "r2": round(r2, 2),
            "s1": round(s1, 2), "s2": round(s2, 2),
        }

    def compute(self, df: pd.DataFrame, params: dict) -> dict:
        # Monthly pivot: use last complete month's data
        df_with_dates = df.copy()
        if hasattr(df.index, 'tz') and df.index.tz is not None:
            dates = df.index.tz_localize(None)
        else:
            dates = df.index
        df_with_dates.index = dates

        # Group by month
        monthly = df_with_dates.resample("ME").agg({
            "High": "max", "Low": "min", "Close": "last"
        }).dropna()

        monthly_pivot = {}
        if len(monthly) >= 2:
            prev_month = monthly.iloc[-2]
            monthly_pivot = self._compute_pivot(prev_month["High"], prev_month["Low"], prev_month["Close"])

        # Quarterly pivot: use last complete quarter's data
        quarterly = df_with_dates.resample("QE").agg({
            "High": "max", "Low": "min", "Close": "last"
        }).dropna()

        quarterly_pivot = {}
        if len(quarterly) >= 2:
            prev_quarter = quarterly.iloc[-2]
            quarterly_pivot = self._compute_pivot(prev_quarter["High"], prev_quarter["Low"], prev_quarter["Close"])

        latest_close = df["Close"].iloc[-1]
        above_monthly = latest_close > monthly_pivot.get("pivot", 0) if monthly_pivot else None
        above_quarterly = latest_close > quarterly_pivot.get("pivot", 0) if quarterly_pivot else None

        return {
            "close": round(latest_close, 2),
            "monthly_pivot": monthly_pivot.get("pivot"),
            "quarterly_pivot": quarterly_pivot.get("pivot"),
            "above_monthly": above_monthly,
            "above_quarterly": above_quarterly,
            "monthly_levels": monthly_pivot,
            "quarterly_levels": quarterly_pivot,
        }

    def check(self, computed: dict, params: dict) -> dict:
        above_m = computed["above_monthly"]
        above_q = computed["above_quarterly"]

        if above_m is None and above_q is None:
            return {"status": "FAIL", "value": "N/A", "threshold": "Above pivots", "details": "Insufficient data"}

        pivot_type = params["pivot_type"]
        if pivot_type == "monthly":
            passed = above_m is True
        elif pivot_type == "quarterly":
            passed = above_q is True
        else:  # both
            passed = above_m is True and above_q is True

        above_one = (above_m is True) or (above_q is True)
        if passed:
            status = "PASS"
        elif above_one:
            status = "BORDERLINE"
        else:
            status = "FAIL"

        return {
            "status": status,
            "value": f"Monthly Pivot={computed['monthly_pivot']}, Quarterly Pivot={computed['quarterly_pivot']}",
            "threshold": f"Above {pivot_type} pivot(s)",
            "details": f"Above Monthly: {above_m}, Above Quarterly: {above_q}",
        }
