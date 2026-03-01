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
import logging
import traceback
from datetime import datetime
from pathlib import Path

from freeassetfilter.utils.path_utils import get_app_data_path


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
        except Exception as e:
            # 如果文件日志创建失败，使用备用方案
            print(f"[警告] 创建日志文件失败: {e}", file=sys.__stderr__ if sys.__stderr__ else None)
    
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
                except Exception:
                    pass
        except Exception:
            pass
    
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
        except Exception:
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
    
    # 构建异常信息
    error_msg = f"\n=== 检测到未捕获的异常 ===\n"
    error_msg += f"异常类型: {exc_type.__name__}\n"
    error_msg += f"异常值: {exc_value}\n"
    error_msg += f"异常堆栈:\n"
    
    # 获取堆栈跟踪字符串
    stack_trace = ''.join(traceback.format_tb(exc_traceback))
    error_msg += stack_trace
    error_msg += "==========================\n"
    
    # 记录到日志
    logger.error(error_msg)
    
    # 同时尝试输出到控制台（如果可用）
    if sys.stderr is not None:
        try:
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
        except Exception:
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
