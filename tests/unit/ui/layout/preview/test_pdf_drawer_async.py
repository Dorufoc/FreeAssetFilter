# -*- coding: utf-8 -*-
# targets: freeassetfilter.ui.layout.preview.pdf_previewer_layout
"""PDF 缩略图抽屉异步批处理测试（faf-core-rust-migration todo 31）。

验证 ``PdfPreviewerLayout._populate_thumbnail_drawer`` 0.25x 逐页循环移出
UI 线程后的四条核心契约：

1. **缩略图像素与改造前一致** —— 抽屉产出的缩略图与同步 0.25x 渲染
   （同一 ``fitz.Matrix(0.25, 0.25)``）逐像素一致（PNG 哈希断言）；
2. **UI 线程不执行渲染** —— ``fitz.Page.get_pixmap`` 调用发生在 worker
   线程（线程 id 断言，UI 线程 id 不在渲染线程集合内）；
3. **generation 防陈旧** —— 快速翻页/重复填充时旧批结果被丢弃
   （重复填充后缩略图数量仍等于页数、陈旧批直达 handler 不被采纳）；
4. **worker 路径无 QPixmap 构造** —— ``_ThumbnailDrawerTask`` 类体
   grep 断言不含 ``QPixmap``。

另覆盖 worker 失败路径（损坏/缺失文档 → 空抽屉不崩溃）与分批语义
（20 页 / 每批 8 → 8+8+4 三批）。
"""
from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from typing import Any, List, Tuple

import pytest

fitz = pytest.importorskip("fitz")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QThreadPool
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from freeassetfilter.ui.layout.preview.pdf_previewer_layout import (
    PdfPreviewerLayout,
    _ThumbnailDrawerTask,
)
from tests.support.qt_helpers import flush_widget_queue, safe_teardown, wait_for_signal

pytestmark = pytest.mark.unit


def _make_pdf(tmp_path: Path, pages: int = 3) -> str:
    """用 PyMuPDF 在内存构造多页 PDF（612×792pt，与既有测试一致）。"""
    doc: fitz.Document = fitz.open()
    for i in range(pages):
        page: fitz.Page = doc.new_page(width=612, height=792)
        page.insert_text((72, 72), f"Page {i + 1}")
    target = tmp_path / "drawer_async.pdf"
    doc.save(str(target))
    doc.close()
    return str(target)


def _image_png_hash(image: QImage) -> str:
    """把 QImage 编码为 PNG 后取 sha256（确定性的像素级哈希）。"""
    buffer: QByteArray = QByteArray()
    sink: QBuffer = QBuffer(buffer)
    sink.open(QIODevice.WriteOnly)
    image.save(sink, "PNG")
    sink.close()
    return hashlib.sha256(bytes(buffer.data())).hexdigest()


def _wait_drawer_populated(
    layout: PdfPreviewerLayout, expected: int, qapp: QApplication, timeout: float = 20.0
) -> None:
    """有界事件泵，直到抽屉缩略图数量达到 *expected*。"""
    import time

    deadline: float = time.time() + timeout
    while time.time() < deadline:
        qapp.processEvents()
        if len(layout._thumbnail_widgets) >= expected:  # noqa: SLF001
            qapp.processEvents()
            return
        time.sleep(0.01)
    raise AssertionError(
        f"缩略图抽屉未在 {timeout}s 内填充到 {expected} 个"
        f"（当前 {len(layout._thumbnail_widgets)}）"
    )


# ── 1. 像素一致性（与改造前的同步 0.25x 渲染逐像素一致）──────────────


def test_drawer_pixels_identical_to_synchronous(
    qapp: QApplication, tmp_path: Path
) -> None:
    """happy：抽屉缩略图像素哈希 == 同步 0.25x 渲染像素哈希。

    Args:
        qapp: session QApplication。
        tmp_path: 每用例临时目录。
    """
    path: str = _make_pdf(tmp_path, pages=3)
    layout: PdfPreviewerLayout = PdfPreviewerLayout()
    try:
        assert layout.set_file(path) is True
        _wait_drawer_populated(layout, 3, qapp)

        # 参考：与改造前完全一致的同步 0.25x 渲染（同一 Matrix）
        doc: fitz.Document = fitz.open(path)
        try:
            page: fitz.Page = doc.load_page(0)
            pix: fitz.Pixmap = page.get_pixmap(
                matrix=fitz.Matrix(0.25, 0.25), alpha=False
            )
            ref: QImage = QImage(
                bytes(pix.samples), pix.width, pix.height, pix.stride,
                QImage.Format_RGB888,
            )
        finally:
            doc.close()

        thumb_img: QImage = layout._thumbnail_widgets[0]._pixmap.toImage()  # noqa: SLF001
        assert thumb_img.width() == 153  # 0.25x of 612
        assert thumb_img.height() == 198  # 0.25x of 792
        assert _image_png_hash(thumb_img) == _image_png_hash(ref)
    finally:
        layout.cleanup()
        safe_teardown(layout)
        flush_widget_queue(qapp)


# ── 2. UI 线程不执行渲染（线程 id）───────────────────────────────────


def test_drawer_renders_off_ui_thread(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """happy：get_pixmap 渲染全部发生在非 UI 线程。

    monkeypatch ``fitz.Page.get_pixmap`` 记录调用线程 id；断言发生渲染
    且 UI 线程 id 不在渲染线程集合内（UI 线程不执行 0.25x 渲染循环）。

    Args:
        qapp: session QApplication。
        tmp_path: 每用例临时目录。
        monkeypatch: pytest monkeypatch。
    """
    path: str = _make_pdf(tmp_path, pages=6)
    render_thread_ids: List[int] = []
    main_tid: int = threading.get_ident()
    orig_get_pixmap: Any = fitz.Page.get_pixmap

    def _spy_get_pixmap(self: Any, *args: Any, **kwargs: Any) -> Any:
        render_thread_ids.append(threading.get_ident())
        return orig_get_pixmap(self, *args, **kwargs)

    monkeypatch.setattr(fitz.Page, "get_pixmap", _spy_get_pixmap)

    layout: PdfPreviewerLayout = PdfPreviewerLayout()
    try:
        assert layout.set_file(path) is True
        _wait_drawer_populated(layout, 6, qapp)
        assert render_thread_ids, "应至少发生一次页面渲染"
        assert main_tid not in set(render_thread_ids), (
            "0.25x 渲染不得发生在 UI 线程"
        )
    finally:
        layout.cleanup()
        safe_teardown(layout)
        flush_widget_queue(qapp)


# ── 3. generation 防陈旧（快速翻页/重复填充丢弃旧批）─────────────────


def test_drawer_generation_drops_stale_batches(
    qapp: QApplication, tmp_path: Path
) -> None:
    """happy：快速翻页（重复填充）后旧批结果被丢弃，数量不重复。

    先完整填充一轮（gen1），再手动触发第二次填充（gen2 自增、旧任务
    取消）；陈旧批直达 ``_on_thumbnail_batch_ready`` 不被采纳；等待
    gen2 填充完成后缩略图数量恰为页数（无重复），在途任务全部释放。

    Args:
        qapp: session QApplication。
        tmp_path: 每用例临时目录。
    """
    path: str = _make_pdf(tmp_path, pages=20)  # 3 批（8+8+4）
    layout: PdfPreviewerLayout = PdfPreviewerLayout()
    try:
        assert layout.set_file(path) is True
        _wait_drawer_populated(layout, 20, qapp)
        gen1: int = layout._thumb_gen
        assert len(layout._thumbnail_widgets) == 20

        # 快速翻页：再次填充 → generation 自增、旧任务协作式取消
        layout._populate_thumbnail_drawer()
        assert layout._thumb_gen == gen1 + 1

        # 陈旧批直达 handler：即使 worker 迟到投递也直接被丢弃
        stale: QImage = QImage(4, 4, QImage.Format_RGB888)
        count_before: int = len(layout._thumbnail_widgets)
        layout._on_thumbnail_batch_ready(gen1, [(0, stale)])
        assert len(layout._thumbnail_widgets) == count_before

        # 等待 gen2 填充完成 → 数量仍恰为页数（无重复采纳）
        _wait_drawer_populated(layout, 20, qapp)
        assert len(layout._thumbnail_widgets) == 20
        # 全部任务 finished 后引用释放
        deadline: float = 20.0
        import time

        end: float = time.time() + deadline
        while layout._thumb_tasks and time.time() < end:
            qapp.processEvents()
            time.sleep(0.01)
        assert layout._thumb_tasks == []
    finally:
        layout.cleanup()
        safe_teardown(layout)
        flush_widget_queue(qapp)


def test_drawer_late_stale_batch_not_adopted(
    qapp: QApplication, tmp_path: Path
) -> None:
    """boundary：gen 不匹配的 batch 绝不修改抽屉（防翻页串批）。"""
    path: str = _make_pdf(tmp_path, pages=2)
    layout: PdfPreviewerLayout = PdfPreviewerLayout()
    try:
        assert layout.set_file(path) is True
        _wait_drawer_populated(layout, 2, qapp)
        current_gen: int = layout._thumb_gen
        before: int = len(layout._thumbnail_widgets)
        img: QImage = QImage(8, 8, QImage.Format_RGB888)
        layout._on_thumbnail_batch_ready(current_gen - 1, [(0, img)])
        layout._on_thumbnail_batch_ready(current_gen + 1, [(0, img)])
        assert len(layout._thumbnail_widgets) == before
    finally:
        layout.cleanup()
        safe_teardown(layout)
        flush_widget_queue(qapp)


# ── 4. worker 路径无 QPixmap 构造（grep 断言）────────────────────────


def test_worker_path_has_no_qpixmap_construction(qapp: QApplication) -> None:
    """grep 断言：``_ThumbnailDrawerTask`` 类体不出现 ``QPixmap(`` 构造。"""
    import freeassetfilter.ui.layout.preview.pdf_previewer_layout as _mod

    src: str = Path(_mod.__file__).read_text(encoding="utf-8")
    start: int = src.index("class _ThumbnailDrawerTask")
    end: int = src.index("class PdfPreviewerLayout", start)
    worker_src: str = src[start:end]
    assert worker_src.strip(), "应能定位到 worker 类体"
    assert "QPixmap(" not in worker_src, "worker 段不得构造 QPixmap"


# ── worker 单元级：分批语义 / generation / 失败路径 ──────────────────


def test_worker_batches_and_generation(
    qapp: QApplication, tmp_path: Path
) -> None:
    """happy：20 页 / 每批 8 → 三批（8+8+4），generation 原样回传。"""
    path: str = _make_pdf(tmp_path, pages=20)
    task: _ThumbnailDrawerTask = _ThumbnailDrawerTask(
        path=path, page_count=20, generation=42, batch_size=8
    )
    batches: List[Tuple[int, int]] = []
    first_images: List[QImage] = []
    finished: List[int] = []

    def _collect_batch(gen: int, batch: Any) -> None:
        batches.append((gen, len(batch)))
        if not first_images:
            first_images.extend(img for _, img in batch)

    task.batch_ready.connect(_collect_batch)
    task.finished.connect(lambda g: finished.append(g))
    task.start()
    try:
        assert wait_for_signal(task.finished, 15000), "worker 未在超时内完成"
        # batch 与 finished 同 sender 按序投递，全部 batch 必先于 finished 到达
        assert batches == [(42, 8), (42, 8), (42, 4)]
        assert finished == [42]
        # 每批图像为 0.25x 渲染（153×198），GUI 线程可经 fromImage 转 QPixmap
        assert first_images
        assert all(img.width() == 153 and img.height() == 198 for img in first_images)
        assert all(not img.isNull() for img in first_images)
    finally:
        QThreadPool.globalInstance().waitForDone(5000)


def test_worker_missing_doc_emits_finished_empty(
    qapp: QApplication, tmp_path: Path
) -> None:
    """failure：文档缺失 → 不崩溃、无 batch、finished 照发（空抽屉）。"""
    task: _ThumbnailDrawerTask = _ThumbnailDrawerTask(
        path=str(tmp_path / "missing.pdf"), page_count=5, generation=7
    )
    batches: List[Any] = []
    finished: List[int] = []
    task.batch_ready.connect(lambda g, b: batches.append((g, b)))
    task.finished.connect(lambda g: finished.append(g))
    task.start()
    try:
        assert wait_for_signal(task.finished, 15000), "worker 未在超时内完成"
        assert batches == []
        assert finished == [7]
    finally:
        QThreadPool.globalInstance().waitForDone(5000)
