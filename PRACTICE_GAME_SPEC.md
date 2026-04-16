# Practice Game Feature Spec

## Status: Batch 1 DONE (backend), Batches 2-7 TODO (frontend)

## Safety: Tag `v1.0-pre-practice` preserves pre-game state

## What's Done (Batch 1)
- `engine/practice.py` — game engine (start_round, next_day, execute_trade, end_round, mistake analysis)
- `api/routes_practice.py` — 5 API endpoints (start, next, trade, end, stocks)
- `api/app.py` — routes registered
- Purse: 1,00,000. Max 60 days. Random stock + random start date.

## Remaining Batches

### Batch 2: Frontend Practice tab + basic UI
- Add "Practice" to nav tabs (after Watchlist)
- New `<section id="tab-practice">` with layout:
  - Top: universe toggle (Nifty 500 / Next 500) + "NEW ROUND" button
  - Center: chart area (reuse lightweight-charts, same style as Screener)
  - Bottom: action buttons (NEXT DAY, BUY, SELL) + position tracker
- Wire to POST /practice/start

### Batch 3: Candle-by-candle chart
- On start: render warmup candles (60 bars) + indicators
- "NEXT DAY" button: POST /practice/next → append candle to chart
- Indicators (RSI, Supertrend, BB, SMA, Volume) update with each new candle
- All indicators available via dropdown (same as Screener chart)
- OHLC overlay updates per candle

### Batch 4: BUY/SELL + position tracker + purse
- BUY button: POST /practice/trade {action:"buy"} → show entry on chart (green marker)
- SELL button: POST /practice/trade {action:"sell"} → show exit on chart (red marker)
- Position card: entry price, qty, current P&L (updates each candle), holding days
- Purse display: remaining cash, position value
- Day counter: "Day 15/60"

### Batch 5: Mistake analysis (backend already done)
- `_analyze_mistakes()` in engine/practice.py checks at each trade:
  - RSI overbought/oversold at entry
  - Price vs SMA 20 position
  - Declining candle pattern
  - Volume below average
  - Falls back to "Probable external event factor" if no indicator explains

### Batch 6: Round summary card
- POST /practice/end → display summary:
  - Total P&L (₹ and %), win rate, avg holding, best/worst trade
  - Mistake analysis for each losing trade
  - Winning trade confirmations
- Show as overlay/modal after round ends

### Batch 7: Profile + history
- Nickname input (localStorage)
- Session log stored in localStorage: [{date, stock, trades, pnl, score}]
- Cumulative stats table: total sessions, avg P&L, win rate
- "History" section below game with expandable trade details

## Value-Adds
- Trade markers on chart (green ▲ buy, red ▼ sell)
- Running P&L line
- Difficulty indicator based on stock volatility
- Auto-exit warning at day 55
