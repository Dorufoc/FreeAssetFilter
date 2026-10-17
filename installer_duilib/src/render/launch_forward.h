#pragma once
//
// launch_forward.h - 完成后启动的去提权转发（Frozen contract §15，唯一 owner = Todo 15）。
//
// 安装器 GUI 是提权 NSIS 进程 `Exec` 出来的子进程（继承管理员令牌），因此**禁止**
// 直接 `ShellExecuteW(exe)` —— 子进程会继承管理员令牌。§15 的唯一允许实现：
//
//   `ShellExecuteW(L"open", L"explorer.exe", L"\"<installDir>\\FreeAssetFilter.exe\"",
//                  nullptr, nullptr, SW_SHOWNORMAL)`
//
// 即经 `explorer.exe` 转发 `open`：请求被交给已运行的桌面 shell（标准用户令牌），
// 由 shell 启动目标进程，从而脱离管理员令牌继承。
//
// 本模块无窗口/COM 依赖，可在无 GUI 的 harness 中直接驱动做令牌断言。
//
#include <windows.h>

#include <string>

namespace faf {

// 一次启动尝试的结果（供 GUI 提示与 harness 断言）。
struct LaunchOutcome {
    bool launched = false;    // explorer 转发已发出（ShellExecuteW 返回 > 32）
    bool missingExe = false;  // `<installDir>\FreeAssetFilter.exe` 不存在（不崩溃，仅提示）
    std::wstring error;       // 人类可读失败原因；成功时为空串
};

// §15 去提权启动。**调用方（InstallerWindow::OnFinishIntent）必须先确认
// `AppState.optLaunch` 为真**——本函数自身不读取选项（守卫在调用点，防止误启动）。
// owner 可为 null（无所有者窗口）。绝不直接 ShellExecuteW(目标 exe)。
LaunchOutcome LaunchInstalledAppDeElevated(const std::wstring& installDir, HWND owner);

}  // namespace faf
