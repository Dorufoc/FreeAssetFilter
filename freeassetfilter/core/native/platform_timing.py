#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""W5 高精度定时 + W6 交换链延迟探测（PERFORMANCE_CEILING_PLAN.md §3.3）。

交互窗口契约（调用方必须遵守）
------------------------------
``timeBeginPeriod(1)`` 是**系统全局副作用**：它把整个 OS 的定时器分辨率
提到 1ms，直接增加全机功耗。因此**严禁应用生命周期常开**，只允许在
明确的交互/动画窗口期内持有：

* 动画 / 滚动 / 拖动会话 **START** 时调用 :func:`begin_highres_timer`。
* 会话 **END** 时必须调用 :func:`end_highres_timer`（成对、必调）。
* 嵌套会话由引用计数保护：多次 begin 需等量 end，第 0 次 end 才真正
  调用 ``timeEndPeriod(1)`` 恢复默认分辨率。
* ``powersave`` 档位**永远不开启**（begin 直接返回 False，不触碰 winmm）。
* 便捷写法：用 :func:`highres_timer_window` 上下文管理器包裹会话体。
* 基准/阻塞测试不得开启（CI 抖动污染）。

当前已接线的窗口边界
----------------------
:class:`~freeassetfilter.core.managers.heartbeat_manager.HeartbeatManager`
的 fast-tick（60fps 动画）窗口：首个 ``use_fast_tick`` 回调注册
（``_maybe_start_fast_timer``）即 begin，最后一个注销 / ``stop()``
（``_maybe_stop_fast_timer``）即 end。该挂接受 ``FAF_HIGHRES_TIMER=1``
环境变量门控（默认关闭），正式打开时机为 todo 14 三档开关落地后由
性能档位统一控制；门控关闭期间 heartbeat 行为与原来完全一致。

W6 探测诚实性
--------------
:func:`probe_swapchain_latency` 会**真实尝试**：加载 ``dxgi.dll`` 建
``IDXGIFactory1``（证明 DXGI 路径可用）＋ 反射应用内 ``QRhiWidget``
实例（证明 RHI 表面是否暴露到 Python 侧）。``SetMaximumFrameLatency``
需要原生 ``IDXGISwapChain2*``，Python 侧无法从 ``QRhiWidget`` 拿到该
指针，故可达时返回 ``"reachable"``（未来 C++ 层直连时），当前实际
返回 ``"deferred-to-P3"`` ＋ 单行原因，并**强制落盘**
``.omo/evidence/performance-ceiling-optimization/task-13/swapchain_probe.txt``
（含 ``swapchain_latency=`` 与 ``reason=`` 两行）。该产物是验收项，
函数永不静默跳过、永不抛异常（失败也落盘）。
"""

from __future__ import annotations

import contextlib
import ctypes
import datetime
import logging
import os
import statistics
import sys
import threading
import time
from pathlib import Path
from typing import Iterator, Literal, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 平台守卫与 winmm / ntdll 绑定
# ---------------------------------------------------------------------------

IS_WINDOWS: bool = sys.platform == "win32"

#: ``timeBeginPeriod`` 的目标分辨率（毫秒）。
TARGET_RESOLUTION_MS: int = 1

#: 性能档位。``powersave`` 下 begin 直接拒绝。
_ACTIVE_PROFILE: str = "balanced"
_PROFILE_LOCK: threading.Lock = threading.Lock()

_winmm = None  # type: ignore[var-annotated]
_ntdll = None  # type: ignore[var-annotated]

if IS_WINDOWS:  # pragma: no cover - 仅 Windows 下绑定
    try:
        _winmm = ctypes.WinDLL("winmm", use_last_error=True)
        _winmm.timeBeginPeriod.argtypes = [ctypes.c_uint]
        _winmm.timeBeginPeriod.restype = ctypes.c_uint
        _winmm.timeEndPeriod.argtypes = [ctypes.c_uint]
        _winmm.timeEndPeriod.restype = ctypes.c_uint
    except OSError:
        _winmm = None
    try:
        _ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
    except OSError:
        _ntdll = None


class _TIMECAPS(ctypes.Structure):
    """winmm ``TIMECAPS``：``timeGetDevCaps`` 的输出结构。"""

    _fields_ = [
        ("wPeriodMin", ctypes.c_uint),
        ("wPeriodMax", ctypes.c_uint),
    ]


# ---------------------------------------------------------------------------
# W5：引用计数的高精度定时器
# ---------------------------------------------------------------------------

_state_lock: threading.Lock = threading.Lock()
_refcount: int = 0
_elevated: bool = False


def set_active_profile(profile: str) -> None:
    """设置当前性能档位（``performance`` / ``balanced`` / ``powersave``）。

    Args:
        profile: 档位名；未知取值回退为 ``balanced``。
    """
    global _ACTIVE_PROFILE
    normalized = str(profile).lower()
    if normalized not in ("performance", "balanced", "powersave"):
        normalized = "balanced"
    with _PROFILE_LOCK:
        _ACTIVE_PROFILE = normalized


def get_active_profile() -> str:
    """返回当前性能档位。

    Returns:
        ``performance`` / ``balanced`` / ``powersave`` 之一。
    """
    with _PROFILE_LOCK:
        return _ACTIVE_PROFILE


def get_refcount() -> int:
    """返回当前高精度定时器的引用计数（诊断用）。

    Returns:
        未配对的 ``begin_highres_timer`` 调用次数。
    """
    with _state_lock:
        return _refcount


def is_elevated() -> bool:
    """返回系统定时器分辨率当前是否由本模块抬高。

    Returns:
        已成功调用 ``timeBeginPeriod(1)`` 且尚未恢复时为 True。
    """
    with _state_lock:
        return _elevated


def get_timer_caps() -> Tuple[int, int]:
    """经 ``timeGetDevCaps`` 查询系统支持的定时器分辨率区间。

    Returns:
        ``(wPeriodMin_ms, wPeriodMax_ms)``；非 Windows 或查询失败时
        返回 ``(1, 16)`` 的保守假设（文档化降级，不抛异常）。
    """
    if IS_WINDOWS and _winmm is not None:
        try:
            caps = _TIMECAPS()
            fn = _winmm.timeGetDevCaps
            fn.argtypes = [ctypes.POINTER(_TIMECAPS), ctypes.c_uint]
            fn.restype = ctypes.c_uint
            if fn(ctypes.byref(caps), ctypes.sizeof(caps)) == 0:
                return (int(caps.wPeriodMin), int(caps.wPeriodMax))
        except (OSError, ValueError, AttributeError):
            pass
    return (1, 16)


def get_current_timer_resolution_ms() -> float:
    """读取当前系统定时器分辨率（毫秒）。

    优先经 ``ntdll!NtQueryTimerResolution`` 回读真实值（100ns 单位）；
    不可用时按本模块持有状态回退为 ``1.0``（已抬高）/ ``15.6``
    （默认），回退路径仅用于非 Windows 降级。

    Returns:
        当前分辨率毫秒数。
    """
    if IS_WINDOWS and _ntdll is not None:
        try:
            query = _ntdll.NtQueryTimerResolution
            query.argtypes = [
                ctypes.POINTER(ctypes.c_ulong),
                ctypes.POINTER(ctypes.c_ulong),
                ctypes.POINTER(ctypes.c_ulong),
            ]
            query.restype = ctypes.c_long
            minimum = ctypes.c_ulong(0)
            maximum = ctypes.c_ulong(0)
            current = ctypes.c_ulong(0)
            status = query(
                ctypes.byref(minimum), ctypes.byref(maximum), ctypes.byref(current)
            )
            if int(status) >= 0 and int(current.value) > 0:
                return float(int(current.value)) / 10000.0
        except (OSError, ValueError, AttributeError):
            pass
    with _state_lock:
        elevated = _elevated
    return 1.0 if elevated else 15.6


def begin_highres_timer(profile: Optional[str] = None) -> bool:
    """开启交互窗口期的高精度定时（引用计数 +1）。

    ``powersave`` 档位永远拒绝（返回 False，不触碰 winmm）。首个持有者
    触发真实的 ``timeBeginPeriod(1)``；嵌套调用只增加计数。

    Args:
        profile: 本次调用的档位覆写；``None`` 表示使用全局档位。

    Returns:
        持有成功（计数已 +1）返回 True；档位拒绝 / 非 Windows /
        winmm 不可用 / ``timeBeginPeriod`` 失败返回 False。
    """
    active = str(profile).lower() if profile else get_active_profile()
    if active == "powersave":
        return False
    if not IS_WINDOWS or _winmm is None:
        return False
    with _state_lock:
        global _refcount, _elevated
        if _refcount == 0:
            try:
                if _winmm.timeBeginPeriod(TARGET_RESOLUTION_MS) != 0:
                    logger.warning("timeBeginPeriod(1) failed")
                    return False
            except (OSError, ValueError):
                logger.warning("timeBeginPeriod(1) raised", exc_info=True)
                return False
            _elevated = True
        _refcount += 1
        return True


def end_highres_timer() -> bool:
    """结束一个交互窗口期的高精度定时（引用计数 -1）。

    计数归零时调用 ``timeEndPeriod(1)`` 恢复默认分辨率；计数已为零时
    返回 False 且不触碰 winmm（防止误恢复他人持有的分辨率）。

    Returns:
        计数成功 -1 返回 True；无持有时返回 False。
    """
    with _state_lock:
        global _refcount, _elevated
        if _refcount <= 0:
            return False
        _refcount -= 1
        if _refcount == 0 and _elevated:
            try:
                if IS_WINDOWS and _winmm is not None:
                    _winmm.timeEndPeriod(TARGET_RESOLUTION_MS)
            except (OSError, ValueError):
                logger.warning("timeEndPeriod(1) raised", exc_info=True)
            finally:
                _elevated = False
        return True


def reset_highres_timer_state() -> None:
    """强制清零引用计数并恢复默认分辨率（仅测试用逃生舱）。

    生产代码禁止调用；单测 fixture 用它保证用例间隔离。
    """
    with _state_lock:
        global _refcount, _elevated
        if _elevated:
            try:
                if IS_WINDOWS and _winmm is not None:
                    _winmm.timeEndPeriod(TARGET_RESOLUTION_MS)
            except (OSError, ValueError):
                pass
            _elevated = False
        _refcount = 0


@contextlib.contextmanager
def highres_timer_window(
    profile: Optional[str] = None,
) -> Iterator[bool]:
    """以上下文管理器包裹一次交互/动画会话的高精度定时。

    Args:
        profile: 档位覆写；``None`` 表示使用全局档位。

    Yields:
        begin 是否成功持有。
    """
    opened = begin_highres_timer(profile)
    try:
        yield opened
    finally:
        if opened:
            end_highres_timer()


def measure_frame_jitter(
    samples: int = 30,
    interval_ms: float = 16.0,
) -> dict:
    """在当前分辨率下测量 ``interval_ms`` 睡眠的帧间隔抖动。

    Args:
        samples: 采样次数（对抗 flaky：调用方应保证 N>=3）。
        interval_ms: 目标等待间隔毫秒数。

    Returns:
        ``{"samples": N, "mean_ms": .., "stdev_ms": .., "max_ms": ..,
        "min_ms": .., "resolution_ms": ..}``。
    """
    stamps: list[float] = []
    for _ in range(max(1, int(samples))):
        start = time.perf_counter()
        time.sleep(float(interval_ms) / 1000.0)
        stamps.append((time.perf_counter() - start) * 1000.0)
    return {
        "samples": len(stamps),
        "mean_ms": statistics.fmean(stamps),
        "stdev_ms": statistics.pstdev(stamps) if len(stamps) > 1 else 0.0,
        "max_ms": max(stamps),
        "min_ms": min(stamps),
        "resolution_ms": get_current_timer_resolution_ms(),
    }


# ---------------------------------------------------------------------------
# W6：交换链延迟探测（诚实尝试 + 强制产物）
# ---------------------------------------------------------------------------

#: 仓库根（``freeassetfilter/core/native/platform_timing.py`` 上溯三级）。
_REPO_ROOT: Path = Path(__file__).resolve().parents[3]

#: W6 探测产物相对路径（验收强制项）。
PROBE_ARTIFACT_REL: str = (
    ".omo/evidence/performance-ceiling-optimization/task-13/swapchain_probe.txt"
)


def default_probe_artifact_path() -> Path:
    """返回 W6 探测产物的默认落盘路径。

    Returns:
        仓库根下的 ``swapchain_probe.txt`` 绝对路径。
    """
    return _REPO_ROOT / PROBE_ARTIFACT_REL


def _attempt_dxgi_factory() -> str:
    """真实尝试：加载 dxgi.dll 并创建 IDXGIFactory1。

    Returns:
        ``"ok"`` 或 ``"fail:<原因>"`` 的单行状态。
    """
    if not IS_WINDOWS:
        return "fail:non-windows"
    try:
        dxgi = ctypes.WinDLL("dxgi", use_last_error=True)
    except OSError as exc:
        return f"fail:load-dxgi:{exc}"
    try:
        create = dxgi.CreateDXGIFactory1
        create.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        create.restype = ctypes.c_long
        iid = (ctypes.c_ubyte * 16)(
            0x78, 0xAE, 0x0A, 0x77, 0x6F, 0xF2, 0xBA, 0x4D,
            0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87,
        )
        out = ctypes.c_void_p()
        hr = create(ctypes.byref(iid), ctypes.byref(out))
        if int(hr) >= 0 and out.value:
            # 探测目的已达成（工厂可建 ⇒ DXGI 路径可用）；按 IUnknown
            # vtable[2] 释放，避免单次探测泄漏 COM 引用。
            try:
                vtbl = ctypes.cast(
                    out, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
                )
                proto = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
                proto(vtbl.contents[2])(out)
            except (OSError, ValueError):
                pass
            return "ok"
        return f"fail:hr=0x{int(hr) & 0xFFFFFFFF:08X}"
    except (OSError, ValueError, AttributeError) as exc:
        return f"fail:{type(exc).__name__}:{exc}"


def _attempt_rhi_surface() -> str:
    """真实尝试：反射应用内 QRhiWidget 实例，判断 RHI 表面是否暴露。

    Returns:
        ``"widgets=<n>"``（找到 n 个 QRhiWidget）或
        ``"unavailable:<原因>"`` 的单行状态。
    """
    try:
        from PySide6.QtWidgets import QApplication, QRhiWidget  # type: ignore[import]
    except ImportError as exc:
        return f"unavailable:no-QRhiWidget-in-PySide6:{exc}"
    except (OSError, ValueError) as exc:
        return f"unavailable:import-failed:{exc}"
    try:
        app = QApplication.instance()
        if app is None:
            return "unavailable:no-QApplication-instance"
        found = 0
        for widget in app.topLevelWidgets():
            try:
                found += len(widget.findChildren(QRhiWidget))
            except (RuntimeError, AttributeError):
                continue
        return f"widgets={found}"
    except (RuntimeError, AttributeError, OSError) as exc:
        return f"unavailable:scan-failed:{exc}"


def probe_swapchain_latency(
    artifact_path: Optional[Path | str] = None,
) -> Literal["reachable", "deferred-to-P3"]:
    """探测 D3D11 交换链并尝试设置最大帧延迟（W6）。

    实际执行 DXGI 工厂创建与 RHI 表面反射两步真实尝试；由于
    ``IDXGISwapChain2*`` 无法从 Python 侧 ``QRhiWidget`` 获取，
    当前必然落到 ``"deferred-to-P3"``（C++ 层 todo P3/P5 落地
    ``SetMaximumFrameLatency``），但尝试过程与原因全部如实记录。
    无论结论如何都落盘产物文件，永不静默跳过、永不抛异常。

    Args:
        artifact_path: 产物覆写路径；``None`` 用默认仓库路径。

    Returns:
        ``"reachable"``（实际设置成功，仅未来 C++ 直连路径）或
        ``"deferred-to-P3"``。
    """
    verdict: Literal["reachable", "deferred-to-P3"] = "deferred-to-P3"
    target = Path(artifact_path) if artifact_path else default_probe_artifact_path()
    dxgi_status = _attempt_dxgi_factory()
    rhi_status = _attempt_rhi_surface()
    if not IS_WINDOWS:
        reason = "non-Windows platform; no DXGI swap chain to program"
    elif dxgi_status != "ok":
        reason = (
            "DXGI factory unreachable "
            f"({dxgi_status}); C++ layer (todo P3/P5) will set MaximumFrameLatency"
        )
    else:
        reason = (
            "RHI swap chain not exposed to Python; "
            "C++ layer (todo P3/P5) will set MaximumFrameLatency"
        )
    lines = [
        f"swapchain_latency={verdict}",
        f"reason={reason}",
        f"dxgi_factory={dxgi_status}",
        f"rhi_surface={rhi_status}",
        f"os={sys.platform}",
        "timestamp="
        + datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    ]
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        logger.warning("swapchain probe artifact write failed", exc_info=True)
    return verdict


def highres_timer_enabled_by_env() -> bool:
    """heartbeat 挂接的门控：仅 ``FAF_HIGHRES_TIMER=1`` 时允许自动持有。

    Returns:
        环境变量显式开启时为 True（默认 False，保证基准测试不开启）。
    """
    return os.environ.get("FAF_HIGHRES_TIMER", "0") == "1"
