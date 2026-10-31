//
// maintenance_detector.cpp - T2 实现：安装状态 / 选项 / 版本只读探测。
//
// 全部路径只读（见头文件契约）；唯一的写操作是 WriteMaintenanceDump。
// 生产/测试注册表键一律来自 render/maintenance_protocol.h，不在本文件重复定义。
//
#include "maintenance_detector.h"

#include <windows.h>

#include <knownfolders.h>
#include <objbase.h>
#include <shlobj.h>

#include <algorithm>
#include <cstddef>
#include <cwchar>
#include <filesystem>
#include <utility>
#include <vector>

#include "render/maintenance_protocol.h"

namespace spk {
namespace {

// protocol 头未收录 Run 键（它不属于安装信息键/卸载键）。值名与快捷方式名
// 统一取自 protocol::kShortcutStem，保证测试构建不会碰到生产 Run 值/快捷方式。
constexpr wchar_t kRunKey[] = L"Software\\Microsoft\\Windows\\CurrentVersion\\Run";
constexpr wchar_t kLnkSuffix[] = L".lnk";

// WriteMaintenanceDump 的 INI 键（诊断 schema；见头文件）。
constexpr wchar_t kDumpSchema[] = L"1";
constexpr wchar_t kDumpKeyDetected[] = L"detected";
constexpr wchar_t kDumpKeyComplete[] = L"complete";
constexpr wchar_t kDumpKeyInstallDir[] = L"install_dir";
constexpr wchar_t kDumpKeyVersion[] = L"version";
constexpr wchar_t kDumpKeyOptDesktop[] = L"opt_desktop";
constexpr wchar_t kDumpKeyOptStartmenu[] = L"opt_startmenu";
constexpr wchar_t kDumpKeyOptAutostart[] = L"opt_autostart";
constexpr wchar_t kDumpKeyOptionsInferred[] = L"options_inferred";

// ---------------------------------------------------------------------------
// RAII
// ---------------------------------------------------------------------------

// HKEY 的 RAII 包装（只读打开，析构 RegCloseKey）。
class UniqueRegKey {
public:
    UniqueRegKey() = default;
    explicit UniqueRegKey(HKEY key) noexcept : key_(key) {}
    ~UniqueRegKey() { reset(); }

    UniqueRegKey(const UniqueRegKey&) = delete;
    UniqueRegKey& operator=(const UniqueRegKey&) = delete;

    UniqueRegKey(UniqueRegKey&& other) noexcept : key_(other.release()) {}
    UniqueRegKey& operator=(UniqueRegKey&& other) noexcept {
        if (this != &other) reset(other.release());
        return *this;
    }

    HKEY get() const noexcept { return key_; }
    HKEY release() noexcept {
        HKEY key = key_;
        key_ = nullptr;
        return key;
    }
    void reset(HKEY key = nullptr) noexcept {
        if (key_ != nullptr) RegCloseKey(key_);
        key_ = key;
    }

private:
    HKEY key_ = nullptr;
};

// HANDLE 的 RAII 包装（INVALID_HANDLE_VALUE / nullptr 均视为空）。
class UniqueHandle {
public:
    UniqueHandle() = default;
    explicit UniqueHandle(HANDLE handle) noexcept : handle_(handle) {}
    ~UniqueHandle() { reset(); }

    UniqueHandle(const UniqueHandle&) = delete;
    UniqueHandle& operator=(const UniqueHandle&) = delete;

    UniqueHandle(UniqueHandle&& other) noexcept : handle_(other.release()) {}
    UniqueHandle& operator=(UniqueHandle&& other) noexcept {
        if (this != &other) reset(other.release());
        return *this;
    }

    bool valid() const noexcept { return handle_ != nullptr && handle_ != INVALID_HANDLE_VALUE; }
    HANDLE get() const noexcept { return handle_; }
    HANDLE release() noexcept {
        HANDLE handle = handle_;
        handle_ = nullptr;
        return handle;
    }
    void reset(HANDLE handle = nullptr) noexcept {
        if (valid()) CloseHandle(handle_);
        handle_ = handle;
    }

private:
    HANDLE handle_ = nullptr;
};

// ---------------------------------------------------------------------------
// 路径 / 字符串
// ---------------------------------------------------------------------------

bool PathExists(const std::wstring& path) {
    return !path.empty() && GetFileAttributesW(path.c_str()) != INVALID_FILE_ATTRIBUTES;
}

std::wstring JoinPath(const std::wstring& base, const std::wstring& leaf) {
    if (base.empty()) return leaf;
    std::wstring result = base;
    if (result.back() != L'\\' && result.back() != L'/') result.push_back(L'\\');
    result += leaf;
    return result;
}

void TrimInPlace(std::wstring& text) {
    const auto isTrimmable = [](wchar_t ch) {
        return ch == L' ' || ch == L'\t' || ch == L'\r' || ch == L'\n' || ch == L'\0';
    };
    while (!text.empty() && isTrimmable(text.back())) text.pop_back();
    std::size_t start = 0;
    while (start < text.size() && isTrimmable(text[start])) ++start;
    if (start != 0) text.erase(0, start);
}

// 去掉外层引号/空白与尾部多余分隔符，并折叠 `.`/重复分隔符；保留盘符根 "C:\"。
std::wstring NormalizeInstallDir(std::wstring dir) {
    TrimInPlace(dir);
    if (dir.size() >= 2 && dir.front() == L'"' && dir.back() == L'"') {
        dir = dir.substr(1, dir.size() - 2);
        TrimInPlace(dir);
    }
    if (dir.empty()) return {};

    std::replace(dir.begin(), dir.end(), L'/', L'\\');
    std::wstring normalized = std::filesystem::path(dir).lexically_normal().wstring();
    while (normalized.size() > 3 && normalized.back() == L'\\') normalized.pop_back();
    return normalized;
}

// 快捷方式 / Run 值名（生产 Sopeek，测试 SopeekTest）。
// 不再从 exe 名推导：测试 exe 名带 Test 但必须与生产快捷方式完全隔离。
std::wstring ShortcutStem() {
    return protocol::kShortcutStem;
}

bool EqualsIgnoreCase(const std::wstring& left, const std::wstring& right) {
    const int leftLength = static_cast<int>(left.size());
    const int rightLength = static_cast<int>(right.size());
    return CompareStringOrdinal(left.c_str(), leftLength, right.c_str(), rightLength, TRUE) ==
           CSTR_EQUAL;
}

// ---------------------------------------------------------------------------
// 已知文件夹 / 快捷方式
// ---------------------------------------------------------------------------

std::wstring KnownFolderPath(REFKNOWNFOLDERID folderId) {
    PWSTR raw = nullptr;
    if (FAILED(SHGetKnownFolderPath(folderId, KF_FLAG_DEFAULT, nullptr, &raw)) || raw == nullptr) {
        return {};
    }
    std::wstring path(raw);
    CoTaskMemFree(raw);
    return path;
}

// 无法定位桌面目录时回退默认 true（D11）。
bool InferDesktopOption() {
    const std::wstring desktop = KnownFolderPath(FOLDERID_Desktop);
    if (desktop.empty()) return true;
    return PathExists(JoinPath(desktop, ShortcutStem() + kLnkSuffix));
}

// NSIS 写 <Programs>\<stem>\<stem>.lnk；兼容旧安装器的扁平 <Programs>\<stem>.lnk。
// 无法定位开始菜单目录时回退默认 true（D11）。
bool InferStartmenuOption() {
    const std::wstring programs = KnownFolderPath(FOLDERID_Programs);
    if (programs.empty()) return true;
    const std::wstring stem = ShortcutStem();
    const std::wstring shortcut = stem + kLnkSuffix;
    return PathExists(JoinPath(JoinPath(programs, stem), shortcut)) ||
           PathExists(JoinPath(programs, shortcut));
}

// ---------------------------------------------------------------------------
// 注册表（只读）
// ---------------------------------------------------------------------------

enum class ValueState {
    Missing,  // 键或值不存在
    Invalid,  // 存在但类型/长度不是 DWORD
    Present,
};

ValueState ReadDword(HKEY root, const wchar_t* subKey, const wchar_t* valueName, DWORD& out) {
    HKEY raw = nullptr;
    if (RegOpenKeyExW(root, subKey, 0, KEY_QUERY_VALUE, &raw) != ERROR_SUCCESS) {
        return ValueState::Missing;
    }
    UniqueRegKey key(raw);

    DWORD type = 0;
    DWORD data = 0;
    DWORD bytes = sizeof(data);
    const LSTATUS status = RegQueryValueExW(key.get(), valueName, nullptr, &type,
                                            reinterpret_cast<LPBYTE>(&data), &bytes);
    if (status == ERROR_FILE_NOT_FOUND) return ValueState::Missing;
    if (status != ERROR_SUCCESS) return ValueState::Invalid;
    if (type != REG_DWORD || bytes != sizeof(DWORD)) return ValueState::Invalid;

    out = data;
    return ValueState::Present;
}

bool ReadString(HKEY root, const wchar_t* subKey, const wchar_t* valueName, std::wstring& out) {
    HKEY raw = nullptr;
    if (RegOpenKeyExW(root, subKey, 0, KEY_QUERY_VALUE, &raw) != ERROR_SUCCESS) return false;
    UniqueRegKey key(raw);

    DWORD type = 0;
    DWORD bytes = 0;
    if (RegQueryValueExW(key.get(), valueName, nullptr, &type, nullptr, &bytes) != ERROR_SUCCESS) {
        return false;
    }
    if ((type != REG_SZ && type != REG_EXPAND_SZ) || bytes < sizeof(wchar_t)) return false;

    // 多留一个 wchar，兼容未写终止 NUL 的值。
    std::wstring buffer(bytes / sizeof(wchar_t) + 1, L'\0');
    DWORD capacity = static_cast<DWORD>(buffer.size() * sizeof(wchar_t));
    if (RegQueryValueExW(key.get(), valueName, nullptr, &type,
                         reinterpret_cast<LPBYTE>(buffer.data()), &capacity) != ERROR_SUCCESS) {
        return false;
    }
    if (type != REG_SZ && type != REG_EXPAND_SZ) return false;
    if (capacity > buffer.size() * sizeof(wchar_t)) return false;

    buffer.resize(capacity / sizeof(wchar_t));
    while (!buffer.empty() && buffer.back() == L'\0') buffer.pop_back();
    out = std::move(buffer);
    return true;
}

// Run 值必须精确指向本安装 exe；NSIS 写入时带外层引号，故允许成对引号。
bool RunValueMatches(const std::wstring& value, const std::wstring& exePath) {
    if (value.empty() || exePath.empty()) return false;
    std::wstring candidate = value;
    if (candidate.size() >= 2 && candidate.front() == L'"' && candidate.back() == L'"') {
        candidate = candidate.substr(1, candidate.size() - 2);
    }
    return EqualsIgnoreCase(candidate, exePath);
}

// 无法推断（installDir 为空）时回退默认 false（D11）。
// 测试构建绝不读取生产 Run 键：测试安装不写自启项，读取生产值会把它错误地
// 推断为用户选择并带入测试安装元数据（F2）。
bool InferAutostartOption(const std::wstring& exePath) {
    if (protocol::kTestMode) return false;
    if (exePath.empty()) return false;
    const std::wstring valueName = ShortcutStem();
    std::wstring value;
    if (!ReadString(HKEY_CURRENT_USER, kRunKey, valueName.c_str(), value)) return false;
    return RunValueMatches(value, exePath);
}

// ---------------------------------------------------------------------------
// 版本资源
// ---------------------------------------------------------------------------

// version.dll 不在 CMake 的链接库清单中（T2 不允许改 CMakeLists.txt），故按需
// 动态加载；对外仍是标准 GetFileVersionInfoSizeW/GetFileVersionInfoW/
// VerQueryValueW 语义，不引入额外链接依赖与第三方库。
template <typename Fn>
Fn LoadVersionFn(HMODULE module, const char* name) {
    const FARPROC raw = GetProcAddress(module, name);
    if (raw == nullptr) return nullptr;
    // 先转 void(*)()（GCC 视为与任意函数类型兼容），再转目标签名。
    return reinterpret_cast<Fn>(reinterpret_cast<void (*)()>(raw));
}

class VersionApi {
public:
    using GetSizeFn = BOOL(WINAPI*)(LPCWSTR, LPDWORD);
    using GetInfoFn = BOOL(WINAPI*)(LPCWSTR, DWORD, DWORD, LPVOID);
    using QueryFn = BOOL(WINAPI*)(LPCVOID, LPCWSTR, LPVOID*, PUINT);

    VersionApi() {
        module_ = LoadLibraryW(L"version.dll");
        if (module_ == nullptr) return;
        getSize_ = LoadVersionFn<GetSizeFn>(module_, "GetFileVersionInfoSizeW");
        getInfo_ = LoadVersionFn<GetInfoFn>(module_, "GetFileVersionInfoW");
        query_ = LoadVersionFn<QueryFn>(module_, "VerQueryValueW");
        if (getSize_ == nullptr || getInfo_ == nullptr || query_ == nullptr) {
            getSize_ = nullptr;
            getInfo_ = nullptr;
            query_ = nullptr;
            FreeLibrary(module_);
            module_ = nullptr;
        }
    }

    ~VersionApi() {
        if (module_ != nullptr) FreeLibrary(module_);
    }

    VersionApi(const VersionApi&) = delete;
    VersionApi& operator=(const VersionApi&) = delete;

    bool available() const { return module_ != nullptr; }
    GetSizeFn getSize() const { return getSize_; }
    GetInfoFn getInfo() const { return getInfo_; }
    QueryFn query() const { return query_; }

private:
    HMODULE module_ = nullptr;
    GetSizeFn getSize_ = nullptr;
    GetInfoFn getInfo_ = nullptr;
    QueryFn query_ = nullptr;
};

// 进程级惰性单例（C++11 线程安全；进程退出时 FreeLibrary）。
const VersionApi& VersionApiInstance() {
    static const VersionApi api;
    return api;
}

void QueryFileVersionString(const VersionApi& api, const std::vector<BYTE>& data, WORD language,
                            WORD codePage, std::wstring& out) {
    wchar_t block[64] = {};
    std::swprintf(block, ARRAYSIZE(block), L"\\StringFileInfo\\%04x%04x\\FileVersion",
                  static_cast<unsigned>(language), static_cast<unsigned>(codePage));

    void* rawValue = nullptr;
    UINT valueChars = 0;
    if (!api.query()(data.data(), block, &rawValue, &valueChars) || rawValue == nullptr ||
        valueChars == 0) {
        return;
    }

    std::wstring version(static_cast<const wchar_t*>(rawValue), valueChars);
    TrimInPlace(version);
    out = std::move(version);
}

// 失败（exe 不存在/无版本资源/无 FileVersion 字符串）=> 空串（T2）。
std::wstring ReadFileVersion(const std::wstring& exePath) {
    if (exePath.empty()) return {};
    const VersionApi& api = VersionApiInstance();
    if (!api.available()) return {};

    DWORD ignored = 0;
    const DWORD bytes = api.getSize()(exePath.c_str(), &ignored);
    if (bytes == 0) return {};

    std::vector<BYTE> data(bytes);
    if (!api.getInfo()(exePath.c_str(), 0, bytes, data.data())) return {};

    struct Translation {
        WORD language;
        WORD codePage;
    };

    Translation* translations = nullptr;
    UINT translationBytes = 0;
    if (!api.query()(data.data(), L"\\VarFileInfo\\Translation",
                     reinterpret_cast<LPVOID*>(&translations), &translationBytes) ||
        translations == nullptr || translationBytes < sizeof(Translation)) {
        return {};
    }

    const std::size_t count = translationBytes / sizeof(Translation);
    for (std::size_t i = 0; i < count; ++i) {
        std::wstring version;
        QueryFileVersionString(api, data, translations[i].language, translations[i].codePage,
                               version);
        if (!version.empty()) return version;
    }
    return {};
}

// ---------------------------------------------------------------------------
// 诊断输出（唯一的写操作）
// ---------------------------------------------------------------------------

bool PrecreateUtf16BomFile(const std::wstring& path) {
    UniqueHandle file(CreateFileW(path.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS,
                                  FILE_ATTRIBUTE_NORMAL, nullptr));
    if (!file.valid()) return false;

    const unsigned char bom[2] = {0xFF, 0xFE};
    DWORD written = 0;
    const BOOL ok = WriteFile(file.get(), bom, sizeof(bom), &written, nullptr);
    return ok != FALSE && written == sizeof(bom);
}

}  // namespace

MaintenanceInfo Detect(const std::wstring& installDir) {
    MaintenanceInfo info;

    info.installDir = NormalizeInstallDir(installDir);
    if (info.installDir.empty()) {
        std::wstring storedDir;
        if (ReadString(HKEY_CURRENT_USER, protocol::kInstallInfoKey, protocol::kValueInstallDir,
                       storedDir)) {
            info.installDir = NormalizeInstallDir(storedDir);
        }
    }

    const std::wstring exePath =
        info.installDir.empty() ? std::wstring() : JoinPath(info.installDir, protocol::kAppExeName);
    const std::wstring internalPath = info.installDir.empty()
                                          ? std::wstring()
                                          : JoinPath(info.installDir, protocol::kInternalDirName);

    const bool exeExists = PathExists(exePath);
    const bool internalExists = PathExists(internalPath);
    info.detected = exeExists || internalExists;  // D15-H1 唯一判定
    info.complete = exeExists && internalExists;
    if (exeExists) info.version = ReadFileVersion(exePath);

    // 选项：注册表 DWORD 优先；缺失/非法时逐项推断（D11）。
    DWORD value = 0;
    const auto readOption = [&](const wchar_t* valueName, bool& option) {
        if (ReadDword(HKEY_CURRENT_USER, protocol::kInstallInfoKey, valueName, value) !=
            ValueState::Present) {
            return false;
        }
        option = value != 0;
        return true;
    };

    const bool desktopPersisted = readOption(protocol::kValueOptDesktop, info.optDesktop);
    const bool startmenuPersisted = readOption(protocol::kValueOptStartmenu, info.optStartmenu);
    const bool autostartPersisted = readOption(protocol::kValueOptAutostart, info.optAutostart);

    if (!desktopPersisted) info.optDesktop = InferDesktopOption();
    if (!startmenuPersisted) info.optStartmenu = InferStartmenuOption();
    if (!autostartPersisted) info.optAutostart = InferAutostartOption(exePath);

    info.optionsInferred = !desktopPersisted || !startmenuPersisted || !autostartPersisted;
    return info;
}

bool WriteMaintenanceDump(const MaintenanceInfo& info, const std::wstring& iniPath) {
    if (iniPath.empty()) return false;
    if (!PrecreateUtf16BomFile(iniPath)) return false;

    bool ok = true;
    const auto write = [&](const wchar_t* key, const std::wstring& value) {
        ok = (WritePrivateProfileStringW(protocol::kMaintenanceSection, key, value.c_str(),
                                         iniPath.c_str()) != FALSE) &&
             ok;
    };
    const auto writeBool = [&](const wchar_t* key, bool value) { write(key, value ? L"1" : L"0"); };

    write(protocol::kKeySchema, kDumpSchema);
    writeBool(kDumpKeyDetected, info.detected);
    writeBool(kDumpKeyComplete, info.complete);
    write(kDumpKeyInstallDir, info.installDir);
    write(kDumpKeyVersion, info.version);
    writeBool(kDumpKeyOptDesktop, info.optDesktop);
    writeBool(kDumpKeyOptStartmenu, info.optStartmenu);
    writeBool(kDumpKeyOptAutostart, info.optAutostart);
    writeBool(kDumpKeyOptionsInferred, info.optionsInferred);

    // 刷盘（跨进程/后续读取可见；M4 同款收尾）。
    WritePrivateProfileStringW(nullptr, nullptr, nullptr, iniPath.c_str());
    return ok;
}

}  // namespace spk
