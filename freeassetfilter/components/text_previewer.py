#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

文本预览器组件
支持多种文档格式的预览，包括纯文本、Markdown和各种代码文件
特点：
- 多编码支持（自动检测GBK/UTF-8等）
- Markdown渲染支持
- 代码语法高亮（Python/JSON/XML等）
- 大文件分块加载和渲染优化
- 集成平滑滚动（D_ScrollBar）
- 线程安全设计
- 查找和高亮功能
- 完整的控制栏（字体/大小/编码/查找）
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QComboBox, QSlider, QTextEdit, QFrame, QApplication,
    QGridLayout, QSizePolicy, QMessageBox, QToolBar, QAction,
    QLineEdit, QPushButton, QWidgetAction
)
from PyQt5.QtGui import (
    QFont, QIcon, QTextCursor, QTextDocument, QSyntaxHighlighter,
    QTextCharFormat, QColor, QFontDatabase, QPalette, QPainter,
    QTextFormat, QBrush, QTextBlock
)
from PyQt5.QtCore import (
    Qt, QSize, QTimer, pyqtSignal, QThread, QStringListModel,
    QRegularExpression, QMutex, QMutexLocker
)
from PyQt5.QtGui import (
    QFont, QIcon, QTextCursor, QTextDocument, QSyntaxHighlighter,
    QTextCharFormat, QColor, QFontDatabase, QPalette, QPainter,
    QTextFormat, QBrush, QTextBlock
)

import re
import colorsys

from freeassetfilter.widgets.D_widgets import CustomButton
from freeassetfilter.widgets.D_more_menu import D_MoreMenu
from freeassetfilter.widgets.smooth_scroller import D_ScrollBar, SmoothScroller
from freeassetfilter.widgets.input_widgets import CustomInputBox
from freeassetfilter.widgets.progress_widgets import D_ProgressBar
from freeassetfilter.widgets.dropdown_menu import CustomDropdownMenu

try:
    import markdown
    MARKDOWN_AVAILABLE = True
except ImportError:
    MARKDOWN_AVAILABLE = False

try:
    from pygments import lex
    from pygments.lexers import get_lexer_by_name, get_lexer_for_filename, TextLexer
    from pygments.token import Token
    PYGMENTS_AVAILABLE = True
except ImportError:
    PYGMENTS_AVAILABLE = False

try:
    import chardet
    CHARDET_AVAILABLE = True
except ImportError:
    CHARDET_AVAILABLE = False

ENCODING_LIST = ['UTF-8', 'GBK', 'GB2312', 'BIG5', 'LATIN1', 'UTF-16', 'ASCII']

CODE_EXTENSIONS = {
    '.py': 'python', '.js': 'javascript', '.ts': 'typescript',
    '.json': 'json', '.xml': 'xml', '.html': 'html', '.css': 'css',
    '.c': 'c', '.cpp': 'cpp', '.h': 'c', '.hpp': 'cpp',
    '.java': 'java', '.cs': 'csharp', '.go': 'go', '.rust': 'rust',
    '.sql': 'sql', '.sh': 'bash', '.bat': 'batch', '.ps1': 'powershell',
    '.yml': 'yaml', '.yaml': 'yaml', '.ini': 'ini', '.cfg': 'ini',
    '.toml': 'toml', '.md': 'markdown', '.rst': 'rst', '.lua': 'lua',
    '.php': 'php', '.rb': 'ruby', '.swift': 'swift', '.kt': 'kotlin',
    '.r': 'r', '.m': 'matlab', '.pl': 'perl', '.pm': 'perl'
}

TEXT_EXTENSIONS = {
    '.txt', '.log', '.md', '.markdown', '.csv', '.rst', '.json', '.xml',
    '.html', '.htm', '.css', '.js', '.ts', '.yaml', '.yml', '.ini',
    '.cfg', '.conf', '.env', '.gitignore', '.gitconfig', '.properties',
    '.c', '.cpp', '.h', '.hpp', '.java', '.cs', '.py', '.go', '.rs',
    '.sql', '.sh', '.bat', '.php', '.rb', '.lua', '.swift', '.kt',
    '.r', '.m', '.pl', '.pm', '.tex', '.latex', '.asciidoc', '.adoc',
    '.vue', '.jsx', '.tsx', '.sass', '.scss', '.less', '.styl'
}


class SyntaxHighlighter(QSyntaxHighlighter):
    """基础语法高亮器"""
    
    def __init__(self, parent=None, theme='dark'):
        super().__init__(parent)
        self.highlighting_rules = []
        self.theme = theme
        self._build_highlighting_rules()
    
    def _build_highlighting_rules(self):
        """构建高亮规则 - 参考现代 IDE 配色方案"""
        if self.theme == 'dark':
            # 深色主题配色 - 参考 VS Code 等现代编辑器
            self._colors = {
                'keyword': QColor('#FF7B72'),      # 关键字：橙红色 (if, while, return 等)
                'string': QColor('#A5D6FF'),       # 字符串：浅蓝色
                'number': QColor('#79C0FF'),       # 数字：亮蓝色
                'comment': QColor('#8B949E'),      # 注释：灰色
                'function': QColor('#D2A8FF'),     # 函数名：紫色
                'class': QColor('#FFA657'),        # 类名：橙色
                'operator': QColor('#FF7B72'),     # 运算符：橙红色
                'punctuation': QColor('#C9D1D9'),  # 标点符号：浅灰色
                'default': QColor('#C9D1D9'),      # 默认文本：浅灰色
                'tag': QColor('#7EE787'),          # XML/HTML 标签：绿色
                'attribute': QColor('#79C0FF'),    # XML/HTML 属性名：亮蓝色
                'value': QColor('#A5D6FF'),        # XML/HTML 属性值：浅蓝色
                'property': QColor('#79C0FF'),     # JSON 键名：亮蓝色
                'preprocessor': QColor('#FF7B72'), # 预处理指令：橙红色
            }
        else:
            # 浅色主题配色
            self._colors = {
                'keyword': QColor('#D73A49'),      # 关键字：红色
                'string': QColor('#032F62'),       # 字符串：深蓝色
                'number': QColor('#005CC5'),       # 数字：蓝色
                'comment': QColor('#6A737D'),      # 注释：灰色
                'function': QColor('#6F42C1'),     # 函数名：紫色
                'class': QColor('#E36209'),        # 类名：橙色
                'operator': QColor('#D73A49'),     # 运算符：红色
                'punctuation': QColor('#24292E'),  # 标点符号：深灰色
                'default': QColor('#24292E'),      # 默认文本：深灰色
                'tag': QColor('#22863A'),          # XML/HTML 标签：绿色
                'attribute': QColor('#005CC5'),    # XML/HTML 属性名：蓝色
                'value': QColor('#032F62'),        # XML/HTML 属性值：深蓝色
                'property': QColor('#005CC5'),     # JSON 键名：蓝色
                'preprocessor': QColor('#D73A49'), # 预处理指令：红色
            }
    
    def highlightBlock(self, text):
        """高亮文本块

        参数：
            text (str): 当前文本块的内容
        """
        if not text:
            return

        for pattern, fmt in self.highlighting_rules:
            match_iterator = pattern.globalMatch(text)
            while match_iterator.hasNext():
                match = match_iterator.next()
                start = match.capturedStart()
                length = match.capturedLength()
                self.setFormat(start, length, fmt)
    
    def setTheme(self, theme):
        """设置主题"""
        self.theme = theme
        self._build_highlighting_rules()


class PythonHighlighter(SyntaxHighlighter):
    """Python语法高亮器"""
    
    def __init__(self, parent=None, theme='dark'):
        super().__init__(parent, theme)
        self._build_python_rules()
    
    def _build_python_rules(self):
        """构建Python高亮规则"""
        keyword_patterns = [
            r'\bdef\b', r'\bclass\b', r'\bimport\b', r'\bfrom\b',
            r'\breturn\b', r'\bif\b', r'\belif\b', r'\belse\b',
            r'\bfor\b', r'\bwhile\b', r'\btry\b', r'\bexcept\b',
            r'\bwith\b', r'\bas\b', r'\bpass\b', r'\bbreak\b',
            r'\bcontinue\b', r'\blambda\b', r'\byield\b', r'\bglobal\b',
            r'\bnonlocal\b', r'\bassert\b', r'\braise\b', r'\bdel\b',
            r'\band\b', r'\bor\b', r'\bnot\b', r'\bin\b', r'\bis\b',
            r'\bTrue\b', r'\bFalse\b', r'\bNone\b', r'\bself\b'
        ]
        
        keyword_format = QTextCharFormat()
        keyword_format.setForeground(self._colors['keyword'])
        keyword_format.setFontWeight(QFont.Bold)
        
        for pattern in keyword_patterns:
            regex = QRegularExpression(pattern)
            self.highlighting_rules.append((regex, keyword_format))
        
        string_patterns = [
            (r'""".*?"""', QTextCharFormat()),
            (r"'''.*?'''", QTextCharFormat()),
            (r'".*?"', QTextCharFormat()),
            (r'".*?$', QTextCharFormat()),
            (r"'.*?'", QTextCharFormat()),
            (r"'.*?$", QTextCharFormat()),
        ]
        
        string_format = QTextCharFormat()
        string_format.setForeground(self._colors['string'])
        
        for pattern, fmt in string_patterns:
            regex = QRegularExpression(pattern)
            fmt_copy = QTextCharFormat(string_format)
            self.highlighting_rules.append((regex, fmt_copy))
        
        number_format = QTextCharFormat()
        number_format.setForeground(self._colors['number'])
        number_regex = QRegularExpression(r'\b[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?\b')
        self.highlighting_rules.append((number_regex, number_format))
        
        comment_format = QTextCharFormat()
        comment_format.setForeground(self._colors['comment'])
        comment_regex = QRegularExpression(r'#.*$')
        comment_regex.setPatternOptions(QRegularExpression.MultilineOption)
        self.highlighting_rules.append((comment_regex, comment_format))
        
        function_format = QTextCharFormat()
        function_format.setForeground(self._colors['function'])
        function_regex = QRegularExpression(r'\b[a-zA-Z_]\w*(?=\s*\()')
        self.highlighting_rules.append((function_regex, function_format))


class JsonHighlighter(SyntaxHighlighter):
    """JSON语法高亮器 - 优化版本

    支持以下元素的高亮：
    - 键名（属性名）：使用 attribute 颜色
    - 字符串值：使用 string 颜色
    - 数字：使用 number 颜色
    - 布尔值和 null：使用 keyword 颜色
    - 标点符号：使用 punctuation 颜色
    """

    def __init__(self, parent=None, theme='dark'):
        super().__init__(parent, theme)
        self._build_json_rules()

    def _build_json_rules(self):
        """构建 JSON 高亮规则"""
        # 键名高亮 - 匹配 "key": 中的 key 部分
        key_format = QTextCharFormat()
        key_format.setForeground(self._colors['property'])
        key_format.setFontWeight(QFont.Bold)
        # 匹配双引号内的键名，后面跟着冒号
        key_regex = QRegularExpression(r'"(?:[^"\\]|\\.)*"(?=\s*:)')
        self.highlighting_rules.append((key_regex, key_format))

        # 字符串值高亮 - 匹配普通字符串值
        string_format = QTextCharFormat()
        string_format.setForeground(self._colors['string'])
        string_regex = QRegularExpression(r'"(?:[^"\\]|\\.)*"')
        self.highlighting_rules.append((string_regex, string_format))

        # 数字高亮
        number_format = QTextCharFormat()
        number_format.setForeground(self._colors['number'])
        number_regex = QRegularExpression(r'\b-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?\b')
        self.highlighting_rules.append((number_regex, number_format))

        # 布尔值和 null 高亮
        bool_format = QTextCharFormat()
        bool_format.setForeground(self._colors['keyword'])
        bool_format.setFontWeight(QFont.Bold)
        bool_regex = QRegularExpression(r'\b(?:true|false|null)\b')
        self.highlighting_rules.append((bool_regex, bool_format))

        # 标点符号高亮
        punct_format = QTextCharFormat()
        punct_format.setForeground(self._colors['punctuation'])
        punct_regex = QRegularExpression(r'[{}\[\]:,]')
        self.highlighting_rules.append((punct_regex, punct_format))

    def highlightBlock(self, text):
        """高亮当前文本块 - 重写基类方法以正确处理键名和字符串的优先级"""
        if not text:
            return

        # 首先标记所有键名和字符串的位置（这些区域不应该被数字等规则覆盖）
        protected_ranges = []

        # 1. 处理键名
        key_pattern = self.highlighting_rules[0][0]  # 第一个规则是键名
        key_format = self.highlighting_rules[0][1]

        match_iterator = key_pattern.globalMatch(text)
        while match_iterator.hasNext():
            match = match_iterator.next()
            start = match.capturedStart()
            length = match.capturedLength()
            protected_ranges.append((start, start + length))
            self.setFormat(start, length, key_format)

        # 2. 处理字符串值（第二个规则是字符串）
        string_pattern = self.highlighting_rules[1][0]
        string_format = self.highlighting_rules[1][1]

        match_iterator = string_pattern.globalMatch(text)
        while match_iterator.hasNext():
            match = match_iterator.next()
            start = match.capturedStart()
            length = match.capturedLength()
            end = start + length

            # 检查是否与键名范围重叠
            is_key = False
            for key_start, key_end in protected_ranges:
                if start == key_start and end == key_end:
                    is_key = True
                    break

            if not is_key:
                # 这是普通字符串值，需要保护其内部不被数字规则覆盖
                protected_ranges.append((start, end))
                self.setFormat(start, length, string_format)

        # 3. 应用其他规则（数字、布尔值、标点符号），但跳过受保护的范围
        for pattern, fmt in self.highlighting_rules[2:]:
            match_iterator = pattern.globalMatch(text)
            while match_iterator.hasNext():
                match = match_iterator.next()
                start = match.capturedStart()
                length = match.capturedLength()
                end = start + length

                # 检查是否与受保护范围重叠
                overlaps_protected = False
                for protected_start, protected_end in protected_ranges:
                    if start < protected_end and end > protected_start:
                        overlaps_protected = True
                        break

                if not overlaps_protected:
                    self.setFormat(start, length, fmt)


class XmlHighlighter(SyntaxHighlighter):
    """XML/HTML语法高亮器 - 优化版本

    支持以下元素的高亮：
    - 标签名：使用 tag 颜色
    - 属性名：使用 attribute 颜色
    - 属性值（字符串）：使用 value 颜色
    - 注释：使用 comment 颜色
    - 处理指令（如 <?xml ?>）：使用 keyword 颜色
    - CDATA 区块：使用 string 颜色
    - 实体引用：使用 number 颜色
    """

    def __init__(self, parent=None, theme='dark'):
        super().__init__(parent, theme)
        self._build_xml_rules()

    def _build_xml_rules(self):
        """构建 XML/HTML 高亮规则"""
        # 注释高亮 - 优先匹配，避免与其他规则冲突
        comment_format = QTextCharFormat()
        comment_format.setForeground(self._colors['comment'])
        comment_format.setFontItalic(True)
        comment_regex = QRegularExpression(r'<!--[\s\S]*?-->')
        self.highlighting_rules.append((comment_regex, comment_format))

        # CDATA 区块高亮
        cdata_format = QTextCharFormat()
        cdata_format.setForeground(self._colors['string'])
        cdata_regex = QRegularExpression(r'<!\[CDATA\[[\s\S]*?\]\]>')
        self.highlighting_rules.append((cdata_regex, cdata_format))

        # DOCTYPE 声明高亮
        doctype_format = QTextCharFormat()
        doctype_format.setForeground(self._colors['keyword'])
        doctype_format.setFontWeight(QFont.Bold)
        doctype_regex = QRegularExpression(r'<!DOCTYPE[^>]*>')
        self.highlighting_rules.append((doctype_regex, doctype_format))

        # 处理指令高亮（如 <?xml version="1.0"?>）
        pi_format = QTextCharFormat()
        pi_format.setForeground(self._colors['keyword'])
        pi_regex = QRegularExpression(r'<\?[^?]*\?>')
        self.highlighting_rules.append((pi_regex, pi_format))

        # 结束标签高亮
        end_tag_format = QTextCharFormat()
        end_tag_format.setForeground(self._colors['tag'])
        end_tag_regex = QRegularExpression(r'</[a-zA-Z][a-zA-Z0-9:._-]*\s*>')
        self.highlighting_rules.append((end_tag_regex, end_tag_format))

        # 开始标签名高亮（包括自闭合标签）
        tag_format = QTextCharFormat()
        tag_format.setForeground(self._colors['tag'])
        tag_format.setFontWeight(QFont.Bold)
        # 匹配 <tag 或 <tag> 中的 tag 部分
        tag_regex = QRegularExpression(r'<[a-zA-Z][a-zA-Z0-9:._-]*')
        self.highlighting_rules.append((tag_regex, tag_format))

        # 属性名高亮
        attr_format = QTextCharFormat()
        attr_format.setForeground(self._colors['attribute'])
        # 匹配属性名，支持 XML 命名空间前缀
        attr_regex = QRegularExpression(r'\s[a-zA-Z_:][a-zA-Z0-9:._-]*(?=\s*=)')
        self.highlighting_rules.append((attr_regex, attr_format))

        # 属性值高亮（双引号）
        string_format = QTextCharFormat()
        string_format.setForeground(self._colors['value'])
        string_regex = QRegularExpression(r'"(?:[^"\\]|\\.)*"')
        self.highlighting_rules.append((string_regex, string_format))

        # 属性值高亮（单引号）
        string_single_format = QTextCharFormat()
        string_single_format.setForeground(self._colors['value'])
        string_single_regex = QRegularExpression(r"'(?:[^'\\]|\\.)*'")
        self.highlighting_rules.append((string_single_regex, string_single_format))

        # 实体引用高亮（如 &amp; &#123;）
        entity_format = QTextCharFormat()
        entity_format.setForeground(self._colors['number'])
        entity_regex = QRegularExpression(r'&(?:#[0-9]+|#x[0-9a-fA-F]+|[a-zA-Z][a-zA-Z0-9]*);')
        self.highlighting_rules.append((entity_regex, entity_format))

        # 标签结束符号高亮
        punct_format = QTextCharFormat()
        punct_format.setForeground(self._colors['punctuation'])
        punct_regex = QRegularExpression(r'[<>/]')
        self.highlighting_rules.append((punct_regex, punct_format))

    def highlightBlock(self, text):
        """高亮当前文本块 - 重写基类方法以正确工作"""
        if not text:
            return

        for pattern, fmt in self.highlighting_rules:
            match_iterator = pattern.globalMatch(text)
            while match_iterator.hasNext():
                match = match_iterator.next()
                start = match.capturedStart()
                length = match.capturedLength()
                self.setFormat(start, length, fmt)


class TextPreviewThread(QThread):
    """文本加载后台线程"""
    
    finished = pyqtSignal(str, bool)
    error = pyqtSignal(str)
    progress = pyqtSignal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.file_path = ""
        self.encoding = "auto"
        self.max_size = 10 * 1024 * 1024
        self._mutex = QMutex()
        self._abort = False
    
    def setFile(self, file_path, encoding="auto"):
        """设置要加载的文件"""
        with QMutexLocker(self._mutex):
            self.file_path = file_path
            self.encoding = encoding
    
    def abort(self):
        """请求终止"""
        with QMutexLocker(self._mutex):
            self._abort = True
    
    def run(self):
        """执行文件加载"""
        with QMutexLocker(self._mutex):
            if self._abort:
                return
            file_path = self.file_path
            encoding = self.encoding
        
        try:
            file_size = os.path.getsize(file_path)
            
            if file_size > self.max_size:
                self.error.emit(f"文件过大 ({file_size / 1024 / 1024:.1f}MB)，最大支持 {self.max_size / 1024 / 1024:.0f}MB")
                return
            
            content = ""
            detected_encoding = None
            
            if encoding == "auto":
                if CHARDET_AVAILABLE:
                    with open(file_path, 'rb') as f:
                        raw_data = f.read(1024 * 1024)
                        result = chardet.detect(raw_data)
                        detected_encoding = result.get('encoding', 'utf-8')
                        
                        if detected_encoding and detected_encoding.lower() != 'ascii':
                            try:
                                content = raw_data.decode(detected_encoding)
                                self.progress.emit(100)
                            except UnicodeDecodeError:
                                detected_encoding = 'utf-8'
                                content = raw_data.decode('utf-8', errors='replace')
                                self.progress.emit(100)
                        else:
                            try:
                                content = raw_data.decode('utf-8')
                                self.progress.emit(100)
                            except UnicodeDecodeError:
                                content = raw_data.decode('utf-8', errors='replace')
                                self.progress.emit(100)
                    
                    if file_size > len(raw_data):
                        with open(file_path, 'r', encoding=detected_encoding or 'utf-8',
                                  errors='replace') as f:
                            remaining = f.read()
                            content += remaining
                else:
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        detected_encoding = 'utf-8'
                    except UnicodeDecodeError:
                        try:
                            with open(file_path, 'r', encoding='gbk') as f:
                                content = f.read()
                            detected_encoding = 'gbk'
                        except UnicodeDecodeError:
                            with open(file_path, 'r', encoding='utf-8',
                                      errors='replace') as f:
                                content = f.read()
                            detected_encoding = 'utf-8 (with replacements)'
            else:
                try:
                    with open(file_path, 'r', encoding=encoding,
                              errors='replace') as f:
                        content = f.read()
                    detected_encoding = encoding
                except Exception as e:
                    self.error.emit(f"无法使用 {encoding} 编码读取文件: {str(e)}")
                    return
            
            self.finished.emit(content, True)
            
        except Exception as e:
            self.error.emit(f"读取文件失败: {str(e)}")


class TextPreviewWidget(QWidget):
    """
    文本预览主控件
    负责文本显示、格式渲染和用户交互
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        self.global_font = getattr(app, 'global_font', QFont())
        self.default_font_size = getattr(app, 'default_font_size', 12)
        
        self.current_file_path = ""
        self.current_encoding = "auto"
        self.is_markdown = False
        self.current_highlighter = None
        self.file_content = ""
        
        self._thread = None
        self._mutex = QMutex()
        self._is_loading = False
        
        self._search_results = []
        self._current_search_index = -1
        self._search_term = ""
        self._case_sensitive = False
        
        self._init_ui()
        self._apply_theme()
    
    def _init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        self._init_toolbar(layout)
        self._init_text_edit(layout)
        self._init_search_bar(layout)
        self._init_progress_bar(layout)
    
    def _init_toolbar(self, parent_layout):
        """初始化工具栏"""
        toolbar = QWidget()
        toolbar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(10, 5, 10, 5)
        toolbar_layout.setSpacing(10)
        
        app = QApplication.instance()
        text_color = "#333333"
        if hasattr(app, 'settings_manager'):
            text_color = app.settings_manager.get_setting("appearance.colors.secondary_color", "#333333")
        
        icon_dir = os.path.join(os.path.dirname(__file__), '..', 'icons')
        font_icon_path = os.path.join(icon_dir, "font.svg")
        
        self.font_dropdown = CustomDropdownMenu(use_internal_button=False)
        self.font_dropdown.set_fixed_width(int(100 * self.dpi_scale))
        self.font_button = CustomButton(
            font_icon_path,
            button_type="normal",
            display_mode="icon",
            tooltip_text="字体"
        )
        self.font_dropdown.set_target_button(self.font_button)
        
        available_fonts = sorted(set(QFontDatabase().families()))
        default_font = QFont().family()
        font_items = ["默认字体"] + available_fonts
        default_index = 0
        self.font_dropdown.set_items(font_items, font_items[default_index])
        self.font_dropdown.itemClicked.connect(self._on_font_selected)
        self.font_button.clicked.connect(self.font_dropdown.show_menu)
        toolbar_layout.addWidget(self.font_button)
        
        self.encoding_dropdown = CustomDropdownMenu(use_internal_button=False)
        self.encoding_dropdown.set_fixed_width(int(60 * self.dpi_scale))
        encoding_icon_path = os.path.join(icon_dir, "earth.svg")
        self.encoding_button = CustomButton(
            encoding_icon_path,
            button_type="normal",
            display_mode="icon",
            tooltip_text="编码"
        )
        self.encoding_dropdown.set_target_button(self.encoding_button)
        self.encoding_dropdown.set_items(["自动检测"] + ENCODING_LIST, "自动检测")
        self.encoding_dropdown.itemClicked.connect(self._on_encoding_selected)
        self.encoding_button.clicked.connect(self.encoding_dropdown.show_menu)
        toolbar_layout.addWidget(self.encoding_button)
        
        size_label = QLabel("大小")
        size_label.setStyleSheet(f"color: {text_color};")
        toolbar_layout.addWidget(size_label)
        
        self.font_size_slider = D_ProgressBar(
            orientation=D_ProgressBar.Horizontal,
            is_interactive=True
        )
        self.font_size_slider.setRange(4, 40)
        self.font_size_slider.setValue(self.default_font_size)
        self.font_size_slider.setFixedWidth(int(100 * self.dpi_scale))
        self.font_size_slider.valueChanged.connect(self._on_font_size_changed)
        toolbar_layout.addWidget(self.font_size_slider)
        
        toolbar_layout.addStretch()
        
        icon_dir = os.path.join(os.path.dirname(__file__), '..', 'icons')
        search_icon_path = os.path.join(icon_dir, "search.svg")
        
        self.search_button = CustomButton(
            search_icon_path,
            button_type="normal",
            display_mode="icon",
            tooltip_text="查找 (Ctrl+F)"
        )
        self.search_button.clicked.connect(self._toggle_search)
        toolbar_layout.addWidget(self.search_button)
        
        parent_layout.addWidget(toolbar)
    
    def _init_text_edit(self, parent_layout):
        """初始化文本编辑区"""
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        app = QApplication.instance()
        base_color = "#FFFFFF"
        if hasattr(app, 'settings_manager'):
            base_color = app.settings_manager.get_setting("appearance.colors.base_color", "#FFFFFF")

        container.setStyleSheet(f"background-color: {base_color};")
        
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setLineWrapMode(QTextEdit.NoWrap)
        self.text_edit.setUndoRedoEnabled(False)
        self.text_edit.setContextMenuPolicy(Qt.CustomContextMenu)
        self.text_edit.customContextMenuRequested.connect(self._show_context_menu)
        
        default_font = QFont()
        default_font.setPointSize(int(self.default_font_size * self.dpi_scale))
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
                padding: 10px;
            }}
        """)
        
        scroll_bar = D_ScrollBar(self.text_edit, Qt.Vertical)
        self.text_edit.setVerticalScrollBar(scroll_bar)
        scroll_bar.apply_theme_from_settings()
        
        horizontal_scroll_bar = D_ScrollBar(self.text_edit, Qt.Horizontal)
        self.text_edit.setHorizontalScrollBar(horizontal_scroll_bar)
        horizontal_scroll_bar.apply_theme_from_settings()
        
        container_layout.addWidget(self.text_edit)
        
        parent_layout.addWidget(container)
        
        SmoothScroller.apply_to_scroll_area(self.text_edit)
        
        self._init_context_menu()
    
    def _init_context_menu(self):
        """初始化右键菜单"""
        self.context_menu = D_MoreMenu(self.text_edit)
        self.context_menu.set_items([
            {"text": "复制", "data": "copy"},
            {"text": "全选", "data": "select_all"}
        ])
        self.context_menu.itemClicked.connect(self._on_context_menu_clicked)
    
    def _on_context_menu_clicked(self, data):
        """处理右键菜单项点击"""
        if data == "copy":
            self.text_edit.copy()
        elif data == "select_all":
            self.text_edit.selectAll()
    
    def _show_context_menu(self, pos):
        """显示右键菜单"""
        # 将局部坐标转换为全局坐标
        global_pos = self.text_edit.mapToGlobal(pos)
        self.context_menu.popup(global_pos)
    
    def _init_search_bar(self, parent_layout):
        """初始化搜索栏"""
        self.search_bar = QWidget()
        self.search_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        search_layout = QHBoxLayout(self.search_bar)
        search_layout.setContentsMargins(10, 5, 10, 5)
        search_layout.setSpacing(5)
        
        icon_dir = os.path.join(os.path.dirname(__file__), '..', 'icons')
        
        self.search_input = CustomInputBox(
            placeholder_text="查找文本...",
            height=20
        )
        self.search_input.setMinimumWidth(int(50 * self.dpi_scale))
        self.search_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.search_input.textChanged.connect(self._on_search_text_changed)
        self.search_input.editingFinished.connect(self._perform_search)
        search_layout.addWidget(self.search_input, stretch=1)
        
        self.search_word_button = CustomButton(
            "查询",
            button_type="primary",
            display_mode="text",
            height=20,
            tooltip_text="执行搜索"
        )
        self.search_word_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.search_word_button.clicked.connect(self._perform_search)
        search_layout.addWidget(self.search_word_button)
        
        self.search_prev_button = CustomButton(
            os.path.join(icon_dir, "arrow_left.svg"),
            button_type="normal",
            display_mode="icon",
            tooltip_text="上一个"
        )
        self.search_prev_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.search_prev_button.clicked.connect(self._go_to_previous_match)
        search_layout.addWidget(self.search_prev_button)
        
        self.search_info_label = QLabel("0/0")
        self.search_info_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        app = QApplication.instance()
        if hasattr(app, 'settings_manager'):
            secondary_color = app.settings_manager.get_setting("appearance.colors.secondary_color", "#666666")
            self.search_info_label.setStyleSheet(f"color: {secondary_color};")
        search_layout.addWidget(self.search_info_label)
        
        self.search_next_button = CustomButton(
            os.path.join(icon_dir, "arrow_right.svg"),
            button_type="normal",
            display_mode="icon",
            tooltip_text="下一个"
        )
        self.search_next_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.search_next_button.clicked.connect(self._go_to_next_match)
        search_layout.addWidget(self.search_next_button)
        
        self.search_bar.hide()
        parent_layout.addWidget(self.search_bar)
    
    def _init_progress_bar(self, parent_layout):
        """初始化进度条"""
        self.progress_bar = D_ProgressBar(
            orientation=D_ProgressBar.Horizontal,
            is_interactive=False
        )
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(int(4 * self.dpi_scale))
        parent_layout.addWidget(self.progress_bar)
    
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
                padding: 10px;
            }}
        """)
    
    def _detect_file_type(self, file_path):
        """检测文件类型"""
        _, ext = os.path.splitext(file_path)
        ext = ext.lower()
        
        if ext in ['.md', '.markdown']:
            return 'markdown'
        
        if ext in CODE_EXTENSIONS:
            return 'code'
        
        if ext in TEXT_EXTENSIONS:
            return 'text'
        
        return 'text'
    
    def _create_highlighter(self, file_type):
        """创建语法高亮器"""
        theme = 'dark'
        app = QApplication.instance()
        if hasattr(app, 'settings_manager'):
            theme = 'light'
        
        if file_type == 'python':
            self.current_highlighter = PythonHighlighter(self.text_edit.document(), theme)
        elif file_type == 'json':
            self.current_highlighter = JsonHighlighter(self.text_edit.document(), theme)
        elif file_type in ['xml', 'html', 'css']:
            self.current_highlighter = XmlHighlighter(self.text_edit.document(), theme)
        else:
            self.current_highlighter = None
    
    def set_file(self, file_path):
        """
        设置要预览的文件
        
        Args:
            file_path (str): 文件路径
        """
        if not os.path.exists(file_path):
            return
        
        self.current_file_path = file_path
        
        self._clear_search()
        
        if self._thread and self._thread.isRunning():
            self._thread.abort()
            self._thread.wait()
        
        self.text_edit.clear()
        self.text_edit.setDocument(QTextDocument())
        
        if self.current_highlighter:
            self.current_highlighter.deleteLater()
            self.current_highlighter = None
        
        self.file_content = ""
        self.is_markdown = False
        
        self._start_loading()
        
        current_item = self.encoding_dropdown._current_item
        if isinstance(current_item, dict):
            encoding = current_item.get('text', '')
        else:
            encoding = current_item if current_item else "自动检测"
        if encoding == "自动检测":
            encoding = "auto"
        
        self._load_file_async(file_path, encoding)
    
    def _load_file_async(self, file_path, encoding):
        """异步加载文件"""
        if self._thread and self._thread.isRunning():
            self._thread.abort()
            self._thread.wait()
        
        self._thread = TextPreviewThread(self)
        self._thread.setFile(file_path, encoding)
        self._thread.finished.connect(self._on_file_loaded)
        self._thread.error.connect(self._on_load_error)
        self._thread.progress.connect(self._on_load_progress)
        self._thread.start()
    
    def _is_grayscale(self, r, g, b):
        """判断颜色是否为灰度（彩色分量接近相等）"""
        max_val = max(r, g, b)
        min_val = min(r, g, b)
        return (max_val - min_val) < 15
    
    def _is_light_color(self, hex_color):
        """
        判断颜色是否为浅色
        
        Args:
            hex_color: 十六进制颜色字符串，如 '#RRGGBB'
            
        Returns:
            bool: 是否为浅色（亮度 > 0.5）
        """
        if not hex_color or not hex_color.startswith('#') or len(hex_color) != 7:
            return False
        
        try:
            r = int(hex_color[1:3], 16)
            g = int(hex_color[3:5], 16)
            b = int(hex_color[5:7], 16)
            
            # 计算亮度 (使用相对亮度公式)
            luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
            return luminance > 0.5
        except (ValueError, IndexError):
            return False
    
    def _invert_grayscale(self, r, g, b):
        """反转灰度颜色"""
        return 255 - r, 255 - g, 255 - b
    
    def _adjust_brightness(self, r, g, b):
        """调整彩色亮度（反转亮度）"""
        h, l, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
        new_l = 1.0 - l
        new_r, new_g, new_b = colorsys.hls_to_rgb(h, new_l, s)
        return int(new_r * 255), int(new_g * 255), int(new_b * 255)
    
    def _invert_color(self, hex_color):
        """
        根据当前主题反转颜色
        
        Args:
            hex_color: 十六进制颜色字符串，如 '#RRGGBB'
            
        Returns:
            str: 反转后的十六进制颜色字符串
        """
        if not hex_color or not hex_color.startswith('#') or len(hex_color) != 7:
            return hex_color
        
        try:
            r = int(hex_color[1:3], 16)
            g = int(hex_color[3:5], 16)
            b = int(hex_color[5:7], 16)
            
            if self._is_grayscale(r, g, b):
                r, g, b = self._invert_grayscale(r, g, b)
            else:
                r, g, b = self._adjust_brightness(r, g, b)
            
            return f'#{r:02x}{g:02x}{b:02x}'
        except (ValueError, IndexError):
            return hex_color
    
    def _process_html_colors(self, html, is_dark):
        """
        处理HTML中的颜色值（仅深色模式下反转颜色）
        
        Args:
            html: HTML字符串
            is_dark: 是否为深色模式
            
        Returns:
            str: 处理后的HTML字符串
        """
        if not is_dark:
            return html
        
        color_pattern = re.compile(r'color:\s*(#[0-9A-Fa-f]{6})')
        
        def replace_color(match):
            return f'color: {self._invert_color(match.group(1))}'
        
        html = color_pattern.sub(replace_color, html)
        
        background_pattern = re.compile(r'background(-color)?:\s*(#[0-9A-Fa-f]{6})')
        
        def replace_bg(match):
            return f'background-color: {self._invert_color(match.group(2))}'
        
        html = background_pattern.sub(replace_bg, html)
        
        border_color_pattern = re.compile(r'border(-color)?:\s*(#[0-9A-Fa-f]{6})')
        
        def replace_border(match):
            return f'border-color: {self._invert_color(match.group(2))}'
        
        html = border_color_pattern.sub(replace_border, html)
        
        return html
    
    def _on_file_loaded(self, content, success):
        """文件加载完成回调"""
        self._stop_loading()
        
        if not success:
            return
        
        self.file_content = content
        
        file_type = self._detect_file_type(self.current_file_path)
        
        if file_type == 'markdown' and MARKDOWN_AVAILABLE:
            self._render_markdown(content)
        else:
            self._render_plain_text(content, file_type)
        
        self._apply_search_highlight()
    
    def _refresh_display(self):
        """刷新显示"""
        if not self.file_content:
            return
        
        if self.is_markdown:
            self._render_markdown(self.file_content)
        else:
            self._render_plain_text(self.file_content, self._detect_file_type(self.current_file_path))
    
    def _preprocess_markdown_lists(self, content):
        """预处理 Markdown 列表缩进，统一为 4 空格缩进

        参数：
            content (str): 原始 Markdown 内容

        返回：
            str: 处理后的 Markdown 内容
        """
        lines = content.split('\n')
        processed_lines = []

        for line in lines:
            # 检测行首的缩进（空格或制表符）
            stripped = line.lstrip()
            if not stripped:
                processed_lines.append(line)
                continue

            # 计算原始缩进长度
            indent_len = len(line) - len(stripped)
            original_indent = line[:indent_len]

            # 将制表符转换为空格（1个制表符 = 4个空格）
            spaces_only = original_indent.replace('\t', '    ')

            # 如果缩进不是4的倍数，调整为4的倍数
            # 这样可以处理 2空格、3空格等各种缩进方式
            current_spaces = len(spaces_only)
            if current_spaces > 0 and current_spaces % 4 != 0:
                # 计算应该有多少个4空格缩进
                # 假设原始意图是每级缩进4空格
                level = max(1, round(current_spaces / 4))
                new_indent = '    ' * level
                processed_lines.append(new_indent + stripped)
            else:
                processed_lines.append(spaces_only + stripped)

        return '\n'.join(processed_lines)

    def _render_markdown(self, content):
        """渲染Markdown"""
        try:
            # 预处理列表缩进
            content = self._preprocess_markdown_lists(content)

            md = markdown.Markdown(
                extensions=['fenced_code', 'codehilite', 'tables', 'sane_lists'],
                extension_configs={
                    'codehilite': {'noclasses': True, 'guess_lang': False}
                }
            )
            html = md.convert(content)
            
            current_font = self.text_edit.font()
            font_family = current_font.family()
            # 使用缩放后的字体大小（像素值），用于 CSS 样式
            font_size = int(self.default_font_size * self.dpi_scale)
            
            is_dark = False
            app = QApplication.instance()
            if hasattr(app, 'settings_manager'):
                theme = app.settings_manager.get_setting("general.theme", "dark")
                is_dark = theme == "dark"
                secondary_color = app.settings_manager.get_setting("appearance.colors.secondary_color", "#333333")
                base_color = app.settings_manager.get_setting("appearance.colors.base_color", "#FFFFFF")
                normal_color = app.settings_manager.get_setting("appearance.colors.normal_color", "#666666")
                auxiliary_color = app.settings_manager.get_setting("appearance.colors.auxiliary_color", "#999999")
            else:
                secondary_color = "#333333"
                base_color = "#FFFFFF"
                normal_color = "#666666"
                auxiliary_color = "#999999"
            
            # 代码块背景使用 auxiliary_color
            code_bg = auxiliary_color
            pre_bg = code_bg
            # 表格边框使用 normal_color，表头背景使用 auxiliary_color
            border_color = normal_color
            th_bg = auxiliary_color
            
            header_style = f"""
                <style>
                    body {{ font-family: {font_family}, sans-serif; font-size: {font_size}px; line-height: 1.6; color: {secondary_color}; margin: 0; padding: 0; }}
                    div {{ color: {secondary_color}; }}
                    p {{ color: {secondary_color}; margin: 0.5em 0; }}
                    li {{ color: {secondary_color}; margin: 0.3em 0; }}
                    pre {{ background-color: {pre_bg}; padding: 10px; border-radius: 4px; overflow-x: auto; margin: 0.5em 0; }}
                    code {{ background-color: {code_bg}; padding: 2px 5px; border-radius: 3px; font-family: Consolas, monospace; color: {secondary_color}; }}
                    pre code {{ background-color: transparent; padding: 0; color: {secondary_color} !important; }}
                    pre code * {{ color: {secondary_color} !important; }}
                    h1, h2, h3, h4, h5, h6 {{ color: {secondary_color}; margin-top: 1.5em; margin-bottom: 0.5em; }}
                    h1 {{ font-size: 2em; border-bottom: 1px solid {border_color}; }}
                    h2 {{ font-size: 1.5em; border-bottom: 1px solid {border_color}; }}
                    table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
                    th {{ background-color: {th_bg}; color: {secondary_color}; }}
                    td {{ color: {secondary_color}; }}
                    th, td {{ border: 1px solid {border_color}; padding: 8px; text-align: left; }}
                    blockquote {{ border-left: 4px solid {border_color}; margin: 0.5em 0; padding-left: 16px; color: {secondary_color}; }}
                    img {{ max-width: 100%; }}
                    strong, b {{ color: {secondary_color}; }}
                    em, i {{ color: {secondary_color}; }}
                    a {{ color: {secondary_color}; text-decoration: underline; }}
                    /* 列表样式优化 */
                    ul, ol {{ margin: 0.5em 0; padding-left: 2em; }}
                    ul ul, ul ol, ol ul, ol ol {{ margin: 0.2em 0; }}
                    ul li {{ list-style-type: disc; }}
                    ul ul li {{ list-style-type: circle; }}
                    ul ul ul li {{ list-style-type: square; }}
                    ol li {{ list-style-type: decimal; }}
                    ol ol li {{ list-style-type: lower-alpha; }}
                    ol ol ol li {{ list-style-type: lower-roman; }}
                    li > p {{ margin: 0.2em 0; }}
                    li > ul, li > ol {{ margin: 0.2em 0; }}
                </style>
            """
            
            # 在应用样式前，处理 Markdown 内容中的颜色（仅深色模式）
            if is_dark:
                html = self._process_html_colors(html, True)
            
            html = f"<html><head>{header_style}</head><body>{html}</body></html>"
            
            self.text_edit.setHtml(html)
            self.is_markdown = True
            
        except Exception as e:
            self.text_edit.setPlainText(content)
            self.is_markdown = False
    
    def _render_plain_text(self, content, file_type):
        """渲染纯文本/代码"""
        self.text_edit.setPlainText(content)
        self.is_markdown = False
        
        if file_type == 'code':
            _, ext = os.path.splitext(self.current_file_path)
            ext = ext.lower()
            code_type = CODE_EXTENSIONS.get(ext, 'text')
            self._create_highlighter(code_type)
            # 代码高亮模式下使用 FiraCode-VF 字体
            self._apply_code_font()
    
    def _on_load_error(self, error_msg):
        """加载错误回调"""
        self._stop_loading()
        self.text_edit.setPlainText(f"加载失败: {error_msg}")
    
    def _on_load_progress(self, value):
        """加载进度回调"""
        self.progress_bar.setValue(value)
    
    def _start_loading(self):
        """开始加载动画"""
        self._is_loading = True
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        
        self._progress_animation = QTimer(self)
        self._progress_animation.timeout.connect(self._animate_progress)
        self._progress_animation.start(100)
    
    def _animate_progress(self):
        """进度条动画"""
        if not self._is_loading:
            return
        
        current = self.progress_bar.value()
        if current >= 90:
            current = 0
        else:
            current += 10
        self.progress_bar.setValue(current)
    
    def _stop_loading(self):
        """停止加载动画"""
        self._is_loading = False
        if hasattr(self, '_progress_animation'):
            self._progress_animation.stop()
        self.progress_bar.setVisible(False)
        self.progress_bar.setValue(100)
    
    def _apply_code_font(self):
        """应用代码高亮专用字体（FiraCode-VF）"""
        if not hasattr(self, 'text_edit') or self.text_edit is None:
            return
        
        app = QApplication.instance()
        firacode_family = getattr(app, 'firacode_font_family', None)
        
        if firacode_family:
            code_font = QFont(firacode_family)
            current_size = self.font_size_slider.value()
            code_font.setPointSize(current_size)
            self.text_edit.setFont(code_font)
    
    def _restore_default_font(self):
        """恢复默认字体"""
        if not hasattr(self, 'text_edit') or self.text_edit is None:
            return
        default_font = QFont()
        current_size = self.font_size_slider.value()
        default_font.setPointSize(current_size)
        self.text_edit.setFont(default_font)
        self._refresh_display()
    
    def _change_font(self, font_name):
        """更改字体"""
        if not hasattr(self, 'text_edit') or self.text_edit is None:
            return
        font = self.text_edit.font()
        font.setFamily(font_name)
        current_size = self.font_size_slider.value()
        font.setPointSize(current_size)
        self.text_edit.setFont(font)
        
        self._refresh_display()
    
    def _on_font_selected(self, item):
        """字体选择回调"""
        if isinstance(item, dict):
            font_name = item.get('data', item.get('text', ''))
        else:
            font_name = item
        
        if font_name == "默认字体":
            self._restore_default_font()
        else:
            self._change_font(font_name)
    
    def _on_font_size_changed(self, value):
        """字体大小滑块变化回调"""
        self._change_font_size(str(value))
    
    def _on_encoding_selected(self, item):
        """编码选择回调"""
        if isinstance(item, dict):
            encoding = item.get('data', item.get('text', ''))
        else:
            encoding = item
        self._change_encoding(encoding)
    
    def _change_font_size(self, size_text):
        """更改字体大小"""
        if not hasattr(self, 'text_edit') or self.text_edit is None:
            return
        try:
            size = int(size_text)
            font = self.text_edit.font()
            font.setPointSize(size)
            self.text_edit.setFont(font)
            self._refresh_display()
        except ValueError:
            pass
    
    def _change_encoding(self, encoding):
        """更改编码"""
        if self.current_file_path and os.path.exists(self.current_file_path):
            self.set_file(self.current_file_path)
    
    def _toggle_search(self):
        """切换搜索栏"""
        if self.search_bar.isVisible():
            self.search_bar.hide()
            self._clear_search()
        else:
            self.search_bar.show()
            self.search_input.setFocus()
        self._update_search_button_style()
    
    def _update_search_button_style(self):
        """
        根据搜索状态更新搜索按钮的样式
        - 当搜索栏可见或有搜索内容时，使用强调样式（primary）
        - 当搜索栏隐藏且无搜索内容时，使用普通样式（normal）
        """
        if hasattr(self, 'search_button'):
            if self.search_bar.isVisible() or self._search_term:
                self.search_button.button_type = "primary"
            else:
                self.search_button.button_type = "normal"
            self.search_button.update_style()
    
    def _on_search_text_changed(self, text):
        """搜索文本变化时清除高亮"""
        if not text:
            self._clear_search()
    
    def _perform_search(self):
        """执行搜索"""
        search_term = self.search_input.text()
        print(f"[DEBUG] _perform_search: search_term = '{search_term}'")
        if not search_term:
            self._clear_search()
            return
        
        self._search_term = search_term
        self._search_results = []
        self._current_search_index = -1
        
        content = self.text_edit.toPlainText()
        
        pos = content.find(search_term)
        print(f"[DEBUG] _perform_search: found at pos = {pos}")
        
        while pos >= 0:
            self._search_results.append(pos)
            pos = content.find(search_term, pos + 1)
        
        print(f"[DEBUG] _perform_search: results count = {len(self._search_results)}")
        
        if self._search_results:
            self._current_search_index = 0
            self._highlight_search_results()
            self._update_search_info()
            self._go_to_match(0)
        else:
            self._update_search_info()
    
    def _go_to_previous_match(self):
        """跳转到上一个匹配项"""
        print(f"[DEBUG] _go_to_previous_match: results = {len(self._search_results)}, current = {self._current_search_index}")
        if not self._search_results:
            print(f"[DEBUG] _go_to_previous_match: early return, no results")
            return
        
        self._current_search_index = (self._current_search_index - 1) % len(self._search_results)
        print(f"[DEBUG] _go_to_previous_match: new index = {self._current_search_index}")
        self._go_to_match(self._current_search_index)
        self._update_search_info()
    
    def _go_to_next_match(self):
        """跳转到下一个匹配项"""
        print(f"[DEBUG] _go_to_next_match: results = {len(self._search_results)}, current = {self._current_search_index}")
        if not self._search_results:
            print(f"[DEBUG] _go_to_next_match: early return, no results")
            return
        
        self._current_search_index = (self._current_search_index + 1) % len(self._search_results)
        print(f"[DEBUG] _go_to_next_match: new index = {self._current_search_index}")
        self._go_to_match(self._current_search_index)
        self._update_search_info()
    
    def _go_to_match(self, index):
        """跳转到指定索引的匹配项"""
        print(f"[DEBUG] _go_to_match: index = {index}, results count = {len(self._search_results)}")
        if not self._search_results or index < 0 or index >= len(self._search_results):
            print(f"[DEBUG] _go_to_match: early return due to invalid index")
            return
        
        pos = self._search_results[index]
        print(f"[DEBUG] _go_to_match: pos = {pos}, term = '{self._search_term}'")
        
        self._highlight_search_results()
        
        cursor = QTextCursor(self.text_edit.document())
        cursor.setPosition(pos + len(self._search_term))
        self.text_edit.setTextCursor(cursor)
        self.text_edit.ensureCursorVisible()
    
    def _highlight_search_results(self):
        """高亮搜索结果"""
        print(f"[DEBUG] _highlight_search_results: called with {len(self._search_results)} results")
        
        app = QApplication.instance()
        accent_color_hex = "#007AFF"
        secondary_color_hex = "#666666"
        if hasattr(app, 'settings_manager'):
            accent_color_hex = app.settings_manager.get_setting("appearance.colors.accent_color", "#007AFF")
            secondary_color_hex = app.settings_manager.get_setting("appearance.colors.secondary_color", "#666666")
        
        accent_color = QColor(accent_color_hex)
        accent_color.setAlpha(127)
        
        secondary_color = QColor(secondary_color_hex)
        secondary_color.setAlpha(51)
        
        extra_selections = []
        
        highlight_format = QTextCharFormat()
        highlight_format.setBackground(secondary_color)
        
        current_format = QTextCharFormat()
        current_format.setBackground(accent_color)
        
        for i, pos in enumerate(self._search_results):
            extra_selection = QTextEdit.ExtraSelection()
            
            if i == self._current_search_index:
                extra_selection.format = current_format
            else:
                extra_selection.format = highlight_format
            
            extra_selection.cursor = QTextCursor(self.text_edit.document())
            extra_selection.cursor.setPosition(pos)
            extra_selection.cursor.setPosition(pos + len(self._search_term), QTextCursor.KeepAnchor)
            
            extra_selections.append(extra_selection)
        
        print(f"[DEBUG] _highlight_search_results: setting {len(extra_selections)} extra selections")
        self.text_edit.setExtraSelections(extra_selections)
        self.text_edit.viewport().update()
    
    def _apply_search_highlight(self):
        """应用搜索高亮"""
        if self._search_term and self._search_results:
            self._perform_search()
        else:
            self.text_edit.setExtraSelections([])
    
    def _update_search_info(self):
        """更新搜索信息标签"""
        count = len(self._search_results)
        if count > 0:
            current = self._current_search_index + 1
            self.search_info_label.setText(f"{current}/{count}")
        else:
            self.search_info_label.setText("0/0")
    
    def _clear_search(self):
        """清除搜索"""
        self._search_term = ""
        self._search_results = []
        self._current_search_index = -1
        self.search_info_label.setText("0/0")
        self.text_edit.setExtraSelections([])
        self._update_search_button_style()
    
    def cleanup(self):
        """清理资源"""
        if self._thread and self._thread.isRunning():
            self._thread.abort()
            self._thread.wait()
        self._clear_search()


class TextPreviewer(QWidget):
    """
    完整文本预览器组件
    包含窗口控件和TextPreviewWidget
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
        
        self.preview_widget = TextPreviewWidget(self)
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
        设置要预览的文件
        
        Args:
            file_path (str): 文件路径
        """
        self.preview_widget.set_file(file_path)
    
    def cleanup(self):
        """清理资源"""
        self.preview_widget.cleanup()
