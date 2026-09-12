#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地无边框窗口基类（替代外部依赖 PySideSix-Frameless-Window / qframelesswindow）

基于 Qt 6.10+ 原生方案（经 _frameless_modern_demo.py M6 组合人工验证）：

    Qt.Window | Qt.ExpandedClientAreaHint | Qt.NoTitleBarBackgroundHint

适用版本：``PySide6>=6.10.0``。这两个标志虽是 Qt 6.9 引入，但 Qt 6.9 的
``fixTopLevelWindowFlags`` 用 ``switch (flags)`` 精确匹配整个 flags，带上
``ExpandedClientAreaHint|NoTitleBarBackgroundHint`` 后不再命中裸
``Qt::Window``，不会自动补全 title hints → ``WS_CAPTION`` 等样式位全缺 →
最大化动画消失 / Win7 边框；Qt 6.10 加了 ``clientAreaHints`` 排除逻辑
（``switch (flags & ~clientAreaHints)``）才修复（详见 AGENTS.md）。

设计要点（与 win32 原生能力的关系）：
1. 窗口标志
   - ``Qt.Window`` 触发 Qt 在 Windows 平台自动补全
     ``WindowTitleHint|WindowSystemMenuHint|WindowMinimizeButtonHint|
     WindowMaximizeButtonHint|WindowCloseButtonHint``（见 qtbase
     qwindowswindow.cpp ``fixTopLevelWindowFlags``），原生 ``WS_CAPTION|
     WS_SYSMENU|WS_THICKFRAME|WS_MINIMIZEBOX|WS_MAXIMIZEBOX`` 样式位全部
     保留 → 最大化/最小化动画、Aero Snap 贴靠、八向原生缩放俱在。
   - ``Qt.ExpandedClientAreaHint`` 让 WM_NCCALCSIZE 返回 0 把客户区扩展到
     整个窗口（非客户区仅剩 ~8px 缩放边框），内容可绘制到原标题栏区域；
     同时 Qt 自动 ``DwmExtendFrameIntoClientArea(-1)`` 保留圆角与阴影。
   - ``Qt.NoTitleBarBackgroundHint`` 让 Qt 的标题栏子窗口不画背景。
2. 去掉系统按钮（两条路径）
   a) 清除 ``WS_SYSMENU``：Qt 为 ExpandedClientAreaHint 施加
      ``DwmExtendFrameIntoClientArea``，若保留 ``WS_SYSMENU``，DWM 会在被
      扩展的帧区域里绘制系统按钮（— □ ✕）。内容不透明的窗口能把它盖住
      （demo M6 就是如此，属于假象），而本项目标题栏半透明（Mica）会透出。
      故窗口创建/重建后一律 ``style & ~WS_SYSMENU``；``WS_CAPTION`` 必须
      保留（原生最大化/最小化动画与 Aero Snap 的前提）。代价是标题栏右键
      系统菜单 / Alt+Space 失效（产品已确认不需要）。
   b) 撤下 Qt 的标题栏绘制层 ``_q_titlebar``：Qt 6.9+ 为
      ExpandedClientAreaHint 窗口创建它（``WS_EX_LAYERED|WS_EX_TRANSPARENT|
      WS_EX_NOACTIVATE``）绘制系统标题文本与三个按钮，本项目标题栏完全自绘，
      故按 Qt 官方隐藏逻辑（``SetParent(HWND_MESSAGE) + SW_HIDE``）撤下。
      **Qt 6.10 实测它是「顶层窗口」而非主窗口的子窗口**，只按子窗口查找会
      永远找不到（旧实现即因此静默失效、原生按钮一直盖在自绘标题栏下面），
      故 ``_find_qt_titlebars_top_level`` 按「类名 + 本进程」枚举顶层窗口一并撤下。
3. safeArea 下推消除
   ExpandedClientAreaHint 会让平台层返回 ``safeAreaMargins=(0, 标题栏高,
   0, 0)``，且顶层窗口默认自动开启 ``WA_ContentsMarginsRespectsSafeArea``，
   导致整个内容层被下推一个标题栏高度（实测 21px）。此处显式关闭该属性
   （显式 setAttribute 会标记 explicit，阻止 Qt 的默认自动开启）。
4. WM_NCHITTEST 拦截
   尽管样式位保留，仍拦截 WM_NCHITTEST：8px 边缘缩放带返回原生 HT* 缩放
   码，其余（含顶部标题栏区域）一律返回 HTCLIENT —— 系统按钮命中彻底失效，
   拖拽移动交给自绘标题栏的 ``windowHandle().startSystemMove()``（该路径
   仍走系统移动循环，Aero Snap 保留）。
5. WM_NCCALCSIZE 的 wParam==FALSE 分支接管（补 Qt 的缺口）
   Qt 仅在自己处理 ``WM_NCCALCSIZE(wParam==TRUE)`` 时扩展客户区；窗口创建
   或 HWND 重建时的第一次 ``WM_NCCALCSIZE(wParam==FALSE)`` 会落到
   DefWindowProc，由系统按「标准窗口」算出完整非客户区（含标题栏与系统
   按钮）。其表现就是主窗口快速拖拽缩放（GPU/原生子表面令顶层 HWND 重建）
   时右上角闪出原生最小化/最大化/关闭按钮。基类直接在 ``nativeEvent`` 里
   接管该分支，按 Qt 同样的数学给出客户区，并配合
   ``SetWindowPos(SWP_FRAMECHANGED)`` 强制重算帧，彻底不给系统画标题栏的
   机会，同时**保留 WS_CAPTION**——它正是原生最大化/最小化动画的前提。

使用：
    class MainWindow(_FramelessNativeEffectsMixin, FramelessMainWindow): ...
"""

import ctypes
import os
import sys
import traceback
from ctypes import wintypes

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import QMainWindow

from freeassetfilter.utils.app_logger import info, warning

# WM_NCHITTEST 命中码（仅本模块使用）
_HTCLIENT = 1
_HTTOP = 12
_HTTOPLEFT = 13
_HTTOPRIGHT = 14
_HTBOTTOM = 15
_HTBOTTOMLEFT = 16
_HTBOTTOMRIGHT = 17
_HTLEFT = 10
_HTRIGHT = 11

# 边缘缩放带宽度：与 WS_THICKFRAME 边框一致（DPI 无关，系统缩放由命中码驱动）。
# 该值与 Qt 的 getResizeBorderThickness(96) 相同（SM_CXSIZEFRAME 4 +
# SM_CXPADDEDBORDER 4，Qt 在 handleCalculateSize 中硬编码 96 DPI），故物理像素
# 恒为 8，与显示器缩放无关。
_EDGE_BORDER = 8

# 参与的窗口消息
_WM_NCCALCSIZE = 0x0083
_WM_NCHITTEST = 0x0084

# HWND_MESSAGE = (HWND)-3。绝不能用 0xFFFFFFFF：那是 0x00000000FFFFFFFF 的
# 正数句柄，SetParent 会以 ERROR_INVALID_WINDOW_HANDLE(1400) 失败。
_HWND_MESSAGE = -3

# SetWindowPos 标志（强制重算非客户区，不移动/缩放/激活窗口）
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010
_SWP_FRAMECHANGED = 0x0020
_SWP_FRAME_RECALC = (
    _SWP_FRAMECHANGED | _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOZORDER | _SWP_NOACTIVATE
)

#: Qt 为 ExpandedClientAreaHint 创建的系统标题栏子窗口类名。
#: 当同一进程内注册过不同 Qt 实例的同名类时，Qt 会给类名追加 UUID 后缀，
#: 故匹配时用前缀而非全等（见 ``_find_qt_titlebar``）。
_TITLEBAR_CLASS = "_q_titlebar"

#: EnumChildWindows 回调原型（找到目标时返回 FALSE 以停止枚举）。
_ENUM_CHILD_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

#: 顶层 ``_q_titlebar`` 逐个查找的上限（FindWindowExW 循环）。
#: 实测该窗口**不在 ``EnumWindows`` 的枚举结果里**（654 个顶层窗口 / 151 个类名
#: 均无匹配），只能用 ``FindWindowExW(NULL, prev, "_q_titlebar", None)`` 逐个取，
#: 故用上限 + 去重防御替身或异常环境返回同一句柄导致死循环。
_TITLEBAR_TOP_LEVEL_MAX_SCAN = 64

# GetWindowLong 索引与样式位（用于兜底隐藏：摘除失败时清除 WS_VISIBLE）
_GWL_STYLE = -16
_WS_VISIBLE = 0x10000000

#: WS_SYSMENU（系统菜单样式位）。**必须清除**：它与 Qt 为 ExpandedClientAreaHint
#: 施加的 ``DwmExtendFrameIntoClientArea`` 叠加后，DWM 会在被扩展的帧区域里绘制
#: 系统按钮（— □ ✕）。内容不透明的窗口能把它盖住（demo M6 就是如此，属于假象），
#: 而本项目标题栏走 Mica/半透明，就会透出来 —— 这正是「自绘标题栏下面盖着一层
#: 原生按钮、拖拽缩放时冒出第二个关闭按钮」的来源。代价是标题栏右键系统菜单与
#: Alt+Space 失效（产品已确认不需要）。**不要顺带清除 WS_CAPTION**：原生最大化/
#: 最小化动画与 Aero Snap 都依赖它。
_WS_SYSMENU = 0x00080000

#: 原生无边框窗口所需的最低 Qt 版本（ExpandedClientAreaHint 的 title hints
#: 自动补全逻辑自 Qt 6.10 起才正确，见模块 docstring）。
MIN_QT_VERSION = (6, 10)

#: 已声明原型的 user32 缓存（None 表示尚未初始化/不可用）。
_user32 = None


def _get_user32():
    """返回已声明 argtypes/restype 的 user32，不可用时返回 None。

    必须显式声明原型：``ctypes.windll`` 的默认 ``restype`` 是 32 位 ``c_long``，
    会把 HWND 截断；``SetWindowPos``/``SetParent`` 等也需要正确的 HWND 参数类型
    才能接受 ``HWND_MESSAGE`` 这类特殊值。
    """
    global _user32
    if _user32 is not None:
        return _user32
    if sys.platform != "win32":
        return None
    try:
        lib = ctypes.WinDLL("user32", use_last_error=True)
    except OSError:  # pragma: no cover - 仅异常环境触发
        return None
    lib.FindWindowExW.argtypes = [
        wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
    ]
    lib.FindWindowExW.restype = wintypes.HWND
    lib.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
    lib.SetParent.restype = wintypes.HWND
    lib.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    lib.ShowWindow.restype = wintypes.BOOL
    lib.IsZoomed.argtypes = [wintypes.HWND]
    lib.IsZoomed.restype = wintypes.BOOL
    lib.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    lib.GetWindowRect.restype = wintypes.BOOL
    lib.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, wintypes.UINT,
    ]
    lib.SetWindowPos.restype = wintypes.BOOL
    lib.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    lib.GetClassNameW.restype = ctypes.c_int
    lib.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    lib.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    lib.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    lib.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    lib.EnumChildWindows.argtypes = [wintypes.HWND, _ENUM_CHILD_PROC, wintypes.LPARAM]
    lib.EnumChildWindows.restype = wintypes.BOOL
    lib.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND, ctypes.POINTER(wintypes.DWORD),
    ]
    lib.GetWindowThreadProcessId.restype = wintypes.DWORD
    _user32 = lib
    return lib


def _find_qt_titlebar(hwnd: int, deep: bool = False) -> int:
    """查找 Qt 的 ``_q_titlebar`` 子窗口，返回 HWND（未找到返回 0）。

    Args:
        hwnd: 顶层窗口句柄。
        deep: True 时在 ``FindWindowExW``（精确类名）失败后，改用
            ``EnumChildWindows`` 按类名前缀匹配。用于兜底「同名类被追加
            UUID 后缀」或其它类名变体；成本高于精确查找，故仅在
            WinIdChange/showEvent 等低频路径启用。
    """
    user32 = _get_user32()
    if user32 is None or not hwnd:
        return 0
    tb = user32.FindWindowExW(wintypes.HWND(hwnd), None, _TITLEBAR_CLASS, None)
    # 注意：ctypes 的 HWND 是 c_void_p，`int(HWND)` 会按字节串解析并抛 ValueError，
    # 必须取 .value（与 _hide_qt_titlebar 中的同类说明一致）。
    tb_value = int(getattr(tb, "value", tb) or 0)
    if tb_value or not deep:
        return tb_value

    found = {"hwnd": 0}

    def _cb(child, _lparam):
        buf = ctypes.create_unicode_buffer(128)
        user32.GetClassNameW(child, buf, 128)
        if buf.value.startswith(_TITLEBAR_CLASS):
            found["hwnd"] = int(getattr(child, "value", child) or 0)
            return False  # 停止枚举
        return True

    try:
        user32.EnumChildWindows(wintypes.HWND(hwnd), _ENUM_CHILD_PROC(_cb), 0)
    except Exception:  # noqa: BLE001 - 兜底查找失败按未找到处理
        return 0
    return found["hwnd"]


def _find_qt_titlebars_top_level() -> list[int]:
    """返回当前进程内所有顶层 ``_q_titlebar`` 窗口句柄（按类名 + 进程过滤）。

    Qt 6.10 实测把该窗口创建为**顶层窗口**（owner=0，
    ``WS_EX_LAYERED|WS_EX_TRANSPARENT|WS_EX_NOACTIVATE``，尺寸约为「窗口宽 ×
    标题栏高」），而**不是主窗口的子窗口**——只按子窗口查找会永远返回空，这正是
    旧实现「静默失效、原生按钮一直盖在自绘标题栏下面」的根因（实测
    ``_hide_qt_titlebar(deep=True)`` 恒为 False）。

    **不能用 ``EnumWindows``**：实测其枚举出的 654 个顶层窗口 / 151 个类名中
    都没有 ``_q_titlebar``；只能用 ``FindWindowExW(NULL, prev, "_q_titlebar",
    None)`` 逐个取（同 Qt 官方 ``FindWindowEx``/演示脚本的做法）。

    进程内该窗口均属于本项目自己的无边框窗口，语义上都需要隐藏，故按进程过滤后
    全部返回，无需再区分它属于哪一个窗口。
    """
    user32 = _get_user32()
    if user32 is None:
        return []
    my_pid = os.getpid()
    found: list[int] = []
    seen: set[int] = set()
    prev = wintypes.HWND(0)
    try:
        for _ in range(_TITLEBAR_TOP_LEVEL_MAX_SCAN):
            hwnd = user32.FindWindowExW(None, prev, _TITLEBAR_CLASS, None)
            hwnd_value = int(getattr(hwnd, "value", hwnd) or 0)
            if not hwnd_value or hwnd_value in seen:
                break
            seen.add(hwnd_value)
            pid = wintypes.DWORD(0)
            user32.GetWindowThreadProcessId(
                wintypes.HWND(hwnd_value), ctypes.byref(pid)
            )
            if pid.value == my_pid:
                found.append(hwnd_value)
            prev = wintypes.HWND(hwnd_value)
    except Exception:  # noqa: BLE001 - 枚举失败按已找到的结果返回
        return found
    return found


def _hit_test_code(x: int, y: int, left: int, top: int, right: int, bottom: int,
                   border: int) -> int:
    """计算 WM_NCHITTEST 命中码（纯函数，便于单测）。

    窗口矩形为 (left, top, right, bottom)，边缘缩放带宽度为 ``border``：
    - 落入边缘带的坐标返回对应 HT* 缩放码（HTTOPLEFT/HTTOP/HTLEFT...）；
    - 其余一律返回 HTCLIENT（含顶部标题栏区域，系统按钮命中失效）。
    """
    lx = x - left < border
    rx = right - x < border
    ty = y - top < border
    by = bottom - y < border
    if lx and ty:
        return _HTTOPLEFT
    if rx and by:
        return _HTBOTTOMRIGHT
    if rx and ty:
        return _HTTOPRIGHT
    if lx and by:
        return _HTBOTTOMLEFT
    if ty:
        return _HTTOP
    if by:
        return _HTBOTTOM
    if lx:
        return _HTLEFT
    if rx:
        return _HTRIGHT
    return _HTCLIENT


def _calc_client_rect_wparam0(left: int, top: int, right: int, bottom: int,
                              border: int, maximized: bool) -> tuple[int, int, int, int]:
    """按 Qt 的客户区扩展数学，把拟定窗口矩形换算为客户区矩形（纯函数，便于单测）。

    对应 qtbase ``qwindowswindow.cpp`` 的
    ``QWindowsGeometryHint::handleCalculateSize`` 中 ExpandedClientAreaHint
    分支（``wParam==TRUE`` 时由 Qt 自身完成）：

    - 非最大化：左/右/下各内缩 ``border``，**顶边不缩**（内容可绘制到原标题栏区）；
    - 最大化：四边都内缩 ``border``（避免内容被边框裁掉）。

    Returns:
        ``(left, top, right, bottom)``：调整后的客户区矩形。
    """
    if border <= 0:
        return left, top, right, bottom
    if maximized:
        top += border
    return left + border, top, right - border, bottom - border


def _parse_version(text: str) -> tuple[int, ...]:
    """把 ``"6.10.3"`` 之类的版本串解析为整数元组（宽松解析）。"""
    parts: list[int] = []
    for token in str(text).split("."):
        digits = ""
        for ch in token:
            if ch.isdigit():
                digits += ch
            else:
                break
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def frameless_runtime_status() -> tuple[bool, str]:
    """检查当前运行时是否支持原生无边框窗口（Qt 6.10+ 的 ExpandedClientAreaHint）。

    Returns:
        ``(supported, detail)``。supported 为 True 时 detail 为当前 Qt/PySide6
        版本；为 False 时 detail 为原因与修复建议（供日志与提示框直接展示）。
    """
    try:  # pragma: no cover - 版本号仅用于展示
        from PySide6 import __version__ as pyside_version
    except Exception:  # noqa: BLE001
        pyside_version = "未知"
    try:  # pragma: no cover - 版本号仅用于展示
        from PySide6.QtCore import qVersion

        qt_version = qVersion()
    except Exception:  # noqa: BLE001
        qt_version = pyside_version

    minimum = f"{MIN_QT_VERSION[0]}.{MIN_QT_VERSION[1]}"
    if not hasattr(Qt, "ExpandedClientAreaHint"):
        return False, (
            f"当前 Qt {qt_version} / PySide6 {pyside_version} 缺少 "
            f"Qt.ExpandedClientAreaHint，无边框窗口会退化成带原生标题栏的普通窗口。"
            f"请升级 PySide6>={minimum} 后重新安装或重新打包。"
        )
    parsed = _parse_version(qt_version)
    if parsed[:2] and parsed[:2] < MIN_QT_VERSION:
        return False, (
            f"当前 Qt {qt_version} / PySide6 {pyside_version} 低于 {minimum}，"
            f"ExpandedClientAreaHint 的 title hints 不会自动补全，窗口会退化为 "
            f"Win7 风格边框并丢失最大化动画。请升级 PySide6>={minimum} 后重新"
            f"安装或重新打包。"
        )
    return True, f"Qt {qt_version} / PySide6 {pyside_version}"


class FramelessMainWindow(QMainWindow):
    """基于 Qt 6.10+ 原生 ExpandedClientAreaHint 方案的无边框主窗口基类。

    替代 qframelesswindow.FramelessMainWindow：不依赖外部无边框库，完整
    保留原生窗口能力（动画 / Aero Snap / 缩放），并彻底移除系统按钮的
    图形与命中。自绘标题栏由子类负责（拖拽经 startSystemMove）。
    """

    #: 诊断用：WinIdChange 记录调用栈的最大次数（防止频繁重建时刷屏日志）。
    _WIN_ID_STACK_LIMIT = 10

    def __init__(self, parent=None):
        super().__init__(parent)
        flags = Qt.Window
        self._expanded_client_area = hasattr(Qt, "ExpandedClientAreaHint")
        if self._expanded_client_area:
            flags |= Qt.ExpandedClientAreaHint
        if hasattr(Qt, "NoTitleBarBackgroundHint"):
            flags |= Qt.NoTitleBarBackgroundHint
        self.setWindowFlags(flags)

        if not self._expanded_client_area:
            # 旧 Qt（如打包环境内置的 6.8）：无边框能力不可用，窗口会带原生
            # 标题栏。启动流程会另行给出显著提示，这里只做兜底记录。
            supported, detail = frameless_runtime_status()
            if not supported:
                warning(f"无边框窗口退化：{detail}")

        # 关闭 safeArea 内容下推（ExpandedClientAreaHint 默认会让平台返回
        # safeAreaMargins=(0, 标题栏高, 0, 0)，顶层窗口默认自动开启
        # WA_ContentsMarginsRespectsSafeArea 把内容推下一个标题栏高度）。
        # 显式 setAttribute 会标记 explicitContentsMarginsRespectsSafeArea，
        # 阻止 Qt 的默认自动开启（qtbase qwidget.cpp:1209-1220 / 11406-11410）。
        if hasattr(Qt.WidgetAttribute, "WA_ContentsMarginsRespectsSafeArea"):
            self.setAttribute(Qt.WidgetAttribute.WA_ContentsMarginsRespectsSafeArea, False)

        # 若构造阶段 HWND 已存在（winId 被提前访问），立即隐藏 Qt 标题栏。
        # 这里用 internalWinId() 判断而**不能**用 winId()：winId() 会强制建窗，
        # 而顶层窗口一旦建窗就固定了合成后端（raster / RHI）。音频模式的流体
        # 背景需要 RHI 合成后端（见 main_window 中建窗前的预热点），提前建窗会
        # 让预热失效。HWND 尚未创建时由 showEvent / WinIdChange 兜底处理。
        if self.internalWinId():
            self.reapply_native_window_effects()

    # ---- 事件钩子 ----
    def showEvent(self, event) -> None:
        """窗口显示时确保 Qt 标题栏子窗口被隐藏、且非客户区已被扩展。"""
        super().showEvent(event)
        self.reapply_native_window_effects()

    def event(self, e: QEvent) -> bool:
        """监听 WinIdChange：HWND 重建（GPU 表面附着等）后新 ``_q_titlebar``
        子窗口会重新出现，且创建期的 ``WM_NCCALCSIZE(wParam=FALSE)`` 会让系统
        算出完整标题栏，需重新隐藏并强制重算帧。

        重建同时记录诊断信息（见 :meth:`_log_win_id_change`），用于定位触发源。
        """
        if e.type() == QEvent.Type.WinIdChange:
            self._log_win_id_change()
            self.reapply_native_window_effects()
        return super().event(e)

    def _log_win_id_change(self) -> None:
        """记录顶层 HWND 重建诊断，用于定位触发重建的代码路径。

        HWND 重建（GPU 表面附着、窗口标志变更等）是 ``_q_titlebar`` 复活与
        原生标题栏闪现的根源（见模块 docstring）。此处记录重建序号、新旧句柄、
        窗口标志、几何/窗口状态/DPR，并在前 :attr:`_WIN_ID_STACK_LIMIT` 次附带
        调用栈，便于反查是哪一个调用点触发。日志写入应用日志文件。
        """
        try:
            new_id = int(self.internalWinId() or 0)
        except (TypeError, RuntimeError, ValueError):
            new_id = 0

        old_id = getattr(self, "_diag_win_id", None)
        self._diag_win_id = new_id
        if new_id == old_id:
            return  # 句柄未变化（如仅窗口标志变更），无需记录

        count = getattr(self, "_diag_win_id_count", 0) + 1
        self._diag_win_id_count = count
        try:
            flags = int(self.windowFlags().value) & 0xFFFFFFFF
        except (AttributeError, TypeError, ValueError):
            flags = 0
        size = self.size()
        old_desc = f"0x{old_id:X}" if old_id else "无"
        info(
            f"WinIdChange #{count}: HWND {old_desc} -> 0x{new_id:X}, "
            f"flags=0x{flags:X}, {size.width()}x{size.height()}, "
            f"visible={self.isVisible()}, maximized={self.isMaximized()}, "
            f"fullscreen={self.isFullScreen()}, dpr={self.devicePixelRatioF():.2f}"
        )
        if count <= self._WIN_ID_STACK_LIMIT:
            stack = "".join(traceback.format_stack(limit=12)[:-1])
            info(f"WinIdChange #{count} 调用栈（越靠下越接近触发点）:\n{stack}")

    def nativeEvent(self, eventType: bytes, message: object) -> tuple:
        """拦截 WM_NCCALCSIZE 与 WM_NCHITTEST，接管原生非客户区。

        - ``WM_NCCALCSIZE(wParam==FALSE)``：Qt 不处理、会落到 DefWindowProc
          算出完整标题栏（快速拖拽缩放时闪出原生系统按钮的根因）。这里按
          Qt 的数学直接给出扩展后的客户区并返回已处理。
        - ``WM_NCCALCSIZE(wParam==TRUE)``：交回 Qt（Qt 自己会正确扩展）。
        - ``WM_NCHITTEST``：边缘缩放带保留原生缩放码，其余一律 HTCLIENT。
        """
        if sys.platform != "win32" or eventType != b"windows_generic_MSG":
            return super().nativeEvent(eventType, message)
        try:
            msg = wintypes.MSG.from_address(int(message))
        except Exception:
            return super().nativeEvent(eventType, message)

        if msg.message == _WM_NCCALCSIZE and self._expanded_client_area:
            if int(msg.wParam) == 0 and self._apply_client_rect_wparam0(msg):
                return True, 0
            return super().nativeEvent(eventType, message)

        if msg.message == _WM_NCHITTEST:
            return self._handle_nchittest(msg)

        return super().nativeEvent(eventType, message)

    # ---- 原生消息处理 ----
    def _msg_hwnd(self, msg) -> wintypes.HWND:
        """取消息目标窗口句柄，优先用 ``msg.hWnd``（避免在原生消息处理中回调查询 Qt）。"""
        try:
            hwnd = int(getattr(msg, "hWnd", 0) or 0)
        except (TypeError, ValueError):
            hwnd = 0
        if hwnd:
            return wintypes.HWND(hwnd)
        try:
            return wintypes.HWND(int(self.winId()))
        except (TypeError, RuntimeError, ValueError):
            return wintypes.HWND(0)

    def _apply_client_rect_wparam0(self, msg) -> bool:
        """按 Qt 的数学为 ``WM_NCCALCSIZE(wParam==FALSE)`` 写入客户区矩形。

        wParam==FALSE 时 lParam 是一个 ``RECT*``（拟定的窗口矩形，屏幕坐标），
        就地改写为客户区矩形即可；该分支的返回值被系统忽略。

        Returns:
            True 表示已成功写入（调用方应返回 ``(True, 0)`` 吞掉该消息）。
        """
        user32 = _get_user32()
        if user32 is None:
            return False
        try:
            rect = ctypes.cast(int(msg.lParam), ctypes.POINTER(wintypes.RECT)).contents
        except Exception:
            return False
        hwnd = self._msg_hwnd(msg)
        if not hwnd.value:
            return False

        maximized = bool(user32.IsZoomed(hwnd)) and not self.isFullScreen()
        left, top, right, bottom = _calc_client_rect_wparam0(
            rect.left, rect.top, rect.right, rect.bottom, _EDGE_BORDER, maximized
        )
        rect.left, rect.top, rect.right, rect.bottom = left, top, right, bottom
        return True

    def _handle_nchittest(self, msg) -> tuple:
        """WM_NCHITTEST：边缘缩放带返回原生缩放码，其余一律 HTCLIENT。"""
        user32 = _get_user32()
        if user32 is None:
            return False, 0
        hwnd = self._msg_hwnd(msg)
        if not hwnd.value:
            return False, 0

        lp = int(msg.lParam)
        x = ctypes.c_short(lp & 0xFFFF).value
        y = ctypes.c_short((lp >> 16) & 0xFFFF).value

        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False, 0
        # 最大化/全屏时无缩放边框，边缘带归零
        border = 0 if self.isMaximized() or self.isFullScreen() else _EDGE_BORDER
        code = _hit_test_code(x, y, rect.left, rect.top, rect.right, rect.bottom, border)
        return True, code

    # ---- 原生辅助 ----
    def _hide_qt_titlebar(self, deep: bool = False) -> bool:
        """隐藏 Qt 的 ``_q_titlebar`` 系统标题栏绘制层（Qt 6.9+ 内部实现）。

        对应 qtbase qwindowswindow.cpp：
          - 创建: ``CreateWindowEx(WS_EX_LAYERED|WS_EX_TRANSPARENT|
            WS_EX_NOACTIVATE, "_q_titlebar", ...)``
          - 官方隐藏: ``SetParent(hwndTitlebar, HWND_MESSAGE) + ShowWindow(SW_HIDE)``

        该窗口是 ``WS_EX_LAYERED | WS_EX_TRANSPARENT`` 的覆盖层，尺寸约为
        「窗口宽 × 标题栏高」，绘制系统标题文本与 — □ ✕ 三个按钮；垫在自绘
        标题栏下方，一旦可见就会「透出原生按钮」。

        **Qt 6.10 实测**：它被创建为**顶层窗口**（owner=0），而**不是主窗口的
        子窗口**，故这里两路查找后全部隐藏：子窗口路径兼容其它 Qt 版本，顶层
        路径覆盖 6.10 实况。进程内所有该窗口都属于本项目自己的无边框窗口，
        语义上都需要隐藏，因此无需再区分它属于哪一个窗口。

        Args:
            deep: 子窗口精确类名查不到时是否启用 ``EnumChildWindows`` 前缀匹配兜底。

        Returns:
            True 表示确实找到并隐藏了至少一个标题栏窗口。
        """
        if sys.platform != "win32":
            return False
        user32 = _get_user32()
        if user32 is None:
            return False
        try:
            # 注意：ctypes 的 HWND 是 c_void_p，int(HWND) 会按字节串解析并抛
            # ValueError——必须取 .value（早期版本正是因此静默失败）。
            # 用 internalWinId() 而非 winId()：不强制建窗（见 resizeEvent 说明）。
            hwnd_value = int(self.internalWinId() or 0)
        except (TypeError, RuntimeError, ValueError):
            return False
        if not hwnd_value:
            return False
        try:
            # 两路查找：顶层窗口（Qt 6.10 实况）+ 主窗口子窗口（兼容其它版本）
            candidates = _find_qt_titlebars_top_level()
            child = _find_qt_titlebar(hwnd_value, deep=deep)
            if child:
                candidates.append(child)
            if not candidates:
                return False
            hidden_any = False
            for tb_value in dict.fromkeys(candidates):  # 去重且保持顺序
                tb_hwnd = wintypes.HWND(tb_value)
                # 首选：把标题栏窗口摘出原层级并挂到消息窗口（HWND_MESSAGE=(HWND)-3）。
                # 消息窗口永不显示，故一旦成功即彻底杜绝系统按钮透出。
                prev_parent = user32.SetParent(tb_hwnd, wintypes.HWND(_HWND_MESSAGE))
                user32.ShowWindow(tb_hwnd, 0)  # SW_HIDE
                if not prev_parent:
                    # SetParent 失败（例如句柄无效）时兜底：清除 WS_VISIBLE 样式位，
                    # 令系统不会绘制它，即便后续被重新设置位置也保持不可见。
                    style = user32.GetWindowLongPtrW(tb_hwnd, _GWL_STYLE)
                    user32.SetWindowLongPtrW(tb_hwnd, _GWL_STYLE, style & ~_WS_VISIBLE)
                    user32.ShowWindow(tb_hwnd, 0)
                hidden_any = True
            return hidden_any
        except Exception:
            # 隐藏失败不影响窗口正常使用（仅系统按钮绘制层残留）
            return False

    def _hide_qt_titlebar_soon(self) -> None:
        """在事件循环下一轮再隐藏一次 ``_q_titlebar``（时序兜底）。

        Qt 只在 ``QWindowsWindow`` 构造与 ``setWindowFlags_sys`` 中把标题栏
        ``SW_SHOW``，而这两处都可能发生在同步回调（``WinIdChange`` /
        ``showEvent``）**返回之后**——即此刻同步隐藏会输给 Qt 稍后的显示。
        因此再排一次 ``QTimer.singleShot(0)`` 隐藏：等本轮事件派发结束、Qt
        该显示的都显示完，再撤下，避免 GPU 表面令 HWND 重建时闪出系统按钮。
        """
        QTimer.singleShot(0, self._hide_qt_titlebar)

    def _refresh_native_frame(self) -> None:
        """强制系统重算非客户区（SWP_FRAMECHANGED），清除残留的原生标题栏。

        窗口创建或 HWND 重建时的首次 ``WM_NCCALCSIZE(wParam=FALSE)`` 若未被
        接管，系统会按标准窗口算出完整标题栏。带 SWP_FRAMECHANGED 的
        SetWindowPos 会再触发一次 ``WM_NCCALCSIZE(wParam=TRUE)``，Qt 借此重新
        扩展客户区，残留标题栏随即被覆盖。不移动/缩放/激活窗口，可安全重复调用。
        """
        if sys.platform != "win32":
            return
        user32 = _get_user32()
        if user32 is None:
            return
        try:
            # 不强制建窗：HWND 尚未创建时无需重算（showEvent 会补）。
            hwnd = wintypes.HWND(int(self.internalWinId() or 0))
        except (TypeError, RuntimeError, ValueError):
            return
        if not hwnd.value:
            return
        try:
            user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, _SWP_FRAME_RECALC)
        except Exception:
            # 重算失败只影响边缘残留，不影响可用性
            pass

    def _strip_system_menu(self) -> None:
        """清除 ``WS_SYSMENU``，阻止 DWM 在扩展帧里绘制系统按钮（— □ ✕）。

        保留 ``WS_CAPTION``/``WS_THICKFRAME``（原生最大化/最小化动画与 Aero
        Snap 的前提），只去掉 ``WS_SYSMENU``——原因见 ``_WS_SYSMENU`` 常量说明。
        代价是标题栏右键系统菜单 / Alt+Space 失效（产品已确认不需要）。

        样式位变化需 ``SWP_FRAMECHANGED`` 才会让 DWM 重算帧，故调用方随后会走
        :meth:`_refresh_native_frame`。
        """
        if sys.platform != "win32":
            return
        user32 = _get_user32()
        if user32 is None:
            return
        try:
            hwnd = wintypes.HWND(int(self.internalWinId() or 0))
        except (TypeError, RuntimeError, ValueError):
            return
        if not hwnd.value:
            return
        try:
            style = user32.GetWindowLongPtrW(hwnd, _GWL_STYLE)
            if style & _WS_SYSMENU:
                user32.SetWindowLongPtrW(hwnd, _GWL_STYLE, style & ~_WS_SYSMENU)
        except Exception:
            # 清除失败只影响系统按钮绘制层，不阻断其它原生效果
            return

    def reapply_native_window_effects(self) -> None:
        """HWND 创建/重建后重新应用原生窗口效果。

        样式（``WS_THICKFRAME``/``WS_CAPTION``）由 Qt 的 ExpandedClientAreaHint
        在窗口创建时自动应用，此处按顺序补四件事：

        1. 清除 ``WS_SYSMENU``，阻止 DWM 在扩展帧里绘制系统按钮（半透明标题栏
           下会透出，是「自绘标题栏下面盖着原生按钮」的根因之一）；
        2. 确保 Qt 的 ``_q_titlebar`` 标题栏绘制层保持隐藏（顶层窗口 + 子窗口
           两路查找，``WS_VISIBLE`` 兜底清除）；
        3. 强制重算非客户区：让第 1 步的样式变化立即生效，并把创建/重建瞬间
           可能残留的原生标题栏替换为扩展后的客户区；
        4. 再排一次延迟隐藏——Qt 可能在本同步回调返回之后才把标题栏
           ``SW_SHOW``，只做同步隐藏会输掉这个时序竞争。
        """
        self._strip_system_menu()
        self._hide_qt_titlebar(deep=True)
        self._refresh_native_frame()
        self._hide_qt_titlebar_soon()

    def resizeEvent(self, event) -> None:
        """缩放时压制 ``_q_titlebar``（系统按钮只会在缩放过程中透出）。

        Qt 只在 ``QWindowsWindow`` 构造（HWND 重建）与 ``setWindowFlags_sys``
        中 ``SW_SHOW`` 该子窗口，且都发生在同步回调返回之后，故这里按
        「同步隐藏 + 延迟隐藏」各兜底一次。

        不再使用缩放期轮询定时器：实测当前实现（QRhiWidget 参与宿主合成、
        不原生化）下缩放不会重建 HWND，真正的重建场景由 :meth:`event` 的
        ``WinIdChange`` 钩子覆盖（见 ``_FramelessNativeEffectsMixin`` 说明）。

        用 ``internalWinId()`` 判断而非 ``winId()``：主窗口在 ``__init__`` 阶段
        就会 ``resize()``，而 ``winId()`` 会强制建窗——顶层窗口一旦建窗就固定了
        合成后端，会让建窗前的 RHI 预热失效（流体背景静默回退 CPU）。HWND 尚未
        创建时无需处理，showEvent / WinIdChange 会补上。
        """
        super().resizeEvent(event)
        if not self._expanded_client_area or not self.internalWinId():
            return
        self._hide_qt_titlebar()
        self._hide_qt_titlebar_soon()
