# -*- coding: utf-8 -*-
"""
MD5CalculationTask 单元测试
测试 freeassetfilter/core/workers/staging_tasks.py 中的 MD5CalculationTask。
"""

import hashlib
from unittest.mock import patch

import pytest

from freeassetfilter.core.heartbeat_manager import HeartbeatManager
from freeassetfilter.core.workers.staging_tasks import MD5CalculationTask


class TestMD5CalculationTask:
    """MD5CalculationTask 全覆盖测试。

    测试策略：
    - 将 HeartbeatManager.request_main_thread 替换为同步调用（monkeypatch），
      使回调在 run() 内部立即执行，无需 Qt 事件循环。
    - 使用 tmp_path 创建/删除测试文件。
    """

    @pytest.fixture(autouse=True)
    def _patch_heartbeat(self, monkeypatch):
        """将 HeartbeatManager.request_main_thread 替换为同步执行。

        原方法将回调排队到主线程心跳 tick 中执行，需要 Qt 事件循环。
        替换后回调立即在当前线程执行，使测试可以同步验证结果。
        """
        monkeypatch.setattr(
            HeartbeatManager,
            "request_main_thread",
            lambda self, fn, priority=5: fn(),
        )

    # ── 正确计算 MD5 ────────────────────────────────────────────────

    def test_md5_valid_file(self, tmp_path):
        """对存在文件正确计算 MD5 并回调 hexdigest。

        验证：
        - 回调收到正确的 MD5 十六进制字符串。
        - 回调被恰好调用一次。
        """
        content = b"test content for md5 validation"
        f = tmp_path / "valid.dat"
        f.write_bytes(content)
        expected = hashlib.md5(content).hexdigest()

        results: list[str | None] = []
        task = MD5CalculationTask(str(f), lambda r: results.append(r))
        task.run()

        assert len(results) == 1
        assert results[0] == expected

    def test_md5_empty_file(self, tmp_path):
        """空文件返回空字符串的 MD5（d41d8cd98f00b204e9800998ecf8427e）。"""
        f = tmp_path / "empty.dat"
        f.write_text("")
        expected = hashlib.md5(b"").hexdigest()

        results: list[str | None] = []
        task = MD5CalculationTask(str(f), lambda r: results.append(r))
        task.run()

        assert len(results) == 1
        assert results[0] == expected

    def test_md5_large_file(self, tmp_path):
        """大文件（1MB）正确计算 MD5，覆盖流式分块读取路径。

        MD5CalculationTask 以 4KB 块读取文件，此测试验证
        多块场景下哈希值正确。
        """
        import os

        content = os.urandom(1024 * 1024)
        f = tmp_path / "large.dat"
        f.write_bytes(content)
        expected = hashlib.md5(content).hexdigest()

        results: list[str | None] = []
        task = MD5CalculationTask(str(f), lambda r: results.append(r))
        task.run()

        assert len(results) == 1
        assert results[0] == expected

    # ── 文件不存在 ──────────────────────────────────────────────────

    def test_file_not_found(self, tmp_path):
        """文件不存在时回调 None。"""
        non_existent = str(tmp_path / "does_not_exist.dat")

        results: list[str | None] = []
        task = MD5CalculationTask(non_existent, lambda r: results.append(r))
        task.run()

        assert len(results) == 1
        assert results[0] is None

    # ── 权限/IO 错误 ─────────────────────────────────────────────────

    def test_permission_denied(self, tmp_path):
        """PermissionError 时回调 None。"""
        f = tmp_path / "no_access.dat"
        f.write_bytes(b"some content")

        results: list[str | None] = []
        task = MD5CalculationTask(str(f), lambda r: results.append(r))

        with patch("builtins.open", side_effect=PermissionError("Access denied")):
            task.run()

        assert len(results) == 1
        assert results[0] is None

    def test_io_error(self, tmp_path):
        """IOError / OSError 时回调 None。"""
        f = tmp_path / "io_error.dat"
        f.write_bytes(b"some content")

        results: list[str | None] = []
        task = MD5CalculationTask(str(f), lambda r: results.append(r))

        with patch("builtins.open", side_effect=IOError("I/O error")):
            task.run()

        assert len(results) == 1
        assert results[0] is None

    # ── 回调被调用验证 ────────────────────────────────────────────────

    def test_callback_invoked_once_for_valid_file(self, tmp_path):
        """对存在文件回调函数被恰好调用一次。"""
        f = tmp_path / "cb_check.dat"
        f.write_bytes(b"test")

        call_count = 0

        def callback(result: str | None) -> None:
            nonlocal call_count
            call_count += 1

        task = MD5CalculationTask(str(f), callback)
        task.run()

        assert call_count == 1

    def test_callback_invoked_once_for_nonexistent_file(self, tmp_path):
        """对不存在的文件回调函数被恰好调用一次。"""
        non_existent = str(tmp_path / "ghost.dat")

        call_count = 0

        def callback(result: str | None) -> None:
            nonlocal call_count
            call_count += 1

        task = MD5CalculationTask(non_existent, callback)
        task.run()

        assert call_count == 1
