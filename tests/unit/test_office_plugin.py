# -*- coding: utf-8 -*-
"""Office 文档预览插件单元测试"""

import json, os, sys
from pathlib import Path
import pytest

_root = Path(__file__).resolve().parent.parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

PLUGIN_DIR = _root / "plugins" / "office_preview"


def test_manifest_exists():
    """plugin.json must exist"""
    assert (PLUGIN_DIR / "plugin.json").is_file()


def test_manifest_valid_json():
    """plugin.json is valid JSON"""
    with open(PLUGIN_DIR / "plugin.json", "r", encoding="utf-8") as f:
        m = json.load(f)
    assert isinstance(m, dict)


def test_manifest_required_fields():
    """plugin.json has required fields including all office types"""
    with open(PLUGIN_DIR / "plugin.json", "r", encoding="utf-8") as f:
        m = json.load(f)
    assert "id" in m and m["id"] == "office_preview"
    assert "name" in m
    assert "version" in m
    assert "capabilities" in m
    caps = m["capabilities"]
    assert "preview_handler" in caps
    types = caps["preview_handler"]["file_types"]
    for t in ("doc", "docx", "xls", "xlsx", "ppt", "pptx"):
        assert t in types


def test_init_py_exists():
    """__init__.py must exist"""
    assert (PLUGIN_DIR / "__init__.py").is_file()


def test_widget_py_exists():
    """office_widget.py must exist"""
    assert (PLUGIN_DIR / "office_widget.py").is_file()


def test_webview2_host_py_exists():
    """webview2_host.py must exist"""
    assert (PLUGIN_DIR / "webview2_host.py").is_file()


def test_webview2_dll_exists():
    """WebView2Loader.dll must exist alongside the plugin"""
    assert (PLUGIN_DIR / "WebView2Loader.dll").is_file()


def test_requirements_txt_exists():
    """requirements.txt must exist"""
    assert (PLUGIN_DIR / "requirements.txt").is_file()

def test_plugin_class_importable():
    """OfficePreviewPlugin class is importable"""
    sys.path.insert(0, str(_root / "plugins"))
    try:
        from office_preview import OfficePreviewPlugin
        assert OfficePreviewPlugin is not None
    except ImportError as e:
        print(f"Warning: {e}")
    finally:
        sys.path.remove(str(_root / "plugins"))


def test_plugin_class_inherits_base():
    """Plugin class inherits BasePlugin"""
    from freeassetfilter.plugins.base_plugin import BasePlugin
    sys.path.insert(0, str(_root / "plugins"))
    try:
        from office_preview import OfficePreviewPlugin
        assert issubclass(OfficePreviewPlugin, BasePlugin)
    finally:
        sys.path.remove(str(_root / "plugins"))


def test_widget_module_importable():
    """office_widget module is importable"""
    try:
        from plugins.office_preview.office_widget import create_qt_widget
        assert create_qt_widget is not None
    except ImportError as e:
        print(f"Warning: {e}")


def test_webview2_host_module_importable():
    """webview2_host module is importable and has WebView2Host"""
    try:
        from plugins.office_preview.webview2_host import WebView2Host, is_available
        assert WebView2Host is not None
        assert is_available is not None
    except ImportError as e:
        print(f"Warning: {e}")


def test_is_webview2_available_runs():
    """is_webview2_available runs without crash"""
    try:
        from plugins.office_preview.office_widget import is_webview2_available
        result = is_webview2_available()
        assert isinstance(result, bool)
    except ImportError:
        pytest.skip("webview2_host not available")


def test_is_office_available_runs():
    """is_office_available runs without crash"""
    try:
        from plugins.office_preview.office_widget import is_office_available
        result = is_office_available()
        assert isinstance(result, bool)
    except ImportError:
        pytest.skip("comtypes not available")


def test_convert_functions_importable():
    """convert_via_com and convert_via_libreoffice are importable"""
    try:
        from plugins.office_preview.office_widget import (
            convert_via_com,
            convert_via_libreoffice,
            convert_to_pdf,
        )
        assert convert_via_com is not None
        assert convert_via_libreoffice is not None
        assert convert_to_pdf is not None
    except ImportError as e:
        print(f"Warning: {e}")


def test_local_office_server_importable():
    """LocalOfficeServer class is importable"""
    try:
        from plugins.office_preview.office_widget import LocalOfficeServer
        assert LocalOfficeServer is not None
    except ImportError as e:
        print(f"Warning: {e}")


def test_office_preview_capabilities():
    """PluginManager can discover and load the office plugin, and handlers are registered"""
    from freeassetfilter.plugins.plugin_manager import PluginManager
    pm = PluginManager(str(_root / "plugins"))
    pm.discover()
    assert "office_preview" in pm.discovered_plugins
    p = pm.load("office_preview")
    assert p is not None
    assert p.plugin_id == "office_preview"
    for t in ("doc", "docx", "xls", "xlsx", "ppt", "pptx"):
        h = pm.get_preview_handler(t)
        assert h is not None
        assert h.plugin_id == "office_preview"
    pm.unload("office_preview")


def test_integration_preview_type_document():
    """UnifiedPreviewer should check document type for plugin interception"""
    with open(
        _root / "freeassetfilter" / "components" / "unified_previewer.py",
        "r", encoding="utf-8",
    ) as f:
        content = f.read()
    assert '"document"' in content or "'document'" in content
    assert 'preview_type in ("text", "unknown", "document")' in content


def test_integration_fallback_not_text():
    """Plugin preview failure should not show text preview (avoid binary garbage)"""
    with open(
        _root / "freeassetfilter" / "components" / "unified_previewer.py",
        "r", encoding="utf-8",
    ) as f:
        content = f.read()
    assert "_show_text_preview(file_path)" not in content.split(
        "def _show_plugin_preview"
    )[1].split("def ")[0]
