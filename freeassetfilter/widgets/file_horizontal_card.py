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
    Qt, pyqtSignal, QFileInfo, QEvent, QPropertyAnimation, QEasingCurve, pyqtProperty, QParallelAnimationGroup, QTimer, QPoint
)
from PyQt5.QtGui import (
    QFont, QFontMetrics, QPixmap, QColor, QCursor
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
        previewStateChanged (bool, str): 预览状态改变事件，传递预览状态和文件路径
    
    属性：
        file_path (str): 文件路径
        is_selected (bool): 是否选中
        is_previewing (bool): 是否处于预览态
        thumbnail_mode (str): 缩略图显示模式，可选值：'icon' 或 'custom'
        dpi_scale (float): DPI缩放因子
        enable_multiselect (bool): 是否开启多选功能
        single_line_mode (bool): 是否使用单行文本格式
    
    方法：
        set_file_path(file_path): 设置文件路径
        set_selected(selected): 设置选中状态
        set_previewing(previewing): 设置预览状态
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
    previewStateChanged = pyqtSignal(bool, str)  # 预览状态变化信号
    renameRequested = pyqtSignal(str)  # 重命名请求信号，传递文件路径
    deleteRequested = pyqtSignal(str)  # 删除请求信号，传递文件路径
    drag_started = pyqtSignal(dict)  # 拖拽开始信号，传递文件信息
    drag_ended = pyqtSignal(dict, str)  # 拖拽结束信号，传递文件信息和放置目标类型
    
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
        
        normal_border_width = int(1 * self.dpi_scale)
        # 预览态使用2倍边框宽度
        scaled_border_width = normal_border_width * 2 if self._is_previewing else normal_border_width
        scaled_border_radius = int(8 * self.dpi_scale)
        
        r, g, b, a = self._anim_bg_color.red(), self._anim_bg_color.green(), self._anim_bg_color.blue(), self._anim_bg_color.alpha()
        bg_color = f"rgba({r}, {g}, {b}, {a})"
        
        # 预览态使用secondary_color作为边框颜色，其他状态使用动画边框颜色
        if self._is_previewing:
            border_color = self.secondary_color
        else:
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
        self._is_previewing = False  # 预览态标志
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
        
        # 长按拖拽相关属性
        self._long_press_timer = QTimer(self)
        self._long_press_timer.setSingleShot(True)
        self._long_press_timer.timeout.connect(self._on_long_press)
        self._long_press_duration = 500  # 长按触发时间（毫秒）
        self._is_long_pressing = False
        self._drag_start_pos = None
        self._drag_card = None  # 拖拽时显示的浮动卡片
        self._is_dragging = False
        self._original_opacity = 1.0
        self._file_info = None  # 文件信息字典
        
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
        # 设置鼠标事件穿透，避免鼠标移动到图标上时触发父容器的Leave事件
        self.icon_display.setAttribute(Qt.WA_TransparentForMouseEvents, True)
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
    
    def set_previewing(self, previewing):
        """
        设置预览状态
        
        参数：
            previewing (bool): 是否处于预览态
        """
        if self._is_previewing != previewing:
            self._is_previewing = previewing
            if previewing:
                self._is_mouse_over = False
                self._trigger_preview_animation()
            else:
                self._trigger_unpreview_animation()
            self.update_card_style()
            self.previewStateChanged.emit(previewing, self._file_path)
    
    def _trigger_preview_animation(self):
        """触发预览态动画"""
        if not hasattr(self, '_style_colors'):
            self.update_card_style()
            return
        
        # 停止其他动画
        self._hover_anim_group.stop()
        self._leave_anim_group.stop()
        self._select_anim_group.stop()
        self._deselect_anim_group.stop()
        
        colors = self._style_colors
        secondary_qcolor = QColor(self.secondary_color)
        
        # 根据当前选中状态决定背景色
        if self._is_selected:
            target_bg = colors['selected_bg']
        else:
            target_bg = colors['normal_bg']
        
        self._anim_preview_bg.setStartValue(self._anim_bg_color)
        self._anim_preview_bg.setEndValue(target_bg)
        self._anim_preview_border.setStartValue(self._anim_border_color)
        self._anim_preview_border.setEndValue(secondary_qcolor)
        
        self._preview_anim_group.start()
    
    def _trigger_unpreview_animation(self):
        """触发取消预览态动画"""
        if not hasattr(self, '_style_colors'):
            self.update_card_style()
            return
        
        self._preview_anim_group.stop()
        
        colors = self._style_colors
        
        # 根据当前选中状态决定目标状态
        if self._is_selected:
            target_bg = colors['selected_bg']
            target_border = colors['selected_border']
        else:
            target_bg = colors['normal_bg']
            target_border = colors['normal_border']
        
        self._anim_unpreview_bg.setStartValue(self._anim_bg_color)
        self._anim_unpreview_bg.setEndValue(target_bg)
        self._anim_unpreview_border.setStartValue(self._anim_border_color)
        self._anim_unpreview_border.setEndValue(target_border)
        
        self._unpreview_anim_group.start()
    
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
        #print(f"[DEBUG] CustomFileHorizontalCard.refresh_thumbnail 被调用: {self._file_path}")
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
            #print(f"_load_file_info called, component_width: {component_width}")
            if component_width <= 0:
                # 如果组件宽度还未计算，使用一个默认值
                component_width = int(87.5 * self.dpi_scale)
                #print(f"Using default component_width: {component_width}")

            # 文件名截断处理
            name_font_metrics = QFontMetrics(self.name_label.font())
            # 留一些边距和图标的宽度
            icon_margin = int(10 * self.dpi_scale)
            available_width = component_width - icon_margin  # 图标宽度 + 边距
            # 调试信息：打印可用宽度计算
            #print(f"icon_margin: {icon_margin}, available_width: {available_width}")
            if available_width < 0:
                available_width = 0
                #print(f"available_width < 0, setting to 0")

            # 调试信息：打印文字截断前的完整文本
            #print(f"Original file name: '{file_name}'")

            elided_file_name = name_font_metrics.elidedText(file_name, Qt.ElideRight, available_width)

            # 文件信息截断处理
            info_text = f"{file_path}  {file_size}"

            # 调试信息：打印文字截断前的完整文本
            #print(f"Original info text: '{info_text}'")
            info_font_metrics = QFontMetrics(self.info_label.font())
            elided_info_text = info_font_metrics.elidedText(info_text, Qt.ElideRight, available_width)

            # 调试信息：打印截断后的文本
            #print(f"Elided file name: '{elided_file_name}'")
            #print(f"Elided info text: '{elided_info_text}'")

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
                        svg_widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)
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

            is_photo = suffix in ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'tiff', 'avif', 'cr2', 'cr3', 'nef', 'arw', 'dng', 'orf', 'psd', 'psb']
            is_video = suffix in ['mp4', 'mov', 'avi', 'mkv', 'wmv', 'flv', 'webm', 'm4v', 'mpeg', 'mpg', 'mxf']

            #print(f"[DEBUG] _set_file_icon: file={self._file_path}, suffix={suffix}, is_photo={is_photo}, is_video={is_video}")
            #print(f"[DEBUG] thumbnail_path={thumbnail_path}, exists={os.path.exists(thumbnail_path)}")

            use_thumbnail = False
            if (is_photo or is_video) and os.path.exists(thumbnail_path):
                use_thumbnail = True

            if use_thumbnail:
                scaled_icon_size = int(40 * self.dpi_scale)
                from PyQt5.QtGui import QImage
                image = QImage(thumbnail_path)
                #print(f"[DEBUG] QImage加载结果: isNull={image.isNull()}")
                if not image.isNull():
                    pixmap = QPixmap.fromImage(image)
                    #print(f"[DEBUG] 成功加载缩略图: {thumbnail_path}")
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
                    svg_widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                    svg_widget.show()
                elif isinstance(svg_widget, QLabel):
                    for child in self.icon_display.findChildren((QLabel, QSvgWidget)):
                        child.deleteLater()
                    svg_widget.setParent(self.card_container)
                    svg_widget.setFixedSize(scaled_icon_size, scaled_icon_size)
                    svg_widget.setStyleSheet("background: transparent; border: none; padding: 0; margin: 0;")
                    svg_widget.setAttribute(Qt.WA_TranslucentBackground, True)
                    svg_widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                    svg_widget.show()
                elif isinstance(svg_widget, QWidget):
                    for child in self.icon_display.findChildren((QLabel, QSvgWidget, QWidget)):
                        child.deleteLater()
                    svg_widget.setParent(self.card_container)
                    svg_widget.setFixedSize(scaled_icon_size, scaled_icon_size)
                    svg_widget.setStyleSheet("background: transparent; border: none; padding: 0; margin: 0;")
                    svg_widget.setAttribute(Qt.WA_TranslucentBackground, True)
                    svg_widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)
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
            'psd': '图像.svg', 'psb': '图像.svg',
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
        # 设置鼠标事件穿透，避免鼠标移动到图标上时触发父容器的Leave事件
        self.icon_display.setAttribute(Qt.WA_TransparentForMouseEvents, True)

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
        
        # 预览态动画组
        self._preview_anim_group = QParallelAnimationGroup(self)
        
        self._anim_preview_bg = QPropertyAnimation(self, b"anim_bg_color")
        self._anim_preview_bg.setDuration(180)
        self._anim_preview_bg.setEasingCurve(QEasingCurve.OutCubic)
        
        self._anim_preview_border = QPropertyAnimation(self, b"anim_border_color")
        self._anim_preview_border.setDuration(180)
        self._anim_preview_border.setEasingCurve(QEasingCurve.OutCubic)
        
        self._preview_anim_group.addAnimation(self._anim_preview_bg)
        self._preview_anim_group.addAnimation(self._anim_preview_border)
        
        # 取消预览态动画组
        self._unpreview_anim_group = QParallelAnimationGroup(self)
        
        self._anim_unpreview_bg = QPropertyAnimation(self, b"anim_bg_color")
        self._anim_unpreview_bg.setDuration(200)
        self._anim_unpreview_bg.setEasingCurve(QEasingCurve.InOutQuad)
        
        self._anim_unpreview_border = QPropertyAnimation(self, b"anim_border_color")
        self._anim_unpreview_border.setDuration(200)
        self._anim_unpreview_border.setEasingCurve(QEasingCurve.InOutQuad)
        
        self._unpreview_anim_group.addAnimation(self._anim_unpreview_bg)
        self._unpreview_anim_group.addAnimation(self._anim_unpreview_border)
        
        self._apply_animated_style()
    
    def update_card_style(self):
        """更新卡片样式"""
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtGui import QColor
        
        normal_border_width = int(1 * self.dpi_scale)
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
        
        # 保存secondary_color为实例属性，供其他方法使用
        self.secondary_color = secondary_color
        
        self.setStyleSheet("""
            QWidget {
                background: transparent;
                border: none;
            }
        """)
        
        if self._is_previewing:
            # 预览态：边框使用secondary_color，宽度为2倍
            preview_border_width = normal_border_width * 2
            
            if self._is_selected:
                # 预览态+选中态：使用选中态背景
                qcolor = QColor(accent_color)
                r, g, b = qcolor.red(), qcolor.green(), qcolor.blue()
                bg_color = f"rgba({r}, {g}, {b}, 102)"
            else:
                # 预览态+未选中态：使用普通背景
                bg_color = base_color
            
            card_style = ""
            card_style += "QWidget {"
            card_style += f"background-color: {bg_color};"
            card_style += f"border: {preview_border_width}px solid {secondary_color};"
            card_style += f"border-radius: {scaled_border_radius}px;"
            card_style += "}"
            self.card_container.setStyleSheet(card_style)
            
            self.name_label.setStyleSheet(f"background: transparent; border: none; color: {secondary_color};")
            self.info_label.setStyleSheet(f"background: transparent; border: none; color: {secondary_color};")
        elif self._enable_multiselect and self._is_selected:
            # 选中态
            qcolor = QColor(accent_color)
            r, g, b = qcolor.red(), qcolor.green(), qcolor.blue()
            bg_color = f"rgba({r}, {g}, {b}, 102)"
            
            card_style = ""
            card_style += "QWidget {"
            card_style += f"background-color: {bg_color};"
            card_style += f"border: {normal_border_width}px solid {accent_color};"
            card_style += f"border-radius: {scaled_border_radius}px;"
            card_style += "}"
            self.card_container.setStyleSheet(card_style)
            
            self.name_label.setStyleSheet(f"background: transparent; border: none; color: {secondary_color};")
            self.info_label.setStyleSheet(f"background: transparent; border: none; color: {secondary_color};")
        else:
            # 普通态
            card_style = ""
            card_style += "QWidget {"
            card_style += f"background-color: {base_color};"
            card_style += f"border: {normal_border_width}px solid {auxiliary_color};"
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
        import datetime
        def debug(msg):
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            print(f"[{timestamp}] [CustomFileHorizontalCard.mousePressEvent] {msg}")

        debug(f"鼠标按下事件触发，按钮: {event.button()}")

        if event.button() == Qt.LeftButton:
            debug(f"左键按下，触控优化: {self._is_touch_optimization_enabled()}")
            self._touch_start_pos = event.pos()
            self._is_touch_dragging = False
            # 只有在触控操作优化开启时才启动长按定时器
            if self._is_touch_optimization_enabled():
                debug(f"启动长按定时器，时长: {self._long_press_duration}ms")
                self._long_press_timer.start(self._long_press_duration)
            self._drag_start_pos = event.globalPos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """处理鼠标移动事件"""
        if self._touch_start_pos is not None:
            delta = event.pos() - self._touch_start_pos
            if abs(delta.x()) > self._touch_drag_threshold or abs(delta.y()) > self._touch_drag_threshold:
                self._is_touch_dragging = True
                # 如果正在长按，取消长按定时器
                if self._is_long_pressing:
                    self._long_press_timer.stop()
                    self._is_long_pressing = False
                    # 如果还没有开始拖拽，启动拖拽
                    if not self._is_dragging:
                        self._start_drag()

        # 如果正在拖拽，更新拖拽卡片位置
        if self._is_dragging:
            self._update_drag_card_position(event.globalPos())

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """处理鼠标释放事件"""
        import datetime
        def debug(msg):
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            print(f"[{timestamp}] [CustomFileHorizontalCard.mouseReleaseEvent] {msg}")

        debug(f"鼠标释放事件触发，按钮: {event.button()}, 左键: {Qt.LeftButton}")

        if event.button() == Qt.LeftButton:
            debug(f"左键释放，_is_dragging: {self._is_dragging}, _is_long_pressing: {self._is_long_pressing}")
            if self._is_dragging:
                # 拖拽结束，处理放置逻辑
                debug(f"正在拖拽中，调用 _end_drag")
                self._end_drag(event.globalPos())
            elif self._is_long_pressing:
                # 如果处于长按状态但没有拖拽（用户长按后松开但没有移动），取消长按状态
                debug(f"长按状态但未拖拽，调用 _cancel_drag")
                self._cancel_drag()
            elif self._touch_start_pos is not None and not self._is_touch_dragging:
                # 如果不是拖拽，处理点击
                debug(f"普通点击，发出 clicked 信号")
                self.clicked.emit(self._file_path)
            # 停止长按定时器
            self._long_press_timer.stop()
            self._is_long_pressing = False
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
        #print(f"resizeEvent triggered, card width: {self.width()}")
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
        
        # 预览态和选中态不响应hover效果
        if self._is_selected or self._is_previewing:
            return
        
        self._leave_anim_group.stop()
        
        colors = self._style_colors
        self._anim_hover_bg.setStartValue(self._anim_bg_color)
        self._anim_hover_bg.setEndValue(colors['hover_bg'])
        self._anim_hover_border.setStartValue(self._anim_border_color)
        self._anim_hover_border.setEndValue(colors['hover_border'])
        
        self._hover_anim_group.start()
    
    def _trigger_leave_animation(self):
        """触发离开动画"""
        if not hasattr(self, '_style_colors'):
            return
        
        # 预览态和选中态不响应leave效果
        if self._is_selected or self._is_previewing:
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
    
    # ==================== 长按拖拽功能 ====================
    
    def _is_touch_optimization_enabled(self):
        """
        检查触控操作优化是否启用
        对于存储池中的卡片，使用 file_staging.touch_optimization 设置
        
        Returns:
            bool: 触控操作优化是否启用
        """
        try:
            from freeassetfilter.core.settings_manager import SettingsManager
            settings_manager = SettingsManager()
            # 优先检查 file_staging 设置，如果不存在则使用 file_selector 设置
            staging_setting = settings_manager.get_setting("file_staging.touch_optimization", None)
            if staging_setting is not None:
                return staging_setting
            return settings_manager.get_setting("file_selector.touch_optimization", True)
        except Exception:
            return True
    
    def _on_long_press(self):
        """
        处理长按事件
        当用户长按卡片时触发，开始拖拽操作
        """
        import datetime
        def debug(msg):
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d:%M:%S.%f')[:-3]
            print(f"[{timestamp}] [CustomFileHorizontalCard._on_long_press] {msg}")

        debug(f"长按事件触发")
        self._is_long_pressing = True
        self._start_drag()
    
    def _start_drag(self):
        """
        开始拖拽操作
        创建浮动卡片并设置原始卡片为半透明
        """
        import datetime
        def debug(msg):
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            print(f"[{timestamp}] [CustomFileHorizontalCard._start_drag] {msg}")

        debug(f"开始拖拽，_file_info: {self._file_info is not None}")

        self._is_dragging = True

        # 设置原始卡片为半透明
        debug(f"设置拖拽外观")
        self._set_dragging_appearance(True)

        # 创建浮动拖拽卡片
        debug(f"创建拖拽卡片")
        self._create_drag_card()

        # 发出拖拽开始信号
        if self._file_info:
            debug(f"发出拖拽开始信号")
            self.drag_started.emit(self._file_info)

        # 改变鼠标样式
        debug(f"改变鼠标样式")
        self.setCursor(QCursor(Qt.ClosedHandCursor))

        # 捕获鼠标，确保能接收到鼠标释放事件
        debug(f"捕获鼠标")
        self.grabMouse()

        debug(f"拖拽开始完成")
    
    def _set_dragging_appearance(self, is_dragging):
        """
        设置拖拽时的外观样式
        
        Args:
            is_dragging (bool): 是否正在拖拽
        """
        if is_dragging:
            # 保存当前样式
            self._original_style = self.card_container.styleSheet()
            
            # 创建半透明背景色
            base_qcolor = QColor(self._get_base_color())
            r, g, b = base_qcolor.red(), base_qcolor.green(), base_qcolor.blue()
            bg_color = f"rgba({r}, {g}, {b}, 102)"  # 40% 透明度
            
            border_qcolor = QColor(self._get_auxiliary_color())
            br, bg, bb = border_qcolor.red(), border_qcolor.green(), border_qcolor.blue()
            border_color = f"rgba({br}, {bg}, {bb}, 102)"
            
            scaled_border_radius = int(8 * self.dpi_scale)
            scaled_border_width = int(1 * self.dpi_scale)
            
            # 应用半透明样式
            self.card_container.setStyleSheet(
                f"QWidget {{"
                f"background-color: {bg_color}; "
                f"border: {scaled_border_width}px solid {border_color}; "
                f"border-radius: {scaled_border_radius}px;"
                f"}}"
            )
            
            # 设置子控件透明度
            self.icon_display.setStyleSheet("background: transparent; border: none; opacity: 0.4;")
            self.name_label.setStyleSheet(f"color: {self._get_secondary_color()}; background: transparent; border: none; opacity: 0.4;")
            self.info_label.setStyleSheet(f"color: {self._get_secondary_color()}; background: transparent; border: none; opacity: 0.4;")
        else:
            # 恢复正常样式
            self.update_card_style()
    
    def _get_base_color(self):
        """获取基础颜色"""
        try:
            from freeassetfilter.core.settings_manager import SettingsManager
            settings_manager = SettingsManager()
            return settings_manager.get_setting("appearance.colors.base_color", "#212121")
        except Exception:
            return "#212121"
    
    def _get_auxiliary_color(self):
        """获取辅助颜色"""
        try:
            from freeassetfilter.core.settings_manager import SettingsManager
            settings_manager = SettingsManager()
            return settings_manager.get_setting("appearance.colors.auxiliary_color", "#3D3D3D")
        except Exception:
            return "#3D3D3D"
    
    def _get_secondary_color(self):
        """获取次要颜色（文字颜色）"""
        try:
            from freeassetfilter.core.settings_manager import SettingsManager
            settings_manager = SettingsManager()
            return settings_manager.get_setting("appearance.colors.secondary_color", "#FFFFFF")
        except Exception:
            return "#FFFFFF"
    
    def _create_drag_card(self):
        """
        创建浮动拖拽卡片
        使用 file horizontal card 样式，外层透明，内层圆角区域显示背景色
        """
        if self._drag_card:
            self._drag_card.deleteLater()
        
        # 创建浮动卡片窗口
        self._drag_card = QWidget(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self._drag_card.setObjectName("DragCard")

        # 设置卡片尺寸 - 使用与存储池卡片相同的自适应宽度
        card_width = self.card_container.width()
        card_height = self.card_container.height()
        self._drag_card.setFixedSize(card_width, card_height)

        # 设置外层透明
        self._drag_card.setStyleSheet("background-color: transparent; border: none;")
        self._drag_card.setAttribute(Qt.WA_TranslucentBackground, True)
        self._drag_card.setAutoFillBackground(False)

        # 设置拖拽卡片不接收鼠标事件，让事件传递到下层窗口
        self._drag_card.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        
        # 创建主布局
        main_layout = QVBoxLayout(self._drag_card)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 创建内部卡片（带圆角和背景色）
        from PyQt5.QtWidgets import QFrame
        inner_card = QFrame()
        inner_card.setObjectName("InnerCard")
        
        scaled_border_radius = int(8 * self.dpi_scale)
        scaled_border_width = int(1 * self.dpi_scale)
        base_color = self._get_base_color()
        normal_color = self._get_auxiliary_color()
        secondary_color = self._get_secondary_color()
        
        inner_card.setStyleSheet(
            f"#InnerCard {{"
            f"background-color: {base_color}; "
            f"border: {scaled_border_width}px solid {normal_color}; "
            f"border-radius: {scaled_border_radius}px;"
            f"}}"
            f"#InnerCard QLabel {{ background-color: transparent; border: none; }}"
        )
        inner_card.setAutoFillBackground(True)
        
        # 创建内部布局 - 使用水平布局（file horizontal card 样式）
        layout = QHBoxLayout(inner_card)
        layout.setSpacing(int(7.5 * self.dpi_scale))
        min_height_margin = int(6.25 * self.dpi_scale)
        layout.setContentsMargins(
            int(7.5 * self.dpi_scale),
            min_height_margin,
            int(7.5 * self.dpi_scale),
            min_height_margin
        )
        layout.setAlignment(Qt.AlignVCenter)
        
        # 创建图标显示区域 - 使用与原始卡片相同的图标大小 (40 * dpi_scale)
        icon_container = QWidget()
        icon_size = int(40 * self.dpi_scale)
        icon_container.setFixedSize(icon_size, icon_size)
        icon_container.setStyleSheet("background: transparent; border: none;")
        icon_layout = QVBoxLayout(icon_container)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_layout.setSpacing(0)
        icon_layout.setAlignment(Qt.AlignCenter)
        
        # 复制当前显示的图标 - 根据图标类型使用不同的复制方式
        self._copy_icon_to_drag_card(icon_container)
        
        layout.addWidget(icon_container, alignment=Qt.AlignVCenter)
        
        # 创建文字信息区
        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        if self._single_line_mode:
            text_layout.setSpacing(0)
        else:
            text_layout.setSpacing(int(4 * self.dpi_scale))
        text_layout.setAlignment(Qt.AlignVCenter)
        
        # 创建文件名标签
        name_font = QFont(self.global_font)
        name_font.setBold(True)
        
        name_label = QLabel()
        name_label.setAlignment(Qt.AlignLeft)
        name_label.setWordWrap(False)
        name_label.setFont(name_font)
        name_label.setStyleSheet(f"color: {secondary_color}; background: transparent; border: none;")
        name_label.setText(self.name_label.text())
        text_layout.addWidget(name_label)
        
        # 创建文件信息标签
        if not self._single_line_mode:
            info_font = QFont(self.global_font)
            info_font.setWeight(QFont.Normal)
            
            info_label = QLabel()
            info_label.setAlignment(Qt.AlignLeft)
            info_label.setWordWrap(False)
            info_label.setFont(info_font)
            info_label.setStyleSheet(f"color: {secondary_color}; background: transparent; border: none;")
            info_label.setText(self.info_label.text())
            text_layout.addWidget(info_label)
        
        layout.addLayout(text_layout, 1)
        
        # 将内部卡片添加到主布局
        main_layout.addWidget(inner_card)
        
        # 显示拖拽卡片在鼠标位置
        cursor_pos = QCursor.pos()
        self._drag_card.move(cursor_pos.x() - card_width // 2, cursor_pos.y() - card_height // 2)
        self._drag_card.show()
    
    def _update_drag_card_position(self, global_pos):
        """
        更新拖拽卡片位置
        
        Args:
            global_pos: 鼠标全局位置
        """
        if self._drag_card:
            card_width = self._drag_card.width()
            card_height = self._drag_card.height()
            self._drag_card.move(global_pos.x() - card_width // 2, global_pos.y() - card_height // 2)
    
    def _end_drag(self, global_pos):
        """
        结束拖拽操作

        Args:
            global_pos: 鼠标释放时的全局位置
        """
        import datetime
        def debug(msg):
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            print(f"[{timestamp}] [CustomFileHorizontalCard._end_drag] {msg}")

        debug(f"结束拖拽，位置: ({global_pos.x()}, {global_pos.y()})")

        # 恢复原始卡片样式
        self._set_dragging_appearance(False)

        # 恢复鼠标样式
        self.setCursor(QCursor(Qt.ArrowCursor))

        # 检测放置目标
        drop_target = self._detect_drop_target(global_pos)
        debug(f"检测到放置目标: {drop_target}")

        # 发出拖拽结束信号
        if self._file_info:
            debug(f"发出拖拽结束信号，文件: {self._file_info.get('name', 'unknown')}")
            self.drag_ended.emit(self._file_info, drop_target)
        else:
            debug(f"警告: _file_info 为 None，无法发出信号")

        # 清理拖拽卡片
        if self._drag_card:
            self._drag_card.deleteLater()
            self._drag_card = None

        # 释放鼠标捕获
        self.releaseMouse()

        self._is_dragging = False
        self._is_long_pressing = False

    def _cancel_drag(self):
        """
        取消拖拽操作
        当用户长按后松开但没有移动时调用，恢复原始状态
        """
        # 恢复原始卡片样式
        self._set_dragging_appearance(False)

        # 恢复鼠标样式
        self.setCursor(QCursor(Qt.ArrowCursor))

        # 清理拖拽卡片（隐藏hover卡片）
        if self._drag_card:
            self._drag_card.deleteLater()
            self._drag_card = None

        # 释放鼠标捕获
        self.releaseMouse()

        # 重置状态
        self._is_dragging = False
        self._is_long_pressing = False

        # 停止长按定时器
        self._long_press_timer.stop()

    def _detect_drop_target(self, global_pos):
        """
        检测拖拽放置的目标区域

        Args:
            global_pos: 鼠标全局位置

        Returns:
            str: 放置目标类型 ('file_selector', 'previewer', 'none')
        """
        # 获取主窗口
        main_window = self.window()
        if not main_window:
            return 'none'

        # 检查是否在文件选择器区域
        if hasattr(main_window, 'file_selector_a'):
            file_selector = main_window.file_selector_a
            if file_selector and file_selector.isVisible():
                # 使用 mapToGlobal 获取文件选择器的全局坐标范围
                selector_top_left = file_selector.mapToGlobal(file_selector.rect().topLeft())
                selector_bottom_right = file_selector.mapToGlobal(file_selector.rect().bottomRight())
                # 创建全局矩形
                from PyQt5.QtCore import QRect
                selector_global_rect = QRect(selector_top_left, selector_bottom_right)
                if selector_global_rect.contains(global_pos):
                    return 'file_selector'

        # 检查是否在统一预览器区域
        if hasattr(main_window, 'unified_previewer'):
            previewer = main_window.unified_previewer
            if previewer and previewer.isVisible():
                # 使用 mapToGlobal 获取预览器的全局坐标范围
                previewer_top_left = previewer.mapToGlobal(previewer.rect().topLeft())
                previewer_bottom_right = previewer.mapToGlobal(previewer.rect().bottomRight())
                # 创建全局矩形
                from PyQt5.QtCore import QRect
                previewer_global_rect = QRect(previewer_top_left, previewer_bottom_right)
                if previewer_global_rect.contains(global_pos):
                    return 'previewer'

        return 'none'
    
    def is_dragging(self):
        """
        获取当前是否正在拖拽

        Returns:
            bool: 是否正在拖拽
        """
        return self._is_dragging

    def set_file_info(self, file_info):
        """
        设置文件信息

        Args:
            file_info (dict): 文件信息字典
        """
        self._file_info = file_info

    def _copy_icon_to_drag_card(self, parent_container):
        """
        复制图标到拖拽卡片
        根据原卡片的图标类型（QLabel/QSvgWidget/自定义Widget）使用不同的复制方式

        Args:
            parent_container: 拖拽卡片中的图标容器
        """
        try:
            from PyQt5.QtSvg import QSvgWidget
            from PyQt5.QtGui import QPixmap

            # 获取图标尺寸 - 使用与原始卡片相同的图标大小 (40 * dpi_scale)
            icon_size = int(40 * self.dpi_scale)

            # 检查 icon_display 的类型
            if isinstance(self.icon_display, QLabel):
                # QLabel 类型 - 直接复制 pixmap
                pixmap = self.icon_display.pixmap()
                if pixmap and not pixmap.isNull():
                    icon_label = QLabel(parent_container)
                    icon_label.setAlignment(Qt.AlignCenter)
                    icon_label.setFixedSize(icon_size, icon_size)
                    icon_label.setStyleSheet("background: transparent; border: none;")
                    icon_label.setPixmap(pixmap)
                    parent_container.layout().addWidget(icon_label)
                    return

            elif isinstance(self.icon_display, QSvgWidget):
                # QSvgWidget 类型 - 重新渲染 SVG
                # 尝试获取 SVG 文件路径并重新渲染
                if self._file_path:
                    file_info = QFileInfo(self._file_path)
                    suffix = file_info.suffix().lower()
                    icon_path = self._get_file_icon_path(suffix, file_info.isDir())

                    if icon_path and os.path.exists(icon_path):
                        svg_widget = None
                        if icon_path.endswith("未知底板.svg") or icon_path.endswith("压缩文件.svg"):
                            if icon_path.endswith("压缩文件.svg"):
                                display_suffix = "." + suffix
                            else:
                                display_suffix = suffix.upper()
                                if len(display_suffix) > 5:
                                    display_suffix = "FILE"
                            svg_widget = SvgRenderer.render_unknown_file_icon(icon_path, display_suffix, icon_size, self.dpi_scale)
                        else:
                            svg_widget = SvgRenderer.render_svg_to_widget(icon_path, icon_size, self.dpi_scale)

                        if svg_widget:
                            svg_widget.setParent(parent_container)
                            svg_widget.setFixedSize(icon_size, icon_size)
                            svg_widget.setStyleSheet("background: transparent; border: none; padding: 0; margin: 0;")
                            svg_widget.setAttribute(Qt.WA_TranslucentBackground, True)
                            parent_container.layout().addWidget(svg_widget)
                            return

            else:
                # 其他类型（可能是包含子控件的自定义 Widget）
                # 查找子控件中的 QLabel 或 QSvgWidget
                qlabel_child = self.icon_display.findChild(QLabel)
                qsvg_child = self.icon_display.findChild(QSvgWidget)

                if qlabel_child and qlabel_child.pixmap() and not qlabel_child.pixmap().isNull():
                    # 复制 QLabel 的 pixmap
                    pixmap = qlabel_child.pixmap()
                    icon_label = QLabel(parent_container)
                    icon_label.setAlignment(Qt.AlignCenter)
                    icon_label.setFixedSize(icon_size, icon_size)
                    icon_label.setStyleSheet("background: transparent; border: none;")
                    icon_label.setPixmap(pixmap)
                    parent_container.layout().addWidget(icon_label)
                    return

                elif qsvg_child:
                    # 重新渲染 SVG
                    if self._file_path:
                        file_info = QFileInfo(self._file_path)
                        suffix = file_info.suffix().lower()
                        icon_path = self._get_file_icon_path(suffix, file_info.isDir())

                        if icon_path and os.path.exists(icon_path):
                            svg_widget = None
                            if icon_path.endswith("未知底板.svg") or icon_path.endswith("压缩文件.svg"):
                                if icon_path.endswith("压缩文件.svg"):
                                    display_suffix = "." + suffix
                                else:
                                    display_suffix = suffix.upper()
                                    if len(display_suffix) > 5:
                                        display_suffix = "FILE"
                                svg_widget = SvgRenderer.render_unknown_file_icon(icon_path, display_suffix, icon_size, self.dpi_scale)
                            else:
                                svg_widget = SvgRenderer.render_svg_to_widget(icon_path, icon_size, self.dpi_scale)

                            if svg_widget:
                                svg_widget.setParent(parent_container)
                                svg_widget.setFixedSize(icon_size, icon_size)
                                svg_widget.setStyleSheet("background: transparent; border: none; padding: 0; margin: 0;")
                                svg_widget.setAttribute(Qt.WA_TranslucentBackground, True)
                                parent_container.layout().addWidget(svg_widget)
                                return

            # 如果以上都失败，使用默认的文件图标
            self._create_default_icon_for_drag(parent_container, icon_size)

        except Exception as e:
            print(f"复制图标到拖拽卡片失败: {e}")
            # 创建默认图标 - 使用与原始卡片相同的图标大小 (40 * dpi_scale)
            self._create_default_icon_for_drag(parent_container, int(40 * self.dpi_scale))

    def _create_default_icon_for_drag(self, parent_container, icon_size):
        """
        为拖拽卡片创建默认图标

        Args:
            parent_container: 父容器
            icon_size: 图标尺寸
        """
        try:
            # 尝试根据文件类型重新创建图标
            if self._file_path:
                file_info = QFileInfo(self._file_path)
                suffix = file_info.suffix().lower()
                is_dir = file_info.isDir()

                # 检查是否有缩略图（图片/视频）
                import hashlib
                thumb_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data", "thumbnails")
                md5_hash = hashlib.md5(self._file_path.encode('utf-8'))
                file_hash = md5_hash.hexdigest()[:16]
                thumbnail_path = os.path.join(thumb_dir, f"{file_hash}.png")

                is_photo = suffix in ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'tiff', 'avif', 'cr2', 'cr3', 'nef', 'arw', 'dng', 'orf', 'psd', 'psb']
                is_video = suffix in ['mp4', 'mov', 'avi', 'mkv', 'wmv', 'flv', 'webm', 'm4v', 'mpeg', 'mpg', 'mxf']

                if (is_photo or is_video) and os.path.exists(thumbnail_path):
                    # 使用缩略图
                    pixmap = QPixmap(thumbnail_path)
                    if not pixmap.isNull():
                        icon_label = QLabel(parent_container)
                        icon_label.setAlignment(Qt.AlignCenter)
                        icon_label.setFixedSize(icon_size, icon_size)
                        icon_label.setStyleSheet("background: transparent; border: none;")
                        scaled_pixmap = pixmap.scaled(icon_size, icon_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                        icon_label.setPixmap(scaled_pixmap)
                        parent_container.layout().addWidget(icon_label)
                        return

                # 对于 lnk/exe/url 文件，使用系统图标
                if not is_dir and suffix in ["lnk", "exe", "url"]:
                    try:
                        from freeassetfilter.utils.icon_utils import get_highest_resolution_icon, hicon_to_pixmap, DestroyIcon
                        hicon = get_highest_resolution_icon(self._file_path, desired_size=256)
                        if hicon:
                            pixmap = hicon_to_pixmap(hicon, icon_size, None)
                            DestroyIcon(hicon)
                            if pixmap and not pixmap.isNull():
                                icon_label = QLabel(parent_container)
                                icon_label.setAlignment(Qt.AlignCenter)
                                icon_label.setFixedSize(icon_size, icon_size)
                                icon_label.setStyleSheet("background: transparent; border: none;")
                                icon_label.setPixmap(pixmap)
                                parent_container.layout().addWidget(icon_label)
                                return
                    except Exception:
                        pass

                # 使用 SVG 图标
                icon_path = self._get_file_icon_path(suffix, is_dir)
                if icon_path and os.path.exists(icon_path):
                    svg_widget = None
                    if icon_path.endswith("未知底板.svg") or icon_path.endswith("压缩文件.svg"):
                        if icon_path.endswith("压缩文件.svg"):
                            display_suffix = "." + suffix
                        else:
                            display_suffix = suffix.upper()
                            if len(display_suffix) > 5:
                                display_suffix = "FILE"
                        svg_widget = SvgRenderer.render_unknown_file_icon(icon_path, display_suffix, icon_size, self.dpi_scale)
                    else:
                        svg_widget = SvgRenderer.render_svg_to_widget(icon_path, icon_size, self.dpi_scale)

                    if svg_widget:
                        svg_widget.setParent(parent_container)
                        svg_widget.setFixedSize(icon_size, icon_size)
                        svg_widget.setStyleSheet("background: transparent; border: none; padding: 0; margin: 0;")
                        svg_widget.setAttribute(Qt.WA_TranslucentBackground, True)
                        parent_container.layout().addWidget(svg_widget)
                        return

            # 最终回退：创建空白图标
            icon_label = QLabel(parent_container)
            icon_label.setAlignment(Qt.AlignCenter)
            icon_label.setFixedSize(icon_size, icon_size)
            icon_label.setStyleSheet("background: transparent; border: none;")
            parent_container.layout().addWidget(icon_label)

        except Exception as e:
            print(f"创建默认图标失败: {e}")