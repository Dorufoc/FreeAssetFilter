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
from PySide6.QtWidgets import QApplication

# 组件模块内部使用短路径导入（from theme import tm），
# 要求 freeassetfilter/ui 位于 sys.path；与 test_styled_basic.py 一致。
_UI_ROOT: str = str(Path(__file__).resolve().parents[4] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from tests.support.qt_helpers import drain_deferred_deletes, safe_teardown  # noqa: E402

import freeassetfilter.ui.components.styled_dialog as styled_dialog_module  # noqa: E402
from freeassetfilter.ui.components.styled_button import StyledButton  # noqa: E402
from freeassetfilter.ui.components.styled_dialog import (  # noqa: E402
    FOOTER_NONE,
    FOOTER_RIGHT,
    SIZE_CONFIG,
    StyledDialog,
)
from freeassetfilter.ui.layout import update_dialogs  # noqa: E402

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
