#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DriveListLoaderThread 单元测试

测试驱动器列表加载线程的创建、启动、信号发射和盘符可用性检查。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QThread
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from freeassetfilter.core.workers.drive_list_loader import (
    _DriveAvailabilityCheckRunnable,
    _DriveAvailabilitySignals,
    DriveListLoaderThread,
)


# ==============================================================================
# 辅助工具
# ==============================================================================


def _spy_signal_args(signal):
    """连接一个 slot 到 signal，返回一个列表用于收集发射参数。

    PySide6 的 QSignalSpy 在某些版本不支持索引访问，
    因此使用此辅助函数替代 spy[0] 来获取参数。
    """
    args_list = []

    def _collect(*args):
        args_list.append(args)

    signal.connect(_collect)
    return args_list


# ==============================================================================
# DriveListLoaderThread — 创建 & 基本属性
# ==============================================================================


class TestDriveListLoaderThreadCreation:
    """测试 DriveListLoaderThread 的创建和基本属性。"""

    def test_creation(self, qapp) -> None:
        """Given 无参数
        When 创建 DriveListLoaderThread 实例
        Then 实例创建成功且 loaded 信号存在。
        """
        thread = DriveListLoaderThread()
        assert thread is not None
        assert hasattr(thread, "loaded")
        thread.quit()
        thread.wait(1000)

    def test_is_qthread_subclass(self, qapp) -> None:
        """Given DriveListLoaderThread 类
        Then 它是 QThread 的子类。
        """
        assert issubclass(DriveListLoaderThread, QThread)


# ==============================================================================
# DriveListLoaderThread — run() 信号发射
# ==============================================================================


class TestDriveListLoaderThreadRun:
    """测试 DriveListLoaderThread.run() 的信号发射逻辑。

    通过 mock Windows API 来控制 GetLogicalDrives 和 WNetOpenEnumW 的返回值，
    验证 loaded 信号在不同场景下按预期发射。
    """

    # -- 工具方法 -----------------------------------------------------------

    @staticmethod
    def _run_thread_and_collect(
        thread: DriveListLoaderThread,
    ) -> tuple[list[str], list[str]]:
        """启动线程，等待完成，处理事件队列，返回 loaded 信号参数。

        Returns:
            (local_drives, network_locations)
        """
        spy = QSignalSpy(thread.loaded)
        args = _spy_signal_args(thread.loaded)
        thread.start()
        assert thread.wait(5000), "Thread did not finish within 5s"
        # 跨线程信号是 QueuedConnection，需要处理事件队列
        QApplication.processEvents()
        assert spy.count() >= 1, "loaded 信号应至少发射一次"
        local_drives, network_locations = args[0]
        return local_drives, network_locations

    # -- Windows 正常路径 ---------------------------------------------------

    @patch("freeassetfilter.core.workers.drive_list_loader.sys.platform", "win32")
    @patch(
        "freeassetfilter.core.workers.drive_list_loader."
        "ctypes.windll.kernel32.GetLogicalDrives"
    )
    @patch("freeassetfilter.core.workers.drive_list_loader.ctypes.WinDLL")
    def test_emits_loaded_with_specific_drives(
        self, mock_windll: MagicMock, mock_get_drives: MagicMock, qapp
    ) -> None:
        """Given GetLogicalDrives 返回 C+E 盘（位掩码 0x0014）
        When run() 执行完毕
        Then loaded 信号发射，携带 ["C:", "E:"] 和 []。
        """
        mock_get_drives.return_value = 0x0014  # bits 2 (C) and 4 (E)
        mock_mpr = MagicMock()
        mock_mpr.WNetOpenEnumW.return_value = 1  # 非 0 = 枚举失败
        mock_windll.return_value = mock_mpr

        thread = DriveListLoaderThread()
        local_drives, network_locations = self._run_thread_and_collect(thread)

        assert local_drives == ["C:", "E:"]
        assert network_locations == []

    @patch("freeassetfilter.core.workers.drive_list_loader.sys.platform", "win32")
    @patch(
        "freeassetfilter.core.workers.drive_list_loader."
        "ctypes.windll.kernel32.GetLogicalDrives"
    )
    @patch("freeassetfilter.core.workers.drive_list_loader.ctypes.WinDLL")
    def test_emits_loaded_with_all_drives(
        self, mock_windll: MagicMock, mock_get_drives: MagicMock, qapp
    ) -> None:
        """Given 所有 26 个盘符都存在（位掩码 0x03FFFFFF）
        When run() 执行完毕
        Then loaded 信号包含全部 A:-Z: 盘符。
        """
        mock_get_drives.return_value = 0x03FFFFFF  # 全部 26 位
        mock_mpr = MagicMock()
        mock_mpr.WNetOpenEnumW.return_value = 1
        mock_windll.return_value = mock_mpr

        thread = DriveListLoaderThread()
        local_drives, _ = self._run_thread_and_collect(thread)

        assert len(local_drives) == 26
        assert local_drives == [chr(65 + i) + ":" for i in range(26)]

    # -- Windows 异常路径 ---------------------------------------------------

    @patch("freeassetfilter.core.workers.drive_list_loader.sys.platform", "win32")
    @patch(
        "freeassetfilter.core.workers.drive_list_loader."
        "ctypes.windll.kernel32.GetLogicalDrives"
    )
    @patch("freeassetfilter.core.workers.drive_list_loader.ctypes.WinDLL")
    def test_get_logical_drives_failure_emits_empty(
        self, mock_windll: MagicMock, mock_get_drives: MagicMock, qapp
    ) -> None:
        """Given GetLogicalDrives() 抛出异常
        When run() 执行完毕
        Then loaded 信号携带空 local_drives（静默失败）。
        """
        mock_get_drives.side_effect = OSError("API fail")
        mock_mpr = MagicMock()
        mock_mpr.WNetOpenEnumW.return_value = 1
        mock_windll.return_value = mock_mpr

        thread = DriveListLoaderThread()
        local_drives, _ = self._run_thread_and_collect(thread)

        assert local_drives == []

    @patch("freeassetfilter.core.workers.drive_list_loader.sys.platform", "win32")
    @patch(
        "freeassetfilter.core.workers.drive_list_loader."
        "ctypes.windll.kernel32.GetLogicalDrives"
    )
    def test_mpr_load_failure_still_emits_local_drives(
        self, mock_get_drives: MagicMock, qapp
    ) -> None:
        """Given mpr.dll 加载失败
        When run() 执行完毕
        Then loaded 信号仍携带本地盘符，network_locations 为空。
        """
        mock_get_drives.return_value = 0x0054  # bits 2,4,6 → C:, E:, G:

        with patch(
            "freeassetfilter.core.workers.drive_list_loader.ctypes.WinDLL",
            side_effect=OSError("找不到 mpr.dll"),
        ):
            thread = DriveListLoaderThread()
            local_drives, network_locations = self._run_thread_and_collect(thread)

        assert local_drives == ["C:", "E:", "G:"]
        assert network_locations == []

    # -- 非 Windows 路径 ----------------------------------------------------

    @patch("freeassetfilter.core.workers.drive_list_loader.sys", spec=object)
    def test_non_windows_emits_root(
        self, mock_sys: Any, qapp
    ) -> None:
        """Given 非 Windows 平台（sys.platform == "linux"）
        When run() 执行完毕
        Then loaded 携带 ["/"] 和 []。
        """
        mock_sys.platform = "linux"

        thread = DriveListLoaderThread()
        local_drives, network_locations = self._run_thread_and_collect(thread)

        assert local_drives == ["/"]
        assert network_locations == []

    # -- 信号发射次数验证 ---------------------------------------------------

    @patch("freeassetfilter.core.workers.drive_list_loader.sys.platform", "win32")
    @patch(
        "freeassetfilter.core.workers.drive_list_loader."
        "ctypes.windll.kernel32.GetLogicalDrives"
    )
    @patch("freeassetfilter.core.workers.drive_list_loader.ctypes.WinDLL")
    def test_loaded_emitted_exactly_once(
        self, mock_windll: MagicMock, mock_get_drives: MagicMock, qapp
    ) -> None:
        """Given 正常 Windows 环境
        When run() 执行完毕
        Then loaded 信号恰好发射一次。
        """
        mock_get_drives.return_value = 0x0004
        mock_mpr = MagicMock()
        mock_mpr.WNetOpenEnumW.return_value = 1
        mock_windll.return_value = mock_mpr

        thread = DriveListLoaderThread()
        spy = QSignalSpy(thread.loaded)
        thread.start()
        assert thread.wait(5000)
        QApplication.processEvents()

        assert spy.count() == 1

    @patch("freeassetfilter.core.workers.drive_list_loader.sys.platform", "win32")
    @patch(
        "freeassetfilter.core.workers.drive_list_loader."
        "ctypes.windll.kernel32.GetLogicalDrives"
    )
    @patch("freeassetfilter.core.workers.drive_list_loader.ctypes.WinDLL")
    def test_at_least_one_drive_is_listed(
        self, mock_windll: MagicMock, mock_get_drives: MagicMock, qapp
    ) -> None:
        """Given Windows 环境有至少一个盘符（C:）
        When run() 执行完毕
        Then local_drives 至少包含一个盘符。
        """
        mock_get_drives.return_value = 0x0004  # C:
        mock_mpr = MagicMock()
        mock_mpr.WNetOpenEnumW.return_value = 1
        mock_windll.return_value = mock_mpr

        thread = DriveListLoaderThread()
        local_drives, _ = self._run_thread_and_collect(thread)

        assert len(local_drives) >= 1

    # -- 全零位掩码 ---------------------------------------------------------

    @patch("freeassetfilter.core.workers.drive_list_loader.sys.platform", "win32")
    @patch(
        "freeassetfilter.core.workers.drive_list_loader."
        "ctypes.windll.kernel32.GetLogicalDrives"
    )
    @patch("freeassetfilter.core.workers.drive_list_loader.ctypes.WinDLL")
    def test_no_drives_at_all(
        self, mock_windll: MagicMock, mock_get_drives: MagicMock, qapp
    ) -> None:
        """Given 没有任何盘符或网络位置
        When run() 执行完毕
        Then loaded 信号携带空列表和空列表。
        """
        mock_get_drives.return_value = 0x00000000  # 没有盘符
        mock_mpr = MagicMock()
        mock_mpr.WNetOpenEnumW.return_value = 1
        mock_windll.return_value = mock_mpr

        thread = DriveListLoaderThread()
        spy = QSignalSpy(thread.loaded)
        args = _spy_signal_args(thread.loaded)
        thread.start()
        assert thread.wait(5000)
        QApplication.processEvents()

        assert spy.count() == 1
        local_drives, network_locations = args[0]
        assert local_drives == []
        assert network_locations == []


# ==============================================================================
# _DriveAvailabilityCheckRunnable
# ==============================================================================


class TestDriveAvailabilityCheckRunnableCreation:
    """测试 _DriveAvailabilityCheckRunnable 的创建。"""

    def test_creation(self, qapp) -> None:
        """Given 盘符路径和 signals 对象
        When 创建 _DriveAvailabilityCheckRunnable 实例
        Then 实例创建成功，属性正确。
        """
        signals = _DriveAvailabilitySignals()
        runnable = _DriveAvailabilityCheckRunnable("C:", signals)
        assert runnable is not None
        assert runnable._drive_path == "C:"
        assert runnable._signals is signals

    def test_signals_object_has_finished(self, qapp) -> None:
        """Given _DriveAvailabilitySignals 实例
        Then finished 信号存在。
        """
        signals = _DriveAvailabilitySignals()
        assert hasattr(signals, "finished")


class TestDriveAvailabilityCheckRunnableRun:
    """测试 _DriveAvailabilityCheckRunnable.run() 的盘符可用性检查逻辑。"""

    @staticmethod
    def _run_runnable_and_collect(
        runnable: _DriveAvailabilityCheckRunnable,
        signals: _DriveAvailabilitySignals,
    ) -> tuple[str, bool]:
        """执行 runnable.run() 并收集 finished 信号参数。

        Returns:
            (drive_path, available)
        """
        spy = QSignalSpy(signals.finished)
        args = _spy_signal_args(signals.finished)
        runnable.run()
        # 同线程信号是 DirectConnection，无需 processEvents
        assert spy.count() == 1
        return args[0]

    @patch("os.path.exists")
    @patch("os.scandir")
    def test_drive_available_with_files(
        self, mock_scandir: MagicMock, mock_exists: MagicMock, qapp
    ) -> None:
        """Given 盘符存在且有文件条目
        When run() 执行
        Then finished 信号携带 (drive_path, True)。
        """
        mock_exists.return_value = True
        mock_scandir.return_value.__enter__.return_value = iter([MagicMock()])

        signals = _DriveAvailabilitySignals()
        runnable = _DriveAvailabilityCheckRunnable("D:", signals)
        drive_path, available = self._run_runnable_and_collect(runnable, signals)

        assert drive_path == "D:"
        assert available is True
        mock_exists.assert_called_with("D:\\")
        mock_scandir.assert_called_with("D:\\")

    @patch("os.path.exists")
    @patch("os.scandir")
    def test_drive_available_empty_directory(
        self, mock_scandir: MagicMock, mock_exists: MagicMock, qapp
    ) -> None:
        """Given 盘符存在但为空目录（next(it, None) 返回 None）
        When run() 执行
        Then finished 信号携带 (drive_path, True)。
        """
        mock_exists.return_value = True
        mock_scandir.return_value.__enter__.return_value = iter([])

        signals = _DriveAvailabilitySignals()
        runnable = _DriveAvailabilityCheckRunnable("D:", signals)
        _, available = self._run_runnable_and_collect(runnable, signals)

        assert available is True

    @patch("os.path.exists")
    def test_drive_not_exists(
        self, mock_exists: MagicMock, qapp
    ) -> None:
        """Given 盘符路径不存在
        When run() 执行
        Then finished 信号携带 (drive_path, False)。
        """
        mock_exists.return_value = False

        signals = _DriveAvailabilitySignals()
        runnable = _DriveAvailabilityCheckRunnable("X:", signals)
        drive_path, available = self._run_runnable_and_collect(runnable, signals)

        assert drive_path == "X:"
        assert available is False

    @patch("os.path.exists")
    @patch("os.scandir")
    def test_drive_unavailable_os_error(
        self, mock_scandir: MagicMock, mock_exists: MagicMock, qapp
    ) -> None:
        """Given os.scandir 抛出 OSError（如设备未就绪）
        When run() 执行
        Then finished 信号携带 (drive_path, False)。
        """
        mock_exists.return_value = True
        mock_scandir.return_value.__enter__.side_effect = OSError("设备未就绪")

        signals = _DriveAvailabilitySignals()
        runnable = _DriveAvailabilityCheckRunnable("A:", signals)
        _, available = self._run_runnable_and_collect(runnable, signals)

        assert available is False

    @patch("os.path.exists")
    @patch("os.scandir")
    def test_drive_unavailable_permission_error(
        self, mock_scandir: MagicMock, mock_exists: MagicMock, qapp
    ) -> None:
        """Given os.scandir 抛出 PermissionError（如访问被拒绝）
        When run() 执行
        Then finished 信号携带 (drive_path, False)。
        """
        mock_exists.return_value = True
        mock_scandir.return_value.__enter__.side_effect = PermissionError("访问被拒绝")

        signals = _DriveAvailabilitySignals()
        runnable = _DriveAvailabilityCheckRunnable("R:", signals)
        _, available = self._run_runnable_and_collect(runnable, signals)

        assert available is False

    @patch("os.path.exists")
    @patch("os.scandir")
    def test_drive_with_trailing_slash(
        self, mock_scandir: MagicMock, mock_exists: MagicMock, qapp
    ) -> None:
        """Given 盘符路径以反斜杠结尾
        When run() 执行
        Then 路径不额外追加反斜杠，检查仍然成功。
        """
        mock_exists.return_value = True
        mock_scandir.return_value.__enter__.return_value = iter([MagicMock()])

        signals = _DriveAvailabilitySignals()
        runnable = _DriveAvailabilityCheckRunnable("E:\\", signals)
        drive_path, available = self._run_runnable_and_collect(runnable, signals)

        assert drive_path == "E:\\"
        assert available is True
        mock_exists.assert_called_with("E:\\")
        mock_scandir.assert_called_with("E:\\")

    @patch("os.path.exists")
    @patch("os.scandir")
    def test_drive_with_forward_slash(
        self, mock_scandir: MagicMock, mock_exists: MagicMock, qapp
    ) -> None:
        """Given 盘符路径以正斜杠结尾
        When run() 执行
        Then 路径不被追加斜杠。
        """
        mock_exists.return_value = True
        mock_scandir.return_value.__enter__.return_value = iter([MagicMock()])

        signals = _DriveAvailabilitySignals()
        runnable = _DriveAvailabilityCheckRunnable("F:/", signals)
        _, available = self._run_runnable_and_collect(runnable, signals)

        assert available is True
        mock_exists.assert_called_with("F:/")
        mock_scandir.assert_called_with("F:/")

    @patch("os.path.exists")
    @patch("os.scandir")
    def test_drive_with_neither_slash(
        self, mock_scandir: MagicMock, mock_exists: MagicMock, qapp
    ) -> None:
        """Given 盘符路径结尾没有斜杠
        When run() 执行
        Then 路径自动追加反斜杠。
        """
        mock_exists.return_value = True
        mock_scandir.return_value.__enter__.return_value = iter([MagicMock()])

        signals = _DriveAvailabilitySignals()
        runnable = _DriveAvailabilityCheckRunnable("G:", signals)
        _, available = self._run_runnable_and_collect(runnable, signals)

        assert available is True
        mock_exists.assert_called_with("G:\\")
        mock_scandir.assert_called_with("G:\\")
