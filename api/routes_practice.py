"""
Practice Game API — Candle-by-candle trading simulation.
POST /practice/start   — Start a new round
POST /practice/next    — Reveal next candle
POST /practice/trade   — Execute BUY or SELL
POST /practice/end     — End round and get summary
GET  /practice/stocks   — List available stocks for practice
"""

from fastapi import APIRouter, Header
from pydantic import BaseModel
from typing import Optional

from engine.practice import start_round, next_day, execute_trade, end_round, get_available_stocks

router = APIRouter()

# In-memory game state (single player, local app)
_active_game = {"state": None}


class StartRequest(BaseModel):
    symbol: Optional[str] = None
    universe: str = "nifty500"  # "nifty500" or "next500"
    max_days: int = 60  # 30, 60, or 90
    mode: str = "free"  # "free", "daily", or "replay"
    start_idx: Optional[int] = None  # for replay


class TradeRequest(BaseModel):
    action: str  # "buy" or "sell"
    qty: Optional[int] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    note: Optional[str] = None
    conviction: Optional[int] = None
    side: str = "long"  # "long" or "short"


@router.get("/practice/stocks")
def list_practice_stocks(universe: str = "nifty500"):
    """List stocks available for practice."""
    stocks = get_available_stocks(universe)
    return {"universe": universe, "count": len(stocks), "stocks": stocks[:50]}


@router.post("/practice/start")
def practice_start(req: StartRequest):
    """Start a new practice round."""
    result = start_round(
        symbol=req.symbol,
        universe=req.universe,
        max_days=req.max_days,
        mode=req.mode,
        start_idx_override=req.start_idx,
    )
    if "error" in result:
        return result

    _active_game["state"] = result

    # Return only what the player should see (no future data)
    return {
        "symbol": result["symbol"],
        "difficulty": result.get("difficulty", "Medium"),
        "briefing": result.get("briefing"),
        "mode": result.get("mode", "free"),
        "start_idx": result.get("start_idx"),
        "purse": result["purse"],
        "max_days": result["max_days"],
        "day": 0,
        "total_bars": result["total_bars"],
        "warmup_candles": result["warmup_candles"],
        "warmup_volumes": result["warmup_volumes"],
        "indicators": result["indicators"],
    }


@router.post("/practice/next")
def practice_next():
    """Reveal next candle."""
    if not _active_game["state"]:
        return {"error": "No active game. Start a new round first."}

    result = next_day(_active_game["state"])
    return result


@router.post("/practice/trade")
def practice_trade(req: TradeRequest):
    """Execute a trade (buy or sell)."""
    if not _active_game["state"]:
        return {"error": "No active game. Start a new round first."}

    result = execute_trade(
        _active_game["state"],
        req.action,
        qty=req.qty,
        sl=req.sl,
        tp=req.tp,
        note=req.note,
        conviction=req.conviction,
        side=req.side,
    )
    return result


@router.post("/practice/end")
def practice_end(authorization: Optional[str] = Header(None)):
    """End the round and get summary with mistake analysis.

    If the caller is signed in, the finished round is also persisted to
    `practice_sessions` (used by personal history + leaderboard). The
    session is recorded as `public=0` by default — the user opts in
    later via /leaderboard/session/{id}/public, so nothing leaks
    automatically.
    """
    if not _active_game["state"]:
        return {"error": "No active game."}

    state = _active_game["state"]
    result = end_round(state)
    _active_game["state"] = None

    # Best-effort persistence — never break the response if logging fails
    try:
        from fastapi import Request  # noqa
        # Pull authorization from FastAPI's Header injection helper
    except Exception:
        pass
    try:
        from engine.leaderboard import record_session
        from engine.auth import verify_token
        from engine.db import get_conn
        user_id = None
        if authorization:
            tok = authorization[7:] if authorization.startswith("Bearer ") else authorization
            try:
                payload = verify_token(tok)
                with get_conn() as conn:
                    row = conn.execute(
                        "SELECT id FROM users WHERE username = ? COLLATE NOCASE",
                        (payload.get("username", ""),),
                    ).fetchone()
                if row:
                    user_id = row["id"]
            except Exception:
                user_id = None
        record_session(
            user_id=user_id,
            symbol=state.get("symbol", ""),
            summary=result,
            trades=state.get("trades", []),
            max_days=state.get("max_days", 60),
            mode=state.get("mode", "free"),
            public=False,
        )
    except Exception as e:
        # Logged sessions are nice-to-have; never block the response.
        print(f"[practice/end] record_session failed: {e}", flush=True)
    return result
