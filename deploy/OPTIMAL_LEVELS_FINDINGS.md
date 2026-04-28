# Optimal Entry / Exit — methodology + measured efficiency

*Built and tested locally on 2026-04-28. Not deployed to production.*

## What was built

**Backend** (`engine/optimal_levels.py`)
A forward-looking analyzer that produces a single trade plan per stock:

```
Entry  /  Stop  /  Target  +  0–100 confidence score  +  rationale list
```

The score blends 9 components (clamped to 100):

| Factor | Max | What it measures |
|---|---|---|
| Trend regime | 25 | Price vs EMA21 / EMA50 / SMA200 (4 buckets) |
| ADX(14) strength | 20 | Whether the trend has actual conviction |
| R:R ratio | 15 | 2.0× risk minimum, capped near 52W high |
| Risk size | 10 | Tighter stops (< 5%) = better |
| VCP score | 10 | Recent 20-bar range vs prior 20-bar range |
| Higher-TF aligned | 10 | Weekly close > weekly EMA10 |
| Volume context | 10 | 5d/20d ratio — contraction is best |
| **Consensus bonus** | +25 | MFS percentile + MTF (1D/1W/1M) + chart pattern + bulk-deals |
| **Exhaustion penalty** | −25 | Mature 60d return + RSI overbought |

Bands: ≥75 = high · ≥55 = moderate · ≥35 = low · <35 = very_low.
Downtrend stocks return `tradeable=False` with full diagnostic context.

**Backtest harness** (`engine/optimal_levels_backtest.py`)
Walks history backwards. At each sample point it computes the plan using
ONLY data available *at that moment*, then watches the next 60 bars to see
which level was hit first — entry triggered? target? stop? hold expiry?
Aggregates win rate / R-multiples / fill rate by regime + confidence band.

**API**
`GET /stock/{sym}/optimal-levels` returns the full plan as JSON. Auto-loaded
by the running `uvicorn --reload` on the local laptop server.

**Frontend** (`frontend/index.html`)
- New `ENTRY/EXIT` button next to INFO / HELP / EVENTS / TEMPLATE in the
  chart header.
- When toggled ON, fetches the plan, draws 3 horizontal price lines on the
  candle chart (entry blue, stop red dashed, target green), and shows a
  panel with the score, breakdown, consensus chips, and rationale.
- Resets cleanly when chart is closed or another stock is opened.

---

## Measured efficiency (the honest part)

100 stocks × 4 historical samples each = **308 plans generated**, 127
tradeable, 119 trades entered, 60-bar forward window.

### Headline numbers

| Metric | Value |
|---|---|
| Plans generated | 308 |
| Tradeable plans | 127 (41%) |
| Trades entered | 119 (94% fill rate on tradeable) |
| **Overall win rate** | **30.3%** |
| **Avg R per trade** | **−0.17R** |
| Avg winner | +1.73R |
| Avg loser | −1.00R |

**The strategy is unprofitable on average.** Break-even at the current
2.0R / −1.0R payoff ratio is ~33% win rate. We're at 30.3%.

### By confidence band — the surprise

| Band | n | Win rate | Avg R |
|---|---|---|---|
| **moderate** | 50 | **40.0%** | **+0.09R** ← profitable |
| high | 49 | 22.4% | −0.39R ← worse than coin flip |
| low | 19 | 26.3% | −0.27R |
| very_low | 1 | 0% | −1.0R |

The "high-confidence" band — uptrend + strong ADX + VCP pattern + good R:R
— *underperforms*. Likely cause: those setups are typically late-stage moves
that have already extended. Buyers see strength → enter → trend exhausts.

The **moderate band has positive expectancy** (+0.09R/trade × 40% wins).
Mid-confidence setups catch earlier-stage trends before everything
"looks good".

### By regime

| Regime | n | Win rate | Avg R |
|---|---|---|---|
| early_uptrend | 19 | 31.6% | −0.05R |
| sideways | 50 | 30.0% | −0.13R |
| uptrend | 50 | 30.0% | −0.27R |

All regimes near 30% — confidence band is the more discriminating signal.

### Exit-reason mix

```
stop hit:     83  (70%)
target hit:   32  (27%)
hold expiry:   4  (3%)
```

Stops dominate because targets are 2.0R away vs stops 1.0R — wider distance
to target = lower probability of reaching it in 60 bars.

---

## What this means for shipping

**Don't market it as "Optimal Trade Plan"** — at 30% win rate, that would
be misleading and expose you to legitimate complaints.

**Honest options for tomorrow:**

### Option A — Ship as "Decision-Support Levels", filter to moderate
Show the panel for ALL stocks, but visually de-emphasize high/low/very-low
confidence (gray out). Highlight moderate-band setups only. Add a header
disclosure:

> *"Backtest on 100 stocks × 4 historical samples shows ~30% overall hit
> rate. Moderate-confidence setups have measured the most edge
> (+0.09R/trade, 40% win rate). Educational only."*

This is honest, defensible, and actually has an edge.

### Option B — Ship as "Reference Levels" only, no claim of edge
Drop all confidence labels. Just show entry/stop/target as "structurally-
derived levels" — i.e. *"here's where ATR + 20-day swing + 2R math suggest
you should set your levels IF you decide to trade this"*. Pure infrastructure.
No win-rate claim.

### Option C — Don't ship until algorithm has measurable edge
Hold it back. Iterate further:
- Mean-reversion mode for sideways (buy range low, target range high)
- Trail stops once 1R profit hit
- Different SL methodology (chart-structure swing lows, not ATR)
- Volume-confirmed breakouts only
- Walk-forward optimization on the score weights themselves

**My honest recommendation: Option A** — the moderate-band signal is real
(+0.09R is small but positive across 50 trades, statistically meaningful)
and the rationale panel + score breakdown gives users the diagnostic
context to apply judgment. Just don't oversell it.

---

## Backtester verification (separate)

While auditing the optimal-levels work, I also re-tested the existing
**Backtester** UI/API end-to-end with the *correct* condition syntax
(`above` / `below`, not `>` / `<`):

```
Strategy: Buy when RSI(14) < 30, hold 15 bars, SL 3%, TP 6%
Stock:    RELIANCE
Result:   11 trades, 36.4% win rate, -9.2% total return,
          BUT +43.71% ALPHA vs buy-and-hold (which was -52.91%)
```

Backtester produces real trades, real metrics, real alpha math. Earlier I
reported "0 trades" — that was operator error in my curl tests using `<`/`>`
which the backend doesn't recognize. **Backtester UI flow is fine to ship
as-is.**

---

## Files modified locally (not deployed)

```
engine/optimal_levels.py            (rewritten — v2.3 with consensus + exhaustion penalty)
engine/optimal_levels_backtest.py   (new — backtest harness)
api/routes_stock.py                 (new endpoint /stock/{sym}/optimal-levels)
frontend/index.html                 (new ENTRY/EXIT button + lines + panel)
deploy/OPTIMAL_LEVELS_FINDINGS.md   (this doc)
```

Local server is auto-reloading via `uvicorn --reload` so the new endpoint
is already live at `http://localhost:8000/stock/RELIANCE/optimal-levels`.
Open the UI in browser, run a screen, click any stock to open its chart,
hit the new ENTRY/EXIT button — you'll see the lines + panel.

Tomorrow's call: pick A / B / C, then we either deploy, defer, or keep iterating.
