#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
媒体探测工具
统一封装 ffprobe / ffmpeg 的路径解析与媒体信息读取逻辑
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from freeassetfilter.utils.app_logger import debug, warning


FFPROBE_TIMEOUT = 8
FFMPEG_TIMEOUT = 15

_FFMPEG_WARMUP_LOCK = threading.Lock()
_FFMPEG_WARMUP_RESULT: Optional[Dict[str, bool]] = None


def _native_dir() -> Path:
    return Path(__file__).resolve().parent / "native"


def _resolve_tool_path(tool_name: str) -> str:
    """
    优先返回项目内 bundled 工具路径，否则回退为 PATH 中的命令名
    """
    bundled = _native_dir() / tool_name
    if bundled.exists():
        return str(bundled)
    return tool_name


def get_ffprobe_path() -> str:
    return _resolve_tool_path("ffprobe.exe" if os.name == "nt" else "ffprobe")


def get_ffmpeg_path() -> str:
    return _resolve_tool_path("ffmpeg.exe" if os.name == "nt" else "ffmpeg")


def get_subprocess_creationflags() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _run_warmup_command(command: List[str], *, label: str, timeout: int) -> bool:
    """
    执行轻量级预热命令，提前拉起 ffmpeg / ffprobe 相关运行时。
    """
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1, int(timeout)),
            creationflags=get_subprocess_creationflags(),
        )
    except FileNotFoundError:
        debug(f"[media_probe] 预热跳过，未找到命令: {label}")
        return False
    except subprocess.TimeoutExpired:
        debug(f"[media_probe] 预热命令超时: {label}")
        return False
    except Exception as e:
        debug(f"[media_probe] 预热命令执行失败: {label}, 错误: {e}")
        return False

    if completed.returncode != 0:
        stderr_text = (completed.stderr or "").strip()
        if stderr_text:
            debug(f"[media_probe] 预热命令返回非0: {label}, stderr={stderr_text}")
        return False

    return True


def warmup_ffmpeg_tools(force: bool = False) -> Dict[str, bool]:
    """
    后台预热 ffmpeg / ffprobe 相关模块，降低首次媒体探测和软解启动延迟。

    预热内容：
    - ffprobe 版本查询：提前拉起探测进程与依赖
    - ffmpeg 版本查询：提前拉起 ffmpeg 主体
    - ffmpeg -hwaccels：提前触发硬解能力枚举相关初始化
    """
    global _FFMPEG_WARMUP_RESULT

    with _FFMPEG_WARMUP_LOCK:
        if _FFMPEG_WARMUP_RESULT is not None and not force:
            return dict(_FFMPEG_WARMUP_RESULT)

        ffprobe_path = get_ffprobe_path()
        ffmpeg_path = get_ffmpeg_path()

        result = {
            "ffprobe_version": _run_warmup_command(
                [ffprobe_path, "-version"],
                label="ffprobe -version",
                timeout=min(5, FFPROBE_TIMEOUT),
            ),
            "ffmpeg_version": _run_warmup_command(
                [ffmpeg_path, "-hide_banner", "-version"],
                label="ffmpeg -version",
                timeout=min(5, FFMPEG_TIMEOUT),
            ),
            "ffmpeg_hwaccels": _run_warmup_command(
                [ffmpeg_path, "-hide_banner", "-hwaccels"],
                label="ffmpeg -hwaccels",
                timeout=min(5, FFMPEG_TIMEOUT),
            ),
        }

        _FFMPEG_WARMUP_RESULT = dict(result)
        return dict(result)


def run_ffprobe_json(
    file_path: str,
    *,
    show_format: bool = True,
    show_streams: bool = True,
    extra_entries: Optional[List[str]] = None,
    timeout: int = FFPROBE_TIMEOUT,
) -> Optional[Dict[str, Any]]:
    """
    运行 ffprobe 并返回 JSON 结果
    """
    command = [
        get_ffprobe_path(),
        "-v",
        "quiet",
        "-print_format",
        "json",
    ]

    show_entries: List[str] = []
    if show_format:
        show_entries.append("format")
    if show_streams:
        show_entries.append("stream")
    if extra_entries:
        show_entries.extend(extra_entries)

    if show_entries:
        command.extend(["-show_entries", ":".join(show_entries)])

    if show_streams:
        command.append("-show_streams")
    if show_format:
        command.append("-show_format")

    command.append(file_path)

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=get_subprocess_creationflags(),
        )
    except FileNotFoundError:
        warning("[media_probe] 未找到 ffprobe")
        return None
    except subprocess.TimeoutExpired:
        debug(f"[media_probe] ffprobe 超时: {file_path}")
        return None
    except Exception as e:
        debug(f"[media_probe] ffprobe 执行失败: {file_path}, 错误: {e}")
        return None

    if completed.returncode != 0:
        stderr_text = (completed.stderr or "").strip()
        if stderr_text:
            debug(f"[media_probe] ffprobe 异常输出: {stderr_text}")
        return None

    try:
        return json.loads(completed.stdout or "{}")
    except Exception as e:
        debug(f"[media_probe] 解析 ffprobe JSON 失败: {file_path}, 错误: {e}")
        return None


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        result = float(value)
        if result > 0:
            return result
    except (TypeError, ValueError):
        pass
    return None


def _safe_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_fraction(value: Any) -> Optional[float]:
    if value in (None, "", "0/0", "N/A"):
        return None

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if "/" in text:
        try:
            num, den = text.split("/", 1)
            num_f = float(num)
            den_f = float(den)
            if den_f != 0:
                result = num_f / den_f
                if result > 0:
                    return result
        except (TypeError, ValueError, ZeroDivisionError):
            return None

    return _safe_float(text)


def get_video_stream_info(file_path: str) -> Dict[str, Any]:
    """
    获取视频流核心信息
    返回字段：
    - duration_seconds
    - width
    - height
    - fps
    - bitrate
    - codec
    """
    payload = run_ffprobe_json(file_path, show_format=True, show_streams=True)
    if not payload:
        return {}

    result: Dict[str, Any] = {}
    format_info = payload.get("format") or {}
    streams = payload.get("streams") or []
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), None)

    duration_candidates: List[float] = []

    format_duration = _safe_float(format_info.get("duration"))
    if format_duration:
        duration_candidates.append(format_duration)

    if video_stream:
        stream_duration = _safe_float(video_stream.get("duration"))
        if stream_duration:
            duration_candidates.append(stream_duration)

    if duration_candidates:
        result["duration_seconds"] = max(duration_candidates)

    if video_stream:
        width = _safe_int(video_stream.get("width"))
        height = _safe_int(video_stream.get("height"))
        if width and height and width > 0 and height > 0:
            result["width"] = width
            result["height"] = height

        fps = (
            _parse_fraction(video_stream.get("avg_frame_rate"))
            or _parse_fraction(video_stream.get("r_frame_rate"))
        )
        if fps:
            result["fps"] = fps

        codec = video_stream.get("codec_name")
        if codec:
            result["codec"] = str(codec)

        bit_rate = _safe_int(video_stream.get("bit_rate"))
        if bit_rate and bit_rate > 0:
            result["bitrate"] = bit_rate

    if "bitrate" not in result:
        format_bitrate = _safe_int(format_info.get("bit_rate"))
        if format_bitrate and format_bitrate > 0:
            result["bitrate"] = format_bitrate

    return result


def get_video_duration_seconds(file_path: str) -> Optional[float]:
    info = get_video_stream_info(file_path)
    duration = info.get("duration_seconds")
    return float(duration) if isinstance(duration, (int, float)) and duration > 0 else None
