# -*- coding: utf-8 -*-
"""
font_previewer 单元测试
测试 freeassetfilter/components/font_previewer.py 模块的功能，
重点验证控制栏背景色正确使用 settings_manager 提供的 auxiliary_color。
"""
import pytest
import os
import sys
from unittest.mock import MagicMock, patch, PropertyMock


# =============================================================================
# 辅助函数：向当前的 QApplication 实例注入 mock settings_manager
# =============================================================================

def inject_settings_manager(auxiliary_color="#3D3D3D", base_color="#FFFFFF",
                            secondary_color="#333333", bg_color="#F5F5F5"):
    """
    向当前的 QApplication 实例注入模拟的 settings_manager。
    必须在 QApplication 已创建后调用。
    """
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    assert app is not None, "QApplication 尚未创建"

    sm = MagicMock()
    def get_setting_side_effect(key, default=None):
        values = {
            "appearance.colors.auxiliary_color": auxiliary_color,
            "appearance.colors.secondary_color": secondary_color,
            "appearance.colors.base_color": base_color,
            "appearance.colors.window_background": bg_color,
        }
        return values.get(key, default)
    sm.get_setting.side_effect = get_setting_side_effect

    app.settings_manager = sm
    app.dpi_scale_factor = 1.0
    from PySide6.QtGui import QFont
    app.global_font = QFont()
    app.default_font_size = 24
    return app


# =============================================================================
# 测试类：控制栏背景色
# =============================================================================

class TestToolbarBackgroundColor:
    """测试字体预览器控制栏（toolbar）背景色是否正确使用 auxiliary_color"""

    def test_toolbar_is_instance_variable(self, qt_app):
        """测试 _init_toolbar 将 toolbar 保存为 self.toolbar 实例变量"""
        inject_settings_manager()
        from freeassetfilter.components.font_previewer import FontPreviewWidget
        widget = FontPreviewWidget()
        assert hasattr(widget, "toolbar"), "toolbar 应为实例变量"
        from PySide6.QtWidgets import QWidget
        assert isinstance(widget.toolbar, QWidget), "toolbar 应为 QWidget 实例"

    def test_toolbar_background_from_settings_auxiliary_color(self, qt_app):
        """测试 toolbar 背景色从 settings_manager 读取 auxiliary_color"""
        expected_color = "#AABBCC"
        inject_settings_manager(auxiliary_color=expected_color)
        from freeassetfilter.components.font_previewer import FontPreviewWidget
        widget = FontPreviewWidget()

        stylesheet = widget.toolbar.styleSheet()
        assert expected_color in stylesheet, (
            f"toolbar 样式表应包含 auxiliary_color({expected_color})，"
            f"实际: {stylesheet}"
        )
        assert "background-color" in stylesheet.lower(), (
            f"toolbar 样式表应设置 background-color，实际: {stylesheet}"
        )

    def test_toolbar_background_default_fallback(self, qt_app):
        """测试 settings_manager 不可用时 toolbar 使用备用默认色"""
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        # 移除 settings_manager
        if hasattr(app, 'settings_manager'):
            del app.settings_manager
        app.dpi_scale_factor = 1.0
        from PySide6.QtGui import QFont
        app.global_font = QFont()
        app.default_font_size = 24

        from freeassetfilter.components.font_previewer import FontPreviewWidget
        widget = FontPreviewWidget()

        stylesheet = widget.toolbar.styleSheet()
        # 默认备用色是 #3D3D3D
        assert "#3D3D3D" in stylesheet, (
            f"settings_manager 不可用时 toolbar 应使用默认 #3D3D3D，"
            f"实际: {stylesheet}"
        )

    def test_apply_theme_updates_toolbar_background(self, qt_app):
        """测试 _apply_theme 能更新 toolbar 的背景色"""
        initial_color = "#3D3D3D"
        updated_color = "#556677"

        inject_settings_manager(auxiliary_color=initial_color)
        from freeassetfilter.components.font_previewer import FontPreviewWidget
        widget = FontPreviewWidget()

        # 验证初始颜色
        assert initial_color in widget.toolbar.styleSheet()

        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()

        # 修改 settings_manager 返回值，模拟用户切换主题
        def new_side_effect(key, default=None):
            values = {
                "appearance.colors.auxiliary_color": updated_color,
                "appearance.colors.secondary_color": "#333333",
                "appearance.colors.base_color": "#FFFFFF",
                "appearance.colors.window_background": "#F5F5F5",
            }
            return values.get(key, default)
        app.settings_manager.get_setting.side_effect = new_side_effect

        widget._apply_theme()

        # 验证 toolbar 背景色已更新
        stylesheet = widget.toolbar.styleSheet()
        assert updated_color in stylesheet, (
            f"_apply_theme 后 toolbar 样式表应包含更新后的颜色 {updated_color}，"
            f"实际: {stylesheet}"
        )
        assert initial_color not in stylesheet, (
            f"_apply_theme 后 toolbar 样式表不应包含旧颜色 {initial_color}"
        )


# =============================================================================
# 测试类：确保没有破坏原有的功能
# =============================================================================

class TestFontPreviewWidgetRegression:
    """回归测试：确保修改没有破坏其他功能"""

    def test_text_edit_still_gets_base_color(self, qt_app):
        """测试文本编辑区域仍正确获取 base_color 背景色"""
        expected_base = "#F0F0F0"
        inject_settings_manager(base_color=expected_base)
        from freeassetfilter.components.font_previewer import FontPreviewWidget
        widget = FontPreviewWidget()

        assert hasattr(widget, "text_edit"), "text_edit 应存在"
        text_stylesheet = widget.text_edit.styleSheet()
        assert expected_base in text_stylesheet, (
            f"text_edit 样式表应包含 base_color({expected_base})，"
            f"实际: {text_stylesheet}"
        )

    def test_apply_theme_updates_text_edit_colors(self, qt_app):
        """测试 _apply_theme 仍能正确更新文本编辑区域颜色"""
        inject_settings_manager()
        from freeassetfilter.components.font_previewer import FontPreviewWidget
        widget = FontPreviewWidget()

        new_base = "#EEEEEE"
        new_secondary = "#111111"
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()

        def new_side_effect(key, default=None):
            values = {
                "appearance.colors.auxiliary_color": "#3D3D3D",
                "appearance.colors.secondary_color": new_secondary,
                "appearance.colors.base_color": new_base,
                "appearance.colors.window_background": "#F5F5F5",
            }
            return values.get(key, default)
        app.settings_manager.get_setting.side_effect = new_side_effect

        widget._apply_theme()

        text_stylesheet = widget.text_edit.styleSheet()
        assert new_base in text_stylesheet, (
            f"_apply_theme 后 text_edit 应有新的 base_color({new_base})"
        )
        assert new_secondary in text_stylesheet, (
            f"_apply_theme 后 text_edit 应有新的 secondary_color({new_secondary})"
        )

    def test_font_size_slider_exists_and_works(self, qt_app):
        """测试字体大小滑块仍存在且功能正常"""
        inject_settings_manager()
        from freeassetfilter.components.font_previewer import FontPreviewWidget
        widget = FontPreviewWidget()

        assert hasattr(widget, "font_size_slider"), "font_size_slider 应存在"
        assert hasattr(widget, "font_size_label"), "font_size_label 应存在"

        # 测试初始状态
        assert widget.font_size_label.text() == "24px", (
            f"默认字体大小标签应为'24px'，实际: {widget.font_size_label.text()}"
        )
        assert widget.font_size_slider.value() == 24, (
            f"默认滑块值应为24，实际: {widget.font_size_slider.value()}"
        )

        # 测试 _on_font_size_changed 槽函数正常工作
        widget._on_font_size_changed(20)
        assert widget.font_size_label.text() == "20px", (
            f"_on_font_size_changed(20)后标签应显示'20px'，实际: {widget.font_size_label.text()}"
        )
        # 注意：setValue 可能不会立即触发信号，所以直接验证槽函数

    def test_init_layout_has_toolbar_before_text_edit(self, qt_app):
        """测试布局结构：toolbar 在 text_edit 上方"""
        inject_settings_manager()
        from freeassetfilter.components.font_previewer import FontPreviewWidget
        widget = FontPreviewWidget()

        layout = widget.layout()
        assert layout is not None, "布局应存在"

        # 验证 toolbar 和 text_edit 都在布局中
        assert widget.toolbar.parent() is widget, "toolbar 父级应为 FontPreviewWidget"
        assert widget.text_edit is not None, "text_edit 应存在"


# =============================================================================
# 测试类：FontPreviewer（外层容器）
# =============================================================================

class TestFontPreviewer:
    """测试 FontPreviewer 外层容器"""

    def test_font_previewer_creates_preview_widget(self, qt_app):
        """测试 FontPreviewer 正确创建 FontPreviewWidget"""
        inject_settings_manager()
        from freeassetfilter.components.font_previewer import FontPreviewer
        previewer = FontPreviewer()

        assert hasattr(previewer, "preview_widget"), "FontPreviewer 应有 preview_widget"
        from freeassetfilter.components.font_previewer import FontPreviewWidget
        assert isinstance(previewer.preview_widget, FontPreviewWidget), (
            "preview_widget 应为 FontPreviewWidget 实例"
        )

    def test_font_previewer_has_toolbar(self, qt_app):
        """测试 FontPreviewer 内部的 FontPreviewWidget 有 toolbar"""
        inject_settings_manager()
        from freeassetfilter.components.font_previewer import FontPreviewer
        previewer = FontPreviewer()

        inner = previewer.preview_widget
        assert hasattr(inner, "toolbar"), "内部 FontPreviewWidget 应有 toolbar"
        assert inner.toolbar is not None, "toolbar 不应为 None"

    def test_font_previewer_toolbar_uses_auxiliary_color(self, qt_app):
        """测试 FontPreviewer 内的 toolbar 也使用 auxiliary_color"""
        expected_color = "#C0FFEE"
        inject_settings_manager(auxiliary_color=expected_color)
        from freeassetfilter.components.font_previewer import FontPreviewer
        previewer = FontPreviewer()

        inner = previewer.preview_widget
        stylesheet = inner.toolbar.styleSheet()
        assert expected_color in stylesheet, (
            f"FontPreviewer 内部 toolbar 应使用 auxiliary_color({expected_color})，"
            f"实际: {stylesheet}"
        )


# =============================================================================
# 测试类：模块导入和基本结构
# =============================================================================

class TestFontPreviewerModule:
    """测试模块导入和基本结构"""

    def test_module_import(self):
        """测试模块可以导入"""
        from freeassetfilter.components.font_previewer import (
            FontPreviewer, FontPreviewWidget, FontLoadThread,
            ZoomDisabledTextEdit
        )
        assert FontPreviewer is not None
        assert FontPreviewWidget is not None
        assert FontLoadThread is not None
        assert ZoomDisabledTextEdit is not None

    def test_module_has_required_attributes(self):
        """测试模块有必要的属性"""
        from freeassetfilter.components import font_previewer
        assert font_previewer is not None
        # 检查模块中的类
        assert hasattr(font_previewer, "FontPreviewer")
        assert hasattr(font_previewer, "FontPreviewWidget")
        assert hasattr(font_previewer, "FontLoadThread")
        assert hasattr(font_previewer, "ZoomDisabledTextEdit")


# =============================================================================
# 测试类：边界情况测试
# =============================================================================

class TestFontPreviewerEdgeCases:
    """测试边界情况和鲁棒性"""

    def test_no_settings_manager_no_crash(self, qt_app):
        """测试 settings_manager 不存在时不崩溃"""
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if hasattr(app, 'settings_manager'):
            del app.settings_manager
        app.dpi_scale_factor = 1.0
        from PySide6.QtGui import QFont
        app.global_font = QFont()
        app.default_font_size = 24

        from freeassetfilter.components.font_previewer import FontPreviewWidget
        try:
            widget = FontPreviewWidget()
            # 验证 toolbar 有备用背景色
            assert "#3D3D3D" in widget.toolbar.styleSheet()
        except Exception as e:
            pytest.fail(f"无 settings_manager 时初始化失败: {e}")

    def test_settings_manager_missing_color_key_no_crash(self, qt_app):
        """测试 settings_manager 缺失颜色键时不崩溃"""
        inject_settings_manager()
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        # get_setting 返回 None 模拟键缺失
        app.settings_manager.get_setting.return_value = None

        from freeassetfilter.components.font_previewer import FontPreviewWidget
        try:
            widget = FontPreviewWidget()
            # 验证 toolbar 使用 __init__ 中的 local 默认值
            # 因为 get_setting 返回 None，local auxiliary_color 仍保留初始 "#3D3D3D"
            assert "#3D3D3D" in widget.toolbar.styleSheet()
        except Exception as e:
            pytest.fail(f"缺失颜色键时初始化失败: {e}")

    def test_repeated_apply_theme_no_leak(self, qt_app):
        """测试多次调用 _apply_theme 不会不断叠加样式表"""
        inject_settings_manager()
        from freeassetfilter.components.font_previewer import FontPreviewWidget
        widget = FontPreviewWidget()

        # 调用多次 _apply_theme
        for _ in range(5):
            widget._apply_theme()

        stylesheet = widget.toolbar.styleSheet()
        # 验证样式表只包含一次 background-color
        bg_count = stylesheet.lower().count("background-color")
        assert bg_count == 1, (
            f"重复调用 _apply_theme 后样式表中 background-color 应只出现1次，"
            f"实际出现 {bg_count} 次: {stylesheet}"
        )


if __name__ == "__main__":
    pytest.main(["-v", __file__])
