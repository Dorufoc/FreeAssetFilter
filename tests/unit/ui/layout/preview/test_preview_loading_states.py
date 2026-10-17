# -*- coding: utf-8 -*-
"""预览器加载圆环与主线程非阻塞行为测试。

覆盖：
- 图片标准格式：后台解码期间圆环可见、`set_file` 快速返回、完成后隐藏
- 文本：读取/解码后台执行，加载覆盖页与圆环显隐
- PDF：异步打开期间浮动遮罩可见，文档 + 首帧就绪后隐藏
- Office：转换期间圆环可见，converted 后隐藏
- 字体：加载线程完成/失败时圆环显隐
- 文件夹 / 压缩包：加载覆盖层 helper 的 busy 状态切换
- 视频：媒体加载后台执行、fileLoaded 后隐藏圆环、buffering 信号驱动缓冲遮罩

验证命令：
    python -m pytest tests/unit/ui/layout/preview/test_preview_loading_states.py -q
"""

# targets: ui.layout.preview.* loading states

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

_PROJECT_ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / "freeassetfilter").is_dir()
)
_UI_ROOT = _PROJECT_ROOT / "freeassetfilter" / "ui"
for _p in (str(_UI_ROOT), str(_PROJECT_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import freeassetfilter.ui.layout.preview.folder_previewer_layout as folder_mod  # noqa: E402
import freeassetfilter.ui.layout.preview.office_previewer_layout as office_mod  # noqa: E402
import freeassetfilter.ui.layout.preview.text_previewer_layout as text_mod  # noqa: E402
from freeassetfilter.services.image_decoder_service import ImageDecoderService  # noqa: E402
from freeassetfilter.ui.layout.preview.folder_previewer_layout import (  # noqa: E402
    FolderPreviewerLayout,
)
from freeassetfilter.ui.layout.preview.image_previewer_layout import (  # noqa: E402
    ImagePreviewerLayout,
)
from freeassetfilter.ui.layout.preview.office_previewer_layout import (  # noqa: E402
    OfficePreviewerLayout,
)
from freeassetfilter.ui.layout.preview.pdf_previewer_layout import (  # noqa: E402
    PdfPreviewerLayout,
)
from freeassetfilter.ui.layout.preview.text_previewer_layout import (  # noqa: E402
    TextPreviewerLayout,
)
from freeassetfilter.ui.layout.preview.video_player_layout import (  # noqa: E402
    VideoPlayerLayout,
)
from tests.support.qt_helpers import flush_widget_queue, wait_until  # noqa: E402

pytestmark = pytest.mark.unit


# =============================================================================
# 工具
# =============================================================================


def _pump(qapp: QApplication, ms: int = 50) -> None:
    """有界事件泵。"""
    deadline = time.monotonic() + ms / 1000.0
    while time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)


def _make_png(tmp_path: Path) -> str:
    """生成一张 320×240 PNG。"""
    image = QImage(320, 240, QImage.Format.Format_RGB32)
    image.fill(QColor(90, 150, 200))
    path = tmp_path / "loading.png"
    assert image.save(str(path), "PNG")
    return str(path)


def _make_pdf(tmp_path: Path) -> str:
    """生成单页 PDF。"""
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 72), "loading")
    path = tmp_path / "loading.pdf"
    doc.save(str(path))
    doc.close()
    return str(path)


# =============================================================================
# 图片
# =============================================================================


def test_image_loading_spinner_and_non_blocking(
    qapp: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """标准格式解码在后台执行：set_file 快速返回，圆环先显示后隐藏。"""
    path = _make_png(tmp_path)
    gate = threading.Event()
    entered = threading.Event()
    real_decode = ImageDecoderService.decode_standard_to_qimage

    def _gated_decode(file_path: str):
        entered.set()
        gate.wait(5)
        return real_decode(file_path)

    monkeypatch.setattr(
        ImageDecoderService,
        "decode_standard_to_qimage",
        staticmethod(_gated_decode),
    )
    previewer = ImagePreviewerLayout()
    previewer.resize(600, 480)
    try:
        start = time.monotonic()
        assert previewer.set_file(path) is True
        assert time.monotonic() - start < 0.5, "解码不应阻塞 set_file"
        assert entered.wait(2), "后台解码未启动"
        assert not previewer._loading_spinner.isHidden()  # noqa: SLF001
        assert "解码" in previewer._placeholder.text()  # noqa: SLF001
        assert previewer._content_stack.currentIndex() == 1  # noqa: SLF001

        gate.set()
        assert wait_until(
            qapp,
            lambda: previewer._loading_spinner.isHidden(),  # noqa: SLF001
            timeout_ms=5000,
        )
        assert not previewer._pixmap_item.pixmap().isNull()  # noqa: SLF001
        assert previewer._content_stack.currentIndex() == 0  # noqa: SLF001
    finally:
        gate.set()
        previewer.cleanup()
        flush_widget_queue(qapp)
        previewer.deleteLater()
        flush_widget_queue(qapp)


# =============================================================================
# 文本
# =============================================================================


def test_text_loading_spinner_and_non_blocking(
    qapp: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """文本读取/解码后台执行：加载期间圆环可见，完成后隐藏。"""
    path = tmp_path / "loading.txt"
    path.write_text("hello loading", encoding="utf-8")
    gate = threading.Event()
    entered = threading.Event()
    real_decode = text_mod._decode_auto_chain  # noqa: SLF001

    def _gated_decode(raw: bytes, encoding: Optional[str] = None):
        entered.set()
        gate.wait(5)
        return real_decode(raw, encoding)

    monkeypatch.setattr(text_mod, "_decode_auto_chain", _gated_decode)
    previewer = TextPreviewerLayout()
    previewer.resize(600, 480)
    try:
        start = time.monotonic()
        previewer.set_file(str(path))
        assert time.monotonic() - start < 0.5, "读取/解码不应阻塞 set_file"
        assert entered.wait(2), "后台读取/解码未启动"
        assert not previewer._loading_spinner.isHidden()  # noqa: SLF001
        assert previewer._content_stack.currentIndex() == 2  # noqa: SLF001

        gate.set()
        assert wait_until(
            qapp,
            lambda: previewer._loading_spinner.isHidden(),  # noqa: SLF001
            timeout_ms=5000,
        )
        assert previewer._content_stack.currentIndex() == 0  # noqa: SLF001
        assert "hello loading" in previewer._source_view._text_edit.toPlainText()
    finally:
        gate.set()
        previewer.cleanup()
        flush_widget_queue(qapp)
        previewer.deleteLater()
        flush_widget_queue(qapp)


# =============================================================================
# PDF
# =============================================================================


def test_pdf_busy_overlay_until_first_render(
    qapp: QApplication, tmp_path: Path
) -> None:
    """PDF 异步打开：浮动遮罩「正在打开/渲染」可见，首帧后隐藏。"""
    path = _make_pdf(tmp_path)
    previewer = PdfPreviewerLayout()
    previewer.resize(600, 480)
    try:
        start = time.monotonic()
        assert previewer.set_file(path) is True
        assert time.monotonic() - start < 0.5, "PDF 打开不应阻塞 set_file"
        assert not previewer._busy_overlay.isHidden()  # noqa: SLF001
        assert not previewer._busy_overlay._spinner.isHidden()  # noqa: SLF001
        assert "打开" in previewer._busy_overlay._label.text()  # noqa: SLF001

        assert wait_until(
            qapp,
            lambda: previewer._renderer._doc is not None  # noqa: SLF001
            and previewer._content_stack.currentIndex() == 0,  # noqa: SLF001
            timeout_ms=5000,
        )
        assert wait_until(
            qapp,
            lambda: previewer._busy_overlay.isHidden(),  # noqa: SLF001
            timeout_ms=5000,
        )
    finally:
        previewer.cleanup()
        flush_widget_queue(qapp)
        previewer.deleteLater()
        flush_widget_queue(qapp)


def test_pdf_missing_path_hides_spinner(qapp: QApplication, tmp_path: Path) -> None:
    """PDF 缺失路径：返回 False、遮罩隐藏、覆盖页显示错误。"""
    previewer = PdfPreviewerLayout()
    try:
        assert previewer.set_file(str(tmp_path / "ghost.pdf")) is False
        assert previewer._busy_overlay.isHidden()  # noqa: SLF001
        assert "文件不存在" in previewer._placeholder.text()  # noqa: SLF001
    finally:
        previewer.cleanup()
        flush_widget_queue(qapp)
        previewer.deleteLater()
        flush_widget_queue(qapp)


# =============================================================================
# Office
# =============================================================================


class _FakeOfficeWorker(QObject):
    """可控 Office worker 替身。"""

    converted = Signal(str)
    failed = Signal(str)

    def __init__(self, file_info: dict, timeout: Any = None, parent: Any = None) -> None:
        super().__init__(parent)
        self.file_info = dict(file_info)
        self.started = False

    def start(self) -> None:
        self.started = True

    def is_running(self) -> bool:
        return self.started

    def request_cancel(self) -> None:
        self.started = False

    def retire(self) -> None:
        self.started = False

    def cleanup(self, wait_ms: int = 3000) -> None:
        self.started = False


def test_office_conversion_spinner(
    qapp: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Office 转换期间圆环可见，converted 后隐藏并显示 HTML 视图。"""
    monkeypatch.setattr(office_mod, "OfficeConverterWorker", _FakeOfficeWorker)
    previewer = OfficePreviewerLayout()
    try:
        previewer.set_file(str(tmp_path / "sample.docx"))
        assert isinstance(previewer._current_worker, _FakeOfficeWorker)  # noqa: SLF001
        assert not previewer._loading_spinner.isHidden()  # noqa: SLF001
        assert previewer._content_stack.currentWidget() is previewer._overlay  # noqa: SLF001

        previewer._current_worker.converted.emit("html:<p>ok</p>")  # noqa: SLF001
        qapp.processEvents()
        assert previewer._loading_spinner.isHidden()  # noqa: SLF001
        assert previewer._content_stack.currentWidget() is previewer._html_view  # noqa: SLF001
    finally:
        previewer.cleanup()
        flush_widget_queue(qapp)
        previewer.deleteLater()
        flush_widget_queue(qapp)


def test_office_converted_pdf_routes_to_pdf_loading(
    qapp: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Office 转换出 PDF 后：内嵌 PDF 预览器接管并显示自己的加载遮罩。"""
    monkeypatch.setattr(office_mod, "OfficeConverterWorker", _FakeOfficeWorker)
    pdf_path = _make_pdf(tmp_path)
    previewer = OfficePreviewerLayout()
    try:
        previewer.set_file(str(tmp_path / "sample.xlsx"))
        previewer._current_worker.converted.emit(pdf_path)  # noqa: SLF001
        qapp.processEvents()
        assert previewer._pdf is not None  # noqa: SLF001
        assert previewer._content_stack.currentWidget() is previewer._pdf_holder  # noqa: SLF001
        assert not previewer._pdf._busy_overlay.isHidden()  # noqa: SLF001
        assert wait_until(
            qapp,
            lambda: previewer._pdf._busy_overlay.isHidden(),  # noqa: SLF001
            timeout_ms=5000,
        )
    finally:
        previewer.cleanup()
        flush_widget_queue(qapp)
        previewer.deleteLater()
        flush_widget_queue(qapp)


# =============================================================================
# 字体
# =============================================================================


class _FakeFontThread(QObject):
    """可控字体加载线程替身（预览器只依赖信号与少量方法）。"""

    finished = Signal(int, bool, str, int)
    error = Signal(int, str)
    thread_finished = Signal()

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._file_path = ""
        self._request_id = 0
        self._aborted = False
        self.started = False

    def set_file(self, file_path: str) -> None:
        self._file_path = file_path

    def set_request_id(self, request_id: int) -> None:
        self._request_id = request_id

    def abort(self) -> None:
        self._aborted = True

    def start(self) -> None:
        self.started = True

    def isRunning(self) -> bool:  # noqa: N802
        return self.started and not self._aborted


def test_font_loading_spinner(
    qapp: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """字体加载期间圆环可见，成功回调后隐藏并切预览页。"""
    monkeypatch.setattr("freeassetfilter.ui.layout.preview.font_previewer_layout.FontLoadThread", _FakeFontThread)
    path = tmp_path / "fake.ttf"
    path.write_bytes(b"\x00")
    previewer = __import__(
        "freeassetfilter.ui.layout.preview.font_previewer_layout",
        fromlist=["FontPreviewerLayout"],
    ).FontPreviewerLayout()
    try:
        previewer.set_file(str(path))
        assert isinstance(previewer._load_thread, _FakeFontThread)  # noqa: SLF001
        assert not previewer._loading_spinner.isHidden()  # noqa: SLF001
        thread = previewer._load_thread  # noqa: SLF001
        thread.finished.emit(thread._request_id, True, "FakeFamily", 1)  # noqa: SLF001
        qapp.processEvents()
        assert previewer._loading_spinner.isHidden()  # noqa: SLF001
    finally:
        previewer.cleanup()
        flush_widget_queue(qapp)
        previewer.deleteLater()
        flush_widget_queue(qapp)


# =============================================================================
# 文件夹 / 压缩包
# =============================================================================


def test_folder_loading_spinner_and_gated_scan(
    qapp: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """目录扫描期间圆环可见，完成后隐藏并显示列表。"""
    root = tmp_path / "folder"
    root.mkdir()
    (root / "a.txt").write_text("a", encoding="utf-8")
    gate = threading.Event()
    entered = threading.Event()
    real_collect = folder_mod._collect_directory_entries  # noqa: SLF001

    def _gated_collect(path: str):
        entered.set()
        gate.wait(5)
        return real_collect(path)

    monkeypatch.setattr(folder_mod, "_collect_directory_entries", _gated_collect)
    previewer = FolderPreviewerLayout()
    previewer.resize(600, 480)
    try:
        previewer.set_file(str(root))
        assert entered.wait(2), "后台扫描未启动"
        assert not previewer._loading_spinner.isHidden()  # noqa: SLF001
        assert previewer._content_stack.currentIndex() == previewer._PAGE_OVERLAY  # noqa: SLF001
        gate.set()
        assert wait_until(
            qapp,
            lambda: previewer._loading_spinner.isHidden()  # noqa: SLF001
            and previewer._content_stack.currentIndex() == previewer._PAGE_LIST,  # noqa: SLF001
            timeout_ms=5000,
        )
    finally:
        gate.set()
        previewer.cleanup()
        flush_widget_queue(qapp)
        previewer.deleteLater()
        flush_widget_queue(qapp)


def test_archive_overlay_busy_contract(qapp: QApplication) -> None:
    """压缩包覆盖层：busy=True 显示圆环，busy=False 隐藏。"""
    from freeassetfilter.ui.layout.preview.archive_previewer_layout import (
        ArchivePreviewerLayout,
    )

    previewer = ArchivePreviewerLayout()
    try:
        previewer._show_overlay("正在读取压缩包内容…", busy=True)  # noqa: SLF001
        assert not previewer._loading_spinner.isHidden()  # noqa: SLF001
        previewer._show_overlay("压缩包内无内容或无法读取", busy=False)  # noqa: SLF001
        assert previewer._loading_spinner.isHidden()  # noqa: SLF001
    finally:
        previewer.cleanup()
        flush_widget_queue(qapp)
        previewer.deleteLater()
        flush_widget_queue(qapp)


# =============================================================================
# 视频 / 音频
# =============================================================================


def test_video_loading_and_buffering_spinner(
    qapp: QApplication,
    heartbeat_manager: Any,
    tmp_path: Path,
) -> None:
    """视频加载后台执行；fileLoaded 隐藏圆环；buffering 驱动缓冲遮罩。"""
    from unittest.mock import MagicMock

    media = tmp_path / "sample.mp4"
    media.write_bytes(b"\x00" * 16)
    previewer = VideoPlayerLayout()
    previewer.resize(600, 480)
    gate = threading.Event()
    entered = threading.Event()
    fake = MagicMock()
    fake.is_core_operational.return_value = True
    fake.is_initialized.return_value = True
    fake.set_window_id.return_value = True
    fake.play.return_value = True
    fake.set_volume.return_value = True
    fake.set_speed.return_value = True
    fake.set_loop.return_value = True

    def _gated_load(*args: Any, **kwargs: Any) -> bool:
        entered.set()
        gate.wait(5)
        return True

    fake.load_file.side_effect = _gated_load
    previewer._mpv_manager = fake  # noqa: SLF001
    previewer._refresh_player_tracks = lambda: None  # type: ignore[method-assign]  # noqa: SLF001
    try:
        start = time.monotonic()
        assert previewer.set_file(str(media), is_audio=False) is True
        assert time.monotonic() - start < 0.5, "媒体加载不应阻塞 set_file"
        assert entered.wait(2), "后台加载未启动"
        assert not previewer._loading_spinner.isHidden()  # noqa: SLF001
        assert previewer._stack.currentIndex() == 1  # noqa: SLF001

        gate.set()
        assert wait_until(
            qapp,
            lambda: previewer._media_load_task is None,  # noqa: SLF001
            timeout_ms=5000,
        )
        previewer._on_file_loaded(str(media))  # noqa: SLF001
        qapp.processEvents()
        assert previewer._loading_spinner.isHidden()  # noqa: SLF001
        assert previewer._stack.currentIndex() == 0  # noqa: SLF001

        previewer._on_buffering_changed(True)  # noqa: SLF001
        assert not previewer._loading_spinner.isHidden()  # noqa: SLF001
        assert "缓冲" in previewer._placeholder.text()  # noqa: SLF001
        previewer._on_buffering_changed(False)  # noqa: SLF001
        assert previewer._loading_spinner.isHidden()  # noqa: SLF001
        assert previewer._stack.currentIndex() == 0  # noqa: SLF001
    finally:
        gate.set()
        previewer.cleanup()
        flush_widget_queue(qapp)
        previewer.deleteLater()
        flush_widget_queue(qapp)
