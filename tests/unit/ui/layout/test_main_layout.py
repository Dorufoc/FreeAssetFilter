# -*- coding: utf-8 -*-
"""MainLayout 主布局装配测试（classic / workspace 两种组装 + 比例规则）。

覆盖：
- 两种模式的区域/分割条树结构；
- workspace 默认比例：左 1/3、预览画布 16:9（含预览器顶栏补偿）、底行 50:50；
- 半高上限：底行（workspace）/ 信息区（classic）≤ 右区可用高度一半；
- 16:9 降级：窗口过矮时半高上限优先，底行不低于下限（可行时）；
- 用户拖拽右竖条后停止自动 16:9；主横条拖拽时未拖拽右竖条则同步 16:9；
- 窗口缩放（自动态）维持 16:9。

验证命令：
    python -m pytest tests/unit/ui/layout/test_main_layout.py --timeout 60 -q
"""

# targets: ui.layout.main_layout

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Tuple

import pytest
from PySide6.QtWidgets import QApplication

# 布局模块内部使用短路径导入（from theme import tm 等），要求 freeassetfilter/ui
# 位于 sys.path；与 tests/unit/ui/layout/test_layouts.py 的 bootstrap 保持一致。
_UI_ROOT: str = str(Path(__file__).resolve().parents[4] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from freeassetfilter.ui.layout.main_layout import (  # noqa: E402
    BOTTOM_MIN_PX,
    CLASSIC_MODE,
    HANDLE_WIDTH,
    PREVIEW_CHROME_PX,
    WORKSPACE_MODE,
    WORKSPACE_POOL_RATIO,
    MainLayout,
)
from tests.support.qt_helpers import safe_teardown  # noqa: E402

pytestmark = pytest.mark.unit


def _pump_events(qapp: QApplication, ms: float = 300) -> None:
    """有界事件泵：让布局/尺寸事件与延迟比例更新完成。"""
    deadline = time.time() + ms / 1000
    while time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.01)


def _show_layout(
    qapp: QApplication, mode: str, size: Tuple[int, int] = (1200, 800)
) -> MainLayout:
    """显示一个布局并应用默认比例（返回后即可测量尺寸）。"""
    layout = MainLayout(mode)
    layout.resize(*size)
    layout.show()
    _pump_events(qapp)
    layout.apply_default_ratios()
    _pump_events(qapp)
    return layout


def _right_available(layout: MainLayout) -> int:
    """右竖条可用高度（不含把手）。"""
    return max(0, layout.splitters["right"].height() - HANDLE_WIDTH)


class TestMainLayoutStructure:
    """两种模式的分割条树结构。"""

    def test_workspace_structure(self, qapp: QApplication) -> None:
        """workspace：主横条〔选择 | 右竖条〔预览 | 底行〔储存 | 信息〕〕〕。"""
        layout = MainLayout(WORKSPACE_MODE)
        try:
            assert layout.mode == WORKSPACE_MODE
            assert set(layout.zones.keys()) == {"selector", "preview", "pool", "info"}
            assert set(layout.splitters.keys()) == {"main", "right", "bottom"}
            main = layout.splitters["main"]
            right = layout.splitters["right"]
            bottom = layout.splitters["bottom"]
            assert main.count() == 2
            assert main.widget(0) is layout.zones["selector"]
            assert main.widget(1) is right
            assert right.count() == 2
            assert right.widget(0) is layout.zones["preview"]
            assert right.widget(1) is bottom
            assert bottom.count() == 2
            assert bottom.widget(0) is layout.zones["pool"]
            assert bottom.widget(1) is layout.zones["info"]
        finally:
            layout.deleteLater()
            qapp.processEvents()

    def test_classic_structure(self, qapp: QApplication) -> None:
        """classic：主横条〔选择 | 储存 | 右列〔预览 | 信息〕+ 底栏槽位〕。"""
        layout = MainLayout(CLASSIC_MODE)
        try:
            assert layout.mode == CLASSIC_MODE
            assert set(layout.splitters.keys()) == {"main", "right"}
            main = layout.splitters["main"]
            right = layout.splitters["right"]
            assert main.count() == 3
            assert main.widget(0) is layout.zones["selector"]
            assert main.widget(1) is layout.zones["pool"]
            # 右列容器：垂直分割[预览|信息] + 底部操作栏槽位
            right_host = main.widget(2)
            assert right_host is not None
            assert right_host.layout() is not None
            assert right_host.layout().indexOf(right) >= 0
            slot = layout.classic_action_slot()
            assert slot is not None
            assert right_host.layout().indexOf(slot) >= 0
            assert slot.height() == 48
            assert right.count() == 2
            assert right.widget(0) is layout.zones["preview"]
            assert right.widget(1) is layout.zones["info"]
        finally:
            layout.deleteLater()
            qapp.processEvents()

    def test_workspace_has_no_classic_action_slot(self, qapp: QApplication) -> None:
        """workspace 组装无经典底栏槽位。"""
        layout = MainLayout(WORKSPACE_MODE)
        try:
            assert layout.classic_action_slot() is None
        finally:
            layout.deleteLater()
            qapp.processEvents()

    def test_classic_action_slot_at_bottom(self, qapp: QApplication) -> None:
        """经典布局：底栏槽位位于右分割区（预览|信息）下方、整列最底部。"""
        layout = _show_layout(qapp, CLASSIC_MODE, (1180, 742))
        try:
            slot = layout.classic_action_slot()
            right = layout.splitters["right"]
            assert slot is not None
            # 位于右分割区下方（信息面板下侧）
            assert slot.y() >= right.y() + right.height()
            # 48px 高且底边贴近布局底部（与左右两栏底栏同底对齐）
            assert slot.height() == 48
            assert abs((slot.y() + slot.height()) - layout.height()) <= 2
        finally:
            safe_teardown(layout)

    def test_invalid_mode_falls_back_to_workspace(self, qapp: QApplication) -> None:
        """非法模式回退 workspace。"""
        layout = MainLayout("bogus")
        try:
            assert layout.mode == WORKSPACE_MODE
        finally:
            layout.deleteLater()
            qapp.processEvents()


class TestWorkspaceRatios:
    """workspace 默认比例：左 1/3 / 预览画布 16:9 / 底行 50:50 / 半高上限。"""

    def test_default_left_ratio_and_16_9(self, qapp: QApplication) -> None:
        """1200x800：左栏 1/3；预览画布约 16:9（含顶栏补偿）；底行占余下高度。"""
        layout = _show_layout(qapp, WORKSPACE_MODE, (1200, 800))
        try:
            main = layout.splitters["main"]
            right = layout.splitters["right"]
            bottom = layout.splitters["bottom"]

            avail_w = layout.width() - HANDLE_WIDTH
            expect_left = int(round(avail_w * (1.0 / 3.0)))
            left_w, right_w = main.sizes()
            assert abs(left_w - expect_left) <= 3
            assert abs(right_w - (avail_w - expect_left)) <= 3

            v_avail = _right_available(layout)
            # 画布 16:9：预览区高 = 右列宽 × 9/16 + 预览器顶栏补偿
            expect_preview = (
                int(round(right_w * 9.0 / 16.0)) + PREVIEW_CHROME_PX
            )
            preview_h, bottom_h = right.sizes()
            assert abs(preview_h - expect_preview) <= 3
            assert abs(bottom_h - (v_avail - expect_preview)) <= 3

            # 底行半高上限（show 会重置隐藏期约束，故应用后应已重新生效）
            assert abs(bottom.maximumHeight() - v_avail // 2) <= 2
            assert bottom.height() <= v_avail // 2 + 2

            # 底行 50 : 50（储存与信息各占界面约 1/3 宽）
            pool_w, info_w = bottom.sizes()
            assert pool_w + info_w > 0
            assert abs(pool_w / (pool_w + info_w) - WORKSPACE_POOL_RATIO) <= 0.03
        finally:
            safe_teardown(layout)

    def test_bottom_ratio_with_min_width_child(self, qapp: QApplication) -> None:
        """底行一侧带最小宽度（真实储存池约 324px）时仍按 50:50 分配。"""
        layout = _show_layout(qapp, WORKSPACE_MODE, (1200, 800))
        try:
            bottom = layout.splitters["bottom"]
            layout.zones["pool"].setMinimumWidth(324)
            layout.apply_default_ratios()
            _pump_events(qapp)

            pool_w, info_w = bottom.sizes()
            assert pool_w + info_w > 0
            assert abs(pool_w / (pool_w + info_w) - WORKSPACE_POOL_RATIO) <= 0.03
        finally:
            safe_teardown(layout)

    def test_short_window_degrades_with_bottom_min(self, qapp: QApplication) -> None:
        """窗口偏矮：16:9 受底行下限钳制，底行不低于 BOTTOM_MIN_PX。"""
        layout = _show_layout(qapp, WORKSPACE_MODE, (1200, 500))
        try:
            right = layout.splitters["right"]
            bottom = layout.splitters["bottom"]
            v_avail = _right_available(layout)
            preview_h, bottom_h = right.sizes()
            # v_avail=490 → lower=245, upper=290, target=780×9/16+48≈487 → preview=290
            assert abs(bottom_h - BOTTOM_MIN_PX) <= 3
            assert bottom_h <= v_avail // 2 + 2
            assert bottom.height() <= v_avail // 2 + 2
        finally:
            safe_teardown(layout)

    def test_extremely_short_window_cap_wins(self, qapp: QApplication) -> None:
        """窗口极矮：半高上限优先，16:9 优雅降级（预览仍至少占一半）。"""
        layout = _show_layout(qapp, WORKSPACE_MODE, (1200, 360))
        try:
            right = layout.splitters["right"]
            v_avail = _right_available(layout)
            _, bottom_h = right.sizes()
            assert bottom_h <= v_avail // 2 + 2
        finally:
            safe_teardown(layout)

    def test_cap_blocks_programmatic_oversize(self, qapp: QApplication) -> None:
        """把底行拉到远超半高：被 maximumHeight 钳制，预览区获得余下高度。"""
        layout = _show_layout(qapp, WORKSPACE_MODE, (1200, 800))
        try:
            right = layout.splitters["right"]
            bottom = layout.splitters["bottom"]
            v_avail = _right_available(layout)
            half = v_avail // 2

            right.setSizes([120, v_avail * 4])
            _pump_events(qapp)

            _, bottom_h = right.sizes()
            assert bottom_h <= half + 2
            assert bottom.height() <= half + 2
        finally:
            safe_teardown(layout)

    def test_resize_maintains_16_9_until_drag(self, qapp: QApplication) -> None:
        """窗口缩放（未拖拽）：预览区宽度变化后自动维持 16:9。"""
        layout = _show_layout(qapp, WORKSPACE_MODE, (1200, 800))
        try:
            layout.resize(1400, 900)
            _pump_events(qapp)

            right = layout.splitters["right"]
            preview_h, _ = right.sizes()
            expect = (
                int(round(right.width() * 9.0 / 16.0)) + PREVIEW_CHROME_PX
            )
            # 钳制可能介入，但 1400x900 下目标值处于 [lower, upper] 区间内
            v_avail = _right_available(layout)
            assert v_avail // 2 <= expect <= v_avail - BOTTOM_MIN_PX
            assert abs(preview_h - expect) <= 3
        finally:
            safe_teardown(layout)

    def test_drag_right_splitter_disables_auto(self, qapp: QApplication) -> None:
        """用户拖拽右竖条后：后续窗口缩放不再自动改回 16:9。"""
        layout = _show_layout(qapp, WORKSPACE_MODE, (1200, 800))
        try:
            right = layout.splitters["right"]
            v_avail = _right_available(layout)

            # 模拟用户拖拽（QSplitter.splitterMoved 仅在真实拖拽时发射）
            right.setSizes([v_avail - 150, 150])
            _pump_events(qapp)
            layout._on_right_splitter_moved(0, 1)
            assert layout._right_user_dragged is True
            dragged_ratio = right.sizes()[0] / max(1, _right_available(layout))

            layout.resize(1400, 900)
            _pump_events(qapp)

            # 自动 16:9 已停用：缩放后保持用户比例（QSplitter 按比例缩放），
            # 且明显偏离 16:9 目标值
            new_ratio = right.sizes()[0] / max(1, _right_available(layout))
            assert abs(new_ratio - dragged_ratio) <= 0.02
            expect_16_9 = right.width() * 9.0 / 16.0 + PREVIEW_CHROME_PX
            assert abs(right.sizes()[0] - expect_16_9) > 10
        finally:
            safe_teardown(layout)

    def test_main_drag_syncs_16_9_when_not_dragged(self, qapp: QApplication) -> None:
        """主横条（左右分界）拖拽：未拖拽右竖条时按新宽度同步 16:9。"""
        layout = _show_layout(qapp, WORKSPACE_MODE, (1200, 800))
        try:
            main = layout.splitters["main"]
            right = layout.splitters["right"]
            avail_w = layout.width() - HANDLE_WIDTH

            main.setSizes([200, avail_w - 200])
            _pump_events(qapp)
            layout._on_main_splitter_moved(0, 1)
            _pump_events(qapp)

            expect = (
                int(round(right.width() * 9.0 / 16.0)) + PREVIEW_CHROME_PX
            )
            # 主横条拖到 200px 后右列变宽，目标值可能触及底行下限 → 按钳制取值
            v_avail = _right_available(layout)
            lower = v_avail - v_avail // 2
            upper = v_avail - BOTTOM_MIN_PX
            if upper < lower:
                expect = lower
            else:
                expect = max(lower, min(expect, upper))
            assert abs(right.sizes()[0] - expect) <= 3
        finally:
            safe_teardown(layout)

    def test_apply_default_ratios_resets_drag(self, qapp: QApplication) -> None:
        """apply_default_ratios 复位拖拽标记并恢复 16:9 默认比例。"""
        layout = _show_layout(qapp, WORKSPACE_MODE, (1200, 800))
        try:
            right = layout.splitters["right"]
            v_avail = _right_available(layout)
            right.setSizes([v_avail - 150, 150])
            layout._on_right_splitter_moved(0, 1)
            assert layout._right_user_dragged is True

            layout.apply_default_ratios()
            _pump_events(qapp)

            assert layout._right_user_dragged is False
            expect = (
                int(round(right.width() * 9.0 / 16.0)) + PREVIEW_CHROME_PX
            )
            assert abs(right.sizes()[0] - expect) <= 3
        finally:
            safe_teardown(layout)


class TestClassicRatios:
    """classic 默认比例：三栏等分 / 右栏各半 / 信息区 ≤ 半高。"""

    def test_default_three_columns_equal(self, qapp: QApplication) -> None:
        """1200x800：三栏约各 1/3；右栏上下各半；信息区半高上限。"""
        layout = _show_layout(qapp, CLASSIC_MODE, (1200, 800))
        try:
            main = layout.splitters["main"]
            right = layout.splitters["right"]
            info = layout.zones["info"]

            avail_w = layout.width() - 2 * HANDLE_WIDTH
            third = avail_w // 3
            sizes = main.sizes()
            for size in sizes:
                assert abs(size - third) <= 3

            v_avail = _right_available(layout)
            half = v_avail // 2
            preview_h, info_h = right.sizes()
            assert abs(preview_h - info_h) <= 3
            assert info.maximumHeight() == half
            assert info.height() <= half + 2
        finally:
            safe_teardown(layout)

    def test_info_capped_at_half(self, qapp: QApplication) -> None:
        """把信息区拉到远超半高：被钳制，预览区占余下部分。"""
        layout = _show_layout(qapp, CLASSIC_MODE, (1200, 800))
        try:
            right = layout.splitters["right"]
            info = layout.zones["info"]
            v_avail = _right_available(layout)
            half = v_avail // 2

            right.setSizes([120, v_avail * 4])
            _pump_events(qapp)

            assert info.height() <= half + 2
            assert right.sizes()[0] >= half - 2
        finally:
            safe_teardown(layout)
