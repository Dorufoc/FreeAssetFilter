"""
设置布局 — 设置窗口的内容区域（使用 StyledSidebar）
"""

from __future__ import annotations

import copy
import os

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QFrame, QLabel, QStackedWidget,
    QApplication, QScrollArea, QFileDialog,
)
from PySide6.QtCore import (
    Qt, Signal, QRectF, QPropertyAnimation, QEasingCurve, Property, QPoint,
    QEvent, QObject, QTimer,
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
from components.styled_slider import StyledSlider
from components.styled_scroll_area import StyledScrollBar, StyledScrollArea
from components.styled_segmented import StyledSegmented
from components.styled_dialog import create_danger_dialog
from components.styled_color_picker import _ColorPanel
from components.custom_background import (
    BACKGROUND_DIR_NAME,
    import_custom_background_image,
)
from components.theme_transition_overlay import ThemeTransitionOverlay
from freeassetfilter.core.managers.settings_manager_v2 import SettingsManagerV2
from freeassetfilter.utils.path_utils import get_app_data_path


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

# ── 背景米卡效果可调参数（名称 / 取值区间 / 默认值 / 单位） ────────────
# 对应 SettingsManagerV2 的 appearance.mica.* 键与主窗口 MicaMaterial 参数。
MICA_PARAM_SPECS = {
    "saturation": {
        "name": "背景色饱和度", "min": 0.0, "max": 8.0,
        "default": 4.5, "decimals": 1, "unit": "×",
    },
    "contrast": {
        "name": "对比度", "min": 0.0, "max": 3.0,
        "default": 1.5, "decimals": 1, "unit": "×",
    },
    "blur_radius": {
        "name": "背景模糊度", "min": 0.0, "max": 300.0,
        "default": 200.0, "decimals": 0, "unit": " px",
    },
    "tint_opacity": {
        "name": "叠加层透明度", "min": 0.0, "max": 100.0,
        "default": 70.0, "decimals": 0, "unit": "%",
    },
}

# 实时预览防抖间隔（ms）：叠加层透明度绘制期生效可即时跟随；
# 模糊/饱和度/对比度重建较重，防抖后在后台线程应用（不阻塞 UI）。
MICA_PREVIEW_DEBOUNCE_MS = 200


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


class AppearanceSettingsPage(QWidget):
    """外观设置页面 — 深色模式开关 + 主题色选择。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._color_buttons: list[AccentColorButton] = []
        self._custom_btn: CustomAccentButton | None = None
        self._custom_panel: _ColorPanel | None = None
        self._current_accent: str = ""  # tracked for save
        self._event_filter_installed: bool = False  # track event filter state
        self._event_filter_targets: list[QObject] = []
        # 窗口背景状态（初值在 _build_ui 中从 V2 覆盖）
        self._bg_mode: str = "mica"        # "mica" / "image"
        self._bg_image_name: str = ""      # 持久化目录中的背景图片文件名
        self._bg_updating: bool = False    # 编程式切换分段控件的守卫标志
        self._build_ui()
        self._load_v2_settings()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)

        # ── 深色模式开关 ──
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

        # 从 V2 读取已保存的设置作为初始状态
        v2 = SettingsManagerV2()
        v2.load()
        saved_theme = v2.get("appearance.theme", "light")
        saved_accent = v2.get("appearance.accent_color", "#007AFF")

        is_dark = (saved_theme == "dark")
        self._dark_toggle = StyledToggle(checked=is_dark, size="default")
        self._dark_toggle.toggled.connect(self._on_dark_toggle)
        dark_layout.addWidget(self._dark_toggle)

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

        # ── 背景米卡效果（滑动条配置项） ──
        mica_label = QLabel("背景米卡效果")
        mica_label.setStyleSheet(
            f"background: transparent; border: none;"
            f"color: {tm.text.name()}; font-size: 13px; font-weight: 500;"
        )
        layout.addWidget(mica_label)

        # 实时预览防抖：拖动中合并高频 value_changed，超时后统一应用
        self._mica_preview_timer = QTimer(self)
        self._mica_preview_timer.setSingleShot(True)
        self._mica_preview_timer.setInterval(MICA_PREVIEW_DEBOUNCE_MS)
        self._mica_preview_timer.timeout.connect(self._apply_mica_preview)

        self._mica_sliders: dict[str, StyledSlider] = {}
        self._mica_value_labels: dict[str, QLabel] = {}
        self._mica_values: dict[str, float] = {}

        saved_mica = v2.get("appearance.mica", {}) or {}
        mica_rows = QVBoxLayout()
        mica_rows.setContentsMargins(0, 0, 0, 0)
        mica_rows.setSpacing(16)
        for key, spec in MICA_PARAM_SPECS.items():
            initial = float(saved_mica.get(key, spec["default"]))
            # 越界值（旧配置/手改 JSON）钳制回取值区间
            initial = max(spec["min"], min(spec["max"], initial))
            mica_rows.addWidget(self._build_mica_slider_row(key, spec, initial))
        layout.addLayout(mica_rows)

        # ── 窗口背景（米卡效果 / 自定义图片） ──
        saved_bg = v2.get("appearance.background", {}) or {}
        saved_bg_mode = saved_bg.get("mode", "mica")
        self._bg_mode = saved_bg_mode if saved_bg_mode in ("mica", "image") else "mica"
        self._bg_image_name = str(saved_bg.get("image", "") or "")

        bg_label = QLabel("窗口背景")
        bg_label.setStyleSheet(
            f"background: transparent; border: none;"
            f"color: {tm.text.name()}; font-size: 13px; font-weight: 500;"
        )
        layout.addWidget(bg_label)
        self._bg_label = bg_label

        self._bg_segmented = StyledSegmented(variant="pill", size="sm")
        self._bg_segmented.add_segment("米卡效果")
        self._bg_segmented.add_segment("自定义图片")
        self._bg_segmented.current_changed.connect(self._on_bg_segment_changed)
        # 初始选中项来自 V2：image → 索引 1。守卫内编程式切换，
        # 避免初始化期间触发 _on_bg_segment_changed 的应用/持久化逻辑。
        self._bg_updating = True
        try:
            if self._bg_mode == "image":
                self._bg_segmented.set_current_index(1, animate=False)
        finally:
            self._bg_updating = False
        layout.addWidget(self._bg_segmented)

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

        # 初始按模式设置图片行可见性与米卡滑动条可用性（不触发应用逻辑）
        self._update_bg_ui_state()

        # ── 实验性：原生 DWM 云母（Windows 11） ──
        # 开启后向 DWM 申请系统级云母背景（DWMWA_SYSTEMBACKDROP_TYPE），自研
        # 渲染层停用 —— 合成完全交给 DWM，主线程零自研渲染开销；非 Win11 /
        # dwmapi 调用失败时自动保持自研层（开关回弹由 apply 返回值驱动）。
        native_row = QFrame()
        native_row.setStyleSheet("background: transparent; border: none;")
        native_layout = QHBoxLayout(native_row)
        native_layout.setContentsMargins(0, 0, 0, 0)
        native_layout.setSpacing(12)

        native_label = QLabel("实验性：原生 DWM 云母（Windows 11）")
        native_label.setStyleSheet(
            f"background: transparent; border: none;"
            f"color: {tm.text.name()}; font-size: 13px; font-weight: 500;"
        )
        native_layout.addWidget(native_label)
        native_layout.addStretch()

        saved_native = False
        try:
            saved_native = bool(v2.get("appearance.mica_native_dwm", False))
        except Exception:
            pass
        self._native_mica_toggle = StyledToggle(checked=saved_native, size="default")
        self._native_mica_toggle.toggled.connect(self._on_native_mica_toggle)
        native_layout.addWidget(self._native_mica_toggle)

        layout.addWidget(native_row)

        layout.addStretch()

    # ── 背景米卡效果：滑动条构建与交互 ─────────────────────────────────

    def _build_mica_slider_row(
        self, key: str, spec: dict, initial: float,
    ) -> QFrame:
        """创建单个米卡参数行：参数名 + 当前值显示 + 滑动条。"""
        row = QFrame()
        row.setStyleSheet("background: transparent; border: none;")
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)

        # 头部：参数名（左） + 当前值（右，含单位）
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        name_label = QLabel(spec["name"])
        name_label.setStyleSheet(
            f"background: transparent; border: none;"
            f"color: {tm.text.name()}; font-size: 13px; font-weight: 500;"
        )
        header.addWidget(name_label)
        header.addStretch()

        value_label = QLabel(self._format_mica_value(key, initial))
        value_label.setStyleSheet(
            f"background: transparent; border: none;"
            f"color: {tm.text.name()}; font-size: 13px; font-weight: 500;"
        )
        value_label.setMinimumWidth(56)
        value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header.addWidget(value_label)
        row_layout.addLayout(header)

        # 滑动条（StyledSlider 为 0.0-1.0 归一化值，映射到参数实际区间）
        slider = StyledSlider(value=self._to_norm(key, initial), size="sm")
        slider.value_changed.connect(
            lambda value, k=key: self._on_mica_slider_changed(k, value)
        )
        slider.released.connect(
            lambda k=key: self._on_mica_slider_released(k)
        )
        row_layout.addWidget(slider)

        self._mica_sliders[key] = slider
        self._mica_value_labels[key] = value_label
        self._mica_values[key] = initial
        return row

    def _to_norm(self, key: str, value: float) -> float:
        """参数实际值 → 滑动条归一化值（0.0-1.0）。"""
        spec = MICA_PARAM_SPECS[key]
        span = spec["max"] - spec["min"]
        if span <= 0:
            return 0.0
        return max(0.0, min(1.0, (value - spec["min"]) / span))

    def _from_norm(self, key: str, norm: float) -> float:
        """滑动条归一化值 → 参数实际值（按精度取整）。"""
        spec = MICA_PARAM_SPECS[key]
        value = spec["min"] + (spec["max"] - spec["min"]) * max(0.0, min(1.0, norm))
        return round(value, spec["decimals"])

    def _format_mica_value(self, key: str, value: float) -> str:
        """格式化当前值显示（含单位，如 4.5× / 200 px / 70%）。"""
        spec = MICA_PARAM_SPECS[key]
        return f"{value:.{spec['decimals']}f}{spec['unit']}"

    def _on_mica_slider_changed(self, key: str, norm: float) -> None:
        """拖动中：更新当前值显示，并防抖触发实时预览。"""
        self._mica_values[key] = self._from_norm(key, norm)
        self._mica_value_labels[key].setText(
            self._format_mica_value(key, self._mica_values[key])
        )
        self._mica_preview_timer.start()

    def _on_mica_slider_released(self, key: str) -> None:
        """释放滑动条：立即应用最终值并持久化到 V2。"""
        self._mica_preview_timer.stop()
        self._apply_mica_preview()
        self._save_mica_settings()

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

    def _apply_mica_preview(self) -> None:
        """将当前滑动条值实时应用到主窗口的 Mica 背景（实时预览）。"""
        mw = self._find_main_window()
        if mw is None:
            return
        mica_bg = mw._mica_background
        if mica_bg is None or not hasattr(mica_bg, "apply_mica_parameters"):
            return
        mica_bg.apply_mica_parameters(
            blur_radius=int(round(self._mica_values["blur_radius"])),
            saturation=float(self._mica_values["saturation"]),
            contrast=float(self._mica_values["contrast"]),
            tint_opacity=int(round(self._mica_values["tint_opacity"])),
        )

    def _save_mica_settings(self) -> None:
        """将米卡效果参数持久化到 SettingsManagerV2（重启后恢复）。"""
        try:
            v2 = SettingsManagerV2()
            v2.load()
            v2.set("appearance.mica", {
                "blur_radius": int(round(self._mica_values["blur_radius"])),
                "saturation": float(self._mica_values["saturation"]),
                "contrast": float(self._mica_values["contrast"]),
                "tint_opacity": int(round(self._mica_values["tint_opacity"])),
            })
            v2.save()
        except Exception:
            pass

    def _on_native_mica_toggle(self, checked: bool) -> None:
        """实验开关切换：持久化（appearance.mica_native_dwm）并即时应用到主窗口。

        应用走 ``_mica_background.apply_native_mica``（最佳努力）：DWM 调用
        失败（非 Win11 / dwmapi 缺失）时自研层保持接管，开关状态仅作记录。

        Args:
            checked: 是否启用原生 DWM 云母。
        """
        try:
            v2 = SettingsManagerV2()
            v2.load()
            v2.set("appearance.mica_native_dwm", bool(checked))
            v2.save()
        except Exception:
            pass
        mw = self._find_main_window()
        if mw is None:
            return
        mica_bg = getattr(mw, "_mica_background", None)
        if mica_bg is not None and hasattr(mica_bg, "apply_native_mica"):
            mica_bg.apply_native_mica(checked)

    # ── 窗口背景：模式切换与图片导入 ─────────────────────────────────

    def _on_bg_segment_changed(self, index: int) -> None:
        """窗口背景分段控件切换处理。

        Args:
            index: 新选中的分段索引（0 = 米卡效果，1 = 自定义图片）。
        """
        if self._bg_updating:
            return
        if index == 1:
            # 已有持久化图片且文件存在 → 直接切换；否则强制走选择流程
            if self._bg_image_name and os.path.exists(self._bg_image_path()):
                self._apply_background_settings("image")
            else:
                self._choose_bg_image(force=True)
        else:
            self._apply_background_settings("mica")

    def _on_choose_bg_image_clicked(self) -> None:
        """「选择图片…」按钮点击入口（非强制场景：取消/失败不回退分段）。"""
        self._choose_bg_image(force=False)

    def _choose_bg_image(self, force: bool = False) -> bool:
        """打开文件对话框选择并导入背景图片。

        Args:
            force: True 表示由分段控件首次切入「自定义图片」触发的强制
                选择场景——用户取消或导入失败时把分段控件编程式回退到
                「米卡效果」；False 表示「选择图片…」按钮触发，取消或
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
        self._apply_background_settings("image")
        return True

    def _revert_bg_segment(self) -> None:
        """把分段控件编程式回退到「米卡效果」（守卫内切换不触发处理器）。"""
        self._bg_updating = True
        try:
            self._bg_segmented.set_current_index(0)
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

    def _apply_background_settings(self, mode: str) -> None:
        """切换窗口背景模式：应用到主窗口并持久化。

        Args:
            mode: 目标背景模式："mica" 或 "image"。
        """
        self._bg_mode = mode
        mw = self._find_main_window()
        if mw is not None:
            if mode == "image":
                if hasattr(mw, "set_custom_background_image"):
                    mw.set_custom_background_image(self._bg_image_path())
                if hasattr(mw, "set_background_mode"):
                    mw.set_background_mode("image")
            else:
                if hasattr(mw, "set_background_mode"):
                    mw.set_background_mode("mica")
        self._save_background_settings()
        self._update_bg_ui_state()

    def _save_background_settings(self) -> None:
        """将窗口背景设置持久化到 SettingsManagerV2（重启后恢复）。"""
        try:
            v2 = SettingsManagerV2()
            v2.load()
            v2.set("appearance.background", {
                "mode": self._bg_mode,
                "image": self._bg_image_name,
            })
            v2.save()
        except Exception:
            pass

    def _update_bg_ui_state(self) -> None:
        """按当前背景模式刷新图片行可见性与米卡控件可用性。"""
        is_image = (self._bg_mode == "image")
        self._bg_image_row.setVisible(is_image)
        for slider in self._mica_sliders.values():
            slider.setEnabled(not is_image)
        # 数值标签带 QSS 颜色，需同步切换置灰色（禁用态不会自动变灰）
        value_color = (
            tm.alpha_of(tm.mid, 130).name() if is_image else tm.text.name()
        )
        for label in self._mica_value_labels.values():
            label.setEnabled(not is_image)
            label.setStyleSheet(
                f"background: transparent; border: none;"
                f"color: {value_color}; font-size: 13px; font-weight: 500;"
            )
        self._bg_file_label.setText(
            self._bg_image_name if self._bg_image_name else "未设置"
        )

    def _on_dark_toggle(self, checked: bool) -> None:
        """深色模式开关切换 — 仅记录状态，点击「应用」才全局生效。"""
        # 状态已记录在 self._dark_toggle.checked 中

    def _on_color_clicked(self, color_hex: str) -> None:
        """主题色选择 — 仅记录状态，点击「应用」才全局生效。"""
        self._current_accent = color_hex
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
        """浮动颜色选择面板值变化 — 实时更新当前强调色。"""
        self._current_accent = hex_color
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
        """主题切换时刷新页面内文字颜色。"""
        # 更新 toggle 状态（避免信号循环：暂时断开）
        self._dark_toggle.toggled.disconnect(self._on_dark_toggle)
        self._dark_toggle.checked = tm.is_dark_theme()
        self._dark_toggle.toggled.connect(self._on_dark_toggle)
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
        # 重新应用背景模式相关的可用性/置灰状态（米卡数值标签颜色）
        self._update_bg_ui_state()

    def _load_v2_settings(self) -> None:
        """确保 UI 控件与 V2 保存的值一致（不修改 tm）。"""
        v2 = SettingsManagerV2()
        v2.load()

        saved_theme = v2.get("appearance.theme", "light")
        is_dark = (saved_theme == "dark")
        self._dark_toggle.toggled.disconnect(self._on_dark_toggle)
        self._dark_toggle.checked = is_dark
        self._dark_toggle.toggled.connect(self._on_dark_toggle)

        saved_accent = v2.get("appearance.accent_color", "#007AFF")
        self._current_accent = saved_accent
        preset_values = {btn.color_hex.upper() for btn in self._color_buttons}
        is_preset = saved_accent.upper() in preset_values
        for btn in self._color_buttons:
            btn.selected = (btn.color_hex.upper() == saved_accent.upper())
        if self._custom_btn is not None:
            # 非预设且非 auto 的值视为自定义颜色
            self._custom_btn.selected = (
                not is_preset and saved_accent.upper() != "AUTO"
            )

    def collect_settings(self) -> dict:
        """收集当前页面的 V2 设置值。

        Returns:
            dict: V2 分类树格式的设置字典。
        """
        return {
            "appearance": {
                "theme": "dark" if self._dark_toggle.checked else "light",
                "accent_color": self._current_accent,
            },
        }


class SettingsLayout(QWidget):
    """设置布局"""

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
        self._appearance_page = AppearanceSettingsPage()
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

        # 主题切换时刷新内容区背景
        tm.theme_changed.connect(self._on_theme_changed)

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
        """创建底部按钮栏（重置 + 保存）。"""
        bar = QFrame()
        bar.setObjectName("SettingsBottomBar")
        bar.setStyleSheet("background: transparent; border: none;")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)

        self._reset_btn = StyledButton("重置", variant="secondary", size="sm")
        self._reset_btn.clicked.connect(self._on_reset_clicked)
        layout.addWidget(self._reset_btn)

        layout.addStretch()

        self._apply_btn = StyledButton("应用", variant="primary", size="sm")
        self._apply_btn.clicked.connect(self._on_apply_clicked)
        layout.addWidget(self._apply_btn)

        return bar

    def _on_reset_clicked(self) -> None:
        """重置按钮 — 无功能（占位）。"""

    def _on_apply_clicked(self) -> None:
        """应用按钮 — 将设置全局生效（应用到 tm）并持久化到 SettingsManagerV2。"""
        # 收集当前设置
        appearance = self._appearance_page.collect_settings().get("appearance", {})
        theme = appearance.get("theme", "light")
        accent = appearance.get("accent_color", "#007AFF")

        # "auto" 表示跟随 Windows 系统强调色，应用时解析为实际颜色。
        saved_accent = accent
        if isinstance(accent, str) and accent.lower() == "auto":
            accent = get_system_accent_color()

        # 先捕获设置窗口快照并启动过渡遮罩，再应用主题，实现平滑切换。
        # 使用 grabWindow(HWND) 而非 grab()，避免 OpenGL Mica 背景合成花屏。
        # 设置窗口是主窗口的 owned 子窗口，QWidget.window() 会返回主窗口，
        # 因此优先取创建方显式传入的 host_window。
        settings_window = self._host_window if self._host_window is not None else self.window()
        if settings_window is not None:
            overlay = ThemeTransitionOverlay.from_widget(settings_window)
            overlay.start()

        # 全局生效：应用到 tm
        tm.set_theme(theme)
        tm._colors["accent"]["primary"] = accent
        tm.colors_updated.emit(tm._colors)

        # 持久化到 V2：theme + accent_color + 完整颜色树。
        # 强调色保留原始值（"auto" 或具体 #RRGGBB），不持久化存储 DWM 获取到的
        # 实际颜色数值；程序下次启动时会重新从 DWM 读取。
        colors_dict = copy.deepcopy(tm._colors)
        colors_dict["accent"]["primary"] = saved_accent

        v2 = SettingsManagerV2()
        v2.load()
        v2.set("appearance.theme", theme)
        v2.set("appearance.accent_color", saved_accent)
        v2.set("appearance.colors", colors_dict)
        v2.save()

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
