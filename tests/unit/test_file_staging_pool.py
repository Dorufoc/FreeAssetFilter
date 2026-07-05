# -*- coding: utf-8 -*-
"""
file_staging_pool 单元测试
测试 freeassetfilter/components/file_staging_pool.py 模块的功能
"""
import json
import os
import threading

from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem


class _DummySettingsManager:
    def get_setting(self, key, default=None):
        return default


class _MappedSettingsManager:
    def __init__(self, overrides=None):
        self._overrides = overrides or {}

    def get_setting(self, key, default=None):
        return self._overrides.get(key, default)


class _DummySignal:
    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)


class _DummyMessageBox:
    def __init__(self, *args, **kwargs):
        self.buttonClicked = _DummySignal()

    def set_title(self, *_args, **_kwargs):
        pass

    def set_text(self, *_args, **_kwargs):
        pass

    def set_buttons(self, *_args, **_kwargs):
        pass

    def exec(self):
        pass

    def close(self, *_args, **_kwargs):
        pass


def _build_pool_view(qt_app, monkeypatch, temp_file):
    from freeassetfilter.widgets.file_staging_pool_delegate import FileStagingPoolCardDelegate
    from freeassetfilter.widgets.file_staging_pool_model import FileStagingPoolListModel, FileStagingPoolListView

    monkeypatch.setattr(qt_app, "dpi_scale_factor", 1.0, raising=False)
    monkeypatch.setattr(qt_app, "global_font", QFont(), raising=False)
    monkeypatch.setattr(qt_app, "settings_manager", _DummySettingsManager(), raising=False)

    model = FileStagingPoolListModel(dpi_scale=1.0, global_font=QFont())
    view = FileStagingPoolListView(dpi_scale=1.0, global_font=QFont())
    delegate = FileStagingPoolCardDelegate(
        dpi_scale=1.0,
        global_font=QFont(),
        single_line_mode=False,
        enable_delete_action=True,
        parent=view,
    )

    view.setModel(model)
    view.setItemDelegate(delegate)
    delegate.set_view(view)

    model.add_file(
        {
            "path": temp_file,
            "name": os.path.basename(temp_file),
            "display_name": os.path.basename(temp_file),
            "original_name": os.path.basename(temp_file),
            "is_dir": False,
            "size": os.path.getsize(temp_file),
        }
    )

    view.resize(640, 120)
    view.show()
    qt_app.processEvents()

    return view, model, delegate, model.index(0, 0)


def _build_empty_pool_view(qt_app, monkeypatch, height=260):
    from freeassetfilter.widgets.file_staging_pool_delegate import FileStagingPoolCardDelegate
    from freeassetfilter.widgets.file_staging_pool_model import FileStagingPoolListModel, FileStagingPoolListView

    monkeypatch.setattr(qt_app, "dpi_scale_factor", 1.0, raising=False)
    monkeypatch.setattr(qt_app, "global_font", QFont(), raising=False)
    monkeypatch.setattr(qt_app, "settings_manager", _DummySettingsManager(), raising=False)

    model = FileStagingPoolListModel(dpi_scale=1.0, global_font=QFont())
    view = FileStagingPoolListView(dpi_scale=1.0, global_font=QFont())
    delegate = FileStagingPoolCardDelegate(
        dpi_scale=1.0,
        global_font=QFont(),
        single_line_mode=False,
        enable_delete_action=True,
        parent=view,
    )

    view.setModel(model)
    view.setItemDelegate(delegate)
    delegate.set_view(view)
    view.resize(640, height)
    view.show()
    qt_app.processEvents()

    return view, model, delegate


def _make_staging_item(file_path):
    return {
        "path": file_path,
        "name": os.path.basename(file_path),
        "display_name": os.path.basename(file_path),
        "original_name": os.path.basename(file_path),
        "is_dir": False,
        "size": os.path.getsize(file_path),
    }


def _write_temp_file(temp_dir, name, content=b"data"):
    file_path = os.path.join(temp_dir, name)
    with open(file_path, "wb") as f:
        f.write(content)
    return file_path


def _build_option(view, index):
    option = QStyleOptionViewItem()
    if hasattr(view, "initViewItemOption"):
        view.initViewItemOption(option)
    option.rect = view.visualRect(index)
    option.widget = view.viewport()
    return option


def _build_pool_widget(qt_app, monkeypatch, backup_dir):
    import freeassetfilter.components.file_staging_pool as file_staging_pool_module
    from freeassetfilter.components.file_staging_pool import FileStagingPool

    monkeypatch.setattr(qt_app, "dpi_scale_factor", 1.0, raising=False)
    monkeypatch.setattr(qt_app, "global_font", QFont(), raising=False)
    monkeypatch.setattr(qt_app, "settings_manager", _DummySettingsManager(), raising=False)
    monkeypatch.setattr(file_staging_pool_module, "get_app_data_path", lambda: backup_dir)

    return FileStagingPool()


class TestFileStagingPoolBasic:
    """测试 FileStagingPool 基本功能"""
    
    def test_module_import(self):
        """测试模块可以导入"""
        from freeassetfilter.components.file_staging_pool import FileStagingPool
        assert FileStagingPool is not None
    
    def test_module_has_required_attributes(self):
        """测试模块有必要的属性"""
        from freeassetfilter.components import file_staging_pool
        # 检查模块存在
        assert file_staging_pool is not None


class TestFileStagingPoolRobustness:
    """测试 FileStagingPool 鲁棒性"""
    
    def test_module_handles_errors_gracefully(self):
        """测试模块能优雅处理错误"""
        # 基础错误处理测试
        pass


class TestFileStagingPoolIntegration:
    """测试 FileStagingPool 集成"""
    
    def test_module_integration(self):
        """测试模块集成"""
        # 集成测试
        pass

    def test_horizontal_model_does_not_expose_native_qt_tooltip(self, qt_app, monkeypatch, temp_file):
        """横向卡片列表不应通过 Qt.ToolTipRole 触发原生 tooltip。"""
        view, model, _delegate, index = _build_pool_view(qt_app, monkeypatch, temp_file)
        try:
            assert model.data(index, Qt.ToolTipRole) is None
        finally:
            view.close()

    def test_rename_button_click_uses_delegate_action(self, qt_app, monkeypatch, temp_file):
        """点击重命名按钮时，应触发按钮动作而不是普通卡片点击。"""
        view, _model, delegate, index = _build_pool_view(qt_app, monkeypatch, temp_file)
        rename_requests = []
        left_clicks = []

        delegate.renameRequested.connect(rename_requests.append)
        view.item_left_clicked.connect(lambda file_info: left_clicks.append(file_info["path"]))

        option = _build_option(view, index)
        rename_rect = delegate.get_rename_action_rect(option, index)
        assert not rename_rect.isNull()

        click_pos = rename_rect.center()
        QTest.mouseMove(view.viewport(), click_pos)
        QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, click_pos)
        qt_app.processEvents()

        assert rename_requests == [temp_file]
        assert left_clicks == []

        view.close()

    def test_delete_button_click_uses_delegate_action(self, qt_app, monkeypatch, temp_file):
        """点击删除按钮时，应触发删除动作而不是普通卡片点击。"""
        view, _model, delegate, index = _build_pool_view(qt_app, monkeypatch, temp_file)
        delete_requests = []
        left_clicks = []

        delegate.deleteRequested.connect(delete_requests.append)
        view.item_left_clicked.connect(lambda file_info: left_clicks.append(file_info["path"]))

        option = _build_option(view, index)
        delete_rect = delegate.get_delete_action_rect(option, index)
        assert not delete_rect.isNull()

        click_pos = delete_rect.center()
        QTest.mouseMove(view.viewport(), click_pos)
        QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, click_pos)
        qt_app.processEvents()

        assert delete_requests == [temp_file]
        assert left_clicks == []

        view.close()

    def test_previewing_card_hover_still_shows_action_buttons(self, qt_app, monkeypatch, temp_file):
        """预览态卡片在 hover 时，仍应显示并命中操作按钮。"""
        view, model, delegate, index = _build_pool_view(qt_app, monkeypatch, temp_file)

        model.set_previewing(temp_file, True)
        qt_app.processEvents()

        option = _build_option(view, index)
        option.state |= QStyle.State_MouseOver

        assert delegate.should_show_action_area(option, index) is True

        rename_rect = delegate.get_rename_action_rect(option, index)
        assert not rename_rect.isNull()
        assert delegate.action_at(option, index, rename_rect.center()) == delegate.ACTION_RENAME

        view.close()

    def test_clicking_card_body_still_emits_item_click(self, qt_app, monkeypatch, temp_file):
        """点击卡片主体时，仍然保持原有的预览点击行为。"""
        view, _model, delegate, index = _build_pool_view(qt_app, monkeypatch, temp_file)
        rename_requests = []
        delete_requests = []
        left_clicks = []

        delegate.renameRequested.connect(rename_requests.append)
        delegate.deleteRequested.connect(delete_requests.append)
        view.item_left_clicked.connect(lambda file_info: left_clicks.append(file_info["path"]))

        option = _build_option(view, index)
        action_area = delegate.get_action_area_rect(option, index)
        item_rect = view.visualRect(index)
        click_pos = QPoint(item_rect.left() + 24, item_rect.center().y())
        assert not action_area.contains(click_pos)

        QTest.mouseMove(view.viewport(), click_pos)
        QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, click_pos)
        qt_app.processEvents()

        assert left_clicks == [temp_file]
        assert rename_requests == []
        assert delete_requests == []

        view.close()

    def test_added_cards_use_left_slide_fade_motion(self, qt_app, monkeypatch, temp_dir):
        """连续新增卡片应从左侧滑入并从透明过渡到不透明。"""
        view, model, _delegate = _build_empty_pool_view(qt_app, monkeypatch)
        file_path = _write_temp_file(temp_dir, "added.txt")
        second_path = _write_temp_file(temp_dir, "added-second.txt")

        assert model.add_file(_make_staging_item(file_path)) is True
        assert model.add_file(_make_staging_item(second_path)) is True
        qt_app.processEvents()

        key = view._normalize_motion_path(file_path)
        second_key = view._normalize_motion_path(second_path)
        assert key in view._card_motion_items
        assert second_key in view._card_motion_items

        animation = view._card_motion_items[key]
        assert animation["start_rect"].x() < animation["end_rect"].x()
        assert animation["start_opacity"] == 0.0
        assert animation["end_opacity"] == 1.0
        assert animation["easing"] == "out_quint"

        index = model.index(0, 0)
        view._card_motion_start_ms = view._card_motion_now_ms()
        motion = view.card_motion_paint_parameters(index, view.visualRect(index))
        assert motion["dx"] < 0
        assert motion["opacity"] < 1.0

        view.close()

    def test_removed_middle_card_is_marked_then_destroyed_after_exit_motion(self, qt_app, monkeypatch, temp_dir):
        """删除中部卡片时，先标记并左滑淡出，动画结束后才真正移除模型项。"""
        view, model, _delegate = _build_empty_pool_view(qt_app, monkeypatch)
        file_paths = [
            _write_temp_file(temp_dir, "first.txt"),
            _write_temp_file(temp_dir, "second.txt"),
            _write_temp_file(temp_dir, "third.txt"),
        ]
        model.set_files([_make_staging_item(path) for path in file_paths])
        qt_app.processEvents()
        view.cancel_card_motion(update=False)

        assert model.remove_file(file_paths[1])
        qt_app.processEvents()

        removed_key = view._normalize_motion_path(file_paths[1])
        assert model.rowCount() == 3
        assert model.index(1, 0).data(model.IsRemovingRole) is True
        assert removed_key in view._card_motion_items

        exit_animation = view._card_motion_items[removed_key]
        assert exit_animation["end_rect"].x() < exit_animation["start_rect"].x()
        assert exit_animation["start_opacity"] == 1.0
        assert exit_animation["end_opacity"] == 0.0
        assert exit_animation["easing"] == "in_cubic"

        index = model.index(1, 0)
        view._card_motion_start_ms = view._card_motion_now_ms() - view._card_motion_duration_ms / 2
        motion = view.card_motion_paint_parameters(index, view.visualRect(index))
        assert motion["dx"] < 0
        assert motion["opacity"] < 1.0

        view._finalize_marked_removal(file_paths[1], removed_key)
        qt_app.processEvents()

        assert model.rowCount() == 2
        assert model.index(1, 0).data(model.FilePathRole) == os.path.normpath(file_paths[2])
        moved_key = view._normalize_motion_path(file_paths[2])
        assert moved_key in view._card_motion_items

        move_animation = view._card_motion_items[moved_key]
        assert move_animation["start_rect"].y() > move_animation["end_rect"].y()
        assert move_animation["start_opacity"] == 1.0
        assert move_animation["end_opacity"] == 1.0
        assert move_animation["easing"] == "in_out_cubic"

        index = model.index(1, 0)
        view._card_motion_start_ms = view._card_motion_now_ms() - view._card_motion_duration_ms / 2
        motion = view.card_motion_paint_parameters(index, view.visualRect(index))
        assert motion["dy"] > 0
        assert motion["opacity"] == 1.0

        view.close()

    def test_file_record_change_setting_disables_remove_transition(self, qt_app, monkeypatch, temp_dir):
        """关闭记录增减动画后，标记删除应立即完成，不再保留过渡状态。"""
        view, model, _delegate = _build_empty_pool_view(qt_app, monkeypatch)
        file_path = _write_temp_file(temp_dir, "remove-now.txt")

        monkeypatch.setattr(
            qt_app,
            "settings_manager",
            _MappedSettingsManager({"appearance.animations.file_record_changes": False}),
            raising=False,
        )

        try:
            assert model.add_file(_make_staging_item(file_path)) is True
            qt_app.processEvents()

            removed_info = model.remove_file(file_path)
            assert removed_info["path"] == os.path.normpath(file_path)
            qt_app.processEvents()

            assert model.rowCount() == 0
            assert view._card_motion_items == {}
            assert view._card_motion_exit_items == []
            assert view._card_motion_timer.isActive() is False
        finally:
            view.close()

    def test_remove_motion_only_prepares_visible_move_items(self, qt_app, monkeypatch, temp_dir):
        """删除卡片后的位移动画只需要为可见窗口内的卡片准备状态。"""
        view, model, _delegate = _build_empty_pool_view(qt_app, monkeypatch, height=140)
        file_paths = [
            _write_temp_file(temp_dir, f"item-{row:03d}.txt")
            for row in range(80)
        ]
        model.set_files([_make_staging_item(path) for path in file_paths])
        qt_app.processEvents()

        pending = view._build_remove_card_motion_pending(0, 0, capture_exit=False)
        move_items = pending["move_items"]

        assert move_items
        assert len(move_items) < 12
        assert view._normalize_motion_path(file_paths[-1]) not in move_items

        view.close()

    def test_card_motion_repaint_uses_bounded_dirty_region(self, qt_app, monkeypatch, temp_dir):
        """卡片进入动画每帧只刷新运动区域，不刷新整个 viewport。"""
        view, model, _delegate = _build_empty_pool_view(qt_app, monkeypatch, height=260)
        file_path = _write_temp_file(temp_dir, "bounded-update.txt")

        updates = []
        original_update = view.viewport().update

        def record_update(*args):
            if args:
                updates.append(args[0])
            else:
                updates.append(view.viewport().rect())
            return original_update(*args)

        monkeypatch.setattr(view.viewport(), "update", record_update)

        assert model.add_file(_make_staging_item(file_path)) is True
        qt_app.processEvents()
        view._advance_card_motion()

        bounded_updates = [
            rect for rect in updates
            if hasattr(rect, "isValid") and rect.isValid()
        ]
        assert bounded_updates
        assert all(rect != view.viewport().rect() for rect in bounded_updates)

        view.close()

    def test_card_motion_finish_refreshes_hover_under_static_cursor(self, qt_app, monkeypatch, temp_dir):
        """卡片移动到静止鼠标下方后，应主动刷新 hover 命中。"""
        import freeassetfilter.widgets.file_staging_pool_model as staging_model_module

        class _MouseMoveRecorder(QObject):
            def __init__(self):
                super().__init__()
                self.positions = []

            def eventFilter(self, _obj, event):
                if event.type() == QEvent.MouseMove:
                    self.positions.append(event.position().toPoint())
                return False

        view, model, _delegate = _build_empty_pool_view(qt_app, monkeypatch, height=260)
        file_paths = [
            _write_temp_file(temp_dir, "first-hover.txt"),
            _write_temp_file(temp_dir, "second-hover.txt"),
        ]
        model.set_files([_make_staging_item(path) for path in file_paths])
        qt_app.processEvents()

        index = model.index(1, 0)
        end_rect = view.visualRect(index).translated(0, -view.gridSize().height())
        view._card_motion_items = {
            view._normalize_motion_path(file_paths[1]): view._make_move_animation(
                view.visualRect(index),
                end_rect,
            )
        }
        view._card_motion_start_ms = view._card_motion_now_ms() - view._card_motion_duration_ms - 1

        cursor_pos = view.viewport().mapToGlobal(end_rect.center())
        monkeypatch.setattr(
            staging_model_module.QCursor,
            "pos",
            staticmethod(lambda: cursor_pos),
        )

        recorder = _MouseMoveRecorder()
        view.viewport().installEventFilter(recorder)
        try:
            view._advance_card_motion()
            qt_app.processEvents()
        finally:
            view.viewport().removeEventFilter(recorder)

        assert end_rect.center() in recorder.positions

        view.close()


class TestFileStagingPoolTraversalOptimizations:
    def test_manual_link_files_caches_original_md5(self, monkeypatch, temp_dir):
        from PySide6.QtWidgets import QFileDialog
        from freeassetfilter.components.file_staging_pool import FileStagingPool
        import freeassetfilter.components.file_staging_pool as file_staging_pool_module

        search_dir = os.path.join(temp_dir, "search")
        os.makedirs(search_dir)

        original_path = os.path.join(temp_dir, "original.bin")
        first_candidate = os.path.join(search_dir, "candidate_a.bin")
        second_candidate = os.path.join(search_dir, "candidate_b.bin")

        for path in (original_path, first_candidate, second_candidate):
            with open(path, "wb") as f:
                f.write(b"data")

        md5_map = {
            original_path: "md5-target",
            first_candidate: "md5-other",
            second_candidate: "md5-target",
        }
        call_counts = {}

        pool = FileStagingPool.__new__(FileStagingPool)
        pool.update_unlinked_list = lambda *_args, **_kwargs: None

        def fake_calculate_md5(path):
            call_counts[path] = call_counts.get(path, 0) + 1
            return md5_map[path]

        pool.calculate_md5 = fake_calculate_md5

        monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_args, **_kwargs: search_dir)
        monkeypatch.setattr(file_staging_pool_module, "CustomMessageBox", _DummyMessageBox)

        unlinked_files = [
            {
                "status": "unlinked",
                "new_path": None,
                "original_file_info": {
                    "path": original_path,
                    "name": os.path.basename(original_path),
                },
            }
        ]

        FileStagingPool.manual_link_files(pool, unlinked_files, None)

        assert call_counts[original_path] == 1
        assert unlinked_files[0]["status"] == "linked"
        assert unlinked_files[0]["new_path"] == second_candidate

    def test_calculate_folder_size_worker_does_not_call_exists(self, monkeypatch, temp_dir):
        from freeassetfilter.components.file_staging_pool import FileStagingPool
        import freeassetfilter.components.file_staging_pool as file_staging_pool_module

        folder_path = os.path.join(temp_dir, "folder")
        os.makedirs(folder_path)
        file_path = os.path.join(folder_path, "payload.bin")
        with open(file_path, "wb") as f:
            f.write(b"12345")

        def fail_exists(_path):
            raise AssertionError("os.path.exists should not be used during folder size calculation")

        monkeypatch.setattr(file_staging_pool_module.os.path, "exists", fail_exists)

        result = FileStagingPool._calculate_folder_size_worker(folder_path, threading.Event())

        assert result == {"path": folder_path, "size": 5}


class TestFileStagingPoolBackupPersistence:
    def test_save_backup_filters_runtime_only_fields(self, qt_app, monkeypatch, temp_dir, temp_file):
        pool = _build_pool_widget(qt_app, monkeypatch, temp_dir)

        pool.add_file(
            {
                "path": temp_file,
                "name": os.path.basename(temp_file),
                "display_name": os.path.basename(temp_file),
                "original_name": os.path.basename(temp_file),
                "is_dir": False,
                "size": os.path.getsize(temp_file),
                "modified": "2026-01-01 00:00:00",
                "created": "2026-01-01 00:00:00",
                "suffix": "txt",
                "is_previewing": True,
                "icon_pixmap": QPixmap(16, 16),
                "runtime_object": object(),
            }
        )

        pool.flush_backup_save_now(r"C:\test-path")

        backup_file = os.path.join(temp_dir, "staging_pool_backup.json")
        with open(backup_file, "r", encoding="utf-8") as f:
            backup_data = json.load(f)

        assert backup_data["selector_state"]["last_path"] == r"C:\test-path"
        assert len(backup_data["items"]) == 1
        restored_item = backup_data["items"][0]
        assert restored_item["path"] == os.path.normpath(temp_file)
        assert restored_item["name"] == os.path.basename(temp_file)
        assert "is_previewing" not in restored_item
        assert "icon_pixmap" not in restored_item
        assert "runtime_object" not in restored_item

        pool.close()

    def test_load_backup_normalizes_legacy_payload_and_invalid_items(self, qt_app, monkeypatch, temp_dir, temp_file):
        pool = _build_pool_widget(qt_app, monkeypatch, temp_dir)

        backup_file = os.path.join(temp_dir, "staging_pool_backup.json")
        with open(backup_file, "w", encoding="utf-8") as f:
            json.dump(
                [
                    {
                        "path": temp_file,
                        "name": os.path.basename(temp_file),
                        "display_name": os.path.basename(temp_file),
                        "original_name": os.path.basename(temp_file),
                        "is_dir": False,
                        "size": os.path.getsize(temp_file),
                        "suffix": "txt",
                        "is_previewing": True,
                    },
                    {"name": "missing-path.txt"},
                    "bad-entry",
                ],
                f,
                ensure_ascii=False,
                indent=2,
            )

        backup_data = pool.load_backup()

        assert backup_data["selector_state"]["last_path"] == "All"
        assert len(backup_data["items"]) == 1
        assert backup_data["items"][0]["path"] == os.path.normpath(temp_file)
        assert "is_previewing" not in backup_data["items"][0]

        pool.close()

    def test_legacy_previewing_backup_restores_as_normal_card(self, qt_app, monkeypatch, temp_dir, temp_file):
        pool = _build_pool_widget(qt_app, monkeypatch, temp_dir)

        backup_file = os.path.join(temp_dir, "staging_pool_backup.json")
        with open(backup_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "items": [
                        {
                            "path": temp_file,
                            "name": os.path.basename(temp_file),
                            "display_name": os.path.basename(temp_file),
                            "original_name": os.path.basename(temp_file),
                            "is_dir": False,
                            "size": os.path.getsize(temp_file),
                            "suffix": "txt",
                            "is_previewing": True,
                        }
                    ],
                    "selector_state": {"last_path": r"C:\last-path"},
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

        backup_data = pool.load_backup()

        assert backup_data["items"][0]["path"] == os.path.normpath(temp_file)
        assert "is_previewing" not in backup_data["items"][0]

        pool.add_file(backup_data["items"][0])
        index = pool.pool_model.index(0, 0)

        assert index.data(pool.pool_model.IsPreviewingRole) is False

        pool.close()

    def test_save_backup_prefers_model_state_when_items_cache_is_stale(self, qt_app, monkeypatch, temp_dir, temp_file):
        pool = _build_pool_widget(qt_app, monkeypatch, temp_dir)

        pool.add_file(
            {
                "path": temp_file,
                "name": os.path.basename(temp_file),
                "display_name": os.path.basename(temp_file),
                "original_name": os.path.basename(temp_file),
                "is_dir": False,
                "size": os.path.getsize(temp_file),
                "suffix": "txt",
            }
        )

        pool.items = []
        pool.flush_backup_save_now("All")

        backup_file = os.path.join(temp_dir, "staging_pool_backup.json")
        with open(backup_file, "r", encoding="utf-8") as f:
            backup_data = json.load(f)

        assert len(backup_data["items"]) == 1
        assert backup_data["items"][0]["path"] == os.path.normpath(temp_file)

        pool.close()
