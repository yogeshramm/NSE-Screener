"""
Indicator Precompute — warms the indicator cache for all symbols.
Run by daily_download.py after market close so daytime scans are instant.
Reads pickles directly — never falls through to live yfinance.
"""

import pickle
from pathlib import Path

from engine.default_config import get_default_config
from engine.indicator_cache import load_cached, save_cached, _config_hash, purge_stale_date_files
from indicators.registry import run_all_indicators
from engine.presets import load_preset

HISTORY_DIR = Path(__file__).parent.parent / "data_store" / "history"
FUNDAMENTALS_DIR = Path(__file__).parent.parent / "data_store" / "fundamentals"


def _load_bundle(symbol: str):
    """Load daily_df + sector from disk only. Returns (daily_df, sector) or (None, None)."""
    hist_path = HISTORY_DIR / f"{symbol}.pkl"
    if not hist_path.exists():
        return None, None
    try:
        with open(hist_path, "rb") as f:
            daily_df = pickle.load(f)
        if daily_df is None or len(daily_df) < 50:
            return None, None
    except Exception:
        return None, None

    sector = None
    fund_path = FUNDAMENTALS_DIR / f"{symbol}.pkl"
    if fund_path.exists():
        try:
            with open(fund_path, "rb") as f:
                fund = pickle.load(f)
            sector = fund.get("sector") if isinstance(fund, dict) else None
        except Exception:
            pass

    return daily_df, sector


def _get_configs() -> list[dict]:
    """Return default config + all saved presets (deduplicated by hash)."""
    configs = [get_default_config()]
    seen_hashes = {_config_hash(configs[0])}
    presets_dir = Path(__file__).parent.parent / "config" / "presets"
    if presets_dir.exists():
        for pf in presets_dir.glob("*.json"):
            try:
                p = load_preset(pf.stem)
                if p and p.get("config"):
                    c = get_default_config()
                    for k, v in p["config"].items():
                        if k in c and isinstance(c[k], dict) and isinstance(v, dict):
                            c[k].update(v)
                        else:
                            c[k] = v
                    h = _config_hash(c)
                    if h not in seen_hashes:
                        configs.append(c)
                        seen_hashes.add(h)
            except Exception:
                pass
    return configs


def warm_cache(symbols: list[str] | None = None, verbose: bool = False) -> dict:
    """
    Precompute indicator results for all symbols × all distinct config hashes.
    Each (symbol, config_hash) gets its own cache file ({symbol}_{hash}.pkl)
    so multiple presets coexist without overwriting each other.
    Stale-hash files (unknown configs) are purged automatically.
    Returns stats dict.
    """
    if symbols is None:
        symbols = [p.stem for p in HISTORY_DIR.glob("*.pkl")]

    configs = _get_configs()
    current_hashes = {_config_hash(c) for c in configs}

    # Purge old-format {symbol}.pkl files and files with unknown hashes.
    purged = purge_stale_date_files(symbols, current_hashes, current_date="")
    if verbose and purged:
        print(f"  Purged {purged} stale/old-format cache files")

    hits = misses = skipped = 0

    for symbol in symbols:
        daily_df, sector = _load_bundle(symbol)
        if daily_df is None:
            skipped += 1
            continue

        last_bar_date = str(daily_df.index[-1].date())

        for config in configs:
            cached = load_cached(symbol, config, sector, last_bar_date)
            if cached is not None:
                hits += 1
                continue
            try:
                results = run_all_indicators(daily_df, sector=sector)
                save_cached(symbol, config, sector, last_bar_date, results)
                misses += 1
            except Exception as e:
                if verbose:
                    print(f"  [WARN] {symbol}: {e}")
                skipped += 1

    if verbose:
        print(f"  Precompute done: {misses} computed, {hits} already cached, {skipped} skipped")
    return {"computed": misses, "cached": hits, "skipped": skipped, "purged": purged}
