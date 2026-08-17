# -*- coding: utf-8 -*-
# targets: widgets.base_card_delegate, widgets.file_block_card, widgets.file_horizontal_card, widgets.file_horizontal_card_delegate
#       widgets.file_selector_model
"""
test_card_delegates - 卡片基类委托与卡片控件的离屏渲染测试（widgets 批 3 之一）。

覆盖模块:
- freeassetfilter/widgets/base_card_delegate.py（BaseCardDelegate）
- freeassetfilter/widgets/file_block_card.py（FileBlockCard）
- freeassetfilter/widgets/file_horizontal_card.py（CustomFileHorizontalCard）
- freeassetfilter/widgets/file_horizontal_card_delegate.py（FileHorizontalCardDelegate）

核心策略:
- 全部渲染走离屏 QPixmap（QWidget.render / delegate.paint 到 QPainter+Pixmap），
  不弹真实窗口；用 QStyleOptionViewItem 手工构造 option，避免依赖真实视图。
- 用本文件内的 ``_MinimalCardDelegate`` 作为 BaseCardDelegate 的最小具体子类，
  通过它驱动基类的 paint()/动画同步/阴影/颜色管线。
- 用 ``no_card_animations`` fixture 关闭卡片状态动画，保证 paint 结果即时
  且不启动后台动画定时器。
- 通过 ``_StubSettingsManager`` 注入 get_setting，避免读写磁盘。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

import pytest
from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPalette, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionViewItem, QWidget

from tests.support.data_factories import file_info_dict, make_text
from tests.support.qt_helpers import (
    assert_pixmap_nonempty,
    process_qt_events,
    safe_teardown,
)

from freeassetfilter.widgets.base_card_delegate import BaseCardDelegate
from freeassetfilter.widgets.file_block_card import FileBlockCard
from freeassetfilter.widgets.file_horizontal_card import CustomFileHorizontalCard
from freeassetfilter.widgets.file_horizontal_card_delegate import FileHorizontalCardDelegate
from freeassetfilter.widgets.file_selector_model import FileSelectorListModel

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


class _MinimalCardDelegate(BaseCardDelegate):
    """BaseCardDelegate 的最小具体子类：_paint_card 用背景色填充选区。

    基类 ``_paint_card`` 抛 NotImplementedError，本类补齐该抽象方法，
    从而能够驱动基类的 paint()/动画同步/取色/阴影整条管线。
    """

    def _paint_card(self, painter, option, index, for_drag_preview=False):
        """用当前动画背景色填充 option.rect。

        Args:
            painter: 目标 QPainter。
            option: QStyleOptionViewItem（含 rect/state）。
            index: 模型索引（本实现不使用）。
            for_drag_preview: 拖拽预览标记（透传给取色逻辑）。
        """
        anim_key = self._get_animation_key({})
        anim_state = self._sync_animation_state(anim_key, {}, False, False, False)
        colors = self._get_paint_colors(
            {"border_width": 1, "preview_border_width": 2},
            False,
            False,
            anim_state,
            for_drag_preview=for_drag_preview,
        )
        painter.fillRect(option.rect, colors[0])


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
        "freeassetfilter.widgets.file_block_card.is_animation_enabled",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr(
        "freeassetfilter.widgets.file_horizontal_card.is_animation_enabled",
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
    rect: QRect = QRect(0, 0, 280, 140),
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
        dict[str, Any]: 兼容 FileSelectorListModel 的文件信息。
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
        dict[str, Any]: 兼容 FileSelectorListModel 的文件信息。
    """
    info = _normal_file_info(path, name=name)
    info["is_missing"] = True
    return info


# =============================================================================
# BaseCardDelegate
# =============================================================================


class TestBaseCardDelegate:
    """BaseCardDelegate 构造与基类绘制管线测试。"""

    def test_constructor_defaults(self, stub_settings_manager: _StubSettingsManager) -> None:
        """默认构造应初始化颜色与字体属性。

        Args:
            stub_settings_manager: SettingsManager 替身。
        """
        delegate = BaseCardDelegate(
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        assert delegate._dpi_scale == 1.0
        assert delegate._view is None
        assert delegate._animation_states == {}
        assert delegate.base_color == "#212121"
        assert hasattr(delegate, "name_font")
        assert hasattr(delegate, "small_font")
        assert hasattr(delegate, "name_font_metrics")

    def test_constructor_with_parent(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
    ) -> None:
        """传入 parent 应建立父子关系。

        Args:
            qapp: 会话级 QApplication（创建 QWidget 前必须先存在）。
            stub_settings_manager: SettingsManager 替身。
        """
        parent = QWidget()
        delegate = BaseCardDelegate(
            dpi_scale=2.0,
            global_font=QFont("Arial", 12),
            parent=parent,
            settings_manager=stub_settings_manager,
        )
        assert delegate.parent() is parent
        assert delegate._dpi_scale == 2.0
        safe_teardown(parent)

    def test_paint_to_pixmap_via_minimal_subclass(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
    ) -> None:
        """基类 paint() 到 QPixmap 应不崩溃且产生非空内容。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
        """
        model = _build_selector_model(
            [_normal_file_info("C:/tmp/alpha.txt")],
            settings_manager=stub_settings_manager,
        )
        delegate = _MinimalCardDelegate(
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        index = model.index(0, 0)
        pixmap = _paint_delegate_pixmap(delegate, index)
        assert_pixmap_nonempty(pixmap)

    def test_paint_hovered_and_selected_no_crash(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
    ) -> None:
        """悬停与选中状态下的基类 paint() 不应崩溃。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
        """
        model = _build_selector_model(
            [_normal_file_info("C:/tmp/bravo.txt")],
            settings_manager=stub_settings_manager,
        )
        delegate = _MinimalCardDelegate(
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        index = model.index(0, 0)
        hovered = _paint_delegate_pixmap(
            delegate,
            index,
            state=QStyle.State_Enabled | QStyle.State_MouseOver,
        )
        assert_pixmap_nonempty(hovered)
        delegate.clear_caches()
        selected = _paint_delegate_pixmap(delegate, index)
        assert_pixmap_nonempty(selected)

    def test_missing_file_paint_no_crash(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
    ) -> None:
        """缺失文件项的基类 paint() 不应崩溃。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
        """
        model = _build_selector_model(
            [_missing_file_info("C:/tmp/nope.txt")],
            settings_manager=stub_settings_manager,
        )
        delegate = _MinimalCardDelegate(
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
    ) -> None:
        """build_drag_pixmap 应返回非空 pixmap。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
        """
        model = _build_selector_model(
            [_normal_file_info("C:/tmp/charlie.txt")],
            settings_manager=stub_settings_manager,
        )
        delegate = _MinimalCardDelegate(
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        index = model.index(0, 0)
        palette = QPalette()
        pixmap = delegate.build_drag_pixmap(index, QSize(200, 100), palette)
        assert_pixmap_nonempty(pixmap)

    def test_update_theme_and_clear_caches_no_crash(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
    ) -> None:
        """update_theme 与 clear_caches 不应崩溃。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
        """
        delegate = _MinimalCardDelegate(
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        delegate.update_theme()
        delegate.clear_caches()
        delegate.set_dragging_file_path("C:/tmp/abc.txt")
        assert delegate._dragging_file_path == os.path.normpath("C:/tmp/abc.txt")


# =============================================================================
# FileBlockCard
# =============================================================================


class TestFileBlockCard:
    """FileBlockCard 控件构造与离屏渲染测试。"""

    def test_construct_and_render_pixmap(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
        tmp_path,
    ) -> None:
        """正常文件的卡片离屏渲染应非空。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
            tmp_path: pytest 临时目录。
        """
        file_path = make_text(str(tmp_path / "hello.txt"), content="hello")
        info = _normal_file_info(file_path)
        card = FileBlockCard(
            file_info=info,
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        pixmap = _render_widget_pixmap(card, 180, 150, qapp)
        assert_pixmap_nonempty(pixmap)
        safe_teardown(card)

    def test_render_selected_and_previewing(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
        tmp_path,
    ) -> None:
        """选中与预览状态下的卡片渲染不应崩溃。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
            tmp_path: pytest 临时目录。
        """
        file_path = make_text(str(tmp_path / "selected.txt"), content="sel")
        card = FileBlockCard(
            file_info=_normal_file_info(file_path),
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        card.set_selected(True)
        card.set_previewing(True)
        pixmap = _render_widget_pixmap(card, 180, 150, qapp)
        assert_pixmap_nonempty(pixmap)
        safe_teardown(card)

    def test_missing_file_paint_no_crash(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
        tmp_path,
    ) -> None:
        """缺失文件的卡片渲染不应崩溃。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
            tmp_path: pytest 临时目录。
        """
        missing_path = str(tmp_path / "does_not_exist.png")
        card = FileBlockCard(
            file_info=_missing_file_info(missing_path),
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        pixmap = _render_widget_pixmap(card, 180, 150, qapp)
        assert_pixmap_nonempty(pixmap)
        safe_teardown(card)

    def test_set_file_info_updates_render(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
        tmp_path,
    ) -> None:
        """set_file_info 后重新渲染不应崩溃。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
            tmp_path: pytest 临时目录。
        """
        file_path = make_text(str(tmp_path / "swap.txt"), content="swap")
        card = FileBlockCard(
            file_info=_normal_file_info(str(tmp_path / "first.txt")),
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        card.set_file_info(_normal_file_info(file_path, name="second.txt"))
        pixmap = _render_widget_pixmap(card, 180, 150, qapp)
        assert_pixmap_nonempty(pixmap)
        safe_teardown(card)


# =============================================================================
# CustomFileHorizontalCard
# =============================================================================


class TestCustomFileHorizontalCard:
    """CustomFileHorizontalCard 控件构造与离屏渲染测试。"""

    def test_construct_without_file(self, qapp: QApplication, stub_settings_manager: _StubSettingsManager) -> None:
        """未指定文件路径的横向卡片应能构造。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
        """
        card = CustomFileHorizontalCard(
            file_path=None,
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        assert card._file_path is None
        safe_teardown(card)

    def test_render_pixmap_with_real_file(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
        tmp_path,
    ) -> None:
        """带真实文件的横向卡片离屏渲染应非空。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
            tmp_path: pytest 临时目录。
        """
        file_path = make_text(str(tmp_path / "card.txt"), content="card")
        card = CustomFileHorizontalCard(
            file_path=file_path,
            enable_multiselect=True,
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        pixmap = _render_widget_pixmap(card, 600, 60, qapp)
        assert_pixmap_nonempty(pixmap)
        safe_teardown(card)

    def test_missing_path_paint_no_crash(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
        tmp_path,
    ) -> None:
        """缺失路径的横向卡片渲染不应崩溃。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
            tmp_path: pytest 临时目录。
        """
        missing_path = str(tmp_path / "missing.png")
        card = CustomFileHorizontalCard(
            file_path=missing_path,
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        card.set_path_exists(False)
        pixmap = _render_widget_pixmap(card, 600, 60, qapp)
        assert_pixmap_nonempty(pixmap)
        safe_teardown(card)

    def test_selected_and_previewing_no_crash(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
        tmp_path,
    ) -> None:
        """选中与预览状态的横向卡片渲染不应崩溃。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
            tmp_path: pytest 临时目录。
        """
        file_path = make_text(str(tmp_path / "state.txt"), content="state")
        card = CustomFileHorizontalCard(
            file_path=file_path,
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        card.set_selected(True)
        card.set_previewing(True)
        card.set_custom_info_text("自定义说明")
        pixmap = _render_widget_pixmap(card, 600, 60, qapp)
        assert_pixmap_nonempty(pixmap)
        safe_teardown(card)

    def test_signals_defined(self, qapp: QApplication, stub_settings_manager: _StubSettingsManager) -> None:
        """横向卡片应暴露约定的 Qt 信号。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
        """
        card = CustomFileHorizontalCard(
            file_path=None,
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        expected = {
            "clicked",
            "doubleClicked",
            "selectionChanged",
            "previewStateChanged",
            "renameRequested",
            "deleteRequested",
            "drag_started",
            "drag_ended",
        }
        assert expected <= set(card.__class__.__dict__)
        safe_teardown(card)


# =============================================================================
# FileHorizontalCardDelegate
# =============================================================================


class TestFileHorizontalCardDelegate:
    """FileHorizontalCardDelegate 构造与离屏渲染测试。"""

    def test_construct_defaults(self, stub_settings_manager: _StubSettingsManager) -> None:
        """默认构造应初始化字体属性。

        Args:
            stub_settings_manager: SettingsManager 替身。
        """
        delegate = FileHorizontalCardDelegate(
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
        """横向委托 paint() 到 QPixmap 应非空。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
        """
        model = _build_selector_model(
            [_normal_file_info("C:/tmp/delta.txt")],
            settings_manager=stub_settings_manager,
        )
        delegate = FileHorizontalCardDelegate(
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        pixmap = _paint_delegate_pixmap(delegate, model.index(0, 0), rect=QRect(0, 0, 320, 60))
        assert_pixmap_nonempty(pixmap)

    def test_paint_selected_and_hovered_no_crash(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
    ) -> None:
        """横向委托的选中/悬停状态渲染不应崩溃。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
        """
        model = _build_selector_model(
            [_normal_file_info("C:/tmp/echo.txt")],
            settings_manager=stub_settings_manager,
        )
        delegate = FileHorizontalCardDelegate(
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        index = model.index(0, 0)
        pixmap = _paint_delegate_pixmap(
            delegate,
            index,
            rect=QRect(0, 0, 320, 60),
            state=QStyle.State_Enabled | QStyle.State_MouseOver,
        )
        assert_pixmap_nonempty(pixmap)
        model.set_selected("C:/tmp/echo.txt", True)
        model.set_previewing("C:/tmp/echo.txt", True)
        pixmap = _paint_delegate_pixmap(delegate, index, rect=QRect(0, 0, 320, 60))
        assert_pixmap_nonempty(pixmap)

    def test_paint_missing_file_no_crash(
        self,
        qapp: QApplication,
        stub_settings_manager: _StubSettingsManager,
    ) -> None:
        """横向委托对缺失文件项渲染不应崩溃。

        Args:
            qapp: 会话级 QApplication。
            stub_settings_manager: SettingsManager 替身。
        """
        model = _build_selector_model(
            [_missing_file_info("C:/tmp/gone_bad.txt")],
            settings_manager=stub_settings_manager,
        )
        delegate = FileHorizontalCardDelegate(
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        pixmap = _paint_delegate_pixmap(delegate, model.index(0, 0), rect=QRect(0, 0, 320, 60))
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
            [_normal_file_info("C:/tmp/foxtrot.txt")],
            settings_manager=stub_settings_manager,
        )
        model.set_card_width(300, 56, 1)
        delegate = FileHorizontalCardDelegate(
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=stub_settings_manager,
        )
        option = QStyleOptionViewItem()
        hint = delegate.sizeHint(option, model.index(0, 0))
        assert hint.width() == 300
        assert hint.height() > 0
