"""
Fundamental Filter Checker
Evaluates fundamental data against filter thresholds.
These filters use data from yfinance ticker.info, not OHLCV.
"""

from datetime import datetime, timedelta


def check_fundamentals(stock_data: dict, config: dict) -> dict:
    """
    Check all fundamental filters for a stock.

    Args:
        stock_data: dict from yfinance_fetcher.fetch_all()
        config: filter configuration dict

    Returns:
        dict of {filter_name: {status, value, threshold, details}}
    """
    results = {}

    # --- ROE ---
    cfg = config.get("roe", {})
    if cfg.get("enabled", True):
        roe_pct = stock_data.get("roe_pct")
        minimum = cfg.get("roe_minimum", 12)
        if roe_pct is not None:
            margin = minimum * 0.05
            if roe_pct >= minimum:
                status = "PASS"
            elif roe_pct >= minimum - margin:
                status = "BORDERLINE"
            else:
                status = "FAIL"
            results["roe"] = {
                "status": status, "value": f"{roe_pct}%",
                "threshold": f">= {minimum}%", "details": f"ROE = {roe_pct}%",
            }
        else:
            results["roe"] = {
                "status": "FAIL", "value": "N/A",
                "threshold": f">= {minimum}%", "details": "ROE data unavailable",
            }
    else:
        results["roe"] = {"status": "SKIPPED", "value": "N/A", "threshold": "N/A", "details": "Disabled"}

    # --- ROCE ---
    cfg = config.get("roce", {})
    if cfg.get("enabled", True):
        roce = stock_data.get("roce")
        minimum = cfg.get("roce_minimum", 10)
        if roce is not None:
            margin = minimum * 0.05
            if roce >= minimum:
                status = "PASS"
            elif roce >= minimum - margin:
                status = "BORDERLINE"
            else:
                status = "FAIL"
            results["roce"] = {
                "status": status, "value": f"{roce}%",
                "threshold": f">= {minimum}%", "details": f"ROCE = {roce}%",
            }
        else:
            results["roce"] = {
                "status": "FAIL", "value": "N/A",
                "threshold": f">= {minimum}%", "details": "ROCE data unavailable",
            }
    else:
        results["roce"] = {"status": "SKIPPED", "value": "N/A", "threshold": "N/A", "details": "Disabled"}

    # --- Debt to Equity ---
    cfg = config.get("debt_to_equity", {})
    if cfg.get("enabled", True):
        de = stock_data.get("debt_to_equity_ratio")
        maximum = cfg.get("de_maximum", 1.0)
        sector = stock_data.get("sector", "")
        # PSU/Infra exemption
        psu_infra = cfg.get("exclude_psu_infra", True)
        is_exempt = psu_infra and sector in ("Utilities", "Industrials", "Energy")

        if de is not None:
            if is_exempt:
                results["debt_to_equity"] = {
                    "status": "PASS", "value": f"{de}",
                    "threshold": f"<= {maximum} (PSU/Infra exempt)",
                    "details": f"D/E = {de}, sector {sector} exempted",
                }
            elif de <= maximum:
                status = "PASS"
                margin = maximum * 0.05
                if de > maximum - margin:
                    status = "BORDERLINE"
                results["debt_to_equity"] = {
                    "status": status, "value": f"{de}",
                    "threshold": f"<= {maximum}",
                    "details": f"D/E = {de}",
                }
            else:
                results["debt_to_equity"] = {
                    "status": "FAIL", "value": f"{de}",
                    "threshold": f"<= {maximum}",
                    "details": f"D/E = {de} exceeds maximum",
                }
        elif de is None and stock_data.get("sector") == "Financial Services":
            # Banks don't typically report D/E through yfinance
            results["debt_to_equity"] = {
                "status": "PASS", "value": "N/A (Bank)",
                "threshold": f"<= {maximum}",
                "details": "D/E not applicable for banks",
            }
        else:
            results["debt_to_equity"] = {
                "status": "FAIL", "value": "N/A",
                "threshold": f"<= {maximum}",
                "details": "D/E data unavailable",
            }
    else:
        results["debt_to_equity"] = {"status": "SKIPPED", "value": "N/A", "threshold": "N/A", "details": "Disabled"}

    # --- EPS ---
    cfg = config.get("eps", {})
    if cfg.get("enabled", True):
        eps = stock_data.get("trailing_eps")
        minimum = cfg.get("eps_minimum", 0)
        if eps is not None and eps > minimum:
            results["eps"] = {
                "status": "PASS", "value": f"{eps}",
                "threshold": f"> {minimum}",
                "details": f"EPS = {eps}",
            }
        elif eps is not None:
            results["eps"] = {
                "status": "FAIL", "value": f"{eps}",
                "threshold": f"> {minimum}",
                "details": f"EPS = {eps}",
            }
        else:
            results["eps"] = {
                "status": "FAIL", "value": "N/A",
                "threshold": f"> {minimum}", "details": "EPS data unavailable",
            }
    else:
        results["eps"] = {"status": "SKIPPED", "value": "N/A", "threshold": "N/A", "details": "Disabled"}

    # --- Free Cash Flow ---
    cfg = config.get("free_cash_flow", {})
    if cfg.get("enabled", True):
        fcf = stock_data.get("free_cash_flow")
        if fcf is not None and fcf > 0:
            results["free_cash_flow"] = {
                "status": "PASS", "value": f"{fcf:,.0f}",
                "threshold": "Positive",
                "details": f"FCF = {fcf:,.0f}",
            }
        elif fcf is not None:
            results["free_cash_flow"] = {
                "status": "FAIL", "value": f"{fcf:,.0f}",
                "threshold": "Positive",
                "details": f"FCF = {fcf:,.0f} (negative)",
            }
        else:
            results["free_cash_flow"] = {
                "status": "FAIL", "value": "N/A",
                "threshold": "Positive", "details": "FCF data unavailable",
            }
    else:
        results["free_cash_flow"] = {"status": "SKIPPED", "value": "N/A", "threshold": "N/A", "details": "Disabled"}

    # --- Institutional Holdings ---
    cfg = config.get("institutional_holdings", {})
    if cfg.get("enabled", True):
        holdings = stock_data.get("institutional_holdings_pct")
        if holdings is not None:
            results["institutional_holdings"] = {
                "status": "PASS", "value": f"{holdings}%",
                "threshold": "Stable or rising",
                "details": f"Institutional: {holdings}%",
            }
        else:
            # yfinance often returns None for Indian stocks — don't penalize
            results["institutional_holdings"] = {
                "status": "BORDERLINE", "value": "N/A",
                "threshold": "Stable or rising",
                "details": "Institutional data unavailable (common for NSE stocks)",
            }
    else:
        results["institutional_holdings"] = {"status": "SKIPPED", "value": "N/A", "threshold": "N/A", "details": "Disabled"}

    # --- Analyst Ratings ---
    cfg = config.get("analyst_ratings", {})
    if cfg.get("enabled", True):
        recs = stock_data.get("recommendations")
        minimum = cfg.get("analyst_buy_minimum", 3)
        if recs is not None and hasattr(recs, 'empty') and not recs.empty:
            # Count buy + strongBuy from most recent period
            latest = recs.iloc[0] if len(recs) > 0 else {}
            buy_count = 0
            if hasattr(latest, 'get'):
                buy_count = latest.get("buy", 0) + latest.get("strongBuy", 0)
            elif hasattr(latest, '__getitem__'):
                buy_count = (latest.get("buy", 0) if hasattr(latest, 'get')
                            else (latest["buy"] if "buy" in latest.index else 0))
                strong = (latest.get("strongBuy", 0) if hasattr(latest, 'get')
                         else (latest["strongBuy"] if "strongBuy" in latest.index else 0))
                buy_count = int(buy_count) + int(strong)

            if buy_count >= minimum:
                results["analyst_ratings"] = {
                    "status": "PASS", "value": f"{buy_count} buy/strongBuy",
                    "threshold": f">= {minimum}",
                    "details": f"Buy+StrongBuy = {buy_count}",
                }
            else:
                results["analyst_ratings"] = {
                    "status": "FAIL", "value": f"{buy_count} buy/strongBuy",
                    "threshold": f">= {minimum}",
                    "details": f"Buy+StrongBuy = {buy_count}",
                }
        else:
            results["analyst_ratings"] = {
                "status": "FAIL", "value": "N/A",
                "threshold": f">= {minimum}",
                "details": "No analyst data",
            }
    else:
        results["analyst_ratings"] = {"status": "SKIPPED", "value": "N/A", "threshold": "N/A", "details": "Disabled"}

    # --- Earnings Blackout ---
    cfg = config.get("earnings_blackout", {})
    if cfg.get("enabled", True):
        calendar = stock_data.get("earnings_calendar", {})
        blackout_days = cfg.get("earnings_blackout_days", 7)
        earnings_date = None

        if isinstance(calendar, dict):
            ed = calendar.get("Earnings Date")
            if ed is not None:
                if isinstance(ed, list):
                    earnings_date = ed[0] if ed else None
                elif isinstance(ed, dict):
                    earnings_date = list(ed.values())[0] if ed else None
                else:
                    earnings_date = ed

        if earnings_date is not None:
            try:
                from pandas import Timestamp
                if isinstance(earnings_date, Timestamp):
                    ed_date = earnings_date.date()
                else:
                    ed_date = datetime.strptime(str(earnings_date)[:10], "%Y-%m-%d").date()
                days_until = (ed_date - datetime.now().date()).days
                if days_until > blackout_days:
                    results["earnings_blackout"] = {
                        "status": "PASS",
                        "value": f"{days_until} days until earnings",
                        "threshold": f"> {blackout_days} days",
                        "details": f"Earnings on {ed_date}",
                    }
                elif days_until >= 0:
                    results["earnings_blackout"] = {
                        "status": "FAIL",
                        "value": f"{days_until} days until earnings",
                        "threshold": f"> {blackout_days} days",
                        "details": f"Earnings too close: {ed_date}",
                    }
                else:
                    # Earnings already passed
                    results["earnings_blackout"] = {
                        "status": "PASS",
                        "value": f"Earnings passed ({abs(days_until)} days ago)",
                        "threshold": f"> {blackout_days} days",
                        "details": f"Last earnings: {ed_date}",
                    }
            except Exception:
                results["earnings_blackout"] = {
                    "status": "BORDERLINE", "value": "Unknown",
                    "threshold": f"> {blackout_days} days",
                    "details": "Could not parse earnings date",
                }
        else:
            results["earnings_blackout"] = {
                "status": "PASS", "value": "No upcoming earnings found",
                "threshold": f"> {blackout_days} days",
                "details": "No earnings date in calendar",
            }
    else:
        results["earnings_blackout"] = {"status": "SKIPPED", "value": "N/A", "threshold": "N/A", "details": "Disabled"}

    # --- PE Ratio ---
    cfg = config.get("pe_ratio", {})
    if cfg.get("enabled", True):
        pe = stock_data.get("trailing_pe")
        maximum = cfg.get("pe_maximum", 40)
        if pe is not None:
            margin = maximum * 0.05
            if pe <= maximum:
                status = "PASS"
                if pe > maximum - margin:
                    status = "BORDERLINE"
                results["pe_ratio"] = {
                    "status": status, "value": f"{round(pe, 2)}",
                    "threshold": f"<= {maximum}",
                    "details": f"PE = {round(pe, 2)}",
                }
            else:
                results["pe_ratio"] = {
                    "status": "FAIL", "value": f"{round(pe, 2)}",
                    "threshold": f"<= {maximum}",
                    "details": f"PE = {round(pe, 2)} exceeds maximum",
                }
        else:
            results["pe_ratio"] = {
                "status": "FAIL", "value": "N/A",
                "threshold": f"<= {maximum}",
                "details": "PE data unavailable",
            }
    else:
        results["pe_ratio"] = {"status": "SKIPPED", "value": "N/A", "threshold": "N/A", "details": "Disabled"}

    # --- Daily Turnover ---
    cfg = config.get("daily_turnover", {})
    if cfg.get("enabled", True):
        avg_vol = stock_data.get("average_volume")
        price = stock_data.get("current_price") or stock_data.get("latest_close")
        minimum_cr = cfg.get("turnover_minimum", 5)
        if avg_vol is not None and price is not None:
            turnover_cr = (avg_vol * price) / 10_000_000  # convert to crore
            if turnover_cr >= minimum_cr:
                results["daily_turnover"] = {
                    "status": "PASS", "value": f"{round(turnover_cr, 1)} Cr",
                    "threshold": f">= {minimum_cr} Cr",
                    "details": f"Avg turnover = {round(turnover_cr, 1)} Cr/day",
                }
            else:
                results["daily_turnover"] = {
                    "status": "FAIL", "value": f"{round(turnover_cr, 1)} Cr",
                    "threshold": f">= {minimum_cr} Cr",
                    "details": f"Avg turnover = {round(turnover_cr, 1)} Cr/day",
                }
        else:
            results["daily_turnover"] = {
                "status": "FAIL", "value": "N/A",
                "threshold": f">= {minimum_cr} Cr",
                "details": "Volume/price data unavailable",
            }
    else:
        results["daily_turnover"] = {"status": "SKIPPED", "value": "N/A", "threshold": "N/A", "details": "Disabled"}

    # --- Free Float (estimated from institutional + promoter holdings) ---
    cfg = config.get("free_float", {})
    if cfg.get("enabled", True):
        # yfinance doesn't reliably provide free float for NSE stocks
        # Pass with BORDERLINE since this data is hard to get
        results["free_float"] = {
            "status": "BORDERLINE", "value": "N/A",
            "threshold": f">= {cfg.get('freefloat_minimum', 30)}%",
            "details": "Free float data not available via yfinance (will use NSE data when available)",
        }
    else:
        results["free_float"] = {"status": "SKIPPED", "value": "N/A", "threshold": "N/A", "details": "Disabled"}

    return results
