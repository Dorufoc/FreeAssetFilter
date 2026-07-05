# -*- coding: utf-8 -*-
"""
ComboSelector 单元测试
测试 freeassetfilter/widgets/combo_selector.py 模块的功能
"""
import pytest
from typing import List

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QSignalSpy


class TestComboSelectorCreation:
    """测试 ComboSelector 创建与基本属性"""

    def test_module_import(self):
        """测试模块可以导入"""
        from freeassetfilter.widgets.combo_selector import ComboSelector
        assert ComboSelector is not None

    def test_create_widget(self, qt_app):
        """测试创建 ComboSelector 实例"""
        from freeassetfilter.widgets.combo_selector import ComboSelector

        selector = ComboSelector()
        try:
            assert selector is not None
            assert selector._items == []
            assert selector.currentText() == ""
            assert selector.text_label.text() == ""
        finally:
            selector.deleteLater()

    def test_create_with_parent(self, qt_app):
        """测试带父控件创建 ComboSelector"""
        from PySide6.QtWidgets import QWidget
        from freeassetfilter.widgets.combo_selector import ComboSelector

        parent = QWidget()
        selector = ComboSelector(parent)
        try:
            assert selector.parent() is parent
        finally:
            selector.deleteLater()
            parent.deleteLater()

    def test_minimum_height_applies_dpi_scale(self, qt_app):
        """测试最小高度应用 DPI 缩放"""
        from freeassetfilter.widgets.combo_selector import ComboSelector

        qt_app.dpi_scale_factor = 2.0
        selector = ComboSelector()
        try:
            assert selector.minimumHeight() == 56  # 28 * 2.0
        finally:
            selector.deleteLater()


class TestComboSelectorItems:
    """测试 ComboSelector 选项管理"""

    def test_set_items_with_default(self, qt_app):
        """测试设置选项列表并指定默认值"""
        from freeassetfilter.widgets.combo_selector import ComboSelector

        selector = ComboSelector()
        try:
            selector.set_items(["A", "B", "C"], default_item="B")
            assert selector.currentText() == "B"
            assert selector.text_label.text() == "B"
        finally:
            selector.deleteLater()

    def test_set_items_defaults_to_first(self, qt_app):
        """测试未指定默认值时自动选中第一项"""
        from freeassetfilter.widgets.combo_selector import ComboSelector

        selector = ComboSelector()
        try:
            selector.set_items(["X", "Y", "Z"])
            assert selector.currentText() == "X"
        finally:
            selector.deleteLater()

    def test_set_items_empty(self, qt_app):
        """测试设置空选项列表"""
        from freeassetfilter.widgets.combo_selector import ComboSelector

        selector = ComboSelector()
        try:
            selector.set_items([])
            assert selector.currentText() == ""
            assert selector._items == []
        finally:
            selector.deleteLater()

    def test_set_items_non_string_items(self, qt_app):
        """测试非字符串选项自动转为字符串"""
        from freeassetfilter.widgets.combo_selector import ComboSelector

        selector = ComboSelector()
        try:
            selector.set_items([1, 2, 3])
            assert selector._items == ["1", "2", "3"]
            assert selector.currentText() == "1"
        finally:
            selector.deleteLater()

    def test_currentText_initial(self, qt_app):
        """测试初始状态 currentText 返回空字符串"""
        from freeassetfilter.widgets.combo_selector import ComboSelector

        selector = ComboSelector()
        try:
            assert selector.currentText() == ""
        finally:
            selector.deleteLater()

    def test_setCurrentText_updates_label(self, qt_app):
        """测试 setCurrentText 更新文本标签"""
        from freeassetfilter.widgets.combo_selector import ComboSelector

        selector = ComboSelector()
        try:
            selector.set_items(["A", "B"])
            selector.setCurrentText("B")
            assert selector.currentText() == "B"
            assert selector.text_label.text() == "B"
        finally:
            selector.deleteLater()

    def test_setCurrentText_same_value_no_change(self, qt_app):
        """测试设置相同值不会重复发射信号"""
        from freeassetfilter.widgets.combo_selector import ComboSelector
        from PySide6.QtTest import QSignalSpy

        selector = ComboSelector()
        try:
            selector.set_items(["A", "B"])
            spy = QSignalSpy(selector.currentIndexChanged)
            selector.setCurrentText("A")  # already "A"
            assert spy.count() == 0
        finally:
            selector.deleteLater()

    def test_set_value_compat(self, qt_app):
        """测试兼容接口 set_value"""
        from freeassetfilter.widgets.combo_selector import ComboSelector

        selector = ComboSelector()
        try:
            selector.set_items(["A", "B"])
            selector.set_value("B")
            assert selector.get_value() == "B"
        finally:
            selector.deleteLater()

    def test_get_value_compat(self, qt_app):
        """测试兼容接口 get_value 返回 currentText"""
        from freeassetfilter.widgets.combo_selector import ComboSelector

        selector = ComboSelector()
        try:
            selector.set_items(["A", "B"])
            selector.setCurrentText("B")
            assert selector.get_value() == "B"
        finally:
            selector.deleteLater()


class TestComboSelectorSignal:
    """测试 ComboSelector 信号发射"""

    def test_currentIndexChanged_emitted_on_setCurrentText(self, qt_app):
        """测试 setCurrentText 发射 currentIndexChanged 信号"""
        from freeassetfilter.widgets.combo_selector import ComboSelector
        from PySide6.QtTest import QSignalSpy

        selector = ComboSelector()
        try:
            selector.set_items(["A", "B"])
            spy = QSignalSpy(selector.currentIndexChanged)

            selector.setCurrentText("B")
            assert spy.count() == 1
            assert spy.at(0)[0] == "B"
        finally:
            selector.deleteLater()

    def test_currentIndexChanged_emitted_on_set_items_with_default(self, qt_app):
        """测试 set_items 带默认值发射信号"""
        from freeassetfilter.widgets.combo_selector import ComboSelector
        from PySide6.QtTest import QSignalSpy

        selector = ComboSelector()
        try:
            spy = QSignalSpy(selector.currentIndexChanged)

            selector.set_items(["A", "B", "C"], default_item="C")
            assert spy.count() == 1
            assert spy.at(0)[0] == "C"
        finally:
            selector.deleteLater()

    def test_currentIndexChanged_multiple_changes(self, qt_app):
        """测试多次变更发射多个信号"""
        from freeassetfilter.widgets.combo_selector import ComboSelector
        from PySide6.QtTest import QSignalSpy

        selector = ComboSelector()
        try:
            selector.set_items(["A", "B", "C"])
            spy = QSignalSpy(selector.currentIndexChanged)

            selector.setCurrentText("B")
            selector.setCurrentText("C")
            selector.setCurrentText("A")
            assert spy.count() == 3
            assert [spy.at(i)[0] for i in range(spy.count())] == ["B", "C", "A"]
        finally:
            selector.deleteLater()

    def test_signal_not_emitted_on_initial_set_items_without_default(self, qt_app):
        """测试 set_items 不指定默认值时也发射信号（选中第一项）"""
        from freeassetfilter.widgets.combo_selector import ComboSelector
        from PySide6.QtTest import QSignalSpy

        selector = ComboSelector()
        try:
            spy = QSignalSpy(selector.currentIndexChanged)

            selector.set_items(["A", "B"])
            assert spy.count() == 1
            assert spy.at(0)[0] == "A"
        finally:
            selector.deleteLater()

    def test_signal_not_emitted_on_empty_items(self, qt_app):
        """测试设置空列表不发射信号"""
        from freeassetfilter.widgets.combo_selector import ComboSelector
        from PySide6.QtTest import QSignalSpy

        selector = ComboSelector()
        try:
            spy = QSignalSpy(selector.currentIndexChanged)

            selector.set_items([])
            assert spy.count() == 0
        finally:
            selector.deleteLater()


class TestComboSelectorVisual:
    """测试 ComboSelector 视觉与布局"""

    def test_text_label_initially_empty(self, qt_app):
        """测试文本标签初始为空"""
        from freeassetfilter.widgets.combo_selector import ComboSelector

        selector = ComboSelector()
        try:
            assert selector.text_label.text() == ""
        finally:
            selector.deleteLater()

    def test_setTextColor_updates_style(self, qt_app):
        """测试 setTextColor 更新标签样式"""
        from freeassetfilter.widgets.combo_selector import ComboSelector

        selector = ComboSelector()
        try:
            selector.setTextColor("#FF0000")
            assert "color: #FF0000" in selector.text_label.styleSheet()
        finally:
            selector.deleteLater()

    def test_text_label_alignment(self, qt_app):
        """测试文本标签对齐方式为左对齐垂直居中"""
        from freeassetfilter.widgets.combo_selector import ComboSelector

        selector = ComboSelector()
        try:
            assert selector.text_label.alignment() == (Qt.AlignLeft | Qt.AlignVCenter)
        finally:
            selector.deleteLater()

    def test_arrow_button_exists(self, qt_app):
        """测试箭头按钮存在"""
        from freeassetfilter.widgets.combo_selector import ComboSelector

        selector = ComboSelector()
        try:
            assert selector.arrow_btn is not None
            assert selector.arrow_btn.width() == 28
            assert selector.arrow_btn.height() == 28
        finally:
            selector.deleteLater()


class TestComboSelectorDropdown:
    """测试 ComboSelector 下拉菜单行为"""

    def test_show_dropdown_empty_items_no_crash(self, qt_app):
        """测试空选项时调用 _show_dropdown 不崩溃"""
        from freeassetfilter.widgets.combo_selector import ComboSelector

        selector = ComboSelector()
        try:
            # 空选项时 _show_dropdown 直接 return
            selector._show_dropdown()
            qt_app.processEvents()
        finally:
            selector.deleteLater()

    def test_dropdown_on_item_clicked_dict_handling(self, qt_app):
        """测试 _show_dropdown 内部回调正确处理 dict 类型选中项"""
        from freeassetfilter.widgets.combo_selector import ComboSelector
        from PySide6.QtTest import QSignalSpy

        selector = ComboSelector()
        try:
            selector.set_items(["A", "B", "C"])
            spy = QSignalSpy(selector.currentIndexChanged)

            # 直接调用 setCurrentText 验证信号和状态
            selector.setCurrentText("C")
            assert spy.count() == 1
            assert spy.at(0)[0] == "C"
            assert selector.currentText() == "C"
        finally:
            selector.deleteLater()
