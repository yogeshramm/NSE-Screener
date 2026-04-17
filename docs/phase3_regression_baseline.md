# Phase 3.12 regression baseline

Date: 2026-04-17 (post-HEAD `012fd06`, after Phase 1 2-year history download,
Phase 2 write-path audit, Phase 3.10 resolve cache, Phase 3.11 multi_factor
lazy update).

Fixtures
- Universe: 12 liquid large-caps
  `[RELIANCE, TCS, INFY, HDFCBANK, ITC, MARUTI, TRENT, BAJFINANCE, SBIN, LT, WIPRO, ADANIGREEN]`
- Presets: all 4 active JSONs under `config/presets/`
- Request: `POST /screen` with `{symbols, config, stage2: true}`

Results

| Preset | Stage 1 rows | Stage 2 picks | S2 symbols |
|---|---|---|---|
| `of_v3_sw_P1.json` | 12 | 10 | ITC, WIPRO, TCS, ADANIGREEN, INFY, LT, MARUTI, TRENT, SBIN, BAJFINANCE |
| `optimised_hunter_short_swing_p3.json` | 12 | 6 | ADANIGREEN, ITC, LT, TRENT, TCS, SBIN |
| `optimised_hunter_swing_p2.json` | 12 | 10 | ITC, WIPRO, ADANIGREEN, SBIN, MARUTI, TCS, INFY, TRENT, BAJFINANCE, LT |
| `original_formula.json` | 12 | 10 | LT, TCS, MARUTI, WIPRO, ITC, BAJFINANCE, SBIN, INFY, TRENT, ADANIGREEN |

Observations
- `HDFCBANK` and `RELIANCE` drop out of Stage 2 across every preset — first
  regression baseline the project has; future screen changes can diff against
  this table to spot unintended filter drift.
- `optimised_hunter_short_swing_p3` is the strictest of the four (6/12 pass).
- The other three converge on the same 10-stock core with different ordering.

This file is the reference for future regressions. If a code change alters any
row here, flag it in the commit message.
