"""
Eager indicator precomputation — warm the cache after daily_download.

Run this after the morning data update so the FIRST scan of the day is
also instant, not just subsequent ones. Single-process loop is fine; we're
trading wall time for predictability and low RAM (2GB droplet).

Usage (script):
    python -m engine.precompute              # Nifty 500
    python -m engine.precompute --scope all  # full universe

Usage (programmatic, called from daily_download):
    from engine.precompute import warm_cache
    warm_cache(scope="nifty500")
"""

import time
from typing import Iterable

from engine.default_config import get_default_config
from engine.indicator_cache import load_cached, save_cached
from indicators.registry import run_all_indicators


def _build_inputs(config):
    from engine.default_config import CONFIG_TO_INDICATOR
    enabled, params = {}, {}
    for ck, ind in CONFIG_TO_INDICATOR.items():
        cfg = config.get(ck, {})
        enabled[ind] = cfg.get("enabled", True)
        rest = {k: v for k, v in cfg.items() if k != "enabled"}
        if rest:
            params[ind] = rest
    return enabled, params


def _resolve_symbols(scope: str) -> list[str]:
    from data.nse_history import get_history_stats
    from data.nse_symbols import NIFTY_500_FALLBACK, get_nifty500_live

    hist_syms = set(get_history_stats().get("symbols", []))
    if scope == "all":
        return sorted(hist_syms)
    try:
        live = list(get_nifty500_live())
    except Exception:
        live = list(NIFTY_500_FALLBACK)
    if scope == "nifty200":
        live = live[:200]
    return [s for s in live if s in hist_syms]


def warm_cache(scope: str = "nifty500", symbols: Iterable[str] | None = None,
               verbose: bool = True) -> dict:
    """
    Compute and cache indicator_results for every symbol in scope.

    Returns a summary dict {computed, cached_hit, errors, elapsed_s}.
    Safe to run repeatedly — already-fresh entries are skipped.
    """
    from api.data_helper import get_stock_bundle  # lazy import (heavy deps)

    config = get_default_config()
    enabled, params = _build_inputs(config)

    if symbols is None:
        symbols = _resolve_symbols(scope)
    symbols = list(symbols)

    t0 = time.time()
    computed = cached_hit = errors = skipped = 0
    n = len(symbols)

    if verbose:
        print(f"\n  Warming indicator cache for {n} symbols ({scope})...")

    for i, sym in enumerate(symbols, 1):
        try:
            bundle = get_stock_bundle(sym)
            df = bundle.get("daily_df")
            if df is None or len(df) < 50:
                skipped += 1
                continue
            sector = bundle.get("stock_data", {}).get("sector")
            last_bar = str(df.index[-1].date())

            if load_cached(sym, config, sector, last_bar) is not None:
                cached_hit += 1
            else:
                results = run_all_indicators(
                    df, enabled_indicators=enabled, params=params,
                    sector=sector, df_4h=None,
                )
                save_cached(sym, config, sector, last_bar, results)
                computed += 1
        except Exception as e:
            errors += 1
            if verbose:
                print(f"    [WARN] {sym}: {e}")

        if verbose and i % 50 == 0:
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed else 0
            eta = (n - i) / rate if rate else 0
            print(f"    {i}/{n} | computed={computed} hit={cached_hit} "
                  f"err={errors} skip={skipped} | {rate:.1f}/s ETA {eta:.0f}s")

    elapsed = time.time() - t0
    if verbose:
        print(f"\n  Done. computed={computed} hit={cached_hit} "
              f"err={errors} skip={skipped} in {elapsed:.1f}s")

    return {"computed": computed, "cached_hit": cached_hit,
            "errors": errors, "skipped": skipped, "elapsed_s": elapsed,
            "total": n}


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Warm the indicator cache.")
    p.add_argument("--scope", default="nifty500",
                   choices=["nifty200", "nifty500", "all"])
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args()
    warm_cache(scope=args.scope, verbose=not args.quiet)
