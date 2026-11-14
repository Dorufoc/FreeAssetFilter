"""``sopeek.core.cancellation``：树形取消令牌与有界批次队列。"""

from __future__ import annotations

import pytest

from sopeek.core.cancellation import (
    BoundedBatchQueue,
    CancellationToken,
    CancelledError,
)


pytestmark = pytest.mark.unit


# ── CancellationToken ─────────────────────────────────────────────────────


def test_fresh_token_is_not_cancelled() -> None:
    token = CancellationToken()
    assert token.is_cancelled() is False
    assert token.reason() == ""
    token.check()  # 不抛异常
    assert token.as_check()() is False


def test_cancel_is_idempotent_and_keeps_first_reason() -> None:
    token = CancellationToken()
    token.cancel("first")
    token.cancel("second")
    assert token.is_cancelled() is True
    assert token.reason() == "first"


def test_check_raises_with_reason() -> None:
    token = CancellationToken()
    token.cancel("因为用户取消")
    with pytest.raises(CancelledError) as excinfo:
        token.check()
    assert "因为用户取消" in str(excinfo.value)


def test_child_cascades_from_parent() -> None:
    parent = CancellationToken()
    child = parent.child()
    assert child.is_cancelled() is False

    parent.cancel("parent cancelled")
    assert child.is_cancelled() is True
    assert child.reason() == "parent cancelled"


def test_child_of_already_cancelled_parent_is_cancelled_immediately() -> None:
    parent = CancellationToken()
    parent.cancel("早于子令牌创建")
    child = parent.child()
    assert child.is_cancelled() is True
    assert child.reason() == "早于子令牌创建"


def test_cancelling_child_does_not_cancel_parent() -> None:
    parent = CancellationToken()
    child = parent.child()
    child.cancel("only child")
    assert parent.is_cancelled() is False
    assert child.is_cancelled() is True


def test_reset_clears_state() -> None:
    token = CancellationToken()
    token.cancel("temp")
    token.reset()
    assert token.is_cancelled() is False
    assert token.reason() == ""
    token.check()


def test_grandchild_cascade() -> None:
    root = CancellationToken()
    mid = root.child()
    leaf = mid.child()
    root.cancel("root")
    assert leaf.is_cancelled() is True


# ── BoundedBatchQueue ─────────────────────────────────────────────────────


def test_queue_drains_in_order() -> None:
    queue = BoundedBatchQueue(maxlen=8)
    queue.push([1, 2])
    queue.push([3])
    assert queue.drain() == [[1, 2], [3]]
    assert len(queue) == 0
    assert queue.drain() == []


def test_queue_drops_oldest_when_full() -> None:
    queue = BoundedBatchQueue(maxlen=2)
    assert queue.push(["a"]) == 0
    assert queue.push(["b"]) == 0
    assert queue.push(["c"]) == 1  # 丢最旧的一批
    assert queue.drain() == [["b"], ["c"]]
    assert queue.dropped == 1


def test_queue_maxlen_below_one_is_clamped() -> None:
    queue = BoundedBatchQueue(maxlen=0)
    queue.push([1])
    assert queue.drain() == [[1]]


def test_queue_clear_keeps_drop_counter() -> None:
    queue = BoundedBatchQueue(maxlen=1)
    queue.push([1])
    queue.push([2])
    queue.clear()
    assert len(queue) == 0
    assert queue.dropped == 1
