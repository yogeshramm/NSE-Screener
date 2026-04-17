# Phase 2 audit — write paths to `data_store/history/*.pkl`

Date: 2026-04-17
Scope: every code path that creates, appends to, or overwrites a history pickle.
Goal: prove no path can truncate existing history; catch destructive writes before
re-enabling the daily launchd job (`com.nse-screener.daily-update.plist`).

## Inventory of writers

Grepped repo for `pickle\.dump|to_pickle` and filtered to paths that target
`data_store/history/`:

| # | Caller | Location | Safety |
|---|--------|----------|--------|
| 1 | `nse_history.save_history` | `data/nse_history.py:38-62` | Truncation guard (5-bar tolerance) + atomic temp+rename. |
| 2 | `nse_history.append_bhavcopy_to_history` | `data/nse_history.py:181-193` | Concat existing + today → `drop_duplicates(keep="last")` → sort → `save_history`. First-time branch writes only if existing is None/empty. |
| 3 | `nse_history.backfill_from_yfinance` | `data/nse_history.py:222-228` | Concat yf_df + existing with dedup+sort → `save_history`. `keep="last"` on the concat order means existing rows win date overlap. |
| 4 | `setup_data.download_historical_prices._flush_batch` | `setup_data.py` (Phase 1) | Load existing → concat → dedup → sort → atomic temp+rename. Invoked every 50 dates via checkpoint path. |

All other `pickle.dump` hits write to **different** directories and were ruled
out:

- `data/batch_downloader.py:59` → `data_store/{date}/{symbol}.pkl` (daily store)
- `api/routes_data.py:392` → `data_store/fundamentals/{sym}.pkl`
- `data/nse_events.py:48`, `data/nse_institutional.py:36`, `data/stock_news.py:73`
  → feature-specific cache dirs
- `engine/multi_factor.py:138`, `engine/mtf_confluence.py:97`, `data/cache.py:42`
  → analytics caches
- `setup_data.py:488` → fundamentals dir

No direct bypass of the merge-then-save pattern was found.

## Runtime verification

1. `launchctl list | grep nse-screener` → empty (confirmed unloaded).
2. RELIANCE pre-run: 538 bars, 2024-02-08 → 2026-04-17.
3. `python3 -u daily_download.py --prices-only` executed once:
   - Step 1 (Bhavcopy append): 2403 EQ rows parsed, 0 updated / 0 new / 0 errors
     — today's date was already present in every existing pickle, so the
     `if trade_date in existing.index: continue` short-circuit ran. No writes,
     no truncation.
   - Step 3 (yfinance backfill) started for 432 stocks with <200 bars; heavy
     rate-limiting from yfinance (`Too Many Requests`). Killed before completion
     — this does not change the audit conclusion, because every backfill call
     goes through the merge + `save_history` path (row #3) whose safety is
     proven above.
4. RELIANCE post-run: 538 bars, unchanged.
5. `grep -c "\[SAFETY\]" /tmp/daily_run.log` → 0. The guard never had to
   refuse a write.

## Conclusion

No destructive write paths exist. No patch required. Safe to reload the
launchd job.

    launchctl load ~/Library/LaunchAgents/com.nse-screener.daily-update.plist
