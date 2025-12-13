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

2. 商业使用：需联系 qpdrfc123@gmail.com 获取书面授权�?
项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE
独立的文本预览器组件
提供文本文件预览、Markdown渲染和代码语法高亮功�?
"""

import sys
import os
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QFileDialog, QLabel, QScrollArea, QGroupBox, QGridLayout,
    QTextEdit, QComboBox, QMenu, QAction
)
from PyQt5.QtGui import (
    QFont, QIcon
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
            # 第一步：获取文件大小（这一步对于网络文件可能会阻塞，需要优化）
            self.progress_updated.emit(0, "正在获取文件信息...")
            
            # 异步获取文件大小，避免阻塞主线程
            file_size = self._get_file_size_with_timeout()
            if file_size == -1:
                raise Exception("无法获取文件大小")
            
            # 第二步：打开文件并分块读取
            self.progress_updated.emit(5, "正在打开文件...")
            
            # 计算分块大小，根据文件大小动态调整
            # 网络文件使用较小的分块，确保进度实时更新
            chunk_size = 65536  # 64KB，适合网络文件
            
            read_bytes = 0
            content = []
            encoding = self.encoding
            
            # 尝试使用UTF-8编码
            try:
                # 使用二进制模式打开文件，然后手动解码
                # 这样可以更精确地控制读取进度，特别是对于网络文件
                with open(self.file_path, 'rb') as f:
                    while not self.is_cancelled:
                        # 读取二进制数据
                        binary_chunk = f.read(chunk_size)
                        if not binary_chunk:
                            break
                        
                        # 更新已读取字节数
                        read_bytes += len(binary_chunk)
                        
                        # 解码为文本
                        text_chunk = binary_chunk.decode(encoding)
                        content.append(text_chunk)
                        
                        # 计算进度
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
                        # 读取二进制数据
                        binary_chunk = f.read(chunk_size)
                        if not binary_chunk:
                            break
                        
                        # 更新已读取字节数
                        read_bytes += len(binary_chunk)
                        
                        # 解码为文本
                        text_chunk = binary_chunk.decode(encoding)
                        content.append(text_chunk)
                        
                        # 计算进度
                        progress = 5 + int(min(95, (read_bytes / file_size) * 95))
                        self.progress_updated.emit(progress, f"正在读取文件... {progress}%")
            except Exception as e:
                # 处理其他可能的错误
                self.file_read_failed.emit(f"读取文件时出错: {str(e)}")
                return
            
            if not self.is_cancelled:
                self.progress_updated.emit(100, "文件读取完成")
                self.file_read_completed.emit(''.join(content), encoding)
        except Exception as e:
            self.file_read_failed.emit(str(e))
    
    def _get_file_size_with_timeout(self, timeout=5):
        """
        带超时的文件大小获取，避免网络文件阻塞过长时间
        
        Args:
            timeout (int): 超时时间（秒）
            
        Returns:
            int: 文件大小（字节），如果超时返回-1
        """
        import threading
        
        file_size = [0]
        error = [None]
        
        def get_size():
            try:
                file_size[0] = os.path.getsize(self.file_path)
            except Exception as e:
                error[0] = e
        
        # 创建线程获取文件大小
        thread = threading.Thread(target=get_size)
        thread.daemon = True
        thread.start()
        
        # 等待线程完成或超时
        thread.join(timeout)
        
        if thread.is_alive():
            # 超时，尝试使用备用方案
            try:
                # 尝试打开文件并获取大小（对于某些网络文件系统可能更可靠）
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
    文本预览部件，支持Markdown渲染和代码高�?
    """
    # 信号定义
    file_read_progress = pyqtSignal(int, str)  # 文件读取进度信号，参数：进度值(0-100)，状态描述
    file_read_finished = pyqtSignal()  # 文件读取完成信号
    file_read_cancelled = pyqtSignal()  # 文件读取取消信号
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 获取全局字体
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtGui import QFont
        app = QApplication.instance()
        self.global_font = getattr(app, 'global_font', QFont())
        #print(f"[DEBUG] TextPreviewWidget获取到的全局字体: {self.global_font.family()}")
        
        # 设置组件字体
        self.setFont(self.global_font)
        
        # 文件数据
        self.current_file_path = ""
        self.file_content = ""
        
        # 预览模式
        self.preview_mode = "auto"  # auto, text, markdown, code
        
        # 文件读取线程
        self.read_thread = None
        
        # 初始化UI
        self.init_ui()
    
    def init_ui(self):
        """
        初始化预览部件UI
        """
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # 设置背景�?
        self.setStyleSheet("background-color: #f5f5f5;")
        
        # 预览模式选择
        mode_layout = QHBoxLayout()
        mode_layout.setSpacing(10)
        
        mode_label = QLabel("预览模式:")
        mode_label.setFont(self.global_font)
        mode_label.setStyleSheet("font-size: 14px; color: #333; font-weight: 500;")
        
        self.mode_selector = QComboBox()
        self.mode_selector.addItems(["自动检测", "纯文本", "Markdown", "代码高亮"])
        self.mode_selector.currentTextChanged.connect(self.change_preview_mode)
        self.mode_selector.setFont(self.global_font)
        self.mode_selector.setStyleSheet('''.QComboBox {
            background-color: white;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            padding: 8px 12px;
            font-size: 14px;
            color: #333;
        }
        .QComboBox:hover {
            border-color: #1976d2;
        }
        .QComboBox:focus {
            border-color: #1976d2;
            outline: none;
        }''')
        
        mode_layout.addWidget(mode_label)
        mode_layout.addWidget(self.mode_selector)
        mode_layout.addStretch()
        layout.addLayout(mode_layout)
        
        # 预览区域
        self.web_view = QWebEngineView()
        self.web_view.setMinimumHeight(500)
        self.web_view.setStyleSheet("background-color: white; border: 1px solid #e0e0e0; border-radius: 8px;")
        # 为WebView添加自定义上下文菜单
        self.web_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.web_view.customContextMenuRequested.connect(self.show_context_menu)
        layout.addWidget(self.web_view)
        print(f"[DEBUG] TextPreviewWidget UI组件设置字体: {self.global_font.family()}")
    
    def set_file(self, file_path):
        """
        设置要预览的文本文件
        
        Args:
            file_path (str): 文本文件路径
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
        
        Args:
            progress (int): 进度值(0-100)
            status (str): 状态描述
        """
        # 发射进度信号，供外部进度条使用
        self.file_read_progress.emit(progress, status)
    
    def on_file_read_completed(self, content, encoding):
        """
        文件读取完成回调
        
        Args:
            content (str): 文件内容
            encoding (str): 文件编码
        """
        self.file_content = content
        # 更新预览
        self.update_preview()
        # 发射读取完成信号
        self.file_read_finished.emit()
    
    def on_file_read_failed(self, error):
        """
        文件读取失败回调
        
        Args:
            error (str): 错误信息
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
    
    def update_preview(self):
        """
        更新预览内容
        """
        if not self.file_content:
            return
        
        # 自动检测模�?
        if self.preview_mode == "auto":
            # 根据文件扩展名判�?
            ext = os.path.splitext(self.current_file_path)[1].lower()
            if ext in ['.txt']:
                # txt文件使用纯文本模�?
                html_content = self.render_plain_text(self.file_content)
            elif ext in ['.md', '.markdown', '.mdown', '.mkd']:
                # Markdown文件使用Markdown模式
                html_content = self.render_markdown(self.file_content)
            else:
                # 其他代码源文件使用代码高亮模�?
                html_content = self.render_code(self.file_content, self.current_file_path)
        
        # 纯文本模�?
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
        渲染纯文�?
        
        Args:
            content (str): 纯文本内�?
        
        Returns:
            str: HTML格式的文�?
        """
        # 转义HTML特殊字符
        content = content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        content = content.replace('"', '&quot;').replace("'", '&#39;')
        # 替换换行�?
        content = content.replace('\n', '<br>')
        
        # 使用普通字符串拼接，避免f-string中的大括号冲�?
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {
                    font-family: Arial, sans-serif;
                    font-size: 14px;
                    line-height: 1.6;
                    color: #333;
                    margin: 20px;
                    background-color: #fff;
                    word-wrap: break-word;
                    word-break: break-word;
                }
                pre {
                    white-space: pre-wrap;
                    word-wrap: break-word;
                    margin: 0;
                }
            </style>
        </head>
        <body>
            <pre>""" + content + """
            </pre>
        </body>
        </html>
        """
        
        return html
    
    def render_markdown(self, content):
        """
        渲染Markdown
        
        Args:
            content (str): Markdown内容
        
        Returns:
            str: HTML格式的Markdown
        """
        # 使用markdown库将Markdown转换为HTML
        rendered_markdown = markdown.markdown(content, extensions=[
            'markdown.extensions.extra',
            'markdown.extensions.codehilite',
            'markdown.extensions.toc'
        ])
        
        # 添加CSS样式，使用字符串拼接避免f-string冲突
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {
                    font-family: Arial, sans-serif;
                    font-size: 16px;
                    line-height: 1.8;
                    color: #333;
                    margin: 20px;
                    background-color: #fff;
                    word-wrap: break-word;
                    word-break: break-word;
                    overflow-x: hidden;
                }
                h1, h2, h3, h4, h5, h6 {
                    color: #2c3e50;
                    margin-top: 1.5em;
                    margin-bottom: 0.5em;
                    word-wrap: break-word;
                }
                code {
                    background-color: #f0f0f0;
                    padding: 2px 4px;
                    border-radius: 3px;
                    font-family: Consolas, Monaco, 'Andale Mono', monospace;
                    word-wrap: break-word;
                }
                pre {
                    background-color: #f8f8f8;
                    border: 1px solid #e8e8e8;
                    border-radius: 5px;
                    padding: 15px;
                    white-space: pre-wrap;
                    word-wrap: break-word;
                    overflow-x: auto;
                }
                pre code {
                    background-color: transparent;
                    padding: 0;
                }
                blockquote {
                    border-left: 4px solid #ddd;
                    margin-left: 0;
                    padding-left: 20px;
                    color: #666;
                    word-wrap: break-word;
                }
                table {
                    border-collapse: collapse;
                    width: 100%;
                    margin: 20px 0;
                    word-wrap: break-word;
                }
                th, td {
                    border: 1px solid #ddd;
                    padding: 8px 12px;
                    text-align: left;
                    word-wrap: break-word;
                }
                th {
                    background-color: #f0f0f0;
                }
                img {
                    max-width: 100%;
                    height: auto;
                }
            </style>
        </head>
        <body>
        """ + rendered_markdown + """
        </body>
        </html>
        """
        
        return html
    
    def render_code(self, content, filename):
        """
        渲染代码高亮
        
        Args:
            content (str): 代码内容
            filename (str): 文件名，用于自动检测语言
        
        Returns:
            str: HTML格式的高亮代�?
        """
        try:
            # 尝试根据文件名获取合适的词法分析�?
            lexer = get_lexer_for_filename(filename)
        except:
            # 如果无法获取，使用文本词法分析器
            lexer = TextLexer()
        
        # 创建HTML格式化器，不生成完整HTML文档
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
        
        # 创建完整HTML文档，添加自动换行样�?
        # 使用普通字符串拼接，避免f-string中的大括号冲�?
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
        """ + css + """
                body {
                    font-family: Arial, sans-serif;
                    font-size: 14px;
                    line-height: 1.6;
                    color: #333;
                    margin: 20px;
                    background-color: #fff;
                    word-wrap: break-word;
                    word-break: break-word;
                    overflow-x: hidden;
                }
                .highlight {
                    background-color: #f8f8f8;
                    border: 1px solid #e8e8e8;
                    border-radius: 5px;
                    padding: 15px;
                    overflow-x: auto;
                }
                .highlight pre {
                    margin: 0;
                    white-space: pre-wrap;
                    word-wrap: break-word;
                }
                .highlight table {
                    width: 100%;
                    word-wrap: break-word;
                }
                .highlight td {
                    vertical-align: top;
                    word-wrap: break-word;
                }
                .highlight code {
                    font-family: Consolas, Monaco, 'Andale Mono', monospace;
                    font-size: 13px;
                    word-wrap: break-word;
                }
            </style>
        </head>
        <body>
        """ + highlighted_code + """
        </body>
        </html>
        """
        
        return html


class TextPreviewer(QMainWindow):
    """
    文本预览器主窗口
    """
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("文本预览器")
        self.setGeometry(100, 100, 1000, 800)
        
        # 获取全局字体
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtGui import QFont
        app = QApplication.instance()
        self.global_font = getattr(app, 'global_font', QFont())
        #print(f"[DEBUG] TextPreviewer获取到的全局字体: {self.global_font.family()}")
        
        # 设置窗口字体
        self.setFont(self.global_font)
        
        # 创建UI
        self.init_ui()
    
    def init_ui(self):
        """
        初始化用户界�?
        """
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 创建主布局
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 设置整体背景�?
        self.setStyleSheet("background-color: #f5f5f5;")
        
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
            "文本文件 (*.txt *.md *.markdown *.mdown *.mkd *.py *.js *.html *.css *.json *.yaml *.yml *.xml *.java *.c *.cpp *.h *.hpp *.go *.rs);;所有文�?(*)"
        )
        
        if file_path:
            self.load_file_from_path(file_path)
    
    def load_file_from_path(self, file_path):
        """
        从外部路径加载文本文�?
        
        Args:
            file_path (str): 文本文件路径
        """
        if self.text_widget.set_file(file_path):
            # 更新窗口标题
            file_name = os.path.basename(file_path)
            self.setWindowTitle(f"文本预览�?- {file_name}")
            
            return True
        return False
    
    def set_file(self, file_path):
        """
        设置要显示的文本文件
        
        Args:
            file_path (str): 文本文件路径
        """
        self.load_file_from_path(file_path)


# 命令行参数支�?
if __name__ == "__main__":
    app = QApplication(sys.argv)
    viewer = TextPreviewer()
    
    # 如果提供了文件路径参数，直接加载
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
        viewer.load_file_from_path(file_path)
    
    viewer.show()
    sys.exit(app.exec_())

