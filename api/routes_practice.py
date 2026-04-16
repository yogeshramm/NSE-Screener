"""
Practice Game API — Candle-by-candle trading simulation.
POST /practice/start   — Start a new round
POST /practice/next    — Reveal next candle
POST /practice/trade   — Execute BUY or SELL
POST /practice/end     — End round and get summary
GET  /practice/stocks   — List available stocks for practice
"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from engine.practice import start_round, next_day, execute_trade, end_round, get_available_stocks

router = APIRouter()

# In-memory game state (single player, local app)
_active_game = {"state": None}


class StartRequest(BaseModel):
    symbol: Optional[str] = None
    universe: str = "nifty500"  # "nifty500" or "next500"


class TradeRequest(BaseModel):
    action: str  # "buy" or "sell"


@router.get("/practice/stocks")
def list_practice_stocks(universe: str = "nifty500"):
    """List stocks available for practice."""
    stocks = get_available_stocks(universe)
    return {"universe": universe, "count": len(stocks), "stocks": stocks[:50]}


@router.post("/practice/start")
def practice_start(req: StartRequest):
    """Start a new practice round."""
    result = start_round(symbol=req.symbol, universe=req.universe)
    if "error" in result:
        return result

    _active_game["state"] = result

    # Return only what the player should see (no future data)
    return {
        "symbol": result["symbol"],
        "difficulty": result.get("difficulty", "Medium"),
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

    result = execute_trade(_active_game["state"], req.action)
    return result


@router.post("/practice/end")
def practice_end():
    """End the round and get summary with mistake analysis."""
    if not _active_game["state"]:
        return {"error": "No active game."}

    result = end_round(_active_game["state"])
    _active_game["state"] = None
    return result
