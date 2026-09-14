# -*- coding: utf-8 -*-
# targets: core.native.bridges.faf_core_bridge,
#          ui.layout.file_selector_layout, utils.syntax_highlighter,
#          services.file_info_service
"""faf_core 原生核心性能基准（faf-core-rust-migration todo 32）。

锁定五条 faf_core 主路径的耗时/吞吐口径，全部以「native vs Python 基线」
对照方式记录并落盘基线 JSON（``tests/benchmark/baseline/faf-core-perf.json``）：

* **目录扫描**（10k 文件临时目录）：P50/P95——native
  （``_native_scan_directory`` → ``faf_scan_directory``）vs Python 基线
  （``FileSelectorLayout._collect_directory_entries_python``，listdir+stat）；
* **大文件高亮**（≥1000 行，3000 行 Python 合成样本）：P50/P95——native
  整块（``FafCoreHighlighter.highlight_text`` → ``faf_highlight_text``）
  vs Python 基线（``PygmentsHighlighter`` 逐行，即 app 在 DLL 缺失时的回退链）；
* **哈希吞吐**（流式 256KiB 块，32MiB 文件）：吞吐 MB/s + P50——native
  （``bridge.hash_file_streaming`` → ``faf_hash_init/update/final``）
  vs Python 基线（``file_info_service.compute_hashes``，hashlib 同块口径）；
* **复制吞吐**（16 × 512KiB 源文件）：吞吐 MB/s + P50——native
  （``bridge.copy_files`` → ``faf_copy_files``，rayon 并行）
  vs Python 基线（``shutil.copy2`` 逐文件，即 app 的 Python 复制路径）；
* **>8MB JSON 上限回退路径耗时**：构造 30k 条 in-memory 条目（载荷 ≈12.5MiB，
  超 ``MAX_JSON_BYTES``），测量 (a) native ``sort_entries`` 的 8MB 守卫拒绝
  耗时（桥内显式 ``MAX_JSON_BYTES`` 检查，faf_core_bridge.py L446-450）与
  (b) Python 回退排序耗时（``_apply_sort`` mode-2 同款 key，逐字对齐
  file_selector_layout.py L1452）；cap 回退全路径不得抛异常。

  说明：扫描路径的 8MB 上限守卫在 Rust 侧（``scan.rs`` 内建
  ``STATUS_TOO_LARGE``），需约 3 万+ 文件目录才能触发——基准每轮全量运行
  都要建目录，成本过高，故本基准以「桥内显式守卫」的 sort 路径作为真实
  超限触发器（计划允许 mock 或真实构造超限目录），Python 回退排序耗时即为
  用户在超限场景下实际等待的 Python 回退成本。

断言纪律（计划原文，性能是记录性指标）：
* **精确断言** ``P50_native <= P50_python * 1.2``——native 快于或接近基线；
  不达标只打印 WARN 并继续（exit 0），**不 FAIL**；
* 失败条件只针对：崩溃/异常、native 在正常数据上返回 ``None``、cap 回退
  路径抛异常。

冒烟降级：设 ``FAF_BENCH_SMOKE=1`` 时以 5 样本快速模式运行（CI 冒烟门控，
阈值不变、仅缩样本与数据规模）。

基准落盘：每次运行把 P50/P95/吞吐/时间戳/机器摘要写入
``tests/benchmark/baseline/faf-core-perf.json``（仅记录，不触发 git 操作）。
"""

from __future__ import annotations

import json
import math
import os
import platform
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pytest

from freeassetfilter.core.native.bridges.faf_core_bridge import (
    FafCoreBridge,
    get_faf_core_bridge,
)

#: 布局模块内部使用短路径导入（from theme import tm / components.*），要求
#: freeassetfilter/ui 位于 sys.path（与 test_layouts.py:50-52 bootstrap 一致）。
_UI_ROOT: str = str(
    Path(__file__).resolve().parents[2] / "freeassetfilter" / "ui"
)
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from freeassetfilter.services.file_info_service import compute_hashes
from freeassetfilter.ui.layout.file_selector_layout import (
    FileSelectorLayout,
    _native_scan_directory,
    _native_sort_entries,
)
from freeassetfilter.utils.syntax_highlighter import (
    FafCoreHighlighter,
    PygmentsHighlighter,
)

pytestmark = [pytest.mark.benchmark, pytest.mark.timeout(300)]

#: 冒烟模式开关（FAF_BENCH_SMOKE=1 时启用 5 样本快速断言）。
_SMOKE_ENV: str = os.environ.get("FAF_BENCH_SMOKE", "").strip().lower()
SMOKE_MODE: bool = _SMOKE_ENV not in ("", "0", "false", "no")

# --- native vs Python 对照断言系数（计划原文：P50_native <= P50_python*1.2）---
#: WARN-only 对比系数；不达标仅 WARN，不 FAIL。
PERF_RATIO: float = 1.2

# --- 样本规模 ---
#: 全量模式目录扫描文件数。
SCAN_FILES_FULL: int = 10000
#: 冒烟模式目录扫描文件数。
SCAN_FILES_SMOKE: int = 5000
#: 目录扫描计时样本数（native+python 交错对）。
SCAN_SAMPLES_FULL: int = 5
SCAN_SAMPLES_SMOKE: int = 5
#: 高亮样本迭代次数（每次迭代产出 3 行 → 全量 3000 行，满足 ≥1000 行要求）。
HIGHLIGHT_ITERS: int = 1000
#: 高亮计时样本数。
HIGHLIGHT_SAMPLES_FULL: int = 5
HIGHLIGHT_SAMPLES_SMOKE: int = 5
#: 哈希吞吐文件体积（MiB）。
HASH_MIB: int = 32
#: 哈希计时样本数。
HASH_SAMPLES_FULL: int = 5
HASH_SAMPLES_SMOKE: int = 3
#: 复制源文件数量与单文件体积（字节）。
COPY_FILES: int = 16
COPY_FILE_BYTES: int = 512 * 1024
#: 复制计时样本数。
COPY_SAMPLES_FULL: int = 5
COPY_SAMPLES_SMOKE: int = 3
#: >8MB 上限回退测试的 in-memory 条目数（≈12.5MiB 载荷，稳定超过 8MiB）。
CAP_ENTRIES: int = 30000
#: cap 回退计时样本数。
CAP_SAMPLES_FULL: int = 3
CAP_SAMPLES_SMOKE: int = 2

#: 基准 JSON 落盘路径。
BASELINE_PATH: Path = (
    Path(__file__).resolve().parent / "baseline" / "faf-core-perf.json"
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


def _stats_ms(samples: Sequence[float]) -> Dict[str, float]:
    """样本升序统计（P50/P95/mean/max，毫秒）。

    Args:
        samples: 耗时样本列表（秒）。

    Returns:
        dict[str, float]: ``p50_ms`` / ``p95_ms`` / ``mean_ms`` / ``max_ms``。
    """
    ordered: List[float] = sorted(samples)
    return {
        "p50_ms": round(_percentile(ordered, 50.0) * 1000.0, 3),
        "p95_ms": round(_percentile(ordered, 95.0) * 1000.0, 3),
        "mean_ms": round(sum(samples) / len(samples) * 1000.0, 3),
        "max_ms": round(ordered[-1] * 1000.0, 3),
    }


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
        section: 小节名（scan_directory / highlight / hash_throughput /
            copy_throughput / overlimit_fallback）。
        payload: 该小节的指标字典。
    """
    _BASELINE[section] = payload
    document: Dict[str, Any] = {
        "schema": "faf-core-perf-baseline/v1",
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "smoke" if SMOKE_MODE else "full",
        "machine": _machine_summary(),
    }
    document.update(_BASELINE)
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _check_native_vs_python(
    p50_native_ms: float,
    p50_python_ms: float,
    section: str,
) -> Dict[str, Any]:
    """应用计划精确断言 ``P50_native <= P50_python * 1.2``（WARN-only）。

    不达标只打印 WARN 并记录实际值，**不 raise**——性能为记录性指标；
    崩溃/异常才 FAIL。返回值写回基准 JSON 的 assertion 字段。

    Args:
        p50_native_ms: native 路径 P50 耗时（毫秒）。
        p50_python_ms: Python 基线 P50 耗时（毫秒）。
        section: 指标名（用于 WARN 文案）。

    Returns:
        dict[str, Any]: ``rule`` / ``p50_native_ms`` / ``p50_python_ms`` /
            ``limit_ms`` / ``passed`` 五字段。
    """
    limit_ms: float = round(p50_python_ms * PERF_RATIO, 3)
    passed: bool = p50_native_ms <= limit_ms
    if passed:
        print(
            f"[OK] {section}: P50_native {p50_native_ms:.2f}ms <= "
            f"P50_python*{PERF_RATIO} {limit_ms:.2f}ms"
        )
    else:
        print(
            f"[WARN] {section}: P50_native {p50_native_ms:.2f}ms > "
            f"P50_python*{PERF_RATIO} {limit_ms:.2f}ms "
            f"— 性能为记录性指标，不 FAIL（记录实际值）"
        )
    return {
        "rule": f"P50_native <= P50_python*{PERF_RATIO}",
        "p50_native_ms": round(p50_native_ms, 3),
        "p50_python_ms": round(p50_python_ms, 3),
        "limit_ms": limit_ms,
        "passed": passed,
    }


def _python_sort_mode2(entries: List[Dict[str, Any]]) -> None:
    """``_apply_sort`` mode-2 分支逐字回退（file_selector_layout.py L1452）。

    与 ``_apply_sort`` 排序管线逐字节一致：``(not is_dir, modified)`` 倒序。
    用于 >8MB 上限回退路径的 Python 侧耗时测量。

    Args:
        entries: 7 键条目列表（就地修改）。
    """
    entries.sort(
        key=lambda x: (not x["is_dir"], x.get("modified", "")), reverse=True
    )


# =============================================================================
# 数据 fixture（全部落在临时目录，绝不触碰真实 data/）
# =============================================================================
@pytest.fixture(scope="module")
def bridge() -> FafCoreBridge:
    """模块级共享原生桥实例；DLL 不可用时跳过整个基准。

    Returns:
        FafCoreBridge: 已确认 ``available`` 的桥实例。
    """
    inst: Optional[FafCoreBridge] = get_faf_core_bridge()
    if inst is None or not inst.available:
        pytest.skip("faf_core.dll 不可用，跳过 faf_core 原生基准")
    return inst


@pytest.fixture(scope="module")
def big_dir(tmp_path_factory: Any) -> str:
    """10k（冒烟 5k）文件的临时目录（目录扫描基准语料）。

    Args:
        tmp_path_factory: pytest 会话级临时目录工厂。

    Returns:
        str: 目录绝对路径。
    """
    count: int = SCAN_FILES_SMOKE if SMOKE_MODE else SCAN_FILES_FULL
    workdir: Path = tmp_path_factory.mktemp("faf_bench_scan")
    body: bytes = b"x = 1\n" * 5
    for i in range(count):
        (workdir / f"file_{i:05d}.py").write_bytes(body)
    print(f"\n扫描语料: {count} 文件 @ {workdir}")
    return str(workdir)


@pytest.fixture(scope="module")
def highlight_corpus() -> str:
    """3000 行 Python 合成代码（≥1000 行要求），整块高亮语料。

    Returns:
        str: 代码文本。
    """
    lines: List[str] = []
    for i in range(HIGHLIGHT_ITERS):
        lines.append(f"def func_{i}(a, b):")
        lines.append(f"    # comment {i}")
        lines.append(f"    return a + b  # tail {i}")
    return "\n".join(lines) + "\n"


@pytest.fixture(scope="module")
def hash_file(tmp_path_factory: Any) -> str:
    """32MiB 确定性内容文件（哈希吞吐基准语料）。

    Args:
        tmp_path_factory: pytest 会话级临时目录工厂。

    Returns:
        str: 文件绝对路径。
    """
    workdir: Path = tmp_path_factory.mktemp("faf_bench_hash")
    target: Path = workdir / "blob.bin"
    blob: bytes = bytes(range(256)) * (4096 * HASH_MIB)  # 256B * 4096*32 = 32MiB
    with open(target, "wb") as fh:
        fh.write(blob)
    return str(target)


@pytest.fixture(scope="module")
def copy_sources(tmp_path_factory: Any) -> Tuple[List[str], Path]:
    """16 × 512KiB 源文件（复制吞吐基准语料，总量 8MiB）。

    Args:
        tmp_path_factory: pytest 会话级临时目录工厂。

    Returns:
        tuple[list[str], Path]: 源文件路径列表 + 源目录（供目标目录同盘
            放置，保证吞吐可比）。
    """
    workdir: Path = tmp_path_factory.mktemp("faf_bench_copy")
    src_dir: Path = workdir / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    for i in range(COPY_FILES):
        with open(src_dir / f"f{i:02d}.bin", "wb") as fh:
            fh.write(os.urandom(COPY_FILE_BYTES))
    sources: List[str] = [str(p) for p in src_dir.iterdir()]
    print(f"\n复制语料: {len(sources)} 文件 @ {src_dir}")
    return sources, workdir


# =============================================================================
# 目录扫描（10k 文件）P50/P95
# =============================================================================
class TestDirectoryScan:
    """目录扫描延迟分位数（native ``faf_scan_directory`` vs Python listdir+stat）。"""

    def test_scan_10k_p50_p95_native_vs_python(
        self, bridge: FafCoreBridge, big_dir: str
    ) -> None:
        """预热后交错采样：native P50 须 ≤ Python 基线 × 1.2（WARN-only）。"""
        if not bridge._supports_scan:
            pytest.skip("faf_core 无 scan 导出，跳过目录扫描基准")

        # 预热轮：DLL 惰性初始化 / 首次 stat 冷缓存，不计入统计
        _native_scan_directory(big_dir)
        FileSelectorLayout._collect_directory_entries_python(big_dir)

        samples: int = SCAN_SAMPLES_SMOKE if SMOKE_MODE else SCAN_SAMPLES_FULL
        native_ms: List[float] = []
        python_ms: List[float] = []
        for _ in range(samples):
            start: float = time.perf_counter()
            native: Optional[List[Dict[str, Any]]] = _native_scan_directory(big_dir)
            native_ms.append(time.perf_counter() - start)
            # 正常数据上 native 返回 None 属真实失败 → FAIL
            assert native is not None, "native 目录扫描返回 None（应 FAIL）"
            assert len(native) == len(os.listdir(big_dir))

            start = time.perf_counter()
            py: Optional[List[Dict[str, Any]]] = (
                FileSelectorLayout._collect_directory_entries_python(big_dir)
            )
            python_ms.append(time.perf_counter() - start)
            assert py is not None and len(py) == len(native)

        n_stats: Dict[str, float] = _stats_ms(native_ms)
        p_stats: Dict[str, float] = _stats_ms(python_ms)
        speedup_p50: float = (
            p_stats["p50_ms"] / n_stats["p50_ms"] if n_stats["p50_ms"] else 0.0
        )
        assertion: Dict[str, Any] = _check_native_vs_python(
            n_stats["p50_ms"], p_stats["p50_ms"], "目录扫描"
        )
        print(
            f"目录扫描(10k): 样本 {samples} | "
            f"native P50 {n_stats['p50_ms']:.1f}ms/P95 {n_stats['p95_ms']:.1f}ms | "
            f"python P50 {p_stats['p50_ms']:.1f}ms/P95 {p_stats['p95_ms']:.1f}ms | "
            f"P50 加速 {speedup_p50:.2f}x"
        )
        _record_baseline(
            "scan_directory",
            {
                "files": len(os.listdir(big_dir)),
                "samples": samples,
                "native": n_stats,
                "python": p_stats,
                "p50_speedup_x": round(speedup_p50, 3),
                "assertion": assertion,
            },
        )


# =============================================================================
# 大文件高亮（≥1000 行）
# =============================================================================
class TestLargeFileHighlight:
    """大文件（3000 行）语法高亮延迟（native 整块 vs Pygments 逐行）。"""

    def test_highlight_3000_lines_p50_p95_native_vs_python(
        self, bridge: FafCoreBridge, highlight_corpus: str
    ) -> None:
        """预热后交错采样：native P50 须 ≤ Python 基线 × 1.2（WARN-only）。"""
        if not bridge._supports_highlight:
            pytest.skip("faf_core 无 highlight 导出，跳过高亮基准")

        native_engine: FafCoreHighlighter = FafCoreHighlighter()
        python_engine: PygmentsHighlighter = PygmentsHighlighter()

        # 预热轮：syntect 语法表 / Pygments 词法缓存，不计入统计
        native_engine.highlight_text(highlight_corpus, "python")
        python_engine.highlight_line("def warm(a):  # warm", "python")

        samples: int = (
            HIGHLIGHT_SAMPLES_SMOKE if SMOKE_MODE else HIGHLIGHT_SAMPLES_FULL
        )
        native_ms: List[float] = []
        python_ms: List[float] = []
        for _ in range(samples):
            start: float = time.perf_counter()
            blocks: List[List[Any]] = native_engine.highlight_text(
                highlight_corpus, "python"
            )
            native_ms.append(time.perf_counter() - start)
            # 正常文本上 native 返回 None / 空 → 真实失败 → FAIL
            assert blocks is not None and len(blocks) > 0

            start = time.perf_counter()
            py_blocks: List[List[Any]] = [
                python_engine.highlight_line(line, "python")
                for line in highlight_corpus.split("\n")
            ]
            python_ms.append(time.perf_counter() - start)
            assert len(py_blocks) == len(blocks)

        n_stats: Dict[str, float] = _stats_ms(native_ms)
        p_stats: Dict[str, float] = _stats_ms(python_ms)
        speedup_p50: float = (
            p_stats["p50_ms"] / n_stats["p50_ms"] if n_stats["p50_ms"] else 0.0
        )
        assertion: Dict[str, Any] = _check_native_vs_python(
            n_stats["p50_ms"], p_stats["p50_ms"], "大文件高亮"
        )
        lines: int = highlight_corpus.count("\n")
        print(
            f"大文件高亮({lines} 行): 样本 {samples} | "
            f"native P50 {n_stats['p50_ms']:.1f}ms/P95 {n_stats['p95_ms']:.1f}ms | "
            f"python P50 {p_stats['p50_ms']:.1f}ms/P95 {p_stats['p95_ms']:.1f}ms | "
            f"P50 加速 {speedup_p50:.2f}x"
        )
        _record_baseline(
            "highlight",
            {
                "lines": lines,
                "chars": len(highlight_corpus),
                "samples": samples,
                "native": n_stats,
                "python": p_stats,
                "p50_speedup_x": round(speedup_p50, 3),
                "assertion": assertion,
            },
        )


# =============================================================================
# 哈希吞吐（流式 256KiB 块）
# =============================================================================
class TestHashThroughput:
    """32MiB 文件三哈希吞吐（native ``faf_hash_*`` vs hashlib）。"""

    def test_hash_streaming_throughput_native_vs_python(
        self, bridge: FafCoreBridge, hash_file: str
    ) -> None:
        """预热后交错采样：native P50 ≤ Python × 1.2（WARN-only）；吞吐记录。"""
        if not bridge._supports_hash:
            pytest.skip("faf_core 无 hash 导出，跳过哈希吞吐基准")

        size_bytes: int = os.path.getsize(hash_file)

        # 预热轮：句柄注册表 / 页缓存爬坡，不计入统计
        first_native: Optional[Dict[str, str]] = bridge.hash_file_streaming(hash_file)
        assert first_native is not None, "native 哈希返回 None（应 FAIL）"
        compute_hashes(hash_file)
        assert first_native == compute_hashes(hash_file)

        samples: int = HASH_SAMPLES_SMOKE if SMOKE_MODE else HASH_SAMPLES_FULL
        native_s: List[float] = []
        python_s: List[float] = []
        for _ in range(samples):
            start: float = time.perf_counter()
            result: Optional[Dict[str, str]] = bridge.hash_file_streaming(hash_file)
            native_s.append(time.perf_counter() - start)
            assert result is not None and result == first_native

            start = time.perf_counter()
            py_result: Dict[str, str] = compute_hashes(hash_file)
            python_s.append(time.perf_counter() - start)
            assert py_result == first_native

        n_stats: Dict[str, float] = _stats_ms(native_s)
        p_stats: Dict[str, float] = _stats_ms(python_s)
        n_mib_s: float = (size_bytes / 2**20) / (
            n_stats["p50_ms"] / 1000.0
        ) if n_stats["p50_ms"] else 0.0
        p_mib_s: float = (size_bytes / 2**20) / (
            p_stats["p50_ms"] / 1000.0
        ) if p_stats["p50_ms"] else 0.0
        assertion: Dict[str, Any] = _check_native_vs_python(
            n_stats["p50_ms"], p_stats["p50_ms"], "哈希吞吐"
        )
        print(
            f"哈希吞吐({size_bytes // 2**20}MiB): 样本 {samples} | "
            f"native P50 {n_stats['p50_ms']:.1f}ms ({n_mib_s:.0f} MiB/s) | "
            f"python P50 {p_stats['p50_ms']:.1f}ms ({p_mib_s:.0f} MiB/s)"
        )
        _record_baseline(
            "hash_throughput",
            {
                "file_mib": size_bytes / 2**20,
                "chunk_bytes": 256 * 1024,
                "samples": samples,
                "native": {**n_stats, "mib_per_sec_p50": round(n_mib_s, 2)},
                "python": {**p_stats, "mib_per_sec_p50": round(p_mib_s, 2)},
                "assertion": assertion,
            },
        )


# =============================================================================
# 复制吞吐（native rayon vs shutil.copy2）
# =============================================================================
class TestCopyThroughput:
    """16 × 512KiB 批量复制吞吐（native ``faf_copy_files`` vs ``shutil.copy2``）。"""

    def test_copy_throughput_native_vs_python(
        self,
        bridge: FafCoreBridge,
        copy_sources: Tuple[List[str], Path],
    ) -> None:
        """预热后交错采样：native P50 ≤ Python × 1.2（WARN-only）；吞吐记录。"""
        if not bridge._supports_copy:
            pytest.skip("faf_core 无 copy 导出，跳过复制吞吐基准")

        sources, workdir = copy_sources
        total_bytes: int = sum(os.path.getsize(s) for s in sources)

        def _native_copy(dst: Path) -> None:
            res: Optional[Dict[str, Any]] = bridge.copy_files(sources, str(dst))
            assert res is not None, "native 复制返回 None（应 FAIL）"
            assert len(res.get("copied", [])) == len(sources)

        def _python_copy(dst: Path) -> None:
            for src in sources:
                shutil.copy2(src, str(dst / os.path.basename(src)))

        # 预热轮：rayon 线程池爬坡 / 页缓存爬坡，不计入统计
        warm_dir: Path = workdir / "warm"
        warm_dir.mkdir(exist_ok=True)
        _native_copy(warm_dir)
        shutil.rmtree(warm_dir)

        samples: int = COPY_SAMPLES_SMOKE if SMOKE_MODE else COPY_SAMPLES_FULL
        native_s: List[float] = []
        python_s: List[float] = []
        for i in range(samples):
            ndst: Path = workdir / f"native_{i}"
            pdst: Path = workdir / f"python_{i}"
            ndst.mkdir(exist_ok=True)
            pdst.mkdir(exist_ok=True)

            start: float = time.perf_counter()
            _native_copy(ndst)
            native_s.append(time.perf_counter() - start)

            start = time.perf_counter()
            _python_copy(pdst)
            python_s.append(time.perf_counter() - start)

            shutil.rmtree(ndst, ignore_errors=True)
            shutil.rmtree(pdst, ignore_errors=True)

        n_stats: Dict[str, float] = _stats_ms(native_s)
        p_stats: Dict[str, float] = _stats_ms(python_s)
        n_mib_s: float = (total_bytes / 2**20) / (
            n_stats["p50_ms"] / 1000.0
        ) if n_stats["p50_ms"] else 0.0
        p_mib_s: float = (total_bytes / 2**20) / (
            p_stats["p50_ms"] / 1000.0
        ) if p_stats["p50_ms"] else 0.0
        assertion: Dict[str, Any] = _check_native_vs_python(
            n_stats["p50_ms"], p_stats["p50_ms"], "复制吞吐"
        )
        print(
            f"复制吞吐({len(sources)} 文件 {total_bytes // 2**20}MiB): 样本 {samples} | "
            f"native P50 {n_stats['p50_ms']:.1f}ms ({n_mib_s:.0f} MiB/s) | "
            f"python P50 {p_stats['p50_ms']:.1f}ms ({p_mib_s:.0f} MiB/s)"
        )
        _record_baseline(
            "copy_throughput",
            {
                "sources": len(sources),
                "total_bytes": total_bytes,
                "samples": samples,
                "native": {**n_stats, "mib_per_sec_p50": round(n_mib_s, 2)},
                "python": {**p_stats, "mib_per_sec_p50": round(p_mib_s, 2)},
                "assertion": assertion,
            },
        )


# =============================================================================
# >8MB JSON 上限回退路径耗时
# =============================================================================
class TestOverLimitFallback:
    """>8MB JSON 上限回退路径（桥内显式守卫拒绝 + Python 回退排序）。"""

    def test_overlimit_fallback_no_exception_and_records_time(
        self, bridge: FafCoreBridge
    ) -> None:
        """30k in-memory 条目超 8MiB：native 守卫拒绝不崩溃，Python 回退可执行。

        失败条件：守卫路径抛异常 / Python 回退抛异常——**cap 回退路径断言
        不抛异常**；耗时仅记录（无性能 FAIL）。
        """
        if not bridge._supports_sort:
            pytest.skip("faf_core 无 sort 导出，跳过上限回退基准")

        long_path: str = "C:/" + "p" * 300
        entries: List[Dict[str, Any]] = [
            {
                "name": f"n{i}",
                "path": f"{long_path}/{i}",
                "is_dir": False,
                "size": i,
                "modified": "2026-09-14 10:00",
                "created": "2026-09-14 10:00",
                "suffix": "txt",
            }
            for i in range(CAP_ENTRIES)
        ]
        payload_bytes: int = len(
            json.dumps(entries, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        )
        # 语料自检：载荷必须超过 8MiB，否则没有测到真实 cap 守卫
        assert payload_bytes > 8 * 1024 * 1024, (
            f"cap 语料未超 8MiB: {payload_bytes / 2**20:.1f}MiB"
        )

        samples: int = CAP_SAMPLES_SMOKE if SMOKE_MODE else CAP_SAMPLES_FULL
        reject_ms: List[float] = []
        fallback_ms: List[float] = []
        for _ in range(samples):
            # (a) native 守卫：序列化 + 8MiB 检查 → 返回 None（不抛异常）
            start: float = time.perf_counter()
            rejected: Optional[List[Dict[str, Any]]] = _native_sort_entries(
                entries, 2
            )
            reject_ms.append(time.perf_counter() - start)
            assert rejected is None, (
                "超过 8MiB 载荷应被 MAX_JSON_BYTES 守卫拒绝（不崩溃）"
            )

            # (b) Python 回退：_apply_sort mode-2 同款排序（就地）
            fallback_entries: List[Dict[str, Any]] = [dict(e) for e in entries]
            start = time.perf_counter()
            _python_sort_mode2(fallback_entries)
            fallback_ms.append(time.perf_counter() - start)
            # 回退排序确实生效（首元素为最晚 modified）
            assert fallback_entries[0]["modified"] == "2026-09-14 10:00"

        reject_stats: Dict[str, float] = _stats_ms(reject_ms)
        fallback_stats: Dict[str, float] = _stats_ms(fallback_ms)
        total_p50: float = round(
            reject_stats["p50_ms"] + fallback_stats["p50_ms"], 3
        )
        print(
            f">8MB 上限回退({payload_bytes / 2**20:.1f}MiB 载荷): 样本 {samples} | "
            f"native 守卫拒绝 P50 {reject_stats['p50_ms']:.1f}ms | "
            f"Python 回退排序 P50 {fallback_stats['p50_ms']:.1f}ms | "
            f"回退全路径 P50 {total_p50:.1f}ms"
        )
        _record_baseline(
            "overlimit_fallback",
            {
                "entries": CAP_ENTRIES,
                "payload_mib": round(payload_bytes / 2**20, 3),
                "cap_bytes": 8 * 1024 * 1024,
                "samples": samples,
                "native_cap_reject": reject_stats,
                "python_fallback": fallback_stats,
                "total_fallback_p50_ms": total_p50,
                "no_exception": True,
            },
        )
