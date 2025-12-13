#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
模拟网络文件读取延迟的测试脚本
用于测试网络文件预览功能
"""

import os
import time
import threading
from PyQt5.QtCore import QThread, pyqtSignal

class MockNetworkFileReader:
    """
    模拟网络文件读取器，添加延迟以模拟网络文件读取
    """
    
    def __init__(self, file_path, delay_ms=50):
        """
        初始化模拟网络文件读取器
        
        Args:
            file_path (str): 实际文件路径
            delay_ms (int): 每次读取的延迟时间（毫秒）
        """
        self.file_path = file_path
        self.delay_ms = delay_ms
        self.is_cancelled = False
    
    def read_with_progress(self, callback=None):
        """
        模拟网络文件读取，带进度回调
        
        Args:
            callback (function): 进度回调函数，参数：(progress, status)
        
        Returns:
            str: 文件内容
        """
        try:
            # 获取文件大小
            file_size = os.path.getsize(self.file_path)
            
            if callback:
                callback(0, "正在获取文件信息...")
            
            # 模拟网络延迟
            time.sleep(0.5)
            
            if callback:
                callback(5, "正在打开文件...")
            
            # 模拟网络延迟
            time.sleep(0.5)
            
            # 读取文件内容，添加延迟
            chunk_size = 65536  # 64KB
            read_bytes = 0
            content = []
            
            with open(self.file_path, 'rb') as f:
                while not self.is_cancelled:
                    # 读取数据
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    
                    # 模拟网络延迟
                    time.sleep(self.delay_ms / 1000)
                    
                    # 更新进度
                    read_bytes += len(chunk)
                    progress = 5 + int(min(95, (read_bytes / file_size) * 95))
                    
                    if callback:
                        callback(progress, f"正在读取文件... {progress}%")
                    
                    # 添加到内容
                    content.append(chunk)
            
            if self.is_cancelled:
                return None
            
            if callback:
                callback(100, "文件读取完成")
            
            # 合并内容并解码
            return b''.join(content).decode('utf-8')
        except Exception as e:
            if callback:
                callback(-1, f"读取失败: {str(e)}")
            raise
    
    def cancel(self):
        """
        取消读取操作
        """
        self.is_cancelled = True

# 测试用例
if __name__ == "__main__":
    def progress_callback(progress, status):
        print(f"进度: {progress}%, 状态: {status}")
    
    # 创建测试文件
    test_file = "test_large_file.txt"
    if not os.path.exists(test_file):
        print(f"测试文件 {test_file} 不存在，请先运行 create_large_file.py")
        exit(1)
    
    # 测试模拟网络文件读取
    reader = MockNetworkFileReader(test_file, delay_ms=10)
    
    # 启动读取线程
    def test_read():
        try:
            content = reader.read_with_progress(progress_callback)
            if content:
                print(f"读取完成，内容长度: {len(content)} 字符")
        except Exception as e:
            print(f"读取失败: {str(e)}")
    
    thread = threading.Thread(target=test_read)
    thread.daemon = True
    thread.start()
    
    # 运行5秒后取消
    time.sleep(5)
    print("\n取消读取操作...")
    reader.cancel()
    thread.join()
    print("测试完成")
