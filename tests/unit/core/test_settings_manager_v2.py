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


class TestHardwareAccelerationSetting:
    """performance.hardware_acceleration：默认关闭、往返与合并白名单。"""

    def test_default_is_disabled(self) -> None:
        """默认树含 hardware_acceleration == False。"""
        assert DEFAULT_SETTINGS_V2["performance"]["hardware_acceleration"] is False

    def test_set_get_roundtrip(self, tmp_path: Path) -> None:
        """内存读写往返；相同值二次写入返回 False。"""
        v2 = _fresh_v2(tmp_path)
        v2.load()
        assert v2.get("performance.hardware_acceleration") is False
        v2.set("performance.hardware_acceleration", True)
        assert v2.get("performance.hardware_acceleration") is True
        assert v2.set("performance.hardware_acceleration", True) is False

    def test_save_load_merge_keeps_enabled(self, tmp_path: Path) -> None:
        """save → 新实例 load → merge 后 True 保持。"""
        tmp_file = str(tmp_path / "settings_v2.json")
        v2 = SettingsManagerV2(tmp_file)
        v2.load()
        v2.set("performance.hardware_acceleration", True)
        v2.save()

        fresh = SettingsManagerV2(tmp_file)
        fresh.load()
        assert fresh.get("performance.hardware_acceleration") is True

    def test_non_bool_value_falls_back_disabled(self, tmp_path: Path) -> None:
        """非布尔值（含字符串 "true"）合并时回退 False。"""
        import json

        tmp_file = tmp_path / "settings_v2.json"
        tmp_file.write_text(
            json.dumps(
                {
                    "version": 2,
                    "performance": {"hardware_acceleration": "true"},
                }
            ),
            encoding="utf-8",
        )
        v2 = SettingsManagerV2(str(tmp_file))
        v2.load()
        assert v2.get("performance.hardware_acceleration") is False


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
    """general 布尔开关：enable_ai_entry / include_remote_drives / blank_right_click_go_back
    / show_hidden_files / show_system_files。"""

    def test_defaults_are_false(self) -> None:
        """默认树五个开关均为 False（AI 入口 / 网络盘光驱 / 空白右键返回 / 显示隐藏 / 显示系统文件默认关闭）。"""
        assert DEFAULT_SETTINGS_V2["general"]["enable_ai_entry"] is False
        assert DEFAULT_SETTINGS_V2["general"]["include_remote_drives"] is False
        assert DEFAULT_SETTINGS_V2["general"]["blank_right_click_go_back"] is False
        assert DEFAULT_SETTINGS_V2["general"]["show_hidden_files"] is False
        assert DEFAULT_SETTINGS_V2["general"]["show_system_files"] is False

    def test_fresh_load_has_false_defaults(self, tmp_path: Path) -> None:
        """新文件加载即含五键且为 False。"""
        v2 = _fresh_v2(tmp_path)
        v2.load()
        assert v2.get("general.enable_ai_entry") is False
        assert v2.get("general.include_remote_drives") is False
        assert v2.get("general.blank_right_click_go_back") is False
        assert v2.get("general.show_hidden_files") is False
        assert v2.get("general.show_system_files") is False

    def test_save_load_merge_keeps_true(self, tmp_path: Path) -> None:
        """save → 新实例 load → merge 后 True 保持（布尔白名单键不丢失）。"""
        tmp_file = str(tmp_path / "settings_v2.json")
        v2 = SettingsManagerV2(tmp_file)
        v2.load()
        v2.set("general.enable_ai_entry", True)
        v2.set("general.include_remote_drives", True)
        v2.set("general.blank_right_click_go_back", True)
        v2.set("general.show_hidden_files", True)
        v2.set("general.show_system_files", True)
        v2.save()

        fresh = SettingsManagerV2(tmp_file)
        fresh.load()
        assert fresh.get("general.enable_ai_entry") is True
        assert fresh.get("general.include_remote_drives") is True
        assert fresh.get("general.blank_right_click_go_back") is True
        assert fresh.get("general.show_hidden_files") is True
        assert fresh.get("general.show_system_files") is True

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
                        "blank_right_click_go_back": bad,
                        "show_hidden_files": bad,
                        "show_system_files": bad,
                    },
                }
            ),
            encoding="utf-8",
        )
        v2 = SettingsManagerV2(str(tmp_file))
        v2.load()
        assert v2.get("general.enable_ai_entry") is False
        assert v2.get("general.include_remote_drives") is False
        assert v2.get("general.blank_right_click_go_back") is False
        assert v2.get("general.show_hidden_files") is False
        assert v2.get("general.show_system_files") is False


class TestStaleWriterProtection:
    """多实例写盘防覆盖（2026-10「重启后所有设置恢复默认」回归）。

    同一进程内可能存在多个 SettingsManagerV2 实例（引导层、设置窗口、
    退出钩子等），各自持有独立内存快照。save() 必须只回写本次改动过的
    键，旧实例的保存不得覆盖其他实例已落盘的新值。
    """

    def test_stale_instance_save_keeps_newer_writes(self, tmp_path: Path) -> None:
        """复现修复前缺陷：退出实例写 last_exit_time 不再回退设置页提交。"""
        tmp_file = str(tmp_path / "settings_v2.json")

        # 会话开始：引导层实例加载（文件不存在 → 默认树）。
        boot = SettingsManagerV2(tmp_file)
        boot.load()

        # 设置页提交：新实例写用户修改并落盘。
        editor = SettingsManagerV2(tmp_file)
        editor.load()
        editor.set("general.layout_mode", "classic")
        editor.set("appearance.theme_mode", "light")
        editor.set("performance.profile", "performance")
        editor.save()

        # 退出：引导层实例写 last_exit_time 后保存（修复前整份覆盖磁盘）。
        boot.set("app.last_exit_time", 12345.0)
        boot.save()

        fresh = SettingsManagerV2(tmp_file)
        fresh.load()
        assert fresh.get("general.layout_mode") == "classic"
        assert fresh.get("appearance.theme_mode") == "light"
        assert fresh.get("performance.profile") == "performance"
        assert fresh.get("app.last_exit_time") == 12345.0

    def test_save_without_changes_does_not_clobber(self, tmp_path: Path) -> None:
        """无改动键的 save() 不写盘：不覆盖其他实例的新值。"""
        tmp_file = str(tmp_path / "settings_v2.json")
        boot = SettingsManagerV2(tmp_file)
        boot.load()

        editor = SettingsManagerV2(tmp_file)
        editor.load()
        editor.set("general.layout_mode", "classic")
        editor.save()

        boot.save()  # 无脏键 → no-op（修复前会回写启动时旧快照）

        fresh = SettingsManagerV2(tmp_file)
        fresh.load()
        assert fresh.get("general.layout_mode") == "classic"

    def test_dirty_writes_merge_across_instances(self, tmp_path: Path) -> None:
        """两实例先加载后各写各键：先后保存互不覆盖。"""
        tmp_file = str(tmp_path / "settings_v2.json")
        first = SettingsManagerV2(tmp_file)
        first.load()
        second = SettingsManagerV2(tmp_file)
        second.load()

        first.set("appearance.accent_color", "#112233")
        second.set("general.layout_mode", "classic")
        first.save()
        second.save()

        fresh = SettingsManagerV2(tmp_file)
        fresh.load()
        assert fresh.get("appearance.accent_color") == "#112233"
        assert fresh.get("general.layout_mode") == "classic"

    def test_unknown_top_level_domains_preserved(self, tmp_path: Path) -> None:
        """未知顶层域（app / file_selector）在合并写盘后仍保留。"""
        import json

        tmp_file = tmp_path / "settings_v2.json"
        tmp_file.write_text(
            json.dumps(
                {
                    "version": 2,
                    "app": {"last_exit_time": 111.0},
                    "file_selector": {"last_cleanup_time": 222.0},
                    "general": {"layout_mode": "classic"},
                }
            ),
            encoding="utf-8",
        )
        v2 = SettingsManagerV2(str(tmp_file))
        v2.load()
        assert v2.get("app.last_exit_time") == 111.0
        v2.set("appearance.theme_mode", "light")
        v2.save()

        fresh = SettingsManagerV2(str(tmp_file))
        fresh.load()
        assert fresh.get("appearance.theme_mode") == "light"
        assert fresh.get("app.last_exit_time") == 111.0
        assert fresh.get("file_selector.last_cleanup_time") == 222.0

    def test_default_path_under_app_data_dir(self) -> None:
        """默认文件路径跟随应用数据目录（安装版可写目录由 path_utils 统一）。"""
        import os

        from freeassetfilter.utils.path_utils import get_app_data_path

        v2 = SettingsManagerV2()
        assert v2.file_path == os.path.join(
            get_app_data_path(), "settings_v2.json"
        )

    def test_save_failure_keeps_dirty_keys_for_retry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """写盘抛 OSError（权限/占用）时异常上抛且改动键保留，可重试。"""
        tmp_file = str(tmp_path / "settings_v2.json")
        v2 = SettingsManagerV2(tmp_file)
        v2.load()
        v2.set("general.layout_mode", "classic")

        def _denied() -> None:
            raise PermissionError("simulated write denial")

        monkeypatch.setattr(v2, "_write", _denied)
        with pytest.raises(PermissionError):
            v2.save()
        # 失败后脏键保留（后续可重试），内存值不回退。
        assert v2._dirty_paths == {"general.layout_mode"}
        assert v2.get("general.layout_mode") == "classic"

        monkeypatch.undo()
        v2.save()
        fresh = SettingsManagerV2(tmp_file)
        fresh.load()
        assert fresh.get("general.layout_mode") == "classic"

    def test_reset_to_defaults_is_authoritative(self, tmp_path: Path) -> None:
        """reset_to_defaults 仍全量写默认树（覆盖磁盘上的既有值）。"""
        tmp_file = str(tmp_path / "settings_v2.json")
        editor = SettingsManagerV2(tmp_file)
        editor.load()
        editor.set("general.layout_mode", "classic")
        editor.save()

        resetter = SettingsManagerV2(tmp_file)
        resetter.load()
        resetter.reset_to_defaults()

        fresh = SettingsManagerV2(tmp_file)
        fresh.load()
        assert fresh.get("general.layout_mode") == "workspace"


class TestGeneralFloatingPoolEnabled:
    """general.floating_pool_enabled：默认 True（general 下首个默认开启布尔）。

    合并白名单回归（Oracle B1，BLOCKER 修复）：用户关闭浮窗落盘 ``False``
    后，``_merge_with_defaults`` 的 general 白名单块必须回读该键，否则每次
    启动加载时丢弃该值、``get`` 退回默认 ``True``——开关无法跨重启持久化
    （静默失效）。
    """

    def test_default_floating_pool_enabled_is_true(self) -> None:
        """默认树含 general.floating_pool_enabled 且为 True。"""
        assert DEFAULT_SETTINGS_V2["general"]["floating_pool_enabled"] is True

    def test_fresh_load_has_true_default(self, tmp_path: Path) -> None:
        """新文件加载即含该键（默认 True）。"""
        v2 = _fresh_v2(tmp_path)
        v2.load()
        assert v2.get("general.floating_pool_enabled") is True

    def test_save_load_merge_keeps_disabled_false(self, tmp_path: Path) -> None:
        """重启持久化：落盘 False → 新实例 load → 仍为 False（白名单回归守卫）。"""
        tmp_file = str(tmp_path / "settings_v2.json")
        v2 = SettingsManagerV2(tmp_file)
        v2.load()
        v2.set("general.floating_pool_enabled", False)
        v2.save()

        fresh = SettingsManagerV2(tmp_file)
        fresh.load()
        assert fresh.get("general.floating_pool_enabled") is False

    def test_invalid_value_falls_back_true(self, tmp_path: Path) -> None:
        """非布尔值（含字符串 "false"/数字）一律丢弃，回退默认 True。"""
        import json

        tmp_file = tmp_path / "settings_v2.json"
        tmp_file.write_text(
            json.dumps(
                {"version": 2, "general": {"floating_pool_enabled": "false"}}
            ),
            encoding="utf-8",
        )
        v2 = SettingsManagerV2(str(tmp_file))
        v2.load()
        assert v2.get("general.floating_pool_enabled") is True


class TestGeneralFloatingPoolSnapEnabled:
    """general.floating_pool_snap_enabled：默认 True（镜像 floating_pool_enabled）。

    与 :class:`TestGeneralFloatingPoolEnabled` 同构的合并白名单回归：用户
    关闭贴边吸附落盘 ``False`` 后，``_merge_with_defaults`` 的 general
    白名单块必须回读该键，否则每次启动加载时丢弃该值、``get`` 退回默认
    ``True``——开关无法跨重启持久化（静默失效）。
    """

    def test_default_floating_pool_snap_enabled_is_true(self) -> None:
        """默认树含 general.floating_pool_snap_enabled 且为 True。"""
        assert DEFAULT_SETTINGS_V2["general"]["floating_pool_snap_enabled"] is True

    def test_fresh_load_has_true_default(self, tmp_path: Path) -> None:
        """新文件加载即含该键（默认 True）。"""
        v2 = _fresh_v2(tmp_path)
        v2.load()
        assert v2.get("general.floating_pool_snap_enabled") is True

    def test_save_load_merge_keeps_disabled_false(self, tmp_path: Path) -> None:
        """重启持久化：落盘 False → 新实例 load → 仍为 False（白名单回归守卫）。"""
        tmp_file = str(tmp_path / "settings_v2.json")
        v2 = SettingsManagerV2(tmp_file)
        v2.load()
        v2.set("general.floating_pool_snap_enabled", False)
        v2.save()

        fresh = SettingsManagerV2(tmp_file)
        fresh.load()
        assert fresh.get("general.floating_pool_snap_enabled") is False

    def test_invalid_value_falls_back_true(self, tmp_path: Path) -> None:
        """非布尔值（含字符串 "false"/数字）一律丢弃，回退默认 True。"""
        import json

        tmp_file = tmp_path / "settings_v2.json"
        tmp_file.write_text(
            json.dumps(
                {"version": 2, "general": {"floating_pool_snap_enabled": "false"}}
            ),
            encoding="utf-8",
        )
        v2 = SettingsManagerV2(str(tmp_file))
        v2.load()
        assert v2.get("general.floating_pool_snap_enabled") is True
