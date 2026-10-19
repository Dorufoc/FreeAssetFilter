# -*- coding: utf-8 -*-
"""文本预览器 Ctrl+滚轮字号缩放：步进、钳制与缩放弹窗同步测试。

回归背景：Ctrl+滚轮曾由 QTextEdit / QTextBrowser 的 Qt 原生缩放处理，
只改控件自身字号、不经过 ``TextPreviewerLayout._font_size``，导致缩放
弹窗滑条/百分比与实际字号脱节（旧架构 ``ZoomDisabledTextEdit`` 的行为
在布局重构后丢失）。

用例通过向控件视口合成 ``QWheelEvent`` 驱动，不依赖窗口管理器，
offscreen 平台同样可运行。
"""

from __future__ import annotations

import time
from typing import Any, Iterator, Optional

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QTextEdit

from freeassetfilter.ui.layout.preview import text_previewer_layout as _tpl
from freeassetfilter.ui.layout.preview.text_previewer_layout import (
    TextPreviewerLayout,
)
from tests.support.qt_helpers import safe_teardown

pytestmark = pytest.mark.unit

_BASE_FONT_SIZE = 14
_FONT_SIZE_MIN = 8
_FONT_SIZE_MAX = 32


class _CountingMarkdownRenderer:
    """Markdown 渲染测试替身：记录 render() 调用次数与最后一次字号。

    与真实 ``MarkdownRenderer`` 保持同一构造/调用契约（``font_size``
    关键字、``is_available()``、``set_font_size()``、``render()``），
    供 Ctrl+滚轮防抖合并断言使用。
    """

    call_count = 0
    last_font_size: Optional[int] = None

    def __init__(self, font_size: int = _BASE_FONT_SIZE) -> None:
        self._font_size = font_size

    @classmethod
    def is_available(cls) -> bool:
        """模拟 markdown + pygments 可用。"""
        return True

    def set_font_size(self, size: int) -> None:
        """与真实渲染器一致的字号设置。"""
        self._font_size = size

    def render(self, text: str, file_path: Optional[str] = None) -> str:
        """返回内嵌字号与输入长度的可断言 HTML。"""
        _CountingMarkdownRenderer.call_count += 1
        _CountingMarkdownRenderer.last_font_size = self._font_size
        return f"<p>rendered-{self._font_size}:{len(text)}</p>"


def _pump(qapp: QApplication, ms: int = 150) -> None:
    """有界事件泵：等待平滑滚动动画 / 字号防抖计时器落地。"""
    deadline = time.monotonic() + ms / 1000.0
    while time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)


def _pump_until(qapp: QApplication, predicate: Any, timeout_ms: int = 3000) -> bool:
    """泵事件直到条件成立或超时（返回最终判定结果）。"""
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        if predicate():
            return True
        qapp.processEvents()
        time.sleep(0.01)
    return bool(predicate())


def _send_wheel(
    widget: QTextEdit, delta_y: int, modifiers: Any = Qt.ControlModifier
) -> None:
    """向控件视口合成一次滚轮事件（QAbstractScrollArea 转发到 wheelEvent）。"""
    pos = QPointF(widget.rect().center())
    event = QWheelEvent(
        pos,
        QPointF(widget.mapToGlobal(pos.toPoint())),
        QPoint(0, 0),
        QPoint(0, delta_y),
        Qt.NoButton,
        modifiers,
        Qt.ScrollUpdate,
        False,
    )
    QApplication.sendEvent(widget.viewport(), event)


@pytest.fixture()
def layout(qapp: QApplication) -> Iterator[TextPreviewerLayout]:
    """构造并显示文本预览器，测试结束后安全销毁。"""
    previewer = TextPreviewerLayout()
    previewer.resize(900, 600)
    previewer.show()
    _pump(qapp, 60)
    yield previewer
    safe_teardown(previewer)


def test_ctrl_wheel_steps_source_view_and_syncs_popup(
    qapp: QApplication, layout: TextPreviewerLayout
) -> None:
    """Ctrl+滚轮 ±1 格：字号状态、控件字号与缩放弹窗同步更新。"""
    layout._on_zoom_clicked()
    popup = layout._zoom_popup
    assert popup is not None

    edit = layout._source_view._text_edit
    assert layout._font_size == _BASE_FONT_SIZE

    _send_wheel(edit, 120)
    assert layout._font_size == 15
    # 若 Qt 原生缩放未被拦截，文档字号会在 15 基础上再次变化；
    # 恒等于 _font_size 说明事件只应用了一次
    assert edit.document().defaultFont().pointSizeF() == 15.0
    assert popup._pct_btn.text() == "107%"
    assert popup._slider.value == pytest.approx((15 - _FONT_SIZE_MIN) / 24.0)

    _send_wheel(edit, -120)
    assert layout._font_size == _BASE_FONT_SIZE
    assert edit.document().defaultFont().pointSizeF() == float(_BASE_FONT_SIZE)
    assert popup._pct_btn.text() == "100%"
    assert popup._slider.value == pytest.approx(
        (_BASE_FONT_SIZE - _FONT_SIZE_MIN) / 24.0
    )


def test_ctrl_wheel_clamped_at_bounds(
    qapp: QApplication, layout: TextPreviewerLayout
) -> None:
    """连续上/下滚钳制在 8~32，弹窗百分比同步到边界值。"""
    layout._on_zoom_clicked()
    popup = layout._zoom_popup
    assert popup is not None
    edit = layout._source_view._text_edit

    for _ in range(30):
        _send_wheel(edit, 120)
    assert layout._font_size == _FONT_SIZE_MAX
    assert popup._pct_btn.text() == "229%"

    _send_wheel(edit, 120)
    assert layout._font_size == _FONT_SIZE_MAX

    for _ in range(40):
        _send_wheel(edit, -120)
    assert layout._font_size == _FONT_SIZE_MIN
    assert popup._pct_btn.text() == "57%"

    _send_wheel(edit, -120)
    assert layout._font_size == _FONT_SIZE_MIN


def test_plain_wheel_scrolls_without_zoom(
    qapp: QApplication, layout: TextPreviewerLayout
) -> None:
    """普通滚轮：只滚动、不改字号（Ctrl+滚轮拦截不影响平滑滚动）。"""
    layout.set_text_content(
        "\n".join(f"line {i}" for i in range(300)), "sample.txt"
    )
    _pump(qapp, 80)
    edit = layout._source_view._text_edit
    assert edit.document().defaultFont().pointSizeF() == float(_BASE_FONT_SIZE)

    _send_wheel(edit, -120, Qt.NoModifier)
    _pump(qapp, 300)  # 平滑滚动动画 150ms

    assert layout._font_size == _BASE_FONT_SIZE
    assert edit.document().defaultFont().pointSizeF() == float(_BASE_FONT_SIZE)
    assert edit.verticalScrollBar().value() > 0


def test_markdown_ctrl_wheel_debounces_and_syncs(
    qapp: QApplication, monkeypatch: Any
) -> None:
    """Markdown 模式：连滚只触发一次渲染，弹窗在防抖期间即已同步。"""
    monkeypatch.setattr(_tpl, "_MarkdownRenderer", _CountingMarkdownRenderer)
    _CountingMarkdownRenderer.call_count = 0
    _CountingMarkdownRenderer.last_font_size = None

    previewer = TextPreviewerLayout()
    previewer.resize(900, 600)
    previewer.show()
    try:
        previewer.set_text_content("# hello\nworld", "note.md")
        browser = previewer._markdown_view._text_browser
        assert _pump_until(
            qapp,
            lambda: _CountingMarkdownRenderer.call_count >= 1
            and browser.toPlainText().strip() == "rendered-14:13",
        )
        _CountingMarkdownRenderer.call_count = 0

        previewer._on_zoom_clicked()
        popup = previewer._zoom_popup
        assert popup is not None

        # 连续 5 格（期间不泵事件：防抖窗口内不触发渲染）
        for _ in range(5):
            _send_wheel(browser, 120)
        assert previewer._font_size == 19
        assert popup._pct_btn.text() == "136%"
        assert popup._slider.value == pytest.approx((19 - _FONT_SIZE_MIN) / 24.0)
        assert _CountingMarkdownRenderer.call_count == 0

        # 越过 120ms 防抖窗口：只渲染一次且为最终字号
        assert _pump_until(
            qapp,
            lambda: _CountingMarkdownRenderer.call_count == 1
            and browser.toPlainText().strip() == "rendered-19:13",
            timeout_ms=5000,
        )
        assert _CountingMarkdownRenderer.last_font_size == 19
        assert browser.font().pointSizeF() == 19.0
    finally:
        safe_teardown(previewer)
