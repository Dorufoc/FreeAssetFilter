// Standalone MinGW regression harness for the installer's owner-drawn input.
#include "render/license_sheet.h"
#include "render/layout.h"
#include "render/pages_welcome.h"
#include "render/render_context.h"
#include <cstdio>
#include <d2d1_1helper.h>

namespace {

bool VerifyAgreementRendering(spk::LicenseSheet& sheet) {
    using spk::ComPtr;
    ComPtr<ID3D11Device> d3d;
    ComPtr<IDXGIDevice> dxgi;
    ComPtr<ID2D1Factory1> factory;
    ComPtr<ID2D1Device> device;
    ComPtr<ID2D1DeviceContext> dc;
    if (FAILED(D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_WARP, nullptr, D3D11_CREATE_DEVICE_BGRA_SUPPORT,
                                nullptr, 0, D3D11_SDK_VERSION, d3d.GetAddressOf(), nullptr, nullptr)) ||
        FAILED(d3d->QueryInterface(IID_PPV_ARGS(dxgi.GetAddressOf()))) ||
        FAILED(D2D1CreateFactory(D2D1_FACTORY_TYPE_SINGLE_THREADED, factory.GetAddressOf())) ||
        FAILED(factory->CreateDevice(dxgi.Get(), device.GetAddressOf())) ||
        FAILED(device->CreateDeviceContext(D2D1_DEVICE_CONTEXT_OPTIONS_NONE, dc.GetAddressOf()))) {
        return false;
    }

    const D2D1_SIZE_U size{700, 600};
    auto properties = D2D1::BitmapProperties1(D2D1_BITMAP_OPTIONS_TARGET,
        D2D1::PixelFormat(DXGI_FORMAT_B8G8R8A8_UNORM, D2D1_ALPHA_MODE_PREMULTIPLIED), 96, 96);
    ComPtr<ID2D1Bitmap1> target, readback;
    if (FAILED(dc->CreateBitmap(size, nullptr, 0, properties, target.GetAddressOf()))) return false;
    properties.bitmapOptions = D2D1_BITMAP_OPTIONS_CPU_READ | D2D1_BITMAP_OPTIONS_CANNOT_DRAW;
    if (FAILED(dc->CreateBitmap(size, nullptr, 0, properties, readback.GetAddressOf()))) return false;
    dc->SetTarget(target.Get());
    dc->SetDpi(96, 96);
    dc->BeginDraw();
    dc->Clear(D2D1::ColorF(0, 0.0f));
    dc->SetTransform(D2D1::Matrix3x2F::Translation(20.0f, 10.0f));
    sheet.Render(dc.Get(), spk::LightTheme());
    D2D1_MATRIX_3X2_F after{};
    dc->GetTransform(&after);
    if (FAILED(dc->EndDraw())) return false;
    dc->SetTarget(nullptr);
    if (FAILED(readback->CopyFromBitmap(nullptr, target.Get(), nullptr))) return false;
    D2D1_MAPPED_RECT pixels{};
    if (FAILED(readback->Map(D2D1_MAP_OPTIONS_READ, &pixels))) return false;
    const auto alpha = [&](unsigned x, unsigned y) { return pixels.bits[y * pixels.pitch + x * 4 + 3]; };
    // Read a gutter, the old modal card area, and points inside and outside the shifted Back button.
    const bool ok = after._31 == 20.0f && after._32 == 10.0f &&
                    alpha(25, 200) == 0 && alpha(65, 422) == 0 &&
                    alpha(static_cast<unsigned>(spk::design::kButtonLeft) + 18, 451) == 0 &&
                    alpha(static_cast<unsigned>(spk::design::kButtonLeft) + 29, 451) != 0;
    readback->Unmap();
    return ok;
}

}  // namespace

int main() {
    int failures = 0;
    auto check = [&](bool ok, const char* name) {
        std::printf("%s %s\n", ok ? "PASS" : "FAIL", name);
        if (!ok) ++failures;
    };
    using namespace spk;
    PathField field;
    Button button;
    field.SetBounds({0, 0, 80, 30});
    button.SetBounds({90, 0, 180, 30});
    WidgetHost host;
    host.Add(&field);
    host.Add(&button);
    host.FocusNext();
    host.Dispatch({InputEvent::Key, 0, 0, VK_RETURN});
    check(field.TakeActivated(), "Enter activates focused path field");
    host.Dispatch({InputEvent::Up, 10, 10});
    check(!field.TakeActivated(), "stray release cannot open the picker");
    host.Dispatch({InputEvent::Move, 100, 10});
    host.Dispatch({InputEvent::Move, 10, 10});
    check(!button.Hovered() && field.Hovered(), "moving to another widget clears hover");
    host.Dispatch({InputEvent::Down, 100, 10});
    check(host.Dispatch({InputEvent::Up, 10, 10}), "release outside requests repaint of pressed state");
    check(!field.TakeActivated() && !button.Pressed() && !button.ClickCount(), "drag release cannot activate another widget");
    host.Dispatch({InputEvent::Down, 100, 10});
    host.Dispatch({InputEvent::Up, 100, 10});
    check(button.ClickCount() == 1, "matching press and release click once");
    host.Clear();
    check(!button.Focused(), "rebuilding tab order clears former focus");
    LicenseSheet sheet;
    sheet.Layout(ComputeShellLayout(false).contentCard);
    check(sheet.BackButton().Bounds().left == design::kButtonLeft &&
          sheet.BackButton().Bounds().top == design::kButtonTop, "agreement uses the standard action position");
    auto* reader = dynamic_cast<LicenseBox*>(sheet.Host().Widgets().front());
    check(reader && reader->Bounds().left == layout::kContentLeft &&
          reader->Bounds().right == layout::kContentLeft + layout::kContentWidth,
          "agreement reading area uses the full content width");
    if (!reader) return 1;
    sheet.SetContent(L"开源协议", std::wstring(8000, L'x'));
    sheet.Enter();
    check(sheet.Host().Focused() == reader, "entering agreement focuses the reader");
    sheet.Host().Dispatch({InputEvent::Key, 0, 0, VK_END});
    check(reader->ScrollOffset() > 0 && reader->AtBottom(), "focused reader scrolls to the end");
    sheet.Host().FocusNext();
    check(sheet.Host().Focused() == &sheet.BackButton(), "Tab moves from reader to Back");
    sheet.Layout(ComputeShellLayout(false).contentCard);
    check(sheet.Host().Focused() == &sheet.BackButton(), "relayout preserves focused Back button");
    int returns = 0;
    sheet.BackButton().SetOnClick([&] { ++returns; });
    sheet.Host().Dispatch({InputEvent::Key, 0, 0, VK_RETURN});
    check(returns == 1, "Enter invokes the Back button callback");
    const auto box = reader->Bounds();
    sheet.Host().Dispatch({InputEvent::Down, box.left + 1, box.top + 1});
    sheet.SetContent(L"用户协议", std::wstring(8000, L'y'));
    sheet.Enter();
    check(reader->Text().front() == L'y' && reader->ScrollOffset() == 0,
          "re-entering with new content resets the reader to the top");
    check(sheet.Host().Focused() == reader && !sheet.Host().HasPointerPress() && !reader->Dragging(),
          "re-entering resets pointer capture and restores reading focus");
    check(VerifyAgreementRendering(sheet), "agreement renders without a backdrop and preserves the parent transform");
    CheckBox checkbox;
    Animator animator;
    checkbox.BindAnimator(&animator);
    checkbox.SetChecked(true);
    checkbox.SetChecked(false);
    animator.Tick(0);
    animator.Tick(200);
    check(checkbox.CheckProgress() == 0.0f, "rapid checkbox reversal lands on current state");
    return failures != 0;
}
