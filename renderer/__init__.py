"""Scrolling lyrics video renderer."""

from renderer.config import RenderConfig, default_unhappy_config
from renderer.core import prepare_render_assets, render_preview_frame, render_video
from renderer.lrc import LyricBlock, parse_lrc_file, parse_lrc_text

__all__ = [
    "RenderConfig",
    "LyricBlock",
    "default_unhappy_config",
    "parse_lrc_file",
    "parse_lrc_text",
    "prepare_render_assets",
    "render_preview_frame",
    "render_video",
]
