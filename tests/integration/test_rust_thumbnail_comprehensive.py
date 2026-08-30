# -*- coding: utf-8 -*-
"""Rust 缩略图引擎综合功能验证（图像精度 + 视频功能）集成测试。

覆盖 ``freeassetfilter.core.native.bridges.rust_thumbnail_bridge`` 的
真实解码回路（DLL 直调，桥内无 Python 回退）：

* **图像多分辨率精度**（``TestImageMultiResolution``）：16x16 / 256x256 /
  1920x1080 / 3840x2160 渐变+几何图形 PNG 各请求 64x64——返回非 None、
  尺寸不超框、保比例（≤1 像素）、16x16 不放大、缓冲长度自洽；像素级
  与 PIL ``BOX`` 重采样参照比对（引擎 ``box_resize_rgba`` 为面积平均
  box filter，实测最大偏差 1，LANCZOS/BILINEAR 参照不可比）；
* **JPEG 输出路径**（``TestJpegOutputPath``）：``generate_jpg`` 多分辨率
  输出合法 JPEG（\\xff\\xd8 魔数、PIL 可解码、尺寸 ≤ 请求框）；
  ``generate_jpg_batch`` ≥4 张混合路径批量全部有效；
* **T3 门控格式**（``TestT3GatedFormats``）：假 .cr2 / .svg 命中 T3 跳过
  清单返回 ``STATUS_UNSUPPORTED(-6)``，且跳过记录经 ``get_error_log()``
  补录（JSON 数组含对应 path/format/status）；
* **视频缩略图**（``TestVideoThumbnails``，全部 ``timeout(180)``）：系统
  完整版 ffmpeg（PATH 探测）+ lavfi testsrc 现场生成 mp4(h264)×6 /
  webm(vp9) / avi(mpeg4) / mkv(h264) 夹具——RGBA 形状断言、JPEG 路径、
  跨容器成功率、解码统计前后快照递增（实测本机路由 d3d11va 硬件路径，
  ``software_*`` 计数不递增，故断言四类 attempts 总和递增——对照引擎
  ``record_attempt`` 按 mode 分桶的实现行为）。
* **性能预期指标实测**（``TestPerformance*`` 六个类，文件末尾追加节）：
  spec 硬目标逐项实测——冷启动首请求（subprocess 全新进程）/ 单张热
  路径 p50/p95（RGBA 与 JPEG 分测）/ 缓存命中 p95 / 32 路突发并发加速
  比 / 32 线程并发单张 p95 / 视频抽帧 p50 与 4 路并发视频全成功；实测
  数据 print 摘要 + JSON 落 ``tmp_path``，断言失败信息带实测值与目标值。

资源纪律：图像/视频夹具全部落 ``tmp_path_factory``（module 级一次生成
共享）；视频夹具由**系统完整版** ffmpeg 生成（项目自带 minimal build 无
libx264/libvpx 编码器），Rust 引擎解码时仍用项目自带 minimal ffmpeg
（含 h264/vp9/mpeg4 解码器与 mp4/webm/avi/mkv demuxer，已探测确认）。
"""

from __future__ import annotations

import io
import json
import logging
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import pytest
from PIL import Image, ImageDraw

from freeassetfilter.core.native.bridges.rust_thumbnail_bridge import (
    STATUS_OK,
    STATUS_UNSUPPORTED,
    RustThumbnailBridge,
)


pytestmark = [pytest.mark.integration, pytest.mark.rust]


bridge = pytest.importorskip(
    "freeassetfilter.core.native.bridges.rust_thumbnail_bridge"
)

# 系统 PATH 中的完整版 ffmpeg（生成视频夹具用；模块级探测一次）
_SYSTEM_FFMPEG: Optional[str] = shutil.which("ffmpeg")

# 多分辨率精度验证的源图尺寸集合（含不放大边界与 4K 超采样场景）
_PNG_SIZES: Tuple[Tuple[int, int], ...] = (
    (16, 16),
    (256, 256),
    (1920, 1080),
    (3840, 2160),
)

# mp4(h264) 夹具规格：(语义名, 宽, 高, 时长秒)
_MP4_SPECS: Tuple[Tuple[str, int, int, int], ...] = (
    ("mp4_320x240_1s", 320, 240, 1),
    ("mp4_320x240_5s", 320, 240, 5),
    ("mp4_1280x720_1s", 1280, 720, 1),
    ("mp4_1280x720_5s", 1280, 720, 5),
    ("mp4_1920x1080_1s", 1920, 1080, 1),
    ("mp4_1920x1080_5s", 1920, 1080, 5),
)

# 解码统计中「尝试」类计数的键（record_attempt 按 mode 分桶的实现口径）
_ATTEMPT_KEYS: Tuple[str, ...] = (
    "d3d11va_attempts",
    "dxva2_attempts",
    "qsv_attempts",
    "software_attempts",
)


# =============================================================================
# 数据工厂
# =============================================================================
def _make_gradient_png(path: Path, width: int, height: int) -> None:
    """生成二维渐变色 + 几何图形 PNG（非纯色，便于像素级比对）。

    Args:
        path: 目标文件路径。
        width: 图像宽度（像素）。
        height: 图像高度（像素）。
    """
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)
    x_step = max(1, width // 64)
    for y in range(height):
        for x in range(0, width, x_step):
            r = (x * 255) // max(1, width - 1)
            g = (y * 255) // max(1, height - 1)
            b = ((x + y) * 255) // max(1, width + height - 2)
            draw.rectangle(
                [x, y, min(x + x_step, width) - 1, y], fill=(r, g, b)
            )
    # 叠加几何图形制造高频边缘（椭圆 + 竖条），避免纯渐变的过度平滑
    draw.ellipse(
        [width // 4, height // 4, 3 * width // 4, 3 * height // 4],
        fill=(255, 0, 0),
    )
    draw.rectangle(
        [width // 8, height // 8,
         width // 8 + max(1, width // 16), height - height // 8],
        fill=(0, 255, 0),
    )
    img.save(str(path), format="PNG")


def _max_abs_diff(image_a: Image.Image, image_b: Image.Image) -> int:
    """计算两幅同尺寸图像逐像素逐通道的最大绝对差。

    Args:
        image_a: 参照图像 A。
        image_b: 参照图像 B（尺寸须与 A 一致）。

    Returns:
        int: 全部像素全部通道的最大绝对差。
    """
    bytes_a = image_a.tobytes()
    bytes_b = image_b.tobytes()
    return max(abs(a - b) for a, b in zip(bytes_a, bytes_b))


def _run_ffmpeg(out_path: Path, extra_args: List[str]) -> None:
    """以系统完整版 ffmpeg 生成单个视频夹具（失败给出清晰错误）。

    Args:
        out_path: 输出视频路径。
        extra_args: 编码参数（-c:v 等，置于输入之后）。

    Raises:
        AssertionError: ffmpeg 进程非零退出或超时（120s）。
    """
    assert _SYSTEM_FFMPEG is not None, "系统 ffmpeg 未探测到"
    cmd: List[str] = [
        _SYSTEM_FFMPEG, "-y", "-loglevel", "error",
        *extra_args,
        str(out_path),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120
        )
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(f"ffmpeg 生成 {out_path.name} 超时(120s)") from exc
    assert proc.returncode == 0, (
        f"ffmpeg 生成 {out_path.name} 失败 rc={proc.returncode} "
        f"stderr={proc.stderr[:500]}"
    )
    assert out_path.exists() and out_path.stat().st_size > 0, (
        f"ffmpeg 未产出有效文件: {out_path}"
    )


# =============================================================================
# fixtures
# =============================================================================
@pytest.fixture()
def rust_bridge() -> Any:
    """提供可用性门控的 RustThumbnailBridge 实例（镜像既有测试写法）。"""
    inst = RustThumbnailBridge()
    if not inst.available:
        pytest.skip("thumbnail_generator.dll 不可用，跳过综合集成测试")
    return inst


@pytest.fixture(scope="module")
def gradient_pngs(tmp_path_factory: Any) -> Dict[Tuple[int, int], str]:
    """module 级一次生成 4 个分辨率的渐变 PNG，返回 {(w, h): path}。"""
    base: Path = tmp_path_factory.mktemp("gradient_pngs")
    result: Dict[Tuple[int, int], str] = {}
    for w, h in _PNG_SIZES:
        p = base / f"gradient_{w}x{h}.png"
        _make_gradient_png(p, w, h)
        result[(w, h)] = str(p)
    return result


@pytest.fixture(scope="module")
def video_fixtures(tmp_path_factory: Any) -> Dict[str, str]:
    """module 级一次生成全部视频夹具，返回 {语义名: 绝对路径}。

    mp4(h264)×6 覆盖 320x240/1280x720/1920x1080 × 1s/5s；另生成
    webm(vp9) / avi(mpeg4) / mkv(h264) 各一个（320x240/1s）。
    编码器用系统完整版 ffmpeg（项目自带 minimal build 无 libx264/libvpx）。
    """
    base: Path = tmp_path_factory.mktemp("video_fixtures")
    result: Dict[str, str] = {}

    for name, w, h, duration in _MP4_SPECS:
        out = base / f"{name}.mp4"
        _run_ffmpeg(out, [
            "-f", "lavfi",
            "-i", f"testsrc=duration={duration}:size={w}x{h}:rate=10",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        ])
        result[name] = str(out)

    webm = base / "webm_320x240_1s.webm"
    _run_ffmpeg(webm, [
        "-f", "lavfi",
        "-i", "testsrc=duration=1:size=320x240:rate=10",
        "-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8",
    ])
    result["webm_320x240_1s"] = str(webm)

    avi = base / "avi_320x240_1s.avi"
    _run_ffmpeg(avi, [
        "-f", "lavfi",
        "-i", "testsrc=duration=1:size=320x240:rate=10",
        "-c:v", "mpeg4",
    ])
    result["avi_320x240_1s"] = str(avi)

    mkv = base / "mkv_320x240_1s.mkv"
    _run_ffmpeg(mkv, [
        "-f", "lavfi",
        "-i", "testsrc=duration=1:size=320x240:rate=10",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
    ])
    result["mkv_320x240_1s"] = str(mkv)

    return result


# =============================================================================
# 1. 图像多分辨率精度验证
# =============================================================================
class TestImageMultiResolution:
    """渐变 PNG 经引擎 RGBA 路径的尺寸/比例/缓冲/像素精度契约。"""

    @pytest.mark.parametrize("size", _PNG_SIZES)
    def test_rgba_dimensions_aspect_and_buffer(
        self, rust_bridge: Any, gradient_pngs: Dict[Tuple[int, int], str],
        size: Tuple[int, int],
    ) -> None:
        """各分辨率：非 None、尺寸 ≤64、保比例 ≤1px、len==w*h*4。"""
        src_w, src_h = size
        path = gradient_pngs[size]
        generated, status = rust_bridge.generate_rgba_with_status(path, 64, 64)
        assert status == STATUS_OK, f"{size} 桥状态码 {status}"
        assert generated is not None, f"{size} 未产出 RGBA"
        raw, out_w, out_h, channels = generated  # type: ignore[misc]

        assert 0 < out_w <= 64 and 0 < out_h <= 64, \
            f"{size} 输出 {out_w}x{out_h} 越界（T1 不放大）"
        assert channels == 4, f"{size} 通道数 {channels}"
        assert len(raw) == out_w * out_h * channels, \
            f"{size} 缓冲长度不自洽: {len(raw)} != {out_w * out_h * channels}"

        # 保比例：按输出宽度折算的预期高度与实际高度差 ≤1 像素
        expected_h = src_h * out_w / src_w
        assert abs(out_h - expected_h) <= 1.0, (
            f"{size} 宽高比失守: out={out_w}x{out_h} "
            f"期望高度≈{expected_h:.2f}"
        )

    def test_small_input_not_upscaled(
        self, rust_bridge: Any, gradient_pngs: Dict[Tuple[int, int], str],
    ) -> None:
        """16x16 输入请求 64x64 不被放大：输出恰为 16x16。"""
        path = gradient_pngs[(16, 16)]
        generated, status = rust_bridge.generate_rgba_with_status(path, 64, 64)
        assert status == STATUS_OK and generated is not None
        raw, out_w, out_h, _channels = generated  # type: ignore[misc]
        assert (out_w, out_h) == (16, 16), \
            f"16x16 输入被放大为 {out_w}x{out_h}"

    @pytest.mark.parametrize("size", _PNG_SIZES)
    def test_pixel_accuracy_against_pil_box(
        self, rust_bridge: Any, gradient_pngs: Dict[Tuple[int, int], str],
        size: Tuple[int, int],
    ) -> None:
        """像素精度：引擎输出 vs PIL BOX 等比缩放，最大绝对差 ≤3。

        引擎缩放为 ``box_resize_rgba``（面积平均 box filter），故参照算法
        必须用 PIL ``Image.BOX``（LANCZOS/BILINEAR 与 box filter 语义
        不同，实测差值 18~52 不可比）。16x16 输入无缩放，与原图逐像素
        一致（差 0）。
        """
        path = gradient_pngs[size]
        generated, status = rust_bridge.generate_rgba_with_status(path, 64, 64)
        assert status == STATUS_OK and generated is not None
        raw, out_w, out_h, _channels = generated  # type: ignore[misc]

        got = Image.frombytes("RGBA", (out_w, out_h), bytes(raw))
        reference = Image.open(path).convert("RGBA").resize(
            (out_w, out_h), Image.BOX
        )

        # alpha 通道全 255（RGB 源图不携带透明度）
        alpha_band = got.getchannel("A")
        alpha_min, _alpha_max = alpha_band.getextrema()
        assert alpha_min == 255, f"{size} alpha 存在非 255 值: min={alpha_min}"

        diff = _max_abs_diff(got, reference)
        print(f"[pixel-accuracy] {size} -> {out_w}x{out_h} max_abs_diff={diff}")
        assert diff <= 3, (
            f"{size} 像素最大绝对差 {diff} 超阈值 3"
        )


# =============================================================================
# 2. JPEG 输出路径验证
# =============================================================================
class TestJpegOutputPath:
    """``generate_jpg`` 单张与 ``generate_jpg_batch`` 批量的 JPEG 契约。"""

    @pytest.mark.parametrize("size", _PNG_SIZES)
    def test_generate_jpg_multi_resolution(
        self, rust_bridge: Any, gradient_pngs: Dict[Tuple[int, int], str],
        size: Tuple[int, int],
    ) -> None:
        """多分辨率 PNG 各生成 JPEG：\\xff\\xd8 开头、可解码、尺寸 ≤ 请求框。"""
        if not rust_bridge._supports_jpg:  # noqa: SLF001
            pytest.skip("DLL 未导出 native_generate_thumbnail_jpg")
        path = gradient_pngs[size]
        data, status = rust_bridge.generate_jpg_with_status(path, 64, 64)
        assert status == STATUS_OK, f"{size} JPG 状态码 {status}"
        assert isinstance(data, bytes) and len(data) > 0, f"{size} 无 JPG 字节"

        assert data[:2] == b"\xff\xd8", \
            f"{size} JPEG 魔数缺失: {data[:2].hex()}"
        decoded = Image.open(io.BytesIO(data))
        decoded.load()
        assert decoded.size[0] <= 64 and decoded.size[1] <= 64, \
            f"{size} JPEG 解码尺寸 {decoded.size} 超请求框 64x64"

    def test_generate_jpg_batch_mixed_paths(
        self, rust_bridge: Any, gradient_pngs: Dict[Tuple[int, int], str],
    ) -> None:
        """≥4 张混合分辨率路径批量：每项均为有效 JPEG。"""
        if not rust_bridge._supports_batch_jpg:  # noqa: SLF001
            pytest.skip("DLL 未导出 native_generate_batch_jpg")
        paths: List[str] = [gradient_pngs[size] for size in _PNG_SIZES]
        results = rust_bridge.generate_jpg_batch(paths, 64, 64)

        assert isinstance(results, list) and len(results) == len(paths)
        for i, item in enumerate(results):
            assert isinstance(item, bytes) and len(item) > 0, \
                f"批量第 {i} 项（{_PNG_SIZES[i]}）非有效字节"
            assert item[:2] == b"\xff\xd8", \
                f"批量第 {i} 项 JPEG 魔数缺失"
            decoded = Image.open(io.BytesIO(item))
            decoded.load()
            assert decoded.size[0] <= 64 and decoded.size[1] <= 64, \
                f"批量第 {i} 项解码尺寸 {decoded.size} 超框"


# =============================================================================
# 3. T3 门控格式验证
# =============================================================================
class TestT3GatedFormats:
    """T3 跳过清单（RAW 系 + psb/xcf/svg/jxr）的门控与 errorlog 补录。"""

    def test_cr2_and_svg_return_unsupported(
        self, rust_bridge: Any, tmp_path: Any,
    ) -> None:
        """假 .cr2 / .svg 均被门控：``generate_rgba_with_status`` 返回 -6。"""
        cr2 = tmp_path / "fake_sample.cr2"
        cr2.write_bytes(b"\x00\x01\x02 not a real cr2 payload")
        svg = tmp_path / "fake_sample.svg"
        svg.write_text("<svg xmlns='test'>not a real svg</svg>", encoding="utf-8")

        for path in (str(cr2), str(svg)):
            generated, status = rust_bridge.generate_rgba_with_status(
                path, 64, 64
            )
            assert generated is None, f"{path} 不应产出 RGBA"
            assert status == STATUS_UNSUPPORTED, \
                f"{path} 应被 T3 门控 -6，实测 status={status}"

    def test_skip_entries_recorded_in_error_log(
        self, rust_bridge: Any, tmp_path: Any,
    ) -> None:
        """跳过记录经 ``get_error_log()`` 补录：JSON 数组含对应路径。"""
        cr2 = tmp_path / "logged_sample.cr2"
        cr2.write_bytes(b"fake cr2 for errorlog")
        svg = tmp_path / "logged_sample.svg"
        svg.write_text("<svg>fake svg for errorlog</svg>", encoding="utf-8")

        assert rust_bridge.clear_error_log() is True
        for path in (str(cr2), str(svg)):
            rust_bridge.generate_rgba_with_status(path, 64, 64)

        entries = json.loads(rust_bridge.get_error_log())
        assert isinstance(entries, list), "errorlog 应为 JSON 数组"
        logged_paths = {str(entry.get("path", "")) for entry in entries}
        for path in (str(cr2), str(svg)):
            assert path in logged_paths, \
                f"{path} 未出现在 errorlog 补录中，实际条目数 {len(entries)}"
        # 每条补录均含 path/format/status 结构化字段
        for entry in entries:
            if entry.get("path") in (str(cr2), str(svg)):
                assert {"path", "format", "status"}.issubset(entry.keys())
                assert entry["status"] == STATUS_UNSUPPORTED


# =============================================================================
# 4. 视频缩略图验证（全部 timeout(180)）
# =============================================================================
@pytest.mark.skipif(
    _SYSTEM_FFMPEG is None,
    reason="系统 PATH 无完整版 ffmpeg，无法生成视频夹具",
)
@pytest.mark.timeout(180)
class TestVideoThumbnails:
    """视频经引擎 T2 ffmpeg 解码路径的 RGBA/JPEG/统计契约。

    视频抽帧单次可能 1-20s，整类 ``timeout(180)``（覆盖 module 级夹具
    生成时间 + 单测试多次抽帧）。夹具由系统完整版 ffmpeg 生成，引擎解码
    用项目自带 minimal ffmpeg（已探测含 h264/vp9/mpeg4 解码器）。
    """

    @pytest.mark.parametrize("name", [spec[0] for spec in _MP4_SPECS])
    def test_mp4_rgba_generation(
        self, rust_bridge: Any, video_fixtures: Dict[str, str], name: str,
    ) -> None:
        """每个 mp4 夹具请求 128x128：非 None、不超框、len==w*h*4。"""
        path = video_fixtures[name]
        generated, status = rust_bridge.generate_rgba_with_status(
            path, 128, 128
        )
        assert status == STATUS_OK, f"{name} 桥状态码 {status}"
        assert generated is not None, f"{name} 未产出 RGBA"
        raw, out_w, out_h, channels = generated  # type: ignore[misc]
        assert 0 < out_w <= 128 and 0 < out_h <= 128, \
            f"{name} 输出 {out_w}x{out_h} 越界"
        assert channels == 4, f"{name} 通道数 {channels}"
        assert len(raw) == out_w * out_h * channels, \
            f"{name} 缓冲长度不自洽"

    def test_mp4_jpeg_generation(
        self, rust_bridge: Any, video_fixtures: Dict[str, str],
    ) -> None:
        """JPEG 路径：至少 2 个 mp4 夹具产出合法 JPEG（魔数 + 可解码）。"""
        if not rust_bridge._supports_jpg:  # noqa: SLF001
            pytest.skip("DLL 未导出 native_generate_thumbnail_jpg")
        targets = [
            video_fixtures["mp4_320x240_1s"],
            video_fixtures["mp4_1920x1080_1s"],
        ]
        for path in targets:
            data, status = rust_bridge.generate_jpg_with_status(path, 128, 128)
            assert status == STATUS_OK, f"{path} JPG 状态码 {status}"
            assert isinstance(data, bytes) and len(data) > 0
            assert data[:2] == b"\xff\xd8", "视频 JPEG 魔数缺失"
            decoded = Image.open(io.BytesIO(data))
            decoded.load()
            assert decoded.size[0] <= 128 and decoded.size[1] <= 128, \
                f"视频 JPEG 解码尺寸 {decoded.size} 超请求框"

    def test_other_containers_at_least_one_succeeds(
        self, rust_bridge: Any, video_fixtures: Dict[str, str],
    ) -> None:
        """webm/avi/mkv 容器：generate_rgba 至少一个成功，逐容器记录 status。"""
        containers: Dict[str, str] = {
            "webm": video_fixtures["webm_320x240_1s"],
            "avi": video_fixtures["avi_320x240_1s"],
            "mkv": video_fixtures["mkv_320x240_1s"],
        }
        outcomes: Dict[str, int] = {}
        success_count = 0
        for cname, path in containers.items():
            generated, status = rust_bridge.generate_rgba_with_status(
                path, 128, 128
            )
            outcomes[cname] = status
            if generated is not None:
                success_count += 1
                raw, out_w, out_h, channels = generated  # type: ignore[misc]
                assert 0 < out_w <= 128 and 0 < out_h <= 128
                assert len(raw) == out_w * out_h * channels

        print(f"[containers] outcomes={outcomes} success={success_count}/3")
        assert success_count >= 1, \
            f"webm/avi/mkv 全部失败: {outcomes}（引擎限制或 bug 待查）"

    def test_decode_stats_increment(
        self, rust_bridge: Any, video_fixtures: Dict[str, str],
    ) -> None:
        """解码统计：视频生成后 attempts 类计数递增（前后快照比对）。

        引擎 ``record_attempt`` 按 mode 分桶（d3d11va/dxva2/qsv/software）；
        实测本机路由 d3d11va 硬件路径（``software_*`` 不动），故断言四类
        attempts 之和递增且 ≥ 执行次数——对照实现行为而非仅 software 计数。

        注意：同文件 + 同请求尺寸的重复调用会命中引擎内部像素缓存，
        缓存命中不走解码路径、计数不递增（实测 before==after），故先
        ``clear_cache()`` 强制后续两次生成走真实解码。
        """
        assert rust_bridge.clear_cache() is True
        before: Dict[str, int] = rust_bridge.get_decode_stats()
        assert isinstance(before, dict) and before, "解码统计不可为空"

        executed = 0
        for key in ("mp4_320x240_1s", "mp4_1280x720_1s"):
            generated, status = rust_bridge.generate_rgba_with_status(
                video_fixtures[key], 128, 128
            )
            assert status == STATUS_OK and generated is not None, \
                f"{key} 视频生成失败 status={status}"
            executed += 1

        after: Dict[str, int] = rust_bridge.get_decode_stats()
        print(f"[decode-stats] before={before}")
        print(f"[decode-stats] after={after}")

        def total_attempts(snapshot: Dict[str, int]) -> int:
            return sum(snapshot.get(k, 0) for k in _ATTEMPT_KEYS)

        assert total_attempts(after) >= total_attempts(before) + executed, (
            f"attempts 总和未按执行次数递增: "
            f"before={total_attempts(before)} after={total_attempts(after)} "
            f"executed={executed} detail_before={before} detail_after={after}"
        )


# =============================================================================
# 5. 性能预期指标实测（spec 硬目标，文件末尾追加节）
# =============================================================================
# 性能夹具：1080p JPEG 尺寸（冷启动/热路径/缓存命中/并发单张共用）
_PERF_JPEG_SIZE: Tuple[int, int] = (1920, 1080)

# 突发并发的 8 张混合分辨率（256x256 ~ 3840x2160）
_BURST_SIZES: Tuple[Tuple[int, int], ...] = (
    (256, 256),
    (640, 360),
    (1024, 768),
    (1280, 720),
    (1920, 1080),
    (2560, 1440),
    (3200, 1800),
    (3840, 2160),
)

# 性能采样参数
_COLD_START_RUNS: int = 3          # 冷启动全新进程次数（取中位数）
_HOT_PATH_ROUNDS: int = 60         # 热路径逐次计时次数
_CACHE_HIT_ROUNDS: int = 40        # 缓存命中采样次数
_BURST_CONCURRENCY: int = 32       # 突发并发线程数
_BURST_BATCH_COUNT: int = 32       # 突发并发批数（每批 8 张）
_CONCURRENT_IMAGE_WORKERS: int = 32  # 并发单张线程数
_VIDEO_EXTRACT_ROUNDS: int = 8     # 视频抽帧循环次数
_CONCURRENT_VIDEO_PATHS: int = 4   # 并发视频路数

# 冷启动子进程内联脚本：分段计时（import 链 / DLL 加载 / 首次调用），
# 经 stdout 的 KEY=VALUE 行回传主进程解析；夹具路径经 sys.argv[1] 传入
_COLD_START_CODE: str = r"""
import sys
import time

t0 = time.perf_counter()
from freeassetfilter.core.native.bridges.rust_thumbnail_bridge import (
    RustThumbnailBridge,
)
t1 = time.perf_counter()
bridge = RustThumbnailBridge()
t2 = time.perf_counter()
result = bridge.generate_rgba(sys.argv[1], 64, 64)
t3 = time.perf_counter()
print("STAGE_IMPORT_MS=%.2f" % ((t1 - t0) * 1000.0))
print("STAGE_CTOR_MS=%.2f" % ((t2 - t1) * 1000.0))
print("STAGE_FIRST_MS=%.2f" % ((t3 - t2) * 1000.0))
print("COLD_TOTAL_MS=%.2f" % ((t3 - t0) * 1000.0))
print("COLD_OK=%d" % (1 if result is not None else 0))
"""


def _make_gradient_jpeg(path: Path, width: int, height: int) -> None:
    """生成二维渐变 + 几何图形 JPEG（性能夹具：文件小、复制开销低）。

    复用 ``_make_gradient_png`` 的渐变+椭圆+竖条图案后转存 JPEG
    （quality=88），与既有功能夹具同源，解码路径口径可比。

    Args:
        path: 目标文件路径（.jpg）。
        width: 图像宽度（像素）。
        height: 图像高度（像素）。
    """
    tmp_png = path.with_suffix(".src.png")
    _make_gradient_png(tmp_png, width, height)
    with Image.open(tmp_png) as img:
        img.save(str(path), format="JPEG", quality=88)
    tmp_png.unlink()


def _pct(samples: List[float], q: float) -> float:
    """分位数（sorted + index 保守取法：``idx = int(n*q)`` 钳制到末位）。

    Args:
        samples: 毫秒样本列表（非空）。
        q: 分位比例（0.50 即 p50，0.95 即 p95）。

    Returns:
        float: 对应分位数的样本值（ms）。
    """
    ordered = sorted(samples)
    idx = min(int(len(ordered) * q), len(ordered) - 1)
    return ordered[idx]


def _fmt_stats(samples: List[float]) -> str:
    """格式化一批毫秒样本的 p50/p95/min/max/n 摘要字符串。

    Args:
        samples: 毫秒样本列表（非空）。

    Returns:
        str: 形如 ``p50=12.30ms p95=15.70ms min=... max=... n=60``。
    """
    return (
        f"p50={_pct(samples, 0.50):.2f}ms "
        f"p95={_pct(samples, 0.95):.2f}ms "
        f"min={min(samples):.2f}ms "
        f"max={max(samples):.2f}ms "
        f"n={len(samples)}"
    )


def _dump_perf_json(tmp_dir: Any, name: str, payload: Dict[str, Any]) -> None:
    """性能数据写 JSON 落盘并打印路径（报告回贴与事后分析用）。

    Args:
        tmp_dir: 测试级 ``tmp_path`` 目录。
        name: 指标短名（文件名成分）。
        payload: 序列化数据（含原始样本与统计量）。
    """
    out = Path(tmp_dir) / f"perf_{name}.json"
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[perf-json] {name} -> {out}")


def _parse_cold_start_output(stdout: str) -> Dict[str, float]:
    """解析冷启动子进程的 KEY=VALUE 分段计时输出。

    Args:
        stdout: 子进程标准输出全文。

    Returns:
        Dict[str, float]: 含 ``import`` / ``ctor`` / ``first`` / ``total`` /
        ``cold_ok`` 五键的映射。

    Raises:
        AssertionError: 输出缺必需字段（附 stdout 尾部 300 字符助诊断）。
    """
    tags: Dict[str, str] = {
        "import": "STAGE_IMPORT_MS=",
        "ctor": "STAGE_CTOR_MS=",
        "first": "STAGE_FIRST_MS=",
        "total": "COLD_TOTAL_MS=",
        "cold_ok": "COLD_OK=",
    }
    fields: Dict[str, float] = {}
    for line in stdout.splitlines():
        stripped = line.strip()
        for key, tag in tags.items():
            if stripped.startswith(tag):
                fields[key] = float(stripped[len(tag):])
    missing = [k for k in tags if k not in fields]
    assert not missing, (
        f"冷启动子进程输出缺字段 {missing}，stdout 尾部: {stdout[-300:]!r}"
    )
    return fields


@pytest.fixture()
def perf_quiet_logs() -> Iterator[None]:
    """性能测量期抑制 ``FreeAssetFilter`` logger 的 DEBUG/INFO 输出。

    测量环境净化而非引擎改动：``-s`` 直通终端时 AppLogger 的 DEBUG 行
    逐条打印（实测每条 ~12ms 终端开销），远大于缓存命中 5ms 量级的
    被测时间，构成观察者效应污染；生产 GUI 无此直通路径。测试后恢复
    原级别。
    """
    logger = logging.getLogger("FreeAssetFilter")
    old_level = logger.level
    logger.setLevel(logging.WARNING)
    try:
        yield
    finally:
        logger.setLevel(old_level)


# -----------------------------------------------------------------------------
# 性能夹具（module 级一次生成共享）
# -----------------------------------------------------------------------------
@pytest.fixture(scope="module")
def perf_jpeg_1080p(tmp_path_factory: Any) -> str:
    """module 级一次生成 1080p 渐变 JPEG（冷启动/热路径/缓存命中共用）。"""
    base: Path = tmp_path_factory.mktemp("perf_jpeg")
    target = base / "perf_1920x1080.jpg"
    _make_gradient_jpeg(target, *_PERF_JPEG_SIZE)
    return str(target)


@pytest.fixture(scope="module")
def perf_jpeg_1080p_copies32(
    tmp_path_factory: Any, perf_jpeg_1080p: str
) -> List[str]:
    """1080p JPEG 的 32 个互异路径副本（并发单张 p95 用，避免缓存串扰）。"""
    base: Path = tmp_path_factory.mktemp("perf_jpeg_copies")
    paths: List[str] = []
    for i in range(_CONCURRENT_IMAGE_WORKERS):
        dst = base / f"copy_{i:02d}.jpg"
        shutil.copyfile(perf_jpeg_1080p, dst)
        paths.append(str(dst))
    return paths


@pytest.fixture(scope="module")
def perf_burst_batches(tmp_path_factory: Any) -> List[List[str]]:
    """32 批 × 8 张混合分辨率 JPEG（共 256 个互异路径，突发并发用）。

    8 张源图（256x256 ~ 3840x2160）各生成一次后复制 32 份——引擎像素
    缓存以路径为键，互异路径确保串行基线与并发两侧均无缓存命中干扰，
    加速比口径才成立（同路径重复调用会命中缓存使基线失真）。
    """
    base: Path = tmp_path_factory.mktemp("perf_burst")
    src_dir = base / "src"
    src_dir.mkdir()
    sources: Dict[Tuple[int, int], str] = {}
    for w, h in _BURST_SIZES:
        src = src_dir / f"burst_{w}x{h}.jpg"
        _make_gradient_jpeg(src, w, h)
        sources[(w, h)] = str(src)

    batch_dir = base / "batches"
    batch_dir.mkdir()
    batches: List[List[str]] = []
    for i in range(_BURST_BATCH_COUNT):
        batch: List[str] = []
        for w, h in _BURST_SIZES:
            dst = batch_dir / f"b{i:02d}_{w}x{h}.jpg"
            shutil.copyfile(sources[(w, h)], dst)
            batch.append(str(dst))
        batches.append(batch)
    return batches


# -----------------------------------------------------------------------------
# 5.1 冷启动首请求
# -----------------------------------------------------------------------------
@pytest.mark.benchmark
@pytest.mark.slow
@pytest.mark.timeout(300)
class TestPerformanceColdStart:
    """冷启动首请求：全新 Python 进程 import + 加载 DLL + 首次调用 ≤ 500ms。

    pytest 主进程内 DLL 已加载，测不了冷启动——必须 subprocess 启动全新
    进程测量；3 次全新进程取中位数（每次含进程内 import 链 + DLL 加载
    + 首次 generate_rgba，OS 文件缓存命中为接受口径）。

    引擎懒初始化优化后实测中位 ~256ms（3 次 256~260ms）：import 链
    ~222ms + DLL 加载 ~22ms + 引擎首调 ~13ms（原 ``System::new_all()``
    全系统扫描 ~440ms 已改为 ``System::new()`` 空构造 + 首调按需
    ``refresh_memory``，见 ``lib.rs`` NativeEngine::new 注释）。
    """

    def test_cold_start_first_request_le_500ms(
        self, rust_bridge: Any, perf_jpeg_1080p: str, tmp_path: Any
    ) -> None:
        """3 次全新子进程分段计时，总耗时中位数 ≤ 500ms。"""
        project_root = Path(__file__).resolve().parents[2]
        runs: List[Dict[str, float]] = []
        for i in range(_COLD_START_RUNS):
            proc = subprocess.run(
                [sys.executable, "-X", "utf8", "-c", _COLD_START_CODE,
                 perf_jpeg_1080p],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(project_root),
            )
            assert proc.returncode == 0, (
                f"冷启动子进程运行失败 rc={proc.returncode} "
                f"stderr尾部={proc.stderr[-500:]}"
            )
            fields = _parse_cold_start_output(proc.stdout)
            assert fields["cold_ok"] == 1, "冷启动子进程首次 generate_rgba 失败"
            runs.append(fields)
            print(
                f"[cold-start] run#{i + 1} total={fields['total']:.1f}ms "
                f"(import={fields['import']:.1f}ms "
                f"ctor={fields['ctor']:.1f}ms "
                f"first={fields['first']:.1f}ms)"
            )

        totals = [r["total"] for r in runs]
        median = sorted(totals)[len(totals) // 2]
        _dump_perf_json(tmp_path, "cold_start", {
            "runs": runs,
            "median_ms": median,
            "target_ms": 500.0,
        })
        assert median <= 500.0, (
            f"实测中位 {median:.1f}ms > 目标 500ms（3 次: "
            f"{', '.join(f'{t:.1f}' for t in totals)}）"
        )


# -----------------------------------------------------------------------------
# 5.2 单张图像热路径
# -----------------------------------------------------------------------------
@pytest.mark.benchmark
@pytest.mark.slow
@pytest.mark.timeout(300)
class TestPerformanceHotPath:
    """单张 1080p JPEG → 64x64 热路径：RGBA 与 JPEG 各 p50 ≤ 30ms、p95 ≤ 80ms。

    热路径口径：引擎预热（5 次丢弃）、每次测量前 ``clear_cache()``
    强制真实解码（缓存命中是另一独立指标）。
    """

    def _run_hot_path(
        self,
        bridge: Any,
        path: str,
        call: Any,
        label: str,
        tmp_path: Any,
    ) -> Tuple[float, float]:
        """热路径采样公共实现：预热 5 次丢弃后逐次计时 60 次。

        Args:
            bridge: RustThumbnailBridge 实例。
            path: 1080p JPEG 路径。
            call: 待计时调用（``generate_rgba`` 或 ``generate_jpg``）。
            label: 指标短名（print 与 JSON 文件名成分）。
            tmp_path: 测试级临时目录。

        Returns:
            Tuple[float, float]: (p50_ms, p95_ms)。
        """
        for _ in range(5):  # 预热丢弃：触发引擎懒初始化与页缓存
            call(path, 64, 64)
        samples: List[float] = []
        for _ in range(_HOT_PATH_ROUNDS):
            assert bridge.clear_cache() is True
            t0 = time.perf_counter()
            result = call(path, 64, 64)
            t1 = time.perf_counter()
            assert result is not None, f"[{label}] generate 返回 None"
            samples.append((t1 - t0) * 1000.0)

        p50 = _pct(samples, 0.50)
        p95 = _pct(samples, 0.95)
        print(f"[{label}] {_fmt_stats(samples)}")
        _dump_perf_json(tmp_path, label, {
            "p50_ms": p50,
            "p95_ms": p95,
            "samples_ms": samples,
        })
        return p50, p95

    def test_rgba_hot_path_p50_p95(
        self, rust_bridge: Any, perf_jpeg_1080p: str, tmp_path: Any,
        perf_quiet_logs: Iterator[None],
    ) -> None:
        """RGBA 路径：60 次逐次计时，p50 ≤ 30ms 且 p95 ≤ 80ms。"""
        p50, p95 = self._run_hot_path(
            rust_bridge, perf_jpeg_1080p, rust_bridge.generate_rgba,
            "hot_rgba", tmp_path,
        )
        assert p50 <= 30.0, f"实测 p50 {p50:.2f}ms > 目标 30ms"
        assert p95 <= 80.0, f"实测 p95 {p95:.2f}ms > 目标 80ms"

    def test_jpg_hot_path_p50_p95(
        self, rust_bridge: Any, perf_jpeg_1080p: str, tmp_path: Any,
        perf_quiet_logs: Iterator[None],
    ) -> None:
        """JPEG 路径：60 次逐次计时，p50 ≤ 30ms 且 p95 ≤ 80ms。"""
        if not rust_bridge._supports_jpg:  # noqa: SLF001
            pytest.skip("DLL 未导出 native_generate_thumbnail_jpg")
        p50, p95 = self._run_hot_path(
            rust_bridge, perf_jpeg_1080p, rust_bridge.generate_jpg,
            "hot_jpg", tmp_path,
        )
        assert p50 <= 30.0, f"实测 p50 {p50:.2f}ms > 目标 30ms"
        assert p95 <= 80.0, f"实测 p95 {p95:.2f}ms > 目标 80ms"


# -----------------------------------------------------------------------------
# 5.3 缓存命中时延
# -----------------------------------------------------------------------------
@pytest.mark.benchmark
@pytest.mark.slow
@pytest.mark.timeout(300)
class TestPerformanceCacheHit:
    """缓存命中时延：清缓存→预热填充→计时命中调用，p95 ≤ 5ms。"""

    def test_cache_hit_p95_le_5ms(
        self, rust_bridge: Any, perf_jpeg_1080p: str, tmp_path: Any,
        perf_quiet_logs: Iterator[None],
    ) -> None:
        """40 次「清缓存→填充→计时命中」采样，p95 ≤ 5ms。"""
        bridge = rust_bridge
        for _ in range(3):  # 引擎预热（触发懒初始化）
            warm = bridge.generate_rgba(perf_jpeg_1080p, 64, 64)
            assert warm is not None, "预热调用失败"

        samples: List[float] = []
        for _ in range(_CACHE_HIT_ROUNDS):
            assert bridge.clear_cache() is True
            fill = bridge.generate_rgba(perf_jpeg_1080p, 64, 64)
            assert fill is not None, "缓存填充调用失败"
            t0 = time.perf_counter()
            hit = bridge.generate_rgba(perf_jpeg_1080p, 64, 64)
            t1 = time.perf_counter()
            assert hit is not None, "缓存命中调用返回 None（未命中）"
            samples.append((t1 - t0) * 1000.0)

        p95 = _pct(samples, 0.95)
        print(f"[cache-hit] {_fmt_stats(samples)}")
        _dump_perf_json(tmp_path, "cache_hit", {
            "p95_ms": p95,
            "samples_ms": samples,
        })
        assert p95 <= 5.0, f"实测 p95 {p95:.2f}ms > 目标 5ms"


# -----------------------------------------------------------------------------
# 5.4 突发高并发吞吐加速比
# -----------------------------------------------------------------------------
@pytest.mark.benchmark
@pytest.mark.slow
@pytest.mark.timeout(300)
class TestPerformanceBurst:
    """突发高并发：32 路并发 × 8 张混合分辨率批量，全成功零失败且加速比 ≥ 3×。

    串行基线与并发口径一致（均逐张 ``generate_jpg``）；256 个互异路径
    确保两侧均无缓存命中（见 ``perf_burst_batches``）。
    """

    def test_burst_32x8_speedup_ge_3x(
        self, rust_bridge: Any, perf_burst_batches: List[List[str]],
        tmp_path: Any, perf_quiet_logs: Iterator[None],
    ) -> None:
        """串行 32 轮×8 张 vs 32 线程并发，256/256 有效且加速比 ≥ 3.0。"""
        if not rust_bridge._supports_jpg:  # noqa: SLF001
            pytest.skip("DLL 未导出 native_generate_thumbnail_jpg")
        bridge = rust_bridge
        total_images = _BURST_BATCH_COUNT * len(_BURST_SIZES)

        def gen_batch(batch: List[str]) -> List[Optional[bytes]]:
            return [bridge.generate_jpg(p, 64, 64) for p in batch]

        # 预热丢弃：触发引擎懒初始化，避免计入基线
        gen_batch(perf_burst_batches[0])

        # 串行基线：clear_cache 后单线程 32 轮、每轮 8 张逐张
        assert bridge.clear_cache() is True
        t0 = time.perf_counter()
        serial_results: List[Optional[bytes]] = []
        for batch in perf_burst_batches:
            serial_results.extend(gen_batch(batch))
        serial_ms = (time.perf_counter() - t0) * 1000.0

        # 并发：clear_cache 后 32 任务同时提交（每任务逐张 8 张，口径一致）
        assert bridge.clear_cache() is True
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=_BURST_CONCURRENCY) as pool:
            futures = [pool.submit(gen_batch, batch)
                       for batch in perf_burst_batches]
            parallel_results: List[Optional[bytes]] = []
            for fut in futures:
                parallel_results.extend(fut.result())
        parallel_ms = (time.perf_counter() - t0) * 1000.0

        serial_ok = sum(1 for r in serial_results if r is not None)
        parallel_ok = sum(1 for r in parallel_results if r is not None)
        speedup = serial_ms / parallel_ms if parallel_ms > 0 else 0.0
        print(
            f"[burst] serial={serial_ms:.1f}ms ({serial_ok}/{total_images}) "
            f"parallel={parallel_ms:.1f}ms ({parallel_ok}/{total_images}) "
            f"speedup={speedup:.2f}x"
        )
        _dump_perf_json(tmp_path, "burst", {
            "serial_ms": serial_ms,
            "parallel_ms": parallel_ms,
            "speedup": speedup,
            "serial_ok": serial_ok,
            "parallel_ok": parallel_ok,
            "total_images": total_images,
        })

        assert serial_ok == total_images, (
            f"串行基线 {serial_ok}/{total_images} 有效，存在失败项"
        )
        assert parallel_ok == total_images, (
            f"并发 {parallel_ok}/{total_images} 有效，存在失败项（零失败要求）"
        )
        assert speedup >= 3.0, (
            f"实测加速比 {speedup:.2f}x < 目标 3.0x "
            f"(serial={serial_ms:.1f}ms parallel={parallel_ms:.1f}ms)"
        )


# -----------------------------------------------------------------------------
# 5.5 并发下单张时延
# -----------------------------------------------------------------------------
@pytest.mark.benchmark
@pytest.mark.slow
@pytest.mark.timeout(300)
class TestPerformanceConcurrentLatency:
    """32 线程并发单张 1080p RGBA：含排队+处理的单张时延 p95 ≤ 200ms。"""

    def test_concurrent_single_image_p95_le_200ms(
        self, rust_bridge: Any, perf_jpeg_1080p_copies32: List[str],
        tmp_path: Any, perf_quiet_logs: Iterator[None],
    ) -> None:
        """32 线程各对独立 1080p 文件 generate_rgba，p95 ≤ 200ms。"""
        bridge = rust_bridge
        # 预热丢弃（触发懒初始化），随后清缓存保证 32 路均真实解码
        warm = bridge.generate_rgba(perf_jpeg_1080p_copies32[0], 64, 64)
        assert warm is not None, "预热调用失败"
        assert bridge.clear_cache() is True

        def worker(path: str) -> Tuple[float, bool]:
            t0 = time.perf_counter()
            result = bridge.generate_rgba(path, 64, 64)
            t1 = time.perf_counter()
            return (t1 - t0) * 1000.0, result is not None

        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=_CONCURRENT_IMAGE_WORKERS) as pool:
            futures = [pool.submit(worker, p)
                       for p in perf_jpeg_1080p_copies32]
            outcomes = [fut.result() for fut in futures]
        wall_ms = (time.perf_counter() - t0) * 1000.0

        failures = [lat for lat, ok in outcomes if not ok]
        valid = [lat for lat, ok in outcomes if ok]
        p95 = _pct(valid, 0.95) if valid else float("inf")
        print(
            f"[concurrent-latency] n={len(outcomes)} "
            f"fail={len(failures)} wall={wall_ms:.1f}ms "
            f"latency({_fmt_stats(valid)})"
        )
        _dump_perf_json(tmp_path, "concurrent_latency", {
            "wall_ms": wall_ms,
            "p95_ms": p95,
            "failures": len(failures),
            "samples_ms": valid,
        })

        assert not failures, f"{len(failures)} 路并发调用返回 None（零失败要求）"
        assert p95 <= 200.0, f"实测 p95 {p95:.2f}ms > 目标 200ms"


# -----------------------------------------------------------------------------
# 5.6 视频抽帧性能（类级 timeout 600s 覆盖夹具生成与多次抽帧）
# -----------------------------------------------------------------------------
@pytest.mark.skipif(
    _SYSTEM_FFMPEG is None,
    reason="系统 PATH 无完整版 ffmpeg，无法生成视频夹具",
)
@pytest.mark.benchmark
@pytest.mark.slow
@pytest.mark.timeout(600)
class TestPerformanceVideo:
    """视频抽帧性能：720p/5s p50 ≤ 3s 且 8/8 成功；4 路并发视频全成功。"""

    def test_video_720p_5s_p50_le_3s(
        self, rust_bridge: Any, video_fixtures: Dict[str, str],
        tmp_path: Any, perf_quiet_logs: Iterator[None],
    ) -> None:
        """720p/5s mp4 → 64x64：8 次「清缓存+计时」，8/8 成功且 p50 ≤ 3s。"""
        bridge = rust_bridge
        path = video_fixtures["mp4_1280x720_5s"]
        # 预热丢弃：触发 ffmpeg/d3d11va 解码路径初始化
        warm = bridge.generate_rgba(path, 64, 64)
        assert warm is not None, "预热抽帧失败"

        samples: List[float] = []
        for i in range(_VIDEO_EXTRACT_ROUNDS):
            assert bridge.clear_cache() is True
            t0 = time.perf_counter()
            result = bridge.generate_rgba(path, 64, 64)
            t1 = time.perf_counter()
            assert result is not None, f"第 {i + 1} 轮抽帧失败（返回 None）"
            samples.append((t1 - t0) * 1000.0)

        p50 = _pct(samples, 0.50)
        print(f"[video-720p-5s] {_fmt_stats(samples)}")
        _dump_perf_json(tmp_path, "video_720p_5s", {
            "p50_ms": p50,
            "samples_ms": samples,
        })
        assert len(samples) == _VIDEO_EXTRACT_ROUNDS, "存在未计入的失败轮次"
        assert p50 <= 3000.0, f"实测 p50 {p50:.1f}ms > 目标 3000ms"

    def test_concurrent_4_videos_all_success(
        self, rust_bridge: Any, video_fixtures: Dict[str, str],
        tmp_path: Any, perf_quiet_logs: Iterator[None],
    ) -> None:
        """4 个不同规格视频 4 线程同时 generate_rgba，全部非 None。"""
        bridge = rust_bridge
        keys = (
            "mp4_320x240_1s",
            "mp4_1280x720_1s",
            "mp4_1280x720_5s",
            "mp4_1920x1080_5s",
        )
        paths = [video_fixtures[k] for k in keys]

        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=_CONCURRENT_VIDEO_PATHS) as pool:
            futures = [pool.submit(bridge.generate_rgba, p, 64, 64)
                       for p in paths]
            results = [fut.result() for fut in futures]
        wall_ms = (time.perf_counter() - t0) * 1000.0

        outcomes = {keys[i]: results[i] is not None
                    for i in range(len(keys))}
        print(f"[concurrent-video] outcomes={outcomes} wall={wall_ms:.1f}ms")
        _dump_perf_json(tmp_path, "concurrent_video", {
            "wall_ms": wall_ms,
            "outcomes": outcomes,
        })
        for key, ok in outcomes.items():
            assert ok, f"并发视频 {key} 抽帧失败（返回 None）"
