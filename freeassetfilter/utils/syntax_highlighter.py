#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 现代化IDE风格语法高亮配色处理器

参考设计理念：
- GitHub Dark/Light 主题
- VS Code 现代编辑器视觉风格
- 长时间编码视觉舒适度优先

支持语言：
编程语言：Python、C、C++、Java、R、Lua、JavaScript、C#、VB、SQL、PHP、Go、Rust
标记语言：HTML、CSS、JSON、XML
"""

import re
import os
import sys
from enum import Enum, auto
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional, Pattern, Callable
from PyQt5.QtGui import QColor, QTextCharFormat, QFont
from PyQt5.QtCore import Qt

# 尝试导入SettingsManager，如果失败则使用默认配置
try:
    from freeassetfilter.core.settings_manager import SettingsManager
except ImportError:
    SettingsManager = None


class TokenType(Enum):
    """语法元素类型枚举"""
    # 通用类型
    KEYWORD = auto()           # 关键字
    VARIABLE = auto()          # 变量
    FUNCTION = auto()          # 函数
    STRING = auto()            # 字符串
    COMMENT = auto()           # 注释
    NUMBER = auto()            # 数字
    OPERATOR = auto()          # 运算符
    CLASS_TYPE = auto()        # 类/类型
    CONSTANT = auto()          # 常量
    BUILTIN = auto()           # 内置函数/对象
    DECORATOR = auto()         # 装饰器/注解
    
    # 标记语言专用
    TAG = auto()               # HTML/XML标签
    ATTRIBUTE = auto()         # 属性
    CSS_PROPERTY = auto()      # CSS属性
    CSS_VALUE = auto()         # CSS值
    SELECTOR = auto()          # CSS选择器
    
    # 特殊类型
    PLAIN = auto()             # 普通文本
    WHITESPACE = auto()        # 空白字符
    LINE_BREAK = auto()        # 换行


@dataclass
class Token:
    """语法标记数据类"""
    type: TokenType
    value: str
    start: int
    end: int


@dataclass
class ColorScheme:
    """配色方案数据类"""
    # 基础颜色
    background: str
    foreground: str
    
    # 语法元素颜色
    keyword: str
    variable: str
    function: str
    string: str
    comment: str
    number: str
    operator: str
    class_type: str
    constant: str
    builtin: str
    decorator: str
    
    # 标记语言颜色
    tag: str
    attribute: str
    css_property: str
    css_value: str
    selector: str
    
    # 行号、选中区域等UI颜色
    line_number: str
    line_number_active: str
    selection: str
    current_line: str
    bracket_match: str
    bracket_mismatch: str
    
    # 编辑器样式
    font_family: str = "Fira Code, Consolas, Monaco, 'Courier New', monospace"
    font_size: int = 14
    line_height: float = 1.5


class ColorSchemes:
    """
    预定义配色方案集合
    参考GitHub Dark/Light和VS Code现代编辑器风格
    """
    
    @staticmethod
    def github_dark() -> ColorScheme:
        """
        GitHub Dark 主题配色方案
        特点：深色背景，柔和对比度，长时间编码舒适
        """
        return ColorScheme(
            # 基础颜色 - 深色背景
            background="#0d1117",
            foreground="#c9d1d9",
            
            # 语法元素颜色 - 柔和不刺眼
            keyword="#ff7b72",          # 柔和红色 - 关键字
            variable="#79c0ff",         # 天蓝色 - 变量
            function="#d2a8ff",         # 淡紫色 - 函数
            string="#a5d6ff",           # 浅蓝色 - 字符串
            comment="#8b949e",          # 灰色 - 注释
            number="#79c0ff",           # 天蓝色 - 数字
            operator="#ff7b72",         # 柔和红色 - 运算符
            class_type="#ffa657",       # 橙色 - 类/类型
            constant="#79c0ff",         # 天蓝色 - 常量
            builtin="#d2a8ff",          # 淡紫色 - 内置函数
            decorator="#d2a8ff",        # 淡紫色 - 装饰器
            
            # 标记语言颜色
            tag="#7ee787",              # 绿色 - 标签
            attribute="#79c0ff",        # 天蓝色 - 属性
            css_property="#79c0ff",     # 天蓝色 - CSS属性
            css_value="#a5d6ff",        # 浅蓝色 - CSS值
            selector="#d2a8ff",         # 淡紫色 - 选择器
            
            # UI颜色
            line_number="#6e7681",
            line_number_active="#c9d1d9",
            selection="#264f78",
            current_line="#161b22",
            bracket_match="#1f6feb",
            bracket_mismatch="#f85149"
        )
    
    @staticmethod
    def github_light() -> ColorScheme:
        """
        GitHub Light 主题配色方案
        特点：浅色背景，清晰对比度，专业可读
        """
        return ColorScheme(
            # 基础颜色 - 浅色背景
            background="#ffffff",
            foreground="#24292f",
            
            # 语法元素颜色 - 清晰区分
            keyword="#cf222e",          # 红色 - 关键字
            variable="#0969da",         # 蓝色 - 变量
            function="#8250df",         # 紫色 - 函数
            string="#0a3069",           # 深蓝色 - 字符串
            comment="#6e7781",          # 灰色 - 注释
            number="#0550ae",           # 蓝色 - 数字
            operator="#cf222e",         # 红色 - 运算符
            class_type="#953800",       # 棕色 - 类/类型
            constant="#0550ae",         # 蓝色 - 常量
            builtin="#8250df",          # 紫色 - 内置函数
            decorator="#8250df",        # 紫色 - 装饰器
            
            # 标记语言颜色
            tag="#116329",              # 绿色 - 标签
            attribute="#0969da",        # 蓝色 - 属性
            css_property="#0969da",     # 蓝色 - CSS属性
            css_value="#0a3069",        # 深蓝色 - CSS值
            selector="#8250df",         # 紫色 - 选择器
            
            # UI颜色
            line_number="#6e7781",
            line_number_active="#24292f",
            selection="#b4d5fe",
            current_line="#f6f8fa",
            bracket_match="#0969da",
            bracket_mismatch="#cf222e"
        )
    
    @staticmethod
    def vscode_dark() -> ColorScheme:
        """
        VS Code Dark+ 主题配色方案
        特点：经典深色，高对比度，专业开发体验
        """
        return ColorScheme(
            # 基础颜色
            background="#1e1e1e",
            foreground="#d4d4d4",
            
            # 语法元素颜色
            keyword="#569cd6",          # 蓝色 - 关键字
            variable="#9cdcfe",         # 浅蓝 - 变量
            function="#dcdcaa",         # 黄色 - 函数
            string="#ce9178",           # 橙色 - 字符串
            comment="#6a9955",          # 绿色 - 注释
            number="#b5cea8",           # 浅绿 - 数字
            operator="#d4d4d4",         # 白色 - 运算符
            class_type="#4ec9b0",       # 青色 - 类/类型
            constant="#4fc1ff",         # 亮蓝 - 常量
            builtin="#dcdcaa",          # 黄色 - 内置函数
            decorator="#4ec9b0",        # 青色 - 装饰器
            
            # 标记语言颜色
            tag="#569cd6",              # 蓝色 - 标签
            attribute="#9cdcfe",        # 浅蓝 - 属性
            css_property="#9cdcfe",     # 浅蓝 - CSS属性
            css_value="#ce9178",        # 橙色 - CSS值
            selector="#d7ba7d",         # 棕色 - 选择器
            
            # UI颜色
            line_number="#858585",
            line_number_active="#c6c6c6",
            selection="#264f78",
            current_line="#2d2d2d",
            bracket_match="#ffd700",
            bracket_mismatch="#f44747"
        )
    
    @staticmethod
    def vscode_light() -> ColorScheme:
        """
        VS Code Light+ 主题配色方案
        特点：经典浅色，清晰易读，适合日间开发
        """
        return ColorScheme(
            # 基础颜色
            background="#ffffff",
            foreground="#333333",
            
            # 语法元素颜色
            keyword="#0000ff",          # 蓝色 - 关键字
            variable="#001080",         # 深蓝 - 变量
            function="#795e26",         # 棕色 - 函数
            string="#a31515",           # 深红 - 字符串
            comment="#008000",          # 绿色 - 注释
            number="#098658",           # 绿色 - 数字
            operator="#000000",         # 黑色 - 运算符
            class_type="#267f99",       # 青色 - 类/类型
            constant="#0070c1",         # 蓝色 - 常量
            builtin="#795e26",          # 棕色 - 内置函数
            decorator="#267f99",        # 青色 - 装饰器
            
            # 标记语言颜色
            tag="#800000",              # 深红 - 标签
            attribute="#001080",        # 深蓝 - 属性
            css_property="#001080",     # 深蓝 - CSS属性
            css_value="#0000ff",        # 蓝色 - CSS值
            selector="#800000",         # 深红 - 选择器
            
            # UI颜色
            line_number="#237893",
            line_number_active="#0b216f",
            selection="#add6ff",
            current_line="#f5f5f5",
            bracket_match="#ffd700",
            bracket_mismatch="#ff0000"
        )


class LanguagePatterns:
    """
    各编程语言语法模式定义
    使用正则表达式定义不同语言的语法元素
    """
    
    # Python 语法模式
    PYTHON = {
        'keywords': [
            r'\b(?:and|as|assert|async|await|break|class|continue|def|del|elif|else|'
            r'except|finally|for|from|global|if|import|in|is|lambda|nonlocal|not|or|'
            r'pass|raise|return|try|while|with|yield|None|True|False)\b'
        ],
        'builtins': [
            r'\b(?:abs|all|any|ascii|bin|bool|breakpoint|bytearray|bytes|callable|chr|'
            r'classmethod|compile|complex|delattr|dict|dir|divmod|enumerate|eval|exec|'
            r'filter|float|format|frozenset|getattr|globals|hasattr|hash|help|hex|id|'
            r'input|int|isinstance|issubclass|iter|len|list|locals|map|max|memoryview|'
            r'min|next|object|oct|open|ord|pow|print|property|range|repr|reversed|round|'
            r'set|setattr|slice|sorted|staticmethod|str|sum|super|tuple|type|vars|zip|'
            r'__import__)\b'
        ],
        'decorators': [r'@\w+(?:\.\w+)*'],
        'functions': [r'\bdef\s+(\w+)'],
        'classes': [r'\bclass\s+(\w+)'],
        'strings': [
            r'"""[\s\S]*?"""',  # 三引号字符串
            r"'''[\s\S]*?'''",
            r'"(?:[^"\\]|\\.)*"',  # 双引号字符串
            r"'(?:[^'\\]|\\.)*'"   # 单引号字符串
        ],
        'comments': [r'#.*'],
        'multiline_strings': [
            r'"""[\s\S]*?"""',
            r"'''[\s\S]*?'''"
        ],
        'numbers': [
            r'\b0[xX][0-9a-fA-F]+\b',  # 十六进制
            r'\b0[oO][0-7]+\b',        # 八进制
            r'\b0[bB][01]+\b',         # 二进制
            r'\b\d+\.?\d*(?:[eE][+-]?\d+)?[jJ]?\b'  # 数字
        ],
        'operators': [
            r'[+\-*/%=<>!&|^~]+',
            r'\*\*=?',
            r'//=?',
            r'<<=?',
            r'>>=?',
            r'==|!=|<=|>=|:=|->'
        ]
    }
    
    # C/C++ 语法模式
    CPP = {
        'keywords': [
            r'\b(?:alignas|alignof|and|and_eq|asm|auto|bitand|bitor|bool|break|case|'
            r'catch|char|char8_t|char16_t|char32_t|class|compl|concept|const|consteval|'
            r'constexpr|constinit|const_cast|continue|co_await|co_return|co_yield|'
            r'decltype|default|delete|do|double|dynamic_cast|else|enum|explicit|export|'
            r'extern|false|float|for|friend|goto|if|inline|int|long|mutable|namespace|'
            r'new|noexcept|not|not_eq|nullptr|operator|or|or_eq|private|protected|'
            r'public|register|reinterpret_cast|requires|return|short|signed|sizeof|'
            r'static|static_assert|static_cast|struct|switch|template|this|thread_local|'
            r'throw|true|try|typedef|typeid|typename|union|unsigned|using|virtual|'
            r'void|volatile|wchar_t|while|xor|xor_eq)\b'
        ],
        'preprocessor': [r'^\s*#\s*\w+'],
        'strings': [
            r'"(?:[^"\\]|\\.)*"',
            r"'(?:[^'\\]|\\.)*'"
        ],
        'comments': [
            r'/\*[\s\S]*?\*/',  # 多行注释
            r'//.*'             # 单行注释
        ],
        'numbers': [
            r'\b0[xX][0-9a-fA-F]+\b',
            r'\b\d+\.?\d*(?:[eE][+-]?\d+)?[fFlL]?\b'
        ],
        'operators': [
            r'[+\-*/%=<>!&|^~]+',
            r'\+\+|--',
            r'<<=?|>>=?',
            r'==|!=|<=|>=|&&|\|\|',
            r'->|\.|->\*|\.\*'
        ]
    }
    
    # Java 语法模式
    JAVA = {
        'keywords': [
            r'\b(?:abstract|assert|boolean|break|byte|case|catch|char|class|const|'
            r'continue|default|do|double|else|enum|extends|false|final|finally|float|'
            r'for|goto|if|implements|import|instanceof|int|interface|long|native|new|'
            r'null|package|private|protected|public|return|short|static|strictfp|super|'
            r'switch|synchronized|this|throw|throws|transient|true|try|void|volatile|while)\b'
        ],
        'annotations': [r'@\w+(?:\([^)]*\))?'],
        'strings': [
            r'"(?:[^"\\]|\\.)*"',
            r"'(?:[^'\\]|\\.)*'"
        ],
        'comments': [
            r'/\*[\s\S]*?\*/',
            r'//.*'
        ],
        'numbers': [
            r'\b0[xX][0-9a-fA-F]+\b',
            r'\b\d+\.?\d*(?:[eE][+-]?\d+)?[fFdDlL]?\b'
        ]
    }
    
    # JavaScript 语法模式
    JAVASCRIPT = {
        'keywords': [
            r'\b(?:async|await|break|case|catch|class|const|continue|debugger|default|'
            r'delete|do|else|export|extends|false|finally|for|function|if|import|in|'
            r'instanceof|let|new|null|return|super|switch|this|throw|true|try|typeof|'
            r'var|void|while|with|yield)\b'
        ],
        'builtins': [
            r'\b(?:Array|Boolean|Date|Error|Function|JSON|Math|Number|Object|RegExp|String|'
            r'Symbol|console|document|window|undefined|NaN|Infinity)\b'
        ],
        'strings': [
            r'`(?:[^`\\]|\\.|\\\$\{[^}]*\})*`',  # 模板字符串
            r'"(?:[^"\\]|\\.)*"',
            r"'(?:[^'\\]|\\.)*'"
        ],
        'comments': [
            r'/\*[\s\S]*?\*/',
            r'//.*$'
        ],
        'regex': [r'/(?:[^/\\]|\\.)+/[gimuy]*'],
        'numbers': [
            r'\b0[xX][0-9a-fA-F]+\b',
            r'\b0[oO][0-7]+\b',
            r'\b0[bB][01]+\b',
            r'\b\d+\.?\d*(?:[eE][+-]?\d+)?\b'
        ]
    }
    
    # C# 语法模式
    CSHARP = {
        'keywords': [
            r'\b(?:abstract|as|base|bool|break|byte|case|catch|char|checked|class|const|'
            r'continue|decimal|default|delegate|do|double|else|enum|event|explicit|'
            r'extern|false|finally|fixed|float|for|foreach|goto|if|implicit|in|int|'
            r'interface|internal|is|lock|long|namespace|new|null|object|operator|out|'
            r'override|params|private|protected|public|readonly|ref|return|sbyte|sealed|'
            r'short|sizeof|stackalloc|static|string|struct|switch|this|throw|true|try|'
            r'typeof|uint|ulong|unchecked|unsafe|ushort|using|virtual|void|volatile|while)\b'
        ],
        'attributes': [r'\[\w+(?:\([^\]]*\))?\]'],
        'strings': [
            r'@"(?:[^"]|"")*"',  # 逐字字符串
            r'\$"(?:[^"\\\{]|\\.|\{[^}]*\})*"',  # 插值字符串
            r'"(?:[^"\\]|\\.)*"',
            r"'(?:[^'\\]|\\.)*'"
        ],
        'comments': [
            r'/\*[\s\S]*?\*/',
            r'//.*$'
        ]
    }
    
    # Go 语法模式
    GO = {
        'keywords': [
            r'\b(?:break|case|chan|const|continue|default|defer|else|fallthrough|for|'
            r'func|go|goto|if|import|interface|map|package|range|return|select|struct|'
            r'switch|type|var)\b'
        ],
        'builtins': [
            r'\b(?:append|cap|close|complex|copy|delete|imag|len|make|new|panic|print|'
            r'println|real|recover)\b'
        ],
        'types': [
            r'\b(?:bool|byte|complex64|complex128|error|float32|float64|int|int8|int16|'
            r'int32|int64|rune|string|uint|uint8|uint16|uint32|uint64|uintptr)\b'
        ],
        'strings': [
            r'`[^`]*`',  # 原始字符串
            r'"(?:[^"\\]|\\.)*"'
        ],
        'comments': [
            r'/\*[\s\S]*?\*/',
            r'//.*$'
        ]
    }
    
    # Rust 语法模式
    RUST = {
        'keywords': [
            r'\b(?:as|async|await|break|const|continue|crate|dyn|else|enum|extern|false|'
            r'fn|for|if|impl|in|let|loop|match|mod|move|mut|pub|ref|return|self|Self|'
            r'static|struct|super|trait|true|type|unsafe|use|where|while)\b'
        ],
        'attributes': [r'#\!?\[[^\]]*\]'],
        'macros': [r'\w+!'],
        'lifetimes': [r"'\w+"],
        'strings': [
            r'b?"(?:[^"\\]|\\.)*"',
            r"b?'(?:[^'\\]|\\.)*'"
        ],
        'comments': [
            r'/\*[\s\S]*?\*/',
            r'//.*$'
        ]
    }
    
    # SQL 语法模式
    SQL = {
        'keywords': [
            r'\b(?:ADD|ALL|ALTER|AND|ANY|AS|ASC|AUTHORIZATION|BACKUP|BEGIN|BETWEEN|'
            r'BREAK|BROWSE|BULK|BY|CASCADE|CASE|CHECK|CHECKPOINT|CLOSE|CLUSTERED|'
            r'COALESCE|COLLATE|COLUMN|COMMIT|COMPUTE|CONNECT|CONSTRAINT|CONTAINS|'
            r'CONTAINSTABLE|CONTINUE|CONVERT|CREATE|CROSS|CURRENT|CURRENT_DATE|'
            r'CURRENT_TIME|CURRENT_TIMESTAMP|CURRENT_USER|CURSOR|DATABASE|DBCC|'
            r'DEALLOCATE|DECLARE|DEFAULT|DELETE|DENY|DESC|DISK|DISTINCT|DISTRIBUTED|'
            r'DOUBLE|DROP|DUMP|ELSE|END|ERRLVL|ESCAPE|EXCEPT|EXEC|EXECUTE|EXISTS|'
            r'EXIT|EXTERNAL|FETCH|FILE|FILLFACTOR|FOR|FOREIGN|FREETEXT|FREETEXTTABLE|'
            r'FROM|FULL|FUNCTION|GOTO|GRANT|GROUP|HAVING|HOLDLOCK|IDENTITY|IDENTITYCOL|'
            r'IDENTITY_INSERT|IF|IN|INDEX|INNER|INSERT|INTERSECT|INTO|IS|JOIN|KEY|'
            r'KILL|LEFT|LIKE|LINENO|LOAD|MERGE|NATIONAL|NOCHECK|NONCLUSTERED|NOT|'
            r'NULL|NULLIF|OF|OFF|OFFSETS|ON|OPEN|OPENDATASOURCE|OPENQUERY|OPENROWSET|'
            r'OPENXML|OPTION|OR|ORDER|OUTER|OVER|PERCENT|PIVOT|PLAN|PRECISION|'
            r'PRIMARY|PRINT|PROC|PROCEDURE|PUBLIC|RAISERROR|READ|READTEXT|RECONFIGURE|'
            r'REFERENCES|REPLICATION|RESTORE|RESTRICT|RETURN|REVERT|REVOKE|RIGHT|'
            r'ROLLBACK|ROWCOUNT|ROWGUIDCOL|RULE|SAVE|SCHEMA|SECURITYAUDIT|SELECT|'
            r'SEMANTICKEYPHRASETABLE|SEMANTICSIMILARITYDETAILSTABLE|SEMANTICSIMILARITYTABLE|'
            r'SET|SETUSER|SHUTDOWN|SOME|STATISTICS|SYSTEM_USER|TABLE|TABLESAMPLE|'
            r'TEXTSIZE|THEN|TO|TOP|TRAN|TRANSACTION|TRIGGER|TRUNCATE|TRY_CONVERT|'
            r'TSEQUAL|UNION|UNIQUE|UNPIVOT|UPDATE|UPDATETEXT|USE|USER|VALUES|'
            r'VARYING|VIEW|WAITFOR|WHERE|WHILE|WITH|WITHIN|WRITETEXT)\b'
        ],
        'functions': [
            r'\b(?:AVG|COUNT|FIRST|LAST|MAX|MIN|SUM|UCASE|LCASE|MID|LEN|ROUND|NOW|FORMAT)\b'
        ],
        'strings': [
            r"'(?:[^']|'')*'",
            r'"(?:[^"]|"")*"'
        ],
        'comments': [
            r'/\*[\s\S]*?\*/',
            r'--.*$'
        ],
        'numbers': [
            r'\b\d+\.?\d*\b'
        ]
    }
    
    # PHP 语法模式
    PHP = {
        'keywords': [
            r'\b(?:__halt_compiler|abstract|and|array|as|break|callable|case|catch|'
            r'class|clone|const|continue|declare|default|die|do|echo|else|elseif|empty|'
            r'enddeclare|endfor|endforeach|endif|endswitch|endwhile|eval|exit|extends|'
            r'final|finally|fn|for|foreach|function|global|goto|if|implements|include|'
            r'include_once|instanceof|insteadof|interface|isset|list|match|namespace|'
            r'new|or|print|private|protected|public|readonly|require|require_once|'
            r'return|static|switch|throw|trait|try|unset|use|var|while|xor|yield|yield from)\b'
        ],
        'variables': [r'\$\w+'],
        'strings': [
            r'"(?:[^"\\]|\\.)*"',
            r"'(?:[^'\\]|\\.)*'",
            r'<<<\w+\n[\s\S]*?\n\w+;?'  # HEREDOC
        ],
        'comments': [
            r'/\*[\s\S]*?\*/',
            r'//.*$',
            r'#.*$'
        ]
    }
    
    # R 语法模式
    R = {
        'keywords': [
            r'\b(?:if|else|repeat|while|function|for|in|next|break|TRUE|FALSE|NULL|'
            r'Inf|NaN|NA|NA_integer_|NA_real_|NA_complex_|NA_character_)\b'
        ],
        'builtins': [
            r'\b(?:c|list|data.frame|matrix|array|factor|as\.\w+|is\.\w+|length|'
            r'mean|median|sd|var|sum|prod|min|max|range|sort|order|rank|unique|'
            r'duplicated|na\.omit|complete\.cases|str|summary|head|tail|names|'
            r'rownames|colnames|dim|nrow|ncol|length|class|mode|typeof|attributes|'
            r'attr|library|require|source|attach|detach|with|within|subset|transform|'
            r'aggregate|merge|reshape|stack|unstack|read\.\w+|write\.\w+|print|'
            r'cat|message|warning|stop|try|tryCatch|debug|browser|trace|untrace)\b'
        ],
        'strings': [
            r'"(?:[^"\\]|\\.)*"',
            r"'(?:[^'\\]|\\.)*'"
        ],
        'comments': [r'#.*$'],
        'numbers': [
            r'\b\d+\.?\d*(?:[eE][+-]?\d+)?[iL]?\b'
        ]
    }
    
    # Lua 语法模式
    LUA = {
        'keywords': [
            r'\b(?:and|break|do|else|elseif|end|false|for|function|goto|if|in|local|'
            r'nil|not|or|repeat|return|then|true|until|while)\b'
        ],
        'builtins': [
            r'\b(?:assert|collectgarbage|dofile|error|getmetatable|ipairs|load|loadfile|'
            r'next|pairs|pcall|print|rawequal|rawget|rawlen|rawset|require|select|'
            r'setmetatable|tonumber|tostring|type|xpcall|_G|_VERSION)\b'
        ],
        'strings': [
            r'\[\[.*?\]\]',  # 多行字符串
            r'"(?:[^"\\]|\\.)*"',
            r"'(?:[^'\\]|\\.)*'"
        ],
        'comments': [
            r'--\[\[[\s\S]*?\]\]',  # 多行注释
            r'--.*$'                 # 单行注释
        ]
    }
    
    # VB/VBA 语法模式
    VB = {
        'keywords': [
            r'\b(?:AddHandler|AddressOf|Alias|And|AndAlso|As|Boolean|ByRef|Byte|ByVal|'
            r'Call|Case|Catch|CBool|CByte|CChar|CDate|CDbl|CDec|Char|CInt|Class|CLng|'
            r'CObj|Const|Continue|CSByte|CShort|CSng|CStr|CType|CUInt|CULng|CUShort|'
            r'Date|Decimal|Declare|Default|Delegate|Dim|DirectCast|Do|Double|Each|'
            r'Else|ElseIf|End|EndIf|Enum|Erase|Error|Event|Exit|False|Finally|For|'
            r'Friend|Function|Get|GetType|GetXMLNamespace|Global|GoSub|GoTo|Handles|'
            r'If|Implements|Imports|In|Inherits|Integer|Interface|Is|IsNot|Let|Lib|'
            r'Like|Long|Loop|Me|Mod|Module|MustInherit|MustOverride|MyBase|MyClass|'
            r'Namespace|Narrowing|New|Next|Not|Nothing|NotInheritable|NotOverridable|'
            r'Object|Of|On|Operator|Option|Optional|Or|OrElse|Out|Overloads|'
            r'Overridable|Overrides|ParamArray|Partial|Private|Property|Protected|'
            r'Public|RaiseEvent|ReadOnly|ReDim|REM|RemoveHandler|Resume|Return|'
            r'SByte|Select|Set|Shadows|Shared|Short|Single|Static|Step|Stop|String|'
            r'Structure|Sub|SyncLock|Then|Throw|To|True|Try|TryCast|TypeOf|UInteger|'
            r'ULong|UShort|Using|Variant|Wend|When|While|Widening|With|WithEvents|'
            r'WriteOnly|Xor)\b'
        ],
        'strings': [
            r'"(?:[^"]|"")*"'
        ],
        'comments': [r"'.*$"],
        'numbers': [
            r'\b\d+\.?\d*(?:[eE][+-]?\d+)?[DFILS@]?\b',
            r'&H[0-9a-fA-F]+'
        ]
    }
    
    # HTML 语法模式
    HTML = {
        'doctype': [r'<!DOCTYPE[^>]*>'],
        'tags': [
            r'</?[a-zA-Z][a-zA-Z0-9]*',  # 标签名
            r'>',
            r'/>'
        ],
        'attributes': [
            r'\b[a-zA-Z-]+(?=\s*=)',  # 属性名
            r'="[^"]*"',              # 双引号属性值
            r"='[^']*'"               # 单引号属性值
        ],
        'comments': [r'<!--[\s\S]*?-->'],
        'entities': [r'&\w+;', r'&#\d+;', r'&#x[0-9a-fA-F]+;']
    }
    
    # CSS 语法模式
    CSS = {
        'selectors': [
            r'[.#]\w+',           # 类和ID选择器
            r'::?\w+',            # 伪类和伪元素
            r'\*',                # 通配符
            r'\[.*?\]'           # 属性选择器
        ],
        'at_rules': [
            r'@\w+[^;{]*',        # @规则
            r'@media[^{]*\{',
            r'@keyframes\s+\w+'
        ],
        'properties': [
            r'(?<=[{\s;])([a-zA-Z-]+)(?=\s*:)'  # 属性名
        ],
        'values': [
            r':\s*([^;{]+)'      # 属性值
        ],
        'strings': [
            r'"[^"]*"',
            r"'[^']*'"
        ],
        'comments': [r'/\*[\s\S]*?\*/'],
        'colors': [
            r'#[0-9a-fA-F]{3,8}\b',
            r'\brgb(?:a)?\([^)]*\)',
            r'\bhsl(?:a)?\([^)]*\)'
        ],
        'units': [
            r'\b\d+\.?\d*(?:px|em|rem|%|vh|vw|vmin|vmax|ex|ch|cm|mm|in|pt|pc|s|ms|deg|'
            r'rad|grad|turn|Hz|kHz|dpi|dpcm|dppx)\b'
        ]
    }
    
    # JSON 语法模式
    JSON = {
        'keys': [r'"(?:[^"\\]|\\.)*"(?=\s*:)'],
        'strings': [r'"(?:[^"\\]|\\.)*"'],
        'numbers': [
            r'-?\d+\.?\d*(?:[eE][+-]?\d+)?',
            r'true|false|null'
        ],
        'punctuation': [r'[{}\[\]:,]']
    }
    
    # XML 语法模式
    XML = {
        'prolog': [r'<\?xml[^?]*\?>'],
        'doctype': [r'<!DOCTYPE[^>]*>'],
        'tags': [
            r'</?[\w:]+',          # 标签名（支持命名空间）
            r'>',
            r'/>'
        ],
        'attributes': [
            r'[\w:]+(?=\s*=)',     # 属性名
            r'="[^"]*"',           # 双引号属性值
            r"='[^']*'"            # 单引号属性值
        ],
        'comments': [r'<!--[\s\S]*?-->'],
        'cdata': [r'<!\[CDATA\[[\s\S]*?\]\]>'],
        'entities': [r'&\w+;', r'&#\d+;', r'&#x[0-9a-fA-F]+;'],
        'processing': [r'<\?[\w:]+[^?]*\?>']
    }


class SyntaxHighlighter:
    """
    语法高亮处理器核心类
    
    负责解析代码文本，识别语法元素，并应用配色方案
    """
    
    def __init__(self, color_scheme: Optional[ColorScheme] = None):
        """
        初始化语法高亮处理器
        
        参数：
            color_scheme: 配色方案，默认使用GitHub Dark
        """
        self.color_scheme = color_scheme or ColorSchemes.github_dark()
        self._format_cache: Dict[TokenType, QTextCharFormat] = {}
        self._build_format_cache()
    
    def _build_format_cache(self):
        """构建文本格式缓存，避免重复创建"""
        scheme = self.color_scheme
        
        # 通用语法元素格式
        self._format_cache[TokenType.KEYWORD] = self._create_format(scheme.keyword, bold=True)
        self._format_cache[TokenType.VARIABLE] = self._create_format(scheme.variable)
        self._format_cache[TokenType.FUNCTION] = self._create_format(scheme.function)
        self._format_cache[TokenType.STRING] = self._create_format(scheme.string)
        self._format_cache[TokenType.COMMENT] = self._create_format(scheme.comment, italic=True)
        self._format_cache[TokenType.NUMBER] = self._create_format(scheme.number)
        self._format_cache[TokenType.OPERATOR] = self._create_format(scheme.operator)
        self._format_cache[TokenType.CLASS_TYPE] = self._create_format(scheme.class_type)
        self._format_cache[TokenType.CONSTANT] = self._create_format(scheme.constant)
        self._format_cache[TokenType.BUILTIN] = self._create_format(scheme.builtin)
        self._format_cache[TokenType.DECORATOR] = self._create_format(scheme.decorator)
        
        # 标记语言格式
        self._format_cache[TokenType.TAG] = self._create_format(scheme.tag, bold=True)
        self._format_cache[TokenType.ATTRIBUTE] = self._create_format(scheme.attribute)
        self._format_cache[TokenType.CSS_PROPERTY] = self._create_format(scheme.css_property)
        self._format_cache[TokenType.CSS_VALUE] = self._create_format(scheme.css_value)
        self._format_cache[TokenType.SELECTOR] = self._create_format(scheme.selector)
        
        # 默认格式
        self._format_cache[TokenType.PLAIN] = self._create_format(scheme.foreground)
    
    def _create_format(self, color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
        """
        创建文本字符格式
        
        参数：
            color: 颜色值（十六进制）
            bold: 是否粗体
            italic: 是否斜体
            
        返回：
            QTextCharFormat: 文本格式对象
        """
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        
        if bold:
            fmt.setFontWeight(QFont.Bold)
        if italic:
            fmt.setFontItalic(True)
        
        # 设置字体
        font = QFont(self.color_scheme.font_family)
        font.setStyleHint(QFont.Monospace)
        font.setFixedPitch(True)
        fmt.setFont(font)
        
        return fmt
    
    def set_color_scheme(self, scheme: ColorScheme):
        """
        设置配色方案
        
        参数：
            scheme: 新的配色方案
        """
        self.color_scheme = scheme
        self._format_cache.clear()
        self._build_format_cache()
    
    def get_format(self, token_type: TokenType) -> QTextCharFormat:
        """
        获取指定语法元素的格式
        
        参数：
            token_type: 语法元素类型
            
        返回：
            QTextCharFormat: 文本格式对象
        """
        return self._format_cache.get(token_type, self._format_cache[TokenType.PLAIN])
    
    def highlight_line(self, text: str, language: str) -> List[Tuple[str, QTextCharFormat]]:
        """
        高亮单行代码
        
        参数：
            text: 代码文本
            language: 编程语言标识
            
        返回：
            List[Tuple[str, QTextCharFormat]]: 高亮后的文本段列表
        """
        tokens = self.tokenize(text, language)
        result = []
        
        for token in tokens:
            fmt = self.get_format(token.type)
            result.append((token.value, fmt))
        
        return result
    
    def tokenize(self, text: str, language: str) -> List[Token]:
        """
        将代码文本分解为语法标记
        
        参数：
            text: 代码文本
            language: 编程语言标识
            
        返回：
            List[Token]: 语法标记列表
        """
        # 获取语言模式
        patterns = self._get_language_patterns(language)
        if not patterns:
            # 无匹配模式时返回纯文本
            return [Token(TokenType.PLAIN, text, 0, len(text))]
        
        tokens = []
        pos = 0
        
        # 按优先级顺序匹配各类语法元素
        while pos < len(text):
            matched = False
            
            # 注释优先（通常包含其他字符）
            if 'comments' in patterns:
                for pattern in patterns['comments']:
                    match = re.match(pattern, text[pos:])
                    if match:
                        tokens.append(Token(TokenType.COMMENT, match.group(), pos, pos + len(match.group())))
                        pos += len(match.group())
                        matched = True
                        break
                if matched:
                    continue
            
            # 字符串
            if 'strings' in patterns:
                for pattern in patterns['strings']:
                    match = re.match(pattern, text[pos:])
                    if match:
                        tokens.append(Token(TokenType.STRING, match.group(), pos, pos + len(match.group())))
                        pos += len(match.group())
                        matched = True
                        break
                if matched:
                    continue
            
            # 关键字
            if 'keywords' in patterns:
                for pattern in patterns['keywords']:
                    match = re.match(pattern, text[pos:])
                    if match:
                        tokens.append(Token(TokenType.KEYWORD, match.group(), pos, pos + len(match.group())))
                        pos += len(match.group())
                        matched = True
                        break
                if matched:
                    continue
            
            # 数字
            if 'numbers' in patterns:
                for pattern in patterns['numbers']:
                    match = re.match(pattern, text[pos:])
                    if match:
                        tokens.append(Token(TokenType.NUMBER, match.group(), pos, pos + len(match.group())))
                        pos += len(match.group())
                        matched = True
                        break
                if matched:
                    continue
            
            # 内置函数
            if 'builtins' in patterns:
                for pattern in patterns['builtins']:
                    match = re.match(pattern, text[pos:])
                    if match:
                        tokens.append(Token(TokenType.BUILTIN, match.group(), pos, pos + len(match.group())))
                        pos += len(match.group())
                        matched = True
                        break
                if matched:
                    continue
            
            # 装饰器/注解
            if 'decorators' in patterns or 'annotations' in patterns or 'attributes' in patterns:
                dec_patterns = (patterns.get('decorators', []) + 
                               patterns.get('annotations', []) + 
                               patterns.get('attributes', []))
                for pattern in dec_patterns:
                    match = re.match(pattern, text[pos:])
                    if match:
                        tokens.append(Token(TokenType.DECORATOR, match.group(), pos, pos + len(match.group())))
                        pos += len(match.group())
                        matched = True
                        break
                if matched:
                    continue
            
            # 运算符
            if 'operators' in patterns:
                for pattern in patterns['operators']:
                    match = re.match(pattern, text[pos:])
                    if match:
                        tokens.append(Token(TokenType.OPERATOR, match.group(), pos, pos + len(match.group())))
                        pos += len(match.group())
                        matched = True
                        break
                if matched:
                    continue
            
            # HTML/XML标签（针对标记语言）
            if 'tags' in patterns:
                for pattern in patterns['tags']:
                    match = re.match(pattern, text[pos:])
                    if match:
                        tokens.append(Token(TokenType.TAG, match.group(), pos, pos + len(match.group())))
                        pos += len(match.group())
                        matched = True
                        break
                if matched:
                    continue
            
            # HTML/XML属性（针对标记语言）
            if 'attributes' in patterns:
                for pattern in patterns['attributes']:
                    match = re.match(pattern, text[pos:])
                    if match:
                        tokens.append(Token(TokenType.ATTRIBUTE, match.group(), pos, pos + len(match.group())))
                        pos += len(match.group())
                        matched = True
                        break
                if matched:
                    continue
            
            # 未匹配到的字符作为普通文本
            if not matched:
                # 合并连续的普通文本
                plain_text = text[pos]
                pos += 1
                while pos < len(text):
                    # 检查下一个字符是否会被匹配
                    next_matched = False
                    for key in patterns:
                        for pattern in patterns[key]:
                            if re.match(pattern, text[pos:]):
                                next_matched = True
                                break
                        if next_matched:
                            break
                    if next_matched:
                        break
                    plain_text += text[pos]
                    pos += 1
                
                tokens.append(Token(TokenType.PLAIN, plain_text, pos - len(plain_text), pos))
        
        return tokens
    
    def _get_language_patterns(self, language: str) -> Dict[str, List[str]]:
        """
        获取指定语言的模式定义
        
        参数：
            language: 编程语言标识（小写）
            
        返回：
            Dict[str, List[str]]: 模式定义字典
        """
        language = language.lower()
        
        patterns_map = {
            'python': LanguagePatterns.PYTHON,
            'py': LanguagePatterns.PYTHON,
            'c': LanguagePatterns.CPP,
            'cpp': LanguagePatterns.CPP,
            'c++': LanguagePatterns.CPP,
            'cxx': LanguagePatterns.CPP,
            'java': LanguagePatterns.JAVA,
            'javascript': LanguagePatterns.JAVASCRIPT,
            'js': LanguagePatterns.JAVASCRIPT,
            'typescript': LanguagePatterns.JAVASCRIPT,
            'ts': LanguagePatterns.JAVASCRIPT,
            'csharp': LanguagePatterns.CSHARP,
            'c#': LanguagePatterns.CSHARP,
            'cs': LanguagePatterns.CSHARP,
            'go': LanguagePatterns.GO,
            'golang': LanguagePatterns.GO,
            'rust': LanguagePatterns.RUST,
            'rs': LanguagePatterns.RUST,
            'sql': LanguagePatterns.SQL,
            'php': LanguagePatterns.PHP,
            'r': LanguagePatterns.R,
            'lua': LanguagePatterns.LUA,
            'vb': LanguagePatterns.VB,
            'vba': LanguagePatterns.VB,
            'html': LanguagePatterns.HTML,
            'htm': LanguagePatterns.HTML,
            'css': LanguagePatterns.CSS,
            'json': LanguagePatterns.JSON,
            'xml': LanguagePatterns.XML,
            'xhtml': LanguagePatterns.XML,
            'svg': LanguagePatterns.XML
        }
        
        return patterns_map.get(language, {})
    
    def get_background_color(self) -> QColor:
        """获取背景颜色"""
        return QColor(self.color_scheme.background)
    
    def get_foreground_color(self) -> QColor:
        """获取前景（文本）颜色"""
        return QColor(self.color_scheme.foreground)
    
    def get_selection_color(self) -> QColor:
        """获取选中区域颜色"""
        return QColor(self.color_scheme.selection)
    
    def get_current_line_color(self) -> QColor:
        """获取当前行高亮颜色"""
        return QColor(self.color_scheme.current_line)
    
    def get_line_number_color(self) -> QColor:
        """获取行号颜色"""
        return QColor(self.color_scheme.line_number)
    
    def get_line_number_active_color(self) -> QColor:
        """获取当前行号颜色"""
        return QColor(self.color_scheme.line_number_active)


def is_dark_mode() -> bool:
    """
    检测当前是否为深色模式
    
    从SettingsManager读取当前主题设置，自动判断是否为深色模式
    
    返回：
        bool: True为深色模式，False为浅色模式
    """
    if SettingsManager is None:
        # 无法导入SettingsManager时，默认使用深色模式
        return True
    
    try:
        settings_manager = SettingsManager()
        current_theme = settings_manager.get_setting("appearance.theme", "default")
        return current_theme == "dark"
    except Exception:
        # 读取失败时默认使用深色模式
        return True


def get_auto_theme_scheme() -> ColorScheme:
    """
    根据当前系统主题自动获取配色方案
    
    如果当前是深色模式，返回GitHub Dark主题
    如果当前是浅色模式，返回GitHub Light主题
    
    返回：
        ColorScheme: 自动选择的配色方案
    """
    if is_dark_mode():
        return ColorSchemes.github_dark()
    else:
        return ColorSchemes.github_light()


# 便捷函数
def create_highlighter(theme: str = "auto") -> SyntaxHighlighter:
    """
    创建指定主题的语法高亮器
    
    参数：
        theme: 主题名称，可选值：
               - "auto": 自动根据系统主题选择（默认）
               - "github_dark", "github_light"
               - "vscode_dark", "vscode_light"
               
    返回：
        SyntaxHighlighter: 语法高亮器实例
    """
    # 如果设置为auto，自动检测系统主题
    if theme == "auto":
        scheme = get_auto_theme_scheme()
        return SyntaxHighlighter(scheme)
    
    schemes = {
        "github_dark": ColorSchemes.github_dark(),
        "github_light": ColorSchemes.github_light(),
        "vscode_dark": ColorSchemes.vscode_dark(),
        "vscode_light": ColorSchemes.vscode_light()
    }
    
    scheme = schemes.get(theme, ColorSchemes.github_dark())
    return SyntaxHighlighter(scheme)


def get_supported_languages() -> List[str]:
    """
    获取支持的语言列表
    
    返回：
        List[str]: 支持的语言标识列表
    """
    return [
        "python", "py",
        "c", "cpp", "c++", "cxx",
        "java",
        "javascript", "js", "typescript", "ts",
        "csharp", "c#", "cs",
        "go", "golang",
        "rust", "rs",
        "sql",
        "php",
        "r",
        "lua",
        "vb", "vba",
        "html", "htm",
        "css",
        "json",
        "xml", "xhtml", "svg"
    ]


# 测试代码
if __name__ == "__main__":
    # 测试配色方案
    print("测试配色方案...")
    
    # 测试Python代码高亮
    python_code = '''
# 这是一个测试函数
def hello_world(name: str) -> str:
    """返回问候语"""
    message = f"Hello, {name}!"
    return message

class MyClass:
    def __init__(self):
        self.value = 42
    
    @property
    def double(self):
        return self.value * 2
'''
    
    print("\nPython代码测试:")
    print(python_code)
    
    # 测试C++代码高亮
    cpp_code = '''
// C++示例代码
#include <iostream>
#include <vector>

class Calculator {
public:
    int add(int a, int b) {
        return a + b;  // 返回和
    }
    
    template<typename T>
    T multiply(T a, T b) {
        return a * b;
    }
};

int main() {
    Calculator calc;
    std::cout << "Result: " << calc.add(5, 3) << std::endl;
    return 0;
}
'''
    
    print("\nC++代码测试:")
    print(cpp_code)
    
    print("\n配色方案加载成功！")
    print(f"支持的语言: {len(get_supported_languages())} 种")
