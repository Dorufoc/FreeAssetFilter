// mica_internal.h —— 原生库内部共享类型：智能指针、上下文结构、工具函数。
//
// 本头文件不对外导出，仅在 ``mica_*.cpp`` 之间共享。所有 COM 对象通过
// :class:`ComPtr` 管理，保证任何返回路径（含早退与异常安全点）都不泄漏。

#ifndef FAF_MICA_INTERNAL_H
#define FAF_MICA_INTERNAL_H

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif

#include <windows.h>

#include <d2d1_1.h>
#include <d3d11.h>
#include <dxgi1_2.h>
#include <wincodec.h>

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>

#include "mica_render.h"

namespace mica {

// ---------------------------------------------------------------------------
// COM 智能指针
// ---------------------------------------------------------------------------

/// 极简 COM 引用计数包装。刻意不引入 WRL/ATL，避免对特定 SDK 组件的依赖。
template <typename T>
class ComPtr {
public:
    ComPtr() noexcept : ptr_(nullptr) {}
    ComPtr(const ComPtr& other) noexcept : ptr_(other.ptr_) {
        if (ptr_ != nullptr) {
            ptr_->AddRef();
        }
    }
    ComPtr(ComPtr&& other) noexcept : ptr_(other.ptr_) { other.ptr_ = nullptr; }
    ~ComPtr() { Reset(); }

    ComPtr& operator=(const ComPtr& other) noexcept {
        if (this != &other) {
            T* old = ptr_;
            ptr_ = other.ptr_;
            if (ptr_ != nullptr) {
                ptr_->AddRef();
            }
            if (old != nullptr) {
                old->Release();
            }
        }
        return *this;
    }

    ComPtr& operator=(ComPtr&& other) noexcept {
        if (this != &other) {
            Reset();
            ptr_ = other.ptr_;
            other.ptr_ = nullptr;
        }
        return *this;
    }

    void Reset() noexcept {
        if (ptr_ != nullptr) {
            ptr_->Release();
            ptr_ = nullptr;
        }
    }

    /// 供 ``CreateXxx(&p)`` 出参使用，调用前先释放旧值。
    T** Put() noexcept {
        Reset();
        return &ptr_;
    }

    /// 供需要 ``void**`` 的接口（如 ``QueryInterface``）使用。
    void** PutVoid() noexcept { return reinterpret_cast<void**>(Put()); }

    T* Get() const noexcept { return ptr_; }
    T* operator->() const noexcept { return ptr_; }
    explicit operator bool() const noexcept { return ptr_ != nullptr; }

private:
    T* ptr_;
};

// ---------------------------------------------------------------------------
// 常量
// ---------------------------------------------------------------------------

/// 高斯半径硬上限（纹素）。σ 上限 40 -> ceil(3σ) = 120，留少量余量。
constexpr int kMaxBlurRadius = 128;

/// 含扩边中间纹理的尺寸上限，超出则钳制（正常参数下 pad <= ~400）。
constexpr int kMaxPadSide = 1024;

/// 画布长边硬上限，防止调用方传入过大值耗尽显存。
constexpr int kMaxCanvasSide = 4096;

/// 高斯半径系数，对应 ``tint._gaussian_kernel`` 的 3σ。
constexpr float kGaussianRadiusSigmas = 3.0f;

/// 求画布均值时回读的 mip 长边上限（纹素）。
///
/// 取 128 而非 1：NPOT 纹理的 mip 链在奇数维度上按 2x2 盒式降采样会丢弃末行/
/// 末列，越深层丢弃占比越大（3x1 -> 1x1 丢 1/3），1x1 已严重偏向左上角。
/// 在长边 <= 128 的中层 mip 上做 CPU 求和，截断误差 < 1%，回读量 <= 64 KB。
constexpr int kMeanMipMaxSide = 128;

// ---------------------------------------------------------------------------
// 常量缓冲布局（须与 mica_shaders.h 中的 cbuffer 逐字段对应）
// ---------------------------------------------------------------------------

/// 对应 ``AnalyzeCB``。
struct AnalyzeCB {
    float srcRect[4];     ///< x, y, w, h（虚拟桌面像素）
    float canvas[4];      ///< canvasW, canvasH, canvasScale, lodBias
    float virtualOrg[4];  ///< vx, vy, 0, 0
    float gate[4];        ///< lo, hi, feather, 0
};

/// 对应 ``BlurCB``。
struct BlurCB {
    float step[4];    ///< dx, dy, 0, 0（纹素归一化步进）
    float kernel[4];  ///< sigma, radius, invTwoSigmaSq, 0
};

/// 对应 ``CompositeCB``。
struct CompositeCB {
    float shape[4];  ///< gain, chromaCap, alpha, lRef
    float base[4];   ///< g1R, g1G, g1B, ditherEnabled
    float geom[4];   ///< margin, padW, padH, 0
};

static_assert(sizeof(AnalyzeCB) % 16 == 0, "常量缓冲必须 16 字节对齐");
static_assert(sizeof(BlurCB) % 16 == 0, "常量缓冲必须 16 字节对齐");
static_assert(sizeof(CompositeCB) % 16 == 0, "常量缓冲必须 16 字节对齐");

// ---------------------------------------------------------------------------
// 中间纹理对
// ---------------------------------------------------------------------------

/// 一块可作为渲染目标与着色器资源的纹理。
struct RenderTexture {
    ComPtr<ID3D11Texture2D> tex;
    ComPtr<ID3D11RenderTargetView> rtv;
    ComPtr<ID3D11ShaderResourceView> srv;
    int width = 0;
    int height = 0;
    DXGI_FORMAT format = DXGI_FORMAT_UNKNOWN;

    bool Matches(int w, int h, DXGI_FORMAT f) const noexcept {
        return tex && width == w && height == h && format == f;
    }
    void Reset() noexcept {
        srv.Reset();
        rtv.Reset();
        tex.Reset();
        width = 0;
        height = 0;
        format = DXGI_FORMAT_UNKNOWN;
    }
};

// ---------------------------------------------------------------------------
// DXGI 桌面复制会话
// ---------------------------------------------------------------------------

/// 单个输出（显示器）的桌面复制会话。
struct DuplOutput {
    ComPtr<IDXGIOutputDuplication> dupl;
    RECT bounds{};       ///< 该输出在虚拟桌面中的矩形
    DXGI_MODE_ROTATION rotation = DXGI_MODE_ROTATION_UNSPECIFIED;
};

// ---------------------------------------------------------------------------
// 上下文
// ---------------------------------------------------------------------------

/// 渲染上下文。非线程安全——调用方（Python 桥接层）负责串行化。
struct Context {
    // --- 设备 ---
    ComPtr<ID3D11Device> device;
    ComPtr<ID3D11DeviceContext> ctx;
    ComPtr<IDXGIDevice1> dxgiDevice;
    ComPtr<IDXGIAdapter1> adapter;
    ComPtr<ID2D1Factory1> d2dFactory;
    ComPtr<ID2D1Device> d2dDevice;
    ComPtr<ID2D1DeviceContext> d2dCtx;
    ComPtr<IWICImagingFactory> wic;
    D3D_FEATURE_LEVEL featureLevel = static_cast<D3D_FEATURE_LEVEL>(0);
    bool useWarp = false;
    std::string adapterName;

    // --- 着色器 ---
    ComPtr<ID3D11VertexShader> vs;
    ComPtr<ID3D11PixelShader> psAnalyze;
    ComPtr<ID3D11PixelShader> psBlur;
    ComPtr<ID3D11PixelShader> psComposite;
    ComPtr<ID3D11SamplerState> sampler;      ///< 三线性 + CLAMP
    ComPtr<ID3D11SamplerState> samplerPoint; ///< 未使用的备用点采样器
    ComPtr<ID3D11BlendState> blendOff;
    ComPtr<ID3D11RasterizerState> raster;
    ComPtr<ID3D11DepthStencilState> depthOff;
    ComPtr<ID3D11Buffer> cbAnalyze;
    ComPtr<ID3D11Buffer> cbBlur;
    ComPtr<ID3D11Buffer> cbComposite;

    // --- 画布 ---
    // 分两块：``canvasStage`` 单 mip，供 D2D / DXGI 拷贝写入（D2D 只能绑定
    // 单子资源纹理）；``canvas`` 带完整 mip 链，供 PsAnalyze 采样。写入完成后
    // 由 stage 拷到 canvas 的 mip0 再 GenerateMips。
    ComPtr<ID3D11Texture2D> canvasStage;
    ComPtr<ID3D11RenderTargetView> canvasStageRtv;
    ComPtr<ID3D11Texture2D> canvas;
    ComPtr<ID3D11ShaderResourceView> canvasSrv;
    /// ``MEAN_MIP_MAX_SIDE`` 方形 STAGING，用于回读中层 mip 求画布均值。
    /// 不读最深的 1x1 mip：NPOT 纹理在 mip 链末端的奇数维度截断会丢弃末行/末列，
    /// 深层放大后（如 3x1 -> 1x1 丢 1/3）使 1x1 严重偏向左上角。
    ComPtr<ID3D11Texture2D> meanStaging;
    int canvasW = 0;
    int canvasH = 0;
    int canvasMips = 0;
    float canvasScale = 1.0f;
    mica_backend canvasBackend = MICA_BACKEND_NONE;

    // --- 虚拟桌面 ---
    int vx = 0;
    int vy = 0;
    int vw = 0;
    int vh = 0;
    int maxLongSide = 1600;

    // --- 中间纹理（按 pad 尺寸缓存复用）---
    RenderTexture stageA;  ///< 分析输出 / 模糊乒乓 A（RGBA16F）
    RenderTexture stageB;  ///< 模糊乒乓 B（RGBA16F）
    RenderTexture outTex;  ///< 合成输出（BGRA8）
    ComPtr<ID3D11Texture2D> readback;  ///< STAGING 回读纹理
    int readbackW = 0;
    int readbackH = 0;

    // --- DXGI 桌面复制 ---
    std::vector<DuplOutput> dupls;
    int dxgiAvailable = -1;  ///< -1 未探测，0 不可用，1 可用

    // --- COM ---
    /// 本上下文是否是 COM 的初始化方（决定销毁时是否 CoUninitialize）
    bool comInitialized = false;

    // --- 错误信息 ---
    char lastError[512] = {0};
};

// ---------------------------------------------------------------------------
// 错误处理
// ---------------------------------------------------------------------------

/// 记录格式化错误信息到上下文并返回给定状态码。
mica_status Fail(Context* c, mica_status code, const char* fmt, ...);

/// 记录带 HRESULT 的错误信息。
mica_status FailHr(Context* c, mica_status code, HRESULT hr, const char* what);

// ---------------------------------------------------------------------------
// 设备与资源（mica_device.cpp）
// ---------------------------------------------------------------------------

mica_status CreateDeviceAndShaders(Context* c, bool allowWarp);
mica_status EnsureRenderTexture(Context* c, RenderTexture* rt, int w, int h, DXGI_FORMAT fmt);
mica_status EnsureReadback(Context* c, int w, int h);

/// 按需（重）建画布纹理对：``canvasStage``（单 mip，可作 RT）与 ``canvas``
/// （完整 mip 链，可采样）。尺寸不变时复用，避免每次壁纸变化都重新分配显存。
mica_status EnsureCanvas(Context* c, int w, int h);

/// 把 ``canvasStage`` 的内容提交为新画布：拷到 ``canvas`` mip0 并生成 mip 链。
void PublishCanvas(Context* c, mica_backend backend);

/// 绑定全屏三角形绘制所需的固定状态（IA/RS/OM/VS），随后调用方只需设置
/// PS、SRV、CB 与视口即可 ``Draw(3, 0)``。
void BindFullscreenState(Context* c);

/// 设置渲染目标 + 视口并可选清空。
void SetTarget(Context* c, ID3D11RenderTargetView* rtv, int w, int h);

/// 解绑所有 SRV / RTV，避免下一 pass 出现读写同一资源的冲突警告。
void UnbindAll(Context* c);

// ---------------------------------------------------------------------------
// 画布来源（mica_capture.cpp）
// ---------------------------------------------------------------------------

mica_status BuildCanvasFromWallpapers(Context* c,
                                      const mica_monitor_layout* layouts,
                                      int count,
                                      uint32_t fallbackRgb);
mica_status BuildCanvasFromDxgi(Context* c, int timeoutMs);
mica_status BuildCanvasFromMemory(Context* c, const uint8_t* rgb, int w, int h, int stride);
mica_status BuildCanvasSolid(Context* c, uint32_t rgb);
mica_status ProbeDxgi(Context* c, int* outAvailable);
void CloseDupls(Context* c);

// ---------------------------------------------------------------------------
// 管线（mica_pipeline.cpp）
// ---------------------------------------------------------------------------

mica_status RunBake(Context* c,
                    const mica_bake_params* p,
                    uint8_t* outRgb,
                    int capacity,
                    mica_bake_result* outResult);
mica_status CanvasMeanRgb(Context* c, uint32_t* outRgb);

// ---------------------------------------------------------------------------
// 小工具
// ---------------------------------------------------------------------------

/// ``0x00RRGGBB`` -> 归一化 sRGB 三元组。
inline void UnpackRgb(uint32_t packed, float out[3]) noexcept {
    out[0] = static_cast<float>((packed >> 16) & 0xFFu) / 255.0f;
    out[1] = static_cast<float>((packed >> 8) & 0xFFu) / 255.0f;
    out[2] = static_cast<float>(packed & 0xFFu) / 255.0f;
}

/// 画布像素 / 虚拟桌面像素，对应 ``mica.source._canvas_scale``。
inline float CanvasScaleFor(int vw, int vh, int maxLong) noexcept {
    const int longSide = (vw > vh) ? vw : vh;
    if (longSide <= 0 || maxLong <= 0 || longSide <= maxLong) {
        return 1.0f;
    }
    return static_cast<float>(maxLong) / static_cast<float>(longSide);
}

template <typename T>
inline T Clamp(T v, T lo, T hi) noexcept {
    return (v < lo) ? lo : ((v > hi) ? hi : v);
}

}  // namespace mica

#endif  // FAF_MICA_INTERNAL_H
