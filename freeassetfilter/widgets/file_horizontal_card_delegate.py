#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FileHorizontalCardDelegate - 文件选择器列表视图的横向卡片委托

以 Windows 文件资源管理器详细信息视图为参照，
单列显示，文件名左对齐，文件类型/日期/大小右对齐。
"""

from PySide6.QtCore import Qt, QSize, QRect, QRectF
from PySide6.QtGui import QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QApplication, QStyle

from freeassetfilter.widgets.base_card_delegate import BaseCardDelegate
from .file_selector_delegate import _get_file_type_display, _format_file_size_compact


class FileHorizontalCardDelegate(BaseCardDelegate):

    def _init_fonts(self):
        app = QApplication.instance()
        self.global_font = getattr(app, "global_font", self._global_font or QFont()) if app else (self._global_font or QFont())

        self.name_font = QFont(self.global_font)
        name_font_size = max(1, int(self.global_font.pointSize() * 1.1))
        self.name_font.setPointSize(name_font_size)
        self.name_font.setBold(True)
        self.small_font = QFont(self.global_font)
        small_font_size = max(1, int(self.global_font.pointSize() * 0.85))
        self.small_font.setPointSize(small_font_size)

        self.name_font_metrics = QFontMetrics(self.name_font)
        self.small_font_metrics = QFontMetrics(self.small_font)

    def _get_file_info(self, index):
        model = index.model()
        if not model:
            return {}
        return {
            "path": model.data(index, Qt.UserRole + 1) or "",
            "name": model.data(index, Qt.UserRole + 2) or "",
            "is_dir": model.data(index, Qt.UserRole + 3) or False,
            "size": model.data(index, Qt.UserRole + 4) or 0,
            "created": model.data(index, Qt.UserRole + 5) or "",
            "suffix": (model.data(index, Qt.UserRole + 6) or "").lower(),
            "is_selected": model.data(index, Qt.UserRole + 7) or False,
            "is_previewing": model.data(index, Qt.UserRole + 8) or False,
            "icon_pixmap": model.data(index, Qt.UserRole + 9),
        }

    def _calculate_geometry(self, rect):
        dpi = self._dpi_scale

        border_width = max(1, int(1 * dpi))
        preview_border_width = border_width * 2
        radius = max(1, int(8 * dpi))

        icon_size = int(28 * dpi)
        icon_left_margin = int(4 * dpi)
        icon_text_spacing = int(8 * dpi)

        right_margin = int(4 * dpi)
        inner_spacing = int(6 * dpi)

        content_rect = rect.adjusted(border_width, border_width, -border_width, -border_width)
        content_top = content_rect.y() + (content_rect.height() - icon_size) // 2

        icon_rect = QRect(
            content_rect.x() + icon_left_margin,
            content_top,
            icon_size,
            icon_size,
        )

        name_h = self.name_font_metrics.height()
        small_h = self.small_font_metrics.height()

        right_group_base_x = content_rect.right() - right_margin

        return {
            "border_width": border_width,
            "preview_border_width": preview_border_width,
            "radius": radius,
            "icon_rect": icon_rect,
            "content_rect": content_rect,
            "right_group_base_x": right_group_base_x,
            "inner_spacing": inner_spacing,
            "icon_text_spacing": icon_text_spacing,
            "right_margin": right_margin,
            "name_font_height": name_h,
            "small_font_height": small_h,
        }

    def _calculate_right_item_rects(self, geometry, type_text, size_text, date_text):
        type_width = self.small_font_metrics.horizontalAdvance(type_text) if type_text else 0
        date_width = self.small_font_metrics.horizontalAdvance(date_text) if date_text else 0
        size_width = self.small_font_metrics.horizontalAdvance(size_text) if size_text else 0

        spacing = geometry["inner_spacing"]
        right_base = geometry["right_group_base_x"]

        size_rect = QRect(right_base - size_width, 0, size_width, 0)
        date_rect = QRect(size_rect.x() - spacing - date_width, 0, date_width, 0)
        type_rect = QRect(date_rect.x() - spacing - type_width, 0, type_width, 0)

        icon_right_plus_margin = geometry["icon_rect"].right() + geometry["icon_text_spacing"]
        name_max_width = max(30, geometry["right_group_base_x"] - icon_right_plus_margin)

        return {
            "type_rect": type_rect,
            "date_rect": date_rect,
            "size_rect": size_rect,
            "name_max_width": name_max_width,
        }

    def _paint_card(self, painter, option, index, for_drag_preview=False):
        view = option.widget
        if view and view is not self._view:
            self.set_view(view)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        rect = self._resolve_card_rect(option, index, for_drag_preview=for_drag_preview)
        geometry = self._calculate_geometry(rect)
        file_info = self._get_file_info(index)

        is_selected = file_info.get("is_selected", False)
        is_previewing = file_info.get("is_previewing", False)
        is_hovered = bool(option.state & QStyle.State_MouseOver) and not is_selected and not is_previewing and not for_drag_preview

        anim_key = self._get_animation_key(file_info)
        anim_state = self._sync_animation_state(anim_key, file_info, is_hovered, is_selected, is_previewing)

        file_path = self._normalize_path(file_info.get("path", ""))
        is_dragging_source = bool(self._dragging_file_path and file_path == self._dragging_file_path and not for_drag_preview)

        bg_color, border_color, shadow_color, shadow_blur, border_width, content_opacity = self._get_paint_colors(
            geometry, is_selected, is_previewing, anim_state,
            is_dragging_source=is_dragging_source, for_drag_preview=for_drag_preview,
        )

        self._draw_shadow(painter, rect, geometry["radius"], shadow_color, shadow_blur)

        draw_rect = QRectF(rect).adjusted(
            border_width / 2.0, border_width / 2.0,
            -border_width / 2.0, -border_width / 2.0,
        )
        painter.setPen(QPen(border_color, border_width))
        painter.setBrush(bg_color)
        painter.drawRoundedRect(draw_rect, geometry["radius"], geometry["radius"])

        icon_pixmap = file_info.get("icon_pixmap")
        if icon_pixmap and not icon_pixmap.isNull():
            self._draw_scaled_pixmap(painter, geometry["icon_rect"], icon_pixmap, content_opacity)

        painter.setOpacity(content_opacity)

        is_dir = file_info.get("is_dir", False)
        type_text = _get_file_type_display(file_info.get("suffix", ""), is_dir)
        if is_dir:
            size_text = ""
        else:
            size_text = _format_file_size_compact(file_info.get("size", 0))
        date_text = self._format_created_text(file_info.get("created", ""))

        right_items = self._calculate_right_item_rects(geometry, type_text, size_text, date_text)

        icon_right = geometry["icon_rect"].right()
        text_x_start = icon_right + int(8 * self._dpi_scale)

        ct = geometry["content_rect"]
        name_h = geometry["name_font_height"]
        small_h = geometry["small_font_height"]

        name_y = ct.y() + int(4 * self._dpi_scale)
        info_y = ct.bottom() - small_h - int(4 * self._dpi_scale)

        painter.setPen(self._text_color)
        painter.setFont(self.name_font)
        name_text = file_info.get("name", "")
        elided_name = self.name_font_metrics.elidedText(name_text, Qt.ElideRight, right_items["name_max_width"])
        painter.drawText(
            text_x_start, name_y,
            right_items["name_max_width"], name_h,
            Qt.AlignLeft | Qt.AlignVCenter | Qt.TextSingleLine,
            elided_name,
        )

        painter.setFont(self.small_font)
        painter.setPen(self._text_color)

        def draw_right_rect(rect_item, text, y):
            if not text or rect_item is None:
                return
            r = rect_item
            painter.drawText(
                r.x(), y, r.width(), small_h,
                Qt.AlignRight | Qt.AlignVCenter | Qt.TextSingleLine,
                text,
            )

        draw_right_rect(right_items["size_rect"], size_text, info_y)
        draw_right_rect(right_items["date_rect"], date_text, info_y)
        draw_right_rect(right_items["type_rect"], type_text, info_y)

        painter.restore()

    def _resolve_card_rect(self, option, index, for_drag_preview=False):
        rect = QRect(option.rect)
        if for_drag_preview:
            return rect
        target_size = self.sizeHint(option, index)
        if not target_size.isValid():
            return rect

        if self._view and hasattr(self._view, 'viewport'):
            container_width = self._view.viewport().width()
        else:
            container_width = rect.width()

        target_width = min(container_width, target_size.width())
        target_height = min(rect.height(), target_size.height())
        offset_x = max(0, (container_width - target_width) // 2)
        offset_y = max(0, (rect.height() - target_height) // 2)
        return QRect(
            rect.x() + offset_x,
            rect.y() + offset_y,
            target_width,
            target_height,
        )

    def sizeHint(self, option, index):
        dpi = self._dpi_scale
        border_width = max(1, int(1 * dpi))
        icon_left_margin = int(4 * dpi)
        icon_size = int(28 * dpi)
        height = int(2 * border_width + 2 * icon_left_margin + icon_size)
        model = index.model()
        card_width = model.data(index, Qt.UserRole + 10) if model else None
        if card_width and card_width > 0:
            width = card_width
        else:
            width = max(int(200 * dpi), int(150 * dpi))
        return QSize(width, height)
