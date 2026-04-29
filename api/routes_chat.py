"""
POST /chat — Natural language chat agent powered by Groq (Llama 3.1 8B).
Falls back to rule-based parser if Groq key is missing.
"""

import os
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
import httpx

from engine.chat_parser import process_message

router = APIRouter()

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = """You are YOINTELL Assistant — an AI for an Indian NSE swing-trading screener (moneystx.com).

You help users with:
- Technical analysis (RSI, MACD, EMA, Supertrend, Bollinger Bands, VWAP, Ichimoku, ADX, OBV, ATR, Vortex, Stochastic RSI, Williams %R, Awesome Oscillator, CMF, ROC)
- Fundamental analysis (ROE, ROCE, Debt/Equity, EPS, Free Cash Flow, PE Ratio, Institutional Holdings)
- Indian market context (NSE, BSE, Nifty, Sensex, F&O, Bhavcopy, circuit limits, T+1 settlement)
- Swing trading strategies, breakout setups, entry/exit logic, risk management
- Explaining screener results and filter settings

Rules:
- Keep responses concise: 2-4 sentences max unless a detailed explanation is clearly needed
- Always use Indian market context (₹, NSE, Nifty, etc.)
- If asked to run a screen, say the user should use the Run button with the appropriate filters
- Never give direct buy/sell recommendations — frame as analysis only
- Be direct and practical, not verbose"""


class ChatRequest(BaseModel):
    message: str
    config: Optional[dict] = None
    mode: Optional[str] = "auto"


def _groq_key() -> str | None:
    key = os.environ.get("GROQ_API_KEY")
    if key:
        return key
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    try:
        for line in open(env_path):
            if line.startswith("GROQ_API_KEY="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return None


@router.post("/chat")
def chat(request: ChatRequest):
    key = _groq_key()
    # Auto mode: use Groq if key available, else rule-based
    if key and request.mode != "simple":
        return _groq_chat(request.message, key)
    return process_message(request.message, current_config=request.config)


@router.get("/chat/status")
def chat_status():
    key = _groq_key()
    return {"groq": bool(key), "model": GROQ_MODEL if key else None, "ready": bool(key)}


def _groq_chat(message: str, key: str) -> dict:
    try:
        r = httpx.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": GROQ_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": message},
                ],
                "max_tokens": 300,
                "temperature": 0.4,
            },
            timeout=15.0,
        )
        if r.status_code == 200:
            reply = r.json()["choices"][0]["message"]["content"].strip()
            return {"reply": reply, "actions": [], "model": GROQ_MODEL}
        return {"reply": f"Groq error {r.status_code}: {r.text[:200]}", "actions": []}
    except httpx.ReadTimeout:
        return {"reply": "AI is taking too long — try again.", "actions": []}
    except Exception as e:
        return {"reply": f"Error: {str(e)}", "actions": []}
