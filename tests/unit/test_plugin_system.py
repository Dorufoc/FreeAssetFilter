# -*- coding: utf-8 -*-
"""插件系统核心单元测试"""

import json, os, sys, tempfile, logging, shutil
from pathlib import Path
import pytest

_root = Path(__file__).resolve().parent.parent.parent
if str(_root) not in sys.path: sys.path.insert(0, str(_root))


@pytest.fixture
def plugin_root():
    r = _root / "plugins"
    if r.is_dir(): return str(r)
    pytest.skip("no plugins dir")


@pytest.fixture
def temp_root():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


def make_plugin(pdir, pid):
    import importlib
    d = os.path.join(pdir, pid)
    os.makedirs(d, exist_ok=True)
    m = {"id": pid, "name": "Test "+pid, "version": "1.0.0",
         "description": "", "capabilities": {"preview_handler": {"file_types": ["test"]}}}
    with open(os.path.join(d, "plugin.json"), "w", encoding="utf-8") as f:
        json.dump(m, f)
    with open(os.path.join(d, "__init__.py"), "w", encoding="utf-8") as f:
        f.write("""
import logging
from freeassetfilter.plugins.base_plugin import BasePlugin
from freeassetfilter.plugins.protocol import PreviewCapability

class TestPlugin(BasePlugin):
    def on_load(self, pm): pass
    def on_unload(self): pass
    def get_preview_capabilities(self):
        return [PreviewCapability(self.plugin_id, ["test"], lambda: None, 50)]
"""
    )
    return d


# ===== Discovery tests =====

def test_discover_real_plugins():
    from freeassetfilter.plugins.plugin_manager import PluginManager
    pm = PluginManager(str(_root / "plugins"))
    d = pm.discover()
    assert "webview2_preview" in d

def test_discover_empty():
    from freeassetfilter.plugins.plugin_manager import PluginManager
    pm = PluginManager(tempfile.mkdtemp())
    assert pm.discover() == {}

def test_discover_valid(temp_root):
    from freeassetfilter.plugins.plugin_manager import PluginManager
    pm = PluginManager(temp_root)
    make_plugin(temp_root, "my_plugin")
    d = pm.discover()
    assert "my_plugin" in d

def test_discover_skips_no_manifest(temp_root):
    from freeassetfilter.plugins.plugin_manager import PluginManager
    pm = PluginManager(temp_root)
    os.makedirs(os.path.join(temp_root, "empty_dir"))
    assert "empty_dir" not in pm.discover()

def test_discover_skips_bad_json(temp_root):
    from freeassetfilter.plugins.plugin_manager import PluginManager
    pm = PluginManager(temp_root)
    d = os.path.join(temp_root, "bad")
    os.makedirs(d)
    with open(os.path.join(d, "plugin.json"), "w") as f: f.write("not json")
    assert "bad" not in pm.discover()

def test_discover_skips_no_id(temp_root):
    from freeassetfilter.plugins.plugin_manager import PluginManager
    pm = PluginManager(temp_root)
    d = os.path.join(temp_root, "no_id")
    os.makedirs(d)
    with open(os.path.join(d, "plugin.json"), "w", encoding="utf-8") as f:
        json.dump({"name":"x"}, f)
    assert "no_id" not in pm.discover()


# ===== Loading tests =====

def test_load_real():
    from freeassetfilter.plugins.plugin_manager import PluginManager
    pm = PluginManager(str(_root / "plugins"))
    pm.discover()
    p = pm.load("webview2_preview")
    assert p is not None
    assert p.plugin_id == "webview2_preview"

def test_load_nonexistent():
    from freeassetfilter.plugins.plugin_manager import PluginManager
    pm = PluginManager(str(_root / "plugins"))
    assert pm.load("no_such_plugin") is None

def test_load_twice():
    from freeassetfilter.plugins.plugin_manager import PluginManager
    pm = PluginManager(str(_root / "plugins"))
    pm.discover()
    p1 = pm.load("webview2_preview")
    p2 = pm.load("webview2_preview")
    assert p1 is p2

def test_load_all():
    from freeassetfilter.plugins.plugin_manager import PluginManager
    pm = PluginManager(str(_root / "plugins"))
    pm.discover()
    loaded = pm.load_all()
    assert "webview2_preview" in loaded


# ===== Capability tests =====

def test_capability_register(temp_root):
    from freeassetfilter.plugins.plugin_manager import PluginManager
    pm = PluginManager(temp_root)
    make_plugin(temp_root, "cap_test")
    pm.discover(); pm.load("cap_test")
    h = pm.get_preview_handler("test")
    assert h is not None and h.plugin_id == "cap_test"

def test_query_html():
    from freeassetfilter.plugins.plugin_manager import PluginManager
    pm = PluginManager(str(_root / "plugins"))
    pm.discover(); pm.load("webview2_preview")
    h = pm.get_preview_handler("html")
    assert h is not None and h.plugin_id == "webview2_preview"

def test_query_htm():
    from freeassetfilter.plugins.plugin_manager import PluginManager
    pm = PluginManager(str(_root / "plugins"))
    pm.discover(); pm.load("webview2_preview")
    assert pm.has_preview_handler("htm") is True

def test_no_handler():
    from freeassetfilter.plugins.plugin_manager import PluginManager
    pm = PluginManager(str(_root / "plugins"))
    pm.discover(); pm.load("webview2_preview")
    assert pm.get_preview_handler("xyz") is None

def test_supported_types():
    from freeassetfilter.plugins.plugin_manager import PluginManager
    pm = PluginManager(str(_root / "plugins"))
    pm.discover(); pm.load("webview2_preview")
    t = pm.get_supported_preview_types()
    assert "html" in t and "htm" in t


# ===== Unload tests =====

def test_unload_removes_handler(temp_root):
    from freeassetfilter.plugins.plugin_manager import PluginManager
    pm = PluginManager(temp_root)
    make_plugin(temp_root, "u")
    pm.discover(); pm.load("u")
    assert pm.has_preview_handler("test") is True
    pm.unload("u")
    assert pm.has_preview_handler("test") is False

def test_unload_nonexistent():
    from freeassetfilter.plugins.plugin_manager import PluginManager
    pm = PluginManager(str(_root / "plugins"))
    assert pm.unload("nonexistent") is False

def test_unload_all(temp_root):
    from freeassetfilter.plugins.plugin_manager import PluginManager
    pm = PluginManager(temp_root)
    make_plugin(temp_root, "a"); make_plugin(temp_root, "b")
    pm.discover(); pm.load_all()
    assert len(pm.loaded_plugins) == 2
    pm.unload_all()
    assert len(pm.loaded_plugins) == 0


# ===== Lifecycle =====

def test_initialize_shutdown():
    from freeassetfilter.plugins.plugin_manager import PluginManager
    pm = PluginManager(str(_root / "plugins"))
    pm.initialize()
    assert "webview2_preview" in pm.loaded_plugins
    assert pm.has_preview_handler("html") is True
    pm.shutdown()
    assert len(pm.loaded_plugins) == 0
    assert pm.get_supported_preview_types() == []

def test_initialize_twice():
    from freeassetfilter.plugins.plugin_manager import PluginManager
    pm = PluginManager(str(_root / "plugins"))
    pm.initialize(); pm.initialize()
    assert "webview2_preview" in pm.loaded_plugins
    pm.shutdown()


# ===== PluginInfo tests =====

def test_plugin_info_from_manifest():
    from freeassetfilter.plugins.protocol import PluginInfo
    m = {"id": "p1", "name": "P1", "version": "2.0.0", "description": "d", "author": "a"}
    i = PluginInfo.from_manifest(m)
    assert i.plugin_id == "p1" and i.name == "P1"
    assert i.version == "2.0.0" and i.description == "d" and i.author == "a"

def test_plugin_info_minimal():
    from freeassetfilter.plugins.protocol import PluginInfo
    i = PluginInfo.from_manifest({})
    assert i.plugin_id == "unknown" and i.name == "未知插件" and i.version == "0.0.0"

def test_capability_matches():
    from freeassetfilter.plugins.protocol import PreviewCapability
    c = PreviewCapability("t", ["html", "htm"], None)
    assert c.matches("html") and c.matches("HTML") and c.matches("htm")
    assert not c.matches("txt")

def test_capability_type_name():
    from freeassetfilter.plugins.protocol import PreviewCapability
    c = PreviewCapability("webview2_preview", ["html"], None)
    assert c.preview_type_name == "plugin_webview2_preview"