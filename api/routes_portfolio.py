"""Portfolio tracker endpoints."""
from fastapi import APIRouter
from pydantic import BaseModel
from engine.portfolio import list_positions, add_position, delete_position

router = APIRouter()


class AddReq(BaseModel):
    symbol: str
    qty: float
    buy_price: float
    buy_date: str = ""
    notes: str = ""


@router.get("/portfolio")
def portfolio():
    return list_positions()


@router.post("/portfolio/add")
def portfolio_add(req: AddReq):
    return add_position(req.symbol, req.qty, req.buy_price, req.buy_date, req.notes)


@router.delete("/portfolio/{pos_id}")
def portfolio_delete(pos_id: str):
    return delete_position(pos_id)
