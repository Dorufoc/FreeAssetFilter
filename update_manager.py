#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
项目远程更新管理模块
负责检查、下载和更新项目到最新版本
"""

import os
import sys
import re
import logging
import tempfile
import shutil
import zipfile
import requests
from datetime import datetime

# 配置日志
log_file = os.path.join(os.path.dirname(__file__), 'update.log')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# GitHub项目配置
GITHUB_USER = "Dorufoc"
GITHUB_REPO = "FreeAssetFilter"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}"
GITHUB_RELEASES_URL = f"{GITHUB_API_URL}/releases/latest"
GITHUB_ZIP_URL = f"https://github.com/{GITHUB_USER}/{GITHUB_REPO}/archive/refs/heads/main.zip"

# 忽略更新的文件列表
IGNORE_FILES = [
    ".git",
    ".gitignore",
    "update.log",
    "update_manager.py",
    "config.json",
    "user_data",
    "data"
]

# 版本号正则表达式
VERSION_PATTERN = r"v?([0-9]+(?:\.[0-9]+)*)"


def get_local_version():
    """
    从主程序文件中提取当前本地版本号
    
    Returns:
        str: 本地版本号，如 "1.0"
    """
    try:
        main_file = os.path.join(os.path.dirname(__file__), "main.py")
        with open(main_file, "r", encoding="utf-8") as f:
            content = f.read()
        
        # 从文件内容中提取版本号
        match = re.search(r"FreeAssetFilter v([0-9.]+)", content)
        if match:
            local_version = match.group(1)
            logger.info(f"获取到本地版本: {local_version}")
            return local_version
        else:
            logger.warning("无法从main.py中提取版本号，使用默认版本0.0.0")
            return "0.0.0"
    except Exception as e:
        logger.error(f"获取本地版本失败: {e}")
        return "0.0.0"


def get_latest_version():
    """
    从GitHub API获取最新版本号
    
    Returns:
        tuple: (最新版本号, 下载URL)
    """
    try:
        logger.info("正在从GitHub获取最新版本信息...")
        response = requests.get(GITHUB_RELEASES_URL, timeout=10)
        response.raise_for_status()
        
        release_info = response.json()
        latest_version = release_info.get("tag_name", "v0.0.0")
        # 提取纯版本号（去除v前缀）
        match = re.match(VERSION_PATTERN, latest_version)
        if match:
            latest_version = match.group(1)
        
        # 获取最新代码zip包URL
        download_url = GITHUB_ZIP_URL
        logger.info(f"获取到最新版本: {latest_version}, 下载URL: {download_url}")
        return latest_version, download_url
    except requests.exceptions.Timeout:
        logger.error("连接GitHub超时，请检查网络连接")
        return None, None
    except requests.exceptions.RequestException as e:
        logger.error(f"请求GitHub API失败: {e}")
        return None, None
    except Exception as e:
        logger.error(f"获取最新版本失败: {e}")
        return None, None


def version_compare(version1, version2):
    """
    比较两个版本号
    
    Args:
        version1: 版本号1
        version2: 版本号2
        
    Returns:
        int: 1(version1>version2), 0(相等), -1(version1<version2)
    """
    try:
        # 将版本号分割为数字列表
        v1 = list(map(int, version1.split(".")))
        v2 = list(map(int, version2.split(".")))
        
        # 补全长度
        max_len = max(len(v1), len(v2))
        v1 += [0] * (max_len - len(v1))
        v2 += [0] * (max_len - len(v2))
        
        # 逐位比较
        for i in range(max_len):
            if v1[i] > v2[i]:
                return 1
            elif v1[i] < v2[i]:
                return -1
        return 0
    except Exception as e:
        logger.error(f"版本比较失败: {e}")
        return 0


def check_update_available():
    """
    检查是否有更新可用
    
    Returns:
        tuple: (是否有更新, 本地版本, 最新版本, 下载URL)
    """
    local_version = get_local_version()
    latest_version, download_url = get_latest_version()
    
    if not latest_version:
        return False, local_version, None, None
    
    compare_result = version_compare(latest_version, local_version)
    if compare_result > 0:
        logger.info(f"发现新版本: {latest_version} (当前版本: {local_version})")
        return True, local_version, latest_version, download_url
    else:
        logger.info(f"当前已是最新版本: {local_version}")
        return False, local_version, latest_version, None


def download_file(url, save_path):
    """
    下载文件并显示进度
    
    Args:
        url: 文件下载URL
        save_path: 保存路径
        
    Returns:
        bool: 下载是否成功
    """
    try:
        logger.info(f"开始下载文件: {url} 到 {save_path}")
        
        with requests.get(url, stream=True, timeout=30) as response:
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded_size = 0
            
            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        
                        # 打印下载进度
                        if total_size > 0:
                            progress = (downloaded_size / total_size) * 100
                            sys.stdout.write(f"\r下载进度: {progress:.1f}% ({downloaded_size}/{total_size} bytes)")
                            sys.stdout.flush()
        
        sys.stdout.write("\n")
        logger.info(f"文件下载成功: {save_path}")
        return True
    except requests.exceptions.Timeout:
        logger.error("文件下载超时")
        return False
    except requests.exceptions.RequestException as e:
        logger.error(f"文件下载失败: {e}")
        return False
    except Exception as e:
        logger.error(f"文件下载过程中发生错误: {e}")
        return False


def is_ignore_file(file_path):
    """
    判断文件是否需要忽略更新
    
    Args:
        file_path: 文件路径
        
    Returns:
        bool: 是否忽略
    """
    for ignore in IGNORE_FILES:
        if file_path == ignore or file_path.startswith(f"{ignore}/"):
            return True
    return False


def update_files(source_dir, target_dir):
    """
    将源目录中的文件更新到目标目录
    
    Args:
        source_dir: 源目录（解压后的最新代码）
        target_dir: 目标目录（当前项目目录）
        
    Returns:
        bool: 更新是否成功
    """
    try:
        # 遍历源目录
        for root, dirs, files in os.walk(source_dir):
            # 计算相对路径
            relative_path = os.path.relpath(root, source_dir)
            if relative_path == ".":
                relative_path = ""
            
            # 跳过根目录下的.git目录
            if relative_path.startswith(".git"):
                continue
            
            # 创建目标目录
            target_root = os.path.join(target_dir, relative_path)
            if not os.path.exists(target_root):
                os.makedirs(target_root)
            
            # 处理文件
            for file in files:
                source_file = os.path.join(root, file)
                # 计算相对文件路径
                relative_file_path = os.path.join(relative_path, file) if relative_path else file
                
                # 检查是否需要忽略
                if is_ignore_file(relative_file_path):
                    logger.info(f"忽略文件: {relative_file_path}")
                    continue
                
                # 目标文件路径
                target_file = os.path.join(target_dir, relative_file_path)
                
                # 备份旧文件
                backup_file = f"{target_file}.bak"
                if os.path.exists(target_file):
                    shutil.copy2(target_file, backup_file)
                    logger.info(f"已备份文件: {target_file} -> {backup_file}")
                
                # 复制新文件
                shutil.copy2(source_file, target_file)
                logger.info(f"已更新文件: {target_file}")
        
        return True
    except Exception as e:
        logger.error(f"更新文件失败: {e}")
        return False


def clean_backup_files(target_dir):
    """
    清理备份文件
    
    Args:
        target_dir: 目标目录
    """
    try:
        for root, dirs, files in os.walk(target_dir):
            for file in files:
                if file.endswith(".bak"):
                    backup_file = os.path.join(root, file)
                    os.remove(backup_file)
                    logger.info(f"已清理备份文件: {backup_file}")
    except Exception as e:
        logger.error(f"清理备份文件失败: {e}")


def run_update():
    """
    执行完整的更新流程
    
    Returns:
        bool: 更新是否成功
    """
    logger.info("="*60)
    logger.info("开始执行FreeAssetFilter更新流程")
    logger.info(f"更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("="*60)
    
    try:
        # 1. 检查是否有更新
        update_available, local_version, latest_version, download_url = check_update_available()
        
        if not update_available:
            logger.info("当前已是最新版本，无需更新")
            return True
        
        logger.info(f"发现新版本: {latest_version}，当前版本: {local_version}")
        
        # 2. 创建临时目录
        temp_dir = tempfile.mkdtemp()
        logger.info(f"创建临时目录: {temp_dir}")
        
        try:
            # 3. 下载最新代码
            zip_file = os.path.join(temp_dir, f"{GITHUB_REPO}-main.zip")
            if not download_file(download_url, zip_file):
                logger.error("下载最新代码失败")
                return False
            
            # 4. 解压zip文件
            extract_dir = os.path.join(temp_dir, "extract")
            os.makedirs(extract_dir, exist_ok=True)
            
            with zipfile.ZipFile(zip_file, "r") as zip_ref:
                zip_ref.extractall(extract_dir)
            logger.info(f"解压文件成功到: {extract_dir}")
            
            # 5. 找到解压后的主目录（GitHub zip会包含repo名称和分支名）
            extracted_folders = os.listdir(extract_dir)
            if not extracted_folders:
                logger.error("解压后的目录为空")
                return False
            
            source_dir = os.path.join(extract_dir, extracted_folders[0])
            logger.info(f"找到源代码目录: {source_dir}")
            
            # 6. 更新文件
            target_dir = os.path.dirname(__file__)
            if not update_files(source_dir, target_dir):
                logger.error("更新文件失败")
                return False
            
            # 7. 清理临时文件
            shutil.rmtree(temp_dir)
            logger.info(f"已清理临时目录: {temp_dir}")
            
            logger.info("="*60)
            logger.info("更新完成！")
            logger.info(f"当前版本已更新至: {latest_version}")
            logger.info("="*60)
            
            return True
        except Exception as e:
            logger.error(f"更新过程中发生错误: {e}")
            # 清理临时文件
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            return False
    except Exception as e:
        logger.error(f"更新流程启动失败: {e}")
        return False


if __name__ == "__main__":
    """
    主程序入口，直接运行时执行更新流程
    """
    logger.info("\n\n启动FreeAssetFilter更新管理器")
    logger.info("="*60)
    
    success = run_update()
    
    if success:
        print("\n更新成功！")
        print("请重新启动程序以应用更新。")
    else:
        print("\n更新失败，请查看update.log获取详细信息。")
    
    input("\n按Enter键退出...")
