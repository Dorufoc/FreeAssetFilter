// Standalone D2D readback regression for the agreement scroller.
#include <cstdio>
#include <cmath>
#include <d3d11.h>
#include "render/controls_feedback.h"
#include <d2d1_1helper.h>
#include "render/render_context.h"

int main() {
    using namespace spk;
    ComPtr<ID3D11Device> device;
    ComPtr<IDXGIDevice> dxgi;
    ComPtr<ID2D1Factory1> factory;
    ComPtr<ID2D1Device> d2d;
    ComPtr<ID2D1DeviceContext> dc;
    if (FAILED(D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_WARP, nullptr, D3D11_CREATE_DEVICE_BGRA_SUPPORT,
            nullptr, 0, D3D11_SDK_VERSION, device.GetAddressOf(), nullptr, nullptr)) ||
        FAILED(device->QueryInterface(IID_PPV_ARGS(dxgi.GetAddressOf()))) ||
        FAILED(D2D1CreateFactory(D2D1_FACTORY_TYPE_SINGLE_THREADED, factory.GetAddressOf())) ||
        FAILED(factory->CreateDevice(dxgi.Get(), d2d.GetAddressOf())) ||
        FAILED(d2d->CreateDeviceContext(D2D1_DEVICE_CONTEXT_OPTIONS_NONE, dc.GetAddressOf()))) return 2;
    const auto size = D2D1::SizeU(400, 240);
    const auto format = D2D1::PixelFormat(DXGI_FORMAT_B8G8R8A8_UNORM, D2D1_ALPHA_MODE_PREMULTIPLIED);
    auto props = D2D1::BitmapProperties1(D2D1_BITMAP_OPTIONS_TARGET, format, 96, 96);
    ComPtr<ID2D1Bitmap1> canvas, readback;
    if (FAILED(dc->CreateBitmap(size, nullptr, 0, props, canvas.GetAddressOf()))) return 2;
    props.bitmapOptions = D2D1_BITMAP_OPTIONS_CPU_READ | D2D1_BITMAP_OPTIONS_CANNOT_DRAW;
    if (FAILED(dc->CreateBitmap(size, nullptr, 0, props, readback.GetAddressOf()))) return 2;

    LicenseBox box;
    box.SetBounds({0, 0, 400, 240});
    box.SetText(std::wstring(8000, L'x'));
    const auto render = [&](unsigned& width, unsigned& track, unsigned& edges) {
        dc->SetTarget(canvas.Get());
        dc->BeginDraw();
        dc->Clear(D2D1::ColorF(0, 0, 0, 0));
        box.Render(dc.Get(), LightTheme());
        if (FAILED(dc->EndDraw()) || FAILED(readback->CopyFromBitmap(nullptr, canvas.Get(), nullptr))) return false;
        D2D1_MAPPED_RECT mapped{};
        if (FAILED(readback->Map(D2D1_MAP_OPTIONS_READ, &mapped))) return false;
        const auto alpha = [&](unsigned x, unsigned y) { return mapped.bits[y * mapped.pitch + x * 4 + 3]; };
        width = 0;
        const auto background = alpha(50, 120);
        for (unsigned x = 382; x < 400; ++x) width += alpha(x, 30) > background;
        track = alpha(395, 180) > background;
        edges = background < 88 || background > 90 || alpha(50, 0) != background ||
                alpha(50, 18) != background || alpha(50, 220) != background;
        readback->Unmap();
        return true;
    };
    unsigned resting{}, hovered{}, dragging{}, width{}, track{}, edges{};
    unsigned failed = 0;
    const auto check = [&](bool ok, const char* message) {
        if (!ok) { std::printf("FAIL: %s\n", message); ++failed; }
    };
    box.OnFocus(true);
    if (!render(resting, track, edges)) return 2;
    check(!edges, "focused reader has a uniform single translucent fill and no outline or edge fade");
    check(resting == 4 && track == 0, "resting thumb is compact and track is hidden");
    const float height = box.ContentHeight();
    check(height == std::ceil(8000.0f / (368.0f / (14.0f * .55f))) * (14.0f * 1.35f),
          "line wrapping uses equal 16 DIP insets without scrollbar reserve");
    box.OnInput({InputEvent::Move, 390, 30});
    if (!render(hovered, track, edges)) return 2;
    check(hovered > resting && track > 0, "hover reveals track and widens thumb");
    box.OnInput({InputEvent::Down, 390, 30});
    box.OnInput({InputEvent::Move, 500, 30});
    if (!render(dragging, track, edges)) return 2;
    check(box.Dragging() && dragging > resting && track > 0 && box.ContentHeight() == height,
          "captured thumb stays expanded without altering text layout");
    box.OnInput({InputEvent::Up, 500, 30});
    if (!render(width, track, edges)) return 2;
    check(!box.Dragging() && width == resting && track == 0, "release outside clears drag and hover");

    for (int i = 0; i < 8; ++i) box.OnInput({InputEvent::Wheel, 100, 100, -15});
    check(std::abs(box.ScrollOffset() - 42.0f) < 0.01f, "fractional wheel deltas accumulate exactly");
    box.OnInput({InputEvent::Down, 100, 100});
    box.OnInput({InputEvent::Move, 100, 70});
    box.OnInput({InputEvent::Up, 100, 70});
    check(std::abs(box.ScrollOffset() - 72.0f) < 0.01f, "body pans with pointer drag");
    Animator animator;
    box.BindAnimator(&animator);
    box.SetScrollOffset(0.0f);
    box.OnInput({InputEvent::Wheel, 100, 100, -1});
    check(std::abs(box.ScrollOffset() - 0.35f) < 0.01f,
          "sub-notch input updates immediately even with animations enabled");
    box.OnInput({InputEvent::Move, 395, 30});
    animator.Tick(0);
    if (!render(width, track, edges)) return 2;
    check(width == resting, "scrollbar expansion starts at the resting width");
    animator.Tick(121);
    if (!render(width, track, edges)) return 2;
    check(width == 6, "scrollbar reaches six DIP after its animation");

    ComPtr<IDWriteFactory> write;
    if (FAILED(DWriteCreateFactory(DWRITE_FACTORY_TYPE_SHARED, __uuidof(IDWriteFactory),
               reinterpret_cast<IUnknown**>(write.GetAddressOf())))) return 2;
    TextFactory textFactory;
    if (FAILED(textFactory.Initialize(write.Get()))) return 2;
    box.BindText(&textFactory);
    box.BindWriteFactory(write.Get());
    box.SetText(std::wstring(80, L'\n') + L"Last line");
    box.SetScrollOffset(box.MaxScroll());
    check(box.MaxScroll() > 0 && box.AtBottom(), "DirectWrite document can reach its last line");
    if (!render(width, track, edges)) return 2;
    D2D1_MAPPED_RECT endPixels{};
    if (FAILED(readback->Map(D2D1_MAP_OPTIONS_READ, &endPixels))) return 2;
    bool lastLineVisible = false;
    for (unsigned y = 200; y < 224; ++y) {
        for (unsigned x = 16; x < 100; ++x) {
            lastLineVisible |= endPixels.bits[y * endPixels.pitch + x * 4 + 3] > 90;
        }
    }
    readback->Unmap();
    check(lastLineVisible, "last line produces visible glyphs in the viewport");
    box.SetText(L"");
    if (!render(width, track, edges)) return 2;
    check(!width && !track && !edges, "empty reader is fully transparent");
    return failed ? 1 : 0;
}
