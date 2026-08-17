# -*- coding: utf-8 -*-
"""``BaseService``（freeassetfilter/services/base.py）单元测试。

覆盖（happy + boundary/error 各至少一条）：

* 抽象约束：缺少抽象方法实装的 ``BaseService`` 不可直接实例化。
* ``initialize`` —— 成功返回 True / ``is_initialized`` 状态变迁 / 幂等
  （重复调用仅执行一次实际初始化逻辑且仍返回 True）/ ``_do_initialize``
  异常时返回 False 且不置位初始化标志。
* ``dispose`` —— 已初始化才执行销毁 / 幂等 / ``_do_dispose`` 异常时仍
  通过 finally 重置状态并向上抛。
* 生命周期闭环：dispose 后可重新 initialize。
* 并发安全：多线程同时调用 initialize 仅一次实际初始化（内部锁保护）。

用 ``MockConcreteService``（继承 BaseService 的最小实现）实测，避免
依赖任何具体服务的副作用；所有状态均为对象私有，无需全局清理。
"""

from __future__ import annotations

import threading
from typing import List

import pytest

from freeassetfilter.services.base import BaseService

pytestmark = pytest.mark.unit


class MockConcreteService(BaseService):
    """BaseService 的最小测试实现：记录回调次数并支持注入失败。"""

    def __init__(self) -> None:
        """初始化测试桩。"""
        super().__init__()
        self.init_call_count: int = 0
        self.dispose_call_count: int = 0
        self.fail_initialize: bool = False
        self.fail_dispose: bool = False

    def _do_initialize(self) -> None:
        """记录初始化调用，失败注入时抛 RuntimeError。"""
        self.init_call_count += 1
        if self.fail_initialize:
            raise RuntimeError("injected initialize failure")

    def _do_dispose(self) -> None:
        """记录销毁调用，失败注入时抛 RuntimeError。"""
        self.dispose_call_count += 1
        if self.fail_dispose:
            raise RuntimeError("injected dispose failure")


# =============================================================================
# 抽象约束
# =============================================================================
class TestAbstractContract:
    """抽象基类不可直接实例化"""

    def test_abstract_class_cannot_be_instantiated(self) -> None:
        """缺少抽象方法实现时构造应抛 TypeError。"""
        with pytest.raises(TypeError):
            BaseService()  # type: ignore[abstract]


# =============================================================================
# initialize
# =============================================================================
class TestInitialize:
    """初始化生命周期"""

    def test_initialize_success_marks_initialized(self) -> None:
        """初始化成功返回 True，且 is_initialized 变为 True。"""
        service: MockConcreteService = MockConcreteService()
        assert service.is_initialized is False
        assert service.initialize() is True
        assert service.is_initialized is True
        assert service.init_call_count == 1

    def test_initialize_idempotent(self) -> None:
        """重复初始化只执行一次实际逻辑，且每次都返回 True。"""
        service: MockConcreteService = MockConcreteService()
        assert service.initialize() is True
        assert service.initialize() is True
        assert service.init_call_count == 1

    def test_initialize_failure_returns_false(self) -> None:
        """初始化失败返回 False，is_initialized 保持 False。"""
        service: MockConcreteService = MockConcreteService()
        service.fail_initialize = True
        assert service.initialize() is False
        assert service.is_initialized is False

    def test_initialize_can_retry_after_failure(self) -> None:
        """失败后可重试：恢复后 initialize 成功并置位。"""
        service: MockConcreteService = MockConcreteService()
        service.fail_initialize = True
        assert service.initialize() is False
        service.fail_initialize = False
        assert service.initialize() is True
        assert service.is_initialized is True

    def test_initialize_is_thread_safe_single_execution(self) -> None:
        """多线程并发 initialize 只执行一次实际初始化。"""
        service: MockConcreteService = MockConcreteService()
        thread_count: int = 8
        results: List[bool] = []
        barrier: threading.Barrier = threading.Barrier(thread_count)

        def _run_initialize() -> None:
            barrier.wait()
            results.append(service.initialize())

        threads: List[threading.Thread] = [
            threading.Thread(target=_run_initialize) for _ in range(thread_count)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert results.count(True) == thread_count
        assert service.init_call_count == 1


# =============================================================================
# dispose
# =============================================================================
class TestDispose:
    """销毁生命周期"""

    def test_dispose_success_resets_initialized(self) -> None:
        """销毁后 is_initialized 变为 False，且执行一次销毁逻辑。"""
        service: MockConcreteService = MockConcreteService()
        service.initialize()
        service.dispose()
        assert service.is_initialized is False
        assert service.dispose_call_count == 1

    def test_dispose_when_not_initialized_is_noop(self) -> None:
        """未初始化时 dispose 不执行任何销毁逻辑。"""
        service: MockConcreteService = MockConcreteService()
        service.dispose()
        assert service.is_initialized is False
        assert service.dispose_call_count == 0

    def test_dispose_idempotent(self) -> None:
        """重复 dispose 只执行一次销毁逻辑。"""
        service: MockConcreteService = MockConcreteService()
        service.initialize()
        service.dispose()
        service.dispose()
        assert service.dispose_call_count == 1

    def test_dispose_resets_initialized_even_on_failure(self) -> None:
        """销毁逻辑抛异常时仍重置状态（finally 保证）并向上抛。"""
        service: MockConcreteService = MockConcreteService()
        service.initialize()
        service.fail_dispose = True
        with pytest.raises(RuntimeError):
            service.dispose()
        assert service.is_initialized is False

    def test_reinitialize_after_dispose(self) -> None:
        """生命周期闭环：销毁后重新初始化可再次成功。"""
        service: MockConcreteService = MockConcreteService()
        service.initialize()
        service.dispose()
        assert service.initialize() is True
        assert service.is_initialized is True
        assert service.init_call_count == 2