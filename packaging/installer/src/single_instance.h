#pragma once
//
// single_instance.h - 维护/安装/卸载 UI 的单实例互斥体与既有窗口激活（T4）。
//
// 契约（计划 T4、D2、D15 C2/H5）：
//   - SingleInstanceGuard：CreateMutexW(nullptr, FALSE, protocol::kMaintenanceMutex)
//     并检测 ERROR_ALREADY_EXISTS；RAII CloseHandle；不可复制/移动。
//   - ActivateExistingWindow()：轮询 FindWindowW 至多 timeoutMs，找到后
//     ShowWindow(SW_RESTORE) + SetForegroundWindow；失败静默返回 false。
//   - IsMutexHeld()：OpenMutexW(SYNCHRONIZE) + CloseHandle 探测命名对象是否存在，
//     不获取所有权、不修改任何状态（供 setup 侧检查）。
//
// 本模块不创建窗口，不写 maintenance-decision.ini / uninstall-request.ini /
// uninstall-result.ini，也不处理 setup mutex（SetupMutex 归 NSIS/T15）。
//
#include <windows.h>

#include "render/maintenance_protocol.h"

namespace spk {

// 维护 UI 互斥体的 RAII 守卫。构造即尝试创建/打开命名互斥体：
//   - 首次实例：Acquired() == true，持有句柄至析构；
//   - 已存在实例：AlreadyRunning() == true，Acquired() == false，立即关闭句柄；
//   - 其它失败：LastError() 给出 Win32 错误码，Acquired() == false。
class SingleInstanceGuard {
public:
    // 默认使用 protocol::kMaintenanceMutex；测试构建由协议头编译期切换为 `.Test`。
    explicit SingleInstanceGuard(
        const wchar_t* name = protocol::kMaintenanceMutex) noexcept;
    ~SingleInstanceGuard();

    SingleInstanceGuard(const SingleInstanceGuard&) = delete;
    SingleInstanceGuard& operator=(const SingleInstanceGuard&) = delete;
    SingleInstanceGuard(SingleInstanceGuard&&) = delete;
    SingleInstanceGuard& operator=(SingleInstanceGuard&&) = delete;

    // 本次进程是否成功成为唯一实例并持有互斥体。
    bool Acquired() const noexcept { return acquired_; }

    // CreateMutexW 是否报告 ERROR_ALREADY_EXISTS（已有同名互斥体）。
    bool AlreadyRunning() const noexcept { return alreadyRunning_; }

    // 最近一次 CreateMutexW 相关错误；成功持有为 ERROR_SUCCESS。
    DWORD LastError() const noexcept { return lastError_; }

    explicit operator bool() const noexcept { return acquired_; }

private:
    HANDLE mutex_ = nullptr;
    bool acquired_ = false;
    bool alreadyRunning_ = false;
    DWORD lastError_ = ERROR_SUCCESS;
};

// 等待类名为 `className` 的已有窗口出现（轮询），随后 ShowWindow(SW_RESTORE)
// 并 SetForegroundWindow。返回 true 表示窗口已在前台或置前成功；超时、参数
// 非法或置前失败返回 false。默认类名与 installer_window.cpp 的冻结类名一致。
bool ActivateExistingWindow(const wchar_t* className = L"SopeekInstaller",
                            DWORD timeoutMs = 5000);

// 判断命名互斥体当前是否存在：OpenMutexW(SYNCHRONIZE) 成功即存在，随后
// CloseHandle；ERROR_ACCESS_DENIED 视为存在（对象在但当前 token 无权打开）。
bool IsMutexHeld(const wchar_t* name);

}  // namespace spk
