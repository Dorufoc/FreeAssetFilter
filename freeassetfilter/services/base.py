#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 服务基类模块
提供所有服务类的抽象基类，包含线程安全的初始化/销毁生命周期管理。
"""

import threading
from abc import ABC, abstractmethod


class BaseService(ABC):
    """所有服务的抽象基类。

    提供线程安全的初始化/销毁生命周期管理。
    子类必须实现 _do_initialize() 和 _do_dispose() 方法。

    遵循项目中 SettingsManager 的 _lock + _initialized 线程安全模式：

        class MyService(BaseService):
            _instance = None
            _lock = threading.Lock()
            _initialized = False

            def __new__(cls, *args, **kwargs):
                with cls._lock:
                    if cls._instance is None:
                        cls._instance = super().__new__(cls)
                    return cls._instance

            def __init__(self, ...):
                with self._lock:
                    if self._initialized:
                        return
                    self._initialized = True
                    self._init_lock = threading.Lock()
                    ...
    """

    _lock: threading.Lock = threading.Lock()
    """类级别锁，供单例子类在 __new__/__init__ 中使用。"""

    def __init__(self) -> None:
        """初始化服务实例。

        设置实例级别的初始化标志和锁。
        子类如果重写 __init__ 必须调用 super().__init__()。
        """
        self._initialized: bool = False
        self._init_lock: threading.Lock = threading.Lock()

    @property
    def is_initialized(self) -> bool:
        """服务是否已成功初始化。

        Returns:
            bool: 如果 initialize() 已成功调用返回 True，否则返回 False。
        """
        return self._initialized

    def initialize(self) -> bool:
        """初始化服务。

        线程安全。可多次调用；仅首次执行实际初始化逻辑。

        Returns:
            bool: 初始化成功返回 True，失败返回 False。
        """
        with self._init_lock:
            if self._initialized:
                return True

            try:
                self._do_initialize()
                self._initialized = True
                return True
            except Exception:
                self._initialized = False
                return False

    def dispose(self) -> None:
        """销毁服务，释放所有资源。

        线程安全。可多次调用；仅首次执行实际销毁逻辑。
        """
        with self._init_lock:
            if not self._initialized:
                return

            try:
                self._do_dispose()
            finally:
                self._initialized = False

    @abstractmethod
    def _do_initialize(self) -> None:
        """子类特定的初始化逻辑。

        由 initialize() 在初始化锁的保护下调用一次。
        子类必须实现此方法。
        """
        raise NotImplementedError

    @abstractmethod
    def _do_dispose(self) -> None:
        """子类特定的销毁逻辑。

        由 dispose() 在销毁锁的保护下调用一次。
        子类必须实现此方法，释放所有已分配的资源。
        """
        raise NotImplementedError
