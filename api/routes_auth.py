"""
POST /auth/register         — Create new account
POST /auth/login            — Login, get JWT token
GET  /auth/me               — Verify token, get full user info (incl. created/password_changed)
POST /auth/change-password  — Change current user's password (requires current_password)
POST /auth/update-profile   — Update current user's display_name
POST /auth/logout           — Client-side logout (invalidate on frontend)
"""

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import Optional

from engine.auth import (
    register, login, verify_token, get_user,
    change_password, update_display_name,
)

router = APIRouter()


class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = ""


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class UpdateProfileRequest(BaseModel):
    display_name: str


def _require_auth(authorization: Optional[str]) -> dict:
    """Validate auth header, return JWT payload (username, display_name)."""
    if not authorization:
        raise HTTPException(401, "No authorization header")
    token = authorization
    if token.startswith("Bearer "):
        token = token[7:]
    try:
        return verify_token(token)
    except ValueError as e:
        raise HTTPException(401, str(e))


@router.post("/auth/register")
def register_user(request: RegisterRequest):
    """Create a new user account."""
    try:
        user = register(request.username, request.password, request.display_name)
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
    """Verify token and return full user info (display_name, created, password_changed)."""
    payload = _require_auth(authorization)
    full = get_user(payload["username"])
    if full is None:
        # Token valid but user record gone — treat as logged out
        raise HTTPException(401, "User no longer exists")
    return full


@router.post("/auth/change-password")
def change_user_password(request: ChangePasswordRequest, authorization: Optional[str] = Header(None)):
    """Change the authenticated user's password. Requires current password."""
    payload = _require_auth(authorization)
    try:
        change_password(payload["username"], request.current_password, request.new_password)
        return {"status": "ok", "message": "Password changed successfully"}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/auth/update-profile")
def update_user_profile(request: UpdateProfileRequest, authorization: Optional[str] = Header(None)):
    """Update the authenticated user's display name."""
    payload = _require_auth(authorization)
    try:
        return update_display_name(payload["username"], request.display_name)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/auth/logout")
def logout_user():
    """Logout is client-side (discard token). This endpoint is a no-op confirmation."""
    return {"status": "logged_out", "message": "Token discarded. Clear it from localStorage."}
