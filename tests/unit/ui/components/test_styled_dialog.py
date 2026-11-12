# -*- coding: utf-8 -*-
"""StyledDialog 公共 footer / show 接口与 update_dialogs 骨架单元测试。

覆盖 Todo 14 的验收点：

1. ``add_footer_button`` 在 show 前可调用（右对齐/无 footer 两种底栏）；
2. 追加的按钮顺序正确、返回 ``StyledButton`` 且点击回调只触发一次；
3. 首次 show 之后（含 ``animate=False`` 与 ``hide()`` 之后）再追加按钮
   抛出 ``RuntimeError``，而不是 ``AttributeError``；
4. ``show_dialog()`` 委托 ``_show_dialog``，离屏下对话框可见且尺寸固定；
5. ``ui.layout.update_dialogs`` 骨架可导入，7 个公开函数与模块级跟踪
   辅助存在，``_track_dialog`` / ``_untrack_dialog`` 的跟踪与幂等语义。

验证命令：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/unit/ui/components/test_styled_dialog.py -k "footer or show" -v
"""

# targets: ui.components.styled_dialog, ui.layout.update_dialogs

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, Iterator, List

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

# 组件模块内部使用短路径导入（from theme import tm），
# 要求 sopeek/ui 位于 sys.path；与 test_styled_basic.py 一致。
_UI_ROOT: str = str(Path(__file__).resolve().parents[4] / "sopeek" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from tests.support.qt_helpers import drain_deferred_deletes, safe_teardown  # noqa: E402

import sopeek.ui.components.styled_dialog as styled_dialog_module  # noqa: E402
from sopeek.ui.components.styled_button import StyledButton  # noqa: E402
from sopeek.ui.components.styled_dialog import (  # noqa: E402
    FOOTER_NONE,
    FOOTER_RIGHT,
    SIZE_CONFIG,
    StyledDialog,
    active_dialogs,
    close_active_dialogs,
)
from sopeek.ui.components.modal_guard import get_modal_guard  # noqa: E402
from sopeek.ui.layout import update_dialogs  # noqa: E402

pytestmark = pytest.mark.unit


def _widget_items(layout) -> List[object]:
    """按顺序返回布局中的 widget 项（跳过 stretch / 子布局）。

    Args:
        layout: Qt 布局对象。

    Returns:
        List[object]: 按索引顺序的 widget 列表。
    """
    items: List[object] = []
    for index in range(layout.count()):
        widget = layout.itemAt(index).widget()
        if widget is not None:
            items.append(widget)
    return items


@pytest.fixture()
def make_dialog(qapp: QApplication) -> Iterator[Callable[..., StyledDialog]]:
    """构造并自动清理 StyledDialog 的工厂 fixture。

    默认 ``animate=False`` 以保证关闭/销毁路径确定；teardown 时逐个安全
    销毁、派发 DeferredDelete，并清空 update_dialogs 的模块级跟踪表，
    避免顶层窗口与跟踪状态跨测试泄漏。

    Args:
        qapp: 会话级 QApplication。

    Yields:
        Callable[..., StyledDialog]: 接收 StyledDialog 关键字参数并返回实例。
    """
    created: List[StyledDialog] = []

    def _make(**kwargs) -> StyledDialog:
        kwargs.setdefault("animate", False)
        kwargs.setdefault("title", "测试对话框")
        dialog = StyledDialog(**kwargs)
        created.append(dialog)
        return dialog

    yield _make

    for dialog in created:
        try:
            # 强制走同步关闭路径，避免动画在 teardown 中途挂起。
            dialog._animate = False
        except RuntimeError:  # C++ 对象已销毁
            continue
        safe_teardown(dialog)
    drain_deferred_deletes(qapp)
    update_dialogs._active_dialogs.clear()
    update_dialogs._active_progress_dialogs.clear()


# =============================================================================
# add_footer_button
# =============================================================================
class TestAddFooterButton:
    """add_footer_button：show 前追加按钮的契约。"""

    def test_footer_right_adds_two_buttons_in_order(
        self, make_dialog: Callable[..., StyledDialog]
    ) -> None:
        """FOOTER_RIGHT 下追加两个按钮：返回 StyledButton、顺序正确。"""
        dialog = make_dialog(footer_type=FOOTER_RIGHT)

        first = dialog.add_footer_button("取消", variant="ghost")
        second = dialog.add_footer_button("确认")

        assert isinstance(first, StyledButton)
        assert isinstance(second, StyledButton)
        layout = dialog._footer_layout
        assert layout is not None
        assert layout.indexOf(first) >= 0
        assert layout.indexOf(second) >= 0
        assert layout.indexOf(first) < layout.indexOf(second)
        # FOOTER_RIGHT 既有前导 stretch + 两个按钮。
        assert _widget_items(layout) == [first, second]

    def test_footer_right_buttons_trigger_callbacks_once(
        self, make_dialog: Callable[..., StyledDialog]
    ) -> None:
        """追加按钮点击各自触发回调恰一次。"""
        dialog = make_dialog(footer_type=FOOTER_RIGHT)
        calls: List[str] = []

        first = dialog.add_footer_button("一")
        second = dialog.add_footer_button("二")
        first.clicked.connect(lambda: calls.append("first"))
        second.clicked.connect(lambda: calls.append("second"))

        first.click()
        second.click()

        assert calls == ["first", "second"]

    def test_footer_none_lazily_creates_footer(
        self, make_dialog: Callable[..., StyledDialog]
    ) -> None:
        """FOOTER_NONE 初始无底栏，追加按钮时惰性创建并成功。"""
        dialog = make_dialog(footer_type=FOOTER_NONE)
        assert dialog._footer_layout is None

        first = dialog.add_footer_button("稍后")
        second = dialog.add_footer_button("下载更新")

        assert dialog._footer_layout is not None
        assert _widget_items(dialog._footer_layout) == [first, second]

    def test_before_first_show_does_not_raise_attribute_error(
        self, make_dialog: Callable[..., StyledDialog]
    ) -> None:
        """首次 show 前调用不抛 AttributeError（__init__ 已初始化字段）。"""
        dialog = make_dialog(footer_type=FOOTER_NONE)

        assert dialog._footer_layout is None
        assert dialog._show_started is False
        assert isinstance(dialog.add_footer_button("确定"), StyledButton)


# =============================================================================
# show 之后的守卫
# =============================================================================
class TestShowStartedGuard:
    """首次 show 之后 add_footer_button 必须抛 RuntimeError。"""

    @pytest.mark.parametrize("animate", [False, True])
    def test_after_show_raises_runtime_error(
        self, make_dialog: Callable[..., StyledDialog], animate: bool
    ) -> None:
        """show() 后（两种动画设置）追加按钮抛 RuntimeError。"""
        dialog = make_dialog(footer_type=FOOTER_RIGHT, animate=animate)
        dialog.show()

        with pytest.raises(RuntimeError, match="show"):
            dialog.add_footer_button("太晚了")

    def test_after_hide_still_raises(
        self, make_dialog: Callable[..., StyledDialog]
    ) -> None:
        """hide() 不会清除 show-started 状态（不能依赖 isVisible）。"""
        dialog = make_dialog(footer_type=FOOTER_RIGHT)
        dialog.show()
        dialog.hide()
        assert dialog.isVisible() is False

        with pytest.raises(RuntimeError, match="show"):
            dialog.add_footer_button("仍然太晚")


# =============================================================================
# show_dialog
# =============================================================================
class TestShowDialog:
    """show_dialog：委托 _show_dialog 的包装。"""

    def test_delegates_to_show_dialog_function(
        self,
        make_dialog: Callable[..., StyledDialog],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """show_dialog() 以自身为参数调用模块级 _show_dialog。"""
        dialog = make_dialog(footer_type=FOOTER_RIGHT)
        received: List[StyledDialog] = []

        monkeypatch.setattr(
            styled_dialog_module,
            "_show_dialog",
            lambda target: received.append(target),
        )
        dialog.show_dialog()

        assert received == [dialog]

    def test_offscreen_show_visible_and_fixed_size(
        self, qapp: QApplication, make_dialog: Callable[..., StyledDialog]
    ) -> None:
        """真实离屏调用后可见，且为 _show_dialog 计算的固定尺寸。"""
        dialog = make_dialog(footer_type=FOOTER_RIGHT)
        dialog.add_footer_button("确定")

        dialog.show_dialog()
        qapp.processEvents()

        assert dialog.isVisible() is True
        assert dialog.width() > 0
        assert dialog.height() > 0
        expected_width = SIZE_CONFIG[dialog._size]["width"] + dialog.SHADOW_MARGIN * 2
        assert dialog.width() == expected_width
        assert dialog.minimumWidth() == dialog.maximumWidth() == expected_width
        assert dialog.minimumHeight() == dialog.maximumHeight()


# =============================================================================
# update_dialogs 骨架
# =============================================================================
class TestUpdateDialogsSkeleton:
    """update_dialogs 模块骨架：签名、跟踪表与幂等解除。"""

    def test_public_functions_exist(self) -> None:
        """7 个公开函数与跟踪辅助均存在。"""
        for name in (
            "show_no_update",
            "show_check_error",
            "show_update_available",
            "show_startup_update",
            "show_download_progress",
            "show_install_confirm",
            "show_uac_cancelled",
        ):
            assert callable(getattr(update_dialogs, name))

        assert isinstance(update_dialogs._active_dialogs, set)
        assert isinstance(update_dialogs._active_progress_dialogs, dict)
        assert callable(update_dialogs._track_dialog)
        assert callable(update_dialogs._untrack_dialog)

    def test_track_without_request_id_only_set(
        self, make_dialog: Callable[..., StyledDialog]
    ) -> None:
        """request_id=None 只登记 _active_dialogs。"""
        dialog = make_dialog()
        update_dialogs._track_dialog(dialog, None)

        assert dialog in update_dialogs._active_dialogs
        assert update_dialogs._active_progress_dialogs == {}

    def test_track_with_request_id_registers_both_and_finish_removes(
        self, make_dialog: Callable[..., StyledDialog]
    ) -> None:
        """request_id 非 None 时两表登记；关闭后两表都移除。"""
        dialog = make_dialog()
        update_dialogs._track_dialog(dialog, "req-1")

        assert dialog in update_dialogs._active_dialogs
        assert update_dialogs._active_progress_dialogs["req-1"] is dialog

        dialog.close()

        assert dialog not in update_dialogs._active_dialogs
        assert "req-1" not in update_dialogs._active_progress_dialogs

    def test_different_dialog_cannot_pop_request_id(
        self, make_dialog: Callable[..., StyledDialog]
    ) -> None:
        """未登记的同 request_id 对话框不能移除他人条目（按身份判定）。"""
        tracked = make_dialog()
        other = make_dialog()
        update_dialogs._track_dialog(tracked, "req-2")

        update_dialogs._untrack_dialog(other, "req-2")

        assert tracked in update_dialogs._active_dialogs
        assert update_dialogs._active_progress_dialogs["req-2"] is tracked

        # 幂等：重复解除同一对象不抛异常。
        update_dialogs._untrack_dialog(tracked, "req-2")
        update_dialogs._untrack_dialog(tracked, "req-2")
        assert tracked not in update_dialogs._active_dialogs
        assert "req-2" not in update_dialogs._active_progress_dialogs

    def test_destroyed_removes_from_tracking(
        self, qapp: QApplication, make_dialog: Callable[..., StyledDialog]
    ) -> None:
        """destroyed 信号（延迟销毁落地后）也会解除跟踪。"""
        dialog = make_dialog()
        update_dialogs._track_dialog(dialog, "req-3")

        dialog.deleteLater()
        drain_deferred_deletes(qapp)

        assert dialog not in update_dialogs._active_dialogs
        assert "req-3" not in update_dialogs._active_progress_dialogs


class TestRemeasure:
    """``remeasure()``：运行期内容变化后重算固定尺寸。"""

    def test_remeasure_grows_and_keeps_center(self, qapp: QApplication) -> None:
        """向已显示的 body 追加内容后窗口变高，中心不跳。"""
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(8)
        body_layout.addWidget(QLabel("第一行"))

        dialog = StyledDialog(title="remeasure", body_widget=body, animate=False)
        try:
            dialog.show_dialog()
            qapp.processEvents()
            before_height = dialog.height()
            before_center = dialog.frameGeometry().center()

            extra = QLabel("第二行")
            body_layout.addWidget(extra)
            extra.show()
            dialog.remeasure()
            qapp.processEvents()

            assert dialog.height() > before_height
            after_center = dialog.frameGeometry().center()
            assert abs(after_center.x() - before_center.x()) <= 2
            assert abs(after_center.y() - before_center.y()) <= 2
        finally:
            safe_teardown(dialog)
            drain_deferred_deletes(qapp)

    def test_remeasure_keeps_minimum_height(self, qapp: QApplication) -> None:
        """空内容仍保持至少 80px 内容高度（加阴影边距）。"""
        dialog = StyledDialog(title="empty", animate=False)
        try:
            dialog.show_dialog()
            qapp.processEvents()
            dialog.remeasure()

            assert dialog.height() >= 80 + dialog.SHADOW_MARGIN * 2
        finally:
            safe_teardown(dialog)
            drain_deferred_deletes(qapp)


# =============================================================================
# 入场/退场动效
# =============================================================================
class TestMotionAnimation:
    """缩放 + 上浮动效与透明度并行；结束后回到稳态绘制路径。"""

    def test_enter_motion_uses_snapshot_then_restores(
        self, qapp: QApplication, make_dialog: Callable[..., StyledDialog]
    ) -> None:
        """入场期隐藏真实子控件并改用抓图；结束后恢复。"""
        dialog = make_dialog(animate=True)
        dialog.show_dialog()
        qapp.processEvents()

        assert dialog._animating is True
        assert dialog._content_widget.isVisible() is False
        assert dialog._anim_content_pixmap is not None

        QTest.qWait(StyledDialog.ANIM_DURATION + 60)
        qapp.processEvents()

        assert dialog._animating is False
        assert dialog._content_widget.isVisible() is True
        assert dialog._anim_content_pixmap is None
        assert dialog._anim_progress == pytest.approx(1.0)

    def test_exit_reverses_from_current_state(
        self, qapp: QApplication, make_dialog: Callable[..., StyledDialog]
    ) -> None:
        """关闭时反向播放动效，完成后才真正隐藏窗口。"""
        dialog = make_dialog(animate=True)
        dialog.show_dialog()
        qapp.processEvents()
        QTest.qWait(StyledDialog.ANIM_DURATION + 60)
        qapp.processEvents()

        dialog.close()

        assert dialog._is_closing is True
        assert dialog._animating is True
        assert dialog._content_widget.isVisible() is False

        QTest.qWait(StyledDialog.ANIM_DURATION + 60)
        qapp.processEvents()

        assert dialog.isVisible() is False
        assert dialog._is_closing is False
        assert dialog._animating is False
        assert dialog._anim_content_pixmap is None


# =============================================================================
# 宿主窗口归属与模态
# =============================================================================
class TestOwnershipAndModality:
    """parent/modal 参数：owned 顶层窗口 + 自定义模态登记。"""

    def test_parent_makes_owned_top_level_window(
        self, qapp: QApplication, make_dialog: Callable[..., StyledDialog]
    ) -> None:
        """传入 parent → isWindow 为真且瞬态父窗口指向宿主窗口。"""
        owner = QWidget()
        owner.resize(400, 300)
        owner.show()
        qapp.processEvents()
        try:
            dialog = make_dialog(parent=owner)
            dialog.show_dialog()
            qapp.processEvents()

            assert dialog.isWindow() is True, "owned 弹窗必须是顶层窗口（非子控件）"
            assert dialog.parentWidget() is owner
            handle = dialog.windowHandle()
            assert handle is not None
            assert handle.transientParent() is owner.windowHandle()
        finally:
            close_active_dialogs()
            drain_deferred_deletes(qapp)
            safe_teardown(owner)

    def test_no_parent_stays_standalone(
        self, qapp: QApplication, make_dialog: Callable[..., StyledDialog]
    ) -> None:
        """不传 parent 时保持历史行为（无宿主的顶层窗口）。"""
        dialog = make_dialog()
        dialog.show_dialog()
        qapp.processEvents()
        try:
            assert dialog.isWindow() is True
            assert dialog.parentWidget() is None
        finally:
            close_active_dialogs()
            drain_deferred_deletes(qapp)

    def test_modal_true_registers_guard(
        self, qapp: QApplication, make_dialog: Callable[..., StyledDialog]
    ) -> None:
        """modal=True → 守卫登记该弹窗并遮挡宿主窗口。"""
        owner = QWidget()
        owner.resize(400, 300)
        owner.show()
        qapp.processEvents()
        try:
            dialog = make_dialog(parent=owner, modal=True)
            dialog.show_dialog()
            qapp.processEvents()

            guard = get_modal_guard()
            assert guard.active_dialog is dialog
            assert guard.is_blocked(owner) is True
        finally:
            close_active_dialogs()
            drain_deferred_deletes(qapp)
            safe_teardown(owner)

    def test_modal_false_does_not_block(
        self, qapp: QApplication, make_dialog: Callable[..., StyledDialog]
    ) -> None:
        """modal=False（默认）→ 不登记守卫，宿主窗口不受影响。"""
        owner = QWidget()
        owner.resize(400, 300)
        owner.show()
        qapp.processEvents()
        try:
            dialog = make_dialog(parent=owner)
            dialog.show_dialog()
            qapp.processEvents()

            assert get_modal_guard().is_blocked(owner) is False
        finally:
            close_active_dialogs()
            drain_deferred_deletes(qapp)
            safe_teardown(owner)

    def test_closing_modal_dialog_unblocks(
        self, qapp: QApplication, make_dialog: Callable[..., StyledDialog]
    ) -> None:
        """关闭模态弹窗后宿主窗口恢复可交互。"""
        owner = QWidget()
        owner.resize(400, 300)
        owner.show()
        qapp.processEvents()
        try:
            dialog = make_dialog(parent=owner, modal=True)
            dialog.show_dialog()
            qapp.processEvents()
            assert get_modal_guard().is_blocked(owner) is True

            dialog.close_dialog(0)
            qapp.processEvents()

            assert get_modal_guard().is_blocked(owner) is False
        finally:
            close_active_dialogs()
            drain_deferred_deletes(qapp)
            safe_teardown(owner)

    def test_closing_during_exit_animation_unblocks_immediately(
        self, qapp: QApplication, make_dialog: Callable[..., StyledDialog]
    ) -> None:
        """退场动画期间（窗口仍可见）模态与占位已解除，可立刻重开。

        回归：用户关掉弹窗后立刻再点入口，不能因为 180ms 的退场动画而
        「点了没反应」。
        """
        owner = QWidget()
        owner.resize(400, 300)
        owner.show()
        qapp.processEvents()
        try:
            dialog = make_dialog(parent=owner, modal=True, animate=True)
            dialog.show_dialog()
            qapp.processEvents()
            QTest.qWait(StyledDialog.ANIM_DURATION + 60)
            qapp.processEvents()

            dialog.close_dialog(0)
            qapp.processEvents()

            # 动画进行中：窗口仍可见，但遮挡已解除、存活表已反登记
            assert dialog._is_closing is True
            assert dialog.isVisible() is True
            assert get_modal_guard().is_blocked(owner) is False
            assert dialog not in active_dialogs()

            QTest.qWait(StyledDialog.ANIM_DURATION + 60)
            qapp.processEvents()
            assert dialog.isVisible() is False
        finally:
            close_active_dialogs()
            drain_deferred_deletes(qapp)
            safe_teardown(owner)


# =============================================================================
# 存活弹窗登记与统一回收
# =============================================================================
class TestActiveDialogRegistry:
    """``_show_dialog`` 登记 / 反登记与 ``close_active_dialogs``。"""

    def test_show_registers_dialog(
        self, qapp: QApplication, make_dialog: Callable[..., StyledDialog]
    ) -> None:
        """显示后进入存活表，关闭后自动移除。"""
        dialog = make_dialog()
        dialog.show_dialog()
        qapp.processEvents()
        try:
            assert dialog in active_dialogs()

            dialog.close_dialog(0)
            qapp.processEvents()

            assert dialog not in active_dialogs()
        finally:
            close_active_dialogs()
            drain_deferred_deletes(qapp)

    def test_destroyed_dialog_removed(
        self, qapp: QApplication, make_dialog: Callable[..., StyledDialog]
    ) -> None:
        """销毁后自动从存活表移除（不留悬挂引用）。"""
        dialog = make_dialog()
        dialog.show_dialog()
        qapp.processEvents()
        assert dialog in active_dialogs()

        dialog.deleteLater()
        drain_deferred_deletes(qapp)

        assert dialog not in active_dialogs()

    def test_close_active_dialogs_closes_everything(
        self, qapp: QApplication, make_dialog: Callable[..., StyledDialog]
    ) -> None:
        """统一回收关闭全部存活弹窗，且二次调用幂等。"""
        first = make_dialog()
        second = make_dialog()
        first.show_dialog()
        second.show_dialog()
        qapp.processEvents()
        assert len(active_dialogs()) >= 2

        closed = close_active_dialogs()
        qapp.processEvents()

        assert closed >= 2
        assert active_dialogs() == []
        assert first.isVisible() is False
        assert second.isVisible() is False
        # 幂等：再次调用不抛异常
        assert close_active_dialogs() == 0

    def test_close_active_dialogs_filters_by_owner(
        self, qapp: QApplication, make_dialog: Callable[..., StyledDialog]
    ) -> None:
        """传 owner_window 时只关闭该窗口拥有的弹窗。"""
        owner = QWidget()
        owner.resize(400, 300)
        owner.show()
        other = QWidget()
        other.resize(400, 300)
        other.show()
        qapp.processEvents()
        try:
            owned = make_dialog(parent=owner)
            standalone = make_dialog()
            owned.show_dialog()
            standalone.show_dialog()
            qapp.processEvents()

            close_active_dialogs(owner)
            qapp.processEvents()

            assert owned.isVisible() is False
            assert standalone.isVisible() is True
        finally:
            close_active_dialogs()
            drain_deferred_deletes(qapp)
            safe_teardown(owner)
            safe_teardown(other)

    def test_close_skips_exit_animation(
        self, qapp: QApplication, make_dialog: Callable[..., StyledDialog]
    ) -> None:
        """统一回收跳过退场动画（退出路径不能被动画拖住）。"""
        dialog = make_dialog(animate=True)
        dialog.show_dialog()
        qapp.processEvents()

        close_active_dialogs()
        qapp.processEvents()

        assert dialog._animate is False
        assert dialog.isVisible() is False
