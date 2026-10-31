"""Styled music info panel for audio preview mode.

Sopeek - 多功能文件预览与管理工具
Copyright (c) 2026 Dorufoc <dorufoc@outlook.com>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFont, QFontMetrics, QPixmap
from PySide6.QtWidgets import (
    QLabel,
    QHBoxLayout,
    QVBoxLayout,
    QSizePolicy,
    QWidget,
)

from sopeek.core._paths import icons_dir
from sopeek.core.preview.svg_renderer import SvgRenderer
from sopeek.ui.theme.app_stylesheet import register_widget_qss
from theme import tm


class StyledMusicInfoPanel(QWidget):
    """Music information panel for audio preview.

    Displays a cover pixmap on the left (or a fallback SVG placeholder) and
    the track title plus artist stacked on the right. Long text is elided with
    ``Qt.ElideRight``. The panel uses a translucent background so it can be
    composited over a fluid background without obscuring it.

    Scaling:
        面板监听父控件（音频区域，与流体背景同尺寸）的 resize，按**固定面积
        占比**换算封面边长（面积比 ``_AREA_RATIO`` 恒定），并让边距、间距、
        字号、文本省略宽度全部按封面边长等比缩放；面板尺寸随之固定，由外部
        布局居中。这样内嵌预览与全屏预览下封面/文字的视觉占比保持一致。
    """

    # ── 基准尺寸（未收到参考尺寸时的默认值，逻辑像素）──
    COVER_SIZE: int = 120
    H_MARGIN: int = 24
    V_MARGIN: int = 16
    H_SPACING: int = 16
    TEXT_SPACING: int = 8
    TITLE_FONT_SIZE: int = 16
    ARTIST_FONT_SIZE: int = 13

    # ── 自适应比例（均以封面边长为基准）──
    #: 封面面积 / 参考区域面积。用面积而不是边长，才能保证区域宽高比变化时
    #: 封面仍占相同面积比例（短边比例会随宽高比漂移）。
    _AREA_RATIO: float = 0.055
    _COVER_MIN_SIDE_RATIO: float = 0.24
    _COVER_MAX_SIDE_RATIO: float = 0.52
    _COVER_MIN_PX: int = 56
    _COVER_MAX_PX: int = 460
    #: 面板宽 / 封面边长。2.4 时文本区约 0.87×封面，可完整容纳 4 个中文字符
    #: （字号是封面的 0.178 倍），避免默认比例下每首歌标题都被省略号截断。
    _PANEL_WIDTH_PER_COVER: float = 2.4
    _H_MARGIN_PER_COVER: float = 0.20
    _V_MARGIN_PER_COVER: float = 0.133
    _H_SPACING_PER_COVER: float = 0.133
    _TEXT_SPACING_PER_COVER: float = 0.067
    _TITLE_SIZE_PER_COVER: float = 0.178
    _ARTIST_SIZE_PER_COVER: float = 0.144
    _MIN_TITLE_PX: int = 10
    _MIN_ARTIST_PX: int = 9

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the music info panel.

        Args:
            parent: Optional parent widget. 提供时监听其 resize 作为缩放参考。
        """
        super().__init__(parent)

        self._raw_title: str = ""
        self._raw_artist: str = ""
        self._elide_enabled: bool = True
        self._elide_mode: Qt.TextElideMode = Qt.TextElideMode.ElideRight
        self._placeholder_pixmap: QPixmap = QPixmap()
        # 封面当前是否显示占位图：主题变化时仅刷新占位图，不覆盖真实封面。
        self._use_placeholder: bool = True
        #: 真实封面原图（未缩放），尺寸变化时按新尺寸重采样。
        self._cover_source: QPixmap | None = None

        # 当前生效的尺寸（初始为基准值，收到参考尺寸后按比例重算）
        self._cover_px: int = self.COVER_SIZE
        self._panel_width: int = int(self.COVER_SIZE * self._PANEL_WIDTH_PER_COVER)
        self._text_width: int = 0

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

        self._init_ui()
        self._apply_scale()
        # 占位图含主题色替换（#0a59f7 → accent），明暗/强调色变化后需
        # 重渲染，否则一直显示旧配色。
        tm.theme_changed.connect(self._on_theme_changed)
        tm.colors_updated.connect(self._on_theme_changed)

        # 跟随父控件（音频区域）尺寸自适应；父控件即流体背景宿主，
        # 因此封面与文字始终按同一套比例随背景伸缩。
        if parent is not None:
            parent.installEventFilter(self)
            self._apply_reference_size(parent.width(), parent.height())

    def _init_ui(self) -> None:
        """Build the panel layout."""
        self._root_layout = QHBoxLayout(self)
        self._root_layout.setContentsMargins(
            self.H_MARGIN, self.V_MARGIN, self.H_MARGIN, self.V_MARGIN
        )
        self._root_layout.setSpacing(self.H_SPACING)

        self._cover_label = QLabel()
        self._cover_label.setFixedSize(self.COVER_SIZE, self.COVER_SIZE)
        self._cover_label.setScaledContents(True)
        self._cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        register_widget_qss(self._cover_label,("background: transparent;"))
        self._root_layout.addWidget(self._cover_label)

        self._text_container = QWidget()
        self._text_container.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground, True
        )
        self._text_container.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground, False
        )
        self._text_layout = QVBoxLayout(self._text_container)
        self._text_layout.setContentsMargins(0, 0, 0, 0)
        self._text_layout.setSpacing(self.TEXT_SPACING)
        self._text_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self._title_label = QLabel("")
        title_font = QFont("Microsoft YaHei UI", self.TITLE_FONT_SIZE)
        title_font.setBold(True)
        self._title_label.setFont(title_font)
        register_widget_qss(self._title_label,(
            f"background: transparent; color: {tm.text.name()};"
        ))
        self._title_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self._title_label.setWordWrap(False)

        self._artist_label = QLabel("未知艺术家")
        artist_font = QFont("Microsoft YaHei UI", self.ARTIST_FONT_SIZE)
        self._artist_label.setFont(artist_font)
        register_widget_qss(self._artist_label,(
            f"background: transparent; color: {tm.qss_color(tm.text_secondary)};"
        ))
        self._artist_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self._artist_label.setWordWrap(False)

        self._text_layout.addWidget(self._title_label)
        self._text_layout.addWidget(self._artist_label)
        self._text_layout.addStretch(1)

        self._root_layout.addWidget(self._text_container, stretch=1)

    # ------------------------------------------------------------------
    # 自适应缩放
    # ------------------------------------------------------------------

    def eventFilter(self, watched, event) -> bool:
        """父控件（音频区域）尺寸变化时重新计算封面/字号。

        Args:
            watched: 被监听对象。
            event: 事件对象。

        Returns:
            bool: 是否吞掉事件（始终交回基类）。
        """
        if (
            watched is self.parentWidget()
            and event.type() == QEvent.Type.Resize
        ):
            self._apply_reference_size(watched.width(), watched.height())
        return super().eventFilter(watched, event)

    def _apply_reference_size(self, width: int, height: int) -> None:
        """按参考区域尺寸重算封面边长与面板宽度。

        Args:
            width: 参考区域（音频页/流体背景）宽度，逻辑像素。
            height: 参考区域高度，逻辑像素。
        """
        if width <= 0 or height <= 0:
            return

        short_side = min(width, height)
        cover = math.sqrt(self._AREA_RATIO * width * height)
        cover = max(cover, short_side * self._COVER_MIN_SIDE_RATIO)
        cover = min(cover, short_side * self._COVER_MAX_SIDE_RATIO)
        cover_px = int(round(max(self._COVER_MIN_PX, min(self._COVER_MAX_PX, cover))))

        h_margin = self._scaled_margin(cover_px, self._H_MARGIN_PER_COVER)
        h_spacing = self._scaled_margin(cover_px, self._H_SPACING_PER_COVER)
        min_panel = cover_px + 2 * h_margin + h_spacing + 1
        panel_width = max(
            min_panel,
            min(int(round(cover_px * self._PANEL_WIDTH_PER_COVER)), int(width * 0.92)),
        )

        if (cover_px, panel_width) == (self._cover_px, self._panel_width):
            return
        self._cover_px = cover_px
        self._panel_width = panel_width
        self._apply_scale()

    @staticmethod
    def _scaled_margin(cover_px: int, ratio: float) -> int:
        """按封面边长换算最小 4px 的边距/间距。"""
        return max(4, int(round(cover_px * ratio)))

    def _apply_scale(self) -> None:
        """把当前封面边长应用到边距、字号、文本宽度与面板固定尺寸。"""
        cover = self._cover_px
        h_margin = self._scaled_margin(cover, self._H_MARGIN_PER_COVER)
        v_margin = self._scaled_margin(cover, self._V_MARGIN_PER_COVER)
        h_spacing = self._scaled_margin(cover, self._H_SPACING_PER_COVER)
        text_spacing = self._scaled_margin(cover, self._TEXT_SPACING_PER_COVER)

        self._root_layout.setContentsMargins(h_margin, v_margin, h_margin, v_margin)
        self._root_layout.setSpacing(h_spacing)
        self._text_layout.setSpacing(text_spacing)
        self._cover_label.setFixedSize(cover, cover)

        title_px = max(self._MIN_TITLE_PX, int(round(cover * self._TITLE_SIZE_PER_COVER)))
        artist_px = max(
            self._MIN_ARTIST_PX, int(round(cover * self._ARTIST_SIZE_PER_COVER))
        )
        title_font = self._title_label.font()
        title_font.setPixelSize(title_px)
        self._title_label.setFont(title_font)
        artist_font = self._artist_label.font()
        artist_font.setPixelSize(artist_px)
        self._artist_label.setFont(artist_font)

        self._text_width = max(
            1, self._panel_width - cover - 2 * h_margin - h_spacing
        )
        self.setFixedSize(self._panel_width, cover + 2 * v_margin)

        # 占位图是矢量：按新尺寸重渲染；真实封面用原图重新采样，
        # 避免 QLabel.setScaledContents 把 120px 的图硬拉到全屏尺寸而糊化。
        self._load_placeholder()
        self._refresh_cover()
        self._refresh_text()

    def _load_placeholder(self) -> None:
        """（重）渲染主题化 SVG 占位图并按需回填封面。

        走 ``SvgRenderer`` 的换色管线（``#0a59f7`` → accent 等主题令牌），
        保证占位图跟随主题色；文件缺失/渲染失败时退回 ``tm.track_fill``
        纯色填充，保证封面区非空。SVG 是矢量，按当前封面边长重渲染，
        放大到全屏也不会模糊。
        """
        placeholder_path = icons_dir() / "音乐_playing.svg"
        size = max(1, self._cover_px)
        pixmap = QPixmap()
        if placeholder_path.exists():
            pixmap = SvgRenderer.render_svg_to_exact_pixmap(
                str(placeholder_path),
                icon_width=size,
                icon_height=size,
            )
        if pixmap.isNull():
            pixmap = QPixmap(size, size)
            pixmap.fill(tm.track_fill)
        self._placeholder_pixmap = pixmap
        if self._use_placeholder:
            self._cover_label.setPixmap(pixmap)

    def _refresh_cover(self) -> None:
        """按当前封面边长重采样真实封面（保留原图，避免反复拉伸发糊）。"""
        source = self._cover_source
        if self._use_placeholder or source is None or source.isNull():
            return
        dpr = float(self.devicePixelRatioF())
        target = max(1, int(round(self._cover_px * dpr)))
        scaled = source.scaled(
            target,
            target,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(dpr)
        self._cover_label.setPixmap(scaled)

    def _on_theme_changed(self, *_args) -> None:
        """主题/配色变化：重渲染主题化占位图（不覆盖真实封面）。

        Args:
            *_args: 主题信号附带参数（未使用）。
        """
        self._load_placeholder()

    def set_title(self, title: str) -> None:
        """Set the track title.

        Args:
            title: Track title text. Empty strings are preserved as empty.
        """
        self._raw_title = title
        self._refresh_text()

    def set_artist(self, artist: str) -> None:
        """Set the artist name.

        Args:
            artist: Artist name. Empty or whitespace-only strings are shown as
                ``未知艺术家``.
        """
        self._raw_artist = artist
        self._refresh_text()

    def set_cover_pixmap(self, pixmap: QPixmap | None) -> None:
        """Set the cover pixmap, or restore the placeholder when ``None``.

        Args:
            pixmap: Cover image, or ``None`` to fall back to the placeholder.
        """
        if pixmap is not None and not pixmap.isNull():
            self._use_placeholder = False
            self._cover_source = QPixmap(pixmap)
            self._refresh_cover()
        else:
            self._use_placeholder = True
            self._cover_source = None
            self._cover_label.setPixmap(self._placeholder_pixmap)

    def set_placeholder(self) -> None:
        """Restore the default SVG placeholder cover."""
        self._use_placeholder = True
        self._cover_source = None
        self._cover_label.setPixmap(self._placeholder_pixmap)

    def clear(self) -> None:
        """Reset title, artist and cover back to their initial states."""
        self.set_title("")
        self.set_artist("")
        self.set_placeholder()

    def resizeEvent(self, event) -> None:
        """Re-elide labels when the panel size changes."""
        super().resizeEvent(event)
        self._refresh_text()

    def changeEvent(self, event) -> None:
        """DPI 变化（如跨屏拖动）时按新 DPR 重采样封面/占位图。"""
        dpr_change = getattr(QEvent.Type, "DevicePixelRatioChange", None)
        if dpr_change is not None and event.type() == dpr_change:
            self._load_placeholder()
            self._refresh_cover()
        super().changeEvent(event)

    def _refresh_text(self) -> None:
        """Refresh visible label text, applying right-side elision if needed."""
        title = self._raw_title
        artist = self._raw_artist.strip() or "未知艺术家"

        # 用按比例算出的文本区宽度（不读 self.width()），避免“面板尺寸依赖
        # 文本宽度、文本宽度又依赖面板尺寸”的循环。
        available_width = self._text_width
        if available_width > 0:
            title_metrics = QFontMetrics(self._title_label.font())
            title = title_metrics.elidedText(
                title, self._elide_mode, available_width
            )
            artist_metrics = QFontMetrics(self._artist_label.font())
            artist = artist_metrics.elidedText(
                artist, self._elide_mode, available_width
            )

        self._title_label.setText(title)
        self._artist_label.setText(artist)
