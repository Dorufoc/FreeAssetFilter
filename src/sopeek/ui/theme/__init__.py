"""
Theme package for D-fronted PySide6 components.
Provides centralized color token management via ThemeManager singleton.

Usage:
    from theme import tm

    # New property-based API (preferred)
    bg = tm.surface          # QColor("#1a1a1a")
    accent = tm.accent       # QColor("#07c160")
    hover = tm.accent_hover  # 90% HSV brightness
    danger = tm.danger       # QColor("#ef4444")
    muted = tm.alpha_of(tm.text, 60)  # text at 60% opacity

    # Legacy API (during migration)
    color = tm.get_color("button.primary.bg")
    qss = tm.render_qss()
"""

from .theme_manager import get_theme_manager

# Singleton convenience instance
tm = get_theme_manager()

# 短路径别名（如 styled_button.py: ``from theme import tm``）由
# ``sopeek._import_compat`` 的导入重定向 finder 统一收敛，
# 两个名称永远指向同一模块对象；本文件不再自行注入 sys.modules。
# 若本模块先以短名独立加载、finder 尚未安装，后续规范路径导入同样
# 经 finder 反向复用本模块，无需在此重复处理。
