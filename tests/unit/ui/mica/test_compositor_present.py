# -*- coding: utf-8 -*-
"""自研合成器（``ui.mica.compositor``）的呈现调度测试。

锁定「整块虚拟桌面层 + 窗口视口取样 + 自适应呈现」的可断言不变量：

* **首帧 / 跳变立即呈现** —— 最大化、Win+方向键吸附、还原、跨屏瞬移等
  位置跳变必须在**首个事件**立即呈现（零延迟刷新）；
* **取样未变零重绘** —— 亚像素抖动 / 原地微动不产生任何重绘（SKIP）；
* **常规拖动自适应节流** —— 绘制便宜时锁定 16ms（≈逐帧，无感知延迟），
  昂贵时按实测成本降频（DEFER + 补绘），且补绘间隔有 50ms 地板；
* **成本 EMA** —— 呈现耗时喂入指数滑动平均，决定目标呈现间隔。
"""

from __future__ import annotations

import pytest
from PySide6.QtGui import QPixmap

from freeassetfilter.ui.mica.compositor import (
    MAX_PRESENT_INTERVAL_MS,
    MIN_PRESENT_INTERVAL_MS,
    PRESENT_DEFER,
    PRESENT_NOW,
    PRESENT_SKIP,
    ViewportCompositor,
)
from freeassetfilter.ui.mica.drag import ViewportLayer

#: 虚拟桌面矩形（层 1:1 覆盖）。
REGION = (0, 0, 2560, 1440)
#: 窗口尺寸。
WIN = (1600, 1000)

# 本模块在测试体内构造 QPixmap，必须保证 QApplication 先行创建。
pytestmark = pytest.mark.usefixtures("qapp")


def _ready_compositor(region: tuple = REGION) -> ViewportCompositor:
    """构造一块层就绪的合成器（层与虚拟区域 1:1）。"""
    comp = ViewportCompositor()
    layer = ViewportLayer(
        region=region, width=region[2], height=region[3], win_size=WIN
    )
    comp.set_layer(layer, QPixmap(region[2], region[3]))
    return comp


def test_first_advise_presents_now() -> None:
    """层提交后首次 advise：无呈现锚点 → 立即呈现。"""
    comp = _ready_compositor()
    assert comp.advise((0, 0, *WIN)) == PRESENT_NOW


def test_unchanged_sample_skips_present() -> None:
    """呈现锚点与当前取样一致（原地 / 亚像素微动）→ SKIP，零重绘。"""
    comp = _ready_compositor()
    win = (0, 0, *WIN)
    comp.note_presented(win, 0.5)
    assert comp.advise(win) == PRESENT_SKIP


def test_jump_presents_immediately() -> None:
    """位置跳变（单轴位移 > 96px）：立即呈现，不留节流延迟。"""
    comp = _ready_compositor()
    comp.note_presented((0, 0, *WIN), 0.5)
    # 刚呈现过（节流窗口必然未过），但 500px 跳变必须立即呈现。
    assert comp.advise((500, 0, *WIN)) == PRESENT_NOW
    # 尺寸变化同样是跳变（吸附 / 最大化 / 还原）。
    comp.note_presented((500, 0, *WIN), 0.5)
    assert comp.advise((500, 0, 2000, 1200)) == PRESENT_NOW


def test_small_move_within_throttle_defers_with_pending_timer() -> None:
    """连续小位移且节流窗口未过 → DEFER（由补绘定时器兜底刷新）。"""
    comp = _ready_compositor()
    comp.note_presented((0, 0, *WIN), 0.5)
    # 1px 连续拖动：非跳变、取样已变、节流窗口未过。
    assert comp.advise((1, 0, *WIN)) == PRESENT_DEFER
    delay = comp.defer_delay_ms()
    assert 1 <= delay <= MAX_PRESENT_INTERVAL_MS


def test_elapsed_interval_presents_now(monkeypatch: pytest.MonkeyPatch) -> None:
    """节流窗口已过 → 立即呈现（不会无限 DEFER 丢失刷新）。"""
    comp = _ready_compositor()
    comp.note_presented((0, 0, *WIN), 0.5)
    # 把目标间隔压成 0：任何时间消耗都视为窗口已过。
    monkeypatch.setattr(comp, "interval_ms", lambda: 0.0)
    assert comp.advise((1, 0, *WIN)) == PRESENT_NOW


def test_cost_ema_adapts_interval() -> None:
    """绘制成本喂入 EMA：便宜 → 下限 16ms（逐帧）；昂贵 → 上限 50ms（降频地板）。"""
    comp = _ready_compositor()
    comp.note_presented((0, 0, *WIN), 0.5)
    low = comp.interval_ms()
    assert MIN_PRESENT_INTERVAL_MS <= low <= 20.0
    comp.note_presented((0, 0, *WIN), 40.0)
    comp.note_presented((0, 0, *WIN), 40.0)
    comp.note_presented((0, 0, *WIN), 40.0)
    high = comp.interval_ms()
    assert high <= MAX_PRESENT_INTERVAL_MS
    assert high > low


def test_set_geometry_and_pixels_invalidate_anchor() -> None:
    """``set_geometry`` / ``set_pixels``（material 属性 setter 委托路径）
    必须作废呈现锚点 —— 新层 / 新像素后的首个事件立即呈现。"""
    comp = _ready_compositor()
    comp.note_presented((0, 0, *WIN), 0.5)
    assert comp.advise((0, 0, *WIN)) == PRESENT_SKIP

    layer = ViewportLayer(region=REGION, width=1280, height=720, win_size=WIN)
    comp.set_geometry(layer)
    assert comp.layer is layer
    assert comp.pixmap is not None
    # 几何变了（同位置取样坐标随之改变），锚点必须已失效。
    assert comp.advise((0, 0, *WIN)) == PRESENT_NOW

    comp.note_presented((0, 0, *WIN), 0.5)
    comp.set_pixels(QPixmap(64, 64))
    assert comp.advise((0, 0, *WIN)) == PRESENT_NOW


def test_clear_resets_everything() -> None:
    """``clear``（dispose / 原生模式切换）后层未就绪，advise 恒 SKIP。"""
    comp = _ready_compositor()
    comp.clear()
    assert not comp.ready
    assert comp.layer is None
    assert comp.pixmap is None
    assert comp.advise((0, 0, *WIN)) == PRESENT_SKIP
