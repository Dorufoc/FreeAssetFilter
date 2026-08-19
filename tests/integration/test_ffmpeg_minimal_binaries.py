# -*- coding: utf-8 -*-
# targets: core.native.bridges.media_probe / core.managers.thumbnail_manager / rust_thumbnail_bridge
"""FFmpeg 精简二进制集成测试（ffmpeg-minimal-rebuild 计划 Wave 6）。

对替换后的 7MB 静态精简 ffmpeg.exe/ffprobe.exe 做真实二进制级契约验证：

* ① 版本命令（ffmpeg/ffprobe ``-version``）返回码为 0；
* ② ``warmup_ffmpeg_tools()`` 结构契约 + 三条底层命令直接健康探测
  （返回值存在既有已知 bug，见 evidence/warmup-known-issue.md，本文件
  不修复产品代码、不掩盖事实）；
* ③ manifest 能力清单（-formats/-codecs/-filters/-protocols/-hwaccels）
  逐项断言调用点审计的 allow-list；
* ④ ffprobe 时长 JSON：每个样本 ``format.duration > 0`` 且含 video 流；
* ⑤ Python 抽帧：``ThumbnailManager._create_video_thumbnail_ffmpeg`` 产出
  PIL 可解码、尺寸非空、体积 > 0 的 JPEG；
* ⑥ Rust 桥：``RustThumbnailBridge.generate_jpg`` 返回非空可解码 JPEG，
  ``get_available_hwaccels()`` 含 d3d11va/dxva2（rust_available 门控）；
* ⑦ 失败路径：截断的 mp4 副本 → ffprobe 返回 None，抽帧快速失败不挂起。

全部用例以 ``ffmpeg_available`` 门控（False 时跳过）；超时语义遵循
``tests/support/timeout_policy``（integration 层自动 60s）。
"""

from __future__ import annotations

import io
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import pytest
from PIL import Image


pytestmark = pytest.mark.integration


#: 已提交的 10 个视频样本文件名（与 tests/support/media/ 一致，顺序稳定）。
VIDEO_SAMPLE_NAMES: Tuple[str, ...] = (
    "sample_flv1.flv",
    "sample_h263.3gp",
    "sample_h264_mov.mov",
    "sample_h264.mkv",
    "sample_h264.mp4",
    "sample_mpeg2.mpg",
    "sample_mpeg2.mxf",
    "sample_mpeg4.avi",
    "sample_vp9.webm",
    "sample_wmv2.wmv",
)

#: 调用点审计的 manifest 期望清单（与计划 enable 列表一致）。
#: 注意：configure 的 `--enable-demuxer=mpegps` 组件在运行时注册为 demuxer 名
#: `mpeg`（MPEG-PS/Program Stream，见 `ffmpeg -formats` 实际输出），因此此处用
#: 运行时名 `mpeg` 而非配置名 `mpegps`。
EXPECTED_DEMUXERS: Tuple[str, ...] = (
    "mov",
    "matroska",
    "avi",
    "flv",
    "asf",
    "mpeg",
    "mpegts",
    "mxf",
    "dv",
)
EXPECTED_MUXERS: Tuple[str, ...] = ("image2", "image2pipe")
#: FFmpeg master 已将 FLV1 解码器组件名从 flv1 更名为 flv（见 Todo 2 修复轮）。
EXPECTED_DECODERS: Tuple[str, ...] = (
    "h264",
    "hevc",
    "mpeg2video",
    "mpeg4",
    "vp8",
    "vp9",
    "av1",
    "wmv1",
    "wmv2",
    "wmv3",
    "vc1",
    "flv",
    "h263",
    "prores",
    "dvvideo",
    "mjpeg",
)
EXPECTED_ENCODERS: Tuple[str, ...] = ("mjpeg",)


# =============================================================================
# fixtures
# =============================================================================
@pytest.fixture
def ffmpeg_ready(ffmpeg_available: bool) -> None:
    """门控：ffmpeg 不可用时跳过所在用例。

    Args:
        ffmpeg_available: conftest 的会话级 ffmpeg 可用性探测结果。

    Returns:
        None。
    """
    if not ffmpeg_available:
        pytest.skip("ffmpeg_available=False（ffmpeg.exe 缺失或不可执行），跳过")


@pytest.fixture
def video_sample(video_sample_paths: List[str], request: Any) -> str:
    """从会话级样本列表按文件名选取单个样本（indirect parametrize 用）。

    Args:
        video_sample_paths: 会话级视频样本路径列表（由 conftest 提供）。
        request: pytest 请求对象，``request.param`` 为样本文件名。

    Returns:
        str: 所选样本的绝对路径。
    """
    by_name: Dict[str, str] = {Path(p).name: p for p in video_sample_paths}
    return by_name[request.param]


# =============================================================================
# 工具函数
# =============================================================================
def _run_tool_capture(command: List[str], timeout: int = 10) -> str:
    """运行 ffmpeg/ffprobe 信息命令并返回合并输出（stdout + stderr）。

    Args:
        command: 待运行的命令行参数列表。
        timeout: 子进程超时秒数。

    Returns:
        str: stdout 与 stderr 合并的文本输出。

    Raises:
        AssertionError: 命令返回码非 0。
    """
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    assert completed.returncode == 0, (
        f"命令失败 rc={completed.returncode}: {' '.join(command)}"
        f" stderr={completed.stderr!r}"
    )
    return (completed.stdout or "") + (completed.stderr or "")


def _parse_name_flags(lines: Iterable[str]) -> Dict[str, str]:
    """从 ffmpeg 清单输出解析 name → flags 映射（鲁棒，不依赖定宽列）。

    每个数据行形如 ``<flags> <name> <description>``；跳过空行、分隔线与
    ``=`` 图例行（flags 与 name 拆分后再过滤，位置无关）。

    Args:
        lines: 输出行迭代器。

    Returns:
        dict[str, str]: 组件名 → 标志字符串。
    """
    result: Dict[str, str] = {}
    for line in lines:
        stripped: str = line.strip()
        if not stripped:
            continue
        parts: List[str] = stripped.split(None, 2)
        if len(parts) < 2:
            continue
        flags: str = parts[0]
        name: str = parts[1]
        if name == "=" or name.startswith("="):
            continue
        result[name] = flags
    return result


def _parse_protocol_sections(output: str) -> Dict[str, Set[str]]:
    """解析 ``-protocols`` 输出，返回 section → 协议名集合。

    Args:
        output: ``-protocols`` 的合并输出。

    Returns:
        dict[str, set[str]]: 含 ``Input`` 与 ``Output`` 两个键的集合映射。
    """
    sections: Dict[str, Set[str]] = {"Input": set(), "Output": set()}
    current: Optional[str] = None
    for line in output.splitlines():
        stripped: str = line.strip()
        if stripped in ("Input:", "Output:"):
            current = stripped[:-1]
            continue
        if not stripped:
            continue
        if current is not None:
            sections[current].add(stripped)
    return sections


# =============================================================================
# ① 版本命令
# =============================================================================
class TestVersionCommands:
    """ffmpeg / ffprobe ``-version`` 返回码为 0。"""

    def test_ffmpeg_version_rc0(self, ffmpeg_ready: None) -> None:
        """ffmpeg -hide_banner -version 返回 0。"""
        from freeassetfilter.core.native.bridges.media_probe import get_ffmpeg_path

        completed = subprocess.run(
            [get_ffmpeg_path(), "-hide_banner", "-version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        assert completed.returncode == 0

    def test_ffprobe_version_rc0(self, ffmpeg_ready: None) -> None:
        """ffprobe -version 返回 0。"""
        from freeassetfilter.core.native.bridges.media_probe import get_ffprobe_path

        completed = subprocess.run(
            [get_ffprobe_path(), "-version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        assert completed.returncode == 0


# =============================================================================
# ② 预热 / 结构契约
# =============================================================================
class TestWarmup:
    """``warmup_ffmpeg_tools()`` 结构契约与底层命令健康度。

    注意：warmup 返回值既有已知 bug（positional 展开 keyword-only 参数
    → TypeError，三键恒 False）已于产品修复后同步更新断言，见
    evidence/warmup-known-issue.md。这里断言"结构 + 直接命令健康"。
    """

    def test_warmup_returns_structure_contract(self, ffmpeg_ready: None) -> None:
        """返回 dict 且键恰为 ffmpeg_version / ffprobe_version / ffmpeg_hwaccels。"""
        from freeassetfilter.core.native.bridges.media_probe import warmup_ffmpeg_tools

        result = warmup_ffmpeg_tools(force=True)
        assert set(result) == {"ffmpeg_version", "ffprobe_version", "ffmpeg_hwaccels"}

    def test_warmup_underlying_commands_healthy(self, ffmpeg_ready: None) -> None:
        """warmup 的三条底层命令全部返回 0（真实二进制健康度）。"""
        from freeassetfilter.core.native.bridges.media_probe import (
            get_ffmpeg_path,
            get_ffprobe_path,
        )

        commands: List[List[str]] = [
            [get_ffprobe_path(), "-version"],
            [get_ffmpeg_path(), "-hide_banner", "-version"],
            [get_ffmpeg_path(), "-hide_banner", "-hwaccels"],
        ]
        for command in commands:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
            assert completed.returncode == 0, (
                f"warmup 底层命令失败: {' '.join(command)} rc={completed.returncode}"
            )

    def test_warmup_values_true_after_fix(self, ffmpeg_ready: None) -> None:
        """修复后验证：三键均 True（keyword-only 参数 bug 已修复）。

        既有 bug（positional 展开 keyword-only 参数 → TypeError → 三键恒
        False）已在产品代码修复：``warmup_ffmpeg_tools()`` 现在按
        ``command`` 位置 + ``label=/timeout=`` 关键字提交，三条底层命令
        真实执行成功。修复记录见
        ``.omo/evidence/ffmpeg-minimal-rebuild/warmup-known-issue.md``。
        """
        from freeassetfilter.core.native.bridges.media_probe import warmup_ffmpeg_tools

        result = warmup_ffmpeg_tools(force=True)
        assert all(result.values())


# =============================================================================
# ③ manifest 能力清单（allow-list，逐项断言）
# =============================================================================
class TestManifestAllowList:
    """解析 ffmpeg 清单输出，逐项断言 allow-list 全部在位。"""

    def test_demuxers(self, ffmpeg_ready: None) -> None:
        """-formats 的 D 标志行含全部 9 个 demuxer（含逗号别名组拆分）。"""
        from freeassetfilter.core.native.bridges.media_probe import get_ffmpeg_path

        output: str = _run_tool_capture([get_ffmpeg_path(), "-hide_banner", "-formats"])
        # 别名组形如 `mov,mp4,m4a,3gp,3g2,mj2` / `matroska,webm`，按逗号拆开后
        # 参与者名（mov/matroska）即可按成员名匹配。
        demuxers: Set[str] = {
            member
            for name, flags in _parse_name_flags(output.splitlines()).items()
            if "D" in flags
            for member in name.split(",")
        }
        for expected in EXPECTED_DEMUXERS:
            assert expected in demuxers, f"缺少 demuxer: {expected}"

    def test_muxers(self, ffmpeg_ready: None) -> None:
        """-formats 的 E 标志行含 image2 与 image2pipe 两个 muxer。"""
        from freeassetfilter.core.native.bridges.media_probe import get_ffmpeg_path

        output: str = _run_tool_capture([get_ffmpeg_path(), "-hide_banner", "-formats"])
        muxers: Set[str] = {
            name
            for name, flags in _parse_name_flags(output.splitlines()).items()
            if "E" in flags
        }
        for expected in EXPECTED_MUXERS:
            assert expected in muxers, f"缺少 muxer: {expected}"

    def test_decoders(self, ffmpeg_ready: None) -> None:
        """-codecs 的 D 标志行含全部 16 个解码器（逐项，不数总数）。"""
        from freeassetfilter.core.native.bridges.media_probe import get_ffmpeg_path

        output: str = _run_tool_capture([get_ffmpeg_path(), "-hide_banner", "-codecs"])
        codecs: Dict[str, str] = _parse_name_flags(output.splitlines())
        decoders: Set[str] = {name for name, flags in codecs.items() if "D" in flags}
        # FFmpeg master 中 FLV1 解码器组件名为 `flv`（原 flv1），但 `-codecs` 行名
        # 仍显示 flv1、真身 `flv` 仅出现在行尾注解 `(decoders: flv)` 中。从注解
        # 提取该组件名，保证断言匹配运行时真实组件名 `flv` 而非 `flv1`。
        for line in output.splitlines():
            stripped = line.strip()
            if "(decoders:" in stripped:
                for token in stripped.split("(decoders:")[1].split(")")[0].split():
                    if token:
                        decoders.add(token)
        for expected in EXPECTED_DECODERS:
            assert expected in decoders, f"缺少解码器: {expected}"

    def test_encoder_mjpeg(self, ffmpeg_ready: None) -> None:
        """-codecs 的 E 标志行含 mjpeg 编码器。"""
        from freeassetfilter.core.native.bridges.media_probe import get_ffmpeg_path

        output: str = _run_tool_capture([get_ffmpeg_path(), "-hide_banner", "-codecs"])
        codecs: Dict[str, str] = _parse_name_flags(output.splitlines())
        encoders: Set[str] = {name for name, flags in codecs.items() if "E" in flags}
        for expected in EXPECTED_ENCODERS:
            assert expected in encoders, f"缺少编码器: {expected}"

    def test_scale_filter_present(self, ffmpeg_ready: None) -> None:
        """-filters 含 scale 滤镜。"""
        from freeassetfilter.core.native.bridges.media_probe import get_ffmpeg_path

        output: str = _run_tool_capture([get_ffmpeg_path(), "-hide_banner", "-filters"])
        filters: Dict[str, str] = _parse_name_flags(output.splitlines())
        assert "scale" in filters, "缺少 scale filter"

    def test_protocols_file_and_pipe(self, ffmpeg_ready: None) -> None:
        """-protocols 的 Input 与 Output 两段均含 file 与 pipe。"""
        from freeassetfilter.core.native.bridges.media_probe import get_ffmpeg_path

        output: str = _run_tool_capture([get_ffmpeg_path(), "-hide_banner", "-protocols"])
        sections: Dict[str, Set[str]] = _parse_protocol_sections(output)
        assert "file" in sections["Input"], "Input 段缺少 file 协议"
        assert "pipe" in sections["Input"], "Input 段缺少 pipe 协议"
        assert "file" in sections["Output"], "Output 段缺少 file 协议"
        assert "pipe" in sections["Output"], "Output 段缺少 pipe 协议"

    def test_hwaccels_d3d11va_dxva2(self, ffmpeg_ready: None) -> None:
        """-hwaccels 含 d3d11va 与 dxva2（额外条目如 vaapi 允许存在）。"""
        from freeassetfilter.core.native.bridges.media_probe import get_ffmpeg_path

        output: str = _run_tool_capture([get_ffmpeg_path(), "-hide_banner", "-hwaccels"])
        names: Set[str] = {
            line.strip()
            for line in output.splitlines()
            if line.strip() and "=" not in line
        }
        assert "d3d11va" in names, f"hwaccels 缺少 d3d11va: {sorted(names)}"
        assert "dxva2" in names, f"hwaccels 缺少 dxva2: {sorted(names)}"


# =============================================================================
# ④ ffprobe 时长（参数化 10 个样本）
# =============================================================================
class TestFfprobeDuration:
    """``run_ffprobe_json`` 对每个样本返回 duration > 0 且含 video 流。"""

    @pytest.mark.parametrize("video_sample", VIDEO_SAMPLE_NAMES, indirect=True)
    def test_ffprobe_duration_and_video_stream(
        self, video_sample: str, ffmpeg_ready: None
    ) -> None:
        from freeassetfilter.core.native.bridges.media_probe import run_ffprobe_json

        result = run_ffprobe_json(video_sample)
        assert result is not None, f"ffprobe 未能解析样本: {video_sample}"
        duration_text = (result.get("format") or {}).get("duration")
        assert duration_text is not None, f"样本缺少 format.duration: {video_sample}"
        # 已知怪癖：sample_mpeg2.mpg 的 format.duration 仅 0.000011（MPEG-PS
        # 容器无 duration 字段）——只断言 > 0，绝不设精确/最小值。
        assert float(duration_text) > 0, f"format.duration 非正: {duration_text}"
        assert any(
            stream.get("codec_type") == "video"
            for stream in (result.get("streams") or [])
        ), f"样本缺少 video 流: {video_sample}"


# =============================================================================
# ⑤ Python 抽帧（参数化 10 个样本）
# =============================================================================
class TestPythonFrameExtraction:
    """``ThumbnailManager._create_video_thumbnail_ffmpeg`` 产出可解码 JPEG。"""

    @pytest.mark.parametrize("video_sample", VIDEO_SAMPLE_NAMES, indirect=True)
    def test_python_ffmpeg_frame_extraction(
        self, video_sample: str, ffmpeg_ready: None, qapp: Any, tmp_path: Any
    ) -> None:
        from freeassetfilter.core.managers.thumbnail_manager import get_thumbnail_manager

        manager = get_thumbnail_manager()
        out_path: str = str(tmp_path / f"{Path(video_sample).stem}_py.jpg")
        result = manager._create_video_thumbnail_ffmpeg(video_sample, out_path)  # noqa: SLF001
        assert result is not None, f"Python 抽帧失败: {video_sample}"
        assert os.path.getsize(result) > 0, "抽帧产物为空文件"
        with Image.open(result) as img:
            width, height = img.size
            # BASE_SIZE=128×dpi_scale 约束——只断言"非空尺寸"而非具体像素值。
            assert width > 0 and height > 0, f"JPEG 尺寸异常: {img.size}"


# =============================================================================
# ⑥ Rust 桥（rust_available 门控）
# =============================================================================
class TestRustBridge:
    """``RustThumbnailBridge`` 视频抽帧返回非空 JPEG，hwaccels 命中。"""

    @pytest.mark.parametrize("video_sample", VIDEO_SAMPLE_NAMES, indirect=True)
    def test_rust_bridge_generate_jpg(
        self, video_sample: str, ffmpeg_ready: None, rust_available: bool
    ) -> None:
        if not rust_available:
            pytest.skip("Rust 原生扩展不可用（rust_available=False），跳过")
        from freeassetfilter.core.native.bridges.rust_thumbnail_bridge import (
            RustThumbnailBridge,
        )

        bridge = RustThumbnailBridge()
        jpg_bytes = bridge.generate_jpg(video_sample, 256, 256)
        assert jpg_bytes is not None and len(jpg_bytes) > 0, (
            f"Rust 抽帧失败: {video_sample}"
        )
        with Image.open(io.BytesIO(jpg_bytes)) as img:
            width, height = img.size
            assert width > 0 and height > 0, f"JPEG 尺寸异常: {img.size}"
        hwaccels: List[str] = bridge.get_available_hwaccels()
        assert hwaccels, "get_available_hwaccels() 返回空列表"
        lowered: Set[str] = {item.lower() for item in hwaccels}
        assert "d3d11va" in lowered, f"hwaccels 缺少 d3d11va: {hwaccels}"
        assert "dxva2" in lowered, f"hwaccels 缺少 dxva2: {hwaccels}"


# =============================================================================
# ⑦ 失败路径（截断文件：fails-fast，不挂起）
# =============================================================================
class TestFailurePath:
    """损坏/截断输入 → 返回 None / falsy，快速失败不挂起。"""

    def test_corrupt_mp4_fails_fast(
        self, ffmpeg_ready: None, qapp: Any, tmp_path: Any
    ) -> None:
        from tests.support.data_factories import make_video_sample
        from freeassetfilter.core.managers.thumbnail_manager import get_thumbnail_manager
        from freeassetfilter.core.native.bridges.media_probe import run_ffprobe_json

        corrupt_path: str = make_video_sample(
            "sample_h264.mp4", tmp_path / "corrupt.mp4"
        )
        corrupt_file = Path(corrupt_path)
        data: bytes = corrupt_file.read_bytes()
        corrupt_file.write_bytes(data[: len(data) // 2])

        # ffprobe：截断文件返回 None 而非抛异常。
        assert run_ffprobe_json(corrupt_path) is None

        # 抽帧路径：快速失败返回 falsy（进程内自带 timeout，不挂起）。
        manager = get_thumbnail_manager()
        result = manager._create_video_thumbnail_ffmpeg(  # noqa: SLF001
            corrupt_path, str(tmp_path / "corrupt.jpg")
        )
        assert not result