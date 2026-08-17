"""pytest 超时策略：marker→超时映射与自动打标辅助。

本模块是验收超时语义的**单一事实源**。三级优先级（从高到低）：

1. 显式 ``@pytest.mark.timeout(N)`` —— 已显式标记的测试绝不被改写；
2. 自动打标 —— :func:`apply_timeout` 按测试目录层级给未标记项打上
   ``@pytest.mark.timeout(N)``；
3. CLI ``--timeout`` —— 仅兜底那些既无显式 marker 又未被自动打标的测试
   （pytest-timeout 只在测试没有 timeout marker 时才读取配置项）。

因此**运行器的 ``--timeout`` 永不覆盖任何 marker**；本模块在
``pytest_collection_modifyitems`` 中通过 :func:`apply_timeout` 消费 items，
目录层级与 marker 的换算关系见 :data:`TIMEOUT_TIERS`。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Iterable

try:  # pytest 环境的边界：任何环境下 import pytest 都应可用
    import pytest
except ImportError:  # pragma: no cover - bootstrap 场景保护
    pytest = None  # type: ignore[assignment]

#: 测试目录层级（目录名）→ 超时秒数。unit/widgets/components 共用默认 30s。
TIMEOUT_TIERS: dict[str, int] = {
    "unit": 30,
    "widgets": 30,
    "components": 30,
    "integration": 60,
    "gui": 120,
    "benchmark": 300,
}

#: 未命中任何层级时的兜底超时（秒）。
DEFAULT_TIMEOUT: int = 30

#: 与 :data:`TIMEOUT_TIERS` 键一致、可出现在 marker 上的层级名。
_TIER_MARKERS: frozenset[str] = frozenset(TIMEOUT_TIERS.keys())


def timeout_for_path(path: Path) -> int:
    """按路径中的目录名查找层级超时。

    Args:
        path: 测试文件路径（通常为 ``item.path``）。

    Returns:
        int: 命中层级的超时秒数；未命中回退 :data:`DEFAULT_TIMEOUT`。
    """
    parts: tuple[str, ...] = path.parts
    for part in parts:
        if part in TIMEOUT_TIERS:
            return TIMEOUT_TIERS[part]
    return DEFAULT_TIMEOUT


def timeout_for_item(item: Any) -> int:
    """为一枚测试项推导自动打标超时秒数。

    查找顺序：item 携带的层级 marker（benchmark/integration/gui 等）→
    路径目录层级 → 默认值。显式 ``timeout`` marker 的项由调用方提前跳过，
    本函数不处理该分支。

    Args:
        item: pytest 的 Item（``Path`` 位于 ``item.path``）。

    Returns:
        int: 建议的超时秒数。
    """
    for marker_name in _TIER_MARKERS:
        if item.get_closest_marker(marker_name) is not None:
            return TIMEOUT_TIERS[marker_name]
    return timeout_for_path(Path(item.path))


def has_timeout_marker(item: Any) -> bool:
    """判断测试项是否已带显式 ``timeout`` marker。

    Args:
        item: pytest 的 Item。

    Returns:
        bool: True 表示已有显式超时标记（应跳过自动打标）。
    """
    return item.get_closest_marker("timeout") is not None


def apply_timeout(items: Iterable[Any]) -> list[tuple[str, int]]:
    """给未显式标记 ``timeout`` 的测试项自动打标。

    显式 marker 优先；自动打标次之；CLI ``--timeout`` 只兜底上述两者均
    缺失的测试。用于 ``pytest_collection_modifyitems``：

    .. code-block:: python

        def pytest_collection_modifyitems(config, items):
            support.timeout_policy.apply_timeout(items)

    Args:
        items: 收集阶段产出的测试项序列；被打标后会就地修改 item。

    Returns:
        list[tuple[str, int]]: 实际被打标的 (nodeid, 超时秒数) 列表，便于
        运行器展示"本次应用了哪些自动超时"。
    """
    applied: list[tuple[str, int]] = []
    for item in items:
        if has_timeout_marker(item):
            continue
        seconds: int = timeout_for_item(item)
        # item 已带层级 marker 或路径命中同一层级时仍需打标：
        # marker 优先级保证用户侧配置（--timeout）不会越过它。
        item.add_marker(pytest.mark.timeout(seconds))  # type: ignore[union-attr]
        applied.append((item.nodeid, seconds))
    return applied


def measure_duration(started: float) -> float:
    """计算单测试耗时（供进度/慢速缓冲用）。

    Args:
        started: ``time.monotonic()`` 起点。

    Returns:
        float: 经过的秒数。
    """
    return time.monotonic() - started