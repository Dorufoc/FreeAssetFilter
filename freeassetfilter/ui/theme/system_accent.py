"""读取 Windows 系统强调色（Accent Color），供「主题色 → 自动」使用。

数据源优先级（自高到低）：

1. ``HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Accent\\
   AccentColorMenu``：Windows 设置里选择的强调色本体，REG_DWORD，
   格式 ``0xAABBGGRR``（ABGR，低字节是 R）；
2. ``HKCU\\Software\\Microsoft\\Windows\\DWM\\AccentColor``：DWM 记录的
   同义值，同为 ABGR；
3. ``HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Accent\\
   StartColorMenu``：开始菜单使用的同源派生色（通常更暗），仅在主值
   缺失时兜底；
4. ``HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Accent\\
   AccentPalette``：Windows 依据强调色生成的 7 档同源色阶（REG_BINARY，
   每条 4 字节 R,G,B,A；**第 8 条在 Windows 10/11 上恒为固定哨兵**
   ``88 17 98 00``，必须忽略）。仅在主色缺失或不可辨识时用于取可用档位。
5. ``DwmGetColorizationColor``：DWM 合成色（ARGB，混合了透明/标题栏
   设置，只是近似值）；
6. ``HKCU\\Software\\Microsoft\\Windows\\DWM\\ColorizationColor``：与 5
   等价的注册表缓存。

注意：``ColorizationColor`` **不是**强调色。未开启「在标题栏/任务栏
显示强调色」（``ColorPrevalence=0``）时它会是黑色（Windows 11 实测
``0xC4000000``），因此只能作为最后兜底，绝不能当作主数据源。

优雅降级：

- 非 Windows / ``winreg`` 缺失 / 注册表键不存在 / API 调用失败 /
  值为 0 / 格式非法 → 跳过该数据源；
- 强调色必须在深色（``#1A1A1A``）与浅色（``#F5F5F5``）两种应用底板上
  都具备最小可辨识对比度；近黑/近白（如纯黑强调色）会被判为不可用，
  此时优先取 Windows 同源色阶中**带色相**的可用一档（保住用户色调），
  灰阶色阶（纯黑/纯白强调色生成的全灰序列）仍不可用则回退
  ``default``（默认 ``#007AFF``）。

本模块不做进程级缓存：每次调用都重新读取注册表，保证应用每次实际
启动（以及设置页预览/提交）拿到的是当时最新的系统强调色。
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import List, Optional, Tuple

try:  # pragma: no cover - 非 Windows 平台无 winreg；项目仅支持 Windows，属防御性守卫
    import winreg
except ImportError:
    winreg = None  # type: ignore[assignment]


# ── 注册表路径与常量 ────────────────────────────────────────────────
_ACCENT_SUBKEY: str = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Accent"
_DWM_SUBKEY: str = r"Software\Microsoft\Windows\DWM"

#: 兜底强调色（与 PRESET_ACCENT_COLORS 的「活力蓝」一致）。
_DEFAULT_ACCENT: str = "#007AFF"

#: AccentPalette 中真实色阶的条目数：8 条中的最后一条恒为固定哨兵。
_PALETTE_SHADE_COUNT: int = 7

#: 应用两套底板的相对亮度（深色 gray.g1 / 浅色 gray_light.g1）。
_DARK_SURFACE_LUMINANCE: float = 0.0086  # #1A1A1A
_LIGHT_SURFACE_LUMINANCE: float = 0.9131  # #F5F5F5

#: 强调色对两种底板的最小可辨识对比度（仅排除「看不见」的颜色，
#: 不追求正文级 4.5:1，以免误杀用户选择的深色/浅色强调色）。
_MIN_ACCENT_CONTRAST: float = 1.5

#: 无彩色判定阈值：RGB 极差小于该值视为灰阶。近黑/近白的灰阶
#: 强调色无法提供可辨识的品牌色，只能回退默认色而不是返回灰色。
_MIN_CHROMA: int = 16


# ── 颜色解析 / 校验 ─────────────────────────────────────────────────


def _to_hex(r: int, g: int, b: int) -> str:
    """把 0-255 的 RGB 分量序列化为大写 ``#RRGGBB``。

    Args:
        r: 红色分量。
        g: 绿色分量。
        b: 蓝色分量。

    Returns:
        str: 形如 ``#007AFF`` 的字符串。
    """
    return f"#{r & 0xFF:02X}{g & 0xFF:02X}{b & 0xFF:02X}"


def _normalize_hex(value: object) -> Optional[str]:
    """把 ``#RGB`` / ``#RRGGBB`` / ``#RRGGBBAA`` 归一化为 ``#RRGGBB``。

    Args:
        value: 任意待校验值。

    Returns:
        Optional[str]: 合法时返回大写 ``#RRGGBB``；非法返回 None。
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text.startswith("#"):
        return None
    digits = text[1:]
    if len(digits) == 3:
        digits = "".join(ch * 2 for ch in digits)
    elif len(digits) == 8:
        # 项目约定为 #RRGGBBAA（非 Qt 旧的 #AARRGGBB），强调色丢弃 alpha。
        digits = digits[:6]
    if len(digits) != 6:
        return None
    try:
        int(digits, 16)
    except ValueError:
        return None
    return f"#{digits.upper()}"


def _parse_rgb(hex_color: object) -> Optional[Tuple[int, int, int]]:
    """解析 ``#RRGGBB`` 为 ``(r, g, b)``。

    Args:
        hex_color: 颜色字符串。

    Returns:
        Optional[Tuple[int, int, int]]: 解析成功返回三元组，否则 None。
    """
    normalized = _normalize_hex(hex_color)
    if normalized is None:
        return None
    return (
        int(normalized[1:3], 16),
        int(normalized[3:5], 16),
        int(normalized[5:7], 16),
    )


def _relative_luminance(r: int, g: int, b: int) -> float:
    """计算 sRGB 相对亮度（WCAG 2.x）。

    Args:
        r: 红色分量（0-255）。
        g: 绿色分量（0-255）。
        b: 蓝色分量（0-255）。

    Returns:
        float: 0.0（纯黑）到 1.0（纯白）之间的相对亮度。
    """

    def _linear(channel: int) -> float:
        c = max(0, min(255, int(channel))) / 255.0
        if c <= 0.04045:
            return c / 12.92
        return ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)


def _contrast_ratio(lum_a: float, lum_b: float) -> float:
    """计算两相对亮度之间的 WCAG 对比度。"""
    high, low = max(lum_a, lum_b), min(lum_a, lum_b)
    return (high + 0.05) / (low + 0.05)


def _is_usable_accent(hex_color: object) -> bool:
    """判断颜色是否可作为强调色（对深浅两种底板都可见）。

    Args:
        hex_color: 待判断颜色。

    Returns:
        bool: 合法且对比度达标返回 True；近黑/近白/非法返回 False。
    """
    rgb = _parse_rgb(hex_color)
    if rgb is None:
        return False
    luminance = _relative_luminance(*rgb)
    for surface in (_DARK_SURFACE_LUMINANCE, _LIGHT_SURFACE_LUMINANCE):
        if _contrast_ratio(luminance, surface) < _MIN_ACCENT_CONTRAST:
            return False
    return True


def _is_chromatic(hex_color: object) -> bool:
    """判断颜色是否带色相（非灰阶）。

    Args:
        hex_color: 待判断颜色。

    Returns:
        bool: RGB 极差达到阈值的彩色返回 True；灰阶/非法返回 False。
    """
    rgb = _parse_rgb(hex_color)
    if rgb is None:
        return False
    return max(rgb) - min(rgb) >= _MIN_CHROMA


def _abgr_to_hex(value: object) -> Optional[str]:
    """把 ``0xAABBGGRR``（ABGR）DWORD 转为 ``#RRGGBB``。

    Args:
        value: 注册表读出的 DWORD（int）。

    Returns:
        Optional[str]: 值为 0 / 非法时返回 None。
    """
    try:
        packed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if packed <= 0 or ((packed >> 24) & 0xFF) == 0:
        # 0 与 alpha=0 均视为「未设置」。
        return None
    return _to_hex(packed & 0xFF, (packed >> 8) & 0xFF, (packed >> 16) & 0xFF)


def _argb_to_hex(value: object) -> Optional[str]:
    """把 ``0xAARRGGBB``（ARGB）DWORD 转为 ``#RRGGBB``。

    Args:
        value: DWM 返回的 DWORD（int）。

    Returns:
        Optional[str]: 值为 0 / 非法时返回 None。
    """
    try:
        packed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if packed <= 0 or ((packed >> 24) & 0xFF) == 0:
        # 0 与 alpha=0 均视为「未设置」。
        return None
    return _to_hex((packed >> 16) & 0xFF, (packed >> 8) & 0xFF, packed & 0xFF)


# ── 注册表读取 ──────────────────────────────────────────────────────


def _read_registry_value(subkey: str, name: str) -> Optional[object]:
    """读取 HKCU 下指定子键的值（失败安全）。

    Args:
        subkey: 相对 HKEY_CURRENT_USER 的子键路径。
        name: 值名称。

    Returns:
        Optional[object]: 读取成功返回值（DWORD 为 int、BINARY 为 bytes）；
            非 Windows / 键或值缺失 / 权限不足时返回 None。
    """
    if winreg is None or sys.platform != "win32":
        return None
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            subkey,
            0,
            winreg.KEY_READ,
        ) as key:
            value, _ = winreg.QueryValueEx(key, name)
            return value
    except Exception:
        return None


def _read_accent_palette() -> List[str]:
    """读取 ``AccentPalette`` 中的 7 档同源色阶。

    每条 4 字节，按 ``R, G, B, A`` 存放；最后一条（第 8 条）在
    Windows 10/11 上恒为固定哨兵 ``88 17 98 00``，不属于色阶，必须跳过。

    Returns:
        List[str]: 按注册表原顺序（由浅到深）的 ``#RRGGBB`` 列表；
            读取失败返回空列表。
    """
    raw = _read_registry_value(_ACCENT_SUBKEY, "AccentPalette")
    if isinstance(raw, (bytes, bytearray)):
        data = list(raw)
    elif isinstance(raw, (list, tuple)) and all(isinstance(item, int) for item in raw):
        data = list(raw)  # type: ignore[arg-type]
    else:
        return []

    shades: List[str] = []
    for index in range(min(_PALETTE_SHADE_COUNT, len(data) // 4)):
        r, g, b = data[index * 4], data[index * 4 + 1], data[index * 4 + 2]
        if r == 0 and g == 0 and b == 0:
            continue
        shades.append(_to_hex(r, g, b))
    return shades


# ── 各数据源读取 ────────────────────────────────────────────────────


def _get_accent_color_from_accent_registry() -> Optional[str]:
    """读取「强调色本体」：AccentColorMenu，缺失时回退 StartColorMenu。

    Returns:
        Optional[str]: ``#RRGGBB``；两项均缺失/为 0 时返回 None。
    """
    for value_name in ("AccentColorMenu", "StartColorMenu"):
        color = _abgr_to_hex(_read_registry_value(_ACCENT_SUBKEY, value_name))
        if color is not None:
            return color
    return None


def _get_accent_color_from_dwm_accent() -> Optional[str]:
    """读取 ``DWM\\AccentColor``（ABGR）。

    Returns:
        Optional[str]: ``#RRGGBB``；缺失/为 0 时返回 None。
    """
    return _abgr_to_hex(_read_registry_value(_DWM_SUBKEY, "AccentColor"))


def _get_accent_color_from_dwm() -> Optional[str]:
    """调用 ``DwmGetColorizationColor`` 读取 DWM 合成色（ARGB）。

    该值是 DWM 的合成结果，并非严格意义上的强调色；仅在其它数据源
    全部不可用时作为近似兜底。

    Returns:
        Optional[str]: ``#RRGGBB``；API 失败/返回负 HRESULT 时返回 None。
    """
    if sys.platform != "win32":
        return None
    try:
        dwmapi = ctypes.WinDLL("dwmapi")
        get_colorization = dwmapi.DwmGetColorizationColor
        get_colorization.argtypes = [
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.BOOL),
        ]
        # 注意：HRESULT 定义在 ctypes 上，ctypes.wintypes 中并不存在；
        # 早期实现写 wintypes.HRESULT 会抛 AttributeError 并被 except
        # 静默吞掉，导致该数据源永远失效。
        get_colorization.restype = ctypes.HRESULT

        colorization = wintypes.DWORD()
        opaque_blend = wintypes.BOOL()
        result = get_colorization(
            ctypes.byref(colorization), ctypes.byref(opaque_blend)
        )
        if result < 0:
            return None
        return _argb_to_hex(colorization.value)
    except Exception:
        return None


def _get_accent_color_from_registry() -> Optional[str]:
    """读取 ``DWM\\ColorizationColor``（ARGB）作为最后的近似兜底。

    Returns:
        Optional[str]: ``#RRGGBB``；缺失/为 0 时返回 None。
    """
    return _argb_to_hex(_read_registry_value(_DWM_SUBKEY, "ColorizationColor"))


# ── 色阶档位选择 ────────────────────────────────────────────────────


def _usable_palette_shades() -> List[str]:
    """返回 ``AccentPalette`` 中按亮度升序排列的可用色阶。"""
    shades = [shade for shade in _read_accent_palette() if _is_usable_accent(shade)]

    def _luminance(color: str) -> float:
        rgb = _parse_rgb(color)
        return _relative_luminance(*rgb) if rgb is not None else 0.0

    shades.sort(key=_luminance)
    return shades


def _pick_palette_shade(prefer_light: bool) -> Optional[str]:
    """从系统色阶中挑选可用的彩色档位。

    Args:
        prefer_light: 主色过暗时取最亮档；主色过亮时取最暗档。

    Returns:
        Optional[str]: 彩色可用色阶；灰阶/全部不可用/色阶缺失时返回 None。
    """
    shades = [shade for shade in _usable_palette_shades() if _is_chromatic(shade)]
    if not shades:
        return None
    return shades[-1] if prefer_light else shades[0]


def _pick_middle_palette_shade() -> Optional[str]:
    """主色完全缺失时，取系统色阶的中位彩色可用档位。

    Returns:
        Optional[str]: 彩色可用色阶；灰阶/全部不可用/色阶缺失时返回 None。
    """
    shades = [shade for shade in _usable_palette_shades() if _is_chromatic(shade)]
    if not shades:
        return None
    return shades[len(shades) // 2]


# ── 对外入口 ────────────────────────────────────────────────────────


def get_system_accent_color(default: str = _DEFAULT_ACCENT) -> str:
    """返回当前 Windows 个人化强调色（``#RRGGBB``）。

    依次尝试「强调色本体 → DWM AccentColor → 系统色阶 → DWM 合成色 →
    合成色注册表缓存」，全部失败或得到的颜色不可辨识时回退 *default*。

    Args:
        default: 兜底颜色；非法时改用 ``#007AFF``。

    Returns:
        str: 大写 ``#RRGGBB`` 颜色字符串，保证可直接用于主题配色。
    """
    fallback = _normalize_hex(default) or _DEFAULT_ACCENT
    if not _is_usable_accent(fallback):
        # 调用方传入的兜底色本身也不可辨识（如纯黑）→ 使用内置兜底色，
        # 保证返回值永远可直接用于主题配色。
        fallback = _DEFAULT_ACCENT

    primary = (
        _get_accent_color_from_accent_registry() or _get_accent_color_from_dwm_accent()
    )
    if primary is not None:
        if _is_usable_accent(primary):
            return primary
        # 主色存在但不可辨识（如纯黑）：先判断它「太暗」还是「太亮」——
        # 对深色底板对比度不足时取更亮档，否则取更暗档；灰阶色阶会被
        # 过滤掉（纯黑/纯白强调色的色阶无可用色相），最终回退默认色。
        rgb = _parse_rgb(primary)
        if rgb is not None:
            luminance = _relative_luminance(*rgb)
            prefer_light = (
                _contrast_ratio(luminance, _DARK_SURFACE_LUMINANCE)
                < _MIN_ACCENT_CONTRAST
            )
            shade = _pick_palette_shade(prefer_light=prefer_light)
            if shade is not None:
                return shade
        return fallback

    # 主色缺失（部分精简系统/组策略环境）：系统色阶取中位可用档位。
    shade = _pick_middle_palette_shade()
    if shade is not None:
        return shade

    for reader in (
        _get_accent_color_from_dwm,
        _get_accent_color_from_registry,
    ):
        color = reader()
        if color is not None and _is_usable_accent(color):
            return color

    return fallback
