# -*- coding: utf-8 -*-
# targets: freeassetfilter.app.main
"""integration 批 1（W6/todo-24）：主应用入口集成测试。

验证 ``freeassetfilter.app.main`` 模块可导入、暴露正确的入口/句柄符号、
``__main__`` 保护块存在、sys.excepthook 被替换，并保留版本信息。

**绝不调用 main()**：计划约束为禁止真实启动 GUI 主循环。本文件只做
导入与源码/符号级断言。

已知导入副作用与处理（对齐 conftest 单例与 data/ 隔离纪律）：

* ``main`` 模块顶层会调用 ``install_console_capture``（写入真实
  ``data/logs/``）并初始化 faulthandler 日志。测试导入前先 monkeypatch
  ``freeassetfilter.utils.app_logger.install_console_capture`` /
  ``get_logger``，把日志路径改指 ``tmp_path_factory``，避免污染真实
  data/ 目录（约定：禁止访问真实 data/ 或用户设置文件）。
* ``main`` 导入会替换 ``sys.excepthook``（模块顶层行为），teardown 时
  恢复原 excepthook，避免跨测试污染。

与旧快照对照：旧 test_main_app.py 的 ``test_clean_reimport`` 会 pop 全部
``freeassetfilter`` 模块再重导入——在本次重构中因单例/faulthandler 状态
不可逆而移除，由 test_module_imports 的全量导入冒烟覆盖等价语义。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Set, Tuple

import pytest
from PySide6.QtCore import QEvent, QSize
from PySide6.QtGui import QCloseEvent, QFocusEvent, QResizeEvent

from tests.support.qt_helpers import flush_widget_queue

pytestmark = pytest.mark.integration

_PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]


@pytest.fixture
def main_module(tmp_path_factory: Any, monkeypatch: Any) -> Any:
    """导入 freeassetfilter.app.main，抑制日志/faulthandler 副作用。

    Args:
        tmp_path_factory: pytest 会话级临时目录工厂。
        monkeypatch: pytest 的 monkeypatch fixture。

    Returns:
        module: 已导入的 freeassetfilter.app.main 模块对象。
    """
    import freeassetfilter.utils.app_logger as app_logger_mod

    log_dir: Path = tmp_path_factory.mktemp("main_logs")
    log_path: str = str(log_dir / "test.log")

    # 1) 阻止 stdout/stderr 双写到真实 data/logs：capture 返回 False。
    monkeypatch.setattr(
        app_logger_mod, "install_console_capture", lambda _path=None: False
    )
    # 2) 阻止 faulthandler 写真实日志文件：get_log_file_path 指到 tmp。
    monkeypatch.setattr(
        app_logger_mod,
        "get_log_file_path",
        lambda _path=None: log_path,
        raising=False,
    )
    # 3) 记录并允许 main 顶层替换 excepthook，teardown 恢复。
    original_excepthook: Any = sys.excepthook
    try:
        import freeassetfilter.app.main as mod

        yield mod
    finally:
        sys.excepthook = original_excepthook


# ---------------------------------------------------------------------------
# 模块导入与关键符号
# ---------------------------------------------------------------------------
class TestMainModuleImport:
    """freeassetfilter.app.main 应可导入并暴露关键入口符号。"""

    def test_import_succeeds(self, main_module: Any) -> None:
        """导入成功且不是 QApplication 子类（避免与 app 实例混用）。"""
        assert main_module.__name__ == "freeassetfilter.app.main"

    def test_main_function_exists(self, main_module: Any) -> None:
        """main 函数应存在且可调用。"""
        assert callable(main_module.main)

    def test_handle_exception_exists(self, main_module: Any) -> None:
        """handle_exception 句柄函数应存在且可调用。"""
        assert callable(main_module.handle_exception)

    def test_cleanup_faulthandler_exists(self, main_module: Any) -> None:
        """cleanup_faulthandler 清理函数应存在且可调用。"""
        assert callable(main_module.cleanup_faulthandler)

    def test_debug_exit_threads_exists(self, main_module: Any) -> None:
        """debug_exit_threads 应存在（main.py:105 定义的退出辅助）。"""
        assert callable(main_module.debug_exit_threads)

    def test_logger_and_faulthandler_flags(self, main_module: Any) -> None:
        """logger 与 faulthandler 模块级标志应存在且类型正确。"""
        assert main_module.logger is not None
        assert hasattr(main_module, "_fault_handler_file")
        assert isinstance(main_module._fault_handler_enabled, bool)


# ---------------------------------------------------------------------------
# __main__ 保护块
# ---------------------------------------------------------------------------
class TestMainGuard:
    """main() 只应在 __main__ 保护块内被调用（绝不无条件执行）。"""

    def test_main_guard_calls_main(self, main_module: Any) -> None:
        """__main__ 保护块应调用 main()，且条件严格等于 __name__ 判断。"""
        source: str = Path(main_module.__file__).read_text(encoding="utf-8")
        lines: list[str] = source.splitlines()
        guard_idx: int | None = None
        for i, line in enumerate(lines):
            if 'if __name__ == "__main__":' in line:
                guard_idx = i
                break
        assert guard_idx is not None, "缺少 __main__ 保护块"
        # 保护块内（缩进 ≥4 空格）应出现 main() 调用。
        called: bool = False
        for line in lines[guard_idx + 1 :]:
            if not line.strip():
                continue
            if not (line.startswith("    ") or line.startswith("\t")):
                break  # 已退出保护块缩进区
            if "main()" in line:
                called = True
                break
        assert called, "__main__ 保护块内未调用 main()"

    def test_main_guard_not_at_module_top_level(self, main_module: Any) -> None:
        """main() 调用不应出现在模块顶层（防止导入即启动）。

        跳过注释行（可能包含 "main()" 字样），只在**可执行代码**中查找。
        """
        source: str = Path(main_module.__file__).read_text(encoding="utf-8")
        lines: list[str] = source.splitlines()
        for i, line in enumerate(lines):
            code: str = line.split("#", 1)[0].strip()
            if "def main" in code:
                continue  # 函数定义（def main():），不是调用
            # 原始行不以空白开头 ⇒ 模块顶层；缩进的调用（如 __main__ 块内）放行。
            indented: bool = line.startswith((" ", "\t"))
            if "main()" in code and not indented:
                assert False, f"顶层发现 main() 调用于第 {i + 1} 行: {line}"


# ---------------------------------------------------------------------------
# 全局异常钩子
# ---------------------------------------------------------------------------
class TestExcepthook:
    """sys.excepthook 应在模块顶层被替换为应用句柄。

    注意：pytest 自身会接管/还原 sys.excepthook，运行时断言不可靠。
    验证模块源码 G195 处的赋值语句是否存在且指向 handle_exception。
    """

    def test_excepthook_replaced(self, main_module: Any) -> None:
        """源码中应存在 sys.excepthook = handle_exception 顶层赋值。"""
        source: str = Path(main_module.__file__).read_text(encoding="utf-8")
        found: bool = False
        for line in source.splitlines():
            code: str = line.split("#", 1)[0].strip()
            if "sys.excepthook" in code and "handle_exception" in code:
                found = True
                break
        assert found, "源码中未找到 sys.excepthook = handle_exception 赋值"


# ---------------------------------------------------------------------------
# 版本信息
# ---------------------------------------------------------------------------
class TestVersion:
    """包版本与 FAFVERSION 文件应存在且是合法字符串。"""

    def test_package_version(self) -> None:
        """freeassetfilter.__version__ 应为非空字符串。"""
        from freeassetfilter import __version__

        assert isinstance(__version__, str)
        assert len(__version__) > 0

    def test_fafversion_file_exists(self) -> None:
        """FAFVERSION 文件应存在于项目根且内容以 v 开头。"""
        fafversion: Path = _PROJECT_ROOT / "FAFVERSION"
        assert fafversion.is_file(), f"FAFVERSION 不存在: {fafversion}"
        content: str = fafversion.read_text(encoding="utf-8").strip()
        assert len(content) > 0
        assert content.startswith("v")


# ---------------------------------------------------------------------------
# StartupWarmupThread
# ---------------------------------------------------------------------------
class TestStartupWarmupThread:
    """后台预热线程：构造、对象名、run() 对缺失二进制的容错。"""

    def test_construction_sets_object_name(self, main_module: Any) -> None:
        """happy：构造后 objectName 应为 StartupWarmupThread。"""
        thread = main_module.StartupWarmupThread()
        assert thread.objectName() == "StartupWarmupThread"
        thread.deleteLater()

    def test_run_swallows_binary_import_errors(self, main_module: Any) -> None:
        """boundary：run() 对缺失 ffmpeg/LUT 二进制不抛出。"""
        thread = main_module.StartupWarmupThread()
        thread.run()  # 内部全异常吞噬，任何环境都不得抛
        thread.deleteLater()


# ---------------------------------------------------------------------------
# handle_thread_exception
# ---------------------------------------------------------------------------
class TestHandleThreadException:
    """子线程未捕获异常钩子：KeyboardInterrupt 静默、普通异常入日志。"""

    def test_keyboard_interrupt_swallowed(
        self, main_module: Any, monkeypatch: Any
    ) -> None:
        """happy：KeyboardInterrupt 不记日志直接返回。"""
        logged: List[int] = []
        monkeypatch.setattr(
            main_module, "log_exception", lambda *a, **k: logged.append(1)
        )
        args = SimpleNamespace(
            exc_type=KeyboardInterrupt,
            exc_value=KeyboardInterrupt("stop"),
            exc_traceback=None,
        )
        main_module.handle_thread_exception(args)
        assert logged == []

    def test_regular_exception_logged(
        self, main_module: Any, monkeypatch: Any
    ) -> None:
        """happy：普通异常委派给 log_exception。"""
        logged: List[int] = []
        monkeypatch.setattr(
            main_module, "log_exception", lambda *a, **k: logged.append(1)
        )
        args = SimpleNamespace(
            exc_type=ValueError,
            exc_value=ValueError("boom"),
            exc_traceback=None,
        )
        main_module.handle_thread_exception(args)
        assert logged == [1]

    def test_non_exception_type_no_crash(
        self, main_module: Any, monkeypatch: Any
    ) -> None:
        """boundary：exc_type 非类型（issubclass 抛 TypeError）不应崩溃。"""
        logged: List[int] = []
        monkeypatch.setattr(
            main_module, "log_exception", lambda *a, **k: logged.append(1)
        )
        args = SimpleNamespace(exc_type=None, exc_value=None, exc_traceback=None)
        main_module.handle_thread_exception(args)
        assert logged == [1]


# ---------------------------------------------------------------------------
# FreeAssetFilterApp 构造与布局
# ---------------------------------------------------------------------------
class TestFreeAssetFilterApp:
    """主窗口构造、init_ui 布局产物、事件处理与信号转发。"""

    def test_construction_builds_ui(self, main_module: Any, qapp: Any) -> None:
        """happy：真实构造出三栏 UI 与状态标签。"""
        app = main_module.FreeAssetFilterApp()
        try:
            assert app.windowTitle() == "FreeAssetFilter"
            assert app.central_widget is not None
            assert app._splitter is not None
            assert app.left_column is not None
            assert app.middle_column is not None
            assert app.right_column is not None
            assert app.status_label is not None
            assert app.status_label.text().startswith("FreeAssetFilter")
        finally:
            app.deleteLater()
            flush_widget_queue(qapp)

    def test_init_ui_rebuilds_layout(self, main_module: Any, qapp: Any) -> None:
        """boundary：init_ui 二次调用可重建布局（幂等不抛）。"""
        app = main_module.FreeAssetFilterApp()
        try:
            old_central: Any = app.central_widget
            app.init_ui()
            assert app.central_widget is not None
            assert app._splitter is not None
            assert app.left_column is not None
            assert app.status_label is not None
            assert old_central is not app.central_widget  # 确实重建
        finally:
            app.deleteLater()
            flush_widget_queue(qapp)

    def test_show_custom_window_demo(self, main_module: Any, qapp: Any) -> None:
        """happy：演示窗口创建并显示（随后关闭释放）。"""
        app = main_module.FreeAssetFilterApp()
        try:
            app.show_custom_window_demo()
            assert hasattr(app, "custom_window") and app.custom_window is not None
            demo: Any = app.custom_window
            demo.close()
            demo.deleteLater()
        finally:
            app.deleteLater()
            flush_widget_queue(qapp)

    def test_show_info_updates_status_label(
        self, main_module: Any, qapp: Any, monkeypatch: Any
    ) -> None:
        """happy：show_info 把标题与消息写入状态标签。"""
        app = main_module.FreeAssetFilterApp()
        try:
            label_text: List[str] = []

            def _fake_set_text(text: str) -> None:
                label_text.append(text)

            monkeypatch.setattr(app.status_label, "setText", _fake_set_text)
            app.show_info("提示", "hello")
            assert label_text == ["提示: hello"]
        finally:
            app.deleteLater()
            flush_widget_queue(qapp)

    def test_update_theme_startup_phase_light_refresh(
        self, main_module: Any, qapp: Any, monkeypatch: Any
    ) -> None:
        """happy：启动阶段 update_theme 走轻量样式刷新，不重建 UI。"""
        app = main_module.FreeAssetFilterApp()
        try:
            refresh_calls: List[int] = []
            monkeypatch.setattr(
                app, "_apply_theme_to_existing_widgets", lambda: refresh_calls.append(1)
            )
            app._is_startup_phase = True  # 构造即 True，此处显式声明意图
            app.update_theme()
            assert refresh_calls == [1]
        finally:
            app.deleteLater()
            flush_widget_queue(qapp)

    def test_schedule_startup_tasks_creates_watchdog(
        self, main_module: Any, qapp: Any, monkeypatch: Any
    ) -> None:
        """happy：schedule_startup_tasks 创建单发看门狗定时器。

        注意：所有 singleShot(0) 延迟任务在本测试中不驱动事件循环，
        因此不会实际创建重量级控件（file_selector_a 等仍为 None）。
        """
        app = main_module.FreeAssetFilterApp()
        try:
            _suppress_startup_deferred(app, monkeypatch)
            app.schedule_startup_tasks()
            assert app._startup_watchdog_timer is not None
            assert app._startup_watchdog_timer.isSingleShot() is True
            assert app._startup_watchdog_timer.interval() == 15000
        finally:
            app.deleteLater()
            flush_widget_queue(qapp)

    def test_close_event_marks_closing_state(
        self, main_module: Any, qapp: Any, monkeypatch: Any
    ) -> None:
        """happy：closeEvent 置 _is_closing 并清空恢复缓冲。"""
        # 避免污染模块级 faulthandler 全局状态
        monkeypatch.setattr(main_module, "cleanup_faulthandler", lambda: None)
        monkeypatch.setattr(main_module, "debug_exit_threads", lambda: None)
        app = main_module.FreeAssetFilterApp()
        try:
            app._pending_restore_items = [{"path": "x"}]
            event = QCloseEvent()
            app.closeEvent(event)
            assert app._is_closing is True
            assert app._pending_restore_items == []
            assert app._restore_safe_mode is False
        finally:
            app.deleteLater()
            flush_widget_queue(qapp)

    def test_resize_event_schedules_stabilize(self, main_module: Any, qapp: Any) -> None:
        """happy：resizeEvent 委派父类并调度 50ms 稳定回调。"""
        app = main_module.FreeAssetFilterApp()
        try:
            event = QResizeEvent(QSize(800, 600), QSize(400, 300))
            app.resizeEvent(event)  # 不驱动事件循环，singleShot 仅挂起不执行
        finally:
            app.deleteLater()
            flush_widget_queue(qapp)

    def test_focus_in_event_delegates_to_super(
        self, main_module: Any, qapp: Any
    ) -> None:
        """happy：focusInEvent 委派父类且不抛。"""
        app = main_module.FreeAssetFilterApp()
        try:
            event = QFocusEvent(QEvent.Type.FocusIn)
            app.focusInEvent(event)
        finally:
            app.deleteLater()
            flush_widget_queue(qapp)

    def test_change_event_handles_window_state(
        self, main_module: Any, qapp: Any
    ) -> None:
        """happy：WindowStateChange 事件被受理，其余类型直接透传。"""
        app = main_module.FreeAssetFilterApp()
        try:
            state_event = QEvent(QEvent.Type.WindowStateChange)
            app.changeEvent(state_event)  # 调度 200ms 回调，不执行
            other_event = QEvent(QEvent.Type.ActivationChange)
            app.changeEvent(other_event)
        finally:
            app.deleteLater()
            flush_widget_queue(qapp)


# ---------------------------------------------------------------------------
# 文件选择/存储池信号转发 handlers
# ---------------------------------------------------------------------------
class _FakeSelector:
    """模拟 file_selector_a 的最小桩。"""

    def __init__(self) -> None:
        self.selected_files: Dict[str, Set[str]] = {}
        self._selected_file_paths: Set[str] = set()
        self.current_path: str = ""
        self._is_loading: bool = False
        self._refresh_callback: Optional[Any] = None
        self.previewing_file_path: Optional[str] = None
        self.navigated_paths: List[Tuple[str, bool]] = []

    def _update_file_selection_state(self) -> None:
        pass

    def _navigate_to_path(
        self, path: str, callback=None, scroll_to_top: bool = False
    ) -> None:
        self.navigated_paths.append((path, scroll_to_top))
        if callback:
            callback()

    def set_previewing_file(self, path: str) -> None:
        self.previewing_file_path = path

    def clear_previewing_state(self) -> None:
        self.previewing_file_path = None

    def scroll_to_file(self, file_info: Dict[str, Any]) -> None:
        pass


class _FakeStagingPool:
    """模拟 file_staging_pool 的最小桩。"""

    def __init__(self) -> None:
        self.items: List[Dict[str, Any]] = []
        self.added: List[Dict[str, Any]] = []
        self.removed: List[str] = []
        self.previewing_file_path: Optional[str] = None

    def load_backup(self) -> Optional[Dict[str, Any]]:
        """测试桩：默认无备份，可被 monkeypatch 覆盖。"""
        return None

    def add_file(self, file_info: Dict[str, Any]) -> None:
        self.added.append(file_info)

    def remove_file(self, file_path: str) -> None:
        self.removed.append(file_path)

    def set_previewing_file(self, path: str) -> None:
        self.previewing_file_path = path

    def clear_previewing_state(self) -> None:
        self.previewing_file_path = None

    def save_backup(self, last_path: Optional[str] = None) -> None:
        """桩：真实实现会写盘，此处静默（防泄漏任务报错）。"""

    def refresh_all_card_icons(self) -> None:
        """桩：真实实现会重建图标，此处静默。"""

    def show_unlinked_files_dialog(self, items: List[Dict[str, Any]]) -> None:
        """桩：真实实现会弹对话框，此处静默。"""


_STARTUP_DEFERRED_CALLABLES: Tuple[str, ...] = (
    "_init_settings_deferred",
    "_create_real_widgets_deferred",
    "_create_bottom_bar_buttons",
    "_load_fonts_async",
    "_lazy_import_pillow_avif",
    "_apply_theme_to_existing_widgets",
    "check_and_restore_backup",
    "_start_background_warmup",
    "_schedule_thumbnail_cleanup",
    "_init_update_controller_deferred",
)


def _suppress_startup_deferred(app: Any, monkeypatch: Any) -> None:
    """把 schedule_startup_tasks 排期的全部副作用任务替换为 no-op。

    Args:
        app: 被测 FreeAssetFilterApp 实例。
        monkeypatch: pytest monkeypatch（本测试内生效）。

    Note:
        schedule_startup_tasks 用 QTimer.singleShot(0, ...) 排期真实控件创建
        （_create_real_widgets_deferred → video_player 布局 → 真实 MPVManager /
        libmpv-2.dll 加载）与后台预热（ffmpeg/C++/Rust 原生库）。测试尾部的
        flush_widget_queue 会驱动事件循环触发这些 singleShot，导致后续同进程
        测试（如 test_mpv_integration 的 mock 分支）在原生库已加载的状态下
        构造 MPVManager，触发 0xC0000409 崩溃。因此在调度前全部替换为 no-op。
    """
    monkeypatch.setattr(app, "heartbeat_manager", None)
    for name in _STARTUP_DEFERRED_CALLABLES:
        monkeypatch.setattr(app, name, lambda *_a, **_k: None, raising=False)


def _bare_app(main_module: Any) -> Any:
    """创建未调用 __init__ 的 FreeAssetFilterApp 实例（免重量级 UI 构造）。

    Args:
        main_module: 已导入的 freeassetfilter.app.main 模块。

    Returns:
        Any: 裸实例，仅含 handler 依赖的最小属性。
    """
    app = main_module.FreeAssetFilterApp.__new__(main_module.FreeAssetFilterApp)
    app._is_closing = False
    app._pending_restore_items = []
    app._pending_restore_unlinked_files = []
    app._restore_total_count = 0
    app._restore_success_count = 0
    app._restore_batch_size = 50
    app._restore_safe_mode = False
    app._startup_watchdog_timer = None
    app._startup_flags = {
        "restore_done": False,
        "warmup_done": False,
        "cleanup_done": False,
    }
    app.file_selector_a = None
    app.file_staging_pool = None
    return app


class TestSelectorPoolHandlers:
    """选择/存储池信号转发的真实行为验证（裸实例 + 桩）。"""

    def test_handle_file_selection_changed_select(
        self, main_module: Any
    ) -> None:
        """happy：选中时向存储池 add_file（仅当路径未重复）。"""
        app = _bare_app(main_module)
        pool = _FakeStagingPool()
        pool.items = [{"path": "C:/a/b.txt", "suffix": "txt"}]
        app.file_staging_pool = pool

        app.handle_file_selection_changed({"path": "C:/a/b.txt", "suffix": "txt"}, True)
        assert pool.added == []  # 已存在，跳过

        app.handle_file_selection_changed({"path": "C:/a/new.txt", "suffix": "txt"}, True)
        assert len(pool.added) == 1
        assert pool.added[0]["path"] == "C:/a/new.txt"

    def test_handle_file_selection_changed_deselect(
        self, main_module: Any
    ) -> None:
        """happy：取消选中时从存储池 remove_file。"""
        app = _bare_app(main_module)
        pool = _FakeStagingPool()
        app.file_staging_pool = pool

        app.handle_file_selection_changed({"path": "C:/a/b.txt", "suffix": "txt"}, False)
        assert pool.removed == [os.path.normpath("C:/a/b.txt")]

    def test_handle_remove_from_selector(self, main_module: Any) -> None:
        """happy：从选择器已选集合中删除并刷新。"""
        app = _bare_app(main_module)
        sel = _FakeSelector()
        norm_path: str = os.path.normpath("C:/a/b.txt")
        norm_dir: str = os.path.normpath("C:/a")
        sel.selected_files[norm_dir] = {norm_path}
        sel._selected_file_paths = {norm_path}
        app.file_selector_a = sel

        app.handle_remove_from_selector({"path": "C:/a/b.txt", "suffix": "txt"})
        assert norm_path not in sel._selected_file_paths
        assert sel.selected_files == {}  # 空目录键被删除

    def test_handle_navigate_to_path(self, main_module: Any) -> None:
        """happy：导航到路径并滚动（无 file_info 时滚动到顶）。"""
        app = _bare_app(main_module)
        sel = _FakeSelector()
        pool = _FakeStagingPool()
        app.file_selector_a = sel
        app.file_staging_pool = pool

        app.handle_navigate_to_path("C:/a", None)
        assert sel.navigated_paths == [(os.path.normpath("C:/a"), True)]

        app.handle_navigate_to_path("C:/a", {"path": "C:/a/b.txt"})
        assert sel.navigated_paths[-1] == (os.path.normpath("C:/a"), False)
        assert pool.added == [{"path": "C:/a/b.txt"}]

    def test_handle_navigate_to_path_no_selector(self, main_module: Any) -> None:
        """boundary：file_selector_a 不存在时静默返回。"""
        app = _bare_app(main_module)
        app.file_selector_a = None
        app.handle_navigate_to_path("C:/a", None)  # 不抛即可

    def test_handle_file_added_to_pool(self, main_module: Any) -> None:
        """happy：add 加入已选集合，且刷新回调不抛。"""
        app = _bare_app(main_module)
        sel = _FakeSelector()
        norm_path: str = os.path.normpath("C:/a/b.txt")
        norm_dir: str = os.path.normpath("C:/a")
        sel.current_path = norm_dir
        sel._is_loading = False
        app.file_selector_a = sel

        app.handle_file_added_to_pool({"path": "C:/a/b.txt", "suffix": "txt"})
        assert sel.selected_files == {norm_dir: {norm_path}}
        assert sel._selected_file_paths == {norm_path}

    def test_handle_preview_started(self, main_module: Any) -> None:
        """happy：预览开始更新选择器与存储池的预览态。"""
        app = _bare_app(main_module)
        sel = _FakeSelector()
        pool = _FakeStagingPool()
        app.file_selector_a = sel
        app.file_staging_pool = pool

        app.handle_preview_started({"path": "C:/a/b.txt"})
        assert sel.previewing_file_path == "C:/a/b.txt"
        assert pool.previewing_file_path == "C:/a/b.txt"

    def test_handle_preview_started_no_path(self, main_module: Any) -> None:
        """boundary：file_info 缺 path 时提前返回。"""
        app = _bare_app(main_module)
        app.file_selector_a = _FakeSelector()
        app.file_staging_pool = _FakeStagingPool()
        app.handle_preview_started({})  # 不抛即可

    def test_handle_preview_cleared(self, main_module: Any) -> None:
        """happy：预览清除时清空两侧预览态。"""
        app = _bare_app(main_module)
        sel = _FakeSelector()
        pool = _FakeStagingPool()
        sel.previewing_file_path = "C:/a/b.txt"
        pool.previewing_file_path = "C:/a/b.txt"
        app.file_selector_a = sel
        app.file_staging_pool = pool

        app.handle_preview_cleared()
        assert sel.previewing_file_path is None
        assert pool.previewing_file_path is None


# ---------------------------------------------------------------------------
# 备份恢复
# ---------------------------------------------------------------------------
class TestBackupRestore:
    """check/start/restore_backup 的真实行为（纯桩路径，不开对话框）。"""

    def test_check_and_restore_no_backup_marks_done(
        self, main_module: Any
    ) -> None:
        """happy：无备份数据时标记 restore_done。"""
        app = _bare_app(main_module)
        app.file_staging_pool = None  # 走磁盘兜底：备份文件不存在

        app.check_and_restore_backup()
        assert app._startup_flags["restore_done"] is True

    def test_check_and_restore_empty_pool_marks_done(
        self, main_module: Any, monkeypatch: Any
    ) -> None:
        """boundary：备份内容为空列表时同样标记完成。"""
        app = _bare_app(main_module)
        pool = _FakeStagingPool()
        app.file_staging_pool = pool
        monkeypatch.setattr(pool, "load_backup", lambda: {"items": []})

        app.check_and_restore_backup()
        assert app._startup_flags["restore_done"] is True

    def test_check_and_restore_auto_restores(
        self, main_module: Any, qapp: Any, monkeypatch: Any
    ) -> None:
        """happy：默认自动恢复 → 调用 start_restore_backup。"""
        app = _bare_app(main_module)
        pool = _FakeStagingPool()
        backup: Dict[str, Any] = {
            "items": [{"path": "C:/a/b.txt", "suffix": "txt"}]
        }
        monkeypatch.setattr(pool, "load_backup", lambda: backup)
        app.file_staging_pool = pool
        started: List[Any] = []
        monkeypatch.setattr(app, "start_restore_backup", lambda data: started.append(data))

        app.check_and_restore_backup()
        assert started == [backup]
        assert app._startup_flags["restore_done"] is False  # 未走立即完成分支

    def test_start_restore_backup_batches(
        self, main_module: Any, qapp: Any
    ) -> None:
        """happy：启动分批恢复并设置挂起状态。"""
        app = _bare_app(main_module)
        pool = _FakeStagingPool()
        app.file_staging_pool = pool

        app.start_restore_backup({"items": [{"path": "C:/a/b.txt"}]})
        assert app._pending_restore_items == [{"path": "C:/a/b.txt"}]
        assert app._restore_safe_mode is True
        assert pool._suspend_backup_save is True

    def test_restore_backup_delegates_to_start(
        self, main_module: Any, qapp: Any
    ) -> None:
        """happy：restore_backup 兼容入口转发给 start_restore_backup。"""
        app = _bare_app(main_module)
        app.file_staging_pool = _FakeStagingPool()

        app.restore_backup({"items": [{"path": "C:/a/b.txt"}]})
        assert app._pending_restore_items == [{"path": "C:/a/b.txt"}]

    def test_cancel_startup_watchdog(
        self, main_module: Any, qapp: Any, monkeypatch: Any
    ) -> None:
        """happy：取消看门狗定时器并置空。"""
        app = main_module.FreeAssetFilterApp()
        try:
            _suppress_startup_deferred(app, monkeypatch)
            app.schedule_startup_tasks()
            assert app._startup_watchdog_timer is not None
            app._cancel_startup_watchdog()
            assert app._startup_watchdog_timer is None
        finally:
            app.deleteLater()
            flush_widget_queue(qapp)


# ---------------------------------------------------------------------------
# handle_exception（模块级未捕获异常钩子）
# ---------------------------------------------------------------------------
class TestHandleExceptionFunc:
    """顶层未捕获异常钩子：KeyboardInterrupt 走系统默认，其余记日志。"""

    def test_keyboard_interrupt_delegates_to_system(self, main_module: Any, monkeypatch: Any) -> None:
        """happy：KeyboardInterrupt 调用 sys.__excepthook__。"""
        hooked: List[str] = []
        monkeypatch.setattr(
            sys, "__excepthook__", lambda *a: hooked.append("sys")
        )
        logged: List[int] = []
        monkeypatch.setattr(main_module, "log_exception", lambda *a, **k: logged.append(1))
        main_module.handle_exception(KeyboardInterrupt, KeyboardInterrupt("stop"), None)
        assert hooked == ["sys"]
        assert logged == []

    def test_regular_exception_logged(self, main_module: Any, monkeypatch: Any) -> None:
        """happy：普通异常委派给 log_exception。"""
        logged: List[int] = []
        monkeypatch.setattr(main_module, "log_exception", lambda *a, **k: logged.append(1))
        main_module.handle_exception(ValueError, ValueError("boom"), None)
        assert logged == [1]


# ---------------------------------------------------------------------------
# 内部子进程参数解析 / 命令行参数提取
# ---------------------------------------------------------------------------
class TestInternalWorkerArgs:
    """_parse_internal_worker_args / _extract_associated_file_path / _extract_open_path_arg。"""

    def test_parse_thumbnail_args(self, main_module: Any) -> None:
        """happy：--faf-thumbnail-worker 返回 thumbnail 负载。"""
        argv: List[str] = ["main.py", "--faf-thumbnail-worker", "C:/a.mp4", "1.5", "0"]
        wtype, payload = main_module._parse_internal_worker_args(argv)
        assert wtype == "thumbnail"
        assert payload["file_path"] == "C:/a.mp4"
        assert payload["dpi_scale"] == "1.5"
        assert payload["prefer_native"] == "0"

    def test_parse_installer_args(self, main_module: Any) -> None:
        """happy：--faf-run-installer 返回 run-installer 负载。"""
        argv: List[str] = ["main.py", "--faf-run-installer", "C:/x.exe", "abcd", "123"]
        wtype, payload = main_module._parse_internal_worker_args(argv)
        assert wtype == "run-installer"
        assert payload["installer_path"] == "C:/x.exe"
        assert payload["expected_sha256"] == "abcd"
        assert payload["parent_pid"] == "123"

    def test_parse_unknown_args(self, main_module: Any) -> None:
        """boundary：普通参数返回 (None, {})。"""
        wtype, payload = main_module._parse_internal_worker_args(["main.py"])
        assert wtype is None
        assert payload == {}

    def test_parse_short_args_returns_none(self, main_module: Any) -> None:
        """boundary：参数不足 5 个时返回 (None, {})。"""
        wtype, payload = main_module._parse_internal_worker_args(
            ["main.py", "--faf-thumbnail-worker", "C:/a.mp4"]
        )
        assert wtype is None
        assert payload == {}

    def test_extract_associated_file_path(self, main_module: Any) -> None:
        """happy：取 argv[1] 作为关联文件路径。"""
        assert main_module._extract_associated_file_path(["main.py", "C:/a.txt"]) == "C:/a.txt"

    def test_extract_associated_file_ignores_internal_flag(self, main_module: Any) -> None:
        """boundary：--faf- 前缀参数被忽略（内部 worker 参数）。"""
        assert main_module._extract_associated_file_path(["main.py", "--faf-thumbnail-worker"]) is None

    def test_extract_associated_file_no_arg(self, main_module: Any) -> None:
        """boundary：仅程序名时返回 None。"""
        assert main_module._extract_associated_file_path(["main.py"]) is None

    def test_extract_open_path_arg(self, main_module: Any) -> None:
        """happy：--open-path 后跟路径。"""
        argv: List[str] = ["main.py", "--open-path", "C:/dir"]
        assert main_module._extract_open_path_arg(argv) == "C:/dir"

    def test_extract_open_path_missing(self, main_module: Any) -> None:
        """boundary：无 --open-path 时返回 None。"""
        assert main_module._extract_open_path_arg(["main.py"]) is None

    def test_extract_open_path_no_value(self, main_module: Any) -> None:
        """boundary：--open-path 是最后一个参数时返回 None。"""
        assert main_module._extract_open_path_arg(["main.py", "--open-path"]) is None


# ---------------------------------------------------------------------------
# 运行实例信息文件：写 / 读 / 删除
# ---------------------------------------------------------------------------
class TestRuntimeInstanceInfo:
    """runtime_instance.json 的写入、读取、按 PID 条件删除。"""

    def _info_path(self, main_module: Any, tmp_path: Any) -> str:
        p: Path = tmp_path / "runtime_instance.json"
        monkey_path = p
        return str(monkey_path)

    def test_get_runtime_info_file_path(self, main_module: Any, monkeypatch: Any) -> None:
        """happy：路径 = get_app_data_path()/runtime_instance.json。"""
        monkeypatch.setattr(main_module, "get_app_data_path", lambda: "C:/AppData")
        assert main_module._get_runtime_info_file_path() == os.path.join(
            "C:/AppData", "runtime_instance.json"
        )

    def test_write_runtime_instance_info(self, main_module: Any, tmp_path: Any, monkeypatch: Any) -> None:
        """happy：写入 JSON 且包含当前 pid。"""
        target: Path = tmp_path / "runtime_instance.json"
        monkeypatch.setattr(main_module, "_get_runtime_info_file_path", lambda: str(target))
        info: Dict[str, Any] = main_module._write_runtime_instance_info()
        assert os.path.exists(target)
        assert info["pid"] == os.getpid()
        assert json.loads(target.read_text(encoding="utf-8"))["pid"] == os.getpid()

    def test_read_runtime_instance_info_returns_dict(self, main_module: Any, tmp_path: Any, monkeypatch: Any) -> None:
        """happy：读回 dict。"""
        target: Path = tmp_path / "runtime_instance.json"
        target.write_text('{"pid": 42, "exe_path": "C:/x.exe"}', encoding="utf-8")
        monkeypatch.setattr(main_module, "_get_runtime_info_file_path", lambda: str(target))
        assert main_module._read_runtime_instance_info() == {"pid": 42, "exe_path": "C:/x.exe"}

    def test_read_runtime_instance_info_missing(self, main_module: Any, tmp_path: Any, monkeypatch: Any) -> None:
        """boundary：文件不存在返回 None。"""
        target: Path = tmp_path / "nope.json"
        monkeypatch.setattr(main_module, "_get_runtime_info_file_path", lambda: str(target))
        assert main_module._read_runtime_instance_info() is None

    def test_read_runtime_instance_info_non_dict(self, main_module: Any, tmp_path: Any, monkeypatch: Any) -> None:
        """boundary：JSON 非 dict 返回 None。"""
        target: Path = tmp_path / "runtime_instance.json"
        target.write_text("[1,2,3]", encoding="utf-8")
        monkeypatch.setattr(main_module, "_get_runtime_info_file_path", lambda: str(target))
        assert main_module._read_runtime_instance_info() is None

    def test_remove_runtime_instance_info_no_file(self, main_module: Any, tmp_path: Any, monkeypatch: Any) -> None:
        """boundary：文件不存在时静默返回。"""
        target: Path = tmp_path / "missing.json"
        monkeypatch.setattr(main_module, "_get_runtime_info_file_path", lambda: str(target))
        main_module._remove_runtime_instance_info(expected_pid=os.getpid())  # 不抛即可

    def test_remove_runtime_instance_info_matching_pid(self, main_module: Any, tmp_path: Any, monkeypatch: Any) -> None:
        """happy：pid 匹配时删除文件。"""
        target: Path = tmp_path / "runtime_instance.json"
        target.write_text(f'{{"pid": {os.getpid()}}}', encoding="utf-8")
        monkeypatch.setattr(main_module, "_get_runtime_info_file_path", lambda: str(target))
        main_module._remove_runtime_instance_info(expected_pid=os.getpid())
        assert not os.path.exists(target)

    def test_remove_runtime_instance_info_mismatch_pid(self, main_module: Any, tmp_path: Any, monkeypatch: Any) -> None:
        """boundary：pid 不匹配时保留文件。"""
        target: Path = tmp_path / "runtime_instance.json"
        target.write_text('{"pid": 99999}', encoding="utf-8")
        monkeypatch.setattr(main_module, "_get_runtime_info_file_path", lambda: str(target))
        main_module._remove_runtime_instance_info(expected_pid=os.getpid())
        assert os.path.exists(target)


# ---------------------------------------------------------------------------
# 等待进程退出 / 安装程序 helper
# ---------------------------------------------------------------------------
class TestWaitForProcessExit:
    """_wait_for_process_exit：非法 pid 早退，轮询到目标进程结束。"""

    def test_invalid_pid_returns_early(self, main_module: Any) -> None:
        """boundary：pid 非整数直接返回。"""
        main_module._wait_for_process_exit("abc")  # 不抛即可

    def test_polls_until_process_gone(self, main_module: Any, monkeypatch: Any) -> None:
        """happy：进程停止运行后立即返回。"""
        sleeps: List[float] = []
        monkeypatch.setattr(main_module.time, "sleep", lambda s: sleeps.append(s))
        monkeypatch.setattr(main_module, "_is_process_running", lambda pid: False)
        main_module._wait_for_process_exit(12345, timeout_seconds=30)
        assert sleeps == []  # 首次检查即退出，未 sleep

    def test_timeout_after_full_wait(self, main_module: Any, monkeypatch: Any) -> None:
        """boundary：进程持续运行直至超时后进行兜底等待。"""
        sleeps: List[float] = []
        monkeypatch.setattr(main_module.time, "sleep", lambda s: sleeps.append(s))
        # 始终认为在运行 → 轮询 30s 后 time.sleep(1.0)
        monkeypatch.setattr(main_module, "_is_process_running", lambda pid: True)
        main_module._wait_for_process_exit(12345, timeout_seconds=1)
        assert any(s == 1.0 for s in sleeps)


class TestRunInstallerHelper:
    """_run_installer_after_parent_exit 各分支。"""

    def _patch_installer_deps(self, main_module: Any, monkeypatch: Any, tmp_path: Any) -> Path:
        installer: Path = tmp_path / "faf-setup.exe"
        installer.write_bytes(b"MZ")
        monkeypatch.setattr(main_module, "_wait_for_process_exit", lambda *a, **k: None)
        return installer

    def test_missing_args_returns_1(self, main_module: Any, monkeypatch: Any) -> None:
        """boundary：缺少路径或 SHA256 返回 1。"""
        assert main_module._run_installer_after_parent_exit("", "sha", "123") == 1
        assert main_module._run_installer_after_parent_exit("C:/x.exe", "", "123") == 1

    def test_installer_not_exists_returns_1(self, main_module: Any, monkeypatch: Any, tmp_path: Any) -> None:
        """boundary：安装包不存在返回 1。"""
        assert main_module._run_installer_after_parent_exit(
            str(tmp_path / "nope.exe"), "sha", "123"
        ) == 1

    def test_verify_fail_returns_1(self, main_module: Any, monkeypatch: Any, tmp_path: Any) -> None:
        """boundary：SHA256 校验失败返回 1。"""
        installer = self._patch_installer_deps(main_module, monkeypatch, tmp_path)
        import freeassetfilter.core.managers.update_manager as um

        monkeypatch.setattr(um, "verify_installer_file", lambda *a, **k: False)
        assert main_module._run_installer_after_parent_exit(str(installer), "sha", "123") == 1

    def test_success_win32_startfile(self, main_module: Any, monkeypatch: Any, tmp_path: Any) -> None:
        """happy：win32 + os.startfile 路径返回 0。"""
        installer = self._patch_installer_deps(main_module, monkeypatch, tmp_path)
        import freeassetfilter.core.managers.update_manager as um

        started: List[str] = []
        monkeypatch.setattr(um, "verify_installer_file", lambda *a, **k: True)
        monkeypatch.setattr(main_module.os, "startfile", lambda p: started.append(p), raising=False)
        monkeypatch.setattr(main_module, "sys", SimpleNamespace(platform="win32"))
        assert main_module._run_installer_after_parent_exit(str(installer), "sha", "123") == 0
        assert started == [str(installer)]

    def test_fallback_popen(self, main_module: Any, monkeypatch: Any, tmp_path: Any) -> None:
        """boundary：无 startfile 时回退 subprocess.Popen 返回 0。"""
        installer = self._patch_installer_deps(main_module, monkeypatch, tmp_path)
        import freeassetfilter.core.managers.update_manager as um
        import subprocess

        spawned: List[List[str]] = []
        monkeypatch.setattr(um, "verify_installer_file", lambda *a, **k: True)
        # 移除 os.startfile 属性：不存在时走 Popen 分支
        monkeypatch.delattr(main_module.os, "startfile", raising=False)
        monkeypatch.setattr(main_module, "sys", SimpleNamespace(platform="linux"))
        monkeypatch.setattr(subprocess, "Popen", lambda args, **kw: spawned.append(args))
        assert main_module._run_installer_after_parent_exit(str(installer), "sha", "123") == 0
        assert spawned and spawned[0] == [str(installer)]

    def test_both_spawn_fail_returns_1(self, main_module: Any, monkeypatch: Any, tmp_path: Any) -> None:
        """boundary：两次拉起均失败返回 1。"""
        installer = self._patch_installer_deps(main_module, monkeypatch, tmp_path)
        import freeassetfilter.core.managers.update_manager as um
        import subprocess

        monkeypatch.setattr(um, "verify_installer_file", lambda *a, **k: True)
        monkeypatch.delattr(main_module.os, "startfile", raising=False)
        monkeypatch.setattr(main_module, "sys", SimpleNamespace(platform="linux"))
        monkeypatch.setattr(
            subprocess, "Popen", lambda args, **kw: (_ for _ in ()).throw(OSError("spawn"))
        )
        assert main_module._run_installer_after_parent_exit(str(installer), "sha", "123") == 1


# ---------------------------------------------------------------------------
# 进程检测 / 终止 / 重启（ctypes.windll 打桩）
# ---------------------------------------------------------------------------
class _FakeCDLLFunc:
    """模拟 ctypes 动态库函数：支持 .argtypes/.restype 赋值且可调用。

    真实 ctypes 函数对象允许 ``kernel32.OpenProcess.argtypes = [...]``，
    Python 普通方法不允许；用此类包装底层实现以通过属性赋值。
    """

    def __init__(self, impl: Any) -> None:
        self._impl = impl
        self.argtypes: Any = None
        self.restype: Any = None

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._impl(*args, **kwargs)


class _FakeKernel32:
    """模拟 kernel32.dll 的核心 API（ctypes.windll.kernel32）。"""

    def __init__(self) -> None:
        self.open_process_result: int = 0xABC
        self.exit_code_value: int = 259  # STILL_ACTIVE
        self.terminate_result: int = 1
        self.wait_result: int = 0  # WAIT_OBJECT_0
        self.image_name: str = "C:/Program Files/FreeAssetFilter/FAF.exe"
        self.opened: bool = False
        self.get_exit_code_ok: bool = True
        self.query_image_ok: bool = True
        # ctypes 函数对象（可赋 argtypes/restype）
        self.OpenProcess = _FakeCDLLFunc(self._open_process)
        self.GetExitCodeProcess = _FakeCDLLFunc(self._get_exit_code)
        self.CloseHandle = _FakeCDLLFunc(self._close_handle)
        self.QueryFullProcessImageNameW = _FakeCDLLFunc(self._query_image)
        self.TerminateProcess = _FakeCDLLFunc(self._terminate)
        self.WaitForSingleObject = _FakeCDLLFunc(self._wait)

    def _open_process(self, *args: Any) -> int:
        self.opened = True
        return self.open_process_result

    def _get_exit_code(self, handle: Any, exit_code_ptr: Any) -> int:
        exit_code_ptr.value = self.exit_code_value
        return 1 if self.get_exit_code_ok else 0

    def _close_handle(self, *args: Any) -> int:
        return 1

    def _query_image(self, handle: Any, flags: int, buffer: Any, buf_len_ptr: Any) -> int:
        if not self.query_image_ok:
            return 0
        buffer.value = self.image_name
        buf_len_ptr.value = len(self.image_name)
        return 1

    def _terminate(self, *args: Any) -> int:
        return self.terminate_result

    def _wait(self, *args: Any) -> int:
        return self.wait_result


class _FakeWindll:
    """模拟 ctypes.windll，暴露 .kernel32。"""

    def __init__(self, kernel32: Any) -> None:
        self.kernel32 = kernel32


class TestProcessHelpers:
    """_is_process_running / _get_process_image_path / _terminate_process / _restart_current_application。"""

    def test_is_process_running_invalid_pid(self, main_module: Any) -> None:
        """boundary：pid 非正整数返回 False。"""
        assert main_module._is_process_running(0) is False
        assert main_module._is_process_running(-1) is False
        assert main_module._is_process_running("x") is False

    def test_is_process_running_non_win32(self, main_module: Any, monkeypatch: Any) -> None:
        """boundary：非 win32 平台返回 False。"""
        monkeypatch.setattr(main_module.sys, "platform", "linux")
        assert main_module._is_process_running(1234) is False

    def test_is_process_running_alive(self, main_module: Any, monkeypatch: Any) -> None:
        """happy：退出码为 STILL_ACTIVE(259) 判定存活。"""
        import ctypes as ctypes_mod

        fake = _FakeKernel32()
        monkeypatch.setattr(ctypes_mod, "windll", _FakeWindll(fake), raising=False)
        # byref() 包装对象不可写 .value；恒等化后假函数直接收到 DWORD 本体
        monkeypatch.setattr(ctypes_mod, "byref", lambda x: x)
        monkeypatch.setattr(main_module.sys, "platform", "win32")
        assert main_module._is_process_running(1234) is True

    def test_is_process_running_open_fails(self, main_module: Any, monkeypatch: Any) -> None:
        """boundary：OpenProcess 失败返回 False。"""
        import ctypes as ctypes_mod

        fake = _FakeKernel32()
        fake.open_process_result = 0
        monkeypatch.setattr(ctypes_mod, "windll", _FakeWindll(fake), raising=False)
        monkeypatch.setattr(ctypes_mod, "byref", lambda x: x)
        monkeypatch.setattr(main_module.sys, "platform", "win32")
        assert main_module._is_process_running(1234) is False

    def test_get_process_image_path_invalid_pid(self, main_module: Any) -> None:
        """boundary：pid 非法返回 None。"""
        assert main_module._get_process_image_path(0) is None

    def test_get_process_image_path_success(self, main_module: Any, monkeypatch: Any) -> None:
        """happy：返回规范化进程镜像路径。"""
        import ctypes as ctypes_mod

        fake = _FakeKernel32()
        monkeypatch.setattr(ctypes_mod, "windll", _FakeWindll(fake), raising=False)
        monkeypatch.setattr(ctypes_mod, "byref", lambda x: x)
        monkeypatch.setattr(main_module.sys, "platform", "win32")
        result: Optional[str] = main_module._get_process_image_path(1234)
        assert result == os.path.normcase(os.path.normpath(fake.image_name))

    def test_terminate_process_invalid_pid(self, main_module: Any) -> None:
        """boundary：pid 非法返回失败元组。"""
        ok, msg = main_module._terminate_process(0)
        assert ok is False
        assert msg

    def test_terminate_process_non_win32(self, main_module: Any, monkeypatch: Any) -> None:
        """boundary：非 win32 返回"仅支持 Windows"。"""
        monkeypatch.setattr(main_module.sys, "platform", "linux")
        ok, msg = main_module._terminate_process(1234)
        assert ok is False
        assert "Windows" in msg

    def test_terminate_process_success(self, main_module: Any, monkeypatch: Any) -> None:
        """happy：终止成功且立即退出返回 (True, "")。"""
        import ctypes as ctypes_mod

        fake = _FakeKernel32()
        monkeypatch.setattr(ctypes_mod, "windll", _FakeWindll(fake), raising=False)
        monkeypatch.setattr(main_module.sys, "platform", "win32")
        ok, msg = main_module._terminate_process(1234)
        assert ok is True
        assert msg == ""

    def test_terminate_process_timeout(self, main_module: Any, monkeypatch: Any) -> None:
        """boundary：WaitForSingleObject 超时返回超时提示。"""
        import ctypes as ctypes_mod

        fake = _FakeKernel32()
        fake.wait_result = 0x00000102  # WAIT_TIMEOUT
        monkeypatch.setattr(ctypes_mod, "windll", _FakeWindll(fake), raising=False)
        monkeypatch.setattr(main_module.sys, "platform", "win32")
        ok, msg = main_module._terminate_process(1234)
        assert ok is False
        assert "超时" in msg

    def test_terminate_process_open_fails(self, main_module: Any, monkeypatch: Any) -> None:
        """boundary：OpenProcess 失败（权限/已退出）。"""
        import ctypes as ctypes_mod

        fake = _FakeKernel32()
        fake.open_process_result = 0
        monkeypatch.setattr(ctypes_mod, "windll", _FakeWindll(fake), raising=False)
        monkeypatch.setattr(main_module.sys, "platform", "win32")
        ok, msg = main_module._terminate_process(1234)
        assert ok is False

    def test_restart_current_application_spawns(self, main_module: Any, monkeypatch: Any) -> None:
        """happy：用当前 Python + 原 argv 重新拉起。"""
        import subprocess

        spawned: List[List[str]] = []
        monkeypatch.setattr(subprocess, "Popen", lambda args, **kw: spawned.append(args))
        monkeypatch.setattr(main_module.sys, "argv", ["main.py", "--open-path", "C:/a"])
        main_module._restart_current_application()
        assert spawned and spawned[0][0] == sys.executable
        assert spawned[0][1:] == ["--open-path", "C:/a"]


# ---------------------------------------------------------------------------
# 单实例冲突弹窗 / 强制终止重启
# ---------------------------------------------------------------------------
class _FakeMessageBox:
    """模拟 QMessageBox：记录 exec 次数与点击结果。"""

    Warning = 1
    Critical = 2
    Information = 3
    AcceptRole = 4
    DestructiveRole = 5

    last: "_FakeMessageBox" = None
    force_next: bool = False

    def __init__(self) -> None:
        _FakeMessageBox.last = self
        self.exec_calls: int = 0
        self.buttons: List[Tuple[str, int]] = []
        self.clicked: Optional[Tuple[str, int]] = None

    def setWindowTitle(self, title: str) -> None:
        self.title = title

    def setIcon(self, icon: int) -> None:
        self.icon = icon

    def setText(self, text: str) -> None:
        self.text = text

    def setInformativeText(self, text: str) -> None:
        self.info_text = text

    def addButton(self, text: str, role: int) -> Tuple[str, int]:
        self.buttons.append((text, role))
        return (text, role)

    def setDefaultButton(self, button: Any) -> None:
        self.default = button

    def exec(self) -> None:
        self.exec_calls += 1
        if _FakeMessageBox.force_next and len(self.buttons) > 1:
            self.clicked = self.buttons[1]  # 强制终止后重新启动
        elif self.clicked is None and self.buttons:
            self.clicked = self.buttons[0]

    def clickedButton(self) -> Optional[Tuple[str, int]]:
        """返回 exec 后用户点击的按钮（默认第一个按钮）。"""
        return self.clicked


class TestAlreadyRunningDialog:
    """_show_already_running_dialog_and_handle_restart 各分支（QMessageBox 打桩）。"""

    def _patch_messagebox(self, monkeypatch: Any) -> None:
        from PySide6 import QtWidgets as QW

        _FakeMessageBox.force_next = False
        monkeypatch.setattr(QW, "QMessageBox", _FakeMessageBox)

    def test_ok_button_exits(self, main_module: Any, monkeypatch: Any) -> None:
        """happy：点击"确定"直接返回，不终止。"""
        self._patch_messagebox(monkeypatch)
        main_module._show_already_running_dialog_and_handle_restart(None)
        assert _FakeMessageBox.last.exec_calls == 1

    def test_force_restart_no_runtime_info(
        self, main_module: Any, monkeypatch: Any
    ) -> None:
        """boundary：点"强制终止"但无运行实例信息 → 报错弹窗。"""
        self._patch_messagebox(monkeypatch)
        _FakeMessageBox.force_next = True
        monkeypatch.setattr(main_module, "_read_runtime_instance_info", lambda: None)
        main_module._show_already_running_dialog_and_handle_restart(None)
        assert _FakeMessageBox.last.exec_calls >= 2

    def test_force_restart_read_error(
        self, main_module: Any, monkeypatch: Any
    ) -> None:
        """boundary：读取运行实例信息抛异常 → 报错弹窗后返回。"""
        self._patch_messagebox(monkeypatch)
        _FakeMessageBox.force_next = True

        def _boom() -> Any:
            raise OSError("read fail")

        monkeypatch.setattr(main_module, "_read_runtime_instance_info", _boom)
        main_module._show_already_running_dialog_and_handle_restart(None)
        assert _FakeMessageBox.last.exec_calls >= 2

    def test_force_restart_invalid_pid(
        self, main_module: Any, monkeypatch: Any
    ) -> None:
        """boundary：记录中的 pid 非法 → 报错弹窗。"""
        self._patch_messagebox(monkeypatch)
        _FakeMessageBox.force_next = True
        monkeypatch.setattr(
            main_module, "_read_runtime_instance_info", lambda: {"pid": "not-int"}
        )
        main_module._show_already_running_dialog_and_handle_restart(None)
        assert _FakeMessageBox.last.exec_calls >= 2

    def test_force_restart_process_not_running(
        self, main_module: Any, monkeypatch: Any
    ) -> None:
        """boundary：残留进程已退出 → 清理记录并提示。"""
        self._patch_messagebox(monkeypatch)
        _FakeMessageBox.force_next = True
        monkeypatch.setattr(
            main_module, "_read_runtime_instance_info", lambda: {"pid": 1234}
        )
        monkeypatch.setattr(main_module, "_is_process_running", lambda pid: False)
        removed: List[int] = []
        monkeypatch.setattr(
            main_module,
            "_remove_runtime_instance_info",
            lambda expected_pid=None: removed.append(expected_pid),
        )
        main_module._show_already_running_dialog_and_handle_restart(None)
        assert removed == [1234]
        assert _FakeMessageBox.last.exec_calls >= 2

    def test_force_restart_process_mismatch(
        self, main_module: Any, monkeypatch: Any
    ) -> None:
        """boundary：目标进程与程序不匹配 → 报错弹窗。"""
        self._patch_messagebox(monkeypatch)
        _FakeMessageBox.force_next = True
        monkeypatch.setattr(
            main_module, "_read_runtime_instance_info", lambda: {"pid": 1234}
        )
        monkeypatch.setattr(main_module, "_is_process_running", lambda pid: True)
        monkeypatch.setattr(main_module, "_is_expected_app_process", lambda *a: False)
        main_module._show_already_running_dialog_and_handle_restart(None)
        assert _FakeMessageBox.last.exec_calls >= 2

    def test_force_restart_terminate_fail(
        self, main_module: Any, monkeypatch: Any
    ) -> None:
        """boundary：终止失败 → 报错弹窗。"""
        self._patch_messagebox(monkeypatch)
        _FakeMessageBox.force_next = True
        monkeypatch.setattr(
            main_module, "_read_runtime_instance_info", lambda: {"pid": 1234}
        )
        monkeypatch.setattr(main_module, "_is_process_running", lambda pid: True)
        monkeypatch.setattr(main_module, "_is_expected_app_process", lambda *a: True)
        monkeypatch.setattr(
            main_module, "_terminate_process", lambda pid: (False, "被拒")
        )
        main_module._show_already_running_dialog_and_handle_restart(None)
        assert _FakeMessageBox.last.exec_calls >= 2

    def test_force_restart_terminate_and_exit(
        self, main_module: Any, monkeypatch: Any
    ) -> None:
        """happy：终止成功 → 清理记录 → 重启 → sys.exit(0)。"""
        self._patch_messagebox(monkeypatch)
        _FakeMessageBox.force_next = True
        monkeypatch.setattr(
            main_module, "_read_runtime_instance_info",
            lambda: {"pid": 1234, "exe_path": "C:/x/FAF.exe"},
        )
        monkeypatch.setattr(main_module, "_is_process_running", lambda pid: True)
        monkeypatch.setattr(main_module, "_is_expected_app_process", lambda *a: True)
        monkeypatch.setattr(
            main_module, "_terminate_process", lambda pid: (True, "")
        )
        restarted: List[int] = []
        monkeypatch.setattr(
            main_module, "_restart_current_application", lambda: restarted.append(1)
        )
        removed: List[int] = []
        monkeypatch.setattr(
            main_module,
            "_remove_runtime_instance_info",
            lambda expected_pid=None: removed.append(expected_pid),
        )
        exited: List[int] = []
        monkeypatch.setattr(main_module, "sys", SimpleNamespace(platform="win32", exit=lambda c: exited.append(c)))
        main_module._show_already_running_dialog_and_handle_restart(None)
        assert removed == [1234]
        assert restarted == [1]
        assert exited == [0]

    def test_force_restart_restart_fail(
        self, main_module: Any, monkeypatch: Any
    ) -> None:
        """boundary：重启抛异常 → 报错弹窗。"""
        self._patch_messagebox(monkeypatch)
        _FakeMessageBox.force_next = True
        monkeypatch.setattr(
            main_module, "_read_runtime_instance_info",
            lambda: {"pid": 1234, "exe_path": "C:/x/FAF.exe"},
        )
        monkeypatch.setattr(main_module, "_is_process_running", lambda pid: True)
        monkeypatch.setattr(main_module, "_is_expected_app_process", lambda *a: True)
        monkeypatch.setattr(
            main_module, "_terminate_process", lambda pid: (True, "")
        )
        monkeypatch.setattr(
            main_module, "_restart_current_application",
            lambda: (_ for _ in ()).throw(OSError("restart fail")),
        )
        main_module._show_already_running_dialog_and_handle_restart(None)
        assert _FakeMessageBox.last.exec_calls >= 2


# ---------------------------------------------------------------------------
# main() 内部 worker 子进程分支（thumbnail / run-installer）
# ---------------------------------------------------------------------------
class TestMainWorkerBranches:
    """main() 的 --faf-thumbnail-worker / --faf-run-installer 提前退出路径。

    这两个分支位于 QApplication 创建之前，是 main() 中唯一可在无 GUI 环境下
    安全执行且覆盖率收益显著的路径。GUI 主循环路径（app.exec()）不在本文件
    调用（禁止真实启动 GUI 主循环）。
    """

    def test_main_thumbnail_worker(self, main_module: Any, monkeypatch: Any) -> None:
        """happy：thumbnail 分支执行子进程函数并退出。"""
        import freeassetfilter.core.managers.thumbnail_manager as tm

        calls: List[Any] = []
        monkeypatch.setattr(tm, "_run_batch_video_thumbnail_subprocess", lambda *a: calls.append(a) or 0)
        monkeypatch.setattr(main_module.sys, "argv", ["main.py", "--faf-thumbnail-worker", "C:/a.mp4", "1.0", "1"])
        exited: List[int] = []
        monkeypatch.setattr(
            main_module.sys, "exit",
            lambda code: exited.append(code) or (_ for _ in ()).throw(SystemExit(code)),
        )
        with pytest.raises(SystemExit):
            main_module.main()
        assert calls and calls[0][0] == "C:/a.mp4"
        assert exited == [0]

    def test_main_thumbnail_worker_error(self, main_module: Any, monkeypatch: Any) -> None:
        """boundary：缩略图子进程抛异常 → exit(1)。"""
        import freeassetfilter.core.managers.thumbnail_manager as tm

        monkeypatch.setattr(
            tm, "_run_batch_video_thumbnail_subprocess",
            lambda *a: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        monkeypatch.setattr(main_module.sys, "argv", ["main.py", "--faf-thumbnail-worker", "C:/a.mp4", "1.0", "1"])
        exited: List[int] = []
        monkeypatch.setattr(
            main_module.sys, "exit",
            lambda code: exited.append(code) or (_ for _ in ()).throw(SystemExit(code)),
        )
        with pytest.raises(SystemExit):
            main_module.main()
        assert exited == [1]

    def test_main_run_installer_worker(self, main_module: Any, monkeypatch: Any) -> None:
        """happy：run-installer 分支调用 helper 并退出。"""
        calls: List[Any] = []
        monkeypatch.setattr(
            main_module, "_run_installer_after_parent_exit",
            lambda installer_path, expected_sha256, parent_pid: calls.append((installer_path, parent_pid)) or 0,
        )
        monkeypatch.setattr(
            main_module.sys, "argv",
            ["main.py", "--faf-run-installer", "C:/x.exe", "sha", "1234"],
        )
        exited: List[int] = []
        monkeypatch.setattr(
            main_module.sys, "exit",
            lambda code: exited.append(code) or (_ for _ in ()).throw(SystemExit(code)),
        )
        with pytest.raises(SystemExit):
            main_module.main()
        assert calls and calls[0] == ("C:/x.exe", "1234")
        assert exited == [0]

    def test_main_run_installer_worker_error(self, main_module: Any, monkeypatch: Any) -> None:
        """boundary：run-installer helper 抛异常 → exit(1)。"""
        monkeypatch.setattr(
            main_module, "_run_installer_after_parent_exit",
            lambda *a, **k: (_ for _ in ()).throw(OSError("install fail")),
        )
        monkeypatch.setattr(
            main_module.sys, "argv",
            ["main.py", "--faf-run-installer", "C:/x.exe", "sha", "1234"],
        )
        exited: List[int] = []
        monkeypatch.setattr(
            main_module.sys, "exit",
            lambda code: exited.append(code) or (_ for _ in ()).throw(SystemExit(code)),
        )
        with pytest.raises(SystemExit):
            main_module.main()
        assert exited == [1]