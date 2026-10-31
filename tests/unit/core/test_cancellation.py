# -*- coding: utf-8 -*-
"""取消令牌与有界队列测试（P6.5）。

锁定四条契约：

1. 父令牌取消自动级联子令牌（含已取消后再创建的子令牌）；
2. ``check()`` 抛 ``CancelledError``，``as_check()`` 适配既有回调契约；
3. 有界队列超限丢最旧批次并计数；
4. ``drain()`` 清空并按入队顺序返回。

验证命令：
    python -m pytest tests/unit/core/test_cancellation.py -v
"""

from __future__ import annotations

import pytest

from sopeek.core.cancellation import (
    BoundedBatchQueue,
    CancelledError,
    CancellationToken,
)

pytestmark = pytest.mark.unit


def test_parent_cancel_cascades_to_children() -> None:
    """父取消 → 所有子令牌取消。"""
    root = CancellationToken()
    child = root.child()
    grandchild = child.child()

    assert not grandchild.is_cancelled()
    root.cancel("switch view")

    assert root.is_cancelled() and child.is_cancelled() and grandchild.is_cancelled()
    assert child.reason() == "switch view"


def test_child_created_after_cancel_is_immediately_cancelled() -> None:
    """已取消父令牌创建的子令牌立即处于取消态。"""
    root = CancellationToken()
    root.cancel("boom")
    late = root.child()
    assert late.is_cancelled() is True


def test_check_and_as_check() -> None:
    """check() 抛异常；as_check() 返回布尔回调。"""
    token = CancellationToken()
    check = token.as_check()
    assert check() is False
    token.check()  # 未取消不抛

    token.cancel("stop")
    with pytest.raises(CancelledError):
        token.check()
    assert check() is True


def test_cancel_is_idempotent() -> None:
    """重复 cancel 不改变原因、不抛异常。"""
    token = CancellationToken()
    token.cancel("first")
    token.cancel("second")
    assert token.reason() == "first"


def test_reset_only_clears_self() -> None:
    """reset() 只清自身状态（测试/复用场景）。"""
    root = CancellationToken()
    child = root.child()
    root.cancel()
    child.reset()
    assert child.is_cancelled() is False
    assert root.is_cancelled() is True


def test_bounded_queue_drops_oldest() -> None:
    """超限丢最旧批次并累计 dropped。"""
    queue = BoundedBatchQueue(maxlen=2)
    assert queue.push([1]) == 0
    assert queue.push([2]) == 0
    assert queue.push([3]) == 1
    assert queue.dropped == 1
    batches = queue.drain()
    assert batches == [[2], [3]]
    assert len(queue) == 0


def test_bounded_queue_clear_keeps_counter() -> None:
    """clear() 清空但仍保留丢弃计数。"""
    queue = BoundedBatchQueue(maxlen=1)
    queue.push([1])
    queue.push([2])
    queue.clear()
    assert len(queue) == 0
    assert queue.dropped == 1
