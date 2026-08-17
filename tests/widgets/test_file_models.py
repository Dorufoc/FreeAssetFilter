# -*- coding: utf-8 -*-
# targets: widgets.file_selector_delegate, widgets.file_selector_model, widgets.file_staging_pool_delegate, widgets.file_staging_pool_model
"""
test_file_models - 文件选择器/存储池模型与委托的离屏渲染测试（widgets 批 3 之二）。

覆盖模块:
- freeassetfilter/widgets/file_selector_model.py（FileSelectorListModel / FileListView）
- freeassetfilter/widgets/file_selector_delegate.py（FileBlockCardDelegate）
- freeassetfilter/widgets/file_staging_pool_model.py
  （FileStagingPoolListModel / FileStagingPoolItemDelegate / FileStagingPoolListView）
- freeassetfilter/widgets/file_staging_pool_delegate.py（FileStagingPoolCardDelegate）

核心策略:
- 模型数据测试只做行数/角色取值/增删状态断言，不渲染。
- 委托渲染全部走离屏 QPixmap（delegate.paint 到 QPainter+Pixmap / widget.render），
  不弹真实窗口；用 QStyleOptionViewItem 手工构造 option，避免依赖真实视图。
- 用 ``no_card_animations`` fixture 关闭卡片状态动画，保证 paint 结果即时
  且不启动后台动画定时器。
- 通过 ``_StubSettingsManager`` 注入 get_setting，避免读写磁盘。
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest
from PySide6.QtCore import QModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionViewItem, QWidget

from tests.support.data_factories import file_info_dict, make_text
from tests.support.qt_helpers import (
    assert_pixmap_nonempty,
    process_qt_events,
    safe_teardown,
)

from freeassetfilter.widgets.file_selector_delegate import FileBlockCardDelegate
from freeassetfilter.widgets.file_selector_model import FileListView, FileSelectorListModel
from freeassetfilter.widgets.file_staging_pool_delegate import FileStagingPoolCardDelegate
from freeassetfilter.widgets.file_staging_pool_model import (
    FileStagingPoolItemDelegate,
    FileStagingPoolListModel,
    FileStagingPoolListView,
)

pytestmark = pytest.mark.unit


# =============================================================================
# 测试替身
# =============================================================================


class _StubSettingsManager:
    """get_setting 一律返回默认值的 SettingsManager 替身（避免触盘）。"""

    def get_setting(self, key: str, default: Any = None) -> Any:
        """返回默认值。

        Args:
            key: 设置键名（未使用）。
            default: 调用方给定的默认值。

        Returns:
            Any: 始终返回 default。
        """
        return default


# =============================================================================
# 文件内 fixture
# =============================================================================


@pytest.fixture
def no_card_animations(monkeypatch: pytest.MonkeyPatch) -> None:
    """关闭卡片/委托的状态动画，使 paint 结果即时生效。

    Args:
        monkeypatch: pytest 的 monkeypatch fixture。

    Returns:
        None。
    """
    monkeypatch.setattr(
        "freeassetfilter.widgets.base_card_delegate.is_animation_enabled",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr(
        "freeassetfilter.widgets.file_selector_delegate.is_animation_enabled",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr(
        "freeassetfilter.widgets.file_staging_pool_delegate.is_animation_enabled",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr(
        "freeassetfilter.widgets.file_staging_pool_model.is_animation_enabled",
        lambda *_a, **_k: False,
    )


@pytest.fixture
def stub_settings_manager() -> _StubSettingsManager:
    """返回共享的 SettingsManager 替身实例。

    Returns:
        _StubSettingsManager: 替身实例。
    """
    return _StubSettingsManager()


# =============================================================================
# 渲染辅助
# =============================================================================


def _render_widget_pixmap(
    widget: QWidget,
    width: int,
    height: int,
    app: QApplication,
) -> QPixmap:
    """把不可见的 widget 离屏渲染为指定尺寸的 QPixmap。

    Args:
        widget: 待渲染的 QWidget。
        width: 目标宽度。
        height: 目标高度。
        app: QApplication 实例（用于事件泵）。

    Returns:
        QPixmap: 渲染结果（尺寸为 width×height）。
    """
    widget.resize(width, height)
    layout = widget.layout()
    if layout is not None:
        layout.activate()
    process_qt_events(app, ms=10)
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.transparent)
    widget.render(pixmap)
    return pixmap


def _paint_delegate_pixmap(
    delegate,
    index,
    rect: QRect = QRect(0, 0, 300, 64),
    state: QStyle.StateFlag = QStyle.State_Enabled,
) -> QPixmap:
    """通过 delegate.paint 把一项渲染到离屏 QPixmap。

    Args:
        delegate: QStyledItemDelegate 子类实例。
        index: 模型索引。
        rect: option.rect。
        state: option.state 位组合。

    Returns:
        QPixmap: 渲染结果。
    """
    option = QStyleOptionViewItem()
    option.rect = rect
    option.state = state
    pixmap = QPixmap(rect.size())
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    delegate.paint(painter, option, index)
    painter.end()
    return pixmap


def _build_selector_model(
    file_infos: List[Dict[str, Any]],
    settings_manager: Any = None,
) -> FileSelectorListModel:
    """构建带一份文件数据的 FileSelectorListModel。

    Args:
        file_infos: 文件信息字典列表。
        settings_manager: 注入的 SettingsManager 替身（缺省 None）。

    Returns:
        FileSelectorListModel: 就绪的模型实例。
    """
    model = FileSelectorListModel(
        dpi_scale=1.0,
        global_font=QFont(),
        settings_manager=settings_manager or _StubSettingsManager(),
    )
    model.set_files([dict(info) for info in file_infos])
    return model


def _normal_file_info(path: str, name: str = "report.txt") -> Dict[str, Any]:
    """构造带完整展示字段的普通文件信息字典。

    Args:
        path: 文件路径。
        name: 显示名。

    Returns:
        dict[str, Any]: 兼容 FileSelectorListModel / FileStagingPoolListModel 的文件信息。
    """
    info = file_info_dict(path, ext="txt")
    info.update(
        {
            "name": name,
            "suffix": "txt",
            "is_dir": False,
            "size": 4096,
            "created": "2026-01-02T03:04:05",
            "is_selected": False,
            "is_previewing": False,
        }
    )
    return info


def _missing_file_info(path: str, name: str = "gone.png") -> Dict[str, Any]:
    """构造标记为缺失的文件信息字典。

    Args:
        path: 文件路径（不保证存在）。
        name: 显示名。

    Returns:
        dict[str, Any]: 兼容 FileSelectorListModel / FileStagingPoolListModel 的文件信息。
    """
    info = _normal_file_info(path, name=name)
    info["is_missing"] = True
    return info


# =============================================================================
# FileSelectorListModel / FileListView
# =============================================================================


class TestFileSelectorListModel:
    """FileSelectorListModel 数据模型测试。"""

    def test_constructor_defaults(self, stub_settings_manager: _StubSettingsManager) -> None:
        """默认构造应初始化为空列表与默认卡片尺寸。

        Args:
            stub_settings_manager: SettingsManager 替身。
        """
        model = FileSelectorListModel(
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        assert model.rowCount() == 0
        assert model._card_width == 150
        assert model._card_height == 75
        assert model._max_cols == 3
        assert model.sizeHint() == QSize(150, 75)

    def test_role_constants(self) -> None:
        """角色常量应从 UserRole+1 递增到 UserRole+11。

        Returns:
            None。
        """
        model = FileSelectorListModel()
        assert model.FilePathRole == Qt.UserRole + 1
        assert model.FileNameRole == Qt.UserRole + 2
        assert model.IsDirRole == Qt.UserRole + 3
        assert model.FileSizeRole == Qt.UserRole + 4
        assert model.CreatedRole == Qt.UserRole + 5
        assert model.SuffixRole == Qt.UserRole + 6
        assert model.IsSelectedRole == Qt.UserRole + 7
        assert model.IsPreviewingRole == Qt.UserRole + 8
        assert model.IconPixmapRole == Qt.UserRole + 9
        assert model.CardWidthRole == Qt.UserRole + 10
        assert model.GridOffsetRole == Qt.UserRole + 11

    def test_set_files_populates_rows(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
    ) -> None:
        """set_files 后数据角色应正确返回。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
        """
        model = _build_selector_model(
            [_normal_file_info("C:/tmp/aaa.txt", name="aaa.txt")],
            settings_manager=stub_settings_manager,
        )
        assert model.rowCount() == 1
        index = model.index(0, 0)
        assert model.data(index, Qt.DisplayRole) == "aaa.txt"
        assert model.data(index, model.FilePathRole) == "C:/tmp/aaa.txt"
        assert model.data(index, model.IsDirRole) is False
        assert model.data(index, model.FileSizeRole) == 4096
        assert model.data(index, model.SuffixRole) == "txt"
        assert model.data(index, model.IsSelectedRole) is False
        assert model.data(index, model.IsPreviewingRole) is False
        assert model.data(index, model.CardWidthRole) == 150

    def test_set_selected_and_get_selected_files(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
    ) -> None:
        """set_selected 应更新 IsSelectedRole，get_selected_files 返回路径列表。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
        """
        model = _build_selector_model(
            [_normal_file_info("C:/tmp/bbb.txt", name="bbb.txt")],
            settings_manager=stub_settings_manager,
        )
        assert model.set_selected("C:/tmp/bbb.txt", True) is True
        assert model.data(model.index(0, 0), model.IsSelectedRole) is True
        assert model.get_selected_files() == ["C:/tmp/bbb.txt"]
        assert model.set_selected("C:/tmp/absent.txt", True) is False
        assert model.set_selected("C:/tmp/bbb.txt", False) is True
        assert model.get_selected_files() == []

    def test_set_previewing_and_clear_previewing(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
    ) -> None:
        """set_previewing 与 clear_previewing 应更新 IsPreviewingRole。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
        """
        model = _build_selector_model(
            [
                _normal_file_info("C:/tmp/ccc.txt", name="ccc.txt"),
                _normal_file_info("C:/tmp/ddd.txt", name="ddd.txt"),
            ],
            settings_manager=stub_settings_manager,
        )
        model.set_previewing("C:/tmp/ccc.txt", True)
        assert model.data(model.index(0, 0), model.IsPreviewingRole) is True
        assert model.data(model.index(1, 0), model.IsPreviewingRole) is False
        model.clear_previewing()
        assert model.data(model.index(0, 0), model.IsPreviewingRole) is False

    def test_clear_empties_model(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
    ) -> None:
        """clear 应清空所有行。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
        """
        model = _build_selector_model(
            [_normal_file_info("C:/tmp/eee.txt", name="eee.txt")],
            settings_manager=stub_settings_manager,
        )
        assert model.rowCount() == 1
        model.clear()
        assert model.rowCount() == 0

    def test_get_file_info_returns_copy(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
    ) -> None:
        """get_file_info 应返回该行文件信息副本。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
        """
        model = _build_selector_model(
            [_normal_file_info("C:/tmp/fff.txt", name="fff.txt")],
            settings_manager=stub_settings_manager,
        )
        info = model.get_file_info(model.index(0, 0))
        assert info["path"] == "C:/tmp/fff.txt"
        invalid = model.get_file_info(model.index(99, 0))
        assert invalid == {}

    def test_set_card_width_emits_data_changed(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
    ) -> None:
        """set_card_width 应更新 CardWidthRole 并发出 dataChanged。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
        """
        model = _build_selector_model(
            [_normal_file_info("C:/tmp/ggg.txt", name="ggg.txt")],
            settings_manager=stub_settings_manager,
        )
        fired: List[int] = []

        def _on_data_changed(top_left, bottom_right, roles) -> None:
            fired.append(1)

        model.dataChanged.connect(_on_data_changed)
        model.set_card_width(180, 90, 2)
        assert model.data(model.index(0, 0), model.CardWidthRole) == 180
        assert fired
        # 相同值不应重复发射
        before = list(fired)
        model.set_card_width(180, 90, 2)
        assert len(fired) == len(before)

    def test_set_grid_offset_x(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
    ) -> None:
        """set_grid_offset_x 应更新 GridOffsetRole。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
        """
        model = _build_selector_model(
            [_normal_file_info("C:/tmp/hhh.txt", name="hhh.txt")],
            settings_manager=stub_settings_manager,
        )
        model.set_grid_offset_x(12)
        assert model.data(model.index(0, 0), model.GridOffsetRole) == 12

    def test_role_names_present(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
    ) -> None:
        """roleNames 应包含全部自定义角色。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
        """
        model = FileSelectorListModel(
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        names = model.roleNames()
        assert names[model.FilePathRole] == b"filePath"
        assert names[model.FileNameRole] == b"fileName"
        assert names[model.IsDirRole] == b"isDir"
        assert names[model.FileSizeRole] == b"fileSize"
        assert names[model.CreatedRole] == b"created"
        assert names[model.SuffixRole] == b"suffix"
        assert names[model.IsSelectedRole] == b"isSelected"
        assert names[model.IsPreviewingRole] == b"isPreviewing"
        assert names[model.IconPixmapRole] == b"iconPixmap"
        assert names[model.CardWidthRole] == b"cardWidth"
        assert names[model.GridOffsetRole] == b"gridOffsetX"

    def test_flags_include_extended_interaction(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
    ) -> None:
        """有效索引 flags 应允许选择；无效索引应为 NoItemFlags。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
        """
        model = _build_selector_model(
            [_normal_file_info("C:/tmp/iii.txt", name="iii.txt")],
            settings_manager=stub_settings_manager,
        )
        flags = model.flags(model.index(0, 0))
        assert flags & Qt.ItemIsEnabled
        assert flags & Qt.ItemIsSelectable
        assert model.flags(QModelIndex()) == Qt.NoItemFlags


class TestFileListView:
    """FileListView 视图构造与信号定义测试。"""

    def test_constructor_with_stub_settings(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
    ) -> None:
        """带替身设置构造视图不应崩溃。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
        """
        view = FileListView(
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        assert view._settings_manager is stub_settings_manager
        safe_teardown(view)

    def test_signals_defined(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
    ) -> None:
        """FileListView 应暴露约定的 Qt 信号。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
        """
        view = FileListView(settings_manager=stub_settings_manager)
        expected = {
            "file_clicked",
            "file_double_clicked",
            "file_right_clicked",
            "file_selection_changed",
            "file_drag_started",
            "file_drag_ended",
            "navigate_parent_requested",
        }
        assert expected <= set(view.__class__.__dict__)
        safe_teardown(view)


# =============================================================================
# FileBlockCardDelegate
# =============================================================================


class TestFileBlockCardDelegate:
    """FileBlockCardDelegate 构造与离屏渲染测试。"""

    def test_construct_defaults(self, stub_settings_manager: _StubSettingsManager) -> None:
        """默认构造应初始化颜色与字体属性。

        Args:
            stub_settings_manager: SettingsManager 替身。
        """
        delegate = FileBlockCardDelegate(
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        assert delegate._dpi_scale == 1.0
        assert hasattr(delegate, "name_font_metrics")
        assert hasattr(delegate, "small_font_metrics")

    def test_paint_to_pixmap(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
    ) -> None:
        """块委托 paint() 到 QPixmap 应非空。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
        """
        model = _build_selector_model(
            [_normal_file_info("C:/tmp/alpha.txt")],
            settings_manager=stub_settings_manager,
        )
        delegate = FileBlockCardDelegate(
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        pixmap = _paint_delegate_pixmap(delegate, model.index(0, 0))
        assert_pixmap_nonempty(pixmap)

    def test_paint_selected_and_hovered_no_crash(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
    ) -> None:
        """块委托的选中/悬停状态渲染不应崩溃。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
        """
        model = _build_selector_model(
            [_normal_file_info("C:/tmp/bravo.txt")],
            settings_manager=stub_settings_manager,
        )
        delegate = FileBlockCardDelegate(
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        index = model.index(0, 0)
        hovered = _paint_delegate_pixmap(
            delegate,
            index,
            rect=QRect(0, 0, 200, 160),
            state=QStyle.State_Enabled | QStyle.State_MouseOver,
        )
        assert_pixmap_nonempty(hovered)
        model.set_selected("C:/tmp/bravo.txt", True)
        model.set_previewing("C:/tmp/bravo.txt", True)
        selected = _paint_delegate_pixmap(delegate, index, rect=QRect(0, 0, 200, 160))
        assert_pixmap_nonempty(selected)

    def test_paint_missing_file_no_crash(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
    ) -> None:
        """块委托对缺失文件项渲染不应崩溃。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
        """
        model = _build_selector_model(
            [_missing_file_info("C:/tmp/gone_alpha.txt")],
            settings_manager=stub_settings_manager,
        )
        delegate = FileBlockCardDelegate(
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        pixmap = _paint_delegate_pixmap(delegate, model.index(0, 0))
        assert_pixmap_nonempty(pixmap)

    def test_size_hint_uses_card_width(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
    ) -> None:
        """sizeHint 应读取模型 CardWidthRole（Qt.UserRole+10）。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
        """
        model = _build_selector_model(
            [_normal_file_info("C:/tmp/charlie.txt")],
            settings_manager=stub_settings_manager,
        )
        model.set_card_width(180, 90, 2)
        delegate = FileBlockCardDelegate(
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        option = QStyleOptionViewItem()
        hint = delegate.sizeHint(option, model.index(0, 0))
        assert hint.width() == 180
        assert hint.height() > 0


# =============================================================================
# FileStagingPoolListModel
# =============================================================================


class TestFileStagingPoolListModel:
    """FileStagingPoolListModel 数据模型测试。"""

    def test_constructor_defaults(self) -> None:
        """默认构造应使用存储池默认卡片尺寸。

        Returns:
            None。
        """
        model = FileStagingPoolListModel(dpi_scale=1.0, global_font=QFont())
        assert model.rowCount() == 0
        assert model.item_size() == QSize(320, 56)

    def test_role_constants(self) -> None:
        """存储池自定义角色应从 CardWidthRole+1 递增到 ItemSizeRole+1。

        Returns:
            None。
        """
        model = FileStagingPoolListModel()
        base = FileSelectorListModel.CardWidthRole
        assert model.DisplayNameRole == base + 1
        assert model.OriginalNameRole == base + 2
        assert model.ModifiedRole == base + 3
        assert model.IsMissingRole == base + 4
        assert model.SizeCalculatingRole == base + 5
        assert model.InfoTextRole == base + 6
        assert model.ItemHeightRole == base + 7
        assert model.ItemSizeRole == base + 8
        assert model.IsRemovingRole == base + 9

    def test_add_file_returns_true_and_populates(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
        tmp_path,
    ) -> None:
        """add_file 应新增一行并返回 True。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
            tmp_path: pytest 临时目录。
        """
        file_path = make_text(str(tmp_path / "staged.txt"), content="staged")
        model = FileStagingPoolListModel(dpi_scale=1.0, global_font=QFont())
        assert model.add_file(_normal_file_info(file_path)) is True
        assert model.rowCount() == 1
        index = model.index(0, 0)
        assert model.data(index, Qt.DisplayRole) == "report.txt"
        assert model.data(index, model.DisplayNameRole) == "report.txt"
        assert model.data(index, model.IsMissingRole) is False
        assert model.data(index, model.ItemSizeRole) == QSize(320, 56)
        assert model.has_path(file_path) is True

    def test_add_duplicate_returns_false(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
        tmp_path,
    ) -> None:
        """重复路径 add_file 应被拒绝。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
            tmp_path: pytest 临时目录。
        """
        file_path = make_text(str(tmp_path / "dup.txt"), content="dup")
        model = FileStagingPoolListModel(dpi_scale=1.0, global_font=QFont())
        info = _normal_file_info(file_path)
        assert model.add_file(info) is True
        assert model.add_file(dict(info)) is False
        assert model.rowCount() == 1

    def test_add_missing_file_marks_missing(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
        tmp_path,
    ) -> None:
        """add_file 不存在的路径应标记 is_missing。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
            tmp_path: pytest 临时目录。
        """
        missing_path = str(tmp_path / "absent.png")
        model = FileStagingPoolListModel(dpi_scale=1.0, global_font=QFont())
        model.add_file(_normal_file_info(missing_path))
        assert model.has_path(missing_path) is True
        assert model.data(model.index(0, 0), model.IsMissingRole) is True

    def test_remove_marks_removing_then_finalize(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
        tmp_path,
    ) -> None:
        """remove_file 标记 is_removing，finalize_remove_file 删除该行。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
            tmp_path: pytest 临时目录。
        """
        file_path = make_text(str(tmp_path / "bye.txt"), content="bye")
        model = FileStagingPoolListModel(dpi_scale=1.0, global_font=QFont())
        model.add_file(_normal_file_info(file_path))
        removed = model.remove_file(file_path)
        assert removed.get("path", "") == file_path
        assert model.data(model.index(0, 0), model.IsRemovingRole) is True
        # 已标记移除的项目不可再移除
        assert model.remove_file(file_path) == {}
        finalized = model.finalize_remove_file(file_path)
        assert finalized.get("path", "") == file_path
        assert model.rowCount() == 0

    def test_remove_unknown_path_returns_empty(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
    ) -> None:
        """移除不存在路径应返回空字典。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
        """
        model = FileStagingPoolListModel(dpi_scale=1.0, global_font=QFont())
        assert model.remove_file("C:/tmp/nope.txt") == {}
        assert model.finalize_remove_file("C:/tmp/nope.txt") == {}

    def test_update_and_rename_file(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
        tmp_path,
    ) -> None:
        """update_file/rename_file 应更新展示名称。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
            tmp_path: pytest 临时目录。
        """
        file_path = make_text(str(tmp_path / "orig.txt"), content="orig")
        model = FileStagingPoolListModel(dpi_scale=1.0, global_font=QFont())
        model.add_file(_normal_file_info(file_path))
        assert model.rename_file(file_path, "新名称") is True
        assert model.data(model.index(0, 0), model.DisplayNameRole) == "新名称"
        assert model.update_file(file_path, {"info_text": "自定义说明"}) is True
        assert model.data(model.index(0, 0), model.InfoTextRole) == "自定义说明"
        assert model.update_file("C:/tmp/unknown.txt", {"display_name": "x"}) is False

    def test_flags_disabled_while_removing(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
        tmp_path,
    ) -> None:
        """is_removing 状态下 flags 应为 NoItemFlags。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
            tmp_path: pytest 临时目录。
        """
        file_path = make_text(str(tmp_path / "flags.txt"), content="flags")
        model = FileStagingPoolListModel(dpi_scale=1.0, global_font=QFont())
        model.add_file(_normal_file_info(file_path))
        assert model.flags(model.index(0, 0)) & Qt.ItemIsEnabled
        model.remove_file(file_path)
        assert model.flags(model.index(0, 0)) == Qt.NoItemFlags


# =============================================================================
# FileStagingPoolItemDelegate
# =============================================================================


class TestFileStagingPoolItemDelegate:
    """FileStagingPoolItemDelegate 构造与离屏渲染测试。"""

    def test_construct_defaults(self, stub_settings_manager: _StubSettingsManager) -> None:
        """默认构造应初始化 dpi 与字体属性。

        Args:
            stub_settings_manager: SettingsManager 替身。
        """
        delegate = FileStagingPoolItemDelegate(
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        assert delegate._dpi_scale == 1.0
        assert delegate._dragging_file_path == ""

    def test_paint_to_pixmap(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
        tmp_path,
    ) -> None:
        """存储池委托 paint() 到 QPixmap 应非空。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
            tmp_path: pytest 临时目录。
        """
        file_path = make_text(str(tmp_path / "item.txt"), content="item")
        model = FileStagingPoolListModel(dpi_scale=1.0, global_font=QFont())
        model.add_file(_normal_file_info(file_path))
        delegate = FileStagingPoolItemDelegate(
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        pixmap = _paint_delegate_pixmap(delegate, model.index(0, 0))
        assert_pixmap_nonempty(pixmap)

    def test_paint_states_no_crash(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
        tmp_path,
    ) -> None:
        """选中/预览/缺失/拖拽状态的存储池委托渲染不应崩溃。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
            tmp_path: pytest 临时目录。
        """
        file_path = make_text(str(tmp_path / "states.txt"), content="states")
        model = FileStagingPoolListModel(dpi_scale=1.0, global_font=QFont())
        model.add_file(_normal_file_info(file_path))
        delegate = FileStagingPoolItemDelegate(
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        model.set_selected(file_path, True)
        model.set_previewing(file_path, True)
        index = model.index(0, 0)
        selected = _paint_delegate_pixmap(delegate, index)
        assert_pixmap_nonempty(selected)
        delegate.set_dragging_file_path(file_path)
        dragging = _paint_delegate_pixmap(delegate, index)
        assert_pixmap_nonempty(dragging)

    def test_paint_missing_file_no_crash(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
        tmp_path,
    ) -> None:
        """存储池委托对缺失文件项渲染不应崩溃。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
            tmp_path: pytest 临时目录。
        """
        missing_path = str(tmp_path / "gone_item.png")
        model = FileStagingPoolListModel(dpi_scale=1.0, global_font=QFont())
        model.add_file(_missing_file_info(missing_path))
        delegate = FileStagingPoolItemDelegate(
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        pixmap = _paint_delegate_pixmap(delegate, model.index(0, 0))
        assert_pixmap_nonempty(pixmap)

    def test_build_drag_pixmap(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
        tmp_path,
    ) -> None:
        """build_drag_pixmap 应返回非空 pixmap。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
            tmp_path: pytest 临时目录。
        """
        file_path = make_text(str(tmp_path / "drag_item.txt"), content="drag")
        model = FileStagingPoolListModel(dpi_scale=1.0, global_font=QFont())
        model.add_file(_normal_file_info(file_path))
        delegate = FileStagingPoolItemDelegate(
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        from PySide6.QtGui import QPalette

        pixmap = delegate.build_drag_pixmap(model.index(0, 0), QSize(300, 64), QPalette())
        assert_pixmap_nonempty(pixmap)

    def test_size_hint_uses_item_size(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
        tmp_path,
    ) -> None:
        """sizeHint 应返回模型的 item_size。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
            tmp_path: pytest 临时目录。
        """
        file_path = make_text(str(tmp_path / "hint_item.txt"), content="hint")
        model = FileStagingPoolListModel(dpi_scale=1.0, global_font=QFont())
        model.add_file(_normal_file_info(file_path))
        model.set_item_size(300, 56)
        delegate = FileStagingPoolItemDelegate(
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        option = QStyleOptionViewItem()
        assert delegate.sizeHint(option, model.index(0, 0)) == QSize(300, 56)


# =============================================================================
# FileStagingPoolListView
# =============================================================================


class TestFileStagingPoolListView:
    """FileStagingPoolListView 视图构造与信号定义测试。"""

    def test_constructor_with_stub_settings(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
    ) -> None:
        """带替身设置构造存储池视图不应崩溃。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
        """
        view = FileStagingPoolListView(
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        assert view._settings_manager is stub_settings_manager
        assert view._delegate is not None
        safe_teardown(view)

    def test_signals_defined(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
    ) -> None:
        """FileStagingPoolListView 应暴露存储池专属信号。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
        """
        view = FileStagingPoolListView(settings_manager=stub_settings_manager)
        expected = {
            "item_left_clicked",
            "item_right_clicked",
            "item_double_clicked",
            "drag_started",
            "drag_ended",
        }
        assert expected <= set(view.__class__.__dict__)
        safe_teardown(view)

    def test_build_default_model(self, qapp: QApplication, stub_settings_manager: _StubSettingsManager) -> None:
        """build_default_model 应返回 FileStagingPoolListModel。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
        """
        view = FileStagingPoolListView(settings_manager=stub_settings_manager)
        model = view.build_default_model()
        assert isinstance(model, FileStagingPoolListModel)
        safe_teardown(view)


# =============================================================================
# FileStagingPoolCardDelegate
# =============================================================================


class TestFileStagingPoolCardDelegate:
    """FileStagingPoolCardDelegate 构造与离屏渲染测试。"""

    def test_construct_defaults(self, stub_settings_manager: _StubSettingsManager) -> None:
        """默认构造应初始化单行模式与删除动作开关。

        Args:
            stub_settings_manager: SettingsManager 替身。
        """
        delegate = FileStagingPoolCardDelegate(
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        assert delegate._single_line_mode is True
        assert delegate._enable_delete_action is False
        assert delegate._dpi_scale == 1.0

    def test_signals_and_actions_defined(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
    ) -> None:
        """存储池卡片委托应暴露重命名/删除信号与动作常量。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
        """
        delegate = FileStagingPoolCardDelegate(
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        assert "renameRequested" in delegate.__class__.__dict__
        assert "deleteRequested" in delegate.__class__.__dict__
        assert delegate.ACTION_RENAME == "rename"
        assert delegate.ACTION_DELETE == "delete"

    def test_set_single_line_mode_and_delete_action(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
    ) -> None:
        """set_single_line_mode / set_enable_delete_action 应更新开关。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
        """
        delegate = FileStagingPoolCardDelegate(
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        delegate.set_single_line_mode(False)
        assert delegate._single_line_mode is False
        delegate.set_enable_delete_action(True)
        assert delegate._enable_delete_action is True
        delegate.clear_caches()
        assert delegate._pressed_action_key is None

    def test_paint_to_pixmap(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
        tmp_path,
    ) -> None:
        """存储池卡片委托 paint() 到 QPixmap 应非空。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
            tmp_path: pytest 临时目录。
        """
        file_path = make_text(str(tmp_path / "card_item.txt"), content="card")
        model = FileStagingPoolListModel(dpi_scale=1.0, global_font=QFont())
        model.add_file(_normal_file_info(file_path))
        delegate = FileStagingPoolCardDelegate(
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        pixmap = _paint_delegate_pixmap(delegate, model.index(0, 0))
        assert_pixmap_nonempty(pixmap)

    def test_paint_states_no_crash(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
        tmp_path,
    ) -> None:
        """选中/预览/单行删除模式下的存储池卡片委托渲染不应崩溃。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
            tmp_path: pytest 临时目录。
        """
        file_path = make_text(str(tmp_path / "card_states.txt"), content="states")
        model = FileStagingPoolListModel(dpi_scale=1.0, global_font=QFont())
        model.add_file(_normal_file_info(file_path))
        delegate = FileStagingPoolCardDelegate(
            dpi_scale=1.0,
            global_font=QFont(),
            single_line_mode=False,
            enable_delete_action=True,
            settings_manager=stub_settings_manager,
        )
        model.set_selected(file_path, True)
        index = model.index(0, 0)
        selected = _paint_delegate_pixmap(delegate, index)
        assert_pixmap_nonempty(selected)
        model.set_selected(file_path, False)
        model.set_previewing(file_path, True)
        preview = _paint_delegate_pixmap(delegate, index)
        assert_pixmap_nonempty(preview)

    def test_paint_missing_file_no_crash(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
        tmp_path,
    ) -> None:
        """存储池卡片委托对缺失文件项渲染不应崩溃。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
            tmp_path: pytest 临时目录。
        """
        missing_path = str(tmp_path / "gone_card.png")
        model = FileStagingPoolListModel(dpi_scale=1.0, global_font=QFont())
        model.add_file(_missing_file_info(missing_path))
        delegate = FileStagingPoolCardDelegate(
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        pixmap = _paint_delegate_pixmap(delegate, model.index(0, 0))
        assert_pixmap_nonempty(pixmap)

    def test_size_hint_uses_item_size(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
        tmp_path,
    ) -> None:
        """存储池卡片委托 sizeHint 应读取 ItemSizeRole。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
            tmp_path: pytest 临时目录。
        """
        file_path = make_text(str(tmp_path / "card_hint.txt"), content="hint")
        model = FileStagingPoolListModel(dpi_scale=1.0, global_font=QFont())
        model.add_file(_normal_file_info(file_path))
        model.set_item_size(320, 64)
        delegate = FileStagingPoolCardDelegate(
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        option = QStyleOptionViewItem()
        hint = delegate.sizeHint(option, model.index(0, 0))
        assert hint == QSize(320, 64)
