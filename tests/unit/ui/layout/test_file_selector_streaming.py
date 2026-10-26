# -*- coding: utf-8 -*-
"""文件选择器渐进式（流式）目录加载单元测试。

覆盖 ``file_selector_layout.py`` 的流式管线（OPT-002 Phase 1：缓冲窗口）：

(a) 缓冲窗口内非收尾批不落地：路径/模型保持旧视图（计数标签继续
    「加载中… N」反馈，遮罩延迟策略不变）；
(b) 收尾批在窗口内到达 → 原子落地：单次模型重置、模型即最终排序、
    收尾不再重排（无 ``layoutChanged``）；
(c) 超窗（时长/条数上限）转渐进：先落地已缓冲部分（已排序，即最终序
    在该子集上的投影），后续批次合帧结算（flush 前不逐批插入），收尾
    按最终筛选/排序口径核对重排；
(d) 空目录：单批 ``([], True)`` → 计数 0；
(e) 零批错误（``entries=None`` 且未落地任何批）→ 保留旧视图；缓冲期
    "已读到部分"后失败 → 落地已读到部分并收尾（不回溯、不丢数据）；
(f) 过期 token 批次丢弃；
(g) 流式期间引入筛选 / 切换排序 → 收尾按最新口径重derive 最终集合；
(h) 「All」视图载荷不污染目录 raw 缓存（``_raw_entries_path``）；
(i) ``_iter_directory_batches`` 生成器的取消检查与收尾批语义。

测试纪律（与 test_layouts.py 一致）：``FileSelectorLayout`` 真实构造
（offscreen，不 show）；线程池以替身捕获（不真实跑后台线程），批次经
``_on_dir_batch_ready`` 手工驱动，确保中间态可断言。

验证命令：
    python -m pytest tests/unit/ui/layout/test_file_selector_streaming.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

# 布局模块内部使用短路径导入（from theme import tm / components.*），
# 要求 freeassetfilter/ui 位于 sys.path——与 test_layouts.py 的 bootstrap 惯例一致。
_UI_ROOT: str = str(Path(__file__).resolve().parents[4] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from freeassetfilter.ui.layout.file_selector_layout import FileSelectorLayout  # noqa: E402
import freeassetfilter.ui.layout.file_selector_layout as fsl_mod  # noqa: E402

from components.file_list_model import FileNameRole  # noqa: E402

from tests.support.qt_helpers import safe_teardown  # noqa: E402

pytestmark = pytest.mark.unit


# =============================================================================
# 公共辅助
# =============================================================================
class _FakePool:
    """替身线程池：记录投递的 runnable，不真实执行（避免真实 IO/线程）。"""

    def __init__(self) -> None:
        """初始化投递记录列表。"""
        self.started: List[Any] = []

    def start(self, runnable: Any) -> None:
        """记录被投递的 runnable。

        Args:
            runnable: 生产代码构造的 ``_DirectoryStreamRunnable``。
        """
        self.started.append(runnable)


class _SignalWatch:
    """模型信号计数器：断言原子落地不发生二次重排。"""

    def __init__(self, layout: FileSelectorLayout) -> None:
        """连接目标模型的 ``modelReset`` / ``layoutChanged`` 计数。

        Args:
            layout: FileSelectorLayout 实例。
        """
        self.resets: int = 0
        self.layout_changes: int = 0
        model = layout._file_model  # noqa: SLF001
        model.modelReset.connect(self._on_reset)
        model.layoutChanged.connect(self._on_layout)

    def _on_reset(self, *args: Any) -> None:
        """``modelReset`` 计数（签名兼容信号带参/不带参）。"""
        self.resets += 1

    def _on_layout(self, *args: Any) -> None:
        """``layoutChanged`` 计数（签名兼容信号带参/不带参）。"""
        self.layout_changes += 1


def _begin_stream(
    layout: FileSelectorLayout, path: str, monkeypatch: pytest.MonkeyPatch
) -> int:
    """派发一次流式加载并返回其世代 token（线程池以替身捕获，不跑后台）。

    Args:
        layout: FileSelectorLayout 实例。
        path: 目标目录路径或 ``"All"``。
        monkeypatch: pytest monkeypatch fixture。

    Returns:
        int: 本次流式加载的世代 token。
    """
    fake = _FakePool()
    # P6.2：布局已改走 ``core.pools`` 命名池，patch 门面的 ``pool()``。
    monkeypatch.setattr(
        fsl_mod.thread_pools, "pool", lambda name="interactive": fake
    )
    layout._load_directory_async(path)  # noqa: SLF001
    assert len(fake.started) == 1, "应投递一个流式扫描任务"
    return fake.started[0]._token


def _entry(name: str, is_dir: bool = False, path: str = "") -> Dict[str, Any]:
    """构造 7 键条目字典（与目录扫描产物同构）。

    Args:
        name: 条目名称。
        is_dir: 是否为目录。
        path: 完整路径；缺省用 ``C:/stream/<name>``。

    Returns:
        Dict[str, Any]: 7 键条目字典。
    """
    suffix = "" if is_dir else name.rsplit(".", 1)[-1].lower()
    return {
        "name": name,
        "path": path or f"C:/stream/{name}",
        "is_dir": is_dir,
        "size": 0,
        "modified": "",
        "created": "",
        "suffix": suffix,
    }


def _model_names(layout: FileSelectorLayout) -> List[str]:
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


# =============================================================================
# (a)(b) 缓冲窗口 → 收尾批原子落地
# =============================================================================
class TestAtomicLanding:
    """小目录（多数场景）：缓冲窗口内收尾 → 单次原子落地，首帧即最终序。"""

    def test_hold_then_final_lands_once_sorted(
        self, qapp: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """非收尾批只进缓冲；收尾批落地后模型一次成型且已排序。"""
        layout = FileSelectorLayout()
        try:
            token = _begin_stream(layout, "C:/stream", monkeypatch)
            watch = _SignalWatch(layout)
            before = layout._current_path  # noqa: SLF001
            assert before != "C:/stream", "派发阶段不应提前切换当前路径"

            layout._on_dir_batch_ready(  # noqa: SLF001
                "C:/stream",
                [_entry("banana.txt"), _entry("apple.txt")],
                token,
                False,
            )

            assert layout._stream_holding is True  # noqa: SLF001
            assert layout._current_path == before, "缓冲窗口内不得提前跳转"  # noqa: SLF001
            assert layout._file_model.rowCount() == 0  # noqa: SLF001
            assert layout._file_count_label.text() == "加载中… 2"  # noqa: SLF001

            layout._on_dir_batch_ready(  # noqa: SLF001
                "C:/stream", [_entry("cherry.txt")], token, True
            )

            assert layout._current_path == "C:/stream"  # noqa: SLF001
            assert _model_names(layout) == [
                "apple.txt",
                "banana.txt",
                "cherry.txt",
            ], "首帧落地即最终排序，无二次重排"
            assert layout._file_count_label.text() == "3 个条目"  # noqa: SLF001
            assert watch.resets == 1, "原子落地应只发生一次模型重置"
            assert watch.layout_changes == 0, "收尾不得再发射 layoutChanged"
            assert layout._stream_holding is False  # noqa: SLF001
            assert layout._stream_active_token == -1  # noqa: SLF001
            assert len(layout._raw_entries) == 3  # noqa: SLF001
        finally:
            safe_teardown(layout)

    def test_small_directory_single_final_batch_sorted(
        self, qapp: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """真实小目录形态：单批 ``(未排序条目, True)`` → 落地即最终序。"""
        layout = FileSelectorLayout()
        try:
            token = _begin_stream(layout, "C:/small", monkeypatch)
            watch = _SignalWatch(layout)

            layout._on_dir_batch_ready(  # noqa: SLF001
                "C:/small",
                [_entry("b.txt"), _entry("a.txt"), _entry("c.txt")],
                token,
                True,
            )

            assert _model_names(layout) == ["a.txt", "b.txt", "c.txt"]
            assert layout._file_count_label.text() == "3 个条目"  # noqa: SLF001
            assert watch.resets == 1 and watch.layout_changes == 0
        finally:
            safe_teardown(layout)

    def test_atomic_landing_finishes_path_transition_snapshot_after_sort(
        self, qapp: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """落地路径在收尾（排序后）才抓路径过渡快照，且仅抓一次。"""
        layout = FileSelectorLayout()
        try:
            token = _begin_stream(layout, "C:/stream", monkeypatch)
            calls: List[int] = []
            monkeypatch.setattr(
                layout._file_list,  # noqa: SLF001
                "finish_path_transition",
                lambda direction=None: calls.append(direction or 0) or True,
            )
            layout._pending_transition_direction = 1  # noqa: SLF001

            layout._on_dir_batch_ready(  # noqa: SLF001
                "C:/stream", [_entry("b.txt"), _entry("a.txt")], token, True
            )

            assert calls == [1], "路径过渡快照应恰好在落地时抓取一次"
            assert _model_names(layout) == ["a.txt", "b.txt"]
        finally:
            safe_teardown(layout)


# =============================================================================
# (c) 超窗转渐进：先落地已缓冲部分，后续批次合帧结算
# =============================================================================
class TestProgressiveFallback:
    """慢目录（超窗）：先进入并展示已缓冲部分，后续批次渐进追加。"""

    def test_timeout_presents_buffered_sorted(
        self, qapp: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """缓冲窗口到时：已缓冲条目按最终序落地并进入渐进模式。"""
        layout = FileSelectorLayout()
        try:
            token = _begin_stream(layout, "C:/slow", monkeypatch)
            watch = _SignalWatch(layout)
            layout._on_dir_batch_ready(  # noqa: SLF001
                "C:/slow", [_entry("b.txt"), _entry("a.txt")], token, False
            )
            assert layout._file_model.rowCount() == 0  # noqa: SLF001

            layout._on_stream_hold_timeout()  # noqa: SLF001

            assert layout._current_path == "C:/slow"  # noqa: SLF001
            assert _model_names(layout) == ["a.txt", "b.txt"], "已缓冲部分按最终序落地"
            assert layout._file_count_label.text() == "加载中… 2"  # noqa: SLF001
            assert layout._stream_holding is False  # noqa: SLF001

            layout._on_dir_batch_ready("C:/slow", [_entry("c.txt")], token, True)  # noqa: SLF001
            assert _model_names(layout) == ["a.txt", "b.txt", "c.txt"]
            assert layout._file_count_label.text() == "3 个条目"  # noqa: SLF001
            assert watch.layout_changes == 0, "收尾序已一致，不应触发重排"
        finally:
            safe_teardown(layout)

    def test_empty_buffer_timeout_waits_for_first_batch(
        self, qapp: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """窗口到时但缓冲为空：不落地；首批到达后按超窗分支转渐进。"""
        monkeypatch.setattr(fsl_mod, "DIR_STREAM_HOLD_MAX_MS", 0)
        layout = FileSelectorLayout()
        try:
            token = _begin_stream(layout, "C:/slow", monkeypatch)

            layout._on_stream_hold_timeout()  # noqa: SLF001
            assert layout._file_model.rowCount() == 0  # noqa: SLF001
            assert layout._stream_holding is True  # noqa: SLF001

            layout._on_dir_batch_ready(  # noqa: SLF001
                "C:/slow", [_entry("b.txt"), _entry("a.txt")], token, False
            )
            assert layout._current_path == "C:/slow"  # noqa: SLF001
            assert _model_names(layout) == ["a.txt", "b.txt"]
            assert layout._file_count_label.text() == "加载中… 2"  # noqa: SLF001

            layout._on_dir_batch_ready("C:/slow", [], token, True)  # noqa: SLF001
            assert layout._file_count_label.text() == "2 个条目"  # noqa: SLF001
        finally:
            safe_teardown(layout)

    def test_hold_cap_triggers_progressive(
        self, qapp: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """缓冲达到条数上限：立即转渐进并落地已缓冲部分。"""
        cap = fsl_mod.DIR_STREAM_HOLD_MAX_ENTRIES
        layout = FileSelectorLayout()
        try:
            token = _begin_stream(layout, "C:/big", monkeypatch)
            batch = [_entry(f"f{i:04d}.txt") for i in range(cap + 1)]

            layout._on_dir_batch_ready("C:/big", batch, token, False)  # noqa: SLF001

            assert layout._file_model.rowCount() == cap + 1  # noqa: SLF001
            assert layout._file_count_label.text() == f"加载中… {cap + 1}"  # noqa: SLF001

            layout._on_dir_batch_ready("C:/big", [], token, True)  # noqa: SLF001
            assert layout._file_count_label.text() == f"{cap + 1} 个条目"  # noqa: SLF001
        finally:
            safe_teardown(layout)

    def test_progressive_batches_coalesce_until_flush(
        self, qapp: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """渐进模式：批次先入合帧缓冲，flush 一次插入（不逐批 relayout）。"""
        monkeypatch.setattr(fsl_mod, "DIR_STREAM_HOLD_MAX_MS", 0)
        layout = FileSelectorLayout()
        try:
            token = _begin_stream(layout, "C:/big", monkeypatch)
            layout._on_dir_batch_ready("C:/big", [_entry("a.txt")], token, False)  # noqa: SLF001
            assert layout._file_model.rowCount() == 1  # noqa: SLF001

            layout._on_dir_batch_ready("C:/big", [_entry("b.txt")], token, False)  # noqa: SLF001
            layout._on_dir_batch_ready("C:/big", [_entry("c.txt")], token, False)  # noqa: SLF001
            assert layout._file_model.rowCount() == 1, "flush 前不逐批插入"  # noqa: SLF001
            assert len(layout._raw_entries) == 3, "raw 缓存即时累积"  # noqa: SLF001

            layout._flush_stream_batches()  # noqa: SLF001
            assert layout._file_model.rowCount() == 3  # noqa: SLF001
            assert layout._file_count_label.text() == "加载中… 3"  # noqa: SLF001

            layout._on_dir_batch_ready("C:/big", [], token, True)  # noqa: SLF001
            assert _model_names(layout) == ["a.txt", "b.txt", "c.txt"]
            assert layout._file_count_label.text() == "3 个条目"  # noqa: SLF001
        finally:
            safe_teardown(layout)


# =============================================================================
# (d) 空目录
# =============================================================================
class TestEmptyDirectory:
    """空目录：单批 ``([], True)`` 原子落地。"""

    def test_empty_directory_finalizes_to_zero(
        self, qapp: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """空目录：模型空、计数 0、raw 缓存绑定目标路径。"""
        layout = FileSelectorLayout()
        try:
            token = _begin_stream(layout, "C:/empty", monkeypatch)
            layout._on_dir_batch_ready("C:/empty", [], token, True)  # noqa: SLF001
            assert layout._file_model.rowCount() == 0  # noqa: SLF001
            assert layout._file_count_label.text() == "0 个条目"  # noqa: SLF001
            assert layout._raw_entries_path == "C:/empty"  # noqa: SLF001
            assert layout._current_path == "C:/empty"  # noqa: SLF001
        finally:
            safe_teardown(layout)


# =============================================================================
# (e) 错误：零批回滚 / 缓冲期部分落地
# =============================================================================
class TestStreamAbort:
    """错误语义：未读到任何内容 → 保留旧视图；已读到部分 → 落地不回溯。"""

    def test_zero_batch_error_keeps_old_view(
        self, qapp: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``entries=None`` 且无任何缓冲内容 → 保留旧目录与模型。"""
        layout = FileSelectorLayout()
        try:
            layout._current_path = "C:/old"  # noqa: SLF001
            old = [_entry("keep.txt")]
            layout._raw_entries = list(old)  # noqa: SLF001
            layout._raw_entries_path = "C:/old"  # noqa: SLF001
            layout._file_model.set_files(old)  # noqa: SLF001

            token = _begin_stream(layout, "C:/bad", monkeypatch)
            layout._on_dir_batch_ready("C:/bad", None, token, True)  # noqa: SLF001

            assert layout._current_path == "C:/old"  # noqa: SLF001
            assert _model_names(layout) == ["keep.txt"]
            assert layout._raw_entries_path == "C:/old"  # noqa: SLF001
            assert layout._stream_holding is False  # noqa: SLF001
        finally:
            safe_teardown(layout)

    def test_mid_stream_error_keeps_read_entries(
        self, qapp: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """缓冲期已读到部分后错误到达：落地已读到部分（不回溯、不丢失）。"""
        layout = FileSelectorLayout()
        try:
            token = _begin_stream(layout, "C:/stream", monkeypatch)
            layout._on_dir_batch_ready(  # noqa: SLF001
                "C:/stream", [_entry("a.txt"), _entry("b.txt")], token, False
            )
            # 收尾批携带 None（扫描中途异常）：不应清空已读到的部分
            layout._on_dir_batch_ready("C:/stream", None, token, True)  # noqa: SLF001
            assert _model_names(layout) == ["a.txt", "b.txt"]
            assert layout._file_count_label.text() == "2 个条目"  # noqa: SLF001
        finally:
            safe_teardown(layout)


# =============================================================================
# (f) 过期 token 批次丢弃
# =============================================================================
class TestStaleToken:
    """过期世代 token 的批次一律丢弃，不影响当前视图。"""

    def test_stale_batch_discarded(
        self, qapp: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """token 不匹配的批次不得落地/追加任何条目。"""
        layout = FileSelectorLayout()
        try:
            before = layout._current_path  # noqa: SLF001
            token = _begin_stream(layout, "C:/stream", monkeypatch)
            layout._on_dir_batch_ready(  # noqa: SLF001
                "C:/stream", [_entry("x.txt")], token - 1, False
            )
            assert layout._file_model.rowCount() == 0  # noqa: SLF001
            assert layout._current_path == before, "过期批次不得改变当前路径"  # noqa: SLF001
        finally:
            safe_teardown(layout)

    def test_batch_after_finalize_discarded(
        self, qapp: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """收尾后的迟到批次（同 token）被丢弃（世代已终止）。"""
        layout = FileSelectorLayout()
        try:
            token = _begin_stream(layout, "C:/stream", monkeypatch)
            layout._on_dir_batch_ready(  # noqa: SLF001
                "C:/stream", [_entry("a.txt")], token, True
            )
            layout._on_dir_batch_ready(  # noqa: SLF001
                "C:/stream", [_entry("late.txt")], token, False
            )
            assert _model_names(layout) == ["a.txt"]
        finally:
            safe_teardown(layout)


# =============================================================================
# (g) 流式期间筛选 / 排序变更 → 收尾重derive
# =============================================================================
class TestMidStreamReconcile:
    """流式期间修改筛选/排序：收尾按最新口径重建最终集合。"""

    def test_filter_introduced_mid_stream_reconciles_at_finalize(
        self, qapp: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """中途引入筛选：收尾后模型只含匹配项，raw 缓存保留全量。"""
        layout = FileSelectorLayout()
        try:
            token = _begin_stream(layout, "C:/stream", monkeypatch)
            layout._on_dir_batch_ready(  # noqa: SLF001
                "C:/stream", [_entry("a.txt"), _entry("b.png")], token, False
            )
            assert layout._file_model.rowCount() == 0, "缓冲期不提前落地"  # noqa: SLF001
            assert layout._file_count_label.text() == "加载中… 2"  # noqa: SLF001

            layout._filter_pattern = r"\.png$"  # noqa: SLF001
            layout._on_dir_batch_ready(  # noqa: SLF001
                "C:/stream", [_entry("c.png")], token, False
            )
            assert layout._file_model.rowCount() == 0  # noqa: SLF001
            assert layout._file_count_label.text() == "加载中… 2", "计数按新筛选口径反馈"  # noqa: SLF001

            layout._on_dir_batch_ready("C:/stream", [], token, True)  # noqa: SLF001
            assert _model_names(layout) == ["b.png", "c.png"]
            assert len(layout._raw_entries) == 3, "raw 缓存不应被筛选删除"  # noqa: SLF001
        finally:
            safe_teardown(layout)

    def test_sort_change_mid_stream_applies_at_finalize(
        self, qapp: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """中途切换排序：收尾按新模式重排最终集合。"""
        layout = FileSelectorLayout()
        try:
            token = _begin_stream(layout, "C:/stream", monkeypatch)
            layout._on_dir_batch_ready(  # noqa: SLF001
                "C:/stream", [_entry("a.txt"), _entry("c.txt")], token, False
            )
            layout._set_sort_mode(1)  # 名称降序  # noqa: SLF001
            layout._on_dir_batch_ready(  # noqa: SLF001
                "C:/stream", [_entry("b.txt")], token, False
            )
            layout._on_dir_batch_ready("C:/stream", [], token, True)  # noqa: SLF001
            assert _model_names(layout) == ["c.txt", "b.txt", "a.txt"]
        finally:
            safe_teardown(layout)

    def test_filter_apply_during_stream_does_not_rescan(
        self, qapp: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """流式进行中调用 ``_apply_filter_or_reload``：不触发重扫，留待收尾。"""
        layout = FileSelectorLayout()
        try:
            token = _begin_stream(layout, "C:/stream", monkeypatch)
            layout._on_dir_batch_ready(  # noqa: SLF001
                "C:/stream", [_entry("a.txt"), _entry("b.png")], token, False
            )

            reload_calls: List[str] = []
            monkeypatch.setattr(
                layout,  # noqa: SLF001
                "_reload_directory",
                lambda: reload_calls.append("reload"),
            )
            layout._filter_pattern = r"\.png$"  # noqa: SLF001
            layout._apply_filter_or_reload()  # noqa: SLF001
            assert reload_calls == [], "流式期间筛选不得触发重扫"

            layout._on_dir_batch_ready("C:/stream", [], token, True)  # noqa: SLF001
            assert _model_names(layout) == ["b.png"]
        finally:
            safe_teardown(layout)


# =============================================================================
# (h) All 视图载荷不污染目录 raw 缓存
# =============================================================================
class TestAllViewStreaming:
    """「All」视图单批发完，且不改写 ``_raw_entries_path``。"""

    def test_all_view_stream_keeps_raw_cache_clean(
        self, qapp: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """All 流式：模型落地盘符，但目录 raw 缓存绑定保持原状。"""
        layout = FileSelectorLayout()
        try:
            layout._raw_entries_path = "C:/prev"  # noqa: SLF001
            token = _begin_stream(layout, "All", monkeypatch)
            drives = [_entry("C:", is_dir=True), _entry("D:", is_dir=True)]
            layout._on_dir_batch_ready("All", drives, token, True)  # noqa: SLF001

            assert layout._file_model.rowCount() == 2  # noqa: SLF001
            assert layout._raw_entries_path == "C:/prev", "All 不得污染目录 raw 缓存"  # noqa: SLF001
            assert layout._stream_all_entries == drives  # noqa: SLF001
        finally:
            safe_teardown(layout)


# =============================================================================
# (i) _iter_directory_batches 生成器语义
# =============================================================================
class TestIterDirectoryBatches:
    """生成器的分批、收尾批与取消检查语义。"""

    def test_non_cancel_path_terminates_with_final_batch(self, tmp_path: Path) -> None:
        """正常路径：以 ``is_final=True`` 收尾，条目总数守恒。"""
        src = tmp_path / "many"
        src.mkdir()
        for i in range(200):
            (src / f"f{i:03d}.txt").write_text("x", encoding="utf-8")

        batches = list(
            FileSelectorLayout._iter_directory_batches(
                str(src), False, lambda: False, batch_size=1
            )
        )
        assert batches[-1][1] is True, "最后一批必须标记 is_final=True"
        assert sum(len(b) for b, _ in batches) == 200
        assert all(not b[1] for b in batches[:-1]), "非收尾批 is_final 应为 False"

    def test_cancel_check_stops_iteration(self, tmp_path: Path) -> None:
        """取消检查为 True 时立即停止（不产出收尾批）。"""
        src = tmp_path / "many"
        src.mkdir()
        for i in range(200):
            (src / f"f{i:03d}.txt").write_text("x", encoding="utf-8")

        state = {"n": 0}

        def _cancel() -> bool:
            """第三次检查时取消（允许前两批落地）。"""
            state["n"] += 1
            return state["n"] > 2

        batches = list(
            FileSelectorLayout._iter_directory_batches(
                str(src), False, _cancel, batch_size=1
            )
        )
        # batch_size=1：前两次检查放行各产一批，第三次检查取消 → 恰 2 批、无收尾批。
        assert len(batches) == 2, "取消后应立即停止扫描（仅放行前两批）"
        assert all(not final for _, final in batches), "取消后不得产出收尾批"
        assert sum(len(b) for b, _ in batches) == 2

    def test_all_path_single_final_batch(self) -> None:
        """``path="All"``：单批 ``(盘符列表, True)``。"""
        batches = list(
            FileSelectorLayout._iter_directory_batches("All", False, lambda: False)
        )
        assert len(batches) == 1
        entries, is_final = batches[0]
        assert is_final is True
        assert isinstance(entries, list)
