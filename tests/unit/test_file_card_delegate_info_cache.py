"""行数据缓存失效回归测试。

背景：缩略图到位时模型只发 ``dataChanged(..., [IconPixmapRole])``。若失效槽
跟着 sizeHint 一起只认 ``CardWidthRole`` 就提前返回，行数据缓存会一直返回
占位图标 —— 表现为「缩略图已生成，但可视行不更新，滚动/重新导航才刷新」。
"""

from __future__ import annotations

from sopeek.ui.components.file_card_delegate import (
    CardWidthRole,
    FileCardDelegate,
    IconPixmapRole,
)


def _seed(delegate: FileCardDelegate) -> None:
    """塞入两种缓存条目，模拟已经画过一行。"""
    delegate._info_cache[0] = {"name": "a.txt", "icon_pixmap": None}
    delegate._size_hint_cache[(delegate._layout_mode, delegate._card_scale, 0)] = 1


def test_icon_role_change_invalidates_row_info_cache(qapp) -> None:
    """缩略图角色变化必须清掉行数据缓存（sizeHint 缓存可保留）。"""
    delegate = FileCardDelegate()
    _seed(delegate)

    delegate._on_model_data_changed(None, None, [IconPixmapRole])

    assert delegate._info_cache == {}
    assert len(delegate._size_hint_cache) == 1


def test_card_width_role_change_invalidates_both_caches(qapp) -> None:
    """卡片宽度变化同时影响 sizeHint 与行数据缓存。"""
    delegate = FileCardDelegate()
    _seed(delegate)

    delegate._on_model_data_changed(None, None, [CardWidthRole])

    assert delegate._info_cache == {}
    assert delegate._size_hint_cache == {}


def test_unfiltered_data_change_invalidates_both_caches(qapp) -> None:
    """未指定角色（None）视为全部变化。"""
    delegate = FileCardDelegate()
    _seed(delegate)

    delegate._on_model_data_changed()

    assert delegate._info_cache == {}
    assert delegate._size_hint_cache == {}


def test_structure_change_invalidates_both_caches(qapp) -> None:
    """结构变化（复位/增删行）同样要清空两种缓存。"""
    delegate = FileCardDelegate()
    _seed(delegate)

    delegate._on_model_structure_changed()

    assert delegate._info_cache == {}
    assert delegate._size_hint_cache == {}
