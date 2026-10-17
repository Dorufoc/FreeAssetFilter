# -*- coding: utf-8 -*-
"""文件选择器渐进式（流式）目录加载单元测试。

覆盖 ``file_selector_layout.py`` 的流式管线：

(a) 首批落地即跳转（``_current_path``/模型就绪）并撤下加载遮罩；
(b) 后续批次增量追加（``FileListModel.append_files``），计数标签显示
    「加载中… N」；
(c) 收尾（``_finalize_stream``）按最终筛选/排序重排，计数恢复为「N 个条目」；
(d) 空目录：单批 ``([], True)`` → 计数 0；
(e) 零批错误（``entries=None`` 且未落地任何批）→ 保留旧视图；
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
    monkeypatch.setattr(
        fsl_mod, "QThreadPool", SimpleNamespace(globalInstance=lambda: fake)
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
# (a)(b)(c) 首批跳转 / 增量追加 / 收尾重排
# =============================================================================
class TestProgressiveStreaming:
    """首批落地即跳转、后续批次增量追加、收尾排序。"""

    def test_first_batch_jumps_before_final(
        self, qapp: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """首批落地：``_current_path`` 与模型立即就绪（无需等待收尾）。"""
        layout = FileSelectorLayout()
        try:
            token = _begin_stream(layout, "C:/stream", monkeypatch)
            before = layout._current_path  # noqa: SLF001
            assert before != "C:/stream", "派发阶段不应提前切换当前路径"

            layout._on_dir_batch_ready(  # noqa: SLF001
                "C:/stream", [_entry("a.txt")], token, False
            )
            assert layout._current_path == "C:/stream"  # noqa: SLF001
            assert _model_names(layout) == ["a.txt"]
        finally:
            safe_teardown(layout)

    def test_multi_batch_appends_progressively(
        self, qapp: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """多批：模型逐批增长、计数字样为「加载中… N」、收尾恢复并排序。"""
        layout = FileSelectorLayout()
        try:
            token = _begin_stream(layout, "C:/stream", monkeypatch)
            layout._on_dir_batch_ready(  # noqa: SLF001
                "C:/stream",
                [_entry("banana.txt"), _entry("apple.txt")],
                token,
                False,
            )
            assert layout._file_model.rowCount() == 2  # noqa: SLF001
            assert layout._file_count_label.text() == "加载中… 2"  # noqa: SLF001

            layout._on_dir_batch_ready(  # noqa: SLF001
                "C:/stream", [_entry("cherry.txt")], token, False
            )
            assert layout._file_model.rowCount() == 3  # noqa: SLF001
            assert layout._file_count_label.text() == "加载中… 3"  # noqa: SLF001

            layout._on_dir_batch_ready("C:/stream", [], token, True)  # noqa: SLF001
            assert _model_names(layout) == ["apple.txt", "banana.txt", "cherry.txt"]
            assert layout._file_count_label.text() == "3 个条目"  # noqa: SLF001
            assert len(layout._raw_entries) == 3  # noqa: SLF001
        finally:
            safe_teardown(layout)

    def test_empty_directory_finalizes_to_zero(
        self, qapp: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """空目录：单批 ``([], True)`` → 模型空、计数 0、raw 缓存绑定目标路径。"""
        layout = FileSelectorLayout()
        try:
            token = _begin_stream(layout, "C:/empty", monkeypatch)
            layout._on_dir_batch_ready("C:/empty", [], token, True)  # noqa: SLF001
            assert layout._file_model.rowCount() == 0  # noqa: SLF001
            assert layout._file_count_label.text() == "0 个条目"  # noqa: SLF001
            assert layout._raw_entries_path == "C:/empty"  # noqa: SLF001
        finally:
            safe_teardown(layout)


# =============================================================================
# (d) 零批错误保留旧视图
# =============================================================================
class TestStreamAbort:
    """零批错误（首帧即失败）：保留旧视图，不回溯已落地批次。"""

    def test_zero_batch_error_keeps_old_view(
        self, qapp: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``entries=None`` 且无首批落地 → 保留旧目录与模型。"""
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
        finally:
            safe_teardown(layout)

    def test_mid_stream_error_keeps_landed_batches(
        self, qapp: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """已落地若干批后错误到达：保留已落地部分（不回溯、不丢失）。"""
        layout = FileSelectorLayout()
        try:
            token = _begin_stream(layout, "C:/stream", monkeypatch)
            layout._on_dir_batch_ready(  # noqa: SLF001
                "C:/stream", [_entry("a.txt"), _entry("b.txt")], token, False
            )
            # 收尾批携带 None（扫描中途异常）：不应清空已落地模型
            layout._on_dir_batch_ready("C:/stream", None, token, True)  # noqa: SLF001
            assert layout._file_model.rowCount() == 2  # noqa: SLF001
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
        """token 不匹配的批次不得追加任何条目。"""
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
            assert layout._file_model.rowCount() == 2  # noqa: SLF001

            layout._filter_pattern = r"\.png$"  # noqa: SLF001
            layout._on_dir_batch_ready(  # noqa: SLF001
                "C:/stream", [_entry("c.png")], token, False
            )
            assert _model_names(layout) == ["a.txt", "b.png", "c.png"]

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
