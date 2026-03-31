#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 现代化下拉菜单组件
基于 D_HoverMenu 实现，保留现有下拉菜单的定位、显示隐藏动画与交互逻辑，
但其内部列表控件的样式与布局计算全面参考图片预览器右键菜单 D_MoreMenu。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QApplication,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QEvent, QPoint, QRect, QSize, QTimer
from PySide6.QtGui import (
    QFont,
    QFontMetrics,
    QKeySequence,
    QShortcut,
    QColor,
    QPainter,
    QPen,
    QBrush,
)

from .D_hover_menu import D_HoverMenu
from .button_widgets import CustomButton
from .smooth_scroller import D_ScrollBar, SmoothScroller
from freeassetfilter.utils.app_logger import debug


class _DropdownHoverMenu(D_HoverMenu):
    """
    专用于下拉菜单的悬浮菜单承载层。

    与通用 D_HoverMenu 不同：
    - 下拉菜单仅保留透明度动画
    - 不保留位移动画
    - 使用稳定的不透明圆角卡片样式
    """

    def paintEvent(self, event):
        """绘制 dropdown 专用圆角卡片。"""
        app = QApplication.instance()

        if hasattr(app, "settings_manager"):
            settings_manager = app.settings_manager
        else:
            from freeassetfilter.core.settings_manager import SettingsManager

            settings_manager = SettingsManager()

        current_colors = settings_manager.get_setting("appearance.colors", {})
        base_color = current_colors.get("base_color", "#ffffff")
        normal_color = current_colors.get("normal_color", "#d0d0d0")

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        border_pen = QPen(QColor(normal_color))
        border_pen.setWidth(1)
        painter.setPen(border_pen)

        base_qcolor = QColor(base_color)
        base_qcolor.setAlphaF(1.0)
        painter.setBrush(QBrush(base_qcolor))

        rect = QRect(0, 0, self.width() - 1, self.height() - 1)
        radius = self._border_radius
        painter.drawRoundedRect(rect, radius, radius)

    def _animate_show(self):
        """下拉菜单显示动画：仅透明度动画，不执行位移。"""
        if self._is_visible and not self._is_animating and self._get_opacity() >= 0.99:
            return

        self._is_animating = True
        self._stop_timeout_timer()
        self._prepare_geometry_for_show()

        start_opacity = self._get_opacity()
        if not self.isVisible():
            start_opacity = 0.0
            self._opacity_value = start_opacity
            self._vertical_offset = 0
            self._update_mouse_transparency()
            self._update_position_with_offset()
            QWidget.show(self)
        else:
            self._vertical_offset = 0
            self._update_position_with_offset()

        if self._vertical_animation:
            self._vertical_animation.stop()

        self._fade_animation.stop()
        self._fade_animation.setStartValue(start_opacity)
        self._fade_animation.setEndValue(1.0)
        self._fade_animation.start()

        self._is_visible = True

    def _animate_hide(self):
        """下拉菜单隐藏动画：仅透明度动画，不执行位移。"""
        if not self._is_visible or self._is_animating:
            return

        self._is_animating = True
        self._stop_timeout_timer()
        self._vertical_offset = 0
        self._update_position_with_offset()

        if self._vertical_animation:
            self._vertical_animation.stop()

        self._fade_animation.stop()
        self._fade_animation.setStartValue(self._get_opacity())
        self._fade_animation.setEndValue(0.0)
        self._fade_animation.start()


class _DropdownMenuItem(QPushButton):
    """
    dropdown 专用菜单项。
    样式与交互参考 D_MoreMenuItem，但支持 selected / highlighted 状态。
    """

    clickedWithIndex = Signal(int)

    def __init__(self, index: int, item_info: Dict[str, Any], parent=None):
        super().__init__(parent)

        app = QApplication.instance()
        self.dpi_scale = getattr(app, "dpi_scale_factor", 1.0)
        self.global_font = getattr(app, "global_font", QFont())
        self.settings_manager = getattr(app, "settings_manager", None)

        self._index = index
        self._item_info = item_info
        self._hovered = False
        self._selected = False
        self._enabled_state = bool(item_info.get("enabled", True))

        self.setText(str(item_info.get("text", "")))
        self.setFont(self.global_font)
        self.setFlat(True)
        self.setCursor(Qt.PointingHandCursor if self._enabled_state else Qt.ArrowCursor)
        self.setEnabled(self._enabled_state)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        tooltip = str(item_info.get("tooltip", "") or "")
        if tooltip:
            self.setToolTip(tooltip)

        self.clicked.connect(self._emit_clicked_with_index)
        self._apply_stylesheet()

    def _colors(self):
        colors = {
            "base_color": "#ffffff",
            "normal_color": "#f0f0f0",
            "secondary_color": "#333333",
            "accent_color": "#B036EE",
        }

        if self.settings_manager:
            current_colors = self.settings_manager.get_setting("appearance.colors", {})
            colors.update(current_colors)

        return colors

    def _selected_background(self, accent_color: str) -> str:
        qcolor = QColor(accent_color)
        qcolor.setAlpha(80)
        return f"rgba({qcolor.red()}, {qcolor.green()}, {qcolor.blue()}, 0.31)"

    def _apply_stylesheet(self):
        colors = self._colors()

        text_color = colors.get("secondary_color", "#333333")
        hover_color = colors.get("normal_color", "#f0f0f0")
        accent_color = colors.get("accent_color", "#B036EE")
        selected_bg = self._selected_background(accent_color)

        border_radius = int(4 * self.dpi_scale)
        padding_left = int(8 * self.dpi_scale)
        padding_right = int(20 * self.dpi_scale)
        padding_v = int(6 * self.dpi_scale)
        hover_margin = int(1 * self.dpi_scale)

        base_background = "transparent"
        border = "none"

        if self._selected:
            base_background = selected_bg
            border = f"1px solid {accent_color}"

        disabled_text_color = QColor(text_color)
        disabled_text_color.setAlpha(110)

        self.setStyleSheet(
            f"""
            QPushButton {{
                color: {text_color if self._enabled_state else disabled_text_color.name(QColor.HexArgb)};
                padding: {padding_v}px {padding_right}px {padding_v}px {padding_left}px;
                background-color: {base_background};
                border: {border};
                border-radius: {border_radius}px;
                text-align: left;
            }}
            QPushButton:hover {{
                background-color: {hover_color if self._enabled_state and not self._selected else base_background};
                margin: {hover_margin}px;
                padding: {max(0, padding_v - hover_margin)}px {max(0, padding_right - hover_margin)}px {max(0, padding_v - hover_margin)}px {max(0, padding_left - hover_margin)}px;
                border: {border};
                border-radius: {border_radius}px;
            }}
            """
        )

    def _emit_clicked_with_index(self):
        self.clickedWithIndex.emit(self._index)

    def enterEvent(self, event):
        self._hovered = True
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        super().leaveEvent(event)

    def set_selected(self, selected: bool):
        if self._selected == selected:
            return
        self._selected = selected
        self._apply_stylesheet()

    def is_selected(self) -> bool:
        return self._selected

    def item_index(self) -> int:
        return self._index

    def set_item_text(self, text: str):
        self.setText(text)

    def item_info(self) -> Dict[str, Any]:
        return self._item_info


class _DropdownMenuList(QWidget):
    """
    dropdown 专用列表容器。

    参考 D_MoreMenu 的卡片式菜单布局：
    - 外层内容区无额外边框，交给 hover_menu 绘制
    - 内层按钮列表使用按钮式菜单项
    - 宽高计算由文本内容、padding、可见项数量驱动
    """

    itemClicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)

        app = QApplication.instance()
        self.dpi_scale = getattr(app, "dpi_scale_factor", 1.0)
        self.global_font = getattr(app, "global_font", QFont())
        self.settings_manager = getattr(app, "settings_manager", None)

        self._items: List[Dict[str, Any]] = []
        self._item_widgets: List[_DropdownMenuItem] = []
        self._current_index = -1
        self._fixed_width: Optional[int] = None
        self._max_visible_items = 6
        self._max_height = int(140 * self.dpi_scale)

        self._padding = int(4 * self.dpi_scale)
        self._item_spacing = int(2 * self.dpi_scale)
        self._row_min_height = int(20 * self.dpi_scale)
        self._scrollbar_reserved_width = int(10 * self.dpi_scale)

        # 兼容旧调用链：
        # 过去外部代码会访问 dropdown.list_widget.list_widget.sizeHintForRow(0)
        # 这里将 list_widget 指回自身，并补齐少量兼容方法。
        self.list_widget = self

        self._init_ui()

    def _init_ui(self):
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("background: transparent; border: none;")

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(self._padding, self._padding, self._padding, self._padding)
        main_layout.setSpacing(0)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBar(D_ScrollBar(self.scroll_area, Qt.Vertical))
        self.scroll_area.verticalScrollBar().apply_theme_from_settings()
        SmoothScroller.apply_to_scroll_area(self.scroll_area)
        self.scroll_area.setAttribute(Qt.WA_AcceptTouchEvents, False)
        if self.scroll_area.viewport():
            self.scroll_area.viewport().setAttribute(Qt.WA_AcceptTouchEvents, False)
        self.scroll_area.setStyleSheet(
            """
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollArea > QWidget > QWidget {
                background: transparent;
                border: none;
            }
            """
        )

        self.content_widget = QWidget(self.scroll_area)
        self.content_widget.setAttribute(Qt.WA_StyledBackground, True)
        self.content_widget.setStyleSheet("background: transparent; border: none;")
        self.content_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(self._item_spacing)

        self.scroll_area.setWidget(self.content_widget)

        # 下拉菜单列表只允许垂直滚动：
        # QScroller 在 QScrollArea 上默认可产生二维平移，即使横向滚动条被隐藏，
        # 内容宽度与视口宽度稍有抖动时仍可能出现“左右还能拖动一点”的错觉。
        # 这里强制将横向滚动值钳制为 0，彻底禁止横向滚动偏移。
        horizontal_scrollbar = self.scroll_area.horizontalScrollBar()
        horizontal_scrollbar.setDisabled(True)
        horizontal_scrollbar.rangeChanged.connect(lambda *_: horizontal_scrollbar.setValue(0))
        horizontal_scrollbar.valueChanged.connect(
            lambda value: horizontal_scrollbar.setValue(0) if value != 0 else None
        )

        main_layout.addWidget(self.scroll_area)

    def clear_items(self):
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        self._items = []
        self._item_widgets = []
        self._current_index = -1
        self._apply_size()

    def set_items(self, items: Sequence[Dict[str, Any]]):
        self.clear_items()

        self._items = list(items)

        for index, item_info in enumerate(self._items):
            item_widget = _DropdownMenuItem(index, item_info, self.content_widget)
            item_widget.clickedWithIndex.connect(self.itemClicked.emit)
            self.content_layout.addWidget(item_widget)
            self._item_widgets.append(item_widget)

        if self._item_widgets:
            self.set_current_index(0)
        else:
            self._current_index = -1

        self._apply_size()

    def set_fixed_width(self, width: Optional[int]):
        self._fixed_width = None if width is None else max(1, int(width))
        self._apply_size()

    def set_max_visible_items(self, count: int):
        self._max_visible_items = max(1, int(count))
        self._apply_size()

    def set_max_height(self, height: int):
        self._max_height = max(int(28 * self.dpi_scale), int(height))
        self._apply_size()

    def count(self) -> int:
        return len(self._item_widgets)

    def sizeHintForRow(self, index: int) -> int:
        """兼容旧版 QListWidget 风格接口。"""
        if index < 0 or index >= len(self._item_widgets):
            return self._row_height()
        return self._row_height()

    def current_index(self) -> int:
        return self._current_index

    def item_widget(self, index: int) -> Optional[_DropdownMenuItem]:
        if 0 <= index < len(self._item_widgets):
            return self._item_widgets[index]
        return None

    def clear_selection(self):
        self._current_index = -1
        for widget in self._item_widgets:
            widget.set_selected(False)

    def set_current_index(self, index: int):
        if not (0 <= index < len(self._item_widgets)):
            self.clear_selection()
            return

        self._current_index = index
        for item_index, widget in enumerate(self._item_widgets):
            widget.set_selected(item_index == index)

    def scroll_to_index(self, index: int):
        widget = self.item_widget(index)
        if widget is not None:
            self.scroll_area.ensureWidgetVisible(widget, 0, int(4 * self.dpi_scale))

    def _row_height(self) -> int:
        font_metrics = QFontMetrics(self.global_font)
        text_height = font_metrics.height()
        padding_v = int(6 * self.dpi_scale)
        hover_margin = int(1 * self.dpi_scale)
        return max(self._row_min_height, text_height + (padding_v - hover_margin) * 2 + int(2 * self.dpi_scale))

    def _calculate_content_width(self) -> int:
        if self._fixed_width is not None:
            return max(1, self._fixed_width)

        max_item_width = 0
        for index, item_widget in enumerate(self._item_widgets):
            full_text = str(self._items[index].get("text", ""))
            item_widget.set_item_text(full_text)
            max_item_width = max(max_item_width, item_widget.sizeHint().width())

        if max_item_width > 0:
            return max(1, max_item_width)

        font_metrics = QFontMetrics(self.global_font)
        max_text_width = 0

        for item in self._items:
            text = str(item.get("text", ""))
            if text:
                max_text_width = max(max_text_width, font_metrics.horizontalAdvance(text))

        padding_left = int(8 * self.dpi_scale)
        padding_right = int(20 * self.dpi_scale)

        return max(1, max_text_width + padding_left + padding_right)

    def _has_vertical_scrollbar(self) -> bool:
        return len(self._item_widgets) > self._max_visible_items

    def _effective_scrollbar_width(self) -> int:
        scrollbar = self.scroll_area.verticalScrollBar() if hasattr(self, "scroll_area") else None
        if scrollbar is not None:
            hint_width = scrollbar.sizeHint().width()
            if hint_width > 0:
                return hint_width
        return self._scrollbar_reserved_width

    def _calculate_total_width(self) -> int:
        content_width = self._calculate_content_width()
        scrollbar_width = self._effective_scrollbar_width() if self._has_vertical_scrollbar() else 0
        return content_width + scrollbar_width + self._padding * 2

    def _calculate_visible_height(self) -> int:
        item_count = len(self._item_widgets)
        row_height = self._row_height()
        visible_items = min(item_count, self._max_visible_items) if item_count > 0 else 1

        content_height = visible_items * row_height
        if visible_items > 1:
            content_height += (visible_items - 1) * self._item_spacing

        total_height = content_height + self._padding * 2
        return min(max(total_height, int(28 * self.dpi_scale)), self._max_height)

    def _sync_item_text_and_size(self, content_width: int, row_height: int):
        for index, item_widget in enumerate(self._item_widgets):
            text = str(self._items[index].get("text", ""))
            item_widget.set_item_text(text)
            item_widget.setFixedHeight(row_height)
            item_widget.setFixedWidth(content_width)

    def _apply_size(self):
        content_width = self._calculate_content_width()
        visible_height = self._calculate_visible_height()
        row_height = self._row_height()

        item_count = len(self._item_widgets)
        visible_items = min(item_count, self._max_visible_items) if item_count > 0 else 1
        scroll_content_height = visible_items * row_height
        if visible_items > 1:
            scroll_content_height += (visible_items - 1) * self._item_spacing

        needs_scrollbar = self._has_vertical_scrollbar()
        scrollbar_width = self._effective_scrollbar_width() if needs_scrollbar else 0
        scroll_width = content_width + scrollbar_width

        self._sync_item_text_and_size(content_width, row_height)

        self.scroll_area.setFixedWidth(scroll_width)
        self.scroll_area.setFixedHeight(max(1, visible_height - self._padding * 2))
        self.content_widget.setFixedWidth(content_width)
        self.setFixedSize(scroll_width + self._padding * 2, visible_height)

        horizontal_scrollbar = self.scroll_area.horizontalScrollBar()
        if horizontal_scrollbar is not None:
            horizontal_scrollbar.setValue(0)

    def sizeHint(self):
        return QSize(self._calculate_total_width(), self._calculate_visible_height())


class Ddropmenu(QWidget):
    """
    新一代下拉菜单组件。

    支持：
    - 外部按钮/控件作为锚点
    - 内部按钮模式
    - 单选菜单列表
    - 键盘召唤与键盘导航
    - 兼容旧版 CustomDropdownMenu 的常用接口
    """

    itemClicked = Signal(object)
    menuOpening = Signal()
    menuShown = Signal()
    menuHidden = Signal()
    currentItemChanged = Signal(object)

    _active_menu: Optional["Ddropmenu"] = None

    POSITION_MAP = {
        "top": D_HoverMenu.Position_Top,
        "bottom": D_HoverMenu.Position_Bottom,
        "left": D_HoverMenu.Position_Left,
        "right": D_HoverMenu.Position_Right,
        "top_left": D_HoverMenu.Position_TopLeft,
        "top_right": D_HoverMenu.Position_TopRight,
        "bottom_left": D_HoverMenu.Position_BottomLeft,
        "bottom_right": D_HoverMenu.Position_BottomRight,
    }

    def __init__(self, parent=None, position="bottom", use_internal_button=True):
        super().__init__(parent)

        app = QApplication.instance()
        self.dpi_scale = getattr(app, "dpi_scale_factor", 1.0)
        self.global_font = getattr(app, "global_font", QFont())
        self.settings_manager = getattr(app, "settings_manager", None)

        self._position = position if position in self.POSITION_MAP else "bottom"
        self._use_internal_button = use_internal_button
        self._external_target_widget = None
        self._installed_target_widget = None
        self._fixed_width = None
        self._max_height = int(140 * self.dpi_scale)
        self._max_visible_items = 6
        self._items: List[Dict[str, Any]] = []
        self._current_index = -1
        self._current_item = None
        self._menu_visible = False
        self._shortcut: Optional[QShortcut] = None

        self._layout_refresh_timer = QTimer(self)
        self._layout_refresh_timer.setSingleShot(True)
        self._layout_refresh_timer.timeout.connect(self._refresh_visible_menu_position)

        self._init_ui()
        self._bind_signals()

        app = QApplication.instance()
        if app:
            app.installEventFilter(self)

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        if self._use_internal_button:
            self.main_button = CustomButton(
                text="",
                button_type="normal",
                display_mode="text",
            )
            main_layout.addWidget(self.main_button)
        else:
            self.main_button = None

        self.list_widget = _DropdownMenuList(parent=self)
        self.list_widget.hide()

        self.hover_menu = _DropdownHoverMenu(
            parent=self,
            position=self.POSITION_MAP[self._position],
            stay_on_top=True,
            hide_on_window_move=True,
            use_sub_widget_mode=False,
            fill_width=False,
            margin=int(2 * self.dpi_scale),
            border_radius=int(4 * self.dpi_scale),
        )
        self.hover_menu.set_content(self.list_widget)
        self.hover_menu.set_timeout_enabled(False)
        self.hover_menu.keyPressed.connect(self._on_menu_key_pressed)
        self.hover_menu.controlBarHidden.connect(self._on_menu_hidden)

        self.list_widget.installEventFilter(self)
        self.list_widget.scroll_area.installEventFilter(self)
        self.list_widget.content_widget.installEventFilter(self)
        self.hover_menu.installEventFilter(self)

    def _bind_signals(self):
        if self.main_button:
            self.main_button.clicked.connect(self.toggle_menu)

        self.list_widget.itemClicked.connect(self._on_list_item_clicked)

    def _normalize_item(self, item: Any) -> Dict[str, Any]:
        if isinstance(item, dict):
            return {
                "text": str(item.get("text", "")),
                "data": item.get("data", item.get("text", "")),
                "icon_path": item.get("icon_path", ""),
                "enabled": item.get("enabled", True),
                "tooltip": item.get("tooltip", ""),
            }

        return {
            "text": str(item),
            "data": item,
            "icon_path": "",
            "enabled": True,
            "tooltip": "",
        }

    def _display_text_for_item(self, item: Dict[str, Any]) -> str:
        return str(item.get("text", ""))

    def _schedule_layout_refresh(self, delay_ms: int = 0):
        delay_ms = max(0, int(delay_ms))
        self._layout_refresh_timer.stop()
        self._layout_refresh_timer.start(delay_ms)

    def _refresh_visible_menu_position(self):
        """内容宽高稳定后，重新同步一次弹出菜单位置。"""
        if not self.hover_menu.isVisible():
            return

        self.hover_menu.updateGeometry()
        self.hover_menu._prepare_geometry_for_show()

    def _target_widget(self):
        return self._external_target_widget or self.main_button

    def _update_target_event_filter(self):
        target = self._target_widget()

        if self._installed_target_widget is target:
            return

        if self._installed_target_widget is not None:
            try:
                self._installed_target_widget.removeEventFilter(self)
            except RuntimeError:
                pass

        self._installed_target_widget = target

        if self._installed_target_widget is not None:
            self._installed_target_widget.installEventFilter(self)

    def _calculate_dropdown_position(self, target_rect, menu_size):
        spacing = int(4 * self.dpi_scale)
        pos = QPoint()

        anchor_center_x = target_rect.left() + target_rect.width() / 2.0
        anchor_center_y = target_rect.top() + target_rect.height() / 2.0
        target_bottom = target_rect.top() + target_rect.height()
        target_right = target_rect.left() + target_rect.width()

        content_widget = getattr(self.hover_menu, "_content_widget", None)
        if content_widget is not None and content_widget.width() > 0 and content_widget.height() > 0:
            content_x = content_widget.x()
            content_y = content_widget.y()
            content_width = content_widget.width()
            content_height = content_widget.height()
        else:
            content_x = 0
            content_y = 0
            content_width = menu_size.width()
            content_height = menu_size.height()

        centered_x = int(round(anchor_center_x - (content_x + content_width / 2.0)))
        centered_y = int(round(anchor_center_y - (content_y + content_height / 2.0)))

        if self._position == "top":
            pos.setX(centered_x)
            pos.setY(int(round(target_rect.top() - menu_size.height() - spacing)))
        elif self._position == "bottom":
            pos.setX(centered_x)
            pos.setY(int(round(target_bottom + spacing)))
        elif self._position == "left":
            pos.setX(int(round(target_rect.left() - menu_size.width() - spacing)))
            pos.setY(centered_y)
        elif self._position == "right":
            pos.setX(int(round(target_right + spacing)))
            pos.setY(centered_y)
        elif self._position == "top_left":
            pos.setX(centered_x)
            pos.setY(int(round(target_rect.top() - menu_size.height() - spacing)))
        elif self._position == "top_right":
            pos.setX(centered_x)
            pos.setY(int(round(target_rect.top() - menu_size.height() - spacing)))
        elif self._position == "bottom_left":
            pos.setX(centered_x)
            pos.setY(int(round(target_bottom + spacing)))
        elif self._position == "bottom_right":
            pos.setX(centered_x)
            pos.setY(int(round(target_bottom + spacing)))
        else:
            pos.setX(centered_x)
            pos.setY(int(round(target_bottom + spacing)))

        return pos

    def _update_animation_direction(self):
        # 下拉菜单禁用位移动画，仅保留透明度动画
        self.hover_menu._hidden_vertical_offset = 0
        self.hover_menu._vertical_offset = 0

    def _sync_menu_target(self):
        target = self._target_widget()
        self._update_target_event_filter()
        if target:
            self.hover_menu.set_target_widget(target)
        self.hover_menu.set_position(self.POSITION_MAP.get(self._position, D_HoverMenu.Position_Bottom))
        self.hover_menu.set_custom_position_callback(self._calculate_dropdown_position)

    def _apply_button_text(self):
        if not self.main_button or not (0 <= self._current_index < len(self._items)):
            return

        text = self._display_text_for_item(self._items[self._current_index])

        if self._fixed_width:
            font_metrics = QFontMetrics(self.main_button.font())
            text = font_metrics.elidedText(text, Qt.ElideRight, max(8, self._fixed_width - int(8 * self.dpi_scale)))

        self.main_button.setText(text)
        self.main_button.update()

    def _update_list_visual_state(self):
        if 0 <= self._current_index < self.list_widget.count():
            self.list_widget.set_current_index(self._current_index)
            self.list_widget.scroll_to_index(self._current_index)
        else:
            self.list_widget.clear_selection()

    def _adjust_menu_size(self):
        self.list_widget.set_fixed_width(self._fixed_width)
        self.list_widget.set_max_height(self._max_height)
        self.list_widget.set_max_visible_items(self._max_visible_items)

        content_size = self.list_widget.sizeHint()
        self.list_widget.setFixedSize(content_size)
        self.hover_menu.setFixedSize(content_size)
        self.hover_menu.updateGeometry()
        self.hover_menu.update()

    def _find_index_by_value(self, item: Any) -> int:
        if not self._items:
            return -1

        item_float = None
        if isinstance(item, str):
            try:
                item_float = float(item.replace("x", ""))
            except ValueError:
                item_float = None

        for index, menu_item in enumerate(self._items):
            menu_text = menu_item.get("text", "")
            menu_data = menu_item.get("data", menu_text)

            if isinstance(item, dict):
                item_text = item.get("text", "")
                item_data = item.get("data", item_text)
                if (
                    menu_text == item_text
                    or menu_data == item_data
                    or menu_text == item_data
                    or menu_data == item_text
                ):
                    return index
                continue

            menu_text_float = None
            if isinstance(menu_text, str):
                try:
                    menu_text_float = float(menu_text.replace("x", ""))
                except ValueError:
                    menu_text_float = None

            menu_data_float = None
            if isinstance(menu_data, str):
                try:
                    menu_data_float = float(menu_data.replace("x", ""))
                except ValueError:
                    menu_data_float = None

            if (
                menu_text == item
                or menu_data == item
                or (item_float is not None and menu_text_float == item_float)
                or (item_float is not None and menu_data_float == item_float)
            ):
                return index

        return -1

    def _select_index(self, index: int, emit_signal: bool = False):
        if not (0 <= index < len(self._items)):
            return

        self._current_index = index
        self._current_item = self._items[index]
        self._update_list_visual_state()
        self._apply_button_text()

        if emit_signal:
            self.currentItemChanged.emit(self.current_item())

    def _move_highlight(self, delta: int):
        if not self._items:
            return

        if self._current_index < 0:
            next_index = 0
        else:
            next_index = (self._current_index + delta) % len(self._items)

        self._select_index(next_index, emit_signal=True)

    def _activate_current_item(self):
        if not (0 <= self._current_index < len(self._items)):
            return

        if not self._items[self._current_index].get("enabled", True):
            return

        selected_data = self._items[self._current_index]["data"]
        self.itemClicked.emit(selected_data)
        self.hide_menu()

    def _on_list_item_clicked(self, index: int):
        if not (0 <= index < len(self._items)):
            return

        if not self._items[index].get("enabled", True):
            return

        self._select_index(index, emit_signal=True)
        selected_data = self._items[index]["data"]
        self.itemClicked.emit(selected_data)
        self.hide_menu()

    def _on_menu_hidden(self):
        if self._menu_visible:
            self._menu_visible = False
            self.menuHidden.emit()

    def _on_menu_key_pressed(self, event):
        key = event.key()

        if key in (Qt.Key_Up, Qt.Key_Left):
            self._move_highlight(-1)
            event.accept()
            return

        if key in (Qt.Key_Down, Qt.Key_Right):
            self._move_highlight(1)
            event.accept()
            return

        if key in (Qt.Key_Return, Qt.Key_Enter):
            self._activate_current_item()
            event.accept()
            return

        if key == Qt.Key_Escape:
            self.hide_menu()
            event.accept()
            return

    def set_items(self, items: Sequence[Any], default_item: Any = None):
        self._items = [self._normalize_item(item) for item in items]

        self.list_widget.set_items(self._items)

        if default_item is not None:
            self.set_current_item(default_item)
        elif self._items:
            self._select_index(0, emit_signal=False)
        else:
            self._current_index = -1
            self._current_item = None
            if self.main_button:
                self.main_button.setText("")

        self._adjust_menu_size()
        self._schedule_layout_refresh(0)

    def set_current_item(self, item: Any):
        index = item if isinstance(item, int) and 0 <= item < len(self._items) else self._find_index_by_value(item)
        if index >= 0:
            self._select_index(index, emit_signal=False)

    def current_item(self):
        if not (0 <= self._current_index < len(self._items)):
            return None
        return self._items[self._current_index]["data"]

    def current_item_info(self):
        if not (0 <= self._current_index < len(self._items)):
            return None
        return self._items[self._current_index]

    def set_fixed_width(self, width: int):
        self._fixed_width = max(1, int(width))
        if self.main_button:
            self.main_button.setFixedWidth(self._fixed_width)
        self._adjust_menu_size()
        self._apply_button_text()
        self._schedule_layout_refresh(0)

    def set_max_height(self, height: int):
        self._max_height = max(int(28 * self.dpi_scale), int(height))
        self._adjust_menu_size()
        self._schedule_layout_refresh(0)

    def set_max_visible_items(self, count: int):
        self._max_visible_items = max(1, int(count))
        self._adjust_menu_size()
        self._schedule_layout_refresh(0)

    def set_position(self, position: str):
        if position in self.POSITION_MAP:
            self._position = position
            self.hover_menu.set_position(self.POSITION_MAP[position])

    def set_target_widget(self, widget):
        self._external_target_widget = widget
        self._sync_menu_target()

    def set_target_button(self, button):
        self.set_target_widget(button)

    def set_target_rect(self, rect):
        self._external_target_widget = None
        self.hover_menu.set_target_rect(rect)

    def set_offset(self, offset_x: int, offset_y: int):
        self.hover_menu.set_offset(offset_x, offset_y)

    def set_shortcut(self, key_sequence, context=Qt.WidgetWithChildrenShortcut):
        if self._shortcut:
            self._shortcut.deleteLater()
            self._shortcut = None

        host = self._target_widget() or self.parent() or self
        if host is None:
            return

        if not isinstance(key_sequence, QKeySequence):
            key_sequence = QKeySequence(key_sequence)

        self._shortcut = QShortcut(key_sequence, host)
        self._shortcut.setContext(context)
        self._shortcut.activated.connect(self.summon)

    def clear_shortcut(self):
        if self._shortcut:
            self._shortcut.deleteLater()
            self._shortcut = None

    def summon(self):
        self.show_menu()

    def trigger_by_key(self):
        self.summon()

    def show_menu(self):
        if not self._items:
            return

        previous_menu = Ddropmenu._active_menu
        if previous_menu is not None and previous_menu is not self:
            previous_menu.hide_menu()

        self.menuOpening.emit()
        self._sync_menu_target()
        self._adjust_menu_size()
        self._update_animation_direction()

        self.hover_menu.show()
        self._menu_visible = True
        Ddropmenu._active_menu = self
        self.menuShown.emit()

        if self._current_index < 0 and self._items:
            self._select_index(0, emit_signal=False)

        self.list_widget.show()
        self._schedule_layout_refresh(0)

    def hide_menu(self):
        if not self._menu_visible and not self.hover_menu.isVisible():
            return
        self.hover_menu.hide()
        self._menu_visible = False
        if Ddropmenu._active_menu is self:
            Ddropmenu._active_menu = None

    def toggle_menu(self):
        if self.is_menu_visible():
            self.hide_menu()
        else:
            self.show_menu()

    def is_menu_visible(self):
        return self._menu_visible or self.hover_menu.is_visible()

    def enterEvent(self, event):
        super().enterEvent(event)

    def leaveEvent(self, event):
        super().leaveEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._fixed_width is None:
            self._adjust_menu_size()

        if self._items:
            self._schedule_layout_refresh(0)

    def eventFilter(self, obj, event):
        app = QApplication.instance()

        if (
            obj in (
                self.list_widget,
                self.list_widget.scroll_area,
                self.list_widget.content_widget,
                self.hover_menu,
            )
            and event.type() in (QEvent.Resize, QEvent.Show, QEvent.LayoutRequest)
            and self._items
        ):
            delay_ms = 16 if event.type() == QEvent.Show else 0
            self._schedule_layout_refresh(delay_ms)

        if obj is self._target_widget() and self.is_menu_visible() and event.type() == QEvent.MouseButtonPress:
            self.hide_menu()
            event.accept()
            return True

        if obj is app and event.type() in (QEvent.ApplicationDeactivate, QEvent.WindowDeactivate):
            if self.is_menu_visible():
                self.hide_menu()

        return super().eventFilter(obj, event)


class CustomDropdownMenu(Ddropmenu):
    """
    旧接口兼容类。
    现已由 Ddropmenu 作为核心实现承载。
    """

    pass
