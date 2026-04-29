"""
NSE Screener — FastAPI Application
Main entry point for the backend API server.
"""

import threading, subprocess, sys, time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse


def _background_prewarm():
    """Run after startup to warm indicator cache via warm_scope.py.
    Uses direct warm_cache() — no HTTP calls, never blocks uvicorn workers.
    Waits 45s so uvicorn finishes binding before starting."""
    time.sleep(45)
    script = Path(__file__).parent.parent / "deploy" / "warm_scope.py"
    try:
        subprocess.run([sys.executable, str(script), "nifty500"], timeout=600, check=False)
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Launch prewarm in background — won't block startup
    t = threading.Thread(target=_background_prewarm, daemon=True)
    t.start()
    yield

from api.routes_screen import router as screen_router
from api.routes_stock import router as stock_router
from api.routes_indicators import router as indicators_router
from api.routes_presets import router as presets_router
from api.routes_config import router as config_router
from api.routes_data import router as data_router
from api.routes_chart import router as chart_router
from api.routes_watchlist import router as watchlist_router
from api.routes_chat import router as chat_router
from api.routes_auth import router as auth_router
from api.routes_practice import router as practice_router
from api.routes_patterns import router as patterns_router
from api.routes_breakouts import router as breakouts_router
from api.routes_chart_patterns import router as chart_patterns_router
from api.routes_market import router as market_router
from api.routes_backtest import router as backtest_router
from api.routes_events import router as events_router
from api.routes_briefing import router as briefing_router
from api.routes_institutional import router as institutional_router
from api.routes_news import router as news_router
from api.routes_factor import router as factor_router
from api.routes_insights_pro import router as insights_pro_router
from api.routes_mtf import router as mtf_router
from api.routes_portfolio import router as portfolio_router
from api.routes_analyst import router as analyst_router
from api.routes_ticks import router as ticks_router

app = FastAPI(
    title="NSE Screener API",
    description="Professional NSE stock screener with 25 technical indicators, "
                "2-stage screening, and 100-point scoring system.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow Google Stitch frontend and local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register route modules
app.include_router(screen_router, tags=["Screening"])
app.include_router(stock_router, tags=["Stock Inspector"])
app.include_router(indicators_router, tags=["Indicators"])
app.include_router(presets_router, tags=["Presets"])
app.include_router(config_router, tags=["Configuration"])
app.include_router(data_router, tags=["Data Management"])
app.include_router(chart_router, tags=["Chart"])
app.include_router(watchlist_router, tags=["Watchlist"])
app.include_router(chat_router, tags=["Chat Agent"])
app.include_router(auth_router, tags=["Authentication"])
app.include_router(practice_router, tags=["Practice Game"])
app.include_router(patterns_router, tags=["Patterns"])
app.include_router(breakouts_router, tags=["Breakouts"])
app.include_router(chart_patterns_router, tags=["Chart Patterns"])
app.include_router(market_router, tags=["Market Analytics"])
app.include_router(backtest_router, tags=["Backtester"])
app.include_router(events_router, tags=["Events"])
app.include_router(briefing_router, tags=["Briefing"])
app.include_router(institutional_router, tags=["Institutional Radar"])
app.include_router(news_router, tags=["News"])
app.include_router(factor_router, tags=["Multi-Factor Score"])
app.include_router(insights_pro_router, tags=["Insights Pro"])
app.include_router(mtf_router, tags=["Multi-Timeframe Confluence"])
app.include_router(portfolio_router, tags=["Portfolio"])
app.include_router(analyst_router, tags=["Analyst Signal"])
app.include_router(ticks_router, tags=["Live Prices"])


# Serve frontend
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


@app.get("/", tags=["Frontend"])
def serve_frontend():
    """Serve the screener frontend.
    Cache-Control: no-cache (+ ETag) forces the browser to revalidate on every
    load, so a fresh index.html is picked up immediately after a push
    (previously users saw stale/misaligned versions for days until the
    browser naturally expired its cache)."""
    return FileResponse(
        FRONTEND_DIR / "index.html",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


# Browsers always probe for /favicon.ico, /apple-touch-icon.png etc. Inline-SVG
# favicon in the HTML covers modern browsers; these 204 stubs silence the
# legacy probes (which were spamming the access log with 404s).
from fastapi.responses import Response

@app.get("/favicon.ico", include_in_schema=False)
@app.get("/favicon.png", include_in_schema=False)
@app.get("/apple-touch-icon.png", include_in_schema=False)
@app.get("/apple-touch-icon-precomposed.png", include_in_schema=False)
def _favicon_stub():
    return Response(status_code=204)


@app.get("/health", tags=["Health"])
def health_check():
    """Health check endpoint."""
    from indicators.registry import get_all_indicators
    return {
        "status": "ok",
        "service": "NSE Screener API",
        "version": "1.0.0",
        "total_indicators": len(get_all_indicators()),
    }
