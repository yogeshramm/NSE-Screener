"""
POST   /presets/save    — Save a named filter configuration
GET    /presets/list    — List all saved presets
GET    /presets/{name}  — Load a specific preset
DELETE /presets/{name}  — Delete a preset
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from engine.presets import save_preset, load_preset, list_presets, delete_preset

router = APIRouter()


class SavePresetRequest(BaseModel):
    name: str
    config: dict


@router.post("/presets/save")
def save(request: SavePresetRequest):
    """Save a named filter configuration."""
    if not request.name.strip():
        raise HTTPException(400, "Preset name cannot be empty")

    # Sanitize name
    safe_name = request.name.strip().replace(" ", "_").lower()
    path = save_preset(safe_name, request.config)

    return {
        "status": "saved",
        "name": safe_name,
        "path": path,
    }


@router.get("/presets/list")
def list_all():
    """List all available preset names."""
    presets = list_presets()
    return {
        "total": len(presets),
        "presets": presets,
    }


@router.get("/presets/{name}")
def load(name: str):
    """Load a specific preset by name."""
    try:
        config = load_preset(name.strip())
    except FileNotFoundError:
        raise HTTPException(404, f"Preset '{name}' not found")
    return {
        "name": name,
        "config": config,
    }


@router.delete("/presets/{name}")
def delete(name: str):
    """Delete a preset by name."""
    deleted = delete_preset(name.strip())
    if not deleted:
        raise HTTPException(404, f"Preset '{name}' not found")
    return {
        "status": "deleted",
        "name": name,
    }
