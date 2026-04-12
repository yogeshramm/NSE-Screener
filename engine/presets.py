"""
Preset Save/Load System
Save and load named filter configurations as JSON files.
"""

import json
from pathlib import Path

PRESETS_DIR = Path(__file__).parent.parent / "config" / "presets"


def save_preset(name: str, config: dict) -> str:
    """Save a named filter configuration. Returns the file path."""
    PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    filepath = PRESETS_DIR / f"{name}.json"
    with open(filepath, "w") as f:
        json.dump(config, f, indent=2)
    return str(filepath)


def load_preset(name: str) -> dict:
    """Load a named preset. Raises FileNotFoundError if not found."""
    filepath = PRESETS_DIR / f"{name}.json"
    if not filepath.exists():
        raise FileNotFoundError(f"Preset '{name}' not found at {filepath}")
    with open(filepath) as f:
        return json.load(f)


def list_presets() -> list[str]:
    """List all available preset names."""
    PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    return [f.stem for f in PRESETS_DIR.glob("*.json")]


def delete_preset(name: str) -> bool:
    """Delete a preset. Returns True if deleted, False if not found."""
    filepath = PRESETS_DIR / f"{name}.json"
    if filepath.exists():
        filepath.unlink()
        return True
    return False
