#include "installer_window.h"
#include <windows.h>
#include <string>

int APIENTRY WinMain(HINSTANCE instance, HINSTANCE, LPSTR, int) {
    int argc = 0;
    LPWSTR* argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    std::wstring payload;
    std::wstring resultPath;
    for (int i = 1; i + 1 < argc; ++i) {
        if (_wcsicmp(argv[i], L"/payload") == 0) payload = argv[i + 1];
        if (_wcsicmp(argv[i], L"/result") == 0) resultPath = argv[i + 1];
    }
    if (argv) LocalFree(argv);
    if (payload.empty()) payload = L".";
    if (resultPath.empty()) resultPath = payload + L"\\..\\install-result.txt";
    return InstallerWindow(instance, payload, resultPath).Run();
}
