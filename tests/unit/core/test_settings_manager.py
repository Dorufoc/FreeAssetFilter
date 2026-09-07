# -*- coding: utf-8 -*-
# targets: core.managers.settings_manager_v2
"""``SettingsManagerV2`` 单元测试（新版唯一设置管理器）。

旧版 ``core/managers/settings_manager.py``（V1）已随旧版组件层移除；
本文件为 V2 的唯一权威测试。覆盖：

* 模块/默认树结构（version=2、appearance.mica / background 节点）
* ``load`` —— 文件缺失自动生成、损坏 JSON 回退、旧文件平滑升级
  （缺键补默认、opacity→transparency 语义迁移）
* ``get`` / ``set`` —— 点号路径、默认值回退、无变化返回 False
* ``save`` / ``reset_to_defaults`` / ``get_all`` —— 写读往返一致

所有测试均绑定 ``tmp_path`` 的临时设置文件，绝不触碰真实
``data/settings_v2.json``。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from freeassetfilter.core.managers.settings_manager_v2 import (
    DEFAULT_SETTINGS_V2,
    SettingsManagerV2,
)


def _read_json(path: Path) -> Dict[str, Any]:
    """读取 JSON 设置文件内容（断言辅助）。"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# =============================================================================
# 模块与默认树
# =============================================================================
class TestModuleAndDefaults:
    """模块结构与默认树"""

    def test_defaults_tree_shape(self) -> None:
        """默认树含 version=2 与 appearance 关键节点。"""
        assert DEFAULT_SETTINGS_V2["version"] == 2
        appearance = DEFAULT_SETTINGS_V2["appearance"]
        assert appearance["theme"] == "dark"
        assert appearance["theme_mode"] == "dark"
        assert "colors" in appearance
        assert appearance["colors"]["accent"]["primary"] == "#3A9DCB"
        assert appearance["mica"]["blur_radius"] == 200
        assert appearance["background"]["mode"] == "mica"

    def test_public_api(self) -> None:
        """公开 API 面：get/set/load/save/get_all/reset_to_defaults/file_path。"""
        v2_api = {"get", "set", "load", "save", "reset_to_defaults", "get_all"}
        public = {m for m in dir(SettingsManagerV2) if not m.startswith("_")}
        assert v2_api.issubset(public)


# =============================================================================
# load
# =============================================================================
class TestLoad:
    """加载与回退"""

    def test_load_creates_missing_file(self, tmp_path: Path) -> None:
        """文件缺失时 load 后自动生成默认树文件。"""
        v2_file: Path = tmp_path / "fresh.json"
        v2: SettingsManagerV2 = SettingsManagerV2(file_path=str(v2_file))
        data = v2.load()
        assert data["version"] == 2
        assert v2_file.exists()

    def test_load_corrupted_json_falls_back(self, tmp_path: Path) -> None:
        """损坏 JSON 不抛异常，回退默认树。"""
        v2_file: Path = tmp_path / "bad.json"
        v2_file.write_text("{broken", encoding="utf-8")
        v2: SettingsManagerV2 = SettingsManagerV2(file_path=str(v2_file))
        assert v2.load()["version"] == 2
        assert v2.get("appearance.theme") == "dark"

    def test_load_wrong_root_type_falls_back(self, tmp_path: Path) -> None:
        """根节点非 dict（如 list）回退默认树（V2 优于旧版 V1 的校验）。"""
        v2_file: Path = tmp_path / "list.json"
        v2_file.write_text("[1, 2, 3]", encoding="utf-8")
        v2: SettingsManagerV2 = SettingsManagerV2(file_path=str(v2_file))
        assert v2.load()["version"] == 2

    def test_load_merges_old_file_missing_keys(self, tmp_path: Path) -> None:
        """旧文件缺键：加载后补默认值，已存值保留。"""
        v2_file: Path = tmp_path / "old.json"
        v2_file.write_text(
            json.dumps(
                {
                    "version": 2,
                    "appearance": {
                        "theme": "light",
                        "accent_color": "#FF0000",
                        "mica": {"blur_radius": 120},
                    },
                }
            ),
            encoding="utf-8",
        )
        v2: SettingsManagerV2 = SettingsManagerV2(file_path=str(v2_file))
        v2.load()
        assert v2.get("appearance.theme") == "light"
        assert v2.get("appearance.accent_color") == "#FF0000"
        assert v2.get("appearance.mica.blur_radius") == 120
        # 缺省键补齐
        assert v2.get("appearance.theme_mode") == "dark"
        assert v2.get("appearance.mica.saturation") == 4.5
        bg = v2.get("appearance.background")
        assert bg["mode"] == "mica"

    def test_load_opacity_to_transparency_migration(self, tmp_path: Path) -> None:
        """旧字段 ``background.opacity`` 语义迁移为 ``transparency``。"""
        v2_file: Path = tmp_path / "migrate.json"
        v2_file.write_text(
            json.dumps(
                {
                    "version": 2,
                    "appearance": {
                        "background": {"mode": "image", "opacity": 20},
                    },
                }
            ),
            encoding="utf-8",
        )
        v2: SettingsManagerV2 = SettingsManagerV2(file_path=str(v2_file))
        v2.load()
        bg = v2.get("appearance.background")
        assert bg.get("transparency") == 80  # 100 - 20
        assert "opacity" not in bg


# =============================================================================
# get / set
# =============================================================================
class TestGetSet:
    """读写语义"""

    def test_get_default_fallback(self, tmp_path: Path) -> None:
        v2: SettingsManagerV2 = SettingsManagerV2(file_path=str(tmp_path / "s.json"))
        v2.load()
        assert v2.get("nonexistent.key", "fallback") == "fallback"
        assert v2.get("nonexistent.key") is None

    def test_set_roundtrip_and_no_change(self, tmp_path: Path) -> None:
        v2: SettingsManagerV2 = SettingsManagerV2(file_path=str(tmp_path / "s.json"))
        v2.load()
        assert v2.set("appearance.theme", "light") is True
        assert v2.get("appearance.theme") == "light"
        assert v2.set("appearance.theme", "light") is False  # 无变化

    def test_set_creates_intermediate_dicts(self, tmp_path: Path) -> None:
        v2: SettingsManagerV2 = SettingsManagerV2(file_path=str(tmp_path / "s.json"))
        v2.load()
        assert v2.set("a.b.c.d", "value") is True
        assert v2.get("a.b.c.d") == "value"


# =============================================================================
# save / reset / get_all
# =============================================================================
class TestSaveAndReset:
    """写盘与重置"""

    def test_save_roundtrip_persists(self, tmp_path: Path) -> None:
        v2_file: Path = tmp_path / "roundtrip.json"
        v2a: SettingsManagerV2 = SettingsManagerV2(file_path=str(v2_file))
        v2a.load()
        v2a.set("appearance.theme", "light")
        v2a.set("appearance.accent_color", "#3A9DCB")
        v2a.save()

        v2b: SettingsManagerV2 = SettingsManagerV2(file_path=str(v2_file))
        v2b.load()
        assert v2b.get("appearance.theme") == "light"
        assert v2b.get("appearance.accent_color") == "#3A9DCB"

    def test_reset_to_defaults(self, tmp_path: Path) -> None:
        v2: SettingsManagerV2 = SettingsManagerV2(file_path=str(tmp_path / "s.json"))
        v2.load()
        v2.set("appearance.theme", "light")
        v2.reset_to_defaults()
        assert v2.get("appearance.theme") == "dark"

    def test_get_all_returns_data(self, tmp_path: Path) -> None:
        v2: SettingsManagerV2 = SettingsManagerV2(file_path=str(tmp_path / "s.json"))
        v2.load()
        assert v2.get_all()["version"] == 2


# =============================================================================
# appearance.background（自定义窗口背景）
# =============================================================================
class TestBackgroundSettings:
    """V2 ``appearance.background`` 节点测试"""

    def test_background_roundtrip_persists(self, tmp_path: Path) -> None:
        """写读往返：set + save 后新实例 load 读回值与写入完全一致。"""
        v2_file: Path = tmp_path / "bg_roundtrip.json"
        expected: Dict[str, Any] = {"mode": "image", "image": "custom_background.png"}

        v2a: SettingsManagerV2 = SettingsManagerV2(file_path=str(v2_file))
        v2a.load()
        assert v2a.set("appearance.background", expected) is True
        v2a.save()

        v2b: SettingsManagerV2 = SettingsManagerV2(file_path=str(v2_file))
        v2b.load()
        assert v2b.get("appearance.background.mode") == "image"
        assert v2b.get("appearance.background.image") == "custom_background.png"