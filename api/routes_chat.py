"""
POST /chat — Process a natural language chat message and return response + actions.
Supports two modes: 'simple' (rule-based parser) and 'ollama' (local LLM).
"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
import httpx
import json

from engine.chat_parser import process_message

router = APIRouter()

OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "llama3.2"

SYSTEM_PROMPT = """You are YOINTELL Assistant, an AI for an Indian stock screening platform (NSE/BSE).
You help users understand technical indicators, screening strategies, and stock analysis.

Available indicators: RSI, MACD, EMA, Supertrend, Bollinger Bands, VWAP, Ichimoku, ADX, OBV, CMF, ATR, ROC, Vortex, Stochastic RSI, Williams %R, Awesome Oscillator, Fisher Transform, Klinger, Chande Momentum, Force Index.

Available fundamentals: ROE, ROCE, Debt/Equity, EPS, Free Cash Flow, PE Ratio, Institutional Holdings, Analyst Ratings.

Keep responses concise (2-4 sentences). Focus on Indian market context. Use simple language.
If asked to screen stocks or change filters, explain what settings would help but note that the user should use the screener filters directly."""


class ChatRequest(BaseModel):
    message: str
    config: Optional[dict] = None
    mode: Optional[str] = "simple"  # "simple" or "ollama"


@router.post("/chat")
def chat(request: ChatRequest):
    """Process a chat message. Mode: 'simple' = rule-based, 'ollama' = local LLM."""

    if request.mode == "ollama":
        return _ollama_chat(request.message)

    # Default: rule-based parser
    result = process_message(request.message, current_config=request.config)
    return result


@router.get("/chat/status")
def chat_status():
    """Check if Ollama is available."""
    try:
        r = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
        if r.status_code == 200:
            models = [m["name"] for m in r.json().get("models", [])]
            has_model = any(OLLAMA_MODEL in m for m in models)
            return {"ollama": True, "models": models, "ready": has_model}
    except Exception:
        pass
    return {"ollama": False, "models": [], "ready": False}


def _ollama_chat(message: str) -> dict:
    """Send message to Ollama and return response."""
    try:
        r = httpx.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": message},
                ],
                "stream": False,
            },
            timeout=120.0,
        )
        if r.status_code == 200:
            data = r.json()
            reply = data.get("message", {}).get("content", "No response from AI.")
            return {"reply": reply, "actions": []}
        return {"reply": f"Ollama error: {r.status_code}", "actions": []}
    except httpx.ConnectError:
        return {"reply": "Ollama is not running. Start it or switch to Simple mode.", "actions": []}
    except httpx.ReadTimeout:
        return {"reply": "AI is thinking... try again in a moment.", "actions": []}
    except Exception as e:
        return {"reply": f"Error: {str(e)}", "actions": []}
