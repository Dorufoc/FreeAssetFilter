# -*- coding: utf-8 -*-
"""
Office 预览端到端集成测试（T13）

端到端「docx/xlsx → 转换 → 预览」流程，覆盖新 UI 布局
``freeassetfilter/ui/layout/preview/office_previewer_layout.py`` 与
``freeassetfilter/ui/layout/preview/pdf_previewer_layout.py`` —— 后者是本测试的
**首批直接覆盖**（既有 ``tests/components/test_pdf_previewer.py`` 与
``tests/unit/test_pdf_previewer.py`` 只覆盖旧 ``components/`` 组件，Metis D6）。

测试策略（可控端到端）：
- **真实 worker**：使用真实 ``OfficeConverterWorker``（QThread）。跨线程信号经
  ``app.processEvents()`` 轮询等待（PySide6 6.11.1 下 ``QSignalSpy.wait`` 恒返
  False，见 T9 学习）。
- **真实转换**：docx→HTML（mammoth）与 xlsx→TSV（openpyxl）通过 patch
  ``OfficeConverter._soffice_available`` / ``_com_available`` 强制走纯 Python
  路径，使用现场生成的真实源文件（生成器缺失则 ``importorskip`` 跳过，不伪造）。
- **PDF 产物路由**：patch ``OfficeConverter.convert`` 返回构造的
  ``ConversionResult(content_type="pdf")``，产物为 fitz 现造的真实 PDF；断言内嵌
  ``PdfPreviewerLayout.set_file`` 被调用并真实加载（非 fake）。
- **绝不启动真实 Office/Word**：COM 后端在集成测试中一律通过 patch 避开
  （Metis B3）。
- **失败路径**：conversion 返回 ``content_type="error"`` → ``failed`` 信号 →
  错误视图；legacy 格式（doc）无任何后端 → 真实分派返回安装提示 → 错误视图。
- **cleanup 契约（Metis B4）**：``cleanup()`` 必须触达 ``_pdf`` 与
  ``_table_view._pdf`` 的 ``cleanup()``，且可安全调用两次。

全部用例 offscreen 可跑（无真实显示器依赖）。不引入 flaky 时间断言：等待一律用
``_pump_until`` 轮询，不用固定 sleep 断言时序。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QApplication

from freeassetfilter.services import office_converter as conv
from freeassetfilter.services.office_converter import ConversionResult
from freeassetfilter.services.office_converter_worker import OfficeConverterWorker
from freeassetfilter.ui.layout.preview import office_previewer_layout as opl
from freeassetfilter.ui.layout.preview import pdf_previewer_layout as pdf_mod

# =============================================================================
# 轮询辅助（跨线程信号投递必需；替代不可靠的 QSignalSpy.wait）
# =============================================================================


def _pump_until(
    condition: Callable[[], bool],
    timeout_ms: int = 8000,
    interval_ms: float = 5.0,
) -> bool:
    """反复 ``processEvents`` 轮询直到 *condition* 成立或超时。

    ``QSignalSpy.wait(N)`` 在本环境（PySide6 6.11.1）不投递跨线程队列信号，
    手动 ``processEvents()`` 轮询才可靠（T9 已实证）。语义等价：同一超时窗口内
    泵事件直到谓词成立。

    Parameters
    ----------
    condition : Callable[[], bool]
        结束条件谓词。
    timeout_ms : int
        最大等待毫秒数。
    interval_ms : float
        两次泵事件之间的轮询间隔（毫秒）。

    Returns
    -------
    bool
        超时窗口内谓词成立返回 ``True``，否则 ``False``。
    """
    app = QApplication.instance()
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        if condition():
            return True
        if app is not None:
            app.processEvents()
        time.sleep(interval_ms / 1000.0)
    if app is not None:
        app.processEvents()
    return bool(condition())


def _pump_for(ms: int) -> None:
    """泵 Qt 事件循环约 *ms* 毫秒。

    用途：让 ``PdfPreviewerLayout.set_file`` 调度的 ``QTimer.singleShot``
    （50/100/150ms 的 fit/scroll/缩略图任务）在布局仍存活期间触发，避免清理后
    timer 回调命中已销毁对象。这是资源收尾而非时序断言。
    """
    app = QApplication.instance()
    deadline = time.monotonic() + ms / 1000.0
    while time.monotonic() < deadline:
        if app is not None:
            app.processEvents()
        time.sleep(0.005)


def _pump() -> None:
    """单次泵事件（收尾保险）。"""
    app = QApplication.instance()
    if app is not None:
        app.processEvents()


# =============================================================================
# 真实源文件生成器（生成器缺失 → 跳过对应用例，而非伪造）
# =============================================================================


@pytest.fixture
def make_docx(tmp_path: Path) -> Callable[[str], Path]:
    """现场生成最小 docx（python-docx）；生成器缺失则跳过用例。"""

    def _make(name: str = "sample.docx") -> Path:
        docx = pytest.importorskip("docx")
        path = tmp_path / name
        document = docx.Document()
        document.add_paragraph("T13 集成测试文档正文")
        document.save(str(path))
        return path

    return _make


@pytest.fixture
def make_xlsx(tmp_path: Path) -> Callable[[str], Path]:
    """现场生成最小 xlsx（openpyxl）；生成器缺失则跳过用例。"""

    def _make(name: str = "sample.xlsx") -> Path:
        openpyxl = pytest.importorskip("openpyxl")
        path = tmp_path / name
        workbook = openpyxl.Workbook()
        worksheet = workbook.active
        worksheet.append(["姓名", "分数"])
        worksheet.append(["Alice", 90])
        worksheet.append(["Bob", 80])
        workbook.save(str(path))
        return path

    return _make


@pytest.fixture
def make_pdf(tmp_path: Path) -> Callable[[int, str], Path]:
    """用 PyMuPDF(fitz) 现造多页真实 PDF；生成器缺失则跳过用例。"""

    def _make(pages: int = 2, name: str = "out.pdf") -> Path:
        fitz = pytest.importorskip("fitz")
        path = tmp_path / name
        document = fitz.open()
        for index in range(pages):
            page = document.new_page()
            page.insert_text((72, 72), f"T13 集成测试 PDF 第 {index + 1} 页")
        document.save(str(path))
        document.close()
        return path

    return _make


# =============================================================================
# 转换后端裁剪（patch 点）
# =============================================================================


def _file_info(path: Path) -> dict:
    """构建与宿主 ``unified_previewer`` 契约一致的 file_info。"""
    return {
        "name": path.name,
        "path": str(path),
        "is_dir": False,
        "size": path.stat().st_size,
        "modified": "",
        "created": "",
        "suffix": path.suffix.lstrip(".").lower(),
    }


def _force_pure_python(monkeypatch: pytest.MonkeyPatch) -> None:
    """让真实 ``convert()`` 绕过 LO/COM 后端，走真实纯 Python 降级。

    本机 soffice_available=False 但 com_available=True（注册表有 Office/WPS
    ProgID）——若不 patch，docx/xlsx 会分派到 COM 后端真实启动 Office，违反
    Metis B3。两探针都 patch 成 False 同时保证测试与机器无关。
    """
    monkeypatch.setattr(
        conv.OfficeConverter, "_soffice_available", staticmethod(lambda: False)
    )
    monkeypatch.setattr(
        conv.OfficeConverter, "_com_available", staticmethod(lambda: False)
    )


def _patch_convert_result(
    monkeypatch: pytest.MonkeyPatch,
    result: ConversionResult,
) -> None:
    """patch ``OfficeConverter.convert`` 直接返回构造好的结果。

    保留真实 worker 的信号发射 / generation guard / 视图路由，仅替换转换后端
    （模拟 LO/COM 产物或错误结果）。
    """
    monkeypatch.setattr(
        conv.OfficeConverter,
        "convert",
        classmethod(lambda cls, file_info: result),
    )


def _patch_convert_slow(
    monkeypatch: pytest.MonkeyPatch,
    result_factory: Callable[[dict], ConversionResult],
    delay: float = 1.0,
) -> None:
    """patch ``convert`` 为慢速实现（模拟在途转换）。

    用于同实例重分派测试：第一次 ``set_file`` 启动的 worker 仍在转换时再次
    ``set_file``，验证旧 worker 被取消且其迟到信号被 generation guard 丢弃。
    """
    monkeypatch.setattr(
        conv.OfficeConverter,
        "_cleanup_orphan_processes",
        staticmethod(lambda task_started_at: None),
    )

    def _convert(cls: Any, file_info: dict) -> ConversionResult:
        time.sleep(delay)
        return result_factory(file_info)

    monkeypatch.setattr(conv.OfficeConverter, "convert", classmethod(_convert))


# =============================================================================
# 真实纯 Python 转换（mammoth / openpyxl）
# =============================================================================


class TestRealPurePythonConversion:
    """真实 worker + 真实纯 Python 转换：完整「转换 → 信号 → 视图」流。"""

    def test_docx_real_mammoth_conversion_to_html_view(
        self,
        qapp: Any,
        monkeypatch: pytest.MonkeyPatch,
        make_docx: Callable[[str], Path],
    ) -> None:
        """docx → 真实 mammoth → HTML 降级视图（纯 Python 路径强制）。"""
        _force_pure_python(monkeypatch)
        source = make_docx()
        layout = opl.OfficePreviewerLayout()
        try:
            layout.set_file(_file_info(source))
            assert _pump_until(
                lambda: layout._content_stack.currentWidget() is layout._html_view
            ), "html 视图未在超时窗口内出现"
            assert "T13 集成测试文档正文" in layout._html_view.toPlainText()
            worker = layout._current_worker
            assert isinstance(worker, OfficeConverterWorker)
            assert not worker.is_running()
        finally:
            layout.cleanup()
            _pump()

    def test_xlsx_real_openpyxl_conversion_to_table_view(
        self,
        qapp: Any,
        monkeypatch: pytest.MonkeyPatch,
        make_xlsx: Callable[[str], Path],
    ) -> None:
        """xlsx → 真实 openpyxl → TSV 表格视图（只读 QTableWidget）。"""
        _force_pure_python(monkeypatch)
        source = make_xlsx()
        layout = opl.OfficePreviewerLayout()
        try:
            layout.set_file(_file_info(source))
            assert _pump_until(
                lambda: layout._content_stack.currentWidget() is layout._table_view
            ), "table 视图未在超时窗口内出现"
            table = layout._table_view._table_widget
            assert table.rowCount() == 3
            assert table.columnCount() == 2
            assert table.item(1, 1).text() == "90"
            assert table.item(2, 0).text() == "Bob"
            worker = layout._current_worker
            assert isinstance(worker, OfficeConverterWorker)
            assert not worker.is_running()
        finally:
            layout.cleanup()
            _pump()


# =============================================================================
# PDF 产物路由 → 内嵌真实 PdfPreviewerLayout（新布局首批直接覆盖）
# =============================================================================


class TestPdfRoutingToEmbeddedPdfLayout:
    """PDF 负载（裸路径字符串）路由到内嵌 ``PdfPreviewerLayout``。"""

    def test_docx_pdf_payload_embeds_pdf_layout(
        self,
        qapp: Any,
        monkeypatch: pytest.MonkeyPatch,
        make_docx: Callable[[str], Path],
        make_pdf: Callable[[int, str], Path],
    ) -> None:
        """docx 的 PDF 产物 → 独立 PDF 视图，内嵌布局真实加载 2 页 PDF。"""
        source = make_docx()
        pdf_path = make_pdf(pages=2)
        _patch_convert_result(
            monkeypatch,
            ConversionResult(
                content_type="pdf",
                content=str(pdf_path),
                backend_used="com",
            ),
        )
        set_file_calls: list[str] = []
        real_set_file = pdf_mod.PdfPreviewerLayout.set_file

        def _spy_set_file(self: Any, file_path: str) -> bool:
            set_file_calls.append(str(file_path))
            return real_set_file(self, file_path)

        monkeypatch.setattr(
            pdf_mod.PdfPreviewerLayout, "set_file", _spy_set_file
        )

        layout = opl.OfficePreviewerLayout()
        try:
            layout.set_file(_file_info(source))
            assert _pump_until(
                lambda: layout._pdf is not None and bool(set_file_calls)
            ), "PDF 视图未在超时窗口内出现"
            assert layout._content_stack.currentWidget() is layout._pdf_holder
            # 负载是裸路径（worker._encode_content 对 pdf 不添加前缀）
            assert set_file_calls == [str(pdf_path)]
            # 真实 set_file 已加载文档（非 fake）
            assert layout._pdf._renderer._doc is not None
            assert layout._pdf._renderer.page_count() == 2
            worker = layout._current_worker
            assert isinstance(worker, OfficeConverterWorker)
            assert not worker.is_running()
        finally:
            _pump_for(400)  # 让 set_file 调度的 QTimer 在存活期间触发
            layout.cleanup()
            _pump()

    def test_xlsx_pdf_payload_goes_to_table_tab(
        self,
        qapp: Any,
        monkeypatch: pytest.MonkeyPatch,
        make_xlsx: Callable[[str], Path],
        make_pdf: Callable[[int, str], Path],
    ) -> None:
        """xlsx 的 PDF 产物 → 表格面板（_XlsxTableView）的 PDF 标签页。"""
        source = make_xlsx()
        pdf_path = make_pdf(pages=1)
        _patch_convert_result(
            monkeypatch,
            ConversionResult(
                content_type="pdf",
                content=str(pdf_path),
                backend_used="com",
            ),
        )
        set_file_calls: list[str] = []
        real_set_file = pdf_mod.PdfPreviewerLayout.set_file

        def _spy_set_file(self: Any, file_path: str) -> bool:
            set_file_calls.append(str(file_path))
            return real_set_file(self, file_path)

        monkeypatch.setattr(
            pdf_mod.PdfPreviewerLayout, "set_file", _spy_set_file
        )

        layout = opl.OfficePreviewerLayout()
        try:
            layout.set_file(_file_info(source))
            assert _pump_until(
                lambda: layout._table_view._pdf is not None and bool(set_file_calls)
            ), "表格面板 PDF 标签页未在超时窗口内出现"
            assert layout._content_stack.currentWidget() is layout._table_view
            assert set_file_calls == [str(pdf_path)]
            # 默认停在「PDF」标签（index 0）
            assert layout._table_view.currentIndex() == 0
            assert layout._table_view._pdf._renderer._doc is not None
            assert layout._table_view._pdf._renderer.page_count() == 1
        finally:
            _pump_for(400)
            layout.cleanup()
            _pump()


# =============================================================================
# 失败路径（failed 信号 → 错误视图）
# =============================================================================


class TestFailurePath:
    """转换返回错误 / 无可用后端 → ``failed`` → 错误视图。"""

    def test_error_result_routes_to_error_view(
        self,
        qapp: Any,
        monkeypatch: pytest.MonkeyPatch,
        make_docx: Callable[[str], Path],
    ) -> None:
        """conversion 返回 ``content_type="error"`` → 错误视图显示 message。"""
        source = make_docx()
        _patch_convert_result(
            monkeypatch,
            ConversionResult(
                content_type="error",
                content="",
                backend_used="error",
                message="T13 模拟转换失败",
            ),
        )
        layout = opl.OfficePreviewerLayout()
        try:
            layout.set_file(_file_info(source))
            assert _pump_until(
                lambda: layout._content_stack.currentWidget() is layout._error_view
            ), "错误视图未在超时窗口内出现"
            assert "T13 模拟转换失败" in layout._error_view.text()
            worker = layout._current_worker
            assert isinstance(worker, OfficeConverterWorker)
            assert not worker.is_running()
        finally:
            layout.cleanup()
            _pump()

    def test_legacy_doc_no_backend_shows_error_view(
        self,
        qapp: Any,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """legacy doc 无 LO/COM 后端：真实分派 → 安装提示错误视图。

        legacy 格式（doc/xls/ppt）的允许后端只有 LO 与 COM；两探针均 patch 成
        False 后真实 ``convert()`` 走到 ``_error_backend``，经 ``failed`` 信号
        显示安装提示（Metis E6 契约）。
        """
        _force_pure_python(monkeypatch)
        source = tmp_path / "legacy.doc"
        source.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1 T13 fake doc")
        layout = opl.OfficePreviewerLayout()
        try:
            layout.set_file(_file_info(source))
            assert _pump_until(
                lambda: layout._content_stack.currentWidget() is layout._error_view
            ), "错误视图未在超时窗口内出现"
            assert (
                "请安装 LibreOffice 或 Microsoft Office/WPS"
                in layout._error_view.text()
            )
            worker = layout._current_worker
            assert isinstance(worker, OfficeConverterWorker)
            assert not worker.is_running()
        finally:
            layout.cleanup()
            _pump()


# =============================================================================
# 同实例重分派（Metis B5）—— 真实线程下 generation guard
# =============================================================================


class TestRedispatchWithRealWorker:
    """真实 QThread 下同实例重分派：在途 worker 被取消，迟到信号被丢弃。"""

    def test_inflight_worker_cancelled_and_stale_signal_dropped(
        self,
        qapp: Any,
        monkeypatch: pytest.MonkeyPatch,
        make_docx: Callable[[str], Path],
        make_xlsx: Callable[[str], Path],
        make_pdf: Callable[[int, str], Path],
    ) -> None:
        """set_file(docx) 后在途时 set_file(xlsx)：旧 worker 取消、旧信号丢弃。"""
        pdf_path = make_pdf(pages=1)
        _patch_convert_slow(
            monkeypatch,
            lambda file_info: ConversionResult(
                content_type="pdf",
                content=str(pdf_path),
                backend_used="com",
            ),
            delay=1.0,
        )
        set_file_calls: list[str] = []
        real_set_file = pdf_mod.PdfPreviewerLayout.set_file

        def _spy_set_file(self: Any, file_path: str) -> bool:
            set_file_calls.append(str(file_path))
            return real_set_file(self, file_path)

        monkeypatch.setattr(
            pdf_mod.PdfPreviewerLayout, "set_file", _spy_set_file
        )

        docx_src = make_docx()
        xlsx_src = make_xlsx()
        layout = opl.OfficePreviewerLayout()
        try:
            layout.set_file(_file_info(docx_src))
            worker1 = layout._current_worker
            assert worker1 is not None
            # worker1 仍在转换（convert 慢速 1s）时立即重分派
            layout.set_file(_file_info(xlsx_src))
            worker2 = layout._current_worker
            assert worker2 is not None and worker2 is not worker1
            # 旧 worker 已被 cancel + wait 回收
            assert worker1._cancel_requested is True
            assert not worker1.is_running()
            assert layout._content_stack.currentWidget() is layout._overlay

            # 等待 worker2 的 PDF 结果路由
            assert _pump_until(
                lambda: layout._content_stack.currentWidget()
                is layout._table_view
                and bool(set_file_calls)
            ), "worker2 的 PDF 结果未在超时窗口内路由"
            # 只有 worker2 的负载落地（worker1 迟到信号被 generation guard 丢弃）
            assert set_file_calls == [str(pdf_path)]
            assert layout._table_view._pdf is not None
            # worker1 的 failed(已取消) 也未污染视图
            assert layout._error_view.text() == ""
        finally:
            _pump_for(400)
            layout.cleanup()
            _pump()


# =============================================================================
# cleanup() 契约（Metis B4）
# =============================================================================


class TestCleanupContract:
    """cleanup() 必须触达内嵌 PDF 布局的 cleanup，且幂等安全。"""

    def test_cleanup_reaches_both_embedded_pdf_cleanups(
        self,
        qapp: Any,
        monkeypatch: pytest.MonkeyPatch,
        make_docx: Callable[[str], Path],
        make_xlsx: Callable[[str], Path],
        make_pdf: Callable[[int, str], Path],
    ) -> None:
        """cleanup() 同时触达 ``_pdf`` 与 ``_table_view._pdf`` 的 cleanup。"""
        pdf_path = make_pdf(pages=1)
        _patch_convert_result(
            monkeypatch,
            ConversionResult(
                content_type="pdf",
                content=str(pdf_path),
                backend_used="com",
            ),
        )
        cleaned: list[Any] = []
        real_cleanup = pdf_mod.PdfPreviewerLayout.cleanup

        def _spy_cleanup(self: Any) -> None:
            cleaned.append(self)
            real_cleanup(self)

        monkeypatch.setattr(
            pdf_mod.PdfPreviewerLayout, "cleanup", _spy_cleanup
        )

        docx_src = make_docx()
        xlsx_src = make_xlsx()
        layout = opl.OfficePreviewerLayout()
        try:
            layout.set_file(_file_info(docx_src))
            assert _pump_until(
                lambda: layout._pdf is not None
                and layout._pdf._renderer._doc is not None
            ), "独立 PDF 视图未在超时窗口内加载"
            layout.set_file(_file_info(xlsx_src))
            assert _pump_until(
                lambda: layout._table_view._pdf is not None
                and layout._table_view._pdf._renderer._doc is not None
            ), "表格面板 PDF 未在超时窗口内加载"

            embedded_ids = {
                id(layout._pdf),
                id(layout._table_view._pdf),
            }
            layout.cleanup()
            # 两个内嵌实例的 cleanup 都被触达（退出全屏，防 dangling pointer）
            assert {id(widget) for widget in cleaned} == embedded_ids
            # 幂等：二次调用不抛异常
            layout.cleanup()
        finally:
            _pump_for(400)
            layout.cleanup()
            _pump()

    def test_cleanup_after_completed_conversion_is_safe_and_idempotent(
        self,
        qapp: Any,
        monkeypatch: pytest.MonkeyPatch,
        make_xlsx: Callable[[str], Path],
    ) -> None:
        """纯转换完成后 cleanup 安全且幂等（两次调用无异常）。"""
        _force_pure_python(monkeypatch)
        source = make_xlsx()
        layout = opl.OfficePreviewerLayout()
        try:
            layout.set_file(_file_info(source))
            assert _pump_until(
                lambda: layout._content_stack.currentWidget() is layout._table_view
            ), "table 视图未在超时窗口内出现"
            worker = layout._current_worker
            assert isinstance(worker, OfficeConverterWorker)
            layout.cleanup()
            layout.cleanup()
            assert not worker.is_running()
        finally:
            layout.cleanup()
            _pump()
