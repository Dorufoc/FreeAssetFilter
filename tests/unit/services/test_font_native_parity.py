# -*- coding: utf-8 -*-
"""字体 native/fontTools 对拍（faf-core-rust-migration todo-26）。

覆盖 ``freeassetfilter.services.file_info_service`` 的字体 native 接线
（``_get_font_native`` path+mtime 缓存 / ``_font_name_rows`` /
``_font_detail_rows``）与 ``faf_core_bridge.parse_font``：

* **逐字段对拍**（TTF/OTF）：native 的 ``format/glyph_count/ascent/descent/
  line_gap/name1..6`` 与 fontTools ``font["hhea"]`` / ``maxp.numGlyphs`` /
  name 表原值一致（name 解码链镜像 oracle）；
* **accepted-diffs ≤2 机制**：全语料（ttf/otf/woff/woff2）汇总字段差异，
  允许 ≤2 项（记录原因）；
* **回退路径**：WOFF/WOFF2（todo 1 裁决）native 返回 ``None``，服务层回退
  fontTools 且产出与 oracle 一致；损坏字体 → 占位符不崩；
* **缓存**：light/detail 共享 path+mtime 缓存 → 单次 native 调用；
  mtime 变化重新解析；
* **DLL 缺失**：桥 ``parse_font`` 返回 ``None`` 不抛异常，服务层走
  fontTools。

验证命令（仓库根目录，offscreen 无关）：
    python -m pytest tests/unit/services/test_font_native_parity.py -v
"""

# targets: freeassetfilter.services.file_info_service / faf_core_bridge

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from freeassetfilter.services import file_info_service as fis

pytestmark = pytest.mark.unit

_FONT_DIR = (
    Path(__file__).resolve().parents[2]
    / "support"
    / "faf_core_fixtures"
    / "font_samples"
)

_FONT_FIELDS = (
    "format",
    "glyph_count",
    "ascent",
    "descent",
    "line_gap",
    "name1",
    "name2",
    "name3",
    "name4",
    "name5",
    "name6",
)


@pytest.fixture(autouse=True)
def _clear_font_native_cache() -> None:
    """清空模块级 path+mtime 缓存，避免跨测试串扰。"""
    fis._FONT_NATIVE_CACHE.clear()  # noqa: SLF001
    yield
    fis._FONT_NATIVE_CACHE.clear()  # noqa: SLF001


def _fonttools_oracle(path: str) -> Dict[str, Any]:
    """fontTools 独立 oracle：raw hhea / maxp numGlyphs / name1-6。

    name 提取镜像 ``_font_name_rows`` 的解码链（UTF-8 → latin-1）+ 首记录
    优先 + 空值跳过 + seen 去重。
    """
    from fontTools.ttLib import TTFont

    with TTFont(path, lazy=True) as font:
        result: Dict[str, Any] = {
            "format": "OpenType/CFF" if "CFF " in font else "TrueType",
            "glyph_count": font["maxp"].numGlyphs,
            "ascent": font["hhea"].ascent,
            "descent": font["hhea"].descent,
            "line_gap": font["hhea"].lineGap,
        }
        name_table = font["name"]
        seen_values: set = set()
        for name_id in range(1, 7):
            picked: Optional[str] = None
            for record in name_table.names:
                if record.nameID != name_id:
                    continue
                try:
                    value = record.string.decode("utf-8")
                except UnicodeDecodeError:
                    try:
                        value = record.string.decode("latin-1")
                    except (UnicodeDecodeError, AttributeError):
                        break
                value = value.strip()
                if not value:
                    continue
                if value in seen_values:
                    break
                seen_values.add(value)
                picked = value
                break
            result[f"name{name_id}"] = picked
    return result


def _collect_diffs(native: Dict[str, Any], oracle: Dict[str, Any], tag: str) -> List[str]:
    """逐字段比较 native vs oracle，返回差异清单（空 = 全一致）。"""
    diffs: List[str] = []
    for key in _FONT_FIELDS:
        n = native.get(key)
        o = oracle.get(key)
        if n != o:
            diffs.append(f"{tag} 字段 {key}: native={n!r} oracle={o!r}")
    return diffs


def _expected_name_rows(oracle: Dict[str, Any]) -> Dict[str, str]:
    """由 oracle 推导 ``_font_name_rows`` 期望输出。"""
    rows: Dict[str, str] = {}
    for name_id, label in fis._FONT_NAME_ROWS:  # noqa: SLF001
        value = oracle.get(f"name{name_id}")
        if value:
            rows[label] = value
    return rows


def _expected_detail_rows(oracle: Dict[str, Any]) -> Dict[str, str]:
    """由 oracle 推导 ``_font_detail_rows`` 期望输出。"""
    return {
        "字体格式": oracle["format"],
        "字形数": str(oracle["glyph_count"]),
        "上升": str(oracle["ascent"]),
        "下降": str(oracle["descent"]),
        "行间距": str(oracle["line_gap"]),
    }


# =============================================================================
# native 逐字段对拍（TTF/OTF）
# =============================================================================
class TestNativeFontParity:
    """native 字段与 fontTools 原值逐字段一致。"""

    @pytest.mark.parametrize("ext", ["ttf", "otf"])
    def test_native_fields_match_fonttools(
        self, faf_core_available: bool, ext: str
    ) -> None:
        if not faf_core_available:
            pytest.skip("faf_core.dll 不可用，跳过 native 对拍")
        if importlib.util.find_spec("fontTools") is None:
            pytest.skip("fontTools 未安装")
        path = str(_FONT_DIR / f"sample_regular.{ext}")
        native = fis._get_font_native(path)
        assert native is not None, f"{ext} 应走 native 解析"
        oracle = _fonttools_oracle(path)
        diffs = _collect_diffs(native, oracle, ext)
        assert diffs == [], f"{ext} native/fontTools 不一致: {diffs}"

    @pytest.mark.parametrize("ext", ["ttf", "otf"])
    def test_service_rows_match_oracle(
        self, faf_core_available: bool, ext: str
    ) -> None:
        """服务层 light/detail 行与 fontTools oracle 推导一致。"""
        if not faf_core_available:
            pytest.skip("faf_core.dll 不可用，跳过 native 对拍")
        if importlib.util.find_spec("fontTools") is None:
            pytest.skip("fontTools 未安装")
        path = str(_FONT_DIR / f"sample_regular.{ext}")
        oracle = _fonttools_oracle(path)
        assert dict(fis._font_name_rows(path)) == _expected_name_rows(oracle)
        assert dict(fis._font_detail_rows(path)) == _expected_detail_rows(oracle)

    def test_accepted_diffs_within_limit(self, faf_core_available: bool) -> None:
        """全语料字段差异汇总 ≤2（accepted-diffs 机制镜像编码 todo-25）。

        实测 ttf/otf 零差异（todo-22 探针已核）；WOFF/WOFF2 走 fontTools
        回退故不产生 native 差异。保留阈值护栏防止未来夹具/原生回归静默。
        """
        if not faf_core_available:
            pytest.skip("faf_core.dll 不可用，跳过 native 对拍")
        if importlib.util.find_spec("fontTools") is None:
            pytest.skip("fontTools 未安装")
        all_diffs: List[str] = []
        for ext in ("ttf", "otf", "woff", "woff2"):
            path = str(_FONT_DIR / f"sample_regular.{ext}")
            native = fis._get_font_native(path)
            oracle = _fonttools_oracle(path)
            # 服务层行必须与 oracle 一致（native 或 fontTools 回退皆然）
            assert dict(fis._font_name_rows(path)) == _expected_name_rows(oracle)
            assert dict(fis._font_detail_rows(path)) == _expected_detail_rows(oracle)
            if native is not None:
                all_diffs.extend(_collect_diffs(native, oracle, ext))
        assert len(all_diffs) <= 2, f"accepted-diffs 超限: {all_diffs}"


# =============================================================================
# 回退路径（WOFF/WOFF2 / 损坏 / DLL 缺失）
# =============================================================================
class TestFontNativeFallback:
    """native 不可用时回退 fontTools 现状，损坏不崩。"""

    @pytest.mark.parametrize("ext", ["woff", "woff2"])
    def test_woff_woff2_native_none_fonttools_rows(
        self, faf_core_available: bool, ext: str
    ) -> None:
        """WOFF/WOFF2（todo 1 裁决）native 返回 None，服务层回退 fontTools。"""
        if not faf_core_available:
            pytest.skip("faf_core.dll 不可用，跳过 native 对拍")
        if importlib.util.find_spec("fontTools") is None:
            pytest.skip("fontTools 未安装")
        path = str(_FONT_DIR / f"sample_regular.{ext}")
        assert fis._get_font_native(path) is None
        oracle = _fonttools_oracle(path)
        assert dict(fis._font_name_rows(path)) == _expected_name_rows(oracle)
        assert dict(fis._font_detail_rows(path)) == _expected_detail_rows(oracle)

    def test_corrupt_returns_placeholders(self, faf_core_available: bool) -> None:
        """损坏字体 → native None + 服务层占位符（绝不抛 TTLibError）。"""
        if not faf_core_available:
            pytest.skip("faf_core.dll 不可用，跳过 native 对拍")
        path = str(_FONT_DIR / "sample_corrupt.ttf")
        assert fis._get_font_native(path) is None
        assert fis._font_name_rows(path) == []
        assert fis._font_detail_rows(path) == []

    def test_missing_file_returns_placeholders(self) -> None:
        """缺失文件 → 占位符（不调 native 不抛）。"""
        path = "C:/no/such/font.ttf"
        assert fis._get_font_native(path) is None
        assert fis._font_name_rows(path) == []
        assert fis._font_detail_rows(path) == []

    def test_bridge_parse_font_missing_dll_returns_none(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DLL 缺失时桥 ``parse_font`` 返回 None；非 str 入参 → None。"""
        from freeassetfilter.core.native.bridges.faf_core_bridge import FafCoreBridge

        missing = tmp_path / "missing.dll"
        monkeypatch.setattr(
            FafCoreBridge, "_candidate_paths", lambda self: [Path(missing)]
        )
        inst = FafCoreBridge()
        assert inst.parse_font("anything.ttf") is None
        assert inst.parse_font(123) is None

    def test_native_unavailable_service_falls_back_to_fonttools(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """get_faf_core_bridge 返回 None（DLL 缺失语义）→ fontTools 仍产出。"""
        if importlib.util.find_spec("fontTools") is None:
            pytest.skip("fontTools 未安装")
        import freeassetfilter.core.native.bridges.faf_core_bridge as bridge_mod

        monkeypatch.setattr(bridge_mod, "get_faf_core_bridge", lambda: None)
        path = str(_FONT_DIR / "sample_regular.ttf")
        oracle = _fonttools_oracle(path)
        assert dict(fis._font_name_rows(path)) == _expected_name_rows(oracle)
        assert dict(fis._font_detail_rows(path)) == _expected_detail_rows(oracle)


# =============================================================================
# 缓存（path+mtime 单次解析）
# =============================================================================
class TestFontNativeCache:
    """light/detail 共享单次 native 调用；mtime 变化重新解析。"""

    def _install_counting_bridge(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> Dict[str, int]:
        import freeassetfilter.core.native.bridges.faf_core_bridge as bridge_mod

        bridge = bridge_mod.get_faf_core_bridge()
        calls: Dict[str, int] = {"n": 0}
        real_parse = bridge.parse_font

        def counting_parse(p: str) -> Any:
            calls["n"] += 1
            return real_parse(p)

        monkeypatch.setattr(bridge, "parse_font", counting_parse)
        monkeypatch.setattr(bridge_mod, "get_faf_core_bridge", lambda: bridge)
        return calls

    def test_light_detail_share_single_native_call(
        self, faf_core_available: bool, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """light + detail + 重复调用合计仅 1 次 native 解析。"""
        if not faf_core_available:
            pytest.skip("faf_core.dll 不可用，跳过 native 对拍")
        path = str(_FONT_DIR / "sample_regular.ttf")
        calls = self._install_counting_bridge(monkeypatch)
        fis._font_name_rows(path)
        fis._font_detail_rows(path)
        fis._font_name_rows(path)
        assert calls["n"] == 1, "light/detail 应共享单次 native 调用"

    def test_mtime_change_invalidates_cache(
        self,
        faf_core_available: bool,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Any,
    ) -> None:
        """mtime 变化 → 缓存失效重新解析（path+mtime 键语义）。"""
        if not faf_core_available:
            pytest.skip("faf_core.dll 不可用，跳过 native 对拍")
        dst = tmp_path / "f.ttf"
        dst.write_bytes((_FONT_DIR / "sample_regular.ttf").read_bytes())
        path = str(dst)
        calls = self._install_counting_bridge(monkeypatch)
        assert fis._get_font_native(path) is not None
        assert calls["n"] == 1
        assert fis._get_font_native(path) is not None
        assert calls["n"] == 1  # 缓存命中
        st = os.stat(path)
        os.utime(path, (st.st_atime, st.st_mtime + 5))
        assert fis._get_font_native(path) is not None
        assert calls["n"] == 2  # mtime 变化 → 重新解析
