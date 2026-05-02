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


def _warm_status_cache():
    """Compute /data/status response once on startup so the first user
    request doesn't pay 10-25s of pkl-iteration cost (causes Cloudflare 502)."""
    try:
        from api.routes_data import warm_status_cache_on_startup
        warm_status_cache_on_startup()
    except Exception:
        pass


def _warm_os_file_cache():
    """Read every history + fundamentals pkl into OS page cache.
    On a cold-start (post-deploy or post-reboot), the FIRST /screen request
    has to physically read 500+ pkl files from disk — ~30s, right at
    Cloudflare's 30s edge timeout → users see 502. Pre-loading the bytes
    here (no pickle parsing, just os.read) populates the kernel page cache;
    subsequent reads are sub-millisecond.

    Runs in a daemon thread on startup. ~3s for 500 Nifty + 500 fundamentals
    on a 2GB droplet, vs ~30s if first user pays the cost."""
    import time
    time.sleep(2)  # let uvicorn finish binding
    try:
        from data.nse_symbols import get_nifty500_live, NIFTY_500_FALLBACK
        try:
            syms = list(get_nifty500_live())
        except Exception:
            syms = list(NIFTY_500_FALLBACK)
        from setup_data import HISTORY_DIR, FUNDAMENTALS_DIR
        for d in (HISTORY_DIR, FUNDAMENTALS_DIR):
            for sym in syms:
                p = d / f"{sym}.pkl"
                if p.exists():
                    try:
                        with open(p, "rb") as f:
                            f.read()  # load into OS page cache; no parsing
                    except Exception:
                        pass
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure the site owner has admin privileges on every startup
    from engine.auth import ensure_admin
    ensure_admin("yogesh")
    # Launch prewarm in background — won't block startup
    t = threading.Thread(target=_background_prewarm, daemon=True)
    t.start()
    # Pre-populate /data/status cache so first request returns instantly.
    threading.Thread(target=_warm_status_cache, daemon=True).start()
    # Pre-load history + fundamental pkls into OS page cache so the first
    # /screen scan after restart doesn't hit 30s cold-disk read penalty.
    threading.Thread(target=_warm_os_file_cache, daemon=True).start()
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
    """Serve the v2 redesigned frontend."""
    return FileResponse(
        FRONTEND_DIR / "index_v2.html",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@app.get("/v2", tags=["Frontend"])
def serve_frontend_v2():
    """v2 alias — same file as /."""
    return FileResponse(
        FRONTEND_DIR / "index_v2.html",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@app.get("/classic", tags=["Frontend"])
def serve_frontend_classic():
    """Serve the original frontend as a fallback."""
    return FileResponse(
        FRONTEND_DIR / "index.html",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@app.get("/v2", tags=["Frontend"])
def serve_frontend_v2():
    """Serve the v2 redesigned frontend for preview/testing."""
    return FileResponse(
        FRONTEND_DIR / "index_v2.html",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


# Browsers always probe for /favicon.ico, /apple-touch-icon.png etc. Inline-SVG
# favicon in the HTML covers modern browsers; these 204 stubs silence the
# legacy probes (which were spamming the access log with 404s).
from fastapi.responses import Response, JSONResponse

@app.get("/favicon.ico", include_in_schema=False)
@app.get("/favicon.png", include_in_schema=False)
def _favicon_stub():
    return Response(status_code=204)


# ── Android TWA — Digital Asset Links ─────────────────────────────────────────
# Required for Chrome to verify the TWA and hide the URL bar.
# The sha256_cert_fingerprints list must match the APK signing certificate.
# After the first GitHub Actions build, run:
#   keytool -printcert -jarfile app-debug.apk
# and paste the SHA-256 here, then redeploy.
#
# NOTE: Even WITHOUT a matching fingerprint the app works — it just shows a
#       URL bar.  Add the fingerprint later to get full-screen experience.
_ASSET_LINKS_FINGERPRINTS: list[str] = [
    # Placeholder — replace with actual SHA-256 after first APK build.
    # Format: "AA:BB:CC:DD:EE:..."  (colon-separated uppercase hex)
    "00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00"
]

@app.get("/.well-known/assetlinks.json", include_in_schema=False)
def asset_links():
    """Digital Asset Links — lets Chrome verify the TWA and remove the URL bar."""
    return JSONResponse(
        [
            {
                "relation": ["delegate_permission/common.handle_all_urls"],
                "target": {
                    "namespace": "android_app",
                    "package_name": "com.moneystx.app",
                    "sha256_cert_fingerprints": _ASSET_LINKS_FINGERPRINTS,
                },
            }
        ],
        headers={"Cache-Control": "public, max-age=3600"},
    )

# ── PWA support ────────────────────────────────────────────────────────────────

@app.get("/manifest.json", include_in_schema=False)
def pwa_manifest():
    """Web App Manifest — enables 'Add to Home Screen' on Android & iOS."""
    return JSONResponse({
        "name": "MONEYSTX",
        "short_name": "MX",
        "description": "NSE institutional intelligence terminal — 25 indicators, 2-stage screener, real-time charts.",
        "start_url": "/",
        "display": "standalone",
        "orientation": "any",
        "background_color": "#050505",
        "theme_color": "#FF8C00",
        "icons": [
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        ],
        "categories": ["finance"],
        "lang": "en-IN",
        "dir": "ltr",
    }, headers={"Cache-Control": "public, max-age=86400"})

@app.get("/icon-192.png", include_in_schema=False)
def pwa_icon_192():
    return FileResponse(FRONTEND_DIR / "icon-192.png",
                        media_type="image/png",
                        headers={"Cache-Control": "public, max-age=604800"})

@app.get("/icon-512.png", include_in_schema=False)
def pwa_icon_512():
    return FileResponse(FRONTEND_DIR / "icon-512.png",
                        media_type="image/png",
                        headers={"Cache-Control": "public, max-age=604800"})

@app.get("/apple-touch-icon.png", include_in_schema=False)
@app.get("/apple-touch-icon-precomposed.png", include_in_schema=False)
def apple_touch_icon():
    """iOS uses apple-touch-icon for Add to Home Screen."""
    return FileResponse(FRONTEND_DIR / "icon-192.png",
                        media_type="image/png",
                        headers={"Cache-Control": "public, max-age=604800"})


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
