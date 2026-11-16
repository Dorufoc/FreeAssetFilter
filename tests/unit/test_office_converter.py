"""Office 转换服务单元测试。

覆盖本次修复的关键契约：
- PowerPoint 使用 ``SaveAs(路径, 32)``（原可用路径），无窗口失败时以
  “有窗口 + 最小化”重试；
- ``Presentation.Close`` 不带参数；
- 零幻灯片 pptx 在分派前被离线拦截，绝不拉起 PowerPoint；
- COM 异常被格式化为可复制的 HRESULT / 来源 / 描述；
- 外部后端失败后继续尝试纯 Python 后端；
- PowerShell 孤儿清理使用隐藏窗口参数（Windows）。
"""

from __future__ import annotations

import os
import subprocess
import sys
import types
import zipfile
from datetime import datetime
from pathlib import Path

import pytest

from sopeek.services.office_converter import ConversionResult, OfficeConverter


class _FakePresentation:
    """最小 PowerPoint Presentation 替身。"""

    def __init__(self, *, fail_save_count: int = 0) -> None:
        self.fail_save_count = fail_save_count
        self.save_calls: list[tuple[str, int]] = []
        self.export_calls: list[tuple[str, int]] = []
        self.close_calls: list[tuple[tuple, dict]] = []

    def SaveAs(self, path: str, file_format: int) -> None:
        self.save_calls.append((path, file_format))
        if self.fail_save_count > 0:
            self.fail_save_count -= 1
            raise Exception(
                -2147352567,
                "发生意外。",
                (
                    0,
                    "Microsoft PowerPoint",
                    "Presentation.SaveAs : PowerPoint 储存此文件时发生错误。",
                    "",
                    0,
                    -2147467259,
                ),
                None,
            )
        Path(path).write_bytes(b"%PDF-1.4\n")

    def ExportAsFixedFormat(self, path: str, fixed_format_type: int) -> None:
        self.export_calls.append((path, fixed_format_type))
        raise AssertionError("当前实现不应调用 ExportAsFixedFormat")

    def Close(self, *args, **kwargs) -> None:
        self.close_calls.append((args, kwargs))
        if args or kwargs:
            raise TypeError("Presentation.Close() takes no arguments")


class _FakePresentations:
    def __init__(self, presentations: list[_FakePresentation], opened: list) -> None:
        self._presentations = presentations
        self._opened = opened

    def Open(self, path: str, **kwargs):
        self._opened.append((path, kwargs))
        if not self._presentations:
            raise AssertionError("没有更多 Presentation 替身")
        return self._presentations.pop(0)


class _FakeApp:
    """最小 PowerPoint Application 替身。"""

    def __init__(self, presentations: list[_FakePresentation]) -> None:
        self._presentations = presentations
        self.opened: list[tuple[str, dict]] = []
        self.quit_called = False
        self.Visible = True
        self.DisplayAlerts = None
        self.WindowState = None
        self.AutomationSecurity = None

    @property
    def Presentations(self) -> _FakePresentations:
        return _FakePresentations(self._presentations, self.opened)

    def Quit(self) -> None:
        self.quit_called = True


def _install_fake_win32com(
    monkeypatch: pytest.MonkeyPatch,
    app: _FakeApp,
) -> None:
    """把 ``win32com.client`` 替换为返回 *app* 的假模块。"""
    client = types.ModuleType("win32com.client")
    client.DispatchEx = lambda prog_id: app
    client.Dispatch = lambda prog_id: app
    win32com = types.ModuleType("win32com")
    win32com.__path__ = []  # 让 import win32com.client 把它当包处理
    win32com.client = client
    monkeypatch.setitem(sys.modules, "win32com", win32com)
    monkeypatch.setitem(sys.modules, "win32com.client", client)


@pytest.fixture()
def no_orphan_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    """阻止测试触发真实 PowerShell。"""
    monkeypatch.setattr(
        OfficeConverter,
        "_cleanup_orphan_processes",
        staticmethod(lambda *args, **kwargs: None),
    )


def test_format_com_error_extracts_hresult_and_description() -> None:
    exc = Exception(
        -2147352567,
        "发生意外。",
        (
            0,
            "Microsoft PowerPoint",
            "Presentation.SaveAs : PowerPoint 储存此文件时发生错误。",
            "",
            0,
            -2147467259,
        ),
        None,
    )

    detail = OfficeConverter._format_com_error(
        exc,
        stage="导出 PDF",
        source_path=r"C:\a.pptx",
        output_path=r"C:\out.pdf",
    )

    assert "HRESULT：0x80020009" in detail
    assert "内部错误码：0x80004005" in detail
    assert "来源：Microsoft PowerPoint" in detail
    assert "Presentation.SaveAs" in detail
    assert r"C:\a.pptx" in detail


def test_ppt_uses_save_as_pdf_and_parameterless_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    no_orphan_cleanup: None,
) -> None:
    source = tmp_path / "demo.pptx"
    source.write_bytes(b"fake pptx")
    presentation = _FakePresentation()
    app = _FakeApp([presentation])
    _install_fake_win32com(monkeypatch, app)

    result = OfficeConverter._com_convert_in_task(
        str(source), "pptx", datetime.now()
    )

    try:
        assert result.content_type == "pdf"
        assert result.backend_used == "com"
        assert presentation.save_calls, "必须调用 SaveAs"
        assert presentation.save_calls[0][1] == 32  # ppSaveAsPDF
        assert presentation.export_calls == []
        # PowerPoint Close 不接受参数；传 False 会静默失败
        assert presentation.close_calls == [((), {})]
        assert app.quit_called is True
        assert len(app.opened) == 1
        assert app.opened[0][1]["WithWindow"] is False
    finally:
        if result.content_type == "pdf":
            Path(result.content).unlink(missing_ok=True)


def test_ppt_retries_with_window_when_windowless_save_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    no_orphan_cleanup: None,
) -> None:
    source = tmp_path / "demo.pptx"
    source.write_bytes(b"fake pptx")
    first = _FakePresentation(fail_save_count=1)
    second = _FakePresentation()
    app = _FakeApp([first, second])
    _install_fake_win32com(monkeypatch, app)

    result = OfficeConverter._com_convert_in_task(
        str(source), "pptx", datetime.now()
    )

    try:
        assert result.content_type == "pdf"
        assert len(app.opened) == 2
        assert app.opened[0][1]["WithWindow"] is False
        assert app.opened[1][1]["WithWindow"] is True
        assert first.save_calls and first.close_calls
        assert second.save_calls[0][1] == 32
    finally:
        if result.content_type == "pdf":
            Path(result.content).unlink(missing_ok=True)


def test_pptx_slide_count_reads_ooxml(tmp_path: Path) -> None:
    source = tmp_path / "two-slides.pptx"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr(
            "ppt/presentation.xml",
            (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<p:presentation xmlns:p="http://schemas.openxmlformats.org/'
                'presentationml/2006/main"><p:sldIdLst>'
                '<p:sldId id="256" r:id="rId2" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/'
                '2006/relationships"/>'
                '<p:sldId id="257" r:id="rId3" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/'
                '2006/relationships"/>'
                "</p:sldIdLst></p:presentation>"
            ),
        )

    assert OfficeConverter._pptx_slide_count(str(source)) == 2


def test_pptx_slide_count_returns_none_for_invalid_file(tmp_path: Path) -> None:
    source = tmp_path / "not-a-zip.pptx"
    source.write_bytes(b"not a zip")

    assert OfficeConverter._pptx_slide_count(str(source)) is None


def test_ppt_failure_report_keeps_both_save_attempts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    no_orphan_cleanup: None,
) -> None:
    source = tmp_path / "demo.pptx"
    source.write_bytes(b"fake pptx")
    first = _FakePresentation(fail_save_count=1)
    second = _FakePresentation(fail_save_count=1)
    app = _FakeApp([first, second])
    _install_fake_win32com(monkeypatch, app)

    result = OfficeConverter._com_convert_in_task(
        str(source), "pptx", datetime.now()
    )

    assert result.content_type == "error"
    assert result.failed_backend == "com"
    assert "无窗口 SaveAs 失败" in result.detail
    assert "Presentation.SaveAs" in result.detail
    assert len(app.opened) == 2


def test_zero_slide_pptx_is_rejected_before_any_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """零幻灯片 pptx 不得拉起 PowerPoint / COM。"""
    source = tmp_path / "empty.pptx"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr(
            "ppt/presentation.xml",
            (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<p:presentation xmlns:p="http://schemas.openxmlformats.org/'
                'presentationml/2006/main"></p:presentation>'
            ),
        )

    monkeypatch.setattr(
        OfficeConverter,
        "_maybe_cleanup_cache",
        classmethod(lambda cls: None),
    )
    monkeypatch.setattr(
        OfficeConverter,
        "_get_cache_path_safe",
        staticmethod(lambda file_info: None),
    )

    def fail_if_called(cls, backend, file_info, suffix):
        raise AssertionError(f"不应分派到后端 {backend}")

    monkeypatch.setattr(
        OfficeConverter,
        "_try_backend",
        classmethod(fail_if_called),
    )

    result = OfficeConverter.convert({"path": str(source), "suffix": "pptx"})

    assert result.content_type == "outline"
    assert result.content == "该演示文稿没有幻灯片。"
    assert result.backend_used == "pure-python"


def test_convert_falls_back_to_pure_python_after_external_backends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        OfficeConverter,
        "_maybe_cleanup_cache",
        classmethod(lambda cls: None),
    )
    monkeypatch.setattr(
        OfficeConverter,
        "_get_cache_path_safe",
        staticmethod(lambda file_info: None),
    )

    calls: list[str] = []

    def fake_try_backend(cls, backend, file_info, suffix):
        calls.append(backend)
        if backend == "pure-python":
            return ConversionResult(
                content_type="outline",
                content="--- 第 1 页 ---\n标题",
                backend_used="pure-python",
            )
        return ConversionResult(
            content_type="error",
            content="",
            backend_used="error",
            message=f"{backend} failed",
            detail=f"{backend} detail",
            failed_backend=backend,
        )

    monkeypatch.setattr(
        OfficeConverter,
        "_try_backend",
        classmethod(fake_try_backend),
    )

    result = OfficeConverter.convert({"path": "a.pptx", "suffix": "pptx"})

    assert calls == ["com", "libreoffice", "pure-python"]
    assert result.content_type == "outline"
    assert result.backend_used == "pure-python"


def test_convert_aggregates_all_backend_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        OfficeConverter,
        "_maybe_cleanup_cache",
        classmethod(lambda cls: None),
    )
    monkeypatch.setattr(
        OfficeConverter,
        "_get_cache_path_safe",
        staticmethod(lambda file_info: None),
    )

    def fake_try_backend(cls, backend, file_info, suffix):
        return ConversionResult(
            content_type="error",
            content="",
            backend_used="error",
            message=f"{backend} failed",
            detail=f"{backend} detail",
            failed_backend=backend,
        )

    monkeypatch.setattr(
        OfficeConverter,
        "_try_backend",
        classmethod(fake_try_backend),
    )

    result = OfficeConverter.convert({"path": "a.pptx", "suffix": "pptx"})

    assert result.content_type == "error"
    assert result.message == "pure-python failed"
    assert "libreoffice detail" in result.detail
    assert "com detail" in result.detail
    assert "pure-python detail" in result.detail


def test_dispatch_office_app_prefers_dispatch_ex() -> None:
    class Client:
        def __init__(self) -> None:
            self.ex_calls: list[str] = []
            self.dispatch_calls: list[str] = []

        def DispatchEx(self, prog_id: str) -> str:
            self.ex_calls.append(prog_id)
            return "dispatch-ex"

        def Dispatch(self, prog_id: str) -> str:
            self.dispatch_calls.append(prog_id)
            return "dispatch"

    client = Client()
    assert (
        OfficeConverter._dispatch_office_app(client, "PowerPoint.Application")
        == "dispatch-ex"
    )
    assert client.ex_calls == ["PowerPoint.Application"]
    assert client.dispatch_calls == []


def test_dispatch_office_app_falls_back_to_dispatch() -> None:
    class Client:
        def DispatchEx(self, prog_id: str) -> str:
            raise RuntimeError("not supported")

        def Dispatch(self, prog_id: str) -> str:
            return "dispatch"

    assert (
        OfficeConverter._dispatch_office_app(Client(), "Kwpp.Application")
        == "dispatch"
    )


def test_safe_output_stem_sanitizes_and_truncates() -> None:
    stem = OfficeConverter._safe_output_stem(
        'a<b>c:d"e|f?g*' + "h" * 80 + ".pptx"
    )
    assert len(stem) <= 40
    for illegal in '<>:"|?*':
        assert illegal not in stem


@pytest.fixture()
def openpyxl_module():
    """openpyxl 未安装时跳过 xlsx 降级测试。"""
    return pytest.importorskip("openpyxl")


def _save_xlsx(path: Path, builder) -> None:
    """用 openpyxl 创建测试工作簿并保存。"""
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    try:
        builder(workbook)
        workbook.save(path)
    finally:
        workbook.close()


def test_xlsx_pure_python_renders_html_table(
    tmp_path: Path,
    openpyxl_module,
) -> None:
    source = tmp_path / "data.xlsx"

    def build(workbook) -> None:
        sheet = workbook.active
        sheet.title = "Data"
        sheet.append(["Name", "Value"])
        sheet.append(["Alice", 42])

    _save_xlsx(source, build)

    result = OfficeConverter._pure_python_xlsx({"path": str(source)})

    assert result.content_type == "html"
    assert result.backend_used == "pure-python"
    assert "<table" in result.content
    assert "工作表：Data" in result.content
    assert "<th>Name</th>" in result.content
    assert "<td>Alice</td>" in result.content
    assert "<td>42</td>" in result.content


def test_xlsx_pure_python_multiple_sheets_and_escapes_html(
    tmp_path: Path,
    openpyxl_module,
) -> None:
    source = tmp_path / "multi.xlsx"

    def build(workbook) -> None:
        first = workbook.active
        first.title = "One"
        first["A1"] = "<script>&"
        second = workbook.create_sheet("Two")
        second["A1"] = "second"

    _save_xlsx(source, build)

    result = OfficeConverter._pure_python_xlsx({"path": str(source)})

    assert result.content_type == "html"
    assert "工作表：One" in result.content
    assert "工作表：Two" in result.content
    assert "&lt;script&gt;&amp;" in result.content
    assert "<script>" not in result.content
    assert "second" in result.content


def test_xlsx_pure_python_truncates_large_sheet(
    tmp_path: Path,
    openpyxl_module,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "large.xlsx"

    def build(workbook) -> None:
        sheet = workbook.active
        for row in range(1, 6):
            sheet.append([f"r{row}c{col}" for col in range(1, 6)])

    _save_xlsx(source, build)

    monkeypatch.setattr(
        "sopeek.services.office_converter.XLSX_MAX_PREVIEW_ROWS",
        2,
    )
    monkeypatch.setattr(
        "sopeek.services.office_converter.XLSX_MAX_PREVIEW_COLS",
        2,
    )

    result = OfficeConverter._pure_python_xlsx({"path": str(source)})

    assert result.content_type == "html"
    assert "仅显示前 2 行 × 2 列" in result.content
    assert "r1c1" in result.content
    assert "r3c1" not in result.content
    assert "r1c3" not in result.content


def test_xlsx_pure_python_empty_workbook(
    tmp_path: Path,
    openpyxl_module,
) -> None:
    source = tmp_path / "empty.xlsx"
    _save_xlsx(source, lambda workbook: None)

    result = OfficeConverter._pure_python_xlsx({"path": str(source)})

    assert result.content_type == "html"
    assert "（空工作表）" in result.content


def test_xlsx_pure_python_missing_openpyxl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "missing.xlsx"
    source.write_bytes(b"not a real xlsx")
    monkeypatch.setitem(sys.modules, "openpyxl", None)

    result = OfficeConverter._pure_python_xlsx({"path": str(source)})

    assert result.content_type == "error"
    assert result.failed_backend == "pure-python"
    assert "openpyxl" in result.message


def test_xlsx_dispatches_to_pure_python_html(
    tmp_path: Path,
    openpyxl_module,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "fallback.xlsx"

    def build(workbook) -> None:
        sheet = workbook.active
        sheet.title = "Fallback"
        sheet.append(["A", "B"])
        sheet.append([1, 2])

    _save_xlsx(source, build)

    monkeypatch.setattr(
        OfficeConverter,
        "_maybe_cleanup_cache",
        classmethod(lambda cls: None),
    )
    monkeypatch.setattr(
        OfficeConverter,
        "_get_cache_path_safe",
        staticmethod(lambda file_info: None),
    )
    monkeypatch.setattr(
        OfficeConverter,
        "_soffice_available",
        classmethod(lambda cls: False),
    )
    monkeypatch.setattr(
        OfficeConverter,
        "_com_available",
        classmethod(lambda cls, suffix="": False),
    )

    result = OfficeConverter.convert({"path": str(source), "suffix": "xlsx"})

    assert result.content_type == "html"
    assert result.backend_used == "pure-python"
    assert "工作表：Fallback" in result.content


@pytest.mark.skipif(os.name != "nt", reason="Windows 子进程窗口测试")
def test_orphan_cleanup_uses_hidden_powershell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(
        "sopeek.services.office_converter.subprocess.run",
        fake_run,
    )

    OfficeConverter._cleanup_orphan_processes(datetime.now())

    assert "powershell" in captured["args"][0].lower()
    expected_flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert expected_flags
    assert int(captured.get("creationflags", 0)) & expected_flags
    startupinfo = captured.get("startupinfo")
    assert startupinfo is not None
    assert startupinfo.wShowWindow == subprocess.SW_HIDE
