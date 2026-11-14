"""``sopeek.services.previewer_registry``：扩展名 → 预览器类的解析。

注册表是纯映射服务，不应在导入时拉起 QtWidgets；解析到的类必须真的是
预览器（有 ``set_file``）。
"""

from __future__ import annotations


import pytest

from sopeek.services.previewer_registry import PreviewerRegistry


pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean_registry():
    """每个用例后恢复注册表，避免测试之间相互污染。"""
    snapshot = dict(PreviewerRegistry._EXTENSION_MAP)
    cache_snapshot = dict(PreviewerRegistry._CLASS_CACHE)
    yield
    PreviewerRegistry._EXTENSION_MAP.clear()
    PreviewerRegistry._EXTENSION_MAP.update(snapshot)
    PreviewerRegistry._CLASS_CACHE.clear()
    PreviewerRegistry._CLASS_CACHE.update(cache_snapshot)


def test_unknown_extension_returns_none() -> None:
    assert PreviewerRegistry.get_previewer_class({"suffix": "definitely-not-a-suffix"}) is None
    assert PreviewerRegistry.get_previewer_class({}) is None


def test_directory_maps_to_folder_previewer(qapp) -> None:
    cls = PreviewerRegistry.get_previewer_class({"is_dir": True})
    assert cls is not None
    assert cls.__name__ == "FolderPreviewerLayout"


@pytest.mark.parametrize("suffix", ["jpg", "JPG", ".png", "webp"])
def test_image_suffixes_are_case_and_dot_insensitive(qapp, suffix: str) -> None:
    cls = PreviewerRegistry.get_previewer_class({"suffix": suffix})
    assert cls is not None
    assert cls.__name__ == "ImagePreviewerLayout"


def test_pdf_and_text_have_distinct_previewers(qapp) -> None:
    pdf = PreviewerRegistry.get_previewer_class({"suffix": "pdf"})
    text = PreviewerRegistry.get_previewer_class({"suffix": "py"})
    assert pdf.__name__ == "PdfPreviewerLayout"
    assert text.__name__ == "TextPreviewerLayout"
    assert pdf is not text


def test_class_is_cached_between_calls(qapp) -> None:
    first = PreviewerRegistry.get_previewer_class({"suffix": "mkv"})
    second = PreviewerRegistry.get_previewer_class({"suffix": "mkv"})
    assert first is second


def test_register_and_unregister_roundtrip(qapp) -> None:
    class _Fake:
        pass

    PreviewerRegistry.register(".zzz", "sopeek.services.previewer_registry", "_FakeMarker")
    assert PreviewerRegistry._EXTENSION_MAP["zzz"][0] == "sopeek.services.previewer_registry"

    PreviewerRegistry.unregister("zzz")
    assert "zzz" not in PreviewerRegistry._EXTENSION_MAP
    assert PreviewerRegistry.get_previewer_class({"suffix": "zzz"}) is None


def test_registry_module_does_not_import_qtwidgets() -> None:
    """纯映射服务：导入注册表本身不应把 QtWidgets 拉进进程。"""
    import subprocess
    import sys as _sys
    from pathlib import Path

    src = Path(__file__).resolve().parents[3] / "src"
    code = (
        "import sys; sys.path.insert(0, r'%s');"
        "import sopeek.services.previewer_registry;"
        "print('PySide6.QtWidgets' in sys.modules)"
    ) % src
    out = subprocess.run(
        [_sys.executable, "-c", code], capture_output=True, text=True, timeout=120
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().endswith("False")
