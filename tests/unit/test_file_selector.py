# -*- coding: utf-8 -*-
"""
file_selector 单元测试
测试 freeassetfilter/components/file_selector.py 模块的功能
"""
import pytest
import os
import sys
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest

from freeassetfilter.widgets.file_selector_model import FileListView, FileSelectorListModel


class TestFileSelectorBasic:
    """测试 FileSelector 基本功能"""
    
    def test_module_import(self):
        """测试模块可以导入"""
        from freeassetfilter.components.file_selector import CustomFileSelector
        assert CustomFileSelector is not None
    
    def test_module_has_required_attributes(self):
        """测试模块有必要的属性"""
        from freeassetfilter.components import file_selector
        # 检查模块存在
        assert file_selector is not None


class TestFileSelectorRobustness:
    """测试 FileSelector 鲁棒性"""
    
    def test_module_handles_errors_gracefully(self):
        """测试模块能优雅处理错误"""
        # 基础错误处理测试
        pass


class TestFileSelectorIntegration:
    """测试 FileSelector 集成"""
    
    def test_module_integration(self):
        """测试模块集成"""
        # 集成测试
        pass


class TestFileListViewBackNavigation:
    """测试文件选择器矩阵区域的鼠标侧键返回行为"""

    def _create_view(self, qt_app):
        setattr(qt_app, "settings_manager", _DummySettingsManager())
        model = FileSelectorListModel(dpi_scale=1.0)
        model.set_card_width(150, 75, 3)
        model.set_files([{
            "name": "folder",
            "path": "C:/demo/folder",
            "is_dir": True,
            "size": 0,
            "created": "",
            "suffix": "",
        }])

        view = FileListView()
        view.setModel(model)
        view.setGridSize(QSize(164, 80))
        view.resize(420, 220)
        view.show()
        qt_app.processEvents()
        view.doItemsLayout()
        qt_app.processEvents()
        return view, model

    def test_back_side_button_on_card_requests_parent_navigation(self, qt_app):
        view, model = self._create_view(qt_app)
        try:
            hits = []
            view.navigate_parent_requested.connect(lambda: hits.append("back"))

            index = model.index(0, 0)
            click_pos = view.visualRect(index).center()
            assert view.indexAt(click_pos).isValid()

            QTest.mouseClick(view.viewport(), Qt.BackButton, Qt.NoModifier, click_pos)

            assert hits == ["back"]
        finally:
            view.close()
            view.deleteLater()

    def test_back_side_button_on_blank_area_requests_parent_navigation(self, qt_app):
        view, model = self._create_view(qt_app)
        try:
            hits = []
            view.navigate_parent_requested.connect(lambda: hits.append("back"))

            click_pos = QPoint(view.viewport().width() - 8, view.viewport().height() - 8)
            assert not view.indexAt(click_pos).isValid()

            QTest.mouseClick(view.viewport(), Qt.BackButton, Qt.NoModifier, click_pos)

            assert hits == ["back"]
        finally:
            view.close()
            view.deleteLater()


class TestFileListViewPathTransition:
    """测试路径切换时的整体卡片快照动画"""

    def _create_view(self, qt_app):
        setattr(qt_app, "settings_manager", _DummySettingsManager())
        model = FileSelectorListModel(dpi_scale=1.0)
        model.set_card_width(150, 75, 3)
        model.set_files([{
            "name": "folder",
            "path": "C:/demo/folder",
            "is_dir": True,
            "size": 0,
            "created": "",
            "suffix": "",
        }])

        view = FileListView()
        view.setModel(model)
        view.setGridSize(QSize(164, 80))
        view.resize(420, 220)
        view.show()
        qt_app.processEvents()
        view.doItemsLayout()
        qt_app.processEvents()
        return view, model

    def test_path_transition_uses_single_viewport_snapshot_until_new_cards_arrive(self, qt_app):
        view, model = self._create_view(qt_app)
        try:
            assert view.begin_path_transition(1) is True
            assert view._path_transition_waiting_for_incoming is True
            assert view._path_transition_active is False
            assert view._path_transition_timer.isActive() is False
            assert not view._path_transition_outgoing_pixmap.isNull()

            model.set_files([{
                "name": "nested.txt",
                "path": "C:/demo/folder/nested.txt",
                "is_dir": False,
                "size": 12,
                "created": "",
                "suffix": "txt",
            }])
            view.doItemsLayout()
            qt_app.processEvents()

            assert view.finish_path_transition(1) is True
            assert view._path_transition_waiting_for_incoming is False
            assert view._path_transition_active is True
            assert view._path_transition_timer.isActive() is True
            assert not view._path_transition_incoming_pixmap.isNull()

            view._advance_path_transition(
                view._path_transition_start_ms + view._path_transition_duration_ms + 1
            )

            assert view._path_transition_active is False
            assert view._path_transition_waiting_for_incoming is False
            assert view._path_transition_outgoing_pixmap.isNull()
            assert view._path_transition_incoming_pixmap.isNull()
        finally:
            view.close()
            view.deleteLater()

    def test_waiting_path_transition_survives_viewport_resize_before_parent_cards_arrive(self, qt_app):
        view, model = self._create_view(qt_app)
        try:
            assert view.begin_path_transition(-1) is True
            outgoing_cache_key = view._path_transition_outgoing_pixmap.cacheKey()

            view.resize(390, 220)
            qt_app.processEvents()

            assert view._path_transition_waiting_for_incoming is True
            assert view._path_transition_outgoing_pixmap.cacheKey() == outgoing_cache_key

            model.set_files([{
                "name": f"parent_{row}.txt",
                "path": f"C:/demo/parent_{row}.txt",
                "is_dir": False,
                "size": 12,
                "created": "",
                "suffix": "txt",
            } for row in range(12)])
            view.doItemsLayout()
            qt_app.processEvents()

            assert view.finish_path_transition(-1) is True
            assert view._path_transition_active is True
        finally:
            view.close()
            view.deleteLater()


class TestCustomFileSelectorNavigationDirection:
    """测试路径关系到左右平移动画方向的映射"""

    def _create_selector(self):
        from freeassetfilter.components.file_selector import CustomFileSelector

        return CustomFileSelector.__new__(CustomFileSelector)

    def test_entering_child_directory_moves_forward(self):
        selector = self._create_selector()

        assert selector._infer_navigation_direction("C:/demo", "C:/demo/folder") == 1

    def test_returning_to_parent_directory_moves_backward(self):
        selector = self._create_selector()

        assert selector._infer_navigation_direction("C:/demo/folder", "C:/demo") == -1

    def test_all_view_acts_as_top_level_for_direction(self):
        selector = self._create_selector()

        assert selector._infer_navigation_direction("All", "C:/demo") == 1
        assert selector._infer_navigation_direction("C:/demo", "All") == -1


class TestCustomFileSelectorPathTransitionScheduling:
    """测试路径切换完成阶段会延后一帧捕获入场快照"""

    def test_finish_path_transition_is_deferred_to_next_event_loop_turn(self):
        from freeassetfilter.components import file_selector as file_selector_module
        from freeassetfilter.components.file_selector import CustomFileSelector

        selector = CustomFileSelector.__new__(CustomFileSelector)
        selector._pending_path_transition_direction = -1
        selector._pending_path_transition_token = 3

        finish_calls = []

        class _DummyViewport:
            def update(self):
                finish_calls.append("viewport_update")

        class _DummyListView:
            def __init__(self):
                self._viewport = _DummyViewport()

            def doItemsLayout(self):
                finish_calls.append("layout")

            def viewport(self):
                return self._viewport

            def finish_path_transition(self, direction):
                finish_calls.append(("finish", direction))

        selector.files_scroll_area = _DummyListView()

        with patch.object(file_selector_module.QTimer, "singleShot") as single_shot:
            selector._finish_files_path_transition()
            assert finish_calls == ["layout", "viewport_update"]
            single_shot.assert_called_once()

            _, callback = single_shot.call_args[0]
            callback()

            assert finish_calls == [
                "layout",
                "viewport_update",
                "layout",
                ("finish", -1),
            ]


class TestCustomFileSelectorGridSizing:
    """测试滚动条占位变化会触发卡片网格重新计算。"""

    def test_scrollbar_extent_change_schedules_grid_relayout(self, qt_app, monkeypatch):
        from freeassetfilter.components.file_selector import CustomFileSelector

        monkeypatch.setattr(qt_app, "settings_manager", _DummySettingsManager(), raising=False)
        monkeypatch.setattr(qt_app, "global_font", QFont(), raising=False)

        selector = CustomFileSelector()

        try:
            _update_called = []
            original_update = selector._update_grid_size
            monkeypatch.setattr(selector, "_update_grid_size", lambda: _update_called.append(True))

            scrollbar = selector.files_scroll_area.verticalScrollBar()
            scrollbar.effective_extent_changed.emit(0)

            assert len(_update_called) >= 1
        finally:
            selector.close()
            selector.deleteLater()

    def test_card_row_horizontal_gaps_stay_balanced(self, qt_app, monkeypatch):
        from freeassetfilter.components.file_selector import CustomFileSelector

        monkeypatch.setattr(qt_app, "settings_manager", _DummySettingsManager(), raising=False)
        monkeypatch.setattr(qt_app, "global_font", QFont(), raising=False)

        selector = CustomFileSelector()

        try:
            selector._first_show = False
            selector.resize(430, 720)
            selector.show()
            qt_app.processEvents()

            selector.file_model.set_files([{
                "name": f"SKY{1000 + row}.JPG",
                "path": f"C:/demo/SKY{1000 + row}.JPG",
                "is_dir": False,
                "size": 1024 * 1024 * (row + 1),
                "created": "2025-06-29T00:00:00",
                "suffix": "jpg",
            } for row in range(12)])
            selector._update_grid_size()
            selector.files_scroll_area.doItemsLayout()
            qt_app.processEvents()

            view = selector.files_scroll_area
            model = selector.file_model
            first_row_rects = []
            for row in range(model.rowCount()):
                rect = view.visualRect(model.index(row, 0))
                if rect.y() == 0:
                    first_row_rects.append(rect)

            assert len(first_row_rects) >= 2

            left_gap = first_row_rects[0].x()
            right_gap = view.viewport().width() - first_row_rects[-1].right() - 1

            assert abs(left_gap - right_gap) <= selector._card_spacing
        finally:
            selector.close()
            selector.deleteLater()

    def test_column_count_changes_monotonically_while_width_shrinks(self, qt_app, monkeypatch):
        from freeassetfilter.components.file_selector import CustomFileSelector

        monkeypatch.setattr(qt_app, "settings_manager", _DummySettingsManager(), raising=False)
        monkeypatch.setattr(qt_app, "global_font", QFont(), raising=False)

        selector = CustomFileSelector()

        try:
            selector._first_show = False
            selector.file_model.set_files([{
                "name": f"SKY{1000 + row}.JPG",
                "path": f"C:/demo/SKY{1000 + row}.JPG",
                "is_dir": False,
                "size": 1024 * 1024 * (row + 1),
                "created": "2025-06-29T00:00:00",
                "suffix": "jpg",
            } for row in range(20)])

            columns = []
            for width in range(500, 320, -10):
                selector.resize(width, 400)
                selector.show()
                qt_app.processEvents()
                selector._update_grid_size()
                selector.files_scroll_area.doItemsLayout()
                qt_app.processEvents()

                view = selector.files_scroll_area
                first_row_y = None
                first_row_columns = 0
                for row in range(selector.file_model.rowCount()):
                    rect = view.visualRect(selector.file_model.index(row, 0))
                    if row == 0:
                        first_row_y = rect.y()
                    if rect.y() == first_row_y:
                        first_row_columns += 1

                columns.append(first_row_columns)

            assert columns == sorted(columns, reverse=True)
        finally:
            selector.close()
            selector.deleteLater()


class _DummySettingsManager:
    def get_setting(self, key, default=None):
        return default


class _MappedSettingsManager:
    def __init__(self, overrides=None):
        self._overrides = overrides or {}

    def get_setting(self, key, default=None):
        return self._overrides.get(key, default)


class TestFileSelectorCardDelegateVisuals:
    """测试文件选择器卡片 delegate 的 hover / preview 阴影视觉目标值。"""

    def _create_delegate(self, qt_app, monkeypatch):
        from freeassetfilter.widgets.file_selector_delegate import FileBlockCardDelegate

        monkeypatch.setattr(qt_app, "settings_manager", _DummySettingsManager(), raising=False)
        monkeypatch.setattr(qt_app, "global_font", QFont(), raising=False)
        return FileBlockCardDelegate(dpi_scale=1.0, global_font=QFont())

    def test_hover_state_uses_secondary_color_shadow_with_large_blur(self, qt_app, monkeypatch):
        delegate = self._create_delegate(qt_app, monkeypatch)

        _bg, _border, shadow, blur = delegate._target_visuals_for_flags(
            is_hovered=True,
            is_selected=False,
            is_previewing=False,
        )

        assert shadow == delegate._hover_shadow
        assert blur == pytest.approx(8.0 * delegate._dpi_scale)

    def test_preview_state_uses_accent_color_shadow(self, qt_app, monkeypatch):
        delegate = self._create_delegate(qt_app, monkeypatch)

        _bg, _border, shadow, blur = delegate._target_visuals_for_flags(
            is_hovered=False,
            is_selected=False,
            is_previewing=True,
        )

        assert shadow == delegate._preview_shadow
        assert blur == pytest.approx(8.0 * delegate._dpi_scale)

    def test_card_state_animation_setting_disables_delegate_transition(self, qt_app, monkeypatch):
        from freeassetfilter.widgets.file_selector_delegate import FileBlockCardDelegate

        monkeypatch.setattr(
            qt_app,
            "settings_manager",
            _MappedSettingsManager({"appearance.animations.file_card_state": False}),
            raising=False,
        )
        monkeypatch.setattr(qt_app, "global_font", QFont(), raising=False)

        delegate = FileBlockCardDelegate(dpi_scale=1.0, global_font=QFont())
        state = delegate._sync_animation_state("demo", {}, True, False, False)
        target_bg, target_border, target_shadow, target_shadow_blur = delegate._target_visuals_for_flags(
            True,
            False,
            False,
        )

        assert state["animating"] is False
        assert state["bg_color"] == target_bg
        assert state["border_color"] == target_border
        assert state["shadow_color"] == target_shadow
        assert state["shadow_blur"] == float(target_shadow_blur)
        assert "demo" not in delegate._active_animation_keys

    def test_directory_transition_setting_disables_path_transition(self, qt_app, monkeypatch):
        view, _model = TestFileListViewPathTransition()._create_view(qt_app)
        try:
            monkeypatch.setattr(
                qt_app,
                "settings_manager",
                _MappedSettingsManager({"appearance.animations.directory_transition": False}),
                raising=False,
            )
            assert view.begin_path_transition(1) is False
            assert view._path_transition_waiting_for_incoming is False
            assert view._path_transition_active is False
            assert view._path_transition_outgoing_pixmap.isNull()
        finally:
            view.close()
            view.deleteLater()
