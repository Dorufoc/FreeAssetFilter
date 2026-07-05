#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

AppLogger 模块单元测试
"""

import os
import sys
import logging
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from freeassetfilter.utils.app_logger import (
    AppLogger,
    get_logger,
    debug,
    info,
    warning,
    error,
    critical,
    log_exception_details,
    log_exception,
    exception_details,
    install_console_capture,
    TeeStream,
    ComponentSourceFilter,
    ComponentSourceFormatter,
    sanitize_path,
    sanitize_sensitive_info,
    get_safe_error_for_ui,
)


class TestSanitizePath:
    def test_sanitize_windows_user_path(self):
        assert "[USER_HOME]" in sanitize_path(r"C:\Users\john\Documents")

    def test_sanitize_app_data_path(self):
        result = sanitize_path(r"C:\Users\john\AppData\Roaming")
        assert "[USER_HOME]" in result or "[APP_DATA]" in result

    def test_sanitize_system_path(self):
        assert "[SYSTEM]" in sanitize_path(r"C:\Windows\System32")

    def test_sanitize_program_files(self):
        assert "[PROGRAM]" in sanitize_path(r"C:\Program Files\7-Zip")

    def test_sanitize_linux_home(self):
        assert "[USER_HOME]" in sanitize_path("/home/user/documents")

    def test_sanitize_mac_home(self):
        assert "[USER_HOME]" in sanitize_path("/Users/user/documents")

    def test_sanitize_drive_letter(self):
        assert "[DRIVE]" in sanitize_path(r"D:\Projects")

    def test_empty_string(self):
        assert sanitize_path("") == ""

    def test_none_input(self):
        assert sanitize_path(None) is None

    def test_no_sensitive_info(self):
        result = sanitize_path(r"E:\Projects\FreeAssetFilter")
        assert "[USER_HOME]" not in result
        assert "[DRIVE]" not in result or "E:" not in result


class TestSanitizeSensitiveInfo:
    def test_redact_password(self):
        result = sanitize_sensitive_info("password=secret123")
        assert "secret123" not in result
        assert "[REDACTED]" in result

    def test_redact_token(self):
        result = sanitize_sensitive_info("token=abc123xyz")
        assert "abc123xyz" not in result
        assert "[REDACTED]" in result

    def test_redact_api_key(self):
        result = sanitize_sensitive_info("api_key=mysecretkey")
        assert "mysecretkey" not in result
        assert "[REDACTED]" in result

    def test_redact_jwt(self):
        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc123"
        result = sanitize_sensitive_info(f"token={jwt}")
        assert "eyJhbGci" not in result

    def test_redact_aws_key(self):
        result = sanitize_sensitive_info("AKIAIOSFODNN7EXAMPLE")
        assert "AKIAIOSFODNN7EXAMPLE" not in result
        assert "[AWS_ACCESS_KEY_REDACTED]" in result

    def test_empty_string(self):
        assert sanitize_sensitive_info("") == ""

    def test_none_input(self):
        assert sanitize_sensitive_info(None) is None

    def test_no_sensitive_info(self):
        text = "Hello World"
        assert sanitize_sensitive_info(text) == text


class TestErrorHandling:
    def test_get_safe_error_for_ui(self):
        err = FileNotFoundError("missing")
        msg = get_safe_error_for_ui(err)
        assert "文件未找到" in msg
        assert "检查" in msg

    def test_get_safe_error_for_ui_none(self):
        msg = get_safe_error_for_ui(None)
        assert "请重试" in msg

    def test_get_safe_error_for_ui_various_types(self):
        errors = [
            (ValueError("bad value"), "参数错误"),
            (TypeError("wrong type"), "类型错误"),
            (MemoryError("no memory"), "内存不足"),
            (ConnectionError("network down"), "网络连接失败"),
        ]
        for err, expected in errors:
            msg = get_safe_error_for_ui(err)
            assert expected in msg





class TestTeeStream:
    def test_tee_stream_write(self):
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            log_path = f.name

        try:
            mock_stream = MagicMock()
            tee = TeeStream(mock_stream, log_path)
            tee.write("test message")
            mock_stream.write.assert_called_once_with("test message")
            tee.close()
        finally:
            if os.path.exists(log_path):
                os.remove(log_path)

    def test_tee_stream_flush(self):
        mock_stream = MagicMock()
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            log_path = f.name

        try:
            tee = TeeStream(mock_stream, log_path)
            tee.flush()
            mock_stream.flush.assert_called_once()
            tee.close()
        finally:
            if os.path.exists(log_path):
                os.remove(log_path)

    def test_tee_stream_close(self):
        mock_stream = MagicMock()
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            log_path = f.name

        try:
            tee = TeeStream(mock_stream, log_path)
            tee.close()
            assert tee._closed is True
        finally:
            if os.path.exists(log_path):
                os.remove(log_path)

    def test_tee_stream_encoding(self):
        mock_stream = MagicMock()
        mock_stream.encoding = 'utf-8'
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            log_path = f.name

        try:
            tee = TeeStream(mock_stream, log_path)
            assert tee.encoding == 'utf-8'
            tee.close()
        finally:
            if os.path.exists(log_path):
                os.remove(log_path)

    def test_tee_stream_writable(self):
        mock_stream = MagicMock()
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            log_path = f.name

        try:
            tee = TeeStream(mock_stream, log_path)
            assert tee.writable() is True
            tee.close()
        finally:
            if os.path.exists(log_path):
                os.remove(log_path)


class TestComponentSourceFilter:
    def test_filter_adds_source_file(self):
        filter_obj = ComponentSourceFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='test message',
            args=(),
            exc_info=None
        )
        assert filter_obj.filter(record) is True
        assert hasattr(record, 'source_file')


class TestComponentSourceFormatter:
    def test_formatter_with_source_file(self):
        formatter = ComponentSourceFormatter(
            '[%(levelname)s] [%(source_file)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='test message',
            args=(),
            exc_info=None
        )
        record.source_file = 'test_module'
        formatted = formatter.format(record)
        assert 'test_module' in formatted
        assert 'test message' in formatted


class TestAppLogger:
    @pytest.fixture(autouse=True)
    def setup_and_teardown(self):
        AppLogger._instance = None
        AppLogger._initialized = False
        import freeassetfilter.utils.app_logger as logger_module
        logger_module._app_logger = None
        yield
        AppLogger._instance = None
        AppLogger._initialized = False
        logger_module._app_logger = None

    def test_singleton_pattern(self):
        logger1 = get_logger()
        logger2 = get_logger()
        assert logger1 is logger2

    def test_get_log_file_path(self):
        logger = get_logger()
        path = logger.get_log_file_path()
        assert path is not None
        assert isinstance(path, str)
        assert path.endswith('.log')

    def test_log_directory_exists(self):
        logger = get_logger()
        assert os.path.isdir(logger.log_dir)

    def test_log_level_set(self):
        logger = get_logger()
        assert logger.logger.level == logging.DEBUG

    def test_logger_has_file_handler(self):
        logger = get_logger()
        file_handlers = [h for h in logger.logger.handlers
                        if isinstance(h, logging.FileHandler)]
        assert len(file_handlers) >= 1


class TestLoggerConvenienceFunctions:
    @pytest.fixture(autouse=True)
    def setup_and_teardown(self):
        AppLogger._instance = None
        AppLogger._initialized = False
        import freeassetfilter.utils.app_logger as logger_module
        logger_module._app_logger = None
        yield
        AppLogger._instance = None
        AppLogger._initialized = False
        logger_module._app_logger = None

    def test_debug_function(self):
        logger = get_logger()
        with patch.object(logger.logger, 'debug') as mock_debug:
            debug("test debug")
            mock_debug.assert_called_once_with("test debug")

    def test_info_function(self):
        logger = get_logger()
        with patch.object(logger.logger, 'info') as mock_info:
            info("test info")
            mock_info.assert_called_once_with("test info")

    def test_warning_function(self):
        logger = get_logger()
        with patch.object(logger.logger, 'warning') as mock_warning:
            warning("test warning")
            mock_warning.assert_called_once_with("test warning")

    def test_error_function(self):
        logger = get_logger()
        with patch.object(logger.logger, 'error') as mock_error:
            error("test error")
            mock_error.assert_called_once_with("test error")

    def test_critical_function(self):
        logger = get_logger()
        with patch.object(logger.logger, 'critical') as mock_critical:
            critical("test critical")
            mock_critical.assert_called_once_with("test critical")




class TestLogExceptionDetails:
    @pytest.fixture(autouse=True)
    def setup_and_teardown(self):
        AppLogger._instance = None
        AppLogger._initialized = False
        import freeassetfilter.utils.app_logger as logger_module
        logger_module._app_logger = None
        yield
        AppLogger._instance = None
        AppLogger._initialized = False
        logger_module._app_logger = None

    def test_log_exception_details_with_exception(self):
        logger = get_logger()
        try:
            raise ValueError("test error")
        except ValueError as e:
            with patch.object(logger.logger, 'error') as mock_error:
                log_exception_details("Error occurred", exc=e)
                mock_error.assert_called_once()
                call_args = mock_error.call_args[0][0]
                assert "Error occurred" in call_args
                assert "ValueError" in call_args
                assert "test error" in call_args

    def test_log_exception_details_without_exception(self):
        logger = get_logger()
        with patch.object(logger.logger, 'info') as mock_info:
            log_exception_details("Simple message", level='info')
            mock_info.assert_called_once()

    def test_exception_details_convenience_function(self):
        logger = get_logger()
        with patch.object(logger.logger, 'error') as mock_error:
            exception_details("Test error")
            mock_error.assert_called_once()


class TestInstallConsoleCapture:
    @pytest.fixture(autouse=True)
    def setup_and_teardown(self):
        AppLogger._instance = None
        AppLogger._initialized = False
        import freeassetfilter.utils.app_logger as logger_module
        logger_module._app_logger = None
        yield
        AppLogger._instance = None
        AppLogger._initialized = False
        logger_module._app_logger = None

    def test_install_console_capture_returns_bool(self):
        result = install_console_capture()
        assert isinstance(result, bool)

    def test_install_console_capture_with_custom_path(self):
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            log_path = f.name

        try:
            result = install_console_capture(log_path)
            assert isinstance(result, bool)
        finally:
            import gc
            gc.collect()
            import time
            time.sleep(0.1)
            try:
                if os.path.exists(log_path):
                    os.remove(log_path)
            except (PermissionError, OSError):
                pass
