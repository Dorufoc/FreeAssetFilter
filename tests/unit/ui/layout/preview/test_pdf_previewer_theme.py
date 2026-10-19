# -*- coding: utf-8 -*-
# targets: freeassetfilter.ui.layout.preview.pdf_previewer_layout
"""PDF 预览器主题重绘契约。

页面卡片外框随主题显隐（浅色不描边 / 深色描边），而渲染器自身不订阅
``tm.theme_changed``：``_on_theme_changed`` 必须显式重绘 PDF 画布，否则
外框显隐会滞后到下一次滚动 / 缩放才生效。
"""
from __future__ import annotations

from typing import Any

import pytest

from PySide6.QtWidgets import QApplication

import freeassetfilter.ui.layout.preview.pdf_previewer_layout as pdf_layout_mod
from freeassetfilter.ui.layout.preview.native_pdf_renderer import NativePdfRenderer
from freeassetfilter.ui.layout.preview.pdf_previewer_layout import PdfPreviewerLayout
from tests.support.qt_helpers import flush_widget_queue, safe_teardown

pytestmark = pytest.mark.unit


class _UpdateSpy(NativePdfRenderer):
    """记录 ``update()`` 调用次数的渲染器子类（断言画布被强制重绘）。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.update_calls: int = 0

    def update(self, *args: Any, **kwargs: Any) -> None:
        """记录调用后走默认实现（真正请求重绘）。"""
        self.update_calls += 1
        super().update(*args, **kwargs)


def test_theme_changed_repaints_pdf_canvas(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """主题切换回调显式重绘 PDF 画布（卡片外框显隐即时生效）。"""
    monkeypatch.setattr(pdf_layout_mod, "NativePdfRenderer", _UpdateSpy)
    layout: PdfPreviewerLayout = PdfPreviewerLayout()
    try:
        renderer: _UpdateSpy = layout._renderer  # noqa: SLF001
        assert isinstance(renderer, _UpdateSpy), "预览器应使用本次注入的渲染器子类"
        before: int = renderer.update_calls
        layout._on_theme_changed("light")  # noqa: SLF001
        assert renderer.update_calls > before, (
            "主题切换后 PDF 画布未被重绘（卡片外框显隐将滞后到滚动 / 缩放）"
        )
    finally:
        layout.cleanup()
        safe_teardown(layout)
        flush_widget_queue(qapp)
