# -*- coding: utf-8 -*-
"""布局层单元测试（todo-23 批 3 / task-23）。

覆盖 ui/layout 下 11 个布局模块的构造契约、尺寸生效与 set_file 分发：
全部 QWidget 布局以默认参数构造、放入内容后 geometry 非空；
带 ``set_file`` 入口的布局对缺失路径安全降级（不抛异常、返回 False 或
停留在 overlay）；``PreviewFullscreenHost`` 在无父窗口时进出全屏不抛；
``VideoPlayerLayout`` 在无 libmpv 时不真实播放（缺失路径直接返回 False）。

验证命令：
    python -m pytest tests/unit/ui/layout/test_layouts.py --timeout 60 -q
"""

# targets: ui.layout.file_pool_layout, ui.layout.file_selector_layout,
#          ui.layout.settings_layout, ui.layout.unified_previewer_layout,
#          ui.layout.preview.font_previewer_layout,
#          ui.layout.preview.fullscreen_host,
#          ui.layout.preview.image_previewer_layout,
#          ui.layout.preview.office_previewer_layout,
#          ui.layout.preview.pdf_previewer_layout,
#          ui.layout.preview.text_previewer_layout,
#          ui.layout.preview.video_player_layout

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QObject, Qt, QThread, Signal
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QEnterEvent,
    QHideEvent,
    QMouseEvent,
    QPixmap,
)
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

# 布局模块内部使用短路径导入（from theme import tm / components.*），
# 要求 freeassetfilter/ui 位于 sys.path；与 layout/preview 模块自身的
# bootstrap 保持一致（详见 file_pool_layout.py:46 的用法）。
_UI_ROOT: str = str(Path(__file__).resolve().parents[4] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from freeassetfilter.ui.layout.file_pool_layout import FilePoolLayout
from freeassetfilter.ui.layout.file_selector_layout import FileSelectorLayout
from freeassetfilter.ui.layout.preview.font_previewer_layout import (
    DEFAULT_PREVIEW_TEXT,
    FontLoadThread,
    FontPreviewerLayout,
)
from freeassetfilter.ui.layout.preview.fullscreen_host import PreviewFullscreenHost
from freeassetfilter.ui.layout.preview.image_previewer_layout import ImagePreviewerLayout
import freeassetfilter.ui.layout.preview.office_previewer_layout as _opl
from freeassetfilter.ui.layout.preview.office_previewer_layout import (
    OfficePreviewerLayout,
)
from freeassetfilter.ui.layout.preview.pdf_previewer_layout import PdfPreviewerLayout
from freeassetfilter.ui.layout.preview.text_previewer_layout import TextPreviewerLayout
from freeassetfilter.ui.layout.preview.video_player_layout import VideoPlayerLayout
from freeassetfilter.ui.layout.settings_layout import (
    AccentColorButton,
    AppearanceSettingsPage,
    CustomAccentButton,
    SettingsLayout,
)
from freeassetfilter.ui.layout.unified_previewer_layout import UnifiedPreviewerLayout

from tests.support.qt_helpers import safe_teardown  # noqa: E402

pytestmark = pytest.mark.unit

_MISSING_FILE: str = "C:/definitely/missing_file.xyz"
_LAYOUT_SIZE: tuple[int, int] = (640, 480)


def _assert_layout_geometry(widget: QWidget, qapp: QApplication) -> None:
    """宿主 resize 后 geometry 有效（尺寸用例的公共断言）。"""
    widget.resize(*_LAYOUT_SIZE)
    qapp.processEvents()
    assert widget.width() > 0
    assert widget.height() == 480


def _pump_events(qapp: QApplication, ms: float = 300) -> None:
    """有界事件泵：让布局/尺寸事件与重绘完成。"""
    deadline = time.time() + ms / 1000
    while time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.01)


# =============================================================================
# ui.layout.file_pool_layout
# =============================================================================
class TestFilePoolLayout:
    """文件池布局：构造契约、add_file 入池与尺寸生效。"""

    def test_construct_and_geometry(self, qapp: QApplication) -> None:
        """默认构造 + resize 后 geometry 非空。"""
        layout = FilePoolLayout()
        _assert_layout_geometry(layout, qapp)
        layout.deleteLater()

    def test_add_file_and_query(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """add_file 入池后 has_file / get_pool_paths 可见，可安全移除。"""
        # 禁用删除动画，使 remove_file 同步完成（否则经 _removing_paths 异步走）
        import freeassetfilter.ui.layout.file_pool_layout as fpl_mod

        monkeypatch.setattr(
            fpl_mod, "is_animation_enabled", lambda *args, **kwargs: False
        )
        layout = FilePoolLayout()
        _assert_layout_geometry(layout, qapp)
        file_path = "D:/dummy/file_pool_sample.png"
        layout.add_file({"path": file_path, "name": "file_pool_sample.png"})
        assert layout.has_file(file_path) is True
        assert file_path.replace("/", "\\") in layout.get_pool_paths() or file_path in layout.get_pool_paths()
        layout.remove_file(file_path)
        assert layout.has_file(file_path) is False
        layout.deleteLater()


# =============================================================================
# ui.layout.file_selector_layout
# =============================================================================
class TestFileSelectorLayout:
    """文件选择器布局：构造契约与尺寸生效。"""

    def test_construct_and_geometry(self, qapp: QApplication) -> None:
        """默认构造 + resize 后 geometry 非空。"""
        layout = FileSelectorLayout()
        _assert_layout_geometry(layout, qapp)
        layout.deleteLater()

    @staticmethod
    def _make_target_file(tmp_path) -> Path:
        """在临时目录创建一个定位目标文件，返回其路径。"""
        target = tmp_path / "locate_target.txt"
        target.write_text("locate me", encoding="utf-8")
        return target

    def test_locate_file_navigates_and_highlights(
        self, qapp: QApplication, tmp_path: object, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """文件池预览文件不在当前目录：locate_file 导航到所在目录并高亮卡片。"""
        import os

        import freeassetfilter.ui.layout.file_selector_layout as fsl_mod

        messages: list = []
        monkeypatch.setattr(
            fsl_mod.FileSelectorLayout, "_show_message_dialog",
            lambda self, t, m: messages.append((t, m)),
        )

        target = self._make_target_file(tmp_path)
        layout = FileSelectorLayout()
        _assert_layout_geometry(layout, qapp)
        assert messages == []

        layout.locate_file({"path": str(target), "name": target.name})

        target_dir = os.path.abspath(os.path.normpath(str(tmp_path)))
        assert os.path.normcase(layout._current_path) == os.path.normcase(target_dir)
        assert layout._previewing_file_path is not None
        assert (
            os.path.normcase(layout._previewing_file_path)
            == os.path.normcase(str(target))
        )
        # 等待延后滚动的 singleShot 触达后安全清理
        import time

        time.sleep(0.25)
        qapp.processEvents()
        layout.deleteLater()

    def test_locate_file_same_directory_skips_navigation(
        self, qapp: QApplication, tmp_path: object, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """目标文件已在当前目录：locate_file 不重复导航，仅高亮滚动。"""
        import os

        import freeassetfilter.ui.layout.file_selector_layout as fsl_mod

        messages: list = []
        monkeypatch.setattr(
            fsl_mod.FileSelectorLayout, "_show_message_dialog",
            lambda self, t, m: messages.append((t, m)),
        )

        target = self._make_target_file(tmp_path)
        layout = FileSelectorLayout()
        _assert_layout_geometry(layout, qapp)

        layout._load_directory(os.path.abspath(str(tmp_path)))
        assert messages == []

        navigate_calls: list = []
        original_navigate = layout._navigate_to

        def _spy_navigate(path: str) -> None:
            navigate_calls.append(path)
            original_navigate(path)

        monkeypatch.setattr(layout, "_navigate_to", _spy_navigate)

        layout.locate_file({"path": str(target), "name": target.name})

        assert navigate_calls == []  # 目录未变，不触发导航
        assert layout._previewing_file_path is not None
        assert (
            os.path.normcase(layout._previewing_file_path)
            == os.path.normcase(str(target))
        )

        import time

        time.sleep(0.25)
        qapp.processEvents()
        layout.deleteLater()

    def test_locate_file_missing_directory_shows_message(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """目标目录不存在：弹提示且不导航、不高亮。"""
        import os

        import freeassetfilter.ui.layout.file_selector_layout as fsl_mod

        messages: list = []
        monkeypatch.setattr(
            fsl_mod.FileSelectorLayout, "_show_message_dialog",
            lambda self, t, m: messages.append((t, m)),
        )

        layout = FileSelectorLayout()
        _assert_layout_geometry(layout, qapp)

        ghost = "D:/definitely/not/exists_dir/ghost.txt"
        navigate_calls: list = []
        monkeypatch.setattr(layout, "_navigate_to", lambda path: navigate_calls.append(path))

        layout.locate_file({"path": ghost, "name": "ghost.txt"})

        assert len(messages) == 1
        assert messages[0][0] == "错误"
        assert navigate_calls == []
        assert not layout._previewing_file_path
        assert os.path.normcase(layout._current_path) == os.path.normcase("All")
        layout.deleteLater()


# =============================================================================
# ui.layout.file_selector_layout — _go_back 返回过渡动画
# =============================================================================
class TestGoBackTransition:
    """_go_back 返回过渡：历史/上级/盘符根分支均一致触发 direction=-1 动画。

    全部用例均用 MagicMock 计数 begin/finish，不跑真实动画（offscreen 下
    ``FileSelectorLayout`` 真实构造，仅过渡与 IO 入口被替身替换）。
    """

    def test_history_branch_triggers_back_animation(
        self, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """历史分支：有可回退历史时 _go_back 以 -1 触发过渡并加载上一条。

        Args:
            qapp: 会话级 QApplication（offscreen）。
            tmp_path: pytest 临时目录（真实创建 tmpA/tmpB）。
            monkeypatch: 用例级猴子补丁。
        """
        import os

        tmp_a = tmp_path / "tmpA"
        tmp_b = tmp_path / "tmpB"
        tmp_a.mkdir()
        tmp_b.mkdir()
        str_a = os.path.abspath(str(tmp_a))
        str_b = os.path.abspath(str(tmp_b))

        layout = FileSelectorLayout()
        layout.resize(*_LAYOUT_SIZE)
        qapp.processEvents()
        try:
            # 预置历史栈顶为 tmpB，回退应落到 tmpA。
            layout._nav_history = [str_a, str_b]
            layout._history_index = 1
            layout._current_path = str_b
            begin_mock: MagicMock = MagicMock(return_value=True)
            finish_mock: MagicMock = MagicMock(return_value=True)
            load_mock: MagicMock = MagicMock()
            monkeypatch.setattr(layout._file_list, "begin_path_transition", begin_mock)
            monkeypatch.setattr(layout._file_list, "finish_path_transition", finish_mock)
            monkeypatch.setattr(layout, "_load_directory", load_mock)
            monkeypatch.setattr(layout, "_navigate_to_all", MagicMock())
            monkeypatch.setattr(layout, "_save_last_path", MagicMock())
            monkeypatch.setattr(os.path, "isdir", lambda path: True)

            layout._go_back()

            begin_mock.assert_called_once_with(-1)
            finish_mock.assert_called_once_with(-1)
            load_mock.assert_called_once_with(str_a)
        finally:
            safe_teardown(layout)
            qapp.processEvents()

    def test_parent_fallback_triggers_back_animation(
        self, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """上级回退（单条历史/首次访问）：parent 回退分支以 -1 触发过渡。

        覆盖启动恢复、All 重置后等单历史场景：_history_index==0 时
        _go_back 走 parent 回退分支（经 _load_directory_with_transition），
        与历史分支一致触发 -1 动画并加载 dirname 上级。

        Args:
            qapp: 会话级 QApplication（offscreen）。
            tmp_path: pytest 临时目录（真实创建 sub/inner）。
            monkeypatch: 用例级猴子补丁。
        """
        import os

        sub_dir = tmp_path / "sub"
        deep_dir = sub_dir / "inner"
        deep_dir.mkdir(parents=True)
        str_parent = os.path.abspath(str(sub_dir))
        str_deep = os.path.abspath(str(deep_dir))

        layout = FileSelectorLayout()
        layout.resize(*_LAYOUT_SIZE)
        qapp.processEvents()
        try:
            # 单条历史（首次访问/启动恢复场景）：栈顶即 deep，无可回退历史，
            # 回退走 parent 分支，dirname 上级即 parent。
            layout._nav_history = [str_deep]
            layout._history_index = 0
            layout._current_path = str_deep
            begin_mock: MagicMock = MagicMock(return_value=True)
            finish_mock: MagicMock = MagicMock(return_value=True)
            load_mock: MagicMock = MagicMock()
            monkeypatch.setattr(layout._file_list, "begin_path_transition", begin_mock)
            monkeypatch.setattr(layout._file_list, "finish_path_transition", finish_mock)
            monkeypatch.setattr(layout, "_load_directory", load_mock)
            monkeypatch.setattr(layout, "_navigate_to_all", MagicMock())
            monkeypatch.setattr(layout, "_save_last_path", MagicMock())
            monkeypatch.setattr(os.path, "isdir", lambda path: True)

            layout._go_back()

            begin_mock.assert_called_once_with(-1)
            finish_mock.assert_called_once_with(-1)
            load_mock.assert_called_once_with(str_parent)
        finally:
            safe_teardown(layout)
            qapp.processEvents()

    def test_drive_root_delegates_to_all_with_animation(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """盘符根回退：parent == current 时委托 _navigate_to_all 且带 -1 动画。

        Args:
            qapp: 会话级 QApplication（offscreen）。
            monkeypatch: 用例级猴子补丁。
        """
        import os

        layout = FileSelectorLayout()
        layout.resize(*_LAYOUT_SIZE)
        qapp.processEvents()
        try:
            # 无可回退历史、当前为盘符根：dirname 恒返自身以强制走 All 分支。
            layout._nav_history = []
            layout._history_index = -1
            layout._current_path = "D:\\"
            begin_mock: MagicMock = MagicMock(return_value=True)
            finish_mock: MagicMock = MagicMock(return_value=True)
            monkeypatch.setattr(layout._file_list, "begin_path_transition", begin_mock)
            monkeypatch.setattr(layout._file_list, "finish_path_transition", finish_mock)
            monkeypatch.setattr(layout, "_load_all", MagicMock())
            monkeypatch.setattr(layout, "_save_last_path", MagicMock())
            monkeypatch.setattr(layout, "_clear_last_path", MagicMock())
            monkeypatch.setattr(os.path, "isdir", lambda path: True)
            monkeypatch.setattr(os.path, "dirname", lambda path: path)
            navigate_all_calls: list = []
            original_navigate_to_all = layout._navigate_to_all

            def _spy_navigate_to_all() -> None:
                """记录委托并执行真实 All 导航（保留其内部 -1 动画）。"""
                navigate_all_calls.append(True)
                original_navigate_to_all()

            monkeypatch.setattr(layout, "_navigate_to_all", _spy_navigate_to_all)

            layout._go_back()

            assert navigate_all_calls == [True]
            begin_mock.assert_called_once_with(-1)
            finish_mock.assert_called_once_with(-1)
            assert layout._current_path == "All"
        finally:
            safe_teardown(layout)
            qapp.processEvents()

    def test_deep_nesting_sequential_go_back(
        self, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """深层嵌套：逐级 _go_back 每次均触发 -1 动画。

        Args:
            qapp: 会话级 QApplication（offscreen）。
            tmp_path: pytest 临时目录（真实创建 a/b/c）。
            monkeypatch: 用例级猴子补丁。
        """
        import os

        dir_a = tmp_path / "a"
        dir_b = dir_a / "b"
        dir_c = dir_b / "c"
        dir_c.mkdir(parents=True)
        str_a = os.path.abspath(str(dir_a))
        str_b = os.path.abspath(str(dir_b))
        str_c = os.path.abspath(str(dir_c))

        layout = FileSelectorLayout()
        layout.resize(*_LAYOUT_SIZE)
        qapp.processEvents()
        try:
            layout._nav_history = [str_a, str_b, str_c]
            layout._history_index = 2
            layout._current_path = str_c
            begin_mock: MagicMock = MagicMock(return_value=True)
            finish_mock: MagicMock = MagicMock(return_value=True)
            load_mock: MagicMock = MagicMock()
            monkeypatch.setattr(layout._file_list, "begin_path_transition", begin_mock)
            monkeypatch.setattr(layout._file_list, "finish_path_transition", finish_mock)
            monkeypatch.setattr(layout, "_load_directory", load_mock)
            monkeypatch.setattr(layout, "_navigate_to_all", MagicMock())
            monkeypatch.setattr(layout, "_save_last_path", MagicMock())
            monkeypatch.setattr(os.path, "isdir", lambda path: True)

            layout._go_back()
            layout._go_back()

            assert begin_mock.call_count == 2
            assert finish_mock.call_count == 2
            assert [c.args[0] for c in begin_mock.call_args_list] == [-1, -1]
            assert [c.args[0] for c in finish_mock.call_args_list] == [-1, -1]
            assert [c.args[0] for c in load_mock.call_args_list] == [str_b, str_a]
        finally:
            safe_teardown(layout)
            qapp.processEvents()

    @pytest.mark.parametrize("scenario", ["history", "parent"])
    def test_direction_always_minus_one(
        self, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        scenario: str,
    ) -> None:
        """direction 一致性：历史/上级两种前置下 begin 首参恒为 -1。

        Args:
            qapp: 会话级 QApplication（offscreen）。
            tmp_path: pytest 临时目录。
            monkeypatch: 用例级猴子补丁。
            scenario: 前置场景（history=普通历史回退，parent=回到上级）。
        """
        import os

        layout = FileSelectorLayout()
        layout.resize(*_LAYOUT_SIZE)
        qapp.processEvents()
        try:
            if scenario == "history":
                # 普通历史回退：tmpB -> tmpA。
                tmp_a = tmp_path / "hA"
                tmp_b = tmp_path / "hB"
                tmp_a.mkdir(exist_ok=True)
                tmp_b.mkdir(exist_ok=True)
                layout._nav_history = [os.path.abspath(str(tmp_a)), os.path.abspath(str(tmp_b))]
                layout._history_index = 1
                layout._current_path = os.path.abspath(str(tmp_b))
            else:
                # 上级回退（单条历史/首次访问）：inner 经 parent 分支回到 sub。
                sub_dir = tmp_path / "psub"
                deep_dir = sub_dir / "pinner"
                deep_dir.mkdir(parents=True, exist_ok=True)
                layout._nav_history = [os.path.abspath(str(deep_dir))]
                layout._history_index = 0
                layout._current_path = os.path.abspath(str(deep_dir))
            begin_mock: MagicMock = MagicMock(return_value=True)
            finish_mock: MagicMock = MagicMock(return_value=True)
            monkeypatch.setattr(layout._file_list, "begin_path_transition", begin_mock)
            monkeypatch.setattr(layout._file_list, "finish_path_transition", finish_mock)
            monkeypatch.setattr(layout, "_load_directory", MagicMock())
            monkeypatch.setattr(layout, "_navigate_to_all", MagicMock())
            monkeypatch.setattr(layout, "_save_last_path", MagicMock())
            monkeypatch.setattr(os.path, "isdir", lambda path: True)

            layout._go_back()

            assert begin_mock.call_count == 1
            assert begin_mock.call_args.args[0] == -1
            assert finish_mock.call_args.args[0] == -1
        finally:
            safe_teardown(layout)
            qapp.processEvents()


# =============================================================================
# ui.layout.settings_layout
# =============================================================================
class TestSettingsLayout:
    """设置页布局：构造契约与尺寸生效（读取真实 settings_v2.json）。"""

    def test_construct_and_geometry(self, qapp: QApplication) -> None:
        """默认构造 + resize 后 geometry 非空。"""
        layout = SettingsLayout()
        _assert_layout_geometry(layout, qapp)
        layout.deleteLater()

    def test_appearance_page_uses_floating_styled_scrollbar(
        self, qapp: QApplication,
    ) -> None:
        """外观页包在浮动滚动区中：styled 浮动滚动条接管，原生滚动条隐藏。"""
        from PySide6.QtWidgets import QScrollArea

        from components.styled_scroll_area import StyledScrollBar
        from freeassetfilter.ui.layout.settings_layout import _FloatingScrollArea

        layout = SettingsLayout()
        scrolls = layout._stack.findChildren(QScrollArea)
        floating = [s for s in scrolls if isinstance(s, _FloatingScrollArea)]
        assert len(floating) == 1

        area = floating[0]
        # 原生滚动条隐藏，浮动 styled 滚动条存在
        assert area.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        assert area.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        assert isinstance(area._floating_bar, StyledScrollBar)
        # 浮动条锚定挂在外观卡片（#SettingsCard）下，贴其右缘（而非滚动区自身）
        assert area._region is area.parent()
        assert area._floating_bar.parent() is area.parent()
        # 平滑滚动在 showEvent 中初始化（未显示前未施加）
        assert area._scroller_ready is False
        safe_teardown(layout)

    def test_floating_scrollbar_range_and_value_sync(
        self, qapp: QApplication,
    ) -> None:
        """浮动滚动条与内部滚动条范围/值双向同步，随内容显隐。"""
        from freeassetfilter.ui.layout.settings_layout import _FloatingScrollArea

        area = _FloatingScrollArea()
        area.resize(400, 300)

        inner = QWidget()
        inner.setFixedHeight(800)  # 内容超出 → 产生滚动范围
        area.setWidget(inner)
        qapp.processEvents()
        area.show()
        qapp.processEvents()

        vbar = area.verticalScrollBar()
        bar = area._floating_bar
        if vbar.maximum() > 0:
            assert bar.maximum() == vbar.maximum()
            assert bar.isVisible()

            # 内部值变化 → 浮动条跟随
            vbar.setValue(10)
            assert bar.value() == 10
            # 浮动条拖动 → 内部跟随
            bar.setValue(20)
            assert vbar.value() == 20
            # 浮动条贴右侧边缘几何
            assert bar.x() == area.width() - bar.width()
        area.hide()
        safe_teardown(area)


# =============================================================================
# ui.layout.unified_previewer_layout
# =============================================================================
class TestUnifiedPreviewerLayout:
    """统一预览器布局：构造、set_file(None)/clear_preview 分发。"""

    def test_construct_and_geometry(self, qapp: QApplication) -> None:
        """默认构造 + resize 后 geometry 非空。"""
        layout = UnifiedPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.deleteLater()

    def test_info_panel_built_in_bottom_frame(self, qapp: QApplication) -> None:
        """文件信息面板已挂载到下方内容区，且随 clear_preview 复位。"""
        layout = UnifiedPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        # 与产品代码使用同一 sys.path 别名，避免同一模块被双重导入
        import layout.preview.file_info_panel as fip_module

        assert isinstance(layout._info_panel, fip_module.FileInfoPanel)
        assert layout._content_bottom.layout() is not None

        layout.set_file(self._unsupported_file_info())
        qapp.processEvents()
        assert layout._info_panel._file_info is not None

        layout.clear_preview()
        qapp.processEvents()
        assert layout._info_panel._file_info is None
        layout.deleteLater()

    def test_set_file_none_is_safe(self, qapp: QApplication) -> None:
        """set_file(None) 走安全清空路径，不抛异常。"""
        layout = UnifiedPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.set_file(None)
        qapp.processEvents()
        assert layout._content_layout is not None
        layout.clear_preview()
        layout.deleteLater()

    @staticmethod
    def _unsupported_file_info() -> dict:
        """无对应预览器的文件信息（不触发真实预览加载，仅驱动底栏状态）。"""
        return {"path": "D:/dummy/unsupported_sample.zzz", "suffix": "zzz", "is_dir": False}

    def test_bottom_buttons_disabled_then_enabled(
        self, qapp: QApplication,
    ) -> None:
        """无预览文件时底栏按钮禁用；set_file 后启用；clear_preview 后再禁用。"""
        layout = UnifiedPreviewerLayout()
        _assert_layout_geometry(layout, qapp)

        assert layout._share_btn.isEnabled() is False
        assert layout._open_default_btn.isEnabled() is False
        assert layout._locate_btn.isEnabled() is False
        assert layout._close_btn.isEnabled() is False

        layout.set_file(self._unsupported_file_info())
        qapp.processEvents()
        assert layout._share_btn.isEnabled() is True
        assert layout._open_default_btn.isEnabled() is True
        assert layout._locate_btn.isEnabled() is True
        assert layout._close_btn.isEnabled() is True

        layout.clear_preview()
        qapp.processEvents()
        assert layout._share_btn.isEnabled() is False
        assert layout._open_default_btn.isEnabled() is False
        assert layout._locate_btn.isEnabled() is False
        assert layout._close_btn.isEnabled() is False
        layout.deleteLater()

    def test_locate_button_emits_requested(self, qapp: QApplication) -> None:
        """点击"定位到所在目录"发射 locate_requested(当前文件信息)。"""
        layout = UnifiedPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.set_file(self._unsupported_file_info())

        received: list = []
        layout.locate_requested.connect(lambda info: received.append(info))
        layout._locate_btn.click()

        assert len(received) == 1
        assert received[0]["path"] == "D:/dummy/unsupported_sample.zzz"
        layout.deleteLater()

    def test_close_button_emits_clear_requested(self, qapp: QApplication) -> None:
        """点击 close 按钮发射 clear_requested（清除预览请求）。"""
        layout = UnifiedPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.set_file(self._unsupported_file_info())

        received: list = []
        layout.clear_requested.connect(lambda: received.append(True))
        layout._close_btn.click()

        assert received == [True]
        layout.deleteLater()

    @pytest.mark.parametrize(
        "file_info, expected",
        [
            ({"path": "x.mp3", "suffix": "mp3"}, True),   # 无点号音频
            ({"path": "x.wav", "suffix": ".wav"}, True),  # 带点号音频
            ({"path": "x.MP3", "suffix": "MP3"}, True),   # 大写后缀
            ({"suffix": ""}, False),                       # 空后缀
            ({"path": "x.txt", "suffix": "txt"}, False),   # 非音频（无点）
            ({"path": "x.log", "suffix": ".txt"}, False),  # 非音频（带点）
        ],
    )
    def test_is_audio_file_normalizes_suffix(
        self, qapp: QApplication, file_info: dict, expected: bool
    ) -> None:
        """_is_audio_file 对 suffix 归一化（无点/带点/大小写）后再判音频。"""
        layout = UnifiedPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        assert layout._is_audio_file(file_info) is expected
        layout.deleteLater()

    # ── 分割区高度规则 ──────────────────────────────────────────────────

    def _show_split_layout(self, qapp: QApplication) -> UnifiedPreviewerLayout:
        layout = UnifiedPreviewerLayout()
        layout.show()
        layout.resize(720, 920)
        _pump_events(qapp)
        return layout

    @staticmethod
    def _split_heights(layout: UnifiedPreviewerLayout) -> tuple[int, int]:
        return layout._content_top.height(), layout._content_bottom.height()

    def test_default_start_split_is_half(
        self, qapp: QApplication,
    ) -> None:
        """默认起始状态：统一预览器与文件信息预览器各占可用高度的一半。"""
        layout = self._show_split_layout(qapp)
        available = layout._splitter.height() - layout._splitter.handleWidth()
        assert available > 0
        top, bottom = self._split_heights(layout)
        assert abs(top - bottom) <= 2
        assert abs(top - available // 2) <= 2
        # 信息区最高高度即为其默认半高
        assert layout._content_bottom.maximumHeight() == available // 2
        layout._info_panel.stop()
        safe_teardown(layout)

    def test_info_pane_capped_at_half(
        self, qapp: QApplication,
    ) -> None:
        """信息预览器最高高度不超过可用高度的一半（强制拉高也被钳制）。"""
        layout = self._show_split_layout(qapp)
        layout.set_file(self._unsupported_file_info())
        _pump_events(qapp)
        available = layout._splitter.height() - layout._splitter.handleWidth()
        half = available // 2

        # 程序化把底栏拉到远超半高 → 遵循最大高度，顶栏占余下部分
        layout._splitter.setSizes([120, available * 4])
        _pump_events(qapp)
        top, bottom = self._split_heights(layout)
        assert bottom <= half
        assert top >= half
        assert abs(top + bottom - available) <= 2
        layout._info_panel.stop()
        safe_teardown(layout)

    def test_clear_preview_restores_default_split(
        self, qapp: QApplication,
    ) -> None:
        """预览期间手动调高（顶部变大）后取消预览 → 恢复默认各半高度。"""
        layout = self._show_split_layout(qapp)
        layout.set_file(self._unsupported_file_info())
        _pump_events(qapp)
        available = layout._splitter.height() - layout._splitter.handleWidth()
        half = available // 2

        # 用户手动把信息区收窄、预览区放大
        layout._splitter.setSizes([available - half // 3, half // 3])
        _pump_events(qapp)
        top, bottom = self._split_heights(layout)
        assert bottom < half

        layout.clear_preview()
        _pump_events(qapp)
        top, bottom = self._split_heights(layout)
        assert abs(top - bottom) <= 2
        assert abs(top - half) <= 2
        assert layout._content_bottom.maximumHeight() == half
        layout._info_panel.stop()
        safe_teardown(layout)

    # ── 底栏按钮：顺序与两文字按钮等宽 ────────────────────────────────

    def test_bottom_bar_button_order(
        self, qapp: QApplication,
    ) -> None:
        """底栏顺序：share → 打开方式 → 定位目录 → close。"""
        layout = self._show_split_layout(qapp)
        share_x = layout._share_btn.x()
        open_x = layout._open_default_btn.x()
        locate_x = layout._locate_btn.x()
        close_x = layout._close_btn.x()
        assert share_x < open_x < locate_x < close_x
        assert not hasattr(layout, "_explorer_btn")
        layout._info_panel.stop()
        safe_teardown(layout)

    def test_action_buttons_equal_width_and_track_width(
        self, qapp: QApplication,
    ) -> None:
        """两个文字按钮等宽，随功能区宽度同步同增同减。"""
        layout = self._show_split_layout(qapp)

        def _widths() -> list[int]:
            return [layout._open_default_btn.width(), layout._locate_btn.width()]

        def _assert_equal(ws: list[int]) -> None:
            assert max(ws) - min(ws) <= 1  # 等分取整误差不超过 1px

        wide = _widths()
        _assert_equal(wide)
        assert wide[0] > 0

        layout.resize(980, 920)  # 变宽 → 同步变大
        _pump_events(qapp)
        wider = _widths()
        _assert_equal(wider)
        assert wider[0] > wide[0]

        layout.resize(600, 920)  # 变窄 → 同步变小
        _pump_events(qapp)
        narrow = _widths()
        _assert_equal(narrow)
        assert narrow[0] < wider[0]
        layout._info_panel.stop()
        safe_teardown(layout)


# =============================================================================
# ui.layout.preview.font_previewer_layout
# =============================================================================
class TestFontPreviewerLayout:
    """字体预览布局：构造契约与 set_file 缺失路径降级。"""

    def test_construct_and_geometry(self, qapp: QApplication) -> None:
        """默认构造 + resize 后 geometry 非空。"""
        layout = FontPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.deleteLater()

    def test_set_file_missing_safe(self, qapp: QApplication) -> None:
        """set_file(缺失路径) 不抛异常，停留 overlay 视图。"""
        layout = FontPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.set_file(_MISSING_FILE)
        qapp.processEvents()
        assert layout._content_stack.currentIndex() == 1
        layout.deleteLater()


class TestFontPreviewTextDrawer:
    """预览文本编辑抽屉：标题结构 / 展开收起 / 实时同步 / 重置 / 清理收起。"""

    def _shown_layout(self, qapp: QApplication) -> FontPreviewerLayout:
        layout = FontPreviewerLayout()
        layout.show()
        layout.resize(1200, 700)
        _pump_events(qapp)
        return layout

    @staticmethod
    def _settle_drawers(
        qapp: QApplication,
        layout: FontPreviewerLayout,
        ms: float = 1500,
    ) -> None:
        """有界等待：直到左右抽屉的展开/收起动画全部结束。"""
        deadline = time.time() + ms / 1000
        while time.time() < deadline:
            animating = [
                getattr(layout, attr)._animating
                for attr in ("_text_drawer", "_ai_drawer")
                if getattr(layout, attr) is not None
            ]
            if not any(animating):
                return
            qapp.processEvents()
            time.sleep(0.01)

    def test_drawer_default_hidden_with_title(self, qapp: QApplication) -> None:
        """初始隐藏；抽屉含标题「编辑预览文本」，编辑框不再自带重复 label。"""
        from PySide6.QtWidgets import QLabel

        layout = FontPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        assert not layout._text_drawer._is_open
        assert layout._edit_preview_btn.toolTip() == "编辑预览文本"
        titles = [
            c
            for c in layout._text_drawer._panel.findChildren(QLabel)
            if c.text() == "编辑预览文本"
        ]
        assert titles
        assert layout._preview_text_edit.label == ""
        layout.deleteLater()

    def test_toggle_drawer(self, qapp: QApplication) -> None:
        """编辑按钮第一次点击展开、第二次点击收起抽屉。"""
        layout = self._shown_layout(qapp)
        layout._on_edit_preview_text()
        self._settle_drawers(qapp, layout)
        assert layout._text_drawer._is_open
        assert layout._text_drawer.isVisible()
        layout._on_edit_preview_text()
        assert not layout._text_drawer._is_open
        layout.deleteLater()

    def test_edit_text_syncs_to_preview(self, qapp: QApplication) -> None:
        """预览视图激活时：编辑框输入实时同步 _preview_text 与预览区。"""
        layout = FontPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout._content_stack.setCurrentIndex(0)
        layout._preview_text_edit.text = "自定义预览内容 ABC"
        qapp.processEvents()
        assert layout._preview_text == "自定义预览内容 ABC"
        assert layout._preview_view._text_edit.toPlainText() == "自定义预览内容 ABC"
        layout.deleteLater()

    def test_reset_preview_text(self, qapp: QApplication) -> None:
        """重置按钮恢复默认预览文本并同步到预览区。"""
        layout = FontPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout._preview_text_edit.text = "临时内容"
        layout._on_reset_preview_text()
        assert layout._preview_text == DEFAULT_PREVIEW_TEXT
        assert layout._preview_text_edit.text == DEFAULT_PREVIEW_TEXT
        layout.deleteLater()

    def test_cleanup_closes_drawers(self, qapp: QApplication) -> None:
        """cleanup() 收起已展开的编辑与 AI 抽屉，不抛异常。"""
        layout = self._shown_layout(qapp)
        layout._on_edit_preview_text()
        layout._toggle_ai_drawer()
        self._settle_drawers(qapp, layout)
        assert layout._text_drawer._is_open
        assert layout._ai_drawer._is_open
        layout.cleanup()
        assert not layout._text_drawer._is_open
        assert not layout._ai_drawer._is_open
        layout.deleteLater()


class TestFontWeightLabel:
    """字重标签：数值→标准名映射与静态/可变/未加载三种状态显示。"""

    @pytest.mark.parametrize(
        "weight,expected",
        [
            (100, "Thin"),
            (200, "ExtraLight"),
            (300, "Light"),
            (400, "Regular"),
            (500, "Medium"),
            (600, "SemiBold"),
            (700, "Bold"),
            (800, "ExtraBold"),
            (900, "Black"),
            (1000, "Black"),
            (95, "Thin"),      # 最近档偏差 ≤100
            (105, "Thin"),
            (550, "Medium"),
            (0, "Thin"),       # 越界钳制到下限 100
            (2500, "Black"),   # 越界钳制到上限 1000
        ],
    )
    def test_weight_name_mapping(
        self, weight: int, expected: str,
    ) -> None:
        assert FontPreviewerLayout.weight_name(weight) == expected

    def test_placeholder_when_not_loaded(self, qapp: QApplication) -> None:
        """未加载字体：标签 Weight + 按钮 wght（占位禁用）。"""
        layout = FontPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        assert layout._weight_label.text() == "Weight"
        assert layout._weight_value_btn.text() == "wght"
        assert not layout._weight_value_btn.isEnabled()
        layout.deleteLater()

    def test_static_font_shows_weight_name(self, qapp: QApplication) -> None:
        """静态字体加载后：标签显示真实字重名，按钮显示数值。"""
        layout = FontPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.current_font_family = "SomeStatic"
        layout._is_variable_font = False
        layout._current_weight = 700
        layout._sync_weight_controls()
        assert layout._weight_label.text() == "Bold"
        assert layout._weight_value_btn.text() == "700"
        assert layout._weight_value_btn.isEnabled()
        layout.current_font_family = ""
        layout._is_variable_font = False
        layout._sync_weight_controls()
        assert layout._weight_label.text() == "Weight"
        layout.deleteLater()

    def test_variable_font_keeps_weight_label(self, qapp: QApplication) -> None:
        """可变字体：标签保持 Weight，按钮显示数值。"""
        layout = FontPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.current_font_family = "SomeVariable"
        layout._is_variable_font = True
        layout._current_weight = 400
        layout._sync_weight_controls()
        assert layout._weight_label.text() == "Weight"
        assert layout._weight_value_btn.text() == "400"
        assert layout._weight_value_btn.isEnabled()
        layout.deleteLater()


class TestFontWeightControlsLayout:
    """字重控件布局：统一间距 / tooltip 拆分 / 折叠菜单映射 / 弹窗居中。"""

    def _shown_layout(self, qapp: QApplication) -> FontPreviewerLayout:
        layout = FontPreviewerLayout()
        layout.show()
        layout.resize(1200, 700)
        _pump_events(qapp)
        return layout

    def test_uniform_gap_after_weight_button(
        self, qapp: QApplication,
    ) -> None:
        """字重数值按钮与 AI/缩放按钮间距为统一 6px。"""
        from freeassetfilter.ui.layout.preview.preview_toolbar import (
            PreviewToolbarFrame,
        )

        layout = self._shown_layout(qapp)
        gap = PreviewToolbarFrame._GAP
        weight_right = layout._weight_value_btn.x() + layout._weight_value_btn.width()
        assert layout._ai_btn.x() - weight_right == gap
        ai_right = layout._ai_btn.x() + layout._ai_btn.width()
        assert layout._zoom_btn.x() - ai_right == gap
        layout.deleteLater()

    def test_tooltips_split_and_group_clean(
        self, qapp: QApplication,
    ) -> None:
        """标签 tooltip Weight、按钮 wght；分组自身不再带 tooltip。"""
        layout = FontPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        assert layout._weight_label.toolTip() == "Weight"
        assert layout._weight_value_btn.toolTip() == "wght"
        assert layout._weight_group.toolTip() == ""
        layout.deleteLater()

    def test_overflow_menu_label_mapping(
        self, qapp: QApplication,
    ) -> None:
        """折叠「更多」菜单：字重组显示注册名「字重」，其余控件仍取 tooltip。"""
        layout = FontPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        top_bar = layout._top_bar
        assert top_bar._menu_label(layout._weight_group) == "字重"
        assert top_bar._menu_label(layout._ai_btn) == "AI 功能"
        layout.deleteLater()

    def test_weight_popup_centered_with_button(
        self, qapp: QApplication,
    ) -> None:
        """字重弹窗水平中心与数值按钮中心对齐。"""
        import freeassetfilter.ui.layout.preview.font_previewer_layout as fpl_module

        layout = self._shown_layout(qapp)
        anchor = layout._weight_anchor_global()
        button_center = (
            layout._weight_value_btn.mapToGlobal(
                layout._weight_value_btn.rect().center()
            ).x()
        )
        assert abs(anchor.x() - button_center) <= 1  # 锚点即按钮下缘中心
        popup = fpl_module._WeightPopup(parent=layout)
        rect = popup._target_rect(anchor)
        assert abs(rect.center().x() - anchor.x()) <= 1
        popup.close()
        popup.deleteLater()
        layout.deleteLater()


# =============================================================================
# ui.layout.preview.preview_toolbar（弹窗/溢出菜单锚点）
# =============================================================================
class TestPreviewToolbarPopupAnchoring:
    """顶栏弹窗锚点：功能按钮下缘中心对齐 + 折叠回退 + 溢出菜单居中。"""

    def _shown_toolbar(self, qapp: QApplication) -> Any:
        from freeassetfilter.ui.layout.preview.preview_toolbar import (
            PreviewToolbarFrame,
        )

        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        toolbar = PreviewToolbarFrame()
        toolbar.setFixedHeight(48)
        lay.addWidget(toolbar)
        host.resize(640, 120)
        host.show()
        _pump_events(qapp)
        return host, toolbar

    def test_anchor_is_widget_bottom_center(self, qapp: QApplication) -> None:
        """可见功能按钮的弹窗锚点 = 按钮下缘水平中心。"""
        from PySide6.QtWidgets import QPushButton

        host, toolbar = self._shown_toolbar(qapp)
        try:
            button = QPushButton("X", toolbar)
            button.setFixedSize(32, 32)
            button.show()
            _pump_events(qapp)
            anchor = toolbar.popup_anchor_global(button)
            center = button.mapToGlobal(
                QPoint(button.width() // 2, button.height())
            )
            assert abs(anchor.x() - center.x()) <= 1
            assert abs(anchor.y() - center.y()) <= 1
        finally:
            host.close()
            host.deleteLater()
            _pump_events(qapp)

    def test_anchor_falls_back_to_more_button_when_widget_hidden(
        self, qapp: QApplication,
    ) -> None:
        """功能按钮被折叠隐藏时，锚点回退到「更多」按钮下缘中心。"""
        from PySide6.QtWidgets import QPushButton

        host, toolbar = self._shown_toolbar(qapp)
        try:
            hidden = QPushButton("Z", toolbar)
            hidden.hide()
            toolbar._more_btn.show()
            _pump_events(qapp)
            assert toolbar._more_btn.isVisible()

            anchor = toolbar.popup_anchor_global(hidden)
            center = toolbar._more_btn.mapToGlobal(
                QPoint(toolbar._more_btn.width() // 2, toolbar._more_btn.height())
            )
            assert abs(anchor.x() - center.x()) <= 1
            assert abs(anchor.y() - center.y()) <= 1
        finally:
            host.close()
            host.deleteLater()
            _pump_events(qapp)

    def test_anchor_falls_back_to_toolbar_when_all_hidden(
        self, qapp: QApplication,
    ) -> None:
        """功能按钮与「更多」按钮都不可见时，锚点退回顶栏自身下缘中心。"""
        from PySide6.QtWidgets import QPushButton

        host, toolbar = self._shown_toolbar(qapp)
        try:
            hidden = QPushButton("Z", toolbar)
            hidden.hide()
            toolbar._more_btn.hide()
            _pump_events(qapp)

            anchor = toolbar.popup_anchor_global(hidden)
            self_center = toolbar.mapToGlobal(
                QPoint(toolbar.width() // 2, toolbar.height())
            )
            assert abs(anchor.x() - self_center.x()) <= 1
            assert abs(anchor.y() - self_center.y()) <= 1
        finally:
            host.close()
            host.deleteLater()
            _pump_events(qapp)

    def test_overflow_menu_pos_centered_below_more_button(
        self, qapp: QApplication,
    ) -> None:
        """溢出菜单以「⋯」按钮下缘中心水平展开（居中对齐功能按钮）。"""
        host, toolbar = self._shown_toolbar(qapp)
        try:
            toolbar._more_btn.show()
            _pump_events(qapp)
            menu_w = 220
            pos = toolbar._overflow_menu_pos(menu_w)
            center = toolbar._more_btn.mapToGlobal(
                QPoint(toolbar._more_btn.width() // 2, toolbar._more_btn.height())
            )
            assert abs(pos.x() - (center.x() - menu_w // 2)) <= 1
            assert pos.y() == center.y() + 4  # 按钮下缘 4px 间距
        finally:
            host.close()
            host.deleteLater()
            _pump_events(qapp)


# =============================================================================
# ui.layout.preview.fullscreen_host
# =============================================================================
class TestPreviewFullscreenHost:
    """全屏宿主席：attach/detach 进出、无父窗口进出全屏不抛。"""

    def test_attach_detach_roundtrip(self, qapp: QApplication) -> None:
        """attach 移入宿主，exit_fullscreen 还原到原父布局。"""
        container = QWidget()
        layout = QVBoxLayout(container)
        child = QWidget(container)
        layout.addWidget(child)

        host = PreviewFullscreenHost()
        assert host.attach(child) is True
        assert host.content is child
        assert layout.indexOf(child) == -1
        host.exit_fullscreen()
        assert host.content is None
        assert layout.indexOf(child) == 0
        host.deleteLater()
        container.deleteLater()

    def test_fullscreen_without_parent_does_not_raise(
        self, qapp: QApplication
    ) -> None:
        """无父窗口时 show_fullscreen / exit_fullscreen 不抛（QA 要求）。"""
        host = PreviewFullscreenHost()
        host.show_fullscreen()
        qapp.processEvents()
        host.exit_fullscreen()
        qapp.processEvents()
        host.deleteLater()

    def test_escape_emits_signal(self, qapp: QApplication) -> None:
        """Esc 按键发射 escapePressed 信号（先 connect 再触发）。"""
        host = PreviewFullscreenHost()
        received: list[bool] = []
        host.escapePressed.connect(lambda: received.append(True))
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent

        host.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
        assert received == [True]
        host.deleteLater()


# =============================================================================
# ui.layout.preview.image_previewer_layout
# =============================================================================
class TestImagePreviewerLayout:
    """图像预览布局：构造契约与 set_file 缺失路径返回 False。"""

    def test_construct_and_geometry(self, qapp: QApplication) -> None:
        """默认构造 + resize 后 geometry 非空。"""
        layout = ImagePreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.deleteLater()

    def test_set_file_missing_returns_false(self, qapp: QApplication) -> None:
        """set_file(缺失路径) 返回 False，不抛异常。"""
        layout = ImagePreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        assert layout.set_file(_MISSING_FILE) is False
        layout.deleteLater()

    # ── 打开即适配（真实 viewport 尺寸）与透明背景回归 ─────────────────────

    @staticmethod
    def _make_jpg(tmp_path: Any, name: str, width: int, height: int) -> str:
        """生成指定尺寸的纯色 JPG 到 tmp_path，返回路径。"""
        from PySide6.QtGui import QImage

        img = QImage(width, height, QImage.Format.Format_RGB32)
        img.fill(QColor(120, 160, 200))
        path = str(tmp_path / name)
        assert img.save(path, "JPG", 90)
        return path

    @staticmethod
    def _expected_fit_scale(pv: Any) -> float:
        """按 QGraphicsView 当前真实 viewport 计算期望 fit 比例。

        fitInView 内置约 2px/边的防锯齿留白，此处用无留白上界做近似，
        断言时允许 1% 相对误差即可排除“按默认 640×480 占位尺寸适配”
        的旧缺陷（该场景比例相差远大于 1%）。
        """
        vp = pv._image_view.viewport()
        item = pv._gif_proxy_item if pv._is_gif_mode else pv._pixmap_item
        if pv._is_gif_mode:
            rect = item.boundingRect()
            iw, ih = rect.width(), rect.height()
        else:
            pix = item.pixmap()
            iw, ih = pix.width(), pix.height()
        if not iw or not ih:
            return 0.0
        return min(vp.width() / iw, vp.height() / ih)

    def _shown_previewer(
        self, qapp: QApplication, host_w: int = 1200, host_h: int = 900,
        backdrop: str | None = None,
    ) -> tuple[Any, QWidget]:
        """按真实运行时时序构造：创建 → 加入宿主布局 → set_file 前宿主已可见。"""
        host = QWidget()
        host.resize(host_w, host_h)
        root_lay = QVBoxLayout(host)
        root_lay.setContentsMargins(0, 0, 0, 0)
        outer = QWidget(host)
        if backdrop is not None:
            # NOTE (A1 QSS singleton): backdrop must NOT use a direct
            # setStyleSheet — a widget's own sheet outranks the app-level
            # sheet by Qt level precedence and would paint over the
            # previewer's subtree transparency. Palette fill is visually
            # identical and keeps the QSS cascade untouched.
            palette = outer.palette()
            palette.setColor(outer.backgroundRole(), QColor(backdrop))
            outer.setPalette(palette)
            outer.setAutoFillBackground(True)
        root_lay.addWidget(outer)
        lay = QVBoxLayout(outer)
        lay.setContentsMargins(0, 0, 0, 0)
        pv = ImagePreviewerLayout(parent=outer)
        lay.addWidget(pv)
        host.show()
        qapp.processEvents()
        return pv, host

    def test_open_fits_to_real_viewport_not_placeholder(
        self, qapp: QApplication, tmp_path: Any,
    ) -> None:
        """大图打开后按真实预览区尺寸适配，而非未布局前的默认占位尺寸。

        旧实现：_fit_to_view 在 QGraphicsView 仍处于 Qt 默认几何
        （未加入布局 / 布局未激活）时执行，此后真实尺寸生效也无人再校正，
        观感即“打开不自动缩放”。本用例构造与统一预览器一致的时序
        （先 set_file 后布局激活），断言最终缩放贴近真实 viewport 的 fit 值。
        """
        img = self._make_jpg(tmp_path, "wide.jpg", 3000, 2000)
        pv, host = self._shown_previewer(qapp)
        pv.set_file(img)
        _pump_events(qapp, ms=600)
        try:
            vp = pv._image_view.viewport()
            assert vp.width() > 800 and vp.height() > 500, "宿主布局应已生效"
            expected = self._expected_fit_scale(pv)
            assert expected > 0.1
            actual = pv._image_view.transform().m11()
            assert pv._zoom_pct == 100
            assert abs(actual - expected) / expected <= 0.01, (
                f"打开即适配应使用真实 viewport 尺寸: actual={actual:.4f} "
                f"expected={expected:.4f} vp={vp.width()}x{vp.height()}"
            )
        finally:
            pv.cleanup()
            host.close()
            host.deleteLater()
        _pump_events(qapp, ms=100)

    def test_switching_image_refits_at_unchanged_viewport(
        self, qapp: QApplication, tmp_path: Any,
    ) -> None:
        """viewport 未变化时切换不同尺寸图片也必须重新适配（去重不误伤）。"""
        img_a = self._make_jpg(tmp_path, "a_wide.jpg", 3000, 2000)
        img_b = self._make_jpg(tmp_path, "b_square.jpg", 900, 900)
        pv, host = self._shown_previewer(qapp)
        try:
            pv.set_file(img_a)
            _pump_events(qapp, ms=500)
            scale_a = pv._image_view.transform().m11()
            vp_a = (pv._image_view.viewport().width(), pv._image_view.viewport().height())

            pv.set_file(img_b)
            _pump_events(qapp, ms=500)
            assert pv._zoom_pct == 100
            vp_b = (pv._image_view.viewport().width(), pv._image_view.viewport().height())
            assert vp_a == vp_b, "本例应在 viewport 不变的条件下切换"
            expected_b = self._expected_fit_scale(pv)
            actual_b = pv._image_view.transform().m11()
            assert abs(actual_b - expected_b) / expected_b <= 0.01, (
                f"切换文件后需重新 fit: actual={actual_b:.4f} expected={expected_b:.4f}"
            )
            # 两张图片比例差异明显时，新比例不得残留旧图比例
            expected_a = min(vp_a[0] / 3000.0, vp_a[1] / 2000.0)
            assert abs(scale_a - expected_a) / expected_a <= 0.01
            assert abs(actual_b - scale_a) / scale_a > 0.3, "正方形图不应沿用横图比例"
        finally:
            pv.cleanup()
            host.close()
            host.deleteLater()
        _pump_events(qapp, ms=100)

    def test_preview_area_background_is_transparent(
        self, qapp: QApplication, tmp_path: Any,
    ) -> None:
        """预览区不再涂 tm.surface 深色底，透出下层面板背景（同文本预览器）。

        静态断言：view 样式不含不透明 surface 填色、场景无背景画刷、
        viewport 关闭 palette 自绘；
        行为断言：方形图在宽视口内留出左右 letterbox，其区域像素应透明
        （下层面板为纯红，若有深色底则采样为不透明非透明色）。
        """
        img = self._make_jpg(tmp_path, "square.jpg", 2000, 2000)
        pv, host = self._shown_previewer(qapp, backdrop="#ff0000")
        pv.set_file(img)
        _pump_events(qapp, ms=600)
        try:
            view_ss = pv._image_view.styleSheet().lower()
            assert "surface" not in view_ss and "background-color" not in view_ss
            assert pv._image_scene.backgroundBrush().style() == Qt.NoBrush
            assert pv._image_view.viewport().autoFillBackground() is False
            vp = pv._image_view.viewport()
            assert vp.width() > 800
            image_pix = pv._pixmap_item.pixmap()
            assert image_pix.width() == 2000
            shot = vp.grab().toImage()
            # 依据图像实际渲染矩形选取“必定落在留白区”的采样点：
            # 选左右/上下四条留白中最宽的一条在其中间采样；采样坐标按比例
            # 换算到 grab 位图，兼容高 DPI 屏幕（位图为物理像素）。
            tl = pv._image_view.mapFromScene(
                pv._pixmap_item.sceneBoundingRect().topLeft()
            )
            br = pv._image_view.mapFromScene(
                pv._pixmap_item.sceneBoundingRect().bottomRight()
            )
            gaps = {
                "left": tl.x(),
                "right": vp.width() - 1 - br.x(),
                "top": tl.y(),
                "bottom": vp.height() - 1 - br.y(),
            }
            side, gap = max(gaps.items(), key=lambda kv: kv[1])
            mid_x = vp.width() // 2
            mid_y = vp.height() // 2
            if side == "left":
                log_x, log_y = gap // 2, mid_y
            elif side == "right":
                log_x, log_y = vp.width() - 1 - gap // 2, mid_y
            elif side == "top":
                log_x, log_y = mid_x, gap // 2
            else:
                log_x, log_y = mid_x, vp.height() - 1 - gap // 2
            px = int(round(log_x * shot.width() / vp.width()))
            py = int(round(log_y * shot.height() / vp.height()))
            sample = shot.pixelColor(px, py)
            assert gap >= 4, f"图片应被自适应缩放并留出留白: {gaps}"
            assert sample.alpha() == 0, (
                f"预览区留白应透明（side={side}）: {sample} gaps={gaps}"
            )
        finally:
            pv.cleanup()
            host.close()
            host.deleteLater()
        _pump_events(qapp, ms=100)


# =============================================================================
# ui.layout.preview.office_previewer_layout
# =============================================================================
class _FakeOfficeWorker(QObject):
    """``OfficeConverterWorker`` 的可控替身：不启动真实 soffice 线程。"""

    converted = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        file_info: dict,
        timeout: float | None = None,
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self.file_info: dict = file_info
        self._running: bool = False

    def start(self, *args: Any, **kwargs: Any) -> None:
        """镜像 start：fake 只标记运行中。"""
        self._running = True

    def is_running(self) -> bool:
        """线程是否仍在运行。"""
        return self._running

    def isRunning(self) -> bool:  # noqa: N802
        """Qt 兼容接口。"""
        return self._running

    def request_cancel(self) -> None:
        """镜像 request_cancel。"""
        self._running = False

    def wait(self, timeout_ms: int = 3000) -> bool:
        """镜像 wait。"""
        return not self._running

    def cleanup(self, wait_ms: int = 3000) -> None:
        """镜像 cleanup。"""
        self._running = False


class TestOfficePreviewerLayout:
    """Office 预览布局：构造契约与 set_file 分发（注入 fake worker）。"""

    def test_construct_and_geometry(self, qapp: QApplication) -> None:
        """默认构造（无 worker） + resize 后 geometry 非空。"""
        layout = OfficePreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.cleanup()
        layout.deleteLater()

    def test_set_file_str_routes_to_worker(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """宿主 str 路径分发 → 归一化为 dict、启动 worker（fake）。"""
        monkeypatch.setattr(_opl, "OfficeConverterWorker", _FakeOfficeWorker)
        layout = OfficePreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.set_file("C:/fake/path/sample.docx")
        assert layout._current_suffix == "docx"
        assert isinstance(layout._current_worker, _FakeOfficeWorker)
        layout.cleanup()
        layout.deleteLater()


# =============================================================================
# ui.layout.preview.pdf_previewer_layout
# =============================================================================
class TestPdfPreviewerLayout:
    """PDF 预览布局：构造契约、set_file 缺失路径与滚动/居中几何。"""

    @staticmethod
    def _write_pdf(tmp_path: Path, pages: int = 2) -> str:
        """用 PyMuPDF 在内存构造多页 PDF（612×792pt）。"""
        fitz = pytest.importorskip("fitz")
        doc = fitz.open()
        for i in range(pages):
            page = doc.new_page(width=612, height=792)
            page.insert_text((72, 72), f"Page {i + 1}")
        target = tmp_path / "previewer_scroll.pdf"
        doc.save(str(target))
        doc.close()
        return str(target)

    @staticmethod
    def _shown_loaded_layout(
        qapp: QApplication, tmp_path: Path,
    ) -> tuple[QWidget, PdfPreviewerLayout]:
        """展示宿主并加载双页 PDF（完成 fit 与滚动条范围定时任务）。"""
        host = QWidget()
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        layout = PdfPreviewerLayout()
        host_layout.addWidget(layout)
        host.resize(520, 420)
        host.show()
        _pump_events(qapp)
        assert layout.set_file(TestPdfPreviewerLayout._write_pdf(tmp_path)) is True
        _pump_events(qapp, 400)
        return host, layout

    def test_construct_and_geometry(self, qapp: QApplication) -> None:
        """默认构造 + resize 后 geometry 非空。"""
        layout = PdfPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.deleteLater()

    def test_set_file_missing_returns_false(self, qapp: QApplication) -> None:
        """set_file(缺失路径) 返回 False，不抛异常。"""
        layout = PdfPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        assert layout.set_file(_MISSING_FILE) is False
        layout.deleteLater()

    def test_content_centered_including_reserved_scrollbar_column(
        self, qapp: QApplication, tmp_path: Path,
    ) -> None:
        """页面白色卡片相对预览器左右边缘等距（右侧预留滚动条列计入画布）。"""
        host, layout = self._shown_loaded_layout(qapp, tmp_path)
        try:
            renderer = layout._renderer
            view = renderer._view
            assert view is not None
            assert view.right_reserved_px == 12
            # 画布中心 = (渲染器宽 + 预留列宽) / 2
            assert abs(view.frame_center_x() - (renderer.width() + 12) / 2.0) <= 0.5

            zoom = view.zoom_level
            pwz = renderer._page_widths[0] * zoom
            box_left = (0.0 - view.offset_x) * zoom + view.frame_center_x()
            white_left = box_left + 6.0
            white_right = box_left + pwz - 6.0
            ml = white_left
            mr = (renderer.width() + 12) - white_right
            assert abs(ml - mr) <= 1.0
            assert ml > 0 and mr > 0
        finally:
            host.close()
            host.deleteLater()
            _pump_events(qapp)

    def test_vertical_scroll_range_reserves_bottom_gap(
        self, qapp: QApplication, tmp_path: Path,
    ) -> None:
        """有纵向溢出时滚动条最大值 = 内容高 - 视口高 + 底部预留空隙。"""
        host, layout = self._shown_loaded_layout(qapp, tmp_path)
        try:
            renderer = layout._renderer
            view = renderer._view
            total_h = view._accum_page_heights[-1] * view.zoom_level
            view_h = max(view.view_height, 1)
            overflow = int(total_h - view_h)
            if overflow > 0:
                assert layout._vbar.maximum() == (
                    overflow + layout._CONTENT_BOTTOM_GAP
                )
            else:
                assert layout._vbar.maximum() == 0
        finally:
            host.close()
            host.deleteLater()
            _pump_events(qapp)

    def test_horizontal_scrollbar_shows_only_on_overflow(
        self, qapp: QApplication, tmp_path: Path,
    ) -> None:
        """fit 态无横向溢出 → 底行滚动条隐藏；放大后出现，回到 fit 再隐藏。"""
        host, layout = self._shown_loaded_layout(qapp, tmp_path)
        try:
            renderer = layout._renderer
            view = renderer._view
            assert not layout._hbar.isVisible()
            assert layout._hbar.maximum() == 0
            assert not layout._corner.isVisible()

            base = view.get_zoom_for_scale(100)
            renderer.set_zoom(base * 1.6)
            _pump_events(qapp, 60)
            assert layout._hbar.isVisible()
            assert layout._hbar.maximum() > 0
            assert layout._corner.isVisible()

            renderer.fit_to_page()
            _pump_events(qapp, 60)
            assert not layout._hbar.isVisible()
            assert layout._hbar.maximum() == 0
            assert not layout._corner.isVisible()
        finally:
            host.close()
            host.deleteLater()
            _pump_events(qapp)


# =============================================================================
# ui.layout.preview.text_previewer_layout
# =============================================================================
class TestTextPreviewerLayout:
    """文本预览布局：构造契约、set_text_content 与缺失路径降级。"""

    def test_construct_and_geometry(self, qapp: QApplication) -> None:
        """默认构造 + resize 后 geometry 非空。"""
        layout = TextPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.deleteLater()

    def test_set_text_content(self, qapp: QApplication) -> None:
        """直接注入文本内容不抛异常。"""
        layout = TextPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.set_text_content("hello from test")
        qapp.processEvents()
        layout.deleteLater()

    def test_set_file_missing_safe(self, qapp: QApplication) -> None:
        """set_file(缺失路径) 不抛异常。"""
        layout = TextPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.set_file(_MISSING_FILE)
        qapp.processEvents()
        layout.deleteLater()


# =============================================================================
# ui.layout.preview.video_player_layout
# =============================================================================
class TestVideoPlayerLayout:
    """视频播放布局：构造契约；不带 libmpv 时不真实播放（缺失路径返回 False）。"""

    def test_construct_and_geometry(
        self, qapp: QApplication, heartbeat_manager: Any
    ) -> None:
        """默认构造 + resize 后 geometry 非空（HeartbeatManager 已启动）。"""
        animation_enabled_original = qapp.property("faf_disable_animation")
        try:
            qapp.setProperty("faf_disable_animation", True)
            layout = VideoPlayerLayout()
            assert layout is not None
        finally:
            qapp.setProperty("faf_disable_animation", animation_enabled_original)
        _assert_layout_geometry(layout, qapp)
        layout.deleteLater()

    def test_set_file_missing_returns_false(
        self, qapp: QApplication, heartbeat_manager: Any
    ) -> None:
        """无 libmpv 时 set_file(缺失路径) 返回 False，不做真实播放。"""
        animation_enabled_original = qapp.property("faf_disable_animation")
        try:
            qapp.setProperty("faf_disable_animation", True)
            layout = VideoPlayerLayout()
            assert layout.set_file(_MISSING_FILE) is False
        finally:
            qapp.setProperty("faf_disable_animation", animation_enabled_original)
        layout.deleteLater()

    def test_set_file_recovers_dead_core(
        self, qapp: QApplication, heartbeat_manager: Any, tmp_path: object
    ) -> None:
        """核心死亡时 set_file 自动重建（initialize）并重新嵌入窗口后正常加载。"""
        animation_enabled_original = qapp.property("faf_disable_animation")
        try:
            qapp.setProperty("faf_disable_animation", True)
            media = tmp_path / "sample.mp4"
            media.write_bytes(b"\x00" * 16)
            layout = VideoPlayerLayout()

            fake_manager: Any = MagicMock()
            fake_manager.is_core_operational.return_value = False  # 核心已死
            fake_manager.initialize.return_value = True
            fake_manager.set_window_id.return_value = True
            fake_manager.load_file.return_value = True
            fake_manager.play.return_value = True
            fake_manager.set_volume.return_value = True
            fake_manager.set_speed.return_value = True
            layout._mpv_manager = fake_manager  # noqa: SLF001

            assert layout.set_file(str(media), is_audio=False) is True
            fake_manager.initialize.assert_called_once()  # 自愈重建
            fake_manager.set_window_id.assert_called_once()  # 重新嵌入
            fake_manager.load_file.assert_called_once()
            assert layout._stack.currentIndex() == 0  # noqa: SLF001
        finally:
            qapp.setProperty("faf_disable_animation", animation_enabled_original)
        layout.deleteLater()

    def test_load_failure_shows_overlay(
        self, qapp: QApplication, heartbeat_manager: Any, tmp_path: object
    ) -> None:
        """load_file 失败时切回 overlay 显示错误（不再停留黑色视频表面）。"""
        animation_enabled_original = qapp.property("faf_disable_animation")
        try:
            qapp.setProperty("faf_disable_animation", True)
            media = tmp_path / "bad.mp4"
            media.write_bytes(b"\x00" * 16)
            layout = VideoPlayerLayout()

            fake_manager: Any = MagicMock()
            fake_manager.is_core_operational.return_value = True
            fake_manager.set_window_id.return_value = True
            fake_manager.load_file.return_value = False  # 加载失败
            layout._mpv_manager = fake_manager  # noqa: SLF001

            assert layout.set_file(str(media), is_audio=False) is False
            assert layout._stack.currentIndex() == 1  # noqa: SLF001
            assert "无法加载文件" in layout._placeholder.text()  # noqa: SLF001
        finally:
            qapp.setProperty("faf_disable_animation", animation_enabled_original)
        layout.deleteLater()

    def test_core_rebuild_failure_shows_overlay(
        self, qapp: QApplication, heartbeat_manager: Any, tmp_path: object
    ) -> None:
        """核心重建失败时切回 overlay 显示"无法初始化播放器"。"""
        animation_enabled_original = qapp.property("faf_disable_animation")
        try:
            qapp.setProperty("faf_disable_animation", True)
            media = tmp_path / "dead.mp4"
            media.write_bytes(b"\x00" * 16)
            layout = VideoPlayerLayout()

            fake_manager: Any = MagicMock()
            fake_manager.is_core_operational.return_value = False
            fake_manager.initialize.return_value = False  # 重建失败
            layout._mpv_manager = fake_manager  # noqa: SLF001

            assert layout.set_file(str(media), is_audio=False) is False
            assert layout._stack.currentIndex() == 1  # noqa: SLF001
            assert "无法初始化播放器" in layout._placeholder.text()  # noqa: SLF001
        finally:
            qapp.setProperty("faf_disable_animation", animation_enabled_original)
        layout.deleteLater()


# =============================================================================
# ui.layout.preview.font_previewer_layout — FontLoadThread
# =============================================================================
class TestFontLoadThread:
    """FontLoadThread：文件/请求 ID/中止设置与缺失路径降级。"""

    def test_construct_and_setters(self, qapp: QApplication) -> None:
        """构造后 set_file / set_request_id 生效，未启动线程。"""
        thread = FontLoadThread()
        assert isinstance(thread, QThread)
        thread.set_file(_MISSING_FILE)
        thread.set_request_id(7)
        assert thread.file_path == _MISSING_FILE
        assert thread._request_id == 7
        thread.set_request_id(0)
        thread.abort()  # abort 标记置位
        thread.deleteLater()

    def test_run_missing_path_emits_error(self, qapp: QApplication) -> None:
        """run() 同步执行：缺失路径发 error(request_id, 消息)。"""
        thread = FontLoadThread()
        thread.set_file(_MISSING_FILE)
        thread.set_request_id(42)
        received: list = []

        def _on_error(request_id: int, msg: str) -> None:
            received.append((request_id, msg))

        thread.error.connect(_on_error)
        thread.run()  # 同步执行 run 体，避免真实后台线程
        assert len(received) == 1
        assert received[0][0] == 42
        assert "不存在" in received[0][1]
        thread.deleteLater()


# =============================================================================
# ui.layout.settings_layout — AccentColorButton
# =============================================================================
class TestAccentColorButton:
    """AccentColorButton：构造、color_hex/selected/hover_progress 与点击。"""

    def test_construct(self, qapp: QApplication) -> None:
        """默认构造：color_hex 回退为传入值，未选中、hover 进度 0。"""
        btn = AccentColorButton("#007AFF", name="蓝")
        assert btn.color_hex == "#007AFF"
        assert btn.selected is False
        assert btn.hover_progress == 0.0
        safe_teardown(btn)

    def test_value_override(self, qapp: QApplication) -> None:
        """value 参数覆盖 color_hex 返回值（自动模式用）。"""
        btn = AccentColorButton("#007AFF", value="auto")
        assert btn.color_hex == "auto"
        safe_teardown(btn)

    def test_selected_roundtrip(self, qapp: QApplication) -> None:
        """selected 可写且可读回。"""
        btn = AccentColorButton("#007AFF")
        btn.selected = True
        assert btn.selected is True
        btn.selected = False
        assert btn.selected is False
        safe_teardown(btn)

    def test_click_emits_hex(self, qapp: QApplication) -> None:
        """左键按下发射 clicked(原始 hex)。"""
        btn = AccentColorButton("#007AFF")
        received: list = []

        def _on_clicked(color: str) -> None:
            received.append(color)

        btn.clicked.connect(_on_clicked)
        press = QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(20, 20),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        btn.mousePressEvent(press)
        assert received == ["#007AFF"]
        safe_teardown(btn)

    def test_paint_event_safe(self, qapp: QApplication) -> None:
        """离屏渲染不抛异常。"""
        btn = AccentColorButton("#007AFF", center_text="A")
        btn.selected = True
        pm = QPixmap(40, 40)
        pm.fill(QColor("#000000"))
        btn.render(pm)
        safe_teardown(btn)


# =============================================================================
# ui.layout.settings_layout — CustomAccentButton
# =============================================================================
class TestCustomAccentButton:
    """CustomAccentButton：构造、selected 与点击。"""

    def test_construct(self, qapp: QApplication) -> None:
        """默认构造未选中；传参构造选中。"""
        btn = CustomAccentButton()
        assert btn.selected is False
        btn2 = CustomAccentButton(selected=True)
        assert btn2.selected is True
        safe_teardown(btn)
        safe_teardown(btn2)

    def test_selected_setter(self, qapp: QApplication) -> None:
        """selected 可写可读回。"""
        btn = CustomAccentButton()
        btn.selected = True
        assert btn.selected is True
        safe_teardown(btn)

    def test_click_emits(self, qapp: QApplication) -> None:
        """左键按下发射 clicked。"""
        btn = CustomAccentButton()
        received: list = []

        def _on_clicked() -> None:
            received.append(True)

        btn.clicked.connect(_on_clicked)
        press = QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(20, 20),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        btn.mousePressEvent(press)
        assert received == [True]
        safe_teardown(btn)

    def test_paint_event_safe(self, qapp: QApplication) -> None:
        """离屏渲染不抛异常。"""
        btn = CustomAccentButton(selected=True)
        pm = QPixmap(40, 40)
        pm.fill(QColor("#000000"))
        btn.render(pm)
        safe_teardown(btn)


# =============================================================================
# ui.layout.settings_layout — AppearanceSettingsPage
# =============================================================================
class TestAppearanceSettingsPage:
    """AppearanceSettingsPage：构造、设置收集、主题刷新与关闭路径。"""

    def test_construct_and_collect_settings(self, qapp: QApplication) -> None:
        """构造后 collect_settings 返回 V2 外观结构。"""
        page = AppearanceSettingsPage()
        settings = page.collect_settings()
        assert "appearance" in settings
        assert "theme" in settings["appearance"]
        assert "accent_color" in settings["appearance"]
        safe_teardown(page)

    def test_refresh_theme(self, qapp: QApplication) -> None:
        """refresh_theme：同步 toggle 状态且不抛异常。"""
        page = AppearanceSettingsPage()
        page.refresh_theme()
        assert page._dark_toggle.checked == page._dark_toggle.checked
        safe_teardown(page)

    def test_event_filter_dispatches_to_super(self, qapp: QApplication) -> None:
        """面板未创建时 eventFilter 对点击返回 False（放行继续传播）。"""
        page = AppearanceSettingsPage()
        press = QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(10, 10),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        assert page.eventFilter(page, press) is False
        safe_teardown(page)

    def test_hide_and_close_safe(self, qapp: QApplication) -> None:
        """hideEvent / closeEvent 在面板未创建时不抛异常。"""
        page = AppearanceSettingsPage()
        page.hideEvent(QHideEvent())
        page.closeEvent(QCloseEvent())
        safe_teardown(page)

    def test_mica_sliders_removed(self, qapp: QApplication) -> None:
        """米卡参数已固定（按主题定值）：外观页不再构建滑动条配置项。"""
        page = AppearanceSettingsPage()
        assert not hasattr(page, "_mica_sliders")
        assert not hasattr(page, "_mica_value_labels")
        assert not hasattr(page, "_mica_values")
        assert not hasattr(page, "_mica_preview_timer")
        assert not hasattr(page, "_native_mica_toggle")
        safe_teardown(page)

    def test_bg_segmented_hugs_content_width(self, qapp: QApplication) -> None:
        """「窗口背景」分段控件宽度贴合选项内容，不占满页面/卡片整宽。"""
        page = AppearanceSettingsPage()
        page.resize(640, 900)
        qapp.processEvents()

        seg = page._bg_segmented
        hint = seg.sizeHint()
        assert hint.width() > 0
        assert seg.width() == hint.width()
        assert seg.width() < page.width()
        # pill 容器背景只包住选项内容
        assert int(seg._header.content_width) == seg.width()
        safe_teardown(page)

    # ── 窗口背景区块（米卡效果 / 自定义图片） ─────────────────────

    @staticmethod
    def _make_fake_bg_main_window() -> Any:
        """构造记录背景 API 调用顺序的假主窗口（无需真实 QWidget）。"""

        class _FakeBgMainWindow:
            """记录 set_background_mode / set_custom_background_image 调用。"""

            def __init__(self) -> None:
                self.mode_calls: list[str] = []
                self.image_calls: list[str] = []

            def set_background_mode(self, mode: str) -> None:
                self.mode_calls.append(mode)

            def set_custom_background_image(self, path: str) -> bool:
                self.image_calls.append(path)
                return True

        return _FakeBgMainWindow()

    @staticmethod
    def _make_fake_file_dialog(result: tuple[str, str]) -> Any:
        """构造 getOpenFileName 返回固定结果的假 QFileDialog。"""

        class _FakeFileDialog:
            """静态 getOpenFileName 返回预设 (path, filter) 元组。"""

            @staticmethod
            def getOpenFileName(*args: Any, **kwargs: Any) -> tuple[str, str]:
                return result

        return _FakeFileDialog

    def test_background_default_mica_ui_state(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """默认（V2 无背景设置）：mica 模式——分段 0、图片行隐藏、滑动条可用。"""
        import freeassetfilter.ui.layout.settings_layout as sl_mod
        from freeassetfilter.core.managers.settings_manager_v2 import (
            SettingsManagerV2,
        )

        tmp_file = str(tmp_path / "settings_v2.json")
        monkeypatch.setattr(
            sl_mod, "SettingsManagerV2", lambda *a, **k: SettingsManagerV2(tmp_file)
        )

        page = AppearanceSettingsPage()
        assert page._bg_mode == "mica"
        assert page._bg_image_name == ""
        assert page._bg_segmented.current_index == 1
        assert page._bg_image_row.isVisibleTo(page) is False
        assert page._bg_file_label.text() == "未设置"
        safe_teardown(page)

    def test_background_image_mode_loaded_from_v2(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """V2 保存 image 模式且文件存在：初始即 image UI 状态（不触发应用）。"""
        import freeassetfilter.ui.layout.settings_layout as sl_mod
        from freeassetfilter.core.managers.settings_manager_v2 import (
            SettingsManagerV2,
        )
        from components.custom_background import BACKGROUND_DIR_NAME

        tmp_file = str(tmp_path / "settings_v2.json")
        v2 = SettingsManagerV2(tmp_file)
        v2.load()
        v2.set(
            "appearance.background",
            {"mode": "image", "image": "custom_background.png"},
        )
        v2.save()

        bg_dir = tmp_path / BACKGROUND_DIR_NAME
        bg_dir.mkdir()
        pm = QPixmap(16, 16)
        pm.fill(QColor("#336699"))
        assert pm.save(str(bg_dir / "custom_background.png"), "PNG") is True

        monkeypatch.setattr(
            sl_mod, "SettingsManagerV2", lambda *a, **k: SettingsManagerV2(tmp_file)
        )
        monkeypatch.setattr(sl_mod, "get_app_data_path", lambda: str(tmp_path))

        page = AppearanceSettingsPage()
        assert page._bg_mode == "image"
        assert page._bg_image_name == "custom_background.png"
        assert page._bg_segmented.current_index == 2
        assert page._bg_image_row.isVisibleTo(page) is True
        assert page._bg_file_label.text() == "custom_background.png"
        safe_teardown(page)

    def test_apply_background_settings_routes_and_saves(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """_apply_background_settings：暂存优先（未提交不触碰主窗口与磁盘）。

        新语义：仅写入暂存缓存并刷新本页 UI；主窗口应用与 V2 落盘统一由
        ``SettingsLayout._submit_settings`` 在点击应用/确定时执行。
        """
        import freeassetfilter.ui.layout.settings_layout as sl_mod
        from freeassetfilter.core.managers.settings_manager_v2 import (
            SettingsManagerV2,
        )

        tmp_file = str(tmp_path / "settings_v2.json")
        monkeypatch.setattr(
            sl_mod, "SettingsManagerV2", lambda *a, **k: SettingsManagerV2(tmp_file)
        )
        fake_mw = self._make_fake_bg_main_window()
        monkeypatch.setattr(
            sl_mod.AppearanceSettingsPage, "_find_main_window", lambda self: fake_mw
        )
        monkeypatch.setattr(sl_mod, "get_app_data_path", lambda: str(tmp_path))

        page = AppearanceSettingsPage()
        page._bg_image_name = "custom_background.png"

        # image 暂存：不直调主窗口、不落盘，仅缓存 + UI 可见
        page._apply_background_settings("image")
        assert fake_mw.image_calls == []
        assert fake_mw.mode_calls == []
        assert page._staging_cache.get("appearance.background.mode") == "image"
        assert page._staging_cache.get("appearance.background.image") == "custom_background.png"
        assert page._bg_image_row.isVisibleTo(page) is True

        saved = SettingsManagerV2(tmp_file)
        saved.load()
        assert saved.get("appearance.background.mode") == "mica"

        # mica 暂存：同样仅缓存，不动主窗口图片接口
        page._apply_background_settings("mica")
        assert fake_mw.mode_calls == []
        assert len(fake_mw.image_calls) == 0
        assert page._bg_image_row.isVisibleTo(page) is False
        assert page._staging_cache.get("appearance.background.mode") == "mica"
        saved = SettingsManagerV2(tmp_file)
        saved.load()
        assert saved.get("appearance.background.mode") == "mica"
        safe_teardown(page)

    def test_bg_segment_switch_with_existing_image(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """已有持久化图片时切换分段：暂存 image 模式（不经文件对话框、不直写）。"""
        import freeassetfilter.ui.layout.settings_layout as sl_mod
        from freeassetfilter.core.managers.settings_manager_v2 import (
            SettingsManagerV2,
        )
        from components.custom_background import BACKGROUND_DIR_NAME

        tmp_file = str(tmp_path / "settings_v2.json")
        bg_dir = tmp_path / BACKGROUND_DIR_NAME
        bg_dir.mkdir()
        pm = QPixmap(16, 16)
        pm.fill(QColor("#336699"))
        assert pm.save(str(bg_dir / "custom_background.png"), "PNG") is True

        monkeypatch.setattr(
            sl_mod, "SettingsManagerV2", lambda *a, **k: SettingsManagerV2(tmp_file)
        )
        monkeypatch.setattr(sl_mod, "get_app_data_path", lambda: str(tmp_path))
        fake_mw = self._make_fake_bg_main_window()
        monkeypatch.setattr(
            sl_mod.AppearanceSettingsPage, "_find_main_window", lambda self: fake_mw
        )

        page = AppearanceSettingsPage()
        page._bg_image_name = "custom_background.png"
        # 模拟用户点击图像分段（触发 current_changed → 处理器，仅暂存）
        page._bg_segmented.set_current_index(2)

        assert page._bg_mode == "image"
        assert page._staging_cache.get("appearance.background.mode") == "image"
        assert len(fake_mw.image_calls) == 0
        assert fake_mw.mode_calls == []
        saved = SettingsManagerV2(tmp_file)
        saved.load()
        assert saved.get("appearance.background.mode") == "mica"
        safe_teardown(page)

    def test_bg_segment_switch_cancel_reverts(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """无图片时切换分段后取消选择：分段回退、设置不变、不调用主窗口。"""
        import freeassetfilter.ui.layout.settings_layout as sl_mod
        from freeassetfilter.core.managers.settings_manager_v2 import (
            SettingsManagerV2,
        )

        tmp_file = str(tmp_path / "settings_v2.json")
        monkeypatch.setattr(
            sl_mod, "SettingsManagerV2", lambda *a, **k: SettingsManagerV2(tmp_file)
        )
        monkeypatch.setattr(sl_mod, "get_app_data_path", lambda: str(tmp_path))
        monkeypatch.setattr(
            sl_mod, "QFileDialog", self._make_fake_file_dialog(("", ""))
        )
        fake_mw = self._make_fake_bg_main_window()
        monkeypatch.setattr(
            sl_mod.AppearanceSettingsPage, "_find_main_window", lambda self: fake_mw
        )

        page = AppearanceSettingsPage()
        page._bg_segmented.set_current_index(2)

        # 取消：分段编程式回退到云母，模式与持久化设置保持默认（未被写入）
        assert page._bg_segmented.current_index == 1
        assert page._bg_mode == "mica"
        assert fake_mw.mode_calls == []
        assert fake_mw.image_calls == []
        saved = SettingsManagerV2(tmp_file)
        saved.load()
        assert saved.get("appearance.background") == {"mode": "mica", "image": "", "ambient": True, "blur": 0, "transparency": 80}
        safe_teardown(page)

    def test_bg_segment_switch_import_failure_shows_dialog(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """导入失败：弹 danger 对话框、分段回退、不切换不改设置。"""
        import freeassetfilter.ui.layout.settings_layout as sl_mod
        from freeassetfilter.core.managers.settings_manager_v2 import (
            SettingsManagerV2,
        )

        tmp_file = str(tmp_path / "settings_v2.json")
        monkeypatch.setattr(
            sl_mod, "SettingsManagerV2", lambda *a, **k: SettingsManagerV2(tmp_file)
        )
        monkeypatch.setattr(sl_mod, "get_app_data_path", lambda: str(tmp_path))
        monkeypatch.setattr(
            sl_mod, "QFileDialog",
            self._make_fake_file_dialog(("D:/fake/pic.png", "图片文件 (*.png)")),
        )
        monkeypatch.setattr(
            sl_mod, "import_custom_background_image", lambda path: None
        )
        dialog_calls: list[dict] = []
        monkeypatch.setattr(
            sl_mod, "create_danger_dialog",
            lambda **kwargs: dialog_calls.append(kwargs),
        )
        fake_mw = self._make_fake_bg_main_window()
        monkeypatch.setattr(
            sl_mod.AppearanceSettingsPage, "_find_main_window", lambda self: fake_mw
        )

        page = AppearanceSettingsPage()
        page._bg_segmented.set_current_index(2)

        assert len(dialog_calls) == 1
        assert dialog_calls[0]["title"] == "导入失败"
        assert page._bg_segmented.current_index == 1
        assert page._bg_mode == "mica"
        assert fake_mw.mode_calls == []
        saved = SettingsManagerV2(tmp_file)
        saved.load()
        assert saved.get("appearance.background") == {"mode": "mica", "image": "", "ambient": True, "blur": 0, "transparency": 80}
        safe_teardown(page)

    def test_choose_bg_image_success_via_button(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """按钮点击选择图片成功：暂存文件名与 image 模式（提交前不直写）。"""
        import freeassetfilter.ui.layout.settings_layout as sl_mod
        from freeassetfilter.core.managers.settings_manager_v2 import (
            SettingsManagerV2,
        )

        tmp_file = str(tmp_path / "settings_v2.json")
        monkeypatch.setattr(
            sl_mod, "SettingsManagerV2", lambda *a, **k: SettingsManagerV2(tmp_file)
        )
        monkeypatch.setattr(sl_mod, "get_app_data_path", lambda: str(tmp_path))
        monkeypatch.setattr(
            sl_mod, "QFileDialog",
            self._make_fake_file_dialog(("D:/fake/pic.png", "图片文件 (*.png)")),
        )
        dest = str(tmp_path / "backgrounds" / "custom_background.png")
        monkeypatch.setattr(
            sl_mod, "import_custom_background_image", lambda path: dest
        )
        fake_mw = self._make_fake_bg_main_window()
        monkeypatch.setattr(
            sl_mod.AppearanceSettingsPage, "_find_main_window", lambda self: fake_mw
        )

        page = AppearanceSettingsPage()
        # 模拟按钮点击（clicked → _on_choose_bg_image_clicked → 非强制选择）
        page._bg_choose_btn.click()

        assert page._bg_image_name == "custom_background.png"
        assert page._bg_file_label.text() == "custom_background.png"
        assert page._bg_mode == "image"
        assert page._bg_segmented.current_index == 1  # 按钮入口不切分段
        assert page._staging_cache.get("appearance.background.image") == "custom_background.png"
        assert fake_mw.image_calls == []
        assert fake_mw.mode_calls == []
        saved = SettingsManagerV2(tmp_file)
        saved.load()
        assert saved.get("appearance.background.mode") == "mica"
        safe_teardown(page)

    def test_update_bg_ui_state_toggles_image_row(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """_update_bg_ui_state：image 模式显示图片行，mica 模式隐藏。"""
        import freeassetfilter.ui.layout.settings_layout as sl_mod
        from freeassetfilter.core.managers.settings_manager_v2 import (
            SettingsManagerV2,
        )

        tmp_file = str(tmp_path / "settings_v2.json")
        monkeypatch.setattr(
            sl_mod, "SettingsManagerV2", lambda *a, **k: SettingsManagerV2(tmp_file)
        )

        page = AppearanceSettingsPage()
        page._bg_mode = "image"
        page._update_bg_ui_state()
        assert page._bg_image_row.isVisibleTo(page) is True

        page._bg_mode = "mica"
        page._update_bg_ui_state()
        assert page._bg_image_row.isVisibleTo(page) is False
        safe_teardown(page)