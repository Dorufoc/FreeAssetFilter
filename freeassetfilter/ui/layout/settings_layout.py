"""
设置布局 — 设置窗口的内容区域（使用 StyledSidebar）
"""

from __future__ import annotations

import copy

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QFrame, QLabel, QStackedWidget,
    QGridLayout, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QRectF, QPropertyAnimation, QEasingCurve, Property, QPoint
from PySide6.QtGui import (
    QPainter, QColor, QPaintEvent, QPen, QFont, QFontMetrics,
    QConicalGradient, QBrush,
)

from theme import tm
from theme.system_accent import get_system_accent_color
from components.styled_sidebar import StyledSidebar
from components.styled_toggle import StyledToggle
from components.styled_button import StyledButton
from components.styled_color_picker import _ColorPanel
from components.theme_transition_overlay import ThemeTransitionOverlay
from freeassetfilter.core.managers.settings_manager_v2 import SettingsManagerV2


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

        color_grid = QGridLayout()
        color_grid.setContentsMargins(0, 0, 0, 0)
        color_grid.setSpacing(12)

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
            row = i // 6
            col = i % 6
            color_grid.addWidget(btn, row, col)
            self._color_buttons.append(btn)

        # 自定义颜色按钮（360° 全色谱渐变）
        self._custom_btn = CustomAccentButton(selected=False)
        self._custom_btn.clicked.connect(self._on_custom_color_clicked)
        custom_idx = len(PRESET_ACCENT_COLORS)
        color_grid.addWidget(self._custom_btn, custom_idx // 6, custom_idx % 6)

        layout.addLayout(color_grid)
        layout.addStretch()

    def _on_dark_toggle(self, checked: bool) -> None:
        """深色模式开关切换 — 仅记录状态，点击「应用」才全局生效。"""
        pass  # 状态已记录在 self._dark_toggle.checked 中

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
            self._custom_panel = None

    def _on_custom_color_clicked(self) -> None:
        """自定义颜色按钮 — 展开/折叠浮动颜色选择面板。"""
        if self._custom_panel is not None:
            if self._custom_panel.isVisible():
                # 面板已展开 → 启动关闭动画并释放引用
                # 使用 close_animated() 而非 hide()，确保事件过滤器被正确移除，
                # 避免 C++ 对象删除后仍收到事件导致 RuntimeError。
                self._custom_panel.close_animated()
                self._custom_panel = None
                return
            # 旧面板引用已失效（隐藏状态下），丢弃
            self._custom_panel = None

        # 提前计算按钮位置，防止 _ColorPanel 创建后污染引用
        btn_pos = self._custom_btn.mapToGlobal(
            QPoint(self._custom_btn.width() + 4, 0)
        )

        # 传入 AppearanceSettingsPage 作为父窗口，防止 _ColorPanel.show()
        # 触发父 SettingsWindow（含 QOpenGLWidget Mica）HWND 重建
        self._custom_panel = _ColorPanel(parent=self)
        self._custom_panel.color_selected.connect(self._on_panel_color_changed)
        self._custom_panel.closed.connect(self._on_panel_closed)

        initial = self._current_accent
        if initial.lower() == "auto" or not initial.startswith("#"):
            initial = tm.accent.name().upper()
        self._custom_panel.set_color(initial)

        # 在 show_animated 之前更新按钮状态，防止 show 触发 HWND 重建
        # 导致 AccentColorButton 的 C++ 对象被删除后访问出错
        for btn in self._color_buttons:
            btn.selected = False
        self._custom_btn.selected = True

        self._custom_panel.show_animated(btn_pos)

    def _on_panel_color_changed(self, hex_color: str) -> None:
        """浮动颜色选择面板值变化 — 实时更新当前强调色。"""
        self._current_accent = hex_color
        for btn in self._color_buttons:
            btn.selected = False
        if self._custom_btn is not None:
            self._custom_btn.selected = True

    def _on_panel_closed(self) -> None:
        """浮动面板关闭后的清理。"""
        self._custom_panel = None

    def refresh_theme(self) -> None:
        """主题切换时刷新页面内文字颜色。"""
        # 更新 toggle 状态（避免信号循环：暂时断开）
        self._dark_toggle.toggled.disconnect(self._on_dark_toggle)
        self._dark_toggle.checked = tm.is_dark_theme()
        self._dark_toggle.toggled.connect(self._on_dark_toggle)
        # 由外部 _refresh_styles 统一刷新文字颜色

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

    def __init__(self, parent=None):
        super().__init__(parent)

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

        # 页面 0：外观
        self._appearance_page = AppearanceSettingsPage()
        appearance_card = self._create_page_card(self._appearance_page)
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
        pass

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
        settings_window = self.window()
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
