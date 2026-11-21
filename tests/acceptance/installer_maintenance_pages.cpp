// Standalone Windows test: link pages_maintenance, controls_basic, layout, theme,
// text, glyphs and animation with -ldwrite -ld2d1 -lgdi32 -ldwmapi -lole32.
#include "render/pages_maintenance.h"
#include "render/layout.h"
#include "render/pages_progress.h"
#include "render/pages_welcome.h"
#include <cstdio>
#include <d3d11.h>
#include <d2d1_1helper.h>
#include "render/render_context.h"

// WARP draws the actual page offscreen. Read pixels back at 96 DPI so each
// canvas DIP maps to one pixel, including the blank 24-DIP design gutter.
bool MessageInkStaysInside(const spk::Theme& theme) {
    using namespace spk;
    ComPtr<ID3D11Device> device;
    if (FAILED(D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_WARP, nullptr, D3D11_CREATE_DEVICE_BGRA_SUPPORT,
        nullptr, 0, D3D11_SDK_VERSION, device.GetAddressOf(), nullptr, nullptr))) return false;
    ComPtr<IDXGIDevice> dxgi;
    if (FAILED(device->QueryInterface(IID_PPV_ARGS(dxgi.GetAddressOf())))) return false;
    ComPtr<ID2D1Device> d2d;
    ComPtr<ID2D1Factory1> d2factory;
    if (FAILED(D2D1CreateFactory(D2D1_FACTORY_TYPE_SINGLE_THREADED, d2factory.GetAddressOf()))) return false;
    if (FAILED(d2factory->CreateDevice(dxgi.Get(), d2d.GetAddressOf()))) return false;
    ComPtr<ID2D1DeviceContext> dc;
    if (FAILED(d2d->CreateDeviceContext(D2D1_DEVICE_CONTEXT_OPTIONS_NONE, dc.GetAddressOf()))) return false;
    auto props = D2D1::BitmapProperties1(D2D1_BITMAP_OPTIONS_TARGET, D2D1::PixelFormat(DXGI_FORMAT_B8G8R8A8_UNORM, D2D1_ALPHA_MODE_PREMULTIPLIED));
    ComPtr<ID2D1Bitmap1> canvas, readback;
    const auto size = D2D1::SizeU(641, 545);
    if (FAILED(dc->CreateBitmap(size, nullptr, 0, props, canvas.GetAddressOf()))) return false;
    props.bitmapOptions = D2D1_BITMAP_OPTIONS_CPU_READ | D2D1_BITMAP_OPTIONS_CANNOT_DRAW;
    if (FAILED(dc->CreateBitmap(size, nullptr, 0, props, readback.GetAddressOf()))) return false;
    ComPtr<IDWriteFactory> factory;
    if (FAILED(DWriteCreateFactory(DWRITE_FACTORY_TYPE_SHARED, __uuidof(IDWriteFactory), reinterpret_cast<IUnknown**>(factory.GetAddressOf())))) return false;
    TextFactory text;
    if (FAILED(text.Initialize(factory.Get()))) return false;
    MessagePage page;
    page.BindText(&text);
    page.SetContent(std::wstring(400, L'M'), std::wstring(3500, L'文'), std::wstring(300, L'确'), std::wstring(300, L'返'), true);
    page.Layout(ComputeShellLayout(true).contentCard);
    dc->SetTarget(canvas.Get());
    dc->BeginDraw();
    dc->Clear(theme.card);
    page.Render(dc.Get(), theme);
    if (FAILED(dc->EndDraw())) return false;
    dc->SetTarget(nullptr);
    if (FAILED(readback->CopyFromBitmap(nullptr, canvas.Get(), nullptr))) return false;
    D2D1_MAPPED_RECT pixels{};
    if (FAILED(readback->Map(D2D1_MAP_OPTIONS_READ, &pixels))) return false;
    bool safe = true;
    unsigned ink = 0;
    const auto bg = *reinterpret_cast<const UINT32*>(pixels.bits);
    const int actionsTop = static_cast<int>(page.PrimaryButton().Bounds().top);
    for (unsigned y = 0; y < size.height; ++y) {
        const auto* row = reinterpret_cast<const UINT32*>(pixels.bits + pixels.pitch * y);
        for (unsigned x = 0; x < size.width; ++x) if (row[x] != bg) {
            ++ink;
            if (x < 24 || x >= size.width - 24 || y >= size.height - 16 ||
                (static_cast<int>(y) >= actionsTop - 12 && static_cast<int>(y) < actionsTop - 3)) safe = false;
        }
    }
    readback->Unmap();
    return safe && ink > 1000;
}

namespace {
int failures = 0;
void Check(bool condition, const char* message) {
    if (!condition) { std::fprintf(stderr, "FAIL: %s\n", message); ++failures; }
}
}

int main() {
    using namespace spk;
    Check(MessageInkStaysInside(LightTheme()), "light: long message respects margins and action gutter");
    Check(MessageInkStaysInside(DarkTheme()), "dark: long message respects margins and action gutter");
    auto card = ComputeShellLayout(true).contentCard;
    auto inset = card;
    inset.left += 8; inset.right += 8; inset.top += 8; inset.bottom += 8;
    AppState state;
    MaintenancePage maintenance(state);
    maintenance.SetInfo(std::wstring(1000, L'路'), std::wstring(300, L'版'), true, false);
    maintenance.Layout(card);
    auto bounds = maintenance.RepairButton().Bounds();
    maintenance.Layout(inset);
    Check(bounds.left == maintenance.RepairButton().Bounds().left && bounds.top == maintenance.RepairButton().Bounds().top, "maintenance hit bounds stay in canvas DIP");
    Check(bounds.right - bounds.left == 152 && bounds.bottom - bounds.top == 36, "repair uses design primary button size");
    Check(bounds.left == 244 && bounds.top == 427, "repair primary uses welcome button position");
    Check(maintenance.UninstallButton().Bounds().top > bounds.bottom, "uninstall link follows repair primary");
    int updates = 0, repairs = 0, uninstalls = 0;
    maintenance.SetOnUpdate([&]() { ++updates; });
    maintenance.SetOnRepair([&]() { ++repairs; });
    maintenance.SetOnUninstall([&]() { ++uninstalls; });
    maintenance.SetOffer(MaintenanceOffer::Update);
    maintenance.Host().FocusNext();
    Check(maintenance.Host().Focused() == &maintenance.UpdateButton(), "update is the primary action on newer packages");
    maintenance.Host().Dispatch({InputEvent::Key, 0, 0, VK_RETURN});
    maintenance.Host().FocusNext();
    Check(maintenance.Host().Focused() == &maintenance.RepairButton(), "repair is the secondary action on newer packages");
    maintenance.Host().Dispatch({InputEvent::Key, 0, 0, VK_RETURN});
    Check(updates == 1 && repairs == 1 && uninstalls == 0 && !maintenance.UninstallButton().Enabled(), "update and repair dispatch distinct actions");
    maintenance.SetOffer(MaintenanceOffer::UninstallOnly);
    maintenance.Host().FocusNext();
    Check(maintenance.Host().Focused() == &maintenance.UninstallButton(), "uninstall-only entry focuses uninstall");
    maintenance.Host().Dispatch({InputEvent::Key, 0, 0, VK_RETURN});
    Check(uninstalls == 1, "uninstall-only entry dispatches uninstall");
    maintenance.SetOffer(MaintenanceOffer::Repair);
    maintenance.Host().FocusWidget(&maintenance.RepairButton());
    maintenance.SetInfo(L"", L"", false, false);
    Check(maintenance.Host().Focused() != &maintenance.RepairButton(), "disabled repair releases focus");

    UninstallConfirmPage uninstall(state);
    uninstall.Layout(card);
    bounds = uninstall.ConfirmButton().Bounds();
    uninstall.Layout(inset);
    Check(bounds.left == uninstall.ConfirmButton().Bounds().left && bounds.top == uninstall.ConfirmButton().Bounds().top, "uninstall hit bounds stay in canvas DIP");
    Check(!uninstall.DeleteUserData(), "preserve data by default");
    const auto checkbox = uninstall.DeleteUserDataBox().Bounds();
    Check(checkbox.left == design::kOptionAutostartLeft && checkbox.top < 220,
          "uninstall checklist uses the configuration column near its title");
    ProgressPage progress(state);
    progress.Layout(card);
    const auto track = progress.Bar().Bounds();
    Check(track.left == layout::kContentLeft && track.top > design::kPageTitleBaselineY &&
          track.top >= 460 && track.bottom <= 486, "progress track retains the bottom layout and center whitespace");
    uninstall.Host().FocusNext();
    Check(uninstall.Host().Focused() == &uninstall.DeleteUserDataBox(), "checkbox first");
    uninstall.Host().Dispatch({InputEvent::Key, 0, 0, VK_SPACE});
    Check(state.deleteUserData, "keyboard toggle updates state");
    uninstall.Host().FocusNext();
    Check(uninstall.Host().Focused() == &uninstall.ConfirmButton(), "next follows checkbox in the visual order");
    uninstall.Host().FocusNext();
    Check(uninstall.Host().Focused() == &uninstall.CancelButton(), "cancel follows primary action");
    uninstall.SetChecklist(false);
    uninstall.Host().FocusNext();
    Check(uninstall.Host().Focused() == &uninstall.ConfirmButton(), "uninstall welcome has no checkbox");

    MessagePage message;
    message.Host().FocusNext();
    Check(!message.Host().Focused(), "empty initial message has no focusable buttons");
    message.Host().FocusWidget(nullptr);
    message.SetContent(std::wstring(200, L'题'), std::wstring(2000, L'文'), L"确认", L"返回", true);
    message.Layout(card);
    bounds = message.PrimaryButton().Bounds();
    message.Layout(inset);
    Check(bounds.left == message.PrimaryButton().Bounds().left && bounds.top == message.PrimaryButton().Bounds().top, "message hit bounds stay in canvas DIP");
    message.Host().FocusNext();
    Check(message.Host().Focused() == &message.SecondaryButton() && message.SecondaryButton().Bounds().right <= bounds.left, "tab follows visible message buttons left to right");
    message.Host().FocusNext(true);
    Check(message.Host().Focused() == &message.PrimaryButton(), "backward Tab wraps");
    message.SetBusy(true, L"等待");
    Check(!message.Host().Focused() && !message.PrimaryButton().Enabled() && !message.SecondaryButton().Enabled(), "busy hides both actions and releases focus");
    message.SetContent(L"消息", L"正文", L"", L"返回", true);
    message.SetBusy(false);
    message.Host().FocusNext();
    Check(message.Host().Focused() == &message.SecondaryButton(), "secondary-only mode reachable after busy");
    if (!failures) std::puts("Maintenance page regression checks passed");
    return failures ? 1 : 0;
}
