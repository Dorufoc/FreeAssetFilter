"""mica_render.dll 的最小加载冒烟测试。

独立运行，不依赖项目包结构：直接按相对路径定位 ``core/native/bin/mica_render.dll``，
逐项验证导出符号、API 版本、D3D11 设备创建、DXGI 探测与一次真实烘焙。

用法::

    python smoke_test.py
"""

from __future__ import annotations

import ctypes
import math
import sys
import time
from ctypes import wintypes
from pathlib import Path

HERE = Path(__file__).resolve().parent
DLL_PATH = HERE.parents[1] / "bin" / "mica_render.dll"

EXPORTS = (
    "mica_api_version",
    "mica_create",
    "mica_destroy",
    "mica_get_device_info",
    "mica_last_error",
    "mica_set_virtual_desktop",
    "mica_build_canvas_from_wallpapers",
    "mica_build_canvas_from_dxgi",
    "mica_build_canvas_from_memory",
    "mica_build_canvas_solid",
    "mica_dxgi_probe",
    "mica_canvas_mean_rgb",
    "mica_bake",
    "mica_bake_f32",
)

STATUS_NAMES = {
    0: "OK",
    1: "INVALID_ARG",
    2: "NO_DEVICE",
    3: "DEVICE_LOST",
    4: "NO_SOURCE",
    5: "SHADER",
    6: "CAPTURE_TIMEOUT",
    7: "CAPTURE_UNAVAILABLE",
    8: "DECODE",
    9: "OUT_OF_MEMORY",
    10: "UNSUPPORTED",
    11: "INTERNAL",
}

BACKEND_NAMES = {0: "NONE", 1: "WALLPAPER", 2: "DXGI", 3: "MEMORY", 4: "SOLID"}


class DeviceInfo(ctypes.Structure):
    """对应 C 侧 ``mica_device_info``。"""

    _pack_ = 4
    _fields_ = [
        ("api_version", ctypes.c_uint32),
        ("feature_level", ctypes.c_uint32),
        ("use_warp", ctypes.c_int32),
        ("dxgi_available", ctypes.c_int32),
        ("canvas_width", ctypes.c_uint32),
        ("canvas_height", ctypes.c_uint32),
        ("canvas_mips", ctypes.c_uint32),
        ("canvas_backend", ctypes.c_uint32),
        ("adapter", ctypes.c_char * 128),
    ]


class BakeParams(ctypes.Structure):
    """对应 C 侧 ``mica_bake_params``。"""

    _pack_ = 4
    _fields_ = [
        ("win_x", ctypes.c_int32),
        ("win_y", ctypes.c_int32),
        ("win_w", ctypes.c_int32),
        ("win_h", ctypes.c_int32),
        ("grid_w", ctypes.c_uint32),
        ("grid_h", ctypes.c_uint32),
        ("margin", ctypes.c_uint32),
        ("dither", ctypes.c_int32),
        ("sigma", ctypes.c_float),
        ("gain", ctypes.c_float),
        ("chroma_cap", ctypes.c_float),
        ("alpha", ctypes.c_float),
        ("l_ref", ctypes.c_float),
        ("gate_lo", ctypes.c_float),
        ("gate_hi", ctypes.c_float),
        ("gate_feather", ctypes.c_float),
        ("g1_rgb", ctypes.c_uint32),
    ]


class BakeResult(ctypes.Structure):
    """对应 C 侧 ``mica_bake_result``。"""

    _pack_ = 4
    _fields_ = [
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("pad_width", ctypes.c_uint32),
        ("pad_height", ctypes.c_uint32),
        ("sample_x", ctypes.c_float),
        ("sample_y", ctypes.c_float),
        ("sample_w", ctypes.c_float),
        ("sample_h", ctypes.c_float),
        ("duration_ms", ctypes.c_float),
        ("backend", ctypes.c_uint32),
    ]


def status_text(code: int) -> str:
    """把状态码转成可读文本。"""
    return f"{STATUS_NAMES.get(code, '?')}({code})"


def main() -> int:
    """执行冒烟测试，返回进程退出码。"""
    print(f"DLL: {DLL_PATH}")
    if not DLL_PATH.exists():
        print("  [FAIL] 文件不存在")
        return 1
    print(f"  size = {DLL_PATH.stat().st_size / 1024:.1f} KB")

    try:
        dll = ctypes.WinDLL(str(DLL_PATH))
    except OSError as exc:
        print(f"  [FAIL] 加载失败: {exc}")
        return 1
    print("  [OK] WinDLL 加载成功")

    missing = []
    for name in EXPORTS:
        if not hasattr(dll, name):
            missing.append(name)
    if missing:
        print(f"  [FAIL] 缺失导出: {missing}")
        return 1
    print(f"  [OK] {len(EXPORTS)} 个导出符号齐全")

    dll.mica_api_version.restype = ctypes.c_uint32
    dll.mica_api_version.argtypes = []
    ver = dll.mica_api_version()
    print(f"  mica_api_version == {ver}")
    if ver != 2:
        print("  [FAIL] 版本号不符（应为 2）")
        return 1

    dll.mica_create.restype = ctypes.c_int32
    dll.mica_create.argtypes = [ctypes.c_int32, ctypes.POINTER(ctypes.c_void_p)]
    dll.mica_destroy.restype = None
    dll.mica_destroy.argtypes = [ctypes.c_void_p]
    dll.mica_last_error.restype = ctypes.c_char_p
    dll.mica_last_error.argtypes = [ctypes.c_void_p]
    dll.mica_get_device_info.restype = ctypes.c_int32
    dll.mica_get_device_info.argtypes = [ctypes.c_void_p, ctypes.POINTER(DeviceInfo)]
    dll.mica_set_virtual_desktop.restype = ctypes.c_int32
    dll.mica_set_virtual_desktop.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int32,
        ctypes.c_int32,
        ctypes.c_int32,
        ctypes.c_int32,
        ctypes.c_uint32,
    ]
    dll.mica_build_canvas_from_memory.restype = ctypes.c_int32
    dll.mica_build_canvas_from_memory.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
    ]
    dll.mica_build_canvas_solid.restype = ctypes.c_int32
    dll.mica_build_canvas_solid.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    dll.mica_dxgi_probe.restype = ctypes.c_int32
    dll.mica_dxgi_probe.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int32)]
    dll.mica_canvas_mean_rgb.restype = ctypes.c_int32
    dll.mica_canvas_mean_rgb.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    dll.mica_bake.restype = ctypes.c_int32
    dll.mica_bake.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(BakeParams),
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(BakeResult),
    ]
    dll.mica_bake_f32.restype = ctypes.c_int32
    dll.mica_bake_f32.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(BakeParams),
        ctypes.POINTER(ctypes.c_float),
        ctypes.c_int32,
        ctypes.POINTER(BakeResult),
    ]

    ctx = ctypes.c_void_p()
    st = dll.mica_create(1, ctypes.byref(ctx))
    print(f"  mica_create -> {status_text(st)}")
    if st != 0:
        print(f"  [FAIL] {dll.mica_last_error(None)}")
        return 1

    try:
        info = DeviceInfo()
        st = dll.mica_get_device_info(ctx, ctypes.byref(info))
        print(f"  mica_get_device_info -> {status_text(st)}")
        print(f"    adapter       = {info.adapter.decode('utf-8', 'replace')}")
        print(f"    feature_level = 0x{info.feature_level:04X}")
        print(f"    use_warp      = {info.use_warp}")

        avail = ctypes.c_int32()
        t0 = time.perf_counter()
        st = dll.mica_dxgi_probe(ctx, ctypes.byref(avail))
        dt = (time.perf_counter() - t0) * 1000.0
        print(f"  mica_dxgi_probe -> {status_text(st)} available={avail.value} ({dt:.1f} ms)")

        st = dll.mica_set_virtual_desktop(ctx, 0, 0, 2560, 1440, 1600)
        print(f"  mica_set_virtual_desktop -> {status_text(st)}")
        if st != 0:
            print(f"  [FAIL] {dll.mica_last_error(ctx).decode('utf-8', 'replace')}")
            return 1

        # 构造一张 64x64 的合成渐变作为内存画布来源。
        w, h = 64, 64
        buf = bytearray(w * h * 3)
        for y in range(h):
            for x in range(w):
                i = (y * w + x) * 3
                buf[i] = int(255 * x / (w - 1))
                buf[i + 1] = int(255 * y / (h - 1))
                buf[i + 2] = 128
        raw = (ctypes.c_ubyte * len(buf)).from_buffer(buf)
        st = dll.mica_build_canvas_from_memory(ctx, raw, w, h, w * 3)
        print(f"  mica_build_canvas_from_memory -> {status_text(st)}")
        if st != 0:
            print(f"  [FAIL] {dll.mica_last_error(ctx).decode('utf-8', 'replace')}")
            return 1

        mean = ctypes.c_uint32()
        st = dll.mica_canvas_mean_rgb(ctx, ctypes.byref(mean))
        print(
            f"  mica_canvas_mean_rgb -> {status_text(st)} "
            f"#{(mean.value >> 16) & 0xFF:02X}{(mean.value >> 8) & 0xFF:02X}{mean.value & 0xFF:02X}"
        )

        st = dll.mica_get_device_info(ctx, ctypes.byref(info))
        print(
            f"    canvas = {info.canvas_width}x{info.canvas_height} "
            f"mips={info.canvas_mips} backend={BACKEND_NAMES.get(info.canvas_backend)}"
        )

        params = BakeParams(
            win_x=100,
            win_y=100,
            win_w=1200,
            win_h=800,
            grid_w=192,
            grid_h=128,
            margin=8,
            dither=1,
            sigma=24.0,
            gain=1.35,
            chroma_cap=0.045,
            alpha=0.85,
            l_ref=0.32,
            gate_lo=0.02,
            gate_hi=0.98,
            gate_feather=0.06,
            g1_rgb=0x00202020,
        )
        cap = 192 * 128 * 3
        out = (ctypes.c_ubyte * cap)()
        res = BakeResult()

        for i in range(3):
            t0 = time.perf_counter()
            st = dll.mica_bake(ctx, ctypes.byref(params), out, cap, ctypes.byref(res))
            dt = (time.perf_counter() - t0) * 1000.0
            if st != 0:
                print(f"  mica_bake -> {status_text(st)}")
                print(f"  [FAIL] {dll.mica_last_error(ctx).decode('utf-8', 'replace')}")
                return 1
            print(
                f"  mica_bake #{i} -> OK {res.width}x{res.height} "
                f"pad={res.pad_width}x{res.pad_height} "
                f"gpu={res.duration_ms:.2f} ms wall={dt:.2f} ms "
                f"backend={BACKEND_NAMES.get(res.backend)}"
            )

        px = [tuple(out[j * 3 : j * 3 + 3]) for j in (0, 100, 5000, 192 * 128 - 1)]
        print(f"    样本像素 = {px}")
        if all(p == (0, 0, 0) for p in px):
            print("  [WARN] 全部样本为纯黑，可能未真正渲染")

        st = dll.mica_build_canvas_solid(ctx, 0x00336699)
        print(f"  mica_build_canvas_solid -> {status_text(st)}")
        st = dll.mica_bake(ctx, ctypes.byref(params), out, cap, ctypes.byref(res))
        print(f"  mica_bake(solid) -> {status_text(st)} 首像素={tuple(out[0:3])}")

        # --- v2: mica_bake_f32 最小 float32 往返 ---------------------------------
        # 校验符号存在（getattr 不应抛 AttributeError）。
        try:
            bake_f32_fn = getattr(dll, "mica_bake_f32")
        except AttributeError as exc:
            print(f"  [FAIL] 缺失导出 mica_bake_f32: {exc}")
            return 1
        if bake_f32_fn is None:
            print("  [FAIL] mica_bake_f32 解析为 None")
            return 1
        print("  [OK] mica_bake_f32 导出存在（getattr 解析成功）")

        fw, fh = 32, 32
        fparams = BakeParams(
            win_x=100,
            win_y=100,
            win_w=1200,
            win_h=800,
            grid_w=fw,
            grid_h=fh,
            margin=8,
            dither=1,
            sigma=24.0,
            gain=1.35,
            chroma_cap=0.045,
            alpha=0.85,
            l_ref=0.32,
            gate_lo=0.02,
            gate_hi=0.98,
            gate_feather=0.06,
            g1_rgb=0x00202020,
        )
        fcount = fw * fh * 3
        out_f32 = (ctypes.c_float * fcount)()  # float32 RGB，行主序
        fres = BakeResult()
        st = dll.mica_build_canvas_solid(ctx, 0x00336699)
        if st != 0:
            print(f"  [FAIL] mica_build_canvas_solid(f32) -> {status_text(st)}")
            return 1
        st = dll.mica_bake_f32(ctx, ctypes.byref(fparams), out_f32, fcount * 4, ctypes.byref(fres))
        print(f"  mica_bake_f32({fw}x{fh}) -> {status_text(st)}")
        if st != 0:
            print(f"  [FAIL] {dll.mica_last_error(ctx).decode('utf-8', 'replace')}")
            return 1

        finite = all(math.isfinite(float(v)) for v in out_f32)
        in_range = all(0.0 <= float(v) <= 1.0 for v in out_f32)
        mn = min(float(v) for v in out_f32)
        mx = max(float(v) for v in out_f32)
        print(
            f"    grid={fres.width}x{fres.height} pad={fres.pad_width}x{fres.pad_height} "
            f"backend={BACKEND_NAMES.get(fres.backend)}"
        )
        print(f"    float[0:6] = {[round(float(out_f32[i]), 5) for i in range(6)]}")
        print(f"    range=[{mn:.5f}, {mx:.5f}] finite={finite} in_[0,1]={in_range}")
        if st != 0 or not finite or not in_range:
            print("  [FAIL] float32 输出非有限或超出 [0,1] sRGB")
            return 1
        print("  [OK] float32 往返：返回 MICA_OK 且数值有限、位于 [0,1] sRGB")

        # --- malformed: undersized out_capacity 应返回 INVALID_ARG 而非崩溃 -------
        small = (ctypes.c_float * 1)()
        st_small = dll.mica_bake_f32(ctx, ctypes.byref(fparams), small, 4, ctypes.byref(fres))
        print(f"  mica_bake_f32(undersized capacity=4) -> {status_text(st_small)}")
        if st_small != 1:
            print("  [FAIL] undersized buffer 未返回 MICA_ERR_INVALID_ARG(1)")
            return 1
        print("  [OK] undersized buffer 返回 MICA_ERR_INVALID_ARG")
    finally:
        dll.mica_destroy(ctx)
        print("  mica_destroy -> done")

    print("\n[PASS] 冒烟测试通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
