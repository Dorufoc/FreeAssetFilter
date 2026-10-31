# -*- coding: utf-8 -*-
# targets: ui.layout.file_selector_layout, core.native.api
"""P3.4 流式扫描实测：native 游标 vs Python 逐批（含首帧延迟）。

两个指标，缺一不可：

* **首帧延迟**（time-to-first-batch）：渐进式加载的核心语义。若 native 必须
  扫完整个目录才发第一批，首帧会从毫秒级退化到几十毫秒——那就不合格。
  本模块用 ``spk_scan_begin`` + 首次 ``spk_scan_next`` 与 Python 首次
  ``yield`` 对比。
* **全量耗时**：同目录读完所有条目的墙钟。

裁决规则（写入 JSON 的 ``verdict``）：

* ``first_batch_ratio <= 2.0`` 且 ``full_ratio <= 0.9`` → ``native_stream_pass``；
* 首个条件不满足 → ``first_frame_regression``（不得默认开启）；
* 仅第二个不满足 → ``no_throughput_gain``。

产物：``build/bench/p34-native-stream-<ts>.json``。
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from sopeek.core.native import api as native_api

pytestmark = [pytest.mark.benchmark, pytest.mark.timeout(600)]

#: 对比规模（覆盖 5k / 10k 两档历史基线）。
SIZES: Tuple[int, ...] = (5000, 10000)
#: 采样次数（取 P50）。
SAMPLES: int = 5
#: 生产批次大小（与 ``_iter_directory_batches`` 默认一致）。
BATCH_SIZE: int = 64

_OUTPUT_ENV: str = os.environ.get("SPK_BENCH_OUTPUT", "").strip()
if _OUTPUT_ENV:
    _candidate: Path = Path(_OUTPUT_ENV)
    OUTPUT_PATH: Path = (
        _candidate / "p34-native-stream.json"
        if (_candidate.is_dir() or not _candidate.suffix)
        else _candidate
    )
else:
    OUTPUT_PATH = (
        Path(__file__).resolve().parents[2]
        / "build"
        / "bench"
        / f"p34-native-stream-{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )

_RESULTS: Dict[str, Any] = {}


def _percentile(sorted_values: List[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * pct
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def _iter_python(path: Path):
    """生产 Python 逐批（oracle）。"""
    from sopeek.ui.layout.file_selector_layout import FileSelectorLayout

    return FileSelectorLayout._iter_directory_batches_python(
        str(path), False, lambda: False, batch_size=BATCH_SIZE
    )


def _measure_python(path: Path) -> Tuple[float, float]:
    """(首帧毫秒, 全量毫秒)。"""
    started = time.perf_counter()
    first = 0.0
    for index, (batch, _final) in enumerate(_iter_python(path)):
        if index == 0:
            first = (time.perf_counter() - started) * 1000.0
        if not batch and _final:
            break
    return first, (time.perf_counter() - started) * 1000.0


def _measure_native(path: Path) -> Tuple[float, float]:
    """(首帧毫秒, 全量毫秒)；游标不可用时返回 (-1, -1)。"""
    started = time.perf_counter()
    handle = native_api.scan_begin(str(path))
    if not handle:
        return -1.0, -1.0
    first = 0.0
    try:
        index = 0
        while True:
            rows = native_api.scan_next(handle, BATCH_SIZE)
            if rows is None:
                break
            if index == 0:
                first = (time.perf_counter() - started) * 1000.0
            index += 1
            if not rows:
                break
    finally:
        native_api.scan_free(handle)
    return first, (time.perf_counter() - started) * 1000.0


@pytest.fixture(scope="module", params=SIZES)
def big_dir(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> Any:
    """生成 ``SIZES`` 规模的临时目录（模块级复用）。"""
    size = int(request.param)
    root = tmp_path_factory.mktemp(f"p34_{size}")
    body = b"x"
    for index in range(size):
        (root / f"file_{index:06d}.txt").write_bytes(body)
    return size, root


def test_native_stream_vs_python(big_dir: Any) -> None:
    """首帧延迟 + 全量耗时：native 游标 vs Python 逐批。"""
    if not native_api.supports("scanstream"):
        pytest.skip("spk_core 缺流式扫描导出，跳过 P3.4 实测")
    size, root = big_dir

    # 预热（文件系统元数据缓存与 ctypes 首次绑定不计入样本）。
    _measure_python(root)
    _measure_native(root)

    py_first: List[float] = []
    py_full: List[float] = []
    na_first: List[float] = []
    na_full: List[float] = []
    for _ in range(SAMPLES):
        first, full = _measure_python(root)
        py_first.append(first)
        py_full.append(full)
        first, full = _measure_native(root)
        if first < 0:
            pytest.skip("扫描游标不可用")
        na_first.append(first)
        na_full.append(full)

    py_first.sort()
    py_full.sort()
    na_first.sort()
    na_full.sort()
    first_ratio = (
        _percentile(na_first, 0.5) / _percentile(py_first, 0.5)
        if _percentile(py_first, 0.5) > 0
        else 0.0
    )
    full_ratio = (
        _percentile(na_full, 0.5) / _percentile(py_full, 0.5)
        if _percentile(py_full, 0.5) > 0
        else 0.0
    )
    if first_ratio > 2.0:
        verdict = "first_frame_regression"
    elif full_ratio <= 0.9:
        verdict = "native_stream_pass"
    else:
        verdict = "no_throughput_gain"

    _RESULTS[str(size)] = {
        "entries": size,
        "batch_size": BATCH_SIZE,
        "native_first_ms_p50": round(_percentile(na_first, 0.5), 3),
        "python_first_ms_p50": round(_percentile(py_first, 0.5), 3),
        "first_ratio": round(first_ratio, 3),
        "native_full_ms_p50": round(_percentile(na_full, 0.5), 3),
        "python_full_ms_p50": round(_percentile(py_full, 0.5), 3),
        "full_ratio": round(full_ratio, 3),
        "verdict": verdict,
    }
    print(
        f"\n[P3.4] {size}: 首帧 native {_percentile(na_first, 0.5):.2f}ms vs "
        f"py {_percentile(py_first, 0.5):.2f}ms（{first_ratio:.2f}×）；"
        f"全量 {_percentile(na_full, 0.5):.1f}ms vs "
        f"{_percentile(py_full, 0.5):.1f}ms（{full_ratio:.2f}×）→ {verdict}",
        flush=True,
    )


def test_zzz_write_report() -> None:
    """写出 JSON（``zzz`` 前缀保证最后执行）。"""
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload: Dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "python": os.sys.version,
    }
    payload.update(_RESULTS)
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n[P3.4] 结果已写入 {OUTPUT_PATH}", flush=True)
