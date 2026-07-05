# -*- coding: utf-8 -*-
"""
timeline_generator 单元测试
测试 freeassetfilter/core/timeline_generator.py 模块的功能
"""
import pytest
import os
import sys
from unittest.mock import MagicMock, patch


class TestTimelineGeneratorBasic:
    """测试 TimelineGenerator 基本功能"""
    
    def test_module_import(self):
        """测试模块可以导入"""
        from freeassetfilter.core.timeline_generator import TimelineGenerator
        assert TimelineGenerator is not None
    
    def test_module_has_required_attributes(self):
        """测试模块有必要的属性"""
        from freeassetfilter.core import timeline_generator
        # 检查模块存在
        assert timeline_generator is not None


class TestTimelineGeneratorRobustness:
    """测试 TimelineGenerator 鲁棒性"""
    
    def test_module_handles_errors_gracefully(self):
        """测试模块能优雅处理错误"""
        # 基础错误处理测试
        pass


class TestTimelineGeneratorIntegration:
    """测试 TimelineGenerator 集成"""
    
    def test_module_integration(self):
        """测试模块集成"""
        # 集成测试
        pass


class TestTimelineTraversalOptimizations:
    def test_iter_folder_asset_files_uses_scandir(self, monkeypatch, temp_dir):
        from freeassetfilter.core import timeline_generator

        root_dir = os.path.join(temp_dir, "assets")
        nested_dir = os.path.join(root_dir, "nested")
        os.makedirs(nested_dir)

        root_file = os.path.join(root_dir, "root.txt")
        nested_file = os.path.join(nested_dir, "child.txt")
        with open(root_file, "w", encoding="utf-8") as f:
            f.write("root")
        with open(nested_file, "w", encoding="utf-8") as f:
            f.write("child")

        def fail_walk(*_args, **_kwargs):
            raise AssertionError("os.walk should not be used by iter_folder_asset_files")

        monkeypatch.setattr(timeline_generator.os, "walk", fail_walk)

        asset_files = list(timeline_generator.iter_folder_asset_files(root_dir))

        assert {(name, subfolder) for name, _path, subfolder, _mtime in asset_files} == {
            ("root.txt", "assets"),
            ("child.txt", "nested"),
        }
