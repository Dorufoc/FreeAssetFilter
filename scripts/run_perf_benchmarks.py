# -*- coding: utf-8 -*-
"""
性能基准测试运行脚本

功能：
- 运行所有基准测试
- 生成性能基线文件
- 生成性能报告
- 支持 CI/CD 集成

用法：
    python scripts/run_perf_benchmarks.py [--baseline] [--output-dir ./perf_reports]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


def get_project_root() -> Path:
    """获取项目根目录"""
    return Path(__file__).parent.parent


def run_benchmark_tests(test_dir: str, verbose: bool = True) -> bool:
    """运行基准测试"""
    project_root = get_project_root()
    test_path = project_root / test_dir

    if not test_path.exists():
        print(f"错误: 测试目录不存在: {test_path}")
        return False

    cmd = [
        sys.executable, "-m", "pytest",
        str(test_path),
        "-v",
        "--tb=short",
    ]

    if verbose:
        print(f"运行基准测试: {' '.join(cmd)}")

    result = subprocess.run(cmd, cwd=project_root)
    return result.returncode == 0


def collect_perf_snapshots() -> List[Path]:
    """收集所有性能快照文件"""
    # 性能快照通常保存在应用数据目录
    app_data_dir = Path.home() / ".freeassetfilter" / "performance"

    if not app_data_dir.exists():
        return []

    # 获取最近 24 小时内的快照
    snapshots = []
    cutoff_time = datetime.now().timestamp() - 24 * 3600

    for f in app_data_dir.iterdir():
        if f.name.startswith("perf_metrics_") and f.suffix == ".json":
            if f.stat().st_mtime > cutoff_time:
                snapshots.append(f)

    return sorted(snapshots, key=lambda x: x.stat().st_mtime, reverse=True)


def merge_perf_snapshots(snapshots: List[Path]) -> Dict:
    """合并多个性能快照"""
    merged = {
        "timestamp": datetime.now().isoformat(),
        "sources": [],
        "events": {},
    }

    for snapshot_path in snapshots:
        try:
            with open(snapshot_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            merged["sources"].append({
                "file": str(snapshot_path),
                "timestamp": data.get("timestamp", "unknown"),
            })

            # 合并事件数据
            events = data.get("events", {})
            for name, event_data in events.items():
                if name not in merged["events"]:
                    merged["events"][name] = event_data
                else:
                    # 合并统计数据
                    existing = merged["events"][name]
                    existing["calls"] += event_data.get("calls", 0)
                    existing["total_ms"] += event_data.get("total_ms", 0)
                    # 重新计算平均值
                    if existing["calls"] > 0:
                        existing["avg_ms"] = round(
                            existing["total_ms"] / existing["calls"], 3
                        )

        except Exception as e:
            print(f"警告: 无法读取快照 {snapshot_path}: {e}")

    return merged


def generate_baseline(output_path: str, snapshots: Optional[List[Path]] = None) -> bool:
    """生成性能基线文件"""
    if snapshots is None:
        snapshots = collect_perf_snapshots()

    if not snapshots:
        print("警告: 未找到性能快照，无法生成基线")
        return False

    print(f"\n找到 {len(snapshots)} 个性能快照")

    merged = merge_perf_snapshots(snapshots)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    print(f"基线文件已生成: {output_path}")

    # 打印摘要
    events = merged.get("events", {})
    print(f"\n性能指标摘要 ({len(events)} 个指标):")
    for name, data in sorted(events.items()):
        avg_ms = data.get("avg_ms", 0)
        calls = data.get("calls", 0)
        print(f"  {name}: {avg_ms:.2f}ms (calls: {calls})")

    return True


def generate_report(output_dir: str) -> bool:
    """生成性能测试报告"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    snapshots = collect_perf_snapshots()
    if not snapshots:
        print("警告: 未找到性能快照")
        return False

    # 生成基线
    baseline_path = output_path / f"baseline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    generate_baseline(str(baseline_path), snapshots)

    # 生成 Markdown 报告
    merged = merge_perf_snapshots(snapshots)
    report_path = output_path / f"perf_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# FreeAssetFilter 性能基准测试报告\n\n")
        f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

        f.write("## 性能指标汇总\n\n")
        f.write("| 指标名称 | 平均耗时 (ms) | P95 (ms) | P99 (ms) | 调用次数 |\n")
        f.write("|---------|-------------|---------|---------|---------|\n")

        events = merged.get("events", {})
        for name, data in sorted(events.items()):
            avg_ms = data.get("avg_ms", 0)
            p95_ms = data.get("p95_ms", 0)
            p99_ms = data.get("p99_ms", 0)
            calls = data.get("calls", 0)
            f.write(f"| {name} | {avg_ms:.2f} | {p95_ms:.2f} | {p99_ms:.2f} | {calls} |\n")

    print(f"\n报告已生成: {report_path}")
    return True


def main():
    parser = argparse.ArgumentParser(description="性能基准测试运行脚本")
    parser.add_argument(
        "--test-dir",
        type=str,
        default="tests/benchmark/",
        help="基准测试目录 (默认: tests/benchmark/)"
    )
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="生成性能基线文件"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./perf_reports",
        help="报告输出目录 (默认: ./perf_reports)"
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="快速模式：跳过测试运行，只生成报告"
    )

    args = parser.parse_args()

    print("=" * 60)
    print("FreeAssetFilter 性能基准测试")
    print("=" * 60)

    # 运行基准测试
    if not args.quick:
        print("\n1. 运行基准测试...")
        if not run_benchmark_tests(args.test_dir):
            print("警告: 部分测试失败，但继续生成报告")
    else:
        print("\n1. 快速模式：跳过测试运行")

    # 生成报告
    print("\n2. 生成性能报告...")
    output_path = Path(args.output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    if args.baseline:
        baseline_file = output_path / f"baseline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        generate_baseline(str(baseline_file))
    else:
        generate_report(args.output_dir)

    print("\n" + "=" * 60)
    print("性能基准测试完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
