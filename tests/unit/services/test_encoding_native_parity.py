# -*- coding: utf-8 -*-
"""编码探测 native/chardet 对拍（faf-core-rust-migration todo-25）。

覆盖 ``freeassetfilter.services.file_info_service`` 的编码 native 接线
（``_detect_encoding_native`` path+mtime+窗口缓存 / ``_text_light_rows``
1KB 窗口 / ``_text_detail_rows`` 4KB 窗口 / ``_decode_encoding_chain``
回退链）与 ``faf_core_bridge.detect_encoding``：

* **全文件对拍（验收门槛）**：语料 20 文件（CJK ≥8KB：gbk/big5/shift-jis）
  native 探测编码 vs chardet 探测编码各自解码**全文件**字节，经同一
  ``_decode_encoding_chain``（``errors="replace"``）逐字节一致；
  **accepted-diffs ≤2 项**（实测 1 项：latin1_01——native 置信度 <0.5
  返回 ``{}`` → ``utf-8 → latin-1`` 链，chardet 判 Windows-1252，0x80-0x9F
  字节映射差异）；
* **UTF-8 BOM 归一**：native 判 ``utf-8``（chardetng 归一化 BOM）经
  ``_normalize_utf8_bom`` 归一为 ``utf-8-sig``，与 chardet 的 ``UTF-8-SIG``
  路径解码文本逐字节一致（BOM 不残留 ``\\ufeff``）；
* **1KB/4KB 窗口 utf-8 补全**：``_utf8_complete_window`` 将字节窗口补全到
  UTF-8 字符边界——utf-8 中文文件的 1KB/4KB 前缀不再因尾字符截断跌落
  windows-1252；
* **缓存**：同一窗口重复调用命中 path+mtime 缓存（单次 native）；不同窗口
  独立缓存键（窗口语义 1KB/4KB/全文件保持）；mtime 变化重新探测；
* **回退**：native 置信度 <0.5（空 JSON ``{}``）/ DLL 缺失 / 空样本 →
  ``None``，light/detail 回退 chardet 现状，预览器走 ``utf-8 → latin-1`` 链；
* **桥降级**：DLL 缺失 / 非 bytes / 空样本 → ``detect_encoding`` 返回
  ``None`` 不抛异常；合法样本返回 ``{"encoding","confidence"}``。

验证命令（仓库根目录，offscreen 无关）：
    python -m pytest tests/unit/services/test_encoding_native_parity.py -v
"""

# targets: freeassetfilter.services.file_info_service / faf_core_bridge

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

import chardet

from freeassetfilter.services import file_info_service as fis

pytestmark = pytest.mark.unit

_ENC_DIR = (
    Path(__file__).resolve().parents[2]
    / "support"
    / "faf_core_fixtures"
    / "encoding_samples"
)

#: 全部对拍语料（20 文件；CJK gbk/big5/shift-jis 样本均 ≥8KB）。
_CORPUS: List[str] = sorted(str(p) for p in _ENC_DIR.glob("*.txt"))

#: accepted-diffs：native 与 chardet 解码文本分歧（≤2 项，附原因）。
#: latin1_01 —— native 置信度 <0.5 → ``{}`` → latin-1 链；chardet 判
#: Windows-1252。两者对 0x80-0x9F 字节映射不同（latin-1 为 C1 控制符，
#: Windows-1252 为可打印字符），解码文本逐字节不一致。计划 C6 明文：低置信
#: 走 ``utf-8 → latin-1`` 链（Must-NOT 不变），故该项记录而非修复。
_ACCEPTED_DIFFS: Dict[str, str] = {
    "latin1_01.txt": "native 低置信 {} → latin-1 链 vs chardet Windows-1252；0x80-0x9F 映射差异",
}


@pytest.fixture(autouse=True)
def _clear_enc_native_cache() -> None:
    """清空模块级 path+mtime+窗口缓存，避免跨测试串扰。"""
    fis._ENC_NATIVE_CACHE.clear()  # noqa: SLF001
    yield
    fis._ENC_NATIVE_CACHE.clear()  # noqa: SLF001


def _decode_text(raw: bytes, encoding: Optional[str]) -> str:
    """按统一回退链（errors='replace'）解码——与预览器 `_decode_bytes` 同语义。"""
    text, _ = fis._decode_encoding_chain(raw, encoding, errors="replace")
    return text


def _native_encoding(path: str, window: Optional[int] = None) -> Optional[str]:
    """native 探测结果编码（window=None → 全文件）。"""
    raw = Path(path).read_bytes()
    result = fis._detect_encoding_native(raw, path, window=window)
    if result:
        return result.get("encoding")
    return None


# =============================================================================
# 全文件逐字节对拍（验收门槛：accepted-diffs ≤2）
# =============================================================================
class TestNativeEncodingParity:
    """native 解码文本与 chardet 路径逐字节一致（20 语料，CJK ≥8KB）。"""

    @pytest.mark.parametrize("path", _CORPUS)
    def test_decode_text_byte_identical(self, faf_core_available: bool, path: str) -> None:
        """单文件：native 全文件探测 vs chardet 全文件探测 → 解码文本逐字节一致。

        分歧文件仅在 accepted-diffs 清单内放行（≤2 项，附原因）。
        """
        if not faf_core_available:
            pytest.skip("faf_core.dll 不可用，跳过 native 对拍")
        raw = Path(path).read_bytes()
        native_enc = _native_encoding(path, window=None)
        chardet_result = chardet.detect(raw) or {}
        chardet_enc = chardet_result.get("encoding")
        native_text = _decode_text(raw, native_enc)
        chardet_text = _decode_text(raw, chardet_enc)
        if native_text != chardet_text:
            name = Path(path).name
            assert name in _ACCEPTED_DIFFS, (
                f"{name} 分歧未列入 accepted-diffs: "
                f"native={native_enc!r} chardet={chardet_enc!r}"
            )
            # 记录原因（对拍测试保留 accepted-diffs 清单可追溯性）
            assert _ACCEPTED_DIFFS[name], "accepted-diffs 原因不能为空"

    def test_all_corpus_diffs_within_limit(self, faf_core_available: bool) -> None:
        """全语料汇总：未列入 accepted-diffs 的分歧必须为零（≤2 项门槛护栏）。"""
        if not faf_core_available:
            pytest.skip("faf_core.dll 不可用，跳过 native 对拍")
        diffs: List[str] = []
        for path in _CORPUS:
            raw = Path(path).read_bytes()
            native_enc = _native_encoding(path, window=None)
            chardet_result = chardet.detect(raw) or {}
            chardet_enc = chardet_result.get("encoding")
            if _decode_text(raw, native_enc) != _decode_text(raw, chardet_enc):
                diffs.append(Path(path).name)
        unexpected = [d for d in diffs if d not in _ACCEPTED_DIFFS]
        assert unexpected == [], f"accepted-diffs 外零分歧，实测: {unexpected}"

    def test_cjk_full_file_detects_correct_encoding(
        self, faf_core_available: bool,
    ) -> None:
        """CJK ≥8KB 全文件窗口 native 探测正确（gbk/big5/shift_jis/utf-8）。"""
        if not faf_core_available:
            pytest.skip("faf_core.dll 不可用，跳过 native 对拍")
        cases = {
            "gbk_01.txt": "gbk", "gbk_02.txt": "gbk",
            "big5_01.txt": "big5",
            "shiftjis_01.txt": "shift_jis",
            "utf8_01.txt": "utf-8", "utf8bom_01.txt": "utf-8",
        }
        for name, expected in cases.items():
            enc = _native_encoding(str(_ENC_DIR / name), window=None)
            assert enc == expected, f"{name} 全文件应为 {expected}，实测 {enc}"

    def test_utf8_bom_stripped_on_both_paths(
        self, faf_core_available: bool,
    ) -> None:
        """UTF-8 BOM 文件：native(utf-8→utf-8-sig) 与 chardet(UTF-8-SIG) 均剥离 BOM。"""
        if not faf_core_available:
            pytest.skip("faf_core.dll 不可用，跳过 native 对拍")
        for name in ("utf8bom_01.txt", "utf8bom_02.txt"):
            path = str(_ENC_DIR / name)
            raw = Path(path).read_bytes()
            native_text = _decode_text(raw, _native_encoding(path, window=None))
            chardet_text = _decode_text(raw, (chardet.detect(raw) or {}).get("encoding"))
            assert native_text == chardet_text
            assert not native_text.startswith("\ufeff"), "BOM 不应残留"


# =============================================================================
# 采样窗口补全（_utf8_complete_window）
# =============================================================================
class TestUtf8WindowCompletion:
    """1KB/4KB 固定字节窗口补全到 UTF-8 字符边界，utf-8 候选不因尾截断失效。"""

    def test_utf8_cjk_1kb_window_stays_utf8(
        self, faf_core_available: bool,
    ) -> None:
        """utf-8 中文文件 1KB 前缀补全后探测仍为 utf-8（未补全会跌落 windows-1252）。"""
        if not faf_core_available:
            pytest.skip("faf_core.dll 不可用，跳过 native 对拍")
        path = str(_ENC_DIR / "utf8_01.txt")
        raw = Path(path).read_bytes()
        raw_window = raw[: fis._TEXT_LIGHT_WINDOW]  # noqa: SLF001
        completed = fis._utf8_complete_window(raw, fis._TEXT_LIGHT_WINDOW)  # noqa: SLF001
        # 原始字节窗口可能落在多字节字符中间 → 非法 utf-8；补全后必须合法
        try:
            raw_window.decode("utf-8")
            truncated_valid = True
        except UnicodeDecodeError:
            truncated_valid = False
        completed.decode("utf-8")  # 不抛即合法
        from freeassetfilter.core.native.bridges.faf_core_bridge import get_faf_core_bridge

        bridge = get_faf_core_bridge()
        enc = (bridge.detect_encoding(completed) or {}).get("encoding")
        assert enc == "utf-8", f"1KB 补全窗口应为 utf-8，实测 {enc}"
        # 说明性断言：若未补全的窗口也恰好合法则跳过强断言（内容差异）
        if not truncated_valid:
            raw_enc = (bridge.detect_encoding(raw_window) or {}).get("encoding")
            assert raw_enc != "utf-8", "截断窗口不应为 utf-8（否则补全逻辑无意义）"

    def test_completion_is_noop_for_ascii_and_small(self) -> None:
        """ASCII/短内容：补全窗口等于原窗口（无额外字节）。"""
        assert fis._utf8_complete_window(b"hello world", 1024) == b"hello world"
        assert fis._utf8_complete_window(b"abc", 4) == b"abc"

    def test_completion_budget_respected(self) -> None:
        """预算上限：连续跨窗多字节字符补全不超过预算且不越界。"""
        # 1023 字节 ASCII + 一个 4 字节 utf-8 字符跨出窗口（预算 8 足够）
        raw = b"a" * 1023 + "\U0001F600".encode("utf-8") + b"tail"
        out = fis._utf8_complete_window(raw, 1024, budget=8)
        out.decode("utf-8")  # 合法 utf-8 边界
        assert 1024 <= len(out) <= 1024 + 8
        assert out == raw[: len(out)]


# =============================================================================
# 缓存（path+mtime+窗口）
# =============================================================================
class TestEncodingNativeCache:
    """同一窗口重复命中单次 native 调用；不同窗口独立键；mtime 变化重探测。"""

    def _install_counting_bridge(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> Dict[str, int]:
        import freeassetfilter.core.native.bridges.faf_core_bridge as bridge_mod

        bridge = bridge_mod.get_faf_core_bridge()
        calls: Dict[str, int] = {"n": 0}
        real_detect = bridge.detect_encoding

        def counting_detect(data: bytes) -> Any:
            calls["n"] += 1
            return real_detect(data)

        monkeypatch.setattr(bridge, "detect_encoding", counting_detect)
        monkeypatch.setattr(bridge_mod, "get_faf_core_bridge", lambda: bridge)
        return calls

    def test_same_window_reuses_single_native_call(
        self, faf_core_available: bool, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """同一窗口重复调用合计仅 1 次 native；不同窗口独立探测。"""
        if not faf_core_available:
            pytest.skip("faf_core.dll 不可用，跳过 native 对拍")
        path = str(_ENC_DIR / "utf8_01.txt")
        calls = self._install_counting_bridge(monkeypatch)
        fis._text_light_rows(path)  # 1KB 窗口
        fis._text_light_rows(path)  # 缓存命中
        fis._text_detail_rows(path)  # 4KB 窗口（独立键）
        raw = Path(path).read_bytes()
        fis._detect_encoding_native(raw, path, window=None)  # 全文件窗口
        fis._detect_encoding_native(raw, path, window=None)  # 缓存命中
        assert calls["n"] == 3, "1KB/4KB/全文件 三个窗口各 1 次 native 调用"

    def test_mtime_change_invalidates_cache(
        self, faf_core_available: bool, monkeypatch: pytest.MonkeyPatch,
        tmp_path: Any,
    ) -> None:
        """mtime 变化 → 缓存失效重新探测（path+mtime 键语义）。"""
        if not faf_core_available:
            pytest.skip("faf_core.dll 不可用，跳过 native 对拍")
        dst = tmp_path / "e.txt"
        dst.write_bytes((_ENC_DIR / "utf8_01.txt").read_bytes())
        path = str(dst)
        calls = self._install_counting_bridge(monkeypatch)
        raw = dst.read_bytes()
        assert fis._detect_encoding_native(raw, path, window=None) is not None
        assert fis._detect_encoding_native(raw, path, window=None) is not None
        assert calls["n"] == 1
        st = os.stat(path)
        os.utime(path, (st.st_atime, st.st_mtime + 5))
        assert fis._detect_encoding_native(raw, path, window=None) is not None
        assert calls["n"] == 2, "mtime 变化 → 重新探测"


# =============================================================================
# 回退路径（native {} / None / DLL 缺失）
# =============================================================================
class TestEncodingNativeFallback:
    """native 低置信/不可用时回退 chardet 现状，损坏输入不崩。"""

    def test_low_confidence_returns_empty_json(self) -> None:
        """latin-1 样本（native 置信度 <0.5 → {}）→ `_detect_encoding_native` None。"""
        from freeassetfilter.core.native.bridges.faf_core_bridge import get_faf_core_bridge

        bridge = get_faf_core_bridge()
        if not bridge.available or not bridge._supports_detect_encoding:  # noqa: SLF001
            pytest.skip("faf_core.dll 不含 detect 导出，跳过可用路径测试")
        raw = (_ENC_DIR / "latin1_01.txt").read_bytes()
        assert bridge.detect_encoding(raw) == {}
        path = str(_ENC_DIR / "latin1_01.txt")
        assert fis._detect_encoding_native(raw, path, window=None) is None

    def test_light_rows_fall_back_to_chardet_for_latin1(self) -> None:
        """native `{}` → light 行回退 chardet（Windows-1252 标签不崩）。"""
        path = str(_ENC_DIR / "latin1_01.txt")
        rows = dict(fis._text_light_rows(path))
        assert rows["编码格式"] == "Windows-1252"

    def test_short_cjk_sample_low_confidence(self) -> None:
        """超短 CJK 样本（n < 阈值）→ {} → None（走 utf-8 → latin-1 链）。"""
        from freeassetfilter.core.native.bridges.faf_core_bridge import get_faf_core_bridge

        bridge = get_faf_core_bridge()
        if not bridge.available or not bridge._supports_detect_encoding:  # noqa: SLF001
            pytest.skip("faf_core.dll 不含 detect 导出，跳过可用路径测试")
        assert bridge.detect_encoding("中".encode("utf-8")) == {}

    def test_bridge_detect_encoding_missing_dll_returns_none(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """DLL 缺失时桥 `detect_encoding` 返回 None；非 bytes/空样本 → None。"""
        from freeassetfilter.core.native.bridges.faf_core_bridge import FafCoreBridge

        missing = tmp_path / "missing.dll"
        monkeypatch.setattr(
            FafCoreBridge, "_candidate_paths", lambda self: [Path(missing)]
        )
        inst = FafCoreBridge()
        assert inst.available is False
        assert inst.detect_encoding(b"hello world") is None

    def test_bridge_detect_encoding_malformed_input(self) -> None:
        """非 bytes / 空样本 → None（不抛异常，malformed 输入防御）。"""
        from freeassetfilter.core.native.bridges.faf_core_bridge import get_faf_core_bridge

        bridge = get_faf_core_bridge()
        if not bridge.available or not bridge._supports_detect_encoding:  # noqa: SLF001
            pytest.skip("faf_core.dll 不含 detect 导出，跳过可用路径测试")
        assert bridge.detect_encoding(b"") is None
        assert bridge.detect_encoding("not-bytes") is None
        assert bridge.detect_encoding(123) is None

    def test_native_unavailable_service_still_works(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """get_faf_core_bridge 返回 None（DLL 缺失语义）→ chardet 仍产出。"""
        import freeassetfilter.core.native.bridges.faf_core_bridge as bridge_mod

        monkeypatch.setattr(bridge_mod, "get_faf_core_bridge", lambda: None)
        path = str(_ENC_DIR / "gbk_02.txt")
        rows = dict(fis._text_light_rows(path))
        assert rows["编码格式"] not in (fis.UNAVAILABLE, None)
        # detail 计数仍正常（chardet 回退）
        values = dict(fis.collect_detail_data(path)["rows"])
        assert "字符数" in values
