#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

路径处理工具模块
提供资源文件路径、应用数据路径和配置文件路径的处理函数
提供文件系统访问控制功能，防止访问敏感系统路径
"""

import sys
import os
import re
from pathlib import Path
from typing import List, Optional, Set


# Windows保留文件名（不能用作文件名）
WINDOWS_RESERVED_NAMES: Set[str] = {
    'CON', 'PRN', 'AUX', 'NUL',
    'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
    'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'
}

# 非法文件名字符（Windows系统）
ILLEGAL_FILENAME_CHARS: Set[str] = {'<', '>', ':', '"', '|', '?', '*'}

# 最大文件名长度限制
MAX_FILENAME_LENGTH: int = 255

# 最大路径长度限制（Windows标准路径限制）
MAX_PATH_LENGTH: int = 260

# 默认允许的文件扩展名白名单
DEFAULT_ALLOWED_EXTENSIONS: Set[str] = {
    '.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.mpg', '.mpeg',
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp', '.ico',
    '.txt', '.json', '.xml', '.yaml', '.yml', '.ini', '.conf', '.config',
    '.dll', '.exe', '.py', '.pyd', '.pyw'
}

# Windows敏感系统路径黑名单（阻止访问这些路径）
SENSITIVE_PATH_PATTERNS: List[str] = [
    r'^[A-Za-z]:\\Windows',
    r'^[A-Za-z]:\\Program Files',
    r'^[A-Za-z]:\\Program Files \(x86\)',
    r'^[A-Za-z]:\\ProgramData',
    r'^[A-Za-z]:\\Users\\[^\\]+\\AppData\\Local\\Microsoft',
    r'^[A-Za-z]:\\Users\\[^\\]+\\AppData\\Roaming\\Microsoft',
    r'^[A-Za-z]:\\$Recycle\.Bin',
    r'^[A-Za-z]:\\Config\.Msi',
    r'^[A-Za-z]:\\Documents and Settings',
    r'^[A-Za-z]:\\Boot',
    r'^[A-Za-z]:\\System Volume Information',
    r'^[A-Za-z]:\\EFI',
    r'^[A-Za-z]:\\Recovery',
    r'^[A-Za-z]:\\pagefile\.sys$',
    r'^[A-Za-z]:\\hiberfil\.sys$',
    r'^\\\\\\.\\',  # 设备命名空间
    r'^\\\\\\?\\',  # 扩展UNC路径
    r'^\\\\[^\\]+\\',  # UNC网络路径
]

# 编译正则表达式以提高性能
_SENSITIVE_PATH_REGEX = [re.compile(pattern, re.IGNORECASE) for pattern in SENSITIVE_PATH_PATTERNS]

# 允许访问的目录白名单（项目相关路径）
_ALLOWED_BASE_PATHS: List[str] = []


def _get_project_root() -> str:
    """获取项目根目录"""
    try:
        # PyInstaller打包环境
        if getattr(sys, 'frozen', False):
            return os.path.dirname(sys.executable)
        else:
            # 开发环境
            current_file = os.path.abspath(__file__)
            # 从utils/path_utils.py向上3级到项目根目录
            return os.path.dirname(os.path.dirname(os.path.dirname(current_file)))
    except Exception:
        return os.path.abspath(".")


def _init_allowed_paths():
    """初始化允许访问的路径白名单"""
    global _ALLOWED_BASE_PATHS
    if _ALLOWED_BASE_PATHS:
        return
    
    project_root = _get_project_root()
    
    # 添加项目相关路径到白名单
    _ALLOWED_BASE_PATHS = [
        project_root,
        os.path.join(project_root, 'data'),
        os.path.join(project_root, 'config'),
        os.path.join(project_root, 'resources'),
        os.path.join(project_root, 'assets'),
        os.path.join(project_root, 'freeassetfilter'),
        os.path.join(project_root, 'core'),
        os.path.join(project_root, 'utils'),
        os.path.join(project_root, 'thumbnails'),
    ]
    
    # 添加用户文档目录（用于打开视频文件）
    try:
        import ctypes.wintypes
        CSIDL_PERSONAL = 5  # My Documents
        SHGFP_TYPE_CURRENT = 0
        
        buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
        ctypes.windll.shell32.SHGetFolderPathW(None, CSIDL_PERSONAL, None, SHGFP_TYPE_CURRENT, buf)
        documents_path = buf.value
        if documents_path and os.path.exists(documents_path):
            _ALLOWED_BASE_PATHS.append(documents_path)
    except Exception:
        pass
    
    # 添加桌面目录
    try:
        import ctypes.wintypes
        CSIDL_DESKTOPDIRECTORY = 16
        SHGFP_TYPE_CURRENT = 0
        
        buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
        ctypes.windll.shell32.SHGetFolderPathW(None, CSIDL_DESKTOPDIRECTORY, None, SHGFP_TYPE_CURRENT, buf)
        desktop_path = buf.value
        if desktop_path and os.path.exists(desktop_path):
            _ALLOWED_BASE_PATHS.append(desktop_path)
    except Exception:
        pass
    
    # 添加临时目录（用于临时文件操作）
    temp_dir = os.environ.get('TEMP') or os.environ.get('TMP')
    if temp_dir and os.path.exists(temp_dir):
        _ALLOWED_BASE_PATHS.append(temp_dir)
    
    # 规范化所有路径
    _ALLOWED_BASE_PATHS = [os.path.normpath(p) for p in _ALLOWED_BASE_PATHS if os.path.exists(p)]


def is_sensitive_path(path: str) -> bool:
    """
    检查路径是否为敏感系统路径
    
    Args:
        path: 要检查的路径
        
    Returns:
        bool: 如果是敏感路径返回True
    """
    if not path:
        return False
    
    # 规范化路径
    try:
        normalized_path = os.path.normpath(os.path.abspath(path))
    except Exception:
        return True  # 无法解析的路径视为敏感路径
    
    # 检查是否匹配敏感路径模式
    for pattern in _SENSITIVE_PATH_REGEX:
        if pattern.match(normalized_path):
            return True
    
    return False


def is_path_allowed(path: str, strict: bool = False) -> bool:
    """
    验证路径是否在允许访问的范围内
    
    Args:
        path: 要验证的路径
        strict: 是否严格模式（True时只允许白名单内的路径）
        
    Returns:
        bool: 路径是否允许访问
    """
    if not path:
        return False
    
    # 首先检查是否为敏感路径
    if is_sensitive_path(path):
        return False
    
    # 规范化路径
    try:
        normalized_path = os.path.normpath(os.path.abspath(path))
    except Exception:
        return False
    
    # 检查路径是否存在（可选，不强制要求）
    # 如果路径不存在，检查其父目录
    check_path = normalized_path
    while not os.path.exists(check_path) and check_path != os.path.dirname(check_path):
        check_path = os.path.dirname(check_path)
    
    # 初始化白名单
    _init_allowed_paths()
    
    # 检查是否在白名单内
    for allowed_path in _ALLOWED_BASE_PATHS:
        try:
            # 检查路径是否以允许的路径开头
            if normalized_path.lower().startswith(allowed_path.lower()):
                return True
            # 检查允许的路径是否以当前路径开头（当前路径是允许路径的父目录）
            if allowed_path.lower().startswith(normalized_path.lower()):
                return True
        except Exception:
            continue
    
    # 非严格模式下，允许访问用户选择的文件（视频文件等）
    if not strict:
        # 检查是否是文件路径（有扩展名）
        if os.path.splitext(normalized_path)[1]:
            # 检查父目录是否可访问
            parent_dir = os.path.dirname(normalized_path)
            if parent_dir and not is_sensitive_path(parent_dir):
                return True
    
    return False


def validate_dll_path(dll_path: str) -> bool:
    """
    验证DLL路径的合法性，防止DLL劫持攻击
    
    Args:
        dll_path: DLL文件路径
        
    Returns:
        bool: 路径是否合法
    """
    if not dll_path:
        return False
    
    # 规范化路径
    try:
        normalized_path = os.path.normpath(os.path.abspath(dll_path))
    except Exception:
        return False
    
    # 检查文件是否存在
    if not os.path.exists(normalized_path):
        return False
    
    # 检查是否为文件
    if not os.path.isfile(normalized_path):
        return False
    
    # 检查扩展名
    if not normalized_path.lower().endswith('.dll'):
        return False
    
    # 获取项目根目录
    project_root = _get_project_root()
    system_root = os.environ.get('SystemRoot', r'C:\Windows')
    system32 = os.path.join(system_root, 'System32')
    syswow64 = os.path.join(system_root, 'SysWOW64')
    
    # 定义允许的DLL位置（按优先级检查）
    allowed_locations = [
        project_root,
        system32,
        syswow64,
    ]
    
    # 检查是否在允许的位置
    is_in_allowed_location = False
    for allowed_path in allowed_locations:
        try:
            if normalized_path.lower().startswith(os.path.normpath(allowed_path).lower() + os.sep):
                is_in_allowed_location = True
                break
            if normalized_path.lower() == os.path.normpath(allowed_path).lower():
                is_in_allowed_location = True
                break
        except Exception:
            continue
    
    if is_in_allowed_location:
        return True
    
    # 检查是否在PATH环境变量中的可信系统路径
    path_env = os.environ.get('PATH', '')
    for path_dir in path_env.split(os.pathsep):
        if not path_dir:
            continue
        try:
            norm_path_dir = os.path.normpath(path_dir)
            if normalized_path.lower().startswith(norm_path_dir.lower() + os.sep):
                if norm_path_dir.lower().startswith(system_root.lower()):
                    return True
        except Exception:
            continue
    
    # 检查是否为敏感路径（排除已检查的系统目录）
    if is_sensitive_path(normalized_path):
        return False
    
    return False


def get_safe_dll_paths(dll_name: str) -> List[str]:
    """
    获取安全的DLL搜索路径列表
    
    Args:
        dll_name: DLL文件名
        
    Returns:
        List[str]: 安全的DLL路径列表
    """
    safe_paths = []
    
    # 1. 项目目录（最高优先级）
    project_root = _get_project_root()
    core_dir = os.path.join(project_root, 'freeassetfilter', 'core')
    
    for base_dir in [core_dir, project_root]:
        dll_path = os.path.join(base_dir, dll_name)
        if validate_dll_path(dll_path):
            safe_paths.append(dll_path)
    
    # 2. 系统目录
    system_root = os.environ.get('SystemRoot', r'C:\Windows')
    for sys_dir in ['System32', 'SysWOW64']:
        dll_path = os.path.join(system_root, sys_dir, dll_name)
        if validate_dll_path(dll_path):
            safe_paths.append(dll_path)
    
    return safe_paths


# 命令注入特殊字符（仅检查在subprocess参数列表中真正危险的字符）
# 注意：由于使用subprocess.run()传递参数列表（不使用shell=True），
# 文件名中的 &, |, <, > 等字符不会被shell解释，因此是安全的。
# 真正危险的是控制字符和命令替换模式。
INJECTION_CHARS = ['\n', '\r', '\x00']
INJECTION_DANGEROUS_PATTERNS = [
    '$(', '${', '`',  # 命令替换模式（虽然shell=False时不生效，但仍应拒绝）
]


def contains_injection_chars(path: str) -> bool:
    """
    检查路径是否包含命令注入特殊字符
    
    注意：此函数用于检测在subprocess参数列表中真正危险的字符。
    由于使用subprocess.run()传递参数列表（不使用shell=True），
    文件名中的 &, |, <, > 等字符不会被shell解释，因此是安全的。
    
    Args:
        path: 要检查的路径字符串
        
    Returns:
        bool: 如果包含命令注入字符返回True，否则返回False
    """
    if not path:
        return False
    
    # 检查控制字符（换行、回车、空字节）
    for char in INJECTION_CHARS:
        if char in path:
            return True
    
    # 检查命令替换模式
    for pattern in INJECTION_DANGEROUS_PATTERNS:
        if pattern in path:
            return True
    
    return False


def validate_safe_path(path: str, base_path: str = None) -> str:
    """
    验证并规范化路径，防止路径遍历攻击
    
    Args:
        path: 要验证的路径
        base_path: 基础路径，用于限制路径必须在指定目录下
        
    Returns:
        str: 规范化后的绝对路径
        
    Raises:
        ValueError: 如果路径包含命令注入字符或路径遍历攻击
    """
    if not path:
        raise ValueError("路径不能为空")
    
    # 注意：不在这里检查命令注入字符，因为 & 等字符在Windows文件路径中是合法的
    # 命令注入检查应该在使用路径执行外部命令时进行（见 py7z_core.py）
    
    # 规范化路径
    try:
        # 先转换为绝对路径
        abs_path = os.path.abspath(os.path.expanduser(path))
        # 解析所有符号链接和相对路径
        resolved_path = os.path.realpath(abs_path)
    except Exception as e:
        raise ValueError(f"路径解析失败: {e}")
    
    # 如果指定了基础路径，检查是否在基础路径下
    if base_path:
        base_path_resolved = os.path.realpath(os.path.abspath(os.path.expanduser(base_path)))
        # 确保基础路径以分隔符结尾，防止部分匹配
        if not base_path_resolved.endswith(os.sep):
            base_path_resolved += os.sep
        
        if not resolved_path.startswith(base_path_resolved) and resolved_path != base_path_resolved.rstrip(os.sep):
            raise ValueError(f"路径遍历攻击检测: {path} 不在允许的目录 {base_path} 下")
    
    return resolved_path


def is_path_within_base(path: str, base_path: str) -> bool:
    """
    检查路径是否在基础路径下（防止路径遍历）
    
    Args:
        path: 要检查的路径
        base_path: 基础路径
        
    Returns:
        bool: 如果路径在基础路径下返回True
    """
    try:
        resolved_path = os.path.realpath(os.path.abspath(os.path.expanduser(path)))
        base_resolved = os.path.realpath(os.path.abspath(os.path.expanduser(base_path)))
        
        # 确保基础路径以分隔符结尾
        if not base_resolved.endswith(os.sep):
            base_resolved += os.sep
        
        return resolved_path.startswith(base_resolved) or resolved_path == base_resolved.rstrip(os.sep)
    except Exception:
        return False

def get_resource_path(relative_path):
    """获取资源文件的绝对路径，兼容开发和打包环境"""
    try:
        # PyInstaller创建临时文件夹，存储于_MEIPASS
        base_path = sys._MEIPASS
    except AttributeError:
        # 开发环境：使用项目根目录
        base_path = os.path.abspath(".")
        # 向上找到项目根目录
        if not os.path.exists(os.path.join(base_path, relative_path)):
            # 如果当前目录没有，尝试向上查找
            base_path = os.path.dirname(os.path.abspath(__file__))
            for _ in range(3):  # 最多向上找3级
                if os.path.exists(os.path.join(base_path, relative_path)):
                    break
                base_path = os.path.dirname(base_path)
    
    return os.path.join(base_path, relative_path)


def get_app_version(default: str = "未知版本") -> str:
    """
    统一读取应用版本号，兼容开发环境与打包环境

    Args:
        default: 读取失败时返回的默认版本号

    Returns:
        str: FAFVERSION 第一行中的版本号，失败时返回 default
    """
    try:
        version_file_path = get_resource_path("FAFVERSION")

        with open(version_file_path, "r", encoding="utf-8") as version_file:
            first_line = version_file.readline().strip()
            if first_line:
                return first_line
    except Exception as e:
        try:
            from freeassetfilter.utils.app_logger import warning
            warning(f"读取 FAFVERSION 失败: {e}")
        except Exception:
            pass

    return default


def get_app_data_path():
    """获取应用程序数据目录（用于存储配置、数据等）"""
    if getattr(sys, 'frozen', False):
        # 打包环境：使用exe所在目录下的data文件夹
        app_dir = os.path.dirname(sys.executable)
        data_dir = os.path.join(app_dir, 'data')
    else:
        # 开发环境：使用项目根目录下的data文件夹
        data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data')
    
    # 确保目录存在
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(os.path.join(data_dir, 'thumbnails'), exist_ok=True)
    
    return data_dir


def get_config_path():
    """获取配置文件目录"""
    if getattr(sys, 'frozen', False):
        # 打包环境：使用exe所在目录下的config文件夹
        app_dir = os.path.dirname(sys.executable)
        config_dir = os.path.join(app_dir, 'config')
    else:
        # 开发环境：使用项目根目录下的config文件夹
        config_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'config')
    
    # 确保目录存在
    os.makedirs(config_dir, exist_ok=True)
    
    return config_dir


def validate_file_path(path: str, max_length: int = MAX_PATH_LENGTH, allow_relative: bool = False) -> bool:
    """
    统一的文件路径验证函数
    
    验证内容包括：
    - 路径类型（必须是字符串）
    - 路径长度限制
    - 路径格式（空路径、非法字符等）
    - 是否为敏感路径
    
    Args:
        path: 要验证的文件路径
        max_length: 最大路径长度限制，默认260字符
        allow_relative: 是否允许相对路径，默认False
        
    Returns:
        bool: 验证通过返回True，否则返回False
    """
    # 验证路径类型
    if not isinstance(path, str):
        return False
    
    # 验证空路径
    if not path or not path.strip():
        return False
    
    path = path.strip()
    
    # 验证路径长度
    if len(path) > max_length:
        return False
    
    # 注意：不在这里检查命令注入字符，因为 & 等字符在Windows文件路径中是合法的
    # 命令注入检查应该在使用路径执行外部命令时进行
    
    # 检查是否为敏感路径
    if is_sensitive_path(path):
        return False
    
    # 验证路径格式
    try:
        normalized_path = os.path.normpath(path)
    except Exception:
        return False
    
    # 如果不允许相对路径，检查是否为绝对路径
    if not allow_relative:
        if not os.path.isabs(path):
            # Windows下检查是否包含盘符
            if sys.platform == 'win32':
                if len(path) < 2 or path[1] != ':':
                    return False
            else:
                return False
    
    # 检查路径遍历攻击特征
    if '..' in normalized_path.split(os.sep):
        # 允许在相对路径中使用..，但要检查是否在允许范围内
        try:
            abs_path = os.path.abspath(path)
            real_path = os.path.realpath(abs_path)
            if abs_path != real_path and not allow_relative:
                return False
        except Exception:
            return False
    
    return True


def validate_filename(filename: str, max_length: int = MAX_FILENAME_LENGTH, check_reserved: bool = True) -> bool:
    """
    文件名验证函数
    
    验证内容包括：
    - 非法字符检查（<>:"|?*）
    - Windows保留名检查（CON、NUL等）
    - 文件名长度限制（默认255字符）
    - 空文件名检查
    
    Args:
        filename: 要验证的文件名（不包含路径）
        max_length: 最大文件名长度限制，默认255字符
        check_reserved: 是否检查Windows保留名，默认True
        
    Returns:
        bool: 验证通过返回True，否则返回False
    """
    # 验证类型
    if not isinstance(filename, str):
        return False
    
    # 验证空文件名
    if not filename or not filename.strip():
        return False
    
    filename = filename.strip()
    
    # 验证长度限制
    if len(filename) > max_length:
        return False
    
    # 检查非法字符
    for char in ILLEGAL_FILENAME_CHARS:
        if char in filename:
            return False
    
    # 检查控制字符（0x00-0x1F和0x7F）
    for char in filename:
        code = ord(char)
        if code <= 0x1F or code == 0x7F:
            return False
    
    # 检查Windows保留名
    if check_reserved:
        # 获取文件名（不含扩展名）
        name_without_ext = os.path.splitext(filename)[0]
        if name_without_ext.upper() in WINDOWS_RESERVED_NAMES:
            return False
    
    # 检查文件名是否以空格或点结尾（Windows不允许）
    if filename.endswith(' ') or filename.endswith('.'):
        return False
    
    # 检查文件名是否以空格开头
    if filename.startswith(' '):
        return False
    
    return True


def validate_file_extension(filename: str, allowed_extensions: Optional[Set[str]] = None, case_sensitive: bool = False) -> bool:
    """
    文件扩展名验证函数
    
    验证文件扩展名是否在白名单中
    
    Args:
        filename: 要验证的文件名
        allowed_extensions: 允许的扩展名集合，默认使用DEFAULT_ALLOWED_EXTENSIONS
        case_sensitive: 是否区分大小写，默认False（不区分）
        
    Returns:
        bool: 验证通过返回True，否则返回False
    """
    if not isinstance(filename, str):
        return False
    
    if not filename.strip():
        return False
    
    # 使用默认白名单
    if allowed_extensions is None:
        allowed_extensions = DEFAULT_ALLOWED_EXTENSIONS
    
    # 获取扩展名
    ext = os.path.splitext(filename)[1]
    
    # 如果没有扩展名，根据需求决定是否允许
    if not ext:
        return False
    
    # 验证扩展名
    if case_sensitive:
        return ext in allowed_extensions
    else:
        return ext.lower() in (e.lower() for e in allowed_extensions)


def validate_numeric_range(value, min_value=None, max_value=None, allow_none: bool = False) -> bool:
    """
    数值输入验证函数
    
    验证数值是否在有效范围内
    
    Args:
        value: 要验证的数值
        min_value: 最小值限制，None表示无限制
        max_value: 最大值限制，None表示无限制
        allow_none: 是否允许None值，默认False
        
    Returns:
        bool: 验证通过返回True，否则返回False
    """
    # 处理None值
    if value is None:
        return allow_none
    
    # 验证是否为数值类型
    if not isinstance(value, (int, float)):
        try:
            # 尝试转换为浮点数
            float(value)
        except (ValueError, TypeError):
            return False
    
    # 转换为数值进行比较
    try:
        num_value = float(value)
    except (ValueError, TypeError):
        return False
    
    # 检查NaN和Infinity
    import math
    if math.isnan(num_value) or math.isinf(num_value):
        return False
    
    # 验证最小值
    if min_value is not None:
        try:
            if num_value < float(min_value):
                return False
        except (ValueError, TypeError):
            return False
    
    # 验证最大值
    if max_value is not None:
        try:
            if num_value > float(max_value):
                return False
        except (ValueError, TypeError):
            return False
    
    return True
