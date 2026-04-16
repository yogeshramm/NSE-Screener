"""Per-stock news feed (RSS only)."""
from fastapi import APIRouter
from data.stock_news import get_news

router = APIRouter()


@router.get("/news/{symbol}")
def stock_news(symbol: str, limit: int = 5):
    items = get_news(symbol, limit=limit)
    return {"symbol": symbol.upper(), "count": len(items), "items": items}
