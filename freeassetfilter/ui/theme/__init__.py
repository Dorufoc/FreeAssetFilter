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

import sys as _sys
from .theme_manager import ThemeManager, get_theme_manager

# Singleton convenience instance
tm = get_theme_manager()

# Register 'theme' module alias for code using short-path import
# (e.g. styled_button.py: from theme import tm)
# Ensures both import paths resolve to the same ThemeManager instance.
if 'theme' not in _sys.modules:
    _sys.modules['theme'] = _sys.modules['freeassetfilter.ui.theme']
