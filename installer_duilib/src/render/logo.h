#pragma once
//
// logo.h - 从可执行文件资源解码 IDR_LOGO（FAF-setup.png）为 ID2D1Bitmap1。
//
// 走 WIC（CoCreateInstance(CLSID_WICImagingFactory)）解码 PNG。要求进程 COM(STA)
// 已初始化（由 RenderContext 负责）。资源 ID 必须与 installer_duilib/resources/app.rc
// 中的 IDR_LOGO 一致。
//
#include <windows.h>

#include <d2d1_1.h>

#include "render/render_context.h"  // 复用 faf::ComPtr

namespace faf {

// IDR_LOGO 的数值；必须与 resources/app.rc 中的定义保持一致。
#ifndef IDR_LOGO
#define IDR_LOGO 101
#endif

class LogoBitmap {
public:
    LogoBitmap() = default;

    // 从模块资源解码 PNG 为可直接绘制的位图。dc 用于建位图，不拥有。
    HRESULT Load(ID2D1DeviceContext* dc, UINT resourceId = IDR_LOGO);

    ID2D1Bitmap1* Bitmap() const noexcept { return bitmap_.Get(); }
    UINT Width() const noexcept { return width_; }
    UINT Height() const noexcept { return height_; }
    bool IsLoaded() const noexcept { return bitmap_.Get() != nullptr; }

private:
    ComPtr<ID2D1Bitmap1> bitmap_;
    UINT width_ = 0;
    UINT height_ = 0;
};

}  // namespace faf
