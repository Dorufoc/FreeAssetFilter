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
使用 QPdfDocument 渲染页面到 QImage，然后使用自定义控件显示所有页面
全流程适配高DPI缩放
"""

import os
import sys

# 导入日志模块
from freeassetfilter.utils.app_logger import info, debug, warning, error
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QSizePolicy, QSpacerItem, QApplication, QFrame
)
from PySide6.QtCore import Qt, Signal, QTimer, QPoint, QSize
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QFont
from PySide6.QtPdf import QPdfDocument

# 导入自定义控件
from freeassetfilter.widgets.button_widgets import CustomButton
from freeassetfilter.widgets.progress_widgets import D_ProgressBar
from freeassetfilter.widgets.smooth_scroller import SmoothScroller, D_ScrollBar


class PDFPageWidget(QWidget):
    """
    单页PDF显示控件
    类似于 QML 的 PdfPageView，显示单页PDF内容
    支持高DPI显示
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 获取应用实例和DPI缩放因子
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        # 获取设备像素比
        self.device_pixel_ratio = self.devicePixelRatioF() if hasattr(self, 'devicePixelRatioF') else 1.0
        
        # 获取主题颜色
        self.base_color = "#F5F5F5"
        self.normal_color = "#CCCCCC"  # 默认边框颜色
        if hasattr(app, 'settings_manager'):
            self.base_color = app.settings_manager.get_setting("appearance.colors.base_color", "#F5F5F5")
            self.normal_color = app.settings_manager.get_setting("appearance.colors.normal_color", "#CCCCCC")
        
        # 页面数据
        self.page_pixmap = None
        self.page_number = 0
        self.original_size = QSize()  # 原始渲染尺寸（物理像素）
        self.current_zoom = 1.0  # 当前显示缩放比例（相对于原始渲染尺寸）
        
        # 初始化UI
        self._init_ui()
    
    def _init_ui(self):
        """初始化UI"""
        # 创建主布局，添加边距以显示边框
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(1, 1, 1, 1)  # 为边框留出空间
        self.layout.setSpacing(0)
        
        # 创建内部容器用于显示图片，这个容器有边框
        self.frame = QFrame(self)
        self.frame.setFrameShape(QFrame.StyledPanel)
        self.frame.setStyleSheet(f"""
            QFrame {{
                background-color: white;
                border: 1px solid {self.normal_color};
                border-radius: 4px;
            }}
        """)
        
        # 创建frame的内部布局
        frame_layout = QVBoxLayout(self.frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(0)
        
        # 创建图片显示标签
        self.image_label = QLabel(self.frame)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("background-color: transparent;")
        frame_layout.addWidget(self.image_label)
        
        # 将frame添加到主布局
        self.layout.addWidget(self.frame)
        
        # 设置主窗口背景色
        self.setStyleSheet(f"background-color: {self.base_color};")
    
    def set_page_pixmap(self, pixmap: QPixmap, page_number: int):
        """设置页面图片
        
        Args:
            pixmap: 页面图片（已经考虑了devicePixelRatio的高DPI图片）
            page_number: 页码
        """
        self.page_pixmap = pixmap
        self.page_number = page_number
        if pixmap:
            # 保存原始尺寸（逻辑像素）
            self.original_size = QSize(
                int(pixmap.width() / pixmap.devicePixelRatio()),
                int(pixmap.height() / pixmap.devicePixelRatio())
            )
            self._update_display()
    
    def set_zoom(self, zoom_factor: float):
        """设置缩放比例
        
        Args:
            zoom_factor: 缩放比例（1.0 = 原始尺寸）
        """
        self.current_zoom = zoom_factor
        self._update_display()
    
    def _update_display(self):
        """更新显示"""
        if self.page_pixmap:
            # 计算显示尺寸（逻辑像素）
            display_width = int(self.original_size.width() * self.current_zoom)
            display_height = int(self.original_size.height() * self.current_zoom)
            
            # 缩放图片到显示尺寸
            # 保持devicePixelRatio，确保高DPI显示清晰
            scaled_pixmap = self.page_pixmap.scaled(
                int(display_width * self.page_pixmap.devicePixelRatio()),
                int(display_height * self.page_pixmap.devicePixelRatio()),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            
            # 设置devicePixelRatio，让Qt正确处理高DPI显示
            scaled_pixmap.setDevicePixelRatio(self.page_pixmap.devicePixelRatio())
            
            self.image_label.setPixmap(scaled_pixmap)
            
            # 设置标签的固定大小为逻辑像素尺寸
            self.image_label.setFixedSize(display_width, display_height)
    
    def sizeHint(self):
        """返回建议大小"""
        if self.page_pixmap:
            return QSize(
                int(self.original_size.width() * self.current_zoom),
                int(self.original_size.height() * self.current_zoom)
            )
        return super().sizeHint()


class PDFPreviewer(QWidget):
    """
    PDF预览器主组件
    提供PDF文件的完整预览功能，包括页面导航、缩放控制等
    使用 QPdfDocument 渲染页面到 QImage，然后使用自定义控件从上到下显示所有页面
    全流程适配高DPI缩放
    
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
        
        # 获取设备像素比（在窗口显示后会更准确）
        self.device_pixel_ratio = self.devicePixelRatioF() if hasattr(self, 'devicePixelRatioF') else 1.0
        
        # 获取主题颜色
        self.secondary_color = "#333333"
        self.base_color = "#F5F5F5"
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
        
        # 页面渲染设置
        self.page_widgets = []  # 存储所有页面控件
        self.page_pixmaps = []  # 存储所有页面的原始pixmap
        self.render_options = None

        # 渲染DPI设置
        # 基础DPI为72（PDF标准），根据设备DPI和设备像素比计算实际渲染DPI
        self.base_render_dpi = 72

        # 缩放控制
        self.zoom_min = 50  # 最小50%（相对于适合显示的大小）
        self.zoom_max = 400  # 最大400%（相对于适合显示的大小）
        self.zoom_default = 100  # 默认100%（相对于适合显示的大小）
        self.current_zoom = self.zoom_default  # 当前显示的缩放百分比（相对于适合显示的大小）
        self.fit_to_width_zoom = 1.0  # 适合页面宽度的实际缩放因子
        self._user_zoom = None  # 用户手动设置的缩放值（None表示使用自适应缩放）

        # 鼠标中键拖动滚动
        self._middle_button_pressed = False
        self._last_mouse_pos = None

        # Ctrl键控制滚动/缩放
        self._ctrl_pressed = False

        # 初始化UI
        self._init_ui()
    
    def _init_ui(self):
        """初始化用户界面"""
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(int(5 * self.dpi_scale))
        main_layout.setContentsMargins(0, 0, 0, 0)

        # 创建控制栏
        self._create_control_bar()
        main_layout.addWidget(self.control_bar)

        # 创建内容预览区
        self._create_content_area()
        main_layout.addWidget(self.scroll_container, 1)

        # 设置字体
        self.setFont(self.global_font)
    
    def _create_control_bar(self):
        """创建控制栏"""
        self.control_bar = QWidget()
        self.control_bar.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        
        control_layout = QHBoxLayout(self.control_bar)
        control_layout.setSpacing(5)
        control_layout.setContentsMargins(6, 4, 2, 6)
        
        # 上一页按钮
        self.prev_button = CustomButton(
            self.arrow_left_icon,
            parent=self.control_bar,
            button_type="normal",
            display_mode="icon",
            height=20,
            tooltip_text="上一页"
        )
        self.prev_button.clicked.connect(self._go_to_prev_page)
        control_layout.addWidget(self.prev_button)
        
        # 页码标签
        self.page_label = QLabel("0/0")
        self.page_label.setAlignment(Qt.AlignCenter)
        self.page_label.setFont(self.global_font)
        self.page_label.setStyleSheet(f"""
            QLabel {{
                color: {self.secondary_color};
            }}
        """)
        control_layout.addWidget(self.page_label)
        
        # 下一页按钮
        self.next_button = CustomButton(
            self.arrow_right_icon,
            parent=self.control_bar,
            button_type="normal",
            display_mode="icon",
            height=20,
            tooltip_text="下一页"
        )
        self.next_button.clicked.connect(self._go_to_next_page)
        control_layout.addWidget(self.next_button)
        
        # 添加弹性空间
        control_layout.addSpacerItem(
            QSpacerItem(5, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)
        )

        # 缩放标签
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
        # 先连接信号，再设置值，但使用 blockSignals 避免触发初始信号
        self.zoom_slider.valueChanged.connect(self._on_zoom_changed)
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(self.zoom_default)
        self.zoom_slider.blockSignals(False)
        control_layout.addWidget(self.zoom_slider)
    
    def _create_content_area(self):
        """创建内容预览区 - 使用滚动区域显示所有页面"""
        # 创建外层容器，用于添加3px内边距
        self.scroll_container = QWidget(self)
        self.scroll_container.setStyleSheet(f"background-color: {self.base_color};")
        scroll_container_layout = QVBoxLayout(self.scroll_container)
        scroll_container_layout.setContentsMargins(6, 6, 6, 6)  # 6px内边距
        scroll_container_layout.setSpacing(0)

        # 创建滚动区域
        self.scroll_area = QScrollArea(self.scroll_container)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        # 设置整个滚动区域的背景色（包括视口和滚动条区域）
        self.scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background-color: {self.base_color};
                border: none;
            }}
            QScrollArea > QWidget > QWidget {{
                background-color: {self.base_color};
            }}
        """)

        # 启用鼠标跟踪以接收鼠标移动事件
        self.scroll_area.viewport().setMouseTracking(True)

        # 应用丝滑滚动
        SmoothScroller.apply(self.scroll_area, enable_mouse_drag=False)

        # 设置自定义滚动条
        self.scroll_area.setVerticalScrollBar(D_ScrollBar(self.scroll_area, Qt.Vertical))
        self.scroll_area.verticalScrollBar().apply_theme_from_settings()
        self.scroll_area.setHorizontalScrollBar(D_ScrollBar(self.scroll_area, Qt.Horizontal))
        self.scroll_area.horizontalScrollBar().apply_theme_from_settings()

        # 为滚动区域的 viewport 安装事件过滤器，用于处理鼠标中键拖动
        self.scroll_area.viewport().installEventFilter(self)

        # 创建内容容器
        self.content_container = QWidget()
        self.content_container.setStyleSheet(f"background-color: {self.base_color};")
        self.content_layout = QVBoxLayout(self.content_container)
        self.content_layout.setSpacing(int(10 * self.dpi_scale))
        self.content_layout.setContentsMargins(
            int(10 * self.dpi_scale),
            int(10 * self.dpi_scale),
            int(10 * self.dpi_scale),
            int(10 * self.dpi_scale)
        )
        self.content_layout.setAlignment(Qt.AlignHCenter | Qt.AlignTop)

        # 设置内容容器到滚动区域
        self.scroll_area.setWidget(self.content_container)

        # 将滚动区域添加到外层容器
        scroll_container_layout.addWidget(self.scroll_area)

        # 创建 PDF 文档对象
        self.pdf_document = QPdfDocument(self)
    
    def set_file(self, file_info):
        """设置要预览的文件（统一预览器接口）"""
        if isinstance(file_info, dict):
            file_path = file_info.get("path", "")
        else:
            file_path = str(file_info)
        
        self.load_file_from_path(file_path)
    
    def load_file_from_path(self, file_path: str):
        """从文件路径加载PDF"""
        if not file_path or not os.path.exists(file_path):
            self._show_error("文件不存在")
            return
        
        # 关闭之前的文档
        self._close_document()
        
        try:
            # 使用 QtPDF 加载文档
            self.file_path = file_path
            self.pdf_document.load(file_path)
            
            # 获取总页数
            self.total_pages = self.pdf_document.pageCount()
            self.current_page = 0
            
            # 清空现有页面
            self._clear_pages()
            
            # 渲染所有页面
            self._render_all_pages()
            
            # 更新UI
            self._update_page_label()
            self._update_button_states()
            
            # 延迟计算适合页面宽度的缩放比例
            QTimer.singleShot(10, self._calculate_fit_to_width_zoom)
            
            # 发出渲染完成信号
            self.pdf_render_finished.emit()
            
        except Exception as e:
            error(f"[ERROR] 加载PDF失败: {e}")
            self._show_error(f"加载PDF失败: {str(e)}")
    
    def _clear_pages(self):
        """清空所有页面控件"""
        # 清除布局中的所有控件
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        self.page_widgets.clear()
        self.page_pixmaps.clear()
    
    def _get_device_pixel_ratio(self) -> float:
        """获取设备像素比"""
        # 优先使用当前窗口的设备像素比
        if self.window():
            return self.window().devicePixelRatioF() if hasattr(self.window(), 'devicePixelRatioF') else 1.0
        # 否则使用应用程序的设备像素比
        app = QApplication.instance()
        if app:
            return app.devicePixelRatio() if hasattr(app, 'devicePixelRatio') else 1.0
        return 1.0
    
    def _get_render_dpi(self) -> float:
        """计算渲染DPI
        
        根据设备DPI和设备像素比计算实际渲染DPI
        确保在高DPI显示器上渲染清晰
        """
        # 获取设备像素比
        dpr = self._get_device_pixel_ratio()
        
        # 获取屏幕DPI
        logical_dpi = self.logicalDpiX() if self.logicalDpiX() > 0 else 96
        physical_dpi = self.physicalDpiX() if self.physicalDpiX() > 0 else 96
        
        # 基础渲染DPI：使用逻辑DPI（通常是96）乘以设备像素比
        # 这样可以确保在高DPI显示器上渲染的图像有足够的分辨率
        render_dpi = logical_dpi * dpr
        
        # 为了获得更好的质量，额外增加一些分辨率（1.5倍超采样）
        render_dpi = render_dpi * 1.5
        
        # 限制最大渲染DPI以避免内存问题（最大400 DPI）
        render_dpi = min(render_dpi, 400)
        
        return render_dpi
    
    def _render_all_pages(self):
        """渲染所有PDF页面"""
        if self.total_pages == 0:
            return
        
        # 获取渲染DPI
        render_dpi = self._get_render_dpi()
        
        # 获取设备像素比
        dpr = self._get_device_pixel_ratio()
        
        for page_num in range(self.total_pages):
            # 获取页面尺寸（点，1/72英寸）
            page_size = self.pdf_document.pagePointSize(page_num)
            if not page_size:
                continue
            
            # 计算渲染尺寸（物理像素）
            # PDF使用72 DPI作为基础，需要转换到目标渲染DPI
            page_width_pt = page_size.width()
            page_height_pt = page_size.height()
            
            # 计算物理像素尺寸
            render_width_px = int(page_width_pt * render_dpi / 72.0)
            render_height_px = int(page_height_pt * render_dpi / 72.0)
            
            # 渲染页面到 QImage
            image = self.pdf_document.render(page_num, QSize(render_width_px, render_height_px))
            
            if image.isNull():
                warning(f"[PDFPreviewer] 页面 {page_num + 1} 渲染失败")
                continue
            
            # 设置图像的设备像素比
            # 这样Qt会正确处理高DPI显示
            image.setDevicePixelRatio(dpr)
            
            # 转换为 QPixmap
            pixmap = QPixmap.fromImage(image)
            
            # 设置pixmap的设备像素比
            pixmap.setDevicePixelRatio(dpr)
            
            self.page_pixmaps.append(pixmap)
            
            # 创建页面控件
            page_widget = PDFPageWidget(self.content_container)
            page_widget.set_page_pixmap(pixmap, page_num)
            
            self.page_widgets.append(page_widget)
            self.content_layout.addWidget(page_widget)
    
    def _calculate_fit_to_width_zoom(self, force=False):
        """计算适合页面显示的缩放因子，并将其设为100%基准
        无论用户是否手动设置了缩放比例，基准100%都会随视口大小实时变化

        Args:
            force: 是否强制重新计算
        """
        if self.total_pages == 0 or len(self.page_widgets) == 0:
            return

        # 记录用户之前设置的缩放比例（如果有）
        previous_user_zoom = self._user_zoom
        if previous_user_zoom is None:
            previous_user_zoom = 100  # 默认100%

        try:
            # 获取第一页的尺寸（逻辑像素）
            first_page_widget = self.page_widgets[0]
            original_size = first_page_widget.original_size
            
            if original_size.isEmpty():
                return

            # 获取视口尺寸（逻辑像素）
            viewport_width = self.scroll_area.viewport().width()
            viewport_height = self.scroll_area.viewport().height()

            # 如果视口尺寸无效，延迟再次尝试
            if viewport_width < 50 or viewport_height < 50:
                QTimer.singleShot(50, lambda: self._calculate_fit_to_width_zoom(force))
                return

            # 考虑边距
            margins = int(40 * self.dpi_scale)  # 左右边距总和
            available_width = max(viewport_width - margins, 100)
            available_height = max(viewport_height - margins, 100)

            page_width = original_size.width()
            page_height = original_size.height()

            # 计算适合宽度和适合高度的缩放比例
            fit_width_zoom = available_width / page_width
            fit_height_zoom = available_height / page_height

            # 选择较小的缩放比例，确保页面完整显示在区域内
            if page_width > page_height:
                # 横向页面，优先适合高度
                fit_zoom_factor = min(fit_width_zoom, fit_height_zoom)
            else:
                # 纵向页面，优先适合宽度
                fit_zoom_factor = fit_width_zoom

            # 保存适合显示的缩放因子
            self.fit_to_width_zoom = fit_zoom_factor

            # 计算实际缩放因子 = 基准缩放因子 * (用户设置百分比 / 100)
            actual_zoom_factor = self.fit_to_width_zoom * (previous_user_zoom / 100.0)

            # 应用缩放到所有页面
            self._apply_zoom_to_all_pages(actual_zoom_factor)

            # 更新滑块和标签（不触发valueChanged信号）
            self.zoom_slider.blockSignals(True)
            self.zoom_slider.setValue(previous_user_zoom)
            self.zoom_slider.blockSignals(False)
            self.zoom_label.setText(f"{previous_user_zoom}%")

            # 保持用户设置的缩放值（用于后续resize时保持比例）
            self._user_zoom = previous_user_zoom if previous_user_zoom != 100 else None
            self.current_zoom = previous_user_zoom

        except Exception as e:
            warning(f"[PDFPreviewer] 计算适合显示缩放失败: {e}")
            import traceback
            traceback.print_exc()
            # 使用默认100%（缩放因子1.0）
            self.fit_to_width_zoom = 1.0
            self.current_zoom = 100
            self._apply_zoom_to_all_pages(1.0)
    
    def _apply_zoom_to_all_pages(self, zoom_factor: float):
        """应用缩放到所有页面"""
        for page_widget in self.page_widgets:
            page_widget.set_zoom(zoom_factor)
    
    def _close_document(self):
        """关闭当前PDF文档并清理资源"""
        if self.pdf_document:
            self.pdf_document.close()
        
        self._clear_pages()
        self.file_path = None
        self.total_pages = 0
        self.current_page = 0
    
    def _go_to_prev_page(self):
        """跳转到上一页"""
        if self.current_page > 0:
            self._go_to_page(self.current_page - 1)
    
    def _go_to_next_page(self):
        """跳转到下一页"""
        if self.current_page < self.total_pages - 1:
            self._go_to_page(self.current_page + 1)
    
    def _go_to_page(self, page_num: int):
        """跳转到指定页面"""
        if page_num < 0 or page_num >= self.total_pages:
            return

        self.current_page = page_num

        # 滚动到指定页面顶部
        if page_num < len(self.page_widgets):
            page_widget = self.page_widgets[page_num]
            # 计算页面在内容容器中的位置
            # 使用 mapTo 获取相对于 content_container 的位置
            widget_pos = page_widget.mapTo(self.content_container, QPoint(0, 0))
            # 获取垂直滚动条并设置值，使页面顶部对齐视口顶部
            # 考虑内容容器的上边距
            target_y = widget_pos.y()
            v_scrollbar = self.scroll_area.verticalScrollBar()
            v_scrollbar.setValue(target_y)

        # 更新UI
        self._update_page_label()
        self._update_button_states()
    
    def _on_zoom_changed(self, value: int):
        """缩放值变化处理
        
        value: 用户设置的缩放百分比（相对于适合显示的大小，100% = 适合显示）
        """
        self.current_zoom = value
        self._user_zoom = value  # 记录用户手动设置的缩放值
        self.zoom_label.setText(f"{value}%")
        
        # 计算实际缩放因子 = 适合显示的缩放因子 * (用户设置百分比 / 100)
        actual_zoom_factor = self.fit_to_width_zoom * (value / 100.0)
        
        # 应用缩放到所有页面
        self._apply_zoom_to_all_pages(actual_zoom_factor)
    
    def _update_page_label(self):
        """更新页码标签"""
        if self.total_pages > 0:
            self.page_label.setText(f"{self.current_page + 1}/{self.total_pages}")
        else:
            self.page_label.setText("0/0")
    
    def _update_button_states(self):
        """更新按钮状态"""
        self.prev_button.setEnabled(self.current_page > 0)
        self.next_button.setEnabled(self.current_page < self.total_pages - 1)
    
    def _show_error(self, message: str):
        """显示错误信息"""
        # 清除现有页面
        self._clear_pages()
        
        error_label = QLabel(message)
        error_label.setAlignment(Qt.AlignCenter)
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
        """鼠标滚轮事件处理 - 支持Ctrl+滚轮缩放，Ctrl按下时禁用滚动"""
        # 检查Ctrl键是否按下（使用事件修饰符或追踪的状态）
        ctrl_pressed = (event.modifiers() == Qt.ControlModifier) or self._ctrl_pressed

        if ctrl_pressed:
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
        """窗口大小变化事件处理 - 重新计算适合宽度的缩放"""
        super().resizeEvent(event)

        # 如果已加载PDF，始终重新计算基准缩放（不受用户缩放设置影响）
        if self.pdf_document and self.total_pages > 0:
            # 取消之前的延迟调用（如果有）
            if hasattr(self, '_resize_timer'):
                self._resize_timer.stop()
            else:
                self._resize_timer = QTimer(self)
                self._resize_timer.setSingleShot(True)
                self._resize_timer.timeout.connect(lambda: self._calculate_fit_to_width_zoom(force=True))

            # 使用延迟，等待布局完成
            self._resize_timer.start(100)
    
    def eventFilter(self, obj, event):
        """事件过滤器 - 处理鼠标中键拖动滚动、双击重置缩放、Ctrl键状态和滚轮事件"""
        if obj == self.scroll_area.viewport():
            # 处理滚轮事件（在SmoothScroller之前拦截）
            if event.type() == event.Type.Wheel:
                # 检查Ctrl键是否按下
                ctrl_pressed = (event.modifiers() == Qt.ControlModifier) or self._ctrl_pressed

                if ctrl_pressed:
                    # Ctrl+滚轮缩放，阻止滚动
                    delta = event.angleDelta().y()
                    if delta > 0:
                        new_zoom = min(self.current_zoom + 10, self.zoom_max)
                    else:
                        new_zoom = max(self.current_zoom - 10, self.zoom_min)
                    self.zoom_slider.setValue(new_zoom)
                    event.accept()
                    return True  # 阻止事件继续传播
                # 如果没有按Ctrl，让事件继续传播给SmoothScroller处理滚动

            elif event.type() == event.Type.MouseButtonPress:
                if event.button() == Qt.MiddleButton:
                    # 中键按下，开始拖动
                    self._middle_button_pressed = True
                    self._last_mouse_pos = event.pos()
                    # 改变光标为手型，提示用户可以拖动
                    self.scroll_area.viewport().setCursor(Qt.ClosedHandCursor)
                    return True

            elif event.type() == event.Type.MouseMove:
                if self._middle_button_pressed and self._last_mouse_pos:
                    # 计算鼠标移动距离
                    delta = event.pos() - self._last_mouse_pos
                    self._last_mouse_pos = event.pos()

                    # 获取当前滚动条位置
                    h_scrollbar = self.scroll_area.horizontalScrollBar()
                    v_scrollbar = self.scroll_area.verticalScrollBar()

                    # 反向滚动（拖动方向与滚动方向相反）
                    h_scrollbar.setValue(h_scrollbar.value() - delta.x())
                    v_scrollbar.setValue(v_scrollbar.value() - delta.y())

                    return True

            elif event.type() == event.Type.MouseButtonRelease:
                if event.button() == Qt.MiddleButton and self._middle_button_pressed:
                    # 中键释放，结束拖动
                    self._middle_button_pressed = False
                    self._last_mouse_pos = None
                    # 恢复默认光标
                    self.scroll_area.viewport().unsetCursor()
                    return True

            elif event.type() == event.Type.MouseButtonDblClick:
                if event.button() == Qt.LeftButton:
                    # 左键双击，重置缩放到100%
                    self._reset_zoom_to_100()
                    return True

        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        """键盘按下事件 - 检测Ctrl键"""
        if event.key() == Qt.Key_Control:
            self._ctrl_pressed = True
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        """键盘释放事件 - 检测Ctrl键释放"""
        if event.key() == Qt.Key_Control:
            self._ctrl_pressed = False
        super().keyReleaseEvent(event)

    def _reset_zoom_to_100(self):
        """重置缩放到100%"""
        # 清除用户设置的缩放值，使用默认100%
        self._user_zoom = None
        self.current_zoom = 100

        # 更新滑块和标签
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(100)
        self.zoom_slider.blockSignals(False)
        self.zoom_label.setText("100%")

        # 重新计算适合宽度的缩放并应用
        if self.pdf_document and self.total_pages > 0:
            self._calculate_fit_to_width_zoom(force=True)

    def closeEvent(self, event):
        """关闭事件处理"""
        self._close_document()
        super().closeEvent(event)
