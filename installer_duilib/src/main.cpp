#include "installer_window.h"

#include <windows.h>
#include <shellscalingapi.h>  // SetProcessDpiAwareness（Win8.1+ 回退）

#include <string>
#include <cstdlib>  // _wtoi（/auto:page= 解析）

namespace {

// §6 进程 DPI 感知（唯一位置 = WinMain 最早期，早于任何窗口与 COM 初始化）。
// 优先 Per-Monitor-V2（Win10 1703+，经 GetProcAddress 动态解析），失败回退
// SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE)（shcore，Win8.1+），
// 再失败回退 SetProcessDPIAware()（user32）。
void EnableProcessDpiAwareness() {
    HMODULE user32 = GetModuleHandleW(L"user32.dll");
    if (user32) {
        using SetProcessDpiAwarenessContextFn = BOOL(WINAPI*)(DPI_AWARENESS_CONTEXT);
        auto setContext = reinterpret_cast<SetProcessDpiAwarenessContextFn>(
            GetProcAddress(user32, "SetProcessDpiAwarenessContext"));
        if (setContext && setContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)) return;
    }

    HMODULE shcore = LoadLibraryW(L"shcore.dll");
    if (shcore) {
        using SetProcessDpiAwarenessFn = HRESULT(WINAPI*)(PROCESS_DPI_AWARENESS);
        auto setAwareness = reinterpret_cast<SetProcessDpiAwarenessFn>(
            GetProcAddress(shcore, "SetProcessDpiAwareness"));
        if (setAwareness &&
            SUCCEEDED(setAwareness(PROCESS_PER_MONITOR_DPI_AWARE))) {
            return;
        }
    }

    SetProcessDPIAware();
}

}  // namespace

int APIENTRY WinMain(HINSTANCE instance, HINSTANCE, LPSTR, int) {
    // §6：必须位于 WinMain 最早期，早于任何窗口创建与 COM 初始化。
    EnableProcessDpiAwareness();

    int argc = 0;
    LPWSTR* argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    std::wstring payload;
    std::wstring resultPath;
    // Todo 15（main.cpp owner 次序 2 → 15 → 19，§13）：/installdir 由 NSIS 生产
    // `Exec` 行传入（重装预填 Location 页）。
    std::wstring installDir;
    for (int i = 1; i + 1 < argc; ++i) {
        if (_wcsicmp(argv[i], L"/payload") == 0) payload = argv[i + 1];
        if (_wcsicmp(argv[i], L"/result") == 0) resultPath = argv[i + 1];
        if (_wcsicmp(argv[i], L"/installdir") == 0) installDir = argv[i + 1];
    }
    // Todo 19（§17）：/auto 无人值守开关解析。解析在**两种构建中无条件**进行
    //（解析本身无行为副作用）；驱动行为只在 FAF_TESTMODE 构建中编入（见文末
    // #ifdef 与 installer_window.cpp），生产构建解析后直接丢弃、完全保持交互式。
    // 形式：`/auto`（全默认档）、`/auto:opts=<bits>`（§17 四位 0/1 = 桌面/开始菜单/
    // 开机自启/完成后启动；缺位/非法位取 §2 默认 1,1,0,1）、`/auto:page=N`
    //（0..5，固定时序推进到第 N 页后停住；越界视为不停）。
    bool autoDrive = false;
    std::wstring autoProfile;
    int autoStopPage = -1;
    for (int i = 1; i < argc; ++i) {
        const wchar_t* arg = argv[i];
        if (_wcsicmp(arg, L"/auto") == 0) {
            autoDrive = true;
        } else if (_wcsnicmp(arg, L"/auto:opts=", 11) == 0) {
            autoDrive = true;
            autoProfile = arg + 11;
        } else if (_wcsnicmp(arg, L"/auto:page=", 11) == 0) {
            autoDrive = true;
            autoStopPage = _wtoi(arg + 11);
        }
    }
    if (argv) LocalFree(argv);
    if (payload.empty()) payload = L".";
    // §1：结果协议为 INI（与 §13 引擎 resultPath_ 一致；旧 .txt 协议已作废）。
    if (resultPath.empty()) resultPath = payload + L"\\..\\install-result.ini";

#ifdef FAF_TESTMODE
    // 测试构建（FAF_TESTMODE 仅由 cmake/test_mode.cmake 在 -DFAF_TESTMODE=ON 时
    // 定义）：/auto 真正驱动无人值守流程走完 6 页。
    InstallerWindow window(instance, payload, resultPath, installDir);
    if (autoDrive) window.EnableAutoDrive(autoProfile, autoStopPage);
    return window.Run();
#else
    // 生产构建：/auto 已解析但**无任何效果**（不触碰窗口状态；保持完全交互）。
    (void)autoDrive;
    (void)autoProfile;
    (void)autoStopPage;
    return InstallerWindow(instance, payload, resultPath, installDir).Run();
#endif
}
