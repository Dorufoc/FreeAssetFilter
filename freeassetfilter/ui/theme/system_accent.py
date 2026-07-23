"""Read the Windows system accent color from DWM or the registry."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Optional
import winreg


def _get_accent_color_from_dwm() -> Optional[str]:
    """Return the system accent color via DwmGetColorizationColor.

    The returned DWORD is in 0xAARRGGBB format. This function converts it to
    an uppercase ``#RRGGBB`` hex string.
    """
    try:
        dwmapi = ctypes.WinDLL("dwmapi")
        DwmGetColorizationColor = dwmapi.DwmGetColorizationColor
        DwmGetColorizationColor.argtypes = [
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.BOOL),
        ]
        DwmGetColorizationColor.restype = wintypes.HRESULT

        colorization = wintypes.DWORD()
        opaque_blend = wintypes.BOOL()
        hr = DwmGetColorizationColor(
            ctypes.byref(colorization), ctypes.byref(opaque_blend)
        )
        if hr < 0:
            return None

        c = colorization.value
        r = (c >> 16) & 0xFF
        g = (c >> 8) & 0xFF
        b = c & 0xFF
        return f"#{r:02X}{g:02X}{b:02X}"
    except Exception:
        return None


def _get_accent_color_from_registry() -> Optional[str]:
    """Fallback: read the accent color from the DWM registry key.

    ``HKCU\Software\Microsoft\Windows\DWM\ColorizationColor`` stores the
    color as a REG_DWORD in 0xAARRGGBB format.
    """
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\DWM",
            0,
            winreg.KEY_READ,
        ) as key:
            value, _ = winreg.QueryValueEx(key, "ColorizationColor")
            c = int(value)
            r = (c >> 16) & 0xFF
            g = (c >> 8) & 0xFF
            b = c & 0xFF
            return f"#{r:02X}{g:02X}{b:02X}"
    except Exception:
        return None


def get_system_accent_color(default: str = "#007AFF") -> str:
    """Return the current Windows personalization accent color as ``#RRGGBB``.

    Tries the official DWM API first, then falls back to the registry.
    If both fail, returns *default*.
    """
    color = _get_accent_color_from_dwm()
    if color is not None:
        return color
    color = _get_accent_color_from_registry()
    if color is not None:
        return color
    return default
