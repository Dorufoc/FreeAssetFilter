# -*- coding: utf-8 -*-
"""
theme_editor 组件测试
测试 freeassetfilter/components/theme_editor.py 的 ThemeEditor 组件

测试覆盖：
1. ThemeEditor 创建与基本属性（QScrollArea 子类、信号存在）
2. preset_themes / custom_themes 列表内容
3. 信号发射（theme_selected, add_new_design, theme_applied）
4. 公共方法（get_selected_theme, 主题切换）
"""

import pytest


class TestThemeEditorCreation:
    """测试 ThemeEditor 创建"""

    def test_editor_can_be_created(self, qt_app):
        """测试 ThemeEditor 可以正常创建并初始化"""
        from freeassetfilter.components.theme_editor import ThemeEditor
        from PySide6.QtWidgets import QScrollArea

        editor = ThemeEditor()
        try:
            assert editor is not None
            assert isinstance(editor, QScrollArea)
            assert hasattr(editor, "theme_selected")
            assert hasattr(editor, "add_new_design")
            assert hasattr(editor, "theme_applied")
        finally:
            editor.close()
            editor.deleteLater()

    def test_preset_themes_populated(self, qt_app):
        """测试 preset_themes 包含 6 个预设主题"""
        from freeassetfilter.components.theme_editor import ThemeEditor

        editor = ThemeEditor()
        try:
            themes = editor.preset_themes
            assert len(themes) == 6
            names = [t["name"] for t in themes]
            assert "活力蓝" in names
            assert "热情红" in names
            assert "清新绿" in names
            assert "魅力紫" in names
        finally:
            editor.close()
            editor.deleteLater()

    def test_custom_themes_contains_custom_design(self, qt_app):
        """测试 custom_themes 包含默认自定义设计"""
        from freeassetfilter.components.theme_editor import ThemeEditor

        editor = ThemeEditor()
        try:
            assert len(editor.custom_themes) >= 1
            assert editor.custom_themes[0]["name"] == "自定义设计1"
        finally:
            editor.close()
            editor.deleteLater()


class TestThemeEditorSignals:
    """测试 ThemeEditor 信号"""

    def test_theme_selected_emitted_on_card_click(self, qt_app):
        """测试点击预设主题卡片时发射 theme_selected 信号"""
        from freeassetfilter.components.theme_editor import ThemeEditor

        editor = ThemeEditor()
        try:
            qt_app.processEvents()
            captured = []

            def slot(data):
                captured.append(data)

            editor.theme_selected.connect(slot)
            card = editor.preset_grid.itemAt(0).widget()
            editor.on_theme_card_clicked(card)

            assert len(captured) == 1
            assert isinstance(captured[0], dict)
            assert captured[0]["name"] == "活力蓝"
        finally:
            editor.close()
            editor.deleteLater()

    def test_add_new_design_emitted(self, qt_app):
        """测试 on_add_card_clicked 发射 add_new_design 信号"""
        from freeassetfilter.components.theme_editor import ThemeEditor

        editor = ThemeEditor()
        try:
            captured = []

            def slot():
                captured.append(True)

            editor.add_new_design.connect(slot)
            editor.on_add_card_clicked(editor.add_card)

            assert len(captured) == 1
        finally:
            editor.close()
            editor.deleteLater()

    def test_theme_applied_emitted(self, qt_app):
        """测试 on_apply_clicked 发射 theme_applied 信号"""
        from freeassetfilter.components.theme_editor import ThemeEditor

        editor = ThemeEditor()
        try:
            qt_app.processEvents()
            captured = []

            def slot():
                captured.append(True)

            editor.theme_applied.connect(slot)

            # 先选中主题再应用
            card = editor.preset_grid.itemAt(0).widget()
            editor.on_theme_card_clicked(card)
            editor.on_apply_clicked()

            assert len(captured) == 1
        finally:
            editor.close()
            editor.deleteLater()


class TestThemeEditorProperties:
    """测试 ThemeEditor 属性和方法"""

    def test_get_selected_theme_returns_dict_after_selection(self, qt_app):
        """测试选中主题后 get_selected_theme 返回正确主题"""
        from freeassetfilter.components.theme_editor import ThemeEditor

        editor = ThemeEditor()
        try:
            qt_app.processEvents()
            card = editor.preset_grid.itemAt(1).widget()
            editor.on_theme_card_clicked(card)

            result = editor.get_selected_theme()
            assert result is not None
            assert result["name"] == "热情红"
            assert isinstance(result["colors"], list)
            assert len(result["colors"]) > 0
        finally:
            editor.close()
            editor.deleteLater()

    def test_selected_theme_updated_after_different_card_click(self, qt_app):
        """测试点击不同主题卡片后选中的主题正确更新"""
        from freeassetfilter.components.theme_editor import ThemeEditor

        editor = ThemeEditor()
        try:
            qt_app.processEvents()

            card1 = editor.preset_grid.itemAt(0).widget()
            editor.on_theme_card_clicked(card1)
            assert editor.get_selected_theme()["name"] == "活力蓝"

            card2 = editor.preset_grid.itemAt(2).widget()
            editor.on_theme_card_clicked(card2)
            assert editor.get_selected_theme()["name"] == "蜂蜜黄"
        finally:
            editor.close()
            editor.deleteLater()
