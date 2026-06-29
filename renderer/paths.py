"""Application path helpers."""

from __future__ import annotations

import re
import sys
from pathlib import Path

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def app_root() -> Path:
    """Return the app root directory for dev and PyInstaller builds."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def sanitize_filename_part(text: str, fallback: str = "untitled") -> str:
    cleaned = _INVALID_FILENAME_CHARS.sub("", text.strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned or fallback


def build_output_path(root: Path, title: str, artist: str) -> Path:
    """Build output/<title> - <artist>.mp4 under app root."""
    safe_title = sanitize_filename_part(title, "untitled")
    safe_artist = sanitize_filename_part(artist, "unknown")
    return root / "output" / f"{safe_title} - {safe_artist}.mp4"
