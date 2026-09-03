// mica_capture.cpp —— 画布来源：WIC 解码 + Direct2D 摆放 / DXGI 桌面复制 /
//                      CPU 上传 / 纯色。
//
// 画布是"整个虚拟桌面的低分辨率快照"（长边 <= max_long_side，默认 1600）。
// 它只在**壁纸变化**时重建一次，之后任意窗口、任意位置的烘焙都从画布的 mip
// 链上取样，因此单次烘焙成本与窗口尺寸和画布分辨率均无关。
//
// 四条来源路径（优先级由 Python 侧决策，本库只提供能力）
// ----------------------------------------------------
// 1. ``BuildCanvasFromWallpapers`` —— 首选。由 ``IDesktopWallpaper`` 得到的
//    每显示器壁纸路径 + 摆放方式，用 WIC 解码后经 Direct2D 摆放到画布。
//    优点：**不含任何窗口内容**，纯壁纸，与 Windows 11 Mica 的语义完全一致；
//    且不需要独占任何系统资源，可随时重建。
// 2. ``BuildCanvasFromDxgi`` —— 动态壁纸 / 幻灯片 / 壁纸文件无法解码时兜底。
//    通过 ``IDXGIOutputDuplication`` 抓取桌面。缺点是会包含桌面上的窗口内容，
//    故仅在壁纸变化事件触发时抓一次，绝不周期性轮询。
// 3. ``BuildCanvasFromMemory`` —— Python 既有采集链（GDI / 注册台等）的兜底。
// 4. ``BuildCanvasSolid`` —— 最终降级。
//
// 摆放语义严格对齐 ``freeassetfilter/ui/mica/source.py`` 的 ``render_placement``。

#include "mica_internal.h"

#include <algorithm>

namespace mica {

namespace {

/// D2D 单位矩阵。
constexpr D2D1_MATRIX_3X2_F kIdentity3x2 = {1.0f, 0.0f, 0.0f, 1.0f, 0.0f, 0.0f};

D2D1_COLOR_F MakeColor(uint32_t rgb) {
    float c[3];
    UnpackRgb(rgb, c);
    D2D1_COLOR_F out;
    out.r = c[0];
    out.g = c[1];
    out.b = c[2];
    out.a = 1.0f;
    return out;
}

D2D1_RECT_F MakeRect(float x, float y, float w, float h) {
    D2D1_RECT_F r;
    r.left = x;
    r.top = y;
    r.right = x + w;
    r.bottom = y + h;
    return r;
}

/// 行向量约定下的 3x2 矩阵乘法：``Concat(a, b)`` 表示"先 a 后 b"。
D2D1_MATRIX_3X2_F Concat(const D2D1_MATRIX_3X2_F& a, const D2D1_MATRIX_3X2_F& b) {
    D2D1_MATRIX_3X2_F m;
    m._11 = a._11 * b._11 + a._12 * b._21;
    m._12 = a._11 * b._12 + a._12 * b._22;
    m._21 = a._21 * b._11 + a._22 * b._21;
    m._22 = a._21 * b._12 + a._22 * b._22;
    m._31 = a._31 * b._11 + a._32 * b._21 + b._31;
    m._32 = a._31 * b._12 + a._32 * b._22 + b._32;
    return m;
}

D2D1_MATRIX_3X2_F MakeScaleTranslate(float sx, float sy, float tx, float ty) {
    D2D1_MATRIX_3X2_F m = kIdentity3x2;
    m._11 = sx;
    m._22 = sy;
    m._31 = tx;
    m._32 = ty;
    return m;
}

/// 用 D2D 打开画布 stage 作为渲染目标。
mica_status BeginCanvasDraw(Context* c, ComPtr<ID2D1Bitmap1>* outTarget) {
    ComPtr<IDXGISurface> surface;
    HRESULT hr = c->canvasStage->QueryInterface(__uuidof(IDXGISurface), surface.PutVoid());
    if (FAILED(hr)) {
        return FailHr(c, MICA_ERR_INTERNAL, hr, "QueryInterface(IDXGISurface)");
    }
    D2D1_BITMAP_PROPERTIES1 props = {};
    props.pixelFormat.format = DXGI_FORMAT_B8G8R8A8_UNORM;
    props.pixelFormat.alphaMode = D2D1_ALPHA_MODE_IGNORE;
    props.dpiX = 96.0f;  // 96 DPI => D2D 逻辑单位 == 物理像素
    props.dpiY = 96.0f;
    props.bitmapOptions = D2D1_BITMAP_OPTIONS_TARGET | D2D1_BITMAP_OPTIONS_CANNOT_DRAW;
    hr = c->d2dCtx->CreateBitmapFromDxgiSurface(surface.Get(), &props, outTarget->Put());
    if (FAILED(hr)) {
        return FailHr(c, MICA_ERR_INTERNAL, hr, "CreateBitmapFromDxgiSurface(target)");
    }
    c->d2dCtx->SetTarget(outTarget->Get());
    c->d2dCtx->SetTransform(&kIdentity3x2);
    c->d2dCtx->SetAntialiasMode(D2D1_ANTIALIAS_MODE_ALIASED);
    c->d2dCtx->BeginDraw();
    return MICA_OK;
}

/// 结束 D2D 绘制并解绑目标。
mica_status EndCanvasDraw(Context* c) {
    const HRESULT hr = c->d2dCtx->EndDraw();
    c->d2dCtx->SetTarget(nullptr);
    if (FAILED(hr)) {
        if (hr == D2DERR_RECREATE_TARGET) {
            return FailHr(c, MICA_ERR_DEVICE_LOST, hr, "ID2D1DeviceContext::EndDraw");
        }
        return FailHr(c, MICA_ERR_INTERNAL, hr, "ID2D1DeviceContext::EndDraw");
    }
    return MICA_OK;
}

/// 解码壁纸文件为 D2D 位图，并返回其**原始**像素尺寸。
///
/// 解码后按需用 WIC Fant 滤镜预降采样到目标区域长边的 2 倍以内：既省显存，
/// 也和 CPU 版 ``decode_wallpaper`` 的预降采样策略一致。
mica_status DecodeWallpaper(Context* c,
                            const wchar_t* path,
                            float destLong,
                            ComPtr<ID2D1Bitmap1>* outBitmap,
                            int* outNativeW,
                            int* outNativeH) {
    ComPtr<IWICBitmapDecoder> decoder;
    HRESULT hr = c->wic->CreateDecoderFromFilename(path, nullptr, GENERIC_READ,
                                                   WICDecodeMetadataCacheOnDemand, decoder.Put());
    if (FAILED(hr)) {
        return FailHr(c, MICA_ERR_DECODE, hr, "CreateDecoderFromFilename");
    }
    ComPtr<IWICBitmapFrameDecode> frame;
    hr = decoder->GetFrame(0, frame.Put());
    if (FAILED(hr)) {
        return FailHr(c, MICA_ERR_DECODE, hr, "IWICBitmapDecoder::GetFrame");
    }
    UINT nw = 0;
    UINT nh = 0;
    hr = frame->GetSize(&nw, &nh);
    if (FAILED(hr) || nw == 0 || nh == 0) {
        return Fail(c, MICA_ERR_DECODE, "壁纸尺寸无效 (%ux%u)", nw, nh);
    }
    *outNativeW = static_cast<int>(nw);
    *outNativeH = static_cast<int>(nh);

    // 统一到 32bppPBGRA，D2D 唯一可直接消费的格式。
    ComPtr<IWICFormatConverter> conv;
    hr = c->wic->CreateFormatConverter(conv.Put());
    if (FAILED(hr)) {
        return FailHr(c, MICA_ERR_DECODE, hr, "CreateFormatConverter");
    }
    hr = conv->Initialize(frame.Get(), GUID_WICPixelFormat32bppPBGRA, WICBitmapDitherTypeNone,
                          nullptr, 0.0, WICBitmapPaletteTypeMedianCut);
    if (FAILED(hr)) {
        return FailHr(c, MICA_ERR_DECODE, hr, "IWICFormatConverter::Initialize");
    }

    // 预降采样：保留 2 倍余量，Fill 的居中裁切仍有足够细节可用。
    const UINT nativeLong = (nw > nh) ? nw : nh;
    const UINT wantLong = static_cast<UINT>(
        Clamp(destLong * 2.0f, 64.0f, static_cast<float>(kMaxCanvasSide) * 2.0f));
    ComPtr<IWICBitmapSource> src;
    if (nativeLong > wantLong) {
        const double factor = static_cast<double>(wantLong) / static_cast<double>(nativeLong);
        const UINT sw = (std::max)(1u, static_cast<UINT>(nw * factor + 0.5));
        const UINT sh = (std::max)(1u, static_cast<UINT>(nh * factor + 0.5));
        ComPtr<IWICBitmapScaler> scaler;
        hr = c->wic->CreateBitmapScaler(scaler.Put());
        if (FAILED(hr)) {
            return FailHr(c, MICA_ERR_DECODE, hr, "CreateBitmapScaler");
        }
        hr = scaler->Initialize(conv.Get(), sw, sh, WICBitmapInterpolationModeFant);
        if (FAILED(hr)) {
            return FailHr(c, MICA_ERR_DECODE, hr, "IWICBitmapScaler::Initialize");
        }
        hr = scaler->QueryInterface(__uuidof(IWICBitmapSource), src.PutVoid());
        if (FAILED(hr)) {
            return FailHr(c, MICA_ERR_DECODE, hr, "QueryInterface(IWICBitmapSource/scaler)");
        }
    } else {
        hr = conv->QueryInterface(__uuidof(IWICBitmapSource), src.PutVoid());
        if (FAILED(hr)) {
            return FailHr(c, MICA_ERR_DECODE, hr, "QueryInterface(IWICBitmapSource/conv)");
        }
    }

    D2D1_BITMAP_PROPERTIES1 props = {};
    props.pixelFormat.format = DXGI_FORMAT_B8G8R8A8_UNORM;
    props.pixelFormat.alphaMode = D2D1_ALPHA_MODE_PREMULTIPLIED;
    props.dpiX = 96.0f;
    props.dpiY = 96.0f;
    props.bitmapOptions = D2D1_BITMAP_OPTIONS_NONE;
    hr = c->d2dCtx->CreateBitmapFromWicBitmap(src.Get(), &props, outBitmap->Put());
    if (FAILED(hr)) {
        return FailHr(c, MICA_ERR_DECODE, hr, "CreateBitmapFromWicBitmap");
    }
    return MICA_OK;
}

/// 把一幅位图按 ``position`` 摆放到目标矩形。语义对齐 ``render_placement``。
void PlaceBitmap(Context* c,
                 ID2D1Bitmap1* bmp,
                 const D2D1_RECT_F& dest,
                 int32_t position,
                 int nativeW,
                 int nativeH,
                 ID2D1SolidColorBrush* bgBrush) {
    const D2D1_SIZE_F bmpSize = bmp->GetSize();  // 96 DPI 下等于像素尺寸
    const float bw = (std::max)(1.0f, bmpSize.width);
    const float bh = (std::max)(1.0f, bmpSize.height);
    const float dw = (std::max)(1.0f, dest.right - dest.left);
    const float dh = (std::max)(1.0f, dest.bottom - dest.top);

    // 裁剪保证 Center 超出部分与 Tile 的最后一块都被精确切掉。
    c->d2dCtx->PushAxisAlignedClip(&dest, D2D1_ANTIALIAS_MODE_ALIASED);

    switch (position) {
        case MICA_POS_STRETCH: {
            c->d2dCtx->DrawBitmap(bmp, &dest, 1.0f, D2D1_INTERPOLATION_MODE_LINEAR, nullptr,
                                  nullptr);
            break;
        }
        case MICA_POS_FIT: {
            const float scale = (std::min)(dw / bw, dh / bh);
            const float fw = (std::max)(1.0f, bw * scale);
            const float fh = (std::max)(1.0f, bh * scale);
            if (bgBrush != nullptr) {
                c->d2dCtx->FillRectangle(&dest, bgBrush);
            }
            const D2D1_RECT_F fit = MakeRect(dest.left + (dw - fw) * 0.5f,
                                             dest.top + (dh - fh) * 0.5f, fw, fh);
            c->d2dCtx->DrawBitmap(bmp, &fit, 1.0f, D2D1_INTERPOLATION_MODE_LINEAR, nullptr,
                                  nullptr);
            break;
        }
        case MICA_POS_CENTER: {
            // 以"原始像素尺寸换算到画布空间"为基准居中；超出由裁剪切掉。
            const float natW = (std::max)(1.0f, nativeW * c->canvasScale);
            const float natH = (std::max)(1.0f, nativeH * c->canvasScale);
            if (bgBrush != nullptr) {
                c->d2dCtx->FillRectangle(&dest, bgBrush);
            }
            const D2D1_RECT_F centered = MakeRect(dest.left + (dw - natW) * 0.5f,
                                                  dest.top + (dh - natH) * 0.5f, natW, natH);
            c->d2dCtx->DrawBitmap(bmp, &centered, 1.0f, D2D1_INTERPOLATION_MODE_LINEAR, nullptr,
                                  nullptr);
            break;
        }
        case MICA_POS_TILE: {
            const float natW = (std::max)(1.0f, nativeW * c->canvasScale);
            const float natH = (std::max)(1.0f, nativeH * c->canvasScale);
            D2D1_BITMAP_BRUSH_PROPERTIES1 bbp = {};
            bbp.extendModeX = D2D1_EXTEND_MODE_WRAP;
            bbp.extendModeY = D2D1_EXTEND_MODE_WRAP;
            bbp.interpolationMode = D2D1_INTERPOLATION_MODE_LINEAR;
            D2D1_BRUSH_PROPERTIES bp = {};
            bp.opacity = 1.0f;
            // 先把位图缩放到单块瓦片尺寸，再平移到目标左上角（对齐 _render_tile
            // 的"从左上角起铺"语义）。
            bp.transform = MakeScaleTranslate(natW / bw, natH / bh, dest.left, dest.top);
            ComPtr<ID2D1BitmapBrush1> brush;
            if (SUCCEEDED(c->d2dCtx->CreateBitmapBrush(bmp, &bbp, &bp, brush.Put()))) {
                c->d2dCtx->FillRectangle(&dest, brush.Get());
            }
            break;
        }
        case MICA_POS_FILL:
        case MICA_POS_SPAN:
        default: {
            // 按目标宽高比居中裁切源图后铺满
            const float targetAr = dw / dh;
            const float imageAr = bw / bh;
            float srcW = bw;
            float srcH = bh;
            if (imageAr > targetAr) {
                srcH = bh;
                srcW = srcH * targetAr;
            } else {
                srcW = bw;
                srcH = srcW / targetAr;
            }
            const D2D1_RECT_F srcRect =
                MakeRect((bw - srcW) * 0.5f, (bh - srcH) * 0.5f, srcW, srcH);
            c->d2dCtx->DrawBitmap(bmp, &dest, 1.0f, D2D1_INTERPOLATION_MODE_LINEAR, &srcRect,
                                  nullptr);
            break;
        }
    }

    c->d2dCtx->PopAxisAlignedClip();
}

/// 计算把源纹理 ``(tw, th)`` 按 ``rot`` 摆到目标矩形的 D2D 变换矩阵。
///
/// 桌面复制返回的纹理处于**面板方向**，旋转显示器上需要反向旋转才能还原为
/// 桌面方向。旋转后包围盒的宽高会与目标矩形互换，故缩放要基于旋转后的尺寸。
D2D1_MATRIX_3X2_F MakePlacementMatrix(float tw,
                                      float th,
                                      const D2D1_RECT_F& dest,
                                      DXGI_MODE_ROTATION rot) {
    D2D1_MATRIX_3X2_F rotate = kIdentity3x2;
    float rw = tw;
    float rh = th;
    switch (rot) {
        case DXGI_MODE_ROTATION_ROTATE90:
            // (x, y) -> (y, tw - x)
            rotate._11 = 0.0f;
            rotate._12 = -1.0f;
            rotate._21 = 1.0f;
            rotate._22 = 0.0f;
            rotate._31 = 0.0f;
            rotate._32 = tw;
            rw = th;
            rh = tw;
            break;
        case DXGI_MODE_ROTATION_ROTATE180:
            // (x, y) -> (tw - x, th - y)
            rotate._11 = -1.0f;
            rotate._22 = -1.0f;
            rotate._31 = tw;
            rotate._32 = th;
            break;
        case DXGI_MODE_ROTATION_ROTATE270:
            // (x, y) -> (th - y, x)
            rotate._11 = 0.0f;
            rotate._12 = 1.0f;
            rotate._21 = -1.0f;
            rotate._22 = 0.0f;
            rotate._31 = th;
            rotate._32 = 0.0f;
            rw = th;
            rh = tw;
            break;
        default:
            break;
    }
    const float dw = (std::max)(1.0f, dest.right - dest.left);
    const float dh = (std::max)(1.0f, dest.bottom - dest.top);
    const D2D1_MATRIX_3X2_F fit = MakeScaleTranslate(dw / (std::max)(1.0f, rw),
                                                     dh / (std::max)(1.0f, rh), dest.left,
                                                     dest.top);
    return Concat(rotate, fit);
}

/// 打开所有输出的桌面复制会话。已打开则直接返回。
mica_status OpenDupls(Context* c) {
    if (!c->dupls.empty()) {
        return MICA_OK;
    }
    if (!c->adapter) {
        return Fail(c, MICA_ERR_CAPTURE_UNAVAILABLE, "无可用 DXGI 适配器");
    }

    UINT index = 0;
    ComPtr<IDXGIOutput> output;
    HRESULT lastHr = S_OK;
    while (c->adapter->EnumOutputs(index, output.Put()) != DXGI_ERROR_NOT_FOUND) {
        ++index;
        if (!output) {
            continue;
        }
        DXGI_OUTPUT_DESC desc = {};
        if (FAILED(output->GetDesc(&desc)) || desc.AttachedToDesktop == FALSE) {
            continue;
        }
        ComPtr<IDXGIOutput1> output1;
        if (FAILED(output->QueryInterface(__uuidof(IDXGIOutput1), output1.PutVoid()))) {
            continue;
        }
        DuplOutput item;
        const HRESULT hr = output1->DuplicateOutput(c->device.Get(), item.dupl.Put());
        if (FAILED(hr)) {
            lastHr = hr;
            continue;
        }
        item.bounds = desc.DesktopCoordinates;
        item.rotation = desc.Rotation;
        c->dupls.push_back(item);
    }

    if (c->dupls.empty()) {
        c->dxgiAvailable = 0;
        if (FAILED(lastHr)) {
            return FailHr(c, MICA_ERR_CAPTURE_UNAVAILABLE, lastHr, "IDXGIOutput1::DuplicateOutput");
        }
        return Fail(c, MICA_ERR_CAPTURE_UNAVAILABLE, "未找到已连接桌面的 DXGI 输出");
    }
    c->dxgiAvailable = 1;
    return MICA_OK;
}

/// 抓取单个输出的一帧，拷贝到可被 D2D 采样的自有纹理。
mica_status GrabOutput(Context* c,
                       DuplOutput* item,
                       int timeoutMs,
                       ComPtr<ID2D1Bitmap1>* outBitmap,
                       float* outW,
                       float* outH) {
    DXGI_OUTDUPL_FRAME_INFO info = {};
    ComPtr<IDXGIResource> resource;
    HRESULT hr = item->dupl->AcquireNextFrame(static_cast<UINT>((std::max)(0, timeoutMs)), &info,
                                              resource.Put());
    if (hr == DXGI_ERROR_WAIT_TIMEOUT) {
        return MICA_ERR_CAPTURE_TIMEOUT;
    }
    if (FAILED(hr)) {
        return FailHr(c, MICA_ERR_CAPTURE_UNAVAILABLE, hr, "AcquireNextFrame");
    }

    mica_status st = MICA_OK;
    ComPtr<ID3D11Texture2D> acquired;
    if (FAILED(resource->QueryInterface(__uuidof(ID3D11Texture2D), acquired.PutVoid()))) {
        st = Fail(c, MICA_ERR_INTERNAL, "桌面帧无法转为 ID3D11Texture2D");
    }

    if (st == MICA_OK) {
        D3D11_TEXTURE2D_DESC srcDesc = {};
        acquired->GetDesc(&srcDesc);
        // 桌面复制纹理不带 SHADER_RESOURCE 绑定，必须先拷到自有纹理才能被 D2D
        // 当作源位图使用。
        D3D11_TEXTURE2D_DESC td = srcDesc;
        td.Usage = D3D11_USAGE_DEFAULT;
        td.BindFlags = D3D11_BIND_SHADER_RESOURCE;
        td.CPUAccessFlags = 0;
        td.MiscFlags = 0;
        td.MipLevels = 1;
        td.ArraySize = 1;
        ComPtr<ID3D11Texture2D> own;
        hr = c->device->CreateTexture2D(&td, nullptr, own.Put());
        if (FAILED(hr)) {
            st = FailHr(c, MICA_ERR_OUT_OF_MEMORY, hr, "CreateTexture2D(desktop copy)");
        } else {
            c->ctx->CopyResource(own.Get(), acquired.Get());
            ComPtr<IDXGISurface> surface;
            hr = own->QueryInterface(__uuidof(IDXGISurface), surface.PutVoid());
            if (FAILED(hr)) {
                st = FailHr(c, MICA_ERR_INTERNAL, hr, "QueryInterface(IDXGISurface/desktop)");
            } else {
                D2D1_BITMAP_PROPERTIES1 props = {};
                props.pixelFormat.format = td.Format;
                props.pixelFormat.alphaMode = D2D1_ALPHA_MODE_IGNORE;
                props.dpiX = 96.0f;
                props.dpiY = 96.0f;
                props.bitmapOptions = D2D1_BITMAP_OPTIONS_NONE;
                hr = c->d2dCtx->CreateBitmapFromDxgiSurface(surface.Get(), &props,
                                                            outBitmap->Put());
                if (FAILED(hr)) {
                    st = FailHr(c, MICA_ERR_INTERNAL, hr, "CreateBitmapFromDxgiSurface(desktop)");
                } else {
                    *outW = static_cast<float>(td.Width);
                    *outH = static_cast<float>(td.Height);
                }
            }
        }
    }

    // 无论成功与否都必须归还帧，否则下一次 AcquireNextFrame 会失败。
    item->dupl->ReleaseFrame();
    return st;
}

}  // namespace

// ---------------------------------------------------------------------------
// 壁纸文件 -> 画布
// ---------------------------------------------------------------------------

mica_status BuildCanvasFromWallpapers(Context* c,
                                      const mica_monitor_layout* layouts,
                                      int count,
                                      uint32_t fallbackRgb) {
    if (layouts == nullptr || count <= 0) {
        return Fail(c, MICA_ERR_INVALID_ARG, "显示器布局为空");
    }
    if (c->vw <= 0 || c->vh <= 0) {
        return Fail(c, MICA_ERR_INVALID_ARG, "尚未设置虚拟桌面几何");
    }

    const int cw = (std::max)(1, static_cast<int>(c->vw * c->canvasScale + 0.5f));
    const int ch = (std::max)(1, static_cast<int>(c->vh * c->canvasScale + 0.5f));
    mica_status st = EnsureCanvas(c, cw, ch);
    if (st != MICA_OK) {
        return st;
    }

    ComPtr<ID2D1Bitmap1> target;
    st = BeginCanvasDraw(c, &target);
    if (st != MICA_OK) {
        return st;
    }

    const D2D1_COLOR_F clearColor = MakeColor(fallbackRgb);
    c->d2dCtx->Clear(&clearColor);

    int placed = 0;
    for (int i = 0; i < count; ++i) {
        const mica_monitor_layout& mon = layouts[i];
        const bool span = (mon.position == MICA_POS_SPAN);
        D2D1_RECT_F dest;
        if (span) {
            dest = MakeRect(0.0f, 0.0f, static_cast<float>(c->canvasW),
                            static_cast<float>(c->canvasH));
        } else {
            dest = MakeRect((mon.x - c->vx) * c->canvasScale, (mon.y - c->vy) * c->canvasScale,
                            (std::max)(1.0f, mon.w * c->canvasScale),
                            (std::max)(1.0f, mon.h * c->canvasScale));
        }

        ComPtr<ID2D1SolidColorBrush> bgBrush;
        const D2D1_COLOR_F bg = MakeColor(mon.background_rgb);
        c->d2dCtx->CreateSolidColorBrush(&bg, nullptr, bgBrush.Put());

        if (mon.wallpaper == nullptr || mon.wallpaper[0] == L'\0') {
            if (bgBrush) {
                c->d2dCtx->FillRectangle(&dest, bgBrush.Get());
            }
            continue;
        }

        const float destLong = (std::max)(dest.right - dest.left, dest.bottom - dest.top);
        ComPtr<ID2D1Bitmap1> bmp;
        int natW = 0;
        int natH = 0;
        const mica_status decodeSt =
            DecodeWallpaper(c, mon.wallpaper, destLong, &bmp, &natW, &natH);
        if (decodeSt != MICA_OK) {
            // 单个显示器解码失败不影响其余显示器，用背景色兜底该区域。
            if (bgBrush) {
                c->d2dCtx->FillRectangle(&dest, bgBrush.Get());
            }
            continue;
        }
        PlaceBitmap(c, bmp.Get(), dest, mon.position, natW, natH, bgBrush.Get());
        ++placed;

        if (span) {
            // 跨区壁纸已覆盖整个画布，无需再处理其余显示器。
            break;
        }
    }

    st = EndCanvasDraw(c);
    if (st != MICA_OK) {
        return st;
    }
    if (placed == 0) {
        // 所有壁纸都解码失败：画布内容只有背景色，如实标记为 SOLID，让 Python
        // 侧知道应尝试 DXGI 兜底。
        PublishCanvas(c, MICA_BACKEND_SOLID);
        return Fail(c, MICA_ERR_DECODE, "所有壁纸文件均解码失败");
    }
    PublishCanvas(c, MICA_BACKEND_WALLPAPER);
    return MICA_OK;
}

// ---------------------------------------------------------------------------
// DXGI 桌面复制 -> 画布
// ---------------------------------------------------------------------------

mica_status BuildCanvasFromDxgi(Context* c, int timeoutMs) {
    if (c->vw <= 0 || c->vh <= 0) {
        return Fail(c, MICA_ERR_INVALID_ARG, "尚未设置虚拟桌面几何");
    }
    mica_status st = OpenDupls(c);
    if (st != MICA_OK) {
        return st;
    }

    const int cw = (std::max)(1, static_cast<int>(c->vw * c->canvasScale + 0.5f));
    const int ch = (std::max)(1, static_cast<int>(c->vh * c->canvasScale + 0.5f));
    st = EnsureCanvas(c, cw, ch);
    if (st != MICA_OK) {
        return st;
    }

    // 先抓齐所有输出再统一绘制：避免部分成功时画布出现半旧半新的撕裂。
    struct Piece {
        ComPtr<ID2D1Bitmap1> bmp;
        float w = 0.0f;
        float h = 0.0f;
        D2D1_RECT_F dest{};
        DXGI_MODE_ROTATION rot = DXGI_MODE_ROTATION_IDENTITY;
    };
    std::vector<Piece> pieces;
    pieces.reserve(c->dupls.size());
    int timeouts = 0;

    for (DuplOutput& item : c->dupls) {
        Piece piece;
        const mica_status grabSt = GrabOutput(c, &item, timeoutMs, &piece.bmp, &piece.w, &piece.h);
        if (grabSt == MICA_ERR_CAPTURE_TIMEOUT) {
            ++timeouts;
            continue;
        }
        if (grabSt != MICA_OK) {
            // 会话失效（如切换到安全桌面）：丢弃全部会话，下次重新打开。
            CloseDupls(c);
            return grabSt;
        }
        piece.rot = item.rotation;
        piece.dest = MakeRect((item.bounds.left - c->vx) * c->canvasScale,
                              (item.bounds.top - c->vy) * c->canvasScale,
                              (std::max)(1.0f, (item.bounds.right - item.bounds.left) *
                                                   c->canvasScale),
                              (std::max)(1.0f, (item.bounds.bottom - item.bounds.top) *
                                                   c->canvasScale));
        pieces.push_back(std::move(piece));
    }

    if (pieces.empty()) {
        if (timeouts > 0) {
            // 桌面自上次抓取以来无变化，属正常情况：保留旧画布。
            return Fail(c, MICA_ERR_CAPTURE_TIMEOUT, "桌面复制超时（%d 个输出无新帧）", timeouts);
        }
        return Fail(c, MICA_ERR_CAPTURE_UNAVAILABLE, "桌面复制未产出任何帧");
    }

    ComPtr<ID2D1Bitmap1> target;
    st = BeginCanvasDraw(c, &target);
    if (st != MICA_OK) {
        return st;
    }
    const D2D1_COLOR_F black = MakeColor(0x000000u);
    c->d2dCtx->Clear(&black);
    for (const Piece& piece : pieces) {
        const D2D1_MATRIX_3X2_F m = MakePlacementMatrix(piece.w, piece.h, piece.dest, piece.rot);
        c->d2dCtx->SetTransform(&m);
        const D2D1_RECT_F full = MakeRect(0.0f, 0.0f, piece.w, piece.h);
        c->d2dCtx->DrawBitmap(piece.bmp.Get(), &full, 1.0f, D2D1_INTERPOLATION_MODE_LINEAR, nullptr,
                              nullptr);
    }
    c->d2dCtx->SetTransform(&kIdentity3x2);
    st = EndCanvasDraw(c);
    if (st != MICA_OK) {
        return st;
    }
    PublishCanvas(c, MICA_BACKEND_DXGI);
    return MICA_OK;
}

mica_status ProbeDxgi(Context* c, int* outAvailable) {
    if (outAvailable == nullptr) {
        return Fail(c, MICA_ERR_INVALID_ARG, "outAvailable 为空");
    }
    const mica_status st = OpenDupls(c);
    *outAvailable = (st == MICA_OK) ? 1 : 0;
    // 探测后立即释放独占会话，避免长期占用导致其他进程无法复制桌面。
    CloseDupls(c);
    c->dxgiAvailable = *outAvailable;
    return (st == MICA_OK) ? MICA_OK : st;
}

void CloseDupls(Context* c) {
    c->dupls.clear();
}

// ---------------------------------------------------------------------------
// CPU 像素 -> 画布
// ---------------------------------------------------------------------------

mica_status BuildCanvasFromMemory(Context* c, const uint8_t* rgb, int w, int h, int stride) {
    if (rgb == nullptr || w <= 0 || h <= 0) {
        return Fail(c, MICA_ERR_INVALID_ARG, "上传的像素缓冲无效 (%dx%d)", w, h);
    }
    if (stride <= 0) {
        stride = w * 3;
    }
    if (stride < w * 3) {
        return Fail(c, MICA_ERR_INVALID_ARG, "行跨距 %d 小于 %d", stride, w * 3);
    }

    // RGB8 -> BGRA8（D2D / D3D 可直接消费的布局）
    std::vector<uint8_t> bgra(static_cast<size_t>(w) * static_cast<size_t>(h) * 4u);
    for (int y = 0; y < h; ++y) {
        const uint8_t* srcRow = rgb + static_cast<size_t>(y) * static_cast<size_t>(stride);
        uint8_t* dstRow = bgra.data() + static_cast<size_t>(y) * static_cast<size_t>(w) * 4u;
        for (int x = 0; x < w; ++x) {
            dstRow[x * 4 + 0] = srcRow[x * 3 + 2];
            dstRow[x * 4 + 1] = srcRow[x * 3 + 1];
            dstRow[x * 4 + 2] = srcRow[x * 3 + 0];
            dstRow[x * 4 + 3] = 0xFFu;
        }
    }

    D3D11_TEXTURE2D_DESC td = {};
    td.Width = static_cast<UINT>(w);
    td.Height = static_cast<UINT>(h);
    td.MipLevels = 1;
    td.ArraySize = 1;
    td.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
    td.SampleDesc.Count = 1;
    td.Usage = D3D11_USAGE_IMMUTABLE;
    td.BindFlags = D3D11_BIND_SHADER_RESOURCE;
    D3D11_SUBRESOURCE_DATA init = {};
    init.pSysMem = bgra.data();
    init.SysMemPitch = static_cast<UINT>(w) * 4u;
    ComPtr<ID3D11Texture2D> upload;
    HRESULT hr = c->device->CreateTexture2D(&td, &init, upload.Put());
    if (FAILED(hr)) {
        return FailHr(c, MICA_ERR_OUT_OF_MEMORY, hr, "CreateTexture2D(upload)");
    }

    // 画布尺寸取上传尺寸本身：Python 侧已按 canvas_scale 生成过整屏画布。
    mica_status st = EnsureCanvas(c, w, h);
    if (st != MICA_OK) {
        return st;
    }

    ComPtr<IDXGISurface> surface;
    hr = upload->QueryInterface(__uuidof(IDXGISurface), surface.PutVoid());
    if (FAILED(hr)) {
        return FailHr(c, MICA_ERR_INTERNAL, hr, "QueryInterface(IDXGISurface/upload)");
    }
    D2D1_BITMAP_PROPERTIES1 props = {};
    props.pixelFormat.format = DXGI_FORMAT_B8G8R8A8_UNORM;
    props.pixelFormat.alphaMode = D2D1_ALPHA_MODE_IGNORE;
    props.dpiX = 96.0f;
    props.dpiY = 96.0f;
    props.bitmapOptions = D2D1_BITMAP_OPTIONS_NONE;
    ComPtr<ID2D1Bitmap1> bmp;
    hr = c->d2dCtx->CreateBitmapFromDxgiSurface(surface.Get(), &props, bmp.Put());
    if (FAILED(hr)) {
        return FailHr(c, MICA_ERR_INTERNAL, hr, "CreateBitmapFromDxgiSurface(upload)");
    }

    ComPtr<ID2D1Bitmap1> target;
    st = BeginCanvasDraw(c, &target);
    if (st != MICA_OK) {
        return st;
    }
    const D2D1_RECT_F dest =
        MakeRect(0.0f, 0.0f, static_cast<float>(c->canvasW), static_cast<float>(c->canvasH));
    c->d2dCtx->DrawBitmap(bmp.Get(), &dest, 1.0f, D2D1_INTERPOLATION_MODE_LINEAR, nullptr, nullptr);
    st = EndCanvasDraw(c);
    if (st != MICA_OK) {
        return st;
    }
    PublishCanvas(c, MICA_BACKEND_MEMORY);
    return MICA_OK;
}

mica_status BuildCanvasSolid(Context* c, uint32_t rgb) {
    // 纯色画布只需 1x1：mip 链退化为单级，采样成本最低。
    mica_status st = EnsureCanvas(c, 1, 1);
    if (st != MICA_OK) {
        return st;
    }
    ComPtr<ID2D1Bitmap1> target;
    st = BeginCanvasDraw(c, &target);
    if (st != MICA_OK) {
        return st;
    }
    const D2D1_COLOR_F color = MakeColor(rgb);
    c->d2dCtx->Clear(&color);
    st = EndCanvasDraw(c);
    if (st != MICA_OK) {
        return st;
    }
    PublishCanvas(c, MICA_BACKEND_SOLID);
    return MICA_OK;
}

}  // namespace mica
