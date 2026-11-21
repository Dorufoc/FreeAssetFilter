// Sample the trailing cap at the same partial fill as 正在安装.svg.
#include <d3d11.h>
#include <cstdio>
#include "render/controls_feedback.h"
#include "render/render_context.h"

int main() {
    using spk::ComPtr;
    ComPtr<ID3D11Device> d3d;
    ComPtr<IDXGIDevice> dxgi;
    ComPtr<ID2D1Device> device;
    ComPtr<ID2D1DeviceContext> dc;
    ComPtr<ID2D1Factory1> factory;
    if (FAILED(D2D1CreateFactory(D2D1_FACTORY_TYPE_SINGLE_THREADED, __uuidof(ID2D1Factory1), nullptr,
            reinterpret_cast<void**>(factory.GetAddressOf()))) || FAILED(D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_WARP, nullptr,
            D3D11_CREATE_DEVICE_BGRA_SUPPORT, nullptr, 0, D3D11_SDK_VERSION,
            d3d.GetAddressOf(), nullptr, nullptr)) ||
        FAILED(d3d->QueryInterface(IID_PPV_ARGS(dxgi.GetAddressOf()))) ||
        FAILED(factory->CreateDevice(dxgi.Get(), device.GetAddressOf())) ||
        FAILED(device->CreateDeviceContext(D2D1_DEVICE_CONTEXT_OPTIONS_NONE, dc.GetAddressOf()))) return 2;
    const auto size = D2D1::SizeU(564, 12);
    const auto format = D2D1::PixelFormat(DXGI_FORMAT_B8G8R8A8_UNORM, D2D1_ALPHA_MODE_PREMULTIPLIED);
    auto props = D2D1::BitmapProperties1(D2D1_BITMAP_OPTIONS_TARGET, format);
    ComPtr<ID2D1Bitmap1> target, pixels;
    if (FAILED(dc->CreateBitmap(size, nullptr, 0, props, target.GetAddressOf()))) return 2;
    props.bitmapOptions = D2D1_BITMAP_OPTIONS_CPU_READ | D2D1_BITMAP_OPTIONS_CANNOT_DRAW;
    if (FAILED(dc->CreateBitmap(size, nullptr, 0, props, pixels.GetAddressOf()))) return 2;
    dc->SetTarget(target.Get());
    dc->BeginDraw();
    dc->Clear(D2D1::ColorF(D2D1::ColorF::White));
    spk::ProgressBar bar;
    bar.SetBounds({0, 0, 564, 12});
    bar.SetProgressPermille(300); // x=2..170, y=2..10
    bar.Render(dc.Get(), spk::LightTheme());
    if (FAILED(dc->EndDraw()) || FAILED(pixels->CopyFromBitmap(nullptr, target.Get(), nullptr))) return 2;
    D2D1_MAPPED_RECT mapped{};
    if (FAILED(pixels->Map(D2D1_MAP_OPTIONS_READ, &mapped))) return 2;
    const int corner = mapped.bits[2 * mapped.pitch + 169 * 4];
    const int middle = mapped.bits[6 * mapped.pitch + 169 * 4];
    pixels->Unmap();
    if (corner <= middle + 80) {
        std::fprintf(stderr, "Expected rounded cap, corner=%d middle=%d\n", corner, middle);
        return 1;
    }
    return 0;
}
