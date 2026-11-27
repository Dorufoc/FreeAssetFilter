// Sopeek 资源管理器右键菜单扩展（in-proc COM，IExplorerCommand）。
//
// 两条命令：
//   * 文件（“用Sopeek软件打开”）：Windows 10 经典菜单 + Windows 11 现代菜单。
//   * 文件夹/文件夹空白处（“使用Sopeek打开”）：Directory\shell 与
//     Directory\Background\shell 共用同一个 CLSID，标题固定，不依赖上下文。
//
// 设计要点：
//   - 只导出 DllGetClassObject / DllCanUnloadNow（见 shell_ext.def）。
//   - 不依赖 uuid.lib：用到的 IID 在本文件内以同名常量给出，语义完全等价。
//   - 菜单项的目标路径：Invoke 的 IShellItemArray 有项时取首项；文件夹空白处
//     的数组为空（或仅含该文件夹）时，经 IObjectWithSite 保存的 site 取
//     IShellBrowser → IShellView → IFolderView / IPersistFolder2 的当前目录。
//   - 启动应用统一带 --open-path，由应用侧解析并导航/定位。

#include <windows.h>
#include <shlobj.h>
#include <shobjidl.h>
#include <shlwapi.h>
#include <shellapi.h>
#include <servprov.h>

#include <new>
#include <cstdio>
#include <string>

namespace {

HINSTANCE g_module_instance = nullptr;
volatile LONG g_object_count = 0;
volatile LONG g_lock_count = 0;

const GUID kIidUnknown = {0x00000000, 0x0000, 0x0000, {0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46}};
const GUID kIidClassFactory = {0x00000001, 0x0000, 0x0000, {0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46}};
const GUID kIidShellView = {0x000214E3, 0x0000, 0x0000, {0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46}};
const GUID kIidShellBrowser = {0x000214E2, 0x0000, 0x0000, {0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46}};
const GUID kIidServiceProvider = {0x6D5140C1, 0x7436, 0x11CE, {0x80, 0x34, 0x00, 0xAA, 0x00, 0x60, 0x09, 0xFA}};
const GUID kSidShellBrowser = {0x000214D2, 0x0000, 0x0000, {0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46}};
const GUID kIidFolderView = {0xCDE725B0, 0xCCC9, 0x4519, {0x91, 0x7E, 0x32, 0x5D, 0x72, 0xFA, 0xB4, 0xCE}};
const GUID kIidPersistFolder2 = {0x1AC3D9F0, 0x175C, 0x11D1, {0x95, 0xBE, 0x00, 0x60, 0x97, 0x97, 0xEA, 0x4F}};
const GUID kIidExplorerCommand = {0xA08CE4D0, 0xFA25, 0x44AB, {0xB5, 0x7C, 0xC7, 0xB1, 0xC3, 0x23, 0xE0, 0xB9}};
const GUID kIidObjectWithSite = {0xFC4801A3, 0x2BA9, 0x11CF, {0xA2, 0x29, 0x00, 0xAA, 0x00, 0x3D, 0x73, 0x52}};
const GUID kIidShellItem = {0x43826D1E, 0xE718, 0x42EE, {0xBC, 0x55, 0xA1, 0xE2, 0x61, 0xC3, 0x7B, 0xFE}};
const GUID kIidShellWindows = {0x85CB6900, 0x4D95, 0x11CF, {0x96, 0x0C, 0x00, 0x80, 0xC7, 0xF4, 0xEE, 0x85}};
const GUID kClsidShellWindows = {0x9BA05972, 0xF6A8, 0x11CF, {0xA4, 0x42, 0x00, 0xA0, 0xC9, 0x0A, 0x8F, 0x39}};
// SID_STopLevelBrowser：从任意 shell 窗口的 IServiceProvider 拿到它的 IShellBrowser。
const GUID kSidTopLevelBrowser = {0x4C96BE40, 0x915C, 0x11CF, {0x99, 0xD3, 0x00, 0xAA, 0x00, 0x4A, 0xE8, 0x37}};

// 生产与测试各用一对 CLSID：测试构建只写 HKCU，必须不能与 HKLM 的生产
// 注册互相遮蔽（同一个 CLSID 在两处注册时用户级会覆盖机器级）。
const CLSID kClsidFileProduction = {0x02F1BD14, 0xA1B5, 0x4B9E, {0x9E, 0x10, 0xC7, 0x56, 0xD5, 0x37, 0xFD, 0xA0}};
const CLSID kClsidFolderProduction = {0x39F01A4C, 0xDD1D, 0x48D2, {0x8F, 0xB3, 0x0E, 0x0C, 0x76, 0xB3, 0x36, 0xBC}};
const CLSID kClsidFileTest = {0xADD20484, 0x57FF, 0x4DEB, {0x85, 0x61, 0xAC, 0x7F, 0x04, 0xCA, 0xFD, 0xCB}};
const CLSID kClsidFolderTest = {0x430F8D9E, 0x4290, 0x46F8, {0x8E, 0x40, 0xE3, 0x8D, 0xAB, 0x04, 0xC5, 0xBD}};

const wchar_t kFileTitle[] = L"用Sopeek软件打开";
const wchar_t kFolderTitle[] = L"使用Sopeek打开";
const wchar_t kExecutableName[] = L"Sopeek.exe";
const wchar_t kArgumentName[] = L"--open-path";

bool GuidEquals(REFGUID left, REFGUID right) {
    return IsEqualGUID(left, right) != FALSE;
}

bool IsFolderClsid(REFCLSID clsid) {
    return GuidEquals(clsid, kClsidFolderProduction) || GuidEquals(clsid, kClsidFolderTest);
}

bool IsFileClsid(REFCLSID clsid) {
    return GuidEquals(clsid, kClsidFileProduction) || GuidEquals(clsid, kClsidFileTest);
}

std::wstring ModuleDirectory() {
    wchar_t buffer[MAX_PATH * 4] = {};
    DWORD length = GetModuleFileNameW(g_module_instance, buffer, static_cast<DWORD>(sizeof(buffer) / sizeof(buffer[0])));
    if (length == 0 || length >= sizeof(buffer) / sizeof(buffer[0])) {
        return std::wstring();
    }
    std::wstring path(buffer, length);
    const std::wstring::size_type slash = path.find_last_of(L"\\/");
    return slash == std::wstring::npos ? std::wstring() : path.substr(0, slash);
}

std::wstring ExecutablePath() {
    const std::wstring directory = ModuleDirectory();
    if (directory.empty()) {
        return std::wstring();
    }
    return directory + L"\\" + kExecutableName;
}

HRESULT DuplicateString(const wchar_t* source, wchar_t** target) {
    if (target == nullptr) {
        return E_POINTER;
    }
    *target = nullptr;
    return SHStrDupW(source, target);
}

HRESULT DisplayNameOfItem(IShellItem* item, std::wstring& path) {
    if (item == nullptr) {
        return E_INVALIDARG;
    }
    LPWSTR display_name = nullptr;
    const HRESULT hr = item->GetDisplayName(SIGDN_FILESYSPATH, &display_name);
    if (FAILED(hr) || display_name == nullptr) {
        return FAILED(hr) ? hr : E_FAIL;
    }
    path.assign(display_name);
    CoTaskMemFree(display_name);
    return path.empty() ? E_FAIL : S_OK;
}

HRESULT FolderFromView(IUnknown* view_unknown, std::wstring& path) {
    if (view_unknown == nullptr) {
        return E_FAIL;
    }
    IFolderView* folder_view = nullptr;
    if (SUCCEEDED(view_unknown->QueryInterface(kIidFolderView, reinterpret_cast<void**>(&folder_view))) &&
        folder_view != nullptr) {
        IShellItem* folder = nullptr;
        const HRESULT folder_hr = folder_view->GetFolder(kIidShellItem, reinterpret_cast<void**>(&folder));
        if (SUCCEEDED(folder_hr) && folder != nullptr) {
            DisplayNameOfItem(folder, path);
            folder->Release();
        }
        folder_view->Release();
    }
    if (!path.empty()) {
        return S_OK;
    }

    IPersistFolder2* persist = nullptr;
    if (SUCCEEDED(view_unknown->QueryInterface(kIidPersistFolder2, reinterpret_cast<void**>(&persist))) &&
        persist != nullptr) {
        PIDLIST_ABSOLUTE folder_pidl = nullptr;
        if (SUCCEEDED(persist->GetCurFolder(&folder_pidl)) && folder_pidl != nullptr) {
            wchar_t buffer[MAX_PATH * 4] = {};
            if (SHGetPathFromIDListW(folder_pidl, buffer)) {
                path.assign(buffer);
            }
            CoTaskMemFree(folder_pidl);
        }
        persist->Release();
    }
    return path.empty() ? E_FAIL : S_OK;
}

// 文件夹空白处触发时没有 IShellItem，只能从 Explorer 注入的 site 反查当前目录。
// 站点可能是 IShellBrowser、IShellView，或（新版本）只暴露 IServiceProvider；
// 三条路径都试，失败才返回 E_FAIL。
HRESULT FolderFromSite(IUnknown* site, std::wstring& path) {
    if (site == nullptr) {
        return E_FAIL;
    }

    IShellBrowser* browser = nullptr;
    if (SUCCEEDED(site->QueryInterface(kIidShellBrowser, reinterpret_cast<void**>(&browser))) &&
        browser != nullptr) {
        IShellView* view = nullptr;
        if (SUCCEEDED(browser->QueryActiveShellView(&view)) && view != nullptr) {
            FolderFromView(view, path);
            view->Release();
        }
        browser->Release();
    }
    if (!path.empty()) {
        return S_OK;
    }

    IServiceProvider* provider = nullptr;
    if (SUCCEEDED(site->QueryInterface(kIidServiceProvider, reinterpret_cast<void**>(&provider))) &&
        provider != nullptr) {
        IShellBrowser* service_browser = nullptr;
        if (SUCCEEDED(provider->QueryService(kSidShellBrowser, kIidShellBrowser,
                                             reinterpret_cast<void**>(&service_browser))) &&
            service_browser != nullptr) {
            IShellView* view = nullptr;
            if (SUCCEEDED(service_browser->QueryActiveShellView(&view)) && view != nullptr) {
                FolderFromView(view, path);
                view->Release();
            }
            service_browser->Release();
        }
        provider->Release();
    }
    if (!path.empty()) {
        return S_OK;
    }

    FolderFromView(site, path);
    return path.empty() ? E_FAIL : S_OK;
}


// IShellWindows 只用到 IDispatch 之后的 get_Count / Item 两个槽位（7、8）。
// 这里给出与真实 vtable 前缀一致的最小声明：只声明会被调用的两个方法，
// 其余槽位不声明也不调用（不实例化该接口，只做指针转换）。
struct IShellWindowsPrefix : public IDispatch {
    virtual HRESULT STDMETHODCALLTYPE get_Count(long* count) = 0;
    virtual HRESULT STDMETHODCALLTYPE Item(VARIANT index, IDispatch** folder) = 0;
};

// 兜底路径：经典菜单的右键站点有时不提供 IShellBrowser / IShellView，
// 此时按“前台 Explorer 窗口 → IServiceProvider → IShellBrowser → 活动视图”
// 反查当前文件夹。只在前台窗口能对应上时采用；窗口唯一时才退回首个窗口，
// 避免在多个资源管理器窗口时打开错误的目录。
HRESULT FolderFromShellWindows(std::wstring& path) {
    IShellWindowsPrefix* windows = nullptr;
    if (FAILED(CoCreateInstance(kClsidShellWindows, nullptr, CLSCTX_ALL, kIidShellWindows,
                                reinterpret_cast<void**>(&windows))) ||
        windows == nullptr) {
        return E_FAIL;
    }

    const HWND foreground = GetAncestor(GetForegroundWindow(), GA_ROOT);
    long count = 0;
    windows->get_Count(&count);

    std::wstring first_candidate;
    long mapped = 0;
    for (long index = 0; index < count && path.empty(); ++index) {
        VARIANT item_index;
        VariantInit(&item_index);
        item_index.vt = VT_I4;
        item_index.lVal = index;
        IDispatch* dispatch = nullptr;
        if (FAILED(windows->Item(item_index, &dispatch)) || dispatch == nullptr) {
            continue;
        }
        IServiceProvider* provider = nullptr;
        IShellBrowser* browser = nullptr;
        if (SUCCEEDED(dispatch->QueryInterface(kIidServiceProvider, reinterpret_cast<void**>(&provider))) &&
            provider != nullptr) {
            provider->QueryService(kSidTopLevelBrowser, kIidShellBrowser, reinterpret_cast<void**>(&browser));
            provider->Release();
        }
        if (browser == nullptr) {
            dispatch->QueryInterface(kIidShellBrowser, reinterpret_cast<void**>(&browser));
        }
        if (browser != nullptr) {
            HWND browser_window = nullptr;
            const bool matches_foreground =
                foreground != nullptr && SUCCEEDED(browser->GetWindow(&browser_window)) &&
                GetAncestor(browser_window, GA_ROOT) == foreground;
            std::wstring candidate;
            IShellView* view = nullptr;
            if (SUCCEEDED(browser->QueryActiveShellView(&view)) && view != nullptr) {
                FolderFromView(view, candidate);
                view->Release();
            }
            browser->Release();
            ++mapped;
            if (candidate.empty()) {
                continue;
            }
            if (matches_foreground) {
                path = candidate;
            } else if (first_candidate.empty()) {
                first_candidate = candidate;
            }
        }
        dispatch->Release();
    }
    windows->Release();

    if (path.empty() && mapped == 1 && !first_candidate.empty()) {
        path = first_candidate;
    }
    return path.empty() ? E_FAIL : S_OK;
}

// 诊断日志：资源管理器侧的右键菜单点击没有可见界面反馈，出问题只能靠日志定位。
// 写入 %LOCALAPPDATA%\Sopeek\data\logs\shell-ext.log（UTF-8，追加）。
void LogInvocation(const wchar_t* entry, const std::wstring& detail, HRESULT hr) {
    wchar_t local_app_data[MAX_PATH * 4] = {};
    const DWORD length =
        GetEnvironmentVariableW(L"LOCALAPPDATA", local_app_data, static_cast<DWORD>(sizeof(local_app_data) / sizeof(local_app_data[0])));
    if (length == 0 || length >= sizeof(local_app_data) / sizeof(local_app_data[0])) {
        return;
    }
    const std::wstring sopeek_root = std::wstring(local_app_data) + L"\\Sopeek";
    const std::wstring data_root = sopeek_root + L"\\data";
    const std::wstring log_root = data_root + L"\\logs";
    CreateDirectoryW(sopeek_root.c_str(), nullptr);
    CreateDirectoryW(data_root.c_str(), nullptr);
    CreateDirectoryW(log_root.c_str(), nullptr);

    SYSTEMTIME now;
    GetLocalTime(&now);
    wchar_t line[1024] = {};
    const int written_characters = swprintf_s(
        line, sizeof(line) / sizeof(line[0]), L"%04d-%02d-%02d %02d:%02d:%02d [%s] hr=0x%08lX %s\r\n",
        now.wYear, now.wMonth, now.wDay, now.wHour, now.wMinute, now.wSecond, entry,
        static_cast<unsigned long>(hr), detail.c_str());
    if (written_characters <= 0) {
        return;
    }

    const UINT utf8_bytes = WideCharToMultiByte(CP_UTF8, 0, line, written_characters, nullptr, 0, nullptr, nullptr);
    if (utf8_bytes == 0) {
        return;
    }
    std::string utf8(utf8_bytes, '\0');
    WideCharToMultiByte(CP_UTF8, 0, line, written_characters, &utf8[0], static_cast<int>(utf8.size()), nullptr, nullptr);

    const std::wstring log_path = log_root + L"\\shell-ext.log";
    HANDLE file = CreateFileW(log_path.c_str(), FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr,
                              OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) {
        return;
    }
    DWORD bytes_written = 0;
    WriteFile(file, utf8.data(), static_cast<DWORD>(utf8.size()), &bytes_written, nullptr);
    CloseHandle(file);
}


std::wstring QuoteArgument(const std::wstring& value) {
    return L"\"" + value + L"\"";
}

HRESULT LaunchSopeek(const std::wstring& path) {
    const std::wstring executable = ExecutablePath();
    if (executable.empty()) {
        return E_FAIL;
    }
    if (GetFileAttributesW(executable.c_str()) == INVALID_FILE_ATTRIBUTES) {
        // 记下实际算出来的路径：安装目录布局变了（或 DLL 与 Sopeek.exe 不在同一层）
        // 时，这是唯一能说明「点了没反应」原因的线索。
        LogInvocation(L"Launch", std::wstring(L"exe-missing ") + executable,
                      HRESULT_FROM_WIN32(ERROR_FILE_NOT_FOUND));
        return HRESULT_FROM_WIN32(ERROR_FILE_NOT_FOUND);
    }

    // path 为空表示没能确定目标目录：仍然把应用拉起来（启动到上次位置），
    // 好过点了菜单毫无反应。
    const std::wstring parameters =
        path.empty() ? std::wstring() : std::wstring(kArgumentName) + L" " + QuoteArgument(path);
    const HINSTANCE result = ShellExecuteW(nullptr, L"open", executable.c_str(), parameters.c_str(),
                                           nullptr, SW_SHOWNORMAL);
    // ShellExecuteW 的返回值 > 32 才算成功；失败时它把错误码放在返回值里。
    if (reinterpret_cast<INT_PTR>(result) <= 32) {
        return HRESULT_FROM_WIN32(static_cast<DWORD>(reinterpret_cast<INT_PTR>(result)));
    }
    return S_OK;
}

class SopeekExplorerCommand final : public IExplorerCommand, public IObjectWithSite {
public:
    SopeekExplorerCommand(bool folder_command, const CLSID& command_clsid)
        : folder_command_(folder_command), command_clsid_(command_clsid) {
        // COM 引用计数从 1 起算：DllGetClassObject/CreateInstance 会先
        // QueryInterface（AddRef）再把本地引用 Release 掉，调用方手里仍留 1。
        InterlockedIncrement(&g_lock_count);
        InterlockedIncrement(&g_object_count);
    }

    SopeekExplorerCommand(const SopeekExplorerCommand&) = delete;
    SopeekExplorerCommand& operator=(const SopeekExplorerCommand&) = delete;

    // IUnknown
    IFACEMETHODIMP QueryInterface(REFIID riid, void** result) override {
        if (result == nullptr) {
            return E_POINTER;
        }
        *result = nullptr;
        if (GuidEquals(riid, kIidUnknown) || GuidEquals(riid, kIidExplorerCommand)) {
            *result = static_cast<IExplorerCommand*>(this);
            AddRef();
            return S_OK;
        }
        if (GuidEquals(riid, kIidObjectWithSite)) {
            *result = static_cast<IObjectWithSite*>(this);
            AddRef();
            return S_OK;
        }
        return E_NOINTERFACE;
    }

    IFACEMETHODIMP_(ULONG) AddRef() override { return static_cast<ULONG>(InterlockedIncrement(&g_lock_count)); }

    IFACEMETHODIMP_(ULONG) Release() override {
        const ULONG remaining = static_cast<ULONG>(InterlockedDecrement(&g_lock_count));
        if (remaining == 0) {
            InterlockedDecrement(&g_object_count);
            delete this;
        }
        return remaining;
    }

    // IExplorerCommand
    IFACEMETHODIMP GetTitle(IShellItemArray* /*items*/, LPWSTR* title) override {
        return DuplicateString(folder_command_ ? kFolderTitle : kFileTitle, title);
    }

    IFACEMETHODIMP GetIcon(IShellItemArray* /*items*/, LPWSTR* icon) override {
        const std::wstring executable = ExecutablePath();
        if (executable.empty()) {
            return E_FAIL;
        }
        return DuplicateString(executable.c_str(), icon);
    }

    IFACEMETHODIMP GetToolTip(IShellItemArray* /*items*/, LPWSTR* /*tooltip*/) override { return E_NOTIMPL; }

    IFACEMETHODIMP GetCanonicalName(GUID* command_name) override {
        if (command_name == nullptr) {
            return E_POINTER;
        }
        *command_name = command_clsid_;
        return S_OK;
    }

    IFACEMETHODIMP GetState(IShellItemArray* /*items*/, WINBOOL /*ok_to_be_slow*/,
                            EXPCMDSTATE* state) override {
        if (state == nullptr) {
            return E_POINTER;
        }
        *state = ECS_ENABLED;
        return S_OK;
    }

    IFACEMETHODIMP Invoke(IShellItemArray* items, IBindCtx* /*bind_context*/) override {
        std::wstring target;
        DWORD item_count = 0;
        if (items != nullptr) {
            items->GetCount(&item_count);
            if (item_count > 0) {
                IShellItem* first = nullptr;
                if (SUCCEEDED(items->GetItemAt(0, &first)) && first != nullptr) {
                    DisplayNameOfItem(first, target);
                    first->Release();
                }
            }
        }
        const wchar_t* source = L"items";
        if (target.empty()) {
            source = L"site";
            FolderFromSite(site_, target);
        }
        if (target.empty()) {
            source = L"shellwindows";
            FolderFromShellWindows(target);
        }

        const HRESULT launched = LaunchSopeek(target);
        wchar_t detail[768] = {};
        swprintf_s(detail, sizeof(detail) / sizeof(detail[0]),
                   L"%s source=%s items=%lu site=%d target=%ls", folder_command_ ? L"folder" : L"file", source,
                   static_cast<unsigned long>(item_count), site_ != nullptr ? 1 : 0,
                   target.empty() ? L"<none>" : target.c_str());
        LogInvocation(L"Invoke", detail, launched);
        return launched;
    }

    IFACEMETHODIMP GetFlags(EXPCMDFLAGS* flags) override {
        if (flags == nullptr) {
            return E_POINTER;
        }
        *flags = static_cast<EXPCMDFLAGS>(0);
        return S_OK;
    }

    IFACEMETHODIMP EnumSubCommands(IEnumExplorerCommand** enumerator) override {
        if (enumerator != nullptr) {
            *enumerator = nullptr;
        }
        return E_NOTIMPL;
    }

    // IObjectWithSite
    IFACEMETHODIMP SetSite(IUnknown* site) override {
        if (site_ != nullptr) {
            site_->Release();
            site_ = nullptr;
        }
        site_ = site;
        if (site_ != nullptr) {
            site_->AddRef();
        }
        return S_OK;
    }

    IFACEMETHODIMP GetSite(REFIID riid, void** site) override {
        if (site == nullptr) {
            return E_POINTER;
        }
        *site = nullptr;
        if (site_ == nullptr) {
            return E_FAIL;
        }
        return site_->QueryInterface(riid, site);
    }

private:
    ~SopeekExplorerCommand() {
        if (site_ != nullptr) {
            site_->Release();
            site_ = nullptr;
        }
    }

    bool folder_command_;
    CLSID command_clsid_;
    IUnknown* site_ = nullptr;
};

class SopeekClassFactory final : public IClassFactory {
public:
    SopeekClassFactory(bool folder_command, const CLSID& command_clsid)
        : folder_command_(folder_command), command_clsid_(command_clsid) {
        // 与命令对象一致：构造函数即持有一个引用（见 SopeekExplorerCommand）。
        InterlockedIncrement(&g_lock_count);
        InterlockedIncrement(&g_object_count);
    }

    SopeekClassFactory(const SopeekClassFactory&) = delete;
    SopeekClassFactory& operator=(const SopeekClassFactory&) = delete;

    IFACEMETHODIMP QueryInterface(REFIID riid, void** result) override {
        if (result == nullptr) {
            return E_POINTER;
        }
        *result = nullptr;
        if (GuidEquals(riid, kIidUnknown) || GuidEquals(riid, kIidClassFactory)) {
            *result = static_cast<IClassFactory*>(this);
            AddRef();
            return S_OK;
        }
        return E_NOINTERFACE;
    }

    IFACEMETHODIMP_(ULONG) AddRef() override { return static_cast<ULONG>(InterlockedIncrement(&g_lock_count)); }

    IFACEMETHODIMP_(ULONG) Release() override {
        const ULONG remaining = static_cast<ULONG>(InterlockedDecrement(&g_lock_count));
        if (remaining == 0) {
            InterlockedDecrement(&g_object_count);
            delete this;
        }
        return remaining;
    }

    IFACEMETHODIMP CreateInstance(IUnknown* outer, REFIID riid, void** result) override {
        if (outer != nullptr) {
            return CLASS_E_NOAGGREGATION;
        }
        SopeekExplorerCommand* command = new (std::nothrow) SopeekExplorerCommand(folder_command_, command_clsid_);
        if (command == nullptr) {
            return E_OUTOFMEMORY;
        }
        const HRESULT hr = command->QueryInterface(riid, result);
        command->Release();
        return hr;
    }

    IFACEMETHODIMP LockServer(BOOL lock) override {
        if (lock) {
            InterlockedIncrement(&g_object_count);
        } else {
            InterlockedDecrement(&g_object_count);
        }
        return S_OK;
    }

private:
    ~SopeekClassFactory() = default;

    bool folder_command_;
    CLSID command_clsid_;
};

}  // namespace

BOOL APIENTRY DllMain(HMODULE module, DWORD reason, LPVOID /*reserved*/) {
    if (reason == DLL_PROCESS_ATTACH) {
        g_module_instance = module;
        DisableThreadLibraryCalls(module);
    }
    return TRUE;
}

extern "C" __declspec(dllexport) HRESULT STDAPICALLTYPE DllCanUnloadNow() {
    // 只有既没有活动对象、也没有 LockServer 锁时才允许卸载。
    return (g_object_count == 0 && g_lock_count == 0) ? S_OK : S_FALSE;
}

extern "C" __declspec(dllexport) HRESULT STDAPICALLTYPE DllGetClassObject(REFCLSID clsid, REFIID riid,
                                                                          void** result) {
    if (result == nullptr) {
        return E_POINTER;
    }
    *result = nullptr;
    if (!GuidEquals(riid, kIidClassFactory) && !GuidEquals(riid, kIidUnknown)) {
        return E_NOINTERFACE;
    }

    bool folder_command = false;
    if (IsFolderClsid(clsid)) {
        folder_command = true;
    } else if (!IsFileClsid(clsid)) {
        return CLASS_E_CLASSNOTAVAILABLE;
    }

    SopeekClassFactory* factory = new (std::nothrow) SopeekClassFactory(folder_command, clsid);
    if (factory == nullptr) {
        return E_OUTOFMEMORY;
    }
    const HRESULT hr = factory->QueryInterface(riid, result);
    factory->Release();
    return hr;
}

