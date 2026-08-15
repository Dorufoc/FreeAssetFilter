#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OfficeConverter COM 后端（T6）单元测试

通过 mock 模拟 pythoncom / win32com.client / 能力探测，绝不启动真实
Office/WPS。验证：

- Metis A2 / E8 线程纪律：``_convert_with_com`` 内部为每次任务新建一个
  线程；``pythoncom.CoInitialize()`` 是该任务线程的第一条语句（用
  ``threading.get_ident()`` sentinel 断言它运行在任务线程而非调用线程），
  ``pythoncom.CoUninitialize()`` 放入 ``finally``（成功与失败路径均执行）。
- Metis C4 ProgID 顺序回退：MS Office ProgID 创建失败时按顺序尝试 WPS，
  仅顺序尝试，无任何 WPS 特判逻辑。
- 自动化设置：``DisplayAlerts=False``、``ReadOnly=True``（mock 断言）。
- 清理纪律：``app.Quit()`` 在 ``finally`` 中执行（即使导出抛异常）。
- 失败路径：全部 ProgID 创建失败 / pywin32 缺失 → 中文错误结果，绝不抛出。
- 无 Office/WPS 能力：能力探测不可用时返回安装提示错误后端。
"""

import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from freeassetfilter.services.office_converter import (
    ERROR_MESSAGE,
    ConversionResult,
    OfficeConverter,
)


def _make_file_info(suffix: str, path: str) -> dict:
    """构造与 PreviewerRegistry 契约一致且指向真实文件的 file_info。"""
    return {"path": path, "suffix": suffix, "is_dir": False}


def _write_pdf(created: list[Path]):
    """返回一个真实写出 PDF 产物的导出回调，并把产物路径记录到 *created*。"""

    def _do(output_path: object, *args: object, **kwargs: object) -> None:
        pdf_path = Path(str(output_path))
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(b"%PDF-1.4 fake")
        created.append(pdf_path)

    return _do


def _make_fake_office(suffix: str) -> tuple[MagicMock, MagicMock, list[Path]]:
    """按后缀构造可成功完成 COM 转换的假应用；导出时真实创建 PDF 文件。

    Returns
    -------
    tuple[MagicMock, MagicMock, list[Path]]
        ``(app, document, created)`` —— *app* ／ *document* 为 MagicMock，
        *created* 记录导出回调写出的 PDF 路径列表。
    """
    app = MagicMock()
    document = MagicMock()
    created: list[Path] = []

    if suffix in ("doc", "docx"):
        app.Documents.Open.return_value = document
        document.ExportAsFixedFormat.side_effect = (
            lambda out, fmt, *a, **k: _write_pdf(created)(out)
        )
    elif suffix in ("xls", "xlsx"):
        app.Workbooks.Open.return_value = document
        document.ActiveSheet.ExportAsFixedFormat.side_effect = (
            lambda fmt, out, *a, **k: _write_pdf(created)(out)
        )
    else:
        app.Presentations.Open.return_value = document
        document.SaveAs.side_effect = (
            lambda out, fmt, *a, **k: _write_pdf(created)(out)
        )

    return app, document, created


@pytest.fixture(autouse=True)
def _hermetic_com_environment(monkeypatch, tmp_path):
    """所有用例自动生效：隔离临时目录、屏蔽真实孤儿进程清理。

    - 输出 PDF 目录重定向到 ``tmp_path``；
    - ``_cleanup_orphan_processes`` 替换为 no-op，避免测试期真实调用
      powershell 杀进程（``raising=False``：failing-first 阶段该方法
      尚不存在时也能安全打桩）。
    """
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path / "tmp"))
    monkeypatch.setattr(
        OfficeConverter,
        "_cleanup_orphan_processes",
        lambda *a, **k: None,
        raising=False,
    )


@pytest.fixture
def office_source(tmp_path):
    """生成一个真实存在的假 Office 源文件，返回 (file_info, 源路径)。"""
    created: dict[str, str] = {}

    def _make(suffix: str) -> str:
        if suffix not in created:
            src = tmp_path / f"sample.{suffix}"
            src.write_bytes(b"fake office content")
            created[suffix] = str(src)
        return created[suffix]

    return _make


# ===========================================================================
# Metis A2 / E8：per-task 线程 + CoInitialize/CoUninitialize 纪律
# ===========================================================================


class TestThreadDiscipline:
    """``_convert_with_com`` 每次任务新建线程；CoInitialize 在该线程首句执行，
    CoUninitialize 放在 finally（成功与失败路径均执行）。"""

    def test_co_initialize_runs_on_task_thread_success(
        self, office_source
    ) -> None:
        """成功路径：CoInitialize 必须在任务线程执行（sentinel 断言），
        且 CoUninitialize 在同一个线程的 finally 执行。"""
        src = office_source("docx")
        app, _document, created = _make_fake_office("docx")
        init_idents: list[int] = []
        uninit_idents: list[int] = []
        main_ident = threading.get_ident()

        with (
            patch(
                "pythoncom.CoInitialize",
                side_effect=lambda *a, **k: init_idents.append(
                    threading.get_ident()
                ),
            ),
            patch(
                "pythoncom.CoUninitialize",
                side_effect=lambda *a, **k: uninit_idents.append(
                    threading.get_ident()
                ),
            ),
            patch("win32com.client.Dispatch", return_value=app),
        ):
            result = OfficeConverter._convert_with_com(
                _make_file_info("docx", src), "docx"
            )

        assert isinstance(result, ConversionResult)
        assert result.backend_used == "com"
        assert created, "COM 导出回调应被调用并生成 PDF"
        assert result.content == created[0]
        assert result.content.is_file()
        assert init_idents, "CoInitialize 必须被调用"
        assert len(init_idents) == 1, "每次任务应恰好初始化一次 COM"
        assert (
            init_idents[0] != main_ident
        ), "CoInitialize 必须运行在任务线程，而不是调用线程"
        assert set(uninit_idents) == set(init_idents), (
            "CoUninitialize 必须与 CoInitialize 在同一个任务线程执行"
        )

    def test_co_uninitialize_in_finally_on_failure_path(self, office_source) -> None:
        """失败路径（所有 ProgID 创建失败）：CoUninitialize 仍必须在 finally 执行。"""
        src = office_source("docx")
        uninit_idents: list[int] = []

        with (
            patch("pythoncom.CoInitialize", return_value=0),
            patch(
                "pythoncom.CoUninitialize",
                side_effect=lambda *a, **k: uninit_idents.append(
                    threading.get_ident()
                ),
            ),
            patch("win32com.client.Dispatch", side_effect=OSError("no office")),
        ):
            result = OfficeConverter._convert_with_com(
                _make_file_info("docx", src), "docx"
            )

        assert result.backend_used == "error"
        assert result.content_type == "error"
        assert result.message, "错误结果应携带中文说明"
        assert len(uninit_idents) == 1, "失败路径也必须执行 CoUninitialize（Metis E8）"
        assert uninit_idents[0] != threading.get_ident(), (
            "CoUninitialize 必须运行在任务线程，而不是调用线程"
        )


# ===========================================================================
# Metis C4：ProgID 顺序尝试（MS Office → WPS），无 WPS 特判
# ===========================================================================


class TestProgIdOrder:
    """按后缀顺序尝试 MS Office ProgID，失败再尝试 WPS ProgID。"""

    def test_word_fails_falls_back_to_kwps(self, office_source) -> None:
        """Word.Application 创建失败 → 顺序回退到 Kwps.Application（WPS）。"""
        src = office_source("docx")
        app, _document, created = _make_fake_office("docx")
        dispatch_calls: list[str] = []

        def _fake_dispatch(prog_id: str) -> MagicMock:
            dispatch_calls.append(prog_id)
            if prog_id == "Word.Application":
                raise OSError("MS Word unavailable")
            return app

        with (
            patch("pythoncom.CoInitialize", return_value=0),
            patch("pythoncom.CoUninitialize"),
            patch("win32com.client.Dispatch", side_effect=_fake_dispatch),
        ):
            result = OfficeConverter._convert_with_com(
                _make_file_info("docx", src), "docx"
            )

        assert dispatch_calls == [
            "Word.Application",
            "Kwps.Application",
        ], "必须按 MS Office → WPS 的顺序尝试 ProgID"
        assert result.backend_used == "com"
        assert result.content_type == "pdf"
        assert created, "WPS 兜底路径应完成转换"
        assert result.content == created[0]
        app.Quit.assert_called_once()


# ===========================================================================
# 自动化设置：DisplayAlerts=False、ReadOnly=True
# ===========================================================================


class TestAutomationSettings:
    """自动化设置断言（mock）：DisplayAlerts=False、ReadOnly=True 打开文档。"""

    def test_word_display_alerts_off_and_read_only_open(self, office_source) -> None:
        """Word 家族：DisplayAlerts=False、Visible=False，Documents.Open 只读。"""
        src = office_source("docx")
        app, document, created = _make_fake_office("docx")

        with (
            patch("pythoncom.CoInitialize", return_value=0),
            patch("pythoncom.CoUninitialize"),
            patch("win32com.client.Dispatch", return_value=app),
        ):
            result = OfficeConverter._convert_with_com(
                _make_file_info("docx", src), "docx"
            )

        assert result.backend_used == "com"
        assert app.DisplayAlerts is False
        assert app.Visible is False
        app.Documents.Open.assert_called_once_with(src, ReadOnly=True)
        document.Close.assert_called_once_with(False)

    def test_excel_display_alerts_off_and_read_only_open(self, office_source) -> None:
        """Excel 家族：DisplayAlerts=False、Visible=False（Excel 允许隐藏），
        Workbooks.Open 只读且不更新链接。"""
        src = office_source("xlsx")
        app, _document, created = _make_fake_office("xlsx")

        with (
            patch("pythoncom.CoInitialize", return_value=0),
            patch("pythoncom.CoUninitialize"),
            patch("win32com.client.Dispatch", return_value=app),
        ):
            result = OfficeConverter._convert_with_com(
                _make_file_info("xlsx", src), "xlsx"
            )

        assert result.backend_used == "com"
        assert app.DisplayAlerts is False
        assert app.Visible is False, "Excel 允许隐藏主窗口，应保持 Visible=False"
        app.Workbooks.Open.assert_called_once_with(
            src, ReadOnly=True, UpdateLinks=0
        )

    def test_pptx_saves_as_pdf_format_32(self, office_source) -> None:
        """PowerPoint 家族：Presentations.Open 只读无窗口，SaveAs(路径, 32)。

        回归断言（F3 真实 QA 缺陷）：
        1. PowerPoint 禁止 ``app.Visible=False``（COM 异常 -2147352567），
           因此必须改为 ``app.WindowState = 2``（ppWindowMinimized）最小化
           方案，且 **绝不写** ``app.Visible``；
        2. win32com 动态分派对 PowerPoint 的 ``SaveAs`` 没有 ``PrintRange``
           参数，调用必须为 ``SaveAs(路径, 32)``（传 PrintRange 会抛
           "unexpected keyword argument 'PrintRange'"）。
        """
        src = office_source("pptx")
        app, document, created = _make_fake_office("pptx")

        with (
            patch("pythoncom.CoInitialize", return_value=0),
            patch("pythoncom.CoUninitialize"),
            patch("win32com.client.Dispatch", return_value=app),
        ):
            result = OfficeConverter._convert_with_com(
                _make_file_info("pptx", src), "pptx"
            )

        assert result.backend_used == "com"
        assert app.WindowState == 2, "PowerPoint 应使用最小化窗口（ppWindowMinimized）"
        assert (
            app.Visible is not False
        ), "PowerPoint 不得设置 app.Visible（禁止隐藏主窗口，会抛 COM 异常）"
        app.Presentations.Open.assert_called_once_with(
            src, ReadOnly=True, WithWindow=False
        )
        assert document.SaveAs.called
        call_args = document.SaveAs.call_args
        assert str(call_args.args[0]) == str(created[0]), (
            "SaveAs 应导出到产物 PDF 路径"
        )
        assert call_args.args[1] == 32, "32 = ppSaveAsPDF"
        assert (
            call_args.kwargs == {}
        ), "PowerPoint SaveAs 不得传 PrintRange（win32com 动态分派不接受）"


# ===========================================================================
# 清理纪律：Quit() 在 finally 中执行（即使导出抛异常）
# ===========================================================================


class TestQuitInFinally:
    """``app.Quit()`` 必须始终执行 —— 即使导出抛出异常。"""

    def test_quit_called_when_export_raises(self, office_source) -> None:
        """导出抛异常 → 返回错误结果，但 document.Close + app.Quit 仍执行。"""
        src = office_source("docx")
        app = MagicMock()
        document = MagicMock()
        app.Documents.Open.return_value = document
        document.ExportAsFixedFormat.side_effect = OSError("export failed")

        def _fake_dispatch(prog_id: str) -> MagicMock:
            if prog_id == "Word.Application":
                return app
            raise OSError("WPS unavailable")

        with (
            patch("pythoncom.CoInitialize", return_value=0),
            patch("pythoncom.CoUninitialize"),
            patch("win32com.client.Dispatch", side_effect=_fake_dispatch),
        ):
            result = OfficeConverter._convert_with_com(
                _make_file_info("docx", src), "docx"
            )

        assert result.backend_used == "error"
        assert result.content_type == "error"
        assert "COM" in result.message, "错误消息应包含失败来源"
        document.Close.assert_called_once_with(False)
        app.Quit.assert_called_once()


# ===========================================================================
# 失败路径 / 无后端：错误结果（绝不抛出）
# ===========================================================================


class TestFailurePaths:
    """全部 ProgID 创建失败 / pywin32 缺失 / 能力探测不可用 → 错误结果。"""

    def test_all_dispatch_fails_returns_chinese_error(self, office_source) -> None:
        """所有 ProgID 创建失败 → 中文错误结果，绝不抛出异常。"""
        src = office_source("docx")

        with (
            patch("pythoncom.CoInitialize", return_value=0),
            patch("pythoncom.CoUninitialize"),
            patch("win32com.client.Dispatch", side_effect=OSError("no office")),
        ):
            result = OfficeConverter._convert_with_com(
                _make_file_info("docx", src), "docx"
            )

        assert isinstance(result, ConversionResult)
        assert result.backend_used == "error"
        assert result.content_type == "error"
        assert result.message
        assert any("\u4e00" <= ch <= "\u9fff" for ch in result.message), (
            "错误消息应为中文"
        )

    def test_import_guard_returns_error_without_pywin32(self, office_source) -> None:
        """pywin32 缺失（惰性导入失败）→ 错误结果，不启动线程、不抛出。"""
        src = office_source("docx")

        with patch.dict(
            sys.modules, {"pythoncom": None, "win32com": None}
        ):
            result = OfficeConverter._convert_with_com(
                _make_file_info("docx", src), "docx"
            )

        assert result.backend_used == "error"
        assert result.content_type == "error"
        assert "pywin32" in result.message

    def test_no_office_or_wps_capability_returns_install_prompt(self) -> None:
        """LO / COM 能力探测均不可用 → legacy 格式返回安装提示错误后端。"""
        with (
            patch.object(OfficeConverter, "_soffice_available", return_value=False),
            patch.object(OfficeConverter, "_com_available", return_value=False),
        ):
            result = OfficeConverter.convert(
                _make_file_info("doc", "C:/dummy/sample.doc")
            )

        assert result.backend_used == "error"
        assert result.content_type == "error"
        assert result.message == ERROR_MESSAGE

    def test_missing_source_returns_degraded_com_result(self) -> None:
        """源文件不存在 → 保留 ``"com"``/``"pdf"`` 标识的降级结果（镜像
        ``_degraded_result`` 约定，兼容 T4 分派路由测试），且不启动线程。"""
        init_idents: list[int] = []

        with (
            patch(
                "pythoncom.CoInitialize",
                side_effect=lambda *a, **k: init_idents.append(
                    threading.get_ident()
                ),
            ),
        ):
            result = OfficeConverter._convert_with_com(
                _make_file_info("docx", "C:/dummy/sample.docx"), "docx"
            )

        assert result.backend_used == "com"
        assert result.content_type == "pdf"
        assert result.message, "降级结果应携带失败原因"
        assert result.content == ""
        assert not init_idents, "源文件缺失时不得启动 COM 任务线程"


# ===========================================================================
# 6 种后缀成功路径
# ===========================================================================


class TestSuccessForAllSuffixes:
    """doc/docx/xls/xlsx/ppt/pptx 在 COM 可用时均应转换出非空 PDF。"""

    @pytest.mark.parametrize("suffix", ["doc", "docx", "xls", "xlsx", "ppt", "pptx"])
    def test_com_conversion_produces_non_empty_pdf(
        self, office_source, suffix: str
    ) -> None:
        """每个后缀成功转换：结果为 pdf 类型，产物为存在且非空的 Path。"""
        src = office_source(suffix)
        app, _document, created = _make_fake_office(suffix)

        with (
            patch("pythoncom.CoInitialize", return_value=0),
            patch("pythoncom.CoUninitialize"),
            patch("win32com.client.Dispatch", return_value=app),
        ):
            result = OfficeConverter._convert_with_com(
                _make_file_info(suffix, src), suffix
            )

        assert isinstance(result, ConversionResult)
        assert result.backend_used == "com"
        assert result.content_type == "pdf"
        assert created, "COM 导出回调应被调用并生成 PDF"
        assert result.content == created[0]
        assert result.content.is_file()
        assert result.content.stat().st_size > 0, "产物 PDF 必须非空"
        assert result.message == ""
        app.Quit.assert_called_once()