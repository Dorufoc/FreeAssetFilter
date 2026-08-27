# -*- coding: utf-8 -*-
"""todo 29（测试夹具扩充）Python 集成层夹具回归：全格式经桥命中 T1 原生路径。

覆盖 ``tests/unit/core/thumbnail_fixtures/`` 固化夹具（19 个，全部 <512KB，
由 ``.omo/evidence/thumbnail-rust-refactor/task-29-gen-fixtures.py`` 确定性
生成）经 ``RustThumbnailBridge.generate_rgba_with_status(path, 64, 64)``
的真实解码回路。

**原生路径命中口径**（桥内无 Python 回退——``generate_rgba_with_status``
直调 DLL ``native_generate_thumbnail``，返回 ``(bytes, 0)`` 即原生解码成功）：

* **强断言（逐像素一致）**：无损格式的桥输出与 PIL 独立解码路径
  ``Image.open(f).convert("RGBA").tobytes()`` 逐字节比对。源图均 ≤64px 且
  T1 缩放「不放大」（lib.rs resize_dimensions fill=false），输出 = 源尺寸
  恒等映射，像素级可比。覆盖 png×4 / bmp×2 / tiff×2 / webp-lossless /
  ppm / qoi / tga / ico / gif 动画+interlaced 共 14 夹具；
* **弱断言（非 None 且通道=4）**：jpeg（zune-jpeg 与 PIL 有损解码逐像素
  一致不可行）、psd（1036 缩略图经 JPEG 有损链路）、dds/icns（PIL 无对应
  解码器，按构造公式断言期望值）。

**avif/heic/jp2 门控用例**：bundled ffmpeg 最小构建无对应 demuxer，
lib.rs ``CAPABILITY_GATED_IMAGE_EXTS`` 对这四扩展名静态返回 -6——夹具不
固化（T1 无消费方），测试内 skipif 门控现场生成到 tmp_path 验证门控契约；
编码器缺失时 skip 非 fail。

夹具生成策略（PIL 能写→固化文件；不能写→手工构造已验证字节并记录理由）
详见生成脚本 docstring 与 learnings.md Task 29 条目。
"""

from __future__ import annotations

import io
import os
from typing import Any, List, Tuple

import pytest
from PIL import Image

from freeassetfilter.core.native.bridges.rust_thumbnail_bridge import (
    STATUS_OK,
    STATUS_UNSUPPORTED,
    RustThumbnailBridge,
)


pytestmark = pytest.mark.unit


FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "thumbnail_fixtures")
MAX_FIXTURE_BYTES = 512 * 1024
THUMB_WIDTH, THUMB_HEIGHT = 64, 64

# 无损格式：桥输出与 PIL 独立解码逐像素比对（强断言集合）
PIXEL_EXACT_BASENAMES: Tuple[str, ...] = (
    "sample_p6.ppm",
    "sample_qoi.qoi",
    "sample_bmp24.bmp",
    "sample_bmp_rle8.bmp",
    "sample_tga24.tga",
    "sample_ico_png.ico",
    "sample_gif_anim.gif",
    "sample_gif_interlaced.gif",
    "sample_png_rgb.png",
    "sample_png_rgba.png",
    "sample_png_gray.png",
    "sample_png_pal.png",
    "sample_tiff_lzw.tif",
    "sample_tiff_deflate.tif",
    "sample_webp_lossless.webp",
)

# 五类原生路径命中必验格式 → 夹具名（jpeg 走弱断言，其余强断言）
FIVE_CATEGORY_BASENAMES: Tuple[str, ...] = (
    "sample_png_rgb.png",
    "sample_bmp24.bmp",
    "sample_jpeg.jpg",
    "sample_webp_lossless.webp",
    "sample_tiff_lzw.tif",
)


def _fixture_names() -> List[str]:
    """列出夹具目录全部文件名（排序稳定）。"""
    return sorted(name for name in os.listdir(FIXTURE_DIR)
                  if os.path.isfile(os.path.join(FIXTURE_DIR, name)))


def _can_encode(fmt: str) -> bool:
    """探测当前 Pillow 是否具备 fmt 编码能力（能力探测，失败即 False）。"""
    try:
        buf = io.BytesIO()
        Image.new("RGB", (8, 8)).save(buf, fmt)
        return True
    except Exception:  # noqa: BLE001 —— 能力探测，任何失败都视为不可用
        return False


_HAS_AVIF_ENCODER = _can_encode("AVIF")
_HAS_HEIF_ENCODER = _can_encode("HEIF")
_HAS_JP2_ENCODER = _can_encode("JPEG2000")


@pytest.fixture
def rust_bridge() -> Any:
    """提供可用性门控的 RustThumbnailBridge 实例（镜像 test_status_channel.py）。"""
    inst = RustThumbnailBridge()
    if not inst.available:
        pytest.skip("thumbnail_generator.dll 不可用，跳过夹具集成测试")
    return inst


# =============================================================================
# 夹具清单：<512KB 硬约束
# =============================================================================
class TestFixtureInventory:
    """固化夹具的体积与完整性约束。"""

    def test_fixture_dir_nonempty_and_all_under_512kb(self) -> None:
        """夹具目录非空且每个文件严格小于 512KB。"""
        names = _fixture_names()
        assert names, f"夹具目录为空: {FIXTURE_DIR}"
        for name in names:
            size = os.path.getsize(os.path.join(FIXTURE_DIR, name))
            assert 0 < size < MAX_FIXTURE_BYTES, f"{name} 大小 {size} B 越界"


# =============================================================================
# 全量夹具：桥 generate_rgba_with_status 契约
# =============================================================================
class TestBridgeNativeDecodeAllFixtures:
    """每个固化夹具经桥解码返回 ``(bytes, 0)`` 且形状自洽。"""

    @pytest.mark.parametrize("name", _fixture_names())
    def test_bridge_generates_rgba_with_ok_status(
        self, rust_bridge: Any, name: str
    ) -> None:
        """单夹具回路：status==0、通道==4、len(raw)==w*h*4、尺寸 ≤ 请求值。"""
        path = os.path.join(FIXTURE_DIR, name)
        generated, status = rust_bridge.generate_rgba_with_status(
            path, THUMB_WIDTH, THUMB_HEIGHT
        )
        assert status == STATUS_OK, f"{name} 桥状态码 {status}"
        assert generated is not None, f"{name} 未产出 RGBA"
        raw, out_w, out_h, channels = generated  # type: ignore[misc]
        assert channels == 4, f"{name} 通道数 {channels}"
        assert len(raw) == out_w * out_h * channels, f"{name} 缓冲长度不自洽"
        assert 0 < out_w <= THUMB_WIDTH and 0 < out_h <= THUMB_HEIGHT, \
            f"{name} 输出尺寸 {out_w}x{out_h} 越界（T1 不放大）"


# =============================================================================
# 强断言：无损格式与 PIL 独立解码逐像素一致
# =============================================================================
class TestPixelExactAgainstPilReference:
    """桥输出 == PIL 直解 RGBA（源 ≤64px + 不放大 ⇒ 恒等映射可比）。"""

    @pytest.mark.parametrize("name", PIXEL_EXACT_BASENAMES)
    def test_lossless_fixture_matches_pil_decode(
        self, rust_bridge: Any, name: str
    ) -> None:
        """逐字节比对桥 RGBA 与 PIL 参照解码（含尺寸恒等）。"""
        path = os.path.join(FIXTURE_DIR, name)
        reference = Image.open(path).convert("RGBA")

        generated, status = rust_bridge.generate_rgba_with_status(
            path, THUMB_WIDTH, THUMB_HEIGHT
        )
        assert status == STATUS_OK and generated is not None
        raw, out_w, out_h, _channels = generated  # type: ignore[misc]
        assert (out_w, out_h) == reference.size, \
            f"{name} 尺寸 {out_w}x{out_h} != PIL {reference.size}"
        assert raw == reference.tobytes(), f"{name} 像素与 PIL 解码不一致"


# =============================================================================
# 弱断言/公式断言：有损与 PIL 无解码器的格式
# =============================================================================
class TestHandmadeAndLossyExpectations:
    """jpeg/psd 弱断言；dds/icns 按构造公式精确断言。"""

    def test_jpeg_decodes_native_with_four_channels(self, rust_bridge: Any) -> None:
        """jpeg：非 None 且通道=4（有损解码跨实现逐像素一致不可行）。"""
        path = os.path.join(FIXTURE_DIR, "sample_jpeg.jpg")
        generated, status = rust_bridge.generate_rgba_with_status(
            path, THUMB_WIDTH, THUMB_HEIGHT
        )
        assert status == STATUS_OK
        assert generated is not None
        raw, out_w, out_h, channels = generated  # type: ignore[misc]
        assert channels == 4
        assert 0 < out_w <= THUMB_WIDTH and 0 < out_h <= THUMB_HEIGHT
        assert len(raw) == out_w * out_h * channels

    def test_psd_returns_1036_thumbnail_dimensions(self, rust_bridge: Any) -> None:
        """psd：解码产物为 1036 缩略图（16x16 JPEG 有损链路，仅锁尺寸）。"""
        path = os.path.join(FIXTURE_DIR, "sample_psd_1036.psd")
        generated, status = rust_bridge.generate_rgba_with_status(
            path, THUMB_WIDTH, THUMB_HEIGHT
        )
        assert status == STATUS_OK
        assert generated is not None
        raw, out_w, out_h, channels = generated  # type: ignore[misc]
        assert (out_w, out_h) == (16, 16), f"1036 缩略图应为 16x16，got {out_w}x{out_h}"
        assert channels == 4
        assert len(raw) == out_w * out_h * channels

    def test_dds_bc1_solid_red_formula(self, rust_bridge: Any) -> None:
        """dds BC1：标准纯红块 → 4x4 全 (255,0,0,255)（构造公式精确断言）。"""
        path = os.path.join(FIXTURE_DIR, "sample_dds_bc1.dds")
        generated, status = rust_bridge.generate_rgba_with_status(
            path, THUMB_WIDTH, THUMB_HEIGHT
        )
        assert status == STATUS_OK
        assert generated is not None
        raw, out_w, out_h, _channels = generated  # type: ignore[misc]
        assert (out_w, out_h) == (4, 4)
        assert raw == bytes([255, 0, 0, 255]) * 16

    def test_icns_ic04_png_entry_formula(self, rust_bridge: Any) -> None:
        """icns ic04(PNG16)：内嵌纯色 PNG → 16x16 全 (11,220,80,255)。"""
        path = os.path.join(FIXTURE_DIR, "sample_icns_png.icns")
        generated, status = rust_bridge.generate_rgba_with_status(
            path, THUMB_WIDTH, THUMB_HEIGHT
        )
        assert status == STATUS_OK
        assert generated is not None
        raw, out_w, out_h, _channels = generated  # type: ignore[misc]
        assert (out_w, out_h) == (16, 16)
        assert raw == bytes([11, 220, 80, 255]) * 256


# =============================================================================
# 五类原生路径命中契约：png/bmp/jpeg/webp/tiff
# =============================================================================
class TestNativePathHitFiveCategories:
    """png/bmp/jpeg/webp/tiff 五类的原生路径命中显式验证。

    桥内无 Python 回退：``generate_rgba_with_status`` 返回 ``(bytes, 0)``
    即证明 DLL 解码管线消费了该文件。png/bmp/webp/tiff 叠加强断言
    （与 PIL 直解逐像素一致）；jpeg 因有损走弱断言。
    """

    @pytest.mark.parametrize("name", FIVE_CATEGORY_BASENAMES)
    def test_category_hits_native_decode_path(
        self, rust_bridge: Any, name: str
    ) -> None:
        """五类逐一命中：成功态 + 通道=4；无损四类再锁像素级一致。"""
        path = os.path.join(FIXTURE_DIR, name)
        generated, status = rust_bridge.generate_rgba_with_status(
            path, THUMB_WIDTH, THUMB_HEIGHT
        )
        assert status == STATUS_OK, f"{name} 未命中原生解码（status={status}）"
        assert generated is not None
        raw, out_w, out_h, channels = generated  # type: ignore[misc]
        assert channels == 4
        assert len(raw) == out_w * out_h * channels

        if name != "sample_jpeg.jpg":  # jpeg 有损：仅弱断言（见类 docstring）
            reference = Image.open(path).convert("RGBA")
            assert (out_w, out_h) == reference.size
            assert raw == reference.tobytes(), f"{name} 与 PIL 直解不一致"


# =============================================================================
# avif/heic/jp2：skipif 门控的能力门控容器契约
# =============================================================================
class TestCapabilityGatedContainers:
    """CAPABILITY_GATED_IMAGE_EXTS（avif/heic/heif/jp2）静态 -6 门控契约。

    bundled ffmpeg 最小构建无对应 demuxer 且无 T1 解码器 → lib.rs 在解码
    分发前快速返回 UNSUPPORTED(-6) 交 Python 回退链。夹具不固化（T1 无
    消费方），现场生成到 tmp_path；编码器缺失时 skip 非 fail。
    """

    def _assert_gated_unsupported(self, rust_bridge: Any, path: str) -> None:
        """公共断言体：桥返回 (None, -6)，errorlog 前后清理。"""
        assert rust_bridge.clear_error_log() is True
        try:
            generated, status = rust_bridge.generate_rgba_with_status(
                path, THUMB_WIDTH, THUMB_HEIGHT
            )
            assert generated is None
            assert status == STATUS_UNSUPPORTED, \
                f"{path} 应被能力门控拦截 -6，got {status}"
        finally:
            assert rust_bridge.clear_error_log() is True

    @pytest.mark.skipif(not _HAS_AVIF_ENCODER, reason="Pillow 无法编码 AVIF（pillow-avif 缺失）")
    def test_avif_capability_gated(self, rust_bridge: Any, tmp_path: Any) -> None:
        """AVIF：能编码时验证 -6 门控；不能编码时 skip。"""
        path = str(tmp_path / "gated.avif")
        Image.new("RGB", (16, 16), (20, 200, 80)).save(path, format="AVIF")
        self._assert_gated_unsupported(rust_bridge, path)

    @pytest.mark.skipif(not _HAS_HEIF_ENCODER, reason="Pillow 无法编码 HEIF（pillow-heif 缺失）")
    def test_heic_capability_gated(self, rust_bridge: Any, tmp_path: Any) -> None:
        """HEIC：能编码时验证 -6 门控；pillow-heif 缺失时 skip。"""
        path = str(tmp_path / "gated.heic")
        Image.new("RGB", (16, 16), (20, 200, 80)).save(path, format="HEIF")
        self._assert_gated_unsupported(rust_bridge, path)

    @pytest.mark.skipif(not _HAS_JP2_ENCODER, reason="Pillow 无法编码 JP2（OpenJPEG 缺失）")
    def test_jp2_capability_gated(self, rust_bridge: Any, tmp_path: Any) -> None:
        """JP2：OpenJPEG 可用时验证 -6 门控（JPEG2000 格式名写出 .jp2）。"""
        path = str(tmp_path / "gated.jp2")
        Image.new("RGB", (16, 16), (20, 200, 80)).save(path, format="JPEG2000")
        self._assert_gated_unsupported(rust_bridge, path)
