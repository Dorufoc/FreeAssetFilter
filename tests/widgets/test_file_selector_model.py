# -*- coding: utf-8 -*-
"""
FileSelectorListModel 和 FileListView 单元测试
"""

from typing import Any, Dict, List

import pytest
from PySide6.QtCore import QModelIndex, QSize, Qt, QPointF
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QListView

from freeassetfilter.widgets.file_selector_model import (
    FileSelectorListModel,
    FileListView,
)

# ── helpers ──────────────────────────────────────────────────────


def make_file_info(
    path: str,
    name: str = "",
    is_dir: bool = False,
    size: int = 0,
    suffix: str = "",
    created: str = "",
    **extra: Any,
) -> Dict[str, Any]:
    """构建标准 file_info 字典"""
    result: Dict[str, Any] = {
        "path": path,
        "name": name or path.split("/")[-1],
        "is_dir": is_dir,
        "size": size,
        "suffix": suffix or (path.split(".")[-1] if "." in path else ""),
        "created": created,
    }
    result.update(extra)
    return result


def sample_files() -> List[Dict[str, Any]]:
    """构造一组样本文件数据"""
    return [
        make_file_info("C:/photos/sunset.jpg", name="sunset.jpg", size=204800, suffix="jpg"),
        make_file_info("C:/docs/report.pdf", name="report.pdf", size=512000, suffix="pdf"),
        make_file_info("C:/videos/clip.mp4", name="clip.mp4", size=1048576, suffix="mp4"),
        make_file_info("C:/photos/vacation", name="vacation", is_dir=True, suffix=""),
        make_file_info("C:/docs/notes.txt", name="notes.txt", size=4096, suffix="txt"),
    ]


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def model(qapp):
    """提供 FileSelectorListModel 实例"""
    m = FileSelectorListModel(dpi_scale=1.0)
    yield m
    m.deleteLater()


@pytest.fixture
def filled_model(qapp):
    """提供已填充 5 条数据的模型"""
    m = FileSelectorListModel(dpi_scale=1.0)
    m.set_files(sample_files())
    yield m
    m.deleteLater()


@pytest.fixture
def view(qapp):
    """提供 FileListView 实例"""
    v = FileListView()
    yield v
    v.close()
    v.deleteLater()


# ══════════════════════════════════════════════════════════════════
# FileSelectorListModel 测试
# ══════════════════════════════════════════════════════════════════


class TestFileSelectorListModelCreation:
    """模型创建"""

    def test_create_default(self, model: FileSelectorListModel) -> None:
        """默认参数创建模型"""
        assert model.rowCount() == 0
        assert isinstance(model, FileSelectorListModel)

    def test_create_with_settings_manager(self, qapp) -> None:
        """传入 settings_manager 创建模型"""
        from freeassetfilter.core.settings_manager import SettingsManager

        sm = SettingsManager()
        m = FileSelectorListModel(settings_manager=sm)
        assert m.rowCount() == 0
        m.deleteLater()

    def test_create_with_custom_params(self, qapp) -> None:
        """传入 dpi_scale 和 global_font"""
        from PySide6.QtGui import QFont

        font = QFont("Arial", 10)
        m = FileSelectorListModel(dpi_scale=1.5, global_font=font)
        assert m.rowCount() == 0
        m.deleteLater()


class TestFileSelectorListModelRowColumnCount:
    """rowCount / columnCount"""

    def test_row_count_initially_zero(self, model: FileSelectorListModel) -> None:
        assert model.rowCount() == 0

    def test_row_count_after_set_files(self, filled_model: FileSelectorListModel) -> None:
        assert filled_model.rowCount() == 5

    def test_row_count_with_valid_parent(self, filled_model: FileSelectorListModel) -> None:
        """传入有效的 QModelIndex 应返回 0（列表模型无子项）"""
        idx = filled_model.index(0, 0)
        assert filled_model.rowCount(idx) == 0

    def test_column_count(self, model: FileSelectorListModel) -> None:
        """QAbstractListModel 默认 columnCount 返回 1"""
        # PySide6 6.11+ marks columnCount as private on QAbstractListModel;
        # verify indirectly: list models have exactly 1 column, so column >= 1 is invalid
        model.set_files([{"path": "/f.txt", "name": "f.txt", "size": 0, "created": ""}])
        idx0 = model.index(0, 0)
        assert idx0.isValid()
        idx_bad = model.index(0, 1)
        assert not idx_bad.isValid()


class TestFileSelectorListModelData:
    """data() 方法"""

    def test_data_invalid_index(self, filled_model: FileSelectorListModel) -> None:
        """无效索引应返回 None"""
        assert filled_model.data(QModelIndex(), Qt.DisplayRole) is None
        invalid_idx = filled_model.index(999, 0)
        assert filled_model.data(invalid_idx, Qt.DisplayRole) is None

    def test_data_display_role(self, filled_model: FileSelectorListModel) -> None:
        """Qt.DisplayRole 应返回文件名"""
        idx0 = filled_model.index(0, 0)
        assert filled_model.data(idx0, Qt.DisplayRole) == "sunset.jpg"

        idx1 = filled_model.index(1, 0)
        assert filled_model.data(idx1, Qt.DisplayRole) == "report.pdf"

    def test_data_file_path_role(self, filled_model: FileSelectorListModel) -> None:
        idx2 = filled_model.index(2, 0)
        assert filled_model.data(idx2, FileSelectorListModel.FilePathRole) == "C:/videos/clip.mp4"

    def test_data_file_name_role(self, filled_model: FileSelectorListModel) -> None:
        idx0 = filled_model.index(0, 0)
        assert filled_model.data(idx0, FileSelectorListModel.FileNameRole) == "sunset.jpg"

    def test_data_is_dir_role(self, filled_model: FileSelectorListModel) -> None:
        idx0 = filled_model.index(0, 0)
        assert filled_model.data(idx0, FileSelectorListModel.IsDirRole) is False

        idx3 = filled_model.index(3, 0)
        assert filled_model.data(idx3, FileSelectorListModel.IsDirRole) is True

    def test_data_file_size_role(self, filled_model: FileSelectorListModel) -> None:
        idx0 = filled_model.index(0, 0)
        assert filled_model.data(idx0, FileSelectorListModel.FileSizeRole) == 204800

    def test_data_suffix_role(self, filled_model: FileSelectorListModel) -> None:
        idx1 = filled_model.index(1, 0)
        assert filled_model.data(idx1, FileSelectorListModel.SuffixRole) == "pdf"

    def test_data_created_role(self, filled_model: FileSelectorListModel) -> None:
        idx0 = filled_model.index(0, 0)
        assert filled_model.data(idx0, FileSelectorListModel.CreatedRole) == ""

    def test_data_is_selected_role_initially_false(self, filled_model: FileSelectorListModel) -> None:
        idx0 = filled_model.index(0, 0)
        assert filled_model.data(idx0, FileSelectorListModel.IsSelectedRole) is False

    def test_data_is_previewing_role_initially_false(self, filled_model: FileSelectorListModel) -> None:
        idx0 = filled_model.index(0, 0)
        assert filled_model.data(idx0, FileSelectorListModel.IsPreviewingRole) is False

    def test_data_card_width_role(self, filled_model: FileSelectorListModel) -> None:
        idx0 = filled_model.index(0, 0)
        width = filled_model.data(idx0, FileSelectorListModel.CardWidthRole)
        assert isinstance(width, int)
        assert width > 0

    def test_data_grid_offset_role(self, filled_model: FileSelectorListModel) -> None:
        idx0 = filled_model.index(0, 0)
        offset = filled_model.data(idx0, FileSelectorListModel.GridOffsetRole)
        assert isinstance(offset, int)

    def test_data_unknown_role(self, filled_model: FileSelectorListModel) -> None:
        """未识别的角色应返回 None"""
        idx0 = filled_model.index(0, 0)
        assert filled_model.data(idx0, Qt.ToolTipRole) is None

    def test_data_icon_pixmap_role(self, filled_model: FileSelectorListModel) -> None:
        """IconPixmapRole 应返回 QPixmap 或 None"""
        idx0 = filled_model.index(0, 0)
        result = filled_model.data(idx0, FileSelectorListModel.IconPixmapRole)
        # 可能是 None 或 QPixmap（取决于系统环境）
        from PySide6.QtGui import QPixmap
        assert result is None or isinstance(result, QPixmap)


class TestFileSelectorListModelSetData:
    """setData() 方法"""

    def test_set_data_invalid_index(self, filled_model: FileSelectorListModel) -> None:
        assert filled_model.setData(QModelIndex(), True, FileSelectorListModel.IsSelectedRole) is False

    def test_set_data_is_selected(self, filled_model: FileSelectorListModel) -> None:
        idx0 = filled_model.index(0, 0)
        assert filled_model.setData(idx0, True, FileSelectorListModel.IsSelectedRole) is True
        assert filled_model.data(idx0, FileSelectorListModel.IsSelectedRole) is True

    def test_set_data_is_previewing(self, filled_model: FileSelectorListModel) -> None:
        idx0 = filled_model.index(0, 0)
        assert filled_model.setData(idx0, True, FileSelectorListModel.IsPreviewingRole) is True
        assert filled_model.data(idx0, FileSelectorListModel.IsPreviewingRole) is True

    def test_set_data_unknown_role(self, filled_model: FileSelectorListModel) -> None:
        """未支持的角色应返回 False"""
        idx0 = filled_model.index(0, 0)
        assert filled_model.setData(idx0, "test", Qt.EditRole) is False

    def test_set_data_emits_data_changed(self, filled_model: FileSelectorListModel) -> None:
        """setData 应发射 dataChanged 信号"""
        spy = QSignalSpy(filled_model.dataChanged)
        idx0 = filled_model.index(0, 0)
        filled_model.setData(idx0, True, FileSelectorListModel.IsSelectedRole)
        assert spy.count() == 1
        emitted_top = spy.at(0)[0]
        assert emitted_top == idx0


class TestFileSelectorListModelSetFiles:
    """set_files() 加载文件列表"""

    def test_set_files_replaces_data(self, model: FileSelectorListModel) -> None:
        model.set_files(sample_files())
        assert model.rowCount() == 5
        assert model.data(model.index(0, 0), FileSelectorListModel.FilePathRole) == "C:/photos/sunset.jpg"

    def test_set_files_emits_model_reset(self, model: FileSelectorListModel) -> None:
        spy = QSignalSpy(model.modelReset)
        model.set_files(sample_files())
        assert spy.count() == 1

    def test_set_files_defaults_bool_fields(self, model: FileSelectorListModel) -> None:
        """set_files 应为缺失的 is_selected / is_previewing 设置默认值"""
        files_no_bools = [
            make_file_info("C:/test/file1.txt"),
            {"path": "C:/test/file2.txt", "name": "file2.txt"},
        ]
        model.set_files(files_no_bools)
        assert model.rowCount() == 2
        idx0 = model.index(0, 0)
        assert model.data(idx0, FileSelectorListModel.IsSelectedRole) is False
        assert model.data(idx0, FileSelectorListModel.IsPreviewingRole) is False

    def test_set_files_builds_path_index(self, filled_model: FileSelectorListModel) -> None:
        """set_files 后应用 get_row 可查到路径"""
        row = filled_model.get_row("C:/photos/sunset.jpg")
        assert row == 0

    def test_set_files_empty_list(self, model: FileSelectorListModel) -> None:
        """设置空列表应清空模型"""
        model.set_files([])
        assert model.rowCount() == 0

    def test_set_files_keep_selection(self, filled_model: FileSelectorListModel) -> None:
        """再次调用 set_files 且 keep_selection 时保留选中状态"""
        idx0 = filled_model.index(0, 0)
        filled_model.setData(idx0, True, FileSelectorListModel.IsSelectedRole)

        # 重新设置文件列表（模拟 keep_selection 行为）
        files = sample_files()
        files[0]["is_selected"] = True
        filled_model.set_files(files)
        assert filled_model.data(idx0, FileSelectorListModel.IsSelectedRole) is True


class TestFileSelectorListModelClear:
    """clear() 清空模型"""

    def test_clear_empties_data(self, filled_model: FileSelectorListModel) -> None:
        filled_model.clear()
        assert filled_model.rowCount() == 0

    def test_clear_emits_model_reset(self, filled_model: FileSelectorListModel) -> None:
        spy = QSignalSpy(filled_model.modelReset)
        filled_model.clear()
        assert spy.count() == 1

    def test_clear_path_index_cleared(self, filled_model: FileSelectorListModel) -> None:
        filled_model.clear()
        assert filled_model.get_row("C:/photos/sunset.jpg") == -1

    def test_clear_idempotent(self, model: FileSelectorListModel) -> None:
        """重复 clear 不应报错"""
        model.clear()
        model.clear()
        assert model.rowCount() == 0


class TestFileSelectorListModelSelection:
    """选择操作"""

    def test_select_all_selects_everything(self, filled_model: FileSelectorListModel) -> None:
        filled_model.select_all()
        for row in range(filled_model.rowCount()):
            assert filled_model.data(filled_model.index(row, 0), FileSelectorListModel.IsSelectedRole) is True

    def test_deselect_all_unselects_everything(self, filled_model: FileSelectorListModel) -> None:
        filled_model.select_all()
        filled_model.deselect_all()
        for row in range(filled_model.rowCount()):
            assert filled_model.data(filled_model.index(row, 0), FileSelectorListModel.IsSelectedRole) is False

    def test_toggle_selected(self, filled_model: FileSelectorListModel) -> None:
        row = filled_model.get_row("C:/docs/report.pdf")
        assert row >= 0
        # 初始为 False
        assert filled_model.data(filled_model.index(row, 0), FileSelectorListModel.IsSelectedRole) is False
        # toggle 为 True
        result = filled_model.toggle_selected("C:/docs/report.pdf")
        assert result is True
        assert filled_model.data(filled_model.index(row, 0), FileSelectorListModel.IsSelectedRole) is True
        # toggle 为 False
        result = filled_model.toggle_selected("C:/docs/report.pdf")
        assert result is False
        assert filled_model.data(filled_model.index(row, 0), FileSelectorListModel.IsSelectedRole) is False

    def test_toggle_selected_unknown_path(self, filled_model: FileSelectorListModel) -> None:
        """不存在的路径应返回 False"""
        assert filled_model.toggle_selected("C:/nonexistent.txt") is False

    def test_set_selected(self, filled_model: FileSelectorListModel) -> None:
        filled_model.set_selected("C:/videos/clip.mp4", True)
        row = filled_model.get_row("C:/videos/clip.mp4")
        assert filled_model.data(filled_model.index(row, 0), FileSelectorListModel.IsSelectedRole) is True

    def test_set_selected_unknown_path(self, filled_model: FileSelectorListModel) -> None:
        """不存在的路径应返回 False"""
        assert filled_model.set_selected("C:/nonexistent.txt", True) is False

    def test_get_selected_files(self, filled_model: FileSelectorListModel) -> None:
        filled_model.set_selected("C:/photos/sunset.jpg", True)
        filled_model.set_selected("C:/docs/report.pdf", True)
        selected = filled_model.get_selected_files()
        assert "C:/photos/sunset.jpg" in selected
        assert "C:/docs/report.pdf" in selected
        assert len(selected) == 2

    def test_get_selected_files_empty(self, model: FileSelectorListModel) -> None:
        assert model.get_selected_files() == []

    def test_is_selected(self, filled_model: FileSelectorListModel) -> None:
        assert filled_model.is_selected("C:/photos/sunset.jpg") is False
        filled_model.set_selected("C:/photos/sunset.jpg", True)
        assert filled_model.is_selected("C:/photos/sunset.jpg") is True

    def test_is_selected_unknown_path(self, filled_model: FileSelectorListModel) -> None:
        """不存在的路径应返回 False"""
        assert filled_model.is_selected("C:/nonexistent.txt") is False


class TestFileSelectorListModelPreviewing:
    """预览状态管理"""

    def test_set_previewing(self, filled_model: FileSelectorListModel) -> None:
        filled_model.set_previewing("C:/docs/report.pdf", True)
        row = filled_model.get_row("C:/docs/report.pdf")
        assert filled_model.data(filled_model.index(row, 0), FileSelectorListModel.IsPreviewingRole) is True

    def test_set_previewing_auto_clear_others(self, filled_model: FileSelectorListModel) -> None:
        """设置预览时 is_previewing=None 应只标记指定的文件"""
        filled_model.set_previewing("C:/docs/report.pdf", True)
        filled_model.set_previewing("C:/photos/sunset.jpg", None)

        # report.pdf 应取消预览
        assert filled_model.data(
            filled_model.index(filled_model.get_row("C:/docs/report.pdf"), 0),
            FileSelectorListModel.IsPreviewingRole,
        ) is False
        # sunset.jpg 应设为预览
        assert filled_model.data(
            filled_model.index(filled_model.get_row("C:/photos/sunset.jpg"), 0),
            FileSelectorListModel.IsPreviewingRole,
        ) is True

    def test_clear_previewing(self, filled_model: FileSelectorListModel) -> None:
        filled_model.set_previewing("C:/photos/sunset.jpg", True)
        filled_model.clear_previewing()
        for row in range(filled_model.rowCount()):
            assert filled_model.data(filled_model.index(row, 0), FileSelectorListModel.IsPreviewingRole) is False


class TestFileSelectorListModelGetRow:
    """get_row() 路径搜索"""

    def test_get_row_found(self, filled_model: FileSelectorListModel) -> None:
        assert filled_model.get_row("C:/docs/report.pdf") == 1

    def test_get_row_not_found(self, filled_model: FileSelectorListModel) -> None:
        assert filled_model.get_row("C:/nonexistent.txt") == -1

    def test_get_row_empty_path(self, filled_model: FileSelectorListModel) -> None:
        assert filled_model.get_row("") == -1


class TestFileSelectorListModelGetFileInfo:
    """get_file_info()"""

    def test_get_file_info_valid_index(self, filled_model: FileSelectorListModel) -> None:
        idx0 = filled_model.index(0, 0)
        info = filled_model.get_file_info(idx0)
        assert isinstance(info, dict)
        assert info["path"] == "C:/photos/sunset.jpg"
        assert info["name"] == "sunset.jpg"

    def test_get_file_info_invalid_index(self, filled_model: FileSelectorListModel) -> None:
        assert filled_model.get_file_info(QModelIndex()) == {}
        assert filled_model.get_file_info(filled_model.index(999, 0)) == {}


class TestFileSelectorListModelGeometry:
    """尺寸配置"""

    def test_set_card_width(self, model: FileSelectorListModel) -> None:
        model.set_card_width(200, 100, 4)
        assert model.data(QModelIndex(), FileSelectorListModel.CardWidthRole) is None  # invalid index

        model.set_files([make_file_info("C:/test.txt")])
        model.set_card_width(200, 100, 4)
        idx0 = model.index(0, 0)
        assert model.data(idx0, FileSelectorListModel.CardWidthRole) == 200

    def test_set_card_width_noop(self, filled_model: FileSelectorListModel) -> None:
        """相同值不应发射信号"""
        spy = QSignalSpy(filled_model.dataChanged)
        filled_model.set_card_width(150, 75, 3)
        assert spy.count() == 0

    def test_set_grid_offset_x(self, model: FileSelectorListModel) -> None:
        model.set_files([make_file_info("C:/test.txt")])
        model.set_grid_offset_x(10)
        idx0 = model.index(0, 0)
        assert model.data(idx0, FileSelectorListModel.GridOffsetRole) == 10

    def test_set_grid_offset_x_noop(self, filled_model: FileSelectorListModel) -> None:
        """相同值不应发射信号"""
        spy = QSignalSpy(filled_model.dataChanged)
        filled_model.set_grid_offset_x(0)
        assert spy.count() == 0

    def test_update_geometry_delegates(self, model: FileSelectorListModel) -> None:
        """update_geometry 应委托给 set_card_width"""
        model.set_files([make_file_info("C:/test.txt")])
        model.update_geometry(300, 150, 5)
        idx0 = model.index(0, 0)
        assert model.data(idx0, FileSelectorListModel.CardWidthRole) == 300


class TestFileSelectorListModelFlags:
    """flags()"""

    def test_flags_invalid_index(self, model: FileSelectorListModel) -> None:
        assert model.flags(QModelIndex()) == Qt.NoItemFlags

    def test_flags_valid_index(self, filled_model: FileSelectorListModel) -> None:
        idx0 = filled_model.index(0, 0)
        f = filled_model.flags(idx0)
        assert f & Qt.ItemIsEnabled
        assert f & Qt.ItemIsSelectable
        assert f & Qt.ItemIsUserCheckable


class TestFileSelectorListModelRoleNames:
    """roleNames()"""

    def test_role_names_contains_all_roles(self, filled_model: FileSelectorListModel) -> None:
        names = filled_model.roleNames()
        assert names[FileSelectorListModel.FilePathRole] == b"filePath"
        assert names[FileSelectorListModel.FileNameRole] == b"fileName"
        assert names[FileSelectorListModel.IsDirRole] == b"isDir"
        assert names[FileSelectorListModel.IsSelectedRole] == b"isSelected"
        assert names[FileSelectorListModel.IsPreviewingRole] == b"isPreviewing"
        assert names[FileSelectorListModel.SuffixRole] == b"suffix"
        assert names[FileSelectorListModel.IconPixmapRole] == b"iconPixmap"
        assert names[FileSelectorListModel.CardWidthRole] == b"cardWidth"
        assert names[FileSelectorListModel.GridOffsetRole] == b"gridOffsetX"


class TestFileSelectorListModelSizeHint:
    """sizeHint()"""

    def test_size_hint_returns_qsize(self, model: FileSelectorListModel) -> None:
        hint = model.sizeHint()
        assert isinstance(hint, QSize)
        assert hint.width() > 0
        assert hint.height() > 0


class TestFileSelectorListModelAttachView:
    """attach_view()"""

    def test_attach_view_none(self, filled_model: FileSelectorListModel) -> None:
        """attach_view(None) 应清除视图引用"""
        filled_model.attach_view(None)
        # 不应抛出异常
        filled_model.select_all()

    def test_attach_view_and_clear(self, filled_model: FileSelectorListModel, view: FileListView) -> None:
        """关联视图后清空不应出错"""
        filled_model.attach_view(view)
        filled_model.clear()
        assert filled_model.rowCount() == 0


class TestFileSelectorListModelClearCaches:
    """clear_caches()"""

    def test_clear_caches_all(self, filled_model: FileSelectorListModel) -> None:
        """不传参时应清空所有缓存"""
        filled_model.clear_caches()  # 不应抛出异常

    def test_clear_caches_with_path(self, filled_model: FileSelectorListModel) -> None:
        """传入路径时应精确失效"""
        filled_model.clear_caches(file_path="C:/photos/sunset.jpg")

    def test_clear_caches_with_emit(self, filled_model: FileSelectorListModel) -> None:
        """emit_change=True 应发射 dataChanged"""
        spy = QSignalSpy(filled_model.dataChanged)
        filled_model.clear_caches(emit_change=True)
        assert spy.count() == 1


class TestFileSelectorListModelRefreshIcon:
    """refresh_icon()"""

    def test_refresh_icon_valid_path(self, filled_model: FileSelectorListModel) -> None:
        result = filled_model.refresh_icon("C:/photos/sunset.jpg")
        assert result is True

    def test_refresh_icon_invalid_path(self, filled_model: FileSelectorListModel) -> None:
        result = filled_model.refresh_icon("C:/nonexistent.txt")
        assert result is False


class TestFileSelectorListModelSortFilter:
    """排序/筛选兼容性"""

    def test_set_files_preserves_order(self, filled_model: FileSelectorListModel) -> None:
        """set_files 应保留传入的顺序"""
        assert filled_model.data(filled_model.index(0, 0), FileSelectorListModel.FileNameRole) == "sunset.jpg"
        assert filled_model.data(filled_model.index(4, 0), FileSelectorListModel.FileNameRole) == "notes.txt"

    def test_data_is_consistent_across_rows(self, filled_model: FileSelectorListModel) -> None:
        """每行数据应内部一致"""
        for row in range(filled_model.rowCount()):
            info = filled_model.get_file_info(filled_model.index(row, 0))
            assert filled_model.data(filled_model.index(row, 0), Qt.DisplayRole) == info["name"]
            assert filled_model.data(filled_model.index(row, 0), FileSelectorListModel.FilePathRole) == info["path"]


class TestFileSelectorListModelSignals:
    """信号测试"""

    def test_model_reset_on_set_files(self, model: FileSelectorListModel) -> None:
        spy = QSignalSpy(model.modelReset)
        model.set_files(sample_files())
        assert spy.count() == 1

    def test_model_reset_on_clear(self, filled_model: FileSelectorListModel) -> None:
        spy = QSignalSpy(filled_model.modelReset)
        filled_model.clear()
        assert spy.count() == 1

    def test_data_changed_on_set_selected(self, filled_model: FileSelectorListModel) -> None:
        spy = QSignalSpy(filled_model.dataChanged)
        filled_model.set_selected("C:/docs/report.pdf", True)
        assert spy.count() == 1
        top_left = spy.at(0)[0]
        assert top_left.row() == 1

    def test_data_changed_on_set_previewing(self, filled_model: FileSelectorListModel) -> None:
        spy = QSignalSpy(filled_model.dataChanged)
        filled_model.set_previewing("C:/videos/clip.mp4", True)
        assert spy.count() == 1

    def test_data_changed_on_toggle_selected(self, filled_model: FileSelectorListModel) -> None:
        spy = QSignalSpy(filled_model.dataChanged)
        filled_model.toggle_selected("C:/docs/notes.txt")
        assert spy.count() == 1


# ══════════════════════════════════════════════════════════════════
# FileListView 测试
# ══════════════════════════════════════════════════════════════════


class TestFileListViewCreation:
    """FileListView 创建"""

    def test_create(self, view: FileListView) -> None:
        assert isinstance(view, FileListView)
        assert isinstance(view, QListView)

    def test_create_with_custom_dpi(self, qapp) -> None:
        v = FileListView(dpi_scale=2.0)
        assert hasattr(v, "_dpi_scale")
        v.close()
        v.deleteLater()

    def test_create_with_settings_manager(self, qapp) -> None:
        from freeassetfilter.core.settings_manager import SettingsManager

        sm = SettingsManager()
        v = FileListView(settings_manager=sm)
        assert hasattr(v, "_settings_manager")
        v.close()
        v.deleteLater()

    def test_view_properties(self, view: FileListView) -> None:
        """基本视图属性"""
        assert view.viewMode() == QListView.IconMode
        assert view.selectionMode() == QListView.ExtendedSelection


class TestFileListViewModelOperations:
    """FileListView 模型挂载"""

    def test_set_model(self, view: FileListView, filled_model: FileSelectorListModel) -> None:
        view.setModel(filled_model)
        assert view.model() is filled_model

    def test_set_model_none(self, view: FileListView) -> None:
        """设置 None 模型不应崩溃"""
        view.setModel(None)
        assert view.model() is None

    def test_set_model_multiple_times(self, view: FileListView, filled_model: FileSelectorListModel) -> None:
        view.setModel(filled_model)
        view.setModel(filled_model)  # 再次设同一模型
        assert view.model() is filled_model

    def test_model_signals(self, view: FileListView, model: FileSelectorListModel) -> None:
        """模型重置后视图不应崩溃"""
        view.setModel(model)
        model.set_files(sample_files())
        assert model.rowCount() == 5
        model.clear()
        assert model.rowCount() == 0


class TestFileListViewSignals:
    """FileListView 信号"""

    def test_file_clicked_signal(self, view: FileListView) -> None:
        assert hasattr(view, "file_clicked")
        assert view.file_clicked is not None

    def test_file_double_clicked_signal(self, view: FileListView) -> None:
        assert hasattr(view, "file_double_clicked")
        assert view.file_double_clicked is not None

    def test_file_right_clicked_signal(self, view: FileListView) -> None:
        assert hasattr(view, "file_right_clicked")
        assert view.file_right_clicked is not None

    def test_file_selection_changed_signal(self, view: FileListView) -> None:
        assert hasattr(view, "file_selection_changed")
        assert view.file_selection_changed is not None

    def test_file_drag_started_signal(self, view: FileListView) -> None:
        assert hasattr(view, "file_drag_started")
        assert view.file_drag_started is not None

    def test_file_drag_ended_signal(self, view: FileListView) -> None:
        assert hasattr(view, "file_drag_ended")
        assert view.file_drag_ended is not None

    def test_navigate_parent_requested_signal(self, view: FileListView) -> None:
        assert hasattr(view, "navigate_parent_requested")
        assert view.navigate_parent_requested is not None


class TestFileListViewInteractionSettings:
    """交互设置"""

    def test_refresh_interaction_settings(self, view: FileListView) -> None:
        """refresh_interaction_settings 不应抛出异常"""
        view.refresh_interaction_settings()

    def test_is_scroll_optimizing_default(self, view: FileListView) -> None:
        assert view.is_scroll_optimizing() is False

    def test_enter_leave_events(self, view: FileListView) -> None:
        """enterEvent/leaveEvent 不应抛出异常"""
        from PySide6.QtCore import QEvent, QPointF
        from PySide6.QtGui import QEnterEvent, QPointingDevice

        # 模拟 enter event
        enter_pt = QPointF(10, 10)
        device = QPointingDevice.primaryPointingDevice()
        enter_event = QEnterEvent(enter_pt, enter_pt, enter_pt, device)
        view.enterEvent(enter_event)

        # 模拟 leave event
        leave_event = QEvent(QEvent.Type.Leave)
        view.leaveEvent(leave_event)

        # 不应抛出异常
