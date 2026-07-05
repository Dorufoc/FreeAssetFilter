#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试辅助工具函数
"""

import os
import time
from PySide6.QtCore import QTimer, QEventLoop, QObject
from PySide6.QtWidgets import QApplication


def create_temp_file(path, content=""):
    """
    在指定路径创建临时文件
    
    Args:
        path: 文件完整路径
        content: 文件内容
    
    Returns:
        str: 创建的文件路径
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def process_qt_events(qapp, ms=50):
    """
    处理 Qt 事件循环
    
    Args:
        qapp: QApplication 实例
        ms: 处理事件的毫秒数
    """
    if qapp:
        qapp.processEvents()
        QTimer.singleShot(ms, qapp.quit)
        qapp.exec()


def wait_for_signal(signal, timeout_ms=5000):
    """
    等待信号发射
    
    Args:
        signal: Qt 信号对象
        timeout_ms: 超时时间（毫秒）
    
    Returns:
        bool: 如果在超时前信号发射则返回 True，否则返回 False
    """
    result = {"emitted": False, "args": None}
    
    def on_signal(*args):
        result["emitted"] = True
        result["args"] = args
    
    signal.connect(on_signal)
    
    loop = QEventLoop()
    QTimer.singleShot(timeout_ms, loop.quit)
    
    # 当信号发射时退出事件循环
    signal.connect(loop.quit)
    
    loop.exec()
    
    signal.disconnect(on_signal)
    try:
        signal.disconnect(loop.quit)
    except RuntimeError:
        pass
    
    return result["emitted"], result["args"]


def mock_file_info(file_path, file_type="file", extra=None):
    """
    创建模拟的文件信息字典
    
    Args:
        file_path: 文件路径
        file_type: 文件类型（file, directory 等）
        extra: 额外的字段字典
    
    Returns:
        dict: 模拟的文件信息
    """
    if extra is None:
        extra = {}
    
    name = os.path.basename(file_path)
    _, extension = os.path.splitext(name)
    
    info = {
        "path": file_path,
        "name": name,
        "type": file_type,
        "extension": extension,
        "size": extra.pop("size", 0),
        "modified": extra.pop("modified", 0),
    }
    
    info.update(extra)
    return info
