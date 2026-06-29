"""LRC lyric parsing."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class LyricBlock:
    time: float
    en: str
    cn: str


_META = ("作词", "作曲", "翻唱", "作詞", "编曲")
_TIMESTAMP = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")


def parse_lrc_text(text: str) -> list[LyricBlock]:
    if not text.strip():
        raise ValueError("歌词内容为空")
    grouped: dict[float, list[str]] = {}
    for raw in text.splitlines():
        line = raw.strip()
        matches = list(_TIMESTAMP.finditer(line))
        if not matches:
            continue
        lyric = line[matches[-1].end() :].strip()
        if not lyric:
            continue
        for m in matches:
            t = int(m.group(1)) * 60 + float(m.group(2))
            grouped.setdefault(t, []).append(lyric)

    blocks: list[LyricBlock] = []
    for t in sorted(grouped):
        lines = grouped[t]
        if not lines:
            continue
        if any(k in lines[0] for k in _META):
            continue
        blocks.append(LyricBlock(t, lines[0], lines[1] if len(lines) > 1 else ""))

    if not blocks:
        raise ValueError("未解析到有效歌词行，请检查 LRC 格式")
    return blocks


def parse_lrc_file(path: Path) -> list[LyricBlock]:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return parse_lrc_text(path.read_text(encoding=encoding))
        except UnicodeDecodeError:
            continue
    return parse_lrc_text(path.read_text(encoding="utf-8", errors="replace"))


def blocks_fingerprint(blocks: list[LyricBlock]) -> str:
    payload = "\n".join(f"{b.time}\t{b.en}\t{b.cn}" for b in blocks)
    return hashlib.md5(payload.encode("utf-8")).hexdigest()
