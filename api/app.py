"""
NSE Screener — FastAPI Application
Main entry point for the backend API server.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes_screen import router as screen_router
from api.routes_stock import router as stock_router
from api.routes_indicators import router as indicators_router
from api.routes_presets import router as presets_router
from api.routes_config import router as config_router

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


@app.get("/", tags=["Health"])
def health_check():
    """Health check endpoint."""
    from indicators.registry import get_all_indicators
    return {
        "status": "ok",
        "service": "NSE Screener API",
        "version": "1.0.0",
        "total_indicators": len(get_all_indicators()),
    }
