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
from pathlib import Path
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
    # IMPORTANT: bypass api.data_helper.get_stock_bundle here. That helper
    # falls through to live yfinance fetches when local data is short, which
    # would turn a 6-minute precompute into hours of rate-limited yfinance
    # calls (each small-cap with < 50 local bars triggers an 8-step fetch).
    # We only ever want to warm symbols that already have sufficient local
    # history, so read pickles directly and skip the rest immediately.
    import pickle as _pk
    from setup_data import HISTORY_DIR, FUNDAMENTALS_DIR

    # Warm the default config + every preset in config/presets/. Without this,
    # picking a preset on the UI triggers a full cold scan (22s+ on Nifty 500)
    # because the cache key includes the config hash. The cache holds up to 5
    # entries per symbol, which fits 1 default + up to 4 presets.
    import json
    base = get_default_config()
    enabled, params = _build_inputs(base)  # kept for backward compat (unused below)
    configs: list[tuple[str, dict]] = [("default", base)]
    presets_dir = Path(__file__).parent.parent / "config" / "presets"
    if presets_dir.exists():
        for pf in sorted(presets_dir.glob("*.json")):
            try:
                preset_overrides = json.loads(pf.read_text())
                merged = {**base}
                for k, v in preset_overrides.items():
                    if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
                        merged[k] = {**merged[k], **v}
                    else:
                        merged[k] = v
                configs.append((pf.stem, merged))
            except Exception as e:
                if verbose:
                    print(f"  [WARN] preset {pf.stem}: {e}")

    if symbols is None:
        symbols = _resolve_symbols(scope)
    symbols = list(symbols)
    if verbose:
        print(f"  Warming for {len(configs)} configs: {[n for n,_ in configs]}")

    t0 = time.time()
    computed = cached_hit = errors = skipped = 0
    n = len(symbols)

    if verbose:
        print(f"\n  Warming indicator cache for {n} symbols ({scope})...")

    for i, sym in enumerate(symbols, 1):
        try:
            hist_path = HISTORY_DIR / f"{sym}.pkl"
            if not hist_path.exists():
                skipped += 1
                continue
            with open(hist_path, "rb") as f:
                df = _pk.load(f)
            if df is None or len(df) < 50:
                skipped += 1
                continue
            sector = None
            fund_path = FUNDAMENTALS_DIR / f"{sym}.pkl"
            if fund_path.exists():
                try:
                    with open(fund_path, "rb") as f:
                        sector = _pk.load(f).get("sector")
                except Exception:
                    pass
            last_bar = str(df.index[-1].date())

            for cfg_name, cfg in configs:
                en, pa = _build_inputs(cfg)
                if load_cached(sym, cfg, sector, last_bar) is not None:
                    cached_hit += 1
                else:
                    results = run_all_indicators(
                        df, enabled_indicators=en, params=pa,
                        sector=sector, df_4h=None,
                    )
                    save_cached(sym, cfg, sector, last_bar, results)
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
