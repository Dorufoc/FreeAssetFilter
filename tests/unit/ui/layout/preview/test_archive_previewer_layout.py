# -*- coding: utf-8 -*-
"""新版压缩包预览器 ArchivePreviewerLayout 单元测试。

覆盖：
- 路由注册：zip 等压缩后缀经 PreviewerRegistry 解析为 ArchivePreviewerLayout
- 条目模型：文件/目录/警示行（\ufffd 替换符）行类型与 flags
- 真实 7z 环境（py7z_available 跳过守卫）：
  - set_file 根目录浏览、路径显示与返回按钮可用态
  - 双击进入（_enter_dir）→ 返回（go_to_parent）→ 根目录返回为空操作
  - 空压缩包空态文案、cleanup 复位
- 异常路径：无效路径弹窗且不崩溃（monkeypatch 拦截弹窗）
- 乱码警示行：monkeypatch 7z 核心返回含替换符条目 → 顶部警示行出现
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import QApplication, QWidget

_PROJECT_ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / "freeassetfilter").is_dir()
)
_UI_ROOT = _PROJECT_ROOT / "freeassetfilter" / "ui"
if str(_UI_ROOT) not in sys.path:
    sys.path.insert(0, str(_UI_ROOT))
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import freeassetfilter.ui.layout.preview.archive_previewer_layout as archive_mod  # noqa: E402
from freeassetfilter.ui.layout.preview.archive_previewer_layout import (  # noqa: E402
    ArchivePreviewerLayout,
    _ArchiveListModel,
    _PLACEHOLDER_NO_ARCHIVE,
    _PLACEHOLDER_ROOT_EMPTY,
    _WARNING_TEXT,
)
from freeassetfilter.services.previewer_registry import PreviewerRegistry  # noqa: E402
from tests.support.qt_helpers import process_qt_events  # noqa: E402

pytestmark = pytest.mark.unit


# =============================================================================
# 工具
# =============================================================================

def _wait_loaded(
    layout: ArchivePreviewerLayout,
    qapp: QApplication,
    timeout_ms: int = 15000,
) -> None:
    """泵事件直到列表读取完成（有界等待，避免挂死）。"""
    deadline = time.monotonic() + timeout_ms / 1000
    while layout._loading and time.monotonic() < deadline:
        process_qt_events(qapp, 30)
    process_qt_events(qapp, 30)


def _make_layout(qapp: QApplication) -> ArchivePreviewerLayout:
    layout = ArchivePreviewerLayout(standalone=True)
    layout.resize(600, 420)
    return layout


def _row_names(model: _ArchiveListModel) -> list:
    """取全部行的显示文本（跳过警示行）。"""
    return [
        model.data(model.index(row), Qt.DisplayRole)
        for row in range(model.rowCount())
        if model.kind_at(row) != "warning"
    ]


@pytest.fixture()
def layout(qapp: QApplication) -> ArchivePreviewerLayout:
    """创建被测预览器（测试结束自动清理）。"""
    widget = _make_layout(qapp)
    yield widget
    widget.cleanup()
    try:
        widget.deleteLater()
    except RuntimeError:
        pass
    process_qt_events(qapp, 30)


# =============================================================================
# 路由注册
# =============================================================================

class TestRegistry:
    """压缩后缀路由指向新版预览器。"""

    def test_archive_suffixes_resolve_to_new_layout(self) -> None:
        """全部压缩包后缀解析为 ArchivePreviewerLayout。"""
        for ext in ("zip", "rar", "tar", "gz", "tgz", "bz2", "xz", "7z", "iso"):
            cls = PreviewerRegistry.get_previewer_class({"suffix": ext})
            assert cls is not None, f"{ext} 未注册"
            assert cls.__name__ == "ArchivePreviewerLayout"


# =============================================================================
# 条目模型
# =============================================================================

class TestArchiveListModel:
    """条目模型行为。"""

    def _make_model(self) -> _ArchiveListModel:
        return _ArchiveListModel()

    def test_set_entries_dirs_files_ordering(self) -> None:
        """目录条目 is_dir 保持、无警示行时不插入警示行。"""
        model = self._make_model()
        entries = [
            {"name": "b.txt", "path": "b.txt", "is_dir": False, "size": 1,
             "modified": "", "suffix": "txt"},
            {"name": "a", "path": "a", "is_dir": True, "size": 0,
             "modified": "", "suffix": ""},
        ]
        model.set_entries(entries)
        assert model.rowCount() == 2
        assert model.kind_at(0) == "file"
        assert model.kind_at(1) == "dir"
        assert model.entry_at(1)["is_dir"] is True
        assert model.has_entries()

    def test_set_entries_skips_blank_names(self) -> None:
        """空白名称条目被跳过。"""
        model = self._make_model()
        model.set_entries([{"name": "", "is_dir": False}])
        assert model.rowCount() == 0
        assert not model.has_entries()

    def test_replacement_char_inserts_warning_row(self) -> None:
        """含替换符（\\ufffd）时顶部插入不可选警示行。"""
        model = self._make_model()
        model.set_entries([{"name": "bad\ufffdname.txt", "is_dir": False}])
        assert model.rowCount() == 2
        assert model.kind_at(0) == "warning"
        assert model.data(model.index(0), Qt.DisplayRole) == _WARNING_TEXT
        flags = model.flags(model.index(0))
        assert not flags & Qt.ItemIsSelectable
        assert not flags & Qt.ItemIsEnabled
        assert model.kind_at(1) == "file"
        assert model.has_entries()

    def test_clear_and_empty(self) -> None:
        """clear 后为空。"""
        model = self._make_model()
        model.set_entries([{"name": "a.txt", "is_dir": False}])
        assert model.rowCount() == 1
        model.clear()
        assert model.rowCount() == 0


# =============================================================================
# 真实 7z 集成（无 7z.exe 时跳过）
# =============================================================================

class TestRealListing:
    """真实压缩包浏览导航。"""

    def test_root_listing_and_path(
        self, qapp: QApplication, layout: ArchivePreviewerLayout,
        sample_zip_file: str, py7z_available: bool,
    ) -> None:
        """set_file 后从根目录列出条目并显示路径。"""
        if not py7z_available:
            pytest.skip("7z.exe 不可用")
        layout.set_file(sample_zip_file)
        _wait_loaded(layout, qapp)
        assert layout._archive_path == sample_zip_file
        assert layout._current_path == ""
        names = _row_names(layout._model)
        assert "hello.txt" in names
        assert "subdir" in names
        assert layout._path_edit.text() == Path(sample_zip_file).name
        assert not layout._back_btn.isEnabled()

    def test_enter_and_back(
        self, qapp: QApplication, layout: ArchivePreviewerLayout,
        sample_zip_file: str, py7z_available: bool,
    ) -> None:
        """进入子目录 → 返回根目录 → 根目录返回为空操作。"""
        if not py7z_available:
            pytest.skip("7z.exe 不可用")
        layout.set_file(sample_zip_file)
        _wait_loaded(layout, qapp)

        layout._enter_dir("subdir")
        _wait_loaded(layout, qapp)
        assert layout._current_path == "subdir"
        assert "data.json" in _row_names(layout._model)
        assert layout._path_edit.text().endswith("/subdir")
        assert layout._back_btn.isEnabled()

        layout.go_to_parent()
        _wait_loaded(layout, qapp)
        assert layout._current_path == ""
        assert "hello.txt" in _row_names(layout._model)
        assert not layout._back_btn.isEnabled()

        layout.go_to_parent()
        _wait_loaded(layout, qapp)
        assert layout._current_path == ""
        assert layout._back_btn.isEnabled() is False

    def test_enter_file_name_ignored(
        self, qapp: QApplication, layout: ArchivePreviewerLayout,
        sample_zip_file: str, py7z_available: bool,
    ) -> None:
        """对文件条目调用进入无效（路径不变化）。"""
        if not py7z_available:
            pytest.skip("7z.exe 不可用")
        layout.set_file(sample_zip_file)
        _wait_loaded(layout, qapp)
        layout._enter_dir("hello.txt")
        _wait_loaded(layout, qapp)
        assert layout._current_path == ""
        assert layout._back_btn.isEnabled() is False

    def test_empty_archive_overlay(
        self, qapp: QApplication, layout: ArchivePreviewerLayout,
        tmp_path: Path, py7z_available: bool,
    ) -> None:
        """空压缩包显示"无内容或无法读取"覆盖层。"""
        if not py7z_available:
            pytest.skip("7z.exe 不可用")
        from tests.support.data_factories import make_zip

        empty_zip = make_zip(tmp_path / "empty.zip", {})
        layout.set_file(str(empty_zip))
        _wait_loaded(layout, qapp)
        assert layout._content_stack.currentIndex() == layout._PAGE_OVERLAY
        assert layout._placeholder.text() == _PLACEHOLDER_ROOT_EMPTY

    def test_cleanup_resets(
        self, qapp: QApplication, layout: ArchivePreviewerLayout,
        sample_zip_file: str, py7z_available: bool,
    ) -> None:
        """cleanup 复位全部浏览状态。"""
        if not py7z_available:
            pytest.skip("7z.exe 不可用")
        layout.set_file(sample_zip_file)
        _wait_loaded(layout, qapp)
        assert layout._archive_path
        layout.cleanup()
        assert layout._archive_path == ""
        assert layout._current_path == ""
        assert layout._model.rowCount() == 0
        assert layout._path_edit.text() == _PLACEHOLDER_NO_ARCHIVE
        assert not layout._back_btn.isEnabled()


# =============================================================================
# 异常与兜底路径
# =============================================================================

class TestFallbacks:
    """无效路径 / 乱码警示行。"""

    def test_invalid_path_shows_dialog_without_crash(
        self,
        qapp: QApplication,
        layout: ArchivePreviewerLayout,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """无效压缩包路径弹窗提示且保持空态。"""
        shown: list = []

        def _fake_dialog(title: str, message: str, *args: Any, **kwargs: Any) -> None:
            shown.append((title, message))

        monkeypatch.setattr(archive_mod, "_show_custom_dialog", _fake_dialog)
        layout.set_file(str(Path("not_exists_dir/not_exists.zip")))
        assert shown, "应弹出错误弹窗"
        assert "无法预览压缩包" in shown[0][0]
        assert "无效的压缩包路径" in shown[0][1]
        assert layout._archive_path == ""
        assert layout._placeholder.text() == _PLACEHOLDER_NO_ARCHIVE

    def test_encoding_warning_row_on_replacement_names(
        self,
        qapp: QApplication,
        layout: ArchivePreviewerLayout,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """7z 核心返回含替换符条目 → 列表顶部出现警示行。"""
        class _FakeCore:
            def list_archive(self, archive_path: str, current_path: str = ""):
                return [
                    {"name": "ok.txt", "path": "ok.txt", "is_dir": False,
                     "size": 1, "modified": "", "suffix": "txt"},
                    {"name": "bad\ufffdname.txt", "path": "bad\ufffdname.txt",
                     "is_dir": False, "size": 2, "modified": "", "suffix": "txt"},
                ]

        dummy = tmp_path / "dummy.zip"
        dummy.write_bytes(b"PK")
        monkeypatch.setattr(archive_mod, "get_7z_core", lambda: _FakeCore())
        layout.set_file(str(dummy))
        _wait_loaded(layout, qapp)
        model = layout._model
        assert model.rowCount() == 3
        assert model.kind_at(0) == "warning"
        assert model.kind_at(1) == "file"
        assert model.kind_at(2) == "file"
        assert "ok.txt" in _row_names(model)


# =============================================================================
# 交互细节（视图级）
# =============================================================================

class TestViewInteraction:
    """空白点击取消选中 / 警示行不可选中。"""

    def test_blank_press_clears_selection(
        self, qapp: QApplication, layout: ArchivePreviewerLayout,
        sample_zip_file: str, py7z_available: bool,
    ) -> None:
        """点击空白区域清除全部选中。"""
        if not py7z_available:
            pytest.skip("7z.exe 不可用")
        layout.set_file(sample_zip_file)
        _wait_loaded(layout, qapp)
        view = layout._view
        assert view.model().rowCount() > 0
        view.setCurrentIndex(view.model().index(0))
        assert view.currentIndex().isValid()
        # 视口外深处的坐标视为空白点击
        view._handle_mouse_press_select(QPoint(5, 5000))
        assert not view.currentIndex().isValid()
        assert view.selectionModel().selectedIndexes() == []

    def test_warning_row_cannot_be_selected(
        self,
        qapp: QApplication,
        layout: ArchivePreviewerLayout,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """警示行不会被空白点击逻辑选中。"""
        class _FakeCore:
            def list_archive(self, archive_path: str, current_path: str = ""):
                return [
                    {"name": "bad\ufffdname.txt", "path": "x", "is_dir": False,
                     "size": 1, "modified": "", "suffix": "txt"},
                ]

        dummy = tmp_path / "dummy.zip"
        dummy.write_bytes(b"PK")
        monkeypatch.setattr(archive_mod, "get_7z_core", lambda: _FakeCore())
        layout.set_file(str(dummy))
        _wait_loaded(layout, qapp)
        view = layout._view
        assert view.model().kind_at(0) == "warning"
        view._handle_mouse_press_select(QPoint(5, 5))
        assert not view.currentIndex().isValid()
