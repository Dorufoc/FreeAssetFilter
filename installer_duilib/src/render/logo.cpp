//
// logo.cpp - IDR_LOGO（PNG）资源 → ID2D1Bitmap1 解码实现。
//
#include "render/logo.h"

#include <wincodec.h>

namespace spk {

HRESULT LogoBitmap::Load(ID2D1DeviceContext* dc, UINT resourceId) {
    bitmap_.Reset();
    width_ = 0;
    height_ = 0;
    if (!dc) return E_POINTER;

    // --- 定位 RCDATA 资源 ---
    // RT_RCDATA 是 MAKEINTRESOURCE(10)，在非 UNICODE 编译单元里是窄字符宏；显式转宽。
    const HRSRC resource = FindResourceW(nullptr, MAKEINTRESOURCEW(resourceId),
                                         reinterpret_cast<LPCWSTR>(RT_RCDATA));
    if (!resource) return HRESULT_FROM_WIN32(GetLastError());

    const DWORD size = SizeofResource(nullptr, resource);
    const HGLOBAL handle = LoadResource(nullptr, resource);
    if (!handle || size == 0) return E_FAIL;
    const void* data = LockResource(handle);
    if (!data) return E_FAIL;

    // --- WIC 解码 ---
    ComPtr<IWICImagingFactory> wic;
    HRESULT hr = CoCreateInstance(CLSID_WICImagingFactory, nullptr, CLSCTX_INPROC_SERVER,
                                  __uuidof(IWICImagingFactory), wic.PutVoid());
    if (FAILED(hr)) return hr;

    ComPtr<IWICStream> stream;
    hr = wic->CreateStream(stream.GetAddressOf());
    if (FAILED(hr)) return hr;
    hr = stream->InitializeFromMemory(const_cast<BYTE*>(static_cast<const BYTE*>(data)), size);
    if (FAILED(hr)) return hr;

    ComPtr<IWICBitmapDecoder> decoder;
    hr = wic->CreateDecoderFromStream(stream.Get(), nullptr, WICDecodeMetadataCacheOnDemand,
                                      decoder.GetAddressOf());
    if (FAILED(hr)) return hr;

    ComPtr<IWICBitmapFrameDecode> frame;
    hr = decoder->GetFrame(0, frame.GetAddressOf());
    if (FAILED(hr)) return hr;

    // 统一转成预乘 BGRA，供 D2D 目标位图直接使用。
    ComPtr<IWICFormatConverter> converter;
    hr = wic->CreateFormatConverter(converter.GetAddressOf());
    if (FAILED(hr)) return hr;
    hr = converter->Initialize(frame.Get(), GUID_WICPixelFormat32bppPBGRA, WICBitmapDitherTypeNone,
                               nullptr, 0.0, WICBitmapPaletteTypeCustom);
    if (FAILED(hr)) return hr;

    hr = dc->CreateBitmapFromWicBitmap(converter.Get(), nullptr, bitmap_.GetAddressOf());
    if (FAILED(hr)) return hr;

    const D2D1_SIZE_U pixels = bitmap_->GetPixelSize();
    width_ = pixels.width;
    height_ = pixels.height;
    return S_OK;
}

}  // namespace spk
