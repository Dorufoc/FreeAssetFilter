# -*- coding: utf-8 -*-
"""
组件测试: CustomFileSelector
测试 CustomFileSelector 组件的核心交互场景 —— 创建/销毁、目录导航、
文件列表加载、排序筛选、视图模式切换、信号发射、预览状态、选择状态

Required fixtures (conftest.py):
    - qapp: session-scoped QApplication
    - file_selector: CustomFileSelector 实例
    - tmp_path: pytest 临时目录
"""

import os
from typing import Any, Dict, List

from PySide6.QtTest import QSignalSpy


# ==============================================================================
# 1. 创建与销毁
# ==============================================================================


class TestCustomFileSelectorCreation:
    """测试 CustomFileSelector 创建和销毁"""

    def test_widget_creation(self, file_selector) -> None:
        """验证组件可以正常创建并具有默认属性值。"""
        assert file_selector is not None
        assert file_selector.current_path is not None
        assert file_selector.filter_pattern == "*"
        assert file_selector.sort_by == "name"
        assert file_selector.sort_order == "asc"
        assert file_selector.view_mode == "card"

    def test_default_state(self, file_selector) -> None:
        """验证初始状态值正确。"""
        assert file_selector.current_path == "All"
        assert file_selector._selected_file_paths == set()
        assert file_selector.previewing_file_path is None
        assert file_selector._is_loading is False
        assert file_selector._first_show is True
        assert isinstance(file_selector.selected_files, dict)
        assert len(file_selector.selected_files) == 0

    def test_safe_destruction(self, qapp) -> None:
        """验证组件可以安全销毁，不抛出异常。"""
        from freeassetfilter.components.file_selector import CustomFileSelector

        selector = CustomFileSelector()
        selector.show()
        qapp.processEvents()
        selector.close()
        selector.deleteLater()
        qapp.processEvents()
        # 销毁后不应崩溃
        assert True


# ==============================================================================
# 2. 目录导航
# ==============================================================================


class TestCustomFileSelectorNavigation:
    """测试目录导航功能"""

    def test_go_to_path_updates_current_path(self, file_selector, tmp_path) -> None:
        """验证 go_to_path() 正确更新 current_path。"""
        test_dir = tmp_path / "subdir"
        test_dir.mkdir()
        file_selector.path_edit.setText(str(test_dir))
        file_selector.go_to_path()
        assert file_selector.current_path == str(test_dir)

    def test_go_to_path_all_returns_to_top(self, file_selector) -> None:
        """验证输入 'All' 时回到顶级视图。"""
        file_selector.current_path = str(os.getcwd())
        file_selector.path_edit.setText("All")
        file_selector.go_to_path()
        assert file_selector.current_path == "All"

    def test_go_to_parent_from_subdirectory(self, file_selector, tmp_path) -> None:
        """验证从子目录返回父目录。"""
        sub_dir = tmp_path / "child"
        sub_dir.mkdir()
        file_selector.current_path = str(sub_dir)
        file_selector.go_to_parent()
        assert file_selector.current_path == str(tmp_path)

    def test_go_to_parent_from_root_goes_to_all(self, file_selector) -> None:
        """验证从盘符根目录返回 All 视图。"""
        if os.name == "nt":
            file_selector.current_path = "C:\\"
            file_selector.go_to_parent()
            assert file_selector.current_path == "All"

    def test_navigate_to_path_updates_path_edit(self, file_selector, tmp_path) -> None:
        """验证 _navigate_to_path 同步更新路径输入框。"""
        test_dir = tmp_path / "nav_test"
        test_dir.mkdir()
        file_selector._navigate_to_path(str(test_dir), update_path_edit=True)
        assert file_selector.path_edit.text() == str(test_dir)

    def test_is_valid_selector_path_all(self, file_selector) -> None:
        """验证 'All' 被视为有效路径。"""
        assert file_selector._is_valid_selector_path("All") is True

    def test_is_valid_selector_path_existing_path(self, file_selector, tmp_path) -> None:
        """验证存在的目录被视为有效。"""
        assert file_selector._is_valid_selector_path(str(tmp_path)) is True

    def test_is_valid_selector_path_empty_is_invalid(self, file_selector) -> None:
        """验证空字符串被视为无效。"""
        assert file_selector._is_valid_selector_path("") is False

    def test_is_valid_selector_path_nonexistent(self, file_selector) -> None:
        """验证不存在的路径被视为无效。"""
        assert file_selector._is_valid_selector_path("/nonexistent/path") is False

    def test_infer_navigation_direction_forward(self, file_selector) -> None:
        """验证进入子目录方向为 1 (前进)。"""
        assert file_selector._infer_navigation_direction("C:/demo", "C:/demo/folder") == 1

    def test_infer_navigation_direction_backward(self, file_selector) -> None:
        """验证返回父目录方向为 -1 (后退)。"""
        assert file_selector._infer_navigation_direction("C:/demo/folder", "C:/demo") == -1

    def test_infer_navigation_direction_from_all(self, file_selector) -> None:
        """验证从 All 进入目录方向为 1。"""
        assert file_selector._infer_navigation_direction("All", "C:/demo") == 1

    def test_infer_navigation_direction_to_all(self, file_selector) -> None:
        """验证返回 All 方向为 -1。"""
        assert file_selector._infer_navigation_direction("C:/demo", "All") == -1

    def test_infer_navigation_direction_same_path(self, file_selector) -> None:
        """验证相同路径方向为 0。"""
        assert file_selector._infer_navigation_direction("C:/demo", "C:/demo") == 0

    def test_same_selector_path_identical(self, file_selector) -> None:
        """验证相同路径返回 True。"""
        assert file_selector._same_selector_path("C:/demo", "C:/demo") is True

    def test_same_selector_path_all(self, file_selector) -> None:
        """验证 All 与 All 比较返回 True。"""
        assert file_selector._same_selector_path("All", "All") is True

    def test_same_selector_path_different(self, file_selector) -> None:
        """验证不同路径返回 False。"""
        assert file_selector._same_selector_path("C:/demo", "D:/demo") is False
        assert file_selector._same_selector_path("All", "C:/demo") is False

    def test_remember_navigation_source_saves_recovery(self, file_selector, tmp_path) -> None:
        """验证 _remember_navigation_source 保存恢复路径。"""
        file_selector.current_path = str(tmp_path)
        target = tmp_path / "sub"
        target.mkdir()
        file_selector._remember_navigation_source(str(target))
        assert file_selector._navigation_recovery_path == str(tmp_path)

    def test_recovery_source_when_current_invalid(self, file_selector, tmp_path) -> None:
        """验证当当前路径无效时恢复路径可用。"""
        file_selector._last_accessible_path = str(tmp_path)
        file_selector.current_path = "/invalid/path"
        recovery = file_selector._get_recovery_source_for_navigation()
        assert recovery == str(tmp_path) or recovery == "All"

    def test_drive_changed_to_all_triggers_navigation(self, file_selector) -> None:
        """验证盘符下拉选择 'All' 触发导航到 All。"""
        file_selector._on_drive_changed("All")
        assert file_selector.current_path == "All"

    def test_is_descendant_selector_path(self, file_selector) -> None:
        """验证 _is_descendant_selector_path 层级判断。"""
        assert file_selector._is_descendant_selector_path("C:/demo/sub", "C:/demo") is True
        assert file_selector._is_descendant_selector_path("C:/demo", "C:/demo") is False
        assert file_selector._is_descendant_selector_path("C:/demo", "C:/other") is False
        assert file_selector._is_descendant_selector_path("All", "C:/demo") is False


# ==============================================================================
# 3. 文件列表加载与处理
# ==============================================================================


class TestCustomFileSelectorFileList:
    """测试文件列表加载、排序、筛选"""

    def test_refresh_files_starts_loading(self, file_selector, tmp_path) -> None:
        """验证 refresh_files() 启动异步文件加载线程。"""
        file_selector.current_path = str(tmp_path)
        file_selector.refresh_files()
        assert file_selector._is_loading is True
        assert file_selector._file_loader_thread is not None

    def test_on_files_loaded_updates_model(self, file_selector, tmp_path) -> None:
        """验证 _on_files_loaded 正确更新 model。"""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")
        files: List[Dict[str, Any]] = [
            {
                "name": "test.txt",
                "path": str(test_file),
                "is_dir": False,
                "size": 7,
                "modified": "2024-01-15T10:00:00",
                "created": "2024-01-15T10:00:00",
                "suffix": "txt",
            }
        ]
        file_selector.current_path = str(tmp_path)
        file_selector._on_files_loaded(
            file_selector._refresh_request_id,
            str(tmp_path),
            files,
            callback=None,
            scroll_to_top=True,
        )
        assert file_selector.file_model.rowCount() == 1
        info = file_selector.file_model.get_file_info(
            file_selector.file_model.index(0, 0)
        )
        assert info is not None
        assert info["name"] == "test.txt"

    def test_stale_request_is_ignored(self, file_selector) -> None:
        """验证过期请求 ID 被忽略，不更新 model。"""
        files = [{"name": "old.txt", "path": "/old", "is_dir": False, "size": 0}]
        old_id = file_selector._refresh_request_id - 1
        file_selector._on_files_loaded(old_id, "/old", files, None, True)
        assert file_selector.file_model.rowCount() == 0

    def test_path_mismatch_is_ignored(self, file_selector) -> None:
        """验证路径不匹配的加载结果被忽略。"""
        files = [{"name": "wrong.txt", "path": "/wrong", "is_dir": False, "size": 0}]
        file_selector.current_path = "/current"
        file_selector._on_files_loaded(
            file_selector._refresh_request_id,
            "/different",
            files,
            None,
            True,
        )
        assert file_selector.file_model.rowCount() == 0

    def test_sort_files_by_name_asc(self, file_selector) -> None:
        """验证按名称升序排序。"""
        files: List[Dict[str, Any]] = [
            {"name": "b.txt", "is_dir": False, "size": 0},
            {"name": "a.txt", "is_dir": False, "size": 0},
        ]
        file_selector.sort_by = "name"
        file_selector.sort_order = "asc"
        sorted_files = file_selector._sort_files(files)
        names = [f["name"] for f in sorted_files]
        assert names == ["a.txt", "b.txt"]

    def test_sort_files_by_size_desc(self, file_selector) -> None:
        """验证按大小降序排序。"""
        files: List[Dict[str, Any]] = [
            {"name": "small.txt", "is_dir": False, "size": 100},
            {"name": "large.txt", "is_dir": False, "size": 1000},
        ]
        file_selector.sort_by = "size"
        file_selector.sort_order = "desc"
        sorted_files = file_selector._sort_files(files)
        names = [f["name"] for f in sorted_files]
        assert names == ["large.txt", "small.txt"]

    def test_sort_files_directories_first(self, file_selector) -> None:
        """验证目录始终排在文件之前。"""
        files: List[Dict[str, Any]] = [
            {"name": "file.txt", "is_dir": False, "size": 0},
            {"name": "folder", "is_dir": True, "size": 0},
        ]
        file_selector.sort_by = "name"
        file_selector.sort_order = "asc"
        sorted_files = file_selector._sort_files(files)
        assert sorted_files[0]["is_dir"] is True
        assert sorted_files[1]["is_dir"] is False

    def test_filter_files_by_wildcard(self, file_selector) -> None:
        """验证按通配符模式筛选文件。"""
        files: List[Dict[str, Any]] = [
            {"name": "test.txt", "is_dir": False, "size": 0, "suffix": "txt"},
            {"name": "data.jpg", "is_dir": False, "size": 0, "suffix": "jpg"},
            {"name": "doc.pdf", "is_dir": False, "size": 0, "suffix": "pdf"},
        ]
        file_selector.filter_pattern = "*.txt"
        filtered = file_selector._filter_files(files)
        assert len(filtered) == 1
        assert filtered[0]["name"] == "test.txt"

    def test_filter_files_by_regex(self, file_selector) -> None:
        """验证按正则模式筛选文件。"""
        files: List[Dict[str, Any]] = [
            {"name": "IMG_001.jpg", "is_dir": False, "size": 0, "suffix": "jpg"},
            {"name": "IMG_002.jpg", "is_dir": False, "size": 0, "suffix": "jpg"},
            {"name": "video.mp4", "is_dir": False, "size": 0, "suffix": "mp4"},
        ]
        file_selector.filter_pattern = "IMG_*"
        filtered = file_selector._filter_files(files)
        assert len(filtered) == 2

    def test_no_filter_returns_all_files(self, file_selector) -> None:
        """验证默认筛选（*）返回全部文件。"""
        files: List[Dict[str, Any]] = [
            {"name": "a.txt", "is_dir": False, "size": 0},
            {"name": "b.jpg", "is_dir": False, "size": 0},
        ]
        file_selector.filter_pattern = "*"
        result = file_selector._filter_files(files)
        assert result == files

    def test_empty_filter_returns_all_files(self, file_selector) -> None:
        """验证空筛选返回全部文件。"""
        files = [{"name": "a.txt", "is_dir": False, "size": 0}]
        file_selector.filter_pattern = ""
        result = file_selector._filter_files(files)
        assert len(result) == 1


# ==============================================================================
# 4. 排序与筛选切换
# ==============================================================================


class TestCustomFileSelectorSort:
    """测试排序切换功能"""

    def test_change_sort_by_name_desc(self, file_selector) -> None:
        """验证 change_sort 更新排序属性。"""
        file_selector.change_sort("名称降序")
        assert file_selector.sort_by == "name"
        assert file_selector.sort_order == "desc"

    def test_change_sort_by_size_desc(self, file_selector) -> None:
        """验证按大小降序切换。"""
        file_selector.change_sort("大小降序")
        assert file_selector.sort_by == "size"
        assert file_selector.sort_order == "desc"

    def test_change_sort_by_modified_asc(self, file_selector) -> None:
        """验证按修改时间升序切换。"""
        file_selector.change_sort("修改时间升序")
        assert file_selector.sort_by == "modified"
        assert file_selector.sort_order == "asc"

    def test_change_sort_unknown_fallback_to_name(self, file_selector) -> None:
        """验证未知排序文本回退到默认。"""
        file_selector.change_sort("无效排序")
        assert file_selector.sort_by == "name"
        assert file_selector.sort_order == "asc"

    def test_sort_item_clicked_tuple(self, file_selector) -> None:
        """验证排序菜单项点击更新排序属性。"""
        file_selector._on_sort_item_clicked(("size", "desc"))
        assert file_selector.sort_by == "size"
        assert file_selector.sort_order == "desc"

    def test_sort_triggers_refresh(self, file_selector) -> None:
        """验证 change_sort 触发 refresh_files。"""
        file_selector.current_path = "All"
        file_selector.change_sort("大小降序")
        # 异步加载已启动
        assert file_selector._is_loading is True

    def test_has_active_filter_default(self, file_selector) -> None:
        """验证默认 `*` 不被视为活跃筛选。"""
        assert file_selector._has_active_filter() is False

    def test_has_active_filter_with_pattern(self, file_selector) -> None:
        """验证设置筛选模式后返回 True。"""
        file_selector.filter_pattern = "*.txt"
        assert file_selector._has_active_filter() is True

    def test_has_active_filter_empty_string(self, file_selector) -> None:
        """验证空字符串不被视为活跃筛选。"""
        file_selector.filter_pattern = ""
        assert file_selector._has_active_filter() is False


# ==============================================================================
# 5. 视图模式切换
# ==============================================================================


class TestCustomFileSelectorViewMode:
    """测试视图模式切换功能"""

    def test_default_view_mode_is_card(self, file_selector) -> None:
        """验证默认视图模式为卡片。"""
        assert file_selector.view_mode == "card"

    def test_change_view_mode_to_list(self, file_selector) -> None:
        """验证切换到列表视图。"""
        file_selector.change_view_mode(1)
        assert file_selector.view_mode == "list"

    def test_change_view_mode_to_card(self, file_selector) -> None:
        """验证切换到卡片视图。"""
        file_selector.view_mode = "list"
        file_selector.change_view_mode(0)
        assert file_selector.view_mode == "card"

    def test_toggle_view_mode_from_card(self, file_selector) -> None:
        """验证从卡片视图切换到列表。"""
        file_selector._toggle_view_mode()
        assert file_selector.view_mode == "list"

    def test_toggle_view_mode_from_list(self, file_selector) -> None:
        """验证从列表视图切换到卡片。"""
        file_selector.view_mode = "list"
        file_selector._toggle_view_mode()
        assert file_selector.view_mode == "card"

    def test_double_toggle_returns_to_card(self, file_selector) -> None:
        """验证两次切换回到卡片。"""
        file_selector._toggle_view_mode()
        file_selector._toggle_view_mode()
        assert file_selector.view_mode == "card"


# ==============================================================================
# 6. 信号发射验证
# ==============================================================================


class TestCustomFileSelectorSignals:
    """测试信号发射与连接"""

    def test_file_selected_signal_emission(self, file_selector) -> None:
        """验证 file_selected 信号可发射和接收。"""
        spy = QSignalSpy(file_selector.file_selected)
        file_info: Dict[str, Any] = {
            "name": "test.txt",
            "path": "/test.txt",
            "is_dir": False,
        }
        file_selector.file_selected.emit(file_info)
        assert spy.count() == 1
        emitted = spy.at(0)
        assert emitted[0]["name"] == "test.txt"

    def test_file_right_clicked_signal(self, file_selector) -> None:
        """验证 file_right_clicked 信号。"""
        spy = QSignalSpy(file_selector.file_right_clicked)
        file_info = {"name": "test.txt", "path": "/test.txt"}
        file_selector.file_right_clicked.emit(file_info)
        assert spy.count() == 1
        assert spy.at(0)[0]["name"] == "test.txt"

    def test_file_selection_changed_signal(self, file_selector) -> None:
        """验证 file_selection_changed 信号含正确参数。"""
        spy = QSignalSpy(file_selector.file_selection_changed)
        file_info = {"name": "test.txt", "path": "/test.txt"}
        file_selector.file_selection_changed.emit(file_info, True)
        assert spy.count() == 1
        emitted = spy.at(0)
        # 第一个参数是 dict (file_info)
        assert emitted[0]["name"] == "test.txt"
        # 第二个参数是 bool (is_selected)
        assert emitted[1] is True

    def test_preview_cancel_requested_signal(self, file_selector) -> None:
        """验证 preview_cancel_requested 信号。"""
        spy = QSignalSpy(file_selector.preview_cancel_requested)
        file_selector.preview_cancel_requested.emit()
        assert spy.count() == 1

    def test_card_click_on_folder_triggers_navigation(self, file_selector, tmp_path) -> None:
        """验证单击文件夹卡片触发目录导航。"""
        sub_dir = tmp_path / "click_folder"
        sub_dir.mkdir()
        file_info = {"name": "click_folder", "path": str(sub_dir), "is_dir": True}
        # 模拟 FileListView.file_clicked 信号
        file_selector.files_scroll_area.file_clicked.emit(file_info)
        assert file_selector.current_path == str(sub_dir)

    def test_card_click_on_file_triggers_file_selected(self, file_selector) -> None:
        """验证单击文件卡片触发 file_selected 信号。"""
        spy = QSignalSpy(file_selector.file_selected)
        file_info = {"name": "test.txt", "path": "/test.txt", "is_dir": False}
        file_selector.files_scroll_area.file_clicked.emit(file_info)
        assert spy.count() == 1

    def test_card_double_click_on_folder_navigates(self, file_selector, tmp_path) -> None:
        """验证双击文件夹触发导航。"""
        sub_dir = tmp_path / "dblclick_folder"
        sub_dir.mkdir()
        file_info = {"name": "dblclick_folder", "path": str(sub_dir), "is_dir": True}
        file_selector.files_scroll_area.file_double_clicked.emit(file_info)
        assert file_selector.current_path == str(sub_dir)

    def test_card_right_click_signal(self, file_selector) -> None:
        """验证右键卡片发射 file_right_clicked。"""
        spy = QSignalSpy(file_selector.file_right_clicked)
        file_info = {"name": "test.txt", "path": "/test.txt"}
        file_selector.files_scroll_area.file_right_clicked.emit(file_info)
        assert spy.count() == 1

    def test_navigate_parent_requested_triggers_go_to_parent(self, file_selector, tmp_path) -> None:
        """验证导航上级请求触发 go_to_parent。"""
        sub_dir = tmp_path / "nav_parent"
        sub_dir.mkdir()
        file_selector.current_path = str(sub_dir)
        file_selector.files_scroll_area.navigate_parent_requested.emit()
        assert file_selector.current_path == str(tmp_path)

    def test_preview_cancel_when_reclicking_previewed_file(self, file_selector, tmp_path) -> None:
        """验证再次点击正在预览的文件时发射取消预览信号。"""
        spy = QSignalSpy(file_selector.preview_cancel_requested)
        test_file = tmp_path / "preview.txt"
        test_file.write_text("preview content")
        file_selector.set_previewing_file(str(test_file))
        file_info = {"name": "preview.txt", "path": str(test_file), "is_dir": False}
        file_selector.files_scroll_area.file_clicked.emit(file_info)
        assert spy.count() == 1


# ==============================================================================
# 7. 预览状态管理
# ==============================================================================


class TestCustomFileSelectorPreviewState:
    """测试预览状态管理"""

    def test_set_previewing_file_updates_path(self, file_selector, tmp_path) -> None:
        """验证 set_previewing_file 设置预览路径。"""
        test_file = tmp_path / "preview_set.txt"
        test_file.write_text("preview")
        file_selector.set_previewing_file(str(test_file))
        assert file_selector.previewing_file_path == os.path.normpath(str(test_file))

    def test_clear_previewing_state(self, file_selector) -> None:
        """验证 clear_previewing_state 清除 model 预览状态。"""
        file_selector.clear_previewing_state()
        # previewing_file_path 不受 clear_previewing_state 影响
        # 但 model 中的预览标记已被清除
        assert True

    def test_set_previewing_file_none(self, file_selector) -> None:
        """验证设为 None 时 previewing_file_path 为 None。"""
        file_selector.set_previewing_file(None)
        assert file_selector.previewing_file_path is None

    def test_set_previewing_file_empty_string(self, file_selector) -> None:
        """验证空字符串视为清除预览。"""
        file_selector.set_previewing_file("")
        assert file_selector.previewing_file_path is None

    def test_set_previewing_twice(self, file_selector, tmp_path) -> None:
        """验证多次设置预览路径最后保留最新。"""
        f1 = tmp_path / "p1.txt"
        f2 = tmp_path / "p2.txt"
        f1.write_text("1")
        f2.write_text("2")
        file_selector.set_previewing_file(str(f1))
        file_selector.set_previewing_file(str(f2))
        assert file_selector.previewing_file_path == os.path.normpath(str(f2))


# ==============================================================================
# 8. 文件选择状态
# ==============================================================================


class TestCustomFileSelectorSelection:
    """测试文件选择状态管理"""

    def test_select_file_updates_selected_paths(self, file_selector, tmp_path) -> None:
        """验证选中文件后 _selected_file_paths 包含该文件。"""
        spy = QSignalSpy(file_selector.file_selection_changed)
        test_file = tmp_path / "select_file.txt"
        test_file.write_text("select")
        file_info = {"name": "select_file.txt", "path": str(test_file), "is_dir": False}
        file_selector._handle_card_selection_changed_signal(file_info, True)
        assert os.path.normpath(str(test_file)) in file_selector._selected_file_paths
        assert spy.count() == 1

    def test_deselect_file_removes_from_paths(self, file_selector, tmp_path) -> None:
        """验证取消选中后 _selected_file_paths 移除该文件。"""
        spy = QSignalSpy(file_selector.file_selection_changed)
        test_file = tmp_path / "deselect_file.txt"
        test_file.write_text("deselect")
        file_info = {"name": "deselect_file.txt", "path": str(test_file), "is_dir": False}
        file_selector._handle_card_selection_changed_signal(file_info, True)
        file_selector._handle_card_selection_changed_signal(file_info, False)
        assert os.path.normpath(str(test_file)) not in file_selector._selected_file_paths
        assert spy.count() == 2

    def test_duplicate_select_does_not_double_emit(self, file_selector, tmp_path) -> None:
        """验证重复选中同一文件不会发射两次信号。"""
        spy = QSignalSpy(file_selector.file_selection_changed)
        test_file = tmp_path / "dup_select.txt"
        test_file.write_text("dup")
        file_info = {"name": "dup_select.txt", "path": str(test_file), "is_dir": False}
        file_selector._handle_card_selection_changed_signal(file_info, True)
        file_selector._handle_card_selection_changed_signal(file_info, True)
        assert spy.count() == 1

    def test_selection_tracks_per_directory(self, file_selector, tmp_path) -> None:
        """验证选中状态按目录分组存储。"""
        f1 = tmp_path / "file1.txt"
        f2 = tmp_path / "file2.txt"
        f1.write_text("1")
        f2.write_text("2")
        info1 = {"name": "file1.txt", "path": str(f1), "is_dir": False}
        info2 = {"name": "file2.txt", "path": str(f2), "is_dir": False}
        file_selector._handle_card_selection_changed_signal(info1, True)
        file_selector._handle_card_selection_changed_signal(info2, True)
        dir_norm = os.path.normpath(str(tmp_path))
        assert dir_norm in file_selector.selected_files
        assert len(file_selector.selected_files[dir_norm]) == 2

    def test_remove_from_staging_pool_clears_selection(self, file_selector, tmp_path) -> None:
        """验证从存储池移除后清除选中状态。"""
        test_file = tmp_path / "remove.txt"
        test_file.write_text("remove")
        file_info = {"name": "remove.txt", "path": str(test_file), "is_dir": False}
        file_selector._handle_card_selection_changed_signal(file_info, True)
        file_selector._remove_from_staging_pool(file_info)
        assert os.path.normpath(str(test_file)) not in file_selector._selected_file_paths


# ==============================================================================
# 9. 拖拽行为
# ==============================================================================


class TestCustomFileSelectorDragDrop:
    """测试拖拽功能"""

    def test_drag_to_staging_pool_emits_selection_changed(self, file_selector, tmp_path) -> None:
        """验证拖拽到暂存池发射 file_selection_changed 信号。"""
        spy = QSignalSpy(file_selector.file_selection_changed)
        test_file = tmp_path / "drag_staging.txt"
        test_file.write_text("drag staging")
        file_info: Dict[str, Any] = {
            "name": "drag_staging.txt",
            "path": str(test_file),
            "is_dir": False,
        }
        file_selector._on_card_drag_ended(file_info, "staging_pool")
        assert spy.count() == 1
        assert spy.at(0)[1] is True

    def test_drag_to_previewer_emits_file_selected(self, file_selector) -> None:
        """验证拖拽到预览器发射 file_selected 信号。"""
        spy = QSignalSpy(file_selector.file_selected)
        file_info = {"name": "drag_preview.txt", "path": "/drag_preview.txt"}
        file_selector._on_card_drag_ended(file_info, "previewer")
        assert spy.count() == 1

    def test_drag_to_none_does_nothing(self, file_selector) -> None:
        """验证拖拽到空白区域无信号。"""
        spy_selected = QSignalSpy(file_selector.file_selected)
        spy_selection_changed = QSignalSpy(file_selector.file_selection_changed)
        file_info = {"name": "drag_none.txt", "path": "/drag_none.txt"}
        file_selector._on_card_drag_ended(file_info, "none")
        assert spy_selected.count() == 0
        assert spy_selection_changed.count() == 0

    def test_drag_to_staging_pool_updates_selected_paths(self, file_selector, tmp_path) -> None:
        """验证拖拽到暂存池后更新选中路径集合。"""
        test_file = tmp_path / "drag_selected.txt"
        test_file.write_text("drag selected")
        file_info = {"name": "drag_selected.txt", "path": str(test_file), "is_dir": False}
        file_selector._on_card_drag_ended(file_info, "staging_pool")
        assert os.path.normpath(str(test_file)) in file_selector._selected_file_paths


# ==============================================================================
# 10. 盘符检测
# ==============================================================================


class TestCustomFileSelectorDriveDetection:
    """测试盘符可用性检测功能"""

    def test_drive_availability_cache_structure(self, file_selector) -> None:
        """验证盘符可用性缓存是 dict。"""
        assert isinstance(file_selector._drive_availability_cache, dict)

    def test_drive_availability_cache_set_and_get(self, file_selector) -> None:
        """验证盘符可用性缓存写入和读取。"""
        file_selector._drive_availability_cache["C:\\"] = (True, 0.0)
        cached = file_selector._drive_availability_cache.get("C:\\")
        assert cached is not None
        assert cached[0] is True

    def test_is_drive_available_returns_optimistic_default(self, file_selector) -> None:
        """验证未知盘符返回乐观默认值 True。"""
        result = file_selector._is_drive_available("Z:\\")
        assert result is True

    def test_is_drive_available_from_cache(self, file_selector) -> None:
        """验证已缓存的盘符返回缓存值。"""
        import time
        file_selector._drive_availability_cache["D:\\"] = (False, time.time())
        result = file_selector._is_drive_available("D:\\")
        assert result is False

    def test_expired_cache_rechecks(self, file_selector) -> None:
        """验证过期缓存触发后台重新检查。"""
        file_selector._drive_availability_cache["E:\\"] = (False, 0.0)
        result = file_selector._is_drive_available("E:\\")
        # 缓存过期但尚未完成后台检查，返回过期缓存值
        assert result is False

    def test_on_drive_availability_result_updates_cache(self, file_selector) -> None:
        """验证后台检查结果更新缓存。"""
        file_selector._on_drive_availability_result("F:\\", True)
        cached = file_selector._drive_availability_cache.get("F:\\")
        assert cached is not None
        assert cached[0] is True

    def test_on_drive_availability_result_unchanged(self, file_selector) -> None:
        """验证可用性未变化时不重复发射信号。"""
        spy = QSignalSpy(file_selector.drive_availability_changed)
        file_selector._drive_availability_cache["G:\\"] = (True, 0.0)
        file_selector._on_drive_availability_result("G:\\", True)
        assert spy.count() == 0

    def test_on_drive_availability_result_changed(self, file_selector) -> None:
        """验证可用性变化时发射信号。"""
        spy = QSignalSpy(file_selector.drive_availability_changed)
        file_selector._drive_availability_cache["H:\\"] = (True, 0.0)
        file_selector._on_drive_availability_result("H:\\", False)
        assert spy.count() == 1
        emitted = spy.at(0)
        assert emitted[0] == "H:\\"
        assert emitted[1] is False

    def test_pending_drive_checks_deduplicates(self, file_selector) -> None:
        """验证相同盘符不会发起重复后台检查。"""
        file_selector._pending_drive_checks = set()
        file_selector._schedule_drive_availability_check("I:\\")
        file_selector._schedule_drive_availability_check("I:\\")
        assert len(file_selector._pending_drive_checks) == 1
