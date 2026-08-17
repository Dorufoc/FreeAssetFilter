# -*- coding: utf-8 -*-
"""test_app_logger: app_logger.py 覆盖测试（todo-10, unit/utils 批 1）。

覆盖：sanitize_path / sanitize_sensitive_info 全矩阵、TeeStream、
ComponentSourceFilter / ComponentSourceFormatter、get_safe_error_for_ui、
log_exception_details、install_console_capture（幂等 + 文件可写）。
"""

from __future__ import annotations

import logging
import re
import sys

import pytest
from unittest.mock import MagicMock, patch

from freeassetfilter.utils.app_logger import (
    AppLogger,
    ComponentSourceFilter,
    ComponentSourceFormatter,
    TeeStream,
    critical,
    debug,
    error,
    exception_details,
    get_logger,
    get_safe_error_for_ui,
    info,
    install_console_capture,
    log_exception,
    log_exception_details,
    sanitize_path,
    sanitize_sensitive_info,
    warning,
)

import freeassetfilter.utils.app_logger as _logger_module


@pytest.fixture(autouse=True)
def _reset_logger_module() -> None:
    """每个测试前清空 app_logger 模块级单例（conftest 的 reset_singletons 不覆盖它）。

    AppLogger 类级 ``_instance/_initialized`` 由 conftest 归零，但模块级
    ``_app_logger`` 缓存在测试间持久，这里保证 ``get_logger()`` 返回新实例。

    Returns:
        None。
    """
    _logger_module._app_logger = None
    yield
    _logger_module._app_logger = None


class TestSanitizePath:
    """sanitize_path 红action矩阵（Windows/Linux/Mac 路径变体）。"""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (r"C:\Users\john\Documents", "[USER_HOME]"),
            (r"C:\Users\john\AppData\Roaming", "[USER_HOME]"),
            (r"C:\Windows\System32", "[SYSTEM]"),
            (r"C:\Program Files\7-Zip", "[PROGRAM]"),
            (r"/home/user/documents", "[USER_HOME]"),
            (r"/Users/user/documents", "[USER_HOME]"),
            (r"D:\Projects", "[DRIVE]"),
            (r"c:\users\bob\file.txt", "[USER_HOME]"),
        ],
        ids=[
            "win-user",
            "win-appdata",
            "win-system",
            "win-program-files",
            "linux-home",
            "mac-home",
            "win-drive",
            "lowercase-drive-user",
        ],
    )
    def test_redacts_sensitive_path(self, raw: str, expected: str) -> None:
        """敏感路径被替换为脱敏占位符。

        Args:
            raw: 原始路径。
            expected: 期望出现在结果中的占位符。
        """
        result = sanitize_path(raw)
        assert expected in result

    def test_empty_string_unchanged(self) -> None:
        """空字符串原样返回。"""
        assert sanitize_path("") == ""

    def test_none_unchanged(self) -> None:
        """None 输入原样返回。"""
        assert sanitize_path(None) is None

    def test_relative_path_unchanged(self) -> None:
        """不含敏感前缀的相对路径不被篡改。"""
        raw = "sub/dir/file.txt"
        assert sanitize_path(raw) == raw

    def test_no_username_leak_in_drive_only(self) -> None:
        """纯盘符路径只被脱敏为 [DRIVE]，不泄露用户名。"""
        result = sanitize_path(r"E:\Projects\FreeAssetFilter")
        assert "E:" not in result
        assert "[DRIVE]" in result


class TestSanitizeSensitiveInfo:
    """sanitize_sensitive_info 全矩阵（凭据类 key=value 与 JWT/AWS/PEM 特例）。"""

    @pytest.mark.parametrize(
        ("raw", "secret"),
        [
            ("password=secret123", "secret123"),
            ("passwd=pw123", "pw123"),
            ("pwd=pxyz", "pxyz"),
            ("secret=s3cr3t", "s3cr3t"),
            ("token=t0k3n42", "t0k3n42"),
            ("api_key=ak123", "ak123"),
            ("api-key=bk456", "bk456"),
            ("key=kv789", "kv789"),
            ("auth=au321", "au321"),
            ("credential=cd111", "cd111"),
            ("private_key=pk222", "pk222"),
            ("oauth_token=ot333", "ot333"),
            ("access_token=at444", "at444"),
            ("refresh_token=rt555", "rt555"),
            ("aws_access_key_id=aki666", "aki666"),
            ("aws_secret_access_key=ask777", "ask777"),
            ("aws_key=awsk888", "awsk888"),
        ],
    )
    def test_redacts_key_value_credentials(self, raw: str, secret: str) -> None:
        """各种 key=value 型凭据被脱敏。

        Args:
            raw: 含凭据的文本。
            secret: 不应残留在结果中的秘密片段。
        """
        result = sanitize_sensitive_info(raw)
        assert secret not in result
        assert "[REDACTED]" in result

    @pytest.mark.parametrize(
        ("raw", "secret"),
        [
            (
                "token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc123",
                "eyJhbGci",
            ),
            (
                "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc123",
                "eyJhbGci",
            ),
            ("AKIAIOSFODNN7EXAMPLE", "AKIAIOSFODNN7EXAMPLE"),
            ("authorization: bearer abc123", "abc123"),
            ("auth token bearer abc.def.ghi", "abc.def.ghi"),
            ("-----BEGIN RSA PRIVATE KEY-----\nabcd\n-----END RSA PRIVATE KEY-----", "RSA"),
        ],
        ids=["jwt-with-prefix", "standalone-jwt", "aws-key", "authorization-bearer", "bearer-jwt", "pem-block"],
    )
    def test_redacts_special_token_formats(self, raw: str, secret: str) -> None:
        """JWT / AWS / Bearer / PEM 等特殊格式被脱敏。

        Args:
            raw: 含特殊格式凭据的文本。
            secret: 不应残留在结果中的秘密片段。
        """
        result = sanitize_sensitive_info(raw)
        assert secret not in result

    def test_redacts_in_sentence(self) -> None:
        """嵌入长句的密码也被脱敏。"""
        result = sanitize_sensitive_info("login ok password=hunter2 host=localhost")
        assert "hunter2" not in result
        assert "[REDACTED]" in result

    def test_redacts_multi_no_secret_left(self) -> None:
        """多个凭据同时存在时全部脱敏。"""
        result = sanitize_sensitive_info("password=alpha123 token=bravo456 api_key=charlie789")
        assert result == "password=[REDACTED] token=[REDACTED] api_key=[REDACTED]"

    def test_empty_string_unchanged(self) -> None:
        """空字符串原样返回。"""
        assert sanitize_sensitive_info("") == ""

    def test_none_unchanged(self) -> None:
        """None 输入原样返回。"""
        assert sanitize_sensitive_info(None) is None

    def test_plain_text_unchanged(self) -> None:
        """无凭据的普通文本不被篡改。"""
        text = "Hello World, the quick brown fox"
        assert sanitize_sensitive_info(text) == text


class TestSafeErrorForUi:
    """get_safe_error_for_ui：异常类型映射到友好中文消息。"""

    def test_known_error_type(self) -> None:
        """已知异常类型返回对应提示。"""
        assert "文件未找到" in get_safe_error_for_ui(FileNotFoundError("missing"))

    def test_none_error(self) -> None:
        """None 异常返回通用提示。"""
        assert "请重试" in get_safe_error_for_ui(None)

    @pytest.mark.parametrize(
        ("exc", "fragment"),
        [
            (ValueError("bad value"), "参数错误"),
            (TypeError("wrong type"), "类型错误"),
            (MemoryError("no memory"), "内存不足"),
            (ConnectionError("network down"), "网络连接失败"),
            (TimeoutError("too slow"), "超时"),
            (PermissionError("denied"), "权限不足"),
        ],
        ids=["value", "type", "memory", "connection", "timeout", "permission"],
    )
    def test_known_error_variants(self, exc: Exception, fragment: str) -> None:
        """多种已知异常类型映射正确。

        Args:
            exc: 异常实例。
            fragment: 期望出现在消息中的片段。
        """
        assert fragment in get_safe_error_for_ui(exc)

    def test_unknown_error_type(self) -> None:
        """未知异常类型回退到通用提示。"""
        class UnusualError(Exception):
            pass

        assert "操作失败，请重试" == get_safe_error_for_ui(UnusualError("x"))


class TestTeeStream:
    """TeeStream 双写流：原始流 + 日志文件。"""

    def test_write_forwards_and_logs(self, tmp_path) -> None:
        """write 同时写入原始流与日志文件。"""
        mock_stream = MagicMock()
        log_path = str(tmp_path / "tee.log")
        tee = TeeStream(mock_stream, log_path)
        try:
            tee.write("test message")
            mock_stream.write.assert_called_once_with("test message")
            tee.flush()
            with open(log_path, "r", encoding="utf-8") as f:
                assert "test message" in f.read()
        finally:
            tee.close()

    def test_write_returns_original_count(self, tmp_path) -> None:
        """write 返回原始流写入字节数。"""
        mock_stream = MagicMock()
        mock_stream.write.return_value = 7
        tee = TeeStream(mock_stream, str(tmp_path / "tee.log"))
        try:
            assert tee.write("hello") == 7
        finally:
            tee.close()

    def test_write_none_returns_zero(self, tmp_path) -> None:
        """write(None) 返回 0 且不崩溃。"""
        tee = TeeStream(MagicMock(), str(tmp_path / "tee.log"))
        try:
            assert tee.write(None) == 0
        finally:
            tee.close()

    def test_write_coerces_non_str(self, tmp_path) -> None:
        """非字符串输入被字符串化后写入日志。"""
        log_path = str(tmp_path / "tee.log")
        tee = TeeStream(MagicMock(), log_path)
        try:
            tee.write(123)
            tee.flush()
            with open(log_path, "r", encoding="utf-8") as f:
                assert "123" in f.read()
        finally:
            tee.close()

    def test_write_original_failure_returns_zero(self, tmp_path) -> None:
        """原始流写入失败时不抛出，返回 0。"""
        mock_stream = MagicMock()
        mock_stream.write.side_effect = OSError("broken pipe")
        tee = TeeStream(mock_stream, str(tmp_path / "tee.log"))
        try:
            assert tee.write("hello") == 0
        finally:
            tee.close()

    def test_flush_flushes_original(self, tmp_path) -> None:
        """flush 转发到原始流。"""
        mock_stream = MagicMock()
        tee = TeeStream(mock_stream, str(tmp_path / "tee.log"))
        try:
            tee.flush()
            mock_stream.flush.assert_called_once()
        finally:
            tee.close()

    def test_writable_always_true(self, tmp_path) -> None:
        """writable() 恒为 True。"""
        tee = TeeStream(MagicMock(), str(tmp_path / "tee.log"))
        try:
            assert tee.writable() is True
        finally:
            tee.close()

    def test_encoding_taken_from_original(self, tmp_path) -> None:
        """encoding 优先来自原始流。"""
        mock_stream = MagicMock()
        mock_stream.encoding = "cp1252"
        tee = TeeStream(mock_stream, str(tmp_path / "tee.log"))
        try:
            assert tee.encoding == "cp1252"
        finally:
            tee.close()

    def test_encoding_fallback_to_argument(self, tmp_path) -> None:
        """原始流无 encoding 属性时使用构造参数。"""

        class DumbStream:
            def flush(self) -> None:
                pass

        tee = TeeStream(DumbStream(), str(tmp_path / "tee.log"), encoding="latin-1")
        try:
            assert tee.encoding == "latin-1"
        finally:
            tee.close()

    def test_isatty_false_for_non_tty(self, tmp_path) -> None:
        """非终端流 isatty() 为 False。"""
        with open(tmp_path / "plain.txt", "w", encoding="utf-8") as real_stream:
            tee = TeeStream(real_stream, str(tmp_path / "tee.log"))
            try:
                assert tee.isatty() is False
            finally:
                tee.close()

    def test_closed_state(self, tmp_path) -> None:
        """close 后 closed 为 True，且二次 close 不崩溃。"""

        class PlainClosedStream:
            closed = False

            def flush(self) -> None:
                pass

        tee = TeeStream(PlainClosedStream(), str(tmp_path / "tee.log"))
        assert tee.closed is False
        tee.close()
        assert tee.closed is True
        tee.close()  # 幂等

    def test_fileno_raises_when_no_original(self, tmp_path) -> None:
        """原始流为 None 时 fileno() 抛 OSError。"""
        tee = TeeStream(None, str(tmp_path / "tee.log"))
        try:
            with pytest.raises(OSError):
                tee.fileno()
        finally:
            tee.close()

    def test_filter_patterns_skips_log(self, tmp_path) -> None:
        """命中 filter_patterns 的行写入原始流但不写入日志。"""
        mock_stream = MagicMock()
        log_path = str(tmp_path / "tee.log")
        tee = TeeStream(mock_stream, log_path, filter_patterns=["Unknown property"])
        try:
            tee.write("Unknown property foo\n")
            tee.write("normal line\n")
            tee.flush()
            assert mock_stream.write.call_count == 2
            with open(log_path, "r", encoding="utf-8") as f:
                content = f.read()
                assert "normal line" in content
                assert "Unknown property" not in content
        finally:
            tee.close()

    def test_getattr_delegates_to_original(self, tmp_path) -> None:
        """未定义属性经 __getattr__ 委托给原始流。"""
        mock_stream = MagicMock()
        mock_stream.some_attr = "delegated"
        tee = TeeStream(mock_stream, str(tmp_path / "tee.log"))
        try:
            assert tee.some_attr == "delegated"
        finally:
            tee.close()


class TestComponentSourceFilter:
    """ComponentSourceFilter：为记录附加 source_file。"""

    def test_filter_adds_source_file(self) -> None:
        """filter 返回 True 并设置 source_file 属性。"""
        filter_obj = ComponentSourceFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="test message",
            args=(),
            exc_info=None,
        )
        assert filter_obj.filter(record) is True
        assert hasattr(record, "source_file")


class TestComponentSourceFormatter:
    """ComponentSourceFormatter：含 source_file 的格式化 + 敏感信息脱敏。"""

    def _make_record(self, msg: str, source_file: object = None) -> logging.LogRecord:
        """构造一条 LogRecord。

        Args:
            msg: 日志消息。
            source_file: 预设的 source_file 属性（None 则不预设）。

        Returns:
            LogRecord: 构造出的记录。
        """
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg=msg,
            args=(),
            exc_info=None,
        )
        if source_file is not None:
            record.source_file = source_file
        return record

    def test_formatter_keeps_message_and_source(self) -> None:
        """带 source_file 的记录保留两者。"""
        formatter = ComponentSourceFormatter("[%(levelname)s] [%(source_file)s] %(message)s")
        formatted = formatter.format(self._make_record("hello world", source_file="test_module"))
        assert "test_module" in formatted
        assert "hello world" in formatted

    def test_formatter_defaults_unknown_source(self) -> None:
        """无 source_file 记录回退到 unknown。"""
        formatter = ComponentSourceFormatter("[%(source_file)s] %(message)s")
        formatted = formatter.format(self._make_record("plain"))
        assert "unknown" in formatted

    def test_formatter_sanitizes_path(self) -> None:
        """格式化输出中的敏感路径被脱敏。"""
        formatter = ComponentSourceFormatter("%(message)s")
        formatted = formatter.format(self._make_record(r"failed at C:\Users\john\file.txt"))
        assert r"C:\Users\john" not in formatted
        assert "[USER_HOME]" in formatted

    def test_formatter_sanitizes_credentials(self) -> None:
        """格式化输出中的凭据被脱敏。"""
        formatter = ComponentSourceFormatter("%(message)s")
        formatted = formatter.format(self._make_record("login token=abc123"))
        assert "abc123" not in formatted
        assert "[REDACTED]" in formatted


class TestLogExceptionDetails:
    """log_exception_details：异常详情与堆栈记录（含脱敏）。"""

    def test_with_exception_records_details(self) -> None:
        """显式传入异常时记录完整信息。"""
        logger = get_logger()
        with patch.object(logger.logger, "error") as mock_error:
            try:
                raise ValueError("test error")
            except ValueError as exc:
                log_exception_details("Error occurred", exc=exc)
            mock_error.assert_called_once()
            text = mock_error.call_args[0][0]
            assert "Error occurred" in text
            assert "ValueError" in text
            assert "test error" in text

    def test_without_exception_uses_level_message(self) -> None:
        """无异常上下文按指定 level 记录纯消息。"""
        logger = get_logger()
        with patch.object(logger.logger, "info") as mock_info:
            log_exception_details("Simple message", level="info")
            mock_info.assert_called_once()
            assert "Simple message" in mock_info.call_args[0][0]

    def test_picks_up_current_exception(self) -> None:
        """exc=None 时读取当前异常上下文。"""
        logger = get_logger()
        with patch.object(logger.logger, "error") as mock_error:
            try:
                raise RuntimeError("boom")
            except RuntimeError:
                log_exception_details("context message")
            mock_error.assert_called_once()
            assert "boom" in mock_error.call_args[0][0]

    def test_message_sensitive_info_redacted(self) -> None:
        """消息中的凭据在记录前被脱敏。"""
        logger = get_logger()
        with patch.object(logger.logger, "error") as mock_error:
            try:
                raise OSError("disk failure")
            except OSError as exc:
                log_exception_details("failed password=secret123", exc=exc)
            assert "secret123" not in mock_error.call_args[0][0]
            assert "[REDACTED]" in mock_error.call_args[0][0]

    def test_unknown_level_falls_back_to_error(self) -> None:
        """未知 level（但存在异常）回退到 error 级别。"""
        logger = get_logger()
        with patch.object(logger.logger, "error") as mock_error:
            log_exception_details("msg", exc=ValueError("bad"), level="not-a-level")
            mock_error.assert_called_once()
            assert "msg" in mock_error.call_args[0][0]

    def test_exception_details_convenience_function(self) -> None:
        """便捷函数 exception_details 委托到 log_exception_details。"""
        logger = get_logger()
        with patch.object(logger.logger, "error") as mock_error:
            exception_details("Test error")
            mock_error.assert_called_once()
            assert "Test error" in mock_error.call_args[0][0]


class TestLogException:
    """log_exception：未捕获异常钩子记录。"""

    def test_records_uncaught_exception(self) -> None:
        """记录异常类型、值与堆栈。"""
        logger = get_logger()
        with patch.object(logger.logger, "error") as mock_error:
            try:
                raise IndexError("boom index")
            except IndexError:
                log_exception(*sys.exc_info())
            mock_error.assert_called_once()
            text = mock_error.call_args[0][0]
            assert "IndexError" in text
            assert "boom index" in text
            assert "检测到未捕获的异常" in text

    def test_sanitizes_sensitive_value(self) -> None:
        """异常值中的敏感信息被脱敏。"""
        logger = get_logger()
        with patch.object(logger.logger, "error") as mock_error:
            try:
                raise ValueError("failed password=topsecret")
            except ValueError:
                log_exception(*sys.exc_info())
            assert "topsecret" not in mock_error.call_args[0][0]
            assert "[REDACTED]" in mock_error.call_args[0][0]

    def test_recursion_guard_reset(self) -> None:
        """记录结束后递归保护标志复位。"""
        logger = get_logger()
        with patch.object(logger.logger, "error"):
            try:
                raise ValueError("x")
            except ValueError:
                log_exception(*sys.exc_info())
        assert _logger_module._log_exception_in_progress is False


class TestModuleLevelFunctions:
    """模块级便捷日志函数委托到 logger。"""

    @pytest.mark.parametrize(
        ("func_name", "level_name"),
        [("debug", "debug"), ("info", "info"), ("warning", "warning"), ("error", "error"), ("critical", "critical")],
    )
    def test_delegates_to_logger_method(self, func_name: str, level_name: str) -> None:
        """模块级函数调用对应 logger 方法。

        Args:
            func_name: 模块级函数名。
            level_name: logger 方法名。
        """
        logger = get_logger()
        func = {"debug": debug, "info": info, "warning": warning, "error": error, "critical": critical}[func_name]
        with patch.object(logger.logger, level_name) as mock_level:
            func("payload")
            mock_level.assert_called_once_with("payload")

    def test_app_logger_singleton(self) -> None:
        """AppLogger 单例模式。"""
        first = AppLogger()
        second = AppLogger()
        assert first is second

    def test_reset_exposed(self) -> None:
        """conftest reset 后重新创建 logger 可得到文件路径。"""
        _logger_module._app_logger = None
        logger = get_logger()
        assert logger.get_log_file_path() is not None
        assert logger.get_log_file_path().endswith(".log")

    def test_logger_is_app_logger_instance(self) -> None:
        """get_logger 返回 AppLogger 派生实例。"""
        assert isinstance(get_logger(), AppLogger)


class TestInstallConsoleCapture:
    """install_console_capture：安装双写流 + 幂等 + 文件可写。"""

    @pytest.fixture(autouse=True)
    def _restore_streams(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试前后恢复 sys.stdout / sys.stderr 原值。"""
        monkeypatch.setattr(sys, "stdout", sys.stdout)
        monkeypatch.setattr(sys, "stderr", sys.stderr)
        yield

    def test_installs_and_writes_to_file(self, tmp_path) -> None:
        """安装后 stdout/stderr 写入日志文件，返回值 True。"""
        log_path = str(tmp_path / "capture.log")
        result = install_console_capture(log_path)
        assert result is True
        assert isinstance(sys.stdout, TeeStream)
        assert isinstance(sys.stderr, TeeStream)

        sys.stdout.write("hello out\n")
        sys.stderr.write("hello err\n")
        sys.stdout.flush()
        sys.stderr.flush()

        with open(log_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "hello out" in content
        assert "hello err" in content

    def test_stderr_filter_applied(self, tmp_path) -> None:
        """stderr 的 MpV 噪音过滤器生效。"""
        log_path = str(tmp_path / "capture.log")
        assert install_console_capture(log_path) is True
        sys.stderr.write("verbose Unknown property foo\n")
        sys.stderr.write("real error line\n")
        sys.stderr.flush()

        with open(log_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "real error line" in content
        assert "Unknown property" not in content

    def test_second_install_is_idempotent(self, tmp_path) -> None:
        """重复调用同路径返回 False 且不崩溃（幂等）。"""
        log_path = str(tmp_path / "capture.log")
        assert install_console_capture(log_path) is True
        # 第二次调用时 stdout/stderr 已是 TeeStream，不重复安装。
        assert install_console_capture(log_path) is False
        assert isinstance(sys.stdout, TeeStream)
        assert isinstance(sys.stderr, TeeStream)

    def test_no_logger_path_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """logger 无 get_log_file_path 时返回 False。"""

        class NoPathLogger:
            pass

        monkeypatch.setattr(_logger_module, "get_logger", lambda: NoPathLogger())
        assert install_console_capture() is False


class TestSanitizePathRedactionComplete:
    """覆盖性补充：多个路径同时出现在一条日志里也全部脱敏。"""

    def test_multiple_windows_paths(self) -> None:
        """一条消息中多个 Windows 路径都脱敏。"""
        result = sanitize_path(r"C:\Users\alice\data C:\Windows\Temp /home/bob/x")
        assert "alice" not in result
        assert "[SYSTEM]" in result
        assert "bob" not in result


class TestSanitizeSensitiveInfoTrailing:
    """覆盖性补充：key= 后无值的边界不崩溃。"""

    def test_empty_value_after_equals(self) -> None:
        """password= 后无值时不抛出。"""
        result = sanitize_sensitive_info("password=")
        assert isinstance(result, str)
        assert "password=" in result