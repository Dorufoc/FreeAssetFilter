# -*- coding: utf-8 -*-
"""
OfficePreviewerLayout（T10）单元测试

通过注入可控的 ``FakeOfficeWorker``（取代 ``OfficeConverterWorker``）验证布局的
**编排**职责（TDD：patched Worker 按需手动发射 ``converted`` / ``failed``），
覆盖：

- 构造契约：宿主以 ``parent`` 单参数调用；所有参数有默认值；``settings_manager``
  为 None 时懒解析（Metis B9）
- 视图路由：pdf 负载 → 内嵌 PdfPreviewerLayout；html → QTextBrowser；
  outline → 文本浏览器；table → 只读表格（sheet 标签页）；failed → 错误视图
- 同实例重分派（Metis B5/E5）：``set_file(docx)`` 后 ``set_file(xlsx)`` 复用同一
  实例，旧 worker 被取消、无残留运行引用；过期信号的 generation guard 生效
- cleanup() 契约（Metis B4）：在途 worker 被 cancel+wait；内嵌 pdf.cleanup() 被
  调用（退出全屏）；可安全调用两次
- >5000 行表格显示「已截断」（table 负载为该约定时的截断提示）
- 6 后缀在无任何后端时对应降级视图可实例化（E6，经 fake worker 的
  ``converted("html:...")`` / ``failed(...)`` 等负载驱动）

所有测试无真实显示依赖（qapp 会话 fixture + offscreen）。fake 同步发射信号，
因此 QSignalSpy.wait() 不可靠的问题在这里不涉及；仍提供 ``_pump`` 辅助。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QTabWidget, QTableWidget, QWidget

# 模块导入（含 sys.path 引导）
from freeassetfilter.ui.layout.preview import office_previewer_layout as opl
from freeassetfilter.ui.layout.preview import pdf_previewer_layout as pdf_mod


# =============================================================================
# Fakes —— patched 的 Worker / PdfPreviewerLayout
# =============================================================================


class FakeOfficeWorker(QObject):
    """``OfficeConverterWorker`` 的可控替身：信号按需手动发射，全部同步。"""

    converted = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        file_info: dict,
        timeout: float | None = None,  # noqa: ARG002
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self.file_info: dict = file_info
        self._running: bool = False
        self.cancel_calls: int = 0
        self.cleanup_calls: int = 0
        self.pending: list[str] = []

    # -- OfficeConverterWorker 公共 API 镜像 ----------------------------------
    def start(self, *args: Any, **kwargs: Any) -> None:
        """镜像 start：把待发负载立即同步发射（单线程 fake）。"""
        self._running = True
        if self.pending:
            for payload in self.pending:
                if payload.startswith("err:"):
                    self.failed.emit(payload[4:])
                else:
                    self.converted.emit(payload)
            self.pending.clear()
            self._running = False

    def is_running(self) -> bool:
        """线程是否仍在运行。"""
        return self._running

    def isRunning(self) -> bool:  # noqa: N802
        """Qt 兼容：线程是否仍在运行。"""
        return self._running

    def request_cancel(self) -> None:
        """镜像 request_cancel：同步结束线程。"""
        self.cancel_calls += 1
        self._running = False

    def wait(self, timeout_ms: int = 3000) -> bool:  # noqa: ARG002
        """镜像 wait：fake 线程总是已结束。"""
        return not self._running

    def cleanup(self, wait_ms: int = 3000) -> None:  # noqa: ARG002
        """镜像 cleanup：cancel + 标记已回收。"""
        self.cleanup_calls += 1
        if self._running:
            self.request_cancel()

    # -- 测试补强 -------------------------------------------------------------
    def emit_converted(self, payload: str) -> None:
        """手动发射 converted 负载。"""
        self._running = True
        self.converted.emit(payload)
        self._running = False

    def emit_failed(self, msg: str) -> None:
        """手动发射 failed 消息。"""
        self._running = True
        self.failed.emit(msg)
        self._running = False


class FakePdfLayout(QWidget):
    """``PdfPreviewerLayout`` 替身（避免触发 fitz/NativePdfRenderer）。"""

    def __init__(self, parent: Any = None, **kwargs: Any) -> None:  # noqa: ARG002
        super().__init__(parent)
        self.set_file_calls: list[str] = []
        self.cleanup_calls: int = 0

    def set_file(self, file_path: str) -> bool:
        """记录 pdf 路径。"""
        self.set_file_calls.append(file_path)
        return True

    def cleanup(self) -> None:
        """记录 cleanup（退出全屏）。"""
        self.cleanup_calls += 1


@pytest.fixture(autouse=True)
def _inject_fakes(qapp, monkeypatch):
    """把 layout 模块内的 Worker / PdfPreviewerLayout 替换为 fakes。"""
    monkeypatch.setattr(opl, "OfficeConverterWorker", FakeOfficeWorker)
    monkeypatch.setattr(pdf_mod, "PdfPreviewerLayout", FakePdfLayout)
    yield


def _pump(ms: int = 60) -> None:
    """pump Qt 事件循环（同步 fake 下仅作保险）。"""
    app = QApplication.instance()
    if app is not None:
        app.processEvents()


def _make_suffix_file_info(suffix: str, path: str = "") -> dict:
    return {"suffix": suffix, "path": path or f"C:/dummy/sample.{suffix}"}


# =============================================================================
# 构造契约（Metis B9）
# =============================================================================


class TestConstruct:
    def test_parent_only_construct(self, qapp):
        """宿主以 ``OfficePreviewerLayout(parent)`` 单参数构造。"""
        host = QWidget()
        layout = opl.OfficePreviewerLayout(host)
        assert layout.parent() is host
        layout.cleanup()
        host.deleteLater()
        _pump()

    def test_all_params_have_defaults(self, qapp):
        """无参构造可用，settings_manager 走懒解析。"""
        layout = opl.OfficePreviewerLayout()
        assert layout._settings_manager is None
        layout.cleanup()
        _pump()

    def test_settings_manager_injected_kept(self, qapp):
        """显式传入 settings_manager 时原样保留。"""
        settings = object()
        layout = opl.OfficePreviewerLayout(settings_manager=settings)
        assert layout._settings_manager is settings
        layout.cleanup()
        _pump()


# =============================================================================
# 宿主 str 调用契约（unified_previewer_layout.py:361-363 set_file(file_path)）
# =============================================================================


class TestHostStrContract:
    def test_set_file_str_path_does_not_raise(self, qapp):
        """宿主传 str 路径 → 不抛 AttributeError，worker 照常启动。"""
        layout = opl.OfficePreviewerLayout()
        layout.set_file("C:/fake/path/sample.docx")
        assert layout._current_worker is not None
        assert layout._current_suffix == "docx"
        layout.cleanup()
        _pump()

    def test_set_file_str_worker_receives_normalized_dict(self, qapp):
        """str 形态归一化为 {path, suffix} dict，保持小写后缀。"""
        layout = opl.OfficePreviewerLayout()
        layout.set_file("C:/FAKE/Report.XLSX")
        worker = layout._current_worker
        assert isinstance(worker, FakeOfficeWorker)
        assert worker.file_info == {"path": "C:/FAKE/Report.XLSX", "suffix": "xlsx"}
        layout.cleanup()
        _pump()

    def test_set_file_str_no_suffix_safe(self, qapp):
        """str 无扩展名 → suffix 为空，不抛异常。"""
        layout = opl.OfficePreviewerLayout()
        layout.set_file("C:/fake/path/README")
        assert layout._current_suffix == ""
        assert layout._current_worker is not None
        layout.cleanup()
        _pump()

    def test_set_file_non_dict_non_str_safe(self, qapp):
        """None 等非法输入 → 安全降级（suffix 空），不抛异常。"""
        layout = opl.OfficePreviewerLayout()
        layout.set_file(None)  # type: ignore[arg-type]
        assert layout._current_suffix == ""
        assert layout._current_worker is not None
        layout.cleanup()
        _pump()

    def test_set_file_str_via_host_flow_routes_suffix(self, qapp):
        """str 输入沿用 generation guard：stale 被丢、新结果生效。"""
        layout = opl.OfficePreviewerLayout()
        layout.set_file("C:/fake/path/a.docx")
        w1 = layout._current_worker
        layout.set_file("C:/fake/path/b.xlsx")
        w2 = layout._current_worker
        assert w2 is not None and w1 is not None and w2 is not w1
        assert layout._current_suffix == "xlsx"
        w1.emit_converted("html:<p>stale</p>")
        assert layout._content_stack.currentWidget() is layout._overlay
        w2.emit_converted("table:a\t1")
        assert layout._content_stack.currentWidget() is layout._table_view
        layout.cleanup()
        _pump()


# =============================================================================
# 视图路由 —— worker 信号 → 正确视图
# =============================================================================


class TestRouting:
    def _make(self, qapp):
        layout = opl.OfficePreviewerLayout()
        return layout

    def test_html_payload_routes_to_html_view(self, qapp, monkeypatch):
        reader_calls: list[Any] = []
        monkeypatch.setattr(opl, "OfficeConverterWorker", FakeOfficeWorker)
        layout = self._make(qapp)
        layout._html_view.setHtml = lambda html: reader_calls.append(html)
        layout.set_file(_make_suffix_file_info("docx"))
        worker = layout._current_worker
        assert isinstance(worker, FakeOfficeWorker)
        worker.emit_converted("html:<p>hello</p>")
        assert layout._content_stack.currentWidget() is layout._html_view
        assert reader_calls == ["<p>hello</p>"]
        layout.cleanup()

    def test_outline_payload_routes_to_outline_view(self, qapp):
        layout = self._make(qapp)
        layout.set_file(_make_suffix_file_info("pptx"))
        worker = layout._current_worker
        worker.emit_converted("outline:--- 第 1 页 ---\nTitle")
        assert layout._content_stack.currentWidget() is layout._outline_view
        assert layout._outline_view.toPlainText() == "--- 第 1 页 ---\nTitle"
        layout.cleanup()

    def test_failed_payload_routes_to_error_view(self, qapp):
        layout = self._make(qapp)
        layout.set_file(_make_suffix_file_info("doc"))
        worker = layout._current_worker
        worker.emit_failed("请安装 LibreOffice 或 Microsoft Office/WPS 以获得完整预览")
        assert layout._content_stack.currentWidget() is layout._error_view
        assert "请安装" in layout._error_view.text()
        layout.cleanup()

    def test_pdf_payload_routes_to_pdf_layout(self, qapp):
        layout = self._make(qapp)
        layout.set_file(_make_suffix_file_info("docx"))
        worker = layout._current_worker
        pdf_path = str(Path("C:/dummy/out.pdf"))
        worker.emit_converted(pdf_path)
        assert layout._content_stack.currentWidget() is layout._pdf_holder
        assert layout._pdf is not None
        assert layout._pdf.set_file_calls == [pdf_path]
        layout.cleanup()


# =============================================================================
# XLSX 表格视图（PDF/表格 切换 + 只读表格 + 截断提示）
# =============================================================================


class TestXlsxTableView:
    def test_table_payload_routes_to_table_view(self, qapp):
        layout = opl.OfficePreviewerLayout()
        layout.set_file(_make_suffix_file_info("xlsx"))
        worker = layout._current_worker
        tsv = "Name\tScore\nAlice\t90\nBob\t80"
        worker.emit_converted(f"table:{tsv}")
        assert layout._content_stack.currentWidget() is layout._table_view
        tab = layout._table_view
        assert isinstance(tab, QTabWidget)
        # 表格标签页的 QTableWidget 内容
        table = tab._table_widget
        assert isinstance(table, QTableWidget)
        assert table.rowCount() == 3
        assert table.columnCount() == 2
        assert table.item(0, 0).text() == "Name"
        assert table.item(1, 1).text() == "90"
        # 只读（禁编辑）
        assert table.editTriggers() != QTableWidget.EditTrigger.DoubleClicked
        layout.cleanup()
        _pump()

    def test_table_over_5000_rows_shows_truncated(self, qapp):
        """>5000 行 → 显示「已截断」提示。"""
        layout = opl.OfficePreviewerLayout()
        layout.set_file(_make_suffix_file_info("xlsx"))
        worker = layout._current_worker
        rows = ["\t".join([f"r{i}", str(i)]) for i in range(5000)]
        worker.emit_converted("table:" + "\n".join(rows))
        # 显示后可见（offscreen 环境需显式 show）
        layout.show()
        _pump()
        assert layout._table_view._truncated_label.isVisibleTo(layout)
        assert "已截断" in layout._table_view._truncated_label.text()
        # 表格只保留上限行数
        assert layout._table_view._table_widget.rowCount() == 5000
        layout.cleanup()
        _pump()

    def test_under_5000_rows_no_truncated(self, qapp):
        layout = opl.OfficePreviewerLayout()
        layout.set_file(_make_suffix_file_info("xlsx"))
        worker = layout._current_worker
        rows = ["a\t1", "b\t2", "c\t3"]
        worker.emit_converted("table:" + "\n".join(rows))
        layout.show()
        _pump()
        assert not layout._table_view._truncated_label.isVisibleTo(layout)
        layout.cleanup()
        _pump()

    def test_xlsx_pdf_payload_routes_to_table_tab(self, qapp):
        """xlsx 的 PDF 负载 → 表格面板的 PDF 标签页 + 内嵌 pdf.set_file。"""
        layout = opl.OfficePreviewerLayout()
        layout.set_file(_make_suffix_file_info("xlsx"))
        worker = layout._current_worker
        pdf_path = str(Path("C:/dummy/out.pdf"))
        worker.emit_converted(pdf_path)
        assert layout._content_stack.currentWidget() is layout._table_view
        pdf = layout._table_view._pdf
        assert pdf is not None
        assert pdf.set_file_calls == [pdf_path]
        # 切换到表格标签
        layout._table_view._switch_to_table()
        assert layout._table_view.currentIndex() == 1
        layout.cleanup()
        _pump()


# =============================================================================
# 同实例重分派（Metis B5/E5）—— generation guard / 无残留 worker
# =============================================================================


class TestRedispatch:
    def test_set_file_docx_then_xlsx_reuses_instance(self, qapp, monkeypatch):
        """同一实例 set_file(docx) 后 set_file(xlsx)：旧 worker 取消、无残留。"""
        layout = opl.OfficePreviewerLayout()
        workers: list[FakeOfficeWorker] = []

        class _TrackingWorker(FakeOfficeWorker):
            def __init__(self, file_info: dict, **kw: Any) -> None:
                super().__init__(file_info, **kw)
                workers.append(self)

        monkeypatch.setattr(opl, "OfficeConverterWorker", _TrackingWorker)
        layout.set_file(_make_suffix_file_info("docx"))
        w1 = workers[-1]
        # 模拟 docx 转换仍在途
        w1._running = True
        layout.set_file(_make_suffix_file_info("xlsx"))
        w2 = workers[-1]
        # 新 worker 已接管；旧 worker 被取消且无残留运行引用
        assert layout._current_worker is w2
        assert w1.cancel_calls == 1
        assert not w1.is_running()
        assert w1.cleanup_calls >= 1
        assert w2 is not w1
        # 视图已被重置为覆盖层（等待新结果）
        assert layout._content_stack.currentWidget() is layout._overlay

        # 过期负载（gen 不匹配）必须被忽略
        w1.emit_converted("html:<p>stale</p>")
        assert layout._content_stack.currentWidget() is layout._overlay

        w2.emit_converted("table:a\t1")
        assert layout._content_stack.currentWidget() is layout._table_view
        layout.cleanup()
        _pump()

    def test_stale_failed_after_redispatch_ignored(self, qapp, monkeypatch):
        """重分派后，旧 worker 的 failed 同样被 generation guard 丢弃。"""
        layout = opl.OfficePreviewerLayout()
        workers: list[FakeOfficeWorker] = []

        class _TrackingWorker(FakeOfficeWorker):
            def __init__(self, file_info: dict, **kw: Any) -> None:
                super().__init__(file_info, **kw)
                workers.append(self)

        monkeypatch.setattr(opl, "OfficeConverterWorker", _TrackingWorker)
        layout.set_file(_make_suffix_file_info("docx"))
        w1 = workers[-1]
        layout.set_file(_make_suffix_file_info("pptx"))
        w1.emit_failed("Office 转换已取消")
        # 无人接管视图：仍停留在 overlay（等待新结果）
        assert layout._content_stack.currentWidget() is layout._overlay
        assert layout._error_view.text() == ""
        layout.cleanup()
        _pump()


# =============================================================================
# cleanup() 契约（Metis B4）
# =============================================================================


class TestCleanup:
    def test_cleanup_cancels_running_worker(self, qapp):
        """worker 运行中调用 cleanup() → 之后 worker isRunning() 为 False。"""
        layout = opl.OfficePreviewerLayout()
        layout.set_file(_make_suffix_file_info("docx"))
        worker = layout._current_worker
        # 模拟 worker 仍在运行（pending 未发）
        assert isinstance(worker, FakeOfficeWorker)
        worker._running = True
        layout.cleanup()
        assert worker is not None
        assert worker.is_running() is False
        assert worker.cancel_calls >= 1
        _pump()

    def test_cleanup_calls_embedded_pdf_cleanup(self, qapp):
        """cleanup() 必须调用内嵌 pdf.cleanup()（退出全屏，防 dangling pointer）。"""
        layout = opl.OfficePreviewerLayout()
        layout._ensure_pdf()  # force lazily-created pdf
        assert layout._pdf is not None
        # 模板方法被替换为 fake（autouse fixture 替换了 PdfPreviewerLayout 方法）
        layout.cleanup()
        assert layout._pdf.cleanup_calls >= 1
        _pump()

    def test_cleanup_is_idempotent(self, qapp):
        """cleanup() 可安全调用两次，无异常。"""
        layout = opl.OfficePreviewerLayout()
        layout.set_file(_make_suffix_file_info("xlsx"))
        layout._current_worker.emit_converted("table:a\t1")
        layout.cleanup()
        layout.cleanup()
        _pump()


# =============================================================================
# 6 后缀在无后端可用时的降级视图实例化（E6）
# =============================================================================


class TestDegradedViews:
    @pytest.mark.parametrize(
        "suffix,payload,view_attr",
        [
            ("docx", "html:<p>docx html</p>", "_html_view"),
            ("pptx", "outline:page1", "_outline_view"),
            ("xlsx", "table:a\t1\nb\t2", "_table_view"),
            ("doc", "err:请安装 LibreOffice 或 Microsoft Office/WPS 以获得完整预览", "_error_view"),
            ("xls", "err:请安装 LibreOffice 或 Microsoft Office/WPS 以获得完整预览", "_error_view"),
            ("ppt", "err:请安装 LibreOffice 或 Microsoft Office/WPS 以获得完整预览", "_error_view"),
        ],
    )
    def test_each_suffix_degraded_view_instantiates(
        self, qapp, suffix: str, payload: str, view_attr: str
    ) -> None:
        """各后缀走降级路径：对应视图可实例化且被切换为当前。"""
        layout = opl.OfficePreviewerLayout()
        layout.set_file(_make_suffix_file_info(suffix))
        worker = layout._current_worker
        assert isinstance(worker, FakeOfficeWorker)
        if payload.startswith("err:"):
            worker.emit_failed(payload[4:])
        else:
            worker.emit_converted(payload)
        assert layout._content_stack.currentWidget() is getattr(layout, view_attr)
        layout.cleanup()
        _pump()