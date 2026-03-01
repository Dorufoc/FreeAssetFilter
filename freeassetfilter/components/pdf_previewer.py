#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

PDF预览器组件
提供PDF文件预览、页面导航和缩放功能
"""

import os
import sys
from concurrent.futures import ThreadPoolExecutor

# 导入日志模块
from freeassetfilter.utils.app_logger import info, debug, warning, error
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QSizePolicy, QSpacerItem, QApplication, QFrame
)
from PySide6.QtCore import Qt, Signal, QTimer, QRect, QRectF, QPoint
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QFont, QRegion, QPainterPath
from PySide6.QtWidgets import QScroller

# 导入自定义控件
from freeassetfilter.widgets.button_widgets import CustomButton
from freeassetfilter.widgets.progress_widgets import D_ProgressBar
from freeassetfilter.widgets.smooth_scroller import SmoothScroller, D_ScrollBar

# 尝试导入PyMuPDF
fitz = None
try:
    import fitz  # PyMuPDF
except ImportError:
    warning("[WARNING] PyMuPDF未安装，PDF预览功能将不可用")


class PDFPageWidget(QWidget):
    """
    PDF页面显示控件
    负责单个PDF页面的渲染和显示
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # 获取DPI缩放因子
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)

        # 初始化属性
        self.page_pixmap = None
        self.page_number = -1
        self.is_rendered = False

        # 设置固定大小策略
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        # 设置最小大小与视频播放器组件相同 (200, 200)，应用DPI缩放
        self.setMinimumSize(int(200 * self.dpi_scale), int(200 * self.dpi_scale))
        
        # 设置样式
        self.setStyleSheet("background-color: transparent;")
    
    def set_pixmap(self, pixmap: QPixmap, logical_size: tuple = None):
        """
        设置页面位图
        
        Args:
            pixmap: 页面位图
            logical_size: 逻辑尺寸元组 (width, height)，如果为None则使用pixmap.size()
        """
        self.page_pixmap = pixmap
        self.is_rendered = True
        
        if pixmap:
            if logical_size:
                # 使用传入的逻辑尺寸
                self.setFixedSize(logical_size[0], logical_size[1])
            else:
                # 获取设备像素比
                from PySide6.QtGui import QGuiApplication
                device_pixel_ratio = QGuiApplication.primaryScreen().devicePixelRatio()
                # 设置控件大小为逻辑像素大小（物理像素 / 设备像素比）
                logical_size = pixmap.size() / device_pixel_ratio
                self.setFixedSize(logical_size.toSize())
        self.update()
    
    def paintEvent(self, event):
        """
        绘制事件
        根据控件大小缩放绘制位图，确保图片始终填充整个容器
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        
        # 绘制背景色（使用base_color）
        base_color = "#F5F5F5"
        if self.parent() and hasattr(self.parent(), 'base_color'):
            base_color = self.parent().base_color
        painter.fillRect(self.rect(), QColor(base_color))
        
        # 绘制页面位图
        if self.page_pixmap and not self.page_pixmap.isNull():
            # 获取控件当前大小
            widget_rect = self.rect()
            # 获取位图大小（考虑设备像素比）
            pixmap_size = self.page_pixmap.size()
            
            # 计算缩放后的目标矩形，保持宽高比并填充整个控件
            target_rect = self._calculate_scaled_rect(widget_rect, pixmap_size)
            
            # 缩放绘制位图
            painter.drawPixmap(target_rect, self.page_pixmap, self.page_pixmap.rect())
        else:
            # 未渲染时显示占位符
            painter.setPen(QColor("#CCCCCC"))
            painter.drawText(self.rect(), Qt.AlignCenter, "加载中...")
        
        painter.end()
    
    def _calculate_scaled_rect(self, widget_rect, pixmap_size):
        """
        计算缩放后的目标矩形，使位图填充整个控件并保持宽高比
        
        Args:
            widget_rect: 控件矩形
            pixmap_size: 位图大小
            
        Returns:
            QRect: 缩放后的目标矩形
        """
        widget_width = widget_rect.width()
        widget_height = widget_rect.height()
        pixmap_width = pixmap_size.width()
        pixmap_height = pixmap_size.height()
        
        # 计算缩放比例，使位图填充整个控件
        scale_x = widget_width / pixmap_width if pixmap_width > 0 else 1.0
        scale_y = widget_height / pixmap_height if pixmap_height > 0 else 1.0
        
        # 使用统一的缩放比例，保持宽高比
        scale = min(scale_x, scale_y)
        
        # 计算缩放后的尺寸
        scaled_width = int(pixmap_width * scale)
        scaled_height = int(pixmap_height * scale)
        
        # 居中显示
        x = (widget_width - scaled_width) // 2
        y = (widget_height - scaled_height) // 2
        
        return QRect(x, y, scaled_width, scaled_height)


class PDFPreviewer(QWidget):
    """
    PDF预览器主组件
    提供PDF文件的完整预览功能，包括页面导航、缩放控制等
    
    信号:
        pdf_render_finished: PDF渲染完成时发出
    """
    
    pdf_render_finished = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 获取应用实例和DPI缩放因子
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        self.global_font = getattr(app, 'global_font', QFont())
        self.default_font_size = getattr(app, 'default_font_size', 10)
        
        # 获取主题颜色
        self.secondary_color = "#333333"  # 默认secondary颜色
        self.base_color = "#F5F5F5"  # 默认base颜色
        if hasattr(app, 'settings_manager'):
            self.secondary_color = app.settings_manager.get_setting("appearance.colors.secondary_color", "#333333")
            self.base_color = app.settings_manager.get_setting("appearance.colors.base_color", "#F5F5F5")
        
        # 获取图标路径
        current_dir = os.path.dirname(os.path.abspath(__file__))
        icons_path = os.path.join(current_dir, '..', 'icons')
        self.icons_path = os.path.abspath(icons_path)
        self.arrow_left_icon = os.path.join(self.icons_path, 'arrow_left.svg')
        self.arrow_right_icon = os.path.join(self.icons_path, 'arrow_right.svg')
        
        # PDF文档对象
        self.pdf_document = None
        self.file_path = None
        self.total_pages = 0
        self.current_page = 0
        
        # 缩放控制
        self.zoom_min = 40  # 最小缩放百分比
        self.zoom_max = 400  # 最大缩放百分比
        self.zoom_default = 100  # 默认缩放百分比
        self.current_zoom = self.zoom_default
        
        # 页面尺寸缓存
        self.page_sizes = []  # 存储每页的原始尺寸 (width, height)
        self.page_widgets = []  # 页面控件列表
        self.page_pixmaps = {}  # 页面位图缓存 {page_num: QPixmap}
        
        # 渲染控制
        self.render_executor = None  # 线程池
        self.max_cache_pages = 5  # 最大缓存页面数
        self.is_loading = False
        
        # 可见区域检测定时器
        self.visibility_timer = QTimer(self)
        self.visibility_timer.setInterval(100)  # 100ms检测一次
        self.visibility_timer.timeout.connect(self._render_visible_pages)

        # 鼠标中键拖动相关属性
        self._is_middle_button_dragging = False  # 是否正在中键拖动
        self._middle_button_drag_global_start_pos = None  # 拖动起始位置（全局坐标）
        self._middle_button_drag_start_scroll_x = 0  # 拖动起始水平滚动值
        self._middle_button_drag_start_scroll_y = 0  # 拖动起始垂直滚动值
        self.setCursor(Qt.ArrowCursor)  # 设置默认光标

        # 初始化UI
        self._init_ui()
    
    def _init_ui(self):
        """
        初始化用户界面
        """
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(int(5 * self.dpi_scale))
        main_layout.setContentsMargins(0, 0, 0, 0)

        # 创建控制栏
        self._create_control_bar()
        main_layout.addWidget(self.control_bar)

        # 创建内容预览区
        self._create_content_area()
        main_layout.addWidget(self.scroll_area, 1)

        # 设置字体
        self.setFont(self.global_font)
    
    def _create_control_bar(self):
        """
        创建控制栏
        """
        self.control_bar = QWidget()
        # 控制栏根据内容自适应宽度，不扩展
        self.control_bar.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        
        control_layout = QHBoxLayout(self.control_bar)
        control_layout.setSpacing(5)
        control_layout.setContentsMargins(6, 4, 2, 6)
        
        # 上一页按钮 - 使用arrow_left.svg图标，普通样式
        self.prev_button = CustomButton(
            self.arrow_left_icon,
            parent=self.control_bar,
            button_type="normal",
            display_mode="icon",
            height=20,  # 未缩放的高度，内部会自动应用dpi_scale
            tooltip_text="上一页"
        )
        self.prev_button.clicked.connect(self._go_to_prev_page)
        control_layout.addWidget(self.prev_button)
        
        # 页码标签 - 使用全局字体，让Qt6自动处理DPI缩放
        self.page_label = QLabel("0/0")
        self.page_label.setAlignment(Qt.AlignCenter)
        self.page_label.setFont(self.global_font)
        self.page_label.setStyleSheet(f"""
            QLabel {{
                color: {self.secondary_color};
            }}
        """)
        control_layout.addWidget(self.page_label)
        
        # 下一页按钮 - 使用arrow_right.svg图标，普通样式
        self.next_button = CustomButton(
            self.arrow_right_icon,
            parent=self.control_bar,
            button_type="normal",
            display_mode="icon",
            height=20,  # 未缩放的高度，内部会自动应用dpi_scale
            tooltip_text="下一页"
        )
        self.next_button.clicked.connect(self._go_to_next_page)
        control_layout.addWidget(self.next_button)
        
        # 添加弹性空间
        control_layout.addSpacerItem(
            QSpacerItem(5, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)
        )

        # 缩放标签 - 使用settings.json中的secondary_color，与文本预览器保持一致
        self.zoom_label = QLabel("100%")
        self.zoom_label.setStyleSheet(f"color: {self.secondary_color};")
        control_layout.addWidget(self.zoom_label)

        # 缩放滑块
        self.zoom_slider = D_ProgressBar(
            parent=self.control_bar,
            orientation=D_ProgressBar.Horizontal,
            is_interactive=True
        )
        self.zoom_slider.setFixedWidth(int(150 * self.dpi_scale))
        self.zoom_slider.setRange(self.zoom_min, self.zoom_max)
        self.zoom_slider.setValue(self.zoom_default)
        self.zoom_slider.valueChanged.connect(self._on_zoom_changed)
        control_layout.addWidget(self.zoom_slider)
    
    def _create_content_area(self):
        """
        创建内容预览区
        """
        # 创建滚动区域
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setFrameShape(QFrame.NoFrame)

        # 应用平滑滚动
        SmoothScroller.apply_to_scroll_area(self.scroll_area)

        # 设置自定义滚动条
        self.scroll_area.setVerticalScrollBar(D_ScrollBar(orientation=Qt.Vertical))
        self.scroll_area.setHorizontalScrollBar(D_ScrollBar(orientation=Qt.Horizontal))

        # 应用主题颜色到滚动条
        self.scroll_area.verticalScrollBar().apply_theme_from_settings()
        self.scroll_area.horizontalScrollBar().apply_theme_from_settings()

        # 连接滚动事件，实时更新当前页码
        self.scroll_area.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)

        # 创建内容容器（无圆角，背景色使用base_color）
        self.content_widget = QWidget()
        self.content_widget.setStyleSheet(f"background-color: {self.base_color};")
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setSpacing(int(10 * self.dpi_scale))
        self.content_layout.setContentsMargins(
            int(20 * self.dpi_scale),
            0,  # 顶部边距设为0，避免第一页上方出现空白间隙
            int(20 * self.dpi_scale),
            int(20 * self.dpi_scale)
        )
        self.content_layout.setAlignment(Qt.AlignHCenter | Qt.AlignTop)

        self.scroll_area.setWidget(self.content_widget)

        # 安装事件过滤器以捕获双击事件（重置缩放）和滚轮事件（Ctrl+滚轮缩放）
        self.content_widget.installEventFilter(self)
        self.scroll_area.installEventFilter(self)
        self.scroll_area.viewport().installEventFilter(self)

        # 设置滚动区域圆角样式（参考file_selector.py的实现）
        # 添加padding为滚动条提供边距，背景色使用base_color
        self.scroll_area.setStyleSheet(f"""
            QScrollArea {{
                border: 1px solid {self.base_color};
                border-radius: 6px;
                background-color: {self.base_color};
                padding: 6px;
            }}
            QScrollArea > QWidget > QWidget {{
                background-color: {self.base_color};
            }}
        """)
    
    def set_file(self, file_info):
        """
        设置要预览的文件（统一预览器接口）
        
        Args:
            file_info: 文件信息字典，包含path键
        """
        if isinstance(file_info, dict):
            file_path = file_info.get("path", "")
        else:
            file_path = str(file_info)
        
        self.load_file_from_path(file_path)
    
    def load_file_from_path(self, file_path: str):
        """
        从文件路径加载PDF
        
        Args:
            file_path: PDF文件路径
        """
        if not file_path or not os.path.exists(file_path):
            self._show_error("文件不存在")
            return
        
        if not fitz:
            self._show_error("PyMuPDF未安装，无法预览PDF文件")
            return
        
        # 关闭之前的文档
        self._close_document()
        
        try:
            # 打开PDF文档
            self.pdf_document = fitz.open(file_path)
            self.file_path = file_path
            self.total_pages = len(self.pdf_document)
            self.current_page = 0
            
            # 获取每页的尺寸
            self.page_sizes = []
            for page_num in range(self.total_pages):
                page = self.pdf_document.load_page(page_num)
                rect = page.rect
                self.page_sizes.append((rect.width, rect.height))
            
            # 创建页面控件
            self._create_page_widgets()

            # 计算页码标签的最大宽度（基于最大页码文本）
            self._update_page_label_width()

            # 更新UI
            self._update_page_label()
            self._update_button_states()

            # 重置滚动条到顶部
            self.scroll_area.verticalScrollBar().setValue(0)
            self.scroll_area.horizontalScrollBar().setValue(0)

            # 启动可见区域检测
            self.visibility_timer.start()

            # 立即渲染第一页
            QTimer.singleShot(0, self._render_visible_pages)
            
        except Exception as e:
            self._show_error(f"加载PDF失败: {str(e)}")
    
    def _close_document(self):
        """
        关闭当前PDF文档并清理资源
        """
        # 停止定时器
        self.visibility_timer.stop()
        
        # 关闭线程池
        if self.render_executor:
            self.render_executor.shutdown(wait=False)
            self.render_executor = None
        
        # 清理页面控件
        self._clear_page_widgets()
        
        # 清理缓存
        self.page_pixmaps.clear()
        
        # 关闭文档
        if self.pdf_document:
            self.pdf_document.close()
            self.pdf_document = None
        
        self.file_path = None
        self.total_pages = 0
        self.current_page = 0
        self.page_sizes = []
    
    def _clear_page_widgets(self):
        """
        清除所有页面控件
        """
        # 移除所有页面控件
        while self.page_widgets:
            widget = self.page_widgets.pop()
            self.content_layout.removeWidget(widget)
            widget.deleteLater()
    
    def _create_page_widgets(self):
        """
        创建页面控件
        """
        self._clear_page_widgets()
        
        for page_num in range(self.total_pages):
            page_widget = PDFPageWidget()
            page_widget.page_number = page_num
            
            # 设置初始大小
            if page_num < len(self.page_sizes):
                orig_width, orig_height = self.page_sizes[page_num]
                width, height = self._calculate_page_size(orig_width, orig_height)
                page_widget.setFixedSize(width, height)
            
            self.page_widgets.append(page_widget)
            self.content_layout.addWidget(page_widget, 0, Qt.AlignHCenter)
    
    def _calculate_page_size(self, orig_width: float, orig_height: float) -> tuple:
        """
        计算页面显示尺寸（逻辑像素）
        100%缩放时，页面宽度刚好适应显示区域宽度（不触发横向滚动）
        
        Args:
            orig_width: 原始宽度（PDF页面原始尺寸）
            orig_height: 原始高度（PDF页面原始尺寸）
            
        Returns:
            (logical_width, logical_height) 逻辑显示尺寸
        """
        # 获取设备像素比
        from PySide6.QtGui import QGuiApplication
        device_pixel_ratio = QGuiApplication.primaryScreen().devicePixelRatio()
        
        # 获取滚动区域可视宽度（减去滚动条宽度和边距）
        # 使用物理像素计算，然后转换为逻辑像素
        scrollbar_width = int(20 * device_pixel_ratio)  # 滚动条宽度预留（物理像素）
        margin_width = int(40 * device_pixel_ratio)  # 左右边距（物理像素）
        viewport_physical_width = self.scroll_area.viewport().width() * device_pixel_ratio
        available_physical_width = viewport_physical_width - scrollbar_width - margin_width
        
        # 确保可用宽度为正数
        available_physical_width = max(available_physical_width, int(100 * device_pixel_ratio))
        
        # 计算100%缩放时的基准比例（物理像素 / 原始尺寸）
        base_scale_physical = available_physical_width / orig_width if orig_width > 0 else 1.0
        
        # 应用当前缩放比例，得到物理像素尺寸
        physical_width = orig_width * base_scale_physical * (self.current_zoom / 100.0)
        physical_height = orig_height * base_scale_physical * (self.current_zoom / 100.0)
        
        # 转换为逻辑像素（控件使用的大小）
        logical_width = int(physical_width / device_pixel_ratio)
        logical_height = int(physical_height / device_pixel_ratio)
        
        return (logical_width, logical_height)
    
    def _render_visible_pages(self):
        """
        渲染当前可见区域的页面
        """
        if not self.pdf_document or not self.page_widgets:
            return

        # 获取滚动区域的可视区域
        viewport = self.scroll_area.viewport()
        viewport_rect = viewport.rect()

        # 计算可见的页面范围
        first_visible = -1
        last_visible = -1

        for i, widget in enumerate(self.page_widgets):
            # 获取控件在视口中的位置（统一使用viewport坐标系）
            widget_pos = widget.mapTo(viewport, QPoint(0, 0))
            widget_rect = QRect(widget_pos, widget.size())

            # 检查是否与可视区域相交
            if widget_rect.intersects(viewport_rect):
                if first_visible == -1:
                    first_visible = i
                last_visible = i

        if first_visible == -1:
            return

        # 渲染可见页面及其相邻页面（预加载）
        start_page = max(0, first_visible - 1)
        end_page = min(last_visible + 2, self.total_pages)
        for page_num in range(start_page, end_page):
            if page_num not in self.page_pixmaps:
                self._render_page(page_num)

        # 清理过期缓存
        self._cleanup_cache()
    
    def _render_page(self, page_num: int):
        """
        渲染指定页面，使用高DPI优化处理
        
        Args:
            page_num: 页码（从0开始）
        """
        if not self.pdf_document or page_num < 0 or page_num >= self.total_pages:
            return
        
        try:
            # 加载页面
            page = self.pdf_document.load_page(page_num)
            
            # 获取设备像素比
            from PySide6.QtGui import QGuiApplication
            device_pixel_ratio = QGuiApplication.primaryScreen().devicePixelRatio()
            
            # 计算逻辑尺寸（控件大小）
            orig_width, orig_height = self.page_sizes[page_num]
            logical_width, logical_height = self._calculate_page_size(orig_width, orig_height)
            
            # 计算物理像素尺寸（位图实际大小）
            physical_width = int(logical_width * device_pixel_ratio)
            physical_height = int(logical_height * device_pixel_ratio)
            
            # 计算渲染矩阵（物理像素 / 原始尺寸）
            render_scale_x = physical_width / orig_width if orig_width > 0 else 1.0
            render_scale_y = physical_height / orig_height if orig_height > 0 else 1.0
            mat = fitz.Matrix(render_scale_x, render_scale_y)
            
            # 渲染页面为位图
            pix = page.get_pixmap(matrix=mat, alpha=False)
            
            # 转换为QImage
            img_data = pix.samples
            img = QImage(
                img_data,
                pix.width,
                pix.height,
                pix.stride,
                QImage.Format_RGB888
            )
            
            # 转换为QPixmap并设置设备像素比
            pixmap = QPixmap.fromImage(img)
            pixmap.setDevicePixelRatio(device_pixel_ratio)
            
            # 缓存并显示（传入logical_width/height作为逻辑尺寸，确保容器大小和位图一致）
            self.page_pixmaps[page_num] = pixmap
            if page_num < len(self.page_widgets):
                self.page_widgets[page_num].set_pixmap(pixmap, (logical_width, logical_height))
            
            # 如果是第一页渲染完成，发出信号
            if page_num == 0 and len(self.page_pixmaps) == 1:
                self.pdf_render_finished.emit()
                
        except Exception as e:
            error(f"[ERROR] 渲染页面 {page_num} 失败: {e}")
    
    def _cleanup_cache(self):
        """
        清理过期的页面缓存
        """
        if len(self.page_pixmaps) <= self.max_cache_pages:
            return

        # 获取当前可见的页面
        viewport = self.scroll_area.viewport()
        viewport_rect = viewport.rect()
        visible_pages = set()

        for i, widget in enumerate(self.page_widgets):
            # 统一使用viewport坐标系
            widget_pos = widget.mapTo(viewport, QPoint(0, 0))
            widget_rect = QRect(widget_pos, widget.size())
            if widget_rect.intersects(viewport_rect):
                visible_pages.add(i)

        # 保留可见页面及其相邻页面
        pages_to_keep = set()
        for page in visible_pages:
            pages_to_keep.add(page)
            pages_to_keep.add(page - 1)
            pages_to_keep.add(page + 1)

        # 清理不在保留列表中的缓存
        pages_to_remove = []
        for page_num in self.page_pixmaps:
            if page_num not in pages_to_keep:
                pages_to_remove.append(page_num)

        for page_num in pages_to_remove:
            del self.page_pixmaps[page_num]
    
    def _go_to_prev_page(self):
        """
        跳转到上一页
        """
        if self.current_page > 0:
            self._go_to_page(self.current_page - 1)
    
    def _go_to_next_page(self):
        """
        跳转到下一页
        """
        if self.current_page < self.total_pages - 1:
            self._go_to_page(self.current_page + 1)
    
    def _go_to_page(self, page_num: int):
        """
        跳转到指定页面
        
        Args:
            page_num: 目标页码（从0开始）
        """
        if page_num < 0 or page_num >= self.total_pages:
            return
        
        self.current_page = page_num
        
        # 滚动到目标页面
        if page_num < len(self.page_widgets):
            widget = self.page_widgets[page_num]
            self.scroll_area.ensureWidgetVisible(widget, 0, int(20 * self.dpi_scale))
        
        # 更新UI
        self._update_page_label()
        self._update_button_states()
        
        # 渲染新页面
        self._render_visible_pages()
    
    def _on_zoom_changed(self, value: int):
        """
        缩放值变化处理
        
        Args:
            value: 新的缩放值
        """
        self.current_zoom = value
        self.zoom_label.setText(f"{value}%")
        
        # 重新计算所有页面大小
        self._update_page_sizes()
        
        # 清除缓存，强制重新渲染
        self.page_pixmaps.clear()
        
        # 重新渲染可见页面
        self._render_visible_pages()
    
    def _on_scroll_changed(self):
        """
        滚动位置变化处理，检测当前可见页面并更新页码标签
        """
        if not self.pdf_document or not self.page_widgets:
            return

        # 获取当前可见的页面（在视口中心位置的页面）
        viewport = self.scroll_area.viewport()
        viewport_rect = viewport.rect()
        viewport_center_y = viewport_rect.height() / 2

        # 找到在视口中心位置的页面
        current_visible_page = 0
        min_distance = float('inf')

        for i, widget in enumerate(self.page_widgets):
            # 获取控件在视口中的位置（统一坐标系）
            widget_pos = widget.mapTo(viewport, QPoint(0, 0))
            widget_rect = QRect(widget_pos, widget.size())

            # 计算页面中心到视口中心的距离
            widget_center_y = widget_rect.top() + widget_rect.height() / 2
            distance = abs(widget_center_y - viewport_center_y)

            # 如果页面与视口相交，且距离中心最近
            if widget_rect.intersects(viewport_rect) and distance < min_distance:
                min_distance = distance
                current_visible_page = i

        # 如果当前页码发生变化，更新UI
        if current_visible_page != self.current_page:
            self.current_page = current_visible_page
            self._update_page_label()
            self._update_button_states()
    
    def _update_page_sizes(self):
        """
        更新所有页面控件的大小
        """
        for i, widget in enumerate(self.page_widgets):
            if i < len(self.page_sizes):
                orig_width, orig_height = self.page_sizes[i]
                width, height = self._calculate_page_size(orig_width, orig_height)
                widget.setFixedSize(width, height)

    def _update_page_label_width(self):
        """
        根据最大页码文本长度预计算页码标签的宽度，避免数字变化时布局抖动
        """
        if self.total_pages <= 0:
            return

        # 构建最大长度的页码文本（例如：999/999）
        max_page_num_str = str(self.total_pages)
        max_text = f"{max_page_num_str}/{max_page_num_str}"

        # 使用QFontMetrics计算文本宽度
        from PySide6.QtGui import QFontMetrics
        font = self.page_label.font()
        font_metrics = QFontMetrics(font)
        text_width = font_metrics.horizontalAdvance(max_text)

        # 添加一些边距（左右各10像素），不再乘以dpi_scale因为font_metrics已经考虑了DPI
        min_width = int(text_width + 20)
        self.page_label.setMinimumWidth(min_width)

    def _update_page_label(self):
        """
        更新页码标签
        """
        if self.total_pages > 0:
            self.page_label.setText(f"{self.current_page + 1}/{self.total_pages}")
        else:
            self.page_label.setText("0/0")
    
    def _update_button_states(self):
        """
        更新按钮状态
        """
        self.prev_button.setEnabled(self.current_page > 0)
        self.next_button.setEnabled(self.current_page < self.total_pages - 1)
    
    def _show_error(self, message: str):
        """
        显示错误信息
        
        Args:
            message: 错误消息
        """
        self._clear_page_widgets()
        
        error_label = QLabel(message)
        error_label.setAlignment(Qt.AlignCenter)
        # 使用全局字体，让Qt6自动处理DPI缩放
        error_font = QFont(self.global_font)
        error_font.setPointSize(int(self.global_font.pointSize() * 1.2))
        error_label.setFont(error_font)
        error_label.setStyleSheet("""
            QLabel {
                color: #FF4444;
            }
        """)
        self.content_layout.addWidget(error_label)
        
        # 发出渲染完成信号（虽然出错了，但需要通知统一预览器关闭进度条）
        self.pdf_render_finished.emit()
    
    def wheelEvent(self, event):
        """
        鼠标滚轮事件处理
        支持Ctrl+滚轮缩放，普通滚轮翻页
        """
        if event.modifiers() == Qt.ControlModifier:
            # Ctrl+滚轮缩放
            delta = event.angleDelta().y()
            if delta > 0:
                new_zoom = min(self.current_zoom + 10, self.zoom_max)
            else:
                new_zoom = max(self.current_zoom - 10, self.zoom_min)
            self.zoom_slider.setValue(new_zoom)
            event.accept()
        else:
            # 普通滚轮交给滚动区域处理
            super().wheelEvent(event)
    
    def resizeEvent(self, event):
        """
        窗口大小变化事件
        """
        super().resizeEvent(event)
        
        # 延迟更新页面大小，避免频繁重绘
        QTimer.singleShot(100, self._delayed_resize)
    
    def _delayed_resize(self):
        """
        延迟处理大小变化
        """
        if self.pdf_document:
            self._update_page_sizes()
            self.page_pixmaps.clear()
            self._render_visible_pages()
    
    def eventFilter(self, obj, event):
        """
        事件过滤器，处理预览区域的鼠标事件
        - 双击左键：重置缩放到100%
        - Ctrl+滚轮：缩放控制（阻止默认滚动行为）
        - 鼠标中键按下：开始拖动模式
        - 鼠标中键释放：结束拖动模式
        - 鼠标移动：在拖动模式下滚动内容

        Args:
            obj: 事件源对象
            event: 事件对象

        Returns:
            bool: 是否已处理事件
        """
        # 处理 content_widget 的双击事件
        if obj == self.content_widget:
            if event.type() == event.MouseButtonDblClick:
                if event.button() == Qt.LeftButton:
                    self.zoom_slider.setValue(self.zoom_default)
                    return True

        # 处理 scroll_area、viewport 和 content_widget 的滚轮事件
        if obj in (self.scroll_area, self.scroll_area.viewport(), self.content_widget):
            if event.type() == event.Wheel:
                # 当按下Ctrl时，阻止默认滚动行为，只进行缩放
                if event.modifiers() == Qt.ControlModifier:
                    delta = event.angleDelta().y()
                    if delta > 0:
                        new_zoom = min(self.current_zoom + 10, self.zoom_max)
                    else:
                        new_zoom = max(self.current_zoom - 10, self.zoom_min)
                    self.zoom_slider.setValue(new_zoom)
                    return True

        # 处理鼠标中键按下事件 - 开始拖动
        if obj in (self.scroll_area, self.scroll_area.viewport(), self.content_widget):
            if event.type() == event.MouseButtonPress:
                if event.button() == Qt.MiddleButton:
                    # 使用全局坐标避免坐标系转换问题
                    self._start_middle_button_drag(event.globalPos())
                    return True

        # 处理鼠标移动事件 - 执行拖动
        if obj in (self.scroll_area, self.scroll_area.viewport(), self.content_widget):
            if event.type() == event.MouseMove:
                if self._is_middle_button_dragging:
                    # 使用全局坐标避免坐标系转换问题
                    self._do_middle_button_drag(event.globalPos())
                    return True

        # 处理鼠标中键释放事件 - 结束拖动
        if obj in (self.scroll_area, self.scroll_area.viewport(), self.content_widget):
            if event.type() == event.MouseButtonRelease:
                if event.button() == Qt.MiddleButton:
                    self._end_middle_button_drag()
                    return True

        return super().eventFilter(obj, event)

    def _start_middle_button_drag(self, global_pos):
        """
        开始鼠标中键拖动

        Args:
            global_pos: 鼠标按下位置（全局坐标）
        """
        self._is_middle_button_dragging = True
        self._middle_button_drag_global_start_pos = global_pos
        # 记录当前滚动位置
        self._middle_button_drag_start_scroll_x = self.scroll_area.horizontalScrollBar().value()
        self._middle_button_drag_start_scroll_y = self.scroll_area.verticalScrollBar().value()
        # 更改光标为手型（表示可以拖动）
        self.scroll_area.viewport().setCursor(Qt.ClosedHandCursor)
        # 禁用平滑滚动（QScroller）以避免动画冲突
        viewport = self.scroll_area.viewport()
        QScroller.ungrabGesture(viewport)

    def _do_middle_button_drag(self, global_pos):
        """
        执行鼠标中键拖动滚动
        使用全局坐标计算偏移，避免坐标系转换导致的闪烁问题

        Args:
            global_pos: 当前鼠标位置（全局坐标）
        """
        if not self._is_middle_button_dragging or self._middle_button_drag_global_start_pos is None:
            return

        # 计算鼠标移动距离（相对于初始位置，使用全局坐标）
        delta_x = global_pos.x() - self._middle_button_drag_global_start_pos.x()
        delta_y = global_pos.y() - self._middle_button_drag_global_start_pos.y()

        # 反向滚动（拖动方向与滚动方向相反）
        new_scroll_x = self._middle_button_drag_start_scroll_x - delta_x
        new_scroll_y = self._middle_button_drag_start_scroll_y - delta_y

        # 应用滚动
        self.scroll_area.horizontalScrollBar().setValue(new_scroll_x)
        self.scroll_area.verticalScrollBar().setValue(new_scroll_y)

    def _end_middle_button_drag(self):
        """
        结束鼠标中键拖动
        """
        self._is_middle_button_dragging = False
        self._middle_button_drag_global_start_pos = None
        # 恢复默认光标
        self.scroll_area.viewport().setCursor(Qt.ArrowCursor)
        # 重新启用平滑滚动（QScroller）
        viewport = self.scroll_area.viewport()
        QScroller.grabGesture(viewport, QScroller.TouchGesture)

    def closeEvent(self, event):
        """
        关闭事件处理
        """
        self._close_document()
        super().closeEvent(event)
