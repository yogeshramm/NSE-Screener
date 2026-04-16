"""
NSE Screener — FastAPI Application
Main entry point for the backend API server.
"""

from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

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

app = FastAPI(
    title="NSE Screener API",
    description="Professional NSE stock screener with 25 technical indicators, "
                "2-stage screening, and 100-point scoring system.",
    version="1.0.0",
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


# Serve frontend
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


@app.get("/", tags=["Frontend"])
def serve_frontend():
    """Serve the screener frontend."""
    return FileResponse(FRONTEND_DIR / "index.html")


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
