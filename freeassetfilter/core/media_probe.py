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

from freeassetfilter.utils.app_logger import debug, info, warning
from freeassetfilter.utils.perf_metrics import increment_perf_counter, set_perf_metadata, track_perf


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


def get_subprocess_startupinfo():
    """获取适用于当前平台的子进程启动信息，用于隐藏窗口"""
    startupinfo = None
    if sys.platform == "win32":
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
        except Exception:
            pass
    return startupinfo


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
            startupinfo=get_subprocess_startupinfo(),
        )
    except FileNotFoundError:
        debug(f"预热跳过，未找到命令: {label}")
        return False
    except subprocess.TimeoutExpired:
        debug(f"预热超时: {label}")
        return False
    except Exception as e:
        debug(f"预热失败: {label}, 错误: {e}")
        return False

    if completed.returncode != 0:
        stderr_text = (completed.stderr or "").strip()
        if stderr_text:
            debug(f"预热返回非0: {label}, stderr={stderr_text}")
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
            debug("使用缓存的预热结果")
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
        debug(f"预热完成: ffprobe={result['ffprobe_version']}, ffmpeg={result['ffmpeg_version']}")
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
    debug(f"开始探测媒体: {file_path}")
    with track_perf("media_probe.run_ffprobe_json"):
        set_perf_metadata("media_probe.run_ffprobe_json", "last_timeout", timeout)
        set_perf_metadata("media_probe.run_ffprobe_json", "last_show_format", show_format)
        set_perf_metadata("media_probe.run_ffprobe_json", "last_show_streams", show_streams)

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
        increment_perf_counter("media_probe.run_ffprobe_json", "invocations")

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                creationflags=get_subprocess_creationflags(),
                startupinfo=get_subprocess_startupinfo(),
            )
        except FileNotFoundError:
            increment_perf_counter("media_probe.run_ffprobe_json", "ffprobe_missing")
            warning("未找到 ffprobe")
            return None
        except subprocess.TimeoutExpired:
            increment_perf_counter("media_probe.run_ffprobe_json", "timeout")
            debug(f"ffprobe 超时: {file_path}")
            return None
        except Exception as e:
            increment_perf_counter("media_probe.run_ffprobe_json", "subprocess_error")
            debug(f"ffprobe 执行失败: {file_path}, 错误: {e}")
            return None

        if completed.returncode != 0:
            increment_perf_counter("media_probe.run_ffprobe_json", "nonzero_exit")
            stderr_text = (completed.stderr or "").strip()
            if stderr_text:
                debug(f"ffprobe 异常输出: {stderr_text}")
            return None

        try:
            payload = json.loads(completed.stdout or "{}")
            increment_perf_counter("media_probe.run_ffprobe_json", "success")
            debug(f"媒体探测成功: {file_path}")
            return payload
        except Exception as e:
            increment_perf_counter("media_probe.run_ffprobe_json", "json_parse_failure")
            debug(f"解析 ffprobe JSON 失败: {file_path}, 错误: {e}")
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
    debug(f"获取视频流信息: {file_path}")
    payload = run_ffprobe_json(file_path, show_format=True, show_streams=True)
    if not payload:
        debug(f"获取视频流信息失败: {file_path}")
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

    debug(f"视频流信息获取成功: {file_path}, 字段={list(result.keys())}")
    return result


def get_video_duration_seconds(file_path: str) -> Optional[float]:
    debug(f"获取视频时长: {file_path}")
    with track_perf("media_probe.get_video_duration_seconds"):
        info = get_video_stream_info(file_path)
        duration = info.get("duration_seconds")
        if isinstance(duration, (int, float)) and duration > 0:
            increment_perf_counter("media_probe.get_video_duration_seconds", "success")
            debug(f"获取视频时长成功: {file_path}, duration={duration}")
            return float(duration)
        increment_perf_counter("media_probe.get_video_duration_seconds", "missing_duration")
        debug(f"获取视频时长失败，无有效时长: {file_path}")
        return None
