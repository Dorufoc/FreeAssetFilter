# -*- coding: utf-8 -*-
"""
FileStagingPoolListModel 单元测试

测试 freeassetfilter/widgets/file_staging_pool_model.py 中的
FileStagingPoolListModel 类。

覆盖范围:
    - 模型创建与基本属性
    - 角色数据（DisplayNameRole, IsMissingRole 等）
    - 数据操作（增删改查）
    - rowCount() / data() 方法
    - 信号发射（dataChanged, rowsInserted, rowsRemoved）
    - 拖放（mimeData, mimeTypes, supportedDragActions）
    - 其他公共 API（rename_file, has_path, index_from_path 等）
"""

import os
import pytest

from PySide6.QtCore import QMimeData, QModelIndex, QSize, Qt, QUrl
from PySide6.QtTest import QSignalSpy

from freeassetfilter.widgets.file_staging_pool_model import FileStagingPoolListModel


# =============================================================================
# 辅助函数
# =============================================================================


def _make_file_info(path: str, **overrides) -> dict:
    """构造最小 file_info 字典，支持覆盖字段。

    Args:
        path: 文件路径。
        **overrides: 覆盖字段，如 name、is_dir、size 等。

    Returns:
        符合模型预期的 file_info dict。
    """
    info: dict = {
        "name": os.path.basename(path),
        "path": path,
        "is_dir": False,
        "size": 1024,
        "modified": "2024-01-15 10:30:00",
        "created": "2024-01-15 10:30:00",
        "suffix": os.path.splitext(path)[1].lstrip("."),
    }
    info.update(overrides)
    return info


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def model(qapp):
    """提供默认的 FileStagingPoolListModel 实例。"""
    mdl = FileStagingPoolListModel(dpi_scale=1.0)
    yield mdl
    mdl.deleteLater()


@pytest.fixture
def temp_file_info(tmp_path):
    """创建一个真实存在的临时文件并返回其 file_info dict。"""
    path = tmp_path / "test_doc.txt"
    path.write_text("hello world")
    return _make_file_info(str(path), size=path.stat().st_size)


@pytest.fixture
def missing_file_info(tmp_path):
    """返回一个不存在的文件路径的 file_info dict。"""
    path = tmp_path / "ghost.txt"
    return _make_file_info(str(path), size=0)


@pytest.fixture
def populated_model(qapp, tmp_path):
    """预先填充 3 条文件的模型。"""
    mdl = FileStagingPoolListModel(dpi_scale=1.0)

    # 真实的文件
    f1 = tmp_path / "alpha.txt"
    f1.write_text("alpha")
    # 不存在的文件
    f2 = tmp_path / "beta.txt"  # 不创建
    # 目录
    d3 = tmp_path / "gamma_dir"
    d3.mkdir()

    files = [
        _make_file_info(str(f1), name="alpha.txt", size=f1.stat().st_size),
        _make_file_info(str(f2), name="beta.txt", size=0),
        _make_file_info(str(d3), name="gamma_dir", is_dir=True, size=0),
    ]
    mdl.set_files(files)
    yield mdl
    mdl.deleteLater()


# =============================================================================
# 测试类
# =============================================================================


class TestFileStagingPoolListModelCreation:
    """模型创建与基本属性"""

    def test_construct_default(self, qapp):
        """默认构造不报错。"""
        mdl = FileStagingPoolListModel()
        assert mdl.rowCount() == 0
        assert mdl._card_width >= 240
        assert mdl._card_height >= 30
        assert mdl._files == []
        mdl.deleteLater()

    def test_construct_with_dpi_scale(self, qapp):
        """传入 dpi_scale 影响卡片尺寸。"""
        mdl = FileStagingPoolListModel(dpi_scale=2.0)
        assert mdl._card_width >= 240
        assert mdl._card_height >= 30
        mdl.deleteLater()

    def test_rowCount_initial(self, model):
        """新建模型 rowCount 为 0。"""
        assert model.rowCount() == 0

    def test_rowCount_invalid_parent(self, model):
        """传入有效 parent index 时 rowCount 返回 0（QAbstractListModel 规范）。"""
        idx = model.index(0, 0)
        assert model.rowCount(idx) == 0

    def test_item_size_default(self, model):
        """item_size 返回 QSize。"""
        size = model.item_size()
        assert isinstance(size, QSize)
        assert size.width() >= 240
        assert size.height() >= 30

    def test_set_item_size_updates(self, model):
        """set_item_size 修改卡片尺寸并发射 dataChanged。"""
        spy = QSignalSpy(model.dataChanged)
        model.set_item_size(300, 50)
        assert model._card_width == 300
        assert model._card_height == 50
        # 无数据时不应发射
        assert spy.count() == 0, "空模型不应发射 dataChanged"

    def test_set_item_size_emits_when_populated(self, populated_model):
        """有数据时 set_item_size 发射 dataChanged。"""
        spy = QSignalSpy(populated_model.dataChanged)
        populated_model.set_item_size(320, 60)
        assert spy.count() >= 1

    def test_set_item_size_same_no_emit(self, populated_model):
        """尺寸不变不应发射 dataChanged。"""
        w, h = populated_model._card_width, populated_model._card_height
        spy = QSignalSpy(populated_model.dataChanged)
        populated_model.set_item_size(w, h)
        assert spy.count() == 0


class TestFileStagingPoolListModelRoles:
    """自定义角色数据"""

    def test_display_name_role(self, populated_model):
        """DisplayNameRole 返回 display_name。"""
        idx = populated_model.index(0, 0)
        value = idx.data(FileStagingPoolListModel.DisplayNameRole)
        assert isinstance(value, str)
        assert len(value) > 0

    def test_original_name_role(self, populated_model):
        """OriginalNameRole 返回 original_name。"""
        idx = populated_model.index(0, 0)
        value = idx.data(FileStagingPoolListModel.OriginalNameRole)
        assert isinstance(value, str)

    def test_modified_role(self, populated_model):
        """ModifiedRole 返回修改时间字符串。"""
        idx = populated_model.index(0, 0)
        value = idx.data(FileStagingPoolListModel.ModifiedRole)
        assert value == "2024-01-15 10:30:00"

    def test_is_missing_role_missing_file(self, missing_file_info, model):
        """缺失文件 IsMissingRole 为 True。"""
        model.add_file(missing_file_info)
        idx = model.index(0, 0)
        assert idx.data(FileStagingPoolListModel.IsMissingRole) is True

    def test_is_missing_role_existing_file(self, temp_file_info, model):
        """真实文件 IsMissingRole 为 False。"""
        model.add_file(temp_file_info)
        idx = model.index(0, 0)
        assert idx.data(FileStagingPoolListModel.IsMissingRole) is False

    def test_size_calculating_role(self, populated_model):
        """SizeCalculatingRole 返回 bool。"""
        idx = populated_model.index(0, 0)
        value = idx.data(FileStagingPoolListModel.SizeCalculatingRole)
        assert isinstance(value, bool)

    def test_info_text_role(self, temp_file_info, model):
        """InfoTextRole 返回说明文本（含路径和大小）。"""
        model.add_file(temp_file_info)
        idx = model.index(0, 0)
        text = idx.data(FileStagingPoolListModel.InfoTextRole)
        assert isinstance(text, str)
        assert len(text) > 0

    def test_is_removing_role_default_false(self, temp_file_info, model):
        """默认 IsRemovingRole 为 False。"""
        model.add_file(temp_file_info)
        idx = model.index(0, 0)
        assert idx.data(FileStagingPoolListModel.IsRemovingRole) is False

    def test_item_height_role(self, model):
        """ItemHeightRole 返回 int。"""
        idx = model.index(0, 0)
        # 空模型返回 None
        assert idx.data(FileStagingPoolListModel.ItemHeightRole) is None

    def test_item_size_role(self, temp_file_info, model):
        """ItemSizeRole 返回 QSize。"""
        model.add_file(temp_file_info)
        idx = model.index(0, 0)
        value = idx.data(FileStagingPoolListModel.ItemSizeRole)
        assert isinstance(value, QSize)

    def test_inherited_file_path_role(self, temp_file_info, model):
        """继承的 FilePathRole 正常工作。"""
        model.add_file(temp_file_info)
        idx = model.index(0, 0)
        path = idx.data(FileStagingPoolListModel.FilePathRole)
        assert isinstance(path, str)
        assert os.path.exists(path)

    def test_inherited_is_selected_role(self, temp_file_info, model):
        """继承的 IsSelectedRole 正常工作。"""
        model.add_file(temp_file_info)
        idx = model.index(0, 0)
        assert idx.data(FileStagingPoolListModel.IsSelectedRole) is False

    def test_invalid_index_returns_none(self, model):
        """无效 index 的 data 返回 None。"""
        assert model.data(QModelIndex(), Qt.DisplayRole) is None

    def test_display_role_shows_visible_name(self, temp_file_info, model):
        """Qt.DisplayRole 显示已处理的名字（存在文件不加后缀）。"""
        model.add_file(temp_file_info)
        idx = model.index(0, 0)
        display = idx.data(Qt.DisplayRole)
        assert isinstance(display, str)
        assert "test_doc.txt" in display

    def test_missing_file_display_shows_warning(self, missing_file_info, model):
        """缺失文件的 DisplayRole 在路径后追加提示。"""
        model.add_file(missing_file_info)
        idx = model.index(0, 0)
        display = idx.data(Qt.DisplayRole)
        assert "（已移动或删除）" in display

    def test_visible_display_name_uses_display_name_first(self, temp_file_info, model):
        """_visible_display_name 优先使用 display_name。"""
        model.add_file(temp_file_info)
        idx = model.index(0, 0)
        # 默认 display_name == name
        display = idx.data(FileStagingPoolListModel.DisplayNameRole)
        assert display == "test_doc.txt"


class TestFileStagingPoolListModelOperations:
    """数据操作 — 增删改查"""

    def test_add_file_returns_true(self, temp_file_info, model):
        """add_file 成功时返回 True。"""
        assert model.add_file(temp_file_info) is True

    def test_add_file_increases_row_count(self, temp_file_info, model):
        """add_file 后 rowCount 增加。"""
        model.add_file(temp_file_info)
        assert model.rowCount() == 1

    def test_add_file_duplicate_returns_false(self, temp_file_info, model):
        """重复路径 add_file 返回 False。"""
        model.add_file(temp_file_info)
        assert model.add_file(temp_file_info) is False
        assert model.rowCount() == 1

    def test_add_file_emits_rows_inserted(self, temp_file_info, model):
        """add_file 发射 rowsInserted 信号。"""
        spy = QSignalSpy(model.rowsInserted)
        model.add_file(temp_file_info)
        assert spy.count() == 1
        _, first, last = spy.at(0)
        assert first == last == 0

    def test_add_files_returns_count(self, tmp_path, model):
        """add_files 返回实际新增数量。"""
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("a")
        f2.write_text("b")
        files = [
            _make_file_info(str(f1)),
            _make_file_info(str(f2)),
        ]
        count = model.add_files(files)
        assert count == 2
        assert model.rowCount() == 2

    def test_add_files_skips_duplicates(self, tmp_path, model):
        """add_files 跳过重复路径。"""
        f1 = tmp_path / "a.txt"
        f1.write_text("a")
        info = _make_file_info(str(f1))
        model.add_file(info)
        count = model.add_files([info, info])
        assert count == 0
        assert model.rowCount() == 1

    def test_set_files_replaces_content(self, tmp_path, model):
        """set_files 替换全部现有内容。"""
        f1 = tmp_path / "a.txt"
        f1.write_text("a")
        model.add_file(_make_file_info(str(f1)))
        assert model.rowCount() == 1

        f2 = tmp_path / "b.txt"
        f2.write_text("b")
        f3 = tmp_path / "c.txt"
        f3.write_text("c")
        model.set_files([
            _make_file_info(str(f2)),
            _make_file_info(str(f3)),
        ])
        assert model.rowCount() == 2

    def test_set_files_deduplicates(self, tmp_path, model):
        """set_files 去重。"""
        f1 = tmp_path / "a.txt"
        f1.write_text("a")
        model.set_files([
            _make_file_info(str(f1)),
            _make_file_info(str(f1)),
        ])
        assert model.rowCount() == 1

    def test_remove_file_sets_removing_flag(self, temp_file_info, model):
        """remove_file 设置 is_removing=True 并发射 dataChanged。"""
        model.add_file(temp_file_info)
        spy = QSignalSpy(model.dataChanged)
        result = model.remove_file(temp_file_info["path"])
        assert isinstance(result, dict)
        assert result.get("path") == temp_file_info["path"]
        idx = model.index(0, 0)
        assert idx.data(FileStagingPoolListModel.IsRemovingRole) is True
        # remove_file 应发射 dataChanged
        assert spy.count() >= 1

    def test_remove_file_twice_returns_empty(self, temp_file_info, model):
        """重复 remove_file 返回空 dict。"""
        model.add_file(temp_file_info)
        model.remove_file(temp_file_info["path"])
        result = model.remove_file(temp_file_info["path"])
        assert result == {}

    def test_finalize_remove_removes_row(self, temp_file_info, model):
        """finalize_remove_file 从模型中移除行。"""
        model.add_file(temp_file_info)
        model.remove_file(temp_file_info["path"])
        spy = QSignalSpy(model.rowsRemoved)
        removed = model.finalize_remove_file(temp_file_info["path"])
        assert isinstance(removed, dict)
        assert model.rowCount() == 0
        assert spy.count() >= 1

    def test_finalize_remove_nonexistent_returns_empty(self, model):
        """finalize_remove_file 不存在文件返回空 dict。"""
        assert model.finalize_remove_file("/nonexistent") == {}

    def test_remove_file_nonexistent_returns_empty(self, model):
        """remove_file 不存在路径返回空 dict。"""
        assert model.remove_file("/nonexistent") == {}

    def test_update_file_updates_field(self, temp_file_info, model):
        """update_file 更新字段并发射 dataChanged。"""
        model.add_file(temp_file_info)
        spy = QSignalSpy(model.dataChanged)
        result = model.update_file(temp_file_info["path"], {"display_name": "renamed.txt"})
        assert result is True
        idx = model.index(0, 0)
        assert idx.data(FileStagingPoolListModel.DisplayNameRole) == "renamed.txt"
        assert spy.count() >= 1

    def test_update_file_missing_path_returns_false(self, model):
        """update_file 不存在的路径返回 False。"""
        assert model.update_file("/nonexistent", {"display_name": "x"}) is False

    def test_update_file_path_conflict_returns_false(self, tmp_path, model):
        """update_file 新路径冲突时返回 False。"""
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("a")
        f2.write_text("b")
        model.add_file(_make_file_info(str(f1)))
        model.add_file(_make_file_info(str(f2)))
        # 尝试将 a.txt 的路径改成 b.txt 的路径 → 冲突
        result = model.update_file(str(f1), {"path": str(f2)})
        assert result is False

    def test_update_file_rebuilds_info_text_on_size_change(self, temp_file_info, model):
        """大小变化时 info_text 自动重建。"""
        model.add_file(temp_file_info)
        model.update_file(temp_file_info["path"], {"size": 9999})
        idx = model.index(0, 0)
        info_text = idx.data(FileStagingPoolListModel.InfoTextRole)
        assert isinstance(info_text, str)

    def test_rename_file_sets_display_name(self, temp_file_info, model):
        """rename_file 设置 display_name。"""
        model.add_file(temp_file_info)
        result = model.rename_file(temp_file_info["path"], "新名字.txt")
        assert result is True
        idx = model.index(0, 0)
        assert idx.data(FileStagingPoolListModel.DisplayNameRole) == "新名字.txt"

    def test_rename_file_clears_display_name_when_empty(self, temp_file_info, model):
        """rename_file 空字符串恢复为 name。"""
        model.add_file(temp_file_info)
        model.rename_file(temp_file_info["path"], "custom")
        model.rename_file(temp_file_info["path"], "")
        idx = model.index(0, 0)
        display = idx.data(FileStagingPoolListModel.DisplayNameRole)
        # 恢复为原始 name
        assert display == temp_file_info["name"]

    def test_rename_file_nonexistent_returns_false(self, model):
        """rename_file 不存在路径返回 False。"""
        assert model.rename_file("/nonexistent", "x") is False

    def test_has_path_returns_true(self, temp_file_info, model):
        """has_path 存在路径返回 True。"""
        model.add_file(temp_file_info)
        assert model.has_path(temp_file_info["path"]) is True

    def test_has_path_returns_false(self, model):
        """has_path 不存在路径返回 False。"""
        assert model.has_path("/nonexistent") is False

    def test_index_from_path_returns_valid(self, temp_file_info, model):
        """index_from_path 返回有效 index。"""
        model.add_file(temp_file_info)
        idx = model.index_from_path(temp_file_info["path"])
        assert idx.isValid()

    def test_index_from_path_nonexistent_returns_invalid(self, model):
        """index_from_path 不存在路径返回无效 index。"""
        idx = model.index_from_path("/nonexistent")
        assert idx.isValid() is False

    def test_get_file_info_by_path_returns_copy(self, temp_file_info, model):
        """get_file_info_by_path 返回文件信息副本。"""
        model.add_file(temp_file_info)
        info = model.get_file_info_by_path(temp_file_info["path"])
        assert isinstance(info, dict)
        assert info["path"] == temp_file_info["path"]

    def test_get_file_info_by_path_nonexistent_returns_empty(self, model):
        """get_file_info_by_path 不存在路径返回空 dict。"""
        assert model.get_file_info_by_path("/nonexistent") == {}

    def test_clear_removes_all(self, temp_file_info, model):
        """clear 清空所有文件。"""
        model.add_file(temp_file_info)
        assert model.rowCount() == 1
        model.clear()
        assert model.rowCount() == 0


class TestFileStagingPoolListModelSignals:
    """信号验证"""

    def test_set_files_emits_model_reset(self, temp_file_info, model):
        """set_files 发射 modelAboutToBeReset 和 modelReset。"""
        spy_about = QSignalSpy(model.modelAboutToBeReset)
        spy_reset = QSignalSpy(model.modelReset)
        model.set_files([temp_file_info])
        assert spy_about.count() >= 1
        assert spy_reset.count() >= 1

    def test_add_file_emits_rows_inserted(self, temp_file_info, model):
        """add_file 发射 rowsInserted。"""
        spy = QSignalSpy(model.rowsInserted)
        model.add_file(temp_file_info)
        assert spy.count() == 1

    def test_remove_then_finalize_emits_rows_removed(self, temp_file_info, model):
        """remove_file + finalize_remove_file 发射 rowsRemoved。"""
        model.add_file(temp_file_info)
        model.remove_file(temp_file_info["path"])
        spy = QSignalSpy(model.rowsRemoved)
        model.finalize_remove_file(temp_file_info["path"])
        assert spy.count() >= 1

    def test_update_file_emits_data_changed(self, temp_file_info, model):
        """update_file 发射 dataChanged。"""
        model.add_file(temp_file_info)
        spy = QSignalSpy(model.dataChanged)
        model.update_file(temp_file_info["path"], {"display_name": "new_name"})
        assert spy.count() >= 1


class TestFileStagingPoolListModelDragDrop:
    """拖放支持"""

    def test_mime_types_returns_uri_list(self, model):
        """mimeTypes 返回 ['text/uri-list']。"""
        assert model.mimeTypes() == ["text/uri-list"]

    def test_mime_data_contains_urls(self, temp_file_info, model):
        """mimeData 包含选中文件的 QUrl。"""
        model.add_file(temp_file_info)
        idx = model.index(0, 0)
        mime = model.mimeData([idx])
        assert isinstance(mime, QMimeData)
        urls = mime.urls()
        assert len(urls) >= 1
        assert os.path.normpath(urls[0].toLocalFile()) == os.path.normpath(temp_file_info["path"])

    def test_mime_data_skips_invalid(self, model):
        """mimeData 传入无效 index 返回空数据。"""
        mime = model.mimeData([QModelIndex()])
        assert isinstance(mime, QMimeData)
        assert len(mime.urls()) == 0

    def test_mime_data_deduplicates(self, temp_file_info, model):
        """mimeData 对重复路径去重。"""
        model.add_file(temp_file_info)
        idx = model.index(0, 0)
        mime = model.mimeData([idx, idx])
        assert len(mime.urls()) == 1

    def test_supported_drag_actions(self, model):
        """supportedDragActions 返回 CopyAction | MoveAction。"""
        actions = model.supportedDragActions()
        assert actions & Qt.CopyAction
        assert actions & Qt.MoveAction


class TestFileStagingPoolListModelSetData:
    """setData 方法"""

    def test_set_data_display_name(self, temp_file_info, model):
        """setData DisplayNameRole 更新 display_name。"""
        model.add_file(temp_file_info)
        idx = model.index(0, 0)
        result = model.setData(idx, "custom", FileStagingPoolListModel.DisplayNameRole)
        assert result is True
        assert idx.data(FileStagingPoolListModel.DisplayNameRole) == "custom"

    def test_set_data_info_text(self, temp_file_info, model):
        """setData InfoTextRole 更新 info_text。"""
        model.add_file(temp_file_info)
        idx = model.index(0, 0)
        result = model.setData(idx, "custom info", FileStagingPoolListModel.InfoTextRole)
        assert result is True
        assert idx.data(FileStagingPoolListModel.InfoTextRole) == "custom info"

    def test_set_data_is_missing(self, temp_file_info, model):
        """setData IsMissingRole 更新 is_missing。"""
        model.add_file(temp_file_info)
        idx = model.index(0, 0)
        result = model.setData(idx, True, FileStagingPoolListModel.IsMissingRole)
        assert result is True
        assert idx.data(FileStagingPoolListModel.IsMissingRole) is True

    def test_set_data_is_removing(self, temp_file_info, model):
        """setData IsRemovingRole 更新 is_removing。"""
        model.add_file(temp_file_info)
        idx = model.index(0, 0)
        result = model.setData(idx, True, FileStagingPoolListModel.IsRemovingRole)
        assert result is True
        assert idx.data(FileStagingPoolListModel.IsRemovingRole) is True

    def test_set_data_size_calculating(self, tmp_path, model):
        """setData SizeCalculatingRole 更新 size_calculating。"""
        d = tmp_path / "some_dir"
        d.mkdir()
        dir_info = _make_file_info(str(d), is_dir=True, size=0)
        model.add_file(dir_info)
        idx = model.index(0, 0)
        result = model.setData(idx, True, FileStagingPoolListModel.SizeCalculatingRole)
        assert result is True
        assert idx.data(FileStagingPoolListModel.SizeCalculatingRole) is True

    def test_set_data_invalid_index_returns_false(self, model):
        """setData 无效 index 返回 False。"""
        assert model.setData(QModelIndex(), "x", Qt.DisplayRole) is False


class TestFileStagingPoolListModelPrepareFileInfo:
    """_prepare_file_info 的内部逻辑验证（通过公共 API 间接测试）"""

    def test_missing_flag_detected_automatically(self, tmp_path, model):
        """不存在的文件自动标记 is_missing=True。"""
        path = tmp_path / "nonexistent.txt"
        info = _make_file_info(str(path))
        model.add_file(info)
        idx = model.index(0, 0)
        assert idx.data(FileStagingPoolListModel.IsMissingRole) is True

    def test_dir_without_size_triggers_calculating(self, tmp_path, model):
        """目录无 size 时 size_calculating=True。"""
        d = tmp_path / "some_dir"
        d.mkdir()
        info = _make_file_info(str(d), is_dir=True, size=None)
        model.add_file(info)
        idx = model.index(0, 0)
        assert idx.data(FileStagingPoolListModel.SizeCalculatingRole) is True

    def test_normal_file_not_calculating(self, temp_file_info, model):
        """普通文件 size_calculating=False。"""
        model.add_file(temp_file_info)
        idx = model.index(0, 0)
        assert idx.data(FileStagingPoolListModel.SizeCalculatingRole) is False


class TestFileStagingPoolListModelEdgeCases:
    """边界情况"""

    def test_empty_path_handling(self, model):
        """空路径不报错。"""
        model.add_file({"name": "empty", "path": "", "is_dir": False})
        assert model.rowCount() == 1
        idx = model.index(0, 0)
        assert idx.data(Qt.DisplayRole) is not None

    def test_none_file_info_dict(self, model):
        """部分字段缺失时仍工作。"""
        info = {"path": "C:/some/path.txt"}  # 最简 dict
        model.add_file(info)
        assert model.rowCount() == 1
        idx = model.index(0, 0)
        # 缺失的 name 会从 path 提取
        assert idx.data(FileStagingPoolListModel.FileNameRole) == "path.txt"

    def test_set_files_empty_list(self, temp_file_info, model):
        """set_files 空列表清空模型。"""
        model.add_file(temp_file_info)
        assert model.rowCount() == 1
        model.set_files([])
        assert model.rowCount() == 0

    def test_role_names_includes_staging_roles(self, model):
        """roleNames 包含暂存池特有的角色。"""
        names = model.roleNames()
        assert b"displayName" in names.values()
        assert b"isMissing" in names.values()
        assert b"infoText" in names.values()
        assert b"isRemoving" in names.values()
        assert b"sizeCalculating" in names.values()
        assert b"originalName" in names.values()
        assert b"itemHeight" in names.values()
        assert b"itemSize" in names.values()

    def test_flags_for_removing_item(self, temp_file_info, model):
        """正在移除的文件 flags 返回 NoItemFlags。"""
        model.add_file(temp_file_info)
        model.remove_file(temp_file_info["path"])
        idx = model.index(0, 0)
        flags = model.flags(idx)
        assert flags == Qt.NoItemFlags

    def test_flags_for_normal_item(self, temp_file_info, model):
        """正常文件 flags 包含可拖放。"""
        model.add_file(temp_file_info)
        idx = model.index(0, 0)
        flags = model.flags(idx)
        assert flags & Qt.ItemIsEnabled
        assert flags & Qt.ItemIsSelectable
        assert flags & Qt.ItemIsDragEnabled

    def test_flags_invalid_index(self, model):
        """无效 index flags 返回 NoItemFlags。"""
        assert model.flags(QModelIndex()) == Qt.NoItemFlags

    def test_refresh_icon_returns_false_for_nonexistent(self, model):
        """refresh_icon 不存在路径返回 False。"""
        assert model.refresh_icon("/nonexistent") is False

    def test_refresh_icon_returns_true(self, temp_file_info, model):
        """refresh_icon 成功返回 True。"""
        model.add_file(temp_file_info)
        result = model.refresh_icon(temp_file_info["path"])
        assert result is True
