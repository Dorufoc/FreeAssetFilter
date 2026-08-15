"""
FileSelectorLayout 鼠标侧键返回上级目录测试

覆盖新版文件选择器布局中：鼠标侧键（XButton1/BackButton）点击卡片区域
任意位置应触发返回上一层级目录的行为，行为与顶栏"返回上一级"按钮一致
（历史栈后退 / 回上级目录；All 视图无操作）。
"""

import os
import sys
from pathlib import Path
from typing import List

# Match the sys.path bootstrap used by sibling layout tests so that the
# ui-relative imports (`from theme import tm`, `from components.*`) resolve.
_UI_ROOT = str(Path(__file__).resolve().parents[4] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from components.file_list_model import FileNameRole
from components.styled_context_menu import StyledContextMenu
from freeassetfilter.ui.layout.file_selector_layout import FileSelectorLayout


@pytest.fixture
def selector(qapp, monkeypatch) -> FileSelectorLayout:
    """创建 FileSelectorLayout 实例并在测试结束后清理。

    - 关闭 showEvent 自动恢复上次路径（避免读取真实 last_path.json）
    - 屏蔽 last_path 读写，防止测试污染用户数据目录
    """
    layout = FileSelectorLayout()
    layout._first_show = False  # 禁止 showEvent 触发 _init_navigation
    monkeypatch.setattr(layout, "_save_last_path", lambda path: None)
    monkeypatch.setattr(layout, "_clear_last_path", lambda: None)
    layout.resize(420, 620)
    layout.show()
    qapp.processEvents()
    try:
        yield layout
    finally:
        layout.close()
        layout.deleteLater()


def _send_side_button_press(layout: FileSelectorLayout, pos) -> None:
    """向文件列表 viewport 发送鼠标侧键（XButton1）按下事件。"""
    local_pos = QPointF(pos.x(), pos.y())
    event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        local_pos,
        local_pos,
        Qt.MouseButton.XButton1,
        Qt.MouseButton.XButton1,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(layout._file_list.viewport(), event)


def _navigate(layout: FileSelectorLayout, path: str) -> None:
    """导航到指定目录（同步加载，无需等待异步任务）。"""
    layout._navigate_to(path)


class TestSideButtonGoBack:
    """鼠标侧键返回上级目录行为。"""

    def test_xbutton1_goes_back_to_parent(self, selector, tmp_path) -> None:
        """进入子目录后按侧键：返回上级目录。"""
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        _navigate(selector, str(tmp_path))
        assert selector._current_path == str(tmp_path)

        _navigate(selector, str(subdir))
        assert selector._current_path == str(subdir)

        # 在卡片区域任意位置按下侧键（pos 落在列表内容区）
        _send_side_button_press(selector, selector._file_list.viewport().rect().center())

        assert selector._current_path == str(tmp_path), "侧键应返回上级目录"

    def test_xbutton1_does_not_trigger_card_click(self, selector, tmp_path) -> None:
        """卡片上方按侧键：不触发卡片点击，仅返回上级目录。"""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        file_a = tmp_path / "a.txt"
        file_a.write_text("hello", encoding="utf-8")
        (tmp_path / "b.txt").write_text("world", encoding="utf-8")

        _navigate(selector, str(tmp_path))
        _navigate(selector, str(subdir))
        assert selector._current_path == str(subdir)

        clicked_rows: List[int] = []
        selector._file_list.clicked.connect(lambda index: clicked_rows.append(index.row()))

        # pos 取 viewport 左上角附近（首个卡片区域）
        _send_side_button_press(selector, QPointF(20, 20))

        assert clicked_rows == [], "侧键不应触发卡片点击信号"
        assert selector._current_path == str(tmp_path), "侧键应返回上级目录"

    def test_xbutton1_in_all_view_is_noop(self, selector, qapp) -> None:
        """All 视图按侧键：无任何副作用（仍在 All 视图）。"""
        assert selector._current_path == "All"
        _send_side_button_press(selector, selector._file_list.viewport().rect().center())
        qapp.processEvents()
        assert selector._current_path == "All"
        assert selector._nav_history == []

    def test_xbutton1_from_history_backtracks(self, selector, tmp_path) -> None:
        """多次导航后按侧键：沿历史栈后退，而非直接跳父目录。"""
        sub_a = tmp_path / "a"
        sub_b = tmp_path / "b"
        sub_a.mkdir()
        sub_b.mkdir()

        _navigate(selector, str(tmp_path))
        _navigate(selector, str(sub_a))
        _navigate(selector, str(sub_b))
        assert selector._current_path == str(sub_b)

        _send_side_button_press(selector, selector._file_list.viewport().rect().center())

        assert selector._current_path == str(sub_a), "侧键应沿历史栈后退一步"


class TestSortMenu:
    """排序下拉菜单：连续多次切换排序模式均应生效（回归测试）。

    回归背景：StyledContextMenu 曾直接把 ``callback`` 连接到
    ``QAction.triggered(bool)``，checkable 菜单项触发时会把勾选状态
    ``True`` 作为实参传入 ``lambda m=mode: ...``，覆盖绑定的 mode，
    导致 `_sort_mode` 恒等于 1（名称↓），二次选择不再生效。
    """

    def _open_sort_menu(self, selector, monkeypatch):
        """以真实生产路径弹出排序菜单（拦截 exec 避免阻塞）。"""
        captured: dict = {}

        def fake_exec(self, pos) -> None:
            captured.setdefault("menu", self)

        monkeypatch.setattr(StyledContextMenu, "exec", fake_exec)
        selector._show_sort_menu()
        return captured["menu"]

    def _model_names(self, selector) -> List[str]:
        """按当前模型顺序返回文件名列。"""
        model = selector._file_model
        return [
            model.data(model.index(row, 0), FileNameRole)
            for row in range(model.rowCount())
        ]

    def _make_files(self, tmp_path) -> None:
        """构造名称序、大小序、修改时序互不相同的 3 个文件。"""
        (tmp_path / "a.txt").write_text("x" * 10, encoding="utf-8")     # 10B，最早修改
        (tmp_path / "b.bin").write_text("x" * 2000, encoding="utf-8")   # 2000B，次新
        (tmp_path / "c.log").write_text("x" * 300, encoding="utf-8")    # 300B，最新修改
        base = 1_700_000_000
        os.utime(tmp_path / "a.txt", (base, base))
        os.utime(tmp_path / "b.bin", (base + 60, base + 60))
        os.utime(tmp_path / "c.log", (base + 120, base + 120))

    def test_sort_menu_switching_multiple_times_applies(
        self, selector, monkeypatch, tmp_path
    ) -> None:
        """依次切换 名称↓ → 大小↓ → 修改时间↓ → 大小↑ → 修改时间↑，
        每次触发后排序模式与列表顺序都应真实变化。"""
        self._make_files(tmp_path)
        _navigate(selector, str(tmp_path))

        menu = self._open_sort_menu(selector, monkeypatch)
        actions = menu.actions()
        assert len(actions) == 8, "排序菜单应包含 8 种模式"

        # 1) 名称↓
        actions[1].trigger()
        assert selector._sort_mode == 1
        assert self._model_names(selector) == ["c.log", "b.bin", "a.txt"]

        # 2) 大小↓
        actions[4].trigger()
        assert selector._sort_mode == 4
        assert self._model_names(selector) == ["b.bin", "c.log", "a.txt"]

        # 3) 修改时间↓（c.log 最新）
        actions[2].trigger()
        assert selector._sort_mode == 2
        assert self._model_names(selector) == ["c.log", "b.bin", "a.txt"]

        # 4) 大小↑
        actions[5].trigger()
        assert selector._sort_mode == 5
        assert self._model_names(selector) == ["a.txt", "c.log", "b.bin"]

        # 5) 修改时间↑（a.txt 最早）
        actions[3].trigger()
        assert selector._sort_mode == 3
        assert self._model_names(selector) == ["a.txt", "b.bin", "c.log"]
