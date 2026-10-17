//
// install_engine.cpp - 安装引擎实现（Todo 13）。
//
// Frozen contracts（不得另行发明）：§1 结果 INI schema / §3 取消与失败语义 /
// §10 permille 进度 / §11 payload 就绪哨兵。
//
#include "render/install_engine.h"

#include <windows.h>

#include <algorithm>
#include <cerrno>
#include <chrono>
#include <cstdlib>
#include <system_error>

namespace fs = std::filesystem;

namespace faf {
namespace {

// §11：生产默认 1500000ms，严格小于 NSIS 的 FAF_WAIT_TIMEOUT_MS（1800000ms），
// 避免 NSIS 先 Abort 而 GUI 仍在等待形成孤儿进程。
constexpr std::uint64_t kDefaultPayloadTimeoutMs = 1500000ULL;
static_assert(kDefaultPayloadTimeoutMs < 1800000ULL,
              "Frozen §11: payload timeout must stay strictly below NSIS FAF_WAIT_TIMEOUT_MS");

constexpr wchar_t kSentinelName[] = L"payload.ready";
constexpr DWORD kSentinelPollMs = 100;

const wchar_t* BoolText(bool value) { return value ? L"1" : L"0"; }

// §1：以 UTF-16LE + BOM（0xFF 0xFE）预创建结果文件。**仅允许在结果写入例程内调用**——
// 严禁在 GUI 启动或开始安装时预创建（否则 NSIS 的 IfFileExists 早于结果成立）。
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

}  // namespace

std::filesystem::path PayloadSentinelPath(const std::filesystem::path& payload) {
    // §11 冻结推导：父目录 / "payload.ready"；无父目录（默认 "."）⇒ 当前目录下
    // "payload.ready"（parent_path() 为空，空路径拼接即退化名）。
    return payload.parent_path() / kSentinelName;
}

std::uint64_t PayloadTimeoutMs() {
    // §11：无条件读取（与 NSIS 侧 FAF_WAIT_TIMEOUT_MS 同性质的运行时诊断覆盖，
    // 不受 #ifdef FAF_TESTMODE 约束）；未设置或非法 ⇒ 生产默认。
    wchar_t buffer[64] = {};
    const DWORD length =
        GetEnvironmentVariableW(L"FAF_PAYLOAD_TIMEOUT_MS", buffer, ARRAYSIZE(buffer));
    if (length == 0 || length >= ARRAYSIZE(buffer)) return kDefaultPayloadTimeoutMs;
    errno = 0;
    wchar_t* end = nullptr;
    const unsigned long long value = std::wcstoull(buffer, &end, 10);
    if (errno == ERANGE || end == buffer || *end != L'\0') return kDefaultPayloadTimeoutMs;
    return static_cast<std::uint64_t>(value);
}

bool WriteInstallResultIni(const std::wstring& resultPath, const std::wstring& dir, bool abort,
                           const std::wstring& error, const InstallOptions& options) {
    if (resultPath.empty()) return false;

    std::error_code ec;
    const fs::path path(resultPath);
    if (path.has_parent_path()) fs::create_directories(path.parent_path(), ec);

    // §1：唯一允许的 BOM 预创建点（结果写入例程内）。
    if (!PrecreateUtf16BomFile(resultPath)) return false;

    // §1：先写 [faf] 占位节（schema=1），使 [install] 永不为文件首节——规避
    // GetPrivateProfileString 对「BOM + 首节」的历史性怪癖。
    bool ok = WritePrivateProfileStringW(L"faf", L"schema", L"1", resultPath.c_str()) != FALSE;
    auto write = [&](const wchar_t* key, const wchar_t* value) {
        ok = (WritePrivateProfileStringW(L"install", key, value, resultPath.c_str()) != FALSE) && ok;
    };
    write(L"dir", dir.c_str());
    write(L"desktop", BoolText(options.desktop));
    write(L"startmenu", BoolText(options.startmenu));
    write(L"autostart", BoolText(options.autostart));
    // error 恒写：成功为空串（GetPrivateProfileString 读回空串，语义一致）。
    write(L"error", error.c_str());
    // §1 终端键：abort 恒被写入，且必须是最后一个键（NSIS 仅当它非空才认为就绪）。
    write(L"abort", abort ? L"1" : L"0");

    // 防御性收尾（刷新 INI→注册表映射缓存；真实文件写入本身对其余进程即时可见）。
    WritePrivateProfileStringW(nullptr, nullptr, nullptr, resultPath.c_str());
    return ok;
}

int InstallEngine::PermilleFor(std::uint64_t written, std::uint64_t total) {
    if (total == 0) return 1000;  // 空 payload：无字节可报，直接视为完成
    const std::uint64_t permille = written * 1000ULL / total;
    return static_cast<int>(std::min<std::uint64_t>(permille, 1000ULL));
}

InstallEngine::InstallEngine(std::wstring payload, std::wstring installDir, std::wstring resultPath)
    : payload_(std::move(payload)),
      installDir_(std::move(installDir)),
      resultPath_(std::move(resultPath)) {}

InstallResult InstallEngine::Run(const InstallOptions& options, const std::atomic<bool>& cancel,
                                 const ProgressFn& onProgress) {
    writtenFiles_.clear();
    createdDirs_.clear();
    InstallResult result;

    // ---- 1. §11：先等哨兵（必须早于预扫描）----
    const fs::path sentinel = PayloadSentinelPath(fs::path(payload_));
    const std::uint64_t timeoutMs = PayloadTimeoutMs();
    const auto waitStart = std::chrono::steady_clock::now();
    std::error_code waitEc;
    while (!fs::exists(sentinel, waitEc)) {
        if (cancel.load()) {
            result.cancelled = true;
            result.error = L"cancelled";
            return Finalize(result, options);
        }
        const auto elapsedMs = std::chrono::duration_cast<std::chrono::milliseconds>(
                                   std::chrono::steady_clock::now() - waitStart)
                                   .count();
        if (elapsedMs >= 0 && static_cast<std::uint64_t>(elapsedMs) >= timeoutMs) {
            // §11：只有超过宽限才写 abort=1 error=payload-timeout 并退出。
            result.timedOut = true;
            result.error = L"payload-timeout";
            return Finalize(result, options);
        }
        Sleep(kSentinelPollMs);
    }
    if (cancel.load()) {
        result.cancelled = true;
        result.error = L"cancelled";
        return Finalize(result, options);
    }

    // ---- 2. 递归预扫描：payload 总字节 + 文件数（哨兵在 payload 之外，不计数）----
    std::error_code dirEc;
    if (!fs::is_directory(fs::path(payload_), dirEc)) {
        result.error = L"payload-missing";
        return Finalize(result, options);
    }
    std::vector<Entry> entries;
    std::uint64_t totalBytes = 0;
    {
        std::error_code itEc;
        fs::recursive_directory_iterator it(fs::path(payload_),
                                            fs::directory_options::skip_permission_denied, itEc);
        const fs::recursive_directory_iterator end;
        while (!itEc && it != end) {
            std::error_code fileEc;
            if (it->is_regular_file(fileEc) && !fileEc) {
                const fs::path source = it->path();
                // 防御：仅当退化布局（payload="."，哨兵恰好落在 payload 内）命中同名哨兵时跳过。
                bool isSentinel = false;
                if (source.filename() == kSentinelName) {
                    std::error_code eqEc;
                    isSentinel = fs::equivalent(source, sentinel, eqEc) && !eqEc;
                }
                if (!isSentinel) {
                    std::error_code relEc;
                    const fs::path relative = fs::relative(source, fs::path(payload_), relEc);
                    const std::uint64_t size = it->file_size(fileEc);
                    if (!relEc && !fileEc) {
                        entries.push_back(Entry{source, relative, size});
                        totalBytes += size;
                    }
                }
            }
            it.increment(itEc);
        }
    }
    result.totalFiles = entries.size();
    result.totalBytes = totalBytes;

    // ---- 3. 复制：累计已写字节 → permille（§10）；取消即停（§3）----
    const fs::path targetRoot(installDir_);
    {
        std::error_code mkEc;
        fs::create_directories(targetRoot, mkEc);
        std::error_code isDirEc;
        if (mkEc || !fs::is_directory(targetRoot, isDirEc)) {
            result.error = L"install-dir-create-failed";
            return Finalize(result, options);
        }
    }

    std::uint64_t copiedBytes = 0;
    for (const Entry& entry : entries) {
        if (cancel.load()) {
            result.cancelled = true;
            result.error = L"cancelled";
            return Finalize(result, options);
        }
        const fs::path destination = targetRoot / entry.relative;
        if (!EnsureParentCreated(destination.parent_path())) {
            result.error = L"mkdir-failed: " + entry.relative.wstring();
            return Finalize(result, options);
        }
        std::error_code copyEc;
        fs::copy_file(entry.source, destination, fs::copy_options::overwrite_existing, copyEc);
        if (copyEc) {
            result.error = L"copy-failed: " + entry.relative.wstring();
            return Finalize(result, options);
        }
        writtenFiles_.push_back(destination);
        copiedBytes += entry.size;
        ++result.copiedFiles;
        result.copiedBytes = copiedBytes;
        if (onProgress) onProgress(PermilleFor(copiedBytes, totalBytes));
    }

    // 复制完成后、宣布成功前的最后取消检查（避免「已取消仍报成功」的窄竞态）。
    if (cancel.load()) {
        result.cancelled = true;
        result.error = L"cancelled";
        return Finalize(result, options);
    }
    if (onProgress) onProgress(1000);  // 终值恒发（节流方保证不丢 1000）
    result.ok = true;
    return Finalize(result, options);
}

bool InstallEngine::EnsureParentCreated(const std::filesystem::path& parent) {
    if (parent.empty()) return true;
    std::error_code existsEc;
    if (fs::exists(parent, existsEc)) return fs::is_directory(parent, existsEc);

    // 记录尚不存在的祖先链（自下而上），供 §3 清理时按深度逆序删除空目录。
    std::vector<fs::path> pending;
    fs::path probe = parent;
    while (!probe.empty() && !fs::exists(probe, existsEc)) {
        pending.push_back(probe);
        const fs::path up = probe.parent_path();
        if (up == probe || up.empty()) break;  // 到达根：不再上溯
        probe = up;
    }
    std::error_code createEc;
    fs::create_directories(parent, createEc);
    if (createEc) return false;
    for (const fs::path& dir : pending) createdDirs_.push_back(dir);
    return true;
}

void InstallEngine::CleanupWritten() {
    std::error_code ec;
    for (auto it = writtenFiles_.rbegin(); it != writtenFiles_.rend(); ++it) {
        fs::remove(*it, ec);  // 仅删本次写入项（被覆盖的旧文件无法还原——§3 已知取舍）
        ec.clear();
    }
    // 目录按路径深度（native 长度近似）降序删除；非空删除会失败并静默保留。
    std::vector<fs::path> dirs = createdDirs_;
    std::sort(dirs.begin(), dirs.end(), [](const fs::path& a, const fs::path& b) {
        return a.native().size() > b.native().size();
    });
    for (const fs::path& dir : dirs) {
        std::error_code removeEc;
        fs::remove(dir, removeEc);
    }
    writtenFiles_.clear();
    createdDirs_.clear();
}

InstallResult InstallEngine::Finalize(InstallResult result, const InstallOptions& options) {
    if (!result.ok) CleanupWritten();  // §3：取消或发生错误 ⇒ 删除本次运行已写入的文件
    // §1：abort = 失败/取消/超时（成功为 0）；error 恒写（成功空串）。
    result.iniWritten =
        WriteInstallResultIni(resultPath_, installDir_, /*abort=*/!result.ok, result.error, options);
    return result;
}

}  // namespace faf
