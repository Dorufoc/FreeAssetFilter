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
import logging
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

from freeassetfilter.utils.path_utils import get_app_data_path


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
        
        # 设置日志格式
        self.formatter = logging.Formatter(
            '[%(asctime)s] [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # 添加文件处理器
        self._add_file_handler()
        
        # 添加控制台处理器（如果可用）
        self._add_console_handler()
        
        # 清理旧日志文件
        self._cleanup_old_logs()
        
        AppLogger._initialized = True
        
    def _get_log_dir(self):
        """获取日志目录路径"""
        app_data_path = get_app_data_path()
        return os.path.join(app_data_path, 'logs')
    
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
            self.logger.addHandler(file_handler)
        except (OSError, IOError, PermissionError, FileNotFoundError) as e:
            # 如果文件日志创建失败，使用备用方案
            print(f"[警告] 创建日志文件失败 - 文件操作错误: {e}", file=sys.__stderr__ if sys.__stderr__ else None)
        except (ValueError, TypeError) as e:
            # 如果文件日志创建失败，使用备用方案
            print(f"[警告] 创建日志文件失败 - 数据转换错误: {e}", file=sys.__stderr__ if sys.__stderr__ else None)
    
    def _add_console_handler(self):
        """添加控制台日志处理器（仅在控制台可用时）"""
        # 检查 stdout 和 stderr 是否可用
        if sys.stdout is not None and sys.stderr is not None:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(logging.DEBUG)
            console_handler.setFormatter(self.formatter)
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
                    print(f"[警告] 删除旧日志文件失败 - 文件操作错误: {e}", file=sys.__stderr__ if sys.__stderr__ else None)
        except (OSError, IOError, PermissionError, FileNotFoundError) as e:
            print(f"[警告] 清理旧日志文件失败 - 文件操作错误: {e}", file=sys.__stderr__ if sys.__stderr__ else None)
        except (ValueError, TypeError) as e:
            print(f"[警告] 清理旧日志文件失败 - 数据转换错误: {e}", file=sys.__stderr__ if sys.__stderr__ else None)
    
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


def log_print(msg, level='info'):
    """
    兼容 print 的日志输出函数
    
    Args:
        msg: 日志消息
        level: 日志级别，可选 'debug', 'info', 'warning', 'error', 'critical'
    """
    logger = get_logger()
    
    # 同时尝试 print（如果控制台可用）
    if sys.stdout is not None:
        try:
            print(msg)
        except (OSError, IOError, PermissionError, FileNotFoundError) as e:
            # 控制台输出失败，静默处理（已在日志中记录）
            pass
        except (ValueError, TypeError) as e:
            # 控制台输出失败，静默处理（已在日志中记录）
            pass
    
    # 写入日志文件
    level_map = {
        'debug': logger.debug,
        'info': logger.info,
        'warning': logger.warning,
        'error': logger.error,
        'critical': logger.critical
    }
    
    log_func = level_map.get(level, logger.info)
    log_func(msg)


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
    
    # 记录到日志
    logger.error(error_msg)
    
    # 同时尝试输出到控制台（如果可用）
    if sys.stderr is not None:
        try:
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
        except (OSError, IOError, PermissionError, FileNotFoundError) as e:
            # 控制台异常输出失败，静默处理（已在日志中记录）
            pass
        except (ValueError, TypeError) as e:
            # 控制台异常输出失败，静默处理（已在日志中记录）
            pass


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
