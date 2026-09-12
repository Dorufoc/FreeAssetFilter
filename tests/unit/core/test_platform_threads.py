"""W2/W3/W4/W8 platform_threads 单测（tests/unit/core/test_platform_threads.py）。

全部用 fake DLL + monkeypatch，不碰真实 WinAPI，可在 offscreen/CI 下运行。
覆盖：三档语义、优雅降级（无权限→False/None 不抛异常）、
``SetThreadSelectedCpuSets`` 参数顺序、MMCSS 在工作线程内注册/成对恢复、
TIME_CRITICAL 主线程守卫。
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Any

import pytest

import freeassetfilter.core.native.platform_threads as pt
from freeassetfilter.core.native.platform_threads import (
    THREAD_PRIORITY_TIME_CRITICAL,
    THREAD_POWER_THROTTLING_STATE,
)


class FakeKernel32:
    """kernel32 替身：记录调用，模拟成功语义。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.fail_next: dict[str, Exception] = {}
        self.thread_throttling_off: bool = True

    def _maybe_fail(self, name: str) -> None:
        exc = self.fail_next.pop(name, None)
        if exc is not None:
            raise exc

    def GetCurrentProcess(self) -> int:
        return 0x1234

    def GetCurrentThread(self) -> int:
        return -2  # 真实 GetCurrentThread() 伪句柄值

    def SetProcessInformation(self, *args: Any) -> bool:
        self.calls.append(("SetProcessInformation", args))
        self._maybe_fail("SetProcessInformation")
        return True

    def SetThreadInformation(self, *args: Any) -> bool:
        self.calls.append(("SetThreadInformation", args))
        self._maybe_fail("SetThreadInformation")
        return True

    def GetThreadInformation(self, handle: Any, cls: Any, info: Any, size: Any) -> bool:
        self.calls.append(("GetThreadInformation", (handle, cls)))
        state = ctypes.cast(info, ctypes.POINTER(THREAD_POWER_THROTTLING_STATE)).contents
        state.Version = 1
        state.ControlMask = 0x1
        state.StateMask = 0 if self.thread_throttling_off else 0x1
        return True

    def SetThreadSelectedCpuSets(self, thread: Any, ids: Any, count: Any) -> bool:
        # 顺序断言的关键：第二个位置必须是 ID 数组，第三个是 Count。
        # 注：ctypes 标量无 __int__（本机 int(c_ulong) 抛错），一律取 .value。
        ids_list = [x.value if hasattr(x, "value") else x for x in ids]
        count_int = count.value if hasattr(count, "value") else count
        self.calls.append(("SetThreadSelectedCpuSets", (thread, ids_list, count_int)))
        self._maybe_fail("SetThreadSelectedCpuSets")
        return True

    def GetThreadSelectedCpuSets(
        self, thread: Any, ids: Any, count: Any, required: Any
    ) -> bool:
        out = ctypes.cast(required, ctypes.POINTER(wintypes.ULONG)).contents
        if ids is None:
            out.value = 2
            return False
        out.value = 2
        ids[0], ids[1] = 20, 21
        return True

    def SetThreadPriority(self, thread: Any, level: Any) -> bool:
        level_int = level.value if hasattr(level, "value") else level
        self.calls.append(("SetThreadPriority", (thread, level_int)))
        self._maybe_fail("SetThreadPriority")
        return True

    def OpenThread(self, access: Any, inherit: Any, tid: Any) -> int:
        return 0x5678

    def names(self) -> list[str]:
        """返回已记录的调用名序列。"""
        return [name for name, _ in self.calls]


class FakeAvrt:
    """avrt 替身：记录调用线程 ident，证明调用线程内注册。"""

    def __init__(self) -> None:
        self.registers: list[tuple[str, int]] = []
        self.reverts: list[tuple[Any, int]] = []

    def AvSetMmThreadCharacteristicsW(self, task_name: Any, index: Any) -> int:
        ident = threading.get_ident()
        self.registers.append((str(task_name), ident))
        ctypes.cast(index, ctypes.POINTER(wintypes.DWORD)).contents.value = 1
        return 0xABCD

    def AvRevertMmThreadCharacteristics(self, handle: Any) -> bool:
        self.reverts.append((handle, threading.get_ident()))
        return True


@pytest.fixture()
def fakes(monkeypatch: pytest.MonkeyPatch) -> tuple[FakeKernel32, FakeAvrt]:
    """注入 fake DLL 并强制绑定可用。"""
    kernel = FakeKernel32()
    avrt = FakeAvrt()
    monkeypatch.setattr(pt, "_kernel32", kernel)
    monkeypatch.setattr(pt, "_avrt", avrt)
    monkeypatch.setattr(pt, "_ensure_bindings", lambda: True)
    return kernel, avrt


@pytest.fixture()
def no_power(monkeypatch: pytest.MonkeyPatch) -> None:
    """模拟非 Windows / DLL 缺失：绑定不可用。"""
    monkeypatch.setattr(pt, "_kernel32", None)
    monkeypatch.setattr(pt, "_avrt", None)
    monkeypatch.setattr(pt, "_ensure_bindings", lambda: False)


def _topology(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pt,
        "detect_cpu_topology",
        lambda: {
            "available": True,
            "cpu_sets": [],
            "p_core_ids": [0, 1],
            "e_core_ids": [20, 21],
        },
    )


# --- 三档语义 ---------------------------------------------------------------


def test_process_policy_three_modes(
    fakes: tuple[FakeKernel32, FakeAvrt],
) -> None:
    """三档进程策略：powersave 不动，其余关进程节流。"""
    kernel, _ = fakes
    assert pt.apply_process_power_policy("powersave") is True
    assert kernel.names() == []
    assert pt.apply_process_power_policy("balanced") is True
    assert pt.apply_process_power_policy("performance") is True
    proc_calls = [c for c in kernel.calls if c[0] == "SetProcessInformation"]
    assert len(proc_calls) == 2
    _, args = proc_calls[0]
    assert int(args[1]) == pt.ProcessPowerThrottling
    state = ctypes.cast(args[2], ctypes.POINTER(pt.PROCESS_POWER_THROTTLING_STATE)).contents
    assert state.Version == 1
    assert state.StateMask == 0
    assert state.ControlMask & 0x1


def test_process_policy_failure_degrades(
    fakes: tuple[FakeKernel32, FakeAvrt],
) -> None:
    """无权限（抛异常）→ 返回 False，不抛异常。"""
    kernel, _ = fakes
    kernel.fail_next["SetProcessInformation"] = OSError("access denied")
    assert pt.apply_process_power_policy("performance") is False


def test_configure_worker_three_modes(
    fakes: tuple[FakeKernel32, FakeAvrt], monkeypatch: pytest.MonkeyPatch
) -> None:
    """线程钩子三档：performance 全开，balanced 不钉核不提权，powersave 全跳过。"""
    kernel, _ = fakes
    _topology(monkeypatch)
    # performance 全开必须在工作线程内调用（主线程内提权被守卫拒绝是正确的）。
    outcome: dict[str, Any] = {}

    def entry() -> None:
        outcome["perf"] = pt.configure_worker_thread(role="decode", mode="performance")

    worker = threading.Thread(target=entry, name="configure-probe")
    worker.start()
    worker.join(timeout=10)
    assert not worker.is_alive()
    perf = outcome["perf"]
    assert perf["throttling"] is True
    assert perf["pinned"] is True
    assert perf["mmcss"] == 0xABCD
    assert perf["priority"] is True
    pin_calls = [c for c in kernel.calls if c[0] == "SetThreadSelectedCpuSets"]
    assert pin_calls and pin_calls[0][1][1] == [20, 21]  # decode → E 核

    kernel.calls.clear()
    bal = pt.configure_worker_thread(role="decode", mode="balanced")
    assert bal["throttling"] is True
    assert bal["pinned"] is False
    assert bal["mmcss"] == 0xABCD
    assert bal["priority"] is False
    assert "SetThreadSelectedCpuSets" not in kernel.names()
    assert "SetThreadPriority" not in kernel.names()

    kernel.calls.clear()
    save = pt.configure_worker_thread(role="decode", mode="powersave")
    assert save == {"throttling": False, "pinned": False, "mmcss": None, "priority": False}
    assert kernel.calls == []


def test_ui_role_never_pinned_or_boosted(
    fakes: tuple[FakeKernel32, FakeAvrt], monkeypatch: pytest.MonkeyPatch
) -> None:
    """ui role 在 performance 档也不钉核/提权。"""
    kernel, _ = fakes
    _topology(monkeypatch)
    summary = pt.configure_worker_thread(role="ui", mode="performance")
    assert summary["pinned"] is False
    assert summary["priority"] is False
    assert "SetThreadSelectedCpuSets" not in kernel.names()
    assert "SetThreadPriority" not in kernel.names()


# --- 优雅降级 ---------------------------------------------------------------


def test_graceful_degradation(no_power: None) -> None:
    """绑定不可用：全部返回 False/None，不抛异常；revert(None) 为 True。"""
    assert pt.is_power_available() is False
    assert pt.apply_process_power_policy("performance") is False
    assert pt.set_thread_throttling(object(), True) is False
    assert pt.pin_thread_to_cpu_set(object(), [0]) is False
    assert pt.readback_thread_throttling(object()) is None
    assert pt.readback_thread_cpu_sets(object()) is None
    assert pt.register_mmcss("Playback") is None
    assert pt.revert_mmcss(None) is True
    assert pt.revert_mmcss(object()) is False
    assert pt.set_thread_priority(object(), THREAD_PRIORITY_TIME_CRITICAL) is False
    assert pt.detect_cpu_topology()["available"] is False
    assert pt.get_current_thread_handle() is None
    summary = pt.configure_worker_thread(role="decode", mode="performance")
    assert summary["mmcss"] is None


# --- CPU 集参数顺序 ------------------------------------------------------------


def test_pin_arg_order_ids_before_count(
    fakes: tuple[FakeKernel32, FakeAvrt],
) -> None:
    """SetThreadSelectedCpuSets 按 (Thread, CpuSetIds, Count) 顺序调用。"""
    kernel, _ = fakes
    assert pt.pin_thread_to_cpu_set(-2, [20, 21]) is True
    name, recorded = kernel.calls[0]
    assert name == "SetThreadSelectedCpuSets"
    thread, ids, count = recorded
    assert thread == -2
    assert ids == [20, 21]  # 数组在前
    assert count == 2  # Count 在后
    assert pt.pin_thread_to_cpu_set(-2, []) is False  # 空列表拒绝


def test_readback_proves_pin(fakes: tuple[FakeKernel32, FakeAvrt]) -> None:
    """回读 CPU 集：直接证据（非“返回 True 即成功”）。"""
    assert pt.readback_thread_cpu_sets(-2) == [20, 21]
    assert pt.readback_thread_throttling(-2) is True


# --- MMCSS：调用线程内注册 + 成对恢复 --------------------------------------------


def test_mmcss_registers_inside_worker_thread(
    fakes: tuple[FakeKernel32, FakeAvrt],
) -> None:
    """MMCSS 注册发生在目标工作线程内（记录 ident），主线程只负责断言。"""
    _, avrt = fakes
    main_ident = threading.get_ident()
    outcome: dict[str, Any] = {}

    def entry() -> None:
        handle = pt.register_mmcss("Playback")
        outcome["handle"] = handle
        outcome["reverted"] = pt.revert_mmcss(handle)

    worker = threading.Thread(target=entry, name="mmcss-probe")
    worker.start()
    worker.join(timeout=10)
    assert not worker.is_alive()
    assert outcome["handle"] == 0xABCD
    assert outcome["reverted"] is True
    assert len(avrt.registers) == 1
    task_name, worker_ident = avrt.registers[0]
    assert task_name == "Playback"
    assert worker_ident != main_ident  # 注册在工作线程内，不在主线程
    assert avrt.reverts == [(0xABCD, worker_ident)]  # 同线程成对恢复


def test_worker_scope_reverts_on_exception(
    fakes: tuple[FakeKernel32, FakeAvrt], monkeypatch: pytest.MonkeyPatch
) -> None:
    """线程体抛异常时 scope 仍成对 revert。"""
    _, avrt = fakes
    _topology(monkeypatch)

    class Boom(RuntimeError):
        pass

    with pytest.raises(Boom), pt.worker_thread_scope(role="decode", mode="performance"):
        raise Boom()
    assert len(avrt.registers) == 1
    assert len(avrt.reverts) == 1


# --- 优先级守卫 ---------------------------------------------------------------


def test_priority_refuses_time_critical_on_main_thread(
    fakes: tuple[FakeKernel32, FakeAvrt],
) -> None:
    """主线程 + 自身伪句柄 + TIME_CRITICAL → 拒绝且不调用 API。"""
    kernel, _ = fakes
    assert threading.current_thread() is threading.main_thread()
    assert pt.set_thread_priority(-2, THREAD_PRIORITY_TIME_CRITICAL) is False
    assert "SetThreadPriority" not in kernel.names()
    # 普通优先级在主线程允许（返回 fake 成功）。
    assert pt.set_thread_priority(-2, pt.THREAD_PRIORITY_NORMAL) is True


def test_priority_allowed_on_worker_thread(
    fakes: tuple[FakeKernel32, FakeAvrt],
) -> None:
    """工作线程内自身提权允许（调用者非主线程）。"""
    kernel, _ = fakes
    outcome: dict[str, Any] = {}

    def entry() -> None:
        outcome["ok"] = pt.set_thread_priority(-2, THREAD_PRIORITY_TIME_CRITICAL)

    worker = threading.Thread(target=entry, name="prio-probe")
    worker.start()
    worker.join(timeout=10)
    assert outcome["ok"] is True
    assert ("SetThreadPriority", (-2, 15)) in kernel.calls
