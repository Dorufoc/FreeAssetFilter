# -*- coding: utf-8 -*-
"""
C++ 扩展模块测试
测试 C++ 扩展是否正确加载和工作
"""
import pytest
import sys
import os
from pathlib import Path


class TestCppColorExtractor:
    """测试 C++ 颜色提取器扩展"""
    
    def test_cpp_color_extractor_module_exists(self):
        """测试 C++ 颜色提取器模块存在"""
        module_path = Path('freeassetfilter/core/cpp_color_extractor/__init__.py')
        assert module_path.exists(), "C++ 颜色提取器模块不存在"
    
    def test_cpp_color_extractor_setup_exists(self):
        """测试 C++ 颜色提取器 setup 文件存在"""
        setup_path = Path('freeassetfilter/core/cpp_color_extractor/setup.py')
        assert setup_path.exists(), "C++ 颜色提取器 setup.py 不存在"
    
    def test_cpp_color_extractor_can_import(self):
        """测试 C++ 颜色提取器可以导入"""
        try:
            from freeassetfilter.core import cpp_color_extractor
            assert True
        except ImportError as e:
            pytest.skip(f"C++ 颜色提取器未编译或无法导入: {e}")
    
    def test_color_extractor_class(self):
        """测试 ColorExtractor 类"""
        try:
            from freeassetfilter.core.cpp_color_extractor import ColorExtractor
            assert ColorExtractor is not None
            
            # 测试可以实例化
            extractor = ColorExtractor()
            assert extractor is not None
        except ImportError:
            pytest.skip("C++ 颜色提取器未编译")


class TestCppLutPreview:
    """测试 C++ LUT 预览扩展"""
    
    def test_cpp_lut_preview_module_exists(self):
        """测试 C++ LUT 预览模块存在"""
        module_path = Path('freeassetfilter/core/cpp_lut_preview/__init__.py')
        assert module_path.exists(), "C++ LUT 预览模块不存在"
    
    def test_cpp_lut_preview_setup_exists(self):
        """测试 C++ LUT 预览 setup 文件存在"""
        setup_path = Path('freeassetfilter/core/cpp_lut_preview/setup.py')
        assert setup_path.exists(), "C++ LUT 预览 setup.py 不存在"
    
    def test_cpp_lut_preview_can_import(self):
        """测试 C++ LUT 预览可以导入"""
        try:
            from freeassetfilter.core import cpp_lut_preview
            assert True
        except ImportError as e:
            pytest.skip(f"C++ LUT 预览未编译或无法导入: {e}")


class TestCppExtensionIntegration:
    """测试 C++ 扩展集成"""
    
    def test_cpp_extensions_directory_structure(self):
        """测试 C++ 扩展目录结构"""
        cpp_dirs = [
            'freeassetfilter/core/cpp_color_extractor',
            'freeassetfilter/core/cpp_lut_preview'
        ]
        
        for dir_path in cpp_dirs:
            assert Path(dir_path).is_dir(), f"目录不存在: {dir_path}"
            
            # 检查必要的文件
            assert Path(f"{dir_path}/__init__.py").exists()
            assert Path(f"{dir_path}/setup.py").exists()
    
    def test_cpp_extensions_have_source_files(self):
        """测试 C++ 扩展有源文件"""
        # 检查颜色提取器源文件
        color_extractor_sources = list(Path('freeassetfilter/core/cpp_color_extractor').glob('*.cpp'))
        color_extractor_sources += list(Path('freeassetfilter/core/cpp_color_extractor').glob('*.c'))
        
        # 检查 LUT 预览源文件
        lut_preview_sources = list(Path('freeassetfilter/core/cpp_lut_preview').glob('*.cpp'))
        lut_preview_sources += list(Path('freeassetfilter/core/cpp_lut_preview').glob('*.c'))
        
        # 至少应该有一些源文件或已编译的扩展
        has_sources = len(color_extractor_sources) > 0 or len(lut_preview_sources) > 0
        
        # 或者检查是否有已编译的 pyd 文件
        has_compiled = (
            list(Path('freeassetfilter/core/cpp_color_extractor').glob('*.pyd')) or
            list(Path('freeassetfilter/core/cpp_lut_preview').glob('*.pyd'))
        )
        
        assert has_sources or has_compiled, "没有找到 C++ 源文件或已编译的扩展"


class TestCppExtensionFallback:
    """测试 C++ 扩展回退机制"""
    
    def test_python_fallback_for_color_extractor(self):
        """测试颜色提取器有 Python 回退实现"""
        from freeassetfilter.core.color_extractor import ColorExtractor
        
        # 应该可以使用 Python 实现
        extractor = ColorExtractor()
        assert extractor is not None
    
    def test_color_extractor_extract_method(self):
        """测试颜色提取器的 extract 方法"""
        from freeassetfilter.core.color_extractor import ColorExtractor
        
        extractor = ColorExtractor()
        
        # 测试 extract 方法存在
        assert hasattr(extractor, 'extract')
        assert callable(getattr(extractor, 'extract'))
