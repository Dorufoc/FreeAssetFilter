# -*- coding: utf-8 -*-
# targets: core.native.bridges.rust_thumbnail_bridge
"""缩略图延迟分位数与批量吞吐基准（thumbnail-rust-refactor todo 30）。

锁定 T1/T2 主路径经桥 ``with_status`` 入口的性能契约（严格版；既有
``test_thumbnail_perf.py`` 的 ``AVG_UPPER_BOUND_S=0.2`` 宽松断言保留作回归网）：

* 图像合集单张延迟：P50 ≤ 50ms / P95 ≤ 150ms（进程内、排除首轮冷缓存）；
* 视频抽帧延迟：P50 ≤ 0.8s / P95 ≤ 3s（T2 ffmpeg 子进程路径）；
* 批量吞吐 ≥ 120 张/s（16 线程、普通 SSD、预热后计时）。

并发口径说明（按桥 API 特性选择）：吞吐用 **ThreadPoolExecutor(16) 并发单张**
而非 ``generate_jpg_batch``——批量导出内部已由 rayon 全局池并行（Task 4 实测
worker 数 = CPU 数），再叠加 16 个批量调用方会让计时粒度模糊；ctypes 调用
期间释放 GIL，16 线程并发单张可获得真实并行度，且该调用方模式已被
``tests/unit/core/test_rust_batch_concurrency.py`` 验证为数据安全。

计时纪律：

* 全部使用 ``time.perf_counter``；
* 首轮预热（DLL 惰性初始化 / rayon 注册表 / ffmpeg 能力表 OnceLock / 首次
  解码冷缓存）不计入统计；
* 原生内存缓存保持热态（契约原文"预热后计时"），度量稳态用户可感延迟。

冒烟降级：设环境变量 ``FAF_BENCH_SMOKE=1`` 时以 5 样本快速模式运行
（阈值不变、仅缩样本），供 CI 冒烟门控。

语料口径（todo 30 实测发现）：固化夹具中 ``min(w,h) < 8`` 的微缩图经原生
JPG 编码路径返回 -5（RGBA 路径正常，生产链路由 manager 的 Python 兜底
消化）——基准只度量成功生成，故按运行时探针过滤这部分夹具并如实记录；
另以 ``make_image`` 补充 240x180 ~ 1024x768 常规尺寸样本贴近真实负载。

基准落盘：每次运行将 P50/P95/吞吐/时间戳/机器摘要写入
``tests/benchmark/baseline/thumbnail-latency.json``。
"""

from __future__ import annotations

import itertools
import json
import math
import os
import platform
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence

import pytest

from freeassetfilter.core.native.bridges.rust_thumbnail_bridge import (
    RustThumbnailBridge,
)
from tests.support.data_factories import make_image

pytestmark = [pytest.mark.benchmark, pytest.mark.rust]

#: 冒烟模式开关（FAF_BENCH_SMOKE=1 时启用 5 样本快速断言）。
_SMOKE_ENV: str = os.environ.get("FAF_BENCH_SMOKE", "").strip().lower()
SMOKE_MODE: bool = _SMOKE_ENV not in ("", "0", "false", "no")

# --- 契约阈值（todo 30 原文，不许改） ---
#: 图像单张 P50 上限（毫秒）。
IMAGE_P50_LIMIT_MS: float = 50.0
#: 图像单张 P95 上限（毫秒）。
IMAGE_P95_LIMIT_MS: float = 150.0
#: 视频抽帧 P50 上限（毫秒）。
VIDEO_P50_LIMIT_MS: float = 800.0
#: 视频抽帧 P95 上限（毫秒）。
VIDEO_P95_LIMIT_MS: float = 3000.0
#: 批量吞吐下限（张/秒）。
THROUGHPUT_FLOOR_IPS: float = 120.0

# --- 样本规模 ---
#: 全量模式图像计时样本数（语料轮转采样）。
IMAGE_SAMPLES_FULL: int = 100
#: 冒烟模式图像样本数。
IMAGE_SAMPLES_SMOKE: int = 5
#: 全量模式参与计时的视频数（取体积最小的前 N 个，控制总时长）。
VIDEO_FILES_FULL: int = 3
#: 全量模式每视频计时次数（3 文件 × 5 次 = 15 样本）。
VIDEO_PASSES_FULL: int = 5
#: 冒烟模式视频样本数（最小单文件 × 5 次）。
VIDEO_SAMPLES_SMOKE: int = 5
#: 吞吐测试线程数。
THROUGHPUT_THREADS: int = 16
#: 全量模式吞吐轮数（16 线程 × 20 轮 = 320 任务）。
THROUGHPUT_ROUNDS_FULL: int = 20
#: 冒烟模式吞吐轮数（16 线程 × 4 轮 = 64 任务）。
THROUGHPUT_ROUNDS_SMOKE: int = 4
#: 目标缩略图边长（正方形，与 manager 默认口径同量级）。
THUMB_SIZE: int = 128
#: 原生 JPG 编码路径的实测最小边长约束（min(w,h) < 8 的源返回 -5，
#: RGBA 路径不受限；见模块 docstring 语料口径说明）。
JPG_PATH_MIN_DIM: int = 8

#: 程序化常规尺寸样本（文件名, PIL 格式, 尺寸）——贴近真实缩略图负载。
GENERATED_SPECS = [
    ("gen_240x180.jpg", "JPEG", (240, 180)),
    ("gen_320x240.png", "PNG", (320, 240)),
    ("gen_640x480.jpg", "JPEG", (640, 480)),
    ("gen_800x600.png", "PNG", (800, 600)),
    ("gen_1024x768.jpg", "JPEG", (1024, 768)),
]

#: 固化图像夹具目录（19 个小图，全部 <2KB）。
FIXTURE_DIR: Path = (
    Path(__file__).resolve().parents[1] / "unit" / "core" / "thumbnail_fixtures"
)
#: 视频样本目录（11 个小视频）。
MEDIA_DIR: Path = Path(__file__).resolve().parents[1] / "support" / "media"
#: 基准 JSON 落盘路径。
BASELINE_PATH: Path = (
    Path(__file__).resolve().parent / "baseline" / "thumbnail-latency.json"
)

#: 模块级基准结果累积器（每个用例写入自己的小节后整体落盘）。
_BASELINE: Dict[str, Any] = {}


# =============================================================================
# 辅助函数
# =============================================================================
def _percentile(sorted_values: Sequence[float], pct: float) -> float:
    """线性插值分位数（与 numpy 默认 linear 口径一致）。

    Args:
        sorted_values: 已升序排序的样本序列。
        pct: 百分位（0-100）。

    Returns:
        float: 分位数值；空序列返回 0.0。
    """
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank: float = (len(sorted_values) - 1) * (pct / 100.0)
    lo: int = int(math.floor(rank))
    hi: int = min(lo + 1, len(sorted_values) - 1)
    frac: float = rank - lo
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


def _video_corpus(count: int) -> List[str]:
    """体积最小的 ``count`` 个视频样本（控制 ffmpeg 子进程总时长）。

    Args:
        count: 需要的视频数量。

    Returns:
        list[str]: 绝对路径列表（按体积升序）。
    """
    videos: List[Path] = sorted(
        (p for p in MEDIA_DIR.iterdir() if p.is_file()),
        key=lambda p: (p.stat().st_size, p.name),
    )
    return [str(p) for p in videos[:count]]


def _timed_jpg_calls(
    bridge: RustThumbnailBridge, paths: Sequence[str], total: int
) -> List[float]:
    """逐张计时调用 ``generate_jpg_with_status``，返回毫秒样本列表。

    按 ``itertools.cycle`` 轮转语料；每个样本断言 status==0 且 JPEG 魔数完整，
    确保计时的是成功生成而非失败快速返回。

    Args:
        bridge: 已确认可用的原生桥实例。
        paths: 语料路径列表（至少 1 个）。
        total: 计时样本总数。

    Returns:
        list[float]: 每次调用的耗时（毫秒）。
    """
    samples: List[float] = []
    for path in itertools.islice(itertools.cycle(paths), total):
        start: float = time.perf_counter()
        blob, status = bridge.generate_jpg_with_status(path, THUMB_SIZE, THUMB_SIZE)
        elapsed_ms: float = (time.perf_counter() - start) * 1000.0
        assert status == 0, f"{Path(path).name} 生成失败 status={status}"
        assert blob is not None and blob[:2] == b"\xff\xd8", (
            f"{Path(path).name} 返回非法 JPEG"
        )
        samples.append(elapsed_ms)
    return samples


def _machine_summary() -> Dict[str, Any]:
    """机器摘要字段（平台 / Python / CPU）。"""
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
    }


def _record_baseline(section: str, payload: Dict[str, Any]) -> None:
    """累积基准小节并整体落盘 JSON。

    最后写入的文件包含本次运行全部已完成小节；只跑单个用例时其余小节
    缺省，JSON 仍自洽。

    Args:
        section: 小节名（image_latency / video_latency / batch_throughput）。
        payload: 该小节的指标字典。
    """
    _BASELINE[section] = payload
    document: Dict[str, Any] = {
        "schema": "thumbnail-latency-baseline/v1",
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "smoke" if SMOKE_MODE else "full",
        "machine": _machine_summary(),
    }
    document.update(_BASELINE)
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


@pytest.fixture(scope="module")
def bridge() -> RustThumbnailBridge:
    """模块级共享原生桥实例；DLL 不可用时跳过整个基准。

    Returns:
        RustThumbnailBridge: 已确认 ``available`` 的桥实例。
    """
    inst = RustThumbnailBridge()
    if not inst.available:
        pytest.skip("thumbnail_generator.dll 不可用，跳过原生缩略图基准")
    return inst


@pytest.fixture(scope="module")
def image_corpus(
    bridge: RustThumbnailBridge, tmp_path_factory: Any
) -> List[str]:
    """图像语料：JPG 路径可成功的固化夹具 + 程序化常规尺寸样本。

    夹具先经 ``generate_rgba_with_status`` 探针取源尺寸，过滤
    ``min(w,h) < JPG_PATH_MIN_DIM`` 的微缩图（原生 JPG 编码路径对这类源
    返回 -5，生产链路由 manager 回退 Python 兜底；基准只度量成功生成），
    过滤名单打印留痕并写入基准 JSON。

    Args:
        bridge: 已确认可用的原生桥实例。
        tmp_path_factory: pytest 会话级临时目录工厂（程序化样本落盘处）。

    Returns:
        list[str]: 图像绝对路径列表。
    """
    corpus: List[str] = []
    excluded: List[str] = []
    for p in sorted(FIXTURE_DIR.iterdir()):
        if not p.is_file() or p.suffix == ".py":
            continue
        payload, _status = bridge.generate_rgba_with_status(
            str(p), THUMB_SIZE, THUMB_SIZE
        )
        if payload is None:
            excluded.append(p.name)
            continue
        _raw, width, height, _ch = payload
        if min(width, height) < JPG_PATH_MIN_DIM:
            excluded.append(f"{p.name}({width}x{height})")
            continue
        corpus.append(str(p))

    workdir: Any = tmp_path_factory.mktemp("faf_bench_corpus")
    for name, fmt, size in GENERATED_SPECS:
        corpus.append(make_image(workdir / name, fmt=fmt, size=size))

    print(
        f"\n图像语料: {len(corpus)} 个"
        f"（夹具 {len(corpus) - len(GENERATED_SPECS)} + 程序化 {len(GENERATED_SPECS)}）；"
        f"排除微缩图: {', '.join(excluded) if excluded else '无'}"
    )
    return corpus


# =============================================================================
# 图像延迟分位数
# =============================================================================
class TestImageLatencyQuantiles:
    """图像合集单张延迟分位数（进程内 T1 主路径，排除首轮冷缓存）。"""

    def test_image_p50_p95_within_contract(
        self, bridge: RustThumbnailBridge, image_corpus: List[str]
    ) -> None:
        """预热一轮后采样：P50 ≤ 50ms 且 P95 ≤ 150ms。"""
        corpus: List[str] = (
            image_corpus[:IMAGE_SAMPLES_SMOKE] if SMOKE_MODE else image_corpus
        )

        # 预热轮：DLL 惰性初始化 + 首次解码冷缓存，不计入统计
        _timed_jpg_calls(bridge, corpus, len(corpus))

        total: int = IMAGE_SAMPLES_SMOKE if SMOKE_MODE else IMAGE_SAMPLES_FULL
        samples: List[float] = _timed_jpg_calls(bridge, corpus, total)

        ordered: List[float] = sorted(samples)
        p50: float = _percentile(ordered, 50.0)
        p95: float = _percentile(ordered, 95.0)
        mean_ms: float = sum(samples) / len(samples)
        print(
            f"\n图像单张延迟: 样本 {len(samples)} | "
            f"P50 {p50:.2f}ms | P95 {p95:.2f}ms | 平均 {mean_ms:.2f}ms | "
            f"最大 {ordered[-1]:.2f}ms"
        )
        _record_baseline(
            "image_latency",
            {
                "samples": len(samples),
                "corpus_size": len(corpus),
                "p50_ms": round(p50, 3),
                "p95_ms": round(p95, 3),
                "mean_ms": round(mean_ms, 3),
                "max_ms": round(ordered[-1], 3),
                "thresholds": {
                    "p50_ms": IMAGE_P50_LIMIT_MS,
                    "p95_ms": IMAGE_P95_LIMIT_MS,
                },
            },
        )
        assert p50 <= IMAGE_P50_LIMIT_MS, (
            f"图像单张 P50 过慢: {p50:.2f}ms (上限 {IMAGE_P50_LIMIT_MS:.0f}ms)"
        )
        assert p95 <= IMAGE_P95_LIMIT_MS, (
            f"图像单张 P95 过慢: {p95:.2f}ms (上限 {IMAGE_P95_LIMIT_MS:.0f}ms)"
        )


# =============================================================================
# 视频延迟分位数
# =============================================================================
class TestVideoLatencyQuantiles:
    """视频抽帧延迟分位数（T2 ffmpeg 子进程路径）。"""

    def test_video_p50_p95_within_contract(self, bridge: RustThumbnailBridge) -> None:
        """逐视频预热后采样：P50 ≤ 0.8s 且 P95 ≤ 3s。"""
        corpus: List[str] = _video_corpus(1 if SMOKE_MODE else VIDEO_FILES_FULL)

        # 预热轮：ffmpeg 能力表 OnceLock + 子进程首启冷开销，不计入统计
        _timed_jpg_calls(bridge, corpus, len(corpus))

        if SMOKE_MODE:
            total: int = VIDEO_SAMPLES_SMOKE
        else:
            total = len(corpus) * VIDEO_PASSES_FULL
        samples: List[float] = _timed_jpg_calls(bridge, corpus, total)

        ordered: List[float] = sorted(samples)
        p50: float = _percentile(ordered, 50.0)
        p95: float = _percentile(ordered, 95.0)
        mean_ms: float = sum(samples) / len(samples)
        names: str = ", ".join(Path(p).name for p in corpus)
        print(
            f"\n视频抽帧延迟 [{names}]: 样本 {len(samples)} | "
            f"P50 {p50:.1f}ms | P95 {p95:.1f}ms | 平均 {mean_ms:.1f}ms | "
            f"最大 {ordered[-1]:.1f}ms"
        )
        _record_baseline(
            "video_latency",
            {
                "samples": len(samples),
                "files": [Path(p).name for p in corpus],
                "p50_ms": round(p50, 3),
                "p95_ms": round(p95, 3),
                "mean_ms": round(mean_ms, 3),
                "max_ms": round(ordered[-1], 3),
                "thresholds": {
                    "p50_ms": VIDEO_P50_LIMIT_MS,
                    "p95_ms": VIDEO_P95_LIMIT_MS,
                },
            },
        )
        assert p50 <= VIDEO_P50_LIMIT_MS, (
            f"视频抽帧 P50 过慢: {p50:.1f}ms (上限 {VIDEO_P50_LIMIT_MS:.0f}ms)"
        )
        assert p95 <= VIDEO_P95_LIMIT_MS, (
            f"视频抽帧 P95 过慢: {p95:.1f}ms (上限 {VIDEO_P95_LIMIT_MS:.0f}ms)"
        )


# =============================================================================
# 批量吞吐
# =============================================================================
class TestBatchThroughput:
    """16 线程并发单张的批量吞吐（预热后计时）。"""

    def test_throughput_16_threads_above_120_ips(
        self, bridge: RustThumbnailBridge, image_corpus: List[str]
    ) -> None:
        """ThreadPoolExecutor(16) 并发生成：吞吐 ≥ 120 张/s。"""
        corpus: List[str] = image_corpus
        rounds: int = THROUGHPUT_ROUNDS_SMOKE if SMOKE_MODE else THROUGHPUT_ROUNDS_FULL
        tasks: List[str] = list(
            itertools.islice(itertools.cycle(corpus), THROUGHPUT_THREADS * rounds)
        )

        def work(path: str) -> None:
            blob, status = bridge.generate_jpg_with_status(
                path, THUMB_SIZE, THUMB_SIZE
            )
            assert status == 0, f"{Path(path).name} 生成失败 status={status}"
            assert blob is not None and blob[:2] == b"\xff\xd8", (
                f"{Path(path).name} 返回非法 JPEG"
            )

        with ThreadPoolExecutor(max_workers=THROUGHPUT_THREADS) as executor:
            # 预热：一轮满并发（rayon 注册表 / 线程池爬坡），不计入统计
            list(executor.map(work, tasks[:THROUGHPUT_THREADS]))
            start: float = time.perf_counter()
            list(executor.map(work, tasks))
            elapsed_s: float = time.perf_counter() - start

        throughput: float = len(tasks) / elapsed_s if elapsed_s > 0 else 0.0
        print(
            f"\n批量吞吐: {len(tasks)} 张 / {elapsed_s:.3f}s @ "
            f"{THROUGHPUT_THREADS} 线程 = {throughput:.1f} 张/s "
            f"(下限 {THROUGHPUT_FLOOR_IPS:.0f})"
        )
        _record_baseline(
            "batch_throughput",
            {
                "threads": THROUGHPUT_THREADS,
                "total_images": len(tasks),
                "elapsed_s": round(elapsed_s, 4),
                "images_per_second": round(throughput, 2),
                "threshold_images_per_second": THROUGHPUT_FLOOR_IPS,
            },
        )
        assert throughput >= THROUGHPUT_FLOOR_IPS, (
            f"批量吞吐过低: {throughput:.1f} 张/s "
            f"(下限 {THROUGHPUT_FLOOR_IPS:.0f} 张/s, {THROUGHPUT_THREADS} 线程)"
        )
