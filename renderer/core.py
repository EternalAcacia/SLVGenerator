"""Core frame rendering engine."""

from __future__ import annotations

import math
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from renderer.config import RenderConfig
from renderer.ffmpeg_encode import VideoEncoder, resolve_video_encoder, video_encode_ffmpeg_args
from renderer.lrc import LyricBlock, blocks_fingerprint

ProgressCallback = Callable[[float, float, str], None]


@dataclass
class LineSprite:
    inactive: np.ndarray
    active: np.ndarray
    inactive_h: int
    active_h: int
    inactive_w: int
    active_w: int
    slot_h: int
    slot_w: int
    blend_steps: list[tuple[np.ndarray, int, int]]


@dataclass
class RenderAssets:
    bg_large: np.ndarray
    cover_base: np.ndarray
    title_layer: np.ndarray
    sprites: list[LineSprite]
    layout_steps: list[float]
    spectrum: np.ndarray | None
    fingerprint: str


def assets_fingerprint(cfg: RenderConfig, blocks: list[LyricBlock]) -> str:
    return f"{cfg.fingerprint()}|{blocks_fingerprint(blocks)}"


def check_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def ease_out_power(x: float, power: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return 1.0 - pow(1.0 - x, power)


def load_font(path: str | Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


def wiggle_offset(cfg: RenderConfig, t: float) -> tuple[float, float]:
    if not cfg.wiggle_enabled:
        return 0.0, 0.0
    phase = t * cfg.wiggle_freq * math.tau
    wx = cfg.wiggle_amp * math.sin(phase + 0.6)
    wy = cfg.wiggle_amp * math.cos(phase * 0.87 + 1.4)
    return wx, wy


def add_text_glow(img: Image.Image, cfg: RenderConfig, blur: int | None = None, glow_alpha: int | None = None) -> Image.Image:
    blur = cfg.text_glow_blur if blur is None else blur
    glow_alpha = cfg.text_glow_alpha if glow_alpha is None else glow_alpha
    _, _, _, alpha = img.split()
    glow = Image.new("RGBA", img.size, (255, 255, 255, 0))
    glow.putalpha(alpha.point(lambda a: min(a, glow_alpha)))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=blur))
    return Image.alpha_composite(glow, img)


def prepare_bg_large(cfg: RenderConfig) -> np.ndarray:
    img = Image.open(cfg.bg_image).convert("RGB")
    tw = int(cfg.width * cfg.bg_overscan)
    th = int(cfg.height * cfg.bg_overscan)
    scale = max(tw / img.width, th / img.height)
    img = img.resize((int(img.width * scale), int(img.height * scale)), Image.Resampling.LANCZOS)
    left = (img.width - tw) // 2
    top = (img.height - th) // 2
    img = img.crop((left, top, left + tw, top + th))
    img = img.filter(ImageFilter.GaussianBlur(radius=4))
    overlay = Image.new("RGBA", (tw, th), (0, 0, 0, 45))
    merged = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    return np.asarray(merged)


def sample_bg_frame(cfg: RenderConfig, bg_large: np.ndarray, t: float) -> np.ndarray:
    wx, wy = wiggle_offset(cfg, t)
    lh, lw = bg_large.shape[:2]
    cx = (lw - cfg.width) // 2 + int(wx)
    cy = (lh - cfg.height) // 2 + int(wy)
    cx = max(0, min(cx, lw - cfg.width))
    cy = max(0, min(cy, lh - cfg.height))
    return bg_large[cy : cy + cfg.height, cx : cx + cfg.width].copy()


def make_cover_sprite(cfg: RenderConfig) -> np.ndarray:
    img = Image.open(cfg.bg_image).convert("RGB")
    size = cfg.cover_radius * 2
    scale = max(size / img.width, size / img.height)
    scaled_w = int(img.width * scale)
    scaled_h = int(img.height * scale)
    img = img.resize((scaled_w, scaled_h), Image.Resampling.LANCZOS)
    cx = int(scaled_w * min(max(cfg.disc_src_cx_ratio, 0.0), 1.0))
    cy = int(scaled_h * min(max(cfg.disc_src_cy_ratio, 0.0), 1.0))
    left = max(0, min(cx - size // 2, scaled_w - size))
    top = max(0, min(cy - size // 2, scaled_h - size))
    img = img.crop((left, top, left + size, top + size))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    rgba = img.convert("RGBA")
    rgba.putalpha(mask)
    return np.asarray(rgba)


def rotate_cover(cfg: RenderConfig, cover: np.ndarray, angle_deg: float) -> np.ndarray:
    img = Image.fromarray(cover)
    r = cfg.cover_radius
    rotated = img.rotate(-angle_deg, resample=Image.Resampling.BICUBIC, expand=False, center=(r, r))
    return np.asarray(rotated)


def perspective_coefficients(
    src: list[tuple[float, float]],
    dst: list[tuple[float, float]],
) -> tuple[float, ...]:
    matrix: list[list[float]] = []
    for (x, y), (u, v) in zip(src, dst):
        matrix.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        matrix.append([0, 0, 0, x, y, 1, -v * x, -v * y])
    a = np.array(matrix, dtype=np.float64)
    b = np.array([c for pair in dst for c in pair], dtype=np.float64)
    res = np.linalg.solve(a, b)
    return tuple(float(v) for v in res)


def apply_y_perspective(cfg: RenderConfig, layer: np.ndarray, *, left_closer: bool = True) -> np.ndarray:
    tilt = cfg.lyrics_tilt_y
    h, w = layer.shape[:2]
    depth = w * math.sin(math.radians(tilt)) * 0.52
    inset_y = depth * 0.14
    src = [(0, 0), (w, 0), (w, h), (0, h)]
    if left_closer:
        dst = [
            (depth * 0.08, inset_y),
            (w - depth * 0.78, inset_y * 1.6),
            (w - depth * 0.82, h - inset_y * 1.6),
            (depth * 0.08, h - inset_y),
        ]
    else:
        dst = [
            (depth * 0.78, inset_y * 1.6),
            (w - depth * 0.08, inset_y),
            (w - depth * 0.08, h - inset_y),
            (depth * 0.82, h - inset_y * 1.6),
        ]
    coeffs = perspective_coefficients(src, dst)
    img = Image.fromarray(layer)
    warped = img.transform((w, h), Image.Transform.PERSPECTIVE, coeffs, Image.Resampling.BICUBIC)
    return np.asarray(warped)


def apply_title_perspective(cfg: RenderConfig, layer: np.ndarray) -> np.ndarray:
    tilt = cfg.title_tilt_y
    h, w = layer.shape[:2]
    depth = w * math.sin(math.radians(tilt)) * 0.38
    inset_y = depth * 0.07
    src = [(0, 0), (w, 0), (w, h), (0, h)]
    dst = [
        (depth * 0.52, inset_y),
        (w - depth * 0.05, inset_y * 0.75),
        (w - depth * 0.05, h - inset_y * 0.75),
        (depth * 0.55, h - inset_y),
    ]
    coeffs = perspective_coefficients(src, dst)
    img = Image.fromarray(layer)
    warped = img.transform((w, h), Image.Transform.PERSPECTIVE, coeffs, Image.Resampling.BICUBIC)
    return np.asarray(warped)


def build_fonts(cfg: RenderConfig) -> dict:
    for p in (cfg.font_en, cfg.font_en_bold, cfg.font_cn, cfg.font_title, cfg.font_artist):
        if not Path(p).exists():
            raise FileNotFoundError(f"字体文件不存在: {p}")
    return {
        "title": load_font(cfg.font_title, cfg.title_font_size),
        "artist": load_font(cfg.font_artist, cfg.artist_font_size),
        "inactive_en": load_font(cfg.font_en, cfg.lyric_font_inactive_en),
        "active_en": load_font(cfg.font_en_bold, cfg.lyric_font_active_en),
        "inactive_cn": load_font(cfg.font_cn, cfg.lyric_font_inactive_cn),
        "active_cn": load_font(cfg.font_cn, cfg.lyric_font_active_cn),
    }


def draw_title_layer(cfg: RenderConfig, fonts: dict) -> np.ndarray:
    probe = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    probe_draw = ImageDraw.Draw(probe)
    title_bbox = probe_draw.textbbox((cfg.title_text_x, cfg.title_text_y), cfg.title, font=fonts["title"])
    artist_bbox = probe_draw.textbbox((cfg.artist_text_x, cfg.artist_text_y), cfg.artist, font=fonts["artist"])
    right = max(title_bbox[2], artist_bbox[2], 960)
    bottom = max(title_bbox[3], artist_bbox[3], 360)
    tmp = Image.new("RGBA", (right + 96, bottom + 96), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tmp)
    draw.text((cfg.title_text_x, cfg.title_text_y), cfg.title, font=fonts["title"], fill=(255, 255, 255, 245))
    draw.text((cfg.artist_text_x, cfg.artist_text_y), cfg.artist, font=fonts["artist"], fill=(255, 255, 255, 210))
    tmp = add_text_glow(tmp, cfg)
    bbox = tmp.getbbox()
    if not bbox:
        return np.zeros((1, 1, 4), dtype=np.uint8)
    glow_margin = 18
    cropped = tmp.crop(
        (
            max(0, bbox[0] - glow_margin),
            max(0, bbox[1] - glow_margin),
            min(tmp.width, bbox[2] + glow_margin),
            min(tmp.height, bbox[3] + glow_margin),
        )
    )
    cw, ch = cropped.size
    padded = np.zeros(
        (ch + cfg.title_pad_top + cfg.title_pad_bottom, cw + cfg.title_pad_left + cfg.title_pad_right, 4),
        dtype=np.uint8,
    )
    padded[cfg.title_pad_top : cfg.title_pad_top + ch, cfg.title_pad_left : cfg.title_pad_left + cw] = np.asarray(cropped)
    return apply_title_perspective(cfg, padded)


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def build_blend_steps(cfg: RenderConfig, sprite: LineSprite) -> list[tuple[np.ndarray, int, int]]:
    n = cfg.highlight_blend_steps
    steps: list[tuple[np.ndarray, int, int]] = [(sprite.inactive, sprite.inactive_h, sprite.inactive_w)]
    if n <= 2:
        steps.append((sprite.active, sprite.active_h, sprite.active_w))
        return steps
    active_img = Image.fromarray(sprite.active)
    rw = sprite.inactive_w / max(sprite.active_w, 1)
    rh = sprite.inactive_h / max(sprite.active_h, 1)
    for i in range(1, n - 1):
        t = i / (n - 1)
        new_w = max(1, int(round(sprite.active_w * lerp(rw, 1.0, t))))
        new_h = max(1, int(round(sprite.active_h * lerp(rh, 1.0, t))))
        scaled = active_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        arr = np.asarray(scaled).astype(np.float32)
        alpha_mul = lerp(cfg.lyric_alpha_inactive / 255.0, 1.0, t)
        rgb_mul = lerp(0.88, 1.0, t)
        arr[:, :, 3] *= alpha_mul
        arr[:, :, :3] *= rgb_mul
        steps.append((np.clip(arr, 0, 255).astype(np.uint8), new_h, new_w))
    steps.append((sprite.active, sprite.active_h, sprite.active_w))
    return steps


def blend_sprite_pair(a, b, frac: float):
    arr_a, ha, wa = a
    arr_b, hb, wb = b
    h, w = max(ha, hb), max(wa, wb)
    out = np.zeros((h, w, 4), dtype=np.float32)
    inv = 1.0 - frac
    for arr, ah, aw, weight in ((arr_a, ha, wa, inv), (arr_b, hb, wb, frac)):
        if weight <= 0.0:
            continue
        oy, ox = (h - ah) // 2, (w - aw) // 2
        patch = arr.astype(np.float32)
        alpha = patch[:, :, 3:4] / 255.0 * weight
        out[oy : oy + ah, ox : ox + aw, :3] += patch[:, :, :3] * alpha
        out[oy : oy + ah, ox : ox + aw, 3:4] += patch[:, :, 3:4] * weight
    out_a = out[:, :, 3:4] / 255.0
    rgb = np.where(out_a > 1e-6, out[:, :, :3] / np.maximum(out_a, 1e-6), 0)
    result = np.zeros((h, w, 4), dtype=np.uint8)
    result[:, :, :3] = np.clip(rgb, 0, 255).astype(np.uint8)
    result[:, :, 3] = np.clip(out[:, :, 3], 0, 255).astype(np.uint8)
    return result, h, w


def sample_highlight_sprite(sprite: LineSprite, blend: float):
    if blend <= 0.0:
        return sprite.blend_steps[0]
    if blend >= 1.0:
        return sprite.blend_steps[-1]
    steps = sprite.blend_steps
    idx_f = blend * (len(steps) - 1)
    i0 = int(idx_f)
    i1 = min(i0 + 1, len(steps) - 1)
    frac = idx_f - i0
    if frac < 1e-4:
        return steps[i0]
    if frac > 1.0 - 1e-4:
        return steps[i1]
    return blend_sprite_pair(steps[i0], steps[i1], frac)


def _draw_bilingual_sprite(cfg, block, en_font, cn_font, alpha, pad_top, cn_gap, cn_h, en_bottom, glow_blur, glow_alpha):
    color = (255, 255, 255, alpha)
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    en_w = probe.textlength(block.en, font=en_font)
    cn_w = probe.textlength(block.cn, font=cn_font) if block.cn else 0
    canvas_w = int(max(cfg.lyrics_min_canvas_w, max(en_w, cn_w) + 64))
    canvas_w = min(canvas_w, cfg.lyrics_max_canvas_w)
    tmp = Image.new("RGBA", (canvas_w, 220), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tmp)
    en_x = (canvas_w - en_w) / 2
    draw.text((en_x, pad_top), block.en, font=en_font, fill=color)
    cn_y = pad_top + cn_gap
    if block.cn:
        cn_x = (canvas_w - cn_w) / 2
        draw.text((cn_x, cn_y), block.cn, font=cn_font, fill=color)
        content_bottom = cn_y + cn_h
    else:
        content_bottom = pad_top + en_bottom
    bbox = tmp.getbbox()
    if not bbox:
        return np.zeros((1, 1, 4), dtype=np.uint8), 1, 0
    cropped = tmp.crop((0, max(0, bbox[1] - 8), canvas_w, max(content_bottom + 14, bbox[3] + 8)))
    cropped = add_text_glow(cropped, cfg, blur=glow_blur, glow_alpha=glow_alpha)
    arr = np.asarray(cropped)
    return arr, arr.shape[0], arr.shape[1]


def render_bilingual_sprite(cfg, block, fonts, active: bool):
    if active:
        return _draw_bilingual_sprite(
            cfg, block, fonts["active_en"], fonts["active_cn"], cfg.lyric_alpha_active,
            12, 48, 44, 40, cfg.text_glow_blur + 1, cfg.text_glow_alpha + 30,
        )
    return _draw_bilingual_sprite(
        cfg, block, fonts["inactive_en"], fonts["inactive_cn"], cfg.lyric_alpha_inactive,
        6, 38, 34, 32, cfg.text_glow_blur, cfg.text_glow_alpha,
    )


def build_layout_steps(cfg: RenderConfig, sprites: list[LineSprite]) -> list[float]:
    steps: list[float] = []
    for i in range(len(sprites) - 1):
        h_i = max(sprites[i].active_h, sprites[i].inactive_h)
        h_j = max(sprites[i + 1].active_h, sprites[i + 1].inactive_h)
        steps.append((h_i + h_j) / 2 + cfg.base_gap)
    return steps


def build_line_sprites(cfg: RenderConfig, blocks: list[LyricBlock], fonts: dict) -> list[LineSprite]:
    sprites: list[LineSprite] = []
    for block in blocks:
        inactive, ih, iw = render_bilingual_sprite(cfg, block, fonts, False)
        active, ah, aw = render_bilingual_sprite(cfg, block, fonts, True)
        sprite = LineSprite(inactive, active, ih, ah, iw, aw, max(ih, ah), max(iw, aw), [])
        sprite.blend_steps = build_blend_steps(cfg, sprite)
        sprites.append(sprite)
    return sprites


def blit_rgba(dst: np.ndarray, src: np.ndarray, x: int, y: int, alpha_mul: float = 1.0) -> None:
    h, w = src.shape[:2]
    dh, dw = dst.shape[:2]
    if alpha_mul <= 0.01 or y >= dh or y + h <= 0 or x >= dw or x + w <= 0:
        return
    y1, y2 = max(0, y), min(dh, y + h)
    x1, x2 = max(0, x), min(dw, x + w)
    sy1, sy2 = y1 - y, y2 - y
    sx1, sx2 = x1 - x, x2 - x
    if x2 <= x1 or y2 <= y1:
        return
    patch = src[sy1:sy2, sx1:sx2]
    alpha_s = patch[:, :, 3:4].astype(np.float32) / 255.0 * alpha_mul
    if dst.shape[2] == 4:
        dst_patch = dst[y1:y2, x1:x2].astype(np.float32)
        alpha_d = dst_patch[:, :, 3:4] / 255.0
        out_a = alpha_s + alpha_d * (1.0 - alpha_s)
        out_rgb = patch[:, :, :3].astype(np.float32) * alpha_s + dst_patch[:, :, :3] * alpha_d * (1.0 - alpha_s)
        dst[y1:y2, x1:x2, :3] = np.where(out_a > 1e-6, out_rgb / np.maximum(out_a, 1e-6), 0).astype(np.uint8)
        dst[y1:y2, x1:x2, 3] = (out_a[:, :, 0] * 255).astype(np.uint8)
    else:
        dst[y1:y2, x1:x2] = (
            dst[y1:y2, x1:x2].astype(np.float32) * (1 - alpha_s) + patch[:, :, :3].astype(np.float32) * alpha_s
        ).astype(np.uint8)


def lyric_fade(cfg: RenderConfig, dist: float, y_center: float) -> float:
    top = cfg.lyrics_center_y - cfg.lyrics_view_half
    bottom = cfg.lyrics_center_y + cfg.lyrics_view_half
    dist_fade = max(0.0, 1.0 - abs(dist) * 0.28)
    if y_center <= top:
        edge_fade = 0.0
    elif y_center < top + cfg.lyrics_fade:
        edge_fade = (y_center - top) / cfg.lyrics_fade
    elif y_center > bottom:
        edge_fade = 0.0
    elif y_center > bottom - cfg.lyrics_fade:
        edge_fade = (bottom - y_center) / cfg.lyrics_fade
    else:
        edge_fade = 1.0
    return dist_fade * max(0.0, min(1.0, edge_fade))


def compute_y_centers(cfg, scroll_idx, layout_steps, start_i, end_i):
    ref_i = int(math.floor(scroll_idx))
    ref_i = max(start_i, min(end_i - 1, ref_i))
    frac = scroll_idx - ref_i
    step = layout_steps[ref_i] if ref_i < len(layout_steps) else cfg.base_gap + 80
    y_centers = {ref_i: cfg.lyrics_center_y - frac * step}
    for i in range(ref_i - 1, start_i - 1, -1):
        y_centers[i] = y_centers[i + 1] - layout_steps[i]
    for i in range(ref_i + 1, end_i):
        y_centers[i] = y_centers[i - 1] + layout_steps[i - 1]
    return y_centers


def get_line_highlight_blend(i: int, scroll_idx: float) -> float:
    dist = scroll_idx - i
    if dist <= -1.0 or dist >= 1.0:
        return 0.0
    if dist <= 0.0:
        return 1.0 + dist
    return 1.0 - dist


def render_lyrics_panel(cfg: RenderConfig, sprites, scroll_idx, layout_steps) -> np.ndarray:
    panel = np.zeros((cfg.lyrics_panel_h, cfg.lyrics_panel_w, 4), dtype=np.uint8)
    start_i = max(0, int(scroll_idx) - cfg.visible_above)
    end_i = min(len(sprites), int(scroll_idx) + cfg.visible_below + 1)
    view_top = cfg.lyrics_center_y - cfg.lyrics_view_half - 60
    view_bottom = cfg.lyrics_center_y + cfg.lyrics_view_half + 60
    y_centers = compute_y_centers(cfg, scroll_idx, layout_steps, start_i, end_i)
    for i in range(start_i, end_i):
        dist = i - scroll_idx
        y = y_centers[i]
        blend = get_line_highlight_blend(i, scroll_idx)
        sprite = sprites[i]
        fade = lyric_fade(cfg, dist, y)
        if fade <= 0.01:
            continue
        src, h, w = sample_highlight_sprite(sprite, blend)
        slot_top = round(y - sprite.slot_h / 2)
        y_blit = slot_top + (sprite.slot_h - h) // 2
        if not (view_top <= slot_top + sprite.slot_h and slot_top <= view_bottom):
            continue
        x_slot = cfg.lyrics_center_x - sprite.slot_w // 2
        x_blit = max(
            cfg.lyrics_side_margin,
            min(x_slot + (sprite.slot_w - w) // 2, cfg.lyrics_panel_w - w - cfg.lyrics_side_margin),
        )
        blit_rgba(panel, src, x_blit, y_blit, fade)
    pad_v, pad_l, pad_r = cfg.lyrics_panel_pad_v, cfg.lyrics_panel_pad_left, cfg.lyrics_panel_pad_right
    padded = np.zeros((cfg.lyrics_panel_h + pad_v * 2, cfg.lyrics_panel_w + pad_l + pad_r, 4), dtype=np.uint8)
    padded[pad_v : pad_v + cfg.lyrics_panel_h, pad_l : pad_l + cfg.lyrics_panel_w] = panel
    return apply_y_perspective(cfg, padded)


def load_audio_spectrum(cfg: RenderConfig) -> np.ndarray:
    n_bars = cfg.spectrum_bars
    fps = cfg.fps
    cmd = [
        "ffmpeg", "-v", "error", "-i", str(cfg.audio_file),
        "-ac", "1", "-ar", "22050", "-f", "f32le", "pipe:1",
    ]
    raw = subprocess.check_output(cmd)
    samples = np.frombuffer(raw, dtype=np.float32)
    sr = 22050
    frame_samples = sr // fps
    total_frames = int(math.ceil(len(samples) / frame_samples))
    spectrum = np.zeros((total_frames, n_bars), dtype=np.float32)
    win = min(frame_samples * 2, 4096)
    if win < 64:
        win = 64
    freqs = np.fft.rfftfreq(win, 1 / sr)
    band_edges = np.geomspace(80, min(8000, sr / 2), n_bars + 1)
    for fi in range(total_frames):
        start = fi * frame_samples
        chunk = samples[start : start + win]
        if len(chunk) < win:
            chunk = np.pad(chunk, (0, win - len(chunk)))
        windowed = chunk * np.hanning(win)
        mag = np.abs(np.fft.rfft(windowed))
        for bi in range(n_bars):
            mask = (freqs >= band_edges[bi]) & (freqs < band_edges[bi + 1])
            spectrum[fi, bi] = float(mag[mask].mean()) if mask.any() else 0.0
    spectrum = np.log1p(spectrum)
    mx = spectrum.max() or 1.0
    return spectrum / mx


def draw_spectrum(cfg: RenderConfig, frame: np.ndarray, magnitudes: np.ndarray, disc_angle_deg: float) -> None:
    cx, cy = cfg.cover_center
    outer_r = cfg.spectrum_inner + cfg.spectrum_max_len + 16
    margin = cfg.spectrum_glow_blur * 3 + cfg.spectrum_bar_width + 6
    crop_r = int(outer_r + margin)
    x0 = max(0, cx - crop_r)
    y0 = max(0, cy - crop_r)
    x1 = min(cfg.width, cx + crop_r)
    y1 = min(cfg.height, cy + crop_r)
    lcx, lcy = cx - x0, cy - y0
    layer = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    rot = math.radians(disc_angle_deg)
    for i, mag in enumerate(magnitudes):
        angle = (i / len(magnitudes)) * math.tau - math.pi / 2 + rot
        inner_x = lcx + math.cos(angle) * cfg.spectrum_inner
        inner_y = lcy + math.sin(angle) * cfg.spectrum_inner
        length = 8 + mag * cfg.spectrum_max_len
        outer_x = lcx + math.cos(angle) * (cfg.spectrum_inner + length)
        outer_y = lcy + math.sin(angle) * (cfg.spectrum_inner + length)
        bar_alpha = int(cfg.spectrum_bar_alpha_min + mag * (cfg.spectrum_bar_alpha_max - cfg.spectrum_bar_alpha_min))
        draw.line([(inner_x, inner_y), (outer_x, outer_y)], fill=(255, 255, 255, bar_alpha), width=cfg.spectrum_bar_width)
        perp_x = -math.sin(angle) * 1.4
        perp_y = math.cos(angle) * 1.4
        draw.line(
            [(inner_x + perp_x, inner_y + perp_y), (outer_x + perp_x, outer_y + perp_y)],
            fill=(255, 255, 255, min(255, int(bar_alpha * 0.92))),
            width=max(5, cfg.spectrum_bar_width - 2),
        )
        draw.line([(inner_x, inner_y), (outer_x, outer_y)], fill=(255, 255, 255, 255), width=max(3, cfg.spectrum_bar_width - 5))
    _, _, _, alpha = layer.split()
    glow = Image.new("RGBA", layer.size, (255, 255, 255, 0))
    glow.putalpha(alpha.point(lambda a: min(a, cfg.spectrum_glow_alpha)))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=cfg.spectrum_glow_blur))
    combined = Image.alpha_composite(glow, layer)
    base = Image.fromarray(frame[y0:y1, x0:x1]).convert("RGBA")
    merged = Image.alpha_composite(base, combined)
    frame[y0:y1, x0:x1] = np.asarray(merged.convert("RGB"))


def get_scroll_index(cfg: RenderConfig, blocks: list[LyricBlock], t: float, duration: float) -> float:
    if not blocks or t < blocks[0].time:
        return 0.0
    for i in range(len(blocks) - 1):
        line_start = blocks[i].time
        next_start = blocks[i + 1].time
        if not (line_start <= t < next_start):
            continue
        interval = max(next_start - line_start, 0.001)
        scroll_span = max(interval * cfg.scroll_tail_ratio, cfg.scroll_min_seconds)
        scroll_span = min(scroll_span, interval * 0.95)
        scroll_start = next_start - scroll_span
        if t < scroll_start:
            return float(i)
        p = (t - scroll_start) / max(scroll_span, 0.001)
        return i + ease_out_power(p, cfg.scroll_ease_power)
    last = len(blocks) - 1
    if t < blocks[last].time:
        return float(last)
    tail_end = min(duration, blocks[last].time + 4.0)
    if tail_end <= blocks[last].time:
        return float(last)
    interval = tail_end - blocks[last].time
    scroll_span = min(max(interval * cfg.scroll_tail_ratio, cfg.scroll_min_seconds), interval * 0.95)
    scroll_start = tail_end - scroll_span
    if t < scroll_start:
        return float(last)
    p = (t - scroll_start) / max(scroll_span, 0.001)
    return last + ease_out_power(p, cfg.scroll_ease_power) * 0.1


def render_frame(
    cfg: RenderConfig,
    assets: RenderAssets,
    scroll_idx: float,
    spectrum_row: np.ndarray,
    t: float,
) -> np.ndarray:
    frame = sample_bg_frame(cfg, assets.bg_large, t)
    disc_angle = (t * cfg.disc_rot_speed) % 360.0
    if cfg.disc_enabled:
        cover = rotate_cover(cfg, assets.cover_base, disc_angle)
        cx, cy = cfg.cover_center
        blit_rgba(frame, cover, cx - cfg.cover_radius, cy - cfg.cover_radius)
    if cfg.spectrum_enabled:
        draw_spectrum(cfg, frame, spectrum_row, disc_angle)
    blit_rgba(frame, assets.title_layer, cfg.title_blit_x - cfg.title_pad_left, cfg.title_blit_y - cfg.title_pad_top)
    lyrics = render_lyrics_panel(cfg, assets.sprites, scroll_idx, assets.layout_steps)
    blit_rgba(frame, lyrics, cfg.lyrics_panel_x - cfg.lyrics_panel_pad_left, cfg.lyrics_panel_y - cfg.lyrics_panel_pad_v)
    return frame


def get_duration(audio_path: Path) -> float:
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
        text=True,
    )
    return float(out.strip())


def validate_config(cfg: RenderConfig, blocks: list[LyricBlock]) -> None:
    if not cfg.bg_image.exists():
        raise FileNotFoundError(f"背景图片不存在: {cfg.bg_image}")
    if not blocks:
        raise ValueError("歌词为空")
    build_fonts(cfg)


def prepare_render_assets(
    cfg: RenderConfig,
    blocks: list[LyricBlock],
    *,
    load_spectrum: bool = False,
) -> RenderAssets:
    validate_config(cfg, blocks)
    fonts = build_fonts(cfg)
    bg_large = prepare_bg_large(cfg)
    cover_base = make_cover_sprite(cfg)
    title_layer = draw_title_layer(cfg, fonts)
    sprites = build_line_sprites(cfg, blocks, fonts)
    layout_steps = build_layout_steps(cfg, sprites)
    spectrum = load_audio_spectrum(cfg) if load_spectrum and cfg.spectrum_enabled else None
    return RenderAssets(bg_large, cover_base, title_layer, sprites, layout_steps, spectrum, assets_fingerprint(cfg, blocks))


def render_preview_frame(
    cfg: RenderConfig,
    blocks: list[LyricBlock],
    assets: RenderAssets | None = None,
    t: float = 0.0,
) -> Image.Image:
    if assets is None or assets.fingerprint != assets_fingerprint(cfg, blocks):
        assets = prepare_render_assets(cfg, blocks, load_spectrum=False)
    duration = max((blocks[-1].time + 4.0) if blocks else 1.0, 1.0)
    scroll_idx = get_scroll_index(cfg, blocks, t, duration)
    spec_row = np.zeros(cfg.spectrum_bars, dtype=np.float32)
    frame = render_frame(cfg, assets, scroll_idx, spec_row, t)
    return Image.fromarray(frame, mode="RGB")


def _ffmpeg_error_tail(stderr: str) -> str:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    return "\n".join(lines[-8:])


def _build_ffmpeg_encode_cmd(cfg: RenderConfig, encoder: VideoEncoder) -> list[str]:
    return [
        "ffmpeg", "-y", "-v", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{cfg.width}x{cfg.height}", "-r", str(cfg.fps), "-i", "-",
        "-i", str(cfg.audio_file),
        "-map", "0:v:0", "-map", "1:a:0",
        *video_encode_ffmpeg_args(encoder),
        "-c:a", "aac", "-b:a", "320k", "-shortest", str(cfg.output_path),
    ]


def _write_video_frames(
    cfg: RenderConfig,
    blocks: list[LyricBlock],
    assets: RenderAssets,
    duration: float,
    total_frames: int,
    encoder: VideoEncoder,
    started_at: float,
    report: Callable[[float, float, str], None],
    cancel_event=None,
) -> None:
    proc = subprocess.Popen(_build_ffmpeg_encode_cmd(cfg, encoder), stdin=subprocess.PIPE, stderr=subprocess.PIPE, text=False)
    assert proc.stdin is not None
    assert proc.stderr is not None
    pipe_error: BrokenPipeError | None = None
    try:
        for i in range(total_frames):
            if cancel_event is not None and cancel_event.is_set():
                raise InterruptedError("渲染已取消")
            t = i / cfg.fps
            if cfg.spectrum_enabled and assets.spectrum is not None:
                spec = assets.spectrum[min(i, len(assets.spectrum) - 1)]
            else:
                spec = np.zeros(cfg.spectrum_bars, dtype=np.float32)
            scroll_idx = get_scroll_index(cfg, blocks, t, duration)
            frame = render_frame(cfg, assets, scroll_idx, spec, t)
            try:
                proc.stdin.write(frame.tobytes())
            except BrokenPipeError as exc:
                pipe_error = exc
                break
            if i % (cfg.fps * 3) == 0:
                elapsed = time.monotonic() - started_at
                report(100.0 * i / total_frames, elapsed, f"渲染中 {t:.1f}s")
    finally:
        try:
            proc.stdin.close()
        except BrokenPipeError:
            pipe_error = pipe_error or BrokenPipeError()
        if cancel_event is not None and cancel_event.is_set():
            proc.terminate()
            raise InterruptedError("渲染已取消")

    stderr = proc.stderr.read().decode("utf-8", errors="replace")
    return_code = proc.wait()
    if pipe_error is not None or return_code != 0:
        detail = _ffmpeg_error_tail(stderr)
        suffix = f"\n{detail}" if detail else ""
        raise RuntimeError(f"ffmpeg 编码失败 ({encoder.label}){suffix}")


def render_video(
    cfg: RenderConfig,
    blocks: list[LyricBlock],
    progress_callback: ProgressCallback | None = None,
    cancel_event=None,
) -> None:
    if not check_ffmpeg():
        raise RuntimeError("未找到 ffmpeg/ffprobe，请安装并加入 PATH")
    if not cfg.audio_file.exists():
        raise FileNotFoundError(f"音频文件不存在: {cfg.audio_file}")

    def report(pct: float, elapsed: float, msg: str) -> None:
        if progress_callback:
            progress_callback(pct, elapsed, msg)

    started_at = time.monotonic()
    report(0.0, 0.0, "准备资源...")
    assets = prepare_render_assets(cfg, blocks, load_spectrum=cfg.spectrum_enabled)
    if cfg.spectrum_enabled:
        assert assets.spectrum is not None
    duration = get_duration(cfg.audio_file)
    total_frames = int(math.ceil(duration * cfg.fps))
    cfg.output_path.parent.mkdir(parents=True, exist_ok=True)
    encoder = resolve_video_encoder(cfg.video_encoder, strict=cfg.video_encoder != "auto")
    report(0.0, 0.0, f"渲染 {total_frames} 帧... (编码器: {encoder.label})")
    fallback_encoder = resolve_video_encoder("libx264", strict=True)
    try:
        _write_video_frames(cfg, blocks, assets, duration, total_frames, encoder, started_at, report, cancel_event)
    except RuntimeError:
        if cfg.video_encoder != "auto" or encoder.codec == fallback_encoder.codec:
            raise
        report(0.0, time.monotonic() - started_at, f"{encoder.label} 失败，回退到 {fallback_encoder.label}...")
        _write_video_frames(cfg, blocks, assets, duration, total_frames, fallback_encoder, started_at, report, cancel_event)
        encoder = fallback_encoder
    report(100.0, time.monotonic() - started_at, f"完成: {cfg.output_path} (编码器: {encoder.label})")
