# -*- coding: utf-8 -*-
"""SettingsManagerV2 单元测试（todo 14 新建；此前仅有 v1 测试）。

覆盖 ``freeassetfilter/core/managers/settings_manager_v2.py``：

* 默认树含 ``performance.profile == "balanced"``；
* ``performance.profile`` 点号读写往返；
* save → load → merge 往返保持（三档值 + 缺键回退 + 非法值回退）；
* 既有 appearance 键不受影响（只增不改）。

验证命令：
    python -m pytest tests/unit/core/test_settings_manager_v2.py -q --timeout 60
"""

from __future__ import annotations

from pathlib import Path

import pytest

from freeassetfilter.core.managers.settings_manager_v2 import (
    DEFAULT_PERFORMANCE_PROFILE,
    DEFAULT_SETTINGS_V2,
    PERFORMANCE_PROFILES,
    SettingsManagerV2,
)

pytestmark = pytest.mark.unit


def _fresh_v2(tmp_path: Path) -> SettingsManagerV2:
    """构造绑定临时文件的 V2 管理器。"""
    return SettingsManagerV2(str(tmp_path / "settings_v2.json"))


class TestPerformanceProfileDefaults:
    """默认树形状。"""

    def test_default_profile_is_balanced(self) -> None:
        """默认档位为 balanced，三档常量齐全。"""
        assert DEFAULT_SETTINGS_V2["performance"]["profile"] == "balanced"
        assert DEFAULT_PERFORMANCE_PROFILE == "balanced"
        assert tuple(PERFORMANCE_PROFILES) == (
            "performance",
            "balanced",
            "powersave",
        )

    def test_fresh_load_has_profile(self, tmp_path: Path) -> None:
        """新文件加载即含 performance.profile。"""
        v2 = _fresh_v2(tmp_path)
        v2.load()
        assert v2.get("performance.profile") == "balanced"


class TestPerformanceProfileRoundTrip:
    """点号读写 + 落盘往返（stale state 对抗）。"""

    @pytest.mark.parametrize("mode", ["performance", "balanced", "powersave"])
    def test_set_get_roundtrip(self, tmp_path: Path, mode: str) -> None:
        """三档值内存读写往返（set 无变化时返回 False 系正常语义）。"""
        v2 = _fresh_v2(tmp_path)
        v2.load()
        v2.set("performance.profile", mode)
        assert v2.get("performance.profile") == mode
        # 相同值二次写入返回 False（无变化）。
        assert v2.set("performance.profile", mode) is False

    @pytest.mark.parametrize("mode", ["performance", "balanced", "powersave"])
    def test_save_load_merge_keeps_value(self, tmp_path: Path, mode: str) -> None:
        """save → 新实例 load → merge 后值保持（往返不丢失）。"""
        tmp_file = str(tmp_path / "settings_v2.json")
        v2 = SettingsManagerV2(tmp_file)
        v2.load()
        v2.set("performance.profile", mode)
        v2.save()

        fresh = SettingsManagerV2(tmp_file)
        fresh.load()
        assert fresh.get("performance.profile") == mode
        # 再存一次仍保持（merge 幂等）。
        fresh.save()
        third = SettingsManagerV2(tmp_file)
        third.load()
        assert third.get("performance.profile") == mode

    def test_old_file_missing_key_merges_default(
        self, tmp_path: Path
    ) -> None:
        """旧文件缺 performance 域：合并后回退 balanced（不抛异常）。"""
        import json

        tmp_file = tmp_path / "settings_v2.json"
        tmp_file.write_text(
            json.dumps({"version": 2, "appearance": {"theme": "dark"}}),
            encoding="utf-8",
        )
        v2 = SettingsManagerV2(str(tmp_file))
        v2.load()
        assert v2.get("performance.profile") == "balanced"

    def test_invalid_value_falls_back_default(self, tmp_path: Path) -> None:
        """非法档位值：合并时回退 balanced。"""
        import json

        tmp_file = tmp_path / "settings_v2.json"
        tmp_file.write_text(
            json.dumps(
                {"version": 2, "performance": {"profile": "turbo-ultra"}}
            ),
            encoding="utf-8",
        )
        v2 = SettingsManagerV2(str(tmp_file))
        v2.load()
        assert v2.get("performance.profile") == "balanced"


class TestNoRegressionOnAppearance:
    """只增不改：appearance 既有键合并行为不变。"""

    def test_appearance_keys_intact(self, tmp_path: Path) -> None:
        """appearance 域默认键齐全，profile 新增不破坏旧结构。"""
        v2 = _fresh_v2(tmp_path)
        settings = v2.load()
        assert settings["appearance"]["theme"] == "dark"
        assert settings["appearance"]["background"]["mode"] == "mica"
        assert settings["performance"]["profile"] == "balanced"


class TestGeneralLayoutMode:
    """general.layout_mode：默认值、往返与合并（主界面布局切换）。"""

    def test_default_layout_mode_is_workspace(self) -> None:
        """默认树含 general.layout_mode == workspace。"""
        assert DEFAULT_SETTINGS_V2["general"]["layout_mode"] == "workspace"

    def test_fresh_load_has_layout_mode(self, tmp_path: Path) -> None:
        """新文件加载即含 general.layout_mode（默认 workspace）。"""
        v2 = _fresh_v2(tmp_path)
        v2.load()
        assert v2.get("general.layout_mode") == "workspace"

    @pytest.mark.parametrize("mode", ["classic", "workspace"])
    def test_save_load_merge_keeps_value(self, tmp_path: Path, mode: str) -> None:
        """save → 新实例 load → merge 后布局模式保持（往返不丢失）。"""
        tmp_file = str(tmp_path / "settings_v2.json")
        v2 = SettingsManagerV2(tmp_file)
        v2.load()
        v2.set("general.layout_mode", mode)
        v2.save()

        fresh = SettingsManagerV2(tmp_file)
        fresh.load()
        assert fresh.get("general.layout_mode") == mode

    def test_old_file_missing_key_merges_default(self, tmp_path: Path) -> None:
        """旧文件缺 general 域：合并后回退 workspace（不抛异常）。"""
        import json

        tmp_file = tmp_path / "settings_v2.json"
        tmp_file.write_text(
            json.dumps({"version": 2, "appearance": {"theme": "dark"}}),
            encoding="utf-8",
        )
        v2 = SettingsManagerV2(str(tmp_file))
        v2.load()
        assert v2.get("general.layout_mode") == "workspace"

    def test_invalid_value_falls_back_default(self, tmp_path: Path) -> None:
        """非法布局模式：合并时回退 workspace。"""
        import json

        tmp_file = tmp_path / "settings_v2.json"
        tmp_file.write_text(
            json.dumps(
                {"version": 2, "general": {"layout_mode": "bogus-layout"}}
            ),
            encoding="utf-8",
        )
        v2 = SettingsManagerV2(str(tmp_file))
        v2.load()
        assert v2.get("general.layout_mode") == "workspace"


class TestGeneralBooleanToggles:
    """general.enable_ai_entry / include_remote_drives：默认、往返与非法值回退。"""

    def test_defaults_are_false(self) -> None:
        """默认树两个开关均为 False（AI 入口与网络盘/光驱默认关闭）。"""
        assert DEFAULT_SETTINGS_V2["general"]["enable_ai_entry"] is False
        assert DEFAULT_SETTINGS_V2["general"]["include_remote_drives"] is False

    def test_fresh_load_has_false_defaults(self, tmp_path: Path) -> None:
        """新文件加载即含两键且为 False。"""
        v2 = _fresh_v2(tmp_path)
        v2.load()
        assert v2.get("general.enable_ai_entry") is False
        assert v2.get("general.include_remote_drives") is False

    def test_save_load_merge_keeps_true(self, tmp_path: Path) -> None:
        """save → 新实例 load → merge 后 True 保持（布尔白名单键不丢失）。"""
        tmp_file = str(tmp_path / "settings_v2.json")
        v2 = SettingsManagerV2(tmp_file)
        v2.load()
        v2.set("general.enable_ai_entry", True)
        v2.set("general.include_remote_drives", True)
        v2.save()

        fresh = SettingsManagerV2(tmp_file)
        fresh.load()
        assert fresh.get("general.enable_ai_entry") is True
        assert fresh.get("general.include_remote_drives") is True

    @pytest.mark.parametrize("bad", ["true", 1, 0, None, "yes"])
    def test_invalid_values_fall_back_false(self, tmp_path: Path, bad) -> None:
        """非布尔（含字符串 "true"/数字）一律丢弃，回退默认 False。"""
        import json

        tmp_file = tmp_path / "settings_v2.json"
        tmp_file.write_text(
            json.dumps(
                {
                    "version": 2,
                    "general": {
                        "enable_ai_entry": bad,
                        "include_remote_drives": bad,
                    },
                }
            ),
            encoding="utf-8",
        )
        v2 = SettingsManagerV2(str(tmp_file))
        v2.load()
        assert v2.get("general.enable_ai_entry") is False
        assert v2.get("general.include_remote_drives") is False
