// Standalone Windows regression test. Run in a throwaway directory (argv[1]).
#include "render/pages_setup.h"
#include "render/layout.h"
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>

int main(int argc, char** argv) {
    if (argc != 2) return 2;
    const std::filesystem::path dir = std::filesystem::absolute(argv[1]);
    // Require a fresh fixture root before writing any sentinel files.
    if (!std::filesystem::create_directory(dir)) return 2;
    const auto existing = dir / L".spk_write_probe.tmp";
    std::ofstream(existing) << "keep";
    AppState state;
    state.installDir = (dir / L"new-install").wstring();
    state.agreed = true;
    spk::ConfigurePage page(state);
    page.OnEnter();
    bool ok = true;
    auto check = [&](bool result, const char* msg) {
        if (!result) { std::cerr << msg << '\n'; ok = false; }
    };
    std::string contents;
    std::ifstream(existing) >> contents;
    check(contents == "keep", "checking permission overwrote an existing file");
    check(!std::filesystem::exists(state.installDir), "checking permission created the install target");
    page.SetPayloadDir(L"", std::numeric_limits<unsigned long long>::max());
    check(!page.CanProceed() && !page.SpaceSufficient(), "payload change left stale disk-space gate");
    const auto regular = dir / L"regular";
    std::ofstream(regular) << "file";
    std::wstring error;
    check(!spk::ProbeWritable((regular / L"child").wstring(), error), "file ancestor treated as directory");
    page.SetPayloadDir(L"", 1);
    check(page.CanProceed(), "payload change did not release disk-space gate");
    page.Layout(spk::ComputeShellLayout(false).contentCard);
    check(!page.BackButton().HitTest(1, 497), "blank canvas activates Back");
    int opened = 0;
    page.SetOnOpenDocument([&](bool user) { opened += user ? 10 : 1; });
    page.Host().FocusWidget(&page.AgreeBox());
    const spk::InputEvent enter{spk::InputEvent::Key, 0, 0, VK_RETURN};
    page.Host().FocusNext();
    page.OnInput(enter);
    page.Host().FocusNext();
    page.OnInput(enter);
    check(opened == 11 && state.agreed, "Tab/Enter could not read both agreements independently");
    state.optAutostart = true;
    state.optContextMenu = false;
    state.optDesktop = false;
    state.optStartmenu = false;
    state.agreed = false;
    page.SetMaintenanceMode(Operation::Repair);
    page.OnEnter();
    check(!page.Field().IsFocusable() && !page.AutostartBox().Enabled() &&
          !page.ContextMenuBox().Enabled() && !page.DesktopBox().Enabled(), "maintenance options are editable");
    check(page.AutostartBox().Checked() && !page.ContextMenuBox().Checked() &&
          !page.DesktopBox().Checked(), "maintenance options did not reflect stored settings");
    check(!page.CanProceed() && page.AgreeBox().Enabled(), "maintenance needs a fresh agreement");
    page.Host().FocusWidget(&page.AgreeBox());
    page.OnInput(enter);
    page.SyncToState();
    check(page.CanProceed() && !state.optStartmenu, "maintenance overwrote a stored option");
    page.SetMaintenanceMode(Operation::Install);
    check(page.Field().IsFocusable() && page.AutostartBox().Enabled(), "fresh setup did not unlock options");
    return ok ? 0 : 1;
}
