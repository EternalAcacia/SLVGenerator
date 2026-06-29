"""CustomTkinter GUI for scrolling lyrics video generator."""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image

from renderer.config import RenderConfig
from renderer.core import assets_fingerprint, check_ffmpeg, render_preview_frame, render_video
from renderer.ffmpeg_encode import ENCODER_AUTO_LABEL, encoder_combo_choices, resolve_video_encoder
from renderer.fonts import FontInfo, pick_default_fonts, scan_system_fonts
from renderer.lrc import parse_lrc_text
from renderer.paths import app_root, build_output_path

from gui.widgets import ScrollableComboBox

PROJECT_ROOT = app_root()
PREVIEW_WIDTH = 520

RESOLUTION_PRESETS: dict[str, tuple[int, int] | None] = {
    "1920×1080 (1080p)": (1920, 1080),
    "1280×720 (720p)": (1280, 720),
    "3840×2160 (4K)": (3840, 2160),
    "2560×1440 (2K)": (2560, 1440),
    "1080×1920 (竖屏 1080p)": (1080, 1920),
    "720×1280 (竖屏 720p)": (720, 1280),
    "自定义": None,
}


class LyricsVideoApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title("滚动字幕视频生成器")
        self.geometry("1280x820")
        self.minsize(1100, 700)

        self._fonts: list[FontInfo] = []
        self._font_map: dict[str, FontInfo] = {}
        self._preview_image: ctk.CTkImage | None = None
        self._cached_assets = None
        self._cached_fingerprint: str | None = None
        self._busy = threading.Event()
        self._cancel_render = threading.Event()
        self._worker: threading.Thread | None = None

        self._build_ui()
        self._load_fonts()
        if not check_ffmpeg():
            messagebox.showwarning("提示", "未检测到 ffmpeg/ffprobe，预览可用，但导出视频需要安装 ffmpeg 并加入 PATH。")

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=11, uniform="main")
        self.grid_columnconfigure(1, weight=9, uniform="main")
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)

        left = ctk.CTkFrame(self)
        left.grid(row=0, column=0, sticky="nsew", padx=(12, 6), pady=12)
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(0, weight=1)

        self.tabs = ctk.CTkTabview(left)
        self.tabs.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.tabs.add("素材")
        self.tabs.add("字体")
        self.tabs.add("字幕")
        self.tabs.add("标题")
        self.tabs.add("唱片与背景")
        self._build_tab_media()
        self._build_tab_fonts()
        self._build_tab_lyrics()
        self._build_tab_title()
        self._build_tab_disc()

        right = ctk.CTkFrame(self)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 12), pady=12)
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(right, text="首帧预览", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, pady=(12, 6))
        self.preview_label = ctk.CTkLabel(right, text="点击「刷新预览」生成预览", width=PREVIEW_WIDTH, height=int(PREVIEW_WIDTH * 9 / 16))
        self.preview_label.grid(row=1, column=0, padx=12, pady=6, sticky="n")
        self.preview_status = ctk.CTkLabel(right, text="", text_color="#888888")
        self.preview_status.grid(row=2, column=0, pady=(0, 8))
        self.preview_btn = ctk.CTkButton(right, text="刷新预览", command=self._on_preview)
        self.preview_btn.grid(row=3, column=0, pady=(0, 12))

        bottom = ctk.CTkFrame(self)
        bottom.grid(row=1, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 12))
        bottom.grid_columnconfigure(0, weight=1)
        btn_row = ctk.CTkFrame(bottom, fg_color="transparent")
        btn_row.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        self.render_btn = ctk.CTkButton(btn_row, text="开始渲染", command=self._on_render, width=120)
        self.render_btn.pack(side="left", padx=4)
        self.cancel_btn = ctk.CTkButton(btn_row, text="取消", command=self._on_cancel, width=80, state="disabled")
        self.cancel_btn.pack(side="left", padx=4)
        self.progress = ctk.CTkProgressBar(bottom)
        self.progress.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 4))
        self.progress.set(0)
        self.status_label = ctk.CTkLabel(bottom, text="就绪", anchor="w")
        self.status_label.grid(row=2, column=0, sticky="ew", padx=12)
        self.log_box = ctk.CTkTextbox(bottom, height=80)
        self.log_box.grid(row=3, column=0, sticky="ew", padx=12, pady=(4, 8))

    def _build_tab_media(self) -> None:
        tab = self.tabs.tab("素材")
        self.bg_path = ctk.StringVar()
        self.audio_path = ctk.StringVar()
        self.title_var = ctk.StringVar(value="")
        self.artist_var = ctk.StringVar(value="")
        self.resolution_preset = ctk.StringVar(value="1920×1080 (1080p)")
        self.width_var = ctk.StringVar(value="1920")
        self.height_var = ctk.StringVar(value="1080")
        self._row_file(tab, 0, "背景图片", self.bg_path, [("图片", "*.jpg *.jpeg *.png *.webp")])
        self._row_file(tab, 1, "音频文件", self.audio_path, [("音频", "*.mp3 *.aac *.wav *.flac *.m4a")])
        ctk.CTkLabel(tab, text="歌名").grid(row=2, column=0, sticky="w", padx=8, pady=(8, 0))
        ctk.CTkEntry(tab, textvariable=self.title_var).grid(row=2, column=1, sticky="ew", padx=8, pady=(8, 0))
        ctk.CTkLabel(tab, text="歌手").grid(row=3, column=0, sticky="w", padx=8, pady=4)
        ctk.CTkEntry(tab, textvariable=self.artist_var).grid(row=3, column=1, sticky="ew", padx=8, pady=4)
        ctk.CTkLabel(tab, text="输出路径").grid(row=4, column=0, sticky="w", padx=8, pady=4)
        self.output_path_label = ctk.CTkLabel(
            tab,
            text=str(build_output_path(PROJECT_ROOT, "", "")),
            anchor="w",
            justify="left",
            wraplength=520,
            text_color="#aaaaaa",
        )
        self.output_path_label.grid(row=4, column=1, sticky="ew", padx=8, pady=4)
        self.title_var.trace_add("write", self._update_output_path_label)
        self.artist_var.trace_add("write", self._update_output_path_label)
        ctk.CTkLabel(tab, text="分辨率").grid(row=5, column=0, sticky="w", padx=8, pady=4)
        res_frame = ctk.CTkFrame(tab, fg_color="transparent")
        res_frame.grid(row=5, column=1, sticky="ew", padx=8, pady=4)
        self.resolution_combo = ctk.CTkComboBox(
            res_frame,
            values=list(RESOLUTION_PRESETS.keys()),
            variable=self.resolution_preset,
            command=self._on_resolution_preset,
            width=220,
        )
        self.resolution_combo.pack(side="left")
        ctk.CTkLabel(res_frame, text="宽").pack(side="left", padx=(12, 4))
        self.width_entry = ctk.CTkEntry(res_frame, textvariable=self.width_var, width=72, state="disabled")
        self.width_entry.pack(side="left")
        ctk.CTkLabel(res_frame, text="高").pack(side="left", padx=(8, 4))
        self.height_entry = ctk.CTkEntry(res_frame, textvariable=self.height_var, width=72, state="disabled")
        self.height_entry.pack(side="left")
        self._encoder_label_to_codec: dict[str, str] = {}
        self.video_encoder_var = ctk.StringVar(value=ENCODER_AUTO_LABEL)
        ctk.CTkLabel(tab, text="视频编码").grid(row=6, column=0, sticky="w", padx=8, pady=4)
        enc_frame = ctk.CTkFrame(tab, fg_color="transparent")
        enc_frame.grid(row=6, column=1, sticky="ew", padx=8, pady=4)
        self.encoder_combo = ctk.CTkComboBox(
            enc_frame,
            values=[ENCODER_AUTO_LABEL],
            variable=self.video_encoder_var,
            command=self._on_encoder_choice,
            width=220,
        )
        self.encoder_combo.pack(side="left")
        self.encoder_hint = ctk.CTkLabel(enc_frame, text="", text_color="#888888")
        self.encoder_hint.pack(side="left", padx=(12, 0))
        self._refresh_encoder_choices()
        ctk.CTkLabel(tab, text="LRC 歌词").grid(row=7, column=0, sticky="nw", padx=8, pady=8)
        lrc_btns = ctk.CTkFrame(tab, fg_color="transparent")
        lrc_btns.grid(row=7, column=1, sticky="ew", padx=8, pady=8)
        ctk.CTkButton(lrc_btns, text="选择 LRC 文件", width=120, command=self._pick_lrc).pack(side="left")
        ctk.CTkLabel(
            lrc_btns,
            text="同一时间戳多行：第 1 行主歌词，第 2 行副歌词",
            text_color="#aaaaaa",
        ).pack(side="left", padx=(10, 0))
        self.lrc_text = ctk.CTkTextbox(tab, height=180)
        self.lrc_text.grid(row=8, column=0, columnspan=2, sticky="nsew", padx=8, pady=(0, 8))
        tab.grid_columnconfigure(1, weight=1)
        tab.grid_rowconfigure(8, weight=1)

    def _build_tab_fonts(self) -> None:
        tab = self.tabs.tab("字体")
        self.font_en_var = ctk.StringVar()
        self.font_en_bold_var = ctk.StringVar()
        self.font_cn_var = ctk.StringVar()
        self.font_title_var = ctk.StringVar()
        self.font_artist_var = ctk.StringVar()
        ctk.CTkButton(tab, text="刷新字体列表", command=self._load_fonts).grid(row=0, column=0, columnspan=2, pady=8)
        self._row_combo(tab, 1, "主歌词字体", self.font_en_var)
        self._row_combo(tab, 2, "主歌词高亮字体", self.font_en_bold_var)
        self._row_combo(tab, 3, "副歌词字体", self.font_cn_var)
        self._row_combo(tab, 4, "歌名字体", self.font_title_var)
        self._row_combo(tab, 5, "歌手字体", self.font_artist_var)
        self.font_path_label = ctk.CTkLabel(tab, text="", wraplength=400, justify="left", text_color="#aaaaaa")
        self.font_path_label.grid(row=6, column=0, columnspan=2, sticky="w", padx=8, pady=8)

    def _build_tab_lyrics(self) -> None:
        tab = self.tabs.tab("字幕")
        self.lyric_font_inactive_en = self._slider(tab, 0, "主歌词普通字号", 18, 60, 32, step=1)
        self.lyric_font_active_en = self._slider(tab, 1, "主歌词高亮字号", 24, 80, 44, step=1)
        self.lyric_font_inactive_cn = self._slider(tab, 2, "副歌词普通字号", 16, 56, 28, step=1)
        self.lyric_font_active_cn = self._slider(tab, 3, "副歌词高亮字号", 20, 72, 35, step=1)
        self.lyrics_right_margin = self._slider(tab, 4, "右侧边距", 40, 300, 88)
        self.lyrics_pad_left = self._slider(tab, 5, "左内边距", 20, 120, 56)
        self.lyrics_pad_right = self._slider(tab, 6, "右内边距", 40, 160, 100)
        self.lyrics_pad_v = self._slider(tab, 7, "上下内边距", 20, 120, 56)
        self.lyrics_view_half = self._slider(tab, 8, "显示半高", 150, 450, 300)
        self.visible_above = self._slider(tab, 9, "上方可见行", 2, 10, 5, step=1)
        self.visible_below = self._slider(tab, 10, "下方可见行", 2, 10, 6, step=1)
        self.lyrics_fade = self._slider(tab, 11, "边缘淡出", 40, 160, 95)

    def _build_tab_title(self) -> None:
        tab = self.tabs.tab("标题")
        self.title_blit_x = self._slider(tab, 0, "标题层 X", 0, 600, 68, step=1)
        self.title_blit_y = self._slider(tab, 1, "标题层 Y", 0, 300, 56, step=1)
        self.title_font_size = self._slider(tab, 2, "歌名字号", 24, 120, 64, step=1)
        self.artist_font_size = self._slider(tab, 3, "歌手字号", 16, 80, 33, step=1)
        self.title_text_x = self._slider(tab, 4, "歌名相对 X", 0, 260, 20, step=1)
        self.title_text_y = self._slider(tab, 5, "歌名相对 Y", 0, 160, 18, step=1)
        self.artist_text_x = self._slider(tab, 6, "歌手相对 X", 0, 260, 20, step=1)
        self.artist_text_y = self._slider(tab, 7, "歌手相对 Y", 0, 220, 92, step=1)

    def _build_tab_disc(self) -> None:
        tab = self.tabs.tab("唱片与背景")
        self.disc_enabled = tk.BooleanVar(value=True)
        self.spectrum_enabled = tk.BooleanVar(value=True)
        ctk.CTkSwitch(tab, text="显示唱片", variable=self.disc_enabled).grid(row=0, column=0, columnspan=2, padx=8, pady=(8, 4), sticky="w")
        ctk.CTkSwitch(tab, text="显示音频频谱", variable=self.spectrum_enabled).grid(row=1, column=0, columnspan=2, padx=8, pady=4, sticky="w")
        self.disc_src_x = self._slider(tab, 2, "唱片图源 X", 0, 100, 50, step=1)
        self.disc_src_y = self._slider(tab, 3, "唱片图源 Y", 0, 100, 50, step=1)
        self.cover_x = self._slider(tab, 4, "唱片中心 X", 150, 600, 328, step=1)
        self.cover_y = self._slider(tab, 5, "唱片中心 Y", 200, 880, 540, step=1)
        self.cover_radius = self._slider(tab, 6, "唱片半径", 80, 220, 178, step=1)
        self.wiggle_enabled = tk.BooleanVar(value=True)
        ctk.CTkSwitch(tab, text="背景 Wiggle", variable=self.wiggle_enabled).grid(row=7, column=0, columnspan=2, padx=8, pady=12, sticky="w")
        self.wiggle_freq = self._slider(tab, 8, "Wiggle 频率", 0.2, 3.0, 1.2, step=0.1)
        self.wiggle_amp = self._slider(tab, 9, "Wiggle 幅度", 0.0, 20.0, 5.0, step=0.5)

    def _slider(self, parent, row, label, vmin, vmax, default, step=1):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=row, column=0, columnspan=2, sticky="ew", padx=8, pady=4)
        ctk.CTkLabel(frame, text=label, width=100, anchor="w").pack(side="left")
        val_label = ctk.CTkLabel(frame, text=str(default), width=50)
        val_label.pack(side="right")

        def on_change(v):
            if step == 1:
                val_label.configure(text=str(int(float(v))))
            else:
                val_label.configure(text=f"{float(v):.1f}")

        slider = ctk.CTkSlider(frame, from_=vmin, to=vmax, number_of_steps=int((vmax - vmin) / step) if step else 100, command=on_change)
        slider.set(default)
        slider.pack(side="left", fill="x", expand=True, padx=8)
        slider._val_label = val_label  # type: ignore[attr-defined]
        slider._is_int = step == 1
        return slider

    def _slider_value(self, slider) -> float | int:
        v = slider.get()
        return int(round(v)) if slider._is_int else float(v)

    def _row_file(self, parent, row, label, var, filetypes, save=False):
        ctk.CTkLabel(parent, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=6)

        def pick():
            if save:
                p = filedialog.asksaveasfilename(filetypes=filetypes, defaultextension=".mp4")
            else:
                p = filedialog.askopenfilename(filetypes=filetypes)
            if p:
                var.set(p)

        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=row, column=1, sticky="ew", padx=8, pady=6)
        ctk.CTkEntry(frame, textvariable=var).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(frame, text="浏览", width=60, command=pick).pack(side="left", padx=(6, 0))

    def _row_combo(self, parent, row, label, var):
        ctk.CTkLabel(parent, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=6)
        combo = ScrollableComboBox(parent, variable=var, values=[], command=self._update_font_paths)
        combo.grid(row=row, column=1, sticky="ew", padx=8, pady=6)
        parent.grid_columnconfigure(1, weight=1)
        setattr(self, f"_combo_{row}", combo)

    def _pick_lrc(self) -> None:
        p = filedialog.askopenfilename(filetypes=[("LRC", "*.lrc"), ("文本", "*.txt")])
        if p:
            text = self._read_text_file(Path(p))
            self.lrc_text.delete("1.0", "end")
            self.lrc_text.insert("1.0", text)

    def _read_text_file(self, path: Path) -> str:
        for encoding in ("utf-8-sig", "utf-8", "gb18030"):
            try:
                return path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
        return path.read_text(encoding="utf-8", errors="replace")

    def _refresh_encoder_choices(self) -> None:
        choices = encoder_combo_choices()
        self._encoder_label_to_codec = {label: codec for label, codec in choices}
        labels = [label for label, _ in choices]
        current = self.video_encoder_var.get()
        self.encoder_combo.configure(values=labels)
        if current not in labels:
            self.video_encoder_var.set(ENCODER_AUTO_LABEL)
        self._update_encoder_hint()

    def _on_encoder_choice(self, _choice: str) -> None:
        self._update_encoder_hint()

    def _update_encoder_hint(self) -> None:
        preference = self._encoder_label_to_codec.get(self.video_encoder_var.get(), "auto")
        resolved = resolve_video_encoder(preference)
        if preference == "auto":
            self.encoder_hint.configure(text=f"将使用: {resolved.label}")
        else:
            self.encoder_hint.configure(text=f"已选择: {resolved.label}")

    def _get_video_encoder_preference(self) -> str:
        return self._encoder_label_to_codec.get(self.video_encoder_var.get(), "auto")

    def _update_output_path_label(self, *_args) -> None:
        path = build_output_path(PROJECT_ROOT, self.title_var.get(), self.artist_var.get())
        self.output_path_label.configure(text=str(path))

    def _on_resolution_preset(self, choice: str) -> None:
        preset = RESOLUTION_PRESETS.get(choice)
        if preset:
            w, h = preset
            self.width_var.set(str(w))
            self.height_var.set(str(h))
            self.width_entry.configure(state="disabled")
            self.height_entry.configure(state="disabled")
        else:
            self.width_entry.configure(state="normal")
            self.height_entry.configure(state="normal")

    def _parse_resolution(self) -> tuple[int, int]:
        try:
            width = int(self.width_var.get().strip())
            height = int(self.height_var.get().strip())
        except ValueError as exc:
            raise ValueError("分辨率宽高必须是整数") from exc
        if width < 320 or height < 240:
            raise ValueError("分辨率过小，请至少使用 320×240")
        if width > 7680 or height > 4320:
            raise ValueError("分辨率过大，请不超过 7680×4320")
        return width, height

    def _load_fonts(self) -> None:
        self._fonts = scan_system_fonts(PROJECT_ROOT)
        self._font_map = {f.display_name: f for f in self._fonts}
        all_names = [f.display_name for f in self._fonts]
        self._combo_1.configure(values=all_names)
        self._combo_2.configure(values=all_names)
        self._combo_3.configure(values=all_names)
        self._combo_4.configure(values=all_names)
        self._combo_5.configure(values=all_names)
        en, en_bold, cn = pick_default_fonts(self._fonts, PROJECT_ROOT)
        if en:
            self.font_en_var.set(en.display_name)
            self.font_artist_var.set(en.display_name)
        if en_bold:
            self.font_en_bold_var.set(en_bold.display_name)
            self.font_title_var.set(en_bold.display_name)
        if cn:
            self.font_cn_var.set(cn.display_name)
        self._update_font_paths()
        self._log(f"已扫描 {len(self._fonts)} 个字体")

    def _update_font_paths(self, _=None) -> None:
        parts = []
        for label, var in (
            ("主", self.font_en_var),
            ("主高亮", self.font_en_bold_var),
            ("副", self.font_cn_var),
            ("歌名", self.font_title_var),
            ("歌手", self.font_artist_var),
        ):
            info = self._font_map.get(var.get())
            if info:
                parts.append(f"{label}: {info.path}")
        self.font_path_label.configure(text="\n".join(parts))

    def _log(self, msg: str) -> None:
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.status_label.configure(text=msg)

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.preview_btn.configure(state=state)
        self.render_btn.configure(state=state)
        self.cancel_btn.configure(state="normal" if busy else "disabled")
        if busy:
            self._busy.set()
        else:
            self._busy.clear()

    def _build_config(self) -> RenderConfig:
        fe = self._font_map.get(self.font_en_var.get())
        fb = self._font_map.get(self.font_en_bold_var.get())
        fc = self._font_map.get(self.font_cn_var.get())
        ft = self._font_map.get(self.font_title_var.get())
        fa = self._font_map.get(self.font_artist_var.get())
        if not fe or not fb or not fc or not ft or not fa:
            raise ValueError("请选择主歌词、主歌词高亮、副歌词、歌名、歌手字体")
        width, height = self._parse_resolution()
        title = self.title_var.get().strip()
        artist = self.artist_var.get().strip()
        if not title:
            raise ValueError("请填写歌名")
        if not artist:
            raise ValueError("请填写歌手")
        return RenderConfig(
            width=width,
            height=height,
            video_encoder=self._get_video_encoder_preference(),
            bg_image=Path(self.bg_path.get()),
            audio_file=Path(self.audio_path.get()),
            output_path=build_output_path(PROJECT_ROOT, title, artist),
            title=title,
            artist=artist,
            font_en=fe.path,
            font_en_bold=fb.path,
            font_cn=fc.path,
            font_title=ft.path,
            font_artist=fa.path,
            title_blit_x=int(self._slider_value(self.title_blit_x)),
            title_blit_y=int(self._slider_value(self.title_blit_y)),
            title_font_size=int(self._slider_value(self.title_font_size)),
            artist_font_size=int(self._slider_value(self.artist_font_size)),
            title_text_x=int(self._slider_value(self.title_text_x)),
            title_text_y=int(self._slider_value(self.title_text_y)),
            artist_text_x=int(self._slider_value(self.artist_text_x)),
            artist_text_y=int(self._slider_value(self.artist_text_y)),
            lyric_font_inactive_en=int(self._slider_value(self.lyric_font_inactive_en)),
            lyric_font_active_en=int(self._slider_value(self.lyric_font_active_en)),
            lyric_font_inactive_cn=int(self._slider_value(self.lyric_font_inactive_cn)),
            lyric_font_active_cn=int(self._slider_value(self.lyric_font_active_cn)),
            lyrics_panel_right_margin=int(self._slider_value(self.lyrics_right_margin)),
            lyrics_panel_pad_left=int(self._slider_value(self.lyrics_pad_left)),
            lyrics_panel_pad_right=int(self._slider_value(self.lyrics_pad_right)),
            lyrics_panel_pad_v=int(self._slider_value(self.lyrics_pad_v)),
            lyrics_view_half=int(self._slider_value(self.lyrics_view_half)),
            visible_above=int(self._slider_value(self.visible_above)),
            visible_below=int(self._slider_value(self.visible_below)),
            lyrics_fade=int(self._slider_value(self.lyrics_fade)),
            cover_center_x=int(self._slider_value(self.cover_x)),
            cover_center_y=int(self._slider_value(self.cover_y)),
            cover_radius=int(self._slider_value(self.cover_radius)),
            disc_enabled=bool(self.disc_enabled.get()),
            spectrum_enabled=bool(self.spectrum_enabled.get()),
            disc_src_cx_ratio=float(self._slider_value(self.disc_src_x)) / 100.0,
            disc_src_cy_ratio=float(self._slider_value(self.disc_src_y)) / 100.0,
            wiggle_enabled=bool(self.wiggle_enabled.get()),
            wiggle_freq=float(self._slider_value(self.wiggle_freq)),
            wiggle_amp=float(self._slider_value(self.wiggle_amp)),
        )

    def _parse_blocks(self):
        text = self.lrc_text.get("1.0", "end").strip()
        if not text:
            raise ValueError("请填写或导入 LRC 歌词")
        return parse_lrc_text(text)

    def _on_preview(self) -> None:
        if self._busy.is_set():
            return
        self._set_busy(True)
        self.preview_status.configure(text="正在生成预览...", text_color="#888888")

        def work():
            err = None
            img = None
            try:
                cfg = self._build_config()
                blocks = self._parse_blocks()
                fp = assets_fingerprint(cfg, blocks)
                assets = self._cached_assets if self._cached_fingerprint == fp else None
                if assets is None:
                    from renderer.core import prepare_render_assets

                    assets = prepare_render_assets(cfg, blocks, load_spectrum=False)
                    self._cached_assets = assets
                    self._cached_fingerprint = fp
                img = render_preview_frame(cfg, blocks, assets=assets, t=0.0)
            except Exception as e:
                err = str(e)

            self.after(0, lambda: self._preview_done(img, err))

        threading.Thread(target=work, daemon=True).start()

    def _preview_done(self, img: Image.Image | None, err: str | None) -> None:
        self._set_busy(False)
        if err:
            self.preview_status.configure(text=err, text_color="#ff6666")
            self._log(f"预览失败: {err}")
            return
        assert img is not None
        w, h = img.size
        scale = PREVIEW_WIDTH / w
        preview = img.resize((PREVIEW_WIDTH, int(h * scale)), Image.Resampling.LANCZOS)
        self._preview_image = ctk.CTkImage(light_image=preview, dark_image=preview, size=preview.size)
        self.preview_label.configure(image=self._preview_image, text="")
        self.preview_status.configure(text="预览已更新", text_color="#66cc88")
        self._log("预览生成完成")

    def _on_render(self) -> None:
        if self._busy.is_set():
            return
        if not check_ffmpeg():
            messagebox.showerror("错误", "未找到 ffmpeg，无法导出视频。")
            return
        self._cancel_render.clear()
        self._set_busy(True)
        self.progress.set(0)

        def work():
            err = None
            try:
                cfg = self._build_config()
                blocks = self._parse_blocks()

                def progress(pct, elapsed, msg):
                    self.after(0, lambda: self._render_progress(pct, msg))

                render_video(cfg, blocks, progress_callback=progress, cancel_event=self._cancel_render)
            except InterruptedError:
                err = "已取消"
            except Exception as e:
                err = str(e)
            self.after(0, lambda: self._render_done(err))

        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()

    def _render_progress(self, pct: float, msg: str) -> None:
        self.progress.set(pct / 100.0)
        self._log(msg)

    def _render_done(self, err: str | None) -> None:
        self._set_busy(False)
        self.progress.set(1.0 if not err else 0)
        if err:
            self._log(f"渲染失败: {err}")
            if err != "已取消":
                messagebox.showerror("渲染失败", err)
        else:
            cfg = self._build_config()
            self._log("渲染完成")
            messagebox.showinfo("完成", f"视频已保存到:\n{cfg.output_path}")

    def _on_cancel(self) -> None:
        self._cancel_render.set()
        self._log("正在取消...")


def run_app() -> None:
    app = LyricsVideoApp()
    app.mainloop()
