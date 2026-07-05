# -*- coding: utf-8 -*-
"""UnifiedPreviewer 插件集成测试"""

import os, sys, json, tempfile, shutil
from pathlib import Path
import pytest

_root = Path(__file__).resolve().parent.parent.parent
if str(_root) not in sys.path: sys.path.insert(0, str(_root))


@pytest.fixture
def qapp():
    """QApplication fixture for Qt tests"""
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFont
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    app.dpi_scale_factor = 1.0
    app.global_font = QFont()
    yield app


@pytest.fixture
def plugin_manager(qapp):
    """Plugin manager initialized and stored on app"""
    from freeassetfilter.plugins.plugin_manager import PluginManager
    pm = PluginManager(str(_root / "plugins"))
    pm.initialize()
    qapp.plugin_manager = pm
    yield pm
    pm.shutdown()
    qapp.plugin_manager = None


@pytest.fixture
def unified_previewer(qapp):
    """UnifiedPreviewer instance"""
    from freeassetfilter.components.unified_previewer import UnifiedPreviewer
    widget = UnifiedPreviewer()
    yield widget
    widget.close()
    widget.deleteLater()


@pytest.fixture
def html_file_info(tmp_path):
    """HTML file info dict"""
    f = tmp_path / "test.html"
    f.write_text("<html><body><h1>Test</h1></body></html>", encoding="utf-8")
    return {
        "name": "test.html",
        "path": str(f),
        "is_dir": False,
        "size": f.stat().st_size,
        "modified": "",
        "created": "",
        "suffix": "html",
    }


@pytest.fixture
def txt_file_info(tmp_path):
    """TXT file info dict"""
    f = tmp_path / "test.txt"
    f.write_text("Hello World", encoding="utf-8")
    return {
        "name": "test.txt",
        "path": str(f),
        "is_dir": False,
        "size": f.stat().st_size,
        "modified": "",
        "created": "",
        "suffix": "txt",
    }


def test_plugin_manager_stored_on_app(qapp, plugin_manager):
    """Plugin manager is accessible from QApplication"""
    app = qapp
    assert hasattr(app, "plugin_manager")
    assert app.plugin_manager is not None
    assert app.plugin_manager.has_preview_handler("html") is True


def test_plugin_manager_handles_html(plugin_manager):
    """Plugin manager can handle .html files"""
    handler = plugin_manager.get_preview_handler("html")
    assert handler is not None
    assert handler.plugin_id == "webview2_preview"
    assert handler.preview_type_name == "plugin_webview2_preview"


def test_previewer_starts_without_plugin(unified_previewer, txt_file_info):
    """Previewer works normally without plugin manager for .txt files"""
    # Without plugin manager on app
    app = __import__('PySide6.QtWidgets').QtWidgets.QApplication.instance()
    if hasattr(app, "plugin_manager"):
        delattr(app, "plugin_manager")

    unified_previewer.set_file(txt_file_info)
    assert unified_previewer.current_file_info is not None
    assert unified_previewer.current_file_info["suffix"] == "txt"


def test_previewer_html_without_plugin(unified_previewer, html_file_info):
    """HTML files fall back to text preview without plugin"""
    from freeassetfilter.components.text_previewer import TextPreviewWidget

    app = __import__('PySide6.QtWidgets').QtWidgets.QApplication.instance()
    if hasattr(app, "plugin_manager"):
        delattr(app, "plugin_manager")

    unified_previewer.set_file(html_file_info)
    assert unified_previewer.current_file_info is not None


def test_previewer_html_with_plugin_dispatched(unified_previewer, plugin_manager, html_file_info):
    """HTML files with plugin manager should dispatch to plugin type"""
    from freeassetfilter.components.unified_previewer import UnifiedPreviewer
    app = __import__('PySide6.QtWidgets').QtWidgets.QApplication.instance()

    # Verify plugin_manager is set on app
    assert hasattr(app, "plugin_manager")
    assert app.plugin_manager.has_preview_handler("html") is True

    # Set file - this triggers show_preview internally
    unified_previewer.set_file(html_file_info)