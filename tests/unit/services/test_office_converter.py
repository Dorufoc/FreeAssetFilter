# -*- coding: utf-8 -*-
"""``OfficeConverter`` / ``OfficeConverterWorker`` / office_cache 联动测试
（todo-13 unit/services 批2）。

覆盖：
* 三模式后端 dispatch（LO → COM → pure-python）与探测函数 mock；
* 真实 xlsx / docx 纯 Python 转换成功路径（openpyxl / mammoth）；
* legacy 格式在无后端时的安装提示；缓存命中跳过重新转换；
* worker 的信号 / 取消 / 超时队列行为。

环境纪律：
* **禁止真实启动全套 Office 套件**——COM/LO 分支全部通过 monkeypatch
  探测函数（``_soffice_available`` / ``_com_available``）或 patch 后端
  方法控制，真实探测只走注册表（不启动进程）；
* 超时上限 60s（pytest.ini 默认 30s），worker 信号等待全部有界；
* 趋势性缓存写入 / 周期清理线程在模块级 teardown 中停止，防悬挂。
"""

# targets: services.office_converter, services.office_converter_worker, services.office_cache

from __future__ import annotations

import os
import threading
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import pytest

from freeassetfilter.services.office_cache import (
    MAX_OFFICE_CACHE_AGE_DAYS,
    OFFICE_CACHE_TARGET_BYTES,
    cleanup_cache,
    get_cache_path,
    office_cache_dir,
    put_cache,
    start_periodic_cleanup,
    stop_periodic_cleanup,
)
from freeassetfilter.services.office_converter import (
    ERROR_MESSAGE,
    ConversionResult,
    OfficeConverter,
    clear_active_lo_popen,
    get_active_lo_popen,
)
import freeassetfilter.services.office_converter as _oc_module
from freeassetfilter.services.office_converter_worker import OfficeConverterWorker
from tests.support.qt_helpers import flush_widget_queue, wait_for_signal

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module", autouse=True)
def _no_periodic_cleanup() -> None:
    """模块级：测试前/后停掉 office_cache 周期清理线程。

    Returns:
        None。
    """
    stop_periodic_cleanup()
    yield
    stop_periodic_cleanup()


@pytest.fixture
def office_cache_redirect(monkeypatch: Any, tmp_path: Path) -> Path:
    """把 office_cache 目录重定向到 tmp_path，避免污染仓库 data/。

    Args:
        monkeypatch: pytest monkeypatch。
        tmp_path: pytest 临时目录。

    Returns:
        Path: 重定向后的缓存目录路径。
    """
    target: Path = tmp_path / "office_cache"
    target.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "freeassetfilter.services.office_cache.office_cache_dir",
        lambda: target,
    )
    return target


# ── 数据生成 ─────────────────────────────────────────────────────────────


def make_xlsx(path: Union[str, Path], rows: Sequence[Sequence[Any]]) -> str:
    """用 openpyxl 生成一个真实 xlsx 文件。

    Args:
        path: 输出路径（``.xlsx``）。
        rows: 二维数据（行→单元格值）。

    Returns:
        str: 生成后的文件路径。
    """
    import openpyxl

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    for row_index, row in enumerate(rows, start=1):
        for col_index, value in enumerate(row, start=1):
            sheet.cell(row=row_index, column=col_index, value=value)
    workbook.save(str(path))
    return str(path)


def make_docx(path: Union[str, Path], text: str = "Hello Docx World") -> str:
    """构造一个最小可用 docx（zip 结构，可被 mammoth 解析）。

    Args:
        path: 输出路径（``.docx``）。
        text: 文档正文文本。

    Returns:
        str: 生成后的文件路径。
    """
    out: Path = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    content_types: str = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels: str = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    document: str = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
    )
    with zipfile.ZipFile(str(out), "w") as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", document)
    return str(out)


def _set_probes(monkeypatch: Any, soffice: bool, com: bool) -> None:
    """强制 ``OfficeConverter`` 的两个探测函数返回指定值。

    Args:
        monkeypatch: pytest monkeypatch。
        soffice: LibreOffice 探测结果。
        com: COM 探测结果。
    """
    monkeypatch.setattr(OfficeConverter, "_soffice_available", staticmethod(lambda: soffice))
    monkeypatch.setattr(OfficeConverter, "_com_available", staticmethod(lambda: com))


def _pdf_result(path: Path, backend: str = "libreoffice") -> ConversionResult:
    """构造一个含真实 PDF 产物的后端成功结果。

    Args:
        path: 产物 PDF 路径。
        backend: 后端标识。

    Returns:
        ConversionResult: PDF 内容的结果。
    """
    return ConversionResult(
        content_type="pdf",
        content=path,
        backend_used=backend,
    )


# ── 后端 dispatch ────────────────────────────────────────────────────────


class TestBackendDispatch:
    """按「LO → COM → 纯 Python」顺序分派的三模式测试。"""

    def test_libreoffice_wins_when_available(
        self, monkeypatch: Any, tmp_path: Path, office_cache_redirect: Path
    ) -> None:
        """happy：LO 可用时 docx 应优先走 LibreOffice 分支。

        Args:
            monkeypatch: pytest monkeypatch。
            tmp_path: pytest 临时目录。
            office_cache_redirect: 缓存重定向 fixture。
        """
        _set_probes(monkeypatch, soffice=True, com=True)
        pdf: Path = tmp_path / "out.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        monkeypatch.setattr(
            OfficeConverter,
            "_convert_with_libreoffice",
            staticmethod(lambda file_info, suffix: _pdf_result(pdf, "libreoffice")),
        )
        result: ConversionResult = OfficeConverter.convert(
            {"path": str(tmp_path / "a.docx"), "suffix": "docx"}
        )
        assert result.backend_used == "libreoffice"
        assert result.content_type == "pdf"

    def test_com_used_when_lo_absent(
        self, monkeypatch: Any, tmp_path: Path, office_cache_redirect: Path
    ) -> None:
        """happy：LO 缺失、COM 可用时 docx 应走 COM 分支。

        Args:
            monkeypatch: pytest monkeypatch。
            tmp_path: pytest 临时目录。
            office_cache_redirect: 缓存重定向 fixture。
        """
        _set_probes(monkeypatch, soffice=False, com=True)
        pdf: Path = tmp_path / "com.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        monkeypatch.setattr(
            OfficeConverter,
            "_convert_with_com",
            staticmethod(lambda file_info, suffix: _pdf_result(pdf, "com")),
        )
        result: ConversionResult = OfficeConverter.convert(
            {"path": str(tmp_path / "b.docx"), "suffix": "docx"}
        )
        assert result.backend_used == "com"
        assert result.content_type == "pdf"

    def test_pure_python_xlsx_table_success(
        self, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """happy：LO/COM 均缺→走纯 Python，真实 xlsx 转 TSV 表格。

        Args:
            monkeypatch: pytest monkeypatch。
            tmp_path: pytest 临时目录。
        """
        _set_probes(monkeypatch, soffice=False, com=False)
        xlsx: str = make_xlsx(
            tmp_path / "data.xlsx",
            [["姓名", "分数"], ["张三", 99], ["李四", 88]],
        )
        result: ConversionResult = OfficeConverter.convert(
            {"path": xlsx, "suffix": "xlsx"}
        )
        assert result.backend_used == "pure-python"
        assert result.content_type == "table"
        assert "姓名\t分数" in result.content
        assert "张三\t99" in result.content

    def test_pure_python_docx_real_conversion(
        self, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """happy：纯 Python 后端真实转换最小 docx（mammoth）。

        Args:
            monkeypatch: pytest monkeypatch。
            tmp_path: pytest 临时目录。
        """
        few_import: bool = True
        try:
            import mammoth  # noqa: F401
        except ImportError:
            few_import = False
        if not few_import:
            pytest.skip("mammoth 未安装，跳过真实 docx 转换")
        _set_probes(monkeypatch, soffice=False, com=False)
        docx: str = make_docx(tmp_path / "letter.docx", "Hello Docx World")
        result: ConversionResult = OfficeConverter.convert(
            {"path": docx, "suffix": "docx"}
        )
        assert result.backend_used == "pure-python"
        assert result.content_type == "html"
        assert "Hello Docx World" in str(result.content)

    def test_pure_python_sanitizes_cell_separators(
        self, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """boundary：单元格内的制表符/换行应被清洗为空格。

        Args:
            monkeypatch: pytest monkeypatch。
            tmp_path: pytest 临时目录。
        """
        _set_probes(monkeypatch, soffice=False, com=False)
        xlsx: str = make_xlsx(tmp_path / "dirty.xlsx", [["a\tb", "c\nd"]])
        result: ConversionResult = OfficeConverter.convert(
            {"path": xlsx, "suffix": "xlsx"}
        )
        assert result.content_type == "table"
        assert result.content == "a b\tc d"  # 内部 \t/\n 已清洗，仅保留 TSV 分隔符

    def test_legacy_doc_returns_install_prompt_without_backends(
        self, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """error：legacy doc 在 LO/COM 均不可用时返回安装提示。

        Args:
            monkeypatch: pytest monkeypatch。
            tmp_path: pytest 临时目录。
        """
        _set_probes(monkeypatch, soffice=False, com=False)
        legacy: Path = tmp_path / "old.doc"
        legacy.write_bytes(b"legacy doc bytes")
        result: ConversionResult = OfficeConverter.convert(
            {"path": str(legacy), "suffix": "doc"}
        )
        assert result.backend_used == "error"
        assert result.message == ERROR_MESSAGE

    def test_unknown_suffix_returns_error(self, monkeypatch: Any, tmp_path: Path) -> None:
        """error：未知后缀返回错误且不抛出。

        Args:
            monkeypatch: pytest monkeypatch。
            tmp_path: pytest 临时目录。
        """
        _set_probes(monkeypatch, soffice=False, com=False)
        result: ConversionResult = OfficeConverter.convert(
            {"path": str(tmp_path / "x.weird"), "suffix": "weird"}
        )
        assert result.backend_used == "error"
        assert "不支持" in result.message

    def test_missing_suffix_returns_error(self, monkeypatch: Any, tmp_path: Path) -> None:
        """error：缺少后缀信息返回提示错误。

        Args:
            monkeypatch: pytest monkeypatch。
            tmp_path: pytest 临时目录。
        """
        _set_probes(monkeypatch, soffice=False, com=False)
        result: ConversionResult = OfficeConverter.convert({"path": str(tmp_path / "nofmt")})
        assert result.backend_used == "error"
        assert "后缀" in result.message

    def test_convert_with_non_dict_file_info_never_raises(self, monkeypatch: Any) -> None:
        """error：非字典 file_info 返回错误而非异常。

        Args:
            monkeypatch: pytest monkeypatch。
        """
        _set_probes(monkeypatch, soffice=False, com=False)
        result: ConversionResult = OfficeConverter.convert(None)  # type: ignore[arg-type]
        assert result.backend_used == "error"

    def test_pure_python_degraded_when_path_missing(self, monkeypatch: Any, tmp_path: Path) -> None:
        """boundary：docx 路径缺失返回保留后端标识的降级结果。

        Args:
            monkeypatch: pytest monkeypatch。
            tmp_path: pytest 临时目录。
        """
        _set_probes(monkeypatch, soffice=False, com=False)
        result: ConversionResult = OfficeConverter.convert(
            {"path": str(tmp_path / "ghost.docx"), "suffix": "docx"}
        )
        assert result.backend_used == "pure-python"
        assert result.content == ""
        assert "不存在" in result.message

    def test_com_prog_ids_by_suffix(self) -> None:
        """boundary：``_com_prog_ids`` 按后缀返回有序 ProgID。"""
        assert OfficeConverter._com_prog_ids("docx") == ("Word.Application", "Kwps.Application")
        assert OfficeConverter._com_prog_ids("xls") == ("Excel.Application", "Ket.Application")
        assert OfficeConverter._com_prog_ids("pptx") == (
            "PowerPoint.Application", "Kwpp.Application",
        )
        assert OfficeConverter._com_prog_ids("nope") == ()


# ── office_cache 联动 ────────────────────────────────────────────────────


class TestCacheIntegration:
    """缓存命中跳过重新转换 / 源文件变化触发 miss。"""

    def test_first_convert_writes_cache_second_hits(
        self, monkeypatch: Any, tmp_path: Path, office_cache_redirect: Path
    ) -> None:
        """happy：首次转换落缓存，二次直接命中（后端零调用）。

        Args:
            monkeypatch: pytest monkeypatch。
            tmp_path: pytest 临时目录。
            office_cache_redirect: 缓存重定向 fixture。
        """
        source: Path = tmp_path / "doc.docx"
        source.write_bytes(b"real source bytes")
        pdf: Path = tmp_path / "out.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake content")
        calls: List[int] = [0]
        _set_probes(monkeypatch, soffice=True, com=True)

        def _fake_lo(file_info: dict, suffix: str) -> ConversionResult:
            calls[0] += 1
            return _pdf_result(pdf, "libreoffice")

        monkeypatch.setattr(OfficeConverter, "_convert_with_libreoffice", staticmethod(_fake_lo))
        file_info: Dict[str, Any] = {"path": str(source), "suffix": "docx"}

        first: ConversionResult = OfficeConverter.convert(file_info)
        assert first.backend_used == "libreoffice"
        assert calls[0] == 1

        second: ConversionResult = OfficeConverter.convert(file_info)
        assert second.backend_used == "cache"
        assert calls[0] == 1  # 后端未被再次调用
        assert Path(second.content).is_file()

    def test_source_change_invalidates_cache(
        self, monkeypatch: Any, tmp_path: Path, office_cache_redirect: Path
    ) -> None:
        """boundary：源文件大小变化后缓存键失效，触发重新转换。

        Args:
            monkeypatch: pytest monkeypatch。
            tmp_path: pytest 临时目录。
            office_cache_redirect: 缓存重定向 fixture。
        """
        source: Path = tmp_path / "doc.docx"
        source.write_bytes(b"version one")
        pdf: Path = tmp_path / "out.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        _set_probes(monkeypatch, soffice=True, com=True)
        monkeypatch.setattr(
            OfficeConverter,
            "_convert_with_libreoffice",
            staticmethod(lambda file_info, suffix: _pdf_result(pdf, "libreoffice")),
        )
        file_info: Dict[str, Any] = {"path": str(source), "suffix": "docx"}
        assert OfficeConverter.convert(file_info).backend_used == "libreoffice"
        source.write_bytes(b"version two is much longer content")
        assert OfficeConverter.convert(file_info).backend_used == "libreoffice"


class TestOfficeCacheModule:
    """office_cache 模块本身的 put / get / cleanup / periodicity。"""

    def test_put_then_get_hit_and_miss(
        self, tmp_path: Path, office_cache_redirect: Path
    ) -> None:
        """happy：put_cache 后 get_cache_path 命中；未写时 miss。

        Args:
            tmp_path: pytest 临时目录。
            office_cache_redirect: 缓存重定向 fixture。
        """
        source: Path = tmp_path / "doc.xlsx"
        source.write_bytes(b"source for cache key")
        pdf: Path = tmp_path / "prod.pdf"
        pdf.write_bytes(b"%PDF-1.4 real")
        info: Dict[str, Any] = {"path": str(source), "suffix": "xlsx"}

        assert get_cache_path(info) is None  # 初始 miss
        cached: Path = put_cache(info, pdf)
        assert cached != pdf  # 已复制进缓存
        assert cached.exists()
        hit: Optional[Path] = get_cache_path(info)
        assert hit is not None
        assert hit == cached

    def test_put_cache_degrades_for_stat_failure(
        self, tmp_path: Path, office_cache_redirect: Path
    ) -> None:
        """boundary：源文件不可 stat 时 put_cache 原样返回。

        Args:
            tmp_path: pytest 临时目录。
            office_cache_redirect: 缓存重定向 fixture。
        """
        pdf: Path = tmp_path / "prod.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        result: Path = put_cache({"path": str(tmp_path / "ghost.xlsx")}, pdf)
        assert result == pdf

    def test_cleanup_cache_evicts_oldest_by_size(
        self, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """boundary：超过大小阈值时最旧优先驱逐。

        Args:
            monkeypatch: pytest monkeypatch。
            tmp_path: pytest 临时目录。
        """
        cache_dir: Path = tmp_path / "office_cache"
        cache_dir.mkdir()
        for index in range(4):
            (cache_dir / f"{index}.pdf").write_bytes(b"x" * 40)
        monkeypatch.setattr(
            "freeassetfilter.services.office_cache.OFFICE_CACHE_TARGET_BYTES", 60
        )
        removed: int = cleanup_cache(cache_dir)
        assert removed >= 1
        remaining: int = sum(p.stat().st_size for p in cache_dir.iterdir())
        assert remaining <= 60

    def test_cleanup_cache_evicts_by_age(
        self, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """boundary：过期条目（mtime 早于阈值）被驱逐。

        Args:
            monkeypatch: pytest monkeypatch。
            tmp_path: pytest 临时目录。
        """
        cache_dir: Path = tmp_path / "office_cache"
        cache_dir.mkdir()
        fresh: Path = cache_dir / "fresh.pdf"
        fresh.write_bytes(b"x" * 10)
        stale: Path = cache_dir / "stale.pdf"
        stale.write_bytes(b"x" * 10)
        old_time: float = time.time() - 10 * 86400
        os.utime(stale, (old_time, old_time))
        monkeypatch.setattr(
            "freeassetfilter.services.office_cache.MAX_OFFICE_CACHE_AGE_DAYS", 7
        )
        cleanup_cache(cache_dir)
        assert fresh.exists()
        assert not stale.exists()

    def test_cleanup_cache_missing_dir_returns_zero(self, tmp_path: Path) -> None:
        """boundary：目录不存在时返回 0 且不抛出。"""
        assert cleanup_cache(tmp_path / "no_such_dir") == 0

    def test_start_stop_periodic_cleanup_idempotent(self) -> None:
        """happy：周期清理启动幂等、停止幂等。"""
        stop_periodic_cleanup()
        thread: Optional[threading.Thread] = start_periodic_cleanup(interval_seconds=1.1)
        assert thread is not None and thread.is_alive()
        assert start_periodic_cleanup(interval_seconds=1.1) is thread
        assert stop_periodic_cleanup() is True
        assert stop_periodic_cleanup() is False


# ── OfficeConverterWorker ────────────────────────────────────────────────


def _shutdown_office_worker(worker: OfficeConverterWorker, qapp: Any, timeout_ms: int = 3000) -> None:
    """安全回收 office worker：isRunning 守卫 + wait/terminate 兜底。

    Args:
        worker: 待回收的 worker。
        qapp: QApplication 实例（事件冲刷用）。
        timeout_ms: 首次 wait 超时毫秒数。
    """
    if worker.isRunning():
        if not worker.wait(timeout_ms):
            worker.terminate()
            worker.wait(timeout_ms)
    worker.deleteLater()
    flush_widget_queue(qapp)


class TestOfficeConverterWorker:
    """worker 信号 / 取消 / 超时队列行为。"""

    def test_converted_signal_for_pure_python(
        self, qapp: Any, monkeypatch: Any
    ) -> None:
        """happy：纯 Python 结果应编码为 ``html:...`` 发射 converted。

        Args:
            qapp: 会话级 QApplication。
            monkeypatch: pytest monkeypatch。
        """
        result: ConversionResult = ConversionResult(
            content_type="html", content="<p>Hi</p>", backend_used="pure-python"
        )
        monkeypatch.setattr(OfficeConverter, "convert", staticmethod(lambda file_info: result))
        worker: OfficeConverterWorker = OfficeConverterWorker(
            {"path": "x.docx", "suffix": "docx"}
        )
        got: List[str] = []
        worker.converted.connect(got.append)
        mis: List[str] = []
        worker.failed.connect(mis.append)
        worker.start()
        assert wait_for_signal(worker.converted, timeout_ms=3000)
        assert got == ["html:<p>Hi</p>"]
        assert not mis
        _shutdown_office_worker(worker, qapp)

    def test_failed_signal_for_error_result(self, qapp: Any, monkeypatch: Any) -> None:
        """error：content_type == error → failed 携带消息。

        Args:
            qapp: 会话级 QApplication。
            monkeypatch: pytest monkeypatch。
        """
        result: ConversionResult = ConversionResult(
            content_type="error", content="", backend_used="error", message="转换爆炸"
        )
        monkeypatch.setattr(OfficeConverter, "convert", staticmethod(lambda file_info: result))
        worker: OfficeConverterWorker = OfficeConverterWorker(
            {"path": "x.docx", "suffix": "docx"}
        )
        got: List[str] = []
        worker.failed.connect(got.append)
        worker.start()
        assert wait_for_signal(worker.failed, timeout_ms=3000)
        assert got == ["转换爆炸"]
        _shutdown_office_worker(worker, qapp)

    def test_cancel_emits_cancel_message(self, qapp: Any, monkeypatch: Any) -> None:
        """boundary：取消进行中的转换应发射「已取消」。

        终止 seam 被 no-op，避免轮询 Popen 与 powershell 孤儿清理。

        Args:
            qapp: 会话级 QApplication。
            monkeypatch: pytest monkeypatch。
        """
        entered: threading.Event = threading.Event()
        release: threading.Event = threading.Event()

        def _blocking_convert(file_info: dict) -> ConversionResult:
            entered.set()
            release.wait(5)
            return ConversionResult(
                content_type="html", content="late", backend_used="pure-python"
            )

        monkeypatch.setattr(OfficeConverter, "convert", staticmethod(_blocking_convert))
        monkeypatch.setattr(
            OfficeConverterWorker, "_terminate_active_subprocess", lambda self, grace=None: None
        )
        worker: OfficeConverterWorker = OfficeConverterWorker(
            {"path": "x.docx", "suffix": "docx"}
        )
        got: List[str] = []
        worker.failed.connect(got.append)
        worker.start()
        assert entered.wait(3), "worker 转换未进入"
        worker.request_cancel()
        assert worker._cancel_requested is True
        release.set()
        assert wait_for_signal(worker.failed, timeout_ms=3000)
        assert "已取消" in got[0]
        _shutdown_office_worker(worker, qapp)

    def test_timeout_emits_timeout_failed(self, qapp: Any, monkeypatch: Any) -> None:
        """error：worker 超时设置应发射含「超时」的 failed。

        Args:
            qapp: 会话级 QApplication。
            monkeypatch: pytest monkeypatch。
        """
        entered: threading.Event = threading.Event()
        release: threading.Event = threading.Event()

        def _blocking_convert(file_info: dict) -> ConversionResult:
            entered.set()
            release.wait(5)
            return ConversionResult(
                content_type="html", content="late", backend_used="pure-python"
            )

        monkeypatch.setattr(OfficeConverter, "convert", staticmethod(_blocking_convert))
        monkeypatch.setattr(
            OfficeConverterWorker, "_terminate_active_subprocess", lambda self, grace=None: None
        )
        worker: OfficeConverterWorker = OfficeConverterWorker(
            {"path": "x.docx", "suffix": "docx"}, timeout=0.1
        )
        got: List[str] = []
        worker.failed.connect(got.append)
        worker.start()
        assert entered.wait(3)
        # 等看门狗定时器（0.1s）真的触发，避免与 release 竞态
        await_fired = time.monotonic() + 3.0
        while not worker._timed_out and time.monotonic() < await_fired:
            time.sleep(0.01)
        assert worker._timed_out is True
        release.set()
        # 信号自 worker 线程 Queued 投递；wait_for_signal 的 QEventLoop 可能
        # 错过已入队事件（与 test_double_start_ignored 同因，见其注释），
        # 故轮询事件泵等待 failed 到达，保证 flaky 稳定。
        await_fire = time.monotonic() + 3.0
        while not got and time.monotonic() < await_fire:
            flush_widget_queue(qapp, iterations=5)
            time.sleep(0.01)
        assert "超时" in got[0]
        _shutdown_office_worker(worker, qapp)

    def test_double_start_ignored(self, qapp: Any, monkeypatch: Any) -> None:
        """boundary：线程运行中重复 start 被忽略，转换只执行一次。

        Args:
            qapp: 会话级 QApplication。
            monkeypatch: pytest monkeypatch。
        """
        calls: List[int] = [0]

        def _fast_convert(file_info: dict) -> ConversionResult:
            calls[0] += 1
            return ConversionResult(
                content_type="html", content="<p>ok</p>", backend_used="pure-python"
            )

        monkeypatch.setattr(OfficeConverter, "convert", staticmethod(_fast_convert))
        worker: OfficeConverterWorker = OfficeConverterWorker(
            {"path": "x.docx", "suffix": "docx"}
        )
        got: List[str] = []
        worker.converted.connect(got.append)
        worker.start()
        worker.start()  # 守卫：忽略二次启动
        # 排队信号目标在发射时连接定死，wait_for_signal 可能错过已入队事件，
        # 故轮询事件泵等待 received 到达
        deadline: float = time.monotonic() + 3.0
        while not got and time.monotonic() < deadline:
            flush_widget_queue(qapp, iterations=5)
            time.sleep(0.01)
        assert got == ["html:<p>ok</p>"]
        assert calls[0] == 1
        _shutdown_office_worker(worker, qapp)

    def test_cleanup_cancels_and_schedules_delete(self, qapp: Any, monkeypatch: Any) -> None:
        """boundary：cleanup 在运行中请求取消并安排 deleteLater。

        Args:
            qapp: 会话级 QApplication。
            monkeypatch: pytest monkeypatch。
        """
        entered: threading.Event = threading.Event()
        release: threading.Event = threading.Event()

        def _blocking_convert(file_info: dict) -> ConversionResult:
            entered.set()
            release.wait(5)
            return ConversionResult(
                content_type="html", content="late", backend_used="pure-python"
            )

        monkeypatch.setattr(OfficeConverter, "convert", staticmethod(_blocking_convert))
        monkeypatch.setattr(
            OfficeConverterWorker, "_terminate_active_subprocess", lambda self, grace=None: None
        )
        worker: OfficeConverterWorker = OfficeConverterWorker(
            {"path": "x.docx", "suffix": "docx"}
        )
        worker.start()
        assert entered.wait(3)
        worker.cleanup(wait_ms=200)  # cancel + wait(有界) + deleteLater
        assert worker._cancel_requested is True
        release.set()
        if worker.isRunning():
            if not worker.wait(3000):
                worker.terminate()
                worker.wait(3000)
        flush_widget_queue(qapp)

    def test_encode_content_codings(self, monkeypatch: Any, tmp_path: Path) -> None:
        """boundary：``_encode_content`` 对 pdf / 文本产物的编码。"""
        worker: OfficeConverterWorker = OfficeConverterWorker(
            {"path": str(tmp_path / "x.docx"), "suffix": "docx"}
        )
        pdf: Path = tmp_path / "out.pdf"
        assert worker._encode_content(_pdf_result(pdf, "com")) == str(pdf)
        table: ConversionResult = ConversionResult(
            content_type="table", content="a\tb", backend_used="pure-python"
        )
        assert worker._encode_content(table) == "table:a\tb"


# ── T9 取消 seam：活动 soffice Popen 注册表 ─────────────────────────────


class TestActiveLoPopenSeam:
    """``get_active_lo_popen`` / ``clear_active_lo_popen`` 读写注册表。"""

    def test_get_initial_miss_returns_none(self) -> None:
        """happy：注册表无当前线程键时返回 None。"""
        _oc_module._ACTIVE_LO_POPEN.pop(threading.get_ident(), None)
        assert get_active_lo_popen() is None
        assert get_active_lo_popen(thread_id=threading.get_ident() + 1) is None

    def test_get_registered_handle_roundtrip(self) -> None:
        """happy：注册句柄可被读取；显式 thread_id 也能读取。"""
        tid: int = threading.get_ident()
        handle: object = object()
        _oc_module._ACTIVE_LO_POPEN[tid] = handle
        try:
            assert get_active_lo_popen() is handle
            assert get_active_lo_popen(thread_id=tid) is handle
        finally:
            _oc_module._ACTIVE_LO_POPEN.pop(tid, None)

    def test_clear_removes_current_thread(self) -> None:
        """happy：clear 清除当前线程句柄，随后读取为 None。"""
        tid: int = threading.get_ident()
        _oc_module._ACTIVE_LO_POPEN[tid] = object()
        try:
            clear_active_lo_popen()
            assert get_active_lo_popen() is None
            assert tid not in _oc_module._ACTIVE_LO_POPEN
        finally:
            _oc_module._ACTIVE_LO_POPEN.pop(tid, None)

    def test_clear_explicit_thread_id(self) -> None:
        """boundary：显式 thread_id 只清除指定线程的键。"""
        tid: int = threading.get_ident()
        other: int = tid + 12345
        _oc_module._ACTIVE_LO_POPEN[other] = object()
        _oc_module._ACTIVE_LO_POPEN[tid] = object()
        try:
            clear_active_lo_popen(thread_id=other)
            assert other not in _oc_module._ACTIVE_LO_POPEN
            assert tid in _oc_module._ACTIVE_LO_POPEN  # 本线程句柄保留
        finally:
            _oc_module._ACTIVE_LO_POPEN.pop(tid, None)
            _oc_module._ACTIVE_LO_POPEN.pop(other, None)

    def test_clear_missing_key_is_noop(self) -> None:
        """boundary：清除不存在的线程键不抛错。"""
        _oc_module._ACTIVE_LO_POPEN.pop(threading.get_ident(), None)
        clear_active_lo_popen()
        clear_active_lo_popen(thread_id=threading.get_ident() + 999)


# ── 常量与导出完整性 ─────────────────────────────────────────────────────


class TestConstants:
    """常量引用冒烟，防止误 import。"""

    def test_exported_constants_exist(self) -> None:
        """happy：office_cache 关键常量/函数可被导入。"""
        assert MAX_OFFICE_CACHE_AGE_DAYS >= 1
        assert OFFICE_CACHE_TARGET_BYTES > 0
        assert office_cache_dir().name == "office_cache"


__all__: Tuple[str, ...] = ()