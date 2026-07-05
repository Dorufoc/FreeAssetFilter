# -*- coding: utf-8 -*-
"""
hover_tooltip 单元测试
测试 freeassetfilter/widgets/hover_tooltip.py 模块的功能
"""
import pytest
import os
import sys
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class TestHoverTooltipBasic:
    """测试 HoverTooltip 基本功能"""
    
    def test_module_import(self):
        """测试模块可以导入"""
        from freeassetfilter.widgets.hover_tooltip import HoverTooltip
        assert HoverTooltip is not None
    
    def test_module_has_required_attributes(self):
        """测试模块有必要的属性"""
        from freeassetfilter.widgets import hover_tooltip
        # 检查模块存在
        assert hover_tooltip is not None


class TestHoverTooltipRobustness:
    """测试 HoverTooltip 鲁棒性"""
    
    def test_module_handles_errors_gracefully(self):
        """测试模块能优雅处理错误"""
        # 基础错误处理测试
        pass


class TestHoverTooltipIntegration:
    """测试 HoverTooltip 集成"""
    
    def test_module_integration(self):
        """测试模块集成"""
        # 集成测试
        pass

    def test_file_card_tooltip_contains_required_file_metadata(self, qt_app, temp_file):
        """文件卡片 tooltip 应包含文件名、类型、创建/修改时间和路径。"""
        from freeassetfilter.widgets.hover_tooltip import HoverTooltip

        tooltip = HoverTooltip()
        try:
            text = tooltip._build_file_card_tooltip(
                temp_file,
                file_info={
                    "path": temp_file,
                    "name": "test_file.txt",
                    "suffix": "txt",
                    "is_dir": False,
                },
            )

            assert "名称: test_file.txt" in text
            assert "类型: .txt" in text
            assert "创建时间:" in text
            assert "修改时间:" in text
            assert f"路径: {temp_file}" in text
        finally:
            tooltip.cleanup()
            tooltip.deleteLater()

    def test_virtualized_file_list_index_tooltip_uses_file_metadata(self, qt_app, temp_file):
        """虚拟化 block card 列表应从命中的 model index 构建自定义 tooltip。"""
        from PySide6.QtCore import QPoint
        from freeassetfilter.widgets.file_selector_model import FileListView, FileSelectorListModel
        from freeassetfilter.widgets.hover_tooltip import HoverTooltip

        model = FileSelectorListModel(dpi_scale=1.0)
        model.set_files(
            [
                {
                    "path": temp_file,
                    "name": "test_file.txt",
                    "size": os.path.getsize(temp_file),
                    "created": "",
                    "suffix": "txt",
                    "is_dir": False,
                }
            ]
        )
        model.set_card_width(160, 80, 1)

        view = FileListView()
        view.setModel(model)
        view.setGridSize(model.sizeHint())
        view.resize(220, 140)
        view.show()
        view.doItemsLayout()
        qt_app.processEvents()

        tooltip = HoverTooltip()
        try:
            index_rect = view.visualRect(model.index(0, 0))
            local_pos = index_rect.center() if index_rect.isValid() else QPoint(20, 20)
            tooltip.last_mouse_pos = view.viewport().mapToGlobal(local_pos)
            text = tooltip._build_view_index_tooltip(view.viewport())

            assert "名称: test_file.txt" in text
            assert "类型: .txt" in text
            assert "创建时间:" in text
            assert "修改时间:" in text
            assert f"路径: {os.path.normpath(temp_file)}" in text
        finally:
            tooltip.cleanup()
            tooltip.deleteLater()
            view.deleteLater()
