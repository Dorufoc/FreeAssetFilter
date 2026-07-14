"""
PDF 预览器布局 — 顶栏（48px 固定高度）+ 内容区（自适应拉伸）
"""

import sys
from pathlib import Path
from typing import Any, Optional

# 独立运行时的 sys.path 引导（在模块级导入前执行）
_this_file = Path(__file__).resolve()
_ui_root = str(_this_file.parent.parent.parent)  # freeassetfilter/ui/
if _ui_root not in sys.path:
    sys.path.insert(0, _ui_root)
_project_root = str(_this_file.parent.parent.parent.parent.parent)  # 项目根
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QApplication, QLineEdit,
    QPushButton, QStackedLayout,
)
from PySide6.QtCore import Qt, Signal, QEvent, QPoint, QRect, QRectF, QTimer, QPropertyAnimation, QEasingCurve, QSize
from PySide6.QtGui import QFont, QFontMetrics, QMouseEvent, QPainter, QPainterPath, QPen, QColor, QPaintEvent, QPixmap, QImage

from theme import tm
from components.styled_button import StyledButton
from components.styled_drawer import StyledDrawer
from components.styled_number_input import StyledNumberInput
from freeassetfilter.core._paths import icons_dir
from freeassetfilter.components.native_pdf_renderer import NativePdfRenderer
from freeassetfilter.ui.components.styled_scroll_area import StyledScrollArea
from freeassetfilter.ui.components.styled_slider import StyledSlider


class _ToolbarFrame(QFrame):
    """顶栏框架 —— 页面标签通过布局居中，操作按钮在 resizeEvent 中绝对定位到两侧。

    这样页码标签是在整个顶栏宽度上真正居中，不会被两侧按钮挤偏。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._left_buttons: list[QWidget] = []
        self._right_buttons: list[QWidget] = []

    def add_left_button(self, btn: QWidget) -> None:
        """注册一个左侧按钮，将其父对象设为此顶栏并在下次布局时自动定位。"""
        self._left_buttons.append(btn)
        btn.setParent(self)

    def add_right_button(self, btn: QWidget) -> None:
        """注册一个右侧按钮，将其父对象设为此顶栏并在下次布局时自动定位。"""
        self._right_buttons.append(btn)
        btn.setParent(self)

    def resizeEvent(self, event) -> None:
        """每次大小变化时将按钮固定到两侧，不影响中间布局的居中计算。"""
        super().resizeEvent(event)
        # 左侧按钮（从左往右排列）
        left = 8  # 左侧内边距 8px
        for btn in self._left_buttons:
            btn.move(left, (self.height() - btn.height()) // 2)
            left = btn.geometry().right() + 6  # 按钮间距 6px
        # 右侧按钮（从右往左排列）
        right = self.width() - 8  # 右侧内边距 8px
        for btn in reversed(self._right_buttons):
            btn.move(right - btn.width(), (self.height() - btn.height()) // 2)
            right = btn.geometry().left() - 6  # 按钮间距 6px


class _ZoomPopup(QWidget):
    """缩放弹出面板：含横向滑动条 + StyledButton 显示百分比。"""

    def __init__(self, parent=None):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._parent_layout = parent
        self._radius = 8
        self._padding = 8
        self._closing = False

        # 动画
        self._fade = QPropertyAnimation(self, b"windowOpacity")
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._slide = QPropertyAnimation(self, b"geometry")
        self._slide.setEasingCurve(QEasingCurve.OutCubic)

        # 内容
        self._zoom_value = 100  # 百分比（100 = 自适应）

        layout = QHBoxLayout(self)
        layout.setContentsMargins(self._padding, self._padding, self._padding, self._padding)
        layout.setSpacing(8)

        # 百分比按钮（点击重置100%）
        self._pct_btn = StyledButton("100%", variant="ghost", size="sm")
        self._pct_btn.setFixedHeight(28)
        self._pct_btn.clicked.connect(self._reset_zoom)
        layout.addWidget(self._pct_btn)

        # 横向滑动条
        self._slider = StyledSlider(value=0.5, size="sm", orientation=Qt.Horizontal)
        self._slider.setFixedWidth(140)
        self._slider.value_changed.connect(self._on_slider_changed)
        layout.addWidget(self._slider)

    def paintEvent(self, event: QPaintEvent):
        """绘制半透明圆角背景 + 边框（与视频播放器弹窗一致）。"""
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = self._radius

        p.setPen(Qt.NoPen)
        p.setBrush(tm.alpha_of(tm.surface, 85))
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)

        p.setPen(QPen(tm.alpha_of(tm.mid, 30), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), r, r)
        p.end()

    def show_animated(self, anchor_br: QPoint):
        """从按钮右下角向下展开，弹窗右对齐。"""
        pw = 220
        ph = 48
        margin_r = int(5 * self._parent_layout._dpi_scale) if self._parent_layout else 5
        x = anchor_br.x() - pw - margin_r
        y = anchor_br.y() + int(7 * self._parent_layout._dpi_scale) if self._parent_layout else anchor_br.y() + 7

        screen = QApplication.primaryScreen()
        if screen:
            sg = screen.availableGeometry()
            x = max(sg.x() + 8, min(x, sg.right() - pw - 8))

        start_h = 10
        self.setGeometry(x, y, pw, start_h)
        self.setWindowOpacity(0.0)
        super().show()
        self.raise_()
        self.activateWindow()

        self._fade.stop()
        self._fade.setDuration(180)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)

        self._slide.stop()
        self._slide.setDuration(200)
        self._slide.setStartValue(self.geometry())
        self._slide.setEndValue(QRectF(x, y, pw, ph))

        self._fade.start()
        self._slide.start()

    def close_animated(self):
        if self._closing:
            return
        self._closing = True
        self._fade.stop()
        self._fade.setDuration(120)
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)

        self._slide.stop()
        self._slide.setDuration(120)
        self._slide.setStartValue(self.geometry())
        end = QRectF(self.geometry())
        end.setHeight(8)
        self._slide.setEndValue(end.toRect())

        self._slide.finished.connect(self._close_and_reset)
        self._fade.start()
        self._slide.start()

    def _close_and_reset(self):
        self._slide.finished.disconnect(self._close_and_reset)
        self.close()
        self._closing = False

    def _on_slider_changed(self, val: float):
        """滑动条 0.0~1.0 → 缩放 50%~300%"""
        pct = 50 + int(val * 250)
        self._zoom_value = max(50, min(300, pct))
        self._pct_btn.setText(f"{self._zoom_value}%")
        if self._parent_layout and hasattr(self._parent_layout, '_renderer'):
            r = self._parent_layout._renderer
            base = r._view.get_zoom_for_scale(100) if hasattr(r._view, 'get_zoom_for_scale') else r._view.zoom_level
            r.set_zoom(base * self._zoom_value / 100.0)

    def _reset_zoom(self):
        self._zoom_value = 100
        self._pct_btn.setText("100%")
        self._slider._value = 0.5
        self._slider.update()
        if self._parent_layout and hasattr(self._parent_layout, '_renderer'):
            self._parent_layout._renderer.fit_to_page()

    def sync_from_renderer(self) -> None:
        """从渲染器的当前缩放级别同步滑条位置和百分比显示。"""
        layout = self._parent_layout
        if layout is None or not hasattr(layout, '_renderer') or layout._renderer is None:
            return
        r = layout._renderer
        if r._view is None:
            return
        current = r._view.zoom_level
        base = r._view.get_zoom_for_scale(100) if hasattr(r._view, 'get_zoom_for_scale') else current
        if base <= 0:
            return
        pct = int(current / base * 100)
        pct = max(50, min(300, pct))
        self._zoom_value = pct
        self._pct_btn.setText(f"{pct}%")
        # slider 0.0~1.0 → 50%~300%
        val = (pct - 50) / 250.0
        self._slider.value = val
        self._slider.update()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._closing = False


class _IndexPageThumbnail(QWidget):
    """PDF 索引缩略图 — 圆角位图 + 当前页描边 + 页码徽章"""

    pageClicked = Signal(int)

    def __init__(
        self,
        pixmap: QPixmap,
        page_number: int,
        is_current: bool = False,
        thumbnail_width: int = 140,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._page_number = page_number
        self._is_current = is_current
        self._thumb_w = thumbnail_width

        # Maintain aspect ratio
        if pixmap and not pixmap.isNull():
            pw = pixmap.width() / max(pixmap.devicePixelRatio(), 1.0)
            ph = pixmap.height() / max(pixmap.devicePixelRatio(), 1.0)
            ratio = pw / ph if ph > 0 else 1.0
            self._thumb_h = int(self._thumb_w / ratio)
        else:
            self._thumb_h = 180

        self._pixmap = pixmap

        total_w = self._thumb_w + 8   # 4px margin each side
        total_h = self._thumb_h + 8 + 20  # 4px margin + badge room
        self.setFixedSize(total_w, total_h)
        self.setCursor(Qt.PointingHandCursor)

    def set_current(self, is_current: bool) -> None:
        if self._is_current != is_current:
            self._is_current = is_current
            self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self.pageClicked.emit(self._page_number)
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        margin = 4
        radius = 8
        x, y = margin, margin
        w, h = self._thumb_w, self._thumb_h
        card_rect = QRectF(x, y, w, h)

        # ── White background rounded rect ──
        painter.setBrush(Qt.white)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(card_rect, radius, radius)

        # ── Page pixmap clipped to rounded rect ──
        if self._pixmap and not self._pixmap.isNull():
            clip_path = QPainterPath()
            clip_path.addRoundedRect(card_rect, radius, radius)
            painter.setClipPath(clip_path)
            painter.drawPixmap(
                int(x), int(y), int(w), int(h),
                self._pixmap,
            )
            painter.setClipping(False)

        # ── Current page: 4px accent border ──
        if self._is_current:
            border_pen = QPen(tm.accent, 4.0)
            border_pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(border_pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(card_rect, radius, radius)

        # ── Page number badge (bottom-right) ──
        badge_text = str(self._page_number + 1)  # 1-based display
        font = QFont("Microsoft YaHei UI", 10, QFont.Weight.Medium)
        painter.setFont(font)
        fm = QFontMetrics(font)
        badge_w = fm.horizontalAdvance(badge_text) + 12
        badge_h = 18
        badge_x = x + w - badge_w - 5
        badge_y = y + h - badge_h - 5

        if self._is_current:
            badge_bg = tm.accent
            badge_fg = QColor("#ffffff")
        else:
            badge_bg = tm.alpha_of(tm.mid, 80)
            badge_fg = QColor("#ffffff")

        painter.setPen(Qt.NoPen)
        painter.setBrush(badge_bg)
        painter.drawRoundedRect(QRectF(badge_x, badge_y, badge_w, badge_h), 4, 4)

        painter.setPen(badge_fg)
        painter.drawText(
            QRectF(badge_x, badge_y, badge_w, badge_h),
            Qt.AlignCenter,
            badge_text,
        )

        painter.end()


class PdfPreviewerLayout(QWidget):
    """
    PDF 预览器布局

    顶栏固定 48px（与文件选择器底栏高度一致），用于放置一排操作按钮；
    其余区域为内容区，后续接入 PDF 渲染组件。

    Signals:
        close_requested: 关闭预览请求信号
    """

    close_requested = Signal()

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        dpi_scale: Optional[float] = None,
        global_font: Optional[QFont] = None,
        settings_manager: Optional[Any] = None,
        standalone: bool = False,
    ) -> None:
        super().__init__(parent)
        self._dpi_scale = dpi_scale or 1.0
        self._global_font = global_font or QFont("Segoe UI", 9)
        self._settings_manager = settings_manager
        self._standalone = standalone

        self._current_page = 1
        self._total_pages = 1
        self._fullscreen: bool = False
        self._saved_geometry = None
        self._thumbnail_widgets: list[_IndexPageThumbnail] = []

        self._init_ui()
        self._init_index_drawer()
        # StyledDrawer 创建后默认跟随 parent 可见，但其 backdrop 会覆盖内容区拦截鼠标事件。
        # 必须显式隐藏，等用户点击索引按钮时才通过 open_drawer() 显示。
        self._index_drawer.hide()
        self._init_ai_drawer()
        self._ai_drawer.hide()
        self._connect_theme()
        self._connect_focus_tracking()

    def _init_ui(self) -> None:
        """初始化顶栏 + 内容区布局。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 顶栏（固定高度 48px，与文件选择器底栏一致）
        self._top_bar = _ToolbarFrame()
        self._top_bar.setObjectName("PdfPreviewerTopBar")
        self._top_bar.setFixedHeight(48)
        self._build_top_bar()
        layout.addWidget(self._top_bar)

        # 内容区（自适应拉伸）— 使用 QStackedLayout 模仿 video_player_layout
        # index 0 = 渲染器 (NativePdfRenderer)
        # index 1 = 覆盖层（未加载时显示 + standalone 的"选择文件"按钮）
        self._content_area = QFrame()
        self._content_area.setObjectName("PdfPreviewerContent")
        self._content_stack = QStackedLayout(self._content_area)
        self._content_stack.setContentsMargins(0, 0, 0, 0)

        # ── index 0：PDF 渲染器 + 双 StyledScrollBar ──
        # QGridLayout: (0,0)=renderer, (0,1)=vbar, (1,0)=hbar, (1,1)=corner
        self._scroll_container = QWidget()
        from PySide6.QtWidgets import QGridLayout
        scroll_grid = QGridLayout(self._scroll_container)
        scroll_grid.setContentsMargins(0, 0, 0, 0)
        scroll_grid.setSpacing(0)

        self._renderer = NativePdfRenderer(
            self._content_area,
            settings_manager=self._settings_manager,
            dpi_scale=self._dpi_scale,
            global_font=self._global_font,
        )
        scroll_grid.addWidget(self._renderer, 0, 0)

        from freeassetfilter.ui.components.styled_scroll_area import StyledScrollBar
        self._vbar = StyledScrollBar(orientation=Qt.Vertical)
        self._vbar.setRange(0, 0)
        self._vbar.setMaximumWidth(12)
        self._vbar.valueChanged.connect(self._on_scroll_changed)
        scroll_grid.addWidget(self._vbar, 0, 1)

        self._hbar = StyledScrollBar(orientation=Qt.Horizontal)
        self._hbar.setRange(0, 0)
        self._hbar.setMaximumHeight(12)
        self._hbar.valueChanged.connect(self._on_hscroll_changed)
        scroll_grid.addWidget(self._hbar, 1, 0)

        # Corner spacer
        corner = QWidget()
        corner.setFixedSize(self._hbar.height(), self._vbar.width())
        scroll_grid.addWidget(corner, 1, 1)

        self._content_stack.addWidget(self._scroll_container)

        # 用 _WheelSmoothScrollFilter 接管水平和垂直滚轮事件
        from freeassetfilter.ui.components.styled_scroll_area import _WheelSmoothScrollFilter
        self._scroll_container.verticalScrollBar = lambda: self._vbar  # type: ignore[attr-defined]
        self._scroll_container.horizontalScrollBar = lambda: self._hbar  # type: ignore[attr-defined]
        self._wheel_filter = _WheelSmoothScrollFilter(self._scroll_container, self._renderer)
        self._renderer.installEventFilter(self._wheel_filter)

        # Connect signals
        self._renderer.page_changed.connect(self._on_renderer_page_changed)
        self._renderer.total_pages_changed.connect(self.set_total_pages)
        self._renderer.zoom_changed.connect(self._update_scroll_range)

        # ── index 1：覆盖层（未加载文件时显示）──
        self._overlay = QWidget()
        self._overlay.setObjectName("PdfPreviewerOverlay")
        overlay_layout = QVBoxLayout(self._overlay)
        overlay_layout.setAlignment(Qt.AlignCenter)
        overlay_layout.setSpacing(16)

        # 提示文字
        self._placeholder = QLabel("打开 PDF 文件开始预览")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setStyleSheet("color: #888; font-size: 14px; background: transparent;")
        overlay_layout.addWidget(self._placeholder)

        # "选择文件"按钮（仅 standalone 模式，视频播放器模式）
        self._browse_btn: Optional[QPushButton] = None
        if self._standalone:
            self._browse_btn = QPushButton("选择 PDF 文件")
            self._browse_btn.setFixedSize(160, 40)
            self._browse_btn.setCursor(Qt.PointingHandCursor)
            self._browse_btn.clicked.connect(self._on_browse_file)
            self._style_browse_button()
            overlay_layout.addWidget(self._browse_btn, alignment=Qt.AlignCenter)

        self._content_stack.addWidget(self._overlay)

        # 初始显示覆盖层（index 1）
        self._content_stack.setCurrentIndex(1)

        layout.addWidget(self._content_area, stretch=1)

        # 缩放弹出面板（延迟初始化）
        self._zoom_popup: Optional[_ZoomPopup] = None

        # Wire toolbar buttons
        self._zoom_btn.clicked.connect(self._on_zoom_clicked)
        self._maxsize_btn.clicked.connect(self._on_maxsize_toggle)

    def _build_top_bar(self) -> None:
        """构建顶栏：中间页码标签（点击切换为数字输入器），右侧 AI、缩放图标按钮。"""
        top_layout = QHBoxLayout(self._top_bar)
        top_layout.setContentsMargins(8, 6, 8, 6)
        top_layout.setSpacing(6)
        top_layout.setAlignment(Qt.AlignCenter)

        # 中间：页码按钮（点击切换为数字输入器）+ 数字输入器（默认隐藏）
        self._page_container = QWidget()
        page_layout = QHBoxLayout(self._page_container)
        m2 = int(2 * self._dpi_scale)
        page_layout.setContentsMargins(m2, m2, m2, m2)
        page_layout.setSpacing(6)
        page_layout.setAlignment(Qt.AlignCenter)

        self._page_button = StyledButton("1 / 1", variant="ghost", size="sm")
        self._page_button.setFixedHeight(26)
        self._page_button.clicked.connect(self._start_page_edit)
        page_layout.addWidget(self._page_button)

        self._page_input = StyledNumberInput(
            value=1, min_val=1, max_val=9999, step=1, size="sm"
        )
        # 缩小高度避免边框被裁切：30→24px，同时缩小内部子控件
        self._page_input.setFixedHeight(24)
        for child in self._page_input.findChildren(QWidget):
            if child is not self._page_input and not isinstance(child, QLineEdit):
                child.setFixedSize(24, 24)
            elif isinstance(child, QLineEdit):
                child.setFixedHeight(24)
        self._page_input.setVisible(False)
        self._page_input.value_changed.connect(self._on_page_value_changed)
        page_layout.addWidget(self._page_input)

        # 左侧：索引按钮（绝对定位，不影响居中布局）
        index_icon = str(icons_dir() / "index.svg")
        self._index_btn = StyledButton("", variant="ghost", size="sm", icon=index_icon)
        self._index_btn.setFixedSize(32, 32)
        self._index_btn.setToolTip("索引")
        self._index_btn.clicked.connect(self._toggle_index_drawer)
        self._top_bar.add_left_button(self._index_btn)

        # 左侧弹簧，将页码区域推至中间
        top_layout.addStretch(1)
        top_layout.addWidget(self._page_container)
        # 右侧弹簧，与左侧弹簧共同将页码区域居中
        top_layout.addStretch(1)

        # 右侧：AI 图标按钮（绝对定位，不影响居中布局）
        ai_icon = str(icons_dir() / "ai.svg")
        self._ai_btn = StyledButton("", variant="ghost", size="sm", icon=ai_icon)
        self._ai_btn.setFixedSize(32, 32)
        self._ai_btn.setToolTip("AI 功能")
        self._ai_btn.clicked.connect(self._on_ai_clicked)
        self._top_bar.add_right_button(self._ai_btn)

        # 右侧：缩放图标按钮（绝对定位，不影响居中布局）
        zoom_icon = str(icons_dir() / "zoom.svg")
        self._zoom_btn = StyledButton("", variant="ghost", size="sm", icon=zoom_icon)
        self._zoom_btn.setFixedSize(32, 32)
        self._top_bar.add_right_button(self._zoom_btn)

        # 右侧：最大化图标按钮（绝对定位，不影响居中布局）
        self._maxsize_icon_path = str(icons_dir() / "maxsize.svg")
        self._minisize_icon_path = str(icons_dir() / "minisize.svg")
        self._maxsize_btn = StyledButton("", variant="ghost", size="sm", icon=self._maxsize_icon_path)
        self._maxsize_btn.setFixedSize(32, 32)
        self._maxsize_btn.setToolTip("最大化")
        self._top_bar.add_right_button(self._maxsize_btn)

    def _init_index_drawer(self) -> None:
        """初始化索引侧边抽屉面板（bare 模式内部嵌入 StyledScrollArea）。"""
        self._index_drawer = StyledDrawer(
            orientation="left",
            size="sm",
            bare=True,
            parent=self._content_area,
        )
        # 移除面板自身边框，只保留背景色
        self._index_drawer._panel.setStyleSheet(
            f"#DrawerPanel {{ background-color: {tm.surface.name()}; border: none; }}"
        )
        # 覆写面板尺寸计算：视口宽度小于默认宽度时横向缩小以完整显示
        _orig_get_panel_size = self._index_drawer._get_panel_size
        def _constrained_panel_size():
            pw, ph = _orig_get_panel_size()
            available_w = self._content_area.width()
            margin = 4  # 保留 4px 边缘间隙
            max_pw = max(available_w - margin, 60)
            return min(pw, max_pw), ph
        self._index_drawer._get_panel_size = _constrained_panel_size
        # 在 bare panel 中嵌入 StyledScrollArea
        panel_layout = self._index_drawer._panel.layout()
        self._index_scroll = StyledScrollArea()
        self._index_scroll.setWidgetResizable(True)
        self._index_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._index_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # 内容容器
        self._index_content = QWidget()
        self._index_content_layout = QVBoxLayout(self._index_content)
        self._index_content_layout.setContentsMargins(6, 6, 6, 6)
        self._index_content_layout.setSpacing(6)
        self._index_content_layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        self._index_scroll.setWidget(self._index_content)
        panel_layout.addWidget(self._index_scroll)

    def _init_ai_drawer(self) -> None:
        """初始化 AI 右侧抽屉面板（bare 模式，内容留空）。"""
        self._ai_drawer = StyledDrawer(
            orientation="right",
            size="sm",
            bare=True,
            parent=self._content_area,
        )
        # 移除面板自身边框，只保留背景色
        self._ai_drawer._panel.setStyleSheet(
            f"#DrawerPanel {{ background-color: {tm.surface.name()}; border: none; }}"
        )
        # 覆写面板尺寸计算：视口宽度小于默认宽度时横向缩小以完整显示
        _orig_get_panel_size = self._ai_drawer._get_panel_size
        def _constrained_panel_size():
            pw, ph = _orig_get_panel_size()
            available_w = self._content_area.width()
            margin = 4  # 保留 4px 边缘间隙
            max_pw = max(available_w - margin, 60)
            return min(pw, max_pw), ph
        self._ai_drawer._get_panel_size = _constrained_panel_size
        # 占位文本提示
        self._ai_placeholder = QLabel("敬请期待")
        self._ai_placeholder.setAlignment(Qt.AlignCenter)
        self._ai_placeholder.setWordWrap(True)
        self._ai_placeholder.setStyleSheet(
            f"color: {tm.mid.name()}; font-size: 14px; background: transparent;"
            " padding: 24px;"
        )
        panel_layout = self._ai_drawer._panel.layout()
        panel_layout.addStretch()
        panel_layout.addWidget(self._ai_placeholder, alignment=Qt.AlignCenter)
        panel_layout.addStretch()

    def _toggle_index_drawer(self) -> None:
        """切换索引侧边面板的展开/收起。"""
        if self._index_drawer._is_open:
            self._index_drawer.close_drawer()
        else:
            self._index_drawer.open_drawer()

    def _toggle_ai_drawer(self) -> None:
        """切换 AI 侧边面板的展开/收起。"""
        if self._ai_drawer._is_open:
            self._ai_drawer.close_drawer()
        else:
            self._ai_drawer.open_drawer()

    def _connect_theme(self) -> None:
        """连接主题切换信号。"""
        tm.theme_changed.connect(self._on_theme_changed)

    def _connect_focus_tracking(self) -> None:
        """连接应用级焦点/点击事件，用于检测数字输入器失焦。"""
        app = QApplication.instance()
        if app is not None:
            app.focusChanged.connect(self._on_app_focus_changed)
            app.installEventFilter(self)

    def _start_page_edit(self) -> None:
        """点击页码按钮时进入编辑模式。"""
        self._page_button.setVisible(False)
        self._page_input.setVisible(True)
        self._page_input.value = self._current_page

        line_edit = self._page_input.findChild(QLineEdit)
        if line_edit is not None:
            line_edit.setFocus(Qt.MouseFocusReason)
            line_edit.selectAll()

    def _update_page_button_text(self) -> None:
        """刷新页码按钮显示文本。"""
        self._page_button.setText(f"{self._current_page} / {self._total_pages}")

    def _finish_page_edit(self) -> None:
        """退出编辑模式，恢复为页码按钮显示。"""
        if self._page_input.isVisible():
            self._page_input.setVisible(False)
            self._page_button.setVisible(True)
            self._update_page_button_text()

    def _update_scroll_range_after_load(self) -> None:
        """PDF 加载完成后滚动到第一页，设置滚动条范围。"""
        if not hasattr(self, '_renderer') or self._renderer._view is None:
            return
        self._update_scroll_range(self._renderer._view.zoom_level)
        self._vbar.setValue(0)

    def _on_hscroll_changed(self, value: int) -> None:
        """横向滚动条 → 同步到渲染器的水平偏移。"""
        if hasattr(self, '_renderer') and self._renderer._view is not None:
            v = self._renderer._view
            zoom = max(v.zoom_level, 0.01)
            v.offset_x = value / zoom + v.view_width / (2.0 * zoom)
            self._renderer.update()

    def _on_scroll_changed(self, value: int) -> None:
        """滚动条位置变化 → 同步到渲染器的视图偏移，并更新页码。"""
        if hasattr(self, '_renderer') and self._renderer._view is not None:
            v = self._renderer._view
            zoom = max(v.zoom_level, 0.01)
            # scrollbar pixel → absolute document space (中心模型)
            v.offset_y = value / zoom + v.view_height / (2.0 * zoom)
            # 边界限制：页面超出视口时 ±30px，否则居中
            self._renderer._clamp_offset(zoom)
            # 检测当前视口中心所在页面，更新页码按钮
            if self._renderer._accum_heights:
                center_page, _ = v.absolute_to_page(v.offset_y)
                new_page = center_page + 1  # 1-based
                if new_page != self._current_page:
                    self._current_page = new_page
                    self._update_page_button_text()
                    self._update_thumbnail_highlight(center_page)
            # 提交新可见页面的渲染请求（滚动后未缓存的页面需要加载）
            self._renderer._submit_render_for_visible_pages()
            self._renderer.update()

    def _update_scroll_range(self, zoom: float) -> None:
        """zoom 变化后重新计算双滚动条范围和步长，并同步滑块到当前 offset。"""
        if not hasattr(self, '_renderer') or self._renderer._view is None:
            return
        v = self._renderer._view
        # 垂直
        if not v._accum_page_heights:
            self._vbar.setRange(0, 0)
        else:
            total_h: float = v._accum_page_heights[-1] * zoom
            view_h: int = max(v.view_height, 1)
            scroll_max: int = max(0, int(total_h - view_h))
            self._vbar.setRange(0, scroll_max)
            self._vbar.setSingleStep(20)
            self._vbar.setPageStep(view_h)
            # 同步滑块到当前 offset_y（避免缩放后滚动条位置失配导致跳变）
            new_val = int((v.offset_y - v.view_height / (2.0 * zoom)) * zoom)
            new_val = max(self._vbar.minimum(), min(self._vbar.maximum(), new_val))
            self._vbar.blockSignals(True)
            self._vbar.setValue(new_val)
            self._vbar.blockSignals(False)
        # 水平
        if not self._renderer._page_widths:
            self._hbar.setRange(0, 0)
        else:
            total_w: float = self._renderer._page_widths[0] * zoom
            view_w: int = max(v.view_width, 1)
            scroll_max: int = max(0, int(total_w - view_w))
            self._hbar.setRange(0, scroll_max)
            self._hbar.setSingleStep(20)
            self._hbar.setPageStep(view_w)
            # 同步滑块到当前 offset_x
            new_hval = int((v.offset_x - v.view_width / (2.0 * zoom)) * zoom)
            new_hval = max(self._hbar.minimum(), min(self._hbar.maximum(), new_hval))
            self._hbar.blockSignals(True)
            self._hbar.setValue(new_hval)
            self._hbar.blockSignals(False)

    def _on_renderer_page_changed(self, page: int) -> None:
        """Slot for NativePdfRenderer.page_changed signal."""
        self._current_page = page + 1  # 1-based for display
        self._update_page_button_text()
        self._update_thumbnail_highlight(page)
        # 同步滚动条位置到新页面偏移，避免触发滚动时跳回跳转前的位置
        if hasattr(self, '_renderer') and self._renderer._view is not None:
            self._update_scroll_range(self._renderer._view.zoom_level)

    def _on_maxsize_toggle(self) -> None:
        """切换全屏 / 还原窗口（参考 video_player_layout，不改变窗口 flags）。"""
        win = self.window()
        if win is None:
            return
        if not self._fullscreen:
            self._saved_geometry = win.geometry()
            win.showFullScreen()
            self._maxsize_btn.set_svg_icon(self._minisize_icon_path)
            self._maxsize_btn.setToolTip("还原")
            self._fullscreen = True
        else:
            win.showNormal()
            if self._saved_geometry:
                win.setGeometry(self._saved_geometry)
            self._maxsize_btn.set_svg_icon(self._maxsize_icon_path)
            self._maxsize_btn.setToolTip("最大化")
            self._fullscreen = False

    def _on_app_mouse_press(self, event: QMouseEvent) -> None:
        """全局鼠标点击：点击菜单外部时关闭缩放弹窗。"""
        if self._zoom_popup is not None and self._zoom_popup.isVisible():
            popup_rect = QRect(self._zoom_popup.pos(), self._zoom_popup.size())
            if not popup_rect.contains(event.globalPos()):
                self._zoom_popup.close_animated()

    def _on_zoom_clicked(self) -> None:
        """缩放按钮点击：展开/收起缩放弹出面板。"""
        if self._zoom_popup is not None and self._zoom_popup.isVisible():
            self._zoom_popup.close_animated()
            return
        if self._zoom_popup is None:
            self._zoom_popup = _ZoomPopup(parent=self)
        # 打开前从渲染器同步当前缩放值
        self._zoom_popup.sync_from_renderer()
        # 锚点在顶栏右下角，弹窗右对齐于顶栏
        tb_br = self._top_bar.mapToGlobal(QPoint(self._top_bar.width(), self._top_bar.height()))
        self._zoom_popup.show_animated(tb_br)

    def _on_page_value_changed(self, value: int) -> None:
        """数字输入器值变化时实时跳转并更新页码按钮。"""
        self._current_page = value
        self._update_page_button_text()
        if hasattr(self, '_renderer'):
            self._renderer.go_to_page(value - 1)  # convert to 0-based

    def _on_ai_clicked(self) -> None:
        """AI 按钮点击：切换 AI 侧边面板的展开/收起。"""
        self._toggle_ai_drawer()

    def _on_app_focus_changed(self, old: Optional[QWidget], new: Optional[QWidget]) -> None:
        """焦点变化：页码编辑失焦 + 缩放弹窗关闭。"""
        # 页码编辑失焦
        if old is not None:
            if self._page_container.isAncestorOf(old) or old is self._page_container:
                if not (self._page_container.isAncestorOf(new) or new is self._page_container):
                    self._finish_page_edit()
        # 缩放弹窗关闭由 eventFilter（MouseButtonPress/Move/Resize）处理
        # 不在焦点变化中处理，避免交互时因焦点反复切换导致弹窗意外关闭

    def resizeEvent(self, event) -> None:
        """窗口尺寸变化时同步更新索引和 AI 侧边栏的遮罩和面板尺寸。"""
        super().resizeEvent(event)
        if hasattr(self, '_index_drawer') and self._index_drawer._is_open:
            self._index_drawer._update_container_geom()
            cw, ch = self._index_drawer._cw, self._index_drawer._ch
            # 更新遮罩和抽屉自身尺寸
            self._index_drawer.setGeometry(0, 0, cw, ch)
            self._index_drawer._backdrop.setGeometry(0, 0, cw, ch)
            # 侧边栏面板上下延伸、横向自适应
            pw, _ = self._index_drawer._get_panel_size()
            self._index_drawer._panel.resize(pw, ch)

        if hasattr(self, '_ai_drawer') and self._ai_drawer._is_open:
            self._ai_drawer._update_container_geom()
            cw, ch = self._ai_drawer._cw, self._ai_drawer._ch
            self._ai_drawer.setGeometry(0, 0, cw, ch)
            self._ai_drawer._backdrop.setGeometry(0, 0, cw, ch)
            pw, _ = self._ai_drawer._get_panel_size()
            self._ai_drawer._panel.resize(pw, ch)
            # 右侧面板需要重新定位到新右边缘，并更新动画目标位置
            self._ai_drawer._panel.move(cw - pw, 0)
            self._ai_drawer._start_pos = QPoint(cw, 0)
            self._ai_drawer._end_pos = QPoint(cw - pw, 0)

    def eventFilter(self, obj: Any, event: QEvent) -> bool:
        """应用级事件过滤：页码编辑失焦 + 弹窗外部点击/窗口移动/缩放关闭。"""
        # 窗口移动或缩放时关闭弹窗（但 WindowDeactivate 除外——
        # 交互缩放弹窗（Qt.Tool 独立窗口）会导致主窗口失活，这时候不应该关闭弹窗）
        if event.type() in (QEvent.Move, QEvent.Resize):
            if obj is self.window() or obj is self:
                if self._zoom_popup is not None and self._zoom_popup.isVisible():
                    self._zoom_popup.close_animated()
        if event.type() == QEvent.MouseButtonPress:
            me = event if isinstance(event, QMouseEvent) else None
            if me is not None:
                click_global = me.globalPosition().toPoint()
                # 页码输入器失焦
                if self._page_input.isVisible():
                    container_rect = QRect(
                        self._page_container.mapToGlobal(QPoint(0, 0)),
                        self._page_container.size(),
                    )
                    if not container_rect.contains(click_global):
                        self._finish_page_edit()
                # 缩放弹窗外部点击关闭
                if self._zoom_popup is not None and self._zoom_popup.isVisible():
                    pr = QRect(self._zoom_popup.pos(), self._zoom_popup.size())
                    if not pr.contains(click_global):
                        self._zoom_popup.close_animated()
        return super().eventFilter(obj, event)

    # ── 覆盖层样式（video_player_layout 模式）──

    def _style_browse_button(self) -> None:
        """应用主题色到"选择 PDF 文件"按钮（模仿 video_player_layout 模式）。"""
        if self._browse_btn is None:
            return
        btn_text = tm.mid.name()
        btn_hover_text = tm.text.name()
        btn_bg = tm.fill.name()
        btn_border = tm.alpha_of(tm.mid, 30).name()
        self._browse_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 1px solid {btn_border};
                border-radius: 8px;
                color: {btn_text};
                font-size: 13px;
                font-family: 'Microsoft YaHei UI', 'Segoe UI', sans-serif;
                padding: 0 16px;
            }}
            QPushButton:hover {{
                background: {btn_bg};
                color: {btn_hover_text};
                border: 1px solid {tm.mid.name()};
            }}
            QPushButton:pressed {{
                background: {btn_bg};
            }}
        """)

    def _on_browse_file(self) -> None:
        """打开文件选择对话框选择 PDF（仅 standalone 模式，video_player_layout 模式）。"""
        from PySide6.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 PDF 文件",
            "",
            "PDF 文件 (*.pdf);;所有文件 (*.*)",
        )
        if file_path:
            self.set_file(file_path)

    def _stop_preview(self) -> None:
        """停止预览，切换回覆盖层显示（模仿 video_player_layout 的 on_file_ended）。"""
        self._content_stack.setCurrentIndex(1)
        self._placeholder.setText("打开 PDF 文件开始预览")

    def _update_thumbnail_highlight(self, current_page: int) -> None:
        """更新缩略图列表中当前页的高亮状态。"""
        for i, thumb in enumerate(self._thumbnail_widgets):
            thumb.set_current(i == current_page)

    def set_total_pages(self, total: int) -> None:
        """设置总页数并更新显示。"""
        self._total_pages = max(1, total)
        self._page_input.max_val = self._total_pages
        if self._current_page > self._total_pages:
            self._current_page = self._total_pages
        self._update_page_button_text()

    def set_file(self, file_path: str) -> bool:
        """加载 PDF 文件。

        Args:
            file_path: 文件路径

        Returns:
            bool: 是否加载成功
        """
        success = self._renderer.load_document(file_path)
        if success:
            self._current_page = 1
            self._total_pages = self._renderer.page_count()
            self._update_page_button_text()
            self._page_input.max_val = self._total_pages
            # 切换到渲染器视图（index 0，模仿 video_player_layout set_file 模式）
            self._content_stack.setCurrentIndex(0)
            # 切换后渲染器从隐藏变为可见，尺寸从 0 变为实际值。
            # load_document 中按 width=0 计算的 zoom 极小，这里重新适配。
            QTimer.singleShot(50, self._renderer.fit_to_page)
            # 更新滚动条范围
            QTimer.singleShot(100, self._update_scroll_range_after_load)
            # Populate thumbnail drawer
            QTimer.singleShot(150, lambda: self._populate_thumbnail_drawer())
        return success

    def _populate_thumbnail_drawer(self) -> None:
        """Generate QPixmap thumbnails for all pages inside the StyledScrollArea."""
        if not hasattr(self, '_renderer') or self._renderer._doc is None:
            return

        import fitz

        doc = self._renderer._doc
        layout = self._index_content_layout

        # Clear existing thumbnails
        self._thumbnail_widgets.clear()
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        count = doc.page_count()
        for i in range(count):
            try:
                page = doc._doc.load_page(i)
                # Render at 0.25x for decent thumbnail quality
                mat = fitz.Matrix(0.25, 0.25)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
                qpix = QPixmap.fromImage(img)
            except Exception:
                qpix = QPixmap(140, 180)
                qpix.fill(Qt.lightGray)

            thumb = _IndexPageThumbnail(
                qpix, i,
                is_current=(i == self._current_page - 1),
                thumbnail_width=140,
            )
            thumb.pageClicked.connect(lambda p: self._renderer.go_to_page(p))
            self._thumbnail_widgets.append(thumb)
            layout.addWidget(thumb)

        layout.addStretch()

    def set_section_styles(self, fill_color: str, border_color: str) -> None:
        """应用面板样式（主题切换时由 MainWindow 调用）。"""
        # 顶栏控制栏：背景与边框均透明
        self._top_bar.setStyleSheet("""
            background-color: transparent;
            border: 1px solid transparent;
            border-radius: 8px;
        """)
        # 内容区：背景使用 G1（主题 surface 色），边框透明
        self._content_area.setStyleSheet(f"""
            background-color: {tm.surface.name()};
            border: 1px solid transparent;
            border-radius: 8px;
        """)
        # 覆盖层背景与内容区一致
        self._overlay.setStyleSheet(f"""
            background-color: {tm.surface.name()};
        """)

    def _on_theme_changed(self, theme_name: str) -> None:
        """主题变更时刷新样式。"""
        self._refresh_text_colors()
        self._style_browse_button()
        self.update()

    def _refresh_text_colors(self) -> None:
        """主题切换时刷新页码按钮及输入器颜色。"""
        # StyledButton 在 paintEvent 中实时读取 tm 颜色，只需触发重绘
        self._page_button.update()
        self._page_input.refresh_theme()


if __name__ == "__main__":
    app = QApplication(sys.argv)

    window = QWidget()
    window.setWindowTitle("PDF 预览器 (独立测试)")
    window.resize(960, 600)

    # 居中显示
    screen = app.primaryScreen().geometry()
    x = (screen.width() - 960) // 2 + screen.x()
    y = (screen.height() - 600) // 2 + screen.y()
    window.move(x, y)

    previewer = PdfPreviewerLayout(standalone=True)
    layout = QVBoxLayout(window)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(previewer)

    # 独立窗口下主动应用面板圆角背景样式
    mid = tm.mid
    txt = tm.text
    fill_color = f"rgba({txt.red()},{txt.green()},{txt.blue()},{5 / 100})"
    border_color = f"rgba({mid.red()},{mid.green()},{mid.blue()},{50 / 100})"
    previewer.set_section_styles(fill_color, border_color)

    if len(sys.argv) > 1:
        previewer.set_file(sys.argv[1])

    window.show()
    sys.exit(app.exec())
