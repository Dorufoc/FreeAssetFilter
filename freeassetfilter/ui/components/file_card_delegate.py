#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FileCardDelegate — 文件卡片委托，视觉风格精确匹配 StyledInfoCard。

两种模式：
- card (grid): 宽>高，icon 在上，文字在下
- list (horizontal): 高<宽，icon 在左，文字在右

所有颜色从 tm 获取，零硬编码。
"""

from typing import Any, Dict, Optional

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QModelIndex,
    QPropertyAnimation,
    Property,
    QRect,
    QRectF,
    QSize,
    QTimer,
    Qt,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QConicalGradient,
    QFont,
    QFontMetrics,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import QStyledItemDelegate, QStyle, QStyleOptionViewItem

from theme import tm

from components.file_list_model import (
    FileNameRole,
    FilePathRole,
    IsDirRole,
    FileSizeRole,
    ModifiedRole,
    SuffixRole,
    IsSelectedRole,
    IsPreviewingRole,
    IconPixmapRole,
    CardWidthRole,
    GridOffsetRole,
)

# 图标相对 media 区域的放大系数：>1 时图标超出 media 区域边界绘制，视觉更大。
# 当前试探值 1.10 = 放大 10%，后续可按需调整（与 StyledInfoCard 保持一致）。
_MEDIA_ICON_SCALE: float = 1.10

# hover 图标缩放动画总开关：暂时禁用（False），恢复动画时改为 True（与 StyledInfoCard 保持一致）。
_HOVER_MEDIA_ANIM_ENABLED: bool = False

# ── 卡片状态过渡动画（默认 ↔ 池中 ↔ 预览中）────────────────────────────────
_STATE_IN_POOL: int = 1       # 状态位：已在文件池（选中态）
_STATE_PREVIEWING: int = 2    # 状态位：预览中
_STATE_ANIM_DURATION_MS: int = 200   # 状态过渡时长
_STATE_ANIM_INTERVAL_MS: int = 16    # 动画帧间隔
_HOVER_ANIM_DURATION_MS: int = 120   # hover 覆盖层过渡时长（比状态过渡短）


class _VisualState:
    """某一状态组合下的视觉参数（背景色、边框样式、边框宽度）。"""

    __slots__ = ("bg", "border_kind", "border_color", "width")

    def __init__(
        self,
        bg: QColor,
        border_kind: str,
        border_color: Optional[QColor],
        width: float,
    ) -> None:
        self.bg = bg
        self.border_kind = border_kind  # "plain"（纯色）| "gradient"（预览流光渐变）
        self.border_color = border_color
        self.width = width


class _StateTransition:
    """单张卡片的状态过渡动画：from 视觉 → to 视觉，t 为进度（0~1）。"""

    __slots__ = ("from_v", "to_v", "t")

    def __init__(self, from_v: _VisualState, to_v: _VisualState) -> None:
        self.from_v = from_v
        self.to_v = to_v
        self.t = 0.0

# ── 文件类型映射 ──────────────────────────────────────────────────────────────

_FILE_TYPE_MAP: Dict[str, str] = {
    "py": "Python 源文件", "js": "JavaScript 源文件",
    "ts": "TypeScript 源文件", "jsx": "JSX 源文件", "tsx": "TSX 源文件",
    "html": "HTML 文档", "css": "CSS 样式表", "scss": "SCSS 样式表",
    "less": "LESS 样式表", "json": "JSON 文件",
    "xml": "XML 文件", "yaml": "YAML 文件", "yml": "YAML 文件",
    "sh": "Shell 脚本", "bat": "批处理文件", "cmd": "批处理文件",
    "ps1": "PowerShell 脚本", "psm1": "PowerShell 模块",
    "cpp": "C++ 源文件", "c": "C 源文件", "h": "C 头文件",
    "hpp": "C++ 头文件", "java": "Java 源文件",
    "rs": "Rust 源文件", "go": "Go 源文件",
    "rb": "Ruby 源文件", "php": "PHP 源文件",
    "swift": "Swift 源文件", "kt": "Kotlin 源文件",
    "kts": "Kotlin 脚本", "cs": "C# 源文件", "lua": "Lua 源文件",
    "dart": "Dart 源文件", "r": "R 源文件",
    "m": "Objective-C 源文件", "mm": "Objective-C++ 源文件",
    "pl": "Perl 脚本", "pm": "Perl 模块",
    "sql": "SQL 文件", "vue": "Vue 组件",
    "svelte": "Svelte 组件", "astro": "Astro 组件",
    "txt": "文本文档", "md": "MD 源文件",
    "rst": "reStructuredText 文件", "tex": "LaTeX 文档",
    "pdf": "PDF 文档",
    "doc": "Word 文档", "docx": "Word 文档", "docm": "Word 文档",
    "dotx": "Word 模板",
    "xls": "Excel 表格", "xlsx": "Excel 表格", "xlsm": "Excel 表格",
    "xlsb": "Excel 二进制工作簿", "csv": "CSV 表格",
    "ppt": "PowerPoint 演示文稿", "pptx": "PowerPoint 演示文稿",
    "pptm": "PowerPoint 启用宏的演示文稿", "potx": "PowerPoint 模板",
    "rtf": "RTF 文档", "odt": "ODT 文本文档",
    "ods": "ODS 电子表格", "odp": "ODP 演示文稿",
    "jpg": "JPEG 图像", "jpeg": "JPEG 图像", "jpe": "JPEG 图像",
    "png": "PNG 图像", "gif": "GIF 图像", "bmp": "BMP 图像",
    "webp": "WebP 图像", "tiff": "TIFF 图像", "tif": "TIFF 图像",
    "svg": "SVG 图像", "avif": "AVIF 图像",
    "ico": "图标", "cur": "光标",
    "heic": "HEIC 图像", "heif": "HEIF 图像",
    "cr2": "CR2 图像", "cr3": "CR3 图像",
    "nef": "NEF 图像", "nrw": "NRW 图像",
    "arw": "ARW 图像", "srf": "SRF 图像",
    "dng": "DNG 图像", "orf": "ORF 图像",
    "raf": "RAF 图像", "rw2": "RW2 图像",
    "pef": "PEF 图像", "x3f": "X3F 图像",
    "psd": "PSD 图像", "psb": "PSB 图像",
    "ai": "Adobe Illustrator 文档",
    "eps": "EPS 文件",
    "mp4": "MP4 视频", "mov": "MOV 视频", "avi": "AVI 视频",
    "mkv": "MKV 视频", "wmv": "WMV 视频", "flv": "FLV 视频",
    "webm": "WebM 视频", "m4v": "M4V 视频",
    "mpeg": "MPEG 视频", "mpg": "MPG 视频",
    "mxf": "MXF 视频", "3gp": "3GP 视频",
    "vob": "VOB 视频", "m2ts": "M2TS 视频",
    "ts": "TS 视频", "mts": "MTS 视频", "divx": "DivX 视频",
    "mp3": "MP3 音频", "wav": "WAV 音频",
    "flac": "FLAC 音频", "ogg": "OGG 音频",
    "wma": "WMA 音频", "aac": "AAC 音频",
    "m4a": "M4A 音频", "opus": "Opus 音频",
    "mid": "MIDI 序列", "midi": "MIDI 序列",
    "ape": "APE 音频", "ac3": "AC3 音频",
    "tta": "TTA 音频", "dts": "DTS 音频",
    "aiff": "AIFF 音频",
    "zip": "Zip 压缩文件", "rar": "RAR 压缩文件",
    "7z": "7z 压缩文件", "tar": "TAR 压缩文件",
    "gz": "GZip 压缩文件", "bz2": "BZip2 压缩文件",
    "xz": "XZ 压缩文件", "lzma": "LZMA 压缩文件",
    "zst": "Zstd 压缩文件", "lz4": "LZ4 压缩文件",
    "iso": "ISO 镜像", "cab": "CAB 压缩文件",
    "arj": "ARJ 压缩文件", "tgz": "TGZ 压缩文件",
    "ttf": "TTF 字体", "otf": "OTF 字体",
    "woff": "WOFF 字体", "woff2": "WOFF2 字体",
    "eot": "EOT 字体",
    "exe": "应用程序", "dll": "应用程序扩展",
    "msi": "Windows Installer 包",
    "lnk": "快捷方式", "url": "Internet 快捷方式",
    "torrent": "BitTorrent 文件",
    "apk": "APK 安装包",
    "dmg": "DMG 磁盘映像",
    "deb": "DEB 安装包", "rpm": "RPM 安装包",
    "appimage": "AppImage 映像",
    "db": "数据库文件", "sqlite": "SQLite 数据库",
    "srt": "SRT 字幕", "ass": "ASS 字幕", "ssa": "SSA 字幕",
    "vtt": "WebVTT 字幕",
    "log": "日志文件", "ini": "INI 配置",
    "cfg": "配置文件", "conf": "配置文件",
    "reg": "注册表项",
}


def _get_file_type_display(suffix: str, is_dir: bool = False) -> str:
    if is_dir:
        return "文件夹"
    if not suffix:
        return "文件"
    suffix_lower = suffix.lower()
    if suffix_lower in _FILE_TYPE_MAP:
        return _FILE_TYPE_MAP[suffix_lower]
    return f"{suffix_lower.upper()} 文件"


_COLORS_CACHE: Dict[bool, Dict[str, Any]] = {}


def _clear_colors_cache(*_args) -> None:
    """主题变化时清空配色缓存（兜底覆盖同主题重设/热更新）。"""
    _COLORS_CACHE.clear()


tm.theme_changed.connect(_clear_colors_cache)

# 缩放配置缓存：(id(config), scale) → dict（scale 档位有限，内存占用极小）
_SCALED_CONFIG_CACHE: Dict[tuple, Dict[str, Any]] = {}

# 卡片/列表尺寸缓存：(id(config), scale) → (width, height)
# _calc_card_size 与 _calc_list_size 分开缓存，避免同构 key 串值。
_CARD_SIZE_CACHE: Dict[tuple, tuple] = {}
_LIST_SIZE_CACHE: Dict[tuple, tuple] = {}

# QFont / QFontMetrics 缓存：(point_size, weight) → 对象（绘制热路径复用）
_FONT_CACHE: Dict[tuple, "QFont"] = {}
_FONT_METRICS_CACHE: Dict[tuple, "QFontMetrics"] = {}


def _get_colors() -> Dict[str, Any]:
    """当前主题的卡片配色字典（缓存：主题切换前恒定不变）。

    resize 重绘热路径中每帧每卡片都会调用；缓存避免反复解析
    tm.surface/mid/text/accent 等颜色字符串。
    """
    key = tm.is_dark_theme()
    cached = _COLORS_CACHE.get(key)
    if cached is None:
        cached = {
            "bg": tm.alpha_of(tm.surface, 85),
            "border": tm.alpha_of(tm.mid, 30),
            "title": tm.text,
            "subtitle": tm.mid,
            "desc": tm.alpha_of(tm.mid, 60),
            "icon": tm.mid,
            "accent": tm.accent,
            "selected_bg": tm.alpha_of(tm.accent, 40),  # 选中态（已加入文件池）背景覆盖层：半透明主题色
            "secondary": tm.text,  # 预览态文字辅助色（渐变边框不再直接使用该色）
            "hover_overlay": tm.alpha_of(tm.mid, 25),  # hover 反馈：25% 灰度覆盖层（所有状态统一）
        }
        _COLORS_CACHE[key] = cached
    return cached


CARD_CONFIG: Dict[str, Any] = {
    "padding": 8,
    "gap": 6,
    "radius": 6,
    "media_size": 44,
    "icon_size": 20,
    "title_size": 10,
    "title_weight": 400,
    "subtitle_size": 9,
    "subtitle_weight": 400,
    "desc_size": 9,
    "desc_weight": 400,
}

LIST_CONFIG: Dict[str, Any] = {
    "padding": 12,
    "gap": 10,
    "radius": 6,
    "media_size": 40,
    "icon_size": 20,
    "title_size": 10,
    "title_weight": 700,
    "subtitle_size": 9,
    "subtitle_weight": 400,
    "desc_size": 9,
    "desc_weight": 400,
}


class FileCardDelegate(QStyledItemDelegate):
    """文件卡片委托，支持 card（网格）和 list（列表）两种模式。

    关键：QStyledItemDelegate 的 painter 不做坐标平移，option.rect 包含视口绝对坐标。
    所有绘制必须基于 option.rect 的 x/y 偏移，不能假设 (0, 0) 为原点。
    """

    def __init__(self, parent: Optional[object] = None) -> None:
        super().__init__(parent)
        self._layout_mode: str = "card"
        self._card_scale: float = 1.0
        self._pool_file_set: set[str] = set()  # 已存在于文件池中的文件路径集合

        # hover 图标缩放动画（与 StyledInfoCard 一致：1.0 → 1.05，OutBack 缓动）
        self._hover_row: int = -1        # 当前 hover 动画绑定的行（-1 = 无）
        self._hover_progress: float = 0.0  # 该行图标缩放进度（0~1）
        self._view: Optional[object] = None  # 关联视图，动画每帧触发 viewport 重绘
        self._media_scale_anim = QPropertyAnimation(self, b"media_scale")
        self._media_scale_anim.setDuration(220)
        self._media_scale_anim.setEasingCurve(QEasingCurve.OutBack)

        # 预览态渐变边框旋转动画：焦点绕卡片中心旋转（16ms/帧）
        self._preview_angle: float = 0.0          # 渐变焦点当前角度（度）
        self._preview_painted: bool = False        # 最近一帧是否有预览态卡片被绘制
        self._preview_anim_timer = QTimer(self)
        self._preview_anim_timer.setInterval(16)
        self._preview_anim_timer.timeout.connect(self._advance_preview_gradient)

        # 卡片状态过渡动画（默认 ↔ 池中 ↔ 预览中：背景/边框颜色插值 + 交叉淡化）
        self._last_state: Dict[int, int] = {}       # row → 最近一次绘制时的状态位
        self._last_path: Dict[int, str] = {}        # row → 最近一次绘制的文件路径（检测 row 复用）
        self._transitions: Dict[int, _StateTransition] = {}  # row → 进行中的过渡
        # hover 覆盖层透明度过渡（进入淡入 / 离开淡出，120ms）
        self._hover_overlay_progress: Dict[int, float] = {}  # row → 覆盖层当前透明度（0~1）
        self._hover_targets: Dict[int, bool] = {}            # row → hover 目标状态（True=淡入/False=淡出）
        self._state_anim_timer = QTimer(self)
        self._state_anim_timer.setInterval(_STATE_ANIM_INTERVAL_MS)
        self._state_anim_timer.timeout.connect(self._advance_state_transitions)

    @Property(float)
    def media_scale(self) -> float:
        """hover 图标缩放进度（0~1），由 QPropertyAnimation 驱动。"""
        return self._hover_progress

    @media_scale.setter
    def media_scale(self, value: float) -> None:
        self._hover_progress = float(value)
        if self._view is not None:
            self._view.viewport().update()

    def set_view(self, view) -> None:
        """设置关联视图：hover 动画每帧通过其 viewport 触发重绘。

        Args:
            view: 使用本 delegate 的 QListView 实例。
        """
        self._view = view

    def _animate_media_scale(self, target: float) -> None:
        """动画过渡 hover 图标缩放进度（OutBack 缓动，220ms）。"""
        self._media_scale_anim.stop()
        self._media_scale_anim.setStartValue(self._hover_progress)
        self._media_scale_anim.setEndValue(target)
        self._media_scale_anim.start()

    def _advance_preview_gradient(self) -> None:
        """推进预览态边框渐变焦点旋转（循环动画）。

        仅当最近一帧有预览态卡片被绘制时保持运行；预览消失后自动停止，
        避免持续重绘消耗。
        """
        if not self._preview_painted:
            self._preview_anim_timer.stop()
            return
        self._preview_painted = False
        self._preview_angle = (self._preview_angle + 1.0) % 360.0
        if self._view is not None:
            self._view.viewport().update()

    # ── 卡片状态过渡动画（默认 ↔ 池中 ↔ 预览中）─────────────────────────────

    def _advance_state_transitions(self) -> None:
        """推进所有进行中的卡片状态过渡与 hover 覆盖层过渡；无动画时停止定时器。"""
        # 推进卡片状态过渡（默认 ↔ 池中 ↔ 预览中）
        if self._transitions:
            step = _STATE_ANIM_INTERVAL_MS / float(_STATE_ANIM_DURATION_MS)
            finished = []
            for row, tr in self._transitions.items():
                tr.t = min(1.0, tr.t + step)
                if tr.t >= 1.0:
                    finished.append(row)
            for row in finished:
                del self._transitions[row]

        # 推进 hover 覆盖层透明度过渡（进入淡入 / 离开淡出）
        if self._hover_targets:
            hover_step = _STATE_ANIM_INTERVAL_MS / float(_HOVER_ANIM_DURATION_MS)
            for row, target in list(self._hover_targets.items()):
                cur = self._hover_overlay_progress.get(row, 0.0)
                if target:
                    cur = min(1.0, cur + hover_step)
                else:
                    cur = max(0.0, cur - hover_step)
                self._hover_overlay_progress[row] = cur
                if (target and cur >= 1.0) or (not target and cur <= 0.0):
                    del self._hover_targets[row]
                    if cur <= 0.0:
                        self._hover_overlay_progress.pop(row, None)

        if not self._transitions and not self._hover_targets:
            self._state_anim_timer.stop()
            return
        if self._view is not None:
            self._view.viewport().update()

    def _sync_hover_overlay(self, index: QModelIndex, is_hovered: bool) -> None:
        """检测 hover 状态变化，驱动覆盖层透明度过渡（淡入/淡出）。

        Args:
            index: 当前绘制项的索引。
            is_hovered: 是否处于 hover 状态。
        """
        row = index.row()
        current = self._hover_overlay_progress.get(row, 0.0)
        if is_hovered:
            if current >= 1.0:
                self._hover_targets.pop(row, None)
                return
            self._hover_targets[row] = True
        else:
            if current <= 0.0:
                self._hover_targets.pop(row, None)
                return
            self._hover_targets[row] = False
        if not self._state_anim_timer.isActive():
            self._state_anim_timer.start()

    def _sync_state_transition(
        self,
        index: QModelIndex,
        file_info: Dict[str, Any],
        is_in_pool: bool,
        is_previewing: bool,
    ) -> None:
        """检测卡片状态变化，启动背景/边框过渡动画（默认 ↔ 池中 ↔ 预览中）。

        虚拟化滚动导致 row 复用时，以路径变化为准重置该行的状态缓存，
        避免对错误文件播放过渡。

        Args:
            index: 当前绘制项的索引。
            file_info: 文件信息字典。
            is_in_pool: 是否已在文件池。
            is_previewing: 是否处于预览态。
        """
        row = index.row()
        path = file_info.get("path", "") or ""
        mask = (_STATE_IN_POOL if is_in_pool else 0) | (_STATE_PREVIEWING if is_previewing else 0)

        if self._last_path.get(row) != path:
            # 该行内容已变化（滚动复用）：重置缓存，直接显示新状态，不做过渡
            self._last_path[row] = path
            self._last_state[row] = mask
            self._transitions.pop(row, None)
            self._hover_overlay_progress.pop(row, None)
            self._hover_targets.pop(row, None)
            return

        last = self._last_state.get(row)
        if last is None:
            self._last_state[row] = mask
            return

        if last != mask:
            from_v = self._current_visual(row, last)
            to_v = self._resolve_visual(mask)
            self._transitions[row] = _StateTransition(from_v, to_v)
            self._last_state[row] = mask
            if not self._state_anim_timer.isActive():
                self._state_anim_timer.start()

    def _resolve_visual(self, mask: int) -> _VisualState:
        """根据状态位解析卡片的静态视觉参数。

        Args:
            mask: 状态位组合（_STATE_IN_POOL | _STATE_PREVIEWING）。

        Returns:
            对应的视觉参数。
        """
        colors = _get_colors()
        in_pool = bool(mask & _STATE_IN_POOL)
        previewing = bool(mask & _STATE_PREVIEWING)
        if previewing:
            return _VisualState(
                bg=colors["selected_bg"] if in_pool else colors["bg"],
                border_kind="gradient",
                border_color=None,
                width=2.0,
            )
        if in_pool:
            return _VisualState(
                bg=colors["selected_bg"],
                border_kind="plain",
                border_color=colors["accent"],
                width=1.0,
            )
        return _VisualState(
            bg=colors["bg"],
            border_kind="plain",
            border_color=colors["border"],
            width=1.0,
        )

    def _current_visual(self, row: int, fallback_mask: int) -> _VisualState:
        """获取某行当前视觉参数：过渡中取插值结果，否则按状态位解析。

        Args:
            row: 行号。
            fallback_mask: 无过渡时的状态位。

        Returns:
            当前视觉参数。
        """
        tr = self._transitions.get(row)
        if tr is None:
            return self._resolve_visual(fallback_mask)
        t = self._ease_out_cubic(tr.t)
        if tr.from_v.border_kind == "plain" and tr.to_v.border_kind == "plain":
            return _VisualState(
                bg=self._lerp_color(tr.from_v.bg, tr.to_v.bg, t),
                border_kind="plain",
                border_color=self._lerp_color(tr.from_v.border_color, tr.to_v.border_color, t),
                width=tr.from_v.width + (tr.to_v.width - tr.from_v.width) * t,
            )
        # 涉及预览渐变：渐变无法插值，取目标视觉（绘制阶段交叉淡化）
        return tr.to_v

    @staticmethod
    def _ease_out_cubic(t: float) -> float:
        """OutCubic 缓动，用于状态过渡的颜色/透明度插值。"""
        t = min(1.0, max(0.0, t))
        return 1.0 - (1.0 - t) ** 3

    @staticmethod
    def _lerp_color(a: QColor, b: QColor, t: float) -> QColor:
        """线性插值两个颜色（含 alpha 通道）。

        Args:
            a: 起始颜色。
            b: 结束颜色。
            t: 插值进度（0~1）。

        Returns:
            插值后的颜色。
        """
        return QColor(
            int(a.red() + (b.red() - a.red()) * t),
            int(a.green() + (b.green() - a.green()) * t),
            int(a.blue() + (b.blue() - a.blue()) * t),
            int(a.alpha() + (b.alpha() - a.alpha()) * t),
        )

    @staticmethod
    def _scaled_color(color: QColor, factor: float) -> QColor:
        """按比例缩放颜色透明度（用于交叉淡化）。"""
        factor = min(1.0, max(0.0, factor))
        return QColor(
            color.red(),
            color.green(),
            color.blue(),
            int(color.alpha() * factor),
        )

    def _scaled_gradient(self, gradient: QConicalGradient, factor: float) -> QConicalGradient:
        """按比例缩放渐变所有颜色带的透明度（用于交叉淡化）。"""
        scaled = QConicalGradient(gradient.center(), gradient.angle())
        for pos, color in gradient.stops():
            scaled.setColorAt(pos, self._scaled_color(color, factor))
        return scaled

    def _paint_state_surface(
        self,
        painter: QPainter,
        draw_rect: QRectF,
        radius: int,
        is_previewing: bool,
        is_in_pool: bool,
        transition: Optional[_StateTransition],
    ) -> None:
        """绘制卡片边框与背景。

        无过渡时按状态直接绘制；有过渡时背景颜色插值、边框交叉淡化，
        实现 默认 ↔ 池中 ↔ 预览中 之间的平滑颜色混合过渡。

        Args:
            painter: 已激活的 QPainter。
            draw_rect: 内缩后的绘制矩形。
            radius: 圆角半径。
            is_previewing: 是否处于预览态。
            is_in_pool: 是否已在文件池。
            transition: 进行中的状态过渡（无则为 None）。
        """
        colors = _get_colors()

        if transition is None:
            if is_previewing:
                border_width = 2
                border_brush = QBrush(
                    self._make_preview_gradient(draw_rect, self._preview_angle)
                )
                self._preview_painted = True
                if not self._preview_anim_timer.isActive():
                    self._preview_anim_timer.start()
            elif is_in_pool:
                border_width = 1
                border_brush = QBrush(colors["accent"])
            else:
                border_width = 1
                border_brush = QBrush(colors["border"])
            bg_color = colors["selected_bg"] if is_in_pool else colors["bg"]
            painter.setPen(QPen(border_brush, border_width))
            painter.setBrush(bg_color)
            painter.drawRoundedRect(draw_rect, radius, radius)
            return

        t = self._ease_out_cubic(transition.t)
        bg = self._lerp_color(transition.from_v.bg, transition.to_v.bg, t)
        width = transition.from_v.width + (transition.to_v.width - transition.from_v.width) * t

        if transition.from_v.border_kind == "plain" and transition.to_v.border_kind == "plain":
            # 纯色 ↔ 纯色：直接插值颜色，单层绘制
            border_color = self._lerp_color(
                transition.from_v.border_color,
                transition.to_v.border_color,
                t,
            )
            painter.setPen(QPen(QBrush(border_color), width))
            painter.setBrush(bg)
            painter.drawRoundedRect(draw_rect, radius, radius)
            return

        # 涉及预览渐变边框：背景 + 两层半透明边框交叉淡化（颜色混合过渡）
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(draw_rect, radius, radius)
        if t < 1.0:
            self._draw_border_layer(painter, draw_rect, radius, transition.from_v, 1.0 - t, width)
        if t > 0.0:
            self._draw_border_layer(painter, draw_rect, radius, transition.to_v, t, width)

    def _draw_border_layer(
        self,
        painter: QPainter,
        draw_rect: QRectF,
        radius: int,
        visual: _VisualState,
        alpha_factor: float,
        width: float,
    ) -> None:
        """以指定透明度绘制一层边框（纯色或预览流光渐变）。

        Args:
            painter: 已激活的 QPainter。
            draw_rect: 绘制矩形。
            radius: 圆角半径。
            visual: 边框视觉参数。
            alpha_factor: 透明度缩放系数（0~1）。
            width: 边框宽度。
        """
        if visual.border_kind == "gradient":
            grad = self._make_preview_gradient(draw_rect, self._preview_angle)
            brush = QBrush(self._scaled_gradient(grad, alpha_factor))
            self._preview_painted = True
            if not self._preview_anim_timer.isActive():
                self._preview_anim_timer.start()
        else:
            brush = QBrush(self._scaled_color(visual.border_color, alpha_factor))
        painter.setPen(QPen(brush, width))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(draw_rect, radius, radius)

    @staticmethod
    def _make_preview_gradient(rect: QRectF, angle_deg: float) -> QConicalGradient:
        """构建预览态边框流光渐变（角锥渐变，光斑沿圆周旋转）。

        角锥渐变颜色只与角度相关：沿边框一周颜色从主题色 30% 透明度 →
        峰值色 → 主题色 30% 透明度平滑过渡，两道光斑位于对侧并随
        start_angle 递增沿边框流动。峰值色主题感知：深色模式为白色，
        浅色模式为黑色（与背景形成对比）；谷值为主题色 30% 透明度。

        Args:
            rect: 卡片矩形（逻辑坐标）。
            angle_deg: 渐变起始角度（度），动画每帧递增实现旋转。

        Returns:
            可用于 QPen 笔刷的角锥渐变。
        """
        cx = rect.center().x()
        cy = rect.center().y()

        accent_30 = tm.alpha_of(tm.accent, 30)  # 主题色 30% 透明度
        peak = QColor(tm.white) if tm.is_dark_theme() else QColor(tm.black)

        gradient = QConicalGradient(cx, cy, angle_deg)
        gradient.setColorAt(0.0, accent_30)
        gradient.setColorAt(0.25, peak)         # 光斑 1 峰值（深色=白/浅色=黑）
        gradient.setColorAt(0.5, accent_30)
        gradient.setColorAt(0.75, peak)         # 光斑 2 峰值（对侧）
        gradient.setColorAt(1.0, accent_30)
        return gradient

    def _sync_hover_animation(self, index: QModelIndex, is_hovered: bool) -> None:
        """hover 状态翻转时驱动图标缩放动画（每张卡片独立进度）。

        进入：进度重置为 0 后动画到 1（OutBack 缓动，与 StyledInfoCard 一致）；
        离开：从当前进度动画回 0，动画期间该卡片继续绘制缩小过程。
        防抖：离开分支仅当动画未运行时才启动，避免 paint 每帧重启动画。
        """
        row = index.row()
        if not _HOVER_MEDIA_ANIM_ENABLED:
            return
        if is_hovered:
            if self._hover_row != row:
                self._hover_row = row
                self._hover_progress = 0.0
                self._animate_media_scale(1.0)
        elif (
            self._hover_row == row
            and self._hover_progress > 0.0
            and self._media_scale_anim.state() != QAbstractAnimation.Running
        ):
            self._animate_media_scale(0.0)

    def set_pool_files(self, paths: set[str]) -> None:
        """设置当前文件池中的文件路径集合，用于绘制"已在池中"边框标记。"""
        import os
        self._pool_file_set = {os.path.normcase(os.path.normpath(p)) for p in paths} if paths else set()

    def _is_file_in_pool(self, file_path: str) -> bool:
        """检查文件是否在文件池中（O(1) 查询，路径已 normcase 标准化）。"""
        if not file_path or not self._pool_file_set:
            return False
        import os
        return os.path.normcase(os.path.normpath(file_path)) in self._pool_file_set

    def set_card_mode(self) -> None:
        self._layout_mode = "card"

    def set_list_mode(self) -> None:
        self._layout_mode = "list"

    def set_card_scale(self, scale: float) -> None:
        self._card_scale = scale

    # ── 图标绘制 ──────────────────────────────────────────────────────────

    @staticmethod
    def _draw_icon_pixmap(
        painter: QPainter,
        icon_pixmap: object,
        media_rect: QRectF,
        hover_scale: float = 1.0,
    ) -> None:
        """在 media 区域中居中绘制图标，完整填充满整个区域（无背景）。

        设计原则：
        - 图标在 media 区域中严格居中（考虑 DPR 转换逻辑尺寸）
        - 完整填充满 media 区域（尺寸 = media 区域 × _MEDIA_ICON_SCALE），无额外内边距
        - 始终等比缩放适配：小于区域时放大填满，大于区域时缩小适配
        - DPR 感知：QPixmap.width() 返回物理像素，需除以 DPR 得到逻辑尺寸

        Args:
            painter: 已激活的 QPainter。
            icon_pixmap: 要绘制的 QPixmap。
            media_rect: media 区域的 QRectF（逻辑坐标）。
            hover_scale: hover 缩放系数（1.0 = 不放大）。
        """
        dpr = icon_pixmap.devicePixelRatio()
        logical_w = icon_pixmap.width() / dpr
        logical_h = icon_pixmap.height() / dpr

        # 图标显示尺寸 = media 区域尺寸 × 放大系数 × hover 缩放（无内边距）
        display_size = int(media_rect.width() * _MEDIA_ICON_SCALE * hover_scale)

        # 等比缩放至填满 media 区域。注意 scaled() 保留原 DPR：目标尺寸必须用
        # 物理像素（display_size × dpr），否则高 DPI 下逻辑尺寸会缩小 dpr 倍
        #（恰好同尺寸时跳过缩放，避免无谓拷贝）
        if logical_w != display_size or logical_h != display_size:
            target_phys = max(1, int(display_size * dpr))
            icon_pixmap = icon_pixmap.scaled(
                target_phys, target_phys,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            # 缩放后的 pixmap 保持原 DPR，重新计算逻辑尺寸
            dpr = icon_pixmap.devicePixelRatio()
            logical_w = icon_pixmap.width() / dpr
            logical_h = icon_pixmap.height() / dpr

        # 在 media 区域中居中（使用逻辑尺寸，以区域中心为基准）
        offset_x = int(media_rect.center().x() - logical_w / 2.0)
        offset_y = int(media_rect.center().y() - logical_h / 2.0)
        painter.drawPixmap(offset_x, offset_y, icon_pixmap)

    # ── 文件信息读取 ───────────────────────────────────────────────────────

    @staticmethod
    def _get_file_info(index: QModelIndex) -> Dict[str, Any]:
        model = index.model()
        if not model:
            return {}
        return {
            "name": model.data(index, FileNameRole) or "",
            "path": model.data(index, FilePathRole) or "",
            "is_dir": bool(model.data(index, IsDirRole)),
            "size": int(model.data(index, FileSizeRole) or 0),
            "modified": model.data(index, ModifiedRole) or "",
            "suffix": (model.data(index, SuffixRole) or "").lower(),
            "is_selected": bool(model.data(index, IsSelectedRole)),
            "is_previewing": bool(model.data(index, IsPreviewingRole)),
            "icon_pixmap": model.data(index, IconPixmapRole),
        }

    # ── sizeHint ────────────────────────────────────────────────────────────

    @staticmethod
    def _calc_card_size(config: Dict[str, Any], scale: float = 1.0) -> tuple:
        """根据配置计算卡片默认宽度和高度（支持双行文件名）。"""
        key = (id(config), scale)
        cached = _CARD_SIZE_CACHE.get(key)
        if cached is not None:
            return cached
        padding = int(config["padding"] * scale)
        gap = int(config["gap"] * scale)
        media_size = int(config["media_size"] * scale)
        font_key = (config["title_size"], config["title_weight"])
        font = _FONT_CACHE.get(font_key)
        if font is None:
            font = QFont("Microsoft YaHei UI", config["title_size"], config["title_weight"])
            _FONT_CACHE[font_key] = font
        fm = _FONT_METRICS_CACHE.get(font_key)
        if fm is None:
            fm = QFontMetrics(font)
            _FONT_METRICS_CACHE[font_key] = fm
        line_height = fm.height() + 2  # 行高 + 行间距
        text_height = line_height * 2  # 双行
        width = padding * 2 + media_size
        height = padding * 2 + media_size + gap + text_height
        result = (width, height)
        _CARD_SIZE_CACHE[key] = result
        return result

    @staticmethod
    def _calc_list_size(config: Dict[str, Any], scale: float = 1.0) -> tuple:
        """根据配置计算列表模式默认宽度和高度（仅一行文件名）。"""
        key = (id(config), scale)
        cached = _LIST_SIZE_CACHE.get(key)
        if cached is not None:
            return cached
        padding = int(config["padding"] * scale)
        media_size = int(config["media_size"] * scale)
        font_key = (config["title_size"], config["title_weight"])
        font = _FONT_CACHE.get(font_key)
        if font is None:
            font = QFont("Microsoft YaHei UI", config["title_size"], config["title_weight"])
            _FONT_CACHE[font_key] = font
        fm = _FONT_METRICS_CACHE.get(font_key)
        if fm is None:
            fm = QFontMetrics(font)
            _FONT_METRICS_CACHE[font_key] = fm
        text_height = fm.height() + 4
        width = 200
        height = padding * 2 + max(media_size, text_height)
        result = (width, height)
        _LIST_SIZE_CACHE[key] = result
        return result

    def sizeHint(
        self,
        option: Optional[QStyleOptionViewItem],
        index: Optional[QModelIndex],
    ) -> QSize:
        if self._layout_mode == "card":
            config = CARD_CONFIG
            if index is not None and index.isValid():
                model = index.model()
                if model is not None:
                    card_width = model.data(index, CardWidthRole)
                    if card_width is not None and int(card_width) > 0:
                        _, height = self._calc_card_size(config, self._card_scale)
                        return QSize(int(card_width), height)
            width, height = self._calc_card_size(config, self._card_scale)
            return QSize(width, height)
        else:
            config = LIST_CONFIG
            if index is not None and index.isValid():
                model = index.model()
                if model is not None:
                    card_width = model.data(index, CardWidthRole)
                    if card_width is not None and int(card_width) > 0:
                        _, height = self._calc_list_size(config, self._card_scale)
                        return QSize(int(card_width), height)
            width, height = self._calc_list_size(config, self._card_scale)
            return QSize(width, height)

    # ── paint ────────────────────────────────────────────────────────────

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        # 将绘制严格限制在 item 的 grid cell 内，避免 hover 时阴影/背景
        # 因网格偏移溢出到相邻 item 区域而形成残影
        painter.setClipRect(option.rect)

        file_info = self._get_file_info(index)
        is_selected = file_info.get("is_selected", False)
        is_previewing = file_info.get("is_previewing", False)
        is_hovered = bool(option.state & QStyle.State_MouseOver)
        is_in_pool = self._is_file_in_pool(file_info.get("path", ""))

        card_rect = self._resolve_card_rect(option, index)

        # hover 图标缩放动画同步（进入/离开时启动 OutBack 缓动）
        self._sync_hover_animation(index, is_hovered)
        # hover 缩放系数：1.0 → 1.05（与 StyledInfoCard 一致），仅作用于动画绑定行
        hover_scale = 1.0 + 0.05 * (
            self._hover_progress if self._hover_row == index.row() else 0.0
        )

        # 卡片状态过渡动画：检测状态位变化并启动背景/边框过渡
        self._sync_state_transition(index, file_info, is_in_pool, is_previewing)
        transition = self._transitions.get(index.row()) if self._transitions else None
        if transition is not None and transition.t >= 1.0:
            # 兜底清理（正常由定时器移除）
            self._transitions.pop(index.row(), None)
            transition = None

        # hover 覆盖层透明度过渡：淡入/淡出（比状态过渡更短）
        # 注意：默认值必须为 0.0 并与 _sync_hover_overlay 内部一致——若首次
        # hover paint 时默认取 1.0，会先画一帧全量覆盖层再回落淡入，造成闪烁
        self._sync_hover_overlay(index, is_hovered)
        hover_overlay_progress = self._hover_overlay_progress.get(index.row(), 0.0)

        if self._layout_mode == "card":
            self._paint_card(
                painter, card_rect, file_info, is_hovered, is_selected, is_previewing,
                is_in_pool=is_in_pool, hover_scale=hover_scale, transition=transition,
                hover_overlay_progress=hover_overlay_progress,
            )
        else:
            self._paint_list(
                painter, card_rect, file_info, is_hovered, is_selected, is_previewing,
                is_in_pool=is_in_pool, hover_scale=hover_scale, transition=transition,
                hover_overlay_progress=hover_overlay_progress,
            )

        painter.restore()

    def _resolve_card_rect(
        self,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> QRect:
        """解析卡片最终绘制矩形（在 grid cell 内居中）。"""
        rect = QRect(option.rect)
        target_size = self.sizeHint(option, index)
        if not target_size.isValid():
            return rect
        target_width = min(rect.width(), target_size.width())
        target_height = min(rect.height(), target_size.height())
        offset_x = max(0, (rect.width() - target_width + 1) // 2)
        # 垂直方向紧贴单元格顶部，不做居中：gridSize 为行距预留的额外高度
        # 统一落在卡片下方，使第一排卡片距容器上边缘的间距与文件储存池一致，
        # 且不改变卡片之间的行距。
        offset_y = 0

        return QRect(
            rect.x() + offset_x,
            rect.y() + offset_y,
            target_width,
            target_height,
        )

    def _get_scaled_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """获取缩放后的绘制配置（结果按 (config, scale) 缓存，避免每帧重算）。"""
        scale = self._card_scale
        key = (id(config), scale)
        cached = _SCALED_CONFIG_CACHE.get(key)
        if cached is not None:
            return cached
        result = {
            "padding": int(config["padding"] * scale),
            "gap": int(config["gap"] * scale),
            "radius": max(1, int(config["radius"] * scale)),
            "media_size": int(config["media_size"] * scale),
            "icon_size": max(1, int(config["icon_size"] * scale)),
            "title_size": config["title_size"],
            "title_weight": config["title_weight"],
            "subtitle_size": config["subtitle_size"],
            "subtitle_weight": config["subtitle_weight"],
            "desc_size": config["desc_size"],
            "desc_weight": config["desc_weight"],
        }
        _SCALED_CONFIG_CACHE[key] = result
        return result

    def _paint_card(
        self,
        painter: QPainter,
        rect: QRect,
        file_info: Dict[str, Any],
        is_hovered: bool,
        is_selected: bool,
        is_previewing: bool,
        is_in_pool: bool = False,
        hover_scale: float = 1.0,
        transition: Optional[_StateTransition] = None,
        hover_overlay_progress: float = 1.0,
    ) -> None:
        colors = _get_colors()
        config = self._get_scaled_config(CARD_CONFIG)
        padding = config["padding"]
        radius = config["radius"]
        gap = config["gap"]
        media_size = config["media_size"]

        rx = rect.x()
        ry = rect.y()
        w = rect.width()
        h = rect.height()
        card_rect = QRectF(rx, ry, w, h)

        # 状态表面（边框+背景）：无过渡按状态直绘；有过渡颜色插值/交叉淡化
        if transition is not None:
            border_width = transition.from_v.width + (
                transition.to_v.width - transition.from_v.width
            ) * self._ease_out_cubic(transition.t)
        elif is_previewing:
            border_width = 2
        else:
            border_width = 1

        # 内缩 border_width/2 绘制，避免边框被 item 的 clipRect 裁切
        # （参考 FileBlockCard._paint_card 的 adjusted 内缩方案）
        draw_rect = card_rect.adjusted(
            border_width / 2.0,
            border_width / 2.0,
            -border_width / 2.0,
            -border_width / 2.0,
        )
        self._paint_state_surface(
            painter, draw_rect, radius, is_previewing, is_in_pool, transition
        )

        # hover 反馈（所有状态统一）：叠加 25% 主题色覆盖层（透明度过渡动画）
        if is_hovered or hover_overlay_progress > 0.003:
            painter.setPen(Qt.NoPen)
            painter.setBrush(self._scaled_color(colors["hover_overlay"], hover_overlay_progress))
            painter.drawRoundedRect(draw_rect, radius, radius)

        # Media 区域 — 无灰色背景填充，图标直接绘制并填充满整个区域
        media_x = rx + (w - media_size) / 2.0
        media_y = ry + padding

        icon_pixmap = file_info.get("icon_pixmap")
        if icon_pixmap and not icon_pixmap.isNull():
            self._draw_icon_pixmap(
                painter,
                icon_pixmap,
                QRectF(media_x, media_y, media_size, media_size),
                hover_scale=hover_scale,
            )
        else:
            suffix = file_info.get("suffix", "")
            is_dir = file_info.get("is_dir", False)
            icon_char = "D" if is_dir else (suffix[0].upper() if suffix else "?")
            # 字号按放大后的图标尺寸比例计算，视觉占比与填满的图标一致
            icon_font_size = max(config["icon_size"], int(media_size * 0.6 * _MEDIA_ICON_SCALE * hover_scale))
            painter.setFont(QFont("Segoe UI", icon_font_size, QFont.Bold))
            painter.setPen(colors["icon"])
            painter.drawText(QRectF(media_x, media_y, media_size, media_size), Qt.AlignCenter, icon_char)

        # 文字区域
        text_x = rx + padding
        text_y = media_y + media_size + gap
        text_w = w - padding * 2
        text_h = h - (text_y - ry) - padding
        self._draw_text(painter, QRectF(text_x, text_y, text_w, text_h), config, file_info, align=Qt.AlignCenter)

    def _paint_list(
        self,
        painter: QPainter,
        rect: Any,
        file_info: Dict[str, Any],
        is_hovered: bool,
        is_selected: bool,
        is_previewing: bool,
        is_in_pool: bool = False,
        hover_scale: float = 1.0,
        transition: Optional[_StateTransition] = None,
        hover_overlay_progress: float = 1.0,
    ) -> None:
        colors = _get_colors()
        config = self._get_scaled_config(LIST_CONFIG)
        padding = config["padding"]
        radius = config["radius"]
        gap = config["gap"]
        media_size = config["media_size"]

        rx = rect.x()
        ry = rect.y()
        w = rect.width()
        h = rect.height()
        card_rect = QRectF(rx, ry, w, h)

        # 状态表面（边框+背景）：无过渡按状态直绘；有过渡颜色插值/交叉淡化
        if transition is not None:
            border_width = transition.from_v.width + (
                transition.to_v.width - transition.from_v.width
            ) * self._ease_out_cubic(transition.t)
        elif is_previewing:
            border_width = 2
        else:
            border_width = 1

        # 内缩 border_width/2 绘制，避免边框被 item 的 clipRect 裁切
        # （参考 FileBlockCard._paint_card 的 adjusted 内缩方案）
        draw_rect = card_rect.adjusted(
            border_width / 2.0,
            border_width / 2.0,
            -border_width / 2.0,
            -border_width / 2.0,
        )
        self._paint_state_surface(
            painter, draw_rect, radius, is_previewing, is_in_pool, transition
        )

        # hover 反馈（所有状态统一）：叠加 25% 主题色覆盖层（透明度过渡动画）
        if is_hovered or hover_overlay_progress > 0.003:
            painter.setPen(Qt.NoPen)
            painter.setBrush(self._scaled_color(colors["hover_overlay"], hover_overlay_progress))
            painter.drawRoundedRect(draw_rect, radius, radius)

        # Media 区域（左）— 无灰色背景填充，图标直接绘制并填充满整个区域
        media_x = rx + padding
        media_y = ry + (h - media_size) / 2.0

        icon_pixmap = file_info.get("icon_pixmap")
        if icon_pixmap and not icon_pixmap.isNull():
            self._draw_icon_pixmap(
                painter,
                icon_pixmap,
                QRectF(media_x, media_y, media_size, media_size),
                hover_scale=hover_scale,
            )
        else:
            suffix = file_info.get("suffix", "")
            is_dir = file_info.get("is_dir", False)
            icon_char = "D" if is_dir else (suffix[0].upper() if suffix else "?")
            # 字号按放大后的图标尺寸比例计算，视觉占比与填满的图标一致
            icon_font_size = max(config["icon_size"], int(media_size * 0.6 * _MEDIA_ICON_SCALE * hover_scale))
            painter.setFont(QFont("Segoe UI", icon_font_size, QFont.Bold))
            painter.setPen(colors["icon"])
            painter.drawText(QRectF(media_x, media_y, media_size, media_size), Qt.AlignCenter, icon_char)

        # 文字区域（右）
        text_x = media_x + media_size + gap
        text_y = ry + padding
        text_w = w - padding * 2 - media_size - gap
        text_h = h - padding * 2
        self._draw_text(painter, QRectF(text_x, text_y, text_w, text_h), config, file_info)

    # ── 文字绘制 ──────────────────────────────────────────────────────────

    @staticmethod
    def _draw_text(
        painter: QPainter,
        rect: QRectF,
        config: Dict[str, Any],
        file_info: Dict[str, Any],
        align: int = Qt.AlignLeft,
    ) -> None:
        colors = _get_colors()
        name = file_info.get("name", "")

        font_key = (config["title_size"], config["title_weight"])
        font = _FONT_CACHE.get(font_key)
        if font is None:
            font = QFont("Microsoft YaHei UI", config["title_size"], config["title_weight"])
            _FONT_CACHE[font_key] = font
        painter.setFont(font)
        painter.setPen(colors["title"])
        fm = _FONT_METRICS_CACHE.get(font_key)
        if fm is None:
            fm = QFontMetrics(font)
            _FONT_METRICS_CACHE[font_key] = fm

        max_w = int(rect.width())
        line_height = fm.height()
        spacing = 2  # 行间距
        two_line_h = line_height * 2 + spacing

        # 单行能放下 → 在双行区域内垂直居中
        if fm.horizontalAdvance(name) <= max_w:
            y_offset = int((two_line_h - line_height) / 2)
            painter.drawText(
                QRectF(rect.x(), rect.y() + y_offset, max_w, line_height),
                align | Qt.AlignVCenter,
                name,
            )
            return

        # 双行：第一行尽量放满，第二行省略。
        # 二分查找第一行能容纳的最大字符数（替代逐字符递减线性扫描，
        # 将每次绘制的测量次数从 O(n) 降到 O(log n)）。
        lo, hi = 0, len(name)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if fm.horizontalAdvance(name[:mid]) <= max_w:
                lo = mid
            else:
                hi = mid - 1
        first_line = name[:lo]

        painter.drawText(
            QRectF(rect.x(), rect.y(), max_w, line_height),
            align | Qt.AlignTop,
            first_line,
        )

        remaining = name[len(first_line):].strip()
        if remaining:
            second_line = fm.elidedText(remaining, Qt.ElideRight, max_w)
            painter.drawText(
                QRectF(rect.x(), rect.y() + line_height + spacing, max_w, line_height),
                align | Qt.AlignTop,
                second_line,
            )
