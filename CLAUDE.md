# YOINTELL — NSE Stock Intelligence Platform

## Quick Start
```bash
python3 run_server.py  # Starts uvicorn on port 8000
open http://localhost:8000
```

## Project Structure
```
NSE-Screener/
├── api/               # FastAPI routes (33 endpoints)
│   ├── app.py         # Main app, CORS, router registration
│   ├── data_helper.py # Cached data fetching
│   ├── routes_screen.py    # POST /screen
│   ├── routes_stock.py     # GET /stock/{sym}, /stock/{sym}/insights
│   ├── routes_chart.py     # GET /chart/{sym}
│   ├── routes_indicators.py # GET/POST indicators
│   ├── routes_presets.py   # CRUD /presets/*
│   ├── routes_config.py    # GET /config/default
│   ├── routes_data.py      # /data/status, /data/catchup, /data/setup
│   ├── routes_watchlist.py # 6 watchlist endpoints
│   ├── routes_chat.py      # POST /chat
│   └── routes_auth.py      # 4 auth endpoints (JWT+bcrypt)
├── engine/            # Core logic
│   ├── default_config.py   # 44 filters, 86 params
│   ├── screener.py         # 2-stage screening pipeline
│   ├── scorer.py           # 100-point scoring (40/30/20/10)
│   ├── fundamental_checker.py
│   ├── late_entry.py
│   ├── inspector.py
│   ├── insights.py         # AI insights (rule-based)
│   ├── presets.py
│   ├── watchlist.py
│   ├── chat_parser.py      # NLU for chat agent
│   └── auth.py             # JWT auth, bcrypt, file-based users
├── indicators/        # 25 indicators + registry
├── data/              # Data fetchers (NSE, screener.in, yfinance)
├── frontend/
│   └── index.html     # Single-page app (1182 lines, Stitch design)
├── config/            # presets/, watchlist.json, users.json
├── data_store/        # Downloaded data (history/, fundamentals/)
├── setup_data.py      # One-time historical data setup
├── daily_download.py  # Daily update script
└── run_server.py      # uvicorn entry point (port 8000)
```

## Architecture
- **Backend**: FastAPI (Python), 33 REST endpoints
- **Frontend**: Single HTML file with Tailwind CSS, lightweight-charts
- **Data**: NSE Bhavcopy archives + screener.in fundamentals
- **Auth**: JWT tokens + bcrypt passwords, stored in config/users.json
- **Design**: YOINTELL brand, #0a0e1a background, #6effc0 primary

## Key Design Decisions
- Single-page app with 4 tabs: Screener, Configuration, Indicators, Watchlist
- Top navigation only (no side nav)
- Auth uses username (not email), Indian market branding
- 44 filters grouped: Technical (19), Fundamental (11), Breakout & Risk (14)
- 25 indicators with precision tiers (Most Precise, Hidden Gem, Standard)
- 3 highlighted indicators: Supertrend, VWAP Bands, Vortex
- Stage 1 table: #, Stock+sector, Price, PE, RSI, ROE%, Score, Status, Bookmark
- Stage 2 table: #, Stock, Price, SL(red), Target(green), R:R, Score, Status, Bookmark
- Kite-style candlestick chart using lightweight-charts library
- Floating chat agent wired to POST /chat
- Data sync with progress ring + auto-catchup

## Conventions
- All API endpoints return JSON
- Config uses snake_case keys with `enabled` boolean + params
- Presets stored as JSON in config/presets/
- Stock data in data_store/history/{SYMBOL}.pkl
- Fundamentals in data_store/fundamentals/{SYMBOL}.pkl

## GitHub
- Remote: git@github.com:yogeshramm/NSE-Screener.git (SSH)
- Branch: main
