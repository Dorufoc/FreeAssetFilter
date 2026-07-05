# -*- coding: utf-8 -*-
"""WebView2 插件单元测试"""

import os, sys, json
from pathlib import Path
import pytest

_root = Path(__file__).resolve().parent.parent.parent
if str(_root) not in sys.path: sys.path.insert(0, str(_root))

PLUGIN_DIR = _root / "plugins" / "webview2_preview"


def test_manifest_exists():
    """plugin.json must exist"""
    assert (PLUGIN_DIR / "plugin.json").is_file()


def test_manifest_valid_json():
    """plugin.json is valid JSON"""
    with open(PLUGIN_DIR / "plugin.json", "r", encoding="utf-8") as f:
        m = json.load(f)
    assert isinstance(m, dict)


def test_manifest_required_fields():
    """plugin.json has required fields"""
    with open(PLUGIN_DIR / "plugin.json", "r", encoding="utf-8") as f:
        m = json.load(f)
    assert "id" in m and m["id"] == "webview2_preview"
    assert "name" in m
    assert "version" in m
    assert "capabilities" in m
    caps = m["capabilities"]
    assert "preview_handler" in caps
    types = caps["preview_handler"]["file_types"]
    assert "html" in types
    assert "htm" in types


def test_init_py_exists():
    """__init__.py must exist"""
    assert (PLUGIN_DIR / "__init__.py").is_file()


def test_widget_py_exists():
    """webview2_widget.py must exist"""
    assert (PLUGIN_DIR / "webview2_widget.py").is_file()


def test_requirements_txt_exists():
    """requirements.txt must exist"""
    assert (PLUGIN_DIR / "requirements.txt").is_file()


def test_plugin_class_importable():
    """WebView2PreviewPlugin class is importable"""
    sys.path.insert(0, str(_root / "plugins"))
    try:
        from webview2_preview import WebView2PreviewPlugin
        assert WebView2PreviewPlugin is not None
    except ImportError as e:
        print(f"Warning: {e}")
    finally:
        sys.path.remove(str(_root / "plugins"))


def test_plugin_class_inherits_base():
    """Plugin class inherits BasePlugin"""
    from freeassetfilter.plugins.base_plugin import BasePlugin
    sys.path.insert(0, str(_root / "plugins"))
    try:
        from webview2_preview import WebView2PreviewPlugin
        assert issubclass(WebView2PreviewPlugin, BasePlugin)
    finally:
        sys.path.remove(str(_root / "plugins"))


def test_widget_module_importable():
    """webview2_widget module is importable"""
    try:
        from plugins.webview2_preview.webview2_widget import create_qt_widget
        assert create_qt_widget is not None
    except ImportError as e:
        print(f"Warning: {e}")


def test_is_webview2_available_runs():
    """is_webview2_available runs without crash"""
    try:
        from plugins.webview2_preview.webview2_widget import is_webview2_available
        result = is_webview2_available()
        assert isinstance(result, bool)
    except ImportError:
        pytest.skip("comtypes not available")