"""pytest 进度报告：计数、周期小结与最慢测试缓冲。

包装两条 hook：

* :func:`pytest_runtest_logreport` —— 每次测试 call 阶段计数，满足
  "距上次小结 ≥ 60s"或"已累计 200 个测试"之一即打印一行进度小结，
  并维护当轮（本轮会话内）最慢测试的滚动缓冲（默认 5 个）；
* :func:`pytest_terminal_summary` —— 会话结束时输出 top-N 最慢测试。

模块保持无产品依赖：``tests/support/`` 内的纯工具，可被 conftest 或
运行器通过 ``pytest_plugins`` / pluginmanager 直接挂载。
"""

from __future__ import annotations

import time
from typing import Any, List, Optional, Tuple

#: 进度小结的两个触发阈值。
_SUMMARY_INTERVAL_SECONDS: float = 60.0
_SUMMARY_INTERVAL_TESTS: int = 200

#: 滚动缓冲保留的最慢测试数量。
_SLOW_BUDGET: int = 5

#: 会话收尾输出的最慢测试数量。
_TOP_N: int = 5


def _format_seconds(seconds: float) -> str:
    """把秒数格式化为易读字符串。

    Args:
        seconds: 秒数（可为 0）。

    Returns:
        str: 形如 ``1234.5s`` 或 ``0.004s`` 的文本。
    """
    return f"{seconds:.3f}s"


class ProgressReporter:
    """会话级进度状态容器。

    维护计数器、上次小结时间与最慢缓冲。每个测试会话应重置一次
    （:meth:`reset` 由运行器或 conftest 在启动时调用）。
    """

    def __init__(self) -> None:
        self._total: int = 0
        self._passed: int = 0
        self._failed: int = 0
        self._skipped: int = 0
        self._next_summary_at: float = time.monotonic() + _SUMMARY_INTERVAL_SECONDS
        #: 滚动缓冲：已按耗时降序排列的 (耗秒, nodeid) 列表，最长 _SLOW_BUDGET。
        self._slowest: List[Tuple[float, str]] = []
        self._announced_tests: int = 0

    def reset(self) -> None:
        """清空全部状态，供下一个会话复用。"""
        self.__init__()

    def report(self, nodeid: str, duration: float, outcome: str) -> None:
        """登记一次 call 阶段结果并触发周期小结。

        Args:
            nodeid: 测试的 nodeid。
            duration: call 阶段耗时（``report.duration``，秒）。
            outcome: ``passed`` / ``failed`` / ``skipped``。
        """
        self._total += 1
        if outcome == "passed":
            self._passed += 1
        elif outcome == "failed":
            self._failed += 1
        else:
            self._skipped += 1
        self._record_slow(nodeid, duration)
        now: float = time.monotonic()
        if self._total % _SUMMARY_INTERVAL_TESTS == 0 or now >= self._next_summary_at:
            self._print_summary()
            self._next_summary_at = now + _SUMMARY_INTERVAL_SECONDS

    def _record_slow(self, nodeid: str, duration: float) -> None:
        """把测试插入最慢滚动缓冲（保持降序、截断到预算长度）。

        Args:
            nodeid: 测试 nodeid。
            duration: 耗时（秒）。
        """
        self._slowest.append((duration, nodeid))
        self._slowest.sort(key=lambda pair: pair[0], reverse=True)
        del self._slowest[_SLOW_BUDGET:]

    def _print_summary(self) -> None:
        """打印一行进度小结（走 print，供控制台与日志 Tee 双写）。"""
        latest: str = self._slowest[0][1] if self._slowest else "-"
        print(
            f"[progress] 已完成 {self._total} 个测试 "
            f"(通过 {self._passed} / 失败 {self._failed} / 跳过 {self._skipped})；"
            f"当前最慢: {latest} "
            f"({_format_seconds(self._slowest[0][0]) if self._slowest else '-s'})",
            flush=True,
        )

    def slowest(self, top_n: int = _TOP_N) -> List[Tuple[float, str]]:
        """返回当前缓冲中最慢的若干测试。

        Args:
            top_n: 返回数量上限（不超过滚动缓冲长度）。

        Returns:
            list[tuple[float, str]]: 降序的 (耗秒, nodeid)。
        """
        return self._slowest[:top_n]

    def totals(self) -> Tuple[int, int, int, int]:
        """汇总计数器。

        Returns:
            tuple[int, int, int, int]: (total, passed, failed, skipped)。
        """
        return self._total, self._passed, self._failed, self._skipped


#: 模块级单例 reporter（hook 包装函数共享同一状态）。
_reporter: ProgressReporter = ProgressReporter()


def get_reporter() -> ProgressReporter:
    """返回模块级 reporter 实例。

    Returns:
        ProgressReporter: 会话状态容器。
    """
    return _reporter


def reset_progress() -> None:
    """重置模块级 reporter（供测试隔离或会话复用）。"""
    _reporter.reset()


def pytest_runtest_logreport(report: Any) -> None:
    """pytest hook：按 report 的 call 阶段登记结果与耗时。

    Args:
        report: pytest 的 TestReport。
    """
    if getattr(report, "when", None) != "call":
        return
    # pytest 9.1.0 移除 TestReport.get_outcome()；outcome 现为实例属性
    # （todo-5 发现的 todo-3 遗留兼容缺陷，2 处调用点同步修正）。
    outcome: str = str(getattr(report, "outcome", "failed"))
    if outcome in ("failed", "passed", "skipped"):
        _reporter.report(
            nodeid=str(report.nodeid),
            duration=float(getattr(report, "duration", 0.0) or 0.0),
            outcome=outcome,
        )


def pytest_terminal_summary(
    terminalreporter: Any,
    exitstatus: Any,
    config: Optional[Any] = None,
) -> None:
    """pytest hook：会话结束时打印最慢测试 top-N。

    Args:
        terminalreporter: pytest 的 TerminalReporter。
        exitstatus: 会话退出码。
        config: pytest 配置（未使用，仅为 hook 签名兼容）。
    """
    total, passed, failed, skipped = _reporter.totals()
    if total == 0:
        return
    print(f"\n[summary] 共 {total} 个测试 | 通过 {passed} / 失败 {failed} / 跳过 {skipped}")
    slowest_list: List[Tuple[float, str]] = _reporter.slowest()
    if not slowest_list:
        return
    print("[summary] top-5 最慢测试：")
    for rank, (duration, nodeid) in enumerate(slowest_list, start=1):
        print(f"  {rank}. {nodeid}  {_format_seconds(duration)}")