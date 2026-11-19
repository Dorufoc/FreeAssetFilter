# -*- coding: utf-8 -*-
"""组件键盘支持测试（离屏 Qt）。

覆盖本期顺带修复的三个组件缺陷：

* ``StyledDialog``：``Esc`` 关闭（此前完全没有实现）；``Enter`` 执行
  当前焦点按钮（而不是绕过焦点直接触发默认「确定」）；
* ``StyledComboBox``：``↑↓`` 切换值 / ``Space``·``Enter`` 展开 / 展开态导航；
* ``StyledCheckbox``：``Space``·``Enter`` 切换勾选。

验证命令：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/unit/ui/components/test_component_keys.py -v
"""

from __future__ import annotations

from typing import Any

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QApplication, QWidget

pytestmark = pytest.mark.unit


@pytest.fixture
def host(qapp: Any):
    """提供一个已显示的宿主窗口（键盘事件需要真实焦点）。"""
    widget = QWidget()
    widget.resize(400, 300)
    widget.show()
    qapp.processEvents()
    try:
        yield widget
    finally:
        widget.close()
        widget.deleteLater()
        qapp.processEvents()


# ── StyledDialog ─────────────────────────────────────────────────────


def test_dialog_escape_closes(host: QWidget, qapp: Any) -> None:
    """``Esc`` 关闭弹窗并以 result=0 进入关闭流程（此前完全缺失）。

    断言 ``closing`` 而非 ``finished``：后者在退场动画结束后才发，
    离屏环境下动画不保证推进；``closing`` 在关闭动作**开始**时同步发出，
    正是「按 Esc 有没有触发关闭」的直接证据。
    """
    from sopeek.ui.components.styled_dialog import StyledDialog

    dialog = StyledDialog(title="t", body_widget=QWidget(), parent=host)
    closing_results: list = []
    dialog.closing.connect(lambda r: closing_results.append(r))
    dialog.show()
    qapp.processEvents()
    try:
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        qapp.processEvents()
        assert closing_results == [0]
        assert dialog._result == 0
    finally:
        dialog.deleteLater()
        qapp.processEvents()


def test_dialog_escape_ignores_modifiers(host: QWidget, qapp: Any) -> None:
    """带修饰键的 Esc（``Ctrl+Esc``）不关闭弹窗。"""
    from sopeek.ui.components.styled_dialog import StyledDialog

    dialog = StyledDialog(title="t", body_widget=QWidget(), parent=host)
    closing_results: list = []
    dialog.closing.connect(lambda r: closing_results.append(r))
    dialog.show()
    qapp.processEvents()
    try:
        QTest.keyClick(dialog, Qt.Key.Key_Escape, Qt.KeyboardModifier.ControlModifier)
        qapp.processEvents()
        assert closing_results == []
    finally:
        dialog.close_dialog(0)
        dialog.deleteLater()
        qapp.processEvents()


def test_dialog_registers_into_live_table(host: QWidget, qapp: Any) -> None:
    """直接 ``show()`` 的弹窗也会登记到存活表（供上下文阻断）。"""
    from sopeek.ui.components import styled_dialog as sd

    before = sd.live_dialog_count()
    dialog = sd.StyledDialog(title="t", body_widget=QWidget(), parent=host)
    dialog.show()
    qapp.processEvents()
    try:
        assert sd.live_dialog_count() == before + 1
    finally:
        dialog.close_dialog(0)
        qapp.processEvents()
        dialog.deleteLater()
        qapp.processEvents()


def test_dialog_enter_triggers_primary(host: QWidget, qapp: Any) -> None:
    """``Enter`` 触发主按钮（返回 1），而不是标题栏 ✕ 或取消。"""
    from sopeek.ui.components.styled_dialog import create_basic_dialog

    dialog = create_basic_dialog(
        title="确认",
        message="继续？",
        cancel_text="取消",
        confirm_text="确定",
        parent=host,
        animate=False,
    )
    results: list = []
    dialog.closing.connect(lambda r: results.append(r))
    qapp.processEvents()
    try:
        QTest.keyClick(dialog, Qt.Key.Key_Return)
        qapp.processEvents()
        assert results == [1]
    finally:
        dialog.deleteLater()
        qapp.processEvents()


def test_dialog_enter_activates_focused_secondary_button(
    host: QWidget, qapp: Any
) -> None:
    """``Enter`` 执行当前焦点按钮，而不是默认的「确定」。

    回归：应用级过滤器此前无条件调用 ``_activate_default_button()``，
    焦点在「取消」上按 Enter 仍会返回 1（确定）。
    """
    from sopeek.ui.components.styled_button import StyledButton
    from sopeek.ui.components.styled_dialog import create_basic_dialog

    dialog = create_basic_dialog(
        title="确认",
        message="继续？",
        cancel_text="取消",
        confirm_text="确定",
        parent=host,
        animate=False,
    )
    results: list = []
    dialog.closing.connect(lambda r: results.append(r))
    qapp.processEvents()
    try:
        buttons = {b.text(): b for b in dialog.findChildren(StyledButton)}
        cancel = buttons["取消"]
        cancel.setFocus()
        qapp.processEvents()
        assert QApplication.focusWidget() is cancel

        QTest.keyClick(cancel, Qt.Key.Key_Return)
        qapp.processEvents()
        assert results == [0]
    finally:
        if dialog.isVisible():
            dialog.close_dialog(0)
        dialog.deleteLater()
        qapp.processEvents()


def test_dialog_arrow_navigation_then_enter_uses_focused_button(
    host: QWidget, qapp: Any
) -> None:
    """方向键移到「取消」后按 Enter → 执行取消（而不是主按钮）。"""
    from sopeek.ui.components.styled_button import StyledButton
    from sopeek.ui.components.styled_dialog import create_basic_dialog

    dialog = create_basic_dialog(
        title="确认",
        message="继续？",
        cancel_text="取消",
        confirm_text="确定",
        parent=host,
        animate=False,
    )
    results: list = []
    dialog.closing.connect(lambda r: results.append(r))
    qapp.processEvents()
    try:
        buttons = {b.text(): b for b in dialog.findChildren(StyledButton)}
        confirm = buttons["确定"]
        cancel = buttons["取消"]
        confirm.setFocus()
        qapp.processEvents()
        assert QApplication.focusWidget() is confirm

        QTest.keyClick(confirm, Qt.Key.Key_Left)
        qapp.processEvents()
        assert QApplication.focusWidget() is cancel

        QTest.keyClick(cancel, Qt.Key.Key_Return)
        qapp.processEvents()
        assert results == [0]
    finally:
        if dialog.isVisible():
            dialog.close_dialog(0)
        dialog.deleteLater()
        qapp.processEvents()


def test_dialog_numpad_enter_uses_focused_button(
    host: QWidget, qapp: Any
) -> None:
    """小键盘 Enter（带 ``KeypadModifier``）同样执行焦点按钮。"""
    from sopeek.ui.components.styled_button import StyledButton
    from sopeek.ui.components.styled_dialog import create_basic_dialog

    dialog = create_basic_dialog(
        title="确认",
        message="继续？",
        cancel_text="取消",
        confirm_text="确定",
        parent=host,
        animate=False,
    )
    results: list = []
    dialog.closing.connect(lambda r: results.append(r))
    qapp.processEvents()
    try:
        buttons = {b.text(): b for b in dialog.findChildren(StyledButton)}
        cancel = buttons["取消"]
        cancel.setFocus()
        qapp.processEvents()

        QTest.keyClick(
            cancel, Qt.Key.Key_Enter, Qt.KeyboardModifier.KeypadModifier
        )
        qapp.processEvents()
        assert results == [0]
    finally:
        if dialog.isVisible():
            dialog.close_dialog(0)
        dialog.deleteLater()
        qapp.processEvents()


def test_dialog_enter_from_input_falls_back_to_primary(
    host: QWidget, qapp: Any
) -> None:
    """焦点在输入框（无按钮焦点）时，Enter 仍提交默认主按钮。"""
    from PySide6.QtWidgets import QLineEdit

    from sopeek.ui.components.styled_dialog import create_input_dialog

    dialog = create_input_dialog(
        title="重命名",
        message="请输入名称",
        parent=host,
        animate=False,
    )
    results: list = []
    dialog.closing.connect(lambda r: results.append(r))
    qapp.processEvents()
    try:
        edit = next(iter(dialog.findChildren(QLineEdit)))
        edit.setFocus()
        qapp.processEvents()
        assert QApplication.focusWidget() is edit

        QTest.keyClick(edit, Qt.Key.Key_Return)
        qapp.processEvents()
        assert results == [1]
    finally:
        if dialog.isVisible():
            dialog.close_dialog(0)
        dialog.deleteLater()
        qapp.processEvents()


def test_dialog_enter_on_focused_close_button_closes(
    host: QWidget, qapp: Any
) -> None:
    """用户主动把焦点移到标题栏 ✕ 时，Enter 执行关闭而不是找默认按钮。"""
    from sopeek.ui.components.styled_dialog import StyledDialog

    dialog = StyledDialog(
        title="t", body_widget=QWidget(), parent=host, animate=False
    )
    results: list = []
    dialog.closing.connect(lambda r: results.append(r))
    dialog.show()
    qapp.processEvents()
    try:
        close_btn = next(
            b
            for b in dialog.findChildren(QAbstractButton)
            if b.text().strip() == "✕"
        )
        close_btn.setFocus()
        qapp.processEvents()
        assert QApplication.focusWidget() is close_btn

        QTest.keyClick(close_btn, Qt.Key.Key_Return)
        qapp.processEvents()
        assert results == [0]
    finally:
        if dialog.isVisible():
            dialog.close_dialog(0)
        dialog.deleteLater()
        qapp.processEvents()


def test_dialog_delayed_focus_does_not_steal_focused_button(
    host: QWidget, qapp: Any
) -> None:
    """60ms 后移焦到按钮，200/350ms 的延时落焦不得把它抢回输入框。"""
    from PySide6.QtWidgets import QVBoxLayout

    from sopeek.ui.components.styled_dialog import StyledDialog
    from sopeek.ui.components.styled_lineedit import StyledLineEdit

    body = QWidget()
    layout = QVBoxLayout(body)
    edit = StyledLineEdit(size="default")
    layout.addWidget(edit)

    dialog = StyledDialog(
        title="t", body_widget=body, parent=host, animate=False
    )
    confirm = dialog.add_footer_button("应用", variant="primary")
    dialog.show()
    try:
        QTest.qWait(60)
        qapp.processEvents()
        assert QApplication.focusWidget() is edit

        confirm.setFocus()
        qapp.processEvents()
        assert QApplication.focusWidget() is confirm

        # 越过 200ms / 350ms 两次延时落焦。
        QTest.qWait(400)
        qapp.processEvents()
        assert QApplication.focusWidget() is confirm
    finally:
        if dialog.isVisible():
            dialog.close_dialog(0)
        dialog.deleteLater()
        qapp.processEvents()


    """弹窗显示后焦点必须落在正文输入框（否则 Enter / 方向键全失效）。"""
    from PySide6.QtWidgets import QVBoxLayout

    from sopeek.ui.components.styled_dialog import StyledDialog
    from sopeek.ui.components.styled_lineedit import StyledLineEdit

    body = QWidget()
    layout = QVBoxLayout(body)
    edit = StyledLineEdit(size="default")
    layout.addWidget(edit)
    dialog = StyledDialog(title="t", body_widget=body, parent=host, animate=False)
    dialog.show()
    qapp.processEvents()
    QTest.qWait(30)
    qapp.processEvents()
    try:
        assert QApplication.focusWidget() is edit
    finally:
        dialog.close_dialog(0)
        qapp.processEvents()
        dialog.deleteLater()
        qapp.processEvents()


def test_dialog_arrow_key_moves_focus_between_fields(host: QWidget, qapp: Any) -> None:
    """弹窗内 ``↓`` 从输入框移到下方按钮（空间导航，非 Tab 顺序）。"""
    from sopeek.ui.components import spatial_focus_nav
    from sopeek.ui.components.styled_dialog import StyledDialog
    from sopeek.ui.components.styled_lineedit import StyledLineEdit

    body = QWidget()
    from PySide6.QtWidgets import QVBoxLayout

    layout = QVBoxLayout(body)
    edit = StyledLineEdit(size="default")
    layout.addWidget(edit)

    dialog = StyledDialog(title="筛选", body_widget=body, parent=host, animate=False)
    dialog.add_footer_button("取消", variant="ghost")
    dialog.add_footer_button("应用", variant="primary")
    dialog.show()
    qapp.processEvents()
    try:
        edit.setFocus()
        qapp.processEvents()
        before = QApplication.focusWidget()
        assert before is edit
        # 空间导航至少能在弹窗内找到一个「下方」目标
        assert spatial_focus_nav.move_focus(dialog, "down") is True
        qapp.processEvents()
        assert QApplication.focusWidget() is not edit
        # 焦点目标必须在本弹窗内
        target = QApplication.focusWidget()
        assert target is dialog or dialog.isAncestorOf(target)
    finally:
        dialog.close_dialog(0)
        qapp.processEvents()
        dialog.deleteLater()
        qapp.processEvents()


def test_drawer_close_restores_previous_focus(host: QWidget, qapp: Any) -> None:
    """抽屉关闭后焦点回到打开前的控件（而不是落到路径框）。"""
    from PySide6.QtWidgets import QLineEdit

    from sopeek.ui.components.styled_drawer import StyledDrawer

    edit = QLineEdit(host)
    edit.setGeometry(10, 10, 100, 24)
    edit.show()
    edit.setFocus()
    qapp.processEvents()
    assert QApplication.focusWidget() is edit

    drawer = StyledDrawer(parent=host)
    drawer.open_drawer()
    QTest.qWait(400)
    qapp.processEvents()
    try:
        assert drawer.is_open is True
        drawer.close_drawer()
        QTest.qWait(400)
        qapp.processEvents()
        assert drawer.is_open is False
        assert QApplication.focusWidget() is edit
    finally:
        drawer.deleteLater()
        qapp.processEvents()


def test_osd_is_independent_toplevel(qapp: Any) -> None:
    """OSD 必须是独立顶层窗口：控制栏隐藏时不能把它一起带走。

    音频模式实测缺陷：浮动控制栏 3~6 秒自动隐藏，作为其子窗口的 OSD
    随之消失，导致长按倍速标签「自己没了」。
    """
    from sopeek.ui.components.styled_player_bar import StyledPlayerBar

    bar = StyledPlayerBar()
    bar.resize(600, 60)
    bar.show()
    qapp.processEvents()
    try:
        osd = bar._osd_widget
        assert osd.parent() is None
        assert osd.isWindow() is True
        bar.set_osd_target(bar)
        bar.show_osd_sticky("2.0x")
        qapp.processEvents()
        assert osd.isVisible() is True
        # 控制栏隐藏后 OSD 仍可见
        bar.hide()
        qapp.processEvents()
        assert osd.isVisible() is True
        bar.hide_osd()
        qapp.processEvents()
        assert osd.isVisible() is False
    finally:
        bar.close()
        qapp.processEvents()


def test_pool_batch_tab_removes_enter_is_noop(qapp: Any) -> None:
    """批量态下 ``Tab`` 移出全部选中，``Enter`` 完全无操作。"""
    from sopeek.ui.layout.file_pool_layout import FilePoolLayout

    pool = FilePoolLayout()
    pool.resize(400, 400)
    pool.show()
    qapp.processEvents()
    try:
        base = "C:/tmp/poolbatch"
        for i in range(4):
            pool.add_file(
                {
                    "path": f"{base}/f{i}.png",
                    "name": f"f{i}.png",
                    "is_dir": False,
                    "size": 1,
                    "modified": "",
                    "created": "",
                    "suffix": ".png",
                }
            )
        qapp.processEvents()
        order = pool._ordered_paths()
        assert len(order) == 4
        pool._set_cursor(order[0])
        pool.enter_batch_mode(+1, axis="row")
        assert pool._batch_mode is True
        selected_before = set(pool._batch_selected)
        assert selected_before
        # Enter 不改变任何状态
        pool._shortcut_enter()
        assert pool._batch_mode is True
        assert set(pool._batch_selected) == selected_before
        # Tab 才移出：批量态退出（_commit_batch_remove 内部会 exit）
        pool._toggle_pool_current()
        assert pool._batch_mode is False
    finally:
        pool.close()
        qapp.processEvents()


# ── StyledComboBox ───────────────────────────────────────────────────


def test_combobox_focus_policy() -> None:
    """下拉框可被键盘聚焦，且声明自己处理按键。"""
    from sopeek.ui.components.styled_combobox import StyledComboBox

    combo = StyledComboBox(items=["a", "b"])
    assert combo.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert combo.property("sp_owns_keys") is True
    combo.deleteLater()


def test_combobox_down_steps_value(host: QWidget, qapp: Any) -> None:
    """未展开时 ``↓`` 直接切到下一个值（不展开弹层）。"""
    from sopeek.ui.components.styled_combobox import StyledComboBox

    combo = StyledComboBox(items=["a", "b", "c"], parent=host)
    combo.show()
    combo.setFocus()
    qapp.processEvents()
    try:
        assert combo.currentText() == "a"
        QTest.keyClick(combo, Qt.Key.Key_Down)
        assert combo.currentText() == "b"
        QTest.keyClick(combo, Qt.Key.Key_Up)
        assert combo.currentText() == "a"
    finally:
        combo.deleteLater()


def test_combobox_skips_divider(host: QWidget, qapp: Any) -> None:
    """``↑↓`` 跳过 ``---`` 分隔项。"""
    from sopeek.ui.components.styled_combobox import StyledComboBox

    combo = StyledComboBox(items=["a", "---", "c"], parent=host)
    combo.show()
    combo.setFocus()
    qapp.processEvents()
    try:
        QTest.keyClick(combo, Qt.Key.Key_Down)
        assert combo.currentText() == "c"
        QTest.keyClick(combo, Qt.Key.Key_Up)
        assert combo.currentText() == "a"
    finally:
        combo.deleteLater()


def test_combobox_space_opens_popup(host: QWidget, qapp: Any) -> None:
    """未展开时 ``Space`` 展开弹层。"""
    from sopeek.ui.components.styled_combobox import StyledComboBox

    combo = StyledComboBox(items=["a", "b"], parent=host)
    combo.show()
    combo.setFocus()
    qapp.processEvents()
    try:
        QTest.keyClick(combo, Qt.Key.Key_Space)
        qapp.processEvents()
        assert combo._open is True
    finally:
        combo._close()
        combo.deleteLater()


def test_combobox_popup_escape_keeps_value(host: QWidget, qapp: Any) -> None:
    """展开态 ``Esc`` 只关闭弹层，不改变当前值。"""
    from sopeek.ui.components.styled_combobox import StyledComboBox

    combo = StyledComboBox(items=["a", "b", "c"], parent=host)
    combo.show()
    combo.setFocus()
    qapp.processEvents()
    try:
        QTest.keyClick(combo, Qt.Key.Key_Down)
        before = combo.currentText()
        QTest.keyClick(combo, Qt.Key.Key_Space)
        qapp.processEvents()
        assert combo._open is True
        QTest.keyClick(combo, Qt.Key.Key_Escape)
        qapp.processEvents()
        assert combo._open is False
        assert combo.currentText() == before
    finally:
        combo._close()
        combo.deleteLater()


def test_combobox_popup_enter_selects(host: QWidget, qapp: Any) -> None:
    """展开态 ``↓`` + ``Enter`` 选中下一项并关闭。"""
    from sopeek.ui.components.styled_combobox import StyledComboBox

    combo = StyledComboBox(items=["a", "b", "c"], parent=host)
    combo.show()
    combo.setFocus()
    qapp.processEvents()
    try:
        QTest.keyClick(combo, Qt.Key.Key_Space)
        qapp.processEvents()
        QTest.keyClick(combo, Qt.Key.Key_Down)
        QTest.keyClick(combo, Qt.Key.Key_Return)
        qapp.processEvents()
        assert combo._open is False
        assert combo.currentText() == "b"
    finally:
        combo._close()
        combo.deleteLater()


# ── StyledCheckbox ───────────────────────────────────────────────────


def test_checkbox_focus_policy() -> None:
    """复选框可被键盘聚焦，且声明自己处理按键。"""
    from sopeek.ui.components.styled_checkbox import StyledCheckbox

    box = StyledCheckbox(text="x")
    assert box.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert box.property("sp_owns_keys") is True
    box.deleteLater()


def test_checkbox_space_toggles(host: QWidget, qapp: Any) -> None:
    """``Space`` 切换勾选态。"""
    from sopeek.ui.components.styled_checkbox import StyledCheckbox

    box = StyledCheckbox(text="x", parent=host)
    box.show()
    box.setFocus()
    qapp.processEvents()
    try:
        assert box.checked is False
        QTest.keyClick(box, Qt.Key.Key_Space)
        assert box.checked is True
        QTest.keyClick(box, Qt.Key.Key_Space)
        assert box.checked is False
    finally:
        box.deleteLater()


def test_checkbox_enter_toggles(host: QWidget, qapp: Any) -> None:
    """``Enter`` 同样切换勾选态。"""
    from sopeek.ui.components.styled_checkbox import StyledCheckbox

    box = StyledCheckbox(text="x", parent=host)
    box.show()
    box.setFocus()
    qapp.processEvents()
    try:
        QTest.keyClick(box, Qt.Key.Key_Return)
        assert box.checked is True
    finally:
        box.deleteLater()


def test_checkbox_disabled_ignores_keys(host: QWidget, qapp: Any) -> None:
    """禁用态不响应 ``Space``。"""
    from sopeek.ui.components.styled_checkbox import StyledCheckbox

    box = StyledCheckbox(text="x", enabled=False, parent=host)
    box.show()
    box.setFocus()
    qapp.processEvents()
    try:
        QTest.keyClick(box, Qt.Key.Key_Space)
        assert box.checked is False
    finally:
        box.deleteLater()


# ── StyledInfoCard ───────────────────────────────────────────────────


def test_info_card_focus_policy() -> None:
    """储存池卡片可被 ``setFocus()`` 聚焦（方向键导航前置条件）。"""
    from sopeek.ui.components.styled_info_card import StyledInfoCard

    card = StyledInfoCard(title="x")
    assert card.focusPolicy() == Qt.FocusPolicy.StrongFocus
    card.deleteLater()


def test_info_card_keyboard_focus_flag() -> None:
    """``set_keyboard_focused`` 幂等切换绘制状态。"""
    from sopeek.ui.components.styled_info_card import StyledInfoCard

    card = StyledInfoCard(title="x")
    assert card._keyboard_focused is False
    card.set_keyboard_focused(True)
    assert card._keyboard_focused is True
    card.set_keyboard_focused(True)  # 幂等
    assert card._keyboard_focused is True
    card.set_keyboard_focused(False)
    assert card._keyboard_focused is False
    card.deleteLater()
