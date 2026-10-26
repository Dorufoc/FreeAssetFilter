# -*- coding: utf-8 -*-
# targets: utils.syntax_highlighter, ui.layout.preview.text_previewer_layout
"""P0.3b 高亮三臂：验证「5000 次 FFI 是主因」这一假设是否成立。

现有基准只测过**整块** native（3000 行 ≈ 215.9ms）与**逐行 Pygments**
（≈214.4ms），两者持平。但它从未测过**逐行 native**——也就是当前生产路径
（``_TextHighlighter.highlightBlock`` → ``tokenize`` → 每行一次 FFI）。

如果逐行 native ≈ 整块 native，则「减少 FFI 次数」收益有限，P1.1 需要重新评估；
如果逐行 native 远慢于整块，则 P1.1 收益明确且可量化。

三臂：

============ ================================================================
臂           实现
============ ================================================================
``line_native``  当前生产路径：逐行 ``FafCoreHighlighter.tokenize``
                 （每行 1 次 ctypes + 1 次 ``json.loads``）
``block_native`` 整块 ``FafCoreHighlighter.highlight_text``（1 次 FFI +
                 纯 Python ``_spans_to_blocks`` 切分）
``line_pygments`` 逐行 ``PygmentsHighlighter.highlight_line``（DLL 缺失时的回退）
============ ================================================================

产物：``build/bench/p03b-highlight-three-arm.json``。
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

from freeassetfilter.core.native.bridges.faf_core_bridge import get_faf_core_bridge

_UI_ROOT: str = str(Path(__file__).resolve().parents[2] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from freeassetfilter.utils.syntax_highlighter import (  # noqa: E402
    FafCoreHighlighter,
    PygmentsHighlighter,
    faf_core_highlight_available,
)

pytestmark = [pytest.mark.benchmark, pytest.mark.timeout(300)]

#: 语料行数（与 test_faf_core_perf.HIGHLIGHT_ITERS × 3 对齐）。
CORPUS_LINES: int = 3000
#: 采样次数。
SAMPLES: int = 5
#: 语言标识。
LANGUAGE: str = "python"

_OUTPUT_ENV: str = os.environ.get("FAF_BENCH_OUTPUT", "").strip()
if _OUTPUT_ENV:
    _candidate: Path = Path(_OUTPUT_ENV)
    OUTPUT_PATH: Path = (
        _candidate / "p03b-highlight-three-arm.json"
        if (_candidate.is_dir() or not _candidate.suffix)
        else _candidate
    )
else:
    OUTPUT_PATH = (
        Path(__file__).resolve().parents[2]
        / "build"
        / "bench"
        / f"p03b-highlight-three-arm-{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )


def _percentile(sorted_values: List[float], pct: float) -> float:
    """线性插值分位数。"""
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
    """机器指纹。"""
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
    }


def _corpus() -> str:
    """3000 行 Python 合成代码（与主基准同构）。"""
    lines: List[str] = []
    per_iter: int = CORPUS_LINES // 3
    for i in range(per_iter):
        lines.append(f"def func_{i}(a, b):")
        lines.append(f"    # comment {i}")
        lines.append(f"    return a + b  # tail {i}")
    return "\n".join(lines) + "\n"


class _FfiCounter:
    """临时替换 bridge.highlight_text，统计调用次数与返回载荷规模。"""

    def __init__(self, bridge: Any) -> None:
        self._bridge = bridge
        self._had_attr: bool = "highlight_text" in bridge.__dict__
        self._saved_attr: Any = bridge.__dict__.get("highlight_text")
        self._original = bridge.highlight_text
        self.calls: int = 0
        self.spans: int = 0
        self.payload_bytes: int = 0

    def __enter__(self) -> "_FfiCounter":
        def wrapped(language: str, text: str) -> Optional[list]:
            self.calls += 1
            result = self._original(language, text)
            if result:
                self.spans += len(result)
                self.payload_bytes += len(
                    json.dumps(result, separators=(",", ":")).encode("utf-8")
                )
            return result

        self._bridge.highlight_text = wrapped
        return self

    def __exit__(self, *exc_info: Any) -> None:
        """干净恢复：若原来无实例属性则删除，避免留下绑定方法副本。"""
        if self._had_attr:
            self._bridge.highlight_text = self._saved_attr
        else:
            del self._bridge.highlight_text

    def reset(self) -> None:
        """清零计数器（预热后调用）。"""
        self.calls = 0
        self.spans = 0
        self.payload_bytes = 0


def _time_s(func: Any) -> float:
    """执行一次并返回**秒**（与 ``_stats_ms`` 的 ×1000 口径配套）。"""
    start: float = time.perf_counter()
    func()
    return time.perf_counter() - start


@pytest.fixture(scope="module")
def bridge() -> Any:
    """原生桥；DLL 不可用时跳过。"""
    inst = get_faf_core_bridge()
    if inst is None or not inst.available or not faf_core_highlight_available():
        pytest.skip("faf_core 高亮不可用，跳过三臂对比")
    return inst


def test_highlight_three_arms(bridge: Any) -> None:
    """逐行 native vs 整块 native vs 逐行 Pygments。"""
    text: str = _corpus()
    lines: List[str] = text.split("\n")
    native = FafCoreHighlighter()
    pygments = PygmentsHighlighter()
    # 注意：``reset_singletons``（function 级 autouse）会在 module 级 fixture
    # 之后把 ``faf_core_bridge._instance`` 归零，因此高亮器可能拿到另一个
    # bridge 实例。计数必须以**高亮器实际持有的实例**为准，不能依赖 fixture。
    target_bridge = native._bridge
    assert target_bridge is not None, "FafCoreHighlighter 未挂上 bridge"

    arms: Dict[str, Any] = {}

    # ---- 臂 A：逐行 native（当前生产路径）----
    with _FfiCounter(target_bridge) as counter_a:

        def arm_line_native() -> None:
            for line in lines:
                native.tokenize(line, LANGUAGE)

        arm_line_native()  # 预热
        counter_a.reset()
        samples_a: List[float] = [_time_s(arm_line_native) for _ in range(SAMPLES)]
        arms["line_native"] = {
            "stats": _stats_ms(samples_a),
            "ffi_calls_per_run": counter_a.calls // max(1, SAMPLES),
            "spans_per_run": counter_a.spans // max(1, SAMPLES),
            "payload_bytes_per_run": counter_a.payload_bytes // max(1, SAMPLES),
        }

    # ---- 臂 B：整块 native ----
    with _FfiCounter(target_bridge) as counter_b:

        def arm_block_native() -> None:
            native.highlight_text(text, LANGUAGE)

        arm_block_native()
        counter_b.reset()
        samples_b: List[float] = [_time_s(arm_block_native) for _ in range(SAMPLES)]
        arms["block_native"] = {
            "stats": _stats_ms(samples_b),
            "ffi_calls_per_run": counter_b.calls // max(1, SAMPLES),
            "spans_per_run": counter_b.spans // max(1, SAMPLES),
            "payload_bytes_per_run": counter_b.payload_bytes // max(1, SAMPLES),
        }

    # ---- 臂 C：逐行 Pygments（回退链）----
    def arm_line_pygments() -> None:
        for line in lines:
            pygments.highlight_line(line, LANGUAGE)

    arm_line_pygments()
    samples_c: List[float] = [_time_s(arm_line_pygments) for _ in range(SAMPLES)]
    arms["line_pygments"] = {
        "stats": _stats_ms(samples_c),
        "ffi_calls_per_run": 0,
        "spans_per_run": None,
        "payload_bytes_per_run": 0,
    }

    a_p50: float = arms["line_native"]["stats"]["p50_ms"]
    b_p50: float = arms["block_native"]["stats"]["p50_ms"]
    c_p50: float = arms["line_pygments"]["stats"]["p50_ms"]

    block_vs_line: float = a_p50 / b_p50 if b_p50 else 0.0
    if block_vs_line >= 1.2:
        verdict: str = "block_worthwhile"
    elif block_vs_line <= 0.85:
        verdict = "block_slower"
    else:
        verdict = "block_marginal"

    print(
        f"\n[P0.3b] {CORPUS_LINES} 行 | line_native {a_p50:.1f}ms "
        f"({arms['line_native']['ffi_calls_per_run']} FFI, "
        f"{arms['line_native']['payload_bytes_per_run']/1024:.1f} KiB) | "
        f"block_native {b_p50:.1f}ms "
        f"({arms['block_native']['ffi_calls_per_run']} FFI, "
        f"{arms['block_native']['payload_bytes_per_run']/1024:.1f} KiB) | "
        f"line_pygments {c_p50:.1f}ms | "
        f"block/line 加速 {1/block_vs_line:.2f}x ({verdict})",
        flush=True,
    )

    document: Dict[str, Any] = {
        "schema": "faf-highlight-three-arm/v1",
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "machine": _machine_summary(),
        "corpus": {"lines": CORPUS_LINES, "chars": len(text), "language": LANGUAGE},
        "samples": SAMPLES,
        "arms": arms,
        "comparison": {
            "block_vs_line_ratio": round(block_vs_line, 3),
            "block_speedup_x": round(1.0 / block_vs_line, 3) if block_vs_line else 0.0,
            "verdict": verdict,
            "line_pygments_vs_line_native_x": round(
                c_p50 / a_p50 if a_p50 else 0.0, 3
            ),
        },
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[P0.3b] 结果已写入 {OUTPUT_PATH}", flush=True)

    # 硬约束：整块路径必须只调用 1 次 FFI（契约正确性）。
    assert arms["block_native"]["ffi_calls_per_run"] == 1
    # 逐行路径必须每行一次（证明「N 次 FFI」假设成立）。
    assert arms["line_native"]["ffi_calls_per_run"] >= CORPUS_LINES
