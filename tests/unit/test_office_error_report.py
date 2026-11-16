"""Office 错误报告构建器测试。"""

from __future__ import annotations

from datetime import datetime

from sopeek.services.office_error_report import build_office_error_report


def test_report_contains_user_and_technical_context() -> None:
    report = build_office_error_report(
        "PowerPoint 导出 PDF 失败",
        detail="HRESULT：0x80004005\n描述：PowerPoint 储存此文件时发生错误。",
        file_path=r"C:\Home\桌面\新建文件夹\PowerPoint.pptx",
        suffix="pptx",
        backend="com",
        timestamp=datetime(2026, 11, 16, 12, 0, 0),
    )

    assert "Sopeek Office 预览错误报告" in report
    assert "2026-11-16 12:00:00" in report
    assert r"C:\Home\桌面\新建文件夹\PowerPoint.pptx" in report
    assert "格式：pptx" in report
    assert "后端：com" in report
    assert "PowerPoint 导出 PDF 失败" in report
    assert "HRESULT：0x80004005" in report
    assert "技术详情：" in report


def test_report_handles_empty_message_and_detail() -> None:
    report = build_office_error_report("")

    assert "错误：未知错误" in report
    assert "技术详情：" not in report
    assert report.endswith("\n")


def test_report_always_ends_with_newline() -> None:
    report = build_office_error_report("x", detail="y")
    assert report.endswith("\n")
    assert not report.endswith("\n\n")
