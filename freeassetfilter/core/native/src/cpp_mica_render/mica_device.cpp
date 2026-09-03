// mica_device.cpp —— D3D11 / D2D / WIC 设备创建、HLSL 编译与资源池。
//
// 关键取舍
// --------
// * **运行时编译 HLSL**：``d3dcompiler_47.dll`` 自 Windows 8 起随系统提供，
//   这里用 ``LoadLibrary`` 动态加载而非静态导入，这样即使该 DLL 缺失也只是
//   返回 ``MICA_ERR_SHADER``（Python 侧降级到 CPU 管线），不会导致整个模块
//   加载失败。编译一次约 15–30 ms，只在创建上下文时发生。
// * **BGRA_SUPPORT**：D2D 互操作要求设备带该标志，否则
//   ``CreateBitmapFromDxgiSurface`` 会失败。
// * **资源池**：中间纹理按尺寸缓存复用。参数不变时连续烘焙零分配。

#include "mica_internal.h"
#include "mica_shaders.h"

#include <d3dcompiler.h>

#include <cstdarg>
#include <string>

namespace mica {

namespace {

/// 动态加载的 ``D3DCompile`` 入口，进程内只解析一次。
pD3DCompile g_compile = nullptr;
HMODULE g_compilerModule = nullptr;

/// 解析 ``D3DCompile``。返回 false 表示编译器不可用。
bool LoadCompiler() {
    if (g_compile != nullptr) {
        return true;
    }
    static const char* const kNames[] = {"d3dcompiler_47.dll", "d3dcompiler_46.dll",
                                         "d3dcompiler_43.dll"};
    for (const char* name : kNames) {
        HMODULE mod = ::LoadLibraryA(name);
        if (mod == nullptr) {
            continue;
        }
        auto fn = reinterpret_cast<pD3DCompile>(::GetProcAddress(mod, "D3DCompile"));
        if (fn != nullptr) {
            g_compilerModule = mod;
            g_compile = fn;
            return true;
        }
        ::FreeLibrary(mod);
    }
    return false;
}

/// UTF-16 -> UTF-8，失败时返回空串。
std::string ToUtf8(const wchar_t* text) {
    if (text == nullptr || text[0] == L'\0') {
        return std::string();
    }
    const int need = ::WideCharToMultiByte(CP_UTF8, 0, text, -1, nullptr, 0, nullptr, nullptr);
    if (need <= 1) {
        return std::string();
    }
    std::string out(static_cast<size_t>(need - 1), '\0');
    ::WideCharToMultiByte(CP_UTF8, 0, text, -1, out.data(), need, nullptr, nullptr);
    return out;
}

/// 编译单个着色器入口点。``source`` 为「公共内核 + 阶段源」的拼接。
mica_status CompileStage(Context* c,
                         const std::string& source,
                         const char* entry,
                         const char* target,
                         ComPtr<ID3DBlob>* outBlob) {
    ComPtr<ID3DBlob> code;
    ComPtr<ID3DBlob> errors;
    const UINT flags = D3DCOMPILE_ENABLE_STRICTNESS | D3DCOMPILE_OPTIMIZATION_LEVEL3;
    const HRESULT hr = g_compile(source.c_str(), source.size(), "mica.hlsl", nullptr, nullptr,
                                 entry, target, flags, 0, code.Put(), errors.Put());
    if (FAILED(hr)) {
        const char* msg = "无编译器诊断";
        if (errors && errors->GetBufferPointer() != nullptr) {
            msg = static_cast<const char*>(errors->GetBufferPointer());
        }
        return Fail(c, MICA_ERR_SHADER, "HLSL 编译失败 (%s/%s, hr=0x%08lX): %s", entry, target,
                    static_cast<unsigned long>(hr), msg);
    }
    *outBlob = code;
    return MICA_OK;
}

/// 创建三段像素着色器与全屏顶点着色器。
mica_status BuildShaders(Context* c) {
    if (!LoadCompiler()) {
        return Fail(c, MICA_ERR_SHADER, "无法加载 d3dcompiler_47.dll，HLSL 编译器不可用");
    }

    // 特性等级 11_0 及以上用 SM5，否则退到 SM4（Hash21 的整数位运算要求 SM4+）。
    const bool sm5 = (c->featureLevel >= D3D_FEATURE_LEVEL_11_0);
    const char* vsTarget = sm5 ? "vs_5_0" : "vs_4_0";
    const char* psTarget = sm5 ? "ps_5_0" : "ps_4_0";

    const std::string common(kMicaShaderCommon);
    const std::string srcAnalyze = common + kMicaShaderAnalyze;
    const std::string srcBlur = common + kMicaShaderBlur;
    const std::string srcComposite = common + kMicaShaderComposite;

    ComPtr<ID3DBlob> blob;
    mica_status st = CompileStage(c, common, "VsFullscreen", vsTarget, &blob);
    if (st != MICA_OK) {
        return st;
    }
    HRESULT hr = c->device->CreateVertexShader(blob->GetBufferPointer(), blob->GetBufferSize(),
                                               nullptr, c->vs.Put());
    if (FAILED(hr)) {
        return FailHr(c, MICA_ERR_SHADER, hr, "CreateVertexShader");
    }

    struct StageDesc {
        const std::string* source;
        const char* entry;
        ComPtr<ID3D11PixelShader>* slot;
    };
    const StageDesc stages[] = {
        {&srcAnalyze, "PsAnalyze", &c->psAnalyze},
        {&srcBlur, "PsBlur", &c->psBlur},
        {&srcComposite, "PsComposite", &c->psComposite},
    };
    for (const StageDesc& s : stages) {
        st = CompileStage(c, *s.source, s.entry, psTarget, &blob);
        if (st != MICA_OK) {
            return st;
        }
        hr = c->device->CreatePixelShader(blob->GetBufferPointer(), blob->GetBufferSize(), nullptr,
                                         s.slot->Put());
        if (FAILED(hr)) {
            return FailHr(c, MICA_ERR_SHADER, hr, "CreatePixelShader");
        }
    }
    return MICA_OK;
}

/// 创建采样器 / 混合 / 光栅 / 深度状态与三个常量缓冲。
mica_status BuildStates(Context* c) {
    D3D11_SAMPLER_DESC sd = {};
    sd.Filter = D3D11_FILTER_MIN_MAG_MIP_LINEAR;
    // CLAMP 直接实现了 CPU 版重采样与高斯卷积的"边缘钳制填充"语义。
    sd.AddressU = D3D11_TEXTURE_ADDRESS_CLAMP;
    sd.AddressV = D3D11_TEXTURE_ADDRESS_CLAMP;
    sd.AddressW = D3D11_TEXTURE_ADDRESS_CLAMP;
    sd.ComparisonFunc = D3D11_COMPARISON_NEVER;
    sd.MinLOD = 0.0f;
    sd.MaxLOD = D3D11_FLOAT32_MAX;
    HRESULT hr = c->device->CreateSamplerState(&sd, c->sampler.Put());
    if (FAILED(hr)) {
        return FailHr(c, MICA_ERR_INTERNAL, hr, "CreateSamplerState(linear)");
    }
    sd.Filter = D3D11_FILTER_MIN_MAG_MIP_POINT;
    hr = c->device->CreateSamplerState(&sd, c->samplerPoint.Put());
    if (FAILED(hr)) {
        return FailHr(c, MICA_ERR_INTERNAL, hr, "CreateSamplerState(point)");
    }

    D3D11_BLEND_DESC bd = {};
    bd.RenderTarget[0].BlendEnable = FALSE;
    bd.RenderTarget[0].RenderTargetWriteMask = D3D11_COLOR_WRITE_ENABLE_ALL;
    hr = c->device->CreateBlendState(&bd, c->blendOff.Put());
    if (FAILED(hr)) {
        return FailHr(c, MICA_ERR_INTERNAL, hr, "CreateBlendState");
    }

    D3D11_RASTERIZER_DESC rd = {};
    rd.FillMode = D3D11_FILL_SOLID;
    rd.CullMode = D3D11_CULL_NONE;
    rd.DepthClipEnable = TRUE;
    hr = c->device->CreateRasterizerState(&rd, c->raster.Put());
    if (FAILED(hr)) {
        return FailHr(c, MICA_ERR_INTERNAL, hr, "CreateRasterizerState");
    }

    D3D11_DEPTH_STENCIL_DESC dd = {};
    dd.DepthEnable = FALSE;
    dd.StencilEnable = FALSE;
    hr = c->device->CreateDepthStencilState(&dd, c->depthOff.Put());
    if (FAILED(hr)) {
        return FailHr(c, MICA_ERR_INTERNAL, hr, "CreateDepthStencilState");
    }

    struct CbDesc {
        UINT size;
        ComPtr<ID3D11Buffer>* slot;
        const char* name;
    };
    const CbDesc cbs[] = {
        {sizeof(AnalyzeCB), &c->cbAnalyze, "AnalyzeCB"},
        {sizeof(BlurCB), &c->cbBlur, "BlurCB"},
        {sizeof(CompositeCB), &c->cbComposite, "CompositeCB"},
    };
    for (const CbDesc& cb : cbs) {
        D3D11_BUFFER_DESC bdesc = {};
        bdesc.ByteWidth = cb.size;
        bdesc.Usage = D3D11_USAGE_DYNAMIC;
        bdesc.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
        bdesc.CPUAccessFlags = D3D11_CPU_ACCESS_WRITE;
        hr = c->device->CreateBuffer(&bdesc, nullptr, cb.slot->Put());
        if (FAILED(hr)) {
            return FailHr(c, MICA_ERR_INTERNAL, hr, cb.name);
        }
    }
    return MICA_OK;
}

/// 创建 D2D1 工厂 / 设备 / 上下文，以及 WIC 工厂。
mica_status BuildD2DAndWic(Context* c) {
    D2D1_FACTORY_OPTIONS opts = {};
    opts.debugLevel = D2D1_DEBUG_LEVEL_NONE;
    HRESULT hr = ::D2D1CreateFactory(D2D1_FACTORY_TYPE_SINGLE_THREADED,
                                     __uuidof(ID2D1Factory1), &opts,
                                     reinterpret_cast<void**>(c->d2dFactory.Put()));
    if (FAILED(hr)) {
        return FailHr(c, MICA_ERR_UNSUPPORTED, hr, "D2D1CreateFactory");
    }
    hr = c->d2dFactory->CreateDevice(c->dxgiDevice.Get(), c->d2dDevice.Put());
    if (FAILED(hr)) {
        return FailHr(c, MICA_ERR_UNSUPPORTED, hr, "ID2D1Factory1::CreateDevice");
    }
    hr = c->d2dDevice->CreateDeviceContext(D2D1_DEVICE_CONTEXT_OPTIONS_NONE, c->d2dCtx.Put());
    if (FAILED(hr)) {
        return FailHr(c, MICA_ERR_UNSUPPORTED, hr, "CreateDeviceContext");
    }

    hr = ::CoCreateInstance(CLSID_WICImagingFactory, nullptr, CLSCTX_INPROC_SERVER,
                            IID_IWICImagingFactory, c->wic.PutVoid());
    if (FAILED(hr)) {
        return FailHr(c, MICA_ERR_UNSUPPORTED, hr, "CoCreateInstance(WICImagingFactory)");
    }
    return MICA_OK;
}

}  // namespace

// ---------------------------------------------------------------------------
// 错误处理
// ---------------------------------------------------------------------------

mica_status Fail(Context* c, mica_status code, const char* fmt, ...) {
    if (c != nullptr) {
        va_list args;
        va_start(args, fmt);
        ::_vsnprintf_s(c->lastError, sizeof(c->lastError), _TRUNCATE, fmt, args);
        va_end(args);
    }
    return code;
}

mica_status FailHr(Context* c, mica_status code, HRESULT hr, const char* what) {
    return Fail(c, code, "%s 失败，hr=0x%08lX", what, static_cast<unsigned long>(hr));
}

// ---------------------------------------------------------------------------
// 设备创建
// ---------------------------------------------------------------------------

mica_status CreateDeviceAndShaders(Context* c, bool allowWarp) {
    // COM：优先复用调用线程已有的公寓；若本上下文是初始化方则记录，销毁时对称
    // 反初始化。RPC_E_CHANGED_MODE 表示线程已处于另一种公寓模型，可正常继续。
    const HRESULT coHr = ::CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    c->comInitialized = (coHr == S_OK);

    static const D3D_FEATURE_LEVEL kLevels[] = {
        D3D_FEATURE_LEVEL_11_1, D3D_FEATURE_LEVEL_11_0,
        D3D_FEATURE_LEVEL_10_1, D3D_FEATURE_LEVEL_10_0,
    };
    // BGRA_SUPPORT 是 D2D 互操作的硬性要求。
    const UINT flags = D3D11_CREATE_DEVICE_BGRA_SUPPORT;

    HRESULT hr = ::D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, flags, kLevels,
                                     ARRAYSIZE(kLevels), D3D11_SDK_VERSION, c->device.Put(),
                                     &c->featureLevel, c->ctx.Put());
    if (FAILED(hr)) {
        // 部分驱动不认识 11_1 的枚举值，去掉首项重试。
        hr = ::D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, flags, kLevels + 1,
                                 ARRAYSIZE(kLevels) - 1, D3D11_SDK_VERSION, c->device.Put(),
                                 &c->featureLevel, c->ctx.Put());
    }
    if (FAILED(hr) && allowWarp) {
        hr = ::D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_WARP, nullptr, flags, kLevels + 1,
                                 ARRAYSIZE(kLevels) - 1, D3D11_SDK_VERSION, c->device.Put(),
                                 &c->featureLevel, c->ctx.Put());
        c->useWarp = SUCCEEDED(hr);
    }
    if (FAILED(hr)) {
        return FailHr(c, MICA_ERR_NO_DEVICE, hr, "D3D11CreateDevice");
    }

    hr = c->device->QueryInterface(__uuidof(IDXGIDevice1), c->dxgiDevice.PutVoid());
    if (FAILED(hr)) {
        return FailHr(c, MICA_ERR_NO_DEVICE, hr, "QueryInterface(IDXGIDevice1)");
    }
    // 最多允许 1 帧在飞，降低桌面复制的延迟与显存占用。
    c->dxgiDevice->SetMaximumFrameLatency(1);

    ComPtr<IDXGIAdapter> baseAdapter;
    if (SUCCEEDED(c->dxgiDevice->GetAdapter(baseAdapter.Put())) && baseAdapter) {
        if (SUCCEEDED(baseAdapter->QueryInterface(__uuidof(IDXGIAdapter1),
                                                  c->adapter.PutVoid())) &&
            c->adapter) {
            DXGI_ADAPTER_DESC1 desc = {};
            if (SUCCEEDED(c->adapter->GetDesc1(&desc))) {
                c->adapterName = ToUtf8(desc.Description);
            }
        }
    }

    mica_status st = BuildShaders(c);
    if (st != MICA_OK) {
        return st;
    }
    st = BuildStates(c);
    if (st != MICA_OK) {
        return st;
    }
    return BuildD2DAndWic(c);
}

// ---------------------------------------------------------------------------
// 资源池
// ---------------------------------------------------------------------------

mica_status EnsureRenderTexture(Context* c, RenderTexture* rt, int w, int h, DXGI_FORMAT fmt) {
    w = Clamp(w, 1, kMaxPadSide);
    h = Clamp(h, 1, kMaxPadSide);
    if (rt->Matches(w, h, fmt)) {
        return MICA_OK;
    }
    rt->Reset();

    D3D11_TEXTURE2D_DESC td = {};
    td.Width = static_cast<UINT>(w);
    td.Height = static_cast<UINT>(h);
    td.MipLevels = 1;
    td.ArraySize = 1;
    td.Format = fmt;
    td.SampleDesc.Count = 1;
    td.Usage = D3D11_USAGE_DEFAULT;
    td.BindFlags = D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE;
    HRESULT hr = c->device->CreateTexture2D(&td, nullptr, rt->tex.Put());
    if (FAILED(hr)) {
        return FailHr(c, MICA_ERR_OUT_OF_MEMORY, hr, "CreateTexture2D(intermediate)");
    }
    hr = c->device->CreateRenderTargetView(rt->tex.Get(), nullptr, rt->rtv.Put());
    if (FAILED(hr)) {
        return FailHr(c, MICA_ERR_INTERNAL, hr, "CreateRenderTargetView(intermediate)");
    }
    hr = c->device->CreateShaderResourceView(rt->tex.Get(), nullptr, rt->srv.Put());
    if (FAILED(hr)) {
        return FailHr(c, MICA_ERR_INTERNAL, hr, "CreateShaderResourceView(intermediate)");
    }
    rt->width = w;
    rt->height = h;
    rt->format = fmt;
    return MICA_OK;
}

mica_status EnsureReadback(Context* c, int w, int h) {
    w = Clamp(w, 1, kMaxPadSide);
    h = Clamp(h, 1, kMaxPadSide);
    if (c->readback && c->readbackW == w && c->readbackH == h) {
        return MICA_OK;
    }
    c->readback.Reset();

    D3D11_TEXTURE2D_DESC td = {};
    td.Width = static_cast<UINT>(w);
    td.Height = static_cast<UINT>(h);
    td.MipLevels = 1;
    td.ArraySize = 1;
    td.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
    td.SampleDesc.Count = 1;
    td.Usage = D3D11_USAGE_STAGING;
    td.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    const HRESULT hr = c->device->CreateTexture2D(&td, nullptr, c->readback.Put());
    if (FAILED(hr)) {
        return FailHr(c, MICA_ERR_OUT_OF_MEMORY, hr, "CreateTexture2D(staging)");
    }
    c->readbackW = w;
    c->readbackH = h;
    return MICA_OK;
}

mica_status EnsureCanvas(Context* c, int w, int h) {
    w = Clamp(w, 1, kMaxCanvasSide);
    h = Clamp(h, 1, kMaxCanvasSide);
    if (c->canvas && c->canvasStage && c->canvasW == w && c->canvasH == h) {
        return MICA_OK;
    }
    c->canvasSrv.Reset();
    c->canvas.Reset();
    c->canvasStageRtv.Reset();
    c->canvasStage.Reset();
    c->canvasW = 0;
    c->canvasH = 0;
    c->canvasMips = 0;
    c->canvasBackend = MICA_BACKEND_NONE;

    // stage：单 mip。D2D 只能从单子资源纹理取得 IDXGISurface，故必须独立一块。
    D3D11_TEXTURE2D_DESC td = {};
    td.Width = static_cast<UINT>(w);
    td.Height = static_cast<UINT>(h);
    td.MipLevels = 1;
    td.ArraySize = 1;
    td.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
    td.SampleDesc.Count = 1;
    td.Usage = D3D11_USAGE_DEFAULT;
    td.BindFlags = D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE;
    HRESULT hr = c->device->CreateTexture2D(&td, nullptr, c->canvasStage.Put());
    if (FAILED(hr)) {
        return FailHr(c, MICA_ERR_OUT_OF_MEMORY, hr, "CreateTexture2D(canvasStage)");
    }
    hr = c->device->CreateRenderTargetView(c->canvasStage.Get(), nullptr, c->canvasStageRtv.Put());
    if (FAILED(hr)) {
        return FailHr(c, MICA_ERR_INTERNAL, hr, "CreateRenderTargetView(canvasStage)");
    }

    // canvas：完整 mip 链。PsAnalyze 用硬件三线性按 LOD 取样，等价于 CPU 版
    // 的盒式预降采样但质量更好，且成本与窗口尺寸无关。
    td.MipLevels = 0;  // 0 = 生成到 1x1 的完整链
    td.MiscFlags = D3D11_RESOURCE_MISC_GENERATE_MIPS;
    hr = c->device->CreateTexture2D(&td, nullptr, c->canvas.Put());
    if (FAILED(hr)) {
        return FailHr(c, MICA_ERR_OUT_OF_MEMORY, hr, "CreateTexture2D(canvas)");
    }
    hr = c->device->CreateShaderResourceView(c->canvas.Get(), nullptr, c->canvasSrv.Put());
    if (FAILED(hr)) {
        return FailHr(c, MICA_ERR_INTERNAL, hr, "CreateShaderResourceView(canvas)");
    }

    D3D11_TEXTURE2D_DESC actual = {};
    c->canvas->GetDesc(&actual);
    c->canvasMips = static_cast<int>(actual.MipLevels);
    c->canvasW = w;
    c->canvasH = h;
    return MICA_OK;
}

void PublishCanvas(Context* c, mica_backend backend) {
    if (!c->canvas || !c->canvasStage) {
        return;
    }
    c->ctx->CopySubresourceRegion(c->canvas.Get(), 0, 0, 0, 0, c->canvasStage.Get(), 0, nullptr);
    if (c->canvasSrv) {
        c->ctx->GenerateMips(c->canvasSrv.Get());
    }
    c->canvasBackend = backend;
}

// ---------------------------------------------------------------------------
// 绘制状态
// ---------------------------------------------------------------------------

void BindFullscreenState(Context* c) {
    ID3D11DeviceContext* dc = c->ctx.Get();
    dc->IASetInputLayout(nullptr);
    dc->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    dc->VSSetShader(c->vs.Get(), nullptr, 0);
    dc->GSSetShader(nullptr, nullptr, 0);
    dc->HSSetShader(nullptr, nullptr, 0);
    dc->DSSetShader(nullptr, nullptr, 0);
    dc->RSSetState(c->raster.Get());
    dc->OMSetDepthStencilState(c->depthOff.Get(), 0);
    const float blendFactor[4] = {0.0f, 0.0f, 0.0f, 0.0f};
    dc->OMSetBlendState(c->blendOff.Get(), blendFactor, 0xFFFFFFFFu);
    ID3D11SamplerState* samplers[] = {c->sampler.Get()};
    dc->PSSetSamplers(0, 1, samplers);
}

void SetTarget(Context* c, ID3D11RenderTargetView* rtv, int w, int h) {
    ID3D11DeviceContext* dc = c->ctx.Get();
    ID3D11RenderTargetView* targets[] = {rtv};
    dc->OMSetRenderTargets(1, targets, nullptr);
    D3D11_VIEWPORT vp = {};
    vp.TopLeftX = 0.0f;
    vp.TopLeftY = 0.0f;
    vp.Width = static_cast<float>(w);
    vp.Height = static_cast<float>(h);
    vp.MinDepth = 0.0f;
    vp.MaxDepth = 1.0f;
    dc->RSSetViewports(1, &vp);
}

void UnbindAll(Context* c) {
    ID3D11DeviceContext* dc = c->ctx.Get();
    ID3D11ShaderResourceView* nullSrv[1] = {nullptr};
    dc->PSSetShaderResources(0, 1, nullSrv);
    ID3D11RenderTargetView* nullRtv[1] = {nullptr};
    dc->OMSetRenderTargets(1, nullRtv, nullptr);
}

}  // namespace mica
