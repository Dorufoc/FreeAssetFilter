# -*- coding: utf-8 -*-
"""新版文件夹预览器 FolderPreviewerLayout 单元测试。

覆盖：
- 路由注册：is_dir=True 经 PreviewerRegistry 解析为 FolderPreviewerLayout
- 条目模型：目录/文件行类型、隐藏文件不过滤、空白名跳过
- 真实文件系统（pytest tmp_path）：
  - set_file 根目录浏览、路径显示与返回按钮可用态
  - 进入子目录 → 返回根目录 → 根目录返回为空操作（不越出根文件夹）
  - 对文件条目进入无效；空目录空态文案
- 异常路径：文件夹不存在 / 扫描不可读 → 覆盖层且不崩溃；cleanup 复位
- 宿主集成：UnifiedPreviewerLayout.set_file(is_dir) → FolderPreviewerLayout
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

_PROJECT_ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / "freeassetfilter").is_dir()
)
_UI_ROOT = _PROJECT_ROOT / "freeassetfilter" / "ui"
if str(_UI_ROOT) not in sys.path:
    sys.path.insert(0, str(_UI_ROOT))
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import freeassetfilter.ui.layout.preview.folder_previewer_layout as folder_mod  # noqa: E402
from freeassetfilter.ui.layout.preview.folder_previewer_layout import (  # noqa: E402
    FolderPreviewerLayout,
    _FolderListModel,
    _PLACEHOLDER_EMPTY,
    _PLACEHOLDER_NO_FOLDER,
    _PLACEHOLDER_UNAVAILABLE,
)
from freeassetfilter.services.previewer_registry import PreviewerRegistry  # noqa: E402
from tests.support.qt_helpers import process_qt_events  # noqa: E402

pytestmark = pytest.mark.unit


# =============================================================================
# 工具
# =============================================================================

def _wait_loaded(
    layout: FolderPreviewerLayout,
    qapp: QApplication,
    timeout_ms: int = 10000,
) -> None:
    """泵事件直到扫描完成（有界等待，避免挂死）。"""
    deadline = time.monotonic() + timeout_ms / 1000
    while layout._loading and time.monotonic() < deadline:
        process_qt_events(qapp, 30)
    process_qt_events(qapp, 30)


def _row_names(model: _FolderListModel) -> list:
    """取全部行的显示文本。"""
    return [
        model.data(model.index(row), Qt.DisplayRole)
        for row in range(model.rowCount())
    ]


@pytest.fixture()
def sample_dir(tmp_path: Path) -> Path:
    """构造含文件/子目录/点文件的示例目录树。"""
    root = tmp_path / "sample_root"
    root.mkdir()
    (root / "alpha.txt").write_text("a", encoding="utf-8")
    (root / "sub").mkdir()
    (root / "sub" / "data.json").write_text("{}", encoding="utf-8")
    (root / ".hidden").write_text("h", encoding="utf-8")
    return root


@pytest.fixture()
def layout(qapp: QApplication) -> FolderPreviewerLayout:
    """创建被测预览器（测试结束自动清理）。"""
    widget = FolderPreviewerLayout(standalone=True)
    widget.resize(600, 420)
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
    """目录条目路由指向新版文件夹预览器。"""

    def test_is_dir_resolves_to_folder_previewer(self) -> None:
        """is_dir=True 解析为 FolderPreviewerLayout。"""
        cls = PreviewerRegistry.get_previewer_class({"is_dir": True, "suffix": ""})
        assert cls is not None
        assert cls.__name__ == "FolderPreviewerLayout"


# =============================================================================
# 条目模型
# =============================================================================

class TestFolderListModel:
    """条目模型行为。"""

    def test_set_entries_kinds_and_hidden(self) -> None:
        """目录/文件行类型正确，隐藏文件（点开头）不过滤。"""
        model = _FolderListModel()
        entries = [
            {"name": "a.txt", "path": "x/a.txt", "is_dir": False, "size": 1,
             "modified": "", "created": "", "suffix": "txt"},
            {"name": "d", "path": "x/d", "is_dir": True, "size": 0,
             "modified": "", "created": "", "suffix": ""},
            {"name": ".hidden", "path": "x/.hidden", "is_dir": False, "size": 1,
             "modified": "", "created": "", "suffix": ""},
        ]
        model.set_entries(entries)
        assert model.rowCount() == 3
        assert model.kind_at(0) == "file"
        assert model.kind_at(1) == "dir"
        assert model.kind_at(2) == "file"
        assert model.entry_at(1)["is_dir"] is True
        assert ".hidden" in _row_names(model)

    def test_set_entries_skips_blank_names(self) -> None:
        """空白名称条目被跳过。"""
        model = _FolderListModel()
        model.set_entries([{"name": "", "is_dir": False}])
        assert model.rowCount() == 0

    def test_clear(self) -> None:
        """clear 后为空。"""
        model = _FolderListModel()
        model.set_entries([{"name": "a.txt", "is_dir": False}])
        assert model.rowCount() == 1
        model.clear()
        assert model.rowCount() == 0


# =============================================================================
# 真实文件系统导航
# =============================================================================

class TestRealNavigation:
    """真实目录浏览导航。"""

    def test_root_listing_and_path(
        self, qapp: QApplication, layout: FolderPreviewerLayout, sample_dir: Path,
    ) -> None:
        """set_file 后列出根目录条目并显示路径。"""
        layout.set_file(str(sample_dir))
        _wait_loaded(layout, qapp)
        assert layout._root_path == str(sample_dir)
        assert layout._current_rel == ""
        names = _row_names(layout._model)
        assert "alpha.txt" in names
        assert "sub" in names
        assert ".hidden" in names
        assert layout._model.kind_at(names.index("sub")) == "dir"
        assert layout._path_edit.text() == str(sample_dir).replace("\\", "/")
        assert not layout._back_btn.isEnabled()

    def test_enter_and_back(
        self, qapp: QApplication, layout: FolderPreviewerLayout, sample_dir: Path,
    ) -> None:
        """进入子目录 → 返回根目录 → 根目录返回为空操作。"""
        layout.set_file(str(sample_dir))
        _wait_loaded(layout, qapp)

        layout._enter_dir("sub")
        _wait_loaded(layout, qapp)
        assert layout._current_rel == "sub"
        assert "data.json" in _row_names(layout._model)
        assert layout._path_edit.text().endswith("/sub")
        assert layout._back_btn.isEnabled()

        layout.go_to_parent()
        _wait_loaded(layout, qapp)
        assert layout._current_rel == ""
        assert "alpha.txt" in _row_names(layout._model)
        assert not layout._back_btn.isEnabled()

        layout.go_to_parent()
        _wait_loaded(layout, qapp)
        assert layout._current_rel == ""
        assert not layout._back_btn.isEnabled()

    def test_deep_enter_and_step_back(
        self, qapp: QApplication, layout: FolderPreviewerLayout, tmp_path: Path,
    ) -> None:
        """多级子目录逐步返回。"""
        deep = tmp_path / "deep_root"
        deep.mkdir()
        (deep / "l1").mkdir()
        (deep / "l1" / "l2").mkdir()
        (deep / "l1" / "l2" / "leaf.txt").write_text("x", encoding="utf-8")

        layout.set_file(str(deep))
        _wait_loaded(layout, qapp)
        layout._enter_dir("l1")
        _wait_loaded(layout, qapp)
        layout._enter_dir("l2")
        _wait_loaded(layout, qapp)
        assert layout._current_rel == "l1/l2"
        assert "leaf.txt" in _row_names(layout._model)

        layout.go_to_parent()
        _wait_loaded(layout, qapp)
        assert layout._current_rel == "l1"
        layout.go_to_parent()
        _wait_loaded(layout, qapp)
        assert layout._current_rel == ""

    def test_enter_file_name_ignored(
        self, qapp: QApplication, layout: FolderPreviewerLayout, sample_dir: Path,
    ) -> None:
        """对文件条目进入无效（路径不变化）。"""
        layout.set_file(str(sample_dir))
        _wait_loaded(layout, qapp)
        layout._enter_dir("alpha.txt")
        _wait_loaded(layout, qapp)
        assert layout._current_rel == ""
        assert not layout._back_btn.isEnabled()

    def test_empty_dir_overlay(
        self, qapp: QApplication, layout: FolderPreviewerLayout, tmp_path: Path,
    ) -> None:
        """空目录显示空态覆盖层。"""
        empty_dir = tmp_path / "empty_dir"
        empty_dir.mkdir()
        layout.set_file(str(empty_dir))
        _wait_loaded(layout, qapp)
        assert layout._content_stack.currentIndex() == layout._PAGE_OVERLAY
        assert layout._placeholder.text() == _PLACEHOLDER_EMPTY
        # 路径仍展示根目录
        assert layout._path_edit.text() == str(empty_dir).replace("\\", "/")

    def test_cleanup_resets(
        self, qapp: QApplication, layout: FolderPreviewerLayout, sample_dir: Path,
    ) -> None:
        """cleanup 复位全部浏览状态。"""
        layout.set_file(str(sample_dir))
        _wait_loaded(layout, qapp)
        assert layout._root_path
        layout.cleanup()
        assert layout._root_path == ""
        assert layout._current_rel == ""
        assert layout._model.rowCount() == 0
        assert layout._path_edit.text() == _PLACEHOLDER_NO_FOLDER
        assert not layout._back_btn.isEnabled()


# =============================================================================
# 异常与兜底路径
# =============================================================================

class TestFallbacks:
    """路径无效 / 扫描不可读。"""

    def test_missing_folder_quiet_cleanup(
        self, qapp: QApplication, layout: FolderPreviewerLayout, tmp_path: Path,
    ) -> None:
        """文件夹不存在：静默回到占位态且不崩溃。"""
        layout.set_file(str(tmp_path / "not_exists_dir"))
        assert layout._root_path == ""
        assert layout._placeholder.text() == _PLACEHOLDER_NO_FOLDER

    def test_unreadable_folder_overlay(
        self,
        qapp: QApplication,
        layout: FolderPreviewerLayout,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """扫描返回 None（不可读）→ 覆盖层提示且不崩溃。"""
        root = tmp_path / "locked_root"
        root.mkdir()
        (root / "a.txt").write_text("x", encoding="utf-8")
        monkeypatch.setattr(
            folder_mod, "_collect_directory_entries", lambda path: None
        )
        layout.set_file(str(root))
        _wait_loaded(layout, qapp)
        assert layout._content_stack.currentIndex() == layout._PAGE_OVERLAY
        assert layout._placeholder.text() == _PLACEHOLDER_UNAVAILABLE
        assert layout._model.rowCount() == 0


# =============================================================================
# 宿主集成
# =============================================================================

class TestHostIntegration:
    """统一预览器宿主对 is_dir 的路由。"""

    def test_unified_previewer_routes_folder(
        self, qapp: QApplication, sample_dir: Path,
    ) -> None:
        """UnifiedPreviewerLayout.set_file(is_dir=True) → FolderPreviewerLayout。"""
        from freeassetfilter.ui.layout.unified_previewer_layout import (
            UnifiedPreviewerLayout,
        )

        host = UnifiedPreviewerLayout()
        host.resize(760, 640)
        host.set_file(
            {
                "name": sample_dir.name,
                "path": str(sample_dir),
                "is_dir": True,
                "size": 0,
                "modified": "",
                "created": "",
                "suffix": "",
            }
        )
        try:
            deadline = time.monotonic() + 10
            widget = host._current_preview_widget
            while time.monotonic() < deadline:
                process_qt_events(qapp, 30)
                widget = host._current_preview_widget
                if widget is None:
                    continue
                preview = widget
                if isinstance(preview, FolderPreviewerLayout):
                    if preview._model.rowCount() > 0:
                        break
            assert widget is not None
            assert isinstance(widget, FolderPreviewerLayout)
            assert widget._root_path == str(sample_dir)
            assert widget._model.rowCount() >= 2
            assert "alpha.txt" in _row_names(widget._model)
        finally:
            host.cleanup()
            try:
                host.deleteLater()
            except RuntimeError:
                pass
            process_qt_events(qapp, 30)
