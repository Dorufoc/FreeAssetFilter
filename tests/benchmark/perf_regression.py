# -*- coding: utf-8 -*-
"""性能回归检测器（todo-27：旧 perf_regression_checker 逻辑迁入）。

从归档快照 ``old-tests-snapshot/tests/benchmark/perf_regression_checker.py``
迁入 ``PerfMetric`` / ``RegressionResult`` 数据类与
``PerformanceRegressionChecker`` 的 compare / generate / print 逻辑。

契约要点（V3 审计 / Momus 修正）：

* **方法名是 ``PerformanceRegressionChecker.compare_metrics``**——旧
  ``compare`` 是错误命名，与 ``tests/run_tests.py`` regression 子命令的
  ``_compare_metrics`` 对齐；
* **仅报告、不 gate**：本模块任何路径都不把"检测到退化"当作失败条件，
  退出码语义由调用方决定（run_tests.py regression 恒返回 0）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

#: 性能退化阈值（默认 15%，与 run_tests.py 的 REGRESSION_THRESHOLD 一致）。
DEFAULT_THRESHOLD: float = 0.15


@dataclass
class PerfMetric:
    """性能指标数据类（字段与旧 PerfMetric 一致）。"""

    name: str
    avg_ms: float
    p95_ms: float
    p99_ms: float
    calls: int = 0


@dataclass
class RegressionResult:
    """单指标回归检测结果。

    ``severity`` 取值：``improved`` / ``low`` / ``medium`` / ``high`` /
    ``info``（新增指标），与旧实现一致。
    """

    metric_name: str
    baseline_value: float
    current_value: float
    change_percent: float
    is_regression: bool
    severity: str


class PerformanceRegressionChecker:
    """性能回归检测器：加载基线 → 对比当前 → 生成报告（不 gate）。"""

    def __init__(self, threshold: float = DEFAULT_THRESHOLD) -> None:
        """初始化检测器。

        Args:
            threshold: 性能退化阈值（变化百分比超过该值视为退化，
                默认 15%）。
        """
        self.threshold: float = threshold
        self.results: List[RegressionResult] = []

    def load_baseline(self, baseline_path: str) -> Dict[str, PerfMetric]:
        """从 JSON 性能文件加载基线指标映射。

        Args:
            baseline_path: 基线 JSON 文件路径（结构含 ``events`` 映射）。

        Returns:
            dict[str, PerfMetric]: 指标名 → 指标数据。
        """
        metrics: Dict[str, PerfMetric] = {}
        for name, event_data in self._load_events(baseline_path).items():
            metrics[name] = PerfMetric(
                name=name,
                avg_ms=float(event_data.get("avg_ms", 0.0)),
                p95_ms=float(event_data.get("p95_ms", 0.0)),
                p99_ms=float(event_data.get("p99_ms", 0.0)),
                calls=int(event_data.get("calls", 0)),
            )
        return metrics

    def load_current(self, current_path: str) -> Dict[str, PerfMetric]:
        """加载当前性能数据（与 load_baseline 同构）。

        Args:
            current_path: 当前性能 JSON 文件路径。

        Returns:
            dict[str, PerfMetric]: 指标名 → 指标数据。
        """
        return self.load_baseline(current_path)

    def compare_metrics(
        self,
        baseline: Dict[str, PerfMetric],
        current: Dict[str, PerfMetric],
    ) -> List[RegressionResult]:
        """对比基线和当前性能并产出逐指标回归结果。

        接口为 ``compare_metrics``（V3 审计修正；旧快照的 ``compare``
        是错误的命名）。

        Args:
            baseline: 基线指标映射。
            current: 当前指标映射。

        Returns:
            list[RegressionResult]: 全部指标（新增/缺失/变化）的对比结果。
        """
        results: List[RegressionResult] = []
        all_metrics: set = set(baseline.keys()) | set(current.keys())

        for metric_name in all_metrics:
            base_metric: Optional[PerfMetric] = baseline.get(metric_name)
            current_metric: Optional[PerfMetric] = current.get(metric_name)

            if base_metric is None:
                # 新增指标
                results.append(
                    RegressionResult(
                        metric_name=metric_name,
                        baseline_value=0.0,
                        current_value=current_metric.avg_ms if current_metric else 0.0,
                        change_percent=float("inf"),
                        is_regression=False,
                        severity="info",
                    )
                )
                continue

            if current_metric is None:
                # 指标缺失（性能能力回退，视为高严重度）
                results.append(
                    RegressionResult(
                        metric_name=metric_name,
                        baseline_value=base_metric.avg_ms,
                        current_value=0.0,
                        change_percent=float("-inf"),
                        is_regression=True,
                        severity="high",
                    )
                )
                continue

            # 计算变化百分比
            baseline_value: float = base_metric.avg_ms
            current_value: float = current_metric.avg_ms

            if baseline_value == 0:
                change_percent: float = 0.0 if current_value == 0 else float("inf")
            else:
                change_percent = (current_value - baseline_value) / baseline_value

            # 判断是否为退化（性能变差）
            is_regression: bool = change_percent > self.threshold

            # 确定严重程度
            if change_percent > self.threshold * 2:
                severity: str = "high"
            elif change_percent > self.threshold:
                severity = "medium"
            elif change_percent > 0:
                severity = "low"
            else:
                severity = "improved"

            results.append(
                RegressionResult(
                    metric_name=metric_name,
                    baseline_value=baseline_value,
                    current_value=current_value,
                    change_percent=change_percent,
                    is_regression=is_regression,
                    severity=severity,
                )
            )

        self.results = results
        return results

    def generate_report(self, results: List[RegressionResult]) -> Dict[str, Any]:
        """汇总回归对比报告 dict。

        Args:
            results: ``compare_metrics`` 的产物。

        Returns:
            dict[str, Any]: ``summary`` / ``regressions`` /
            ``improvements`` 三段的报告结构。
        """
        regressions: List[RegressionResult] = [r for r in results if r.is_regression]
        improvements: List[RegressionResult] = [
            r for r in results if r.severity == "improved"
        ]
        unchanged: List[RegressionResult] = [
            r for r in results if r.severity == "low"
        ]

        report: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "threshold": self.threshold,
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

    def print_report(self, report: Dict[str, Any]) -> None:
        """把回归对比报告打印到控制台（仅报告，不 gate）。

        Args:
            report: ``generate_report`` 的产物。
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
                print(
                    f"  [{severity_icon}] {item['metric']} "
                    f"基线 {item['baseline_ms']}ms -> 当前 {item['current_ms']}ms "
                    f"({item['change']})"
                )

        if report["improvements"]:
            print("\n性能改进项:")
            for item in report["improvements"]:
                print(
                    f"  [improved] {item['metric']} "
                    f"基线 {item['baseline_ms']}ms -> 当前 {item['current_ms']}ms "
                    f"({item['change']})"
                )

        print("\n" + "=" * 60)

    @staticmethod
    def _load_events(path: str) -> Dict[str, Dict[str, Any]]:
        """读取 JSON 性能文件的 events 映射。

        Args:
            path: JSON 文件路径（基线或快照）。

        Returns:
            dict[str, dict]: events 映射；文件格式异常时返回空字典。
        """
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data: Dict[str, Any] = json.load(fh)
        except (OSError, ValueError):
            return {}
        events: Dict[str, Any] = data.get("events", {})
        return {name: dict(item) for name, item in events.items()}


def main(argv: Optional[List[str]] = None) -> int:
    """命令行入口：对比基线/当前并打印报告，恒返回 0（仅报告不 gate）。

    Args:
        argv: 命令行参数；None 时取 ``sys.argv[1:]``。

    Returns:
        int: 恒 0（无论是否检测到退化，都不作为失败条件）。
    """
    import argparse
    import os
    import sys

    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="性能回归对比（仅报告，不 gate）",
    )
    parser.add_argument(
        "--baseline",
        type=str,
        required=True,
        help="性能基线 JSON 文件路径",
    )
    parser.add_argument(
        "--current",
        type=str,
        default=None,
        help="当前性能 JSON 文件路径（缺省时尝试读环境变量 PERF_CURRENT）",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"退化阈值（默认 {DEFAULT_THRESHOLD:.0%}）",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="报告 JSON 输出路径（写入后仍不 gate）",
    )
    args: argparse.Namespace = parser.parse_args(argv)

    current_path: str = args.current or os.environ.get(
        "PERF_CURRENT", "perf_current.json"
    )
    if not os.path.exists(args.baseline) or not os.path.exists(current_path):
        print(f"错误: 基线或当前文件不存在（baseline={args.baseline}, "
              f"current={current_path}）", file=sys.stderr)
        return 1

    checker: PerformanceRegressionChecker = PerformanceRegressionChecker(
        threshold=args.threshold
    )
    baseline_metrics: Dict[str, PerfMetric] = checker.load_baseline(args.baseline)
    current_metrics: Dict[str, PerfMetric] = checker.load_current(current_path)
    results: List[RegressionResult] = checker.compare_metrics(
        baseline_metrics, current_metrics
    )
    report: Dict[str, Any] = checker.generate_report(results)
    checker.print_report(report)

    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
        print(f"\n报告已保存: {args.output}")

    # 仅报告：即使存在退化也返回 0（计划 todo-27 Momus 修正）。
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())