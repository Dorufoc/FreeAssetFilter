# -*- coding: utf-8 -*-
"""
性能回归检测工具

功能：
- 加载历史性能基线
- 运行当前性能测试
- 对比性能差异
- 生成回归报告
- 支持 CI/CD 集成

用法：
    python perf_regression_checker.py --baseline baseline.json --threshold 0.15
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


@dataclass
class PerfMetric:
    """性能指标数据类"""
    name: str
    avg_ms: float
    p95_ms: float
    p99_ms: float
    calls: int = 0


@dataclass
class RegressionResult:
    """回归检测结果"""
    metric_name: str
    baseline_value: float
    current_value: float
    change_percent: float
    is_regression: bool
    severity: str  # "low", "medium", "high"


class PerformanceRegressionChecker:
    """性能回归检测器"""

    def __init__(self, threshold: float = 0.15):
        """
        初始化检测器

        Args:
            threshold: 性能退化阈值（默认 15%）
        """
        self.threshold = threshold
        self.results: List[RegressionResult] = []

    def load_baseline(self, baseline_path: str) -> Dict[str, PerfMetric]:
        """加载性能基线数据"""
        with open(baseline_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        metrics = {}
        events = data.get("events", {})
        for name, event_data in events.items():
            metrics[name] = PerfMetric(
                name=name,
                avg_ms=event_data.get("avg_ms", 0.0),
                p95_ms=event_data.get("p95_ms", 0.0),
                p99_ms=event_data.get("p99_ms", 0.0),
                calls=event_data.get("calls", 0),
            )
        return metrics

    def load_current(self, current_path: str) -> Dict[str, PerfMetric]:
        """加载当前性能数据"""
        return self.load_baseline(current_path)

    def compare_metrics(
        self,
        baseline: Dict[str, PerfMetric],
        current: Dict[str, PerfMetric],
    ) -> List[RegressionResult]:
        """对比基线和当前性能数据"""
        results = []

        # 检查所有指标
        all_metrics = set(baseline.keys()) | set(current.keys())

        for metric_name in all_metrics:
            baseline_metric = baseline.get(metric_name)
            current_metric = current.get(metric_name)

            if baseline_metric is None:
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
                # 缺失指标
                results.append(
                    RegressionResult(
                        metric_name=metric_name,
                        baseline_value=baseline_metric.avg_ms,
                        current_value=0.0,
                        change_percent=float("-inf"),
                        is_regression=True,
                        severity="high",
                    )
                )
                continue

            # 计算变化百分比
            baseline_value = baseline_metric.avg_ms
            current_value = current_metric.avg_ms

            if baseline_value == 0:
                change_percent = 0.0 if current_value == 0 else float("inf")
            else:
                change_percent = (current_value - baseline_value) / baseline_value

            # 判断是否为回归（性能变差）
            is_regression = change_percent > self.threshold

            # 确定严重程度
            if change_percent > self.threshold * 2:
                severity = "high"
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

        return results

    def generate_report(self, results: List[RegressionResult]) -> Dict[str, Any]:
        """生成回归检测报告"""
        regressions = [r for r in results if r.is_regression]
        improvements = [r for r in results if r.severity == "improved"]
        unchanged = [r for r in results if r.severity == "low"]

        report = {
            "timestamp": datetime.now().isoformat(),
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
        """打印回归检测报告"""
        summary = report["summary"]

        print("\n" + "=" * 60)
        print("性能回归检测报告")
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
            print("\n⚠️  性能退化项:")
            for item in report["regressions"]:
                severity_icon = "🔴" if item["severity"] == "high" else "🟡"
                print(f"  {severity_icon} {item['metric']}")
                print(f"     基线: {item['baseline_ms']}ms -> 当前: {item['current_ms']}ms ({item['change']})")

        if report["improvements"]:
            print("\n✅ 性能改进项:")
            for item in report["improvements"]:
                print(f"  🟢 {item['metric']}")
                print(f"     基线: {item['baseline_ms']}ms -> 当前: {item['current_ms']}ms ({item['change']})")

        print("\n" + "=" * 60)
        if summary["has_regression"]:
            print("❌ 检测到性能退化！")
        else:
            print("✅ 未检测到性能退化")
        print("=" * 60)


def run_benchmark_tests(test_pattern: str = "tests/benchmark/") -> str:
    """运行基准测试并返回性能快照路径"""
    import tempfile

    # 创建临时输出文件
    output_file = tempfile.mktemp(suffix="_perf_snapshot.json")

    # 运行 pytest 基准测试
    cmd = [
        sys.executable, "-m", "pytest",
        test_pattern,
        "-v",
        "--tb=short",
    ]

    print(f"运行基准测试: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"基准测试运行失败:\n{result.stderr}")
        # 即使测试失败也继续，可能有部分结果

    # 查找最新的性能快照
    perf_dir = os.path.expanduser("~/.freeassetfilter/performance")
    if os.path.exists(perf_dir):
        snapshots = sorted(
            [f for f in os.listdir(perf_dir) if f.startswith("perf_metrics_")],
            reverse=True
        )
        if snapshots:
            return os.path.join(perf_dir, snapshots[0])

    return output_file


def main():
    parser = argparse.ArgumentParser(description="性能回归检测工具")
    parser.add_argument(
        "--baseline",
        type=str,
        required=True,
        help="性能基线文件路径 (JSON)"
    )
    parser.add_argument(
        "--current",
        type=str,
        default=None,
        help="当前性能数据路径 (JSON)，不指定则运行测试"
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.15,
        help="性能退化阈值 (默认 15%%)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="perf_regression_report.json",
        help="报告输出路径"
    )
    parser.add_argument(
        "--run-tests",
        action="store_true",
        help="运行基准测试获取当前数据"
    )
    parser.add_argument(
        "--test-pattern",
        type=str,
        default="tests/benchmark/",
        help="测试文件匹配模式"
    )

    args = parser.parse_args()

    # 检查基线文件
    if not os.path.exists(args.baseline):
        print(f"错误: 基线文件不存在: {args.baseline}")
        sys.exit(1)

    # 获取当前性能数据
    if args.run_tests or args.current is None:
        print("运行基准测试获取当前性能数据...")
        args.current = run_benchmark_tests(args.test_pattern)
        print(f"性能快照: {args.current}")

    if not os.path.exists(args.current):
        print(f"错误: 当前性能数据文件不存在: {args.current}")
        sys.exit(1)

    # 执行回归检测
    checker = PerformanceRegressionChecker(threshold=args.threshold)

    print(f"\n加载基线数据: {args.baseline}")
    baseline = checker.load_baseline(args.baseline)

    print(f"加载当前数据: {args.current}")
    current = checker.load_current(args.current)

    print(f"\n对比性能数据...")
    results = checker.compare_metrics(baseline, current)

    report = checker.generate_report(results)
    checker.print_report(report)

    # 保存报告
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n报告已保存: {args.output}")

    # 根据回归情况设置退出码
    if report["summary"]["has_regression"]:
        sys.exit(2)  # 性能退化
    else:
        sys.exit(0)  # 正常


if __name__ == "__main__":
    main()
