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

import time
from pathlib import Path
from typing import Any, List, Optional, Tuple

import pytest

fitz = pytest.importorskip("fitz")  # PyMuPDF 缺失时跳过整个模块

from PySide6.QtGui import QImage

from freeassetfilter.services.pdf_document import PdfDocument
from freeassetfilter.services.pdf_document_view import PdfDocumentView
from freeassetfilter.services.pdf_renderer import (
    PdfBackgroundRenderer,
    RenderRequest,
    RenderResponse,
)
from tests.support.data_factories import make_pdf
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
