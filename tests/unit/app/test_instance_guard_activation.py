"""单实例唤醒事件（``Sopeek_SingleInstance_Activate``）的单元测试。

真实命名事件只在 Windows 上有意义；其余平台跳过往返用例，仅验证空句柄
路径安全。
"""

from __future__ import annotations

import os
import sys

import pytest

from sopeek.app import instance_guard

pytestmark = pytest.mark.unit


@pytest.fixture()
def open_request_path(tmp_path, monkeypatch):
    """把打开请求文件重定向到临时目录，避免污染真实 state 目录。"""
    request_file = tmp_path / "open_request.json"
    monkeypatch.setattr(
        instance_guard, "_get_open_request_file_path", lambda: str(request_file)
    )
    return request_file


@pytest.mark.skipif(sys.platform != "win32", reason="命名事件仅 Windows 可用")
def test_activation_event_roundtrip() -> None:
    """创建事件 → 第二实例置位 → 消费一次 → 自动重置后不再触发。"""
    handle = instance_guard._create_activation_event()
    assert handle, "唤醒事件创建失败（句柄为空）"
    try:
        assert instance_guard._consume_activation_event(handle) is False

        assert instance_guard._signal_existing_instance() is True
        assert instance_guard._consume_activation_event(handle) is True
        # 自动重置事件被消费后信号即清除。
        assert instance_guard._consume_activation_event(handle) is False
    finally:
        # 所有路径都释放句柄，避免命名事件对象残留。
        instance_guard._release_activation_event(handle)


def test_activation_event_null_handle_is_safe() -> None:
    """空句柄：消费返回 False，释放不抛异常。"""
    assert instance_guard._consume_activation_event(None) is False
    instance_guard._release_activation_event(None)


def test_open_request_roundtrip(open_request_path) -> None:
    """写入 → 读取一次拿到绝对路径 → 文件被消费删除 → 再次读取为空。"""
    target = os.path.join(os.getcwd(), "sample.txt")
    assert instance_guard._write_open_request(target) is True
    assert open_request_path.is_file()

    assert instance_guard._read_and_clear_open_request() == os.path.abspath(target)
    assert not open_request_path.exists()
    assert instance_guard._read_and_clear_open_request() is None


def test_open_request_discard(open_request_path) -> None:
    """丢弃会删除残留请求，重复丢弃是幂等的。"""
    assert instance_guard._write_open_request("C:\\temp\\a.txt") is True
    instance_guard._discard_open_request()
    assert not open_request_path.exists()
    instance_guard._discard_open_request()  # 文件已不存在也不能抛异常
    assert instance_guard._read_and_clear_open_request() is None


def test_open_request_rejects_corrupt_file(open_request_path) -> None:
    """损坏的 JSON 或缺少 path 字段时返回 None 并删除文件，不抛异常。"""
    open_request_path.write_text("{not-json", encoding="utf-8")
    assert instance_guard._read_and_clear_open_request() is None
    assert not open_request_path.exists()

    open_request_path.write_text('{"path": ""}', encoding="utf-8")
    assert instance_guard._read_and_clear_open_request() is None
    assert not open_request_path.exists()
