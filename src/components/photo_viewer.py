#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

独立的照片查看器组件
提供图片查看、像素信息显示和缩放功能
"""

import sys
import os
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QFileDialog, QLabel, QScrollArea, QGroupBox, QGridLayout,
    QMenu, QMessageBox
)
from PyQt5.QtGui import (
    QImage, QPixmap, QPainter, QPen, QColor, QCursor,
    QFont, QIcon
)
from PyQt5.QtCore import (
    Qt, QPoint, QRect, QSize, QTimer, pyqtSignal, QMimeData, QUrl
)


class ImageWidget(QWidget):
    """
    图片显示部件，支持缩放、像素信息显示等功能
    """
    pixel_info_changed = pyqtSignal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        
        # 初始化所有属性，确保在使用前都被定义
        self.original_image = None
        self.scaled_image = None
        self.pixmap = None
        self.scale_factor = 1.0
        self.min_scale = 0.1
        self.max_scale = 10.0
        self.is_panning = False
        self.last_mouse_pos = QPoint()
        self.pan_offset = QPoint()
        self.mouse_pos = QPoint()
        self.current_file_path = ""
        
        # 像素信息
        self.pixel_info = {
            'x': 0, 'y': 0,
            'r': 0, 'g': 0, 'b': 0,
            'hex': '#000000'
        }
    
    def set_image(self, image_path):
        """
        设置要显示的图片
        
        Args:
            image_path (str): 图片文件路径
        
        Returns:
            bool: 是否成功加载图片
        """
        try:
            if not os.path.exists(image_path):
                return False
            
            self.original_image = QImage(image_path)
            if not self.original_image.isNull():
                # 保存当前文件路径
                self.current_file_path = image_path
                # 重置平移参数
                self.pan_offset = QPoint()
                # 计算自适应缩放因子
                self.calculate_fit_scale()
                self.update_image()
                self.update()
                return True
            return False
        except Exception as e:
            print(f"加载图片时出错: {e}")
            return False
    
    def calculate_fit_scale(self):
        """
        计算自适应缩放因子，使图片完整显示在控件中
        """
        try:
            if self.original_image:
                # 获取父控件的大小（滚动区域的视口大小）
                parent_size = self.parent().viewport().size() if hasattr(self.parent(), 'viewport') else self.parent().size() if self.parent() else QSize(800, 600)
                available_width = parent_size.width() - 20  # 留出一些边距
                available_height = parent_size.height() - 20
                
                # 计算缩放因子
                image_width = self.original_image.width()
                image_height = self.original_image.height()
                
                if image_width > 0 and image_height > 0:
                    width_ratio = available_width / image_width
                    height_ratio = available_height / image_height
                    
                    # 选择较小的缩放因子，确保图片完全适应
                    self.scale_factor = min(width_ratio, height_ratio)
                    
                    # 确保不小于最小缩放比例
                    self.scale_factor = max(self.scale_factor, self.min_scale)
        except Exception as e:
            print(f"计算自适应缩放时出错: {e}")
            # 使用默认缩放因子
            self.scale_factor = 1.0
    
    def update_image(self):
        """
        更新缩放后的图片
        """
        try:
            if self.original_image:
                # 计算缩放后的大小
                scaled_size = self.original_image.size() * self.scale_factor
                self.scaled_image = self.original_image.scaled(
                    scaled_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                self.pixmap = QPixmap.fromImage(self.scaled_image)
                
                # 更新窗口大小
                parent_size = self.parent().viewport().size() if hasattr(self.parent(), 'viewport') else self.parent().size() if self.parent() else QSize(800, 600)
                self.setMinimumSize(
                    max(scaled_size.width(), parent_size.width()),
                    max(scaled_size.height(), parent_size.height())
                )
        except Exception as e:
            print(f"更新图片时出错: {e}")
    
    def paintEvent(self, event):
        """
        绘制图片
        """
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(40, 40, 40))
        
        if self.pixmap and self.scaled_image:
            try:
                # 计算绘制位置（居中）
                rect = self.rect()
                image_rect = QRect(
                    rect.center().x() - self.scaled_image.width() // 2 + self.pan_offset.x(),
                    rect.center().y() - self.scaled_image.height() // 2 + self.pan_offset.y(),
                    self.scaled_image.width(),
                    self.scaled_image.height()
                )
                
                # 绘制图片
                painter.drawPixmap(image_rect, self.pixmap)
                
                # 绘制当前鼠标位置的十字线
                if self.is_valid_pixel_position(self.mouse_pos):
                    pen = QPen(QColor(255, 255, 255), 1, Qt.DotLine)
                    pen.setWidth(1)
                    painter.setPen(pen)
                    
                    # 十字线
                    painter.drawLine(
                        image_rect.left(), self.mouse_pos.y(),
                        image_rect.right(), self.mouse_pos.y()
                    )
                    painter.drawLine(
                        self.mouse_pos.x(), image_rect.top(),
                        self.mouse_pos.x(), image_rect.bottom()
                    )
            except Exception as e:
                print(f"绘制图片时出错: {e}")
        painter.end()
    
    def mousePressEvent(self, event):
        """
        鼠标按下事件
        """
        try:
            if event.button() == Qt.LeftButton:
                # 左键拖动图片
                self.is_panning = True
                self.last_mouse_pos = event.pos()
                self.setCursor(QCursor(Qt.ClosedHandCursor))
                # 如果点击在有效像素位置，更新像素信息
                if self.is_valid_pixel_position(event.pos()):
                    self.update_pixel_info(event.pos())
        except Exception as e:
            print(f"处理鼠标按下事件时出错: {e}")
    
    def mouseReleaseEvent(self, event):
        """
        鼠标释放事件
        """
        try:
            if event.button() == Qt.LeftButton:
                self.is_panning = False
                self.setCursor(QCursor(Qt.ArrowCursor))
        except Exception as e:
            print(f"处理鼠标释放事件时出错: {e}")
    
    def mouseMoveEvent(self, event):
        """
        鼠标移动事件
        """
        try:
            self.mouse_pos = event.pos()
            
            if self.is_panning:
                # 处理平移
                delta = event.pos() - self.last_mouse_pos
                self.pan_offset += delta
                self.last_mouse_pos = event.pos()
                self.update()
            else:
                # 更新像素信息
                if self.is_valid_pixel_position(self.mouse_pos):
                    self.update_pixel_info(self.mouse_pos)
        except Exception as e:
            print(f"处理鼠标移动事件时出错: {e}")
    
    def wheelEvent(self, event):
        """
        鼠标滚轮事件（缩放）
        """
        try:
            # 无论鼠标是否在图片上，都可以进行缩放
            if self.original_image and self.scaled_image:
                # 计算鼠标在图片中的位置
                rect = self.rect()
                image_rect = QRect(
                    rect.center().x() - self.scaled_image.width() // 2 + self.pan_offset.x(),
                    rect.center().y() - self.scaled_image.height() // 2 + self.pan_offset.y(),
                    self.scaled_image.width(),
                    self.scaled_image.height()
                )
                
                # 计算鼠标在图片上的相对位置（如果鼠标在图片外，使用图片中心）
                if image_rect.contains(event.pos()):
                    mouse_in_image = event.pos() - image_rect.topLeft()
                    mouse_in_original = mouse_in_image / self.scale_factor
                else:
                    # 鼠标在图片外，使用图片中心作为缩放点
                    mouse_in_image = QPoint(self.scaled_image.width() // 2, self.scaled_image.height() // 2)
                    mouse_in_original = mouse_in_image / self.scale_factor
                    
                # 缩放
                delta = 1.1 if event.angleDelta().y() > 0 else 0.9
                new_scale = self.scale_factor * delta
                
                # 限制缩放范围
                if self.min_scale <= new_scale <= self.max_scale:
                    self.scale_factor = new_scale
                    self.update_image()
                    
                    # 调整平移偏移，使鼠标指向的点保持不变
                    new_mouse_in_image = mouse_in_original * self.scale_factor
                    self.pan_offset += mouse_in_image - new_mouse_in_image
                    
                    self.update()
        except Exception as e:
            print(f"处理鼠标滚轮事件时出错: {e}")
        
        # 阻止滚轮事件传递给滚动条
        event.accept()
    
    def mouseDoubleClickEvent(self, event):
        """
        鼠标双击事件（重置缩放）
        """
        try:
            if event.button() == Qt.LeftButton:
                self.reset_view()
        except Exception as e:
            print(f"处理鼠标双击事件时出错: {e}")
    
    def contextMenuEvent(self, event):
        """
        右键菜单事件
        """
        try:
            menu = QMenu()
            
            # 复制色度值
            copy_color_action = menu.addAction("复制色度值")
            copy_color_action.triggered.connect(self.copy_color_value)
            
            # 复制文件路径
            if self.current_file_path:
                copy_path_action = menu.addAction("复制文件路径")
                copy_path_action.triggered.connect(self.copy_file_path)
                
                # 复制文件名
                copy_name_action = menu.addAction("复制文件名")
                copy_name_action.triggered.connect(self.copy_file_name)
                
                # 复制文件本身（这里只是提示，实际复制需要更复杂的实现）
                copy_file_action = menu.addAction("复制文件")
                copy_file_action.triggered.connect(self.copy_file)
            
            menu.exec_(event.globalPos())
        except Exception as e:
            print(f"显示右键菜单时出错: {e}")
    
    def copy_color_value(self):
        """
        复制当前像素的色度值
        """
        try:
            clipboard = QApplication.clipboard()
            color_value = f"RGB({self.pixel_info['r']}, {self.pixel_info['g']}, {self.pixel_info['b']})\n"
            color_value += f"HEX: {self.pixel_info['hex']}\n"
            color_value += f"坐标: ({self.pixel_info['x']}, {self.pixel_info['y']})"
            clipboard.setText(color_value)
        except Exception as e:
            print(f"复制色度值时出错: {e}")
    
    def copy_file_path(self):
        """
        复制当前文件的完整路径
        """
        try:
            if self.current_file_path:
                clipboard = QApplication.clipboard()
                clipboard.setText(self.current_file_path)
        except Exception as e:
            print(f"复制文件路径时出错: {e}")
    
    def copy_file_name(self):
        """
        复制当前文件的文件名
        """
        try:
            if self.current_file_path:
                clipboard = QApplication.clipboard()
                clipboard.setText(os.path.basename(self.current_file_path))
        except Exception as e:
            print(f"复制文件名时出错: {e}")
    
    def copy_file(self):
        """
        复制文件本身
        """
        try:
            if self.current_file_path and os.path.exists(self.current_file_path):
                # 这里只是复制文件路径到剪贴板
                # 实际复制文件需要使用 QMimeData 和 QClipboard.setMimeData
                clipboard = QApplication.clipboard()
                mime_data = QMimeData()
                url = QUrl.fromLocalFile(self.current_file_path)
                mime_data.setUrls([url])
                clipboard.setMimeData(mime_data)
        except Exception as e:
            print(f"复制文件时出错: {e}")
    
    def is_valid_pixel_position(self, pos):
        """
        检查给定位置是否在有效像素范围内
        """
        try:
            if not self.original_image or not self.scaled_image:
                return False
            
            # 计算图片显示区域
            rect = self.rect()
            image_rect = QRect(
                rect.center().x() - self.scaled_image.width() // 2 + self.pan_offset.x(),
                rect.center().y() - self.scaled_image.height() // 2 + self.pan_offset.y(),
                self.scaled_image.width(),
                self.scaled_image.height()
            )
            
            return image_rect.contains(pos)
        except Exception as e:
            print(f"检查像素位置时出错: {e}")
            return False
    
    def update_pixel_info(self, pos):
        """
        更新鼠标位置的像素信息
        """
        try:
            if self.original_image and self.scaled_image and self.is_valid_pixel_position(pos):
                # 计算图片显示区域
                rect = self.rect()
                image_rect = QRect(
                    rect.center().x() - self.scaled_image.width() // 2 + self.pan_offset.x(),
                    rect.center().y() - self.scaled_image.height() // 2 + self.pan_offset.y(),
                    self.scaled_image.width(),
                    self.scaled_image.height()
                )
                
                # 计算鼠标在图片中的位置
                mouse_in_image = pos - image_rect.topLeft()
                mouse_in_original = mouse_in_image / self.scale_factor
                
                # 获取像素颜色
                x = int(mouse_in_original.x())
                y = int(mouse_in_original.y())
                
                if 0 <= x < self.original_image.width() and 0 <= y < self.original_image.height():
                    color = self.original_image.pixelColor(x, y)
                    
                    # 更新像素信息
                    self.pixel_info = {
                        'x': x,
                        'y': y,
                        'r': color.red(),
                        'g': color.green(),
                        'b': color.blue(),
                        'hex': color.name()
                    }
                    
                    # 发送信号
                    self.pixel_info_changed.emit(self.pixel_info)
        except Exception as e:
            print(f"更新像素信息时出错: {e}")
    
    def reset_view(self):
        """
        重置视图（恢复自适应缩放状态）
        """
        try:
            self.pan_offset = QPoint()
            self.calculate_fit_scale()
            self.update_image()
            self.update()
        except Exception as e:
            print(f"重置视图时出错: {e}")
    
    def get_pixel_info(self):
        """
        获取当前像素信息
        """
        return self.pixel_info


class PhotoViewer(QWidget):
    """
    照片查看器组件
    提供图片查看、缩放、平移等功能
    """
    
    def __init__(self, parent=None):
        """
        初始化照片查看器
        
        Args:
            parent: 父窗口部件
        """
        super().__init__(parent)
        
        # 获取全局字体
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtGui import QFont
        app = QApplication.instance()
        self.global_font = getattr(app, 'global_font', QFont())
        #print(f"[DEBUG] PhotoViewer获取到的全局字体: {self.global_font.family()}")
        
        # 设置组件字体
        self.setFont(self.global_font)
        
        # 初始化所有属性
        self.image_widget = None
        self.scroll_area = None
        
        # 设置窗口属性
        self.setWindowTitle("照片查看器")
        self.setMinimumSize(800, 600)
        
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
        self.setStyleSheet("background-color: #f5f5f5;")
        
        # 1. 图片显示区域
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("background-color: #212121;")
        
        self.image_widget = ImageWidget()
        self.scroll_area.setWidget(self.image_widget)
        
        main_layout.addWidget(self.scroll_area, 1)
    
    def open_file(self):
        """
        打开图片文件
        """
        try:
            file_path, _ = QFileDialog.getOpenFileName(
                self, "打开图片文件", "", 
                "图片文件 (*.png *.jpg *.jpeg *.bmp *.gif *.tiff *.webp);;所有文件 (*)"
            )
            
            if file_path:
                if self.image_widget.set_image(file_path):
                    # 更新窗口标题
                    self.setWindowTitle(f"照片查看器 - {os.path.basename(file_path)}")
                else:
                    # 图片加载失败
                    QMessageBox.warning(self, "错误", "无法加载图片文件")
        except Exception as e:
            print(f"打开文件时出错: {e}")
            QMessageBox.warning(self, "错误", f"打开文件时出错: {str(e)}")
    
    def reset_view(self):
        """
        重置视图
        """
        try:
            self.image_widget.reset_view()
        except Exception as e:
            print(f"重置视图时出错: {e}")
    
    def load_image_from_path(self, image_path):
        """
        从外部路径加载图片
        
        Args:
            image_path (str): 图片文件路径
        
        Returns:
            bool: 是否成功加载图片
        """
        try:
            if self.image_widget.set_image(image_path):
                # 更新窗口标题
                self.setWindowTitle(f"照片查看器 - {os.path.basename(image_path)}")
                return True
            return False
        except Exception as e:
            print(f"从路径加载图片时出错: {e}")
            return False
    
    def set_file(self, file_path):
        """
        设置要显示的图片文件
        
        Args:
            file_path (str): 图片文件路径
        
        Returns:
            bool: 是否成功加载图片
        """
        return self.load_image_from_path(file_path)


# 命令行参数支持
if __name__ == "__main__":
    app = QApplication(sys.argv)
    viewer = PhotoViewer()
    
    # 如果提供了图片路径参数，直接加载
    if len(sys.argv) > 1:
        image_path = sys.argv[1]
        viewer.load_image_from_path(image_path)
    
    viewer.show()
    sys.exit(app.exec_())