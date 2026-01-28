#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeMediaClub
许可协议：https://github.com/Dorufoc/FreeMediaClub/blob/main/LICENSE

独立的PDF预览器组件
使用PyMuPDF (fitz)库进行PDF渲染
"""

import sys
import os

# 添加项目根目录到Python路径，解决直接运行时的导入问题
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
    QFileDialog, QLabel, QScrollArea, QGroupBox, QGridLayout,
    QComboBox, QFrame, QMessageBox, QSizePolicy
)
from PyQt5.QtGui import (
    QFont, QIcon, QPixmap, QImage
)
from PyQt5.QtCore import (
    Qt, QSize, QEvent, pyqtSignal, QPoint
)

# 导入自定义控件
from freeassetfilter.widgets.D_widgets import CustomButton
from freeassetfilter.widgets.progress_widgets import D_ProgressBar
from freeassetfilter.widgets.smooth_scroller import SmoothScroller, D_ScrollBar

# 尝试导入PyMuPDF (fitz)库，作为PDF渲染引擎
try:
    import fitz
    FITZ_AVAILABLE = True
except ImportError:
    FITZ_AVAILABLE = False


class PDFPreviewWidget(QWidget):
    """
    PDF预览部件，使用PyMuPDF (fitz)库进行PDF渲染
    """
    # 添加PDF渲染完成信号
    pdf_render_finished = pyqtSignal()
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 获取应用实例
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtGui import QFont
        app = QApplication.instance()
        
        # 获取全局字体
        self.global_font = getattr(app, 'global_font', QFont())
        
        # 获取DPI缩放因子
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        # 设置组件字体
        self.setFont(self.global_font)
        
        # 初始化所有属性
        self.current_file_path = ""
        self.pdf_document = None
        self.zoom = 1.0
        self.total_pages = 0
        self.current_page = 0
        self.rendered_pages = []
        self.preview_container = None
        self.pages_container = None
        self.pages_layout = None
        self.page_label = None
        self.zoom_slider = None
        self.prev_button = None
        self.next_button = None
        self._middle_click_dragging = False
        self._middle_click_start_pos = None
        self._scrollbar_start_values = None
        self._scroller = None
        
        # 初始化UI
        self.init_ui()
    
    def init_ui(self):
        """
        初始化预览部件UI
        """
        layout = QVBoxLayout(self)
        
        scaled_margin = int(10 * self.dpi_scale)
        scaled_spacing = int(8 * self.dpi_scale)
        layout.setContentsMargins(scaled_margin, scaled_margin, scaled_margin, scaled_margin)
        layout.setSpacing(scaled_spacing)
        
        app = QApplication.instance()
        background_color = "#2D2D2D"
        secondary_color = "#333333"
        if hasattr(app, 'settings_manager'):
            background_color = app.settings_manager.get_setting("appearance.colors.window_background", "#2D2D2D")
            secondary_color = app.settings_manager.get_setting("appearance.colors.secondary_color", "#333333")
        self.setStyleSheet(f"background-color: {background_color};")
        
        default_font_size = getattr(app, 'default_font_size', 18)
        scaled_font_size = int(default_font_size * self.dpi_scale)
        
        toolbar_layout = QHBoxLayout()
        toolbar_layout.setSpacing(scaled_spacing)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        
        icon_dir = os.path.join(os.path.dirname(__file__), '..', 'icons')
        prev_icon_path = os.path.join(icon_dir, "arrow_up.svg")
        next_icon_path = os.path.join(icon_dir, "arrow_down.svg")
        
        self.prev_button = CustomButton(prev_icon_path, button_type="normal", display_mode="icon", tooltip_text="上一页")
        self.prev_button.clicked.connect(self.prev_page)
        self.prev_button.setEnabled(False)
        toolbar_layout.addWidget(self.prev_button)
        
        self.page_label = QLabel("0/0")
        self.page_label.setFont(self.global_font)
        self.page_label.setStyleSheet(f"font-size: {scaled_font_size}px; color: {secondary_color}; font-weight: 500;")
        toolbar_layout.addWidget(self.page_label)
        
        self.next_button = CustomButton(next_icon_path, button_type="normal", display_mode="icon", tooltip_text="下一页")
        self.next_button.clicked.connect(self.next_page)
        self.next_button.setEnabled(False)
        toolbar_layout.addWidget(self.next_button)
        
        toolbar_layout.addStretch()
        
        zoom_label = QLabel("缩放:")
        zoom_label.setFont(self.global_font)
        zoom_label.setStyleSheet(f"font-size: {scaled_font_size}px; color: {secondary_color}; font-weight: 500;")
        toolbar_layout.addWidget(zoom_label)
        
        self.zoom_slider = D_ProgressBar(orientation=D_ProgressBar.Horizontal, is_interactive=True)
        self.zoom_slider.setRange(50, 300)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.zoom_slider.valueChanged.connect(self.change_zoom)
        toolbar_layout.addWidget(self.zoom_slider)
        
        layout.addLayout(toolbar_layout)
        
        self.preview_container = QScrollArea()
        self.preview_container.setWidgetResizable(True)
        scaled_min_width = int(100 * self.dpi_scale)
        scaled_min_height = int(100 * self.dpi_scale)
        self.preview_container.setMinimumSize(scaled_min_width, scaled_min_height)
        self.preview_container.setStyleSheet('''.QScrollArea {
            background-color: transparent;
            border: none;
        }
        .QScrollArea > QWidget > QWidget {
            background-color: transparent;
        }''')
        
        self.pages_container = QWidget()
        self.pages_layout = QVBoxLayout(self.pages_container)
        self.pages_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.pages_layout.setSpacing(scaled_spacing)
        self.pages_layout.setContentsMargins(0, 0, 0, 0)
        self.pages_container.setStyleSheet("background-color: transparent;")
        self.pages_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        
        self.preview_container.setWidget(self.pages_container)
        
        self.preview_container.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.preview_container.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.preview_container.setVerticalScrollBar(D_ScrollBar(self.preview_container, Qt.Vertical))
        self.preview_container.verticalScrollBar().apply_theme_from_settings()
        self.preview_container.setHorizontalScrollBar(D_ScrollBar(self.preview_container, Qt.Horizontal))
        self.preview_container.horizontalScrollBar().apply_theme_from_settings()
        self.preview_container.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)
        SmoothScroller.apply_to_scroll_area(self.preview_container)
        
        layout.addWidget(self.preview_container, 1)
        
        print(f"[DEBUG] PDFPreviewWidget UI组件设置字体: {self.global_font.family()}")
        
        self.preview_container.viewport().installEventFilter(self)
        self.installEventFilter(self)
    
    def eventFilter(self, obj, event):
        """
        事件过滤器，处理滚轮事件和窗口大小改变事件
        - Ctrl+滚轮：缩放功能
        - 普通滚轮：默认滚动功能
        - 窗口大小改变：重新计算适合预览区域的缩放值
        """
        try:
            if obj is self.preview_container.viewport() and event.type() == QEvent.Wheel:
                if event.modifiers() & Qt.ControlModifier:
                    # Ctrl+滚轮：处理缩放，拦截事件
                    delta = event.angleDelta().y()
                    # 计算当前缩放百分比
                    current_percent = int((self.zoom / self.base_zoom) * 100)
                    if delta > 0:
                        # 放大
                        new_percent = min(current_percent + 10, 300)
                    else:
                        # 缩小
                        new_percent = max(current_percent - 10, 50)
                    
                    # 更新缩放值和UI
                    self.zoom = (new_percent / 100.0) * self.base_zoom
                    self.zoom_slider.setValue(new_percent)
                    self.update_preview()
                    return True  # 拦截事件，不进行滚动
            elif obj is self and event.type() == QEvent.Resize:
                # 窗口大小改变时，重新计算适合预览区域的缩放值
                # 只在用户没有手动调整缩放的情况下执行
                if self.zoom_slider.value() == 100:
                    self._recalculate_fit_zoom()
        except Exception as e:
            print(f"处理事件时出错: {e}")
        # 普通滚轮：使用默认滚动行为，返回False表示不拦截
        return False
    
    def _recalculate_fit_zoom(self):
        """
        重新计算适合预览区域的缩放值
        """
        try:
            if self.pdf_document and self.total_pages > 0:
                # 获取第一个页面的尺寸
                page = self.pdf_document[0]
                page_rect = page.rect
                page_width = page_rect.width
                
                # 获取预览区域的可用宽度
                # 预览容器的宽度减去左右边距和页面内边距
                scaled_margin = int(10 * self.dpi_scale)
                scaled_padding = int(10 * self.dpi_scale)
                available_width = self.preview_container.width() - (2 * scaled_margin) - (2 * scaled_padding)
                
                # 计算新的基准缩放因子，使页面宽度适应可用宽度
                if available_width > 0:
                    # 更新基准缩放值
                    self.base_zoom = available_width / page_width
                    # 如果当前缩放是100%，更新缩放值
                    if self.zoom_slider.value() == 100:
                        self.zoom = self.base_zoom
                        self.update_preview()
        except Exception as e:
            print(f"重新计算缩放值时出错: {e}")
    
    def mousePressEvent(self, event):
        """
        鼠标按下事件 - 处理中键拖动
        """
        if event.button() == Qt.MiddleButton and self.pdf_document:
            self._middle_click_dragging = True
            self._middle_click_start_pos = event.pos()
            self._scrollbar_start_values = (
                self.preview_container.horizontalScrollBar().value(),
                self.preview_container.verticalScrollBar().value()
            )
            self.setCursor(Qt.ClosedHandCursor)
        else:
            super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        """
        鼠标移动事件 - 处理中键拖动
        """
        if self._middle_click_dragging and self._middle_click_start_pos:
            delta_x = self._middle_click_start_pos.x() - event.pos().x()
            delta_y = self._middle_click_start_pos.y() - event.pos().y()
            
            h_scroll = self.preview_container.horizontalScrollBar()
            v_scroll = self.preview_container.verticalScrollBar()
            
            h_scroll.setValue(self._scrollbar_start_values[0] + delta_x)
            v_scroll.setValue(self._scrollbar_start_values[1] + delta_y)
        else:
            super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event):
        """
        鼠标释放事件 - 结束中键拖动
        """
        if event.button() == Qt.MiddleButton and self._middle_click_dragging:
            self._middle_click_dragging = False
            self._middle_click_start_pos = None
            self._scrollbar_start_values = None
            self.setCursor(Qt.ArrowCursor)
        else:
            super().mouseReleaseEvent(event)
    
    def mouseDoubleClickEvent(self, event):
        """
        鼠标双击事件 - 重置缩放为默认适合大小
        """
        if self.pdf_document:
            self.zoom = self.base_zoom
            self.zoom_slider.setValue(100)
            self.update_preview()
        super().mouseDoubleClickEvent(event)
    
    def set_file(self, file_path):
        """
        设置要预览的PDF文件
        
        Args:
            file_path (str): PDF文件路径
        
        Returns:
            bool: 是否成功加载PDF文件
        """
        try:
            # 清除之前的预览
            self.clear_pages()
            
            if not FITZ_AVAILABLE:
                error_label = QLabel("错误：PyMuPDF (fitz)库未安装\n请运行 pip install PyMuPDF 安装")
                # 使用全局默认字体大小
                app = QApplication.instance()
                default_font_size = getattr(app, 'default_font_size', 18)
                scaled_font_size = int(default_font_size * self.dpi_scale)
                scaled_border_radius = int(8 * self.dpi_scale)
                scaled_padding = int(10 * self.dpi_scale)
                error_label.setStyleSheet(f"color: #d32f2f; font-size: {scaled_font_size}px; background-color: white; border: 1px solid #e0e0e0; border-radius: {scaled_border_radius}px; padding: {scaled_padding}px;")
                self.pages_layout.addWidget(error_label, alignment=Qt.AlignCenter)
                return False
            
            if os.path.exists(file_path) and file_path.lower().endswith('.pdf'):
                self.current_file_path = file_path
                
                # 打开PDF文件
                try:
                    self.pdf_document = fitz.open(file_path)
                    self.total_pages = len(self.pdf_document)
                    
                    # 计算适合预览区域的基准缩放值
                    if self.total_pages > 0:
                        # 获取第一个页面的尺寸
                        page = self.pdf_document[0]
                        page_rect = page.rect
                        page_width = page_rect.width
                        
                        # 获取预览区域的可用宽度
                        # 预览容器的宽度减去左右边距和页面内边距
                        scaled_margin = int(10 * self.dpi_scale)
                        scaled_padding = int(10 * self.dpi_scale)
                        available_width = self.preview_container.width() - (2 * scaled_margin) - (2 * scaled_padding)
                        
                        # 计算基准缩放因子，使页面宽度适应可用宽度
                        if available_width > 0:
                            self.base_zoom = available_width / page_width
                        else:
                            self.base_zoom = 1.0
                    else:
                        self.base_zoom = 1.0
                    
                    # 默认缩放为100%，即适合大小
                    self.zoom = self.base_zoom
                    self.current_page = 1
                    
                    # 更新UI
                    self.update_page_info()
                    self.zoom_slider.setValue(100)
                    self.render_all_pages()
                    self.update_navigation_buttons()
                    
                    return True
                except Exception as e:
                    error_label = QLabel(f"错误：无法打开PDF文件\n{str(e)}")
                    # 使用全局默认字体大小
                    app = QApplication.instance()
                    default_font_size = getattr(app, 'default_font_size', 18)
                    scaled_font_size = int(default_font_size * self.dpi_scale)
                    scaled_border_radius = int(4 * self.dpi_scale)
                    scaled_padding = int(10 * self.dpi_scale)
                    error_label.setStyleSheet(f"color: #d32f2f; font-size: {scaled_font_size}px; background-color: white; border: 1px solid #e0e0e0; border-radius: {scaled_border_radius}px; padding: {scaled_padding}px;")
                    self.pages_layout.addWidget(error_label, alignment=Qt.AlignCenter)
                    return False
            return False
        except Exception as e:
            print(f"设置PDF文件时出错: {e}")
            error_label = QLabel(f"错误：无法处理PDF文件\n{str(e)}")
            # 使用全局默认字体大小
            app = QApplication.instance()
            default_font_size = getattr(app, 'default_font_size', 18)
            scaled_font_size = int(default_font_size * self.dpi_scale)
            scaled_border_radius = int(8 * self.dpi_scale)
            scaled_padding = int(10 * self.dpi_scale)
            error_label.setStyleSheet(f"color: #d32f2f; font-size: {scaled_font_size}px; background-color: white; border: 1px solid #e0e0e0; border-radius: {scaled_border_radius}px; padding: {scaled_padding}px;")
            self.pages_layout.addWidget(error_label, alignment=Qt.AlignCenter)
            return False
    
    def clear_pages(self):
        """
        清空渲染的页面
        """
        try:
            for page_label in self.rendered_pages:
                page_label.deleteLater()
            self.rendered_pages.clear()
        except Exception as e:
            print(f"清除页面时出错: {e}")
    
    def render_all_pages(self):
        """
        渲染所有页面
        """
        try:
            if not self.pdf_document:
                return
            
            for page_num in range(self.total_pages):
                self.render_page(page_num)
            # 所有页面渲染完成，发出信号
            self.pdf_render_finished.emit()
        except Exception as e:
            print(f"渲染所有页面时出错: {e}")
            # 即使出错也发出信号，避免UI卡住
            self.pdf_render_finished.emit()
    
    def render_page(self, page_num):
        """
        渲染单个页面
        
        Args:
            page_num (int): 页码
        """
        try:
            # 获取页面
            page = self.pdf_document[page_num]
            
            # 获取设备像素比
            from PyQt5.QtGui import QGuiApplication
            device_pixel_ratio = QGuiApplication.primaryScreen().devicePixelRatio()
            
            # 设置渲染参数（考虑DPI）
            render_zoom = self.zoom * device_pixel_ratio
            mat = fitz.Matrix(render_zoom, render_zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            
            # 将Pixmap转换为QImage
            qimage = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
            
            # 将QImage转换为QPixmap并设置DPI
            pixmap = QPixmap.fromImage(qimage)
            pixmap.setDevicePixelRatio(device_pixel_ratio)
            
            # 创建页面标签并添加到布局
            page_label = QLabel()
            page_label.setPixmap(pixmap)
            page_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            page_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            
            # 使用DPI缩放因子调整页面样式
            scaled_border_radius = int(8 * self.dpi_scale)
            scaled_padding = int(20 * self.dpi_scale)
            page_label.setStyleSheet(f"background-color: white; border: 1px solid #e0e0e0; border-radius: {scaled_border_radius}px; padding: {scaled_padding}px;")
            
            self.pages_layout.addWidget(page_label, alignment=Qt.AlignVCenter | Qt.AlignLeft)
            self.rendered_pages.append(page_label)
            
        except Exception as e:
            error_label = QLabel(f"错误：无法渲染页 {page_num + 1}\n{str(e)}")
            scaled_font_size = int(14 * self.dpi_scale)
            scaled_border_radius = int(8 * self.dpi_scale)
            scaled_padding = int(10 * self.dpi_scale)
            error_label.setStyleSheet(f"color: #d32f2f; font-size: {scaled_font_size}px; background-color: white; border: 1px solid #e0e0e0; border-radius: {scaled_border_radius}px; padding: {scaled_padding}px;")
            self.pages_layout.addWidget(error_label, alignment=Qt.AlignCenter)
            self.rendered_pages.append(error_label)
    
    def update_page_info(self):
        """
        更新页码信息
        """
        try:
            if self.pdf_document:
                self.page_label.setText(f"{self.current_page}/{self.total_pages}")
        except Exception as e:
            print(f"更新页码信息时出错: {e}")
    
    def update_navigation_buttons(self):
        """
        更新导航按钮状态
        """
        try:
            if self.pdf_document and self.total_pages > 0:
                self.prev_button.setEnabled(True)
                self.next_button.setEnabled(True)
            else:
                self.prev_button.setEnabled(False)
                self.next_button.setEnabled(False)
        except Exception as e:
            print(f"更新导航按钮时出错: {e}")
    
    def update_preview(self):
        """
        更新PDF预览
        """
        try:
            if not self.pdf_document:
                return
            
            self.clear_pages()
            self.render_all_pages()
        except Exception as e:
            print(f"更新预览时出错: {e}")
    
    def change_zoom(self, value):
        """
        改变缩放比例
        """
        try:
            # 根据基准缩放值计算实际缩放值
            self.zoom = (value / 100.0) * self.base_zoom
            self.update_preview()
        except Exception as e:
            print(f"改变缩放时出错: {e}")
    
    def prev_page(self):
        """
        上一页
        """
        try:
            if self.current_page > 1:
                self.current_page -= 1
                self._scroll_to_page(self.current_page)
                self.update_page_info()
        except Exception as e:
            print(f"上一页操作时出错: {e}")
    
    def next_page(self):
        """
        下一页
        """
        try:
            if self.current_page < self.total_pages:
                self.current_page += 1
                self._scroll_to_page(self.current_page)
                self.update_page_info()
        except Exception as e:
            print(f"下一页操作时出错: {e}")
    
    def _scroll_to_page(self, page_num):
        """
        滚动到指定页码（平滑滚动）
        
        Args:
            page_num (int): 页码（从1开始）
        """
        try:
            if 1 <= page_num <= len(self.rendered_pages):
                from PyQt5.QtWidgets import QScroller
                target_page = self.rendered_pages[page_num - 1]
                target_pos = target_page.y() - int(10 * self.dpi_scale)
                target_y = max(0, target_pos)
                
                if self._scroller is None:
                    self._scroller = QScroller.scroller(self.preview_container)
                
                if self._scroller:
                    self._scroller.stop()
                    self._scroller.scrollTo(QPoint(0, target_y), 300)
                else:
                    scroll_bar = self.preview_container.verticalScrollBar()
                    scroll_bar.setValue(target_y)
        except Exception as e:
            print(f"滚动到指定页码时出错: {e}")
    
    def _on_scroll_changed(self, value):
        """
        滚动位置变化时自动检测当前可见页面
        """
        try:
            if not self.pdf_document or not self.rendered_pages:
                return
            
            viewport_top = value
            viewport_bottom = value + self.preview_container.viewport().height()
            
            visible_page = self.current_page
            for i, page_widget in enumerate(self.rendered_pages):
                page_top = page_widget.y()
                page_bottom = page_top + page_widget.height()
                page_center = (page_top + page_bottom) // 2
                
                if page_top <= viewport_bottom and page_bottom >= viewport_top:
                    if page_center >= viewport_top and page_center <= viewport_bottom:
                        visible_page = i + 1
                        break
            
            if visible_page != self.current_page:
                self.current_page = visible_page
                self.update_page_info()
        except Exception as e:
            print(f"检测当前页面时出错: {e}")
    
    def __del__(self):
        """
        析构函数，确保资源释放
        """
        try:
            if self.pdf_document:
                self.pdf_document.close()
        except Exception as e:
            print(f"析构时关闭PDF文档出错: {e}")


class PDFPreviewer(QWidget):
    """
    PDF预览器组件
    提供PDF文件的预览功能
    """
    # 添加PDF渲染完成信号，转发自PDFPreviewWidget
    pdf_render_finished = pyqtSignal()

    def __init__(self, parent=None):
        """
        初始化PDF预览器
        
        Args:
            parent: 父窗口部件
        """
        super().__init__(parent)
        
        # 获取应用实例
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtGui import QFont
        app = QApplication.instance()
        
        # 获取全局字体
        self.global_font = getattr(app, 'global_font', QFont())
        
        # 获取DPI缩放因子
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        # 设置组件字体
        self.setFont(self.global_font)
        
        # 初始化属性
        self.pdf_widget = None
        
        # 设置窗口属性
        self.setWindowTitle("PDF预览器")
        
        # 使用DPI缩放因子调整窗口大小
        scaled_min_width = int(150 * self.dpi_scale)
        scaled_min_height = int(240 * self.dpi_scale)
        self.setMinimumSize(scaled_min_width, scaled_min_height)
        
        # 创建UI组件
        self.init_ui()
    
    def init_ui(self):
        """
        初始化用户界面
        """
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 设置整体背景色
        # 获取主题颜色
        app = QApplication.instance()
        background_color = "#2D2D2D"  # 默认窗口背景色
        if hasattr(app, 'settings_manager'):
            background_color = app.settings_manager.get_setting("appearance.colors.window_background", "#2D2D2D")
        self.setStyleSheet(f"background-color: {background_color};")
        
        # PDF预览区域
        self.pdf_widget = PDFPreviewWidget()
         # 连接PDF渲染完成信号，转发到上层
        self.pdf_widget.pdf_render_finished.connect(self.pdf_render_finished.emit)
        main_layout.addWidget(self.pdf_widget)
    
    def open_file(self):
        """
        打开PDF文件
        """
        try:
            file_path, _ = QFileDialog.getOpenFileName(
                self, "打开PDF文件", "", 
                "PDF文件 (*.pdf);;所有文件 (*)"
            )
            
            if file_path:
                self.load_file_from_path(file_path)
        except Exception as e:
            print(f"打开文件时出错: {e}")
            from freeassetfilter.widgets.D_widgets import CustomMessageBox
            msg_box = CustomMessageBox(self)
            msg_box.set_title("错误")
            msg_box.set_text(f"打开文件时出错: {str(e)}")
            msg_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
            msg_box.exec_()
    
    def load_file_from_path(self, file_path):
        """
        从外部路径加载PDF文件
        
        Args:
            file_path (str): PDF文件路径
        
        Returns:
            bool: 是否成功加载PDF文件
        """
        try:
            if self.pdf_widget.set_file(file_path):
                # 更新窗口标题
                file_name = os.path.basename(file_path)
                self.setWindowTitle(f"PDF预览器 - {file_name}")
                return True
            return False
        except Exception as e:
            print(f"从路径加载PDF时出错: {e}")
            return False
    
    def set_file(self, file_path):
        """
        设置要显示的PDF文件
        
        Args:
            file_path (str): PDF文件路径
        
        Returns:
            bool: 是否成功加载PDF文件
        """
        return self.load_file_from_path(file_path)


# 命令行参数支持
if __name__ == "__main__":
    app = QApplication(sys.argv)
    viewer = PDFPreviewer()
    
    # 如果提供了文件路径参数，直接加载
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
        viewer.load_file_from_path(file_path)
    
    viewer.show()
    sys.exit(app.exec_())