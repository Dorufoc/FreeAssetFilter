# -*- coding: utf-8 -*-
"""``DriveListLoaderThread`` / ``_DriveAvailabilityCheckRunnable`` 单元测试。

覆盖（happy + boundary/error 各至少一条）：

* ``DriveListLoaderThread`` —— **同步调用 ``run()``**（learnings W7：
  ``QThread.start()`` 的 run 本体在 Qt 原生线程执行，coverage 无法追踪），
  mock 盘符位掩码（禁止真实枚举整机磁盘）；覆盖 GetLogicalDrives 失败
  warning、mpr WNetOpenEnumW 失败、完整网络枚举（NETRESOURCE → wstring_at
  → 去重）、WinDLL 加载失败 debug、外层异常 error、非 Windows 回退 ``['/']``
* ``_DriveAvailabilityCheckRunnable`` —— 存在目录返回 True、不存在路径
  返回 False、路径缺失尾分隔符时自动补齐、空目录 StopIteration 分支、
  OSError/PermissionError 分支、兜底 Exception 分支

线程纪律（AGENTS.md / learnings W7）：信号等待全部经同步直连的断言；
任何路径都**不启动真实后台线程**（禁止真实盘符/网络扫描）。
"""
from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Any, List, Tuple

import pytest
from unittest.mock import patch

from freeassetfilter.core.workers import drive_list_loader as _dl
from freeassetfilter.core.workers.drive_list_loader import (
    DriveListLoaderThread,
    _DriveAvailabilityCheckRunnable,
    _DriveAvailabilitySignals,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# mpr 假 DLL
# ---------------------------------------------------------------------------
class _FakeMpr:
    """``ctypes.WinDLL('mpr')`` 替身：枚举立即失败，避免真实网络扫描。"""

    def WNetOpenEnumW(self, *_args: Any, **_kwargs: Any) -> int:
        """返回非零错误码以跳过网络位置枚举。"""
        return 58  # ERROR_BAD_NET_RESP —— 挂起 if 分支

    def WNetCloseEnum(self, *_args: Any, **_kwargs: Any) -> int:
        """空实现。"""
        return 0


class _NetResource(ctypes.Structure):
    """与 run() 内 NETRESOURCE 对齐的 ctypes 结构（写入假枚举缓冲区用）。"""

    _fields_ = [
        ("dwScope", wintypes.DWORD),
        ("dwType", wintypes.DWORD),
        ("dwDisplayType", wintypes.DWORD),
        ("dwUsage", wintypes.DWORD),
        ("lpLocalName", ctypes.c_wchar_p),
        ("lpRemoteName", ctypes.c_wchar_p),
        ("lpComment", ctypes.c_wchar_p),
        ("lpProvider", ctypes.c_wchar_p),
    ]


class _FakeMprEnum:
    """成功枚举一次网络位置：第一次返回 0 并写一个 NETRESOURCE，第二次返回非零。"""

    def __init__(self) -> None:
        self._calls: int = 0
        self.closed: int = 0
        # 结构体引用必须存活到 run() 读取指针时（c_wchar_p 指向的缓冲驻留于此）。
        self._struct = _NetResource(
            wintypes.DWORD(1),
            wintypes.DWORD(0),
            wintypes.DWORD(0),
            wintypes.DWORD(0),
            ctypes.c_wchar_p("Z:"),  # lpLocalName —— 追加到本地盘符
            ctypes.c_wchar_p(r"\\server\share"),  # lpRemoteName —— 追加到网络位置
            None,
            None,
        )

    def WNetOpenEnumW(self, *_args: Any, **_kwargs: Any) -> int:
        """返回 0，进入枚举块。"""
        return 0

    def WNetEnumResourceW(self, _h: Any, count: Any, buf: Any, buf_size: Any) -> int:
        """第一次写 NETRESOURCE 到 buf 并置 count=1；此后返回非零结束循环。

        Args:
            _h: 枚举句柄（忽略）。
            count: ``byref`` 指向的 DWORD（CArgObject，经 cast 写入）。
            buf: ``create_string_buffer``（字符数组，memmove 写入）。
            buf_size: ``byref`` 指向的 DWORD 缓冲区大小（CArgObject）。

        Returns:
            int: 0 表示继续，非零表示枚举结束。
        """
        self._calls += 1
        if self._calls == 1:
            # CArgObject（byref 产物）无 .contents —— 须 cast 成指针再写值。
            ctypes.cast(count, ctypes.POINTER(ctypes.c_ulong)).contents.value = 1
            ctypes.cast(buf_size, ctypes.POINTER(ctypes.c_ulong)).contents.value = (
                ctypes.sizeof(_NetResource)
            )
            ctypes.memmove(buf, ctypes.byref(self._struct), ctypes.sizeof(_NetResource))
            return 0
        return 1  # 非零 → while 中 break

    def WNetCloseEnum(self, _h: Any) -> int:
        """记录关闭次数。"""
        self.closed += 1
        return 0


# ---------------------------------------------------------------------------
# DriveListLoaderThread —— 同步 run()
# ---------------------------------------------------------------------------
def test_drive_list_loader_emits_mocked_drives(qapp: Any) -> None:
    """happy：mock GetLogicalDrives 后 loaded 信号携带排序去重盘符列表。

    test_manual: ``patch('ctypes.windll.kernel32.GetLogicalDrives')`` 制造
    位掩码 ``0b101``（A、C 盘），mock ``ctypes.WinDLL`` 为 ``_FakeMpr``
    （WNetOpenEnumW 返回 58 跳过网络枚举），``thread.run()`` 同步执行后
    loaded 为 ``(['A:', 'C:'], [])``。

    Args:
        qapp: session QApplication。
    """
    if sys.platform != "win32":
        pytest.skip("仅 Windows 支持 ctypes.windll 盘符枚举")

    received: List[Tuple[List[str], List[str]]] = []
    with patch(
        "ctypes.windll.kernel32.GetLogicalDrives", return_value=0b101
    ), patch("ctypes.WinDLL", side_effect=lambda _n: _FakeMpr()):
        thread = DriveListLoaderThread()
        thread.loaded.connect(lambda drives, nets: received.append((drives, nets)))
        thread.run()

    assert received, "loaded 未发出"
    local_drives: List[str] = received[0][0]
    assert local_drives == ["A:", "C:"]
    # 网络位置列表 mock 场景下为空
    assert received[0][1] == []


def test_drive_list_loader_deduplicates_and_sorts(qapp: Any) -> None:
    """boundary：盘符结果排序 + 去重后经 loaded 发出。

    test_manual: 位掩码 0b1110（B、C、D 盘）断言排序结果。

    Args:
        qapp: session QApplication。
    """
    if sys.platform != "win32":
        pytest.skip("仅 Windows 支持 ctypes.windll 盘符枚举")

    received: List[Tuple[List[str], List[str]]] = []
    # 0b1110 = B、C、D 盘
    with patch(
        "ctypes.windll.kernel32.GetLogicalDrives", return_value=0b1110
    ), patch("ctypes.WinDLL", side_effect=lambda _n: _FakeMpr()):
        thread = DriveListLoaderThread()
        thread.loaded.connect(lambda drives, nets: received.append((drives, nets)))
        thread.run()

    assert received[0][0] == ["B:", "C:", "D:"]


def test_drive_list_loader_emits_root_on_non_win32(qapp: Any, monkeypatch: Any) -> None:
    """boundary：非 win32 平台回退为根目录 ['/']。

    test_manual: monkeypatch sys.platform='linux'，断言 loaded=['/']。

    Args:
        qapp: session QApplication。
        monkeypatch: pytest monkeypatch fixture。
    """
    received: List[Tuple[List[str], List[str]]] = []
    if sys.platform == "win32":
        monkeypatch.setattr(sys, "platform", "linux")
    thread = DriveListLoaderThread()
    thread.loaded.connect(lambda drives, nets: received.append((drives, nets)))
    thread.run()
    assert received[0][0] == ["/"]


def test_drive_list_loader_warns_when_getlogicaldrives_fails(
    qapp: Any, monkeypatch: Any
) -> None:
    """error：GetLogicalDrives 抛异常 → warning 分支，仍以空列表 emit。

    test_manual: patch GetLogicalDrives side_effect=OSError + WinDLL 假 DLL，
    断言 warning 被调用、loaded 发出空盘符/空网络列表。

    Args:
        qapp: session QApplication。
        monkeypatch: pytest monkeypatch fixture。
    """
    if sys.platform != "win32":
        pytest.skip("仅 Windows 支持 ctypes.windll 盘符枚举")

    warnings: List[str] = []
    monkeypatch.setattr(_dl, "warning", lambda msg: warnings.append(str(msg)))
    received: List[Tuple[List[str], List[str]]] = []
    with patch(
        "ctypes.windll.kernel32.GetLogicalDrives", side_effect=OSError("no api")
    ), patch("ctypes.WinDLL", side_effect=lambda _n: _FakeMpr()):
        thread = DriveListLoaderThread()
        thread.loaded.connect(lambda drives, nets: received.append((drives, nets)))
        thread.run()

    assert warnings and "失败" in warnings[0]
    assert received[0] == ([], [])


def test_drive_list_loader_enumerates_network_locations(qapp: Any) -> None:
    """happy：WNetOpenEnumW 成功 + 枚举一个 NETRESOURCE → 本地/网络都入列。

    使用 ``_FakeMprEnum``：GetLogicalDrives=0b101 得 A/C 盘；枚举的
    lpLocalName="Z:" 追加本地盘符、lpRemoteName="\\\\server\\share" 追加
    网络位置；断言去重排序后 loaded 输出。

    Args:
        qapp: session QApplication。
    """
    if sys.platform != "win32":
        pytest.skip("仅 Windows 支持 ctypes.windll 盘符枚举")

    fake_mpr = _FakeMprEnum()
    received: List[Tuple[List[str], List[str]]] = []
    with patch(
        "ctypes.windll.kernel32.GetLogicalDrives", return_value=0b101
    ), patch("ctypes.WinDLL", side_effect=lambda _n: fake_mpr):
        thread = DriveListLoaderThread()
        thread.loaded.connect(lambda drives, nets: received.append((drives, nets)))
        thread.run()

    assert received[0][0] == ["A:", "C:", "Z:"]
    assert received[0][1] == [r"\\server\share"]
    assert fake_mpr.closed == 1  # 枚举结束 finally 里关闭句柄


def test_drive_list_loader_debug_when_windll_fails(qapp: Any, monkeypatch: Any) -> None:
    """error：WinDLL('mpr') 加载失败 → debug 分支，保留本地盘符列表。

    test_manual: patch ctypes.WinDLL side_effect=OSError，断言 debug 被调用
    且 loaded 仍发出本地盘符。

    Args:
        qapp: session QApplication。
        monkeypatch: pytest monkeypatch fixture。
    """
    if sys.platform != "win32":
        pytest.skip("仅 Windows 支持 ctypes.windll 盘符枚举")

    debug_msgs: List[str] = []
    monkeypatch.setattr(_dl, "debug", lambda msg: debug_msgs.append(str(msg)))
    received: List[Tuple[List[str], List[str]]] = []
    with patch(
        "ctypes.windll.kernel32.GetLogicalDrives", return_value=0b101
    ), patch("ctypes.WinDLL", side_effect=OSError("mpr missing")):
        thread = DriveListLoaderThread()
        thread.loaded.connect(lambda drives, nets: received.append((drives, nets)))
        thread.run()

    assert debug_msgs and "网络位置失败" in debug_msgs[0]
    assert received[0][0] == ["A:", "C:"]
    assert received[0][1] == []


def test_drive_list_loader_run_outer_exception_logs_error(
    qapp: Any, monkeypatch: Any
) -> None:
    """error：run() 外层兜底 except → error 分支（排序阶段触发）。

    test_manual: monkeypatch builtins.sorted 抛 RuntimeError（run 的
    ``sorted(set(...))`` 在内外层 try 之间，属外层兜底范围），断言模块级
    ``error`` 被调用且含"异常"字样。

    Args:
        qapp: session QApplication。
        monkeypatch: pytest monkeypatch fixture。
    """
    if sys.platform != "win32":
        pytest.skip("仅 Windows 支持 ctypes.windll 盘符枚举")

    error_msgs: List[str] = []
    monkeypatch.setattr(_dl, "error", lambda msg: error_msgs.append(str(msg)))

    def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("模拟排序失败")

    monkeypatch.setattr("builtins.sorted", _boom)
    with patch(
        "ctypes.windll.kernel32.GetLogicalDrives", return_value=0b101
    ), patch("ctypes.WinDLL", side_effect=lambda _n: _FakeMpr()):
        thread = DriveListLoaderThread()
        # 不连接 collected —— run() 在 sorted 处抛错，绝不走到 emit。
        thread.run()

    assert error_msgs and "异常" in error_msgs[0]


# ---------------------------------------------------------------------------
# _DriveAvailabilityCheckRunnable —— 全部分支
# ---------------------------------------------------------------------------
def test_availability_runnable_true_for_existing_dir(tmp_path: Path) -> None:
    """happy：存在的目录经 _DriveAvailabilityCheckRunnable 判定可用。

    Args:
        tmp_path: 临时目录。
    """
    signals: _DriveAvailabilitySignals = _DriveAvailabilitySignals()
    results: List[Tuple[str, bool]] = []

    def _on_finished(drive_path: str, available: bool) -> None:
        results.append((drive_path, available))

    signals.finished.connect(_on_finished)
    runnable: _DriveAvailabilityCheckRunnable = _DriveAvailabilityCheckRunnable(
        str(tmp_path), signals
    )
    runnable.run()
    assert results == [(str(tmp_path), True)]


def test_availability_runnable_false_for_missing_path(tmp_path: Path) -> None:
    """error：不存在的路径经 _DriveAvailabilityCheckRunnable 判定不可用。

    Args:
        tmp_path: 临时目录。
    """
    missing: Path = tmp_path / "nope"
    signals: _DriveAvailabilitySignals = _DriveAvailabilitySignals()
    results: List[Tuple[str, bool]] = []

    def _on_finished(drive_path: str, available: bool) -> None:
        results.append((drive_path, available))

    signals.finished.connect(_on_finished)
    runnable: _DriveAvailabilityCheckRunnable = _DriveAvailabilityCheckRunnable(
        str(missing), signals
    )
    runnable.run()
    assert results == [(str(missing), False)]


def test_availability_runnable_appends_separator(tmp_path: Path) -> None:
    """boundary：缺少尾分隔符的路径被自动补齐后再检查。

    Args:
        tmp_path: 临时目录。
    """
    signals: _DriveAvailabilitySignals = _DriveAvailabilitySignals()
    results: List[Tuple[str, bool]] = []

    def _on_finished(drive_path: str, available: bool) -> None:
        results.append((drive_path, available))

    signals.finished.connect(_on_finished)
    # 不带尾分隔符的目录路径（Windows 风格反斜杠由 os.path.exists 兼容）
    no_trailing: str = str(tmp_path).rstrip("\\/")
    runnable: _DriveAvailabilityCheckRunnable = _DriveAvailabilityCheckRunnable(
        no_trailing, signals
    )
    runnable.run()
    assert results[0][0] == no_trailing
    assert results[0][1] is True


def test_availability_runnable_stop_iteration_on_empty_dir(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """boundary：scandir 抛 StopIteration（空/瞬时目录）→ 仍判定可用。

    test_manual: monkeypatch os.scandir 抛 StopIteration 触发 except 分支。

    Args:
        tmp_path: 临时目录。
        monkeypatch: pytest monkeypatch fixture。
    """
    signals: _DriveAvailabilitySignals = _DriveAvailabilitySignals()
    results: List[Tuple[str, bool]] = []

    def _on_finished(drive_path: str, available: bool) -> None:
        results.append((drive_path, available))

    signals.finished.connect(_on_finished)
    monkeypatch.setattr(os.path, "exists", lambda _p: True)

    def _empty_scan(_p: str) -> Any:
        """os.scandir 直接抛 StopIteration（模拟空/瞬时目录）。"""
        raise StopIteration()

    monkeypatch.setattr(os, "scandir", _empty_scan)
    runnable: _DriveAvailabilityCheckRunnable = _DriveAvailabilityCheckRunnable(
        str(tmp_path), signals
    )
    runnable.run()
    assert results == [(str(tmp_path), True)]


def test_availability_runnable_false_on_permission_error(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """error：scandir 抛 PermissionError → 判定不可用。

    test_manual: monkeypatch os.scandir 抛 PermissionError，断言 False。

    Args:
        tmp_path: 临时目录。
        monkeypatch: pytest monkeypatch fixture。
    """
    signals: _DriveAvailabilitySignals = _DriveAvailabilitySignals()
    results: List[Tuple[str, bool]] = []

    def _on_finished(drive_path: str, available: bool) -> None:
        results.append((drive_path, available))

    signals.finished.connect(_on_finished)
    monkeypatch.setattr(os.path, "exists", lambda _p: True)

    def _deny(_p: str) -> Any:
        raise PermissionError("拒绝访问")

    monkeypatch.setattr(os, "scandir", _deny)
    runnable: _DriveAvailabilityCheckRunnable = _DriveAvailabilityCheckRunnable(
        str(tmp_path), signals
    )
    runnable.run()
    assert results == [(str(tmp_path), False)]


def test_availability_runnable_false_on_generic_exception(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """error：scandir 抛兜底 Exception → 判定不可用。

    test_manual: monkeypatch os.scandir 抛 RuntimeError，断言 False。

    Args:
        tmp_path: 临时目录。
        monkeypatch: pytest monkeypatch fixture。
    """
    signals: _DriveAvailabilitySignals = _DriveAvailabilitySignals()
    results: List[Tuple[str, bool]] = []

    def _on_finished(drive_path: str, available: bool) -> None:
        results.append((drive_path, available))

    signals.finished.connect(_on_finished)
    monkeypatch.setattr(os.path, "exists", lambda _p: True)

    def _boom(_p: str) -> Any:
        raise RuntimeError("意外错误")

    monkeypatch.setattr(os, "scandir", _boom)
    runnable: _DriveAvailabilityCheckRunnable = _DriveAvailabilityCheckRunnable(
        str(tmp_path), signals
    )
    runnable.run()
    assert results == [(str(tmp_path), False)]