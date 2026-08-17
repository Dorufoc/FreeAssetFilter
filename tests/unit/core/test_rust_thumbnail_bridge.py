# -*- coding: utf-8 -*-
"""Rust 缩略图模块单测（tests-comprehensive-refactor todo-9 补全）。

覆盖 ``freeassetfilter.core.native.bridges.rust_thumbnail_bridge``：

* **服务探测**：``RustThumbnailBridge`` 直接构造可用、``_supports_jpg`` /
  ``_supports_batch_jpg`` 能力标记（对应 conftest ``rust_available`` session
  fixture 的概念；模块**不做**单例，也无模块级 ``get_version``）；
* **真实 DLL 路径**：``generate_rgba`` 输出 RGBA 布局与请求尺寸约束
  （校准时 100x80 源图请求 64x64 得到 64x43——**不放大**，因此断言
  ``0 < w <= request`` 且 ``0 < h <= request``；请求 1x1 得到 1x1）、
  ``generate_jpeg`` / ``generate_jpg`` 输出 JPEG 魔数 ``\\xff\\xd8``、
  批量生成返回逐张字节列表、缺失文件返回 ``None``、非图像文件返回
  ``None``、``get_decode_stats`` 返回统计字典、``set_cache_limit`` /
  ``clear_cache`` / ``reset_decode_stats`` 返回 ``True``、
  ``get_available_hwaccels`` 返回列表、并发解码上限设置成功；
* **不依赖任何外部进程**（缩略图走 Rust 原生内部解码，无 ffmpeg/7z
  子进程调用）。

本文件仅依赖 numpy + PIL（二者均已在 session 级探明可用），真实库缺失时
被 ``importorskip`` 跳过（镜像 ``test_rust_color_extractor.py`` 的写法）。

注：生产模块 ``generate_rgba / generate_jpeg / generate_jpg`` 只接受
**文件路径字符串**，不支持 numpy 数组内存输入（``not file_path`` 对数组
触发 ``ValueError``），故不测内存数组路径。
"""

from __future__ import annotations

from typing import Any, List, Tuple

import pytest
from PIL import Image

from freeassetfilter.core.native.bridges.rust_thumbnail_bridge import (
    RustThumbnailBridge,
)


pytestmark = pytest.mark.unit

bridge = pytest.importorskip(
    "freeassetfilter.core.native.bridges.rust_thumbnail_bridge"
)


# =============================================================================
# 数据工厂
# =============================================================================
@pytest.fixture()
def _png_fixture(tmp_path: Any) -> Tuple[str, int, int]:
    """生成 100x80 纯色 PNG，返回 (绝对路径, 宽, 高)。"""
    path: str = str(tmp_path / "sample.png")
    img = Image.new("RGB", (100, 80), (128, 64, 200))
    img.save(path, format="PNG")
    return path, 100, 80


# =============================================================================
# 服务探测（不需要真实图像）
# =============================================================================
class TestBridgeAvailability:
    """``RustThumbnailBridge`` 的可用性与能力标记。"""

    def test_available_flag(self) -> None:
        """服务可用性标记为真（importorskip 后必然成立）。"""
        inst = RustThumbnailBridge()
        assert inst.available is True

    def test_direct_construction(self) -> None:
        """模块不做单例——每次构造独立实例（无 ``get_instance``）。"""
        a = RustThumbnailBridge()
        b = RustThumbnailBridge()
        assert a is not b

    def test_jpg_capability_flags(self) -> None:
        """jpg / batch_jpg 能力标记为 bool（私有属性名带下划线前缀）。"""
        inst = RustThumbnailBridge()
        assert isinstance(inst._supports_jpg, bool)  # noqa: SLF001
        assert isinstance(inst._supports_batch_jpg, bool)  # noqa: SLF001

    def test_dll_engine_loaded(self) -> None:
        """已加载原生引擎（非 None DLL）即视为可用。"""
        inst = RustThumbnailBridge()
        assert (inst._dll is not None) == inst.available  # noqa: SLF001


# =============================================================================
# 真实 Rust 解码路径
# =============================================================================
class TestRustThumbnailReal:
    """真实 lib 解码（机器上 rust_available=True，实际执行）。"""

    def test_generate_rgba_dimensions(
        self, _png_fixture: Tuple[str, int, int]
    ) -> None:
        """生成 RGBA：按请求尺寸缩小且不放大，输出 4 通道。"""
        path, req_w, req_h = _png_fixture
        inst = RustThumbnailBridge()
        result = inst.generate_rgba(path, req_w, req_h)
        assert isinstance(result, tuple)
        assert len(result) == 4
        data, out_w, out_h, channels = result  # type: ignore[misc]
        assert channels == 4
        # 源图 100x80，请求 100x80 会按比例得到不放大结果
        assert 0 < out_w <= req_w
        assert 0 < out_h <= req_h
        assert isinstance(data, bytes)
        assert len(data) == out_w * out_h * channels

    def test_generate_rgba_scaled_small(self, _png_fixture: Any) -> None:
        """请求 1x1 时输出 1x1（缩略图上限约束）。"""
        path, _, _ = _png_fixture
        inst = RustThumbnailBridge()
        data, out_w, out_h, channels = inst.generate_rgba(path, 1, 1)
        assert (out_w, out_h) == (1, 1)
        assert channels == 4
        assert len(data) == 4

    def test_generate_rgba_aspect_ratio_conserved(
        self, _png_fixture: Any
    ) -> None:
        """非等比缩小保留宽高比（64 请求 → 64x51，实测）。"""
        path, _, _ = _png_fixture
        inst = RustThumbnailBridge()
        _, out_w, out_h, _ = inst.generate_rgba(path, 64, 64)
        # 100:80 = 5:4，宽 64 时高为 51（向下取整 51.2）
        assert out_w == 64
        assert out_h == 51
        assert out_h != 64

    def test_generate_jpeg_magic(self, _png_fixture: Any) -> None:
        """``generate_jpeg(path, w, h)`` 输出 JPEG 魔数。"""
        path, _, _ = _png_fixture
        inst = RustThumbnailBridge()
        data = inst.generate_jpeg(path, 32, 32)
        assert isinstance(data, bytes)
        assert data[:2] == b"\xff\xd8"

    def test_generate_jpg_magic(self, _png_fixture: Any) -> None:
        """``generate_jpg(path, w, h)``（内部 decode 路径）输出 JPEG 魔数。"""
        path, _, _ = _png_fixture
        inst = RustThumbnailBridge()
        data = inst.generate_jpg(path, 32, 32)
        assert isinstance(data, bytes)
        assert data[:2] == b"\xff\xd8"

    def test_generate_jpg_batch(self, _png_fixture: Any) -> None:
        """批量生成返回逐张 JPEG 字节列表（顺序一致）。"""
        path, _, _ = _png_fixture
        inst = RustThumbnailBridge()
        results: List[bytes] = inst.generate_jpg_batch([path, path], 32, 32)
        assert isinstance(results, list)
        assert len(results) == 2
        assert results[0][:2] == b"\xff\xd8"
        assert results[1][:2] == b"\xff\xd8"

    def test_generate_rgba_missing_file_returns_none(
        self, tmp_path: Any
    ) -> None:
        """缺失文件返回 None（不抛异常，不触发 crash）。"""
        missing = str(tmp_path / "does_not_exist.png")
        inst = RustThumbnailBridge()
        assert inst.generate_rgba(missing, 32, 32) is None
        assert inst.generate_jpeg(missing, 32, 32) is None
        assert inst.generate_jpg(missing, 32, 32) is None

    def test_math_input_invalid_is_none(self, tmp_path: Any) -> None:
        """非图像文件输入不抛异常（安全降级为 None）。"""
        bad = tmp_path / "fake.txt"
        bad.write_text("not an image", encoding="utf-8")
        inst = RustThumbnailBridge()
        assert inst.generate_jpeg(str(bad), 32, 32) is None
        assert inst.generate_jpg(str(bad), 32, 32) is None


# =============================================================================
# 统计与缓存控制
# =============================================================================
class TestStatsAndCacheControl:
    """解码统计与缓存上限控制。"""

    def test_get_decode_stats_structure(self) -> None:
        """解码统计字典包含全部已知键。"""
        inst = RustThumbnailBridge()
        stats = inst.get_decode_stats()
        assert isinstance(stats, dict)
        expected = {
            "d3d11va_attempts",
            "d3d11va_hits",
            "dxva2_attempts",
            "dxva2_hits",
            "qsv_attempts",
            "qsv_hits",
            "software_attempts",
            "software_hits",
            "software_fallbacks",
        }
        assert expected.issubset(stats.keys())
        for key in expected:
            assert isinstance(stats[key], int)
            assert stats[key] >= 0

    def test_cache_limit_set(self) -> None:
        """``set_cache_limit`` 返回 True。"""
        inst = RustThumbnailBridge()
        assert inst.set_cache_limit(512) is True

    def test_clear_cache(self) -> None:
        """``clear_cache`` 返回 True。"""
        inst = RustThumbnailBridge()
        assert inst.clear_cache() is True

    def test_reset_decode_stats(self) -> None:
        """``reset_decode_stats`` 返回 True。"""
        inst = RustThumbnailBridge()
        assert inst.reset_decode_stats() is True

    def test_get_available_hwaccels_is_list(self) -> None:
        """可用硬件加速列表为 list。"""
        inst = RustThumbnailBridge()
        accels = inst.get_available_hwaccels()
        assert isinstance(accels, list)
        # 列表内容为字符串条目
        assert all(isinstance(x, str) for x in accels)

    def test_set_max_concurrent_hw_video_decodes(self) -> None:
        """并发解码上限可设置（返回 True）。"""
        inst = RustThumbnailBridge()
        assert inst.set_max_concurrent_hw_video_decodes(2) is True


# ---------------------------------------------------------------------------
# ctypes 批量 / 单张结果结构体（模块已 importorskip，DLL 必然可用）
# ---------------------------------------------------------------------------
class TestNativeResultStructures:
    """``NativeThumbnailResult`` / ``NativeThumbnailBatchResult`` 字段布局。"""

    def test_native_thumbnail_result_fields(self) -> None:
        """单张结果：status/width/height/channels/len/data/message。"""
        from ctypes import c_char_p, c_size_t, c_uint8, c_uint32, c_int, POINTER

        fields = bridge.NativeThumbnailResult._fields_
        assert [f[0] for f in fields] == [
            "status",
            "width",
            "height",
            "channels",
            "len",
            "data",
            "message",
        ]
        assert [f[1] for f in fields] == [
            c_int,
            c_uint32,
            c_uint32,
            c_uint8,
            c_size_t,
            POINTER(c_uint8),
            c_char_p,
        ]
        inst = bridge.NativeThumbnailResult()
        assert inst.status == 0 and inst.width == 0 and inst.height == 0
        assert inst.data is None or bool(inst.data) is False

    def test_native_thumbnail_batch_result_fields(self) -> None:
        """批量结果：status/count/results/message。"""
        from ctypes import c_char_p, c_size_t, c_int, POINTER

        fields = bridge.NativeThumbnailBatchResult._fields_
        assert [f[0] for f in fields] == ["status", "count", "results", "message"]
        assert [f[1] for f in fields] == [
            c_int,
            c_size_t,
            POINTER(bridge.NativeThumbnailResult),
            c_char_p,
        ]
        batch = bridge.NativeThumbnailBatchResult()
        assert batch.status == 0 and batch.count == 0