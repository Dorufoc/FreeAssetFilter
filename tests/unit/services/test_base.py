#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BaseService 抽象基类单元测试

覆盖 4 个公共方法 + 1 个属性：
    - initialize()
    - dispose()
    - is_initialized
    - _do_initialize()   （通过 MockConcreteService 间接测试）
    - _do_dispose()      （通过 MockConcreteService 间接测试）

测试点（共 8 项）：
    1. initialize() 调用 _do_initialize() 一次
    2. dispose() 调用 _do_dispose() 一次
    3. 多次 initialize() 幂等（第二次调用返回 True 但不再调用 _do_initialize）
    4. 多次 dispose() 幂等
    5. _do_initialize() 抛异常时 initialize() 返回 False，is_initialized 保持 False
    6. dispose() 后 is_initialized 返回 False
    7. initialize() 成功后 is_initialized 返回 True
    8. 未调用 initialize() 时 is_initialized 返回 False
"""

from unittest.mock import MagicMock, patch

import pytest

from freeassetfilter.services.base import BaseService


# ---------------------------------------------------------------------------
# MockConcreteService — 用于测试抽象基类的具体实现
# ---------------------------------------------------------------------------

class MockConcreteService(BaseService):
    """继承 BaseService 的最小具体实现，用于测试基类逻辑。"""

    def __init__(self) -> None:
        super().__init__()
        self._do_initialize_called: bool = False
        self._do_dispose_called: bool = False

    def _do_initialize(self) -> None:
        """模拟初始化逻辑。"""
        self._do_initialize_called = True

    def _do_dispose(self) -> None:
        """模拟销毁逻辑。"""
        self._do_dispose_called = True


# ---------------------------------------------------------------------------
# MockConcreteServiceWithFlag — 支持在 _do_initialize 中抛异常
# ---------------------------------------------------------------------------

class MockConcreteServiceWithFlag(MockConcreteService):
    """允许通过 flag 控制 _do_initialize() 是否抛异常。"""

    def __init__(self, fail_initialize: bool = False,
                 fail_dispose: bool = False) -> None:
        super().__init__()
        self._fail_initialize = fail_initialize
        self._fail_dispose = fail_dispose

    def _do_initialize(self) -> None:
        if self._fail_initialize:
            raise RuntimeError("模拟初始化失败")
        super()._do_initialize()

    def _do_dispose(self) -> None:
        if self._fail_dispose:
            raise RuntimeError("模拟销毁失败")
        super()._do_dispose()


# ---------------------------------------------------------------------------
# 测试：构造 & 初始状态
# ---------------------------------------------------------------------------

class TestInitialState:
    """未调用 initialize() 时的初始状态测试。"""

    def test_is_initialized_defaults_to_false(self) -> None:
        """测试点 8：未调用 initialize() 时 is_initialized 返回 False。"""
        service = MockConcreteService()
        assert service.is_initialized is False

    def test_has_init_lock(self) -> None:
        """构造后应存在 _init_lock 属性。"""
        service = MockConcreteService()
        assert hasattr(service, "_init_lock")


# ---------------------------------------------------------------------------
# 测试：initialize() 行为
# ---------------------------------------------------------------------------

class TestInitialize:
    """initialize() 方法的正常与异常行为测试。"""

    def test_initialize_calls_do_initialize(self) -> None:
        """测试点 1：initialize() 调用 _do_initialize() 一次。"""
        service = MockConcreteService()
        result = service.initialize()
        assert result is True
        assert service._do_initialize_called is True

    def test_initialize_sets_is_initialized_true(self) -> None:
        """测试点 7：initialize() 成功后 is_initialized 返回 True。"""
        service = MockConcreteService()
        service.initialize()
        assert service.is_initialized is True

    def test_initialize_idempotent(self) -> None:
        """测试点 3：多次 initialize() 幂等，第二次调用返回 True 但不再调用
        _do_initialize。"""
        service = MockConcreteService()
        result1 = service.initialize()
        assert result1 is True

        # 重置标记，验证第二次调用不会再次执行 _do_initialize
        service._do_initialize_called = False
        result2 = service.initialize()

        assert result2 is True
        assert service._do_initialize_called is False, (
            "第二次 initialize() 不应再次调用 _do_initialize()"
        )
        assert service.is_initialized is True

    def test_initialize_failure_returns_false(self) -> None:
        """测试点 5：_do_initialize() 抛异常时 initialize() 返回 False，
        is_initialized 保持 False。"""
        service = MockConcreteServiceWithFlag(fail_initialize=True)
        result = service.initialize()
        assert result is False
        assert service.is_initialized is False

    def test_initialize_failure_does_not_set_flag(self) -> None:
        """_do_initialize() 抛异常后 _initialized 必须保持 False。"""
        service = MockConcreteServiceWithFlag(fail_initialize=True)
        service.initialize()
        # 直接验证内部状态，确保异常分支正确
        assert service._initialized is False

    def test_initialize_called_only_once_on_consecutive_calls(self) -> None:
        """连续多次调用 initialize() 应只执行一次 _do_initialize()。"""
        service = MockConcreteService()
        with patch.object(service, "_do_initialize",
                          wraps=service._do_initialize) as mock_init:
            service.initialize()
            service.initialize()
            service.initialize()
            mock_init.assert_called_once()


# ---------------------------------------------------------------------------
# 测试：dispose() 行为
# ---------------------------------------------------------------------------

class TestDispose:
    """dispose() 方法的正常与异常行为测试。"""

    def test_dispose_calls_do_dispose(self) -> None:
        """测试点 2：dispose() 调用 _do_dispose() 一次。"""
        service = MockConcreteService()
        service.initialize()
        service.dispose()
        assert service._do_dispose_called is True

    def test_dispose_sets_is_initialized_false(self) -> None:
        """测试点 6：dispose() 后 is_initialized 返回 False。"""
        service = MockConcreteService()
        service.initialize()
        assert service.is_initialized is True
        service.dispose()
        assert service.is_initialized is False

    def test_dispose_before_initialize_noop(self) -> None:
        """在 initialize() 之前调用 dispose() 应为空操作（幂等）。"""
        service = MockConcreteService()
        # 不应抛出异常
        service.dispose()
        assert service._do_dispose_called is False
        assert service.is_initialized is False

    def test_dispose_idempotent(self) -> None:
        """测试点 4：多次 dispose() 幂等。"""
        service = MockConcreteService()
        service.initialize()
        service.dispose()

        # 重置标记，验证第二次调用不会再次执行 _do_dispose
        service._do_dispose_called = False
        service.dispose()

        assert service._do_dispose_called is False, (
            "第二次 dispose() 不应再次调用 _do_dispose()"
        )
        assert service.is_initialized is False

    def test_dispose_called_only_once(self) -> None:
        """连续多次 dispose() 应只执行一次 _do_dispose()。"""
        service = MockConcreteService()
        service.initialize()
        with patch.object(service, "_do_dispose",
                          wraps=service._do_dispose) as mock_dispose:
            service.dispose()
            service.dispose()
            service.dispose()
            mock_dispose.assert_called_once()

    def test_dispose_after_reinitialize(self) -> None:
        """在 reinitialize 之后 dispose 仍能正确工作。"""
        service = MockConcreteService()
        service.initialize()
        service.dispose()
        # 重新初始化后还能再销毁
        assert service._do_dispose_called is True
        service._do_dispose_called = False
        service.initialize()
        service.dispose()
        assert service._do_dispose_called is True

    def test_dispose_sets_initialized_false_even_on_error(self) -> None:
        """_do_dispose() 抛异常时 dispose() 仍需将 _initialized 置为 False
        （异常传播到调用方，但 _initialized 已在 finally 块中重置）。"""
        service = MockConcreteServiceWithFlag(fail_dispose=True)
        service.initialize()
        with pytest.raises(RuntimeError, match="模拟销毁失败"):
            service.dispose()
        assert service.is_initialized is False


# ---------------------------------------------------------------------------
# 测试：完整生命周期
# ---------------------------------------------------------------------------

class TestLifecycle:
    """完整初始化-销毁流程测试。"""

    def test_full_lifecycle(self) -> None:
        """完整的初始化-销毁流程：initialize → is_initialized →
        dispose → is_initialized。"""
        service = MockConcreteService()
        assert service.is_initialized is False

        service.initialize()
        assert service.is_initialized is True
        assert service._do_initialize_called is True

        service.dispose()
        assert service.is_initialized is False
        assert service._do_dispose_called is True

    def test_cannot_initialize_after_failure(self) -> None:
        """一次失败的初始化不会影响后续再次初始化的能力。"""
        service = MockConcreteServiceWithFlag(fail_initialize=True)

        # 第一次初始化失败
        result1 = service.initialize()
        assert result1 is False
        assert service.is_initialized is False

        # 修改旗标，第二次应该成功
        service._fail_initialize = False
        result2 = service.initialize()
        assert result2 is True
        assert service.is_initialized is True
        assert service._do_initialize_called is True


# ---------------------------------------------------------------------------
# 测试：线程安全
# ---------------------------------------------------------------------------

class TestThreadSafety:
    """线程安全相关的测试（使用 unittest.mock 模拟锁行为）。"""

    def test_initialize_uses_lock(self) -> None:
        """initialize() 应通过 _init_lock 保证线程安全。"""
        service = MockConcreteService()
        mock_lock = MagicMock()

        with patch.object(service, "_init_lock", mock_lock):
            service.initialize()

        # 验证锁的上下文管理器被使用
        mock_lock.__enter__.assert_called_once()
        mock_lock.__exit__.assert_called_once()

    def test_dispose_uses_lock(self) -> None:
        """dispose() 应通过 _init_lock 保证线程安全。"""
        service = MockConcreteService()
        service.initialize()

        mock_lock = MagicMock()
        with patch.object(service, "_init_lock", mock_lock):
            service.dispose()

        mock_lock.__enter__.assert_called_once()
        mock_lock.__exit__.assert_called_once()


# ---------------------------------------------------------------------------
# 测试：BaseService 为抽象类
# ---------------------------------------------------------------------------

class TestAbstractBase:
    """BaseService 抽象基类约束测试。"""

    def test_cannot_instantiate_abstract_class(self) -> None:
        """BaseService 不能直接被实例化（有 abstractmethod）。"""
        with pytest.raises(TypeError):
            BaseService()  # type: ignore[abstract]

    def test_concrete_service_is_instance(self) -> None:
        """MockConcreteService 是 BaseService 的实例。"""
        service = MockConcreteService()
        assert isinstance(service, BaseService)

    def test_abstract_do_initialize_raises_not_implemented(self) -> None:
        """_do_initialize() 抽象方法体直接调用应抛出 NotImplementedError。"""
        service = MockConcreteService()
        with pytest.raises(NotImplementedError):
            BaseService._do_initialize(service)

    def test_abstract_do_dispose_raises_not_implemented(self) -> None:
        """_do_dispose() 抽象方法体直接调用应抛出 NotImplementedError。"""
        service = MockConcreteService()
        with pytest.raises(NotImplementedError):
            BaseService._do_dispose(service)
