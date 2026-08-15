#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OfficeConverter 分派服务单元测试

通过 mock 注入能力探测结果（不依赖真实 LibreOffice / Office / WPS），验证：
- 无任何后端时现代格式（docx/pptx/xlsx）降级到纯 Python 路径（backend_used == "pure-python"）
- LO 可用时优先 LO，且不触达 COM 探测 / COM 转换 / 纯 Python（Metis E2）
- legacy 格式（doc/xls/ppt）在 LO/COM 均不可用时返回安装提示后端
- 探测函数抛出异常时服务内部捕获并降级到下一级，绝不向外抛出
- T8 缓存清理 seam（_maybe_cleanup_cache）在 convert() 入口被幂等调用
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from freeassetfilter.services import office_cache
from freeassetfilter.services.office_converter import (
    ERROR_MESSAGE,
    ConversionResult,
    OfficeConverter,
)


def _make_file_info(suffix: str) -> dict:
    """构造与 PreviewerRegistry 契约一致的 file_info。"""
    return {"path": f"C:/dummy/sample.{suffix}", "suffix": suffix, "is_dir": False}


def _real_file(tmp_path: Path, name: str = "sample.docx") -> Path:
    """构造一个真实存在的 Office 源文件（缓存键需要可 stat）。"""
    src = tmp_path / name
    src.write_bytes(b"docx-content" * 64)
    return src


def _make_info(src: Path) -> dict:
    """构造 file_info（与 PreviewerRegistry 契约一致）。"""
    return {"path": str(src), "suffix": "docx", "is_dir": False}


def _fake_pdf(tmp_path: Path, name: str = "converted.pdf") -> Path:
    """构造一个产物 PDF。"""
    pdf = tmp_path / name
    pdf.write_bytes(b"%PDF-1.4 fake")
    return pdf


def _redirect_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把缓存目录重定向到 tmp_path 下（调用期 monkeypatch）。"""
    cache_dir = tmp_path / "office_cache"
    monkeypatch.setattr(office_cache, "office_cache_dir", lambda: cache_dir)
    return cache_dir


# ===========================================================================
# 现代格式（docx/pptx/xlsx）无后端 → 纯 Python
# ===========================================================================


class TestModernSuffixesPurePythonFallback:
    """``soffice_available=False`` 且 ``com_available=False`` 时，
    docx/pptx/xlsx 应路由到纯 Python 路径并给出正确的占位内容类型。"""

    @pytest.mark.parametrize(
        "suffix, expected_content_type",
        [
            ("docx", "html"),
            ("pptx", "outline"),
            ("xlsx", "table"),
        ],
    )
    def test_no_backends_routes_to_pure_python(
        self, suffix: str, expected_content_type: str
    ) -> None:
        """无外部后端时现代格式降级到纯 Python。"""
        with (
            patch.object(OfficeConverter, "_soffice_available", return_value=False),
            patch.object(OfficeConverter, "_com_available", return_value=False),
        ):
            result = OfficeConverter.convert(_make_file_info(suffix))

        assert isinstance(result, ConversionResult)
        assert result.backend_used == "pure-python"
        assert result.content_type == expected_content_type
        assert result.truncated is False

    def test_suffix_normalization_upper_and_leading_dot(self) -> None:
        """后缀大小写不敏感且前导点被剥离 —— ``.DOCX`` 应视为 ``docx``。"""
        with (
            patch.object(OfficeConverter, "_soffice_available", return_value=False),
            patch.object(OfficeConverter, "_com_available", return_value=False),
        ):
            result = OfficeConverter.convert({"path": "A.DOCX", "suffix": ".DOCX"})

        assert result.backend_used == "pure-python"
        assert result.content_type == "html"


# ===========================================================================
# LO 优先且不触达 COM / 纯 Python（Metis E2）
# ===========================================================================


class TestLibreOfficePreferred:
    """``soffice_available=True`` 时 LO 优先，COM 探测与纯 Python 均不被触碰。"""

    def test_soffice_available_preferred_over_com_and_pure_python(self) -> None:
        """LO 可用时 COM 探测 / COM 转换 / 纯 Python 均不应被调用。"""
        with (
            patch.object(OfficeConverter, "_soffice_available", return_value=True),
            patch.object(OfficeConverter, "_com_available", return_value=True) as com_probe,
            patch.object(OfficeConverter, "_convert_with_com") as com_conv,
            patch.object(OfficeConverter, "_convert_pure_python") as py_conv,
        ):
            result = OfficeConverter.convert(_make_file_info("docx"))

        assert result.backend_used == "libreoffice"
        assert result.content_type == "pdf"
        com_probe.assert_not_called()
        com_conv.assert_not_called()
        py_conv.assert_not_called()

    def test_soffice_preferred_for_legacy_suffixes(self) -> None:
        """legacy 格式在 LO 可用时同样优先 LO 且不触达后续后端。"""
        with (
            patch.object(OfficeConverter, "_soffice_available", return_value=True),
            patch.object(OfficeConverter, "_com_available", return_value=True) as com_probe,
            patch.object(OfficeConverter, "_convert_pure_python") as py_conv,
        ):
            result = OfficeConverter.convert(_make_file_info("doc"))

        assert result.backend_used == "libreoffice"
        assert result.content_type == "pdf"
        com_probe.assert_not_called()
        py_conv.assert_not_called()


# ===========================================================================
# 分派顺序：LO 不可用时 COM 生效
# ===========================================================================


class TestDispatchOrder:
    """验证「LO → COM → 纯 Python」的顺序降级。"""

    def test_com_used_when_soffice_unavailable(self) -> None:
        """docx 在 LO 不可用、COM 可用时路由到 COM 且不触达纯 Python。"""
        with (
            patch.object(OfficeConverter, "_soffice_available", return_value=False),
            patch.object(OfficeConverter, "_com_available", return_value=True),
            patch.object(OfficeConverter, "_convert_with_libreoffice") as lo_conv,
            patch.object(OfficeConverter, "_convert_pure_python") as py_conv,
        ):
            result = OfficeConverter.convert(_make_file_info("docx"))

        assert result.backend_used == "com"
        assert result.content_type == "pdf"
        lo_conv.assert_not_called()
        py_conv.assert_not_called()

    def test_com_used_for_legacy_when_soffice_unavailable(self) -> None:
        """legacy 格式（xls）在 LO 不可用、COM 可用时路由到 COM。"""
        with (
            patch.object(OfficeConverter, "_soffice_available", return_value=False),
            patch.object(OfficeConverter, "_com_available", return_value=True),
        ):
            result = OfficeConverter.convert(_make_file_info("xls"))

        assert result.backend_used == "com"
        assert result.content_type == "pdf"


# ===========================================================================
# legacy 格式（doc/xls/ppt）无后端 → 安装提示错误后端
# ===========================================================================


class TestLegacyErrorBackend:
    """``soffice_available=False`` 且 ``com_available=False`` 时，
    doc/xls/ppt 应返回安装提示错误后端（纯 Python 不允许用于 legacy）。"""

    @pytest.mark.parametrize("suffix", ["doc", "xls", "ppt"])
    def test_legacy_no_backends_returns_install_prompt(self, suffix: str) -> None:
        """legacy 格式无后端时返回精确的安装提示文案。"""
        with (
            patch.object(OfficeConverter, "_soffice_available", return_value=False),
            patch.object(OfficeConverter, "_com_available", return_value=False),
        ):
            result = OfficeConverter.convert(_make_file_info(suffix))

        assert result.backend_used == "error"
        assert result.content_type == "error"
        assert result.message == ERROR_MESSAGE


# ===========================================================================
# 探测函数抛异常 → 服务内部捕获并降级（绝不向外抛出）
# ===========================================================================


class TestDetectionErrorsNeverRaise:
    """探测函数抛异常时服务内部捕获、降级到下一级，``convert()`` 不抛出。"""

    def test_detection_raises_modern_degrades_to_pure_python(self) -> None:
        """docx 在两侧探测均抛异常时降级到纯 Python，且不向外抛出。"""
        with (
            patch.object(
                OfficeConverter, "_soffice_available",
                side_effect=RuntimeError("soffice probe failed"),
            ),
            patch.object(
                OfficeConverter, "_com_available",
                side_effect=RuntimeError("com probe failed"),
            ),
        ):
            result = OfficeConverter.convert(_make_file_info("pptx"))

        assert result.backend_used == "pure-python"
        assert result.content_type == "outline"

    def test_detection_raises_legacy_degrades_to_error_backend(self) -> None:
        """legacy 格式在两侧探测均抛异常时返回安装提示后端，且不向外抛出。"""
        with (
            patch.object(
                OfficeConverter, "_soffice_available",
                side_effect=RuntimeError("soffice probe failed"),
            ),
            patch.object(
                OfficeConverter, "_com_available",
                side_effect=RuntimeError("com probe failed"),
            ),
        ):
            result = OfficeConverter.convert(_make_file_info("ppt"))

        assert result.backend_used == "error"
        assert result.message == ERROR_MESSAGE

    def test_soffice_probe_raises_com_still_tried(self) -> None:
        """仅 LO 探测抛异常时仍继续尝试 COM（逐级独立降级）。"""
        with (
            patch.object(
                OfficeConverter, "_soffice_available",
                side_effect=RuntimeError("soffice probe failed"),
            ),
            patch.object(OfficeConverter, "_com_available", return_value=True),
        ):
            result = OfficeConverter.convert(_make_file_info("docx"))

        assert result.backend_used == "com"


# ===========================================================================
# 未知后缀 / 异常输入 → 错误结果（不抛出）
# ===========================================================================


class TestUnknownSuffixAndInputs:
    """未知后缀、缺失后缀、非字典输入均应返回错误结果而非抛出。"""

    def test_unknown_suffix_returns_error_result(self) -> None:
        """未知后缀返回 ``backend_used="error"`` 且消息含后缀名。"""
        with (
            patch.object(OfficeConverter, "_soffice_available", return_value=False),
            patch.object(OfficeConverter, "_com_available", return_value=False),
        ):
            result = OfficeConverter.convert(_make_file_info("exe"))

        assert result.backend_used == "error"
        assert "exe" in result.message

    def test_missing_suffix_returns_error_result(self) -> None:
        """缺少 ``suffix`` 键时返回错误结果而非抛出。"""
        with (
            patch.object(OfficeConverter, "_soffice_available", return_value=False),
            patch.object(OfficeConverter, "_com_available", return_value=False),
        ):
            result = OfficeConverter.convert({"path": "C:/dummy/file"})

        assert result.backend_used == "error"
        assert result.content_type == "error"

    def test_non_dict_file_info_does_not_raise(self) -> None:
        """``file_info=None`` 时返回错误结果而非抛出。"""
        with (
            patch.object(OfficeConverter, "_soffice_available", return_value=False),
            patch.object(OfficeConverter, "_com_available", return_value=False),
        ):
            result = OfficeConverter.convert(None)  # type: ignore[arg-type]

        assert result.backend_used == "error"
        assert result.content_type == "error"


# ===========================================================================
# T8 缓存清理 seam
# ===========================================================================


class TestCleanupSeam:
    """``_maybe_cleanup_cache()`` 是 T8 接入点：在 ``convert()`` 入口幂等触发。"""

    def test_maybe_cleanup_cache_invoked_at_convert_entry(self) -> None:
        """``convert()`` 入口应调用一次 ``_maybe_cleanup_cache()``。"""
        with (
            patch.object(OfficeConverter, "_maybe_cleanup_cache") as cleanup,
            patch.object(OfficeConverter, "_soffice_available", return_value=False),
            patch.object(OfficeConverter, "_com_available", return_value=False),
        ):
            OfficeConverter.convert(_make_file_info("xlsx"))

        cleanup.assert_called_once_with()

    def test_cleanup_seam_is_idempotent_noop(self) -> None:
        """T8 占位实现必须无副作用 —— 重复调用安全。"""
        OfficeConverter._maybe_cleanup_cache()
        OfficeConverter._maybe_cleanup_cache()


# ===========================================================================
# 缓存集成接入（T14 需求）：命中复用 / 写入 / pure-python 不缓存
# ===========================================================================


class TestCacheIntegration:
    """``convert()`` 的缓存接线：命中短路不调后端，PDF 产物落缓存，
    pure-python 文本产物不缓存。"""

    def test_pre_put_cache_hit_returns_without_backend(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """前置 put_cache 后 convert 命中：backend_used=="cache" 且后端不被执行。"""
        _redirect_cache(tmp_path, monkeypatch)
        src = _real_file(tmp_path)
        info = _make_info(src)
        office_cache.put_cache(info, _fake_pdf(tmp_path))

        with patch.object(OfficeConverter, "_try_backend") as spy_backend:
            result = OfficeConverter.convert(info)

        assert result.backend_used == "cache"
        assert result.content_type == "pdf"
        assert isinstance(result.content, Path)
        assert result.content.is_file()
        spy_backend.assert_not_called()

    def test_miss_runs_backend_then_writes_cache(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """miss 后走后端，PDF 产物被 put_cache 写入缓存返回缓存内路径。"""
        cache_dir = _redirect_cache(tmp_path, monkeypatch)
        src = _real_file(tmp_path)
        info = _make_info(src)
        pdf = _fake_pdf(tmp_path)
        assert office_cache.get_cache_path(info) is None  # 前置确认 miss

        with patch.object(
            OfficeConverter,
            "_try_backend",
            side_effect=lambda backend, fi, suffix: ConversionResult(
                content_type="pdf", content=pdf, backend_used=backend
            ),
        ):
            result = OfficeConverter.convert(info)

        assert result.backend_used == "libreoffice"
        assert result.content_type == "pdf"
        assert isinstance(result.content, Path)
        assert result.content.parent == cache_dir  # 已切换为缓存内路径
        assert result.content.is_file()
        assert result.content.read_bytes() == pdf.read_bytes()

    def test_com_backend_pdf_also_cached(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """COM 后端产出的 PDF 同样写入缓存。"""
        cache_dir = _redirect_cache(tmp_path, monkeypatch)
        src = _real_file(tmp_path)
        info = _make_info(src)
        pdf = _fake_pdf(tmp_path)

        with patch.object(
            OfficeConverter,
            "_try_backend",
            side_effect=lambda backend, fi, suffix: ConversionResult(
                content_type="pdf", content=pdf, backend_used="com"
            ),
        ):
            result = OfficeConverter.convert(info)

        assert result.backend_used == "com"
        assert result.content.parent == cache_dir
        assert result.content.is_file()

    def test_pure_python_text_result_not_cached(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """pure-python 的 html/outline/table 文本产物不写缓存。"""
        cache_dir = _redirect_cache(tmp_path, monkeypatch)
        src = _real_file(tmp_path)
        info = _make_info(src)

        with patch.object(
            OfficeConverter,
            "_try_backend",
            side_effect=lambda backend, fi, suffix: ConversionResult(
                content_type="html", content="<p>degraded</p>", backend_used="pure-python"
            ),
        ):
            result = OfficeConverter.convert(info)

        assert result.content_type == "html"
        assert result.backend_used == "pure-python"
        # 缓存目录中没有任何写入条目
        assert not cache_dir.exists() or len(list(cache_dir.iterdir())) == 0

    def test_cache_unavailable_degrades_to_backend(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """缓存目录不可写（get_cache_path/put_cache 降级）时转换照常进行。"""
        src = _real_file(tmp_path)
        info = _make_info(src)
        pdf = _fake_pdf(tmp_path)
        # 模拟缓存完全不可用：office_cache_dir 抛异常 → get/put 均降级
        monkeypatch.setattr(
            office_cache, "office_cache_dir", lambda: (_ for _ in ()).throw(OSError("boom"))
        )

        with patch.object(
            OfficeConverter,
            "_try_backend",
            side_effect=lambda backend, fi, suffix: ConversionResult(
                content_type="pdf", content=pdf, backend_used=backend
            ),
        ):
            result = OfficeConverter.convert(info)

        # 未命中缓存，正常走后端，产物保持后端路径（非缓存），不抛异常
        assert result.backend_used == "libreoffice"
        assert result.content_type == "pdf"
        assert result.content == pdf


# ===========================================================================
# 非字典 / 异常输入（对缓存接入的容错延伸）
# ===========================================================================


class TestCacheResilience:
    """缓存读写接入必须在任何异常下都不阻断转换。"""

    def test_get_cache_path_safe_never_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``_get_cache_path_safe`` 在 get_cache_path 抛异常时返回 None 而非抛出。"""
        src = _real_file(tmp_path)
        monkeypatch.setattr(
            office_cache,
            "get_cache_path",
            lambda fi: (_ for _ in ()).throw(OSError("boom")),
        )
        assert OfficeConverter._get_cache_path_safe({"path": str(src)}) is None

    def test_get_cache_path_safe_degrades_on_import_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``_get_cache_path_safe`` 在导入失败（模块缺失）时返回 None。"""
        import builtins

        real_import = builtins.__import__

        def _blocking_import(name, *args, **kwargs):
            if name == "freeassetfilter.services.office_cache":
                raise ImportError("blocked")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _blocking_import)
        assert OfficeConverter._get_cache_path_safe({"path": "C:/dummy/a.docx"}) is None

    def test_convert_never_raises_when_cache_lookup_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """get_cache_path 抛异常时 convert() 照常走后端，不向调用方抛出。"""
        src = _real_file(tmp_path)
        pdf = _fake_pdf(tmp_path)
        _redirect_cache(tmp_path, monkeypatch)
        monkeypatch.setattr(
            office_cache,
            "get_cache_path",
            lambda fi: (_ for _ in ()).throw(OSError("boom")),
        )

        with patch.object(
            OfficeConverter,
            "_try_backend",
            side_effect=lambda backend, fi, suffix: ConversionResult(
                content_type="pdf", content=pdf, backend_used=backend
            ),
        ):
            result = OfficeConverter.convert({"path": str(src), "suffix": "docx"})

        # 缓存查询抛异常被降级为 miss，转换照常走后端并产出 PDF（可落缓存）
        assert result.backend_used == "libreoffice"
        assert result.content_type == "pdf"
        assert isinstance(result.content, Path)
        assert result.content.is_file()


# ===========================================================================
# 能力探测永不抛出
# ===========================================================================


class TestCapabilityDetection:
    """真实环境下的探测函数必须永不抛出且返回 ``bool``。"""

    def test_soffice_available_never_raises(self) -> None:
        """``_soffice_available()`` 永不抛出，返回 ``bool``。"""
        assert isinstance(OfficeConverter._soffice_available(), bool)

    def test_com_available_never_raises(self) -> None:
        """``_com_available()`` 永不抛出，返回 ``bool``。"""
        assert isinstance(OfficeConverter._com_available(), bool)
