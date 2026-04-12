"""
GET /config/default — Get the full default filter configuration
"""

from fastapi import APIRouter
from engine.default_config import get_default_config

router = APIRouter()


@router.get("/config/default")
def get_default():
    """
    Get the complete default filter configuration.
    Every filter with its enabled flag and all parameters.
    Use this as a template for POST /screen config overrides.
    """
    config = get_default_config()

    # Count stats
    total_filters = 0
    total_params = 0
    for key, val in config.items():
        if isinstance(val, dict) and "enabled" in val:
            total_filters += 1
            total_params += len([k for k in val.keys() if k != "enabled"])

    return {
        "total_filters": total_filters,
        "total_params": total_params,
        "config": config,
    }
