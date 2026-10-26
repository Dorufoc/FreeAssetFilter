# -*- coding: utf-8 -*-
# targets: core.native.bridges.faf_core_bridge, ui.layout.file_selector_layout
"""P0.3 目录扫描四臂对比：消解「native 是否更快」的历史矛盾。

背景：仓库里有两份互相矛盾的基线——

* ``task-22``（2026-09-24，5k）：native 116.668ms vs Python 849.516ms → 7.281×
* 旧 ``baseline/faf-core-perf.json``（2026-10-17，10k）：
  native 382.03ms vs Python 116.798ms → 0.306×（``passed: false``）

两者测的是同一份 ``scan.rs``（该文件只有创建提交 ``19e6bb4``），差异必然
来自测量口径或机器状态。本模块用**同一目录、同一预热策略、交错采样**重测
四条臂，产出可裁决的数字。

四臂定义：

============ ============================================================
臂           实现
============ ============================================================
``native``   ``bridge.scan_directory`` → Rust ``faf_scan_directory``
``py_single``  ``FileSelectorLayout._collect_directory_entries_python``
              （1 次 ``os.scandir`` + 逐项 ``stat(follow=True)`` + 2×strftime）
``py_double``  ``py_single`` + ``_apply_hidden_system_filter``
              （生产默认口径：额外 1 次 ``os.scandir`` 取属性位）
``py_onepass`` 单次 ``os.scandir`` 同时产出 7 键 + ``st_file_attributes``
              （P1.3 的目标形态，尚未落地）
============ ============================================================

裁决规则（写入 JSON 的 ``verdict``）：

* ``native`` vs ``py_single``：``>1.1×`` → ``native_blocked``；
  ``0.9–1.1×`` → ``native_experimental``；``<0.9×`` → ``native_pass``。
* ``py_onepass`` vs ``py_double``：节省比例 ≥ 20% → ``onepass_worthwhile``。

产物：``build/bench/p03-scan-three-arm-<ts>.json``（不写 ``baseline/``，
不写用户 ``data/``）。
"""

from __future__ import annotations

import json
import os
import platform
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

from freeassetfilter.core.native.bridges.faf_core_bridge import (
    FafCoreBridge,
    get_faf_core_bridge,
)

#: 布局模块内部使用短路径导入（``from theme import tm`` 等），要求
#: ``freeassetfilter/ui`` 位于 sys.path（与 test_faf_core_perf.py 一致）。
_UI_ROOT: str = str(Path(__file__).resolve().parents[2] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from freeassetfilter.ui.layout.file_selector_layout import FileSelectorLayout

pytestmark = [pytest.mark.benchmark, pytest.mark.timeout(300)]

#: 对比规模（对齐两份历史基线：task-22 用 5k，旧 baseline 用 10k）。
SCAN_SIZES: Tuple[int, ...] = (5000, 10000)
#: 热态交错采样次数。
SAMPLES: int = 5
#: 单文件内容（5 行，约 30 字节）。
_FILE_BODY: bytes = b"x = 1\n" * 5

#: 输出路径（P0.2 产物隔离：默认 build/bench/）。
_OUTPUT_ENV: str = os.environ.get("FAF_BENCH_OUTPUT", "").strip()
if _OUTPUT_ENV:
    _candidate: Path = Path(_OUTPUT_ENV)
    OUTPUT_PATH: Path = (
        _candidate / "p03-scan-three-arm.json"
        if (_candidate.is_dir() or not _candidate.suffix)
        else _candidate
    )
else:
    OUTPUT_PATH = (
        Path(__file__).resolve().parents[2]
        / "build"
        / "bench"
        / f"p03-scan-three-arm-{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )

#: 模块级累积器。
_RESULTS: Dict[str, Any] = {}


def _percentile(sorted_values: List[float], pct: float) -> float:
    """线性插值分位数（与 test_faf_core_perf._percentile 同口径）。"""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank: float = (len(sorted_values) - 1) * (pct / 100.0)
    lo: int = int(rank)
    hi: int = min(lo + 1, len(sorted_values) - 1)
    frac: float = rank - lo
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


def _stats_ms(samples: List[float]) -> Dict[str, float]:
    """样本统计（P50/P95/mean/max，毫秒）。"""
    ordered: List[float] = sorted(samples)
    return {
        "p50_ms": round(_percentile(ordered, 50.0) * 1000.0, 3),
        "p95_ms": round(_percentile(ordered, 95.0) * 1000.0, 3),
        "mean_ms": round(sum(samples) / len(samples) * 1000.0, 3),
        "max_ms": round(ordered[-1] * 1000.0, 3),
    }


def _machine_summary() -> Dict[str, Any]:
    """机器指纹（跨机器对比时必须先比对这组字段）。"""
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
    }


def _single_pass_scan(path: str) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """目标形态：单次 ``os.scandir`` 同时产出 7 键条目与属性位旁路表。

    与生产双遍路径的语义对齐：

    * 7 键字段与 ``_entry_from_direntry`` 逐字段一致（``follow_symlinks=True``）；
    * ``attrs`` 与 ``_hidden_system_attrs_map`` 同口径（``follow_symlinks=False``）。

    Windows 上 ``follow_symlinks=False`` 直接读取 ``read_dir`` 缓存的
    ``WIN32_FIND_DATA``，不产生额外 syscall——这是单遍收益的来源。

    Args:
        path: 目录绝对路径。

    Returns:
        ``(entries, attrs_by_name)``；目录不可读时抛出 ``OSError``（由调用方处理）。
    """
    entries: List[Dict[str, Any]] = []
    attrs_by_name: Dict[str, int] = {}
    with os.scandir(path) as it:
        for dir_entry in it:
            try:
                st = dir_entry.stat(follow_symlinks=True)
                st_no_follow = dir_entry.stat(follow_symlinks=False)
            except OSError:
                continue
            is_dir: bool = dir_entry.is_dir(follow_symlinks=True)
            name: str = dir_entry.name
            suffix: str = "" if is_dir else os.path.splitext(name)[1].lower().lstrip(".")
            entries.append(
                {
                    "name": name,
                    "path": dir_entry.path,
                    "is_dir": is_dir,
                    "size": st.st_size,
                    "modified": datetime.fromtimestamp(st.st_mtime).strftime(
                        "%Y-%m-%d %H:%M"
                    ),
                    "created": datetime.fromtimestamp(st.st_ctime).strftime(
                        "%Y-%m-%d %H:%M"
                    ),
                    "suffix": suffix,
                }
            )
            attrs_by_name[name] = getattr(st_no_follow, "st_file_attributes", 0)
    return entries, attrs_by_name


def _canonical(entries: List[Dict[str, Any]]) -> List[Tuple[Any, ...]]:
    """把条目归一为可按名称排序的指纹（用于逐字段对拍）。"""
    keys: Tuple[str, ...] = ("name", "path", "is_dir", "size", "modified", "created", "suffix")
    return sorted(
        tuple(entry.get(key) for key in keys) for entry in entries
    )


@pytest.fixture(scope="module")
def bridge() -> FafCoreBridge:
    """共享原生桥；DLL 不可用时跳过 native 臂相关断言。"""
    inst: Optional[FafCoreBridge] = get_faf_core_bridge()
    if inst is None or not inst.available:
        pytest.skip("faf_core.dll 不可用，跳过扫描四臂对比")
    return inst


@pytest.fixture(scope="module")
def scan_dirs(tmp_path_factory: Any) -> Dict[int, str]:
    """为每个规模创建独立临时目录（会话结束自动清理）。"""
    created: Dict[int, str] = {}
    for count in SCAN_SIZES:
        workdir: Path = tmp_path_factory.mktemp(f"p03_scan_{count}")
        for i in range(count):
            (workdir / f"file_{i:05d}.py").write_bytes(_FILE_BODY)
        created[count] = str(workdir)
        print(f"\n[P0.3] 语料 {count} 文件 @ {workdir}", flush=True)
    return created


def _time_call(func: Any) -> float:
    """执行一次调用并返回秒级耗时。"""
    start: float = time.perf_counter()
    func()
    return time.perf_counter() - start


def _run_case(bridge: FafCoreBridge, path: str, files: int) -> Dict[str, Any]:
    """对单个目录跑四臂交错采样，返回结构化结果。"""
    native_scan = bridge.scan_directory

    def arm_native() -> None:
        result = native_scan(path)
        assert result is not None, "native 扫描返回 None（应 FAIL）"
        assert len(result) == files

    def arm_py_single() -> None:
        result = FileSelectorLayout._collect_directory_entries_python(path)
        assert result is not None and len(result) == files

    def arm_py_double() -> None:
        entries = FileSelectorLayout._collect_directory_entries_python(path)
        assert entries is not None
        filtered = FileSelectorLayout._apply_hidden_system_filter(
            entries, path, False, False
        )
        assert len(filtered) <= files

    def arm_py_onepass() -> None:
        entries, attrs = _single_pass_scan(path)
        assert len(entries) == files
        visible = [
            e
            for e in entries
            if not (attrs.get(e["name"], 0) & 0x2)  # FILE_ATTRIBUTE_HIDDEN
        ]
        assert len(visible) <= files

    arms: Dict[str, Any] = {
        "native": arm_native,
        "py_single": arm_py_single,
        "py_double": arm_py_double,
        "py_onepass": arm_py_onepass,
    }

    # 预热轮：DLL 惰性初始化 / 首次 stat 冷缓存，不计入统计。
    cold: Dict[str, float] = {}
    for name, func in arms.items():
        cold[name] = 0.0
    # 冷态只在「首个臂的第一次调用」有意义；其余臂此时已被缓存影响，
    # 故只记录首个臂（native）的首次耗时作参考，并显式标注口径。
    cold["native_first_ms"] = round(_time_call(arm_native) * 1000.0, 3)
    for name, func in arms.items():
        if name == "native":
            continue
        _time_call(func)

    samples: Dict[str, List[float]] = {name: [] for name in arms}
    for _ in range(SAMPLES):
        for name, func in arms.items():
            samples[name].append(_time_call(func))

    stats: Dict[str, Dict[str, float]] = {
        name: _stats_ms(values) for name, values in samples.items()
    }

    # 正确性对拍：native / py_single / py_onepass 的 7 键字段必须逐条相等。
    native_entries = native_scan(path) or []
    py_entries = FileSelectorLayout._collect_directory_entries_python(path) or []
    onepass_entries, onepass_attrs = _single_pass_scan(path)
    parity_native_vs_py: bool = _canonical(native_entries) == _canonical(py_entries)
    parity_onepass_vs_py: bool = _canonical(onepass_entries) == _canonical(py_entries)
    oracle_attrs: Optional[Dict[str, int]] = FileSelectorLayout._hidden_system_attrs_map(
        path, False, False
    )
    parity_attrs: bool = (
        oracle_attrs is not None
        and {k: v for k, v in onepass_attrs.items() if k in oracle_attrs}
        == {k: v for k, v in oracle_attrs.items() if k in onepass_attrs}
    )

    native_p50: float = stats["native"]["p50_ms"]
    py_single_p50: float = stats["py_single"]["p50_ms"]
    double_p50: float = stats["py_double"]["p50_ms"]
    onepass_p50: float = stats["py_onepass"]["p50_ms"]

    native_speedup: float = py_single_p50 / native_p50 if native_p50 else 0.0
    if native_p50 > py_single_p50 * 1.1:
        native_verdict: str = "native_blocked"
    elif native_p50 <= py_single_p50 * 0.9:
        native_verdict = "native_pass"
    else:
        native_verdict = "native_experimental"

    onepass_saving_pct: float = (
        (double_p50 - onepass_p50) / double_p50 * 100.0 if double_p50 else 0.0
    )
    onepass_verdict: str = (
        "onepass_worthwhile" if onepass_saving_pct >= 20.0 else "onepass_marginal"
    )

    print(
        f"[P0.3] {files} 文件 | native {native_p50:.1f}ms | "
        f"py_single {py_single_p50:.1f}ms | py_double {double_p50:.1f}ms | "
        f"py_onepass {onepass_p50:.1f}ms | native/py = {native_speedup:.3f}x "
        f"({native_verdict}) | onepass 省 {onepass_saving_pct:.1f}% "
        f"({onepass_verdict})",
        flush=True,
    )

    return {
        "files": files,
        "samples_per_arm": SAMPLES,
        "arms": stats,
        "cold_native_first_ms": cold["native_first_ms"],
        "parity": {
            "native_vs_py_single": parity_native_vs_py,
            "onepass_vs_py_single": parity_onepass_vs_py,
            "onepass_attrs_vs_oracle": parity_attrs,
        },
        "comparison": {
            "native_vs_py_single_x": round(native_speedup, 3),
            "native_verdict": native_verdict,
            "py_double_vs_onepass_x": round(
                double_p50 / onepass_p50 if onepass_p50 else 0.0, 3
            ),
            "onepass_saving_pct": round(onepass_saving_pct, 2),
            "onepass_verdict": onepass_verdict,
        },
    }


def test_scan_four_arms_across_sizes(
    bridge: FafCoreBridge, scan_dirs: Dict[int, str]
) -> None:
    """对 5k / 10k 两个规模跑四臂对比，并落盘 JSON。"""
    cases: List[Dict[str, Any]] = []
    for files in SCAN_SIZES:
        cases.append(_run_case(bridge, scan_dirs[files], files))

    _RESULTS["cases"] = cases

    # 硬约束：7 键字段对拍必须通过（不改契约）。
    for case in cases:
        assert case["parity"]["native_vs_py_single"], (
            f"native 与 Python 7 键字段不一致（{case['files']} 文件）"
        )
        assert case["parity"]["onepass_vs_py_single"], (
            f"单遍与 Python 7 键字段不一致（{case['files']} 文件）"
        )
        assert case["parity"]["onepass_attrs_vs_oracle"], (
            f"单遍 attrs 与 oracle 不一致（{case['files']} 文件）"
        )


def test_zzz_write_report() -> None:
    """把四臂结果写入 JSON（文件名排序保证最后执行）。"""
    document: Dict[str, Any] = {
        "schema": "faf-scan-three-arm/v1",
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "machine": _machine_summary(),
        "sizes": list(SCAN_SIZES),
        "samples_per_arm": SAMPLES,
    }
    document.update(_RESULTS)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\n[P0.3] 结果已写入 {OUTPUT_PATH}", flush=True)
