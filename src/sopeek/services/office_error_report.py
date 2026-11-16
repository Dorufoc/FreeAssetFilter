#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sopeek v1.0

Copyright (c) 2026 Dorufoc <dorufoc@outlook.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/Sopeek
许可协议：https://github.com/Dorufoc/Sopeek/blob/main/LICENSE

Office 预览错误报告构建器

把「用户看到的短消息」与「后端原始技术详情」组装成一份可直接粘贴到
issue / 聊天窗口的纯文本报告。报告只在用户点击「复制错误信息」时生成，
默认不在预览界面展示，避免把 COM HRESULT / 路径等噪音塞进 UI。

设计约束：
- 纯函数、无 Qt 依赖，便于单元测试；
- 版本、日志路径、系统信息全部惰性读取并吞掉异常；
- 任何字段缺失都安全降级，本模块绝不抛出。
"""

from __future__ import annotations

import platform
from datetime import datetime
from typing import Optional


def _safe_version_text() -> str:
    """读取应用版本与构建日期；失败时返回 ``"unknown"``。"""
    try:
        from sopeek import __version__
    except Exception:  # noqa: BLE001 - 报告构建不得因版本读取失败而失败
        return "unknown"

    version = str(__version__ or "unknown")
    try:
        from sopeek.utils.version_info import get_local_build_date

        build_date = get_local_build_date()
    except Exception:  # noqa: BLE001
        build_date = None
    return f"{version} ({build_date})" if build_date else version


def _safe_log_path() -> str:
    """读取当前日志文件路径；失败或未初始化时返回空字符串。"""
    try:
        from sopeek.utils.app_logger import get_logger

        return str(get_logger().get_log_file_path() or "")
    except Exception:  # noqa: BLE001
        return ""


def _safe_platform_text() -> str:
    """读取系统平台描述；失败时返回空字符串。

    优先复用 ``app_logger`` 的 RtlGetVersion 结果（能正确区分 Windows 11
    与 Windows 10），失败再退回 ``platform.platform()``。
    """
    try:
        from sopeek.utils.app_logger import _get_windows_version

        version_text = _get_windows_version()
        if version_text:
            return version_text
    except Exception:  # noqa: BLE001
        pass
    try:
        return platform.platform()
    except Exception:  # noqa: BLE001
        return ""


def build_office_error_report(
    message: str,
    *,
    detail: str = "",
    file_path: str = "",
    suffix: str = "",
    backend: str = "",
    timestamp: Optional[datetime] = None,
) -> str:
    """构建一份可复制的 Office 预览错误报告。

    Parameters
    ----------
    message : str
        预览界面展示的短消息（用户可读）。
    detail : str
        后端技术详情，例如 COM HRESULT、异常描述、导出阶段等。
    file_path : str
        源文件完整路径。
    suffix : str
        归一化小写后缀（无前导点）。
    backend : str
        失败后端标识（``com`` / ``libreoffice`` / ``pure-python``）。
    timestamp : Optional[datetime]
        报告时间；``None`` 时使用当前本地时间。

    Returns
    -------
    str
        以换行结尾的纯文本报告。任何字段缺失都不会抛异常。
    """
    when = (timestamp or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")

    lines: list[str] = [
        "Sopeek Office 预览错误报告",
        "=" * 30,
        f"时间：{when}",
        f"版本：{_safe_version_text()}",
    ]

    system_text = _safe_platform_text()
    if system_text:
        lines.append(f"系统：{system_text}")
    if file_path:
        lines.append(f"文件：{file_path}")
    if suffix:
        lines.append(f"格式：{suffix}")
    if backend:
        lines.append(f"后端：{backend}")

    lines.append(f"错误：{str(message or '').strip() or '未知错误'}")

    detail_text = str(detail or "").strip()
    if detail_text:
        lines.extend(["", "技术详情：", detail_text])

    log_path = _safe_log_path()
    if log_path:
        lines.extend(["", f"日志：{log_path}"])

    lines.extend(
        [
            "",
            "请将以上信息提供给开发者，以便定位问题。",
        ]
    )
    return "\n".join(lines).strip() + "\n"


__all__ = [
    "build_office_error_report",
]
