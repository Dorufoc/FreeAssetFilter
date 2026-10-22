//
// installer_window.cpp - 无边框 DirectComposition 窗口外壳实现（Todo 2）。
//
// Frozen contracts（不得另行发明）：§4 窗口配方 / §5 Mica 透明度 / §6 DPI /
// §10 消息与进度 / §12 app_state.h / §13 资源所有权。
//
#include "installer_window.h"

#include <d2d1_1helper.h>
#include <shlobj.h>
#include <tlhelp32.h>  // T11：已安装应用运行探测（CreateToolhelp32Snapshot）
#include <uxtheme.h>  // MARGINS（须先于 dwmapi.h）
#include <dwmapi.h>

#include <algorithm>
#include <filesystem>

#include "process_control.h"  // T11/D9：按完整路径关闭已安装应用
#include "render/maintenance_protocol.h"  // T11：kAppExeName（唯一常量来源）
#include "render/messages.h"  // §10：WM_INSTALL_PROGRESS/DONE + WM_UI_TICK
#include "render/install_engine.h"  // Todo 13：真实安装引擎（§1/§3/§10/§11 唯一实现）
#include "render/launch_forward.h"  // Todo 15：§15 去提权启动（唯一 owner）
// Todo 12：把 Todo 9/10/11 的页文件接入外壳（仅接线，不改页内部实现）。
#include "render/pages_maintenance.h"  // T10：Maintenance/UninstallConfirm/Message 页
#include "render/pages_progress.h"     // Progress/Finish 页
#include "render/pages_setup.h"        // Location/Options 页
#include "render/pages_welcome.h"      // Welcome/License 页
#include "uninstall_coordinator.h"     // T12：卸载协调器（request/helper/result 轮询）
#include "uninstall_protocol.h"        // T11：WriteMaintenanceDecision（D3 终端键）

namespace fs = std::filesystem;

namespace {

// 追加需求（2026-10-18）：顶部横向 3 节点进度带【协议】【配置】【部署】。
// 欢迎/完成页为英雄页（无步骤区、无底部导航）。
constexpr const wchar_t* kStepLabels[3] = {L"协议", L"配置", L"部署"};
// Todo 12：底部导航按钮尺寸（DIP）。中心落在 bottomBar 垂直中线。
constexpr float kNavButtonW = 112.0f;
constexpr float kNavButtonH = 36.0f;
constexpr float kNavBackCenterX = 680.0f;  // 上一步按钮中心 X（DIP）
constexpr float kNavNextCenterX = 816.0f;  // 下一步按钮中心 X（DIP）
// UI-fix：页托管底部条按钮（取消 / 完成）的统一几何（画布 DIP）。
// 页坐标 = 画布 + shadowMarginDip_（Win10 兜底外扩边距；页 Render 用 Identity 变换）。
constexpr float kFooterRightEdgeX = 872.0f;  // 页操作按钮右缘（画布）
constexpr float kCancelButtonW = 96.0f;      // 「取消」宽度
constexpr int kStepCount = 3;

// T12：UninstallStage → Progress 页阶段文案（wParam/lParam 只传枚举，中文只在此映射）。
const wchar_t* UninstallStageLabel(faf::UninstallStage stage) {
    switch (stage) {
        case faf::UninstallStage::Started: return L"准备卸载";
        case faf::UninstallStage::RemovingShortcuts: return L"正在删除快捷方式";
        case faf::UninstallStage::RemovingRegistry: return L"正在清理注册表";
        case faf::UninstallStage::RemovingFiles: return L"正在删除程序文件";
        case faf::UninstallStage::RemovingUserData: return L"正在清理用户数据";
        case faf::UninstallStage::Done: return L"卸载完成";
        case faf::UninstallStage::Failed: return L"卸载失败";
        case faf::UninstallStage::Cancelled: return L"卸载已取消";
    }
    return L"正在卸载";
}

bool IsKnownUninstallStage(int value) {
    return value >= static_cast<int>(faf::UninstallStage::Started) &&
           value <= static_cast<int>(faf::UninstallStage::Cancelled);
}

bool IsTerminalUninstallStage(int value) {
    return value == static_cast<int>(faf::UninstallStage::Done) ||
           value == static_cast<int>(faf::UninstallStage::Failed) ||
           value == static_cast<int>(faf::UninstallStage::Cancelled);
}
}  // namespace

namespace {

// 关闭按钮背景填充：Windows 标准关闭键色。theme.h 是不可变 token 表（§13），
// 故此处仅本地局部色板（不进 Theme），不与既有 token 体系冲突。
//   悬停 #C42B1C（196,43,28）/ 按下 #B0251A（176,37,26，略深）。
D2D1_COLOR_F CloseHoverRed() { return D2D1::ColorF(0.769f, 0.169f, 0.110f, 1.0f); }
D2D1_COLOR_F CloseArmedRed() { return D2D1::ColorF(0.690f, 0.145f, 0.102f, 1.0f); }
}  // namespace

namespace {

constexpr wchar_t kWindowClass[] = L"FreeAssetFilterInstaller";  // §4 冻结类名
// T10：标题按启动模式设置（自绘标题栏与 CreateWindowExW 共用同一来源）。
constexpr wchar_t kTitleInstall[] = L"FreeAssetFilter 安装程序";
constexpr wchar_t kTitleMaintenance[] = L"FreeAssetFilter 维护";
constexpr wchar_t kTitleUninstall[] = L"FreeAssetFilter 卸载";
constexpr UINT_PTR kTickTimerId = 1;
constexpr UINT kTickIntervalMs = 16;      // §2 主循环 ~16ms 驱动动画 tick
constexpr int kWin10ShadowMarginDip = 12; // §4 Win10 兜底透明外扩边距（DIP）
constexpr ULONGLONG kProgressPostIntervalMs = 33;  // §10：进度 PostMessage 节流 ~30fps
#ifdef FAF_TESTMODE
// Todo 19（§17）：/auto 测试驱动常量——仅测试构建编入（生产零残留）。
constexpr UINT_PTR kAutoTimerId = 2;  // 驱动定时器（独立于 ~16ms 动画 tick）
constexpr UINT kAutoStepMs = 700;     // 固定步进间隔（无人值守取证时序可复现）
#endif

// §6：逻辑画布尺寸（DIP）——唯一来源为 layout.h，不再内联硬编码（亦不得用旧 720x480）。
constexpr int kCanvasW = static_cast<int>(faf::layout::kCanvasWidth);
constexpr int kCanvasH = static_cast<int>(faf::layout::kCanvasHeight);

// T10：启动模式 → 窗口标题（唯一映射点；构造期写入 windowTitle_）。
const wchar_t* TitleForMode(AppMode mode) {
    switch (mode) {
        case AppMode::Maintenance: return kTitleMaintenance;
        case AppMode::Uninstall: return kTitleUninstall;
        case AppMode::Install:
        default: return kTitleInstall;
    }
}

std::string WideToUtf8(const std::wstring& text) {
    if (text.empty()) return {};
    const int size = WideCharToMultiByte(CP_UTF8, 0, text.c_str(), static_cast<int>(text.size()),
                                         nullptr, 0, nullptr, nullptr);
    if (size <= 0) return {};
    std::string out(static_cast<size_t>(size), '\0');
    WideCharToMultiByte(CP_UTF8, 0, text.c_str(), static_cast<int>(text.size()), out.data(), size,
                        nullptr, nullptr);
    return out;
}

std::wstring ToHex(DWORD value) {
    const wchar_t* digits = L"0123456789ABCDEF";
    std::wstring out = L"0x";
    for (int shift = 28; shift >= 0; shift -= 4) out.push_back(digits[(value >> shift) & 0xF]);
    return out;
}

// 无条件运行时诊断落盘（仅当设置 FAF_DIAG_PATH 时写入；未设置时不影响默认行为）。
// 与 FAF_FORCE_WARP / FAF_PAYLOAD_TIMEOUT_MS 同性质，非 FAF_TESTMODE 门闩。
// 底层接受已是 UTF-8 的一行（§16 动画采样行直接走此入口）。
void DiagLogRaw(const std::string& utf8Line) {
    wchar_t path[MAX_PATH] = {};
    const DWORD n = GetEnvironmentVariableW(L"FAF_DIAG_PATH", path, static_cast<DWORD>(ARRAYSIZE(path)));
    if (n == 0 || n >= ARRAYSIZE(path)) return;
    HANDLE file = CreateFileW(path, FILE_APPEND_DATA, FILE_SHARE_READ, nullptr, OPEN_ALWAYS,
                              FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return;
    const std::string utf8 = utf8Line + "\r\n";
    DWORD written = 0;
    SetFilePointer(file, 0, nullptr, FILE_END);
    WriteFile(file, utf8.data(), static_cast<DWORD>(utf8.size()), &written, nullptr);
    CloseHandle(file);
}

void DiagLog(const std::wstring& line) { DiagLogRaw(WideToUtf8(line)); }

// T11：把路径归一化为可比较的绝对长路径（去掉 `\\?\` 前缀，统一小写比较交由
// CompareStringOrdinal(..., TRUE) 完成，不在此改写大小写）。
std::wstring NormalizedPath(const std::wstring& path) {
    wchar_t full[MAX_PATH] = {};
    if (GetFullPathNameW(path.c_str(), ARRAYSIZE(full), full, nullptr) == 0) {
        return path;
    }
    wchar_t longPath[MAX_PATH] = {};
    std::wstring result = full;
    if (GetLongPathNameW(full, longPath, ARRAYSIZE(longPath)) > 0) result = longPath;
    if (result.rfind(L"\\\\?\\", 0) == 0) result.erase(0, 4);
    while (result.size() > 3 && (result.back() == L'\\' || result.back() == L'/')) result.pop_back();
    return result;
}

// T11：探测 `<installDir>\FreeAssetFilter.exe` 是否在运行。
//
// 为什么窗口侧另做一次探测：process_control.h（T3）只暴露“关闭”入口，没有只读
// 探测 API，而 T11 必须区分两条路径 —— 未运行 → 直接写 decision 开始修复；运行中
// → 先异步关闭，**关闭成功后**才允许写 decision。匹配口径与 faf::CloseInstalledApp
// 保持一致：先按映像名预筛，再用 QueryFullProcessImageNameW 取完整路径做大小写不
// 敏感比较，绝不按映像名单独判定（避免误判/误关其它目录的同名 exe）。
bool IsInstalledAppRunning(const std::wstring& installDir) {
    if (installDir.empty()) return false;
    const std::wstring target =
        NormalizedPath(installDir + L"\\" + faf::protocol::kAppExeName);
    if (target.empty()) return false;

    HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snapshot == INVALID_HANDLE_VALUE) return false;
    PROCESSENTRY32W entry{};
    entry.dwSize = sizeof(entry);
    bool running = false;
    if (Process32FirstW(snapshot, &entry)) {
        do {
            if (CompareStringOrdinal(entry.szExeFile, -1, faf::protocol::kAppExeName, -1, TRUE) !=
                CSTR_EQUAL) {
                continue;
            }
            HANDLE process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE,
                                         entry.th32ProcessID);
            if (!process) continue;
            wchar_t image[MAX_PATH] = {};
            DWORD size = ARRAYSIZE(image);
            if (QueryFullProcessImageNameW(process, 0, image, &size)) {
                if (CompareStringOrdinal(NormalizedPath(image).c_str(), -1, target.c_str(), -1,
                                         TRUE) == CSTR_EQUAL) {
                    running = true;
                }
            }
            CloseHandle(process);
            if (running) break;
        } while (Process32NextW(snapshot, &entry));
    }
    CloseHandle(snapshot);
    return running;
}

bool AppsUseLightTheme() {
    DWORD value = 1;
    DWORD size = sizeof(value);
    DWORD type = 0;
    HKEY key = nullptr;
    if (RegOpenKeyExW(HKEY_CURRENT_USER,
                      L"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize", 0,
                      KEY_READ, &key) == ERROR_SUCCESS) {
        RegQueryValueExW(key, L"AppsUseLightTheme", nullptr, &type,
                         reinterpret_cast<LPBYTE>(&value), &size);
        RegCloseKey(key);
    }
    return value != 0;
}

// §5/Todo 4：真实 OS build 判定。`GetVersionEx` 在无 manifest 时会撒谎（返回 6.2），
// 故经 `ntdll!RtlGetVersion` 取真实 build。返回 true 表示 build >= 22621（Win11 Mica 可用）。
bool WindowsBuild22621OrLater() {
    using RtlGetVersionFn = LONG(WINAPI*)(void*);
    HMODULE ntdll = GetModuleHandleW(L"ntdll.dll");
    if (!ntdll) return false;
    auto rtlGetVersion = reinterpret_cast<RtlGetVersionFn>(GetProcAddress(ntdll, "RtlGetVersion"));
    if (!rtlGetVersion) return false;
    // 布局等价于 RTL_OSVERSIONINFOW（MinGW 头未稳定导出该名，故本就地定义）。
    struct OsVersionInfo {
        ULONG size;
        ULONG major;
        ULONG minor;
        ULONG build;
        ULONG platform;
        WCHAR csd[128];
    } vi{};
    vi.size = sizeof(vi);
    if (rtlGetVersion(&vi) != 0) return false;  // STATUS_SUCCESS == 0
    DiagLog(L"os build=" + std::to_wstring(vi.build));
    return vi.major >= 10 && vi.build >= 22621;
}

}  // namespace

InstallerWindow::InstallerWindow(HINSTANCE instance, std::wstring payload, std::wstring resultPath,
                                 std::wstring installDir, AppMode mode, std::wstring decisionPath,
                                 DWORD setupPid, std::uint64_t payloadTimeoutMs, DWORD helperPid,
                                 std::wstring uninstallRequestPath,
                                 std::wstring uninstallResultPath)
    : instance_(instance),
      payload_(std::move(payload)),
      resultPath_(std::move(resultPath)),
      mode_(mode),
      decisionPath_(std::move(decisionPath)),
      helperPid_(helperPid),
      uninstallRequestPath_(std::move(uninstallRequestPath)),
      uninstallResultPath_(std::move(uninstallResultPath)),
      setupPid_(setupPid),
      payloadTimeoutMs_(payloadTimeoutMs) {
    // §15/Todo 15：/installdir（重装预填）优先。产品默认目录只属于安装模式；
    // 维护/卸载缺少 /installdir 时由 main.cpp 从当前 exe 父目录推导（C4）。这里
    // 绝不再对非安装模式回退 Program Files，否则直接卸载可能指向错误目录。
    if (!installDir.empty()) {
        state_.installDir = std::move(installDir);
    } else if (mode_ == AppMode::Install) {
        state_.installDir = L"C:\\Program Files\\FreeAssetFilter";
    }
    // C4：非安装模式若仍拿到空 installDir，交由既有 startup-error 路径失败关闭；
    // 同时不得拼出 `\uninstall-request.ini` 这类根路径。
    if (mode_ != AppMode::Install && state_.installDir.empty()) {
        startupErrorTitle_ = L"无法确定安装目录";
        startupErrorBody_ =
            L"未提供 /installdir，且无法从当前程序位置推导安装目录。操作已取消。";
        exitCode_ = 1;
        maintenanceSuppressDecision_ = true;
    }
    // T12：未显式传路径时按 installDir 推导（D5：文件固定在安装目录）。
    if (!state_.installDir.empty()) {
        if (uninstallRequestPath_.empty()) {
            uninstallRequestPath_ =
                state_.installDir + L"\\" + faf::protocol::kUninstallRequestFile;
        }
        if (uninstallResultPath_.empty()) {
            uninstallResultPath_ =
                state_.installDir + L"\\" + faf::protocol::kUninstallResultFile;
        }
    }
    UpdateWindowTitle();  // T13：windowTitle_ 初始化（window_ 尚为空，仅落字符串）
    // T11/D9：setup 退出 watchdog —— 只监视（SYNCHRONIZE），绝不终止 setup 进程。
    // 打开失败（PID 已消失/无权限）时保持空句柄：此时无法区分“PID 无效”和“setup 已
    // 退出”，贸然中止会误杀正常安装；wait-for-payload 的最终超时仍由 NSIS 侧兜底。
    if (setupPid_ != 0) {
        setupProcess_ = OpenProcess(SYNCHRONIZE, FALSE, setupPid_);
        DiagLog(L"setup watchdog pid=" + std::to_wstring(setupPid_) + L" opened=" +
                std::to_wstring(setupProcess_ ? 1 : 0));
    }
    // §16：生产动画采样 sink = 既有 DiagLog（env 门控，未设置时 no-op）。
    animator_.SetSink([](const std::string& line) { DiagLogRaw(line); });
}

InstallerWindow::~InstallerWindow() {
    DiagLog(L"destructor begin");
    // T12：先停协调器（worker 可能在轮询并 PostMessage），再收尾关闭线程/句柄。
    uninstallCoordinator_.reset();
    // T13：异常销毁路径下安装 worker 可能仍存活（它通过 this 访问引擎/错误槽并
    // PostMessage）。先取消并显式 join，再拆页面/停渲染，避免 use-after-free。
    FinishInstallThread();
    // T11：跨线程句柄必须先收尾——关闭应用的工作线程可能仍在 faf::CloseInstalledApp
    // 内运行并访问本对象成员（closeTargetDir_/closeMutex_），因此在拆页面/停渲染之前
    // join；setup watchdog 的进程句柄同样在此关闭（CloseHandle 不终止 setup）。
    FinishCloseThread();
    if (setupProcess_) {
        CloseHandle(setupProcess_);
        setupProcess_ = nullptr;
    }
    // Todo 12 / T10：页面持 COM 对象（LicenseBox 的 IDWriteTextLayout 等），必须在
    // render_.Shutdown()（含 CoUninitialize）之前析构，避免在失效 COM 单元上 Release。
    // 新增的英雄页同样先于 COM 拆卸。
    maintenancePage_.reset();
    uninstallConfirmPage_.reset();
    messagePage_.reset();
    welcomePage_.reset();
    licensePage_.reset();
    configurePage_.reset();
    progressPage_.reset();
    finishPage_.reset();
    DiagLog(L"destructor before render shutdown");
    // render_ 声明在 shellHost_/控件之前，析构顺序为后者先于 render_。显式 Shutdown
    // 会在这些成员仍持有 D2D/DWrite 资源时拆掉 COM 单元，导致关闭时访问冲突；
    // 统一交给 ~RenderContext() 在其余成员析构后执行一次。
    DiagLog(L"destructor end");
}

int InstallerWindow::Run() {
    if (!CreateAppWindow()) return 1;
    MSG msg{};
    while (GetMessageW(&msg, nullptr, 0, 0) > 0) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }
    DiagLog(L"run loop exited wparam=" + std::to_wstring(msg.wParam));
    return static_cast<int>(msg.wParam);
}

void InstallerWindow::SetStartupError(std::wstring title, std::wstring body) {
    startupErrorTitle_ = std::move(title);
    startupErrorBody_ = std::move(body);
    exitCode_ = 1;
    // 双保险：startup error 的 WM_CLOSE 分支本身不写任何协议，这里同时屏蔽维护
    // decision（防止任何意外路径经 OnMaintenanceCloseIntent 补写 cancel）。
    maintenanceSuppressDecision_ = true;
    DiagLog(L"startup error set title=" + startupErrorTitle_);
}

bool InstallerWindow::CreateAppWindow() {
    INITCOMMONCONTROLSEX ic{sizeof(ic), ICC_PROGRESS_CLASS};
    InitCommonControlsEx(&ic);

    WNDCLASSW wc{};
    wc.hInstance = instance_;
    wc.lpfnWndProc = WindowProc;
    wc.lpszClassName = kWindowClass;
    wc.hCursor = LoadCursor(nullptr, IDC_ARROW);
    wc.hbrBackground = nullptr;
    // §13：图标资源 id 与 app.rc 的 IDI_APP 保持一致（显式数值 100；1 属于 VERSIONINFO）。
    wc.hIcon = LoadIconW(instance_, MAKEINTRESOURCEW(100));
    RegisterClassW(&wc);

    UINT sysDpi = GetDpiForSystem();
    dpi_ = sysDpi ? sysDpi : 96;

    const int widthPx = MulDiv(kCanvasW, static_cast<int>(dpi_), 96);
    const int heightPx = MulDiv(kCanvasH, static_cast<int>(dpi_), 96);
    RECT work{};
    SystemParametersInfoW(SPI_GETWORKAREA, 0, &work, 0);
    const int left = work.left + (work.right - work.left - widthPx) / 2;
    const int top = work.top + (work.bottom - work.top - heightPx) / 2;

    // §4：WS_OVERLAPPEDWINDOW & ~WS_MAXIMIZEBOX + WS_EX_NOREDIRECTIONBITMAP。
    const DWORD style = WS_OVERLAPPEDWINDOW & ~WS_MAXIMIZEBOX;
    const DWORD exStyle = WS_EX_APPWINDOW | WS_EX_NOREDIRECTIONBITMAP;
    window_ = CreateWindowExW(exStyle, kWindowClass, windowTitle_.c_str(), style, left, top,
                              widthPx, heightPx, nullptr, nullptr, instance_, this);
    if (!window_) return false;
    UpdateWindowTitle();  // T13：原生标题与自绘标题栏共用 windowTitle_

    UINT windowDpi = GetDpiForWindow(window_);  // §6：窗口 DPI 用 GetDpiForWindow
    if (windowDpi) dpi_ = windowDpi;

    // §4：DWM 会因 DwmExtendFrameIntoClientArea 在扩展帧上自绘系统按钮（— □ ✕）。
    // 清除 WS_SYSMENU 撤下它们（保留 WS_CAPTION/WS_THICKFRAME 以维持原生最大化动画与 Aero Snap）。
    const LONG_PTR styleNow = GetWindowLongPtrW(window_, GWL_STYLE);
    SetWindowLongPtrW(window_, GWL_STYLE, styleNow & ~WS_SYSMENU);

    InstallDwmEffects();  // 决定 cornerOk_/backdropOk_/extendOk_/win10Fallback_/shadowMarginDip_

    // Win10 兜底向外扩透明边距；Win11 保持 900x600 DIP 精确物理尺寸。
    const int marginPx = MarginPx();
    const int finalW = MulDiv(kCanvasW, static_cast<int>(dpi_), 96) + 2 * marginPx;
    const int finalH = MulDiv(kCanvasH, static_cast<int>(dpi_), 96) + 2 * marginPx;

    // §16 + 减少动画：读 SPI_GETCLIENTAREAANIMATION 必须早于 OnSizeChanged()/EnsurePages()——
    // Animator::SetReduceMotion 只影响其后创建的动画，而页面入场动画（page-welcome-enter /
    // page-license-enter / step2.emph）在 EnsurePages 内烘焙；晚调用会让 boot 动画保留全额时长。
    ApplyReduceMotion();

    // SWP_FRAMECHANGED 强制重算帧 → 触发 WM_NCCALCSIZE(wParam=TRUE)，客户区归零（§4）。
    SetWindowPos(window_, nullptr, left - marginPx, top - marginPx, finalW, finalH,
                 SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED);

    Layout();

    RECT client{};
    GetClientRect(window_, &client);
    OnSizeChanged(static_cast<UINT>(client.right), static_cast<UINT>(client.bottom));

    if (payload_.empty()) payload_ = L".";
    std::error_code ec;
    if (!fs::exists(fs::path(payload_), ec)) {
        errorText_ = L"错误：未找到安装载荷目录：" + payload_;
    }

    // --- 证据用诊断（无 FAF_DIAG_PATH 时不产生任何副作用）---
    wchar_t className[64] = {};
    GetClassNameW(window_, className, ARRAYSIZE(className));
    const DWORD ex = static_cast<DWORD>(GetWindowLongPtrW(window_, GWL_EXSTYLE));
    const DWORD st = static_cast<DWORD>(GetWindowLongPtrW(window_, GWL_STYLE));
    RECT wr{};
    GetWindowRect(window_, &wr);
    DiagLog(std::wstring(L"window class=") + className + L" style=" + ToHex(st) + L" exstyle=" +
            ToHex(ex) + L" noredirbitmap=" + std::to_wstring((ex & WS_EX_NOREDIRECTIONBITMAP) ? 1 : 0) +
            L" rect=" + std::to_wstring(wr.right - wr.left) + L"x" + std::to_wstring(wr.bottom - wr.top) +
            L" dpi=" + std::to_wstring(dpi_));
    DiagLog(std::wstring(L"payload_exists=") + std::to_wstring(errorText_.empty() ? 1 : 0));
    // Todo 15 证据：/installdir 解析值（或默认值）已进入共享状态（Location 页数据源）。
    DiagLog(L"state installDir=" + state_.installDir);

    ShowWindow(window_, SW_SHOW);
    UpdateWindow(window_);

    // §16 + 减少动画：SPI_GETCLIENTAREAANIMATION 已在上方 SetWindowPos 之前读取
    // （ApplyReduceMotion 必须先于 OnSizeChanged()/EnsurePages()），此处不再重复调用；
    // 下方 shellIntro/RequestAnimTick 的 if (!reduceMotion_) 门控依赖 reduce_motion_ 已就绪。
    //
    // 外壳入场动画（0→1，~300ms，WinUI3 Entrance 曲线）——本 todo 的接线在此被真实驱动：
    // WM_TIMER → animator_.Tick() → Render()（dirty 或动画中）→ PresentFrame → Commit。
    // 减少动画时不创建（introAlpha_ 保持 1，立即全不透明，无中间 tick）。
    if (!reduceMotion_) {
        introAnim_ = &animator_.Animate("shellIntro", 0.0f, 1.0f, 300.0f, faf::easing::Entrance);
    }
    dirty_ = true;
    Render();
    if (!reduceMotion_) RequestAnimTick();  // 有活动动画 → 武装 tick 定时器
#ifdef FAF_TESTMODE
    // Todo 19（§17）：/auto 测试驱动——窗口/页面就绪后武装固定时序定时器（生产不编入）。
    if (autoDriveEnabled_) ArmAutoDrive();
#endif
    return true;
}

void InstallerWindow::InstallDwmEffects() {
    darkMode_ = !AppsUseLightTheme();
    BOOL dark = darkMode_ ? TRUE : FALSE;
    const HRESULT darkHr =
        DwmSetWindowAttribute(window_, DWMWA_USE_IMMERSIVE_DARK_MODE, &dark, sizeof(dark));

    // §4 圆角；失败 ⇒ Win10 兜底（不用 SetWindowRgn，改透明外扩边距 + DComp 自绘阴影）。
    DWM_WINDOW_CORNER_PREFERENCE pref = DWMWCP_ROUND;
    cornerOk_ = SUCCEEDED(DwmSetWindowAttribute(window_, DWMWA_WINDOW_CORNER_PREFERENCE, &pref,
                                                sizeof(pref)));

    // §5/Todo 4：Mica backdrop 仅在 build >= 22621 时尝试；更旧的系统（Win10）**不得**
    // 强设该未知 DWMWA，必须静默跳过。backdrop 失败或旧系统 ⇒ 走与 §4 相同的 Win10 兜底分支。
    backdropBuildOk_ = WindowsBuild22621OrLater();
    if (backdropBuildOk_) {
        DWM_SYSTEMBACKDROP_TYPE backdrop = DWMSBT_MAINWINDOW;
        backdropOk_ = SUCCEEDED(DwmSetWindowAttribute(window_, DWMWA_SYSTEMBACKDROP_TYPE, &backdrop,
                                                      sizeof(backdrop)));
    } else {
        backdropOk_ = false;  // build<22621：不设置该属性（Win10 静默跳过）
    }
    win10Fallback_ = !cornerOk_ || !backdropOk_;
    shadowMarginDip_ = win10Fallback_ ? kWin10ShadowMarginDip : 0;

    // §4 候选：帧扩展，使 Mica 覆盖客户区；由冒烟实测裁决保留或忽略。
    MARGINS margins{-1, -1, -1, -1};
    extendOk_ = SUCCEEDED(DwmExtendFrameIntoClientArea(window_, &margins));

    DiagLog(L"dwm build22621=" + std::to_wstring(backdropBuildOk_ ? 1 : 0) + L" corner=" +
            std::to_wstring(cornerOk_ ? 1 : 0) + L" backdrop=" +
            std::to_wstring(backdropOk_ ? 1 : 0) + L" darkHr=" +
            ToHex(static_cast<DWORD>(darkHr)) + L" extend=" + std::to_wstring(extendOk_ ? 1 : 0) +
            L" dark=" + std::to_wstring(darkMode_ ? 1 : 0) + L" win10fallback=" +
            std::to_wstring(win10Fallback_ ? 1 : 0));
}

void InstallerWindow::ApplyDarkMode(bool dark) {
    darkMode_ = dark;
    BOOL flag = dark ? TRUE : FALSE;
    DwmSetWindowAttribute(window_, DWMWA_USE_IMMERSIVE_DARK_MODE, &flag, sizeof(flag));
    dirty_ = true;
}

void InstallerWindow::RefreshSystemTheme() {
    const bool dark = !AppsUseLightTheme();
    if (dark != darkMode_) {
        ApplyDarkMode(dark);  // §5：重设 DWMWA_USE_IMMERSIVE_DARK_MODE
        DiagLog(L"system theme switch dark=" + std::to_wstring(dark ? 1 : 0));
    } else {
        dirty_ = true;  // 主题未变也重绘（DWM 颜色化可能改变 Mica 色调）
    }
    Render();
}

void InstallerWindow::UpdateWindowTitle() {
    // T13：标题唯一映射仍在 TitleForMode()；本函数只负责把同一字符串同时写入
    // 自绘标题栏数据源与原生窗口（任务栏/Alt+Tab）。窗口未创建时仅更新字符串。
    windowTitle_ = TitleForMode(mode_);
    if (window_) SetWindowTextW(window_, windowTitle_.c_str());
}

void InstallerWindow::Layout() {
    // §6：shell 几何唯一来源 = faf::ComputeShellLayout(bool hero)（纯 DIP 计算，不依赖 DPI）。
    // 标题栏最小化/关闭命中区、步骤带、内容卡片、底部条均由该结果提供。
    // 模式由当前页 + 操作类型决定（英雄页 欢迎/完成/维护/卸载确认/消息 无步骤带/底部条；
    // Repair/Uninstall 复用 Progress/Finish 时也必须是英雄页几何——与 SetPage 同一判据）。
    shellLayout_ = faf::ComputeShellLayout(faf::IsHeroPage(state_.page) ||
                                           state_.operation != Operation::Install);
    // Todo 12：shell 几何变化后重排步骤栏/导航按钮/当前页（页面构造前为空操作）。
    if (pagesReady_) {
        LayoutStepBar();
        LayoutFooterButtons();
        LayoutPages();
    }
}

int InstallerWindow::MarginPx() const {
    return MulDiv(shadowMarginDip_, static_cast<int>(dpi_), 96);
}

void InstallerWindow::OnSizeChanged(UINT widthPx, UINT heightPx) {
    if (widthPx == 0 || heightPx == 0) return;
    if (!renderReady_) {
        if (SUCCEEDED(render_.Initialize(window_, widthPx, heightPx, static_cast<float>(dpi_)))) {
            renderReady_ = true;
            DiagLog(L"render init ok warp=" + std::to_wstring(render_.UsingWarp() ? 1 : 0) +
                    L" size=" + std::to_wstring(widthPx) + L"x" + std::to_wstring(heightPx) +
                    L" dpi=" + std::to_wstring(dpi_));
            // Todo 12：render 就绪后构造并绑定页面（Logo/WriteFactory 需设备上下文）。
            EnsurePages();
        } else {
            DiagLog(L"render init FAILED");
        }
        return;
    }
    if (widthPx == render_.Width() && heightPx == render_.Height()) return;
    render_.Resize(widthPx, heightPx);
    render_.SetDpi(static_cast<float>(dpi_));
    if (pagesReady_) LayoutPages();  // Todo 12：尺寸变化后按新 shell 几何重排当前页
}

void InstallerWindow::OnDpiChanged(UINT newDpi, const RECT* suggested) {
    if (newDpi) dpi_ = newDpi;
    const int marginPx = MarginPx();
    const int w = MulDiv(kCanvasW, static_cast<int>(dpi_), 96) + 2 * marginPx;
    const int h = MulDiv(kCanvasH, static_cast<int>(dpi_), 96) + 2 * marginPx;
    int x = suggested ? suggested->left : 0;
    int y = suggested ? suggested->top : 0;
    if (!suggested) {
        RECT r{};
        GetWindowRect(window_, &r);
        x = r.left;
        y = r.top;
    }
    SetWindowPos(window_, nullptr, x, y, w, h, SWP_NOZORDER | SWP_NOACTIVATE);
    Layout();
    dirty_ = true;
    Render();
}

// §16 / 本 todo 唯一拥有的接线：WM_TIMER(~16ms) → 推进所有活动动画 → 若 dirty 或动画中则
// PresentFrame()（Render 内部 = BeginDraw → Clear(透明) → DrawContent → PresentFrame → Commit）
// → 无动画且无 dirty 时 KillTimer 进入闲置；下次新动画/置脏经 RequestAnimTick 重新武装。
void InstallerWindow::Tick() {
    // T11/D9：setup 退出监视必须先于动画推进——setup 消失时立即抬高取消信号，让
    // 引擎在下一个轮询点安全停止（引擎收尾后由 WM_INSTALL_DONE 展示终止原因）。
    CheckSetupWatchdog();
    const double nowMs = faf::SteadyNowMs();
    const bool worked = animator_.Tick(nowMs);  // 推进 + §16 每 tick 采样/边界行
    if (dirty_ || worked) {
        DiagLog(L"frame present t=" + std::to_wstring(static_cast<long long>(nowMs)) +
                L" anim=" + std::to_wstring(worked ? 1 : 0) +
                L" dirty=" + std::to_wstring(dirty_ ? 1 : 0));
        Render();  // 内部 PresentFrame() 已含 dcomp->Commit()
    }
    // T11：安装/修复期间即使无动画也保持 tick 定时器——CheckSetupWatchdog 依赖它，
    // 否则等待 payload 哨兵的静默期会导致 watchdog 停摆（要求 10s 内中止）。
    if (!keepTickAlive_ && !animator_.IsActive() && !dirty_) {
        DiagLog(L"anim idle t=" + std::to_wstring(static_cast<long long>(nowMs)) +
                L" -> KillTimer (no active anim, not dirty)");
        KillTickTimer();
    }
}

// 置脏 + 武装 tick 定时器。UI 任何「需要重绘/启动动画」的路径都经此，
// 保证闲置 KillTimer 之后不会卡死（定时器必被重新武装）。
void InstallerWindow::RequestAnimTick() {
    dirty_ = true;
    EnsureTickTimer();
}

void InstallerWindow::EnsureTickTimer() {
    if (!window_ || tickTimer_) return;
    tickTimer_ = SetTimer(window_, kTickTimerId, kTickIntervalMs, nullptr);
}

void InstallerWindow::KillTickTimer() {
    if (!tickTimer_) return;
    KillTimer(window_, tickTimer_);
    tickTimer_ = 0;
}

// 读 SPI_GETCLIENTAREAANIMATION；关闭动画时新动画时长置 0（直接终态，无中间 tick）。
void InstallerWindow::ApplyReduceMotion() {
    BOOL enabled = TRUE;
    if (!SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION, 0, &enabled, 0)) enabled = TRUE;
    reduceMotion_ = !enabled;
    animator_.SetReduceMotion(reduceMotion_);
    DiagLog(L"reduce_motion=" + std::to_wstring(reduceMotion_ ? 1 : 0));
}

void InstallerWindow::Render() {
    if (!renderReady_) return;
    ID2D1DeviceContext* ctx = render_.DeviceContext();
    if (!ctx) return;
    ctx->BeginDraw();
    // §5：交换链清为全透明，让 Win11 Mica 透出。
    ctx->Clear(D2D1::ColorF(0.0f, 0.0f, 0.0f, 0.0f));
    DrawContent(ctx);
    render_.PresentFrame();
    dirty_ = false;
}

void InstallerWindow::DrawContent(ID2D1DeviceContext* ctx) {
    const faf::Theme theme = faf::GetTheme(darkMode_);  // §13：唯一 token 表
    const float m = static_cast<float>(shadowMarginDip_);
    ctx->SetTransform(D2D1::Matrix3x2F::Translation(m, m));

    // 入场动画进度（减少动画/无入场动画时为 1）：乘入各层/文字 alpha，构成 WinUI3 淡入。
    introAlpha_ = introAnim_ ? introAnim_->Value() : 1.0f;

    // Todo 12：步骤栏 / 导航按钮与 shell 层共享入场进度（同帧动画协同，§16 tick 驱动）。
    faf::Theme faded = theme;
    faded.card.a *= introAlpha_;
    faded.cardStroke.a *= introAlpha_;
    faded.textPrimary.a *= introAlpha_;
    faded.textSecondary.a *= introAlpha_;
    faded.accent.a *= introAlpha_;
    faded.hover.a *= introAlpha_;
    faded.pressed.a *= introAlpha_;
    faded.divider.a *= introAlpha_;

    // §5：Win10 降级先铺一层不透明 Mica 风格渐变底（与 §4 Win10 兜底同一分支）；
    //     Win11 **不铺**，保持透明让 DWM Mica 透出（严禁整面不透明，会遮死 Mica）。
    if (win10Fallback_) DrawMicaFallbackBase(ctx, theme, introAlpha_);

    // §5：左栏（半透明层）/ 内容卡片 / 底部条各按自身 alpha 绘制；其余区域保持透明。
    DrawShellLayers(ctx, theme, introAlpha_);

    // --- Todo 12：步骤栏 + 当前页 + 导航按钮（状态唯一来源 = AppState::page，§12）---
    if (pagesReady_) {
        // 追加需求：英雄页（欢迎/完成）无步骤带——仅向导页绘制 3 个横向节点。
        // T10：Repair/Uninstall 一律不画安装步骤带（operation 非 Install 时）。
        if (state_.operation == Operation::Install && !faf::IsHeroPage(state_.page)) {
            for (int i = 0; i < kStepCount; ++i) stepItems_[i].Render(ctx, faded);
        }
        // 页内 Render 自行 SetTransform（会覆盖 shell 平移），渲染后再恢复边距平移。
        RenderActivePage(ctx, faded);
        ctx->SetTransform(D2D1::Matrix3x2F::Translation(m, m));
        // UI-fix：导航按钮按页面可见性绘制（英雄页全隐藏；Progress 隐藏；Configure 由门控决定）。
        if (navBackVisible_) backButton_.Render(ctx, faded);
        if (navNextVisible_) nextButton_.Render(ctx, faded);
    }

    DrawTitleBar(ctx, theme, introAlpha_);

    if (!errorText_.empty()) {
        const faf::ShellLayout& s = shellLayout_;
        const float cardW = s.contentCard.right - s.contentCard.left;
        DrawTextLine(ctx, errorText_, s.contentCard.left + faf::spacing::M,
                     s.contentCard.top + faf::spacing::M, cardW - 2.0f * faf::spacing::M,
                     faf::fontsize::Body + faf::spacing::S, faf::fontsize::Body,
                     D2D1::ColorF(0.85f, 0.20f, 0.20f, introAlpha_));
    }

    ctx->SetTransform(D2D1::Matrix3x2F::Identity());
}

void InstallerWindow::DrawMicaFallbackBase(ID2D1DeviceContext* ctx, const faf::Theme& theme,
                                           float alpha) {
    const float W = faf::layout::kCanvasWidth;
    const float H = faf::layout::kCanvasHeight;
    const float m = static_cast<float>(shadowMarginDip_);

    // §4 Win10 兜底的 (可选) 自绘柔化阴影：只显现在透明外扩边距内。§14 规定阴影断言
    // 须用桌面 DC，故此阴影仅近似；真正的阴影/圆角证明归 Todo 20 真机截图。
    if (m > 0.0f) {
        faf::ComPtr<ID2D1SolidColorBrush> shadow;
        if (SUCCEEDED(ctx->CreateSolidColorBrush(D2D1::ColorF(0, 0, 0, 0.10f * alpha),
                                                 shadow.GetAddressOf()))) {
            const int steps = 5;
            for (int i = steps - 1; i >= 0; --i) {
                const float grow =
                    (static_cast<float>(i) + 1.0f) * (m / static_cast<float>(steps)) * 0.6f;
                const float r = faf::radius::Medium + grow;
                ctx->FillRoundedRectangle(
                    D2D1::RoundedRect(D2D1::RectF(-grow, -grow, W + grow, H + grow), r, r),
                    shadow.Get());
            }
        }
    }

    // §5 Win10 兜底：不透明 Mica 风格渐变底；明暗单一来源 = Theme.isDark。
    D2D1_GRADIENT_STOP stops[2] = {};
    if (theme.isDark) {
        stops[0] = {0.0f, D2D1::ColorF(0.176f, 0.176f, 0.176f, alpha)};
        stops[1] = {1.0f, D2D1::ColorF(0.102f, 0.102f, 0.102f, alpha)};
    } else {
        stops[0] = {0.0f, D2D1::ColorF(0.980f, 0.980f, 0.980f, alpha)};
        stops[1] = {1.0f, D2D1::ColorF(0.925f, 0.925f, 0.925f, alpha)};
    }
    faf::ComPtr<ID2D1GradientStopCollection> coll;
    if (FAILED(ctx->CreateGradientStopCollection(stops, 2, coll.GetAddressOf()))) return;
    faf::ComPtr<ID2D1LinearGradientBrush> base;
    if (FAILED(ctx->CreateLinearGradientBrush(
            D2D1::LinearGradientBrushProperties(D2D1::Point2F(0, 0), D2D1::Point2F(0, H)),
            coll.Get(), base.GetAddressOf()))) {
        return;
    }
    ctx->FillRoundedRectangle(
        D2D1::RoundedRect(D2D1::RectF(0, 0, W, H), faf::radius::Medium, faf::radius::Medium),
        base.Get());
}

void InstallerWindow::DrawShellLayers(ID2D1DeviceContext* ctx, const faf::Theme& theme,
                                      float alpha) {
    // §6：矩形全部来自 layout（纯 DIP），此处不再硬编码 railW/bottomH/margin/card rect。
    const faf::ShellLayout& s = shellLayout_;

    // §5：Win10 层为不透明；Win11 层保留 token alpha（半透明，透出 Mica）。
    // 入场 alpha 再乘入（淡入）。
    auto layer = [&](D2D1_COLOR_F c) -> D2D1_COLOR_F {
        if (win10Fallback_) c.a = 1.0f;
        c.a *= alpha;
        return c;
    };
    auto faded = [&](D2D1_COLOR_F c) -> D2D1_COLOR_F {
        c.a *= alpha;
        return c;
    };

    faf::ComPtr<ID2D1SolidColorBrush> card;
    if (FAILED(ctx->CreateSolidColorBrush(layer(theme.card), card.GetAddressOf()))) return;
    // 内容卡片已移除：窗口直接承载内容（用户要求，全页面统一，无嵌套容器）。contentCard 仍作为页面内容/内边距区域。

    // 底部条（英雄页 bottomBar 为空矩形 → 跳过绘制/分隔线）。
    if (s.bottomBar.right > s.bottomBar.left && s.bottomBar.bottom > s.bottomBar.top) {
        ctx->FillRectangle(s.bottomBar, card.Get());
    }

    // 追加需求：顶部横向步骤带只在向导页存在（英雄页 stepper 为空 → 跳过）。
    // 步骤节点/连接线/标签由 DrawContent() 内的 StepItem::Render 绘制；此处只画步骤带下缘分隔线。
    if (s.stepper.right > s.stepper.left && s.stepper.bottom > s.stepper.top) {
        faf::ComPtr<ID2D1SolidColorBrush> divider;
        if (SUCCEEDED(ctx->CreateSolidColorBrush(faded(theme.divider), divider.GetAddressOf()))) {
            ctx->DrawLine(D2D1::Point2F(s.stepper.left, s.stepper.bottom),
                          D2D1::Point2F(s.stepper.right, s.stepper.bottom), divider.Get(), 1.0f);
        }
    }
}

void InstallerWindow::DrawTitleBar(ID2D1DeviceContext* ctx, const faf::Theme& theme, float alpha) {
    const faf::ShellLayout& s = shellLayout_;
    const float titleH = s.titleBar.bottom;
    // 标题文字右边界让出两个窗口按钮命中区（layout 常量）。
    const float titleW =
        s.titleBar.right - 2.0f * faf::layout::kWindowButtonWidth - faf::spacing::M;

    D2D1_COLOR_F primary = theme.textPrimary;
    primary.a *= alpha;
    D2D1_COLOR_F dividerColor = theme.divider;
    dividerColor.a *= alpha;

    // §5：标题栏区域保持透明（Win11 让 Mica 透出）；文字/字形用 token 前色，底部一条分隔线。
    // T10：标题文字来自构造期按 mode 设置的 windowTitle_（CreateWindowExW 同源）。
    DrawTextLine(ctx, windowTitle_, faf::spacing::M, 0, titleW, titleH, faf::fontsize::Caption,
                 primary);

    // 窗口按钮（最小化/关闭）悬停/按下背景填充。
    // 视觉态派生自状态机：hot = 光标悬停命中；armed = 已按下且光标仍在同一按钮上（移出即灭）。
    const bool minHot = hoverButton_ == WindowButton::Minimize;
    const bool minArmed = minHot && armedButton_ == WindowButton::Minimize;
    const bool closeHot = hoverButton_ == WindowButton::Close;
    const bool closeArmed = closeHot && armedButton_ == WindowButton::Close;

    // 最小化：中性叠加（复用 theme.hover / pressed token），字形颜色不变。
    if (minHot) {
        D2D1_COLOR_F fill = minArmed ? theme.pressed : theme.hover;
        fill.a *= alpha;
        faf::ComPtr<ID2D1SolidColorBrush> minBg;
        if (SUCCEEDED(ctx->CreateSolidColorBrush(fill, minBg.GetAddressOf()))) {
            ctx->FillRectangle(s.minButton, minBg.Get());
        }
    }
    // 关闭：Windows 标准红填充（悬停 #C42B1C / 按下 #B0251A），覆盖整个 46x32 命中区。
    if (closeHot) {
        D2D1_COLOR_F fill = closeArmed ? CloseArmedRed() : CloseHoverRed();
        fill.a *= alpha;
        faf::ComPtr<ID2D1SolidColorBrush> closeBg;
        if (SUCCEEDED(ctx->CreateSolidColorBrush(fill, closeBg.GetAddressOf()))) {
            ctx->FillRectangle(s.closeButton, closeBg.Get());
        }
    }

    faf::ComPtr<ID2D1SolidColorBrush> stroke;
    if (SUCCEEDED(ctx->CreateSolidColorBrush(primary, stroke.GetAddressOf()))) {
        const float mcx = (s.minButton.left + s.minButton.right) * 0.5f;
        const float mcy = (s.minButton.top + s.minButton.bottom) * 0.5f;
        ctx->DrawLine(D2D1::Point2F(mcx - 6, mcy), D2D1::Point2F(mcx + 6, mcy), stroke.Get(), 1.0f);
    }
    // ✕ 字形：悬停/按下时转白（红底对比），否则保持原前色。
    D2D1_COLOR_F closeGlyph = primary;
    if (closeHot) closeGlyph = D2D1::ColorF(1.0f, 1.0f, 1.0f, alpha);
    faf::ComPtr<ID2D1SolidColorBrush> closeStroke;
    if (SUCCEEDED(ctx->CreateSolidColorBrush(closeGlyph, closeStroke.GetAddressOf()))) {
        const float ccx = (s.closeButton.left + s.closeButton.right) * 0.5f;
        const float ccy = (s.closeButton.top + s.closeButton.bottom) * 0.5f;
        ctx->DrawLine(D2D1::Point2F(ccx - 5, ccy - 5), D2D1::Point2F(ccx + 5, ccy + 5), closeStroke.Get(), 1.0f);
        ctx->DrawLine(D2D1::Point2F(ccx - 5, ccy + 5), D2D1::Point2F(ccx + 5, ccy - 5), closeStroke.Get(), 1.0f);
    }

    faf::ComPtr<ID2D1SolidColorBrush> divider;
    if (SUCCEEDED(ctx->CreateSolidColorBrush(dividerColor, divider.GetAddressOf()))) {
        ctx->DrawLine(D2D1::Point2F(0, titleH), D2D1::Point2F(s.titleBar.right, titleH),
                      divider.Get(), 1.0f);
    }
}

void InstallerWindow::DrawTextLine(ID2D1DeviceContext* ctx, const std::wstring& text, float x, float y,
                                   float width, float height, float sizeDip,
                                   const D2D1_COLOR_F& color, DWRITE_FONT_WEIGHT weight) {
    IDWriteFactory* dwrite = render_.WriteFactory();
    if (!dwrite) return;
    faf::ComPtr<IDWriteTextFormat> format;
    if (FAILED(dwrite->CreateTextFormat(L"Segoe UI", nullptr, weight,
                                        DWRITE_FONT_STYLE_NORMAL, DWRITE_FONT_STRETCH_NORMAL, sizeDip,
                                        L"zh-cn", format.GetAddressOf()))) {
        return;
    }
    format->SetTextAlignment(DWRITE_TEXT_ALIGNMENT_LEADING);
    format->SetParagraphAlignment(DWRITE_PARAGRAPH_ALIGNMENT_CENTER);
    faf::ComPtr<ID2D1SolidColorBrush> brush;
    if (FAILED(ctx->CreateSolidColorBrush(color, brush.GetAddressOf()))) return;
    ctx->DrawText(text.c_str(), static_cast<UINT32>(text.size()), format.Get(),
                  D2D1::RectF(x, y, x + width, y + height), brush.Get());
}

void InstallerWindow::ClientPointToDip(POINT p, float* dx, float* dy) const {
    const float m = static_cast<float>(MarginPx());
    // §6：客户端物理像素 → DIP 的换算比例 = 96 / SafeDpi(dpi_)。dpi_ 为 0 时
    // ClientPxToDipScale 守卫回退 96，绝不出现 96/0 除零（见 layout.h::SafeDpi）。
    const float scale = faf::ClientPxToDipScale(dpi_);
    *dx = (static_cast<float>(p.x) - m) * scale;
    *dy = (static_cast<float>(p.y) - m) * scale;
}

// --- 自绘标题栏窗口按钮（最小化/关闭）状态机 ---------------------------------
InstallerWindow::WindowButton InstallerWindow::HitTestWindowButton(float dipX, float dipY) const {
    const D2D1_POINT_2F pt = D2D1::Point2F(dipX, dipY);
    // 关闭优先（右边缘），其次最小化；命中区来自 layout（纯 DIP，不重新缩放）。
    if (faf::HitTest(shellLayout_.closeButton, pt)) return WindowButton::Close;
    if (faf::HitTest(shellLayout_.minButton, pt)) return WindowButton::Minimize;
    return WindowButton::None;
}

void InstallerWindow::UpdateTitleBarHover(float dipX, float dipY) {
    const WindowButton hit = HitTestWindowButton(dipX, dipY);
    if (hit == hoverButton_) return;  // 无变化无需重绘
    hoverButton_ = hit;
    RequestAnimTick();  // 走既有重绘机制（置脏 + tick 定时器），悬停填充即时出现/消失
}

void InstallerWindow::PerformWindowButtonAction(WindowButton button) {
    HWND hwnd = window_;
    if (!hwnd) return;
    if (button == WindowButton::Close) {
        PostMessageW(hwnd, WM_CLOSE, 0, 0);  // 复用既有取消/关闭清理路径
    } else if (button == WindowButton::Minimize) {
        ShowWindow(hwnd, SW_MINIMIZE);
    }
}

LRESULT CALLBACK InstallerWindow::WindowProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
    auto* self = reinterpret_cast<InstallerWindow*>(GetWindowLongPtrW(hwnd, GWLP_USERDATA));
    if (msg == WM_NCCREATE) {
        self = reinterpret_cast<InstallerWindow*>(reinterpret_cast<CREATESTRUCTW*>(lp)->lpCreateParams);
        SetWindowLongPtrW(hwnd, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(self));
        if (self) self->window_ = hwnd;
    }
    return self ? self->HandleMessage(msg, wp, lp) : DefWindowProcW(hwnd, msg, wp, lp);
}

LRESULT InstallerWindow::HandleMessage(UINT msg, WPARAM wp, LPARAM lp) {
    HWND hwnd = window_;

    // 自绘非客户区：客户区 = 整窗（§4）。DWM 仍按 WS_CAPTION|WS_THICKFRAME 提供圆角/阴影。
    if (msg == WM_NCCALCSIZE) {
        DiagLog(std::wstring(L"WM_NCCALCSIZE wp=") + std::to_wstring(wp));
        if (wp) return 0;
        return DefWindowProcW(hwnd, msg, wp, lp);
    }
    if (msg == WM_ERASEBKGND) return 1;

    // §4 固定尺寸：ptMinTrackSize = ptMaxTrackSize = ptMaxSize，且 ptMaxPosition 防跳动。
    if (msg == WM_GETMINMAXINFO) {
        auto* mmi = reinterpret_cast<MINMAXINFO*>(lp);
        const int marginPx = MarginPx();
        const LONG w = MulDiv(kCanvasW, static_cast<int>(dpi_), 96) + 2 * marginPx;
        const LONG h = MulDiv(kCanvasH, static_cast<int>(dpi_), 96) + 2 * marginPx;
        mmi->ptMinTrackSize.x = w;
        mmi->ptMinTrackSize.y = h;
        mmi->ptMaxTrackSize.x = w;
        mmi->ptMaxTrackSize.y = h;
        mmi->ptMaxSize.x = w;
        mmi->ptMaxSize.y = h;
        RECT r{};
        GetWindowRect(hwnd, &r);
        mmi->ptMaxPosition.x = r.left;
        mmi->ptMaxPosition.y = r.top;
        return 0;
    }

    // §4 禁止最大化/缩放：SC_MAXIMIZE / SC_SIZE 直接吞掉。
    if (msg == WM_SYSCOMMAND) {
        const WPARAM cmd = wp & 0xFFF0;
        if (cmd == SC_MAXIMIZE || cmd == SC_SIZE) return 0;
    }

    // §4 吞掉标题栏双击最大化。
    if (msg == WM_NCLBUTTONDBLCLK) return 0;

    if (msg == WM_NCHITTEST) {
        POINT p{static_cast<LONG>(static_cast<short>(LOWORD(lp))),
                static_cast<LONG>(static_cast<short>(HIWORD(lp)))};
        ScreenToClient(hwnd, &p);
        float dx = 0, dy = 0;
        ClientPointToDip(p, &dx, &dy);
        const D2D1_POINT_2F pt = D2D1::Point2F(dx, dy);
        if (dy >= shellLayout_.titleBar.top && dy < shellLayout_.titleBar.bottom) {
            // 命中区来自 layout（DIP），HitTest 不重新缩放。
            if (faf::HitTest(shellLayout_.minButton, pt) ||
                faf::HitTest(shellLayout_.closeButton, pt))
                return HTCLIENT;
            return HTCAPTION;  // §4 标题栏可拖
        }
        return HTCLIENT;
    }

    if (msg == WM_LBUTTONDOWN) {
        POINT p{static_cast<LONG>(static_cast<short>(LOWORD(lp))),
                static_cast<LONG>(static_cast<short>(HIWORD(lp)))};
        float dx = 0, dy = 0;
        ClientPointToDip(p, &dx, &dy);
        // 窗口按钮：按下**不**触发动作——记录 armed 并捕获鼠标，等「同一按钮上松开」才执行
        //（Win32 push-button 语义；按下即最小化/关闭是本次修复的缺陷）。
        const WindowButton pressed = HitTestWindowButton(dx, dy);
        if (pressed != WindowButton::None) {
            armedButton_ = pressed;
            SetCapture(hwnd);
            RequestAnimTick();
            return 0;
        }
        // §4 自绘标题栏拖拽（HTCAPTION 已由 WM_NCHITTEST 承担；此处为等价兜底路径）。
        if (dy >= shellLayout_.titleBar.top && dy < shellLayout_.titleBar.bottom) {
            ReleaseCapture();
            SendMessageW(hwnd, WM_NCLBUTTONDOWN, HTCAPTION, 0);
            return 0;
        }
        // Todo 12：非标题栏 → 外壳导航按钮 / 当前页 指针分发（经 controls_base.h）。
        faf::InputEvent ev{};
        ev.kind = faf::InputEvent::Down;
        ev.x = dx;
        ev.y = dy;
        DispatchPointer(ev);
        return 0;
    }

    if (msg == WM_LBUTTONUP) {
        POINT p{static_cast<LONG>(static_cast<short>(LOWORD(lp))),
                static_cast<LONG>(static_cast<short>(HIWORD(lp)))};
        float dx = 0, dy = 0;
        ClientPointToDip(p, &dx, &dy);
        if (armedButton_ != WindowButton::None) {
            // 激活条件：松开点仍命中**同一**按钮；否则静默取消（移出后松开 = 取消）。
            const WindowButton armed = armedButton_;
            const WindowButton released = HitTestWindowButton(dx, dy);
            armedButton_ = WindowButton::None;
            if (GetCapture() == hwnd) ReleaseCapture();
            if (released == armed) PerformWindowButtonAction(armed);
            RequestAnimTick();
            return 0;  // 窗口按钮的 Up 不透传给页面
        }
        faf::InputEvent ev{};
        ev.kind = faf::InputEvent::Up;
        ev.x = dx;
        ev.y = dy;
        DispatchPointer(ev);
        return 0;
    }

    if (msg == WM_MOUSEMOVE) {
        POINT p{static_cast<LONG>(static_cast<short>(LOWORD(lp))),
                static_cast<LONG>(static_cast<short>(HIWORD(lp)))};
        float dx = 0, dy = 0;
        ClientPointToDip(p, &dx, &dy);
        // 首次移动注册 TME_LEAVE：光标离开时收到 WM_MOUSELEAVE 以复位悬停（无 Leave 会残留填充）。
        if (!trackingLeave_) {
            TRACKMOUSEEVENT tme{};
            tme.cbSize = sizeof(tme);
            tme.dwFlags = TME_LEAVE;
            tme.hwndTrack = hwnd;
            if (TrackMouseEvent(&tme)) trackingLeave_ = true;
        }
        UpdateTitleBarHover(dx, dy);  // 刷新窗口按钮悬停（变化时置脏重绘）
        faf::InputEvent ev{};
        ev.kind = faf::InputEvent::Move;
        ev.x = dx;
        ev.y = dy;
        DispatchPointer(ev);
        return 0;
    }

    // 光标离开窗口/客户区：复位悬停填充，并允许下次移动重新注册 TME_LEAVE。
    if (msg == WM_MOUSELEAVE) {
        trackingLeave_ = false;
        if (hoverButton_ != WindowButton::None) {
            hoverButton_ = WindowButton::None;
            RequestAnimTick();
        }
        return 0;
    }

    // 捕获丢失（被其它窗口抢走 / 显式释放）→ 清 armed，避免按钮停在按下红态。
    if (msg == WM_CAPTURECHANGED) {
        if (armedButton_ != WindowButton::None) {
            armedButton_ = WindowButton::None;
            RequestAnimTick();
        }
        return 0;
    }

    // §6：滚轮 lParam 为屏幕坐标 → 客户端 → DIP；当前仅 LicenseBox 消费。
    if (msg == WM_MOUSEWHEEL) {
        POINT p{static_cast<LONG>(static_cast<short>(LOWORD(lp))),
                static_cast<LONG>(static_cast<short>(HIWORD(lp)))};
        ScreenToClient(hwnd, &p);
        float dx = 0, dy = 0;
        ClientPointToDip(p, &dx, &dy);
        if (pagesReady_) {
            faf::InputEvent ev{};
            ev.kind = faf::InputEvent::Wheel;
            // 页内坐标 = 画布 DIP + Win10 兜底外扩边距（页布局同偏移，见 PageRect）。
            const float m = static_cast<float>(shadowMarginDip_);
            ev.x = dx + m;
            ev.y = dy + m;
            ev.key = GET_WHEEL_DELTA_WPARAM(wp);
            if (ActivePageHost().Dispatch(ev)) {
                UpdateNavButtons();
                RequestAnimTick();
            }
        }
        return 0;
    }

    // Todo 12：键盘——ESC 关闭（安装中禁止）；Tab 走当前页 Tab 顺序；其余交给当前页。
    if (msg == WM_KEYDOWN) {
        const int vk = static_cast<int>(wp);
        const bool shift = (GetKeyState(VK_SHIFT) & 0x8000) != 0;
        if (vk == VK_ESCAPE) {
            OnEscape();
            return 0;
        }
        if (vk == VK_TAB) {
            if (pagesReady_) {
                ActivePageHost().FocusNext(shift);
                RequestAnimTick();
            }
            return 0;
        }
        if (pagesReady_) {
            faf::InputEvent ev{};
            ev.kind = faf::InputEvent::Key;
            ev.key = vk;
            ev.shift = shift;
            if (ActivePageHost().Dispatch(ev)) {
                UpdateNavButtons();
                RequestAnimTick();
            }
        }
        return 0;
    }

    if (msg == WM_TIMER) {
        if (wp == kTickTimerId) {
            Tick();
            return 0;
        }
#ifdef FAF_TESTMODE
        if (wp == kAutoTimerId) {
            AutoDriveTick();  // Todo 19：/auto 固定时序推进（仅测试构建存在该定时器）
            return 0;
        }
#endif
    }
    if (msg == WM_PAINT) {
        if (dirty_ && renderReady_)
            Render();
        else
            ValidateRect(hwnd, nullptr);
        return 0;
    }
    if (msg == WM_SIZE) {
        if (renderReady_ && wp != SIZE_MINIMIZED) {
            OnSizeChanged(static_cast<UINT>(LOWORD(lp)), static_cast<UINT>(HIWORD(lp)));
        }
        return 0;
    }
    if (msg == WM_DPICHANGED) {
        OnDpiChanged(LOWORD(wp) ? LOWORD(wp) : HIWORD(wp), reinterpret_cast<const RECT*>(lp));
        return 0;
    }
    // §5 实时跟随系统深浅色：ImmersiveColorSet 设置变更 → 重读注册表、重设深色属性、重绘。
    // wParam 为 SPI_SETTINGCHANGE（0x000A；MinGW 的 winuser.h 未导出该名，故用字面量）。
    if (msg == WM_SETTINGCHANGE && wp == 0x000A && lp != 0 &&
        lstrcmpiW(reinterpret_cast<LPCWSTR>(lp), L"ImmersiveColorSet") == 0) {
        RefreshSystemTheme();
        return 0;
    }
    // §5 DWM 颜色化变化（强调色 / 明暗）→ 置脏重绘（让 Mica 色调同步）。
    if (msg == WM_DWMCOLORIZATIONCOLORCHANGED) {
        dirty_ = true;
        Render();
        return 0;
    }
    // T10：第二实例请求恢复并置前（T13 的 SingleInstanceGuard 发出）。
    if (msg == WM_FAF_ACTIVATE) {
        ShowWindow(hwnd, SW_RESTORE);
        SetForegroundWindow(hwnd);
        return 0;
    }
    // T10：维护/卸载跨线程消息占位分发（真实分流由 T11-T13 填充）。
    if (msg == WM_APP_CLOSE_DONE) {
        OnCloseDoneMessage(wp);
        return 0;
    }
    if (msg == WM_UNINSTALL_PROGRESS) {
        OnUninstallProgressMessage(wp, lp);
        return 0;
    }
    if (msg == WM_UNINSTALL_DONE) {
        OnUninstallDoneMessage(wp, lp);
        return 0;
    }
    if (msg == WM_CLOSE) {
        // T14：启动期致命错误页（helper 非管理员 / 身份不一致 / 缺 /decision）
        // 关闭时只销毁窗口：绝不写 maintenance-decision.ini、uninstall-request.ini、
        // uninstall-result.ini 或 install-result.ini，也不触发模式的关闭业务。
        if (!startupErrorTitle_.empty()) {
            DiagLog(L"WM_CLOSE startup error -> DestroyWindow");
            KillTickTimer();
            DestroyWindow(hwnd);
            return 0;
        }
        // T10：非 Install 模式的关闭语义分流到 T11/T12 的接缝方法（写 decision /
        // ui_done 等业务由后续 todo 完成；本 todo 不在此写 INI、不终止进程）。
        if (mode_ == AppMode::Maintenance) {
            OnMaintenanceCloseIntent();
            return 0;
        }
        if (mode_ == AppMode::Uninstall) {
            OnUninstallCloseIntent();
            return 0;
        }
        // Todo 12/13：窗口关闭等同取消。安装中不得立即销毁——引擎仍需按 §3 安全停止、
        // 清理本次写入并写 §1 结果（abort=1）；销毁延迟到 WM_INSTALL_DONE。
        if (installing_) {
            closePending_ = true;
            RaiseCancelIntent();
            return 0;
        }
        WriteCancelResult();  // 非安装中：统一 §1 结果写入（resultWritten_ 守卫防重复）
        KillTickTimer();
        DestroyWindow(hwnd);
        return 0;
    }
    if (msg == WM_DESTROY) {
        DiagLog(L"WM_DESTROY exitCode=" + std::to_wstring(exitCode_));
        KillTickTimer();
        // T14：startup error 页以 1 退出；其余模式保持既有 0。
        PostQuitMessage(exitCode_);
        return 0;
    }
    if (msg == WM_INSTALL_PROGRESS) {  // §10：wParam = permille 0..1000
        progressPermille_ = static_cast<int>(wp);
        // Todo 12：转发到 Progress 页（页面只消费 permille，不制造假进度）。
        if (progressPage_) progressPage_->SetProgressPermille(progressPermille_);
        RequestAnimTick();  // 置脏 + 确保 tick 定时器在跑（可能在闲置被 KillTimer）
        return 0;
    }
    if (msg == WM_INSTALL_DONE) {  // wParam：1 = 成功；0 = 取消/超时/失败（引擎已写 §1 INI）
        installing_ = false;
        keepTickAlive_ = false;  // T11：操作结束，允许 tick 定时器在闲置时停表
        if (installThread_) {
            CloseHandle(installThread_);
            installThread_ = nullptr;
        }
        const bool ok = wp != 0;
        const bool cancelled = installCancelled_.load();
        const bool timedOut = installTimedOut_.load();
        // T11：setup 提前退出会置 cancel_ + installTimedOut_，但 UI 文案必须以
        // “安装程序已退出，操作已终止”为准（不得显示成用户取消或自动关窗）。
        const bool setupExited = state_.setupExited;
        const bool repair = state_.operation == Operation::Repair;
        std::wstring error;
        {
            std::lock_guard<std::mutex> lock(errorMutex_);
            error = installError_;
        }
        DiagLog(L"install done ok=" + std::to_wstring(ok ? 1 : 0) + L" cancelled=" +
                std::to_wstring(cancelled ? 1 : 0) + L" timeout=" +
                std::to_wstring(timedOut ? 1 : 0) + L" setup_exited=" +
                std::to_wstring(setupExited ? 1 : 0) + L" repair=" +
                std::to_wstring(repair ? 1 : 0) + L" error=" + error);

        if (repair) {
            // T11：修复终点。成功 → Finish(Repair)；失败/取消 → Message，窗口保持
            // 打开（修复不回滚，绝不能自动关闭或伪造成功）。
            if (ok) {
                SetPage(Finish);
                return 0;
            }
            if (setupExited) {
                ShowError(L"修复已终止", L"安装程序已退出，操作已终止", L"关闭", L"");
            } else if (cancelled) {
                ShowError(L"修复已取消", L"修复未完成，已写入的程序文件保持原样。", L"关闭", L"");
            } else {
                ShowError(L"修复失败",
                          error.empty() ? L"修复过程中出现未知错误。" : (L"修复失败：" + error),
                          L"关闭", L"");
            }
            return 0;
        }

        if (closePending_) {
            // 安装中收到的关闭：引擎已安全停止并完成 §1 结果写入 → 现在销毁。
            KillTickTimer();
            DestroyWindow(hwnd);
            return 0;
        }
        if (ok) {
            SetPage(Finish);  // 自动进入完成页（Progress→Finish 自动，无需用户下一步）
            return 0;
        }
        if (setupExited) {
            // T11/T13：setup 已退出 → 不自动关窗，统一走可见错误页明确告知操作被终止。
            ShowError(L"安装已终止", L"安装程序已退出，操作已终止", L"关闭", L"");
            return 0;
        }
        if (cancelled) {
            if (progressPage_) progressPage_->MarkCancelled();  // §3：引擎确认已清理完成
            PostMessageW(hwnd, WM_CLOSE, 0, 0);  // 统一关闭路径（resultWritten_ 守卫防二次写）
            return 0;
        }
        // 超时/失败：引擎已写 abort=1 + error=；T13 统一显示可见、可关闭的错误页，
        // 窗口保持打开（不自动退出）。关闭时 WriteCancelResult 受 resultWritten_ 保护。
        ShowError(L"安装失败", error.empty() ? L"安装失败" : (L"安装失败：" + error), L"关闭",
                  L"");
        return 0;
    }

    return DefWindowProcW(hwnd, msg, wp, lp);
}

void InstallerWindow::SetPage(int page) {
    // §12：页面唯一来源 = AppState::page；进入页面统一走 ApplyPageEntry（Synced + Layout）。
    state_.page = page;
    // 追加需求：英雄页（欢迎/完成）⇄ 向导页切换时 shell 几何不同（有无步骤带/底部条），
    // 必须在布局页面之前重算，否则页/步骤带/导航按钮会沿用旧几何。
    // T10：Repair/Uninstall（operation != Install）复用 Progress/Finish 时也按英雄页布局。
    shellLayout_ = faf::ComputeShellLayout(faf::IsHeroPage(page) ||
                                           state_.operation != Operation::Install);
    ApplyPageEntry();
    RequestAnimTick();  // 置脏 + 确保 tick 定时器在跑（页面切换动画 + 步骤栏高亮）
}

DWORD WINAPI InstallerWindow::InstallThreadProc(LPVOID p) {
    static_cast<InstallerWindow*>(p)->InstallThread();
    return 0;
}

void InstallerWindow::WriteAbortResult(const std::wstring& error) {
    // §1：唯一结果写入器（faf::WriteInstallResultIni）的中止包装（abort=1 + error）。
    // resultWritten_ 守卫：引擎已写成功时此处为 no-op（同一进程最多写一次结果）。
    if (resultWritten_) return;
    faf::InstallOptions options;
    options.desktop = state_.optDesktop;
    options.startmenu = state_.optStartmenu;
    options.autostart = state_.optAutostart;
    if (faf::WriteInstallResultIni(resultPath_, state_.installDir, /*abort=*/true, error, options)) {
        resultWritten_ = true;
    }
}

void InstallerWindow::WriteCancelResult() {
    // 保留方法名（Todo 15 兼容）：窗口关闭等同取消 → §1 语义 = abort=1 + error=cancelled。
    WriteAbortResult(L"cancelled");
}

void InstallerWindow::OnFinishIntent() {
    // T12/D15 C1：Finish(Uninstall) 关闭前写 ui_done=1；协调器已失败则不写（helper
    // 已失败/退出，不能伪造 UI 同意收尾）。随后统一走 WM_CLOSE → OnUninstallCloseIntent。
    if (state_.operation == Operation::Uninstall) {
        if (uninstallCoordinator_ && !uninstallCoordinator_->Failed()) {
            uninstallCoordinator_->WriteUiDone();
        }
        PostMessageW(window_, WM_CLOSE, 0, 0);
        return;
    }
    // T11/Acceptance：Finish(Repair) —— 仅当用户勾选「立即启动 FreeAssetFilter」时启动
    // （复选框直接绑定 state_.optLaunchAfterRepair，默认 false），随后关窗；未勾选只关窗。
    if (state_.operation == Operation::Repair) {
        if (!state_.optLaunchAfterRepair) {
            DiagLog(L"repair finish without launch");
            PostMessageW(window_, WM_CLOSE, 0, 0);
            return;
        }
        const faf::LaunchOutcome repairOutcome =
            faf::LaunchInstalledAppDeElevated(state_.installDir, window_);
        DiagLog(L"repair launch attempted dir=" + state_.installDir + L" launched=" +
                std::to_wstring(repairOutcome.launched ? 1 : 0) + L" missing=" +
                std::to_wstring(repairOutcome.missingExe ? 1 : 0) + L" error=" +
                repairOutcome.error);
        if (!repairOutcome.launched) {
            // 启动失败不关窗（不伪造成功）；T13 与安装完成页共用可见错误页。
            ShowError(L"启动失败",
                      repairOutcome.error.empty() ? L"启动失败"
                                                  : (L"启动失败：" + repairOutcome.error),
                      L"关闭", L"");
            return;
        }
        PostMessageW(window_, WM_CLOSE, 0, 0);
        return;
    }
    // §15（唯一 owner = Todo 15）：完成后启动。
    // 追加需求（2026-10-18）：完成页改为英雄页——大按钮「立即启动」= **无条件启动**
    // （页内不再有「立即启动」勾选框，AppState.optLaunch 恒为默认真）。
    //   * 去提权：经 render/launch_forward.h 的 explorer 转发（绝不直接
    //     ShellExecuteW(exe)——会以管理员令牌运行）。
    const faf::LaunchOutcome outcome =
        faf::LaunchInstalledAppDeElevated(state_.installDir, window_);
    DiagLog(L"launch attempted dir=" + state_.installDir + L" launched=" +
            std::to_wstring(outcome.launched ? 1 : 0) + L" missing=" +
            std::to_wstring(outcome.missingExe ? 1 : 0) + L" error=" + outcome.error);
    if (!outcome.launched) {
        // 目标缺失/转发失败：不崩溃、不关闭；T13 统一显示可见错误页，用户可关闭。
        ShowError(L"启动失败",
                  outcome.error.empty() ? L"启动失败" : (L"启动失败：" + outcome.error),
                  L"关闭", L"");
        return;
    }
    PostMessageW(window_, WM_CLOSE, 0, 0);
}

void InstallerWindow::InstallThread() {
    // §2/§1：选项从 AppState 快照（INI 选项键与 GUI 状态的唯一一致性来源）。
    faf::InstallOptions options;
    options.desktop = state_.optDesktop;
    options.startmenu = state_.optStartmenu;
    options.autostart = state_.optAutostart;

    // Todo 13：真实引擎 = §11 哨兵等待 → 预扫描 → 逐文件复制（permille 上报）→
    // §3 取消清理 → §1 结果 INI。引擎内无 HWND/COM，结果 INI 由其唯一写入器完成。
    // T11：installMode_ 在创建线程前由 UI 线程写入，worker 只读（无并发写）。
    faf::InstallEngine engine(payload_, state_.installDir, resultPath_);
    const faf::InstallResult result =
        engine.Run(options, installMode_, cancel_, [this](int permille) {
            // §10：PostMessage 节流 ~30fps；终值 1000 恒发（节流不得吞掉终值）。
            const ULONGLONG now = GetTickCount64();
            if (permille >= 1000 || now - lastProgressPostTick_ >= kProgressPostIntervalMs) {
                lastProgressPostTick_ = now;
                PostMessageW(window_, WM_INSTALL_PROGRESS, static_cast<WPARAM>(permille), 0);
            }
        });

    resultWritten_ = result.iniWritten;
    installCancelled_ = result.cancelled;
    installTimedOut_ = result.timedOut;
    {
        std::lock_guard<std::mutex> lock(errorMutex_);
        installError_ = result.error;
    }
    PostMessageW(window_, WM_INSTALL_DONE, result.ok ? 1 : 0, 0);
}

void InstallerWindow::StartInstall(faf::InstallMode mode) {
    if (installing_) return;  // 防重入（导航已门控，此处为最后防线）
    installMode_ = mode;
    // 每次安装重置取消/结果/错误/进度状态（含失败后重装路径）。
    cancel_ = false;
    closePending_ = false;
    resultWritten_ = false;
    installCancelled_ = false;
    installTimedOut_ = false;
    progressPermille_ = 0;
    errorText_.clear();
    {
        std::lock_guard<std::mutex> lock(errorMutex_);
        installError_.clear();
    }
    installing_ = true;
    // T11：修复期间保持 tick 定时器（setup 退出 watchdog 依赖它；无动画时也不停表）。
    keepTickAlive_ = true;
    if (mode == faf::InstallMode::Repair) {
        // T11：repair 复用 Progress 页 —— operation 是唯一来源（SetPage/布局/步骤栏均读它）。
        state_.operation = Operation::Repair;
    } else {
        state_.operation = Operation::Install;
    }
    SetPage(Progress);
    if (mode == faf::InstallMode::Repair && progressPage_) {
        progressPage_->SetKind(faf::ProgressPage::Kind::Repair);
        progressPage_->SetCancellable(false);  // 修复中不允许取消/ESC/X
        progressPage_->SetNotice(L"修复过程中请勿关闭窗口");
    }
    DiagLog(std::wstring(L"install start dir=") + state_.installDir + L" mode=" +
            std::to_wstring(mode == faf::InstallMode::Repair ? 1 : 0));
    installThread_ = CreateThread(nullptr, 0, InstallThreadProc, this, 0, nullptr);
    if (!installThread_) {
        installing_ = false;
        keepTickAlive_ = false;
        WriteAbortResult(L"thread-create-failed");  // §1：失败必须写 error=
        if (mode == faf::InstallMode::Repair) {
            ShowError(L"无法开始修复", L"修复线程创建失败，程序文件未改动。", L"关闭", L"");
        } else {
            ShowError(L"无法开始安装", L"安装线程创建失败，程序文件未改动。", L"关闭", L"");
        }
    }
}

void InstallerWindow::StartUninstall() {
    if (mode_ != AppMode::Maintenance && mode_ != AppMode::Uninstall) {
        DiagLog(L"uninstall intent ignored outside maintenance/uninstall mode");
        return;
    }
    if (installing_ || closingApp_ || uninstallRunning_) return;  // 防重入

    // T12：Progress 页复用 —— operation 是唯一来源（SetPage/布局/步骤栏均读它）。
    state_.operation = Operation::Uninstall;
    progressPermille_ = 0;
    uninstallTerminal_ = false;
    SetPage(Progress);
    if (progressPage_) {
        progressPage_->SetKind(faf::ProgressPage::Kind::Uninstall);
        progressPage_->SetCancellable(false);  // 卸载中不允许取消/ESC/X
        progressPage_->SetNotice(L"卸载过程中请勿关闭窗口");
        progressPage_->SetStageText(UninstallStageLabel(faf::UninstallStage::Started));
        progressPage_->SetProgressPermille(0);
    }
    DiagLog(L"uninstall start dir=" + state_.installDir + L" helper_pid=" +
            std::to_wstring(helperPid_) + L" delete_user_data=" +
            std::to_wstring(state_.deleteUserData ? 1 : 0));

    if (mode_ == AppMode::Maintenance) {
        // D3/T12：action 是 decision 的终端键，只写一次。写失败不得开始卸载。
        if (!WriteMaintenanceDecisionOnce(MaintenanceAction::Uninstall)) {
            // 与 T11 预检失败一致：X/ESC 也不得补写 cancel。
            maintenanceSuppressDecision_ = true;
            ShowError(L"无法开始卸载", L"无法写入维护决定文件，卸载未开始。", L"关闭", L"");
            return;
        }
        // setup 必须先 ack（D15 C2：写 ack 后立即 Abort 释放 SetupMutex）；未 ack
        // 就启动 helper 会与仍在运行的 setup 冲突。ack 是启动协调器的前置条件。
        if (!faf::WaitForDecisionAck(decisionPath_, faf::protocol::kAckTimeoutMs)) {
            ShowError(L"无法开始卸载",
                      L"安装程序未在限定时间内确认卸载请求，卸载未开始。", L"关闭", L"");
            return;
        }
    }

    // helperPid_==0 时由协调器先写 request 再启动 helper；非 0 时只附着，不二次启动。
    uninstallCoordinator_ = std::make_shared<faf::UninstallCoordinator>(
        state_.installDir, state_.deleteUserData, GetCurrentProcessId(), helperPid_,
        uninstallRequestPath_, uninstallResultPath_, window_);
    std::wstring error;
    if (!uninstallCoordinator_->Start(&error)) {
        uninstallCoordinator_.reset();
        ShowError(L"无法开始卸载", error.empty() ? L"卸载程序启动失败。" : error, L"关闭",
                  L"");
        return;
    }
    uninstallRunning_ = true;
    // 维护卸载不接入 setup watchdog：setup 在 ack 后按 D15 C2 主动退出，属正常收尾。
    keepTickAlive_ = false;
    DiagLog(L"uninstall coordinator started request=" + uninstallRequestPath_ +
            L" result=" + uninstallResultPath_);
}

// ======================= Todo 12：页面状态机 / 导航接线 =====================

// 前置条件：ApplyReduceMotion() 必须已先于本函数执行——Animator::SetReduceMotion 只影响其后
// 创建的动画，本函数内 StartIntro/ApplyPageEntry 烘焙各页入场动画，早读才能让它们立即终态。
void InstallerWindow::EnsurePages() {
    if (pagesReady_) return;
    IDWriteFactory* dwrite = render_.WriteFactory();
    ID2D1DeviceContext* dc = render_.DeviceContext();
    if (!dwrite || !dc) return;  // render 未就绪：稍后重试

    textFactory_.Initialize(dwrite);
    glyphFont_.Initialize(dwrite);
    logoBitmap_.Load(dc);

    welcomePage_ = std::make_unique<faf::WelcomePage>(state_);
    welcomePage_->BindAnimator(&animator_);
    welcomePage_->BindText(&textFactory_);
    welcomePage_->BindGlyphs(&glyphFont_);
    welcomePage_->SetLogo(&logoBitmap_);
    // 追加需求：欢迎页为英雄页——页内大按钮「下一步」承担前进（无底部导航）。
    welcomePage_->SetOnNextIntent([this]() { GoNext(); });

    licensePage_ = std::make_unique<faf::LicensePage>(state_);
    licensePage_->BindAnimator(&animator_);
    licensePage_->BindText(&textFactory_);
    licensePage_->BindGlyphs(&glyphFont_);
    licensePage_->BindWriteFactory(dwrite);
    // UI-fix：许可页页内「下一步」按钮已移除——门控由 UpdateNavButtons() 读 state_.agreed。

    configurePage_ = std::make_unique<faf::ConfigurePage>(state_);
    configurePage_->SetPayloadDir(payload_);
    configurePage_->SetOwner(window_);
    configurePage_->BindAnimator(&animator_);
    configurePage_->BindText(&textFactory_);
    configurePage_->BindGlyphs(&glyphFont_);
    // Todo 15 证据：Configure 页 PathField 的实际持值（= /installdir 预填结果；页面进入
    // 时 ApplyPageEntry → SyncFromState 会再次从此值同步）。
    DiagLog(L"configure prefill field=" + configurePage_->Field().Path());

    progressPage_ = std::make_unique<faf::ProgressPage>(state_);
    progressPage_->BindAnimator(&animator_);
    progressPage_->BindText(&textFactory_);
    progressPage_->BindGlyphs(&glyphFont_);
    progressPage_->SetOnCancel([this]() { RaiseCancelIntent(); });

    finishPage_ = std::make_unique<faf::FinishPage>(state_);
    finishPage_->BindAnimator(&animator_);
    finishPage_->BindText(&textFactory_);
    finishPage_->BindGlyphs(&glyphFont_);
    finishPage_->SetLogo(&logoBitmap_);  // 英雄页图标（成功对勾由页内动画绘制，Logo 备用）
    // 追加需求：完成页为英雄页——大按钮「立即启动」= 无条件去提权启动 + 关窗。
    finishPage_->SetOnFinishIntent([this]() { OnFinishIntent(); });

    // T10：三个英雄页（T7）。回调仅接到本类的占位接缝；T11/T12/T13 替换为真实业务。
    maintenancePage_ = std::make_unique<faf::MaintenancePage>(state_);
    maintenancePage_->BindAnimator(&animator_);
    maintenancePage_->BindText(&textFactory_);
    maintenancePage_->BindGlyphs(&glyphFont_);
    maintenancePage_->SetOnRepair([this]() { OnMaintenanceRepairIntent(); });
    maintenancePage_->SetOnUninstall([this]() { OnMaintenanceUninstallIntent(); });
    maintenancePage_->SetOnCancel([this]() { OnMaintenanceCancelIntent(); });

    uninstallConfirmPage_ = std::make_unique<faf::UninstallConfirmPage>(state_);
    uninstallConfirmPage_->BindAnimator(&animator_);
    uninstallConfirmPage_->BindText(&textFactory_);
    uninstallConfirmPage_->BindGlyphs(&glyphFont_);
    uninstallConfirmPage_->SetOnConfirm([this]() { OnUninstallConfirmIntent(); });
    uninstallConfirmPage_->SetOnCancel([this]() { OnUninstallCancelIntent(); });

    messagePage_ = std::make_unique<faf::MessagePage>(state_);
    messagePage_->BindAnimator(&animator_);
    messagePage_->BindText(&textFactory_);
    messagePage_->BindGlyphs(&glyphFont_);
    messagePage_->SetOnPrimary([this]() { OnMessagePrimaryIntent(); });
    messagePage_->SetOnSecondary([this]() { OnMessageSecondaryIntent(); });

    for (int i = 0; i < kStepCount; ++i) {
        stepItems_[i].SetIndex(i);
        stepItems_[i].SetLabel(kStepLabels[i]);
        stepItems_[i].SetLast(i == kStepCount - 1);
        stepItems_[i].BindAnimator(&animator_);
        stepItems_[i].BindText(&textFactory_);
        stepItems_[i].BindGlyphs(&glyphFont_);
    }

    backButton_.SetLabel(L"上一步");
    backButton_.SetStyle(faf::Button::Secondary);
    backButton_.SetOnClick([this]() { GoBack(); });
    backButton_.BindAnimator(&animator_);
    backButton_.BindText(&textFactory_);
    backButton_.BindGlyphs(&glyphFont_);

    nextButton_.SetLabel(L"下一步");
    nextButton_.SetStyle(faf::Button::Accent);
    nextButton_.SetOnClick([this]() { GoNext(); });
    nextButton_.BindAnimator(&animator_);
    nextButton_.BindText(&textFactory_);
    nextButton_.BindGlyphs(&glyphFont_);

    shellHost_.Add(&backButton_);
    shellHost_.Add(&nextButton_);

    pagesReady_ = true;
    // T14：启动期致命错误优先于任何模式初始化（维护模式绝不能因此进入
    // EnterMaintenanceMode/Detect 流程，卸载模式也不能进入确认页）。
    if (!startupErrorTitle_.empty()) {
        exitCode_ = 1;
        DiagLog(L"startup error page shown title=" + startupErrorTitle_);
        ShowError(startupErrorTitle_, startupErrorBody_, L"关闭", L"");
        RequestAnimTick();
        return;
    }
    if (mode_ == AppMode::Maintenance) {
        // T11：维护模式的初始页 = 页 5（Detect + SetInfo），而非安装向导的欢迎页。
        // EnterMaintenanceMode 内部经 SetPage 完成 shell 几何重算 + ApplyPageEntry。
        EnterMaintenanceMode();
    } else {
        // T12：/uninstall 的初始页 = 卸载确认页（不是安装向导的欢迎页）。
        if (mode_ == AppMode::Uninstall) {
            state_.page = UninstallConfirm;
            shellLayout_ = faf::ComputeShellLayout(
                faf::IsHeroPage(state_.page) || state_.operation != Operation::Install);
        }
        LayoutStepBar();
        LayoutFooterButtons();
        ApplyPageEntry();
    }
    RequestAnimTick();
    DiagLog(L"pages ready count=8");
}

D2D1_RECT_F InstallerWindow::PageRect() const {
    // 页内容矩形 = 内容卡片 + Win10 兜底外扩边距（页布局与命中坐标同偏移）。
    const float m = static_cast<float>(shadowMarginDip_);
    const D2D1_RECT_F& c = shellLayout_.contentCard;
    return D2D1::RectF(c.left + m, c.top + m, c.right + m, c.bottom + m);
}

void InstallerWindow::LayoutStepBar() {
    // 追加需求：横向 3 节点进度带——stepItems_ 均分 stepper 宽度（每列一段；节点居列底、
    // 标签居列中、连接线自上一列中心到本列节点）。
    const D2D1_RECT_F& band = shellLayout_.stepper;
    const float colW = (band.right - band.left) / static_cast<float>(kStepCount);
    for (int i = 0; i < kStepCount; ++i) {
        stepItems_[i].SetOrientation(faf::StepItem::Orientation::Horizontal);
        const float left = band.left + colW * static_cast<float>(i);
        stepItems_[i].SetBounds(D2D1::RectF(left, band.top, left + colW, band.bottom));
    }
}

// UI-fix：底部按钮条统一布局——外壳导航按钮（画布坐标）+ 页托管按钮（取消/打开目录/完成，
// 页坐标 = 画布 + shadowMarginDip_）。页面自身 Layout 不再摆放这些按钮；本函数在每次页面
// Layout（Layout/EnsurePages/LayoutPages/ApplyPageEntry）之后调用，保持按钮与 shell 几何同步。
void InstallerWindow::LayoutFooterButtons() {
    const D2D1_RECT_F& bar = shellLayout_.bottomBar;
    // 追加需求：英雄页（欢迎/完成）bottomBar 为空矩形 → 无底部条（导航/页托管按钮均不参与）。
    const bool hasBar = bar.right > bar.left && bar.bottom > bar.top;
    const float cy = hasBar ? (bar.top + bar.bottom) * 0.5f : 0.0f;
    backButton_.SetBounds(D2D1::RectF(kNavBackCenterX - kNavButtonW * 0.5f,
                                      cy - kNavButtonH * 0.5f,
                                      kNavBackCenterX + kNavButtonW * 0.5f,
                                      cy + kNavButtonH * 0.5f));
    nextButton_.SetBounds(D2D1::RectF(kNavNextCenterX - kNavButtonW * 0.5f,
                                      cy - kNavButtonH * 0.5f,
                                      kNavNextCenterX + kNavButtonW * 0.5f,
                                      cy + kNavButtonH * 0.5f));
    if (!pagesReady_) return;

    const float m = static_cast<float>(shadowMarginDip_);
    const float rowTop = cy - kNavButtonH * 0.5f + m;
    const float rowBottom = cy + kNavButtonH * 0.5f + m;
    if (progressPage_ && hasBar) {
        progressPage_->CancelButton().SetBounds(D2D1::RectF(
            kFooterRightEdgeX - kCancelButtonW + m, rowTop, kFooterRightEdgeX + m, rowBottom));
    }
    // 追加需求：完成页「立即启动」大按钮改由 FinishPage::Layout 自行居中摆放（英雄页无底部条），
    // 外壳不再托管 openDir/finish 按钮（二者已从 FinishPage 删除）。
}

void InstallerWindow::LayoutPages() {
    if (!pagesReady_) return;
    const D2D1_RECT_F card = PageRect();
    switch (state_.page) {
        case Welcome: welcomePage_->Layout(card); break;
        case License: licensePage_->Layout(card); break;
        case Configure: configurePage_->Layout(card); break;
        case Progress:
            // T10：Repair/Uninstall 复用 Progress 页 —— 布局前同步操作类型。
            progressPage_->SetKind(state_.operation);
            progressPage_->Layout(card);
            break;
        case Finish:
            // T10：Repair/Uninstall 复用 Finish 页 —— 布局前同步操作类型。
            finishPage_->SetKind(state_.operation);
            finishPage_->Layout(card);
            break;
        case Maintenance: maintenancePage_->Layout(card); break;
        case UninstallConfirm: uninstallConfirmPage_->Layout(card); break;
        case Message: messagePage_->Layout(card); break;
        default: break;
    }
    // UI-fix：页面 Layout 之后刷新底部条（页托管按钮随页布局同步）。
    LayoutFooterButtons();
}

void InstallerWindow::ApplyPageEntry() {
    if (!pagesReady_) return;
    const D2D1_RECT_F card = PageRect();
    switch (state_.page) {
        case Welcome:
            welcomePage_->ResetIntro();
            welcomePage_->SyncFromState();
            welcomePage_->Layout(card);
            break;
        case License:
            licensePage_->ResetIntro();
            licensePage_->SyncFromState();
            licensePage_->Layout(card);
            break;
        case Configure:
            configurePage_->OnEnter();
            configurePage_->Layout(card);
            break;
        case Progress:
            // T10：页 3 复用（修复/卸载）时先同步 Kind，再渲染进度与文案。
            progressPage_->SetKind(state_.operation);
            progressPage_->Layout(card);
            progressPage_->SetProgressPermille(progressPermille_);
            break;
        case Finish:
            // T10：页 4 复用（修复/卸载）时先同步 Kind，再启动对勾动画。
            finishPage_->SetKind(state_.operation);
            finishPage_->Layout(card);
            finishPage_->StartCheckAnim();
            break;
        case Maintenance:
            // T11 在 OnEnter 时 Detect() + SetInfo()；此处只做几何布局。
            maintenancePage_->Layout(card);
            break;
        case UninstallConfirm:
            // T12：每次进入确认页都重置为“不删除用户数据”（D15 C3 默认 false）。
            state_.deleteUserData = false;
            uninstallConfirmPage_->SyncFromState();
            uninstallConfirmPage_->Layout(card);
            break;
        case Message:
            messagePage_->Layout(card);
            break;
        default:
            break;
    }
    SyncStepBar();
    UpdateNavButtons();
    // UI-fix：页面切换后重摆底部条（含页托管的取消/完成按钮）。
    LayoutFooterButtons();
    // 追加需求：英雄页⇄向导页切换会改变 shell 几何（步骤带有无）——必须按当前几何重排步骤带，
    // 否则向导页的 3 个横向节点会沿用英雄页的空 bounds（不可见）。
    LayoutStepBar();
}

void InstallerWindow::SyncStepBar() {
    // 追加需求：页 → 3 节点映射（License→0「协议」/ Configure→1「配置」/ Progress→2「部署」）；
    // 英雄页（欢迎/完成）无步骤带 → 映射为 -1（不点亮任何节点）。
    // T10：仅安装操作映射 0/1/2；修复/卸载（含复用 Progress 页）一律 -1。
    int step = -1;
    if (state_.operation == Operation::Install) {
        switch (state_.page) {
            case License: step = 0; break;
            case Configure: step = 1; break;
            case Progress: step = 2; break;
            default: step = -1; break;
        }
    }
    for (int i = 0; i < kStepCount; ++i) stepItems_[i].SetStep(i, step);
}

void InstallerWindow::UpdateNavButtons() {
    if (!pagesReady_) return;
    bool canBack = false;
    bool canNext = false;
    // UI-fix：按页面决定外壳导航按钮的可见性（期间始终禁用，见下方门控）。
    // 追加需求：英雄页（欢迎/完成）全隐藏——前进/启动由页内大按钮承担。
    switch (state_.page) {
        case Welcome:
            navBackVisible_ = false;  // 英雄页无外壳导航
            navNextVisible_ = false;
            break;
        case License:
            navBackVisible_ = true;
            navNextVisible_ = true;
            canNext = state_.agreed;
            canBack = true;
            break;
        case Configure:
            navBackVisible_ = true;
            navNextVisible_ = true;
            canNext = configurePage_ && configurePage_->CanProceed();
            canBack = true;
            break;
        // T10：安装/修复/卸载的进度与完成页均无外壳导航（页内按钮自行摆放）；
        // 维护 / 卸载确认 / 消息页为英雄页，同样隐藏外壳导航。
        case Progress:
        case Finish:
        case Maintenance:
        case UninstallConfirm:
        case Message:
        default:
            navBackVisible_ = false;
            navNextVisible_ = false;
            break;
    }
    if (installing_ || uninstallRunning_) {  // 「安装/卸载中不可返回/前进」
        canBack = false;
        canNext = false;
    }
    // UI-fix：下一步按钮文案随页面切换（配置页 = 「安装」）。
    nextButton_.SetLabel(state_.page == Configure ? L"安装" : L"下一步");
    backButton_.SetEnabled(canBack);
    nextButton_.SetEnabled(canNext);
}

void InstallerWindow::GoNext() {
    if (installing_) return;
    switch (state_.page) {
        case Welcome:
            SetPage(License);
            break;
        case License:
            if (!state_.agreed) return;  // 未勾选同意不得前进
            SetPage(Configure);
            break;
        case Configure:
            if (!configurePage_ || !configurePage_->CanProceed()) return;  // 不可写/空间不足
            configurePage_->SyncToState();  // 四选项写回 AppState
            StartInstall();  // 内部 SetPage(Progress) + 起安装线程
            break;
        default:
            return;  // Progress/Finish 无下一步
    }
    UpdateNavButtons();
}

void InstallerWindow::GoBack() {
    if (installing_) return;  // 「安装中不可返回」
    switch (state_.page) {
        case License:
            SetPage(Welcome);
            break;
        case Configure:
            SetPage(License);
            break;
        default:
            return;  // Welcome/Progress/Finish 无上一步
    }
    UpdateNavButtons();
}

void InstallerWindow::RaiseCancelIntent() {
    DiagLog(L"cancel intent raised installing=" + std::to_wstring(installing_ ? 1 : 0));
    // Todo 13：安装中同时置引擎取消信号（§3：安全停止 + 清理本次写入 + abort=1）。
    if (installing_) cancel_ = true;
    if (progressPage_) progressPage_->RequestCancel();
    RequestAnimTick();
}

void InstallerWindow::OnEscape() {
    // T13：ESC 与 WM_CLOSE 完全同义，不再提前用 installing_/uninstallRunning_ 拦截。
    // 模式差异全部交给 WM_CLOSE 分支：
    //   * Install 安装中 → closePending_ + RaiseCancelIntent（既有取消/清理流程）；
    //   * Repair/Uninstall Progress → On*CloseIntent 内忽略（且不置 closePending_）；
    //   * Finish → T11/T12 的完成动作（Uninstall 写 ui_done）。
    PostMessageW(window_, WM_CLOSE, 0, 0);
}

// ===================== T11：维护与修复流程 =====================
// 生命周期总览（D3/D9）：
//   维护页 → 修复意图 → 预检 → [app 运行中 ? 异步关闭（WM_APP_CLOSE_DONE）: 直接]
//   → WriteMaintenanceDecision(repair)（终端键，一次性）→ Progress(Repair) → 引擎
//   → 成功 Finish(Repair) / 失败 Message（窗口保持打开）。
// 取消 / WM_CLOSE / ESC 在维护模式下写一次 cancel decision 后关窗；修复进行中一律忽略。

void InstallerWindow::EnterMaintenanceMode() {
    if (!maintenancePage_) return;
    // T11：Detect 是唯一的安装判定来源（exe 或 _internal 存在）；版本/选项一并读取。
    maintenanceInfo_ = faf::Detect(state_.installDir);
    if (!maintenanceInfo_.installDir.empty()) {
        state_.installDir = maintenanceInfo_.installDir;  // 归一化后的路径（D10）
    }
    state_.installedVersion = maintenanceInfo_.version;
    state_.installDetected = maintenanceInfo_.detected;
    maintenancePage_->SetInfo(maintenanceInfo_.installDir, maintenanceInfo_.version,
                              maintenanceInfo_.detected, maintenanceInfo_.complete);
    DiagLog(L"maintenance detect dir=" + maintenanceInfo_.installDir + L" detected=" +
            std::to_wstring(maintenanceInfo_.detected ? 1 : 0) + L" complete=" +
            std::to_wstring(maintenanceInfo_.complete ? 1 : 0) + L" version=" +
            maintenanceInfo_.version + L" inferred=" +
            std::to_wstring(maintenanceInfo_.optionsInferred ? 1 : 0));

    if (!maintenanceInfo_.detected) {
        // 未检测到安装：只给“关闭”，绝不写 decision、绝不进入修复。
        // suppress 标志同时覆盖用户直接点 X / ESC 的关闭路径（同样不写 decision）。
        maintenanceSuppressDecision_ = true;
        ShowError(L"未找到已安装的 FreeAssetFilter",
                  L"在 " + state_.installDir +
                      L" 未检测到 FreeAssetFilter 的程序文件，无法执行修复。",
                  L"关闭", L"");
        return;
    }
    SetPage(Maintenance);
}

bool InstallerWindow::RepairPreflight(std::wstring* error) const {
    const auto fail = [error](const std::wstring& text) {
        if (error) *error = text;
        return false;
    };
    if (!maintenanceInfo_.detected) {
        return fail(L"未检测到已安装的 FreeAssetFilter，无法修复。");
    }
    const std::wstring& dir = state_.installDir;
    if (dir.empty()) return fail(L"安装目录为空，无法修复。");
    const DWORD attrs = GetFileAttributesW(dir.c_str());
    if (attrs == INVALID_FILE_ATTRIBUTES || (attrs & FILE_ATTRIBUTE_DIRECTORY) == 0) {
        return fail(L"安装目录不存在：" + dir);
    }
    // 可写探测：在安装目录内创建带 PID 的临时文件（FILE_FLAG_DELETE_ON_CLOSE，关闭即
    // 自动删除，不残留、不触碰用户数据）。磁盘空间**不在此处检查**：T6 引擎在哨兵
    // 预扫描之后、首次写入之前判定（D15 H1），避免重复口径。
    const std::wstring probe = dir + L"\\.faf-repair-probe-" +
                               std::to_wstring(GetCurrentProcessId()) + L".tmp";
    HANDLE file = CreateFileW(probe.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS,
                              FILE_ATTRIBUTE_TEMPORARY | FILE_FLAG_DELETE_ON_CLOSE, nullptr);
    if (file == INVALID_HANDLE_VALUE) {
        return fail(L"安装目录不可写（错误码 " + std::to_wstring(GetLastError()) + L"）：" + dir);
    }
    CloseHandle(file);
    return true;
}

bool InstallerWindow::WriteMaintenanceDecisionOnce(MaintenanceAction action) {
    if (mode_ != AppMode::Maintenance) return false;
    // action 是 decision 的终端键：写成功后任何后续关闭/取消都不得覆盖。
    if (maintenanceDecisionWritten_) return false;
    // 未检测到安装 / 预检失败路径明确不写 decision（D15 H1 的“不写”要求）。
    if (maintenanceSuppressDecision_) return false;
    if (decisionPath_.empty()) {
        DiagLog(L"maintenance decision path empty -> not written");
        return false;
    }
    const int actionValue = static_cast<int>(action);
    const bool ok = faf::WriteMaintenanceDecision(decisionPath_, action, GetCurrentProcessId());
    if (ok) maintenanceDecisionWritten_ = true;
    DiagLog(L"maintenance decision action=" + std::to_wstring(actionValue) + L" ok=" +
            std::to_wstring(ok ? 1 : 0) + L" path=" + decisionPath_);
    return ok;
}

void InstallerWindow::StartRepair() {
    if (mode_ != AppMode::Maintenance) {
        DiagLog(L"repair intent ignored outside maintenance mode");
        return;
    }
    if (installing_ || closingApp_) return;  // 已在进行中：防重入

    std::wstring error;
    if (!RepairPreflight(&error)) {
        // 预检失败：不写 decision、不启动引擎（空间检查留给引擎预扫描）。
        // suppress 必须在展示前置位：X/ESC 走 OnMaintenanceCloseIntent 也不得补写 cancel。
        maintenanceSuppressDecision_ = true;
        DiagLog(L"repair preflight failed: " + error);
        ShowError(L"无法修复", error, L"关闭", L"");
        return;
    }

    // T11：选项沿用 Detect 的注册表/推断结果；修复完成页的「立即启动」默认不勾选。
    state_.operation = Operation::Repair;
    state_.optDesktop = maintenanceInfo_.optDesktop;
    state_.optStartmenu = maintenanceInfo_.optStartmenu;
    state_.optAutostart = maintenanceInfo_.optAutostart;
    state_.optLaunchAfterRepair = false;

    if (!IsInstalledAppRunning(state_.installDir)) {
        // 未运行：直接写 decision 并开始修复。
        BeginRepairInstall();
        return;
    }

    // 运行中：先异步关闭（faf::CloseInstalledApp 按完整路径匹配，最长 5s 优雅 + 2s 强制），
    // 关闭成功后才允许写 decision —— D9 的硬性顺序要求。
    DiagLog(L"repair closing running app dir=" + state_.installDir);
    closingApp_ = true;
    keepTickAlive_ = true;  // 关闭等待期间也保持 watchdog 运行
    closeTargetDir_ = state_.installDir;
    {
        std::lock_guard<std::mutex> lock(closeMutex_);
        closeError_.clear();
        closeForced_ = false;
    }
    messagePrimaryAction_ = MessageAction::None;
    messageSecondaryAction_ = MessageAction::None;
    messagePage_->SetContent(L"正在关闭 FreeAssetFilter",
                             L"修复前需要先关闭正在运行的 FreeAssetFilter，请稍候。", L"", L"",
                             false);
    messagePage_->SetBusy(true, L"正在关闭…");
    SetPage(Message);
    RequestAnimTick();

    closeThread_ = CreateThread(nullptr, 0, CloseThreadProc, this, 0, nullptr);
    if (!closeThread_) {
        closingApp_ = false;
        keepTickAlive_ = false;
        // T13：保留 T11 的「重试 / 取消」决策语义（取消 = 写一次 maintenance cancel）。
        ShowError(L"无法关闭 FreeAssetFilter",
                  L"无法创建关闭线程，请手动退出 FreeAssetFilter 后重试。", L"重试",
                  MessageAction::RetryRepair, L"取消", MessageAction::CancelMaintenance);
    }
}

void InstallerWindow::BeginRepairInstall() {
    if (state_.setupExited) {
        // setup 已退出：不再开始任何写操作（避免无主修复）。
        ShowError(L"修复已终止", L"安装程序已退出，操作已终止", L"关闭", L"");
        return;
    }
    if (!WriteMaintenanceDecisionOnce(MaintenanceAction::Repair)) {
        // decision 写不进去就不能开始修复：setup 无法获知 repair 意图。
        // 同样在展示前置 suppress —— 关闭（X/ESC）也不得再补写 cancel。
        maintenanceSuppressDecision_ = true;
        ShowError(L"无法开始修复", L"无法写入维护决定文件，修复未开始。", L"关闭", L"");
        return;
    }
    StartInstall(faf::InstallMode::Repair);
}

void InstallerWindow::ShowMessagePage(std::wstring title, std::wstring body,
                                      std::wstring primaryLabel, MessageAction primary,
                                      std::wstring secondaryLabel, MessageAction secondary) {
    if (!messagePage_) return;
    const bool showSecondary = secondary != MessageAction::None && !secondaryLabel.empty();
    // 先设内容/按钮语义再切页：SetPage → ApplyPageEntry → Layout 会按新内容排版，
    // 避免首帧显示上一条消息（busy 态也必须显式解除）。
    messagePage_->SetBusy(false);
    messagePage_->SetContent(std::move(title), std::move(body), std::move(primaryLabel),
                             std::move(secondaryLabel), showSecondary);
    messagePrimaryAction_ = primary;
    messageSecondaryAction_ = showSecondary ? secondary : MessageAction::None;
    SetPage(Message);
}

void InstallerWindow::ShowError(std::wstring title, std::wstring body,
                                std::wstring primaryLabel, std::wstring secondaryLabel) {
    // T13：默认「关闭」走统一 WM_CLOSE 路径，让各模式既有的决策守卫生效：
    //   * 维护模式：suppress（未检测到安装/预检失败）时不写 cancel；decision 已写
    //     （repair/uninstall 终端）时不覆盖；仅未开始的普通关闭补一次 cancel。
    //   * /uninstall：直接销毁，绝不写 maintenance decision。
    //   * Install：非安装中按既有 WriteCancelResult（resultWritten_ 守卫防覆盖）。
    // 次按钮若传入标签也走同一关闭语义（关闭失败路径会用带 action 的重载覆盖）。
    ShowError(std::move(title), std::move(body), std::move(primaryLabel), MessageAction::Close,
              std::move(secondaryLabel), MessageAction::Close);
}

void InstallerWindow::ShowError(std::wstring title, std::wstring body,
                                std::wstring primaryLabel, MessageAction primary,
                                std::wstring secondaryLabel, MessageAction secondary) {
    // T13：薄封装——错误页复用既有 Message 页与 MessageAction 决策机，不新增页面。
    ShowMessagePage(std::move(title), std::move(body), std::move(primaryLabel), primary,
                    std::move(secondaryLabel), secondary);
}

void InstallerWindow::HandleMessageAction(MessageAction action) {
    switch (action) {
        case MessageAction::None:
            return;
        case MessageAction::Close:
            // 统一关闭路径（维护模式尚未写 decision 时由 OnMaintenanceCloseIntent 补 cancel）。
            PostMessageW(window_, WM_CLOSE, 0, 0);
            return;
        case MessageAction::CloseNoDecision:
            // 未检测到安装 / 预检失败：明确禁止任何 decision 写入。
            maintenanceSuppressDecision_ = true;
            PostMessageW(window_, WM_CLOSE, 0, 0);
            return;
        case MessageAction::CancelMaintenance:
            WriteMaintenanceDecisionOnce(MaintenanceAction::Cancel);
            PostMessageW(window_, WM_CLOSE, 0, 0);
            return;
        case MessageAction::RetryRepair:
            StartRepair();
            return;
        case MessageAction::RetryUninstall:
            // 关闭已安装应用失败后的重试：必须重新执行“是否运行中”检查。
            OnUninstallConfirmIntent();
            return;
    }
}

DWORD WINAPI InstallerWindow::CloseThreadProc(LPVOID p) {
    static_cast<InstallerWindow*>(p)->CloseAppThread();
    return 0;
}

void InstallerWindow::CloseAppThread() {
    // 工作线程只做内核/用户枚举 + PostMessage，绝不触碰 UI。
    const faf::ProcessCloseResult result =
        faf::CloseInstalledApp(closeTargetDir_, /*gracefulTimeoutMs=*/5000,
                               /*forceTimeoutMs=*/2000);
    {
        std::lock_guard<std::mutex> lock(closeMutex_);
        closeError_ = result.error;
        closeForced_ = result.forced;
    }
    PostMessageW(window_, WM_APP_CLOSE_DONE, result.ok ? 1 : 0, 0);
}

void InstallerWindow::FinishCloseThread() {
    if (!closeThread_) return;
    // close worker 最长 7s（5s 优雅 + 2s 强制）；析构路径必须 join，否则 worker 可能在
    // 本对象销毁后继续访问 closeTargetDir_/closeMutex_。UI 线程的完成路径此时 join 立即
    // 返回（worker 已 PostMessage 并即将退出）。
    //
    // T13：使用 INFINITE 显式 join——CloseInstalledApp 内部所有等待均有界；固定 15s
    // 超时后仍关闭句柄会让 worker 在 this 析构后继续使用成员（use-after-free）。
    WaitForSingleObject(closeThread_, INFINITE);
    CloseHandle(closeThread_);
    closeThread_ = nullptr;
}

void InstallerWindow::FinishInstallThread() {
    if (!installThread_) return;
    // T13：安装/修复 worker 通过 this 读写引擎状态、错误槽并向 window_ PostMessage。
    // 异常销毁（窗口已 DestroyWindow 但 worker 尚未投递 WM_INSTALL_DONE）时必须先
    // 置取消，再显式 join；引擎的哨兵等待与复制循环都会轮询 cancel_，因此可退出。
    cancel_ = true;
    WaitForSingleObject(installThread_, INFINITE);
    CloseHandle(installThread_);
    installThread_ = nullptr;
    installing_ = false;
}

void InstallerWindow::CheckSetupWatchdog() {
    if (!setupProcess_ || state_.setupExited) return;
    // T12：维护卸载在 setup ack 后，setup 主动退出属于正常收尾（D15 C2），
    // 不得按“setup 提前退出”中止卸载。
    if (uninstallRunning_) return;
    // 仅在操作进行中监视：维护页/完成页停留时 setup 退出属于正常收尾，不应中止。
    if (!installing_ && !closingApp_) return;
    if (WaitForSingleObject(setupProcess_, 0) != WAIT_OBJECT_0) return;
    state_.setupExited = true;
    cancel_ = true;             // 引擎在下一个轮询点安全停止（repair 不回滚）
    installTimedOut_ = true;    // 保留既有超时分流语义，UI 文案以 setupExited 为准
    DiagLog(L"setup exited during operation installing=" +
            std::to_wstring(installing_ ? 1 : 0) + L" closing=" +
            std::to_wstring(closingApp_ ? 1 : 0));
    RequestAnimTick();
}

void InstallerWindow::OnMaintenanceRepairIntent() {
    DiagLog(L"maintenance repair intent");
    StartRepair();
}

void InstallerWindow::OnMaintenanceUninstallIntent() {
    // T11：只导航到卸载确认页（页 6）；request/helper/进程收尾全部归 T12。
    // 导航本身不写 decision（只有用户最终选择 uninstall 时才由 T12 写）。
    DiagLog(L"maintenance uninstall intent -> UninstallConfirm");
    SetPage(UninstallConfirm);
}

void InstallerWindow::OnMaintenanceCancelIntent() {
    // 维护页「取消」：写一次 cancel decision 后走统一关闭路径（守卫防二次写）。
    DiagLog(L"maintenance cancel intent");
    if (installing_ || closingApp_) return;  // 修复进行中：取消不可用（双保险）
    WriteMaintenanceDecisionOnce(MaintenanceAction::Cancel);
    PostMessageW(window_, WM_CLOSE, 0, 0);
}

void InstallerWindow::OnUninstallConfirmIntent() {
    // T12：SyncToState → 关闭 app（如运行中）→ 写 request → 启动/附着 helper。
    if (mode_ != AppMode::Maintenance && mode_ != AppMode::Uninstall) {
        DiagLog(L"uninstall confirm ignored outside maintenance/uninstall mode");
        return;
    }
    if (installing_ || closingApp_ || uninstallRunning_) return;  // 防重入
    if (!uninstallConfirmPage_) return;

    uninstallConfirmPage_->SyncToState();
    DiagLog(L"uninstall confirm dir=" + state_.installDir + L" delete_user_data=" +
            std::to_wstring(state_.deleteUserData ? 1 : 0));

    if (!IsInstalledAppRunning(state_.installDir)) {
        StartUninstall();
        return;
    }

    // 已安装应用运行中：沿用 T11 的 CloseThread 模式异步关闭；关闭成功后才允许
    // 写 request / 启动 helper（D9 的“先关闭再操作”顺序）。
    DiagLog(L"uninstall closing running app dir=" + state_.installDir);
    pendingUninstallClose_ = true;
    closingApp_ = true;
    keepTickAlive_ = true;
    closeTargetDir_ = state_.installDir;
    {
        std::lock_guard<std::mutex> lock(closeMutex_);
        closeError_.clear();
        closeForced_ = false;
    }
    messagePrimaryAction_ = MessageAction::None;
    messageSecondaryAction_ = MessageAction::None;
    messagePage_->SetContent(L"正在关闭 FreeAssetFilter",
                             L"卸载前需要先关闭正在运行的 FreeAssetFilter，请稍候。", L"",
                             L"", false);
    messagePage_->SetBusy(true, L"正在关闭…");
    SetPage(Message);
    RequestAnimTick();

    closeThread_ = CreateThread(nullptr, 0, CloseThreadProc, this, 0, nullptr);
    if (!closeThread_) {
        closingApp_ = false;
        keepTickAlive_ = false;
        pendingUninstallClose_ = false;
        const MessageAction secondary = mode_ == AppMode::Maintenance
                                            ? MessageAction::CancelMaintenance
                                            : MessageAction::Close;
        ShowError(L"无法关闭 FreeAssetFilter",
                  L"无法创建关闭线程，请手动退出 FreeAssetFilter 后重试。", L"重试",
                  MessageAction::RetryUninstall, L"取消", secondary);
    }
}

void InstallerWindow::OnUninstallCancelIntent() {
    // T12：维护模式的确认页取消 → 返回维护页（不关窗、不写 decision）；
    // /uninstall 模式：helper 启动的 UI 先写 cancelled=1 再退出，直接启动则直接退出。
    if (installing_ || closingApp_ || uninstallRunning_) return;
    if (mode_ == AppMode::Maintenance) {
        DiagLog(L"uninstall cancel -> Maintenance");
        SetPage(Maintenance);
        return;
    }
    if (mode_ == AppMode::Uninstall) {
        if (helperPid_ != 0) {
            const bool ok = faf::WriteUninstallCancel(uninstallRequestPath_);
            DiagLog(L"uninstall cancel request written=" + std::to_wstring(ok ? 1 : 0) +
                    L" path=" + uninstallRequestPath_);
        }
        PostMessageW(window_, WM_CLOSE, 0, 0);
    }
}

void InstallerWindow::OnMessagePrimaryIntent() {
    DiagLog(L"message primary intent action=" +
            std::to_wstring(static_cast<int>(messagePrimaryAction_)));
    HandleMessageAction(messagePrimaryAction_);
}

void InstallerWindow::OnMessageSecondaryIntent() {
    DiagLog(L"message secondary intent action=" +
            std::to_wstring(static_cast<int>(messageSecondaryAction_)));
    HandleMessageAction(messageSecondaryAction_);
}

void InstallerWindow::OnCloseDoneMessage(WPARAM wp) {
    if (!closingApp_) {
        DiagLog(L"close-done ignored (no close in progress) ok=" + std::to_wstring(wp ? 1 : 0));
        return;
    }
    const bool forUninstall = pendingUninstallClose_;
    if (!forUninstall && mode_ != AppMode::Maintenance) {
        DiagLog(L"close-done ignored outside maintenance/repair path ok=" +
                std::to_wstring(wp ? 1 : 0));
        return;
    }
    closingApp_ = false;
    keepTickAlive_ = false;
    FinishCloseThread();
    std::wstring error;
    bool forced = false;
    {
        std::lock_guard<std::mutex> lock(closeMutex_);
        error = closeError_;
        forced = closeForced_;
    }
    DiagLog(L"close-done ok=" + std::to_wstring(wp ? 1 : 0) + L" forced=" +
            std::to_wstring(forced ? 1 : 0) + L" uninstall=" +
            std::to_wstring(forUninstall ? 1 : 0) + L" error=" + error);
    if (wp != 0) {
        pendingUninstallClose_ = false;
        if (forUninstall) {
            // 卸载前置关闭成功：现在才允许写 request / 启动 helper。
            StartUninstall();
        } else {
            // 关闭成功：现在才允许写 repair decision 并进入 Progress。
            BeginRepairInstall();
        }
        return;
    }

    // 关闭失败：不写 decision/request；给「重试 / 取消」。
    // 重试必须重新执行关闭检查（RetryUninstall → OnUninstallConfirmIntent）。
    pendingUninstallClose_ = false;
    const std::wstring body =
        L"关闭已安装的 FreeAssetFilter 失败（" +
        (error.empty() ? std::wstring(L"未知错误") : error) +
        L"）。请手动退出程序后重试。";
    if (forUninstall) {
        const MessageAction secondary = mode_ == AppMode::Maintenance
                                            ? MessageAction::CancelMaintenance
                                            : MessageAction::Close;
        ShowError(L"无法关闭 FreeAssetFilter", body, L"重试",
                  MessageAction::RetryUninstall, L"取消", secondary);
        return;
    }
    ShowError(L"无法关闭 FreeAssetFilter", body, L"重试", MessageAction::RetryRepair,
              L"取消", MessageAction::CancelMaintenance);
}

void InstallerWindow::OnUninstallProgressMessage(WPARAM wp, LPARAM lp) {
    // T12：wParam=permille 0..1000，lParam=protocol::UninstallStage（中文文案在此映射）。
    if (state_.operation != Operation::Uninstall) return;
    if (uninstallTerminal_) return;          // 终态后忽略陈旧进度
    if (state_.page != Progress) return;     // 仅进度页消费
    const int stageValue = static_cast<int>(static_cast<long long>(lp));
    if (!IsKnownUninstallStage(stageValue)) return;
    const auto stage = static_cast<faf::UninstallStage>(stageValue);
    const unsigned long long rawPermille = static_cast<unsigned long long>(wp);
    const int permille = rawPermille > 1000ull ? 1000 : static_cast<int>(rawPermille);
    progressPermille_ = permille;
    if (progressPage_) {
        progressPage_->SetProgressPermille(permille);
        progressPage_->SetStageText(UninstallStageLabel(stage));
        // D15 C3：未勾选删除用户数据时，helper 跳过用户数据阶段并保留全部数据。
        if (stage == faf::UninstallStage::RemovingUserData && !state_.deleteUserData) {
            progressPage_->SetNotice(L"用户数据已保留");
        }
    }
    DiagLog(L"uninstall-progress permille=" + std::to_wstring(permille) + L" stage=" +
            std::to_wstring(stageValue));
    RequestAnimTick();
}

void InstallerWindow::OnUninstallDoneMessage(WPARAM wp, LPARAM lp) {
    // T12/D15 C1：wParam=终端 UninstallStage（Done/Failed/Cancelled）；warning 不参与。
    (void)lp;
    const int stageValue = static_cast<int>(static_cast<long long>(wp));
    if (!IsTerminalUninstallStage(stageValue)) {
        DiagLog(L"uninstall-done ignored non-terminal stage=" + std::to_wstring(stageValue));
        return;
    }
    if (state_.operation != Operation::Uninstall) return;
    if (uninstallTerminal_) return;  // 只认第一个终态
    uninstallTerminal_ = true;
    uninstallRunning_ = false;
    keepTickAlive_ = false;
    const auto stage = static_cast<faf::UninstallStage>(stageValue);
    DiagLog(L"uninstall-done stage=" + std::to_wstring(stageValue));

    switch (stage) {
        case faf::UninstallStage::Done:
            progressPermille_ = 1000;
            if (progressPage_) progressPage_->SetProgressPermille(1000);
            // warning 仅作为 Finish 页非终端提示；Done 仍走 Finish，绝不降级为 Message。
            if (finishPage_) {
                const std::wstring warning =
                    uninstallCoordinator_ ? uninstallCoordinator_->Warning() : std::wstring();
                finishPage_->SetNotice(warning.empty() ? std::wstring() : (L"注意：" + warning));
            }
            SetPage(Finish);  // ApplyPageEntry → FinishPage::SetKind(Uninstall)
            break;
        case faf::UninstallStage::Failed: {
            const std::wstring error =
                uninstallCoordinator_ ? uninstallCoordinator_->Error() : std::wstring();
            // T13：终态失败页。关闭走统一 WM_CLOSE；operation==Uninstall 且 page==Message
            // 时绝不会补写 cancel，因此不会覆盖 helper 已落盘的 failed 终态。
            ShowError(L"卸载未完成",
                      error.empty() ? L"卸载过程中出现未知错误。" : error, L"关闭", L"");
            break;
        }
        case faf::UninstallStage::Cancelled:
            ShowError(L"卸载已取消", L"未删除任何文件", L"关闭", L"");
            break;
        default:
            break;
    }
}

void InstallerWindow::OnMaintenanceCloseIntent() {
    // T11：修复进行中（含“正在关闭 app”）一律忽略 X/ESC；其余关闭语义 = 用户取消。
    if (installing_ || closingApp_ || uninstallRunning_) {
        DiagLog(L"maintenance close ignored while operation in progress");
        return;
    }
    // T12：维护模式的 WM_CLOSE 按 mode_ 分流到本函数（而不是 OnUninstallCloseIntent）。
    // 卸载流程只有 Finish 写 ui_done；Progress/Message 关闭时绝不能写 Cancel——
    // 否则会覆盖已落盘的卸载决定，把 Failed/Cancelled 又改写成 Cancelled。
    if (state_.operation == Operation::Uninstall) {
        if (state_.page == Finish) {
            if (uninstallCoordinator_ && !uninstallCoordinator_->Failed()) {
                const bool ok = uninstallCoordinator_->WriteUiDone();
                DiagLog(L"maintenance uninstall finish ui_done written=" +
                        std::to_wstring(ok ? 1 : 0));
            } else {
                DiagLog(L"maintenance uninstall finish ui_done skipped (coordinator failed/absent)");
            }
        } else if (state_.page == UninstallConfirm) {
            // 保留确认页原有的取消行为；这仍是未启动卸载的取消。
            WriteMaintenanceDecisionOnce(MaintenanceAction::Cancel);
        } else {
            DiagLog(L"maintenance uninstall close without decision");
        }
        KillTickTimer();
        if (window_) DestroyWindow(window_);
        return;
    }
    // 未检测到安装 / 预检失败的路径明确不写 decision（suppress）；正常维护页写一次 cancel。
    WriteMaintenanceDecisionOnce(MaintenanceAction::Cancel);
    KillTickTimer();
    if (window_) DestroyWindow(window_);
}

void InstallerWindow::OnUninstallCloseIntent() {
    // T12/D15 C1：Progress（含关闭前置）一律忽略；Finish(Uninstall) 关闭前写 ui_done；
    // 确认页/消息页直接退出。C++ UI 从不删除文件。
    if (installing_ || closingApp_ || uninstallRunning_) {
        DiagLog(L"uninstall close ignored while operation in progress");
        return;
    }
    if (state_.operation == Operation::Uninstall && state_.page == Progress) {
        // 双保险：正常情况下 uninstallRunning_ 已拦截；终态后 page 已不是 Progress。
        DiagLog(L"uninstall close ignored on Progress page");
        return;
    }
    if (state_.operation == Operation::Uninstall && state_.page == Finish) {
        if (uninstallCoordinator_ && !uninstallCoordinator_->Failed()) {
            const bool ok = uninstallCoordinator_->WriteUiDone();
            DiagLog(L"uninstall finish ui_done written=" + std::to_wstring(ok ? 1 : 0));
        } else {
            DiagLog(L"uninstall finish ui_done skipped (coordinator failed/absent)");
        }
    }
    KillTickTimer();
    if (window_) DestroyWindow(window_);
}

bool InstallerWindow::DispatchPointer(const faf::InputEvent& event) {
    if (!pagesReady_) return false;
    // 外壳导航按钮（画布坐标；外壳层经 Translation(m,m) 绘制与命中）。
    bool consumed = shellHost_.Dispatch(event);
    // 当前页（页布局含 Win10 外扩边距，故命中坐标同偏移）。
    faf::InputEvent pageEvent = event;
    const float m = static_cast<float>(shadowMarginDip_);
    pageEvent.x += m;
    pageEvent.y += m;
    if (ActivePageHost().Dispatch(pageEvent)) consumed = true;
    if (consumed) {
        UpdateNavButtons();
        RequestAnimTick();
    }
    return consumed;
}

faf::WidgetHost& InstallerWindow::ActivePageHost() {
    static faf::WidgetHost empty;
    if (!pagesReady_) return empty;
    switch (state_.page) {
        case Welcome: return welcomePage_->Host();
        case License: return licensePage_->Host();
        case Configure: return configurePage_->Host();
        case Progress: return progressPage_->Host();
        case Finish: return finishPage_->Host();
        case Maintenance: return maintenancePage_->Host();
        case UninstallConfirm: return uninstallConfirmPage_->Host();
        case Message: return messagePage_->Host();
        default: return empty;
    }
}

void InstallerWindow::RenderActivePage(ID2D1DeviceContext* ctx, const faf::Theme& theme) {
    if (!pagesReady_ || !ctx) return;
    switch (state_.page) {
        case Welcome: faf::RenderWelcome(ctx, theme, *welcomePage_); break;
        case License: faf::RenderLicense(ctx, theme, *licensePage_); break;
        case Configure: faf::RenderConfigure(ctx, theme, *configurePage_); break;
        // T10：页 3/4 的 Kind 已在 ApplyPageEntry/LayoutPages 中按 state_.operation
        // 同步（SetKind 会重建 Tab 顺序，禁止在逐帧渲染路径重复调用）。
        case Progress: faf::RenderProgress(ctx, theme, *progressPage_); break;
        case Finish: faf::RenderFinish(ctx, theme, *finishPage_); break;
        case Maintenance: faf::RenderMaintenance(ctx, theme, *maintenancePage_); break;
        case UninstallConfirm: faf::RenderUninstallConfirm(ctx, theme, *uninstallConfirmPage_); break;
        case Message: faf::RenderMessage(ctx, theme, *messagePage_); break;
        default: break;
    }
}

// ==================== Todo 19（§17）：/auto 无人值守测试驱动 ====================
// 仅 FAF_TESTMODE 构建有驱动行为（宏由 cmake/test_mode.cmake 在 -DFAF_TESTMODE=ON
// 时定义）。生产构建保留的只有 EnableAutoDrive 的 no-op 定义；驱动成员/定时器/
// 推进逻辑全部被预处理器剔除——/auto 开关在生产中解析后即丢弃，无任何效果。

void InstallerWindow::EnableAutoDrive(AutoDriveOptions options) {
#ifdef FAF_TESTMODE
    autoDriveEnabled_ = true;
    autoProfile_ = std::move(options.profile);  // 空串 = 全默认档
    // T14/D15 H6：合法 stopPage 扩展到 Welcome..Message（0..7）；越界/负值 = 不停。
    autoStopPage_ = (options.stopPage >= Welcome && options.stopPage <= Message)
                        ? options.stopPage
                        : -1;
    // T14：维护/卸载扩展参数只在测试构建存储；生产构建整个结构体被丢弃。
    autoMode_ = options.mode;
    autoAction_ = std::move(options.action);
    autoDeleteUserData_ = std::move(options.deleteUserData);
    DiagLog(L"auto options stop=" +
            (autoStopPage_ < 0 ? std::wstring(L"none") : std::to_wstring(autoStopPage_)) +
            L" mode=" + std::to_wstring(static_cast<int>(autoMode_)) + L" action=" +
            autoAction_ + L" delete_user_data=" + autoDeleteUserData_);
#else
    // 生产构建保底 no-op：交互行为不受 /auto 影响（规格 §17）。
    (void)options;
#endif
}

#ifdef FAF_TESTMODE

void InstallerWindow::ApplyAutoProfile(const std::wstring& bits) {
    // §17：四位 0/1 = 桌面 / 开始菜单 / 开机自启 / 完成后启动；缺位/非法位取 §2
    // 默认（1,1,0,1）。例：`1101` == 默认档；`0` → (0,1,0,1)。
    const bool kDefaults[4] = {true, true, false, true};
    bool values[4] = {kDefaults[0], kDefaults[1], kDefaults[2], kDefaults[3]};
    for (int i = 0; i < 4 && i < static_cast<int>(bits.size()); ++i) {
        if (bits[i] == L'0') values[i] = false;
        if (bits[i] == L'1') values[i] = true;
    }
    state_.optDesktop = values[0];
    state_.optStartmenu = values[1];
    state_.optAutostart = values[2];
    state_.optLaunch = values[3];
    DiagLog(L"auto profile desktop=" + std::to_wstring(values[0] ? 1 : 0) +
            L" startmenu=" + std::to_wstring(values[1] ? 1 : 0) +
            L" autostart=" + std::to_wstring(values[2] ? 1 : 0) +
            L" launch=" + std::to_wstring(values[3] ? 1 : 0));
}

void InstallerWindow::ArmAutoDrive() {
    if (!window_ || autoTimer_) return;
    ApplyAutoProfile(autoProfile_);  // 先落档：Options 页 SyncFromState 直接读取 AppState
    DiagLog(L"auto drive armed stop=" +
            (autoStopPage_ < 0 ? std::wstring(L"none") : std::to_wstring(autoStopPage_)));
    autoTimer_ = SetTimer(window_, kAutoTimerId, kAutoStepMs, nullptr);
}

void InstallerWindow::StopAutoDrive() {
    if (autoTimer_ && window_) KillTimer(window_, autoTimer_);
    autoTimer_ = 0;
}

void InstallerWindow::AutoDriveTick() {
    if (!autoDriveEnabled_ || autoHalted_) return;
    const int page = state_.page;
    // 到站：/auto:page=N 抵达第 N 页后停住（N=0 时首 tick 即停，不推进任何一页）。
    if (autoStopPage_ >= 0 && page >= autoStopPage_) {
        autoHalted_ = true;
        DiagLog(L"auto stop reached page=" + std::to_wstring(page));
        StopAutoDrive();
        return;
    }
    // 走完：完成页为终态（/auto:page=5 时先命中上面的到站分支）。
    if (autoStopPage_ < 0 && page == Finish) {
        autoHalted_ = true;
        DiagLog(L"auto drive complete page=" + std::to_wstring(page));
        StopAutoDrive();
        return;
    }
    // 安装进行中（Progress）：等待 WM_INSTALL_DONE 自动转完成页；本 tick 不动作、
    // 不记录推进（避免固定周期的重复日志噪音）。
    if (page == Progress) return;

    const auto actionIs = [this](const wchar_t* value) {
        return !autoAction_.empty() && _wcsicmp(autoAction_.c_str(), value) == 0;
    };

    // T14/D15 H6：维护页按 /auto:action=repair|uninstall|cancel 推进；缺省/未知
    // 动作时停在维护页（不替用户做危险决定）。
    if (page == Maintenance) {
        if (actionIs(L"repair")) {
            DiagLog(L"auto maintenance action=repair");
            OnMaintenanceRepairIntent();
            return;
        }
        if (actionIs(L"uninstall")) {
            DiagLog(L"auto maintenance action=uninstall");
            OnMaintenanceUninstallIntent();
            return;
        }
        if (actionIs(L"cancel")) {
            DiagLog(L"auto maintenance action=cancel");
            OnMaintenanceCancelIntent();
            return;
        }
        autoHalted_ = true;
        DiagLog(L"auto maintenance waiting action=" + autoAction_);
        StopAutoDrive();
        return;
    }

    // T14/D15 H6：卸载确认页按 /auto:action=uninstall|cancel 推进；uninstall 时
    // 可先写入 /auto:delete-user-data=0|1，再走既有确认入口。
    if (page == UninstallConfirm) {
        if (actionIs(L"uninstall")) {
            if (!autoDeleteUserData_.empty()) {
                const bool deleteUserData = autoDeleteUserData_ == L"1";
                if (state_.deleteUserData != deleteUserData) {
                    state_.deleteUserData = deleteUserData;
                    if (uninstallConfirmPage_) uninstallConfirmPage_->SyncFromState();
                }
            }
            DiagLog(L"auto uninstall action=uninstall delete_user_data=" +
                    autoDeleteUserData_);
            OnUninstallConfirmIntent();
            return;
        }
        if (actionIs(L"cancel")) {
            DiagLog(L"auto uninstall action=cancel");
            OnUninstallCancelIntent();
            return;
        }
        autoHalted_ = true;
        DiagLog(L"auto uninstall waiting action=" + autoAction_);
        StopAutoDrive();
        return;
    }

    // T14/D15 H6：Message 页按动作点击主/次按钮（busy 态两者皆 None → 停住等待）。
    if (page == Message) {
        if (actionIs(L"cancel") && messageSecondaryAction_ != MessageAction::None) {
            DiagLog(L"auto message action=cancel(secondary)");
            OnMessageSecondaryIntent();
            return;
        }
        if (messagePrimaryAction_ != MessageAction::None) {
            DiagLog(L"auto message action=" +
                    std::to_wstring(static_cast<int>(messagePrimaryAction_)));
            OnMessagePrimaryIntent();
            return;
        }
        autoHalted_ = true;
        DiagLog(L"auto message waiting action=" + autoAction_);
        StopAutoDrive();
        return;
    }

    DiagLog(L"auto advance page=" + std::to_wstring(page));
    switch (page) {
        case Welcome:
            GoNext();
            break;
        case License:
            // 许可门控 = state_.agreed（GoNext 只读 AppState）→ 等效用户勾选同意。
            state_.agreed = true;
            if (licensePage_) licensePage_->SyncFromState();
            GoNext();
            break;
        case Configure:
            // 门控 = 目录可写 + 空间足够（ConfigurePage::CanProceed）；默认预填即可过。
            // GoNext → ConfigurePage::SyncToState() + StartInstall()（进入进度页）。
            GoNext();
            break;
        default:
            break;
    }
}

#endif  // FAF_TESTMODE
