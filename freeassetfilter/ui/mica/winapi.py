"""Windows 原生采集原语 —— COM/DXGI/GDI/SystemParametersInfo 的薄封装。

本模块只做三件事，且**不依赖 Qt / numpy**，可在无显示环境下安全导入：

1. :class:`DesktopWallpaperCom` —— ``IDesktopWallpaper``（Win8+ Shell COM，
   **不是 DWM**）：按显示器读取壁纸路径、纯色背景色与放置方式。这是
   Win11 下唯一能正确拿到"每显示器异图"与"纯色壁纸"的官方 API。
2. :func:`capture_desktop_dxgi` —— DXGI 桌面复制（``IDXGIOutputDuplication``
   + D3D11 暂存纹理回读）：抓取屏幕**实际呈现的像素**，用于 Windows 焦点 /
   幻灯片 / 动态壁纸 / 纯色等拿不到壁纸文件的场景。
3. :func:`capture_desktop_gdi` —— GDI ``BitBlt`` 抓屏兜底：零 COM 风险，
   任何 Windows 版本可用。

稳定性约定
----------
* 所有 COM 调用都走 :class:`ComPtr` + HRESULT 校验，任一环节失败即抛出
  :class:`CaptureError`，由上层降级到下一个后端。
* DXGI / D3D11 的 vtable 索引全部以常量集中声明并注明来源，便于审计。
* 模块导入不执行任何 COM 初始化；:func:`ensure_com` 惰性且幂等。

非 Windows 平台（或 32/64 位缺失 DLL）下所有探测函数返回不可用，不会抛异常。
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# 平台守卫
# ---------------------------------------------------------------------------

IS_WINDOWS: bool = sys.platform == "win32"


class CaptureError(RuntimeError):
    """采集后端失败（COM 调用返回失败 HRESULT / DLL 缺失 / 超时等）。"""


if IS_WINDOWS:  # pragma: no cover - 仅在 Windows 下定义
    _ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
else:  # pragma: no cover - 非 Windows 占位，保证模块可导入
    _ole32 = _user32 = _gdi32 = _kernel32 = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# COM 基础
# ---------------------------------------------------------------------------

S_OK: int = 0
S_FALSE: int = 1
E_FAIL: int = -2147467259          # 0x80004005
E_INVALIDARG: int = -2147024809    # 0x80070057
E_OUTOFMEMORY: int = -2147024882   # 0x8007000E
CLSCTX_LOCAL_SERVER: int = 0x4
CLSCTX_INPROC_SERVER: int = 0x1

# 注意：ctypes 在 ``restype`` 为真正的 ``HRESULT`` 时会对失败码**自动抛出 OSError**，
# 这会打断依赖 "hr != S_OK 即终止" 的枚举循环（如 EnumOutputs / AcquireNextFrame），
# 使上层误判为崩溃而非"取完了"。因此本模块统一用带符号 32 位整数接收 HRESULT
# （64 位 Windows 上 HRESULT 本就是 32 位 LONG），由调用方显式 succeeded() 判断。
#
# 必须在下面的 ``argtypes/restype`` 声明之前定义，否则模块导入即 NameError。
_HRESULT = ctypes.c_long


class GUID(ctypes.Structure):
    """COM ``GUID`` 结构，支持由 ``"{...}"`` 字符串构造。"""

    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    def __init__(self, text: str = "") -> None:
        super().__init__()
        if text:
            _ole32.IIDFromString(text, ctypes.byref(self))

    def __str__(self) -> str:  # pragma: no cover - 仅调试用
        return "{%08X-%04X-%04X-%s}" % (
            self.Data1,
            self.Data2,
            self.Data3,
            "".join("%02X" % b for b in self.Data4),
        )


if IS_WINDOWS:  # pragma: no cover
    _ole32.IIDFromString.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(GUID)]
    _ole32.IIDFromString.restype = _HRESULT
    _ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    _ole32.CoTaskMemFree.restype = None
    _ole32.CoInitialize.argtypes = [ctypes.c_void_p]
    _ole32.CoInitialize.restype = _HRESULT
    _ole32.CoCreateInstance.argtypes = [
        ctypes.POINTER(GUID),
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    _ole32.CoCreateInstance.restype = _HRESULT


def succeeded(hr: int) -> bool:
    """判断 HRESULT 是否成功（``SUCCEEDED`` 宏等价物）。"""
    return int(hr) >= 0


def ensure_com() -> bool:
    """幂等初始化调用线程的 COM（单线程套间）。

    Returns:
        成功（含"本线程已初始化"的 ``S_FALSE``）返回 True；非 Windows 或
        初始化失败返回 False。
    """
    if not IS_WINDOWS:
        return False
    try:
        hr = _ole32.CoInitialize(None)
        return succeeded(hr)
    except (AttributeError, OSError):
        return False


def _co_task_mem_free(ptr: int) -> None:
    """释放 COM 任务分配器分配的内存（``GetWallpaper`` 返回的字符串）。"""
    if ptr and IS_WINDOWS:
        _ole32.CoTaskMemFree(ctypes.c_void_p(ptr))


class ComPtr:
    """极简 COM 接口指针包装：vtable 索引调用 + ``Release`` 生命周期。

    只实现本项目所需的调用能力（无 AddRef 语义、不做引用计数转移），
    析构时释放。所有 vtable 索引由调用方以具名常量传入。
    """

    __slots__ = ("_ptr", "_released")

    def __init__(self, ptr: Optional[int]) -> None:
        self._ptr = ctypes.c_void_p(ptr or 0)
        self._released = not bool(ptr)

    @property
    def ptr(self) -> Optional[ctypes.c_void_p]:
        """底层接口指针（已释放时为 ``None``）。"""
        return None if self._released else self._ptr

    def valid(self) -> bool:
        """接口指针是否有效。"""
        return not self._released and bool(self._ptr.value)

    def method(self, index: int, restype, *argtypes):
        """取出第 ``index`` 号虚方法并绑定为可调用对象。

        Args:
            index: vtable 索引（0/1/2 为 IUnknown 的 QI/AddRef/Release）。
            restype: 返回值 ctypes 类型。
            *argtypes: 除 ``this`` 之外的参数类型。

        Returns:
            可直接调用的 ctypes 函数对象（首参为 ``this``）。
        """
        if not self.valid():
            raise CaptureError("COM 接口指针已释放")
        vtbl = ctypes.cast(self._ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))
        addr = vtbl.contents[index]
        if not addr:
            raise CaptureError(f"vtable[{index}] 为空")
        proto = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
        return proto(addr)

    def query_interface(self, iid: "GUID") -> "ComPtr":
        """``IUnknown::QueryInterface``（vtable 索引 0）。

        Args:
            iid: 目标接口 IID。

        Returns:
            新的 :class:`ComPtr`；失败时其 ``valid()`` 为 False。
        """
        out = ctypes.c_void_p()
        fn = self.method(0, _HRESULT, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))
        hr = fn(self._ptr, ctypes.byref(iid), ctypes.byref(out))
        if not succeeded(hr) or not out.value:
            return ComPtr(None)
        return ComPtr(out.value)

    def release(self) -> None:
        """``IUnknown::Release``（vtable 索引 2），幂等。"""
        if self._released:
            return
        self._released = True
        try:
            if self._ptr.value:
                fn = self.method(2, ctypes.c_ulong)
                fn(self._ptr)
        except (CaptureError, OSError, ValueError):
            pass
        self._ptr = ctypes.c_void_p(0)

    def __del__(self) -> None:  # pragma: no cover - 析构路径
        try:
            self.release()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# IDesktopWallpaper（Shell COM，非 DWM）
# ---------------------------------------------------------------------------

CLSID_DESKTOP_WALLPAPER: str = "{C2CF3110-460E-4FC1-B9D0-8A1C0C9CC4BD}"
IID_DESKTOP_WALLPAPER: str = "{B92B56A9-8B55-4E14-9A89-0199BBB6F93B}"

# vtable 索引（IUnknown 占 0/1/2，其后按 shobjidl_core.h 中的声明顺序）
_DW_GET_WALLPAPER = 4
_DW_GET_MONITOR_DEVICE_PATH_AT = 5
_DW_GET_MONITOR_DEVICE_PATH_COUNT = 6
_DW_GET_MONITOR_RECT = 7
_DW_GET_BACKGROUND_COLOR = 9
_DW_GET_POSITION = 11

#: ``DESKTOP_WALLPAPER_POSITION`` 枚举 → 可读放置方式。
_WALLPAPER_POSITIONS: Tuple[str, ...] = (
    "Center",    # 0 DWPOS_CENTER
    "Tile",      # 1 DWPOS_TILE
    "Stretch",   # 2 DWPOS_STRETCH
    "Fit",       # 3 DWPOS_FIT
    "Fill",      # 4 DWPOS_FILL
    "Span",      # 5 DWPOS_SPAN
)


def _colorref_to_rgb(colorref: int) -> Tuple[int, int, int]:
    """``COLORREF``（0x00BBGGRR）→ ``(r, g, b)``。"""
    return (
        int(colorref) & 0xFF,
        (int(colorref) >> 8) & 0xFF,
        (int(colorref) >> 16) & 0xFF,
    )


class DesktopWallpaperCom:
    """``IDesktopWallpaper`` 封装：每显示器壁纸路径 / 背景色 / 放置方式。

    典型用法::

        dw = DesktopWallpaperCom.create()
        if dw:
            for i in range(dw.monitor_count()):
                mid = dw.monitor_id(i)
                path = dw.wallpaper(mid)
                rect = dw.monitor_rect(mid)
    """

    __slots__ = ("_itf",)

    def __init__(self, itf: ComPtr) -> None:
        self._itf = itf

    @classmethod
    def create(cls) -> Optional["DesktopWallpaperCom"]:
        """创建 COM 实例；不可用（非 Win8+ / COM 失败）时返回 ``None``。

        Returns:
            实例或 ``None``。
        """
        if not IS_WINDOWS or not ensure_com():
            return None
        try:
            clsid = GUID(CLSID_DESKTOP_WALLPAPER)
            iid = GUID(IID_DESKTOP_WALLPAPER)
            out = ctypes.c_void_p()
            hr = _ole32.CoCreateInstance(
                ctypes.byref(clsid),
                None,
                CLSCTX_LOCAL_SERVER,
                ctypes.byref(iid),
                ctypes.byref(out),
            )
            if not succeeded(hr) or not out.value:
                return None
            return cls(ComPtr(out.value))
        except (OSError, ValueError, CaptureError):
            return None

    def close(self) -> None:
        """释放底层接口。"""
        self._itf.release()

    # -- 显示器枚举 ---------------------------------------------------------

    def monitor_count(self) -> int:
        """显示器数量；失败返回 0。"""
        try:
            fn = self._itf.method(
                _DW_GET_MONITOR_DEVICE_PATH_COUNT, _HRESULT, ctypes.POINTER(ctypes.c_uint)
            )
            count = ctypes.c_uint(0)
            hr = fn(self._itf.ptr, ctypes.byref(count))
            return int(count.value) if succeeded(hr) else 0
        except (CaptureError, OSError):
            return 0

    def monitor_id(self, index: int) -> str:
        """第 ``index`` 台显示器的设备路径（``IDesktopWallpaper`` 的 monitorID）。

        Args:
            index: 0 基索引。

        Returns:
            设备路径字符串；失败返回空串。
        """
        try:
            fn = self._itf.method(
                _DW_GET_MONITOR_DEVICE_PATH_AT,
                _HRESULT,
                ctypes.c_uint,
                ctypes.POINTER(ctypes.c_void_p),
            )
            out = ctypes.c_void_p()
            hr = fn(self._itf.ptr, ctypes.c_uint(int(index)), ctypes.byref(out))
            if not succeeded(hr) or not out.value:
                return ""
            text = ctypes.wstring_at(out.value)
            _co_task_mem_free(out.value)
            return text
        except (CaptureError, OSError):
            return ""

    def monitor_rect(self, monitor_id: str) -> Optional[Tuple[int, int, int, int]]:
        """显示器的虚拟桌面矩形 ``(left, top, right, bottom)``（**物理像素**）。

        Args:
            monitor_id: :meth:`monitor_id` 返回的设备路径。

        Returns:
            ``(l, t, r, b)``；失败返回 ``None``。
        """
        try:
            fn = self._itf.method(
                _DW_GET_MONITOR_RECT, _HRESULT, ctypes.c_wchar_p, ctypes.POINTER(wintypes.RECT)
            )
            rect = wintypes.RECT()
            hr = fn(self._itf.ptr, monitor_id, ctypes.byref(rect))
            if not succeeded(hr):
                return None
            return (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
        except (CaptureError, OSError):
            return None

    # -- 壁纸与背景 ---------------------------------------------------------

    def wallpaper(self, monitor_id: str = "") -> str:
        """指定显示器（或全局）的壁纸文件路径。

        Args:
            monitor_id: 设备路径；空串表示全局默认。

        Returns:
            文件路径；无壁纸（纯色）或失败时返回空串。
        """
        try:
            fn = self._itf.method(
                _DW_GET_WALLPAPER,
                _HRESULT,
                ctypes.c_wchar_p,
                ctypes.POINTER(ctypes.c_void_p),
            )
            out = ctypes.c_void_p()
            hr = fn(self._itf.ptr, monitor_id or None, ctypes.byref(out))
            if not succeeded(hr) or not out.value:
                return ""
            text = ctypes.wstring_at(out.value)
            _co_task_mem_free(out.value)
            return text
        except (CaptureError, OSError):
            return ""

    def background_color(self) -> Optional[Tuple[int, int, int]]:
        """纯色壁纸的背景色 ``(r, g, b)``；失败返回 ``None``。"""
        try:
            fn = self._itf.method(
                _DW_GET_BACKGROUND_COLOR, _HRESULT, ctypes.POINTER(wintypes.DWORD)
            )
            value = wintypes.DWORD(0)
            hr = fn(self._itf.ptr, ctypes.byref(value))
            return _colorref_to_rgb(value.value) if succeeded(hr) else None
        except (CaptureError, OSError):
            return None

    def position(self) -> str:
        """壁纸放置方式；失败时回退 ``"Fill"``。"""
        try:
            fn = self._itf.method(_DW_GET_POSITION, ctypes.c_int)
            value = int(fn(self._itf.ptr))
            if 0 <= value < len(_WALLPAPER_POSITIONS):
                return _WALLPAPER_POSITIONS[value]
        except (CaptureError, OSError):
            pass
        return "Fill"


# ---------------------------------------------------------------------------
# GDI 抓屏（零 COM 风险兜底）
# ---------------------------------------------------------------------------

SRCCOPY: int = 0x00CC0020
CAPTUREBLT: int = 0x40000000
DIB_RGB_COLORS: int = 0
SM_XVIRTUALSCREEN: int = 76
SM_YVIRTUALSCREEN: int = 77
SM_CXVIRTUALSCREEN: int = 78
SM_CYVIRTUALSCREEN: int = 79


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


def virtual_screen_rect() -> Tuple[int, int, int, int]:
    """虚拟桌面矩形 ``(x, y, w, h)``（物理像素，进程 DPI 感知下的取值）。"""
    if not IS_WINDOWS:
        return (0, 0, 0, 0)
    x = _user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    y = _user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    w = _user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    h = _user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    return (int(x), int(y), int(w), int(h))


if IS_WINDOWS:  # pragma: no cover
    _user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _user32.GetWindowRect.restype = ctypes.c_int


def window_rect(hwnd: int) -> Tuple[int, int, int, int]:
    """取得窗口的外矩形 ``(x, y, w, h)``（物理像素，与 :func:`virtual_screen_rect` 同坐标系）。

    壁纸源画布以 Win32 虚拟桌面物理像素为坐标基准，因此采样窗口矩形必须同样取自
    Win32（``GetWindowRect``），而**不能**用 Qt 的逻辑像素几何（二者在 DPI 感知进程里
    相差一个 devicePixelRatio）。两者同属 Win32 坐标系，无论进程是否开启 DPI 感知都
    严格对齐。失败时返回 ``(0, 0, 0, 0)``。

    Args:
        hwnd: 窗口句柄（``QWidget.winId()``）。

    Returns:
        ``(x, y, w, h)`` 物理像素矩形。
    """
    if not IS_WINDOWS or not hwnd:
        return (0, 0, 0, 0)
    rect = wintypes.RECT()
    if not _user32.GetWindowRect(int(hwnd), ctypes.byref(rect)):
        return (0, 0, 0, 0)
    return (
        int(rect.left),
        int(rect.top),
        int(rect.right - rect.left),
        int(rect.bottom - rect.top),
    )


def capture_desktop_gdi(
    rect: Optional[Tuple[int, int, int, int]] = None,
) -> Optional[bytes]:
    """以 GDI ``BitBlt`` 抓取桌面区域，返回 BGRA 原始字节（自顶向下）。

    Args:
        rect: ``(x, y, w, h)`` 物理像素矩形；``None`` 表示整个虚拟桌面。

    Returns:
        长度 ``w * h * 4`` 的 ``bytes``（BGRA，首行为顶行）；失败返回 ``None``。

    Raises:
        CaptureError: 非 Windows 平台。
    """
    if not IS_WINDOWS:
        raise CaptureError("GDI 抓屏仅支持 Windows")
    vx, vy, vw, vh = virtual_screen_rect()
    if rect is None:
        rect = (vx, vy, vw, vh)
    x, y, w, h = (int(v) for v in rect)
    w = max(1, min(w, vw))
    h = max(1, min(h, vh))

    screen_dc = _user32.GetDC(None)
    if not screen_dc:
        raise CaptureError("GetDC(NULL) 失败")
    mem_dc = None
    bitmap = None
    try:
        mem_dc = _gdi32.CreateCompatibleDC(screen_dc)
        if not mem_dc:
            raise CaptureError("CreateCompatibleDC 失败")
        bitmap = _gdi32.CreateCompatibleBitmap(screen_dc, w, h)
        if not bitmap:
            raise CaptureError("CreateCompatibleBitmap 失败")
        old = _gdi32.SelectObject(mem_dc, bitmap)
        try:
            if not _gdi32.BitBlt(mem_dc, 0, 0, w, h, screen_dc, x, y, SRCCOPY | CAPTUREBLT):
                raise CaptureError("BitBlt 失败")
        finally:
            if old:
                _gdi32.SelectObject(mem_dc, old)

        bmi = _BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        # 负高度 ⇒ 自顶向下 DIB，省去逐行翻转
        bmi.bmiHeader.biHeight = -h
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0  # BI_RGB

        buf = ctypes.create_string_buffer(w * h * 4)
        lines = _gdi32.GetDIBits(
            mem_dc, bitmap, 0, h, buf, ctypes.byref(bmi), DIB_RGB_COLORS
        )
        if lines != h:
            raise CaptureError(f"GetDIBits 返回 {lines} 行，期望 {h} 行")
        return bytes(buf)
    finally:
        if bitmap:
            _gdi32.DeleteObject(bitmap)
        if mem_dc:
            _gdi32.DeleteDC(mem_dc)
        _user32.ReleaseDC(None, screen_dc)


# ---------------------------------------------------------------------------
# DXGI 桌面复制（可选后端）
# ---------------------------------------------------------------------------

IID_IDXGIFACTORY1: str = "{770AAE78-F26F-4DBA-A829-253C83D1B387}"
IID_IDXGIOUTPUT1: str = "{00CDDEA8-939B-4B83-A340-A685226666CC}"
IID_ID3D11TEXTURE2D: str = "{6F15AAF2-D208-4E89-9AB4-489535D34F9C}"

# IDXGIFactory1 vtable：IUnknown(0-2) + IDXGIObject(3-6) + IDXGIFactory(7-11)
_XGI_FACTORY1_ENUM_ADAPTERS1 = 12
# IDXGIAdapter1 vtable：IUnknown(0-2) + IDXGIObject(3-6) + IDXGIAdapter(7-9)
_XGI_ADAPTER1_ENUM_OUTPUTS = 7
# IDXGIOutput1 vtable：IUnknown(0-2) + IDXGIObject(3-6) + IDXGIOutput(7-17)
_XGI_OUTPUT1_DUPLICATE_OUTPUT = 21
# IDXGIOutputDuplication vtable：IUnknown(0-2) + IDXGIObject(3-6)
_XGI_DUP_ACQUIRE_NEXT_FRAME = 8
_XGI_DUP_RELEASE_FRAME = 14
# ID3D11Device vtable（IUnknown 之后）
_D3D11_CREATE_TEXTURE2D = 5
_D3D11_GET_IMMEDIATE_CONTEXT = 40
# ID3D11DeviceContext vtable（IUnknown + ID3D11DeviceChild 之后）
_D3D11_CTX_MAP = 14
_D3D11_CTX_UNMAP = 15
_D3D11_CTX_COPY_RESOURCE = 47

DXGI_FORMAT_B8G8R8A8_UNORM: int = 87
D3D11_USAGE_STAGING: int = 3
D3D11_CPU_ACCESS_READ: int = 0x20000
D3D11_MAP_READ: int = 1
D3D11_CREATE_DEVICE_BGRA_SUPPORT: int = 0x20
D3D_FEATURE_LEVEL_11_0: int = 0xB000
D3D11_SDK_VERSION: int = 7
D3D_DRIVER_TYPE_HARDWARE: int = 1

DXGI_ERROR_WAIT_TIMEOUT: int = 0x887A0027
DXGI_ERROR_ACCESS_LOST: int = 0x887A0026
DXGI_ERROR_UNSUPPORTED: int = 0x887A0004
DXGI_ERROR_NOT_CURRENTLY_AVAILABLE: int = 0x887A0022


class _DXGI_OUTPUT_DESC(ctypes.Structure):
    _fields_ = [
        ("DeviceName", ctypes.c_wchar * 32),
        ("DesktopCoordinates", wintypes.RECT),
        ("AttachedToDesktop", wintypes.BOOL),
        ("Rotation", ctypes.c_uint),
        ("Monitor", wintypes.HMONITOR),
    ]


class _DXGI_OUTDUPL_FRAME_INFO(ctypes.Structure):
    _fields_ = [
        ("LastPresentTime", ctypes.c_longlong),
        ("LastMouseUpdateTime", ctypes.c_longlong),
        ("AccumulatedFrames", ctypes.c_uint),
        ("RectsCoalesced", wintypes.BOOL),
        ("ProtectedContentMaskedOut", wintypes.BOOL),
        ("PointerPosition", wintypes.POINT),
        ("TotalMetadataBufferSize", ctypes.c_uint),
        ("PointerShapeBufferSize", ctypes.c_uint),
    ]


class _D3D11_TEXTURE2D_DESC(ctypes.Structure):
    _fields_ = [
        ("Width", ctypes.c_uint),
        ("Height", ctypes.c_uint),
        ("MipLevels", ctypes.c_uint),
        ("ArraySize", ctypes.c_uint),
        ("Format", ctypes.c_uint),
        ("SampleCount", ctypes.c_uint),
        ("SampleQuality", ctypes.c_uint),
        ("Usage", ctypes.c_uint),
        ("BindFlags", ctypes.c_uint),
        ("CPUAccessFlags", ctypes.c_uint),
        ("MiscFlags", ctypes.c_uint),
    ]


class _D3D11_MAPPED_SUBRESOURCE(ctypes.Structure):
    _fields_ = [
        ("pData", ctypes.c_void_p),
        ("RowPitch", ctypes.c_uint),
        ("DepthPitch", ctypes.c_uint),
    ]


def _dxgi_error_name(hr: int) -> str:
    """把常见 DXGI 错误码翻译为可读文本（便于日志诊断）。"""
    hr = int(hr)
    names = {
        DXGI_ERROR_WAIT_TIMEOUT: "DXGI_ERROR_WAIT_TIMEOUT",
        DXGI_ERROR_ACCESS_LOST: "DXGI_ERROR_ACCESS_LOST",
        DXGI_ERROR_UNSUPPORTED: "DXGI_ERROR_UNSUPPORTED",
        DXGI_ERROR_NOT_CURRENTLY_AVAILABLE: "DXGI_ERROR_NOT_CURRENTLY_AVAILABLE",
    }
    return names.get(hr, f"HRESULT(0x{hr & 0xFFFFFFFF:08X})")


class _DxgiSession:
    """DXGI 桌面复制会话：D3D11 设备 + 每台显示器的 ``IDXGIOutputDuplication``。

    生命周期内持有 COM 对象，用完必须 :meth:`close`（本类也实现了
    上下文管理器协议）。
    """

    def __init__(self) -> None:
        self._device: Optional[ComPtr] = None
        self._context: Optional[ComPtr] = None
        self._factory: Optional[ComPtr] = None
        self._duplications: List[ComPtr] = []
        self._descs: List[Tuple[int, int, int, int]] = []

    # -- 建立 ---------------------------------------------------------------

    def open(self) -> None:
        """建立 D3D11 设备与全部显示器的桌面复制通道。

        Raises:
            CaptureError: DLL 缺失、COM 初始化失败、设备创建失败或没有任何
                可用输出。
        """
        if not IS_WINDOWS:
            raise CaptureError("DXGI 桌面复制仅支持 Windows")
        if not ensure_com():
            raise CaptureError("COM 初始化失败")

        try:
            d3d11 = ctypes.WinDLL("d3d11", use_last_error=True)
            dxgi = ctypes.WinDLL("dxgi", use_last_error=True)
        except OSError as exc:
            raise CaptureError(f"加载 d3d11/dxgi 失败: {exc}") from exc

        device = ctypes.c_void_p()
        feature_level = ctypes.c_uint(0)
        context = ctypes.c_void_p()
        create = d3d11.D3D11CreateDevice
        create.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_uint),
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        create.restype = _HRESULT
        level = ctypes.c_uint(D3D_FEATURE_LEVEL_11_0)
        hr = create(
            None,
            D3D_DRIVER_TYPE_HARDWARE,
            None,
            D3D11_CREATE_DEVICE_BGRA_SUPPORT,
            ctypes.byref(level),
            1,
            D3D11_SDK_VERSION,
            ctypes.byref(device),
            ctypes.byref(feature_level),
            ctypes.byref(context),
        )
        if not succeeded(hr) or not device.value:
            raise CaptureError(f"D3D11CreateDevice 失败: {_dxgi_error_name(hr)}")
        self._device = ComPtr(device.value)
        self._context = ComPtr(context.value) if context.value else None
        if self._context is None:
            raise CaptureError("无法获取 D3D11 即时上下文")

        factory = ctypes.c_void_p()
        hr = dxgi.CreateDXGIFactory1(
            ctypes.byref(GUID(IID_IDXGIFACTORY1)), ctypes.byref(factory)
        )
        if not succeeded(hr) or not factory.value:
            raise CaptureError(f"CreateDXGIFactory1 失败: {_dxgi_error_name(hr)}")
        self._factory = ComPtr(factory.value)

        self._enum_outputs()

    def _enum_outputs(self) -> None:
        """枚举全部适配器的输出，为已连接的显示器建立复制通道。"""
        assert self._factory is not None
        enum_adapters = self._factory.method(
            _XGI_FACTORY1_ENUM_ADAPTERS1,
            _HRESULT,
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_void_p),
        )
        adapter_index = 0
        while True:
            adapter_ptr = ctypes.c_void_p()
            hr = enum_adapters(
                self._factory.ptr, ctypes.c_uint(adapter_index), ctypes.byref(adapter_ptr)
            )
            adapter_index += 1
            if hr != S_OK or not adapter_ptr.value:
                break
            adapter = ComPtr(adapter_ptr.value)
            try:
                self._enum_adapter_outputs(adapter)
            finally:
                adapter.release()

        if not self._duplications:
            raise CaptureError("未找到任何可复制的显示输出")

    def _enum_adapter_outputs(self, adapter: ComPtr) -> None:
        """枚举单个适配器的输出并逐个建立桌面复制。"""
        enum_outputs = adapter.method(
            _XGI_ADAPTER1_ENUM_OUTPUTS,
            _HRESULT,
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_void_p),
        )
        output_index = 0
        while True:
            output_ptr = ctypes.c_void_p()
            hr = enum_outputs(
                adapter.ptr, ctypes.c_uint(output_index), ctypes.byref(output_ptr)
            )
            output_index += 1
            if hr != S_OK or not output_ptr.value:
                break
            output = ComPtr(output_ptr.value)
            try:
                desc = _DXGI_OUTPUT_DESC()
                get_desc = output.method(
                    7, _HRESULT, ctypes.POINTER(_DXGI_OUTPUT_DESC)
                )
                if not succeeded(get_desc(output.ptr, ctypes.byref(desc))):
                    continue
                if not desc.AttachedToDesktop:
                    continue
                output1 = output.query_interface(GUID(IID_IDXGIOUTPUT1))
                if not output1.valid():
                    continue
                try:
                    dup_ptr = ctypes.c_void_p()
                    duplicate = output1.method(
                        _XGI_OUTPUT1_DUPLICATE_OUTPUT,
                        _HRESULT,
                        ctypes.c_void_p,
                        ctypes.POINTER(ctypes.c_void_p),
                    )
                    hr = duplicate(
                        output1.ptr, self._device.ptr, ctypes.byref(dup_ptr)
                    )
                    if not succeeded(hr) or not dup_ptr.value:
                        continue
                finally:
                    output1.release()
                r = desc.DesktopCoordinates
                self._duplications.append(ComPtr(dup_ptr.value))
                self._descs.append(
                    (int(r.left), int(r.top), int(r.right - r.left), int(r.bottom - r.top))
                )
            finally:
                output.release()

    # -- 抓取 ---------------------------------------------------------------

    @property
    def output_descs(self) -> List[Tuple[int, int, int, int]]:
        """已建立复制通道的显示器矩形列表 ``(x, y, w, h)``（物理像素）。"""
        return list(self._descs)

    def grab(self, index: int, timeout_ms: int = 200, attempts: int = 3) -> Optional[bytes]:
        """抓取第 ``index`` 台显示器的一帧，返回 BGRA 原始字节（自顶向下）。

        Args:
            index: 显示器索引（对应 :attr:`output_descs` 顺序）。
            timeout_ms: ``AcquireNextFrame`` 单次超时（毫秒）。
            attempts: 超时后的重试次数（桌面未更新时会超时，需重试）。

        Returns:
            ``(w, h, bytes)`` 语义见下；失败返回 ``None``。

        Raises:
            CaptureError: 会话未打开或索引越界。
        """
        if not self._duplications:
            raise CaptureError("DXGI 会话未打开")
        if not 0 <= index < len(self._duplications):
            raise CaptureError(f"显示器索引越界: {index}")
        dup = self._duplications[index]
        width, height = self._descs[index][2], self._descs[index][3]

        frame_info = _DXGI_OUTDUPL_FRAME_INFO()
        resource_ptr = ctypes.c_void_p()
        acquire = dup.method(
            _XGI_DUP_ACQUIRE_NEXT_FRAME,
            _HRESULT,
            ctypes.c_uint,
            ctypes.POINTER(_DXGI_OUTDUPL_FRAME_INFO),
            ctypes.POINTER(ctypes.c_void_p),
        )
        release_frame = dup.method(_XGI_DUP_RELEASE_FRAME, _HRESULT)

        hr = DXGI_ERROR_WAIT_TIMEOUT
        for _ in range(max(1, attempts)):
            hr = acquire(
                dup.ptr,
                ctypes.c_uint(timeout_ms),
                ctypes.byref(frame_info),
                ctypes.byref(resource_ptr),
            )
            if succeeded(hr) and resource_ptr.value:
                break
            if hr == DXGI_ERROR_ACCESS_LOST:
                raise CaptureError("DXGI 桌面复制访问丢失（会话需重建）")
        if not succeeded(hr) or not resource_ptr.value:
            return None

        resource = ComPtr(resource_ptr.value)
        try:
            return self._read_texture(resource, width, height)
        finally:
            resource.release()
            release_frame(dup.ptr)

    def _read_texture(self, resource: ComPtr, width: int, height: int) -> Optional[bytes]:
        """把桌面纹理拷到暂存纹理并回读到 CPU（BGRA，自顶向下）。"""
        assert self._device is not None and self._context is not None
        texture = resource.query_interface(GUID(IID_ID3D11TEXTURE2D))
        if not texture.valid():
            return None
        staging = None
        try:
            desc = _D3D11_TEXTURE2D_DESC()
            desc.Width = width
            desc.Height = height
            desc.MipLevels = 1
            desc.ArraySize = 1
            desc.Format = DXGI_FORMAT_B8G8R8A8_UNORM
            desc.SampleCount = 1
            desc.SampleQuality = 0
            desc.Usage = D3D11_USAGE_STAGING
            desc.BindFlags = 0
            desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ
            desc.MiscFlags = 0

            staging_ptr = ctypes.c_void_p()
            create_tex = self._device.method(
                _D3D11_CREATE_TEXTURE2D,
                _HRESULT,
                ctypes.POINTER(_D3D11_TEXTURE2D_DESC),
                ctypes.POINTER(ctypes.c_void_p),
                ctypes.POINTER(ctypes.c_void_p),
            )
            hr = create_tex(
                self._device.ptr, ctypes.byref(desc), None, ctypes.byref(staging_ptr)
            )
            if not succeeded(hr) or not staging_ptr.value:
                return None
            staging = ComPtr(staging_ptr.value)

            copy = self._context.method(
                _D3D11_CTX_COPY_RESOURCE, None, ctypes.c_void_p, ctypes.c_void_p
            )
            copy(self._context.ptr, staging.ptr, texture.ptr)

            mapped = _D3D11_MAPPED_SUBRESOURCE()
            do_map = self._context.method(
                _D3D11_CTX_MAP,
                _HRESULT,
                ctypes.c_void_p,
                ctypes.c_uint,
                ctypes.c_uint,
                ctypes.c_uint,
                ctypes.POINTER(_D3D11_MAPPED_SUBRESOURCE),
            )
            hr = do_map(
                self._context.ptr,
                staging.ptr,
                0,
                D3D11_MAP_READ,
                0,
                ctypes.byref(mapped),
            )
            if not succeeded(hr) or not mapped.pData:
                return None
            try:
                row_bytes = width * 4
                out = bytearray(row_bytes * height)
                # 必须拿到 bytearray 自身的可写视图；对 bytes(out) 做 memmove 会
                # 写进一个立刻被丢弃的临时不可变副本（结果全 0）。
                dst = (ctypes.c_char * len(out)).from_buffer(out)
                base = int(mapped.pData)
                row_pitch = int(mapped.RowPitch)
                if row_pitch == row_bytes:
                    ctypes.memmove(dst, ctypes.c_void_p(base), row_bytes * height)
                else:
                    for row in range(height):  # 行距含对齐填充，逐行拷贝
                        ctypes.memmove(
                            ctypes.byref(dst, row * row_bytes),
                            ctypes.c_void_p(base + row * row_pitch),
                            row_bytes,
                        )
                del dst  # 解除导出，否则 bytes(out) 会因缓冲区被导出而报错
                return bytes(out)
            finally:
                unmap = self._context.method(
                    _D3D11_CTX_UNMAP, None, ctypes.c_void_p, ctypes.c_uint
                )
                unmap(self._context.ptr, staging.ptr, 0)
        finally:
            texture.release()
            if staging is not None:
                staging.release()

    # -- 生命周期 -----------------------------------------------------------

    def close(self) -> None:
        """释放全部 COM 对象（幂等）。"""
        for dup in self._duplications:
            dup.release()
        self._duplications = []
        self._descs = []
        if self._context is not None:
            self._context.release()
            self._context = None
        if self._device is not None:
            self._device.release()
            self._device = None
        if self._factory is not None:
            self._factory.release()
            self._factory = None

    def __enter__(self) -> "_DxgiSession":
        self.open()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def capture_desktop_dxgi(
    rect: Optional[Tuple[int, int, int, int]] = None,
    timeout_ms: int = 200,
) -> Optional[bytes]:
    """以 DXGI 桌面复制抓取指定屏幕区域，返回 BGRA 原始字节（自顶向下）。

    一次性会话（抓取后立即释放全部 COM 对象），适合低频快照场景。

    Args:
        rect: ``(x, y, w, h)`` 物理像素矩形；``None`` 表示整个虚拟桌面。
            跨显示器时按各显示器矩形分别抓取后拼接。
        timeout_ms: ``AcquireNextFrame`` 超时（毫秒）。

    Returns:
        ``bytes``（BGRA，首行为顶行）；任何失败返回 ``None``。
    """
    try:
        session = _DxgiSession()
    except CaptureError:
        return None
    try:
        session.open()
    except CaptureError:
        session.close()
        return None

    try:
        descs = session.output_descs
        if not descs:
            return None
        if rect is None:
            frames = []
            for i in range(len(descs)):
                data = session.grab(i, timeout_ms)
                if data is None:
                    return None
                frames.append((descs[i], data))
            return _stitch_frames(frames)

        x, y, w, h = (int(v) for v in rect)
        pieces = []
        for i, (mx, my, mw, mh) in enumerate(descs):
            ix0, iy0 = max(x, mx), max(y, my)
            ix1, iy1 = min(x + w, mx + mw), min(y + h, my + mh)
            if ix1 <= ix0 or iy1 <= iy0:
                continue
            data = session.grab(i, timeout_ms)
            if data is None:
                return None
            pieces.append(((ix0, iy0, ix1 - ix0, iy1 - iy0), (mx, my), data, (mw, mh)))
        if not pieces:
            return None
        return _compose_pieces(pieces, w, h)
    except CaptureError:
        return None
    finally:
        session.close()


def _stitch_frames(frames: List[Tuple[Tuple[int, int, int, int], bytes]]) -> bytes:
    """把各显示器的帧按虚拟桌面坐标拼接为一整幅图（BGRA）。

    Args:
        frames: ``((mx, my, mw, mh), data)`` 列表。

    Returns:
        拼接后的 BGRA 字节；无帧时返回空 ``bytes``。
    """
    if not frames:
        return b""
    min_x = min(f[0][0] for f in frames)
    min_y = min(f[0][1] for f in frames)
    max_x = max(f[0][0] + f[0][2] for f in frames)
    max_y = max(f[0][1] + f[0][3] for f in frames)
    out_w, out_h = max_x - min_x, max_y - min_y
    out = bytearray(out_w * out_h * 4)
    for (mx, my, mw, mh), data in frames:
        for row in range(mh):
            dst = ((my - min_y) + row) * out_w * 4 + (mx - min_x) * 4
            src = row * mw * 4
            out[dst : dst + mw * 4] = data[src : src + mw * 4]
    return bytes(out)


def _compose_pieces(
    pieces: List[Tuple[Tuple[int, int, int, int], Tuple[int, int], bytes, Tuple[int, int]]],
    out_w: int,
    out_h: int,
) -> bytes:
    """把多显示器裁切块按请求矩形拼接到同一输出缓冲（BGRA）。

    Args:
        pieces: ``((ix, iy, iw, ih), (mx, my), data, (mw, mh))`` 列表。
        out_w: 输出宽度。
        out_h: 输出高度。

    Returns:
        拼接后的 BGRA 字节。
    """
    out = bytearray(out_w * out_h * 4)
    x0 = min(p[0][0] for p in pieces)
    y0 = min(p[0][1] for p in pieces)
    for (ix, iy, iw, ih), (mx, my), data, (mw, _mh) in pieces:
        for row in range(ih):
            src_row = (iy - my) + row
            dst_row = (iy - y0) + row
            src = src_row * mw * 4 + (ix - mx) * 4
            dst = dst_row * out_w * 4 + (ix - x0) * 4
            out[dst : dst + iw * 4] = data[src : src + iw * 4]
    return bytes(out)


# ---------------------------------------------------------------------------
# SystemParametersInfo / 注册表兜底
# ---------------------------------------------------------------------------

SPI_GETDESKWALLPAPER: int = 0x0073
MAX_PATH: int = 260


def wallpaper_path_spi() -> str:
    """通过 ``SystemParametersInfoW(SPI_GETDESKWALLPAPER)`` 读取壁纸路径。

    Returns:
        文件路径；失败返回空串。
    """
    if not IS_WINDOWS:
        return ""
    try:
        buffer = ctypes.create_unicode_buffer(MAX_PATH)
        if _user32.SystemParametersInfoW(SPI_GETDESKWALLPAPER, MAX_PATH, buffer, 0):
            return buffer.value or ""
    except (OSError, ValueError):
        pass
    return ""


def registry_desktop_values() -> Tuple[str, str, str]:
    """读取 ``Control Panel\\Desktop`` 的壁纸路径 / 放置方式 / 平铺标记。

    Returns:
        ``(path, wallpaper_style, tile_wallpaper)``；读取失败时返回空串。
    """
    if not IS_WINDOWS:
        return ("", "", "")
    try:
        import winreg
    except ImportError:  # pragma: no cover
        return ("", "", "")
    values = {"WallPaper": "", "WallpaperStyle": "", "TileWallpaper": ""}
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop")
        try:
            for name in values:
                try:
                    values[name] = str(winreg.QueryValueEx(key, name)[0])
                except OSError:
                    values[name] = ""
        finally:
            winreg.CloseKey(key)
    except OSError:
        return ("", "", "")
    return (values["WallPaper"], values["WallpaperStyle"], values["TileWallpaper"])


def registry_background_color() -> Optional[Tuple[int, int, int]]:
    """读取注册表里"桌面背景纯色"（``Control Panel\\Colors\\Background``）。

    该值是 ``"r g b"`` 形式的字符串（如 ``"0 0 0"``）。

    Returns:
        ``(r, g, b)``；读取或解析失败返回 ``None``。
    """
    if not IS_WINDOWS:
        return None
    try:
        import winreg
    except ImportError:  # pragma: no cover
        return None
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Colors")
        try:
            raw = str(winreg.QueryValueEx(key, "Background")[0])
        finally:
            winreg.CloseKey(key)
    except OSError:
        return None
    parts = raw.split()
    if len(parts) < 3:
        return None
    try:
        return tuple(max(0, min(255, int(p))) for p in parts[:3])  # type: ignore[return-value]
    except ValueError:
        return None
