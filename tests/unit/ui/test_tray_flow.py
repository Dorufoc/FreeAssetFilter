# -*- coding: utf-8 -*-
"""主窗口托盘挂起 / 恢复 / 退出流程。

背景：主窗口关闭支持「询问 / 最小化到系统托盘 / 直接退出」三种行为。
托盘挂起需要先记录并卸载预览内容与后台渲染资源，唤回时再按快照恢复。

本文件锁定以下契约（不构造完整 MainWindow，直接绑定真实方法到轻量替身）：

* ``_suspend_for_tray``：记录预览文件、清空预览、停止信息面板、释放内存
  缓存与后台渲染各一次；重复调用不重复执行；
* ``_resume_from_tray``：按快照重新加载预览与信息面板，清空记录并解除挂起；
  未挂起时不做任何加载；
* ``set_close_action``：合法值生效，非法值回退 "ask"；
* ``_enter_tray_mode``：托盘不可用时返回 False，不隐藏窗口。

验证：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/unit/ui/test_tray_flow.py -q
"""

from __future__ import annotations

from typing import Any, Optional

import pytest

from sopeek.ui.main_window import MainWindow

pytestmark = pytest.mark.unit


# ── 挂起 / 恢复 ────────────────────────────────────────────────────────


class _FakePreviewer:
    """预览器替身：记录当前文件与 clear_preview / set_file 调用。"""

    def __init__(self, info: Optional[dict] = None) -> None:
        self.current_file_info = info
        self.clear_calls = 0
        self.loaded: list = []

    def clear_preview(self) -> None:
        self.clear_calls += 1

    def set_file(self, info: Optional[dict]) -> None:
        self.current_file_info = info
        self.loaded.append(info)


class _FakeInfoPanel:
    """信息面板替身：记录 stop / set_file 调用。"""

    def __init__(self) -> None:
        self.stop_calls = 0
        self.loaded: list = []

    def stop(self) -> None:
        self.stop_calls += 1

    def set_file(self, info: Optional[dict]) -> None:
        self.loaded.append(info)


class _FakeMemoryBudget:
    """内存预算替身：记录 release_caches 调用次数。"""

    def __init__(self) -> None:
        self.release_calls = 0

    def release_caches(self) -> None:
        self.release_calls += 1


class _SuspendHost:
    """``MainWindow._suspend_for_tray`` 的最小宿主替身。"""

    _suspend_for_tray = MainWindow._suspend_for_tray
    _read_current_file_info = staticmethod(MainWindow._read_current_file_info)

    def __init__(self, previewer: Any, info_panel: Any) -> None:
        self._previewer = previewer
        self._info_panel = info_panel
        self._tray_suspended = False
        self._tray_preview_file = None
        self._tray_info_file = None
        self.suspend_renderer_calls = 0

    def _suspend_background_renderers(self) -> None:
        self.suspend_renderer_calls += 1


def test_suspend_for_tray_records_and_releases_once(qapp, monkeypatch) -> None:
    """挂起一次：记录文件、清空预览、停止面板、释放缓存与渲染各一次。"""
    import sopeek.core.memory_budget as memory_budget_module

    budget = _FakeMemoryBudget()
    monkeypatch.setattr(
        memory_budget_module, "get_memory_budget", lambda: budget
    )
    info = {"path": "D:/demo/a.png", "name": "a.png"}
    previewer = _FakePreviewer(info)
    panel = _FakeInfoPanel()
    host = _SuspendHost(previewer, panel)

    MainWindow._suspend_for_tray(host)
    # 重复调用不重复执行
    MainWindow._suspend_for_tray(host)

    assert host._tray_preview_file == info
    assert host._tray_preview_file is not info
    assert host._tray_info_file == info
    assert previewer.clear_calls == 1
    assert panel.stop_calls == 1
    assert budget.release_calls == 1
    assert host.suspend_renderer_calls == 1
    assert host._tray_suspended is True


def test_suspend_accepts_callable_current_file_info(qapp, monkeypatch) -> None:
    """真实预览器以 ``current_file_info()`` 方法暴露当前文件，挂起时须能读取。"""
    import sopeek.core.memory_budget as memory_budget_module

    budget = _FakeMemoryBudget()
    monkeypatch.setattr(
        memory_budget_module, "get_memory_budget", lambda: budget
    )
    info = {"path": "D:/demo/video.mp4", "name": "video.mp4"}

    class _CallablePreviewer:
        """当前文件通过方法返回（与 UnifiedPreviewerLayout 一致）。"""

        def __init__(self) -> None:
            self.clear_calls = 0

        def current_file_info(self) -> dict:
            return dict(info)

        def clear_preview(self) -> None:
            self.clear_calls += 1

    previewer = _CallablePreviewer()
    host = _SuspendHost(previewer, _FakeInfoPanel())

    MainWindow._suspend_for_tray(host)

    assert host._tray_preview_file == info
    assert previewer.clear_calls == 1


def test_suspend_without_preview_records_none(qapp, monkeypatch) -> None:
    """无预览内容时快照记为 None，且仍完成缓存/渲染挂起。"""
    import sopeek.core.memory_budget as memory_budget_module

    budget = _FakeMemoryBudget()
    monkeypatch.setattr(
        memory_budget_module, "get_memory_budget", lambda: budget
    )
    previewer = _FakePreviewer(None)
    panel = _FakeInfoPanel()
    host = _SuspendHost(previewer, panel)

    MainWindow._suspend_for_tray(host)

    assert host._tray_preview_file is None
    assert host._tray_info_file is None
    assert previewer.clear_calls == 1
    assert panel.stop_calls == 1
    assert host._tray_suspended is True


class _ResumeHost:
    """``MainWindow._resume_from_tray`` 的最小宿主替身。"""

    _resume_from_tray = MainWindow._resume_from_tray

    def __init__(
        self,
        previewer: Any,
        info_panel: Any,
        *,
        suspended: bool = True,
        preview_file: Optional[dict] = None,
        info_file: Optional[dict] = None,
    ) -> None:
        self._previewer = previewer
        self._info_panel = info_panel
        self._tray_suspended = suspended
        self._tray_preview_file = preview_file
        self._tray_info_file = info_file
        self.resume_renderer_calls = 0

    def _resume_background_renderers(self) -> None:
        self.resume_renderer_calls += 1


def test_resume_from_tray_reloads_recorded_files(qapp) -> None:
    """恢复：按快照重新加载预览与信息面板，清空记录并解除挂起。"""
    preview_info = {"path": "D:/demo/a.png"}
    info_file = {"path": "D:/demo/b.png"}
    previewer = _FakePreviewer(None)
    panel = _FakeInfoPanel()
    host = _ResumeHost(
        previewer,
        panel,
        suspended=True,
        preview_file=preview_info,
        info_file=info_file,
    )

    MainWindow._resume_from_tray(host)

    assert previewer.loaded == [preview_info]
    assert panel.loaded == [info_file]
    assert host._tray_preview_file is None
    assert host._tray_info_file is None
    assert host._tray_suspended is False
    assert host.resume_renderer_calls == 1


def test_resume_without_suspension_does_not_reload(qapp) -> None:
    """未挂起时恢复为空操作，避免重复加载。"""
    previewer = _FakePreviewer(None)
    panel = _FakeInfoPanel()
    host = _ResumeHost(
        previewer,
        panel,
        suspended=False,
        preview_file={"path": "D:/demo/a.png"},
        info_file={"path": "D:/demo/b.png"},
    )

    MainWindow._resume_from_tray(host)

    assert previewer.loaded == []
    assert panel.loaded == []
    assert host.resume_renderer_calls == 0
    assert host._tray_suspended is False


# ── 关闭行为设置 ───────────────────────────────────────────────────────


class _CloseActionHost:
    """``MainWindow.set_close_action`` 的最小宿主替身。"""

    set_close_action = MainWindow.set_close_action

    def __init__(self) -> None:
        self._close_action = "ask"


def test_set_close_action_accepts_valid_values(qapp) -> None:
    """合法行为值立即生效。"""
    host = _CloseActionHost()

    MainWindow.set_close_action(host, "tray")
    assert host._close_action == "tray"

    MainWindow.set_close_action(host, "quit")
    assert host._close_action == "quit"

    MainWindow.set_close_action(host, "ask")
    assert host._close_action == "ask"


def test_set_close_action_falls_back_to_ask(qapp) -> None:
    """非法行为值回退 "ask"。"""
    host = _CloseActionHost()
    host._close_action = "quit"

    MainWindow.set_close_action(host, "minimize")

    assert host._close_action == "ask"


# ── 托盘不可用兜底 ─────────────────────────────────────────────────────


class _TrayFallbackHost:
    """``MainWindow._enter_tray_mode`` 的最小宿主替身。"""

    _enter_tray_mode = MainWindow._enter_tray_mode

    def __init__(self) -> None:
        self.hide_calls = 0

    def _ensure_tray_controller(self) -> None:
        return None

    def _close_settings_window_now(self) -> None:
        raise AssertionError("托盘不可用时不得关闭设置窗口")

    def _suspend_for_tray(self) -> None:
        raise AssertionError("托盘不可用时不得挂起预览")

    def hide(self) -> None:
        self.hide_calls += 1


def test_enter_tray_mode_returns_false_when_unavailable(qapp) -> None:
    """托盘不可用：返回 False 且不隐藏窗口、不执行挂起。"""
    host = _TrayFallbackHost()

    assert MainWindow._enter_tray_mode(host) is False
    assert host.hide_calls == 0
