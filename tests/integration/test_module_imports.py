# -*- coding: utf-8 -*-
"""
模块导入集成测试
测试所有模块是否能正确导入，无循环导入
"""
import sys
import importlib

import pytest


# =============================================================================
# 全部模块清单（排除 __init__.py / __main__.py）
# =============================================================================

ALL_MODULES = [
    # -- app --
    "freeassetfilter.app.main",
    # -- components --
    "freeassetfilter.components.archive_browser",
    "freeassetfilter.components.file_info_previewer",
    "freeassetfilter.components.file_selector",
    "freeassetfilter.components.file_staging_pool",
    "freeassetfilter.components.folder_content_list",
    "freeassetfilter.components.font_previewer",
    "freeassetfilter.components.pdf_previewer",
    "freeassetfilter.components.photo_viewer",
    "freeassetfilter.components.settings_window",
    "freeassetfilter.components.text_previewer",
    "freeassetfilter.components.theme_editor",
    "freeassetfilter.components.unified_previewer",
    "freeassetfilter.components.update_controller",
    "freeassetfilter.components.video_player",
    # -- core --
    "freeassetfilter.core.color_extractor",
    "freeassetfilter.core.heartbeat_manager",
    "freeassetfilter.core.image_color_utils",
    "freeassetfilter.core.lut_preview_generator",
    "freeassetfilter.core.media_probe",
    "freeassetfilter.core.mpv_manager",
    "freeassetfilter.core.mpv_player_core",
    "freeassetfilter.core.py7z_core",
    "freeassetfilter.core.native.bridges.rust_thumbnail_bridge",
    "freeassetfilter.core.settings_manager",
    "freeassetfilter.core.svg_renderer",
    "freeassetfilter.core.theme_manager",
    "freeassetfilter.core.thumbnail_manager",
    "freeassetfilter.core.update_manager",
    # -- core / native --
    "freeassetfilter.core.native.rust_color_extractor",
    # -- core/native/src / cpp_color_extractor --
    "freeassetfilter.core.native.src.cpp_color_extractor.setup",
    # -- core/native/src / cpp_lut_preview --
    "freeassetfilter.core.native.src.cpp_lut_preview",
    "freeassetfilter.core.native.src.cpp_lut_preview.setup",
    "freeassetfilter.core.native.src.cpp_lut_preview.setup_mingw",
    # -- core / workers --
    "freeassetfilter.core.workers.drive_list_loader",
    "freeassetfilter.core.workers.file_list_loader",
    "freeassetfilter.core.workers.staging_tasks",
    # -- services --
    "freeassetfilter.services.base",
    "freeassetfilter.services.drive_service",
    "freeassetfilter.services.favorites_repository",
    "freeassetfilter.services.favorites_service",
    "freeassetfilter.services.file_service",
    "freeassetfilter.services.media_metadata_service",
    "freeassetfilter.services.previewer_registry",
    "freeassetfilter.services.settings_repository",
    "freeassetfilter.services.staging_pool_service",
    # -- utils --
    "freeassetfilter.utils.animation_settings",
    "freeassetfilter.utils.app_logger",
    "freeassetfilter.utils.async_icon_loader",
    "freeassetfilter.utils.file_icon_helper",
    "freeassetfilter.utils.global_mouse_monitor",
    "freeassetfilter.utils.icon_utils",
    "freeassetfilter.utils.lut_utils",
    "freeassetfilter.utils.path_utils",
    "freeassetfilter.utils.perf_metrics",
    "freeassetfilter.utils.subprocess_utils",
    "freeassetfilter.utils.syntax_highlighter",
    # -- widgets --
    "freeassetfilter.widgets.D_hover_menu",
    "freeassetfilter.widgets.D_more_menu",
    "freeassetfilter.widgets.D_volume",
    "freeassetfilter.widgets.D_volume_control",
    "freeassetfilter.widgets.D_widgets",
    "freeassetfilter.widgets.audio_background",
    "freeassetfilter.widgets.base_card_delegate",
    "freeassetfilter.widgets.button_widgets",
    "freeassetfilter.widgets.color_slider",
    "freeassetfilter.widgets.color_wheel_picker",
    "freeassetfilter.widgets.combo_selector",
    "freeassetfilter.widgets.control_menu",
    "freeassetfilter.widgets.custom_scrollbar",
    "freeassetfilter.widgets.dropdown_menu",
    "freeassetfilter.widgets.file_block_card",
    "freeassetfilter.widgets.file_horizontal_card",
    "freeassetfilter.widgets.file_horizontal_card_delegate",
    "freeassetfilter.widgets.file_selector_delegate",
    "freeassetfilter.widgets.file_selector_model",
    "freeassetfilter.widgets.file_staging_pool_delegate",
    "freeassetfilter.widgets.file_staging_pool_model",
    "freeassetfilter.widgets.hover_tooltip",
    "freeassetfilter.widgets.input_widgets",
    "freeassetfilter.widgets.list_widgets",
    "freeassetfilter.widgets.loading_widget",
    "freeassetfilter.widgets.lut_manager_dialog",
    "freeassetfilter.widgets.message_box",
    "freeassetfilter.widgets.player_control_bar",
    "freeassetfilter.widgets.progress_widgets",
    "freeassetfilter.widgets.setting_widgets",
    "freeassetfilter.widgets.smooth_scroller",
    "freeassetfilter.widgets.switch_widgets",
    "freeassetfilter.widgets.theme_card",
]

# 已知可能无法导入的模块（缺少原生依赖 / 构建脚本等）
_FRAGILE_MODULES = {
    # 原生依赖缺失：需要 rust_color_extractor_native.dll
    "freeassetfilter.core.native.rust_color_extractor",
    # 构建脚本：模块顶层调用 setup() 会解析 sys.argv 导致失败
    "freeassetfilter.core.native.src.cpp_color_extractor.setup",
    "freeassetfilter.core.native.src.cpp_lut_preview.setup",
    "freeassetfilter.core.native.src.cpp_lut_preview.setup_mingw",
}


def _is_fragile(module_name: str) -> bool:
    """判断模块是否可能因缺少原生依赖或属于构建脚本而无法导入"""
    return module_name in _FRAGILE_MODULES


# =============================================================================
# 保留原有测试（确保向后兼容）
# =============================================================================


class TestCoreModulesImport:
    """测试核心模块导入"""

    def test_import_settings_manager(self):
        """测试导入设置管理器"""
        from freeassetfilter.core.settings_manager import SettingsManager
        assert SettingsManager is not None

    def test_import_theme_manager(self):
        """测试导入主题管理器"""
        from freeassetfilter.core.theme_manager import ThemeManager
        assert ThemeManager is not None

    def test_import_thumbnail_manager(self):
        """测试导入缩略图管理器"""
        from freeassetfilter.core.thumbnail_manager import ThumbnailManager
        assert ThumbnailManager is not None

    def test_import_app_logger(self):
        """测试导入日志模块"""
        from freeassetfilter.utils.app_logger import get_logger, info, debug
        assert get_logger is not None
        assert info is not None
        assert debug is not None

    def test_import_path_utils(self):
        """测试导入路径工具"""
        from freeassetfilter.utils.path_utils import (
            get_resource_path, get_app_data_path, get_config_path
        )
        assert get_resource_path is not None
        assert get_app_data_path is not None
        assert get_config_path is not None


class TestComponentsImport:
    """测试组件模块导入"""

    def test_import_file_selector(self):
        """测试导入文件选择器"""
        from freeassetfilter.components.file_selector import CustomFileSelector
        assert CustomFileSelector is not None

    def test_import_unified_previewer(self):
        """测试导入统一预览器"""
        from freeassetfilter.components.unified_previewer import UnifiedPreviewer
        assert UnifiedPreviewer is not None

    def test_import_file_staging_pool(self):
        """测试导入文件存储池"""
        from freeassetfilter.components.file_staging_pool import FileStagingPool
        assert FileStagingPool is not None


class TestWidgetsImport:
    """测试控件模块导入"""

    def test_import_d_widgets(self):
        """测试导入 D_widgets"""
        from freeassetfilter.widgets.D_widgets import CustomWindow, CustomButton
        assert CustomWindow is not None
        assert CustomButton is not None

    def test_import_file_cards(self):
        """测试导入文件卡片"""
        from freeassetfilter.widgets.file_block_card import FileBlockCard
        from freeassetfilter.widgets.file_horizontal_card import CustomFileHorizontalCard
        assert FileBlockCard is not None
        assert CustomFileHorizontalCard is not None


class TestMainAppImport:
    """测试主应用程序导入"""

    def test_import_main_app(self):
        """测试导入主应用程序"""
        from freeassetfilter.app.main import FreeAssetFilterApp, main
        assert FreeAssetFilterApp is not None
        assert main is not None


# =============================================================================
# 全面参数化模块导入测试
# =============================================================================


def _build_module_params():
    """构建 pytest 参数化参数，为脆弱模块添加 xfail 标记"""
    params = []
    for mod_name in ALL_MODULES:
        if _is_fragile(mod_name):
            params.append(pytest.param(
                mod_name,
                marks=pytest.mark.xfail(
                    reason=f"缺少原生依赖: {mod_name}",
                    strict=False,
                ),
            ))
        else:
            params.append(pytest.param(mod_name))
    return params


class TestAllModulesImport:
    """全覆盖模块导入测试（~90 个模块）"""

    @pytest.mark.parametrize("module_name", _build_module_params())
    def test_individual_module_import(self, module_name: str):
        """逐个验证每个模块可被导入"""
        mod = importlib.import_module(module_name)
        assert mod is not None, f"模块 {module_name} 导入后为 None"

    def test_package_init_imports(self):
        """验证所有 __init__.py 包可被导入（隐式测试）"""
        packages = [
            "freeassetfilter",
            "freeassetfilter.app",
            "freeassetfilter.components",
            "freeassetfilter.core",
            "freeassetfilter.core.workers",
            "freeassetfilter.services",
            "freeassetfilter.utils",
            "freeassetfilter.widgets",
            "freeassetfilter.libs",
            "freeassetfilter.icons",
            "freeassetfilter.core.native.src.cpp_lut_preview",
        ]
        for pkg in packages:
            mod = importlib.import_module(pkg)
            assert mod is not None, f"包 {pkg} 导入后为 None"


class TestNoCircularImports:
    """测试没有循环导入"""

    @staticmethod
    def _clear_freeassetfilter_modules() -> None:
        """清除所有已导入的 freeassetfilter 模块"""
        keys = [k for k in sys.modules if k.startswith("freeassetfilter")]
        for k in keys:
            del sys.modules[k]

    def test_no_circular_imports_in_core(self):
        """测试核心模块没有循环导入"""
        self._clear_freeassetfilter_modules()
        try:
            from freeassetfilter.core import settings_manager
            from freeassetfilter.core import theme_manager
            from freeassetfilter.core import thumbnail_manager
            from freeassetfilter.utils import app_logger
            from freeassetfilter.utils import path_utils
            assert True
        except ImportError as e:
            pytest.fail(f"Circular import detected: {e}")

    def test_no_circular_imports_in_components(self):
        """测试组件模块没有循环导入"""
        self._clear_freeassetfilter_modules()
        try:
            from freeassetfilter.components import file_selector
            from freeassetfilter.components import unified_previewer
            from freeassetfilter.components import file_staging_pool
            assert True
        except ImportError as e:
            pytest.fail(f"Circular import detected: {e}")

    def test_no_circular_imports_all_modules(self):
        """
        在干净环境中批量导入所有非脆弱模块，验证无循环导入。
        脆弱模块（缺少原生依赖）被排除在外，避免误报。
        """
        self._clear_freeassetfilter_modules()
        errors: list[str] = []
        for mod_name in ALL_MODULES:
            if _is_fragile(mod_name):
                continue
            try:
                importlib.import_module(mod_name)
            except ImportError as e:
                errors.append(f"{mod_name}: {e}")
        if errors:
            pytest.fail(
                f"以下模块存在导入问题（可能是循环导入）：\n"
                + "\n".join(errors)
            )
