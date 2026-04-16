"""Multi-factor score endpoint."""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import List
from engine.multi_factor import compute_factor_scores

router = APIRouter()


class FactorReq(BaseModel):
    symbols: List[str]


@router.post("/factor-score")
def factor_score(req: FactorReq):
    syms = [s.strip().upper() for s in req.symbols if s.strip()]
    scores = compute_factor_scores(syms)
    return {"count": len(scores), "scores": scores}
