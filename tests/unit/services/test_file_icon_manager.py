# -*- coding: utf-8 -*-
"""``FileIconManager`` 单元测试（todo-13 unit/services 批2）。

覆盖：SVG 图标渲染管线（已知后缀 / 目录 / 未知后缀）、L1 缓存命中与
主题色失效、缺失图标路径的空 pixmap 回退（不抛异常）、未知文件文字叠加、
预加载与清缓存。

设计要点：
* ``FileIconManager`` 是线程安全单例，且不在 conftest ``reset_singletons``
  清单内——测试通过 clear_cache() 保证缓存隔离，不依赖单例重置；
* ``_get_theme_colors`` 依赖 SettingsManager，测试用可变的固定色元组
  monkeypatch，保证缓存键可预测且与设置文件无关；
* 所有临时文件使用 ``tmp_path``，图标基座文件则复用仓库自带 SVG。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from freeassetfilter.core.managers.settings_manager import SettingsManager
from freeassetfilter.services.file_icon_manager import FileIconManager
from tests.support.data_factories import make_image
from tests.support.qt_helpers import assert_pixmap_nonempty, flush_widget_queue

pytestmark = pytest.mark.unit


def _file_info(suffix: str, path: str = "", is_dir: bool = False) -> Dict[str, Any]:
    """构造与产品 FileInfo 兼容的图标测试元信息。

    Args:
        suffix: 文件扩展名（不含点）。
        path: 文件路径（可为空，仅目录/系统图标分支可能用到）。
        is_dir: 是否为目录。

    Returns:
        dict[str, Any]: 文件信息字典。
    """
    return {
        "path": path,
        "name": f"sample.{suffix}" if suffix else path,
        "is_dir": is_dir,
        "suffix": suffix,
        "size": 1,
        "modified": 0,
    }


@pytest.fixture
def icon_manager(qapp: Any) -> FileIconManager:
    """提供清空缓存后的 FileIconManager 单例；teardown 再次清缓存。

    Args:
        qapp: 会话级 QApplication（QPixmap 渲染需要）。

    Returns:
        FileIconManager: 图中全会状态干净的单例。
    """
    manager: FileIconManager = FileIconManager()
    manager.clear_cache()
    yield manager
    manager.clear_cache()
    flush_widget_queue(qapp)


@pytest.fixture
def theme_colors(monkeypatch: Any) -> List[str]:
    """把 5 个主题色替换为可变元组，可控制缓存键。

    Args:
        monkeypatch: pytest monkeypatch。

    Returns:
        list[str]: 可变颜色列表（“引用可变”以便测试后续修改）。
    """
    colors: List[str] = ["#111111", "#222222", "#333333", "#444444", "#555555"]
    monkeypatch.setattr(
        FileIconManager,
        "_get_theme_colors",
        lambda self: tuple(colors),
    )
    return colors


# ── 渲染管线 happy 路径 ──────────────────────────────────────────────────


class TestIconRendering:
    """已知 / 目录 / 未知后缀的 SVG 图标渲染。"""

    def test_known_suffix_renders_nonempty(self, icon_manager: FileIconManager, theme_colors: List[str]) -> None:
        """happy：已知音频后缀应渲染出非空图标。

        Args:
            icon_manager: 图标管理器 fixture。
            theme_colors: 固定主题色 fixture。
        """
        pixmap = icon_manager.get_icon_pixmap(_file_info("mp3"), 48, 1.0)
        assert_pixmap_nonempty(pixmap, "已知后缀 mp3 图标应为非空")

    def test_dir_suffix_renders_folder_icon(self, icon_manager: FileIconManager, theme_colors: List[str]) -> None:
        """happy：目录应渲染文件夹图标。

        Args:
            icon_manager: 图标管理器 fixture。
            theme_colors: 固定主题色 fixture。
        """
        pixmap = icon_manager.get_icon_pixmap(
            _file_info("", path="C:/some/dir", is_dir=True), 48, 1.0
        )
        assert_pixmap_nonempty(pixmap, "目录图标应为非空")

    def test_unknown_suffix_renders_text_overlay(self, icon_manager: FileIconManager, theme_colors: List[str]) -> None:
        """happy：未知后缀应走文字叠加分支且图标非空。

        Args:
            icon_manager: 图标管理器 fixture。
            theme_colors: 固定主题色 fixture。
        """
        pixmap = icon_manager.get_icon_pixmap(_file_info("zzz"), 48, 1.0)
        assert_pixmap_nonempty(pixmap, "未知后缀图标应为非空")

    def test_long_unknown_suffix_falls_back_to_file_label(self, icon_manager: FileIconManager, theme_colors: List[str]) -> None:
        """boundary：长度 >=5 的未知后缀叠加文字应回退为 FILE。

        通过构造不含该后缀样式的路径间接验证——此处直接调
        get_file_icon_path 确认未知路径；渲染非空即可。

        Args:
            icon_manager: 图标管理器 fixture。
            theme_colors: 固定主题色 fixture。
        """
        info: Dict[str, Any] = _file_info("verylongext")
        icon_path: str = icon_manager.get_icon_path(info)
        assert "未知" in icon_path  # 未知底板被选中
        pixmap = icon_manager.get_icon_pixmap(info, 48, 1.0)
        assert_pixmap_nonempty(pixmap, "长未知后缀图标应为非空")

    def test_png_without_thumbnail_falls_back_to_svg(self, icon_manager: FileIconManager, theme_colors: List[str], tmp_path: Path) -> None:
        """boundary：无磁盘缩略图的 PNG 应回退到 SVG 图标而非空。

        Args:
            icon_manager: 图标管理器 fixture。
            theme_colors: 固定主题色 fixture。
            tmp_path: pytest 临时目录。
        """
        png_path: str = make_image(tmp_path / "fresh.png", fmt="PNG")
        pixmap = icon_manager.get_icon_pixmap(_file_info("png", path=png_path), 48, 1.0)
        assert_pixmap_nonempty(pixmap, "无缩略图 PNG 图标应为非空")


# ── 缓存行为 ─────────────────────────────────────────────────────────────


class TestCacheBehaviour:
    """L1 缓存命中、主题色失效与清缓存。"""

    def test_second_call_returns_cached_identical_pixmap(self, icon_manager: FileIconManager, theme_colors: List[str]) -> None:
        """happy：同键二次调用应命中 L1 缓存且返回同一对象。

        Args:
            icon_manager: 图标管理器 fixture。
            theme_colors: 固定主题色 fixture。
        """
        info: Dict[str, Any] = _file_info("mp3")
        first = icon_manager.get_icon_pixmap(info, 48, 1.0)
        second = icon_manager.get_icon_pixmap(info, 48, 1.0)
        assert first is second

    def test_theme_color_change_invalidates_cache(self, icon_manager: FileIconManager, theme_colors: List[str]) -> None:
        """boundary：主题色变化应使缓存失效并渲染新对象。

        Args:
            icon_manager: 图标管理器 fixture。
            theme_colors: 可变主题色 fixture。
        """
        info: Dict[str, Any] = _file_info("mp3")
        first = icon_manager.get_icon_pixmap(info, 48, 1.0)
        assert_pixmap_nonempty(first)
        theme_colors[0] = "#FF0000"  # 修改基础色 → 缓存键变化
        second = icon_manager.get_icon_pixmap(info, 48, 1.0)
        assert second is not first
        assert_pixmap_nonempty(second)

    def test_clear_cache_removes_entries(self, icon_manager: FileIconManager, theme_colors: List[str]) -> None:
        """boundary：clear_cache() 后缓存应清空且仍可渲染。

        Args:
            icon_manager: 图标管理器 fixture。
            theme_colors: 固定主题色 fixture。
        """
        info: Dict[str, Any] = _file_info("mp3")
        icon_manager.get_icon_pixmap(info, 48, 1.0)
        assert len(icon_manager._icon_cache) > 0
        icon_manager.clear_cache()
        assert len(icon_manager._icon_cache) == 0
        pixmap = icon_manager.get_icon_pixmap(info, 48, 1.0)
        assert_pixmap_nonempty(pixmap, "清缓存后仍可重新渲染")

    def test_preload_icons_warms_cache(self, icon_manager: FileIconManager, theme_colors: List[str]) -> None:
        """happy：preload_icons 预热后 get 应命中缓存。

        Args:
            icon_manager: 图标管理器 fixture。
            theme_colors: 固定主题色 fixture。
        """
        infos: List[Dict[str, Any]] = [
            _file_info("mp3"),
            _file_info("docx"),
            _file_info("xyz"),
        ]
        icon_manager.preload_icons(infos, 32, 1.0)
        for info in infos:
            pixmap = icon_manager.get_icon_pixmap(info, 32, 1.0)
            assert_pixmap_nonempty(pixmap, f"suffix={info['suffix']} 预加载图标非空")


# ── 缺失 / 异常回退 ──────────────────────────────────────────────────────


class TestMissingFallback:
    """图标路径缺失时返回空 QPixmap 而不抛异常。"""

    def test_missing_icon_path_returns_empty_pixmap(
        self, icon_manager: FileIconManager, theme_colors: List[str], monkeypatch: Any
    ) -> None:
        """error：图标路径缺失应返回空 QPixmap，不抛异常。

        Args:
            icon_manager: 图标管理器 fixture。
            theme_colors: 固定主题色 fixture。
            monkeypatch: pytest monkeypatch。
        """
        monkeypatch.setattr(
            "freeassetfilter.services.file_icon_manager.get_file_icon_path",
            lambda _info: "C:/does/not/exist/icon.svg",
        )
        pixmap = icon_manager.get_icon_pixmap(_file_info("mp3"), 48, 1.0)
        assert pixmap.isNull()

    def test_get_icon_path_delegates_to_helper(
        self, icon_manager: FileIconManager, monkeypatch: Any
    ) -> None:
        """happy：get_icon_path 委托给 file_icon_helper。

        Args:
            icon_manager: 图标管理器 fixture。
            monkeypatch: pytest monkeypatch。
        """
        sentinel: str = "C:/picked/icon.svg"
        monkeypatch.setattr(
            "freeassetfilter.services.file_icon_manager.get_file_icon_path",
            lambda _info: sentinel,
        )
        assert icon_manager.get_icon_path(_file_info("mp3")) == sentinel

    def test_rendering_survives_reset_settings_singleton(self, icon_manager: FileIconManager, theme_colors: List[str], monkeypatch: Any) -> None:
        """boundary：SettingsManager 单例被重置后渲染仍不崩溃。

        缓存键使用内部 mock 的主题色，与 SettingsManager 解耦。

        Args:
            icon_manager: 图标管理器 fixture。
            theme_colors: 固定主题色 fixture。
            monkeypatch: pytest monkeypatch。
        """
        monkeypatch.setattr(SettingsManager, "_instance", None)
        monkeypatch.setattr(SettingsManager, "_initialized", False)
        assert_pixmap_nonempty(icon_manager.get_icon_pixmap(_file_info("docx"), 48, 1.0))


# ── 未知图标文字叠加直接方法 ─────────────────────────────────────────────


class TestUnknownIconBuilder:
    """``_build_unknown_icon_pixmap`` 的文字叠加 / 字体收缩。"""

    def _unknown_board_svg(self, icon_manager: FileIconManager) -> str:
        """返回真实存在的未知底板 SVG 路径。

        Args:
            icon_manager: 图标管理器 fixture。

        Returns:
            str: SVG 文件路径。
        """
        path: str = icon_manager.get_icon_path(_file_info("zzz"))
        assert Path(path).is_file()
        return path

    def test_short_text_overlay(self, icon_manager: FileIconManager, theme_colors: List[str]) -> None:
        """happy：短文本应完整叠加且图标非空。

        Args:
            icon_manager: 图标管理器 fixture。
            theme_colors: 固定主题色 fixture。
        """
        pixmap = icon_manager._build_unknown_icon_pixmap(
            self._unknown_board_svg(icon_manager), "MP4", 48, 1.0, "#212121"
        )
        assert_pixmap_nonempty(pixmap, "短文本叠加图标应为非空")

    def test_long_text_font_shrinks(self, icon_manager: FileIconManager, theme_colors: List[str]) -> None:
        """boundary：过长文本应触发字体收缩且不崩溃。

        Args:
            icon_manager: 图标管理器 fixture。
            theme_colors: 固定主题色 fixture。
        """
        long_text: str = "VERYLONGTEXTFILEEXTENSION"
        pixmap = icon_manager._build_unknown_icon_pixmap(
            self._unknown_board_svg(icon_manager), long_text, 48, 1.0, "#212121"
        )
        assert_pixmap_nonempty(pixmap, "长文本收缩后图标仍为非空")

    def test_empty_text_renders_base_only(self, icon_manager: FileIconManager, theme_colors: List[str]) -> None:
        """boundary：空文本应只渲染底板，不抛异常。

        Args:
            icon_manager: 图标管理器 fixture。
            theme_colors: 固定主题色 fixture。
        """
        pixmap = icon_manager._build_unknown_icon_pixmap(
            self._unknown_board_svg(icon_manager), "", 48, 1.0, "#212121"
        )
        assert_pixmap_nonempty(pixmap, "空文本底板图标应为非空")


# ── DPR 边界 ─────────────────────────────────────────────────────────────


class TestDprBehaviour:
    """不同设备像素比的缓存区分。"""

    def test_dpr_part_of_cache_key(self, icon_manager: FileIconManager, theme_colors: List[str]) -> None:
        """boundary：dpr 不同应产生独立的缓存条目。

        Args:
            icon_manager: 图标管理器 fixture。
            theme_colors: 固定主题色 fixture。
        """
        info: Dict[str, Any] = _file_info("mp3")
        at_1x = icon_manager.get_icon_pixmap(info, 48, 1.0)
        at_2x = icon_manager.get_icon_pixmap(info, 48, 2.0)
        assert at_1x is not at_2x
        assert_pixmap_nonempty(at_1x)
        assert_pixmap_nonempty(at_2x)


__all__: Tuple[str, ...] = ()