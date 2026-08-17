# -*- coding: utf-8 -*-
# targets: core.managers.settings_manager, core.managers.settings_manager_v2
"""``SettingsManager``（core/managers/settings_manager.py）单元测试。

覆盖（方法矩阵：happy + boundary/error 各至少一条）：

* 单例模式（``_instance``/``_initialized`` 防重入）
* ``load_settings`` —— 文件缺失自动创建、损坏 JSON 安全回退、未知节保留
* ``get_setting`` —— 嵌套 key、颜色快速路径缓存、默认值回退、settings 为 None
* ``set_setting`` —— 变更/无变更、深嵌套自动建字典、dirty_keys 追踪
* ``schedule_save`` / ``save_settings`` —— 防抖合并写盘、权限/类型错误被吞
* 播放器音量/倍速存取
* ``reset_to_defaults`` / ``get_colors_dict``
* v2 兼容 smoke —— ``SettingsManagerV2`` 可导入且公开 API 一致

所有测试均绑定 ``tmp_path`` 的临时设置文件，绝不触碰真实
``data/settings.json``（单例通过 reset_singletons autouse fixture 隔离）。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest

from freeassetfilter.core.managers.settings_manager import SettingsManager
from freeassetfilter.core.managers.settings_manager_v2 import SettingsManagerV2


def _wait_save_timer(manager: SettingsManager, timeout: float = 5.0) -> None:
    """等待防抖写盘定时器（threading.Timer）执行完毕。

    ``settings_manager`` 用 ``threading.Timer`` 实现 0.35s 防抖保存，
    不是 QTimer——因此用带超时的轮询等待 ``_save_timer`` 被消费为 None。

    Args:
        manager: 待检查的 SettingsManager 实例。
        timeout: 最大等待秒数，超时抛 AssertionError（挂死保护）。
    """
    deadline: float = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with manager._settings_lock:
            timer = manager._save_timer
        if timer is None:
            return
        time.sleep(0.01)
    raise AssertionError("防抖保存定时器未在超时内完成")


def _read_json(path: str) -> Dict[str, Any]:
    """读取 JSON 设置文件内容（断言辅助）。"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# =============================================================================
# 单例模式
# =============================================================================
class TestSingleton:
    """单例模式测试"""

    def test_singleton_returns_same_instance(self, settings_manager: Any) -> None:
        """重复构造必须返回同一实例。"""
        again: SettingsManager = SettingsManager()
        assert again is settings_manager

    def test_singleton_ignores_second_settings_file_arg(
        self, settings_manager: Any, tmp_path: Path
    ) -> None:
        """边界：已初始化后传入不同 settings_file 不得重建实例。"""
        second: SettingsManager = SettingsManager(settings_file=str(tmp_path / "other.json"))
        assert second is settings_manager
        assert second._settings_file == settings_manager._settings_file


# =============================================================================
# load_settings
# =============================================================================
class TestLoadSettings:
    """设置加载与合并"""

    def test_load_settings_creates_missing_file(self, tmp_path: Path) -> None:
        """文件不存在时构造应创建文件并返回默认设置。"""
        settings_file: Path = tmp_path / "fresh.json"
        SettingsManager._instance = None
        SettingsManager._initialized = False
        manager = SettingsManager(settings_file=str(settings_file))

        assert settings_file.exists()
        assert isinstance(manager.settings, dict)
        assert manager.settings["appearance"]["theme"] == "default"

    def test_load_settings_returns_defaults(self, settings_manager: Any) -> None:
        """默认设置结构完整：font/appearance/player 等顶层节存在。"""
        settings: Dict[str, Any] = settings_manager.settings
        assert isinstance(settings, dict)
        assert "appearance" in settings
        assert "font" in settings
        assert settings["font"]["size"] == 10
        assert settings["appearance"]["colors"]["accent_color"] == "#007AFF"

    def test_load_corrupted_json_falls_back_to_defaults(self, tmp_path: Path) -> None:
        """QA 场景：损坏 JSON 不抛异常且回退默认设置。"""
        bad_file: Path = tmp_path / "bad.json"
        bad_file.write_text("{not valid json!!", encoding="utf-8")

        SettingsManager._instance = None
        SettingsManager._initialized = False
        manager = SettingsManager(settings_file=str(bad_file))

        assert manager.settings is not None
        assert isinstance(manager.settings, dict)
        assert manager.get_setting("appearance.theme") == "default"
        # 回退后应重写文件为合法 JSON。
        loaded: Dict[str, Any] = _read_json(str(bad_file))
        assert loaded["appearance"]["theme"] == "default"

    def test_load_json_wrong_root_type_raises_attribute_error(
        self, tmp_path: Path
    ) -> None:
        """边界（记录现状）：根节点非 dict 的有效 JSON 逃过异常回退。

        已知产品缺陷（v1 SettingsManager）：``SettingsRepository.load`` 对
        语法合法的 ``[1,2,3]`` 返回 truthy 的 list，``load_settings`` 因此
        跳过回退分支；``_merge_settings`` 对 list 调用 ``.items()`` 抛
        AttributeError，且该类型不在 ``load_settings`` 的捕获清单中——
        构造即在 ``__init__`` 传播异常。settings_manager_v2 对此场景有
        保护（见 ``SettingsManagerV2.load`` 的 ``isinstance(data, dict)``
        校验）。本测试固化当下行为，修复该缺陷时应同步更新断言。
        """
        bad_file: Path = tmp_path / "list.json"
        bad_file.write_text("[1, 2, 3]", encoding="utf-8")

        SettingsManager._instance = None
        SettingsManager._initialized = False
        with pytest.raises(AttributeError):
            SettingsManager(settings_file=str(bad_file))

    def test_load_merges_existing_settings(self, tmp_path: Path) -> None:
        """已存在文件：用户值覆盖默认值，未知节保留。"""
        settings_file: Path = tmp_path / "merge.json"
        settings_file.write_text(
            json.dumps(
                {
                    "appearance": {
                        "theme": "dark",
                        "colors": {"accent_color": "#FF0000"},
                    },
                    "font": {"size": 14},
                    "custom_section": {"key": "value"},
                }
            ),
            encoding="utf-8",
        )

        SettingsManager._instance = None
        SettingsManager._initialized = False
        manager = SettingsManager(settings_file=str(settings_file))

        assert manager.get_setting("appearance.theme") == "dark"
        assert manager.get_setting("appearance.colors.accent_color") == "#FF0000"
        assert manager.get_setting("font.size") == 14
        # 未知顶层节在加载合并后必须保留。
        assert manager.get_setting("custom_section.key") == "value"


# =============================================================================
# get_setting
# =============================================================================
class TestGetSetting:
    """读取设置"""

    def test_get_setting_happy_path(self, settings_manager: Any) -> None:
        """嵌套 key 正确取值。"""
        assert settings_manager.get_setting("appearance.theme") == "default"
        assert settings_manager.get_setting("appearance.colors.accent_color") == "#007AFF"

    def test_get_setting_default_fallback(self, settings_manager: Any) -> None:
        """边界：未知 key 返回默认值且不抛异常。"""
        assert settings_manager.get_setting("nonexistent.key", "fallback") == "fallback"

    def test_get_setting_missing_no_default_returns_none(self, settings_manager: Any) -> None:
        """边界：未知 key 且无默认值时返回 None。"""
        assert settings_manager.get_setting("nonexistent.key") is None

    def test_get_setting_none_settings_returns_default(self, settings_manager: Any) -> None:
        """边界：settings 为 None 时不崩溃，直接返回默认值。"""
        settings_manager.settings = None
        assert settings_manager.get_setting("appearance.theme", "default") == "default"
        assert settings_manager.get_setting("player.volume", 100) == 100

    def test_color_fast_path_short_circuits(self, settings_manager: Any) -> None:
        """``appearance.colors.*`` 走内存颜色缓存快速路径。"""
        settings_manager.set_setting("appearance.colors.accent_color", "#123456")
        assert settings_manager.get_setting("appearance.colors.accent_color") == "#123456"


# =============================================================================
# set_setting
# =============================================================================
class TestSetSetting:
    """写设置"""

    def test_set_setting_roundtrip(self, settings_manager: Any) -> None:
        """写入后立即读回。"""
        changed: bool = settings_manager.set_setting("appearance.theme", "dark")
        assert changed is True
        assert settings_manager.get_setting("appearance.theme") == "dark"

    def test_set_setting_no_change_returns_false(self, settings_manager: Any) -> None:
        """边界：设相同值返回 False（无变更）。"""
        original: str = settings_manager.get_setting("appearance.theme")
        assert settings_manager.set_setting("appearance.theme", original) is False

    def test_set_setting_creates_intermediate_dicts(self, settings_manager: Any) -> None:
        """深嵌套路径自动创建中间字典。"""
        changed: bool = settings_manager.set_setting("a.b.c.d", "value")
        assert changed is True
        assert settings_manager.settings["a"]["b"]["c"]["d"] == "value"

    def test_set_setting_tracks_dirty_keys(self, settings_manager: Any) -> None:
        """每条变更记录进 ``_dirty_keys``（防抖保存依据）。"""
        assert settings_manager._dirty_keys == set()
        settings_manager.set_setting("appearance.theme", "dark")
        assert "appearance.theme" in settings_manager._dirty_keys

    def test_set_setting_clears_color_cache(self, settings_manager: Any) -> None:
        """颜色变更时清除颜色缓存（防止脏读）。"""
        settings_manager.get_setting("appearance.colors.accent_color")
        with settings_manager._color_cache_lock:
            assert "accent_color" in settings_manager._color_cache
        settings_manager.set_setting("appearance.colors.accent_color", "#0F0F0F")
        with settings_manager._color_cache_lock:
            assert "accent_color" not in settings_manager._color_cache


# =============================================================================
# save_settings / schedule_save（防抖合并写盘）
# =============================================================================
class TestSaveSettings:
    """写盘与防抖"""

    def test_save_settings_persists_to_file(self, settings_manager: Any) -> None:
        """手动 save_settings 后文件内容包含变更。"""
        settings_manager.set_setting("appearance.theme", "dark")
        settings_manager.save_settings()

        assert settings_manager._settings_file is not None
        saved: Dict[str, Any] = _read_json(str(settings_manager._settings_file))
        assert saved["appearance"]["theme"] == "dark"
        # 保存后脏标记应清除。
        assert settings_manager._dirty_keys == set()

    def test_save_settings_permission_error_swallowed(
        self, settings_manager: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """边界：写入权限不足时记录错误但不向上抛。"""
        with patch("builtins.open", side_effect=PermissionError("denied")):
            settings_manager.set_setting("appearance.theme", "dark")
            settings_manager.save_settings()

    def test_save_settings_type_error_swallowed(self, settings_manager: Any) -> None:
        """边界：设置含不可序列化对象时写入失败但不抛异常。"""
        settings_manager.settings["bad_key"] = object()
        settings_manager.save_settings()

    def test_schedule_save_creates_timer(self, settings_manager: Any) -> None:
        """schedule_save 应创建一个挂起的防抖定时器。"""
        assert settings_manager._save_timer is None
        settings_manager.schedule_save(delay=0.5)
        assert settings_manager._save_timer is not None
        settings_manager._save_timer.cancel()

    def test_schedule_save_debounces_merging(self, settings_manager: Any) -> None:
        """防抖合并：窗口内多次变更聚合成一次写盘且全部落盘。"""
        settings_manager.set_setting("appearance.theme", "dark")
        settings_manager.schedule_save(delay=0.15)
        first_timer = settings_manager._save_timer

        settings_manager.set_setting("player.speed", 1.5)
        settings_manager.schedule_save(delay=0.15)
        second_timer = settings_manager._save_timer

        # 第二次调度取代第一次：旧 timer 被取消，实例不同。
        assert first_timer is not second_timer
        assert first_timer.finished.is_set() or not first_timer.is_alive()

        _wait_save_timer(settings_manager)
        saved: Dict[str, Any] = _read_json(str(settings_manager._settings_file))
        assert saved["appearance"]["theme"] == "dark"
        assert saved["player"]["speed"] == 1.5

    def test_schedule_save_default_delay_flushes(self, settings_manager: Any) -> None:
        """默认延迟（0.35s）足够让写盘完成（防抖窗口结束）。"""
        settings_manager.set_setting("appearance.theme", "dark")
        settings_manager.schedule_save()
        assert settings_manager._save_delay_seconds == 0.35

        _wait_save_timer(settings_manager)
        saved: Dict[str, Any] = _read_json(str(settings_manager._settings_file))
        assert saved["appearance"]["theme"] == "dark"

    def test_flush_scheduled_save_clears_timer(self, settings_manager: Any) -> None:
        """tick 到达后定时器被消费为 None。"""
        settings_manager.set_setting("appearance.theme", "dark")
        settings_manager.schedule_save(delay=0.05)
        _wait_save_timer(settings_manager)
        assert settings_manager._save_timer is None


# =============================================================================
# reset_to_defaults / get_colors_dict
# =============================================================================
class TestResetAndColors:
    """重置与颜色字典"""

    def test_reset_to_defaults(self, settings_manager: Any) -> None:
        """reset_to_defaults 将内存设置还原为默认值。"""
        settings_manager.set_setting("appearance.theme", "dark")
        settings_manager.set_setting("appearance.colors.accent_color", "#FF0000")
        settings_manager.reset_to_defaults()

        assert settings_manager.get_setting("appearance.theme") == "default"
        assert settings_manager.get_setting("appearance.colors.accent_color") == "#007AFF"

    def test_get_colors_dict_happy_path(self, settings_manager: Any) -> None:
        """get_colors_dict 返回完整颜色字典。"""
        colors: Dict[str, Any] = settings_manager.get_colors_dict()
        assert colors["accent_color"] == "#007AFF"
        assert colors["base_color"] == "#FFFFFF"
        assert "custom_design_color" in colors

    def test_get_colors_dict_none_settings_returns_defaults(self, settings_manager: Any) -> None:
        """边界：settings 为 None 时返回默认颜色字典。"""
        settings_manager.settings = None
        colors: Dict[str, Any] = settings_manager.get_colors_dict()
        assert colors["accent_color"] == "#007AFF"


# =============================================================================
# 播放器音量 / 倍速
# =============================================================================
class TestPlayerVolumeAndSpeed:
    """播放器音量与倍速存取"""

    def test_get_player_volume_use_default(self, settings_manager: Any) -> None:
        """volume：use_default=True 返回 default_volume。"""
        settings_manager.set_setting("player.use_default_volume", True)
        settings_manager.set_setting("player.default_volume", 75)
        assert settings_manager.get_player_volume() == 75

    def test_get_player_volume_use_last(self, settings_manager: Any) -> None:
        """volume：use_default=False 返回 last_volume。"""
        settings_manager.set_setting("player.use_default_volume", False)
        settings_manager.set_setting("player.last_volume", 60)
        assert settings_manager.get_player_volume() == 60

    def test_get_player_speed_use_default(self, settings_manager: Any) -> None:
        """speed：use_default_speed=True 返回 default_speed。"""
        settings_manager.set_setting("player.use_default_speed", True)
        settings_manager.set_setting("player.default_speed", 1.5)
        assert settings_manager.get_player_speed() == 1.5

    def test_get_player_speed_use_last(self, settings_manager: Any) -> None:
        """speed：use_default_speed=False 返回 last_speed。"""
        settings_manager.set_setting("player.use_default_speed", False)
        settings_manager.set_setting("player.last_speed", 2.0)
        assert settings_manager.get_player_speed() == 2.0

    def test_save_player_volume_and_speed(self, settings_manager: Any) -> None:
        """save_player_volume/save_player_speed 写内存并调度落盘。"""
        settings_manager.save_player_volume(80)
        settings_manager.save_player_speed(1.75)
        assert settings_manager.get_setting("player.last_volume") == 80
        assert settings_manager.get_setting("player.last_speed") == 1.75
        assert "player.last_volume" in settings_manager._dirty_keys
        assert "player.last_speed" in settings_manager._dirty_keys


# =============================================================================
# settings_manager_v2 兼容 smoke
# =============================================================================
class TestSettingsManagerV2Compat:
    """V2 兼容 smoke：可导入且公开 API 一致"""

    def test_v2_module_importable(self) -> None:
        """``settings_manager_v2`` 模块可导入且含 SettingsManagerV2 类。"""
        import freeassetfilter.core.managers.settings_manager_v2 as v2_module

        assert hasattr(v2_module, "SettingsManagerV2")
        assert hasattr(v2_module, "DEFAULT_SETTINGS_V2")

    def test_v2_public_api_consistent_with_v1(self) -> None:
        """V1 与 V2 的公开读写 API 面一致（

        ``get_setting``/``set_setting`` ↔ ``get``/``set``，均有点号路径语义）。
        """
        v1_api = {"get_setting", "set_setting", "save_settings", "reset_to_defaults"}
        v2_api = {"get", "set", "load", "save", "reset_to_defaults", "get_all"}
        assert v1_api.issubset({m for m in dir(SettingsManager) if not m.startswith("_")})
        assert v2_api.issubset({m for m in dir(SettingsManagerV2) if not m.startswith("_")})
        assert hasattr(SettingsManagerV2, "file_path")

    def test_v2_roundtrip_with_tmp_file(self, tmp_path: Path) -> None:
        """V2 写读往返：set → save → 新实例 load → get。"""
        v2_file: Path = tmp_path / "settings_v2.json"

        # 首次 load：默认值 + 写盘。
        v2a: SettingsManagerV2 = SettingsManagerV2(file_path=str(v2_file))
        assert v2a.load()["version"] == 2
        assert v2a.get("appearance.theme") == "dark"
        assert v2_file.exists()

        v2a.set("appearance.theme", "light")
        v2a.set("appearance.accent_color", "#3A9DCB")
        assert v2a.set("appearance.theme", "light") is False  # 无变化
        v2a.save()

        # 新实例显式 load 后重新读取，确认持久化。
        v2b: SettingsManagerV2 = SettingsManagerV2(file_path=str(v2_file))
        v2b.load()
        assert v2b.get("appearance.theme") == "light"
        assert v2b.get("appearance.accent_color") == "#3A9DCB"

    def test_v2_corrupted_json_falls_back(self, tmp_path: Path) -> None:
        """V2 损坏 JSON：load 回退默认值且不抛异常。"""
        v2_file: Path = tmp_path / "settings_v2_bad.json"
        v2_file.write_text("{broken", encoding="utf-8")

        v2: SettingsManagerV2 = SettingsManagerV2(file_path=str(v2_file))
        assert v2.load()["version"] == 2
        assert v2.get("appearance.theme") == "dark"