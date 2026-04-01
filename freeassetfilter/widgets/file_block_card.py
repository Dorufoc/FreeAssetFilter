#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

文件块卡片组件
高性能可伸缩文件卡片控件，支持多种交互状态和文件信息展示
支持长按拖拽功能
"""

import os

from PySide6.QtWidgets import QWidget, QSizePolicy, QApplication, QLabel
from PySide6.QtCore import (
    Qt,
    Signal,
    QEvent,
    QSize,
    QPropertyAnimation,
    Property,
    QEasingCurve,
    QParallelAnimationGroup,
    QTimer,
    QRect,
    QRectF,
)
from PySide6.QtGui import (
    QFont,
    QFontMetrics,
    QPixmap,
    QColor,
    QPainter,
    QCursor,
    QPen,
    QFontDatabase,
    QPalette,
)

from freeassetfilter.core.svg_renderer import SvgRenderer
from freeassetfilter.core.settings_manager import SettingsManager
from freeassetfilter.utils.file_icon_helper import get_file_icon_path
from freeassetfilter.utils.app_logger import debug, error
from freeassetfilter.core.thumbnail_manager import get_existing_thumbnail_path, get_thumbnail_manager


class FileBlockCard(QWidget):
    """
    高性能文件块卡片组件

    特性：
    - 最小横向宽度35，最大50（支持DPI缩放）
    - 圆角和边框设计
    - 四种状态：未选中态、hover态、选中态、预览态
    - 选中态不响应hover效果
    - 预览态边框使用secondary_color，宽度为选中态的2倍
    - 支持左键点击、右键点击、左键双击
    - 支持非线性动画过渡效果
    - 支持长按拖拽功能，拖拽到存储池选中文件，拖拽到预览器预览文件
    - 全自绘高性能实现，适合大量实例同时显示

    信号：
    - clicked: 点击信号，传递file_info
    - right_clicked: 右键点击信号，传递file_info
    - double_clicked: 双击信号，传递file_info
    - selection_changed: 选中状态变化信号，传递(file_info, is_selected)
    - preview_state_changed: 预览状态变化信号，传递(file_info, is_previewing)
    - drag_started: 拖拽开始信号，传递file_info
    - drag_ended: 拖拽结束信号，传递(file_info, drop_target_type)
    """

    clicked = Signal(dict)
    right_clicked = Signal(dict)
    double_clicked = Signal(dict)
    selection_changed = Signal(dict, bool)
    preview_state_changed = Signal(dict, bool)
    drag_started = Signal(dict)
    drag_ended = Signal(dict, str)

    _icon_cache = {}
    _font_family_cache = None

    @classmethod
    def _clear_shared_caches(cls, file_path=None):
        if file_path is None:
            cls._icon_cache.clear()
            return

        normalized_path = os.path.normpath(file_path)
        keys_to_remove = [
            cache_key
            for cache_key in cls._icon_cache.keys()
            if cache_key and len(cache_key) > 0 and os.path.normpath(str(cache_key[0])) == normalized_path
        ]
        for cache_key in keys_to_remove:
            cls._icon_cache.pop(cache_key, None)

    @classmethod
    def _get_overlay_font_family(cls):
        if cls._font_family_cache is not None:
            return cls._font_family_cache

        font_path = os.path.join(os.path.dirname(__file__), "..", "icons", "庞门正道标题体.ttf")
        font_path = os.path.normpath(font_path)
        try:
            if os.path.exists(font_path):
                font_id = QFontDatabase.addApplicationFont(font_path)
                if font_id != -1:
                    families = QFontDatabase.applicationFontFamilies(font_id)
                    if families:
                        cls._font_family_cache = families[0]
                        return cls._font_family_cache
        except (OSError, IOError, PermissionError, FileNotFoundError, RuntimeError, ValueError, TypeError) as e:
            debug(f"加载文件图标覆盖字体失败: {e}")

        cls._font_family_cache = ""
        return cls._font_family_cache

    @Property(QColor)
    def anim_bg_color(self):
        return self._anim_bg_color

    @anim_bg_color.setter
    def anim_bg_color(self, color):
        if self._anim_bg_color == color:
            return
        self._anim_bg_color = QColor(color)
        self.update()

    @Property(QColor)
    def anim_border_color(self):
        return self._anim_border_color

    @anim_border_color.setter
    def anim_border_color(self, color):
        if self._anim_border_color == color:
            return
        self._anim_border_color = QColor(color)
        self.update()

    def __init__(self, file_info, dpi_scale=1.0, parent=None):
        super().__init__(parent)

        self.file_info = file_info
        self.dpi_scale = dpi_scale
        self._flexible_width = None

        self._is_selected = False
        self._is_hovered = False
        self._is_previewing = False

        self._touch_drag_threshold = int(10 * self.dpi_scale)
        self._touch_start_pos = None
        self._is_touch_dragging = False

        self._long_press_timer = QTimer(self)
        self._long_press_timer.setSingleShot(True)
        self._long_press_timer.timeout.connect(self._on_long_press)
        self._long_press_duration = 500
        self._is_long_pressing = False
        self._drag_start_pos = None
        self._drag_card = None
        self._is_dragging = False
        self._drag_visual_active = False

        self._geometry_cache_signature = None
        self._geometry_cache = {}
        self._text_layout_signature = None
        self._display_name_text = ""
        self._display_size_text = ""
        self._display_date_text = ""
        self._drag_display_name_text = ""
        self._icon_pixmap = QPixmap()
        self._icon_cache_key = None

        self._setup_ui()
        self._setup_signals()
        self._init_animations()
        self._update_styles()
        self._init_interaction_settings_cache()

    def _setup_ui(self):
        """设置基础属性和字体缓存"""
        self.setObjectName("FileBlockCard")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        self.setMouseTracking(True)

        app = QApplication.instance()
        self.default_font_size = getattr(app, "default_font_size", 8) if app else 8
        self.global_font = getattr(app, "global_font", QFont()) if app else QFont()

        self._init_colors()
        self._init_fonts()
        self._update_text_cache()
        self._update_icon()

        optimal_width = self._calculate_optimal_width()
        optimal_height = self._calculate_optimal_height()
        self.setMinimumWidth(optimal_width)
        self.setMaximumWidth(optimal_width)
        self.setMinimumHeight(optimal_height)
        self.setMaximumHeight(optimal_height)

    def _init_fonts(self):
        """初始化字体及度量缓存"""
        self.name_font = QFont(self.global_font)
        self.small_font = QFont(self.global_font)
        small_font_size = max(1, int(self.global_font.pointSize() * 0.85))
        self.small_font.setPointSize(small_font_size)

        self.name_font_metrics = QFontMetrics(self.name_font)
        self.small_font_metrics = QFontMetrics(self.small_font)

        self._text_color = QColor(self.secondary_color)
        self._label_palette = QPalette()
        self._label_palette.setColor(QPalette.WindowText, self._text_color)

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
        except (OSError, IOError, PermissionError, FileNotFoundError) as e:
            debug(f"初始化颜色配置失败 - 文件操作错误，使用默认颜色: {e}")
            self.base_color = "#212121"
            self.auxiliary_color = "#3D3D3D"
            self.normal_color = "#717171"
            self.accent_color = "#B036EE"
            self.secondary_color = "#FFFFFF"
        except (ValueError, TypeError) as e:
            debug(f"初始化颜色配置失败 - 数据转换错误，使用默认颜色: {e}")
            self.base_color = "#212121"
            self.auxiliary_color = "#3D3D3D"
            self.normal_color = "#717171"
            self.accent_color = "#B036EE"
            self.secondary_color = "#FFFFFF"
        except RuntimeError as e:
            debug(f"初始化颜色配置失败 - Qt运行时错误，使用默认颜色: {e}")
            self.base_color = "#212121"
            self.auxiliary_color = "#3D3D3D"
            self.normal_color = "#717171"
            self.accent_color = "#B036EE"
            self.secondary_color = "#FFFFFF"

    def _calculate_optimal_height(self):
        """计算卡片最佳高度"""
        min_height = int(75 * self.dpi_scale)
        icon_size = int(38 * self.dpi_scale)
        name_font_height = self.name_font_metrics.height()
        small_font_height = self.small_font_metrics.height()

        labels_height = name_font_height + (small_font_height * 2)
        layout_spacing = int(2 * self.dpi_scale)
        total_spacing = layout_spacing * 3
        vertical_margins = int(4 * self.dpi_scale) * 2
        border_width = int(1 * self.dpi_scale) * 2

        required_height = icon_size + labels_height + total_spacing + vertical_margins + border_width
        return max(required_height, min_height)

    def _calculate_optimal_width(self):
        """计算卡片最佳宽度"""
        base_min_width = int(50 * self.dpi_scale)
        date_text_width = self.small_font_metrics.horizontalAdvance("2024-12-31")
        char_width = self.small_font_metrics.horizontalAdvance("W")
        horizontal_margins = int(4 * self.dpi_scale) * 2
        border_width = int(1 * self.dpi_scale) * 2

        required_width = date_text_width + char_width + horizontal_margins + border_width
        return max(required_width, base_min_width)

    def _setup_signals(self):
        """设置事件过滤器"""
        self.installEventFilter(self)

    def _init_interaction_settings_cache(self):
        """初始化交互设置缓存"""
        self._touch_optimization_enabled = True
        self._mouse_buttons_swapped = False
        try:
            app = QApplication.instance()
            settings_manager = getattr(app, "settings_manager", None) if app else None
            if settings_manager is None:
                settings_manager = SettingsManager()

            self._touch_optimization_enabled = bool(
                settings_manager.get_setting("file_selector.touch_optimization", True)
            )
            self._mouse_buttons_swapped = bool(
                settings_manager.get_setting("file_selector.mouse_buttons_swap", False)
            )
        except (OSError, IOError, PermissionError, FileNotFoundError) as e:
            debug(f"初始化交互设置缓存失败 - 文件操作错误: {e}")
        except (ValueError, TypeError) as e:
            debug(f"初始化交互设置缓存失败 - 数据转换错误: {e}")
        except RuntimeError as e:
            debug(f"初始化交互设置缓存失败 - Qt运行时错误: {e}")

    def _is_touch_optimization_enabled(self):
        return getattr(self, "_touch_optimization_enabled", True)

    def _is_mouse_buttons_swapped(self):
        return getattr(self, "_mouse_buttons_swapped", False)

    def _is_previewer_loading(self):
        try:
            main_window = self.window()
            if main_window and hasattr(main_window, "unified_previewer"):
                previewer = main_window.unified_previewer
                if previewer and hasattr(previewer, "is_loading_preview"):
                    return previewer.is_loading_preview
        except (OSError, IOError, PermissionError, FileNotFoundError) as e:
            debug(f"检查预览器加载状态失败 - 文件操作错误: {e}")
        except (ValueError, TypeError) as e:
            debug(f"检查预览器加载状态失败 - 数据转换错误: {e}")
        except RuntimeError as e:
            debug(f"检查预览器加载状态失败 - Qt运行时错误: {e}")
        return False

    def eventFilter(self, obj, event):
        """事件过滤器，处理鼠标事件"""
        if obj == self:
            buttons_swapped = self._is_mouse_buttons_swapped()

            if event.type() == QEvent.MouseButtonPress:
                if event.button() == Qt.LeftButton:
                    self._touch_start_pos = event.pos()
                    self._is_touch_dragging = False
                    if self._is_touch_optimization_enabled() and not self._is_previewer_loading():
                        self._long_press_timer.start(self._long_press_duration)
                    self._drag_start_pos = event.globalPos()
                elif event.button() == Qt.RightButton:
                    if buttons_swapped:
                        self._touch_start_pos = event.pos()
                        self._is_touch_dragging = False
                        if self._is_touch_optimization_enabled() and not self._is_previewer_loading():
                            self._long_press_timer.start(self._long_press_duration)
                        self._drag_start_pos = event.globalPos()
                    else:
                        self._on_right_click(event)
                else:
                    return False
                return True

            elif event.type() == QEvent.MouseMove:
                if self._is_dragging and self._drag_card:
                    self._update_drag_card_position(event.globalPos())
                    return True
                elif self._touch_start_pos is not None:
                    delta = event.pos() - self._touch_start_pos
                    if abs(delta.x()) > self._touch_drag_threshold or abs(delta.y()) > self._touch_drag_threshold:
                        self._is_touch_dragging = True
                        if not self._is_dragging:
                            self._long_press_timer.stop()
                            self._is_long_pressing = False
                return False

            elif event.type() == QEvent.MouseButtonRelease:
                if event.button() == Qt.LeftButton:
                    if self._is_dragging:
                        self._end_drag(event.globalPos())
                    elif self._touch_start_pos is not None and not self._is_touch_dragging:
                        if buttons_swapped:
                            self._on_right_click(event)
                        else:
                            self._on_click(event)
                    self._long_press_timer.stop()
                    self._is_long_pressing = False
                    self._touch_start_pos = None
                    self._is_touch_dragging = False
                elif event.button() == Qt.RightButton:
                    if buttons_swapped:
                        if self._is_dragging:
                            self._end_drag(event.globalPos())
                        elif self._touch_start_pos is not None and not self._is_touch_dragging:
                            self._on_click(event)
                        self._long_press_timer.stop()
                        self._is_long_pressing = False
                        self._touch_start_pos = None
                        self._is_touch_dragging = False
                return True

            elif event.type() == QEvent.MouseButtonDblClick:
                if event.button() == Qt.LeftButton:
                    self._long_press_timer.stop()
                    self._is_long_pressing = False
                    if buttons_swapped:
                        self._on_right_click(event)
                    else:
                        self._on_double_click(event)
                elif event.button() == Qt.RightButton:
                    if buttons_swapped:
                        self._long_press_timer.stop()
                        self._is_long_pressing = False
                        self._on_double_click(event)
                return True

            elif event.type() == QEvent.Enter:
                if not self._is_selected and not self._is_dragging:
                    self._is_hovered = True
                    self._trigger_hover_animation()
                return False

            elif event.type() == QEvent.Leave:
                if not self._is_dragging:
                    self._is_hovered = False
                    self._trigger_leave_animation()
                self._touch_start_pos = None
                self._is_touch_dragging = False
                return False

        return super().eventFilter(obj, event)

    def _on_click(self, event):
        self.clicked.emit(self.file_info)

    def _on_right_click(self, event):
        self.set_selected(not self._is_selected)
        self.right_clicked.emit(self.file_info)

    def _on_double_click(self, event):
        self.double_clicked.emit(self.file_info)

    def _init_animations(self):
        """初始化卡片状态切换动画"""
        base_qcolor = QColor(self.base_color)
        auxiliary_qcolor = QColor(self.auxiliary_color)
        normal_qcolor = QColor(self.normal_color)
        accent_qcolor = QColor(self.accent_color)

        normal_bg = QColor(base_qcolor)
        hover_bg = QColor(auxiliary_qcolor)
        selected_bg = QColor(accent_qcolor)
        selected_bg.setAlpha(102)
        normal_border = QColor(auxiliary_qcolor)
        hover_border = QColor(normal_qcolor)
        selected_border = QColor(accent_qcolor)

        self._style_colors = {
            "normal_bg": normal_bg,
            "hover_bg": hover_bg,
            "selected_bg": selected_bg,
            "normal_border": normal_border,
            "hover_border": hover_border,
            "selected_border": selected_border,
        }

        self._anim_bg_color = QColor(normal_bg)
        self._anim_border_color = QColor(normal_border)

        self._hover_anim_group = QParallelAnimationGroup(self)

        self._anim_hover_bg = QPropertyAnimation(self, b"anim_bg_color")
        self._anim_hover_bg.setStartValue(normal_bg)
        self._anim_hover_bg.setEndValue(hover_bg)
        self._anim_hover_bg.setDuration(150)
        self._anim_hover_bg.setEasingCurve(QEasingCurve.OutCubic)

        self._anim_hover_border = QPropertyAnimation(self, b"anim_border_color")
        self._anim_hover_border.setStartValue(normal_border)
        self._anim_hover_border.setEndValue(hover_border)
        self._anim_hover_border.setDuration(150)
        self._anim_hover_border.setEasingCurve(QEasingCurve.OutCubic)

        self._hover_anim_group.addAnimation(self._anim_hover_bg)
        self._hover_anim_group.addAnimation(self._anim_hover_border)

        self._leave_anim_group = QParallelAnimationGroup(self)

        self._anim_leave_bg = QPropertyAnimation(self, b"anim_bg_color")
        self._anim_leave_bg.setStartValue(hover_bg)
        self._anim_leave_bg.setEndValue(normal_bg)
        self._anim_leave_bg.setDuration(200)
        self._anim_leave_bg.setEasingCurve(QEasingCurve.InOutQuad)

        self._anim_leave_border = QPropertyAnimation(self, b"anim_border_color")
        self._anim_leave_border.setStartValue(hover_border)
        self._anim_leave_border.setEndValue(normal_border)
        self._anim_leave_border.setDuration(200)
        self._anim_leave_border.setEasingCurve(QEasingCurve.InOutQuad)

        self._leave_anim_group.addAnimation(self._anim_leave_bg)
        self._leave_anim_group.addAnimation(self._anim_leave_border)

        self._select_anim_group = QParallelAnimationGroup(self)

        self._anim_select_bg = QPropertyAnimation(self, b"anim_bg_color")
        self._anim_select_bg.setStartValue(normal_bg)
        self._anim_select_bg.setEndValue(selected_bg)
        self._anim_select_bg.setDuration(180)
        self._anim_select_bg.setEasingCurve(QEasingCurve.OutCubic)

        self._anim_select_border = QPropertyAnimation(self, b"anim_border_color")
        self._anim_select_border.setStartValue(normal_border)
        self._anim_select_border.setEndValue(selected_border)
        self._anim_select_border.setDuration(180)
        self._anim_select_border.setEasingCurve(QEasingCurve.OutCubic)

        self._select_anim_group.addAnimation(self._anim_select_bg)
        self._select_anim_group.addAnimation(self._anim_select_border)

        self._deselect_anim_group = QParallelAnimationGroup(self)

        self._anim_deselect_bg = QPropertyAnimation(self, b"anim_bg_color")
        self._anim_deselect_bg.setStartValue(selected_bg)
        self._anim_deselect_bg.setEndValue(normal_bg)
        self._anim_deselect_bg.setDuration(200)
        self._anim_deselect_bg.setEasingCurve(QEasingCurve.InOutQuad)

        self._anim_deselect_border = QPropertyAnimation(self, b"anim_border_color")
        self._anim_deselect_border.setStartValue(selected_border)
        self._anim_deselect_border.setEndValue(normal_border)
        self._anim_deselect_border.setDuration(200)
        self._anim_deselect_border.setEasingCurve(QEasingCurve.InOutQuad)

        self._deselect_anim_group.addAnimation(self._anim_deselect_bg)
        self._deselect_anim_group.addAnimation(self._anim_deselect_border)

        self._preview_anim_group = QParallelAnimationGroup(self)

        self._anim_preview_bg = QPropertyAnimation(self, b"anim_bg_color")
        self._anim_preview_bg.setDuration(180)
        self._anim_preview_bg.setEasingCurve(QEasingCurve.OutCubic)

        self._anim_preview_border = QPropertyAnimation(self, b"anim_border_color")
        self._anim_preview_border.setDuration(180)
        self._anim_preview_border.setEasingCurve(QEasingCurve.OutCubic)

        self._preview_anim_group.addAnimation(self._anim_preview_bg)
        self._preview_anim_group.addAnimation(self._anim_preview_border)

        self._unpreview_anim_group = QParallelAnimationGroup(self)

        self._anim_unpreview_bg = QPropertyAnimation(self, b"anim_bg_color")
        self._anim_unpreview_bg.setDuration(200)
        self._anim_unpreview_bg.setEasingCurve(QEasingCurve.InOutQuad)

        self._anim_unpreview_border = QPropertyAnimation(self, b"anim_border_color")
        self._anim_unpreview_border.setDuration(200)
        self._anim_unpreview_border.setEasingCurve(QEasingCurve.InOutQuad)

        self._unpreview_anim_group.addAnimation(self._anim_unpreview_bg)
        self._unpreview_anim_group.addAnimation(self._anim_unpreview_border)

    def _stop_all_animations(self):
        for attr_name in (
            "_hover_anim_group",
            "_leave_anim_group",
            "_select_anim_group",
            "_deselect_anim_group",
            "_preview_anim_group",
            "_unpreview_anim_group",
        ):
            group = getattr(self, attr_name, None)
            if group is not None:
                group.stop()

    def _trigger_hover_animation(self):
        if not hasattr(self, "_style_colors"):
            self._update_styles()
            return

        if self._is_selected or self._is_previewing:
            return

        self._leave_anim_group.stop()

        colors = self._style_colors
        self._anim_hover_bg.setStartValue(self._anim_bg_color)
        self._anim_hover_bg.setEndValue(colors["hover_bg"])
        self._anim_hover_border.setStartValue(self._anim_border_color)
        self._anim_hover_border.setEndValue(colors["hover_border"])

        self._hover_anim_group.start()

    def _trigger_leave_animation(self):
        if not hasattr(self, "_style_colors"):
            self._update_styles()
            return

        if self._is_selected or self._is_previewing:
            return

        self._hover_anim_group.stop()

        colors = self._style_colors
        self._anim_leave_bg.setStartValue(self._anim_bg_color)
        self._anim_leave_bg.setEndValue(colors["normal_bg"])
        self._anim_leave_border.setStartValue(self._anim_border_color)
        self._anim_leave_border.setEndValue(colors["normal_border"])
        self._leave_anim_group.start()

    def _update_styles(self):
        """高性能样式刷新入口"""
        self._update_card_style()
        self._update_label_styles()

    def update_theme(self):
        """重新加载主题颜色并刷新当前卡片样式/图标/动画缓存"""
        self._stop_all_animations()
        self._init_colors()
        self._init_fonts()
        self._init_animations()
        FileBlockCard._clear_shared_caches()
        SvgRenderer._invalidate_color_cache()
        self._text_color = QColor(self.secondary_color)
        self._label_palette.setColor(QPalette.WindowText, self._text_color)
        self._invalidate_geometry_cache()
        self._update_text_cache(force=True)
        self._update_icon(force=True)
        self._update_styles()
        self._init_interaction_settings_cache()
        self.update()

    def _update_card_style(self):
        self.update()

    def _update_label_styles(self):
        self.update()

    def _hex_to_rgba(self, hex_color, alpha):
        hex_color = hex_color.lstrip("#")
        if len(hex_color) == 6:
            r = int(hex_color[0:2], 16)
            g = int(hex_color[2:4], 16)
            b = int(hex_color[4:6], 16)
            return f"rgba({r}, {g}, {b}, {alpha / 100.0:.2f})"
        return hex_color

    def set_selected(self, selected):
        if self._is_selected != selected:
            self._is_selected = selected
            if selected:
                self._is_hovered = False
                self._trigger_select_animation()
            else:
                self._trigger_deselect_animation()
            self._update_label_styles()
            self.selection_changed.emit(self.file_info, selected)

    def set_previewing(self, previewing):
        if self._is_previewing != previewing:
            self._is_previewing = previewing
            if previewing:
                self._is_hovered = False
                self._trigger_preview_animation()
            else:
                self._trigger_unpreview_animation()
            self._update_card_style()
            self._update_label_styles()
            self.preview_state_changed.emit(self.file_info, previewing)

    def _trigger_preview_animation(self):
        if not hasattr(self, "_style_colors"):
            self._update_styles()
            return

        self._hover_anim_group.stop()
        self._leave_anim_group.stop()
        self._select_anim_group.stop()
        self._deselect_anim_group.stop()

        colors = self._style_colors
        secondary_qcolor = QColor(self.secondary_color)

        target_bg = colors["selected_bg"] if self._is_selected else colors["normal_bg"]

        self._anim_preview_bg.setStartValue(self._anim_bg_color)
        self._anim_preview_bg.setEndValue(target_bg)
        self._anim_preview_border.setStartValue(self._anim_border_color)
        self._anim_preview_border.setEndValue(secondary_qcolor)

        self._preview_anim_group.start()

    def _trigger_unpreview_animation(self):
        if not hasattr(self, "_style_colors"):
            self._update_styles()
            return

        self._preview_anim_group.stop()

        colors = self._style_colors
        if self._is_selected:
            target_bg = colors["selected_bg"]
            target_border = colors["selected_border"]
        else:
            target_bg = colors["normal_bg"]
            target_border = colors["normal_border"]

        self._anim_unpreview_bg.setStartValue(self._anim_bg_color)
        self._anim_unpreview_bg.setEndValue(target_bg)
        self._anim_unpreview_border.setStartValue(self._anim_border_color)
        self._anim_unpreview_border.setEndValue(target_border)

        self._unpreview_anim_group.start()

    def _trigger_select_animation(self):
        if not hasattr(self, "_style_colors"):
            self._update_styles()
            return

        self._hover_anim_group.stop()
        self._leave_anim_group.stop()

        colors = self._style_colors
        self._anim_select_bg.setStartValue(self._anim_bg_color)
        self._anim_select_bg.setEndValue(colors["selected_bg"])
        self._anim_select_border.setStartValue(self._anim_border_color)
        self._anim_select_border.setEndValue(colors["selected_border"])
        self._select_anim_group.start()

    def _trigger_deselect_animation(self):
        if not hasattr(self, "_style_colors"):
            self._update_styles()
            return

        self._select_anim_group.stop()

        colors = self._style_colors
        self._anim_deselect_bg.setStartValue(self._anim_bg_color)
        self._anim_deselect_bg.setEndValue(colors["normal_bg"])
        self._anim_deselect_border.setStartValue(self._anim_border_color)
        self._anim_deselect_border.setEndValue(colors["normal_border"])
        self._deselect_anim_group.start()

    def is_selected(self):
        return self._is_selected

    def is_previewing(self):
        return self._is_previewing

    def set_file_info(self, file_info):
        self.file_info = file_info
        self._icon_cache_key = None
        self._update_text_cache(force=True)
        self._update_icon(force=True)
        self.update()

    def refresh_thumbnail(self):
        self._icon_cache_key = None
        self._update_icon(force=True)
        self.update()

    def prepare_for_reuse(self, file_info, flexible_width=None):
        self._cleanup_drag_state()
        self._stop_all_animations()
        self._is_selected = False
        self._is_hovered = False
        self._is_previewing = False
        self._anim_bg_color = QColor(self._style_colors["normal_bg"])
        self._anim_border_color = QColor(self._style_colors["normal_border"])
        self.set_file_info(file_info)
        if flexible_width is not None:
            self.set_flexible_width(flexible_width)
        else:
            self.updateGeometry()
        self.update()

    def sizeHint(self):
        optimal_width = self._calculate_optimal_width()
        optimal_height = self._calculate_optimal_height()
        return QSize(optimal_width, optimal_height)

    def set_flexible_width(self, width):
        self._flexible_width = width
        optimal_width = self._calculate_optimal_width()
        constrained_width = max(optimal_width, width)
        self.setFixedWidth(constrained_width)
        self.updateGeometry()
        self._update_text_cache(force=True)

    def _invalidate_geometry_cache(self):
        self._geometry_cache_signature = None
        self._text_layout_signature = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._invalidate_geometry_cache()
        self._update_text_cache(force=True)

    def _on_long_press(self):
        if self._is_previewer_loading():
            self._is_long_pressing = False
            return
        self._is_long_pressing = True
        self._start_drag()

    def _start_drag(self):
        self._is_dragging = True
        self._set_dragging_appearance(True)
        self._create_drag_card()
        self.drag_started.emit(self.file_info)
        self.setCursor(QCursor(Qt.ClosedHandCursor))

    def _set_dragging_appearance(self, is_dragging):
        self._drag_visual_active = bool(is_dragging)
        self.update()

    def _create_drag_card(self):
        if self._drag_card:
            self._drag_card.deleteLater()

        pixmap = self._render_card_pixmap(for_drag_preview=True)
        self._drag_card = QLabel(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self._drag_card.setAttribute(Qt.WA_TranslucentBackground, True)
        self._drag_card.setStyleSheet("background: transparent; border: none;")
        self._drag_card.setPixmap(pixmap)
        self._drag_card.resize(pixmap.size())

        cursor_pos = QCursor.pos()
        card_width = self._drag_card.width()
        card_height = self._drag_card.height()
        self._drag_card.move(cursor_pos.x() - card_width // 2, cursor_pos.y() - card_height // 2)
        self._drag_card.show()

    def _format_size_for_drag(self, size):
        return self._format_size(size)

    def _update_drag_card_position(self, global_pos):
        if self._drag_card:
            card_width = self._drag_card.width()
            card_height = self._drag_card.height()
            self._drag_card.move(global_pos.x() - card_width // 2, global_pos.y() - card_height // 2)

    def _cleanup_drag_state(self):
        self._long_press_timer.stop()
        self._is_long_pressing = False
        self._touch_start_pos = None
        self._is_touch_dragging = False
        self._drag_start_pos = None

        if self._drag_card:
            self._drag_card.hide()
            self._drag_card.deleteLater()
            self._drag_card = None

        self._is_dragging = False
        self._drag_visual_active = False
        self.unsetCursor()
        self._update_styles()

    def _end_drag(self, global_pos):
        self._set_dragging_appearance(False)
        self.setCursor(QCursor(Qt.ArrowCursor))
        drop_target = self._detect_drop_target(global_pos)
        self.drag_ended.emit(self.file_info, drop_target)
        self._cleanup_drag_state()

    def _detect_drop_target(self, global_pos):
        main_window = self.window()
        if not main_window:
            return "none"

        if hasattr(main_window, "file_staging_pool"):
            staging_pool = main_window.file_staging_pool
            if staging_pool and staging_pool.isVisible():
                staging_rect = staging_pool.rect()
                staging_global_pos = staging_pool.mapToGlobal(staging_rect.topLeft())
                staging_global_rect = staging_rect.translated(staging_global_pos - staging_pool.pos())
                if staging_global_rect.contains(global_pos):
                    return "staging_pool"

        if hasattr(main_window, "unified_previewer"):
            previewer = main_window.unified_previewer
            if previewer and previewer.isVisible():
                previewer_rect = previewer.rect()
                previewer_global_pos = previewer.mapToGlobal(previewer_rect.topLeft())
                previewer_global_rect = previewer_rect.translated(previewer_global_pos - previewer.pos())
                if previewer_global_rect.contains(global_pos):
                    return "previewer"

        return "none"

    def is_dragging(self):
        return self._is_dragging

    def hideEvent(self, event):
        self._cleanup_drag_state()
        self._stop_all_animations()
        super().hideEvent(event)

    def closeEvent(self, event):
        self._cleanup_drag_state()
        self._stop_all_animations()
        super().closeEvent(event)

    def _format_size(self, size):
        if size < 0:
            size = 0
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        if size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        return f"{size / (1024 * 1024 * 1024):.1f} GB"

    def _format_created_text(self, created):
        if not created:
            return ""
        from PySide6.QtCore import QDateTime

        try:
            dt = QDateTime.fromString(created, Qt.ISODate)
            if dt.isValid():
                return dt.toString("yyyy-MM-dd")
        except (ValueError, TypeError) as e:
            debug(f"解析日期时间失败 - 数据转换错误: {e}, 原始值: {created}")
        return created[:10] if len(created) >= 10 else created

    def _update_text_cache(self, force=False):
        name = self.file_info.get("name", "")
        size_text = "文件夹" if self.file_info.get("is_dir", False) else self._format_size(self.file_info.get("size", 0))
        date_text = self._format_created_text(self.file_info.get("created", ""))

        signature = (self.width(), name, size_text, date_text)
        if not force and self._text_layout_signature == signature:
            return

        self._text_layout_signature = signature
        self._display_size_text = size_text
        self._display_date_text = date_text

        content_rect = self._get_content_rect()
        text_max_width = max(int(35 * self.dpi_scale), content_rect.width())
        drag_text_max_width = max(int(35 * self.dpi_scale), self.width() - int(8 * self.dpi_scale))

        self._display_name_text = self.name_font_metrics.elidedText(name, Qt.ElideRight, text_max_width)
        self._drag_display_name_text = self.name_font_metrics.elidedText(name, Qt.ElideRight, drag_text_max_width)

    def _get_content_rect(self):
        margin = int(4 * self.dpi_scale)
        return self.rect().adjusted(margin, margin, -margin, -margin)

    def _ensure_geometry_cache(self):
        border_width = max(1, int(1 * self.dpi_scale))
        preview_border_width = border_width * 2
        radius = max(1, int(8 * self.dpi_scale))
        icon_size = int(38 * self.dpi_scale)
        spacing = int(2 * self.dpi_scale)
        margins = int(4 * self.dpi_scale)

        signature = (
            self.width(),
            self.height(),
            border_width,
            preview_border_width,
            radius,
            icon_size,
            spacing,
            margins,
        )
        if self._geometry_cache_signature == signature:
            return

        self._geometry_cache_signature = signature

        content_rect = self.rect().adjusted(margins, margins, -margins, -margins)
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

        self._geometry_cache = {
            "border_width": border_width,
            "preview_border_width": preview_border_width,
            "radius": radius,
            "content_rect": content_rect,
            "icon_rect": icon_rect,
            "name_rect": name_rect,
            "size_rect": size_rect,
            "time_rect": time_rect,
        }

    def _get_thumbnail_path(self, file_path):
        thumbnail_path = get_existing_thumbnail_path(file_path)
        if thumbnail_path:
            return thumbnail_path

        thumbnail_manager = get_thumbnail_manager(self.dpi_scale)
        return thumbnail_manager.get_thumbnail_path(file_path)

    def _get_icon_path(self):
        return get_file_icon_path(self.file_info)

    def _safe_get_mtime(self, path):
        if not path:
            return None
        try:
            return os.path.getmtime(path)
        except (OSError, IOError, PermissionError, FileNotFoundError, RuntimeError, TypeError, ValueError):
            return None

    def _build_icon_source_signature(self):
        file_path = self.file_info.get("path", "")
        is_dir = self.file_info.get("is_dir", False)
        suffix = self.file_info.get("suffix", "").lower()

        if not file_path:
            return ("empty",)

        if not is_dir and suffix in ["lnk", "exe", "url"]:
            file_mtime = self._safe_get_mtime(file_path)
            return ("system_icon", os.path.normpath(file_path), file_mtime)

        thumbnail_path = get_existing_thumbnail_path(file_path)
        is_photo = suffix in [
            "jpg", "jpeg", "png", "gif", "bmp", "webp", "tiff", "svg",
            "avif", "cr2", "cr3", "nef", "arw", "dng", "orf", "psd", "psb"
        ]
        is_video = suffix in [
            "mp4", "mov", "avi", "mkv", "wmv", "flv", "webm", "m4v", "mpeg", "mpg", "mxf"
        ]

        if (is_photo or is_video) and thumbnail_path and os.path.exists(thumbnail_path):
            thumbnail_mtime = self._safe_get_mtime(thumbnail_path)
            return ("thumbnail", os.path.normpath(thumbnail_path), thumbnail_mtime)

        icon_path = self._get_icon_path()
        icon_mtime = self._safe_get_mtime(icon_path) if icon_path and os.path.exists(icon_path) else None
        return ("file_icon", os.path.normpath(icon_path) if icon_path else "", icon_mtime)

    def _get_device_pixel_ratio(self):
        try:
            dpr = float(self.devicePixelRatioF())
            if dpr > 0:
                return dpr
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass

        try:
            app = QApplication.instance()
            screen = app.primaryScreen() if app else None
            if screen is not None:
                dpr = float(screen.devicePixelRatio())
                if dpr > 0:
                    return dpr
        except RuntimeError:
            pass

        return 1.0

    def _render_exact_svg_icon_pixmap(self, icon_path, icon_width, icon_height, replace_colors=True):
        pixmap = SvgRenderer.render_svg_to_exact_pixmap(
            icon_path,
            icon_width=icon_width,
            icon_height=icon_height,
            replace_colors=replace_colors,
            device_pixel_ratio=self._get_device_pixel_ratio(),
        )
        return self._recenter_icon_pixmap(pixmap)

    def _recenter_icon_pixmap(self, pixmap):
        """仅裁切透明边缘并在原尺寸画布中重新居中，不进行额外缩放。"""
        if pixmap.isNull():
            return pixmap

        try:
            source_image = pixmap.toImage()
            image_width = source_image.width()
            image_height = source_image.height()

            min_x = image_width
            min_y = image_height
            max_x = -1
            max_y = -1

            for y in range(image_height):
                for x in range(image_width):
                    if QColor.fromRgba(source_image.pixel(x, y)).alpha() > 0:
                        if x < min_x:
                            min_x = x
                        if y < min_y:
                            min_y = y
                        if x > max_x:
                            max_x = x
                        if y > max_y:
                            max_y = y

            if max_x < min_x or max_y < min_y:
                return pixmap

            source_rect = QRect(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)
            full_rect = QRect(0, 0, image_width, image_height)
            if source_rect == full_rect:
                return pixmap

            recentered = QPixmap(image_width, image_height)
            recentered.fill(Qt.transparent)

            target_x = (image_width - source_rect.width()) // 2
            target_y = (image_height - source_rect.height()) // 2

            clean_pixmap = QPixmap.fromImage(source_image)
            clean_pixmap.setDevicePixelRatio(1.0)

            painter = QPainter(recentered)
            painter.setRenderHint(QPainter.Antialiasing, False)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
            painter.drawPixmap(
                target_x,
                target_y,
                clean_pixmap,
                source_rect.x(),
                source_rect.y(),
                source_rect.width(),
                source_rect.height(),
            )
            painter.end()

            dpr = pixmap.devicePixelRatio()
            if dpr and dpr > 0:
                recentered.setDevicePixelRatio(dpr)
            return recentered
        except (RuntimeError, ValueError, TypeError) as e:
            debug(f"重居中文件图标失败: {e}")
            return pixmap

    def _normalize_icon_pixmap(self, pixmap, icon_size):
        """将任意来源的图标规范化为逻辑尺寸 Pixmap，完整且视觉居中显示。"""
        if pixmap.isNull():
            normalized = QPixmap(icon_size, icon_size)
            normalized.fill(Qt.transparent)
            return normalized

        try:
            clean_image = pixmap.toImage()
            clean_pixmap = QPixmap.fromImage(clean_image)
            clean_pixmap.setDevicePixelRatio(1.0)

            output_dpr = self._get_device_pixel_ratio()

            logical_size = max(1, int(icon_size))
            physical_canvas_size = max(1, int(round(logical_size * output_dpr)))

            source_rect = QRect(0, 0, clean_pixmap.width(), clean_pixmap.height())

            # 自动裁掉纯透明边缘，确保视觉内容真正居中
            try:
                image = clean_pixmap.toImage()
                min_x = image.width()
                min_y = image.height()
                max_x = -1
                max_y = -1

                for y in range(image.height()):
                    for x in range(image.width()):
                        if QColor.fromRgba(image.pixel(x, y)).alpha() > 0:
                            if x < min_x:
                                min_x = x
                            if y < min_y:
                                min_y = y
                            if x > max_x:
                                max_x = x
                            if y > max_y:
                                max_y = y

                if max_x >= min_x and max_y >= min_y:
                    source_rect = QRect(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)
            except (RuntimeError, ValueError, TypeError) as crop_error:
                debug(f"裁切图标透明边缘失败，回退使用完整区域: {crop_error}")

            source_width = max(1, source_rect.width())
            source_height = max(1, source_rect.height())

            normalized = QPixmap(physical_canvas_size, physical_canvas_size)
            normalized.fill(Qt.transparent)

            target_size = QSize(source_width, source_height).scaled(
                physical_canvas_size,
                physical_canvas_size,
                Qt.KeepAspectRatio,
            )
            target_rect = QRectF(
                (physical_canvas_size - target_size.width()) / 2.0,
                (physical_canvas_size - target_size.height()) / 2.0,
                float(target_size.width()),
                float(target_size.height()),
            )

            painter = QPainter(normalized)
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            painter.drawPixmap(
                target_rect,
                clean_pixmap,
                QRectF(source_rect),
            )
            painter.end()

            normalized.setDevicePixelRatio(output_dpr)
            return normalized
        except (RuntimeError, ValueError, TypeError) as e:
            debug(f"规范化图标 Pixmap 失败: {e}")
            fallback = QPixmap(icon_size, icon_size)
            fallback.fill(Qt.transparent)
            return fallback

    def _grab_widget_icon_pixmap(self, widget, icon_size):
        """将 SVG widget 渲染结果抓取为稳定的缓存 pixmap。"""
        if widget is None:
            pixmap = QPixmap(icon_size, icon_size)
            pixmap.fill(Qt.transparent)
            return pixmap

        try:
            widget.setAttribute(Qt.WA_TranslucentBackground, True)
            widget.setStyleSheet("background: transparent; border: none; padding: 0; margin: 0;")
            widget.resize(icon_size, icon_size)
            pixmap = widget.grab()
            widget.deleteLater()
            return self._normalize_icon_pixmap(pixmap, icon_size)
        except (RuntimeError, ValueError, TypeError) as e:
            debug(f"抓取 SVG widget 图标失败: {e}")
            try:
                widget.deleteLater()
            except RuntimeError:
                pass
            fallback = QPixmap(icon_size, icon_size)
            fallback.fill(Qt.transparent)
            return fallback

    def _build_unknown_icon_pixmap(self, icon_path, text, icon_size):
        dpr = self._get_device_pixel_ratio()
        physical_canvas_size = max(1, int(round(icon_size * dpr)))
        base_pixmap = SvgRenderer.render_svg_to_exact_pixmap(
            icon_path,
            icon_width=icon_size,
            icon_height=icon_size,
            replace_colors=True,
            device_pixel_ratio=dpr,
        )

        final_pixmap = QPixmap(physical_canvas_size, physical_canvas_size)
        final_pixmap.fill(Qt.transparent)

        painter = QPainter(final_pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawPixmap(
            QRectF(0.0, 0.0, float(physical_canvas_size), float(physical_canvas_size)),
            base_pixmap,
            QRectF(0.0, 0.0, float(base_pixmap.width()), float(base_pixmap.height())),
        )

        if text:
            font = QFont()
            font_family = self._get_overlay_font_family()
            if font_family:
                font.setFamily(font_family)

            font.setBold(True)
            base_font_pixel_size = max(1, int(physical_canvas_size * 0.234))
            min_font_pixel_size = max(1, int(physical_canvas_size * 0.15))
            font.setPixelSize(base_font_pixel_size)

            font_metrics = QFontMetrics(font)
            text_width = font_metrics.horizontalAdvance(text)
            text_height = font_metrics.height()

            while (
                (text_width > physical_canvas_size * 0.8 or text_height > physical_canvas_size * 0.8)
                and base_font_pixel_size > min_font_pixel_size
            ):
                base_font_pixel_size -= 1
                font.setPixelSize(base_font_pixel_size)
                font_metrics = QFontMetrics(font)
                text_width = font_metrics.horizontalAdvance(text)
                text_height = font_metrics.height()

            is_unified_style = " – 2.svg" in icon_path
            is_textured_archive = "压缩文件 – 1.svg" in icon_path
            if is_unified_style:
                text_color = QColor(self.base_color)
            elif icon_path.endswith("压缩文件.svg") or is_textured_archive:
                text_color = QColor(255, 255, 255)
            else:
                text_color = QColor(0, 0, 0)

            painter.setPen(text_color)
            painter.setFont(font)
            painter.drawText(
                QRectF(0.0, 0.0, float(physical_canvas_size), float(physical_canvas_size)),
                Qt.AlignCenter,
                text,
            )

        painter.end()
        final_pixmap.setDevicePixelRatio(dpr)
        return self._recenter_icon_pixmap(final_pixmap)

    def _build_icon_pixmap(self):
        file_path = self.file_info.get("path", "")
        icon_size = int(38 * self.dpi_scale)
        if not file_path:
            pixmap = QPixmap(icon_size, icon_size)
            pixmap.fill(Qt.transparent)
            return pixmap

        is_dir = self.file_info.get("is_dir", False)
        suffix = self.file_info.get("suffix", "").lower()

        try:
            if not is_dir and suffix in ["lnk", "exe", "url"]:
                try:
                    from freeassetfilter.utils.icon_utils import (
                        get_highest_resolution_icon,
                        hicon_to_pixmap,
                        DestroyIcon,
                    )
                    from PySide6.QtGui import QGuiApplication

                    dpr = QGuiApplication.primaryScreen().devicePixelRatio()
                    hicon = get_highest_resolution_icon(file_path)
                    if hicon:
                        pixmap = hicon_to_pixmap(hicon, icon_size, None, dpr, keep_original_size=True)
                        DestroyIcon(hicon)
                        if pixmap and not pixmap.isNull():
                            return self._normalize_icon_pixmap(pixmap, icon_size)
                except (OSError, IOError, PermissionError, FileNotFoundError) as e:
                    debug(f"提取Windows图标失败 - 文件操作错误: {e}")
                except (ValueError, TypeError) as e:
                    debug(f"提取Windows图标失败 - 数据转换错误: {e}")
                except RuntimeError as e:
                    debug(f"提取Windows图标失败 - Qt运行时错误: {e}")

            thumbnail_path = self._get_thumbnail_path(file_path)
            is_photo = suffix in [
                "jpg", "jpeg", "png", "gif", "bmp", "webp", "tiff", "svg",
                "avif", "cr2", "cr3", "nef", "arw", "dng", "orf", "psd", "psb"
            ]
            is_video = suffix in [
                "mp4", "mov", "avi", "mkv", "wmv", "flv", "webm", "m4v", "mpeg", "mpg", "mxf"
            ]

            if (is_photo or is_video) and os.path.exists(thumbnail_path):
                pixmap = QPixmap(thumbnail_path)
                if not pixmap.isNull():
                    return self._normalize_icon_pixmap(pixmap, icon_size)

            icon_path = self._get_icon_path()
            if icon_path and os.path.exists(icon_path):
                if icon_path.endswith("未知底板.svg") or icon_path.endswith("未知底板 – 1.svg"):
                    display_suffix = suffix.upper()
                    if len(display_suffix) >= 5:
                        display_suffix = "FILE"
                    return self._build_unknown_icon_pixmap(icon_path, display_suffix, icon_size)

                if icon_path.endswith("压缩文件.svg") or icon_path.endswith("压缩文件 – 1.svg"):
                    display_suffix = "." + suffix if suffix else ""
                    return self._build_unknown_icon_pixmap(icon_path, display_suffix, icon_size)

                return self._render_exact_svg_icon_pixmap(
                    icon_path,
                    icon_size,
                    icon_size,
                    replace_colors=True,
                )

        except (OSError, IOError, PermissionError, FileNotFoundError) as e:
            error(f"更新文件图标失败 - 文件操作错误: {e}")
        except (ValueError, TypeError) as e:
            error(f"更新文件图标失败 - 数据转换错误: {e}")
        except RuntimeError as e:
            error(f"更新文件图标失败 - Qt运行时错误: {e}")

        fallback = QPixmap(icon_size, icon_size)
        fallback.fill(Qt.transparent)
        return fallback

    def _update_icon(self, force=False):
        file_path = self.file_info.get("path", "")
        suffix = self.file_info.get("suffix", "").lower()
        icon_size = int(38 * self.dpi_scale)
        device_pixel_ratio = round(self._get_device_pixel_ratio(), 4)
        icon_source_signature = self._build_icon_source_signature()
        cache_key = (
            file_path,
            self.file_info.get("is_dir", False),
            suffix,
            icon_size,
            self.dpi_scale,
            device_pixel_ratio,
            self.base_color,
            self.auxiliary_color,
            self.normal_color,
            self.accent_color,
            self.secondary_color,
            icon_source_signature,
        )

        if not force and self._icon_cache_key == cache_key and not self._icon_pixmap.isNull():
            return

        self._icon_cache_key = cache_key
        cached = FileBlockCard._icon_cache.get(cache_key)
        if cached is not None and not cached.isNull():
            self._icon_pixmap = cached
            return

        self._icon_pixmap = self._build_icon_pixmap()
        if not self._icon_pixmap.isNull():
            FileBlockCard._icon_cache[cache_key] = self._icon_pixmap

    def _get_paint_colors(self, for_drag_preview=False):
        if self._drag_visual_active and not for_drag_preview:
            base_qcolor = QColor(self.base_color)
            base_qcolor.setAlpha(102)
            border_qcolor = QColor(self.auxiliary_color)
            border_qcolor.setAlpha(102)
            return base_qcolor, border_qcolor, QColor(self.secondary_color), self._geometry_cache["border_width"], 0.4

        if for_drag_preview:
            bg_color = QColor(self.base_color)
            border_color = QColor(self.normal_color)
            return bg_color, border_color, QColor(self.secondary_color), self._geometry_cache["border_width"], 1.0

        border_width = (
            self._geometry_cache["preview_border_width"]
            if self._is_previewing
            else self._geometry_cache["border_width"]
        )
        border_color = QColor(self.secondary_color) if self._is_previewing else QColor(self._anim_border_color)
        return QColor(self._anim_bg_color), border_color, QColor(self.secondary_color), border_width, 1.0

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

    def _paint_card(self, painter, rect=None, for_drag_preview=False):
        self._ensure_geometry_cache()
        if rect is None:
            rect = self.rect()

        radius = self._geometry_cache["radius"]
        bg_color, border_color, text_color, border_width, content_opacity = self._get_paint_colors(for_drag_preview)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        draw_rect = QRectF(rect).adjusted(
            border_width / 2.0,
            border_width / 2.0,
            -border_width / 2.0,
            -border_width / 2.0,
        )

        painter.setPen(QPen(border_color, border_width))
        painter.setBrush(bg_color)
        painter.drawRoundedRect(draw_rect, self._geometry_cache["radius"], self._geometry_cache["radius"])

        self._draw_scaled_pixmap(painter, self._geometry_cache["icon_rect"], self._icon_pixmap, content_opacity)

        painter.setPen(text_color)
        painter.setOpacity(content_opacity)

        painter.setFont(self.name_font)
        painter.drawText(self._geometry_cache["name_rect"], Qt.AlignCenter | Qt.TextSingleLine, self._display_name_text)

        painter.setFont(self.small_font)
        painter.drawText(self._geometry_cache["size_rect"], Qt.AlignCenter | Qt.TextSingleLine, self._display_size_text)
        painter.drawText(self._geometry_cache["time_rect"], Qt.AlignCenter | Qt.TextSingleLine, self._display_date_text)

        painter.restore()

    def paintEvent(self, event):
        painter = QPainter(self)
        self._paint_card(painter)
        painter.end()

    def _render_card_pixmap(self, for_drag_preview=False):
        size = self.size()
        if size.width() <= 0 or size.height() <= 0:
            return QPixmap()

        pixmap = QPixmap(size)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        self._paint_card(painter, self.rect(), for_drag_preview=for_drag_preview)
        painter.end()
        return pixmap
