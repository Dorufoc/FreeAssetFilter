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
- 隐藏/系统过滤：收集期单点接线（Python 回退 + native 双路径）、实例默认
  隐藏、setter 幂等 / AND 语义 / 重扫口径
- 宿主集成：UnifiedPreviewerLayout.set_file(is_dir) → FolderPreviewerLayout；
  宿主隐藏/系统开关的创建时下发与预览中联动重扫
"""

from __future__ import annotations

import ctypes
import os
import sys
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QItemSelectionModel, Qt
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


def _set_file_attributes(path: Path, attrs: int) -> None:
    """经 Win32 SetFileAttributesW 设置文件/目录属性位。"""
    ok = ctypes.windll.kernel32.SetFileAttributesW(str(path), attrs)
    if ok == 0:
        raise OSError(ctypes.get_last_error(), f"SetFileAttributesW 失败: {path}")


def _make_hidden_system_dir(tmp_path: Path) -> Path:
    """构造含普通/隐藏/系统/双重属性与隐藏目录的临时目录。"""
    src_dir: Path = tmp_path / "hs"
    src_dir.mkdir()
    (src_dir / "normal.txt").write_text("n", encoding="utf-8")
    (src_dir / "hidden.txt").write_text("h", encoding="utf-8")
    (src_dir / "system.txt").write_text("s", encoding="utf-8")
    (src_dir / "both.txt").write_text("b", encoding="utf-8")
    hidden_dir = src_dir / "hidden_dir"
    hidden_dir.mkdir()
    _set_file_attributes(src_dir / "hidden.txt", 0x2)
    _set_file_attributes(src_dir / "system.txt", 0x4)
    _set_file_attributes(src_dir / "both.txt", 0x2 | 0x4)
    _set_file_attributes(hidden_dir, 0x2)
    return src_dir


def _wait_host_folder(
    qapp: QApplication, host: object, timeout_ms: int = 10000
) -> FolderPreviewerLayout:
    """泵事件直到统一预览器路由出已加载的 FolderPreviewerLayout。"""
    deadline = time.monotonic() + timeout_ms / 1000
    widget = None
    while time.monotonic() < deadline:
        process_qt_events(qapp, 30)
        candidate = host._current_preview_widget
        if (
            isinstance(candidate, FolderPreviewerLayout)
            and not candidate._loading
            and candidate._root_path
        ):
            widget = candidate
            break
    assert widget is not None, "文件夹预览器未在超时内就绪"
    return widget


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
            folder_mod,
            "_collect_directory_entries",
            lambda path, **kwargs: None,
        )
        layout.set_file(str(root))
        _wait_loaded(layout, qapp)
        assert layout._content_stack.currentIndex() == layout._PAGE_OVERLAY
        assert layout._placeholder.text() == _PLACEHOLDER_UNAVAILABLE
        assert layout._model.rowCount() == 0


# =============================================================================
# 隐藏/系统文件过滤（收集期单点接线 + 实例开关 + setter 重扫口径）
# =============================================================================

class TestHiddenSystemFiltering:
    """隐藏/系统过滤：收集单点、实例默认隐藏、setter 幂等/AND/重扫语义。"""

    _ALL_NAMES = ["both.txt", "hidden.txt", "hidden_dir", "normal.txt", "system.txt"]

    def test_python_fallback_filter_matrix(
        self, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """回退路径：四组开关组合的可见名集正确 + 条目仍 7 键。"""
        src_dir = _make_hidden_system_dir(tmp_path)
        monkeypatch.setattr(folder_mod, "_native_scan_directory", lambda path: None)

        def names(show_hidden: bool, show_system: bool) -> list:
            entries = folder_mod._collect_directory_entries(
                str(src_dir), show_hidden=show_hidden, show_system=show_system
            )
            assert entries is not None
            for entry in entries:
                assert set(entry.keys()) == {
                    "name", "path", "is_dir", "size",
                    "modified", "created", "suffix",
                }, "过滤后条目必须保持 7 键同构"
            return sorted(e["name"] for e in entries)

        assert names(False, False) == ["normal.txt"]
        assert names(True, False) == ["hidden.txt", "hidden_dir", "normal.txt"]
        assert names(True, True) == self._ALL_NAMES
        assert names(False, True) == ["normal.txt"]

    def test_legacy_no_flags_returns_all(
        self, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """静态直调未传开关（均 None）→ 不做过滤，保留 legacy 口径。"""
        src_dir = _make_hidden_system_dir(tmp_path)
        monkeypatch.setattr(folder_mod, "_native_scan_directory", lambda path: None)
        entries = folder_mod._collect_directory_entries(str(src_dir))
        assert entries is not None
        assert sorted(e["name"] for e in entries) == self._ALL_NAMES

    def test_instance_default_hides_hidden_and_system(
        self, qapp: QApplication, layout: FolderPreviewerLayout, tmp_path: Path
    ) -> None:
        """实例级默认口径：隐藏/系统条目不可见（仅普通条目）。"""
        src_dir = _make_hidden_system_dir(tmp_path)
        layout.set_file(str(src_dir))
        _wait_loaded(layout, qapp)
        assert sorted(_row_names(layout._model)) == ["normal.txt"]

    def test_setter_rescan_matrix_and_cascade(
        self, qapp: QApplication, layout: FolderPreviewerLayout, tmp_path: Path
    ) -> None:
        """setter：开启隐藏/系统后重扫生效；关闭隐藏级联关闭系统。"""
        src_dir = _make_hidden_system_dir(tmp_path)
        layout.set_file(str(src_dir))
        _wait_loaded(layout, qapp)
        assert sorted(_row_names(layout._model)) == ["normal.txt"]

        layout.set_show_hidden_files(True)
        _wait_loaded(layout, qapp)
        assert sorted(_row_names(layout._model)) == [
            "hidden.txt", "hidden_dir", "normal.txt",
        ]

        layout.set_show_system_files(True)
        _wait_loaded(layout, qapp)
        assert sorted(_row_names(layout._model)) == self._ALL_NAMES

        layout.set_show_hidden_files(False)
        _wait_loaded(layout, qapp)
        assert layout._show_hidden_files is False
        assert layout._show_system_files is False
        assert sorted(_row_names(layout._model)) == ["normal.txt"]

    def test_setter_idempotent_and_guards(
        self,
        qapp: QApplication,
        layout: FolderPreviewerLayout,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """setter：AND 语义 / 同值不重扫 / 未加载文件夹不重扫。"""
        refresh_calls: list = []
        monkeypatch.setattr(
            layout, "_refresh", lambda: refresh_calls.append("refresh")
        )

        # 未加载文件夹：setter 只存值不重扫
        layout.set_show_hidden_files(True)
        assert layout._show_hidden_files is True
        assert refresh_calls == []

        # 隐藏关闭时开启系统 → AND 语义 no-op，不重扫
        layout.set_show_hidden_files(False)
        layout.set_show_system_files(True)
        assert layout._show_system_files is False
        assert refresh_calls == []

        # 已加载文件夹（直接置 root）：口径变化触发重扫，同值不触发
        layout._root_path = str(tmp_path)
        layout.set_show_hidden_files(True)
        assert refresh_calls == ["refresh"]
        layout.set_show_hidden_files(True)
        assert refresh_calls == ["refresh"]
        layout.set_show_system_files(True)
        assert layout._show_system_files is True
        assert refresh_calls == ["refresh", "refresh"]
        layout.set_show_hidden_files(False)
        assert layout._show_system_files is False
        assert refresh_calls == ["refresh", "refresh", "refresh"]

    def test_native_filter_matrix_when_dll_available(
        self, qapp: QApplication, tmp_path: Path
    ) -> None:
        """native 路径：默认隐藏与开启隐藏两档可见名集正确（DLL 缺失 skip）。"""
        import freeassetfilter.core.native.bridges.faf_core_bridge as fcb_mod

        bridge = fcb_mod.get_faf_core_bridge()
        if not bridge.available or not bridge._supports_scan:  # noqa: SLF001
            pytest.skip("faf_core DLL 不可用或缺 scan 导出")
        src_dir = _make_hidden_system_dir(tmp_path)

        def names(show_hidden: bool, show_system: bool) -> list:
            entries = folder_mod._collect_directory_entries(
                str(src_dir), show_hidden=show_hidden, show_system=show_system
            )
            assert entries is not None
            return sorted(e["name"] for e in entries)

        assert names(False, False) == ["normal.txt"]
        assert names(True, False) == ["hidden.txt", "hidden_dir", "normal.txt"]


# =============================================================================
# 自动监听刷新 + 选中联动
# =============================================================================

class TestWatcherAndSelection:
    """QFileSystemWatcher 自动刷新与 entry_selected 联动信号。"""

    @staticmethod
    def _watched_dirs(layout: FolderPreviewerLayout) -> set:
        """规范化后的监听目录集合。"""
        return {os.path.normcase(p) for p in layout._watcher.directories()}

    def test_watcher_armed_on_current_dir(
        self, qapp: QApplication, layout: FolderPreviewerLayout, sample_dir: Path,
    ) -> None:
        """扫描成功后当前目录被纳入监听。"""
        layout.set_file(str(sample_dir))
        _wait_loaded(layout, qapp)
        assert os.path.normcase(str(sample_dir)) in self._watched_dirs(layout)

    def test_watcher_follows_navigation(
        self, qapp: QApplication, layout: FolderPreviewerLayout, sample_dir: Path,
    ) -> None:
        """进入子目录后监听目标切换为该子目录。"""
        layout.set_file(str(sample_dir))
        _wait_loaded(layout, qapp)
        layout._enter_dir("sub")
        _wait_loaded(layout, qapp)
        expected = os.path.normcase(str(sample_dir / "sub"))
        assert expected in self._watched_dirs(layout)

    def test_directory_changed_debounces_single_refresh(
        self,
        qapp: QApplication,
        layout: FolderPreviewerLayout,
        sample_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """连续变更事件经 300ms 防抖合并为一次重扫。"""
        layout.set_file(str(sample_dir))
        _wait_loaded(layout, qapp)
        calls: list = []
        monkeypatch.setattr(layout, "_refresh", lambda: calls.append("refresh"))

        layout._on_directory_changed(str(sample_dir))
        layout._on_directory_changed(str(sample_dir))
        process_qt_events(qapp, 30)
        assert calls == [], "防抖窗口内不应立即重扫"

        deadline = time.monotonic() + 3
        while not calls and time.monotonic() < deadline:
            process_qt_events(qapp, 30)
        assert calls == ["refresh"], "防抖到期后应恰好重扫一次"

    def test_cleanup_stops_watcher_and_timer(
        self, qapp: QApplication, layout: FolderPreviewerLayout, sample_dir: Path,
    ) -> None:
        """cleanup 移除监听路径并停止防抖定时器。"""
        layout.set_file(str(sample_dir))
        _wait_loaded(layout, qapp)
        layout._on_directory_changed(str(sample_dir))
        assert layout._watcher_debounce.isActive()

        layout.cleanup()
        assert layout._watcher.directories() == []
        assert not layout._watcher_debounce.isActive()

    def test_selection_emits_entry_then_none(
        self, qapp: QApplication, layout: FolderPreviewerLayout, sample_dir: Path,
    ) -> None:
        """选中条目发 dict（真实路径），取消选中发 None。"""
        layout.set_file(str(sample_dir))
        _wait_loaded(layout, qapp)
        received: list = []
        layout.entry_selected.connect(lambda entry: received.append(entry))

        index = layout._model.index(0, 0)
        layout._view.selectionModel().select(
            index, QItemSelectionModel.ClearAndSelect
        )
        qapp.processEvents()
        assert received, "选中后应发出信号"
        entry = received[-1]
        assert isinstance(entry, dict)
        assert str(entry["path"]).endswith("sub")
        assert entry["is_dir"] is True

        layout._view.clearSelection()
        qapp.processEvents()
        assert received[-1] is None

    def test_selection_dedup_on_repeated_select(
        self, qapp: QApplication, layout: FolderPreviewerLayout, sample_dir: Path,
    ) -> None:
        """重复选中同一路径不重复发射（去重）。"""
        layout.set_file(str(sample_dir))
        _wait_loaded(layout, qapp)
        received: list = []
        layout.entry_selected.connect(lambda entry: received.append(entry))

        index = layout._model.index(0, 0)
        layout._view.selectionModel().select(
            index, QItemSelectionModel.ClearAndSelect
        )
        qapp.processEvents()
        count_after_first = len(received)
        layout._view.selectionModel().select(
            index, QItemSelectionModel.ClearAndSelect
        )
        qapp.processEvents()
        assert len(received) == count_after_first

    def test_cleanup_emits_none_when_selected(
        self, qapp: QApplication, layout: FolderPreviewerLayout, sample_dir: Path,
    ) -> None:
        """cleanup 时若存在选中条目，对外补发一次 None。"""
        layout.set_file(str(sample_dir))
        _wait_loaded(layout, qapp)
        received: list = []
        layout.entry_selected.connect(lambda entry: received.append(entry))
        layout._view.selectionModel().select(
            layout._model.index(0, 0), QItemSelectionModel.ClearAndSelect
        )
        qapp.processEvents()
        assert received and received[-1] is not None

        layout.cleanup()
        assert received[-1] is None


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

    def test_host_forwards_flags_on_previewer_creation(
        self, qapp: QApplication, tmp_path: Path
    ) -> None:
        """宿主先存开关：文件夹预览器创建时收到快照并生效。"""
        from freeassetfilter.ui.layout.unified_previewer_layout import (
            UnifiedPreviewerLayout,
        )

        src_dir = _make_hidden_system_dir(tmp_path)
        host = UnifiedPreviewerLayout()
        host.resize(760, 640)
        host.set_show_hidden_files(True)
        host.set_show_system_files(True)
        host.set_file(
            {
                "name": src_dir.name,
                "path": str(src_dir),
                "is_dir": True,
                "size": 0,
                "modified": "",
                "created": "",
                "suffix": "",
            }
        )
        try:
            widget = _wait_host_folder(qapp, host)
            assert widget._show_hidden_files is True
            assert widget._show_system_files is True
            assert sorted(_row_names(widget._model)) == (
                TestHiddenSystemFiltering._ALL_NAMES
            )
        finally:
            host.cleanup()
            try:
                host.deleteLater()
            except RuntimeError:
                pass
            process_qt_events(qapp, 30)

    def test_host_setter_updates_live_folder_preview(
        self, qapp: QApplication, tmp_path: Path
    ) -> None:
        """预览中切换开关：当前文件夹预览器收到下发并重扫。"""
        from freeassetfilter.ui.layout.unified_previewer_layout import (
            UnifiedPreviewerLayout,
        )

        src_dir = _make_hidden_system_dir(tmp_path)
        host = UnifiedPreviewerLayout()
        host.resize(760, 640)
        host.set_file(
            {
                "name": src_dir.name,
                "path": str(src_dir),
                "is_dir": True,
                "size": 0,
                "modified": "",
                "created": "",
                "suffix": "",
            }
        )
        try:
            widget = _wait_host_folder(qapp, host)
            assert sorted(_row_names(widget._model)) == ["normal.txt"]

            host.set_show_hidden_files(True)
            _wait_loaded(widget, qapp)
            assert widget._show_hidden_files is True
            assert sorted(_row_names(widget._model)) == [
                "hidden.txt", "hidden_dir", "normal.txt",
            ]

            host.set_show_system_files(True)
            _wait_loaded(widget, qapp)
            assert sorted(_row_names(widget._model)) == (
                TestHiddenSystemFiltering._ALL_NAMES
            )

            host.set_show_hidden_files(False)
            _wait_loaded(widget, qapp)
            assert widget._show_hidden_files is False
            assert widget._show_system_files is False
            assert sorted(_row_names(widget._model)) == ["normal.txt"]
        finally:
            host.cleanup()
            try:
                host.deleteLater()
            except RuntimeError:
                pass
            process_qt_events(qapp, 30)
