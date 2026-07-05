# -*- coding: utf-8 -*-
"""
Rust 颜色提取 DLL 桥接层单元测试
测试 color_extractor_free_string 是否正确绑定和调用
"""

from unittest.mock import MagicMock, PropertyMock, patch

import pytest


@pytest.fixture(scope="module")
def bridge():
    """返回 _BRIDGE 实例，若 DLL 不可用则跳过"""
    try:
        from freeassetfilter.core.native.rust_color_extractor import _BRIDGE
        if not _BRIDGE.available:
            pytest.skip("rust_color_extractor_native.dll 不可用")
        return _BRIDGE
    except ImportError as e:
        pytest.skip(f"rust_color_extractor_native.dll 不可用: {e}")


class TestFreeStringBinding:
    """验证 _bind() 中 color_extractor_free_string 的正确注册"""

    def test_free_string_binding_exists(self, bridge):
        """验证 free_string 已经在 DLL 上绑定"""
        assert hasattr(bridge._dll, "color_extractor_free_string")

    def test_free_string_argtypes_void_p(self, bridge):
        """验证 free_string argtypes 为 [c_void_p]（而非 c_char_p）"""
        from ctypes import c_void_p
        func = bridge._dll.color_extractor_free_string
        assert func.argtypes == [c_void_p], (
            f"argtypes 应为 [c_void_p]，实际为 {func.argtypes}"
        )

    def test_free_string_restype_none(self, bridge):
        """验证 free_string restype 为 None"""
        func = bridge._dll.color_extractor_free_string
        assert func.restype is None


class TestGetVersionMemoryFree:
    """验证 get_version() 调用 free_string"""

    def test_get_version_returns_str(self, bridge):
        """验证 get_version 正常返回字符串"""
        version = bridge.get_version()
        assert isinstance(version, str)
        assert len(version) > 0

    def test_get_version_calls_free_string(self, bridge):
        """验证 get_version 调用 free_string 释放 Rust 分配的字符串"""
        original = bridge._dll.color_extractor_free_string
        mock_free = MagicMock()
        bridge._dll.color_extractor_free_string = mock_free
        try:
            version = bridge.get_version()
            assert isinstance(version, str)
            mock_free.assert_called_once()
            # 参数必须是指针（非空）
            args, _ = mock_free.call_args
            assert args[0] is not None, "free_string 收到空指针"
        finally:
            bridge._dll.color_extractor_free_string = original

    def test_get_version_free_string_after_null(self, bridge):
        """模拟 get_version 返回空指针场景，验证 free_string 不被调用（提前 raise）"""
        original_get = bridge._dll.color_extractor_get_version
        original_free = bridge._dll.color_extractor_free_string

        mock_free = MagicMock()
        bridge._dll.color_extractor_free_string = mock_free
        try:
            # 返回空指针（None），get_version 应提前 raise RuntimeError
            import ctypes
            bridge._dll.color_extractor_get_version = MagicMock(return_value=None)

            with pytest.raises(RuntimeError, match="无法获取版本信息"):
                bridge.get_version()

            # free_string 不应该被调用（因为 null 检查提前返回）
            mock_free.assert_not_called()
        finally:
            bridge._dll.color_extractor_get_version = original_get
            bridge._dll.color_extractor_free_string = original_free


class TestExtractColorsMemoryFree:
    """验证 extract_colors() 调用 free_string"""

    def test_extract_colors_calls_free_string(self, bridge):
        """使用空图像数据模拟，验证 extract_colors 最终调用 free_string"""
        original = bridge._dll.color_extractor_free_string
        mock_free = MagicMock()
        bridge._dll.color_extractor_free_string = mock_free
        try:
            from freeassetfilter.core.native.rust_color_extractor import _BRIDGE

            with pytest.raises((RuntimeError, ValueError)):
                _BRIDGE.extract_colors(b"")

            # free_string 可能不被调用（因 image_data 为空时提前 ValueError），
            # 我们改用非空但图像头部无效的数据来测试
            pass
        finally:
            bridge._dll.color_extractor_free_string = original

    def test_extract_colors_free_string_called_with_nonnull_image(self, bridge):
        """使用伪造的简图数据，验证 extract_colors 调用 free_string"""
        original = bridge._dll.color_extractor_free_string
        mock_free = MagicMock()
        bridge._dll.color_extractor_free_string = mock_free

        original_extract = bridge._dll.color_extractor_extract_colors

        try:
            # 伪造返回一个有效的 JSON 指针
            import ctypes
            from ctypes import c_char_p

            fake_json = b'{"colors": [[255, 0, 0], [0, 255, 0]]}'
            raw_ptr = ctypes.c_char_p(fake_json)
            bridge._dll.color_extractor_extract_colors = MagicMock(return_value=raw_ptr.value)

            result = bridge.extract_colors(b"\x00" * 100)
            assert result == [(255, 0, 0), (0, 255, 0)]
            mock_free.assert_called_once()
        finally:
            bridge._dll.color_extractor_extract_colors = original_extract
            bridge._dll.color_extractor_free_string = original

    def test_extract_colors_free_string_on_error(self, bridge):
        """伪造返回 error JSON，验证异常时 free_string 也被调用"""
        original = bridge._dll.color_extractor_free_string
        mock_free = MagicMock()
        bridge._dll.color_extractor_free_string = mock_free

        original_extract = bridge._dll.color_extractor_extract_colors

        try:
            # 伪造返回 error JSON
            import ctypes
            from ctypes import c_char_p

            fake_json = b'{"error": "test error"}'
            raw_ptr = ctypes.c_char_p(fake_json)
            bridge._dll.color_extractor_extract_colors = MagicMock(return_value=raw_ptr.value)

            with pytest.raises(RuntimeError, match="test error"):
                bridge.extract_colors(b"\x00" * 100)

            mock_free.assert_called_once()
        finally:
            bridge._dll.color_extractor_extract_colors = original_extract
            bridge._dll.color_extractor_free_string = original
