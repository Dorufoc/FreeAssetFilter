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
        """构建高亮规则"""
        if self.theme == 'dark':
            self._colors = {
                'keyword': QColor('#569CD6'),
                'string': QColor('#CE9178'),
                'number': QColor('#B5CEA8'),
                'comment': QColor('#6A9955'),
                'function': QColor('#DCDCAA'),
                'class': QColor('#4EC9B0'),
                'operator': QColor('#D4D4D4'),
                'punctuation': QColor('#D4D4D4'),
                'default': QColor('#D4D4D4'),
                'tag': QColor('#569CD6'),
                'attribute': QColor('#9CDCFE'),
                'value': QColor('#CE9178'),
                'property': QColor('#9CDCFE'),
            }
        else:
            self._colors = {
                'keyword': QColor('#0000FF'),
                'string': QColor('#A31515'),
                'number': QColor('#098658'),
                'comment': QColor('#008000'),
                'function': QColor('#795E26'),
                'class': QColor('#267F99'),
                'operator': QColor('#000000'),
                'punctuation': QColor('#000000'),
                'default': QColor('#000000'),
                'tag': QColor('#0000FF'),
                'attribute': QColor('#FF0000'),
                'value': QColor('#A31515'),
                'property': QColor('#FF0000'),
            }
    
    def highlightBlock(self, textBlock):
        """高亮文本块"""
        if not isinstance(textBlock, QTextBlock):
            return
        
        document = textBlock.document()
        if not document:
            return
        
        plain_text = document.toPlainText()
        if not plain_text:
            return
            
        for pattern, format in self.highlighting_rules:
            matchIterator = pattern.globalMatch(plain_text, textBlock.position())
            while matchIterator.hasNext():
                match = matchIterator.next()
                if match.hasMatch():
                    start = match.capturedStart()
                    length = match.capturedLength()
                    if start >= textBlock.position() and start + length <= textBlock.position() + textBlock.length():
                        self.setFormat(start - textBlock.position(), length, format)
    
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
    """JSON语法高亮器"""
    
    def __init__(self, parent=None, theme='dark'):
        super().__init__(parent, theme)
        self._build_json_rules()
    
    def _build_json_rules(self):
        string_format = QTextCharFormat()
        string_format.setForeground(self._colors['string'])
        string_regex = QRegularExpression(r'"(?:[^"\\]|\\.)*"')
        self.highlighting_rules.append((string_regex, string_format))
        
        key_format = QTextCharFormat()
        key_format.setForeground(self._colors['attribute'])
        key_regex = QRegularExpression(r'"(?:[^"\\]|\\.)*(?="\s*:)')
        self.highlighting_rules.append((key_regex, key_format))
        
        number_format = QTextCharFormat()
        number_format.setForeground(self._colors['number'])
        number_regex = QRegularExpression(r'\b[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?\b')
        self.highlighting_rules.append((number_regex, number_format))
        
        bool_format = QTextCharFormat()
        bool_format.setForeground(self._colors['keyword'])
        bool_regex = QRegularExpression(r'\b(?:true|false|null)\b')
        self.highlighting_rules.append((bool_regex, bool_format))


class XmlHighlighter(SyntaxHighlighter):
    """XML/HTML语法高亮器"""
    
    def __init__(self, parent=None, theme='dark'):
        super().__init__(parent, theme)
        self._build_xml_rules()
    
    def _build_xml_rules(self):
        tag_format = QTextCharFormat()
        tag_format.setForeground(self._colors['tag'])
        tag_regex = QRegularExpression(r'</?[a-zA-Z][a-zA-Z0-9]*')
        self.highlighting_rules.append((tag_regex, tag_format))
        
        attribute_format = QTextCharFormat()
        attribute_format.setForeground(self._colors['attribute'])
        attr_regex = QRegularExpression(r'\s[a-zA-Z][a-zA-Z0-9-]*=')
        self.highlighting_rules.append((attr_regex, attribute_format))
        
        string_format = QTextCharFormat()
        string_format.setForeground(self._colors['value'])
        string_regex = QRegularExpression(r'"[^"]*"')
        self.highlighting_rules.append((string_regex, string_format))
        
        comment_format = QTextCharFormat()
        comment_format.setForeground(self._colors['comment'])
        comment_regex = QRegularExpression(r'<!--.*?-->')
        comment_regex.setPatternOptions(QRegularExpression.DotEverythingOption)
        self.highlighting_rules.append((comment_regex, comment_format))


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
        self.font_size_slider.setValue(12)
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
        
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setLineWrapMode(QTextEdit.NoWrap)
        self.text_edit.setUndoRedoEnabled(False)
        self.text_edit.setContextMenuPolicy(Qt.CustomContextMenu)
        self.text_edit.customContextMenuRequested.connect(self._show_context_menu)
        
        default_font = QFont()
        default_font.setPointSize(int(12 * self.dpi_scale))
        self.text_edit.setFont(default_font)
        
        self.text_edit.setStyleSheet("""
            QTextEdit {
                background-color: #FFFFFF;
                color: #333333;
                border: none;
                padding: 10px;
            }
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
        self.context_menu.move(pos)
        self.context_menu.show()
    
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
        text_color = app.settings_manager.get_setting("appearance.colors.text_primary", "#333333")
        secondary_color = app.settings_manager.get_setting("appearance.colors.secondary_color", "#666666")
        
        self.setStyleSheet(f"""
            background-color: {bg_color};
            color: {text_color};
        """)
        
        self.text_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: #FFFFFF;
                color: {text_color};
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
        self.text_edit.clear()
        
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
    
    def _render_markdown(self, content):
        """渲染Markdown"""
        try:
            md = markdown.Markdown(
                extensions=['fenced_code', 'codehilite', 'tables', 'nl2br'],
                extension_configs={
                    'codehilite': {'noclasses': True, 'guess_lang': False}
                }
            )
            html = md.convert(content)
            
            current_font = self.text_edit.font()
            font_family = current_font.family()
            font_size = current_font.pointSize()
            
            header_style = f"""
                <style>
                    body {{ font-family: {font_family}, sans-serif; font-size: {font_size}px; line-height: 1.6; color: #333; }}
                    pre {{ background-color: #f5f5f5; padding: 10px; border-radius: 4px; overflow-x: auto; }}
                    code {{ background-color: #f5f5f5; padding: 2px 5px; border-radius: 3px; font-family: Consolas, monospace; }}
                    pre code {{ background-color: transparent; padding: 0; }}
                    h1, h2, h3, h4, h5, h6 {{ color: #1a1a1a; margin-top: 1.5em; margin-bottom: 0.5em; }}
                    h1 {{ font-size: 2em; border-bottom: 1px solid #eee; }}
                    h2 {{ font-size: 1.5em; border-bottom: 1px solid #eee; }}
                    table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
                    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                    th {{ background-color: #f5f5f5; }}
                    blockquote {{ border-left: 4px solid #ddd; margin: 0; padding-left: 16px; color: #666; }}
                    img {{ max-width: 100%; }}
                </style>
            """
            
            full_html = f"<html><head>{header_style}</head><body>{html}</body></html>"
            
            self.text_edit.setHtml(full_html)
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
    
    def _on_search_text_changed(self, text):
        """搜索文本变化时清除高亮"""
        if not text:
            self._clear_search()
    
    def _perform_search(self):
        """执行搜索"""
        search_term = self.search_input.text()
        if not search_term:
            self._clear_search()
            return
        
        self._search_term = search_term
        self._search_results = []
        self._current_search_index = -1
        
        content = self.text_edit.toPlainText()
        
        flags = Qt.CaseSensitive if self._case_sensitive else Qt.CaseInsensitive
        pos = content.find(search_term, 0, flags)
        
        while pos >= 0:
            self._search_results.append(pos)
            pos = content.find(search_term, pos + 1, flags)
        
        if self._search_results:
            self._current_search_index = 0
            self._highlight_search_results()
            self._update_search_info()
            self._go_to_match(0)
        else:
            self._update_search_info()
    
    def _go_to_previous_match(self):
        """跳转到上一个匹配项"""
        if not self._search_results:
            return
        
        self._current_search_index = (self._current_search_index - 1) % len(self._search_results)
        self._go_to_match(self._current_search_index)
        self._update_search_info()
    
    def _go_to_next_match(self):
        """跳转到下一个匹配项"""
        if not self._search_results:
            return
        
        self._current_search_index = (self._current_search_index + 1) % len(self._search_results)
        self._go_to_match(self._current_search_index)
        self._update_search_info()
    
    def _go_to_match(self, index):
        """跳转到指定索引的匹配项"""
        if not self._search_results or index < 0 or index >= len(self._search_results):
            return
        
        pos = self._search_results[index]
        cursor = QTextCursor(self.text_edit.document())
        cursor.setPosition(pos)
        cursor.setPosition(pos + len(self._search_term), QTextCursor.KeepAnchor)
        
        self.text_edit.setTextCursor(cursor)
        self.text_edit.setCenterOnScroll(True)
    
    def _highlight_search_results(self):
        """高亮搜索结果"""
        extra_selections = []
        
        highlight_format = QTextCharFormat()
        highlight_format.setBackground(QColor(0xFF, 0xFF, 0x00, 100))
        
        current_format = QTextCharFormat()
        current_format.setBackground(QColor(0xFF, 0x00, 0x00, 150))
        
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
        
        self.text_edit.setExtraSelections(extra_selections)
    
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
        self.search_input.setText("")
        self.search_info_label.setText("0/0")
        self.text_edit.setExtraSelections([])
    
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
