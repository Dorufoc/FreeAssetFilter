#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 缩略图缓存清理模块
用于自动清除超过限制数量的缩略图缓存文件
"""

import os
import threading
import time
import hashlib
from concurrent.futures import ThreadPoolExecutor

__all__ = ['ThumbnailCleaner']

class ThumbnailCleaner:
    """
    缩略图缓存清理器
    用于管理和清理缩略图缓存，确保缓存文件数量不超过设定的限制
    """
    
    def __init__(self, max_cache_size=2000, max_threads=10):
        """
        初始化缩略图清理器
        
        Args:
            max_cache_size (int): 缓存文件的最大数量，超过此数量将触发清理
            max_threads (int): 清理时使用的最大线程数
        """
        self.max_cache_size = max_cache_size
        self.max_threads = max_threads
        self.thumbnails_dir = self._get_thumbnails_dir()
    
    def _get_thumbnails_dir(self):
        """
        获取缩略图缓存目录路径
        
        Returns:
            str: 缩略图缓存目录的绝对路径
        """
        # 获取项目根目录
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        # 构建缩略图缓存目录路径
        thumbnails_dir = os.path.join(project_root, "data", "thumbnails")
        # 确保目录存在
        os.makedirs(thumbnails_dir, exist_ok=True)
        return thumbnails_dir
    
    def _get_all_thumbnail_files(self):
        """
        获取所有缩略图文件及其创建时间
        
        Returns:
            list: 包含(文件路径, 创建时间)元组的列表
        """
        thumbnail_files = []
        
        try:
            # 遍历缩略图目录
            for filename in os.listdir(self.thumbnails_dir):
                if filename.endswith('.png'):
                    file_path = os.path.join(self.thumbnails_dir, filename)
                    try:
                        # 获取文件的创建时间（或修改时间，如果创建时间不可用）
                        ctime = os.path.getctime(file_path)
                        thumbnail_files.append((file_path, ctime))
                    except Exception:
                        # 忽略无法访问的文件
                        continue
        except Exception:
            # 忽略目录访问错误
            pass
        
        return thumbnail_files
    
    def _delete_file(self, file_path):
        """
        删除单个文件的线程安全方法
        
        Args:
            file_path (str): 要删除的文件路径
        """
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                return True
        except Exception:
            # 忽略删除错误
            pass
        return False
    
    def clean_thumbnails(self, cleanup_period_days=None):
        """
        清理缩略图缓存，删除超过最大数量的旧文件
        
        Args:
            cleanup_period_days (int, optional): 缓存清理周期（天），如果提供，则删除超过此天数的文件
            
        Returns:
            tuple: (删除的文件数量, 剩余的文件数量)
        """
        # 获取所有缩略图文件及其创建时间
        thumbnail_files = self._get_all_thumbnail_files()
        total_files = len(thumbnail_files)
        
        # 需要删除的文件路径列表
        files_to_delete_paths = []
        
        if cleanup_period_days:
            # 基于时间的清理：删除超过指定天数的文件
            current_time = time.time()
            cutoff_time = current_time - (cleanup_period_days * 86400)  # 86400秒 = 1天
            
            for file_path, ctime in thumbnail_files:
                if ctime < cutoff_time:
                    files_to_delete_paths.append(file_path)
        else:
            # 基于数量的清理：删除超过最大数量的旧文件
            if total_files <= self.max_cache_size:
                return 0, total_files
            
            # 需要删除的文件数量
            files_to_delete = total_files - self.max_cache_size
            
            # 按创建时间排序（旧文件在前）
            thumbnail_files.sort(key=lambda x: x[1])
            
            # 选择要删除的文件
            files_to_delete_paths = [file_path for file_path, _ in thumbnail_files[:files_to_delete]]
        
        # 使用线程池快速删除文件
        deleted_count = 0
        
        if files_to_delete_paths:
            with ThreadPoolExecutor(max_workers=self.max_threads) as executor:
                # 提交所有删除任务
                results = list(executor.map(self._delete_file, files_to_delete_paths))
                # 统计成功删除的数量
                deleted_count = sum(results)
        
        return deleted_count, total_files - deleted_count
    
    def is_thumbnail_exists(self, file_path):
        """
        检查指定文件的缩略图是否存在
        
        Args:
            file_path (str): 原始文件路径
        
        Returns:
            bool: 如果缩略图存在返回True，否则返回False
        """
        # 计算缩略图文件名
        md5_hash = hashlib.md5(file_path.encode('utf-8'))
        file_hash = md5_hash.hexdigest()[:16]
        thumbnail_path = os.path.join(self.thumbnails_dir, f"{file_hash}.png")
        
        return os.path.exists(thumbnail_path)
    
    def get_thumbnail_path(self, file_path):
        """
        获取指定文件的缩略图路径
        
        Args:
            file_path (str): 原始文件路径
        
        Returns:
            str: 缩略图文件路径
        """
        # 计算缩略图文件名
        md5_hash = hashlib.md5(file_path.encode('utf-8'))
        file_hash = md5_hash.hexdigest()[:16]
        thumbnail_path = os.path.join(self.thumbnails_dir, f"{file_hash}.png")
        
        return thumbnail_path
    
    def get_cache_statistics(self):
        """
        获取缓存统计信息
        
        Returns:
            dict: 包含缓存统计信息的字典
        """
        thumbnail_files = self._get_all_thumbnail_files()
        total_files = len(thumbnail_files)
        
        if total_files == 0:
            return {
                "total_files": 0,
                "max_files": self.max_cache_size,
                "usage_percentage": 0,
                "oldest_file_time": None,
                "newest_file_time": None
            }
        
        # 计算最旧和最新文件的时间
        ctimes = [ctime for _, ctime in thumbnail_files]
        oldest_time = min(ctimes)
        newest_time = max(ctimes)
        
        # 计算使用百分比
        usage_percentage = (total_files / self.max_cache_size) * 100 if self.max_cache_size > 0 else 0
        
        return {
            "total_files": total_files,
            "max_files": self.max_cache_size,
            "usage_percentage": usage_percentage,
            "oldest_file_time": oldest_time,
            "newest_file_time": newest_time
        }


# 单例模式实现
_thumbnail_cleaner_instance = None
_thumbnail_cleaner_lock = threading.Lock()

def get_thumbnail_cleaner(max_cache_size=2000, max_threads=10):
    """
    获取缩略图清理器的单例实例
    
    Args:
        max_cache_size (int): 缓存文件的最大数量
        max_threads (int): 清理时使用的最大线程数
    
    Returns:
        ThumbnailCleaner: 缩略图清理器实例
    """
    global _thumbnail_cleaner_instance
    
    with _thumbnail_cleaner_lock:
        if _thumbnail_cleaner_instance is None:
            _thumbnail_cleaner_instance = ThumbnailCleaner(max_cache_size, max_threads)
    
    return _thumbnail_cleaner_instance
