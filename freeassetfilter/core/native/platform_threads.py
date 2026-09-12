"""Windows 线程电源/亲和/MMCSS/优先级控制 —— kernel32/avrt 的薄 ctypes 封装。

本模块只做 Windows 原生线程调度的细粒度控制，且**不依赖 Qt / numpy**，
可在无显示环境下安全导入：

1. W2 电源节流：``SetProcessInformation(ProcessPowerThrottling)`` 关闭进程级
   节流；``SetThreadInformation(ThreadPowerThrottling)`` 对解码/渲染线程关闭
   节流；``GetThreadInformation`` 回读验证。
2. W3 CPU 集亲和：``SetThreadSelectedCpuSets``（注意参数顺序为
   ``(Thread, CpuSetIds, Count)``——数组在前、Count 在后，顺序错会破坏栈）；
   UI/渲染线程钉 P 核，解码农场线程钉 E 核；``GetSystemCpuSetInformation``
   枚举 CPU 集并按 ``EfficiencyClass`` 区分 P/E 核。
3. W4 MMCSS：``AvSetMmThreadCharacteristics("Playback"|"Audio")`` ——该 API
   **只作用于调用线程**，注册代码必须在目标工作线程入口执行（见
   :func:`configure_worker_thread` / :func:`worker_thread_scope`），退出时
   必须 :func:`revert_mmcss` 成对恢复。
4. W8 线程优先级：``SetThreadPriority(THREAD_PRIORITY_TIME_CRITICAL)`` ——仅
   专用解码/渲染线程，**绝不用于 UI 主线程**（函数内有主线程守卫）。

三档语义（``mode``）::

    performance = 关进程节流 + 关线程节流 + 钉核 + MMCSS + 提权
    balanced    = 关进程节流 + 关线程节流 + MMCSS（不钉核、不提权）
    powersave   = 全部不动（默认档，见 PERFORMANCE_CEILING_PLAN.md 风险 §7）

句柄 vs 线程 ID 约定
--------------------
* ``SetThreadSelectedCpuSets`` / ``SetThreadInformation`` /
  ``SetThreadPriority`` 取 **HANDLE**：在调用线程内用 ``GetCurrentThread()``
  的伪句柄即可；跨线程操作他人时用 ``OpenThread`` 打开真实句柄。
* ``AvSetMmThreadCharacteristics`` **不需要句柄**——它只注册调用线程。

非 Windows 平台（或 DLL 缺失/无权限）下所有写操作返回 ``False``/``None``
并记一条 warning，不抛异常（静默降级）。
"""

from __future__ import annotations

import ctypes
import sys
import threading
from contextlib import contextmanager
from ctypes import wintypes
from typing import Any, Callable, Iterator, Literal, Optional

PerfProfile = Literal["performance", "balanced", "powersave"]

IS_WINDOWS: bool = sys.platform == "win32"

DEFAULT_PROFILE: PerfProfile = "powersave"

# ---------------------------------------------------------------------------
# 常量（来源：winnt.h / processthreadsapi.h / avrt.h / winbase.h）
# ---------------------------------------------------------------------------

# PROCESS_INFORMATION_CLASS
ProcessPowerThrottling: int = 4
PROCESS_POWER_THROTTLING_CURRENT_VERSION: int = 1
# ControlMask 位：选择要控制的节流机制；StateMask=0 表示全部关闭。
POWER_THROTTLING_PROCESS_EXECUTION_SPEED: int = 0x1
POWER_THROTTLING_PROCESS_IGNORE_TIMER_RESOLUTION: int = 0x4

# THREAD_INFORMATION_CLASS
ThreadPowerThrottling: int = 3
THREAD_POWER_THROTTLING_CURRENT_VERSION: int = 1
POWER_THROTTLING_THREAD_EXECUTION_SPEED: int = 0x1

THREAD_PRIORITY_TIME_CRITICAL: int = 15
THREAD_PRIORITY_HIGHEST: int = 2
THREAD_PRIORITY_ABOVE_NORMAL: int = 1
THREAD_PRIORITY_NORMAL: int = 0

THREAD_QUERY_LIMITED_INFORMATION: int = 0x0800
THREAD_SET_INFORMATION: int = 0x0020
THREAD_SET_LIMITED_INFORMATION: int = 0x0400
THREAD_QUERY_INFORMATION: int = 0x0040

MMCSS_TASK_PLAYBACK: str = "Playback"
MMCSS_TASK_AUDIO: str = "Audio"


class PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
    """进程级电源节流策略（winnt.h）。"""

    _fields_ = [
        ("Version", wintypes.ULONG),
        ("ControlMask", wintypes.ULONG),
        ("StateMask", wintypes.ULONG),
    ]


class THREAD_POWER_THROTTLING_STATE(ctypes.Structure):
    """线程级电源节流策略（winnt.h）。"""

    _fields_ = [
        ("Version", wintypes.ULONG),
        ("ControlMask", wintypes.ULONG),
        ("StateMask", wintypes.ULONG),
    ]


def _log_warning(message: str) -> None:
    """记录降级 warning（app_logger 不可用时回退标准库日志）。"""
    try:
        from freeassetfilter.utils.app_logger import warning

        warning(message)
    except Exception:  # noqa: BLE001  # 日志本身绝不能抛异常
        import logging

        logging.getLogger(__name__).warning(message)


# ---------------------------------------------------------------------------
# DLL 绑定（模块级可 monkeypatch 变量，单测用 fake 替换）
# ---------------------------------------------------------------------------

_kernel32: Any = None
_avrt: Any = None


def _ensure_bindings() -> bool:
    """惰性绑定 kernel32/avrt，返回 False 表示不可用（非 Windows/DLL 缺失）。

    Returns:
        是否可用。不可用时调用方应静默降级。
    """
    global _kernel32, _avrt
    if not IS_WINDOWS:
        return False
    if _kernel32 is not None:
        return True
    try:
        _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _kernel32.SetProcessInformation.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        _kernel32.SetProcessInformation.restype = wintypes.BOOL
        _kernel32.SetThreadInformation.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.ULONG,
        ]
        _kernel32.SetThreadInformation.restype = wintypes.BOOL
        _kernel32.GetThreadInformation.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.ULONG,
        ]
        _kernel32.GetThreadInformation.restype = wintypes.BOOL
        # 关键顺序：(Thread, CpuSetIds, Count)——数组在前、Count 在后。
        _kernel32.SetThreadSelectedCpuSets.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.ULONG),
            wintypes.ULONG,
        ]
        _kernel32.SetThreadSelectedCpuSets.restype = wintypes.BOOL
        _kernel32.GetThreadSelectedCpuSets.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.ULONG),
            wintypes.ULONG,
            ctypes.POINTER(wintypes.ULONG),
        ]
        _kernel32.GetThreadSelectedCpuSets.restype = wintypes.BOOL
        _kernel32.GetSystemCpuSetInformation.argtypes = [
            wintypes.LPVOID,
            wintypes.ULONG,
            ctypes.POINTER(wintypes.ULONG),
            wintypes.HANDLE,
            wintypes.ULONG,
        ]
        _kernel32.GetSystemCpuSetInformation.restype = wintypes.BOOL
        _kernel32.SetThreadPriority.argtypes = [wintypes.HANDLE, ctypes.c_int]
        _kernel32.SetThreadPriority.restype = wintypes.BOOL
        _kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        _kernel32.GetCurrentThread.restype = wintypes.HANDLE
    except Exception as exc:  # noqa: BLE001  # 绑定失败即整体不可用
        _kernel32 = None
        _log_warning(f"platform_threads: kernel32 绑定失败，电源/亲和控制降级: {exc}")
        return False
    try:
        _avrt = ctypes.WinDLL("avrt", use_last_error=True)
        _avrt.AvSetMmThreadCharacteristicsW.argtypes = [
            wintypes.LPCWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        _avrt.AvSetMmThreadCharacteristicsW.restype = wintypes.HANDLE
        _avrt.AvRevertMmThreadCharacteristics.argtypes = [wintypes.HANDLE]
        _avrt.AvRevertMmThreadCharacteristics.restype = wintypes.BOOL
    except Exception as exc:  # noqa: BLE001  # 无 MMCSS 服务时仅该分支降级
        _avrt = None
        _log_warning(f"platform_threads: avrt 绑定失败，MMCSS 降级: {exc}")
    return True


def is_power_available() -> bool:
    """探测电源/亲和控制是否可用。

    Returns:
        Windows 且 kernel32 绑定成功时为 True，否则 False。
    """
    return _ensure_bindings()


def get_current_thread_handle() -> Any:
    """返回调用线程的伪句柄（仅调用线程内有效）。

    Returns:
        ``GetCurrentThread()`` 伪句柄；非 Windows 返回 None。
    """
    if not _ensure_bindings():
        return None
    return _kernel32.GetCurrentThread()


def open_thread_handle(thread_id: int) -> Any:
    """为指定线程 ID 打开真实句柄（跨线程操作他人时用）。

    Args:
        thread_id: ``GetCurrentThreadId`` 意义下的 OS 线程 ID。

    Returns:
        真实线程句柄（用后 ``CloseHandle``），失败返回 None。
    """
    if not _ensure_bindings():
        return None
    try:
        access = THREAD_SET_LIMITED_INFORMATION | THREAD_QUERY_LIMITED_INFORMATION
        handle = _kernel32.OpenThread(access, False, thread_id)
    except Exception as exc:  # noqa: BLE001  # OpenThread 未绑定/失败即降级
        _log_warning(f"platform_threads: OpenThread({thread_id}) 失败: {exc}")
        return None
    return handle or None


def apply_process_power_policy(mode: PerfProfile = DEFAULT_PROFILE) -> bool:
    """应用进程级电源节流策略（W2）。

    performance/balanced：``SetProcessInformation(ProcessPowerThrottling,
    {Version=1, ControlMask=EXECUTION_SPEED|IGNORE_TIMER_RESOLUTION,
    StateMask=0})`` 关闭进程级节流；powersave：不动，直接返回 True。

    Args:
        mode: 三档之一。

    Returns:
        生效（或 powersave 下无需生效）返回 True；无权限/不可用返回 False。
    """
    if mode == "powersave":
        return True
    if not _ensure_bindings():
        _log_warning("platform_threads: 电源控制不可用，进程节流策略降级跳过")
        return False
    try:
        state = PROCESS_POWER_THROTTLING_STATE()
        state.Version = PROCESS_POWER_THROTTLING_CURRENT_VERSION
        state.ControlMask = (
            POWER_THROTTLING_PROCESS_EXECUTION_SPEED
            | POWER_THROTTLING_PROCESS_IGNORE_TIMER_RESOLUTION
        )
        state.StateMask = 0  # 0 = 关闭上述节流机制
        ok = bool(
            _kernel32.SetProcessInformation(
                _kernel32.GetCurrentProcess(),
                ProcessPowerThrottling,
                ctypes.byref(state),
                ctypes.sizeof(state),
            )
        )
    except Exception as exc:  # noqa: BLE001  # 无权限等一律降级不抛异常
        _log_warning(f"platform_threads: SetProcessInformation 失败（可能无权限）: {exc}")
        return False
    if not ok:
        _log_warning("platform_threads: SetProcessInformation 返回 FALSE，进程节流未关闭")
    return ok


def set_thread_throttling(thread_handle: Any, disable: bool = True) -> bool:
    """开关指定线程的电源节流（W2，HANDLE 版）。

    Args:
        thread_handle: 线程 HANDLE（调用线程内传 ``GetCurrentThread()`` 伪句柄）。
        disable: True=关闭节流，False=恢复默认。

    Returns:
        成功 True；不可用/失败 False。
    """
    if not _ensure_bindings():
        return False
    if not thread_handle:
        return False
    try:
        state = THREAD_POWER_THROTTLING_STATE()
        state.Version = THREAD_POWER_THROTTLING_CURRENT_VERSION
        state.ControlMask = POWER_THROTTLING_THREAD_EXECUTION_SPEED
        state.StateMask = 0 if disable else POWER_THROTTLING_THREAD_EXECUTION_SPEED
        return bool(
            _kernel32.SetThreadInformation(
                thread_handle,
                ThreadPowerThrottling,
                ctypes.byref(state),
                ctypes.sizeof(state),
            )
        )
    except Exception as exc:  # noqa: BLE001  # 无权限等一律降级
        _log_warning(f"platform_threads: SetThreadInformation 失败: {exc}")
        return False


def readback_thread_throttling(thread_handle: Any) -> Optional[bool]:
    """回读线程节流状态（W2 直接证据）。

    Args:
        thread_handle: 线程 HANDLE。

    Returns:
        True=节流已关，False=仍受节流，None=不可读。
    """
    if not _ensure_bindings():
        return None
    if not thread_handle:
        return None
    try:
        state = THREAD_POWER_THROTTLING_STATE()
        state.Version = THREAD_POWER_THROTTLING_CURRENT_VERSION
        state.ControlMask = POWER_THROTTLING_THREAD_EXECUTION_SPEED
        ok = bool(
            _kernel32.GetThreadInformation(
                thread_handle,
                ThreadPowerThrottling,
                ctypes.byref(state),
                ctypes.sizeof(state),
            )
        )
    except Exception as exc:  # noqa: BLE001  # 回读失败记 None
        _log_warning(f"platform_threads: GetThreadInformation 失败: {exc}")
        return None
    if not ok:
        return None
    masked = state.StateMask & POWER_THROTTLING_THREAD_EXECUTION_SPEED
    return bool(masked == 0)


def pin_thread_to_cpu_set(thread_handle: Any, cpu_set_ids: list[int]) -> bool:
    """把线程钉到指定 CPU 集（W3）。

    真实签名 ``SetThreadSelectedCpuSets(HANDLE Thread, PULONG CpuSetIds,
    ULONG CpuSetIdsCount)``——**数组在前、Count 在后**，顺序错会破坏栈。

    Args:
        thread_handle: 线程 HANDLE。
        cpu_set_ids: CPU 集 ID 列表（见 :func:`detect_cpu_topology`）。

    Returns:
        成功 True；空列表/不可用/失败 False。
    """
    if not _ensure_bindings():
        return False
    if not thread_handle or not cpu_set_ids:
        return False
    try:
        ids = (wintypes.ULONG * len(cpu_set_ids))(*cpu_set_ids)
        # 注意：arg order = (Thread, CpuSetIds, Count)，与文档一致。
        return bool(
            _kernel32.SetThreadSelectedCpuSets(
                thread_handle, ids, wintypes.ULONG(len(cpu_set_ids))
            )
        )
    except Exception as exc:  # noqa: BLE001  # 无权限等一律降级
        _log_warning(f"platform_threads: SetThreadSelectedCpuSets 失败: {exc}")
        return False


def readback_thread_cpu_sets(thread_handle: Any) -> Optional[list[int]]:
    """回读线程当前 CPU 集（W3 直接证据）。

    Args:
        thread_handle: 线程 HANDLE。

    Returns:
        CPU 集 ID 列表；不可读返回 None。
    """
    if not _ensure_bindings():
        return None
    if not thread_handle:
        return None
    try:
        required = wintypes.ULONG(0)
        _kernel32.GetThreadSelectedCpuSets(thread_handle, None, 0, ctypes.byref(required))
        count = int(required.value)
        if count <= 0:
            return []
        ids = (wintypes.ULONG * count)()
        ok = bool(
            _kernel32.GetThreadSelectedCpuSets(
                thread_handle, ids, wintypes.ULONG(count), ctypes.byref(required)
            )
        )
        if not ok:
            return None
        out: list[int] = []
        for i in range(int(required.value)):
            item = ids[i]
            out.append(item.value if hasattr(item, "value") else item)
        return out
    except Exception as exc:  # noqa: BLE001  # 回读失败记 None
        _log_warning(f"platform_threads: GetThreadSelectedCpuSets 回读失败: {exc}")
        return None


def detect_cpu_topology() -> dict:
    """枚举 CPU 集并区分 P/E 核（275HX 大小核识别）。

    ``GetSystemCpuSetInformation`` 两遍调用取 ``SYSTEM_CPU_SET_INFORMATION``
    数组；``EfficiencyClass`` 越高越省电（E 核），最低为 P 核。结构体按原始
    字节解析（x64 偏移：Id@8, LogicalProcessorIndex@14, EfficiencyClass@18），
    避免 ctypes 联合体对齐坑。

    Returns:
        ``{"available": bool, "cpu_sets": [...], "p_core_ids": [...],
        "e_core_ids": [...]}``；不可用时 ``available=False`` 且列表为空。
    """
    empty: dict = {
        "available": False,
        "cpu_sets": [],
        "p_core_ids": [],
        "e_core_ids": [],
    }
    if not _ensure_bindings():
        return empty
    try:
        returned = wintypes.ULONG(0)
        _kernel32.GetSystemCpuSetInformation(None, 0, ctypes.byref(returned), None, 0)
        size = int(returned.value)
        if size <= 0:
            return empty
        buf = (ctypes.c_ubyte * size)()
        ok = bool(
            _kernel32.GetSystemCpuSetInformation(
                buf, wintypes.ULONG(size), ctypes.byref(returned), None, 0
            )
        )
        if not ok:
            return empty
        import struct

        raw = bytes(buf[: int(returned.value)])
        sets: list[dict] = []
        offset = 0
        while offset + 8 <= len(raw):
            entry_size, entry_type = struct.unpack_from("<IB", raw, offset)
            if entry_size < 8 or offset + entry_size > len(raw):
                break
            if entry_type == 0 and entry_size >= 24:  # CpuSetInformation
                cpu_id, group = struct.unpack_from("<IH", raw, offset + 8)
                lpi, _, _, _, eff = struct.unpack_from("<BBBBB", raw, offset + 14)
                sets.append(
                    {
                        "id": int(cpu_id),
                        "group": int(group),
                        "logical_processor_index": int(lpi),
                        "efficiency_class": int(eff),
                    }
                )
            offset += int(entry_size)
        if not sets:
            return empty
        classes = sorted({s["efficiency_class"] for s in sets})
        lo, hi = classes[0], classes[-1]
        p_ids = [s["id"] for s in sets if s["efficiency_class"] == lo]
        e_ids = [s["id"] for s in sets if s["efficiency_class"] == hi] if hi != lo else []
        return {
            "available": True,
            "cpu_sets": sets,
            "p_core_ids": p_ids,
            "e_core_ids": e_ids,
        }
    except Exception as exc:  # noqa: BLE001  # 枚举失败即不可用
        _log_warning(f"platform_threads: CPU 拓扑枚举失败: {exc}")
        return empty


def register_mmcss(task_name: str) -> Optional[Any]:
    """注册 MMCSS（W4）——**只作用于调用线程**。

    必须在目标工作线程入口的第一行调用（见 :func:`worker_thread_scope`），
    从主线程为他人调用是无效的（最常见的实现错误）。

    Args:
        task_name: ``"Playback"``（解码/合成线程）或 ``"Audio"``（音频线程）。

    Returns:
        MMCSS 句柄（线程退出时传给 :func:`revert_mmcss`）；不可用返回 None。
    """
    if not _ensure_bindings() or _avrt is None:
        return None
    try:
        index = wintypes.DWORD(0)
        handle = _avrt.AvSetMmThreadCharacteristicsW(task_name, ctypes.byref(index))
    except Exception as exc:  # noqa: BLE001  # 无 MMCSS 服务时降级
        _log_warning(f"platform_threads: AvSetMmThreadCharacteristics 失败: {exc}")
        return None
    return handle or None


def revert_mmcss(handle: Any) -> bool:
    """恢复 MMCSS 注册（W4，必须与 :func:`register_mmcss` 成对）。

    Args:
        handle: :func:`register_mmcss` 返回的句柄；None 直接返回 True。

    Returns:
        成功（或无需恢复）True，否则 False。
    """
    if handle is None:
        return True
    if not _ensure_bindings() or _avrt is None:
        return False
    try:
        return bool(_avrt.AvRevertMmThreadCharacteristics(handle))
    except Exception as exc:  # noqa: BLE001  # 恢复失败记 warning
        _log_warning(f"platform_threads: AvRevertMmThreadCharacteristics 失败: {exc}")
        return False


def _handle_int_value(handle: Any) -> Optional[int]:
    """取 HANDLE 整数值（int / c_void_p 均可；ctypes HWND 式对象取 .value）。

    Args:
        handle: 线程 HANDLE。

    Returns:
        整数句柄值；取不到返回 None。
    """
    if handle is None:
        return None
    if isinstance(handle, int):
        return handle
    try:
        value = getattr(handle, "value", None)
    except Exception:  # noqa: BLE001  # 兜底走 operator.index
        value = None
    if isinstance(value, int):
        return value
    try:
        import operator

        return operator.index(handle)
    except Exception:  # noqa: BLE001  # 不可比对时返回 None（调用方保守处理）
        return None


def set_thread_priority(thread_handle: Any, level: int) -> bool:
    """设置线程优先级（W8）。

    ``THREAD_PRIORITY_TIME_CRITICAL(15)`` 仅用于专用解码/渲染线程；若调用
    线程就是 UI 主线程且目标句柄指向调用线程自身（``GetCurrentThread()``
    伪句柄），直接拒绝并返回 False（防输入饥饿）。比对失败时保守拒绝。

    Args:
        thread_handle: 线程 HANDLE。
        level: 优先级（15=TIME_CRITICAL 等）。

    Returns:
        成功 True；主线程提权拒绝/不可用/失败 False。
    """
    if not _ensure_bindings():
        return False
    if not thread_handle:
        return False
    if int(level) >= THREAD_PRIORITY_TIME_CRITICAL:
        try:
            caller_is_main = threading.current_thread() is threading.main_thread()
        except Exception:  # noqa: BLE001  # 取不到则保守为 True
            caller_is_main = True
        if caller_is_main:
            try:
                pseudo = _handle_int_value(_kernel32.GetCurrentThread())
                target = _handle_int_value(thread_handle)
                is_self = pseudo is not None and target is not None and pseudo == target
            except Exception:  # noqa: BLE001  # 比对失败保守视为自身
                is_self = True
            if is_self:
                _log_warning("platform_threads: 拒绝给 UI 主线程设置 TIME_CRITICAL")
                return False
    try:
        return bool(_kernel32.SetThreadPriority(thread_handle, int(level)))
    except Exception as exc:  # noqa: BLE001  # 无权限等一律降级
        _log_warning(f"platform_threads: SetThreadPriority 失败: {exc}")
        return False


# ---------------------------------------------------------------------------
# 稀疏集成：工作线程入口钩子
# ---------------------------------------------------------------------------

Role = Literal["decode", "playback", "audio", "render", "ui"]


def configure_worker_thread(
    role: Role = "decode",
    mode: PerfProfile = DEFAULT_PROFILE,
    on_mmcss: Optional[Callable[[Any], None]] = None,
) -> dict:
    """工作线程入口钩子（必须在目标线程内第一行调用）。

    按三档语义配置**调用线程自身**：线程节流开关 + CPU 集钉核 + MMCSS 注册 +
    优先级提升。调用方负责在线程退出时 :func:`revert_mmcss`（或直接用
    :func:`worker_thread_scope` 包裹整个线程体）。

    Args:
        role: ``decode``（E 核 + Playback + 提权）/ ``playback``（P 核 +
            Playback + 提权）/ ``audio``（P 核 + Audio + 提权）/
            ``render``（P 核 + Playback + 提权）/ ``ui``（仅关线程节流，
            永不钉核/提权）。
        mode: 三档；powersave 直接返回全跳过。
        on_mmcss: 可选回调，收到 MMCSS 句柄（测试/埋点用）。

    Returns:
        ``{"throttling": bool, "pinned": bool, "mmcss": handle|None,
        "priority": bool}`` 执行纪要。
    """
    summary: dict = {"throttling": False, "pinned": False, "mmcss": None, "priority": False}
    if mode == "powersave":
        return summary
    handle = get_current_thread_handle()
    if handle is None:
        return summary
    summary["throttling"] = set_thread_throttling(handle, disable=True)
    if mode == "balanced" or role == "ui":
        # balanced 不钉核不提权；ui 永不钉核/提权。MMCSS 仍注册（低风险）。
        summary["mmcss"] = register_mmcss(
            MMCSS_TASK_AUDIO if role == "audio" else MMCSS_TASK_PLAYBACK
        )
        if on_mmcss is not None and summary["mmcss"] is not None:
            on_mmcss(summary["mmcss"])
        return summary
    # performance 档：钉核 + MMCSS + 提权。
    topology = detect_cpu_topology()
    if topology["available"]:
        ids = topology["e_core_ids"] if role == "decode" else topology["p_core_ids"]
        if ids:
            summary["pinned"] = pin_thread_to_cpu_set(handle, ids)
    summary["mmcss"] = register_mmcss(
        MMCSS_TASK_AUDIO if role == "audio" else MMCSS_TASK_PLAYBACK
    )
    if on_mmcss is not None and summary["mmcss"] is not None:
        on_mmcss(summary["mmcss"])
    summary["priority"] = set_thread_priority(handle, THREAD_PRIORITY_TIME_CRITICAL)
    return summary


@contextmanager
def worker_thread_scope(
    role: Role = "decode", mode: PerfProfile = DEFAULT_PROFILE
) -> Iterator[dict]:
    """工作线程体上下文（线程内使用）：入口配置、出口成对 revert。

    Args:
        role: 见 :func:`configure_worker_thread`。
        mode: 三档；powersave 为空操作上下文。

    Yields:
        :func:`configure_worker_thread` 返回的执行纪要。
    """
    summary = configure_worker_thread(role=role, mode=mode)
    try:
        yield summary
    finally:
        revert_mmcss(summary.get("mmcss"))
