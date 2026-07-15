"""
图片预览器布局 — 顶栏（48px 固定高度）+ 内容区（自适应拉伸）
"""

import sys
from pathlib import Path
from typing import Any, Optional

# sys.path bootstrap
_this_file = Path(__file__).resolve()
_ui_root = str(_this_file.parent.parent.parent)  # freeassetfilter/ui/
if _ui_root not in sys.path:
    sys.path.insert(0, _ui_root)
_project_root = str(_this_file.parent.parent.parent.parent.parent)  # project root
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QApplication,
    QPushButton, QStackedLayout, QGraphicsView, QGraphicsScene, QMenu,
    QGraphicsProxyWidget,
)
from PySide6.QtCore import Qt, Signal, QEvent, QPoint, QPointF, QRect, QRectF, QSize, QSizeF, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QFont, QPixmap, QImageReader, QWheelEvent, QPainter, QPen, QColor, QPaintEvent, QMouseEvent, QAction, QTransform, QMovie

from theme import tm
from components.styled_button import StyledButton
from freeassetfilter.core._paths import icons_dir
from freeassetfilter.services.image_decode_worker import ImageDecodeWorker
from freeassetfilter.services.image_decoder_service import ImageDecoderService
from freeassetfilter.ui.components.styled_scroll_area import StyledScrollBar
from freeassetfilter.ui.components.styled_slider import StyledSlider


class _ToolbarFrame(QFrame):
    """顶栏框架 —— 与 PdfPreviewerLayout 完全相同的顶栏框架。"""

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
        left = 8
        for btn in self._left_buttons:
            btn.move(left, (self.height() - btn.height()) // 2)
            left = btn.geometry().right() + 6
        # 右侧按钮（从右往左排列）
        right = self.width() - 8
        for btn in reversed(self._right_buttons):
            btn.move(right - btn.width(), (self.height() - btn.height()) // 2)
            right = btn.geometry().left() - 6


class _StyledHScrollBar(StyledScrollBar):
    """横向样式滚动条，修正 sizeHint 高度为 12px，避免 QGraphicsView 预留 100px 空白。"""
    def __init__(self, parent=None):
        super().__init__(orientation=Qt.Horizontal, parent=parent)
    def sizeHint(self):
        return QSize(100, 12)


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
        """绘制半透明圆角背景 + 边框。"""
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
        """滑动条 0.0~1.0 → 缩放 50%~500%"""
        pct = 50 + int(val * 450)
        self._zoom_value = max(50, min(500, pct))
        self._pct_btn.setText(f"{self._zoom_value}%")
        if self._parent_layout and hasattr(self._parent_layout, '_apply_zoom_pct'):
            self._parent_layout._apply_zoom_pct(self._zoom_value)

    def _reset_zoom(self):
        self._zoom_value = 100
        self._pct_btn.setText("100%")
        self._slider.value = (100 - 50) / 450.0
        if self._parent_layout and hasattr(self._parent_layout, '_fit_to_view'):
            self._parent_layout._fit_to_view()

    def sync_from_renderer(self) -> None:
        """从当前缩放百分比同步滑条位置和百分比显示。"""
        layout = self._parent_layout
        if layout is None:
            return
        pct = getattr(layout, '_zoom_pct', 100)
        pct = max(50, min(500, pct))
        self._zoom_value = pct
        self._pct_btn.setText(f"{pct}%")
        val = (pct - 50) / 450.0
        self._slider.value = val

    def hideEvent(self, event):
        super().hideEvent(event)
        self._closing = False


class _ColorPickerOverlay(QWidget):
    """取色器覆盖层：贯穿视口的虚线十字 + 浮动色彩卡片（由 eventFilter 驱动更新）。"""

    def __init__(self, viewport, image_view, pixmap_item, picker_owner):
        super().__init__(viewport)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)  # 透传鼠标事件到 viewport
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setVisible(False)

        self._image_view = image_view
        self._pixmap_item = pixmap_item
        self._owner = picker_owner
        self._mouse_pos = QPoint()
        self._pixel_color = QColor(255, 255, 255)
        self._has_color = False

    def set_mouse_pos(self, pos: QPoint, color: QColor) -> None:
        """更新鼠标位置和像素颜色。"""
        self._mouse_pos = pos
        self._pixel_color = color
        self._has_color = True
        self.update()

    def clear(self) -> None:
        """清除取色显示。"""
        self._has_color = False
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        if not self._has_color:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = self._mouse_pos.x(), self._mouse_pos.y()

        # Crosshair shadow
        p.setPen(QPen(QColor(0, 0, 0, 80), 1, Qt.DashLine))
        p.drawLine(0, cy + 1, w, cy + 1)
        p.drawLine(cx + 1, 0, cx + 1, h)

        # Dashed crosshair
        p.setPen(QPen(QColor(255, 255, 255), 1, Qt.DashLine))
        p.drawLine(0, cy, w, cy)
        p.drawLine(cx, 0, cx, h)

        # Center dot
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(QPointF(cx, cy), 2.5, 2.5)

        # Floating color card
        card_w, card_h = 148, 72
        card_x = cx + 16
        card_y = cy - card_h - 8
        if card_x + card_w > w:
            card_x = cx - card_w - 16
        if card_y < 4:
            card_y = cy + 8

        # Card background
        p.setPen(QPen(QColor(120, 120, 120), 1))
        p.setBrush(QColor(25, 25, 25, 220))
        p.drawRoundedRect(card_x, card_y, card_w, card_h, 6, 6)

        # Color swatch
        bs = 24
        bx = card_x + 8
        by = card_y + 6
        p.setPen(QPen(QColor(80, 80, 80), 1))
        p.setBrush(self._pixel_color)
        p.drawRoundedRect(bx, by, bs, bs, 4, 4)

        # Hex text
        p.setPen(Qt.white)
        font = QFont("Consolas", 12, QFont.Bold)
        p.setFont(font)
        hex_text = self._pixel_color.name().upper()
        p.drawText(QRect(bx + bs + 8, card_y + 2, card_w - bs - 20, 32), Qt.AlignVCenter | Qt.AlignLeft, hex_text)

        # Hint text
        p.setPen(QColor(180, 180, 180))
        hint_font = QFont("Microsoft YaHei UI", 9)
        p.setFont(hint_font)
        hint = "左键复制十六进制色值\n右键查看更多选项"
        p.drawText(QRect(card_x + 8, card_y + 36, card_w - 16, 30), Qt.AlignLeft | Qt.AlignTop, hint)

        p.end()


class ImagePreviewerLayout(QWidget):
    """
    图片预览器布局

    顶栏固定 48px（与 PDF 预览器顶栏高度一致），用于放置一排操作按钮；
    其余区域为内容区，后续接入图片渲染组件。

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

        self._fullscreen: bool = False
        self._saved_geometry = None
        self._current_file: str = ""
        self._zoom_pct: int = 100       # 50-500, 100 = fit to view
        self._base_scale: float = 1.0   # QGraphicsView scale at fit-to-view
        self._zoom_popup: Optional[_ZoomPopup] = None
        self._rotation: int = 0  # 0, 90, 180, 270
        self._flip_h: bool = False
        self._flip_v: bool = False
        self._is_panning: bool = False
        self._last_pan_pos: QPoint = QPoint()
        self._color_picker_active: bool = False

        # GIF 动画支持
        self._is_gif_mode: bool = False
        self._gif_proxy_item: Optional[QGraphicsProxyWidget] = None
        self._gif_movie: Optional[QMovie] = None
        self._gif_label: Optional[QLabel] = None
        self._gif_paused: bool = False
        self._gif_was_paused_before_picker: bool = False

        self._decode_worker: Optional[ImageDecodeWorker] = None
        self._current_decode_seq: int = 0

        self._init_ui()
        self._connect_theme()

    def _init_ui(self) -> None:
        """初始化顶栏 + 内容区布局。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 顶栏（固定高度 48px，与 PDF 预览器一致）
        self._top_bar = _ToolbarFrame()
        self._top_bar.setObjectName("ImagePreviewerTopBar")
        self._top_bar.setFixedHeight(48)
        self._build_top_bar()
        layout.addWidget(self._top_bar)

        # 内容区（自适应拉伸）— 使用 QStackedLayout
        # index 0 = 图片内容区（空，留待后续）
        # index 1 = 覆盖层（未加载时显示 + standalone 的"选择文件"按钮）
        self._content_area = QFrame()
        self._content_area.setObjectName("ImagePreviewerContent")
        self._content_stack = QStackedLayout(self._content_area)
        self._content_stack.setContentsMargins(0, 0, 0, 0)

        # ── index 0：图片预览区 (QGraphicsView + QGraphicsScene) ──
        self._image_view = QGraphicsView()
        self._image_view.setObjectName("ImagePreviewerView")
        self._image_view.setRenderHint(QPainter.SmoothPixmapTransform)
        self._image_view.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self._image_view.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self._image_view.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self._image_view.setStyleSheet("background-color: #1a1a1a; border: none;")
        self._image_view.setFrameShape(QFrame.NoFrame)

        # 使用 StyledScrollBar 替换默认滚动条
        self._vbar = StyledScrollBar(orientation=Qt.Vertical)
        self._vbar.setMaximumWidth(12)
        self._image_view.setVerticalScrollBar(self._vbar)

        self._hbar = _StyledHScrollBar()
        self._image_view.setHorizontalScrollBar(self._hbar)

        # 安装事件过滤器拦截滚轮/鼠标事件
        self._image_view.viewport().installEventFilter(self)
        self._image_view.viewport().setCursor(Qt.OpenHandCursor)

        self._image_scene = QGraphicsScene(self._image_view)
        self._image_view.setScene(self._image_scene)

        self._pixmap_item = self._image_scene.addPixmap(QPixmap())
        self._content_stack.addWidget(self._image_view)

        # ── 取色器覆盖层（默认隐藏）──
        self._color_picker_overlay = _ColorPickerOverlay(self._image_view.viewport(), self._image_view, self._pixmap_item, self)
        self._image_view.viewport().setFocusPolicy(Qt.StrongFocus)

        # ── index 1：覆盖层（未加载文件时显示）──
        self._overlay = QWidget()
        self._overlay.setObjectName("ImagePreviewerOverlay")
        overlay_layout = QVBoxLayout(self._overlay)
        overlay_layout.setAlignment(Qt.AlignCenter)
        overlay_layout.setSpacing(16)

        # 提示文字
        self._placeholder = QLabel("选择图片文件开始预览")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setStyleSheet("color: #888; font-size: 14px; background: transparent;")
        overlay_layout.addWidget(self._placeholder)

        # "选择文件"按钮（仅 standalone 模式）
        self._browse_btn: Optional[QPushButton] = None
        if self._standalone:
            self._browse_btn = QPushButton("选择图片文件")
            self._browse_btn.setFixedSize(160, 40)
            self._browse_btn.setCursor(Qt.PointingHandCursor)
            self._browse_btn.clicked.connect(self._on_browse_file)
            self._style_browse_button()
            overlay_layout.addWidget(self._browse_btn, alignment=Qt.AlignCenter)

        self._content_stack.addWidget(self._overlay)

        # 初始显示覆盖层（index 1）
        self._content_stack.setCurrentIndex(1)

        layout.addWidget(self._content_area, stretch=1)

        # Wire toolbar buttons
        self._zoom_btn.clicked.connect(self._on_zoom_clicked)
        self._maxsize_btn.clicked.connect(self._on_maxsize_toggle)

    def _build_top_bar(self) -> None:
        """构建顶栏：左侧翻转/旋转按钮，右侧缩放、最大化按钮。"""
        top_layout = QHBoxLayout(self._top_bar)
        top_layout.setContentsMargins(8, 6, 8, 6)
        top_layout.setSpacing(6)

        # 左侧：水平翻转图标按钮
        flip_h_icon = str(icons_dir() / "horizontalflip.svg")
        self._flip_h_btn = StyledButton("", variant="ghost", size="sm", icon=flip_h_icon)
        self._flip_h_btn.setFixedSize(32, 32)
        self._flip_h_btn.setToolTip("水平翻转")
        self._flip_h_btn.clicked.connect(self._toggle_flip_h)
        self._top_bar.add_left_button(self._flip_h_btn)

        # 左侧：垂直翻转图标按钮
        flip_v_icon = str(icons_dir() / "verticalflip.svg")
        self._flip_v_btn = StyledButton("", variant="ghost", size="sm", icon=flip_v_icon)
        self._flip_v_btn.setFixedSize(32, 32)
        self._flip_v_btn.setToolTip("垂直翻转")
        self._flip_v_btn.clicked.connect(self._toggle_flip_v)
        self._top_bar.add_left_button(self._flip_v_btn)

        # 左侧：旋转图标按钮
        rotate_icon = str(icons_dir() / "rotate.svg")
        self._rotate_btn = StyledButton("", variant="ghost", size="sm", icon=rotate_icon)
        self._rotate_btn.setFixedSize(32, 32)
        self._rotate_btn.setToolTip("顺时针旋转 90°")
        self._rotate_btn.clicked.connect(self._rotate_cw)
        self._top_bar.add_left_button(self._rotate_btn)

        # 左侧：取色器图标按钮（紧挨旋转按钮右侧）
        colorpicker_icon = str(icons_dir() / "colorpicker.svg")
        self._colorpicker_btn = StyledButton("", variant="ghost", size="sm", icon=colorpicker_icon)
        self._colorpicker_btn.setFixedSize(32, 32)
        self._colorpicker_btn.setToolTip("取色")
        self._colorpicker_btn.clicked.connect(self._toggle_color_picker)
        self._top_bar.add_left_button(self._colorpicker_btn)

        # ── 中间弹性空间 ──
        top_layout.addStretch(1)

        # 中间：GIF 播放/暂停按钮（默认隐藏，GIF 加载后显示）
        pause_icon_path = str(icons_dir() / "pause.svg")
        play_icon_path = str(icons_dir() / "play.svg")
        self._gif_pause_icon_path = pause_icon_path
        self._gif_play_icon_path = play_icon_path
        self._gif_play_btn = StyledButton("", variant="ghost", size="sm", icon=pause_icon_path)
        self._gif_play_btn.setFixedSize(32, 32)
        self._gif_play_btn.setToolTip("暂停")
        self._gif_play_btn.clicked.connect(self._toggle_gif_playback)
        self._gif_play_btn.hide()
        top_layout.addWidget(self._gif_play_btn)

        # ── 中间弹性空间 ──
        top_layout.addStretch(1)

        # 右侧：缩放图标按钮（由 _ToolbarFrame 绝对定位）
        zoom_icon = str(icons_dir() / "zoom.svg")
        self._zoom_btn = StyledButton("", variant="ghost", size="sm", icon=zoom_icon)
        self._zoom_btn.setFixedSize(32, 32)
        self._zoom_btn.setToolTip("缩放")
        self._top_bar.add_right_button(self._zoom_btn)

        # 右侧：最大化图标按钮
        self._maxsize_icon_path = str(icons_dir() / "maxsize.svg")
        self._minisize_icon_path = str(icons_dir() / "minisize.svg")
        self._maxsize_btn = StyledButton("", variant="ghost", size="sm", icon=self._maxsize_icon_path)
        self._maxsize_btn.setFixedSize(32, 32)
        self._maxsize_btn.setToolTip("最大化")
        self._top_bar.add_right_button(self._maxsize_btn)

    # ── 公共 API ──

    def set_file(self, file_path: str) -> bool:
        """加载并显示图片文件。

        标准格式（jpg/png/bmp/tiff/webp/svg/ico）使用同步 QImageReader 解码；
        复杂格式（RAW/HEIF/AVIF/PSD）通过 ImageDecodeWorker 异步解码。

        Args:
            file_path: 图片文件路径

        Returns:
            bool: 是否加载成功
        """
        if not file_path:
            return False

        # 加载新文件时退出取色模式
        self._color_picker_active = False
        if hasattr(self, '_color_picker_overlay'):
            self._color_picker_overlay.setVisible(False)
        # 切换文件时清理 GIF 模式
        if self._is_gif_mode:
            self._clear_gif()

        suffix = Path(file_path).suffix.lower()

        if suffix == '.gif':
            return self._load_gif(file_path)

        if suffix in ImageDecoderService.STANDARD_FORMATS:
            return self._load_standard(file_path)

        if ImageDecoderService.is_complex_format(suffix):
            return self._load_complex_async(file_path)

        self._placeholder.setText(f"不支持该图片格式（格式：{suffix}）")
        self._content_stack.setCurrentIndex(1)
        return False

    # ── GIF 动画方法 ──

    def _load_gif(self, file_path: str) -> bool:
        """加载并播放 GIF 动画（通过 QGraphicsProxyWidget 嵌入 QLabel+QMovie）。

        Args:
            file_path: GIF 文件路径

        Returns:
            bool: 是否加载成功
        """
        self._cancel_decode_worker()
        self._clear_gif()

        movie = QMovie(file_path)
        if not movie.isValid():
            self._placeholder.setText("无法加载GIF文件")
            self._content_stack.setCurrentIndex(1)
            return False

        # 先获取 GIF 第一帧尺寸，确保 QLabel 尺寸正确
        movie.jumpToFrame(0)
        frame_size = movie.currentPixmap().size()
        if not frame_size.isValid():
            self._placeholder.setText("无法获取GIF尺寸")
            self._content_stack.setCurrentIndex(1)
            return False

        label = QLabel()
        label.setMovie(movie)
        label.setFixedSize(frame_size)
        label.setStyleSheet("background: transparent;")
        movie.start()  # 自动播放
        # 显示暂停按钮（默认播放状态）
        self._gif_play_btn.show()
        self._gif_play_btn.set_svg_icon(self._gif_pause_icon_path)
        self._gif_play_btn.setToolTip("暂停")
        self._gif_paused = False

        # 设置场景矩形为 GIF 实际尺寸，与普通图片的 setSceneRect 行为一致
        self._image_scene.setSceneRect(QRectF(QPointF(0, 0), QSizeF(frame_size)))

        proxy = QGraphicsProxyWidget()
        proxy.setWidget(label)
        self._image_scene.addItem(proxy)

        # 隐藏原有的 pixmap item
        self._pixmap_item.setVisible(False)

        self._gif_movie = movie
        self._gif_label = label
        self._gif_proxy_item = proxy
        self._is_gif_mode = True
        self._current_file = file_path

        self._fit_to_view()
        self._content_stack.setCurrentIndex(0)
        return True

    def _clear_gif(self) -> None:
        """清理 GIF 资源并恢复 pixmap item。"""
        if self._gif_movie is not None:
            self._gif_movie.stop()
            self._gif_movie = None
        if self._gif_proxy_item is not None:
            self._image_scene.removeItem(self._gif_proxy_item)
            self._gif_proxy_item = None
        self._gif_label = None
        self._gif_play_btn.hide()
        self._pixmap_item.setVisible(True)
        self._is_gif_mode = False
        # 重置旋转/翻转状态
        self._rotation = 0
        self._flip_h = False
        self._flip_v = False
        self._rotate_btn._variant = "ghost"
        self._update_flip_button_style()

    def _toggle_gif_playback(self) -> None:
        """切换 GIF 播放/暂停状态。"""
        if self._gif_movie is None:
            return
        if not self._gif_paused:
            self._gif_movie.setPaused(True)
            self._gif_play_btn.set_svg_icon(self._gif_play_icon_path)
            self._gif_play_btn.setToolTip("播放")
            self._gif_paused = True
        else:
            self._gif_movie.setPaused(False)
            self._gif_play_btn.set_svg_icon(self._gif_pause_icon_path)
            self._gif_play_btn.setToolTip("暂停")
            self._gif_paused = False

    def _load_standard(self, file_path: str) -> bool:
        """同步加载标准格式图片（jpg/png/bmp/tiff/webp/svg/ico）。

        Args:
            file_path: 图片文件路径

        Returns:
            bool: 是否加载成功
        """
        if self._is_gif_mode:
            self._clear_gif()
        reader = QImageReader(file_path)
        reader.setAutoTransform(True)
        qimage = reader.read()
        if qimage.isNull():
            self._placeholder.setText(f"无法加载图片: {reader.errorString()}")
            self._content_stack.setCurrentIndex(1)
            return False

        pixmap = QPixmap.fromImage(qimage)
        self._pixmap_item.setPixmap(pixmap)
        self._image_scene.setSceneRect(QRectF(pixmap.rect()))

        self._current_file = file_path
        self._fit_to_view()
        self._content_stack.setCurrentIndex(0)
        return True

    def _load_complex_async(self, file_path: str) -> bool:
        """异步加载复杂格式图片（RAW/HEIF/AVIF/PSD）。

        Args:
            file_path: 图片文件路径

        Returns:
            bool: 始终返回 True（实际结果通过回调处理）
        """
        if self._is_gif_mode:
            self._clear_gif()
        self._cancel_decode_worker()
        self._current_decode_seq += 1
        seq = self._current_decode_seq

        self._placeholder.setText("正在解码图片...")
        self._content_stack.setCurrentIndex(1)

        worker = ImageDecodeWorker(file_path)
        worker.decoded.connect(
            lambda qimage, path, s=seq: self._on_decoded(qimage, path, s)
        )
        worker.failed.connect(
            lambda err, s=seq: self._on_decode_failed(err, s)
        )
        worker.finished.connect(worker.deleteLater)

        worker.start_with_timeout()
        self._decode_worker = worker
        return True

    def _on_decoded(self, qimage, file_path: str, seq: int) -> None:
        """异步解码成功回调。

        Args:
            qimage: 解码后的 QImage
            file_path: 原始文件路径
            seq: 解码序列号（用于忽略过期回调）
        """
        if seq != self._current_decode_seq:
            return
        if qimage is None or qimage.isNull():
            self._placeholder.setText("解码结果为空")
            self._content_stack.setCurrentIndex(1)
            return

        pixmap = QPixmap.fromImage(qimage)
        self._pixmap_item.setPixmap(pixmap)
        self._image_scene.setSceneRect(QRectF(pixmap.rect()))

        self._current_file = file_path
        self._fit_to_view()
        self._content_stack.setCurrentIndex(0)

    def _on_decode_failed(self, error_msg: str, seq: int) -> None:
        """异步解码失败回调。

        Args:
            error_msg: 错误消息
            seq: 解码序列号（用于忽略过期回调）
        """
        if seq != self._current_decode_seq:
            return
        self._placeholder.setText(f"解码失败: {error_msg}")
        self._content_stack.setCurrentIndex(1)

    def _cancel_decode_worker(self) -> None:
        """取消当前正在运行的解码 worker。"""
        if self._decode_worker is not None:
            worker = self._decode_worker
            self._decode_worker = None
            if worker.isRunning():
                worker.cancel()
            worker.deleteLater()

    def _on_zoom_clicked(self) -> None:
        """缩放按钮点击：展开/收起缩放弹出面板。"""
        if self._zoom_popup is not None and self._zoom_popup.isVisible():
            self._zoom_popup.close_animated()
            return
        if self._zoom_popup is None:
            self._zoom_popup = _ZoomPopup(parent=self)
        self._zoom_popup.sync_from_renderer()
        tb_br = self._top_bar.mapToGlobal(QPoint(self._top_bar.width(), self._top_bar.height()))
        self._zoom_popup.show_animated(tb_br)

    def _fit_to_view(self) -> None:
        """自适应缩放，记录基准缩放作为 100%。"""
        if self._is_gif_mode and self._gif_proxy_item is not None:
            self._reset_view()
            self._image_view.fitInView(self._gif_proxy_item, Qt.KeepAspectRatio)
            self._base_scale = self._image_view.transform().m11()
            self._zoom_pct = 100
            return
        if self._pixmap_item.pixmap().isNull():
            return
        self._reset_view()
        self._image_view.fitInView(self._pixmap_item, Qt.KeepAspectRatio)
        self._base_scale = self._image_view.transform().m11()
        self._zoom_pct = 100

    def _apply_zoom_pct(self, pct: int) -> None:
        """按百分比（相对 fit_to_view）缩放。"""
        pct = max(50, min(500, pct))
        self._zoom_pct = pct
        if self._base_scale <= 0:
            return
        if not self._is_gif_mode and self._pixmap_item.pixmap().isNull():
            return
        target = self._base_scale * pct / 100.0
        self._reset_view()
        self._image_view.scale(target, target)

        # 缩放弹出面板展开时同步滑块和百分比显示
        if self._zoom_popup is not None and self._zoom_popup.isVisible():
            self._zoom_popup.sync_from_renderer()

    def _reset_view(self) -> None:
        """重置视图变换。"""
        self._image_view.resetTransform()

    def _apply_item_transform(self) -> None:
        """组合应用翻转和旋转变换，以图像自身中心为基准轴。"""
        target = self._gif_proxy_item if self._is_gif_mode else self._pixmap_item
        if target is None:
            return

        # 以图像自身 boundingRect 中心为基准轴，而非视口中心
        center = target.boundingRect().center()
        cx, cy = center.x(), center.y()

        # 在图像本地坐标系中组合变换：平移到中心 → 旋转 → 翻转 → 平移回
        t = QTransform()
        t.translate(cx, cy)
        t.rotate(self._rotation)
        if self._flip_h:
            t.scale(-1, 1)
        if self._flip_v:
            t.scale(1, -1)
        t.translate(-cx, -cy)
        target.setTransform(t)

    def _rotate_cw(self) -> None:
        """图片顺时针旋转 90°，以视口预览区域中心为锚点。"""
        self._rotation = (self._rotation + 90) % 360
        self._rotate_btn._variant = "primary" if self._rotation != 0 else "ghost"
        self._rotate_btn.update()
        self._apply_item_transform()
        if self._is_gif_mode or not self._pixmap_item.pixmap().isNull():
            saved_pct = self._zoom_pct
            self._fit_to_view()
            if saved_pct != 100:
                self._apply_zoom_pct(saved_pct)

    def _toggle_flip_h(self) -> None:
        """切换水平翻转（以视口垂直中心轴线为基准）。"""
        self._flip_h = not self._flip_h
        self._update_flip_button_style()
        self._apply_item_transform()
        if self._is_gif_mode or not self._pixmap_item.pixmap().isNull():
            saved_pct = self._zoom_pct
            self._fit_to_view()
            if saved_pct != 100:
                self._apply_zoom_pct(saved_pct)

    def _toggle_flip_v(self) -> None:
        """切换垂直翻转（以视口水平中心轴线为基准）。"""
        self._flip_v = not self._flip_v
        self._update_flip_button_style()
        self._apply_item_transform()
        if self._is_gif_mode or not self._pixmap_item.pixmap().isNull():
            saved_pct = self._zoom_pct
            self._fit_to_view()
            if saved_pct != 100:
                self._apply_zoom_pct(saved_pct)

    def _update_flip_button_style(self) -> None:
        """根据翻转状态更新按钮强调样式。"""
        self._flip_h_btn._variant = "primary" if self._flip_h else "ghost"
        self._flip_h_btn.update()
        self._flip_v_btn._variant = "primary" if self._flip_v else "ghost"
        self._flip_v_btn.update()

    def _toggle_color_picker(self) -> None:
        """切换取色模式。进入时自动暂停 GIF，退出时恢复 GIF 播放状态。"""
        entering = not self._color_picker_active
        self._color_picker_active = entering

        if entering:
            # ── 进入取色模式：保存 GIF 暂停状态，若播放中则暂停 ──
            if self._is_gif_mode and self._gif_movie is not None:
                self._gif_was_paused_before_picker = self._gif_paused
                if not self._gif_paused:
                    self._gif_movie.setPaused(True)
                    self._gif_paused = True
                    # 保持暂停图标（取色模式下按钮隐藏，但状态要正确）
                    self._gif_play_btn.set_svg_icon(self._gif_play_icon_path)
                    self._gif_play_btn.setToolTip("播放")

            # 显示前重新定位覆盖层到 viewport 位置
            vp = self._image_view.viewport()
            self._color_picker_overlay.setGeometry(vp.rect())
            self._color_picker_overlay.raise_()
            # 初始显示中心十字和色彩信息
            center = vp.rect().center()
            color = self._get_pixel_color(center)
            if color is None:
                color = QColor(128, 128, 128)
            self._color_picker_overlay.set_mouse_pos(center, color)
        else:
            # ── 退出取色模式：恢复到取色前的 GIF 播放状态 ──
            if self._is_gif_mode and self._gif_movie is not None:
                if not self._gif_was_paused_before_picker and self._gif_paused:
                    self._gif_movie.setPaused(False)
                    self._gif_paused = False
                    self._gif_play_btn.set_svg_icon(self._gif_pause_icon_path)
                    self._gif_play_btn.setToolTip("暂停")

            self._color_picker_overlay.clear()
            self._image_view.viewport().setCursor(Qt.OpenHandCursor)
            self._colorpicker_btn._variant = "ghost"
            self._colorpicker_btn.update()
        self._color_picker_overlay.setVisible(entering)
        if entering:
            self._image_view.viewport().setCursor(Qt.CrossCursor)
            self._colorpicker_btn._variant = "primary"
            self._colorpicker_btn.update()

    def _get_pixel_color(self, viewport_pos: QPoint) -> Optional[QColor]:
        """从视口坐标获取像素颜色（自动处理旋转）。"""
        if self._is_gif_mode:
            if self._gif_movie is None or self._gif_proxy_item is None:
                return None
            frame_pixmap = self._gif_movie.currentPixmap()
            if frame_pixmap.isNull():
                return None
            scene_pos = self._image_view.mapToScene(viewport_pos)
            local_pos = self._gif_proxy_item.mapFromScene(scene_pos)
            px = int(round(local_pos.x()))
            py = int(round(local_pos.y()))
            w, h = frame_pixmap.width(), frame_pixmap.height()
            if 0 <= px < w and 0 <= py < h:
                return QColor(frame_pixmap.toImage().pixel(px, py))
            return None
        pixmap = self._pixmap_item.pixmap()
        if pixmap.isNull():
            return None
        scene_pos = self._image_view.mapToScene(viewport_pos)
        local_pos = self._pixmap_item.mapFromScene(scene_pos)
        px = int(round(local_pos.x()))
        py = int(round(local_pos.y()))
        w, h = pixmap.width(), pixmap.height()
        if 0 <= px < w and 0 <= py < h:
            return QColor(pixmap.toImage().pixel(px, py))
        return None

    def _copy_color_and_exit(self, event) -> None:
        """左键：复制 HEX 到剪贴板并退出取色模式。"""
        color = self._get_pixel_color(event.position().toPoint())
        if color is not None:
            QApplication.clipboard().setText(color.name().upper())
        self._toggle_color_picker()

    def _show_color_context_menu(self, event, color: QColor) -> None:
        """右键：显示色彩格式菜单，点击后复制对应格式并退出取色模式。"""

        def _format_rgb255(c: QColor) -> str:
            return f"rgb({c.red()}, {c.green()}, {c.blue()})"

        def _format_rgb_f(c: QColor) -> str:
            return f"rgb({c.redF():.3f}, {c.greenF():.3f}, {c.blueF():.3f})"

        def _format_hsl(c: QColor) -> str:
            h = max(0, c.hslHue())
            s = c.hslSaturation() * 100 // 255
            l = c.lightness() * 100 // 255
            return f"hsl({h}, {s}%, {l}%)"

        def _format_hsv(c: QColor) -> str:
            h = max(0, c.hsvHue())
            s = c.hsvSaturation() * 100 // 255
            v = c.value() * 100 // 255
            return f"hsv({h}, {s}%, {v}%)"

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #2a2a2a;
                border: 1px solid #555;
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item {
                color: #eee;
                padding: 6px 24px 6px 12px;
                border-radius: 4px;
                font-size: 12px;
                font-family: 'Microsoft YaHei UI', 'Segoe UI', sans-serif;
            }
            QMenu::item:selected {
                background-color: #444;
            }
        """)

        items = [
            (_format_rgb255(color), "RGB (0-255)"),
            (_format_rgb_f(color),  "RGB (0.0-1.0)"),
            (_format_hsl(color),    "HSL"),
            (_format_hsv(color),    "HSV"),
        ]
        for value, label in items:
            action = QAction(f"{label}  {value}", self)
            action.setData(value)
            menu.addAction(action)

        chosen = menu.exec(event.globalPosition().toPoint())
        if chosen is not None:
            QApplication.clipboard().setText(chosen.data())
        self._toggle_color_picker()

    def eventFilter(self, obj, event) -> bool:
        """拦截事件：取色器 + 拖拽平移 + 双击复位 + 滚轮缩放 + 弹窗外部点击关闭 + 窗口移动/缩放关闭弹窗。"""

        # 取色模式：viewport 上拦截鼠标事件，更新覆盖层
        if self._color_picker_active and obj is self._image_view.viewport():
            if event.type() == QEvent.MouseMove:
                pos = event.position().toPoint()
                color = self._get_pixel_color(pos)
                if color is None:
                    color = self._color_picker_overlay._pixel_color
                self._color_picker_overlay.set_mouse_pos(pos, color)
                return True
            if event.type() == QEvent.MouseButtonPress:
                pos = event.position().toPoint()
                if event.button() == Qt.LeftButton:
                    color = self._get_pixel_color(pos)
                    if color is not None:
                        QApplication.clipboard().setText(color.name().upper())
                    self._toggle_color_picker()
                    return True
                if event.button() == Qt.RightButton:
                    color = self._get_pixel_color(pos)
                    if color is not None:
                        self._show_color_context_menu(event, color)
                    return True
            if event.type() == QEvent.KeyPress:
                if event.key() == Qt.Key_Escape:
                    self._toggle_color_picker()
                    return True

        # 鼠标中键/左键拖拽平移（行为一致）
        if event.type() == QEvent.MouseButtonPress and obj is self._image_view.viewport():
            if event.button() in (Qt.LeftButton, Qt.MiddleButton):
                self._is_panning = True
                self._last_pan_pos = event.position().toPoint()
                self._image_view.viewport().setCursor(Qt.ClosedHandCursor)
                return True

        if event.type() == QEvent.MouseButtonDblClick and obj is self._image_view.viewport():
            if event.button() in (Qt.LeftButton, Qt.MiddleButton):
                self._fit_to_view()
                return True

        if event.type() == QEvent.MouseMove and obj is self._image_view.viewport():
            if self._is_panning:
                delta = event.position().toPoint() - self._last_pan_pos
                self._last_pan_pos = event.position().toPoint()
                hbar = self._image_view.horizontalScrollBar()
                vbar = self._image_view.verticalScrollBar()
                hbar.setValue(hbar.value() - delta.x())
                vbar.setValue(vbar.value() - delta.y())
                return True

        if event.type() == QEvent.MouseButtonRelease and obj is self._image_view.viewport():
            if event.button() in (Qt.LeftButton, Qt.MiddleButton):
                self._is_panning = False
                self._image_view.viewport().setCursor(Qt.OpenHandCursor)
                return True

        # 鼠标点击外部时关闭缩放弹窗
        if event.type() == QEvent.MouseButtonPress and self._zoom_popup is not None and self._zoom_popup.isVisible():
            me = event if isinstance(event, QMouseEvent) else None
            if me is not None:
                popup_rect = QRect(self._zoom_popup.pos(), self._zoom_popup.size())
                if not popup_rect.contains(me.globalPosition().toPoint()):
                    self._zoom_popup.close_animated()

        # 窗口移动或缩放时关闭弹窗
        if event.type() in (QEvent.Move, QEvent.Resize):
            if obj is self.window() or obj is self:
                if self._zoom_popup is not None and self._zoom_popup.isVisible():
                    self._zoom_popup.close_animated()

        if obj is self._image_view.viewport() and event.type() == QEvent.Wheel:
            we = QWheelEvent(event)
            delta = we.angleDelta().y()
            if delta == 0:
                return True
            # 步进 10%，范围与 zoom 菜单一致 50%-500%
            step = 10
            new_pct = self._zoom_pct + (step if delta > 0 else -step)
            new_pct = max(50, min(500, new_pct))
            if new_pct == self._zoom_pct:
                return True  # 已达边界
            # 以鼠标位置为锚点缩放，保持该像素不动
            old_pos = self._image_view.mapToScene(we.position().toPoint())
            self._apply_zoom_pct(new_pct)
            new_pos = self._image_view.mapToScene(we.position().toPoint())
            delta_pos = new_pos - old_pos
            self._image_view.translate(delta_pos.x(), delta_pos.y())
            return True  # 完全消费事件，不触发滚动
        return super().eventFilter(obj, event)

    def resizeEvent(self, event) -> None:
        """窗口大小变化时如果处于 fit 模式则重新适配。"""
        super().resizeEvent(event)
        if hasattr(self, '_image_view') and self._content_stack.currentIndex() == 0:
            if self._zoom_pct == 100:
                if self._is_gif_mode or not self._pixmap_item.pixmap().isNull():
                    self._fit_to_view()
        if hasattr(self, '_color_picker_overlay'):
            vp = self._image_view.viewport()
            self._color_picker_overlay.setGeometry(vp.rect())
            self._color_picker_overlay.raise_()

    def set_section_styles(self, fill_color: str, border_color: str) -> None:
        """应用面板样式（主题切换时由 MainWindow 调用）。"""
        self._top_bar.setStyleSheet("""
            background-color: transparent;
            border: 1px solid transparent;
            border-radius: 8px;
        """)
        self._content_area.setStyleSheet(f"""
            background-color: {tm.surface.name()};
            border: 1px solid transparent;
            border-radius: 8px;
        """)
        self._overlay.setStyleSheet(f"""
            background-color: {tm.surface.name()};
        """)

    # ── 内部方法 ──

    def _connect_theme(self) -> None:
        """连接主题切换信号。"""
        tm.theme_changed.connect(self._on_theme_changed)

    def _on_theme_changed(self, theme_name: str) -> None:
        """主题变更时刷新样式。"""
        self._style_browse_button()
        self.update()

    def _on_maxsize_toggle(self) -> None:
        """切换全屏 / 还原窗口。"""
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

    def _on_browse_file(self) -> None:
        """打开文件选择对话框选择图片（仅 standalone 模式）。"""
        from PySide6.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择图片文件",
            "",
            "图片文件 (*.png *.jpg *.jpeg *.gif *.bmp *.webp *.svg *.tiff *.tif *.ico);;所有文件 (*.*)",
        )
        if file_path:
            self.set_file(file_path)

    def _style_browse_button(self) -> None:
        """应用主题色到"选择图片文件"按钮。"""
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


if __name__ == "__main__":
    app = QApplication(sys.argv)

    window = QWidget()
    window.setWindowTitle("图片预览器 (独立测试)")
    window.resize(960, 600)

    # 居中显示
    screen = app.primaryScreen().geometry()
    x = (screen.width() - 960) // 2 + screen.x()
    y = (screen.height() - 600) // 2 + screen.y()
    window.move(x, y)

    previewer = ImagePreviewerLayout(standalone=True)
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
