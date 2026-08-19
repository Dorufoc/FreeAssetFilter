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
from types import SimpleNamespace
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
    QDialog,
    QLabel,
    QListView,
    QListWidgetItem,
    QWidget,
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


# =============================================================================
# W15 批次1：线程 run 边界 / ctor 默认分支 / 路径与视图模式持久化
# =============================================================================
def _build_isolated_selector(
    monkeypatch: Any,
    settings_manager: Any,
    tmp_path: Path,
    **ctor_kwargs: Any,
) -> Any:
    """应用 file_selector 隔离 + W12 假件后按自定义 ctor kwargs 构造选择器。

    供 W15 构造分支测试（dpi_scale/global_font/settings_manager/
    initial_navigate_path/restore_last_path）复用，不经过标准 fixture。

    Args:
        monkeypatch: pytest monkeypatch fixture。
        settings_manager: 临时设置文件绑定的 SettingsManager（可为 None）。
        tmp_path: pytest 内置临时目录。
        **ctor_kwargs: 透传给 CustomFileSelector.__init__ 的额外实参。

    Returns:
        Any: 已隔离的 CustomFileSelector 实例（调用方负责 safe_teardown）。
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

    selector: Any = CustomFileSelector(
        settings_manager=settings_manager, **ctor_kwargs
    )
    selector.save_path_file = str(tmp_path / "last_path.json")
    selector.save_view_mode_file = str(tmp_path / "view_mode.json")
    selector.favorites_file = str(tmp_path / "favorites.json")
    return selector


class TestThumbnailGeneratorCancelCallback:
    """ThumbnailGeneratorThread：cancel_check 回调被实际调用（L133-134）。"""

    def test_run_cancel_callback_short_circuits(self, qapp: Any) -> None:
        """管理器调用 cancel_check() 且已取消 → 提前返回 (0,0)。"""
        from freeassetfilter.components.file_selector import ThumbnailGeneratorThread

        finished: List[Any] = []

        def fake_create_thumbnails_batch(
            _self: Any,
            files: List[Dict[str, Any]],
            progress_callback: Any = None,
            cancel_check: Any = None,
        ) -> tuple:
            if cancel_check and cancel_check():
                return (0, 0)
            return (len(files), len(files))

        class _FakeManager:
            create_thumbnails_batch = fake_create_thumbnails_batch

        files = [
            {"path": "/tmp/a.png", "name": "a.png"},
            {"path": "/tmp/b.png", "name": "b.png"},
        ]
        thread = ThumbnailGeneratorThread(
            thumbnail_manager=_FakeManager(), files_to_generate=files
        )
        thread.finished.connect(lambda s, t: finished.append((s, t)))
        try:
            thread.cancel()
            thread.run()
        finally:
            thread.deleteLater()
        # _is_cancelled=True → cancel_check()=True → (0,0)；final_total=processed_count=0
        assert finished == [(0, 0)]


class TestDriveListLoaderThreadRunEdge:
    """DriveListLoaderThread.run 边界：非 win32 与外层异常（L167/L172-173）。"""

    def test_run_non_win32_uses_slash_root(self, qapp: Any, monkeypatch: Any) -> None:
        """非 win32：local_drives 回退为 ['/']。"""
        monkeypatch.setattr(fs, "sys", SimpleNamespace(platform="linux"))
        from freeassetfilter.components.file_selector import DriveListLoaderThread

        thread = DriveListLoaderThread()
        results: List[Any] = []
        thread.loaded.connect(lambda l, n: results.append((l, n)))
        try:
            thread.run()
        finally:
            thread.deleteLater()
        assert results == [(["/"], [])]

    def test_run_outer_exception_logged(self, qapp: Any, monkeypatch: Any) -> None:
        """去重/排序抛异常（不可哈希元素）→ 外层 except 记录日志。"""
        monkeypatch.setattr(fs.sys, "platform", "win32")
        monkeypatch.setattr(
            fs.DriveService, "_list_windows_drives", lambda: [{}]
        )
        monkeypatch.setattr(
            fs.DriveService, "_list_windows_network_locations", lambda: []
        )
        error_logger = MagicMock()
        monkeypatch.setattr(fs, "error", error_logger)
        from freeassetfilter.components.file_selector import DriveListLoaderThread

        thread = DriveListLoaderThread()
        results: List[Any] = []
        thread.loaded.connect(lambda l, n: results.append((l, n)))
        try:
            thread.run()
        finally:
            thread.deleteLater()
        assert results == []
        error_logger.assert_called_once()


class TestFileListLoaderThreadAllNonWin32:
    """FileListLoaderThread.run：All + 非 win32 根目录分支（L215-224）。"""

    def test_run_all_root_non_win32(self, qapp: Any, tmp_path: Path, monkeypatch: Any) -> None:
        """非 win32 All：以 "/" 作为根条目并携带 stat 时间。"""
        monkeypatch.setattr(fs, "sys", SimpleNamespace(platform="linux"))
        from freeassetfilter.components.file_selector import FileListLoaderThread

        thread = FileListLoaderThread("All")
        loaded: List[Any] = []
        thread.loaded.connect(lambda p, f: loaded.append((p, f)))
        try:
            thread.run()
        finally:
            thread.deleteLater()
        assert loaded and loaded[0][0] == "All"
        assert loaded[0][1][0]["path"] == "/"
        assert loaded[0][1][0]["is_dir"] is True

    def test_run_all_root_stat_error(self, qapp: Any, tmp_path: Path, monkeypatch: Any) -> None:
        """非 win32 All：os.stat 抛 OSError → modified/created 置空。"""
        monkeypatch.setattr(fs, "sys", SimpleNamespace(platform="linux"))
        monkeypatch.setattr(
            fs.os, "stat", lambda p: (_ for _ in ()).throw(OSError("denied"))
        )
        from freeassetfilter.components.file_selector import FileListLoaderThread

        thread = FileListLoaderThread("All")
        loaded: List[Any] = []
        thread.loaded.connect(lambda p, f: loaded.append((p, f)))
        try:
            thread.run()
        finally:
            thread.deleteLater()
        assert loaded and loaded[0][1][0]["path"] == "/"
        assert loaded[0][1][0]["modified"] == ""
        assert loaded[0][1][0]["created"] == ""


class TestDriveAvailabilityCheckRunnableEdge:
    """_DriveAvailabilityCheckRunnable：StopIteration 与泛型异常（L308/L311-312）。"""

    def test_run_stop_iteration_available(self, qapp: Any, tmp_path: Path, monkeypatch: Any) -> None:
        """scandir 抛 StopIteration → 空目录仍判可用。"""
        from freeassetfilter.components.file_selector import (
            _DriveAvailabilityCheckRunnable,
            _DriveAvailabilitySignals,
        )

        def _stop(_p: str) -> Any:
            raise StopIteration

        monkeypatch.setattr(fs.os, "scandir", _stop)
        monkeypatch.setattr(fs.os.path, "exists", lambda p: True)
        signals = _DriveAvailabilitySignals()
        results: List[Any] = []
        signals.finished.connect(lambda p, a: results.append((p, a)))
        runnable = _DriveAvailabilityCheckRunnable(str(tmp_path), signals)
        runnable.run()
        assert results and results[0][1] is True

    def test_run_generic_exception_unavailable(self, qapp: Any, tmp_path: Path, monkeypatch: Any) -> None:
        """scandir 抛非 OSError 异常 → 判不可用。"""
        from freeassetfilter.components.file_selector import (
            _DriveAvailabilityCheckRunnable,
            _DriveAvailabilitySignals,
        )

        def _boom(_p: str) -> Any:
            raise RuntimeError("boom")

        monkeypatch.setattr(fs.os, "scandir", _boom)
        monkeypatch.setattr(fs.os.path, "exists", lambda p: True)
        signals = _DriveAvailabilitySignals()
        results: List[Any] = []
        signals.finished.connect(lambda p, a: results.append((p, a)))
        runnable = _DriveAvailabilityCheckRunnable(str(tmp_path), signals)
        runnable.run()
        assert results and results[0][1] is False


class TestSelectorCtorBranches:
    """CustomFileSelector.__init__ 默认分支（L334/L341/L349-350/L442-444/L448）。"""

    def test_explicit_dpi_scale(self, qapp: Any, settings_manager: Any, tmp_path: Path, monkeypatch: Any) -> None:
        """显式 dpi_scale 走 L334。"""
        selector: Any = _build_isolated_selector(
            monkeypatch, settings_manager, tmp_path, dpi_scale=2.5
        )
        try:
            assert selector.dpi_scale == 2.5
        finally:
            safe_teardown(selector)

    def test_explicit_global_font(self, qapp: Any, settings_manager: Any, tmp_path: Path, monkeypatch: Any) -> None:
        """显式 global_font 走 L341。"""
        font = QFont("Arial", 10)
        selector: Any = _build_isolated_selector(
            monkeypatch, settings_manager, tmp_path, global_font=font
        )
        try:
            assert selector.global_font.pointSize() == 10
        finally:
            safe_teardown(selector)

    def test_settings_manager_none_branch(self, qapp: Any, settings_manager: Any, tmp_path: Path, monkeypatch: Any) -> None:
        """settings_manager=None → 内部新建 SettingsManager（L349-350）。"""
        import freeassetfilter.core.managers.settings_manager as sm_mod

        _target: List[Any] = [settings_manager]

        class _FakeSettingsManagerFactory:
            """替换 sm_mod.SettingsManager：保留类属性（_initialized/_instance），
            实例化直接返回 _target[0]（__new__ 返回异类实例会跳过 __init__）。"""

            _initialized = True
            _instance = None

            def __new__(cls, *args: Any, **kwargs: Any) -> Any:
                return _target[0]

        monkeypatch.setattr(sm_mod, "SettingsManager", _FakeSettingsManagerFactory)
        selector: Any = _build_isolated_selector(monkeypatch, None, tmp_path)
        try:
            assert selector._settings_manager is settings_manager
        finally:
            safe_teardown(selector)

    def test_initial_navigate_path_branch(self, qapp: Any, settings_manager: Any, tmp_path: Path, monkeypatch: Any) -> None:
        """app.initial_navigate_path 合法 → ctor 采用该路径（L442-444）。"""
        monkeypatch.setattr(
            qapp, "initial_navigate_path", str(tmp_path), raising=False
        )
        selector: Any = _build_isolated_selector(
            monkeypatch, settings_manager, tmp_path
        )
        try:
            assert selector.current_path == str(tmp_path)
            assert selector._last_accessible_path == str(tmp_path)
            assert selector._navigation_recovery_path == str(tmp_path)
        finally:
            safe_teardown(selector)

    def test_restore_last_path_disabled(self, qapp: Any, settings_manager: Any, tmp_path: Path, monkeypatch: Any) -> None:
        """restore_last_path=False → else 分支保持 current_path=All（L448）。"""
        settings_manager.set_setting("file_selector.restore_last_path", False)
        selector: Any = _build_isolated_selector(
            monkeypatch, settings_manager, tmp_path
        )
        try:
            assert selector.current_path == "All"
        finally:
            safe_teardown(selector)


class TestLastPathPersistence:
    """load_last_path / _on_last_path_loaded 真实实现（L474-477/L481-494）。"""

    def test_load_last_path_real_updates_path(self, qapp: Any, file_selector_w12: Any, tmp_path: Path) -> None:
        """真实 load_last_path：读取 save_path_file 并更新 current_path。"""
        selector: Any = file_selector_w12
        (tmp_path / "last_path.json").write_text(
            json.dumps({"last_accessible_path": str(tmp_path), "last_path": str(tmp_path)}),
            encoding="utf-8",
        )
        _REAL_LOAD_LAST_PATH(selector)
        assert selector.current_path == str(tmp_path)
        assert selector._last_accessible_path == str(tmp_path)
        assert selector._navigation_recovery_path == str(tmp_path)

    def test_load_last_path_real_missing_file(self, qapp: Any, file_selector_w12: Any) -> None:
        """文件不存在 → data None → 直接返回。"""
        selector: Any = file_selector_w12
        _REAL_LOAD_LAST_PATH(selector)
        assert selector.current_path == "All"

    def test_on_last_path_loaded_none(self, qapp: Any, file_selector_w12: Any) -> None:
        """data=None 直接返回。"""
        selector: Any = file_selector_w12
        selector._on_last_path_loaded(None)
        assert selector.current_path == "All"

    def test_on_last_path_loaded_valid_paths(self, qapp: Any, file_selector_w12: Any, tmp_path: Path) -> None:
        """合法 last_accessible_path 与 last_path 均生效。"""
        selector: Any = file_selector_w12
        selector._on_last_path_loaded(
            {"last_accessible_path": str(tmp_path), "last_path": str(tmp_path)}
        )
        assert selector._last_accessible_path == str(tmp_path)
        assert selector._navigation_recovery_path == str(tmp_path)
        assert selector.current_path == str(tmp_path)

    def test_on_last_path_loaded_invalid_paths(self, qapp: Any, file_selector_w12: Any) -> None:
        """非法路径（不存在）不触发字段更新。"""
        selector: Any = file_selector_w12
        selector._on_last_path_loaded(
            {
                "last_accessible_path": str(tmp_path_cached() / "nope"),
                "last_path": str(tmp_path_cached() / "nope2"),
            }
        )
        assert selector._last_accessible_path == "All"
        assert selector.current_path == "All"

    def test_on_last_path_loaded_malformed_data(self, qapp: Any, file_selector_w12: Any, monkeypatch: Any) -> None:
        """data 非 dict（list）→ data.get 抛 AttributeError → warning。"""
        selector: Any = file_selector_w12
        warn_logger = MagicMock()
        monkeypatch.setattr(fs, "warning", warn_logger)
        selector._on_last_path_loaded([1, 2, 3])
        warn_logger.assert_called_once()


class TestViewModePersistence:
    """_load_view_mode / _on_view_mode_loaded 真实实现（L527-532/L536-543）。"""

    def test_load_view_mode_real_reads(self, qapp: Any, file_selector_w12: Any, tmp_path: Path) -> None:
        """真实 _load_view_mode：读取 view_mode 文件并二次调用早退。"""
        selector: Any = file_selector_w12
        (tmp_path / "view_mode.json").write_text(
            json.dumps({"view_mode": "list"}), encoding="utf-8"
        )
        _REAL_LOAD_VIEW_MODE(selector)
        assert selector._view_mode_loaded is True
        assert selector.view_mode == "list"
        # 二次调用走 L527-528 早退分支
        _REAL_LOAD_VIEW_MODE(selector)

    def test_load_view_mode_real_missing_file(self, qapp: Any, file_selector_w12: Any) -> None:
        """文件不存在 → data None → 视图模式保持默认。"""
        selector: Any = file_selector_w12
        _REAL_LOAD_VIEW_MODE(selector)
        assert selector._view_mode_loaded is True
        assert selector.view_mode == "card"

    def test_on_view_mode_loaded_none(self, qapp: Any, file_selector_w12: Any) -> None:
        """data=None 直接返回。"""
        selector: Any = file_selector_w12
        selector._on_view_mode_loaded(None)
        assert selector.view_mode == "card"

    def test_on_view_mode_loaded_valid_mode(self, qapp: Any, file_selector_w12: Any) -> None:
        """合法模式更新 view_mode。"""
        selector: Any = file_selector_w12
        selector._on_view_mode_loaded({"view_mode": "list"})
        assert selector.view_mode == "list"

    def test_on_view_mode_loaded_invalid_mode(self, qapp: Any, file_selector_w12: Any) -> None:
        """非法模式不更新。"""
        selector: Any = file_selector_w12
        selector._on_view_mode_loaded({"view_mode": "garbage"})
        assert selector.view_mode == "card"

    def test_on_view_mode_loaded_malformed_data(self, qapp: Any, file_selector_w12: Any, monkeypatch: Any) -> None:
        """data 非 dict → 异常分支 warning。"""
        selector: Any = file_selector_w12
        warn_logger = MagicMock()
        monkeypatch.setattr(fs, "warning", warn_logger)
        selector._on_view_mode_loaded([1, 2])
        warn_logger.assert_called_once()


class _ImmediateHeartbeat:
    """假 HeartbeatManager：request_main_thread 同步执行回调（W15）。"""

    def request_main_thread(self, fn: Callable[..., Any], priority: int = 5) -> None:
        del priority
        fn()

    def start(self) -> None:
        pass

    def stop_all(self) -> None:
        pass


class TestPathSaveMethods:
    """save_current_path / _flush_path_save / save_view_mode / _flush_view_mode_save。"""

    def _patch_heartbeat(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(fs, "HeartbeatManager", lambda: _ImmediateHeartbeat())

    def test_save_current_path_recovery_wins(self, qapp: Any, file_selector_w12: Any, monkeypatch: Any) -> None:
        """current_path != last_accessible → 优先 _navigation_recovery_path（L506）。"""
        selector: Any = file_selector_w12
        selector.current_path = "C:\\x"
        selector._last_accessible_path = "C:\\y"
        selector._navigation_recovery_path = "C:\\z"
        self._patch_heartbeat(monkeypatch)
        selector.save_current_path()
        assert json.loads(
            Path(selector.save_path_file).read_text(encoding="utf-8")
        )["last_path"] == "C:\\z"

    def test_save_current_path_falls_back_last_accessible(self, qapp: Any, file_selector_w12: Any, monkeypatch: Any) -> None:
        """无 recovery 时回退到 last_accessible_path。"""
        selector: Any = file_selector_w12
        selector.current_path = "C:\\x"
        selector._last_accessible_path = "C:\\y"
        selector._navigation_recovery_path = None
        self._patch_heartbeat(monkeypatch)
        selector.save_current_path()
        assert json.loads(
            Path(selector.save_path_file).read_text(encoding="utf-8")
        )["last_path"] == "C:\\y"

    def test_flush_path_save_none_returns(self, qapp: Any, file_selector_w12: Any) -> None:
        """_pending_path_data=None → 直接返回（L519-520）。"""
        selector: Any = file_selector_w12
        selector._pending_path_data = None
        selector._flush_path_save()

    def test_flush_path_save_writes_json(self, qapp: Any, file_selector_w12: Any) -> None:
        """_pending_path_data 非空 → 清空并写 JSON（L521-524）。"""
        selector: Any = file_selector_w12
        selector._pending_path_data = {"last_path": "C:\\z", "last_accessible_path": "C:\\y"}
        selector._flush_path_save()
        assert selector._pending_path_data is None
        written = json.loads(Path(selector.save_path_file).read_text(encoding="utf-8"))
        assert written == {"last_path": "C:\\z", "last_accessible_path": "C:\\y"}

    def test_save_view_mode_writes(self, qapp: Any, file_selector_w12: Any, monkeypatch: Any) -> None:
        """save_view_mode → _flush_view_mode_save 写 JSON（L549-550/L554-558）。"""
        selector: Any = file_selector_w12
        selector.view_mode = "list"
        self._patch_heartbeat(monkeypatch)
        selector.save_view_mode()
        assert selector._pending_view_mode is None
        written = json.loads(Path(selector.save_view_mode_file).read_text(encoding="utf-8"))
        assert written == {"view_mode": "list"}

    def test_flush_view_mode_save_none_returns(self, qapp: Any, file_selector_w12: Any) -> None:
        """_pending_view_mode=None → 直接返回（L555-556）。"""
        selector: Any = file_selector_w12
        selector._pending_view_mode = None
        selector._flush_view_mode_save()

    def test_flush_view_mode_save_writes_json(self, qapp: Any, file_selector_w12: Any) -> None:
        """_pending_view_mode 非空 → 清空并写 JSON（L557-558）。"""
        selector: Any = file_selector_w12
        selector._pending_view_mode = "card"
        selector._flush_view_mode_save()
        assert selector._pending_view_mode is None
        written = json.loads(Path(selector.save_view_mode_file).read_text(encoding="utf-8"))
        assert written == {"view_mode": "card"}


class TestShowSortMenu:
    """sort_btn 点击 → show_sort_menu 闭包（L736-740）。"""

    def test_click_shows_menu(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        """点击排序按钮：set_target_button + show_menu（L737-738）。"""
        selector: Any = file_selector_w12
        selector.sort_btn.click()
        selector.sort_menu.set_target_button.assert_called_with(selector.sort_btn)
        selector.sort_menu.show_menu.assert_called_once()


class TestGetThemeColors:
    """_get_theme_colors（L877-899）：默认值 / settings_manager 分支。"""

    def test_defaults_without_settings_manager(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """app 无 settings_manager 属性 → 全部返回默认色（L881-890）。"""
        selector: Any = file_selector_w12
        plain_app = object()  # 无 settings_manager 属性
        monkeypatch.setattr(fs.QApplication, "instance", lambda: plain_app)
        colors: Dict[str, str] = selector._get_theme_colors()
        assert colors == {
            "base_color": "#212121",
            "auxiliary_color": "#f1f3f5",
            "normal_color": "#717171",
            "secondary_color": "#FFFFFF",
            "accent_color": "#F0C54D",
            "panel_background": "#f1f3f5",
        }

    def test_reads_settings_manager(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """app 带 settings_manager → 走 get_setting 分支（L891-898）。"""
        selector: Any = file_selector_w12
        fake_app = SimpleNamespace(settings_manager=True)
        monkeypatch.setattr(fs.QApplication, "instance", lambda: fake_app)
        monkeypatch.setattr(
            selector._settings_manager,
            "get_setting",
            lambda key, default: "#AABBCC",
        )
        colors: Dict[str, str] = selector._get_theme_colors()
        assert all(v == "#AABBCC" for v in colors.values())


class TestUpdateTheme:
    """update_theme（L901-979）：主题刷新主路径 + 容错分支。"""

    def _patch_core(self, selector: Any, monkeypatch: Any) -> None:
        """打桩核心调用点（模型/委托/主题色）。"""
        colors: Dict[str, str] = {
            "base_color": "#111111",
            "auxiliary_color": "#f1f3f5",
            "normal_color": "#717171",
            "secondary_color": "#FFFFFF",
            "accent_color": "#F0C54D",
            "panel_background": "#222222",
        }
        monkeypatch.setattr(selector, "_get_theme_colors", lambda: colors)
        model = MagicMock()
        monkeypatch.setattr(selector, "file_model", model)
        card_theme = MagicMock()
        monkeypatch.setattr(selector.card_delegate, "update_theme", card_theme)
        list_theme = MagicMock()
        monkeypatch.setattr(selector.list_delegate, "update_theme", list_theme)
        return model, card_theme, list_theme, colors

    def test_main_path(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """主路径：清缓存/委托刷新/样式表全执行（L905-979）。"""
        selector: Any = file_selector_w12
        model, card_theme, list_theme, colors = self._patch_core(selector, monkeypatch)
        selector.update_theme()
        model.clear_caches.assert_called_once_with(emit_change=True)
        card_theme.assert_called_once()
        list_theme.assert_called_once()
        assert "#222222" in selector.styleSheet()
        assert "#111111" in selector.control_panel.styleSheet()
        assert "#111111" in selector.status_bar.styleSheet()

    def test_tolerates_widget_exceptions(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """各控件 update_theme 抛异常 → 被 try/except 吞掉（L919-971）。"""
        def boom(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("x")

        selector: Any = file_selector_w12
        self._patch_core(selector, monkeypatch)
        monkeypatch.setattr(selector.path_edit, "update_theme", boom)
        monkeypatch.setattr(selector.files_scroll_area, "refresh_interaction_settings", boom)
        monkeypatch.setattr(selector.refresh_btn, "update_theme", boom)
        monkeypatch.setattr(selector.sort_menu, "update_theme", boom)
        selector.hover_tooltip.update = boom
        selector.update_theme()  # 不抛异常

    def test_skips_missing_attributes(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """控件缺失 / 无 update_theme → hasattr 保护跳过（L913-977）。"""
        selector: Any = file_selector_w12
        self._patch_core(selector, monkeypatch)

        class _MinimalArea:
            """满足 eventFilter/末尾 update 的最小滚动区假件（无 viewport 会崩）。"""

            def __init__(self) -> None:
                self._vp = SimpleNamespace(width=lambda: 500)

            def viewport(self) -> Any:
                return self._vp

            def setStyleSheet(self, *args: Any, **kwargs: Any) -> None:
                pass

            def update(self) -> None:
                pass

        monkeypatch.setattr(selector, "control_panel", None)
        monkeypatch.setattr(selector, "status_bar", None)
        monkeypatch.setattr(selector, "path_edit", object())
        monkeypatch.setattr(selector, "files_scroll_area", _MinimalArea())
        monkeypatch.setattr(selector, "sort_btn", object())
        # 菜单循环：sort_menu 无 update_theme → 跳过；drive_combo 保持假件
        # （异步盘符加载回调 _apply_drive_list 需要 set_items/sizeHintForRow）。
        monkeypatch.setattr(selector, "sort_menu", object())
        selector.update_theme()  # 不抛异常


class TestGoToParent:
    """go_to_parent（L1282-1306）：win32/非 win32 根与父目录。"""

    def _navigate_mock(self, selector: Any, monkeypatch: Any) -> Any:
        nav = MagicMock()
        monkeypatch.setattr(selector, "_navigate_to_path", nav)
        return nav

    def test_win32_root_goes_all(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """win32 磁盘根目录 "C:\\" → 跳转 All（L1291-1301）。"""
        selector: Any = file_selector_w12
        monkeypatch.setattr(sys, "platform", "win32")
        selector.current_path = "C:\\"
        nav = self._navigate_mock(selector, monkeypatch)
        selector.go_to_parent()
        nav.assert_called_once_with("All")

    def test_win32_parent(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """win32 非根目录 → 跳转 dirname（L1304-1306）。"""
        selector: Any = file_selector_w12
        monkeypatch.setattr(sys, "platform", "win32")
        selector.current_path = "C:\\Users"
        nav = self._navigate_mock(selector, monkeypatch)
        selector.go_to_parent()
        nav.assert_called_once_with("C:\\")

    def test_posix_root_goes_all(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """非 win32 根目录 "/" → 跳转 All（L1294-1301）。"""
        selector: Any = file_selector_w12
        monkeypatch.setattr(sys, "platform", "linux")
        selector.current_path = "/"
        nav = self._navigate_mock(selector, monkeypatch)
        selector.go_to_parent()
        nav.assert_called_once_with("All")

    def test_posix_parent(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """非 win32 非根目录 → 跳转 dirname（L1304-1306）。"""
        selector: Any = file_selector_w12
        monkeypatch.setattr(sys, "platform", "linux")
        selector.current_path = "/home"
        nav = self._navigate_mock(selector, monkeypatch)
        selector.go_to_parent()
        nav.assert_called_once_with("/")


class TestGetStagingPool:
    """_get_staging_pool（L1142-1152）：父链查找 / 未找到 / 异常回退。"""

    def test_finds_pool_on_parent(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """父链某节点带 file_staging_pool → 返回该池（L1146-1148）。"""
        selector: Any = file_selector_w12
        pool = MagicMock()
        parent = SimpleNamespace(file_staging_pool=pool)
        monkeypatch.setattr(selector, "parent", lambda: parent)
        assert selector._get_staging_pool() is pool

    def test_returns_none_without_pool(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """父链无 file_staging_pool → 返回 None（L1149-1152）。"""
        selector: Any = file_selector_w12
        leaf = SimpleNamespace()
        monkeypatch.setattr(selector, "parent", lambda: leaf)
        assert selector._get_staging_pool() is None

    def test_exception_returns_none(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """父链访问抛异常 → 返回 None（L1150-1151）。"""
        selector: Any = file_selector_w12

        def _raise() -> Any:
            raise RuntimeError("boom")

        bad = SimpleNamespace(parent=_raise)
        monkeypatch.setattr(selector, "parent", lambda: bad)
        assert selector._get_staging_pool() is None


class TestRefreshStagingPoolThumbnails:
    """_refresh_staging_pool_thumbnails（L1154-1170）：reload / 旧版 / 异常。"""

    def test_calls_reload_all_cards(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        """staging_pool 提供 reload_all_cards → 调用之（L1163-1164）。"""
        selector: Any = file_selector_w12
        pool = MagicMock()
        selector._refresh_staging_pool_thumbnails(pool)
        pool.reload_all_cards.assert_called_once()

    def test_legacy_card_refresh(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        """无 reload_all_cards → 逐卡片 refresh_thumbnail（L1166-1168）。"""
        selector: Any = file_selector_w12
        card = MagicMock()
        pool = SimpleNamespace(cards=[(card, {"path": "x"})])
        selector._refresh_staging_pool_thumbnails(pool)
        card.refresh_thumbnail.assert_called_once()

    def test_exception_swallowed(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        """reload_all_cards 抛异常 → 被吞（L1169-1170）。"""
        selector: Any = file_selector_w12
        pool = MagicMock()
        pool.reload_all_cards.side_effect = RuntimeError("x")
        selector._refresh_staging_pool_thumbnails(pool)  # 不抛异常


class TestClearThumbnailCache:
    """_clear_thumbnail_cache（L1186-1280）：确认/成功/空/失败 各分支。"""

    def _patch_visible(self, selector: Any, monkeypatch: Any, visible: bool = True) -> Any:
        """固定 isVisible 返回值。"""
        monkeypatch.setattr(selector, "isVisible", lambda: visible)
        return selector

    def _setup(self, selector: Any, monkeypatch: Any, file_count: int) -> Any:
        """打桩 get_thumbnail_manager + refresh_files。"""
        manager = MagicMock()
        manager.clear_all_thumbnails.return_value = file_count
        monkeypatch.setattr(fs, "get_thumbnail_manager", lambda *a, **k: manager)
        refresh = MagicMock()
        monkeypatch.setattr(selector, "refresh_files", refresh)
        return manager, refresh

    def test_not_visible_returns(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """不可见 → 直接返回（L1192-1193）。"""
        selector: Any = file_selector_w12
        self._patch_visible(selector, monkeypatch, visible=False)
        selector._clear_thumbnail_cache()  # 不抛异常

    def test_cancel_returns(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """确认框点取消（button_index=1）→ is_confirmed=False 返回（L1200-1208）。"""
        selector: Any = file_selector_w12
        self._patch_visible(selector, monkeypatch)
        monkeypatch.setattr(_FakeMessageBox, "auto_button_index", 1)
        monkeypatch.setattr(fs, "get_thumbnail_manager", MagicMock())
        selector._clear_thumbnail_cache()  # 不抛异常

    def test_invisible_after_confirm_returns(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """确认后不可见 → 返回（L1211-1212）。"""
        selector: Any = file_selector_w12
        calls = {"n": 0}

        def _vis() -> bool:
            calls["n"] += 1
            return calls["n"] == 1  # 首次 True，确认后 False

        monkeypatch.setattr(selector, "isVisible", _vis)
        monkeypatch.setattr(_FakeMessageBox, "auto_button_index", 0)
        monkeypatch.setattr(fs, "get_thumbnail_manager", MagicMock())
        selector._clear_thumbnail_cache()  # 不抛异常

    def test_confirmed_clears(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """确认且清出 N>0 → 刷新列表 + 成功提示（L1210-1255）。"""
        selector: Any = file_selector_w12
        self._patch_visible(selector, monkeypatch)
        monkeypatch.setattr(_FakeMessageBox, "auto_button_index", 0)
        manager, refresh = self._setup(selector, monkeypatch, file_count=5)
        selector._clear_thumbnail_cache()
        manager.clear_all_thumbnails.assert_called_once()
        refresh.assert_called_once()

    def test_empty_cache_shows_hint(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """清出 0 个 → 提示缓存为空（L1256-1267）。"""
        selector: Any = file_selector_w12
        self._patch_visible(selector, monkeypatch)
        monkeypatch.setattr(_FakeMessageBox, "auto_button_index", 0)
        manager, refresh = self._setup(selector, monkeypatch, file_count=0)
        selector._clear_thumbnail_cache()
        manager.clear_all_thumbnails.assert_called_once()
        refresh.assert_not_called()

    def test_refreshes_staging_pool(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """找到 staging_pool → 刷新其卡片（L1239-1243）。"""
        selector: Any = file_selector_w12
        self._patch_visible(selector, monkeypatch)
        monkeypatch.setattr(_FakeMessageBox, "auto_button_index", 0)
        manager, _refresh = self._setup(selector, monkeypatch, file_count=2)
        pool = MagicMock()
        monkeypatch.setattr(selector, "_get_staging_pool", lambda: pool)
        selector._clear_thumbnail_cache()
        pool.reload_all_cards.assert_called_once()

    def test_exception_shows_error(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """清理抛异常 → 错误提示（L1268-1280）。"""
        selector: Any = file_selector_w12
        self._patch_visible(selector, monkeypatch)
        monkeypatch.setattr(_FakeMessageBox, "auto_button_index", 0)

        def _raise(*a: Any, **k: Any) -> Any:
            raise RuntimeError("boom")

        monkeypatch.setattr(fs, "get_thumbnail_manager", _raise)
        selector._clear_thumbnail_cache()  # 错误提示不阻塞

    def test_runtime_errors_swallowed(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """RuntimeError 分支（模型缓存/刷新/暂存池）被吞（L1222-1243）。"""
        selector: Any = file_selector_w12
        self._patch_visible(selector, monkeypatch)
        monkeypatch.setattr(_FakeMessageBox, "auto_button_index", 0)
        manager, _refresh = self._setup(selector, monkeypatch, file_count=2)

        def _rte(*a: Any, **k: Any) -> Any:
            raise RuntimeError("gone")

        monkeypatch.setattr(selector.file_model, "clear_caches", _rte)
        monkeypatch.setattr(selector, "refresh_files", _rte)
        monkeypatch.setattr(selector, "_get_staging_pool", _rte)
        selector._clear_thumbnail_cache()  # 各 RuntimeError 分支被吞


class TestSaveAndFlushFavorites:
    """_save_favorites / _flush_favorites_save（L1335-1349）。"""

    def test_save_starts_timer(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        """_save_favorites → 防抖定时器 start（L1339）。"""
        selector: Any = file_selector_w12
        selector._save_favorites()
        selector._favorites_save_timer.start.assert_called_once()

    def test_flush_loads_first_when_not_loaded(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """未加载收藏 → 先 _load_favorites 再保存（L1343-1344）。"""
        selector: Any = file_selector_w12
        selector._favorites_loaded = False
        selector.favorites = [{"path": "C:\\a", "name": "a"}]
        load = MagicMock()
        monkeypatch.setattr(selector, "_load_favorites", load)
        save = MagicMock()
        monkeypatch.setattr(selector._favorites_service, "save", save)
        selector._flush_favorites_save()
        load.assert_called_once()
        save.assert_called_once_with(["C:\\a"])

    def test_flush_saves_paths(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """提取全部含 path 的条目路径保存（L1346-1347）。"""
        selector: Any = file_selector_w12
        selector._favorites_loaded = True
        selector.favorites = [
            {"path": "C:\\a", "name": "a"},
            {"path": "C:\\b", "name": "b"},
            {"name": "no-path"},
        ]
        save = MagicMock()
        monkeypatch.setattr(selector._favorites_service, "save", save)
        selector._flush_favorites_save()
        save.assert_called_once_with(["C:\\a", "C:\\b"])

    def test_flush_exception_warns(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """保存抛异常 → warning（L1348-1349）。"""
        selector: Any = file_selector_w12
        selector._favorites_loaded = True
        selector.favorites = [{"path": "C:\\a", "name": "a"}]
        save = MagicMock(side_effect=RuntimeError("x"))
        monkeypatch.setattr(selector._favorites_service, "save", save)
        warn = MagicMock()
        monkeypatch.setattr("freeassetfilter.components.file_selector.warning", warn)
        selector._flush_favorites_save()
        warn.assert_called_once()


class TestFindFavoriteByPath:
    """_find_favorite_by_path（L1514-1520）。"""

    def test_finds_matching(self, qapp: Any, file_selector_w12: Any) -> None:
        """normpath 匹配返回条目（L1517-1519）。"""
        selector: Any = file_selector_w12
        selector.favorites = [{"path": "C:\\fav\\a.txt", "name": "a.txt"}]
        found = selector._find_favorite_by_path("C:\\fav\\a.txt")
        assert found == {"path": "C:\\fav\\a.txt", "name": "a.txt"}

    def test_no_match_returns_none(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        """无匹配 → None（L1520）。"""
        selector: Any = file_selector_w12
        selector.favorites = [{"path": "C:\\fav\\a.txt", "name": "a.txt"}]
        assert selector._find_favorite_by_path("C:\\other\\b.txt") is None

    def test_empty_path_returns_none(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        """空路径 → None（L1516）。"""
        selector: Any = file_selector_w12
        selector.favorites = [{"path": "C:\\fav\\a.txt", "name": "a.txt"}]
        assert selector._find_favorite_by_path("") is None


class TestOnFavoriteClicked:
    """_on_favorite_clicked（L1446-1452）。"""

    def test_existing_path_navigates(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """路径存在 → 导航 + 关闭对话框（L1450-1452）。"""
        selector: Any = file_selector_w12
        target = make_text(str(tmp_path / "click.txt"))
        nav = MagicMock()
        monkeypatch.setattr(selector, "_navigate_to_path", nav)
        dialog = MagicMock()
        selector._on_favorite_clicked(target, dialog)
        nav.assert_called_once_with(target)
        dialog.close.assert_called_once()

    def test_missing_path_noop(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """路径不存在 → 无操作（L1450）。"""
        selector: Any = file_selector_w12
        nav = MagicMock()
        monkeypatch.setattr(selector, "_navigate_to_path", nav)
        selector._on_favorite_clicked("C:\\nope.txt", MagicMock())
        nav.assert_not_called()


class TestOnFavoriteRenameDlg:
    """_on_favorite_rename_dlg（L1454-1485）。"""

    def test_not_found_returns(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """收藏项不存在 → 直接返回（L1458-1460）。"""
        selector: Any = file_selector_w12
        selector.favorites = []
        monkeypatch.setattr(_FakeMessageBox, "auto_button_index", 0)
        selector._on_favorite_rename_dlg("C:\\x", MagicMock(), MagicMock())

    def test_cancel_returns(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """点取消 → 不更新（L1477 判 False）。"""
        selector: Any = file_selector_w12
        selector.favorites = [{"path": "C:\\r.txt", "name": "r"}]
        monkeypatch.setattr(_FakeMessageBox, "auto_button_index", 1)
        model = MagicMock()
        selector._on_favorite_rename_dlg("C:\\r.txt", model, MagicMock())
        assert selector.favorites[0]["name"] == "r"
        model.update_file.assert_not_called()

    def test_confirm_updates(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """确认 + 有效名称 → 更新收藏 + 保存 + 模型刷新（L1477-1485）。"""
        selector: Any = file_selector_w12
        selector.favorites = [{"path": "C:\\r.txt", "name": "r"}]
        monkeypatch.setattr(_FakeMessageBox, "auto_button_index", 0)
        monkeypatch.setattr(_FakeMessageBox, "get_input", lambda self: "新名字")
        model = MagicMock()
        dialog = MagicMock()
        selector._on_favorite_rename_dlg("C:\\r.txt", model, dialog)
        assert selector.favorites[0]["name"] == "新名字"
        model.update_file.assert_called_once_with(
            "C:\\r.txt", {"display_name": "新名字"}
        )

    def test_blank_name_keeps(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """空名 → 不更新（L1479）。"""
        selector: Any = file_selector_w12
        selector.favorites = [{"path": "C:\\r.txt", "name": "r"}]
        monkeypatch.setattr(_FakeMessageBox, "auto_button_index", 0)
        monkeypatch.setattr(_FakeMessageBox, "get_input", lambda self: "   ")
        model = MagicMock()
        selector._on_favorite_rename_dlg("C:\\r.txt", model, MagicMock())
        assert selector.favorites[0]["name"] == "r"
        model.update_file.assert_not_called()


class TestOnFavoriteDeleteDlg:
    """_on_favorite_delete_dlg（L1487-1512）。"""

    def test_not_found_returns(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """收藏项不存在 → 直接返回（L1491-1493）。"""
        selector: Any = file_selector_w12
        selector.favorites = []
        monkeypatch.setattr(_FakeMessageBox, "auto_button_index", 0)
        selector._on_favorite_delete_dlg("C:\\x", MagicMock(), MagicMock())

    def test_cancel_keeps(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """点取消 → 不删除（L1509 判 False）。"""
        selector: Any = file_selector_w12
        selector.favorites = [{"path": "C:\\d.txt", "name": "d"}]
        monkeypatch.setattr(_FakeMessageBox, "auto_button_index", 1)
        model = MagicMock()
        selector._on_favorite_delete_dlg("C:\\d.txt", model, MagicMock())
        assert len(selector.favorites) == 1
        model.finalize_remove_file.assert_not_called()

    def test_confirm_removes(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """确认 → 移出列表 + 模型删除（L1509-1512）。"""
        selector: Any = file_selector_w12
        selector.favorites = [
            {"path": "C:\\d.txt", "name": "d"},
            {"path": "C:\\keep.txt", "name": "keep"},
        ]
        monkeypatch.setattr(_FakeMessageBox, "auto_button_index", 0)
        model = MagicMock()
        selector._on_favorite_delete_dlg("C:\\d.txt", model, MagicMock())
        assert selector.favorites == [{"path": "C:\\keep.txt", "name": "keep"}]
        model.finalize_remove_file.assert_called_once_with("C:\\d.txt")


class TestAddCurrentPathToFavoritesStandalone:
    """_add_current_path_to_favorites_standalone（L1522-1570）。"""

    def test_already_exists_shows_info(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """路径已在收藏 → 提示信息框并返回（L1529-1537）。"""
        selector: Any = file_selector_w12
        selector.current_path = "C:\\cur"
        selector.favorites = [{"path": "C:\\cur", "name": "cur"}]
        # _add_current_path_to_favorites_standalone 会先调用 _load_favorites()
        # 从文件重载收藏（tmp 空文件 → 清空手设列表）；置位 _favorites_loaded
        # 使其走早退分支，真正命中"已存在"循环（L1529-1537）。
        selector._favorites_loaded = True
        recorded = _spy_message_box_text(monkeypatch)
        monkeypatch.setattr(_FakeMessageBox, "auto_button_index", 0)
        selector._add_current_path_to_favorites_standalone()
        assert len(selector.favorites) == 1
        assert any("该路径已在收藏夹中" in t for t in recorded)
        selector._add_current_path_to_favorites_standalone()
        assert len(selector.favorites) == 1

    def test_cancel_does_not_add(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """点取消 → 不添加（L1556 判 False）。"""
        selector: Any = file_selector_w12
        selector.current_path = "C:\\cur"
        selector.favorites = []
        monkeypatch.setattr(_FakeMessageBox, "auto_button_index", 1)
        selector._add_current_path_to_favorites_standalone()
        assert selector.favorites == []

    def test_blank_name_does_not_add(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """空名 → 不添加（L1558）。"""
        selector: Any = file_selector_w12
        selector.current_path = "C:\\cur"
        selector.favorites = []
        monkeypatch.setattr(_FakeMessageBox, "auto_button_index", 0)
        monkeypatch.setattr(_FakeMessageBox, "get_input", lambda self: "  ")
        selector._add_current_path_to_favorites_standalone()
        assert selector.favorites == []

    def test_confirm_adds(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """确认 + 有效名 → 追加收藏 + 成功框（L1556-1570）。"""
        selector: Any = file_selector_w12
        selector.current_path = "C:\\cur"
        selector.favorites = []
        monkeypatch.setattr(_FakeMessageBox, "auto_button_index", 0)
        monkeypatch.setattr(_FakeMessageBox, "get_input", lambda self: "我的收藏")
        selector._add_current_path_to_favorites_standalone()
        assert selector.favorites == [
            {"name": "我的收藏", "path": "C:\\cur"}
        ]


class TestOnFavoriteDoubleClicked:
    """_on_favorite_double_clicked（L1572-1583）。"""

    def test_no_separator_noop(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """文本无 ' - ' → 无操作（L1578）。"""
        selector: Any = file_selector_w12
        item = MagicMock()
        item.text.return_value = "no separator"
        nav = MagicMock()
        monkeypatch.setattr(selector, "_navigate_to_path", nav)
        selector._on_favorite_double_clicked(item, MagicMock())
        nav.assert_not_called()

    def test_existing_path_navigates(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """提取路径命中 → 导航 + accept（L1578-1583）。"""
        selector: Any = file_selector_w12
        target = make_text(str(tmp_path / "dbl.txt"))
        item = MagicMock()
        item.text.return_value = f"名称 - {target}"
        nav = MagicMock()
        monkeypatch.setattr(selector, "_navigate_to_path", nav)
        dialog = MagicMock()
        selector._on_favorite_double_clicked(item, dialog)
        nav.assert_called_once_with(target)
        dialog.accept.assert_called_once()

    def test_missing_path_noop(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """提取路径不存在 → 不导航（L1580）。"""
        selector: Any = file_selector_w12
        item = MagicMock()
        item.text.return_value = "名称 - C:\\missing.txt"
        nav = MagicMock()
        monkeypatch.setattr(selector, "_navigate_to_path", nav)
        selector._on_favorite_double_clicked(item, MagicMock())
        nav.assert_not_called()


class TestShowFavoriteContextMenu:
    """_show_favorite_context_menu（L1585-1607）。"""

    def test_no_item_returns(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """itemAt 无条目 → 直接返回（L1591-1592）。"""
        selector: Any = file_selector_w12
        favorites_list = MagicMock()
        favorites_list.itemAt.return_value = None
        menu_cls = MagicMock()
        monkeypatch.setattr(fs, "QMenu", menu_cls)
        selector._show_favorite_context_menu(QPoint(0, 0), favorites_list)
        menu_cls.assert_not_called()

    def test_item_builds_menu(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """有条目 → 构建重命名/删除菜单并 exec（L1594-1607）。"""
        selector: Any = file_selector_w12
        favorites_list = MagicMock()
        favorites_list.itemAt.return_value = MagicMock()
        favorites_list.mapToGlobal.return_value = QPoint(5, 5)
        menu_cls = MagicMock()
        menu = menu_cls.return_value
        monkeypatch.setattr(fs, "QMenu", menu_cls)
        selector._show_favorite_context_menu(QPoint(0, 0), favorites_list)
        menu_cls.assert_called_once_with(selector)
        assert menu.addAction.call_count == 2
        menu.exec_.assert_called_once()


class TestRenameFavorite:
    """_rename_favorite（L1609-1645）。"""

    def test_no_separator_noop(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """文本无 ' - ' → 无操作（L1614）。"""
        selector: Any = file_selector_w12
        selector.favorites = [{"path": "C:\\a.txt", "name": "a"}]
        item = MagicMock()
        item.text.return_value = "no sep"
        item.setText = MagicMock()
        monkeypatch.setattr(_FakeMessageBox, "auto_button_index", 0)
        selector._rename_favorite(item, MagicMock())
        assert selector.favorites[0]["name"] == "a"
        item.setText.assert_not_called()

    def test_match_not_found_noop(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """无匹配收藏项 → 无操作（L1619 循环不命中）。"""
        selector: Any = file_selector_w12
        selector.favorites = [{"path": "C:\\a.txt", "name": "a"}]
        item = MagicMock()
        item.text.return_value = "old - C:\\other.txt"
        item.setText = MagicMock()
        monkeypatch.setattr(_FakeMessageBox, "auto_button_index", 0)
        selector._rename_favorite(item, MagicMock())
        item.setText.assert_not_called()

    def test_cancel_keeps(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """点取消 → 不改名（L1638 判 False）。"""
        selector: Any = file_selector_w12
        selector.favorites = [{"path": "C:\\a.txt", "name": "old"}]
        item = MagicMock()
        item.text.return_value = "old - C:\\a.txt"
        item.setText = MagicMock()
        monkeypatch.setattr(_FakeMessageBox, "auto_button_index", 1)
        selector._rename_favorite(item, MagicMock())
        assert selector.favorites[0]["name"] == "old"
        item.setText.assert_not_called()

    def test_confirm_renames(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """确认 + 有效名 → 更新收藏 + 改列表文本（L1638-1644）。"""
        selector: Any = file_selector_w12
        selector.favorites = [{"path": "C:\\a.txt", "name": "old"}]
        item = MagicMock()
        item.text.return_value = "old - C:\\a.txt"
        item.setText = MagicMock()
        monkeypatch.setattr(_FakeMessageBox, "auto_button_index", 0)
        monkeypatch.setattr(_FakeMessageBox, "get_input", lambda self: "新名")
        selector._rename_favorite(item, MagicMock())
        assert selector.favorites[0]["name"] == "新名"
        item.setText.assert_called_once_with("新名 - C:\\a.txt")


class TestDeleteFavorite:
    """_delete_favorite（L1647-1678）。"""

    def test_no_separator_noop(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """文本无 ' - ' → 无操作（L1652）。"""
        selector: Any = file_selector_w12
        selector.favorites = [{"path": "C:\\a.txt", "name": "a"}]
        item = MagicMock()
        item.text.return_value = "no sep"
        favorites_list = MagicMock()
        monkeypatch.setattr(_FakeMessageBox, "auto_button_index", 0)
        selector._delete_favorite(item, favorites_list)
        assert len(selector.favorites) == 1
        favorites_list.takeItem.assert_not_called()

    def test_cancel_keeps(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """点取消 → 不删除（L1673 判 False）。"""
        selector: Any = file_selector_w12
        selector.favorites = [{"path": "C:\\a.txt", "name": "a"}]
        item = MagicMock()
        item.text.return_value = "a - C:\\a.txt"
        favorites_list = MagicMock()
        monkeypatch.setattr(_FakeMessageBox, "auto_button_index", 1)
        selector._delete_favorite(item, favorites_list)
        assert len(selector.favorites) == 1
        favorites_list.takeItem.assert_not_called()

    def test_confirm_deletes(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """确认 → 移出收藏 + takeItem（L1673-1678）。"""
        selector: Any = file_selector_w12
        selector.favorites = [
            {"path": "C:\\a.txt", "name": "a"},
            {"path": "C:\\b.txt", "name": "b"},
        ]
        item = MagicMock()
        item.text.return_value = "a - C:\\a.txt"
        favorites_list = MagicMock()
        favorites_list.row.return_value = 0
        monkeypatch.setattr(_FakeMessageBox, "auto_button_index", 0)
        selector._delete_favorite(item, favorites_list)
        assert selector.favorites == [{"path": "C:\\b.txt", "name": "b"}]
        favorites_list.takeItem.assert_called_once_with(0)


class TestAddCurrentPathToFavorites:
    """_add_current_path_to_favorites（L1680-1734）。"""

    def test_already_exists_shows_info(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """路径已在收藏 → 提示并返回（L1693-1702）。"""
        selector: Any = file_selector_w12
        selector.current_path = "C:\\cur"
        selector.favorites = [{"path": "C:\\cur", "name": "cur"}]
        favorites_list = MagicMock()
        monkeypatch.setattr(_FakeMessageBox, "auto_button_index", 0)
        selector._add_current_path_to_favorites(favorites_list, favorites_list)
        assert len(selector.favorites) == 1
        favorites_list.addItem.assert_not_called()

    def test_cancel_does_not_add(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """点取消 → 不添加（L1722 判 False）。"""
        selector: Any = file_selector_w12
        selector.current_path = "C:\\cur"
        selector.favorites = []
        favorites_list = MagicMock()
        monkeypatch.setattr(_FakeMessageBox, "auto_button_index", 1)
        selector._add_current_path_to_favorites(favorites_list, favorites_list)
        assert selector.favorites == []
        favorites_list.addItem.assert_not_called()

    def test_blank_name_does_not_add(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """空名 → 不添加（L1724）。"""
        selector: Any = file_selector_w12
        selector.current_path = "C:\\cur"
        selector.favorites = []
        favorites_list = MagicMock()
        monkeypatch.setattr(_FakeMessageBox, "auto_button_index", 0)
        monkeypatch.setattr(_FakeMessageBox, "get_input", lambda self: "")
        selector._add_current_path_to_favorites(favorites_list, favorites_list)
        assert selector.favorites == []

    def test_confirm_adds(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """确认 + 有效名 → 追加收藏 + addItem（L1722-1734）。"""
        selector: Any = file_selector_w12
        selector.current_path = "C:\\cur"
        selector.favorites = []
        favorites_list = MagicMock()
        monkeypatch.setattr(_FakeMessageBox, "auto_button_index", 0)
        monkeypatch.setattr(_FakeMessageBox, "get_input", lambda self: "收藏名")
        selector._add_current_path_to_favorites(favorites_list, favorites_list)
        assert len(selector.favorites) == 1
        assert selector.favorites[0]["name"] == "收藏名"
        assert selector.favorites[0]["path"] == "C:\\cur"
        favorites_list.addItem.assert_called_once_with("收藏名 - C:\\cur")


# =============================================================================
# 导航恢复源（L1746-1764）
# =============================================================================
class TestGetRecoverySourceForNavigation:
    """_get_recovery_source_for_navigation（L1746-1755）优先级链。"""

    def test_valid_current_path_used(
        self, qapp: Any, file_selector_w12: Any, tmp_path: Path
    ) -> None:
        """current_path 存在 → 直接返回（L1747-1749）。"""
        selector: Any = file_selector_w12
        target = tmp_path / "valid"
        target.mkdir()
        selector.current_path = str(target)
        assert selector._get_recovery_source_for_navigation() == str(target)

    def test_falls_back_to_last_accessible(
        self, qapp: Any, file_selector_w12: Any, tmp_path: Path
    ) -> None:
        """current_path 失效 → 用 _last_accessible_path（L1751-1753）。"""
        selector: Any = file_selector_w12
        fallback = tmp_path / "fallback"
        fallback.mkdir()
        selector.current_path = str(tmp_path / "gone")
        selector._last_accessible_path = str(fallback)
        assert selector._get_recovery_source_for_navigation() == str(fallback)

    def test_all_fallback(
        self, qapp: Any, file_selector_w12: Any, tmp_path: Path
    ) -> None:
        """两者都失效 → "All"（L1755）。"""
        selector: Any = file_selector_w12
        selector.current_path = str(tmp_path / "gone")
        selector._last_accessible_path = str(tmp_path / "also_gone")
        assert selector._get_recovery_source_for_navigation() == "All"


class TestRememberNavigationSource:
    """_remember_navigation_source（L1757-1764）保存恢复来源。"""

    def test_same_path_skips(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """目标路径与当前相同 → 不保存（L1758-1759）。"""
        selector: Any = file_selector_w12
        save = MagicMock()
        monkeypatch.setattr(selector, "save_current_path", save)
        selector._remember_navigation_source("All")
        save.assert_not_called()
        assert selector._navigation_recovery_path == "All"

    def test_different_path_saves_recovery(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """不同路径 → 记录恢复源 + 更新 last_accessible + 保存（L1761-1764）。"""
        selector: Any = file_selector_w12
        save = MagicMock()
        monkeypatch.setattr(selector, "save_current_path", save)
        selector._remember_navigation_source("C:\\Users")
        assert selector._navigation_recovery_path == "All"
        assert selector._last_accessible_path == "All"
        save.assert_called_once_with(path="All")


# =============================================================================
# 盘符列表（L1839-1902）
# =============================================================================
class TestBuildDriveItems:
    """_build_drive_items（L1860-1865）组装下拉列表。"""

    def test_local_only(self, qapp: Any, file_selector_w12: Any) -> None:
        """无网络位置 → 仅 "All" + 本地盘符（L1861）。"""
        selector: Any = file_selector_w12
        assert selector._build_drive_items(["C:\\", "D:\\"], []) == [
            "All",
            "C:\\",
            "D:\\",
        ]

    def test_with_network_separator(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        """有网络位置 → 追加分隔线与网络项（L1862-1864）。"""
        selector: Any = file_selector_w12
        items = selector._build_drive_items(
            ["C:\\"], ["\\\\server\\share", "\\\\nas\\data"]
        )
        assert items == [
            "All",
            "C:\\",
            "--- 网络位置 ---",
            "\\\\server\\share",
            "\\\\nas\\data",
        ]


class TestGetCurrentDriveItem:
    """_get_current_drive_item（L1867-1879）默认选中项判定。"""

    def test_all_view(self, qapp: Any, file_selector_w12: Any) -> None:
        """current_path == "All" → "All"（L1868-1869）。"""
        selector: Any = file_selector_w12
        assert selector._get_current_drive_item(["All", "C:\\"]) == "All"

    def test_win32_drive_letter(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """win32 常规路径 → 返回盘符（L1872-1877）。"""
        selector: Any = file_selector_w12
        monkeypatch.setattr(sys, "platform", "win32")
        selector.current_path = "C:\\Users\\foo"
        assert selector._get_current_drive_item(["All", "C:\\", "D:\\"]) == "C:"

    def test_win32_unc_loop_match(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """win32 无盘符反斜杠路径 → 遍历 all_drives 匹配前缀（L1873-1876）。"""
        selector: Any = file_selector_w12
        monkeypatch.setattr(sys, "platform", "win32")
        selector.current_path = "\\\\share"
        assert (
            selector._get_current_drive_item(["All", "\\\\share", "D:\\"])
            == "\\\\share"
        )

    def test_win32_no_drive_returns_all(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """win32 无盘符且不匹配 → "All"（L1877）。"""
        selector: Any = file_selector_w12
        monkeypatch.setattr(sys, "platform", "win32")
        selector.current_path = "relative"
        assert selector._get_current_drive_item(["All", "C:\\"]) == "All"

    def test_posix_returns_slash(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """非 win32 → 恒定 "/"（L1879）。"""
        selector: Any = file_selector_w12
        monkeypatch.setattr(sys, "platform", "linux")
        selector.current_path = "/home/user"
        assert selector._get_current_drive_item(["All"]) == "/"


class TestApplyDriveList:
    """_apply_drive_list（L1881-1894）应用盘符到下拉框。"""

    def test_empty_list_returns(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """空列表 → 直接返回不操作下拉框（L1882-1883）。"""
        selector: Any = file_selector_w12
        combo = MagicMock()
        monkeypatch.setattr(selector, "drive_combo", combo)
        selector._apply_drive_list([])
        combo.assert_not_called()

    def test_applies_items_with_current_default(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """默认项由 _get_current_drive_item 得出（L1885-1886）。"""
        selector: Any = file_selector_w12
        combo = MagicMock()
        combo.list_widget.list_widget.sizeHintForRow.return_value = 20
        monkeypatch.setattr(selector, "drive_combo", combo)
        monkeypatch.setattr(selector, "dpi_scale", 1.0)
        monkeypatch.setattr(sys, "platform", "win32")
        selector.current_path = "D:\\\\data"

        selector._apply_drive_list(["All", "C:\\", "D:\\"])

        combo.set_items.assert_called_once_with(
            ["All", "C:\\", "D:\\"], default_item="D:"
        )
        combo.set_max_visible_items.assert_called_once_with(3)
        combo.set_max_height.assert_called_once()
        height: int = combo.set_max_height.call_args[0][0]
        assert height == 3 * 20 + 6

    def test_default_item_override(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """显式 default_item 参数优先（L1885）。"""
        selector: Any = file_selector_w12
        combo = MagicMock()
        combo.list_widget.list_widget.sizeHintForRow.return_value = 20
        monkeypatch.setattr(selector, "drive_combo", combo)
        monkeypatch.setattr(selector, "dpi_scale", 1.0)

        selector._apply_drive_list(["All", "C:\\"], default_item="C:\\")

        combo.set_items.assert_called_once_with(
            ["All", "C:\\"], default_item="C:\\"
        )


class TestOnDriveListLoaded:
    """_on_drive_list_loaded（L1896-1899）缓存 + 应用。"""

    def test_caches_and_applies(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """保存本地/网络缓存并组装应用（L1897-1899）。"""
        selector: Any = file_selector_w12
        apply = MagicMock()
        monkeypatch.setattr(selector, "_apply_drive_list", apply)

        selector._on_drive_list_loaded(
            ["C:\\", "D:\\"], ["\\\\server\\share"]
        )

        assert selector._cached_local_drives == ["C:\\", "D:\\"]
        assert selector._cached_network_locations == ["\\\\server\\share"]
        apply.assert_called_once_with(
            ["All", "C:\\", "D:\\", "--- 网络位置 ---", "\\\\server\\share"]
        )


class TestOnDriveListThreadFinished:
    """_on_drive_list_thread_finished（L1901-1902）清理线程引用。"""

    def test_clears_thread(self, qapp: Any, file_selector_w12: Any) -> None:
        """线程结束后 _drive_list_thread 置 None（L1902）。"""
        selector: Any = file_selector_w12
        selector._drive_list_thread = MagicMock()
        selector._on_drive_list_thread_finished()
        assert selector._drive_list_thread is None


class TestUpdateDriveList:
    """_update_drive_list（L1839-1858）快速路径 + 异步线程。"""

    def _fake_thread_cls(self) -> Any:
        class _FakeDriveListThread:
            def __init__(self, owner: Any) -> None:
                self.owner = owner
                self.started = False
                self.loaded = MagicMock()
                self.finished = MagicMock()

            def isRunning(self) -> bool:
                return False

            def start(self) -> None:
                self.started = True

        return _FakeDriveListThread

    def test_fast_path_applies_and_starts(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """list_drives 有值 → 同步应用 + 启动异步线程（L1844-1858）。"""
        selector: Any = file_selector_w12
        apply = MagicMock()
        monkeypatch.setattr(selector, "_apply_drive_list", apply)
        fake_cls = self._fake_thread_cls()
        monkeypatch.setattr(fs, "DriveListLoaderThread", fake_cls)

        selector._update_drive_list()

        apply.assert_called_once_with(["All", "C:\\"])
        assert isinstance(selector._drive_list_thread, fake_cls)
        assert selector._drive_list_thread.started is True

    def test_exception_in_list_drives_still_starts(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """快速路径抛异常被吞，异步线程仍启动（L1848-1849）。"""
        selector: Any = file_selector_w12
        monkeypatch.setattr(
            DriveService,
            "list_drives",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        apply = MagicMock()
        monkeypatch.setattr(selector, "_apply_drive_list", apply)
        fake_cls = self._fake_thread_cls()
        monkeypatch.setattr(fs, "DriveListLoaderThread", fake_cls)

        selector._update_drive_list()

        apply.assert_not_called()
        assert isinstance(selector._drive_list_thread, fake_cls)

    def test_running_thread_skips_new(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """已有线程运行中 → 不新建（L1852-1854），快速路径仍应用。"""
        selector: Any = file_selector_w12
        running = MagicMock()
        running.isRunning.return_value = True
        selector._drive_list_thread = running
        apply = MagicMock()
        monkeypatch.setattr(selector, "_apply_drive_list", apply)

        def _boom(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("不应构造新线程")

        monkeypatch.setattr(fs, "DriveListLoaderThread", _boom)

        selector._update_drive_list()

        apply.assert_called_once_with(["All", "C:\\"])
        assert selector._drive_list_thread is running


# =============================================================================
# 目录加载失败恢复（L2391-2411）
# =============================================================================
class TestGetDirectoryLoadFailureRecoveryPath:
    """_get_directory_load_failure_recovery_path（L2391-2399）。"""

    def test_uses_navigation_recovery(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        """_navigation_recovery_path 有效且不等于失败路径 → 返回它（L2392-2395）。"""
        selector: Any = file_selector_w12
        selector._navigation_recovery_path = "C:\\Users"
        selector._last_accessible_path = "C:\\old"
        assert (
            selector._get_directory_load_failure_recovery_path("C:\\bad")
            == "C:\\Users"
        )

    def test_recovery_same_as_failed_returns_all(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        """恢复源与失败路径相同 → "All"（L2397-2398）。"""
        selector: Any = file_selector_w12
        selector._navigation_recovery_path = "C:\\same"
        assert (
            selector._get_directory_load_failure_recovery_path("C:\\same")
            == "All"
        )

    def test_default_fallback(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """无恢复源 → "All"（L2394 兜底）。"""
        selector: Any = file_selector_w12
        monkeypatch.delattr(selector, "_navigation_recovery_path", raising=False)
        monkeypatch.delattr(selector, "_last_accessible_path", raising=False)
        assert (
            selector._get_directory_load_failure_recovery_path("C:\\bad")
            == "All"
        )


class TestRecoverAfterDirectoryLoadFailure:
    """_recover_after_directory_load_failure（L2401-2411）整体恢复流程。"""

    def test_full_recovery(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """设置三个路径字段 + path_edit + 保存 + 刷新（L2402-2411）。"""
        selector: Any = file_selector_w12
        monkeypatch.setattr(
            selector,
            "_get_directory_load_failure_recovery_path",
            lambda failed: "C:\\Users",
        )
        path_edit = MagicMock()
        monkeypatch.setattr(selector, "path_edit", path_edit)
        save = MagicMock()
        monkeypatch.setattr(selector, "save_current_path", save)
        refresh = MagicMock()
        monkeypatch.setattr(selector, "refresh_files", refresh)

        selector._recover_after_directory_load_failure("C:\\bad")

        assert selector._last_accessible_path == "C:\\Users"
        assert selector._navigation_recovery_path == "C:\\Users"
        assert selector.current_path == "C:\\Users"
        path_edit.setText.assert_called_once_with("C:\\Users")
        save.assert_called_once()
        refresh.assert_called_once()

    def test_recovery_to_all(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """恢复源 == 失败路径 → 落到 "All"（L2397-2398 联动）。"""
        selector: Any = file_selector_w12
        selector._navigation_recovery_path = "C:\\same"
        selector.save_current_path = MagicMock()
        refresh = MagicMock()
        monkeypatch.setattr(selector, "refresh_files", refresh)

        selector._recover_after_directory_load_failure("C:\\same")

        assert selector.current_path == "All"
        assert selector._navigation_recovery_path == "All"
        refresh.assert_called_once()


# =============================================================================
# 路径语义判定（L2291-2325）
# =============================================================================
class TestSameSelectorPath:
    """_same_selector_path（L2291-2299）。"""

    def test_identical_true(self, qapp: Any, file_selector_w12: Any) -> None:
        """完全相等 → True（L2292-2293）。"""
        selector: Any = file_selector_w12
        assert selector._same_selector_path("C:\\a", "C:\\a") is True

    def test_all_either_side_false(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        """任一侧 "All" 或为空 → False（L2294-2295）。"""
        selector: Any = file_selector_w12
        assert selector._same_selector_path("All", "C:\\a") is False
        assert selector._same_selector_path("C:\\a", "") is False
        assert selector._same_selector_path(None, "C:\\a") is False

    def test_normalized_equal_true(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        """normcase/normpath 后相等 → True（L2297）。"""
        selector: Any = file_selector_w12
        assert (
            selector._same_selector_path(
                "C:\\Foo\\..\\Bar", "c:\\bar"
            )
            is True
        )

    def test_non_equal_false(self, qapp: Any, file_selector_w12: Any) -> None:
        """不同路径 → False（L2297）。"""
        selector: Any = file_selector_w12
        assert selector._same_selector_path("C:\\a", "C:\\b") is False

    def test_exception_returns_false(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        """normpath 抛 TypeError 等 → False（L2298-2299）。"""
        selector: Any = file_selector_w12
        assert selector._same_selector_path("C:\\a", 123) is False


class TestIsDescendantSelectorPath:
    """_is_descendant_selector_path（L2301-2312）。"""

    def test_all_or_empty_false(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        """任一侧 "All"/空 → False（L2302-2303）。"""
        selector: Any = file_selector_w12
        assert selector._is_descendant_selector_path("All", "C:\\a") is False
        assert selector._is_descendant_selector_path("C:\\a", "") is False
        assert selector._is_descendant_selector_path(None, None) is False

    def test_equal_false(self, qapp: Any, file_selector_w12: Any) -> None:
        """相同路径不算后代（L2308-2309）。"""
        selector: Any = file_selector_w12
        assert (
            selector._is_descendant_selector_path("C:\\a", "C:\\a")
            is False
        )

    def test_descendant_true(self, qapp: Any, file_selector_w12: Any) -> None:
        """子路径是基准路径的后代 → True（L2310）。"""
        selector: Any = file_selector_w12
        assert (
            selector._is_descendant_selector_path("C:\\Users\\a", "C:\\Users")
            is True
        )

    def test_sibling_false(self, qapp: Any, file_selector_w12: Any) -> None:
        """兄弟路径 → False（L2310）。"""
        selector: Any = file_selector_w12
        assert (
            selector._is_descendant_selector_path("C:\\Users\\b", "C:\\Users\\a")
            is False
        )

    def test_exception_false(self, qapp: Any, file_selector_w12: Any) -> None:
        """commonpath 抛异常 → False（L2311-2312）。"""
        selector: Any = file_selector_w12
        assert selector._is_descendant_selector_path("C:\\a", 123) is False


class TestInferNavigationDirection:
    """_infer_navigation_direction（L2314-2325）。"""

    def test_same_path_zero(self, qapp: Any, file_selector_w12: Any) -> None:
        """相同路径 → 0（L2315-2316）。"""
        selector: Any = file_selector_w12
        selector.current_path = "C:\\a"
        assert selector._infer_navigation_direction("C:\\a", "C:\\a") == 0

    def test_from_all_forward(self, qapp: Any, file_selector_w12: Any) -> None:
        """"All" → 具体路径 → 1（L2317-2318）。"""
        selector: Any = file_selector_w12
        assert selector._infer_navigation_direction("All", "C:\\a") == 1

    def test_to_all_back(self, qapp: Any, file_selector_w12: Any) -> None:
        """具体路径 → "All" → -1（L2319-2320）。"""
        selector: Any = file_selector_w12
        assert selector._infer_navigation_direction("C:\\a", "All") == -1

    def test_descend_forward(self, qapp: Any, file_selector_w12: Any) -> None:
        """进入子目录 → 1（L2321-2322）。"""
        selector: Any = file_selector_w12
        assert (
            selector._infer_navigation_direction("C:\\Users", "C:\\Users\\a")
            == 1
        )

    def test_ascend_back(self, qapp: Any, file_selector_w12: Any) -> None:
        """回到父目录 → -1（L2323-2324）。"""
        selector: Any = file_selector_w12
        assert (
            selector._infer_navigation_direction("C:\\Users\\a", "C:\\Users")
            == -1
        )

    def test_unrelated_forward(self, qapp: Any, file_selector_w12: Any) -> None:
        """无关路径默认 → 1（L2325）。"""
        selector: Any = file_selector_w12
        assert (
            selector._infer_navigation_direction("C:\\a", "D:\\b")
            == 1
        )


# =============================================================================
# 路径切换动画（L2327-2389）
# =============================================================================
class TestBeginFilesPathTransition:
    """_begin_files_path_transition（L2327-2343）。"""

    def test_no_list_view_returns(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """无 files_scroll_area → 直接返回（L2330-2332）。"""
        selector: Any = file_selector_w12
        monkeypatch.setattr(selector, "files_scroll_area", None)
        selector._begin_files_path_transition("C:\\a")
        assert selector._pending_path_transition_direction == 0

    def test_no_begin_method_returns(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """滚动区无 begin_path_transition → 返回（L2331）。"""
        selector: Any = file_selector_w12
        monkeypatch.setattr(selector, "files_scroll_area", object())
        selector._begin_files_path_transition("C:\\a")
        assert selector._pending_path_transition_direction == 0

    def test_same_direction_skips(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        """方向 0 → 不启动动画（L2335-2336）。"""
        selector: Any = file_selector_w12
        list_view = MagicMock()
        selector.files_scroll_area = list_view
        selector._begin_files_path_transition("All")
        list_view.begin_path_transition.assert_not_called()
        assert selector._pending_path_transition_direction == 0

    def test_starts_transition(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        """方向非 0 且 begin 成功 → 记录方向 + 令牌自增（L2337-2341）。"""
        selector: Any = file_selector_w12
        list_view = MagicMock()
        list_view.begin_path_transition.return_value = True
        selector.files_scroll_area = list_view
        token_before: int = selector._pending_path_transition_token
        selector._begin_files_path_transition("C:\\a")
        list_view.begin_path_transition.assert_called_once_with(1)
        assert selector._pending_path_transition_direction == 1
        assert selector._pending_path_transition_token == token_before + 1

    def test_begin_exception_swallowed(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        """begin_path_transition 抛异常 → 吞掉（L2342-2343）。"""
        selector: Any = file_selector_w12
        list_view = MagicMock()
        list_view.begin_path_transition.side_effect = RuntimeError("boom")
        selector.files_scroll_area = list_view
        selector._begin_files_path_transition("C:\\a")  # 不抛
        assert selector._pending_path_transition_direction == 0


class TestFinishFilesPathTransition:
    """_finish_files_path_transition（L2345-2362）。"""

    def test_zero_direction_returns(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        """方向 0 → 返回（L2347-2348）。"""
        selector: Any = file_selector_w12
        selector._pending_path_transition_direction = 0
        selector._finish_files_path_transition()  # 不抛

    def test_no_list_view_returns(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """无滚动区 → 返回（L2351-2353）。"""
        selector: Any = file_selector_w12
        selector._pending_path_transition_direction = 1
        monkeypatch.setattr(selector, "files_scroll_area", None)
        selector._finish_files_path_transition()
        assert selector._pending_path_transition_direction == 0

    def test_happy_path(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """方向非 0 → 重置方向 + doItemsLayout + 调度延迟完成（L2350-2360）。"""

        class _NoopTimer:
            @staticmethod
            def singleShot(*args: Any, **kwargs: Any) -> None:
                pass

        selector: Any = file_selector_w12
        selector._pending_path_transition_direction = 1
        selector._pending_path_transition_token = 7
        list_view = MagicMock()
        selector.files_scroll_area = list_view
        deferred = MagicMock()
        monkeypatch.setattr(selector, "_finish_files_path_transition_deferred", deferred)
        monkeypatch.setattr(fs, "QTimer", _NoopTimer)

        selector._finish_files_path_transition()

        assert selector._pending_path_transition_direction == 0
        list_view.doItemsLayout.assert_called_once()
        list_view.viewport().update.assert_called_once()


class TestFinishFilesPathTransitionDeferred:
    """_finish_files_path_transition_deferred（L2364-2379）。"""

    def test_zero_direction_returns(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        """方向 0 → 返回（L2365-2366）。"""
        selector: Any = file_selector_w12
        selector._finish_files_path_transition_deferred(0, 0)

    def test_stale_token_returns(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        """令牌不匹配 → 返回（L2368-2369）。"""
        selector: Any = file_selector_w12
        selector._pending_path_transition_token = 9
        list_view = MagicMock()
        selector.files_scroll_area = list_view
        selector._finish_files_path_transition_deferred(8, 1)
        list_view.finish_path_transition.assert_not_called()

    def test_happy_path(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        """匹配 → doItemsLayout + finish_path_transition(direction)（L2375-2377）。"""
        selector: Any = file_selector_w12
        selector._pending_path_transition_token = 5
        list_view = MagicMock()
        selector.files_scroll_area = list_view
        selector._finish_files_path_transition_deferred(5, 1)
        list_view.doItemsLayout.assert_called_once()
        list_view.finish_path_transition.assert_called_once_with(1)

    def test_missing_list_view_returns(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """滚动区缺失 → 返回（L2371-2373）。"""
        selector: Any = file_selector_w12
        selector._pending_path_transition_token = 5
        monkeypatch.setattr(selector, "files_scroll_area", None)
        selector._finish_files_path_transition_deferred(5, 1)


class TestCancelFilesPathTransition:
    """_cancel_files_path_transition（L2381-2389）。"""

    def test_resets_and_cancels(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        """重置方向 + 令牌自增 + 调用 cancel（L2382-2387）。"""
        selector: Any = file_selector_w12
        selector._pending_path_transition_direction = 1
        selector._pending_path_transition_token = 3
        list_view = MagicMock()
        selector.files_scroll_area = list_view

        selector._cancel_files_path_transition()

        assert selector._pending_path_transition_direction == 0
        assert selector._pending_path_transition_token == 4
        list_view.cancel_path_transition.assert_called_once()

    def test_no_scroll_area_still_resets(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """无滚动区 → 仅重置方向与令牌（L2384 守卫）。"""
        selector: Any = file_selector_w12
        selector._pending_path_transition_direction = 1
        selector._pending_path_transition_token = 3
        monkeypatch.setattr(selector, "files_scroll_area", None)
        selector._cancel_files_path_transition()
        assert selector._pending_path_transition_direction == 0
        assert selector._pending_path_transition_token == 4


# =============================================================================
# Batch E：缩略图生成 L987-1140 / refresh_files 异常 / posix "All" 根目录 /
# 卡片宽度边缘与松动分支（L1331-1332, L1690, L1743-1744, L1873-1876,
# L2510-2513, L2632）
# =============================================================================
class _FakeThumbnailGeneratorThread(MagicMock):
    """假 ThumbnailGeneratorThread：记录入参，不启动真实线程。

    生产 ``_generate_thumbnails``（file_selector.py:1073）通过 ``fs`` 命名
    空间构造后台线程并 connect 四个 Signal（progress_updated /
    thumbnail_created / error_occurred / finished）；MagicMock 基类为这些
    属性自动生成记录 connect 调用的子 mock，测试可通过
    ``selector._thumbnail_thread.finished.connect.call_args`` 取出回调
    直接在测试线程内驱动 finished/thumbnail_created 处理流。
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # MagicMock 子 mock 创建（_get_child_mock）会以 parent/_new_parent 等
        # 关键字实参实例化本类；与 _FakeDropdownMenu 同模式：先丢弃 mock 内部
        # 实参，再从位置实参中取出生产传入的 (thumbnail_manager, files)。
        thumbnail_manager = (
            args[0] if len(args) > 0 else kwargs.pop("thumbnail_manager", None)
        )
        files_to_generate: List[Dict[str, Any]] = (
            args[1]
            if len(args) > 1
            else kwargs.pop("files_to_generate", [])
        )
        super().__init__()
        self.thumbnail_manager = thumbnail_manager
        self.files_to_generate = files_to_generate
        self._started = False
        self._is_running = False
        self.cancel_calls = 0

    def start(self) -> None:
        self._started = True
        self._is_running = True

    def isRunning(self) -> bool:
        return self._is_running

    def cancel(self) -> None:
        self.cancel_calls += 1

    def deleteLater(self) -> None:
        pass


def _spy_message_box_text(monkeypatch: Any) -> List[str]:
    """记录所有 _FakeMessageBox.set_text 调用内容（返回记录列表）。"""
    recorded: List[str] = []
    orig_set_text = _FakeMessageBox.set_text

    def spy_set_text(self: Any, text: str) -> None:
        recorded.append(text)
        return orig_set_text(self, text)

    monkeypatch.setattr(_FakeMessageBox, "set_text", spy_set_text)
    return recorded


def _spy_message_box_instances(monkeypatch: Any) -> List[Any]:
    """记录所有 _FakeMessageBox 构造实例（返回实例列表）。"""
    instances: List[Any] = []
    orig_init = _FakeMessageBox.__init__

    def spy_init(self: Any, parent: Any = None, *args: Any, **kwargs: Any) -> None:
        orig_init(self, parent, *args, **kwargs)
        instances.append(self)

    monkeypatch.setattr(_FakeMessageBox, "__init__", spy_init)
    return instances


class TestGenerateThumbnails:
    """_generate_thumbnails（L987-1140）：线程占用/空列表/取景→启动→完成/取消。"""

    def _manager(self, media_paths: List[str], existing: List[str]) -> Any:
        """构造缩略图管理器 mock：is_media_file / has_thumbnail 按路径判定。"""
        manager = MagicMock()
        manager.is_media_file.side_effect = lambda p: p in media_paths
        manager.has_thumbnail.side_effect = lambda p: p in existing
        return manager

    def _setup_happy(
        self,
        selector: Any,
        monkeypatch: Any,
        manager: Any,
        selector_file: Dict[str, Any],
    ) -> Any:
        """通用 happy-path 打桩：_get_files / _get_staging_pool / 线程类 /
        refresh_files 全 mock，返回被替换的线程类。"""
        monkeypatch.setattr(fs, "get_thumbnail_manager", lambda *a, **k: manager)
        monkeypatch.setattr(selector, "_get_files", lambda: [selector_file])
        monkeypatch.setattr(selector, "_get_staging_pool", lambda: None)
        monkeypatch.setattr(fs, "ThumbnailGeneratorThread", _FakeThumbnailGeneratorThread)
        monkeypatch.setattr(selector, "refresh_files", MagicMock())
        return _FakeThumbnailGeneratorThread

    def test_running_thread_shows_info(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """已有线程正在运行 → 提示并返回（L987-995）。"""
        selector: Any = file_selector_w12
        running = MagicMock()
        running.isRunning.return_value = True
        selector._thumbnail_thread = running
        recorded = _spy_message_box_text(monkeypatch)

        selector._generate_thumbnails()

        assert selector._thumbnail_thread is running
        assert any("已有缩略图生成任务正在进行" in t for t in recorded)

    def test_no_candidates_shows_hint(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """无候选（_get_files 空 + 无暂存池）→ 提示无需生成（L1033-1041）。"""
        selector: Any = file_selector_w12
        manager = self._manager([], [])
        monkeypatch.setattr(fs, "get_thumbnail_manager", lambda *a, **k: manager)
        monkeypatch.setattr(selector, "_get_files", lambda: [])
        monkeypatch.setattr(selector, "_get_staging_pool", lambda: None)
        recorded = _spy_message_box_text(monkeypatch)

        selector._generate_thumbnails()

        assert any("所有文件都已有缩略图" in t for t in recorded)
        assert selector._thumbnail_thread is None

    def test_staging_pool_without_items_ignored(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """暂存池对象无 items 属性 → 忽略（L1015 守卫）。"""
        selector: Any = file_selector_w12
        manager = self._manager([], [])
        monkeypatch.setattr(fs, "get_thumbnail_manager", lambda *a, **k: manager)
        monkeypatch.setattr(selector, "_get_files", lambda: [])
        monkeypatch.setattr(selector, "_get_staging_pool", lambda: object())
        recorded = _spy_message_box_text(monkeypatch)

        selector._generate_thumbnails()

        assert any("所有文件都已有缩略图" in t for t in recorded)

    def test_staging_pool_files_collected(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """选择器 + 暂存池文件均被采集，空路径/is_dir/已有缩略图被跳过（L1002-1031）。"""
        selector: Any = file_selector_w12
        media = ["C:\\sel\\a.jpg", "C:\\pool\\b.png", "C:\\pool\\c.png"]
        manager = self._manager(media, ["C:\\pool\\c.png"])
        selector_file: Dict[str, Any] = {
            "path": "C:\\sel\\a.jpg",
            "name": "a.jpg",
            "is_dir": False,
        }
        pool = SimpleNamespace(
            items=[
                {"path": "", "name": "", "is_dir": False},  # 无路径 → 跳过
                {"path": "C:\\pool\\b.png", "name": "b.png", "is_dir": False},
                {"path": "C:\\pool\\dir", "is_dir": True},  # 目录 → 跳过
                {"path": "C:\\pool\\c.png", "name": "c", "is_dir": False},  # 已有 → 跳过
            ]
        )
        monkeypatch.setattr(fs, "get_thumbnail_manager", lambda *a, **k: manager)
        monkeypatch.setattr(selector, "_get_files", lambda: [selector_file])
        monkeypatch.setattr(selector, "_get_staging_pool", lambda: pool)
        monkeypatch.setattr(fs, "ThumbnailGeneratorThread", _FakeThumbnailGeneratorThread)
        monkeypatch.setattr(selector, "refresh_files", MagicMock())

        selector._generate_thumbnails()

        assert selector._thumbnail_thread is not None
        assert selector._thumbnail_thread.files_to_generate == [
            {"path": "C:\\sel\\a.jpg", "name": "a.jpg", "source": "selector"},
            {"path": "C:\\pool\\b.png", "name": "b.png", "source": "staging_pool"},
        ]

    def test_happy_path_starts_and_finishes(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """正常启动 → 按钮禁用；finished → 按钮恢复 + 完成提示（L1072-1140）。"""
        selector: Any = file_selector_w12
        manager = self._manager(["C:\\sel\\a.jpg"], [])
        selector_file: Dict[str, Any] = {
            "path": "C:\\sel\\a.jpg",
            "name": "a.jpg",
            "is_dir": False,
        }
        self._setup_happy(selector, monkeypatch, manager, selector_file)
        recorded = _spy_message_box_text(monkeypatch)

        selector._generate_thumbnails()

        thread: Any = selector._thumbnail_thread
        assert thread is not None
        assert thread._started
        assert not selector.generate_thumbnails_btn.isEnabled()
        assert thread.files_to_generate == [
            {"path": "C:\\sel\\a.jpg", "name": "a.jpg", "source": "selector"}
        ]

        finish_cb = thread.finished.connect.call_args[0][0]
        finish_cb(2, 2)

        assert selector.generate_thumbnails_btn.isEnabled()
        assert selector._thumbnail_thread is None
        assert any("缩略图生成完成！成功: 2, 总数: 2" in t for t in recorded)

    def test_cancel_flow(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """点取消 → 恢复按钮 + 线程 cancel；finished 后不再弹完成框（L1060-1104）。"""
        selector: Any = file_selector_w12
        manager = self._manager(["C:\\sel\\a.jpg"], [])
        selector_file: Dict[str, Any] = {
            "path": "C:\\sel\\a.jpg",
            "name": "a.jpg",
            "is_dir": False,
        }
        self._setup_happy(selector, monkeypatch, manager, selector_file)
        instances = _spy_message_box_instances(monkeypatch)

        selector._generate_thumbnails()

        thread: Any = selector._thumbnail_thread
        progress_msg = next(m for m in instances if getattr(m, "title", "") == "生成缩略图")
        finish_cb = thread.finished.connect.call_args[0][0]

        progress_msg.buttonClicked.emit(0)  # 触发 on_cancel_clicked

        assert thread.cancel_calls == 1
        assert selector.generate_thumbnails_btn.isEnabled()
        assert progress_msg.closed

        before_count = len(instances)
        finish_cb(1, 1)
        assert selector._thumbnail_thread is None
        assert len(instances) == before_count  # 取消后不弹完成框

    def test_thumbnail_created_updates_model(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """thumbnail_created(selector 源) → 清模型缓存 + 刷新视口（L1084-1091）。"""
        selector: Any = file_selector_w12
        manager = self._manager(["C:\\sel\\a.jpg"], [])
        selector_file: Dict[str, Any] = {
            "path": "C:\\sel\\a.jpg",
            "name": "a.jpg",
            "is_dir": False,
        }
        self._setup_happy(selector, monkeypatch, manager, selector_file)
        clear_caches = MagicMock()
        monkeypatch.setattr(selector.file_model, "clear_caches", clear_caches)

        selector._generate_thumbnails()

        thumb_cb = selector._thumbnail_thread.thumbnail_created.connect.call_args[0][0]
        thumb_cb({"path": "C:\\sel\\a.jpg", "source": "selector"})
        clear_caches.assert_called_once()

    def test_thumbnail_created_staging_refreshes_card(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """thumbnail_created(staging_pool 源) → 刷新对应暂存池卡片（L1088-1089）。"""
        selector: Any = file_selector_w12
        manager = self._manager(["C:\\sel\\a.jpg", "C:\\pool\\b.png"], [])
        selector_file: Dict[str, Any] = {
            "path": "C:\\sel\\a.jpg",
            "name": "a.jpg",
            "is_dir": False,
        }
        self._setup_happy(selector, monkeypatch, manager, selector_file)
        refresh_card = MagicMock()
        monkeypatch.setattr(selector, "_refresh_staging_pool_card", refresh_card)

        selector._generate_thumbnails()

        thumb_cb = selector._thumbnail_thread.thumbnail_created.connect.call_args[0][0]
        thumb_cb({"path": "C:\\pool\\b.png", "source": "staging_pool"})
        refresh_card.assert_called_once_with("C:\\pool\\b.png")

    def test_error_occurred_just_logs(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """error_occurred → 仅记日志不抛（L1092-1093）。"""
        selector: Any = file_selector_w12
        manager = self._manager(["C:\\sel\\a.jpg"], [])
        selector_file: Dict[str, Any] = {
            "path": "C:\\sel\\a.jpg",
            "name": "a.jpg",
            "is_dir": False,
        }
        self._setup_happy(selector, monkeypatch, manager, selector_file)

        selector._generate_thumbnails()

        err_cb = selector._thumbnail_thread.error_occurred.connect.call_args[0][0]
        err_cb("x", ValueError("boom"))  # 不抛异常

    def test_progress_update_flushes_throttle(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """progress_updated 回调 → 节流器即时刷新进度文本（L1077-1082）。"""
        selector: Any = file_selector_w12
        manager = self._manager(["C:\\sel\\a.jpg"], [])
        selector_file: Dict[str, Any] = {
            "path": "C:\\sel\\a.jpg",
            "name": "a.jpg",
            "is_dir": False,
        }
        self._setup_happy(selector, monkeypatch, manager, selector_file)

        class _ImmediateThrottler:
            def __init__(self, min_interval_ms: int = 0) -> None:
                del min_interval_ms

            def update(
                self,
                current: int,
                total: int,
                file_data: Dict[str, Any],
                callback: Callable[..., Any],
            ) -> None:
                callback(current, total, file_data)

        monkeypatch.setattr(fs, "ProgressThrottler", _ImmediateThrottler)
        recorded = _spy_message_box_text(monkeypatch)

        selector._generate_thumbnails()

        progress_cb = selector._thumbnail_thread.progress_updated.connect.call_args[0][0]
        progress_cb(1, 2, {"path": "C:\\sel\\a.jpg"})  # 不抛异常
        assert any("正在生成缩略图... (1/2)" in t for t in recorded)

    def test_finish_with_staging_pool_refreshes_pool(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """完成时含暂存池源 → 结果分栏 + 刷新暂存池卡片（L1115, L1124-1126）。"""
        selector: Any = file_selector_w12
        manager = self._manager(["C:\\sel\\a.jpg", "C:\\pool\\b.png"], [])
        selector_file: Dict[str, Any] = {
            "path": "C:\\sel\\a.jpg",
            "name": "a.jpg",
            "is_dir": False,
        }
        monkeypatch.setattr(fs, "get_thumbnail_manager", lambda *a, **k: manager)
        monkeypatch.setattr(selector, "_get_files", lambda: [selector_file])
        pool = MagicMock()
        pool.items = [{"path": "C:\\pool\\b.png", "name": "b.png", "is_dir": False}]
        monkeypatch.setattr(selector, "_get_staging_pool", lambda: pool)
        monkeypatch.setattr(fs, "ThumbnailGeneratorThread", _FakeThumbnailGeneratorThread)
        monkeypatch.setattr(selector, "refresh_files", MagicMock())
        recorded = _spy_message_box_text(monkeypatch)

        selector._generate_thumbnails()

        thread: Any = selector._thumbnail_thread
        assert any(f["source"] == "staging_pool" for f in thread.files_to_generate)

        finish_cb = thread.finished.connect.call_args[0][0]
        finish_cb(2, 2)  # on_finished → L1124-1126 刷新暂存池

        pool.reload_all_cards.assert_called_once()
        assert any("存储池: 1 个" in t for t in recorded)


class TestGetFilesPosixRoot:
    """_get_files 的 posix "All" 根目录分支（L2503-2524）。"""

    def test_all_root_single(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """非 win32 + "All" → 恰好一个根目录 "/"（L2503-2524）。"""
        selector: Any = file_selector_w12
        monkeypatch.setattr(sys, "platform", "linux")
        selector.current_path = "All"

        files = selector._get_files()

        assert len(files) == 1
        assert files[0]["path"] == "/"
        assert files[0]["name"] == "/"
        assert files[0]["is_dir"] is True
        assert files[0]["suffix"] == ""

    def test_stat_oserror_blank(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """os.stat("/") 抛 OSError → modified/created 置空（L2510-2513）。"""
        selector: Any = file_selector_w12
        monkeypatch.setattr(sys, "platform", "linux")
        selector.current_path = "All"

        def _boom(*a: Any, **k: Any) -> Any:
            raise OSError("no root")

        monkeypatch.setattr(os, "stat", _boom)

        files = selector._get_files()

        assert files[0]["modified"] == ""
        assert files[0]["created"] == ""


class TestRefreshFilesException:
    """refresh_files 的异常兜底（L2198-2201）。"""

    def test_loader_construction_failure(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """FileListLoaderThread 构造抛异常 → 复位 loading + 取消路径动画（L2198-2201）。"""
        selector: Any = file_selector_w12
        cancel_mock = MagicMock()
        monkeypatch.setattr(selector, "_cancel_files_path_transition", cancel_mock)
        error_logger = MagicMock()
        monkeypatch.setattr(fs, "error", error_logger)

        class _BoomLoader:
            def __init__(self, *a: Any, **k: Any) -> None:
                raise RuntimeError("loader boom")

        monkeypatch.setattr(fs, "FileListLoaderThread", _BoomLoader)

        selector.refresh_files()  # 不抛异常

        assert selector._is_loading is False
        cancel_mock.assert_called_once()
        error_logger.assert_called_once()


class TestLoadFavoritesFailure:
    """_load_favorites 读取异常（L1331-1332）。"""

    def test_service_load_raises(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """FavoritesService.load 抛异常 → 记日志并返回空列表（L1331-1332）。"""
        selector: Any = file_selector_w12
        logger = MagicMock()
        monkeypatch.setattr(fs, "warning", logger)

        def _boom(*a: Any, **k: Any) -> Any:
            raise OSError("favorites boom")

        monkeypatch.setattr(selector._favorites_service, "load", _boom)

        result = selector._load_favorites()  # 不抛异常

        logger.assert_called_once()
        assert result == []


class TestIsValidSelectorPathException:
    """_is_valid_selector_path 的异常兜底（L1743-1744）。"""

    def test_bad_path_type_returns_false(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        """os.path.exists 对非法类型抛 TypeError → 返回 False（L1743-1744）。

        刻意不整全局 monkeypatch os.path.exists（后台设置防抖线程也会调用
        它，会造成跨线程异常），改用 list 实参触发固有 TypeError。
        """
        selector: Any = file_selector_w12
        assert selector._is_valid_selector_path(["not", "a", "str"]) is False


class TestCalculateCardWidthEdge:
    """_calculate_card_width 的 max_cols 非正分支（L2631-2632）。"""

    def test_max_columns_nonpositive_returns_base(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """max_cols <= 0 → 直接返回基础宽度（L2631-2632）。"""
        selector: Any = file_selector_w12
        list_view = MagicMock()
        viewport = MagicMock()
        viewport.width.return_value = 500
        list_view.viewport.return_value = viewport
        monkeypatch.setattr(selector, "files_scroll_area", list_view)
        selector._card_spacing = 8
        selector._calculate_card_base_width = lambda: 100

        selector._calculate_max_columns = lambda: 0
        assert selector._calculate_card_width() == 100

        selector._calculate_max_columns = lambda: -1
        assert selector._calculate_card_width() == 100


class TestGetCurrentDriveItemUnc:
    """_get_current_drive_item 的 win32 前缀遍历（L1872-1877）。

    实测：``os.path.splitdrive("\\\\share\\sub")`` 在 Windows 上会把
    ``\\\\share\\sub`` 当作 UNC 盘符直返，不进入循环；要用单反斜杠
    相对路径（splitdrive 返回空盘符）才能确定进入 L1873-1876 遍历。
    """

    def test_loop_matches_backslashed_prefix(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """splitdrive 为空且 \\ 开头 → 遍历前缀命中并返回（L1873-1876）。"""
        selector: Any = file_selector_w12
        monkeypatch.setattr(sys, "platform", "win32")
        selector.current_path = "\\foo\\bar"
        assert (
            selector._get_current_drive_item(["All", "\\foo", "D:\\"])
            == "\\foo"
        )

    def test_loop_skip_separator_no_match_returns_all(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """遍历跳过网络分隔线且无命中 → 回落 "All"（L1875, L1877）。"""
        selector: Any = file_selector_w12
        monkeypatch.setattr(sys, "platform", "win32")
        selector.current_path = "\\foo\\bar"
        assert (
            selector._get_current_drive_item(["--- 网络位置 ---", "D:\\"])
            == "All"
        )

    def test_unc_subpath_returns_splitdrive_drive(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """win32 UNC 子路径 → splitdrive 直返 server+share（L1872, L1877）。"""
        selector: Any = file_selector_w12
        monkeypatch.setattr(sys, "platform", "win32")
        selector.current_path = "\\\\share\\sub\\file"
        assert (
            selector._get_current_drive_item(["All", "\\\\share"])
            == "\\\\share\\sub"
        )


class TestClearThumbnailCacheStagingRefreshFailure:
    """_clear_thumbnail_cache 的暂存池刷新 RuntimeError（L1241-1243）。"""

    def test_refresh_staging_pool_runtimeerror_swallowed(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """_refresh_staging_pool_thumbnails 抛 RuntimeError → 被吞（L1241-1243）。"""
        selector: Any = file_selector_w12
        monkeypatch.setattr(selector, "isVisible", lambda: True)
        monkeypatch.setattr(_FakeMessageBox, "auto_button_index", 0)
        manager = MagicMock()
        manager.clear_all_thumbnails.return_value = 2
        monkeypatch.setattr(fs, "get_thumbnail_manager", lambda *a, **k: manager)
        monkeypatch.setattr(selector, "refresh_files", MagicMock())
        pool = MagicMock()  # 带 cards 属性 → 走 L1239 分支
        monkeypatch.setattr(selector, "_get_staging_pool", lambda: pool)

        def _boom(*a: Any, **k: Any) -> Any:
            raise RuntimeError("refresh boom")

        monkeypatch.setattr(selector, "_refresh_staging_pool_thumbnails", _boom)

        selector._clear_thumbnail_cache()  # 不抛异常


class TestAddCurrentPathToFavoritesRoot:
    """_add_current_path_to_favorites 的默认名回退（L1688-1690）。"""

    def test_root_name_fallback(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """basename 为空（盘符根）→ 默认名回退为完整路径（L1688-1690）。"""
        selector: Any = file_selector_w12
        selector.current_path = "C:\\"
        selector.favorites = []
        favorites_list = MagicMock()
        monkeypatch.setattr(_FakeMessageBox, "auto_button_index", 0)

        selector._add_current_path_to_favorites(favorites_list, favorites_list)

        assert len(selector.favorites) == 1
        assert selector.favorites[0]["name"] == "C:\\"
        assert selector.favorites[0]["path"] == "C:\\"
        favorites_list.addItem.assert_called_once_with("C:\\ - C:\\")


# =============================================================================
# Batch F：卡片信号 / 拖拽 / 图标 / 事件过滤器 / 上下文菜单 / 属性 / 大小格式化
# （targets L2718-3395 末端，覆盖 L2719-2723, 2730-2733, 2738-2742,
# 2761-2782, 2786-2793, 2797-2798, 2802, 2813-2828, 2832-2836, 2843-3038,
# 3045-3050, 3056-3063, 3065-3100, 3103-3124, 3127-3131, 3140-3144,
# 3147-3178, 3181-3194, 3203-3206, 3215-3218, 3228, 3237-3303,
# 3318-3355, 3377）
# =============================================================================
class _FakeContextMenu:
    """假 QMenu：addAction/exec_ 记录调用，绝不进入模态事件循环。

    生产 ``_show_context_menu``（file_selector.py:3102）构造 QMenu 后调用
    ``menu.exec_(self.mapToGlobal(pos))``；真实 QMenu.exec_ 会阻塞等待用户
    交互，必须用假件替换（与 _FakeMessageBox 同理）。
    """

    def __init__(self, parent: QObject = None) -> None:
        self.parent = parent
        self.actions: List[Any] = []
        self.exec_pos: Any = None

    def addAction(self, action: Any) -> Any:
        self.actions.append(action)
        return action

    def exec_(self, pos: Any = None) -> None:
        self.exec_pos = pos


class _FakePropsDialog(QWidget):
    """假 QDialog：exec() 直接返回，exec 不阻塞（_show_properties 专用）。"""

    def __init__(self, parent: QObject = None) -> None:
        super().__init__(parent)

    def accept(self) -> None:
        pass

    def exec(self) -> int:
        return 0


class TestFindVisibleCardByPath:
    """_find_visible_card_by_path（L2718-2723）：row 缺失返回 None，命中返回 file_info。"""

    def test_row_not_found_returns_none(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """get_row 返回 -1 → None。"""
        selector: Any = file_selector_w12
        model = MagicMock()
        model.get_row.return_value = -1
        monkeypatch.setattr(selector, "file_model", model)

        assert selector._find_visible_card_by_path("C:\\a.txt") is None

    def test_row_found_returns_file_info(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """get_row >= 0 → 返回 get_file_info(index(row, 0))。"""
        selector: Any = file_selector_w12
        model = MagicMock()
        model.get_row.return_value = 2
        model.index.return_value = MagicMock()
        info: Dict[str, Any] = {"path": "C:\\a.txt", "name": "a.txt"}
        model.get_file_info.return_value = info
        monkeypatch.setattr(selector, "file_model", model)

        assert selector._find_visible_card_by_path("C:\\a.txt") is info


class TestBackNavigationEvent:
    """event() 鼠标后退按钮（L2725-2734）与 _is_back_navigation_button（L2736-2742）。"""

    def test_mouse_press_back_button_goes_parent(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """MouseButtonPress + BackButton → go_to_parent() 并返回 True。"""
        selector: Any = file_selector_w12
        go_parent = MagicMock()
        monkeypatch.setattr(selector, "go_to_parent", go_parent)

        ev = QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(10, 10),
            Qt.MouseButton.BackButton,
            Qt.MouseButton.BackButton,
            Qt.KeyboardModifier.NoModifier,
        )
        result = selector.event(ev)

        go_parent.assert_called_once()
        assert result is True

    def test_mouse_press_nonback_falls_through(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """MouseButtonPress + LeftButton → 不触发 go_to_parent。"""
        selector: Any = file_selector_w12
        go_parent = MagicMock()
        monkeypatch.setattr(selector, "go_to_parent", go_parent)

        ev = QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(10, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        selector.event(ev)
        go_parent.assert_not_called()

    def test_is_back_navigation_button_true(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        """BackButton / XButton1 / ExtraButton1 均判定为后退导航键。"""
        selector: Any = file_selector_w12
        assert selector._is_back_navigation_button(Qt.MouseButton.BackButton)
        assert selector._is_back_navigation_button(Qt.MouseButton.XButton1)
        assert selector._is_back_navigation_button(Qt.MouseButton.ExtraButton1)

    def test_is_back_navigation_button_false(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        """普通左键不判定为后退导航键。"""
        selector: Any = file_selector_w12
        assert not selector._is_back_navigation_button(Qt.MouseButton.LeftButton)


class TestCardDragEnded:
    """_on_card_drag_ended（L2752-2782）：staging_pool 添加 / previewer 预览。"""

    def _file_info(self, path: str = "C:\\f\\a.txt") -> Dict[str, Any]:
        return {"path": path, "name": "a.txt", "is_dir": False}

    def test_staging_pool_adds_new_file(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        """drop_target='staging_pool' 且未选中 → 添加到 selected_files 并发射信号。"""
        selector: Any = file_selector_w12
        selector._selected_file_paths = set()
        selector.selected_files = {}
        spy = MagicMock()
        selector.file_selection_changed.connect(spy)

        selector._on_card_drag_ended(self._file_info(), "staging_pool")

        norm = os.path.normpath("C:\\f\\a.txt")
        assert selector.selected_files[os.path.normpath("C:\\f")] == {norm}
        assert norm in selector._selected_file_paths
        spy.assert_called_once_with(self._file_info(), True)

    def test_staging_pool_already_selected_noop(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        """已选中 → 不重复添加 / 不发信号。"""
        selector: Any = file_selector_w12
        norm = os.path.normpath("C:\\f\\a.txt")
        selector._selected_file_paths = {norm}
        selector.selected_files = {os.path.normpath("C:\\f"): {norm}}
        spy = MagicMock()
        selector.file_selection_changed.connect(spy)

        selector._on_card_drag_ended(self._file_info(), "staging_pool")

        spy.assert_not_called()
        assert selector.selected_files[os.path.normpath("C:\\f")] == {norm}

    def test_previewer_emits_file_selected(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        """drop_target='previewer' → file_selected.emit(file_info)。"""
        selector: Any = file_selector_w12
        spy = MagicMock()
        selector.file_selected.connect(spy)

        selector._on_card_drag_ended(self._file_info(), "previewer")

        spy.assert_called_once_with(self._file_info())


class TestCardClickHandlers:
    """_handle_card_clicked_signal / _on_folder_clicked / 右键 / 选中变化 / 双击。"""

    @staticmethod
    def _info(path: str) -> Dict[str, Any]:
        return {"path": path, "name": os.path.basename(path), "is_dir": False}

    def test_click_dir_folders_navigate(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """点击 is_dir → _on_folder_clicked → 设置路径并 go_to_path。"""
        selector: Any = file_selector_w12
        go_path = MagicMock()
        monkeypatch.setattr(selector, "go_to_path", go_path)
        set_text = MagicMock()
        monkeypatch.setattr(selector.path_edit, "setText", set_text)

        selector._handle_card_clicked_signal({"path": "C:\\dir", "is_dir": True})

        set_text.assert_called_once_with("C:\\dir")
        go_path.assert_called_once()

    def test_click_file_previewing_cancels(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        """非目录且正预览同一文件 → preview_cancel_requested。"""
        selector: Any = file_selector_w12
        path = "C:\\f\\a.txt"
        selector.previewing_file_path = os.path.normpath(path)
        spy = MagicMock()
        selector.preview_cancel_requested.connect(spy)
        spy_sel = MagicMock()
        selector.file_selected.connect(spy_sel)

        selector._handle_card_clicked_signal(self._info(path))

        spy.assert_called_once()
        spy_sel.assert_not_called()

    def test_click_file_not_previewing_selects(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        """非目录且未预览该文件 → file_selected.emit。"""
        selector: Any = file_selector_w12
        selector.previewing_file_path = None
        spy = MagicMock()
        selector.file_selected.connect(spy)
        spy_cancel = MagicMock()
        selector.preview_cancel_requested.connect(spy_cancel)

        info = self._info("C:\\f\\b.txt")
        selector._handle_card_clicked_signal(info)

        spy.assert_called_once_with(info)
        spy_cancel.assert_not_called()

    def test_right_click_emits_signal(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        """_handle_card_right_clicked_signal → file_right_clicked.emit。"""
        selector: Any = file_selector_w12
        spy = MagicMock()
        selector.file_right_clicked.connect(spy)
        info = {"path": "C:\\a.txt", "is_dir": False}

        selector._handle_card_right_clicked_signal(info)

        spy.assert_called_once_with(info)

    def test_selection_changed_selects(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        """is_selected=True 且未选中 → 添加并发射 True。"""
        selector: Any = file_selector_w12
        selector._selected_file_paths = set()
        selector.selected_files = {}
        spy = MagicMock()
        selector.file_selection_changed.connect(spy)
        info = self._info("C:\\f\\a.txt")

        selector._handle_card_selection_changed_signal(info, True)

        norm = os.path.normpath("C:\\f\\a.txt")
        assert selector.selected_files[os.path.normpath("C:\\f")] == {norm}
        spy.assert_called_once_with(info, True)

    def test_selection_changed_deselects(
        self, qapp: Any, file_selector_w12: Any
    ) -> None:
        """is_selected=False 且已选中 → 移除并发射 False。"""
        selector: Any = file_selector_w12
        norm = os.path.normpath("C:\\f\\a.txt")
        selector._selected_file_paths = {norm}
        selector.selected_files = {os.path.normpath("C:\\f"): {norm}}
        spy = MagicMock()
        selector.file_selection_changed.connect(spy)
        info = self._info("C:\\f\\a.txt")

        selector._handle_card_selection_changed_signal(info, False)

        assert selector.selected_files[os.path.normpath("C:\\f")] == set()
        spy.assert_called_once_with(info, False)

    def test_double_click_dir_navigates(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """双击目录 → 设置路径 + go_to_path。"""
        selector: Any = file_selector_w12
        go_path = MagicMock()
        monkeypatch.setattr(selector, "go_to_path", go_path)
        set_text = MagicMock()
        monkeypatch.setattr(selector.path_edit, "setText", set_text)

        selector._handle_card_double_clicked_signal({"path": "C:\\dir", "is_dir": True})

        set_text.assert_called_once_with("C:\\dir")
        go_path.assert_called_once()

    def test_double_click_file_opens(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """双击文件 → _open_file_by_path。"""
        selector: Any = file_selector_w12
        opener = MagicMock()
        monkeypatch.setattr(selector, "_open_file_by_path", opener)

        selector._handle_card_double_clicked_signal(
            {"path": "C:\\f\\a.txt", "is_dir": False}
        )

        opener.assert_called_once_with("C:\\f\\a.txt")


class TestFormatSize:
    """_format_size（L3052-3063）：B/KB/MB/GB 四档。"""

    def test_bytes(self, file_selector_w12: Any) -> None:
        assert file_selector_w12._format_size(500) == "500 B"

    def test_kilobytes(self, file_selector_w12: Any) -> None:
        assert file_selector_w12._format_size(2048) == "2.0 KB"

    def test_megabytes(self, file_selector_w12: Any) -> None:
        assert file_selector_w12._format_size(5 * 1024 * 1024) == "5.0 MB"

    def test_gigabytes(self, file_selector_w12: Any) -> None:
        assert file_selector_w12._format_size(3 * 1024 * 1024 * 1024) == "3.0 GB"


class TestGetThumbnailPath:
    """_get_thumbnail_path（L3040-3050）：命中既有路径 / 回退 get_thumbnail_path。"""

    def test_existing_thumbnail_returns_path(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """get_existing_thumbnail_path 命中 → 直接返回。"""
        selector: Any = file_selector_w12
        monkeypatch.setattr(
            fs, "get_existing_thumbnail_path", lambda p: "C:\\cache.webp"
        )
        assert selector._get_thumbnail_path("C:\\a.jpg") == "C:\\cache.webp"

    def test_fallback_to_manager(
        self, qapp: Any, file_selector_w12: Any, monkeypatch: Any
    ) -> None:
        """既有路径为空 → get_thumbnail_manager().get_thumbnail_path。"""
        selector: Any = file_selector_w12
        monkeypatch.setattr(fs, "get_existing_thumbnail_path", lambda p: "")
        manager = MagicMock()
        manager.get_thumbnail_path.return_value = "C:\\thumb.webp"
        monkeypatch.setattr(fs, "get_thumbnail_manager", lambda *a, **k: manager)

        assert selector._get_thumbnail_path("C:\\a.jpg") == "C:\\thumb.webp"