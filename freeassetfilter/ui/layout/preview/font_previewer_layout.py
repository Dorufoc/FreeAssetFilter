"""
字体预览器布局 — 顶栏（48px 固定高度）+ 内容区（自适应拉伸）

支持：
- 字体文件加载与异步渲染（.ttf / .otf / .woff / .woff2 / .eot）
- 预览文本编辑抽屉
- 字号缩放（8–32px）
- 主题切换

控件使用 Styled 系列组件（StyledButton / StyledSlider / StyledDrawer /
StyledTextarea / StyledScrollBar 等）和 `tm` 提供的颜色 token，不使用旧的
D_* 或 Custom* 控件。
"""

import os
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

from components.styled_button import StyledButton
from components.styled_combobox import StyledComboBox
from components.styled_drawer import StyledDrawer
from components.styled_slider import StyledSlider
from components.styled_textarea import StyledTextarea
from layout.preview.fullscreen_host import PreviewFullscreenHost
from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QMutex,
    QMutexLocker,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QMouseEvent,
    QPaintEvent,
    QPainter,
    QPainterPath,
    QPen,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedLayout,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from theme import tm

from freeassetfilter.core._paths import icons_dir
from freeassetfilter.ui.layout.preview.text_previewer_layout import (
    _StyledPreviewScrollArea,
)

# ──────────────────────────────────────────────────────────────────────────────
# 模块常量
# ──────────────────────────────────────────────────────────────────────────────

FONT_SIZE_MIN = 8
FONT_SIZE_MAX = 32
DEFAULT_FONT_SIZE = 14

FONT_FILTERS = "字体文件 (*.ttf *.otf *.woff *.woff2 *.eot);;所有文件 (*.*)"

DEFAULT_PREVIEW_TEXT = """FreeAssetFilter字体示例

汉字之美，在于形、意、韵。天地人和，万物有序。
漢字之美，在於形、意、韻。天地人和，萬物有序。

The quick brown fox jumps over the lazy dog.
abcdefghijklmnopqrstuvwxyz
ABCDEFGHIJKLMNOPQRSTUVWXYZ
0123456789
!@#$%^&*()_+-=[]{};':",./<>?

吾輩は猫である。名前はまだ無い。あいうえお かきくけこ さしすせそ
사람은 무엇으로 사는가?가나다라마바사 아자차카타파하
В чащах юга жил бы цитрус? Да, но фальшивый экземпляр!абвгдеёжзийклмнопрстуфхцчшщъыьэюя"""


# ──────────────────────────────────────────────────────────────────────────────
# 顶栏框架（从 text_previewer_layout.py / pdf_previewer_layout.py 原样复制）
# ──────────────────────────────────────────────────────────────────────────────

class _ToolbarFrame(QFrame):
    """顶栏框架 —— 页面标签通过布局居中，操作按钮在 resizeEvent 中绝对定位到两侧。

    这样标题标签是在整个顶栏宽度上真正居中，不会被两侧按钮挤偏。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        """初始化顶栏框架。

        Args:
            parent: 父控件。
        """
        super().__init__(parent)
        self._left_buttons: list[QWidget] = []
        self._right_buttons: list[QWidget] = []

    def add_left_button(self, btn: QWidget) -> None:
        """注册一个左侧按钮，将其父对象设为此顶栏并在下次布局时自动定位。

        Args:
            btn: 要放置到左侧的按钮控件。
        """
        self._left_buttons.append(btn)
        btn.setParent(self)

    def add_right_button(self, btn: QWidget) -> None:
        """注册一个右侧按钮，将其父对象设为此顶栏并在下次布局时自动定位。

        Args:
            btn: 要放置到右侧的按钮控件。
        """
        self._right_buttons.append(btn)
        btn.setParent(self)

    def fixedHeight(self) -> int:
        """返回当前固定高度（便于测试使用）。

        Returns:
            当前控件高度，单位为像素。
        """
        return self.height()

    def _layout_buttons(self) -> None:
        """将已注册的可见按钮固定到顶栏两侧，跳过隐藏按钮。"""
        # 左侧按钮（从左往右排列）
        left = 8  # 左侧内边距 8px
        for btn in self._left_buttons:
            if not btn.isVisible():
                continue
            btn.move(left, (self.height() - btn.height()) // 2)
            left = btn.geometry().right() + 6  # 按钮间距 6px
        # 右侧按钮（从右往左排列）
        right = self.width() - 8  # 右侧内边距 8px
        for btn in reversed(self._right_buttons):
            if not btn.isVisible():
                continue
            btn.move(right - btn.width(), (self.height() - btn.height()) // 2)
            right = btn.geometry().left() - 6  # 按钮间距 6px

    def resizeEvent(self, event) -> None:
        """每次大小变化时重新定位可见按钮，不影响中间布局的居中计算。"""
        super().resizeEvent(event)
        self._layout_buttons()

    def showEvent(self, event) -> None:
        """首次显示时立即布局按钮（某些平台下初始 resizeEvent 可能不触发）。"""
        super().showEvent(event)
        self._layout_buttons()

    def _get_colors(self) -> dict[str, QColor]:
        """获取当前主题下的顶栏颜色（paintEvent 中动态读取，确保主题切换生效）。"""
        return {
            "bg": tm.fill,
            "border": tm.alpha_of(tm.mid, 25),
        }

    def paintEvent(self, event: QPaintEvent) -> None:
        """自绘顶栏圆角背景与边框，颜色跟随当前主题。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        colors = self._get_colors()
        rect = QRectF(self.rect())
        radius = 8.0

        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)

        painter.setPen(Qt.NoPen)
        painter.setBrush(colors["bg"])
        painter.drawPath(path)

        painter.setPen(QPen(colors["border"], 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)


# ──────────────────────────────────────────────────────────────────────────────
# 支持 Ctrl+滚轮缩放的 QTextEdit
# ──────────────────────────────────────────────────────────────────────────────

class _ZoomAwareTextEdit(QTextEdit):
    """预览区内部文本控件：拦截 Ctrl+滚轮事件并转换为字号调整信号。

    Signals:
        font_size_change_requested(delta): 正数表示增大，负数表示减小。
    """

    font_size_change_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        """初始化文本控件。

        Args:
            parent: 父控件。
        """
        super().__init__(parent)

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Ctrl+滚轮时触发自定义字号调整，避免 QTextEdit 默认缩放行为。"""
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self.font_size_change_requested.emit(1)
            elif delta < 0:
                self.font_size_change_requested.emit(-1)
            event.accept()
            return
        super().wheelEvent(event)


# ──────────────────────────────────────────────────────────────────────────────
# 字体渲染预览区（复用 text_previewer_layout 的 _StyledPreviewScrollArea 模式）
# ──────────────────────────────────────────────────────────────────────────────

class _PreviewScrollArea(_StyledPreviewScrollArea):
    """字体预览包装器：只读 QTextEdit + 自定义滚动条 + 平滑滚轮。

    与文本预览器的源码视图保持一致，垂直滚动单位为像素。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        """初始化预览区内部的 QTextEdit 并交给基类包装。"""
        self._text_edit = _ZoomAwareTextEdit()
        self._text_edit.setObjectName("FontPreviewerTextEdit")
        self._text_edit.setReadOnly(True)
        self._text_edit.setLineWrapMode(QTextEdit.WidgetWidth)
        self._text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._text_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._text_edit.setViewportMargins(16, 12, 16, 12)
        self._text_edit.setAcceptRichText(False)
        self._content_widget = self._text_edit
        self._wheel_step_scale = 1.0
        super().__init__(parent)

    def update_wheel_step_scale(self) -> None:
        """像素滚动模式下保持 1.0 步长比例。"""
        self._wheel_step_scale = 1.0
        if self._wheel_filter is not None:
            self._wheel_filter.set_wheel_step_scale(self._wheel_step_scale)


# ──────────────────────────────────────────────────────────────────────────────
# 字体加载后台线程（从旧的 font_previewer.py 移植）
# ──────────────────────────────────────────────────────────────────────────────

class FontLoadThread(QThread):
    """字体加载后台线程。

    通过 QFontDatabase.addApplicationFont 在后台加载字体文件，并使用
    request_id 机制支持取消旧请求。成功时发射 ``(request_id, True,
    font_family, font_id)``；失败时发射 ``(request_id, error_msg)``。
    """

    finished = Signal(int, bool, str, int)
    error = Signal(int, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        """初始化字体加载线程。

        Args:
            parent: 父控件。
        """
        super().__init__(parent)
        self.file_path: str = ""
        self._request_id: int = 0
        self._mutex = QMutex()
        self._abort: bool = False

    def set_file(self, file_path: str) -> None:
        """设置要加载的字体文件路径。

        Args:
            file_path: 字体文件的绝对或相对路径。
        """
        with QMutexLocker(self._mutex):
            self.file_path = file_path

    def set_request_id(self, request_id: int) -> None:
        """设置请求 ID，用于在结果返回时识别是否为最新请求。

        Args:
            request_id: 本次加载请求的唯一标识。
        """
        with QMutexLocker(self._mutex):
            self._request_id = request_id

    def abort(self) -> None:
        """请求终止当前加载任务。"""
        with QMutexLocker(self._mutex):
            self._abort = True

    def run(self) -> None:
        """执行字体加载。"""
        with QMutexLocker(self._mutex):
            if self._abort:
                return
            file_path = self.file_path
            request_id = self._request_id

        try:
            if not os.path.exists(file_path):
                self.error.emit(request_id, f"字体文件不存在: {file_path}")
                return

            # 加载字体文件
            font_id = QFontDatabase.addApplicationFont(file_path)

            if font_id == -1:
                self.error.emit(request_id, "无法加载字体文件，可能格式不支持")
                return

            # 获取字体族名称
            font_families = QFontDatabase.applicationFontFamilies(font_id)

            if not font_families:
                self.error.emit(request_id, "无法获取字体族名称")
                return

            font_family = font_families[0]
            self.finished.emit(request_id, True, font_family, font_id)

        except Exception as e:  # noqa: BLE001
            self.error.emit(request_id, f"加载字体失败: {e!s}")


# ──────────────────────────────────────────────────────────────────────────────
# 支持程序化赋值的缩放滑动条
# ──────────────────────────────────────────────────────────────────────────────

class _ZoomSlider(StyledSlider):
    """StyledSlider 子类：在 ``value`` 属性被程序化写入时同样发射 ``value_changed``。

    基类 ``StyledSlider`` 只在用户拖拽轨道时通过 ``SliderTrack`` 发射该信号，
    导致外部直接设置 ``_slider.value = 0.5`` 时父布局收不到回调。此子类保持
    其他行为不变，仅让 setter 也发射信号，使缩放弹窗的同步和测试驱动生效。
    """

    @property
    def value(self) -> float:
        return super().value

    @value.setter
    def value(self, v: float) -> None:
        clamped = max(0.0, min(1.0, v))
        self._track_widget.value = clamped
        self._on_value_changed(clamped)


# ──────────────────────────────────────────────────────────────────────────────
# 字号缩放弹出面板
# ──────────────────────────────────────────────────────────────────────────────

class _ZoomPopup(QWidget):
    """字号缩放弹出面板：含横向滑动条 + 百分比按钮。

    将滑动条 0.0~1.0 线性映射到 ``FONT_SIZE_MIN``~``FONT_SIZE_MAX`` 像素。
    """

    FONT_SIZE_MIN = FONT_SIZE_MIN
    FONT_SIZE_MAX = FONT_SIZE_MAX

    def __init__(
        self,
        parent: Optional["FontPreviewerLayout"] = None,
    ) -> None:
        """初始化缩放弹出面板。

        Args:
            parent: 父布局实例，用于同步字号。
        """
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._parent_layout = parent
        self._radius = 8
        self._padding = 8
        self._closing = False
        if self._parent_layout is not None:
            self._base_font_size = getattr(
                self._parent_layout, "_current_font_size", DEFAULT_FONT_SIZE
            )
        else:
            self._base_font_size = DEFAULT_FONT_SIZE
        self._zoom_value = self._base_font_size

        # 动画
        self._fade = QPropertyAnimation(self, b"windowOpacity")
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._slide = QPropertyAnimation(self, b"geometry")
        self._slide.setEasingCurve(QEasingCurve.OutCubic)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            self._padding, self._padding, self._padding, self._padding
        )
        layout.setSpacing(8)

        # 百分比按钮（点击重置为 100%）
        self._pct_btn = StyledButton("100%", variant="ghost", size="sm")
        self._pct_btn.setFixedHeight(28)
        self._pct_btn.clicked.connect(self._reset_zoom)
        layout.addWidget(self._pct_btn)

        # 横向滑动条（使用会发射程序化写入信号的子类）
        self._slider = _ZoomSlider(
            value=self._font_size_to_value(self._base_font_size),
            size="sm",
            orientation=Qt.Horizontal,
        )
        self._slider.setFixedWidth(140)
        self._slider.value_changed.connect(self._on_slider_changed)
        layout.addWidget(self._slider)

    def _font_size_to_value(self, font_size: int) -> float:
        """将字号映射为滑动条 0.0~1.0。"""
        size = max(self.FONT_SIZE_MIN, min(self.FONT_SIZE_MAX, font_size))
        return (size - self.FONT_SIZE_MIN) / max(
            1, self.FONT_SIZE_MAX - self.FONT_SIZE_MIN
        )

    def _value_to_font_size(self, value: float) -> int:
        """将滑动条 0.0~1.0 映射为字号。"""
        return self.FONT_SIZE_MIN + int(
            value * (self.FONT_SIZE_MAX - self.FONT_SIZE_MIN)
        )

    def paintEvent(self, event) -> None:
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

    def show_animated(self, anchor_br: QPoint) -> None:
        """从按钮右下角向下展开，弹窗右对齐。"""
        pw = 220
        ph = 48
        margin_r = 5
        x = anchor_br.x() - pw - margin_r
        y = anchor_br.y() + 7

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

    def close_animated(self) -> None:
        """带动画关闭弹窗。"""
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

    def _close_and_reset(self) -> None:
        self._slide.finished.disconnect(self._close_and_reset)
        self.close()
        self._closing = False

    def _on_slider_changed(self, val: float) -> None:
        """滑动条变化时同步字号到父布局。"""
        font_size = self._value_to_font_size(val)
        self._zoom_value = font_size
        pct = 100
        if self._base_font_size > 0:
            pct = round(font_size / self._base_font_size * 100)
        self._pct_btn.setText(f"{pct}%")
        if self._parent_layout is not None and hasattr(
            self._parent_layout, "_apply_font_size_from_zoom"
        ):
            self._parent_layout._apply_font_size_from_zoom(font_size)

    def _reset_zoom(self) -> None:
        """重置为基准字号（100%）。"""
        self._zoom_value = self._base_font_size
        self._pct_btn.setText("100%")
        self._slider.value = self._font_size_to_value(self._base_font_size)
        if self._parent_layout is not None and hasattr(
            self._parent_layout, "_apply_font_size_from_zoom"
        ):
            self._parent_layout._apply_font_size_from_zoom(self._base_font_size)

    def sync_from_parent(self) -> None:
        """从父布局当前字号同步滑条和百分比显示。"""
        layout = self._parent_layout
        if layout is None:
            return
        font_size = max(
            self.FONT_SIZE_MIN,
            min(
                self.FONT_SIZE_MAX,
                getattr(layout, "_current_font_size", self._base_font_size),
            ),
        )
        self._zoom_value = font_size
        pct = 100
        if self._base_font_size > 0:
            pct = round(font_size / self._base_font_size * 100)
        self._pct_btn.setText(f"{pct}%")
        self._slider.value = self._font_size_to_value(font_size)

    def hideEvent(self, event: QEvent) -> None:
        super().hideEvent(event)
        self._closing = False


# ──────────────────────────────────────────────────────────────────────────────
# 支持程序化赋值的可变字重滑动条
# ──────────────────────────────────────────────────────────────────────────────

class _WeightSlider(StyledSlider):
    """StyledSlider 子类：在 ``value`` 属性被程序化写入时同样发射 ``value_changed``。"""

    @property
    def value(self) -> float:
        return super().value

    @value.setter
    def value(self, v: float) -> None:
        clamped = max(0.0, min(1.0, v))
        self._track_widget.value = clamped
        self._on_value_changed(clamped)


# ──────────────────────────────────────────────────────────────────────────────
# 可变字重高级弹窗
# ──────────────────────────────────────────────────────────────────────────────

class _WeightPopup(QWidget):
    """可变字重高级弹窗：含纵向滑块 + 数值标签。

    将滑动条 0.0~1.0 线性映射到 100~1000 的字重值。
    """

    WEIGHT_MIN = 100
    WEIGHT_MAX = 1000

    def __init__(
        self,
        parent: Optional["FontPreviewerLayout"] = None,
    ) -> None:
        """初始化可变字重弹出面板。

        Args:
            parent: 父布局实例，用于同步字重。
        """
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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(self._padding, self._padding, self._padding, self._padding)
        layout.setSpacing(6)

        self._value_label = QLabel("400")
        self._value_label.setAlignment(Qt.AlignCenter)
        self._value_label.setStyleSheet(
            f"color: {tm.text.name()}; font-size: 12px; background: transparent;"
        )
        layout.addWidget(self._value_label)

        self._slider = _WeightSlider(
            value=self._weight_to_value(400),
            size="sm",
            orientation=Qt.Vertical,
        )
        self._slider.setFixedSize(24, 140)
        self._slider.value_changed.connect(self._on_slider_changed)
        layout.addWidget(self._slider, alignment=Qt.AlignHCenter)

        layout.addStretch()

    def refresh_theme(self) -> None:
        """刷新主题相关样式（主题切换时由父布局调用）。"""
        # 更新数值标签的文本颜色
        self._value_label.setStyleSheet(
            f"color: {tm.text.name()}; font-size: 12px; background: transparent;"
        )
        # 触发重绘以更新背景/边框颜色
        self.update()

    def _weight_to_value(self, weight: int) -> float:
        """将字重值映射为滑动条 0.0~1.0。"""
        w = max(self.WEIGHT_MIN, min(self.WEIGHT_MAX, weight))
        return (w - self.WEIGHT_MIN) / max(1, self.WEIGHT_MAX - self.WEIGHT_MIN)

    def _value_to_weight(self, value: float) -> int:
        """将滑动条 0.0~1.0 映射为字重值。"""
        return self.WEIGHT_MIN + round(value * (self.WEIGHT_MAX - self.WEIGHT_MIN))

    def paintEvent(self, event) -> None:
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

    def show_animated(self, anchor: QPoint) -> None:
        """从指定锚点（按钮左下角）向下展开弹窗。"""
        pw = 56
        ph = 200
        margin = 4
        x = anchor.x()
        y = anchor.y() + margin

        screen = QApplication.primaryScreen()
        if screen is not None:
            sg = screen.availableGeometry()
            x = max(sg.x() + 8, min(x, sg.right() - pw - 8))
            if y + ph > sg.bottom() - 8:
                y = anchor.y() - ph - margin

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

    def close_animated(self) -> None:
        """带动画关闭弹窗。"""
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

    def _close_and_reset(self) -> None:
        self._slide.finished.disconnect(self._close_and_reset)
        self.close()
        self._closing = False

    def _on_slider_changed(self, val: float) -> None:
        """滑动条变化时同步字重到父布局。"""
        weight = self._value_to_weight(val)
        self._value_label.setText(str(weight))
        if self._parent_layout is not None:
            self._parent_layout._apply_variable_weight(weight)

    def sync_from_parent(self) -> None:
        """从父布局当前字重同步滑条和标签。"""
        layout = self._parent_layout
        if layout is None:
            return
        weight = max(
            self.WEIGHT_MIN,
            min(
                self.WEIGHT_MAX,
                getattr(layout, "_current_variable_weight", 400),
            ),
        )
        self._slider.value = self._weight_to_value(weight)
        self._value_label.setText(str(weight))

    def hideEvent(self, event: QEvent) -> None:
        super().hideEvent(event)
        self._closing = False


# ──────────────────────────────────────────────────────────────────────────────
# 字体预览器主布局
# ──────────────────────────────────────────────────────────────────────────────

class FontPreviewerLayout(QWidget):
    """字体预览器布局。

    顶栏固定 48px，包含标题与常用操作；内容区域使用 QStackedLayout
    在未加载覆盖层与字体渲染预览之间切换。

    Signals:
        close_requested: 关闭预览请求信号（供外部容器响应）。
    """

    close_requested = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        dpi_scale: float | None = None,
        global_font: QFont | None = None,
        settings_manager: Any | None = None,
        standalone: bool = False,
    ) -> None:
        """初始化字体预览器布局。

        Args:
            parent: 父控件。
            dpi_scale: DPI 缩放比例，缺省为 1.0。
            global_font: 全局字体，用于 UI 控件缺省字号计算。
            settings_manager: 设置管理器实例。
            standalone: 是否为独立运行模式。
        """
        super().__init__(parent)
        self._dpi_scale = dpi_scale or 1.0
        self._global_font = global_font or QFont("Segoe UI", DEFAULT_FONT_SIZE)
        self._settings_manager = settings_manager
        self._standalone = standalone

        self._current_file: str = ""
        self.current_font_family: str = ""
        self._current_font_id: int | None = None
        _point_size = self._global_font.pointSize()
        self._current_font_size: int = (
            max(FONT_SIZE_MIN, min(FONT_SIZE_MAX, _point_size))
            if _point_size > 0
            else DEFAULT_FONT_SIZE
        )
        self._preview_text: str = DEFAULT_PREVIEW_TEXT
        self._fullscreen: bool = False
        self._fullscreen_host: Optional[PreviewFullscreenHost] = None
        self._load_thread: FontLoadThread | None = None
        self._load_request_id: int = 0
        self._zoom_popup: QWidget | None = None
        self._text_drawer: StyledDrawer | None = None
        self._ai_drawer: StyledDrawer | None = None
        self._weight_combo: StyledComboBox | None = None
        self._weight_btn: StyledButton | None = None
        self._weight_popup: QWidget | None = None
        self._current_variable_weight: int = 400

        self._current_style: str = "Regular"
        self._available_styles: list[str] = []

        self._init_ui()
        self._connect_theme()
        self._apply_default_panel_styles()

    def _init_ui(self) -> None:
        """初始化顶栏 + 内容区布局。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 顶栏（48px 固定高度，与 PDF / 图片 / 文本预览器一致）
        self._top_bar = _ToolbarFrame()
        self._top_bar.setObjectName("FontPreviewerTopBar")
        self._top_bar.setFixedHeight(48)
        self._build_top_bar()
        layout.addWidget(self._top_bar)

        # 内容区（自适应拉伸）
        # index 0 = 字体渲染预览（_PreviewScrollArea 内部 QTextEdit）
        # index 1 = 未加载覆盖层（提示文字 + standalone 的"选择字体文件"按钮）
        self._content_area = QFrame()
        self._content_area.setObjectName("FontPreviewerContent")
        self._content_stack = QStackedLayout(self._content_area)
        self._content_stack.setContentsMargins(0, 0, 0, 0)

        # ── index 0：字体渲染预览 ──
        self._preview_view = _PreviewScrollArea(self._content_area)
        self._preview_view._text_edit.setPlainText(self._preview_text)
        self._apply_text_edit_theme()
        self._content_stack.addWidget(self._preview_view)

        # ── index 1：未加载覆盖层 ──
        self._overlay = QWidget()
        self._overlay.setObjectName("FontPreviewerOverlay")
        overlay_layout = QVBoxLayout(self._overlay)
        overlay_layout.setAlignment(Qt.AlignCenter)
        overlay_layout.setSpacing(16)

        self._placeholder = QLabel("选择字体文件开始预览")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._refresh_placeholder_style()
        overlay_layout.addWidget(self._placeholder)

        # "选择字体文件"按钮（仅 standalone 模式）
        self._browse_btn: QPushButton | None = None
        if self._standalone:
            self._browse_btn = QPushButton("选择字体文件")
            self._browse_btn.setFixedSize(160, 40)
            self._browse_btn.setCursor(Qt.PointingHandCursor)
            self._browse_btn.clicked.connect(self._on_browse_file)
            self._style_browse_button()
            overlay_layout.addWidget(self._browse_btn, alignment=Qt.AlignCenter)

        self._content_stack.addWidget(self._overlay)

        # 初始显示覆盖层
        self._content_stack.setCurrentIndex(1)

        # 左侧预览文本编辑抽屉
        self._init_text_drawer()
        self._text_drawer.hide()

        # 右侧 AI 抽屉
        self._init_ai_drawer()
        self._ai_drawer.hide()

        layout.addWidget(self._content_area, stretch=1)

        # Ctrl+滚轮字号调整
        self._preview_view._text_edit.font_size_change_requested.connect(
            self._on_wheel_font_size_change
        )

        # 绑定顶栏按钮（缩放弹窗 / 最大化在后续 Wave 中完整实现）
        self._zoom_btn.clicked.connect(self._on_zoom_clicked)
        self._maxsize_btn.clicked.connect(self._on_maxsize_toggle)

        # 应用级事件过滤：缩放弹窗外部点击 / 窗口移动关闭
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def _build_top_bar(self) -> None:
        """构建顶栏：左侧编辑预览文本按钮，右侧 AI / 缩放 / 最大化按钮。"""
        top_layout = QHBoxLayout(self._top_bar)
        top_layout.setContentsMargins(8, 6, 8, 6)
        top_layout.setSpacing(6)

        # 左侧：编辑预览文本图标按钮
        edit_icon = str(icons_dir() / "font.svg")
        self._edit_preview_btn = StyledButton(
            "", variant="ghost", size="sm", icon=edit_icon
        )
        self._edit_preview_btn.setFixedSize(32, 32)
        self._edit_preview_btn.setToolTip("编辑预览文本")
        self._edit_preview_btn.clicked.connect(self._on_edit_preview_text)
        self._top_bar.add_left_button(self._edit_preview_btn)

        # 左侧：字重/样式下拉框
        self._weight_combo = StyledComboBox(items=[], size="sm")
        self._weight_combo.setFixedWidth(110)
        self._weight_combo.setToolTip("字重 / 样式")
        self._weight_combo.selection_made.connect(self._on_weight_selected)
        self._top_bar.add_left_button(self._weight_combo)

        # 左侧：高级可变字重按钮
        self._weight_btn = StyledButton("400", variant="ghost", size="sm")
        self._weight_btn.setFixedHeight(30)
        self._weight_btn.setFixedWidth(50)
        self._weight_btn.setToolTip("高级可变字重")
        self._weight_btn.clicked.connect(self._on_weight_clicked)
        self._top_bar.add_left_button(self._weight_btn)

        # 右侧：AI 图标按钮（打开右侧 AI 抽屉）
        ai_icon = str(icons_dir() / "ai.svg")
        self._ai_btn = StyledButton("", variant="ghost", size="sm", icon=ai_icon)
        self._ai_btn.setFixedSize(32, 32)
        self._ai_btn.setToolTip("AI 功能")
        self._ai_btn.clicked.connect(self._on_ai_clicked)
        self._top_bar.add_right_button(self._ai_btn)

        # 右侧：缩放图标按钮
        zoom_icon = str(icons_dir() / "zoom.svg")
        self._zoom_btn = StyledButton("", variant="ghost", size="sm", icon=zoom_icon)
        self._zoom_btn.setFixedSize(32, 32)
        self._zoom_btn.setToolTip("缩放")
        self._top_bar.add_right_button(self._zoom_btn)

        # 右侧：最大化 / 还原图标按钮
        self._maxsize_icon_path = str(icons_dir() / "maxsize.svg")
        self._minisize_icon_path = str(icons_dir() / "minisize.svg")
        self._maxsize_btn = StyledButton(
            "", variant="ghost", size="sm", icon=self._maxsize_icon_path
        )
        self._maxsize_btn.setFixedSize(32, 32)
        self._maxsize_btn.setToolTip("最大化")
        self._top_bar.add_right_button(self._maxsize_btn)

    def _populate_weight_combo(self) -> None:
        """根据已发现的命名实例填充字重/样式下拉框。"""
        if self._weight_combo is None:
            return
        self._weight_combo.blockSignals(True)
        styles = self._available_styles
        if styles:
            self._weight_combo.addItems(list(styles))
            if "Regular" in styles:
                self._weight_combo.setCurrentText("Regular")
                self._current_style = "Regular"
            else:
                self._weight_combo.setCurrentIndex(0)
                first = self._weight_combo.currentText()
                if first:
                    self._current_style = first
            self._weight_combo.setEnabled(len(styles) > 1)
        else:
            self._weight_combo.addItems(["Regular"])
            self._weight_combo.setCurrentIndex(0)
            self._weight_combo.setEnabled(False)
            self._current_style = "Regular"
        self._weight_combo.blockSignals(False)

    def _on_weight_selected(self, style_name: str) -> None:
        """用户选择新的命名实例时刷新预览。"""
        if not style_name or style_name == self._current_style:
            return
        self._current_style = style_name
        self._apply_preview_font()

    def _on_weight_clicked(self) -> None:
        """高级可变字重按钮点击：展开/收起弹窗。"""
        # 字体未加载时禁用高级字重弹窗
        if not self.current_font_family:
            return
        if self._weight_popup is not None and self._weight_popup.isVisible():
            self._weight_popup.close_animated()
            return
        if self._weight_popup is None:
            self._weight_popup = _WeightPopup(parent=self)
        self._weight_popup.sync_from_parent()
        anchor = self._weight_btn.mapToGlobal(
            QPoint(0, self._weight_btn.height())
        )
        self._weight_popup.show_animated(anchor)

    def _apply_variable_weight(self, weight: int) -> None:
        """应用可变字重到预览文本。"""
        self._current_variable_weight = weight
        if not self.current_font_family:
            return
        font = self._preview_view._text_edit.font()
        font.setWeight(QFont.Weight(weight))
        # 尝试使用可变字体轴
        if hasattr(font, "variableAxisTags") and "wght" in font.variableAxisTags():
            font.setVariableAxis("wght", float(weight))
        self._preview_view._text_edit.setFont(font)
        if self._weight_btn is not None:
            self._weight_btn.setText(str(weight))

    def _init_text_drawer(self) -> None:
        """初始化左侧预览文本编辑抽屉。

        抽屉嵌入在内容区内，包含一个 ``StyledTextarea`` 和一个重置按钮。
        """
        self._text_drawer = StyledDrawer(
            orientation="left",
            size="sm",
            bare=True,
            parent=self._content_area,
        )
        self._text_drawer._panel.setStyleSheet(
            f"#DrawerPanel {{ background-color: {tm.surface.name()}; border: none; }}"
        )

        # 限制面板宽度不超过内容区宽度
        _orig_get_panel_size = self._text_drawer._get_panel_size

        def _constrained_panel_size() -> tuple[int, int]:
            pw, ph = _orig_get_panel_size()
            available_w = self._content_area.width()
            max_pw = max(available_w - 4, 60)
            return min(pw, max_pw), ph

        self._text_drawer._get_panel_size = _constrained_panel_size  # type: ignore[method-assign]

        panel_layout = self._text_drawer._panel.layout()
        panel_layout.setContentsMargins(16, 16, 16, 16)
        panel_layout.setSpacing(12)

        self._preview_text_edit = StyledTextarea(
            text=DEFAULT_PREVIEW_TEXT,
            placeholder="在此输入预览文本…",
            label="预览文本",
        )
        self._preview_text_edit.text_changed.connect(self._on_preview_text_changed)
        panel_layout.addWidget(self._preview_text_edit, stretch=1)

        self._reset_preview_btn = StyledButton("重置", variant="secondary", size="sm")
        self._reset_preview_btn.setFixedHeight(32)
        self._reset_preview_btn.clicked.connect(self._on_reset_preview_text)
        panel_layout.addWidget(self._reset_preview_btn)

    def _init_ai_drawer(self) -> None:
        """初始化右侧 AI 抽屉面板（bare 模式，内容留空）。"""
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

        def _constrained_panel_size() -> tuple[int, int]:
            pw, ph = _orig_get_panel_size()
            available_w = self._content_area.width()
            margin = 4  # 保留 4px 边缘间隙
            max_pw = max(available_w - margin, 60)
            return min(pw, max_pw), ph

        self._ai_drawer._get_panel_size = _constrained_panel_size  # type: ignore[method-assign]

        # 占位文本提示
        self._ai_placeholder = QLabel("AI 功能")
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

    def _toggle_ai_drawer(self) -> None:
        """切换 AI 侧边面板的展开/收起。"""
        if self._ai_drawer is None:
            return
        if self._ai_drawer._is_open:
            self._ai_drawer.close_drawer()
        else:
            self._ai_drawer.open_drawer()

    def _on_ai_clicked(self) -> None:
        """AI 按钮点击：切换 AI 侧边面板的展开/收起。"""
        self._toggle_ai_drawer()

    def _on_preview_text_changed(self, text: str) -> None:
        """预览文本编辑框内容变化时同步到预览区。

        Args:
            text: 当前输入的预览文本。
        """
        self._preview_text = text
        if self._content_stack.currentIndex() == 0:
            self._preview_view._text_edit.setPlainText(self._preview_text)

    def _on_reset_preview_text(self) -> None:
        """重置预览文本为默认值。"""
        self._preview_text_edit.text = DEFAULT_PREVIEW_TEXT
        self._preview_text = DEFAULT_PREVIEW_TEXT
        if self._content_stack.currentIndex() == 0:
            self._preview_view._text_edit.setPlainText(self._preview_text)

    def resizeEvent(self, event) -> None:
        """窗口尺寸变化时同步更新左右两侧抽屉的遮罩和面板尺寸。"""
        super().resizeEvent(event)
        drawer = getattr(self, "_text_drawer", None)
        if drawer is not None and drawer._is_open:
            drawer._update_container_geom()
            cw, ch = drawer._cw, drawer._ch
            drawer.setGeometry(0, 0, cw, ch)
            drawer._backdrop.setGeometry(0, 0, cw, ch)
            pw, _ = drawer._get_panel_size()
            drawer._panel.resize(pw, ch)
            drawer._panel.move(0, 0)

        ai_drawer = getattr(self, "_ai_drawer", None)
        if ai_drawer is not None and ai_drawer._is_open:
            ai_drawer._update_container_geom()
            cw, ch = ai_drawer._cw, ai_drawer._ch
            ai_drawer.setGeometry(0, 0, cw, ch)
            ai_drawer._backdrop.setGeometry(0, 0, cw, ch)
            pw, _ = ai_drawer._get_panel_size()
            ai_drawer._panel.resize(pw, ch)
            # 右侧面板需要重新定位到新右边缘，并更新动画目标位置
            ai_drawer._panel.move(cw - pw, 0)
            ai_drawer._start_pos = QPoint(cw, 0)
            ai_drawer._end_pos = QPoint(cw - pw, 0)

    def eventFilter(self, obj: Any, event: QEvent) -> bool:
        """应用级事件过滤：缩放/字重弹窗在窗口移动/缩放或点击外部时关闭。"""
        if (
            event.type() in (QEvent.Move, QEvent.Resize)
            and (obj is self.window() or obj is self)
            and self._zoom_popup is not None
            and self._zoom_popup.isVisible()
        ):
            self._zoom_popup.close_animated()
        if (
            event.type() in (QEvent.Move, QEvent.Resize)
            and (obj is self.window() or obj is self)
            and self._weight_popup is not None
            and self._weight_popup.isVisible()
        ):
            self._weight_popup.close_animated()
        if event.type() == QEvent.MouseButtonPress:
            me = event if isinstance(event, QMouseEvent) else None
            if (
                me is not None
                and self._zoom_popup is not None
                and self._zoom_popup.isVisible()
            ):
                click_global = me.globalPosition().toPoint()
                pr = QRect(self._zoom_popup.pos(), self._zoom_popup.size())
                if not pr.contains(click_global):
                    self._zoom_popup.close_animated()
            if (
                me is not None
                and self._weight_popup is not None
                and self._weight_popup.isVisible()
            ):
                click_global = me.globalPosition().toPoint()
                pr = QRect(self._weight_popup.pos(), self._weight_popup.size())
                if not pr.contains(click_global):
                    self._weight_popup.close_animated()
        return super().eventFilter(obj, event)

    def _connect_theme(self) -> None:
        """连接主题切换信号。"""
        tm.theme_changed.connect(self._on_theme_changed)

    def _apply_stylesheet(self) -> None:
        """应用预览文本编辑器的主题样式。"""
        self._apply_text_edit_theme()

    def _on_theme_changed(self, theme_name: str) -> None:
        """主题变更时刷新样式。

        Args:
            theme_name: 新的主题名称（"dark" / "light"）。
        """
        self._apply_stylesheet()
        self._style_browse_button()
        self._refresh_placeholder_style()
        self._preview_view._vbar.update()
        self._preview_view._hbar.update()
        self.set_section_styles("", "")
        self._top_bar.update()
        if self._text_drawer is not None:
            self._text_drawer._panel.setStyleSheet(
                f"#DrawerPanel {{ background-color: {tm.surface.name()}; border: none; }}"
            )
        if self._ai_drawer is not None:
            self._ai_drawer._panel.setStyleSheet(
                f"#DrawerPanel {{ background-color: {tm.surface.name()}; border: none; }}"
            )
            self._ai_placeholder.setStyleSheet(
                f"color: {tm.mid.name()}; font-size: 14px; background: transparent;"
                " padding: 24px;"
            )
        # 刷新字重弹窗主题（如果可见）
        if self._weight_popup is not None and self._weight_popup.isVisible():
            self._weight_popup.refresh_theme()
        self.update()

    def set_section_styles(self, fill_color: str, border_color: str) -> None:
        """应用面板样式（主题切换时由 MainWindow 调用）。

        Args:
            fill_color: 填充色（当前未使用，保留签名兼容）。
            border_color: 边框色（当前未使用，保留签名兼容）。
        """
        self._top_bar.setStyleSheet("border-radius: 8px;")
        self._content_area.setStyleSheet(
            f"""
            background-color: {tm.surface.name()};
            border: 1px solid transparent;
            border-radius: 8px;
            """
        )
        self._overlay.setStyleSheet(
            f"background-color: {tm.surface.name()};"
        )
        for _w in (self._top_bar, self._content_area, self._overlay):
            _w.style().unpolish(_w)
            _w.style().polish(_w)

    def _apply_default_panel_styles(self) -> None:
        """应用默认面板样式。"""
        self.set_section_styles("", "")

    def _apply_text_edit_theme(self) -> None:
        """将当前主题颜色应用到预览 QTextEdit。"""
        self._preview_view._text_edit.setStyleSheet(
            f"""
            QTextEdit {{
                background-color: {tm.surface.name()};
                color: {tm.text.name()};
                border: none;
            }}
            """
        )

    def _refresh_placeholder_style(self) -> None:
        """更新占位提示文字颜色。"""
        self._placeholder.setStyleSheet(
            f"color: {tm.mid.name()}; font-size: 14px; background: transparent;"
        )

    def _style_browse_button(self) -> None:
        """应用主题色到"选择字体文件"按钮。"""
        if self._browse_btn is None:
            return
        btn_text = tm.mid.name()
        btn_hover_text = tm.text.name()
        btn_bg = tm.fill.name()
        btn_border = tm.alpha_of(tm.mid, 30).name()
        self._browse_btn.setStyleSheet(
            f"""
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
            """
        )

    def set_file(self, file_path: str) -> None:
        """设置并异步加载要预览的字体文件。

        每次调用都会取消旧加载任务、卸载之前加载的字体，并生成新的
        request_id 以保证结果对应关系。

        Args:
            file_path: 字体文件路径。
        """
        self._current_file = file_path
        self._cancel_load()

        # 卸载旧字体，避免重复加载造成字体数据库膨胀
        if self._current_font_id is not None and self._current_font_id != -1:
            QFontDatabase.removeApplicationFont(self._current_font_id)
            self._current_font_id = None

        self.current_font_family = ""
        self._placeholder.setText(f"正在加载: {Path(file_path).name}")
        self._refresh_placeholder_style()
        self._content_stack.setCurrentIndex(1)

        self._load_font_async()

    def _load_font_async(self) -> None:
        """启动 FontLoadThread 异步加载字体。"""
        self._load_request_id += 1
        thread = FontLoadThread(self)
        thread.set_file(self._current_file)
        thread.set_request_id(self._load_request_id)
        thread.finished.connect(self._on_font_loaded)
        thread.error.connect(self._on_load_error)
        self._load_thread = thread
        thread.start()

    def _cancel_load(self) -> None:
        """取消当前进行中的字体加载任务。"""
        thread = self._load_thread
        if thread is None:
            return
        if thread.isRunning():
            thread.abort()
            thread.wait(300)
        self._load_thread = None

    def _on_font_loaded(
        self,
        request_id: int,
        success: bool,
        font_family: str,
        font_id: int,
    ) -> None:
        """字体加载完成的槽函数。

        Args:
            request_id: 本次加载的请求 ID。
            success: 是否加载成功。
            font_family: 加载到的字体族名称。
            font_id: QFontDatabase 返回的 application font id。
        """
        thread = self.sender()
        if isinstance(thread, FontLoadThread):
            if self._load_thread is thread:
                self._load_thread = None
            thread.deleteLater()

        if request_id != self._load_request_id:
            # 旧请求：卸载其字体，避免资源泄漏
            QFontDatabase.removeApplicationFont(font_id)
            return

        if not success:
            self._on_load_error(request_id, "字体加载失败")
            return

        self._current_font_id = font_id
        self.current_font_family = font_family

        self._available_styles = list(QFontDatabase.styles(self.current_font_family))
        if "Regular" not in self._available_styles:
            self._current_style = ""
        else:
            self._current_style = "Regular"

        self._update_preview()

    def _on_load_error(self, request_id: int, error_msg: str) -> None:
        """字体加载失败的槽函数。

        Args:
            request_id: 本次加载的请求 ID。
            error_msg: 错误信息。
        """
        thread = self.sender()
        if isinstance(thread, FontLoadThread):
            if self._load_thread is thread:
                self._load_thread = None
            thread.deleteLater()

        if request_id != self._load_request_id:
            return

        self._placeholder.setText(error_msg)
        self._placeholder.setStyleSheet(
            f"color: {tm.danger.name()}; font-size: 14px; background: transparent;"
        )
        self._content_stack.setCurrentIndex(1)

    def _apply_preview_font(self) -> None:
        """将当前字体族、样式和字号应用到预览 QTextEdit。"""
        if not self.current_font_family:
            return
        if self._current_style:
            font = QFontDatabase.font(
                self.current_font_family, self._current_style, self._current_font_size
            )
        else:
            font = QFont()
            font.setFamily(self.current_font_family)
            font.setPointSize(self._current_font_size)
        self._preview_view._text_edit.setFont(font)
        self._sync_weight_button()

    def _sync_weight_button(self) -> None:
        """同步高级可变字重按钮的显示值为当前字体的字重，并根据字体加载状态启用/禁用按钮。"""
        if self._weight_btn is None:
            return
        if not self.current_font_family:
            # 字体未加载时禁用高级字重按钮
            self._weight_btn.setEnabled(False)
            self._weight_btn.setText("400")
            return
        self._weight_btn.setEnabled(True)
        font = self._preview_view._text_edit.font()
        weight = font.weight()
        # QFont.weight() returns int 0-99? In Qt returns QFont.Weight enum (int)
        self._weight_btn.setText(str(weight))

    def _update_preview(self) -> None:
        """将加载好的字体应用到预览 QTextEdit 并切换到预览视图。"""
        if not self.current_font_family:
            return

        self._apply_preview_font()
        self._populate_weight_combo()
        self._preview_view._text_edit.setPlainText(self._preview_text)

        self._placeholder.setText("选择字体文件开始预览")
        self._refresh_placeholder_style()
        self._content_stack.setCurrentIndex(0)

    def _on_browse_file(self) -> None:
        """独立模式下打开文件选择对话框选择字体文件。"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择字体文件",
            "",
            FONT_FILTERS,
        )
        if file_path:
            self.set_file(file_path)

    def _on_edit_preview_text(self) -> None:
        """切换左侧预览文本编辑抽屉的展开/收起状态。"""
        if self._text_drawer is None:
            return
        if self._text_drawer._is_open:
            self._text_drawer.close_drawer()
        else:
            self._text_drawer.open_drawer()

    def _on_zoom_clicked(self) -> None:
        """缩放按钮点击：展开/收起字号缩放弹窗。"""
        if self._zoom_popup is not None and self._zoom_popup.isVisible():
            self._zoom_popup.close_animated()
            return
        if self._zoom_popup is None:
            self._zoom_popup = _ZoomPopup(parent=self)
        self._zoom_popup.sync_from_parent()
        tb_br = self._top_bar.mapToGlobal(
            QPoint(self._top_bar.width(), self._top_bar.height())
        )
        self._zoom_popup.show_animated(tb_br)

    def _apply_font_size_from_zoom(self, font_size: int) -> None:
        """由缩放弹窗驱动，设置新的预览字号。

        Args:
            font_size: 目标字号（像素）。
        """
        self._current_font_size = max(
            FONT_SIZE_MIN, min(FONT_SIZE_MAX, int(font_size))
        )
        self._apply_preview_font()

    def _on_wheel_font_size_change(self, delta: int) -> None:
        """Ctrl+滚轮调整字号。

        Args:
            delta: 字号变化量，+1 或 -1。
        """
        new_size = max(
            FONT_SIZE_MIN, min(FONT_SIZE_MAX, self._current_font_size + delta)
        )
        if new_size == self._current_font_size:
            return
        self._current_font_size = new_size
        self._apply_preview_font()
        if self._zoom_popup is not None:
            self._zoom_popup.sync_from_parent()

    def _on_maxsize_toggle(self) -> None:
        """切换全屏 / 还原窗口。

        全屏时把自身分离到独立 frameless 宿主窗口（PreviewFullscreenHost），
        而不是全屏主窗口；退出时还原回原内嵌布局。
        """
        if not self._fullscreen:
            self._enter_fullscreen()
        else:
            self._exit_fullscreen()

    def _enter_fullscreen(self) -> None:
        """分离到独立 frameless 全屏窗口。"""
        if self._fullscreen_host is None:
            self._fullscreen_host = PreviewFullscreenHost()
            self._fullscreen_host.escapePressed.connect(self._on_maxsize_toggle)
            self._fullscreen_host.closed.connect(self._on_maxsize_toggle)
        if not self._fullscreen_host.attach(self):
            return
        self._fullscreen_host.show_fullscreen()
        self._maxsize_btn.set_svg_icon(self._minisize_icon_path)
        self._maxsize_btn.setToolTip("还原")
        self._fullscreen = True

    def _exit_fullscreen(self) -> None:
        """退出全屏：还原回主窗口内嵌布局。"""
        if self._fullscreen_host is None:
            self._fullscreen = False
            return
        self._fullscreen_host.exit_fullscreen()
        self._fullscreen_host.deleteLater()
        self._fullscreen_host = None
        self._maxsize_btn.set_svg_icon(self._maxsize_icon_path)
        self._maxsize_btn.setToolTip("最大化")
        self._fullscreen = False

    def cleanup(self) -> None:
        """清理资源；若处于全屏先退出，避免内嵌 widget 被直接销毁。"""
        if self._fullscreen:
            self._exit_fullscreen()


# ──────────────────────────────────────────────────────────────────────────────
# 独立测试入口
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = QApplication(sys.argv)

    window = QWidget()
    window.setWindowTitle("字体预览器 (独立测试)")
    window.resize(960, 600)

    # 居中显示
    screen = app.primaryScreen().geometry()
    x = (screen.width() - 960) // 2 + screen.x()
    y = (screen.height() - 600) // 2 + screen.y()
    window.move(x, y)

    previewer = FontPreviewerLayout(standalone=True)
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

    # 在 offscreen 平台下自动退出，方便 CI / 冒烟测试
    if app.platformName().lower() == "offscreen":
        def _exit_offscreen() -> None:
            window.close()
            app.quit()
        QTimer.singleShot(300, _exit_offscreen)

    sys.exit(app.exec())
