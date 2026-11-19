# -*- coding: utf-8 -*-
"""启动默认焦点回归（真实主窗口的延迟构建路径）。

背景：正式启动先显示轻量外壳，文件选择器、预览器、储存池等四区在
``show()`` 之后才由 ``initialize_deferred_content`` 分阶段构建。窗口激活时
默认焦点兜底拿不到文件选择器，若不再补一次，启动完成后没有任何焦点控件，
方向键 / Enter 文件导航不可用。

本文件锁定以下契约：

* 延迟内容构建完成后，键盘焦点落到文件选择器的文件列表；
* 快捷键区域同步为 ``selector``；
* 启动补焦点只执行一次，不会在用户把焦点移到路径框后再次抢回。

验证命令：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/integration/test_startup_focus.py -v
"""

from __future__ import annotations

import time
from typing import Any, Callable, Iterator

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from sopeek.core.shortcuts import reset_dispatcher_for_tests

pytestmark = pytest.mark.integration


def _wait_until(
    qapp: Any, predicate: Callable[[], bool], timeout_ms: int = 3000
) -> bool:
    """处理事件直到条件成立或超时。"""
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        QTest.qWait(20)
    return False


@pytest.fixture
def window(qapp: Any) -> Iterator[Any]:
    """按正式启动顺序构造主窗口：轻量壳显示后再构建四区。"""
    from sopeek.ui.main_window import MainWindow

    win = MainWindow(defer_heavy_init=True)
    win.resize(1200, 800)
    win.show()
    QTest.qWait(50)
    win.initialize_deferred_content()
    try:
        # 四区构建是 show 后的链式定时任务，先等文件选择器落地再交给用例。
        assert _wait_until(qapp, lambda: win._file_selector is not None)
        yield win
    finally:
        win.close()
        win.deleteLater()
        qapp.processEvents()
        reset_dispatcher_for_tests()


def test_startup_focus_lands_on_file_selector(window: Any, qapp: Any) -> None:
    """四区就绪后默认焦点必须落在文件列表，且区域为 selector。"""
    selector = window._file_selector
    assert selector is not None

    assert _wait_until(
        qapp, lambda: QApplication.focusWidget() is selector._file_list
    )
    assert selector._file_list.hasFocus()
    assert window._shortcuts.region() == "selector"


def test_startup_focus_is_one_shot(window: Any, qapp: Any) -> None:
    """启动补焦点只执行一次：用户把焦点移到路径框后不得再次抢回。"""
    selector = window._file_selector
    assert _wait_until(
        qapp, lambda: QApplication.focusWidget() is selector._file_list
    )

    selector._path_input.setFocus()
    QApplication.processEvents()
    assert selector._path_input.hasFocus()

    window._focus_selector_on_startup()
    QApplication.processEvents()
    assert selector._path_input.hasFocus()
