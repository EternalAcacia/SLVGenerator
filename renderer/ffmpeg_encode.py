"""FFmpeg H.264 encoder detection and argument builders."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class VideoEncoder:
    codec: str
    label: str
    args: tuple[str, ...]


_ENCODERS: tuple[VideoEncoder, ...] = (
    VideoEncoder(
        "h264_nvenc",
        "NVIDIA NVENC",
        ("-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "20", "-pix_fmt", "yuv420p"),
    ),
    VideoEncoder(
        "h264_qsv",
        "Intel Quick Sync",
        ("-c:v", "h264_qsv", "-global_quality", "20", "-pix_fmt", "yuv420p"),
    ),
    VideoEncoder(
        "h264_amf",
        "AMD AMF",
        (
            "-c:v",
            "h264_amf",
            "-quality",
            "quality",
            "-rc",
            "cqp",
            "-qp_i",
            "20",
            "-qp_p",
            "20",
            "-pix_fmt",
            "yuv420p",
        ),
    ),
    VideoEncoder(
        "libx264",
        "CPU (libx264)",
        ("-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p"),
    ),
)

_ENCODER_BY_CODEC = {encoder.codec: encoder for encoder in _ENCODERS}

ENCODER_AUTO_LABEL = "自动检测"


def encoder_combo_choices() -> list[tuple[str, str]]:
    """Return GUI combo items as (display label, encoder preference codec)."""
    available = usable_ffmpeg_video_encoders()
    choices: list[tuple[str, str]] = [(ENCODER_AUTO_LABEL, "auto")]
    seen: set[str] = set()
    for encoder in _ENCODERS:
        if encoder.codec in available and encoder.codec not in seen:
            choices.append((encoder.label, encoder.codec))
            seen.add(encoder.codec)
    return choices


@lru_cache(maxsize=1)
def available_ffmpeg_video_encoders() -> frozenset[str]:
    try:
        output = subprocess.check_output(
            ["ffmpeg", "-hide_banner", "-encoders"],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=15,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return frozenset()

    codecs: set[str] = set()
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith("V"):
            codecs.add(parts[1])
    return frozenset(codecs)


@lru_cache(maxsize=None)
def video_encoder_probe_error(codec: str) -> str | None:
    """Return None when an encoder can successfully encode a tiny test frame."""
    encoder = _ENCODER_BY_CODEC.get(codec)
    if encoder is None:
        return f"未知编码器: {codec}"
    if codec not in available_ffmpeg_video_encoders():
        return f"当前 FFmpeg 不支持 {encoder.label}"

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=256x256:r=1:d=0.1",
        "-frames:v",
        "1",
        *encoder.args,
        "-f",
        "null",
        "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return str(exc)
    if proc.returncode == 0:
        return None
    return (proc.stderr or proc.stdout or f"{encoder.label} 试编码失败").strip()


def is_video_encoder_usable(codec: str) -> bool:
    return video_encoder_probe_error(codec) is None


@lru_cache(maxsize=1)
def usable_ffmpeg_video_encoders() -> frozenset[str]:
    return frozenset(encoder.codec for encoder in _ENCODERS if is_video_encoder_usable(encoder.codec))


def resolve_video_encoder(preference: str = "auto", *, strict: bool = False) -> VideoEncoder:
    """Pick the best usable H.264 encoder, with optional explicit preference."""
    available = usable_ffmpeg_video_encoders()
    if preference and preference != "auto":
        preferred = _ENCODER_BY_CODEC.get(preference)
        if preferred is not None and preferred.codec in available:
            return preferred
        if strict:
            label = preferred.label if preferred is not None else preference
            detail = video_encoder_probe_error(preference) if preferred is not None else None
            suffix = f"\n{detail}" if detail else ""
            raise RuntimeError(f"编码器不可用: {label}{suffix}")

    for encoder in _ENCODERS:
        if encoder.codec in available:
            return encoder

    return _ENCODER_BY_CODEC["libx264"]


def video_encode_ffmpeg_args(encoder: VideoEncoder | None = None, *, preference: str = "auto") -> list[str]:
    chosen = encoder or resolve_video_encoder(preference)
    return list(chosen.args)
