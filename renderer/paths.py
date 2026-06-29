"""Application path helpers."""

from __future__ import annotations

import sys
from pathlib import Path


def app_root() -> Path:
    """Return the app root directory for dev and PyInstaller builds."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent
