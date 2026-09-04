# -*- coding: utf-8 -*-
"""拖动期快速路径的性能回归门禁。

拖动快速路径（``MicaMaterial.begin_interaction`` 纯移动分支）的契约是 **O(1)/事件**：
不允许逐事件触发整窗重绘、COM 桌面探测或重烘焙 —— 否则帧成本随窗口面积增长
（窗口越大拖动越卡）。本测试以「大量纯移动事件的总耗时」为门禁：一旦未来有人
在该路径里重新引入探测 / 更新 / 重烘（每事件毫秒级），总耗时必然击穿阈值。

阈值取宽松上限（1 万事件 < 500ms ⇒ 单事件 < 50µs），只拦“每事件毫秒级”的退化，
不追逐常数级抖动。
"""

from __future__ import annotations

import time
from unittest import mock

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QWidget

from freeassetfilter.ui.mica import material as material_mod
from freeassetfilter.ui.mica.drag import ViewportLayer

#: 模拟拖动事件数。
EVENTS: int = 10_000
#: 总耗时上限（毫秒）—— 纯 O(1) Python 循环的数百倍余量。
BUDGET_MS: float = 500.0

#: 监视器矩形与窗口尺寸（与 test_mica_material_drag 同构）。
MONITOR = (0, 0, 2560, 1440)
WIN = (1600, 1000)


def test_fast_path_cost_stays_constant_per_event(qapp) -> None:
    """层就绪后连续纯移动事件：总耗时受控，不随事件逐帧做重活。"""
    widget = QWidget()
    mica = material_mod.MicaMaterial(widget, lazy=True)
    try:
        mica._layer = ViewportLayer(region=MONITOR, width=512, height=288, win_size=WIN)
        mica._layer_pixmap = QPixmap(512, 288)
        mica._layer_key = ("params", True, "sig", MONITOR, 2560)
        mica._layer_display_long = 2560
        mica._maybe_rebake = mock.Mock()  # type: ignore[method-assign]

        positions = [
            (i % 1000, (i * 7) % 500, *WIN) for i in range(EVENTS)
        ]  # 全部落在同一监视器内的移动
        started = time.perf_counter()
        for i, win in enumerate(positions):
            mica._window_rect_tuple = lambda w=win: w  # type: ignore[method-assign]
            mica.begin_interaction()
        elapsed_ms = (time.perf_counter() - started) * 1000.0
    finally:
        mica.dispose()
        widget.deleteLater()

    assert elapsed_ms < BUDGET_MS, (
        f"拖动快速路径退化：{EVENTS} 次纯移动事件耗时 {elapsed_ms:.1f}ms"
        f"（预算 {BUDGET_MS:.0f}ms，单事件 > {BUDGET_MS * 1000 / EVENTS:.0f}µs）——"
        "可能重新引入了逐事件重绘 / COM 探测 / 重烘焙"
    )
