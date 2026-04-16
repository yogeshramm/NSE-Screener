# Practice Game Feature Spec

## Status: ALL BATCHES COMPLETE (backend + frontend)

## Safety: Tag `v1.0-pre-practice` preserves pre-game state

## What's Done (Batch 1)
- `engine/practice.py` — game engine (start_round, next_day, execute_trade, end_round, mistake analysis)
- `api/routes_practice.py` — 5 API endpoints (start, next, trade, end, stocks)
- `api/app.py` — routes registered
- Purse: 1,00,000. Max 60 days. Random stock + random start date.

## Completed Batches

### Batch 2: Frontend Practice tab + basic UI ✓
- "Practice" tab added to nav (after Watchlist)
- `<section id="tab-practice">` with welcome screen + game layout
- Top bar: universe toggle (Nifty 500 / Next 500) + "NEW ROUND" button + Day counter + Purse
- Center: chart area (lightweight-charts, same style as Screener)
- Bottom: action buttons (NEXT DAY, BUY, SELL, END ROUND) + position tracker

### Batch 3: Candle-by-candle chart ✓
- On start: renders 60 warmup candles + SMA 20, Bollinger Bands, Supertrend, Volume
- "NEXT DAY": POST /practice/next → appends candle, recomputes all indicators client-side
- RSI sub-panel with 70/30 reference lines, synced time scale
- OHLC overlay updates per candle

### Batch 4: BUY/SELL + position tracker + purse ✓
- BUY: green arrow marker on chart, position card shows entry/qty/P&L/holding days
- SELL: red arrow marker with P&L text
- Purse display: remaining cash + position value, updates each candle
- Day counter: "Day N/60", auto-exit warning at day 55

### Batch 5: Mistake analysis ✓
- Backend `_analyze_mistakes()` checks RSI, SMA 20, declining pattern, volume
- Frontend displays in summary modal with green (good) / red (loss) cards

### Batch 6: Round summary modal ✓
- Stats grid: Total P&L, Win Rate, Final Purse, Avg Hold
- Best/Worst trade highlight cards
- Trade Analysis section with per-trade indicator feedback
- Close + Play Again buttons

### Batch 7: Profile + history ✓
- Session history stored in localStorage (last 50 sessions)
- Cumulative stats: total sessions, avg P&L, avg win rate
- History list with date, symbol, trades, P&L per session
- Displayed on welcome screen below Start Round button

## Value-Adds
- Trade markers on chart (green ▲ buy, red ▼ sell)
- Running P&L line
- Difficulty indicator based on stock volatility
- Auto-exit warning at day 55
