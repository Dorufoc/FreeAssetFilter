#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 工具模块

提供各种实用工具函数和类
"""

from .path_utils import get_app_data_path, get_config_path, get_resource_path
from .icon_utils import get_lnk_target, get_all_icons_from_exe, get_highest_resolution_icon
from .fix_encoding import fix_file, fix_all_files
from .mouse_activity_monitor import MouseActivityMonitor

__all__ = [
    'get_app_data_path',
    'get_config_path', 
    'get_resource_path',
    'get_lnk_target',
    'get_all_icons_from_exe',
    'get_highest_resolution_icon',
    'fix_file',
    'fix_all_files',
    'MouseActivityMonitor'
]
