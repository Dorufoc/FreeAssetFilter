# -*- coding: utf-8 -*-
"""提权进程下的原生 ``WM_DROPFILES`` 拖入兜底（``ElevatedDropFallbackMixin``）。

背景：应用以管理员身份运行时，Windows 的 UIPI 会让 Explorer（中等完整性）发起
的 OLE 拖放（``IDropTarget`` 路径）被静默丢弃，窗口收不到任何
``dragEnterEvent``。``WM_DROPFILES`` 是绕开 UIPI 的经典途径，但它只发给按
「传统模式」注册的窗口，而 ``DragAcceptFiles`` 与 OLE 注册互斥——故安装顺序
必须是「先 ``RevokeDragDrop``，再 ``DragAcceptFiles``」，否则窗口永远收不到
``WM_DROPFILES``。

本模块提供：

- :class:`ElevatedDropFallbackMixin`：宿主窗口（``MainWindow`` /
  ``FloatingPoolWindow``）多继承本 Mixin 后，自动在「Windows + 提权进程」下
  安装原生兜底；未提权时零原生调用、``nativeEvent`` 保持纯透传，行为与安装前
  完全一致。
- 模块级可打桩函数（``_revoke_drag_drop`` / ``_drag_accept_files`` /
  ``_allow_dropped_message`` / ``_resolve_client_drop_point`` /
  ``_query_drop_paths`` / ``_drag_finish``）：单元测试据此在不触碰真实原生侧的
  情况下验证安装语义与消息处理流程。

坐标口径：``DragQueryPoint`` 返回目标窗口**客户区物理像素**；命中测试
（:meth:`ElevatedDropFallbackMixin._elevated_drop_accepts_point`）接收 Qt 逻辑
坐标，故按 ``devicePixelRatioF()`` 换算后再调用。HDROP 句柄由 ``try/finally``
保证 ``DragFinish``，任何路由异常都不得穿透回 Qt 的原生回调。
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Any, Optional

from PySide6.QtCore import QEvent
from PySide6.QtGui import QShowEvent

from sopeek.utils import elevation
from sopeek.utils.app_logger import debug, info, warning

WM_DROPFILES = 0x0233
"""int: 传统文件拖放通知消息（``HDROP`` 载荷；配合消息过滤器即可穿透 UIPI）。"""

WM_COPYDATA = 0x004A
"""int: 跨进程数据拷贝消息（提权进程需显式放开过滤器才能收到）。"""

WM_COPYGLOBALDATA = 0x0049
"""int: shell 向高完整性进程传递全局内存（HDROP 数据）依赖的私有消息。"""

MSGFLT_ALLOW = 1
"""int: ``ChangeWindowMessageFilterEx`` 的「放行」动作常量。"""

_ELEVATED_DROP_MESSAGES: tuple[int, ...] = (
    WM_DROPFILES,
    WM_COPYDATA,
    WM_COPYGLOBALDATA,
)
"""tuple: 需要为提权进程放开 UIPI 过滤器的消息集合。"""

_DRAG_FILE_COUNT_INDEX = 0xFFFFFFFF
"""int: ``DragQueryFileW`` 查询文件总数的 ``iFile`` 特殊值。"""

_IS_WINDOWS = sys.platform == "win32"
"""bool: 非 Windows 平台整体退化为空操作（导入安全、``nativeEvent`` 透传）。"""


class _DROPFILES(ctypes.Structure):
    """``DROPFILES`` 头结构（Python 3.9 的 ``ctypes.wintypes`` 未提供）。

    Attributes:
        pFiles: 文件路径列表相对本结构起始地址的字节偏移。
        pt: 拖拽起始鼠标位置（``fNC`` 为真时为屏幕坐标）。
        fNC: 落点是否位于非客户区。
        fWide: 路径列表是否为 UTF-16（``True`` 时用 ``DragQueryFileW`` 读取）。
    """

    _fields_ = (
        ("pFiles", wintypes.DWORD),
        ("pt", wintypes.POINT),
        ("fNC", wintypes.BOOL),
        ("fWide", wintypes.BOOL),
    )


_ole32: Optional[Any] = None
_user32: Optional[Any] = None
_shell32: Optional[Any] = None
_kernel32: Optional[Any] = None


def _load_native_libraries() -> bool:
    """惰性加载 ole32 / user32 / shell32 / kernel32 并声明函数原型（幂等）。

    Returns:
        bool: 加载成功返回 ``True``；非 Windows 或加载失败返回 ``False``
        （调用方一律退化为空操作，绝不抛出）。
    """
    global _ole32, _user32, _shell32, _kernel32
    if not _IS_WINDOWS:
        return False
    if _ole32 is not None:
        return True
    try:
        ole32 = ctypes.WinDLL("ole32", use_last_error=True)
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        # 撤销 OLE 投放目标必须在 DragAcceptFiles 之前（否则收不到 WM_DROPFILES）
        ole32.RevokeDragDrop.argtypes = [wintypes.HWND]
        ole32.RevokeDragDrop.restype = ctypes.c_long

        user32.ChangeWindowMessageFilterEx.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.DWORD,
            ctypes.c_void_p,
        ]
        user32.ChangeWindowMessageFilterEx.restype = wintypes.BOOL
        user32.ScreenToClient.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.POINT),
        ]
        user32.ScreenToClient.restype = wintypes.BOOL

        # shellapi.h 系列（DragAcceptFiles/DragQuery*）由 shell32 导出，不在 user32
        shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
        shell32.DragAcceptFiles.restype = None
        shell32.DragQueryPoint.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.POINT),
        ]
        shell32.DragQueryPoint.restype = wintypes.BOOL
        shell32.DragQueryFileW.argtypes = [
            wintypes.HANDLE,
            wintypes.UINT,
            wintypes.LPWSTR,
            wintypes.UINT,
        ]
        shell32.DragQueryFileW.restype = wintypes.UINT
        shell32.DragFinish.argtypes = [wintypes.HANDLE]
        shell32.DragFinish.restype = None

        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.restype = wintypes.BOOL
    except (OSError, AttributeError) as exc:
        warning(f"[elevated_drop] 原生库加载失败，兜底停用：{exc}")
        _ole32 = _user32 = _shell32 = _kernel32 = None
        return False
    _ole32, _user32, _shell32, _kernel32 = ole32, user32, shell32, kernel32
    return True


def _revoke_drag_drop(hwnd: int) -> bool:
    """撤销窗口的 OLE 投放目标注册（``RevokeDragDrop``，ole32）。

    Args:
        hwnd: 目标顶层窗口句柄。

    Returns:
        bool: 成功返回 ``True``；未注册 / 失败返回 ``False``（仅日志）。
    """
    if not _load_native_libraries() or not hwnd:
        return False
    try:
        result = int(_ole32.RevokeDragDrop(wintypes.HWND(hwnd)))
    except (OSError, TypeError, ValueError) as exc:
        debug(f"[elevated_drop] RevokeDragDrop 失败：{exc}")
        return False
    if result != 0:
        debug(f"[elevated_drop] RevokeDragDrop 返回 0x{result & 0xFFFFFFFF:08x}")
        return False
    return True


def _drag_accept_files(hwnd: int, accept: bool) -> None:
    """注册 / 注销窗口为传统 ``WM_DROPFILES`` 拖放目标（``DragAcceptFiles``）。

    Args:
        hwnd: 目标顶层窗口句柄。
        accept: ``True`` 注册、``False`` 注销。
    """
    if not _load_native_libraries() or not hwnd:
        return
    try:
        _shell32.DragAcceptFiles(wintypes.HWND(hwnd), bool(accept))
    except (OSError, TypeError, ValueError) as exc:
        debug(f"[elevated_drop] DragAcceptFiles 失败：{exc}")


def _allow_dropped_message(hwnd: int, message_id: int) -> bool:
    """放开 UIPI 对指定消息的过滤器（``ChangeWindowMessageFilterEx``）。

    Args:
        hwnd: 目标顶层窗口句柄。
        message_id: 要放行的消息常量（``WM_DROPFILES`` 等）。

    Returns:
        bool: 放行成功返回 ``True``；失败返回 ``False``（仅日志）。
    """
    if not _load_native_libraries() or not hwnd:
        return False
    try:
        ok = bool(
            _user32.ChangeWindowMessageFilterEx(
                wintypes.HWND(hwnd),
                message_id,
                MSGFLT_ALLOW,
                None,
            )
        )
    except (OSError, TypeError, ValueError) as exc:
        debug(f"[elevated_drop] ChangeWindowMessageFilterEx 失败：{exc}")
        return False
    if not ok:
        debug(
            "[elevated_drop] ChangeWindowMessageFilterEx 返回失败："
            f"msg=0x{message_id:04x} err={ctypes.get_last_error()}"
        )
    return ok


def _resolve_client_drop_point(hdrop: int, hwnd: int) -> tuple[int, int]:
    """解析落点（目标窗口客户区物理像素坐标）。

    优先 ``DragQueryPoint``（shell 已按接收窗口换算为客户区坐标）；失败
    （FALSE，通常是非客户区落点）时退回读取 ``DROPFILES.pt``：``fNC`` 为真
    时其为屏幕坐标，经 ``ScreenToClient`` 换算。全部失败返回 ``(0, 0)``。

    Args:
        hdrop: ``WM_DROPFILES`` 的 ``HDROP`` 句柄。
        hwnd: 接收窗口句柄（回退路径换算屏幕坐标用）。

    Returns:
        tuple[int, int]: 客户区物理像素 ``(x, y)``。
    """
    if not _load_native_libraries() or not hdrop:
        return (0, 0)
    point = wintypes.POINT()
    try:
        if _shell32.DragQueryPoint(wintypes.HANDLE(hdrop), ctypes.byref(point)):
            return (int(point.x), int(point.y))
    except (OSError, TypeError, ValueError) as exc:
        debug(f"[elevated_drop] DragQueryPoint 失败：{exc}")
    # 回退：读取 DROPFILES.pt（GMEM 句柄须先 GlobalLock 才能解引用）
    try:
        pointer = _kernel32.GlobalLock(wintypes.HGLOBAL(hdrop))
        if not pointer:
            return (0, 0)
        try:
            drop_files = _DROPFILES.from_address(pointer)
            fallback = wintypes.POINT(int(drop_files.pt.x), int(drop_files.pt.y))
            is_non_client = bool(drop_files.fNC)
        finally:
            _kernel32.GlobalUnlock(wintypes.HGLOBAL(hdrop))
        if is_non_client and hwnd:
            if not _user32.ScreenToClient(wintypes.HWND(hwnd), ctypes.byref(fallback)):
                return (0, 0)
        return (int(fallback.x), int(fallback.y))
    except (OSError, TypeError, ValueError) as exc:
        debug(f"[elevated_drop] DROPFILES 回退解析失败：{exc}")
        return (0, 0)


def _query_drop_paths(hdrop: int) -> list[str]:
    """读取 ``HDROP`` 中的全部本地路径（``DragQueryFileW``）。

    Args:
        hdrop: ``WM_DROPFILES`` 的 ``HDROP`` 句柄。

    Returns:
        list[str]: 解析出的路径列表；失败或为空时返回空列表。
    """
    if not _load_native_libraries() or not hdrop:
        return []
    paths: list[str] = []
    for index in range(_drag_query_file_count(hdrop)):
        file_path = _drag_query_file_path(hdrop, index)
        if file_path:
            paths.append(file_path)
    return paths


def _drag_query_file_count(hdrop: int) -> int:
    """查询 ``HDROP`` 中的文件总数（``iFile = 0xFFFFFFFF``）。

    Args:
        hdrop: ``WM_DROPFILES`` 的 ``HDROP`` 句柄。

    Returns:
        int: 文件总数；失败返回 ``0``。
    """
    try:
        return int(
            _shell32.DragQueryFileW(
                wintypes.HANDLE(hdrop), _DRAG_FILE_COUNT_INDEX, None, 0
            )
        )
    except (OSError, TypeError, ValueError) as exc:
        debug(f"[elevated_drop] DragQueryFileW(count) 失败：{exc}")
        return 0


def _drag_query_file_path(hdrop: int, index: int) -> str:
    """读取 ``HDROP`` 中第 ``index`` 个文件的路径（``DragQueryFileW``）。

    Args:
        hdrop: ``WM_DROPFILES`` 的 ``HDROP`` 句柄。
        index: 以 0 起始的文件序号。

    Returns:
        str: 路径字符串；越界 / 失败返回空串。
    """
    try:
        length = int(_shell32.DragQueryFileW(wintypes.HANDLE(hdrop), index, None, 0))
        if length <= 0:
            return ""
        buffer = ctypes.create_unicode_buffer(length + 1)
        written = int(
            _shell32.DragQueryFileW(
                wintypes.HANDLE(hdrop), index, buffer, length + 1
            )
        )
        if written <= 0:
            return ""
        return buffer.value
    except (OSError, TypeError, ValueError) as exc:
        debug(f"[elevated_drop] DragQueryFileW(path, {index}) 失败：{exc}")
        return ""


def _drag_finish(hdrop: int) -> None:
    """释放 ``HDROP`` 句柄（``DragFinish``；处理完成后必须调用）。

    Args:
        hdrop: ``WM_DROPFILES`` 的 ``HDROP`` 句柄。
    """
    if not _load_native_libraries() or not hdrop:
        return
    try:
        _shell32.DragFinish(wintypes.HANDLE(hdrop))
    except (OSError, TypeError, ValueError) as exc:
        debug(f"[elevated_drop] DragFinish 失败：{exc}")


class ElevatedDropFallbackMixin:
    """提权进程下的原生 ``WM_DROPFILES`` 拖入兜底 Mixin。

    宿主类须把本 Mixin 排在 Qt 基类之外层（``class Host(ElevatedDropFallbackMixin,
    ...)``），并让普通类的 ``nativeEvent`` 位于其后：Mixin 只拦截
    ``WM_DROPFILES``，其余消息（``WM_NCCALCSIZE`` / ``WM_NCHITTEST`` 等无边框
    依赖的消息）一律立即交回 ``super().nativeEvent``，逐条委托不引入任何行为
    变化。

    安装时机（自门控；未提权时零原生调用）：

    - ``showEvent``：窗口首次显示、HWND 建立后安装；
    - ``event()`` 捕获 ``QEvent.Type.WinIdChange``：GPU 表面导致 HWND 重建时
      强制重装（注册状态随旧 HWND 一起丢失）。

    宿主可覆写两个业务钩子：

    - :meth:`_elevated_drop_accepts_point`：落点命中测试（Qt 逻辑坐标），返回
      ``False`` 时丢弃该次拖放（仍 ``DragFinish``）；
    - :meth:`_elevated_drop_accept_paths`：接收通过命中测试的路径列表。

    Attributes:
        _elevated_drop_installed: 是否已安装（类级默认 ``False``，未安装时
            ``nativeEvent`` 纯透传）。
        _elevated_drop_hwnd: 已安装 / 已放行的目标 HWND；``0`` 表示未安装。
    """

    #: 类级默认：未安装时 nativeEvent 完全透传（零开销、零行为变化）。
    _elevated_drop_installed: bool = False
    #: 已接管的目标 HWND（``0`` 表示尚未安装）。
    _elevated_drop_hwnd: int = 0

    # ── Qt 事件钩子 ─────────────────────────────────────────────

    def showEvent(self, event: QShowEvent) -> None:
        """窗口显示时尝试安装原生兜底（幂等）。

        Args:
            event: 显示事件（先交回基类，保持既有链路顺序）。
        """
        super().showEvent(event)
        self._install_elevated_drop_fallback()

    def event(self, event: QEvent) -> bool:
        """``WinIdChange`` 后强制重装兜底（HWND 重建会丢失注册状态）。

        Args:
            event: 事件对象。

        Returns:
            bool: 交回基类的处理结果。
        """
        if event.type() == QEvent.Type.WinIdChange:
            self._install_elevated_drop_fallback(force=True)
        return super().event(event)

    def nativeEvent(self, eventType: bytes, message: int) -> tuple[bool, int]:
        """拦截 ``WM_DROPFILES``；未安装或其它消息一律透传。

        Args:
            eventType: Qt 原生事件类型（Windows 上为 ``b"windows_generic_MSG"``
                或 ``b"windows_dispatcher_MSG"``）。
            message: ``MSG`` 指针地址。

        Returns:
            tuple[bool, int]: ``(是否已处理, 处理结果)``。
        """
        if self._elevated_drop_installed and eventType in (
            b"windows_generic_MSG",
            b"windows_dispatcher_MSG",
        ):
            try:
                msg = wintypes.MSG.from_address(int(message))
            except (TypeError, ValueError) as exc:
                debug(f"[elevated_drop] MSG 解析失败，透传：{exc}")
                return super().nativeEvent(eventType, message)
            if msg.message == WM_DROPFILES:
                try:
                    self._handle_wm_dropfiles(int(msg.wParam))
                except Exception as exc:  # noqa: BLE001 - 绝不穿透回 Qt 回调
                    warning(f"[elevated_drop] WM_DROPFILES 处理失败：{exc}")
                return True, 0
        return super().nativeEvent(eventType, message)

    # ── 安装 / 处理 ─────────────────────────────────────────────

    def _install_elevated_drop_fallback(self, force: bool = False) -> None:
        """（幂等）安装原生兜底：RevokeDragDrop → DragAcceptFiles → 消息过滤器。

        仅「Windows + 提权进程 + 已有 HWND」下执行；任何一步失败都只记日志，
        绝不抛出（安装失败保持未安装状态，行为与普通非提权路径一致）。

        Args:
            force: ``True`` 时即使已安装也重跑原生调用（``WinIdChange`` 重建
                场景；HWND 已更换，旧注册已随旧窗口丢失）。
        """
        if not _IS_WINDOWS:
            return
        if self._elevated_drop_installed and not force:
            return
        try:
            if not elevation.is_process_elevated():
                return
        except Exception as exc:  # noqa: BLE001 - 检测失败按「未提权」处理
            debug(f"[elevated_drop] 提权检测失败，跳过兜底：{exc}")
            return
        hwnd = int(self.internalWinId() or 0)
        if not hwnd:
            return
        # 顺序不可交换：有 OLE 注册时窗口收不到 WM_DROPFILES
        _revoke_drag_drop(hwnd)
        _drag_accept_files(hwnd, True)
        allowed = 0
        for message_id in _ELEVATED_DROP_MESSAGES:
            if _allow_dropped_message(hwnd, message_id):
                allowed += 1
        self._elevated_drop_hwnd = hwnd
        self._elevated_drop_installed = True
        info(
            "[elevated_drop] 已安装 WM_DROPFILES 兜底："
            f"hwnd=0x{hwnd:x} "
            f"filter_allowed={allowed}/{len(_ELEVATED_DROP_MESSAGES)}"
        )

    def _handle_wm_dropfiles(self, hdrop: int) -> None:
        """解析 ``HDROP`` → 命中测试 → 路由路径；任何路径都保证 ``DragFinish``。

        Args:
            hdrop: ``WM_DROPFILES`` 的 ``HDROP`` 句柄。
        """
        if not hdrop:
            return
        try:
            physical = _resolve_client_drop_point(hdrop, self._elevated_drop_hwnd)
            try:
                ratio = float(self.devicePixelRatioF()) or 1.0
            except (TypeError, ValueError):
                ratio = 1.0
            logical_x = int(round(physical[0] / ratio))
            logical_y = int(round(physical[1] / ratio))
            if not self._elevated_drop_accepts_point(logical_x, logical_y):
                debug(
                    "[elevated_drop] 落点未命中接收区，丢弃："
                    f"logical=({logical_x}, {logical_y})"
                )
                return
            paths = _query_drop_paths(hdrop)
            if not paths:
                debug("[elevated_drop] HDROP 未解析出路径，忽略")
                return
            debug(f"[elevated_drop] 路由 {len(paths)} 条路径：{paths}")
            self._elevated_drop_accept_paths(paths)
        finally:
            _drag_finish(hdrop)

    # ── 宿主业务钩子 ─────────────────────────────────────────────

    def _elevated_drop_accepts_point(self, x: int, y: int) -> bool:
        """落点命中测试（宿主窗口客户区 Qt 逻辑坐标）。

        默认一律接受（宿主按需覆写，如主窗口只接受文件池区域）。

        Args:
            x: 客户区逻辑 X 坐标。
            y: 客户区逻辑 Y 坐标。

        Returns:
            bool: ``True`` 接受该次拖放。
        """
        return True

    def _elevated_drop_accept_paths(self, paths: list[str]) -> None:
        """接收通过命中测试的路径列表（宿主必须覆写才有实际效果）。

        Args:
            paths: 解析出的本地路径列表（已通过命中测试）。
        """
