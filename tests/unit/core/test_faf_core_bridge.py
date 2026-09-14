# -*- coding: utf-8 -*-
"""faf_core 桥单测（faf-core-rust-migration todo-3）。

覆盖 ``freeassetfilter.core.native.bridges.faf_core_bridge``：

* **可用路径**（真实 DLL 存在时）：``FafCoreBridge`` 直接构造可用、
  ``_supports_version`` 能力标记、``version()`` 返回合法
  ``{"version": ...}``、连续两次调用一致（``faf_free_message`` 不泄漏）；
* **降级路径**（DLL 缺失 / mock 探测 False）：``available is False``、
  ``version()`` 返回 ``None`` 不抛异常、``free_message(None)`` 不抛异常。

本文件仅依赖 ctypes 标准库；真实库缺失时可用路径测试被跳过，
降级路径测试恒执行。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from freeassetfilter.core.native.bridges.faf_core_bridge import (
    FafCoreBridge,
)

pytestmark = pytest.mark.unit

bridge = pytest.importorskip(
    "freeassetfilter.core.native.bridges.faf_core_bridge"
)


# =============================================================================
# 可用路径（需要真实 faf_core.dll）
# =============================================================================
class TestBridgeAvailability:
    """``FafCoreBridge`` 的可用性与版本查询。"""

    def test_available_flag(self) -> None:
        """DLL 存在时服务可用性标记为真，否则跳过。"""
        inst = FafCoreBridge()
        if not inst.available:
            pytest.skip("faf_core.dll 不可用，跳过可用路径测试")
        assert inst.available is True

    def test_direct_construction(self) -> None:
        """模块不做单例——每次构造独立实例（无 ``get_instance``）。"""
        a = FafCoreBridge()
        b = FafCoreBridge()
        assert a is not b

    def test_version_capability_flag(self) -> None:
        """version 能力标记为 bool（私有属性名带下划线前缀）。"""
        inst = FafCoreBridge()
        assert isinstance(inst._supports_version, bool)  # noqa: SLF001

    def test_version_valid(self) -> None:
        """可用时 ``version()`` 返回含非空 ``version`` 字段的字典。"""
        inst = FafCoreBridge()
        if not inst.available:
            pytest.skip("faf_core.dll 不可用，跳过可用路径测试")
        result = inst.version()
        assert isinstance(result, dict)
        assert result.get("version")
        assert isinstance(result["version"], str)

    def test_version_consistent_across_calls(self) -> None:
        """连续两次调用返回一致值（``faf_free_message`` 不泄漏/不野指针）。"""
        inst = FafCoreBridge()
        if not inst.available:
            pytest.skip("faf_core.dll 不可用，跳过可用路径测试")
        first = inst.version()
        second = inst.version()
        assert first == second
        assert first is not second


# =============================================================================
# 降级路径（DLL 缺失 / mock，不依赖真实 DLL）
# =============================================================================
class TestBridgeDegraded:
    """DLL 缺失时安全降级：返回默认值，不抛异常。"""

    def test_missing_dll_unavailable(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """候选路径全部不存在时 ``available is False``。"""
        missing = tmp_path / "missing.dll"
        monkeypatch.setattr(
            FafCoreBridge, "_candidate_paths", lambda self: [Path(missing)]
        )
        inst = FafCoreBridge()
        assert inst.available is False

    def test_missing_dll_version_returns_none(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DLL 缺失时 ``version()`` 返回 ``None`` 不抛异常。"""
        missing = tmp_path / "missing.dll"
        monkeypatch.setattr(
            FafCoreBridge, "_candidate_paths", lambda self: [Path(missing)]
        )
        inst = FafCoreBridge()
        assert inst.version() is None

    def test_free_message_null_safe(self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """降级实例上 ``free_message(None)`` 不抛异常。"""
        missing = tmp_path / "missing.dll"
        monkeypatch.setattr(
            FafCoreBridge, "_candidate_paths", lambda self: [Path(missing)]
        )
        inst = FafCoreBridge()
        inst.free_message(None)
        inst.free_message(0)


# =============================================================================
# 语法高亮能力（todo 13：faf_highlight_text 绑定与降级）
# =============================================================================
class TestBridgeHighlight:
    """``highlight_text`` 能力标记、可用路径与降级路径。"""

    def test_highlight_capability_flag(self) -> None:
        """``_supports_highlight`` 为 bool（能力探测属性）。"""
        assert isinstance(FafCoreBridge()._supports_highlight, bool)  # noqa: SLF001

    def test_highlight_returns_span_list(self) -> None:
        """可用时返回 ``[{start,len,token_type}]``，span 连续覆盖全文。"""
        inst = FafCoreBridge()
        if not inst.available or not inst._supports_highlight:  # noqa: SLF001
            pytest.skip("faf_core.dll 不含 highlight 导出，跳过可用路径测试")
        spans = inst.highlight_text("python", "def f(a):\n    return 42\n")
        assert isinstance(spans, list)
        assert spans, "Python 样本应至少一个 span"
        for span in spans:
            assert isinstance(span, dict)
            for key in ("start", "len", "token_type"):
                assert isinstance(span.get(key), int), f"span[{key}] 应为 int"
        # 字符偏移连续覆盖全文（∑len == 文本字符数）
        assert sum(s["len"] for s in spans) == len("def f(a):\n    return 42\n")
        cursor = 0
        for span in spans:
            assert span["start"] == cursor, "span 应连续覆盖"
            cursor += span["len"]

    def test_highlight_unknown_language_returns_empty(self) -> None:
        """未知语言 → 空列表（非 None；Python 保默认样式不触发回退）。"""
        inst = FafCoreBridge()
        if not inst.available or not inst._supports_highlight:  # noqa: SLF001
            pytest.skip("faf_core.dll 不含 highlight 导出，跳过可用路径测试")
        assert inst.highlight_text("not_a_real_language", "plain text") == []

    def test_highlight_unsupported_language_returns_none(self) -> None:
        """映射命中但 syntect 默认集缺失的语言 → None（触发 Python 回退）。"""
        inst = FafCoreBridge()
        if not inst.available or not inst._supports_highlight:  # noqa: SLF001
            pytest.skip("faf_core.dll 不含 highlight 导出，跳过可用路径测试")
        # PowerShell 在映射表但不在 syntect 默认集（todo 11 约定 -6 → null）
        assert inst.highlight_text("powershell", "$x = 1\n") is None

    def test_highlight_missing_dll_returns_none(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DLL 缺失时 ``highlight_text`` 返回 ``None`` 不抛异常。"""
        missing = tmp_path / "missing.dll"
        monkeypatch.setattr(
            FafCoreBridge, "_candidate_paths", lambda self: [Path(missing)]
        )
        inst = FafCoreBridge()
        assert inst.highlight_text("python", "x = 1") is None

    def test_highlight_non_string_returns_none(self) -> None:
        """语言/文本非 str → None（malformed 输入防御，不抛）。"""
        inst = FafCoreBridge()
        if not inst.available or not inst._supports_highlight:  # noqa: SLF001
            pytest.skip("faf_core.dll 不含 highlight 导出，跳过可用路径测试")
        assert inst.highlight_text("python", 123) is None
        assert inst.highlight_text(42, "x = 1") is None


# =============================================================================
# 批量复制能力（todo 27：faf_copy_files / copy_files，todo 29 接线）
# =============================================================================
class TestBridgeCopy:
    """``copy_files`` 能力标记、批量复制可用路径与降级路径。"""

    def test_copy_capability_flag(self) -> None:
        """``_supports_copy`` 为 bool（能力探测属性）。"""
        assert isinstance(FafCoreBridge()._supports_copy, bool)  # noqa: SLF001

    def test_copy_files_roundtrip_file_and_dir(
        self, tmp_path: Any
    ) -> None:
        """文件与目录批量复制 → copied 明细 + 目标文件真实存在且 mtime 保留。"""
        inst = FafCoreBridge()
        if not inst.available or not inst._supports_copy:  # noqa: SLF001
            pytest.skip("faf_core.dll 不含 copy 导出，跳过可用路径测试")
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        f = src_dir / "a.txt"
        f.write_bytes(b"hello world")
        tree = src_dir / "tree"
        (tree / "sub").mkdir(parents=True)
        (tree / "sub" / "leaf.txt").write_bytes(b"leaf")
        dest = tmp_path / "dest"
        dest.mkdir()

        # 先给源文件设已知 mtime，验证 copystat 保留。
        import os
        import time as _time

        known = 1_700_000_000
        os.utime(f, (known, known))
        result = inst.copy_files(
            [str(f), str(tree)], str(dest)
        )
        assert isinstance(result, dict)
        copied = result.get("copied")
        assert isinstance(copied, list)
        assert len(copied) == 2, f"copied 应含 2 项: {copied}"
        assert result.get("failed") == []
        dst_file = dest / "a.txt"
        assert dst_file.read_bytes() == b"hello world"
        assert int(dst_file.stat().st_mtime) == known, "目标 mtime 应与源一致"
        assert (dest / "tree" / "sub" / "leaf.txt").read_bytes() == b"leaf"

    def test_copy_files_missing_source_is_per_file_failure(
        self, tmp_path: Any
    ) -> None:
        """缺失源记入 failed，合法源继续成功（不中断整批）。"""
        inst = FafCoreBridge()
        if not inst.available or not inst._supports_copy:  # noqa: SLF001
            pytest.skip("faf_core.dll 不含 copy 导出，跳过可用路径测试")
        src = tmp_path / "ok.txt"
        src.write_bytes(b"data")
        missing = tmp_path / "missing.txt"
        dest = tmp_path / "dest"
        dest.mkdir()
        result = inst.copy_files([str(src), str(missing)], str(dest))
        assert result is not None
        assert len(result.get("copied", [])) == 1
        assert len(result.get("failed", [])) == 1
        assert result["failed"][0]["src"] == str(missing)
        assert result["failed"][0]["error"]

    def test_copy_files_malformed_input_returns_none(self) -> None:
        """非 list 源/非 str 目标 → None（不抛异常）。"""
        inst = FafCoreBridge()
        assert inst.copy_files("not-a-list", r"C:\tmp") is None
        assert inst.copy_files(["a"], 123) is None

    def test_copy_files_missing_dll_returns_none(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DLL 缺失时 ``copy_files`` 返回 ``None``（调用方回退 Python）。"""
        missing = tmp_path / "missing.dll"
        monkeypatch.setattr(
            FafCoreBridge, "_candidate_paths", lambda self: [Path(missing)]
        )
        inst = FafCoreBridge()
        assert inst.available is False
        assert inst.copy_files(["a.txt"], str(tmp_path)) is None


# =============================================================================
# 目录大小聚合能力（todo 27：faf_sum_directory_sizes / sum_directory_sizes）
# =============================================================================
class TestBridgeSizesum:
    """``sum_directory_sizes`` 能力标记、可用路径与降级路径。"""

    def test_sizesum_capability_flag(self) -> None:
        """``_supports_sizesum`` 为 bool（能力探测属性）。"""
        assert isinstance(
            FafCoreBridge()._supports_sizesum, bool  # noqa: SLF001
        )

    def test_sizesum_roundtrip_nested(self, tmp_path: Any) -> None:
        """嵌套目录大小聚合 → 单遍求和（目录字节不计）。"""
        inst = FafCoreBridge()
        if not inst.available or not inst._supports_sizesum:  # noqa: SLF001
            pytest.skip("faf_core.dll 不含 sizesum 导出，跳过可用路径测试")
        d = tmp_path / "d"
        (d / "sub1" / "sub2").mkdir(parents=True)
        (d / "a.txt").write_bytes(bytes(100))
        (d / "sub1" / "b.txt").write_bytes(bytes(200))
        (d / "sub1" / "sub2" / "c.bin").write_bytes(bytes(300))
        result = inst.sum_directory_sizes([str(d)])
        assert result is not None
        results = result.get("results")
        assert isinstance(results, list) and len(results) == 1
        assert results[0]["path"] == str(d)
        assert results[0]["error"] is None
        assert results[0]["size"] == 600

    def test_sizesum_error_path_reported_per_entry(self, tmp_path: Any) -> None:
        """缺失/非目录路径 → error 字段落原因，不中断其它路径。"""
        inst = FafCoreBridge()
        if not inst.available or not inst._supports_sizesum:  # noqa: SLF001
            pytest.skip("faf_core.dll 不含 sizesum 导出，跳过可用路径测试")
        good = tmp_path / "good"
        good.mkdir()
        (good / "x.bin").write_bytes(bytes(7))
        missing = tmp_path / "ghost"
        result = inst.sum_directory_sizes([str(good), str(missing)])
        assert result is not None
        results = result.get("results")
        assert len(results) == 2
        assert results[0]["size"] == 7
        assert results[0]["error"] is None
        assert results[1]["size"] == 0
        assert isinstance(results[1]["error"], str)

    def test_sizesum_malformed_input_returns_none(self) -> None:
        """非 list 入参 → None（不抛异常）。"""
        inst = FafCoreBridge()
        assert inst.sum_directory_sizes("not-a-list") is None

    def test_sizesum_missing_dll_returns_none(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DLL 缺失时 ``sum_directory_sizes`` 返回 ``None``（回退 Python walk）。"""
        missing = tmp_path / "missing.dll"
        monkeypatch.setattr(
            FafCoreBridge, "_candidate_paths", lambda self: [Path(missing)]
        )
        inst = FafCoreBridge()
        assert inst.sum_directory_sizes([str(tmp_path)]) is None
