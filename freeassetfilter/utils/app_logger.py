#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

应用程序日志模块
解决无控制台模式下(windows exe) print输出被丢弃的问题
将日志同时输出到文件和控制台（如果可用）
"""

import sys
import os
import re
import io
import atexit
import logging
import traceback
import inspect
import platform
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from freeassetfilter.utils.path_utils import get_app_data_path


# ==================== 系统信息收集 ====================

def _get_windows_version() -> str:
    """
    通过 RtlGetVersion API 获取 Windows 版本信息
    该 API 不受兼容性模式影响，比 WMI 更可靠
    
    Returns:
        str: 格式化的 Windows 版本字符串
    """
    try:
        import ctypes
        from ctypes import wintypes

        class OSVERSIONINFOEXW(ctypes.Structure):
            _fields_ = [
                ("dwOSVersionInfoSize", wintypes.DWORD),
                ("dwMajorVersion", wintypes.DWORD),
                ("dwMinorVersion", wintypes.DWORD),
                ("dwBuildNumber", wintypes.DWORD),
                ("dwPlatformId", wintypes.DWORD),
                ("szCSDVersion", wintypes.WCHAR * 128),
                ("wServicePackMajor", wintypes.WORD),
                ("wServicePackMinor", wintypes.WORD),
                ("wSuiteMask", wintypes.WORD),
                ("wProductType", wintypes.BYTE),
                ("wReserved", wintypes.BYTE),
            ]

        os_info = OSVERSIONINFOEXW()
        os_info.dwOSVersionInfoSize = ctypes.sizeof(OSVERSIONINFOEXW)

        ntdll = ctypes.windll.ntdll
        status = ntdll.RtlGetVersion(ctypes.byref(os_info))

        if status == 0:  # STATUS_SUCCESS
            # 根据版本号识别 Windows 版本名称
            version_name = "Windows"
            major = os_info.dwMajorVersion
            minor = os_info.dwMinorVersion

            if major == 10 and minor == 0:
                if os_info.dwBuildNumber >= 22000:
                    version_name = "Windows 11"
                else:
                    version_name = "Windows 10"
            elif major == 6 and minor == 3:
                version_name = "Windows 8.1"
            elif major == 6 and minor == 2:
                version_name = "Windows 8"
            elif major == 6 and minor == 1:
                version_name = "Windows 7"
            elif major == 6 and minor == 0:
                version_name = "Windows Vista"

            return f"{version_name} (Build {os_info.dwBuildNumber})"
    except Exception:
        pass
    return ""


def _get_memory_info() -> str:
    """
    通过 GlobalMemoryStatusEx API 获取物理内存信息
    
    Returns:
        str: 格式化的内存容量字符串
    """
    try:
        import ctypes
        from ctypes import wintypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", wintypes.DWORD),
                ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        mem_status = MEMORYSTATUSEX()
        mem_status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)

        kernel32 = ctypes.windll.kernel32
        if kernel32.GlobalMemoryStatusEx(ctypes.byref(mem_status)):
            total_gb = mem_status.ullTotalPhys / (1024 ** 3)
            return f"{total_gb:.2f} GB"
    except Exception:
        pass
    return ""


def _get_cpu_info_from_registry() -> str:
    """
    通过注册表获取 CPU 名称
    
    Returns:
        str: CPU 名称
    """
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        ) as key:
            cpu_name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            return cpu_name.strip()
    except Exception:
        pass
    return ""


def _get_gpu_info_from_registry() -> str:
    """
    通过注册表获取显卡信息

    Returns:
        str: 显卡名称列表
    """
    gpus = []

    # 强显卡标识（必须包含其中一个）
    GPU_KEYWORDS_STRONG = ['NVIDIA', 'AMD', 'RADEON', 'GEFORCE', 'RTX', 'GTX', 'ARC', 'QUADRO', 'TESLA']
    # 弱显卡标识（需要配合其他显卡相关词）
    GPU_KEYWORDS_WEAK = ['INTEL']
    # 显卡辅助词（配合弱标识使用）
    GPU_HELPERS = ['GRAPHICS', 'IRIS', 'XE', 'UHD', 'HD', 'ARC', 'GPU']
    # 需要排除的非显卡设备关键词
    EXCLUDE_KEYWORDS = ['USB', 'AUDIO', 'NETWORK', 'ETHERNET', 'WIFI', 'WI-FI', 'BLUETOOTH',
                       'HOST', 'HUB', 'SATA', 'NVME', 'SSD',
                       'CAMERA', 'MICROPHONE', 'SPEAKER', 'TOUCHPAD', 'KEYBOARD', 'MOUSE']

    def is_valid_gpu(name: str) -> bool:
        """检查是否为有效的显卡名称"""
        name_upper = name.upper()

        # 不能包含排除关键词
        has_exclude = any(kw in name_upper for kw in EXCLUDE_KEYWORDS)
        if has_exclude:
            return False

        # 检查强显卡标识
        has_strong = any(kw in name_upper for kw in GPU_KEYWORDS_STRONG)
        if has_strong:
            return True

        # 检查弱显卡标识 + 辅助词
        has_weak = any(kw in name_upper for kw in GPU_KEYWORDS_WEAK)
        has_helper = any(kw in name_upper for kw in GPU_HELPERS)
        if has_weak and has_helper:
            return True

        return False

    def clean_gpu_name(name: str) -> str:
        """清理显卡名称，移除 INF 文件引用格式"""
        # 处理 @oem123.inf,%xxx%;Name 格式
        if ';' in name:
            parts = name.split(';')
            # 取最后一部分（实际名称）
            name = parts[-1].strip()
        # 移除残留的 %xxx% 变量
        import re
        name = re.sub(r'%[^%]+%', '', name)
        # 清理多余的空格
        name = ' '.join(name.split())
        return name.strip()

    try:
        import winreg

        # 方法1: 从 Enum\PCI 键获取显卡信息
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Enum\PCI"
            ) as pci_key:
                index = 0
                while True:
                    try:
                        device_id = winreg.EnumKey(pci_key, index)

                        with winreg.OpenKey(pci_key, device_id) as dev_key:
                            sub_index = 0
                            while True:
                                try:
                                    sub_id = winreg.EnumKey(dev_key, sub_index)
                                    full_path = f"SYSTEM\\CurrentControlSet\\Enum\\PCI\\{device_id}\\{sub_id}"

                                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, full_path) as sub_key:
                                        try:
                                            # 优先读取 FriendlyName
                                            try:
                                                friendly_name, _ = winreg.QueryValueEx(sub_key, "FriendlyName")
                                                name = friendly_name.strip()
                                            except FileNotFoundError:
                                                #  fallback 到 DeviceDesc
                                                device_desc, _ = winreg.QueryValueEx(sub_key, "DeviceDesc")
                                                name = device_desc.strip()

                                            if name and is_valid_gpu(name):
                                                cleaned = clean_gpu_name(name)
                                                if cleaned:
                                                    gpus.append(cleaned)
                                        except FileNotFoundError:
                                            pass
                                    sub_index += 1
                                except OSError:
                                    break
                        index += 1
                    except OSError:
                        break
        except Exception:
            pass

        # 方法2: 从 Control\Video\{GUID}\Video 获取活跃显卡
        if not gpus:
            try:
                with winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SYSTEM\CurrentControlSet\Control\Video"
                ) as video_key:
                    index = 0
                    while True:
                        try:
                            guid = winreg.EnumKey(video_key, index)
                            video_sub_path = f"SYSTEM\\CurrentControlSet\\Control\\Video\\{guid}\\Video"

                            try:
                                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, video_sub_path) as sub_key:
                                    try:
                                        device_desc, _ = winreg.QueryValueEx(sub_key, "DeviceDesc")
                                        if device_desc:
                                            desc = device_desc.strip()
                                            if is_valid_gpu(desc):
                                                cleaned = clean_gpu_name(desc)
                                                if cleaned:
                                                    gpus.append(cleaned)
                                    except FileNotFoundError:
                                        pass
                            except FileNotFoundError:
                                pass
                            index += 1
                        except OSError:
                            break
            except Exception:
                pass

    except Exception:
        pass

    # 去重并返回
    if gpus:
        seen = set()
        unique_gpus = []
        for gpu in gpus:
            # 简化名称用于去重判断（移除常见厂商名和空格）
            simple = gpu.upper()
            for word in ['NVIDIA', 'AMD', 'INTEL', 'CORPORATION', 'GRAPHICS', '  ']:
                simple = simple.replace(word, ' ')
            simple = simple.strip().replace(' ', '')

            if simple not in seen:
                seen.add(simple)
                unique_gpus.append(gpu)

        return ", ".join(unique_gpus[:2])  # 最多显示2个显卡

    return ""


def _get_system_info_native() -> Dict[str, Any]:
    """
    通过 Windows API 和注册表获取系统硬件信息
    绕过 WMI，避免 OEM 系统对 WMI 的屏蔽或魔改
    
    Returns:
        Dict[str, Any]: 包含 CPU、显卡、内存等信息的字典
    """
    info = {}

    # 获取操作系统版本
    os_version = _get_windows_version()
    if os_version:
        info['os'] = os_version

    # 获取内存信息
    memory = _get_memory_info()
    if memory:
        info['memory'] = memory

    # 获取 CPU 信息
    cpu = _get_cpu_info_from_registry()
    if cpu:
        info['cpu'] = cpu

    # 获取显卡信息
    gpu = _get_gpu_info_from_registry()
    if gpu:
        info['gpu'] = gpu

    return info


def _get_system_info() -> Dict[str, Any]:
    """
    获取系统信息的综合函数
    优先使用 Windows API 和注册表方式，绕过 WMI 避免 OEM 系统限制
    
    Returns:
        Dict[str, Any]: 包含所有系统信息的字典
    """
    info = {}

    # 获取 Python 环境信息
    try:
        info['python_version'] = platform.python_version()
        info['python_implementation'] = platform.python_implementation()
        info['architecture'] = platform.architecture()[0]
    except Exception:
        pass

    # 第1层：使用 Windows API 和注册表获取系统信息（最可靠）
    try:
        native_info = _get_system_info_native()
        info.update(native_info)
    except Exception:
        pass

    # 第2层：兜底方案 - 使用 platform 模块
    if 'os' not in info or not info['os']:
        try:
            info['os'] = f"{platform.system()} {platform.release()}"
        except Exception:
            info['os'] = "未知"

    if 'cpu' not in info or not info['cpu']:
        try:
            cpu_name = platform.processor()
            info['cpu'] = cpu_name if cpu_name else "未知"
        except Exception:
            info['cpu'] = "未知"

    if 'memory' not in info or not info['memory']:
        info['memory'] = "未知"

    if 'gpu' not in info or not info['gpu']:
        info['gpu'] = "未知"

    return info


def _get_app_info() -> Dict[str, Any]:
    """
    获取应用程序信息（版本、安装路径等）
    
    Returns:
        Dict[str, Any]: 应用程序信息字典
    """
    info = {}
    
    try:
        if getattr(sys, 'frozen', False):
            install_path = os.path.dirname(sys.executable)
        else:
            current_file = os.path.abspath(__file__)
            install_path = os.path.dirname(os.path.dirname(os.path.dirname(current_file)))
        info['install_path'] = install_path
    except Exception:
        try:
            info['install_path'] = os.path.abspath(".")
        except Exception:
            info['install_path'] = "未知路径"
    
    try:
        version_file = os.path.join(info['install_path'], 'FAFVERSION')
        if os.path.exists(version_file):
            with open(version_file, 'r', encoding='utf-8') as f:
                lines = [line.strip() for line in f.readlines() if line.strip()]
            if lines:
                info['version'] = lines[0]
            else:
                info['version'] = "未知版本"
        else:
            info['version'] = "未知版本"
    except Exception:
        info['version'] = "未知版本"
    
    return info


# ==================== 组件来源追踪 ====================

# 标记是否正在输出启动信息
_in_startup_log = False

def _get_caller_filename() -> str:
    """
    获取调用日志函数的文件名
    
    Returns:
        str: 调用者文件名（不含路径）
    """
    global _in_startup_log
    
    if _in_startup_log:
        return 'app_logger'
    
    try:
        # 获取当前调用栈
        stack = inspect.stack()
        
        # 跳过的文件名模式列表
        skip_patterns = ['app_logger.py', '__init__.py']
        
        # 查找第一个不在跳过列表中的调用者
        for frame_info in stack:
            filename = frame_info.filename
            basename = os.path.basename(filename)
            
            # 检查是否需要跳过该文件
            should_skip = False
            for pattern in skip_patterns:
                if pattern in basename:
                    should_skip = True
                    break
            
            if not should_skip:
                # 获取文件名（不含扩展名）
                name, _ = os.path.splitext(basename)
                return name
    except (IndexError, AttributeError):
        pass
    return 'unknown'


class ComponentSourceFilter(logging.Filter):
    """
    日志过滤器，自动添加组件来源信息到日志记录中
    """
    
    def filter(self, record: logging.LogRecord) -> bool:
        """
        在日志记录中添加组件来源信息
        
        Args:
            record: 日志记录对象
            
        Returns:
            bool: 始终返回True，表示继续处理日志
        """
        # 获取调用者文件名
        record.source_file = _get_caller_filename()
        return True


class ComponentSourceFormatter(logging.Formatter):
    """
    自定义日志格式化器，支持组件来源信息
    """
    
    def format(self, record: logging.LogRecord) -> str:
        """
        格式化日志记录，包含组件来源信息
        
        Args:
            record: 日志记录对象
            
        Returns:
            str: 格式化后的日志字符串
        """
        # 如果没有source_file属性，添加一个默认值
        if not hasattr(record, 'source_file'):
            record.source_file = 'unknown'
        formatted = super().format(record)
        formatted = sanitize_path(formatted)
        formatted = sanitize_sensitive_info(formatted)
        return formatted


# ==================== 异常类型分类 ====================

class SecurityException(Exception):
    """安全相关异常基类"""
    pass


class ResourceException(Exception):
    """资源相关异常基类"""
    pass


class FileOperationException(ResourceException):
    """文件操作异常（文件不存在、读写失败、格式错误等）"""
    def __init__(self, message: str = "文件操作失败", original_error: Optional[Exception] = None):
        self.original_error = original_error
        super().__init__(message)


class NetworkException(ResourceException):
    """网络相关异常（连接失败、超时、下载失败等）"""
    def __init__(self, message: str = "网络操作失败", original_error: Optional[Exception] = None):
        self.original_error = original_error
        super().__init__(message)


class MemoryException(ResourceException):
    """内存相关异常（内存不足、分配失败等）"""
    def __init__(self, message: str = "内存操作失败", original_error: Optional[Exception] = None):
        self.original_error = original_error
        super().__init__(message)


class PermissionException(SecurityException):
    """权限相关异常（访问被拒绝、权限不足等）"""
    def __init__(self, message: str = "权限不足", original_error: Optional[Exception] = None):
        self.original_error = original_error
        super().__init__(message)


class ConfigurationException(Exception):
    """配置相关异常"""
    def __init__(self, message: str = "配置错误", original_error: Optional[Exception] = None):
        self.original_error = original_error
        super().__init__(message)


# ==================== 敏感信息过滤 ====================

# 敏感路径模式列表
SENSITIVE_PATH_PATTERNS = [
    # Windows 用户目录
    (r'[A-Za-z]:\\Users\\[^\\]+', '[USER_HOME]'),
    (r'[A-Za-z]:\\[^\\]+\\AppData\\', '[APP_DATA]'),
    # Windows 系统目录
    (r'[A-Za-z]:\\Windows\\[^\\]+', '[SYSTEM]'),
    (r'[A-Za-z]:\\Program Files[^\\]*\\[^\\]+', '[PROGRAM]'),
    # Linux/Mac 用户目录
    (r'/home/[^/]+', '[USER_HOME]'),
    (r'/Users/[^/]+', '[USER_HOME]'),
    # 绝对路径前缀
    (r'[A-Za-z]:\\', '[DRIVE]'),
]

# 敏感信息模式（密码、密钥、令牌等）
SENSITIVE_INFO_PATTERNS = [
    (r'password\s*=\s*[^\s,;]+', 'password=[REDACTED]'),
    (r'passwd\s*=\s*[^\s,;]+', 'passwd=[REDACTED]'),
    (r'pwd\s*=\s*[^\s,;]+', 'pwd=[REDACTED]'),
    (r'secret\s*=\s*[^\s,;]+', 'secret=[REDACTED]'),
    (r'token\s*=\s*[^\s,;]+', 'token=[REDACTED]'),
    (r'api[_-]?key\s*=\s*[^\s,;]+', 'api_key=[REDACTED]'),
    (r'key\s*=\s*[^\s,;]+', 'key=[REDACTED]'),
    (r'auth\s*=\s*[^\s,;]+', 'auth=[REDACTED]'),
    (r'credential\s*=\s*[^\s,;]+', 'credential=[REDACTED]'),
    (r'private[_-]?key\s*=\s*[^\s,;]+', 'private_key=[REDACTED]'),
    (r'jwt[_-]?token\s*=\s*[^\s,;]+', 'jwt_token=[REDACTED]'),
    (r'jwt\s*=\s*[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', 'jwt=[REDACTED]'),
    (r'eyJ[A-Za-z0-9_-]*\.eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]*', '[JWT_TOKEN_REDACTED]'),
    (r'oauth[_-]?token\s*=\s*[^\s,;]+', 'oauth_token=[REDACTED]'),
    (r'access[_-]?token\s*=\s*[^\s,;]+', 'access_token=[REDACTED]'),
    (r'refresh[_-]?token\s*=\s*[^\s,;]+', 'refresh_token=[REDACTED]'),
    (r'aws[_-]?access[_-]?key[_-]?id\s*=\s*[^\s,;]+', 'aws_access_key_id=[REDACTED]'),
    (r'aws[_-]?secret[_-]?access[_-]?key\s*=\s*[^\s,;]+', 'aws_secret_access_key=[REDACTED]'),
    (r'aws[_-]?key\s*=\s*[^\s,;]+', 'aws_key=[REDACTED]'),
    (r'AKIA[A-Z0-9]{16}', '[AWS_ACCESS_KEY_REDACTED]'),
    (r'-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----', '-----BEGIN PRIVATE KEY [REDACTED]-----'),
    (r'-----END\s+(?:RSA\s+)?PRIVATE\s+KEY-----', '-----END PRIVATE KEY-----'),
    (r'authorization\s*:\s*bearer\s+[^\s,;]+', 'authorization: bearer [REDACTED]'),
    (r'bearer\s+[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', 'bearer [REDACTED]'),
]


def sanitize_path(path: str) -> str:
    """
    清理路径中的敏感信息
    
    Args:
        path: 原始路径
        
    Returns:
        str: 清理后的安全路径
    """
    if not path or not isinstance(path, str):
        return path
    
    sanitized = path
    for pattern, replacement in SENSITIVE_PATH_PATTERNS:
        sanitized = re.sub(pattern, replacement, sanitized, flags=re.IGNORECASE)
    
    return sanitized


def sanitize_sensitive_info(text: str) -> str:
    """
    清理文本中的敏感信息（密码、密钥等）
    
    Args:
        text: 原始文本
        
    Returns:
        str: 清理后的安全文本
    """
    if not text or not isinstance(text, str):
        return text
    
    sanitized = text
    for pattern_item in SENSITIVE_INFO_PATTERNS:
        if len(pattern_item) == 3:
            pattern, replacement, flags = pattern_item
            sanitized = re.sub(pattern, replacement, sanitized, flags=flags)
        else:
            pattern, replacement = pattern_item
            sanitized = re.sub(pattern, replacement, sanitized, flags=re.IGNORECASE)
    
    return sanitized


def get_safe_error_message(error: Exception, include_details: bool = False) -> str:
    """
    获取安全的错误信息（不包含敏感路径）
    
    Args:
        error: 异常对象
        include_details: 是否包含详细错误信息（默认False，只返回安全信息）
        
    Returns:
        str: 安全的错误信息
    """
    if error is None:
        return "发生未知错误"
    
    # 获取异常类型名称
    error_type = type(error).__name__
    
    # 获取异常消息并清理
    error_msg = str(error)
    safe_msg = sanitize_path(error_msg)
    safe_msg = sanitize_sensitive_info(safe_msg)
    
    # 根据异常类型返回用户友好的消息
    user_friendly_messages = {
        'FileNotFoundError': '文件未找到',
        'PermissionError': '权限不足，无法访问',
        'IsADirectoryError': '路径指向目录而非文件',
        'NotADirectoryError': '路径不是有效的目录',
        'OSError': '系统操作失败',
        'IOError': '输入/输出错误',
        'MemoryError': '内存不足',
        'TimeoutError': '操作超时',
        'ConnectionError': '网络连接失败',
        'FileOperationException': '文件操作失败',
        'NetworkException': '网络操作失败',
        'MemoryException': '内存操作失败',
        'PermissionException': '权限不足',
        'ConfigurationException': '配置错误',
    }
    
    base_message = user_friendly_messages.get(error_type, '操作失败')
    
    if include_details and safe_msg:
        return f"{base_message}: {safe_msg}"
    
    return base_message


def get_safe_error_for_ui(error: Exception) -> str:
    """
    获取用于UI显示的安全错误信息（最简版本，绝不包含任何敏感信息）
    
    Args:
        error: 异常对象
        
    Returns:
        str: 安全的错误信息，适合显示给用户
    """
    if error is None:
        return "操作失败，请重试"
    
    # 只返回预定义的友好消息，不包含任何原始错误信息
    error_type = type(error).__name__
    
    ui_messages = {
        'FileNotFoundError': '文件未找到，请检查文件是否存在',
        'PermissionError': '权限不足，无法访问该文件',
        'IsADirectoryError': '选择的对象是文件夹而非文件',
        'NotADirectoryError': '无效的路径',
        'OSError': '系统操作失败，请检查磁盘空间或文件权限',
        'IOError': '读取/写入失败，请检查文件是否被占用',
        'MemoryError': '内存不足，请关闭其他程序后重试',
        'TimeoutError': '操作超时，请检查网络连接后重试',
        'ConnectionError': '网络连接失败，请检查网络设置',
        'FileExistsError': '文件已存在',
        'FileOperationException': '文件处理失败',
        'NetworkException': '网络操作失败',
        'MemoryException': '内存不足',
        'PermissionException': '权限不足',
        'ConfigurationException': '配置错误',
        'ValueError': '参数错误',
        'TypeError': '类型错误',
        'KeyError': '数据缺失',
        'IndexError': '索引越界',
        'AttributeError': '属性错误',
        'RuntimeError': '运行时错误',
    }
    
    return ui_messages.get(error_type, '操作失败，请重试')


def classify_exception(error: Exception) -> type:
    """
    根据异常类型分类异常
    
    Args:
        error: 异常对象
        
    Returns:
        type: 异常分类类型
    """
    if error is None:
        return Exception
    
    error_type = type(error)
    error_name = error_type.__name__
    
    # 文件相关异常
    file_exceptions = (
        FileNotFoundError, PermissionError, IsADirectoryError, 
        NotADirectoryError, FileExistsError, EOFError,
        'FileOperationException'
    )
    if error_type in file_exceptions or error_name in file_exceptions:
        return FileOperationException
    
    # 权限相关异常
    if error_type == PermissionError or error_name == 'PermissionException':
        return PermissionException
    
    # 网络相关异常
    network_exceptions = (
        ConnectionError, TimeoutError, BlockingIOError, 
        InterruptedError, 'NetworkException'
    )
    if error_type in network_exceptions or error_name in network_exceptions:
        return NetworkException
    
    # 内存相关异常
    memory_exceptions = (MemoryError, 'MemoryException')
    if error_type in memory_exceptions or error_name in memory_exceptions:
        return MemoryException
    
    return Exception


class TeeStream(io.TextIOBase):
    """
    将文本同时写入原始控制台流和日志文件的简单双写流。
    用于捕获 print/sys.stdout.write/sys.stderr.write/traceback.print_exc 等输出。
    """

    def __init__(self, original_stream, log_file_path: str, encoding: str = 'utf-8'):
        self.original_stream = original_stream
        self.log_file_path = log_file_path
        self.encoding_name = encoding or 'utf-8'
        self._log_stream = None
        self._closed = False

        try:
            log_dir = os.path.dirname(log_file_path)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            self._log_stream = open(log_file_path, 'a', encoding=self.encoding_name, buffering=1)
        except (OSError, IOError, PermissionError, FileNotFoundError, ValueError, TypeError):
            self._log_stream = None

    @property
    def encoding(self):
        return getattr(self.original_stream, 'encoding', None) or self.encoding_name

    @property
    def closed(self):
        original_closed = False
        try:
            original_closed = bool(getattr(self.original_stream, 'closed', False))
        except (AttributeError, ValueError):
            original_closed = False
        return self._closed or original_closed

    def writable(self):
        return True

    def isatty(self):
        try:
            return bool(self.original_stream and self.original_stream.isatty())
        except (AttributeError, OSError, ValueError):
            return False

    def fileno(self):
        if self.original_stream is None:
            raise OSError("Underlying stream is unavailable")
        return self.original_stream.fileno()

    def write(self, s):
        if s is None:
            return 0

        if not isinstance(s, str):
            s = str(s)

        written = 0

        if self.original_stream is not None:
            try:
                written = self.original_stream.write(s)
            except (OSError, IOError, ValueError, TypeError):
                written = 0

        if self._log_stream is not None:
            try:
                self._log_stream.write(s)
            except (OSError, IOError, ValueError, TypeError):
                pass

        return written if written is not None else len(s)

    def flush(self):
        if self.original_stream is not None:
            try:
                self.original_stream.flush()
            except (OSError, IOError, ValueError, TypeError):
                pass

        if self._log_stream is not None:
            try:
                self._log_stream.flush()
            except (OSError, IOError, ValueError, TypeError):
                pass

    def close(self):
        if self._closed:
            return

        self.flush()

        if self._log_stream is not None:
            try:
                self._log_stream.close()
            except (OSError, IOError, ValueError, TypeError):
                pass

        self._closed = True

    def __getattr__(self, item):
        if self.original_stream is not None:
            return getattr(self.original_stream, item)
        raise AttributeError(item)


def _get_original_console_stream(stream_name: str):
    """
    获取原始控制台流，优先使用 sys.__stdout__/sys.__stderr__，
    避免 logger 的控制台 handler 被 stdout/stderr tee 再次写入日志文件。
    """
    original_name = f"__{stream_name}__"
    original_stream = getattr(sys, original_name, None)
    current_stream = getattr(sys, stream_name, None)

    for stream in (original_stream, current_stream):
        if stream is None:
            continue

        try:
            if stream.closed:
                continue
        except (AttributeError, ValueError):
            pass

        return stream

    return None


def _write_bootstrap_fallback(message: str) -> None:
    """
    在日志系统尚未可用时，使用最小能力写入原始 stderr。

    注意：
    - 该函数仅允许在统一日志组件内部使用
    - 项目其他模块不得直接 print / sys.stderr.write 输出日志
    """
    if message is None:
        return

    if not isinstance(message, str):
        message = str(message)

    safe_message = sanitize_path(message)
    safe_message = sanitize_sensitive_info(safe_message)

    fallback_stream = getattr(sys, "__stderr__", None) or getattr(sys, "stderr", None)
    if fallback_stream is None:
        return

    try:
        fallback_stream.write(f"{safe_message}\n")
        fallback_stream.flush()
    except (OSError, IOError, ValueError, TypeError, AttributeError):
        pass


class AppLogger:
    """
    应用程序日志管理器
    
    功能：
    - 在无控制台模式下将日志写入文件
    - 在有控制台时同时输出到控制台
    - 支持日志级别控制
    - 自动处理日志文件轮转
    """
    
    _instance = None
    _initialized = False
    
    def __new__(cls, *args, **kwargs):
        """单例模式，确保只有一个日志实例"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, log_level=logging.DEBUG, max_log_files=5):
        """
        初始化日志管理器
        
        Args:
            log_level: 日志级别，默认为 DEBUG
            max_log_files: 保留的最大日志文件数量
        """
        # 避免重复初始化
        if AppLogger._initialized:
            return
            
        self.logger = logging.getLogger("FreeAssetFilter")
        self.logger.setLevel(log_level)
        self.logger.handlers = []  # 清除已有处理器
        
        self.max_log_files = max_log_files
        self.log_dir = self._get_log_dir()
        
        # 确保日志目录存在
        os.makedirs(self.log_dir, exist_ok=True)
        
        # 创建日志文件路径
        self.log_file = self._create_log_file()
        
        # 设置日志格式 - 包含组件来源信息
        self.formatter = ComponentSourceFormatter(
            '[%(asctime)s] [%(levelname)s] [%(source_file)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # 创建组件来源过滤器
        self.component_filter = ComponentSourceFilter()
        
        # 添加文件处理器
        self._add_file_handler()
        
        # 添加控制台处理器（如果可用）
        self._add_console_handler()
        
        # 清理旧日志文件
        self._cleanup_old_logs()
        
        AppLogger._initialized = True
        
        # 输出初始化信息
        self._log_startup_info()
        
    def _get_log_dir(self):
        """获取日志目录路径"""
        try:
            if getattr(sys, 'frozen', False):
                app_dir = os.path.dirname(sys.executable)
                data_dir = os.path.join(app_dir, 'data')
            else:
                data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data')
            return os.path.join(data_dir, 'logs')
        except Exception:
            return os.path.join(os.path.abspath('.'), 'data', 'logs')
    
    def _create_log_file(self):
        """创建日志文件路径，使用时间戳命名"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        return os.path.join(self.log_dir, f'app_{timestamp}.log')
    
    def _add_file_handler(self):
        """添加文件日志处理器"""
        try:
            file_handler = logging.FileHandler(
                self.log_file, 
                encoding='utf-8',
                mode='a'
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(self.formatter)
            # 添加组件来源过滤器
            file_handler.addFilter(self.component_filter)
            self.logger.addHandler(file_handler)
        except (OSError, IOError, PermissionError, FileNotFoundError) as e:
            # 如果文件日志创建失败，使用统一日志组件内部兜底方案
            _write_bootstrap_fallback(f"[警告] 创建日志文件失败 - 文件操作错误: {e}")
        except (ValueError, TypeError) as e:
            # 如果文件日志创建失败，使用统一日志组件内部兜底方案
            _write_bootstrap_fallback(f"[警告] 创建日志文件失败 - 数据转换错误: {e}")
    
    def _add_console_handler(self):
        """添加控制台日志处理器（仅在控制台可用时）"""
        console_stream = _get_original_console_stream('stdout')
        if console_stream is not None:
            console_handler = logging.StreamHandler(console_stream)
            console_handler.setLevel(logging.DEBUG)
            console_handler.setFormatter(self.formatter)
            # 添加组件来源过滤器
            console_handler.addFilter(self.component_filter)
            self.logger.addHandler(console_handler)
    
    def _cleanup_old_logs(self):
        """清理旧的日志文件，只保留最新的 max_log_files 个"""
        try:
            log_files = [
                f for f in os.listdir(self.log_dir) 
                if f.startswith('app_') and f.endswith('.log')
            ]
            # 按修改时间排序
            log_files.sort(key=lambda f: os.path.getmtime(
                os.path.join(self.log_dir, f)
            ), reverse=True)
            
            # 删除旧文件
            for old_file in log_files[self.max_log_files:]:
                try:
                    os.remove(os.path.join(self.log_dir, old_file))
                except (OSError, IOError, PermissionError, FileNotFoundError) as e:
                    _write_bootstrap_fallback(f"[警告] 删除旧日志文件失败 - 文件操作错误: {e}")
        except (OSError, IOError, PermissionError, FileNotFoundError) as e:
            _write_bootstrap_fallback(f"[警告] 清理旧日志文件失败 - 文件操作错误: {e}")
        except (ValueError, TypeError) as e:
            _write_bootstrap_fallback(f"[警告] 清理旧日志文件失败 - 数据转换错误: {e}")
    
    def debug(self, msg):
        """输出调试日志"""
        self.logger.debug(msg)
    
    def info(self, msg):
        """输出信息日志"""
        self.logger.info(msg)
    
    def warning(self, msg):
        """输出警告日志"""
        self.logger.warning(msg)
    
    def error(self, msg):
        """输出错误日志"""
        self.logger.error(msg)
    
    def critical(self, msg):
        """输出严重错误日志"""
        self.logger.critical(msg)
    
    def exception(self, msg):
        """输出异常信息，包含堆栈跟踪"""
        self.logger.exception(msg)
    
    def get_log_file_path(self):
        """获取当前日志文件路径"""
        return self.log_file
    
    def _log_startup_info(self):
        """输出启动信息到日志"""
        global _in_startup_log
        try:
            app_info = _get_app_info()
            system_info = _get_system_info()
            
            # 标记为启动日志
            _in_startup_log = True
            
            self.info("=" * 60)
            self.info("FreeAssetFilter 启动")
            self.info("=" * 60)
            
            self.info(f"应用版本: {app_info.get('version', '未知')}")
            self.info(f"安装路径: {app_info.get('install_path', '未知')}")
            self.info(f"日志文件: {self.log_file}")
            
            self.info("-" * 60)
            self.info("系统信息:")
            self.info(f"  操作系统: {system_info.get('os', '未知')}")
            self.info(f"  CPU: {system_info.get('cpu', '未知')}")
            self.info(f"  显卡: {system_info.get('gpu', '未知')}")
            self.info(f"  内存: {system_info.get('memory', '未知')}")
            self.info(f"  架构: {system_info.get('architecture', '未知')}")
            self.info(f"  Python: {system_info.get('python_version', '未知')} ({system_info.get('python_implementation', '未知')})")
            
            self.info("=" * 60)
        except Exception as e:
            try:
                self.warning(f"输出启动信息失败: {e}")
            except Exception:
                pass
        finally:
            # 恢复正常状态
            _in_startup_log = False


# 全局日志实例
_app_logger = None


def get_logger():
    """
    获取日志管理器实例
    
    Returns:
        AppLogger: 日志管理器实例
    """
    global _app_logger
    if _app_logger is None:
        _app_logger = AppLogger()
    return _app_logger


def install_console_capture(log_file_path: Optional[str] = None) -> bool:
    """
    将 sys.stdout / sys.stderr 替换为双写流：
    - 有控制台时保留原始控制台输出
    - 同时把所有标准输出和标准错误写入日志文件

    Args:
        log_file_path: 日志文件路径，未提供时使用当前 logger 的日志文件

    Returns:
        bool: 是否至少成功安装了一个 tee 流
    """
    logger = get_logger()

    if not log_file_path:
        try:
            log_file_path = logger.get_log_file_path()
        except (AttributeError, OSError, IOError, PermissionError, FileNotFoundError, ValueError, TypeError):
            return False

    installed = False

    original_stdout = _get_original_console_stream('stdout')
    if not isinstance(sys.stdout, TeeStream):
        try:
            sys.stdout = TeeStream(original_stdout, log_file_path)
            installed = True
        except (OSError, IOError, PermissionError, FileNotFoundError, ValueError, TypeError):
            pass

    original_stderr = _get_original_console_stream('stderr')
    if not isinstance(sys.stderr, TeeStream):
        try:
            sys.stderr = TeeStream(original_stderr, log_file_path)
            installed = True
        except (OSError, IOError, PermissionError, FileNotFoundError, ValueError, TypeError):
            pass

    if installed:
        def _cleanup_stream(stream):
            if isinstance(stream, TeeStream):
                try:
                    stream.flush()
                except (OSError, IOError, ValueError, TypeError):
                    pass

        atexit.register(lambda: _cleanup_stream(sys.stdout))
        atexit.register(lambda: _cleanup_stream(sys.stderr))

    return installed


def log_print(msg, level='info'):
    """
    兼容 print 的日志输出函数

    Args:
        msg: 日志消息
        level: 日志级别，可选 'debug', 'info', 'warning', 'error', 'critical'
    """
    logger = get_logger()

    level_map = {
        'debug': logger.debug,
        'info': logger.info,
        'warning': logger.warning,
        'error': logger.error,
        'critical': logger.critical
    }

    log_func = level_map.get(level, logger.info)
    log_func(msg)


def log_exception_details(message: str, exc: Optional[BaseException] = None, level: str = 'error'):
    """
    通过统一日志组件记录异常详情和堆栈，替代 traceback.print_exc() / logging.exception()。

    Args:
        message: 上下文消息
        exc: 异常对象；未提供时尝试读取当前异常上下文
        level: 日志级别，可选 'debug', 'info', 'warning', 'error', 'critical'
    """
    logger = get_logger()

    safe_message = sanitize_path(str(message))
    safe_message = sanitize_sensitive_info(safe_message)

    active_exc = exc
    if active_exc is None:
        active_exc = sys.exc_info()[1]

    if active_exc is None:
        log_print(safe_message, level=level)
        return

    safe_exc_text = sanitize_path(str(active_exc))
    safe_exc_text = sanitize_sensitive_info(safe_exc_text)

    trace_text = ''.join(
        traceback.format_exception(type(active_exc), active_exc, active_exc.__traceback__)
    )
    safe_trace_text = sanitize_path(trace_text)
    safe_trace_text = sanitize_sensitive_info(safe_trace_text)

    full_message = (
        f"{safe_message}\n"
        f"异常类型: {type(active_exc).__name__}\n"
        f"异常信息: {safe_exc_text}\n"
        f"异常堆栈:\n{safe_trace_text}"
    )

    level_map = {
        'debug': logger.debug,
        'info': logger.info,
        'warning': logger.warning,
        'error': logger.error,
        'critical': logger.critical
    }
    log_func = level_map.get(level, logger.error)
    log_func(full_message)


def log_exception(exc_type, exc_value, exc_traceback):
    """
    记录未捕获的异常
    
    Args:
        exc_type: 异常类型
        exc_value: 异常值
        exc_traceback: 异常回溯信息
    """
    logger = get_logger()
    
    # 过滤异常值中的敏感信息
    safe_exc_value = sanitize_path(str(exc_value))
    safe_exc_value = sanitize_sensitive_info(safe_exc_value)
    
    # 构建异常信息
    error_msg = f"\n=== 检测到未捕获的异常 ===\n"
    error_msg += f"异常类型: {exc_type.__name__}\n"
    error_msg += f"异常值: {safe_exc_value}\n"
    error_msg += f"异常堆栈:\n"
    
    # 获取堆栈跟踪字符串并过滤敏感信息
    stack_trace = ''.join(traceback.format_tb(exc_traceback))
    safe_stack_trace = sanitize_path(stack_trace)
    safe_stack_trace = sanitize_sensitive_info(safe_stack_trace)
    error_msg += safe_stack_trace
    error_msg += "==========================\n"
    
    # 记录到日志。
    # 不再主动调用 sys.__excepthook__，避免在 stderr 已经被双写到日志文件时产生重复记录。
    logger.error(error_msg)


# 便捷的日志函数
def debug(msg):
    """输出调试日志"""
    get_logger().debug(msg)


def info(msg):
    """输出信息日志"""
    get_logger().info(msg)


def warning(msg):
    """输出警告日志"""
    get_logger().warning(msg)


def error(msg):
    """输出错误日志"""
    get_logger().error(msg)


def critical(msg):
    """输出严重错误日志"""
    get_logger().critical(msg)


def exception_details(message: str, exc: Optional[BaseException] = None, level: str = 'error'):
    """便捷函数：通过统一日志组件记录异常详情和堆栈。"""
    log_exception_details(message, exc=exc, level=level)
