#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

2. 商业使用：需联系 qpdrfc123@gmail.com 获取书面授权
项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE
独立的文本预览器组件
提供文本文件预览、Markdown渲染和代码语法高亮功能
"""

import sys
import os
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QFileDialog, QLabel, QScrollArea, QGroupBox, QGridLayout,
    QTextEdit, QComboBox, QMenu, QAction, QSpinBox
)
from PyQt5.QtGui import (
    QFont, QIcon, QFontDatabase
)
from PyQt5.QtCore import (
    Qt, QUrl, QThread, pyqtSignal
)
from PyQt5.QtWebEngineWidgets import QWebEngineView
import markdown
from pygments import highlight
from pygments.lexers import get_lexer_for_filename, TextLexer
from pygments.formatters import HtmlFormatter


class FileReadThread(QThread):
    """
    文件读取线程，用于异步读取文件内容并报告进度
    特别优化了网络文件（如NAS上的文件）的读取方式
    """
    # 信号定义
    progress_updated = pyqtSignal(int, str)  # 进度更新信号，参数：进度值(0-100)，状态描述
    file_read_completed = pyqtSignal(str, str)  # 文件读取完成信号，参数：文件内容，编码
    file_read_failed = pyqtSignal(str)  # 文件读取失败信号，参数：错误信息
    
    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path
        self.encoding = 'utf-8'
        self.is_cancelled = False
    
    def run(self):
        """
        执行文件读取操作
        优化了网络文件的读取方式，确保进度实时更新
        """
        try:
            # 第一步：获取文件大小
            self.progress_updated.emit(0, "正在获取文件信息...")
            
            # 异步获取文件大小
            file_size = self._get_file_size_with_timeout()
            if file_size == -1:
                raise Exception("无法获取文件大小")
            
            # 第二步：打开文件并分块读取
            self.progress_updated.emit(5, "正在打开文件...")
            
            chunk_size = 65536  # 64KB
            
            read_bytes = 0
            content = []
            encoding = self.encoding
            
            # 尝试使用UTF-8编码
            try:
                with open(self.file_path, 'rb') as f:
                    while not self.is_cancelled:
                        binary_chunk = f.read(chunk_size)
                        if not binary_chunk:
                            break
                        
                        read_bytes += len(binary_chunk)
                        text_chunk = binary_chunk.decode(encoding)
                        content.append(text_chunk)
                        
                        progress = 5 + int(min(95, (read_bytes / file_size) * 95))
                        self.progress_updated.emit(progress, f"正在读取文件... {progress}%")
            except UnicodeDecodeError:
                # 尝试使用GBK编码
                encoding = 'gbk'
                read_bytes = 0
                content = []
                self.progress_updated.emit(0, "正在使用GBK编码打开文件...")
                
                with open(self.file_path, 'rb') as f:
                    while not self.is_cancelled:
                        binary_chunk = f.read(chunk_size)
                        if not binary_chunk:
                            break
                        
                        read_bytes += len(binary_chunk)
                        text_chunk = binary_chunk.decode(encoding)
                        content.append(text_chunk)
                        
                        progress = 5 + int(min(95, (read_bytes / file_size) * 95))
                        self.progress_updated.emit(progress, f"正在读取文件... {progress}%")
            except Exception as e:
                self.file_read_failed.emit(f"读取文件时出错: {str(e)}")
                return
            
            if not self.is_cancelled:
                self.progress_updated.emit(100, "文件读取完成")
                self.file_read_completed.emit(''.join(content), encoding)
        except Exception as e:
            self.file_read_failed.emit(str(e))
    
    def _get_file_size_with_timeout(self, timeout=5):
        """
        带超时的文件大小获取
        """
        import threading
        
        file_size = [0]
        error = [None]
        
        def get_size():
            try:
                file_size[0] = os.path.getsize(self.file_path)
            except Exception as e:
                error[0] = e
        
        thread = threading.Thread(target=get_size)
        thread.daemon = True
        thread.start()
        thread.join(timeout)
        
        if thread.is_alive():
            try:
                with open(self.file_path, 'rb') as f:
                    f.seek(0, os.SEEK_END)
                    file_size[0] = f.tell()
                    f.seek(0)
            except Exception as e:
                error[0] = e
        
        if error[0]:
            print(f"获取文件大小失败: {error[0]}")
            return -1
        
        return file_size[0]
    
    def cancel(self):
        """
        取消文件读取操作
        """
        self.is_cancelled = True


class TextPreviewWidget(QWidget):
    """
    文本预览部件，支持Markdown渲染和代码高亮
    """
    # 信号定义
    file_read_progress = pyqtSignal(int, str)  # 文件读取进度信号
    file_read_finished = pyqtSignal()  # 文件读取完成信号
    file_read_cancelled = pyqtSignal()  # 文件读取取消信号
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 获取全局字体和DPI缩放因子
        app = QApplication.instance()
        self.global_font = getattr(app, 'global_font', QFont())
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        # 设置组件字体
        self.setFont(self.global_font)
        
        # 文件数据
        self.current_file_path = ""
        self.file_content = ""
        
        # 预览模式
        self.preview_mode = "auto"  # auto, text, markdown, code
        
        # 字体设置
        self.current_font = "Arial"  # 默认字体
        self.font_scale = 1.0  # 默认100%
        self.font_size = 16  # 默认字体大小(px)
        
        # 文件读取线程
        self.read_thread = None
        
        # 初始化UI
        self.init_ui()
    
    def init_ui(self):
        """
        初始化预览部件UI
        """
        layout = QVBoxLayout(self)
        
        # 应用DPI缩放因子到布局参数
        scaled_margin = int(10 * self.dpi_scale)
        scaled_spacing = int(8 * self.dpi_scale)
        layout.setContentsMargins(scaled_margin, scaled_margin, scaled_margin, scaled_margin)
        layout.setSpacing(scaled_spacing)
        
        # 设置背景色
        app = QApplication.instance()
        background_color = "#2D2D2D"  # 默认窗口背景色
        if hasattr(app, 'settings_manager'):
            background_color = app.settings_manager.get_setting("appearance.colors.window_background", "#2D2D2D")
        self.setStyleSheet(f"background-color: {background_color};")
        
        # 预览模式选择
        mode_layout = QGridLayout()
        mode_layout.setSpacing(int(5 * self.dpi_scale))
        mode_layout.setColumnStretch(4, 1)  # 最后一列添加拉伸
        
        # 使用全局默认字体大小
        app = QApplication.instance()
        default_font_size = getattr(app, 'default_font_size', 9)
        scaled_font_size = int(default_font_size * self.dpi_scale)
        scaled_padding_v = int(4 * self.dpi_scale)
        scaled_padding_h = int(6 * self.dpi_scale)
        scaled_border_radius = int(4 * self.dpi_scale)
        scaled_combo_font_size = int(default_font_size * self.dpi_scale)
        scaled_max_width = int(100 * self.dpi_scale)  # 下拉框最大宽度
        
        # 第一行：预览模式
        mode_label = QLabel("预览模式:")
        mode_label.setFont(self.global_font)
        mode_label.setStyleSheet(f"font-size: {scaled_font_size}px; color: #333; font-weight: 500;")
        mode_layout.addWidget(mode_label, 0, 0)
        
        self.mode_selector = QComboBox()
        self.mode_selector.addItems(["自动检测", "纯文本", "Markdown", "代码高亮"])
        self.mode_selector.currentTextChanged.connect(self.change_preview_mode)
        self.mode_selector.setFont(self.global_font)
        self.mode_selector.setMaximumWidth(scaled_max_width)
        self.mode_selector.setStyleSheet(f'''.QComboBox {{
            background-color: white;
            border: 1px solid #e0e0e0;
            border-radius: {scaled_border_radius}px;
            padding: {scaled_padding_v}px {scaled_padding_h}px;
            font-size: {scaled_combo_font_size}px;
            color: #333;
        }}
        .QComboBox:hover {{
            border-color: #1976d2;
        }}
        .QComboBox:focus {{
            border-color: #1976d2;
            outline: none;
        }}''')
        mode_layout.addWidget(self.mode_selector, 0, 1)
        
        # 第一行：字体选择
        font_label = QLabel("字体:")
        font_label.setFont(self.global_font)
        font_label.setStyleSheet(f"font-size: {scaled_font_size}px; color: #333; font-weight: 500;")
        mode_layout.addWidget(font_label, 0, 2)
        
        self.font_selector = QComboBox()
        # 获取系统中可用的字体列表
        font_list = QFontDatabase().families()
        self.font_selector.addItems(font_list)
        # 设置默认字体
        if "Arial" in font_list:
            self.change_font("Arial")
            self.font_selector.setCurrentText("Arial")
        elif "SimHei" in font_list:
            self.change_font("SimHei")
            self.font_selector.setCurrentText("SimHei")
        # 确保字体选择器和current_font一致
        self.font_selector.setCurrentText(self.current_font)
        self.font_selector.setFont(self.global_font)
        self.font_selector.setMaximumWidth(scaled_max_width)
        self.font_selector.setStyleSheet(f'''.QComboBox {{
            background-color: white;
            border: 1px solid #e0e0e0;
            border-radius: {scaled_border_radius}px;
            padding: {scaled_padding_v}px {scaled_padding_h}px;
            font-size: {scaled_combo_font_size}px;
            color: #333;
        }}
        .QComboBox:hover {{
            border-color: #1976d2;
        }}
        .QComboBox:focus {{
            border-color: #1976d2;
            outline: none;
        }}''')
        mode_layout.addWidget(self.font_selector, 0, 3)
        
        # 第二行：字体大小
        font_size_label = QLabel("字体大小:")
        font_size_label.setFont(self.global_font)
        font_size_label.setStyleSheet(f"font-size: {scaled_font_size}px; color: #333; font-weight: 500;")
        mode_layout.addWidget(font_size_label, 1, 0)
        
        self.font_size_selector = QComboBox()
        font_size_options = ["小", "标准", "大", "特大", "自定义"]
        self.font_size_selector.addItems(font_size_options)
        self.font_size_selector.setCurrentIndex(1)  # 默认选择"标准"
        self.font_size_selector.setFont(self.global_font)
        self.font_size_selector.setMaximumWidth(scaled_max_width)
        self.font_size_selector.setStyleSheet(f'''.QComboBox {{
            background-color: white;
            border: 1px solid #e0e0e0;
            border-radius: {scaled_border_radius}px;
            padding: {scaled_padding_v}px {scaled_padding_h}px;
            font-size: {scaled_combo_font_size}px;
            color: #333;
        }}
        .QComboBox:hover {{
            border-color: #1976d2;
        }}
        .QComboBox:focus {{
            border-color: #1976d2;
            outline: none;
        }}''')
        mode_layout.addWidget(self.font_size_selector, 1, 1)
        
        # 第二行：自定义字体大小输入框
        self.custom_font_size_spinbox = QSpinBox()
        self.custom_font_size_spinbox.setRange(8, 72)  # 字体大小范围8-72px
        self.custom_font_size_spinbox.setValue(self.font_size)
        self.custom_font_size_spinbox.setFont(self.global_font)
        self.custom_font_size_spinbox.setMaximumWidth(int(100 * self.dpi_scale))  # 更小的最大宽度
        self.custom_font_size_spinbox.setStyleSheet(f'''.QSpinBox {{
            background-color: white;
            border: 1px solid #e0e0e0;
            border-radius: {scaled_border_radius}px;
            padding: {scaled_padding_v}px {scaled_padding_h}px;
            font-size: {scaled_combo_font_size}px;
            color: #333;
        }}
        .QSpinBox:hover {{
            border-color: #1976d2;
        }}
        .QSpinBox:focus {{
            border-color: #1976d2;
            outline: none;
        }}''')
        # 默认隐藏自定义字体大小输入框
        self.custom_font_size_spinbox.hide()
        mode_layout.addWidget(self.custom_font_size_spinbox, 1, 2, 1, 2)  # 跨两列
        
        layout.addLayout(mode_layout)
        
        # 预览区域
        self.web_view = QWebEngineView()
        scaled_min_height = int(250 * self.dpi_scale)
        self.web_view.setMinimumHeight(scaled_min_height)
        self.web_view.setStyleSheet(f"background-color: white; border: 1px solid #e0e0e0; border-radius: {scaled_border_radius}px;")
        # 为WebView添加自定义上下文菜单
        self.web_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.web_view.customContextMenuRequested.connect(self.show_context_menu)
        layout.addWidget(self.web_view)
        
        # 连接信号槽
        self.font_size_selector.currentTextChanged.connect(self.change_font_size)
        self.font_selector.currentTextChanged.connect(self.change_font)
        self.custom_font_size_spinbox.valueChanged.connect(self.change_custom_font_size)
    
    def set_file(self, file_path):
        """
        设置要预览的文本文件
        """
        if os.path.exists(file_path):
            self.current_file_path = file_path
            
            # 如果当前有正在运行的读取线程，先取消
            if self.read_thread and self.read_thread.isRunning():
                self.read_thread.cancel()
                self.read_thread.wait()
            
            # 创建新的文件读取线程
            self.read_thread = FileReadThread(file_path)
            
            # 连接信号
            self.read_thread.progress_updated.connect(self.on_file_read_progress)
            self.read_thread.file_read_completed.connect(self.on_file_read_completed)
            self.read_thread.file_read_failed.connect(self.on_file_read_failed)
            
            # 启动线程
            self.read_thread.start()
            
            return True
        return False
    
    def on_file_read_progress(self, progress, status):
        """
        文件读取进度更新回调
        """
        # 发射进度信号，供外部进度条使用
        self.file_read_progress.emit(progress, status)
    
    def on_file_read_completed(self, content, encoding):
        """
        文件读取完成回调
        """
        self.file_content = content
        # 更新预览
        self.update_preview()
        # 发射读取完成信号
        self.file_read_finished.emit()
    
    def on_file_read_failed(self, error):
        """
        文件读取失败回调
        """
        print(f"文件读取失败: {error}")
        # 显示错误信息
        self.file_content = f"文件读取失败: {error}"
        self.update_preview()
        # 发射读取完成信号
        self.file_read_finished.emit()
    
    def cancel_file_read(self):
        """
        取消文件读取操作
        """
        if self.read_thread and self.read_thread.isRunning():
            self.read_thread.cancel()
            self.file_read_cancelled.emit()
    
    def change_preview_mode(self, mode_text):
        """
        切换预览模式
        """
        mode_map = {
            "自动检测": "auto",
            "纯文本": "text",
            "Markdown": "markdown",
            "代码高亮": "code"
        }
        self.preview_mode = mode_map[mode_text]
        self.update_preview()
    
    def change_font_size(self, size_text):
        """
        切换字体大小
        """
        if size_text == "自定义":
            # 显示自定义字体大小输入框
            self.custom_font_size_spinbox.show()
            # 使用当前自定义字体大小
            self.font_size = self.custom_font_size_spinbox.value()
        else:
            # 隐藏自定义字体大小输入框
            self.custom_font_size_spinbox.hide()
            # 使用预设的字体大小
            size_map = {
                "小": 12,     # 12px
                "标准": 16,   # 16px
                "大": 20,     # 20px
                "特大": 24    # 24px
            }
            self.font_size = size_map[size_text]
        
        self.update_preview()
        
    def change_font(self, font_name):
        """
        切换字体
        """
        print(f"切换字体: {self.current_font} -> {font_name}")
        self.current_font = font_name
        if self.file_content:
            print(f"更新预览，当前字体: {self.current_font}")
            self.update_preview()
        
    def change_custom_font_size(self, size):
        """
        改变自定义字体大小
        """
        self.font_size = size
        self.update_preview()
    
    def update_preview(self):
        """
        更新预览内容
        """
        if not self.file_content:
            return
        
        # 自动检测模式
        if self.preview_mode == "auto":
            # 根据文件扩展名判断
            ext = os.path.splitext(self.current_file_path)[1].lower()
            if ext in ['.txt']:
                # txt文件使用纯文本模式
                html_content = self.render_plain_text(self.file_content)
            elif ext in ['.md', '.markdown', '.mdown', '.mkd']:
                # Markdown文件使用Markdown模式
                html_content = self.render_markdown(self.file_content)
            else:
                # 其他代码源文件使用代码高亮模式
                html_content = self.render_code(self.file_content, self.current_file_path)
        
        # 纯文本模式
        elif self.preview_mode == "text":
            html_content = self.render_plain_text(self.file_content)
        
        # Markdown模式
        elif self.preview_mode == "markdown":
            html_content = self.render_markdown(self.file_content)
        
        # 代码高亮模式
        elif self.preview_mode == "code":
            html_content = self.render_code(self.file_content, self.current_file_path)
        
        # 设置HTML内容
        self.web_view.setHtml(html_content)
    
    def show_context_menu(self, position):
        """
        显示自定义上下文菜单，仅在有选中文本时显示复制选项
        """
        # 使用JavaScript检查是否有选中的文本
        def check_selection(selection_text):
            if selection_text.strip():
                # 创建上下文菜单
                menu = QMenu(self.web_view)
                
                # 创建复制动作
                copy_action = QAction("复制", self.web_view)
                copy_action.triggered.connect(self.copy_selected_text)
                menu.addAction(copy_action)
                
                # 在鼠标位置显示菜单
                menu.exec_(self.web_view.mapToGlobal(position))
        
        # 执行JavaScript获取选中的文本
        self.web_view.page().runJavaScript("window.getSelection().toString();", check_selection)
    
    def copy_selected_text(self):
        """
        复制选中的文本到剪贴板
        """
        def copy_to_clipboard(selection_text):
            if selection_text.strip():
                clipboard = QApplication.clipboard()
                clipboard.setText(selection_text)
        
        # 执行JavaScript获取选中的文本并复制到剪贴板
        self.web_view.page().runJavaScript("window.getSelection().toString();", copy_to_clipboard)
    
    def render_plain_text(self, content):
        """
        渲染纯文本
        """
        # 转义HTML特殊字符
        content = content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        content = content.replace('"', '&quot;').replace("'", '&#39;')
        # 替换换行符
        content = content.replace('\n', '<br>')
        
        # 应用DPI缩放因子和字体大小
        final_font_size = int(self.font_size * self.dpi_scale)
        
        # 使用普通字符串拼接，避免f-string中的大括号冲突
        html = "<!DOCTYPE html>\n"
        html += "<html>\n"
        html += "<head>\n"
        html += "    <meta charset=\"utf-8\">\n"
        html += "    <style>\n"
        html += "        body, pre, code {\n"
        html += "            font-family: '" + self.current_font + "', sans-serif !important;\n"
        html += "            font-size: " + str(final_font_size) + "px;\n"
        html += "            line-height: 1.6;\n"
        html += "            color: #333;\n"
        html += "            margin: 20px;\n"
        html += "            background-color: #fff;\n"
        html += "            word-wrap: break-word;\n"
        html += "            word-break: break-word;\n"
        html += "        }\n"
        html += "        pre {\n"
        html += "            white-space: pre-wrap;\n"
        html += "            word-wrap: break-word;\n"
        html += "            margin: 0;\n"
        html += "        }\n"
        html += "    </style>\n"
        html += "</head>\n"
        html += "<body>\n"
        html += "    <pre>" + content + "</pre>\n"
        html += "</body>\n"
        html += "</html>\n"
        
        return html
    
    def render_markdown(self, content):
        """
        渲染Markdown
        """
        # 使用markdown库将Markdown转换为HTML
        rendered_markdown = markdown.markdown(content, extensions=[
            'markdown.extensions.extra',
            'markdown.extensions.codehilite',
            'markdown.extensions.toc'
        ])
        
        # 应用DPI缩放因子和字体大小
        final_font_size = int(self.font_size * self.dpi_scale)
        
        # 添加CSS样式
        html = "<!DOCTYPE html>\n"
        html += "<html>\n"
        html += "<head>\n"
        html += "    <meta charset=\"utf-8\">\n"
        html += "    <style>\n"
        html += "        body {\n"
        html += "            font-family: '" + self.current_font + "', sans-serif;\n"
        html += "            font-size: " + str(final_font_size) + "px;\n"
        html += "            line-height: 1.8;\n"
        html += "            color: #333;\n"
        html += "            margin: 20px;\n"
        html += "            background-color: #fff;\n"
        html += "            word-wrap: break-word;\n"
        html += "            word-break: break-word;\n"
        html += "            overflow-x: hidden;\n"
        html += "        }\n"
        html += "        h1, h2, h3, h4, h5, h6 {\n"
        html += "            color: #2c3e50;\n"
        html += "            margin-top: 1.5em;\n"
        html += "            margin-bottom: 0.5em;\n"
        html += "            word-wrap: break-word;\n"
        html += "        }\n"
        html += "        code {\n"
        html += "            background-color: #f0f0f0;\n"
        html += "            padding: 2px 4px;\n"
        html += "            border-radius: 3px;\n"
        html += "            font-family: '" + self.current_font + "', Consolas, Monaco, 'Andale Mono', monospace !important;\n"
        html += "            word-wrap: break-word;\n"
        html += "        }\n"
        html += "        pre {\n"
        html += "            background-color: #f8f8f8;\n"
        html += "            border: 1px solid #e8e8e8;\n"
        html += "            border-radius: 5px;\n"
        html += "            padding: 15px;\n"
        html += "            white-space: pre-wrap;\n"
        html += "            word-wrap: break-word;\n"
        html += "            overflow-x: auto;\n"
        html += "        }\n"
        html += "        pre code {\n"
        html += "            background-color: transparent;\n"
        html += "            padding: 0;\n"
        html += "        }\n"
        html += "        blockquote {\n"
        html += "            border-left: 4px solid #ddd;\n"
        html += "            margin-left: 0;\n"
        html += "            padding-left: 20px;\n"
        html += "            color: #666;\n"
        html += "            word-wrap: break-word;\n"
        html += "        }\n"
        html += "        table {\n"
        html += "            border-collapse: collapse;\n"
        html += "            width: 100%;\n"
        html += "            margin: 20px 0;\n"
        html += "            word-wrap: break-word;\n"
        html += "        }\n"
        html += "        th, td {\n"
        html += "            border: 1px solid #ddd;\n"
        html += "            padding: 8px 12px;\n"
        html += "            text-align: left;\n"
        html += "            word-wrap: break-word;\n"
        html += "        }\n"
        html += "        th {\n"
        html += "            background-color: #f0f0f0;\n"
        html += "        }\n"
        html += "        img {\n"
        html += "            max-width: 100%;\n"
        html += "            height: auto;\n"
        html += "        }\n"
        html += "    </style>\n"
        html += "</head>\n"
        html += "<body>\n"
        html += rendered_markdown + "\n"
        html += "</body>\n"
        html += "</html>\n"
        
        return html
    
    def render_code(self, content, filename):
        """
        渲染代码高亮
        """
        try:
            # 尝试根据文件名获取合适的词法分析器
            lexer = get_lexer_for_filename(filename)
        except:
            # 如果无法获取，使用文本词法分析器
            lexer = TextLexer()
        
        # 创建HTML格式化器
        formatter = HtmlFormatter(
            style='default',
            linenos=True,
            full=False,
            cssclass='highlight'
        )
        
        # 生成高亮HTML
        highlighted_code = highlight(content, lexer, formatter)
        
        # 获取CSS样式
        css = formatter.get_style_defs('.highlight')
        
        # 应用DPI缩放因子和字体大小
        final_font_size = int(self.font_size * self.dpi_scale)
        
        # 创建完整HTML文档
        html = "<!DOCTYPE html>\n"
        html += "<html>\n"
        html += "<head>\n"
        html += "    <meta charset=\"utf-8\">\n"
        html += "    <style>\n"
        html += css + "\n"
        html += "        body {\n"
        html += "            font-family: '" + self.current_font + "', sans-serif;\n"
        html += "            font-size: " + str(final_font_size) + "px;\n"
        html += "            line-height: 1.6;\n"
        html += "            color: #333;\n"
        html += "            margin: 20px;\n"
        html += "            background-color: #fff;\n"
        html += "            word-wrap: break-word;\n"
        html += "            word-break: break-word;\n"
        html += "            overflow-x: hidden;\n"
        html += "        }\n"
        html += "        .highlight {\n"
        html += "            background-color: #f8f8f8;\n"
        html += "            border: 1px solid #e8e8e8;\n"
        html += "            border-radius: 5px;\n"
        html += "            padding: 15px;\n"
        html += "            overflow-x: auto;\n"
        html += "        }\n"
        html += "        .highlight pre {\n"
        html += "            margin: 0;\n"
        html += "            white-space: pre-wrap;\n"
        html += "            word-wrap: break-word;\n"
        html += "        }\n"
        html += "        .highlight table {\n"
        html += "            width: 100%;\n"
        html += "            word-wrap: break-word;\n"
        html += "        }\n"
        html += "        .highlight td {\n"
        html += "            vertical-align: top;\n"
        html += "            word-wrap: break-word;\n"
        html += "        }\n"
        html += "        .highlight code {\n"
        html += "            font-family: '" + self.current_font + "', Consolas, Monaco, 'Andale Mono', monospace !important;\n"
        html += "            font-size: 90%;\n"
        html += "            word-wrap: break-word;\n"
        html += "        }\n"
        html += "    </style>\n"
        html += "</head>\n"
        html += "<body>\n"
        html += highlighted_code + "\n"
        html += "</body>\n"
        html += "</html>\n"
        
        return html


class TextPreviewer(QMainWindow):
    """
    文本预览器主窗口
    """
    
    def __init__(self):
        super().__init__()
        
        # 获取全局字体和DPI缩放因子
        app = QApplication.instance()
        self.global_font = getattr(app, 'global_font', QFont())
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        # 设置窗口属性
        self.setWindowTitle("文本预览器")
        
        # 使用DPI缩放因子调整窗口大小
        scaled_min_width = int(300 * self.dpi_scale)
        scaled_min_height = int(200 * self.dpi_scale)
        self.setGeometry(100, 100, scaled_min_width, scaled_min_height)
        self.setMinimumSize(scaled_min_width, scaled_min_height)
        
        # 设置窗口字体
        self.setFont(self.global_font)
        
        # 创建UI
        self.init_ui()
    
    def init_ui(self):
        """
        初始化用户界面
        """
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 创建主布局
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 设置整体背景色
        app = QApplication.instance()
        background_color = "#2D2D2D"  # 默认窗口背景色
        if hasattr(app, 'settings_manager'):
            background_color = app.settings_manager.get_setting("appearance.colors.window_background", "#2D2D2D")
        self.setStyleSheet(f"background-color: {background_color};")
        
        # 文本预览区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("background-color: transparent;")
        
        self.text_widget = TextPreviewWidget()
        scroll_area.setWidget(self.text_widget)
        
        main_layout.addWidget(scroll_area, 1)
    
    def open_file(self):
        """
        打开文本文件
        """
        file_path, _ = QFileDialog.getOpenFileName(
            self, "打开文本文件", "", 
            "文本文件 (*.txt *.md *.markdown *.mdown *.mkd *.py *.js *.html *.css *.json *.yaml *.yml *.xml *.java *.c *.cpp *.h *.hpp *.go *.rs);;所有文件(*)")
        
        if file_path:
            self.load_file_from_path(file_path)
    
    def load_file_from_path(self, file_path):
        """
        从外部路径加载文本文件
        """
        if self.text_widget.set_file(file_path):
            # 更新窗口标题
            file_name = os.path.basename(file_path)
            self.setWindowTitle(f"文本预览器- {file_name}")
            
            return True
        return False
    
    def set_file(self, file_path):
        """
        设置要显示的文本文件
        """
        self.load_file_from_path(file_path)


# 命令行参数支持
if __name__ == "__main__":
    app = QApplication(sys.argv)
    viewer = TextPreviewer()
    
    # 如果提供了文件路径参数，直接加载
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
        viewer.load_file_from_path(file_path)
    
    viewer.show()
    sys.exit(app.exec_())