# -*- coding: utf-8 -*-
"""窗口级模态守卫（``components.modal_guard``）单元测试。

覆盖验收点：

1. 模态弹窗显示期间，宿主窗口的内容控件点击/键盘事件被吞掉；
2. 弹窗自身的控件正常响应（不被自己的模态拦截）；
3. 带 ``sp_modal_passthrough`` 属性的控件（标题栏 ✕）在模态期间仍可点击；
4. 嵌套作用域：内层弹窗关闭后，外层仍遮挡宿主窗口；
5. 弹窗关闭/销毁后自动解除遮挡（不会把界面永久锁死）；
6. ``pop_for`` / ``pop_owner`` / ``clear`` 的幂等性。

验证命令：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/unit/ui/components/test_modal_guard.py -v
"""

# targets: ui.components.modal_guard

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, List

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget

# 组件模块内部使用短路径导入（from theme import tm），
# 要求 sopeek/ui 位于 sys.path；与 test_styled_dialog.py 一致。
_UI_ROOT: str = str(Path(__file__).resolve().parents[4] / "sopeek" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from tests.support.qt_helpers import drain_deferred_deletes, safe_teardown  # noqa: E402

from sopeek.ui.components.modal_guard import (  # noqa: E402
    MODAL_PASSTHROUGH_PROPERTY,
    ModalGuard,
)

pytestmark = pytest.mark.unit


def _make_dialog(owner: QWidget) -> QWidget:
    """构造一个 owned 顶层弹窗（``Qt.Dialog`` + 无边框）。

    Args:
        owner: 宿主窗口。

    Returns:
        QWidget: 已 ``show()`` 的弹窗实例。
    """
    dialog = QWidget(owner)
    dialog.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
    dialog.resize(200, 120)
    dialog.show()
    return dialog


@pytest.fixture()
def guard(qapp: QApplication):
    """安装一个独立的 ``ModalGuard``（不污染全局单例）。

    Yields:
        ModalGuard: 已安装到 QApplication 的守卫实例。
    """
    instance = ModalGuard()
    qapp.installEventFilter(instance)
    try:
        yield instance
    finally:
        instance.clear()
        try:
            qapp.removeEventFilter(instance)
        except RuntimeError:
            pass


@pytest.fixture()
def host(qapp: QApplication):
    """宿主窗口：含一个内容按钮与一个带放行属性的「✕」按钮。

    Yields:
        tuple: ``(window, content_button, close_button, hits)``。
    """
    window = QWidget()
    window.resize(400, 300)
    layout = QVBoxLayout(window)
    content = QPushButton("筛选")
    content.setFixedSize(120, 40)
    close_btn = QPushButton("✕")
    close_btn.setFixedSize(32, 32)
    close_btn.setProperty(MODAL_PASSTHROUGH_PROPERTY, True)
    layout.addWidget(content)
    layout.addWidget(close_btn)
    window.show()

    hits: List[str] = []
    content.clicked.connect(lambda: hits.append("content"))
    close_btn.clicked.connect(lambda: hits.append("close"))
    qapp.processEvents()
    try:
        yield window, content, close_btn, hits
    finally:
        safe_teardown(window)
        drain_deferred_deletes(qapp)


class TestBlocking:
    """模态期间宿主窗口不可交互。"""

    def test_content_click_blocked(self, qapp: QApplication, guard: ModalGuard, host) -> None:
        """宿主内容按钮的点击被吞掉（不触发 clicked）。"""
        window, content, _close_btn, hits = host
        dialog = _make_dialog(window)
        guard.push(dialog, window)
        qapp.processEvents()

        QTest.mouseClick(content, Qt.LeftButton)
        qapp.processEvents()

        assert hits == [], "模态期间宿主内容按钮不应响应点击"
        safe_teardown(dialog)

    def test_keyboard_blocked(self, qapp: QApplication, guard: ModalGuard, host) -> None:
        """宿主窗口的键盘事件被吞掉。"""
        window, _content, _close_btn, _hits = host
        dialog = _make_dialog(window)
        guard.push(dialog, window)
        qapp.processEvents()

        received: List[int] = []
        original = window.keyPressEvent

        def _spy(event) -> None:
            received.append(event.key())
            original(event)

        window.keyPressEvent = _spy  # type: ignore[method-assign]
        QTest.keyClick(window, Qt.Key_Right)
        qapp.processEvents()

        assert received == [], "模态期间宿主窗口不应收到键盘事件"
        safe_teardown(dialog)

    def test_dialog_own_widget_still_clickable(
        self, qapp: QApplication, guard: ModalGuard, host
    ) -> None:
        """弹窗自身的按钮不受自己的模态影响。"""
        window, _content, _close_btn, _hits = host
        dialog = _make_dialog(window)
        layout = QVBoxLayout(dialog)
        inside = QPushButton("确定")
        inside.setFixedSize(80, 30)
        layout.addWidget(inside)
        dialog_hits: List[str] = []
        inside.clicked.connect(lambda: dialog_hits.append("ok"))
        guard.push(dialog, window)
        qapp.processEvents()

        QTest.mouseClick(inside, Qt.LeftButton)
        qapp.processEvents()

        assert dialog_hits == ["ok"], "弹窗自身按钮必须可点击"
        safe_teardown(dialog)

    def test_passthrough_close_button_allowed(
        self, qapp: QApplication, guard: ModalGuard, host
    ) -> None:
        """带放行属性的 ✕ 在模态期间仍可点击（用户能关主窗）。"""
        window, _content, close_btn, hits = host
        dialog = _make_dialog(window)
        guard.push(dialog, window)
        qapp.processEvents()

        QTest.mouseClick(close_btn, Qt.LeftButton)
        qapp.processEvents()

        assert hits == ["close"], "带 sp_modal_passthrough 的 ✕ 必须放行"
        safe_teardown(dialog)

    def test_passthrough_inherited_by_child_widget(
        self, qapp: QApplication, guard: ModalGuard, host
    ) -> None:
        """放行属性沿祖先链继承（✕ 内部子控件同样放行）。"""
        window, _content, close_btn, hits = host
        dialog = _make_dialog(window)
        guard.push(dialog, window)
        qapp.processEvents()

        # 直接向按钮投递鼠标事件（模拟点在按钮内部区域）
        QTest.mouseClick(close_btn, Qt.LeftButton, pos=close_btn.rect().center())
        qapp.processEvents()

        assert hits == ["close"]
        safe_teardown(dialog)


class TestScopes:
    """作用域的嵌套与解除。"""

    def test_is_blocked_reflects_scope(
        self, qapp: QApplication, guard: ModalGuard, host
    ) -> None:
        """push 后 is_blocked 为真；关闭弹窗后自动变假。"""
        window, _content, _close_btn, _hits = host
        dialog = _make_dialog(window)
        assert guard.is_blocked(window) is False

        guard.push(dialog, window)
        qapp.processEvents()
        assert guard.is_blocked(window) is True

        dialog.close()
        qapp.processEvents()
        # 弹窗已不可见：prune 后作用域失效
        assert guard.is_blocked(window) is False

    def test_nested_inner_close_keeps_outer_blocking(
        self, qapp: QApplication, guard: ModalGuard, host
    ) -> None:
        """内层弹窗关闭后，外层弹窗仍遮挡宿主窗口。"""
        window, content, _close_btn, hits = host
        outer = _make_dialog(window)
        guard.push(outer, window)
        inner = _make_dialog(outer)
        guard.push(inner, outer)
        qapp.processEvents()

        assert guard.is_blocked(window) is True
        assert guard.is_blocked(outer) is True

        inner.close()
        qapp.processEvents()

        assert guard.is_blocked(window) is True, "内层关闭不应解除对主窗口的遮挡"
        QTest.mouseClick(content, Qt.LeftButton)
        qapp.processEvents()
        assert hits == [], "外层仍应挡住宿主内容按钮"

        outer.close()
        qapp.processEvents()
        assert guard.is_blocked(window) is False

    def test_pop_for_is_idempotent(self, qapp: QApplication, guard: ModalGuard, host) -> None:
        """pop_for 重复调用不抛异常且效果幂等。"""
        window, _content, _close_btn, _hits = host
        dialog = _make_dialog(window)
        guard.push(dialog, window)

        guard.pop_for(dialog)
        guard.pop_for(dialog)
        assert guard.is_blocked(window) is False
        safe_teardown(dialog)

    def test_pop_owner_removes_only_that_host(
        self, qapp: QApplication, guard: ModalGuard, host
    ) -> None:
        """pop_owner 只移除指定宿主的作用域（其它作用域保留）。"""
        window, _content, _close_btn, _hits = host
        other = QWidget()
        other.resize(200, 150)
        other.show()

        first = _make_dialog(window)
        second = _make_dialog(other)
        guard.push(first, window)
        guard.push(second, other)
        assert guard.active_dialog is second

        # 移除其它宿主：second 的作用域仍在，窗口仍被遮挡
        guard.pop_owner(QWidget())
        assert guard.active_dialog is second

        guard.pop_owner(window)
        guard.pop_owner(other)
        assert guard.active_dialog is None
        assert guard.is_blocked(window) is False
        assert guard.is_blocked(other) is False
        safe_teardown(first)
        safe_teardown(second)
        safe_teardown(other)

    def test_clear_removes_all(self, qapp: QApplication, guard: ModalGuard, host) -> None:
        """clear 清空全部作用域（退出兜底）。"""
        window, _content, _close_btn, _hits = host
        dialog = _make_dialog(window)
        guard.push(dialog, window)

        guard.clear()

        assert guard.is_blocked(window) is False
        assert guard.active_dialog is None
        safe_teardown(dialog)

    def test_destroyed_dialog_pruned(
        self, qapp: QApplication, guard: ModalGuard, host
    ) -> None:
        """弹窗被销毁后作用域自动剔除，界面不会被永久锁死。"""
        window, _content, _close_btn, _hits = host
        dialog = _make_dialog(window)
        guard.push(dialog, window)

        dialog.deleteLater()
        drain_deferred_deletes(qapp)

        assert guard.is_blocked(window) is False

    def test_push_same_dialog_twice_keeps_single_scope(
        self, qapp: QApplication, guard: ModalGuard, host
    ) -> None:
        """同一弹窗重复 push 不产生重复作用域。"""
        window, _content, _close_btn, _hits = host
        dialog = _make_dialog(window)
        guard.push(dialog, window)
        guard.push(dialog, window)

        guard.pop_for(dialog)

        assert guard.is_blocked(window) is False
        safe_teardown(dialog)

    def test_unrelated_window_not_blocked(
        self, qapp: QApplication, guard: ModalGuard, host
    ) -> None:
        """未被遮挡的其它窗口不受影响。"""
        window, _content, _close_btn, _hits = host
        unrelated = QWidget()
        unrelated.resize(200, 150)
        layout = QVBoxLayout(unrelated)
        button = QPushButton("ok")
        button.setFixedSize(60, 30)
        layout.addWidget(button)
        unrelated.show()
        clicks: List[str] = []
        button.clicked.connect(lambda: clicks.append("ok"))

        dialog = _make_dialog(window)
        guard.push(dialog, window)
        qapp.processEvents()

        QTest.mouseClick(button, Qt.LeftButton)
        qapp.processEvents()

        assert clicks == ["ok"], "无关窗口不应被模态拦截"
        safe_teardown(dialog)
        safe_teardown(unrelated)


class TestEventTypeCoverage:
    """拦截的事件类型覆盖鼠标 / 键盘 / 滚轮 / 上下文菜单。"""

    @pytest.mark.parametrize(
        "event_type",
        [
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.MouseButtonDblClick,
            QEvent.Type.Wheel,
            QEvent.Type.KeyPress,
            QEvent.Type.KeyRelease,
            QEvent.Type.ContextMenu,
        ],
    )
    def test_event_type_intercepted(
        self, qapp: QApplication, guard: ModalGuard, host, event_type: Any
    ) -> None:
        """被遮挡窗口上的指定事件类型一律消费。"""
        window, content, _close_btn, _hits = host
        dialog = _make_dialog(window)
        guard.push(dialog, window)
        qapp.processEvents()

        event = QEvent(event_type)
        assert guard.eventFilter(content, event) is True
        safe_teardown(dialog)

    @pytest.mark.parametrize(
        "event_type",
        [QEvent.Type.MouseMove, QEvent.Type.Enter, QEvent.Type.Leave],
    )
    def test_hover_events_pass(
        self, qapp: QApplication, guard: ModalGuard, host, event_type: Any
    ) -> None:
        """悬停类事件放行（保留光标反馈，避免 hover 卡死）。"""
        window, content, _close_btn, _hits = host
        dialog = _make_dialog(window)
        guard.push(dialog, window)
        qapp.processEvents()

        assert guard.eventFilter(content, QEvent(event_type)) is False
        safe_teardown(dialog)

    def test_no_scope_never_intercepts(
        self, qapp: QApplication, guard: ModalGuard, host
    ) -> None:
        """无作用域时一律放行。"""
        _window, content, _close_btn, _hits = host
        assert guard.eventFilter(content, QEvent(QEvent.Type.MouseButtonPress)) is False

    def test_host_interactive_again_after_dialog_closed(
        self, qapp: QApplication, guard: ModalGuard, host
    ) -> None:
        """弹窗关闭后宿主立即恢复交互（无"幽灵模态"窗口期）。

        回归：退场动画期间弹窗仍 ``isVisible()``，若只按可见性判断，用户
        关掉弹窗后立刻点击会被吞掉约 180ms。
        """
        window, content, _close_btn, hits = host
        dialog = _make_dialog(window)
        guard.push(dialog, window)
        qapp.processEvents()
        assert guard.is_blocked(window) is True

        dialog.close()
        qapp.processEvents()

        assert guard.is_blocked(window) is False
        QTest.mouseClick(content, Qt.LeftButton)
        qapp.processEvents()
        assert hits == ["content"], "弹窗关闭后宿主内容按钮必须立即可点"
