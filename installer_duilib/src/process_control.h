#pragma once
//
// process_control.h - 精确关闭已安装的 FreeAssetFilter（计划 T3 / D9，冲突以 D15 为准）。
//
// 只按**完整映像路径**匹配 `<installDir>\FreeAssetFilter.exe`（大小写不敏感），
// 绝不按进程名模糊匹配：python.exe、FAF-Launcher.exe 以及其它目录下的同名 exe
// 都不会被触碰。
//
// 关闭流程（纯 Win32，不调用 taskkill/PowerShell，不创建子进程）：
//   1. CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS) 枚举进程；
//   2. OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE) +
//      QueryFullProcessImageNameW 取完整映像路径，与目标路径比较；
//   3. EnumWindows 对属于匹配 PID 的**可见顶层窗口** PostMessage(WM_CLOSE)；
//   4. 等待 gracefulTimeoutMs；仍存活则 OpenProcess(PROCESS_TERMINATE | SYNCHRONIZE)
//      + TerminateProcess，再等待 forceTimeoutMs；
//   5. 仍存活返回 error="app-close-timeout"（D9）。
//
// 本模块不创建 UI/线程/COM，可在任意工作线程中调用（T11/T12 在工作线程调用后通过
// WM_APP_CLOSE_DONE 把结果回投 UI）。所有内核句柄由 RAII 关闭，无全局可变状态，
// 因此并发调用也是安全的（各调用使用独立快照与句柄）。
//
#include <windows.h>

#include <string>

namespace faf {

// 一次关闭尝试的结果。
struct ProcessCloseResult {
    bool ok = false;        // 目标进程已全部退出（本来就没运行也视为成功）
    bool forced = false;    // 走过 TerminateProcess 强制路径
    std::wstring error;     // 失败原因；成功为空串；超时为 "app-close-timeout"
};

// 精确关闭 `<installDir>\FreeAssetFilter.exe` 的所有实例（同一路径多开也全部处理）。
//
// - installDir 可为相对路径/短路径：内部用 GetFullPathNameW + GetLongPathNameW 归一化，
//   再以 CompareStringOrdinal(..., TRUE) 做大小写不敏感比较。
// - 仅向匹配 PID 的可见顶层窗口发送 WM_CLOSE；无可见窗口的进程只能等待/强制结束。
// - 无匹配进程时立即返回 ok=true（幂等，可安全重复调用）。
// - 失败错误串：installDir 为空 -> "app-close-invalid-install-dir"；
//   进程快照失败 -> "app-close-snapshot-failed"；
//   强制等待后仍未退出 -> "app-close-timeout"。
ProcessCloseResult CloseInstalledApp(const std::wstring& installDir,
                                     DWORD gracefulTimeoutMs = 5000,
                                     DWORD forceTimeoutMs = 2000);

// 当前进程是否处于提升（管理员）令牌；查询失败返回 false。
//
// 计划 T2 的维护检测也可能需要同名能力（T2 允许“另放 process_control”）。两处实现
// 同时存在时由链接器择一（本定义在 MinGW 下为 weak），不会产生重复符号。
bool IsProcessElevated();

}  // namespace faf
