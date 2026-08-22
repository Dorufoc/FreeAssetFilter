# -*- coding: utf-8 -*-
"""Rust 桥新导出接线单测（thumbnail-rust-refactor todo 25）。

覆盖 ``RustThumbnailBridge`` 新增的 4 个方法级封装（既有 14 个绑定零改动）：

* ``get_error_log() -> str``：JSON 数组字符串，降级返回 ``"[]"``；
* ``clear_error_log() -> bool``：成功 ``True``，降级 ``False``；
* ``get_supported_formats() -> str``：JSON 对象字符串，降级返回 ``"{}"``；
* ``get_ffmpeg_capabilities() -> str``：JSON 对象字符串，降级返回 ``"{}"``。

验证维度：

1. **真实 DLL 路径**（dev_release_dll 优先 target/release，需先
   ``cargo build --release``）：返回类型、JSON 可解析性、形状契约，
   以及 T3 跳过端到端回路（伪 .cr2 文件生成失败 → errorlog 出现
   ``format="cr2" / status=-6`` 条目 → 清空后为空数组）；
2. **降级路径**：monkeypatch ``_available=False`` 或对应
   ``_supports_* = False`` 时四个方法分别返回安全降级值且不抛异常。

既有断言零改动：本文件不修改 ``test_rust_thumbnail_bridge.py`` 的任何用例。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from freeassetfilter.core.native.bridges.rust_thumbnail_bridge import (
    RustThumbnailBridge,
)

pytestmark = [pytest.mark.unit, pytest.mark.rust]

bridge = pytest.importorskip(
    "freeassetfilter.core.native.bridges.rust_thumbnail_bridge"
)


# =============================================================================
# 能力标记
# =============================================================================
class TestNewExportCapabilityFlags:
    """todo 25 新增的三个 ``_supports_*`` 探测标记。"""

    def test_new_capability_flags_are_bool(self) -> None:
        """errorlog / formats / caps 标记均为 bool（绑定探测结果）。"""
        inst = RustThumbnailBridge()
        assert isinstance(inst._supports_errorlog, bool)  # noqa: SLF001
        assert isinstance(inst._supports_formats, bool)  # noqa: SLF001
        assert isinstance(inst._supports_caps, bool)  # noqa: SLF001


# =============================================================================
# 真实 DLL 路径：4 个方法的返回类型与形状契约
# =============================================================================
class TestErrorLogBridgeMethods:
    """``get_error_log`` / ``clear_error_log`` 方法级封装。"""

    def test_get_error_log_returns_valid_json_array_str(self) -> None:
        """返回 str 且可解析为 JSON 数组；条目字段齐备。"""
        inst = RustThumbnailBridge()
        payload_text = inst.get_error_log()
        assert isinstance(payload_text, str)
        payload = json.loads(payload_text)
        assert isinstance(payload, list)
        for item in payload:
            assert isinstance(item, dict)
            assert {"path", "format", "status", "message", "timestamp"}.issubset(
                item.keys()
            )

    def test_clear_error_log_returns_true(self) -> None:
        """清空成功返回 True，随后查询为空数组字符串。"""
        inst = RustThumbnailBridge()
        assert inst.clear_error_log() is True
        assert json.loads(inst.get_error_log()) == []

    def test_round_trip_t3_skip_writes_error_log(self, tmp_path: Any) -> None:
        """T3 端到端回路：伪 .cr2 生成失败 → errorlog 记录 cr2/-6 → 清空复原。

        验证 lib.rs T3 扩展名路由经桥透传：generate_rgba 返回 None（status=-6
        被吞掉），但错误进入环形缓冲并可经 get_error_log 读出。
        """
        inst = RustThumbnailBridge()
        assert inst.clear_error_log() is True

        fake_cr2 = tmp_path / "broken.cr2"
        fake_cr2.write_bytes(b"not-a-real-cr2-payload")
        try:
            # T3 命中：快速返回 -6，桥层安全降级为 None
            assert inst.generate_rgba(str(fake_cr2), 32, 32) is None

            entries = json.loads(inst.get_error_log())
            matched = [
                e
                for e in entries
                if e.get("format") == "cr2" and e.get("status") == -6
            ]
            assert matched, "T3 跳过应写入一条 format=cr2/status=-6 记录"
            assert matched[-1]["message"] == "T3 unsupported format"
            assert str(fake_cr2) in matched[-1]["path"]
            assert isinstance(matched[-1]["timestamp"], int)
        finally:
            # 清理全局缓冲，避免影响同进程后续用例
            assert inst.clear_error_log() is True


class TestSupportedFormatsBridgeMethod:
    """``get_supported_formats`` 方法级封装。"""

    def test_returns_valid_json_object_with_14_format_ids(self) -> None:
        """返回 str 且可解析为含 formats 数组的 JSON 对象（14 组标识）。"""
        inst = RustThumbnailBridge()
        payload_text = inst.get_supported_formats()
        assert isinstance(payload_text, str)
        payload = json.loads(payload_text)
        assert isinstance(payload, dict)
        formats = payload["formats"]
        assert isinstance(formats, list)
        assert len(formats) == 14
        for entry in formats:
            assert isinstance(entry["id"], str)
            assert isinstance(entry["extensions"], list) and entry["extensions"]


class TestFfmpegCapabilitiesBridgeMethod:
    """``get_ffmpeg_capabilities`` 方法级封装。"""

    def test_returns_valid_json_object_shape(self) -> None:
        """返回 str 且可解析为含 version/formats/codecs 键的 JSON 对象。"""
        inst = RustThumbnailBridge()
        payload_text = inst.get_ffmpeg_capabilities()
        assert isinstance(payload_text, str)
        payload = json.loads(payload_text)
        assert isinstance(payload, dict)
        assert isinstance(payload["version"], str)
        assert isinstance(payload["formats"], list)
        assert isinstance(payload["codecs"], list)


# =============================================================================
# 降级路径：DLL 不可用 / 绑定缺失 → 安全降级值，不抛异常
# =============================================================================
DEGRADED_EXPECTATIONS = [
    ("get_error_log", "[]"),
    ("clear_error_log", False),
    ("get_supported_formats", "{}"),
    ("get_ffmpeg_capabilities", "{}"),
]


class TestDegradedPathsUnavailable:
    """``_available=False``（DLL 缺失场景模拟）时四方法安全降级。"""

    @pytest.mark.parametrize(("method_name", "expected"), DEGRADED_EXPECTATIONS)
    def test_unavailable_returns_safe_default(
        self, monkeypatch: Any, method_name: str, expected: Any
    ) -> None:
        """available 为 False 时返回降级值且不抛异常。"""
        inst = RustThumbnailBridge()
        monkeypatch.setattr(inst, "_available", False)  # noqa: SLF001
        result = getattr(inst, method_name)()
        assert result == expected
        assert isinstance(result, type(expected))


class TestDegradedPathsMissingBinding:
    """DLL 可用但 ``_supports_*`` 绑定缺失时四方法安全降级。"""

    @pytest.mark.parametrize(
        ("method_name", "expected", "flag_name"),
        [
            ("get_error_log", "[]", "_supports_errorlog"),
            ("clear_error_log", False, "_supports_errorlog"),
            ("get_supported_formats", "{}", "_supports_formats"),
            ("get_ffmpeg_capabilities", "{}", "_supports_caps"),
        ],
    )
    def test_missing_binding_returns_safe_default(
        self, monkeypatch: Any, method_name: str, expected: Any, flag_name: str
    ) -> None:
        """对应能力标记为 False 时返回降级值且不触碰 DLL。"""
        inst = RustThumbnailBridge()
        assert inst.available is True
        monkeypatch.setattr(inst, flag_name, False)  # noqa: SLF001
        result = getattr(inst, method_name)()
        assert result == expected
