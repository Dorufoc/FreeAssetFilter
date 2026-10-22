//
// process_control.cpp - T3 精确关闭已安装应用（契约见 process_control.h / D9）。
//
// 关键约束（不得回退）：
//   - 只杀完整路径等于 `<installDir>\FreeAssetFilter.exe` 的进程；
//   - 优雅阶段只 PostMessage(WM_CLOSE)，不在此阶段调用 TerminateProcess；
//   - 超时才进入强制阶段，最终仍失败必须返回 "app-close-timeout"；
//   - 不创建子进程（taskkill/PowerShell 都是禁止项）。
//
#include "process_control.h"

#include <tlhelp32.h>

#include <algorithm>
#include <climits>
#include <memory>
#include <string_view>
#include <utility>
#include <vector>

#include "render/maintenance_protocol.h"

namespace faf {
namespace {

// 内核句柄统一 RAII：快照/进程/令牌句柄离开作用域即关闭。
struct HandleCloser {
    void operator()(HANDLE handle) const noexcept {
        if (handle != nullptr && handle != INVALID_HANDLE_VALUE) {
            CloseHandle(handle);
        }
    }
};

using UniqueHandle = std::unique_ptr<void, HandleCloser>;

// 大小写不敏感的序号比较（与区域设置无关，避免 Turkish-I 等陷阱）。
bool EqualsIgnoreCase(std::wstring_view lhs, std::wstring_view rhs) {
    if (lhs.size() > static_cast<size_t>(INT_MAX) || rhs.size() > static_cast<size_t>(INT_MAX)) {
        return false;
    }
    const wchar_t* lhsData = lhs.empty() ? L"" : lhs.data();
    const wchar_t* rhsData = rhs.empty() ? L"" : rhs.data();
    return CompareStringOrdinal(lhsData, static_cast<int>(lhs.size()), rhsData,
                                static_cast<int>(rhs.size()), TRUE) == CSTR_EQUAL;
}

// 去掉 `\\?\` / `\\?\UNC\` 扩展前缀，使 QueryFullProcessImageNameW 的输出能与普通
// Win32 路径比较。
std::wstring StripExtendedPrefix(std::wstring path) {
    if (path.size() >= 8 && EqualsIgnoreCase(std::wstring_view(path).substr(0, 8), L"\\\\?\\UNC\\")) {
        path = L"\\\\" + path.substr(8);
    } else if (path.size() >= 4 &&
               EqualsIgnoreCase(std::wstring_view(path).substr(0, 4), L"\\\\?\\")) {
        path.erase(0, 4);
    }
    return path;
}

// GetFullPathNameW 的 std::wstring 包装：解析相对路径、`.`/`..` 与正斜杠。
std::wstring AbsolutePath(const std::wstring& path) {
    if (path.empty()) return {};
    const DWORD required = GetFullPathNameW(path.c_str(), 0, nullptr, nullptr);
    if (required == 0) return path;

    std::wstring buffer(required, L'\0');
    const DWORD written = GetFullPathNameW(path.c_str(), required, buffer.data(), nullptr);
    if (written == 0) return path;
    buffer.resize(std::min<size_t>(written, buffer.size()));
    return buffer;
}

// 尽量把 8.3 短路径展开为长路径；文件不存在/失败时原样返回。
std::wstring LongPath(const std::wstring& absolute) {
    const DWORD required = GetLongPathNameW(absolute.c_str(), nullptr, 0);
    if (required == 0) return absolute;

    std::wstring buffer(required, L'\0');
    const DWORD written = GetLongPathNameW(absolute.c_str(), buffer.data(), required);
    if (written == 0 || written >= required) return absolute;
    buffer.resize(written);
    return buffer;
}

// 用于比较的规范化路径：绝对路径 -> 长路径 -> 去扩展前缀 -> 去尾部分隔符。
std::wstring NormalizePath(const std::wstring& path) {
    std::wstring normalized = StripExtendedPrefix(LongPath(AbsolutePath(path)));
    // 保留 `C:\` 这类根路径；其余路径的尾部分隔符不影响映像路径比较。
    while (normalized.size() > 3 &&
           (normalized.back() == L'\\' || normalized.back() == L'/')) {
        normalized.pop_back();
    }
    return normalized;
}

std::wstring BuildTargetImagePath(const std::wstring& installDir) {
    if (installDir.empty()) return {};
    std::wstring joined = installDir;
    if (joined.back() != L'\\' && joined.back() != L'/') {
        joined.push_back(L'\\');
    }
    joined += protocol::kAppExeName;
    return NormalizePath(joined);
}

// QueryFullProcessImageNameW：缓冲区不足时按 API 返回的所需长度重试一次。
std::wstring QueryImagePath(HANDLE process) {
    std::wstring buffer(MAX_PATH, L'\0');
    for (int attempt = 0; attempt < 2; ++attempt) {
        DWORD size = static_cast<DWORD>(buffer.size());
        if (QueryFullProcessImageNameW(process, 0, buffer.data(), &size)) {
            buffer.resize(std::min<size_t>(size, buffer.size()));
            return buffer;
        }
        if (GetLastError() != ERROR_INSUFFICIENT_BUFFER) return {};
        const size_t next = std::max<size_t>(static_cast<size_t>(size) + 1, buffer.size() * 2);
        buffer.resize(next);
    }
    return {};
}

// 在归一化前先按文件名快速排除，避免为系统里每个进程都做文件系统查询。
bool HasAppExeFileName(const std::wstring& imagePath) {
    const size_t separator = imagePath.find_last_of(L"\\/");
    const std::wstring_view name =
        separator == std::wstring::npos ? std::wstring_view(imagePath)
                                        : std::wstring_view(imagePath).substr(separator + 1);
    return EqualsIgnoreCase(name, protocol::kAppExeName);
}

struct CloseWindowContext {
    DWORD pid = 0;
};

// EnumWindows 只枚举顶层窗口；只对匹配 PID 的可见顶层窗口发 WM_CLOSE。
BOOL CALLBACK PostCloseToProcessWindow(HWND window, LPARAM contextParam) {
    auto* context = reinterpret_cast<CloseWindowContext*>(contextParam);

    DWORD windowPid = 0;
    GetWindowThreadProcessId(window, &windowPid);
    if (windowPid != context->pid) return TRUE;
    if (!IsWindowVisible(window)) return TRUE;

    // 失败（窗口已销毁/无权限）不阻塞其它窗口；最终以进程句柄是否 signaled 为准。
    PostMessageW(window, WM_CLOSE, 0, 0);
    return TRUE;
}

// 在共享截止时间内等待全部进程句柄（单批上限 MAXIMUM_WAIT_OBJECTS）。
bool WaitForAllProcesses(const std::vector<HANDLE>& handles, DWORD timeoutMs) {
    const ULONGLONG deadline = GetTickCount64() + static_cast<ULONGLONG>(timeoutMs);
    size_t offset = 0;
    while (offset < handles.size()) {
        const size_t remainingCount = handles.size() - offset;
        const DWORD batch = static_cast<DWORD>(
            std::min<size_t>(remainingCount, static_cast<size_t>(MAXIMUM_WAIT_OBJECTS)));

        const ULONGLONG now = GetTickCount64();
        const DWORD waitMs = now < deadline ? static_cast<DWORD>(deadline - now) : 0;
        const DWORD waited =
            WaitForMultipleObjects(batch, handles.data() + offset, TRUE, waitMs);
        if (waited == WAIT_OBJECT_0) {
            offset += batch;
            continue;
        }
        if (waited == WAIT_FAILED) return false;

        // WAIT_TIMEOUT：截止时间已到。再做一次零等待确认，避免刚好在边界退出的进程
        // 被误判为超时。
        if (WaitForMultipleObjects(batch, handles.data() + offset, TRUE, 0) == WAIT_OBJECT_0) {
            offset += batch;
            continue;
        }
        return false;
    }
    return true;
}

}  // namespace

ProcessCloseResult CloseInstalledApp(const std::wstring& installDir,
                                     DWORD gracefulTimeoutMs,
                                     DWORD forceTimeoutMs) {
    ProcessCloseResult result;
    if (installDir.empty()) {
        result.error = L"app-close-invalid-install-dir";
        return result;
    }

    const std::wstring targetPath = BuildTargetImagePath(installDir);
    if (targetPath.empty()) {
        result.error = L"app-close-invalid-install-dir";
        return result;
    }

    const HANDLE rawSnapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (rawSnapshot == INVALID_HANDLE_VALUE) {
        result.error = L"app-close-snapshot-failed";
        return result;
    }
    UniqueHandle snapshot(rawSnapshot);

    PROCESSENTRY32W entry{};
    entry.dwSize = sizeof(entry);
    if (!Process32FirstW(snapshot.get(), &entry)) {
        if (GetLastError() == ERROR_NO_MORE_FILES) {
            result.ok = true;
            return result;
        }
        result.error = L"app-close-snapshot-failed";
        return result;
    }

    const DWORD selfPid = GetCurrentProcessId();
    std::vector<DWORD> matchedPids;
    std::vector<UniqueHandle> processHandles;
    std::vector<HANDLE> waitHandles;

    do {
        const DWORD pid = entry.th32ProcessID;
        if (pid == 0 || pid == selfPid) continue;

        const HANDLE rawProcess =
            OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, FALSE, pid);
        if (rawProcess == nullptr) continue;  // 无法查询（保护进程/权限不足）→ 跳过
        UniqueHandle process(rawProcess);

        const std::wstring imagePath = QueryImagePath(process.get());
        if (imagePath.empty() || !HasAppExeFileName(imagePath)) continue;

        // 完整映像路径比较：杜绝“同名不同目录”的误杀。
        const std::wstring normalizedImage = NormalizePath(imagePath);
        if (!EqualsIgnoreCase(normalizedImage, targetPath)) continue;

        matchedPids.push_back(pid);
        waitHandles.push_back(process.get());  // 句柄由 processHandles 持有到函数结束
        processHandles.push_back(std::move(process));
    } while (Process32NextW(snapshot.get(), &entry));

    if (matchedPids.empty()) {
        result.ok = true;  // 幂等：本来就没运行
        return result;
    }

    // 优雅阶段：只发 WM_CLOSE，给应用保存状态/释放文件锁的机会。
    for (const DWORD pid : matchedPids) {
        CloseWindowContext context;
        context.pid = pid;
        EnumWindows(PostCloseToProcessWindow, reinterpret_cast<LPARAM>(&context));
    }

    if (WaitForAllProcesses(waitHandles, gracefulTimeoutMs)) {
        result.ok = true;
        return result;
    }

    // 强制阶段：优雅超时后 TerminateProcess，再等 forceTimeoutMs（D9）。
    result.forced = true;
    for (const DWORD pid : matchedPids) {
        const HANDLE rawTerminate = OpenProcess(PROCESS_TERMINATE | SYNCHRONIZE, FALSE, pid);
        if (rawTerminate == nullptr) continue;
        UniqueHandle terminate(rawTerminate);
        // 返回值不单独判定：进程可能恰好在 OpenProcess 与 TerminateProcess 之间退出，
        // 最终一律以原 SYNCHRONIZE 句柄是否 signaled 为准。
        TerminateProcess(terminate.get(), 1);
    }

    if (WaitForAllProcesses(waitHandles, forceTimeoutMs)) {
        result.ok = true;
        return result;
    }

    result.error = L"app-close-timeout";
    return result;
}

// 计划 T2 也允许提供同名提权检测（见头文件说明）：MinGW 下标记 weak，两处实现同时
// 存在时由链接器择一，避免并行批次合入后出现重复符号。逻辑两者等价。
#if defined(__GNUC__)
__attribute__((weak))
#endif
bool IsProcessElevated() {
    HANDLE rawToken = nullptr;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &rawToken)) {
        return false;
    }
    UniqueHandle token(rawToken);

    TOKEN_ELEVATION elevation{};
    DWORD returnedSize = 0;
    if (!GetTokenInformation(token.get(), TokenElevation, &elevation, sizeof(elevation),
                             &returnedSize)) {
        return false;
    }
    return elevation.TokenIsElevated != 0;
}

}  // namespace faf
