//
// launch_forward.cpp - §15 完成后启动的去提权转发实现（Todo 15）。
//
// 唯一机制（§15，不得另行发明）：`ShellExecuteW(L"open", L"explorer.exe",
// L"\"<target>\"", ...)`。直接 `ShellExecuteW(target)` 属于禁止项（子进程继承
// 管理员令牌）。详见头文件注释。
//
#include "render/launch_forward.h"

#include <shellapi.h>

#include <filesystem>
#include <system_error>

namespace fs = std::filesystem;

namespace faf {

LaunchOutcome LaunchInstalledAppDeElevated(const std::wstring& installDir, HWND owner) {
    LaunchOutcome outcome;
    if (installDir.empty()) {
        outcome.error = L"安装目录为空，无法启动";
        return outcome;
    }

    const fs::path exePath = fs::path(installDir) / L"FreeAssetFilter.exe";
    std::error_code ec;
    if (!fs::exists(exePath, ec)) {
        // 目标缺失：不崩溃、不抛异常 —— 只返回可展示的错误（QA 场景 launch-missing）。
        outcome.missingExe = true;
        outcome.error = L"未找到已安装的程序：" + exePath.wstring();
        return outcome;
    }

    // §15：去提权转发。参数 = 带引号的目标路径（路径可含空格/非 ASCII）。
    const std::wstring parameters = L"\"" + exePath.wstring() + L"\"";
    const HINSTANCE result =
        ShellExecuteW(owner, L"open", L"explorer.exe", parameters.c_str(), nullptr, SW_SHOWNORMAL);
    const INT_PTR code = reinterpret_cast<INT_PTR>(result);
    if (code <= 32) {
        // ShellExecuteW 约定：返回值 <= 32 为错误码。
        outcome.error = L"启动失败（explorer 转发返回码 " + std::to_wstring(code) + L"）";
        return outcome;
    }

    outcome.launched = true;
    return outcome;
}

}  // namespace faf
