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
