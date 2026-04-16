"""Backtester API."""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, Dict, Any
from engine.backtester import run_backtest

router = APIRouter()


class Rule(BaseModel):
    indicator: str
    condition: str
    value: float


class BacktestReq(BaseModel):
    symbol: str
    entry: Rule
    exit: Optional[Rule] = None
    sl_pct: Optional[float] = None
    tp_pct: Optional[float] = None
    hold_bars: int = 20
    start_date: Optional[str] = None
    end_date: Optional[str] = None


@router.post("/backtest/run")
def backtest_run(req: BacktestReq):
    return run_backtest(
        symbol=req.symbol.upper(),
        entry_rule=req.entry.model_dump(),
        exit_rule=req.exit.model_dump() if req.exit else None,
        sl_pct=req.sl_pct,
        tp_pct=req.tp_pct,
        hold_bars=req.hold_bars,
        start_date=req.start_date,
        end_date=req.end_date,
    )
