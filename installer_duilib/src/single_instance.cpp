//
// single_instance.cpp - 维护/安装/卸载 UI 的单实例互斥体与既有窗口激活（T4）。
//
// 实现约束：纯 Win32 / C++17，无第三方依赖；不创建窗口，不写任何 INI/注册表。
//
#include "single_instance.h"

namespace faf {
namespace {

// FindWindowW 轮询间隔；与协议约定的跨进程轮询量级一致（D3/M4/H5）。
constexpr DWORD kActivationPollMs = 50;

bool ValidName(const wchar_t* name) noexcept {
    return name != nullptr && name[0] != L'\0';
}

}  // namespace

SingleInstanceGuard::SingleInstanceGuard(const wchar_t* name) noexcept {
    if (!ValidName(name)) {
        lastError_ = ERROR_INVALID_PARAMETER;
        return;
    }

    // 清除调用线程的陈旧错误码；新对象创建成功时 GetLastError 即保持 0。
    SetLastError(ERROR_SUCCESS);
    mutex_ = CreateMutexW(nullptr, FALSE, name);
    if (mutex_ == nullptr) {
        lastError_ = GetLastError();
        return;
    }

    const DWORD createError = GetLastError();
    if (createError == ERROR_ALREADY_EXISTS) {
        // 已有实例：不持有额外句柄，让第一实例继续承担责任。
        alreadyRunning_ = true;
        lastError_ = ERROR_ALREADY_EXISTS;
        CloseHandle(mutex_);
        mutex_ = nullptr;
        return;
    }

    acquired_ = true;
    lastError_ = ERROR_SUCCESS;
}

SingleInstanceGuard::~SingleInstanceGuard() {
    if (mutex_ != nullptr) {
        CloseHandle(mutex_);
        mutex_ = nullptr;
    }
    acquired_ = false;
}

bool ActivateExistingWindow(const wchar_t* className, DWORD timeoutMs) {
    if (!ValidName(className)) return false;

    const ULONGLONG start = GetTickCount64();
    HWND window = nullptr;
    for (;;) {
        window = FindWindowW(className, nullptr);
        if (window != nullptr) break;

        const ULONGLONG elapsed = GetTickCount64() - start;
        if (elapsed >= timeoutMs) return false;

        const ULONGLONG remaining = timeoutMs - elapsed;
        Sleep(remaining < kActivationPollMs ? static_cast<DWORD>(remaining)
                                            : kActivationPollMs);
    }

    ShowWindow(window, SW_RESTORE);
    if (SetForegroundWindow(window)) return true;

    // 前台锁可能拒绝跨进程置前：短暂附加到当前前台线程的输入队列后重试。
    const HWND foreground = GetForegroundWindow();
    const DWORD foregroundThread =
        foreground != nullptr ? GetWindowThreadProcessId(foreground, nullptr) : 0;
    const DWORD currentThread = GetCurrentThreadId();
    if (foregroundThread != 0 && foregroundThread != currentThread &&
        AttachThreadInput(currentThread, foregroundThread, TRUE)) {
        SetForegroundWindow(window);
        AttachThreadInput(currentThread, foregroundThread, FALSE);
    }
    return GetForegroundWindow() == window;
}

bool IsMutexHeld(const wchar_t* name) {
    if (!ValidName(name)) return false;

    HANDLE mutex = OpenMutexW(SYNCHRONIZE, FALSE, name);
    if (mutex == nullptr) {
        // 对象存在但当前 token 无访问权时，仍应视为“已被持有”。
        return GetLastError() == ERROR_ACCESS_DENIED;
    }

    CloseHandle(mutex);
    return true;
}

}  // namespace faf
