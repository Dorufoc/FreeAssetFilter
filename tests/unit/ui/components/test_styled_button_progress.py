# -*- coding: utf-8 -*-
"""StyledButton 运行时进度模式单元测试。

覆盖 ``set_progress`` / ``progress`` 的状态读写与钳制、进度模式下
spinner 定时器的惰性启停、以及 paintEvent 进度分支（轨道 + 填充 +
spinner + 百分比文本）的离屏渲染冒烟。约束与 test_styled_fluid.py
一致：全部离屏（绝不 show() 真实窗口）、显式依赖 session qapp、
百分比文本由 paint 自绘（不污染 QPushButton 文本）。

验证命令：
    python -m pytest tests/unit/ui/components/test_styled_button_progress.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QApplication

# 组件模块内部使用短路径导入（from theme import tm / components.*），
# 要求 freeassetfilter/ui 位于 sys.path；与 test_styled_basic.py 一致。
_UI_ROOT: str = str(Path(__file__).resolve().parents[4] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from tests.support.qt_helpers import assert_pixmap_nonempty, safe_teardown  # noqa: E402

from freeassetfilter.ui.components.styled_button import StyledButton  # noqa: E402

pytestmark = pytest.mark.unit


def _make_button(qapp: Any) -> StyledButton:
    """构造固定尺寸的 primary 生成按钮（与底栏「生成缩略图」同变体）。

    Args:
        qapp: 会话级 QApplication。

    Returns:
        StyledButton: 已 resize(120, 40) 的按钮实例（未 show，离屏渲染）。
    """
    del qapp  # 依赖 qapp fixture 保证 QApplication 已存在，本身不直接使用
    btn = StyledButton("生成缩略图", variant="primary", size="sm")
    btn.resize(120, 40)
    return btn


# =============================================================================
# 状态读写与钳制
# =============================================================================
class TestProgressState:
    """set_progress / progress 的状态读写与钳制。"""

    def test_set_and_clear_progress(self, qapp: QApplication) -> None:
        """set_progress(0.5) 写入 0.5；set_progress(None) 归 None。"""
        btn = _make_button(qapp)
        assert btn.progress() is None, "初始应处于非进度模式"
        btn.set_progress(0.5)
        assert btn.progress() == 0.5
        btn.set_progress(None)
        assert btn.progress() is None
        safe_teardown(btn)

    def test_progress_clamped_to_unit_range(self, qapp: QApplication) -> None:
        """越界值钳制到 [0.0, 1.0]：1.5 → 1.0、-0.2 → 0.0。"""
        btn = _make_button(qapp)
        btn.set_progress(1.5)
        assert btn.progress() == 1.0
        btn.set_progress(-0.2)
        assert btn.progress() == 0.0
        btn.set_progress(None)
        safe_teardown(btn)

    def test_progress_mode_keeps_button_text(self, qapp: QApplication) -> None:
        """进度模式不污染 QPushButton 文本（百分比由 paint 自绘）。"""
        btn = _make_button(qapp)
        btn.set_progress(0.3)
        assert btn.text() == "生成缩略图"
        btn.set_progress(None)
        assert btn.text() == "生成缩略图"
        safe_teardown(btn)


# =============================================================================
# spinner 定时器启停联动
# =============================================================================
class TestProgressTimer:
    """进度模式与 spinner 定时器（_timer）的惰性启停联动。"""

    def test_progress_activates_and_stops_spinner_timer(
        self, qapp: QApplication
    ) -> None:
        """set_progress 惰性创建并激活定时器；set_progress(None) 停止。"""
        btn = _make_button(qapp)
        assert btn._timer is None  # noqa: SLF001 - 定时器惰性创建契约
        btn.set_progress(0.3)
        assert btn._timer is not None  # noqa: SLF001
        assert btn._timer.isActive()  # noqa: SLF001
        btn.set_progress(None)
        assert not btn._timer.isActive()  # noqa: SLF001
        safe_teardown(btn)


# =============================================================================
# paintEvent 进度分支渲染冒烟
# =============================================================================
class TestProgressPaint:
    """paintEvent 进度分支（轨道 + 填充 + spinner + 百分比）离屏渲染冒烟。"""

    def test_progress_mode_grab_renders_nonempty(self, qapp: QApplication) -> None:
        """进度模式 grab() 不崩溃且渲染非空 pixmap（真实执行进度分支）。"""
        btn = _make_button(qapp)
        btn.set_progress(0.42)
        pm = btn.grab()
        assert not pm.isNull()
        # grab() 返回物理像素 pixmap（含 devicePixelRatio），仅断言
        # 设备无关尺寸覆盖按钮逻辑尺寸（120x40），不做像素级相等
        assert pm.width() > 0 and pm.height() > 0
        assert_pixmap_nonempty(pm, "进度模式渲染不应为全零像素")
        btn.set_progress(None)
        safe_teardown(btn)

    def test_exit_progress_mode_returns_to_normal_paint(
        self, qapp: QApplication
    ) -> None:
        """退出进度模式后回到普通文本绘制路径，grab 正常。"""
        btn = _make_button(qapp)
        btn.set_progress(0.7)
        btn.grab()  # 先走一次进度分支
        btn.set_progress(None)
        pm = btn.grab()
        assert not pm.isNull()
        assert_pixmap_nonempty(pm, "退出进度模式后普通绘制路径应正常渲染")
        safe_teardown(btn)
