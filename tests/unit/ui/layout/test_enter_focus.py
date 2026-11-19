# -*- coding: utf-8 -*-
"""Enter / Tab 的批量态与预览移交语义（离屏 Qt）。

覆盖：

* 文件选择器 Enter：文件 → 预览并请求移交焦点；文件夹 → 进入目录；
* 文件选择器批量态 Enter → 完全无操作；Tab → 选中项全部加入储存池；
* 储存池 Enter：预览当前卡片并请求移交焦点（重复按不再取消预览）；
* 储存池批量态 Enter → 完全无操作。

验证命令：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/unit/ui/layout/test_enter_focus.py -v
"""

from __future__ import annotations

import os
from typing import Any, Iterator, List

import pytest

pytestmark = pytest.mark.unit


def _file_entry(path: str) -> dict:
    """构造文件类型条目（7 键，供两个列表模型共用）。"""
    return {
        "name": os.path.basename(path),
        "path": path,
        "is_dir": False,
        "size": 1,
        "modified": "",
        "created": "",
        "suffix": os.path.splitext(path)[1].lstrip(".").lower(),
    }


def _dir_entry(path: str) -> dict:
    """构造目录类型条目。"""
    entry = _file_entry(path)
    entry["is_dir"] = True
    entry["suffix"] = ""
    return entry


@pytest.fixture
def selector(qapp: Any, tmp_path: Any) -> Iterator[Any]:
    """离屏文件选择器（模型直接注入，不触发磁盘扫描）。"""
    from sopeek.ui.layout.file_selector_layout import FileSelectorLayout

    widget = FileSelectorLayout()
    widget.resize(600, 400)
    widget.show()
    qapp.processEvents()
    try:
        yield widget
    finally:
        widget._unregister_shortcuts()
        widget.close()
        widget.deleteLater()
        qapp.processEvents()


@pytest.fixture
def pool(qapp: Any) -> Iterator[Any]:
    """离屏储存池。"""
    from sopeek.ui.layout.file_pool_layout import FilePoolLayout

    widget = FilePoolLayout()
    widget.resize(400, 500)
    widget.show()
    qapp.processEvents()
    try:
        yield widget
    finally:
        widget._unregister_shortcuts()
        widget.close()
        widget.deleteLater()
        qapp.processEvents()


# ── 文件选择器 ───────────────────────────────────────────────────────


def test_selector_enter_file_previews_and_requests_focus(
    selector: Any, tmp_path: Any, monkeypatch: Any
) -> None:
    """文件卡片 Enter：发 file_selected + preview_focus_requested，不外部打开。"""
    file_path = str(tmp_path / "a.png")
    selector._file_model.set_files([_file_entry(file_path)])
    selector._sync_nav_cursor(file_path)

    selected: List[dict] = []
    focus_requests: List[bool] = []
    selector.file_selected.connect(selected.append)
    selector.preview_focus_requested.connect(lambda: focus_requests.append(True))
    if hasattr(os, "startfile"):
        monkeypatch.setattr(
            os,
            "startfile",
            lambda *_a, **_k: pytest.fail("Enter 不应再用系统默认程序打开文件"),
        )

    assert selector._shortcut_enter() is True

    assert [info["path"] for info in selected] == [file_path]
    assert focus_requests == [True]


def test_selector_enter_folder_navigates_unchanged(
    selector: Any, tmp_path: Any, monkeypatch: Any
) -> None:
    """文件夹卡片 Enter：仍进入目录，且不请求移交焦点。"""
    dir_path = str(tmp_path / "sub")
    selector._file_model.set_files([_dir_entry(dir_path)])
    selector._sync_nav_cursor(dir_path)

    navigated: List[str] = []
    focus_requests: List[bool] = []
    monkeypatch.setattr(
        selector, "_navigate_to", lambda path, **_kw: navigated.append(path) or True
    )
    selector.preview_focus_requested.connect(lambda: focus_requests.append(True))

    assert selector._shortcut_enter() is True

    assert navigated == [dir_path]
    assert focus_requests == []


def test_selector_batch_enter_is_noop(
    selector: Any, tmp_path: Any, monkeypatch: Any
) -> None:
    """批量态 Enter：不导航、不预览、不入池、不移交焦点。"""
    file_path = str(tmp_path / "a.png")
    selector._file_model.set_files([_file_entry(file_path)])
    selector._sync_nav_cursor(file_path)
    selector._batch_mode = True
    selector._batch_selected = {file_path}

    selected: List[dict] = []
    focus_requests: List[bool] = []
    add_infos: List[list] = []
    navigated: List[str] = []
    selector.file_selected.connect(selected.append)
    selector.preview_focus_requested.connect(lambda: focus_requests.append(True))
    selector.add_files_to_pool_requested.connect(add_infos.append)
    monkeypatch.setattr(
        selector, "_navigate_to", lambda path, **_kw: navigated.append(path) or True
    )

    assert selector._shortcut_enter() is True

    assert selector._batch_mode is True
    assert selector._batch_selected == {file_path}
    assert selected == []
    assert focus_requests == []
    assert add_infos == []
    assert navigated == []


def test_selector_batch_tab_adds_all_to_pool(
    selector: Any, tmp_path: Any
) -> None:
    """批量态 Tab：选中项一次性全部加入储存池并退出批量态。"""
    first = str(tmp_path / "a.png")
    second = str(tmp_path / "b.png")
    selector._file_model.set_files([_file_entry(first), _file_entry(second)])
    selector._batch_mode = True
    selector._batch_selected = {first, second}

    add_infos: List[list] = []
    selector.add_files_to_pool_requested.connect(add_infos.append)

    assert selector._toggle_pool_current() is True

    assert selector._batch_mode is False
    assert selector._batch_selected == set()
    assert len(add_infos) == 1
    assert sorted(info["path"] for info in add_infos[0]) == sorted([first, second])


# ── 储存池 ───────────────────────────────────────────────────────────


def test_pool_enter_previews_and_requests_focus(
    pool: Any, tmp_path: Any
) -> None:
    """池内卡片 Enter：预览并请求移交焦点。"""
    file_path = str(tmp_path / "p.png")
    pool.add_file(_file_entry(file_path))
    pool._set_cursor(file_path)

    clicked: List[dict] = []
    focus_requests: List[bool] = []
    pool.item_left_clicked.connect(clicked.append)
    pool.preview_focus_requested.connect(lambda: focus_requests.append(True))

    assert pool._shortcut_enter() is True

    assert [info["path"] for info in clicked] == [file_path]
    assert focus_requests == [True]


def test_pool_enter_does_not_toggle_cancel_on_repeat(
    pool: Any, tmp_path: Any
) -> None:
    """重复 Enter：预览态不取消，只再次请求移交焦点。"""
    file_path = str(tmp_path / "p.png")
    pool.add_file(_file_entry(file_path))
    pool._set_cursor(file_path)
    pool.set_previewing_file(file_path)

    clicked: List[dict] = []
    cancelled: List[bool] = []
    focus_requests: List[bool] = []
    pool.item_left_clicked.connect(clicked.append)
    pool.preview_cancel_requested.connect(lambda: cancelled.append(True))
    pool.preview_focus_requested.connect(lambda: focus_requests.append(True))

    assert pool._shortcut_enter() is True

    assert clicked == []
    assert cancelled == []
    assert focus_requests == [True]


def test_pool_batch_enter_is_noop(pool: Any, qapp: Any, tmp_path: Any) -> None:
    """池内批量态 Enter：完全无操作。"""
    file_path = str(tmp_path / "p.png")
    pool.add_file(_file_entry(file_path))
    # 新卡片入场动画前处于隐藏态，_ordered_paths 会跳过；先跑一轮事件。
    qapp.processEvents()
    pool._set_cursor(file_path)
    pool.enter_batch_mode(+1, axis="row")
    assert pool._batch_mode is True

    clicked: List[dict] = []
    cancelled: List[bool] = []
    focus_requests: List[bool] = []
    pool.item_left_clicked.connect(clicked.append)
    pool.preview_cancel_requested.connect(lambda: cancelled.append(True))
    pool.preview_focus_requested.connect(lambda: focus_requests.append(True))

    assert pool._shortcut_enter() is True

    assert pool._batch_mode is True
    assert clicked == []
    assert cancelled == []
    assert focus_requests == []
