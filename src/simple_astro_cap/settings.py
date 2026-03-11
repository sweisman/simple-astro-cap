"""JSON-based settings persistence."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, fields
from pathlib import Path

log = logging.getLogger(__name__)

_SETTINGS_DIR = Path.home() / ".config" / "simple-astro-cap"
_SETTINGS_FILE = _SETTINGS_DIR / "settings.json"


@dataclass
class AppSettings:
    exposure_us: float = 5000.0
    gain: float = 50.0
    offset: float = 0.0
    bit_depth: int = 8
    output_dir: str = "~/astro-captures"
    format_name: str = "SER"
    snap_format: str = "PNG"
    lens_description: str = ""
    sidebar_width: int = 250
    snap_sequence: int = 0
    session_sequence: int = 0


def load_settings() -> AppSettings:
    """Load settings from disk. Returns defaults on any error."""
    if not _SETTINGS_FILE.exists():
        return AppSettings()
    try:
        data = json.loads(_SETTINGS_FILE.read_text())
        # Only use keys that are valid fields
        valid = {f.name for f in fields(AppSettings)}
        filtered = {k: v for k, v in data.items() if k in valid}
        return AppSettings(**filtered)
    except Exception as e:
        log.warning("Failed to load settings: %s", e)
        return AppSettings()


def save_settings(settings: AppSettings) -> None:
    """Save settings to disk."""
    try:
        _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        _SETTINGS_FILE.write_text(json.dumps(asdict(settings), indent=2) + "\n")
    except Exception as e:
        log.warning("Failed to save settings: %s", e)
