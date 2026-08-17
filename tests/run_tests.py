#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FreeAssetFilter 统一测试运行器（tests/run_tests.py）。

九个 argparse 子命令（``python tests/run_tests.py <子命令>``）：

* **all**（默认）—— 全量非基准套件，追加 ``-m "not benchmark and not gui"``
  （benchmark 仅由显式 ``benchmark`` 子命令执行；同时保留 pytest.ini
  ``addopts`` 中 ``-m "not gui"`` 的排除语义——CLI ``-m`` 会整体覆盖 ini 的
  ``-m``，故必须在这里**合并**两个排除，V3 修正见计划 todo-5/29）；
* **unit / widgets / components / integration** —— 按目录范围运行对应分层；
  骨架期自动追加 ``tests/.omo_qa_smoke/``（探针）保证 collected ≥ 1，
  规避零收集退出码 5（todo-5 验收口径）；
* **gui** —— 隐式 ``-m gui`` + ``FAF_VISUAL=1``，并**取消**默认 offscreen
  （真实显示器环境，todo-26 语义）；
* **benchmark** —— 隐式 ``-m benchmark``，默认超时 300s；
* **coverage** —— 同 ``all`` 范围并附加 ``--cov=freeassetfilter
  --cov-report=term``；``--strict`` 时再运行 ``coverage_manifest``；
* **regression** —— 运行 benchmark 后对比
  ``.omo/evidence/tests-comprehensive-refactor/perf_baseline.json``，
  仅输出对比报告、不作为性能 gate（todo-27 Momus 修正）。

公共行为：

* 启动即 ``log_setup.prepare_log_dir()``（清空旧 ``run-*.log``）并打印当前
  日志路径（幂等：pytest 侧的 ``log_setup.pytest_configure`` 复用同一文件，
  不会二次清理）；
* 默认 ``QT_QPA_PLATFORM=offscreen``（``--visual`` 时取消；``gui`` 子命令
  无条件取消）；
* 默认 ``--timeout 30``（``--timeout N`` 可覆盖）。超时三级优先级的完整语义
  见 ``tests.support.timeout_policy``：显式 marker 最高、自动打标次之、
  这里透传的 CLI ``--timeout`` 仅兜底两者均缺失的测试——**CLI 永不覆盖
  marker**；
* 始终 ``-v`` 流式进度 + 挂载 progress / log_setup 两个 support 插件
  （60s 周期小结 + 结束 top-5 最慢）；
* 透传 ``-k`` / ``--tb`` / ``-x`` / ``--co``（收集模式可直接用于验收）；
* 退出码透传 pytest（若子命令是子流程，则聚合）。

用法示例：:

    python tests/run_tests.py unit --co          # 收集模式验收（exit 0）
    python tests/run_tests.py all                # 默认套件
    python tests/run_tests.py gui                # 视觉测试（真实显示器）
    python tests/run_tests.py coverage --strict  # 覆盖率 + manifest 严格门
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

#: 仓库根（本文件位于 tests/ 下，上溯一级即根目录）。
ROOT_DIR: Path = Path(__file__).resolve().parents[1]

#: 全部子命令清单（--help 展示、argparse choices）。
SUBCOMMANDS: Tuple[str, ...] = (
    "all", "unit", "widgets", "components", "integration",
    "gui", "benchmark", "coverage", "regression",
)

#: 非基准子命令的默认超时（秒）。
DEFAULT_TIMEOUT: int = 30
#: benchmark / regression 子命令的专属默认超时（秒）。
BENCHMARK_TIMEOUT: int = 300

#: 回归基线文件路径（todo-27 benchmark 子命令写入）。
PERF_BASELINE: Path = (
    ROOT_DIR / ".omo" / "evidence" / "tests-comprehensive-refactor" / "perf_baseline.json"
)
#: 产品性能快照目录（perf_metrics 输出，见 freeassetfilter/utils/perf_metrics.py）。
PERF_SNAPSHOT_DIR: Path = Path.home() / ".freeassetfilter" / "performance"
#: 回归退化阈值（沿用旧 perf_regression_checker 默认 15%）。
REGRESSION_THRESHOLD: float = 0.15

#: 运行器挂载的 support 插件（progress 周期小结 / log_setup 双写日志）。
_PROGRESS_PLUGIN: str = "tests.support.progress"
_LOG_PLUGIN: str = "tests.support.log_setup"


def _ensure_sys_path() -> None:
    """把仓库根插入 sys.path 首位，保证 ``tests.support.*`` 可导入。

    直接以 ``python tests/run_tests.py`` 运行时，Python 会把脚本所在目录
    （``tests/``）放进 sys.path[0]，此时 ``import tests.support...`` 找不到
    包；根目录在前才可解析。
    """
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))


def _resolve_timeout(command: str, args: argparse.Namespace) -> int:
    """计算本次子命令生效的 CLI 超时秒数。

    优先级：用户显式 ``--timeout N`` > 子命令默认（benchmark/regression 为
    300，其余 30）。注意这里的取值只影响 CLI 兜底层——任何显式 timeout
    marker 或 timeout_policy 自动打标仍优先（见 tests/support/timeout_policy.py）。

    Args:
        command: 当前子命令名。
        args: 解析后的参数命名空间。

    Returns:
        int: 应透传给 pytest 的 ``--timeout`` 秒数。
    """
    if args.timeout is not None:
        return args.timeout
    if command in ("benchmark", "regression"):
        return BENCHMARK_TIMEOUT
    return DEFAULT_TIMEOUT


def _configure_platform(command: str, visual: bool) -> None:
    """按子命令调整显示相关环境变量。

    默认 ``QT_QPA_PLATFORM=offscreen``（``--visual`` 时取消）；
    ``gui`` 子命令无条件取消 offscreen（真实显示器）并设置
    ``FAF_VISUAL=1``（供 gui 套件判断断言层/截图层深浅模式）。

    Args:
        command: 当前子命令名。
        visual: 用户是否显式传入 ``--visual``。
    """
    if visual:
        os.environ.pop("QT_QPA_PLATFORM", None)
    else:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if command == "gui":
        os.environ.pop("QT_QPA_PLATFORM", None)
        os.environ["FAF_VISUAL"] = "1"
    else:
        os.environ.pop("FAF_VISUAL", None)


def _scope_paths(command: str) -> List[str]:
    """计算子命令的 pytest 收集路径参数。

    按分层目录划定范围；unit/widgets/components/integration 在骨架期
    （``tests/.omo_qa_smoke/`` 存在时）追加探针目录，保证每个子命令
    collected ≥ 1，规避零收集退出码 5——这是 todo-5 验收的前提。

    Args:
        command: 当前子命令名。

    Returns:
        list[str]: 传给 pytest 的路径参数列表。
    """
    tests_root: Path = ROOT_DIR / "tests"
    smoke_dir: Path = tests_root / ".omo_qa_smoke"
    layered: Tuple[str, ...] = ("unit", "widgets", "components", "integration")
    if command == "all":
        return [str(tests_root)]
    if command in layered:
        paths: List[str] = [str(tests_root / command)]
        if smoke_dir.is_dir():
            paths.append(str(smoke_dir))
        return paths
    if command == "gui":
        return [str(tests_root / "gui")]
    if command in ("benchmark", "regression"):
        return [str(tests_root / "benchmark")]
    if command == "coverage":
        return [str(tests_root)]
    raise ValueError(f"未知子命令: {command}")


def _marker_args(command: str) -> List[str]:
    """计算子命令需要覆盖或补充的 ``-m`` 参数。

    ``all``/``coverage`` 必须合并两个排除（not benchmark and not gui）——
    因为 CLI ``-m`` 整体覆盖 pytest.ini addopts 里的 ``-m "not gui"``，
    只传 ``-m "not benchmark"`` 会导致 gui 用例被纳入默认套件。
    gui/benchmark 子命令则用 ``-m gui`` / ``-m benchmark`` 反选对应 marker
    （覆盖 addopts 的默认排除）。其余分层子命令不传 ``-m``，沿用 ini 的
    ``-m "not gui"``。

    Args:
        command: 当前子命令名。

    Returns:
        list[str]: 需追加的 ``-m <expr>`` 参数（空则不改写）。
    """
    if command in ("all", "coverage"):
        return ["-m", "not benchmark and not gui"]
    if command == "gui":
        return ["-m", "gui"]
    if command == "benchmark":
        return ["-m", "benchmark"]
    return []


def build_pytest_args(command: str, args: argparse.Namespace) -> List[str]:
    """组装本次子命令的完整 pytest 参数列表。

    公共基底：挂载 progress + log_setup 插件、``-v``、``--timeout``、
    ``-k``/``--tb``/``-x``/``--co`` 透传、收集路径、子命令专属 ``-m``。

    Args:
        command: 当前子命令名。
        args: 解析后的参数命名空间。

    Returns:
        list[str]: 可直接交给 ``pytest.main`` 的参数列表。
    """
    pytest_args: List[str] = [
        "-p", _PROGRESS_PLUGIN,
        "-p", _LOG_PLUGIN,
        "-v",
        "--timeout", str(_resolve_timeout(command, args)),
    ]
    if args.k:
        pytest_args.extend(["-k", args.k])
    if args.tb:
        pytest_args.extend(["--tb", args.tb])
    if args.exitfirst:
        pytest_args.append("-x")
    if args.co:
        pytest_args.append("--collect-only")
    pytest_args.extend(_scope_paths(command))
    pytest_args.extend(_marker_args(command))
    return pytest_args


def _prepare_log_dir() -> Path:
    """调用 log_setup 准备本次运行日志目录并返回日志文件路径。

    幂等：再次调用会清掉上一个会话的 ``run-*.log`` 并重新命名；pytest 侧
    ``log_setup.pytest_configure`` 检测到 ``_log_path`` 已设置后复用同一文件。

    Returns:
        Path: 本次运行的 ``run-<timestamp>.log`` 绝对路径。
    """
    from tests.support.log_setup import prepare_log_dir
    return prepare_log_dir()


def _run_pytest(pytest_args: List[str]) -> int:
    """在同进程内以 pytest.main 执行并返回退出码。

    Args:
        pytest_args: 完整 pytest 参数列表。

    Returns:
        int: pytest 退出码（透传，不作翻译）。
    """
    import pytest
    print("[run_tests] pytest " + " ".join(pytest_args), flush=True)
    return pytest.main(pytest_args)


# ---------------------------------------------------------------------------
# regression 子命令：旧 perf_regression_checker 的 compare_metrics /
# generate_report / print_report 逻辑移植（归档快照为唯一来源，接口不变）。
# 运行器自包含该逻辑，不依赖 todo-27 新建的 tests/benchmark/perf_regression.py。
# ---------------------------------------------------------------------------


@dataclass
class _PerfMetric:
    """性能指标数据类（移植自旧 perf_regression_checker.PerfMetric）。"""

    name: str
    avg_ms: float
    p95_ms: float
    p99_ms: float
    calls: int = 0


@dataclass
class _RegressionResult:
    """单指标回归检测结果（移植自旧 perf_regression_checker.RegressionResult）。"""

    metric_name: str
    baseline_value: float
    current_value: float
    change_percent: float
    is_regression: bool
    severity: str


def _load_metrics(path: str) -> Dict[str, _PerfMetric]:
    """加载 JSON 性能文件的 events 映射为 ``_PerfMetric``。

    Args:
        path: JSON 文件路径（基线或快照）。

    Returns:
        dict[str, _PerfMetric]: 指标名 → 指标数据。
    """
    with open(path, "r", encoding="utf-8") as f:
        data: Dict[str, Any] = json.load(f)
    metrics: Dict[str, _PerfMetric] = {}
    events: Dict[str, Dict[str, Any]] = data.get("events", {})
    for name, event_data in events.items():
        metrics[name] = _PerfMetric(
            name=name,
            avg_ms=float(event_data.get("avg_ms", 0.0)),
            p95_ms=float(event_data.get("p95_ms", 0.0)),
            p99_ms=float(event_data.get("p99_ms", 0.0)),
            calls=int(event_data.get("calls", 0)),
        )
    return metrics


def _compare_metrics(
    baseline: Dict[str, _PerfMetric],
    current: Dict[str, _PerfMetric],
) -> List[_RegressionResult]:
    """对比基线和当前性能并产出逐指标回归结果。

    Args:
        baseline: 基线指标映射。
        current: 当前指标映射。

    Returns:
        list[_RegressionResult]: 全部指标（新增/缺失/变化）的对比结果。
    """
    results: List[_RegressionResult] = []
    all_metrics: set = set(baseline.keys()) | set(current.keys())
    for metric_name in all_metrics:
        base: Optional[_PerfMetric] = baseline.get(metric_name)
        curr: Optional[_PerfMetric] = current.get(metric_name)
        if base is None:
            results.append(
                _RegressionResult(
                    metric_name=metric_name,
                    baseline_value=0.0,
                    current_value=curr.avg_ms if curr else 0.0,
                    change_percent=float("inf"),
                    is_regression=False,
                    severity="info",
                )
            )
            continue
        if curr is None:
            results.append(
                _RegressionResult(
                    metric_name=metric_name,
                    baseline_value=base.avg_ms,
                    current_value=0.0,
                    change_percent=float("-inf"),
                    is_regression=True,
                    severity="high",
                )
            )
            continue
        if base.avg_ms == 0:
            change_percent: float = 0.0 if curr.avg_ms == 0 else float("inf")
        else:
            change_percent = (curr.avg_ms - base.avg_ms) / base.avg_ms
        is_regression: bool = change_percent > REGRESSION_THRESHOLD
        if change_percent > REGRESSION_THRESHOLD * 2:
            severity: str = "high"
        elif change_percent > REGRESSION_THRESHOLD:
            severity = "medium"
        elif change_percent > 0:
            severity = "low"
        else:
            severity = "improved"
        results.append(
            _RegressionResult(
                metric_name=metric_name,
                baseline_value=base.avg_ms,
                current_value=curr.avg_ms,
                change_percent=change_percent,
                is_regression=is_regression,
                severity=severity,
            )
        )
    return results


def _generate_report(results: List[_RegressionResult]) -> Dict[str, Any]:
    """汇总回归对比报告 dict。

    Args:
        results: 逐指标对比结果。

    Returns:
        dict[str, Any]: summary / regressions / improvements 三段的报告。
    """
    regressions: List[_RegressionResult] = [r for r in results if r.is_regression]
    improvements: List[_RegressionResult] = [r for r in results if r.severity == "improved"]
    unchanged: List[_RegressionResult] = [r for r in results if r.severity == "low"]
    report: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "threshold": REGRESSION_THRESHOLD,
        "summary": {
            "total_metrics": len(results),
            "regressions": len(regressions),
            "improvements": len(improvements),
            "unchanged": len(unchanged),
            "has_regression": len(regressions) > 0,
        },
        "regressions": [
            {
                "metric": r.metric_name,
                "baseline_ms": round(r.baseline_value, 3),
                "current_ms": round(r.current_value, 3),
                "change": f"{r.change_percent:+.1%}",
                "severity": r.severity,
            }
            for r in sorted(regressions, key=lambda x: x.change_percent, reverse=True)
        ],
        "improvements": [
            {
                "metric": r.metric_name,
                "baseline_ms": round(r.baseline_value, 3),
                "current_ms": round(r.current_value, 3),
                "change": f"{r.change_percent:+.1%}",
            }
            for r in sorted(improvements, key=lambda x: x.change_percent)
        ],
    }
    return report


def _print_report(report: Dict[str, Any]) -> None:
    """把回归对比报告打印到控制台。

    Args:
        report: ``_generate_report`` 的产物。
    """
    summary: Dict[str, Any] = report["summary"]
    print("\n" + "=" * 60)
    print("性能回归对比报告（仅报告，不 gate）")
    print("=" * 60)
    print(f"检测时间: {report['timestamp']}")
    print(f"退化阈值: {report['threshold']:.1%}")
    print("-" * 60)
    print(f"总指标数: {summary['total_metrics']}")
    print(f"退化数量: {summary['regressions']}")
    print(f"改进数量: {summary['improvements']}")
    print(f"未变化: {summary['unchanged']}")
    print("-" * 60)
    if report["regressions"]:
        print("\n性能退化项:")
        for item in report["regressions"]:
            severity_icon: str = "HIGH" if item["severity"] == "high" else "med"
            print(f"  [{severity_icon}] {item['metric']} "
                  f"基线 {item['baseline_ms']}ms -> 当前 {item['current_ms']}ms ({item['change']})")
    if report["improvements"]:
        print("\n性能改进项:")
        for item in report["improvements"]:
            print(f"  [improved] {item['metric']} "
                  f"基线 {item['baseline_ms']}ms -> 当前 {item['current_ms']}ms ({item['change']})")
    print("\n" + "=" * 60)


def _latest_perf_snapshot() -> Optional[Path]:
    """返回最新的性能快照文件（perf_metrics_*.json）。

    Returns:
        Optional[Path]: 最新快照路径；目录不存在或无快照时返回 None。
    """
    if not PERF_SNAPSHOT_DIR.is_dir():
        return None
    snapshots: List[Path] = sorted(
        PERF_SNAPSHOT_DIR.glob("perf_metrics_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return snapshots[0] if snapshots else None


def _run_regression(args: argparse.Namespace) -> int:
    """执行 regression：跑 benchmark 后对比基线并打印报告。

    退出码恒 0（仅报告，不作为性能 gate）——与 Scope"禁止性能秒数上限
    gate"及 todo-27 Momus 修正一致。仅当基线文件或当前快照缺失（基础设施
    未就绪）时返回 1。

    Args:
        args: 解析后的参数命名空间。

    Returns:
        int: 0（正常对比完成）；1（基线/快照缺失或对比失败）。
    """
    benchmark_args: List[str] = build_pytest_args("regression", args)
    print("[run_tests] [regression] 步骤 1/2: 运行 benchmark 套件", flush=True)
    _run_pytest(benchmark_args)

    if not PERF_BASELINE.exists():
        print(f"[run_tests] [regression] 错误: 回归基线不存在: {PERF_BASELINE} "
              f"（请先运行 benchmark 子命令生成）", file=sys.stderr, flush=True)
        return 1

    current_snapshot: Optional[Path] = _latest_perf_snapshot()
    if current_snapshot is None:
        print("[run_tests] [regression] 错误: 未发现性能快照 "
              "perf_metrics_*.json，无法对比", file=sys.stderr, flush=True)
        return 1

    print(f"[run_tests] [regression] 步骤 2/2: 对比基线 {PERF_BASELINE.name} "
          f"vs 当前 {current_snapshot.name}", flush=True)
    baseline_metrics: Dict[str, _PerfMetric] = _load_metrics(str(PERF_BASELINE))
    current_metrics: Dict[str, _PerfMetric] = _load_metrics(str(current_snapshot))
    results: List[_RegressionResult] = _compare_metrics(baseline_metrics, current_metrics)
    report: Dict[str, Any] = _generate_report(results)
    _print_report(report)
    # 仅报告：即使检测到退化也返回 0，不 gate（计划 todo-27）。
    return 0


def _run_coverage(args: argparse.Namespace) -> int:
    """执行 coverage：同 all 范围 + 覆盖率选项；``--strict`` 再跑 manifest。

    Args:
        args: 解析后的参数命名空间。

    Returns:
        int: pytest 退出码；``--strict`` 时若 pytest 通过则返回 manifest 结果。
    """
    pytest_args: List[str] = build_pytest_args("coverage", args)
    pytest_args.extend(["--cov=freeassetfilter", "--cov-report=term"])
    code: int = _run_pytest(pytest_args)
    if code != 0 or not args.strict:
        return code
    from tests.support import coverage_manifest
    print("[run_tests] [coverage] --strict: 运行 coverage_manifest", flush=True)
    return coverage_manifest.main(["--strict"])


def _run_layered(command: str, args: argparse.Namespace) -> int:
    """执行分层 / all / gui / benchmark 子命令（单一 pytest 进程）。

    Args:
        command: 当前子命令名。
        args: 解析后的参数命名空间。

    Returns:
        int: pytest 退出码（原样透传）。
    """
    return _run_pytest(build_pytest_args(command, args))


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """解析命令行参数。

    Args:
        argv: 命令行参数；None 时取 sys.argv[1:]。

    Returns:
        argparse.Namespace: 解析结果。
    """
    parser = argparse.ArgumentParser(
        prog="run_tests",
        description="FreeAssetFilter 统一测试运行器：分层/全覆盖/覆盖率/回归。",
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="all",
        choices=SUBCOMMANDS,
        help="子命令（默认 all）：all | unit | widgets | components | integration "
             "| gui | benchmark | coverage | regression",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        metavar="N",
        help="CLI 兜底超时秒数（仅对无 marker 测试生效；marker 优先；"
             "benchmark/regression 默认 300，其余 30）",
    )
    parser.add_argument(
        "-k",
        dest="k",
        metavar="EXPR",
        help="按表达式过滤测试（原样透传 pytest -k）",
    )
    parser.add_argument(
        "--tb",
        choices=["auto", "long", "short", "no", "line", "native"],
        default=None,
        help="回溯格式（默认继承 pytest.ini 的 --tb=short）",
    )
    parser.add_argument(
        "-x",
        "--exitfirst",
        action="store_true",
        help="首个失败即停止（透传 pytest -x）",
    )
    parser.add_argument(
        "--co",
        "--collect-only",
        action="store_true",
        dest="co",
        help="仅收集不执行（透传 pytest --collect-only，验收用）",
    )
    parser.add_argument(
        "--visual",
        action="store_true",
        help="取消默认 QT_QPA_PLATFORM=offscreen（真实显示器场景）",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="仅 coverage 子命令有效：额外以 --strict 运行 coverage_manifest",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """统一运行器入口。

    Args:
        argv: 命令行参数；None 时取 sys.argv[1:]。

    Returns:
        int: 透传的 pytest / manifest 退出码。
    """
    _ensure_sys_path()
    args: argparse.Namespace = _parse_args(argv)

    if args.strict and args.command != "coverage":
        print(f"[run_tests] 警告: --strict 仅对 coverage 子命令有意义，"
              f"本次 {args.command} 忽略该选项", file=sys.stderr, flush=True)

    log_path: Path = _prepare_log_dir()
    print(f"[run_tests] 子命令={args.command} | 测试日志: {log_path}", flush=True)
    _configure_platform(args.command, args.visual)

    if args.command == "coverage":
        return _run_coverage(args)
    if args.command == "regression":
        return _run_regression(args)
    return _run_layered(args.command, args)


if __name__ == "__main__":
    sys.exit(main())