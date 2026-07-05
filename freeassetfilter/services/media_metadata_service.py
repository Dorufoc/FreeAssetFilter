#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2026 Dorufoc <dorufoc@outlook.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

媒体元数据提取服务
负责从各类媒体文件中提取元数据（封面、基本信息、音频参数等），
将提取逻辑与 UI 组件解耦以便复用和测试。
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, Optional

# 可选依赖：mutagen 未安装时静默降级
try:
    from mutagen import File as mutagen_file
except ImportError:
    mutagen_file = None

from freeassetfilter.services.base import BaseService


class MediaMetadataService(BaseService):
    """媒体元数据提取服务。

    纯数据提取，不含任何 UI 逻辑。支持音频封面、文件基本属性、
    音频编码参数等元数据的提取。

    使用方式::

        svc = MediaMetadataService()
        svc.initialize()

        cover = svc.extract_audio_cover("song.mp3")
        info = svc.extract_basic_info("video.mp4")

        svc.dispose()
    """

    # ── BaseService 生命周期 ────────────────────────────────────────

    def _do_initialize(self) -> None:
        """初始化服务（无资源需要分配）。"""
        pass

    def _do_dispose(self) -> None:
        """释放服务资源（无资源需要清理）。"""
        pass

    # ── 公开 API ────────────────────────────────────────────────────

    def extract_audio_cover(self, file_path: str) -> Optional[bytes]:
        """从音频文件中提取封面图像数据。

        Args:
            file_path: 音频文件路径。

        Returns:
            封面图像的二进制数据（JPEG/PNG），无封面或失败时返回 None。
        """
        if not mutagen_file:
            return None

        if not os.path.isfile(file_path):
            return None

        try:
            audio = mutagen_file(file_path)
            if audio is None:
                return None

            # 方法1: 从 tags 中按常见 key 查找封面数据
            if hasattr(audio, 'tags') and audio.tags:
                for key in ('cover', ' Cover', 'APIC:', 'covr', 'albumart'):
                    if key in audio.tags:
                        data = audio.tags[key].data
                        if isinstance(data, bytes):
                            return data

            # 方法2: 遍历所有 tag 值，按魔术字节识别图片
            if hasattr(audio, 'tags') and audio.tags:
                for tag in audio.tags.values():
                    if hasattr(tag, 'data') and isinstance(tag.data, bytes):
                        data: bytes = tag.data
                        if len(data) > 10 and self._looks_like_image(data):
                            return data

            return None

        except Exception:  # noqa: BLE001  — 外部库可能抛出任意异常，宽泛捕获以保证健壮性
            return None

    def extract_basic_info(self, file_path: str) -> Dict[str, Any]:
        """提取文件基本元数据。

        返回以下字段（键名均为英文，缺失的字段不会出现在字典中）：

        - ``file_name``      — 文件名
        - ``file_path``      — 完整路径
        - ``file_size``      — 文件大小（字节）
        - ``file_size_str``  — 格式化后的文件大小字符串
        - ``created_time``   — 创建时间（ISO 格式）
        - ``modified_time``  — 修改时间（ISO 格式）
        - ``is_dir``         — 是否为目录
        - ``extension``      — 文件扩展名（小写，不含点）
        - ``duration``       — 音频/视频时长（秒，仅媒体文件）
        - ``duration_str``   — 格式化后的时长字符串
        - ``bitrate``        — 比特率（bps，仅媒体文件）
        - ``bitrate_str``    — 格式化后的比特率字符串
        - ``channels``       — 声道数（仅音频文件）
        - ``sample_rate``    — 采样率（Hz，仅音频文件）
        - ``audio_format``   — 音频编码格式（仅媒体文件）

        Args:
            file_path: 文件路径。

        Returns:
            包含文件元数据的字典。文件不存在或不可读时返回仅含基础路径信息的字典。
        """
        info: Dict[str, Any] = {
            "file_name": os.path.basename(file_path),
            "file_path": file_path,
        }

        if not os.path.exists(file_path):
            return info

        info["is_dir"] = os.path.isdir(file_path)
        _, ext = os.path.splitext(file_path)
        info["extension"] = ext.lower().lstrip(".")

        # ── 文件系统属性 ───────────────────────────────────────────
        try:
            stat = os.stat(file_path)
            info["file_size"] = stat.st_size
            info["file_size_str"] = self._format_size(stat.st_size)
            info["created_time"] = datetime.fromtimestamp(
                stat.st_ctime
            ).isoformat()
            info["modified_time"] = datetime.fromtimestamp(
                stat.st_mtime
            ).isoformat()
        except (OSError, IOError, PermissionError):
            pass

        # ── 媒体元数据（mutagen） ──────────────────────────────────
        if mutagen_file and not info.get("is_dir", False):
            try:
                audio = mutagen_file(file_path)
                if audio is not None and hasattr(audio, 'info'):
                    audio_info = audio.info

                    if hasattr(audio_info, 'length') and audio_info.length:
                        info["duration"] = float(audio_info.length)
                        info["duration_str"] = self._format_duration(
                            audio_info.length
                        )

                    if (
                        hasattr(audio_info, 'bitrate')
                        and audio_info.bitrate
                    ):
                        info["bitrate"] = int(audio_info.bitrate)
                        info["bitrate_str"] = self._format_bitrate(
                            audio_info.bitrate
                        )

                    if hasattr(audio_info, 'channels'):
                        info["channels"] = int(audio_info.channels)

                    if hasattr(audio_info, 'sample_rate'):
                        info["sample_rate"] = int(audio_info.sample_rate)

                    # 编码格式
                    if hasattr(audio, 'mime'):
                        info["audio_format"] = str(audio.mime[0])
                    elif hasattr(audio, 'filename'):
                        # 从文件扩展名推断
                        pass  # 已在 extension 字段中体现
            except Exception:  # noqa: BLE001
                pass

        return info

    # ── 工具方法 ────────────────────────────────────────────────────

    @staticmethod
    def _format_size(size: int) -> str:
        """将字节数格式化为人类可读的大小字符串。"""
        if size < 0:
            return "无法获取"
        for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """将秒数格式化为 ``MM:SS`` 或 ``HH:MM:SS``。"""
        if seconds < 0:
            return "无法获取"
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"

    @staticmethod
    def _format_bitrate(bitrate: int) -> str:
        """将 bps 格式化为 Kbps / Mbps。"""
        if bitrate < 0:
            return "无法获取"
        if bitrate < 1000:
            return f"{bitrate} bps"
        if bitrate < 1_000_000:
            return f"{bitrate / 1000:.1f} Kbps"
        return f"{bitrate / 1_000_000:.1f} Mbps"

    # ── 内部辅助 ────────────────────────────────────────────────────

    @staticmethod
    def _looks_like_image(data: bytes) -> bool:
        """通过魔术字节判断是否为常见图像格式。"""
        return (
            len(data) >= 2
            and (
                data[:3] == b'\xff\xd8\xff'   # JPEG
                or data[:4] == b'\x89PNG'     # PNG
                or data[:2] in (b'BM', b'GI', b'CI')  # BMP / GIF / ...
            )
        )
