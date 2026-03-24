#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

7z 压缩包处理核心模块
使用 7z.exe 命令行工具处理所有压缩格式
"""

import os
import sys
import subprocess
import re
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from pathlib import Path

# 导入日志模块
from freeassetfilter.utils.app_logger import info, debug, warning, error
from freeassetfilter.utils.path_utils import validate_safe_path, contains_injection_chars


class Py7zCore:
    """
    7z 压缩包处理核心类
    使用 7z.exe 命令行工具统一处理所有压缩格式
    """

    # 默认命令超时时间（秒）
    DEFAULT_COMMAND_TIMEOUT = 60

    # 安全限制常量
    MAX_ARCHIVE_FILES = 10000  # 压缩包内最大文件数量
    MAX_NESTED_DEPTH = 5       # 嵌套压缩包最大递归深度

    def __init__(self, command_timeout: int = None):
        """
        初始化 7z 核心模块

        Args:
            command_timeout: 命令执行超时时间（秒），默认60秒
        """
        self._7z_exe_path = None
        self._command_timeout = command_timeout or self.DEFAULT_COMMAND_TIMEOUT
        self._find_7z_exe()

    def _find_7z_exe(self) -> str:
        """
        查找 7z.exe 的路径

        Returns:
            str: 7z.exe 的完整路径

        Raises:
            FileNotFoundError: 如果找不到 7z.exe
        """
        if self._7z_exe_path and os.path.exists(self._7z_exe_path):
            return self._7z_exe_path

        # 可能的 7z.exe 路径列表
        possible_paths = []

        # 1. 首先检查项目 core/7z 目录
        current_file = os.path.abspath(__file__)
        core_dir = os.path.dirname(current_file)
        project_7z_path = os.path.join(core_dir, "7z", "7z.exe")
        possible_paths.append(project_7z_path)

        # 2. 检查系统 PATH 中的 7z
        possible_paths.extend([
            "7z.exe",
            "7z",
        ])

        # 3. 检查常见的 7-Zip 安装路径
        program_files_paths = [
            os.path.expandvars(r"%ProgramFiles%\7-Zip\7z.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\7-Zip\7z.exe"),
            r"C:\Program Files\7-Zip\7z.exe",
            r"C:\Program Files (x86)\7-Zip\7z.exe",
        ]
        possible_paths.extend(program_files_paths)

        # 查找第一个存在的路径
        for path in possible_paths:
            try:
                if os.path.exists(path):
                    self._7z_exe_path = path
                    debug(f"找到 7z.exe: {path}")
                    return path
            except Exception:
                continue

        # 如果都找不到，尝试使用 where 命令
        try:
            result = subprocess.run(
                ["where", "7z.exe"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                path = result.stdout.strip().split('\n')[0].strip()
                if os.path.exists(path):
                    self._7z_exe_path = path
                    debug(f"通过 where 命令找到 7z.exe: {path}")
                    return path
        except Exception as e:
            debug(f"使用 where 命令查找 7z.exe 失败: {e}")

        error("找不到 7z.exe，请确保 7-Zip 已安装或在项目 core/7z 目录中")
        raise FileNotFoundError("找不到 7z.exe，请确保 7-Zip 已安装")

    def _run_7z_command(self, args: List[str], encoding: str = "utf-8", timeout: int = None) -> Tuple[int, str, str]:
        """
        运行 7z 命令（带超时控制）

        Args:
            args: 命令参数列表
            encoding: 输出编码
            timeout: 命令执行超时时间（秒），默认使用实例配置

        Returns:
            Tuple[int, str, str]: (返回码, 标准输出, 标准错误)
        """
        for arg in args:
            if contains_injection_chars(arg):
                error(f"检测到命令注入风险，拒绝执行: {arg}")
                return -1, "", "检测到命令注入风险"

        cmd = [self._7z_exe_path] + args
        debug(f"执行 7z 命令: {' '.join(cmd)}")

        # 使用指定的超时时间或实例默认值
        actual_timeout = timeout if timeout is not None else self._command_timeout

        try:
            # 对于 UTF-16 编码，不使用 text=True，而是手动解码
            if encoding.lower() in ['utf-16', 'utf-16le', 'utf-16be']:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=actual_timeout
                )
                # 手动处理 UTF-16 解码
                try:
                    if encoding.lower() == 'utf-16':
                        stdout = result.stdout.decode('utf-16', errors='replace')
                        stderr = result.stderr.decode('utf-16', errors='replace')
                    elif encoding.lower() == 'utf-16le':
                        stdout = result.stdout.decode('utf-16le', errors='replace')
                        stderr = result.stderr.decode('utf-16le', errors='replace')
                    else:  # utf-16be
                        stdout = result.stdout.decode('utf-16be', errors='replace')
                        stderr = result.stderr.decode('utf-16be', errors='replace')
                except Exception as decode_err:
                    debug(f"UTF-16 解码失败，尝试使用默认编码: {decode_err}")
                    stdout = result.stdout.decode('utf-8', errors='replace')
                    stderr = result.stderr.decode('utf-8', errors='replace')
                return result.returncode, stdout, stderr
            else:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding=encoding,
                    errors="replace",
                    timeout=actual_timeout
                )
                return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            error(f"7z 命令执行超时（{actual_timeout}秒）")
            return -1, "", f"命令执行超时（{actual_timeout}秒）"
        except Exception as e:
            error(f"执行 7z 命令失败: {e}")
            return -1, "", str(e)

    def _detect_encoding_from_output(self, output: str, requested_encoding: str) -> str:
        """
        从 7z 输出中检测编码
        通过检查是否有 UTF8 特性标记来判断

        Args:
            output: 7z 命令输出
            requested_encoding: 用户请求的编码

        Returns:
            str: 检测到的编码
        """
        # 如果用户明确指定了非 UTF-8 编码，尊重用户选择
        if requested_encoding.lower() not in ['utf-8', 'utf8']:
            return requested_encoding

        # 查找是否有 UTF8 标记
        # 如果文件有 Characteristics = UTF8，说明使用 UTF-8 编码
        # 否则可能是 GBK/CP936

        # 检查输出中是否有乱码字符（替换字符）
        replacement_count = output.count('\ufffd')  # � 字符

        # 如果有替换字符，说明 UTF-8 解码失败，尝试 GBK
        if replacement_count > 0:
            debug(f"检测到 {replacement_count} 个乱码字符，尝试使用 GBK 编码")
            return "gbk"

        return "utf-8"

    def list_archive(
        self,
        archive_path: str,
        current_path: str = "",
        encoding: str = "utf-8",
        nested_depth: int = 0
    ) -> List[Dict]:
        """
        列出压缩包内容

        Args:
            archive_path: 压缩包文件路径
            current_path: 当前浏览路径（用于显示子目录内容）
            encoding: 文件名字符编码
            nested_depth: 当前嵌套深度（用于递归调用时限制深度）

        Returns:
            List[Dict]: 文件和目录列表，每个元素包含:
                - name: 文件名
                - path: 完整路径
                - is_dir: 是否为目录
                - size: 文件大小（字节）
                - modified: 修改时间（ISO 格式字符串）
                - suffix: 文件后缀（小写，不含点）
        """
        # 验证路径安全
        try:
            archive_path = validate_safe_path(archive_path)
        except ValueError as e:
            error(f"路径验证失败: {e}")
            return []

        if not os.path.exists(archive_path):
            error(f"压缩包不存在: {archive_path}")
            return []

        # 检查嵌套深度限制
        if nested_depth >= self.MAX_NESTED_DEPTH:
            warning(f"嵌套压缩包深度超过限制 ({self.MAX_NESTED_DEPTH}层)，跳过: {archive_path}")
            return []

        # 使用 7z l 命令列出内容
        # -slt 参数表示以技术模式输出（包含详细信息）
        args = ["l", "-slt", archive_path]

        returncode, stdout, stderr = self._run_7z_command(args, encoding)

        if returncode != 0:
            error(f"列出压缩包内容失败: {stderr}")
            return []

        # 检测编码问题，如果有乱码则重新使用 GBK
        detected_encoding = self._detect_encoding_from_output(stdout, encoding)
        if detected_encoding != encoding:
            debug(f"检测到编码问题，重新使用 {detected_encoding} 编码")
            returncode, stdout, stderr = self._run_7z_command(args, detected_encoding)
            if returncode != 0:
                error(f"列出压缩包内容失败: {stderr}")
                return []

        # 解析输出
        files = self._parse_list_output(stdout, current_path, archive_path)

        # 检查文件数量限制
        if len(files) > self.MAX_ARCHIVE_FILES:
            warning(f"压缩包内文件数量 ({len(files)}) 超过限制 ({self.MAX_ARCHIVE_FILES})，截断处理: {archive_path}")
            files = files[:self.MAX_ARCHIVE_FILES]

        return files

    def _parse_list_output(self, output: str, current_path: str, archive_path: str = "") -> List[Dict]:
        """
        解析 7z l -slt 命令的输出

        Args:
            output: 7z 命令的输出文本
            current_path: 当前浏览路径
            archive_path: 压缩包路径（用于排除压缩包本身）

        Returns:
            List[Dict]: 解析后的文件列表
        """
        files = []
        dirs = set()

        # 获取压缩包文件名（用于排除）
        archive_name = os.path.basename(archive_path) if archive_path else ""

        # 将 current_path 中的正斜杠统一转换为反斜杠（用于匹配 7z 输出）
        current_path_normalized = current_path.replace('/', '\\') if current_path else ""

        # 分割成各个文件块
        # 每个文件块以 "Path = " 开头，以空行或下一个 "Path = " 结束
        # 限制最大文件块数量以防止ReDoS攻击
        blocks = re.split(r'\n(?=Path = )', output, maxsplit=self.MAX_ARCHIVE_FILES)

        for block in blocks:
            block = block.strip()
            if not block or not block.startswith("Path = "):
                continue

            if len(files) >= self.MAX_ARCHIVE_FILES:
                debug(f"已达到文件数量限制 ({self.MAX_ARCHIVE_FILES})，停止解析")
                break

            file_info = self._parse_file_block(block)
            if not file_info:
                continue

            file_path = file_info.get("path", "")
            if not file_path:
                continue

            # 跳过压缩包本身（7z 输出包含完整路径）
            if file_path == archive_path:
                continue

            # 跳过隐藏文件
            basename = os.path.basename(file_path.rstrip('\\/'))
            if basename.startswith('.'):
                continue

            # 检查是否在当前路径下
            if current_path_normalized:
                if not file_path.startswith(current_path_normalized + '\\'):
                    continue
                # 获取相对路径
                rel_path = file_path[len(current_path_normalized) + 1:]
            else:
                rel_path = file_path

            # 跳过空路径
            if not rel_path:
                continue

            # 将反斜杠转换为正斜杠（统一使用正斜杠作为内部路径分隔符）
            rel_path_normalized = rel_path.replace('\\', '/')
            file_path_normalized = file_path.replace('\\', '/')

            # 检查是否是当前路径下的直接子项
            if '\\' in rel_path or '/' in rel_path:
                # 是子目录下的文件，只添加目录
                sub_dir = rel_path_normalized.split('/')[0]
                if sub_dir and sub_dir not in dirs:
                    dirs.add(sub_dir)
                    files.append({
                        "name": sub_dir,
                        "path": f"{current_path}/{sub_dir}" if current_path else sub_dir,
                        "is_dir": True,
                        "size": 0,
                        "modified": "",
                        "suffix": ""
                    })
            else:
                # 是当前目录下的文件
                is_dir = file_info.get("is_dir", False)
                if is_dir:
                    dirs.add(rel_path_normalized)
                    files.append({
                        "name": rel_path_normalized,
                        "path": file_path_normalized,
                        "is_dir": True,
                        "size": 0,
                        "modified": "",
                        "suffix": ""
                    })
                else:
                    files.append({
                        "name": rel_path_normalized,
                        "path": file_path_normalized,
                        "is_dir": False,
                        "size": file_info.get("size", 0),
                        "modified": file_info.get("modified", ""),
                        "suffix": os.path.splitext(rel_path_normalized)[1].lower()[1:] if '.' in rel_path_normalized else ''
                    })

        # 去重并排序（目录在前，按名称排序）
        unique_files = {}
        for file in files:
            unique_files[file["name"]] = file

        return sorted(unique_files.values(), key=lambda x: (not x["is_dir"], x["name"].lower()))

    def _parse_file_block(self, block: str) -> Optional[Dict]:
        """
        解析单个文件信息块

        Args:
            block: 文件信息文本块

        Returns:
            Optional[Dict]: 文件信息字典，解析失败返回 None
        """
        info_dict = {}

        # 提取 Path - 使用非贪婪匹配和行限制防止回溯攻击
        path_match = re.search(r'^Path = ([^\n]+)$', block, re.MULTILINE)
        if not path_match:
            return None
        info_dict["path"] = path_match.group(1).strip()

        # 提取 Size
        size_match = re.search(r'^Size = (\d+)$', block, re.MULTILINE)
        if size_match:
            info_dict["size"] = int(size_match.group(1))
        else:
            info_dict["size"] = 0

        # 提取 Modified 时间 - 使用行限制防止回溯攻击
        modified_match = re.search(r'^Modified = ([^\n]+)$', block, re.MULTILINE)
        if modified_match:
            modified_str = modified_match.group(1).strip()
            try:
                # 7z 输出的时间格式: 2023-01-15 10:30:00
                dt = datetime.strptime(modified_str, "%Y-%m-%d %H:%M:%S")
                info_dict["modified"] = dt.isoformat()
            except ValueError:
                info_dict["modified"] = ""
        else:
            info_dict["modified"] = ""

        # 判断是否为目录
        # 7z 输出中，目录的 Size 通常为 0，且 Attributes 包含 D
        attr_match = re.search(r'^Attributes = ([^\n]+)$', block, re.MULTILINE)
        if attr_match:
            attrs = attr_match.group(1).strip()
            info_dict["is_dir"] = 'D' in attrs
        else:
            # 如果没有 Attributes，通过路径末尾的 / 判断
            info_dict["is_dir"] = info_dict["path"].endswith('/')

        # 提取 CRC（可选）
        crc_match = re.search(r'^CRC = ([0-9A-F]+)$', block, re.MULTILINE)
        if crc_match:
            info_dict["crc"] = crc_match.group(1).strip()

        return info_dict

    def is_encrypted(self, archive_path: str, encoding: str = "utf-8") -> bool:
        """
        检测压缩包是否加密

        Args:
            archive_path: 压缩包文件路径
            encoding: 编码

        Returns:
            bool: 是否加密
        """
        # 验证路径安全
        try:
            archive_path = validate_safe_path(archive_path)
        except ValueError as e:
            error(f"路径验证失败: {e}")
            return False
        
        if not os.path.exists(archive_path):
            return False

        # 使用 7z l 命令，检查输出中是否有加密提示
        args = ["l", archive_path]
        returncode, stdout, stderr = self._run_7z_command(args, encoding)

        if returncode != 0:
            # 如果返回码非0，可能是需要密码
            error_lower = stderr.lower()
            if any(keyword in error_lower for keyword in ["password", "加密", "encrypted", "cannot open"]):
                return True

        # 检查输出中是否有加密相关的提示
        output_lower = stdout.lower()
        encrypted_keywords = [
            "encrypted",
            "password",
            "加密",
            "密码"
        ]

        for keyword in encrypted_keywords:
            if keyword in output_lower:
                return True

        # 尝试检测文件头是否加密
        # 使用 7z l -slt 查看是否有 Encrypted = + 标记
        args = ["l", "-slt", archive_path]
        returncode, stdout, stderr = self._run_7z_command(args, encoding)

        if "Encrypted = +" in stdout or "Encrypted = yes" in stdout.lower():
            return True

        return False

    def get_archive_type(self, archive_path: str) -> str:
        """
        获取压缩包类型

        Args:
            archive_path: 压缩包文件路径

        Returns:
            str: 压缩包类型（如 zip, rar, 7z, tar 等）
        """
        # 验证路径安全
        try:
            archive_path = validate_safe_path(archive_path)
        except ValueError as e:
            error(f"路径验证失败: {e}")
            return "unknown"
        
        if not os.path.exists(archive_path):
            return "unknown"

        # 使用 7z l 命令获取类型
        args = ["l", archive_path]
        returncode, stdout, stderr = self._run_7z_command(args)

        if returncode != 0:
            return "unknown"

        # 解析类型信息
        # 7z 输出格式中通常包含 "Type = " 行
        type_match = re.search(r'^Type = ([^\n]+)$', stdout, re.MULTILINE)
        if type_match:
            archive_type = type_match.group(1).strip().lower()
            return archive_type

        # 如果无法从输出解析，尝试从扩展名判断
        ext = os.path.splitext(archive_path)[1].lower()
        ext_map = {
            '.zip': 'zip',
            '.rar': 'rar',
            '.7z': '7z',
            '.tar': 'tar',
            '.gz': 'gzip',
            '.tgz': 'gzip',
            '.bz2': 'bzip2',
            '.xz': 'xz',
            '.iso': 'iso',
            '.cab': 'cab',
            '.arj': 'arj',
            '.lzh': 'lzh',
            '.chm': 'chm',
            '.z': 'z',
            '.rpm': 'rpm',
            '.deb': 'deb',
            '.dmg': 'dmg',
            '.xar': 'xar',
            '.wim': 'wim',
        }

        return ext_map.get(ext, 'unknown')

    def test_archive(self, archive_path: str, encoding: str = "utf-8") -> Tuple[bool, str]:
        """
        测试压缩包完整性

        Args:
            archive_path: 压缩包文件路径
            encoding: 编码

        Returns:
            Tuple[bool, str]: (是否有效, 错误信息)
        """
        # 验证路径安全
        try:
            archive_path = validate_safe_path(archive_path)
        except ValueError as e:
            return False, f"路径验证失败: {e}"
        
        if not os.path.exists(archive_path):
            return False, "文件不存在"

        args = ["t", archive_path]
        returncode, stdout, stderr = self._run_7z_command(args, encoding)

        if returncode == 0:
            return True, ""
        else:
            return False, stderr or stdout


# 全局单例实例
_7z_core_instance = None


def get_7z_core(command_timeout: int = None) -> Py7zCore:
    """
    获取 7z 核心模块的全局单例实例

    Args:
        command_timeout: 命令执行超时时间（秒），默认60秒

    Returns:
        Py7zCore: 7z 核心模块实例
    """
    global _7z_core_instance
    if _7z_core_instance is None:
        _7z_core_instance = Py7zCore(command_timeout=command_timeout)
    return _7z_core_instance


def list_archive(
    archive_path: str,
    current_path: str = "",
    encoding: str = "utf-8"
) -> List[Dict]:
    """
    便捷函数：列出压缩包内容

    Args:
        archive_path: 压缩包文件路径
        current_path: 当前浏览路径
        encoding: 编码

    Returns:
        List[Dict]: 文件列表
    """
    core = get_7z_core()
    return core.list_archive(archive_path, current_path, encoding)


def is_encrypted(archive_path: str, encoding: str = "utf-8") -> bool:
    """
    便捷函数：检测压缩包是否加密

    Args:
        archive_path: 压缩包文件路径
        encoding: 编码

    Returns:
        bool: 是否加密
    """
    core = get_7z_core()
    return core.is_encrypted(archive_path, encoding)


def get_archive_type(archive_path: str) -> str:
    """
    便捷函数：获取压缩包类型

    Args:
        archive_path: 压缩包文件路径

    Returns:
        str: 压缩包类型
    """
    core = get_7z_core()
    return core.get_archive_type(archive_path)


if __name__ == "__main__":
    # 测试代码
    print("7z Core Module Test")
    print("=" * 50)

    try:
        core = Py7zCore()
        print(f"7z.exe 路径: {core._7z_exe_path}")

        # 测试列出当前目录下的压缩包
        test_dir = os.path.dirname(os.path.abspath(__file__))
        print(f"\n测试目录: {test_dir}")

        # 查找测试用的压缩包
        for filename in os.listdir(test_dir):
            if filename.endswith(('.zip', '.rar', '.7z', '.tar', '.gz')):
                archive_path = os.path.join(test_dir, filename)
                print(f"\n测试压缩包: {filename}")
                print(f"类型: {core.get_archive_type(archive_path)}")
                print(f"加密: {core.is_encrypted(archive_path)}")

                files = core.list_archive(archive_path)
                print(f"文件数量: {len(files)}")
                for f in files[:5]:  # 只显示前5个
                    type_str = "[DIR]" if f["is_dir"] else "[FILE]"
                    print(f"  {type_str} {f['name']}")
                if len(files) > 5:
                    print(f"  ... 还有 {len(files) - 5} 个文件")
                break
        else:
            print("未找到测试用的压缩包")

    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
