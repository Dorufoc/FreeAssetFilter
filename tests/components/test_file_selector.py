# -*- coding: utf-8 -*-
"""components 批 1（W4/todo-18）：文件选择器组件测试。

覆盖 ``freeassetfilter/components/file_selector.py`` 中
``CustomFileSelector`` 的公开 / 半公开 API：

* 构造与默认状态（current_path/filter_pattern/sort_by/sort_order/
  view_mode）、Model/View 骨架（file_model/files_scroll_area/
  control_panel/status_bar/path_edit/drive_combo）与信号定义。
* 路径校验（_is_valid_selector_path）与目录导航（_navigate_to_path →
  真实 FileListLoaderThread 加载 tmp 目录 → file_model 行数/名称）。
* "All" 视图（mock ``ctypes.windll.kernel32.GetLogicalDrives`` 位掩码，
  禁止真实枚举整机磁盘）。
* 过滤 / 排序（_filter_files / _sort_files，经 FileService）。
* 收藏加载（_load_favorites：str 旧格式归一化为 {path,name} dict，
  favorites_file 重定向到 tmp，FavoritesService 文件路径同步）。
* 预览态与滚动（set_previewing_file / clear_previewing_state /
  scroll_to_file）。

约束（计划 todo-18）：零生产代码改动；状态 JSON 文件
（save_path_file/save_view_mode_file/favorites_file）全部重定向到 tmp；
ctor 中的 ``load_last_path`` / ``_load_view_mode`` 置为 no-op 防止异步
读真实 ``data/``；DriveService 的同步 / 异步盘符枚举全部 mock；所有
跨线程等待有界（``_pump_until`` / ``wait_for_signal``），绝不
exec() 任何模态对话框。
"""

# targets: components.file_selector

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List
from unittest.mock import patch

import pytest

from freeassetfilter.components.file_selector import CustomFileSelector
from freeassetfilter.services.drive_service import DriveService

from tests.support.data_factories import make_image, make_text
from tests.support.qt_helpers import flush_widget_queue, safe_teardown

pytestmark = pytest.mark.unit


# =============================================================================
# 公共辅助
# =============================================================================
def _pump_until(
    qapp: Any,
    predicate: Callable[[], bool],
    timeout_s: float = 8.0,
) -> bool:
    """在截止期内轮询冲刷 Qt 事件直到谓词满足（有界，绝不无限等待）。

    Args:
        qapp: 会话级 QApplication 实例。
        predicate: 目标板状态谓词。
        timeout_s: 最长等待秒数。

    Returns:
        bool: 谓词在超时前满足返回 True，否则 False。
    """
    deadline: float = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        flush_widget_queue(qapp, iterations=5)
        time.sleep(0.01)
    return bool(predicate())


@pytest.fixture
def file_selector(
    qapp: Any,
    settings_manager: Any,
    tmp_path: Path,
    monkeypatch: Any,
) -> Any:
    """提供隔离的 CustomFileSelector 实例（function scope）。

    阻止 ctor 异步读写真实 ``data/`` 状态文件，并把所有持久化路径
    重定向到 tmp；盘符枚举（同步快速路径 + 异步线程静态方法）全部
    mock，避免真实磁盘扫描。

    Args:
        qapp: 会话级 QApplication。
        settings_manager: 临时设置文件绑定的 SettingsManager。
        tmp_path: pytest 内置临时目录。
        monkeypatch: pytest monkeypatch fixture。

    Returns:
        Any: 已隔离的 CustomFileSelector 实例。
    """
    monkeypatch.setattr(CustomFileSelector, "load_last_path", lambda self: None)
    monkeypatch.setattr(CustomFileSelector, "_load_view_mode", lambda self: None)
    monkeypatch.setattr(DriveService, "list_drives", lambda *a, **k: ["C:\\"])
    monkeypatch.setattr(
        DriveService, "_list_windows_drives", lambda *a, **k: ["C:\\"]
    )
    monkeypatch.setattr(
        DriveService, "_list_windows_network_locations", lambda *a, **k: []
    )

    selector: Any = CustomFileSelector(settings_manager=settings_manager)
    selector.save_path_file = str(tmp_path / "last_path.json")
    selector.save_view_mode_file = str(tmp_path / "view_mode.json")
    selector.favorites_file = str(tmp_path / "favorites.json")

    yield selector

    for thread_name in ("_file_loader_thread", "_drive_list_thread"):
        thread: Any = getattr(selector, thread_name, None)
        if thread is not None and thread.isRunning():
            if not thread.wait(2000):
                thread.terminate()
                thread.wait(1000)
    safe_teardown(selector)


def _all_files(names: List[str], base: str = "/tmp") -> List[Dict[str, Any]]:
    """按名称构造迷你 file_info 字典列表（供过滤/排序测试）。

    Args:
        names: 文件名序列。
        base: 假想父目录。

    Returns:
        list[dict]: 最小文件信息字典列表（name/path/is_dir）。
    """
    return [
        {"name": name, "path": f"{base}/{name}", "is_dir": False}
        for name in names
    ]


# =============================================================================
# 构造与默认状态
# =============================================================================
class TestConstruction:
    """构造后的默认状态与骨架。"""

    def test_default_state(self, file_selector: Any) -> None:
        """默认 filter/sort/view/current_path 字段符合初值。"""
        assert file_selector.current_path == "All"
        assert file_selector.filter_pattern == "*"
        assert file_selector.sort_by == "name"
        assert file_selector.sort_order == "asc"
        assert file_selector.view_mode == "card"

    def test_model_view_backbone_exists(self, file_selector: Any) -> None:
        """file_model/files_scroll_area/面板控件齐备。"""
        assert file_selector.file_model is not None
        assert file_selector.files_scroll_area is not None
        assert file_selector.control_panel is not None
        assert file_selector.status_bar is not None
        assert file_selector.path_edit is not None
        assert file_selector.drive_combo is not None

    def test_signals_declared(self, file_selector: Any) -> None:
        """五大公开信号均可实例化访问。"""
        for signal_name in (
            "file_selected",
            "file_right_clicked",
            "file_selection_changed",
            "preview_cancel_requested",
            "drive_availability_changed",
        ):
            assert hasattr(file_selector, signal_name)
            assert getattr(file_selector, signal_name) is not None

    def test_item_lists_empty_on_construction(self, file_selector: Any) -> None:
        """初始文件与选中集合为空。"""
        assert file_selector.file_model._files == []
        assert file_selector.selected_files == {}
        assert file_selector._selected_file_paths == set()


# =============================================================================
# 路径校验
# =============================================================================
class TestPathValidation:
    """_is_valid_selector_path 的边界判定。"""

    def test_accepts_all(self, file_selector: Any) -> None:
        """"All" 恒为合法路径。"""
        assert file_selector._is_valid_selector_path("All") is True

    def test_accepts_existing_dir(self, file_selector: Any, tmp_path: Path) -> None:
        """已存在的目录判定为合法。"""
        target: Path = tmp_path / "exists"
        target.mkdir()
        assert file_selector._is_valid_selector_path(str(target)) is True

    def test_rejects_nonexistent(self, file_selector: Any, tmp_path: Path) -> None:
        """不存在的目录判定为非法。"""
        assert file_selector._is_valid_selector_path(str(tmp_path / "nope")) is False

    def test_rejects_empty(self, file_selector: Any) -> None:
        """空串判定为非法。"""
        assert file_selector._is_valid_selector_path("") is False


# =============================================================================
# 目录导航（真实加载 tmp 目录）
# =============================================================================
class TestDirectoryNavigation:
    """_navigate_to_path → FileListLoaderThread → file_model。"""

    def test_navigate_to_tmp_dir(
        self, file_selector: Any, qapp: Any, tmp_path: Path
    ) -> None:
        """导航到含 2 文件目录后，current_path 更新且模型加载完整。

        注意：不能直接导航到 ``tmp_path`` 根——conftest 的
        ``settings_manager``/``file_selector`` fixture 会在根下写入
        ``test_settings.json``/``last_path.json``，污染目录计数。因此
        在两个文件的子目录 ``nav/`` 中导航。
        """
        nav_dir: Path = tmp_path / "nav"
        nav_dir.mkdir()
        make_text(str(nav_dir / "note.txt"))
        make_image(str(nav_dir / "pic.png"))

        file_selector._navigate_to_path(str(nav_dir))

        ok: bool = _pump_until(
            qapp,
            lambda: (not file_selector._is_loading)
            and file_selector.file_model.rowCount() == 2,
        )
        assert ok, "目录加载超时"
        assert file_selector.current_path == str(nav_dir)
        names: List[str] = [
            file_selector.file_model._files[i]["name"]
            for i in range(file_selector.file_model.rowCount())
        ]
        assert "note.txt" in names
        assert "pic.png" in names
        assert file_selector._last_accessible_path == str(nav_dir)

    def test_navigate_sets_path_edit(
        self, file_selector: Any, qapp: Any, tmp_path: Path
    ) -> None:
        """导航后面包屑输入框同步为当前路径。"""
        target: Path = tmp_path / "sub"
        target.mkdir()
        file_selector._navigate_to_path(str(target))

        ok: bool = _pump_until(qapp, lambda: not file_selector._is_loading)
        assert ok, "目录加载超时"
        assert file_selector.path_edit.text() == str(target)

    def test_all_mode_mocked_drives(
        self, file_selector: Any, qapp: Any
    ) -> None:
        """All 视图：mock GetLogicalDrives 位掩码后加载盘符条目。"""
        if os.name != "nt":
            pytest.skip("win32 All 模式需要模拟盘符位掩码")

        with patch(
            "ctypes.windll.kernel32.GetLogicalDrives", return_value=0b101
        ):
            file_selector._navigate_to_path("All")
            ok: bool = _pump_until(
                qapp,
                lambda: (not file_selector._is_loading)
                and file_selector.file_model.rowCount() >= 2,
            )
        assert ok, "All 模式加载超时"
        names: List[str] = [
            file_selector.file_model._files[i]["name"]
            for i in range(file_selector.file_model.rowCount())
        ]
        assert "A:" in names
        assert "C:" in names
        drive_a: Dict[str, Any] = file_selector.file_model._files[
            names.index("A:")
        ]
        assert drive_a["is_dir"] is True


# =============================================================================
# 过滤与排序
# =============================================================================
class TestFiltering:
    """_filter_files 的通配符过滤。"""

    def test_filter_all_keeps_everything(self, file_selector: Any) -> None:
        """`*` 模式返回全部文件。"""
        file_selector.filter_pattern = "*"
        files: List[Dict[str, Any]] = _all_files(
            ["a.txt", "b.jpg", "c.mp4"], base=str(Path("/tmp"))
        )
        filtered: List[Dict[str, Any]] = file_selector._filter_files(files)
        assert len(filtered) == 3

    def test_filter_extension_keeps_only_matching(
        self, file_selector: Any
    ) -> None:
        """`*.txt` 只保留 txt 条目。"""
        file_selector.filter_pattern = "*.txt"
        files: List[Dict[str, Any]] = _all_files(
            ["a.txt", "b.jpg"], base=str(Path("/tmp"))
        )
        filtered: List[Dict[str, Any]] = file_selector._filter_files(files)
        assert len(filtered) == 1
        assert filtered[0]["name"] == "a.txt"

    def test_filter_no_side_effect_on_input_list(
        self, file_selector: Any
    ) -> None:
        """过滤不改动传入列表本身（返回新列表）。"""
        file_selector.filter_pattern = "*.txt"
        files: List[Dict[str, Any]] = _all_files(
            ["a.txt", "b.jpg"], base=str(Path("/tmp"))
        )
        file_selector._filter_files(files)
        assert len(files) == 2


class TestSorting:
    """_sort_files 的排序方向控制。"""

    def test_sort_by_name_asc(self, file_selector: Any) -> None:
        """升序：按名称排序。"""
        file_selector.sort_by = "name"
        file_selector.sort_order = "asc"
        files: List[Dict[str, Any]] = _all_files(
            ["b.txt", "a.txt"], base=str(Path("/tmp"))
        )
        sorted_files: List[Dict[str, Any]] = file_selector._sort_files(files)
        assert [f["name"] for f in sorted_files] == ["a.txt", "b.txt"]

    def test_sort_by_name_desc(self, file_selector: Any) -> None:
        """降序：按名称反向排序。"""
        file_selector.sort_by = "name"
        file_selector.sort_order = "desc"
        files: List[Dict[str, Any]] = _all_files(
            ["a.txt", "b.txt"], base=str(Path("/tmp"))
        )
        sorted_files: List[Dict[str, Any]] = file_selector._sort_files(files)
        assert [f["name"] for f in sorted_files] == ["b.txt", "a.txt"]


# =============================================================================
# 收藏加载
# =============================================================================
class TestFavoritesLoad:
    """_load_favorites 的延迟加载与旧格式归一化。"""

    def test_load_favorites_normalizes_str_entries(
        self,
        file_selector: Any,
        qapp: Any,
        tmp_path: Path,
    ) -> None:
        """str 旧格式归一化为 {path,name} dict 条目。"""
        file_a: str = make_text(str(tmp_path / "a.txt"))
        file_b: str = make_text(str(tmp_path / "b.txt"))
        favorites_file: Path = tmp_path / "favorites.json"
        # 注意：Windows 路径含反斜杠（如 C:\\Users\\...），直接 f-string
        # 插值会破坏 JSON 转义（\\U 非法），必须用 json.dumps 序列化。
        favorites_file.write_text(
            json.dumps([file_a, {"path": file_b, "name": "b.txt"}]),
            encoding="utf-8",
        )
        file_selector.favorites_file = str(favorites_file)

        favorites: List[Dict[str, Any]] = file_selector._load_favorites()

        assert file_selector._favorites_loaded is True
        assert len(favorites) == 2
        assert favorites[0]["path"] == file_a
        assert favorites[0]["name"] == "a.txt"
        assert favorites[1]["path"] == file_b
        # FavoritesService 文件路径同步到覆盖后的 favorites_file
        assert (
            file_selector._favorites_service.favorites_file
            == str(favorites_file)
        )

    def test_load_favorites_idempotent(
        self, file_selector: Any, qapp: Any, tmp_path: Path
    ) -> None:
        """重复加载只读一次（_loaded 标志防重复 IO）。"""
        file_a: str = make_text(str(tmp_path / "a.txt"))
        favorites_file: Path = tmp_path / "favorites.json"
        favorites_file.write_text(
            json.dumps([file_a]), encoding="utf-8"
        )
        file_selector.favorites_file = str(favorites_file)

        first: List[Dict[str, Any]] = file_selector._load_favorites()
        second: List[Dict[str, Any]] = file_selector._load_favorites()
        assert first == second
        assert len(second) == 1


# =============================================================================
# 预览态与滚动
# =============================================================================
class TestPreviewAndScroll:
    """set_previewing_file / clear_previewing_state / scroll_to_file。"""

    def test_set_previewing_file_normalizes(
        self, file_selector: Any, tmp_path: Path
    ) -> None:
        """设置后 previewing_file_path 归一化为绝对路径。"""
        target: Path = tmp_path / "preview.txt"
        target.write_text("x", encoding="utf-8")
        file_selector.set_previewing_file(str(target))
        assert file_selector.previewing_file_path == os.path.normpath(str(target))

    def test_clear_previewing_state(self, file_selector: Any) -> None:
        """清除后模型内无预览条目。"""
        file_selector.file_model.set_files(
            [{"path": "/tmp/a.txt", "name": "a.txt", "is_dir": False}]
        )
        file_selector.set_previewing_file("/tmp/a.txt")
        assert file_selector.file_model._files[0].get("is_previewing") is True

        file_selector.clear_previewing_state()
        assert file_selector.file_model._files[0].get("is_previewing") is False

    def test_scroll_to_file_unknown_path_no_crash(
        self, file_selector: Any, tmp_path: Path
    ) -> None:
        """未知路径滚动静默返回（不抛异常）。"""
        file_selector.file_model.set_files([])
        file_selector.scroll_to_file(
            {"path": str(tmp_path / "missing.txt")}
        )

    def test_scroll_to_file_known_path_no_crash(
        self, file_selector: Any, tmp_path: Path
    ) -> None:
        """模型内已知路径滚动不抛异常。"""
        file_a: str = make_text(str(tmp_path / "a.txt"))
        file_selector.file_model.set_files(
            [{"path": file_a, "name": "a.txt", "is_dir": False}]
        )
        file_selector.scroll_to_file({"path": file_a})


# =============================================================================
# file_selector 内部线程 / 节流器（构造契约，不启动重型线程）
# =============================================================================

class TestFileSelectorThreads:
    """file_selector 内部 QThread：构造 + 类级接口契约。"""

    def test_drive_list_loader_thread_constructs(self, qapp: Any) -> None:
        """DriveListLoaderThread：可构造、未启动、失败路径安全。"""
        from freeassetfilter.components.file_selector import DriveListLoaderThread

        thread = DriveListLoaderThread()
        try:
            assert not thread.isRunning()
            assert hasattr(thread, "loaded")
        finally:
            if thread.isRunning():
                thread.wait(2000)
            thread.deleteLater()

    def test_file_list_loader_thread_constructs(self, qapp: Any, tmp_path: Path) -> None:
        """FileListLoaderThread：构造绑定 current_path。"""
        from freeassetfilter.components.file_selector import FileListLoaderThread

        thread = FileListLoaderThread(str(tmp_path))
        try:
            assert thread.current_path == str(tmp_path)
            assert not thread.isRunning()
        finally:
            if thread.isRunning():
                thread.wait(2000)
            thread.deleteLater()


class TestProgressThrottler:
    """ProgressThrottler：立即刷新 vs 间隔节流。"""

    def test_throttle_immediate_update(self, qapp: Any) -> None:
        """远离上次刷新的调用应同步执行 update_func。"""
        from freeassetfilter.components.file_selector import ProgressThrottler

        calls: List[Any] = []
        throttler = ProgressThrottler(min_interval_ms=1)
        try:
            throttler.update(1, 10, {"path": "x"}, lambda c, t, d: calls.append((c, t, d)))
            assert calls, "首调用（间隔足够）应立即执行"
            assert calls[-1][0] == 1
            assert calls[-1][1] == 10
        finally:
            throttler.deleteLater()

    def test_throttle_interval_respected(self, qapp: Any) -> None:
        """高频调用落入节流区间时不重复立即执行。"""
        from freeassetfilter.components.file_selector import ProgressThrottler

        calls: List[Any] = []
        throttler = ProgressThrottler(min_interval_ms=60_000)
        try:
            throttler.update(1, 10, {"path": "x"}, lambda c, t, d: calls.append((c, t, d)))
            count_after_first = len(calls)
            throttler.update(2, 10, {"path": "y"}, lambda c, t, d: calls.append((c, t, d)))
            assert len(calls) == count_after_first, "大间隔节流内不应同步执行第二次"
        finally:
            throttler.deleteLater()


class TestThumbnailGeneratorThread:
    """ThumbnailGeneratorThread：构造契约（空任务列表直接 emit finished）。"""

    def test_construct_empty_batch(self, qapp: Any) -> None:
        """空批次构造后 cancel / finished 信号契约。"""
        from freeassetfilter.components.file_selector import ThumbnailGeneratorThread

        thread = ThumbnailGeneratorThread(thumbnail_manager=None, files_to_generate=[])
        try:
            assert thread.files_to_generate == []
            thread.cancel()
            assert thread._is_cancelled is True
        finally:
            if thread.isRunning():
                thread.wait(2000)
            thread.deleteLater()

    def test_run_empty_batch_emits_finished(self, qapp: Any) -> None:
        """同步 run()：空列表直接发射 finished(0, 0)，不触碰管理器。"""
        from freeassetfilter.components.file_selector import ThumbnailGeneratorThread

        emitted: List[Dict[str, Any]] = []
        thread = ThumbnailGeneratorThread(thumbnail_manager=None, files_to_generate=[])
        thread.finished.connect(lambda s, t: emitted.append({"s": s, "t": t}))
        try:
            thread.run()
        finally:
            thread.deleteLater()
        assert emitted == [{"s": 0, "t": 0}]

    def test_run_batch_success(self, qapp: Any) -> None:
        """同步 run()：批量成功路径发射进度/完成信号。"""
        from freeassetfilter.components.file_selector import ThumbnailGeneratorThread

        progress: List[Any] = []
        created: List[Any] = []
        finished: List[Any] = []

        def fake_create_thumbnails_batch(
            _self: Any,
            files: List[Dict[str, Any]],
            progress_callback: Any = None,
            cancel_check: Any = None,
        ) -> tuple:
            # 普通函数赋值到类属性后会被绑定成实例方法，第一个位置参数
            # 必然是 _FakeManager 实例本身，因此签名首参必须是 _self。
            for i, f in enumerate(files):
                if progress_callback:
                    progress_callback(i + 1, len(files), f, True)
            return (2, 2)

        class _FakeManager:
            create_thumbnails_batch = fake_create_thumbnails_batch

        files = [{"path": f"/tmp/{n}", "name": n} for n in ("a.png", "b.mp4")]
        thread = ThumbnailGeneratorThread(
            thumbnail_manager=_FakeManager(), files_to_generate=files
        )
        thread.progress_updated.connect(
            lambda c, t, d: progress.append((c, t, d))
        )
        thread.thumbnail_created.connect(created.append)
        thread.finished.connect(lambda s, t: finished.append((s, t)))
        try:
            thread.run()
        finally:
            thread.deleteLater()
        assert len(progress) == 2
        assert [p[0] for p in progress] == [1, 2]
        assert len(created) == 2
        assert finished == [(2, 2)]

    def test_run_batch_cancel_uses_processed_count(self, qapp: Any) -> None:
        """取消后 finished 以 processed_count 为最终总数。"""
        from freeassetfilter.components.file_selector import ThumbnailGeneratorThread

        finished: List[Any] = []

        def fake_create_thumbnails_batch(
            _self: Any,
            files: List[Dict[str, Any]],
            progress_callback: Any = None,
            cancel_check: Any = None,
        ) -> tuple:
            # 模拟执行过程中被取消：只处理 1 个后返回
            return (1, 1)

        class _FakeManager:
            create_thumbnails_batch = fake_create_thumbnails_batch

        files = [{"path": f"/tmp/{n}", "name": n} for n in ("a.png", "b.mp4")]
        thread = ThumbnailGeneratorThread(thumbnail_manager=_FakeManager(), files_to_generate=files)
        thread.finished.connect(lambda s, t: finished.append((s, t)))
        try:
            thread.cancel()
            thread.run()
        finally:
            thread.deleteLater()
        assert finished == [(1, 1)]

    def test_run_batch_exception_emits_error(self, qapp: Any) -> None:
        """同步 run()：批量处理抛异常时发射 error_occurred + finished(0,0)。"""
        from freeassetfilter.components.file_selector import ThumbnailGeneratorThread

        errors: List[Any] = []
        finished: List[Any] = []

        def fake_create_thumbnails_batch(*_args: Any, **_kwargs: Any) -> tuple:
            raise RuntimeError("boom")

        class _FakeManager:
            create_thumbnails_batch = fake_create_thumbnails_batch

        files = [{"path": "/tmp/a.png", "name": "a.png"}]
        thread = ThumbnailGeneratorThread(thumbnail_manager=_FakeManager(), files_to_generate=files)
        thread.error_occurred.connect(lambda code, exc: errors.append((code, exc)))
        thread.finished.connect(lambda s, t: finished.append((s, t)))
        try:
            thread.run()
        finally:
            thread.deleteLater()
        assert errors[0][0] == "batch_generate"
        assert isinstance(errors[0][1], RuntimeError)
        assert finished == [(0, 0)]


# =============================================================================
# 线程 / 后台任务 run() 同步覆盖（QThread.start 无法被 coverage 追踪，
# 一律直接调用 run();QRunnable 同理直接调用 run()）
# =============================================================================
class TestDriveListLoaderThreadRun:
    """DriveListLoaderThread.run 同步执行：win32 与异常路径。"""

    def test_run_emits_sorted_drives(self, qapp: Any, monkeypatch: Any) -> None:
        """win32：两个源返回后去重排序并发射 loaded。"""
        from freeassetfilter.components.file_selector import DriveListLoaderThread

        monkeypatch.setattr(
            "freeassetfilter.components.file_selector.DriveService._list_windows_drives",
            lambda: ["C:\\", "A:\\", "C:\\"],
        )
        monkeypatch.setattr(
            "freeassetfilter.components.file_selector.DriveService._list_windows_network_locations",
            lambda: ["N:\\"],
        )
        thread = DriveListLoaderThread()
        results: List[Any] = []
        thread.loaded.connect(lambda l, n: results.append((l, n)))
        try:
            thread.run()
        finally:
            thread.deleteLater()
        assert results == [(["A:\\", "C:\\"], ["N:\\"])]

    def test_run_exception_logs_error(self, qapp: Any, monkeypatch: Any) -> None:
        """驱动枚举抛异常时仅记录日志，不发射 loaded。"""
        from freeassetfilter.components.file_selector import DriveListLoaderThread

        monkeypatch.setattr(
            "freeassetfilter.components.file_selector.DriveService._list_windows_drives",
            lambda: (_ for _ in ()).throw(OSError("denied")),
        )
        monkeypatch.setattr(
            "freeassetfilter.components.file_selector.DriveService._list_windows_network_locations",
            lambda: [],
        )
        thread = DriveListLoaderThread()
        results: List[Any] = []
        thread.loaded.connect(lambda l, n: results.append((l, n)))
        try:
            thread.run()
        finally:
            thread.deleteLater()
        assert results == [] or results == [([], [])]


class TestFileListLoaderThreadRun:
    """FileListLoaderThread.run 同步执行：All 模式 / 目录扫描 / 错误路径。"""

    def test_run_all_mode_win32(self, qapp: Any, monkeypatch: Any) -> None:
        """All + win32：GetLogicalDrives 位掩码产生盘符条目。"""
        if os.name != "nt":
            pytest.skip("win32 All 模式需要 ctypes")
        from freeassetfilter.components.file_selector import FileListLoaderThread

        with patch("ctypes.windll.kernel32.GetLogicalDrives", return_value=0b101):
            thread = FileListLoaderThread("All")
            loaded: List[Any] = []
            thread.loaded.connect(lambda p, f: loaded.append((p, f)))
            try:
                thread.run()
            finally:
                thread.deleteLater()
        assert loaded and loaded[0][0] == "All"
        names: List[str] = [f["name"] for f in loaded[0][1]]
        assert "A:" in names and "C:" in names

    def test_run_scans_directory(self, qapp: Any, tmp_path: Path) -> None:
        """普通目录：经 FileService 扫描后发射 loaded。"""
        from freeassetfilter.components.file_selector import FileListLoaderThread

        target: Path = tmp_path / "scan"
        target.mkdir()
        make_text(str(target / "one.txt"))

        thread = FileListLoaderThread(str(target))
        loaded: List[Any] = []
        thread.loaded.connect(lambda p, f: loaded.append((p, f)))
        try:
            thread.run()
        finally:
            thread.deleteLater()
        assert loaded and loaded[0][0] == str(target)
        names: List[str] = [f["name"] for f in loaded[0][1]]
        assert "one.txt" in names

    def test_run_refuses_symlink(self, qapp: Any, tmp_path: Path, monkeypatch: Any) -> None:
        """符号链接目录触发 failed 信号。"""
        from freeassetfilter.components.file_selector import FileListLoaderThread

        monkeypatch.setattr(
            "freeassetfilter.components.file_selector.os.path.islink", lambda p: True
        )
        thread = FileListLoaderThread(str(tmp_path))
        failed: List[Any] = []
        thread.failed.connect(lambda p, m: failed.append((p, m)))
        try:
            thread.run()
        finally:
            thread.deleteLater()
        assert len(failed) == 1
        assert "符号链接" in failed[0][1]

    def test_run_scan_failure_emits_failed(self, qapp: Any, tmp_path: Path, monkeypatch: Any) -> None:
        """扫描抛异常时发射 failed 信号。"""
        from freeassetfilter.components.file_selector import FileListLoaderThread

        class _BrokenService:
            def scan_directory(self, _path: str) -> Any:
                raise PermissionError("access denied")

        monkeypatch.setattr(
            "freeassetfilter.components.file_selector.FileService", _BrokenService
        )
        thread = FileListLoaderThread(str(tmp_path))
        failed: List[Any] = []
        thread.failed.connect(lambda p, m: failed.append((p, m)))
        try:
            thread.run()
        finally:
            thread.deleteLater()
        assert len(failed) == 1
        assert "access denied" in failed[0][1]


class TestJsonRunnables:
    """_JsonWriteRunnable / _JsonReadRunnable 同步 run()。"""

    def test_write_runnable_creates_json(self, qapp: Any, tmp_path: Path) -> None:
        """写入路径：数据函数结果序列化为 JSON 文件。"""
        from freeassetfilter.components.file_selector import _JsonWriteRunnable

        target: Path = tmp_path / "nested" / "out.json"
        runnable = _JsonWriteRunnable(
            str(target), lambda: {"last_path": "C:\\tmp"}
        )
        runnable.run()
        assert json.loads(target.read_text(encoding="utf-8")) == {
            "last_path": "C:\\tmp"
        }

    def test_write_runnable_exception_silent(self, qapp: Any, tmp_path: Path) -> None:
        """写入失败（数据函数抛异常）仅记录 warning，不向上传播。"""
        from freeassetfilter.components.file_selector import _JsonWriteRunnable

        def _boom() -> Any:
            raise OSError("disk full")

        runnable = _JsonWriteRunnable(str(tmp_path / "x.json"), _boom)
        runnable.run()  # 不应抛异常

    def test_read_runnable_missing_file(self, qapp: Any, tmp_path: Path) -> None:
        """文件不存在时发射 None。"""
        from freeassetfilter.components.file_selector import (
            _JsonReadRunnable,
            _JsonReadSignals,
        )

        signals = _JsonReadSignals()
        results: List[Any] = []
        signals.finished.connect(results.append)
        runnable = _JsonReadRunnable(str(tmp_path / "missing.json"), signals)
        runnable.run()
        assert results == [None]

    def test_read_runnable_existing_file(self, qapp: Any, tmp_path: Path) -> None:
        """文件存在时发射解析后的 dict。"""
        from freeassetfilter.components.file_selector import (
            _JsonReadRunnable,
            _JsonReadSignals,
        )

        data_file: Path = tmp_path / "data.json"
        data_file.write_text(json.dumps({"view_mode": "list"}), encoding="utf-8")
        signals = _JsonReadSignals()
        results: List[Any] = []
        signals.finished.connect(results.append)
        runnable = _JsonReadRunnable(str(data_file), signals)
        runnable.run()
        assert results == [{"view_mode": "list"}]

    def test_read_runnable_corrupt_file_emits_none(
        self, qapp: Any, tmp_path: Path
    ) -> None:
        """损坏 JSON 时发射 None。"""
        from freeassetfilter.components.file_selector import (
            _JsonReadRunnable,
            _JsonReadSignals,
        )

        data_file: Path = tmp_path / "bad.json"
        data_file.write_text("{not json", encoding="utf-8")
        signals = _JsonReadSignals()
        results: List[Any] = []
        signals.finished.connect(results.append)
        runnable = _JsonReadRunnable(str(data_file), signals)
        runnable.run()
        assert results == [None]


class TestDriveAvailabilityCheckRunnable:
    """_DriveAvailabilityCheckRunnable.run 同步执行：真实目录/空目录/缺失。"""

    def test_run_available_dir(self, qapp: Any, tmp_path: Path) -> None:
        from freeassetfilter.components.file_selector import (
            _DriveAvailabilityCheckRunnable,
            _DriveAvailabilitySignals,
        )

        signals = _DriveAvailabilitySignals()
        results: List[Any] = []
        signals.finished.connect(lambda p, a: results.append((p, a)))
        (tmp_path / "a.txt").write_text("x", encoding="utf-8")
        runnable = _DriveAvailabilityCheckRunnable(str(tmp_path), signals)
        runnable.run()
        # 发射的是原始 drive_path（不做规范化/补分隔符），与入参完全一致
        assert results and results[0][1] is True
        assert results[0][0] == str(tmp_path)

    def test_run_empty_dir_available(self, qapp: Any, tmp_path: Path) -> None:
        """空目录 scandir 抛出 StopIteration → 仍判可用。"""
        from freeassetfilter.components.file_selector import (
            _DriveAvailabilityCheckRunnable,
            _DriveAvailabilitySignals,
        )

        signals = _DriveAvailabilitySignals()
        results: List[Any] = []
        signals.finished.connect(lambda p, a: results.append((p, a)))
        runnable = _DriveAvailabilityCheckRunnable(str(tmp_path) + "\\\\", signals)
        runnable.run()
        assert results and results[0][1] is True

    def test_run_missing_dir_unavailable(self, qapp: Any, tmp_path: Path) -> None:
        """目录不存在 → 判不可用。"""
        from freeassetfilter.components.file_selector import (
            _DriveAvailabilityCheckRunnable,
            _DriveAvailabilitySignals,
        )

        signals = _DriveAvailabilitySignals()
        results: List[Any] = []
        signals.finished.connect(lambda p, a: results.append((p, a)))
        runnable = _DriveAvailabilityCheckRunnable(
            str(tmp_path / "nope"), signals
        )
        runnable.run()
        assert results and results[0][1] is False

    def test_run_exception_unavailable(self, qapp: Any, tmp_path: Path, monkeypatch: Any) -> None:
        """scandir 抛 OSError → 判不可用。"""
        from freeassetfilter.components.file_selector import (
            _DriveAvailabilityCheckRunnable,
            _DriveAvailabilitySignals,
        )

        def _broken_scandir(_p: str) -> Any:
            raise PermissionError("denied")

        monkeypatch.setattr(
            "freeassetfilter.components.file_selector.os.scandir", _broken_scandir
        )
        monkeypatch.setattr(
            "freeassetfilter.components.file_selector.os.path.exists", lambda p: True
        )
        signals = _DriveAvailabilitySignals()
        results: List[Any] = []
        signals.finished.connect(lambda p, a: results.append((p, a)))
        runnable = _DriveAvailabilityCheckRunnable(str(tmp_path), signals)
        runnable.run()
        assert results and results[0][1] is False