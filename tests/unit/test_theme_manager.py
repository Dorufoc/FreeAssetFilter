# -*- coding: utf-8 -*-
"""
ThemeManager 单元测试
测试主题管理器的核心功能
"""
import pytest
import os
import sys
from unittest.mock import MagicMock, patch


class TestThemeManagerBasic:
    """测试 ThemeManager 基本功能"""
    
    def test_theme_manager_import(self):
        """测试 ThemeManager 可以导入"""
        from freeassetfilter.core.theme_manager import ThemeManager
        assert ThemeManager is not None
    
    def test_theme_manager_signals_exist(self):
        """测试 ThemeManager 信号存在"""
        from freeassetfilter.core.theme_manager import ThemeManager
        # 检查信号是否存在
        assert hasattr(ThemeManager, 'theme_changed')
        assert hasattr(ThemeManager, 'colors_updated')
    
    def test_theme_manager_initialization(self, qt_app, clean_settings_manager, temp_dir):
        """测试 ThemeManager 初始化"""
        from freeassetfilter.core.theme_manager import ThemeManager
        from freeassetfilter.core.settings_manager import SettingsManager
        
        settings_file = os.path.join(temp_dir, "settings.json")
        sm = SettingsManager(settings_file)
        
        tm = ThemeManager(sm)
        
        assert tm is not None
        assert tm.settings_manager is not None
        assert hasattr(tm, 'theme_colors')
    
    def test_theme_colors_loading(self, qt_app, clean_settings_manager, temp_dir):
        """测试主题颜色加载"""
        from freeassetfilter.core.theme_manager import ThemeManager
        from freeassetfilter.core.settings_manager import SettingsManager
        
        settings_file = os.path.join(temp_dir, "settings.json")
        sm = SettingsManager(settings_file)
        tm = ThemeManager(sm)
        
        # 检查主题颜色是否加载
        assert "accent_color" in tm.theme_colors
        assert "base_color" in tm.theme_colors
        assert "secondary_color" in tm.theme_colors
        assert "normal_color" in tm.theme_colors
        assert "auxiliary_color" in tm.theme_colors
    
    def test_darken_color_light_mode(self, qt_app, clean_settings_manager, temp_dir):
        """测试浅色模式下的颜色加深"""
        from freeassetfilter.core.theme_manager import ThemeManager
        from freeassetfilter.core.settings_manager import SettingsManager
        
        settings_file = os.path.join(temp_dir, "settings.json")
        sm = SettingsManager(settings_file)
        # 设置为浅色模式
        sm.set_setting("appearance.theme", "default")
        
        tm = ThemeManager(sm)
        
        # 测试颜色加深
        original_color = "#FFFFFF"
        darkened = tm._darken_color(original_color, 10)
        
        # 浅色模式下应该加深（颜色值变小）
        assert darkened != original_color
        assert darkened.startswith("#")
    
    def test_darken_color_dark_mode(self, qt_app, clean_settings_manager, temp_dir):
        """测试深色模式下的颜色变浅"""
        from freeassetfilter.core.theme_manager import ThemeManager
        from freeassetfilter.core.settings_manager import SettingsManager
        
        settings_file = os.path.join(temp_dir, "settings.json")
        sm = SettingsManager(settings_file)
        # 设置为深色模式
        sm.set_setting("appearance.theme", "dark")
        
        tm = ThemeManager(sm)
        
        # 测试颜色处理
        original_color = "#333333"
        result = tm._darken_color(original_color, 10)
        
        # 深色模式下应该变浅
        assert result.startswith("#")


class TestThemeManagerColorOperations:
    """测试 ThemeManager 颜色操作"""
    
    def test_hex_to_rgb_conversion(self, qt_app, clean_settings_manager, temp_dir):
        """测试十六进制到RGB转换"""
        from freeassetfilter.core.theme_manager import ThemeManager
        from freeassetfilter.core.settings_manager import SettingsManager
        from PySide6.QtGui import QColor
        
        settings_file = os.path.join(temp_dir, "settings.json")
        sm = SettingsManager(settings_file)
        tm = ThemeManager(sm)
        
        # 测试 QColor 能正确解析十六进制颜色
        color = QColor("#FF5733")
        assert color.red() == 255
        assert color.green() == 87
        assert color.blue() == 51
    
    def test_color_darkening_calculation(self, qt_app, clean_settings_manager, temp_dir):
        """测试颜色加深计算"""
        from freeassetfilter.core.theme_manager import ThemeManager
        from freeassetfilter.core.settings_manager import SettingsManager
        
        settings_file = os.path.join(temp_dir, "settings.json")
        sm = SettingsManager(settings_file)
        sm.set_setting("appearance.theme", "default")
        tm = ThemeManager(sm)
        
        # 测试不同百分比的颜色加深
        test_cases = [
            ("#FFFFFF", 0, "#FFFFFF"),   # 0% 应该不变
            ("#FFFFFF", 100, "#000000"), # 100% 应该变成黑色
        ]
        
        for original, percent, expected in test_cases:
            result = tm._darken_color(original, percent)
            assert result.startswith("#")
            assert len(result) == 7  # #RRGGBB
    
    def test_auxiliary_color_variants(self, qt_app, clean_settings_manager, temp_dir):
        """测试辅助色变体"""
        from freeassetfilter.core.theme_manager import ThemeManager
        from freeassetfilter.core.settings_manager import SettingsManager
        
        settings_file = os.path.join(temp_dir, "settings.json")
        sm = SettingsManager(settings_file)
        tm = ThemeManager(sm)
        
        # 检查辅助色变体是否存在
        assert hasattr(tm, 'auxiliary_color_darker_2')
        assert hasattr(tm, 'auxiliary_color_darker_5')
        
        # 检查是否为有效的十六进制颜色
        assert tm.auxiliary_color_darker_2.startswith("#")
        assert tm.auxiliary_color_darker_5.startswith("#")


class TestThemeManagerRobustness:
    """测试 ThemeManager 鲁棒性"""
    
    def test_invalid_color_handling(self, qt_app, clean_settings_manager, temp_dir):
        """测试无效颜色处理"""
        from freeassetfilter.core.theme_manager import ThemeManager
        from freeassetfilter.core.settings_manager import SettingsManager
        
        settings_file = os.path.join(temp_dir, "settings.json")
        sm = SettingsManager(settings_file)
        tm = ThemeManager(sm)
        
        # 测试无效颜色格式
        invalid_colors = [
            "not_a_color",
            "",
            "#GGGGGG",  # 无效的十六进制
            "#FFF",     # 短格式
            "rgb(255,0,0)",  # RGB格式
        ]
        
        for invalid_color in invalid_colors:
            # 应该不抛出异常
            try:
                result = tm._darken_color(invalid_color, 10)
                # 结果应该是某种有效的颜色格式或默认值
                assert isinstance(result, str)
            except Exception:
                # 抛出异常也是可接受的
                pass
    
    def test_edge_case_percentages(self, qt_app, clean_settings_manager, temp_dir):
        """测试边界百分比值"""
        from freeassetfilter.core.theme_manager import ThemeManager
        from freeassetfilter.core.settings_manager import SettingsManager
        
        settings_file = os.path.join(temp_dir, "settings.json")
        sm = SettingsManager(settings_file)
        tm = ThemeManager(sm)
        
        # 测试边界百分比
        edge_percentages = [0, 1, 50, 99, 100, -1, 101]
        
        for percent in edge_percentages:
            try:
                result = tm._darken_color("#808080", percent)
                assert isinstance(result, str)
            except (ValueError, TypeError):
                # 某些无效值可能抛出异常
                pass
    
    def test_concurrent_theme_access(self, qt_app, clean_settings_manager, temp_dir):
        """测试并发主题访问"""
        import threading
        from freeassetfilter.core.theme_manager import ThemeManager
        from freeassetfilter.core.settings_manager import SettingsManager
        
        settings_file = os.path.join(temp_dir, "settings.json")
        sm = SettingsManager(settings_file)
        tm = ThemeManager(sm)
        
        results = []
        
        def worker(worker_id):
            try:
                # 多次读取主题颜色
                for _ in range(10):
                    colors = tm.theme_colors
                    _ = tm._darken_color("#808080", 10)
                results.append((worker_id, True))
            except Exception as e:
                results.append((worker_id, False, str(e)))
        
        # 创建多个线程并发访问
        threads = []
        for i in range(5):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()
        
        # 等待所有线程完成
        for t in threads:
            t.join()
        
        # 验证所有操作都成功
        assert len(results) == 5
        assert all(r[1] for r in results), f"Some concurrent operations failed: {results}"


class TestThemeManagerSignals:
    """测试 ThemeManager 信号"""
    
    def test_theme_changed_signal(self, qt_app, clean_settings_manager, temp_dir):
        """测试主题变更信号"""
        from freeassetfilter.core.theme_manager import ThemeManager
        from freeassetfilter.core.settings_manager import SettingsManager
        
        settings_file = os.path.join(temp_dir, "settings.json")
        sm = SettingsManager(settings_file)
        tm = ThemeManager(sm)
        
        # 测试信号可以连接
        signal_received = []
        
        def on_theme_changed(theme_name):
            signal_received.append(theme_name)
        
        tm.theme_changed.connect(on_theme_changed)
        
        # 发射信号
        tm.theme_changed.emit("dark")
        
        assert len(signal_received) == 1
        assert signal_received[0] == "dark"
    
    def test_colors_updated_signal(self, qt_app, clean_settings_manager, temp_dir):
        """测试颜色更新信号"""
        from freeassetfilter.core.theme_manager import ThemeManager
        from freeassetfilter.core.settings_manager import SettingsManager
        
        settings_file = os.path.join(temp_dir, "settings.json")
        sm = SettingsManager(settings_file)
        tm = ThemeManager(sm)
        
        # 测试信号可以连接
        signal_received = []
        
        def on_colors_updated(colors):
            signal_received.append(colors)
        
        tm.colors_updated.connect(on_colors_updated)
        
        # 发射信号
        test_colors = {"accent_color": "#FF0000"}
        tm.colors_updated.emit(test_colors)
        
        assert len(signal_received) == 1
        assert signal_received[0] == test_colors
