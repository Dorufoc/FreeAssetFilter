# -*- coding: utf-8 -*-
"""框选功能单元测试（文件选择器 / 文件储存池 / 共享手势组件）。

覆盖：
- BoxSelectionGesture：拖拽阈值激活、命中集合替换回调、释放收尾、守卫兜底；
- FileSelectorLayout：左键拖拽框选更新模型选中态且不触发预览；单击清除；
  右键已选中卡片批量入池信号；右键未选中卡片单卡信号；右键空白返回上级；
- FilePoolLayout：框选命中应用/清除、右键批量移除、未选中卡片放行、
  移除后集合清理；
- FileCardDelegate：框选选中态虚线视觉、优先级与"选中态不做过渡"。

测试纪律（与 tests/unit/ui/layout/test_layouts.py 一致）：
真实构造布局（offscreen，不 show → 不触发首屏导航），事件经
``layout.eventFilter(...)`` 真实路由，视觉/几何依赖处经 monkeypatch 精确注入。

验证命令：
    python -m pytest tests/unit/ui/layout/test_box_selection.py -v
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest
from PySide6.QtCore import QEvent, QModelIndex, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QWidget

# 布局模块内部使用短路径导入（from theme import tm / components.*），
# 要求 freeassetfilter/ui 位于 sys.path——与 test_layouts.py 的 bootstrap 惯例一致。
_UI_ROOT: str = str(Path(__file__).resolve().parents[4] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from components.box_selection import BoxSelectionGesture  # noqa: E402
from components.file_card_delegate import (  # noqa: E402
    FileCardDelegate,
    _STATE_BOX_SELECTED,
    _STATE_IN_POOL,
    _STATE_PREVIEWING,
)
from components.file_list_model import FileListModel  # noqa: E402
from freeassetfilter.ui.layout.file_pool_layout import FilePoolLayout  # noqa: E402
from freeassetfilter.ui.layout.file_selector_layout import FileSelectorLayout  # noqa: E402

pytestmark = pytest.mark.unit


# =============================================================================
# 公共辅助
# =============================================================================
def _file_entry(name: str, directory: str = "C:/box") -> Dict[str, Any]:
    """构造模型/入池所需的文件信息字典。"""
    return {
        "name": name,
        "path": os.path.join(directory, name),
        "is_dir": False,
        "size": 10,
        "modified": "",
        "created": "",
        "suffix": "txt",
    }


def _mouse(
    kind: QEvent.Type,
    pos: QPoint,
    button: Qt.MouseButton,
    buttons: Qt.MouseButton,
) -> QMouseEvent:
    """构造鼠标事件（本地/全局坐标一致，便于直接投递给 eventFilter）。"""
    return QMouseEvent(kind, QPointF(pos), QPointF(pos), button, buttons, Qt.NoModifier)


def _press(pos: QPoint) -> QMouseEvent:
    return _mouse(QEvent.MouseButtonPress, pos, Qt.LeftButton, Qt.LeftButton)


def _move(pos: QPoint) -> QMouseEvent:
    return _mouse(QEvent.MouseMove, pos, Qt.NoButton, Qt.LeftButton)


def _release(pos: QPoint) -> QMouseEvent:
    return _mouse(QEvent.MouseButtonRelease, pos, Qt.LeftButton, Qt.NoButton)


def _right_release(pos: QPoint) -> QMouseEvent:
    return _mouse(QEvent.MouseButtonRelease, pos, Qt.RightButton, Qt.NoButton)


def _teardown(*widgets: Any) -> None:
    for widget in widgets:
        try:
            widget.deleteLater()
        except RuntimeError:
            continue


# =============================================================================
# BoxSelectionGesture：手势状态机
# =============================================================================
class TestBoxSelectionGesture:
    """共享手势组件：阈值、回调、收尾与守卫兜底。"""

    def test_threshold_and_lifecycle(self, qapp: QApplication) -> None:
        """未超阈值不激活；超阈值激活并回调命中集合；finish 返回是否激活过。"""
        parent = QWidget()
        hits_seen: List[set] = []
        gesture = BoxSelectionGesture(
            parent,
            overlay_parent=parent,
            hit_test=lambda rect: {1, 2},
            on_hits=hits_seen.append,
        )
        gesture.begin(QPoint(0, 0))
        assert gesture.update(QPoint(3, 3), True) is False
        assert gesture.active is False
        assert gesture.update(QPoint(60, 60), True) is True
        assert gesture.active is True
        assert hits_seen == [{1, 2}]
        assert gesture.finish(QPoint(70, 70)) is True
        assert gesture.active is False
        assert gesture.started is False
        _teardown(parent)

    def test_hits_deduplicated(self, qapp: QApplication) -> None:
        """命中集合未变化时不重复回调（拖拽期间避免无谓刷新）。"""
        parent = QWidget()
        hits_seen: List[set] = []
        gesture = BoxSelectionGesture(
            parent,
            overlay_parent=parent,
            hit_test=lambda rect: {7},
            on_hits=hits_seen.append,
        )
        gesture.begin(QPoint(0, 0))
        gesture.update(QPoint(60, 60), True)
        gesture.update(QPoint(80, 80), True)
        assert hits_seen == [{7}]
        _teardown(parent)

    def test_button_released_self_heal(self, qapp: QApplication) -> None:
        """无按键移动（释放丢失残留）时自动收尾，不残留框选态。"""
        parent = QWidget()
        gesture = BoxSelectionGesture(parent, overlay_parent=parent)
        gesture.begin(QPoint(0, 0))
        gesture.update(QPoint(60, 60), True)
        assert gesture.active is True
        gesture.update(QPoint(80, 80), False)
        assert gesture.active is False
        assert gesture.started is False
        _teardown(parent)

    def test_guard_finalizes_lost_release(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """守卫轮询发现左键已释放时，按最后位置兜底收尾（保留命中回调）。"""
        parent = QWidget()
        hits_seen: List[set] = []
        gesture = BoxSelectionGesture(
            parent,
            overlay_parent=parent,
            hit_test=lambda rect: {3},
            on_hits=hits_seen.append,
        )
        gesture.begin(QPoint(0, 0))
        gesture.update(QPoint(60, 60), True)
        monkeypatch.setattr(
            QApplication, "mouseButtons", staticmethod(lambda: Qt.NoButton)
        )
        gesture._on_guard_tick()
        assert gesture.active is False
        assert gesture.started is False
        assert hits_seen == [{3}]
        _teardown(parent)


# =============================================================================
# FileSelectorLayout：框选 / 右键
# =============================================================================
class TestSelectorBoxSelection:
    """文件选择器框选与右键批量入池。"""

    @staticmethod
    def _make_layout(qapp: QApplication) -> FileSelectorLayout:
        layout = FileSelectorLayout()
        layout.resize(800, 600)
        layout._file_model.set_files([_file_entry(f"f{i}.txt") for i in range(6)])
        return layout

    @staticmethod
    def _patch_visual_rects(layout: FileSelectorLayout, monkeypatch: pytest.MonkeyPatch) -> None:
        """以 3 列网格的固定矩形替换 view.visualRect（无需真实布局）。"""
        from PySide6.QtCore import QRect

        rects = {
            row: QRect(20 + (row % 3) * 120, 20 + (row // 3) * 120, 110, 110)
            for row in range(6)
        }
        monkeypatch.setattr(
            layout._file_list, "visualRect", lambda index: rects[index.row()]
        )

    def test_drag_selects_rows_without_preview(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """左键拖拽超阈值 → 命中行选中；释放后选中态保留；全程不触发预览。"""
        layout = self._make_layout(qapp)
        self._patch_visual_rects(layout, monkeypatch)
        previewed: List[dict] = []
        layout.file_selected.connect(previewed.append)
        viewport = layout._file_list.viewport()

        assert layout.eventFilter(viewport, _press(QPoint(10, 10))) is False
        assert layout.eventFilter(viewport, _move(QPoint(255, 130))) is True
        assert layout._file_model.get_selected_rows() == {0, 1}
        # 框选拖拽期间不触发预览
        assert previewed == []
        # 释放：手势已激活 → 消费释放事件（阻止 clicked → 预览）
        assert layout.eventFilter(viewport, _release(QPoint(255, 130))) is True
        assert layout._box_gesture.active is False
        # 选中态在释放后保留，等待右键批量操作
        assert layout._file_model.get_selected_rows() == {0, 1}
        assert previewed == []
        _teardown(layout)

    def test_drag_outside_rows_clears_selection(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """二次拖拽为替换语义：上一轮选中行在未命中时自动取消。"""
        layout = self._make_layout(qapp)
        self._patch_visual_rects(layout, monkeypatch)
        layout._file_model.set_rows_selected({0, 1, 2}, True)
        viewport = layout._file_list.viewport()
        # 拖框只覆盖 row=0（x 20~130, y 20~130），row=1/2 未被命中应取消
        layout.eventFilter(viewport, _press(QPoint(15, 15)))
        layout.eventFilter(viewport, _move(QPoint(130, 128)))
        assert layout._file_model.get_selected_rows() == {0}
        layout.eventFilter(viewport, _release(QPoint(130, 128)))
        _teardown(layout)

    def test_single_click_card_clears_selection(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """单击卡片：清除框选并触发预览（原有语义保留）。"""
        layout = self._make_layout(qapp)
        layout._file_model.set_rows_selected({0, 1}, True)
        previewed: List[dict] = []
        layout.file_selected.connect(previewed.append)
        layout._on_file_clicked(layout._file_model.index(2, 0))
        assert layout._file_model.get_selected_rows() == set()
        assert len(previewed) == 1 and previewed[0]["path"].endswith("f2.txt")
        _teardown(layout)

    def test_click_blank_clears_selection(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """未拖拽的空白单击：清除框选（不触发预览）。"""
        layout = self._make_layout(qapp)
        self._patch_visual_rects(layout, monkeypatch)
        layout._file_model.set_rows_selected({0}, True)
        monkeypatch.setattr(
            layout._file_list, "indexAt", lambda pos: QModelIndex()
        )
        viewport = layout._file_list.viewport()
        layout.eventFilter(viewport, _press(QPoint(5, 5)))
        assert layout.eventFilter(viewport, _release(QPoint(6, 6))) is False
        assert layout._file_model.get_selected_rows() == set()
        _teardown(layout)

    def test_right_click_selected_card_adds_all(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """右键已选中卡片：批量入池信号携带全部选中项，随后清除框选。"""
        layout = self._make_layout(qapp)
        layout._file_model.set_rows_selected({0, 1}, True)
        monkeypatch.setattr(
            layout._file_list, "indexAt", lambda pos: layout._file_model.index(1, 0)
        )
        received: List[list] = []
        layout.add_files_to_pool_requested.connect(received.append)
        layout._on_right_click_toggle_pool(QPoint(5, 5))
        assert len(received) == 1
        paths = sorted(info["path"] for info in received[0])
        assert len(paths) == 2
        assert paths[0].endswith("f0.txt") and paths[1].endswith("f1.txt")
        assert layout._file_model.get_selected_rows() == set()
        _teardown(layout)

    def test_right_click_selected_card_removes_all_when_all_in_pool(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """全部选中项已在池中：右键改为批量移出信号，且不发入池信号。"""
        layout = self._make_layout(qapp)
        layout._file_model.set_rows_selected({0, 1, 2}, True)
        # 模拟三项都已在储存池（sync_pool_status 归一化写入 _pool_paths）
        layout.sync_pool_status({
            _file_entry("f0.txt")["path"],
            _file_entry("f1.txt")["path"],
            _file_entry("f2.txt")["path"],
        })
        monkeypatch.setattr(
            layout._file_list, "indexAt", lambda pos: layout._file_model.index(1, 0)
        )
        added: List[list] = []
        removed: List[list] = []
        layout.add_files_to_pool_requested.connect(added.append)
        layout.remove_files_from_pool_requested.connect(removed.append)
        layout._on_right_click_toggle_pool(QPoint(5, 5))
        assert added == []
        assert len(removed) == 1 and len(removed[0]) == 3
        assert layout._file_model.get_selected_rows() == set()
        _teardown(layout)

    def test_right_click_mixed_selection_adds(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """混合选择（部分在池）：仍走批量入池分支（add-only）。"""
        layout = self._make_layout(qapp)
        layout._file_model.set_rows_selected({0, 1}, True)
        layout.sync_pool_status({_file_entry("f0.txt")["path"]})
        monkeypatch.setattr(
            layout._file_list, "indexAt", lambda pos: layout._file_model.index(1, 0)
        )
        added: List[list] = []
        removed: List[list] = []
        layout.add_files_to_pool_requested.connect(added.append)
        layout.remove_files_from_pool_requested.connect(removed.append)
        layout._on_right_click_toggle_pool(QPoint(5, 5))
        assert removed == []
        assert len(added) == 1 and len(added[0]) == 2
        assert layout._file_model.get_selected_rows() == set()
        _teardown(layout)

    def test_all_in_pool_edge_cases(self, qapp: QApplication) -> None:
        """_all_in_pool：空列表 / 空池集合 / 路径缺失均判 False。"""
        layout = self._make_layout(qapp)
        path0 = _file_entry("f0.txt")["path"]
        assert layout._all_in_pool([]) is False
        assert layout._all_in_pool([{"path": path0}]) is False
        layout.sync_pool_status({path0})
        assert layout._all_in_pool([{"path": path0}]) is True
        assert layout._all_in_pool([{"path": ""}]) is False
        assert layout._all_in_pool([{"path": path0}, {"path": "C:/box/none.txt"}]) is False
        _teardown(layout)

    def test_right_click_unselected_card_toggles_single(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """右键未选中卡片：清除框选 + 保留单卡切换信号。"""
        layout = self._make_layout(qapp)
        layout._file_model.set_rows_selected({0}, True)
        monkeypatch.setattr(
            layout._file_list, "indexAt", lambda pos: layout._file_model.index(2, 0)
        )
        toggled: List[dict] = []
        layout.toggle_pool_requested.connect(toggled.append)
        layout._on_right_click_toggle_pool(QPoint(5, 5))
        assert len(toggled) == 1 and toggled[0]["path"].endswith("f2.txt")
        assert layout._file_model.get_selected_rows() == set()
        _teardown(layout)

    def test_right_click_blank_goes_back(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """右键空白区：清除框选 + 仍返回上一级（与批量入池互不冲突）。"""
        layout = self._make_layout(qapp)
        layout._file_model.set_rows_selected({0}, True)
        monkeypatch.setattr(
            layout._file_list, "indexAt", lambda pos: QModelIndex()
        )
        back_calls: List[bool] = []
        monkeypatch.setattr(layout, "_go_back", lambda: back_calls.append(True))
        layout._on_right_click_toggle_pool(QPoint(5, 5))
        assert back_calls == [True]
        assert layout._file_model.get_selected_rows() == set()
        _teardown(layout)

    def test_clear_box_selection_idempotent(self, qapp: QApplication) -> None:
        """clear_box_selection 幂等且可重复调用。"""
        layout = self._make_layout(qapp)
        layout._file_model.set_rows_selected({0, 2}, True)
        layout.clear_box_selection()
        layout.clear_box_selection()
        assert layout._file_model.get_selected_rows() == set()
        _teardown(layout)

    def test_hit_test_stops_at_unlaid_rows(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Batched 惰性布局：遇到未布局行（无效矩形）即停止扫描。"""
        from PySide6.QtCore import QRect

        layout = self._make_layout(qapp)
        rects = {
            0: QRect(20, 20, 110, 110),
            1: QRect(140, 20, 110, 110),
            2: QRect(-1, -1, 0, 0),
            3: QRect(20, 140, 110, 110),
            4: QRect(140, 140, 110, 110),
            5: QRect(260, 140, 110, 110),
        }
        monkeypatch.setattr(
            layout._file_list, "visualRect", lambda index: rects[index.row()]
        )
        monkeypatch.setattr(
            layout._file_list, "indexAt", lambda pos: layout._file_model.index(0, 0)
        )
        hits = layout._box_hit_test(QRect(0, 0, 400, 400))
        assert hits == {0, 1}
        _teardown(layout)

    def test_hit_test_returns_empty_when_unlaid(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """全部行均无有效矩形（尚未布局）时返回空集合。"""
        from PySide6.QtCore import QRect

        layout = self._make_layout(qapp)
        empty = QRect(-1, -1, 0, 0)
        monkeypatch.setattr(
            layout._file_list, "visualRect", lambda index: empty
        )
        assert layout._box_hit_test(QRect(0, 0, 400, 400)) == set()
        _teardown(layout)


# =============================================================================
# FilePoolLayout：框选 / 右键批量移除
# =============================================================================
class TestPoolBoxSelection:
    """文件储存池框选与右键批量移除。"""

    @staticmethod
    def _make_pool(
        qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> FilePoolLayout:
        import freeassetfilter.ui.layout.file_pool_layout as fpl_mod

        # 禁用增删动画，使 add/remove 同步完成（避免异步定时器跨测试残留）
        monkeypatch.setattr(fpl_mod, "is_animation_enabled", lambda *a, **k: False)
        pool = FilePoolLayout()
        pool.resize(600, 600)
        return pool

    def test_drag_hits_apply_and_clear(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """左键拖拽超阈值：命中路径应用到卡片选中态；释放后选中保留。"""
        pool = self._make_pool(qapp, monkeypatch)
        info = _file_entry("a.txt", "C:/pool")
        pool.add_file(info)
        path = os.path.normpath(info["path"])
        card = pool._card_widgets[path]
        monkeypatch.setattr(pool, "_pool_box_hit_test", lambda rect: {path})
        viewport = pool._scroll_area.viewport()

        assert pool.eventFilter(viewport, _press(QPoint(10, 10))) is False
        # 模拟真实链路：卡片已进入按压缩放反馈
        card._pressed = True
        assert pool.eventFilter(viewport, _move(QPoint(200, 200))) is True
        assert path in pool._box_selected_paths
        assert card._is_selected is True
        # 释放：手势已激活 → 消费释放事件（阻止卡片 clicked → 预览）
        # 同时复位卡片的按压缩放反馈
        assert pool.eventFilter(viewport, _release(QPoint(200, 200))) is True
        assert path in pool._box_selected_paths
        assert card._pressed is False

        pool.clear_box_selection()
        assert pool._box_selected_paths == set()
        assert card._is_selected is False
        _teardown(pool)

    def test_right_click_selected_card_removes_all(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """右键已选中卡片：逐路径批量移除并清除框选，消费释放事件。"""
        pool = self._make_pool(qapp, monkeypatch)
        info_a = _file_entry("a.txt", "C:/pool")
        info_b = _file_entry("b.txt", "C:/pool")
        pool.add_file(info_a)
        pool.add_file(info_b)
        path_a = os.path.normpath(info_a["path"])
        path_b = os.path.normpath(info_b["path"])
        pool._apply_pool_box_hits({path_a, path_b})

        removed: List[str] = []
        monkeypatch.setattr(pool, "remove_file", removed.append)
        monkeypatch.setattr(pool, "_pool_card_path_at", lambda pos: path_a)
        viewport = pool._scroll_area.viewport()
        assert pool.eventFilter(viewport, _right_release(QPoint(10, 10))) is True
        assert sorted(removed) == sorted([path_a, path_b])
        assert pool._box_selected_paths == set()
        _teardown(pool)

    def test_right_click_unselected_card_passes_through(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """右键未选中卡片：清除框选但放行（保留现有单卡右键移除）。"""
        pool = self._make_pool(qapp, monkeypatch)
        info_a = _file_entry("a.txt", "C:/pool")
        info_b = _file_entry("b.txt", "C:/pool")
        pool.add_file(info_a)
        pool.add_file(info_b)
        path_a = os.path.normpath(info_a["path"])
        path_b = os.path.normpath(info_b["path"])
        pool._apply_pool_box_hits({path_a})

        removed: List[str] = []
        monkeypatch.setattr(pool, "remove_file", removed.append)
        monkeypatch.setattr(pool, "_pool_card_path_at", lambda pos: path_b)
        viewport = pool._scroll_area.viewport()
        assert pool.eventFilter(viewport, _right_release(QPoint(10, 10))) is False
        assert removed == []
        assert pool._box_selected_paths == set()
        _teardown(pool)

    def test_finalize_remove_cleans_selection(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """卡片最终移除后，框选集合同步剔除该路径。"""
        pool = self._make_pool(qapp, monkeypatch)
        info = _file_entry("a.txt", "C:/pool")
        pool.add_file(info)
        path = os.path.normpath(info["path"])
        pool._apply_pool_box_hits({path})
        pool._finalize_remove(path)
        assert path not in pool._box_selected_paths
        _teardown(pool)

    def test_clear_all_clears_selection(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """清空池时同步清空框选集合。"""
        pool = self._make_pool(qapp, monkeypatch)
        pool.add_file(_file_entry("a.txt", "C:/pool"))
        path = os.path.normpath("C:/pool/a.txt")
        pool._apply_pool_box_hits({path})
        pool.clear_all_without_confirmation()
        assert pool._box_selected_paths == set()
        _teardown(pool)


# =============================================================================
# FileCardDelegate：框选态视觉
# =============================================================================
class TestDelegateBoxSelectedVisual:
    """框选选中态：虚线边框、填充强度与预览优先级、无过渡。"""

    def test_visual_resolution(self, qapp: QApplication) -> None:
        delegate = FileCardDelegate()
        plain = delegate._resolve_visual(0)
        selected = delegate._resolve_visual(_STATE_BOX_SELECTED)
        pooled_selected = delegate._resolve_visual(_STATE_BOX_SELECTED | _STATE_IN_POOL)
        preview_selected = delegate._resolve_visual(_STATE_PREVIEWING | _STATE_BOX_SELECTED)

        assert plain.dashed is False
        assert selected.border_kind == "plain" and selected.dashed is True
        # 池中填充比框选填充更浓（40% > 25%）
        assert pooled_selected.dashed is True
        assert pooled_selected.bg.alpha() > selected.bg.alpha()
        # 预览流光边框优先级最高
        assert preview_selected.border_kind == "gradient"

    def test_selection_changes_skip_transition(self, qapp: QApplication) -> None:
        """涉及框选态的状态变化不做过渡动画；池中态变化仍保留过渡。"""
        model = FileListModel()
        model.set_files([_file_entry("x.txt")])
        index = model.index(0, 0)
        info = {"path": "C:/box/x.txt"}

        delegate = FileCardDelegate()
        delegate._sync_state_transition(index, info, False, False, False)
        delegate._sync_state_transition(index, info, False, False, True)
        assert delegate._transitions == {}
        delegate._sync_state_transition(index, info, True, False, True)
        assert delegate._transitions == {}

        pool_delegate = FileCardDelegate()
        pool_delegate._sync_state_transition(index, info, False, False, False)
        pool_delegate._sync_state_transition(index, info, True, False, False)
        assert 0 in pool_delegate._transitions
