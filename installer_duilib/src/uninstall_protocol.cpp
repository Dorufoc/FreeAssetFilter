//
// uninstall_protocol.cpp - 维护/卸载跨进程 INI 协议实现（T5）。
//
// 只使用 Win32 profile API + C++17 标准库；不启动 helper、不删除任何文件。
// 协议常量全部来自 render/maintenance_protocol.h。
//
#include "uninstall_protocol.h"

#include <windows.h>

#include <algorithm>
#include <cerrno>
#include <chrono>
#include <climits>
#include <cstdlib>
#include <cwchar>
#include <filesystem>
#include <system_error>

namespace spk {
namespace {

namespace proto = protocol;

// 部分写入的重试窗口（M4：读取方允许 200ms 重试）。以 20ms 步进轮询，
// 总窗口固定为 protocol::kPollIntervalMs（200ms）。
constexpr std::uint32_t kReadRetryWindowMs = proto::kPollIntervalMs;
constexpr DWORD kReadRetryStepMs = 20;

constexpr std::size_t kInitialStringBuffer = 512;
constexpr std::size_t kMaxStringBuffer = 65536;

const wchar_t* BoolText(bool value) { return value ? L"1" : L"0"; }

bool FileExists(const std::wstring& path) {
    if (path.empty()) return false;
    const DWORD attributes = GetFileAttributesW(path.c_str());
    return attributes != INVALID_FILE_ATTRIBUTES &&
           (attributes & FILE_ATTRIBUTE_DIRECTORY) == 0;
}

bool EnsureParentDirectory(const std::wstring& path) {
    std::error_code ec;
    const std::filesystem::path filePath(path);
    if (!filePath.has_parent_path()) return true;
    std::filesystem::create_directories(filePath.parent_path(), ec);
    return !ec;
}

// 与 install_engine.cpp 相同的 BOM 预创建策略：W 变体在全新文件上会创建 ANSI
// 文件，因此必须先写 UTF-16LE BOM，后续 WritePrivateProfileStringW 才会以
// UTF-16LE 追加内容。CREATE_ALWAYS 同时清掉旧内容（request/decision 每次都是
// 一份完整的新快照）；WriteUiDone/WriteMaintenanceAck 不调用本函数。
bool PrecreateUtf16BomFile(const std::wstring& path) {
    HANDLE file = CreateFileW(path.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS,
                              FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return false;
    const unsigned char bom[2] = {0xFF, 0xFE};
    DWORD written = 0;
    const BOOL ok = WriteFile(file, bom, sizeof(bom), &written, nullptr);
    CloseHandle(file);
    return ok != FALSE && written == sizeof(bom);
}

// M4：跨进程写入后的强制刷盘。传 nullptr 三元组让 profile API 丢弃每个进程的
// INI 缓存并立即写回磁盘。注意：该调用在部分 Windows 版本上即使文件存在也会
// 返回 FALSE + ERROR_FILE_NOT_FOUND，但数据已落盘；因此只作 best-effort 刷盘，
// 不用它的返回值判定写入成败（与 install_engine.cpp 一致）。
void FlushIni(const std::wstring& path) {
    WritePrivateProfileStringW(nullptr, nullptr, nullptr, path.c_str());
}

// 每次跨进程写入后立即刷盘，保证 helper/UI 在 200ms 重试窗口内能看到已落盘的键。
bool WriteValue(const wchar_t* section, const wchar_t* key, const wchar_t* value,
                const std::wstring& path) {
    if (WritePrivateProfileStringW(section, key, value, path.c_str()) == FALSE) return false;
    FlushIni(path);
    return true;
}

// 读取字符串；缓冲区不足时按 2 倍增长（上限 64K），正确处理超长 error/warning。
std::wstring ReadString(const wchar_t* section, const wchar_t* key, const std::wstring& path) {
    std::wstring buffer(kInitialStringBuffer, L'\0');
    for (;;) {
        const DWORD copied =
            GetPrivateProfileStringW(section, key, L"", buffer.data(),
                                     static_cast<DWORD>(buffer.size()), path.c_str());
        if (copied < buffer.size() - 1) {
            buffer.resize(copied);
            return buffer;
        }
        if (buffer.size() >= kMaxStringBuffer) {
            buffer.resize(copied);
            return buffer;
        }
        buffer.resize(std::min(buffer.size() * 2, kMaxStringBuffer));
    }
}

bool ParseStage(const std::wstring& text, UninstallStage* stage) {
    struct StageName {
        const wchar_t* text;
        UninstallStage stage;
    };
    static constexpr StageName kStageNames[] = {
        {proto::kStageStarted, UninstallStage::Started},
        {proto::kStageRemovingShortcuts, UninstallStage::RemovingShortcuts},
        {proto::kStageRemovingRegistry, UninstallStage::RemovingRegistry},
        {proto::kStageRemovingFiles, UninstallStage::RemovingFiles},
        {proto::kStageRemovingUserData, UninstallStage::RemovingUserData},
        {proto::kStageDone, UninstallStage::Done},
        {proto::kStageFailed, UninstallStage::Failed},
        {proto::kStageCancelled, UninstallStage::Cancelled},
    };
    for (const StageName& entry : kStageNames) {
        if (_wcsicmp(text.c_str(), entry.text) == 0) {
            *stage = entry.stage;
            return true;
        }
    }
    return false;
}

bool IsTerminalStage(UninstallStage stage) {
    return stage == UninstallStage::Done || stage == UninstallStage::Failed ||
           stage == UninstallStage::Cancelled;
}

bool ParseDword(const std::wstring& text, DWORD* value) {
    if (text.empty()) return false;
    errno = 0;
    wchar_t* end = nullptr;
    const unsigned long long parsed = std::wcstoull(text.c_str(), &end, 10);
    if (errno == ERANGE || end == text.c_str() || *end != L'\0' ||
        parsed > static_cast<unsigned long long>(ULONG_MAX)) {
        return false;
    }
    *value = static_cast<DWORD>(parsed);
    return true;
}

int ReadPermille(const std::wstring& path, UninstallStage stage) {
    const UINT value = GetPrivateProfileIntW(proto::kUninstallSection, proto::kKeyPermille,
                                             static_cast<INT>(-1), path.c_str());
    if (value == static_cast<UINT>(-1)) return StageToPermille(stage);
    return static_cast<int>(std::min<UINT>(value, 1000u));
}

struct RequestSnapshot {
    bool cancelled = false;
    bool deleteUserData = false;
    DWORD uiPid = 0;
    std::wstring uiExe;
};

// 一次完整读取尝试。只有 schema=1 且 cancel 或三个字段齐全才算就绪；
// 任一步缺失都返回 false，由外层在 200ms 窗口内重试。
bool TryReadRequest(const std::wstring& path, RequestSnapshot* snapshot) {
    if (ReadString(proto::kUninstallSection, proto::kKeySchema, path) != L"1") return false;

    const std::wstring cancelledText =
        ReadString(proto::kUninstallSection, proto::kKeyCancelled, path);
    if (cancelledText == L"1") {
        snapshot->cancelled = true;
        return true;
    }
    // cancelled=0 或缺省都按未取消处理；其余值视为尚未写全/非法。
    if (!cancelledText.empty() && cancelledText != L"0") return false;

    const std::wstring deleteText =
        ReadString(proto::kUninstallSection, proto::kKeyDeleteUserData, path);
    const std::wstring pidText = ReadString(proto::kUninstallSection, proto::kKeyUiPid, path);
    const std::wstring exeText = ReadString(proto::kUninstallSection, proto::kKeyUiExe, path);
    if (deleteText != L"0" && deleteText != L"1") return false;
    if (exeText.empty()) return false;

    DWORD pid = 0;
    if (!ParseDword(pidText, &pid)) return false;

    snapshot->deleteUserData = deleteText == L"1";
    snapshot->uiPid = pid;
    snapshot->uiExe = exeText;
    return true;
}

}  // namespace

int StageToPermille(UninstallStage stage) {
    switch (stage) {
        case UninstallStage::Started:
            return 0;
        case UninstallStage::RemovingShortcuts:
            return 100;
        case UninstallStage::RemovingRegistry:
            return 300;
        case UninstallStage::RemovingFiles:
            return 500;
        case UninstallStage::RemovingUserData:
            return 800;
        case UninstallStage::Done:
            return 1000;
        case UninstallStage::Failed:
        case UninstallStage::Cancelled:
            return 0;
    }
    return 0;
}

bool WriteUninstallRequest(const std::wstring& path, bool deleteUserData, DWORD uiPid,
                           const std::wstring& uiExe) {
    if (path.empty()) return false;
    if (!EnsureParentDirectory(path) || !PrecreateUtf16BomFile(path)) return false;

    // schema 必须最先写；ui_exe 最后写，读侧以它齐全作为 request 就绪信号。
    bool ok = WriteValue(proto::kUninstallSection, proto::kKeySchema, L"1", path);
    ok = WriteValue(proto::kUninstallSection, proto::kKeyDeleteUserData,
                    BoolText(deleteUserData), path) &&
         ok;
    const std::wstring pidText = std::to_wstring(uiPid);
    ok = WriteValue(proto::kUninstallSection, proto::kKeyUiPid, pidText.c_str(), path) && ok;
    ok = WriteValue(proto::kUninstallSection, proto::kKeyUiExe, uiExe.c_str(), path) && ok;

    return ok;
}

bool WriteUninstallCancel(const std::wstring& path) {
    if (path.empty()) return false;
    if (!EnsureParentDirectory(path) || !PrecreateUtf16BomFile(path)) return false;

    bool ok = WriteValue(proto::kUninstallSection, proto::kKeySchema, L"1", path);
    ok = WriteValue(proto::kUninstallSection, proto::kKeyCancelled, L"1", path) && ok;

    return ok;
}

bool ReadUninstallRequest(const std::wstring& path, bool* deleteUserData, DWORD* uiPid,
                          std::wstring* uiExe, bool* cancelled) {
    if (deleteUserData) *deleteUserData = false;
    if (uiPid) *uiPid = 0;
    if (uiExe) uiExe->clear();
    if (cancelled) *cancelled = false;

    if (!FileExists(path)) return false;

    const auto deadline = std::chrono::steady_clock::now() +
                          std::chrono::milliseconds(kReadRetryWindowMs);
    for (;;) {
        RequestSnapshot snapshot;
        if (TryReadRequest(path, &snapshot)) {
            if (deleteUserData) *deleteUserData = snapshot.deleteUserData;
            if (uiPid) *uiPid = snapshot.uiPid;
            if (uiExe) *uiExe = snapshot.uiExe;
            if (cancelled) *cancelled = snapshot.cancelled;
            return true;
        }
        if (std::chrono::steady_clock::now() >= deadline) return false;
        Sleep(kReadRetryStepMs);
    }
}

bool WriteUiDone(const std::wstring& path) {
    // 不预创建：request 必须已经存在。预创建会把一个缺少 schema/ui_exe 的
    // 文件变成“看似存在”的 request，helper 会误判。
    if (!FileExists(path)) return false;
    const bool ok = WriteValue(proto::kUninstallSection, proto::kKeyUiDone, L"1", path);
    return ok;
}

bool ReadUninstallResult(const std::wstring& path, UninstallStage* stage, int* permille,
                         bool* done, std::wstring* error, std::wstring* warning) {
    if (stage) *stage = UninstallStage::Started;
    if (permille) *permille = 0;
    if (done) *done = false;
    if (error) error->clear();
    if (warning) warning->clear();

    if (!FileExists(path)) return false;

    const auto deadline = std::chrono::steady_clock::now() +
                          std::chrono::milliseconds(kReadRetryWindowMs);
    for (;;) {
        // done 是唯一终端键；stage 必须同时落在 done/failed/cancelled 之一，
        // 否则不构成 D15 C1 的终态（stage=failed 单独出现不算完成）。
        const std::wstring doneText =
            ReadString(proto::kUninstallSection, proto::kKeyDone, path);
        if (doneText == L"1") {
            UninstallStage parsedStage = UninstallStage::Started;
            if (ParseStage(ReadString(proto::kUninstallSection, proto::kKeyStage, path),
                           &parsedStage) &&
                IsTerminalStage(parsedStage)) {
                if (stage) *stage = parsedStage;
                if (permille) *permille = ReadPermille(path, parsedStage);
                if (error) {
                    *error = ReadString(proto::kUninstallSection, proto::kKeyError, path);
                }
                if (warning) {
                    *warning = ReadString(proto::kUninstallSection, proto::kKeyWarning, path);
                }
                if (done) *done = true;
                return true;
            }
        }
        if (std::chrono::steady_clock::now() >= deadline) return false;
        Sleep(kReadRetryStepMs);
    }
}

bool ReadUninstallProgress(const std::wstring& path, UninstallStage* stage, int* permille) {
    if (stage) *stage = UninstallStage::Started;
    if (permille) *permille = 0;
    if (!FileExists(path)) return false;

    // 与 ReadUninstallResult 不同：这里不读 done，也不等待 200ms。调用方（协调器
    // 工作线程）本身按 protocol::kPollIntervalMs 轮询，一次快照即可；stage 尚未
    // 写入（BOM 刚创建/部分写入）时返回 false，下一轮再读。
    UninstallStage parsedStage = UninstallStage::Started;
    if (!ParseStage(ReadString(proto::kUninstallSection, proto::kKeyStage, path), &parsedStage)) {
        return false;
    }
    if (stage) *stage = parsedStage;
    if (permille) *permille = ReadPermille(path, parsedStage);
    return true;
}

bool WaitForDecisionAck(const std::wstring& decisionPath, std::uint32_t timeoutMs) {
    if (decisionPath.empty()) return false;

    const auto start = std::chrono::steady_clock::now();
    for (;;) {
        if (ReadString(proto::kMaintenanceSection, proto::kKeyAck, decisionPath) == L"1") {
            return true;
        }

        const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
                                 std::chrono::steady_clock::now() - start)
                                 .count();
        if (elapsed >= static_cast<long long>(timeoutMs)) return false;

        const auto remaining =
            timeoutMs - static_cast<std::uint32_t>(std::max<long long>(elapsed, 0));
        Sleep(std::min<DWORD>(proto::kPollIntervalMs, remaining));
    }
}

bool WriteMaintenanceDecision(const std::wstring& path, MaintenanceAction action, DWORD pid) {
    if (path.empty()) return false;

    const wchar_t* actionText = nullptr;
    switch (action) {
        case MaintenanceAction::Repair:
            actionText = proto::kActionRepair;
            break;
        case MaintenanceAction::Uninstall:
            actionText = proto::kActionUninstall;
            break;
        case MaintenanceAction::Cancel:
            actionText = proto::kActionCancel;
            break;
    }
    if (actionText == nullptr) return false;

    if (!EnsureParentDirectory(path) || !PrecreateUtf16BomFile(path)) return false;

    // schema 先写、action 最后写（setup 只把非空 action 当作就绪）。
    bool ok = WriteValue(proto::kMaintenanceSection, proto::kKeySchema, L"1", path);
    const std::wstring pidText = std::to_wstring(pid);
    ok = WriteValue(proto::kMaintenanceSection, proto::kKeyPid, pidText.c_str(), path) && ok;
    ok = WriteValue(proto::kMaintenanceSection, proto::kKeyAck, L"0", path) && ok;
    ok = WriteValue(proto::kMaintenanceSection, proto::kKeyAction, actionText, path) && ok;

    return ok;
}

bool WriteMaintenanceAck(const std::wstring& path) {
    if (!FileExists(path)) return false;
    const bool ok = WriteValue(proto::kMaintenanceSection, proto::kKeyAck, L"1", path);
    return ok;
}

}  // namespace spk
