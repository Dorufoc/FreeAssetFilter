# -*- coding: utf-8 -*-
"""主窗口应用级方向键导航过滤器单元测试（arrow-key-file-preview-nav Todo 3 + Todo 4）。

覆盖 ui.main_window.MainWindow：

- 应用级 eventFilter 的方向键捕获分支（按压 / 释放 / 自动重复 / 非方向键）；
- _nav_should_capture 的 10 步守卫顺序（激活 / 弹窗 / 焦点 / 文本 / 储存池）；
- 既有标题栏拖拽鼠标分支的行为保持（回归守卫：标签非白名单 / 非 Widget 对象）；
- changeEvent 失活重置（reset_nav_state）；
- 安装 / 卸载幂等与 destroyed 兜底卸载（全局 QApplication 上无残留过滤器）。

无头环境下没有真实的“活动窗口”，捕获类用例按计划要求统一打桩：
``window.isActiveWindow -> True``、``QApplication.activeWindow -> window``、
``QApplication.focusWidget -> 指定窗口内控件``。

Todo 4 追加：``_on_file_selected`` 的预览防重复加载（同路径早退；不同路径 /
None / 空路径 / 无 getter / getter 抛错时照常刷新），以及端到端接线用例
（eventFilter → 真实 ``FileSelectorLayout`` 按压/释放 → ``file_selected``
恰好发射一次）。

验证命令：
    python -m pytest tests/unit/ui/test_main_window_nav_filter.py -q --timeout 60
"""

# targets: ui.main_window, ui.layout.file_selector_layout

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pytest
from PySide6.QtCore import QEvent, QObject, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QLineEdit,
    QPlainTextEdit,
    QSlider,
    QSpinBox,
    QTextEdit,
    QWidget,
)

# main_window.py 自带 _ui_root bootstrap（见文件头），但其依赖的
# components/layout 模块同样依赖该 short-path，此处补齐（同
# test_main_window.py 的约定）。
_UI_ROOT: str = str(Path(__file__).resolve().parents[3] / "sopeek" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from sopeek.ui.layout.file_selector_layout import FileSelectorLayout  # noqa: E402
from sopeek.ui.main_window import MainWindow  # noqa: E402

from tests.support.qt_helpers import drain_deferred_deletes  # noqa: E402

pytestmark = pytest.mark.unit


class _StubMicaBackground(QWidget):
    """make_mica_background 的 QWidget 替身（防 Mica 残留跨用例原生崩溃）。

    与 test_main_window.py 同款：真实 MicaMaterial 会在顶层窗口安装事件
    过滤器并创建定时器，测试销毁窗口后残留回调可能撞原生访问冲突。
    本文件断言不依赖真实 Mica 视觉，直接替换为无损替身。
    """

    def handle_window_resize(self) -> None:
        """空实现：替身无需响应窗口缩放。"""

    def handle_window_move(self) -> None:
        """空实现：替身无需响应窗口移动。"""

    def _ensure_mica_material(self) -> None:
        """空实现：替身无材质，返回 None 让调用方走守卫分支。"""

    def sync_theme(self) -> None:
        """空实现：替身无需重烘焙 Mica 主题。"""


@pytest.fixture(autouse=True)
def _stub_mica_background(monkeypatch: pytest.MonkeyPatch) -> None:
    """用普通 QWidget 替代真实 Mica 背景层 + 中和分阶段面板构建定时器。

    Mica 替身见 ``_StubMicaBackground``。``_build_panels_deferred`` 的中和
    是必需的：``_setup_content`` 以 ``QTimer.singleShot(0, ...)`` 排定面板
    构建，会在后续事件泵（pytest-qt teardown 的 processEvents）里对替身
    ``_file_pool`` 调用 ``set_section_styles`` 而报错；被延迟销毁的窗口还会
    再触发 ``_finalize_panels`` 撞已删除的 C++ 对象。本文件只验证过滤器，
    不建真实面板。
    """
    monkeypatch.setattr(
        "sopeek.ui.main_window.make_mica_background",
        lambda *a, **k: _StubMicaBackground(),
    )
    monkeypatch.setattr(MainWindow, "_build_panels_deferred", lambda self: None)


class _StubNavSelector:
    """FileSelectorLayout 导航入口替身（press / release / reset 三入口）。"""

    def __init__(self, press_result: bool = True, release_result: bool = True) -> None:
        self.press_calls: List[int] = []
        self.release_calls: List[int] = []
        self.reset_calls: int = 0
        self._press_result = press_result
        self._release_result = release_result

    def handle_nav_key_press(self, key: int) -> bool:
        """记录按压键并返回预设结果。"""
        self.press_calls.append(key)
        return self._press_result

    def handle_nav_key_release(self, key: int) -> bool:
        """记录释放键并返回预设结果。"""
        self.release_calls.append(key)
        return self._release_result

    def reset_nav_state(self) -> None:
        """记录一次激活重置调用。"""
        self.reset_calls += 1


class _StubPathSink:
    """``set_previewing_file`` 记录替身（_file_selector / _file_pool 共用）。"""

    def __init__(self) -> None:
        self.previewing_paths: List[str] = []

    def set_previewing_file(self, file_path: str) -> None:
        """记录一次预览态路径写入。"""
        self.previewing_paths.append(file_path)


class _StubPoolSink(QWidget):
    """QWidget 形态的 ``_file_pool`` 替身（记录 ``set_previewing_file``）。

    捕获守卫第 9 步会对池调用 ``pool.isAncestorOf(fw)``，故 e2e / 去重用例
    的池替身必须是真实 QWidget；不显示、不参与布局。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.previewing_paths: List[str] = []

    def set_previewing_file(self, file_path: str) -> None:
        """记录一次预览态路径写入。"""
        self.previewing_paths.append(file_path)


class _StubPreviewer:
    """统一预览器替身：可控 ``current_file_info`` 返回/抛错，记录 ``set_file``。"""

    def __init__(self, current: Any = None, raises: bool = False) -> None:
        self._current = current
        self._raises = raises
        self.set_file_calls: List[Any] = []

    def current_file_info(self) -> Any:
        """返回预设的当前文件信息；``raises=True`` 时抛 RuntimeError（对抗用例）。"""
        if self._raises:
            raise RuntimeError("current_file_info 读取失败（替身配置）")
        return self._current

    def set_file(self, file_info: Any) -> None:
        """记录一次预览加载调用。"""
        self.set_file_calls.append(file_info)


class _NoGetterPreviewer:
    """无 ``current_file_info`` 的预览器替身（仅实现 ``set_file``）。"""

    def __init__(self) -> None:
        self.set_file_calls: List[Any] = []

    def set_file(self, file_info: Any) -> None:
        """记录一次预览加载调用。"""
        self.set_file_calls.append(file_info)


@pytest.fixture
def nav_window(qapp: QApplication) -> Any:
    """MainWindow 构造工厂；用例结束后卸载过滤器并销毁全部新建窗口。"""
    windows: List[MainWindow] = []

    def _make() -> MainWindow:
        window = MainWindow()
        windows.append(window)
        return window

    yield _make

    for window in windows:
        try:
            window._uninstall_nav_key_filter()
        except RuntimeError:
            pass  # C++ 对象已销毁（destroyed 用例）：卸载已无必要
        try:
            window.deleteLater()
        except RuntimeError:
            pass
    qapp.processEvents()


def _activate(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    focus: Optional[QWidget],
) -> None:
    """打桩“主窗口激活 + 指定焦点控件”环境（无头测试无真实活动窗口）。

    Args:
        window: 待激活的 MainWindow。
        monkeypatch: pytest monkeypatch 夹具。
        focus: QApplication.focusWidget() 的返回控件（None 表示无焦点）。
    """
    monkeypatch.setattr(window, "isActiveWindow", lambda: True)
    monkeypatch.setattr(QApplication, "activeWindow", staticmethod(lambda: window))
    monkeypatch.setattr(QApplication, "activePopupWidget", staticmethod(lambda: None))
    monkeypatch.setattr(QApplication, "focusWidget", staticmethod(lambda: focus))


def _key_event(
    event_type: QEvent.Type, key: int, auto_repeat: bool = False
) -> QKeyEvent:
    """构造指定类型的方向键事件。"""
    return QKeyEvent(event_type, key, Qt.NoModifier, "", auto_repeat, 1)


def _mouse_press(point: QPointF) -> QMouseEvent:
    """构造左键按压事件（局部/全局坐标同点）。"""
    return QMouseEvent(
        QEvent.MouseButtonPress,
        point,
        point,
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )


#: Todo 4 e2e 用例的伪路径基目录（条目仅落模型，不做磁盘访问）。
_NAV_BASE_DIR: str = os.path.normpath("C:/nav_todo4")


def _nav_entry(name: str, is_dir: bool = False) -> Dict[str, Any]:
    """构造 7 键条目（``FileListModel.set_files`` 契约，Todo 4 e2e 用例用）。

    Args:
        name: 文件名。
        is_dir: 是否为目录。

    Returns:
        Dict[str, Any]: name/path/is_dir/size/modified/created/suffix 条目。
    """
    path = os.path.normpath(os.path.join(_NAV_BASE_DIR, name))
    suffix = "" if is_dir or "." not in name else name.rsplit(".", 1)[-1].lower()
    return {
        "name": name,
        "path": path,
        "is_dir": is_dir,
        "size": 0,
        "modified": "2026-01-01 00:00:00",
        "created": "2026-01-01 00:00:00",
        "suffix": suffix,
    }


class TestNavCapture:
    """捕获分支：按压 / 释放 / 自动重复 / 非方向键 / 处理器拒绝。"""

    def test_captures_press_and_release_with_plain_focus(
        self, nav_window: Callable[[], MainWindow], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(a) 窗口激活且焦点在中性控件：按压与释放均被捕获并转发给选择器。"""
        window = nav_window()
        stub = _StubNavSelector()
        window._file_selector = stub
        _activate(window, monkeypatch, window._content)

        press = _key_event(QEvent.KeyPress, Qt.Key_Right)
        press.ignore()
        assert window.eventFilter(window._content, press) is True
        assert press.isAccepted() is True
        assert stub.press_calls == [Qt.Key_Right]

        release = _key_event(QEvent.KeyRelease, Qt.Key_Right)
        release.ignore()
        assert window.eventFilter(window._content, release) is True
        assert release.isAccepted() is True
        assert stub.release_calls == [Qt.Key_Right]

    def test_captures_with_readonly_text_focus(
        self, nav_window: Callable[[], MainWindow], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(b) 焦点在只读文本预览（QTextEdit / QPlainTextEdit）：方向键仍被捕获。"""
        window = nav_window()
        stub = _StubNavSelector()
        window._file_selector = stub
        read_only_edit = QTextEdit(window)
        read_only_edit.setReadOnly(True)
        read_only_plain = QPlainTextEdit(window)
        read_only_plain.setReadOnly(True)

        for focus in (read_only_edit, read_only_plain):
            _activate(window, monkeypatch, focus)
            event = _key_event(QEvent.KeyPress, Qt.Key_Up)
            assert window.eventFilter(focus, event) is True
        assert stub.press_calls == [Qt.Key_Up, Qt.Key_Up]

    def test_release_autorepeat_not_forwarded(
        self, nav_window: Callable[[], MainWindow], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(h) 自动重复的 KeyRelease 不转发 release 处理器；普通释放才转发。"""
        window = nav_window()
        stub = _StubNavSelector()
        window._file_selector = stub
        _activate(window, monkeypatch, window._content)

        repeat = _key_event(QEvent.KeyRelease, Qt.Key_Right, auto_repeat=True)
        assert window.eventFilter(window._content, repeat) is False
        assert stub.release_calls == []

        normal = _key_event(QEvent.KeyRelease, Qt.Key_Right, auto_repeat=False)
        assert window.eventFilter(window._content, normal) is True
        assert stub.release_calls == [Qt.Key_Right]

    def test_non_arrow_key_not_captured(
        self, nav_window: Callable[[], MainWindow], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """异常输入：非方向键不被捕获、不调用选择器（Space 等保持原语义）。"""
        window = nav_window()
        stub = _StubNavSelector()
        window._file_selector = stub
        _activate(window, monkeypatch, window._content)

        for key in (Qt.Key_Space, Qt.Key_1, Qt.Key_QuoteLeft, Qt.Key_A):
            assert (
                window.eventFilter(window._content, _key_event(QEvent.KeyPress, key))
                is False
            )
        assert stub.press_calls == []

    def test_press_handler_false_means_not_captured(
        self, nav_window: Callable[[], MainWindow], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """误导性成功守卫：处理器返回 False 时不得报告捕获（落到鼠标守卫）。"""
        window = nav_window()
        stub = _StubNavSelector(press_result=False, release_result=False)
        window._file_selector = stub
        _activate(window, monkeypatch, window._content)

        press = _key_event(QEvent.KeyPress, Qt.Key_Left)
        press.ignore()
        assert window.eventFilter(window._content, press) is False
        assert press.isAccepted() is False
        release = _key_event(QEvent.KeyRelease, Qt.Key_Left)
        assert window.eventFilter(window._content, release) is False
        assert stub.press_calls == [Qt.Key_Left]
        assert stub.release_calls == [Qt.Key_Left]

    def test_none_selector_does_not_raise(
        self, nav_window: Callable[[], MainWindow], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """失败路径：_file_selector 为 None 时返回鼠标分支结果且不抛异常。"""
        window = nav_window()
        window._file_selector = None
        _activate(window, monkeypatch, window._content)
        event = _key_event(QEvent.KeyPress, Qt.Key_Right)
        assert window.eventFilter(window._content, event) is False


class TestNavShouldCaptureGuards:
    """_nav_should_capture 的守卫顺序（c)-(g) 及补充：焦点控件类别。"""

    def test_no_capture_editable_text_and_line_edit(
        self, nav_window: Callable[[], MainWindow], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(c) 焦点在可编辑文本框 / 单行编辑框：不捕获。"""
        window = nav_window()
        stub = _StubNavSelector()
        window._file_selector = stub
        editable_edit = QTextEdit(window)  # 默认可编辑
        editable_plain = QPlainTextEdit(window)  # 默认可编辑
        line_edit = QLineEdit(window)

        for focus in (editable_edit, editable_plain, line_edit):
            _activate(window, monkeypatch, focus)
            assert (
                window.eventFilter(focus, _key_event(QEvent.KeyPress, Qt.Key_Right))
                is False
            )
        assert stub.press_calls == []

    def test_no_capture_spinbox_combo_slider(
        self, nav_window: Callable[[], MainWindow], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """守卫 8：焦点在自旋框 / 下拉框 / 滑块：不捕获。"""
        window = nav_window()
        stub = _StubNavSelector()
        window._file_selector = stub
        for focus in (QSpinBox(window), QComboBox(window), QSlider(window)):
            _activate(window, monkeypatch, focus)
            assert (
                window.eventFilter(focus, _key_event(QEvent.KeyPress, Qt.Key_Down))
                is False
            )
        assert stub.press_calls == []

    def test_no_capture_pool_focus(
        self, nav_window: Callable[[], MainWindow], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(d) 焦点在储存池控件或其子控件：不捕获（池内导航优先）。"""
        window = nav_window()
        stub = _StubNavSelector()
        window._file_selector = stub
        pool = QWidget(window)
        pool_child = QWidget(pool)
        window._file_pool = pool

        for focus in (pool, pool_child):
            _activate(window, monkeypatch, focus)
            assert (
                window.eventFilter(focus, _key_event(QEvent.KeyPress, Qt.Key_Down))
                is False
            )
        assert stub.press_calls == []

    def test_no_capture_when_inactive_or_another_active_window(
        self, nav_window: Callable[[], MainWindow], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(e) isActiveWindow False 或 activeWindow 非本窗口：不捕获。"""
        window = nav_window()
        stub = _StubNavSelector()
        window._file_selector = stub

        monkeypatch.setattr(QApplication, "activePopupWidget", staticmethod(lambda: None))
        monkeypatch.setattr(QApplication, "focusWidget", staticmethod(lambda: window._content))

        # 主窗口自身报告未激活
        monkeypatch.setattr(window, "isActiveWindow", lambda: False)
        monkeypatch.setattr(QApplication, "activeWindow", staticmethod(lambda: window))
        assert (
            window.eventFilter(
                window._content, _key_event(QEvent.KeyPress, Qt.Key_Right)
            )
            is False
        )

        # 报告激活但 activeWindow 指向他处（兜底判定）
        monkeypatch.setattr(window, "isActiveWindow", lambda: True)
        monkeypatch.setattr(QApplication, "activeWindow", staticmethod(lambda: None))
        assert (
            window.eventFilter(
                window._content, _key_event(QEvent.KeyPress, Qt.Key_Right)
            )
            is False
        )
        assert stub.press_calls == []

    def test_no_capture_with_active_popup(
        self, nav_window: Callable[[], MainWindow], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(f) 存在活动弹出窗口：不捕获（弹窗自行消费方向键）。"""
        window = nav_window()
        stub = _StubNavSelector()
        window._file_selector = stub
        _activate(window, monkeypatch, window._content)
        popup = QWidget(window)
        monkeypatch.setattr(QApplication, "activePopupWidget", staticmethod(lambda: popup))
        assert (
            window.eventFilter(window._content, _key_event(QEvent.KeyPress, Qt.Key_Right))
            is False
        )
        assert stub.press_calls == []

    def test_no_capture_when_focus_widget_none(
        self, nav_window: Callable[[], MainWindow], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(g) 无焦点控件：不捕获。"""
        window = nav_window()
        stub = _StubNavSelector()
        window._file_selector = stub
        _activate(window, monkeypatch, None)
        assert (
            window.eventFilter(window._content, _key_event(QEvent.KeyPress, Qt.Key_Right))
            is False
        )
        assert stub.press_calls == []

    def test_no_capture_foreign_window_focus(
        self, nav_window: Callable[[], MainWindow], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """守卫 5：焦点控件属于其它窗口：不捕获（不为别的窗口消费按键）。"""
        window = nav_window()
        stub = _StubNavSelector()
        window._file_selector = stub
        other = QWidget()
        _activate(window, monkeypatch, other)
        assert (
            window.eventFilter(other, _key_event(QEvent.KeyPress, Qt.Key_Right))
            is False
        )
        assert stub.press_calls == []
        other.deleteLater()


class TestMouseBranchRegression:
    """回归守卫：既有标题栏拖拽鼠标分支未被方向键分支旁路。"""

    def test_mouse_titlebar_branch_preserved(
        self, nav_window: Callable[[], MainWindow], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(i) 标题栏上的左键按压仍触达 startSystemMove 并返回 True。"""
        window = nav_window()
        header = QWidget()
        header.setObjectName("TitleBar")
        moves: List[bool] = []

        class _Handle:
            """windowHandle 替身：记录 startSystemMove 调用。"""

            def startSystemMove(self) -> bool:
                """记录一次拖拽移动请求。"""
                moves.append(True)
                return True

        monkeypatch.setattr(window, "windowHandle", lambda: _Handle())
        event = _mouse_press(QPointF(5.0, 5.0))
        assert window.eventFilter(header, event) is True
        assert moves == [True]
        header.deleteLater()

    def test_mouse_non_widget_obj_does_not_raise(
        self, nav_window: Callable[[], MainWindow], qapp: QApplication
    ) -> None:
        """(i) 应用级过滤下非 QWidget 接收对象：负向守卫兜底，不抛异常。"""
        window = nav_window()
        event = _mouse_press(QPointF(5.0, 5.0))
        assert window.eventFilter(qapp, event) is False
        assert (
            window.eventFilter(qapp, QEvent(QEvent.User)) is False
        )


class TestActivationReset:
    """changeEvent：失活时重置选择器导航状态（无 wedged 状态）。"""

    def test_change_event_activation_reset(
        self, nav_window: Callable[[], MainWindow], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(j) 失活 ActivationChange 调 reset_nav_state；激活/其它事件不调。"""
        window = nav_window()
        stub = _StubNavSelector()
        window._file_selector = stub

        monkeypatch.setattr(window, "isActiveWindow", lambda: False)
        window.changeEvent(QEvent(QEvent.ActivationChange))
        assert stub.reset_calls == 1

        monkeypatch.setattr(window, "isActiveWindow", lambda: True)
        window.changeEvent(QEvent(QEvent.ActivationChange))
        assert stub.reset_calls == 1

        monkeypatch.setattr(window, "isActiveWindow", lambda: False)
        window.changeEvent(QEvent(QEvent.WindowTitleChange))
        assert stub.reset_calls == 1

        # _file_selector 未构建：不抛异常
        window._file_selector = None
        window.changeEvent(QEvent(QEvent.ActivationChange))


class TestInstallLifecycle:
    """安装 / 卸载：幂等与 destroyed 兜底（全局 QApplication 无残留）。"""

    def test_install_idempotent_and_uninstall_removes(
        self,
        nav_window: Callable[[], MainWindow],
        qapp: QApplication,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """(k) 构造即安装；重复安装不再调 installEventFilter；卸载调 remove。"""
        window = nav_window()
        assert window._nav_filter_installed is True

        install_calls: List[Any] = []
        real_install = qapp.installEventFilter

        def _spy_install(obj: QObject) -> None:
            install_calls.append(obj)
            real_install(obj)

        monkeypatch.setattr(qapp, "installEventFilter", _spy_install)
        window._install_nav_key_filter()
        window._install_nav_key_filter()
        assert install_calls == []
        assert window._nav_filter_installed is True

        remove_calls: List[Any] = []
        real_remove = qapp.removeEventFilter

        def _spy_remove(obj: QObject) -> None:
            remove_calls.append(obj)
            real_remove(obj)

        monkeypatch.setattr(qapp, "removeEventFilter", _spy_remove)
        window._uninstall_nav_key_filter()
        assert window._nav_filter_installed is False
        assert remove_calls == [window]

        # 重复卸载：不重复移除
        window._uninstall_nav_key_filter()
        assert remove_calls == [window]

    def test_install_noop_when_no_qapplication(
        self, nav_window: Callable[[], MainWindow], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """失败路径：QApplication.instance() 为 None 时安装是无操作且无异常。"""
        window = nav_window()
        window._uninstall_nav_key_filter()
        assert window._nav_filter_installed is False

        monkeypatch.setattr(QApplication, "instance", staticmethod(lambda: None))
        window._install_nav_key_filter()
        assert window._nav_filter_installed is False

    def test_second_window_destroyed_leaves_no_app_filter(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """生命周期：第二个 MainWindow 销毁（destroyed 路径）触发兜底卸载。

        本用例不依赖 closeEvent：直接 deleteLater + 显式派发 DeferredDelete，
        断言 removeEventFilter 被以该窗口实参调用且安装标记已清零。
        """
        first = MainWindow()
        try:
            second = MainWindow()
            assert second._nav_filter_installed is True

            remove_calls: List[Any] = []
            real_remove = qapp.removeEventFilter

            def _spy_remove(obj: QObject) -> None:
                remove_calls.append(obj)
                real_remove(obj)

            monkeypatch.setattr(qapp, "removeEventFilter", _spy_remove)
            second.deleteLater()
            drain_deferred_deletes(qapp)

            assert second in remove_calls
            assert second._nav_filter_installed is False
        finally:
            try:
                first._uninstall_nav_key_filter()
            except RuntimeError:
                pass
            try:
                first.deleteLater()
            except RuntimeError:
                pass
            qapp.processEvents()


def _hook_dedupe(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    previewer: Any,
) -> Tuple[_StubPathSink, _StubPathSink, List[dict]]:
    """装配 ``_on_file_selected`` 去重用例环境（Todo 4 验收 (a)-(d)）。

    ``_file_selector`` / ``_file_pool`` 换成 ``_StubPathSink``（只记录预览态
    写入）；``_previewer`` 换成传入替身；``_show_preview`` 换成本实例级记录器
    并透传真实实现（顺带验证其内部 None 守卫的安全性）。

    Args:
        window: 已构造的 MainWindow。
        monkeypatch: pytest monkeypatch 夹具。
        previewer: ``_previewer`` 替身（``_StubPreviewer`` /
            ``_NoGetterPreviewer`` / ``None``）。

    Returns:
        Tuple: (selector 替身, pool 替身, ``_show_preview`` 入参记录列表)。
    """
    selector = _StubPathSink()
    pool = _StubPoolSink(window)
    window._file_selector = selector
    window._file_pool = pool
    window._previewer = previewer
    show_calls: List[dict] = []
    real_show = MainWindow._show_preview

    def _spy_show(file_info: dict) -> None:
        """记录入参后透传真实 ``_show_preview``（其 None 守卫须安全）。"""
        show_calls.append(file_info)
        real_show(window, file_info)

    monkeypatch.setattr(window, "_show_preview", _spy_show)
    return selector, pool, show_calls


class TestOnFileSelectedDedupe:
    """验收 (a)-(d)：``_on_file_selected`` 预览防重复加载。"""

    _FILE_INFO: Dict[str, Any] = {
        "path": os.path.normpath("C:/nav_todo4/a.txt"),
        "suffix": "txt",
    }

    def test_same_path_does_not_reload(
        self, nav_window: Callable[[], MainWindow], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(a) 预览器当前文件与本次选中同路径：早退，不下发 _show_preview。"""
        window = nav_window()
        previewer = _StubPreviewer({"path": self._FILE_INFO["path"]})
        selector, pool, show_calls = _hook_dedupe(window, monkeypatch, previewer)

        window._on_file_selected(self._FILE_INFO)

        assert show_calls == []
        assert previewer.set_file_calls == []
        # set_previewing_file 同步先于去重执行（选择器 + 池）
        assert selector.previewing_paths == [self._FILE_INFO["path"]]
        assert pool.previewing_paths == [self._FILE_INFO["path"]]

        # 规范化后相等（Windows 大小写 / 分隔符不敏感）同样拦住
        window._previewer = _StubPreviewer({"path": r"c:/NAV_TODO4/a.TXT"})
        window._on_file_selected(self._FILE_INFO)
        assert show_calls == []
        assert window._previewer.set_file_calls == []

    def test_different_path_reloads(
        self, nav_window: Callable[[], MainWindow], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(b) 当前文件路径不同：照常下发 _show_preview / set_file。"""
        window = nav_window()
        previewer = _StubPreviewer({"path": os.path.normpath("C:/nav_todo4/other.txt")})
        _, _, show_calls = _hook_dedupe(window, monkeypatch, previewer)

        window._on_file_selected(self._FILE_INFO)

        assert show_calls == [self._FILE_INFO]
        assert previewer.set_file_calls == [self._FILE_INFO]

    def test_none_or_empty_current_reloads(
        self, nav_window: Callable[[], MainWindow], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(c) current_file_info() 返回 None / 空路径：照常刷新预览。"""
        window = nav_window()
        previewer = _StubPreviewer(None)
        _, _, show_calls = _hook_dedupe(window, monkeypatch, previewer)

        window._on_file_selected(self._FILE_INFO)
        assert show_calls == [self._FILE_INFO]

        window._previewer = _StubPreviewer({"path": ""})
        window._on_file_selected(self._FILE_INFO)
        assert show_calls == [self._FILE_INFO, self._FILE_INFO]

    def test_missing_getter_and_none_previewer(
        self, nav_window: Callable[[], MainWindow], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(d) 无 current_file_info / _previewer 为 None：不抛异常且照常刷新。"""
        window = nav_window()
        no_getter = _NoGetterPreviewer()
        _, _, show_calls = _hook_dedupe(window, monkeypatch, no_getter)

        window._on_file_selected(self._FILE_INFO)
        assert show_calls == [self._FILE_INFO]
        assert no_getter.set_file_calls == [self._FILE_INFO]

        # _previewer 为 None：getter 读取被守卫跳过，真实 _show_preview 的
        # None 守卫兜底（预览器与信息面板都不存在）
        window._previewer = None
        window._on_file_selected(self._FILE_INFO)
        assert show_calls == [self._FILE_INFO, self._FILE_INFO]

    def test_getter_exception_treated_as_no_current(
        self, nav_window: Callable[[], MainWindow], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """对抗：current_file_info() 抛错 → 按无当前文件处理，继续刷新预览。"""
        window = nav_window()
        previewer = _StubPreviewer(raises=True)
        _, _, show_calls = _hook_dedupe(window, monkeypatch, previewer)

        window._on_file_selected(self._FILE_INFO)

        assert show_calls == [self._FILE_INFO]
        assert previewer.set_file_calls == [self._FILE_INFO]


class TestEndToEndArrowWiring:
    """验收 (e)：eventFilter → 真实 FileSelectorLayout → file_selected 恰好一次。"""

    def test_right_press_release_advances_real_selector_and_emits_once(
        self,
        nav_window: Callable[[], MainWindow],
        qapp: QApplication,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """(e) 真实选择器接线：按压移动光标（不发射），释放发射一次且主窗口链跑完。"""
        window = nav_window()
        selector = FileSelectorLayout()
        try:
            selector._file_model.set_files(
                [
                    _nav_entry("folder", True),
                    _nav_entry("a.txt"),
                    _nav_entry("b.txt"),
                    _nav_entry("c.txt"),
                ]
            )
            selector._current_path = _NAV_BASE_DIR
            selector._view_mode = "card"
            selector._grid_cols = 0
            anchor = _nav_entry("a.txt")["path"]
            target = _nav_entry("b.txt")["path"]
            selector.set_previewing_file(anchor)

            pool = _StubPoolSink(window)
            window._file_selector = selector
            window._file_pool = pool
            window._previewer = None

            # 与 _finalize_panels 同款接线：选择器 file_selected → 主窗口处理链
            selector.file_selected.connect(window._on_file_selected)
            emitted: List[dict] = []
            selector.file_selected.connect(lambda info: emitted.append(info))

            _activate(window, monkeypatch, window._content)

            press = _key_event(QEvent.KeyPress, Qt.Key_Right)
            press.ignore()
            assert window.eventFilter(window._content, press) is True
            assert press.isAccepted() is True
            assert selector._nav_cursor_path == target
            assert selector._previewing_file_path == target
            assert emitted == []  # 按压只移动高亮，预览不加载

            release = _key_event(QEvent.KeyRelease, Qt.Key_Right)
            release.ignore()
            assert window.eventFilter(window._content, release) is True
            assert release.isAccepted() is True
            assert len(emitted) == 1
            assert emitted[0]["path"] == target
            assert pool.previewing_paths == [target]  # _on_file_selected 链已同步跑完
        finally:
            selector.deleteLater()
            qapp.processEvents()
