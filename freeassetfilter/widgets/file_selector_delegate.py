#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FileSelectorDelegate - 文件选择器列表视图的自定义委托

基于 FileBlockCard._paint_card() 的视觉与动画语义实现，
为 QListView 提供与 FileBlockCard 接近一致的卡片渲染效果。
"""

from datetime import datetime

from PySide6.QtCore import Qt, QSize, QRect, QRectF, QTimer
from PySide6.QtGui import QColor, QPen, QFont, QFontMetrics, QPixmap, QPainter
from PySide6.QtWidgets import QStyledItemDelegate, QApplication, QStyle, QStyleOptionViewItem

from freeassetfilter.core.settings_manager import SettingsManager
from freeassetfilter.utils.app_logger import debug


class FileBlockCardDelegate(QStyledItemDelegate):
    """
    文件块卡片委托

    特性：
    - 复现 FileBlockCard 的 hover / selected / preview 颜色与切换节奏
    - 动画状态以 file path 为 key，避免排序/筛选/刷新导致串状态
    - 动画定时器仅在存在活动动画时运行，空闲时自动停止
    """

    def __init__(self, dpi_scale=1.0, global_font=None, parent=None):
        super().__init__(parent)
        self._dpi_scale = dpi_scale
        self._global_font = global_font
        self._view = None
        self._animation_states = {}
        self._active_animation_keys = set()
        self._dragging_file_path = None

        self._animation_timer = QTimer(self)
        self._animation_timer.setInterval(16)
        self._animation_timer.timeout.connect(self._on_animation_tick)

        self._init_colors()
        self._init_fonts()

    def set_view(self, view):
        """设置关联的视图"""
        self._view = view
        if view:
            view.setMouseTracking(True)

    def clear_caches(self):
        """清理委托内部动画缓存"""
        self._animation_states.clear()
        self._active_animation_keys.clear()
        self._dragging_file_path = None
        self._stop_animation_timer_if_idle()
        if self._view:
            self._view.viewport().update()

    def update_theme(self):
        """主题更新后刷新颜色和字体缓存"""
        self._init_colors()
        self._init_fonts()
        self.clear_caches()

    def set_dragging_file_path(self, file_path):
        """设置当前处于拖拽中的文件路径"""
        import os

        normalized_path = os.path.normpath(file_path) if file_path else None
        if self._dragging_file_path == normalized_path:
            return

        self._dragging_file_path = normalized_path
        if self._view:
            self._view.viewport().update()

    def _init_colors(self):
        """初始化颜色配置"""
        try:
            app = QApplication.instance()
            settings_manager = getattr(app, "settings_manager", None) if app else None
            if settings_manager is None:
                settings_manager = SettingsManager()

            self.base_color = settings_manager.get_setting("appearance.colors.base_color", "#212121")
            self.auxiliary_color = settings_manager.get_setting("appearance.colors.auxiliary_color", "#3D3D3D")
            self.normal_color = settings_manager.get_setting("appearance.colors.normal_color", "#717171")
            self.accent_color = settings_manager.get_setting("appearance.colors.accent_color", "#B036EE")
            self.secondary_color = settings_manager.get_setting("appearance.colors.secondary_color", "#FFFFFF")
        except Exception as error:
            debug(f"初始化委托颜色配置失败，使用默认颜色: {error}")
            self.base_color = "#212121"
            self.auxiliary_color = "#3D3D3D"
            self.normal_color = "#717171"
            self.accent_color = "#B036EE"
            self.secondary_color = "#FFFFFF"

        self._normal_bg = QColor(self.base_color)
        self._hover_bg = QColor(self.auxiliary_color)
        self._selected_bg = QColor(self.accent_color)
        self._selected_bg.setAlpha(102)

        self._normal_border = QColor(self.auxiliary_color)
        self._hover_border = QColor(self.normal_color)
        self._selected_border = QColor(self.accent_color)
        self._preview_border = QColor(self.secondary_color)
        self._text_color = QColor(self.secondary_color)

    def _init_fonts(self):
        """初始化字体配置"""
        app = QApplication.instance()
        self.global_font = getattr(app, "global_font", self._global_font or QFont()) if app else (self._global_font or QFont())

        self.name_font = QFont(self.global_font)
        self.small_font = QFont(self.global_font)
        small_font_size = max(1, int(self.global_font.pointSize() * 0.85))
        self.small_font.setPointSize(small_font_size)

        self.name_font_metrics = QFontMetrics(self.name_font)
        self.small_font_metrics = QFontMetrics(self.small_font)

    def _normalize_path(self, file_path: str) -> str:
        import os

        return os.path.normpath(file_path) if file_path else ""

    def _format_created_text(self, created: str) -> str:
        if not created:
            return ""

        try:
            from PySide6.QtCore import QDateTime

            dt = QDateTime.fromString(created, Qt.ISODate)
            if dt.isValid():
                return dt.toString("yyyy-MM-dd")
        except (RuntimeError, TypeError, ValueError):
            pass

        return created[:10] if len(created) >= 10 else created

    def _format_file_size(self, size_bytes):
        if size_bytes < 0:
            size_bytes = 0
        if size_bytes < 1024:
            return f"{int(size_bytes)} B"
        if size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        if size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"

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
        dpi_scale = self._dpi_scale

        border_width = max(1, int(1 * dpi_scale))
        preview_border_width = border_width * 2
        radius = max(1, int(8 * dpi_scale))
        icon_size = int(38 * dpi_scale)
        spacing = int(2 * dpi_scale)
        margins = int(4 * dpi_scale)

        content_rect = rect.adjusted(margins, margins, -margins, -margins)

        icon_rect = QRect(
            content_rect.x() + max(0, (content_rect.width() - icon_size) // 2),
            content_rect.y(),
            min(icon_size, max(0, content_rect.width())),
            icon_size,
        )

        name_h = self.name_font_metrics.height()
        small_h = self.small_font_metrics.height()

        name_rect = QRect(
            content_rect.x(),
            icon_rect.bottom() + 1 + spacing,
            content_rect.width(),
            name_h,
        )
        size_rect = QRect(
            content_rect.x(),
            name_rect.bottom() + 1 + spacing,
            content_rect.width(),
            small_h,
        )
        time_rect = QRect(
            content_rect.x(),
            size_rect.bottom() + 1 + spacing,
            content_rect.width(),
            small_h,
        )

        return {
            "border_width": border_width,
            "preview_border_width": preview_border_width,
            "radius": radius,
            "icon_rect": icon_rect,
            "name_rect": name_rect,
            "size_rect": size_rect,
            "time_rect": time_rect,
        }

    def _default_anim_state(self):
        return {
            "bg_color": QColor(self._normal_bg),
            "border_color": QColor(self._normal_border),
            "is_hovered": False,
            "is_selected": False,
            "is_previewing": False,
            "animating": False,
            "animation_start_time": 0.0,
            "animation_duration": 0,
            "easing": "out_cubic",
            "start_bg": QColor(self._normal_bg),
            "start_border": QColor(self._normal_border),
            "target_bg": QColor(self._normal_bg),
            "target_border": QColor(self._normal_border),
        }

    def _get_animation_key(self, file_info):
        return self._normalize_path(file_info.get("path", "")) or f"rowless::{file_info.get('name', '')}"

    def _get_animation_state(self, key):
        if key not in self._animation_states:
            self._animation_states[key] = self._default_anim_state()
        return self._animation_states[key]

    def _ensure_animation_timer_running(self):
        if not self._active_animation_keys:
            return
        if not self._animation_timer.isActive():
            self._animation_timer.start()

    def _ease(self, curve_name: str, t: float) -> float:
        t = max(0.0, min(1.0, t))
        if curve_name == "in_out_quad":
            if t < 0.5:
                return 2 * t * t
            return 1 - pow(-2 * t + 2, 2) / 2
        return 1 - pow(1 - t, 3)

    def _interpolate_color(self, c1, c2, t):
        r = int(c1.red() + (c2.red() - c1.red()) * t)
        g = int(c1.green() + (c2.green() - c1.green()) * t)
        b = int(c1.blue() + (c2.blue() - c1.blue()) * t)
        a = int(c1.alpha() + (c2.alpha() - c1.alpha()) * t)
        return QColor(r, g, b, a)

    def _target_colors_for_flags(self, is_hovered: bool, is_selected: bool, is_previewing: bool):
        if is_previewing:
            target_bg = QColor(self._selected_bg) if is_selected else QColor(self._normal_bg)
            return target_bg, QColor(self._preview_border)

        if is_selected:
            return QColor(self._selected_bg), QColor(self._selected_border)

        if is_hovered:
            return QColor(self._hover_bg), QColor(self._hover_border)

        return QColor(self._normal_bg), QColor(self._normal_border)

    def _transition_meta(self, prev_hovered, prev_selected, prev_previewing, is_hovered, is_selected, is_previewing):
        if is_previewing and not prev_previewing:
            return 180, "out_cubic"
        if (not is_previewing) and prev_previewing:
            return 200, "in_out_quad"
        if is_selected and not prev_selected:
            return 180, "out_cubic"
        if (not is_selected) and prev_selected:
            return 200, "in_out_quad"
        if is_hovered and not prev_hovered:
            return 150, "out_cubic"
        if (not is_hovered) and prev_hovered:
            return 200, "in_out_quad"
        return 150, "out_cubic"

    def _sync_animation_state(self, key, file_info, is_hovered, is_selected, is_previewing):
        state = self._get_animation_state(key)

        prev_hovered = state["is_hovered"]
        prev_selected = state["is_selected"]
        prev_previewing = state["is_previewing"]

        target_bg, target_border = self._target_colors_for_flags(is_hovered, is_selected, is_previewing)

        needs_transition = (
            prev_hovered != is_hovered
            or prev_selected != is_selected
            or prev_previewing != is_previewing
        )

        state["is_hovered"] = is_hovered
        state["is_selected"] = is_selected
        state["is_previewing"] = is_previewing

        if not needs_transition:
            if not state["animating"]:
                state["bg_color"] = QColor(target_bg)
                state["border_color"] = QColor(target_border)
            return state

        duration, easing = self._transition_meta(
            prev_hovered,
            prev_selected,
            prev_previewing,
            is_hovered,
            is_selected,
            is_previewing,
        )

        state["start_bg"] = QColor(state["bg_color"])
        state["start_border"] = QColor(state["border_color"])
        state["target_bg"] = QColor(target_bg)
        state["target_border"] = QColor(target_border)
        state["animation_duration"] = duration
        state["easing"] = easing
        state["animation_start_time"] = datetime.now().timestamp() * 1000.0
        state["animating"] = True
        self._active_animation_keys.add(key)

        self._ensure_animation_timer_running()

        return state

    def _stop_animation_timer_if_idle(self):
        if self._active_animation_keys:
            self._ensure_animation_timer_running()
            return

        if self._animation_timer.isActive():
            self._animation_timer.stop()

    def _on_animation_tick(self):
        if not self._active_animation_keys:
            self._stop_animation_timer_if_idle()
            return

        now = datetime.now().timestamp() * 1000.0
        needs_repaint = False

        completed_keys = []

        for key in tuple(self._active_animation_keys):
            state = self._animation_states.get(key)
            if not state or not state.get("animating", False):
                completed_keys.append(key)
                continue

            elapsed = now - state["animation_start_time"]
            duration = max(1, int(state["animation_duration"]))

            if elapsed >= duration:
                state["bg_color"] = QColor(state["target_bg"])
                state["border_color"] = QColor(state["target_border"])
                state["animating"] = False
                completed_keys.append(key)
            else:
                progress = elapsed / duration
                eased = self._ease(state.get("easing", "out_cubic"), progress)
                state["bg_color"] = self._interpolate_color(state["start_bg"], state["target_bg"], eased)
                state["border_color"] = self._interpolate_color(state["start_border"], state["target_border"], eased)

            needs_repaint = True

        for key in completed_keys:
            self._active_animation_keys.discard(key)

        self._stop_animation_timer_if_idle()

        if needs_repaint and self._view:
            self._view.viewport().update()

    def _get_paint_colors(self, geometry, is_selected, is_previewing, anim_state, is_dragging_source=False, for_drag_preview=False):
        if is_dragging_source:
            bg_color = QColor(self.base_color)
            bg_color.setAlpha(102)

            border_color = QColor(self.auxiliary_color)
            border_color.setAlpha(102)

            return bg_color, border_color, geometry["border_width"], 0.4

        if for_drag_preview:
            return QColor(self.base_color), QColor(self.normal_color), geometry["border_width"], 1.0

        border_width = geometry["preview_border_width"] if is_previewing else geometry["border_width"]
        bg_color = QColor(anim_state["bg_color"])
        border_color = QColor(anim_state["border_color"])
        return bg_color, border_color, border_width, 1.0

    def _draw_scaled_pixmap(self, painter, rect, pixmap, opacity=1.0):
        if pixmap.isNull() or rect.width() <= 0 or rect.height() <= 0:
            return

        physical_width = max(1, pixmap.width())
        physical_height = max(1, pixmap.height())

        dpr = pixmap.devicePixelRatio()
        if dpr and dpr > 0:
            logical_width = max(1, int(round(physical_width / dpr)))
            logical_height = max(1, int(round(physical_height / dpr)))
        else:
            logical_width = physical_width
            logical_height = physical_height

        same_size = logical_width == rect.width() and logical_height == rect.height()

        if same_size:
            target_rect = QRectF(rect)
        else:
            target_size = QSize(logical_width, logical_height).scaled(rect.size(), Qt.KeepAspectRatio)
            target_rect = QRectF(
                rect.x() + (rect.width() - target_size.width()) / 2.0,
                rect.y() + (rect.height() - target_size.height()) / 2.0,
                float(target_size.width()),
                float(target_size.height()),
            )

        painter.save()
        painter.setOpacity(opacity)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, not same_size)
        painter.drawPixmap(
            target_rect,
            pixmap,
            QRectF(0.0, 0.0, float(physical_width), float(physical_height)),
        )
        painter.restore()

    def _resolve_card_rect(self, option, index, for_drag_preview=False):
        rect = QRect(option.rect)
        if for_drag_preview:
            return rect

        target_size = self.sizeHint(option, index)
        if not target_size.isValid():
            return rect

        target_width = min(rect.width(), target_size.width())
        target_height = min(rect.height(), target_size.height())

        offset_x = max(0, (rect.width() - target_width) // 2)
        offset_y = max(0, (rect.height() - target_height) // 2)

        return QRect(
            rect.x() + offset_x,
            rect.y() + offset_y,
            target_width,
            target_height,
        )

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
        anim_state = self._sync_animation_state(
            anim_key,
            file_info,
            is_hovered,
            is_selected,
            is_previewing,
        )

        file_path = self._normalize_path(file_info.get("path", ""))
        is_dragging_source = bool(self._dragging_file_path and file_path == self._dragging_file_path and not for_drag_preview)

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

        painter.setPen(self._text_color)
        painter.setOpacity(content_opacity)
        painter.setFont(self.name_font)

        name_text = file_info.get("name", "")
        elided_name = self.name_font_metrics.elidedText(
            name_text,
            Qt.ElideRight,
            geometry["name_rect"].width(),
        )
        painter.drawText(
            geometry["name_rect"],
            Qt.AlignCenter | Qt.TextSingleLine,
            elided_name,
        )

        painter.setFont(self.small_font)

        if file_info.get("is_dir", False):
            size_text = "文件夹"
        else:
            size_text = self._format_file_size(file_info.get("size", 0))
        painter.drawText(
            geometry["size_rect"],
            Qt.AlignCenter | Qt.TextSingleLine,
            size_text,
        )

        created_time = self._format_created_text(file_info.get("created", ""))
        painter.drawText(
            geometry["time_rect"],
            Qt.AlignCenter | Qt.TextSingleLine,
            created_time,
        )

        painter.restore()

    def paint(self, painter, option, index):
        self._paint_card(painter, option, index, for_drag_preview=False)

    def build_drag_pixmap(self, index, size, palette):
        option = QStyleOptionViewItem()
        if self._view:
            option.initFrom(self._view.viewport())
        option.rect = QRect(0, 0, size.width(), size.height())
        option.palette = palette
        option.state |= QStyle.State_Enabled

        pixmap = QPixmap(size)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        self._paint_card(painter, option, index, for_drag_preview=True)
        painter.end()
        return pixmap

    def sizeHint(self, option, index):
        dpi_scale = self._dpi_scale

        min_height = int(75 * dpi_scale)
        icon_size = int(38 * dpi_scale)
        name_font_height = self.name_font_metrics.height()
        small_font_height = self.small_font_metrics.height()

        labels_height = name_font_height + (small_font_height * 2)
        spacing = int(2 * dpi_scale)
        total_spacing = spacing * 3
        vertical_margins = int(4 * dpi_scale) * 2
        border_width = int(1 * dpi_scale) * 2

        required_height = icon_size + labels_height + total_spacing + vertical_margins + border_width
        height = max(required_height, min_height)

        model = index.model()
        card_width = model.data(index, Qt.UserRole + 10) if model else None
        if card_width and card_width > 0:
            width = card_width
        else:
            base_min_width = int(50 * dpi_scale)
            date_text_width = self.small_font_metrics.horizontalAdvance("2024-12-31")
            char_width = self.small_font_metrics.horizontalAdvance("W")
            horizontal_margins = int(4 * dpi_scale) * 2
            border_w = int(1 * dpi_scale) * 2
            required_width = date_text_width + char_width + horizontal_margins + border_w
            width = max(required_width, base_min_width)

        return QSize(width, height)
