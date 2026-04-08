#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0
Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>
协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；
项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE
自定义文件横向卡片组件
采用左右结构布局，左侧为缩略图/图标，右侧为文字信息
"""

import os
import sys

from PySide6.QtCore import (
    Qt,
    Signal,
    QFileInfo,
    QEvent,
    QPropertyAnimation,
    QEasingCurve,
    Property,
    QParallelAnimationGroup,
    QTimer,
    QRect,
    QRectF,
    QSize,
    QPoint,
)
from PySide6.QtGui import (
    QFont,
    QFontMetrics,
    QPixmap,
    QColor,
    QCursor,
    QPainter,
    QPen,
    QFontDatabase,
    QPalette,
)
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QSizePolicy,
    QApplication,
)

from .button_widgets import CustomButton
from .hover_tooltip import HoverTooltip

# 添加项目根目录到Python路径
sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")),
)

from freeassetfilter.core.settings_manager import SettingsManager  # noqa: E402
from freeassetfilter.core.svg_renderer import SvgRenderer  # noqa: E402
from freeassetfilter.core.thumbnail_manager import get_existing_thumbnail_path, get_thumbnail_manager  # noqa: E402
from freeassetfilter.utils.app_logger import debug, error  # noqa: E402
from freeassetfilter.utils.file_icon_helper import get_icon_path  # noqa: E402


class _HorizontalCardSurface(QWidget):
    """负责卡片底板绘制的轻量画布，保留 card_container 接口不变。"""

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self._owner = owner
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        self.setAutoFillBackground(False)

    def paintEvent(self, event):
        painter = QPainter(self)
        self._owner._paint_card_surface(painter, self.rect())
        painter.end()
        super().paintEvent(event)


class CustomFileHorizontalCard(QWidget):
    """
    自定义文件横向卡片组件

    信号：
        clicked (str): 鼠标单击事件，传递文件路径
        doubleClicked (str): 鼠标双击事件，传递文件路径
        selectionChanged (bool, str): 选中状态改变事件，传递选中状态和文件路径
        previewStateChanged (bool, str): 预览状态改变事件，传递预览状态和文件路径

    属性：
        file_path (str): 文件路径
        is_selected (bool): 是否选中
        is_previewing (bool): 是否处于预览态
        thumbnail_mode (str): 缩略图显示模式，可选值：'icon' 或 'custom'
        dpi_scale (float): DPI缩放因子
        enable_multiselect (bool): 是否开启多选功能
        single_line_mode (bool): 是否使用单行文本格式
    """

    clicked = Signal(str)
    doubleClicked = Signal(str)
    selectionChanged = Signal(bool, str)
    previewStateChanged = Signal(bool, str)
    renameRequested = Signal(str)
    deleteRequested = Signal(str)
    drag_started = Signal(dict)
    drag_ended = Signal(dict, str)

    _current_card_with_visible_buttons = None
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
            for cache_key in list(cls._icon_cache.keys())
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
            debug(f"加载横向卡片覆盖字体失败: {e}")

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
        self._update_card_surface()

    @Property(QColor)
    def anim_border_color(self):
        return self._anim_border_color

    @anim_border_color.setter
    def anim_border_color(self, color):
        if self._anim_border_color == color:
            return
        self._anim_border_color = QColor(color)
        self._update_card_surface()

    def __init__(
        self,
        file_path=None,
        parent=None,
        enable_multiselect=True,
        display_name=None,
        single_line_mode=False,
        enable_delete_button=True,
    ):
        super().__init__(parent)

        app = QApplication.instance()
        self.dpi_scale = getattr(app, "dpi_scale_factor", 1.0)
        self.global_font = getattr(app, "global_font", QFont())
        self.default_font_size = getattr(app, "default_font_size", 9)

        self.setFont(self.global_font)

        self._file_path = file_path
        self._is_selected = False
        self._is_previewing = False
        self._thumbnail_mode = "icon"
        self._enable_multiselect = enable_multiselect
        self._display_name = display_name
        self._single_line_mode = single_line_mode
        self._path_exists = True
        self._custom_info_text = None
        self._enable_delete_button = enable_delete_button

        self._is_mouse_over = False

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
        self._file_info = None

        self._geometry_cache_signature = None
        self._geometry_cache = {}
        self._text_layout_signature = None
        self._display_name_text = ""
        self._display_info_text = ""
        self._icon_pixmap = QPixmap()
        self._icon_cache_key = None
        self._text_mode_deleted = False

        self._label_normal_palette = QPalette()
        self._label_dim_palette = QPalette()
        self._label_missing_palette = QPalette()

        self._init_colors()
        self._init_fonts()
        self.init_ui()
        self._init_animations()
        self._apply_text_palette()
        self._update_card_surface()

        self.hover_tooltip = HoverTooltip(self)
        self.hover_tooltip.set_target_widget(self.card_container)

        if file_path:
            self.set_file_path(file_path, display_name)

    def _init_colors(self):
        try:
            app = QApplication.instance()
            settings_manager = getattr(app, "settings_manager", None)
            if settings_manager is None:
                settings_manager = SettingsManager()

            self.accent_color = settings_manager.get_setting("appearance.colors.accent_color", "#1890ff")
            self.base_color = settings_manager.get_setting("appearance.colors.base_color", "#ffffff")
            self.normal_color = settings_manager.get_setting("appearance.colors.normal_color", "#e0e0e0")
            self.secondary_color = settings_manager.get_setting("appearance.colors.secondary_color", "#333333")
            self.auxiliary_color = settings_manager.get_setting("appearance.colors.auxiliary_color", "#f0f8ff")
        except (OSError, IOError, PermissionError, FileNotFoundError) as e:
            debug(f"初始化横向卡片颜色失败 - 文件操作错误: {e}")
            self.accent_color = "#1890ff"
            self.base_color = "#ffffff"
            self.normal_color = "#e0e0e0"
            self.secondary_color = "#333333"
            self.auxiliary_color = "#f0f8ff"
        except (ValueError, TypeError, RuntimeError) as e:
            debug(f"初始化横向卡片颜色失败 - 数据或运行时错误: {e}")
            self.accent_color = "#1890ff"
            self.base_color = "#ffffff"
            self.normal_color = "#e0e0e0"
            self.secondary_color = "#333333"
            self.auxiliary_color = "#f0f8ff"

        normal_bg = QColor(self.base_color)
        hover_bg = QColor(self.auxiliary_color)
        selected_bg = QColor(self.accent_color)
        selected_bg.setAlpha(102)

        normal_border = QColor(self.auxiliary_color)
        hover_border = QColor(self.normal_color)
        selected_border = QColor(self.accent_color)

        self._style_colors = {
            "normal_bg": normal_bg,
            "hover_bg": hover_bg,
            "selected_bg": selected_bg,
            "normal_border": normal_border,
            "hover_border": hover_border,
            "selected_border": selected_border,
        }

        if not hasattr(self, "_anim_bg_color"):
            self._anim_bg_color = QColor(normal_bg)
        if not hasattr(self, "_anim_border_color"):
            self._anim_border_color = QColor(normal_border)

    def _init_fonts(self):
        self.name_font = QFont(self.global_font)
        self.name_font.setBold(True)

        self.info_font = QFont(self.global_font)
        self.info_font.setWeight(QFont.Normal)

        self.name_font_metrics = QFontMetrics(self.name_font)
        self.info_font_metrics = QFontMetrics(self.info_font)

        secondary_qcolor = QColor(self.secondary_color)
        self._secondary_dim_color = self._darken_or_lighten_color(self.secondary_color)
        self._missing_name_color = QColor(self.normal_color)
        self._missing_info_color = QColor(self.normal_color)

        self._label_normal_palette.setColor(QPalette.WindowText, secondary_qcolor)
        self._label_dim_palette.setColor(QPalette.WindowText, QColor(self._secondary_dim_color))
        self._label_missing_palette.setColor(QPalette.WindowText, self._missing_info_color)

    def init_ui(self):
        """初始化用户界面"""
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumWidth(0)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.card_container = _HorizontalCardSurface(self, self)
        self.card_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.card_container.setMinimumWidth(0)
        self.card_container.setMouseTracking(True)

        card_content_layout = QHBoxLayout(self.card_container)
        card_content_layout.setSpacing(int(7.5 * self.dpi_scale))
        min_height_margin = int(6.25 * self.dpi_scale)
        card_content_layout.setContentsMargins(
            int(7.5 * self.dpi_scale),
            min_height_margin,
            int(7.5 * self.dpi_scale),
            min_height_margin,
        )
        card_content_layout.setAlignment(Qt.AlignVCenter)

        self.icon_display = QLabel()
        self.icon_display.setAlignment(Qt.AlignCenter)
        self.icon_display.setFixedSize(int(40 * self.dpi_scale), int(40 * self.dpi_scale))
        self.icon_display.setStyleSheet("background: transparent; border: none;")
        self.icon_display.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        card_content_layout.addWidget(self.icon_display, alignment=Qt.AlignVCenter)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0 if self._single_line_mode else int(4 * self.dpi_scale))
        text_layout.setAlignment(Qt.AlignVCenter)

        self.name_label = QLabel()
        self.name_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.name_label.setWordWrap(False)
        self.name_label.setMinimumWidth(0)
        self.name_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.name_label.setFont(self.name_font)
        self.name_label.setStyleSheet("background: transparent; border: none;")
        text_layout.addWidget(self.name_label)

        self.info_label = QLabel()
        self.info_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.info_label.setWordWrap(False)
        self.info_label.setMinimumWidth(0)
        self.info_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.info_label.setFont(self.info_font)
        self.info_label.setStyleSheet("background: transparent; border: none;")
        if not self._single_line_mode:
            text_layout.addWidget(self.info_label)

        card_content_layout.addLayout(text_layout, 1)

        self.overlay_widget = QWidget(self.card_container)
        self.overlay_widget.setStyleSheet("background: transparent; border: none;")
        self.overlay_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.overlay_widget.setGeometry(self.card_container.rect())

        overlay_layout = QHBoxLayout(self.overlay_widget)
        overlay_layout.setContentsMargins(
            int(2.5 * self.dpi_scale),
            min_height_margin,
            int(2.5 * self.dpi_scale),
            min_height_margin,
        )
        overlay_layout.setSpacing(int(2.5 * self.dpi_scale))
        overlay_layout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.button1 = CustomButton(
            "重命名",
            parent=self.overlay_widget,
            button_type="primary",
            display_mode="text",
        )
        self.button1.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        overlay_layout.addStretch(1)
        overlay_layout.addWidget(self.button1)
        self.button1.clicked.connect(lambda: self.renameRequested.emit(self._file_path))

        self.button2 = None
        if self._enable_delete_button:
            self.button2 = CustomButton(
                "删除",
                parent=self.overlay_widget,
                button_type="warning",
                display_mode="text",
            )
            self.button2.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            overlay_layout.addWidget(self.button2)
            self.button2.clicked.connect(lambda: self.deleteRequested.emit(self._file_path))

        main_layout.addWidget(self.card_container)

        self.overlay_widget.setWindowOpacity(0.0)
        self.overlay_widget.hide()

        self.card_container.installEventFilter(self)
        self.overlay_widget.installEventFilter(self)

    def _ensure_geometry_cache(self):
        border_width = max(1, int(1 * self.dpi_scale))
        preview_border_width = border_width * 2
        radius = max(1, int(8 * self.dpi_scale))
        signature = (
            self.card_container.width(),
            self.card_container.height(),
            border_width,
            preview_border_width,
            radius,
        )
        if self._geometry_cache_signature == signature:
            return

        self._geometry_cache_signature = signature
        self._geometry_cache = {
            "border_width": border_width,
            "preview_border_width": preview_border_width,
            "radius": radius,
        }

    def _invalidate_geometry_cache(self):
        self._geometry_cache_signature = None

    def _update_card_surface(self):
        self._ensure_geometry_cache()
        self.card_container.update()

    def _get_paint_colors(self):
        self._ensure_geometry_cache()

        if self._drag_visual_active:
            bg_qcolor = QColor(self.base_color)
            bg_qcolor.setAlpha(102)
            border_qcolor = QColor(self.auxiliary_color)
            border_qcolor.setAlpha(102)
            return bg_qcolor, border_qcolor, self._geometry_cache["border_width"]

        border_width = (
            self._geometry_cache["preview_border_width"]
            if self._is_previewing
            else self._geometry_cache["border_width"]
        )
        border_color = QColor(self.secondary_color) if self._is_previewing else QColor(self._anim_border_color)
        return QColor(self._anim_bg_color), border_color, border_width

    def _paint_card_surface(self, painter, rect):
        self._ensure_geometry_cache()
        bg_color, border_color, border_width = self._get_paint_colors()

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        draw_rect = QRectF(rect).adjusted(
            border_width / 2.0,
            border_width / 2.0,
            -border_width / 2.0,
            -border_width / 2.0,
        )
        painter.setPen(QPen(border_color, border_width))
        painter.setBrush(bg_color)
        painter.drawRoundedRect(draw_rect, self._geometry_cache["radius"], self._geometry_cache["radius"])
        painter.restore()

    def _render_card_pixmap(self):
        size = self.card_container.size()
        if size.width() <= 0 or size.height() <= 0:
            return QPixmap()

        pixmap = QPixmap(size)
        pixmap.fill(Qt.transparent)

        self._paint_card_surface_on_pixmap(pixmap)
        return pixmap

    def _paint_card_surface_on_pixmap(self, pixmap):
        painter = QPainter(pixmap)
        self._paint_card_surface(painter, QRect(QPoint(0, 0), pixmap.size()))
        painter.end()

        overlay_visible = self.overlay_widget.isVisible()
        self.overlay_widget.hide()
        grabbed = self.card_container.grab()
        if overlay_visible:
            self.overlay_widget.show()

        mix_painter = QPainter(pixmap)
        mix_painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        mix_painter.drawPixmap(0, 0, grabbed)
        mix_painter.end()

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

    def _apply_animated_style(self):
        """保留旧接口，内部改为轻量刷新。"""
        self._apply_text_palette()
        self._update_card_surface()

    def _apply_text_palette(self):
        normal_text_style = f"background: transparent; border: none; color: {self.secondary_color};"
        missing_text_style = f"background: transparent; border: none; color: {self.normal_color};"

        if self._path_exists:
            self.name_label.setPalette(self._label_normal_palette)
            self.info_label.setPalette(self._label_normal_palette)
            self.name_label.setStyleSheet(normal_text_style)
            self.info_label.setStyleSheet(normal_text_style)
        else:
            self.name_label.setPalette(self._label_missing_palette)
            self.info_label.setPalette(self._label_missing_palette)
            self.name_label.setStyleSheet(
                f"{missing_text_style} text-decoration: line-through;"
            )
            self.info_label.setStyleSheet(missing_text_style)

    def _init_animations(self):
        normal_bg = QColor(self._style_colors["normal_bg"])
        hover_bg = QColor(self._style_colors["hover_bg"])
        selected_bg = QColor(self._style_colors["selected_bg"])
        normal_border = QColor(self._style_colors["normal_border"])
        hover_border = QColor(self._style_colors["hover_border"])
        selected_border = QColor(self._style_colors["selected_border"])

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

    def update_card_style(self):
        """兼容旧接口，改为刷新绘制与文本样式。"""
        self._init_colors()
        self._init_fonts()
        self._apply_text_palette()
        self._update_card_surface()

    def update_style(self):
        self.update_card_style()

    def update_theme(self):
        self._stop_all_animations()
        self._init_colors()
        self._init_fonts()
        self._init_animations()
        CustomFileHorizontalCard._clear_shared_caches()
        SvgRenderer._invalidate_color_cache()
        self._invalidate_geometry_cache()
        self._update_text_cache(force=True)
        self._update_icon(force=True)
        self._apply_text_palette()
        self._update_card_surface()

    def set_file_path(self, file_path, display_name=None):
        self._file_path = file_path
        if display_name is not None:
            self._display_name = display_name
        self._icon_cache_key = None
        self._load_file_info()
        self._update_icon(force=True)

    def set_path_exists(self, exists):
        self._path_exists = exists
        self._load_file_info()
        self._update_icon(force=True)

    def set_custom_info_text(self, text):
        self._custom_info_text = text
        self._load_file_info()

    def set_selected(self, selected):
        if self._enable_multiselect and self._is_selected != selected:
            self._is_selected = selected
            if selected:
                self._trigger_select_animation()
            else:
                self._trigger_deselect_animation()
            self._apply_text_palette()
            self.selectionChanged.emit(selected, self._file_path)

    def set_previewing(self, previewing):
        if self._is_previewing != previewing:
            self._is_previewing = previewing
            if previewing:
                self._is_mouse_over = False
                self.overlay_widget.hide()
                self.overlay_widget.setWindowOpacity(0.0)
                self._trigger_preview_animation()
            else:
                self._trigger_unpreview_animation()
            self._apply_text_palette()
            self._update_card_surface()
            self.previewStateChanged.emit(previewing, self._file_path)

    def _trigger_preview_animation(self):
        if not hasattr(self, "_style_colors"):
            self.update_card_style()
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
            self.update_card_style()
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
            self.update_card_style()
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
            self.update_card_style()
            return

        self._select_anim_group.stop()

        colors = self._style_colors
        self._anim_deselect_bg.setStartValue(self._anim_bg_color)
        self._anim_deselect_bg.setEndValue(colors["normal_bg"])
        self._anim_deselect_border.setStartValue(self._anim_border_color)
        self._anim_deselect_border.setEndValue(colors["normal_border"])
        self._deselect_anim_group.start()

    def set_thumbnail_mode(self, mode):
        if mode in ["icon", "custom"]:
            self._thumbnail_mode = mode
            self._update_icon(force=True)

    def refresh_thumbnail(self):
        self._icon_cache_key = None
        self._update_icon(force=True)

    def _calculate_text_max_width(self):
        card_layout = self.card_container.layout()
        layout_margins = card_layout.contentsMargins()

        icon_width = int(40 * self.dpi_scale)
        layout_spacing = card_layout.spacing()
        horizontal_margin = layout_margins.left() + layout_margins.right()
        max_width = self.width() - horizontal_margin - icon_width - layout_spacing - int(10 * self.dpi_scale)

        min_width = int(50 * self.dpi_scale)
        return max(min_width, max_width)

    def _load_file_info(self):
        if not self._file_path:
            return

        try:
            file_info = QFileInfo(self._file_path)
            file_name = self._display_name if self._display_name else file_info.fileName()
            file_path = file_info.absoluteFilePath()

            if not self._path_exists:
                display_name = f"{file_name}（已移动或删除）"
                info_text = self._file_path
                self._file_info = {
                    "path": self._file_path,
                    "name": file_name,
                    "display_name": file_name,
                    "size": 0,
                    "is_dir": False,
                    "suffix": QFileInfo(self._file_path).suffix().lower(),
                }
                self._update_text_cache(display_name=display_name, info_text=info_text, deleted=True, force=True)
                self._apply_text_palette()
                return

            if file_info.isDir():
                file_size = "文件夹"
            else:
                file_size = self._format_size(file_info.size())

            if self._single_line_mode:
                combined_text = f"{file_name} ({file_size})"
                info_text = ""
                display_name = combined_text
            else:
                display_name = file_name
                info_text = self._custom_info_text if self._custom_info_text else f"{file_path}  {file_size}"

            self._file_info = {
                "path": self._file_path,
                "name": file_info.fileName() or file_name,
                "display_name": file_name,
                "size": file_info.size() if not file_info.isDir() else 0,
                "is_dir": file_info.isDir(),
                "suffix": file_info.suffix().lower(),
            }

            self._update_text_cache(display_name=display_name, info_text=info_text, deleted=False, force=True)
            self._apply_text_palette()
        except (OSError, IOError, PermissionError, FileNotFoundError) as e:
            error(f"加载文件信息失败 - 文件操作错误: {e}")
        except (ValueError, TypeError, RuntimeError) as e:
            error(f"加载文件信息失败 - 数据转换或Qt错误: {e}")

    def _update_text_cache(self, display_name=None, info_text=None, deleted=False, force=False):
        if display_name is None:
            display_name = self._display_name or ""
        if info_text is None:
            info_text = ""

        max_width = self._calculate_text_max_width()
        signature = (max_width, display_name, info_text, deleted, self._single_line_mode)
        if not force and self._text_layout_signature == signature:
            return

        self._text_layout_signature = signature
        self._text_mode_deleted = deleted
        self._display_name_text = self.name_font_metrics.elidedText(display_name, Qt.ElideRight, max_width)
        self._display_info_text = self.info_font_metrics.elidedText(info_text, Qt.ElideRight, max_width)

        self.name_label.setText(self._display_name_text)
        if self._single_line_mode:
            self.info_label.hide()
        else:
            self.info_label.setText(self._display_info_text)
            self.info_label.show()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._invalidate_geometry_cache()
        if self._file_path:
            self._load_file_info()
        self.on_card_container_resize(None)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Enter:
            if not self._is_mouse_over:
                self._is_mouse_over = True
                self._trigger_hover_animation()
                self._hide_other_card_buttons()
                self.on_card_container_resize(None)
                if self.overlay_widget.layout() is not None:
                    self.overlay_widget.layout().invalidate()
                    self.overlay_widget.layout().activate()
                self.overlay_widget.setWindowOpacity(1.0)
                self.overlay_widget.show()
                CustomFileHorizontalCard._current_card_with_visible_buttons = self
        elif event.type() == QEvent.Leave:
            if self._is_mouse_over:
                self._is_mouse_over = False
                if not self._is_dragging:
                    self._trigger_leave_animation()
                self.overlay_widget.hide()
                self.overlay_widget.setWindowOpacity(0.0)
                if CustomFileHorizontalCard._current_card_with_visible_buttons is self:
                    CustomFileHorizontalCard._current_card_with_visible_buttons = None
            if not self._is_dragging:
                self._touch_start_pos = None
                self._is_touch_dragging = False

        return super().eventFilter(obj, event)

    def _hide_other_card_buttons(self):
        current_card = CustomFileHorizontalCard._current_card_with_visible_buttons
        if current_card is not None and current_card is not self:
            try:
                if current_card.isVisible():
                    current_card._is_mouse_over = False
                    current_card._trigger_leave_animation()
                    current_card.overlay_widget.hide()
                    current_card.overlay_widget.setWindowOpacity(0.0)
            except RuntimeError:
                pass
            CustomFileHorizontalCard._current_card_with_visible_buttons = None

    def _trigger_hover_animation(self):
        if not hasattr(self, "_style_colors"):
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

    def on_card_container_resize(self, event):
        self.overlay_widget.setGeometry(self.card_container.rect())
        self.overlay_widget.setMaximumWidth(self.card_container.width())
        self.overlay_widget.setMaximumHeight(self.card_container.height())

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._touch_start_pos = event.pos()
            self._is_touch_dragging = False
            if self._is_touch_optimization_enabled():
                self._long_press_timer.start(self._long_press_duration)
            self._drag_start_pos = event.globalPos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._is_dragging and self._drag_card:
            self._update_drag_card_position(event.globalPos())
            return
        if self._touch_start_pos is not None:
            delta = event.pos() - self._touch_start_pos
            if abs(delta.x()) > self._touch_drag_threshold or abs(delta.y()) > self._touch_drag_threshold:
                self._is_touch_dragging = True
                if not self._is_dragging:
                    self._long_press_timer.stop()
                    self._is_long_pressing = False
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self._is_dragging:
                self._end_drag(event.globalPos())
            elif self._is_long_pressing:
                self._cancel_drag()
            elif self._touch_start_pos is not None and not self._is_touch_dragging:
                self._long_press_timer.stop()
                self._is_long_pressing = False
                self.clicked.emit(self._file_path)
            else:
                self._long_press_timer.stop()
                self._is_long_pressing = False

            self._touch_start_pos = None
            self._is_touch_dragging = False
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.doubleClicked.emit(self._file_path)
            super().mouseDoubleClickEvent(event)

    @property
    def file_path(self):
        return self._file_path

    @file_path.setter
    def file_path(self, value):
        self.set_file_path(value)

    @property
    def is_selected(self):
        return self._is_selected

    @is_selected.setter
    def is_selected(self, value):
        self.set_selected(value)

    @property
    def thumbnail_mode(self):
        return self._thumbnail_mode

    @thumbnail_mode.setter
    def thumbnail_mode(self, value):
        self.set_thumbnail_mode(value)

    @property
    def enable_multiselect(self):
        return self._enable_multiselect

    @enable_multiselect.setter
    def enable_multiselect(self, value):
        self._enable_multiselect = value
        self.update_card_style()

    def set_enable_multiselect(self, enable):
        self.enable_multiselect = enable

    @property
    def single_line_mode(self):
        return self._single_line_mode

    @single_line_mode.setter
    def single_line_mode(self, value):
        self._single_line_mode = value
        if self._file_path:
            self._load_file_info()

    def set_single_line_mode(self, enable):
        self.single_line_mode = enable

    def _is_touch_optimization_enabled(self):
        try:
            settings_manager = SettingsManager()
            staging_setting = settings_manager.get_setting("file_staging.touch_optimization", None)
            if staging_setting is not None:
                return staging_setting
            return settings_manager.get_setting("file_selector.touch_optimization", True)
        except (OSError, IOError, PermissionError, FileNotFoundError) as e:
            debug(f"检查触控操作优化设置失败 - 文件操作错误: {e}")
            return True
        except (ValueError, TypeError, RuntimeError) as e:
            debug(f"检查触控操作优化设置失败 - 数据或运行时错误: {e}")
            return True

    def _on_long_press(self):
        self._is_long_pressing = True
        self._start_drag()

    def _start_drag(self):
        self._is_dragging = True
        self._set_dragging_appearance(True)
        self._create_drag_card()
        if self._file_info:
            self.drag_started.emit(self._file_info)
        self.setCursor(QCursor(Qt.ClosedHandCursor))
        self.grabMouse()

    def _set_dragging_appearance(self, is_dragging):
        self._drag_visual_active = bool(is_dragging)

        opacity = 0.4 if is_dragging else 1.0
        graphics_effect = self.icon_display.graphicsEffect()
        if graphics_effect is not None:
            graphics_effect.setEnabled(False)

        self.icon_display.setWindowOpacity(opacity)
        self.name_label.setWindowOpacity(opacity)
        self.info_label.setWindowOpacity(opacity)

        self._apply_text_palette()
        self._update_card_surface()

    def _create_drag_card(self):
        if self._drag_card:
            self._drag_card.deleteLater()

        pixmap = self._render_card_pixmap()
        self._drag_card = QLabel(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self._drag_card.setObjectName("DragCard")
        self._drag_card.setAttribute(Qt.WA_TranslucentBackground, True)
        self._drag_card.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._drag_card.setStyleSheet("background: transparent; border: none;")
        self._drag_card.setPixmap(pixmap)
        self._drag_card.resize(pixmap.size())

        cursor_pos = QCursor.pos()
        card_width = self._drag_card.width()
        card_height = self._drag_card.height()
        self._drag_card.move(cursor_pos.x() - card_width // 2, cursor_pos.y() - card_height // 2)
        self._drag_card.show()

    def _update_drag_card_position(self, global_pos):
        if self._drag_card:
            card_width = self._drag_card.width()
            card_height = self._drag_card.height()
            self._drag_card.move(global_pos.x() - card_width // 2, global_pos.y() - card_height // 2)

    def _end_drag(self, global_pos):
        self._set_dragging_appearance(False)
        self.setCursor(QCursor(Qt.ArrowCursor))

        drop_target = self._detect_drop_target(global_pos)
        if self._file_info:
            self.drag_ended.emit(self._file_info, drop_target)

        if self._drag_card:
            self._drag_card.deleteLater()
            self._drag_card = None

        self.releaseMouse()
        self._is_dragging = False
        self._is_long_pressing = False

    def _cancel_drag(self):
        self._set_dragging_appearance(False)
        self.setCursor(QCursor(Qt.ArrowCursor))

        if self._drag_card:
            self._drag_card.deleteLater()
            self._drag_card = None

        self.releaseMouse()
        self._is_dragging = False
        self._is_long_pressing = False
        self._long_press_timer.stop()

    def _detect_drop_target(self, global_pos):
        main_window = self.window()
        if not main_window:
            return "none"

        if hasattr(main_window, "file_selector_a"):
            file_selector = main_window.file_selector_a
            if file_selector and file_selector.isVisible():
                selector_top_left = file_selector.mapToGlobal(file_selector.rect().topLeft())
                selector_bottom_right = file_selector.mapToGlobal(file_selector.rect().bottomRight())
                from PySide6.QtCore import QRect as QtRect

                selector_global_rect = QtRect(selector_top_left, selector_bottom_right)
                if selector_global_rect.contains(global_pos):
                    return "file_selector"

        if hasattr(main_window, "unified_previewer"):
            previewer = main_window.unified_previewer
            if previewer and previewer.isVisible():
                previewer_top_left = previewer.mapToGlobal(previewer.rect().topLeft())
                previewer_bottom_right = previewer.mapToGlobal(previewer.rect().bottomRight())
                from PySide6.QtCore import QRect as QtRect

                previewer_global_rect = QtRect(previewer_top_left, previewer_bottom_right)
                if previewer_global_rect.contains(global_pos):
                    return "previewer"

        return "none"

    def is_dragging(self):
        return self._is_dragging

    def set_file_info(self, file_info):
        self._file_info = file_info

    def hideEvent(self, event):
        self._long_press_timer.stop()
        if self._drag_card:
            self._drag_card.hide()
            self._drag_card.deleteLater()
            self._drag_card = None
        self._stop_all_animations()
        super().hideEvent(event)

    def closeEvent(self, event):
        self._long_press_timer.stop()
        if self._drag_card:
            self._drag_card.hide()
            self._drag_card.deleteLater()
            self._drag_card = None
        self._stop_all_animations()
        super().closeEvent(event)

    def _format_size(self, size):
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.2f} KB"
        if size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.2f} MB"
        return f"{size / (1024 * 1024 * 1024):.2f} GB"

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

    def _safe_get_mtime(self, path):
        if not path:
            return None
        try:
            return os.path.getmtime(path)
        except (OSError, IOError, PermissionError, FileNotFoundError, RuntimeError, TypeError, ValueError):
            return None

    def _get_file_icon_path(self, suffix, is_dir=False):
        icon_dir = os.path.join(os.path.dirname(__file__), "..", "icons")

        if is_dir:
            icon_name = "文件夹"
        elif suffix in ["mp4", "mov", "avi", "mkv", "wmv", "flv", "webm", "m4v", "mpeg", "mpg", "mxf"]:
            icon_name = "视频"
        elif suffix in [
            "jpg", "jpeg", "png", "gif", "bmp", "webp", "tiff", "svg",
            "avif", "cr2", "cr3", "nef", "arw", "dng", "orf", "psd", "psb",
        ]:
            icon_name = "图像"
        elif suffix == "pdf":
            icon_name = "PDF"
        elif suffix in ["ppt", "pptx"]:
            icon_name = "PPT"
        elif suffix in ["xls", "xlsx"]:
            icon_name = "表格"
        elif suffix in ["doc", "docx"]:
            icon_name = "Word文档"
        elif suffix in ["txt", "md", "rtf"]:
            icon_name = "文档"
        elif suffix in ["ttf", "otf", "woff", "woff2", "eot"]:
            icon_name = "字体"
        elif suffix in ["mp3", "wav", "flac", "aac", "ogg", "m4a"]:
            icon_name = "音乐"
        elif suffix in ["zip", "rar", "7z", "tar", "gz", "bz2", "xz", "lzma", "iso", "cab", "arj"]:
            icon_name = "压缩文件"
        else:
            icon_name = "未知底板"

        return get_icon_path(icon_name, icon_dir)

    def _build_icon_source_signature(self):
        file_path = self._file_path or ""
        file_info = QFileInfo(file_path) if file_path else QFileInfo()
        is_dir = file_info.isDir() if file_path else False
        suffix = file_info.suffix().lower() if file_path else ""

        if not file_path:
            return ("empty",)

        if not is_dir and suffix in ["lnk", "exe", "url"]:
            file_mtime = self._safe_get_mtime(file_path)
            return ("system_icon", os.path.normpath(file_path), file_mtime)

        thumbnail_path = get_existing_thumbnail_path(file_path)
        is_photo = suffix in [
            "jpg", "jpeg", "png", "gif", "bmp", "webp", "tiff", "svg",
            "avif", "cr2", "cr3", "nef", "arw", "dng", "orf", "psd", "psb",
        ]
        is_video = suffix in ["mp4", "mov", "avi", "mkv", "wmv", "flv", "webm", "m4v", "mpeg", "mpg", "mxf"]

        if (is_photo or is_video) and thumbnail_path and os.path.exists(thumbnail_path):
            thumbnail_mtime = self._safe_get_mtime(thumbnail_path)
            return ("thumbnail", os.path.normpath(thumbnail_path), thumbnail_mtime)

        icon_path = self._get_file_icon_path(suffix, is_dir)
        icon_mtime = self._safe_get_mtime(icon_path) if icon_path and os.path.exists(icon_path) else None
        return ("file_icon", os.path.normpath(icon_path) if icon_path else "", icon_mtime)

    def _recenter_icon_pixmap(self, pixmap):
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
                        min_x = min(min_x, x)
                        min_y = min(min_y, y)
                        max_x = max(max_x, x)
                        max_y = max(max_y, y)

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
            debug(f"重居中横向卡片图标失败: {e}")
            return pixmap

    def _normalize_icon_pixmap(self, pixmap, icon_size):
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

            try:
                image = clean_pixmap.toImage()
                min_x = image.width()
                min_y = image.height()
                max_x = -1
                max_y = -1

                for y in range(image.height()):
                    for x in range(image.width()):
                        if QColor.fromRgba(image.pixel(x, y)).alpha() > 0:
                            min_x = min(min_x, x)
                            min_y = min(min_y, y)
                            max_x = max(max_x, x)
                            max_y = max(max_y, y)

                if max_x >= min_x and max_y >= min_y:
                    source_rect = QRect(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)
            except (RuntimeError, ValueError, TypeError) as crop_error:
                debug(f"裁切横向卡片图标透明边缘失败: {crop_error}")

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
            painter.drawPixmap(target_rect, clean_pixmap, QRectF(source_rect))
            painter.end()

            normalized.setDevicePixelRatio(output_dpr)
            return normalized
        except (RuntimeError, ValueError, TypeError) as e:
            debug(f"规范化横向卡片图标失败: {e}")
            fallback = QPixmap(icon_size, icon_size)
            fallback.fill(Qt.transparent)
            return fallback

    def _render_exact_svg_icon_pixmap(self, icon_path, icon_width, icon_height, replace_colors=True):
        pixmap = SvgRenderer.render_svg_to_exact_pixmap(
            icon_path,
            icon_width=icon_width,
            icon_height=icon_height,
            replace_colors=replace_colors,
            device_pixel_ratio=self._get_device_pixel_ratio(),
        )
        return self._recenter_icon_pixmap(pixmap)

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
        file_path = self._file_path or ""
        icon_size = int(40 * self.dpi_scale)
        if not file_path:
            pixmap = QPixmap(icon_size, icon_size)
            pixmap.fill(Qt.transparent)
            return pixmap

        try:
            file_info = QFileInfo(file_path)
            is_dir = file_info.isDir()
            suffix = file_info.suffix().lower()

            if not self._path_exists:
                icon_path = self._get_file_icon_path("", False)
                if icon_path and os.path.exists(icon_path):
                    return self._build_unknown_icon_pixmap(icon_path, "?", icon_size)

            if not is_dir and suffix in ["lnk", "exe", "url"]:
                try:
                    from freeassetfilter.utils.icon_utils import get_highest_resolution_icon, hicon_to_pixmap, DestroyIcon
                    from PySide6.QtGui import QGuiApplication

                    dpr = QGuiApplication.primaryScreen().devicePixelRatio()
                    hicon = get_highest_resolution_icon(file_path)
                    if hicon:
                        pixmap = hicon_to_pixmap(hicon, icon_size, None, dpr, keep_original_size=True)
                        DestroyIcon(hicon)
                        if pixmap and not pixmap.isNull():
                            return self._normalize_icon_pixmap(pixmap, icon_size)
                except (OSError, IOError, PermissionError, FileNotFoundError) as e:
                    debug(f"提取横向卡片系统图标失败 - 文件操作错误: {e}")
                except (ValueError, TypeError, RuntimeError) as e:
                    debug(f"提取横向卡片系统图标失败 - 数据或运行时错误: {e}")

            thumbnail_path = get_existing_thumbnail_path(file_path)
            if not thumbnail_path:
                thumbnail_manager = get_thumbnail_manager(self.dpi_scale)
                thumbnail_path = thumbnail_manager.get_thumbnail_path(file_path)

            is_photo = suffix in [
                "jpg", "jpeg", "png", "gif", "bmp", "webp", "tiff", "avif",
                "cr2", "cr3", "nef", "arw", "dng", "orf", "psd", "psb", "svg",
            ]
            is_video = suffix in ["mp4", "mov", "avi", "mkv", "wmv", "flv", "webm", "m4v", "mpeg", "mpg", "mxf"]

            if (is_photo or is_video) and thumbnail_path and os.path.exists(thumbnail_path):
                pixmap = QPixmap(thumbnail_path)
                if not pixmap.isNull():
                    return self._normalize_icon_pixmap(pixmap, icon_size)

            icon_path = self._get_file_icon_path(suffix, is_dir)
            if icon_path and os.path.exists(icon_path):
                if "未知底板" in os.path.basename(icon_path):
                    display_suffix = suffix.upper()
                    if len(display_suffix) >= 5:
                        display_suffix = "FILE"
                    return self._build_unknown_icon_pixmap(icon_path, display_suffix or "?", icon_size)

                if "压缩文件" in os.path.basename(icon_path):
                    display_suffix = "." + suffix if suffix else ""
                    return self._build_unknown_icon_pixmap(icon_path, display_suffix, icon_size)

                return self._render_exact_svg_icon_pixmap(
                    icon_path,
                    icon_size,
                    icon_size,
                    replace_colors=True,
                )
        except (OSError, IOError, PermissionError, FileNotFoundError) as e:
            error(f"构建横向卡片图标失败 - 文件操作错误: {e}")
        except (ValueError, TypeError, RuntimeError) as e:
            error(f"构建横向卡片图标失败 - 数据或运行时错误: {e}")

        fallback = QPixmap(icon_size, icon_size)
        fallback.fill(Qt.transparent)
        return fallback

    def _update_icon(self, force=False):
        file_path = self._file_path or ""
        file_info = QFileInfo(file_path) if file_path else QFileInfo()
        suffix = file_info.suffix().lower() if file_path else ""
        icon_size = int(40 * self.dpi_scale)
        device_pixel_ratio = round(self._get_device_pixel_ratio(), 4)
        icon_source_signature = self._build_icon_source_signature()

        cache_key = (
            file_path,
            file_info.isDir() if file_path else False,
            suffix,
            icon_size,
            self.dpi_scale,
            device_pixel_ratio,
            self.base_color,
            self.auxiliary_color,
            self.normal_color,
            self.accent_color,
            self.secondary_color,
            self._path_exists,
            icon_source_signature,
        )

        if not force and self._icon_cache_key == cache_key and not self._icon_pixmap.isNull():
            return

        self._icon_cache_key = cache_key
        cached = CustomFileHorizontalCard._icon_cache.get(cache_key)
        if cached is not None and not cached.isNull():
            self._icon_pixmap = cached
            self._set_icon_pixmap(self._icon_pixmap, icon_size)
            return

        self._icon_pixmap = self._build_icon_pixmap()
        if not self._icon_pixmap.isNull():
            CustomFileHorizontalCard._icon_cache[cache_key] = self._icon_pixmap

        self._set_icon_pixmap(self._icon_pixmap, icon_size)

    def _set_icon_pixmap(self, pixmap, size):
        logical_size = int(size)
        if logical_size > 0:
            self.icon_display.setFixedSize(logical_size, logical_size)
            self.icon_display.setAlignment(Qt.AlignCenter)
            if pixmap and not pixmap.isNull():
                self.icon_display.setPixmap(pixmap)
            else:
                blank = QPixmap(logical_size, logical_size)
                blank.fill(Qt.transparent)
                self.icon_display.setPixmap(blank)

    def _darken_or_lighten_color(self, color_hex, amount=30):
        try:
            app = QApplication.instance()
            if hasattr(app, "settings_manager"):
                settings_manager = app.settings_manager
            else:
                settings_manager = SettingsManager()
            current_theme = settings_manager.get_setting("appearance.theme", "default")
            is_dark_mode = current_theme == "dark"
        except (OSError, IOError, PermissionError, FileNotFoundError, ValueError, TypeError, RuntimeError):
            is_dark_mode = False

        color = color_hex.lstrip("#")
        r = int(color[0:2], 16)
        g = int(color[2:4], 16)
        b = int(color[4:6], 16)

        if is_dark_mode:
            r = min(255, r + int(255 * amount / 100))
            g = min(255, g + int(255 * amount / 100))
            b = min(255, b + int(255 * amount / 100))
        else:
            r = max(0, r - int(255 * amount / 100))
            g = max(0, g - int(255 * amount / 100))
            b = max(0, b - int(255 * amount / 100))

        return f"#{r:02x}{g:02x}{b:02x}"
