# -*- coding: utf-8 -*-
"""test_qt_message_handler: Qt 层消息捕获模块测试（fix-log-truncation Todo 3）。

覆盖：install_qt_message_handler 返回 True；qWarning→warning、
qCritical→error（均含 ``[Qt]`` 前缀与原文）；handler 内异常被兜底、
进程不崩溃且触发 bootstrap fallback。
"""

from __future__ import annotations

import logging
from typing import Any, List

import pytest


class _ListHandler(logging.Handler):
    """收集用内存 Handler（记录全部 LogRecord）。

    Args:
        records: 外部传入的收集列表。
    """

    def __init__(self, records: List[logging.LogRecord]) -> None:
        """初始化收集 Handler。

        Args:
            records: 用于收集 LogRecord 的外部列表。
        """
        super().__init__()
        self._records = records

    def emit(self, record: logging.LogRecord) -> None:
        """收集一条日志记录。

        Args:
            record: 待收集的日志记录。
        """
        self._records.append(record)


@pytest.fixture
def _reset_app_logger_singleton() -> Any:
    """每个测试前后清空 app_logger 模块级 ``_app_logger`` 缓存。

    Yields:
        None。
    """
    import freeassetfilter.utils.app_logger as _logger_module

    _logger_module._app_logger = None
    yield
    _logger_module._app_logger = None


@pytest.fixture
def restore_qt_handler(request: Any, qapp: Any) -> Any:
    """保证 Qt 全局消息 handler 在测试后必被恢复。

    进程级全局——测试中途抛异常也不能泄漏到其他测试。

    Args:
        request: pytest 请求对象（用于 addfinalizer）。
        qapp: 会话级 QApplication（保证 Qt 消息系统可用）。

    Returns:
        None。
    """
    from PySide6.QtCore import qInstallMessageHandler

    def _restore() -> None:
        try:
            qInstallMessageHandler(None)
        except Exception:
            pass

    request.addfinalizer(_restore)
    try:
        yield
    finally:
        _restore()


@pytest.fixture
def collected_records(
    _reset_app_logger_singleton: Any, restore_qt_handler: Any
) -> List[logging.LogRecord]:
    """给 "FreeAssetFilter" logger 挂载收集用 ListHandler。

    Args:
        _reset_app_logger_singleton: 日志单例隔离 fixture。
        restore_qt_handler: Qt handler 恢复 fixture。

    Returns:
        list[logging.LogRecord]: 收集到的日志记录列表。
    """
    from freeassetfilter.utils.app_logger import get_logger
    from freeassetfilter.utils.qt_message_handler import install_qt_message_handler

    assert install_qt_message_handler() is True
    # 先实例化单例：AppLogger.__init__ 会清空 logger.handlers，
    # 必须在其之后再挂载收集器，否则收集器会被清空。
    get_logger()
    records: List[logging.LogRecord] = []
    handler = _ListHandler(records)
    handler.setLevel(logging.DEBUG)
    qt_logger = logging.getLogger("FreeAssetFilter")
    old_level = qt_logger.level
    qt_logger.setLevel(logging.DEBUG)
    qt_logger.addHandler(handler)
    try:
        yield records
    finally:
        try:
            qt_logger.removeHandler(handler)
        finally:
            qt_logger.setLevel(old_level)


def test_install_returns_true(
    _reset_app_logger_singleton: Any, restore_qt_handler: Any
) -> None:
    """install_qt_message_handler 应返回 True。

    Args:
        _reset_app_logger_singleton: 日志单例隔离 fixture。
        restore_qt_handler: Qt handler 恢复 fixture。
    """
    from freeassetfilter.utils.qt_message_handler import install_qt_message_handler

    assert install_qt_message_handler() is True


def test_qwarning_captured_as_warning(
    collected_records: List[logging.LogRecord], qapp: Any
) -> None:
    """qWarning 应被捕获为 warning 级且含 [Qt] 前缀与原文。

    Args:
        collected_records: 日志收集列表 fixture。
        qapp: 会话级 QApplication。
    """
    from PySide6.QtCore import qWarning

    qWarning("faf-qt-test-warning")
    matches = [r for r in collected_records if "faf-qt-test-warning" in r.getMessage()]
    assert matches, "qWarning 消息未被 Qt handler 捕获"
    assert any(r.levelno == logging.WARNING for r in matches)
    assert any(r.getMessage().startswith("[Qt]") for r in matches)


def test_qcritical_captured_as_error(
    collected_records: List[logging.LogRecord], qapp: Any
) -> None:
    """qCritical 应被捕获为 error 级且含 [Qt] 前缀与原文。

    Args:
        collected_records: 日志收集列表 fixture。
        qapp: 会话级 QApplication。
    """
    from PySide6.QtCore import qCritical

    qCritical("faf-qt-test-critical")
    matches = [r for r in collected_records if "faf-qt-test-critical" in r.getMessage()]
    assert matches, "qCritical 消息未被 Qt handler 捕获"
    assert any(r.levelno == logging.ERROR for r in matches)
    assert any(r.getMessage().startswith("[Qt]") for r in matches)


def test_handler_exception_falls_back_without_raise(
    _reset_app_logger_singleton: Any, restore_qt_handler: Any, qapp: Any
) -> None:
    """handler 内 logger 抛异常时进程不崩溃且走 bootstrap fallback。

    Args:
        _reset_app_logger_singleton: 日志单例隔离 fixture。
        restore_qt_handler: Qt handler 恢复 fixture。
        qapp: 会话级 QApplication。
    """
    from unittest.mock import MagicMock, patch

    from PySide6.QtCore import QtMsgType, qWarning

    import freeassetfilter.utils.qt_message_handler as _qt_module

    assert _qt_module.install_qt_message_handler() is True

    raising_logger = MagicMock()
    raising_logger.debug.side_effect = RuntimeError("boom-debug")
    raising_logger.info.side_effect = RuntimeError("boom-info")
    raising_logger.warning.side_effect = RuntimeError("boom-warning")
    raising_logger.error.side_effect = RuntimeError("boom-error")
    raising_logger.critical.side_effect = RuntimeError("boom-critical")

    with (
        patch.object(_qt_module, "get_logger", return_value=raising_logger),
        patch.object(_qt_module, "_write_bootstrap_fallback") as _fallback,
    ):
        # 经真实 Qt 通道触发（handler 内异常绝不向上抛，进程不崩溃）。
        qWarning("faf-qt-failure-path-warning")
        assert _fallback.called

        # 直接调用 handler（覆盖 QtFatalMsg 分支亦不抛）。
        _qt_module._qt_message_handler(QtMsgType.QtFatalMsg, None, "faf-qt-fatal-direct")
        assert _fallback.call_count >= 2
