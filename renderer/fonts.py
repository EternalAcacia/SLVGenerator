"""System font discovery for UI font pickers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from PIL import ImageFont

_FONT_EXTS = {".ttf", ".otf", ".ttc"}

_FAMILY_ZH: dict[str, str] = {
    "Microsoft YaHei": "微软雅黑",
    "Microsoft YaHei Bold": "微软雅黑 粗体",
    "Microsoft YaHei Light": "微软雅黑 细体",
    "SimHei": "黑体",
    "SimSun": "宋体",
    "NSimSun": "新宋体",
    "KaiTi": "楷体",
    "FangSong": "仿宋",
    "DengXian": "等线",
    "DengXian Light": "等线 细体",
    "DengXian Bold": "等线 粗体",
    "Source Han Sans CN": "思源黑体 CN",
    "Source Han Sans SC": "思源黑体 SC",
    "Source Han Sans CN Bold": "思源黑体 CN 粗体",
    "Source Han Sans SC Bold": "思源黑体 SC 粗体",
    "Noto Sans CJK SC": "Noto Sans CJK 简体中文",
    "Noto Sans SC": "Noto Sans 简体中文",
    "PingFang SC": "苹方 简体",
    "STHeiti": "华文黑体",
    "STSong": "华文宋体",
    "STKaiti": "华文楷体",
    "STFangsong": "华文仿宋",
    "YouYuan": "幼圆",
    "LiSu": "隶书",
    "Meiryo": "日文 Meiryo",
    "Meiryo UI": "日文 Meiryo UI",
    "Yu Gothic": "日文 游ゴシック",
    "Yu Gothic UI": "日文 Yu Gothic UI",
    "MS Gothic": "日文 MS Gothic",
    "MS Mincho": "日文 MS Mincho",
    "Malgun Gothic": "韩文 Malgun Gothic",
}

_CJK_FAMILY_KEYWORDS = (
    "yahei", "微软雅黑", "simhei", "黑体", "simsun", "宋体", "nsimsun", "新宋体",
    "kaiti", "楷体", "fangsong", "仿宋", "dengxian", "等线", "source han", "思源",
    "noto sans cjk", "noto sans sc", "noto serif cjk", "pingfang", "苹方",
    "microsoft jhenghei", "微軟正黑", "mingliu", "細明體", "sarasa", "更纱",
    "wenquanyi", "文泉驿", "stheiti", "stkaiti", "stsong", "stfangsong",
    "stxihei", "stzhongsong", "youyuan", "幼圆", "lisu", "隶书", "harmonyos sans sc",
    "meiryo", "yu gothic", "ms gothic", "ms mincho", "malgun gothic",
)

_CJK_STEM_HINTS = (
    "msyh", "msjh", "simhei", "simsun", "nsimsun", "kaiti", "fangsong", "dengxian",
    "sourcehan", "notosanscjk", "notosanssc", "notoserifcjk", "pingfang", "sarasa",
    "cjksc", "cjktc", "cjkhk", "mingliu", "pmingliu", "yuanti", "stheiti", "stkaiti",
    "stsong", "stfangsong", "stxihei", "stzhongsong", "youyuan", "lisu",
    "meiryo", "yugoth", "msgothic", "msmincho", "malgun",
)


@dataclass(frozen=True)
class FontInfo:
    path: Path
    display_name: str
    supports_cjk: bool

    def __str__(self) -> str:
        return self.display_name


def _font_dirs(project_root: Path | None) -> list[Path]:
    dirs: list[Path] = [
        Path("C:/Windows/Fonts"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Windows/Fonts",
    ]
    if project_root:
        dirs.append(project_root / "fonts")
    return [d for d in dirs if d.is_dir()]


def _try_load(path: Path, size: int = 24) -> ImageFont.FreeTypeFont | None:
    try:
        return ImageFont.truetype(str(path), size=size)
    except OSError:
        return None


def _supports_cjk(font: ImageFont.FreeTypeFont, path: Path) -> bool:
    stem = path.stem.lower()
    if any(hint in stem for hint in _CJK_STEM_HINTS):
        return True
    try:
        family, style = font.getname()
        hay = f"{family} {style}".lower()
    except Exception:
        return False
    return any(keyword in hay for keyword in _CJK_FAMILY_KEYWORDS)


def _english_label(font: ImageFont.FreeTypeFont, path: Path) -> str:
    try:
        family, style = font.getname()
        if family:
            if style and style not in ("Regular", "Normal", ""):
                return f"{family} {style}"
            return family
    except Exception:
        pass
    return path.stem.replace("-", " ")


def _display_name(font: ImageFont.FreeTypeFont, path: Path) -> str:
    en = _english_label(font, path)
    zh = _FAMILY_ZH.get(en)
    if zh is None:
        family, style = font.getname()
        zh = _FAMILY_ZH.get(family)
    if zh:
        return f"{zh} ({en})" if zh != en else zh
    return en


def _unique_display_name(name: str, used: dict[str, int]) -> str:
    if name not in used:
        used[name] = 1
        return name
    used[name] += 1
    return f"{name} [{used[name]}]"


def scan_system_fonts(project_root: Path | None = None) -> list[FontInfo]:
    seen: set[str] = set()
    results: list[FontInfo] = []
    used_names: dict[str, int] = {}

    for font_dir in _font_dirs(project_root):
        for path in sorted(font_dir.iterdir()):
            if path.suffix.lower() not in _FONT_EXTS:
                continue
            key = str(path.resolve()).lower()
            if key in seen:
                continue
            font = _try_load(path)
            if font is None:
                continue
            seen.add(key)
            cjk = _supports_cjk(font, path)
            label = _unique_display_name(_display_name(font, path), used_names)
            results.append(FontInfo(path=path, display_name=label, supports_cjk=cjk))

    results.sort(key=lambda f: f.display_name.lower())
    return results


def pick_default_fonts(fonts: list[FontInfo], project_root: Path | None = None) -> tuple[FontInfo | None, FontInfo | None, FontInfo | None]:
    """Return (en, en_bold, cn) best guesses."""
    en = en_bold = cn = None
    path_map = {str(f.path).lower(): f for f in fonts}

    def match_any(f: FontInfo, *needles: str) -> bool:
        hay = f"{f.display_name} {f.path.name}".lower().replace(" ", "")
        return any(n.replace(" ", "") in hay for n in needles)

    for name in ("segoeui", "segoe ui", "arial"):
        for f in fonts:
            if match_any(f, name) and not f.supports_cjk:
                en = f
                break
        if en:
            break

    for name in ("segoeuib", "segoe ui bold", "arialbd", "arial bold"):
        for f in fonts:
            if match_any(f, name) and not f.supports_cjk:
                en_bold = f
                break
        if en_bold:
            break

    for key in ("sourcehansanscn-bold", "source han sans cn bold", "msyhbd", "microsoft yahei bold", "simhei", "微软雅黑"):
        for f in fonts:
            if f.supports_cjk and match_any(f, key):
                cn = f
                break
        if cn:
            break

    if cn is None:
        cjk_fonts = [f for f in fonts if f.supports_cjk]
        if cjk_fonts:
            cn = cjk_fonts[0]

    if project_root:
        bundled = project_root / "fonts" / "SourceHanSansCN-Bold.otf"
        if bundled.exists():
            bf = path_map.get(str(bundled.resolve()).lower())
            if bf:
                cn = bf

    if en is None:
        latin = [f for f in fonts if not f.supports_cjk]
        if latin:
            en = latin[0]
    if en_bold is None:
        en_bold = en

    return en, en_bold, cn
