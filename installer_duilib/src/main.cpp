#include "installer_window.h"
#include "maintenance_detector.h"
#include "process_control.h"  // T14：IsProcessElevated（GetTokenInformation(TokenElevation)）
#include "single_instance.h"  // T13：单实例互斥体 + 既有窗口激活

#include <windows.h>
#include <knownfolders.h>     // FOLDERID_LocalAppData（/orig-localappdata 校验）
#include <sddl.h>             // ConvertSidToStringSidW（/orig-sid 校验）
#include <shellapi.h>         // ShellExecuteW（runas 重启动）
#include <shellscalingapi.h>  // SetProcessDpiAwareness（Win8.1+ 回退）
#include <shlobj.h>           // SHGetKnownFolderPath

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <cstdlib>  // _wtoi（/auto:page= 解析）
#include <filesystem>
#include <string>
#include <utility>
#include <vector>

namespace {

constexpr wchar_t kAutoOptsPrefix[] = L"/auto:opts=";
constexpr wchar_t kAutoPagePrefix[] = L"/auto:page=";
constexpr wchar_t kAutoModePrefix[] = L"/auto:mode=";
constexpr wchar_t kAutoActionPrefix[] = L"/auto:action=";
constexpr wchar_t kAutoDeleteUserDataPrefix[] = L"/auto:delete-user-data=";
constexpr wchar_t kTestDumpMaintenancePrefix[] = L"/test-dump-maintenance=";
// C4：安装模式的产品默认目录。维护/卸载绝不使用该默认值（见 ResolveInstallDir）。
constexpr wchar_t kDefaultInstallDir[] = L"C:\\Program Files\\FreeAssetFilter";
// M1：setup 维护/卸载时临时释放 GUI 的目录名前缀（%TEMP%\FreeAssetFilterMaintenance-<pid>）。
constexpr wchar_t kMaintenanceTempLeafPrefix[] = L"FreeAssetFilterMaintenance-";

template <std::size_t N>
constexpr std::size_t LiteralLength(const wchar_t (&)[N]) {
    return N - 1;
}

std::string WideToUtf8(const std::wstring& text) {
    if (text.empty()) return {};
    const int needed = WideCharToMultiByte(CP_UTF8, 0, text.data(), static_cast<int>(text.size()),
                                           nullptr, 0, nullptr, nullptr);
    if (needed <= 0) return {};
    std::string result(static_cast<std::size_t>(needed), '\0');
    WideCharToMultiByte(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), result.data(),
                        needed, nullptr, nullptr);
    return result;
}

// M1：环境变量门控的诊断落盘（与 installer_window.cpp 的 DiagLog 同格式：UTF-8 追加）。
// 未设置 FAF_DIAG_PATH 时完全 no-op，生产默认行为不受影响。
void DiagLog(const std::wstring& line) {
    wchar_t path[MAX_PATH] = {};
    const DWORD n = GetEnvironmentVariableW(L"FAF_DIAG_PATH", path, static_cast<DWORD>(ARRAYSIZE(path)));
    if (n == 0 || n >= ARRAYSIZE(path)) return;
    HANDLE file = CreateFileW(path, FILE_APPEND_DATA, FILE_SHARE_READ, nullptr, OPEN_ALWAYS,
                              FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return;
    const std::string utf8 = WideToUtf8(line) + "\r\n";
    DWORD written = 0;
    SetFilePointer(file, 0, nullptr, FILE_END);
    WriteFile(file, utf8.data(), static_cast<DWORD>(utf8.size()), &written, nullptr);
    CloseHandle(file);
}

// T14 解析结果。所有字段仅是命令行输入；真正的文件/注册表副作用只发生在
// InstallerWindow 内部（/test-dump-maintenance 是唯一显式诊断写入口）。
struct ParsedArgs {
    std::wstring payload;
    std::wstring resultPath;
    std::wstring installDir;
    std::wstring decisionPath;
    std::wstring helperPath;  // /helper <path>（NSIS helper → UI 参数，UI 自身不消费）
    std::wstring uiPath;      // /ui <path>（同上）
    std::wstring origSid;
    std::wstring origLocalAppData;
    DWORD helperPid = 0;
    DWORD setupPid = 0;
    std::uint64_t payloadTimeoutMs = 0;
    bool maintenance = false;
    bool uninstall = false;
    bool elevated = false;
    bool uninstallLauncher = false;  // NSIS helper 标志（本 UI 不映射为 GUI 模式）
    bool uninstallHelper = false;    // NSIS helper 标志（同上）
    bool silent = false;             // /S（NSIS helper 静默卸载；本 UI 只解析）
    bool autoDrive = false;
    std::wstring autoProfile;
    int autoStopPage = -1;
    AppMode autoMode = AppMode::Install;
    std::wstring autoAction;
    std::wstring autoDeleteUserData;
#ifdef FAF_TESTMODE
    std::wstring testDumpPath;
#endif
};

// Windows 命令行参数引用规则：仅含空白/引号时需要包裹；反斜杠只在引号前翻倍。
std::wstring QuoteArgument(const std::wstring& arg) {
    const bool needsQuotes = arg.empty() || arg.find_first_of(L" \t\"") != std::wstring::npos;
    if (!needsQuotes) return arg;

    std::wstring quoted;
    quoted.reserve(arg.size() + 2);
    quoted.push_back(L'"');
    std::size_t backslashes = 0;
    for (const wchar_t ch : arg) {
        if (ch == L'\\') {
            ++backslashes;
            continue;
        }
        if (ch == L'"') {
            quoted.append(backslashes * 2 + 1, L'\\');
            quoted.push_back(L'"');
        } else {
            quoted.append(backslashes, L'\\');
            quoted.push_back(ch);
        }
        backslashes = 0;
    }
    quoted.append(backslashes * 2, L'\\');
    quoted.push_back(L'"');
    return quoted;
}

// 还原原始参数（不含 exe 路径）。提权重启动时直接附加 `/elevated ...`，
// 保证 setup/helper 传入的 /installdir、/decision 等参数原样保留。
std::wstring BuildOriginalArguments(int argc, wchar_t** argv) {
    std::wstring result;
    for (int i = 1; i < argc; ++i) {
        if (!result.empty()) result.push_back(L' ');
        result += QuoteArgument(argv[i] ? argv[i] : L"");
    }
    return result;
}

// 非负十进制 DWORD；空/前缀负号/尾随垃圾/溢出一律返回 0（调用方按缺省处理）。
DWORD ParseDword(const wchar_t* text) {
    if (!text || !*text || *text == L'-') return 0;
    wchar_t* end = nullptr;
    const unsigned long long value = std::wcstoull(text, &end, 10);
    if (end == text || (end && *end != L'\0') || value > 0xFFFFFFFFull) return 0;
    return static_cast<DWORD>(value);
}

// 非负十进制 uint64；语义同 ParseDword（/payload-timeout 的 0 = 引擎默认）。
std::uint64_t ParseNonNegativeU64(const wchar_t* text) {
    if (!text || !*text || *text == L'-') return 0;
    wchar_t* end = nullptr;
    const unsigned long long value = std::wcstoull(text, &end, 10);
    if (end == text || (end && *end != L'\0')) return 0;
    return static_cast<std::uint64_t>(value);
}

ParsedArgs ParseArguments(int argc, wchar_t** argv) {
    ParsedArgs args;
    const auto valueAt = [argc, argv](int index) -> const wchar_t* {
        return (index + 1 < argc) ? argv[index + 1] : nullptr;
    };

    for (int i = 1; i < argc; ++i) {
        const wchar_t* arg = argv[i];
        if (!arg) continue;

        if (_wcsicmp(arg, L"/maintenance") == 0) {
            args.maintenance = true;
        } else if (_wcsicmp(arg, L"/uninstall") == 0) {
            args.uninstall = true;
        } else if (_wcsicmp(arg, L"/uninstall-launcher") == 0) {
            args.uninstallLauncher = true;
        } else if (_wcsicmp(arg, L"/uninstall-helper") == 0) {
            args.uninstallHelper = true;
#if defined(FAF_TESTMODE)
        } else if (_wcsnicmp(arg, kTestDumpMaintenancePrefix,
                             LiteralLength(kTestDumpMaintenancePrefix)) == 0) {
            args.testDumpPath = arg + LiteralLength(kTestDumpMaintenancePrefix);
#endif
        } else if (_wcsicmp(arg, L"/elevated") == 0) {
            args.elevated = true;
        } else if (_wcsicmp(arg, L"/S") == 0) {
            args.silent = true;
        } else if (_wcsicmp(arg, L"/payload") == 0) {
            if (const wchar_t* value = valueAt(i)) {
                args.payload = value;
                ++i;
            }
        } else if (_wcsicmp(arg, L"/result") == 0) {
            if (const wchar_t* value = valueAt(i)) {
                args.resultPath = value;
                ++i;
            }
        } else if (_wcsicmp(arg, L"/installdir") == 0) {
            if (const wchar_t* value = valueAt(i)) {
                args.installDir = value;
                ++i;
            }
        } else if (_wcsicmp(arg, L"/decision") == 0) {
            if (const wchar_t* value = valueAt(i)) {
                args.decisionPath = value;
                ++i;
            }
        } else if (_wcsicmp(arg, L"/helper") == 0) {
            if (const wchar_t* value = valueAt(i)) {
                args.helperPath = value;
                ++i;
            }
        } else if (_wcsicmp(arg, L"/helper-pid") == 0) {
            if (const wchar_t* value = valueAt(i)) {
                args.helperPid = ParseDword(value);
                ++i;
            }
        } else if (_wcsicmp(arg, L"/ui") == 0) {
            if (const wchar_t* value = valueAt(i)) {
                args.uiPath = value;
                ++i;
            }
        } else if (_wcsicmp(arg, L"/orig-sid") == 0) {
            if (const wchar_t* value = valueAt(i)) {
                args.origSid = value;
                ++i;
            }
        } else if (_wcsicmp(arg, L"/orig-localappdata") == 0) {
            if (const wchar_t* value = valueAt(i)) {
                args.origLocalAppData = value;
                ++i;
            }
        } else if (_wcsicmp(arg, L"/setup-pid") == 0) {
            if (const wchar_t* value = valueAt(i)) {
                args.setupPid = ParseDword(value);
                ++i;
            }
        } else if (_wcsicmp(arg, L"/payload-timeout") == 0) {
            if (const wchar_t* value = valueAt(i)) {
                args.payloadTimeoutMs = ParseNonNegativeU64(value);
                ++i;
            }
        } else if (_wcsicmp(arg, L"/auto") == 0) {
            args.autoDrive = true;
        } else if (_wcsnicmp(arg, kAutoOptsPrefix, LiteralLength(kAutoOptsPrefix)) == 0) {
            args.autoDrive = true;
            args.autoProfile = arg + LiteralLength(kAutoOptsPrefix);
        } else if (_wcsnicmp(arg, kAutoPagePrefix, LiteralLength(kAutoPagePrefix)) == 0) {
            args.autoDrive = true;
            args.autoStopPage = _wtoi(arg + LiteralLength(kAutoPagePrefix));
        } else if (_wcsnicmp(arg, kAutoModePrefix, LiteralLength(kAutoModePrefix)) == 0) {
            args.autoDrive = true;
            const wchar_t* value = arg + LiteralLength(kAutoModePrefix);
            if (_wcsicmp(value, L"maintenance") == 0) {
                args.autoMode = AppMode::Maintenance;
            } else if (_wcsicmp(value, L"uninstall") == 0) {
                args.autoMode = AppMode::Uninstall;
            } else {
                args.autoMode = AppMode::Install;
            }
        } else if (_wcsnicmp(arg, kAutoActionPrefix, LiteralLength(kAutoActionPrefix)) == 0) {
            args.autoDrive = true;
            args.autoAction = arg + LiteralLength(kAutoActionPrefix);
        } else if (_wcsnicmp(arg, kAutoDeleteUserDataPrefix,
                             LiteralLength(kAutoDeleteUserDataPrefix)) == 0) {
            args.autoDrive = true;
            args.autoDeleteUserData = arg + LiteralLength(kAutoDeleteUserDataPrefix);
        }
    }
    return args;
}

AppMode SelectMode(const ParsedArgs& args) {
    if (args.maintenance) return AppMode::Maintenance;
    if (args.uninstall) return AppMode::Uninstall;
    return AppMode::Install;
}

std::wstring SelfExePath() {
    std::wstring buffer(MAX_PATH, L'\0');
    for (;;) {
        const DWORD written =
            GetModuleFileNameW(nullptr, buffer.data(), static_cast<DWORD>(buffer.size()));
        if (written == 0) return {};
        if (written < buffer.size()) {
            buffer.resize(written);
            return buffer;
        }
        buffer.resize(buffer.size() * 2);
    }
}

// 当前进程 token 的 user SID（字符串形式）。失败返回空串。
std::wstring CurrentUserSid() {
    HANDLE token = nullptr;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token)) return {};

    DWORD needed = 0;
    GetTokenInformation(token, TokenUser, nullptr, 0, &needed);
    if (needed == 0) {
        CloseHandle(token);
        return {};
    }

    std::vector<BYTE> buffer(needed);
    const BOOL ok = GetTokenInformation(token, TokenUser, buffer.data(), needed, &needed);
    CloseHandle(token);
    if (!ok) return {};

    auto* user = reinterpret_cast<TOKEN_USER*>(buffer.data());
    LPWSTR sidText = nullptr;
    if (!ConvertSidToStringSidW(user->User.Sid, &sidText) || !sidText) return {};

    std::wstring result(sidText);
    LocalFree(sidText);
    return result;
}

// %LOCALAPPDATA%（FOLDERID_LocalAppData）。失败返回空串。
std::wstring CurrentLocalAppData() {
    PWSTR raw = nullptr;
    if (FAILED(SHGetKnownFolderPath(FOLDERID_LocalAppData, KF_FLAG_DEFAULT, nullptr, &raw)) ||
        !raw) {
        return {};
    }
    std::wstring result(raw);
    CoTaskMemFree(raw);
    return result;
}

std::wstring NormalizeDirectoryForCompare(std::wstring value) {
    std::replace(value.begin(), value.end(), L'/', L'\\');
    while (value.size() > 1 && value.back() == L'\\') value.pop_back();
    return value;
}

bool EqualsIgnoreCase(const std::wstring& lhs, const std::wstring& rhs) {
    return CompareStringOrdinal(lhs.c_str(), -1, rhs.c_str(), -1, TRUE) == CSTR_EQUAL;
}

// C4：安装目录是否包含已安装产品的判定信号（与 maintenance_detector 一致：
// FreeAssetFilter.exe 或 _internal 任一存在即可）。
bool HasInstalledPayload(const std::wstring& directory) {
    if (directory.empty()) return false;
    std::error_code ec;
    const std::filesystem::path base(directory);
    return std::filesystem::exists(base / L"FreeAssetFilter.exe", ec) ||
           std::filesystem::exists(base / L"_internal", ec);
}

// C4：在进入任何诊断、身份校验或窗口创建之前解析出非空且与模式匹配的安装目录。
//   - Install：空 /installdir 仍沿用既有产品默认目录；
//   - Uninstall/Maintenance：只接受显式 /installdir，或当前 exe 的父目录（且必须
//     含 FreeAssetFilter.exe / _internal）。绝不回退 Program Files。
// 返回 false 时 errorDetail 为可见错误页文案（调用方走 ShowStartupError）。
bool ResolveInstallDir(ParsedArgs* args, AppMode mode, std::wstring* errorDetail) {
    if (!args) return false;
    if (!args->installDir.empty()) return true;
    if (mode == AppMode::Install) {
        args->installDir = kDefaultInstallDir;
        return true;
    }

    const std::wstring selfExe = SelfExePath();
    if (selfExe.empty()) {
        if (errorDetail) {
            *errorDetail = L"无法定位卸载程序自身，无法确定安装目录。操作已取消。";
        }
        return false;
    }

    const std::filesystem::path parent = std::filesystem::path(selfExe).parent_path();
    if (parent.empty() || !HasInstalledPayload(parent.wstring())) {
        if (errorDetail) {
            *errorDetail = L"未提供 /installdir，且当前程序所在目录“" + parent.wstring() +
                           L"”未检测到 FreeAssetFilter 程序文件。操作已取消。";
        }
        return false;
    }
    args->installDir = parent.wstring();
    return true;
}

// M1：读取 %TEMP%（动态长度，避免 MAX_PATH 截断）。
std::wstring TempDirectoryPath() {
    const DWORD needed = GetEnvironmentVariableW(L"TEMP", nullptr, 0);
    if (needed == 0) return {};
    std::wstring buffer(needed, L'\0');
    const DWORD written = GetEnvironmentVariableW(L"TEMP", buffer.data(), needed);
    if (written == 0 || written >= needed) return {};
    buffer.resize(written);
    return buffer;
}

// 比较用路径：先尽量规范化（长路径/大小写由 EqualsIgnoreCase 处理），再统一分隔符。
std::wstring CanonicalPathForCompare(const std::wstring& value) {
    if (value.empty()) return {};
    std::error_code ec;
    const std::filesystem::path canonical = std::filesystem::weakly_canonical(value, ec);
    return NormalizeDirectoryForCompare(ec ? value : canonical.wstring());
}

// M1：当前 exe 是否恰好位于 `%TEMP%\FreeAssetFilterMaintenance-<十进制数字>\`。
// 目录名不匹配（含多余字符、绝对路径不同、%TEMP% 本身）一律返回 false，
// 保证清理守卫永远不会删除无关路径。
bool MatchMaintenanceTempDirectory(const std::wstring& executablePath,
                                   std::wstring* directory) {
    if (executablePath.empty()) return false;
    const std::filesystem::path parent = std::filesystem::path(executablePath).parent_path();
    if (parent.empty()) return false;

    const std::wstring leaf = parent.filename().wstring();
    const std::size_t prefixLength = LiteralLength(kMaintenanceTempLeafPrefix);
    if (leaf.size() <= prefixLength ||
        _wcsnicmp(leaf.c_str(), kMaintenanceTempLeafPrefix, prefixLength) != 0) {
        return false;
    }
    for (std::size_t i = prefixLength; i < leaf.size(); ++i) {
        if (leaf[i] < L'0' || leaf[i] > L'9') return false;
    }

    // exe 的父目录才是维护临时目录；必须再上一级恰好等于 %TEMP%，否则
    // `%TEMP%\sub\FreeAssetFilterMaintenance-<digits>` 这类无关路径也会被误删。
    const std::filesystem::path container = parent.parent_path();
    if (container.empty()) return false;

    const std::wstring containerPath = CanonicalPathForCompare(container.wstring());
    const std::wstring tempRaw = TempDirectoryPath();
    const std::wstring tempPath = CanonicalPathForCompare(tempRaw);
    if (containerPath.empty() || tempPath.empty() || !EqualsIgnoreCase(containerPath, tempPath)) {
        DiagLog(L"maintenance temp match failed container=" + containerPath + L" temp=" + tempPath +
                L" tempRaw=" + tempRaw + L" leaf=" + leaf);
        return false;
    }
    if (directory) *directory = parent.wstring();
    return true;
}

// M1：维护/卸载 GUI 的临时目录清理守卫。
//
// 为什么必须延迟删除：GUI 的 exe 与 libwinpthread-1.dll 在进程存活期间被 Windows
// 锁定，无法删除。这里在正常退出流程末尾启动一个分离的隐藏 cmd，短暂延时后
// `rmdir /s /q` 精确删除已校验的临时目录；不阻塞 UI、不使用 system()、失败静默。
// 只有当前进程确实成为唯一 UI 实例后才 Arm()，重复实例/提权父进程绝不会删除
// 第一个 GUI 正在使用的目录。
class MaintenanceTempCleanupGuard {
public:
    MaintenanceTempCleanupGuard() = default;
    ~MaintenanceTempCleanupGuard() { ScheduleDelete(); }

    MaintenanceTempCleanupGuard(const MaintenanceTempCleanupGuard&) = delete;
    MaintenanceTempCleanupGuard& operator=(const MaintenanceTempCleanupGuard&) = delete;

    // 仅当 exe 位于精确的维护临时目录时武装；否则保持禁用。
    void Arm(const std::wstring& executablePath) {
        tempDirectory_.clear();
        std::wstring directory;
        if (!MatchMaintenanceTempDirectory(executablePath, &directory)) {
            DiagLog(L"maintenance temp cleanup not armed exe=" + executablePath);
            return;
        }
        tempDirectory_ = std::move(directory);
        DiagLog(L"maintenance temp cleanup armed dir=" + tempDirectory_);
    }

private:
    void ScheduleDelete() const {
        if (tempDirectory_.empty()) {
            DiagLog(L"maintenance temp cleanup inactive (guard not armed)");
            return;
        }

        wchar_t systemDirectory[MAX_PATH] = {};
        const UINT length = GetSystemDirectoryW(systemDirectory, ARRAYSIZE(systemDirectory));
        if (length == 0 || length >= ARRAYSIZE(systemDirectory)) {
            DiagLog(L"maintenance temp cleanup skipped: GetSystemDirectoryW failed");
            return;
        }
        std::wstring cmdPath(systemDirectory);
        cmdPath += L"\\cmd.exe";

        // cmd /d 跳过 AutoRun。exe/DLL 在进程存活期间被锁定，因此不能在析构点
        // 一次性 rmdir；这里用 ~1s（ping -n 2）间隔重试最多 10 次，覆盖进程退出
        // 释放锁的瞬间，同时把总时长控制在 QA 的 15s 观察窗内。路径已在 Arm()
        // 中精确校验，rmdir 只作用于该目录。timeout 在无控制台时不可靠，故仍用 ping。
        constexpr int kDeleteAttempts = 10;
        std::wstring commandLine = L"\"" + cmdPath + L"\" /d /c for /l %i in (1,1,";
        commandLine += std::to_wstring(kDeleteAttempts);
        commandLine += L") do @(rmdir /s /q \"";
        commandLine += tempDirectory_;
        commandLine += L"\" 2>nul & if not exist \"";
        commandLine += tempDirectory_;
        commandLine += L"\" exit /b 0 & ping -n 2 127.0.0.1 >nul)";

        // 关键修复：绝不让子进程继承已消失的当前目录。NSIS `Exec` 继承 `$OUTDIR`
        // （本流程为 `$PLUGINSDIR`），setup 在维护取消后立即 Abort 并删除该目录；
        // 若用 nullptr 作为 lpCurrentDirectory，CreateProcessW 会以 ERROR_DIRECTORY
        // 失败，删除永远不会发生（历史遗留的 %TEMP% 目录即由此产生）。
        STARTUPINFOW startup{};
        startup.cb = sizeof(startup);
        PROCESS_INFORMATION process{};
        const BOOL created =
            CreateProcessW(cmdPath.c_str(), commandLine.data(), nullptr, nullptr, FALSE,
                           CREATE_NO_WINDOW, nullptr, systemDirectory, &startup, &process);
        if (!created) {
            DiagLog(L"maintenance temp cleanup CreateProcessW failed err=" +
                    std::to_wstring(GetLastError()));
            return;
        }
        DiagLog(L"maintenance temp cleanup spawned pid=" +
                std::to_wstring(process.dwProcessId));
        CloseHandle(process.hThread);
        CloseHandle(process.hProcess);
    }

    std::wstring tempDirectory_;
};

// D12/H2：提权前/后都必须确认 token 用户与 helper 记录的交互用户一致。不一致
// 时拒绝跨用户操作；返回 true 时 detail 为可展示给用户的原因。
bool IdentityMismatch(const ParsedArgs& args, const std::wstring& currentSid,
                      const std::wstring& currentLocalAppData, std::wstring* detail) {
    if (!args.origSid.empty() && !EqualsIgnoreCase(args.origSid, currentSid)) {
        if (detail) {
            *detail = L"当前进程的用户身份与启动卸载的交互用户不一致。"
                      L"请使用当前用户的管理员权限运行卸载程序。";
        }
        return true;
    }
    if (!args.origLocalAppData.empty() &&
        !EqualsIgnoreCase(NormalizeDirectoryForCompare(args.origLocalAppData),
                          NormalizeDirectoryForCompare(currentLocalAppData))) {
        if (detail) {
            *detail = L"当前进程的 %LOCALAPPDATA% 与启动卸载的交互用户不一致。"
                      L"请使用当前用户的管理员权限运行卸载程序。";
        }
        return true;
    }
    return false;
}

// 错误页（D12/D15）：helper 非管理员 / 原用户身份不一致时必须显示可见错误页，
// 不能弹 MessageBox，也不能写任何协议 INI 或注册表。窗口的 startup-error 分支
// 会在进入维护/卸载流程之前完成显示，关闭时直接销毁（不写 decision/result）。
int ShowStartupError(HINSTANCE instance, const std::wstring& title, const std::wstring& body,
                     AppMode mode, const ParsedArgs& args) {
    InstallerWindow window(instance, args.payload, args.resultPath, args.installDir, mode);
    window.SetStartupError(title, body);
    return window.Run();
}

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

    // T14/D15 H2：**先解析、后提权、最后才建互斥体/窗口**。未提权的父进程在
    // ShellExecuteW(runas) 之后立即退出，绝不能在启动提权子进程前持有
    // SingleInstanceGuard（否则子进程会看到 mutex 已存在并直接激活/退出）。
    int argc = 0;
    LPWSTR* argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    ParsedArgs args = ParseArguments(argc, argv);
#ifdef FAF_TESTMODE
    if (argv) LocalFree(argv);
    argv = nullptr;
#else
    const std::wstring originalArguments = BuildOriginalArguments(argc, argv);
    if (argv) LocalFree(argv);
    argv = nullptr;
#endif

    const AppMode mode = SelectMode(args);

    // C4：先保证 installDir 非空且与模式匹配，再进入 /test-dump-maintenance、身份
    // 校验或窗口创建。维护/卸载无法推导时显示可见启动错误并返回非零，绝不回退
    // Program Files（避免直接卸载指向错误目录）。
    std::wstring installDirError;
    if (!ResolveInstallDir(&args, mode, &installDirError)) {
        return ShowStartupError(instance, L"无法确定安装目录", installDirError, mode, args);
    }

#ifdef FAF_TESTMODE
    // 测试钩子：写 MaintenanceInfo 后立即退出；发生在提权/互斥体/窗口之前。
    if (!args.testDumpPath.empty()) {
        const faf::MaintenanceInfo info = faf::Detect(args.installDir);
        return faf::WriteMaintenanceDump(info, args.testDumpPath) ? 0 : 1;
    }
#endif

    if (args.payload.empty()) args.payload = L".";
    // §1：结果协议默认路径保持不变（payload\..\install-result.ini）。
    if (args.resultPath.empty()) args.resultPath = args.payload + L"\\..\\install-result.ini";

    // D12/H2：提权前读取当前用户 SID 与 %LOCALAPPDATA%；既用于 runas 参数，
    // 也用于与 helper 传入的 /orig-sid、/orig-localappdata 比对。
    const std::wstring currentSid = CurrentUserSid();
    const std::wstring currentLocalAppData = CurrentLocalAppData();

    std::wstring identityDetail;
    if (IdentityMismatch(args, currentSid, currentLocalAppData, &identityDetail)) {
        return ShowStartupError(instance, L"用户身份不一致", identityDetail, mode, args);
    }

#ifndef FAF_TESTMODE
    // FAF_TESTMODE 完全跳过提权（测试 setup 为 RequestExecutionLevel user）。生产：
    //   * /elevated 仍非管理员 → MessageBox + 1（防递归）；
    //   * /helper-pid 已继承 helper 的管理员令牌 → 绝不再次提权；仍非管理员 →
    //     可见错误页 + 1（不写协议）；
    //   * 直接 /uninstall 或 /maintenance 未提权 → runas 重启自身，父进程退出 0。
    const bool admin = faf::IsProcessElevated();
    if (args.elevated && !admin) {
        MessageBoxW(nullptr,
                    L"维护/卸载需要管理员权限，但当前进程未获得管理员权限，已取消。",
                    L"FreeAssetFilter", MB_OK | MB_ICONERROR);
        return 1;
    }

    const bool helperLaunched = args.helperPid != 0;
    if (helperLaunched) {
        if (!admin) {
            return ShowStartupError(
                instance, L"需要管理员权限",
                L"卸载组件未获得管理员权限，无法继续。请通过“应用和功能”重新启动卸载。",
                mode, args);
        }
    } else if (!args.elevated && !admin &&
               (mode == AppMode::Uninstall || mode == AppMode::Maintenance)) {
        if (currentSid.empty() || currentLocalAppData.empty()) {
            MessageBoxW(nullptr,
                        L"无法读取当前用户身份信息，提升权限失败，操作已取消。",
                        L"FreeAssetFilter", MB_OK | MB_ICONERROR);
            return 1;
        }

        const std::wstring selfExe = SelfExePath();
        if (selfExe.empty()) {
            MessageBoxW(nullptr, L"无法定位安装程序自身，提升权限失败，操作已取消。",
                        L"FreeAssetFilter", MB_OK | MB_ICONERROR);
            return 1;
        }

        std::wstring parameters = originalArguments;
        if (!parameters.empty()) parameters.push_back(L' ');
        parameters += L"/elevated /orig-sid ";
        parameters += QuoteArgument(currentSid);
        parameters += L" /orig-localappdata ";
        parameters += QuoteArgument(currentLocalAppData);

        // 注意：lpFile 已经是 selfExe，lpParameters 里绝不重复 exe 路径。
        const HINSTANCE launched =
            ShellExecuteW(nullptr, L"runas", selfExe.c_str(), parameters.c_str(),
                          args.installDir.empty() ? nullptr : args.installDir.c_str(),
                          SW_SHOWNORMAL);
        if (reinterpret_cast<INT_PTR>(launched) <= 32) {
            MessageBoxW(nullptr,
                        mode == AppMode::Uninstall
                            ? L"卸载需要管理员权限，已取消。"
                            : L"维护操作需要管理员权限，已取消。",
                        L"FreeAssetFilter", MB_OK | MB_ICONERROR);
            return 1;
        }
        return 0;  // 提权子进程已启动；父进程不持有互斥体、不创建窗口。
    }
#endif

    // T13：只有真正要创建窗口的进程才获取单实例互斥体。提权父进程已在上面
    // 返回，因此不会出现“父进程持锁 → 子进程误判已有实例”的死锁。
    //
    // M1：清理守卫声明在窗口与互斥体之前 ⇒ 析构顺序为 InstallerWindow → 互斥体
    // → 守卫，确保所有 UI 句柄关闭、单实例释放后才安排临时目录删除。只在成为
    // 唯一实例后 Arm()，重复实例（AlreadyRunning/!Acquired）绝不会删除第一个
    // GUI 正在使用的临时目录。
    MaintenanceTempCleanupGuard cleanupGuard;
    faf::SingleInstanceGuard singleInstance;
    if (singleInstance.AlreadyRunning()) {
        faf::ActivateExistingWindow();
        return 0;
    }
    if (!singleInstance.Acquired()) return 1;
    cleanupGuard.Arm(SelfExePath());

    // T14：/maintenance 必须带 /decision；缺失时显示可见错误页（不写任何协议）。
    if (mode == AppMode::Maintenance && args.decisionPath.empty()) {
        return ShowStartupError(
            instance, L"缺少维护决策文件",
            L"维护模式必须通过 /decision 指定 maintenance-decision.ini。操作已取消。",
            mode, args);
    }

    InstallerWindow window(instance, args.payload, args.resultPath, args.installDir, mode,
                           args.decisionPath, args.setupPid, args.payloadTimeoutMs,
                           args.helperPid);
#ifdef FAF_TESTMODE
    // 测试构建：/auto 及其维护/卸载扩展参数才真正驱动无人值守流程；生产构建
    // 解析后直接丢弃（EnableAutoDrive 为 no-op，交互行为完全不变）。
    if (args.autoDrive) {
        InstallerWindow::AutoDriveOptions options;
        options.profile = args.autoProfile;
        options.stopPage = args.autoStopPage;
        options.mode = args.autoMode;
        options.action = args.autoAction;
        options.deleteUserData = args.autoDeleteUserData;
        window.EnableAutoDrive(std::move(options));
    }
#endif
    return window.Run();
}
