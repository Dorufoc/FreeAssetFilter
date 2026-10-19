# -*- coding: utf-8 -*-
# targets: freeassetfilter.ui.layout.preview.native_pdf_renderer
"""NativePdfRenderer 单元测试。

旧版该组件的测试随 tests/components/test_previewers.py（旧组件测试资产）
一并删除；本文件为迁移至 ``ui/layout/preview/`` 后的覆盖：

* 载入有效 PDF：页数/缩放/跳页/适应页宽接口可用；
* 载入缺失文件：不抛异常并优雅返回；
* 关闭事件（closeEvent）安全；
* 右键菜单构建与动作（复制/图片另存为/缩放组/全选）；
* 交互面：拖拽选区与剪贴板、Ctrl+滚轮缩放、普通滚轮不缩放、
  中键双击重置缩放、Ctrl 键状态跟踪、复制选中文字与全选
  （直接构造事件调用处理器，不依赖窗口系统）；
* 页面卡片外框主题口径：深色描边、浅色不描边（浅色下 G4 为近黑，
  会在预览区边缘形成黑边），像素级采样断言（固定底色宿主）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

# ui 短路径导入引导（styled 组件内部使用 ``from theme/components import ...``）
_UI_ROOT: str = str(Path(__file__).resolve().parents[5] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from theme import tm  # noqa: E402
from freeassetfilter.ui.layout.preview.native_pdf_renderer import NativePdfRenderer
from tests.support.qt_helpers import process_qt_events, wait_until

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

    def test_load_document_async_emits_finished(
        self, qapp: Any, sample_pdf_file: str
    ) -> None:
        """async：load_document_async 立即受理，完成后发 document_load_finished。"""
        renderer = NativePdfRenderer()
        received: list = []
        renderer.document_load_finished.connect(
            lambda ok, msg: received.append((ok, msg))
        )
        try:
            assert renderer.load_document_async(sample_pdf_file) is True
            assert wait_until(qapp, lambda: bool(received), timeout_ms=5000)
            assert received[0][0] is True
            assert renderer.page_count() == 1
        finally:
            renderer.close()

    def test_load_document_async_missing_returns_false(
        self, qapp: Any, tmp_path: Any
    ) -> None:
        """async：缺失路径同步返回 False，不发完成信号。"""
        renderer = NativePdfRenderer()
        received: list = []
        renderer.document_load_finished.connect(
            lambda ok, msg: received.append((ok, msg))
        )
        try:
            assert renderer.load_document_async(str(tmp_path / "missing.pdf")) is False
            qapp.processEvents()
            assert not received
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


class TestInteractionCoverage:
    """交互面覆盖：选区拖拽 / 滚轮缩放 / 键盘状态 / 中键双击 / 复制与全选。"""

    @staticmethod
    def _renderer(sample_pdf_file: str) -> NativePdfRenderer:
        renderer = NativePdfRenderer()
        renderer.resize(800, 600)
        assert renderer.load_document(sample_pdf_file) is True
        return renderer

    @staticmethod
    def _mouse_event(
        event_type: Any,
        pos: tuple,
        button: Any = Qt.LeftButton,
        buttons: Any = None,
        modifiers: Any = Qt.NoModifier,
    ) -> Any:
        if buttons is None:
            buttons = button
        local = QPointF(float(pos[0]), float(pos[1]))
        return QMouseEvent(event_type, local, local, button, buttons, modifiers)

    @staticmethod
    def _wheel_event(pos: tuple, delta_y: int, modifiers: Any) -> Any:
        local = QPointF(float(pos[0]), float(pos[1]))
        return QWheelEvent(
            local,
            local,
            QPoint(),
            QPoint(0, delta_y),
            Qt.NoButton,
            modifiers,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )

    def test_drag_selection_fills_rects_and_clipboard(
        self, qapp: Any, sample_pdf_file: str,
    ) -> None:
        """左键拖过页面文字：命中选区、填充高亮矩形、松开写入剪贴板。"""
        renderer = self._renderer(sample_pdf_file)
        try:
            words = renderer._doc.get_text_words(0)
            assert words, "样例 PDF 应包含可选文字"
            wx0, wy0, wx1, wy1 = words[0][:4]
            center_y = (wy0 + wy1) / 2.0
            begin = renderer._view.absolute_to_window_pos(wx0, center_y)
            end = renderer._view.absolute_to_window_pos(wx1, center_y)

            renderer.mousePressEvent(
                self._mouse_event(QEvent.Type.MouseButtonPress, begin)
            )
            renderer.mouseMoveEvent(
                self._mouse_event(
                    QEvent.Type.MouseMove, end,
                    button=Qt.NoButton, buttons=Qt.LeftButton,
                )
            )
            assert renderer._selected_text, "拖拽后应命中文字"
            assert renderer._view.selected_character_rects

            renderer.mouseReleaseEvent(
                self._mouse_event(QEvent.Type.MouseButtonRelease, end)
            )
            assert QApplication.clipboard().text() == renderer._selected_text
        finally:
            renderer.close()

    def test_ctrl_wheel_zooms_plain_wheel_does_not(
        self, qapp: Any, sample_pdf_file: str,
    ) -> None:
        """Ctrl+滚轮放大/缩小；普通滚轮不改缩放。"""
        renderer = self._renderer(sample_pdf_file)
        try:
            zoom0 = renderer._view.zoom_level
            renderer.wheelEvent(self._wheel_event((400, 300), 120, Qt.ControlModifier))
            zoom1 = renderer._view.zoom_level
            assert zoom1 > zoom0
            renderer.wheelEvent(self._wheel_event((400, 300), -120, Qt.ControlModifier))
            assert renderer._view.zoom_level < zoom1

            zoom_plain = renderer._view.zoom_level
            renderer.wheelEvent(self._wheel_event((400, 300), 120, Qt.NoModifier))
            assert renderer._view.zoom_level == zoom_plain
        finally:
            renderer.close()

    def test_middle_double_click_resets_zoom(self, qapp: Any, sample_pdf_file: str) -> None:
        """中键双击 → 重置为适应页宽。"""
        renderer = self._renderer(sample_pdf_file)
        try:
            fit_zoom = renderer._view.zoom_level
            renderer.wheelEvent(self._wheel_event((400, 300), 120, Qt.ControlModifier))
            assert renderer._view.zoom_level != fit_zoom
            renderer.mouseDoubleClickEvent(
                self._mouse_event(
                    QEvent.Type.MouseButtonDblClick, (400, 300), button=Qt.MiddleButton
                )
            )
            assert renderer._view.zoom_level == pytest.approx(fit_zoom, rel=1e-9)
        finally:
            renderer.close()

    def test_key_press_release_tracks_ctrl(self, qapp: Any, sample_pdf_file: str) -> None:
        """Ctrl 键按下/松开状态跟踪。"""
        renderer = self._renderer(sample_pdf_file)
        try:
            assert renderer._ctrl_pressed is False
            renderer.keyPressEvent(
                QKeyEvent(QEvent.Type.KeyPress, Qt.Key_Control, Qt.NoModifier)
            )
            assert renderer._ctrl_pressed is True
            renderer.keyReleaseEvent(
                QKeyEvent(QEvent.Type.KeyRelease, Qt.Key_Control, Qt.NoModifier)
            )
            assert renderer._ctrl_pressed is False
        finally:
            renderer.close()

    def test_copy_selected_text_and_select_all(self, qapp: Any, sample_pdf_file: str) -> None:
        """全选 → 剪贴板文本；手动复制入口与全选结果一致。"""
        renderer = self._renderer(sample_pdf_file)
        try:
            renderer._select_all()
            text = renderer._selected_text
            assert "Hello" in text
            assert renderer._view.selected_character_rects
            assert QApplication.clipboard().text() == text

            QApplication.clipboard().clear()
            renderer._copy_selected_text()
            assert QApplication.clipboard().text() == text
        finally:
            renderer.close()


class TestPageCardBorderTheme:
    """页面卡片外框主题口径：深色描边、浅色不描边（像素级采样断言）。

    浅色模式下 G4（``tm.text``）为近黑 ``#1a1a1a``：页面卡片若照画外框，
    在 fit-to-width 贴边时会沿预览区边缘形成黑边。新口径为浅色不描边、
    仅深色保留近白细线；断言基于固定底色宿主窗口上的抓图采样，不依赖
    系统 / mica 背景。
    """

    #: 固定宿主底色：浅色用例用浅底（黑边检测），深色用例用深底（白线检测）
    _BACKDROP_LIGHT = "#f0f0f0"
    _BACKDROP_DARK = "#2b2b2b"

    @staticmethod
    def _mount(qapp: Any, backdrop: str) -> tuple:
        """把渲染器挂到固定底色宿主窗口上并显示（布局激活后返回）。

        Args:
            qapp: session QApplication。
            backdrop: 宿主的固定背景色（CSS 颜色）。

        Returns:
            tuple: ``(host, renderer)``；宿主为抓图根（渲染器透明、透出底色）。
        """
        host = QWidget()
        host.setStyleSheet(f"background-color: {backdrop};")
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        renderer = NativePdfRenderer()
        host_layout.addWidget(renderer)
        host.resize(600, 400)
        host.show()
        process_qt_events(qapp, ms=0)
        return host, renderer

    @staticmethod
    def _wait_first_page(qapp: Any, renderer: NativePdfRenderer) -> None:
        """有界等待首屏页面渲染进入缓存（未渲染完成时卡片不绘制）。"""
        assert wait_until(
            qapp,
            lambda: renderer._renderer.find_cached(
                0, renderer._view.zoom_level
            ) is not None,
            timeout_ms=8000,
        ), "页面渲染未在超时内完成"

    @staticmethod
    def _card_left_x(renderer: NativePdfRenderer) -> float:
        """按 paintEvent 同口径计算页面卡片左边缘（逻辑坐标）。"""
        view = renderer._view
        zoom = view.zoom_level
        win_x = (0.0 - view.offset_x) * zoom + view.frame_center_x()
        return win_x + 6.0  # card_margin

    @staticmethod
    def _band_extremes(image: Any, x_logical: float, half: float = 3.0) -> tuple:
        """取卡片左边缘（纵向中线）±half 逻辑像素条带的最小/最大亮度。

        Args:
            image: 抓图位图（物理像素，采样按 devicePixelRatio 换算）。
            x_logical: 条带中心的逻辑 x（通常为卡片左边缘）。
            half: 条带半宽（逻辑像素）。

        Returns:
            tuple[float, float]: ``(min, max)`` 亮度（0-255）。
        """
        dpr = image.devicePixelRatio() or 1.0
        y_dev = min(image.height() - 1, max(0, image.height() // 2))
        x0 = max(0, int((x_logical - half) * dpr))
        x1 = min(image.width() - 1, int((x_logical + half) * dpr))
        values = []
        for x_dev in range(x0, x1 + 1):
            color = image.pixelColor(x_dev, y_dev)
            values.append((color.red() + color.green() + color.blue()) / 3.0)
        return min(values), max(values)

    @staticmethod
    def _restore_theme(qapp: Any, initial_dark: bool) -> None:
        """把主题恢复到用例开始时的明暗状态（避免跨用例污染）。"""
        tm.set_theme_mode("dark" if initial_dark else "light")
        process_qt_events(qapp, ms=0)

    def test_light_theme_page_card_has_no_dark_border(
        self, qapp: Any, sample_pdf_file: str,
    ) -> None:
        """浅色：卡片外沿无描边（不再出现近黑 G4 线 → 无黑边）。"""
        initial_dark = tm.is_dark_theme()
        tm.set_theme_mode("light")
        host, renderer = self._mount(qapp, self._BACKDROP_LIGHT)
        try:
            assert renderer.load_document(sample_pdf_file) is True
            self._wait_first_page(qapp, renderer)
            image = host.grab().toImage()
            card_left = self._card_left_x(renderer)
            lo, _hi = self._band_extremes(image, card_left)
            assert lo > 150, (
                f"浅色模式页面卡片边缘出现深色描边（条带最暗亮度 {lo:.0f}，"
                f"卡片左边缘 x={card_left:.1f}）"
            )
        finally:
            renderer.close()
            host.close()
            host.deleteLater()
            self._restore_theme(qapp, initial_dark)

    def test_dark_theme_page_card_keeps_light_border(
        self, qapp: Any, sample_pdf_file: str,
    ) -> None:
        """深色：卡片外沿保留近白 1.5px 描边（贴边时勾勒白页）。"""
        initial_dark = tm.is_dark_theme()
        tm.set_theme_mode("dark")
        host, renderer = self._mount(qapp, self._BACKDROP_DARK)
        try:
            assert renderer.load_document(sample_pdf_file) is True
            self._wait_first_page(qapp, renderer)
            image = host.grab().toImage()
            card_left = self._card_left_x(renderer)
            # 描边在卡片外侧仅约 0.75 逻辑像素：取外沿窄带最大亮度，
            # 覆盖高 DPI 下抗锯齿摊分（任一滴像素显著亮于底色即证明描边存在）。
            _lo, hi = self._band_extremes(image, card_left - 1.0, half=0.5)
            assert hi > 150, (
                f"深色模式页面卡片描边缺失（外沿条带最亮亮度 {hi:.0f}，"
                f"卡片左边缘 x={card_left:.1f}）"
            )
        finally:
            renderer.close()
            host.close()
            host.deleteLater()
            self._restore_theme(qapp, initial_dark)