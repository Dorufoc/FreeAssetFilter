# -*- coding: utf-8 -*-
"""FileSelectorLayout 方向键导航单元测试（arrow-key-file-preview-nav Todo 1 + Todo 2）。

覆盖计划 Todo 1 验收标准 (a)-(e)：
  (a) ``_nav_cols()`` 列表模式返回 1、卡片模式返回 ``max(1, _grid_cols)``；
  (b) ``_scan_file_row`` 在 ``[dir, a, b, c]`` 上从 ``a`` 向前依次命中
      ``b``/``c`` 并环绕回 ``a``（目录被跳过）；
  (c) ``_grid_step_row`` 在 ``cols=3``、``[a, dir, b, c, d, e]`` 上从 idx0
      ``+1`` 命中 idx3（c，模型行网格，而非文件序），从 idx2（b）``+1``
      命中 idx5（e）；
  (d) ``_resolve_anchor_row`` 解析 ``set_previewing_file`` 写入的规范化路径，
      未知路径返回 -1，大小写不同时走 normcase 回退扫描；
  (e) 卡片模式 ``_grid_cols == 0``（未布局）回退为 1 且不抛异常。
另覆盖窄边界：空模型 / 全目录模型 / 单文件模型 / 越界行 / reset_nav_state
在模型重填路径上的自动复位。
Todo 2 追加：``handle_nav_key_press`` / ``handle_nav_key_release`` 的
tap 一步、连发（hold）、释放恰好一次发射、方向键放行语义与卡片网格
垂直步进（验收 (a)-(k)），并覆盖原始 int 键值（主窗口 ``event.key()``
调用口径）与"手势中模型重填"的对抗场景。

验证命令：
    .venv/Scripts/python.exe -m pytest tests/unit/ui/layout/test_file_selector_keyboard_nav.py -q --timeout 60
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

# 布局模块内部使用短路径导入（from theme import tm / components.*），
# 要求 freeassetfilter/ui 位于 sys.path；与 test_layouts.py:48-53 的
# bootstrap 约定一致。
_UI_ROOT: str = str(Path(__file__).resolve().parents[4] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from freeassetfilter.ui.layout.file_selector_layout import FileSelectorLayout

pytestmark = pytest.mark.unit

#: 伪路径基目录（条目仅落模型，不做任何磁盘访问）。
_BASE_DIR: str = os.path.normpath("C:/nav_todo1")


def _entry(name: str, is_dir: bool = False) -> Dict[str, Any]:
    """构造 7 键条目字典（与 ``FileListModel.set_files`` 的契约一致）。

    Args:
        name: 文件名。
        is_dir: 是否为目录。

    Returns:
        Dict[str, Any]: name/path/is_dir/size/modified/created/suffix 条目。
    """
    path = os.path.normpath(os.path.join(_BASE_DIR, name))
    suffix = "" if is_dir or "." not in name else name.rsplit(".", 1)[-1].lower()
    return {
        "name": name,
        "path": path,
        "is_dir": is_dir,
        "size": 0,
        "modified": "2026-01-01 00:00:00",
        "created": "2026-01-01 00:00:00",
        "suffix": suffix,
    }


def _make_layout(
    qapp: QApplication,
    entries: List[Dict[str, Any]],
    view_mode: str = "card",
    grid_cols: int = 0,
) -> FileSelectorLayout:
    """构造真实 ``FileSelectorLayout`` 并直接写入模型/视图快照（不触磁盘）。

    Args:
        qapp: 会话级 QApplication（offscreen）。
        entries: 7 键条目列表（``FileListModel.set_files`` 入参）。
        view_mode: ``card`` 或 ``list``。
        grid_cols: 网格列数快照（0 = 尚未布局）。

    Returns:
        FileSelectorLayout: 已落模型与视图参数的选择器实例。
    """
    layout = FileSelectorLayout()
    layout._file_model.set_files(entries)
    layout._current_path = _BASE_DIR
    layout._view_mode = view_mode
    layout._grid_cols = grid_cols
    return layout


class TestNavCols:
    """验收标准 (a)/(e)：视图列数快照与 0 回退。"""

    def test_list_mode_is_single_column(self, qapp: QApplication) -> None:
        """(a) 列表模式恒为 1（无视卡片网格残值）。"""
        layout = _make_layout(qapp, [_entry("a.txt")], view_mode="list", grid_cols=5)
        try:
            assert layout._nav_cols() == 1
        finally:
            layout.deleteLater()

    def test_card_mode_uses_grid_cols(self, qapp: QApplication) -> None:
        """(a) 卡片模式返回 max(1, _grid_cols)。"""
        layout = _make_layout(qapp, [_entry("a.txt")], view_mode="card", grid_cols=4)
        try:
            assert layout._nav_cols() == 4
        finally:
            layout.deleteLater()

    def test_card_mode_uncomputed_grid_cols_falls_back_to_one(
        self, qapp: QApplication
    ) -> None:
        """(e) _grid_cols == 0（未布局）回退为 1，不抛异常、无重排。"""
        layout = _make_layout(qapp, [_entry("a.txt")], view_mode="card", grid_cols=0)
        try:
            assert layout._nav_cols() == 1
        finally:
            layout.deleteLater()


class TestScanFileRow:
    """验收标准 (b)：文件序扫描跳过目录并环绕。"""

    def test_forward_skips_dir_and_wraps(self, qapp: QApplication) -> None:
        """(b) [dir, a, b, c] 从 a 前行：b → c → 环绕回 a（跳过目录）。"""
        entries = [
            _entry("folder", True),
            _entry("a.txt"),
            _entry("b.txt"),
            _entry("c.txt"),
        ]
        layout = _make_layout(qapp, entries)
        try:
            assert layout._row_is_dir(0) is True
            assert layout._scan_file_row(1, 1) == 2
            assert layout._scan_file_row(2, 1) == 3
            assert layout._scan_file_row(3, 1) == 1  # 环绕越过目录回到 a
        finally:
            layout.deleteLater()

    def test_backward_skips_dir_and_wraps(self, qapp: QApplication) -> None:
        """(b) 反向：从 a 后退环绕到 c；从 b 后退到 a。"""
        entries = [
            _entry("folder", True),
            _entry("a.txt"),
            _entry("b.txt"),
            _entry("c.txt"),
        ]
        layout = _make_layout(qapp, entries)
        try:
            assert layout._scan_file_row(1, -1) == 3
            assert layout._scan_file_row(2, -1) == 1
        finally:
            layout.deleteLater()

    def test_empty_model_returns_none(self, qapp: QApplication) -> None:
        """空模型（rowCount == 0）返回 None，不抛异常。"""
        layout = _make_layout(qapp, [])
        try:
            assert layout._scan_file_row(0, 1) is None
            assert layout._scan_file_row(0, -1) is None
        finally:
            layout.deleteLater()

    def test_only_dirs_model_returns_none(self, qapp: QApplication) -> None:
        """全目录模型返回 None（无文件可命中）。"""
        layout = _make_layout(qapp, [_entry("d1", True), _entry("d2", True)])
        try:
            assert layout._scan_file_row(0, 1) is None
            assert layout._scan_file_row(1, -1) is None
        finally:
            layout.deleteLater()

    def test_single_file_model_wraps_to_itself(self, qapp: QApplication) -> None:
        """单文件模型环绕即自身（算法自然结果，无异常）。"""
        layout = _make_layout(qapp, [_entry("a.txt")])
        try:
            assert layout._scan_file_row(0, 1) == 0
            assert layout._scan_file_row(0, -1) == 0
        finally:
            layout.deleteLater()


class TestGridStepRow:
    """验收标准 (c)：卡片网格按模型行步进（cols 计全部格子含目录）。"""

    @staticmethod
    def _layout(qapp: QApplication) -> FileSelectorLayout:
        """构造 cols=3 的 6 行混合模型 [a, dir, b, c, d, e]（idx 0..5）。"""
        entries = [
            _entry("a.txt"),
            _entry("folder", True),
            _entry("b.txt"),
            _entry("c.txt"),
            _entry("d.txt"),
            _entry("e.txt"),
        ]
        return _make_layout(qapp, entries, view_mode="card", grid_cols=3)

    def test_down_from_row0_uses_model_row_grid(self, qapp: QApplication) -> None:
        """(c) idx0 (a, 行0列0) +1 → 行2列0 = idx3 (c)，而不是文件序邻居 b/d。"""
        layout = self._layout(qapp)
        try:
            assert layout._grid_step_row(0, 1) == 3
            assert layout._row_path(3).endswith("c.txt")
            # 对照：文件序步进给出的是 b（idx2）——证明取的是模型行网格。
            assert layout._scan_file_row(0, 1) == 2
        finally:
            layout.deleteLater()

    def test_down_from_row2_snaps_to_column(self, qapp: QApplication) -> None:
        """(c) idx2 (b, 行0列2) +1 → 行2列2 = idx5 (e)。"""
        layout = self._layout(qapp)
        try:
            assert layout._grid_step_row(2, 1) == 5
            assert layout._row_path(5).endswith("e.txt")
        finally:
            layout.deleteLater()

    def test_down_from_last_grid_row_wraps_to_row_zero(
        self, qapp: QApplication
    ) -> None:
        """末行 +1 环绕到首行同列：idx3 (c, 行1列0) +1 → idx0 (a)。"""
        layout = self._layout(qapp)
        try:
            assert layout._grid_step_row(3, 1) == 0
        finally:
            layout.deleteLater()

    def test_up_snaps_to_nearest_column(self, qapp: QApplication) -> None:
        """idx5 (e, 行1列2) -1 → 行0 最近非目录 = idx2 (b)。"""
        layout = self._layout(qapp)
        try:
            assert layout._grid_step_row(5, -1) == 2
        finally:
            layout.deleteLater()

    def test_target_row_all_dirs_returns_none(self, qapp: QApplication) -> None:
        """目标网格行整行皆目录：返回 None（调用方回退文件序扫描）。"""
        entries = [
            _entry("a.txt"),
            _entry("folder1", True),
            _entry("folder2", True),
            _entry("folder3", True),
        ]
        layout = _make_layout(qapp, entries, view_mode="card", grid_cols=2)
        try:
            assert layout._grid_step_row(0, 1) is None
        finally:
            layout.deleteLater()

    def test_empty_model_returns_none(self, qapp: QApplication) -> None:
        """空模型返回 None，不抛异常。"""
        layout = _make_layout(qapp, [], view_mode="card", grid_cols=3)
        try:
            assert layout._grid_step_row(0, 1) is None
            assert layout._grid_step_row(0, -1) is None
        finally:
            layout.deleteLater()


class TestResolveAnchorRow:
    """验收标准 (d)：锚点行解析（预览路径 / 光标路径 / normcase 回退 / -1）。"""

    _ENTRIES: List[Dict[str, Any]] = [
        _entry("folder", True),
        _entry("a.txt"),
        _entry("b.txt"),
        _entry("c.txt"),
    ]

    def test_previewing_path_resolves_after_set_previewing_file(
        self, qapp: QApplication
    ) -> None:
        """(d) set_previewing_file 规范化写入后，_resolve_anchor_row 命中其行。"""
        layout = _make_layout(qapp, self._ENTRIES)
        try:
            assert layout._resolve_anchor_row() == -1  # 无锚点
            layout.set_previewing_file(_entry("b.txt")["path"])
            assert layout._previewing_file_path == os.path.normpath(
                _entry("b.txt")["path"]
            )
            assert layout._resolve_anchor_row() == 2
        finally:
            layout.deleteLater()

    def test_unknown_paths_return_minus_one(self, qapp: QApplication) -> None:
        """(d) 陌生路径 → -1（含 set_previewing_file 未命中不写状态的情况）。"""
        layout = _make_layout(qapp, self._ENTRIES)
        try:
            layout.set_previewing_file(os.path.normpath("C:/nav_todo1/ghost.txt"))
            assert layout._previewing_file_path == ""
            assert layout._resolve_anchor_row() == -1
        finally:
            layout.deleteLater()

    def test_case_difference_falls_back_to_normcase_scan(
        self, qapp: QApplication
    ) -> None:
        """(d) 盘符/段大小写不同 → normcase/normpath 全表扫描回退仍命中。"""
        layout = _make_layout(qapp, self._ENTRIES)
        try:
            # 直接注入未规范化的全大写路径（set_previewing_file 只接受精确命中）。
            layout._previewing_file_path = _entry("b.txt")["path"].upper()
            assert layout._resolve_anchor_row() == 2
        finally:
            layout.deleteLater()

    def test_cursor_path_takes_priority_over_previewing_path(
        self, qapp: QApplication
    ) -> None:
        """手势光标路径优先于预览路径。"""
        layout = _make_layout(qapp, self._ENTRIES)
        try:
            layout.set_previewing_file(_entry("a.txt")["path"])
            layout._nav_cursor_path = _entry("c.txt")["path"]
            assert layout._resolve_anchor_row() == 3
        finally:
            layout.deleteLater()

    def test_empty_model_returns_minus_one(self, qapp: QApplication) -> None:
        """空模型任何锚点都无法解析 → -1。"""
        layout = _make_layout(qapp, [])
        try:
            layout._nav_cursor_path = os.path.join(_BASE_DIR, "a.txt")
            layout._previewing_file_path = os.path.join(_BASE_DIR, "a.txt")
            assert layout._resolve_anchor_row() == -1
        finally:
            layout.deleteLater()


class TestNavModelSignatureAndRowGuards:
    """辅助契约：模型签名三元组与越界行守卫。"""

    def test_model_signature_tuple(self, qapp: QApplication) -> None:
        """签名 = (_current_path, rowCount, _view_mode)。"""
        layout = _make_layout(qapp, [_entry("a.txt")], view_mode="list", grid_cols=1)
        try:
            assert layout._nav_model_signature() == (_BASE_DIR, 1, "list")
        finally:
            layout.deleteLater()

    def test_out_of_range_rows_are_guarded(self, qapp: QApplication) -> None:
        """越界行：_row_is_dir → False、_row_path → ""（不抛异常）。"""
        layout = _make_layout(qapp, [_entry("a.txt")])
        try:
            assert layout._row_is_dir(-1) is False
            assert layout._row_is_dir(5) is False
            assert layout._row_path(-1) == ""
            assert layout._row_path(99) == ""
        finally:
            layout.deleteLater()


class TestResetNavState:
    """模型重填（目录切换）自动复位导航手势状态。"""

    def test_reset_clears_gesture_fields(self, qapp: QApplication) -> None:
        """reset_nav_state 清空 active/cursor_row/model_key（幂等）。"""
        layout = _make_layout(qapp, [_entry("a.txt")])
        try:
            layout._nav_active = True
            layout._nav_cursor_row = 0
            layout._nav_model_key = (_BASE_DIR, 1, "card")
            layout.reset_nav_state()
            assert layout._nav_active is False
            assert layout._nav_cursor_row == -1
            assert layout._nav_model_key is None
            layout.reset_nav_state()  # 幂等：再次调用不抛异常
            assert layout._nav_active is False
        finally:
            layout.deleteLater()

    def test_apply_directory_entries_resets_nav_state(
        self, qapp: QApplication
    ) -> None:
        """同步目录应用（_apply_directory_entries）后手势状态被复位。"""
        layout = _make_layout(qapp, [_entry("a.txt")])
        try:
            layout._nav_active = True
            layout._nav_cursor_row = 0
            layout._nav_model_key = (_BASE_DIR, 1, "card")
            layout._apply_directory_entries(
                _BASE_DIR, [_entry("x.txt"), _entry("y.txt")]
            )
            assert layout._nav_active is False
            assert layout._nav_cursor_row == -1
            assert layout._nav_model_key is None
            assert layout._file_model.rowCount() == 2
        finally:
            layout.deleteLater()

    def test_apply_first_batch_resets_nav_state(self, qapp: QApplication) -> None:
        """流式首批落地（_apply_first_batch，生产导航路径）后手势状态被复位。"""
        layout = _make_layout(qapp, [_entry("a.txt")])
        try:
            layout._nav_active = True
            layout._nav_cursor_row = 0
            layout._nav_model_key = (_BASE_DIR, 1, "card")
            layout._apply_first_batch(_BASE_DIR, [_entry("x.txt")])
            assert layout._nav_active is False
            assert layout._nav_cursor_row == -1
            assert layout._nav_model_key is None
            assert layout._current_path == _BASE_DIR
            assert layout._file_model.rowCount() == 1
        finally:
            layout.deleteLater()

    def test_apply_all_entries_resets_nav_state(self, qapp: QApplication) -> None:
        """All 视图重填（_apply_all_entries）后手势状态被复位。"""
        layout = _make_layout(qapp, [_entry("a.txt")])
        try:
            layout._nav_active = True
            layout._nav_cursor_row = 0
            layout._nav_model_key = (_BASE_DIR, 1, "card")
            layout._apply_all_entries([_entry("C.txt", False)])
            assert layout._nav_active is False
            assert layout._nav_cursor_row == -1
            assert layout._nav_model_key is None
        finally:
            layout.deleteLater()


# ── Todo 2：按下/释放手势（tap 一步、hold 连发、release 只发一次）─────────


def _emit_spy(layout: FileSelectorLayout) -> List[Dict[str, Any]]:
    """连接 ``file_selected`` 并把发射参数实时收集进列表（间谍）。

    Args:
        layout: 待观测的文件选择器。

    Returns:
        List[Dict[str, Any]]: 已发射的文件信息字典列表。
    """
    emitted: List[Dict[str, Any]] = []
    layout.file_selected.connect(emitted.append)
    return emitted


class TestNavPressRelease:
    """验收标准 (a)-(h)：tap 步进、连发保持、释放单发、放行语义。"""

    @staticmethod
    def _dir_abc_layout(qapp: QApplication) -> FileSelectorLayout:
        """构造 [dir, a, b, c] 卡片布局（cols=3；锚点由用例自行预置）。"""
        entries = [
            _entry("folder", True),
            _entry("a.txt"),
            _entry("b.txt"),
            _entry("c.txt"),
        ]
        return _make_layout(qapp, entries, view_mode="card", grid_cols=3)

    def test_tap_advances_one_file_and_emits_once(
        self, qapp: QApplication
    ) -> None:
        """(a) 锚点 a + Right 按放：光标到 b；按下零发射，释放恰好一次 path=b。"""
        layout = self._dir_abc_layout(qapp)
        emitted = _emit_spy(layout)
        try:
            layout.set_previewing_file(_entry("a.txt")["path"])
            assert layout.handle_nav_key_press(Qt.Key_Right) is True
            assert layout._nav_cursor_path == _entry("b.txt")["path"]
            assert emitted == []  # 按下阶段绝不发射（不加载预览）
            assert layout.handle_nav_key_release(Qt.Key_Right) is True
            assert len(emitted) == 1
            assert emitted[0]["path"] == _entry("b.txt")["path"]
            assert emitted[0]["name"] == "b.txt"
            assert emitted[0]["is_dir"] is False
        finally:
            layout.deleteLater()

    def test_second_tap_moves_to_next_file_then_wraps(
        self, qapp: QApplication
    ) -> None:
        """(b) 连续 tap：a→b→c→环绕回 a（跨目录跳过），依次各发一次。"""
        layout = self._dir_abc_layout(qapp)
        emitted = _emit_spy(layout)
        try:
            layout.set_previewing_file(_entry("a.txt")["path"])
            for expected in ("b.txt", "c.txt", "a.txt"):
                assert layout.handle_nav_key_press(Qt.Key_Right) is True
                assert layout._nav_cursor_path == _entry(expected)["path"]
                assert layout.handle_nav_key_release(Qt.Key_Right) is True
            assert [info["path"] for info in emitted] == [
                _entry("b.txt")["path"],
                _entry("c.txt")["path"],
                _entry("a.txt")["path"],
            ]
        finally:
            layout.deleteLater()

    def test_hold_advances_per_repeat_and_emits_once_on_release(
        self, qapp: QApplication
    ) -> None:
        """(c)(d) 无预置锚点：Right 连按 3 次（hold）落到 c；期间零发射，释放后仅一次。

        注意不预置锚点：若预置 a，3 次连发会多走一步（b→c→环绕 a），
        与验收 (c) 的"以 a 为起点、3 次到 c"不符。
        """
        layout = self._dir_abc_layout(qapp)
        emitted = _emit_spy(layout)
        try:
            for _ in range(3):
                assert layout.handle_nav_key_press(Qt.Key_Right) is True
                assert emitted == []  # 连发期间绝不发射（预览不加载）
            assert layout._nav_cursor_path == _entry("c.txt")["path"]
            assert layout.handle_nav_key_release(Qt.Key_Right) is True
            assert len(emitted) == 1
            assert emitted[0]["path"] == _entry("c.txt")["path"]
        finally:
            layout.deleteLater()

    def test_no_anchor_right_picks_first_file(self, qapp: QApplication) -> None:
        """(e) 无锚点 + Right → 第一个文件（目录被跳过）。"""
        layout = self._dir_abc_layout(qapp)
        try:
            assert layout.handle_nav_key_press(Qt.Key_Right) is True
            assert layout._nav_cursor_path == _entry("a.txt")["path"]
        finally:
            layout.deleteLater()

    def test_no_anchor_left_picks_last_file(self, qapp: QApplication) -> None:
        """(e) 无锚点 + Left → 最后一个文件。"""
        layout = self._dir_abc_layout(qapp)
        try:
            assert layout.handle_nav_key_press(Qt.Key_Left) is True
            assert layout._nav_cursor_path == _entry("c.txt")["path"]
        finally:
            layout.deleteLater()

    def test_empty_model_press_returns_false(self, qapp: QApplication) -> None:
        """(f) 空模型按下方向键 → False（不抛异常、无状态变化）。"""
        layout = _make_layout(qapp, [])
        try:
            assert layout.handle_nav_key_press(Qt.Key_Right) is False
            assert layout._nav_cursor_path == ""
            assert layout._nav_active is False
        finally:
            layout.deleteLater()

    def test_non_arrow_key_returns_false(self, qapp: QApplication) -> None:
        """(g) 非方向键 → False（字母/回车/空格一律原样放行）。"""
        layout = self._dir_abc_layout(qapp)
        try:
            assert layout.handle_nav_key_press(Qt.Key_A) is False
            assert layout.handle_nav_key_press(Qt.Key_Return) is False
            assert layout.handle_nav_key_press(Qt.Key_Space) is False
            assert layout._nav_active is False
            assert layout._nav_cursor_path == ""
        finally:
            layout.deleteLater()

    def test_release_without_press_or_with_other_key_returns_false(
        self, qapp: QApplication
    ) -> None:
        """(h) 无手势释放 / 异键释放 → False 且零发射；原键释放仍有效。"""
        layout = self._dir_abc_layout(qapp)
        emitted = _emit_spy(layout)
        try:
            layout.set_previewing_file(_entry("a.txt")["path"])
            # 未按下过的释放：False、零发射
            assert layout.handle_nav_key_release(Qt.Key_Right) is False
            assert emitted == []
            assert layout.handle_nav_key_press(Qt.Key_Right) is True
            # 手势进行中，异键释放：False、手势保持活动、零发射
            assert layout.handle_nav_key_release(Qt.Key_Up) is False
            assert layout._nav_active is True
            assert emitted == []
            # 原键释放：True、恰好一次发射
            assert layout.handle_nav_key_release(Qt.Key_Right) is True
            assert len(emitted) == 1
            assert emitted[0]["path"] == _entry("b.txt")["path"]
        finally:
            layout.deleteLater()

    def test_raw_int_keys_match_arrow_map(self, qapp: QApplication) -> None:
        """主窗口以 ``event.key()``（普通 int）调用：与 Qt.Key 枚举等价命中。"""
        layout = self._dir_abc_layout(qapp)
        emitted = _emit_spy(layout)
        try:
            layout.set_previewing_file(_entry("a.txt")["path"])
            assert layout.handle_nav_key_press(int(Qt.Key_Right)) is True
            assert layout._nav_cursor_path == _entry("b.txt")["path"]
            assert layout.handle_nav_key_release(int(Qt.Key_Right)) is True
            assert len(emitted) == 1
            assert emitted[0]["path"] == _entry("b.txt")["path"]
        finally:
            layout.deleteLater()

    def test_all_dirs_model_press_returns_false(self, qapp: QApplication) -> None:
        """全目录模型无文件可命中：按下 → False，不置手势状态。"""
        layout = _make_layout(
            qapp,
            [_entry("d1", True), _entry("d2", True)],
            view_mode="card",
            grid_cols=2,
        )
        try:
            assert layout.handle_nav_key_press(Qt.Key_Down) is False
            assert layout._nav_active is False
            assert layout._nav_cursor_path == ""
        finally:
            layout.deleteLater()

    def test_release_dropped_silently_when_path_left_model(
        self, qapp: QApplication
    ) -> None:
        """对抗：手势中模型被重填（光标路径已不在）→ 释放被吞但不发射。"""
        layout = self._dir_abc_layout(qapp)
        emitted = _emit_spy(layout)
        try:
            layout.set_previewing_file(_entry("a.txt")["path"])
            assert layout.handle_nav_key_press(Qt.Key_Right) is True
            # 直接重填模型（绕开 _apply_* 的自动 reset，制造"残影"手势）
            layout._file_model.set_files([_entry("z.txt")])
            assert layout.handle_nav_key_release(Qt.Key_Right) is True
            assert emitted == []
        finally:
            layout.deleteLater()


class TestNavVertical:
    """验收标准 (i)-(k)：卡片网格垂直步进、全目录目标行回退、falsy-zero 环绕。"""

    _GRID_ENTRIES: List[Dict[str, Any]] = [
        _entry("folder", True),
        _entry("a.txt"),
        _entry("b.txt"),
        _entry("c.txt"),
        _entry("d.txt"),
        _entry("e.txt"),
    ]

    def test_card_down_steps_a_real_grid_row(self, qapp: QApplication) -> None:
        """(i) cols=3：从 a（行0列1）向下 → d（行1列1），而非文件序邻居 b。"""
        layout = _make_layout(
            qapp, self._GRID_ENTRIES, view_mode="card", grid_cols=3
        )
        try:
            layout.set_previewing_file(_entry("a.txt")["path"])
            assert layout.handle_nav_key_press(Qt.Key_Down) is True
            assert layout._nav_cursor_path == _entry("d.txt")["path"]
            # 文件序步进（scan）给出的是 b——证明走的是模型行网格。
            assert layout._nav_cursor_path != _entry("b.txt")["path"]
        finally:
            layout.deleteLater()

    def test_card_up_snaps_to_nearest_row_cell(self, qapp: QApplication) -> None:
        """(i) cols=3：从 e（行1列2）向上吸附到行0最近非目录 = b。"""
        layout = _make_layout(
            qapp, self._GRID_ENTRIES, view_mode="card", grid_cols=3
        )
        try:
            layout.set_previewing_file(_entry("e.txt")["path"])
            assert layout.handle_nav_key_press(Qt.Key_Up) is True
            assert layout._nav_cursor_path == _entry("b.txt")["path"]
        finally:
            layout.deleteLater()

    def test_list_mode_down_steps_one_file(self, qapp: QApplication) -> None:
        """(i) 列表模式向下每次一个文件（连发亦然）：a→b→c。"""
        layout = _make_layout(
            qapp, self._GRID_ENTRIES, view_mode="list", grid_cols=1
        )
        try:
            layout.set_previewing_file(_entry("a.txt")["path"])
            assert layout.handle_nav_key_press(Qt.Key_Down) is True
            assert layout._nav_cursor_path == _entry("b.txt")["path"]
            assert layout.handle_nav_key_press(Qt.Key_Down) is True
            assert layout._nav_cursor_path == _entry("c.txt")["path"]
        finally:
            layout.deleteLater()

    def test_all_dirs_target_row_falls_back_to_next_file(
        self, qapp: QApplication
    ) -> None:
        """(j) cols=2、[a,b,dir,dir]：从 a 向下目标行整行皆目录 → 回退 b（非 False）。"""
        entries = [
            _entry("a.txt"),
            _entry("b.txt"),
            _entry("folder1", True),
            _entry("folder2", True),
        ]
        layout = _make_layout(qapp, entries, view_mode="card", grid_cols=2)
        try:
            layout.set_previewing_file(_entry("a.txt")["path"])
            assert layout.handle_nav_key_press(Qt.Key_Down) is True
            assert layout._nav_cursor_path == _entry("b.txt")["path"]
        finally:
            layout.deleteLater()

    def test_vertical_wrap_to_row_zero_is_preserved(
        self, qapp: QApplication
    ) -> None:
        """(k) falsy-zero 回归：cols=2、[a,b,c,d]：从 c 向下环绕到 a（行 0）。

        若实现写成 ``_grid_step_row(...) or _scan_file_row(...)``，合法结果 0
        是 falsy，会被误换成文件序邻居 d（行 3）；本用例锁定显式 None 判断。
        """
        entries = [
            _entry("a.txt"),
            _entry("b.txt"),
            _entry("c.txt"),
            _entry("d.txt"),
        ]
        layout = _make_layout(qapp, entries, view_mode="card", grid_cols=2)
        try:
            layout.set_previewing_file(_entry("c.txt")["path"])
            assert layout.handle_nav_key_press(Qt.Key_Down) is True
            assert layout._nav_cursor_path == _entry("a.txt")["path"]
            assert layout._nav_cursor_path != _entry("d.txt")["path"]
        finally:
            layout.deleteLater()
