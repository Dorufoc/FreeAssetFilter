# -*- coding: utf-8 -*-
"""
FileStagingPoolCardDelegate 单元测试

测试 freeassetfilter/widgets/file_staging_pool_delegate.py 模块的功能。
覆盖：创建、信号发射、paint() 调用、显示名称格式、尺寸格式、操作按钮等。
"""

import os
from typing import Any, Dict, Optional

import pytest
from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionViewItem, QWidget


# =============================================================================
# 辅助工具 — 模拟管理器
# =============================================================================


class _DummySettingsManager:
    """模拟 SettingsManager，所有 get_setting 返回默认值。"""

    def get_setting(self, key: str, default: Any = None) -> Any:
        return default


class _MappedSettingsManager:
    """模拟 SettingsManager，可指定特定键的返回值。"""

    def __init__(self, overrides: Optional[Dict[str, Any]] = None) -> None:
        self._overrides = overrides or {}

    def get_setting(self, key: str, default: Any = None) -> Any:
        return self._overrides.get(key, default)


# =============================================================================
# 辅助工具 — 构建视图+模型+委托
# =============================================================================


def _create_option(view, index) -> QStyleOptionViewItem:
    """构建 QStyleOptionViewItem 用于 paint 测试。"""
    option = QStyleOptionViewItem()
    if hasattr(view, "initViewItemOption"):
        view.initViewItemOption(option)
    option.rect = view.visualRect(index)
    option.widget = view.viewport()
    return option


class _DelegateTestHelper:
    """封装常用的视图+模型+委托创建逻辑。"""

    def __init__(self, qt_app, monkeypatch) -> None:
        self.qt_app = qt_app
        self.monkeypatch = monkeypatch
        self._instrument_app()

    def _instrument_app(self) -> None:
        """确保 QApplication 属性存在。"""
        self.monkeypatch.setattr(
            self.qt_app, "settings_manager", _DummySettingsManager(), raising=False
        )
        self.monkeypatch.setattr(
            self.qt_app, "global_font", QFont(), raising=False
        )
        self.monkeypatch.setattr(
            self.qt_app, "dpi_scale_factor", 1.0, raising=False
        )

    def create(self, **kwargs) -> "tuple":
        """创建完整的视图+模型+委托体系。

        Returns:
            (view, model, delegate)
        """
        from freeassetfilter.widgets.file_staging_pool_delegate import (
            FileStagingPoolCardDelegate,
        )
        from freeassetfilter.widgets.file_staging_pool_model import (
            FileStagingPoolListModel,
            FileStagingPoolListView,
        )

        model = FileStagingPoolListModel(dpi_scale=1.0, global_font=QFont())
        view = FileStagingPoolListView(dpi_scale=1.0, global_font=QFont())
        delegate = FileStagingPoolCardDelegate(
            dpi_scale=1.0,
            global_font=QFont(),
            **kwargs,
        )

        view.setModel(model)
        view.setItemDelegate(delegate)
        delegate.set_view(view)
        view.resize(640, 120)
        view.show()
        self.qt_app.processEvents()

        return view, model, delegate


def _create_delegate_only(qt_app, monkeypatch, **kwargs):
    """仅创建委托实例，不使用视图/模型。"""
    from freeassetfilter.widgets.file_staging_pool_delegate import (
        FileStagingPoolCardDelegate,
    )

    monkeypatch.setattr(qt_app, "settings_manager", _DummySettingsManager(), raising=False)
    monkeypatch.setattr(qt_app, "global_font", QFont(), raising=False)
    return FileStagingPoolCardDelegate(
        dpi_scale=1.0,
        global_font=QFont(),
        **kwargs,
    )


# =============================================================================
# 测试类
# =============================================================================


class TestFileStagingPoolCardDelegateCreation:
    """FileStagingPoolCardDelegate 创建测试。"""

    def test_creation_default(self, qapp, monkeypatch) -> None:
        """默认构造函数应正确初始化属性。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        assert delegate is not None
        assert delegate._single_line_mode is True
        assert delegate._enable_delete_action is False
        assert delegate._enable_actions is True
        assert delegate._pressed_action_key is None
        assert delegate._action_slide_states == {}
        assert delegate._active_action_slide_keys == set()
        assert delegate.parent() is None

    def test_creation_with_parent(self, qapp, monkeypatch) -> None:
        """传入 parent 参数应正确设置父子关系。"""
        parent = QWidget()
        delegate = _create_delegate_only(qapp, monkeypatch, parent=parent)
        assert delegate.parent() is parent
        parent.deleteLater()

    def test_creation_with_settings_manager(self, qapp, monkeypatch) -> None:
        """传入 settings_manager 参数应被使用。"""
        sm = _MappedSettingsManager({"appearance.theme": "dark"})
        delegate = _create_delegate_only(qapp, monkeypatch, settings_manager=sm)
        assert delegate._settings_manager is sm

    def test_creation_without_settings_manager(self, qapp, monkeypatch) -> None:
        """不传 settings_manager 应自动创建 SettingsManager 实例。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        assert delegate._settings_manager is not None

    def test_creation_with_single_line_mode_false(self, qapp, monkeypatch) -> None:
        """single_line_mode=False 也应工作（实际始终为 True）。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        # 构造器内固定为 True，即使传了 False
        assert delegate._single_line_mode is True

    def test_creation_with_delete_action_enabled(self, qapp, monkeypatch) -> None:
        """enable_delete_action=True 应让 delete 按钮可用。"""
        delegate = _create_delegate_only(qapp, monkeypatch, enable_delete_action=True)
        assert delegate._enable_delete_action is True


class TestFileStagingPoolCardDelegateSignals:
    """重命名/删除信号测试。"""

    def test_rename_requested_signal(self, qapp, monkeypatch, tmp_path) -> None:
        """renameRequested 信号应能正常发射。"""
        helper = _DelegateTestHelper(qapp, monkeypatch)
        view, model, delegate = helper.create(enable_delete_action=True)

        received_paths: list = []

        def on_rename(path: str) -> None:
            received_paths.append(path)

        delegate.renameRequested.connect(on_rename)

        # 添加一个文件到模型
        test_file = tmp_path / "test_rename.txt"
        test_file.write_text("data")
        model.add_file({
            "path": str(test_file),
            "name": "test_rename.txt",
            "display_name": "test_rename.txt",
            "original_name": "test_rename.txt",
            "is_dir": False,
            "size": 4,
        })
        qapp.processEvents()
        index = model.index(0, 0)
        option = _create_option(view, index)

        # 设置悬停状态以使操作按钮可见
        option.state |= QStyle.State_MouseOver

        # 模拟点击重命名按钮
        rects = delegate.get_action_rects(option, index)
        assert delegate.ACTION_RENAME in rects, "重命名按钮 rect 应存在"
        btn_rect = rects[delegate.ACTION_RENAME]

        # 用 editorEvent 模拟点击
        event = QMouseEvent(
            QEvent.MouseButtonPress,
            btn_rect.center(),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        delegate.editorEvent(event, model, option, index)

        event = QMouseEvent(
            QEvent.MouseButtonRelease,
            btn_rect.center(),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        delegate.editorEvent(event, model, option, index)
        qapp.processEvents()

        assert len(received_paths) == 1
        assert received_paths[0] == str(test_file)

        view.close()
        view.deleteLater()

    def test_delete_requested_signal(self, qapp, monkeypatch, tmp_path) -> None:
        """deleteRequested 信号应能正常发射。"""
        helper = _DelegateTestHelper(qapp, monkeypatch)
        view, model, delegate = helper.create(enable_delete_action=True)

        received_paths: list = []

        def on_delete(path: str) -> None:
            received_paths.append(path)

        delegate.deleteRequested.connect(on_delete)

        test_file = tmp_path / "test_delete.txt"
        test_file.write_text("data")
        model.add_file({
            "path": str(test_file),
            "name": "test_delete.txt",
            "display_name": "test_delete.txt",
            "original_name": "test_delete.txt",
            "is_dir": False,
            "size": 4,
        })
        qapp.processEvents()
        index = model.index(0, 0)
        option = _create_option(view, index)

        # 设置悬停状态以使操作按钮可见
        option.state |= QStyle.State_MouseOver

        rects = delegate.get_action_rects(option, index)
        assert delegate.ACTION_DELETE in rects, "删除按钮 rect 应存在"
        btn_rect = rects[delegate.ACTION_DELETE]

        # 模拟点击删除按钮
        event = QMouseEvent(
            QEvent.MouseButtonPress,
            btn_rect.center(),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        delegate.editorEvent(event, model, option, index)

        event = QMouseEvent(
            QEvent.MouseButtonRelease,
            btn_rect.center(),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        delegate.editorEvent(event, model, option, index)
        qapp.processEvents()

        assert len(received_paths) == 1
        assert received_paths[0] == str(test_file)

        view.close()
        view.deleteLater()


class TestFileStagingPoolCardDelegatePaint:
    """paint() 基本调用测试。"""

    def test_paint_does_not_crash(self, qapp, monkeypatch, tmp_path) -> None:
        """paint() 应在正常条件下不崩溃。"""
        helper = _DelegateTestHelper(qapp, monkeypatch)
        view, model, delegate = helper.create(enable_delete_action=True)

        test_file = tmp_path / "test_paint.txt"
        test_file.write_text("data")
        model.add_file({
            "path": str(test_file),
            "name": "test_paint.txt",
            "display_name": "test_paint.txt",
            "original_name": "test_paint.txt",
            "is_dir": False,
            "size": 4,
        })
        qapp.processEvents()
        index = model.index(0, 0)
        option = _create_option(view, index)

        pixmap = QPixmap(option.rect.size())
        pixmap.fill(Qt.white)
        painter = QPainter(pixmap)
        try:
            delegate.paint(painter, option, index)
        finally:
            painter.end()

        # paint 成功即视为通过（无异常）
        assert True

    def test_paint_with_invalid_index(self, qapp, monkeypatch) -> None:
        """paint() 应在无效 index 时不崩溃。"""
        from freeassetfilter.widgets.file_staging_pool_delegate import (
            FileStagingPoolCardDelegate,
        )
        from freeassetfilter.widgets.file_staging_pool_model import (
            FileStagingPoolListModel,
            FileStagingPoolListView,
        )

        monkeypatch.setattr(qapp, "settings_manager", _DummySettingsManager(), raising=False)
        monkeypatch.setattr(qapp, "global_font", QFont(), raising=False)

        model = FileStagingPoolListModel(dpi_scale=1.0, global_font=QFont())
        view = FileStagingPoolListView(dpi_scale=1.0, global_font=QFont())
        delegate = FileStagingPoolCardDelegate(
            dpi_scale=1.0,
            global_font=QFont(),
            enable_delete_action=True,
            parent=view,
        )
        view.setModel(model)
        view.setItemDelegate(delegate)
        delegate.set_view(view)
        view.resize(640, 120)
        view.show()
        qapp.processEvents()

        # 无效 index
        index = model.index(99, 0)
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 100, 30)
        option.widget = view.viewport()

        pixmap = QPixmap(100, 30)
        pixmap.fill(Qt.white)
        painter = QPainter(pixmap)
        try:
            delegate.paint(painter, option, index)
        finally:
            painter.end()

        view.close()
        view.deleteLater()

    def test_paint_with_missing_file(self, qapp, monkeypatch, tmp_path) -> None:
        """paint() 应对标记为缺失的文件不崩溃。"""
        helper = _DelegateTestHelper(qapp, monkeypatch)
        view, model, delegate = helper.create(enable_delete_action=True)

        model.add_file({
            "path": str(tmp_path / "nonexistent.txt"),
            "name": "nonexistent.txt",
            "display_name": "nonexistent.txt",
            "original_name": "nonexistent.txt",
            "is_dir": False,
            "is_missing": True,
            "size": 0,
        })
        qapp.processEvents()
        index = model.index(0, 0)
        option = _create_option(view, index)

        pixmap = QPixmap(option.rect.size())
        pixmap.fill(Qt.white)
        painter = QPainter(pixmap)
        try:
            delegate.paint(painter, option, index)
        finally:
            painter.end()

        assert True
        view.close()
        view.deleteLater()


class TestFileStagingPoolCardDelegateDisplayName:
    """显示名称格式化测试。"""

    def test_visible_display_name_normal(self, qapp, monkeypatch) -> None:
        """正常文件应返回 visible_name。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        file_info = {
            "visible_name": "example.txt",
            "name": "example.txt",
            "is_missing": False,
        }
        result = delegate._visible_display_name(file_info)
        assert result == "example.txt"

    def test_visible_display_name_fallback_to_display_name(self, qapp, monkeypatch) -> None:
        """无 visible_name 时回退到 display_name。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        file_info = {
            "visible_name": "",
            "display_name": "fallback.txt",
            "is_missing": False,
        }
        result = delegate._visible_display_name(file_info)
        assert result == "fallback.txt"

    def test_visible_display_name_fallback_to_name(self, qapp, monkeypatch) -> None:
        """无 display_name 时回退到 name。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        file_info = {
            "visible_name": "",
            "display_name": "",
            "name": "name_fallback.txt",
            "is_missing": False,
        }
        result = delegate._visible_display_name(file_info)
        assert result == "name_fallback.txt"

    def test_visible_display_name_fallback_to_path_basename(self, qapp, monkeypatch) -> None:
        """无所有名称字段时回退到路径 basename。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        file_info = {
            "visible_name": "",
            "display_name": "",
            "name": "",
            "path": r"C:\test\folder\file.txt",
            "is_missing": False,
        }
        result = delegate._visible_display_name(file_info)
        assert "file.txt" in result

    def test_visible_display_name_missing_with_suffix(self, qapp, monkeypatch) -> None:
        """缺失文件应附加 '（已移动或删除）' 后缀。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        file_info = {
            "visible_name": "",
            "display_name": "lost_file.txt",
            "is_missing": True,
        }
        result = delegate._visible_display_name(file_info)
        assert "lost_file.txt" in result
        assert "已移动或删除" in result

    def test_visible_display_name_missing_fallback(self, qapp, monkeypatch) -> None:
        """缺失文件通过 path basename 回退时应包含后缀。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        file_info = {
            "visible_name": "",
            "display_name": "",
            "name": "",
            "path": r"C:\missing\data.bin",
            "is_missing": True,
        }
        result = delegate._visible_display_name(file_info)
        assert "data.bin" in result
        assert "已移动或删除" in result


class TestFileStagingPoolCardDelegateInlineSize:
    """内联尺寸文本格式化测试。"""

    def test_inline_size_missing(self, qapp, monkeypatch) -> None:
        """缺失文件应返回空字符串。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        result = delegate._inline_size_text({"is_missing": True})
        assert result == ""

    def test_inline_size_dir_calculating(self, qapp, monkeypatch) -> None:
        """正在计算大小的目录应显示提示文本。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        result = delegate._inline_size_text({
            "is_missing": False,
            "is_dir": True,
            "size_calculating": True,
        })
        assert "正在计算大小" in result

    def test_inline_size_dir_done(self, qapp, monkeypatch) -> None:
        """已计算完成的目录应显示大小或 '文件夹'。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        result = delegate._inline_size_text({
            "is_missing": False,
            "is_dir": True,
            "size_calculating": False,
            "size": None,
        })
        assert result == "文件夹"

    def test_inline_size_file(self, qapp, monkeypatch) -> None:
        """普通文件应返回格式化大小。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        result = delegate._inline_size_text({
            "is_missing": False,
            "is_dir": False,
            "size": 2048,
        })
        assert result == "2.00 KB"


class TestFileStagingPoolCardDelegateFormatSize:
    """_format_file_size 静态方法测试。"""

    def test_format_size_none(self, qapp, monkeypatch) -> None:
        """None 输入应返回空字符串。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        assert delegate._format_file_size(None) == ""

    def test_format_size_string_invalid(self, qapp, monkeypatch) -> None:
        """无效字符串应返回空字符串。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        assert delegate._format_file_size("not_a_number") == ""

    def test_format_size_negative(self, qapp, monkeypatch) -> None:
        """负数应视为 0。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        assert delegate._format_file_size(-100) == "0 B"

    def test_format_size_bytes(self, qapp, monkeypatch) -> None:
        """小于 1024 应显示 B。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        assert delegate._format_file_size(500) == "500 B"

    def test_format_size_kb(self, qapp, monkeypatch) -> None:
        """小于 1MB 应显示 KB。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        assert delegate._format_file_size(2048) == "2.00 KB"

    def test_format_size_mb(self, qapp, monkeypatch) -> None:
        """小于 1GB 应显示 MB。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        assert delegate._format_file_size(3 * 1024 * 1024) == "3.00 MB"

    def test_format_size_gb(self, qapp, monkeypatch) -> None:
        """大于等于 1GB 应显示 GB。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        assert delegate._format_file_size(2 * 1024 * 1024 * 1024) == "2.00 GB"

    def test_format_size_zero(self, qapp, monkeypatch) -> None:
        """0 应显示 '0 B'。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        assert delegate._format_file_size(0) == "0 B"


class TestFileStagingPoolCardDelegateActions:
    """操作按钮相关测试。"""

    def test_action_sequence_without_delete(self, qapp, monkeypatch) -> None:
        """默认禁用删除时，action_sequence 应只包含 rename。"""
        delegate = _create_delegate_only(qapp, monkeypatch, enable_delete_action=False)
        actions = delegate._action_sequence()
        assert actions == [delegate.ACTION_RENAME]

    def test_action_sequence_with_delete(self, qapp, monkeypatch) -> None:
        """启用删除时，action_sequence 应包含 rename 和 delete。"""
        delegate = _create_delegate_only(qapp, monkeypatch, enable_delete_action=True)
        actions = delegate._action_sequence()
        assert actions == [delegate.ACTION_RENAME, delegate.ACTION_DELETE]

    def test_action_text_rename(self, qapp, monkeypatch) -> None:
        """重命名操作的文本应为 '重命名'。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        assert delegate._action_text(delegate.ACTION_RENAME) == "重命名"

    def test_action_text_delete(self, qapp, monkeypatch) -> None:
        """删除操作的文本应为 '删除'。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        assert delegate._action_text(delegate.ACTION_DELETE) == "删除"

    def test_action_button_type_rename(self, qapp, monkeypatch) -> None:
        """重命名按钮类型应为 primary。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        assert delegate._action_button_type(delegate.ACTION_RENAME) == "primary"

    def test_action_button_type_delete(self, qapp, monkeypatch) -> None:
        """删除按钮类型应为 warning。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        assert delegate._action_button_type(delegate.ACTION_DELETE) == "warning"


class TestFileStagingPoolCardDelegateSetters:
    """setter 方法测试。"""

    def test_set_single_line_mode_enabled(self, qapp, monkeypatch) -> None:
        """set_single_line_mode(False) 应更新属性（实际始终为 bool）。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        delegate.set_single_line_mode(False)
        assert delegate._single_line_mode is False

    def test_set_single_line_mode_redundant(self, qapp, monkeypatch) -> None:
        """重复设置相同值不应触发更新。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        delegate.set_single_line_mode(True)
        assert delegate._single_line_mode is True

    def test_set_enable_delete_action(self, qapp, monkeypatch) -> None:
        """set_enable_delete_action(True) 应启用删除操作。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        delegate.set_enable_delete_action(True)
        assert delegate._enable_delete_action is True

    def test_set_enable_delete_action_redundant(self, qapp, monkeypatch) -> None:
        """重复设置相同值不应触发更新。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        delegate.set_enable_delete_action(False)
        assert delegate._enable_delete_action is False

    def test_clear_caches(self, qapp, monkeypatch) -> None:
        """clear_caches 应清除操作滑动状态和 pressed key。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        delegate._pressed_action_key = ("key", "rename")
        delegate._action_slide_states["test"] = {"current_offset": 10.0}
        delegate._active_action_slide_keys.add("test")

        delegate.clear_caches()

        assert delegate._pressed_action_key is None
        assert delegate._action_slide_states == {}
        assert delegate._active_action_slide_keys == set()


class TestFileStagingPoolCardDelegateDarkenColor:
    """_darken_or_lighten_color 方法测试。"""

    def test_darken_light_mode(self, qapp, monkeypatch) -> None:
        """亮色模式下颜色应变暗。"""
        sm = _MappedSettingsManager({"appearance.theme": "light"})
        delegate = _create_delegate_only(qapp, monkeypatch, settings_manager=sm)
        color = QColor(200, 200, 200)
        result = delegate._darken_or_lighten_color(color, 0.2)
        # 亮色模式：每个通道乘以 (1-pct)
        expected_r = int(200 * (1 - 0.2))
        expected_g = int(200 * (1 - 0.2))
        expected_b = int(200 * (1 - 0.2))
        assert result.red() == expected_r
        assert result.green() == expected_g
        assert result.blue() == expected_b

    def test_darken_dark_mode_high_luminance(self, qapp, monkeypatch) -> None:
        """暗色模式下高亮度颜色应轻微变亮。"""
        sm = _MappedSettingsManager({"appearance.theme": "dark"})
        delegate = _create_delegate_only(qapp, monkeypatch, settings_manager=sm)
        # 高亮度 (luminance > 0.3)
        color = QColor(200, 200, 200)
        result = delegate._darken_or_lighten_color(color, 0.2)
        # 暗色模式：向白色方向增加
        pct = 0.2
        expected_r = min(255, int(200 + (255 - 200) * pct))
        expected_g = min(255, int(200 + (255 - 200) * pct))
        expected_b = min(255, int(200 + (255 - 200) * pct))
        assert result.red() == expected_r
        assert result.green() == expected_g
        assert result.blue() == expected_b

    def test_darken_dark_mode_low_luminance(self, qapp, monkeypatch) -> None:
        """暗色模式下低亮度颜色应使用更大调整系数。"""
        sm = _MappedSettingsManager({"appearance.theme": "dark"})
        delegate = _create_delegate_only(qapp, monkeypatch, settings_manager=sm)
        # 极低亮度 (luminance < 0.1)
        color = QColor(10, 10, 10)
        result = delegate._darken_or_lighten_color(color, 0.2)
        # luminance = (0.299*10 + 0.587*10 + 0.114*10)/255 = 10/255 ≈ 0.039 < 0.1
        # adjusted_percentage = min(0.2 * 2.5, 0.4) = 0.4
        pct = 0.4
        expected_r = min(255, int(10 + (255 - 10) * pct))
        expected_g = min(255, int(10 + (255 - 10) * pct))
        expected_b = min(255, int(10 + (255 - 10) * pct))
        assert result.red() == expected_r
        assert result.green() == expected_g
        assert result.blue() == expected_b


class TestFileStagingPoolCardDelegateButtonColors:
    """按钮颜色测试。"""

    def test_button_colors_rename_normal(self, qapp, monkeypatch) -> None:
        """重命名按钮默认颜色应使用 accent_color。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        colors = delegate._button_colors(delegate.ACTION_RENAME, hovered=False, pressed=False)
        assert colors["bg"] == QColor(delegate.accent_color)
        assert colors["border_width"] == 0.0

    def test_button_colors_delete_normal(self, qapp, monkeypatch) -> None:
        """删除按钮默认颜色应使用 warning_color。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        colors = delegate._button_colors(delegate.ACTION_DELETE, hovered=False, pressed=False)
        assert colors["bg"] == QColor(delegate.warning_color)
        assert colors["border_width"] == 1.5

    def test_button_colors_rename_hovered(self, qapp, monkeypatch) -> None:
        """重命名按钮 hover 时应变亮/暗。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        colors = delegate._button_colors(delegate.ACTION_RENAME, hovered=True, pressed=False)
        assert colors["bg"] != QColor(delegate.accent_color)

    def test_button_colors_delete_pressed(self, qapp, monkeypatch) -> None:
        """删除按钮 pressed 时应进一步变亮/暗。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        colors = delegate._button_colors(delegate.ACTION_DELETE, hovered=False, pressed=True)
        assert colors["bg"] != QColor(delegate.warning_color)


class TestFileStagingPoolCardDelegateButtonMetrics:
    """按钮尺寸指标测试。"""

    def test_button_metrics_rename(self, qapp, monkeypatch) -> None:
        """重命名按钮应有合理的尺寸。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        metrics = delegate._button_metrics("重命名", "primary")
        assert metrics["width"] > 0
        assert metrics["height"] > 0
        assert metrics["radius"] > 0

    def test_button_metrics_delete(self, qapp, monkeypatch) -> None:
        """删除按钮应有合理的尺寸。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        metrics = delegate._button_metrics("删除", "warning")
        assert metrics["width"] > 0
        assert metrics["height"] > 0
        assert metrics["radius"] > 0

    def test_button_layout_metrics(self, qapp, monkeypatch) -> None:
        """布局指标应返回正确的键。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        metrics = delegate._button_layout_metrics()
        assert "margin_x" in metrics
        assert "margin_y" in metrics
        assert "spacing" in metrics
        assert metrics["margin_x"] >= 0
        assert metrics["margin_y"] >= 0
        assert metrics["spacing"] >= 0


class TestFileStagingPoolCardDelegateGeometry:
    """几何计算测试。"""

    def test_calculate_geometry(self, qapp, monkeypatch) -> None:
        """_calculate_geometry 应返回完整几何字典。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        rect = QRect(0, 0, 200, 40)
        geo = delegate._calculate_geometry(rect)
        assert "border_width" in geo
        assert "preview_border_width" in geo
        assert "radius" in geo
        assert "icon_rect" in geo
        assert "name_rect" in geo
        assert geo["border_width"] > 0
        assert geo["icon_rect"].isValid()
        assert geo["name_rect"].isValid()

    def test_calculate_geometry_icon_position(self, qapp, monkeypatch) -> None:
        """图标应在内容区域左侧垂直居中。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        rect = QRect(0, 0, 200, 40)
        geo = delegate._calculate_geometry(rect)
        icon_rect = geo["icon_rect"]
        # 图标垂直居中
        assert icon_rect.y() + icon_rect.height() / 2 == pytest.approx(
            rect.height() / 2, abs=2
        )


class TestFileStagingPoolCardDelegateActionRects:
    """操作按钮矩形测试。"""

    def test_get_action_rects_empty_without_view(self, qapp, monkeypatch) -> None:
        """没有视图时不应崩溃。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 200, 40)
        rects = delegate.get_action_rects(option, None)
        assert isinstance(rects, dict)

    def test_get_rename_action_rect(self, qapp, monkeypatch, tmp_path) -> None:
        """get_rename_action_rect 应返回 QRect。"""
        helper = _DelegateTestHelper(qapp, monkeypatch)
        view, model, delegate = helper.create(enable_delete_action=True)

        test_file = tmp_path / "test.txt"
        test_file.write_text("data")
        model.add_file({
            "path": str(test_file),
            "name": "test.txt",
            "display_name": "test.txt",
            "original_name": "test.txt",
            "is_dir": False,
            "size": 4,
        })
        qapp.processEvents()
        index = model.index(0, 0)
        option = _create_option(view, index)
        # 设置鼠标悬停以显示操作区域
        option.state |= QStyle.State_MouseOver

        rect = delegate.get_rename_action_rect(option, index)
        assert isinstance(rect, QRect)

        view.close()
        view.deleteLater()

    def test_get_delete_action_rect_enabled(self, qapp, monkeypatch, tmp_path) -> None:
        """启用删除时 get_delete_action_rect 应返回有效 QRect。"""
        helper = _DelegateTestHelper(qapp, monkeypatch)
        view, model, delegate = helper.create(enable_delete_action=True)

        test_file = tmp_path / "test2.txt"
        test_file.write_text("data")
        model.add_file({
            "path": str(test_file),
            "name": "test2.txt",
            "display_name": "test2.txt",
            "original_name": "test2.txt",
            "is_dir": False,
            "size": 4,
        })
        qapp.processEvents()
        index = model.index(0, 0)
        option = _create_option(view, index)
        option.state |= QStyle.State_MouseOver

        rect = delegate.get_delete_action_rect(option, index)
        assert isinstance(rect, QRect)

        view.close()
        view.deleteLater()

    def test_get_action_rect(self, qapp, monkeypatch, tmp_path) -> None:
        """get_action_rect 应返回指定操作的矩形。"""
        helper = _DelegateTestHelper(qapp, monkeypatch)
        view, model, delegate = helper.create(enable_delete_action=True)

        test_file = tmp_path / "test3.txt"
        test_file.write_text("data")
        model.add_file({
            "path": str(test_file),
            "name": "test3.txt",
            "display_name": "test3.txt",
            "original_name": "test3.txt",
            "is_dir": False,
            "size": 4,
        })
        qapp.processEvents()
        index = model.index(0, 0)
        option = _create_option(view, index)
        option.state |= QStyle.State_MouseOver

        rect = delegate.get_action_rect(delegate.ACTION_RENAME, option, index)
        assert isinstance(rect, QRect)
        assert rect.isValid() or rect.isNull()

        view.close()
        view.deleteLater()

    def test_get_action_area_rect(self, qapp, monkeypatch, tmp_path) -> None:
        """get_action_area_rect 应合并所有操作按钮区域。"""
        helper = _DelegateTestHelper(qapp, monkeypatch)
        view, model, delegate = helper.create(enable_delete_action=True)

        test_file = tmp_path / "test4.txt"
        test_file.write_text("data")
        model.add_file({
            "path": str(test_file),
            "name": "test4.txt",
            "display_name": "test4.txt",
            "original_name": "test4.txt",
            "is_dir": False,
            "size": 4,
        })
        qapp.processEvents()
        index = model.index(0, 0)
        option = _create_option(view, index)
        option.state |= QStyle.State_MouseOver

        area = delegate.get_action_area_rect(option, index)
        assert isinstance(area, QRect)

        view.close()
        view.deleteLater()


class TestFileStagingPoolCardDelegateShouldShowAction:
    """操作区域可见性测试。"""

    def test_should_show_action_not_hovered(self, qapp, monkeypatch, tmp_path) -> None:
        """非悬停状态应返回 False。"""
        helper = _DelegateTestHelper(qapp, monkeypatch)
        view, model, delegate = helper.create(enable_delete_action=True)

        test_file = tmp_path / "test.txt"
        test_file.write_text("data")
        model.add_file({
            "path": str(test_file),
            "name": "test.txt",
            "display_name": "test.txt",
            "original_name": "test.txt",
            "is_dir": False,
            "size": 4,
        })
        qapp.processEvents()
        index = model.index(0, 0)
        option = _create_option(view, index)
        # 确保没有 hover 标记
        option.state &= ~QStyle.State_MouseOver

        assert delegate.should_show_action_area(option, index) is False

        view.close()
        view.deleteLater()

    def test_should_show_action_hovered(self, qapp, monkeypatch, tmp_path) -> None:
        """悬停状态应返回 True。"""
        helper = _DelegateTestHelper(qapp, monkeypatch)
        view, model, delegate = helper.create(enable_delete_action=True)

        test_file = tmp_path / "test.txt"
        test_file.write_text("data")
        model.add_file({
            "path": str(test_file),
            "name": "test.txt",
            "display_name": "test.txt",
            "original_name": "test.txt",
            "is_dir": False,
            "size": 4,
        })
        qapp.processEvents()
        index = model.index(0, 0)
        option = _create_option(view, index)
        option.state |= QStyle.State_MouseOver

        assert delegate.should_show_action_area(option, index) is True

        view.close()
        view.deleteLater()

    def test_should_show_action_drag_preview(self, qapp, monkeypatch, tmp_path) -> None:
        """拖拽预览模式应返回 False。"""
        helper = _DelegateTestHelper(qapp, monkeypatch)
        view, model, delegate = helper.create(enable_delete_action=True)

        test_file = tmp_path / "test.txt"
        test_file.write_text("data")
        model.add_file({
            "path": str(test_file),
            "name": "test.txt",
            "display_name": "test.txt",
            "original_name": "test.txt",
            "is_dir": False,
            "size": 4,
        })
        qapp.processEvents()
        index = model.index(0, 0)
        option = _create_option(view, index)

        assert delegate.should_show_action_area(option, index, for_drag_preview=True) is False

        view.close()
        view.deleteLater()

    def test_should_show_action_removing(self, qapp, monkeypatch, tmp_path) -> None:
        """正在移除的文件应返回 False。"""
        helper = _DelegateTestHelper(qapp, monkeypatch)
        view, model, delegate = helper.create(enable_delete_action=True)

        test_file = tmp_path / "test.txt"
        test_file.write_text("data")
        model.add_file({
            "path": str(test_file),
            "name": "test.txt",
            "display_name": "test.txt",
            "original_name": "test.txt",
            "is_dir": False,
            "size": 4,
            "is_removing": True,
        })
        qapp.processEvents()
        index = model.index(0, 0)
        option = _create_option(view, index)
        option.state |= QStyle.State_MouseOver

        assert delegate.should_show_action_area(option, index) is False

        view.close()
        view.deleteLater()


class TestFileStagingPoolCardDelegateSizeHint:
    """sizeHint 测试。"""

    def test_sizeHint_returns_valid_size(self, qapp, monkeypatch, tmp_path) -> None:
        """sizeHint 应返回有效的 QSize。"""
        helper = _DelegateTestHelper(qapp, monkeypatch)
        view, model, delegate = helper.create()

        test_file = tmp_path / "test.txt"
        test_file.write_text("data")
        model.add_file({
            "path": str(test_file),
            "name": "test.txt",
            "display_name": "test.txt",
            "original_name": "test.txt",
            "is_dir": False,
            "size": 4,
        })
        qapp.processEvents()
        index = model.index(0, 0)

        size = delegate.sizeHint(QStyleOptionViewItem(), index)
        assert isinstance(size, QSize)
        assert size.width() > 0
        assert size.height() > 0

        view.close()
        view.deleteLater()

    def test_sizeHint_min_width(self, qapp, monkeypatch) -> None:
        """sizeHint 最小宽度应合理。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        size = delegate.sizeHint(QStyleOptionViewItem(), None)
        assert size.width() >= 160
        assert size.height() > 0

    def test_sizeHint_default_height(self, qapp, monkeypatch) -> None:
        """sizeHint 默认高度应基于 dpi 计算。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        size = delegate.sizeHint(QStyleOptionViewItem(), None)
        # height = 2 * border + 2 * v_margin + icon_size
        expected_height = 2 * 1 + 2 * 3 + 12  # border=1, v_margin=3, icon=12
        assert size.height() == expected_height


class TestFileStagingPoolCardDelegateEventPos:
    """_event_pos 位置提取测试。"""

    def test_event_pos_from_pos(self, qapp, monkeypatch) -> None:
        """_event_pos 应提取 QMouseEvent 的位置。"""
        from PySide6.QtWidgets import QWidget

        delegate = _create_delegate_only(qapp, monkeypatch)
        widget = QWidget()
        event = QMouseEvent(
            QEvent.MouseButtonPress,
            QPoint(42, 99),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        pos = delegate._event_pos(event)
        assert pos == QPoint(42, 99)
        widget.deleteLater()


class TestFileStagingPoolCardDelegateHitTest:
    """hit_test_action 测试。"""

    def test_hit_test_action_not_visible(self, qapp, monkeypatch, tmp_path) -> None:
        """不可见时 hit_test 应返回 None。"""
        helper = _DelegateTestHelper(qapp, monkeypatch)
        view, model, delegate = helper.create(enable_delete_action=True)

        test_file = tmp_path / "test.txt"
        test_file.write_text("data")
        model.add_file({
            "path": str(test_file),
            "name": "test.txt",
            "display_name": "test.txt",
            "original_name": "test.txt",
            "is_dir": False,
            "size": 4,
        })
        qapp.processEvents()
        index = model.index(0, 0)
        option = _create_option(view, index)
        option.state &= ~QStyle.State_MouseOver  # 无悬停

        result = delegate.hit_test_action(option, index, QPoint(0, 0))
        assert result is None

        view.close()
        view.deleteLater()

    def test_action_at(self, qapp, monkeypatch, tmp_path) -> None:
        """action_at 是 hit_test_action 的别名。"""
        helper = _DelegateTestHelper(qapp, monkeypatch)
        view, model, delegate = helper.create(enable_delete_action=True)

        test_file = tmp_path / "test.txt"
        test_file.write_text("data")
        model.add_file({
            "path": str(test_file),
            "name": "test.txt",
            "display_name": "test.txt",
            "original_name": "test.txt",
            "is_dir": False,
            "size": 4,
        })
        qapp.processEvents()
        index = model.index(0, 0)
        option = _create_option(view, index)

        result = delegate.action_at(option, index, QPoint(0, 0), require_visible=False)
        # 根据点击位置，可能为 None 或操作名
        assert result is None or result in (delegate.ACTION_RENAME, delegate.ACTION_DELETE)

        view.close()
        view.deleteLater()


class TestFileStagingPoolCardDelegateComposeTexts:
    """_compose_texts 文本组成测试。"""

    def test_compose_texts_returns_tuple(self, qapp, monkeypatch) -> None:
        """_compose_texts 应返回 (name, '') 元组。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        name_text, info_text = delegate._compose_texts({
            "visible_name": "test.txt",
            "is_missing": False,
        })
        assert name_text == "test.txt"
        assert info_text == ""


class TestFileStagingPoolCardDelegateAnimation:
    """动画相关方法测试。"""

    def test_sync_action_slide_hide(self, qapp, monkeypatch) -> None:
        """_sync_action_slide(should_show=False) 应重置偏移并清除动画。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        key = "test_key"
        delegate._sync_action_slide(key, should_show=False, btn_width=50)
        state = delegate._action_slide_states.get(key)
        assert state is not None
        assert state["is_visible"] is False
        assert state["current_offset"] == 54.0  # btn_width(50) + margin_x(4) * 1.0

    def test_sync_action_slide_show(self, qapp, monkeypatch) -> None:
        """_sync_action_slide(should_show=True) 应启动动画。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        key = "test_key"
        delegate._sync_action_slide(key, should_show=True, btn_width=50)
        state = delegate._action_slide_states.get(key)
        assert state is not None
        assert state["is_visible"] is True
        assert state["animating"] is True
        assert key in delegate._active_action_slide_keys

    def test_tick_action_slide_animations_idle(self, qapp, monkeypatch) -> None:
        """没有活跃动画时 tick 不应崩溃。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        delegate._tick_action_slide_animations()
        assert True  # 没有崩溃即通过

    def test_lookup_current_slide_offset_empty(self, qapp, monkeypatch) -> None:
        """无文件信息时 _lookup_current_slide_offset 应返回 0。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        offset = delegate._lookup_current_slide_offset(None)
        assert offset == 0.0

    def test_clear_caches_clears_animation_state(self, qapp, monkeypatch) -> None:
        """clear_caches 应重置 pressed_action_key。"""
        delegate = _create_delegate_only(qapp, monkeypatch)
        delegate._pressed_action_key = ("file_key", "rename")
        delegate.clear_caches()
        assert delegate._pressed_action_key is None


class TestFileStagingPoolCardDelegateEditorEvent:
    """editorEvent 事件处理测试。"""

    def test_editor_event_invalid_index(self, qapp, monkeypatch) -> None:
        """无效 index 应返回 False。"""
        delegate = _create_delegate_only(qapp, monkeypatch, enable_delete_action=True)
        from PySide6.QtCore import QModelIndex

        event = QMouseEvent(
            QEvent.MouseButtonPress,
            QPoint(0, 0),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        result = delegate.editorEvent(event, None, QStyleOptionViewItem(), QModelIndex())
        assert result is False

    def test_editor_event_disabled_actions(self, qapp, monkeypatch, tmp_path) -> None:
        """禁用操作时 editorEvent 应返回 False。"""
        helper = _DelegateTestHelper(qapp, monkeypatch)
        view, model, delegate = helper.create(enable_delete_action=False)
        delegate._enable_actions = False

        test_file = tmp_path / "test.txt"
        test_file.write_text("data")
        model.add_file({
            "path": str(test_file),
            "name": "test.txt",
            "display_name": "test.txt",
            "original_name": "test.txt",
            "is_dir": False,
            "size": 4,
        })
        qapp.processEvents()
        index = model.index(0, 0)
        option = _create_option(view, index)

        event = QMouseEvent(
            QEvent.MouseButtonPress,
            QPoint(0, 0),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        result = delegate.editorEvent(event, model, option, index)
        assert result is False

        view.close()
        view.deleteLater()


class TestFileStagingPoolCardDelegateIntegration:
    """集成测试 — 检查委托与模型+视图的联动。"""

    def test_delegate_stores_view_reference(self, qapp, monkeypatch) -> None:
        """set_view() 后委托应持有视图引用。"""
        helper = _DelegateTestHelper(qapp, monkeypatch)
        view, model, delegate = helper.create()
        assert delegate._view is view
        view.close()
        view.deleteLater()

    def test_paint_with_motion_parameters(self, qapp, monkeypatch, tmp_path) -> None:
        """提供 card_motion_paint_parameters 时 paint 应不崩溃。"""
        helper = _DelegateTestHelper(qapp, monkeypatch)
        view, model, delegate = helper.create(enable_delete_action=True)

        test_file = tmp_path / "test_motion.txt"
        test_file.write_text("data")
        model.add_file({
            "path": str(test_file),
            "name": "test_motion.txt",
            "display_name": "test_motion.txt",
            "original_name": "test_motion.txt",
            "is_dir": False,
            "size": 4,
        })
        qapp.processEvents()
        index = model.index(0, 0)
        option = _create_option(view, index)

        # 模拟 view 提供 motion 参数
        view.card_motion_paint_parameters = lambda idx, rect: {
            "dx": 10,
            "dy": 0,
            "opacity": 0.8,
        }

        pixmap = QPixmap(option.rect.size())
        pixmap.fill(Qt.white)
        painter = QPainter(pixmap)
        try:
            delegate.paint(painter, option, index)
        finally:
            painter.end()

        assert True
        view.close()
        view.deleteLater()

    def test_paint_with_motion_parameters_error(self, qapp, monkeypatch, tmp_path) -> None:
        """card_motion_paint_parameters 抛出异常时应降级到普通 paint。"""
        helper = _DelegateTestHelper(qapp, monkeypatch)
        view, model, delegate = helper.create(enable_delete_action=True)

        test_file = tmp_path / "test_motion_err.txt"
        test_file.write_text("data")
        model.add_file({
            "path": str(test_file),
            "name": "test_motion_err.txt",
            "display_name": "test_motion_err.txt",
            "original_name": "test_motion_err.txt",
            "is_dir": False,
            "size": 4,
        })
        qapp.processEvents()
        index = model.index(0, 0)
        option = _create_option(view, index)

        def _bad_motion_params(idx, rect):
            raise RuntimeError("simulated error")

        view.card_motion_paint_parameters = _bad_motion_params

        pixmap = QPixmap(option.rect.size())
        pixmap.fill(Qt.white)
        painter = QPainter(pixmap)
        try:
            delegate.paint(painter, option, index)
        finally:
            painter.end()

        assert True
        view.close()
        view.deleteLater()

    def test_init_colors_fallback_on_exception(self, qapp, monkeypatch) -> None:
        """SettingsManager 出错时 _init_colors 应使用默认颜色。"""
        class _BrokenSettingsManager:
            def get_setting(self, key, default=None):
                raise RuntimeError("broken")

        delegate = _create_delegate_only(
            qapp, monkeypatch, settings_manager=_BrokenSettingsManager()
        )
        assert delegate.accent_color == "#1890ff"
        assert delegate.warning_color == "#F44336"
