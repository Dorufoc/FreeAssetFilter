//
// render_context.cpp - D3D11 + D2D1 + DirectWrite + DirectComposition 渲染底座实现。
//
#include "render/render_context.h"

#include <d2d1_1helper.h>

namespace faf {

namespace {

// 创建 D3D11 设备。必须带 D3D11_CREATE_DEVICE_BGRA_SUPPORT（D2D 与 BGRA 交换链互操作前提）。
// 若目标运行时不认识 D3D_FEATURE_LEVEL_11_1（Win8 之前），去掉后重试。
HRESULT CreateD3D11Device(D3D_DRIVER_TYPE driverType, ID3D11Device** device) {
    const UINT flags = D3D11_CREATE_DEVICE_BGRA_SUPPORT;
    const D3D_FEATURE_LEVEL levelsWith11_1[] = {
        D3D_FEATURE_LEVEL_11_1,
        D3D_FEATURE_LEVEL_11_0,
        D3D_FEATURE_LEVEL_10_1,
        D3D_FEATURE_LEVEL_10_0,
    };
    const D3D_FEATURE_LEVEL levels[] = {
        D3D_FEATURE_LEVEL_11_0,
        D3D_FEATURE_LEVEL_10_1,
        D3D_FEATURE_LEVEL_10_0,
    };

    HRESULT hr = D3D11CreateDevice(nullptr, driverType, nullptr, flags, levelsWith11_1,
                                   ARRAYSIZE(levelsWith11_1), D3D11_SDK_VERSION, device,
                                   nullptr, nullptr);
    if (hr == E_INVALIDARG) {
        hr = D3D11CreateDevice(nullptr, driverType, nullptr, flags, levels, ARRAYSIZE(levels),
                               D3D11_SDK_VERSION, device, nullptr, nullptr);
    }
    return hr;
}

}  // namespace

RenderContext::~RenderContext() { Shutdown(); }

bool RenderContext::ForceWarpRequested() {
    wchar_t value[8] = {};
    const DWORD length =
        GetEnvironmentVariableW(L"FAF_FORCE_WARP", value, static_cast<DWORD>(ARRAYSIZE(value)));
    return length > 0 && value[0] == L'1';
}

HRESULT RenderContext::Initialize(HWND hwnd, UINT widthPx, UINT heightPx, float dpi) {
    if (IsValid()) return S_OK;

    width_ = widthPx;
    height_ = heightPx;
    dpi_ = dpi;
    usingWarp_ = false;

    // 进程级 COM(STA) —— D2D/DWrite/WIC/DComp/FileDialog 共用该单元。
    const HRESULT comHr = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    if (comHr == S_OK || comHr == S_FALSE) {
        comInitialized_ = true;
    } else if (comHr == RPC_E_CHANGED_MODE) {
        // 本线程已用其它单元模型初始化：仍可继续，但不负责反初始化。
        comInitialized_ = false;
    } else {
        return comHr;
    }

    HRESULT hr = CreateDeviceResources();
    if (SUCCEEDED(hr)) hr = CreateSwapChain(hwnd);
    if (SUCCEEDED(hr)) hr = CreateD2DTarget();
    if (FAILED(hr)) Shutdown();
    return hr;
}

HRESULT RenderContext::CreateDeviceResources() {
    // --- D3D11 设备：默认硬件；FAF_FORCE_WARP=1 或硬件失败时回退 WARP ---
    const D3D_DRIVER_TYPE driverType =
        ForceWarpRequested() ? D3D_DRIVER_TYPE_WARP : D3D_DRIVER_TYPE_HARDWARE;

    HRESULT hr = CreateD3D11Device(driverType, d3dDevice_.GetAddressOf());
    usingWarp_ = (driverType == D3D_DRIVER_TYPE_WARP);
    if (FAILED(hr) && driverType != D3D_DRIVER_TYPE_WARP) {
        hr = CreateD3D11Device(D3D_DRIVER_TYPE_WARP, d3dDevice_.GetAddressOf());
        usingWarp_ = true;
    }
    if (FAILED(hr)) return hr;

    // --- IDXGIDevice → adapter → IDXGIFactory2 ---
    hr = d3dDevice_->QueryInterface(__uuidof(IDXGIDevice), dxgiDevice_.PutVoid());
    if (FAILED(hr)) return hr;

    ComPtr<IDXGIAdapter> adapter;
    hr = dxgiDevice_->GetAdapter(adapter.GetAddressOf());
    if (FAILED(hr)) return hr;

    hr = adapter->GetParent(__uuidof(IDXGIFactory2), dxgiFactory_.PutVoid());
    if (FAILED(hr)) return hr;

    // --- DirectComposition 设备：必须请求 DesktopDevice IID（CreateTargetForHwnd 定义于其上）---
    hr = DCompositionCreateDevice2(dxgiDevice_.Get(), __uuidof(IDCompositionDesktopDevice),
                                   dcomp_.PutVoid());
    if (FAILED(hr)) return hr;

    // --- D2D 工厂 / 设备 / 设备上下文 ---
    D2D1_FACTORY_OPTIONS factoryOptions{};
    hr = D2D1CreateFactory(D2D1_FACTORY_TYPE_SINGLE_THREADED, __uuidof(ID2D1Factory1),
                           &factoryOptions, d2dFactory_.PutVoid());
    if (FAILED(hr)) return hr;

    hr = d2dFactory_->CreateDevice(dxgiDevice_.Get(), d2dDevice_.GetAddressOf());
    if (FAILED(hr)) return hr;

    hr = d2dDevice_->CreateDeviceContext(D2D1_DEVICE_CONTEXT_OPTIONS_NONE,
                                         d2dContext_.GetAddressOf());
    if (FAILED(hr)) return hr;
    d2dContext_->SetDpi(dpi_, dpi_);

    // --- DirectWrite 工厂（共享，供 Todo 3 排版使用）---
    hr = DWriteCreateFactory(DWRITE_FACTORY_TYPE_SHARED, __uuidof(IDWriteFactory),
                             reinterpret_cast<IUnknown**>(dwrite_.GetAddressOf()));
    if (FAILED(hr)) return hr;

    return S_OK;
}

HRESULT RenderContext::CreateSwapChain(HWND hwnd) {
    DXGI_SWAP_CHAIN_DESC1 desc{};
    desc.Width = width_;
    desc.Height = height_;
    desc.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
    desc.Stereo = FALSE;
    desc.SampleDesc.Count = 1;
    desc.SampleDesc.Quality = 0;
    desc.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
    desc.BufferCount = 2;
    desc.Scaling = DXGI_SCALING_STRETCH;
    desc.SwapEffect = DXGI_SWAP_EFFECT_FLIP_SEQUENTIAL;
    desc.AlphaMode = DXGI_ALPHA_MODE_PREMULTIPLIED;
    desc.Flags = 0;

    HRESULT hr = dxgiFactory_->CreateSwapChainForComposition(d3dDevice_.Get(), &desc, nullptr,
                                                             swapChain_.GetAddressOf());
    if (FAILED(hr)) return hr;

    // 目标 → 视觉 → 内容（生命周期顺序 device → target → visual → swapchain）
    hr = dcomp_->CreateTargetForHwnd(hwnd, TRUE, dcompTarget_.GetAddressOf());
    if (FAILED(hr)) return hr;

    // CreateVisual 在 IDCompositionDevice2/DesktopDevice 上返回 IDCompositionVisual2**。
    hr = dcomp_->CreateVisual(dcompVisual_.GetAddressOf());
    if (FAILED(hr)) return hr;

    hr = dcompVisual_->SetContent(swapChain_.Get());
    if (FAILED(hr)) return hr;

    hr = dcompTarget_->SetRoot(dcompVisual_.Get());
    if (FAILED(hr)) return hr;

    return dcomp_->Commit();
}

HRESULT RenderContext::CreateD2DTarget() {
    ComPtr<IDXGISurface> surface;
    HRESULT hr = swapChain_->GetBuffer(0, __uuidof(IDXGISurface), surface.PutVoid());
    if (FAILED(hr)) return hr;

    const D2D1_BITMAP_PROPERTIES1 properties = D2D1::BitmapProperties1(
        D2D1_BITMAP_OPTIONS_TARGET | D2D1_BITMAP_OPTIONS_CANNOT_DRAW,
        D2D1::PixelFormat(DXGI_FORMAT_B8G8R8A8_UNORM, D2D1_ALPHA_MODE_PREMULTIPLIED), dpi_, dpi_);

    hr = d2dContext_->CreateBitmapFromDxgiSurface(surface.Get(), &properties,
                                                 targetBitmap_.GetAddressOf());
    if (FAILED(hr)) return hr;

    d2dContext_->SetTarget(targetBitmap_.Get());
    return S_OK;
}

void RenderContext::ReleaseTarget() {
    if (d2dContext_) d2dContext_->SetTarget(nullptr);
    targetBitmap_.Reset();
}

HRESULT RenderContext::Resize(UINT widthPx, UINT heightPx) {
    if (!swapChain_) return E_FAIL;

    // ResizeBuffers 前必须释放全部后台缓冲引用（含 D2D 目标位图）。
    ReleaseTarget();
    width_ = widthPx;
    height_ = heightPx;

    HRESULT hr = swapChain_->ResizeBuffers(0, widthPx, heightPx, DXGI_FORMAT_UNKNOWN, 0);
    if (FAILED(hr)) return hr;
    return CreateD2DTarget();
}

HRESULT RenderContext::SetDpi(float dpi) {
    if (!d2dContext_) return E_FAIL;
    dpi_ = dpi;
    d2dContext_->SetDpi(dpi, dpi);

    // 目标位图在创建时固定了 DPI，变更后需重建以保持 DIP→像素映射一致。
    if (targetBitmap_) {
        ReleaseTarget();
        return CreateD2DTarget();
    }
    return S_OK;
}

HRESULT RenderContext::PresentFrame() {
    if (!d2dContext_ || !swapChain_ || !dcomp_) return E_FAIL;

    HRESULT hr = d2dContext_->EndDraw();
    if (FAILED(hr)) return hr;

    hr = swapChain_->Present(1, 0);
    if (FAILED(hr)) return hr;

    return dcomp_->Commit();
}

void RenderContext::Shutdown() {
    ReleaseTarget();
    d2dContext_.Reset();
    dwrite_.Reset();
    d2dDevice_.Reset();
    d2dFactory_.Reset();
    dcompVisual_.Reset();
    dcompTarget_.Reset();
    swapChain_.Reset();
    dxgiFactory_.Reset();
    dcomp_.Reset();
    dxgiDevice_.Reset();
    d3dDevice_.Reset();

    if (comInitialized_) {
        CoUninitialize();
        comInitialized_ = false;
    }

    width_ = 0;
    height_ = 0;
    usingWarp_ = false;
}

}  // namespace faf
