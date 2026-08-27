# -*- coding: utf-8 -*-
"""todo 27（矩阵接通）三级格式矩阵测试：分类函数 + 分桶路由 + 三样本回退。

覆盖 ``ThumbnailManager`` 三级格式矩阵（T1 native / T2 ffmpeg /
T3 Python）在分类函数与批量分桶上的一致性，以及三样本端到端路由：

* **矩阵分类**：T1/T2/T3 扩展名逐一断言 ``is_image_file`` /
  ``is_video_file`` / ``is_media_file`` 的归类边界（含大写等价与
  非媒体快速排除）；
* **分桶路由**：png 进 native 链、ts 进视频链、svg 进 Python 专用链
  （spy 各生成入口，不触发真实子进程/解码）；
* **三样本路由**：avif（T2 门控容器）→ 原生 -6 → Python 桶；损坏 BMP
  （T1 解码失败）→ -2 → PIL 回退；伪扩展名 .txt（非媒体）→ 快速失败
  不挂起。

资源纪律：镜像 ``test_status_channel.py::status_manager`` fixture——
缓存目录重定向 ``tmp_path``，teardown 清缓存并归零单例；依赖原生引擎的
用例在 DLL 缺失时 skip。
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, List, Set, Tuple

import pytest
from PIL import Image
from unittest.mock import patch

from freeassetfilter.core.managers.thumbnail_manager import ThumbnailManager
from freeassetfilter.core.native.bridges.rust_thumbnail_bridge import (
    STATUS_DECODE_FAILED,
    STATUS_TOO_LARGE,
    STATUS_UNSUPPORTED,
)


pytestmark = pytest.mark.unit


# =============================================================================
# 数据工厂（镜像 test_status_channel.py）
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


def make_svg(path: Any) -> str:
    """写入最小合法 SVG 文本（内容不被解码——分桶测试中加载器已被 spy 替换）。

    Args:
        path: 目标路径。

    Returns:
        str: 写入后的文件路径字符串。
    """
    with open(str(path), "w", encoding="utf-8") as fh:
        fh.write('<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"/>')
    return str(path)


def make_stub_ts(path: Any) -> str:
    """写入 .ts 占位字节（内容不被探测——视频生成入口已被 spy 替换）。

    Args:
        path: 目标路径。

    Returns:
        str: 写入后的文件路径字符串。
    """
    with open(str(path), "wb") as fh:
        fh.write(b"\x47" + b"\x00" * 63)
    return str(path)


# =============================================================================
# fixture
# =============================================================================
@pytest.fixture
def matrix_manager(tmp_path: Any) -> Any:
    """缩略图目录隔离到临时目录的 ThumbnailManager（不门控原生可用性）。

    镜像 ``test_status_channel.py::status_manager`` 模式：重定向
    ``_thumb_dir`` 并清理路径存在缓存；teardown 清缓存并归零单例。

    Args:
        tmp_path: pytest 内置每测试临时目录。

    Returns:
        ThumbnailManager: 绑定临时缓存目录的实例。
    """
    manager = ThumbnailManager()
    thumb_dir: str = str(tmp_path / "thumbs")
    manager._thumb_dir = thumb_dir  # noqa: SLF001
    os.makedirs(thumb_dir, exist_ok=True)
    manager._clear_path_exists_cache()  # noqa: SLF001
    yield manager
    try:
        manager.clear_all_thumbnails()
    except Exception:
        pass
    ThumbnailManager._instance = None
    ThumbnailManager._initialized = False


@pytest.fixture
def native_matrix_manager(matrix_manager: Any) -> Any:
    """原生引擎可用性门控版（分桶与三样本路由依赖 Rust 链路）。

    Args:
        matrix_manager: 未门控的基础实例。

    Returns:
        ThumbnailManager: 原生引擎可用的同一实例；缺失时 skip。
    """
    if not matrix_manager._is_native_available():  # noqa: SLF001
        pytest.skip("原生缩略图引擎不可用，跳过矩阵路由测试")
    return matrix_manager


# =============================================================================
# 矩阵分类：三级扩展名 × 三个分类函数
# =============================================================================
class TestMatrixClassification:
    """三级矩阵在 ``is_image_file`` / ``is_video_file`` / ``is_media_file``
    上的归类边界。"""

    def test_t1_native_extensions_classified_as_image(
        self, matrix_manager: Any
    ) -> None:
        """T1 全表：每项均为图片+媒体且非视频，并覆盖注册表关键扩展名。"""
        t1_expected_keys = {
            ".pbm", ".pgm", ".ppm", ".pnm", ".pam",
            ".qoi", ".bmp", ".dib",
            ".tga", ".icb", ".vda", ".vst", ".tpic",
            ".ico", ".cur", ".gif", ".png",
            ".jpg", ".jpeg", ".jpe", ".jfif",
            ".tif", ".tiff", ".webp", ".vp8", ".psd", ".dds", ".icns",
        }
        assert t1_expected_keys <= set(ThumbnailManager.NATIVE_IMAGE_FORMATS), (
            "T1 常量表应覆盖 registry FORMAT_SPECS 的全部关键扩展名"
        )
        for ext in ThumbnailManager.NATIVE_IMAGE_FORMATS:
            sample = f"sample{ext}"
            assert matrix_manager.is_image_file(sample) is True, ext
            assert matrix_manager.is_media_file(sample) is True, ext
            assert matrix_manager.is_video_file(sample) is False, ext

    def test_t2_video_extensions_classified_as_video(
        self, matrix_manager: Any
    ) -> None:
        """T2 视频全集：每项均为视频+媒体且非图片，含本次新增的专业容器。"""
        t2_expected_keys = {
            ".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".webm", ".m4v",
            ".mpeg", ".mpg", ".mxf", ".vob", ".m2ts", ".ts", ".mts", ".m2t",
            ".dv", ".prores", ".3gp", ".hevc", ".h264",
        }
        assert t2_expected_keys == set(ThumbnailManager.VIDEO_FORMATS), (
            "T2 视频常量表应与 ffmpeg 桶全集一致"
        )
        for ext in ThumbnailManager.VIDEO_FORMATS:
            sample = f"clip{ext}"
            assert matrix_manager.is_video_file(sample) is True, ext
            assert matrix_manager.is_media_file(sample) is True, ext
            assert matrix_manager.is_image_file(sample) is False, ext

    def test_t2_gated_containers_classified_as_image(
        self, matrix_manager: Any
    ) -> None:
        """T2 门控图像容器（avif/heic/heif/jp2）：归类为图片而非视频。"""
        assert set(ThumbnailManager.GATED_IMAGE_FORMATS) == {
            ".avif", ".heic", ".heif", ".jp2"
        }
        for ext in ThumbnailManager.GATED_IMAGE_FORMATS:
            sample = f"modern{ext}"
            assert matrix_manager.is_image_file(sample) is True, ext
            assert matrix_manager.is_media_file(sample) is True, ext
            assert matrix_manager.is_video_file(sample) is False, ext

    def test_t3_python_extensions_remain_attemptable(
        self, matrix_manager: Any
    ) -> None:
        """T3 全表：Rust 快速 -6 的扩展名在 manager 层仍为'可尝试'媒体。"""
        t3_raw_expected = {".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf",
                           ".raf", ".rw2", ".pef", ".x3f"}
        assert t3_raw_expected == set(ThumbnailManager.RAW_FORMATS), (
            "RAW 表应与 Rust T3_SKIP_EXTS 的 RAW 段对齐（含 raf/rw2/pef/x3f）"
        )
        assert set(ThumbnailManager.PYTHON_ONLY_IMAGE_FORMATS) == {
            ".svg", ".xcf", ".jxr"
        }
        assert set(ThumbnailManager.PSD_FORMATS) == {".psb"}
        for ext in ThumbnailManager.PYTHON_DEDICATED_FORMATS:
            sample = f"pro{ext}"
            assert matrix_manager.is_image_file(sample) is True, ext
            assert matrix_manager.is_media_file(sample) is True, ext
            assert matrix_manager.is_video_file(sample) is False, ext

    def test_non_media_extensions_excluded(self, matrix_manager: Any) -> None:
        """非媒体扩展名三个分类函数一致返回 False（含无扩展名路径）。"""
        for sample in ("notes.txt", "doc.pdf", "archive.zip", "noext"):
            assert matrix_manager.is_image_file(sample) is False, sample
            assert matrix_manager.is_video_file(sample) is False, sample
            assert matrix_manager.is_media_file(sample) is False, sample

    def test_uppercase_extension_equivalence(self, matrix_manager: Any) -> None:
        """大写扩展名与小写等价（分类函数内部小写化归一）。"""
        assert matrix_manager.is_image_file("PHOTO.PNG") is True
        assert matrix_manager.is_image_file("PHOTO.JPEG") is True
        assert matrix_manager.is_video_file("CLIP.TS") is True
        assert matrix_manager.is_media_file("IMG.CR2") is True

    def test_tier_sets_are_disjoint_and_aggregated(self) -> None:
        """桶间不相交（.psd 现单登记为 T1 native；.psb 单登记为 T3 Python），
        且聚合表恰为各桶并集。"""
        video_set: Set[str] = set(ThumbnailManager.VIDEO_FORMATS)
        image_set: Set[str] = set(ThumbnailManager.IMAGE_FORMATS)
        assert not video_set & image_set, "视频桶与图片桶不得相交"

        expected_image: Set[str] = (
            set(ThumbnailManager.NATIVE_IMAGE_FORMATS)
            | set(ThumbnailManager.GATED_IMAGE_FORMATS)
            | set(ThumbnailManager.PYTHON_DEDICATED_FORMATS)
        )
        assert image_set == expected_image


# =============================================================================
# 分桶路由：png → native / ts → 视频 / svg → Python 专用
# =============================================================================
class TestBatchBucketing:
    """``create_thumbnails_batch`` 按三级矩阵分桶（spy 各生成入口验证）。"""

    def test_png_goes_native_ts_goes_video_svg_goes_python(
        self, native_matrix_manager: Any, tmp_path: Any
    ) -> None:
        """三样本同批：断言各自命中目标链路且互不串扰。

        所有生成入口均替换为记录型桩（native 桩返回 -7 以阻断 Python
        重试，保证隔离干净），因此不触发真实子进程/解码。
        """
        png = make_small_png(tmp_path / "bucket.png")
        ts = make_stub_ts(tmp_path / "bucket.ts")
        svg = make_svg(tmp_path / "bucket.svg")

        calls: List[Tuple[str, str]] = []

        def fake_native(file_path: str, thumbnail_path: str,
                        legacy_thumbnail_path: str) -> Tuple[None, int]:
            calls.append(("native", os.path.splitext(file_path)[1]))
            return None, STATUS_TOO_LARGE

        def fake_video(file_path: str, thumbnail_path: str,
                       legacy_thumbnail_path: str,
                       prefer_native: bool = True) -> None:
            calls.append(("video", os.path.splitext(file_path)[1]))
            return None

        def fake_python_image(file_path: str, thumbnail_path: str) -> None:
            calls.append(("python_image", os.path.splitext(file_path)[1]))
            return None

        manager = native_matrix_manager
        with patch.object(manager, "_create_native_thumbnail_with_status",
                          side_effect=fake_native), \
             patch.object(manager, "_create_video_thumbnail_batch_safe",
                          side_effect=fake_video), \
             patch.object(manager, "_create_image_thumbnail",
                          side_effect=fake_python_image):
            success, processed = manager.create_thumbnails_batch([png, ts, svg])

        assert processed == 3
        assert success == 0, "所有生成入口均为桩失败，批量不应计成功"

        assert ("native", ".png") in calls, "png 应进入 native 链路"
        assert ("video", ".ts") in calls, "ts 应进入视频链路"
        assert ("python_image", ".svg") in calls, "svg 应进入 Python 专用链路"

        native_calls = [c for c in calls if c[0] == "native"]
        video_calls = [c for c in calls if c[0] == "video"]
        python_calls = [c for c in calls if c[0] == "python_image"]
        assert native_calls == [("native", ".png")], "仅 png 走 native"
        assert video_calls == [("video", ".ts")], "仅 ts 走视频链"
        assert python_calls == [("python_image", ".svg")], "仅 svg 走 Python 图片链"


# =============================================================================
# 三样本端到端路由：avif → -6 / 坏 BMP → -2 / .txt → 快速失败
# =============================================================================
class TestThreeSampleRouting:
    """三样本各自命中对应回退语义（与 todo 33 状态路由协同）。"""

    def test_avif_unsupported_routes_to_python_bucket(
        self, native_matrix_manager: Any, tmp_path: Any
    ) -> None:
        """avif（T2 门控容器）：原生通道 -6 → 公开路径回落 Python 桶。

        pillow-avif 缺失时经 :func:`make_avif_or_skip` 跳过本用例。
        """
        manager = native_matrix_manager
        avif = make_avif_or_skip(tmp_path / "matrix.avif")
        assert manager.is_image_file(avif) is True, "avif 应归类为图片（T2 门控）"

        thumb_path = manager.get_thumbnail_path(avif)
        legacy_path = manager.get_legacy_thumbnail_path(avif)

        result, status = manager._create_native_thumbnail_with_status(  # noqa: SLF001
            avif, thumb_path, legacy_path
        )
        assert result is None
        assert status == STATUS_UNSUPPORTED

        with patch.object(manager, "_create_image_thumbnail",
                          wraps=manager._create_image_thumbnail) as python_spy:
            manager.create_thumbnail(avif)

        assert python_spy.called is True, "UNSUPPORTED(-6) 应回落 Python 桶"

    def test_corrupt_bmp_decode_failed_routes_to_pil(
        self, native_matrix_manager: Any, tmp_path: Any, caplog: Any
    ) -> None:
        """损坏 BMP（T1 解码失败）：通道状态 -2 → PIL 回退且无 -7 专属告警。"""
        manager = native_matrix_manager
        bmp = make_truncated_bmp(tmp_path / "broken.bmp")

        thumb_path = manager.get_thumbnail_path(bmp)
        legacy_path = manager.get_legacy_thumbnail_path(bmp)

        result, status = manager._create_native_thumbnail_with_status(  # noqa: SLF001
            bmp, thumb_path, legacy_path
        )
        assert result is None
        assert status == STATUS_DECODE_FAILED

        with caplog.at_level(logging.WARNING):
            with patch.object(manager, "_create_image_thumbnail",
                              wraps=manager._create_image_thumbnail) as pil_spy:
                manager.create_thumbnail(bmp)

        assert pil_spy.called is True, "DECODE_FAILED(-2) 应交 PIL 回退"
        assert not any(
            "图像尺寸超限" in rec.getMessage() for rec in caplog.records
        ), "-2 不是确定性超限，不得记录 -7 专属告警"

    def test_fake_txt_extension_fails_fast_without_hanging(
        self, native_matrix_manager: Any, tmp_path: Any
    ) -> None:
        """伪扩展名 .txt（非媒体）：is_media_file 门控快速失败，零链路调用。"""
        manager = native_matrix_manager
        txt_path = tmp_path / "garbage.txt"
        txt_path.write_bytes(b"this is definitely not an image payload")

        assert manager.is_media_file(str(txt_path)) is False

        started = time.perf_counter()
        with patch.object(manager, "_create_native_thumbnail_with_status",
                          wraps=manager._create_native_thumbnail_with_status) as native_spy, \
             patch.object(manager, "_create_image_thumbnail",
                          wraps=manager._create_image_thumbnail) as pil_spy, \
             patch.object(manager, "_create_video_thumbnail_batch_safe",
                          wraps=manager._create_video_thumbnail_batch_safe) as video_spy:
            result = manager.create_thumbnail(str(txt_path))
        elapsed = time.perf_counter() - started

        assert result is None
        assert elapsed < 5.0, f"非媒体文件应快速失败而非挂起（耗时 {elapsed:.2f}s）"
        assert native_spy.called is False, "非媒体不应进入原生链路"
        assert pil_spy.called is False, "非媒体不应进入 PIL 回退"
        assert video_spy.called is False, "非媒体不应进入视频链路"
