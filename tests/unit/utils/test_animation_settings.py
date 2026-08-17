# -*- coding: utf-8 -*-
"""test_animation_settings: animation_settings.py 覆盖测试（todo-10, unit/utils 批 1）。

覆盖：resolve_settings_manager 注入 / 无管理器回退 / 模块导入路径、
is_animation_enabled 各动画 key 的读取路径与回退。
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from freeassetfilter.utils.animation_settings import is_animation_enabled, resolve_settings_manager

#: SettingsManager 导入目标（resolve_settings_manager 内部 from-import 用）。
_SETTINGS_MODULE_NAME: str = "freeassetfilter.core.managers.settings_manager"


class FakeSettingsManager:
    """测试用假管理器：get_setting 返回预设值或抛异常。"""

    def __init__(self, values: dict[str, Any] | None = None, error: BaseException | None = None) -> None:
        """初始化假管理器。

        Args:
            values: key_path → 值的映射。
            error: 若设置，get_setting 一律抛该异常。
        """
        self.values: dict[str, Any] = dict(values or {})
        self.error: BaseException | None = error

    def get_setting(self, key_path: str, default: Any = None) -> Any:
        """模拟 SettingsManager.get_setting。

        Args:
            key_path: 设置键路径。
            default: 缺省值。

        Returns:
            Any: 预设值或默认值。

        Raises:
            BaseException: 当 error 被注入时。
        """
        if self.error is not None:
            raise self.error
        return self.values.get(key_path, default)


@pytest.fixture()
def fake_manager() -> FakeSettingsManager:
    """返回空值假管理器。"""
    return FakeSettingsManager()


class TestResolveSettingsManager:
    """resolve_settings_manager 三种路径。"""

    def test_returns_injected_manager(self, fake_manager: FakeSettingsManager) -> None:
        """显式传入的管理器原样返回。"""
        assert resolve_settings_manager(fake_manager) is fake_manager

    def test_import_failure_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """模块导入失败时回退 None。"""
        monkeypatch.setitem(sys.modules, _SETTINGS_MODULE_NAME, None)
        assert resolve_settings_manager(None) is None

    def test_import_path_constructs_manager(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """无注入时经模块导入构造管理器。"""
        fake_module = types.ModuleType(_SETTINGS_MODULE_NAME)
        fake_module.SettingsManager = FakeSettingsManager
        monkeypatch.setitem(sys.modules, _SETTINGS_MODULE_NAME, fake_module)
        manager = resolve_settings_manager(None)
        assert isinstance(manager, FakeSettingsManager)


class TestIsAnimationEnabled:
    """is_animation_enabled 各 key 路径与回退。"""

    @pytest.mark.parametrize(
        "key",
        [
            "directory_transition",
            "file_record_changes",
            "smooth_scrolling",
            "file_card_state",
            "progress_bar_smoothing",
            "button_smoothing",
        ],
    )
    def test_false_values_return_false(self, key: str) -> None:
        """每个动画 key 存储 False 时返回 False。"""
        manager = FakeSettingsManager({f"appearance.animations.{key}": False})
        assert is_animation_enabled(key, settings_manager=manager) is False

    @pytest.mark.parametrize(
        "key",
        [
            "directory_transition",
            "file_record_changes",
            "smooth_scrolling",
            "file_card_state",
            "progress_bar_smoothing",
            "button_smoothing",
        ],
    )
    def test_true_values_return_true(self, key: str) -> None:
        """每个动画 key 存储 True 时返回 True。"""
        manager = FakeSettingsManager({f"appearance.animations.{key}": True})
        assert is_animation_enabled(key, settings_manager=manager) is True

    def test_short_key_prefixed(self, fake_manager: FakeSettingsManager) -> None:
        """短 key 被自动补全为 prefix.key。"""
        fake_manager.values = {"appearance.animations.smooth_scrolling": True}
        assert is_animation_enabled("smooth_scrolling", settings_manager=fake_manager) is True

    def test_full_key_passthrough(self, fake_manager: FakeSettingsManager) -> None:
        """已带前缀的完整 key 不被重复补全。"""
        fake_manager.values = {"appearance.animations.fade_out": False}
        assert (
            is_animation_enabled("appearance.animations.fade_out", settings_manager=fake_manager) is False
        )

    def test_missing_key_uses_default(self, fake_manager: FakeSettingsManager) -> None:
        """未存储的 key 使用调用方 default。"""
        assert is_animation_enabled("unknown_key", default=False, settings_manager=fake_manager) is False
        assert is_animation_enabled("unknown_key", default=True, settings_manager=fake_manager) is True

    def test_manager_error_falls_back_to_default(self) -> None:
        """管理器抛异常时回退 default。"""
        manager = FakeSettingsManager(error=RuntimeError("boom"))
        assert is_animation_enabled("x", default=False, settings_manager=manager) is False
        assert is_animation_enabled("x", default=True, settings_manager=manager) is True

    def test_no_manager_uses_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """无管理器可用时返回 bool(default)。"""
        monkeypatch.setitem(sys.modules, _SETTINGS_MODULE_NAME, None)
        assert is_animation_enabled("smooth_scrolling", default=True) is True
        assert is_animation_enabled("smooth_scrolling", default=False) is False