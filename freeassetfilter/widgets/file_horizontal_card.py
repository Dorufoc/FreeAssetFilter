#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0
Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>
协议说明：本软件基于 MIT 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；
项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE
自定义文件横向卡片组件
采用左右结构布局，左侧为缩略图/图标，右侧为文字信息
"""
import os
import sys
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QSizePolicy, QStackedLayout
)
from .button_widgets import CustomButton
from PyQt5.QtCore import (
    Qt, pyqtSignal, QFileInfo, QEvent, QPropertyAnimation, QEasingCurve, pyqtProperty, QParallelAnimationGroup
)
from PyQt5.QtGui import (
    QFont, QFontMetrics, QPixmap, QColor
)
from PyQt5.QtSvg import QSvgWidget
# 导入悬浮详细信息组件
from .hover_tooltip import HoverTooltip
# 添加项目根目录到Python路径
sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
)
from freeassetfilter.core.svg_renderer import SvgRenderer  # noqa: E402 模块级别的导入不在文件顶部（需要先添加路径）


class CustomFileHorizontalCard(QWidget):
    """
    自定义文件横向卡片组件
    
    信号：
        clicked (str): 鼠标单击事件，传递文件路径
        doubleClicked (str): 鼠标双击事件，传递文件路径
        selectionChanged (bool, str): 选中状态改变事件，传递选中状态和文件路径
    
    属性：
        file_path (str): 文件路径
        is_selected (bool): 是否选中
        thumbnail_mode (str): 缩略图显示模式，可选值：'icon' 或 'custom'
        dpi_scale (float): DPI缩放因子
        enable_multiselect (bool): 是否开启多选功能
        single_line_mode (bool): 是否使用单行文本格式
    
    方法：
        set_file_path(file_path): 设置文件路径
        set_selected(selected): 设置选中状态
        set_thumbnail_mode(mode): 设置缩略图显示模式
        set_enable_multiselect(enable): 设置是否开启多选功能
        set_single_line_mode(enable): 设置是否使用单行文本格式
    
    参数：
        file_path (str): 文件路径
        parent (QWidget): 父部件
        enable_multiselect (bool): 是否开启多选功能，默认值为True
        single_line_mode (bool): 是否使用单行文本格式，默认值为False
    """
    # 信号定义
    clicked = pyqtSignal(str)
    doubleClicked = pyqtSignal(str)
    selectionChanged = pyqtSignal(bool, str)
    renameRequested = pyqtSignal(str)  # 重命名请求信号，传递文件路径
    deleteRequested = pyqtSignal(str)  # 删除请求信号，传递文件路径
    
    @pyqtProperty(QColor)
    def anim_bg_color(self):
        return self._anim_bg_color
    
    @anim_bg_color.setter
    def anim_bg_color(self, color):
        self._anim_bg_color = color
        self._apply_animated_style()
    
    @pyqtProperty(QColor)
    def anim_border_color(self):
        return self._anim_border_color
    
    @anim_border_color.setter
    def anim_border_color(self, color):
        self._anim_border_color = color
        self._apply_animated_style()
    
    def _apply_animated_style(self):
        """应用动画颜色到卡片样式"""
        if not hasattr(self, '_style_colors'):
            return
        
        scaled_border_width = int(1 * self.dpi_scale)
        scaled_border_radius = int(8 * self.dpi_scale)
        
        r, g, b, a = self._anim_bg_color.red(), self._anim_bg_color.green(), self._anim_bg_color.blue(), self._anim_bg_color.alpha()
        bg_color = f"rgba({r}, {g}, {b}, {a})"
        border_color = self._anim_border_color.name()
        
        card_style = ""
        card_style += "QWidget {"
        card_style += f"background-color: {bg_color};"
        card_style += f"border: {scaled_border_width}px solid {border_color};"
        card_style += f"border-radius: {scaled_border_radius}px;"
        card_style += "}"
        self.card_container.setStyleSheet(card_style)

    def __init__(self, file_path=None, parent=None, enable_multiselect=True, display_name=None, single_line_mode=False):
        super().__init__(parent)
        
        # 获取应用实例和DPI缩放因子
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        # 获取全局字体
        self.global_font = getattr(app, 'global_font', QFont())
        
        # 设置组件字体
        self.setFont(self.global_font)
        
        # 初始化属性
        self._file_path = file_path
        self._is_selected = False
        self._thumbnail_mode = 'icon'  # 默认使用icon模式
        self._enable_multiselect = enable_multiselect  # 是否开启多选功能
        self._display_name = display_name  # 显示名称，优先于文件系统中的文件名
        self._single_line_mode = single_line_mode  # 是否使用单行文本格式
        self._path_exists = True  # 路径是否存在，用于收藏夹中标记已删除的路径

        # 鼠标悬停标志，用于跟踪鼠标是否在卡片区域内
        self._is_mouse_over = False
        
        self._touch_drag_threshold = int(10 * self.dpi_scale)
        self._touch_start_pos = None
        self._is_touch_dragging = False
        
        # 初始化UI
        self.init_ui()
        
        # 初始化悬浮详细信息组件
        self.hover_tooltip = HoverTooltip(self)
        self.hover_tooltip.set_target_widget(self.card_container)
        
        # 如果提供了文件路径，加载文件信息
        if file_path:
            self.set_file_path(file_path, display_name)

    def init_ui(self):
        """初始化用户界面"""
        # 设置组件大小策略，允许自由调整宽度和高度，确保能随窗口缩小
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumWidth(0)  # 移除最小宽度限制
        # 创建主布局（垂直布局）
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 创建卡片容器（底层白色圆角矩形）
        self.card_container = QWidget()
        # 设置卡片容器大小策略，确保能随窗口缩小
        self.card_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.card_container.setMinimumWidth(0)  # 移除最小宽度限制
        self.card_container.setStyleSheet("background: transparent; border: none;")
        
        # 创建卡片内容布局
        card_content_layout = QHBoxLayout(self.card_container)
        card_content_layout.setSpacing(int(7.5 * self.dpi_scale))
        # 增加上下高度尺寸，设置为更大的数值
        min_height_margin = int(6.25 * self.dpi_scale)
        card_content_layout.setContentsMargins(
            int(7.5 * self.dpi_scale),
            min_height_margin,
            int(7.5 * self.dpi_scale),
            min_height_margin
        )
        card_content_layout.setAlignment(Qt.AlignVCenter)
        
        # 缩略图/图标显示组件
        self.icon_display = QLabel()
        self.icon_display.setAlignment(Qt.AlignCenter)
        self.icon_display.setFixedSize(int(20 * self.dpi_scale), int(20 * self.dpi_scale))
        self.icon_display.setStyleSheet('background: transparent; border: none;')
        card_content_layout.addWidget(self.icon_display, alignment=Qt.AlignVCenter)
        
        # 文字信息区
        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        
        # 根据单行模式设置间距
        if self._single_line_mode:
            text_layout.setSpacing(0)  # 单行模式下无间距
        else:
            text_layout.setSpacing(int(4 * self.dpi_scale))  # 默认垂直间距
            
        text_layout.setAlignment(Qt.AlignVCenter)
        
        # 文件名标签
        self.name_label = QLabel()
        self.name_label.setAlignment(Qt.AlignLeft)
        self.name_label.setWordWrap(False)
        # 设置最小宽度为0，允许自由收缩
        self.name_label.setMinimumWidth(0)
        # 忽略文字自然长度，允许自由收缩
        self.name_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        # 设置字体大小和粗细
        name_font = QFont(self.global_font)
        name_font.setBold(True)  # 字重600
        self.name_label.setFont(name_font)
        # 初始设置默认样式，后续会在update_card_style中更新为主题颜色
        self.name_label.setStyleSheet("background: transparent; border: none;")
        text_layout.addWidget(self.name_label)
        
        # 文件信息标签
        self.info_label = QLabel()
        self.info_label.setAlignment(Qt.AlignLeft)
        self.info_label.setWordWrap(False)
        # 设置最小宽度为0，允许自由收缩
        self.info_label.setMinimumWidth(0)
        # 忽略文字自然长度，允许自由收缩
        self.info_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        # 设置字体大小
        info_font = QFont(self.global_font)
        info_font.setWeight(QFont.Normal)  # 设置为正常字重
        self.info_label.setFont(info_font)
        # 初始设置默认样式，后续会在update_card_style中更新为主题颜色
        self.info_label.setStyleSheet("background: transparent; border: none;")
        
        # 根据单行模式决定是否显示文件信息标签
        if not self._single_line_mode:
            text_layout.addWidget(self.info_label)
        
        card_content_layout.addLayout(text_layout, 1)
        
        # 创建覆盖层布局（用于放置功能按钮）
        self.overlay_widget = QWidget(self.card_container)
        self.overlay_widget.setStyleSheet("background: transparent; border: none;")
        # 确保覆盖层大小始终与卡片容器一致
        self.overlay_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.overlay_widget.setGeometry(self.card_container.rect())
        
        # 设置覆盖层布局
        overlay_layout = QHBoxLayout(self.overlay_widget)
        # 使用与卡片内容布局相同的上下边距
        min_height_margin = int(6.25 * self.dpi_scale)
        overlay_layout.setContentsMargins(
            int(2.5 * self.dpi_scale),
            min_height_margin,
            int(2.5 * self.dpi_scale),
            min_height_margin
        )
        overlay_layout.setSpacing(int(2.5 * self.dpi_scale))
        # 右对齐，确保按钮始终在右侧
        overlay_layout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        
        # 创建两个功能按钮，使用默认大小
        self.button1 = CustomButton(
            "重命名",
            parent=self.overlay_widget,
            button_type="primary",
            display_mode="text"
        )
        self.button2 = CustomButton(
            "删除",
            parent=self.overlay_widget,
            button_type="warning",
            display_mode="text"
        )
        
        # 确保按钮不会超出显示区域
        self.button1.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.button2.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        
        # 在按钮左侧添加伸展因子，确保按钮始终靠右显示，不会超出显示区域
        overlay_layout.addStretch(1)
        
        # 添加按钮到覆盖层布局
        overlay_layout.addWidget(self.button1)
        overlay_layout.addWidget(self.button2)
        
        # 连接按钮信号
        self.button1.clicked.connect(lambda: self.renameRequested.emit(self._file_path))
        self.button2.clicked.connect(lambda: self.deleteRequested.emit(self._file_path))
        
        # 添加卡片容器到主布局
        main_layout.addWidget(self.card_container)
        
        # 初始隐藏覆盖层（完全隐藏，不显示）
        self.overlay_widget.setWindowOpacity(0.0)
        self.overlay_widget.hide()
        
        # 连接resizeEvent，确保覆盖层始终覆盖整个卡片容器
        self.card_container.resizeEvent = self.on_card_container_resize
        # 初始化动画
        self._init_animations()
        # 初始化卡片样式
        self.update_card_style()
        
        # 为卡片容器和覆盖层添加事件过滤器，用于处理鼠标悬停事件
        self.card_container.installEventFilter(self)
        self.overlay_widget.installEventFilter(self)

    def set_file_path(self, file_path, display_name=None):
        """
        设置文件路径并更新显示
        参数：
            file_path (str): 文件路径
            display_name (str, optional): 显示名称，优先于文件系统中的文件名
        """
        self._file_path = file_path
        if display_name is not None:
            self._display_name = display_name
        self._load_file_info()
        self._set_file_icon()

    def set_path_exists(self, exists):
        """
        设置路径是否存在状态
        用于收藏夹中标记已删除或移动的路径

        参数：
            exists (bool): 路径是否存在
        """
        self._path_exists = exists
        self._load_file_info()
        self._set_file_icon()

    def set_selected(self, selected):
        """
        设置选中状态
        
        参数：
            selected (bool): 是否选中
        """
        if self._enable_multiselect:
            if self._is_selected != selected:
                self._is_selected = selected
                if selected:
                    self._trigger_select_animation()
                else:
                    self._trigger_deselect_animation()
                self.selectionChanged.emit(selected, self._file_path)
    
    def _trigger_select_animation(self):
        """触发选中动画"""
        if not hasattr(self, '_style_colors'):
            self.update_card_style()
            return
        
        self._hover_anim_group.stop()
        self._leave_anim_group.stop()
        
        colors = self._style_colors
        self._anim_select_bg.setStartValue(self._anim_bg_color)
        self._anim_select_bg.setEndValue(colors['selected_bg'])
        self._anim_select_border.setStartValue(self._anim_border_color)
        self._anim_select_border.setEndValue(colors['selected_border'])
        self._select_anim_group.start()
    
    def _trigger_deselect_animation(self):
        """触发取消选中动画"""
        if not hasattr(self, '_style_colors'):
            self.update_card_style()
            return
        
        self._select_anim_group.stop()
        
        colors = self._style_colors
        self._anim_deselect_bg.setStartValue(self._anim_bg_color)
        self._anim_deselect_bg.setEndValue(colors['normal_bg'])
        self._anim_deselect_border.setStartValue(self._anim_border_color)
        self._anim_deselect_border.setEndValue(colors['normal_border'])
        self._deselect_anim_group.start()

    def set_thumbnail_mode(self, mode):
        """
        设置缩略图显示模式
        参数：
            mode (str): 显示模式，可选值：'icon' 或 'custom'
        """
        if mode in ['icon', 'custom']:
            self._thumbnail_mode = mode
            self._set_file_icon()

    def refresh_thumbnail(self):
        """刷新缩略图显示"""
        print(f"[DEBUG] CustomFileHorizontalCard.refresh_thumbnail 被调用: {self._file_path}")
        self._set_file_icon()

    def _load_file_info(self):
        """
        加载文件信息
        """
        if not self._file_path:
            return

        try:
            # 获取设置中的颜色
            from freeassetfilter.core.settings_manager import SettingsManager
            settings_manager = SettingsManager()
            normal_color = settings_manager.get_setting("appearance.colors.normal_color", "#808080")
            secondary_color = settings_manager.get_setting("appearance.colors.secondary_color", "#333333")

            # 如果路径不存在，显示删除线效果和提示文字
            if not self._path_exists:
                # 优先使用_display_name
                if hasattr(self, '_display_name') and self._display_name:
                    file_name = self._display_name
                else:
                    file_name = os.path.basename(self._file_path)

                # 获取当前组件宽度
                component_width = self.width()
                if component_width <= 0:
                    component_width = int(87.5 * self.dpi_scale)

                # 计算可用宽度
                name_font_metrics = QFontMetrics(self.name_label.font())
                icon_margin = int(10 * self.dpi_scale)
                available_width = max(0, component_width - icon_margin)

                # 添加删除线效果和（已移动或删除）后缀
                display_name = f"{file_name}（已移动或删除）"
                elided_name = name_font_metrics.elidedText(display_name, Qt.ElideRight, available_width)

                # 设置带删除线的样式，使用normal_color（灰色）
                self.name_label.setText(elided_name)
                self.name_label.setStyleSheet(f"background: transparent; border: none; text-decoration: line-through; color: {normal_color};")

                # 显示路径信息，使用normal_color（灰色）
                info_text = self._file_path
                info_font_metrics = QFontMetrics(self.info_label.font())
                elided_info = info_font_metrics.elidedText(info_text, Qt.ElideRight, available_width)
                self.info_label.setText(elided_info)
                self.info_label.setStyleSheet(f"background: transparent; border: none; color: {normal_color};")
                self.info_label.show()
                return

            file_info = QFileInfo(self._file_path)

            # 优先使用_display_name，否则从文件系统获取文件名
            if hasattr(self, '_display_name') and self._display_name:
                file_name = self._display_name
            else:
                file_name = file_info.fileName()

            # 获取文件路径
            file_path = file_info.absoluteFilePath()

            # 获取文件大小
            if file_info.isDir():
                file_size = "文件夹"
            else:
                file_size = self._format_size(file_info.size())

            # 计算文本宽度，设置自动截断
            # 获取当前组件宽度作为参考（减去图标和边距）
            component_width = self.width()
            # 调试信息：打印组件宽度
            print(f"_load_file_info called, component_width: {component_width}")
            if component_width <= 0:
                # 如果组件宽度还未计算，使用一个默认值
                component_width = int(87.5 * self.dpi_scale)
                print(f"Using default component_width: {component_width}")

            # 文件名截断处理
            name_font_metrics = QFontMetrics(self.name_label.font())
            # 留一些边距和图标的宽度
            icon_margin = int(10 * self.dpi_scale)
            available_width = component_width - icon_margin  # 图标宽度 + 边距
            # 调试信息：打印可用宽度计算
            print(f"icon_margin: {icon_margin}, available_width: {available_width}")
            if available_width < 0:
                available_width = 0
                print(f"available_width < 0, setting to 0")

            # 调试信息：打印文字截断前的完整文本
            print(f"Original file name: '{file_name}'")

            elided_file_name = name_font_metrics.elidedText(file_name, Qt.ElideRight, available_width)

            # 文件信息截断处理
            info_text = f"{file_path}  {file_size}"

            # 调试信息：打印文字截断前的完整文本
            print(f"Original info text: '{info_text}'")
            info_font_metrics = QFontMetrics(self.info_label.font())
            elided_info_text = info_font_metrics.elidedText(info_text, Qt.ElideRight, available_width)

            # 调试信息：打印截断后的文本
            print(f"Elided file name: '{elided_file_name}'")
            print(f"Elided info text: '{elided_info_text}'")

            # 恢复默认样式，使用secondary_color
            self.name_label.setStyleSheet(f"background: transparent; border: none; color: {secondary_color};")
            self.info_label.setStyleSheet(f"background: transparent; border: none; color: {secondary_color};")

            # 根据单行模式更新标签文本
            if self._single_line_mode:
                # 单行模式下，将文件信息合并到文件名标签中
                combined_text = f"{file_name} ({file_size})"
                # 计算合并文本的截断显示
                combined_elided_text = name_font_metrics.elidedText(combined_text, Qt.ElideRight, available_width)
                self.name_label.setText(combined_elided_text)
                # 隐藏文件信息标签
                self.info_label.hide()
            else:
                # 多行模式下，分别显示文件名和文件信息
                self.name_label.setText(elided_file_name)
                self.info_label.setText(elided_info_text)
                # 显示文件信息标签
                self.info_label.show()

        except Exception as e:
            print(f"加载文件信息失败: {e}")

    def _set_file_icon(self):
        """设置文件图标或缩略图"""
        if not self._file_path:
            return
        try:
            # 如果路径不存在，显示未知图标底板+?符号
            if not self._path_exists:
                scaled_icon_size = int(40 * self.dpi_scale)
                icon_dir = os.path.join(os.path.dirname(__file__), '..', 'icons')
                unknown_icon_path = os.path.join(icon_dir, "未知底板.svg")
                if os.path.exists(unknown_icon_path):
                    svg_widget = SvgRenderer.render_unknown_file_icon(unknown_icon_path, "?", scaled_icon_size, self.dpi_scale)
                    if isinstance(svg_widget, (QSvgWidget, QLabel, QWidget)):
                        for child in self.icon_display.findChildren((QLabel, QSvgWidget, QWidget)):
                            child.deleteLater()
                        svg_widget.setParent(self.card_container)
                        svg_widget.setFixedSize(scaled_icon_size, scaled_icon_size)
                        svg_widget.setStyleSheet("background: transparent; border: none; padding: 0; margin: 0;")
                        svg_widget.setAttribute(Qt.WA_TranslucentBackground, True)
                        svg_widget.show()
                        self.card_container.layout().removeWidget(self.icon_display)
                        if isinstance(self.icon_display, QLabel):
                            self.icon_display.deleteLater()
                        self.icon_display = svg_widget
                        self.card_container.layout().insertWidget(0, self.icon_display, alignment=Qt.AlignVCenter)
                return

            file_info = QFileInfo(self._file_path)
            suffix = file_info.suffix().lower()

            if suffix in ["lnk", "exe", "url"]:
                scaled_icon_size = int(40 * self.dpi_scale)

                file_path = self._file_path

                try:
                    from freeassetfilter.utils.icon_utils import get_highest_resolution_icon, hicon_to_pixmap, DestroyIcon
                    hicon = get_highest_resolution_icon(file_path, desired_size=256)
                    if hicon:
                        pixmap = hicon_to_pixmap(hicon, scaled_icon_size, None)
                        DestroyIcon(hicon)

                        if pixmap and not pixmap.isNull():
                            self._set_icon_pixmap(pixmap, scaled_icon_size)
                            return
                except Exception:
                    pass

                from PyQt5.QtWidgets import QFileIconProvider
                icon_provider = QFileIconProvider()
                icon = icon_provider.icon(file_info)

                available_sizes = icon.availableSizes()
                if available_sizes:
                    max_size = max(available_sizes, key=lambda s: s.width() * s.height())
                    max_width, max_height = max_size.width(), max_size.height()
                else:
                    max_width = max_height = 4096

                high_res_pixmap = icon.pixmap(max_width, max_height)

                if not high_res_pixmap.isNull():
                    self._set_icon_pixmap(high_res_pixmap, scaled_icon_size)
                    return

            import hashlib
            thumb_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data", "thumbnails")
            md5_hash = hashlib.md5(self._file_path.encode('utf-8'))
            file_hash = md5_hash.hexdigest()[:16]
            thumbnail_path = os.path.join(thumb_dir, f"{file_hash}.png")

            is_photo = suffix in ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'tiff', 'avif', 'cr2', 'cr3', 'nef', 'arw', 'dng', 'orf']
            is_video = suffix in ['mp4', 'mov', 'avi', 'mkv', 'wmv', 'flv', 'webm', 'm4v', 'mpeg', 'mpg', 'mxf']

            print(f"[DEBUG] _set_file_icon: file={self._file_path}, suffix={suffix}, is_photo={is_photo}, is_video={is_video}")
            print(f"[DEBUG] thumbnail_path={thumbnail_path}, exists={os.path.exists(thumbnail_path)}")

            use_thumbnail = False
            if (is_photo or is_video) and os.path.exists(thumbnail_path):
                use_thumbnail = True

            if use_thumbnail:
                scaled_icon_size = int(40 * self.dpi_scale)
                from PyQt5.QtGui import QImage
                image = QImage(thumbnail_path)
                print(f"[DEBUG] QImage加载结果: isNull={image.isNull()}")
                if not image.isNull():
                    pixmap = QPixmap.fromImage(image)
                    print(f"[DEBUG] 成功加载缩略图: {thumbnail_path}")
                    self._set_icon_pixmap(pixmap, scaled_icon_size)
                    return

            icon_path = self._get_file_icon_path(suffix, file_info.isDir())
            if icon_path and os.path.exists(icon_path):
                scaled_icon_size = int(40 * self.dpi_scale)

                if icon_path.endswith("未知底板.svg") or icon_path.endswith("压缩文件.svg"):
                    if icon_path.endswith("压缩文件.svg"):
                        display_suffix = "." + file_info.suffix()
                    else:
                        display_suffix = file_info.suffix().upper()
                        if len(display_suffix) > 5:
                            display_suffix = "FILE"

                    svg_widget = SvgRenderer.render_unknown_file_icon(icon_path, display_suffix, scaled_icon_size, self.dpi_scale)
                else:
                    svg_widget = SvgRenderer.render_svg_to_widget(icon_path, scaled_icon_size, self.dpi_scale)
                
                if isinstance(svg_widget, QSvgWidget):
                    for child in self.icon_display.findChildren((QLabel, QSvgWidget)):
                        child.deleteLater()
                    svg_widget.setParent(self.card_container)
                    svg_widget.setFixedSize(scaled_icon_size, scaled_icon_size)
                    svg_widget.setStyleSheet("background: transparent; border: none; padding: 0; margin: 0;")
                    svg_widget.setAttribute(Qt.WA_TranslucentBackground, True)
                    svg_widget.show()
                elif isinstance(svg_widget, QLabel):
                    for child in self.icon_display.findChildren((QLabel, QSvgWidget)):
                        child.deleteLater()
                    svg_widget.setParent(self.card_container)
                    svg_widget.setFixedSize(scaled_icon_size, scaled_icon_size)
                    svg_widget.setStyleSheet("background: transparent; border: none; padding: 0; margin: 0;")
                    svg_widget.setAttribute(Qt.WA_TranslucentBackground, True)
                    svg_widget.show()
                elif isinstance(svg_widget, QWidget):
                    for child in self.icon_display.findChildren((QLabel, QSvgWidget, QWidget)):
                        child.deleteLater()
                    svg_widget.setParent(self.card_container)
                    svg_widget.setFixedSize(scaled_icon_size, scaled_icon_size)
                    svg_widget.setStyleSheet("background: transparent; border: none; padding: 0; margin: 0;")
                    svg_widget.setAttribute(Qt.WA_TranslucentBackground, True)
                    svg_widget.show()
                else:
                    self._set_default_icon()
                
                if isinstance(svg_widget, (QSvgWidget, QLabel, QWidget)) and svg_widget.parent() == self.card_container:
                    self.card_container.layout().removeWidget(self.icon_display)
                    if isinstance(self.icon_display, QLabel):
                        self.icon_display.deleteLater()
                    self.icon_display = svg_widget
                    self.card_container.layout().insertWidget(0, self.icon_display, alignment=Qt.AlignVCenter)
            else:
                self._set_default_icon()
        except Exception as e:
            print(f"设置文件图标失败: {e}")

    def _get_file_icon_path(self, suffix, is_dir=False):
        """获取文件图标路径"""
        icon_dir = os.path.join(os.path.dirname(__file__), '..', 'icons')
        if is_dir:
            return os.path.join(icon_dir, "文件夹.svg")
        # 根据文件后缀返回对应的图标路径
        icon_map = {
            # 视频格式
            'mp4': '视频.svg', 'mov': '视频.svg', 'avi': '视频.svg',
            'mkv': '视频.svg', 'wmv': '视频.svg', 'flv': '视频.svg',
            'webm': '视频.svg', 'm4v': '视频.svg', 'mpeg': '视频.svg',
            'mpg': '视频.svg', 'mxf': '视频.svg',
            # 图片格式
            'jpg': '图像.svg', 'jpeg': '图像.svg', 'png': '图像.svg',
            'gif': '图像.svg', 'bmp': '图像.svg', 'webp': '图像.svg',
            'tiff': '图像.svg', 'svg': '图像.svg', 'avif': '图像.svg',
            'cr2': '图像.svg', 'cr3': '图像.svg', 'nef': '图像.svg',
            'arw': '图像.svg', 'dng': '图像.svg', 'orf': '图像.svg',
            # 文档格式
            'pdf': 'PDF.svg', 'ppt': 'PPT.svg', 'pptx': 'PPT.svg',
            'xls': '表格.svg', 'xlsx': '表格.svg',
            'doc': 'Word文档.svg', 'docx': 'Word文档.svg',
            'txt': '文档.svg', 'md': '文档.svg', 'rtf': '文档.svg',
            # 字体格式
            'ttf': '字体.svg', 'otf': '字体.svg', 'woff': '字体.svg',
            'woff2': '字体.svg', 'eot': '字体.svg',
            # 音频格式
            'mp3': '音乐.svg', 'wav': '音乐.svg', 'flac': '音乐.svg',
            'aac': '音乐.svg', 'ogg': '音乐.svg', 'm4a': '音乐.svg',
            # 压缩文件格式
            'zip': '压缩文件.svg', 'rar': '压缩文件.svg', '7z': '压缩文件.svg',
            'tar': '压缩文件.svg', 'gz': '压缩文件.svg', 'bz2': '压缩文件.svg',
        }
        return os.path.join(icon_dir, icon_map.get(suffix, "未知底板.svg"))

    def _set_icon_pixmap(self, pixmap, size):
        """设置图标Pixmap"""
        logical_size = int(size)
        physical_size = int(size * self.devicePixelRatio())
        if logical_size > 0 and physical_size > 0:
            if not isinstance(self.icon_display, QLabel):
                self._create_icon_label()
            
            self.icon_display.setFixedSize(logical_size, logical_size)
            
            self.icon_display.clear()
            
            scaled_pixmap = pixmap.scaled(physical_size, physical_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            scaled_pixmap.setDevicePixelRatio(self.devicePixelRatio())
            self.icon_display.setPixmap(scaled_pixmap)

    def _create_icon_label(self):
        """创建新的QLabel用于显示图标"""
        old_icon_display = self.icon_display
        
        if old_icon_display.parent() == self.card_container:
            card_layout = self.card_container.layout()
            card_layout.removeWidget(old_icon_display)
        
        old_icon_display.hide()
        
        def recursive_delete(widget):
            """递归删除所有子组件"""
            for child in widget.findChildren((QLabel, QSvgWidget, QWidget)):
                if child.parent() == widget:
                    recursive_delete(child)
                    child.hide()
                    child.deleteLater()
        
        recursive_delete(old_icon_display)
        old_icon_display.deleteLater()
        
        self.icon_display = QLabel()
        self.icon_display.setAlignment(Qt.AlignCenter)
        self.icon_display.setFixedSize(old_icon_display.size())
        self.icon_display.setStyleSheet('background: transparent; border: none;')
        
        card_layout = self.card_container.layout()
        card_layout.insertWidget(0, self.icon_display, alignment=Qt.AlignVCenter)
        self.icon_display.show()

    def _set_default_icon(self):
        """设置默认图标"""
        pixmap = QPixmap(self.icon_display.size())
        pixmap.fill(Qt.transparent)
        self.icon_display.setPixmap(pixmap)

    def _format_size(self, size):
        """格式化文件大小"""
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.2f} KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.2f} MB"
        else:
            return f"{size / (1024 * 1024 * 1024):.2f} GB"
    
    def _init_animations(self):
        """初始化卡片状态切换动画"""
        from PyQt5.QtWidgets import QApplication
        from freeassetfilter.core.settings_manager import SettingsManager
        
        app = QApplication.instance()
        if hasattr(app, 'settings_manager'):
            settings_manager = app.settings_manager
        else:
            settings_manager = SettingsManager()
        
        accent_color_hex = settings_manager.get_setting("appearance.colors.accent_color", "#1890ff")
        base_color_hex = settings_manager.get_setting("appearance.colors.base_color", "#ffffff")
        normal_color_hex = settings_manager.get_setting("appearance.colors.normal_color", "#e0e0e0")
        secondary_color_hex = settings_manager.get_setting("appearance.colors.secondary_color", "#333333")
        auxiliary_color_hex = settings_manager.get_setting("appearance.colors.auxiliary_color", "#f0f8ff")
        
        accent_qcolor = QColor(accent_color_hex)
        base_qcolor = QColor(base_color_hex)
        normal_qcolor = QColor(normal_color_hex)
        auxiliary_qcolor = QColor(auxiliary_color_hex)
        
        normal_bg = QColor(base_qcolor)
        hover_bg = QColor(auxiliary_qcolor)
        selected_bg = QColor(accent_qcolor)
        selected_bg.setAlpha(102)
        normal_border = QColor(auxiliary_qcolor)
        hover_border = QColor(normal_qcolor)
        selected_border = QColor(accent_qcolor)
        
        self._style_colors = {
            'normal_bg': normal_bg,
            'hover_bg': hover_bg,
            'selected_bg': selected_bg,
            'normal_border': normal_border,
            'hover_border': hover_border,
            'selected_border': selected_border
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
        
        self._apply_animated_style()
    
    def update_card_style(self):
        """更新卡片样式"""
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtGui import QColor
        
        scaled_border_width = int(1 * self.dpi_scale)
        scaled_border_radius = int(8 * self.dpi_scale)
        
        app = QApplication.instance()
        settings_manager = getattr(app, 'settings_manager', None)
        
        accent_color = "#1890ff"
        base_color = "#ffffff"
        normal_color = "#e0e0e0"
        secondary_color = "#333333"
        auxiliary_color = "#f0f8ff"
        
        if settings_manager:
            accent_color = settings_manager.get_setting("appearance.colors.accent_color", accent_color)
            base_color = settings_manager.get_setting("appearance.colors.base_color", base_color)
            normal_color = settings_manager.get_setting("appearance.colors.normal_color", normal_color)
            secondary_color = settings_manager.get_setting("appearance.colors.secondary_color", secondary_color)
            auxiliary_color = settings_manager.get_setting("appearance.colors.auxiliary_color", auxiliary_color)
        
        self.setStyleSheet("""
            QWidget {
                background: transparent;
                border: none;
            }
        """)
        
        if self._enable_multiselect and self._is_selected:
            qcolor = QColor(accent_color)
            r, g, b = qcolor.red(), qcolor.green(), qcolor.blue()
            bg_color = f"rgba({r}, {g}, {b}, 102)"
            
            card_style = ""
            card_style += "QWidget {"
            card_style += f"background-color: {bg_color};"
            card_style += f"border: {scaled_border_width}px solid {accent_color};"
            card_style += f"border-radius: {scaled_border_radius}px;"
            card_style += "}"
            self.card_container.setStyleSheet(card_style)
            
            self.name_label.setStyleSheet(f"background: transparent; border: none; color: {secondary_color};")
            self.info_label.setStyleSheet(f"background: transparent; border: none; color: {secondary_color};")
        else:
            card_style = ""
            card_style += "QWidget {"
            card_style += f"background-color: {base_color};"
            card_style += f"border: {scaled_border_width}px solid {auxiliary_color};"
            card_style += f"border-radius: {scaled_border_radius}px;"
            card_style += "}"
            card_style += "QWidget:hover {"
            card_style += f"background-color: {auxiliary_color};"
            card_style += f"border-color: {normal_color};"
            card_style += "}"
            self.card_container.setStyleSheet(card_style)
            
            def darken_color(color_hex, amount=30):
                app = QApplication.instance()
                if hasattr(app, 'settings_manager'):
                    settings_manager = app.settings_manager
                else:
                    from freeassetfilter.core.settings_manager import SettingsManager
                    settings_manager = SettingsManager()
                current_theme = settings_manager.get_setting("appearance.theme", "default")
                is_dark_mode = (current_theme == "dark")
                
                color = color_hex.lstrip('#')
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
            
            secondary_color_dark = darken_color(secondary_color)
            
            self.name_label.setStyleSheet(f"background: transparent; border: none; color: {secondary_color_dark};")
            self.info_label.setStyleSheet(f"background: transparent; border: none; color: {secondary_color};")

    def mousePressEvent(self, event):
        """处理鼠标按下事件"""
        if event.button() == Qt.LeftButton:
            self._touch_start_pos = event.pos()
            self._is_touch_dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """处理鼠标移动事件"""
        if self._touch_start_pos is not None:
            delta = event.pos() - self._touch_start_pos
            if abs(delta.x()) > self._touch_drag_threshold or abs(delta.y()) > self._touch_drag_threshold:
                self._is_touch_dragging = True
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """处理鼠标释放事件"""
        if event.button() == Qt.LeftButton:
            if self._touch_start_pos is not None and not self._is_touch_dragging:
                self.clicked.emit(self._file_path)
            self._touch_start_pos = None
            self._is_touch_dragging = False
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        """处理鼠标双击事件"""
        if event.button() == Qt.LeftButton:
            self.doubleClicked.emit(self._file_path)
            super().mouseDoubleClickEvent(event)
    
    def resizeEvent(self, event):
        """处理大小变化事件，重新计算文字截断"""
        super().resizeEvent(event)
        # 调试信息：打印卡片宽度
        print(f"resizeEvent triggered, card width: {self.width()}")
        # 当卡片尺寸改变时，重新计算文字的截断显示
        if self._file_path:
            self._load_file_info()

    def eventFilter(self, obj, event):
        """事件过滤器，用于处理鼠标悬停事件"""
        from PyQt5.QtCore import QEvent
        
        if event.type() == QEvent.Enter:
            if not self._is_mouse_over:
                self._is_mouse_over = True
                self._trigger_hover_animation()
                # 确保覆盖层大小与卡片容器一致
                self.on_card_container_resize(None)
                # 强制刷新布局，确保按钮位置正确
                self.overlay_widget.layout().invalidate()
                self.overlay_widget.layout().activate()
                self.overlay_widget.setWindowOpacity(1.0)
                self.overlay_widget.show()
        elif event.type() == QEvent.Leave:
            if self._is_mouse_over:
                self._is_mouse_over = False
                self._trigger_leave_animation()
                self.overlay_widget.hide()
                self.overlay_widget.setWindowOpacity(0.0)
            self._touch_start_pos = None
            self._is_touch_dragging = False
        
        return super().eventFilter(obj, event)
    
    def _trigger_hover_animation(self):
        """触发悬停动画"""
        if not hasattr(self, '_style_colors'):
            return
        
        self._leave_anim_group.stop()
        
        colors = self._style_colors
        if self._is_selected:
            self._anim_hover_bg.setStartValue(self._anim_bg_color)
            self._anim_hover_bg.setEndValue(colors['selected_bg'])
            self._anim_hover_border.setStartValue(self._anim_border_color)
            self._anim_hover_border.setEndValue(colors['selected_border'])
        else:
            self._anim_hover_bg.setStartValue(self._anim_bg_color)
            self._anim_hover_bg.setEndValue(colors['hover_bg'])
            self._anim_hover_border.setStartValue(self._anim_border_color)
            self._anim_hover_border.setEndValue(colors['hover_border'])
        
        self._hover_anim_group.start()
    
    def _trigger_leave_animation(self):
        """触发离开动画"""
        if not hasattr(self, '_style_colors'):
            return
        
        if self._is_selected:
            return
        
        self._hover_anim_group.stop()
        
        colors = self._style_colors
        self._anim_leave_bg.setStartValue(self._anim_bg_color)
        self._anim_leave_bg.setEndValue(colors['normal_bg'])
        self._anim_leave_border.setStartValue(self._anim_border_color)
        self._anim_leave_border.setEndValue(colors['normal_border'])
        self._leave_anim_group.start()
    
    def on_card_container_resize(self, event):
        """当卡片容器大小改变时，调整覆盖层的大小"""
        # 调用原有的resizeEvent方法
        QWidget.resizeEvent(self.card_container, event)
        # 确保覆盖层的大小始终与卡片容器一致
        self.overlay_widget.setGeometry(self.card_container.rect())
        # 确保覆盖层的宽度不超过卡片容器的宽度
        self.overlay_widget.setMaximumWidth(self.card_container.width())
        # 确保覆盖层的高度不超过卡片容器的高度
        self.overlay_widget.setMaximumHeight(self.card_container.height())

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
        """获取是否开启多选功能"""
        return self._enable_multiselect

    @enable_multiselect.setter
    def enable_multiselect(self, value):
        """设置是否开启多选功能
        
        参数：
            value (bool): 是否开启多选功能
        """
        self._enable_multiselect = value
        # 更新卡片样式，确保样式正确反映当前的多选功能状态
        self.update_card_style()

    def set_enable_multiselect(self, enable):
        """
        设置是否开启多选功能
        
        参数：
            enable (bool): 是否开启多选功能
        """
        self.enable_multiselect = enable

    @property
    def single_line_mode(self):
        """获取是否使用单行文本格式"""
        return self._single_line_mode

    @single_line_mode.setter
    def single_line_mode(self, value):
        """设置是否使用单行文本格式
        
        参数：
            value (bool): 是否使用单行文本格式
        """
        self._single_line_mode = value
        # 重新加载文件信息以更新显示
        if self._file_path:
            self._load_file_info()

    def set_single_line_mode(self, enable):
        """
        设置是否使用单行文本格式
        
        参数：
            enable (bool): 是否使用单行文本格式
        """
        self.single_line_mode = enable
    
    def update_style(self):
        """
        更新卡片样式，用于主题变化时
        """
        self.update_card_style()