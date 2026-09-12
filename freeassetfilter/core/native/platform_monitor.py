#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""W9/W10 平台监视器：DWM 协同探测 + USER/GDI 句柄预算采样。

W9（DWM 协同）：PySide6 时代以「探测 + 记录」为主，不做合成器写入。
:func:`probe_dwm_present_parameters` 仅解析 ``dwmapi.dll`` 导出符号并把
结论落盘为 ``w14_dwm_probe.txt`` 产物，恒返回 ``"probe-only"``——诚实
探测，永不伪造 ``applied``。

W10（句柄预算）：:func:`sample_gui_resources` 经 ``user32.GetGuiResources``
对当前进程采样 ``GR_GDIOBJECTS`` / ``GR_USEROBJECTS`` 计数，并做阈值
告警（USER 上限 10000，8000 起警告；GDI 同口径）。

线程注意：本模块所有调用均为同步 ctypes 调用，无后台线程；采样开销为
两次 syscall 级调用，可直接在 ``perf_metrics.snapshot()`` 内调用。

Copyright (c) 2026 Dorufoc <dorufoc@outlook.com>
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from typing import Any, Dict, Literal, Optional

from freeassetfilter.utils.app_logger import debug, warning

IS_WINDOWS: bool = sys.platform == "win32"

#: USER 对象进程上限（Windows 会话硬上限 10000）。
USER_OBJECT_CAP: int = 10000
#: USER 对象警告水位。
USER_OBJECT_WARN: int = 8000
#: GDI 对象进程上限（默认 10000，可经注册表上调；按默认口径告警）。
GDI_OBJECT_CAP: int = 10000
#: GDI 对象警告水位。
GDI_OBJECT_WARN: int = 8000

#: GetGuiResources 的 uiFlags：0 = GDI 对象，1 = USER 对象。
_GR_GDIOBJECTS: int = 0
_GR_USEROBJECTS: int = 1

#: W9 探测结论（PySide6 时代唯一合法值）。
DWM_PROBE_ONLY: Literal["probe-only"] = "probe-only"

_lock = threading.Lock()
_user32 = None  # type: ignore[var-annotated]
_kernel32 = None  # type: ignore[var-annotated]

if IS_WINDOWS:  # pragma: no cover - 仅 Windows 下绑定
    try:
        _user32 = ctypes.WinDLL("user32", use_last_error=True)
        _user32.GetGuiResources.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        _user32.GetGuiResources.restype = ctypes.c_uint
    except OSError:
        _user32 = None
    try:
        _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    except OSError:
        _kernel32 = None


def sample_gui_resources() -> Dict[str, Any]:
    """采样当前进程的 USER/GDI 对象计数并做阈值告警。

    非 Windows 或 user32 不可用时返回计数字段为 ``None`` 的降级字典
    （调用方按缺失处理，不抛异常）。

    Returns:
        Dict[str, Any]: ``{"user_objects", "gdi_objects", "user_warn",
        "gdi_warn", "user_over_cap", "gdi_over_cap", "platform"}``。
        ``*_warn`` 在计数 >= 对应 WARN 水位时为 True；``*_over_cap``
        在计数 >= CAP 时为 True。
    """
    if not IS_WINDOWS or _user32 is None or _kernel32 is None:
        return {
            "user_objects": None,
            "gdi_objects": None,
            "user_warn": False,
            "gdi_warn": False,
            "user_over_cap": False,
            "gdi_over_cap": False,
            "platform": sys.platform,
        }
    with _lock:
        try:
            handle = _kernel32.GetCurrentProcess()
            user_count = int(_user32.GetGuiResources(handle, _GR_USEROBJECTS))
            gdi_count = int(_user32.GetGuiResources(handle, _GR_GDIOBJECTS))
        except OSError as exc:
            warning(f"GetGuiResources 采样失败: {exc}")
            return {
                "user_objects": None,
                "gdi_objects": None,
                "user_warn": False,
                "gdi_warn": False,
                "user_over_cap": False,
                "gdi_over_cap": False,
                "platform": sys.platform,
            }
    user_warn = user_count >= USER_OBJECT_WARN
    gdi_warn = gdi_count >= GDI_OBJECT_WARN
    if user_warn:
        warning(
            f"USER 对象逼近上限: {user_count}/{USER_OBJECT_CAP} "
            f"(warn={USER_OBJECT_WARN})"
        )
    if gdi_warn:
        warning(
            f"GDI 对象逼近上限: {gdi_count}/{GDI_OBJECT_CAP} "
            f"(warn={GDI_OBJECT_WARN})"
        )
    return {
        "user_objects": user_count,
        "gdi_objects": gdi_count,
        "user_warn": user_warn,
        "gdi_warn": gdi_warn,
        "user_over_cap": user_count >= USER_OBJECT_CAP,
        "gdi_over_cap": gdi_count >= GDI_OBJECT_CAP,
        "platform": sys.platform,
    }


def check_gui_resource_budget(
    sample: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """对一次句柄采样做预算判定（纯函数，便于单测阈值逻辑）。

    Args:
        sample: :func:`sample_gui_resources` 的返回值；为 ``None`` 时
            现场采样一次。

    Returns:
        Dict[str, Any]: ``{"ok", "warnings", "user_objects",
        "gdi_objects"}``；``ok`` 为 False 当且仅当任一计数越过 CAP。
    """
    data = sample if sample is not None else sample_gui_resources()
    user_count = data.get("user_objects")
    gdi_count = data.get("gdi_objects")
    warnings: list[str] = []
    ok = True
    if isinstance(user_count, int):
        if user_count >= USER_OBJECT_CAP:
            ok = False
            warnings.append(f"user_objects {user_count} >= cap {USER_OBJECT_CAP}")
        elif user_count >= USER_OBJECT_WARN:
            warnings.append(f"user_objects {user_count} >= warn {USER_OBJECT_WARN}")
    if isinstance(gdi_count, int):
        if gdi_count >= GDI_OBJECT_CAP:
            ok = False
            warnings.append(f"gdi_objects {gdi_count} >= cap {GDI_OBJECT_CAP}")
        elif gdi_count >= GDI_OBJECT_WARN:
            warnings.append(f"gdi_objects {gdi_count} >= warn {GDI_OBJECT_WARN}")
    return {
        "ok": ok,
        "warnings": warnings,
        "user_objects": user_count,
        "gdi_objects": gdi_count,
    }


def default_probe_artifact_path() -> str:
    """返回 W9 探测产物的默认落盘路径。

    Returns:
        str: ``.omo/evidence/performance-ceiling-optimization/task-14/w14_dwm_probe.txt``。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    # here = <root>/freeassetfilter/core/native，上溯 3 级即仓库根。
    root = os.path.dirname(
        os.path.dirname(os.path.dirname(here))
    )
    return os.path.join(
        root,
        ".omo",
        "evidence",
        "performance-ceiling-optimization",
        "task-14",
        "w14_dwm_probe.txt",
    )


def _attempt_dwm_symbols() -> Dict[str, Any]:
    """解析 dwmapi 导出符号存在性（只读探测，不调用写入型 API）。

    Returns:
        Dict[str, Any]: 各符号的 ``present`` 标记与平台信息。
    """
    info: Dict[str, Any] = {
        "platform": sys.platform,
        "dwmapi_loaded": False,
        "DwmGetCompositionTimingInfo": "unavailable",
        "DwmSetPresentParameters": "unavailable",
        "DwmGetColorizationColor": "unavailable",
    }
    if not IS_WINDOWS:
        info["reason"] = "non-windows: DWM 不存在"
        return info
    try:
        dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
    except OSError as exc:
        info["reason"] = f"dwmapi 加载失败: {exc}"
        return info
    info["dwmapi_loaded"] = True
    for name in (
        "DwmGetCompositionTimingInfo",
        "DwmSetPresentParameters",
        "DwmGetColorizationColor",
    ):
        try:
            getattr(dwmapi, name)
            info[name] = "present"
        except AttributeError:
            info[name] = "missing"
    return info


def probe_dwm_present_parameters(
    artifact_path: Optional[str] = None,
) -> Literal["probe-only"]:
    """W9 DWM 协同探测（只探测、不写入合成器参数）。

    PySide6（QRhiWidget/RHI 合成）时代，直接调用
    ``DwmSetPresentParameters`` 会与 Qt 的合成器状态竞争，故本函数
    仅做导出符号解析 + 结论落盘，恒返回 ``"probe-only"``。

    Args:
        artifact_path: 产物落盘路径；为 ``None`` 时使用
            :func:`default_probe_artifact_path`。

    Returns:
        Literal["probe-only"]: 恒为 ``"probe-only"``。
    """
    symbols = _attempt_dwm_symbols()
    target = artifact_path or default_probe_artifact_path()
    lines = [
        "dwm_probe=probe-only",
        f"reason=pyside6-rhi-owned-composition; writes deferred to P3/P5",
        f"dwmapi_loaded={symbols.get('dwmapi_loaded')}",
        f"DwmGetCompositionTimingInfo={symbols.get('DwmGetCompositionTimingInfo')}",
        f"DwmSetPresentParameters={symbols.get('DwmSetPresentParameters')}",
        f"DwmGetColorizationColor={symbols.get('DwmGetColorizationColor')}",
        f"platform={symbols.get('platform')}",
        f"timestamp={time.strftime('%Y-%m-%dT%H:%M:%S')}",
    ]
    if "reason" in symbols:
        lines.append(f"detail={symbols['reason']}")
    try:
        parent = os.path.dirname(target)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError as exc:
        warning(f"W9 DWM 探测产物落盘失败: {exc}")
    debug("W9 DWM 探测结论: probe-only（PySide6 合成器接管，不做写入）")
    return DWM_PROBE_ONLY
