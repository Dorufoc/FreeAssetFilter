# -*- coding: utf-8 -*-
"""文件选择器 faf_core native 接线单元测试（.omo/plans/faf-core-rust-migration todo 9）。

验证 ``file_selector_layout.py`` 的 faf_core native 接线与 raw entries 缓存：

(a) 排序切换**不触发磁盘重扫**（mock ``_collect_directory_entries`` 计数为 0）
    + 内存重排结果与真实重扫一致（模型顺序断言）；
(b) 筛选应用/清除**不重扫**（计数不变）+ 结果与重扫一致；
(c) 桥不可用（monkeypatch ``get_faf_core_bridge`` 返回 available=False 或
    native 返回 None 的降级实例）→ ``_collect_directory_entries`` 回退
    Python 路径，行为不变；
(d) 桥可用时 native ``scan_directory`` 结果与 Python oracle
    ``_collect_directory_entries_python`` 对 `tests/support/faf_core_fixtures/
    dir_samples/` 逐字段一致（DLL 缺失时 skip）。

测试纪律（与 tests/unit/ui/layout/test_layouts.py 一致）：

* ``FileSelectorLayout`` 真实构造（offscreen，不 show → 不触发首屏导航）；
* mock 一律经 ``monkeypatch`` 精确注入；模型顺序经真实 ``FileNameRole`` 读取；
* 排序/筛选管线直接复用产品方法（``_set_sort_mode`` / ``_apply_filter_or_reload``），
  不绕开被测接线。

验证命令：
    python -m pytest tests/unit/ui/layout/test_file_selector_native_wiring.py -v
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, List

import pytest

# 布局模块内部使用短路径导入（from theme import tm / components.*），
# 要求 freeassetfilter/ui 位于 sys.path——与 test_layouts.py 的 bootstrap 惯例一致。
_UI_ROOT: str = str(Path(__file__).resolve().parents[4] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from freeassetfilter.ui.layout.file_selector_layout import FileSelectorLayout  # noqa: E402
import freeassetfilter.ui.layout.file_selector_layout as fsl_mod  # noqa: E402

# 与布局模块共享同一模块实例（components.* 短路径），FileNameRole 为 int 角色值。
from components.file_list_model import FileNameRole  # noqa: E402

pytestmark = pytest.mark.unit

_FIXTURES_DIR: Path = (
    Path(__file__).resolve().parents[3] / "support" / "faf_core_fixtures" / "dir_samples"
)


# =============================================================================
# 公共辅助
# =============================================================================
def _make_src_dir(tmp_path: Path) -> Path:
    """构造含混合条目（目录/文件/大小写歧义）的临时目录。

    Args:
        tmp_path: pytest 内置每测试临时目录。

    Returns:
        Path: 构造后的目录路径。
    """
    src_dir: Path = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "banana.txt").write_text("a", encoding="utf-8")
    (src_dir / "Apple.txt").write_text("b", encoding="utf-8")
    (src_dir / "cherry.txt").write_text("c", encoding="utf-8")
    (src_dir / "photo.png").write_bytes(b"x")
    (src_dir / "doc.txt").write_bytes(b"x")
    (src_dir / "images").mkdir()
    return src_dir


def _model_names(layout: Any) -> List[str]:
    """读取模型中全部条目名称（真实 FileNameRole，顺序即模型序）。

    Args:
        layout: FileSelectorLayout 实例。

    Returns:
        List[str]: 名称列表。
    """
    model = layout._file_model  # noqa: SLF001
    return [
        model.data(model.index(i, 0), FileNameRole)  # type: ignore[arg-type]
        for i in range(model.rowCount())
    ]


class _UnavailableBridge:
    """降级桥替身：available=False 且无任何能力标志（模拟 DLL 缺失）。"""

    available = False
    _supports_scan = False
    _supports_sort = False


class _FailingBridge:
    """可用但 native 返回 None 的替身（模拟 native 失败/超 8MB 上限）。"""

    available = True
    _supports_scan = True
    _supports_sort = True

    def scan_directory(self, path: str):
        del path
        return None

    def sort_entries(self, entries, mode):
        del entries, mode
        return None


# =============================================================================
# (a) 排序切换不重扫 + 内存重排与重扫一致
# =============================================================================
class TestSortModeSwitchNoRescan:
    """``_set_sort_mode`` 对 raw 缓存内存重排，绝不重扫磁盘。"""

    def test_sort_switch_uses_cache_and_matches_rescan(
        self, qapp: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """排序切换：collect 计数 0 + 模型顺序正确 + 与重扫结果一致。

        Args:
            qapp: 会话级 QApplication。
            tmp_path: pytest 内置每测试临时目录。
            monkeypatch: pytest monkeypatch fixture。
        """
        src_dir = _make_src_dir(tmp_path)
        layout: Any = FileSelectorLayout()
        layout._load_directory(str(src_dir))  # noqa: SLF001
        assert layout._current_path == str(src_dir)  # noqa: SLF001

        # 模式 0（默认 名称↑）：目录先，文件按小写名升序
        assert _model_names(layout) == [
            "images",
            "Apple.txt",
            "banana.txt",
            "cherry.txt",
            "doc.txt",
            "photo.png",
        ]
        assert len(layout._raw_entries) == 6  # noqa: SLF001

        # 挂载计数包装（仍委托真实实现，断言「未被调用」）
        calls: List[str] = []
        original_collect = layout._collect_directory_entries  # noqa: SLF001

        def counting_collect(path: str) -> Any:
            calls.append(path)
            return original_collect(path)

        monkeypatch.setattr(layout, "_collect_directory_entries", counting_collect)

        # 切换排序 → 内存重排，不触发磁盘重扫
        layout._set_sort_mode(1)
        assert calls == [], "切换排序不应触发磁盘重扫（_collect_directory_entries 计数应保持 0）"
        # 模式 1（名称↓）：文件先（小写名降序），目录最后
        assert _model_names(layout) == [
            "photo.png",
            "doc.txt",
            "cherry.txt",
            "banana.txt",
            "Apple.txt",
            "images",
        ]
        assert len(layout._raw_entries) == 6, "raw 缓存不应被内存重排改写"  # noqa: SLF001

        # 内存重排结果与真实重扫一致（_reload_directory 允许真实重扫）
        mem_names: List[str] = _model_names(layout)
        layout._reload_directory()  # noqa: SLF001
        assert calls, "刷新按钮应真实重扫"
        assert _model_names(layout) == mem_names, "缓存重排结果与重扫结果不一致"


# =============================================================================
# (b) 筛选应用/清除不重扫 + 结果与重扫一致
# =============================================================================
class TestFilterApplyNoRescan:
    """``_apply_filter_or_reload`` 对 raw 缓存内存重排（on_apply/on_clear 共用）。"""

    def test_filter_apply_and_clear_use_cache_without_rescan(
        self, qapp: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """筛选应用/清除：collect 计数 0 + 结果与重扫一致。

        Args:
            qapp: 会话级 QApplication。
            tmp_path: pytest 内置每测试临时目录。
            monkeypatch: pytest monkeypatch fixture。
        """
        src_dir = _make_src_dir(tmp_path)
        layout: Any = FileSelectorLayout()
        layout._load_directory(str(src_dir))  # noqa: SLF001

        calls: List[str] = []
        original_collect = layout._collect_directory_entries  # noqa: SLF001

        def counting_collect(path: str) -> Any:
            calls.append(path)
            return original_collect(path)

        monkeypatch.setattr(layout, "_collect_directory_entries", counting_collect)

        # ── 应用筛选（等价 on_apply 的接线路径）──
        layout._filter_pattern = r"\.png$"  # noqa: SLF001
        layout._update_filter_button_state()  # noqa: SLF001
        layout._apply_filter_or_reload()  # noqa: SLF001
        assert calls == [], "应用筛选不应触发磁盘重扫"
        assert _model_names(layout) == ["photo.png"]

        # 结果与真实重扫一致
        mem_names: List[str] = _model_names(layout)
        layout._reload_directory()  # noqa: SLF001
        assert calls, "刷新按钮应真实重扫"
        assert _model_names(layout) == mem_names, "筛选结果与重扫结果不一致"

        # ── 清除筛选（等价 on_clear 的接线路径）──
        calls.clear()
        layout._filter_pattern = ""  # noqa: SLF001
        layout._update_filter_button_state()  # noqa: SLF001
        layout._apply_filter_or_reload()  # noqa: SLF001
        assert calls == [], "清除筛选不应触发磁盘重扫"
        assert len(_model_names(layout)) == 6, "清除筛选应恢复全部条目"

    def test_filter_on_all_view_falls_back_to_rescan(
        self, qapp: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """"All" 视图无 raw 缓存 → 筛选应用回退重扫（保持现行为）。

        Args:
            qapp: 会话级 QApplication。
            tmp_path: pytest 内置每测试临时目录。
            monkeypatch: pytest monkeypatch fixture。
        """
        layout: Any = FileSelectorLayout()
        layout._current_path = "All"  # noqa: SLF001
        layout._raw_entries = []  # noqa: SLF001
        layout._raw_entries_path = ""  # noqa: SLF001

        reload_calls: List[str] = []
        monkeypatch.setattr(
            layout, "_reload_directory", lambda: reload_calls.append("reload")
        )
        layout._filter_pattern = r"\.png$"  # noqa: SLF001
        layout._apply_filter_or_reload()  # noqa: SLF001
        assert reload_calls == ["reload"], '"All" 视图应回退重扫'


# =============================================================================
# (c) 桥不可用 → Python 回退行为不变
# =============================================================================
class TestBridgeUnavailableFallback:
    """DLL 缺失/失败 → ``_collect_directory_entries`` 回退 Python 实现。"""

    def test_collect_falls_back_to_python_when_bridge_unavailable(
        self, qapp: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """桥 available=False → Python 路径返回等价结果（不崩溃、字段完整）。

        Args:
            qapp: 会话级 QApplication。
            tmp_path: pytest 内置每测试临时目录。
            monkeypatch: pytest monkeypatch fixture。
        """
        src_dir = _make_src_dir(tmp_path)
        monkeypatch.setattr(fsl_mod, "get_faf_core_bridge", lambda: _UnavailableBridge())

        entries = FileSelectorLayout._collect_directory_entries(str(src_dir))
        assert entries is not None, "DLL 缺失时 Python 回退不应返回 None"
        assert sorted(e["name"] for e in entries) == sorted(
            ["banana.txt", "Apple.txt", "cherry.txt", "photo.png", "doc.txt", "images"]
        )
        for entry in entries:
            assert set(entry.keys()) == {
                "name", "path", "is_dir", "size", "modified", "created", "suffix",
            }, "Python 回退条目必须保持 7 键同构"

    def test_collect_falls_back_when_native_returns_none(
        self, qapp: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """桥可用但 native 返回 None（失败/超限）→ 回退 Python，结果不变。

        Args:
            qapp: 会话级 QApplication。
            tmp_path: pytest 内置每测试临时目录。
            monkeypatch: pytest monkeypatch fixture。
        """
        src_dir = _make_src_dir(tmp_path)

        # 桥可用时的基线（真实路径：native 或 Python 均可，字段确定性等价）
        baseline = FileSelectorLayout._collect_directory_entries(str(src_dir))
        assert baseline is not None

        monkeypatch.setattr(fsl_mod, "get_faf_core_bridge", lambda: _FailingBridge())
        actual = FileSelectorLayout._collect_directory_entries(str(src_dir))
        assert actual is not None, "native 失败回退 Python 不应返回 None"

        baseline_by_name = {e["name"]: e for e in baseline}
        actual_by_name = {e["name"]: e for e in actual}
        assert set(baseline_by_name) == set(actual_by_name)
        for name, entry in actual_by_name.items():
            assert entry == baseline_by_name[name], f"回退路径字段分歧: {name}"


# =============================================================================
# (d) 桥可用 → native 与 Python oracle 逐字段一致（dir_samples 夹具）
# =============================================================================
class TestNativeScanParityOnFixtures:
    """native ``scan_directory`` 与 Python oracle 对拍（真实 DLL 可用时）。"""

    @pytest.mark.parametrize("sample", ["project_alpha", "project_beta_混合项目"])
    def test_native_scan_matches_python_oracle(
        self, qapp: Any, monkeypatch: pytest.MonkeyPatch, sample: str
    ) -> None:
        """对 dir_samples 两个夹具目录：native 与 Python oracle 逐字段一致。

        Args:
            qapp: 会话级 QApplication。
            monkeypatch: pytest monkeypatch fixture。
            sample: 夹具目录名（parametrize）。
        """
        import freeassetfilter.core.native.bridges.faf_core_bridge as fcb_mod

        bridge = fcb_mod.get_faf_core_bridge()
        if not bridge.available or not bridge._supports_scan:  # noqa: SLF001
            pytest.skip("faf_core DLL 不可用或缺 scan 导出")

        path: Path = _FIXTURES_DIR / sample
        native = bridge.scan_directory(str(path))
        # 绕过单点接线的 native 优先，直接取 Python 回退实现做 oracle
        python = FileSelectorLayout._collect_directory_entries_python(str(path))
        assert native is not None, f"{sample}: native 扫描失败"
        assert python is not None, f"{sample}: Python oracle 扫描失败"

        native_by_name = {e["name"]: e for e in native}
        python_by_name = {e["name"]: e for e in python}
        assert set(native_by_name) == set(python_by_name), f"{sample}: 条目集合不一致"
        for name, entry in native_by_name.items():
            assert entry == python_by_name[name], f"{sample}/{name}: 逐字段不一致"


# =============================================================================
# 同步/异步路径单点接线冒烟（桥可用时经 _collect_directory_entries 走 native）
# =============================================================================
class TestSinglePointWiring:
    """``_collect_directory_entries`` 为同步/异步双路径的单一接线点。"""

    def test_collect_via_layout_returns_entries(self, qapp: Any, tmp_path: Path) -> None:
        """真实 ``_collect_directory_entries``（native 或回退）返回非 None。

        Args:
            qapp: 会话级 QApplication。
            tmp_path: pytest 内置每测试临时目录。
        """
        src_dir = _make_src_dir(tmp_path)
        entries = FileSelectorLayout._collect_directory_entries(str(src_dir))
        assert entries is not None
        assert len(entries) == 6
        # 目录不可读 → None（调用方清空处理契约不变）
        missing = FileSelectorLayout._collect_directory_entries(
            os.path.abspath(str(tmp_path / "no_such_dir_xyz"))
        )
        assert missing is None
