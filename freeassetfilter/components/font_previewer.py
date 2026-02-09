#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

字体预览器组件
支持加载并预览字体文件
特点：
- 加载指定字体文件作为显示字体
- 纯文本预览模式
- 字体大小缩放控制
- 集成平滑滚动（D_ScrollBar）
- 线程安全设计
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QSizePolicy, QApplication, QFrame
)
from PyQt5.QtGui import (
    QFont, QFontDatabase, QPalette, QColor
)
from PyQt5.QtCore import (
    Qt, pyqtSignal, QThread, QMutex, QMutexLocker
)

from freeassetfilter.widgets.smooth_scroller import D_ScrollBar, SmoothScroller
from freeassetfilter.widgets.progress_widgets import D_ProgressBar


# 默认预览文本 - 展示字体的各种字符
DEFAULT_PREVIEW_TEXT = """FreeAssetFilter字体示例

汉字之美，在于形、意、韵。天地人和，万物有序。
漢字之美，在於形、意、韻。天地人和，萬物有序。

The quick brown fox jumps over the lazy dog.
abcdefghijklmnopqrstuvwxyz
ABCDEFGHIJKLMNOPQRSTUVWXYZ
0123456789
!@#$%^&*()_+-=[]{};':",./<>?

吾輩は猫である。名前はまだ無い。あいうえお かきくけこ さしすせそ
사람은 무엇으로 사는가?가나다라마바사 아자차카타파하
В чащах юга жил бы цитрус? Да, но фальшивый экземпляр!абвгдеёжзийклмнопрстуфхцчшщъыьэюя"""


class ZoomDisabledTextEdit(QTextEdit):
    """
    禁用缩放的文本编辑器
    
    继承自QTextEdit，但禁用了Ctrl+滚轮缩放功能
    支持Ctrl+滚轮控制字体大小
    """
    
    # 信号：字体大小变化通知，参数为变化量（正数表示增大，负数表示减小）
    font_size_change_requested = pyqtSignal(int)
    
    def __init__(self, parent=None):
        """
        初始化文本编辑器
        
        参数：
            parent: 父控件
        """
        super().__init__(parent)
    
    def wheelEvent(self, event):
        """
        处理滚轮事件
        
        当按下Ctrl键时，通过信号通知字体大小变化
        否则正常处理滚轮事件（滚动）
        
        参数：
            event: 滚轮事件
        """
        # 如果按下了Ctrl键，发送字体大小变化信号
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                # 向上滚动，增大字体
                self.font_size_change_requested.emit(1)
            elif delta < 0:
                # 向下滚动，减小字体
                self.font_size_change_requested.emit(-1)
            event.accept()
            return
        
        # 否则正常处理滚轮事件（滚动）
        super().wheelEvent(event)


class FontLoadThread(QThread):
    """字体加载后台线程"""

    finished = pyqtSignal(bool, str, int)
    error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.file_path = ""
        self._mutex = QMutex()
        self._abort = False

    def set_file(self, file_path):
        """设置要加载的字体文件"""
        with QMutexLocker(self._mutex):
            self.file_path = file_path

    def abort(self):
        """请求终止"""
        with QMutexLocker(self._mutex):
            self._abort = True

    def run(self):
        """执行字体加载"""
        with QMutexLocker(self._mutex):
            if self._abort:
                return
            file_path = self.file_path

        try:
            if not os.path.exists(file_path):
                self.error.emit(f"字体文件不存在: {file_path}")
                return

            # 加载字体文件
            font_id = QFontDatabase.addApplicationFont(file_path)

            if font_id == -1:
                self.error.emit("无法加载字体文件，可能格式不支持")
                return

            # 获取字体族名称
            font_families = QFontDatabase.applicationFontFamilies(font_id)

            if not font_families:
                self.error.emit("无法获取字体族名称")
                return

            font_family = font_families[0]
            self.finished.emit(True, font_family, font_id)

        except Exception as e:
            self.error.emit(f"加载字体失败: {str(e)}")


class FontPreviewWidget(QWidget):
    """
    字体预览主控件
    负责加载字体文件并显示预览文本
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        self.global_font = getattr(app, 'global_font', QFont())
        self.default_font_size = getattr(app, 'default_font_size', 24)
        
        self.current_file_path = ""
        self.current_font_family = ""
        self.font_id = -1
        
        self._thread = None
        self._mutex = QMutex()
        self._is_loading = False
        
        self._init_ui()
        self._apply_theme()
    
    def _init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._init_toolbar(layout)
        self._init_text_edit(layout)
    
    def _init_toolbar(self, parent_layout):
        """初始化工具栏 - 只包含字体大小滑块"""
        toolbar = QWidget()
        toolbar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(10, 5, 10, 5)
        toolbar_layout.setSpacing(10)
        
        app = QApplication.instance()
        text_color = "#333333"
        if hasattr(app, 'settings_manager'):
            text_color = app.settings_manager.get_setting("appearance.colors.secondary_color", "#333333")
        
        # 字体大小标签和滑块
        size_label = QLabel("大小")
        size_label.setStyleSheet(f"color: {text_color};")
        toolbar_layout.addWidget(size_label)
        
        self.font_size_slider = D_ProgressBar(
            orientation=D_ProgressBar.Horizontal,
            is_interactive=True
        )
        self.font_size_slider.setRange(4, 40)
        self.font_size_slider.setValue(self.default_font_size)
        self.font_size_slider.setFixedWidth(int(150 * self.dpi_scale))
        self.font_size_slider.valueChanged.connect(self._on_font_size_changed)
        toolbar_layout.addWidget(self.font_size_slider)
        
        # 显示当前字体大小数值
        self.font_size_label = QLabel(f"{self.default_font_size}px")
        self.font_size_label.setStyleSheet(f"color: {text_color};")
        toolbar_layout.addWidget(self.font_size_label)
        
        toolbar_layout.addStretch()
        
        parent_layout.addWidget(toolbar)
    
    def _init_text_edit(self, parent_layout):
        """初始化文本编辑区"""
        container = QWidget()
        container_layout = QHBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        app = QApplication.instance()
        base_color = "#FFFFFF"
        if hasattr(app, 'settings_manager'):
            base_color = app.settings_manager.get_setting("appearance.colors.base_color", "#FFFFFF")

        container.setStyleSheet(f"background-color: {base_color};")
        
        # 创建文本编辑器
        self.text_edit = ZoomDisabledTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setLineWrapMode(QTextEdit.WidgetWidth)
        self.text_edit.setUndoRedoEnabled(False)
        # 禁用右键菜单
        self.text_edit.setContextMenuPolicy(Qt.NoContextMenu)
        # 禁用文本选择功能
        self.text_edit.setTextInteractionFlags(Qt.NoTextInteraction)
        # 连接字体大小变化信号
        self.text_edit.font_size_change_requested.connect(self._on_font_size_change_requested)
        
        # 设置默认字体
        default_font = QFont()
        default_font.setPointSize(int(self.default_font_size * self.dpi_scale))
        default_font.setWeight(QFont.Normal)
        self.text_edit.setFont(default_font)

        app = QApplication.instance()
        base_color = "#FFFFFF"
        second_color = "#333333"
        if hasattr(app, 'settings_manager'):
            base_color = app.settings_manager.get_setting("appearance.colors.base_color", "#FFFFFF")
            second_color = app.settings_manager.get_setting("appearance.colors.secondary_color", "#333333")

        self.text_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {base_color};
                color: {second_color};
                border: none;
                padding: {int(6 * self.dpi_scale)}px;
            }}
        """)
        
        # 设置滚动条
        scroll_bar = D_ScrollBar(self.text_edit, Qt.Vertical)
        self.text_edit.setVerticalScrollBar(scroll_bar)
        scroll_bar.apply_theme_from_settings()
        
        horizontal_scroll_bar = D_ScrollBar(self.text_edit, Qt.Horizontal)
        self.text_edit.setHorizontalScrollBar(horizontal_scroll_bar)
        horizontal_scroll_bar.apply_theme_from_settings()
        
        container_layout.addWidget(self.text_edit)

        parent_layout.addWidget(container)

        SmoothScroller.apply_to_scroll_area(self.text_edit)

    def _apply_theme(self):
        """应用主题"""
        app = QApplication.instance()
        if not hasattr(app, 'settings_manager'):
            return

        bg_color = app.settings_manager.get_setting("appearance.colors.window_background", "#F5F5F5")
        base_color = app.settings_manager.get_setting("appearance.colors.base_color", "#FFFFFF")
        secondary_color = app.settings_manager.get_setting("appearance.colors.secondary_color", "#333333")

        self.setStyleSheet(f"""
            background-color: {bg_color};
        """)

        self.text_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {base_color};
                color: {secondary_color};
                border: none;
                padding: {int(6 * self.dpi_scale)}px;
            }}
        """)

    def _on_font_size_changed(self, value):
        """处理字体大小滑块变化"""
        self.font_size_label.setText(f"{value}px")
        self._update_font_size(value)
    
    def _on_font_size_change_requested(self, delta):
        """处理Ctrl+滚轮字体大小变化请求"""
        current_value = self.font_size_slider.value()
        new_value = current_value + delta
        new_value = max(self.font_size_slider.minimum(), min(self.font_size_slider.maximum(), new_value))
        self.font_size_slider.setValue(new_value)
    
    def _update_font_size(self, size):
        """更新字体大小"""
        if self.current_font_family:
            font = QFont(self.current_font_family)
        else:
            font = QFont()
        font.setPointSize(int(size * self.dpi_scale))
        font.setWeight(QFont.Normal)
        self.text_edit.setFont(font)
    

    
    def set_file(self, file_path):
        """
        设置要预览的字体文件

        参数：
            file_path (str): 字体文件路径
        """
        if not os.path.exists(file_path):
            self.text_edit.setPlainText(f"字体文件不存在: {file_path}")
            return

        # 如果之前加载过字体，先移除
        if self.font_id != -1:
            QFontDatabase.removeApplicationFont(self.font_id)
            self.font_id = -1

        # 重置字体相关状态
        self.current_font_family = ""

        # 重置文本编辑器为默认字体
        default_font = QFont()
        default_font.setPointSize(int(self.default_font_size * self.dpi_scale))
        default_font.setWeight(QFont.Normal)
        self.text_edit.setFont(default_font)

        self.current_file_path = file_path
        self.text_edit.clear()
        self.text_edit.setPlainText("正在加载字体...")

        # 取消之前的线程
        if self._thread and self._thread.isRunning():
            try:
                self._thread.finished.disconnect(self._on_font_loaded)
                self._thread.error.disconnect(self._on_load_error)
            except (TypeError, RuntimeError):
                pass
            self._thread.abort()
            self._thread.wait()
            self._thread = None

        self._load_font_async(file_path)

    def _load_font_async(self, file_path):
        """异步加载字体"""
        # 如果之前有线程在运行，先断开信号连接再终止
        if self._thread and self._thread.isRunning():
            try:
                self._thread.finished.disconnect(self._on_font_loaded)
                self._thread.error.disconnect(self._on_load_error)
            except (TypeError, RuntimeError):
                pass
            self._thread.abort()
            self._thread.wait()
            self._thread = None

        # 创建新线程并连接信号
        self._thread = FontLoadThread(self)
        self._thread.set_file(file_path)
        self._thread.finished.connect(self._on_font_loaded)
        self._thread.error.connect(self._on_load_error)
        self._thread.start()

    def _on_font_loaded(self, success, font_family, font_id):
        """字体加载完成回调"""
        if not success:
            self.text_edit.setPlainText(f"加载字体失败")
            return

        # 保存新加载的字体ID和字体族名称
        self.font_id = font_id
        self.current_font_family = font_family

        # 更新字体显示
        self._update_font_display()

    def _on_load_error(self, error_msg):
        """加载错误回调"""
        self.text_edit.setPlainText(f"加载字体失败: {error_msg}")
    
    def _update_font_display(self):
        """更新字体显示"""
        if not self.current_font_family:
            return
        
        # 创建字体对象
        font = QFont(self.current_font_family)
        font_size = self.font_size_slider.value()
        font.setPointSize(int(font_size * self.dpi_scale))
        font.setWeight(QFont.Normal)
        
        # 应用到文本编辑器
        self.text_edit.setFont(font)
        
        # 设置预览文本
        preview_text = DEFAULT_PREVIEW_TEXT

        # 添加字体信息
        font_info = f"""字体名称: {self.current_font_family}
"""

        self.text_edit.setPlainText(font_info + preview_text)

    def set_preview_text(self, text):
        """
        设置自定义预览文本

        参数：
            text (str): 预览文本内容
        """
        if self.current_font_family:
            font_info = f"""字体名称: {self.current_font_family}
"""
            self.text_edit.setPlainText(font_info + text)
        else:
            self.text_edit.setPlainText(text)

    def set_font(self, file_path):
        """
        设置要预览的字体文件（set_file的别名，用于兼容性）
        
        参数：
            file_path (str): 字体文件路径
        """
        self.set_file(file_path)

    def cleanup(self):
        """清理资源"""
        # 断开线程信号连接
        if self._thread:
            try:
                self._thread.finished.disconnect(self._on_font_loaded)
                self._thread.error.disconnect(self._on_load_error)
            except (TypeError, RuntimeError):
                pass
            
            # 终止线程
            if self._thread.isRunning():
                self._thread.abort()
                self._thread.wait()
            self._thread = None
        
        # 移除加载的字体
        if self.font_id != -1:
            QFontDatabase.removeApplicationFont(self.font_id)
            self.font_id = -1
        
        # 重置字体族名称
        self.current_font_family = ""


class FontPreviewer(QWidget):
    """
    完整字体预览器组件
    包含窗口控件和FontPreviewWidget
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        self.global_font = getattr(app, 'global_font', QFont())
        self.setFont(self.global_font)
        
        self._init_ui()
        self._apply_theme()
    
    def _init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        self.preview_widget = FontPreviewWidget(self)
        layout.addWidget(self.preview_widget)
    
    def _apply_theme(self):
        """应用主题"""
        app = QApplication.instance()
        if not hasattr(app, 'settings_manager'):
            return
        
        bg_color = app.settings_manager.get_setting("appearance.colors.window_background", "#F5F5F5")
        self.setStyleSheet(f"background-color: {bg_color};")
    
    def set_file(self, file_path):
        """
        设置要预览的字体文件
        
        参数：
            file_path (str): 字体文件路径
        """
        self.preview_widget.set_file(file_path)
    
    def set_preview_text(self, text):
        """
        设置自定义预览文本
        
        参数：
            text (str): 预览文本内容
        """
        self.preview_widget.set_preview_text(text)
    
    def cleanup(self):
        """清理资源"""
        self.preview_widget.cleanup()


if __name__ == "__main__":
    # 简单的测试代码
    app = QApplication(sys.argv)
    
    # 创建主窗口
    window = QWidget()
    window.setWindowTitle("字体预览器测试")
    window.resize(800, 600)
    
    layout = QVBoxLayout(window)
    
    # 创建字体预览器
    previewer = FontPreviewer()
    layout.addWidget(previewer)
    
    # 如果提供了字体文件路径，则加载
    if len(sys.argv) > 1:
        previewer.set_file(sys.argv[1])
    else:
        previewer.preview_widget.text_edit.setPlainText("请提供字体文件路径作为参数")
    
    window.show()
    sys.exit(app.exec_())
