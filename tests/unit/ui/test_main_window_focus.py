# -*- coding: utf-8 -*-
"""主窗口激活焦点兜底回归。

背景：主窗口内容就绪后可能没有任何焦点控件。此时关闭设置窗、对话框等
独立顶层弹窗，Qt 会按 Tab 顺序把焦点自动交给第一个可聚焦控件——文件
选择器顶部的路径框。``MainWindow`` 在 ``ActivationChange`` 时把这类
「无焦点激活」兜底到文件列表，避免路径框被动获焦。

本文件锁定以下契约：

* 主窗口重新激活且无焦点 → 调用文件选择器的 ``focus_file_list``；
* 已有焦点控件 → 不抢焦点；
* 主窗口关闭中 → 不再聚焦；
* 文件选择器尚未就绪 → 静默跳过；
* 路径框有焦点时点击其外部（NoFocus 按钮/空白区）→ 主动释放路径框焦点；
* 点击路径框本身或其内嵌按钮 → 保持焦点；
* 鼠标点击切换焦点区 → 描边一次；同一焦点区内连续点击 → 不重复描边；
* 键盘切换焦点区 → 仍描边；
* 取消预览后焦点不在任何面板 → 兜底到文件列表；已在池/选择器内则不抢。

验证：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/unit/ui/test_main_window_focus.py -v
"""

from __future__ import annotations

from typing import Any, Optional

import pytest
from PySide6.QtWidgets import QWidget

from sopeek.ui.layout.file_selector_layout import FileSelectorLayout
from sopeek.ui.main_window import MainWindow

pytestmark = pytest.mark.unit


class _FakePathInput:
    """路径框替身：只覆盖焦点释放判定用到的最小接口。"""

    def __init__(self, *, focused: bool = True) -> None:
        self._focused = focused
        self.clear_calls = 0
        self._inside_targets: list = []

    def hasFocus(self) -> bool:
        return self._focused

    def clearFocus(self) -> None:
        self.clear_calls += 1
        self._focused = False

    def isAncestorOf(self, target: object) -> bool:
        return target in self._inside_targets


class _PathFocusHost:
    """``FileSelectorLayout.release_path_focus_on_outside_click`` 的最小宿主替身。"""

    def __init__(self, path_input: _FakePathInput) -> None:
        self._path_input = path_input


class _FakeSelector:
    """记录 ``focus_file_list`` 调用的文件选择器替身。"""

    def __init__(self) -> None:
        self.focus_calls = 0

    def focus_file_list(self) -> None:
        self.focus_calls += 1


class _FocusHost:
    """``MainWindow._restore_default_focus_if_needed`` 的最小宿主替身。"""

    def __init__(
        self,
        *,
        focus: Optional[Any] = None,
        selector: Optional[_FakeSelector] = None,
        close_in_progress: bool = False,
    ) -> None:
        self._focus_widget = focus
        self._file_selector = selector
        self._close_in_progress = close_in_progress

    def focusWidget(self) -> Optional[Any]:
        return self._focus_widget


def test_activation_without_focus_falls_back_to_file_list(qapp) -> None:
    """无焦点激活：默认落点必须是文件列表（而非路径框）。"""
    selector = _FakeSelector()
    host = _FocusHost(focus=None, selector=selector)

    MainWindow._restore_default_focus_if_needed(host)

    assert selector.focus_calls == 1


def test_activation_keeps_existing_focus(qapp) -> None:
    """已有焦点控件时不抢焦点（例如用户正在编辑路径框/搜索框）。"""
    selector = _FakeSelector()
    host = _FocusHost(focus=object(), selector=selector)

    MainWindow._restore_default_focus_if_needed(host)

    assert selector.focus_calls == 0


def test_activation_skips_while_main_window_closing(qapp) -> None:
    """主窗口退出路径中不再建立新焦点。"""
    selector = _FakeSelector()
    host = _FocusHost(
        focus=None, selector=selector, close_in_progress=True
    )

    MainWindow._restore_default_focus_if_needed(host)

    assert selector.focus_calls == 0


def test_activation_without_file_selector_is_safe(qapp) -> None:
    """内容尚未构建（文件选择器为 None）时静默跳过。"""
    host = _FocusHost(focus=None, selector=None)

    MainWindow._restore_default_focus_if_needed(host)


def test_outside_click_releases_path_input_focus(qapp) -> None:
    """路径框有焦点时点击其他区域：主动释放，避免弹窗关闭后原样还给路径框。"""
    path_input = _FakePathInput(focused=True)
    host = _PathFocusHost(path_input)

    released = FileSelectorLayout.release_path_focus_on_outside_click(
        host, object()
    )

    assert released is True
    assert path_input.clear_calls == 1


def test_click_inside_path_input_keeps_focus(qapp) -> None:
    """点击路径框本身或其内嵌按钮（历史箭头）时不释放焦点。"""
    path_input = _FakePathInput(focused=True)
    host = _PathFocusHost(path_input)

    assert (
        FileSelectorLayout.release_path_focus_on_outside_click(
            host, path_input
        )
        is False
    )

    child = object()
    path_input._inside_targets.append(child)
    assert (
        FileSelectorLayout.release_path_focus_on_outside_click(host, child)
        is False
    )
    assert path_input.clear_calls == 0


def test_outside_click_without_path_focus_is_noop(qapp) -> None:
    """路径框本来没有焦点时不做任何事（可聚焦目标已由 Qt 接管）。"""
    path_input = _FakePathInput(focused=False)
    host = _PathFocusHost(path_input)

    released = FileSelectorLayout.release_path_focus_on_outside_click(
        host, object()
    )

    assert released is False
    assert path_input.clear_calls == 0


# ── 取消预览后的焦点兜底 ────────────────────────────────────────────────


class _CancelFocusHost:
    """``MainWindow._restore_selector_focus_after_cancel`` 的最小宿主替身。

    把真实方法挂到类上，使 ``self._move_focus_out_of_dead_preview()`` 的
    属性查找按实例绑定（与真实 ``MainWindow`` 上的调用形态一致）。
    """

    _move_focus_out_of_dead_preview = MainWindow._move_focus_out_of_dead_preview
    _focus_selector_with_flash = MainWindow._focus_selector_with_flash

    def __init__(
        self,
        *,
        selector: Optional[_FakeSelector] = None,
        focused_zone: Optional[str] = None,
        popup_open: bool = False,
        close_in_progress: bool = False,
    ) -> None:
        self._file_selector = selector
        self._focused_zone = focused_zone
        self._popup_open = popup_open
        self._close_in_progress = close_in_progress
        self.flashed: list = []

    def _zone_has_keyboard_focus(self, name: str) -> bool:
        return self._focused_zone == name

    def _flash_zone_focus(self, zone_name: str) -> None:
        self.flashed.append(zone_name)


@pytest.fixture()
def _no_active_popup(monkeypatch):
    """取消预览兜底会查询活动弹层；单元测试里固定为「无弹层」。"""
    from PySide6.QtWidgets import QApplication

    monkeypatch.setattr(
        QApplication, "activePopupWidget", staticmethod(lambda: None)
    )


def test_cancel_focus_falls_back_to_file_list(qapp, _no_active_popup) -> None:
    """焦点不在任何面板（典型：落到路径框）时兜底到文件列表并高亮。"""
    selector = _FakeSelector()
    host = _CancelFocusHost(selector=selector, focused_zone=None)

    MainWindow._restore_selector_focus_after_cancel(host)

    assert selector.focus_calls == 1
    assert host.flashed == ["selector"]


def test_cancel_focus_keeps_pool_focus(qapp, _no_active_popup) -> None:
    """焦点已在储存池：再次点击池内卡片取消预览时不得抢走焦点。"""
    selector = _FakeSelector()
    host = _CancelFocusHost(selector=selector, focused_zone="pool")

    MainWindow._restore_selector_focus_after_cancel(host)

    assert selector.focus_calls == 0


def test_cancel_focus_keeps_selector_focus(qapp, _no_active_popup) -> None:
    """焦点已在文件列表（点击卡片取消）：保持不动。"""
    selector = _FakeSelector()
    host = _CancelFocusHost(selector=selector, focused_zone="selector")

    MainWindow._restore_selector_focus_after_cancel(host)

    assert selector.focus_calls == 0


def test_cancel_focus_skips_while_popup_open(qapp, monkeypatch) -> None:
    """有活动弹层时不抢焦点（弹层自行管理焦点）。"""
    from PySide6.QtWidgets import QApplication

    monkeypatch.setattr(
        QApplication, "activePopupWidget", staticmethod(lambda: object())
    )
    selector = _FakeSelector()
    host = _CancelFocusHost(selector=selector, focused_zone=None)

    MainWindow._restore_selector_focus_after_cancel(host)

    assert selector.focus_calls == 0


def test_cancel_focus_skips_while_closing(qapp, _no_active_popup) -> None:
    """主窗口关闭中不再建立新焦点。"""
    selector = _FakeSelector()
    host = _CancelFocusHost(
        selector=selector, focused_zone=None, close_in_progress=True
    )

    MainWindow._restore_selector_focus_after_cancel(host)

    assert selector.focus_calls == 0


def test_cancel_focus_without_selector_is_safe(qapp, _no_active_popup) -> None:
    """选择器尚未构建（None）时静默跳过。"""
    host = _CancelFocusHost(selector=None, focused_zone=None)

    MainWindow._restore_selector_focus_after_cancel(host)


# ── 启动原生前台激活 ────────────────────────────────────────────────────


class _StartupForegroundHost:
    """``MainWindow.ensure_startup_foreground`` 的最小宿主替身。"""

    def __init__(
        self,
        *,
        hwnd: int = 0x2222,
        visible: bool = True,
        minimized: bool = False,
        close_in_progress: bool = False,
    ) -> None:
        self._startup_foreground_done = False
        self._close_in_progress = close_in_progress
        self._visible = visible
        self._minimized = minimized
        self._hwnd = hwnd
        self.raise_calls = 0
        self.activate_calls = 0

    def isVisible(self) -> bool:
        return self._visible

    def isMinimized(self) -> bool:
        return self._minimized

    def winId(self) -> int:
        return self._hwnd

    def raise_(self) -> None:
        self.raise_calls += 1

    def activateWindow(self) -> None:
        self.activate_calls += 1


@pytest.fixture()
def _native_foreground_env(monkeypatch):
    """把平台判定固定为真实 Windows 桌面，并清空活动弹层。"""
    from PySide6.QtWidgets import QApplication

    monkeypatch.setattr(
        QApplication, "platformName", staticmethod(lambda: "windows")
    )
    monkeypatch.setattr(
        QApplication, "activePopupWidget", staticmethod(lambda: None)
    )


def test_startup_foreground_activates_once(
    qapp, monkeypatch, _native_foreground_env
) -> None:
    """首次调用走原生兜底；重复调用不得再次抢焦点。"""
    import sopeek.ui.main_window as main_window_module

    force_calls: list = []
    monkeypatch.setattr(
        main_window_module, "is_foreground_window", lambda hwnd: False
    )
    monkeypatch.setattr(
        main_window_module,
        "force_foreground_window",
        lambda hwnd: force_calls.append(hwnd) or True,
    )
    host = _StartupForegroundHost()

    MainWindow.ensure_startup_foreground(host)
    MainWindow.ensure_startup_foreground(host)

    assert force_calls == [0x2222]
    assert host.raise_calls == 1
    assert host.activate_calls == 1


def test_startup_foreground_skips_force_when_already_foreground(
    qapp, monkeypatch, _native_foreground_env
) -> None:
    """已是原生前台时只做 Qt 激活，不再调用原生兜底。"""
    import sopeek.ui.main_window as main_window_module

    force_calls: list = []
    monkeypatch.setattr(
        main_window_module, "is_foreground_window", lambda hwnd: True
    )
    monkeypatch.setattr(
        main_window_module,
        "force_foreground_window",
        lambda hwnd: force_calls.append(hwnd) or True,
    )
    host = _StartupForegroundHost()

    MainWindow.ensure_startup_foreground(host)

    assert force_calls == []
    assert host.raise_calls == 1
    assert host.activate_calls == 1


def test_startup_foreground_skips_while_closing(
    qapp, monkeypatch, _native_foreground_env
) -> None:
    """关闭中不再抢前台。"""
    import sopeek.ui.main_window as main_window_module

    force_calls: list = []
    monkeypatch.setattr(
        main_window_module, "is_foreground_window", lambda hwnd: False
    )
    monkeypatch.setattr(
        main_window_module,
        "force_foreground_window",
        lambda hwnd: force_calls.append(hwnd) or True,
    )
    host = _StartupForegroundHost(close_in_progress=True)

    MainWindow.ensure_startup_foreground(host)

    assert force_calls == []
    assert host.raise_calls == 0
    assert host.activate_calls == 0


def test_startup_foreground_skips_when_minimized(
    qapp, monkeypatch, _native_foreground_env
) -> None:
    """用户启动后立即最小化时不强行拉回前台。"""
    import sopeek.ui.main_window as main_window_module

    force_calls: list = []
    monkeypatch.setattr(
        main_window_module, "is_foreground_window", lambda hwnd: False
    )
    monkeypatch.setattr(
        main_window_module,
        "force_foreground_window",
        lambda hwnd: force_calls.append(hwnd) or True,
    )
    host = _StartupForegroundHost(minimized=True)

    MainWindow.ensure_startup_foreground(host)

    assert force_calls == []
    assert host.raise_calls == 0
    assert host.activate_calls == 0


def test_startup_foreground_skips_offscreen(qapp, monkeypatch) -> None:
    """离屏测试环境不调用原生 Win32 激活。"""
    import sopeek.ui.main_window as main_window_module

    force_calls: list = []
    monkeypatch.setattr(
        main_window_module,
        "force_foreground_window",
        lambda hwnd: force_calls.append(hwnd) or True,
    )
    host = _StartupForegroundHost()

    MainWindow.ensure_startup_foreground(host)

    assert force_calls == []
    assert host.raise_calls == 0
    assert host.activate_calls == 0


def test_startup_foreground_skips_with_active_popup(
    qapp, monkeypatch, _native_foreground_env
) -> None:
    """启动时已有本进程弹层（如更新提示）：不抢弹层的焦点。"""
    import sopeek.ui.main_window as main_window_module
    from PySide6.QtWidgets import QApplication

    force_calls: list = []
    monkeypatch.setattr(
        main_window_module, "is_foreground_window", lambda hwnd: False
    )
    monkeypatch.setattr(
        main_window_module,
        "force_foreground_window",
        lambda hwnd: force_calls.append(hwnd) or True,
    )
    monkeypatch.setattr(
        QApplication, "activePopupWidget", staticmethod(lambda: object())
    )
    host = _StartupForegroundHost()

    MainWindow.ensure_startup_foreground(host)

    assert force_calls == []
    assert host.raise_calls == 0
    assert host.activate_calls == 0


# ── 鼠标点击焦点区描边 ──────────────────────────────────────────────────


class _FakeShortcutDispatcher:
    """记录区域替换的最小派发器替身（与真实实现同为「同区域 no-op」）。"""

    def __init__(self, region: str = "selector") -> None:
        self._region = region
        self.replace_calls: list = []

    def region(self) -> str:
        return self._region

    def replace_region(self, region: str) -> None:
        if region == self._region:
            return
        self._region = region
        self.replace_calls.append(region)


class _ClickRegionHost(QWidget):
    """``MainWindow._sync_region_from_click`` 的最小宿主替身。"""

    _sync_region_from_click = MainWindow._sync_region_from_click

    def __init__(self, clicked_region: str, shortcuts: _FakeShortcutDispatcher) -> None:
        super().__init__()
        self._shortcuts = shortcuts
        self._clicked_region = clicked_region
        self._child = QWidget(self)
        self._last_flash_zone = ""
        self.remembered: list = []
        self.flashed: list = []
        self._empty_cycle_selector_stay = False

    def _resolve_shortcut_region(self, _obj: QWidget) -> str:
        return self._clicked_region

    # 现有用例只验证「区域同步 + 描边去重」，不涉及空区焦点回退；
    # 三个辅助方法返回中性值，空区回退由集成测试覆盖。
    def _click_zone_name(self, _obj: QWidget) -> str:
        return ""

    def _zone_can_take_focus(self, _name: str) -> bool:
        return True

    def _is_blank_click_in_zone(self, _obj: QWidget, _zone: str) -> bool:
        return False

    def _remember_zone_before_preview(self, region: str) -> None:
        self.remembered.append(region)

    def _flash_zone_focus(self, zone_name: str) -> None:
        # 与真实实现一致：成功描边后记录区域，供下一次点击去重。
        self.flashed.append(zone_name)
        self._last_flash_zone = zone_name


def test_repeated_click_in_same_zone_flashes_once(qapp) -> None:
    """同一焦点区内连续点击：首次描边，后续不重复。"""
    shortcuts = _FakeShortcutDispatcher("selector")
    host = _ClickRegionHost("selector", shortcuts)

    host._sync_region_from_click(host._child)
    host._sync_region_from_click(host._child)

    assert shortcuts.replace_calls == []
    assert host.flashed == ["selector"]
    # 回跳记录仍然更新：点击即使不描边，也要记住当前焦点区。
    assert host.remembered == ["selector", "selector"]


def test_click_new_zone_flashes_once(qapp) -> None:
    """跨焦点区点击：切换时描边一次，随后同区点击不重复。"""
    shortcuts = _FakeShortcutDispatcher("selector")
    host = _ClickRegionHost("pool", shortcuts)

    host._sync_region_from_click(host._child)
    assert shortcuts.region() == "pool"
    assert shortcuts.replace_calls == ["pool"]
    assert host.flashed == ["pool"]

    # 第二次点击仍在储存池：焦点区未变化，不再描边。
    host._sync_region_from_click(host._child)
    assert shortcuts.replace_calls == ["pool"]
    assert host.flashed == ["pool"]


def test_click_flashes_when_region_already_synced_by_focus_changed(qapp) -> None:
    """``focusChanged`` 先把区域改到点击处时，跨区点击仍需描边。

    真实点击可聚焦控件时 Qt 会先发 ``focusChanged``，快捷键区域在鼠标
    事件过滤器执行前就已是目标区域；去重必须依据「上次高亮区域」而非
    当前区域，否则会漏掉所有跨区点击的高亮。
    """
    shortcuts = _FakeShortcutDispatcher("pool")
    host = _ClickRegionHost("pool", shortcuts)
    host._last_flash_zone = "selector"

    host._sync_region_from_click(host._child)

    assert shortcuts.replace_calls == []
    assert host.flashed == ["pool"]


def test_click_same_zone_already_highlighted_by_keyboard_does_not_flash(qapp) -> None:
    """键盘刚高亮过的区域，鼠标点击同一区域不重复描边。"""
    shortcuts = _FakeShortcutDispatcher("pool")
    host = _ClickRegionHost("pool", shortcuts)
    host._last_flash_zone = "pool"

    host._sync_region_from_click(host._child)

    assert host.flashed == []


class _FakeFlashLayout:
    """只记录区域描边调用的主布局替身。"""

    def __init__(self) -> None:
        self.flashed: list = []

    def flash_zone_focus(self, name: str) -> None:
        self.flashed.append(name)


class _FlashHost:
    """``MainWindow._flash_zone_focus`` 的最小宿主替身。"""

    _flash_zone_focus = MainWindow._flash_zone_focus

    def __init__(self) -> None:
        self._main_layout = _FakeFlashLayout()
        self._last_flash_zone = ""


def test_flash_zone_focus_records_last_highlighted_zone(qapp) -> None:
    """真实描边方法必须同步记录区域，鼠标点击去重才有依据。"""
    host = _FlashHost()

    MainWindow._flash_zone_focus(host, "pool")

    assert host._main_layout.flashed == ["pool"]
    assert host._last_flash_zone == "pool"


class _FakePathInputFocus:
    """路径框聚焦替身。"""

    def __init__(self) -> None:
        self.focus_calls = 0

    def setFocus(self) -> None:
        self.focus_calls += 1


class _FakeSelectorFocus:
    """文件选择器聚焦替身。"""

    def __init__(self) -> None:
        self._path_input = _FakePathInputFocus()
        self.focus_first_calls = 0
        self.focus_file_calls = 0

    def focus_first_entry(self) -> None:
        self.focus_first_calls += 1

    def focus_file_list(self) -> None:
        self.focus_file_calls += 1


class _KeyboardZoneHost:
    """``MainWindow._focus_zone`` 的最小宿主替身。"""

    _focus_zone = MainWindow._focus_zone

    def __init__(self, zone: str) -> None:
        self._zone = zone
        self._file_selector = _FakeSelectorFocus()
        self.flashed: list = []

    def _zone_has_keyboard_focus(self, name: str) -> bool:
        return name == self._zone

    def _flash_zone_focus(self, zone_name: str) -> None:
        self.flashed.append(zone_name)


def test_keyboard_zone_switch_still_flashes(qapp) -> None:
    """键盘切换焦点区仍描边（鼠标去重不能影响键盘路径）。"""
    host = _KeyboardZoneHost("selector")

    assert MainWindow._focus_zone(host, "selector") is True

    assert host._file_selector.focus_file_calls == 1
    assert host.flashed == ["selector"]
