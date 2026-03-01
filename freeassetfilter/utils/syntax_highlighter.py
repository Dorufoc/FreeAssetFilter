#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

语法高亮模块 - 基于 Syntect 实现

功能说明：
- 使用 pysyntect 库实现高性能语法高亮
- 支持 500+ 种编程语言的语法定义
- 兼容 VS Code / Sublime Text 的 TextMate 语法文件
- 支持 TextMate 主题定义
- 纯 Python 实现，无需 Node.js 依赖

工作原理：
1. 加载语法定义：从内置或自定义路径加载 .sublime-syntax 文件
2. 加载主题：从内置或自定义路径加载 .tmTheme 文件
3. 逐行扫描：使用 Oniguruma 正则引擎对代码进行词法分析
4. 生成 Token：输出带样式信息的 Token 列表
5. 合成样式：根据主题将 Token 映射为颜色值

TextMate 语法文件支持：
- 支持 .sublime-syntax (Sublime Text 3+)
- 支持 .tmLanguage (TextMate / VS Code)
- 支持 .plist 格式的语法定义
- 支持从 VS Code 扩展加载语法
"""

import os
import sys
import json
import plistlib
from dataclasses import dataclass
from enum import Enum, auto
from typing import List, Dict, Optional, Tuple, Union, Callable, Any, TYPE_CHECKING
from pathlib import Path

# PySide6 导入
from PySide6.QtGui import QColor, QTextCharFormat, QFont
from PySide6.QtCore import Qt

# 尝试导入 pysyntect
try:
    import syntect
    from syntect import (
        highlight,
        load_default_syntax,
        load_syntax_folder,
        load_theme_folder,
        escape_to_console,
        Style
    )
    SYNTECT_AVAILABLE = True
except ImportError:
    SYNTECT_AVAILABLE = False
    Style = None  # 类型占位

# 尝试导入 Pygments 作为备选方案
try:
    from pygments import lex
    from pygments.lexers import get_lexer_by_name, get_lexer_for_filename, TextLexer, guess_lexer
    from pygments.token import Token
    from pygments.styles import get_style_by_name, get_all_styles
    PYGMENTS_AVAILABLE = True
except ImportError:
    PYGMENTS_AVAILABLE = False

# 导入日志模块
from freeassetfilter.utils.app_logger import info, debug, warning, error


class TokenType(Enum):
    """Token 类型枚举"""
    KEYWORD = auto()           # 关键字
    STRING = auto()            # 字符串
    NUMBER = auto()            # 数字
    COMMENT = auto()           # 注释
    FUNCTION = auto()          # 函数名
    CLASS_TYPE = auto()        # 类名/类型
    OPERATOR = auto()          # 运算符
    PUNCTUATION = auto()       # 标点符号
    VARIABLE = auto()          # 变量
    CONSTANT = auto()          # 常量
    TAG = auto()               # XML/HTML 标签
    ATTRIBUTE = auto()         # 属性名
    VALUE = auto()             # 属性值
    PREPROCESSOR = auto()      # 预处理指令
    DEFAULT = auto()           # 默认文本
    WHITESPACE = auto()        # 空白字符


@dataclass
class Token:
    """语法 Token 数据类
    
    属性：
        text: Token 文本内容
        token_type: Token 类型
        start_pos: 起始位置（字符索引）
        end_pos: 结束位置（字符索引）
        scopes: 作用域栈（用于调试）
    """
    text: str
    token_type: TokenType
    start_pos: int
    end_pos: int
    scopes: List[str] = None
    
    def __post_init__(self):
        if self.scopes is None:
            self.scopes = []


@dataclass
class ColorScheme:
    """颜色方案数据类
    
    属性：
        name: 方案名称
        background: 背景色 (hex)
        foreground: 前景色 (hex)
        colors: Token 类型到颜色的映射
    """
    name: str
    background: str
    foreground: str
    colors: Dict[TokenType, str]


class ColorSchemes:
    """预定义颜色方案"""
    
    @staticmethod
    def github_dark() -> ColorScheme:
        """GitHub Dark 主题"""
        return ColorScheme(
            name="github_dark",
            background="#0d1117",
            foreground="#c9d1d9",
            colors={
                TokenType.KEYWORD: "#ff7b72",
                TokenType.STRING: "#a5d6ff",
                TokenType.NUMBER: "#79c0ff",
                TokenType.COMMENT: "#8b949e",
                TokenType.FUNCTION: "#d2a8ff",
                TokenType.CLASS_TYPE: "#ffa657",
                TokenType.OPERATOR: "#ff7b72",
                TokenType.PUNCTUATION: "#c9d1d9",
                TokenType.VARIABLE: "#c9d1d9",
                TokenType.CONSTANT: "#79c0ff",
                TokenType.TAG: "#7ee787",
                TokenType.ATTRIBUTE: "#79c0ff",
                TokenType.VALUE: "#a5d6ff",
                TokenType.PREPROCESSOR: "#ff7b72",
                TokenType.DEFAULT: "#c9d1d9",
                TokenType.WHITESPACE: "#c9d1d9",
            }
        )
    
    @staticmethod
    def github_light() -> ColorScheme:
        """GitHub Light 主题"""
        return ColorScheme(
            name="github_light",
            background="#ffffff",
            foreground="#24292e",
            colors={
                TokenType.KEYWORD: "#d73a49",
                TokenType.STRING: "#032f62",
                TokenType.NUMBER: "#005cc5",
                TokenType.COMMENT: "#6a737d",
                TokenType.FUNCTION: "#6f42c1",
                TokenType.CLASS_TYPE: "#e36209",
                TokenType.OPERATOR: "#d73a49",
                TokenType.PUNCTUATION: "#24292e",
                TokenType.VARIABLE: "#24292e",
                TokenType.CONSTANT: "#005cc5",
                TokenType.TAG: "#22863a",
                TokenType.ATTRIBUTE: "#005cc5",
                TokenType.VALUE: "#032f62",
                TokenType.PREPROCESSOR: "#d73a49",
                TokenType.DEFAULT: "#24292e",
                TokenType.WHITESPACE: "#24292e",
            }
        )
    
    @staticmethod
    def vscode_dark() -> ColorScheme:
        """VS Code Dark+ 主题"""
        return ColorScheme(
            name="vscode_dark",
            background="#1e1e1e",
            foreground="#d4d4d4",
            colors={
                TokenType.KEYWORD: "#569cd6",
                TokenType.STRING: "#ce9178",
                TokenType.NUMBER: "#b5cea8",
                TokenType.COMMENT: "#6a9955",
                TokenType.FUNCTION: "#dcdcaa",
                TokenType.CLASS_TYPE: "#4ec9b0",
                TokenType.OPERATOR: "#d4d4d4",
                TokenType.PUNCTUATION: "#d4d4d4",
                TokenType.VARIABLE: "#9cdcfe",
                TokenType.CONSTANT: "#4fc1ff",
                TokenType.TAG: "#569cd6",
                TokenType.ATTRIBUTE: "#9cdcfe",
                TokenType.VALUE: "#ce9178",
                TokenType.PREPROCESSOR: "#c586c0",
                TokenType.DEFAULT: "#d4d4d4",
                TokenType.WHITESPACE: "#d4d4d4",
            }
        )
    
    @staticmethod
    def vscode_light() -> ColorScheme:
        """VS Code Light+ 主题"""
        return ColorScheme(
            name="vscode_light",
            background="#ffffff",
            foreground="#000000",
            colors={
                TokenType.KEYWORD: "#0000ff",
                TokenType.STRING: "#a31515",
                TokenType.NUMBER: "#098658",
                TokenType.COMMENT: "#008000",
                TokenType.FUNCTION: "#795e26",
                TokenType.CLASS_TYPE: "#267f99",
                TokenType.OPERATOR: "#000000",
                TokenType.PUNCTUATION: "#000000",
                TokenType.VARIABLE: "#001080",
                TokenType.CONSTANT: "#0070c1",
                TokenType.TAG: "#800000",
                TokenType.ATTRIBUTE: "#ff0000",
                TokenType.VALUE: "#0000ff",
                TokenType.PREPROCESSOR: "#af00db",
                TokenType.DEFAULT: "#000000",
                TokenType.WHITESPACE: "#000000",
            }
        )

    @staticmethod
    def base16_ocean_dark() -> ColorScheme:
        """Base16 Ocean Dark 主题"""
        return ColorScheme(
            name="base16_ocean_dark",
            background="#2b303b",
            foreground="#c0c5ce",
            colors={
                TokenType.KEYWORD: "#b48ead",
                TokenType.STRING: "#a3be8c",
                TokenType.NUMBER: "#d08770",
                TokenType.COMMENT: "#65737e",
                TokenType.FUNCTION: "#8fa1b3",
                TokenType.CLASS_TYPE: "#ebcb8b",
                TokenType.OPERATOR: "#bf616a",
                TokenType.PUNCTUATION: "#c0c5ce",
                TokenType.VARIABLE: "#c0c5ce",
                TokenType.CONSTANT: "#d08770",
                TokenType.TAG: "#bf616a",
                TokenType.ATTRIBUTE: "#ebcb8b",
                TokenType.VALUE: "#a3be8c",
                TokenType.PREPROCESSOR: "#b48ead",
                TokenType.DEFAULT: "#c0c5ce",
                TokenType.WHITESPACE: "#c0c5ce",
            }
        )

    @staticmethod
    def base16_ocean_light() -> ColorScheme:
        """Base16 Ocean Light 主题"""
        return ColorScheme(
            name="base16_ocean_light",
            background="#eff1f5",
            foreground="#4f5b66",
            colors={
                TokenType.KEYWORD: "#b48ead",
                TokenType.STRING: "#a3be8c",
                TokenType.NUMBER: "#d08770",
                TokenType.COMMENT: "#a7adba",
                TokenType.FUNCTION: "#8fa1b3",
                TokenType.CLASS_TYPE: "#ebcb8b",
                TokenType.OPERATOR: "#bf616a",
                TokenType.PUNCTUATION: "#4f5b66",
                TokenType.VARIABLE: "#4f5b66",
                TokenType.CONSTANT: "#d08770",
                TokenType.TAG: "#bf616a",
                TokenType.ATTRIBUTE: "#ebcb8b",
                TokenType.VALUE: "#a3be8c",
                TokenType.PREPROCESSOR: "#b48ead",
                TokenType.DEFAULT: "#4f5b66",
                TokenType.WHITESPACE: "#4f5b66",
            }
        )


@dataclass
class TextMateGrammar:
    """TextMate 语法定义数据类
    
    用于表示从 .tmLanguage 或 .sublime-syntax 文件加载的语法定义
    
    属性：
        name: 语法名称
        scope_name: 作用域名（如 source.python）
        file_extensions: 支持的文件扩展名列表
        patterns: 匹配规则列表
        repository: 命名模式仓库
        uuid: 唯一标识符
        source_file: 源文件路径
    """
    name: str
    scope_name: str
    file_extensions: List[str]
    patterns: List[Dict[str, Any]]
    repository: Dict[str, Any]
    uuid: Optional[str] = None
    source_file: Optional[str] = None


class TextMateGrammarLoader:
    """TextMate 语法文件加载器
    
    支持加载多种格式的语法定义文件：
    - .sublime-syntax (Sublime Text 3+, YAML 格式)
    - .tmLanguage (TextMate, XML plist 格式)
    - .json (VS Code, JSON 格式)
    - .plist (属性列表格式)
    
    使用示例：
        loader = TextMateGrammarLoader()
        
        # 加载单个文件
        grammar = loader.load_file("path/to/python.tmLanguage")
        
        # 加载整个文件夹
        grammars = loader.load_folder("path/to/grammars/")
        
        # 从 VS Code 扩展加载
        grammars = loader.load_vscode_extension("path/to/extension/")
    """
    
    def __init__(self):
        self.grammars: Dict[str, TextMateGrammar] = {}
        self._scope_to_grammar: Dict[str, TextMateGrammar] = {}
    
    def load_file(self, file_path: str) -> Optional[TextMateGrammar]:
        """加载单个语法定义文件
        
        参数：
            file_path: 语法文件路径
            
        返回：
            TextMateGrammar 对象或 None
        """
        path = Path(file_path)
        if not path.exists():
            warning(f"[TextMateGrammarLoader] 文件不存在: {file_path}")
            return None

        try:
            suffix = path.suffix.lower()

            if suffix == '.sublime-syntax':
                return self._load_sublime_syntax(file_path)
            elif suffix == '.tmlanguage':
                return self._load_tm_language(file_path)
            elif suffix == '.json':
                return self._load_json(file_path)
            elif suffix == '.plist':
                return self._load_plist(file_path)
            else:
                warning(f"[TextMateGrammarLoader] 不支持的文件格式: {suffix}")
                return None

        except Exception as e:
            error(f"[TextMateGrammarLoader] 加载失败 {file_path}: {e}")
            return None
    
    def _load_sublime_syntax(self, file_path: str) -> Optional[TextMateGrammar]:
        """加载 Sublime Syntax 文件 (YAML 格式)
        
        参数：
            file_path: 文件路径
            
        返回：
            TextMateGrammar 对象
        """
        try:
            import yaml
        except ImportError:
            warning("[TextMateGrammarLoader] 需要 PyYAML 库来加载 .sublime-syntax 文件")
            return None
        
        with open(file_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        return self._parse_grammar_data(data, file_path)
    
    def _load_tm_language(self, file_path: str) -> Optional[TextMateGrammar]:
        """加载 TextMate Language 文件 (XML plist 格式)
        
        参数：
            file_path: 文件路径
            
        返回：
            TextMateGrammar 对象
        """
        with open(file_path, 'rb') as f:
            data = plistlib.load(f)
        
        return self._parse_grammar_data(data, file_path)
    
    def _load_json(self, file_path: str) -> Optional[TextMateGrammar]:
        """加载 JSON 格式的语法定义
        
        参数：
            file_path: 文件路径
            
        返回：
            TextMateGrammar 对象
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        return self._parse_grammar_data(data, file_path)
    
    def _load_plist(self, file_path: str) -> Optional[TextMateGrammar]:
        """加载 plist 格式的语法定义
        
        参数：
            file_path: 文件路径
            
        返回：
            TextMateGrammar 对象
        """
        with open(file_path, 'rb') as f:
            data = plistlib.load(f)
        
        return self._parse_grammar_data(data, file_path)
    
    def _parse_grammar_data(self, data: Dict[str, Any], source_file: str) -> TextMateGrammar:
        """解析语法定义数据
        
        参数：
            data: 原始数据字典
            source_file: 源文件路径
            
        返回：
            TextMateGrammar 对象
        """
        # 处理不同格式的字段名差异
        name = data.get('name', '')
        scope_name = data.get('scopeName', data.get('scope_name', ''))
        file_extensions = data.get('fileTypes', data.get('file_extensions', []))
        patterns = data.get('patterns', [])
        repository = data.get('repository', {})
        uuid = data.get('uuid')
        
        grammar = TextMateGrammar(
            name=name,
            scope_name=scope_name,
            file_extensions=file_extensions if isinstance(file_extensions, list) else [],
            patterns=patterns if isinstance(patterns, list) else [],
            repository=repository if isinstance(repository, dict) else {},
            uuid=uuid,
            source_file=source_file
        )
        
        # 注册到映射表
        if scope_name:
            self._scope_to_grammar[scope_name] = grammar
        if name:
            self.grammars[name.lower()] = grammar
        
        return grammar
    
    def load_folder(self, folder_path: str) -> Dict[str, TextMateGrammar]:
        """加载文件夹中的所有语法定义
        
        参数：
            folder_path: 文件夹路径
            
        返回：
            语法名称到 TextMateGrammar 的映射
        """
        folder = Path(folder_path)
        if not folder.exists() or not folder.is_dir():
            warning(f"[TextMateGrammarLoader] 文件夹不存在: {folder_path}")
            return {}

        grammars = {}

        # 支持的扩展名
        extensions = ['.sublime-syntax', '.tmlanguage', '.json', '.plist']

        for ext in extensions:
            for file_path in folder.glob(f'*{ext}'):
                grammar = self.load_file(str(file_path))
                if grammar and grammar.name:
                    grammars[grammar.name.lower()] = grammar

        info(f"[TextMateGrammarLoader] 从 {folder_path} 加载了 {len(grammars)} 个语法定义")
        return grammars
    
    def load_vscode_extension(self, extension_path: str) -> Dict[str, TextMateGrammar]:
        """从 VS Code 扩展加载语法定义
        
        VS Code 扩展通常位于：
        - Windows: %USERPROFILE%\.vscode\extensions\
        - macOS: ~/.vscode/extensions/
        - Linux: ~/.vscode/extensions/
        
        参数：
            extension_path: 扩展文件夹路径
            
        返回：
            语法名称到 TextMateGrammar 的映射
        """
        ext_path = Path(extension_path)
        if not ext_path.exists():
            return {}
        
        grammars = {}
        
        # 查找 syntaxes 或 grammars 文件夹
        for subfolder in ['syntaxes', 'grammars']:
            grammar_folder = ext_path / subfolder
            if grammar_folder.exists():
                folder_grammars = self.load_folder(str(grammar_folder))
                grammars.update(folder_grammars)
        
        return grammars
    
    def get_grammar_by_scope(self, scope_name: str) -> Optional[TextMateGrammar]:
        """通过作用域名获取语法定义
        
        参数：
            scope_name: 作用域名（如 source.python）
            
        返回：
            TextMateGrammar 对象或 None
        """
        return self._scope_to_grammar.get(scope_name)
    
    def get_grammar_by_extension(self, extension: str) -> Optional[TextMateGrammar]:
        """通过文件扩展名获取语法定义
        
        参数：
            extension: 文件扩展名（如 .py）
            
        返回：
            TextMateGrammar 对象或 None
        """
        ext = extension.lower()
        if not ext.startswith('.'):
            ext = '.' + ext
        
        for grammar in self.grammars.values():
            if ext in [e.lower() for e in grammar.file_extensions]:
                return grammar
        
        return None


# 文件扩展名到语言的映射
EXTENSION_TO_LANGUAGE = {
    # Python
    '.py': 'python', '.pyw': 'python', '.pyi': 'python',
    # C/C++
    '.c': 'c', '.cpp': 'cpp', '.cxx': 'cpp', '.cc': 'cpp',
    '.h': 'c', '.hpp': 'cpp', '.hxx': 'cpp',
    # Java
    '.java': 'java',
    # JavaScript/TypeScript
    '.js': 'javascript', '.jsx': 'javascript', '.mjs': 'javascript',
    '.ts': 'typescript', '.tsx': 'typescript',
    # C#
    '.cs': 'csharp',
    # Go
    '.go': 'go',
    # Rust
    '.rs': 'rust',
    # SQL
    '.sql': 'sql',
    # PHP
    '.php': 'php', '.phtml': 'php',
    # R
    '.r': 'r', '.R': 'r',
    # Lua
    '.lua': 'lua',
    # VB/VBA
    '.vb': 'vb', '.vbs': 'vb', '.vba': 'vb',
    # HTML
    '.html': 'html', '.htm': 'html',
    # CSS
    '.css': 'css', '.scss': 'scss', '.sass': 'sass', '.less': 'less',
    # JSON
    '.json': 'json',
    # XML
    '.xml': 'xml', '.xhtml': 'xml', '.svg': 'xml', '.xsl': 'xml', '.xslt': 'xml',
    # 其他
    '.sh': 'bash', '.bat': 'batch', '.ps1': 'powershell',
    '.yml': 'yaml', '.yaml': 'yaml', '.ini': 'ini', '.cfg': 'ini',
    '.toml': 'toml', '.md': 'markdown', '.rst': 'rst',
    '.rb': 'ruby', '.swift': 'swift', '.kt': 'kotlin',
    '.m': 'matlab', '.pl': 'perl', '.pm': 'perl',
    '.vue': 'vue', '.svelte': 'svelte',
}


@dataclass
class TextMateTheme:
    """TextMate 主题数据类
    
    用于表示从 .tmTheme 文件加载的颜色主题
    
    属性：
        name: 主题名称
        author: 作者
        settings: 颜色设置列表
        uuid: 唯一标识符
        source_file: 源文件路径
    """
    name: str
    author: str
    settings: List[Dict[str, Any]]
    uuid: Optional[str] = None
    source_file: Optional[str] = None


class TextMateThemeLoader:
    """TextMate 主题文件加载器
    
    支持加载多种格式的主题文件：
    - .tmTheme (TextMate / VS Code, XML plist 格式)
    - .json (VS Code, JSON 格式)
    - .plist (属性列表格式)
    
    使用示例：
        loader = TextMateThemeLoader()
        
        # 加载单个主题
        theme = loader.load_file("path/to/theme.tmTheme")
        
        # 加载整个文件夹
        themes = loader.load_folder("path/to/themes/")
        
        # 转换为 ColorScheme
        color_scheme = loader.to_color_scheme(theme, "my_theme")
    """
    
    def __init__(self):
        self.themes: Dict[str, TextMateTheme] = {}
    
    def load_file(self, file_path: str) -> Optional[TextMateTheme]:
        """加载单个主题文件
        
        参数：
            file_path: 主题文件路径
            
        返回：
            TextMateTheme 对象或 None
        """
        path = Path(file_path)
        if not path.exists():
            warning(f"[TextMateThemeLoader] 文件不存在: {file_path}")
            return None

        try:
            suffix = path.suffix.lower()

            if suffix == '.tmtheme':
                return self._load_tm_theme(file_path)
            elif suffix == '.json':
                return self._load_json(file_path)
            elif suffix == '.plist':
                return self._load_plist(file_path)
            else:
                warning(f"[TextMateThemeLoader] 不支持的文件格式: {suffix}")
                return None

        except Exception as e:
            error(f"[TextMateThemeLoader] 加载失败 {file_path}: {e}")
            return None
    
    def _load_tm_theme(self, file_path: str) -> Optional[TextMateTheme]:
        """加载 TextMate Theme 文件 (XML plist 格式)
        
        参数：
            file_path: 文件路径
            
        返回：
            TextMateTheme 对象
        """
        with open(file_path, 'rb') as f:
            data = plistlib.load(f)
        
        return self._parse_theme_data(data, file_path)
    
    def _load_json(self, file_path: str) -> Optional[TextMateTheme]:
        """加载 JSON 格式的主题
        
        参数：
            file_path: 文件路径
            
        返回：
            TextMateTheme 对象
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        return self._parse_theme_data(data, file_path)
    
    def _load_plist(self, file_path: str) -> Optional[TextMateTheme]:
        """加载 plist 格式的主题
        
        参数：
            file_path: 文件路径
            
        返回：
            TextMateTheme 对象
        """
        with open(file_path, 'rb') as f:
            data = plistlib.load(f)
        
        return self._parse_theme_data(data, file_path)
    
    def _parse_theme_data(self, data: Dict[str, Any], source_file: str) -> TextMateTheme:
        """解析主题数据
        
        参数：
            data: 原始数据字典
            source_file: 源文件路径
            
        返回：
            TextMateTheme 对象
        """
        name = data.get('name', '')
        author = data.get('author', '')
        settings = data.get('settings', [])
        uuid = data.get('uuid')
        
        theme = TextMateTheme(
            name=name,
            author=author,
            settings=settings if isinstance(settings, list) else [],
            uuid=uuid,
            source_file=source_file
        )
        
        # 注册到映射表
        if name:
            self.themes[name.lower()] = theme
        
        return theme
    
    def load_folder(self, folder_path: str) -> Dict[str, TextMateTheme]:
        """加载文件夹中的所有主题
        
        参数：
            folder_path: 文件夹路径
            
        返回：
            主题名称到 TextMateTheme 的映射
        """
        folder = Path(folder_path)
        if not folder.exists() or not folder.is_dir():
            warning(f"[TextMateThemeLoader] 文件夹不存在: {folder_path}")
            return {}

        themes = {}

        # 支持的扩展名
        extensions = ['.tmtheme', '.json', '.plist']

        for ext in extensions:
            for file_path in folder.glob(f'*{ext}'):
                theme = self.load_file(str(file_path))
                if theme and theme.name:
                    themes[theme.name.lower()] = theme

        info(f"[TextMateThemeLoader] 从 {folder_path} 加载了 {len(themes)} 个主题")
        return themes
    
    def to_color_scheme(self, theme: TextMateTheme, scheme_name: str) -> ColorScheme:
        """将 TextMate 主题转换为 ColorScheme
        
        参数：
            theme: TextMateTheme 对象
            scheme_name: 颜色方案名称
            
        返回：
            ColorScheme 对象
        """
        # 默认颜色
        background = "#1e1e1e"
        foreground = "#d4d4d4"
        colors = {token_type: foreground for token_type in TokenType}
        
        # 解析主题设置
        for setting in theme.settings:
            if not isinstance(setting, dict):
                continue
            
            scope = setting.get('scope', '')
            settings = setting.get('settings', {})
            
            if not scope:
                # 全局设置
                background = settings.get('background', background)
                foreground = settings.get('foreground', foreground)
                
                # 更新所有 Token 的默认颜色
                for token_type in TokenType:
                    colors[token_type] = foreground
            else:
                # 根据作用域映射到 TokenType
                foreground_color = settings.get('foreground', foreground)
                
                # 简单的作用域映射
                scope_lower = scope.lower()
                if 'keyword' in scope_lower:
                    colors[TokenType.KEYWORD] = foreground_color
                elif 'string' in scope_lower:
                    colors[TokenType.STRING] = foreground_color
                elif 'number' in scope_lower or 'constant.numeric' in scope_lower:
                    colors[TokenType.NUMBER] = foreground_color
                elif 'comment' in scope_lower:
                    colors[TokenType.COMMENT] = foreground_color
                elif 'function' in scope_lower:
                    colors[TokenType.FUNCTION] = foreground_color
                elif 'class' in scope_lower or 'type' in scope_lower:
                    colors[TokenType.CLASS_TYPE] = foreground_color
                elif 'operator' in scope_lower:
                    colors[TokenType.OPERATOR] = foreground_color
                elif 'tag' in scope_lower:
                    colors[TokenType.TAG] = foreground_color
                elif 'attribute' in scope_lower:
                    colors[TokenType.ATTRIBUTE] = foreground_color
                elif 'variable' in scope_lower:
                    colors[TokenType.VARIABLE] = foreground_color
                elif 'constant' in scope_lower:
                    colors[TokenType.CONSTANT] = foreground_color
        
        return ColorScheme(
            name=scheme_name,
            background=background,
            foreground=foreground,
            colors=colors
        )


# Pygments token 到 TokenType 的映射（延迟初始化以避免导入错误）
PYGMENTS_TOKEN_MAP = {}

def _init_pygments_token_map():
    """初始化 Pygments Token 映射"""
    global PYGMENTS_TOKEN_MAP
    if PYGMENTS_TOKEN_MAP or not PYGMENTS_AVAILABLE:
        return
    
    from pygments.token import (
        Keyword, String, Number, Comment, Name, Operator, Punctuation, Text
    )
    
    PYGMENTS_TOKEN_MAP.update({
        Keyword: TokenType.KEYWORD,
        Keyword.Constant: TokenType.KEYWORD,
        Keyword.Declaration: TokenType.KEYWORD,
        Keyword.Namespace: TokenType.KEYWORD,
        Keyword.Reserved: TokenType.KEYWORD,
        Keyword.Type: TokenType.KEYWORD,
        String: TokenType.STRING,
        String.Single: TokenType.STRING,
        String.Double: TokenType.STRING,
        String.Triple: TokenType.STRING,
        String.Backtick: TokenType.STRING,
        String.Doc: TokenType.COMMENT,
        Number: TokenType.NUMBER,
        Number.Integer: TokenType.NUMBER,
        Number.Float: TokenType.NUMBER,
        Number.Hex: TokenType.NUMBER,
        Number.Oct: TokenType.NUMBER,
        Comment: TokenType.COMMENT,
        Comment.Single: TokenType.COMMENT,
        Comment.Multiline: TokenType.COMMENT,
        Comment.Special: TokenType.COMMENT,
        Name.Function: TokenType.FUNCTION,
        Name.Function.Magic: TokenType.FUNCTION,
        Name.Class: TokenType.CLASS_TYPE,
        Name.Type: TokenType.CLASS_TYPE,
        Name.Type.Class: TokenType.CLASS_TYPE,
        Operator: TokenType.OPERATOR,
        Operator.Word: TokenType.OPERATOR,
        Punctuation: TokenType.PUNCTUATION,
        Name: TokenType.VARIABLE,
        Name.Variable: TokenType.VARIABLE,
        Name.Constant: TokenType.CONSTANT,
        Name.Attribute: TokenType.ATTRIBUTE,
        Name.Tag: TokenType.TAG,
        Name.Builtin: TokenType.KEYWORD,
        Name.Builtin.Pseudo: TokenType.KEYWORD,
        Name.Decorator: TokenType.PREPROCESSOR,
        Comment.Preproc: TokenType.PREPROCESSOR,
        Text: TokenType.DEFAULT,
        Text.Whitespace: TokenType.WHITESPACE,
    })


class SyntectHighlighter:
    """基于 Syntect 的语法高亮器
    
    使用 pysyntect 库实现高性能语法高亮，支持 500+ 种语言。
    同时支持加载自定义 TextMate 语法文件和主题。
    
    属性：
        syntax_set: 语法定义集合
        theme: 当前主题
        color_scheme: 颜色方案
        grammar_loader: TextMate 语法加载器
        theme_loader: TextMate 主题加载器
    """
    
    def __init__(self, color_scheme: Optional[ColorScheme] = None):
        """初始化语法高亮器
        
        参数：
            color_scheme: 颜色方案，默认为 GitHub Dark
        """
        self.color_scheme = color_scheme or ColorSchemes.github_dark()
        self.syntax_set = None
        self.theme = None
        self._formats_cache: Dict[str, QTextCharFormat] = {}
        
        # 初始化 TextMate 加载器
        self.grammar_loader = TextMateGrammarLoader()
        self.theme_loader = TextMateThemeLoader()
        
        if SYNTECT_AVAILABLE:
            self._init_syntect()
            self._init_default_theme()
    
    def _init_syntect(self):
        """初始化 Syntect 语法集合"""
        try:
            self.syntax_set = load_default_syntax()
        except Exception as e:
            error(f"[SyntectHighlighter] 加载默认语法失败: {e}")
            self.syntax_set = None
    
    def _init_default_theme(self):
        """初始化默认主题
        
        注意：pysyntect库的Theme类没有公开的构造函数，
        主题必须通过load_theme_folder从.tmTheme文件加载。
        这里我们不加载默认主题，而是依赖color_scheme进行颜色映射。
        """
        # pysyntect的Theme不能直接实例化，需要通过主题文件加载
        # 我们将使用color_scheme来进行颜色映射，而不是依赖syntect主题
        self.theme = None
    
    def is_available(self) -> bool:
        """检查高亮器是否可用
        
        Syntect需要主题才能工作，如果没有主题则不可用
        
        返回：
            bool: 是否可用
        """
        return SYNTECT_AVAILABLE and self.syntax_set is not None and self.theme is not None
    
    def load_syntax_from_folder(self, folder_path: str):
        """从文件夹加载语法定义
        
        参数：
            folder_path: 包含 .sublime-syntax 文件的文件夹路径
        """
        if not SYNTECT_AVAILABLE:
            return

        try:
            self.syntax_set = load_syntax_folder(folder_path)
        except Exception as e:
            error(f"[SyntectHighlighter] 加载语法失败: {e}")

    def load_theme_from_folder(self, folder_path: str) -> Dict[str, any]:
        """从文件夹加载主题

        参数：
            folder_path: 包含 .tmTheme 文件的文件夹路径

        返回：
            主题名称到主题对象的映射
        """
        if not SYNTECT_AVAILABLE:
            return {}

        try:
            themes = load_theme_folder(folder_path)
            return {name: theme for name, theme in themes.items()}
        except Exception as e:
            error(f"[SyntectHighlighter] 加载主题失败: {e}")
            return {}
    
    def load_textmate_grammar(self, file_path: str) -> Optional[TextMateGrammar]:
        """加载 TextMate 语法定义文件
        
        支持格式：
        - .sublime-syntax (Sublime Text 3+)
        - .tmLanguage (TextMate / VS Code)
        - .json (VS Code)
        - .plist (属性列表)
        
        参数：
            file_path: 语法文件路径
            
        返回：
            TextMateGrammar 对象或 None
        """
        return self.grammar_loader.load_file(file_path)
    
    def load_textmate_grammars_from_folder(self, folder_path: str) -> Dict[str, TextMateGrammar]:
        """从文件夹加载所有 TextMate 语法定义
        
        参数：
            folder_path: 包含语法文件的文件夹路径
            
        返回：
            语法名称到 TextMateGrammar 的映射
        """
        return self.grammar_loader.load_folder(folder_path)
    
    def load_vscode_extension_grammars(self, extension_path: str) -> Dict[str, TextMateGrammar]:
        """从 VS Code 扩展加载语法定义
        
        VS Code 扩展通常位于：
        - Windows: %USERPROFILE%\\.vscode\\extensions\
        - macOS: ~/.vscode/extensions/
        - Linux: ~/.vscode/extensions/
        
        参数：
            extension_path: 扩展文件夹路径
            
        返回：
            语法名称到 TextMateGrammar 的映射
        """
        return self.grammar_loader.load_vscode_extension(extension_path)
    
    def load_textmate_theme(self, file_path: str) -> Optional[TextMateTheme]:
        """加载 TextMate 主题文件
        
        支持格式：
        - .tmTheme (TextMate / VS Code)
        - .json (VS Code)
        - .plist (属性列表)
        
        参数：
            file_path: 主题文件路径
            
        返回：
            TextMateTheme 对象或 None
        """
        return self.theme_loader.load_file(file_path)
    
    def load_textmate_themes_from_folder(self, folder_path: str) -> Dict[str, TextMateTheme]:
        """从文件夹加载所有 TextMate 主题
        
        参数：
            folder_path: 包含主题文件的文件夹路径
            
        返回：
            主题名称到 TextMateTheme 的映射
        """
        return self.theme_loader.load_folder(folder_path)
    
    def apply_textmate_theme(self, theme: TextMateTheme, scheme_name: Optional[str] = None):
        """应用 TextMate 主题
        
        参数：
            theme: TextMateTheme 对象
            scheme_name: 颜色方案名称（可选）
        """
        if scheme_name is None:
            scheme_name = theme.name.lower().replace(' ', '_')

        self.color_scheme = self.theme_loader.to_color_scheme(theme, scheme_name)
        info(f"[SyntectHighlighter] 已应用主题: {theme.name}")
    
    def get_textmate_grammar_info(self, grammar_name: str) -> Optional[Dict[str, Any]]:
        """获取 TextMate 语法信息
        
        参数：
            grammar_name: 语法名称
            
        返回：
            包含语法信息的字典或 None
        """
        grammar = self.grammar_loader.grammars.get(grammar_name.lower())
        if grammar is None:
            return None
        
        return {
            'name': grammar.name,
            'scope_name': grammar.scope_name,
            'file_extensions': grammar.file_extensions,
            'uuid': grammar.uuid,
            'source_file': grammar.source_file,
            'pattern_count': len(grammar.patterns),
            'repository_count': len(grammar.repository)
        }
    
    def get_textmate_theme_info(self, theme_name: str) -> Optional[Dict[str, Any]]:
        """获取 TextMate 主题信息
        
        参数：
            theme_name: 主题名称
            
        返回：
            包含主题信息的字典或 None
        """
        theme = self.theme_loader.themes.get(theme_name.lower())
        if theme is None:
            return None
        
        return {
            'name': theme.name,
            'author': theme.author,
            'uuid': theme.uuid,
            'source_file': theme.source_file,
            'setting_count': len(theme.settings)
        }
    
    def get_supported_languages(self) -> List[str]:
        """获取支持的语言列表
        
        返回：
            支持的语言名称列表
        """
        if self.syntax_set:
            try:
                return list(self.syntax_set.languages)
            except:
                pass
        return list(set(EXTENSION_TO_LANGUAGE.values()))
    
    def highlight_line(self, line: str, language: str) -> List[Token]:
        """高亮单行代码
        
        参数：
            line: 代码行文本
            language: 语言标识符
            
        返回：
            Token 列表
        """
        if not SYNTECT_AVAILABLE or not self.syntax_set:
            return [Token(line, TokenType.DEFAULT, 0, len(line))]
        
        try:
            # 使用 Syntect 高亮（需要 theme 参数）
            if self.theme is None:
                # 如果没有主题，使用 Pygments 作为备选
                return self._fallback_highlight(line, language)
            
            color_ranges = highlight(line, language, self.syntax_set, self.theme)
            
            tokens = []
            current_pos = 0
            
            for style, text in color_ranges:
                token_type = self._map_syntect_style_to_token_type(style)
                end_pos = current_pos + len(text)
                tokens.append(Token(
                    text=text,
                    token_type=token_type,
                    start_pos=current_pos,
                    end_pos=end_pos
                ))
                current_pos = end_pos
            
            return tokens
        except Exception as e:
            error(f"[SyntectHighlighter] 高亮失败: {e}")
            return [Token(line, TokenType.DEFAULT, 0, len(line))]
    
    def _map_syntect_style_to_token_type(self, style) -> TokenType:
        """将 Syntect 样式映射为 TokenType
        
        参数：
            style: Syntect 样式对象
            
        返回：
            TokenType
        """
        # 根据前景色判断类型（简化映射）
        fg = style.foreground
        hex_color = f"#{fg.r:02x}{fg.g:02x}{fg.b:02x}"
        
        # 与颜色方案对比
        for token_type, color in self.color_scheme.colors.items():
            if color.lower() == hex_color.lower():
                return token_type
        
        return TokenType.DEFAULT
    
    def _fallback_highlight(self, line: str, language: str) -> List[Token]:
        """备选高亮方案（使用 Pygments）
        
        参数：
            line: 代码行文本
            language: 语言标识符
            
        返回：
            Token 列表
        """
        if not PYGMENTS_AVAILABLE:
            return [Token(line, TokenType.DEFAULT, 0, len(line))]
        
        try:
            from pygments import lex
            from pygments.lexers import get_lexer_by_name, TextLexer
            
            try:
                lexer = get_lexer_by_name(language)
            except:
                lexer = TextLexer()
            
            _init_pygments_token_map()
            tokens = []
            current_pos = 0
            
            for token_type, value in lex(line, lexer):
                pygments_type = TokenType.DEFAULT
                for token_parent in token_type:
                    if token_parent in PYGMENTS_TOKEN_MAP:
                        pygments_type = PYGMENTS_TOKEN_MAP[token_parent]
                        break
                
                end_pos = current_pos + len(value)
                tokens.append(Token(
                    text=value,
                    token_type=pygments_type,
                    start_pos=current_pos,
                    end_pos=end_pos
                ))
                current_pos = end_pos
            
            return tokens
        except Exception as e:
            return [Token(line, TokenType.DEFAULT, 0, len(line))]
    
    def get_qtextformat(self, token_type: TokenType) -> QTextCharFormat:
        """获取 TokenType 对应的 QTextCharFormat
        
        参数：
            token_type: Token 类型
            
        返回：
            QTextCharFormat 对象
        """
        cache_key = f"{self.color_scheme.name}_{token_type.name}"
        
        if cache_key not in self._formats_cache:
            fmt = QTextCharFormat()
            color_hex = self.color_scheme.colors.get(token_type, self.color_scheme.foreground)
            fmt.setForeground(QColor(color_hex))
            self._formats_cache[cache_key] = fmt
        
        return self._formats_cache[cache_key]
    
    def guess_language(self, filename: str) -> Optional[str]:
        """根据文件名猜测语言
        
        参数：
            filename: 文件名
            
        返回：
            语言标识符或 None
        """
        ext = Path(filename).suffix.lower()
        return EXTENSION_TO_LANGUAGE.get(ext)


class PygmentsHighlighter:
    """基于 Pygments 的语法高亮器（备选方案）
    
    当 Syntect 不可用时使用 Pygments 作为备选。
    
    属性：
        color_scheme: 颜色方案
        style: Pygments 样式
    """
    
    def __init__(self, color_scheme: Optional[ColorScheme] = None):
        """初始化语法高亮器
        
        参数：
            color_scheme: 颜色方案，默认为 GitHub Dark
        """
        self.color_scheme = color_scheme or ColorSchemes.github_dark()
        self._formats_cache: Dict[str, QTextCharFormat] = {}
        self._pygments_style = None
        
        if PYGMENTS_AVAILABLE:
            self._init_pygments_style()
    
    def _init_pygments_style(self):
        """初始化 Pygments 样式"""
        try:
            # 根据颜色方案选择 Pygments 样式
            if 'dark' in self.color_scheme.name.lower():
                self._pygments_style = get_style_by_name('monokai')
            else:
                self._pygments_style = get_style_by_name('default')
        except:
            self._pygments_style = None
    
    def highlight_line(self, line: str, language: str) -> List[Token]:
        """高亮单行代码
        
        参数：
            line: 代码行文本
            language: 语言标识符
            
        返回：
            Token 列表
        """
        if not PYGMENTS_AVAILABLE:
            return [Token(line, TokenType.DEFAULT, 0, len(line))]
        
        try:
            lexer = get_lexer_by_name(language)
        except:
            try:
                lexer = guess_lexer(line)
            except:
                lexer = TextLexer()
        
        tokens = []
        current_pos = 0
        
        for token_type, value in lex(line, lexer):
            pygments_type = self._map_pygments_token(token_type)
            end_pos = current_pos + len(value)
            tokens.append(Token(
                text=value,
                token_type=pygments_type,
                start_pos=current_pos,
                end_pos=end_pos
            ))
            current_pos = end_pos
        
        return tokens
    
    def _map_pygments_token(self, token) -> TokenType:
        """将 Pygments token 映射为 TokenType
        
        参数：
            token: Pygments token
            
        返回：
            TokenType
        """
        # 确保映射已初始化
        _init_pygments_token_map()
        
        # 直接检查token本身是否在映射中
        if token in PYGMENTS_TOKEN_MAP:
            return PYGMENTS_TOKEN_MAP[token]
        
        # 逐级查找映射（使用token.parent属性获取父级）
        current = token
        while current:
            if current in PYGMENTS_TOKEN_MAP:
                return PYGMENTS_TOKEN_MAP[current]
            # 获取父token
            current = current.parent
        
        return TokenType.DEFAULT
    
    def get_qtextformat(self, token_type: TokenType) -> QTextCharFormat:
        """获取 TokenType 对应的 QTextCharFormat
        
        参数：
            token_type: Token 类型
            
        返回：
            QTextCharFormat 对象
        """
        cache_key = f"pygments_{self.color_scheme.name}_{token_type.name}"
        
        if cache_key not in self._formats_cache:
            fmt = QTextCharFormat()
            color_hex = self.color_scheme.colors.get(token_type, self.color_scheme.foreground)
            fmt.setForeground(QColor(color_hex))
            self._formats_cache[cache_key] = fmt
        
        return self._formats_cache[cache_key]
    
    def guess_language(self, filename: str) -> Optional[str]:
        """根据文件名猜测语言
        
        参数：
            filename: 文件名
            
        返回：
            语言标识符或 None
        """
        ext = Path(filename).suffix.lower()
        return EXTENSION_TO_LANGUAGE.get(ext)
    
    def get_supported_languages(self) -> List[str]:
        """获取支持的语言列表"""
        return list(set(EXTENSION_TO_LANGUAGE.values()))


class SyntaxHighlighter:
    """统一的语法高亮接口
    
    自动选择最佳可用的高亮引擎（Syntect > Pygments > 无高亮）
    支持自动加载 TextMate 语法文件并根据文件扩展名进行高亮
    
    属性：
        engine: 实际使用的高亮引擎
        color_scheme: 颜色方案
        grammar_loader: TextMate 语法加载器
        _ext_to_language: 文件扩展名到语言的映射缓存
    """
    
    # 默认语法文件目录
    DEFAULT_SYNTAX_DIR = Path(__file__).parent / "syntax"
    
    def __init__(self, color_scheme: Optional[ColorScheme] = None, 
                 engine: Optional[str] = None,
                 syntax_dir: Optional[str] = None):
        """初始化语法高亮器
        
        参数：
            color_scheme: 颜色方案
            engine: 指定引擎 ('syntect', 'pygments', 'auto')
            syntax_dir: TextMate 语法文件目录，默认为 core/syntax
        """
        self.color_scheme = color_scheme or ColorSchemes.github_dark()
        self._engine: Union[SyntectHighlighter, PygmentsHighlighter, None] = None
        self.grammar_loader = TextMateGrammarLoader()
        self._ext_to_language: Dict[str, str] = {}
        self._language_to_scope: Dict[str, str] = {}
        
        # 选择引擎
        if engine == 'syntect' and SYNTECT_AVAILABLE:
            syntect_highlighter = SyntectHighlighter(self.color_scheme)
            # 检查Syntect是否真正可用（需要主题）
            if syntect_highlighter.is_available():
                self._engine = syntect_highlighter
            elif PYGMENTS_AVAILABLE:
                warning("[SyntaxHighlighter] Syntect需要主题文件，切换到Pygments引擎")
                self._engine = PygmentsHighlighter(self.color_scheme)
        elif engine == 'pygments' and PYGMENTS_AVAILABLE:
            self._engine = PygmentsHighlighter(self.color_scheme)
        elif engine == 'auto' or engine is None:
            # 自动选择最佳引擎
            if SYNTECT_AVAILABLE:
                syntect_highlighter = SyntectHighlighter(self.color_scheme)
                # 检查Syntect是否真正可用（需要主题）
                if syntect_highlighter.is_available():
                    self._engine = syntect_highlighter
                elif PYGMENTS_AVAILABLE:
                    warning("[SyntaxHighlighter] Syntect需要主题文件，切换到Pygments引擎")
                    self._engine = PygmentsHighlighter(self.color_scheme)
            if self._engine is None and PYGMENTS_AVAILABLE:
                self._engine = PygmentsHighlighter(self.color_scheme)

        if self._engine is None:
            warning("[SyntaxHighlighter] 警告: 没有可用的语法高亮引擎")
        
        # 加载 TextMate 语法文件
        self._load_textmate_syntaxes(syntax_dir)
    
    def _load_textmate_syntaxes(self, syntax_dir: Optional[str] = None):
        """加载 TextMate 语法文件
        
        参数：
            syntax_dir: 语法文件目录，None 则使用默认目录
        """
        if syntax_dir is None:
            syntax_dir = self.DEFAULT_SYNTAX_DIR
        
        syntax_path = Path(syntax_dir)
        if not syntax_path.exists():
            warning(f"[SyntaxHighlighter] 语法目录不存在: {syntax_dir}")
            return
        
        # 加载所有语法文件
        grammars = self.grammar_loader.load_folder(str(syntax_path))
        
        if not grammars:
            return
        
        # 语法名称到扩展名的映射（VS Code 语法文件通常没有 fileTypes）
        grammar_to_extensions = {
            'c': ['.c', '.h'],
            'c++': ['.cpp', '.cxx', '.cc', '.hpp', '.hxx', '.h'],
            'c#': ['.cs'],
            'objective-c': ['.m', '.h'],
            'objective-c++': ['.mm', '.h'],
            'cuda c++': ['.cu', '.cuh'],
            'java': ['.java'],
            'javascript': ['.js', '.jsx', '.mjs', '.es', '.es6'],
            'typescript': ['.ts', '.tsx'],
            'python': ['.py', '.pyw', '.pyi'],
            'go': ['.go'],
            'rust': ['.rs'],
            'swift': ['.swift'],
            'ruby': ['.rb', '.rbw', '.rake', '.gemspec'],
            'php': ['.php', '.phtml', '.php3', '.php4', '.php5', '.phps'],
            'perl': ['.pl', '.pm', '.pod'],
            'perl 6': ['.p6', '.pl6', '.pm6'],
            'lua': ['.lua'],
            'r': ['.r', '.R', '.rdata', '.rds', '.rda'],
            'shell script': ['.sh', '.bash', '.zsh', '.fish', '.ksh'],
            'powershell': ['.ps1', '.psm1', '.psd1'],
            'html': ['.html', '.htm', '.shtml', '.xhtml'],
            'css': ['.css'],
            'scss': ['.scss'],
            'less': ['.less'],
            'json': ['.json', '.jsonc', '.jsonl'],
            'yaml': ['.yaml', '.yml'],
            'xml': ['.xml', '.xsl', '.xslt', '.xsd', '.svg', '.rss'],
            'markdown': ['.md', '.markdown', '.mdown', '.mkd', '.mkdn'],
            'sql': ['.sql'],
            'dockerfile': ['dockerfile', '.dockerfile'],
            'makefile': ['makefile', 'Makefile', '.mk'],
            'ini': ['.ini', '.cfg', '.conf', '.config'],
            'diff': ['.diff', '.patch'],
            'clojure': ['.clj', '.cljs', '.cljc', '.edn'],
            'coffeescript': ['.coffee', '.cson'],
            'dart': ['.dart'],
            'elixir': ['.ex', '.exs'],
            'erlang': ['.erl', '.hrl'],
            'fsharp': ['.fs', '.fsx', '.fsi'],
            'groovy': ['.groovy', '.gvy', '.gy', '.gsh'],
            'julia': ['.jl'],
            'kotlin': ['.kt', '.kts'],
            'latex': ['.tex', '.latex', '.ltx'],
            'matlab': ['.m'],
            'pug': ['.pug', '.jade'],
            'handlebars': ['.hbs', '.handlebars'],
            'hlsl': ['.hlsl', '.hlsli', '.fx', '.fxh'],
            'shaderlab': ['.shader', '.cginc', '.compute'],
            'vb': ['.vb', '.vbs', '.vba', '.bas'],
            'viml': ['.vim'],
            'vue': ['.vue'],
            'xsl': ['.xsl', '.xslt'],
            'toml': ['.toml'],
            'dotenv': ['.env'],
            'batch file': ['.bat', '.cmd'],
            'coffeescript': ['.coffee'],
            'diff': ['.diff', '.patch'],
            'dockerfile': ['dockerfile'],
            'gitignore': ['.gitignore'],
            'groovy': ['.groovy'],
            'julia': ['.jl'],
            'latex': ['.tex'],
            'lua': ['.lua'],
            'makefile': ['makefile'],
            'perl': ['.pl'],
            'perl 6': ['.p6'],
            'powershell': ['.ps1'],
            'pug': ['.pug'],
            'r': ['.r'],
            'ruby': ['.rb'],
            'rust': ['.rs'],
            'scala': ['.scala'],
            'handlebars': ['.hbs', '.handlebars'],
            'bibtex': ['.bib'],
            'tex': ['.tex'],
            'xsl': ['.xsl', '.xslt'],
            'shell script': ['.sh'],
            'sql': ['.sql'],
            'swift': ['.swift'],
            'typescript': ['.ts'],
            'vb': ['.vb'],
            'xml': ['.xml'],
            'yaml': ['.yaml'],
        }
        
        # 构建扩展名到语言的映射
        for name, grammar in grammars.items():
            # 从语法名称提取语言标识符
            language = self._normalize_language_name(grammar.name)
            
            # 从语法定义中获取扩展名
            for ext in grammar.file_extensions:
                ext = ext.lower()
                if not ext.startswith('.'):
                    ext = '.' + ext
                self._ext_to_language[ext] = language
            
            # 从映射表中获取扩展名
            name_lower = grammar.name.lower()
            if name_lower in grammar_to_extensions:
                for ext in grammar_to_extensions[name_lower]:
                    ext_lower = ext.lower()
                    if not ext_lower.startswith('.'):
                        ext_lower = '.' + ext_lower
                    self._ext_to_language[ext_lower] = language
            
            # 映射作用域名
            if grammar.scope_name:
                self._language_to_scope[language] = grammar.scope_name

        info(f"[SyntaxHighlighter] 已加载 {len(grammars)} 个语法定义，"
              f"支持 {len(self._ext_to_language)} 种文件扩展名")
    
    def _normalize_language_name(self, name: str) -> str:
        """规范化语言名称
        
        将语法名称转换为统一的语言标识符
        
        参数：
            name: 原始名称
            
        返回：
            规范化的语言标识符
        """
        name_lower = name.lower()
        
        # 常见语言名称映射
        name_mapping = {
            'c++': 'cpp',
            'c#': 'csharp',
            'objective-c': 'objc',
            'objective-c++': 'objcpp',
            'javascript (with react support)': 'javascript',
            'typescriptreact': 'typescript',
            'javascriptreact': 'javascript',
            'json with comments': 'json',
            'json lines': 'json',
            'magicpython': 'python',
            'shell script': 'bash',
            'shell-unix-bash': 'bash',
            'yaml ain\'t markup language': 'yaml',
            'perl 6': 'perl6',
            'asp vb.net': 'vb',
        }
        
        # 直接映射
        if name_lower in name_mapping:
            return name_mapping[name_lower]
        
        # 移除括号内容
        import re
        name_clean = re.sub(r'\s*\([^)]*\)', '', name_lower).strip()
        
        # 替换空格和特殊字符
        name_clean = re.sub(r'[\s\-]+', '_', name_clean)
        
        return name_clean
    
    def get_language_by_extension(self, filename: str) -> Optional[str]:
        """根据文件扩展名获取语言标识符
        
        优先使用 TextMate 语法中的映射，其次使用内置映射
        
        参数：
            filename: 文件名或路径
            
        返回：
            语言标识符或 None
        """
        ext = Path(filename).suffix.lower()
        
        # 首先尝试 TextMate 语法映射
        if ext in self._ext_to_language:
            return self._ext_to_language[ext]
        
        # 然后尝试内置映射
        if ext in EXTENSION_TO_LANGUAGE:
            return EXTENSION_TO_LANGUAGE[ext]
        
        # 尝试通过 grammar_loader 查找
        grammar = self.grammar_loader.get_grammar_by_extension(ext)
        if grammar:
            return self._normalize_language_name(grammar.name)
        
        return None
    
    def highlight_file(self, text: str, filename: str) -> List[List[Token]]:
        """根据文件名自动选择语言并高亮
        
        参数：
            text: 代码文本
            filename: 文件名（用于推断语言）
            
        返回：
            每行的 Token 列表
        """
        language = self.get_language_by_extension(filename)

        if language:
            debug(f"[SyntaxHighlighter] 检测到语言: {language} ({filename})")
            return self.highlight_text(text, language)
        else:
            debug(f"[SyntaxHighlighter] 无法识别文件类型: {filename}")
            # 使用默认高亮（无语法高亮）
            lines = text.split('\n')
            return [[Token(line, TokenType.DEFAULT, 0, len(line))] for line in lines]
    
    def highlight_line(self, line: str, language: str) -> List[Token]:
        """高亮单行代码
        
        参数：
            line: 代码行文本
            language: 语言标识符
            
        返回：
            Token 列表
        """
        if self._engine:
            return self._engine.highlight_line(line, language)
        return [Token(line, TokenType.DEFAULT, 0, len(line))]
    
    def tokenize(self, line: str, language: str) -> List[Token]:
        """Tokenize单行代码（highlight_line的别名，用于兼容接口）
        
        参数：
            line: 代码行文本
            language: 语言标识符
            
        返回：
            Token 列表
        """
        return self.highlight_line(line, language)
    
    def highlight_text(self, text: str, language: str) -> List[List[Token]]:
        """高亮多行代码
        
        参数：
            text: 代码文本
            language: 语言标识符
            
        返回：
            每行的 Token 列表
        """
        lines = text.split('\n')
        return [self.highlight_line(line, language) for line in lines]
    
    def get_qtextformat(self, token_type: TokenType) -> QTextCharFormat:
        """获取 TokenType 对应的 QTextCharFormat
        
        参数：
            token_type: Token 类型
            
        返回：
            QTextCharFormat 对象
        """
        if self._engine:
            return self._engine.get_qtextformat(token_type)
        
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(self.color_scheme.foreground))
        return fmt
    
    def get_background_color(self) -> QColor:
        """获取背景颜色
        
        返回：
            QColor 对象
        """
        return QColor(self.color_scheme.background)
    
    def get_foreground_color(self) -> QColor:
        """获取前景颜色
        
        返回：
            QColor 对象
        """
        return QColor(self.color_scheme.foreground)
    
    def guess_language(self, filename: str) -> Optional[str]:
        """根据文件名猜测语言
        
        参数：
            filename: 文件名
            
        返回：
            语言标识符或 None
        """
        if self._engine:
            return self._engine.guess_language(filename)
        return None
    
    def get_supported_languages(self) -> List[str]:
        """获取支持的语言列表"""
        if self._engine:
            return self._engine.get_supported_languages()
        return []
    
    def set_color_scheme(self, color_scheme: ColorScheme):
        """设置颜色方案
        
        参数：
            color_scheme: 新的颜色方案
        """
        self.color_scheme = color_scheme
        if self._engine:
            self._engine.color_scheme = color_scheme
            self._engine._formats_cache.clear()


# 便捷函数
def create_highlighter(theme: str = 'github_dark') -> SyntaxHighlighter:
    """创建语法高亮器
    
    参数：
        theme: 主题名称 ('github_dark', 'github_light', 'vscode_dark', 'vscode_light', 'auto')
               'auto' 会根据当前主题模式自动选择
        
    返回：
        SyntaxHighlighter 实例
    """
    if theme == 'auto':
        # 自动根据暗色模式选择配色方案
        color_scheme = get_auto_theme_scheme()
    else:
        scheme_map = {
            'github_dark': ColorSchemes.github_dark(),
            'github_light': ColorSchemes.github_light(),
            'vscode_dark': ColorSchemes.vscode_dark(),
            'vscode_light': ColorSchemes.vscode_light(),
        }
        color_scheme = scheme_map.get(theme, ColorSchemes.github_dark())
    
    return SyntaxHighlighter(color_scheme)


def get_supported_languages() -> List[str]:
    """获取支持的语言列表"""
    return list(set(EXTENSION_TO_LANGUAGE.values()))


def is_dark_mode() -> bool:
    """检测是否为深色模式

    从应用设置中获取主题设置，判断是否为深色模式

    返回：
        是否为深色模式
    """
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app and hasattr(app, 'settings_manager'):
            # 使用正确的设置键名 appearance.theme
            theme = app.settings_manager.get_setting("appearance.theme", "default")
            return theme == "dark"
    except Exception:
        pass

    # 默认返回False（亮色模式），与设置管理器默认值保持一致
    return False


def get_auto_theme_scheme() -> ColorScheme:
    """根据系统主题获取自动配色方案

    暗色模式使用 github_dark
    亮色模式使用 vscode_light（前景色更深，对比度更好）

    返回：
        合适的颜色方案
    """
    if is_dark_mode():
        return ColorSchemes.github_dark()
    else:
        return ColorSchemes.vscode_light()


def guess_language_from_filename(filename: str) -> Optional[str]:
    """根据文件名猜测语言
    
    参数：
        filename: 文件名
        
    返回：
        语言标识符或 None
    """
    ext = Path(filename).suffix.lower()
    return EXTENSION_TO_LANGUAGE.get(ext)


# 向后兼容的别名
LanguagePatterns = None  # 旧版兼容


if __name__ == '__main__':
    # 简单测试
    info("=" * 60)
    info("语法高亮模块测试")
    info("=" * 60)

    info(f"\nSyntect 可用: {SYNTECT_AVAILABLE}")
    info(f"Pygments 可用: {PYGMENTS_AVAILABLE}")

    # 创建高亮器
    highlighter = create_highlighter('github_dark')

    # 测试代码
    test_code = '''def hello_world():
    """这是一个测试函数"""
    message = "Hello, World!"
    print(message)
    return 42'''

    info("\n测试代码:")
    info(test_code)
    info("\n高亮结果:")

    tokens_list = highlighter.highlight_text(test_code, 'python')
    for i, tokens in enumerate(tokens_list):
        info(f"\n第 {i+1} 行:")
        for token in tokens:
            info(f"  [{token.token_type.name}] '{token.text}'")
