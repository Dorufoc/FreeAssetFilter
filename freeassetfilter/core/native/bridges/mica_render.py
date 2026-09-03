#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``mica_render.dll`` 的 ctypes 桥接层 —— Mica GPU 渲染原生库的 Python 门面。

本模块是 :mod:`freeassetfilter.ui.mica` 与原生 D3D11 渲染库之间**唯一**的接口，
职责严格限定为三件事：

1. **定位并加载 DLL** —— 路径经 :func:`freeassetfilter.core._paths.native_bin_dir`
   解析（唯一事实来源），开发期额外允许从 ``native/src/cpp_mica_render/`` 直接加载
   刚编译出的产物。
2. **ABI 映射** —— 把 ``mica_render.h`` 的结构体与函数签名映射为 ctypes 类型，
   并做版本校验（:data:`REQUIRED_API_VERSION`）。
3. **错误转译** —— 所有非零 ``mica_status`` 抛出 :class:`MicaRenderError`，
   携带状态码与原生侧的 UTF-8 错误描述。

线程约定（**重要**）
-------------------
:class:`MicaRenderContext` 持有 ``ID3D11DeviceContext``（立即上下文）、
单线程 ``ID2D1Factory1`` 与 WIC 工厂，三者**均非线程安全**；且
:func:`mica_create` 会在调用线程上 ``CoInitializeEx``。因此一个实例必须
**始终在创建它的那个线程上使用**。跨线程调度由
:class:`freeassetfilter.ui.mica.gpu.GpuRenderer` 的专用工作线程负责，本层不做
任何隐式加锁 —— 隐式锁只会掩盖误用，而无法修复 COM 公寓归属问题。

不可用时的行为
-------------
DLL 缺失、版本不符、无兼容显卡等一切失败都表现为 :func:`is_available` 返回
``False`` 或构造函数抛 :class:`MicaRenderError`，**绝不 crash 进程**：原生侧在
C ABI 边界拦截了全部 C++ 异常，本层再把返回码转为 Python 异常。
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
from ctypes import (
    POINTER,
    Structure,
    c_char,
    c_char_p,
    c_float,
    c_int32,
    c_uint8,
    c_uint32,
    c_void_p,
    c_wchar_p,
)
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

_LOG = logging.getLogger(__name__)

#: 本桥接层要求的 ABI 版本，必须与 ``mica_render.h`` 的 ``MICA_API_VERSION`` 一致。
REQUIRED_API_VERSION: int = 1

#: DLL 文件名。
LIBRARY_NAME: str = "mica_render.dll"


# ---------------------------------------------------------------------------
# 状态码与枚举
# ---------------------------------------------------------------------------

MICA_OK: int = 0
MICA_ERR_INVALID_ARG: int = 1
MICA_ERR_NO_DEVICE: int = 2
MICA_ERR_DEVICE_LOST: int = 3
MICA_ERR_NO_SOURCE: int = 4
MICA_ERR_SHADER: int = 5
MICA_ERR_CAPTURE_TIMEOUT: int = 6
MICA_ERR_CAPTURE_UNAVAILABLE: int = 7
MICA_ERR_DECODE: int = 8
MICA_ERR_OUT_OF_MEMORY: int = 9
MICA_ERR_UNSUPPORTED: int = 10
MICA_ERR_INTERNAL: int = 11

#: 状态码 → 可读名称，仅用于日志与异常消息。
STATUS_NAMES: Dict[int, str] = {
    MICA_OK: "OK",
    MICA_ERR_INVALID_ARG: "INVALID_ARG",
    MICA_ERR_NO_DEVICE: "NO_DEVICE",
    MICA_ERR_DEVICE_LOST: "DEVICE_LOST",
    MICA_ERR_NO_SOURCE: "NO_SOURCE",
    MICA_ERR_SHADER: "SHADER",
    MICA_ERR_CAPTURE_TIMEOUT: "CAPTURE_TIMEOUT",
    MICA_ERR_CAPTURE_UNAVAILABLE: "CAPTURE_UNAVAILABLE",
    MICA_ERR_DECODE: "DECODE",
    MICA_ERR_OUT_OF_MEMORY: "OUT_OF_MEMORY",
    MICA_ERR_UNSUPPORTED: "UNSUPPORTED",
    MICA_ERR_INTERNAL: "INTERNAL",
}

#: 画布来源枚举 → :mod:`freeassetfilter.ui.mica.source` 的 backend 字符串。
BACKEND_NAMES: Dict[int, str] = {
    0: "none",
    1: "wallpaper",
    2: "dxgi",
    3: "memory",
    4: "solid",
}

#: 壁纸摆放方式字符串 → 原生枚举值（键与 ``source.VALID_POSITIONS`` 一致）。
POSITION_CODES: Dict[str, int] = {
    "Center": 0,
    "Tile": 1,
    "Stretch": 2,
    "Fit": 3,
    "Fill": 4,
    "Span": 5,
}

#: 需要重建整个上下文（而非仅重试）的状态码。
FATAL_STATUS: frozenset = frozenset({MICA_ERR_DEVICE_LOST, MICA_ERR_NO_DEVICE})


class MicaRenderError(RuntimeError):
    """原生库调用失败。

    Attributes:
        status: 原始 ``mica_status`` 码。
        detail: 原生侧 ``mica_last_error`` 的描述（可能为空串）。
    """

    def __init__(self, status: int, detail: str = "", operation: str = "") -> None:
        """构造异常。

        Args:
            status: ``mica_status`` 返回码。
            detail: 原生侧错误描述。
            operation: 触发失败的操作名，用于定位。
        """
        self.status = int(status)
        self.detail = detail
        name = STATUS_NAMES.get(self.status, "?")
        prefix = f"{operation}: " if operation else ""
        super().__init__(f"{prefix}{name}({self.status}) {detail}".rstrip())

    @property
    def fatal(self) -> bool:
        """是否属于必须重建上下文的致命错误。"""
        return self.status in FATAL_STATUS

    @property
    def transient(self) -> bool:
        """是否属于可忽略的瞬时错误（保留旧画布即可）。"""
        return self.status in (MICA_ERR_CAPTURE_TIMEOUT, MICA_ERR_CAPTURE_UNAVAILABLE)


# ---------------------------------------------------------------------------
# ABI 结构体（字段顺序 / 类型必须与 mica_render.h 逐一对应）
# ---------------------------------------------------------------------------


class _DeviceInfoStruct(Structure):
    """``mica_device_info``。"""

    _pack_ = 4
    _fields_ = [
        ("api_version", c_int32),
        ("feature_level", c_int32),
        ("use_warp", c_int32),
        ("dxgi_available", c_int32),
        ("canvas_width", c_int32),
        ("canvas_height", c_int32),
        ("canvas_mips", c_int32),
        ("canvas_backend", c_int32),
        ("adapter", c_char * 128),
    ]


class _MonitorLayoutStruct(Structure):
    """``mica_monitor_layout``。"""

    _pack_ = 4
    _fields_ = [
        ("x", c_int32),
        ("y", c_int32),
        ("w", c_int32),
        ("h", c_int32),
        ("position", c_int32),
        ("background_rgb", c_uint32),
        ("wallpaper", c_wchar_p),
    ]


class _BakeParamsStruct(Structure):
    """``mica_bake_params``。"""

    _pack_ = 4
    _fields_ = [
        ("win_x", c_int32),
        ("win_y", c_int32),
        ("win_w", c_int32),
        ("win_h", c_int32),
        ("grid_w", c_int32),
        ("grid_h", c_int32),
        ("margin", c_int32),
        ("dither", c_int32),
        ("sigma", c_float),
        ("gain", c_float),
        ("chroma_cap", c_float),
        ("alpha", c_float),
        ("l_ref", c_float),
        ("gate_lo", c_float),
        ("gate_hi", c_float),
        ("gate_feather", c_float),
        ("g1_rgb", c_uint32),
    ]


class _BakeResultStruct(Structure):
    """``mica_bake_result``。"""

    _pack_ = 4
    _fields_ = [
        ("width", c_int32),
        ("height", c_int32),
        ("pad_width", c_int32),
        ("pad_height", c_int32),
        ("sample_x", c_float),
        ("sample_y", c_float),
        ("sample_w", c_float),
        ("sample_h", c_float),
        ("duration_ms", c_float),
        ("backend", c_int32),
    ]


# ---------------------------------------------------------------------------
# 面向调用方的数据类
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DeviceInfo:
    """设备与画布状态快照。

    Attributes:
        api_version: 原生 ABI 版本。
        feature_level: D3D 特性等级（``0xB100`` = 11_1）。
        use_warp: 是否降级到 WARP 软件光栅。
        dxgi_available: 桌面复制可用性；``None`` 表示尚未探测。
        canvas_size: 画布尺寸 ``(w, h)``，未构建时 ``(0, 0)``。
        canvas_mips: 画布 mipmap 级数。
        canvas_backend: 画布来源字符串，见 :data:`BACKEND_NAMES`。
        adapter: 适配器描述。
    """

    api_version: int
    feature_level: int
    use_warp: bool
    dxgi_available: Optional[bool]
    canvas_size: Tuple[int, int]
    canvas_mips: int
    canvas_backend: str
    adapter: str

    @property
    def feature_level_text(self) -> str:
        """特性等级的可读形式，如 ``"11_1"``。"""
        major = (self.feature_level >> 12) & 0xF
        minor = (self.feature_level >> 8) & 0xF
        return f"{major}_{minor}"


@dataclass(frozen=True)
class MonitorLayout:
    """单显示器的壁纸摆放描述（:meth:`MicaRenderContext.build_canvas_from_wallpapers` 的输入）。

    Attributes:
        rect: ``(x, y, w, h)`` 显示器矩形（虚拟桌面物理像素）。
        position: 摆放方式，取值见 :data:`POSITION_CODES` 的键。
        background_rgb: Fit / Center 留边填充色 ``(r, g, b)``。
        wallpaper: 壁纸文件绝对路径；空串表示仅填充背景色。
    """

    rect: Tuple[int, int, int, int]
    position: str = "Fill"
    background_rgb: Tuple[int, int, int] = (0, 0, 0)
    wallpaper: str = ""


@dataclass(frozen=True)
class BakeParams:
    """一次烘焙的完整输入。

    字段与 :class:`freeassetfilter.ui.mica.config.EngineParams` 及
    :mod:`freeassetfilter.ui.mica.engine` 的几何量逐一对应，语义见
    ``mica_render.h``。

    Attributes:
        window_rect: ``(x, y, w, h)`` 窗口矩形（虚拟桌面物理像素）。
        grid_size: ``(grid_w, grid_h)`` 目标网格尺寸（不含扩边）。
        margin: 采样扩边宽度（网格像素）。
        sigma: 色度低通标准差（网格像素）。
        gain: 色度增益。
        chroma_cap: 色度软上限（Oklab chroma）。
        alpha: 色调不透明度 0–1。
        l_ref: G1 基色的 Oklab L。
        g1_rgb: G1 基色 ``(r, g, b)``。
        gate_lo: 亮度可靠性门控下限。
        gate_hi: 亮度可靠性门控上限。
        gate_feather: 门控羽化宽度。
        dither: 是否启用 TPDF 抖动。
    """

    window_rect: Tuple[int, int, int, int]
    grid_size: Tuple[int, int]
    margin: int
    sigma: float
    gain: float
    chroma_cap: float
    alpha: float
    l_ref: float
    g1_rgb: Tuple[int, int, int]
    gate_lo: float = 0.010
    gate_hi: float = 0.990
    gate_feather: float = 0.010
    dither: bool = True


@dataclass(frozen=True)
class BakeResult:
    """一次烘焙的输出元数据。

    Attributes:
        size: 输出网格尺寸 ``(w, h)``。
        pad_size: 含扩边的中间纹理尺寸 ``(w, h)``。
        sample_rect: 实际采样的虚拟桌面矩形 ``(x, y, w, h)``。
        duration_ms: GPU 提交 + 回读耗时（毫秒）。
        backend: 画布来源字符串。
    """

    size: Tuple[int, int]
    pad_size: Tuple[int, int]
    sample_rect: Tuple[float, float, float, float]
    duration_ms: float
    backend: str


# ---------------------------------------------------------------------------
# DLL 加载
# ---------------------------------------------------------------------------

_LOAD_LOCK = threading.Lock()
_LIB: Optional[ctypes.WinDLL] = None
_LOAD_FAILED: bool = False
_LOAD_ERROR: str = ""


def candidate_paths() -> List[Path]:
    """返回 DLL 的候选路径，按优先级排列。

    打包后只允许 ``core/native/bin/``；开发期额外允许源码目录，便于编译后
    立即验证而无需先安装。

    Returns:
        候选路径列表（未过滤存在性）。
    """
    try:
        from freeassetfilter.core._paths import native_bin_dir

        bin_dir = native_bin_dir()
    except Exception:  # pragma: no cover - _paths 不可用时退回相对定位
        bin_dir = Path(__file__).resolve().parent.parent / "bin"

    paths = [Path(bin_dir) / LIBRARY_NAME]
    if not getattr(sys, "frozen", False):
        src = Path(__file__).resolve().parent.parent / "src" / "cpp_mica_render"
        paths.append(src / LIBRARY_NAME)
    return paths


def library_path() -> Optional[Path]:
    """返回第一个实际存在的 DLL 路径；都不存在时返回 ``None``。"""
    for path in candidate_paths():
        if path.is_file():
            return path
    return None


def _bind(lib: ctypes.WinDLL) -> None:
    """为 DLL 的全部导出绑定 ctypes 签名。

    Args:
        lib: 已加载的 DLL。

    Raises:
        AttributeError: 缺少必需的导出符号。
    """
    lib.mica_api_version.argtypes = []
    lib.mica_api_version.restype = c_int32

    lib.mica_create.argtypes = [c_int32, POINTER(c_void_p)]
    lib.mica_create.restype = c_int32

    lib.mica_destroy.argtypes = [c_void_p]
    lib.mica_destroy.restype = None

    lib.mica_get_device_info.argtypes = [c_void_p, POINTER(_DeviceInfoStruct)]
    lib.mica_get_device_info.restype = c_int32

    lib.mica_last_error.argtypes = [c_void_p]
    lib.mica_last_error.restype = c_char_p

    lib.mica_set_virtual_desktop.argtypes = [
        c_void_p, c_int32, c_int32, c_int32, c_int32, c_int32,
    ]
    lib.mica_set_virtual_desktop.restype = c_int32

    lib.mica_build_canvas_from_wallpapers.argtypes = [
        c_void_p, POINTER(_MonitorLayoutStruct), c_int32, c_uint32,
    ]
    lib.mica_build_canvas_from_wallpapers.restype = c_int32

    lib.mica_build_canvas_from_dxgi.argtypes = [c_void_p, c_int32]
    lib.mica_build_canvas_from_dxgi.restype = c_int32

    lib.mica_build_canvas_from_memory.argtypes = [
        c_void_p, POINTER(c_uint8), c_int32, c_int32, c_int32,
    ]
    lib.mica_build_canvas_from_memory.restype = c_int32

    lib.mica_build_canvas_solid.argtypes = [c_void_p, c_uint32]
    lib.mica_build_canvas_solid.restype = c_int32

    lib.mica_dxgi_probe.argtypes = [c_void_p, POINTER(c_int32)]
    lib.mica_dxgi_probe.restype = c_int32

    lib.mica_canvas_mean_rgb.argtypes = [c_void_p, POINTER(c_uint32)]
    lib.mica_canvas_mean_rgb.restype = c_int32

    lib.mica_bake.argtypes = [
        c_void_p,
        POINTER(_BakeParamsStruct),
        POINTER(c_uint8),
        c_int32,
        POINTER(_BakeResultStruct),
    ]
    lib.mica_bake.restype = c_int32


def load_library() -> Optional[ctypes.WinDLL]:
    """加载并缓存 DLL（幂等、线程安全）。

    首次失败后会记住失败状态，不再反复尝试 —— 加载失败几乎总是环境性的
    （文件缺失 / 架构不符 / 版本不符），重试没有意义且会拖慢每次调用。

    Returns:
        已绑定签名的 DLL；不可用时返回 ``None``。
    """
    global _LIB, _LOAD_FAILED, _LOAD_ERROR

    if _LIB is not None:
        return _LIB
    if _LOAD_FAILED:
        return None

    with _LOAD_LOCK:
        if _LIB is not None:
            return _LIB
        if _LOAD_FAILED:
            return None

        if sys.platform != "win32":
            _LOAD_FAILED = True
            _LOAD_ERROR = "mica_render 仅支持 Windows"
            return None

        path = library_path()
        if path is None:
            _LOAD_FAILED = True
            _LOAD_ERROR = f"未找到 {LIBRARY_NAME}（候选：{candidate_paths()}）"
            _LOG.info("Mica GPU 后端不可用：%s", _LOAD_ERROR)
            return None

        try:
            lib = ctypes.WinDLL(str(path))
            _bind(lib)
            version = int(lib.mica_api_version())
        except (OSError, AttributeError, ValueError) as exc:
            _LOAD_FAILED = True
            _LOAD_ERROR = f"加载 {path} 失败：{exc}"
            _LOG.warning("Mica GPU 后端不可用：%s", _LOAD_ERROR)
            return None

        if version != REQUIRED_API_VERSION:
            _LOAD_FAILED = True
            _LOAD_ERROR = (
                f"{path} 的 ABI 版本为 {version}，桥接层要求 {REQUIRED_API_VERSION}"
            )
            _LOG.warning("Mica GPU 后端不可用：%s", _LOAD_ERROR)
            return None

        _LIB = lib
        _LOG.debug("mica_render 加载成功：%s (ABI v%d)", path, version)
        return _LIB


def is_available() -> bool:
    """DLL 是否可加载（不代表能成功创建 D3D11 设备）。"""
    return load_library() is not None


def load_error() -> str:
    """最近一次加载失败的原因；从未失败时为空串。"""
    return _LOAD_ERROR


def _pack_rgb(rgb: Sequence[int]) -> int:
    """把 ``(r, g, b)`` 打包为 ``0x00RRGGBB``。

    Args:
        rgb: 长度 ≥3 的整数序列，超出 0–255 的分量按位截断。

    Returns:
        打包后的整数。
    """
    r, g, b = (int(v) & 0xFF for v in tuple(rgb)[:3])
    return (r << 16) | (g << 8) | b


def _unpack_rgb(value: int) -> Tuple[int, int, int]:
    """把 ``0x00RRGGBB`` 拆为 ``(r, g, b)``。"""
    return ((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF)


# ---------------------------------------------------------------------------
# 上下文
# ---------------------------------------------------------------------------


class MicaRenderContext:
    """原生渲染上下文的 Python 包装（单线程亲和，见模块文档）。

    生命周期由本对象持有：:meth:`close` 或垃圾回收时释放全部 GPU 资源。
    重复 :meth:`close` 是安全的。

    Examples:
        >>> ctx = MicaRenderContext()                       # doctest: +SKIP
        >>> ctx.set_virtual_desktop((0, 0, 2560, 1440))     # doctest: +SKIP
        >>> ctx.build_canvas_solid((26, 26, 26))            # doctest: +SKIP
        >>> img, meta = ctx.bake(params)                    # doctest: +SKIP
        >>> ctx.close()                                     # doctest: +SKIP
    """

    __slots__ = ("_lib", "_handle", "_owner_thread", "_canvas_ready")

    def __init__(self, *, allow_warp: bool = True) -> None:
        """创建上下文（含 D3D11 设备、D2D / WIC 工厂与三段着色器）。

        Args:
            allow_warp: 硬件适配器不可用时是否允许降级到 WARP 软件光栅。
                WARP 可用但慢（实测比硬件慢一个量级），仅作为最后手段。

        Raises:
            MicaRenderError: DLL 不可用或设备创建失败。
        """
        lib = load_library()
        if lib is None:
            raise MicaRenderError(MICA_ERR_UNSUPPORTED, load_error(), "load_library")

        handle = c_void_p()
        status = int(lib.mica_create(1 if allow_warp else 0, ctypes.byref(handle)))
        if status != MICA_OK or not handle:
            detail = self._static_error(lib)
            raise MicaRenderError(status or MICA_ERR_NO_DEVICE, detail, "mica_create")

        self._lib = lib
        self._handle: Optional[c_void_p] = handle
        self._owner_thread = threading.get_ident()
        self._canvas_ready = False

    # -- 内部工具 ---------------------------------------------------------

    @staticmethod
    def _static_error(lib: ctypes.WinDLL) -> str:
        """读取上下文创建期的错误（此时无句柄，原生侧用静态缓冲区暴露）。"""
        raw = lib.mica_last_error(None)
        return raw.decode("utf-8", "replace") if raw else ""

    def _error(self) -> str:
        """读取本上下文最近一次失败的描述。"""
        if self._handle is None:
            return ""
        raw = self._lib.mica_last_error(self._handle)
        return raw.decode("utf-8", "replace") if raw else ""

    def _require(self, operation: str) -> c_void_p:
        """校验句柄有效且调用发生在拥有者线程上。

        Args:
            operation: 操作名（异常消息用）。

        Returns:
            有效句柄。

        Raises:
            MicaRenderError: 上下文已关闭。
            RuntimeError: 跨线程调用（编程错误，必须暴露而非静默容忍）。
        """
        if self._handle is None:
            raise MicaRenderError(MICA_ERR_INVALID_ARG, "上下文已关闭", operation)
        if threading.get_ident() != self._owner_thread:
            raise RuntimeError(
                f"MicaRenderContext.{operation} 必须在创建它的线程上调用"
                f"（创建线程 {self._owner_thread}，当前 {threading.get_ident()}）"
            )
        return self._handle

    def _check(self, status: int, operation: str) -> None:
        """非零状态码转异常。

        Args:
            status: ``mica_status`` 返回码。
            operation: 操作名。

        Raises:
            MicaRenderError: ``status != MICA_OK``。
        """
        if status != MICA_OK:
            raise MicaRenderError(status, self._error(), operation)

    # -- 状态 -------------------------------------------------------------

    @property
    def alive(self) -> bool:
        """上下文是否仍然有效。"""
        return self._handle is not None

    @property
    def canvas_ready(self) -> bool:
        """是否已成功构建过画布（决定 :meth:`bake` 能否调用）。"""
        return self._canvas_ready

    def device_info(self) -> DeviceInfo:
        """读取设备与画布状态快照。

        Returns:
            :class:`DeviceInfo`。

        Raises:
            MicaRenderError: 调用失败。
        """
        handle = self._require("device_info")
        raw = _DeviceInfoStruct()
        self._check(
            int(self._lib.mica_get_device_info(handle, ctypes.byref(raw))),
            "mica_get_device_info",
        )
        return DeviceInfo(
            api_version=int(raw.api_version),
            feature_level=int(raw.feature_level),
            use_warp=bool(raw.use_warp),
            dxgi_available=None if raw.dxgi_available < 0 else bool(raw.dxgi_available),
            canvas_size=(int(raw.canvas_width), int(raw.canvas_height)),
            canvas_mips=int(raw.canvas_mips),
            canvas_backend=BACKEND_NAMES.get(int(raw.canvas_backend), "none"),
            adapter=raw.adapter.decode("utf-8", "replace"),
        )

    # -- 画布 -------------------------------------------------------------

    def set_virtual_desktop(
        self,
        virtual_rect: Tuple[int, int, int, int],
        max_long_side: int = 1600,
    ) -> None:
        """声明虚拟桌面几何与画布分辨率上限。

        调用后画布被标记为失效，必须重新构建 —— 桌面几何改变时旧画布的
        坐标映射已不再成立，继续使用会导致取色位置错位。

        Args:
            virtual_rect: ``(x, y, w, h)`` 虚拟桌面矩形（物理像素）。
            max_long_side: 画布长边上限，建议与
                :data:`freeassetfilter.ui.mica.source.CANVAS_MAX_LONG` 一致。

        Raises:
            MicaRenderError: 参数非法。
        """
        handle = self._require("set_virtual_desktop")
        vx, vy, vw, vh = (int(v) for v in virtual_rect)
        self._check(
            int(
                self._lib.mica_set_virtual_desktop(
                    handle, vx, vy, vw, vh, int(max_long_side)
                )
            ),
            "mica_set_virtual_desktop",
        )
        self._canvas_ready = False

    def build_canvas_from_wallpapers(
        self,
        layouts: Sequence[MonitorLayout],
        fallback_rgb: Tuple[int, int, int],
    ) -> None:
        """由壁纸文件构建画布（WIC 解码 + Direct2D 摆放）。

        Args:
            layouts: 每显示器一条，至少一项。
            fallback_rgb: 未被任何显示器覆盖区域的填充色。

        Raises:
            MicaRenderError: 全部壁纸解码失败（此时画布已退化为纯色）或参数非法。
        """
        handle = self._require("build_canvas_from_wallpapers")
        if not layouts:
            raise MicaRenderError(
                MICA_ERR_INVALID_ARG, "layouts 为空", "build_canvas_from_wallpapers"
            )

        count = len(layouts)
        array = (_MonitorLayoutStruct * count)()
        # 显式保留字符串引用：c_wchar_p 不持有所有权，若临时对象被回收则悬垂。
        keep: List[str] = []
        for i, item in enumerate(layouts):
            x, y, w, h = (int(v) for v in item.rect)
            path = str(item.wallpaper or "")
            keep.append(path)
            array[i].x = x
            array[i].y = y
            array[i].w = max(1, w)
            array[i].h = max(1, h)
            array[i].position = POSITION_CODES.get(str(item.position), 4)
            array[i].background_rgb = _pack_rgb(item.background_rgb)
            array[i].wallpaper = path if path else None

        status = int(
            self._lib.mica_build_canvas_from_wallpapers(
                handle, array, count, _pack_rgb(fallback_rgb)
            )
        )
        del keep
        if status == MICA_OK:
            self._canvas_ready = True
        else:
            # 原生侧在全部解码失败时会发布纯色画布，仍可 bake；但调用方需知情，
            # 因此照常抛出，由上层决定是否改走抓屏通道。
            self._canvas_ready = True
            self._check(status, "mica_build_canvas_from_wallpapers")

    def build_canvas_from_dxgi(self, timeout_ms: int = 120) -> None:
        """由 DXGI Desktop Duplication 抓取桌面构建画布。

        Args:
            timeout_ms: 单个输出的等待上限（毫秒）。

        Raises:
            MicaRenderError: 超时（``MICA_ERR_CAPTURE_TIMEOUT``，旧画布保留）或
                会话不可用（``MICA_ERR_CAPTURE_UNAVAILABLE``）。
        """
        handle = self._require("build_canvas_from_dxgi")
        status = int(self._lib.mica_build_canvas_from_dxgi(handle, int(timeout_ms)))
        if status == MICA_OK:
            self._canvas_ready = True
        self._check(status, "mica_build_canvas_from_dxgi")

    def build_canvas_from_memory(self, rgb: object) -> None:
        """由调用方提供的 CPU 像素构建画布（既有 numpy 采集链的兜底通道）。

        Args:
            rgb: shape ``(h, w, 3)`` 的 C 连续 uint8 numpy 数组。

        Raises:
            MicaRenderError: 数组形状 / dtype 非法或上传失败。
        """
        handle = self._require("build_canvas_from_memory")
        import numpy as np

        arr = np.ascontiguousarray(rgb, dtype=np.uint8)
        if arr.ndim != 3 or arr.shape[2] != 3 or arr.shape[0] < 1 or arr.shape[1] < 1:
            raise MicaRenderError(
                MICA_ERR_INVALID_ARG,
                f"期望 (h, w, 3) uint8，实际 {getattr(arr, 'shape', None)}",
                "build_canvas_from_memory",
            )
        height, width = int(arr.shape[0]), int(arr.shape[1])
        ptr = arr.ctypes.data_as(POINTER(c_uint8))
        status = int(
            self._lib.mica_build_canvas_from_memory(handle, ptr, width, height, width * 3)
        )
        if status == MICA_OK:
            self._canvas_ready = True
        self._check(status, "mica_build_canvas_from_memory")

    def build_canvas_solid(self, rgb: Tuple[int, int, int]) -> None:
        """构建纯色画布（最终降级路径）。

        Args:
            rgb: 填充色。

        Raises:
            MicaRenderError: 调用失败。
        """
        handle = self._require("build_canvas_solid")
        status = int(self._lib.mica_build_canvas_solid(handle, _pack_rgb(rgb)))
        if status == MICA_OK:
            self._canvas_ready = True
        self._check(status, "mica_build_canvas_solid")

    def probe_dxgi(self) -> bool:
        """探测 DXGI 桌面复制可用性（真实打开一次会话后立即关闭）。

        Returns:
            可用则 ``True``。

        Raises:
            MicaRenderError: 探测本身失败。
        """
        handle = self._require("probe_dxgi")
        out = c_int32(0)
        self._check(
            int(self._lib.mica_dxgi_probe(handle, ctypes.byref(out))), "mica_dxgi_probe"
        )
        return bool(out.value)

    def canvas_mean_rgb(self) -> Tuple[int, int, int]:
        """读取当前画布平均色。

        Returns:
            ``(r, g, b)``。

        Raises:
            MicaRenderError: 画布未构建或读取失败。
        """
        handle = self._require("canvas_mean_rgb")
        out = c_uint32(0)
        self._check(
            int(self._lib.mica_canvas_mean_rgb(handle, ctypes.byref(out))),
            "mica_canvas_mean_rgb",
        )
        return _unpack_rgb(int(out.value))

    # -- 烘焙 -------------------------------------------------------------

    def bake(self, params: BakeParams) -> Tuple[object, BakeResult]:
        """执行一次完整烘焙。

        Args:
            params: 烘焙输入。

        Returns:
            ``(image, meta)``：``image`` 为 shape ``(grid_h, grid_w, 3)`` 的
            uint8 numpy 数组（由本方法新分配，调用方独占）；``meta`` 为
            :class:`BakeResult`。

        Raises:
            MicaRenderError: 画布未构建、参数非法或 GPU 执行失败。
        """
        handle = self._require("bake")
        import numpy as np

        grid_w, grid_h = (max(1, int(v)) for v in params.grid_size)
        wx, wy, ww, wh = (int(v) for v in params.window_rect)

        raw = _BakeParamsStruct(
            win_x=wx,
            win_y=wy,
            win_w=max(1, ww),
            win_h=max(1, wh),
            grid_w=grid_w,
            grid_h=grid_h,
            margin=max(0, int(params.margin)),
            dither=1 if params.dither else 0,
            sigma=float(params.sigma),
            gain=float(params.gain),
            chroma_cap=float(params.chroma_cap),
            alpha=float(params.alpha),
            l_ref=float(params.l_ref),
            gate_lo=float(params.gate_lo),
            gate_hi=float(params.gate_hi),
            gate_feather=float(params.gate_feather),
            g1_rgb=_pack_rgb(params.g1_rgb),
        )
        image = np.empty((grid_h, grid_w, 3), dtype=np.uint8)
        meta = _BakeResultStruct()
        status = int(
            self._lib.mica_bake(
                handle,
                ctypes.byref(raw),
                image.ctypes.data_as(POINTER(c_uint8)),
                int(image.nbytes),
                ctypes.byref(meta),
            )
        )
        self._check(status, "mica_bake")
        return image, BakeResult(
            size=(int(meta.width), int(meta.height)),
            pad_size=(int(meta.pad_width), int(meta.pad_height)),
            sample_rect=(
                float(meta.sample_x),
                float(meta.sample_y),
                float(meta.sample_w),
                float(meta.sample_h),
            ),
            duration_ms=float(meta.duration_ms),
            backend=BACKEND_NAMES.get(int(meta.backend), "none"),
        )

    # -- 生命周期 ---------------------------------------------------------

    def close(self) -> None:
        """释放上下文与全部 GPU 资源（幂等）。

        跨线程调用不会抛异常 —— 析构路径必须永远可达，否则会泄漏 GPU 资源。
        但正确用法仍应在拥有者线程上关闭。
        """
        handle = self._handle
        if handle is None:
            return
        self._handle = None
        self._canvas_ready = False
        try:
            self._lib.mica_destroy(handle)
        except Exception as exc:  # pragma: no cover - 析构路径防御
            _LOG.debug("mica_destroy 异常：%s", exc)

    def __enter__(self) -> "MicaRenderContext":
        """上下文管理器入口。"""
        return self

    def __exit__(self, *exc_info: object) -> None:
        """上下文管理器出口，释放资源。"""
        self.close()

    def __del__(self) -> None:  # pragma: no cover - 析构路径
        """兜底释放。"""
        try:
            self.close()
        except Exception:
            pass


__all__ = [
    "BACKEND_NAMES",
    "BakeParams",
    "BakeResult",
    "DeviceInfo",
    "LIBRARY_NAME",
    "MICA_ERR_CAPTURE_TIMEOUT",
    "MICA_ERR_CAPTURE_UNAVAILABLE",
    "MICA_ERR_DECODE",
    "MICA_ERR_DEVICE_LOST",
    "MICA_ERR_NO_DEVICE",
    "MICA_OK",
    "MicaRenderContext",
    "MicaRenderError",
    "MonitorLayout",
    "POSITION_CODES",
    "REQUIRED_API_VERSION",
    "STATUS_NAMES",
    "candidate_paths",
    "is_available",
    "library_path",
    "load_error",
    "load_library",
]
