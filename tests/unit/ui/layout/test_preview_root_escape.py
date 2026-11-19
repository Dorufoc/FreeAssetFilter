# -*- coding: utf-8 -*-
"""压缩包 / 文件夹预览器「根目录 Esc 交还焦点」回归。

背景（用户需求）：焦点在预览器内且预览的是压缩包/文件夹时，``Esc`` 逐级
返回到根目录；已在根目录时再按 ``Esc`` 应把焦点交还「进入预览器之前」的
焦点区，并让该区光标刷新到第一个卡片。

本文件锁定以下契约：

* 文件夹预览器：子目录 ``Esc`` 返回上一级且不惊动宿主；根目录交给宿主；
  加载中不消费；独立运行（无宿主）不消费；
* 压缩包预览器：退搜索优先，其次包内上一级，最后根目录交给宿主；
* ``UnifiedPreviewerLayout`` 的宿主回调转发（无宿主时不消费）；
* ``FileSelectorLayout.focus_first_entry``：优先第一个非文件夹条目、全为
  文件夹回退第 0 行、All 视图同样生效、空模型不崩且不动光标。

验证命令：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/unit/ui/layout/test_preview_root_escape.py -v
"""

from __future__ import annotations

import os
from typing import Any, Iterator, List

import pytest
from PySide6.QtTest import QTest

from sopeek.ui.layout.file_selector_layout import FileSelectorLayout
from sopeek.ui.layout.preview.archive_previewer_layout import (
    ArchivePreviewerLayout,
)
from sopeek.ui.layout.preview.folder_previewer_layout import (
    FolderPreviewerLayout,
)
from sopeek.ui.layout.unified_previewer_layout import UnifiedPreviewerLayout

pytestmark = [pytest.mark.unit, pytest.mark.widgets]


# ── 工具 ─────────────────────────────────────────────────────────────


def _consume_chain(provider: Any) -> bool:
    """按派发器语义执行 Esc 链：第一个返回 True 的处理器胜出。"""
    for handler in provider.escape_handlers():
        if handler():
            return True
    return False


@pytest.fixture()
def folder_previewer(qapp: Any) -> Iterator[FolderPreviewerLayout]:
    """已显示的文件夹预览器（销毁时注销快捷键登记）。"""
    widget = FolderPreviewerLayout()
    widget.resize(800, 500)
    widget.show()
    QTest.qWait(30)
    qapp.processEvents()
    try:
        yield widget
    finally:
        widget.cleanup()
        widget.close()
        widget.deleteLater()
        qapp.processEvents()


@pytest.fixture()
def archive_previewer(qapp: Any) -> Iterator[ArchivePreviewerLayout]:
    """已显示的压缩包预览器（销毁时注销快捷键登记）。"""
    widget = ArchivePreviewerLayout()
    widget.resize(800, 500)
    widget.show()
    QTest.qWait(30)
    qapp.processEvents()
    try:
        yield widget
    finally:
        widget.cleanup()
        widget.close()
        widget.deleteLater()
        qapp.processEvents()


# ── 文件夹预览器 ─────────────────────────────────────────────────────


def test_folder_escape_chain_has_parent_then_host(
    folder_previewer: FolderPreviewerLayout,
) -> None:
    """链顺序固定：先返回上一级，再在根目录交还宿主。"""
    assert len(folder_previewer.escape_handlers()) == 2


def test_folder_escape_in_subdir_goes_parent_without_host(
    folder_previewer: FolderPreviewerLayout, monkeypatch: Any
) -> None:
    """子目录 Esc：返回上一级并消费，宿主回调不被调用。"""
    folder_previewer._root_path = os.path.join("C:\\", "root")
    folder_previewer._current_rel = "sub"
    calls: List[str] = []
    monkeypatch.setattr(folder_previewer, "go_to_parent", lambda: calls.append("parent"))
    folder_previewer.set_root_escape_handler(
        lambda: calls.append("host") or True
    )

    assert _consume_chain(folder_previewer) is True
    assert calls == ["parent"]


def test_folder_escape_at_root_hands_focus_to_host(
    folder_previewer: FolderPreviewerLayout, monkeypatch: Any
) -> None:
    """根目录 Esc：交给宿主并消费；不再调用 go_to_parent。"""
    folder_previewer._root_path = os.path.join("C:\\", "root")
    folder_previewer._current_rel = ""
    calls: List[str] = []
    monkeypatch.setattr(
        folder_previewer, "go_to_parent", lambda: calls.append("parent")
    )
    folder_previewer.set_root_escape_handler(
        lambda: calls.append("host") or True
    )

    assert _consume_chain(folder_previewer) is True
    assert calls == ["host"]


def test_folder_escape_at_root_without_host_not_consumed(
    folder_previewer: FolderPreviewerLayout,
) -> None:
    """独立运行（无宿主）：根目录 Esc 不消费，行为与旧版一致。"""
    folder_previewer._current_rel = ""
    assert _consume_chain(folder_previewer) is False


def test_folder_escape_at_root_host_declines_not_consumed(
    folder_previewer: FolderPreviewerLayout,
) -> None:
    """宿主无法接管焦点（返回 False）时 Esc 放行。"""
    folder_previewer._current_rel = ""
    folder_previewer.set_root_escape_handler(lambda: False)
    assert _consume_chain(folder_previewer) is False


def test_folder_escape_loading_does_not_exit(
    folder_previewer: FolderPreviewerLayout, monkeypatch: Any
) -> None:
    """加载中（子目录）不返回上级、也不把焦点甩出预览器。"""
    folder_previewer._root_path = os.path.join("C:\\", "root")
    folder_previewer._current_rel = "sub"
    folder_previewer._loading = True
    calls: List[str] = []
    monkeypatch.setattr(
        folder_previewer, "go_to_parent", lambda: calls.append("parent")
    )
    folder_previewer.set_root_escape_handler(
        lambda: calls.append("host") or True
    )

    assert _consume_chain(folder_previewer) is False
    assert calls == []


def test_dispatcher_consumes_folder_escape_at_root(
    folder_previewer: FolderPreviewerLayout, qapp: Any, monkeypatch: Any
) -> None:
    """端到端：派发器按 ``preview.folder`` 区域执行链并消费根目录 Esc。"""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication

    from sopeek.core.shortcuts import shortcut_dispatcher

    # 清掉前序用例残留的焦点：文本输入控件会让派发器放行纯 Esc
    focus = QApplication.focusWidget()
    if focus is not None:
        focus.clearFocus()
    qapp.processEvents()

    dispatcher = shortcut_dispatcher()
    # 弹层状态由其它用例共享（全局计数），与本用例无关 → 显式放行上下文阻断
    monkeypatch.setattr(dispatcher, "_context_blocked", lambda: False)
    previous_region = dispatcher.region()
    folder_previewer._root_path = os.path.join("C:\\", "root")
    folder_previewer._current_rel = ""
    calls: List[str] = []
    folder_previewer.set_root_escape_handler(
        lambda: calls.append("host") or True
    )
    dispatcher.replace_region("preview.folder")
    event = QKeyEvent(
        QEvent.Type.KeyPress,
        int(Qt.Key.Key_Escape),
        Qt.KeyboardModifier.NoModifier,
    )
    try:
        assert dispatcher.eventFilter(None, event) is True
    finally:
        dispatcher.replace_region(previous_region)
    assert calls == ["host"]


# ── 压缩包预览器 ─────────────────────────────────────────────────────


def test_archive_escape_chain_order(archive_previewer: ArchivePreviewerLayout) -> None:
    """链顺序固定：退搜索 → 包内上一级 → 根目录交还宿主。"""
    assert len(archive_previewer.escape_handlers()) == 3


def test_archive_escape_exits_search_first(
    archive_previewer: ArchivePreviewerLayout, monkeypatch: Any
) -> None:
    """搜索态 Esc：先退出搜索并消费，不触发返回/交还。"""
    archive_previewer._search_mode = True
    calls: List[str] = []
    monkeypatch.setattr(
        archive_previewer, "_exit_search_mode", lambda: calls.append("search")
    )
    monkeypatch.setattr(
        archive_previewer, "go_to_parent", lambda: calls.append("parent")
    )
    archive_previewer.set_root_escape_handler(
        lambda: calls.append("host") or True
    )

    assert _consume_chain(archive_previewer) is True
    assert calls == ["search"]
    archive_previewer._search_mode = False


def test_archive_escape_in_subdir_goes_parent(
    archive_previewer: ArchivePreviewerLayout, monkeypatch: Any
) -> None:
    """包内子目录 Esc：返回上一级并消费。"""
    archive_previewer._current_path = "a/b"
    calls: List[str] = []
    monkeypatch.setattr(
        archive_previewer, "go_to_parent", lambda: calls.append("parent")
    )
    archive_previewer.set_root_escape_handler(
        lambda: calls.append("host") or True
    )

    assert _consume_chain(archive_previewer) is True
    assert calls == ["parent"]


def test_archive_escape_at_root_hands_focus_to_host(
    archive_previewer: ArchivePreviewerLayout, monkeypatch: Any
) -> None:
    """包内根目录 Esc：交给宿主并消费。"""
    archive_previewer._current_path = ""
    calls: List[str] = []
    monkeypatch.setattr(
        archive_previewer, "go_to_parent", lambda: calls.append("parent")
    )
    archive_previewer.set_root_escape_handler(
        lambda: calls.append("host") or True
    )

    assert _consume_chain(archive_previewer) is True
    assert calls == ["host"]


def test_archive_escape_at_root_without_host_not_consumed(
    archive_previewer: ArchivePreviewerLayout,
) -> None:
    """独立运行（无宿主）：根目录 Esc 不消费。"""
    archive_previewer._current_path = ""
    archive_previewer._search_mode = False
    assert _consume_chain(archive_previewer) is False


# ── UnifiedPreviewerLayout 转发 ─────────────────────────────────────


class _ForwardingHost:
    """最小化复用 UnifiedPreviewerLayout 的转发方法（不构造 QWidget）。"""

    _root_escape_handler = None
    _forward_root_escape = UnifiedPreviewerLayout._forward_root_escape
    _apply_root_escape_handler = UnifiedPreviewerLayout._apply_root_escape_handler


class _FakePreviewer:
    """记录宿主回调下发的预览器替身。"""

    def __init__(self) -> None:
        self.handler = None

    def set_root_escape_handler(self, handler) -> None:
        self.handler = handler


def test_unified_forward_without_host_returns_false() -> None:
    """未登记宿主回调时不消费（内层预览器保持旧行为）。"""
    host = _ForwardingHost()
    assert host._forward_root_escape() is False


def test_unified_forward_returns_host_result() -> None:
    """转发器返回宿主回调结果（True/False 原样透传）。"""
    host = _ForwardingHost()
    host._root_escape_handler = lambda: True
    assert host._forward_root_escape() is True
    host._root_escape_handler = lambda: False
    assert host._forward_root_escape() is False


def test_unified_applies_handler_to_inner_previewer() -> None:
    """登记宿主回调时同步下发给当前内层预览器（调用即转发）。"""
    host = _ForwardingHost()
    host._root_escape_handler = lambda: True
    previewer = _FakePreviewer()

    host._apply_root_escape_handler(previewer)

    assert previewer.handler is not None
    assert previewer.handler() is True


# ── 文件选择器落点 ───────────────────────────────────────────────────


def _entry(name: str, *, is_dir: bool = False) -> dict:
    """构造与目录扫描产物同构的 7 键条目。"""
    return {
        "name": name,
        "path": os.path.join("C:\\root_escape", name),
        "is_dir": is_dir,
        "size": 0 if is_dir else 1024,
        "modified": "2026-01-01 00:00",
        "created": "2026-01-01 00:00",
        "suffix": "" if is_dir else os.path.splitext(name)[1].lstrip("."),
    }


@pytest.fixture
def selector(qapp: Any) -> Iterator[FileSelectorLayout]:
    """稳定下来的文件选择器（等异步 All 视图落地后再喂自定义模型）。"""
    widget = FileSelectorLayout()
    widget.resize(640, 480)
    widget.show()
    QTest.qWait(50)
    qapp.processEvents()
    try:
        yield widget
    finally:
        widget.close()
        widget.deleteLater()
        qapp.processEvents()


def _install_entries(
    selector: FileSelectorLayout, entries: List[dict], path: str = "C:\\root_escape"
) -> None:
    selector._current_path = path
    selector._file_model.set_files(entries)
    selector._update_grid_size()
    selector.clear_nav_cursor()
    selector.set_previewing_file("")
    QTest.qWait(20)


def test_focus_first_entry_skips_leading_dirs(
    selector: FileSelectorLayout,
) -> None:
    """混合目录：落点是第一个非文件夹条目，且不改预览高亮。"""
    entries = [
        _entry("dir_a", is_dir=True),
        _entry("a.png"),
        _entry("b.png"),
    ]
    _install_entries(selector, entries)

    selector.focus_first_entry()

    assert selector._nav_cursor_row == 1
    assert selector._nav_cursor_path == os.path.normpath(entries[1]["path"])
    # 只移导航光标：预览高亮保持为空
    assert selector._previewing_file_path == ""
    # 手势状态已复位，下一次方向键从落点继续
    assert selector._nav_active is False
    assert selector._nav_last_key == 0


def test_focus_first_entry_all_dirs_falls_back_to_first_row(
    selector: FileSelectorLayout,
) -> None:
    """目录内全是文件夹：落点回退第 0 行。"""
    entries = [_entry("dir_a", is_dir=True), _entry("dir_b", is_dir=True)]
    _install_entries(selector, entries)

    selector.focus_first_entry()

    assert selector._nav_cursor_row == 0
    assert selector._nav_cursor_path == os.path.normpath(entries[0]["path"])


def test_focus_first_entry_works_in_all_view(
    selector: FileSelectorLayout,
) -> None:
    """All 视图同样落位（不会被 ``_prime_cursor_first_entry`` 的早退拦住）。"""
    entries = [_entry("dir_a", is_dir=True), _entry("a.png")]
    _install_entries(selector, entries, path="All")

    selector.focus_first_entry()

    assert selector._nav_cursor_row == 1
    assert selector._nav_cursor_path == os.path.normpath(entries[1]["path"])


def test_focus_first_entry_empty_model_keeps_cursor(
    selector: FileSelectorLayout,
) -> None:
    """空模型：不崩、不动光标，仅把焦点交给列表。"""
    _install_entries(selector, [])

    selector.focus_first_entry()

    assert selector._nav_cursor_row == -1
    assert selector._nav_cursor_path == ""
