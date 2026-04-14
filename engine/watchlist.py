"""
Watchlist Engine
Persist and evaluate per-stock watchlist with configurable alerts.
Storage: config/watchlist.json (single JSON file).
"""

import json
from pathlib import Path
from datetime import datetime

WATCHLIST_FILE = Path(__file__).parent.parent / "config" / "watchlist.json"


def _load_raw() -> list[dict]:
    if not WATCHLIST_FILE.exists():
        return []
    with open(WATCHLIST_FILE) as f:
        return json.load(f)


def _save_raw(items: list[dict]):
    WATCHLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(items, f, indent=2, default=str)


def load_watchlist() -> list[dict]:
    return _load_raw()


def add_to_watchlist(symbol: str, alerts: list[dict] | None = None) -> dict:
    items = _load_raw()
    symbol = symbol.strip().upper()
    for item in items:
        if item["symbol"] == symbol:
            return item
    new_item = {
        "symbol": symbol,
        "alerts": alerts or [],
        "added_date": datetime.now().isoformat(),
        "notes": "",
    }
    items.append(new_item)
    _save_raw(items)
    return new_item


def remove_from_watchlist(symbol: str) -> bool:
    items = _load_raw()
    symbol = symbol.strip().upper()
    before = len(items)
    items = [i for i in items if i["symbol"] != symbol]
    if len(items) < before:
        _save_raw(items)
        return True
    return False


def add_alert(symbol: str, alert: dict) -> dict | None:
    items = _load_raw()
    symbol = symbol.strip().upper()
    for item in items:
        if item["symbol"] == symbol:
            item["alerts"].append({
                **alert,
                "enabled": True,
                "created": datetime.now().isoformat(),
            })
            _save_raw(items)
            return item
    return None


def remove_alert(symbol: str, alert_index: int) -> dict | None:
    items = _load_raw()
    symbol = symbol.strip().upper()
    for item in items:
        if item["symbol"] == symbol:
            if 0 <= alert_index < len(item["alerts"]):
                item["alerts"].pop(alert_index)
                _save_raw(items)
                return item
    return None


def check_single_alert(alert: dict, stock_data: dict,
                       stage1_result: dict, stage2_result: dict | None) -> dict:
    """Evaluate a single alert against current stock data."""
    if not alert.get("enabled", True):
        return {"triggered": False, "message": "Alert disabled", "details": ""}

    alert_type = alert.get("type", "")
    if alert_type == "indicator":
        return _check_indicator_alert(alert, stage1_result)
    elif alert_type == "price":
        return _check_price_alert(alert, stock_data)
    elif alert_type == "preset":
        return _check_preset_alert(alert, stage1_result, stage2_result)
    return {"triggered": False, "message": f"Unknown type: {alert_type}", "details": ""}


def _check_indicator_alert(alert: dict, stage1_result: dict) -> dict:
    indicator_name = alert.get("indicator", "").upper()
    condition = alert.get("condition", "")
    target_value = float(alert.get("value", 0))

    ind_results = stage1_result.get("indicator_results", [])
    ind = next((r for r in ind_results
                if r.get("indicator", "").upper() == indicator_name), None)

    if ind is None:
        return {"triggered": False, "message": f"{indicator_name} not found", "details": ""}

    # "passes" condition — just check status
    if condition == "passes":
        triggered = ind.get("status") == "PASS"
        return {
            "triggered": triggered,
            "message": f"{indicator_name} {'PASSED' if triggered else 'not passed'}",
            "details": str(ind.get("value", "")),
        }

    # Try to get numeric value from computed dict
    computed = ind.get("computed", {})
    actual = None
    for key in ["rsi", "macd_histogram", "adx", "value", "cmf", "roc",
                "fisher", "cmo", "force_index", "vi_diff"]:
        if key in computed:
            actual = computed[key]
            break
    # Fallback to top-level value
    if actual is None:
        try:
            actual = float(ind.get("value", 0))
        except (ValueError, TypeError):
            actual = None

    if actual is None:
        return {"triggered": False, "message": f"No value for {indicator_name}", "details": ""}

    triggered = False
    if condition == "crosses_above" or condition == "above":
        triggered = actual >= target_value
    elif condition == "crosses_below" or condition == "below":
        triggered = actual <= target_value

    return {
        "triggered": triggered,
        "message": f"{indicator_name} = {actual:.2f}",
        "details": f"{condition} {target_value}",
    }


def _check_price_alert(alert: dict, stock_data: dict) -> dict:
    condition = alert.get("condition", "above")
    target = float(alert.get("value", 0))
    current = stock_data.get("latest_close") or stock_data.get("current_price", 0)
    if not current:
        return {"triggered": False, "message": "No price data", "details": ""}

    triggered = (current >= target) if condition == "above" else (current <= target)
    return {
        "triggered": triggered,
        "message": f"Price = \u20b9{current:.2f}",
        "details": f"{condition} \u20b9{target}",
    }


def _check_preset_alert(alert: dict, stage1_result: dict,
                        stage2_result: dict | None) -> dict:
    s1_passed = stage1_result.get("passed", False)
    s2_passed = stage2_result.get("passed", False) if stage2_result else False
    score = stage1_result.get("score", 0)

    if s2_passed:
        return {"triggered": True, "message": "ENTRY SIGNAL", "details": f"Score: {score}"}
    elif s1_passed:
        return {"triggered": True, "message": "Stage 1 PASS", "details": f"Score: {score}"}
    return {"triggered": False, "message": "Not passing", "details": f"Score: {score}"}
