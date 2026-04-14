"""
POST /auth/register  — Create new account
POST /auth/login     — Login, get JWT token
GET  /auth/me        — Verify token, get user info
POST /auth/logout    — Client-side logout (invalidate on frontend)
"""

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import Optional

from engine.auth import register, login, verify_token, get_user

router = APIRouter()


class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = ""


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/auth/register")
def register_user(request: RegisterRequest):
    """Create a new user account."""
    try:
        user = register(request.username, request.password, request.display_name)
        # Auto-login after registration
        token_data = login(request.username, request.password)
        return {**token_data, "status": "registered"}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/auth/login")
def login_user(request: LoginRequest):
    """Authenticate and return JWT token."""
    try:
        return login(request.username, request.password)
    except ValueError as e:
        raise HTTPException(401, str(e))


@router.get("/auth/me")
def get_current_user(authorization: Optional[str] = Header(None)):
    """Verify token and return current user info."""
    if not authorization:
        raise HTTPException(401, "No authorization header")

    # Support "Bearer <token>" format
    token = authorization
    if token.startswith("Bearer "):
        token = token[7:]

    try:
        user = verify_token(token)
        return user
    except ValueError as e:
        raise HTTPException(401, str(e))


@router.post("/auth/logout")
def logout_user():
    """Logout is client-side (discard token). This endpoint is a no-op confirmation."""
    return {"status": "logged_out", "message": "Token discarded. Clear it from localStorage."}
