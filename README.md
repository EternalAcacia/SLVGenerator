# SLVGenerator

SLVGenerator is a desktop tool for generating scrolling lyrics videos. It uses a CustomTkinter UI and a Pillow/Numpy rendering engine to preview the first frame and export MP4 videos with FFmpeg.

### Features

- Select background image, audio file, and LRC lyrics; videos auto-save to `output/<title> - <artist>.mp4`
- Edit title and artist text
- Scan system fonts and choose fonts for main lyrics, highlighted main lyrics, secondary lyrics, title, and artist
- Adjust lyric font sizes, margins, visible range, fade, disc position, disc radius, title position, and background wiggle
- Toggle disc and audio spectrum visibility; adjust disc image crop from the background
- Choose output resolution presets (1080p, 720p, 4K, vertical) or custom size
- Generate a first-frame preview before rendering
- Render MP4 in a background thread with progress updates

### Requirements

- Python 3.10+ (source install only)
- FFmpeg and FFprobe available in PATH for MP4 export
- Python packages from `requirements.txt` (source install only)

### Download (Windows)

Pre-built Windows builds are available on the [Releases](https://github.com/EternalAcacia/SLVGenerator/releases) page. Download the latest `SLVGenerator-v1.1.0-windows.zip`, extract it, and run `SLVGenerator.exe`.

FFmpeg is still required for MP4 export. You can optionally place custom fonts in a `fonts/` folder next to the executable.

### Run from source

```bash
pip install -r requirements.txt
python main.py
```

### Notes

- Media files, generated videos, local sample projects, and bundled font files are intentionally excluded from the repository
- The app scans system fonts automatically. You can also create a local `fonts/` folder and place your own fonts there; it is ignored by git
- LRC lines with the same timestamp are treated as grouped lyrics: the first line is the main lyric and the second line is the secondary lyric

### License

MIT License. See `LICENSE` for details.

---

SLVGenerator 是一个用于生成滚动字幕歌词视频的桌面工具，使用 CustomTkinter 界面和 Pillow/Numpy 渲染引擎，可预览首帧并通过 FFmpeg 导出 MP4 视频。

### 功能特性

- 选择背景图片、音频文件和 LRC 歌词；视频自动保存到 `output/歌名 - 歌手.mp4`
- 编辑歌名和歌手文本
- 扫描系统字体，并为主歌词、主歌词高亮、副歌词、歌名和歌手分别选择字体
- 调整歌词字号、边距、可见范围、淡出效果、唱片位置、唱片半径、标题位置和背景晃动效果
- 可开关唱片与音频频谱；可调整唱片在背景图上的裁剪区域
- 支持分辨率预设（1080p、720p、4K、竖屏）或自定义尺寸
- 渲染前生成首帧预览
- 在后台线程渲染 MP4，并显示进度更新

### 运行要求

- Python 3.10 或更高版本（仅源码安装时需要）
- 导出 MP4 需要将 FFmpeg 和 FFprobe 添加到 PATH
- 需要安装 `requirements.txt` 中列出的 Python 依赖（仅源码安装时需要）

### Windows 下载

Windows 预编译版本可在 [Releases](https://github.com/EternalAcacia/SLVGenerator/releases) 页面下载。下载最新的 `SLVGenerator-v1.1.0-windows.zip`，解压后运行 `SLVGenerator.exe` 即可。

导出 MP4 仍需要安装 FFmpeg。你也可以在可执行文件旁创建 `fonts/` 文件夹并放入自定义字体。

### 从源码运行

```bash
pip install -r requirements.txt
python main.py
```

### 注意事项

- 媒体文件、生成的视频、本地示例项目和内置字体文件已被有意排除在仓库之外
- 程序会自动扫描系统字体。你也可以创建本地 `fonts/` 文件夹并放入自己的字体；该文件夹会被 git 忽略
- 相同时间戳的 LRC 行会被视为一组歌词：第一行是主歌词，第二行是副歌词

### 许可证

本项目使用 MIT 许可证，详情见 `LICENSE` 文件。
