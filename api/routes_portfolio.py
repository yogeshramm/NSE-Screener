"""Portfolio tracker endpoints."""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from engine.portfolio import list_positions, add_position, delete_position, close_position, update_position

router = APIRouter()


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
def portfolio():
    return list_positions()


@router.post("/portfolio/add")
def portfolio_add(req: AddReq):
    return add_position(
        req.symbol, req.qty, req.buy_price, req.buy_date, req.notes,
        stop_loss=req.stop_loss, target=req.target,
    )


@router.post("/portfolio/{pos_id}/close")
def portfolio_close(pos_id: str, req: CloseReq):
    return close_position(pos_id, req.sell_price, req.sell_date)


@router.patch("/portfolio/{pos_id}")
def portfolio_update(pos_id: str, req: UpdateReq):
    kwargs = {k: v for k, v in req.dict().items() if v is not None}
    return update_position(pos_id, **kwargs)


@router.delete("/portfolio/{pos_id}")
def portfolio_delete(pos_id: str):
    return delete_position(pos_id)
