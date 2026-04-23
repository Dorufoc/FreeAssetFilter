from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple, Union

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionViewItem

from freeassetfilter.core.settings_manager import SettingsManager
from freeassetfilter.utils.app_logger import debug
from freeassetfilter.widgets.file_selector_delegate import FileBlockCardDelegate
from freeassetfilter.widgets.file_staging_pool_model import FileStagingPoolListModel


class FileStagingPoolCardDelegate(FileBlockCardDelegate):
    renameRequested = Signal(str)
    deleteRequested = Signal(str)

    ACTION_RENAME = "rename"
    ACTION_DELETE = "delete"

    def __init__(
        self,
        dpi_scale: float = 1.0,
        global_font=None,
        single_line_mode: bool = False,
        enable_delete_action: bool = True,
        parent=None,
    ):
        self._single_line_mode = bool(single_line_mode)
        self._enable_delete_action = bool(enable_delete_action)
        self._pressed_action_key: Optional[Tuple[str, str]] = None
        super().__init__(dpi_scale=dpi_scale, global_font=global_font, parent=parent)

    def clear_caches(self):
        self._pressed_action_key = None
        super().clear_caches()

    def set_single_line_mode(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self._single_line_mode == enabled:
            return
        self._single_line_mode = enabled
        if self._view:
            self._view.viewport().update()

    def set_enable_delete_action(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self._enable_delete_action == enabled:
            return
        self._enable_delete_action = enabled
        if self._view:
            self._view.viewport().update()

    def _get_settings_manager(self):
        app = QApplication.instance()
        if app and hasattr(app, "settings_manager"):
            return app.settings_manager
        return SettingsManager()

    def _darken_or_lighten_color(self, color_value: Any, percentage: float) -> QColor:
        settings_manager = self._get_settings_manager()
        color = QColor(color_value)
        current_theme = settings_manager.get_setting("appearance.theme", "default")
        is_dark_mode = current_theme == "dark"

        if is_dark_mode:
            luminance = (
                0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
            ) / 255.0
            if luminance < 0.1:
                adjusted_percentage = min(percentage * 2.5, 0.4)
            elif luminance < 0.3:
                adjusted_percentage = min(percentage * 1.8, 0.35)
            else:
                adjusted_percentage = percentage

            red = min(255, int(color.red() + (255 - color.red()) * adjusted_percentage))
            green = min(255, int(color.green() + (255 - color.green()) * adjusted_percentage))
            blue = min(255, int(color.blue() + (255 - color.blue()) * adjusted_percentage))
            return QColor(red, green, blue)

        red = max(0, int(color.red() * (1 - percentage)))
        green = max(0, int(color.green() * (1 - percentage)))
        blue = max(0, int(color.blue() * (1 - percentage)))
        return QColor(red, green, blue)

    def _init_colors(self):
        try:
            app = QApplication.instance()
            settings_manager = getattr(app, "settings_manager", None) if app else None
            if settings_manager is None:
                settings_manager = SettingsManager()

            self.accent_color = settings_manager.get_setting(
                "appearance.colors.accent_color",
                "#1890ff",
            )
            self.base_color = settings_manager.get_setting(
                "appearance.colors.base_color",
                "#ffffff",
            )
            self.normal_color = settings_manager.get_setting(
                "appearance.colors.normal_color",
                "#e0e0e0",
            )
            self.secondary_color = settings_manager.get_setting(
                "appearance.colors.secondary_color",
                "#333333",
            )
            self.auxiliary_color = settings_manager.get_setting(
                "appearance.colors.auxiliary_color",
                "#f0f8ff",
            )
            self.warning_color = settings_manager.get_setting(
                "appearance.colors.notification_error",
                "#F44336",
            )
            notification_text = settings_manager.get_setting(
                "appearance.colors.notification_text",
                "#FFFFFF",
            )
            self.button_warning_text = settings_manager.get_setting(
                "appearance.colors.button_warning_text",
                notification_text,
            )
        except Exception as error:
            debug(f"初始化存储池卡片委托颜色失败，使用默认颜色: {error}")
            self.accent_color = "#1890ff"
            self.base_color = "#ffffff"
            self.normal_color = "#e0e0e0"
            self.secondary_color = "#333333"
            self.auxiliary_color = "#f0f8ff"
            self.warning_color = "#F44336"
            self.button_warning_text = "#FFFFFF"

        self._normal_bg = QColor(self.base_color)
        self._hover_bg = QColor(self.auxiliary_color)
        self._selected_bg = QColor(self.accent_color)
        self._selected_bg.setAlpha(102)

        self._normal_border = QColor(self.auxiliary_color)
        self._hover_border = QColor(self.normal_color)
        self._selected_border = QColor(self.accent_color)
        self._preview_border = QColor(self.secondary_color)
        self._text_color = QColor(self.secondary_color)
        self._info_color = QColor(self.secondary_color)
        self._missing_name_color = QColor(self.normal_color)
        self._missing_info_color = QColor(self.normal_color)

    def _init_fonts(self):
        app = QApplication.instance()
        self.global_font = (
            getattr(app, "global_font", self._global_font or QFont())
            if app
            else (self._global_font or QFont())
        )

        self.name_font = QFont(self.global_font)
        self.name_font.setBold(True)

        self.info_font = QFont(self.global_font)
        self.info_font.setWeight(QFont.Normal)

        self.button_font = QFont(self.global_font)
        self.button_font.setWeight(QFont.DemiBold)

        self.name_font_metrics = QFontMetrics(self.name_font)
        self.info_font_metrics = QFontMetrics(self.info_font)
        self.button_font_metrics = QFontMetrics(self.button_font)

    @staticmethod
    def _format_file_size(size_value) -> str:
        if size_value is None:
            return ""

        try:
            size = float(size_value)
        except (TypeError, ValueError):
            return ""

        if size < 0:
            size = 0.0
        if size < 1024:
            return f"{int(size)} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.2f} KB"
        if size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.2f} MB"
        return f"{size / (1024 * 1024 * 1024):.2f} GB"

    def _get_file_info(self, index):
        model = index.model()
        if not model:
            return {}

        return {
            "path": model.data(index, FileStagingPoolListModel.FilePathRole) or "",
            "name": model.data(index, FileStagingPoolListModel.FileNameRole) or "",
            "display_name": model.data(index, FileStagingPoolListModel.DisplayNameRole) or "",
            "visible_name": model.data(index, Qt.DisplayRole) or "",
            "original_name": model.data(index, FileStagingPoolListModel.OriginalNameRole) or "",
            "is_dir": model.data(index, FileStagingPoolListModel.IsDirRole) or False,
            "size": model.data(index, FileStagingPoolListModel.FileSizeRole),
            "created": model.data(index, FileStagingPoolListModel.CreatedRole) or "",
            "modified": model.data(index, FileStagingPoolListModel.ModifiedRole) or "",
            "suffix": (model.data(index, FileStagingPoolListModel.SuffixRole) or "").lower(),
            "is_selected": model.data(index, FileStagingPoolListModel.IsSelectedRole) or False,
            "is_previewing": model.data(index, FileStagingPoolListModel.IsPreviewingRole) or False,
            "is_missing": model.data(index, FileStagingPoolListModel.IsMissingRole) or False,
            "size_calculating": model.data(index, FileStagingPoolListModel.SizeCalculatingRole) or False,
            "info_text": model.data(index, FileStagingPoolListModel.InfoTextRole) or "",
            "icon_pixmap": model.data(index, FileStagingPoolListModel.IconPixmapRole),
            "item_size": model.data(index, FileStagingPoolListModel.ItemSizeRole),
        }

    def _button_layout_metrics(self) -> dict[str, int]:
        dpi_scale = self._dpi_scale
        return {
            "margin_x": int(2.5 * dpi_scale),
            "margin_y": int(6.25 * dpi_scale),
            "spacing": int(2.5 * dpi_scale),
        }

    def _button_metrics(self, text: str, button_type: str) -> dict[str, float]:
        border_width = 0.0 if button_type == "primary" else 1.5
        min_height = int(20 * self._dpi_scale)
        vertical_padding = int(4 * self._dpi_scale) * 2
        horizontal_padding = int(6 * self._dpi_scale)
        safety_margin = int(4 * self._dpi_scale)
        text_width = self.button_font_metrics.horizontalAdvance(text)
        text_height = self.button_font_metrics.height()
        height = max(min_height, int(text_height + vertical_padding + border_width * 2))
        width = max(
            int(25 * self._dpi_scale),
            int(text_width + horizontal_padding * 2 + border_width * 2 + safety_margin),
        )
        return {
            "width": width,
            "height": height,
            "radius": height / 2.0,
        }

    def _calculate_geometry(self, rect: QRect):
        dpi_scale = self._dpi_scale

        border_width = max(1, int(1 * dpi_scale))
        preview_border_width = border_width * 2
        radius = max(1, int(8 * dpi_scale))

        margin_x = int(7.5 * dpi_scale)
        margin_y = int(6.25 * dpi_scale)
        content_spacing = int(7.5 * dpi_scale)
        icon_size = int(40 * dpi_scale)
        text_spacing = 0 if self._single_line_mode else int(4 * dpi_scale)

        content_rect = rect.adjusted(margin_x, margin_y, -margin_x, -margin_y)

        icon_side = min(icon_size, max(0, content_rect.width()), max(0, content_rect.height()))
        icon_rect = QRect(
            content_rect.x(),
            content_rect.y() + max(0, (content_rect.height() - icon_side) // 2),
            icon_side,
            icon_side,
        )

        text_x = icon_rect.right() + 1 + content_spacing
        text_width = max(0, content_rect.right() - text_x + 1)
        text_rect = QRect(text_x, content_rect.y(), text_width, content_rect.height())

        name_height = self.name_font_metrics.height()
        info_height = self.info_font_metrics.height()

        if self._single_line_mode:
            total_height = name_height
            start_y = text_rect.y() + max(0, (text_rect.height() - total_height) // 2)
            name_rect = QRect(text_rect.x(), start_y, text_rect.width(), name_height)
            info_rect = QRect(text_rect.x(), start_y, text_rect.width(), 0)
        else:
            total_height = name_height + text_spacing + info_height
            start_y = text_rect.y() + max(0, (text_rect.height() - total_height) // 2)
            name_rect = QRect(text_rect.x(), start_y, text_rect.width(), name_height)
            info_rect = QRect(
                text_rect.x(),
                name_rect.bottom() + 1 + text_spacing,
                text_rect.width(),
                info_height,
            )

        text_max_width = max(
            int(50 * dpi_scale),
            rect.width() - margin_x * 2 - icon_size - content_spacing - int(10 * dpi_scale),
        )

        return {
            "border_width": border_width,
            "preview_border_width": preview_border_width,
            "radius": radius,
            "icon_rect": icon_rect,
            "name_rect": name_rect,
            "info_rect": info_rect,
            "text_max_width": max(0, min(text_rect.width(), text_max_width)),
        }

    def _visible_display_name(self, file_info: dict[str, Any]) -> str:
        visible_name = str(file_info.get("visible_name", "") or "")
        if visible_name:
            return visible_name

        display_name = str(file_info.get("display_name", "") or file_info.get("name", "") or "")
        if display_name:
            if file_info.get("is_missing", False):
                return f"{display_name}（已移动或删除）"
            return display_name

        file_path = str(file_info.get("path", "") or "")
        fallback_name = os.path.basename(file_path) or file_path
        if file_info.get("is_missing", False) and fallback_name:
            return f"{fallback_name}（已移动或删除）"
        return fallback_name

    def _inline_size_text(self, file_info: dict[str, Any]) -> str:
        if file_info.get("is_missing", False):
            return ""
        if file_info.get("is_dir", False):
            if file_info.get("size_calculating", False):
                return "正在计算大小..."
            size_text = self._format_file_size(file_info.get("size"))
            return size_text or "文件夹"
        return self._format_file_size(file_info.get("size"))

    def _compose_texts(self, file_info: dict[str, Any]) -> tuple[str, str]:
        name_text = self._visible_display_name(file_info)
        info_text = str(file_info.get("info_text", "") or "")

        if self._single_line_mode:
            inline_size = self._inline_size_text(file_info)
            if inline_size and not file_info.get("is_missing", False):
                return f"{name_text} ({inline_size})", ""
            return name_text, ""

        return name_text, info_text

    def _action_sequence(self) -> list[str]:
        actions = [self.ACTION_RENAME]
        if self._enable_delete_action:
            actions.append(self.ACTION_DELETE)
        return actions

    def _action_text(self, action: str) -> str:
        if action == self.ACTION_DELETE:
            return "删除"
        return "重命名"

    def _action_button_type(self, action: str) -> str:
        if action == self.ACTION_DELETE:
            return "warning"
        return "primary"

    def get_action_rects(
        self,
        option: QStyleOptionViewItem,
        index,
    ) -> dict[str, QRect]:
        layout_metrics = self._button_layout_metrics()
        overlay_rect = option.rect.adjusted(
            layout_metrics["margin_x"],
            layout_metrics["margin_y"],
            -layout_metrics["margin_x"],
            -layout_metrics["margin_y"],
        )
        if overlay_rect.width() <= 0 or overlay_rect.height() <= 0:
            return {}

        action_specs: list[tuple[str, dict[str, float]]] = []
        max_height = 0
        for action in self._action_sequence():
            metrics = self._button_metrics(
                self._action_text(action),
                self._action_button_type(action),
            )
            action_specs.append((action, metrics))
            max_height = max(max_height, int(metrics["height"]))

        if not action_specs or max_height <= 0:
            return {}

        top = overlay_rect.y() + max(0, (overlay_rect.height() - max_height) // 2)
        right_edge = overlay_rect.x() + overlay_rect.width()
        spacing = layout_metrics["spacing"]
        rects: dict[str, QRect] = {}

        for action, metrics in reversed(action_specs):
            width = int(metrics["width"])
            height = int(metrics["height"])
            x = right_edge - width
            y = top + max(0, (max_height - height) // 2)
            rects[action] = QRect(x, y, width, height)
            right_edge = x - spacing

        ordered_rects: dict[str, QRect] = {}
        for action in self._action_sequence():
            if action in rects:
                ordered_rects[action] = rects[action]
        return ordered_rects

    def get_action_rect(
        self,
        action: str,
        option: QStyleOptionViewItem,
        index,
    ) -> QRect:
        return self.get_action_rects(option, index).get(action, QRect())

    def get_rename_action_rect(self, option: QStyleOptionViewItem, index) -> QRect:
        return self.get_action_rect(self.ACTION_RENAME, option, index)

    def get_delete_action_rect(self, option: QStyleOptionViewItem, index) -> QRect:
        return self.get_action_rect(self.ACTION_DELETE, option, index)

    def get_action_area_rect(
        self,
        option: QStyleOptionViewItem,
        index,
    ) -> QRect:
        rects = self.get_action_rects(option, index)
        if not rects:
            return QRect()

        area_rect = QRect()
        for rect in rects.values():
            area_rect = rect if area_rect.isNull() else area_rect.united(rect)
        return area_rect

    def should_show_action_area(
        self,
        option: QStyleOptionViewItem,
        index,
        for_drag_preview: bool = False,
    ) -> bool:
        if for_drag_preview:
            return False

        file_info = self._get_file_info(index)
        if not file_info or file_info.get("is_previewing", False):
            return False

        file_path = self._normalize_path(file_info.get("path", ""))
        if self._dragging_file_path and file_path == self._dragging_file_path:
            return False

        item_key = self._get_animation_key(file_info)
        is_action_pressed = bool(self._pressed_action_key and self._pressed_action_key[0] == item_key)
        is_hovered = bool(option.state & QStyle.State_MouseOver)
        return is_hovered or is_action_pressed

    def hit_test_action(
        self,
        option: QStyleOptionViewItem,
        index,
        pos: QPoint,
        require_visible: bool = True,
    ) -> str | None:
        if require_visible and not self.should_show_action_area(option, index):
            return None

        for action, rect in self.get_action_rects(option, index).items():
            if rect.contains(pos):
                return action
        return None

    def action_at(
        self,
        option: QStyleOptionViewItem,
        index,
        pos: QPoint,
        require_visible: bool = True,
    ) -> str | None:
        return self.hit_test_action(option, index, pos, require_visible=require_visible)

    def _current_hovered_action(
        self,
        option: QStyleOptionViewItem,
        index,
        for_drag_preview: bool = False,
    ) -> Optional[str]:
        if not self.should_show_action_area(option, index, for_drag_preview=for_drag_preview):
            return None
        if option.widget is None:
            return None

        try:
            cursor_pos = option.widget.mapFromGlobal(QCursor.pos())
        except RuntimeError:
            return None

        if not option.rect.contains(cursor_pos):
            return None
        return self.hit_test_action(option, index, cursor_pos, require_visible=False)

    def _button_colors(self, action: str, hovered: bool, pressed: bool) -> Dict[str, Union[QColor, float]]:
        if action == self.ACTION_DELETE:
            normal_bg = QColor(self.warning_color)
            hover_bg = self._darken_or_lighten_color(self.warning_color, 0.1)
            pressed_bg = self._darken_or_lighten_color(self.warning_color, 0.2)
            normal_border = QColor(self.warning_color)
            hover_border = self._darken_or_lighten_color(self.warning_color, 0.1)
            pressed_border = self._darken_or_lighten_color(self.warning_color, 0.2)
            text_color = QColor(self.button_warning_text)
            border_width = 1.5
        else:
            normal_bg = QColor(self.accent_color)
            hover_bg = self._darken_or_lighten_color(self.accent_color, 0.1)
            pressed_bg = self._darken_or_lighten_color(self.accent_color, 0.2)
            normal_border = QColor(self.accent_color)
            hover_border = QColor(self.accent_color)
            pressed_border = QColor(self.accent_color)
            text_color = QColor(self.base_color)
            border_width = 0.0

        if pressed:
            bg_color = pressed_bg
            border_color = pressed_border
        elif hovered:
            bg_color = hover_bg
            border_color = hover_border
        else:
            bg_color = normal_bg
            border_color = normal_border

        return {
            "bg": bg_color,
            "border": border_color,
            "text": text_color,
            "border_width": border_width,
        }

    def _draw_action_button(
        self,
        painter: QPainter,
        rect: QRect,
        action: str,
        hovered: bool,
        pressed: bool,
        opacity: float,
    ) -> None:
        if rect.width() <= 0 or rect.height() <= 0:
            return

        colors = self._button_colors(action, hovered, pressed)
        button_metrics = self._button_metrics(
            self._action_text(action),
            self._action_button_type(action),
        )
        border_width = float(colors["border_width"])
        body_rect = QRectF(rect).adjusted(
            border_width / 2.0,
            border_width / 2.0,
            -border_width / 2.0,
            -border_width / 2.0,
        )
        radius = min(float(button_metrics["radius"]), body_rect.height() / 2.0)

        painter.save()
        painter.setOpacity(opacity)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setFont(self.button_font)
        painter.setBrush(colors["bg"])
        if border_width > 0:
            painter.setPen(QPen(colors["border"], border_width))
        else:
            painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(body_rect, radius, radius)
        painter.setPen(colors["text"])
        painter.drawText(rect, Qt.AlignCenter | Qt.TextSingleLine, self._action_text(action))
        painter.restore()

    def paint_action_area(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index,
        hovered_action: str | None = None,
        pressed_action: str | None = None,
        opacity: float = 1.0,
        force_visible: bool = False,
        for_drag_preview: bool = False,
    ) -> None:
        if not force_visible and not self.should_show_action_area(
            option,
            index,
            for_drag_preview=for_drag_preview,
        ):
            return

        file_info = self._get_file_info(index)
        item_key = self._get_animation_key(file_info)
        if hovered_action is None:
            hovered_action = self._current_hovered_action(
                option,
                index,
                for_drag_preview=for_drag_preview,
            )
        if pressed_action is None and self._pressed_action_key and self._pressed_action_key[0] == item_key:
            pressed_action = self._pressed_action_key[1]

        for action, rect in self.get_action_rects(option, index).items():
            self._draw_action_button(
                painter,
                rect,
                action,
                hovered=hovered_action == action,
                pressed=pressed_action == action,
                opacity=opacity,
            )

    def _paint_texts(
        self,
        painter: QPainter,
        geometry: dict[str, Any],
        file_info: dict[str, Any],
        opacity: float,
    ) -> None:
        name_text, info_text = self._compose_texts(file_info)
        text_width = max(0, int(geometry.get("text_max_width", 0)))
        is_missing = bool(file_info.get("is_missing", False))

        painter.save()
        painter.setOpacity(opacity)

        name_font = QFont(self.name_font)
        if is_missing:
            name_font.setStrikeOut(True)
        painter.setFont(name_font)
        painter.setPen(self._missing_name_color if is_missing else self._text_color)
        painter.drawText(
            geometry["name_rect"],
            Qt.AlignLeft | Qt.AlignVCenter | Qt.TextSingleLine,
            self.name_font_metrics.elidedText(name_text, Qt.ElideRight, text_width),
        )

        if not self._single_line_mode and geometry["info_rect"].height() > 0:
            painter.setFont(self.info_font)
            painter.setPen(self._missing_info_color if is_missing else self._info_color)
            painter.drawText(
                geometry["info_rect"],
                Qt.AlignLeft | Qt.AlignVCenter | Qt.TextSingleLine,
                self.info_font_metrics.elidedText(info_text, Qt.ElideRight, text_width),
            )

        painter.restore()

    def _paint_card(self, painter, option, index, for_drag_preview: bool = False):
        view = option.widget
        if view and view is not self._view:
            self.set_view(view)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        rect = option.rect
        geometry = self._calculate_geometry(rect)
        file_info = self._get_file_info(index)

        is_selected = bool(file_info.get("is_selected", False))
        is_previewing = bool(file_info.get("is_previewing", False))
        is_hovered = (
            bool(option.state & QStyle.State_MouseOver)
            and not is_selected
            and not is_previewing
            and not for_drag_preview
        )

        anim_key = self._get_animation_key(file_info)
        anim_state = self._sync_animation_state(
            anim_key,
            file_info,
            is_hovered,
            is_selected,
            is_previewing,
        )

        file_path = self._normalize_path(file_info.get("path", ""))
        is_dragging_source = bool(
            self._dragging_file_path and file_path == self._dragging_file_path and not for_drag_preview
        )

        bg_color, border_color, border_width, content_opacity = self._get_paint_colors(
            geometry,
            is_selected,
            is_previewing,
            anim_state,
            is_dragging_source=is_dragging_source,
            for_drag_preview=for_drag_preview,
        )

        draw_rect = QRectF(rect).adjusted(
            border_width / 2.0,
            border_width / 2.0,
            -border_width / 2.0,
            -border_width / 2.0,
        )
        painter.setPen(QPen(border_color, border_width))
        painter.setBrush(bg_color)
        painter.drawRoundedRect(draw_rect, geometry["radius"], geometry["radius"])

        icon_pixmap = file_info.get("icon_pixmap")
        if icon_pixmap and not icon_pixmap.isNull():
            self._draw_scaled_pixmap(painter, geometry["icon_rect"], icon_pixmap, content_opacity)

        self._paint_texts(painter, geometry, file_info, content_opacity)
        self.paint_action_area(
            painter,
            option,
            index,
            opacity=content_opacity,
            for_drag_preview=for_drag_preview,
        )
        painter.restore()

    def sizeHint(self, option, index):
        model = index.model()
        if model:
            item_size = model.data(index, FileStagingPoolListModel.ItemSizeRole)
            if isinstance(item_size, QSize) and item_size.isValid():
                return item_size

        dpi_scale = self._dpi_scale
        return QSize(max(240, int(320 * dpi_scale)), max(52, int(64 * dpi_scale)))

    def _event_pos(self, event) -> QPoint:
        if hasattr(event, "position"):
            try:
                return event.position().toPoint()
            except (RuntimeError, TypeError, ValueError):
                pass
        if hasattr(event, "pos"):
            try:
                return event.pos()
            except (RuntimeError, TypeError, ValueError):
                pass
        return QPoint(-1, -1)

    def _update_widget_cursor(
        self,
        option: QStyleOptionViewItem,
        action: Optional[str],
    ) -> None:
        widget = option.widget
        if widget is None:
            return
        if action:
            widget.setCursor(Qt.PointingHandCursor)
        else:
            widget.unsetCursor()

    def _request_repaint(self, option: QStyleOptionViewItem) -> None:
        widget = option.widget
        if widget is None:
            return
        widget.update(option.rect)

    def editorEvent(self, event, model, option, index):
        if not index.isValid() or option.widget is None:
            return False

        event_type = event.type()
        file_info = self._get_file_info(index)
        item_key = self._get_animation_key(file_info)

        if event_type in (QEvent.MouseMove, QEvent.HoverMove):
            pos = self._event_pos(event)
            hovered_action = self.hit_test_action(option, index, pos)
            self._update_widget_cursor(option, hovered_action)
            if self._pressed_action_key and self._pressed_action_key[0] == item_key:
                self._request_repaint(option)
                return True
            if hovered_action:
                self._request_repaint(option)
            return False

        if event_type == QEvent.MouseButtonPress:
            if getattr(event, "button", lambda: None)() != Qt.LeftButton:
                return False
            pos = self._event_pos(event)
            action = self.hit_test_action(option, index, pos)
            if action is None:
                self._pressed_action_key = None
                return False
            self._pressed_action_key = (item_key, action)
            self._update_widget_cursor(option, action)
            self._request_repaint(option)
            return True

        if event_type == QEvent.MouseButtonRelease:
            if getattr(event, "button", lambda: None)() != Qt.LeftButton:
                return False
            pos = self._event_pos(event)
            action = self.hit_test_action(option, index, pos)
            pressed_action = self._pressed_action_key[1] if self._pressed_action_key and self._pressed_action_key[0] == item_key else None
            self._pressed_action_key = None
            self._update_widget_cursor(option, action)
            self._request_repaint(option)
            if action and action == pressed_action:
                file_path = str(file_info.get("path", "") or "")
                if action == self.ACTION_RENAME:
                    self.renameRequested.emit(file_path)
                elif action == self.ACTION_DELETE:
                    self.deleteRequested.emit(file_path)
                return True
            return pressed_action is not None

        if event_type in (QEvent.Leave, QEvent.HoverLeave):
            if self._pressed_action_key and self._pressed_action_key[0] == item_key:
                self._pressed_action_key = None
                self._request_repaint(option)
            self._update_widget_cursor(option, None)
            return False

        return False
