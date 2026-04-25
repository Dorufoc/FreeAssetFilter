#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 按钮类自定义控件
包含各种按钮类UI组件，如自定义按钮等
"""

import os
import threading

from PySide6.QtCore import Qt, QRectF, QSize, QTimer, Property, QVariantAnimation, QEasingCurve, QEvent
from PySide6.QtGui import QColor, QPainter, QFont, QPen, QFontMetrics, QCursor
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QPushButton, QSizePolicy, QApplication

from freeassetfilter.core.svg_renderer import SvgRenderer
from freeassetfilter.utils.animation_settings import is_animation_enabled
from freeassetfilter.utils.app_logger import debug


class CustomButton(QPushButton):
    """
    自定义按钮组件
    特点：
    - 圆角设计
    - 悬停和点击效果
    - 支持强调色和次选色方案
    - 支持文字和图标两种显示模式
    - 使用高性能自绘与单动画实现，避免频繁 QSS 重算
    """

    _svg_cache = {}
    _svg_cache_lock = threading.Lock()

    @Property(float)
    def anim_progress(self):
        return self._anim_progress

    @anim_progress.setter
    def anim_progress(self, value):
        self._anim_progress = float(value)
        self.update()

    def __init__(
        self,
        text="Button",
        parent=None,
        button_type="primary",
        display_mode="text",
        height=20,
        tooltip_text="",
    ):
        """
        初始化自定义按钮

        Args:
            text (str): 按钮文本或SVG图标路径
            parent (QWidget): 父控件
            button_type (str): 按钮类型，可选值："primary"（强调色）、"secondary"（次选色）、"normal"（普通样式）、"warning"（警告样式）
            display_mode (str): 显示模式，可选值："text"（文字显示）、"icon"（图标显示）
            height (int): 按钮高度，默认为20px
            tooltip_text (str): 用于悬浮信息显示的不可见文本
        """
        parent_text = text if display_mode == "text" else tooltip_text
        super().__init__(parent_text, parent)

        self.button_type = button_type
        self._original_height = height
        self._display_mode = display_mode
        self._icon_path = text if self._display_mode == "icon" else None
        self._tooltip_text = tooltip_text

        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.PointingHandCursor)

        app = QApplication.instance()
        self.dpi_scale = getattr(app, "dpi_scale_factor", 1.0) if app else 1.0
        self._height = int(self._original_height * self.dpi_scale)

        self._animations_initialized = False
        self._anim_lock = threading.Lock()

        self._style_metrics = {}
        self._style_colors = {}
        self._disabled_colors = {}
        self._theme_signature = None

        self._state = "normal"
        self._current_colors = None
        self._start_colors = None
        self._target_colors = None
        self._anim_progress = 1.0

        self.global_font = QFont()
        self._button_font = QFont()
        base_font = getattr(app, "global_font", QFont()) if app else QFont()
        self.setFont(base_font)

        self._icon_renderer = None

        self._state_animation = QVariantAnimation(self)
        self._state_animation.setStartValue(0.0)
        self._state_animation.setEndValue(1.0)
        self._state_animation.valueChanged.connect(self._on_anim_value_changed)
        self._state_animation.finished.connect(self._on_anim_finished)

        self.update_style()

        QTimer.singleShot(0, self._init_animations)
        if self._display_mode == "icon":
            QTimer.singleShot(0, lambda: self._render_icon(force=False))

    @classmethod
    def _get_cached_svg_renderer(cls, icon_path, button_type, theme_signature):
        cache_key = (icon_path, button_type, theme_signature)
        with cls._svg_cache_lock:
            return cls._svg_cache.get(cache_key)

    @classmethod
    def _set_cached_svg_renderer(cls, icon_path, button_type, theme_signature, renderer):
        cache_key = (icon_path, button_type, theme_signature)
        with cls._svg_cache_lock:
            cls._svg_cache[cache_key] = renderer

    def setFont(self, font):
        """
        保留原本按钮字重效果。
        原实现依赖样式表中的 font-weight: 600；
        自绘后改为显式维护按钮绘制字体。
        """
        effective_font = QFont(font) if font is not None else QFont()
        self.global_font = QFont(effective_font)

        self._button_font = QFont(effective_font)
        self._button_font.setWeight(QFont.DemiBold)

        super().setFont(self._button_font)

        if hasattr(self, "_display_mode") and self._display_mode == "text":
            if hasattr(self, "_style_metrics") and self._style_metrics:
                self._update_minimum_width_for_text()
            if hasattr(self, "_height"):
                self._height = self._calculate_optimal_height()
                self.setFixedHeight(self._height)
            self.update()

    def _get_text_metrics(self):
        return QFontMetrics(self._button_font)

    def _copy_color_map(self, color_map):
        return {key: QColor(value) for key, value in color_map.items()}

    def _on_anim_value_changed(self, value):
        self.anim_progress = float(value)

    def _on_anim_finished(self):
        if self._target_colors is not None:
            self._current_colors = self._copy_color_map(self._target_colors)
            self._start_colors = self._copy_color_map(self._target_colors)
            self._target_colors = self._copy_color_map(self._target_colors)
        self._anim_progress = 1.0
        self.update()
        QTimer.singleShot(0, self._sync_visual_state)

    def _get_interpolated_colors(self):
        if not self._start_colors or not self._target_colors:
            return self._copy_color_map(self._current_colors or self._style_colors["normal"])

        progress = max(0.0, min(1.0, self._anim_progress))
        result = {}
        for key in self._target_colors:
            start = self._start_colors[key]
            end = self._target_colors[key]
            result[key] = QColor(
                int(start.red() + (end.red() - start.red()) * progress),
                int(start.green() + (end.green() - start.green()) * progress),
                int(start.blue() + (end.blue() - start.blue()) * progress),
                int(start.alpha() + (end.alpha() - start.alpha()) * progress),
            )
        return result

    def _init_animations(self):
        """初始化动画状态"""
        with self._anim_lock:
            if self._animations_initialized:
                return
            self._animations_initialized = True

        normal_colors = self._style_colors.get("normal", {})
        self._current_colors = self._copy_color_map(normal_colors)
        self._start_colors = self._copy_color_map(normal_colors)
        self._target_colors = self._copy_color_map(normal_colors)
        self._anim_progress = 1.0
        self.update()

    def _is_cursor_inside(self):
        if not self.isVisible():
            return False

        if self.underMouse():
            return True

        try:
            global_pos = QCursor.pos()
            local_pos = self.mapFromGlobal(global_pos)
            return self.rect().contains(local_pos)
        except RuntimeError:
            return False

    def _has_blocking_popup(self):
        active_popup = QApplication.activePopupWidget()
        if active_popup is not None and active_popup is not self and not self.isAncestorOf(active_popup):
            return True

        active_modal = QApplication.activeModalWidget()
        if active_modal is not None and active_modal is not self and not self.isAncestorOf(active_modal):
            return True

        return False

    def _sync_visual_state(self, animated=True):
        if not self.isEnabled():
            self._set_visual_state("normal", animated=False)
            return

        if self.isHidden() or self._has_blocking_popup():
            self._set_visual_state("normal", animated=animated)
            return

        is_cursor_inside = self._is_cursor_inside()
        if self.isDown() and is_cursor_inside:
            self._set_visual_state("pressed", animated=animated)
        elif is_cursor_inside:
            self._set_visual_state("hover", animated=animated)
        else:
            self._set_visual_state("normal", animated=animated)

    def _set_visual_state(self, state, animated=True, force=False):
        if state not in self._style_colors:
            state = "normal"

        target = self._style_colors[state]

        if (
            not force
            and state == self._state
            and self._target_colors is not None
            and self._current_colors is not None
            and self._state_animation.state() != QVariantAnimation.Running
        ):
            return

        self._state = state

        if not self._animations_initialized or not animated or not self._is_button_animation_enabled():
            self._state_animation.stop()
            self._current_colors = self._copy_color_map(target)
            self._start_colors = self._copy_color_map(target)
            self._target_colors = self._copy_color_map(target)
            self._anim_progress = 1.0
            self.update()
            return

        current_visual = self._get_interpolated_colors()
        self._current_colors = self._copy_color_map(current_visual)
        self._start_colors = self._copy_color_map(current_visual)
        self._target_colors = self._copy_color_map(target)
        self._anim_progress = 0.0

        duration = 150
        easing = QEasingCurve.OutCubic
        if state == "pressed":
            duration = 80
            easing = QEasingCurve.OutQuad
        elif state == "normal":
            duration = 180
            easing = QEasingCurve.InOutQuad
        elif state == "hover":
            duration = 140
            easing = QEasingCurve.OutCubic

        self._state_animation.stop()
        self._state_animation.setDuration(duration)
        self._state_animation.setEasingCurve(easing)
        self._state_animation.setStartValue(0.0)
        self._state_animation.setEndValue(1.0)
        self._state_animation.start()

    def _get_settings_manager(self):
        app = QApplication.instance()
        if app and hasattr(app, "settings_manager"):
            return app.settings_manager
        from freeassetfilter.core.settings_manager import SettingsManager
        return SettingsManager()

    def _is_button_animation_enabled(self):
        return is_animation_enabled(
            "button_smoothing",
            default=True,
            settings_manager=self._get_settings_manager(),
        )

    def _darken_or_lighten_color(self, color_value, percentage, settings_manager):
        color = QColor(color_value)
        current_theme = settings_manager.get_setting("appearance.theme", "default")
        is_dark_mode = current_theme == "dark"

        if is_dark_mode:
            luminance = (
                0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
            ) / 255
            if luminance < 0.1:
                adjusted_percentage = min(percentage * 2.5, 0.4)
            elif luminance < 0.3:
                adjusted_percentage = min(percentage * 1.8, 0.35)
            else:
                adjusted_percentage = percentage

            r = min(255, int(color.red() + (255 - color.red()) * adjusted_percentage))
            g = min(255, int(color.green() + (255 - color.green()) * adjusted_percentage))
            b = min(255, int(color.blue() + (255 - color.blue()) * adjusted_percentage))
        else:
            r = max(0, int(color.red() * (1 - percentage)))
            g = max(0, int(color.green() * (1 - percentage)))
            b = max(0, int(color.blue() * (1 - percentage)))

        return QColor(r, g, b)

    def _build_theme_colors(self):
        settings_manager = self._get_settings_manager()
        current_colors = settings_manager.get_setting("appearance.colors", {})
        current_theme = settings_manager.get_setting("appearance.theme", "default")

        accent_color = current_colors.get("accent_color", "#007AFF")
        secondary_color = current_colors.get("secondary_color", "#333333")
        normal_color = current_colors.get("normal_color", "#e0e0e0")
        auxiliary_color = current_colors.get("auxiliary_color", "#f1f3f5")
        base_color = current_colors.get("base_color", "#ffffff")
        warning_color = current_colors.get("notification_error", "#F44336")
        notification_text = current_colors.get("notification_text", "#FFFFFF")

        transparent = QColor(0, 0, 0, 0)
        icon_text = transparent if self._display_mode == "icon" else None

        if self.button_type == "primary":
            normal_bg = QColor(accent_color)
            hover_bg = self._darken_or_lighten_color(accent_color, 0.1, settings_manager)
            pressed_bg = self._darken_or_lighten_color(accent_color, 0.2, settings_manager)
            normal_border = QColor(accent_color)
            hover_border = QColor(accent_color)
            pressed_border = QColor(accent_color)
            normal_text = icon_text or QColor(base_color)
            hover_text = icon_text or QColor(base_color)
            pressed_text = icon_text or QColor(base_color)
            disabled_bg = QColor("#888888")
            disabled_text = transparent if self._display_mode == "icon" else QColor("#FFFFFF")
            disabled_border = QColor("#666666")
        elif self.button_type == "normal":
            normal_bg = QColor(base_color)
            hover_bg = self._darken_or_lighten_color(base_color, 0.1, settings_manager)
            pressed_bg = self._darken_or_lighten_color(base_color, 0.2, settings_manager)
            normal_border = QColor(base_color)
            hover_border = QColor(base_color)
            pressed_border = QColor(base_color)
            normal_text = icon_text or QColor(secondary_color)
            hover_text = icon_text or QColor(secondary_color)
            pressed_text = icon_text or QColor(secondary_color)
            disabled_bg = QColor("#2D2D2D")
            disabled_text = transparent if self._display_mode == "icon" else QColor("#666666")
            disabled_border = QColor("#444444")
        elif self.button_type == "warning":
            normal_bg = QColor(warning_color)
            hover_bg = self._darken_or_lighten_color(warning_color, 0.1, settings_manager)
            pressed_bg = self._darken_or_lighten_color(warning_color, 0.2, settings_manager)
            normal_border = QColor(warning_color)
            hover_border = self._darken_or_lighten_color(warning_color, 0.1, settings_manager)
            pressed_border = self._darken_or_lighten_color(warning_color, 0.2, settings_manager)
            normal_text = icon_text or QColor(current_colors.get("button_warning_text", notification_text))
            hover_text = QColor(normal_text)
            pressed_text = QColor(normal_text)
            disabled_bg = QColor("#FF8A80")
            disabled_text = transparent if self._display_mode == "icon" else QColor("#FFFFFF")
            disabled_border = QColor("#FF5252")
        else:  # secondary
            normal_bg = QColor(base_color)
            hover_bg = self._darken_or_lighten_color(base_color, 0.1, settings_manager)
            pressed_bg = self._darken_or_lighten_color(base_color, 0.2, settings_manager)
            normal_border = QColor(accent_color)
            hover_border = QColor(accent_color)
            pressed_border = QColor(accent_color)
            normal_text = icon_text or QColor(accent_color)
            hover_text = icon_text or QColor(accent_color)
            pressed_text = icon_text or QColor(accent_color)
            disabled_bg = QColor("#2D2D2D")
            disabled_text = transparent if self._display_mode == "icon" else QColor("#666666")
            disabled_border = QColor("#444444")

        theme_signature = (
            current_theme,
            accent_color,
            secondary_color,
            normal_color,
            auxiliary_color,
            base_color,
            warning_color,
            notification_text,
            self.button_type,
            self._display_mode,
        )

        state_colors = {
            "normal": {"bg": normal_bg, "border": normal_border, "text": normal_text},
            "hover": {"bg": hover_bg, "border": hover_border, "text": hover_text},
            "pressed": {"bg": pressed_bg, "border": pressed_border, "text": pressed_text},
        }

        disabled_colors = {
            "bg": disabled_bg,
            "border": disabled_border,
            "text": disabled_text,
        }

        return theme_signature, state_colors, disabled_colors

    def _get_border_width(self):
        if self.button_type in ("primary", "normal"):
            return 0.0
        return 1.5

    def _calculate_optimal_height(self):
        min_height = int(self._original_height * self.dpi_scale)
        text_height = self._get_text_metrics().height()
        vertical_padding = int(4 * self.dpi_scale) * 2
        border_width = self._get_border_width() * 2
        required_height = int(text_height + vertical_padding + border_width)
        return max(required_height, min_height)

    def _update_minimum_width_for_text(self):
        if self._display_mode == "icon":
            return

        text = self.text()
        if not text:
            return

        text_width = self._get_text_metrics().horizontalAdvance(text)
        horizontal_padding = self._style_metrics["padding_x"]
        border_width = self._style_metrics["border_width"]
        safety_margin = int(4 * self.dpi_scale)

        min_width = text_width + (horizontal_padding * 2) + (border_width * 2) + safety_margin
        absolute_min = int(25 * self.dpi_scale)
        self.setMinimumWidth(max(int(min_width), absolute_min))

    def _render_icon(self, force=False):
        try:
            if not self._icon_path or not os.path.exists(self._icon_path):
                self._icon_renderer = None
                return

            cached_renderer = None if force else self._get_cached_svg_renderer(
                self._icon_path,
                self.button_type,
                self._theme_signature,
            )
            if cached_renderer is not None and cached_renderer.isValid():
                self._icon_renderer = cached_renderer
                return

            with open(self._icon_path, "r", encoding="utf-8") as f:
                svg_content = f.read()

            svg_content = SvgRenderer._replace_svg_colors(
                svg_content,
                force_black_to_base=(self.button_type == "primary"),
            )

            renderer = QSvgRenderer(svg_content.encode("utf-8"))
            if not renderer.isValid():
                self._icon_renderer = None
                return

            self._set_cached_svg_renderer(
                self._icon_path,
                self.button_type,
                self._theme_signature,
                renderer,
            )
            self._icon_renderer = renderer
        except (OSError, ValueError, TypeError) as e:
            debug(f"渲染SVG图标失败: {e}")
            self._icon_renderer = None

    def update_style(self):
        """
        更新按钮样式与缓存
        """
        app = QApplication.instance()
        self.dpi_scale = getattr(app, "dpi_scale_factor", 1.0) if app else 1.0

        base_font = getattr(app, "global_font", QFont()) if app else QFont()
        self.setFont(base_font)

        self._height = self._calculate_optimal_height()
        self.setFixedHeight(self._height)

        self._style_metrics = {
            "border_radius": self._height / 2.0,
            "padding_y": int(4 * self.dpi_scale),
            "padding_x": int(6 * self.dpi_scale),
            "border_width": self._get_border_width(),
            "icon_ratio": 0.52,
        }

        theme_signature, state_colors, disabled_colors = self._build_theme_colors()
        theme_changed = theme_signature != self._theme_signature
        self._theme_signature = theme_signature
        self._style_colors = state_colors
        self._disabled_colors = disabled_colors

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        if self._display_mode == "icon":
            self.setFixedWidth(self._height)
        else:
            self.setMinimumWidth(int(25 * self.dpi_scale))
            self.setMaximumWidth(16777215)
            self.adjustSize()
            self._update_minimum_width_for_text()

        if theme_changed and self._display_mode == "icon":
            self._render_icon(force=False)

        if not self._animations_initialized:
            self._current_colors = self._copy_color_map(self._style_colors["normal"])
            self._start_colors = self._copy_color_map(self._style_colors["normal"])
            self._target_colors = self._copy_color_map(self._style_colors["normal"])
            self._anim_progress = 1.0
        else:
            self._set_visual_state("normal", animated=False, force=theme_changed)

        self.update()

    def update_theme(self):
        """
        统一主题刷新入口
        - 重新读取主题色
        - 重新应用按钮样式
        - 重新渲染 SVG 图标
        """
        try:
            old_signature = self._theme_signature
            self.update_style()

            if self._display_mode == "icon" and self._theme_signature != old_signature:
                self._render_icon(force=False)

            self.update()
        except Exception as e:
            debug(f"CustomButton.update_theme 刷新失败: {e}")

    def set_primary(self, is_primary):
        """
        设置按钮是否使用强调色（兼容旧接口）
        """
        self.button_type = "primary" if is_primary else "secondary"
        if self._display_mode == "icon":
            self._icon_renderer = None
        self.update_theme()
        self.resizeEvent(None)

    def set_button_type(self, button_type):
        """
        设置按钮类型

        Args:
            button_type (str): 按钮类型，可选值："primary"、"secondary"、"normal"、"warning"
        """
        self.button_type = button_type
        if self._display_mode == "icon":
            self._icon_renderer = None
        self.update_theme()
        self.resizeEvent(None)

    def setText(self, text):
        """
        重写setText方法，在设置文本后自动更新最小宽度和高度
        """
        super().setText(text)
        if self._display_mode == "text":
            self._update_minimum_width_for_text()
            new_height = self._calculate_optimal_height()
            if new_height != self._height:
                self._height = new_height
                self.setFixedHeight(self._height)
            self.update()

    def enterEvent(self, event):
        if self.isEnabled():
            self._set_visual_state("hover", animated=True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self.isEnabled():
            self._set_visual_state("normal", animated=True)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if self.isEnabled() and event.button() == Qt.LeftButton:
            self._set_visual_state("pressed", animated=True)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if not self.isEnabled():
            return

        self._sync_visual_state(animated=True)

    def resizeEvent(self, event):
        if event is not None:
            super().resizeEvent(event)

        app = QApplication.instance()
        new_dpi_scale = getattr(app, "dpi_scale_factor", 1.0) if app else 1.0
        if new_dpi_scale != self.dpi_scale:
            self.update_style()

        if self._display_mode == "icon":
            self._render_icon(force=False)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.EnabledChange:
            QTimer.singleShot(0, self._sync_visual_state)
        elif event.type() == QEvent.ActivationChange:
            window = self.window()
            if window is not None and not window.isActiveWindow():
                self._set_visual_state("normal", animated=False)
        elif event.type() == QEvent.WindowStateChange and self.isHidden():
            self._set_visual_state("normal", animated=False)

    def hideEvent(self, event):
        self._set_visual_state("normal", animated=False)
        super().hideEvent(event)

    def keyPressEvent(self, event):
        """
        禁用按钮的键盘响应，避免捕获方向键和空格键
        """
        event.ignore()

    def sizeHint(self):
        if self._display_mode == "icon":
            return QSize(self._height, self._height)

        text = self.text() or ""
        metrics = self._get_text_metrics()
        width = (
            metrics.horizontalAdvance(text)
            + self._style_metrics.get("padding_x", 6) * 2
            + int(self._style_metrics.get("border_width", 2) * 2)
            + int(4 * self.dpi_scale)
        )
        width = max(width, int(25 * self.dpi_scale))
        return QSize(int(width), int(self._height))

    def minimumSizeHint(self):
        return self.sizeHint()

    def _draw_background(self, painter, colors):
        border_width = self._style_metrics["border_width"]

        body_rect = QRectF(self.rect()).adjusted(
            border_width / 2.0,
            border_width / 2.0,
            -border_width / 2.0,
            -border_width / 2.0,
        )

        radius = min(self._style_metrics["border_radius"], body_rect.height() / 2.0)

        painter.setBrush(colors["bg"])
        if border_width > 0:
            painter.setPen(QPen(colors["border"], border_width))
        else:
            painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(body_rect, radius, radius)

        return body_rect

    def _draw_text(self, painter, body_rect, colors):
        text = self.text()
        if not text:
            return

        text_rect = QRectF(body_rect).adjusted(
            self._style_metrics["padding_x"],
            self._style_metrics["padding_y"],
            -self._style_metrics["padding_x"],
            -self._style_metrics["padding_y"],
        )

        painter.setPen(colors["text"])
        painter.setFont(self._button_font)
        painter.drawText(text_rect, Qt.AlignCenter, text)

    def _draw_icon(self, painter, body_rect):
        if not self._icon_renderer or not self._icon_renderer.isValid():
            return

        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, False)

        dpr = self.devicePixelRatioF() if hasattr(self, "devicePixelRatioF") else 1.0
        button_size = min(body_rect.width(), body_rect.height())
        desired_icon_size = max(1.0, button_size * self._style_metrics["icon_ratio"])

        svg_size = self._icon_renderer.defaultSize()
        if svg_size.width() > 0 and svg_size.height() > 0:
            aspect_ratio = svg_size.width() / svg_size.height()
            if aspect_ratio >= 1:
                desired_icon_width = desired_icon_size
                desired_icon_height = max(1.0, desired_icon_size / aspect_ratio)
            else:
                desired_icon_height = desired_icon_size
                desired_icon_width = max(1.0, desired_icon_size * aspect_ratio)
        else:
            desired_icon_width = desired_icon_size
            desired_icon_height = desired_icon_size

        icon_width_px = max(1, round(desired_icon_width * dpr))
        icon_height_px = max(1, round(desired_icon_height * dpr))
        icon_width = icon_width_px / dpr
        icon_height = icon_height_px / dpr

        x_px = round((body_rect.center().x() - icon_width / 2) * dpr)
        y_px = round((body_rect.center().y() - icon_height / 2) * dpr)
        x = x_px / dpr
        y = y_px / dpr

        target_rect = QRectF(x, y, icon_width, icon_height)
        self._icon_renderer.render(painter, target_rect)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        if self.isEnabled():
            colors = self._get_interpolated_colors()
        else:
            colors = self._copy_color_map(self._disabled_colors)

        body_rect = self._draw_background(painter, colors)

        if self._display_mode == "icon":
            self._draw_icon(painter, body_rect)
        else:
            self._draw_text(painter, body_rect, colors)

        painter.end()
