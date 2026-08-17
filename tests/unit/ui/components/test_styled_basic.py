# -*- coding: utf-8 -*-
"""styled_* 基础组件单元测试（todo-21 批 1 / task-21）。

覆盖 ui/components 下 26 个 styled_* 组件的构造契约与核心行为：每个组件
以默认参数或关键变体构造不抛异常；属性/信号断言只落在源码与离屏探针确认
过的事实（信号先 connect 再触发、有界等待、不弹真实窗口、不做像素比对）。

验证命令：
    python -m pytest tests/unit/ui/ -k "test_styled_basic" --timeout 30 -q
"""

# targets: ui.components.styled_button, ui.components.styled_lineedit,
#          ui.components.styled_textarea, ui.components.styled_checkbox,
#          ui.components.styled_radio, ui.components.styled_toggle,
#          ui.components.styled_number_input, ui.components.styled_slider,
#          ui.components.styled_tag, ui.components.styled_badge,
#          ui.components.styled_avatar, ui.components.styled_progress,
#          ui.components.styled_progress_circle, ui.components.styled_divider,
#          ui.components.styled_scroll_area, ui.components.styled_tooltip,
#          ui.components.styled_context_menu, ui.components.styled_dialog,
#          ui.components.styled_drawer, ui.components.styled_notification_badge,
#          ui.components.styled_info_card, ui.components.styled_segmented,
#          ui.components.styled_steps, ui.components.styled_breadcrumb,
#          ui.components.styled_combobox, ui.components.styled_color_picker

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QEvent, QPointF, QRect, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QEnterEvent,
    QHoverEvent,
    QMouseEvent,
    QPaintEvent,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

# 组件模块内部使用短路径导入（from theme import tm / components.*），
# 要求 freeassetfilter/ui 位于 sys.path；与 tests/unit/ui/layout 下
# test_layouts.py 的 bootstrap 方式保持一致。
_UI_ROOT: str = str(Path(__file__).resolve().parents[4] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from tests.support.qt_helpers import wait_for_signal  # noqa: E402

from freeassetfilter.ui.components.styled_avatar import AvatarGroup, StyledAvatar  # noqa: E402
from freeassetfilter.ui.components.styled_badge import BadgeWrapper, StyledBadge  # noqa: E402
from freeassetfilter.ui.components.styled_breadcrumb import (  # noqa: E402
    BreadcrumbLink,
    StyledBreadcrumb,
    parse_svg_path,
)
from freeassetfilter.ui.components.styled_button import StyledButton  # noqa: E402
from freeassetfilter.ui.components.styled_checkbox import StyledCheckbox  # noqa: E402
from freeassetfilter.ui.components.styled_color_picker import BG_INPUT, StyledColorPicker  # noqa: E402
from freeassetfilter.ui.components.styled_combobox import StyledComboBox  # noqa: E402
from freeassetfilter.ui.components.styled_context_menu import StyledContextMenu  # noqa: E402
from freeassetfilter.ui.components.styled_dialog import (  # noqa: E402
    DialogAnimationEffect,
    DialogIconCircle,
    StyledDialog,
    create_basic_dialog,
    create_center_button_dialog,
    create_custom_dialog,
    create_danger_dialog,
    create_help_link_dialog,
    create_info_dialog,
    create_input_dialog,
    create_large_dialog,
    create_left_button_dialog,
    create_no_border_dialog,
    create_no_footer_dialog,
    create_progress_circular_dialog,
    create_progress_download_dialog,
    create_progress_linear_dialog,
    create_small_dialog,
    create_stacked_button_dialog,
    create_success_dialog,
    create_three_button_dialog,
)
from freeassetfilter.ui.components.styled_divider import StyledDivider  # noqa: E402
from freeassetfilter.ui.components.styled_drawer import StyledDrawer  # noqa: E402
from freeassetfilter.ui.components.styled_info_card import StyledInfoCard  # noqa: E402
from freeassetfilter.ui.components.styled_lineedit import InputWrapper, StyledLineEdit  # noqa: E402
from freeassetfilter.ui.components.styled_notification_badge import (  # noqa: E402
    NotificationBadgeList,
    NotificationItem,
)
from freeassetfilter.ui.components.styled_number_input import StyledNumberInput  # noqa: E402
from freeassetfilter.ui.components.styled_progress import ProgressTrack, StyledProgress  # noqa: E402
from freeassetfilter.ui.components.styled_progress_circle import CircleWidget, StyledProgressCircle  # noqa: E402
from freeassetfilter.ui.components.styled_radio import StyledRadio  # noqa: E402
from freeassetfilter.ui.components.styled_scroll_area import StyledScrollArea, StyledScrollBar  # noqa: E402
from freeassetfilter.ui.components.styled_segmented import StyledSegmented  # noqa: E402
from freeassetfilter.ui.components.styled_slider import SliderTrack, StyledSlider  # noqa: E402
from freeassetfilter.ui.components.styled_steps import StepWidget, StyledSteps  # noqa: E402
from freeassetfilter.ui.components.styled_tag import StyledTag  # noqa: E402
from freeassetfilter.ui.components.styled_textarea import StyledTextarea  # noqa: E402
from freeassetfilter.ui.components.styled_toggle import StyledToggle  # noqa: E402
from freeassetfilter.ui.components.styled_tooltip import StyledTooltip  # noqa: E402

pytestmark = pytest.mark.unit


# =============================================================================
# ui.components.styled_button
# =============================================================================
class TestStyledButton:
    """StyledButton：构造契约、默认文案与变体设置。"""

    def test_construct_and_text(self, qapp: QApplication) -> None:
        """指定文案构造，text() 经 QPushButton 语义可见。"""
        btn = StyledButton("Hi")
        assert isinstance(btn, QPushButton)
        assert btn.text() == "Hi"
        btn.deleteLater()

    def test_set_variant_and_icon(self, qapp: QApplication) -> None:
        """set_variant / set_svg_icon 不抛异常（离屏探针确认）。"""
        btn = StyledButton("OK", variant="primary")
        btn.set_variant("primary")
        btn.set_svg_icon("")
        assert btn.text() == "OK"
        btn.deleteLater()


# =============================================================================
# ui.components.styled_lineedit
# =============================================================================
class TestStyledLineEdit:
    """StyledLineEdit：构造契约、error 状态切换与 InputWrapper。"""

    def test_construct_and_text(self, qapp: QApplication) -> None:
        """构造 + text 经 QLineEdit 语义可见。"""
        le = StyledLineEdit("hello", size="lg")
        assert le.text() == "hello"
        le.deleteLater()

    def test_error_property(self, qapp: QApplication) -> None:
        """error 属性可写（setter 生效）。"""
        le = StyledLineEdit(error=True)
        le.error = False
        assert le.error is False
        le.deleteLater()

    def test_input_wrapper_construct(self, qapp: QApplication) -> None:
        """InputWrapper 默认构造不抛。"""
        wrapper = InputWrapper(placeholder="search", size="sm")
        assert wrapper is not None
        wrapper.deleteLater()


# =============================================================================
# ui.components.styled_textarea
# =============================================================================
class TestStyledTextarea:
    """StyledTextarea：text_changed 信号与 text 属性（内嵌 QPlainTextEdit）。"""

    def test_text_changed_signal(self, qapp: QApplication) -> None:
        """先 connect 再注入文本：text_changed 发射且 text 属性同步。"""
        ta = StyledTextarea(label="Notes")
        received: list[str] = []
        ta.text_changed.connect(received.append)
        ta._text_edit.setPlainText("xyz")
        assert received == ["xyz"]
        assert ta.text == "xyz"
        ta.deleteLater()


# =============================================================================
# ui.components.styled_checkbox
# =============================================================================
class TestStyledCheckbox:
    """StyledCheckbox：toggle 发射 toggled 并更新 checked / indeterminate。"""

    def test_toggle_emits_and_checks(self, qapp: QApplication) -> None:
        """toggle() 后 checked=True，toggled 发射 [True]，indeterminate 清除。"""
        cb = StyledCheckbox(indeterminate=True)
        received: list[bool] = []
        cb.toggled.connect(received.append)
        cb.toggle()
        assert received == [True]
        assert cb.checked is True
        assert cb.indeterminate is False
        cb.deleteLater()


# =============================================================================
# ui.components.styled_radio
# =============================================================================
class TestStyledRadio:
    """StyledRadio：同组互斥与 toggled 发射（cleanup 清理全局组表）。"""

    def test_group_mutual_exclusion(self, qapp: QApplication) -> None:
        """同一 group_name 的两个 radio：选中一个后另一个自动取消。"""
        r1 = StyledRadio(checked=False, text="A", group_name="test-group")
        r2 = StyledRadio(checked=False, text="B", group_name="test-group")
        r1.toggle()
        assert r1.checked is True
        assert r2.checked is False
        r2.toggle()
        assert r2.checked is True
        assert r1.checked is False
        r1.cleanup()
        r2.cleanup()
        r1.deleteLater()
        r2.deleteLater()


# =============================================================================
# ui.components.styled_toggle
# =============================================================================
class TestStyledToggle:
    """StyledToggle：toggle 发射 toggled 并更新 checked。"""

    def test_toggle_emits(self, qapp: QApplication) -> None:
        """toggle() 后 checked=True 且 toggled 发射。"""
        tg = StyledToggle()
        received: list[bool] = []
        tg.toggled.connect(received.append)
        tg.toggle()
        assert received == [True]
        assert tg.checked is True
        tg.deleteLater()


# =============================================================================
# ui.components.styled_number_input
# =============================================================================
class TestStyledNumberInput:
    """StyledNumberInput：构造钳制（value 参数受限到 [min,max]）。"""

    def test_ctor_stores_value(self, qapp: QApplication) -> None:
        """构造保留原始 value（钳制仅经 value setter 生效）。"""
        first = StyledNumberInput(value=2, min_val=0, max_val=10)
        assert first.value == 2
        first.deleteLater()

    def test_value_setter_clamps(self, qapp: QApplication) -> None:
        """value setter 钳制到 [min, max]：50→10，-5→0。"""
        ni = StyledNumberInput(value=5, min_val=0, max_val=10)
        ni.value = 50
        assert ni.value == 10
        ni.value = -5
        assert ni.value == 0
        ni.deleteLater()

    def test_step_delta_and_clamp(self, qapp: QApplication) -> None:
        """_change_value 按 step 增减并在 max 处钳制（探针确认 5+7→10）。"""
        ni = StyledNumberInput(value=5, min_val=0, max_val=10, step=2)
        ni._change_value(7)
        assert ni.value == 10
        ni.deleteLater()


# =============================================================================
# ui.components.styled_slider
# =============================================================================
class TestStyledSlider:
    """StyledSlider：value 属性钳制在 [0,1]，可为 Qt Property 赋值。"""

    def test_value_clamp_and_set(self, qapp: QApplication) -> None:
        """value=2.0 clamps 到 1.0；程序化赋值不回读发射（探针确认 received=[]）。"""
        sl = StyledSlider(2.0)
        assert sl.value == 1.0
        received: list[float] = []
        sl.value_changed.connect(received.append)
        sl.value = 0.9
        assert sl.value == 0.9
        assert received == []
        sl.deleteLater()

    def test_track_construct(self, qapp: QApplication) -> None:
        """SliderTrack 默认构造不抛。"""
        track = SliderTrack(value=0.3, track_height=6, thumb_radius=9)
        assert track.value == 0.3
        track.deleteLater()


# =============================================================================
# ui.components.styled_tag
# =============================================================================
class TestStyledTag:
    """StyledTag：closable 关闭按钮点击发射 closed 并 hide。"""

    def test_close_button_emits_closed(self, qapp: QApplication) -> None:
        """closable=True 时存在 _close_btn；点击后 closed 发射且 tag 隐藏。"""
        tag = StyledTag("Tag", closable=True)
        received: list[bool] = []
        tag.closed.connect(lambda: received.append(True))
        assert tag.closable is True
        assert tag._close_btn is not None
        tag._close_btn.clicked.emit()
        assert received == [True]
        assert tag.isHidden() is True
        tag.deleteLater()

    def test_properties(self, qapp: QApplication) -> None:
        """text/variant/size_variant/closable/pill 属性可读且 setter 生效。"""
        tag = StyledTag("X", variant="danger", size="sm", pill=True)
        assert tag.text == "X"
        assert tag.variant == "danger"
        assert tag.size_variant == "sm"
        assert tag.pill is True
        tag.text = "Y"
        assert tag.text == "Y"
        tag.deleteLater()


# =============================================================================
# ui.components.styled_badge
# =============================================================================
class TestStyledBadge:
    """StyledBadge：文本/变体属性与 BadgeWrapper 构造契约。"""

    def test_construct_and_text(self, qapp: QApplication) -> None:
        """构造 text/variant 生效（探针确认 text='NEW' variant='dot'）。"""
        badge = StyledBadge(text="NEW", variant="dot")
        assert badge.text == "NEW"
        assert badge.variant == "dot"
        badge.deleteLater()

    def test_badge_wrapper(self, qapp: QApplication) -> None:
        """BadgeWrapper(child, badge) 组合构造不抛。"""
        child = QWidget()
        badge = StyledBadge(text="9")
        wrapper = BadgeWrapper(child, badge)
        assert wrapper is not None
        wrapper.deleteLater()
        badge.deleteLater()
        child.deleteLater()


# =============================================================================
# ui.components.styled_avatar
# =============================================================================
class TestStyledAvatar:
    """StyledAvatar：text 属性（构造注入）与 setPixmap 清空文本。"""

    def test_text_property(self, qapp: QApplication) -> None:
        """构造 text='JD' → text 属性返回 'JD'（源码确认 _text=text）。"""
        av = StyledAvatar("JD", size="default")
        assert av.text == "JD"
        assert av.shape == "circle"
        av.text = "AB"
        assert av.text == "AB"
        av.deleteLater()

    def test_avatar_group(self, qapp: QApplication) -> None:
        """AvatarGroup.addAvatar 追加布局不抛。"""
        group = AvatarGroup()
        av1 = StyledAvatar("A")
        av2 = StyledAvatar("B")
        group.addAvatar(av1)
        group.addAvatar(av2)
        assert group is not None
        group.deleteLater()
        av1.deleteLater()
        av2.deleteLater()


# =============================================================================
# ui.components.styled_progress
# =============================================================================
class TestStyledProgress:
    """StyledProgress：value 钳制；variant 白名单外回退 default。"""

    def test_value_clamp(self, qapp: QApplication) -> None:
        """value=1.5 → 1.0；value=-0.3 → 0.0。"""
        p = StyledProgress(value=1.5)
        assert p.value == 1.0
        p.value = -0.3
        assert p.value == 0.0
        p.deleteLater()

    def test_variant_fallback(self, qapp: QApplication) -> None:
        """COLOR_CONFIG 无 'primary'：构造回退 default；setter 白名单生效。"""
        p = StyledProgress(value=0.4, variant="primary")
        assert p.variant == "default"
        p.variant = "warning"
        assert p.variant == "warning"
        p.deleteLater()

    def test_set_label(self, qapp: QApplication) -> None:
        """带 label_title/label_value 构造 + set_label 不抛。"""
        p = StyledProgress(value=0.5, label_title="T", label_value="V")
        p.set_label(title="A", value="B")
        p.set_value_label("50%")
        p.deleteLater()

    def test_track_construct(self, qapp: QApplication) -> None:
        """ProgressTrack 默认构造不抛。"""
        track = ProgressTrack(value=0.6, track_height=8)
        assert track.value == 0.6
        track.deleteLater()


# =============================================================================
# ui.components.styled_progress_circle
# =============================================================================
class TestStyledProgressCircle:
    """StyledProgressCircle：value 可读写（Qt Property）。"""

    def test_value_settable(self, qapp: QApplication) -> None:
        """默认 0.6；程序化赋值回读一致。"""
        circle = StyledProgressCircle(value=0.6, size="md")
        circle.value = 0.25
        assert circle.value == 0.25
        circle.deleteLater()


# =============================================================================
# ui.components.styled_divider
# =============================================================================
class TestStyledDivider:
    """StyledDivider：orientation/text/thick/dashed 属性。"""

    def test_properties(self, qapp: QApplication) -> None:
        """构造参数写入属性并可回读。"""
        div = StyledDivider(
            orientation="horizontal", text="section", thick=True, dashed=True
        )
        assert div.orientation == "horizontal"
        assert div.text == "section"
        assert div.thick is True
        assert div.dashed is True
        div.deleteLater()


# =============================================================================
# ui.components.styled_scroll_area
# =============================================================================
class TestStyledScrollArea:
    """StyledScrollArea：构造契约与 child 挂载。"""

    def test_construct_and_set_widget(self, qapp: QApplication) -> None:
        """默认构造 + setWidget(child) 不抛。"""
        area = StyledScrollArea()
        child = QWidget()
        area.setWidget(child)
        assert area.widget() is child
        area.deleteLater()
        child.deleteLater()


# =============================================================================
# ui.components.styled_tooltip
# =============================================================================
class TestStyledTooltip:
    """StyledTooltip：以宿主 widget 构造不抛（不 show、无真实窗口）。"""

    def test_construct(self, qapp: QApplication) -> None:
        """host + text + placement 构造（探针确认可构造）。"""
        host = QWidget()
        tip = StyledTooltip(host, "tip text", placement="bottom")
        assert tip is not None
        tip.deleteLater()
        host.deleteLater()


# =============================================================================
# ui.components.styled_context_menu
# =============================================================================
class TestStyledContextMenu:
    """StyledContextMenu：add_item / add_separator / add_submenu 契约。"""

    def test_add_item_and_callback(self, qapp: QApplication) -> None:
        """add_item(label) 返回 QAction；trigger 时 callback 以零参调用。"""
        menu = StyledContextMenu(title="menu")
        called: list[bool] = []
        action = menu.add_item("One", callback=lambda: called.append(True))
        assert action is not None
        action.trigger()
        assert called == [True]
        menu.add_separator()
        assert len(menu.actions()) >= 2
        menu.deleteLater()

    def test_add_submenu(self, qapp: QApplication) -> None:
        """add_submenu(label, menu) 返回 QAction。"""
        menu = StyledContextMenu()
        sub = StyledContextMenu()
        action = menu.add_submenu("More", sub)
        assert action is not None
        menu.deleteLater()
        sub.deleteLater()


# =============================================================================
# ui.components.styled_dialog
# =============================================================================
class TestStyledDialog:
    """StyledDialog / DialogIconCircle：构造契约（不 show、不弹真实窗口）。"""

    def test_construct_no_animate(self, qapp: QApplication) -> None:
        """animate=False 构造（默认 footer_type/尺寸）不抛。"""
        dialog = StyledDialog(animate=False, title="T", footer_type="right")
        assert dialog is not None
        dialog.deleteLater()

    def test_icon_circle_types(self, qapp: QApplication) -> None:
        """success/danger/info 三种图标圆环构造不抛。"""
        for icon_type in ("success", "danger", "info"):
            circle = DialogIconCircle(icon_type=icon_type)
            assert circle is not None
            circle.deleteLater()


# =============================================================================
# ui.components.styled_drawer
# =============================================================================
class TestStyledDrawer:
    """StyledDrawer：构造契约与 open/close 状态机（有界等待动画完成）。"""

    def test_construct_bare(self, qapp: QApplication) -> None:
        """裸模式（bare=True, 无 body）构造不抛。"""
        drawer = StyledDrawer(orientation="right", title="T", bare=True)
        assert drawer is not None
        drawer.deleteLater()

    def test_open_close_roundtrip(self, qapp: QApplication) -> None:
        """open_drawer 后 opened 发射（滑动动画完成），close 后 closed + 隐藏。"""
        container = QWidget()
        drawer = StyledDrawer(orientation="right", parent=container)
        drawer.open_drawer()
        assert wait_for_signal(drawer.opened, timeout_ms=2000) is True
        drawer.close_drawer()
        assert wait_for_signal(drawer.closed, timeout_ms=2000) is True
        assert drawer.isHidden() is True
        drawer.deleteLater()
        container.deleteLater()


# =============================================================================
# ui.components.styled_notification_badge
# =============================================================================
class TestNotificationBadge:
    """NotificationItem / NotificationBadgeList：入列-计数-清空与转发信号。"""

    def test_add_count_clear(self, qapp: QApplication) -> None:
        """add_item 后 item_count=1，clear_items 归零（unread=False 无动画）。"""
        lst = NotificationBadgeList()
        item = NotificationItem("bell", "Title", "Desc", "now", unread=False)
        lst.add_item(item)
        assert lst.item_count() == 1
        lst.clear_items()
        assert lst.item_count() == 0
        lst.deleteLater()
        item.deleteLater()

    def test_item_clicked_forwarded(self, qapp: QApplication) -> None:
        """item.clicked 转发为 list.item_clicked(index)。"""
        lst = NotificationBadgeList()
        item = NotificationItem("bell", "T", "D", "now", index=0, unread=False)
        received: list[int] = []
        lst.item_clicked.connect(received.append)
        lst.add_item(item)
        item.clicked.emit(0)
        assert received == [0]
        lst.deleteLater()
        item.deleteLater()

    def test_set_count(self, qapp: QApplication) -> None:
        """set_count 覆盖内部计数徽章（自定义绘制 _CountBadge，无 .text()）。"""
        lst = NotificationBadgeList()
        lst.set_count(5)
        assert lst._count_badge._count == 5
        lst.deleteLater()


# =============================================================================
# ui.components.styled_info_card
# =============================================================================
class TestStyledInfoCard:
    """StyledInfoCard：选中/预览 2 参信号与 action 生命周期。"""

    def test_selection_signal(self, qapp: QApplication) -> None:
        """set_file_path 后 set_selected(True) 发射 selection_changed(True, path)。"""
        card = StyledInfoCard(layout_mode="horizontal", title="T")
        received: list[tuple[bool, str]] = []
        card.selection_changed.connect(lambda s, p: received.append((s, p)))
        card.set_file_path("C:/x/file.png")
        card.set_selected(True)
        assert received == [(True, "C:/x/file.png")]
        received.clear()
        card.set_selected(False)
        assert received == [(False, "C:/x/file.png")]
        card.deleteLater()

    def test_preview_signal(self, qapp: QApplication) -> None:
        """set_previewing(True) 发射 preview_state_changed(True, path)。"""
        card = StyledInfoCard()
        received: list[tuple[bool, str]] = []
        card.preview_state_changed.connect(lambda s, p: received.append((s, p)))
        card.set_previewing(True)
        assert received == [(True, "")]
        received.clear()
        card.set_previewing(False)  # 停止内部 16ms 预览渐变动画
        assert received == [(False, "")]
        card.deleteLater()

    def test_actions_and_scale(self, qapp: QApplication) -> None:
        """add_action/clear_actions/set_scale 不抛且 actions 可清空。"""
        card = StyledInfoCard(overlay_enabled=True)
        card.add_action("Open", callback=lambda: None)
        card.add_action("Delete", icon="", variant="danger", callback=lambda: None)
        assert len(card._actions) == 2
        card.set_scale(1.5)
        card.clear_actions()
        assert len(card._actions) == 0
        card.deleteLater()


# =============================================================================
# ui.components.styled_segmented
# =============================================================================
class TestStyledSegmented:
    """StyledSegmented：add_segment 返回值/计数、索引切换与清空。"""

    def test_segments_and_index(self, qapp: QApplication) -> None:
        """add_segment 返回索引，set_current_index 切换时发射 current_changed。"""
        seg = StyledSegmented()
        assert seg.add_segment("One") == 0
        assert seg.add_segment("Two") == 1
        assert seg.add_segment("Three") == 2
        assert seg.segment_count() == 3
        assert seg.current_index == 0  # 首个分段自动选中
        received: list[int] = []
        seg.current_changed.connect(received.append)
        seg.set_current_index(2)
        assert received == [2]
        assert seg.current_index == 2
        seg.clear()
        assert seg.segment_count() == 0
        seg.deleteLater()

    def test_set_segment_disabled(self, qapp: QApplication) -> None:
        """禁用分段后切换不生效。"""
        seg = StyledSegmented()
        seg.add_segment("A")
        seg.add_segment("B")
        seg.set_segment_disabled(1, True)
        seg.set_current_index(1)
        assert seg.current_index == 0
        seg.deleteLater()


# =============================================================================
# ui.components.styled_steps
# =============================================================================
class TestStyledSteps:
    """StyledSteps：add_step 索引、StepWidget 点击转发与 current_step 回退。"""

    def test_add_step_and_click(self, qapp: QApplication) -> None:
        """add_step 返回索引；步骤点击经 step_clicked 转发索引。"""
        steps = StyledSteps()
        assert steps.add_step("Step1", "desc1") == 0
        assert steps.add_step("Step2", "desc2") == 1
        assert len(steps._steps) == 2
        received: list[int] = []
        steps.step_clicked.connect(received.append)
        steps._steps[0].clicked.emit(0)
        assert received == [0]
        steps.clear()
        assert len(steps._steps) == 0
        steps.deleteLater()

    def test_current_step_rollback(self, qapp: QApplication) -> None:
        """未设置时 current_step 为 -1；clear 后回退 -1。"""
        steps = StyledSteps()
        assert steps.current_step == -1
        steps.add_step("A")
        steps.add_step("B")
        steps.current_step = 1
        assert steps.current_step == 1
        steps.clear()
        assert steps.current_step == -1
        steps.deleteLater()

    def test_step_widget_construct(self, qapp: QApplication) -> None:
        """StepWidget 独立构造 + step_state 读写。"""
        sw = StepWidget(title="Step1", description="desc1", state="current", index=0)
        assert sw.step_state == "current"
        sw.step_state = "completed"
        assert sw.step_state == "completed"
        sw.deleteLater()


# =============================================================================
# ui.components.styled_breadcrumb
# =============================================================================
class TestStyledBreadcrumb:
    """StyledBreadcrumb：add_item/set_items/clear 与 navigated 信号。"""

    def test_add_item_and_navigated(self, qapp: QApplication) -> None:
        """点击第一个链接 → navigated(index, text)。"""
        bc = StyledBreadcrumb(separator=">")
        bc.add_item("Home")
        bc.add_item("Docs")
        received: list[tuple[int, str]] = []
        bc.navigated.connect(lambda i, t: received.append((i, t)))
        bc._link_widgets[0].clicked.emit(0)
        assert received == [(0, "Home")]
        bc.deleteLater()

    def test_set_items_and_clear(self, qapp: QApplication) -> None:
        """set_items 整体替换 + clear 清空。"""
        bc = StyledBreadcrumb()
        bc.set_items([{"text": "A"}, {"text": "B"}, {"text": "C"}])
        assert len(bc._link_widgets) == 3
        bc.clear()
        assert len(bc._link_widgets) == 0
        bc.deleteLater()


# =============================================================================
# ui.components.styled_combobox
# =============================================================================
class TestStyledComboBox:
    """StyledComboBox：currentText/setCurrentText/setCurrentIndex 与信号。"""

    def test_current_text_and_signal(self, qapp: QApplication) -> None:
        """setCurrentText('B') → currentText 更新 + current_index_changed 发射一次。"""
        combo = StyledComboBox(items=["A", "B", "C"], size="default")
        assert combo.count() == 3
        assert combo.currentText() == "A"
        received: list[int] = []
        combo.current_index_changed.connect(received.append)
        combo.setCurrentText("B")
        assert combo.currentText() == "B"
        assert received == [1]
        combo.setCurrentIndex(0)
        assert combo.currentText() == "A"
        assert received == [1, 0]
        combo.deleteLater()


# =============================================================================
# ui.components.styled_color_picker
# =============================================================================
class TestStyledColorPicker:
    """StyledColorPicker：color 属性与 HEX 输入编辑触发 color_changed。"""

    def test_hex_edit_updates_color(self, qapp: QApplication) -> None:
        """_hex_input 输入 '#00FF00' + _on_hex_edited → color 更新 + 信号发射。"""
        picker = StyledColorPicker(color="#000000", enabled=True)
        received: list[str] = []
        picker.color_changed.connect(received.append)
        picker._hex_input.setText("#00FF00")
        picker._on_hex_edited()
        assert picker.color == "#00FF00"
        assert received == ["#00FF00"]
        picker.deleteLater()

    def test_color_property_setter(self, qapp: QApplication) -> None:
        """color setter 归一化回读（大写）+ 发射 color_changed。"""
        picker = StyledColorPicker(color="#000000")
        received: list[str] = []
        picker.color_changed.connect(received.append)
        picker.color = "#123456"
        assert picker.color == "#123456"
        assert received == ["#123456"]
        picker.deleteLater()


# =============================================================================
# ui.components.styled_breadcrumb —— BreadcrumbLink / parse_svg_path
# =============================================================================
class TestBreadcrumbLink:
    """BreadcrumbLink：点击信号、部位状态与 SVG 路径解析。"""

    def test_construct_and_active_toggle(self, qapp: QApplication) -> None:
        """active 属性默认 False，写入 True 后回读一致。"""
        link = BreadcrumbLink("Home", 0, active=False)
        assert link.active is False
        link.active = True
        assert link.active is True
        link.deleteLater()

    def test_click_emits_clicked(self, qapp: QApplication) -> None:
        """非 active 链接左键点击 → clicked(index) 发射。"""
        link = BreadcrumbLink("Docs", 2, active=False)
        received: list[int] = []
        link.clicked.connect(received.append)
        press = QMouseEvent(
            QEvent.MouseButtonPress, QPointF(8.0, 6.0),
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
        )
        link.mousePressEvent(press)
        assert received == [2]
        link.deleteLater()

    def test_active_link_does_not_emit(self, qapp: QApplication) -> None:
        """active 链接点击被忽略（curren page 不可导航）。"""
        link = BreadcrumbLink("Home", 0, active=True)
        received: list[int] = []
        link.clicked.connect(received.append)
        press = QMouseEvent(
            QEvent.MouseButtonPress, QPointF(8.0, 6.0),
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
        )
        link.mousePressEvent(press)
        assert received == []
        link.deleteLater()

    def test_paint_and_hover_roundtrip(self, qapp: QApplication) -> None:
        """enterEvent/leaveEvent 翻转 _hovered；paintEvent 不抛。"""
        link = BreadcrumbLink("Home", 0)
        link.enterEvent(
            QEnterEvent(QPointF(5.0, 5.0), QPointF(5.0, 5.0), QPointF(5.0, 5.0))
        )
        assert link._hovered is True
        link.paintEvent(QPaintEvent(link.rect()))
        link.leaveEvent(QEvent(QEvent.Leave))
        assert link._hovered is False
        link.deleteLater()

    def test_parse_svg_path(self, qapp: QApplication) -> None:
        """M/L/Z 路径解析出非空 QPainterPath；空串为空路径。"""
        path = parse_svg_path("M10 10 L50 10 L50 50 Z")
        assert path.elementCount() > 0
        empty = parse_svg_path("")
        assert empty.isEmpty() is True


# =============================================================================
# ui.components.styled_color_picker —— BG_INPUT
# =============================================================================
class TestColorPickerBgInput:
    """BG_INPUT：从主题管理器惰性取色的 QColor 工厂。"""

    def test_returns_qcolor(self, qapp: QApplication) -> None:
        """BG_INPUT() 返回 QColor 实例（离屏探针确认）。"""
        assert isinstance(BG_INPUT(), QColor)


# =============================================================================
# ui.components.styled_dialog —— DialogAnimationEffect 与 create_*_dialog 工厂
# =============================================================================
class TestDialogAnimationEffect:
    """DialogAnimationEffect：opacity/scale 属性钳制与空源 draw。"""

    def test_opacity_and_scale(self, qapp: QApplication) -> None:
        """opacity/scale 可读写；draw 在空源时走 drawSource 不抛。"""
        host = QWidget()
        effect = DialogAnimationEffect(host)
        effect.opacity = 0.5
        assert effect.opacity == 0.5
        effect.scale = 0.9
        assert effect.scale == 0.9
        pixmap = QPixmap(100, 100)
        painter = QPainter(pixmap)
        effect.draw(painter)
        painter.end()
        effect.deleteLater()
        host.deleteLater()

    def test_property_clamp(self, qapp: QApplication) -> None:
        """opacity 钳到 [0,1]，scale 钳到 >=0。"""
        host = QWidget()
        effect = DialogAnimationEffect(host)
        effect.opacity = 2.0
        assert effect.opacity == 1.0
        effect.opacity = -1.0
        assert effect.opacity == 0.0
        effect.scale = -1.0
        assert effect.scale == 0.0
        effect.deleteLater()
        host.deleteLater()


class TestDialogFactories:
    """create_*_dialog 工厂：拦截 _show_dialog 后全部返回 StyledDialog。"""

    @pytest.fixture(autouse=True)
    def _suppress_show(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """将模块级 _show_dialog 替换为 no-op，避免测试弹出真实窗口。"""
        import freeassetfilter.ui.components.styled_dialog as _sd

        monkeypatch.setattr(_sd, "_show_dialog", lambda dialog: None)

    def test_all_factories_return_dialog(self, qapp: QApplication) -> None:
        """全部 18 个工厂（animate=False）均返回 StyledDialog 实例。"""
        dialogs = [
            create_basic_dialog(animate=False),
            create_center_button_dialog(animate=False),
            create_custom_dialog("标题", "消息", ["确定", "取消"], animate=False),
            create_danger_dialog(animate=False),
            create_help_link_dialog(animate=False),
            create_info_dialog(animate=False),
            create_input_dialog(animate=False),
            create_large_dialog(animate=False),
            create_left_button_dialog(animate=False),
            create_no_border_dialog(animate=False),
            create_no_footer_dialog(animate=False),
            create_progress_circular_dialog(animate=False),
            create_progress_download_dialog(animate=False),
            create_progress_linear_dialog(animate=False),
            create_small_dialog(animate=False),
            create_stacked_button_dialog(animate=False),
            create_success_dialog(animate=False),
            create_three_button_dialog(animate=False),
        ]
        for dialog in dialogs:
            assert isinstance(dialog, StyledDialog)
        for dialog in dialogs:
            dialog.close_dialog(0)
            dialog.deleteLater()


# =============================================================================
# ui.components.styled_progress_circle —— CircleWidget
# =============================================================================
class TestCircleWidget:
    """CircleWidget：anim_value 动画属性与 value 同步。"""

    def test_anim_value_property(self, qapp: QApplication) -> None:
        """构造 anim_value=value；anim_value 可写回读。"""
        circle = CircleWidget(value=0.5, radius=26, stroke_width=5)
        assert circle.anim_value == 0.5
        circle.anim_value = 0.3
        assert circle.anim_value == 0.3
        circle.deleteLater()

    def test_value_clamped_and_paint(self, qapp: QApplication) -> None:
        """value setter 钳到 [0,1]；paintEvent 不抛（offscreen 探针）。"""
        circle = CircleWidget(value=0.0)
        circle.value = 1.5
        assert circle.value == 1.0
        circle.value = -0.3
        assert circle.value == 0.0
        circle.paintEvent(QPaintEvent(circle.rect()))
        circle.deleteLater()


# =============================================================================
# ui.components.styled_scroll_area —— StyledScrollBar
# =============================================================================
class TestStyledScrollBar:
    """StyledScrollBar：构造/configure/sizeHint/交互事件。"""

    def test_configure_and_sizehint(self, qapp: QApplication) -> None:
        """configure 更新视觉度量；sizeHint 返回固定 (8,100)。"""
        bar = StyledScrollBar()
        assert bar.sizeHint() == QSize(8, 100)
        bar.configure(normal_width=6, hover_width=9, padding=3)
        assert bar._bar_width == 6
        assert bar._hover_width == 9
        assert bar._padding == 3
        bar.deleteLater()

    def test_hover_event_roundtrip(self, qapp: QApplication) -> None:
        """HoverEnter 置 _hovered，HoverLeave 清除；paint 不抛。"""
        bar = StyledScrollBar()
        bar.setRange(0, 100)
        bar.resize(12, 200)
        pos = QPointF(6.0, 6.0)
        bar.event(QHoverEvent(QEvent.HoverEnter, pos, pos))
        assert bar._hovered is True
        bar.paintEvent(QPaintEvent(bar.rect()))
        bar.event(QHoverEvent(QEvent.HoverLeave, pos, pos))
        assert bar._hovered is False
        bar.deleteLater()

    def test_mouse_drag_track(self, qapp: QApplication) -> None:
        """左键按/移/放经真实 QMouseEvent 驱动不抛（轨道跳转分支）。"""
        bar = StyledScrollBar()
        bar.setRange(0, 100)
        bar.setPageStep(10)
        bar.resize(12, 200)
        press = QMouseEvent(
            QEvent.MouseButtonPress, QPointF(6.0, 50.0),
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
        )
        move = QMouseEvent(
            QEvent.MouseMove, QPointF(6.0, 60.0),
            Qt.NoButton, Qt.LeftButton, Qt.NoModifier,
        )
        release = QMouseEvent(
            QEvent.MouseButtonRelease, QPointF(6.0, 60.0),
            Qt.LeftButton, Qt.NoButton, Qt.NoModifier,
        )
        bar.mousePressEvent(press)
        bar.mouseMoveEvent(move)
        bar.mouseReleaseEvent(release)
        assert bar.value() >= 0
        bar.deleteLater()