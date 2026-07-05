#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
动画设置工具单元测试
测试 resolve_settings_manager 和 is_animation_enabled 函数
"""

from unittest.mock import MagicMock, patch

import pytest

from freeassetfilter.utils.animation_settings import (
    is_animation_enabled,
    resolve_settings_manager,
)


class TestResolveSettingsManager:
    """resolve_settings_manager 函数测试"""

    @patch("freeassetfilter.core.settings_manager.SettingsManager")
    def test_no_args_returns_settings_manager(self, mock_sm_cls: MagicMock) -> None:
        """无参数时创建并返回 SettingsManager 实例"""
        mock_instance = MagicMock()
        mock_sm_cls.return_value = mock_instance
        result = resolve_settings_manager()
        assert result is mock_instance
        mock_sm_cls.assert_called_once_with()

    def test_custom_manager_returned(self) -> None:
        """传入自定义 manager 时原样返回"""
        mock_manager = MagicMock()
        result = resolve_settings_manager(mock_manager)
        assert result is mock_manager

    @patch("freeassetfilter.core.settings_manager.SettingsManager")
    def test_manager_unavailable_returns_none(self, mock_sm_cls: MagicMock) -> None:
        """SettingsManager 不可用时返回 None（模拟实例化异常）"""
        mock_sm_cls.side_effect = RuntimeError("Cannot load SettingsManager")
        result = resolve_settings_manager()
        assert result is None


class TestIsAnimationEnabled:
    """is_animation_enabled 函数测试"""

    def test_existing_setting(self) -> None:
        """读取存在的设置项返回 bool 值"""
        mock_manager = MagicMock()
        mock_manager.get_setting.return_value = True

        result = is_animation_enabled(
            "appearance.animations.enabled",
            settings_manager=mock_manager,
        )

        assert result is True
        mock_manager.get_setting.assert_called_once_with(
            "appearance.animations.enabled",
            True,
        )

    def test_nonexistent_setting_returns_default(self) -> None:
        """不存在的设置返回默认值 True"""
        mock_manager = MagicMock()
        mock_manager.get_setting.return_value = True

        result = is_animation_enabled("nonexistent", settings_manager=mock_manager)

        assert result is True

    def test_nonexistent_setting_custom_default(self) -> None:
        """不存在的设置返回自定义默认值 False"""
        mock_manager = MagicMock()
        mock_manager.get_setting.return_value = False

        result = is_animation_enabled(
            "nonexistent",
            default=False,
            settings_manager=mock_manager,
        )

        assert result is False
        mock_manager.get_setting.assert_called_once_with(
            "appearance.animations.nonexistent",
            False,
        )

    def test_key_auto_prepend(self) -> None:
        """短键名自动补全 appearance.animations. 前缀"""
        mock_manager = MagicMock()
        mock_manager.get_setting.return_value = True

        result = is_animation_enabled("enabled", settings_manager=mock_manager)

        mock_manager.get_setting.assert_called_once_with(
            "appearance.animations.enabled",
            True,
        )
        assert result is True

    @patch("freeassetfilter.core.settings_manager.SettingsManager")
    def test_custom_manager_used_directly(
        self, mock_sm_cls: MagicMock
    ) -> None:
        """传入自定义 settings_manager 时直接使用，不创建新的 SettingsManager"""
        mock_manager = MagicMock()
        mock_manager.get_setting.return_value = True

        result = is_animation_enabled("enabled", settings_manager=mock_manager)

        assert result is True
        mock_sm_cls.assert_not_called()
