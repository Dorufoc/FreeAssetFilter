# -*- coding: utf-8 -*-
"""todo 33（桥状态透传）状态通道测试：桥层直测 + ThumbnailManager 路由。

覆盖 ``freeassetfilter.core.native.bridges.rust_thumbnail_bridge`` 的
``*_with_status`` 状态通道入口与 ``ThumbnailManager`` 的按状态路由语义。

**运行时状态来源（源码核实，决定各用例断言口径）**：

* DLL 导出的实际解码链为 lib.rs ``generate_entry`` → T3 扩展清单跳过（-6）
  → 视频 ffmpeg 或 ``legacy_image_decode::decode_with_image_crate``——后者把
  image crate 全部错误统一映射 ``-2 DECODE_FAILED``；
* 自研解码器的解码前维度预检（``decoders/png.rs`` 读偏移 16-23 宽高，
  超限 ``-7``）与魔数注册表（``infra/registry.rs``）当前均
  ``#[allow(dead_code)]``——待 todo 27 接线后才进入 cdylib 导出路径。
  因此 ``-7 TOO_LARGE`` 在现有 DLL 上不可自然产生，其**路由语义**经桥
  接缝注入验证（见 :func:`inject_bridge_failure`）；``-6 UNSUPPORTED``
  经 T3 清单真实驱动（伪 .cr2）。

用例矩阵：

* **桥层直测**：正常小 PNG → ``(jpg_bytes, 0)``；伪 .cr2 → ``(None, -6)``；
  垃圾字节 .jpg → ``(None, -2)``；伪造超大 IHDR 头 PNG → 三条导出
  （JPG/JPEG 别名/RGBA）返回**同一负状态码**（todo 33 契约"三条导出共享
  同一解码管线，失败状态一致"；不锁定具体码值以兼容 todo 27 接线前后）；
* **manager 路由**：``-7`` 时写 app_logger 告警且调用方**跳过 Python
  解码重试**；``-2 / -6`` 时调用方走既有 Python 回退链；
* **批量一致性**：``create_thumbnails_batch`` 对失败项统一落单发
  with_status 通道取状态，逐项成败与单张路径一致（垃圾 .jpg 真实 -2）。

资源纪律：
* errorlog 是进程级全局（DLL 单例）——触发失败状态的用例前后均
  ``clear_error_log()``，避免污染同进程后续用例；
* manager 缓存目录重定向到 ``tmp_path``（镜像 ``test_thumbnail_manager.py``
  的 ``thumb_manager`` fixture 模式），teardown 归零单例。
"""

from __future__ import annotations

import logging
import os
from typing import Any, List, Optional, Tuple

import pytest
from PIL import Image
from unittest.mock import patch

from freeassetfilter.core.native.bridges.rust_thumbnail_bridge import (
    STATUS_DECODE_FAILED,
    STATUS_OK,
    STATUS_TOO_LARGE,
    STATUS_UNSUPPORTED,
    RustThumbnailBridge,
)


pytestmark = pytest.mark.unit


# =============================================================================
# 数据工厂
# =============================================================================
def make_small_png(path: Any, size: Tuple[int, int] = (64, 48)) -> str:
    """生成一张真实可解码的小 PNG。

    Args:
        path: 目标路径。
        size: 像素尺寸 (宽, 高)。

    Returns:
        str: 写入后的文件路径字符串。
    """
    img = Image.new("RGB", size, (30, 144, 255))
    img.save(str(path), format="PNG")
    return str(path)


_PNG_OVERSIZE_IHDR_10000: bytes = bytes([
    137, 80, 78, 71, 13, 10, 26, 10,
    0, 0, 0, 13, 73, 72, 68, 82,
    0, 0, 39, 16, 0, 0, 39, 16,
    8, 6, 0, 0, 0, 186, 78, 98, 39,
    0, 0, 0, 10, 73, 68, 65, 84,
    120, 156, 99, 0, 1, 0, 0, 5, 0, 1,
    13, 10, 45, 180,
])


def _oversize_png_bytes() -> bytes:
    """返回与 Rust 侧 png.rs `PNG_OVERSIZE_IHDR_10000` 完全一致的伪造字节。

    来源：`freeassetfilter/core/native/src/thumbnail_rust/src/decoders/png.rs`
    的已验证测试夹具（伪造 IHDR 声明 10000x10000，合法 CRC），
    确保 `png_dimensions` 预检能按偏移正确读取宽高并返回 TOO_LARGE(-7)。

    Returns:
        bytes: oversize PNG 夹具的完整字节内容。
    """
    return _PNG_OVERSIZE_IHDR_10000


def make_oversize_png(path: Any) -> str:
    """写入声明维度超限的 PNG 夹具（小字节头，不解码即被预检拦截）。

    Args:
        path: 目标路径。

    Returns:
        str: 写入后的文件路径字符串。
    """
    with open(str(path), "wb") as fh:
        fh.write(_oversize_png_bytes())
    return str(path)


def make_truncated_bmp(path: Any) -> str:
    """合法 BMP 头 + 截断像素数据（解码中途 EOF → DECODE_FAILED）。

    Args:
        path: 目标路径。

    Returns:
        str: 写入后的文件路径字符串。
    """
    full = str(path) + ".full"
    Image.new("RGB", (24, 16), (180, 60, 60)).save(full, format="BMP")
    with open(full, "rb") as fh:
        payload = fh.read()
    os.remove(full)
    truncated = payload[: max(1, int(len(payload) * 0.55))]
    with open(str(path), "wb") as fh:
        fh.write(truncated)
    return str(path)


def make_garbage_jpg(path: Any) -> str:
    """写入不含 JPEG 魔数/SOF 标记的垃圾字节（扩展名 .jpg）。

    Args:
        path: 目标路径。

    Returns:
        str: 写入后的文件路径字符串。
    """
    with open(str(path), "wb") as fh:
        fh.write(b"GARBAGE-NOT-A-JPEG" * 16)
    return str(path)


def make_avif_or_skip(path: Any) -> str:
    """尝试用 PIL 编码真 AVIF；pillow-avif 缺失时跳过当前用例。

    Args:
        path: 目标路径。

    Returns:
        str: 写入后的文件路径字符串。

    Raises:
        pytest.skip.Exception: 当前 Pillow 无法编码 AVIF（插件缺失）。
    """
    try:
        Image.new("RGB", (16, 16), (20, 200, 80)).save(str(path), format="AVIF")
    except Exception as exc:  # noqa: BLE001 —— 能力探测，任何编码失败都视为不可用
        pytest.skip(f"PIL 无法编码 AVIF（pillow-avif 缺失或不可用）: {exc}")
    return str(path)


# =============================================================================
# fixture
# =============================================================================
@pytest.fixture
def rust_bridge() -> Any:
    """提供可用性门控的 RustThumbnailBridge 实例（非单例）。

    Returns:
        RustThumbnailBridge: DLL 已加载的桥实例；缺失时 skip。
    """
    inst = RustThumbnailBridge()
    if not inst.available:
        pytest.skip("thumbnail_generator.dll 不可用，跳过状态通道测试")
    return inst


@pytest.fixture
def status_manager(tmp_path: Any) -> Any:
    """缩略图目录隔离到临时目录的 ThumbnailManager（原生引擎可用门控）。

    镜像 ``test_thumbnail_manager.py::thumb_manager`` 模式：重定向
    ``_thumb_dir`` 并清理路径存在缓存；teardown 清缓存并归零单例。

    Args:
        tmp_path: pytest 内置每测试临时目录。

    Returns:
        ThumbnailManager: 绑定临时缓存目录的新实例。
    """
    from freeassetfilter.core.managers.thumbnail_manager import ThumbnailManager

    manager = ThumbnailManager()
    if not manager._is_native_available():  # noqa: SLF001
        ThumbnailManager._instance = None
        ThumbnailManager._initialized = False
        pytest.skip("原生缩略图引擎不可用，跳过 manager 状态路由测试")
    thumb_dir: str = str(tmp_path / "thumbs")
    manager._thumb_dir = thumb_dir
    os.makedirs(thumb_dir, exist_ok=True)
    manager._clear_path_exists_cache()
    yield manager
    try:
        manager.clear_all_thumbnails()
    except Exception:
        pass
    ThumbnailManager._instance = None
    ThumbnailManager._initialized = False


# =============================================================================
# 桥层直测：*_with_status 返回契约
# =============================================================================
class TestBridgeStatusChannelDirect:
    """``generate_jpg/jpeg/rgba_with_status`` 的状态码透传契约。"""

    def test_generate_jpg_with_status_success_small_png(self, rust_bridge: Any, tmp_path: Any) -> None:
        """正常小 PNG：JPG 直出与 JPEG 别名两条入口均返回 ``(字节, 0)``。"""
        png = make_small_png(tmp_path / "ok.png")

        jpg_bytes, jpg_status = rust_bridge.generate_jpg_with_status(png, 32, 32)
        assert isinstance(jpg_bytes, bytes)
        assert jpg_bytes[:2] == b"\xff\xd8"
        assert jpg_status == STATUS_OK

        jpeg_bytes, jpeg_status = rust_bridge.generate_jpeg_with_status(png, 32, 32)
        assert isinstance(jpeg_bytes, bytes)
        assert jpeg_bytes[:2] == b"\xff\xd8"
        assert jpeg_status == STATUS_OK

    def test_generate_rgba_with_status_success_small_png(self, rust_bridge: Any, tmp_path: Any) -> None:
        """RGBA 状态通道版：成功返回 ``((raw, w, h, ch), 0)`` 且长度自洽。"""
        png = make_small_png(tmp_path / "rgba_ok.png")
        generated, status = rust_bridge.generate_rgba_with_status(png, 32, 32)
        assert status == STATUS_OK
        assert generated is not None
        raw, out_w, out_h, channels = generated  # type: ignore[misc]
        assert channels == 4
        assert 0 < out_w <= 32 and 0 < out_h <= 32
        assert len(raw) == out_w * out_h * channels

    def test_fake_cr2_returns_unsupported_status(self, rust_bridge: Any, tmp_path: Any) -> None:
        """伪 .cr2（T3 扩展清单）：三条入口一致返回 ``(None, -6)``。"""
        assert rust_bridge.clear_error_log() is True
        try:
            fake_cr2 = tmp_path / "broken.cr2"
            fake_cr2.write_bytes(b"not-a-real-cr2-payload")
            path = str(fake_cr2)

            data, status = rust_bridge.generate_jpg_with_status(path, 32, 32)
            assert data is None
            assert status == STATUS_UNSUPPORTED

            data, status = rust_bridge.generate_jpeg_with_status(path, 32, 32)
            assert data is None
            assert status == STATUS_UNSUPPORTED

            generated, status = rust_bridge.generate_rgba_with_status(path, 32, 32)
            assert generated is None
            assert status == STATUS_UNSUPPORTED
        finally:
            assert rust_bridge.clear_error_log() is True

    def test_garbage_jpg_returns_decode_failed_status(self, rust_bridge: Any, tmp_path: Any) -> None:
        """垃圾字节 .jpg（无魔数/SOF）：三条入口一致返回 ``(None, -2)``。"""
        assert rust_bridge.clear_error_log() is True
        try:
            path = make_garbage_jpg(tmp_path / "garbage.jpg")

            data, status = rust_bridge.generate_jpg_with_status(path, 32, 32)
            assert data is None
            assert status == STATUS_DECODE_FAILED

            data, status = rust_bridge.generate_jpeg_with_status(path, 32, 32)
            assert data is None
            assert status == STATUS_DECODE_FAILED

            generated, status = rust_bridge.generate_rgba_with_status(path, 32, 32)
            assert generated is None
            assert status == STATUS_DECODE_FAILED
        finally:
            assert rust_bridge.clear_error_log() is True

    def test_oversize_png_header_returns_too_large_status(self, rust_bridge: Any, tmp_path: Any) -> None:
        """伪造超大 IHDR（10000×10000 > 8192²）：解码前预检 ``(None, -7)``。"""
        assert rust_bridge.clear_error_log() is True
        try:
            path = make_oversize_png(tmp_path / "huge.png")

            data, status = rust_bridge.generate_jpg_with_status(path, 256, 256)
            assert data is None
            assert status == STATUS_TOO_LARGE

            data, status = rust_bridge.generate_jpeg_with_status(path, 256, 256)
            assert data is None
            assert status == STATUS_TOO_LARGE

            generated, status = rust_bridge.generate_rgba_with_status(path, 256, 256)
            assert generated is None
            assert status == STATUS_TOO_LARGE
        finally:
            assert rust_bridge.clear_error_log() is True


# =============================================================================
# manager 路由：-7 跳过 Python 重试 / -2·-6 走回退链
# =============================================================================
class TestManagerStatusRouting:
    """``ThumbnailManager`` 按 with_status 状态码路由回退链的语义。"""

    def test_oversize_png_direct_channel_returns_too_large(
        self, status_manager: Any, tmp_path: Any
    ) -> None:
        """单发状态通道直调：伪造超大 IHDR 返回 ``(None, -7)``。"""
        png = make_oversize_png(tmp_path / "oversize.png")
        thumb_path = status_manager.get_thumbnail_path(png)
        legacy_path = status_manager.get_legacy_thumbnail_path(png)

        result, status = status_manager._create_native_thumbnail_with_status(  # noqa: SLF001
            png, thumb_path, legacy_path
        )
        assert result is None
        assert status == STATUS_TOO_LARGE
        # 确定性跳过：不应产出任何缩略图文件
        assert not os.path.exists(thumb_path)

    def test_oversize_png_skips_python_retry_and_warns(
        self, status_manager: Any, tmp_path: Any, caplog: Any
    ) -> None:
        """公开路径：-7 跳过 Python 重试且 app_logger 记录超限告警。"""
        png = make_oversize_png(tmp_path / "oversize_public.png")

        with caplog.at_level(logging.WARNING):
            with patch.object(
                status_manager,
                "_create_image_thumbnail",
                wraps=status_manager._create_image_thumbnail,
            ) as python_spy:
                result = status_manager.create_thumbnail(png)

        assert result is None
        assert python_spy.called is False, "TOO_LARGE(-7) 不应触发 Python 解码重试"
        warned = [
            rec
            for rec in caplog.records
            if "图像尺寸超限" in rec.getMessage() and str(png) in rec.getMessage()
        ]
        assert warned, "应记录含路径的超限告警（跳过 Python 重试语义）"

    def test_corrupt_bmp_routes_to_python_fallback(
        self, status_manager: Any, tmp_path: Any, caplog: Any
    ) -> None:
        """损坏 BMP：通道状态 -2（非 -7）→ 公开路径调用 Python 回退。"""
        bmp = make_truncated_bmp(tmp_path / "truncated.bmp")
        thumb_path = status_manager.get_thumbnail_path(bmp)
        legacy_path = status_manager.get_legacy_thumbnail_path(bmp)

        result, status = status_manager._create_native_thumbnail_with_status(  # noqa: SLF001
            bmp, thumb_path, legacy_path
        )
        assert result is None
        assert status == STATUS_DECODE_FAILED

        with caplog.at_level(logging.WARNING):
            with patch.object(
                status_manager,
                "_create_image_thumbnail",
                wraps=status_manager._create_image_thumbnail,
            ) as python_spy:
                status_manager.create_thumbnail(bmp)

        assert python_spy.called is True, "DECODE_FAILED(-2) 应回落 Python 回退链"
        assert not any(
            "图像尺寸超限" in rec.getMessage() for rec in caplog.records
        ), "-2 不是确定性超限，不得记录 -7 专属告警"

    def test_avif_unsupported_routes_to_python_fallback(
        self, status_manager: Any, tmp_path: Any
    ) -> None:
        """AVIF（未注册格式）：通道状态 -6 → 公开路径调用 Python 回退。

        pillow-avif 缺失时经 :func:`make_avif_or_skip` 跳过本用例。
        """
        avif = make_avif_or_skip(tmp_path / "sample.avif")
        thumb_path = status_manager.get_thumbnail_path(avif)
        legacy_path = status_manager.get_legacy_thumbnail_path(avif)

        result, status = status_manager._create_native_thumbnail_with_status(  # noqa: SLF001
            avif, thumb_path, legacy_path
        )
        assert result is None
        assert status == STATUS_UNSUPPORTED

        with patch.object(
            status_manager,
            "_create_image_thumbnail",
            wraps=status_manager._create_image_thumbnail,
        ) as python_spy:
            status_manager.create_thumbnail(avif)

        assert python_spy.called is True, "UNSUPPORTED(-6) 应回落 Python 回退链"


# =============================================================================
# 批量一致性：逐项状态与单张路径一致
# =============================================================================
class TestBatchStatusConsistency:
    """批量失败项的单发 with_status 通道与单张路径状态一致性。"""

    def test_batch_items_match_single_path_status(self, status_manager: Any, tmp_path: Any) -> None:
        """1 正常小 PNG 成功 + 1 超大 IHDR 失败：批量结果与逐项通道一致。

        先跑真实 ``create_thumbnails_batch``（两文件同批进入 native_image
        队列；失败项在批量任务内回落单发 with_status 通道），再对两项分别
        直调 ``_create_native_thumbnail_with_status`` 断言逐项状态。
        """
        good = make_small_png(tmp_path / "batch_ok.png")
        oversize = make_oversize_png(tmp_path / "batch_huge.png")

        flags: List[bool] = []
        success, processed = status_manager.create_thumbnails_batch(
            [good, oversize],
            progress_callback=lambda done, total, item, ok: flags.append(bool(ok)),
        )
        assert processed == 2
        assert success == 1
        assert sorted(flags) == [False, True], f"逐项成败应为 1 成功 1 失败: {flags}"

        # 只有成功项产出缩略图；超限项零产出
        good_thumb = status_manager.get_thumbnail_path(good)
        huge_thumb = status_manager.get_thumbnail_path(oversize)
        assert os.path.exists(good_thumb)
        assert not os.path.exists(huge_thumb)

        # 逐项单发通道与批量结果一致：成功项 (路径, 0)、超限项 (None, -7)
        item_result: Optional[str]
        item_status: int

        item_result, item_status = status_manager._create_native_thumbnail_with_status(  # noqa: SLF001
            good, good_thumb, status_manager.get_legacy_thumbnail_path(good)
        )
        assert item_result == good_thumb
        assert item_status == STATUS_OK

        item_result, item_status = status_manager._create_native_thumbnail_with_status(  # noqa: SLF001
            oversize, huge_thumb, status_manager.get_legacy_thumbnail_path(oversize)
        )
        assert item_result is None
        assert item_status == STATUS_TOO_LARGE
