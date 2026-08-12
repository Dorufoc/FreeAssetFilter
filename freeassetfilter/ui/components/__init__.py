"""D-Fronted Qt6 Components Library.

A complete set of UI components matching the web design system.

聚合导出已惰性化：原先 eager 导入 50+ 组件会拉入 QtSvg / QFontDatabase /
PIL 等重依赖，拖慢应用首屏。现在通过包级 ``__getattr__`` 首次访问时
按需导入，``from components.styled_x import Y`` 子模块导入不受影响。
"""

from __future__ import annotations

import importlib
import sys
import types

# 旧式聚合符号 → 所属子模块（惰性解析用）。子模块名按 `from .X import Y`
# 的原始声明一一对应，保证 ``from components import Y`` 与
# ``from components.X import Y`` 解析到同一对象。
_SYMBOL_TO_MODULE: dict[str, str] = {
    "StyledButton": "styled_button",
    "StyledLineEdit": "styled_lineedit",
    "InputWrapper": "styled_lineedit",
    "StyledToggle": "styled_toggle",
    "StyledCheckbox": "styled_checkbox",
    "StyledRadio": "styled_radio",
    "StyledScrollArea": "styled_scroll_area",
    "StyledScrollBar": "styled_scroll_area",
    "StyledSlider": "styled_slider",
    "SliderTrack": "styled_slider",
    "StyledComboBox": "styled_combobox",
    "StyledProgress": "styled_progress",
    "ProgressTrack": "styled_progress",
    "StyledProgressCircle": "styled_progress_circle",
    "CircleWidget": "styled_progress_circle",
    "SettingsCard": "settings_card",
    "SettingsRow": "settings_card",
    "NotificationRow": "settings_card",
    "PluginItem": "settings_card",
    "StyledSidebar": "styled_sidebar",
    "SidebarItem": "styled_sidebar",
    "StyledDatePicker": "styled_date_picker",
    "MicaMaterial": "mica_material",
    "MicaWidget": "mica_material",
    "MicaWindow": "mica_window",
    "DEFAULT_MICA_CONFIG": "mica_window",
    "StyledTag": "styled_tag",
    "StyledDialog": "styled_dialog",
    "DialogIconCircle": "styled_dialog",
    "create_basic_dialog": "styled_dialog",
    "create_success_dialog": "styled_dialog",
    "create_danger_dialog": "styled_dialog",
    "create_info_dialog": "styled_dialog",
    "create_input_dialog": "styled_dialog",
    "create_small_dialog": "styled_dialog",
    "create_large_dialog": "styled_dialog",
    "create_progress_linear_dialog": "styled_dialog",
    "create_progress_circular_dialog": "styled_dialog",
    "create_progress_download_dialog": "styled_dialog",
    "create_center_button_dialog": "styled_dialog",
    "create_left_button_dialog": "styled_dialog",
    "create_stacked_button_dialog": "styled_dialog",
    "create_three_button_dialog": "styled_dialog",
    "create_help_link_dialog": "styled_dialog",
    "create_no_border_dialog": "styled_dialog",
    "create_no_footer_dialog": "styled_dialog",
    "StyledAccordion": "styled_accordion",
    "StyledAccordionItem": "styled_accordion",
    "StyledAvatar": "styled_avatar",
    "StyledBadge": "styled_badge",
    "StyledBreadcrumb": "styled_breadcrumb",
    "StyledDivider": "styled_divider",
    "StyledCascader": "styled_cascader",
    "StyledColorPicker": "styled_color_picker",
    "StyledContextMenu": "styled_context_menu",
    "StyledFilePicker": "styled_file_picker",
    "StyledNumberInput": "styled_number_input",
    "StyledTabWidget": "styled_tabs",
    "StyledSegmented": "styled_segmented",
    "StyledTextarea": "styled_textarea",
    "StyledTooltip": "styled_tooltip",
    "StyledDrawer": "styled_drawer",
    "StyledCarousel": "styled_carousel",
    "NotificationBadgeList": "styled_notification_badge",
    "NotificationItem": "styled_notification_badge",
    "StyledPagination": "styled_pagination",
    "StyledSteps": "styled_steps",
    "StyledTable": "styled_table",
    "StyledTimeline": "styled_timeline",
    "StyledInfoCard": "styled_info_card",
    "StyledMusicInfoPanel": "styled_music_info_panel",
    "StyledFluidBackground": "styled_fluid_background",
    "StyledPlayerBar": "styled_player_bar",
    "FileListModel": "file_list_model",
    "FileCardDelegate": "file_card_delegate",
    "AnimatedFileListView": "animated_file_list_view",
}

__all__ = [
    "StyledButton",
    "StyledLineEdit",
    "InputWrapper",
    "StyledToggle",
    "StyledCheckbox",
    "StyledRadio",
    "StyledScrollArea",
    "StyledScrollBar",
    "StyledSlider",
    "SliderTrack",
    "StyledComboBox",
    "StyledProgress",
    "ProgressTrack",
    "StyledProgressCircle",
    "CircleWidget",
    "SettingsCard",
    "SettingsRow",
    "NotificationRow",
    "PluginItem",
    "StyledSidebar",
    "SidebarItem",
    "StyledDatePicker",
    "MicaMaterial",
    "MicaWidget",
    "MicaWindow",
    "DEFAULT_MICA_CONFIG",
    "StyledTag",
    "StyledDialog",
    "DialogIconCircle",
    "create_basic_dialog",
    "create_success_dialog",
    "create_danger_dialog",
    "create_info_dialog",
    "create_input_dialog",
    "create_small_dialog",
    "create_large_dialog",
    "create_progress_linear_dialog",
    "create_progress_circular_dialog",
    "create_progress_download_dialog",
    "create_center_button_dialog",
    "create_left_button_dialog",
    "create_stacked_button_dialog",
    "create_three_button_dialog",
    "create_help_link_dialog",
    "create_no_border_dialog",
    "create_no_footer_dialog",
    "StyledAccordion",
    "StyledAccordionItem",
    "StyledAvatar",
    "StyledBadge",
    "StyledBreadcrumb",
    "StyledDivider",
    "StyledCascader",
    "StyledColorPicker",
    "StyledContextMenu",
    "StyledFilePicker",
    "StyledNumberInput",
    "StyledTabWidget",
    "StyledSegmented",
    "StyledTextarea",
    "StyledTooltip",
    "StyledDrawer",
    "StyledCarousel",
    "NotificationBadgeList",
    "NotificationItem",
    "StyledPagination",
    "StyledSteps",
    "StyledTable",
    "StyledTimeline",
    "StyledInfoCard",
    "StyledMusicInfoPanel",
    "StyledFluidBackground",
    "StyledPlayerBar",
    "FileListModel",
    "FileCardDelegate",
    "AnimatedFileListView",
]


def __getattr__(name: str) -> types.ModuleType | object:
    """惰性向后兼容导出。

    Supports both old import patterns:

    * ``from components import styled_button`` → returns the sub-module.
    * ``from components import StyledButton`` → returns the class directly.
    """
    # 1) Sub-module name (lowercase, real file) → import it directly.
    try:
        module = importlib.import_module(f"{__name__}.{name}")
    except ModuleNotFoundError as exc:
        # 仅当确实找不到该子模块本身时才继续；子模块内部依赖缺失
        # 属于真实错误，向上抛出以免被误吞。
        if exc.name != f"{__name__}.{name}":
            raise
    else:
        sys.modules[f"{__name__}.{name}"] = module
        return module

    # 2) Symbol name → import owning module and extract the attribute.
    module_name = _SYMBOL_TO_MODULE.get(name)
    if module_name is not None:
        module = importlib.import_module(f"{__name__}.{module_name}")
        return getattr(module, name)

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """List available backward-compatible names."""
    return sorted(set(__all__) | set(_SYMBOL_TO_MODULE.keys()))
