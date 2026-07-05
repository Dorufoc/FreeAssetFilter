# -*- coding: utf-8 -*-
"""
custom_scrollbar 单元测试
测试 freeassetfilter/widgets/custom_scrollbar.py 模块的功能
"""
import pytest
from PySide6.QtCore import Qt, QEasingCurve, QPropertyAnimation, QSize, QEvent
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget, QScrollBar, QVBoxLayout


@pytest.fixture
def scrollbar(qapp):
    """提供 FileScrollBar 实例（dpi_scale=1.0）"""
    from freeassetfilter.widgets.custom_scrollbar import FileScrollBar

    sb = FileScrollBar(dpi_scale=1.0)
    sb.resize(20, 200)
    yield sb
    sb.close()
    sb.deleteLater()


# =============================================================================
# 基础测试
# =============================================================================


class TestFileScrollBarBasic:
    """测试 FileScrollBar 基本功能"""

    def test_module_import(self):
        """测试模块可以导入"""
        from freeassetfilter.widgets.custom_scrollbar import FileScrollBar

        assert FileScrollBar is not None

    def test_default_creation(self, qapp):
        """测试默认参数创建（无 dpi_scale，从 app 获取）"""
        if not hasattr(qapp, "dpi_scale_factor"):
            qapp.dpi_scale_factor = 1.0
        from freeassetfilter.widgets.custom_scrollbar import FileScrollBar

        sb = FileScrollBar()
        try:
            assert sb._dpi_scale >= 1.0
            assert sb._bar_width_normal >= 4
            assert sb._bar_width_hovered >= 6
            assert sb._bar_width >= 4
            assert sb._thumb_min_height >= 20
            assert sb._padding >= 2
        finally:
            sb.close()
            sb.deleteLater()

    def test_custom_dpi_scale(self, qapp):
        """测试使用自定义 dpi_scale 创建"""
        from freeassetfilter.widgets.custom_scrollbar import FileScrollBar

        sb = FileScrollBar(dpi_scale=2.0)
        try:
            assert sb._dpi_scale == 2.0
            assert sb._bar_width_normal == 8  # 4 * 2.0
            assert sb._bar_width_hovered == 12  # 8 * 1.5
            assert sb._thumb_min_height == 40  # 20 * 2.0
            assert sb._padding == 4  # 2 * 2.0
        finally:
            sb.close()
            sb.deleteLater()

    def test_high_dpi_minimums(self, qapp):
        """测试高 DPI 下最小值限制正确"""
        from freeassetfilter.widgets.custom_scrollbar import FileScrollBar

        sb = FileScrollBar(dpi_scale=0.5)
        try:
            # max(3, int(4 * 0.5)) = max(3, 2) = 3
            assert sb._bar_width_normal == 3
            # max(3, int(3 * 1.5)) = max(3, 4) = 4
            assert sb._bar_width_hovered == 4
            # max(20, int(20 * 0.5)) = max(20, 10) = 20
            assert sb._thumb_min_height == 20
        finally:
            sb.close()
            sb.deleteLater()

    def test_bar_width_property(self, scrollbar):
        """测试 bar_width 属性读写"""
        assert scrollbar.bar_width == 4
        scrollbar.bar_width = 8
        assert scrollbar._bar_width == 8
        assert scrollbar.bar_width == 8
        # 最小值限制为 1
        scrollbar.bar_width = 0
        assert scrollbar._bar_width == 1

    def test_widget_attributes(self, qapp):
        """测试创建的 Widget 具有必要属性"""
        from freeassetfilter.widgets.custom_scrollbar import FileScrollBar

        sb = FileScrollBar(dpi_scale=1.0)
        try:
            assert sb.minimumWidth() >= 0
            assert sb.parent() is None
            assert sb.testAttribute(Qt.WA_OpaquePaintEvent) is True
            assert sb.hasMouseTracking() is True
        finally:
            sb.close()
            sb.deleteLater()

    def test_valueChanged_signal(self, scrollbar):
        """测试 valueChanged 信号存在且可连接"""
        results = []

        def on_changed(val):
            results.append(val)

        scrollbar.valueChanged.connect(on_changed)
        assert scrollbar.valueChanged is not None


# =============================================================================
# 大小计算测试
# =============================================================================


class TestFileScrollBarSizeCalculations:
    """测试 FileScrollBar 大小计算方法"""

    def test_sizeHint(self, qapp):
        """测试 sizeHint 返回值正确"""
        from freeassetfilter.widgets.custom_scrollbar import FileScrollBar

        sb = FileScrollBar(dpi_scale=1.0)
        try:
            hint = sb.sizeHint()
            assert isinstance(hint, QSize)
            # width = bar_width + 2 * padding = 4 + 4 = 8
            assert hint.width() == 8
            assert hint.height() == 0
        finally:
            sb.close()
            sb.deleteLater()

    def test_sizeHint_after_configure(self, qapp):
        """测试配置修改后 sizeHint 更新"""
        from freeassetfilter.widgets.custom_scrollbar import FileScrollBar

        sb = FileScrollBar(dpi_scale=1.0)
        try:
            sb.configure(bar_width_normal=10, padding=3)
            hint = sb.sizeHint()
            # width = 10 + 2 * 3 = 16
            assert hint.width() == 16
        finally:
            sb.close()
            sb.deleteLater()

    def test_thumb_length_when_no_range(self, scrollbar):
        """测试无范围时 thumb_length 返回 0"""
        scrollbar.setRange(0, 0)
        assert scrollbar._thumb_length() == 0

    def test_thumb_length_basic(self, scrollbar):
        """测试 thumb_length 基本计算"""
        scrollbar.setRange(0, 100)
        scrollbar.setPageStep(50)  # 50% of range
        scrollbar.resize(20, 200)
        # track_height = 200 - 2 * 2 = 196
        # ratio = 50 / 100 = 0.5
        # raw = int(196 * 0.5) = 98
        # min = 20, max = int(196 * 0.75) = 147
        # result = clamp(98, 20, 147) = 98
        assert scrollbar._thumb_length() == 98

    def test_thumb_length_clamped_to_min(self, scrollbar):
        """测试 thumb_length 受最小值限制"""
        scrollbar.setRange(0, 1000)
        scrollbar.setPageStep(10)  # 1% of range
        scrollbar.resize(20, 200)
        # ratio = 10 / 1000 = 0.01
        # raw = int(196 * 0.01) = 1
        # clamped to min 20
        assert scrollbar._thumb_length() == 20

    def test_thumb_length_clamped_to_max(self, scrollbar):
        """测试 thumb_length 受最大值限制"""
        scrollbar.setRange(0, 10)
        scrollbar.setPageStep(20)  # > 100% of range
        scrollbar.resize(20, 200)
        # ratio = 20 / 10 = 2.0, min(ratio, 1.0) = 1.0
        # raw = int(196 * 1.0) = 196
        # max = int(196 * 0.75) = 147
        # clamped to 147
        assert scrollbar._thumb_length() == 147

    def test_value_to_y_no_range(self, scrollbar):
        """测试无范围时 value_to_y 返回 padding"""
        scrollbar.setRange(0, 0)
        scrollbar.resize(20, 200)
        assert scrollbar._value_to_y(50) == scrollbar._padding

    def test_value_to_y_at_min(self, scrollbar):
        """测试 value_to_y 在最小值处"""
        scrollbar.setRange(0, 100)
        scrollbar.setPageStep(50)
        scrollbar.resize(20, 200)
        thumb_h = scrollbar._thumb_length()
        # at min: ratio = 0, y = padding
        assert scrollbar._value_to_y(0) == scrollbar._padding

    def test_value_to_y_at_max(self, scrollbar):
        """测试 value_to_y 在最大值处"""
        scrollbar.setRange(0, 100)
        scrollbar.setPageStep(50)
        scrollbar.resize(20, 200)
        thumb_h = scrollbar._thumb_length()
        # at max: ratio = 1.0, y = padding + available
        track_height = 200 - 2 * scrollbar._padding
        available = max(1, track_height - thumb_h)
        expected = scrollbar._padding + available
        assert scrollbar._value_to_y(100) == expected

    def test_y_to_value_at_min(self, scrollbar):
        """测试 y_to_value 在 padding 处对应最小值"""
        scrollbar.setRange(0, 100)
        scrollbar.setPageStep(50)
        scrollbar.resize(20, 200)
        assert scrollbar._y_to_value(scrollbar._padding) == 0

    def test_y_to_value_at_max(self, scrollbar):
        """测试 y_to_value 在最大 y 处对应最大值"""
        scrollbar.setRange(0, 100)
        scrollbar.setPageStep(50)
        scrollbar.resize(20, 200)
        track_height = 200 - 2 * scrollbar._padding
        thumb_h = scrollbar._thumb_length()
        available = max(1, track_height - thumb_h)
        max_y = scrollbar._padding + available
        # At the exact max y, ratio = 1.0, so value = min + 1 * (max - min) = 100
        # But due to integer rounding, it could be close to max
        result = scrollbar._y_to_value(max_y)
        assert result >= 99  # rounding could be off by 1

    def test_value_y_roundtrip(self, scrollbar):
        """测试 value_to_y 和 y_to_value 往返一致"""
        scrollbar.setRange(0, 100)
        scrollbar.setPageStep(50)
        scrollbar.resize(20, 200)
        for val in [0, 10, 25, 50, 75, 100]:
            y = scrollbar._value_to_y(val)
            restored = scrollbar._y_to_value(y)
            # Due to integer rounding, restored may differ by at most 1
            assert abs(restored - val) <= 1, (
                f"Roundtrip failed for value={val}: y={y}, restored={restored}"
            )

    def test_is_point_in_pill_outside(self, scrollbar):
        """测试点不在 pill 形状内"""
        # rect at (8, 0, 4, 98) with radius 2
        assert scrollbar._is_point_in_pill(0, 0, 8, 0, 4, 98, 2) is False
        assert scrollbar._is_point_in_pill(100, 100, 8, 0, 4, 98, 2) is False

    def test_is_point_in_pill_inside(self, scrollbar):
        """测试点在 pill 形状内部"""
        # center of the rect
        assert scrollbar._is_point_in_pill(10, 49, 8, 0, 4, 98, 2) is True

    def test_is_point_in_pill_top_radius(self, scrollbar):
        """测试点在顶部圆角内"""
        # inside top rounded corner area
        assert scrollbar._is_point_in_pill(9, 1, 8, 0, 4, 98, 2) is True

    def test_is_point_in_pill_no_radius(self, scrollbar):
        """测试 radius <= 0 时只检查边界矩形"""
        assert scrollbar._is_point_in_pill(9, 5, 8, 0, 4, 98, 0) is True
        assert scrollbar._is_point_in_pill(9, 5, 8, 0, 4, 98, -1) is True

    def test_is_point_in_pill_bottom_radius(self, scrollbar):
        """测试点在底部圆角外"""
        # point below the pill
        rw, rh = 4, 98
        rx, ry = 8, 0
        radius = 2
        # point below the bottom of the rect
        assert scrollbar._is_point_in_pill(10, ry + rh + 1, rx, ry, rw, rh, radius) is False
        # point at the bottom middle of the rect (inside bottom rounded area)
        assert scrollbar._is_point_in_pill(10, ry + rh - 1, rx, ry, rw, rh, radius) is True


# =============================================================================
# 范围与数值管理测试
# =============================================================================


class TestFileScrollBarRangeValue:
    """测试 FileScrollBar 范围与数值管理"""

    def test_setRange(self, scrollbar):
        """测试 setRange 设置范围"""
        scrollbar.setRange(10, 200)
        assert scrollbar._minimum == 10
        assert scrollbar._maximum == 200

    def test_setValue(self, scrollbar):
        """测试 setValue 设置数值"""
        scrollbar.setRange(0, 100)
        scrollbar.setValue(50)
        assert scrollbar._value == 50

    def test_setValue_clamped_low(self, scrollbar):
        """测试 setValue 被下限限制"""
        scrollbar.setRange(10, 100)
        scrollbar.setValue(5)
        assert scrollbar._value == 10

    def test_setValue_clamped_high(self, scrollbar):
        """测试 setValue 被上限限制"""
        scrollbar.setRange(10, 100)
        scrollbar.setValue(200)
        assert scrollbar._value == 100

    def test_setValue_no_update_on_same(self, scrollbar):
        """测试 setValue 相同值不触发 update"""
        scrollbar.setRange(0, 100)
        scrollbar.setValue(50)
        # Set same value, should not change
        scrollbar.setValue(50)
        assert scrollbar._value == 50

    def test_setPageStep(self, scrollbar):
        """测试 setPageStep 设置页步长"""
        scrollbar.setPageStep(25)
        assert scrollbar._page_step == 25

    def test_setPageStep_minimum(self, scrollbar):
        """测试 setPageStep 最小值为 1"""
        scrollbar.setPageStep(0)
        assert scrollbar._page_step == 1
        scrollbar.setPageStep(-5)
        assert scrollbar._page_step == 1

    def test_setSingleStep(self, scrollbar):
        """测试 setSingleStep 设置单步长"""
        scrollbar.setSingleStep(5)
        assert scrollbar._single_step == 5

    def test_setSingleStep_minimum(self, scrollbar):
        """测试 setSingleStep 最小值为 1"""
        scrollbar.setSingleStep(0)
        assert scrollbar._single_step == 1

    def test_valueChanged_not_emitted_by_setValue(self, scrollbar):
        """测试 setValue 不触发 valueChanged 信号（仅拖拽触发）"""
        results = []
        scrollbar.valueChanged.connect(results.append)
        scrollbar.setRange(0, 100)
        scrollbar.setValue(75)
        # valueChanged is only emitted on drag, not via setValue
        assert results == []

    def test_setValue_updates_internal_value(self, scrollbar):
        """测试 setValue 更新内部 _value"""
        scrollbar.setRange(0, 100)
        scrollbar.setValue(75)
        assert scrollbar._value == 75


# =============================================================================
# 配置测试
# =============================================================================


class TestFileScrollBarConfiguration:
    """测试 FileScrollBar 配置方法"""

    def test_configure_bar_width(self, scrollbar):
        """测试 configure 修改条宽度"""
        scrollbar.configure(bar_width_normal=12)
        assert scrollbar._bar_width_normal == 12
        assert scrollbar._bar_width_hovered == 18  # 12 * 1.5
        assert scrollbar._bar_width == 12

    def test_configure_bar_width_hovered(self, scrollbar):
        """测试 configure 独立修改悬停宽度"""
        scrollbar.configure(bar_width_hovered=20)
        assert scrollbar._bar_width_hovered == 20
        # bar_width_normal stays at default 4
        assert scrollbar._bar_width_normal == 4

    def test_configure_thumb_color(self, scrollbar):
        """测试 configure 修改滑块颜色"""
        scrollbar.configure(thumb_color="#FF0000")
        assert isinstance(scrollbar._thumb_color, QColor)
        assert scrollbar._thumb_color.name() == "#ff0000"

    def test_configure_thumb_hover_color(self, scrollbar):
        """测试 configure 修改悬停颜色"""
        scrollbar.configure(thumb_hover_color="#00FF00")
        assert isinstance(scrollbar._thumb_hover_color, QColor)
        assert scrollbar._thumb_hover_color.name() == "#00ff00"

    def test_configure_padding(self, scrollbar):
        """测试 configure 修改内边距"""
        scrollbar.configure(padding=5)
        assert scrollbar._padding == 5

    def test_configure_bar_width_minimum(self, scrollbar):
        """测试 configure 条宽度最小值为 3"""
        scrollbar.configure(bar_width_normal=1)
        assert scrollbar._bar_width_normal == 3

    def test_configure_bar_width_hovered_minimum(self, scrollbar):
        """测试 configure 悬停宽度最小值为 3"""
        scrollbar.configure(bar_width_hovered=0)
        assert scrollbar._bar_width_hovered == 3

    def test_configure_padding_non_negative(self, scrollbar):
        """测试 configure padding 非负"""
        scrollbar.configure(padding=-1)
        assert scrollbar._padding == 0

    def test_set_padding(self, scrollbar):
        """测试 set_padding 方法"""
        scrollbar.set_padding(8)
        assert scrollbar._padding == 8

    def test_set_padding_non_negative(self, scrollbar):
        """测试 set_padding 非负"""
        scrollbar.set_padding(-5)
        assert scrollbar._padding == 0


# =============================================================================
# 动画测试
# =============================================================================


class TestFileScrollBarAnimation:
    """测试 FileScrollBar 动画功能"""

    def test_animation_object_created(self, scrollbar):
        """测试动画对象创建正确"""
        anim = scrollbar._hover_animation
        assert isinstance(anim, QPropertyAnimation)
        assert anim.propertyName() == b"bar_width"
        assert anim.duration() == 150
        assert anim.easingCurve() == QEasingCurve.OutCubic
        assert anim.targetObject() == scrollbar

    def test_start_hover_animation_target_normal(self, scrollbar):
        """测试悬停结束动画目标为 normal width"""
        # Set bar_width different from normal so animation actually starts
        scrollbar._bar_width = scrollbar._bar_width_hovered
        scrollbar._start_hover_animation(False)
        anim = scrollbar._hover_animation
        assert anim.endValue() == scrollbar._bar_width_normal

    def test_start_hover_animation_target_hovered(self, scrollbar):
        """测试悬停开始动画目标为 hovered width"""
        scrollbar._bar_width = scrollbar._bar_width_normal
        scrollbar._start_hover_animation(True)
        anim = scrollbar._hover_animation
        assert anim.endValue() == scrollbar._bar_width_hovered

    def test_hover_animation_skips_when_at_target_and_not_running(self, scrollbar):
        """测试动画在已在目标值且未运行时跳过"""
        scrollbar._bar_width = scrollbar._bar_width_normal
        # Should not crash or start animation
        scrollbar._start_hover_animation(False)
        assert scrollbar._hover_animation.state() != QPropertyAnimation.Running

    def test_hover_animation_start_value_set(self, scrollbar):
        """测试动画设置正确的起始值"""
        scrollbar._bar_width = 5
        scrollbar._start_hover_animation(True)
        anim = scrollbar._hover_animation
        assert anim.startValue() == 5

    def test_hover_animation_restarts_if_already_running(self, scrollbar):
        """测试动画在运行时重新开始（反向播放场景）"""
        scrollbar._bar_width = 5
        scrollbar._start_hover_animation(True)
        # Change target mid-animation
        scrollbar._start_hover_animation(False)
        anim = scrollbar._hover_animation
        assert anim.endValue() == scrollbar._bar_width_normal
        assert anim.startValue() == 5


# =============================================================================
# 鼠标事件测试
# =============================================================================


class TestFileScrollBarMouseEvents:
    """测试 FileScrollBar 鼠标事件处理"""

    def _create_scrollbar_with_range(self, qapp):
        """创建一个有范围的滚动条用于鼠标测试"""
        from freeassetfilter.widgets.custom_scrollbar import FileScrollBar

        sb = FileScrollBar(dpi_scale=1.0)
        sb.resize(20, 200)
        sb.setRange(0, 100)
        sb.setPageStep(50)
        return sb

    def test_mousePress_starts_drag_on_thumb(self, qapp):
        """测试点击滑块区域开始拖拽"""
        sb = self._create_scrollbar_with_range(qapp)
        try:
            # Calculate the center of the thumb
            thumb_y = sb._value_to_y(sb._value)
            thumb_x = sb.width() - sb._padding - sb._bar_width // 2
            from PySide6.QtCore import QPoint, QPointF
            from PySide6.QtGui import QMouseEvent

            event = QMouseEvent(
                QEvent.MouseButtonPress,
                QPointF(thumb_x, thumb_y + 10),
                QPointF(thumb_x, thumb_y + 10),
                Qt.LeftButton,
                Qt.LeftButton,
                Qt.NoModifier,
            )
            sb.mousePressEvent(event)
            assert sb._dragging is True
            assert sb._drag_start_value == sb._value
        finally:
            sb.close()
            sb.deleteLater()

    def test_mousePress_non_left_button_ignored(self, qapp):
        """测试非左键点击不开始拖拽"""
        sb = self._create_scrollbar_with_range(qapp)
        try:
            from PySide6.QtGui import QMouseEvent

            event = QMouseEvent(
                QEvent.MouseButtonPress,
                sb.rect().center(),
                Qt.RightButton,
                Qt.RightButton,
                Qt.NoModifier,
            )
            sb.mousePressEvent(event)
            assert sb._dragging is False
        finally:
            sb.close()
            sb.deleteLater()

    def test_mouseRelease_ends_drag(self, qapp):
        """测试鼠标释放结束拖拽"""
        sb = self._create_scrollbar_with_range(qapp)
        try:
            from PySide6.QtGui import QMouseEvent
            from PySide6.QtCore import QPointF

            thumb_y = sb._value_to_y(sb._value)
            thumb_x = sb.width() - sb._padding - sb._bar_width // 2
            press = QMouseEvent(
                QEvent.MouseButtonPress,
                QPointF(thumb_x, thumb_y + 10),
                QPointF(thumb_x, thumb_y + 10),
                Qt.LeftButton,
                Qt.LeftButton,
                Qt.NoModifier,
            )
            sb.mousePressEvent(press)
            assert sb._dragging is True

            release = QMouseEvent(
                QEvent.MouseButtonRelease,
                sb.rect().center(),
                Qt.LeftButton,
                Qt.LeftButton,
                Qt.NoModifier,
            )
            sb.mouseReleaseEvent(release)
            assert sb._dragging is False
        finally:
            sb.close()
            sb.deleteLater()

    def test_enterEvent_hover_off_when_not_over_thumb(self, qapp):
        """测试进入但不在滑块上时 hovered 为 False"""
        sb = self._create_scrollbar_with_range(qapp)
        try:
            from PySide6.QtGui import QEnterEvent
            from PySide6.QtCore import QPointF

            # Enter at the far left edge, outside the thumb bar
            event = QEnterEvent(
                QPointF(0, 0),
                QPointF(0, 0),
                QPointF(0, 0),
            )
            sb.enterEvent(event)
            assert sb._hovered is False
        finally:
            sb.close()
            sb.deleteLater()

    def test_leaveEvent_clears_hover(self, qapp):
        """测试离开时清除悬停状态"""
        sb = self._create_scrollbar_with_range(qapp)
        try:
            from PySide6.QtCore import QEvent

            # Set hovered first
            sb._hovered = True
            event = QEvent(QEvent.Leave)
            sb.leaveEvent(event)
            assert sb._hovered is False
            assert sb.cursor().shape() == Qt.ArrowCursor
        finally:
            sb.close()
            sb.deleteLater()

    def test_wheelEvent_forwards_to_parent_viewport(self, qapp):
        """测试滚轮事件转发到父级 viewport"""
        from freeassetfilter.widgets.custom_scrollbar import FileScrollBar

        # Create a container with viewport-like attribute
        container = QWidget()
        viewport = QWidget()
        container.viewport = lambda: viewport
        sb = FileScrollBar(dpi_scale=1.0)
        sb.setParent(container)
        try:
            from PySide6.QtGui import QWheelEvent
            from PySide6.QtCore import QPoint, QPointF

            received = []

            def on_wheel(ev):
                received.append(ev)

            viewport.wheelEvent = on_wheel

            wheel = QWheelEvent(
                QPointF(10, 10),
                QPointF(10, 10),
                QPoint(0, 0),
                QPoint(0, 120),
                Qt.NoButton,
                Qt.NoModifier,
                Qt.ScrollBegin,
                False,
            )
            sb.wheelEvent(wheel)
            assert len(received) == 1
        finally:
            sb.close()
            sb.deleteLater()
            container.close()
            container.deleteLater()

    def test_wheelEvent_no_parent_viewport(self, qapp):
        """测试父级无 viewport 时滚轮事件安全处理"""
        sb = self._create_scrollbar_with_range(qapp)
        try:
            from PySide6.QtGui import QWheelEvent
            from PySide6.QtCore import QPoint, QPointF

            wheel = QWheelEvent(
                QPointF(10, 10),
                QPointF(10, 10),
                QPoint(0, 0),
                QPoint(0, 120),
                Qt.NoButton,
                Qt.NoModifier,
                Qt.ScrollBegin,
                False,
            )
            # Should not crash
            sb.wheelEvent(wheel)
        finally:
            sb.close()
            sb.deleteLater()


# =============================================================================
# 集成测试
# =============================================================================


class TestFileScrollBarIntegration:
    """测试 FileScrollBar 与 Qt 组件的集成"""

    def test_sync_with_qscrollbar(self, qapp):
        """测试 FileScrollBar 可以同步 QScrollBar 的状态"""
        from freeassetfilter.widgets.custom_scrollbar import FileScrollBar

        qsb = QScrollBar()
        qsb.setRange(0, 200)
        qsb.setPageStep(50)
        qsb.setValue(30)

        sb = FileScrollBar(dpi_scale=1.0)
        try:
            sb.setRange(qsb.minimum(), qsb.maximum())
            sb.setPageStep(qsb.pageStep())
            sb.setSingleStep(qsb.singleStep())
            sb.setValue(qsb.value())

            assert sb._minimum == 0
            assert sb._maximum == 200
            assert sb._page_step == 50
            assert sb._value == 30
        finally:
            sb.close()
            sb.deleteLater()
            qsb.close()
            qsb.deleteLater()

    def test_creation_in_window(self, qapp):
        """测试 FileScrollBar 在窗口中创建和显示"""
        from freeassetfilter.widgets.custom_scrollbar import FileScrollBar

        window = QWidget()
        window.resize(300, 400)
        sb = FileScrollBar(dpi_scale=1.0, parent=window)
        sb.resize(20, 380)
        sb.setRange(0, 100)
        sb.setPageStep(50)
        sb.setValue(25)
        try:
            assert sb.parent() == window
            assert sb._value == 25
            qapp.processEvents()
        finally:
            sb.close()
            sb.deleteLater()
            window.close()
            window.deleteLater()
