# -*- coding: utf-8 -*-
# targets: core.pools, core.native.api, core.managers.thumbnail_manager
"""P6.6 线程预算实测：取吞吐拐点（4/6/8/12），并测 P3.6 句柄排序延迟。

两个测量：

1. **解码吞吐曲线**（``decode`` 池的线程数依据）。用「PIL 解码 → 缩放 →
   JPEG 编码」模拟缩略图 worker 的纯 CPU 段（与生产 ``_generate_image_thumbnail``
   同构），一组固定图片在 ``workers ∈ WORKER_SWEEP`` 下各跑一次，算吞吐
   加速比。由于这些 worker 全程持 GIL（PIL 在 encode 时释放、decode 时大
   部分释放），曲线会在某个点饱和——饱和点即「拐点」，用于判断 6 线程
   是否合理，而不是拍脑袋取 ``cpu_count``。

2. **句柄排序延迟**（P3.6 验收项 ``10k 排序 P50 ≤ 5ms``）。``dir_open`` →
   ``dir_sort_window`` → ``dir_close`` 的纯 Rust 耗时（不含 Python 侧扫描），
   与纯 Python ``_apply_sort`` 同规模对比。

裁决规则（写入 JSON 的 ``verdict``）：

* 加速比 ``speedup(6) / speedup(12) >= 0.85`` → ``six_is_knee``（6 线程已接近
  饱和，多开无益）；
* 否则 ``more_threads_help``（提示复核预算）。
* 句柄排序 ``P50 <= 5ms`` → ``sort_target_met``。

产物：``build/bench/p06-thread-budget-<ts>.json``（不写 ``baseline/``，
不写用户 ``data/``）。
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

from freeassetfilter.core.native import api as native_api

pytestmark = [pytest.mark.benchmark, pytest.mark.timeout(600)]

#: 线程数扫描点（4 = 保守，6 = 当前 decode 预算，8/12 = 加压对照）。
WORKER_SWEEP: Tuple[int, ...] = (1, 2, 4, 6, 8, 12)
#: 每轮处理的图片数量（固定，用于算吞吐）。
IMAGE_COUNT: int = 48
#: 合成图片边长（512 覆盖常见卡片图，编码成本接近真实缩略图）。
IMAGE_EDGE: int = 512
#: 每档重复次数（取 P50 口径）。
ROUNDS: int = 3
#: 句柄排序规模（P3.6 验收规模）。
SORT_ENTRIES: int = 10000

_OUTPUT_ENV: str = os.environ.get("FAF_BENCH_OUTPUT", "").strip()
if _OUTPUT_ENV:
    _candidate: Path = Path(_OUTPUT_ENV)
    OUTPUT_PATH: Path = (
        _candidate / "p06-thread-budget.json"
        if (_candidate.is_dir() or not _candidate.suffix)
        else _candidate
    )
else:
    OUTPUT_PATH = (
        Path(__file__).resolve().parents[2]
        / "build"
        / "bench"
        / f"p06-thread-budget-{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )

_RESULTS: Dict[str, Any] = {}


def _percentile(sorted_values: List[float], pct: float) -> float:
    """线性插值分位数（与 test_faf_core_perf 同口径）。"""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * pct
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def _encode_one(source: Any) -> int:
    """解码 → 缩放 → 编码（与生产缩略图 worker 的 CPU 段同构）。"""
    from io import BytesIO

    from PIL import Image

    with Image.open(source) as opened:
        thumb = opened.convert("RGB").resize((256, 256), Image.Resampling.BILINEAR)
        buffer = BytesIO()
        thumb.save(buffer, format="JPEG", quality=85)
        return buffer.tell()


def _run_round(paths: List[str], workers: int) -> float:
    """一组图片在 *workers* 线程下跑完的墙钟毫秒。"""
    started = time.perf_counter()
    if workers == 1:
        for path in paths:
            _encode_one(path)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(_encode_one, paths))
    return (time.perf_counter() - started) * 1000.0


@pytest.fixture(scope="module")
def synthetic_images() -> Any:
    """生成 ``IMAGE_COUNT`` 张 512×512 JPEG（模块级复用，测完即删）。"""
    from PIL import Image

    with tempfile.TemporaryDirectory(prefix="faf_p06_") as tmp:
        root = Path(tmp)
        source = Image.new("RGB", (IMAGE_EDGE, IMAGE_EDGE), (48, 96, 144))
        paths: List[str] = []
        for index in range(IMAGE_COUNT):
            path = root / f"img_{index:03d}.jpg"
            source.save(path, format="JPEG", quality=90)
            paths.append(str(path))
        source.close()
        yield paths


def test_decode_throughput_worker_sweep(synthetic_images: List[str]) -> None:
    """扫描 worker 数 → 吞吐曲线，判定 6 线程是否已到拐点。"""
    sweep: Dict[str, Any] = {}
    # 预热：让文件系统缓存与 PIL 初始化成本在两个方案外发生。
    _run_round(synthetic_images[:8], 2)

    baseline_ms: Optional[float] = None
    for workers in WORKER_SWEEP:
        samples = sorted(
            _run_round(synthetic_images, workers) for _ in range(ROUNDS)
        )
        p50 = _percentile(samples, 0.5)
        if baseline_ms is None:
            baseline_ms = p50
        speedup = (baseline_ms or p50) / p50 if p50 > 0 else 0.0
        sweep[str(workers)] = {
            "p50_ms": round(p50, 3),
            "p95_ms": round(_percentile(samples, 0.95), 3),
            "speedup_vs_1": round(speedup, 3),
            "images_per_s": round(IMAGE_COUNT / (p50 / 1000.0), 2) if p50 else 0.0,
        }

    six = float(sweep["6"]["speedup_vs_1"])
    twelve = float(sweep["12"]["speedup_vs_1"])
    ratio = (six / twelve) if twelve > 0 else 0.0
    verdict = "six_is_knee" if ratio >= 0.85 else "more_threads_help"

    _RESULTS["decode_sweep"] = {
        "image_count": IMAGE_COUNT,
        "image_edge": IMAGE_EDGE,
        "rounds": ROUNDS,
        "workers": sweep,
        "speedup_6_over_12": round(ratio, 3),
        "verdict": verdict,
    }
    print(f"\n[P6.6] decode sweep: {json.dumps(sweep, ensure_ascii=False)}", flush=True)
    print(f"[P6.6] verdict={verdict} (6/12={ratio:.3f})", flush=True)


def _make_sort_entries(count: int) -> List[Dict[str, Any]]:
    """构造 ``count`` 条 7 键条目（名称交错大小写 + 平局时间/大小）。"""
    entries: List[Dict[str, Any]] = []
    for index in range(count):
        name = f"Item_{index:05d}_{'A' if index % 2 else 'a'}.txt"
        entries.append(
            {
                "name": name,
                "path": f"C:/bench/{name}",
                "is_dir": index % 7 == 0,
                "size": index % 11,
                "modified": f"2026-01-{index % 28 + 1:02d} 10:00",
                "created": f"2025-12-{index % 28 + 1:02d} 10:00",
                "suffix": "txt",
            }
        )
    return entries


def test_handle_sort_latency_is_windowed(tmp_path: Path) -> None:
    """P3.6：句柄内排序 10k 条目 P50，并与纯 Python 排序对比。"""
    if not native_api.supports("dirhandle"):
        pytest.skip("dirhandle 不可用（旧 DLL），跳过句柄排序延迟测量")

    # 句柄来自目录扫描，因此用 10k 个空文件构造真实目录。
    total = SORT_ENTRIES
    for index in range(total):
        (tmp_path / f"Item_{index:05d}_{'A' if index % 2 else 'a'}.txt").touch()

    native_samples: List[float] = []
    open_samples: List[float] = []
    for round_index in range(ROUNDS):
        started = time.perf_counter()
        handle = native_api.dir_open(str(tmp_path))
        open_samples.append((time.perf_counter() - started) * 1000.0)
        try:
            if handle <= 0:
                pytest.skip("dir_open 失败，跳过句柄排序延迟测量")
            # P3.6 的目标是「排序 + 取窗口」本身，不含扫描；每一轮交替
            # 名称升/降模式，保证待排数据不是上一轮已排好的顺序。
            mode = round_index % 2
            started = time.perf_counter()
            rows = native_api.dir_sort_window(handle, mode, 0, 200)
            native_samples.append((time.perf_counter() - started) * 1000.0)
            assert rows is not None and len(rows) == 200
        finally:
            native_api.dir_close(handle)

    entries = _make_sort_entries(total)
    python_samples: List[float] = []
    for round_index in range(ROUNDS):
        mode = round_index % 2
        started = time.perf_counter()
        ordered = list(entries)
        ordered.sort(
            key=lambda x: (not x["is_dir"], x["name"].lower()),
            reverse=bool(mode),
        )
        window = ordered[:200]
        assert len(window) == 200
        python_samples.append((time.perf_counter() - started) * 1000.0)

    native_samples.sort()
    python_samples.sort()
    open_samples.sort()
    native_p50 = _percentile(native_samples, 0.5)
    python_p50 = _percentile(python_samples, 0.5)
    open_p50 = _percentile(open_samples, 0.5)
    _RESULTS["handle_sort"] = {
        "entries": total,
        "window": 200,
        "native_sort_window_p50_ms": round(native_p50, 3),
        "python_sort_window_p50_ms": round(python_p50, 3),
        "native_open_scan_p50_ms": round(open_p50, 3),
        "ratio": round(native_p50 / python_p50, 3) if python_p50 else 0.0,
        "verdict":
            "sort_target_met" if native_p50 <= 5.0 else "sort_target_missed",
    }
    print(
        f"\n[P3.6] 句柄排序+窗口 P50={native_p50:.3f}ms vs "
        f"Python P50={python_p50:.3f}ms（扫描未计入：{open_p50:.3f}ms）",
        flush=True,
    )


def test_zzz_write_report() -> None:
    """把所有测量写入 JSON（文件名前缀 ``zzz`` 保证最后执行）。"""
    payload: Dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "python": os.sys.version,
    }
    payload.update(_RESULTS)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n[P6.6] 结果已写入 {OUTPUT_PATH}", flush=True)
