# -*- coding: utf-8 -*-
"""文件选择器弹窗：单实例去重、宿主归属与模态单元测试。

覆盖验收点：

1. 同类弹窗已打开时再次触发入口 → 只前置已有实例，不重复创建
   （筛选 / 收藏夹 / 输入框）；
2. 弹窗关闭后种类占位释放，可再次打开；
3. 弹窗以选择器所在窗口为宿主（``parentWidget`` 指向宿主窗口）；
4. 选择器弹窗默认启用自定义模态，遮挡宿主窗口；
5. ``_track_dialog`` 的身份比较在弹窗销毁后不抛异常。

验证命令：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/unit/ui/layout/test_file_selector_dialogs.py -v
"""

# targets: ui.layout.file_selector_layout

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, List

import pytest
from PySide6.QtWidgets import QApplication, QWidget

_UI_ROOT: str = str(Path(__file__).resolve().parents[4] / "sopeek" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from tests.support.qt_helpers import (  # noqa: E402
    drain_deferred_deletes,
    flush_widget_queue,
    safe_teardown,
)

from sopeek.ui.layout.file_selector_layout import FileSelectorLayout  # noqa: E402
from sopeek.ui.components.styled_dialog import (  # noqa: E402
    active_dialogs,
    close_active_dialogs,
)

pytestmark = pytest.mark.unit

_LAYOUT_SIZE = (640, 480)


@pytest.fixture()
def selector(qapp: QApplication):
    """构造并清理一个挂到宿主窗口的 FileSelectorLayout。

    Yields:
        FileSelectorLayout: 已 resize/show 的选择器布局。
    """
    host = QWidget()
    host.resize(800, 600)
    layout = FileSelectorLayout(host)
    layout.resize(*_LAYOUT_SIZE)
    host.show()
    qapp.processEvents()
    try:
        yield layout
    finally:
        close_active_dialogs()
        flush_widget_queue(qapp, iterations=5)
        safe_teardown(layout)
        safe_teardown(host)
        drain_deferred_deletes(qapp)


class TestSingleInstance:
    """同类弹窗单实例语义。"""

    def test_filter_dialog_not_duplicated(
        self, qapp: QApplication, selector: FileSelectorLayout
    ) -> None:
        """连续两次打开筛选弹窗 → 只有 1 个实例。"""
        selector._show_filter_dialog()
        qapp.processEvents()
        first = selector._dialog_kinds["filter"]

        selector._show_filter_dialog()
        qapp.processEvents()

        assert selector._dialog_kinds["filter"] is first, "第二次打开不应替换实例"
        filter_dialogs = [
            d for d in active_dialogs() if d.windowTitle() == "筛选文件"
        ]
        assert len(filter_dialogs) == 1, "不应出现重复的筛选弹窗"

    def test_favorites_dialog_not_duplicated(
        self, qapp: QApplication, selector: FileSelectorLayout
    ) -> None:
        """连续两次打开收藏夹 → 只有 1 个实例。"""
        selector._show_favorites_dialog()
        qapp.processEvents()
        first = selector._dialog_kinds["favorites"]

        selector._show_favorites_dialog()
        qapp.processEvents()

        assert selector._dialog_kinds["favorites"] is first
        favorites_dialogs = [
            d for d in active_dialogs() if d.windowTitle() == "收藏夹"
        ]
        assert len(favorites_dialogs) == 1

    def test_prompt_dialog_not_duplicated(
        self, qapp: QApplication, selector: FileSelectorLayout
    ) -> None:
        """同类输入框重复触发 → 只有 1 个实例。"""
        selector._prompt_input("添加到收藏夹", "请输入收藏名称:", "demo", lambda _n: None)
        qapp.processEvents()
        kind = "prompt:添加到收藏夹"
        first = selector._dialog_kinds[kind]

        selector._prompt_input("添加到收藏夹", "请输入收藏名称:", "demo", lambda _n: None)
        qapp.processEvents()

        assert selector._dialog_kinds[kind] is first

    def test_different_kinds_coexist(
        self, qapp: QApplication, selector: FileSelectorLayout
    ) -> None:
        """不同种类弹窗互不影响（筛选 + 收藏夹可同时存在）。"""
        selector._show_filter_dialog()
        qapp.processEvents()
        selector._show_favorites_dialog()
        qapp.processEvents()

        assert "filter" in selector._dialog_kinds
        assert "favorites" in selector._dialog_kinds
        assert selector._dialog_kinds["filter"] is not selector._dialog_kinds["favorites"]

    def test_kind_released_after_close(
        self, qapp: QApplication, selector: FileSelectorLayout
    ) -> None:
        """弹窗关闭后种类占位释放，可再次打开。"""
        selector._show_filter_dialog()
        qapp.processEvents()
        first = selector._dialog_kinds["filter"]

        first.close_dialog(0)
        qapp.processEvents()

        assert "filter" not in selector._dialog_kinds
        assert first not in selector._active_dialogs

        selector._show_filter_dialog()
        qapp.processEvents()

        assert "filter" in selector._dialog_kinds
        assert selector._dialog_kinds["filter"] is not first


class TestOwnership:
    """弹窗归属与模态。"""

    def test_filter_dialog_owned_by_host_window(
        self, qapp: QApplication, selector: FileSelectorLayout
    ) -> None:
        """筛选弹窗的 parentWidget 是选择器所在窗口。"""
        selector._show_filter_dialog()
        qapp.processEvents()

        dialog = selector._dialog_kinds["filter"]
        assert dialog.parentWidget() is selector.window()
        assert dialog.isWindow() is True

    def test_filter_dialog_blocks_host(
        self, qapp: QApplication, selector: FileSelectorLayout
    ) -> None:
        """筛选弹窗启用自定义模态，宿主窗口被遮挡。"""
        from sopeek.ui.components.modal_guard import get_modal_guard

        selector._show_filter_dialog()
        qapp.processEvents()

        guard = get_modal_guard()
        assert guard.is_blocked(selector.window()) is True

        selector._dialog_kinds["filter"].close_dialog(0)
        qapp.processEvents()

        assert guard.is_blocked(selector.window()) is False

    def test_nested_prompt_owned_by_outer_dialog(
        self, qapp: QApplication, selector: FileSelectorLayout
    ) -> None:
        """弹窗内再弹输入框：以最内层弹窗为宿主（形成模态链）。"""
        selector._show_filter_dialog()
        qapp.processEvents()
        outer = selector._dialog_kinds["filter"]

        selector._prompt_input("嵌套", "请输入:", "", lambda _n: None)
        qapp.processEvents()

        inner = selector._dialog_kinds["prompt:嵌套"]
        assert inner.parentWidget() is outer

    def test_message_dialog_owned_by_selector_window(
        self, qapp: QApplication, selector: FileSelectorLayout
    ) -> None:
        """通用消息弹窗同样归属选择器所在窗口。"""
        selector._show_message_dialog("提示", "测试消息")
        qapp.processEvents()

        dialogs: List[Any] = [
            d for d in selector._active_dialogs if d.windowTitle() == "提示"
        ]
        assert len(dialogs) == 1
        assert dialogs[0].parentWidget() is selector.window()


class TestTracking:
    """``_track_dialog`` 的引用管理与销毁安全。"""

    def test_tracked_dialog_removed_on_destroy(
        self, qapp: QApplication, selector: FileSelectorLayout
    ) -> None:
        """弹窗被销毁后从跟踪列表移除，且不抛 RuntimeError。"""
        selector._show_filter_dialog()
        qapp.processEvents()
        dialog = selector._dialog_kinds["filter"]

        dialog.deleteLater()
        drain_deferred_deletes(qapp)

        assert dialog not in selector._active_dialogs
        assert "filter" not in selector._dialog_kinds

    def test_reopen_after_destroy(
        self, qapp: QApplication, selector: FileSelectorLayout
    ) -> None:
        """弹窗销毁后再次打开入口可正常创建新实例。"""
        selector._show_filter_dialog()
        qapp.processEvents()
        first = selector._dialog_kinds["filter"]

        first.deleteLater()
        drain_deferred_deletes(qapp)

        selector._show_filter_dialog()
        qapp.processEvents()

        assert "filter" in selector._dialog_kinds
        assert selector._dialog_kinds["filter"] is not first

    def test_claim_ignores_hidden_instance(
        self, qapp: QApplication, selector: FileSelectorLayout
    ) -> None:
        """占位实例已隐藏时视为失效，允许创建新弹窗。"""
        selector._show_filter_dialog()
        qapp.processEvents()
        first = selector._dialog_kinds["filter"]

        first.hide()
        qapp.processEvents()

        selector._show_filter_dialog()
        qapp.processEvents()

        assert selector._dialog_kinds["filter"] is not first
