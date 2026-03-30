#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 现代化下拉菜单组件
基于 D_HoverMenu + CustomSelectList 实现，提供更稳定、更现代、可扩展的下拉菜单能力。

特性：
- 复用 D_HoverMenu 的稳定弹出/定位/边界修正能力
- 复用 CustomSelectList 的统一列表视觉风格
- 支持 top / bottom / left / right 及四角扩展位置
- 支持内部按钮模式与外部目标控件模式
- 支持键盘快捷键召唤、方向键导航、Enter 确认、Esc 关闭
- 保持对旧版 CustomDropdownMenu 接口的兼容
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QApplication, QLabel
from PySide6.QtCore import Qt, Signal, QEvent, QPoint, QRect, QSize, QTimer
from PySide6.QtGui import QFont, QFontMetrics, QKeySequence, QShortcut, QColor, QPainter, QPen, QBrush

from .D_hover_menu import D_HoverMenu
from .list_widgets import CustomSelectList
from .button_widgets import CustomButton
from freeassetfilter.utils.app_logger import debug


class _DropdownHoverMenu(D_HoverMenu):
    """
    专用于下拉菜单的悬浮菜单承载层。
    复用 D_HoverMenu 的圆角卡片绘制思路，但使用 dropdown 专用的不透明卡片样式。

    与通用 D_HoverMenu 不同：
    - 下拉菜单仅保留透明度动画
    - 不保留位移动画
    - 使用稳定的自绘圆角卡片，而不是视频悬浮栏那种半透明背景
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


class Ddropmenu(QWidget):
    """
    新一代下拉菜单组件。

    支持：
    - 外部按钮/控件作为锚点
    - 内部按钮模式
    - 列表单选
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

        self.list_widget = CustomSelectList(
            parent=self,
            default_width=90,
            default_height=72,
            min_width=60,
            min_height=28,
            selection_mode="single",
        )
        self.list_widget.hide()

        self.hover_menu = _DropdownHoverMenu(
            parent=self,
            position=self.POSITION_MAP[self._position],
            stay_on_top=True,
            hide_on_window_move=True,
            use_sub_widget_mode=False,
            fill_width=False,
            margin=int(2 * self.dpi_scale),
            border_radius=int(8 * self.dpi_scale),
        )
        self.hover_menu.set_content(self.list_widget)
        self.hover_menu.set_timeout_enabled(False)
        self.hover_menu.keyPressed.connect(self._on_menu_key_pressed)
        self.hover_menu.controlBarHidden.connect(self._on_menu_hidden)

        # dropdown 使用 itemWidget 自定义文本层，因此需要去掉 CustomSelectList
        # 默认样式里 QListWidget::item 的左侧文本内边距，否则视觉中心会持续左偏。
        list_style = self.list_widget.list_widget.styleSheet()
        self.list_widget.list_widget.setStyleSheet(
            list_style + """
            QListWidget::item {
                padding-left: 0px;
                padding-right: 0px;
            }
            """
        )

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

    def _install_scrolling_item_widgets(self):
        """为 dropdown 列表项安装基础文本控件，保证文本正确居中显示。"""
        text_color = "#333333"
        if self.settings_manager:
            text_color = self.settings_manager.get_setting("appearance.colors.secondary_color", "#333333")

        list_control = self.list_widget.list_widget
        item_height = max(
            int(19 * self.dpi_scale),
            list_control.sizeHintForRow(0) if list_control.count() > 0 else int(19 * self.dpi_scale)
        )

        viewport_width = list_control.viewport().width() if list_control.viewport() else 0
        fallback_width = max(
            viewport_width,
            list_control.width(),
            self.list_widget.width(),
            self._fixed_width or 0,
            self.list_widget.sizeHint().width(),
            int(60 * self.dpi_scale),
        )

        font_metrics = QFontMetrics(self.global_font)

        for index, item_info in enumerate(self._items):
            qt_item = list_control.item(index)
            if qt_item is None:
                continue

            item_rect = list_control.visualItemRect(qt_item)
            item_width = item_rect.width() if item_rect.isValid() and item_rect.width() > 0 else max(1, fallback_width - int(2 * self.dpi_scale))

            row_widget = QWidget()
            row_widget.setAttribute(Qt.WA_StyledBackground, True)
            row_widget.setStyleSheet("background: transparent; border: none;")
            row_widget.setFixedSize(item_width, item_height)

            qt_item.setText("")

            row_layout = QVBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(0)

            display_text = self._display_text_for_item(item_info)
            elided_text = font_metrics.elidedText(display_text, Qt.ElideRight, max(1, item_width - int(8 * self.dpi_scale)))

            label = QLabel(elided_text, row_widget)
            label.setFont(self.global_font)
            label.setAlignment(Qt.AlignCenter)
            label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            label.setStyleSheet(
                f"background: transparent; border: none; margin: 0; padding: 0; color: {text_color};"
            )

            row_layout.addWidget(label)
            qt_item.setSizeHint(QSize(item_width, item_height))
            list_control.setItemWidget(qt_item, row_widget)

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

        # 直接按照 hover_menu 内真实内容区域几何中心进行对齐，
        # 避免使用容器宽高差值估算导致的视觉偏移。
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
        if 0 <= self._current_index < self.list_widget.list_widget.count():
            self.list_widget.set_current_item(self._current_index)
            current_item = self.list_widget.list_widget.item(self._current_index)
            if current_item:
                self.list_widget.list_widget.scrollToItem(current_item)
        else:
            self.list_widget.clear_selection()

    def _adjust_menu_size(self):
        item_count = len(self._items)

        row_height = self.list_widget.list_widget.sizeHintForRow(0) if item_count > 0 else 0
        row_height = max(int(19 * self.dpi_scale), row_height)

        visible_items = min(item_count, self._max_visible_items) if item_count > 0 else 1

        # 高度策略：仅定义最大高度，上限由 _max_height 控制；
        # 实际显示高度根据内部条目数量自适应，不再人为设置偏大的最小高度。
        list_padding = int(6 * self.dpi_scale)
        visible_height = visible_items * row_height + list_padding

        if item_count <= 0:
            visible_height = int(28 * self.dpi_scale)
        else:
            visible_height = min(self._max_height, visible_height)

        content_width = self._fixed_width if self._fixed_width else self.list_widget.sizeHint().width()
        content_width = max(content_width, int(60 * self.dpi_scale))

        # 只控制 CustomSelectList 的可见尺寸，让其内部 QListWidget 继续使用项目自带的
        # D_ScrollBar + SmoothScroller 布局与滚动逻辑。
        self.list_widget.setFixedSize(content_width, visible_height)
        self.list_widget.adjust_width_to_content()
        self.list_widget.setFixedWidth(content_width)
        self.list_widget.setFixedHeight(visible_height)

        # 外层卡片严格跟随实际可见内容尺寸，不再依赖 D_HoverMenu._update_size 的 sizeHint 逻辑
        self.hover_menu.setFixedSize(self.list_widget.width(), self.list_widget.height())
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

        selected_data = self._items[self._current_index]["data"]
        self.itemClicked.emit(selected_data)
        self.hide_menu()

    def _on_list_item_clicked(self, index: int):
        if not (0 <= index < len(self._items)):
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

        self.list_widget.clear_items()
        self.list_widget.add_items(self._items)

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
        QTimer.singleShot(0, self._install_scrolling_item_widgets)

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

    def set_max_height(self, height: int):
        self._max_height = max(int(28 * self.dpi_scale), int(height))
        self._adjust_menu_size()

    def set_max_visible_items(self, count: int):
        self._max_visible_items = max(1, int(count))
        self._adjust_menu_size()

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
        self.list_widget.list_widget.setFocus()
        QTimer.singleShot(0, self._install_scrolling_item_widgets)

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
            QTimer.singleShot(0, self._install_scrolling_item_widgets)

    def eventFilter(self, obj, event):
        app = QApplication.instance()

        if (
            obj is self._target_widget()
            and self.is_menu_visible()
            and event.type() == QEvent.MouseButtonPress
        ):
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
