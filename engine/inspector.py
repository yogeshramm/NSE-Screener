"""
Indicator Inspector
Produces a full breakdown for each stock showing every filter's
status, actual value, threshold, and whether it was enabled/skipped.
"""


def build_inspector_report(stage1_result: dict, stage2_result: dict | None = None) -> list[dict]:
    """
    Build the full indicator inspector breakdown for a stock.

    Returns a list of dicts, one per filter, with:
      - filter_name
      - category: "technical" / "fundamental" / "breakout" / "timing"
      - status: PASS / FAIL / BORDERLINE / SKIPPED / ERROR
      - actual_value
      - threshold
      - enabled: True/False
      - details
    """
    report = []

    # Technical indicators from Stage 1
    for r in stage1_result.get("indicator_results", []):
        report.append({
            "filter_name": r["indicator"],
            "category": r.get("type", "technical"),
            "status": r["status"],
            "actual_value": r.get("value", "N/A"),
            "threshold": r.get("threshold", "N/A"),
            "enabled": r["status"] != "SKIPPED",
            "details": r.get("details", ""),
            "timeframe": r.get("timeframe", "daily"),
        })

    # Fundamental filters
    for name, r in stage1_result.get("fundamental_results", {}).items():
        report.append({
            "filter_name": name,
            "category": "fundamental",
            "status": r["status"],
            "actual_value": r.get("value", "N/A"),
            "threshold": r.get("threshold", "N/A"),
            "enabled": r["status"] != "SKIPPED",
            "details": r.get("details", ""),
            "timeframe": "N/A",
        })

    # Late entry (Stage 1)
    le1 = stage1_result.get("late_entry", {})
    if le1:
        report.append({
            "filter_name": "Late Entry (Stage 1)",
            "category": "timing",
            "status": le1.get("status", "N/A"),
            "actual_value": le1.get("value", "N/A"),
            "threshold": le1.get("threshold", "N/A"),
            "enabled": le1.get("status") != "SKIPPED",
            "details": le1.get("details", ""),
            "timeframe": "daily",
        })

    # Stage 2 breakout filters
    if stage2_result:
        for name, r in stage2_result.get("breakout_results", {}).items():
            report.append({
                "filter_name": name,
                "category": "breakout",
                "status": r["status"],
                "actual_value": r.get("value", "N/A"),
                "threshold": r.get("threshold", "N/A"),
                "enabled": r["status"] != "SKIPPED",
                "details": r.get("details", ""),
                "timeframe": "daily",
            })

        le2 = stage2_result.get("late_entry", {})
        if le2:
            report.append({
                "filter_name": "Late Entry (Stage 2)",
                "category": "timing",
                "status": le2.get("status", "N/A"),
                "actual_value": le2.get("value", "N/A"),
                "threshold": le2.get("threshold", "N/A"),
                "enabled": le2.get("status") != "SKIPPED",
                "details": le2.get("details", ""),
                "timeframe": "daily",
            })

    return report


def print_inspector_report(report: list[dict], symbol: str):
    """Pretty-print the inspector report to terminal."""
    print(f"\n  {'='*80}")
    print(f"  INDICATOR INSPECTOR: {symbol}")
    print(f"  {'='*80}")
    print(f"  {'Filter':<35s} {'Status':<12s} {'Value':<25s} {'Threshold':<20s}")
    print(f"  {'-'*80}")

    categories = {}
    for r in report:
        cat = r["category"]
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(r)

    for cat_name in ["technical", "fundamental", "breakout", "timing"]:
        items = categories.get(cat_name, [])
        if not items:
            continue
        print(f"\n  [{cat_name.upper()}]")
        for r in items:
            status_tag = r["status"]
            if not r["enabled"]:
                status_tag = "SKIPPED"
            value_str = str(r["actual_value"])[:24]
            threshold_str = str(r["threshold"])[:19]
            print(f"  {r['filter_name']:<35s} {status_tag:<12s} {value_str:<25s} {threshold_str:<20s}")

    # Summary counts
    total = len(report)
    passes = sum(1 for r in report if r["status"] == "PASS")
    fails = sum(1 for r in report if r["status"] == "FAIL")
    borders = sum(1 for r in report if r["status"] == "BORDERLINE")
    skipped = sum(1 for r in report if r["status"] == "SKIPPED")
    errors = sum(1 for r in report if r["status"] == "ERROR")

    print(f"\n  {'-'*80}")
    print(f"  Total: {total} filters | {passes} PASS | {borders} BORDERLINE | {fails} FAIL | {skipped} SKIPPED | {errors} ERROR")
    print(f"  {'='*80}")
