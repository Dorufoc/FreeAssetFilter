# -*- coding: utf-8 -*-
"""``DriveService``（freeassetfilter/services/drive_service.py）单元测试。

覆盖（happy + boundary/error 各至少一条）：

* 生命周期 —— 初始化幂等、单例同一实例
* ``list_drives`` —— 本地盘符 + 网络位置合并去重排序（全部 mock，不真实
  枚举整机磁盘）、Windows API 失败静默空列表、非 Windows 返回 ``["/"]``
* ``check_availability`` —— 有内容/空目录可用、不存在不可用、无尾随分隔符
  自动补齐、scandir 权限错误不可用、exists 通用异常不可用

Windows 原生枚举（``ctypes.windll`` / ``mpr``）一律通过 monkeypatch 替换，
保证测试不触碰真实硬件/网络枚举。
"""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

import pytest

from freeassetfilter.services.drive_service import DriveService

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_drive_service_singleton() -> None:
    """在测试前后归零 DriveService 单例，保证每测试全新实例。

    Returns:
        None。
    """
    DriveService._instance = None
    DriveService._initialized = False
    yield
    DriveService._instance = None
    DriveService._initialized = False


# =============================================================================
# 生命周期
# =============================================================================
class TestLifecycle:
    """生命周期与单例"""

    def test_singleton_returns_same_instance(self) -> None:
        """重复构造必须返回同一实例。"""
        assert DriveService() is DriveService()

    def test_initialize_idempotent(self) -> None:
        """initialize 幂等且置位 is_initialized。"""
        svc: DriveService = DriveService()
        assert svc.is_initialized is False
        assert svc.initialize() is True
        assert svc.initialize() is True
        assert svc.is_initialized is True

    def test_dispose_resets_initialized(self) -> None:
        """dispose 后 is_initialized 回到 False。"""
        svc: DriveService = DriveService()
        svc.initialize()
        svc.dispose()
        assert svc.is_initialized is False


# =============================================================================
# list_drives
# =============================================================================
class TestListDrives:
    """盘符枚举"""

    def test_windows_merges_local_and_network_sorted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """本地盘符与网络位置合并去重并排序。"""
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(
            DriveService,
            "_list_windows_drives",
            staticmethod(lambda: ["D:", "C:", "C:"]),
        )
        monkeypatch.setattr(
            DriveService,
            "_list_windows_network_locations",
            staticmethod(lambda: ["\\\\server\\share"]),
        )
        assert DriveService().list_drives() == ["C:", "D:", "\\\\server\\share"]

    def test_windows_network_overlap_deduped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """网络位置与本地盘符重名时去重。"""
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(
            DriveService,
            "_list_windows_drives",
            staticmethod(lambda: ["C:", "E:"]),
        )
        monkeypatch.setattr(
            DriveService,
            "_list_windows_network_locations",
            staticmethod(lambda: ["C:"]),
        )
        assert DriveService().list_drives() == ["C:", "E:"]

    def test_windows_without_network_locations(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """无网络位置时仅返回排序后的本地盘符。"""
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(
            DriveService,
            "_list_windows_drives",
            staticmethod(lambda: ["B:", "A:"]),
        )
        monkeypatch.setattr(
            DriveService,
            "_list_windows_network_locations",
            staticmethod(lambda: []),
        )
        assert DriveService().list_drives() == ["A:", "B:"]

    def test_non_windows_returns_root(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """非 Windows 平台只返回根目录。"""
        monkeypatch.setattr(sys, "platform", "linux")
        assert DriveService().list_drives() == ["/"]

    def test_windows_drive_enumeration_failure_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GetLogicalDrives 不可用时静默返回空列表。"""

        class _FakeKernel32:
            """仅暴露一个必然抛错的 GetLogicalDrives 属性。"""

            @property
            def GetLogicalDrives(self) -> object:
                """模拟 Win32 API 不可用（访问即抛）。"""
                raise OSError("api unavailable")

        monkeypatch.setattr(ctypes, "windll", _FakeKernel32())
        assert DriveService._list_windows_drives() == []

    def test_network_locations_empty_on_mpr_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """mpr DLL 加载失败时网络枚举静默返回空列表。"""
        def _raise_windll(name: str) -> object:
            raise OSError("mpr unavailable")

        monkeypatch.setattr(ctypes, "WinDLL", _raise_windll)
        assert DriveService._list_windows_network_locations() == []


# =============================================================================
# check_availability
# =============================================================================
class TestCheckAvailability:
    """盘符可用性"""

    def test_existing_directory_available(self, tmp_path: Path) -> None:
        """存在的目录可访问。"""
        assert DriveService().check_availability(str(tmp_path)) is True

    def test_empty_directory_available(self, tmp_path: Path) -> None:
        """空目录视为可用。"""
        empty: Path = tmp_path / "empty"
        empty.mkdir()
        assert DriveService().check_availability(str(empty)) is True

    def test_without_trailing_separator_available(self, tmp_path: Path) -> None:
        """不带尾随分隔符的目录路径同样可用（内部自动补齐）。"""
        assert DriveService().check_availability(str(tmp_path)) is True

    def test_nonexistent_path_unavailable(self, tmp_path: Path) -> None:
        """不存在的路径不可用。"""
        assert (
            DriveService().check_availability(str(tmp_path / "missing")) is False
        )

    def test_scandir_permission_error_unavailable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """扫描权限不足时判定不可用。"""
        def _raise_scandir(path: str) -> object:
            raise PermissionError("denied")

        monkeypatch.setattr(os, "scandir", _raise_scandir)
        assert DriveService().check_availability(str(tmp_path)) is False

    def test_exists_generic_exception_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """边界：exists 抛出非 OSError 异常时判定不可用。"""
        def _raise_exists(path: str) -> bool:
            raise RuntimeError("boom")

        monkeypatch.setattr(os.path, "exists", _raise_exists)
        assert DriveService().check_availability("C:\\") is False