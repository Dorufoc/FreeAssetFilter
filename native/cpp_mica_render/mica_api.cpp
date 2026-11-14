// mica_api.cpp —— C ABI 导出层。
//
// 职责边界
// --------
// 本层只做三件事：参数校验、异常拦截、把调用转发到内部实现。所有 C++ 异常
// （主要来自 ``std::vector`` 分配）都在此拦截并转换为错误码，保证 ABI 边界上
// 永不抛出——否则跨越 ctypes 边界会直接终止 Python 进程。

#include "mica_internal.h"

#include <cstring>
#include <new>

using namespace mica;

namespace {

/// 上下文创建失败时上下文已被销毁，错误信息转存到此处，
/// 供 ``mica_last_error(NULL)`` 读取。
char g_createError[512] = {0};

void StoreCreateError(const char* text) {
    ::strncpy_s(g_createError, sizeof(g_createError), (text != nullptr) ? text : "未知错误",
                _TRUNCATE);
}

/// 校验上下文有效性。
bool ValidCtx(mica_context* ctx) {
    return ctx != nullptr && reinterpret_cast<Context*>(ctx)->device;
}

Context* Inner(mica_context* ctx) {
    return reinterpret_cast<Context*>(ctx);
}

}  // namespace

extern "C" {

MICA_API int32_t mica_api_version(void) {
    return MICA_API_VERSION;
}

MICA_API mica_status mica_create(int32_t allow_warp, mica_context** out_ctx) {
    if (out_ctx == nullptr) {
        StoreCreateError("out_ctx 为空");
        return MICA_ERR_INVALID_ARG;
    }
    *out_ctx = nullptr;

    Context* c = nullptr;
    try {
        c = new Context();
    } catch (const std::bad_alloc&) {
        StoreCreateError("分配上下文失败：内存不足");
        return MICA_ERR_OUT_OF_MEMORY;
    }

    mica_status st = MICA_ERR_INTERNAL;
    try {
        st = CreateDeviceAndShaders(c, allow_warp != 0);
    } catch (const std::bad_alloc&) {
        st = Fail(c, MICA_ERR_OUT_OF_MEMORY, "创建设备时内存不足");
    } catch (...) {
        st = Fail(c, MICA_ERR_INTERNAL, "创建设备时发生未知异常");
    }

    if (st != MICA_OK) {
        StoreCreateError(c->lastError);
        const bool needCoUninit = c->comInitialized;
        delete c;
        if (needCoUninit) {
            ::CoUninitialize();
        }
        return st;
    }

    *out_ctx = reinterpret_cast<mica_context*>(c);
    return MICA_OK;
}

MICA_API void mica_destroy(mica_context* ctx) {
    if (ctx == nullptr) {
        return;
    }
    Context* c = Inner(ctx);
    // 桌面复制会话必须先于设备释放。
    CloseDupls(c);
    const bool needCoUninit = c->comInitialized;
    delete c;  // ComPtr 逆序析构，释放全部 D3D/D2D/WIC 对象
    if (needCoUninit) {
        // 必须在全部 COM 对象释放之后才能反初始化。
        ::CoUninitialize();
    }
}

MICA_API const char* mica_last_error(mica_context* ctx) {
    if (ctx == nullptr) {
        return g_createError;
    }
    return Inner(ctx)->lastError;
}

MICA_API mica_status mica_get_device_info(mica_context* ctx, mica_device_info* out_info) {
    if (!ValidCtx(ctx) || out_info == nullptr) {
        return MICA_ERR_INVALID_ARG;
    }
    Context* c = Inner(ctx);
    ::memset(out_info, 0, sizeof(*out_info));
    out_info->api_version = MICA_API_VERSION;
    out_info->feature_level = static_cast<int32_t>(c->featureLevel);
    out_info->use_warp = c->useWarp ? 1 : 0;
    out_info->dxgi_available = c->dxgiAvailable;
    out_info->canvas_width = c->canvasW;
    out_info->canvas_height = c->canvasH;
    out_info->canvas_mips = c->canvasMips;
    out_info->canvas_backend = static_cast<int32_t>(c->canvasBackend);
    ::strncpy_s(out_info->adapter, sizeof(out_info->adapter), c->adapterName.c_str(), _TRUNCATE);
    return MICA_OK;
}

MICA_API mica_status mica_set_virtual_desktop(mica_context* ctx,
                                             int32_t vx,
                                             int32_t vy,
                                             int32_t vw,
                                             int32_t vh,
                                             int32_t max_long_side) {
    if (!ValidCtx(ctx)) {
        return MICA_ERR_INVALID_ARG;
    }
    Context* c = Inner(ctx);
    if (vw <= 0 || vh <= 0) {
        return Fail(c, MICA_ERR_INVALID_ARG, "虚拟桌面尺寸无效 (%dx%d)", vw, vh);
    }
    c->vx = vx;
    c->vy = vy;
    c->vw = vw;
    c->vh = vh;
    c->maxLongSide = Clamp(max_long_side > 0 ? max_long_side : 1600, 64, kMaxCanvasSide);
    c->canvasScale = CanvasScaleFor(vw, vh, c->maxLongSide);
    // 几何变化意味着旧画布尺寸失效，标记为未构建，强制下一次重建。
    c->canvasBackend = MICA_BACKEND_NONE;
    return MICA_OK;
}

MICA_API mica_status mica_build_canvas_from_wallpapers(mica_context* ctx,
                                                      const mica_monitor_layout* layouts,
                                                      int32_t count,
                                                      uint32_t fallback_rgb) {
    if (!ValidCtx(ctx)) {
        return MICA_ERR_INVALID_ARG;
    }
    Context* c = Inner(ctx);
    try {
        return BuildCanvasFromWallpapers(c, layouts, static_cast<int>(count), fallback_rgb);
    } catch (const std::bad_alloc&) {
        return Fail(c, MICA_ERR_OUT_OF_MEMORY, "构建壁纸画布时内存不足");
    } catch (...) {
        return Fail(c, MICA_ERR_INTERNAL, "构建壁纸画布时发生未知异常");
    }
}

MICA_API mica_status mica_build_canvas_from_dxgi(mica_context* ctx, int32_t timeout_ms) {
    if (!ValidCtx(ctx)) {
        return MICA_ERR_INVALID_ARG;
    }
    Context* c = Inner(ctx);
    try {
        return BuildCanvasFromDxgi(c, static_cast<int>(timeout_ms));
    } catch (const std::bad_alloc&) {
        return Fail(c, MICA_ERR_OUT_OF_MEMORY, "桌面复制时内存不足");
    } catch (...) {
        return Fail(c, MICA_ERR_INTERNAL, "桌面复制时发生未知异常");
    }
}

MICA_API mica_status mica_build_canvas_from_memory(mica_context* ctx,
                                                   const uint8_t* rgb,
                                                   int32_t width,
                                                   int32_t height,
                                                   int32_t stride) {
    if (!ValidCtx(ctx)) {
        return MICA_ERR_INVALID_ARG;
    }
    Context* c = Inner(ctx);
    try {
        return BuildCanvasFromMemory(c, rgb, static_cast<int>(width), static_cast<int>(height),
                                     static_cast<int>(stride));
    } catch (const std::bad_alloc&) {
        return Fail(c, MICA_ERR_OUT_OF_MEMORY, "上传画布时内存不足");
    } catch (...) {
        return Fail(c, MICA_ERR_INTERNAL, "上传画布时发生未知异常");
    }
}

MICA_API mica_status mica_build_canvas_solid(mica_context* ctx, uint32_t rgb) {
    if (!ValidCtx(ctx)) {
        return MICA_ERR_INVALID_ARG;
    }
    Context* c = Inner(ctx);
    try {
        return BuildCanvasSolid(c, rgb);
    } catch (...) {
        return Fail(c, MICA_ERR_INTERNAL, "构建纯色画布时发生未知异常");
    }
}

MICA_API mica_status mica_dxgi_probe(mica_context* ctx, int32_t* out_available) {
    if (!ValidCtx(ctx)) {
        return MICA_ERR_INVALID_ARG;
    }
    Context* c = Inner(ctx);
    int available = 0;
    mica_status st;
    try {
        st = ProbeDxgi(c, &available);
    } catch (...) {
        available = 0;
        st = Fail(c, MICA_ERR_INTERNAL, "探测桌面复制时发生未知异常");
    }
    if (out_available != nullptr) {
        *out_available = static_cast<int32_t>(available);
    }
    return st;
}

MICA_API mica_status mica_canvas_mean_rgb(mica_context* ctx, uint32_t* out_rgb) {
    if (!ValidCtx(ctx)) {
        return MICA_ERR_INVALID_ARG;
    }
    Context* c = Inner(ctx);
    try {
        return CanvasMeanRgb(c, out_rgb);
    } catch (...) {
        return Fail(c, MICA_ERR_INTERNAL, "读取画布平均色时发生未知异常");
    }
}

MICA_API mica_status mica_bake(mica_context* ctx,
                              const mica_bake_params* params,
                              uint8_t* out_rgb,
                              int32_t out_capacity,
                              mica_bake_result* out_result) {
    if (!ValidCtx(ctx)) {
        return MICA_ERR_INVALID_ARG;
    }
    Context* c = Inner(ctx);
    try {
        return RunBake(c, params, out_rgb, static_cast<int>(out_capacity), out_result);
    } catch (const std::bad_alloc&) {
        return Fail(c, MICA_ERR_OUT_OF_MEMORY, "烘焙时内存不足");
    } catch (...) {
        return Fail(c, MICA_ERR_INTERNAL, "烘焙时发生未知异常");
    }
}

MICA_API mica_status mica_bake_f32(mica_context* ctx,
                                   const mica_bake_params* params,
                                   float* out_rgb,
                                   int32_t out_capacity,
                                   mica_bake_result* out_result) {
    if (!ValidCtx(ctx) || out_rgb == nullptr) {
        return MICA_ERR_INVALID_ARG;
    }
    Context* c = Inner(ctx);
    try {
        return RunBakeFloat(c, params, out_rgb, static_cast<int>(out_capacity), out_result);
    } catch (const std::bad_alloc&) {
        return Fail(c, MICA_ERR_OUT_OF_MEMORY, "烘焙(f32)时内存不足");
    } catch (...) {
        return Fail(c, MICA_ERR_INTERNAL, "烘焙(f32)时发生未知异常");
    }
}

}  // extern "C"
