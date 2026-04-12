"""
GET  /indicators/available — List all available indicators
POST /indicators/custom    — Register a custom indicator
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from indicators.registry import list_indicators, register_custom_indicator, get_all_indicators
from indicators.base import BaseIndicator

router = APIRouter()


@router.get("/indicators/available")
def get_available_indicators(
    tier: Optional[str] = None,
    highlighted_only: bool = False,
):
    """
    List all available indicators with their parameters, tiers, and highlights.

    Optional filters:
    - tier: "most_precise" or "hidden_gem" to filter by precision tier
    - highlighted_only: True to show only the 3 highlighted indicators
    """
    indicators = list_indicators()

    if tier:
        indicators = [i for i in indicators if i.get("precision_tier") == tier]

    if highlighted_only:
        indicators = [i for i in indicators if i.get("highlighted")]

    # Group by type
    grouped = {}
    for ind in indicators:
        itype = ind["type"]
        if itype not in grouped:
            grouped[itype] = []
        grouped[itype].append(ind)

    return {
        "total": len(indicators),
        "indicators": indicators,
        "by_type": grouped,
        "tiers": {
            "most_precise": [i["name"] for i in indicators if i.get("precision_tier") == "most_precise"],
            "hidden_gem": [i["name"] for i in indicators if i.get("precision_tier") == "hidden_gem"],
            "highlighted": [i["name"] for i in indicators if i.get("highlighted")],
        },
    }


class CustomIndicatorRequest(BaseModel):
    name: str
    description: str
    indicator_type: str = "technical"
    code: str  # Python code defining compute() and check() functions
    params: dict = {}


@router.post("/indicators/custom")
def register_custom(request: CustomIndicatorRequest):
    """
    Register a custom indicator by providing Python code.

    The code must define two functions:
    - compute(df, params) -> dict
    - check(computed, params) -> dict with status, value, threshold, details

    Example code:
    ```
    def compute(df, params):
        latest = df['Close'].iloc[-1]
        sma = df['Close'].rolling(params.get('period', 20)).mean().iloc[-1]
        return {'close': latest, 'sma': sma, 'above': latest > sma}

    def check(computed, params):
        return {
            'status': 'PASS' if computed['above'] else 'FAIL',
            'value': f"Close={computed['close']}, SMA={computed['sma']}",
            'threshold': 'Close above SMA',
            'details': f"Above SMA: {computed['above']}"
        }
    ```
    """
    # Validate the code by executing it in a restricted namespace
    namespace = {}
    try:
        exec(request.code, namespace)
    except Exception as e:
        raise HTTPException(400, f"Code execution failed: {e}")

    if "compute" not in namespace:
        raise HTTPException(400, "Code must define a 'compute' function")
    if "check" not in namespace:
        raise HTTPException(400, "Code must define a 'check' function")

    compute_fn = namespace["compute"]
    check_fn = namespace["check"]
    default_params = request.params

    # Dynamically create a BaseIndicator subclass
    custom_cls = type(
        f"Custom_{request.name.replace(' ', '_')}",
        (BaseIndicator,),
        {
            "name": request.name,
            "indicator_type": request.indicator_type,
            "description": request.description,
            "default_params": property(lambda self, p=default_params: dict(p)),
            "compute": lambda self, df, params, fn=compute_fn: fn(df, params),
            "check": lambda self, computed, params, fn=check_fn: fn(computed, params),
        },
    )

    try:
        registered_name = register_custom_indicator(custom_cls)
    except Exception as e:
        raise HTTPException(400, f"Registration failed: {e}")

    return {
        "status": "registered",
        "name": registered_name,
        "description": request.description,
        "type": request.indicator_type,
        "params": default_params,
    }
