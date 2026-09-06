"""
设置布局 — 设置窗口的内容区域（使用 StyledSidebar）
"""

from __future__ import annotations

import copy
import os
import time

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QFrame, QLabel, QStackedWidget,
    QApplication, QScrollArea, QFileDialog,
)
from PySide6.QtCore import (
    Qt, Signal, QRectF, QPropertyAnimation, QEasingCurve, Property, QPoint,
    QEvent, QObject,
)
from PySide6.QtGui import (
    QPainter, QColor, QPaintEvent, QPen, QFont, QHideEvent, QCloseEvent,
    QConicalGradient, QBrush,
)

from theme import tm
from theme.system_accent import get_system_accent_color
from components.styled_sidebar import StyledSidebar
from components.styled_toggle import StyledToggle
from components.styled_button import StyledButton
from components.styled_scroll_area import StyledScrollBar, StyledScrollArea
from components.styled_segmented import StyledSegmented
from components.styled_slider import StyledSlider
from components.settings_card import SettingsRow
from components.styled_dialog import create_danger_dialog
from components.styled_color_picker import _ColorPanel
from components.custom_background import (
    BACKGROUND_DIR_NAME,
    import_custom_background_image,
)
from components.theme_transition_overlay import ThemeTransitionOverlay
from freeassetfilter.core.managers.settings_manager_v2 import (
    DEFAULT_SETTINGS_V2,
    SettingsManagerV2,
)
from freeassetfilter.ui.layout.settings_staging_cache import SettingsStagingCache
from freeassetfilter.utils.path_utils import get_app_data_path


# ── 自定义图像背景可调参数（与 components/custom_background 对齐） ──
# 模糊半径 px（整数 0-200，默认 0 不模糊），透明度 %（0-100，默认 80% 很透明）。
IMAGE_BG_BLUR_MAX = 200
IMAGE_BG_BLUR_DEFAULT = 0
IMAGE_BG_TRANSPARENCY_DEFAULT = 80


def _normalize_bg_blur(value: object) -> int:
    """归一化图像背景模糊半径到 0~200px（整数）。

    Args:
        value: 待归一化值（非法输入回退默认值）。

    Returns:
        int: 钳制后的模糊半径。
    """
    try:
        blur = int(round(float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return IMAGE_BG_BLUR_DEFAULT
    return max(0, min(IMAGE_BG_BLUR_MAX, blur))


def _normalize_bg_transparency(value: object) -> int:
    """归一化图像背景透明度到 0~100。

    Args:
        value: 待归一化值（非法输入回退默认值）。

    Returns:
        int: 钳制后的透明度百分比。
    """
    try:
        transparency = int(round(float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return IMAGE_BG_TRANSPARENCY_DEFAULT
    return max(0, min(100, transparency))


# ── 预设主题色（参考旧 theme_editor.py） ──────────────────────────────
# "auto" 表示跟随 Windows 系统强调色（DWM ColorizationColor）。
PRESET_ACCENT_COLORS = [
    {"name": "自动", "color": "auto"},
    {"name": "活力蓝", "color": "#007AFF"},
    {"name": "热情红", "color": "#DD5940"},
    {"name": "蜂蜜黄", "color": "#EAB348"},
    {"name": "清新绿", "color": "#78B86C"},
    {"name": "魅力紫", "color": "#9554CF"},
    {"name": "清雅墨", "color": "#5A6C8B"},
]


class _FloatingScrollArea(QScrollArea):
    """设置页滚动区 — 浮动 StyledScrollBar + 丝滑滚动（参考文件选择器模式）。

    - 隐藏 QScrollArea 原生滚动条，由浮动 ``StyledScrollBar`` 接管
      （自绘圆角胶囊 + hover 展开 + 拖拽）。
    - 通过 ``attach_floating_bar_region`` 将浮动条锚定到所在外观卡片
      （#SettingsCard）右侧边框内侧——与文件选择器/文件池浮动滚动条的
      间距约定一致：右缘水平贴边（间隙 0）、上/下内缩 10*dpi。
    - 通过 ``StyledScrollArea.apply_to`` 施加平滑滚轮/触摸手势
      （QScroller 丝滑减速 + 边界弹性回弹），与文件选择器一致。
    - 背景保持透明，透出设置卡片底色；滚动条仅在内容溢出时可见。

    注意：本类不得重写 ``eventFilter``——PySide6 下 QScrollArea 子类一旦
    覆盖该虚函数，其构造期样式表 polish 路径会触发原生访问冲突（构造阶段
    虚表分发到尚未就绪的 Python 对象）。区域尺寸变化必然传导为滚动区自身
    的 resizeEvent，因此浮动条重定位挂接现有事件链即可，无需事件过滤器。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.viewport().setAutoFillBackground(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # 浮动条相对所在区域内容矩形（边框内侧）的上/下内缩：与文件选择器/
        # 文件池浮动滚动条几何约定一致（10*dpi）；右缘水平贴边（间隙 0）
        self._edge_padding = int(10 * self._dpi_scale())
        # 锚定区域（外观卡片 #SettingsCard）；未锚定时回退为滚动区自身
        self._region: QWidget | None = None

        # 浮动滚动条：默认先挂在滚动区自身，attach_floating_bar_region
        # 会将父级改挂到锚定卡片上，使其贴卡片右缘悬浮（内容之上）
        self._floating_bar = StyledScrollBar(self)
        self._floating_bar.setFixedWidth(max(6, int(8 * self._dpi_scale())))
        self._floating_bar.raise_()

        # 与隐藏的原生垂直滚动条双向同步（value 相同不重发，无递归风险）
        vbar = self.verticalScrollBar()
        self._floating_bar.setRange(vbar.minimum(), vbar.maximum())
        self._floating_bar.setSingleStep(1)  # 平滑滚动的细粒度步进
        self._floating_bar.setPageStep(vbar.pageStep())
        vbar.rangeChanged.connect(self._on_range_changed)
        self._floating_bar.valueChanged.connect(vbar.setValue)
        vbar.valueChanged.connect(self._floating_bar.setValue)
        self._floating_bar.setVisible(vbar.maximum() > vbar.minimum())

        self._scroller_ready = False

    def attach_floating_bar_region(self, region: QWidget) -> None:
        """把浮动滚动条挂到所在区域（外观卡片 #SettingsCard）上并贴其右缘。

        文件选择器/文件池的浮动条均以各自内容区边框内侧为参照（右缘水平
        间隙 0、上/下内缩 edge_padding），这里把卡片内容矩形作为同等参照，
        使设置页滚动条与主窗口两侧滚动条的边缘间距逐像素一致。
        卡片缩放必然传导为滚动区 resizeEvent，由既有事件链触发重定位。
        """
        if region is self._region:
            return
        self._region = region
        self._floating_bar.setParent(region)
        self._floating_bar.raise_()
        self._reposition_bar()

    @staticmethod
    def _dpi_scale() -> float:
        """获取 DPI 缩放系数（未标注时回落 1.0）。"""
        app = QApplication.instance()
        return getattr(app, "dpi_scale_factor", 1.0) if app else 1.0

    # ── 原生滚动条 → 浮动滚动条 同步 ─────────────────────────────────

    def _on_range_changed(self, minimum: int, maximum: int) -> None:
        """内容滚动范围变化：同步范围/步进并按需显隐浮动滚动条。"""
        vbar = self.verticalScrollBar()
        self._floating_bar.setRange(minimum, maximum)
        self._floating_bar.setPageStep(vbar.pageStep())
        self._floating_bar.setValue(vbar.value())
        self._floating_bar.setVisible(maximum > minimum)
        self._reposition_bar()

    # ── 几何：浮动滚动条贴所在区域右缘 ───────────────────────────────

    def _reposition_bar(self) -> None:
        """把浮动滚动条贴到所在区域（默认滚动区自身）右缘。

        内容不足时保持隐藏。几何以区域内容矩形（边框内侧）为参照：
        右缘水平贴边（间隙 0）、上/下内缩 edge_padding，
        与文件选择器/文件池浮动滚动条的间距约定逐像素一致。
        """
        bar = self._floating_bar
        if bar.parent() is None:
            return
        region = self._region if self._region is not None else self
        if region.width() <= 0 or region.height() <= 0:
            return
        pad = self._edge_padding
        cr = region.contentsRect()
        bar.setGeometry(
            cr.x() + cr.width() - bar.width(),
            cr.y() + pad,
            bar.width(),
            max(0, cr.height() - 2 * pad),
        )
        bar.raise_()

    # ── 事件：尺寸变化重摆滚动条；首次显示施加丝滑滚动 ────────────────

    def setWidget(self, widget: QWidget) -> None:
        super().setWidget(widget)
        # 新内容装载后立即同步范围（等待 rangeChanged 可能有帧延迟）
        vbar = self.verticalScrollBar()
        self._on_range_changed(vbar.minimum(), vbar.maximum())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._scroller_ready:
            self._scroller_ready = True
            # 平滑滚轮 + 触摸手势（与文件选择器同一套 QScroller 配置）
            StyledScrollArea.apply_to(self, enable_mouse_drag=False)
        self._reposition_bar()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # viewport 高度变化会改变 pageStep，一并同步
        self._floating_bar.setPageStep(self.verticalScrollBar().pageStep())
        self._reposition_bar()


class AccentColorButton(QWidget):
    """主题色选择圆形按钮 — 自绘圆形 + 选中描边。"""

    clicked = Signal(str)  # 发送颜色 hex 字符串

    def __init__(
        self,
        color_hex: str,
        name: str = "",
        center_text: str = "",
        value: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._color_hex = color_hex
        self._value = value if value else color_hex
        self._name = name
        self._center_text = center_text
        self._selected = False
        self._hovered = False
        self._hover_progress = 0.0
        self.setFixedSize(40, 40)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_StyledBackground, False)

        self._hover_anim = QPropertyAnimation(self, b"hover_progress")
        self._hover_anim.setDuration(180)
        self._hover_anim.setEasingCurve(QEasingCurve.InOutCubic)

    @Property(float)
    def hover_progress(self):
        return self._hover_progress

    @hover_progress.setter
    def hover_progress(self, value: float):
        self._hover_progress = value
        self.update()

    @property
    def color_hex(self) -> str:
        """Return the logical value (may be "auto" or a concrete #RRGGBB)."""
        return self._value

    @property
    def selected(self) -> bool:
        return self._selected

    @selected.setter
    def selected(self, value: bool):
        self._selected = value
        self.update()

    def enterEvent(self, event):
        self._hovered = True
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_progress)
        self._hover_anim.setEndValue(1.0)
        self._hover_anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_progress)
        self._hover_anim.setEndValue(0.0)
        self._hover_anim.start()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._color_hex)
            event.accept()
        else:
            super().mousePressEvent(event)

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setClipRect(self.rect())
        rect = QRectF(6, 6, self.width() - 12, self.height() - 12)

        # hover 时缩放
        scale = 1.0 + 0.1 * self._hover_progress
        cx = rect.center().x()
        cy = rect.center().y()
        sw = rect.width() * scale
        sh = rect.height() * scale
        scaled_rect = QRectF(cx - sw / 2, cy - sh / 2, sw, sh)

        # 外圈描边（选中时）
        if self._selected:
            pen = QPen(tm.accent, 3)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(scaled_rect.adjusted(-3, -3, 3, 3))

        # 主色圆
        painter.setPen(Qt.NoPen)
        bg_color = QColor(self._color_hex)
        painter.setBrush(bg_color)
        painter.drawEllipse(scaled_rect)

        # 中央文字（例如自动模式的 "A"）
        if self._center_text:
            text_color = self._contrast_text_color(bg_color)
            font = QFont("Microsoft YaHei UI", 14, QFont.Bold)
            painter.setFont(font)
            painter.setPen(text_color)
            painter.drawText(scaled_rect, Qt.AlignCenter, self._center_text)
        elif self._selected:
            # 选中对勾
            painter.setPen(
                QPen(QColor("#FFFFFF"), 2.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            )
            painter.setBrush(Qt.NoBrush)
            cx = scaled_rect.center().x()
            cy = scaled_rect.center().y()
            painter.drawLine(cx - 5, cy, cx - 1, cy + 4)
            painter.drawLine(cx - 1, cy + 4, cx + 6, cy - 4)
        painter.end()

    @staticmethod
    def _contrast_text_color(bg: QColor) -> QColor:
        """Return white or black text color depending on background luminance."""
        luminance = 0.299 * bg.red() + 0.587 * bg.green() + 0.114 * bg.blue()
        return QColor("#FFFFFF") if luminance < 128 else QColor("#000000")


class CustomAccentButton(QWidget):
    """自定义主题色按钮 — 360° 全色谱渐变圆 + 选中描边。"""

    clicked = Signal()

    def __init__(self, selected: bool = False, parent=None):
        super().__init__(parent)
        self._selected = selected
        self.setFixedSize(40, 40)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_StyledBackground, False)

    @property
    def selected(self) -> bool:
        return self._selected

    @selected.setter
    def selected(self, value: bool):
        self._selected = value
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
        else:
            super().mousePressEvent(event)

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setClipRect(self.rect())
        rect = QRectF(6, 6, self.width() - 12, self.height() - 12)

        # 360° 全色谱锥形渐变：红 → 黄 → 绿 → 青 → 蓝 → 紫 → 红
        gradient = QConicalGradient(rect.center(), 0)
        gradient.setColorAt(0.0 / 6, QColor("#FF0000"))
        gradient.setColorAt(1.0 / 6, QColor("#FFFF00"))
        gradient.setColorAt(2.0 / 6, QColor("#00FF00"))
        gradient.setColorAt(3.0 / 6, QColor("#00FFFF"))
        gradient.setColorAt(4.0 / 6, QColor("#0000FF"))
        gradient.setColorAt(5.0 / 6, QColor("#FF00FF"))
        gradient.setColorAt(6.0 / 6, QColor("#FF0000"))

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(gradient))
        painter.drawEllipse(rect)

        # 选中描边
        if self._selected:
            pen = QPen(tm.accent, 3)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(rect.adjusted(-3, -3, 3, 3))
        painter.end()


class _DarkToggleCompat(QObject):
    """旧深色开关的兼容垫片（非界面组件，仅保存量调用方）。

    新版设置已改用「白天 / 夜晚 / 跟随系统」三段控件，本类仅保留
    ``checked`` 读写与 ``toggled`` 信号，使 ``page._dark_toggle`` 与
    ``page._on_dark_toggle`` 的存量访问继续有效。读返回当前实际生效
    值（跟随模式下为系统解析结果），写等价于暂存夜晚/白天偏好
    （点击确定才生效）。
    """

    toggled = Signal(bool)

    def __init__(self, page: AppearanceSettingsPage) -> None:
        """初始化垫片。

        Args:
            page: 所属外观设置页（读写时代理到其主题方法）。
        """
        super().__init__(page)
        self._page = page

    @property
    def checked(self) -> bool:
        """当前实际是否为深色。

        Returns:
            深色返回 True，否则返回 False。
        """
        return tm.is_dark_theme()

    @checked.setter
    def checked(self, value: bool) -> None:
        self._page._apply_theme_mode("dark" if value else "light")
        self._page._sync_theme_segment()
        try:
            self.toggled.emit(bool(value))
        except Exception:
            pass


class AppearanceSettingsPage(QWidget):
    """外观设置页面 — 深色模式三段选择 + 主题色选择（暂存缓存优先）。

    深色模式为「白天 / 夜晚 / 跟随系统」三态分段控件（与「窗口背景」
    分段同款 ``StyledSegmented`` pill 样式）。暂存隔离铁律：所有控件
    修改只写入 ``SettingsStagingCache``，未提交前不触碰 ``tm``、主窗口
    与 ``SettingsManagerV2`` 磁盘状态；点击确定才全局应用并落盘。
    控件展示以缓存为准。
    """

    # 深色模式三态与分段索引的双向映射（顺序与 _build_ui 添加顺序一致）。
    THEME_MODES: tuple[str, ...] = ("light", "dark", "system")
    THEME_LABELS: tuple[str, ...] = ("白天", "夜晚", "跟随系统")
    THEME_INDEX: dict[str, int] = {"light": 0, "dark": 1, "system": 2}

    def __init__(self, parent=None, staging_cache: SettingsStagingCache | None = None):
        super().__init__(parent)
        if staging_cache is None:
            staging_cache = SettingsStagingCache()
            v2 = SettingsManagerV2()
            snapshot = copy.deepcopy(v2.load())
            staging_cache.begin(snapshot)
        elif not staging_cache.is_active():
            v2 = SettingsManagerV2()
            staging_cache.begin(copy.deepcopy(v2.load()))
        self._staging_cache = staging_cache
        self._color_buttons: list[AccentColorButton] = []
        self._custom_btn: CustomAccentButton | None = None
        self._custom_panel: _ColorPanel | None = None
        self._current_accent: str = ""  # tracked for save
        self._event_filter_installed: bool = False  # track event filter state
        self._event_filter_targets: list[QObject] = []
        # 窗口背景状态（初值在 _build_ui 中从 V2 覆盖）
        self._bg_mode: str = "mica"        # "mica"（云母） / "image"（图像） / "minimalist"（简约）
        self._bg_image_name: str = ""      # 持久化目录中的背景图片文件名
        self._bg_ambient: bool = True      # 弥散氛围开关（简约模式下将主题色作为背景氛围层）
        self._ambient_toggle: StyledToggle | None = None  # 弥散氛围开关控件
        self._ambient_row: QWidget | None = None          # 弥散氛围行容器（仅简约模式可见）
        self._bg_updating: bool = False    # 编程式切换分段控件的守卫标志
        # 图像背景可调参数（初值在 _build_ui 中从暂存缓存覆盖）
        self._bg_blur: int = IMAGE_BG_BLUR_DEFAULT  # 模糊半径 px（整数 0-200）
        self._bg_transparency: int = IMAGE_BG_TRANSPARENCY_DEFAULT  # 透明度 %（0-100）
        self._bg_params_updating: bool = False  # 编程式设置滑动条的守卫标志
        self._bg_params_row: QFrame | None = None  # 参数区容器（仅图像模式可见）
        self._blur_slider: StyledSlider | None = None
        self._transparency_slider: StyledSlider | None = None
        self._blur_value_label: QLabel | None = None
        self._transparency_value_label: QLabel | None = None
        # 深色模式三态状态（初值在 _build_ui 中从暂存缓存覆盖）
        self._theme_mode: str = "dark"   # "light"（白天） / "dark"（夜晚） / "system"（跟随系统）
        self._theme_updating: bool = False  # 编程式切换主题分段控件的守卫标志
        self._theme_segmented: StyledSegmented | None = None
        self._build_ui()
        self._load_v2_settings()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)

        # ── 深色模式三段选择（白天 / 夜晚 / 跟随系统）──
        # 与「窗口背景」分段同款 StyledSegmented（pill/sm），视觉与交互一致。
        dark_row = QFrame()
        dark_row.setStyleSheet("background: transparent; border: none;")
        dark_layout = QHBoxLayout(dark_row)
        dark_layout.setContentsMargins(0, 0, 0, 0)
        dark_layout.setSpacing(12)

        dark_label = QLabel("深色模式")
        dark_label.setStyleSheet(
            f"background: transparent; border: none;"
            f"color: {tm.text.name()}; font-size: 13px; font-weight: 500;"
        )
        dark_layout.addWidget(dark_label)
        dark_layout.addStretch()

        # 从暂存缓存读取初始偏好（缓存已在 __init__ 中以 V2 快照开启）；
        # 旧快照缺 theme_mode 时由 appearance.theme 迁移。
        saved_accent = self._staging_cache.get("appearance.accent_color", "#007AFF")
        self._theme_mode = self._resolve_staged_theme_mode()

        self._theme_segmented = StyledSegmented(variant="pill", size="sm")
        for label in self.THEME_LABELS:
            self._theme_segmented.add_segment(label)
        self._theme_segmented.current_changed.connect(
            self._on_theme_segment_changed
        )
        # 守卫内编程式切换，避免初始化期间触发应用/持久化逻辑。
        self._theme_updating = True
        try:
            self._theme_segmented.set_current_index(
                self.THEME_INDEX.get(self._theme_mode, 1), animate=False
            )
        finally:
            self._theme_updating = False
        dark_layout.addWidget(self._theme_segmented)

        # 存量兼容：保留 _dark_toggle 属性（非界面垫片，不加入布局），
        # 供旧测试/外部调用以 checked/toggled 方式读写实际生效值。
        self._dark_toggle = _DarkToggleCompat(self)

        layout.addWidget(dark_row)

        # ── 主题色选择 ──
        accent_label = QLabel("主题色")
        accent_label.setStyleSheet(
            f"background: transparent; border: none;"
            f"color: {tm.text.name()}; font-size: 13px; font-weight: 500;"
        )
        layout.addWidget(accent_label)

        # 单行布局：所有配色按钮放在同一行
        color_row = QHBoxLayout()
        color_row.setContentsMargins(0, 0, 0, 0)
        color_row.setSpacing(8)  # 缩小间距

        self._current_accent = saved_accent

        for i, preset in enumerate(PRESET_ACCENT_COLORS):
            is_auto = preset["color"].lower() == "auto"
            display_color = get_system_accent_color() if is_auto else preset["color"]
            center_text = "A" if is_auto else ""
            btn = AccentColorButton(
                display_color,
                preset["name"],
                center_text=center_text,
                value=preset["color"],
            )
            btn.clicked.connect(self._on_color_clicked)
            if preset["color"].upper() == saved_accent.upper():
                btn.selected = True
            color_row.addWidget(btn)
            self._color_buttons.append(btn)

        # 自定义颜色按钮（360° 全色谱渐变）
        self._custom_btn = CustomAccentButton(selected=False)
        self._custom_btn.clicked.connect(self._on_custom_color_clicked)
        color_row.addWidget(self._custom_btn)

        color_row.addStretch()  # 右侧弹性空间
        layout.addLayout(color_row)

        # ── 窗口背景（简约 / 云母 / 图像，与深色模式同行布局） ──
        # 云母参数为按主题固定的产品定值（见 main_window.FIXED_MICA_PARAMS），
        # 设置页不再提供滑动条配置。初值来自暂存缓存（隔离层唯一数据源）。
        saved_bg = self._staging_cache.get("appearance.background", {}) or {}
        saved_bg_mode = saved_bg.get("mode", "mica")
        self._bg_mode = saved_bg_mode if saved_bg_mode in ("mica", "image", "minimalist") else "mica"
        self._bg_image_name = str(saved_bg.get("image", "") or "")
        _raw_ambient = saved_bg.get("ambient", True)
        self._bg_ambient = _raw_ambient if isinstance(_raw_ambient, bool) else bool(_raw_ambient)
        self._bg_blur = _normalize_bg_blur(saved_bg.get("blur", IMAGE_BG_BLUR_DEFAULT))
        self._bg_transparency = _normalize_bg_transparency(
            saved_bg.get("transparency", IMAGE_BG_TRANSPARENCY_DEFAULT)
        )

        bg_row = QFrame()
        bg_row.setStyleSheet("background: transparent; border: none;")
        bg_title_layout = QHBoxLayout(bg_row)
        bg_title_layout.setContentsMargins(0, 0, 0, 0)
        bg_title_layout.setSpacing(12)

        bg_label = QLabel("窗口背景")
        bg_label.setStyleSheet(
            f"background: transparent; border: none;"
            f"color: {tm.text.name()}; font-size: 13px; font-weight: 500;"
        )
        bg_title_layout.addWidget(bg_label)
        bg_title_layout.addStretch()
        self._bg_label = bg_label

        self._bg_segmented = StyledSegmented(variant="pill", size="sm")
        self._bg_segmented.add_segment("简约")
        self._bg_segmented.add_segment("云母")
        self._bg_segmented.add_segment("图像")
        self._bg_segmented.current_changed.connect(self._on_bg_segment_changed)
        # 初始选中项来自 V2：简约 → 索引 0（默认选中，无需切换），
        # 云母 → 索引 1，图像 → 索引 2。守卫内编程式切换，避免初始化期间
        # 触发 _on_bg_segment_changed 的应用/持久化逻辑。
        self._bg_updating = True
        try:
            if self._bg_mode == "mica":
                self._bg_segmented.set_current_index(1, animate=False)
            elif self._bg_mode == "image":
                self._bg_segmented.set_current_index(2, animate=False)
        finally:
            self._bg_updating = False
        bg_title_layout.addWidget(self._bg_segmented)
        layout.addWidget(bg_row)

        # 图片行（仅 image 模式可见）：当前文件名 + 「选择图片…」按钮
        self._bg_image_row = QFrame()
        self._bg_image_row.setStyleSheet("background: transparent; border: none;")
        bg_row_layout = QHBoxLayout(self._bg_image_row)
        bg_row_layout.setContentsMargins(0, 0, 0, 0)
        bg_row_layout.setSpacing(12)

        self._bg_file_label = QLabel(
            self._bg_image_name if self._bg_image_name else "未设置"
        )
        self._bg_file_label.setStyleSheet(
            f"background: transparent; border: none;"
            f"color: {tm.text.name()}; font-size: 13px;"
        )
        bg_row_layout.addWidget(self._bg_file_label)
        bg_row_layout.addStretch()

        self._bg_choose_btn = StyledButton("选择图片…", variant="secondary", size="sm")
        self._bg_choose_btn.clicked.connect(self._on_choose_bg_image_clicked)
        bg_row_layout.addWidget(self._bg_choose_btn)
        layout.addWidget(self._bg_image_row)

        # 图像参数区（仅 image 模式可见）：模糊度 / 透明度可拖动滑动条。
        # 默认模糊度 0（不模糊）、透明度 80%（很透明）。
        self._bg_params_row = QFrame()
        self._bg_params_row.setStyleSheet("background: transparent; border: none;")
        params_layout = QVBoxLayout(self._bg_params_row)
        params_layout.setContentsMargins(0, 0, 0, 0)
        params_layout.setSpacing(8)

        label_style = (
            "background: transparent; border: none;"
            f"color: {tm.text.name()}; font-size: 13px;"
        )
        value_style = (
            "background: transparent; border: none;"
            f"color: {tm.text.name()}; font-size: 12px;"
        )

        blur_row = QHBoxLayout()
        blur_row.setContentsMargins(0, 0, 0, 0)
        blur_row.setSpacing(12)
        blur_name = QLabel("模糊度")
        blur_name.setStyleSheet(label_style)
        blur_name.setFixedWidth(48)
        blur_row.addWidget(blur_name)
        self._blur_slider = StyledSlider(
            value=self._bg_blur / IMAGE_BG_BLUR_MAX, size="sm"
        )
        self._blur_slider.value_changed.connect(self._on_blur_changed)
        blur_row.addWidget(self._blur_slider, stretch=1)
        self._blur_value_label = QLabel(f"{self._bg_blur:g}")
        self._blur_value_label.setStyleSheet(value_style)
        self._blur_value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._blur_value_label.setFixedWidth(44)
        blur_row.addWidget(self._blur_value_label)
        params_layout.addLayout(blur_row)

        opacity_row = QHBoxLayout()
        opacity_row.setContentsMargins(0, 0, 0, 0)
        opacity_row.setSpacing(12)
        opacity_name = QLabel("透明度")
        opacity_name.setStyleSheet(label_style)
        opacity_name.setFixedWidth(48)
        opacity_row.addWidget(opacity_name)
        self._transparency_slider = StyledSlider(
            value=self._bg_transparency / 100.0, size="sm"
        )
        self._transparency_slider.value_changed.connect(
            self._on_transparency_changed
        )
        opacity_row.addWidget(self._transparency_slider, stretch=1)
        self._transparency_value_label = QLabel(f"{self._bg_transparency}%")
        self._transparency_value_label.setStyleSheet(value_style)
        self._transparency_value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._transparency_value_label.setFixedWidth(44)
        opacity_row.addWidget(self._transparency_value_label)
        params_layout.addLayout(opacity_row)

        layout.addWidget(self._bg_params_row)

        # 弥散氛围行（仅简约模式可见）：开关实时生效并持久化
        self._ambient_row = SettingsRow(
            title="弥散氛围",
            description="启用后,将选取主题色作为背景氛围层提升质感",
        )
        self._ambient_toggle = StyledToggle(checked=self._bg_ambient, size="default")
        self._ambient_toggle.toggled.connect(self._on_ambient_toggled)
        self._ambient_row.set_control(self._ambient_toggle)
        layout.addWidget(self._ambient_row)

        # 初始按模式设置图片行与弥散氛围行的可见性（不触发应用逻辑）
        self._update_bg_ui_state()

        layout.addStretch()

    # ── 窗口背景：模式切换与图片导入 ─────────────────────────────────

    def _find_main_window(self) -> QWidget | None:
        """定位主窗口（按 _mica_background 属性鸭子类型判定，避免循环导入）。

        设置窗口是主窗口的 owned 子窗口后，self.window() 直接就是主窗口
        （QWidget.window() 返回顶层祖先），因此优先直接判定；遍历
        topLevelWidgets 仅作为回退路径（例如设置窗口未被挂载到主窗口的场景）。
        """
        w = self.window()
        if w is not None and getattr(w, "_mica_background", None) is not None:
            return w
        for w in QApplication.topLevelWidgets():
            if getattr(w, "_mica_background", None) is not None:
                return w
        return None

    # ── 窗口背景：模式切换与图片导入 ─────────────────────────────────

    def _on_bg_segment_changed(self, index: int) -> None:
        """窗口背景分段控件切换处理（暂存优先，未提交不影响主窗口）。

        Args:
            index: 新选中的分段索引（0 = 简约，1 = 云母，2 = 图像）。
        """
        if self._bg_updating:
            return
        if index == 2:
            # 已有持久化图片且文件存在 → 直接暂存；否则强制走选择流程
            if self._bg_image_name and os.path.exists(self._bg_image_path()):
                self._stage_background_settings("image")
            else:
                self._choose_bg_image(force=True)
        elif index == 0:
            self._stage_background_settings("minimalist")
        else:
            self._stage_background_settings("mica")

    def _on_ambient_toggled(self, checked: bool) -> None:
        """弥散氛围开关切换处理：仅写入暂存缓存，点击应用/确定才生效。

        Args:
            checked: 开关新状态；True 表示启用弥散氛围。
        """
        self._bg_ambient = bool(checked)
        if self._bg_mode != "minimalist":
            self._stage_background_settings("minimalist")
            return
        self._staging_cache.set("appearance.background", {
            "mode": self._bg_mode,
            "image": self._bg_image_name,
            "ambient": self._bg_ambient,
            "blur": self._bg_blur,
            "transparency": self._bg_transparency,
        })
        self._update_bg_ui_state()

    def _on_blur_changed(self, value: float) -> None:
        """图像模糊度滑动条 — 仅写入暂存，点击确定才全局生效。

        Args:
            value: 滑动条归一化值 0~1，映射为 0~200px。
        """
        if self._bg_params_updating:
            return
        self._bg_blur = _normalize_bg_blur(
            max(0.0, min(1.0, value)) * IMAGE_BG_BLUR_MAX
        )
        if self._blur_value_label is not None:
            self._blur_value_label.setText(f"{self._bg_blur}")
        self._stage_background_settings(self._bg_mode)

    def _on_transparency_changed(self, value: float) -> None:
        """图像透明度滑动条 — 仅写入暂存，点击确定才全局生效。

        Args:
            value: 滑动条归一化值 0~1，映射为 0~100%（80% 为很透明）。
        """
        if self._bg_params_updating:
            return
        self._bg_transparency = _normalize_bg_transparency(
            max(0.0, min(1.0, value)) * 100.0
        )
        if self._transparency_value_label is not None:
            self._transparency_value_label.setText(f"{self._bg_transparency}%")
        self._stage_background_settings(self._bg_mode)

    def _sync_bg_param_sliders(self) -> None:
        """按当前参数同步两条滑动条与数值标签（守卫内设置，不触发处理器）。"""
        if self._blur_slider is None or self._transparency_slider is None:
            return
        self._bg_params_updating = True
        try:
            self._blur_slider.value = self._bg_blur / IMAGE_BG_BLUR_MAX
            self._transparency_slider.value = self._bg_transparency / 100.0
        finally:
            self._bg_params_updating = False
        if self._blur_value_label is not None:
            self._blur_value_label.setText(f"{self._bg_blur}")
        if self._transparency_value_label is not None:
            self._transparency_value_label.setText(f"{self._bg_transparency}%")

    def _on_choose_bg_image_clicked(self) -> None:
        """「选择图片…」按钮点击入口（非强制场景：取消/失败不回退分段）。"""
        self._choose_bg_image(force=False)

    def _choose_bg_image(self, force: bool = False) -> bool:
        """打开文件对话框选择并导入背景图片。

        Args:
            force: True 表示由分段控件首次切入「图像」触发的强制
                选择场景——用户取消或导入失败时把分段控件编程式回退到
                「云母」；False 表示「选择图片…」按钮触发，取消或
                失败时保持现状（不回退、不改设置）。

        Returns:
            bool: 成功导入并应用图片背景返回 True；用户取消或导入失败
            返回 False。
        """
        path, _ = QFileDialog.getOpenFileName(
            self, "选择背景图片", "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp *.gif);;所有文件 (*)",
        )
        if not path:
            if force:
                self._revert_bg_segment()
            return False

        dest = import_custom_background_image(path)
        if dest is None:
            create_danger_dialog(
                title="导入失败",
                message="背景图片导入失败，请确认所选文件为受支持的有效图片"
                        "（PNG / JPG / JPEG / BMP / WEBP / GIF）。",
            )
            if force:
                self._revert_bg_segment()
            return False

        self._bg_image_name = os.path.basename(dest)
        self._stage_background_settings("image")
        return True

    def _revert_bg_segment(self) -> None:
        """把分段控件编程式回退到「云母」（索引 1，守卫内切换不触发处理器）。"""
        self._bg_updating = True
        try:
            self._bg_segmented.set_current_index(1)
        finally:
            self._bg_updating = False

    def _bg_image_path(self) -> str:
        """当前背景图片在持久化目录中的绝对路径。

        Returns:
            str: ``get_app_data_path()/backgrounds/<文件名>`` 拼接结果；
            未设置文件名时返回目录路径（调用方需先判空）。
        """
        return os.path.join(
            get_app_data_path(), BACKGROUND_DIR_NAME, self._bg_image_name
        )

    def _stage_background_settings(self, mode: str) -> None:
        """暂存窗口背景：仅写入暂存缓存并刷新本页 UI，不触碰主窗口与磁盘。

        提交时由 ``SettingsLayout._submit_settings`` 统一应用到主窗口并持久化。

        Args:
            mode: 目标背景模式："mica"（云母）、"image"（图像）或
                "minimalist"（简约，附带当前弥散氛围开关状态）。
        """
        self._bg_mode = mode
        self._staging_cache.set("appearance.background", {
            "mode": self._bg_mode,
            "image": self._bg_image_name,
            "ambient": self._bg_ambient,
            "blur": self._bg_blur,
            "transparency": self._bg_transparency,
        })
        self._update_bg_ui_state()

    def _apply_background_settings(self, mode: str) -> None:
        """兼容旧直接调用：转入暂存（不再直写主窗口/磁盘）。

        保留方法名以兼容存量测试与外部调用，语义已改为暂存优先。

        Args:
            mode: 目标背景模式。
        """
        self._stage_background_settings(mode)

    def _save_background_settings(self) -> None:
        """将窗口背景设置持久化到 SettingsManagerV2（重启后恢复）。"""
        try:
            v2 = SettingsManagerV2()
            v2.load()
            v2.set("appearance.background", {
                "mode": self._bg_mode,
                "image": self._bg_image_name,
                "ambient": self._bg_ambient,
                "blur": self._bg_blur,
                "transparency": self._bg_transparency,
            })
            v2.save()
        except Exception:
            pass

    def _update_bg_ui_state(self) -> None:
        """按当前背景模式刷新图片行、参数区与弥散氛围行的可见性。

        图片行与参数区（模糊度/透明度滑动条）仅图像模式可见；
        弥散氛围行仅简约模式可见。
        """
        is_image = (self._bg_mode == "image")
        is_minimalist = (self._bg_mode == "minimalist")
        self._bg_image_row.setVisible(is_image)
        self._bg_file_label.setText(
            self._bg_image_name if self._bg_image_name else "未设置"
        )
        if self._bg_params_row is not None:
            self._bg_params_row.setVisible(is_image)
        if self._ambient_row is not None:
            self._ambient_row.setVisible(is_minimalist)

    def _resolve_staged_theme_mode(self) -> str:
        """从暂存缓存解析主题偏好三态。

        优先读 ``appearance.theme_mode``；旧快照缺失时由
        ``appearance.theme``（dark/light）迁移；非法值回退为当前
        ``tm`` 实际值对应的手动偏好。

        Returns:
            偏好值："light" | "dark" | "system"。
        """
        staged_mode = self._staging_cache.get("appearance.theme_mode", None)
        if staged_mode in ("light", "dark", "system"):
            return staged_mode
        staged_theme = self._staging_cache.get("appearance.theme", None)
        if staged_theme in ("light", "dark"):
            return staged_theme
        try:
            return tm.get_theme_mode()
        except Exception:
            return "dark" if tm.is_dark_theme() else "light"

    def _on_theme_segment_changed(self, index: int) -> None:
        """深色模式分段切换 — 仅写入暂存，点击确定才全局生效。

        与「窗口背景」分段同语义：切换只进 ``SettingsStagingCache``，
        不触碰 ``tm``、主窗口与磁盘；应用与落盘统一由
        ``SettingsLayout._submit_settings`` 在点击确定时执行。

        Args:
            index: 新选中的分段索引（0 = 白天，1 = 夜晚，2 = 跟随系统）。
        """
        if self._theme_updating:
            return
        if index < 0 or index >= len(self.THEME_MODES):
            return
        self._apply_theme_mode(self.THEME_MODES[index])

    def _apply_theme_mode(self, mode: str) -> None:
        """暂存主题偏好（不生效、不落盘，点击确定才全局应用）。

        遵循设置页暂存隔离铁律：仅写入暂存缓存并同步分段选中；
        应用到 ``tm`` 与 V2 落盘统一由 ``SettingsLayout._submit_settings``
        执行。跟随系统模式的暂存生效值按当前系统主题只读推导（不触碰 ``tm``）。

        Args:
            mode: 偏好值，"light" | "dark" | "system"，非法值直接忽略。
        """
        if mode not in ("light", "dark", "system"):
            return
        self._theme_mode = mode
        self._staging_cache.set("appearance.theme_mode", mode)
        if mode == "system":
            try:
                from freeassetfilter.ui.theme.system_theme import (
                    get_windows_system_theme,
                )

                effective = get_windows_system_theme()
            except Exception:
                effective = "dark" if tm.is_dark_theme() else "light"
            if effective not in ("light", "dark"):
                effective = "dark" if tm.is_dark_theme() else "light"
        else:
            effective = mode
        self._staging_cache.set("appearance.theme", effective)
        self._sync_theme_segment()

    def _sync_theme_segment(self) -> None:
        """按当前偏好同步分段控件选中项（守卫内切换，不触发处理器）。"""
        if self._theme_segmented is None:
            return
        target = self.THEME_INDEX.get(self._theme_mode, 1)
        self._theme_updating = True
        try:
            self._theme_segmented.set_current_index(target, animate=False)
        finally:
            self._theme_updating = False

    def _on_dark_toggle(self, checked: bool) -> None:
        """兼容旧深色开关调用：等价于暂存夜晚/白天偏好（点击确定才生效）。

        保留方法名以兼容存量测试与外部调用，语义为纯暂存
        （与分段控件一致）。

        Args:
            checked: True 暂存为夜晚（深色），False 暂存为白天（浅色）。
        """
        self._apply_theme_mode("dark" if checked else "light")
        self._sync_theme_segment()

    def _on_color_clicked(self, color_hex: str) -> None:
        """主题色选择 — 写入暂存缓存，点击「应用」/「确定」才全局生效。"""
        self._current_accent = color_hex
        self._staging_cache.set("appearance.accent_color", color_hex)
        for btn in self._color_buttons:
            btn.selected = (btn.color_hex.upper() == color_hex.upper())
        if self._custom_btn is not None:
            self._custom_btn.selected = False
        # 选择预设色时关闭浮动选择面板
        if self._custom_panel is not None:
            self._custom_panel.close_animated()

    def _on_custom_color_clicked(self) -> None:
        """自定义颜色按钮 — 展开/折叠浮动颜色选择面板。
        
        严格的切换行为：
        - 第一张点击：打开面板
        - 面板可见时的点击：关闭面板
        - 关闭动画进行中的点击：取消关闭并重新打开
        - 打开动画进行中的点击：关闭面板
        
        面板引用在页面生命周期内持久存在，不因关闭而丢失。
        """
        # 确保面板存在（只创建一次）
        if self._custom_panel is None:
            self._custom_panel = _ColorPanel(parent=self)
            self._custom_panel.color_selected.connect(self._on_panel_color_changed)
            self._custom_panel.closed.connect(self._on_panel_closed)
        
        panel = self._custom_panel
        
        # 严格切换逻辑：先检查关闭中状态（isVisible 在淡出时仍为 True）
        if panel.is_closing:
            # 面板正在关闭中 → 取消关闭并重新打开
            panel.reopen()
            
            # 更新按钮状态
            for btn in self._color_buttons:
                btn.selected = False
            self._custom_btn.selected = True
        elif panel.isVisible():
            # 面板可见且未在关闭中 → 关闭
            panel.close_animated()
        else:
            # 面板隐藏 → 打开
            btn_pos = self._custom_btn.mapToGlobal(
                QPoint(self._custom_btn.width() + 4, 0)
            )
            
            initial = self._current_accent
            if initial.lower() == "auto" or not initial.startswith("#"):
                initial = tm.accent.name().upper()
            panel.set_color(initial)
            
            # 更新按钮状态
            for btn in self._color_buttons:
                btn.selected = False
            self._custom_btn.selected = True
            
            panel.show_animated(btn_pos)
            # 安装外部点击事件过滤器（在面板显示后安装）
            self._install_outside_click_filter()

    def _install_outside_click_filter(self) -> None:
        """在设置窗口顶层祖先上安装事件过滤器，用于点击外部区域关闭面板。

        设置窗口是主窗口的 owned 子窗口，self.window() 返回主窗口，
        因此过滤器会同时覆盖设置页自身及其子控件与主窗口——面板显示期间
        点击主窗口任何区域同样会关闭面板。

        Safe when no top-level window exists yet (no-op).
        Idempotent: repeated calls have no effect.
        """
        if self._event_filter_installed:
            return
        
        top_window = self.window()
        if top_window is None:
            return
        
        targets: list[QObject] = [top_window, self]
        targets.extend(self.findChildren(QWidget))
        unique_targets = list(dict.fromkeys(targets))
        for target in unique_targets:
            target.installEventFilter(self)
        self._event_filter_targets = unique_targets
        self._event_filter_installed = True

    def _remove_outside_click_filter(self) -> None:
        """Remove event filter from the top-level SettingsWindow.
        
        Idempotent: repeated calls have no effect.
        Safe when no top-level window exists or filter was not installed.
        """
        if not self._event_filter_installed:
            return
        
        for target in self._event_filter_targets:
            target.removeEventFilter(self)
        self._event_filter_targets.clear()
        self._event_filter_installed = False

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Event filter for outside-click dismissal of _ColorPanel.
        
        Intercepts MouseButtonPress on the top-level SettingsWindow.
        - If click is inside the panel's global rect → ignore (let panel handle it)
        - If click is inside the custom button's global rect → ignore (let button handle toggle)
        - Otherwise → close panel with fade animation
        
        Returns False always to let the original event continue propagation.
        """
        if event.type() == QEvent.Type.MouseButtonPress:
            global_pos = event.globalPosition().toPoint()
            
            # Check if panel exists and is visible
            if self._custom_panel is None or not self._custom_panel.isVisible():
                return False
            
            # Check if click is inside the panel
            panel_global_rect = QRectF(
                self._custom_panel.mapToGlobal(QPoint(0, 0)),
                self._custom_panel.size(),
            )
            if panel_global_rect.contains(global_pos):
                # Click inside panel → ignore, let panel handle it
                return False
            
            # Check if click is inside the custom button
            if self._custom_btn is not None:
                btn_global_rect = QRectF(
                    self._custom_btn.mapToGlobal(QPoint(0, 0)),
                    self._custom_btn.size(),
                )
                if btn_global_rect.contains(global_pos):
                    # Click inside button → ignore, let button handler toggle
                    return False
            
            # Click outside panel and button → close panel
            self._custom_panel.close_animated()
        
        return False

    def _on_panel_color_changed(self, hex_color: str) -> None:
        """浮动颜色选择面板值变化 — 写入暂存缓存（提交前不全局生效）。"""
        self._current_accent = hex_color
        self._staging_cache.set("appearance.accent_color", hex_color)
        for btn in self._color_buttons:
            btn.selected = False
        if self._custom_btn is not None:
            self._custom_btn.selected = True

    def _on_panel_closed(self) -> None:
        """浮动面板关闭后的处理。
        
        注意：不将 _custom_panel 设为 None，保持面板引用。
        页面销毁时 Qt 父子关系会自动清理面板。
        """
        # 仅重置按钮状态，不丢弃面板引用
        # 移除外部点击事件过滤器
        self._remove_outside_click_filter()

    def hideEvent(self, event: QHideEvent) -> None:
        """宿主页面隐藏时同步关闭浮动面板并移除事件过滤器。"""
        if self._custom_panel is not None:
            self._custom_panel.close_animated()
        self._remove_outside_click_filter()
        super().hideEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        """宿主页面关闭时同步关闭浮动面板并移除事件过滤器。"""
        if self._custom_panel is not None:
            self._custom_panel.close_animated()
        self._remove_outside_click_filter()
        super().closeEvent(event)

    def refresh_theme(self) -> None:
        """主题切换时刷新页面内文字颜色并同步三段控件。

        暂存隔离铁律：本页的任何修改都不触碰 ``tm``；此处仅处理反方向
        （顶栏按钮 / 系统跟随导致的 ``tm`` 变化）的单向镜像——以 ``tm``
        当前偏好为准回写暂存并同步分段选中，保证设置面板与顶栏按钮一致；
        守卫内编程式切换，不触发提交。
        """
        # 外部主题变化优先同步暂存（主题为实时项，不存在未提交覆盖问题）。
        try:
            external_mode = tm.get_theme_mode()
        except Exception:
            external_mode = "dark" if tm.is_dark_theme() else "light"
        if external_mode in ("light", "dark", "system"):
            if self._staging_cache.get("appearance.theme_mode", None) != external_mode:
                self._staging_cache.set("appearance.theme_mode", external_mode)
            try:
                external_effective = tm.effective_theme()
            except Exception:
                external_effective = "dark" if tm.is_dark_theme() else "light"
            if self._staging_cache.get("appearance.theme", None) != external_effective:
                self._staging_cache.set("appearance.theme", external_effective)
            self._theme_mode = external_mode
        else:
            self._theme_mode = self._resolve_staged_theme_mode()
        self._sync_theme_segment()
        # 由外部 _refresh_styles 统一刷新文字颜色
        # 窗口背景区块：标题与文件名标签颜色跟随主题（覆盖统一刷新，
        # 保证页面脱离 SettingsLayout 宿主单独使用时同样正确）
        self._bg_label.setStyleSheet(
            f"background: transparent; border: none;"
            f"color: {tm.text.name()}; font-size: 13px; font-weight: 500;"
        )
        self._bg_file_label.setStyleSheet(
            f"background: transparent; border: none;"
            f"color: {tm.text.name()}; font-size: 13px;"
        )
        # 弥散氛围开关：同步状态（避免信号循环：暂时断开）
        if self._ambient_toggle is not None:
            self._ambient_toggle.toggled.disconnect(self._on_ambient_toggled)
            self._ambient_toggle.checked = self._bg_ambient
            self._ambient_toggle.toggled.connect(self._on_ambient_toggled)
        # 弥散氛围行标题/描述颜色跟随主题
        if self._ambient_row is not None:
            _ambient_title = getattr(self._ambient_row, "title_label", None)
            if _ambient_title is not None:
                _ambient_title.setStyleSheet(
                    f"font-size: 13.5px; font-weight: 500; color: {tm.text.name()};"
                )
            _ambient_desc = getattr(self._ambient_row, "desc_label", None)
            if _ambient_desc is not None:
                _ambient_desc.setStyleSheet(
                    f"font-size: 12px; color: {tm.alpha_of(tm.mid, 60).name()};"
                    f" line-height: 1.5;"
                )
        # 重新应用背景模式相关的可用性/置灰状态（米卡数值标签颜色）
        self._update_bg_ui_state()

    def _load_v2_settings(self) -> None:
        """确保 UI 控件与暂存缓存一致（不修改 tm，不读盘）。

        历史语义为从 V2 重载，现改为从隔离层同步，保证取消/关闭未提交时
        界面可恢复至原始状态。保留方法名以兼容存量调用。
        """
        self.refresh_from_staging()

    def refresh_from_staging(self) -> None:
        """从暂存缓存刷新全部控件展示（实时更新机制的核心）。

        所有开关、输入框、滑动条展示与暂存内容一致；编程式赋值全程守卫，
        不回写缓存、不触发提交、不触碰主窗口与磁盘。
        """
        self._theme_mode = self._resolve_staged_theme_mode()
        self._sync_theme_segment()

        saved_accent = self._staging_cache.get("appearance.accent_color", "#007AFF")
        self._current_accent = saved_accent
        preset_values = {btn.color_hex.upper() for btn in self._color_buttons}
        is_preset = isinstance(saved_accent, str) and saved_accent.upper() in preset_values
        for btn in self._color_buttons:
            btn.selected = (
                isinstance(saved_accent, str)
                and btn.color_hex.upper() == saved_accent.upper()
            )
        if self._custom_btn is not None:
            self._custom_btn.selected = (
                isinstance(saved_accent, str)
                and not is_preset
                and saved_accent.upper() != "AUTO"
            )

        saved_bg = self._staging_cache.get("appearance.background", {}) or {}
        saved_bg_mode = saved_bg.get("mode", "mica")
        if saved_bg_mode in ("mica", "image", "minimalist"):
            self._bg_mode = saved_bg_mode
        self._bg_image_name = str(saved_bg.get("image", "") or "")
        _raw_ambient = saved_bg.get("ambient", True)
        self._bg_ambient = _raw_ambient if isinstance(_raw_ambient, bool) else bool(_raw_ambient)
        self._bg_blur = _normalize_bg_blur(
            saved_bg.get("blur", IMAGE_BG_BLUR_DEFAULT)
        )
        self._bg_transparency = _normalize_bg_transparency(
            saved_bg.get("transparency", IMAGE_BG_TRANSPARENCY_DEFAULT)
        )
        if self._ambient_toggle is not None:
            try:
                self._ambient_toggle.toggled.disconnect(self._on_ambient_toggled)
            except Exception:
                pass
            self._ambient_toggle.checked = self._bg_ambient
            self._ambient_toggle.toggled.connect(self._on_ambient_toggled)
        self._sync_bg_segment()
        self._sync_bg_param_sliders()
        self._update_bg_ui_state()

    def _sync_bg_segment(self) -> None:
        """按暂存背景模式同步分段控件选中项（守卫内切换，不触发处理器）。"""
        target = {"minimalist": 0, "mica": 1, "image": 2}.get(self._bg_mode, 1)
        self._bg_updating = True
        try:
            self._bg_segmented.set_current_index(target, animate=False)
        finally:
            self._bg_updating = False

    def get_staging_cache(self) -> SettingsStagingCache:
        """返回本页绑定的暂存缓存（调试与提交链路使用）。

        Returns:
            SettingsStagingCache: 隔离层实例。
        """
        return self._staging_cache

    def get_cache_debug_info(self) -> dict:
        """返回暂存缓存调试摘要。

        Returns:
            dict: 见 :meth:`SettingsStagingCache.debug_info`。
        """
        return self._staging_cache.debug_info()

    def collect_settings(self) -> dict:
        """收集暂存区的 V2 设置值（提交事务的数据源）。

        Returns:
            dict: V2 分类树格式的设置字典（含主题、强调色与窗口背景）。
        """
        return {
            "appearance": {
                "theme_mode": self._staging_cache.get(
                    "appearance.theme_mode", self._theme_mode
                ),
                "theme": self._staging_cache.get(
                    "appearance.theme",
                    "dark" if tm.is_dark_theme() else "light",
                ),
                "accent_color": self._staging_cache.get(
                    "appearance.accent_color", self._current_accent
                ),
                "background": self._staging_cache.get(
                    "appearance.background",
                    {
                        "mode": self._bg_mode,
                        "image": self._bg_image_name,
                        "ambient": self._bg_ambient,
                    },
                ),
            },
        }


class SettingsLayout(QWidget):
    """设置布局（暂存隔离 + 统一提交）。

    底部按钮语义：``重置``（警告 ``danger``，回默认值但不落盘，居左）、
    ``取消``（次选 ``secondary``，丢弃暂存并关闭）、``确定``（强调
    ``primary``，提交并关闭）。仅「确定」绑定提交事件（无「应用」按钮）。
    """

    def __init__(self, parent=None, host_window: QWidget | None = None):
        """初始化设置布局。

        Args:
            parent: 父控件。
            host_window: 宿主设置窗口（SettingsWindow）。设置窗口作为主窗口的
                owned 子窗口时，QWidget.window() 返回的是主窗口而非设置窗口
                本身，因此由创建方显式传入，供“应用”等需要整窗快照的逻辑使用。
        """
        super().__init__(parent)
        self._host_window = host_window
        # 暂存隔离层：快照 V2 全量，与主状态严格隔离
        self._staging_cache = SettingsStagingCache()
        _v2_boot = SettingsManagerV2()
        self._staging_cache.begin(copy.deepcopy(_v2_boot.load()))
        self._submitted: bool = False
        self._last_submit_ms: float = 0.0

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── 侧边栏（使用 StyledSidebar 组件，透明背景以显示 Mica） ──
        self._sidebar = StyledSidebar(
            title="",
            width=220,
            compact=False,
            transparent=True,  # 透明背景以显示 Mica 效果
            parent=self,
        )
        self._sidebar.add_item("外观", icon_svg="sun")
        self._sidebar.add_item("通用", icon_svg="gear")
        self._sidebar.item_selected.connect(self._on_item_selected)
        main_layout.addWidget(self._sidebar)

        # ── 内容区（右侧） ──
        self._content_area = QFrame()
        self._content_area.setObjectName("SettingsContentArea")
        content_layout = QVBoxLayout(self._content_area)
        content_layout.setContentsMargins(0, 0, 24, 24)
        content_layout.setSpacing(0)

        # 使用 QStackedWidget 实现多页面切换
        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background: transparent; border: none;")

        # 页面 0：外观（包进透明滚动区域，小窗口尺寸下内容可滚动访问）
        self._appearance_page = AppearanceSettingsPage(staging_cache=self._staging_cache)
        appearance_scroll = self._wrap_page_in_scroll(self._appearance_page)
        appearance_card = self._create_page_card(appearance_scroll)
        # 浮动滚动条锚定到外观卡片（#SettingsCard）右缘：右缘水平贴边、
        # 上下内缩 10*dpi，与文件选择器/文件池浮动滚动条间距一致
        appearance_scroll.attach_floating_bar_region(appearance_card)
        self._stack.addWidget(appearance_card)

        # 页面 1：通用（占位）
        general_card = self._create_page_card(None)
        self._stack.addWidget(general_card)

        content_layout.addWidget(self._stack, stretch=1)

        # ── 底部按钮栏 ──
        buttons_widget = self._create_bottom_buttons()
        content_layout.addWidget(buttons_widget)

        # 应用初始样式
        self._refresh_styles()

        main_layout.addWidget(self._content_area, stretch=1)

        self.setLayout(main_layout)

        # 默认选中第一项
        self._stack.setCurrentIndex(0)

        # 主题切换时刷新内容区背景（生效值变化 + 偏好变化均需刷新，
        # 后者覆盖生效值不变但分段需切换的场景，如 白天→跟随系统且系统正为浅色）。
        tm.theme_changed.connect(self._on_theme_changed)
        try:
            tm.theme_mode_changed.connect(self._on_theme_changed)
        except Exception:
            pass

    def _wrap_page_in_scroll(self, page: QWidget) -> _FloatingScrollArea:
        """将设置页包进浮动滚动条滚动区（styled 滚动条 + 丝滑滚动）。"""
        scroll = _FloatingScrollArea()
        scroll.setWidget(page)
        return scroll

    def _create_page_card(self, inner_widget: QWidget | None) -> QFrame:
        """创建圆角卡片容器，内部放置给定 widget。"""
        card = QFrame()
        card.setObjectName("SettingsCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 20, 20, 20)
        card_layout.setSpacing(12)

        if inner_widget is not None:
            card_layout.addWidget(inner_widget)
        card_layout.addStretch()
        return card

    def _refresh_styles(self) -> None:
        """刷新卡片样式（参考 file_selector_layout 面板样式）"""
        mid = tm.mid
        txt = tm.text
        fill_color = f"rgba({txt.red()},{txt.green()},{txt.blue()},{5 / 100})"
        border_color = f"rgba({mid.red()},{mid.green()},{mid.blue()},{50 / 100})"

        self._stack.setStyleSheet(f"""
            #SettingsCard {{
                background-color: {fill_color};
                border: 1px solid {border_color};
                border-radius: 8px;
            }}
        """)
        self._content_area.setStyleSheet("background-color: transparent; border: none;")

        # 刷新外观页面内的文字颜色
        for i in range(self._stack.count()):
            card = self._stack.widget(i)
            for label in card.findChildren(QLabel):
                if not label.text():
                    continue
                label.setStyleSheet(
                    f"background: transparent; border: none;"
                    f"color: {tm.text.name()}; font-size: 13px; font-weight: 500;"
                )

        # 刷新外观页面
        if hasattr(self, "_appearance_page"):
            self._appearance_page.refresh_theme()
            # 刷新所有颜色按钮
            for btn in self._appearance_page._color_buttons:
                btn.update()

    def _on_item_selected(self, index: int, label: str) -> None:
        """侧边栏导航项选中回调"""
        if 0 <= index < self._stack.count():
            self._stack.setCurrentIndex(index)

    def _on_theme_changed(self, _theme: str) -> None:
        """主题切换时刷新样式"""
        self.refresh_theme()

    # ── 底部按钮 ──────────────────────────────────────────────

    def _create_bottom_buttons(self) -> QFrame:
        """创建底部按钮栏（重置 + 取消 + 确定）。

        样式映射（仅复用 ``StyledButton``，不自绘）：
        确定 = ``primary``（强调，主题色）、取消 = ``secondary``（次选）、
        重置 = ``danger``（警告）。
        布局：左 ``重置``，右 ``取消`` + ``确定``（无「应用」按钮）。

        Returns:
            QFrame: 底部按钮栏容器。
        """
        bar = QFrame()
        bar.setObjectName("SettingsBottomBar")
        bar.setStyleSheet("background: transparent; border: none;")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)

        self._reset_btn = StyledButton("重置", variant="danger", size="sm")
        self._reset_btn.clicked.connect(self._on_reset_clicked)
        layout.addWidget(self._reset_btn)

        layout.addStretch()

        self._cancel_btn = StyledButton("取消", variant="secondary", size="sm")
        self._cancel_btn.clicked.connect(self._on_cancel_clicked)
        layout.addWidget(self._cancel_btn)

        self._confirm_btn = StyledButton("确定", variant="primary", size="sm")
        self._confirm_btn.clicked.connect(self._on_confirm_clicked)
        layout.addWidget(self._confirm_btn)

        # 兼容残留：历史「应用」按钮已移除，不再创建 _apply_btn；
        # _on_apply_clicked 保留为内部别名，仅供旧调用方兼容。
        self._apply_btn = None  # type: ignore[assignment]

        return bar

    def _on_reset_clicked(self) -> None:
        """重置按钮 — 暂存区回默认值并刷新界面，不直接落盘（需确定提交）。"""
        self._staging_cache.reset_to_defaults(copy.deepcopy(DEFAULT_SETTINGS_V2))
        self._appearance_page.refresh_from_staging()

    def _on_cancel_clicked(self) -> None:
        """取消按钮 — 清除暂存并恢复界面至原始状态，然后关闭宿主窗口。"""
        self._staging_cache.discard()
        self._appearance_page.refresh_from_staging()
        self._close_host_window()

    def _on_apply_clicked(self) -> None:
        """兼容旧「应用」调用：等价于提交但不关闭（按钮已移除）。"""
        self._submit_settings(close_after=False)

    def _on_confirm_clicked(self) -> None:
        """确定按钮 — 提交事件（立即应用并关闭设置窗口）。"""
        if self._submit_settings(close_after=False):
            self._submitted = True
            self._close_host_window()

    def _submit_settings(self, close_after: bool = False) -> bool:
        """设置提交事件处理函数（确定按钮绑定，事务性提交）。

        流程：暂存快照 → 校验 → 主题过渡遮罩 → 应用到 ``tm`` → 应用背景到
        主窗口 → 持久化到 ``SettingsManagerV2`` → 基线前移。任一步失败则
        回滚 ``tm`` 并返回 False，不污染磁盘与运行时。

        Args:
            close_after: 预留关闭标志（关闭统一由调用方执行，便于测试断言）。

        Returns:
            bool: 提交成功返回 True，失败返回 False。
        """
        t0 = time.perf_counter()
        staged = self._staging_cache.commit_snapshot()
        appearance = staged.get("appearance", {}) if isinstance(staged, dict) else {}
        theme_mode = appearance.get("theme_mode", None)
        if theme_mode not in ("light", "dark", "system"):
            # 旧快照迁移：由生效值推导偏好。
            legacy_theme = appearance.get("theme", "light")
            theme_mode = "dark" if legacy_theme == "dark" else "light"
        accent = appearance.get("accent_color", "#007AFF")
        staged_bg = appearance.get("background", {}) or {}
        bg_mode = staged_bg.get("mode", "mica")
        if bg_mode not in ("mica", "image", "minimalist"):
            bg_mode = "mica"
        bg_blur = _normalize_bg_blur(
            staged_bg.get("blur", IMAGE_BG_BLUR_DEFAULT)
        )
        bg_transparency = _normalize_bg_transparency(
            staged_bg.get("transparency", IMAGE_BG_TRANSPARENCY_DEFAULT)
        )

        saved_accent = accent
        if isinstance(accent, str) and accent.lower() == "auto":
            accent = get_system_accent_color()

        settings_window = self._host_window if self._host_window is not None else self.window()
        if settings_window is not None:
            try:
                overlay = ThemeTransitionOverlay.from_widget(settings_window)
                overlay.start()
            except Exception:
                pass

        prev_mode = tm.get_theme_mode()
        prev_theme = "dark" if tm.is_dark_theme() else "light"
        prev_colors = copy.deepcopy(tm._colors)
        # 主窗口过渡预抓拍：tm 翻转后主窗槽内各背景层 sync 才能以旧帧为底
        # 做 280ms 交叉淡入，否则退化为裸 update 露出 _root 形成闪现。
        try:
            main_window = self._appearance_page._find_main_window()
            if main_window is not None and hasattr(main_window, "begin_theme_transition"):
                main_window.begin_theme_transition()
        except Exception:  # noqa: BLE001 - 预抓拍失败不阻塞提交本身
            pass
        try:
            tm.set_theme_mode(theme_mode)
            try:
                theme = tm.effective_theme()
            except Exception:
                theme = "dark" if tm.is_dark_theme() else "light"
            tm._colors["accent"]["primary"] = accent
            tm.colors_updated.emit(tm._colors)

            self._apply_staged_background_to_main_window(staged_bg)

            colors_dict = copy.deepcopy(tm._colors)
            colors_dict["accent"]["primary"] = saved_accent

            v2 = SettingsManagerV2()
            v2.load()
            v2.set("appearance.theme_mode", theme_mode)
            v2.set("appearance.theme", theme)
            v2.set("appearance.accent_color", saved_accent)
            v2.set("appearance.colors", colors_dict)
            v2.set("appearance.background", {
                "mode": bg_mode,
                "image": str(staged_bg.get("image", "") or ""),
                "ambient": bool(staged_bg.get("ambient", True)),
                "blur": bg_blur,
                "transparency": bg_transparency,
            })
            v2.save()
        except Exception:
            try:
                tm.set_theme_mode(prev_mode)
                tm.set_theme(prev_theme)
                tm._colors.update(prev_colors)
                tm.colors_updated.emit(tm._colors)
            except Exception:
                pass
            return False

        self._staging_cache.mark_committed(staged)
        self._last_submit_ms = (time.perf_counter() - t0) * 1000.0
        if close_after:
            self._submitted = True
            self._close_host_window()
        return True

    def _apply_staged_background_to_main_window(self, staged_bg: dict) -> None:
        """将暂存背景应用到主窗口（仅提交路径调用）。

        Args:
            staged_bg: 暂存的 ``appearance.background`` 字典。
        """
        mode = staged_bg.get("mode", "mica")
        if mode not in ("mica", "image", "minimalist"):
            mode = "mica"
        image_name = str(staged_bg.get("image", "") or "")
        ambient = staged_bg.get("ambient", True)
        ambient = ambient if isinstance(ambient, bool) else bool(ambient)
        bg_blur = _normalize_bg_blur(
            staged_bg.get("blur", IMAGE_BG_BLUR_DEFAULT)
        )
        bg_transparency = _normalize_bg_transparency(
            staged_bg.get("transparency", IMAGE_BG_TRANSPARENCY_DEFAULT)
        )
        try:
            mw = self._appearance_page._find_main_window()
            if mw is None:
                return
            if mode == "image" and image_name:
                image_path = os.path.join(
                    get_app_data_path(), BACKGROUND_DIR_NAME, image_name
                )
                if hasattr(mw, "set_custom_background_image"):
                    mw.set_custom_background_image(image_path)
                if hasattr(mw, "set_image_background_params"):
                    # 透明度换算为不透明度后下发给图像层。
                    mw.set_image_background_params(
                        bg_blur, 1.0 - bg_transparency / 100.0
                    )
                if hasattr(mw, "set_background_mode"):
                    mw.set_background_mode("image")
            elif mode == "minimalist":
                if hasattr(mw, "set_ambient_enabled"):
                    mw.set_ambient_enabled(ambient)
                if hasattr(mw, "set_background_mode"):
                    mw.set_background_mode("minimalist")
            else:
                if hasattr(mw, "set_background_mode"):
                    mw.set_background_mode("mica")
        except Exception:
            pass

    def _close_host_window(self) -> None:
        """关闭宿主设置窗口（确定/取消路径）。"""
        host = self._host_window if self._host_window is not None else self.window()
        try:
            if host is not None and hasattr(host, "close"):
                host.close()
        except Exception:
            pass

    def on_host_closing(self) -> None:
        """宿主窗口关闭时的生命周期钩子：未提交则自动清除暂存并恢复界面。

        由 ``SettingsWindow.closeEvent`` 调用，保证关闭未提交时缓存不泄漏、
        下次打开为原始状态。
        """
        if self._submitted:
            return
        if self._staging_cache.is_dirty():
            self._staging_cache.discard()
            try:
                self._appearance_page.refresh_from_staging()
            except Exception:
                pass

    def get_cache_debug_info(self) -> dict:
        """返回暂存缓存调试摘要（含最近提交耗时）。

        Returns:
            dict: 调试信息字典。
        """
        info = self._staging_cache.debug_info()
        info["last_submit_ms"] = round(self._last_submit_ms, 3)
        info["submitted"] = self._submitted
        return info

    def refresh_theme(self) -> None:
        """公共方法：强制刷新当前主题下的所有样式"""
        self._refresh_styles()

        # 刷新侧边栏所有导航项的图标和标签颜色
        active_idx = self._sidebar._active_index
        for i, item in enumerate(self._sidebar._items):
            item._set_active(i == active_idx)

        # 刷新折叠按钮的顶部分隔线颜色
        if hasattr(self._sidebar, '_toggle_btn'):
            self._sidebar._toggle_btn.setStyleSheet(
                f"SidebarItem {{ background-color: transparent; "
                f"border-top: 1px solid {tm.alpha_of(tm.surface, 90).name()}; }}"
            )
