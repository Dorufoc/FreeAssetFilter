# -*- coding: utf-8 -*-
"""StyledSegmented 单元测试

测试 freeassetfilter/ui/components/styled_segmented.py 的公共接口：
- API 面（add_segment / current_index / set_current_index / current_changed /
  segment_count / clear / set_segment_disabled / variant / size）
- 默认选中第一个段
- set_current_index 发射 current_changed 信号
- 重复点击同一段不重发信号；越界 / 禁用段无操作
- 非法 variant / size 值被忽略
- 键盘导航（Left / Right / Home / End），跳过禁用段
- 动画属性（indicator_pos / indicator_width 与 QPropertyAnimation）存在
"""

import sys
from pathlib import Path

# 将 freeassetfilter/ui 目录暴露为 ``theme`` / ``components`` 短路径导入根
_UI_ROOT = str(Path(__file__).resolve().parents[4] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

import pytest

from PySide6.QtCore import Qt, QPropertyAnimation
from PySide6.QtTest import QTest

from freeassetfilter.ui.components.styled_segmented import StyledSegmented


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def segmented(qapp) -> StyledSegmented:
    """创建并返回一个独立的 StyledSegmented 实例（pill 变体）。"""
    widget = StyledSegmented(variant="pill", size="default")
    widget.resize(400, 60)
    try:
        yield widget
    finally:
        widget.close()
        widget.deleteLater()


def _make_three(qapp) -> StyledSegmented:
    """创建包含 A / B / C 三个段的组件。"""
    w = StyledSegmented()
    w.add_segment("A")
    w.add_segment("B")
    w.add_segment("C")
    return w


# =============================================================================
# API surface
# =============================================================================


class TestStyledSegmentedAPISurface:
    """验证公共 API 可调用。"""

    def test_api_surface(self, qapp) -> None:
        """组件应暴露 add_segment / current_index / set_current_index /
        current_changed / segment_count / clear / set_segment_disabled /
        variant / size。"""
        widget = StyledSegmented(parent=None)
        try:
            assert callable(widget.add_segment)
            assert callable(widget.set_current_index)
            assert callable(widget.segment_count)
            assert callable(widget.clear)
            assert callable(widget.set_segment_disabled)
            assert hasattr(widget, "current_index")
            assert hasattr(widget, "current_changed")
            assert hasattr(widget, "variant")
            assert hasattr(widget, "size")
        finally:
            widget.deleteLater()

    def test_add_segment_returns_index(self, qapp) -> None:
        """add_segment 应返回递增的段索引。"""
        w = _make_three(qapp)
        assert w.segment_count() == 3
        assert w.add_segment("D") == 3
        w.close()

    def test_first_segment_selected_by_default(self, qapp) -> None:
        """添加第一个（未禁用）段后应自动选中它。"""
        w = _make_three(qapp)
        assert w.current_index == 0
        w.close()

    def test_clear_resets(self, qapp) -> None:
        """clear 应清空所有段并重置当前索引。"""
        w = _make_three(qapp)
        w.set_current_index(2)
        w.clear()
        assert w.segment_count() == 0
        assert w.current_index == 0
        w.close()


# =============================================================================
# Selection behaviour
# =============================================================================


class TestSelection:
    """验证选中状态与信号。"""

    def test_set_current_index_emits_signal(self, qapp) -> None:
        """切换选中段应发射 current_changed 且携带新索引。"""
        w = _make_three(qapp)
        received = []
        w.current_changed.connect(received.append)
        w.set_current_index(1)
        assert received == [1]
        assert w.current_index == 1
        w.close()

    def test_set_current_index_same_index_no_signal(self, qapp) -> None:
        """重复选中同一段不应再次发射信号。"""
        w = _make_three(qapp)
        received = []
        w.current_changed.connect(received.append)
        w.set_current_index(0)
        assert received == []
        w.close()

    def test_set_current_index_out_of_range_ignored(self, qapp) -> None:
        """越界索引应被忽略。"""
        w = _make_three(qapp)
        w.set_current_index(99)
        assert w.current_index == 0
        w.set_current_index(-1)
        assert w.current_index == 0
        w.close()

    def test_disabled_segment_not_selectable(self, qapp) -> None:
        """禁用段不能通过 set_current_index 选中。"""
        w = StyledSegmented()
        w.add_segment("A")
        w.add_segment("B", disabled=True)
        w.add_segment("C")
        w.set_current_index(1)
        assert w.current_index == 0
        w.close()

    def test_set_segment_disabled_toggles(self, qapp) -> None:
        """set_segment_disabled 可动态禁用 / 启用段。"""
        w = StyledSegmented()
        w.add_segment("A")
        w.add_segment("B")
        w.set_segment_disabled(1, True)
        w.set_current_index(1)
        assert w.current_index == 0
        w.set_segment_disabled(1, False)
        w.set_current_index(1)
        assert w.current_index == 1
        w.close()


# =============================================================================
# Variant / size
# =============================================================================


class TestVariantAndSize:
    """验证变体与尺寸属性。"""

    def test_invalid_variant_falls_back(self, qapp) -> None:
        """非法变体应回退到默认 pill。"""
        w = StyledSegmented(variant="bogus")
        assert w.variant == "pill"
        w.close()

    def test_invalid_size_falls_back(self, qapp) -> None:
        """非法尺寸应回退到默认 default。"""
        w = StyledSegmented(size="huge")
        assert w.size == "default"
        w.close()

    def test_variant_setter_validates(self, qapp) -> None:
        """variant setter 只接受合法值。"""
        w = _make_three(qapp)
        w.variant = "underline"
        assert w.variant == "underline"
        w.variant = "bogus"
        assert w.variant == "underline"
        w.close()

    def test_size_setter_validates(self, qapp) -> None:
        """size setter 只接受合法值。"""
        w = _make_three(qapp)
        w.size = "lg"
        assert w.size == "lg"
        w.size = "bogus"
        assert w.size == "lg"
        w.close()

    def test_reconfigure_preserves_current(self, qapp) -> None:
        """切换变体 / 尺寸后当前选中索引保持不变。"""
        w = _make_three(qapp)
        w.set_current_index(2, animate=False)
        w.variant = "underline"
        w.size = "lg"
        assert w.current_index == 2
        w.close()


# =============================================================================
# Keyboard navigation
# =============================================================================


class TestKeyboardNavigation:
    """验证方向键 / Home / End 导航。"""

    def test_arrow_right(self, qapp) -> None:
        """右方向键应切换并发射信号。"""
        w = _make_three(qapp)
        received = []
        w.current_changed.connect(received.append)
        QTest.keyClick(w._header, Qt.Key_Right)
        assert w.current_index == 1
        assert received == [1]
        w.close()

    def test_arrow_left_wraps_stop_at_edge(self, qapp) -> None:
        """左方向键在首段时应保持不动。"""
        w = _make_three(qapp)
        QTest.keyClick(w._header, Qt.Key_Left)
        assert w.current_index == 0
        w.close()

    def test_arrow_skips_disabled(self, qapp) -> None:
        """方向键导航应跳过禁用段。"""
        w = StyledSegmented()
        w.add_segment("A")
        w.add_segment("B", disabled=True)
        w.add_segment("C")
        QTest.keyClick(w._header, Qt.Key_Right)
        assert w.current_index == 2
        w.close()

    def test_home_and_end(self, qapp) -> None:
        """Home / End 应跳转到首 / 尾段。"""
        w = _make_three(qapp)
        w.set_current_index(2, animate=False)
        QTest.keyClick(w._header, Qt.Key_Home)
        assert w.current_index == 0
        QTest.keyClick(w._header, Qt.Key_End)
        assert w.current_index == 2
        w.close()

    def test_keyboard_ignores_unhandled_keys(self, qapp) -> None:
        """未处理的按键不应改变当前索引。"""
        w = _make_three(qapp)
        QTest.keyClick(w._header, Qt.Key_Space)
        assert w.current_index == 0
        w.close()


# =============================================================================
# Animation internals
# =============================================================================


class TestAnimation:
    """验证滑块动画基础设施。"""

    def test_animation_properties_exist(self, qapp) -> None:
        """header 应暴露可动画的 indicator_pos / indicator_width 属性。"""
        w = _make_three(qapp)
        header = w._header
        assert hasattr(header, "indicator_pos")
        assert hasattr(header, "indicator_width")
        assert isinstance(header._pos_anim, QPropertyAnimation)
        assert isinstance(header._width_anim, QPropertyAnimation)
        w.close()

    def test_indicator_tracks_current(self, qapp) -> None:
        """指示器位置 / 宽度应与当前段几何一致。"""
        w = _make_three(qapp)
        header = w._header
        r1 = header._seg_rects[1]
        w.set_current_index(1, animate=False)
        pos, width = header._indicator_rect_for(r1)
        assert abs(header._indicator_pos - pos) < 0.5
        assert abs(header._indicator_width - width) < 0.5
        w.close()

    def test_set_current_without_animation_sets_immediately(self, qapp) -> None:
        """animate=False 时指示器应立即就位（无需等待动画）。"""
        w = _make_three(qapp)
        header = w._header
        w.set_current_index(2, animate=False)
        r2 = header._seg_rects[2]
        pos, width = header._indicator_rect_for(r2)
        assert abs(header._indicator_pos - pos) < 0.5
        assert abs(header._indicator_width - width) < 0.5
        w.close()
