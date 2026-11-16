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
* 点击路径框本身或其内嵌按钮 → 保持焦点。

验证：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/unit/ui/test_main_window_focus.py -v
"""

from __future__ import annotations

from typing import Any, Optional

import pytest

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
