"""帧率无关的时长回归：提高帧率不得改变既有操作时长。

这里锁死的是「动画时长由墙钟决定」这一条：无论动画跑在 Qt 原生 ~16ms 驱动，
还是被 :mod:`sopeek.ui.frame_pacing` 提到面板刷新率，``setDuration(200)`` 都必须
在 200ms 左右结束。窗口给得比较宽松（±60ms），因为它守的是「量级/语义」而不是
逐帧精度——真正的精度由 ``tests/unit/test_frame_scheduler.py`` 的节拍用例负责。
"""

from __future__ import annotations

import time

import pytest
from PySide6.QtCore import QPoint, QPropertyAnimation
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

import sopeek.ui  # noqa: F401  (导入即安装动画补丁，模拟真实进程)

_DURATION_MS = 200


@pytest.fixture()
def animated_widget(qapp):
    """提供一个可动画的顶层控件（``pos`` 是 Qt 属性，离屏也可写）。"""
    widget = QWidget()
    widget.resize(120, 80)
    yield widget
    widget.deleteLater()


def test_property_animation_duration_is_wall_clock(animated_widget, qapp):
    """200ms 的属性动画实际耗时必须落在 200ms 量级，不能被帧率放大或缩小。"""
    animation = QPropertyAnimation(animated_widget, b"pos")
    animation.setDuration(_DURATION_MS)
    animation.setStartValue(QPoint(0, 0))
    animation.setEndValue(QPoint(60, 40))

    finished_at: list[float] = []
    animation.finished.connect(lambda: finished_at.append(time.monotonic()))

    started = time.monotonic()
    animation.start()
    QTest.qWait(_DURATION_MS * 4)

    assert finished_at, "动画未在超时时间内结束"
    elapsed_ms = (finished_at[0] - started) * 1000.0
    assert 140.0 <= elapsed_ms <= 260.0, f"动画时长偏离墙钟目标：{elapsed_ms:.1f}ms"


def test_property_animation_end_value_reached(animated_widget, qapp):
    """动画结束时属性必须精确落到 endValue（插值驱动不得跳值）。"""
    animation = QPropertyAnimation(animated_widget, b"pos")
    animation.setDuration(_DURATION_MS)
    animation.setStartValue(QPoint(0, 0))
    animation.setEndValue(QPoint(60, 40))

    animation.start()
    QTest.qWait(_DURATION_MS * 4)

    assert animation.state() == QPropertyAnimation.State.Stopped
    assert animated_widget.pos() == QPoint(60, 40)
