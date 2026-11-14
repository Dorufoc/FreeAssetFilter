#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""协作式取消令牌与有界批次队列（P6.5）。

项目里已有多种「取消」实现（目录流式的世代 token、缩略图的
``threading.Event``、PDF 的渲染令牌……），但语义与组合方式各不相同。
本模块提供两个最小构件，供新代码统一复用：

* :class:`CancellationToken` —— 树形取消（父取消自动级联子令牌），
  支持 ``check()``（抛 :class:`CancelledError`）与 ``as_check()``
  （适配既有 ``cancel_check: Callable[[], bool]`` 契约）；
* :class:`BoundedBatchQueue` —— 有界批次队列：超限时丢弃**最旧**批次，
  只保留最新窗口（目录流式「最后一次胜出」的背压形态）。

设计约束：

* 令牌只用 ``threading.Event``（可在任意线程 cancel/查询）；
* 子令牌强引用父令牌，父令牌弱引用子令牌（避免泄漏）；
* 队列丢弃只影响「待展示批次」，调用方应保证原始数据另行保存。
"""

from __future__ import annotations

import threading
import weakref
from collections import deque
from typing import Any, Callable, Deque, List, Optional


class CancelledError(RuntimeError):
    """令牌已取消时由 :meth:`CancellationToken.check` 抛出。"""


class CancellationToken:
    """树形协作式取消令牌。"""

    __slots__ = ("_event", "_parent", "_children", "_lock", "_reason", "__weakref__")

    def __init__(self, parent: Optional["CancellationToken"] = None) -> None:
        """创建令牌。

        Args:
            parent: 可选父令牌；父令牌取消会级联取消本令牌。
        """
        self._event = threading.Event()
        self._parent = parent
        self._children: "weakref.WeakSet[CancellationToken]" = weakref.WeakSet()
        self._lock = threading.Lock()
        self._reason = ""
        if parent is not None:
            parent._register_child(self)

    def _register_child(self, child: "CancellationToken") -> None:
        """登记子令牌（父已取消时立即级联）。"""
        with self._lock:
            self._children.add(child)
        if self._event.is_set():
            child.cancel(self._reason or "parent cancelled")

    def cancel(self, reason: str = "") -> None:
        """取消本令牌并级联所有子令牌（幂等）。"""
        if self._event.is_set():
            return
        with self._lock:
            if reason and not self._reason:
                self._reason = reason
            self._event.set()
            children = list(self._children)
        for child in children:
            child.cancel(self._reason or reason)

    def is_cancelled(self) -> bool:
        """是否已取消。"""
        return self._event.is_set()

    def reason(self) -> str:
        """取消原因（未取消时为空串）。"""
        return self._reason

    def check(self) -> None:
        """已取消则抛出 :class:`CancelledError`。"""
        if self._event.is_set():
            raise CancelledError(self._reason or "cancelled")

    def as_check(self) -> Callable[[], bool]:
        """返回适配 ``cancel_check: Callable[[], bool]`` 的回调。"""
        return self._event.is_set

    def child(self) -> "CancellationToken":
        """创建子令牌。"""
        return CancellationToken(parent=self)

    def reset(self) -> None:
        """重置为未取消（仅测试/复用场景；不解除已取消的父子关系）。"""
        with self._lock:
            self._event.clear()
            self._reason = ""


class BoundedBatchQueue:
    """有界批次队列：超限丢弃最旧批次（P6.5 背压）。"""

    __slots__ = ("_queue", "_lock", "_dropped")

    def __init__(self, maxlen: int = 64) -> None:
        """创建队列。

        Args:
            maxlen: 最大批次数（≥1）。
        """
        self._queue: Deque[List[Any]] = deque(maxlen=max(1, int(maxlen)))
        self._lock = threading.Lock()
        self._dropped = 0

    def push(self, batch: List[Any]) -> int:
        """压入一批；若超限则丢弃最旧批次。

        Args:
            batch: 批次条目列表。

        Returns:
            int: 本次因超限丢弃的批次数（0 或 1）。
        """
        with self._lock:
            dropped = 0
            if self._queue.maxlen is not None and len(self._queue) >= self._queue.maxlen:
                dropped = 1
                self._dropped += 1
            # deque(maxlen) 会自动丢最旧；这里显式计数以保持可观测。
            self._queue.append(batch)
            return dropped

    def drain(self) -> List[List[Any]]:
        """取出全部批次并清空。

        Returns:
            list[list]: 按入队顺序排列的批次列表。
        """
        with self._lock:
            batches = list(self._queue)
            self._queue.clear()
            return batches

    def clear(self) -> None:
        """清空（不重置丢弃计数）。"""
        with self._lock:
            self._queue.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._queue)

    @property
    def dropped(self) -> int:
        """累计丢弃批次数。"""
        with self._lock:
            return self._dropped
