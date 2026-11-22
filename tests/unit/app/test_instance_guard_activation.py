"""单实例唤醒事件（``Sopeek_SingleInstance_Activate``）的单元测试。

真实命名事件只在 Windows 上有意义；其余平台跳过往返用例，仅验证空句柄
路径安全。
"""

from __future__ import annotations

import sys

import pytest

from sopeek.app import instance_guard

pytestmark = pytest.mark.unit


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
