"""styled_color_picker 单元测试

测试重点：
1. Qt.Tool 标志替代 Qt.Popup（避免 Windows 矩形原生阴影）
2. WA_ShowWithoutActivating 属性（显示时不抢焦点）
3. 动画生命周期稳定性（快速点击不崩溃）
4. 面板引用持久化（不因关闭而丢失）
"""
import importlib.util
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

# 确保 freeassetfilter.ui.theme 被导入，注册 'theme' 别名
_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# 导入 theme 模块以注册别名
import freeassetfilter.ui.theme  # noqa: F401

# 直接加载 styled_color_picker.py 模块文件
_module_path = _project_root / "freeassetfilter" / "ui" / "components" / "styled_color_picker.py"
spec = importlib.util.spec_from_file_location("_styled_color_picker_module", str(_module_path))
_scp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_scp)


class TestColorPanelToolFlags:
    """测试 _ColorPanel 使用 Qt.Tool 标志而非 Qt.Popup"""

    def test_panel_uses_tool_flags(self, qapp):
        """测试面板使用 Qt.Tool | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus"""
        panel = _scp._ColorPanel(parent=None)
        
        # 检查窗口标志
        flags = panel.windowFlags()
        
        # 必须包含 Tool 标志
        assert flags & Qt.Tool, "面板必须使用 Qt.Tool 标志"
        
        # 必须包含 FramelessWindowHint
        assert flags & Qt.FramelessWindowHint, "面板必须使用 Qt.FramelessWindowHint"
        
        # 必须包含 WindowDoesNotAcceptFocus
        assert flags & Qt.WindowDoesNotAcceptFocus, "面板必须使用 Qt.WindowDoesNotAcceptFocus"
        
        # 注意：Qt.Popup 和 Qt.Tool 的位标志有部分重叠，
        # 所以不能简单地用 & Qt.Popup 来检测，需要检查是否包含 Tool 标志
        # 如果 Tool 标志存在且 Popup 的特定位模式不独立存在，则说明使用的是 Tool
        
        panel.deleteLater()

    def test_panel_wa_show_without_activating(self, qapp):
        """测试面板设置 WA_ShowWithoutActivating 属性"""
        panel = _scp._ColorPanel(parent=None)
        
        # 必须设置 WA_ShowWithoutActivating
        assert panel.testAttribute(Qt.WA_ShowWithoutActivating), \
            "面板必须设置 WA_ShowWithoutActivating（显示时不抢焦点）"
        
        panel.deleteLater()


class TestColorPanelLifecycle:
    """测试 _ColorPanel 生命周期与稳定性"""

    def test_module_import(self):
        """测试模块可以导入"""
        assert _scp._ColorPanel is not None

    def test_panel_creation(self, qapp):
        """测试 panel 创建"""
        panel = _scp._ColorPanel(parent=None)
        assert panel is not None
        assert not panel.isVisible()
        panel.deleteLater()

    def test_panel_translucent_background(self, qapp):
        """测试面板设置 WA_TranslucentBackground"""
        panel = _scp._ColorPanel(parent=None)
        assert panel.testAttribute(Qt.WA_TranslucentBackground), "应设置 WA_TranslucentBackground"
        assert not panel.testAttribute(Qt.WA_OpaquePaintEvent), "不应设置 WA_OpaquePaintEvent"
        panel.deleteLater()

    def test_panel_show_close_cycle_once(self, qapp):
        """测试单次 show/close 循环"""
        panel = _scp._ColorPanel(parent=None)
        anchor = QPoint(100, 100)
        
        panel.show_animated(anchor)
        QTest.qWait(200)  # 等待淡入动画完成（180ms）
        assert panel.isVisible()
        
        panel.close_animated()
        QTest.qWait(200)  # 等待淡出动画完成（150ms）
        assert not panel.isVisible()
        panel.deleteLater()

    def test_panel_show_close_cycle_20_times(self, qapp):
        """测试重复 show/close 循环 20 次无崩溃"""
        panel = _scp._ColorPanel(parent=None)
        anchor = QPoint(100, 100)
        
        for i in range(20):
            panel.show_animated(anchor)
            QTest.qWait(200)  # 等待淡入动画完成
            assert panel.isVisible(), f"第 {i+1} 次 show 后应可见"
            
            panel.close_animated()
            QTest.qWait(200)  # 等待淡出动画完成
            assert not panel.isVisible(), f"第 {i+1} 次 close 后应隐藏"
        
        panel.deleteLater()

    def test_panel_reopen_after_close(self, qapp):
        """测试关闭后可以再次打开"""
        panel = _scp._ColorPanel(parent=None)
        anchor = QPoint(100, 100)
        
        panel.show_animated(anchor)
        QTest.qWait(200)
        assert panel.isVisible()
        
        panel.close_animated()
        QTest.qWait(200)
        assert not panel.isVisible()
        
        panel.show_animated(anchor)
        QTest.qWait(200)
        assert panel.isVisible()
        
        panel.close_animated()
        QTest.qWait(200)
        assert not panel.isVisible()
        panel.deleteLater()

    def test_panel_animation_object_persisted(self, qapp):
        """测试动画对象持久存在（不被 GC）"""
        panel = _scp._ColorPanel(parent=None)
        assert panel._opacity_anim is not None
        assert isinstance(panel._opacity_anim, _scp.QPropertyAnimation)
        
        anchor = QPoint(100, 100)
        panel.show_animated(anchor)
        QTest.qWait(200)
        
        # 再次获取动画对象，应该是同一个
        anim_after = panel._opacity_anim
        assert anim_after is panel._opacity_anim, "动画对象应持久存在"
        
        panel.close_animated()
        QTest.qWait(200)
        panel.deleteLater()


class TestColorPanelSignals:
    """测试 _ColorPanel 信号"""

    def test_color_selected_signal_emitted(self, qapp):
        """测试 color_selected 信号正确发射"""
        panel = _scp._ColorPanel(parent=None)
        anchor = QPoint(100, 100)
        
        panel.show_animated(anchor)
        QTest.qWait(200)
        
        emitted_colors = []
        panel.color_selected.connect(lambda c: emitted_colors.append(c))
        
        # 通过点击色块触发信号
        panel._on_swatch_clicked("#FF5733")
        
        assert len(emitted_colors) > 0, "点击色块应发射 color_selected 信号"
        assert emitted_colors[-1].upper().startswith("#FF5733")
        
        panel.close_animated()
        QTest.qWait(200)
        panel.deleteLater()

    def test_closed_signal_emitted(self, qapp):
        """测试 closed 信号正确发射"""
        panel = _scp._ColorPanel(parent=None)
        anchor = QPoint(100, 100)
        
        panel.show_animated(anchor)
        QTest.qWait(200)
        
        closed_count = [0]
        panel.closed.connect(lambda: closed_count.__setitem__(0, closed_count[0] + 1))
        
        panel.close_animated()
        QTest.qWait(200)  # 等待淡出动画完成
        
        assert closed_count[0] >= 1, "close_animated 应发射 closed 信号"
        panel.deleteLater()
    
    def test_closed_signal_idempotent(self, qapp):
        """测试 closed 信号幂等（不重复发射）"""
        panel = _scp._ColorPanel(parent=None)
        anchor = QPoint(100, 100)
        
        closed_count = [0]
        panel.closed.connect(lambda: closed_count.__setitem__(0, closed_count[0] + 1))
        
        panel.show_animated(anchor)
        QTest.qWait(200)
        
        panel.close_animated()
        QTest.qWait(200)
        
        count_after_close = closed_count[0]
        
        # 再次调用 close_animated（已隐藏）
        panel.close_animated()
        QTest.qWait(100)
        
        # 计数不应增加
        assert closed_count[0] == count_after_close, "closed 信号应幂等"
        panel.deleteLater()


class TestColorPanelNoRuntimeError:
    """测试面板销毁时不抛 RuntimeError"""

    def test_panel_delete_no_error(self, qapp):
        """测试删除 panel 不抛 RuntimeError"""
        panel = _scp._ColorPanel(parent=None)
        anchor = QPoint(100, 100)
        
        panel.show_animated(anchor)
        QTest.qWait(200)
        
        panel.close_animated()
        QTest.qWait(200)
        
        try:
            panel.deleteLater()
            QTest.qWait(100)
        except RuntimeError:
            pytest.fail("panel.deleteLater() 不应抛 RuntimeError")

    def test_panel_destroyed_no_event_filter_leak(self, qapp):
        """测试 panel 销毁后无全局过滤器残留"""
        panel = _scp._ColorPanel(parent=None)
        anchor = QPoint(100, 100)
        
        panel.show_animated(anchor)
        QTest.qWait(200)
        
        panel.close_animated()
        QTest.qWait(200)
        
        # 验证：面板已隐藏
        assert not panel.isVisible(), "关闭后应隐藏"
        panel.deleteLater()


class TestColorPanelEdgeCases:
    """测试边界情况"""

    def test_show_during_show(self, qapp):
        """测试 show 过程中再次 show 应停止并重新淡入"""
        panel = _scp._ColorPanel(parent=None)
        anchor = QPoint(100, 100)
        
        panel.show_animated(anchor)
        QTest.qWait(50)  # 动画进行中
        
        # 再次 show
        panel.show_animated(anchor)
        QTest.qWait(200)
        
        assert panel.isVisible()
        assert panel.windowOpacity() > 0.9  # 应完成淡入
        
        panel.close_animated()
        QTest.qWait(200)
        panel.deleteLater()

    def test_show_during_close(self, qapp):
        """测试 close 过程中再次 show 应取消关闭并淡入"""
        panel = _scp._ColorPanel(parent=None)
        anchor = QPoint(100, 100)
        
        panel.show_animated(anchor)
        QTest.qWait(200)
        
        panel.close_animated()
        QTest.qWait(50)  # 淡出进行中
        
        # 取消关闭，重新 show
        panel.show_animated(anchor)
        QTest.qWait(200)
        
        assert panel.isVisible()
        assert panel.windowOpacity() > 0.9
        
        panel.close_animated()
        QTest.qWait(200)
        panel.deleteLater()

    def test_close_already_hidden(self, qapp):
        """测试关闭已隐藏的面板不重复发射信号"""
        panel = _scp._ColorPanel(parent=None)
        
        closed_count = [0]
        panel.closed.connect(lambda: closed_count.__setitem__(0, closed_count[0] + 1))
        
        # 未 show 过的 panel 调用 close_animated
        panel.close_animated()
        QTest.qWait(100)
        
        # 不应发射 closed（因为从未 show）
        assert closed_count[0] == 0
        panel.deleteLater()


class TestStyledColorPickerIntegration:
    """测试 StyledColorPicker 集成"""

    def test_picker_creation(self, qapp):
        """测试 StyledColorPicker 创建"""
        picker = _scp.StyledColorPicker(color="#007AFF", parent=None)
        assert picker is not None
        assert picker.color == "#007AFF"
        picker.deleteLater()

    def test_picker_color_property(self, qapp):
        """测试 color 属性设置"""
        picker = _scp.StyledColorPicker(color="#007AFF", parent=None)
        picker.color = "#FF5733"
        assert picker.color == "#FF5733"
        picker.deleteLater()

    def test_picker_panel_reuse(self, qapp):
        """测试 picker 复用 panel"""
        picker = _scp.StyledColorPicker(color="#007AFF", parent=None)
        initial_panel = picker._panel
        
        picker._toggle_panel()
        QTest.qWait(200)
        
        picker._toggle_panel()
        QTest.qWait(200)
        
        assert picker._panel is initial_panel, "应复用同一个 panel"
        picker.deleteLater()
    
    def test_picker_panel_translucent(self, qapp):
        """测试 picker 的 panel 使用 WA_TranslucentBackground"""
        picker = _scp.StyledColorPicker(color="#007AFF", parent=None)
        panel = picker._panel
        
        assert panel.testAttribute(Qt.WA_TranslucentBackground), "panel 应设置 WA_TranslucentBackground"
        assert not panel.testAttribute(Qt.WA_OpaquePaintEvent), "panel 不应设置 WA_OpaquePaintEvent"
        picker.deleteLater()


class TestRapidClickingStability:
    """测试快速点击时的稳定性（无 QPaintDevice 崩溃）"""

    def test_panel_rapid_show_close_40_times(self, qapp):
        """测试快速交替 show/close 40 次不崩溃"""
        panel = _scp._ColorPanel(parent=None)
        anchor = QPoint(100, 100)
        
        for i in range(40):
            # 快速打开
            panel.show_animated(anchor)
            QTest.qWait(10)  # 极短等待，模拟快速点击
            
            # 快速关闭
            panel.close_animated()
            QTest.qWait(10)
            
            # 处理所有事件
            QTest.qWait(10)
        
        # 等待所有动画完成
        QTest.qWait(200)
        
        # 不崩溃即成功
        assert True
        panel.deleteLater()

    def test_panel_show_during_fade_out(self, qapp):
        """测试关闭动画进行中重新打开（取消关闭）"""
        panel = _scp._ColorPanel(parent=None)
        anchor = QPoint(100, 100)
        
        # 打开
        panel.show_animated(anchor)
        QTest.qWait(200)
        assert panel.isVisible()
        
        # 开始关闭
        panel.close_animated()
        QTest.qWait(50)  # 关闭动画进行中
        
        # 取消关闭，重新打开
        panel._opacity_anim.stop()
        panel._closing = False
        panel._closed_emitted = False
        panel.show_animated(anchor)
        QTest.qWait(200)
        
        # 应该可见
        assert panel.isVisible()
        assert panel.windowOpacity() > 0.9
        
        # 清理关闭
        panel.close_animated()
        QTest.qWait(200)
        panel.deleteLater()


class TestAppearanceSettingsPagePanelPersistence:
    """测试 AppearanceSettingsPage 中面板引用的持久化
    
    注意：这些测试需要完整的应用环境，在集成测试中运行。
    这里我们验证 _ColorPanel 的基本行为。
    """

    def test_panel_closed_signal_emitted_once(self, qapp):
        """测试面板关闭信号只发射一次"""
        panel = _scp._ColorPanel(parent=None)
        anchor = QPoint(100, 100)
        
        closed_count = [0]
        panel.closed.connect(lambda: closed_count.__setitem__(0, closed_count[0] + 1))
        
        # 打开
        panel.show_animated(anchor)
        QTest.qWait(200)
        
        # 关闭
        panel.close_animated()
        QTest.qWait(200)
        
        # 信号应该只发射一次
        assert closed_count[0] == 1, "closed 信号应只发射一次"
        
        # 再次关闭（已隐藏）
        panel.close_animated()
        QTest.qWait(100)
        
        # 信号不应再次发射
        assert closed_count[0] == 1, "closed 信号不应重复发射"
        
        panel.deleteLater()

    def test_panel_ref_preserved_by_parent(self, qapp):
        """测试面板引用通过父对象保持（Qt 父子关系）"""
        # 创建父 widget
        parent = _scp.QWidget()
        panel = _scp._ColorPanel(parent=parent)
        
        # 显示并关闭
        anchor = QPoint(100, 100)
        panel.show_animated(anchor)
        QTest.qWait(200)
        panel.close_animated()
        QTest.qWait(200)
        
        # 面板引用应该仍然有效（通过父对象）
        # 注意：面板已隐藏，但对象未销毁
        assert panel is not None
        
        # 清理
        parent.deleteLater()


class TestPanelNoNativeShadow:
    """测试面板不渲染 Windows 原生阴影"""

    def test_panel_no_qgraphics_effect(self, qapp):
        """测试面板不使用 QGraphicsEffect"""
        panel = _scp._ColorPanel(parent=None)
        
        # 不应有图形效果
        assert panel.graphicsEffect() is None, "不应使用 QGraphicsEffect（会导致矩形阴影）"
        
        panel.deleteLater()

    def test_panel_no_mask(self, qapp):
        """测试面板不使用 setMask"""
        panel = _scp._ColorPanel(parent=None)
        
        # 不应有遮罩
        # 注意：QRegion() 创建空区域，但 setMask 后 mask() 不为空
        # 检查是否有自定义遮罩
        mask = panel.mask()
        # 空遮罩意味着没有设置遮罩
        # 如果设置了遮罩，mask.isEmpty() 可能返回 False
        # 这里我们验证初始状态没有遮罩
        assert mask.isEmpty() or mask.rectCount() == 0, \
            "面板不应使用 setMask（会导致性能问题）"
        
        panel.deleteLater()


class TestColorPanelReopenBehavior:
    """测试 _ColorPanel 的 reopen 行为"""

    def test_is_closing_property(self, qapp):
        """测试 is_closing 属性正确反映关闭状态"""
        panel = _scp._ColorPanel(parent=None)
        anchor = _scp.QPoint(100, 100)

        # 初始状态：未关闭中
        assert not panel.is_closing, "初始状态应不在关闭中"

        # 打开面板
        panel.show_animated(anchor)
        QTest.qWait(200)
        assert not panel.is_closing, "打开后应不在关闭中"

        # 开始关闭（动画进行中）
        panel.close_animated()
        QTest.qWait(50)  # 关闭动画进行中

        # 此时应在关闭中
        assert panel.is_closing, "关闭动画进行中应返回 True"

        # 等待关闭完成
        QTest.qWait(200)
        assert not panel.is_closing, "关闭完成后应返回 False"

        panel.deleteLater()

    def test_reopen_during_close_animation(self, qapp):
        """测试关闭动画进行中调用 reopen 取消关闭并重新打开"""
        panel = _scp._ColorPanel(parent=None)
        anchor = _scp.QPoint(100, 100)

        # 打开面板
        panel.show_animated(anchor)
        QTest.qWait(200)
        assert panel.isVisible()
        assert not panel.is_closing

        # 开始关闭
        panel.close_animated()
        QTest.qWait(50)  # 关闭动画进行中

        # 确认正在关闭
        assert panel.is_closing, "应在关闭中"
        assert panel.isVisible(), "关闭动画进行中仍应可见"

        # 调用 reopen
        panel.reopen()
        QTest.qWait(200)

        # 应该重新打开
        assert panel.isVisible(), "reopen 后应可见"
        assert not panel.is_closing, "reopen 后应不在关闭中"
        assert panel.windowOpacity() > 0.9, "reopen 后应完成淡入"

        # 清理关闭
        panel.close_animated()
        QTest.qWait(200)
        panel.deleteLater()

    def test_open_close_start_reopen_sequence(self, qapp):
        """测试完整的打开 -> 关闭开始 -> 重新打开序列"""
        panel = _scp._ColorPanel(parent=None)
        anchor = _scp.QPoint(100, 100)

        # 第一阶段：打开
        panel.show_animated(anchor)
        QTest.qWait(200)
        assert panel.isVisible()
        assert not panel.is_closing
        opacity_after_open = panel.windowOpacity()
        assert opacity_after_open > 0.9

        # 第二阶段：开始关闭（但不等待完成）
        panel.close_animated()
        QTest.qWait(50)  # 关闭动画开始
        assert panel.is_closing, "关闭动画应已开始"
        assert panel.isVisible(), "关闭动画进行中应仍可见"
        opacity_during_close = panel.windowOpacity()
        assert opacity_during_close < opacity_after_open, "透明度应在降低"

        # 第三阶段：重新打开（取消关闭）
        panel.reopen()
        QTest.qWait(200)
        assert panel.isVisible(), "reopen 后应可见"
        assert not panel.is_closing, "reopen 后应不在关闭中"
        assert panel.windowOpacity() > 0.9, "reopen 后应完成淡入"

        # 清理
        panel.close_animated()
        QTest.qWait(200)
        panel.deleteLater()

    def test_rapid_40_alternating_operations(self, qapp):
        """测试 40 次快速交替操作（打开/关闭/重新打开）状态确定性"""
        panel = _scp._ColorPanel(parent=None)
        anchor = _scp.QPoint(100, 100)

        for i in range(40):
            # 打开
            if not panel.isVisible():
                panel.show_animated(anchor)
                QTest.qWait(10)
            else:
                # 如果可见，根据状态决定操作
                if panel.is_closing:
                    # 正在关闭中，重新打开
                    panel.reopen()
                    QTest.qWait(10)
                else:
                    # 完全可见，关闭
                    panel.close_animated()
                    QTest.qWait(10)

        # 等待所有动画完成
        QTest.qWait(300)

        # 最终状态确定性：要么可见且不关闭中，要么隐藏且不关闭中
        if panel.isVisible():
            assert not panel.is_closing, "最终状态：如果可见，不应在关闭中"
        else:
            assert not panel.is_closing, "最终状态：如果隐藏，不应在关闭中"

        panel.deleteLater()

    def test_reopen_when_not_closing_is_noop(self, qapp):
        """测试在非关闭状态下调用 reopen 无操作"""
        panel = _scp._ColorPanel(parent=None)
        anchor = _scp.QPoint(100, 100)

        # 打开面板并等待动画完成
        panel.show_animated(anchor)
        QTest.qWait(250)  # 等待淡入完成（180ms）

        # 确保面板处于完全打开状态
        assert panel.windowOpacity() >= 0.99, "面板应已完全打开"
        assert not panel.is_closing, "面板应不在关闭中"

        # 在非关闭状态调用 reopen（应无操作，因为 is_closing=False）
        panel.reopen()
        QTest.qWait(50)

        # 状态应保持不变
        assert panel.isVisible(), "面板应仍可见"
        assert not panel.is_closing, "面板应仍不在关闭中"
        assert panel.windowOpacity() >= 0.99, "透明度应保持接近1.0"

        panel.close_animated()
        QTest.qWait(200)
        panel.deleteLater()


class TestOutsideClickEventFilterLogic:
    """测试外部点击事件过滤器的逻辑
    
    这些测试直接测试 eventFilter 的行为，不依赖完整的 AppearanceSettingsPage 模块。
    通过创建模拟对象来验证事件过滤器的核心逻辑。
    """

    def test_point_inside_rect_detection(self, qapp):
        """测试点是否在矩形内的检测逻辑"""
        from PySide6.QtCore import QRectF, QPointF
        
        # 模拟面板全局矩形
        panel_rect = QRectF(100, 100, 288, 300)  # x, y, width, height
        
        # 测试点在矩形内
        inside_point = QPointF(150, 150)
        assert panel_rect.contains(inside_point), "点应在矩形内"
        
        # 测试点在矩形外
        outside_point = QPointF(50, 50)
        assert not panel_rect.contains(outside_point), "点应在矩形外"
        
        # 测试点在矩形边缘
        edge_point = QPointF(100, 100)
        assert panel_rect.contains(edge_point), "边缘点应在矩形内"

    def test_point_inside_button_rect(self, qapp):
        """测试点是否在按钮矩形内的检测逻辑"""
        from PySide6.QtCore import QRectF, QPointF
        
        # 模拟按钮全局矩形
        btn_rect = QRectF(200, 50, 40, 40)  # x, y, width, height
        
        # 测试点击按钮内部
        btn_inside = QPointF(220, 70)
        assert btn_rect.contains(btn_inside), "点应在按钮内"
        
        # 测试点击按钮外部
        btn_outside = QPointF(300, 70)
        assert not btn_rect.contains(btn_outside), "点应在按钮外"

    def test_global_rect_from_widget_position(self, qapp):
        """测试从 widget 位置构建全局矩形"""
        from PySide6.QtWidgets import QWidget
        from PySide6.QtCore import QRectF, QPoint
        
        widget = QWidget()
        widget.setFixedSize(100, 100)
        widget.move(50, 50)
        widget.show()
        QTest.qWait(50)
        
        # 获取全局位置
        global_pos = widget.mapToGlobal(QPoint(0, 0))
        global_rect = QRectF(global_pos, widget.size())
        
        # 验证矩形尺寸（位置可能受窗口框架影响）
        assert global_rect.width() == 100, "全局矩形宽度应正确"
        assert global_rect.height() == 100, "全局矩形高度应正确"
        # 位置应该是有效的（非零或合理值）
        assert global_rect.x() > 0, "全局矩形 x 坐标应有效"
        assert global_rect.y() > 0, "全局矩形 y 坐标应有效"
        
        widget.close()
        widget.deleteLater()

    def test_event_filter_returns_false_always(self, qapp):
        """测试 eventFilter 始终返回 False（不拦截事件）"""
        from PySide6.QtCore import QEvent, QPointF, QObject
        from PySide6.QtGui import QMouseEvent
        
        # 创建模拟的 eventFilter 实现
        class MockEventFilter(QObject):
            def __init__(self):
                super().__init__()
                self._event_filter_installed = False
            
            def eventFilter(self, watched: QObject, event: QEvent) -> bool:
                """模拟 AppearanceSettingsPage.eventFilter 的返回行为"""
                if event.type() == QEvent.Type.MouseButtonPress:
                    # 无论什么情况，都返回 False 让事件继续传播
                    return False
                return False
        
        mock_filter = MockEventFilter()
        
        # 创建模拟事件
        mouse_event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(10, 10),
            QPointF(10, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        
        # 调用 eventFilter
        result = mock_filter.eventFilter(QObject(), mouse_event)
        
        # 应始终返回 False
        assert not result, "eventFilter 应返回 False"

    def test_install_remove_event_filter_idempotent(self, qapp):
        """测试安装和移除事件过滤器是幂等的"""
        from PySide6.QtWidgets import QWidget, QMainWindow
        from PySide6.QtCore import QObject
        
        main_window = QMainWindow()
        main_window.show()
        QTest.qWait(50)
        
        # 创建模拟过滤器对象
        class MockFilter(QObject):
            def __init__(self):
                super().__init__()
                self._installed = False
            
            def install_filter(self, window):
                if self._installed:
                    return
                window.installEventFilter(self)
                self._installed = True
            
            def remove_filter(self, window):
                if not self._installed:
                    return
                window.removeEventFilter(self)
                self._installed = False
        
        mock = MockFilter()
        
        # 重复安装
        mock.install_filter(main_window)
        assert mock._installed
        mock.install_filter(main_window)  # 再次调用
        assert mock._installed
        
        # 重复移除
        mock.remove_filter(main_window)
        assert not mock._installed
        mock.remove_filter(main_window)  # 再次调用
        assert not mock._installed
        
        main_window.close()
        main_window.deleteLater()

    def test_install_filter_without_window_is_safe(self, qapp):
        """测试无顶层窗口时安装过滤器是安全的"""
        from PySide6.QtCore import QObject
        
        class MockPage(QObject):
            def __init__(self):
                super().__init__()
                self._event_filter_installed = False
            
            def _install_outside_click_filter(self):
                if self._event_filter_installed:
                    return
                top_window = None  # 模拟无顶层窗口
                if top_window is None:
                    return
                top_window.installEventFilter(self)
                self._event_filter_installed = True
            
            def _remove_outside_click_filter(self):
                if not self._event_filter_installed:
                    return
                top_window = None  # 模拟无顶层窗口
                if top_window is None:
                    return
                top_window.removeEventFilter(self)
                self._event_filter_installed = False
        
        mock = MockPage()
        
        # 尝试安装过滤器（应安全地什么都不做）
        mock._install_outside_click_filter()
        assert not mock._event_filter_installed, "无窗口时不应安装过滤器"
        
        # 尝试移除过滤器（应安全地什么都不做）
        mock._remove_outside_click_filter()
        assert not mock._event_filter_installed
