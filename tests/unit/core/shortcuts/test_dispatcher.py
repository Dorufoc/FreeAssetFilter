# -*- coding: utf-8 -*-
"""快捷键派发器测试（离屏 Qt）。

覆盖：

* 区域栈查表顺序（当前区域 → app 回落）；
* 输入框守卫（无命令修饰键一律放行）；
* 上下文阻断（QMenu / StyledDialog / 抽屉 / 浮动面板）；
* 长按状态机（短按保持、长按回滚）；
* ``handler`` 返回 ``False`` 时继续向下层查找；
* ``Escape`` 消费链逐级短路。

验证命令：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/unit/core/shortcuts/test_dispatcher.py -v
"""

from __future__ import annotations

from typing import Any, List

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget

from sopeek.core.shortcuts.dispatcher import (
    BindingTable,
    ShortcutDispatcher,
    reset_dispatcher_for_tests,
)
from sopeek.core.shortcuts.handlers import HandlerRegistry
from sopeek.core.shortcuts.registry import ActionSpec

pytestmark = pytest.mark.unit


def _press(key: int, mods: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier) -> QKeyEvent:
    """构造一次按键按下事件。"""
    return QKeyEvent(QEvent.Type.KeyPress, key, mods)


def _release(
    key: int, mods: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier
) -> QKeyEvent:
    """构造一次按键释放事件。"""
    return QKeyEvent(QEvent.Type.KeyRelease, key, mods)


class _Harness:
    """把派发器与一组可断言的 handler 装在一起。"""

    def __init__(self) -> None:
        self.calls: List[str] = []
        self.table = BindingTable()
        self.handlers = HandlerRegistry()
        self.dispatcher = ShortcutDispatcher(self.table, self.handlers)

    def register(self, action_id: str) -> None:
        """登记一个记录调用次数的 handler。"""
        self.handlers.register(
            action_id, lambda a=action_id: self.calls.append(a), owner=self
        )

    def press(self, key: int, mods: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier) -> bool:
        """派发一次按下事件，返回是否被消费。"""
        return self.dispatcher.eventFilter(None, _press(key, mods))

    def release(
        self, key: int, mods: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier
    ) -> bool:
        """派发一次释放事件，返回是否被消费。"""
        return self.dispatcher.eventFilter(None, _release(key, mods))


@pytest.fixture(autouse=True)
def _clean_dispatcher(qapp: Any):
    """每个用例前后重置全局单例、弹层计数与焦点，避免状态污染。

    三类残留都会直接改变派发结果：

    - ``QApplication.focusWidget()`` → 影响 ``_in_text_input()`` 判定；
    - ``styled_dialog._live_dialogs`` → 影响上下文阻断；
    - 抽屉 / 浮动面板登记表 → 同上。
    """
    _purge_shortcut_state(qapp)
    yield
    _purge_shortcut_state(qapp)


def _purge_shortcut_state(qapp: Any) -> None:
    """清空快捷键相关的全局残留状态。"""
    reset_dispatcher_for_tests()

    # 弹窗存活表
    try:
        from sopeek.ui.components import styled_dialog as _sd

        _sd._live_dialogs.clear()
    except Exception:  # noqa: BLE001 - 组件缺失时跳过
        pass

    # 抽屉 / 浮动面板登记表
    try:
        from sopeek.ui.components import styled_drawer as _dr

        _dr._open_drawers.clear()
    except Exception:  # noqa: BLE001
        pass
    try:
        from sopeek.ui.components import styled_floating_panel as _fp

        _fp._open_panels.clear()
    except Exception:  # noqa: BLE001
        pass

    # 焦点：先清当前焦点控件，再处理挂起事件
    try:
        widget = QApplication.focusWidget()
        if widget is not None:
            widget.clearFocus()
    except RuntimeError:
        pass
    qapp.processEvents()


# ── 基础派发 ─────────────────────────────────────────────────────────


def test_region_lookup_hits_handler(qapp: Any) -> None:
    """区域内的动作能被派发并消费事件。"""
    h = _Harness()
    h.register("selector.refresh")
    h.dispatcher.replace_region("selector")
    assert h.press(Qt.Key.Key_H, Qt.KeyboardModifier.ControlModifier) is True
    assert h.calls == ["selector.refresh"]


def test_unknown_key_not_consumed(qapp: Any) -> None:
    """未登记的键不被消费（放行给控件）。"""
    h = _Harness()
    h.register("selector.refresh")
    h.dispatcher.replace_region("selector")
    assert h.press(Qt.Key.Key_F9) is False
    assert h.calls == []


def test_no_handler_not_consumed(qapp: Any) -> None:
    """注册了键位但没登记 handler 时不消费。"""
    h = _Harness()
    h.dispatcher.replace_region("selector")
    assert h.press(Qt.Key.Key_H, Qt.KeyboardModifier.ControlModifier) is False


def test_app_fallback(qapp: Any) -> None:
    """具体区域无绑定时回落到 app 区域。"""
    h = _Harness()
    h.register("nav.next_zone_f6")
    h.dispatcher.replace_region("preview.image")
    assert h.press(Qt.Key.Key_F6) is True
    assert h.calls == ["nav.next_zone_f6"]


def test_ctrl_arrow_falls_back_to_app_nav_in_selector(qapp: Any) -> None:
    """列表内没有 Ctrl+方向键绑定：回落 app 执行焦点区切换。"""
    h = _Harness()
    h.register("nav.prev_zone")
    h.dispatcher.replace_region("selector")
    assert h.press(Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier) is True
    assert h.calls == ["nav.prev_zone"]


def test_alt_arrow_hits_selector_batch(qapp: Any) -> None:
    """批量选择改绑后，列表内 Alt+方向键命中批量动作。"""
    h = _Harness()
    h.register("selector.batch_left")
    h.dispatcher.replace_region("selector")
    assert h.press(Qt.Key.Key_Left, Qt.KeyboardModifier.AltModifier) is True
    assert h.calls == ["selector.batch_left"]


def test_region_takes_priority_over_app(qapp: Any) -> None:
    """同键在区域与 app 都有绑定时，区域优先。"""
    spec_region = ActionSpec(
        action_id="t.region", title="R", region="selector", default_keys=("F7",)
    )
    spec_app = ActionSpec(
        action_id="t.app", title="A", region="app", default_keys=("F7",)
    )
    table = BindingTable((spec_region, spec_app))
    handlers = HandlerRegistry()
    calls: List[str] = []
    handlers.register("t.region", lambda: calls.append("region"), owner=1)
    handlers.register("t.app", lambda: calls.append("app"), owner=1)
    d = ShortcutDispatcher(table, handlers)
    d.replace_region("selector")
    assert d.eventFilter(None, _press(Qt.Key.Key_F7)) is True
    assert calls == ["region"]


def test_handler_returning_false_falls_through(qapp: Any) -> None:
    """handler 显式返回 False 表示未消费，继续向下层查找。"""
    h = _Harness()
    h.handlers.register(
        "preview.pdf.copy_selection", lambda: False, owner=h
    )
    h.dispatcher.replace_region("preview.pdf")
    assert h.press(Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier) is False


def test_handler_returning_true_consumes(qapp: Any) -> None:
    """handler 返回 True 时消费事件。"""
    h = _Harness()
    h.handlers.register("preview.pdf.copy_selection", lambda: True, owner=h)
    h.dispatcher.replace_region("preview.pdf")
    assert h.press(Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier) is True


# ── 输入框守卫 ───────────────────────────────────────────────────────


def test_text_input_blocks_plain_key(qapp: Any) -> None:
    """输入框内无命令修饰键的动作一律放行。"""
    h = _Harness()
    h.register("selector.nav_up")
    h.dispatcher.replace_region("selector")
    host = QWidget()
    host.resize(400, 200)
    edit = QLineEdit(host)
    host.show()
    edit.setFocus()
    qapp.processEvents()
    try:
        assert qapp.focusWidget() is edit, "测试前置：输入框必须获得焦点"
        assert h.press(Qt.Key.Key_Up) is False
        assert h.calls == []
    finally:
        host.close()
        host.deleteLater()
        qapp.processEvents()


def test_text_input_allows_command_key(qapp: Any) -> None:
    """输入框内带 Ctrl 的动作仍然派发（如 Ctrl+F 筛选）。"""
    h = _Harness()
    h.register("selector.filter")
    h.dispatcher.replace_region("selector")
    host = QWidget()
    host.resize(400, 200)
    edit = QLineEdit(host)
    host.show()
    edit.setFocus()
    qapp.processEvents()
    try:
        assert qapp.focusWidget() is edit, "测试前置：输入框必须获得焦点"
        assert h.press(Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier) is True
        assert h.calls == ["selector.filter"]
    finally:
        host.close()
        host.deleteLater()
        qapp.processEvents()


def test_text_input_allows_ctrl_arrow_zone_nav(qapp: Any) -> None:
    """路径框内 Ctrl+方向键优先切区（中文场景不保留按词移动）。"""
    h = _Harness()
    h.register("nav.prev_zone")
    h.dispatcher.replace_region("path")
    host = QWidget()
    host.resize(400, 200)
    edit = QLineEdit(host)
    host.show()
    edit.setFocus()
    qapp.processEvents()
    try:
        assert qapp.focusWidget() is edit, "测试前置：输入框必须获得焦点"
        assert h.press(Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier) is True
        assert h.calls == ["nav.prev_zone"]
    finally:
        host.close()
        host.deleteLater()
        qapp.processEvents()


def test_readonly_line_edit_allows_plain_escape(qapp: Any) -> None:
    """只读输入框（预览器路径框）不得吞掉 ``Esc``：区域链仍需执行。"""
    h = _Harness()

    class _Provider:
        def escape_handlers(self):
            return [lambda: True]

    h.dispatcher.register_escape_provider("preview.folder", _Provider())
    h.dispatcher.replace_region("preview.folder")
    host = QWidget()
    host.resize(400, 200)
    edit = QLineEdit(host)
    edit.setReadOnly(True)
    host.show()
    edit.setFocus()
    qapp.processEvents()
    try:
        assert qapp.focusWidget() is edit, "测试前置：只读输入框必须获得焦点"
        assert h.press(Qt.Key.Key_Escape) is True
    finally:
        host.close()
        host.deleteLater()
        qapp.processEvents()


def test_editable_line_edit_keeps_escape_for_itself(qapp: Any) -> None:
    """可编辑输入框内 ``Esc`` 仍由控件自身处理（派发器放行）。"""
    h = _Harness()

    class _Provider:
        def escape_handlers(self):
            return [lambda: True]

    h.dispatcher.register_escape_provider("selector", _Provider())
    h.dispatcher.replace_region("selector")
    host = QWidget()
    host.resize(400, 200)
    edit = QLineEdit(host)
    host.show()
    edit.setFocus()
    qapp.processEvents()
    try:
        assert qapp.focusWidget() is edit, "测试前置：输入框必须获得焦点"
        assert h.press(Qt.Key.Key_Escape) is False
    finally:
        host.close()
        host.deleteLater()
        qapp.processEvents()


def test_shift_f_in_text_input_does_not_toggle_drawer(
    qapp: Any, monkeypatch: Any
) -> None:
    """抽屉打开且焦点在搜索框时，``Shift+F`` 必须放行（用于输入大写 F）。

    抽屉开关键已改为 ``Shift+F``（可打印组合键）。若输入框守卫排在上下文
    阻断之后，``works_in_context`` 穿透会让用户在搜索框里输入大写 ``F`` 时
    误关抽屉。
    """
    h = _Harness()
    h.register("preview.text.toggle_search")
    h.dispatcher.replace_region("preview.text")
    monkeypatch.setattr(h.dispatcher, "_context_blocked", lambda: True)
    monkeypatch.setattr(h.dispatcher, "_blocking_source", lambda: "drawer")
    host = QWidget()
    host.resize(400, 200)
    edit = QLineEdit(host)
    host.show()
    edit.setFocus()
    qapp.processEvents()
    try:
        assert qapp.focusWidget() is edit, "测试前置：输入框必须获得焦点"
        assert h.press(Qt.Key.Key_F, Qt.KeyboardModifier.ShiftModifier) is False
        assert h.calls == []
    finally:
        host.close()
        host.deleteLater()
        qapp.processEvents()


def test_ctrl_shift_f_in_text_input_still_toggles_drawer(
    qapp: Any, monkeypatch: Any
) -> None:
    """输入框内 ``Ctrl+Shift+F``（别名键）仍可关闭抽屉。"""
    h = _Harness()
    h.register("preview.text.toggle_search")
    h.dispatcher.replace_region("preview.text")
    monkeypatch.setattr(h.dispatcher, "_context_blocked", lambda: True)
    monkeypatch.setattr(h.dispatcher, "_blocking_source", lambda: "drawer")
    host = QWidget()
    host.resize(400, 200)
    edit = QLineEdit(host)
    host.show()
    edit.setFocus()
    qapp.processEvents()
    try:
        assert qapp.focusWidget() is edit, "测试前置：输入框必须获得焦点"
        mods = (
            Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.ShiftModifier
        )
        assert h.press(Qt.Key.Key_F, mods) is True
        assert h.calls == ["preview.text.toggle_search"]
    finally:
        host.close()
        host.deleteLater()
        qapp.processEvents()


def test_owns_keys_widget_blocks_region(qapp: Any) -> None:
    """声明 ``sp_owns_keys`` 的自定义控件不让区域键生效。"""
    h = _Harness()
    h.register("selector.nav_up")
    h.dispatcher.replace_region("selector")
    host = QWidget()
    host.resize(400, 200)
    widget = QWidget(host)
    widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    widget.setProperty("sp_owns_keys", True)
    host.show()
    widget.setFocus()
    qapp.processEvents()
    try:
        assert qapp.focusWidget() is widget, "测试前置：自定义控件必须获得焦点"
        assert h.press(Qt.Key.Key_Up) is False
    finally:
        host.close()
        host.deleteLater()
        qapp.processEvents()


# ── 上下文阻断 ───────────────────────────────────────────────────────


def test_dialog_blocks_region(qapp: Any) -> None:
    """存活弹窗时区域动作全部静默。"""
    from sopeek.ui.components.styled_dialog import StyledDialog

    h = _Harness()
    h.register("selector.refresh")
    h.dispatcher.replace_region("selector")
    dialog = StyledDialog(title="t", body_widget=QWidget())
    try:
        dialog.show()
        qapp.processEvents()
        assert h.press(Qt.Key.Key_H, Qt.KeyboardModifier.ControlModifier) is False
        assert h.calls == []
    finally:
        dialog.close_dialog(0)
        qapp.processEvents()
        dialog.deleteLater()
        qapp.processEvents()


def test_drawer_blocks_region(qapp: Any) -> None:
    """打开态抽屉阻断区域动作。"""
    from sopeek.ui.components.styled_drawer import StyledDrawer

    h = _Harness()
    h.register("selector.refresh")
    h.dispatcher.replace_region("selector")
    parent = QWidget()
    parent.resize(600, 400)
    parent.show()
    drawer = StyledDrawer(orientation="right", parent=parent)
    try:
        drawer.open_drawer()
        qapp.processEvents()
        assert h.press(Qt.Key.Key_H, Qt.KeyboardModifier.ControlModifier) is False
        assert h.calls == []
    finally:
        drawer.close_drawer()
        parent.close()
        parent.deleteLater()
        qapp.processEvents()


# ── 长按状态机 ───────────────────────────────────────────────────────


def test_long_press_short_keeps_value(qapp: Any) -> None:
    """短按：按下即生效，释放不回滚。"""
    h = _Harness()
    events: List[str] = []
    h.handlers.register(
        "preview.media.speed_2.press", lambda: events.append("press"), owner=h
    )
    h.handlers.register(
        "preview.media.speed_2.release",
        lambda long_pressed=False: events.append(f"release:{long_pressed}"),
        owner=h,
    )
    h.dispatcher.replace_region("preview.media")
    assert h.press(Qt.Key.Key_2) is True
    assert h.release(Qt.Key.Key_2) is True
    assert events == ["press", "release:False"]


def test_long_press_autorepeat_ignored(qapp: Any) -> None:
    """长按期间的 autoRepeat 事件被忽略（不重复执行）。"""
    h = _Harness()
    count: List[int] = []
    h.handlers.register(
        "preview.media.speed_2.press", lambda: count.append(1), owner=h
    )
    h.dispatcher.replace_region("preview.media")
    h.press(Qt.Key.Key_2)
    repeat = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_2, Qt.KeyboardModifier.NoModifier, "", True
    )
    assert h.dispatcher.eventFilter(None, repeat) is True
    assert len(count) == 1


def test_autorepeat_release_does_not_emit(qapp: Any) -> None:
    """系统连发的「伪释放」不得触发 ``.release``（否则长按会连续加载预览）。"""
    h = _Harness()
    releases: List[int] = []
    h.handlers.register(
        "selector.nav_down", lambda: True, owner=h
    )
    h.handlers.register(
        "selector.nav_down.release", lambda: releases.append(1), owner=h
    )
    h.dispatcher.replace_region("selector")
    pseudo_release = QKeyEvent(
        QEvent.Type.KeyRelease,
        Qt.Key.Key_Down,
        Qt.KeyboardModifier.NoModifier,
        "",
        True,
    )
    assert h.dispatcher.eventFilter(None, pseudo_release) is True
    assert releases == []
    # 真正的松手才触发
    assert h.release(Qt.Key.Key_Down) is True
    assert releases == [1]


def test_finish_long_press_restores(qapp: Any) -> None:
    """焦点切换时强制收尾，触发 release 回调。"""
    h = _Harness()
    events: List[str] = []
    h.handlers.register(
        "preview.media.speed_2.press", lambda: events.append("press"), owner=h
    )
    h.handlers.register(
        "preview.media.speed_2.release",
        lambda long_pressed=False: events.append(f"release:{long_pressed}"),
        owner=h,
    )
    h.dispatcher.replace_region("preview.media")
    h.press(Qt.Key.Key_2)
    h.dispatcher.finish_long_press_if_any()
    assert events[0] == "press"
    assert events[1].startswith("release:")


# ── Escape 链 ────────────────────────────────────────────────────────


def test_escape_chain_short_circuits(qapp: Any) -> None:
    """``Esc`` 链第一个返回 True 的处理器胜出，后续不再执行。"""
    h = _Harness()
    order: List[str] = []

    class _Provider:
        def escape_handlers(self):
            return [
                lambda: (order.append("first"), True)[1],
                lambda: (order.append("second"), True)[1],
            ]

    h.dispatcher.register_escape_provider("selector", _Provider())
    h.dispatcher.replace_region("selector")
    assert h.press(Qt.Key.Key_Escape) is True
    assert order == ["first"]


def test_escape_chain_all_false_not_consumed(qapp: Any) -> None:
    """``Esc`` 链全部返回 False 时不消费（放行给上层）。"""
    h = _Harness()

    class _Provider:
        def escape_handlers(self):
            return [lambda: False]

    h.dispatcher.register_escape_provider("selector", _Provider())
    h.dispatcher.replace_region("selector")
    assert h.press(Qt.Key.Key_Escape) is False


def test_escape_unregister(qapp: Any) -> None:
    """注销 Escape 提供者后不再拦截。"""
    h = _Harness()

    class _Provider:
        def escape_handlers(self):
            return [lambda: True]

    h.dispatcher.register_escape_provider("selector", _Provider())
    h.dispatcher.unregister_escape_provider("selector")
    h.dispatcher.replace_region("selector")
    assert h.press(Qt.Key.Key_Escape) is False


# ── 区域栈 ───────────────────────────────────────────────────────────


def test_push_pop_region(qapp: Any) -> None:
    """压栈 / 弹栈切换当前区域。"""
    h = _Harness()
    h.dispatcher.replace_region("selector")
    h.dispatcher.push_region("fullscreen")
    assert h.dispatcher.region() == "fullscreen"
    h.dispatcher.pop_region("fullscreen")
    assert h.dispatcher.region() == "app"


def test_pop_mismatched_region_noop(qapp: Any) -> None:
    """弹出不匹配的区域不改变当前区域。"""
    h = _Harness()
    h.dispatcher.replace_region("selector")
    h.dispatcher.pop_region("fullscreen")
    assert h.dispatcher.region() == "selector"


# ── 注册表注销 ───────────────────────────────────────────────────────


def test_unregister_owner(qapp: Any) -> None:
    """按 owner 注销后按键不再生效。"""
    h = _Harness()
    h.register("selector.refresh")
    h.dispatcher.replace_region("selector")
    assert h.press(Qt.Key.Key_H, Qt.KeyboardModifier.ControlModifier) is True
    assert h.handlers.unregister_owner(h) >= 1
    assert h.press(Qt.Key.Key_H, Qt.KeyboardModifier.ControlModifier) is False


# ── 抽屉 Esc 优先级 ──────────────────────────────────────────────────


def test_escape_closes_top_drawer_before_context_block(
    qapp: Any, monkeypatch: Any
) -> None:
    """抽屉打开时 ``Esc`` 必须先关抽屉，而不是被上下文阻断吞掉。"""
    h = _Harness()
    h.register("selector.refresh")
    h.dispatcher.replace_region("selector")

    # 模拟抽屉处于打开态（上下文阻断成立）
    from sopeek.ui.components import styled_drawer as drawer_module

    monkeypatch.setattr(drawer_module, "open_drawer_count", lambda: 1)
    calls: List[str] = []
    monkeypatch.setattr(
        drawer_module, "close_top_drawer", lambda: calls.append("closed") or True
    )

    assert h.press(Qt.Key.Key_Escape) is True
    assert calls == ["closed"]


def test_escape_no_drawer_falls_through_context_block(
    qapp: Any, monkeypatch: Any
) -> None:
    """没有抽屉时，抽屉关闭函数返回 False，``Esc`` 仍按原有链处理。"""
    h = _Harness()
    h.dispatcher.replace_region("selector")

    from sopeek.ui.components import styled_drawer as drawer_module

    monkeypatch.setattr(drawer_module, "close_top_drawer", lambda: False)
    # 无任何 escape provider：不消费
    assert h.press(Qt.Key.Key_Escape) is False


# ── 区域备用 handler（全屏切换跨区域转发） ──────────────────────────


def test_region_fallback_handler_preferred(qapp: Any) -> None:
    """``{action_id}@{region}`` 优先于同名 handler（用于跨区域转发全屏）。"""
    h = _Harness()
    h.register("preview.image.fullscreen")
    h.handlers.register(
        "preview.image.fullscreen@pool",
        lambda: h.calls.append("pool-forward"),
        owner=h,
    )
    h.dispatcher.replace_region("pool")
    assert h.press(Qt.Key.Key_Backslash, Qt.KeyboardModifier.ControlModifier) is True
    assert h.calls == ["pool-forward"]


def test_works_in_context_action_runs_when_blocked(
    qapp: Any, monkeypatch: Any
) -> None:
    """带 ``works_in_context`` 的开关动作（收藏夹）在弹层打开时仍可关闭。"""
    h = _Harness()
    h.register("selector.favorites")
    h.dispatcher.replace_region("selector")
    monkeypatch.setattr(h.dispatcher, "_context_blocked", lambda: True)
    monkeypatch.setattr(h.dispatcher, "_blocking_source", lambda: "drawer")
    assert h.press(Qt.Key.Key_G, Qt.KeyboardModifier.ControlModifier) is True
    assert h.calls == ["selector.favorites"]


def test_works_in_context_action_blocked_by_menu(
    qapp: Any, monkeypatch: Any
) -> None:
    """``QMenu`` 打开时开关动作也必须阻断（保护 type-ahead）。"""
    h = _Harness()
    h.register("selector.favorites")
    h.dispatcher.replace_region("selector")
    monkeypatch.setattr(h.dispatcher, "_context_blocked", lambda: True)
    monkeypatch.setattr(h.dispatcher, "_blocking_source", lambda: "menu")
    assert h.press(Qt.Key.Key_G, Qt.KeyboardModifier.ControlModifier) is False
    assert h.calls == []


def test_works_in_menu_action_runs_when_menu_open(
    qapp: Any, monkeypatch: Any
) -> None:
    """``Ctrl+L`` 排序菜单打开时仍可派发（用于二次按下关闭）。"""
    h = _Harness()
    h.register("selector.sort_menu")
    h.dispatcher.replace_region("selector")
    monkeypatch.setattr(h.dispatcher, "_context_blocked", lambda: True)
    monkeypatch.setattr(h.dispatcher, "_blocking_source", lambda: "menu")
    assert h.press(Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier) is True
    assert h.calls == ["selector.sort_menu"]


def test_non_menu_action_blocked_when_menu_open(
    qapp: Any, monkeypatch: Any
) -> None:
    """普通动作在 ``QMenu`` 打开时仍被阻断（保护 type-ahead）。"""
    h = _Harness()
    h.register("selector.favorites")
    h.dispatcher.replace_region("selector")
    monkeypatch.setattr(h.dispatcher, "_context_blocked", lambda: True)
    monkeypatch.setattr(h.dispatcher, "_blocking_source", lambda: "menu")
    assert h.press(Qt.Key.Key_G, Qt.KeyboardModifier.ControlModifier) is False
    assert h.calls == []


def test_normal_action_blocked_when_context_open(
    qapp: Any, monkeypatch: Any
) -> None:
    """普通区域动作在弹层打开时仍被阻断。"""
    h = _Harness()
    h.register("selector.refresh")
    h.dispatcher.replace_region("selector")
    monkeypatch.setattr(h.dispatcher, "_context_blocked", lambda: True)
    assert h.press(Qt.Key.Key_H, Qt.KeyboardModifier.ControlModifier) is False
    assert h.calls == []
