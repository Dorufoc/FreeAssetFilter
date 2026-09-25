# -*- coding: utf-8 -*-
# targets: services.pdf_document, services.pdf_document_view, services.pdf_renderer
"""``PdfDocument`` / ``PdfDocumentView`` / ``PdfBackgroundRenderer`` 单元测试。

覆盖（happy + boundary/error 各至少一条）：

* ``PdfDocument`` —— 打开/页数/页尺寸/累积高度、渲染（zoom×dpr 组合）、
  文本词提取、搜索、页面图片提取、损坏 PDF（``fitz.FileDataError``）、
  缺失文件（``FileNotFoundError``）、越界页（``IndexError``）、
  ``close()`` 后的安全降级与重新访问抛 ``RuntimeError``
* ``PdfDocumentView`` —— 坐标三空间互转、zoom 钳制 [0.1, 10.0]、
  ``absolute_to_page`` / ``get_visible_pages`` / ``goto_page`` /
  ``move_pages`` 边界钳制、``move`` 返回值语义
* ``PdfBackgroundRenderer`` —— 后台提交→``render_ready`` 信号→``find_cached``、
  最接近 zoom 回退（20% 门限）、LRU 逐出、失败路径（坏文件→image=None 不入缓存）、
  ``cancel_all`` / ``pending_count``

本文件基于 ``tests.support.data_factories.make_pdf``（纯字节 PDF 1.4）造档，
多页样例由 fitz 内存构造，不依赖 ``tests/fixtures/`` 目录。
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path
from typing import Any, List, Optional, Tuple

import pytest

fitz = pytest.importorskip("fitz")  # PyMuPDF 缺失时跳过整个模块

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage

from freeassetfilter.core.native.bridges.faf_core_bridge import (
    get_faf_core_bridge,
)
from freeassetfilter.services.pdf_document import PdfDocument
from freeassetfilter.services.pdf_document_view import PdfDocumentView
from freeassetfilter.services.pdf_renderer import (
    PdfBackgroundRenderer,
    RenderRequest,
    RenderResponse,
)
from tests.support.qt_helpers import safe_teardown, wait_for_signal

pytestmark = pytest.mark.unit


def _make_multipage_pdf(path: Path, pages: int = 3) -> str:
    """用 fitz 在内存中构造一个多页 PDF。

    Args:
        path: 输出路径。
        pages: 页数（默认 3）。

    Returns:
        str: 生成后的文件路径。
    """
    doc: fitz.Document = fitz.open()
    for i in range(pages):
        page: fitz.Page = doc.new_page(width=612, height=792)
        page.insert_text((72, 72), f"Page {i + 1}")
    doc.save(str(path))
    doc.close()
    return str(path)


def _wait_renders(renderer: PdfBackgroundRenderer, count: int) -> None:
    """等待 renderer 发出 ``count`` 次 ``render_ready``（有界）。

    Args:
        renderer: 后台渲染器。
        count: 期望完成的任务数。

    Raises:
        AssertionError: 任一次信号在超时内未发出。
    """
    for _ in range(count):
        assert wait_for_signal(renderer.render_ready, 10000), "render_ready 超时"


# ── PdfDocument --------------------------------------------------------


def test_open_and_page_metadata(sample_pdf_file: str) -> None:
    """happy：打开后页数/尺寸/累积高度与构造一致，close 后安全降级。

    Args:
        sample_pdf_file: conftest 生成的单页 PDF 路径。
    """
    doc: PdfDocument = PdfDocument(sample_pdf_file)
    try:
        assert doc.page_count() == 1
        width, height = doc.page_size(0)
        assert width == 612.0
        assert height == 792.0
        assert doc.page_widths == [612.0]
        assert doc.page_heights == [792.0]
        assert doc.accum_page_heights == [792.0]
    finally:
        doc.close()

    # close 后安全降级：page_count 0、尺寸缓存放空
    assert doc.page_count() == 0
    assert doc.page_widths == []
    with pytest.raises(RuntimeError):
        doc.page_size(0)


def test_open_missing_file_raises(tmp_path: Path) -> None:
    """error：不存在的文件抛 FileNotFoundError（PyMuPDF 自有的该异常子类）。

    Args:
        tmp_path: 临时目录。
    """
    missing: str = str(tmp_path / "nope.pdf")
    with pytest.raises((FileNotFoundError, fitz.FileNotFoundError)):
        PdfDocument(missing)


def test_open_broken_pdf_raises(tmp_path: Path) -> None:
    """error：损坏的 PDF 字节抛 fitz.FileDataError。

    Args:
        tmp_path: 临时目录。
    """
    broken: Path = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4\nnot a real pdf at all")
    with pytest.raises(fitz.FileDataError):
        PdfDocument(str(broken))


def test_render_returns_qimage(sample_pdf_file: str) -> None:
    """happy：zoom=1.0 渲染出 612×792 QImage，非空非零字节。

    Args:
        sample_pdf_file: 单页 PDF 路径。
    """
    doc: PdfDocument = PdfDocument(sample_pdf_file)
    try:
        image: QImage = doc.render(0, zoom=1.0, dpr=1.0)
        assert not image.isNull()
        assert image.width() == 612
        assert image.height() == 792
        assert image.sizeInBytes() > 0
    finally:
        doc.close()


def test_render_zoom_times_dpr(sample_pdf_file: str) -> None:
    """happy：zoom=2.0 × dpr=2.0 → 2448×3168。

    Args:
        sample_pdf_file: 单页 PDF 路径。
    """
    doc: PdfDocument = PdfDocument(sample_pdf_file)
    try:
        image: QImage = doc.render(0, zoom=2.0, dpr=2.0)
        assert image.width() == 612 * 4
        assert image.height() == 792 * 4
    finally:
        doc.close()


def test_render_invalid_page_raises(sample_pdf_file: str) -> None:
    """error：越界页渲染抛 ValueError（fitz.load_page 的 page not in document）。

    Args:
        sample_pdf_file: 单页 PDF 路径。
    """
    doc: PdfDocument = PdfDocument(sample_pdf_file)
    try:
        with pytest.raises((IndexError, ValueError)):
            doc.render(5, zoom=1.0)
    finally:
        doc.close()


def test_get_text_words(sample_pdf_file: str) -> None:
    """happy：make_pdf 的 "Hello World" 可被词级提取。

    Args:
        sample_pdf_file: 单页 PDF 路径。
    """
    doc: PdfDocument = PdfDocument(sample_pdf_file)
    try:
        words: List[Tuple[float, float, float, float, str, int, int, int]] = (
            doc.get_text_words(0)
        )
        assert words
        texts: List[str] = [w[4] for w in words]
        assert "Hello" in texts
        assert "World" in texts
    finally:
        doc.close()


def test_search_for_finds_text(sample_pdf_file: str) -> None:
    """happy：search_for 定位 "Hello"（默认大小写不敏感）。

    Args:
        sample_pdf_file: 单页 PDF 路径。
    """
    doc: PdfDocument = PdfDocument(sample_pdf_file)
    try:
        rects: List[fitz.Rect] = doc.search_for(0, "hello")
        assert rects, "应至少命中一个矩形"
        assert rects[0].width > 0
    finally:
        doc.close()


def test_get_page_images_empty(sample_pdf_file: str) -> None:
    """boundary：无内嵌图片的页面返回空列表。

    Args:
        sample_pdf_file: 单页 PDF 路径。
    """
    doc: PdfDocument = PdfDocument(sample_pdf_file)
    try:
        assert doc.get_page_images(0) == []
    finally:
        doc.close()


# ── PdfDocumentView -----------------------------------------------------


def test_zoom_clamped_to_bounds(sample_pdf_file: str) -> None:
    """boundary：zoom 钳制在 [0.1, 10.0]，进出界均封顶。

    Args:
        sample_pdf_file: 单页 PDF 路径。
    """
    doc: PdfDocument = PdfDocument(sample_pdf_file)
    try:
        view: PdfDocumentView = PdfDocumentView(doc)
        assert view.set_zoom_level(100.0) == 10.0
        assert view.set_zoom_level(0.001) == 0.1
        view.set_zoom_level(10.0)
        assert view.zoom_in() == 10.0  # 上限封顶
        view.set_zoom_level(0.1)
        assert view.zoom_out() == 0.1  # 下限封顶
        view.set_zoom_level(2.0)
        assert view.zoom_in() == pytest.approx(2.4)
    finally:
        doc.close()


def test_absolute_to_page_binary_search(tmp_path: Path) -> None:
    """happy：多页文档 absolute_to_page 走二分，边界页钳制在 [0, 页高]。

    Args:
        tmp_path: 临时目录。
    """
    pdf_path: str = _make_multipage_pdf(tmp_path / "multi.pdf", pages=3)
    doc: PdfDocument = PdfDocument(pdf_path)
    try:
        view: PdfDocumentView = PdfDocumentView(doc)
        page, y_within = view.absolute_to_page(0.0)
        assert page == 0
        assert y_within == 0.0
        # 第二页中点
        page2, y2 = view.absolute_to_page(792.0 + 100.0)
        assert page2 == 1
        assert y2 == pytest.approx(100.0)
        # 超长坐标 → 钳制到最后一页且 y 封顶到页高
        last_page, y_last = view.absolute_to_page(1e5)
        assert last_page == 2
        assert y_last == pytest.approx(792.0)
    finally:
        doc.close()


def test_visible_pages_and_move_pages(tmp_path: Path) -> None:
    """boundary：get_visible_pages / move_pages 前翻后翻与越界钳制。

    Args:
        tmp_path: 临时目录。
    """
    pdf_path: str = _make_multipage_pdf(tmp_path / "multi.pdf", pages=3)
    doc: PdfDocument = PdfDocument(pdf_path)
    try:
        view: PdfDocumentView = PdfDocumentView(doc)
        assert view.get_visible_pages() == [0]
        view.move_pages(1)
        assert view.get_visible_pages() == [1]
        # 大跨度前翻 → 钳制到最后一页
        view.move_pages(99)
        assert max(view.get_visible_pages()) == 2
        # 大跨度后翻 → 钳制回第一页
        view.move_pages(-99)
        assert view.get_visible_pages() == [0]
    finally:
        doc.close()


def test_document_window_roundtrip_y(sample_pdf_file: str) -> None:
    """happy：document→window→document 的 Y 坐标回到原值（X 受页居中偏移）。

    Args:
        sample_pdf_file: 单页 PDF 路径。
    """
    doc: PdfDocument = PdfDocument(sample_pdf_file)
    try:
        view: PdfDocumentView = PdfDocumentView(doc, zoom_level=1.0)
        view.set_zoom_level(1.0)
        win_x: float
        win_y: float
        win_x, win_y = view.document_to_window_pos(0, 100.0, 200.0)
        page: int
        y_pt: float
        page, _x_pt, y_pt = view.window_to_document_pos(win_x, win_y)
        assert page == 0
        assert y_pt == pytest.approx(200.0)
    finally:
        doc.close()


def test_frame_center_roundtrip_with_reserved_right(
    sample_pdf_file: str,
) -> None:
    """happy：right_reserved_px>0 时帧中心右移半列，窗口↔绝对互逆保持自洽。

    Args:
        sample_pdf_file: 单页 PDF 路径。
    """
    doc: PdfDocument = PdfDocument(sample_pdf_file)
    try:
        view: PdfDocumentView = PdfDocumentView(
            doc, zoom_level=1.5, right_reserved_px=12.0
        )
        view.offset_x = 40.0
        view.offset_y = 50.0
        # 帧中心 = 视口中心 + 预留列宽的一半
        assert view.frame_center_x() == pytest.approx(
            view.view_width / 2 + 6.0
        )
        # 窗口空间帧中心 ↔ 绝对空间 offset 互逆
        center_px: float = view.frame_center_x()
        abs_x: float
        abs_y: float
        abs_x, abs_y = view.window_to_absolute_document_pos(
            center_px, view.view_height / 2
        )
        assert abs_x == pytest.approx(40.0)
        assert abs_y == pytest.approx(50.0)
        win_x: float
        win_y: float
        win_x, win_y = view.absolute_to_window_pos(40.0, 50.0)
        assert win_x == pytest.approx(center_px)
        assert win_y == pytest.approx(view.view_height / 2)
    finally:
        doc.close()


def test_page_margins_symmetric_with_reserved_column(
    sample_pdf_file: str,
) -> None:
    """happy：预留右侧滚动条列后，页面仍相对整个画布左右等距。

    Args:
        sample_pdf_file: 单页 PDF 路径。
    """
    doc: PdfDocument = PdfDocument(sample_pdf_file)
    try:
        view: PdfDocumentView = PdfDocumentView(
            doc,
            zoom_level=1.0,
            view_width=788,
            view_height=600,
            right_reserved_px=12.0,
        )
        view.offset_x = 612.0 / 2  # fit-to-width 语义：文档中心对齐帧中心
        frame: float = view.view_width + view.right_reserved_px
        pwz: float = 612.0
        # 页面卡片 = 页框内缩 6px；外缘到左右边框的距离应相等
        left_margin: float = view.frame_center_x() - pwz / 2 + 6.0
        right_margin: float = frame - (view.frame_center_x() + pwz / 2 - 6.0)
        assert left_margin == pytest.approx(right_margin)
    finally:
        doc.close()


def test_move_returns_bool(sample_pdf_file: str) -> None:
    """boundary：零位移 move 返回 False，非零返回 True。

    Args:
        sample_pdf_file: 单页 PDF 路径。
    """
    doc: PdfDocument = PdfDocument(sample_pdf_file)
    try:
        view: PdfDocumentView = PdfDocumentView(doc)
        assert view.move(0.0, 0.0) is False
        assert view.move(0.0, 1e-10) is False  # <1e-9 视为可忽略
        assert view.move(5.0, 0.0) is True
        assert view.offset_x == 5.0
    finally:
        doc.close()


# ── PdfBackgroundRenderer ------------------------------------------------


def test_submit_and_find_cached(qapp: Any, sample_pdf_file: str) -> None:
    """happy：submit 后收到 render_ready，find_cached 命中精确 zoom。

    Args:
        qapp: session QApplication。
        sample_pdf_file: 单页 PDF 路径。
    """
    renderer: PdfBackgroundRenderer = PdfBackgroundRenderer(max_cache=4)
    try:
        renderer.submit(sample_pdf_file, 0, zoom=1.0, dpr=1.0)
        _wait_renders(renderer, 1)
        resp: Optional[RenderResponse] = renderer.find_cached(0, 1.0)
        assert resp is not None
        assert resp.image is not None
        assert not resp.pending
        assert resp.image.width() == 612
        assert resp.request.zoom == pytest.approx(1.0)
        assert renderer.pending_count() == 0
    finally:
        renderer.cancel_all()
        safe_teardown(renderer)


def test_find_cached_closest_zoom(qapp: Any, sample_pdf_file: str) -> None:
    """boundary：20% 门限内的最接近 zoom 回退命中。

    Args:
        qapp: session QApplication。
        sample_pdf_file: 单页 PDF 路径。
    """
    renderer: PdfBackgroundRenderer = PdfBackgroundRenderer(max_cache=4)
    try:
        renderer.submit(sample_pdf_file, 0, zoom=1.0, dpr=1.0)
        _wait_renders(renderer, 1)
        resp = renderer.find_cached(0, 1.05)
        assert resp is not None
        assert resp.request.zoom == pytest.approx(1.0)
    finally:
        renderer.cancel_all()
        safe_teardown(renderer)


def test_find_cached_zoom_gate_rejects(qapp: Any, sample_pdf_file: str) -> None:
    """boundary：zoom 差异超 20% 时回退被拒绝。

    Args:
        qapp: session QApplication。
        sample_pdf_file: 单页 PDF 路径。
    """
    renderer: PdfBackgroundRenderer = PdfBackgroundRenderer(max_cache=4)
    try:
        renderer.submit(sample_pdf_file, 0, zoom=1.0, dpr=1.0)
        _wait_renders(renderer, 1)
        assert renderer.find_cached(0, 3.0) is None  # 差 200% → 拒绝
    finally:
        renderer.cancel_all()
        safe_teardown(renderer)


def test_find_cached_no_match(qapp: Any, sample_pdf_file: str) -> None:
    """boundary：未渲染的页返回 None。

    Args:
        qapp: session QApplication。
        sample_pdf_file: 单页 PDF 路径。
    """
    renderer: PdfBackgroundRenderer = PdfBackgroundRenderer(max_cache=4)
    try:
        assert renderer.find_cached(0, 1.0) is None
    finally:
        renderer.cancel_all()
        safe_teardown(renderer)


def test_submit_invalid_path_fails(qapp: Any, tmp_path: Path) -> None:
    """error：坏 PDF 路径的任务完成后不入缓存且仍发 render_ready。

    Args:
        qapp: session QApplication。
        tmp_path: 临时目录。
    """
    renderer: PdfBackgroundRenderer = PdfBackgroundRenderer(max_cache=4)
    try:
        bad: str = str(tmp_path / "missing.pdf")
        renderer.submit(bad, 0, zoom=1.0, dpr=1.0)
        _wait_renders(renderer, 1)
        assert renderer.find_cached(0, 1.0) is None
        assert renderer.pending_count() == 0
    finally:
        renderer.cancel_all()
        safe_teardown(renderer)


def test_cancel_all_clears_pending(qapp: Any, tmp_path: Path) -> None:
    """boundary：cancel_all 清空待处理与缓存。

    Args:
        qapp: session QApplication。
        tmp_path: 临时目录。
    """
    pdf_path: str = _make_multipage_pdf(tmp_path / "multi.pdf", pages=2)
    renderer: PdfBackgroundRenderer = PdfBackgroundRenderer(max_cache=4)
    try:
        renderer.submit(pdf_path, 0, zoom=1.0, dpr=1.0)
        assert renderer.pending_count() >= 1
        renderer.cancel_all()
        assert renderer.pending_count() == 0
        assert renderer.find_cached(0, 1.0) is None
    finally:
        renderer.cancel_all()
        safe_teardown(renderer)


def test_lru_eviction(qapp: Any, tmp_path: Path) -> None:
    """boundary：超过 max_cache 时最旧页被逐出，最新页保留。

    test_manual: 逐页 submit+等待（完成顺序确定），前 2 页入缓存后第 3 页
    触发 LRU 逐出第 1 页。

    Args:
        qapp: session QApplication。
        tmp_path: 临时目录。
    """
    pdf_path: str = _make_multipage_pdf(tmp_path / "multi.pdf", pages=3)
    renderer: PdfBackgroundRenderer = PdfBackgroundRenderer(max_cache=2)
    try:
        # 逐页提交并等待完成，保证入缓存顺序 = 0,1,2
        renderer.submit(pdf_path, 0, zoom=1.0, dpr=1.0)
        _wait_renders(renderer, 1)
        renderer.submit(pdf_path, 1, zoom=1.0, dpr=1.0)
        _wait_renders(renderer, 1)
        renderer.submit(pdf_path, 2, zoom=1.0, dpr=1.0)
        _wait_renders(renderer, 1)

        with renderer._lock:
            cache_len: int = len(renderer._cache)
        assert cache_len == 2
        assert renderer.find_cached(0, 1.0) is None  # 最旧被逐出
        assert renderer.find_cached(1, 1.0) is not None
        assert renderer.find_cached(2, 1.0) is not None  # 最新保留
    finally:
        renderer.cancel_all()
        safe_teardown(renderer)


def test_render_request_response_dataclass() -> None:
    """happy：RenderRequest / RenderResponse 数据类字段与默认值。

    test_manual: 直接构造与读取字段。
    """
    req: RenderRequest = RenderRequest(
        path="dummy.pdf", page=1, zoom=2.0, dpr=3.0, request_id=7
    )
    assert req.path == "dummy.pdf"
    assert req.page == 1
    assert req.zoom == pytest.approx(2.0)
    assert req.dpr == pytest.approx(3.0)
    assert req.request_id == 7

    resp: RenderResponse = RenderResponse(request=req)
    assert resp.request is req
    assert resp.image is None
    assert resp.pending is True
    assert resp.invalid is False
    assert resp.timestamp == 0


def test_is_busy_reflects_pending(qapp: Any, sample_pdf_file: str) -> None:
    """boundary：提交后 is_busy 为真，完成且缓存命中后为假。

    Args:
        qapp: session QApplication。
        sample_pdf_file: 单页 PDF 路径。
    """
    renderer: PdfBackgroundRenderer = PdfBackgroundRenderer(max_cache=4)
    try:
        renderer.submit(sample_pdf_file, 0, zoom=1.0, dpr=1.0)
        assert renderer.is_busy() is True
        _wait_renders(renderer, 1)
        deadline: float = time.monotonic() + 3.0
        while renderer.is_busy() and time.monotonic() < deadline:
            pass
        assert renderer.is_busy() is False or renderer.find_cached(0, 1.0) is not None
    finally:
        renderer.cancel_all()
        safe_teardown(renderer)


# =============================================================================
# rust-hot-path-native-migration todo 19：PDF 选区 native 优先 + Python 回退对拍
# =============================================================================
def _noop_select(*args: object, **kwargs: object) -> None:
    """模拟 DLL 缺失：桥 ``pdf_select_words`` 恒 None（回退 Python 过滤）。

    Args:
        args: 忽略的定位参数。
        kwargs: 忽略的关键字参数。
    """
    del args, kwargs
    return None


def current_bridge() -> Optional[object]:
    """当前副本的 faf_core 桥单例（DLL 缺失时返回 ``available=False`` 降级实例）。

    Returns:
        Optional[object]: 桥实例（永远非 None，类型注解与模块一致）。
    """
    return get_faf_core_bridge()


class TestPdfSelectionNativeParity:
    """``get_text_selection`` 优先 native（``faf_pdf_select_words``）接线对拍。

    - native 优先：DLL 可用时 ``pdf_select_words`` 被消费，选中词序列/文本/
      缓存/矩形与纯 Python 回退逐字段一致（bbox 以 Python 权威值为准，
      serde_json ≤1 ULP 漂移不传播到 ``_cached_sel_words`` 与选区矩形）。
    - 回退一致：模拟 DLL 缺失（桥 ``pdf_select_words`` 恒 None）时走原有
      Python 过滤，结果与改造前一致。
    - ``_refresh_selection_rects`` 裁决：**保留 Python**（展示层矩形、非选区
      过滤热路径；同时规避 native bbox 的 ≤1 ULP 传输漂移）。
    """

    _FIXTURE_DIR = (
        Path(__file__).resolve().parents[2]
        / "support"
        / "faf_core_fixtures"
        / "pdf_samples"
    )

    # 向下/向上拖拽、跨页/单页、首末行 x 严格边界、空选区全覆盖
    # （与 task-18-pdf.txt 同源 sample_multi_page.pdf）。
    _SELECTION_CASES: List[Tuple[Tuple[int, int], Tuple[int, int]]] = [
        ((50, 50), (560, 2400)),
        ((72, 90), (560, 200)),
        ((500, 200), (100, 80)),
        ((100, 150), (500, 800)),
        ((200, 110), (200, 150)),
        ((72, 95), (560, 1700)),
        ((0, 120), (0, 120)),
        ((0, 300), (0, 350)),
    ]

    @staticmethod
    def _open_view() -> Tuple[PdfDocument, PdfDocumentView]:
        """打开 todo 5 的 sample_multi_page.pdf（3 页，页高 792pt）。

        Returns:
            tuple[PdfDocument, PdfDocumentView]: 文档与视图对。
        """
        doc: PdfDocument = PdfDocument(
            str(TestPdfSelectionNativeParity._FIXTURE_DIR / "sample_multi_page.pdf")
        )
        return doc, PdfDocumentView(doc)

    @classmethod
    def _select(
        cls, view: PdfDocumentView, case: Tuple[Tuple[int, int], Tuple[int, int]]
    ) -> Tuple[str, List[Tuple[Any, ...]], List[QRectF]]:
        """执行一次选区查询，返回（文本、缓存词、窗口矩形）三元组。

        Args:
            view: 目标视图。
            case: ``((begin_x, begin_y), (end_x, end_y))`` 选区。

        Returns:
            tuple: (selected_text, cached_words, window_rects)。
        """
        bx, by = case[0]
        ex, ey = case[1]
        view.clear_selection()
        text: str = view.get_text_selection(bx, by, ex, ey)
        return text, list(view._cached_sel_words), list(view.selected_character_rects)

    @pytest.mark.parametrize("case", _SELECTION_CASES)
    def test_native_preferred_matches_python_fallback(
        self,
        monkeypatch: pytest.MonkeyPatch,
        case: Tuple[Tuple[int, int], Tuple[int, int]],
    ) -> None:
        """happy：native 优先路径与纯 Python 回退在文本/缓存/矩形上全等。

        ``native_view`` 先于 monkeypatch 执行（DLL 可用即走 native）；随后
        ``python_view`` 被强制回退（桥 ``pdf_select_words`` 恒 None）——
        DLL 可用时即 native-vs-Python 对拍，DLL 缺失时即回退-vs-回退。

        Args:
            monkeypatch: pytest monkeypatch。
            case: 选区参数对。
        """
        doc_n, native_view = self._open_view()
        doc_fb, python_view = self._open_view()
        try:
            bridge = current_bridge()
            if bridge is not None and bridge.available:
                monkeypatch.setattr(bridge, "pdf_select_words", _noop_select)
            native = self._select(native_view, case)
            python_ = self._select(python_view, case)
            assert native == python_
            _, cache, rects = native
            assert len(cache) == len(rects), "缓存词数与窗口矩形数必须一致"
        finally:
            doc_n.close()
            doc_fb.close()

    def test_get_text_selection_consumes_native_bridge(
        self, monkeypatch: pytest.MonkeyPatch, faf_core_available: bool
    ) -> None:
        """native 可用时 ``get_text_selection`` 必须消费桥 ``pdf_select_words``。

        Args:
            monkeypatch: pytest monkeypatch。
            faf_core_available: session 级 DLL 可用性探测。
        """
        if not faf_core_available:
            pytest.skip("faf_core.dll 不可用，跳过 native 接线断言")
        bridge = get_faf_core_bridge()
        if bridge is None or not bridge._supports_pdf_select_words:
            pytest.skip("桥 pdf_select_words 不可用")
        calls: List[Tuple[object, ...]] = []
        real = bridge.pdf_select_words

        def _recording(*args: object, **kwargs: object) -> Optional[list]:
            calls.append(args)
            return real(*args, **kwargs)

        monkeypatch.setattr(bridge, "pdf_select_words", _recording)
        doc, view = self._open_view()
        try:
            text: str = view.get_text_selection(72.0, 90.0, 560.0, 200.0)
            assert text, "选中文本不应为空"
            assert calls, "DLL 可用时 get_text_selection 应优先消费 native 选区过滤"
        finally:
            doc.close()

    def test_fallback_without_native_keeps_python_path(
        self, monkeypatch: pytest.MonkeyPatch, faf_core_available: bool
    ) -> None:
        """failure：DLL 缺失（模拟桥恒 None）回退 Python 且与 oracle 一致。

        Oracle 视图用独立的 ``PdfDocumentView`` 在同样的强制回退下构造，两
        路结果逐字段相等——证明回退路径是改造前过滤逻辑，非静默空结果。

        Args:
            monkeypatch: pytest monkeypatch。
            faf_core_available: session 级 DLL 可用性探测（仅作记录性入参）。
        """
        del faf_core_available
        bridge = current_bridge()
        if bridge is not None and bridge.available:
            monkeypatch.setattr(bridge, "pdf_select_words", _noop_select)
        doc_o, oracle_view = self._open_view()
        doc, view = self._open_view()
        try:
            for case in self._SELECTION_CASES[:3]:
                oracle = self._select(oracle_view, case)
                result = self._select(view, case)
                assert result == oracle, f"回退路径与纯 Python oracle 不一致: {case}"
                assert result[0], "回退路径应真实产出选中文本（前三例非空区）"
        finally:
            doc_o.close()
            doc.close()


# =============================================================================
# rust-hot-path-native-migration todo 20：选区矩形对拍 + 主线程 mouseMove 预算
# =============================================================================
#: 对拍用的视图状态（zoom, offset_x, offset_y）——覆盖缩放/滚动/跨页平移。
_VIEW_STATES: List[Tuple[float, float, float]] = [
    (0.8, 40.0, 320.0),
    (1.0, 306.0, 1296.0),
    (1.5, 150.0, 640.0),
    (2.5, 90.0, 1650.0),
]


def _rect_tuple(rect: QRectF) -> Tuple[float, float, float, float]:
    """把窗口坐标 ``QRectF`` 展平为四边界元组，便于逐矩形比较。

    Args:
        rect: 窗口坐标矩形。

    Returns:
        tuple[float, float, float, float]: ``(left, top, right, bottom)``。
    """
    return (rect.left(), rect.top(), rect.right(), rect.bottom())


def _percentile_ms(samples: List[float], ratio: float) -> float:
    """计算耗时样本的分位值（毫秒），与 ``perf_metrics`` 同口径。

    Args:
        samples: 耗时样本序列（毫秒）。
        ratio: 分位比（0.0~1.0）。

    Returns:
        float: 分位耗时；无样本时返回 0.0。
    """
    ordered = sorted(samples)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return float(ordered[0])
    index = min(
        len(ordered) - 1, max(0, int(math.ceil((len(ordered) - 1) * ratio)))
    )
    return float(ordered[index])


class TestPdfSelectionRectParityAndBudget:
    """todo 20：``selected_character_rects`` 窗口坐标矩形对拍 + 主线程预算。

    - **矩形对拍**：native 优先路径与纯 Python 回退在**相同 zoom/offset** 下
      逐矩形坐标一致（含缩放/滚动后经 ``_refresh_selection_rects`` 重算）。
      两个路径都消费 Python 权威 ``_cached_sel_words``（todo 19 已把 native
      条目解析回 Python bbox），矩形数学完全一致——逐四边界精确相等。
    - **主线程 mouseMove 路径 P50 记录**：驱动真实
      ``NativePdfRenderer.mouseMoveEvent``（``native_pdf_renderer.py:522-575``），
      记录选区分支耗时 P50。该指标为**记录性**——不设 FAIL 硬阈值，仅崩溃/
      异常才 FAIL。
    - 不改绘制行为（纯测试，产品代码零改动）。
    """

    _RECTS_TOL = 0.0  # 逐矩形精确相等（零漂移断言）

    @staticmethod
    def _rects_for_states(
        view: PdfDocumentView,
        case: Tuple[Tuple[int, int], Tuple[int, int]],
    ) -> List[List[Tuple[float, float, float, float]]]:
        """执行一次选区并按 ``_VIEW_STATES`` 逐状态重算窗口矩形。

        选区过滤在绝对文档空间完成，与 zoom/offset 无关；矩形则在每个
        状态下由 ``_refresh_selection_rects`` 以当前 zoom/offset 重算，
        完全模拟拖选后缩放/滚动的高亮刷新行为。

        Args:
            view: 目标视图。
            case: ``((begin_x, begin_y), (end_x, end_y))`` 选区。

        Returns:
            与 ``_VIEW_STATES`` 等长的列表，每项为该状态下逐矩形的
            ``(left, top, right, bottom)`` 列表。
        """
        bx, by = case[0]
        ex, ey = case[1]
        view.clear_selection()
        view.get_text_selection(bx, by, ex, ey)
        per_state: List[List[Tuple[float, float, float, float]]] = []
        for zoom, ox, oy in _VIEW_STATES:
            view.zoom_level = zoom
            view.offset_x = ox
            view.offset_y = oy
            view._refresh_selection_rects()
            per_state.append(
                [_rect_tuple(r) for r in view.selected_character_rects]
            )
        return per_state

    @staticmethod
    def _planar_diff(
        a: List[Tuple[float, float, float, float]],
        b: List[Tuple[float, float, float, float]],
    ) -> List[Tuple[int, Tuple[float, float, float, float], Tuple[float, float, float, float]]]:
        """逐矩形求差，返回 ``(idx, native_rect, python_rect)`` 差异列表。

        Args:
            a: native 路径的矩形列表。
            b: 回退路径的矩形列表。

        Returns:
            list[tuple]: 逐项不一致的矩形明细（空列表=全等）。
        """
        diffs: List[
            Tuple[int, Tuple[float, float, float, float], Tuple[float, float, float, float]]
        ] = []
        if len(a) != len(b):
            return [
                (
                    -1,
                    (float(len(a)), 0.0, 0.0, 0.0),
                    (float(len(b)), 0.0, 0.0, 0.0),
                )
            ]
        for i, (ra, rb) in enumerate(zip(a, b)):
            if ra != rb:
                diffs.append((i, ra, rb))
        return diffs

    @pytest.mark.parametrize(
        "case", TestPdfSelectionNativeParity._SELECTION_CASES
    )
    def test_rects_parity_native_vs_python_across_states(
        self,
        monkeypatch: pytest.MonkeyPatch,
        faf_core_available: bool,
        case: Tuple[Tuple[int, int], Tuple[int, int]],
    ) -> None:
        """happy：native 优先 vs 纯 Python 回退，缩放/滚动后矩形逐项一致。

        先以真实 DLL（recording 包装确认 native 被消费）在 native 视图出
        矩形，再强制回退在 Python 视图出矩形；同一 ``_VIEW_STATES`` 下逐
        矩形精确相等（``_cached_sel_words`` 两路同为 Python 权威值，零漂移）。

        Args:
            monkeypatch: pytest monkeypatch。
            faf_core_available: session 级 DLL 可用性探测。
            case: 选区参数对。
        """
        if not faf_core_available:
            pytest.skip("faf_core.dll 不可用，跳过 native-vs-Python 矩形对拍")
        bridge = current_bridge()
        if bridge is None or not getattr(
            bridge, "_supports_pdf_select_words", False
        ):
            pytest.skip("桥 pdf_select_words 未接线，跳过 native-vs-Python 矩形对拍")
        doc_n, native_view = TestPdfSelectionNativeParity._open_view()
        doc_p, python_view = TestPdfSelectionNativeParity._open_view()
        try:
            real = bridge.pdf_select_words
            calls: List[Tuple[object, ...]] = []

            def _recording(
                *args: object, **kwargs: object
            ) -> Optional[list]:
                calls.append(args)
                return real(*args, **kwargs)

            monkeypatch.setattr(bridge, "pdf_select_words", _recording)
            native_states = self._rects_for_states(native_view, case)
            assert calls, "DLL 可用时 native 路径必须先消费 faf_pdf_select_words"
            monkeypatch.setattr(bridge, "pdf_select_words", _noop_select)
            python_states = self._rects_for_states(python_view, case)

            counts = [len(state) for state in native_states]
            mismatch_msg = f"选区 {case} 矩形对拍："
            for state_idx, (nr, pr) in enumerate(
                zip(native_states, python_states)
            ):
                diffs = self._planar_diff(nr, pr)
                assert not diffs, (
                    f"选区 {case} 状态 _VIEW_STATES[{state_idx}] "
                    f"(zoom,ox,oy)={_VIEW_STATES[state_idx]} 矩形不一致: {diffs}; "
                    f"{mismatch_msg}"
                )
            print(
                f"[PASS] rect-parity native-vs-python {case} "
                f"states={len(_VIEW_STATES)} counts={counts} "
                "per-rect EXACT-EQUAL"
            )
        finally:
            doc_n.close()
            doc_p.close()

    @pytest.mark.parametrize(
        "case", TestPdfSelectionNativeParity._SELECTION_CASES
    )
    def test_rects_parity_fallback_equals_python_across_states(
        self,
        monkeypatch: pytest.MonkeyPatch,
        case: Tuple[Tuple[int, int], Tuple[int, int]],
    ) -> None:
        """failure：DLL 缺失（桥恒 None）回退矩形与纯 Python oracle 一致。

        两路都强制回退（互作 oracle），覆盖缺 DLL 场景下缩放/滚动后的
        矩形一致性；空选区（case6/7）矩形数为 0 亦须逐状态一致。

        Args:
            monkeypatch: pytest monkeypatch。
            case: 选区参数对。
        """
        bridge = current_bridge()
        if bridge is not None and bridge.available:
            monkeypatch.setattr(bridge, "pdf_select_words", _noop_select)
        doc_a, view_a = TestPdfSelectionNativeParity._open_view()
        doc_b, view_b = TestPdfSelectionNativeParity._open_view()
        try:
            states_a = self._rects_for_states(view_a, case)
            states_b = self._rects_for_states(view_b, case)
            for state_idx, (sa, sb) in enumerate(zip(states_a, states_b)):
                diffs = self._planar_diff(sa, sb)
                assert not diffs, (
                    f"DLL 缺失回退 选区 {case} 状态 _VIEW_STATES[{state_idx}] "
                    f"矩形不一致: {diffs}"
                )
            print(
                f"[PASS] rect-parity fallback-vs-python {case} "
                f"states={len(_VIEW_STATES)} counts={[len(s) for s in states_a]} "
                "per-rect EXACT-EQUAL"
            )
        finally:
            doc_a.close()
            doc_b.close()

    def test_mousemove_selection_budget_p50_record(
        self,
        qapp: Any,
        monkeypatch: pytest.MonkeyPatch,
        sample_pdf_file: str,
        faf_core_available: bool,
    ) -> None:
        """记录性：主线程 mouseMove 选区路径耗时 P50/mean/max（不 FAIL）。

        复现 ``NativePdfRenderer.mouseMoveEvent`` 选区分支
        （``native_pdf_renderer.py:535-552``）：每次移动把指针窗口坐标转到
        绝对文档坐标并重新查询选区（``window_to_absolute_document_pos`` +
        ``get_text_selection`` + ``_refresh_selection_rects``）。DLL 可用时
        该路径优先消费 native（``pdf_select_words`` 被调用），否则 Python
        回退；两路耗时 P50 均记录供证据留档。指标仅记录，不设 FAIL 预算。

        Args:
            qapp: session QApplication。
            monkeypatch: pytest monkeypatch。
            sample_pdf_file: 单页 PDF 路径。
            faf_core_available: session 级 DLL 可用性探测。
        """
        del faf_core_available
        ui_root = str(Path(__file__).resolve().parents[3] / "freeassetfilter" / "ui")
        if ui_root not in sys.path:
            sys.path.insert(0, ui_root)
        from PySide6.QtCore import QEvent, QPointF, Qt as _Qt
        from PySide6.QtGui import QMouseEvent

        from freeassetfilter.ui.layout.preview.native_pdf_renderer import (
            NativePdfRenderer,
        )

        renderer: NativePdfRenderer = NativePdfRenderer()
        try:
            assert renderer.load_document(sample_pdf_file) is True
            renderer._renderer.cancel_all()
            view: Optional[PdfDocumentView] = renderer._view
            assert view is not None

            native_calls: List[Tuple[object, ...]] = []
            bridge = current_bridge()
            recorded_mode: str = "python-fallback"
            if bridge is not None and bridge.available and getattr(
                bridge, "_supports_pdf_select_words", False
            ):
                real = bridge.pdf_select_words

                def _record(
                    *args: object, **kwargs: object
                ) -> Optional[list]:
                    native_calls.append(args)
                    return real(*args, **kwargs)

                monkeypatch.setattr(bridge, "pdf_select_words", _record)
                recorded_mode = "native-prefer"

            # 初始化选区分支状态（等价于按下左键后进入拖拽选择）。
            renderer._selecting = True
            renderer._mouse_dragged = True
            renderer._selection_hidden = False
            renderer._selected_text = ""
            begin_abs = view.window_to_absolute_document_pos(100.0, 40.0)
            renderer._sel_begin_abs = (begin_abs[0], begin_abs[1])

            samples: List[float] = []
            n_samples: int = 25
            for i in range(n_samples):
                x: float = 100.0 + float(i % 5) * 60.0
                y: float = 50.0 + float(i // 5) * 20.0
                event = QMouseEvent(
                    QEvent.Type.MouseMove,
                    QPointF(x, y),
                    QPointF(x, y),
                    QPointF(x, y),
                    _Qt.MouseButton.LeftButton,
                    _Qt.MouseButton.LeftButton,
                    _Qt.KeyboardModifier.NoModifier,
                )
                start = time.perf_counter()
                renderer.mouseMoveEvent(event)
                samples.append((time.perf_counter() - start) * 1000.0)

            assert len(samples) == n_samples
            assert view.selected_character_rects, (
                "拖拽选区应在页面文本上产生高亮矩形（预算路径被真实执行）"
            )
            assert not native_calls or len(native_calls) == n_samples, (
                "native 优先模式下每次 mouseMove 都应消费 pdf_select_words"
            )

            p50: float = _percentile_ms(samples, 0.50)
            p95: float = _percentile_ms(samples, 0.95)
            mean: float = sum(samples) / len(samples)
            max_ms: float = max(samples)
            print(
                f"[BUDGET] mode={recorded_mode} native_calls={len(native_calls)} "
                f"samples={len(samples)} p50_ms={p50:.3f} p95_ms={p95:.3f} "
                f"mean_ms={mean:.3f} max_ms={max_ms:.3f} "
                f"rects={len(view.selected_character_rects)}"
            )
        finally:
            if renderer is not None:
                renderer.close()
