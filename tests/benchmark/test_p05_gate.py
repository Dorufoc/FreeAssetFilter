# -*- coding: utf-8 -*-
"""P0.5 门禁汇总：把各基准产物收敛为一张「接线决策表」。

职责：
* 读取 ``build/bench/`` 下的全部基准 JSON；
* 按 P0.5 分级口径汇总 ``pass / experimental / blocked`` 与单遍收益；
* 生成 ``build/bench/gate-summary.json`` 与人类可读的 ``gate-summary.md``；
* 断言：关键产物存在、P0.3 的 parity 全绿、P0.3b 的 FFI 计数符合契约。

本测试**不**因 ``blocked`` 而 FAIL —— ``blocked`` 是「该路径不应进入默认
接线」的结论，不是测试失败。真正的接线约束由人工按裁决表执行。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

pytestmark = [pytest.mark.benchmark, pytest.mark.timeout(120)]

#: 仓库根。
_REPO_ROOT: Path = Path(__file__).resolve().parents[2]
#: 基准产物目录（与 conftest 的默认输出一致）。
BENCH_DIR: Path = Path(
    os.environ.get("SPK_BENCH_OUTPUT", str(_REPO_ROOT / "build" / "bench"))
)
if BENCH_DIR.suffix:
    BENCH_DIR = BENCH_DIR.parent

#: 需要覆盖的最小产物集合（缺任一即视为 P0 未完成）。
_REQUIRED: Dict[str, str] = {
    "spk-core-perf.json": "spk-core-perf-baseline/v1",
    "p03-scan-three-arm.json": "spk-scan-three-arm/v1",
    "p03b-highlight-three-arm.json": "spk-highlight-three-arm/v1",
    "p04-thread-memory-baseline.json": "spk-thread-memory-baseline/v1",
}


def _load(name: str) -> Optional[Dict[str, Any]]:
    """读取单个基准 JSON。"""
    path: Path = BENCH_DIR / name
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _collect_verdicts(document: Dict[str, Any], prefix: str) -> List[Dict[str, Any]]:
    """从 spk-core-perf 基线中抽取各路径的 verdict。"""
    rows: List[Dict[str, Any]] = []
    for section, payload in document.items():
        if not isinstance(payload, dict):
            continue
        assertion = payload.get("assertion")
        if not isinstance(assertion, dict):
            continue
        rows.append(
            {
                "path": f"{prefix}.{section}",
                "native_p50_ms": assertion.get("p50_native_ms"),
                "python_p50_ms": assertion.get("p50_python_ms"),
                "speedup_x": assertion.get("speedup_x"),
                "verdict": assertion.get("verdict", "experimental"),
            }
        )
    return rows


def test_gate_summary() -> None:
    """汇总全部基准并生成决策表。"""
    missing: List[str] = [
        name for name in _REQUIRED if not (BENCH_DIR / name).is_file()
    ]
    assert not missing, (
        f"缺少基准产物 {missing}；请先运行 P0.3/P0.3b/P0.4 与主基准。"
    )

    core = _load("spk-core-perf.json") or {}
    scan = _load("p03-scan-three-arm.json") or {}
    highlight = _load("p03b-highlight-three-arm.json") or {}
    memory = _load("p04-thread-memory-baseline.json") or {}

    rows: List[Dict[str, Any]] = []

    # ---- 主基准各路径 verdict ----
    rows.extend(_collect_verdicts(core, "spk_core"))

    # ---- 目录扫描四臂 ----
    for case in scan.get("cases", []):
        comparison = case.get("comparison", {})
        arms = case.get("arms", {})
        rows.append(
            {
                "path": f"scan.{case.get('files')}files.native",
                "native_p50_ms": arms.get("native", {}).get("p50_ms"),
                "python_p50_ms": arms.get("py_single", {}).get("p50_ms"),
                "speedup_x": comparison.get("native_vs_py_single_x"),
                "verdict": comparison.get("native_verdict"),
            }
        )
        rows.append(
            {
                "path": f"scan.{case.get('files')}files.onepass",
                "native_p50_ms": arms.get("py_onepass", {}).get("p50_ms"),
                "python_p50_ms": arms.get("py_double", {}).get("p50_ms"),
                "speedup_x": comparison.get("py_double_vs_onepass_x"),
                "verdict": comparison.get("onepass_verdict"),
            }
        )

    # ---- 高亮三臂 ----
    hl_arms = highlight.get("arms", {})
    hl_cmp = highlight.get("comparison", {})
    rows.append(
        {
            "path": "highlight.block_vs_line",
            "native_p50_ms": hl_arms.get("block_native", {}).get("stats", {}).get("p50_ms"),
            "python_p50_ms": hl_arms.get("line_native", {}).get("stats", {}).get("p50_ms"),
            "speedup_x": hl_cmp.get("block_speedup_x"),
            "verdict": hl_cmp.get("verdict"),
        }
    )
    rows.append(
        {
            "path": "highlight.native_vs_pygments",
            "native_p50_ms": hl_arms.get("line_native", {}).get("stats", {}).get("p50_ms"),
            "python_p50_ms": hl_arms.get("line_pygments", {}).get("stats", {}).get("p50_ms"),
            "speedup_x": None,
            "verdict": (
                "native_blocked"
                if (hl_arms.get("line_native", {}).get("stats", {}).get("p50_ms") or 0)
                > (hl_arms.get("line_pygments", {}).get("stats", {}).get("p50_ms") or 0)
                * 1.05
                else "native_ok"
            ),
        }
    )

    summary: Dict[str, Any] = {
        "schema": "spk-p0-gate-summary/v1",
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "bench_dir": str(BENCH_DIR),
        "rows": rows,
        "highlight_ffi": {
            "line_native_calls_per_run": hl_arms.get("line_native", {}).get(
                "ffi_calls_per_run"
            ),
            "block_native_calls_per_run": hl_arms.get("block_native", {}).get(
                "ffi_calls_per_run"
            ),
        },
        "thread_memory": {
            "threads": memory.get("process_threads", {}),
            "rss_max_bytes": memory.get("process_memory", {}).get("rss_max_bytes"),
            "probe_overhead": memory.get("probe_overhead"),
        },
    }

    (BENCH_DIR / "gate-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    lines: List[str] = [
        "# P0 接线决策表",
        "",
        f"生成时间：{summary['timestamp']}",
        f"产物目录：`{BENCH_DIR}`",
        "",
        "| 路径 | native (ms) | python (ms) | 倍率 | 裁决 |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        native_ms = row["native_p50_ms"]
        python_ms = row["python_p50_ms"]
        speedup = row["speedup_x"]
        lines.append(
            "| {path} | {native} | {python} | {speedup} | **{verdict}** |".format(
                path=row["path"],
                native=f"{native_ms:.3f}" if isinstance(native_ms, (int, float)) else "—",
                python=f"{python_ms:.3f}" if isinstance(python_ms, (int, float)) else "—",
                speedup=f"{speedup:.3f}x" if isinstance(speedup, (int, float)) else "—",
                verdict=row["verdict"],
            )
        )
    lines.extend(
        [
            "",
            "## 判决口径",
            "",
            "* `pass` / `native_pass` / `onepass_worthwhile`：允许进入默认路径；",
            "* `experimental` / `block_marginal` / `onepass_marginal`：仅实验性开关；",
            "* `blocked` / `native_blocked` / `block_slower`：**不得接线**，需先改造并复测。",
            "",
        ]
    )
    (BENCH_DIR / "gate-summary.md").write_text("\n".join(lines), encoding="utf-8")

    print("\n" + "\n".join(lines), flush=True)

    # ---- 硬约束：P0.3 的 parity 必须全绿 ----
    for case in scan.get("cases", []):
        parity = case.get("parity", {})
        assert parity.get("native_vs_py_single") is True
        assert parity.get("onepass_vs_py_single") is True
        assert parity.get("onepass_attrs_vs_oracle") is True

    # ---- 硬约束：高亮 FFI 计数契约 ----
    assert summary["highlight_ffi"]["block_native_calls_per_run"] == 1
    assert summary["highlight_ffi"]["line_native_calls_per_run"] >= 3000

    # ---- 硬约束：线程/内存基线必须可读 ----
    assert summary["thread_memory"]["threads"]["min"] is not None
    assert summary["thread_memory"]["rss_max_bytes"] is not None
