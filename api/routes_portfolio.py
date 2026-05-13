"""Portfolio tracker endpoints."""
from fastapi import APIRouter, Header
from pydantic import BaseModel
from typing import Optional
from engine.portfolio import list_positions, add_position, delete_position, close_position, update_position

router = APIRouter()


def _username(authorization: Optional[str]) -> Optional[str]:
    """Extract username from Bearer token; return None if absent or invalid."""
    if not authorization:
        return None
    tok = authorization[7:] if authorization.startswith("Bearer ") else authorization
    try:
        from engine.auth import verify_token
        payload = verify_token(tok)
        return payload.get("username") or payload.get("sub") or None
    except Exception:
        return None


class AddReq(BaseModel):
    symbol: str
    qty: float
    buy_price: float
    buy_date: str = ""
    notes: str = ""
    stop_loss: Optional[float] = None
    target: Optional[float] = None


class CloseReq(BaseModel):
    sell_price: float
    sell_date: str = ""


class UpdateReq(BaseModel):
    notes: Optional[str] = None
    stop_loss: Optional[float] = None
    target: Optional[float] = None
    qty: Optional[float] = None
    buy_price: Optional[float] = None
    buy_date: Optional[str] = None


@router.get("/portfolio")
def portfolio(authorization: Optional[str] = Header(None)):
    return list_positions(_username(authorization))


@router.post("/portfolio/add")
def portfolio_add(req: AddReq, authorization: Optional[str] = Header(None)):
    u = _username(authorization)
    return add_position(
        req.symbol, req.qty, req.buy_price, req.buy_date, req.notes,
        stop_loss=req.stop_loss, target=req.target, username=u,
    )


@router.post("/portfolio/{pos_id}/close")
def portfolio_close(pos_id: str, req: CloseReq, authorization: Optional[str] = Header(None)):
    return close_position(pos_id, req.sell_price, req.sell_date, _username(authorization))


@router.patch("/portfolio/{pos_id}")
def portfolio_update(pos_id: str, req: UpdateReq, authorization: Optional[str] = Header(None)):
    kwargs = {k: v for k, v in req.dict().items() if v is not None}
    return update_position(pos_id, username=_username(authorization), **kwargs)


@router.delete("/portfolio/{pos_id}")
def portfolio_delete(pos_id: str, authorization: Optional[str] = Header(None)):
    return delete_position(pos_id, _username(authorization))
