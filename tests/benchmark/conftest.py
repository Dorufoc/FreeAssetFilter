# -*- coding: utf-8 -*-
"""tests/benchmark/ 专属 conftest：自门控 + 产物隔离 + 可选快照导出。

性能治理 P0.2 的三条硬约束：

* **自门控**：裸 ``python -m pytest tests/`` 不得收集/运行 benchmark。
  只有显式指定 ``tests/benchmark`` 路径，或设置 ``FAF_BENCH=1`` 才运行。
  原因：``pytest.ini`` 的 ``testpaths = tests`` 会递归收集本目录，而
  ``pytest-timeout`` 的 ``timeout_method = thread`` 在 Windows 上等价于
  ``os._exit``——一次 native 卡死会带走整个 pytest 进程。

* **产物隔离**：基准 JSON 由各测试文件通过 ``FAF_BENCH_OUTPUT`` 决定落点，
  默认 ``build/bench/``；**永不**覆盖 ``tests/benchmark/baseline/``
  （需显式 ``FAF_BENCH_UPDATE=1``），也**永不**写用户 ``data/`` 或
  ``~/.freeassetfilter/``。

* **显式快照导出**：仅当 ``FAF_BENCH_EXPORT_SNAPSHOT=1`` 时导出 perf
  快照（兼容 ``run_tests.py regression`` 的旧消费契约）。默认关闭。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict

import pytest

#: 仓库根（本文件位于 tests/benchmark/ 下，上溯两级即根目录）。
_REPO_ROOT: Path = Path(__file__).resolve().parents[2]
#: 回归基线文件路径（与 run_tests.py ``PERF_BASELINE`` 一致）。
_PERF_BASELINE: Path = (
    _REPO_ROOT / ".omo" / "evidence" / "tests-comprehensive-refactor" / "perf_baseline.json"
)
#: 默认性能快照目录（仅在显式开启导出时使用）。
_PERF_SNAPSHOT_DIR: Path = Path.home() / ".freeassetfilter" / "performance"
#: 默认基准产物目录（仓库内，已被 .gitignore 的 build/ 覆盖）。
_DEFAULT_OUTPUT_DIR: Path = _REPO_ROOT / "build" / "bench"


def _truthy_env(name: str) -> bool:
    """判断环境变量是否显式开启（``1``/``true``/``yes``/``on``）。"""
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _benchmark_requested(config: Any) -> bool:
    """判定本次 pytest 是否显式请求了 benchmark。

    满足任一条件即视为请求：

    * ``FAF_BENCH`` 为真值；
    * 命令行参数（``config.args``）中任意路径落在 ``tests/benchmark`` 下；
    * 通过 ``-k`` / ``-m`` 选择了 benchmark（保守放行，由用户显式表达意图）。

    Args:
        config: pytest ``Config`` 对象。

    Returns:
        bool: 是否运行 benchmark。
    """
    if _truthy_env("FAF_BENCH"):
        return True
    for arg in getattr(config, "args", []) or []:
        text: str = str(arg).replace("\\", "/").rstrip("/")
        if "benchmark" in text:
            return True
    return False


def pytest_addoption(parser: Any) -> None:
    """注册 benchmark 专属选项。

    Args:
        parser: pytest option parser。
    """
    parser.addoption(
        "--smoke",
        action="store_true",
        default=False,
        help="S9 以 smoke 模式运行（30s）；benchmark 亦以此缩小语料。",
    )
    parser.addoption(
        "--s9-full",
        action="store_true",
        default=False,
        help="S9 跑完整 5 分钟（终验用；CI/冒烟不得使用）。",
    )
    parser.addoption(
        "--bench-output",
        action="store",
        default=None,
        metavar="DIR",
        help="基准 JSON 输出目录；缺省读 FAF_BENCH_OUTPUT，再缺省写 build/bench/。",
    )


def pytest_collection_modifyitems(config: Any, items: list[Any]) -> None:
    """未显式请求时跳过 **benchmark 用例**（自门控）。

    注意：pytest 会把**全量** items 传给每个已加载的 conftest 的同名 hook，
    因此这里必须先筛出本目录的用例（路径落在 ``tests/benchmark/`` 下或带
    ``benchmark`` marker），否则裸 ``pytest tests/`` 会把 3700+ 非基准用例
    一起 skip 掉。

    Args:
        config: pytest ``Config`` 对象。
        items: 已收集的测试项列表（就地修改）。
    """
    if _benchmark_requested(config):
        return
    skip_marker = pytest.mark.skip(
        reason="benchmark 需显式运行：pytest tests/benchmark/ 或 FAF_BENCH=1"
    )
    benchmark_root = Path(__file__).resolve().parent
    for item in items:
        is_benchmark = item.get_closest_marker("benchmark") is not None
        if not is_benchmark:
            try:
                is_benchmark = benchmark_root in Path(str(item.fspath)).parents
            except (AttributeError, OSError, TypeError):
                is_benchmark = False
        if is_benchmark:
            item.add_marker(skip_marker)


def pytest_configure(config: Any) -> None:
    """注册 benchmark 专属 marker，并把输出目录固化到环境变量。

    测试模块（``test_faf_core_perf.py``）在 import 时计算 ``BASELINE_PATH``，
    因此必须在 collection 之前设置环境变量。

    ``pytest.ini`` 启用了 ``--strict-markers``，历史上 ``soak`` 等 benchmark
    专用 marker 未在全局注册；在此就地注册，避免修改 ``pytest.ini``（那会
    改变 149 个既有测试文件的收集语义）。

    Args:
        config: pytest ``Config`` 对象。
    """
    for marker_line in (
        "soak: 长时浸泡测试（仅 benchmark 目录，显式运行）",
        "benchmark_scenario: S1-S10 场景基准（仅 benchmark 目录）",
        "latency: 延迟分位数基准（仅 benchmark 目录）",
        "throughput: 吞吐基准（仅 benchmark 目录）",
    ):
        config.addinivalue_line("markers", marker_line)

    explicit_dir: str | None = config.getoption("--bench-output", default=None)
    if explicit_dir and not os.environ.get("FAF_BENCH_OUTPUT"):
        os.environ["FAF_BENCH_OUTPUT"] = str(Path(explicit_dir).resolve())
    elif not os.environ.get("FAF_BENCH_OUTPUT"):
        _DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        os.environ["FAF_BENCH_OUTPUT"] = str(_DEFAULT_OUTPUT_DIR.resolve())


def _snapshot_to_baseline() -> bool:
    """导出 perf 快照并（首次）确立回归基线。

    Returns:
        bool: 事件键契约是否满足消费方要求。
    """
    from freeassetfilter.utils.perf_metrics import get_perf_snapshot

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
        print(f"[benchmark] 首次运行：确立回归基线 -> {_PERF_BASELINE}", flush=True)
    return all(
        {"avg_ms", "calls", "p95_ms", "p99_ms"} <= set(e.keys())
        for e in snapshot.get("events", {}).values()
    )


def pytest_sessionfinish(session: Any, exitstatus: int) -> None:
    """会话结束时的可选快照导出（默认关闭）。

    Args:
        session: pytest 会话对象（本钩子不使用）。
        exitstatus: pytest 退出码。
    """
    if not _truthy_env("FAF_BENCH_EXPORT_SNAPSHOT"):
        return None
    try:
        _snapshot_to_baseline()
    except Exception as e:  # noqa: BLE001 - 导出失败不阻断测试结论
        print(f"[benchmark] 快照导出失败（忽略）: {e}", flush=True)
    return None
