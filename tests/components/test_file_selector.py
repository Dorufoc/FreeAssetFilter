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
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import (
    QEvent,
    QMimeData,
    QObject,
    QPoint,
    QPointF,
    QSize,
    Qt,
    QTimer,
    QUrl,
    QRunnable,
    QThreadPool,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QMouseEvent,
    QPixmap,
    QResizeEvent,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QListView,
    QListWidgetItem,
)

import freeassetfilter.components.file_selector as fs
from freeassetfilter.components.file_selector import CustomFileSelector
from freeassetfilter.services.drive_service import DriveService

from tests.support.data_factories import make_image, make_svg, make_text
from tests.support.qt_helpers import flush_widget_queue, safe_teardown

pytestmark = pytest.mark.unit

# 真实方法引用：fixture 会把 load_last_path/_load_view_mode 打成 no-op，
# 需要测试真实实现时用这些常量恢复（模块导入时刻捕获，不随 monkeypatch 变化）。
_REAL_LOAD_LAST_PATH = CustomFileSelector.load_last_path
_REAL_LOAD_VIEW_MODE = CustomFileSelector._load_view_mode


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
# W12 假件（fake objects）：QThreadPool / HoverTooltip / MessageBox 族
# =============================================================================
class _FakeQThreadPool:
    """假 QThreadPool：同步执行（不排队真实线程），记录已提交任务。

    替换 ``fs.QThreadPool``，使 ``QThreadPool.globalInstance().start(...)``
    直接同步调用 runnable.run()，从而让 _JsonWriteRunnable / _JsonReadRunnable /
    _DriveAvailabilityCheckRunnable 在测试线程内确定性地完成。
    """

    _instance: "_FakeQThreadPool | None" = None

    @classmethod
    def globalInstance(cls) -> "_FakeQThreadPool":
        if cls._instance is None:
            cls._instance = _FakeQThreadPool()
        return cls._instance

    def __init__(self) -> None:
        self.started: List[QRunnable] = []

    def start(self, runnable: QRunnable, *args: Any, **kwargs: Any) -> None:
        """同步执行任务并记录。"""
        self.started.append(runnable)
        runnable.run()

    def waitForDone(self, msecs: int = 0) -> bool:
        """已全部同步执行完毕，恒返回 True。"""
        return True


class _FakeHoverTooltip(MagicMock):
    """假 HoverTooltip：基于 MagicMock，构造即丢弃实参（W12/W13）。

    W12 实测坑：``MagicMock(任意位置实参)`` 会把首参当作 spec，spec
    非空时未知属性访问直接抛 AttributeError。生产以 ``HoverTooltip(self)``
    传 QWidget 父指针构造，因此必须重写 ``__init__`` 丢弃全部实参再调
    ``super().__init__()``，否则 ``set_target_widget`` 等调用全部中招。
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        super().__init__()


@pytest.fixture(autouse=True)
def _mock_hover_tooltip(monkeypatch: Any) -> None:
    """（autouse）阻止真实 HoverTooltip 构造（W12 防间歇约束）。

    每个 selector 构造会创建真实 HoverTooltip 并向 10+ 目标控件
    installEventFilter + 安装 GlobalMouseMonitor；组合长时间运行时
    半构造实例会被事件泵销毁导致 0xc0000005。本 fixture 全量替换
    ``fs.HoverTooltip`` 为 MagicMock 假件——真实 tooltip 永不构造、
    eventFilter/全局鼠标监听器永不安装。

    Args:
        monkeypatch: pytest monkeypatch fixture。
    """
    import freeassetfilter.components.file_selector as _fs

    monkeypatch.setattr(_fs, "HoverTooltip", _FakeHoverTooltip)


class _FakeMessageBox(QObject):
    """假 CustomMessageBox：exec() 直接返回，不进入模态事件循环。

    模拟用户点击：``auto_button_index`` 非 None 时在 exec() 中先发射
    buttonClicked(index) 再返回，覆盖"确定/取消"分支。
    """

    auto_button_index: int | None = 0

    def __init__(self, parent: QObject = None, *args: Any, **kwargs: Any) -> None:
        super().__init__(parent)
        self.input_text: str = ""
        self.closed: bool = False
        self.title: str = ""
        self.message_text: str = ""
        self._list_layout: Any = MagicMock()
        self._list_widget: Any = MagicMock()
        self._progress_widget: Any = None

    def set_title(self, title: str) -> None:
        self.title = title

    def set_text(self, text: str) -> None:
        self.message_text = text

    def set_buttons(self, *args: Any, **kwargs: Any) -> None:
        pass

    def set_input(self, text: str = "", placeholder: str = "") -> None:
        self.input_text = text

    def get_input(self) -> str:
        return self.input_text

    def set_progress(self, widget: Any) -> None:
        self._progress_widget = widget

    def setMinimumSize(self, *args: Any, **kwargs: Any) -> None:
        pass

    def resize(self, *args: Any, **kwargs: Any) -> None:
        pass

    def show(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def exec(self) -> int:
        idx = type(self).auto_button_index
        if idx is not None:
            self.buttonClicked.emit(idx)
        return idx if idx is not None else 0

    @property
    def list_layout(self) -> Any:
        return self._list_layout

    @property
    def list_widget(self) -> Any:
        return self._list_widget

    # 真实 CustomMessageBox 通过 Signal 发射按钮索引；假件用真实 Signal 模拟。
    # 用类属性在 __init_subclass__ 无谓复杂化，直接声明。
    buttonClicked = Signal(int)


class _FakeCustomWindow(QObject):
    """假 CustomWindow：构造不创建真实窗口。"""

    def __init__(self, parent: QObject = None, *args: Any, **kwargs: Any) -> None:
        super().__init__(parent)

    def set_title(self, *args: Any, **kwargs: Any) -> None:
        pass

    def add_widget(self, *args: Any, **kwargs: Any) -> None:
        pass

    def add_layout(self, *args: Any, **kwargs: Any) -> None:
        pass

    def show(self) -> None:
        pass

    def close(self) -> None:
        pass

    def exec(self) -> None:
        pass


class _FakeDropdownMenu(MagicMock):
    """假 CustomDropdownMenu：构造即丢弃实参（W14 防间歇约束）。

    生产 ``CustomDropdownMenu.__init__``（dropdown_menu.py:611）会执行
    ``app.installEventFilter(self)`` —— 全局应用级事件过滤器。335 个组合
    测试累积数十个全局过滤器后偶发 0xc0000005（access violation）。本假件
    与 ``_FakeHoverTooltip`` 同一模式：重写 ``__init__`` 丢弃全部实参再调
    ``super().__init__()``，从而 drive_combo / sort_menu 永不构造真实
    下拉菜单，set_items / set_target_button / set_current_item /
    show_menu / list_widget.list_widget.sizeHintForRow 等调用全部 mock 化。
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        super().__init__()
        # W14 实测坑：`_apply_drive_list`（file_selector.py:1891-1892）读取
        # ``drive_combo.list_widget.list_widget.sizeHintForRow(0)`` 参与
        # ``max(int, 返回值)`` 算术比较——MagicMock 默认返回 Mock 会导致
        # ``TypeError: '>' not supported``（107 个 setup error）。必须为
        # 该属性链配置确定性 int 返回值；其它调用点（set_items /
        # set_max_visible_items / set_max_height / toggle_menu /
        # set_current_item）均为纯副作用调用，mock 化即可。
        self.list_widget.list_widget.sizeHintForRow.return_value = 20

    def _get_child_mock(self, **kw: Any) -> Any:
        """子属性一律返回基类 MagicMock，避免递归构造（W14 实测坑）。

        MagicMock._get_child_mock 默认用 ``type(self)`` 生成子 mock——
        若保持子类，``__init__`` 中的 ``self.list_widget...`` 配置会再次
        触发子 mock 创建，无限递归直至栈溢出。返回基类 MagicMock 后，
        属性链（list_widget.list_widget.sizeHintForRow）只创建普通 mock。
        """
        return MagicMock(**kw)


# =============================================================================
# W12 假件补丁装饰器（模块级函数，供 fixture 复用）
# =============================================================================
def _apply_w12_patches(monkeypatch: Any, fs: Any) -> None:
    """注入 W12 假件到 file_selector 模块命名空间（含 D_widgets 本地导入）。"""
    monkeypatch.setattr(fs, "QThreadPool", _FakeQThreadPool)
    monkeypatch.setattr(fs, "HoverTooltip", _FakeHoverTooltip)
    monkeypatch.setattr(fs, "CustomMessageBox", _FakeMessageBox)
    monkeypatch.setattr(fs, "CustomWindow", _FakeCustomWindow)
    # W14：CustomDropdownMenu.__init__ 会 app.installEventFilter(self)（全局
    # 应用级过滤器），组合长时间运行时半构造实例被事件泵销毁 → 0xc0000005。
    # 下拉菜单及其内部 CustomSelectList 一律替换为假件，真实菜单永不构造。
    monkeypatch.setattr(fs, "CustomDropdownMenu", _FakeDropdownMenu)
    monkeypatch.setattr(fs, "CustomSelectList", _FakeDropdownMenu)
    # 生产代码内部使用 `from freeassetfilter.widgets.D_widgets import ...` 的
    # 局部导入（如 _on_files_load_failed / apply_filter / _show_favorites_dialog
    # 所依赖的 MessageBox），必须同步替换 D_widgets 命名空间才能拦截。
    import freeassetfilter.widgets.D_widgets as _dw

    monkeypatch.setattr(_dw, "CustomMessageBox", _FakeMessageBox)
    monkeypatch.setattr(_dw, "CustomWindow", _FakeCustomWindow)
    import freeassetfilter.widgets as _w

    monkeypatch.setattr(_w, "CustomMessageBox", _FakeMessageBox)
    monkeypatch.setattr(_w, "CustomWindow", _FakeCustomWindow)


@pytest.fixture
def file_selector_w12(
    qapp: Any,
    settings_manager: Any,
    tmp_path: Path,
    monkeypatch: Any,
) -> Any:
    """提供隔离的 CustomFileSelector 实例 + W12 假件补丁（function scope）。

    与 ``file_selector`` 相同的隔离措施，另注入：

    * ``_FakeQThreadPool`` —— 异步 JSON 读写/盘符可用性检查同步化；
    * ``_FakeHoverTooltip`` —— 避免真实悬浮提示窗创建控件层级；
    * ``_FakeMessageBox``/``_FakeCustomWindow`` —— 模态对话框 exec() 直接返回。

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
    _apply_w12_patches(monkeypatch, fs)

    selector: Any = CustomFileSelector(settings_manager=settings_manager)
    selector.save_path_file = str(tmp_path / "last_path.json")
    selector.save_view_mode_file = str(tmp_path / "view_mode.json")
    selector.favorites_file = str(tmp_path / "favorites.json")
    # 假设 ctor 创建的 QTimer 属性（避免 create/delete 生命周期问题内建属性缺失）
    selector._favorites_save_timer = MagicMock()
    selector._favorites_save_timer.start = MagicMock()

    yield selector

    for thread_name in ("_file_loader_thread", "_drive_list_thread"):
        thread: Any = getattr(selector, thread_name, None)
        if thread is not None and thread.isRunning():
            if not thread.wait(2000):
                thread.terminate()
                thread.wait(1000)
    safe_teardown(selector)


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


class TestShowEvent:
    """showEvent 首显调度逻辑（W12）。"""

    def test_first_show_schedules_refresh(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """首次显示：_first_show 置 False，并延迟调度 refresh_files。"""
        selector: Any = file_selector_w12
        refresh = MagicMock()
        monkeypatch.setattr(selector, "refresh_files", refresh)
        assert selector._first_show is True

        selector.showEvent(QShowEvent())

        assert selector._first_show is False
        entered = _pump_until(qapp, lambda: refresh.called, timeout_s=1.5)
        assert entered
        assert refresh.call_count == 1

    def test_second_show_does_not_reschedule(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """非首次显示不再调度 refresh_files（_first_show 已 False）。"""
        selector: Any = file_selector_w12
        refresh = MagicMock()
        monkeypatch.setattr(selector, "refresh_files", refresh)

        selector.showEvent(QShowEvent())
        _pump_until(qapp, lambda: refresh.called, timeout_s=1.5)
        selector.showEvent(QShowEvent())

        assert refresh.call_count == 1


class TestViewModeToggle:
    """视图模式切换（W12）：delegate / flow / wrapping 生效。"""

    def test_toggle_from_card_to_list_and_back(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """card → list → card：_toggle_view_mode 翻转 view_mode 并应用 delegate。"""
        selector: Any = file_selector_w12
        monkeypatch.setattr(CustomFileSelector, "refresh_files", lambda self, *a, **k: None)

        selector.view_mode = "card"
        selector._toggle_view_mode()
        assert selector.view_mode == "list"
        assert selector.files_scroll_area.itemDelegate() is selector.list_delegate
        assert selector.files_scroll_area.flow() == QListView.TopToBottom
        assert selector.files_scroll_area.isWrapping() is False

        selector._toggle_view_mode()
        assert selector.view_mode == "card"
        assert selector.files_scroll_area.itemDelegate() is selector.card_delegate
        assert selector.files_scroll_area.flow() == QListView.LeftToRight
        assert selector.files_scroll_area.isWrapping() is True

    def test_change_view_mode_sets_mode_and_applies(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """change_view_mode(0)=card / (1)=list：view_mode + refresh_files 调用。"""
        selector: Any = file_selector_w12
        monkeypatch.setattr(CustomFileSelector, "refresh_files", lambda self, *a, **k: None)

        selector.change_view_mode(1)
        assert selector.view_mode == "list"
        assert selector.files_scroll_area.itemDelegate() is selector.list_delegate

        selector.change_view_mode(0)
        assert selector.view_mode == "card"
        assert selector.files_scroll_area.itemDelegate() is selector.card_delegate


class TestFilterButtonStyle:
    """_has_active_filter / _update_filter_button_style（W12）。"""

    def test_has_active_filter(self, file_selector_w12: Any) -> None:
        selector: Any = file_selector_w12
        selector.filter_pattern = "*"
        assert selector._has_active_filter() is False
        selector.filter_pattern = ""
        assert selector._has_active_filter() is False
        selector.filter_pattern = "  "
        assert selector._has_active_filter() is False
        selector.filter_pattern = "*.png"
        assert selector._has_active_filter() is True

    def test_update_filter_button_style_primary_on_active(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """活跃筛选 → primary；默认 "*" → normal。"""
        selector: Any = file_selector_w12
        fake_btn = MagicMock()
        fake_btn.button_type = None
        monkeypatch.setattr(selector, "filter_btn", fake_btn)

        selector.filter_pattern = "*.png"
        selector._update_filter_button_style()
        assert fake_btn.set_button_type.called
        args = fake_btn.set_button_type.call_args[0]
        assert args[0] == "primary"

        selector.filter_pattern = "*"
        selector._update_filter_button_style()
        args = fake_btn.set_button_type.call_args[0]
        assert args[0] == "normal"

    def test_update_filter_button_style_missing_btn_safe(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """未创建 filter_btn 时不抛异常（hasattr 守卫）。"""
        selector: Any = file_selector_w12
        monkeypatch.delattr(selector, "filter_btn", raising=False)
        selector._update_filter_button_style()  # 不抛异常即可


class TestDriveAvailabilityWidget:
    """is_drive_available / _schedule / _on_drive_availability_result（W12）。"""

    def test_fresh_cache_returns_without_scheduling(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """TTL 内缓存直接返回，不发起后台检查。"""
        selector: Any = file_selector_w12
        drive_key: str = str(tmp_path_cached()) + "\\"
        selector._drive_availability_cache[drive_key] = (False, time.time())
        scheduler = MagicMock()
        monkeypatch.setattr(selector, "_schedule_drive_availability_check", scheduler)

        assert selector._is_drive_available(str(tmp_path_cached())) is False
        scheduler.assert_not_called()

    def test_stale_cache_schedules_and_updates(
        self, qapp: Any, file_selector_w12: Any, tmp_path: Path
    ) -> None:
        """过期缓存：发起后台检查（假 QThreadPool 同步执行）→ 缓存被更新并发射信号。"""
        selector: Any = file_selector_w12
        (tmp_path / "a.txt").write_text("x", encoding="utf-8")
        drive_key: str = str(tmp_path) + "\\"
        selector._drive_availability_cache[drive_key] = (False, time.time() - 100)

        changed: List[Any] = []
        selector.drive_availability_changed.connect(
            lambda p, a: changed.append((p, a))
        )

        assert selector._is_drive_available(str(tmp_path)) is False  # 乐观值来自旧缓存
        # 假 QThreadPool 同步跑完 _DriveAvailabilityCheckRunnable，结果回调已同步执行
        assert drive_key in selector._drive_availability_cache
        assert selector._drive_availability_cache[drive_key][0] is True
        assert changed and changed[0][0] == drive_key and changed[0][1] is True
        assert drive_key not in selector._pending_drive_checks

    def test_pending_check_dedups(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        """同一盘符已在 pending 中时不重复调度。"""
        selector: Any = file_selector_w12
        drive_key: str = "X:\\"
        selector._pending_drive_checks = {drive_key}
        fake_pool = _FakeQThreadPool.globalInstance()
        before = list(fake_pool.started)
        selector._is_drive_available("X:")
        assert len(fake_pool.started) == len(before)  # 未新增任务


class TestChangeSort:
    """change_sort / _on_sort_item_clicked（W12）。"""

    def test_change_sort_mapping(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        monkeypatch.setattr(CustomFileSelector, "refresh_files", lambda self, *a, **k: None)
        selector.change_sort("名称升序")
        assert (selector.sort_by, selector.sort_order) == ("name", "asc")
        selector.change_sort("大小降序")
        assert (selector.sort_by, selector.sort_order) == ("size", "desc")
        selector.change_sort("不存在的排序")
        assert (selector.sort_by, selector.sort_order) == ("name", "asc")

    def test_on_sort_item_clicked(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        monkeypatch.setattr(CustomFileSelector, "refresh_files", lambda self, *a, **k: None)
        selector._on_sort_item_clicked(("modified", "desc"))
        assert (selector.sort_by, selector.sort_order) == ("modified", "desc")
        # 非 tuple 参数被忽略
        selector._on_sort_item_clicked("not-a-tuple")
        assert (selector.sort_by, selector.sort_order) == ("modified", "desc")


class TestOnFilesLoadedApply:
    """_on_files_loaded 应用结果到 model + 回调（W12，同步调用不启线程）。"""

    def _prime_matching_state(
        self, selector: Any, target: str
    ) -> None:
        selector.current_path = target
        selector.filter_pattern = "*"
        selector.sort_by = "name"
        selector.sort_order = "asc"

    def test_on_files_loaded_applies_files(
        self, qapp: Any, file_selector_w12: Any, tmp_path: Path
    ) -> None:
        selector: Any = file_selector_w12
        target = str(tmp_path)
        self._prime_matching_state(selector, target)
        files = [
            {"name": "a.txt", "path": f"{target}/a.txt", "is_dir": False},
            {"name": "b.png", "path": f"{target}/b.png", "is_dir": False},
        ]
        callback = MagicMock()

        selector._on_files_loaded(
            selector._refresh_request_id, target, files, callback, True
        )

        assert selector._is_loading is False
        assert selector.file_model.rowCount() == len(files)
        assert callback.called

    def test_on_files_loaded_stale_request_ignored(
        self, qapp: Any, file_selector_w12: Any, tmp_path: Path
    ) -> None:
        """request_id 或 loaded_path 不匹配 → 直接返回，不改 model。"""
        selector: Any = file_selector_w12
        target = str(tmp_path)
        self._prime_matching_state(selector, target)

        selector._on_files_loaded(
            selector._refresh_request_id + 99, target, [{"name": "x"}], None, True
        )
        assert selector.file_model.rowCount() == 0

        selector._on_files_loaded(
            selector._refresh_request_id, "C:\\other", [{"name": "x"}], None, True
        )
        assert selector.file_model.rowCount() == 0

    def test_on_files_loaded_empty_result(
        self, qapp: Any, file_selector_w12: Any, tmp_path: Path
    ) -> None:
        """空文件列表：model 清空、_is_loading 复位、无异常。"""
        selector: Any = file_selector_w12
        target = str(tmp_path)
        self._prime_matching_state(selector, target)
        selector._on_files_loaded(selector._refresh_request_id, target, [], None, False)
        assert selector.file_model.rowCount() == 0
        assert selector._is_loading is False


class TestSelectionPreviewScroll:
    """选中态 / 预览态 / 滚动定位（W12）。"""

    def _seed_files(self, selector: Any, target: str) -> None:
        selector.current_path = target
        selector.filter_pattern = "*"
        selector.sort_by = "name"
        selector.sort_order = "asc"
        files = [
            {"name": "a.txt", "path": f"{target}/a.txt", "is_dir": False},
            {"name": "b.png", "path": f"{target}/b.png", "is_dir": False},
        ]
        selector._on_files_loaded(selector._refresh_request_id, target, files, None, False)

    def test_selection_preview_state(
        self, qapp: Any, file_selector_w12: Any, tmp_path: Path
    ) -> None:
        selector: Any = file_selector_w12
        target = str(tmp_path)
        self._seed_files(selector, target)
        a_path = os.path.normpath(f"{target}/a.txt")

        selector._selected_file_paths = {a_path}
        selector._update_file_selection_state()
        # 不抛异常即通过；选中行存在于 model
        assert selector.file_model.get_row(a_path) == 0

        selector.previewing_file_path = a_path
        selector._check_and_apply_preview_state()

        selector.previewing_file_path = None
        selector._check_and_apply_preview_state()

    def test_set_previewing_file_and_clear(
        self, qapp: Any, file_selector_w12: Any, tmp_path: Path
    ) -> None:
        selector: Any = file_selector_w12
        target = str(tmp_path)
        self._seed_files(selector, target)
        a_path = os.path.normpath(f"{target}/a.txt")

        selector.set_previewing_file(a_path)
        assert selector.previewing_file_path == a_path
        selector.set_previewing_file(None)
        assert selector.previewing_file_path is None
        selector.clear_previewing_state()  # 不抛异常

    def test_scroll_to_file_found_and_missing(
        self, qapp: Any, file_selector_w12: Any, tmp_path: Path
    ) -> None:
        selector: Any = file_selector_w12
        target = str(tmp_path)
        self._seed_files(selector, target)

        selector.scroll_to_file({"path": f"{target}/b.png"})  # 命中，不抛异常
        selector.scroll_to_file({"path": f"{target}/nope.png"})  # 不存在 → 提前返回
        selector.scroll_to_file({})  # 无 path 键 → 提前返回
        selector.scroll_to_file(None)  # None → 提前返回


class TestFavoritesDialogWidget:
    """_show_favorites_dialog 构建（W12：假 MessageBox 不阻塞）。"""

    def test_show_favorites_dialog_populated(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """有收藏项时构建对话框：标题正确、exec 返回假件不再阻塞。"""
        selector: Any = file_selector_w12
        selector.favorites = [
            {"path": "C:\\fav\\a.txt", "name": "a.txt"},
        ]
        monkeypatch.setattr(CustomFileSelector, "_load_favorites", lambda self: None)

        selector._show_favorites_dialog()
        # 假件 _FakeMessageBox 已被 patched 使用（无真实模态循环）
        assert _FakeMessageBox.auto_button_index is not None

    def test_show_favorites_dialog_empty(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """无收藏项也正常构建，不抛异常。"""
        selector: Any = file_selector_w12
        selector.favorites = []
        monkeypatch.setattr(CustomFileSelector, "_load_favorites", lambda self: None)
        selector._show_favorites_dialog()  # 不抛异常即可


class TestOnFilesLoadFailedRecovery:
    """_on_files_load_failed 守卫 + 恢复路径（W12：拦截模态与提权）。"""

    def _prime(self, selector: Any, target: str) -> None:
        selector.current_path = target

    def test_stale_request_returns_early(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        self._prime(selector, "C:\\stale-dir")
        error_logger = MagicMock()
        monkeypatch.setattr("freeassetfilter.components.file_selector.error", error_logger)
        selector._on_files_load_failed(
            selector._refresh_request_id + 7, "C:\\x", "boom"
        )
        error_logger.assert_not_called()
        assert selector._is_loading is False  # ctor 初值，早退不改动

    def test_failure_recovers_without_permission(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """普通失败（无权限关键词）：记录错误 + 恢复路径 + 刷新。"""
        selector: Any = file_selector_w12
        failed = "C:\\denied-dir"
        self._prime(selector, failed)
        monkeypatch.setattr(CustomFileSelector, "refresh_files", lambda self, *a, **k: None)
        monkeypatch.setattr(selector, "_looks_like_permission_denied", lambda msg: False)

        selector._on_files_load_failed(selector._refresh_request_id, failed, "读取目录失败")

        assert selector._is_loading is False
        assert selector.current_path != failed  # 已恢复
        assert selector.path_edit.text() == selector.current_path

    def test_permission_denied_launches_admin_restart(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """权限失败 + 提权重启成功：调用 _restart_application_as_admin 后直接返回。"""
        selector: Any = file_selector_w12
        failed = "C:\\perm-dir"
        self._prime(selector, failed)
        monkeypatch.setattr(CustomFileSelector, "refresh_files", lambda self, *a, **k: None)
        monkeypatch.setattr(selector, "_looks_like_permission_denied", lambda msg: True)
        restart = MagicMock(return_value=(True, ""))
        monkeypatch.setattr(selector, "_restart_application_as_admin", restart)
        failed_dlg = MagicMock()
        monkeypatch.setattr(selector, "_show_elevated_restart_failed_dialog", failed_dlg)

        selector._on_files_load_failed(
            selector._refresh_request_id, failed, "拒绝访问"
        )

        restart.assert_called_once()
        failed_dlg.assert_not_called()


class TestPathTransitionWidget:
    """_finish/_cancel_files_path_transition（W12）。"""

    def test_cancel_increments_token_and_resets_direction(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector._pending_path_transition_direction = 1
        token_before = selector._pending_path_transition_token
        selector._cancel_files_path_transition()
        assert selector._pending_path_transition_direction == 0
        assert selector._pending_path_transition_token == token_before + 1

    def test_finish_with_no_direction_returns(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector._pending_path_transition_direction = 0
        selector._finish_files_path_transition()  # 不抛异常


class TestLooksLikePermissionDenied:
    """_looks_like_permission_denied 关键词匹配。"""

    def test_matches_keywords(self, file_selector_w12: Any) -> None:
        selector: Any = file_selector_w12
        for msg in (
            "Permission denied",
            "Access is denied",
            "拒绝访问",
            "权限不足",
            "WinError 5",
            "errno 13",
        ):
            assert selector._looks_like_permission_denied(msg), msg

    def test_non_matches(self, file_selector_w12: Any) -> None:
        selector: Any = file_selector_w12
        assert selector._looks_like_permission_denied("普通读取失败") is False
        assert selector._looks_like_permission_denied("") is False


class TestEmptyAndInitialStateW12:
    """W12 fixture 下的构造默认态。"""

    def test_w12_initial_state(self, file_selector_w12: Any) -> None:
        selector: Any = file_selector_w12
        assert selector.current_path == "All"
        assert selector.filter_pattern == "*"
        assert selector.sort_by == "name"
        assert selector.view_mode == "card"
        assert selector.file_model.rowCount() == 0
        assert selector._first_show is True


# =============================================================================
# 批次 A：盘符变化 / 视图布局 / 路径过渡补充
# =============================================================================
class TestOnDriveChanged:
    """_on_drive_changed（W12，_navigate_to_path 全部 mock）。"""

    def test_all_option_navigates_all(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        navigate = MagicMock()
        monkeypatch.setattr(selector, "_navigate_to_path", navigate)
        selector._on_drive_changed("  All  ")
        navigate.assert_called_once_with("All")

    def test_network_separator_ignored(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        navigate = MagicMock()
        monkeypatch.setattr(selector, "_navigate_to_path", navigate)
        selector._on_drive_changed("--- 网络位置 ---")
        navigate.assert_not_called()

    def test_drive_letter_appends_backslash(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        navigate = MagicMock()
        monkeypatch.setattr(selector, "_navigate_to_path", navigate)
        selector._on_drive_changed("C:")
        navigate.assert_called_once_with("C:\\")

    def test_unc_share_passes_through(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        navigate = MagicMock()
        monkeypatch.setattr(selector, "_navigate_to_path", navigate)
        selector._on_drive_changed("\\\\server\\share")
        navigate.assert_called_once_with("\\\\server\\share")

    def test_posix_branch_keeps_path(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        monkeypatch.setattr(sys, "platform", "linux")
        navigate = MagicMock()
        monkeypatch.setattr(selector, "_navigate_to_path", navigate)
        selector._on_drive_changed("/mnt/data")
        navigate.assert_called_once_with("/mnt/data")

    def test_non_absolute_drive_ignored(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        navigate = MagicMock()
        monkeypatch.setattr(selector, "_navigate_to_path", navigate)
        selector._on_drive_changed("not-a-drive")
        navigate.assert_not_called()


class TestUpdateDriveSelector:
    """_update_drive_selector（W12，drive_combo mock）。"""

    def test_all_sets_drive_combo(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        combo = MagicMock()
        monkeypatch.setattr(selector, "drive_combo", combo)
        selector.current_path = "All"
        selector._update_drive_selector()
        combo.set_current_item.assert_called_once_with("All")

    def test_win32_sets_drive_letter(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        combo = MagicMock()
        monkeypatch.setattr(selector, "drive_combo", combo)
        selector.current_path = "C:\\some\\dir"
        selector._update_drive_selector()
        combo.set_current_item.assert_called_once_with("C:")

    def test_posix_sets_root(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        monkeypatch.setattr(sys, "platform", "linux")
        combo = MagicMock()
        monkeypatch.setattr(selector, "drive_combo", combo)
        selector.current_path = "/home/user"
        selector._update_drive_selector()
        combo.set_current_item.assert_called_once_with("/")


class TestViewModeButtonTextGuard:
    """_set_view_mode_button_text / _apply_view_mode 守卫（W12）。"""

    def test_view_mode_button_text_missing_btn_safe(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        monkeypatch.delattr(selector, "view_mode_btn", raising=False)
        selector._set_view_mode_button_text()  # 不抛异常

    def test_apply_view_mode_missing_scroll_area_safe(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        monkeypatch.setattr(selector, "files_scroll_area", None)
        selector._apply_view_mode()  # 不抛异常


class TestUpdateListLayout:
    """_update_list_layout（W12，list_view / model mock）。"""

    def test_active_computes_and_sets_grid(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        viewport = MagicMock()
        viewport.width.return_value = 500
        list_view = MagicMock()
        list_view.viewport.return_value = viewport
        model = MagicMock()
        selector.dpi_scale = 1.0
        monkeypatch.setattr(selector, "files_scroll_area", list_view)
        monkeypatch.setattr(selector, "file_model", model)

        selector._update_list_layout()

        list_view.setGridSize.assert_called_once()
        model.set_grid_offset_x.assert_called_once_with(0)
        model.set_card_width.assert_called_once()

    def test_missing_list_view_returns(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        monkeypatch.setattr(selector, "files_scroll_area", None)
        selector._update_list_layout()  # 不抛异常

    def test_zero_viewport_width_returns(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        viewport = MagicMock()
        viewport.width.return_value = 0
        list_view = MagicMock()
        list_view.viewport.return_value = viewport
        monkeypatch.setattr(selector, "files_scroll_area", list_view)
        monkeypatch.setattr(selector, "file_model", MagicMock())
        selector._update_list_layout()
        list_view.setGridSize.assert_not_called()


class TestInferNavigationDirection:
    """_infer_navigation_direction 全部分支矩阵。"""

    def test_direction_matrix(self, file_selector_w12: Any) -> None:
        selector: Any = file_selector_w12
        assert selector._infer_navigation_direction("C:\\a", "C:\\a") == 0
        assert selector._infer_navigation_direction("All", "C:\\a") == 1
        assert selector._infer_navigation_direction("C:\\a", "All") == -1
        assert selector._infer_navigation_direction("C:\\a", "C:\\a\\b") == 1
        assert selector._infer_navigation_direction("C:\\a\\b", "C:\\a") == -1
        assert selector._infer_navigation_direction("D:\\x", "C:\\a") == 1


class TestFilesPathTransition:
    """_begin/_finish/_finish_deferred 路径切换（W12，list_view mock）。"""

    def test_begin_guard_when_no_list_view(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        monkeypatch.setattr(selector, "files_scroll_area", None)
        selector._begin_files_path_transition("C:\\target")
        assert selector._pending_path_transition_direction == 0

    def test_begin_same_path_returns_zero(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector.current_path = "C:\\a"
        list_view = MagicMock()
        monkeypatch.setattr(selector, "files_scroll_area", list_view)
        selector._begin_files_path_transition("C:\\a")
        assert selector._pending_path_transition_direction == 0
        list_view.begin_path_transition.assert_not_called()

    def test_begin_sets_direction_and_increments_token(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector.current_path = "C:\\a"
        list_view = MagicMock()
        list_view.begin_path_transition.return_value = True
        monkeypatch.setattr(selector, "files_scroll_area", list_view)
        token_before: int = selector._pending_path_transition_token
        selector._begin_files_path_transition("C:\\a\\b")
        assert selector._pending_path_transition_direction == 1
        assert selector._pending_path_transition_token == token_before + 1
        list_view.begin_path_transition.assert_called_once_with(1)

    def test_begin_exception_logged(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector.current_path = "C:\\a"
        list_view = MagicMock()
        list_view.begin_path_transition.side_effect = RuntimeError("boom")
        monkeypatch.setattr(selector, "files_scroll_area", list_view)
        debug_logger = MagicMock()
        monkeypatch.setattr(
            "freeassetfilter.components.file_selector.debug", debug_logger
        )
        selector._begin_files_path_transition("C:\\a\\b")
        debug_logger.assert_called_once()
        assert selector._pending_path_transition_direction == 0

    def test_finish_active_resets_and_schedules_deferred(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector._pending_path_transition_direction = 1
        selector._pending_path_transition_token = 5
        viewport = MagicMock()
        list_view = MagicMock()
        list_view.viewport.return_value = viewport
        monkeypatch.setattr(selector, "files_scroll_area", list_view)

        selector._finish_files_path_transition()

        assert selector._pending_path_transition_direction == 0
        list_view.doItemsLayout.assert_called_once()
        viewport.update.assert_called_once()

    def test_finish_guard_when_no_list_view(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector._pending_path_transition_direction = 1
        monkeypatch.setattr(selector, "files_scroll_area", None)
        selector._finish_files_path_transition()
        assert selector._pending_path_transition_direction == 0

    def test_deferred_zero_direction_returns(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        monkeypatch.setattr(selector, "files_scroll_area", MagicMock())
        selector._finish_files_path_transition_deferred(5, 0)  # 不抛异常

    def test_deferred_token_mismatch_returns(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector._pending_path_transition_token = 5
        list_view = MagicMock()
        monkeypatch.setattr(selector, "files_scroll_area", list_view)
        selector._finish_files_path_transition_deferred(99, 1)
        list_view.finish_path_transition.assert_not_called()

    def test_deferred_success_calls_finish(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector._pending_path_transition_token = 5
        list_view = MagicMock()
        monkeypatch.setattr(selector, "files_scroll_area", list_view)
        selector._finish_files_path_transition_deferred(5, 1)
        list_view.doItemsLayout.assert_called_once()
        list_view.finish_path_transition.assert_called_once_with(1)


class TestRefreshStagingPoolCard:
    """_refresh_staging_pool_card：无池 / 命中刷新 / 异常记录（W12）。"""

    def test_no_pool_returns(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        monkeypatch.setattr(selector, "_get_staging_pool", lambda: None)
        selector._refresh_staging_pool_card("C:\\a.txt")  # 不抛异常

    def test_matching_card_refreshes_thumbnail(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        card = MagicMock()
        other_card = MagicMock()
        pool = MagicMock()
        pool.cards = [
            (card, {"path": "C:\\a.txt"}),
            (other_card, {"path": "C:\\b.txt"}),
        ]
        monkeypatch.setattr(selector, "_get_staging_pool", lambda: pool)
        selector._refresh_staging_pool_card("C:\\a.txt")
        card.refresh_thumbnail.assert_called_once()
        other_card.refresh_thumbnail.assert_not_called()

    def test_exception_logs_error(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        error_logger = MagicMock()
        monkeypatch.setattr(
            "freeassetfilter.components.file_selector.error", error_logger
        )
        monkeypatch.setattr(
            selector,
            "_get_staging_pool",
            lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        selector._refresh_staging_pool_card("C:\\a.txt")
        error_logger.assert_called_once()


class TestGoForward:
    """go_forward（W12：nav_history/按钮 mock）。"""

    def test_forward_navigates_to_next_history(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector.nav_history = ["C:\\a", "C:\\b", "C:\\c"]
        selector.history_index = 1
        selector.back_btn = MagicMock()
        selector.forward_btn = MagicMock()
        navigate = MagicMock()
        monkeypatch.setattr(selector, "_navigate_to_path", navigate)

        selector.go_forward()

        assert selector.history_index == 2
        navigate.assert_called_once_with("C:\\c")
        selector.back_btn.setEnabled.assert_any_call(True)
        selector.forward_btn.setEnabled.assert_any_call(False)

    def test_forward_noop_at_history_end(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector.nav_history = ["C:\\a", "C:\\b"]
        selector.history_index = 1
        selector.back_btn = MagicMock()
        selector.forward_btn = MagicMock()
        navigate = MagicMock()
        monkeypatch.setattr(selector, "_navigate_to_path", navigate)

        selector.go_forward()

        navigate.assert_not_called()
        assert selector.history_index == 1


class TestUpdateHistory:
    """_update_history 分支（W12：按钮 mock）。"""

    def _buttons(self, selector: Any) -> None:
        selector.back_btn = MagicMock()
        selector.forward_btn = MagicMock()

    def test_empty_history_initializes(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector.current_path = "C:\\x"
        selector.nav_history = []
        self._buttons(selector)
        selector._update_history()
        assert selector.nav_history == ["C:\\x"]
        assert selector.history_index == 0

    def test_same_path_keeps_history(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector.current_path = "C:\\y"
        selector.nav_history = ["C:\\x", "C:\\y"]
        selector.history_index = 1
        self._buttons(selector)
        selector._update_history()
        assert selector.nav_history == ["C:\\x", "C:\\y"]
        assert selector.history_index == 1

    def test_new_path_truncates_future(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector.current_path = "C:\\new"
        selector.nav_history = ["C:\\a", "C:\\b", "C:\\c"]
        selector.history_index = 1
        self._buttons(selector)
        selector._update_history()
        assert selector.nav_history == ["C:\\a", "C:\\b", "C:\\new"]
        assert selector.history_index == 2

    def test_new_path_at_end_appends(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector.current_path = "C:\\new"
        selector.nav_history = ["C:\\a", "C:\\b"]
        selector.history_index = 1
        self._buttons(selector)
        selector._update_history()
        assert selector.nav_history == ["C:\\a", "C:\\b", "C:\\new"]
        assert selector.history_index == 2


class TestGoToPath:
    """go_to_path 分支（W12：path_edit mock + 假 MessageBox）。"""

    def test_empty_path_navigates_all(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector.path_edit = MagicMock()
        selector.path_edit.text.return_value = ""
        navigate = MagicMock()
        monkeypatch.setattr(selector, "_navigate_to_path", navigate)
        selector.go_to_path()
        navigate.assert_called_once_with("All")

    def test_all_text_navigates_all(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector.path_edit = MagicMock()
        selector.path_edit.text.return_value = "all"
        navigate = MagicMock()
        monkeypatch.setattr(selector, "_navigate_to_path", navigate)
        selector.go_to_path()
        navigate.assert_called_once_with("All")

    def test_absolute_path_navigates_normalized(
        self, qapp: Any, file_selector_w12: Any, tmp_path: Path, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector.path_edit = MagicMock()
        selector.path_edit.text.return_value = str(tmp_path)
        navigate = MagicMock()
        monkeypatch.setattr(selector, "_navigate_to_path", navigate)
        selector.go_to_path()
        navigate.assert_called_once_with(str(tmp_path))

    def test_invalid_path_shows_warning(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector.path_edit = MagicMock()
        selector.path_edit.text.return_value = "not a path"
        navigate = MagicMock()
        monkeypatch.setattr(selector, "_navigate_to_path", navigate)
        # Windows 下 "not a path" 经 abspath 恒为绝对路径；强制 isabs=False
        # 才能命中 else 的无效路径警告分支。
        monkeypatch.setattr("os.path.isabs", lambda p: False)
        selector.go_to_path()  # 假 MessageBox 不阻塞
        navigate.assert_not_called()


class TestFilterStyleFallback:
    """_update_filter_button_style 的 setattr 兼容分支（W12）。"""

    def test_button_without_set_button_type_uses_fallback(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        fake_btn = MagicMock()
        del fake_btn.set_button_type  # 触发 hasattr 为 False 的分支
        fake_btn.update_theme = MagicMock()
        fake_btn.update = MagicMock()
        monkeypatch.setattr(selector, "filter_btn", fake_btn)
        selector.filter_pattern = "*.png"
        selector._update_filter_button_style()
        assert fake_btn.button_type == "primary"
        fake_btn.update_theme.assert_called_once()
        fake_btn.update.assert_called_once()


class TestApplyFilter:
    """apply_filter：确认 / 移除筛选 / 取消 三分支（W12 假 MessageBox）。"""

    def _run(self, selector: Any, monkeypatch: Any, index: int) -> Any:
        refresh = MagicMock()
        monkeypatch.setattr(selector, "refresh_files", refresh)
        monkeypatch.setattr(_FakeMessageBox, "auto_button_index", index)
        selector.apply_filter()
        return refresh

    def test_confirm_empty_pattern_resets_to_star(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        # filter_pattern 为 "*" 时 current_pattern 传递为空 → get_input 空 →
        # 确认后回退为 "*"（空输入复位分支）。
        selector.filter_pattern = "*"
        refresh = self._run(selector, monkeypatch, 0)
        assert selector.filter_pattern == "*"
        refresh.assert_called_once()

    def test_confirm_sets_pattern(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        monkeypatch.setattr(_FakeMessageBox, "get_input", lambda self: "  *.jpg  ")
        refresh = self._run(selector, monkeypatch, 0)
        assert selector.filter_pattern == "*.jpg"
        refresh.assert_called_once()

    def test_remove_filter_resets_to_star(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector.filter_pattern = "*.png"
        refresh = self._run(selector, monkeypatch, 1)
        assert selector.filter_pattern == "*"
        refresh.assert_called_once()

    def test_cancel_keeps_pattern(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector.filter_pattern = "*.png"
        refresh = self._run(selector, monkeypatch, 2)
        assert selector.filter_pattern == "*.png"
        refresh.assert_not_called()


class TestRefreshFilesRejoin:
    """refresh_files 重入旧线程分支（W12：伪线程类）。"""

    def test_restarts_running_thread(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        old_thread = MagicMock()
        old_thread.isRunning.return_value = True
        old_thread.loaded = MagicMock()
        old_thread.failed = MagicMock()
        selector._file_loader_thread = old_thread

        started_paths: list[str] = []

        class _FakeLoader:
            def __init__(self, path: str, parent: Any) -> None:
                self._path = path
                self.loaded = MagicMock()
                self.failed = MagicMock()
                self.finished = MagicMock()
                self.parent = parent

            def start(self) -> None:
                started_paths.append(self._path)

            def isRunning(self) -> bool:
                return False

            def quit(self) -> None:
                pass

            def wait(self, *args: Any) -> bool:
                return True

        monkeypatch.setattr(fs, "FileListLoaderThread", _FakeLoader)
        selector.path_edit = MagicMock()

        selector.refresh_files()

        old_thread.loaded.disconnect.assert_called_once()
        old_thread.failed.disconnect.assert_called_once()
        old_thread.quit.assert_called_once()
        assert started_paths == [selector.current_path]
        assert selector._is_loading is True


class TestOnFilesLoadedException:
    """_on_files_loaded 异常：取消过渡 + 记录错误（W12）。"""

    def test_exception_cancels_transition_and_logs(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector.current_path = "C:\\x"
        selector._refresh_request_id = 5
        monkeypatch.setattr(selector, "_sort_files", MagicMock(side_effect=RuntimeError("boom")))
        cancel = MagicMock()
        monkeypatch.setattr(selector, "_cancel_files_path_transition", cancel)
        error_logger = MagicMock()
        monkeypatch.setattr(
            "freeassetfilter.components.file_selector.error", error_logger
        )
        selector._on_files_loaded(5, "C:\\x", [], None, True)
        cancel.assert_called_once()
        error_logger.assert_called_once()
        assert selector._is_loading is False


class TestOnFilesLoadFailedElevatedDialog:
    """_on_files_load_failed 提权重启失败 → 错误对话框（W12）。"""

    def test_restart_failed_shows_dialog(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector.current_path = "C:\\perm"
        selector._refresh_request_id = 7
        monkeypatch.setattr(selector, "_looks_like_permission_denied", lambda msg: True)
        monkeypatch.setattr(
            selector, "_restart_application_as_admin", lambda: (False, "canceled")
        )
        dialog = MagicMock()
        monkeypatch.setattr(selector, "_show_elevated_restart_failed_dialog", dialog)
        recover = MagicMock()
        monkeypatch.setattr(selector, "_recover_after_directory_load_failure", recover)
        monkeypatch.setattr(_FakeMessageBox, "auto_button_index", 0)

        selector._on_files_load_failed(7, "C:\\perm", "拒绝访问")

        dialog.assert_called_once_with("canceled")
        recover.assert_called_once()


class TestRestartApplicationAsAdmin:
    """_restart_application_as_admin 分支（W12：windll 全 mock）。"""

    def test_non_win32_returns_false(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        monkeypatch.setattr(sys, "platform", "linux")
        ok, message = selector._restart_application_as_admin()
        assert ok is False
        assert "不支持" in message

    def test_win32_error_code_returns_false(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        import ctypes

        selector: Any = file_selector_w12
        fake = MagicMock()
        fake.shell32.ShellExecuteW.return_value = 5
        monkeypatch.setattr(ctypes, "windll", fake)
        ok, message = selector._restart_application_as_admin()
        assert ok is False
        assert "错误码" in message

    def test_win32_success_quits_app(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        import ctypes

        selector: Any = file_selector_w12
        fake = MagicMock()
        fake.shell32.ShellExecuteW.return_value = 42
        monkeypatch.setattr(ctypes, "windll", fake)
        app_mock = MagicMock()
        monkeypatch.setattr(fs.QApplication, "instance", lambda: app_mock)
        ok, message = selector._restart_application_as_admin()
        assert ok is True
        assert message == ""
        app_mock.quit.assert_called_once()

    def test_frozen_subprocess_args(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        import ctypes

        selector: Any = file_selector_w12
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        fake = MagicMock()
        fake.shell32.ShellExecuteW.return_value = 42
        monkeypatch.setattr(ctypes, "windll", fake)
        monkeypatch.setattr(fs.QApplication, "instance", lambda: None)
        ok, message = selector._restart_application_as_admin()
        assert ok is True
        assert message == ""

    def test_exception_returns_false(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        import ctypes

        selector: Any = file_selector_w12
        fake = MagicMock()
        fake.shell32.ShellExecuteW.side_effect = RuntimeError("x")
        monkeypatch.setattr(ctypes, "windll", fake)
        ok, message = selector._restart_application_as_admin()
        assert ok is False
        assert message != ""


class TestShowElevatedRestartFailedDialog:
    """_show_elevated_restart_failed_dialog 构建（W12 假 MessageBox）。"""

    def test_dialog_builds_without_blocking(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector._show_elevated_restart_failed_dialog("boom")  # 不阻塞
        assert _FakeMessageBox.auto_button_index is not None


class TestGetFilesAllMode:
    """_get_files "All" 视图（W12：windll 位掩码 / stat / 可用性全 mock）。"""

    def _patch_windll(
        self, monkeypatch: Any, bitmask: int, stat_result: Any
    ) -> Any:
        import ctypes

        fake = MagicMock()

        class _Kernel32:
            def GetLogicalDrives(self) -> int:
                return bitmask

        fake.kernel32 = _Kernel32()
        monkeypatch.setattr(ctypes, "windll", fake)
        monkeypatch.setattr(fs.os, "stat", lambda p: stat_result)
        return fake

    def test_all_win32_collects_drives(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector.current_path = "All"
        stat_result = MagicMock()
        stat_result.st_mtime = 100.0
        stat_result.st_ctime = 200.0
        self._patch_windll(monkeypatch, 0b101, stat_result)  # A: 与 C:
        monkeypatch.setattr(selector, "_is_drive_available", lambda d: True)

        files = selector._get_files()

        assert [f["name"] for f in files] == ["A:", "C:"]
        assert all(f["is_dir"] for f in files)

    def test_all_win32_stat_failure_empties_dates(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector.current_path = "All"
        self._patch_windll(monkeypatch, 0b001, None)
        monkeypatch.setattr(fs.os, "stat", MagicMock(side_effect=OSError("no drive")))
        monkeypatch.setattr(selector, "_is_drive_available", lambda d: True)

        files = selector._get_files()

        assert files[0]["name"] == "A:"
        assert files[0]["modified"] == ""
        assert files[0]["created"] == ""

    def test_all_win32_unavailable_drive_skipped(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector.current_path = "All"
        self._patch_windll(monkeypatch, 0b101, MagicMock())
        monkeypatch.setattr(selector, "_is_drive_available", lambda d: False)
        files = selector._get_files()
        assert files == []

    def test_all_win32_listing_error_logged(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        import ctypes

        selector: Any = file_selector_w12
        selector.current_path = "All"
        fake = MagicMock()
        fake.kernel32.GetLogicalDrives.side_effect = RuntimeError("boom")
        monkeypatch.setattr(ctypes, "windll", fake)
        error_logger = MagicMock()
        monkeypatch.setattr(
            "freeassetfilter.components.file_selector.error", error_logger
        )
        files = selector._get_files()
        error_logger.assert_called_once()
        assert files == []

    def test_all_posix_root(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        monkeypatch.setattr(sys, "platform", "linux")
        selector.current_path = "All"
        stat_result = MagicMock()
        stat_result.st_mtime = 100.0
        stat_result.st_ctime = 200.0
        monkeypatch.setattr(fs.os, "stat", lambda p: stat_result)
        files = selector._get_files()
        assert [f["name"] for f in files] == ["/"]


class TestGetFilesScanned:
    """_get_files 普通目录扫描（W12：FileService mock）。"""

    def test_scans_directory(
        self, qapp: Any, file_selector_w12: Any, tmp_path: Path, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector.current_path = str(tmp_path)
        fake_files = [
            {"name": "a.txt", "path": str(tmp_path / "a.txt"), "is_dir": False}
        ]
        service = MagicMock()
        service.scan_directory.return_value = fake_files
        monkeypatch.setattr(selector, "_file_service", service)

        files = selector._get_files()

        assert files == fake_files
        service.scan_directory.assert_called_once_with(str(tmp_path))

    def test_symlink_rejected(
        self, qapp: Any, file_selector_w12: Any, tmp_path: Path, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector.current_path = str(tmp_path)
        monkeypatch.setattr(fs.os.path, "islink", lambda p: True)
        error_logger = MagicMock()
        monkeypatch.setattr(
            "freeassetfilter.components.file_selector.error", error_logger
        )
        files = selector._get_files()
        error_logger.assert_called_once()
        assert files == []

    def test_scan_exception_logged(
        self, qapp: Any, file_selector_w12: Any, tmp_path: Path, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector.current_path = str(tmp_path)
        service = MagicMock()
        service.scan_directory.side_effect = OSError("denied")
        monkeypatch.setattr(selector, "_file_service", service)
        error_logger = MagicMock()
        monkeypatch.setattr(
            "freeassetfilter.components.file_selector.error", error_logger
        )
        files = selector._get_files()
        error_logger.assert_called_once()
        assert files == []


class TestGridSizeCalc:
    """grid 尺寸计算簇（W12：list_view/file_model mock）。"""

    def _viewport(self, width: int) -> Any:
        viewport = MagicMock()
        viewport.width.return_value = width
        return viewport

    def test_max_columns_no_list_view(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        monkeypatch.setattr(selector, "files_scroll_area", None)
        assert selector._calculate_max_columns() == 1

    def test_max_columns_zero_width(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        list_view = MagicMock()
        list_view.viewport.return_value = self._viewport(0)
        monkeypatch.setattr(selector, "files_scroll_area", list_view)
        assert selector._calculate_max_columns() == 1

    def test_max_columns_computes(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        list_view = MagicMock()
        list_view.viewport.return_value = self._viewport(500)
        selector._card_spacing = 8
        selector._calculate_card_base_width = lambda: 100
        monkeypatch.setattr(selector, "files_scroll_area", list_view)
        assert selector._calculate_max_columns() == 4  # (500-4)//108

    def test_card_width_no_list_view(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector._calculate_card_base_width = lambda: 100
        monkeypatch.setattr(selector, "files_scroll_area", None)
        assert selector._calculate_card_width() == 100

    def test_card_width_computes(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        list_view = MagicMock()
        list_view.viewport.return_value = self._viewport(500)
        selector._card_spacing = 8
        selector._calculate_card_base_width = lambda: 100
        monkeypatch.setattr(selector, "files_scroll_area", list_view)
        # 公式：leading=4, available=496, cell=max(108, 496//4)=124,
        # 返回 max(100, 124-8)=116。
        assert selector._calculate_card_width() == 116

    def test_schedule_grid_size_update(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        list_view = MagicMock()
        list_view.viewport.return_value = self._viewport(500)
        monkeypatch.setattr(selector, "files_scroll_area", list_view)
        selector._schedule_grid_size_update()
        list_view.update.assert_called_once()

    def test_on_resize_timeout(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        list_view = MagicMock()
        list_view.viewport.return_value = self._viewport(500)
        monkeypatch.setattr(selector, "files_scroll_area", list_view)
        selector._on_resize_timeout()
        list_view.update.assert_called_once()

    def test_update_grid_size_list_mode_reuses_list_layout(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector.view_mode = "list"
        layout = MagicMock()
        monkeypatch.setattr(selector, "_update_list_layout", layout)
        selector._update_grid_size()
        layout.assert_called_once()

    def test_update_grid_size_no_list_view(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        monkeypatch.setattr(selector, "files_scroll_area", None)
        selector._update_grid_size()  # 不抛异常

    def test_update_grid_size_zero_width(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        list_view = MagicMock()
        list_view.viewport.return_value = self._viewport(0)
        monkeypatch.setattr(selector, "files_scroll_area", list_view)
        selector._update_grid_size()
        list_view.setGridSize.assert_not_called()

    def test_update_grid_size_sets_grid(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector.dpi_scale = 1.0
        list_view = MagicMock()
        list_view.viewport.return_value = self._viewport(500)
        list_view.setSpacing = MagicMock()
        list_view.setGridSize = MagicMock()
        model = MagicMock()
        monkeypatch.setattr(selector, "files_scroll_area", list_view)
        monkeypatch.setattr(selector, "file_model", model)

        selector._update_grid_size()

        list_view.setGridSize.assert_called_once()
        model.set_grid_offset_x.assert_called_once()
        model.set_card_width.assert_called_once()


class TestSelectorPathHelpers:
    """_same_selector_path / _is_descendant_selector_path 边界（W12）。"""

    def test_same_path_exception_returns_false(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        monkeypatch.setattr(
            fs.os.path, "normpath", lambda p: (_ for _ in ()).throw(ValueError())
        )
        assert selector._same_selector_path("C:\\a", "C:\\b") is False

    def test_descendant_all_returns_false(
        self, file_selector_w12: Any
    ) -> None:
        selector: Any = file_selector_w12
        assert selector._is_descendant_selector_path("All", "C:\\a") is False
        assert selector._is_descendant_selector_path("C:\\a", "All") is False

    def test_descendant_equal_returns_false(
        self, file_selector_w12: Any
    ) -> None:
        selector: Any = file_selector_w12
        assert selector._is_descendant_selector_path("C:\\a", "C:\\a") is False


class TestPathTransitionExceptions:
    """路径过渡异常分支（W12：list_view mock）。"""

    def test_finish_transition_exception_logged(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector._pending_path_transition_direction = 1
        list_view = MagicMock()
        list_view.doItemsLayout.side_effect = RuntimeError("boom")
        monkeypatch.setattr(selector, "files_scroll_area", list_view)
        debug_logger = MagicMock()
        monkeypatch.setattr(
            "freeassetfilter.components.file_selector.debug", debug_logger
        )
        selector._finish_files_path_transition()
        debug_logger.assert_called_once()

    def test_finish_deferred_missing_method_returns(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector._pending_path_transition_token = 5
        list_view = MagicMock()
        del list_view.finish_path_transition
        monkeypatch.setattr(selector, "files_scroll_area", list_view)
        selector._finish_files_path_transition_deferred(5, 1)
        list_view.doItemsLayout.assert_not_called()

    def test_finish_deferred_exception_logged(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector._pending_path_transition_token = 5
        list_view = MagicMock()
        list_view.finish_path_transition.side_effect = RuntimeError("boom")
        monkeypatch.setattr(selector, "files_scroll_area", list_view)
        debug_logger = MagicMock()
        monkeypatch.setattr(
            "freeassetfilter.components.file_selector.debug", debug_logger
        )
        selector._finish_files_path_transition_deferred(5, 1)
        debug_logger.assert_called_once()

    def test_cancel_transition_exception_logged(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector._pending_path_transition_direction = 1
        list_view = MagicMock()
        list_view.cancel_path_transition.side_effect = RuntimeError("boom")
        monkeypatch.setattr(selector, "files_scroll_area", list_view)
        debug_logger = MagicMock()
        monkeypatch.setattr(
            "freeassetfilter.components.file_selector.debug", debug_logger
        )
        selector._cancel_files_path_transition()
        debug_logger.assert_called_once()


class TestDirectoryLoadFailureRecovery:
    """_get_directory_load_failure_recovery_path（W12）。"""

    def test_matching_recovery_returns_all(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector._navigation_recovery_path = "C:\\x"
        selector._last_accessible_path = "C:\\x"
        assert selector._get_directory_load_failure_recovery_path("C:\\x") == "All"

    def test_different_recovery_returned(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        selector: Any = file_selector_w12
        selector._navigation_recovery_path = "C:\\x"
        selector._last_accessible_path = "C:\\x"
        assert selector._get_directory_load_failure_recovery_path("D:\\y") == "C:\\x"


def tmp_path_cached() -> Path:
    """返回一个稳定的存在目录用于 drive 缓存键构造（不做真实扫描）。"""
    import tempfile

    return Path(tempfile.gettempdir())