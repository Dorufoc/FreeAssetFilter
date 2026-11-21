// Run against the real detector, with HKCU redirected only inside this process.
#include <windows.h>
#include <cstdio>
#include <string>
#include "maintenance_detector.h"
#include "render/maintenance_protocol.h"

int main() {
    const std::wstring fixture = L"Software\\SopeekMaintenanceFixture-" + std::to_wstring(GetCurrentProcessId());
    HKEY root{}, options{};
    if (RegCreateKeyExW(HKEY_CURRENT_USER, fixture.c_str(), 0, nullptr, REG_OPTION_NON_VOLATILE,
                        KEY_ALL_ACCESS, nullptr, &root, nullptr) != ERROR_SUCCESS) return 2;
    bool ok = RegOverridePredefKey(HKEY_CURRENT_USER, root) == ERROR_SUCCESS &&
              RegCreateKeyW(root, spk::protocol::kInstallInfoKey, &options) == ERROR_SUCCESS;
    wchar_t tmp[MAX_PATH]{}, ini[MAX_PATH]{};
    ok = ok && GetTempPathW(MAX_PATH, tmp) && GetTempFileNameW(tmp, L"spk", 0, ini);
    for (DWORD enabled : {0UL, 1UL}) {
        if (!ok) break;
        ok = RegSetValueExW(options, L"OptCtxMenu", 0, REG_DWORD,
                            reinterpret_cast<const BYTE*>(&enabled), sizeof(enabled)) == ERROR_SUCCESS &&
             spk::WriteMaintenanceDump(spk::Detect(L"C:\\SopeekFixture"), ini);
        const UINT actual = GetPrivateProfileIntW(L"maintenance", L"opt_ctxmenu", 9, ini);
        if (actual != enabled) {
            std::fprintf(stderr, "Expected opt_ctxmenu=%lu, got %u\n", enabled, actual);
            ok = false;
        }
    }
    if (*ini) DeleteFileW(ini);
    if (options) RegCloseKey(options);
    RegOverridePredefKey(HKEY_CURRENT_USER, nullptr);
    RegCloseKey(root);
    RegDeleteTreeW(HKEY_CURRENT_USER, fixture.c_str());
    return ok ? 0 : 1;
}
