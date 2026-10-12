# -*- coding: utf-8 -*-
# targets: freeassetfilter.ui.layout.preview.native_pdf_renderer
"""NativePdfRenderer 单元测试（任务 4 补充）。

旧版该组件的测试随 tests/components/test_previewers.py（旧组件测试资产）
一并删除；本文件为迁移至 ``ui/layout/preview/`` 后的冒烟级重覆盖：

* 载入有效 PDF：页数/缩放/跳页/适应页宽接口可用；
* 载入缺失文件：不抛异常并优雅返回；
* 关闭事件（closeEvent）安全；
* 右键菜单构建与动作（复制/图片另存为/缩放组/全选）。

完整交互面（选区/手势）的全覆盖登记在重构执行日志
任务 4 的基建债清单，待后续迭代补足。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from PySide6.QtCore import QPoint

# ui 短路径导入引导（styled 组件内部使用 ``from theme/components import ...``）
_UI_ROOT: str = str(Path(__file__).resolve().parents[5] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from freeassetfilter.ui.layout.preview.native_pdf_renderer import NativePdfRenderer

pytestmark = pytest.mark.unit


class TestNativePdfRendererSmoke:
    """载入与基础导航接口的冒烟覆盖。"""

    def test_load_valid_pdf(self, qapp: Any, sample_pdf_file: str) -> None:
        renderer = NativePdfRenderer()
        try:
            ok = renderer.load_document(sample_pdf_file)
            assert ok is True
            assert renderer.page_count() == 1
        finally:
            renderer.close()

    def test_load_missing_file_graceful(self, qapp: Any, tmp_path: Any) -> None:
        renderer = NativePdfRenderer()
        try:
            ok = renderer.load_document(str(tmp_path / "missing.pdf"))
            assert ok is False
        finally:
            renderer.close()

    def test_navigation_after_load(self, qapp: Any, sample_pdf_file: str) -> None:
        renderer = NativePdfRenderer()
        try:
            assert renderer.load_document(sample_pdf_file) is True
            renderer.go_to_page(1)
            renderer.set_zoom(1.5)
            renderer.fit_to_page()
        finally:
            renderer.close()

    def test_zoom_group_methods_smoke(self, qapp: Any, sample_pdf_file: str) -> None:
        """放大/缩小/适应整页接口可用且不抛异常。"""
        renderer = NativePdfRenderer()
        try:
            assert renderer.load_document(sample_pdf_file) is True
            renderer.zoom_in()
            zoom_after_in = renderer._view.zoom_level
            renderer.zoom_out()
            assert zoom_after_in > renderer._view.zoom_level
            renderer.fit_to_page_bounds()
            assert renderer._view.zoom_level > 0
        finally:
            renderer.close()


class TestContextMenu:
    """右键菜单：条目随命中状态出现 + 动作路由 + 图片另存为。"""

    @staticmethod
    def _labels(menu: Any) -> list:
        """菜单非分隔线条目的文案列表。"""
        return [a.text() for a in menu.actions() if not a.isSeparator()]

    @staticmethod
    def _renderer(sample_pdf_file: str) -> NativePdfRenderer:
        renderer = NativePdfRenderer()
        assert renderer.load_document(sample_pdf_file) is True
        return renderer

    def test_menu_without_selection_or_image(
        self, qapp: Any, sample_pdf_file: str,
    ) -> None:
        """无选区/无图片：只有缩放组与全选。"""
        renderer = self._renderer(sample_pdf_file)
        try:
            renderer._view.selected_character_rects = []
            renderer._find_image_at = lambda pos: None  # type: ignore[method-assign]
            labels = self._labels(renderer._build_context_menu(QPoint(0, 0)))
            assert "复制选中文字" not in labels
            assert "复制图片" not in labels
            assert "图片另存为…" not in labels
            for expected in ("放大", "缩小", "适应页宽", "适应整页", "全选"):
                assert expected in labels
        finally:
            renderer.close()

    def test_menu_shows_selection_and_image_actions(
        self, qapp: Any, sample_pdf_file: str,
    ) -> None:
        """有选区/右键命中图片：复制与另存为条目出现。"""
        renderer = self._renderer(sample_pdf_file)
        try:
            renderer._view.selected_character_rects = [object()]
            fake_img = {"image": b"png-bytes", "ext": "png", "bbox": (0, 0, 1, 1)}
            renderer._find_image_at = lambda pos: fake_img  # type: ignore[method-assign]
            labels = self._labels(renderer._build_context_menu(QPoint(0, 0)))
            assert "复制选中文字" in labels
            assert "复制图片" in labels
            assert "图片另存为…" in labels
        finally:
            renderer.close()

    def test_zoom_actions_route_to_renderer_methods(
        self, qapp: Any, sample_pdf_file: str,
    ) -> None:
        """缩放组条目触发对应渲染器方法。"""
        renderer = self._renderer(sample_pdf_file)
        try:
            calls: list = []
            renderer.zoom_in = lambda: calls.append("in")  # type: ignore[method-assign]
            renderer.zoom_out = lambda: calls.append("out")  # type: ignore[method-assign]
            renderer.fit_to_page = lambda: calls.append("fit-width")  # type: ignore[method-assign]
            renderer.fit_to_page_bounds = lambda: calls.append("fit-page")  # type: ignore[method-assign]
            menu = renderer._build_context_menu(QPoint(0, 0))
            by_text = {a.text(): a for a in menu.actions()}
            by_text["放大"].trigger()
            by_text["缩小"].trigger()
            by_text["适应页宽"].trigger()
            by_text["适应整页"].trigger()
            assert calls == ["in", "out", "fit-width", "fit-page"]
        finally:
            renderer.close()

    def test_save_image_writes_bytes(
        self, qapp: Any, sample_pdf_file: str, tmp_path: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """图片另存为：对话框返回路径后按原始字节写盘。"""
        import freeassetfilter.ui.layout.preview.native_pdf_renderer as npr_mod

        renderer = self._renderer(sample_pdf_file)
        out_path = tmp_path / "img.png"
        monkeypatch.setattr(
            npr_mod.QFileDialog,
            "getSaveFileName",
            staticmethod(lambda *a, **k: (str(out_path), "")),
        )
        try:
            renderer._save_image({"image": b"saved-bytes", "ext": "png"})
            assert out_path.is_file()
            assert out_path.read_bytes() == b"saved-bytes"
        finally:
            renderer.close()

    def test_save_image_cancel_writes_nothing(
        self, qapp: Any, sample_pdf_file: str, tmp_path: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """图片另存为：对话框取消（空路径）不写任何文件。"""
        import freeassetfilter.ui.layout.preview.native_pdf_renderer as npr_mod

        renderer = self._renderer(sample_pdf_file)
        monkeypatch.setattr(
            npr_mod.QFileDialog,
            "getSaveFileName",
            staticmethod(lambda *a, **k: ("", "")),
        )
        before = {p.name for p in tmp_path.iterdir()}
        try:
            renderer._save_image({"image": b"x", "ext": "png"})
            assert {p.name for p in tmp_path.iterdir()} == before
        finally:
            renderer.close()