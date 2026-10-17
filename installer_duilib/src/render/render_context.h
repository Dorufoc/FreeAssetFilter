#pragma once
//
// render_context.h - 安装器渲染底座（D3D11 + D2D1 + DirectWrite + DirectComposition）
//
// 拥有：进程级 COM(STA) 初始化、D3D11 设备、DComp 设备/目标/视觉、合成交换链、
// D2D1 设备上下文与 DirectWrite 工厂。设备与目标的生命周期必须长于窗口。
//
// 绘制坐标全程使用 DIP（96 基准逻辑单位），由 ID2D1DeviceContext::SetDpi 负责放大；
// 只有交换链后台缓冲尺寸使用物理像素。
//
#include <windows.h>

#include <d2d1_1.h>
#include <d3d11.h>
#include <dcomp.h>
#include <dwrite.h>
#include <dxgi1_2.h>

namespace faf {

// 自实现最小 COM 智能指针（RAII），不依赖任何外部库。
template <typename T>
class ComPtr {
public:
    ComPtr() noexcept = default;
    ~ComPtr() { Reset(); }

    ComPtr(const ComPtr&) = delete;
    ComPtr& operator=(const ComPtr&) = delete;

    ComPtr(ComPtr&& other) noexcept : ptr_(other.ptr_) { other.ptr_ = nullptr; }
    ComPtr& operator=(ComPtr&& other) noexcept {
        if (this != &other) {
            Reset();
            ptr_ = other.ptr_;
            other.ptr_ = nullptr;
        }
        return *this;
    }

    T* Get() const noexcept { return ptr_; }
    T* operator->() const noexcept { return ptr_; }
    explicit operator bool() const noexcept { return ptr_ != nullptr; }

    // 供 out-param 使用：调用前先释放已有接口。
    T** GetAddressOf() noexcept { Reset(); return &ptr_; }
    void** PutVoid() noexcept { Reset(); return reinterpret_cast<void**>(&ptr_); }

    void Reset() noexcept {
        if (ptr_) {
            ptr_->Release();
            ptr_ = nullptr;
        }
    }

private:
    T* ptr_ = nullptr;
};

// 渲染上下文：创建于窗口之前、销毁于窗口之后。
class RenderContext {
public:
    RenderContext() = default;
    ~RenderContext();

    RenderContext(const RenderContext&) = delete;
    RenderContext& operator=(const RenderContext&) = delete;

    // 初始化整套渲染栈。widthPx/heightPx 为交换链后台缓冲的物理像素尺寸；
    // dpi 用于 D2D 设备上下文。失败时对象不可用（内部已回滚）。
    HRESULT Initialize(HWND hwnd, UINT widthPx, UINT heightPx, float dpi);

    // 释放全部资源（含进程 COM 反初始化）。幂等，可重复调用。
    void Shutdown();

    // 释放目标位图后重建交换链后台缓冲与 D2D 目标（WM_DPICHANGED / 尺寸变化使用）。
    HRESULT Resize(UINT widthPx, UINT heightPx);

    // 更新 D2D 设备上下文 DPI（DIP 缩放的唯一来源）。
    HRESULT SetDpi(float dpi);

    // 结束本帧：EndDraw → swapchain->Present(1,0) → dcomp->Commit()。
    // 调用前须已 BeginDraw 并完成绘制。
    HRESULT PresentFrame();

    bool IsValid() const noexcept { return swapChain_ && d2dContext_ && dcompTarget_; }

    ID2D1DeviceContext* DeviceContext() const noexcept { return d2dContext_.Get(); }
    IDWriteFactory* WriteFactory() const noexcept { return dwrite_.Get(); }
    ID2D1Factory1* D2DFactory() const noexcept { return d2dFactory_.Get(); }
    ID2D1Device* D2DDevice() const noexcept { return d2dDevice_.Get(); }
    IDCompositionDesktopDevice* CompositionDevice() const noexcept { return dcomp_.Get(); }
    IDXGISwapChain1* SwapChain() const noexcept { return swapChain_.Get(); }

    UINT Width() const noexcept { return width_; }
    UINT Height() const noexcept { return height_; }
    float Dpi() const noexcept { return dpi_; }
    // FAF_FORCE_WARP=1 或硬件设备创建失败并回退时返回 true（供 Todo 2 断言 WARP 路径）。
    bool UsingWarp() const noexcept { return usingWarp_; }

private:
    HRESULT CreateDeviceResources();     // D3D11 + DXGI + DComp + D2D + DWrite 设备
    HRESULT CreateSwapChain(HWND hwnd);  // 合成交换链 + DComp 目标/视觉
    HRESULT CreateD2DTarget();           // 后台缓冲 → ID2D1Bitmap1 并设为 D2D 目标
    void ReleaseTarget();                // 先撤 target 再释放位图（Resize 前置条件）

    // FAF_FORCE_WARP 为无条件运行时诊断覆盖（未设置时不影响默认行为）。
    static bool ForceWarpRequested();

    // 进程级 COM(STA)。非本对象初始化的单元不计入反初始化。
    bool comInitialized_ = false;

    ComPtr<ID3D11Device> d3dDevice_;
    ComPtr<IDXGIDevice> dxgiDevice_;
    ComPtr<IDXGIFactory2> dxgiFactory_;
    ComPtr<IDCompositionDesktopDevice> dcomp_;
    ComPtr<IDCompositionTarget> dcompTarget_;
    ComPtr<IDCompositionVisual2> dcompVisual_;
    ComPtr<IDXGISwapChain1> swapChain_;
    ComPtr<ID2D1Factory1> d2dFactory_;
    ComPtr<ID2D1Device> d2dDevice_;
    ComPtr<ID2D1DeviceContext> d2dContext_;
    ComPtr<ID2D1Bitmap1> targetBitmap_;
    ComPtr<IDWriteFactory> dwrite_;

    UINT width_ = 0;
    UINT height_ = 0;
    float dpi_ = 96.0f;
    bool usingWarp_ = false;
};

}  // namespace faf
