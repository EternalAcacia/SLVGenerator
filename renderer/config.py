"""Render configuration for scrolling lyrics videos."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RenderConfig:
    # Output
    width: int = 1920
    height: int = 1080
    fps: int = 30

    # Media
    bg_image: Path = field(default_factory=lambda: Path("."))
    audio_file: Path = field(default_factory=lambda: Path("."))
    output_path: Path = field(default_factory=lambda: Path("output.mp4"))
    title: str = ""
    artist: str = ""

    # Fonts
    font_en: Path = field(default_factory=lambda: Path("C:/Windows/Fonts/segoeui.ttf"))
    font_en_bold: Path = field(default_factory=lambda: Path("C:/Windows/Fonts/segoeuib.ttf"))
    font_cn: Path = field(default_factory=lambda: Path("fonts/SourceHanSansCN-Bold.otf"))
    font_title: Path = field(default_factory=lambda: Path("C:/Windows/Fonts/segoeuib.ttf"))
    font_artist: Path = field(default_factory=lambda: Path("C:/Windows/Fonts/segoeui.ttf"))

    # Lyrics panel
    lyrics_panel_w: int = 1080
    lyrics_panel_h: int = 760
    lyrics_panel_pad_left: int = 56
    lyrics_panel_pad_right: int = 100
    lyrics_panel_pad_v: int = 56
    lyrics_panel_right_margin: int = 88
    lyrics_side_margin: int = 12
    lyrics_tilt_y: float = 34.0
    lyrics_view_half: int = 300
    lyrics_fade: int = 95
    visible_above: int = 5
    visible_below: int = 6
    lyrics_min_canvas_w: int = 400
    lyrics_max_canvas_w: int = 1040
    base_gap: int = 24

    # Title overlay
    title_tilt_y: float = 28.0
    title_blit_x: int = 68
    title_blit_y: int = 56
    title_pad_left: int = 52
    title_pad_top: int = 44
    title_pad_right: int = 36
    title_pad_bottom: int = 36
    title_font_size: int = 64
    artist_font_size: int = 33
    title_text_x: int = 20
    title_text_y: int = 18
    artist_text_x: int = 20
    artist_text_y: int = 92

    # Lyric fonts
    lyric_font_inactive_en: int = 32
    lyric_font_active_en: int = 44
    lyric_font_inactive_cn: int = 28
    lyric_font_active_cn: int = 35
    lyric_alpha_inactive: int = 105
    lyric_alpha_active: int = 255
    highlight_blend_steps: int = 60
    scroll_tail_ratio: float = 0.38
    scroll_min_seconds: float = 0.3
    scroll_ease_power: float = 4.0

    # Disc
    cover_center_x: int = 328
    cover_center_y: int = 540
    cover_radius: int = 178
    disc_rot_speed: float = 36.0

    # Spectrum
    spectrum_bars: int = 72
    spectrum_inner_offset: int = 12
    spectrum_max_len: int = 64
    spectrum_bar_width: int = 9
    spectrum_bar_alpha_min: int = 215
    spectrum_bar_alpha_max: int = 255
    spectrum_glow_blur: int = 4
    spectrum_glow_alpha: int = 58

    # Background
    wiggle_enabled: bool = True
    wiggle_freq: float = 1.2
    wiggle_amp: float = 5.0
    bg_overscan: float = 1.08

    # Text glow
    text_glow_blur: int = 3
    text_glow_alpha: int = 70

    @property
    def lyrics_panel_x(self) -> int:
        return self.width - self.lyrics_panel_w - self.lyrics_panel_right_margin

    @property
    def lyrics_panel_y(self) -> int:
        return (self.height - self.lyrics_panel_h) // 2

    @property
    def lyrics_center_x(self) -> int:
        return self.lyrics_panel_w // 2

    @property
    def lyrics_center_y(self) -> int:
        return self.lyrics_panel_h // 2

    @property
    def spectrum_inner(self) -> float:
        return self.cover_radius + self.spectrum_inner_offset

    @property
    def cover_center(self) -> tuple[int, int]:
        return (self.cover_center_x, self.cover_center_y)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k, v in d.items():
            if isinstance(v, Path):
                d[k] = str(v)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RenderConfig:
        path_fields = ("bg_image", "audio_file", "output_path", "font_en", "font_en_bold", "font_cn", "font_title", "font_artist")
        kwargs = dict(data)
        for f in path_fields:
            if f in kwargs and kwargs[f]:
                kwargs[f] = Path(kwargs[f])
        return cls(**{k: v for k, v in kwargs.items() if k in cls.__dataclass_fields__})

    def fingerprint(self) -> str:
        """Hash key for asset cache invalidation (config only; pair with blocks_fingerprint)."""
        parts = [
            str(self.bg_image),
            str(self.font_en),
            str(self.font_en_bold),
            str(self.font_cn),
            str(self.font_title),
            str(self.font_artist),
            self.title,
            self.artist,
            str(self.title_blit_x),
            str(self.title_blit_y),
            str(self.title_font_size),
            str(self.artist_font_size),
            str(self.title_text_x),
            str(self.title_text_y),
            str(self.artist_text_x),
            str(self.artist_text_y),
            str(self.lyric_font_inactive_en),
            str(self.lyric_font_active_en),
            str(self.lyric_font_inactive_cn),
            str(self.lyric_font_active_cn),
            str(self.lyrics_panel_w),
            str(self.lyrics_panel_right_margin),
            str(self.lyrics_panel_pad_left),
            str(self.lyrics_panel_pad_right),
            str(self.lyrics_panel_pad_v),
            str(self.lyrics_view_half),
            str(self.lyrics_fade),
            str(self.visible_above),
            str(self.visible_below),
            str(self.cover_center_x),
            str(self.cover_center_y),
            str(self.cover_radius),
            str(self.wiggle_enabled),
            str(self.wiggle_freq),
            str(self.wiggle_amp),
        ]
        return "|".join(parts)


def default_unhappy_config(project_root: Path) -> RenderConfig:
    base = project_root / "Unhappy"
    fonts = project_root / "fonts"
    return RenderConfig(
        bg_image=base / "42607EB29DA556B1FAABCE2CDA21F2FD.jpg",
        audio_file=base / "unhappy.aac",
        output_path=base / "unhappy_lyrics.mp4",
        title="unhappy",
        artist="s0rrow",
        font_en=Path("C:/Windows/Fonts/segoeui.ttf"),
        font_en_bold=Path("C:/Windows/Fonts/segoeuib.ttf"),
        font_cn=fonts / "SourceHanSansCN-Bold.otf",
        font_title=Path("C:/Windows/Fonts/segoeuib.ttf"),
        font_artist=Path("C:/Windows/Fonts/segoeui.ttf"),
        cover_center_y=1080 // 2,
    )
