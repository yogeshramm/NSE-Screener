"""
POST /chat — Process a natural language chat message and return response + actions.
"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from engine.chat_parser import process_message

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    config: Optional[dict] = None  # Current filter config from frontend


@router.post("/chat")
def chat(request: ChatRequest):
    """Process a chat message and return response with frontend actions."""
    result = process_message(request.message, current_config=request.config)
    return result
