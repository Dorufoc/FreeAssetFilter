# -*- coding: utf-8 -*-
"""tests/benchmark/ 专属 conftest：基线确立 + 默认快照导出（todo-27）。

职责（对齐 run_tests.py regression 子命令的消费契约）：

* **会话结束时导出默认性能快照** → ``~/.freeassetfilter/performance/
  perf_metrics_<ts>.json``（``PERF_SNAPSHOT_DIR``），供
  ``_latest_perf_snapshot()`` 读取——否则 regression 在"未发现性能快照"
  处直接退出 1；
* **首次基准运行确立基线** → 若 ``.omo/evidence/tests-comprehensive-refactor/
  perf_baseline.json``（``PERF_BASELINE``，run_tests.py L73-75）尚不存在，
  则把当前快照内容写入该路径。后续运行**不覆写**，以便 regression 对比出
  多次运行间的时序差异（仅报告、不 gate）。

均在 ``tests/benchmark/`` 目录内完成，不触碰 run_tests.py / pytest.ini。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict

#: 仓库根（本文件位于 tests/benchmark/ 下，上溯两级即根目录）。
_REPO_ROOT: Path = Path(__file__).resolve().parents[2]
#: 回归基线文件路径（与 run_tests.py ``PERF_BASELINE`` 一致）。
_PERF_BASELINE: Path = (
    _REPO_ROOT / ".omo" / "evidence" / "tests-comprehensive-refactor" / "perf_baseline.json"
)
#: 默认性能快照目录（与 run_tests.py ``PERF_SNAPSHOT_DIR`` 一致）。
_PERF_SNAPSHOT_DIR: Path = Path.home() / ".freeassetfilter" / "performance"


def _snapshot_to_baseline() -> bool:
    """导出当前 perf 快照并确立基线（若尚不存在）。

    Returns:
        bool: 是否成功完成导出。
    """
    from freeassetfilter.utils.perf_metrics import export_perf_metrics, get_perf_snapshot

    snapshot: Dict[str, Any] = get_perf_snapshot()
    _PERF_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    ts: str = time.strftime("%Y%m%d_%H%M%S")
    snapshot_path: Path = _PERF_SNAPSHOT_DIR / f"perf_metrics_{ts}.json"
    with open(snapshot_path, "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, ensure_ascii=False, indent=2)

    if not _PERF_BASELINE.exists() and snapshot.get("events"):
        _PERF_BASELINE.parent.mkdir(parents=True, exist_ok=True)
        _PERF_BASELINE.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            f"[benchmark] 首次运行：确立回归基线 -> {_PERF_BASELINE}",
            flush=True,
        )
    # 消费方解析口径自检（run_tests._load_metrics 仅读 events.avg_ms/calls）
    event_keys_ok: bool = all(
        {"avg_ms", "calls", "p95_ms", "p99_ms"} <= set(e.keys())
        for e in snapshot.get("events", {}).values()
    )
    return event_keys_ok


def pytest_sessionfinish(session: Any, exitstatus: int) -> None:
    """基准会话结束后导出快照（exit 0 时顺带确立基线）。

    Args:
        session: pytest 会话对象（本钩子不使用）。
        exitstatus: pytest 退出码。
    """
    try:
        _snapshot_to_baseline()
    except Exception as e:  # noqa: BLE001 - 导出失败不阻断测试结论
        print(f"[benchmark] 快照导出失败（忽略）: {e}", flush=True)
    return None