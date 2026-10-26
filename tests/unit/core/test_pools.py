# -*- coding: utf-8 -*-
"""线程池分层与预算测试（P6.2）。

锁定四条契约：

1. **预算收敛**：各命名池之和 + 两个 rayon 池 + 预留 ≤ ``THREAD_CEILING``；
2. **命名池单例**：``pool(name)`` 幂等，``maxThreadCount`` 等于预算；
3. **投递可用**：``start()`` 能在池线程执行 runnable 并完成线程命名；
4. **全局池退场**：``freeassetfilter/**`` 内除 ``app/main.py`` 的兜底限流外
   不得再出现 ``QThreadPool.globalInstance`` 调用（AST 扫描）。

验证命令：
    python -m pytest tests/unit/core/test_pools.py -v
"""

from __future__ import annotations

import ast
import threading
from pathlib import Path
from typing import Any, List

import pytest
from PySide6.QtCore import QRunnable

from freeassetfilter.core import pools

pytestmark = pytest.mark.unit

_REPO_ROOT: Path = Path(__file__).resolve().parents[3]
#: 允许调用 ``QThreadPool.globalInstance`` 的唯一位置（第三方兜底限流）。
_ALLOWED_GLOBAL_POOL = {"main.py"}


@pytest.fixture(autouse=True)
def _reset_pools() -> Any:
    """每个用例前后重置池单例。"""
    pools.reset_for_tests()
    yield
    pools.reset_for_tests()


def test_budget_within_ceiling() -> None:
    """Python 池 + 两个 rayon 池 + 预留不得超过进程上限。"""
    allocations = pools.snapshot()["budget"]["allocations"]
    total = sum(allocations.values())
    assert total <= pools.PYTHON_TOTAL
    assert (
        total + 2 * pools.RAYON_PER_POOL + pools.RESERVED_INPROC
        <= pools.THREAD_CEILING
    )
    assert pools.budget("interactive") >= 2
    assert pools.budget("decode") >= 2
    assert pools.budget("background") >= 1


def test_pool_singleton_and_limit() -> None:
    """``pool()`` 幂等且 maxThreadCount 等于预算。"""
    first = pools.pool("io")
    second = pools.pool("io")
    assert first is second
    assert first.maxThreadCount() == pools.budget("io")
    assert first.objectName() == "faf-io"


def test_start_runs_on_named_pool() -> None:
    """``start()`` 在池线程执行并完成线程命名。"""
    done = threading.Event()
    captured: List[str] = []

    class _Probe(QRunnable):
        def run(self) -> None:  # noqa: D102
            captured.append(threading.current_thread().name)
            done.set()

    pools.start(_Probe(), pool_name="background")
    assert done.wait(5.0), "任务未在池线程完成"
    assert captured, "未捕获到执行线程名"
    assert threading.current_thread().name != captured[0], "任务不应跑在调用线程"


def test_shutdown_clears_pools() -> None:
    """``shutdown()`` 释放池单例。"""
    pools.pool("interactive")
    assert pools.snapshot()["pools"], "应已创建池"
    pools.shutdown(500)
    assert pools.snapshot()["pools"] == {}


def test_snapshot_shape() -> None:
    """线程账本包含预算与池状态。"""
    pools.pool("decode")
    snapshot = pools.snapshot()
    assert "budget" in snapshot and "pools" in snapshot
    assert snapshot["budget"]["ceiling"] == pools.THREAD_CEILING
    assert snapshot["pools"]["decode"]["max"] == pools.budget("decode")


def test_no_global_pool_calls_outside_main() -> None:
    """AST 扫描：业务代码不得再调用 ``QThreadPool.globalInstance``。"""
    offenders: List[str] = []
    for path in ( _REPO_ROOT / "freeassetfilter").rglob("*.py"):
        if path.name in _ALLOWED_GLOBAL_POOL:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):  # pragma: no cover - 损坏文件跳过
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "globalInstance"
                and isinstance(func.value, ast.Name)
                and func.value.id == "QThreadPool"
            ):
                offenders.append(f"{path.relative_to(_REPO_ROOT)}:{node.lineno}")
    assert not offenders, f"仍有业务代码使用全局池: {offenders}"
