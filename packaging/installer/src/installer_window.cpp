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

// 2026-11 设计稿改版：顶部步骤带（协议/配置/部署）与底部按钮条已整体删除——
// 设计稿只有「自绘标题栏 + 整页内容」，每个页面自带主按钮/返回链接。

// T12：UninstallStage → Progress 页阶段文案（wParam/lParam 只传枚举，中文只在此映射）。
const wchar_t* UninstallStageLabel(spk::UninstallStage stage) {
    switch (stage) {
        case spk::UninstallStage::Started: return L"准备卸载";
        case spk::UninstallStage::RemovingShortcuts: return L"正在删除快捷方式";
        case spk::UninstallStage::RemovingRegistry: return L"正在清理注册表";
        case spk::UninstallStage::RemovingFiles: return L"正在删除程序文件";
        case spk::UninstallStage::RemovingUserData: return L"正在清理用户数据";
        case spk::UninstallStage::Done: return L"卸载完成";
        case spk::UninstallStage::Failed: return L"卸载失败";
        case spk::UninstallStage::Cancelled: return L"卸载已取消";
    }
    return L"正在卸载";
}

bool IsKnownUninstallStage(int value) {
    return value >= static_cast<int>(spk::UninstallStage::Started) &&
           value <= static_cast<int>(spk::UninstallStage::Cancelled);
}

bool IsTerminalUninstallStage(int value) {
    return value == static_cast<int>(spk::UninstallStage::Done) ||
           value == static_cast<int>(spk::UninstallStage::Failed) ||
           value == static_cast<int>(spk::UninstallStage::Cancelled);
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

constexpr wchar_t kWindowClass[] = L"SopeekInstaller";  // §4 冻结类名
// setup（NSIS）重启 Explorer 之后用它给本窗口发消息（RegisterWindowMessageW），
// 让窗口所属进程自己把界面抢回前台（跨进程 SetForegroundWindow 会被前台锁拒绝）。
constexpr wchar_t kRestoreForegroundMessageName[] = L"SopeekInstallerRestoreForeground";
// 重启 Explorer 后壳层重建的轮询参数。Explorer 冷启动会在数秒内陆续创建任务栏/桌面
// 窗口并反复抢走前台，所以重试窗口要覆盖这段区间（60 × 150ms ≈ 9s）；setup 侧还会
// 分几次投递同一个请求消息，每次都会把这段重试窗口重新打开一次。
constexpr DWORD kForegroundRestoreRetryMs = 150;
constexpr int kForegroundRestoreRetries = 60;
// 置顶脉冲有轻微闪烁，只按间隔做几次，不参与每次尝试。
constexpr int kForegroundTopmostEveryAttempts = 12;
// 连续多少次探测到「别的程序已在前台」就放弃抢焦点（把控制权让给用户）。
constexpr int kForegroundOtherAppStreakStop = 4;
// T10：标题按启动模式设置（自绘标题栏与 CreateWindowExW 共用同一来源）。
// 安装模式在窗口与任务栏使用同一个标题。
constexpr wchar_t kTitleInstall[] = L"Sopeek 安装程序";
constexpr wchar_t kTitleMaintenance[] = L"Sopeek维护";
constexpr wchar_t kTitleUninstall[] = L"Sopeek卸载";
constexpr UINT_PTR kTickTimerId = 1;
constexpr UINT kTickIntervalMs = 16;      // §2 主循环 ~16ms 驱动动画 tick
constexpr int kWin10ShadowMarginDip = 12; // §4 Win10 兜底透明外扩边距（DIP）
constexpr ULONGLONG kProgressPostIntervalMs = 33;  // §10：进度 PostMessage 节流 ~30fps
constexpr UINT_PTR kCompletionHoldTimerId = 3;
constexpr UINT kCompletionHoldMs = 500;
constexpr ULONGLONG kPreparePollMs = 500;  // 目录字节统计节流
constexpr int kExtractionEndPermille = 800;
constexpr int kUnconfirmedMaxPermille = 999;
constexpr ULONGLONG kPrepareStallWarnMs = 10000;  // 字节数长时间不增长时提示
#ifdef SPK_TESTMODE
// Todo 19（§17）：/auto 测试驱动常量——仅测试构建编入（生产零残留）。
constexpr UINT_PTR kAutoTimerId = 2;  // 驱动定时器（独立于 ~16ms 动画 tick）
constexpr UINT kAutoStepMs = 700;     // 固定步进间隔（无人值守取证时序可复现）
#endif

// §6：逻辑画布尺寸（DIP）——唯一来源为 layout.h，不再内联硬编码（亦不得用旧 720x480）。
constexpr int kCanvasW = static_cast<int>(spk::layout::kCanvasWidth);
constexpr int kCanvasH = static_cast<int>(spk::layout::kCanvasHeight);

// T10：启动模式 → 窗口标题（唯一映射点；构造期写入 windowTitle_）。
const wchar_t* ApplyOperationLabel(Operation operation) {
    switch (operation) {
        case Operation::Repair: return L"修复";
        case Operation::Update: return L"更新";
        default: return L"安装";
    }
}

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

// 无条件运行时诊断落盘（仅当设置 SPK_DIAG_PATH 时写入；未设置时不影响默认行为）。
// 与 SPK_FORCE_WARP / SPK_PAYLOAD_TIMEOUT_MS 同性质，非 SPK_TESTMODE 门闩。
// 底层接受已是 UTF-8 的一行（§16 动画采样行直接走此入口）。
void DiagLogRaw(const std::string& utf8Line) {
    wchar_t path[MAX_PATH] = {};
    const DWORD n = GetEnvironmentVariableW(L"SPK_DIAG_PATH", path, static_cast<DWORD>(ARRAYSIZE(path)));
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

// T11：探测 `<installDir>\Sopeek.exe` 是否在运行。
//
// 为什么窗口侧另做一次探测：process_control.h（T3）只暴露“关闭”入口，没有只读
// 探测 API，而 T11 必须区分两条路径 —— 未运行 → 直接写 decision 开始修复；运行中
// → 先异步关闭，**关闭成功后**才允许写 decision。匹配口径与 spk::CloseInstalledApp
// 保持一致：先按映像名预筛，再用 QueryFullProcessImageNameW 取完整路径做大小写不
// 敏感比较，绝不按映像名单独判定（避免误判/误关其它目录的同名 exe）。
bool IsInstalledAppRunning(const std::wstring& installDir) {
    if (installDir.empty()) return false;
    const std::wstring target =
        NormalizedPath(installDir + L"\\" + spk::protocol::kAppExeName);
    if (target.empty()) return false;

    HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snapshot == INVALID_HANDLE_VALUE) return false;
    PROCESSENTRY32W entry{};
    entry.dwSize = sizeof(entry);
    bool running = false;
    if (Process32FirstW(snapshot, &entry)) {
        do {
            if (CompareStringOrdinal(entry.szExeFile, -1, spk::protocol::kAppExeName, -1, TRUE) !=
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
                                 std::wstring uninstallResultPath,
                                 std::uint64_t payloadBytes)
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
    payloadBytes_ = payloadBytes;
    // §15/Todo 15：/installdir（重装预填）优先。产品默认目录只属于安装模式；
    // 维护/卸载缺少 /installdir 时由 main.cpp 从当前 exe 父目录推导（C4）。这里
    // 绝不再对非安装模式回退 Program Files，否则直接卸载可能指向错误目录。
    if (!installDir.empty()) {
        state_.installDir = std::move(installDir);
    } else if (mode_ == AppMode::Install) {
        state_.installDir = L"C:\\Program Files\\Sopeek";
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
                state_.installDir + L"\\" + spk::protocol::kUninstallRequestFile;
        }
        if (uninstallResultPath_.empty()) {
            uninstallResultPath_ =
                state_.installDir + L"\\" + spk::protocol::kUninstallResultFile;
        }
    }
    UpdateWindowTitle();  // T13：windowTitle_ 初始化（window_ 尚为空，仅落字符串）
    // 现在就打开原进程，避免稍后 PID 被复用。只监视并查询最终退出码。
    if (setupPid_ != 0) {
        setupProcess_ = OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, FALSE, setupPid_);
        if (!setupProcess_ && startupErrorTitle_.empty()) {
            startupErrorTitle_ = L"无法连接安装程序";
            startupErrorBody_ = L"无法监视安装程序的结果，请关闭窗口并重新运行安装包。";
            exitCode_ = 1;
            maintenanceSuppressDecision_ = true;
        }
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
    // T11：跨线程句柄必须先收尾——关闭应用的工作线程可能仍在 spk::CloseInstalledApp
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
    uninstallHeroPage_.reset();
    uninstallConfirmPage_.reset();
    messagePage_.reset();
    welcomePage_.reset();
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
    const bool payloadExists = fs::exists(fs::path(payload_), ec);
    // 维护/卸载模式启动时载荷尚未解包：setup 只在用户选择「修复」后才释放载荷并写
    // payload.ready 哨兵（卸载则完全不需要载荷）。因此「载荷目录缺失」只有安装模式
    // 才是真错误；否则维护窗口会在一切正常时也顶一条红色「未找到安装载荷目录」。
    if (mode_ == AppMode::Install && !payloadExists) {
        errorText_ = L"错误：未找到安装载荷目录：" + payload_;
    }

    // --- 证据用诊断（无 SPK_DIAG_PATH 时不产生任何副作用）---
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
    DiagLog(std::wstring(L"payload_exists=") + std::to_wstring(payloadExists ? 1 : 0) +
            L" mode=" + std::to_wstring(static_cast<int>(mode_)));
    // Todo 15 证据：/installdir 解析值（或默认值）已进入共享状态（Location 页数据源）。
    DiagLog(L"state installDir=" + state_.installDir);

    ShowWindow(window_, SW_SHOW);
    UpdateWindow(window_);

    // 注册「重提前台」私有消息：setup 在重启 Explorer 之后 PostMessage 到本窗口，
    // 由本进程把界面抢回前台（详见 RestoreForeground 的注释）。
    restoreForegroundMessage_ = RegisterWindowMessageW(kRestoreForegroundMessageName);
    DiagLog(std::wstring(L"restore_fg_msg=") + std::to_wstring(restoreForegroundMessage_));

    // §16 + 减少动画：SPI_GETCLIENTAREAANIMATION 已在上方 SetWindowPos 之前读取
    // （ApplyReduceMotion 必须先于 OnSizeChanged()/EnsurePages()），此处不再重复调用；
    // 下方 shellIntro/RequestAnimTick 的 if (!reduceMotion_) 门控依赖 reduce_motion_ 已就绪。
    //
    // 外壳入场动画（0→1，~300ms，WinUI3 Entrance 曲线）——本 todo 的接线在此被真实驱动：
    // WM_TIMER → animator_.Tick() → Render()（dirty 或动画中）→ PresentFrame → Commit。
    // 减少动画时不创建（introAlpha_ 保持 1，立即全不透明，无中间 tick）。
    if (!reduceMotion_) {
        introAnim_ = &animator_.Animate("shellIntro", 0.0f, 1.0f, 300.0f, spk::easing::Entrance);
    }
    dirty_ = true;
    Render();
    if (!reduceMotion_) RequestAnimTick();  // 有活动动画 → 武装 tick 定时器
#ifdef SPK_TESTMODE
    // Todo 19（§17）：/auto 测试驱动——窗口/页面就绪后武装固定时序定时器（生产不编入）。
    if (autoDriveEnabled_) ArmAutoDrive();
#endif
    return true;
}

void InstallerWindow::InstallDwmEffects() {
    // 固定浅色外观，包括 DWM 的系统背景。
    const BOOL dark = FALSE;
    const HRESULT darkHr =
        DwmSetWindowAttribute(window_, DWMWA_USE_IMMERSIVE_DARK_MODE, &dark, sizeof(dark));

    // §4 圆角；失败 ⇒ Win10 兜底（不用 SetWindowRgn，改透明外扩边距 + DComp 自绘阴影）。
    // 设计稿圆角 13 由 DrawWindowCard 自绘；DWM 的 DWMWCP_ROUND（8）只负责把窗口
    // 外轮廓裁圆（13 的弧线整体落在 8 的裁剪区内，不产生可见影响）并给阴影定形。
    DWM_WINDOW_CORNER_PREFERENCE pref = DWMWCP_ROUND;
    cornerOk_ = SUCCEEDED(DwmSetWindowAttribute(window_, DWMWA_WINDOW_CORNER_PREFERENCE, &pref,
                                                sizeof(pref)));

    // 窗口底 = **DWM 浅色 Mica**（用户 2026-11-21 要求：不要纯白底）。Mica 仅在
    // build >= 22621 存在；更旧的系统（Win10）不得强设该未知 DWMWA，静默跳过并走兜底。
    backdropBuildOk_ = WindowsBuild22621OrLater();
    if (backdropBuildOk_) {
        const DWM_SYSTEMBACKDROP_TYPE backdrop = DWMSBT_TABBEDWINDOW;  // Mica Alt
        backdropOk_ = SUCCEEDED(DwmSetWindowAttribute(window_, DWMWA_SYSTEMBACKDROP_TYPE, &backdrop,
                                                      sizeof(backdrop)));
    } else {
        backdropOk_ = false;  // build<22621：不设置该属性（Win10 静默跳过）
    }

    // 扩展帧到完整客户区，让原生 Mica 直接透过透明的 DirectComposition 图层。
    MARGINS margins{-1, -1, -1, -1};
    extendOk_ = backdropOk_ && SUCCEEDED(DwmExtendFrameIntoClientArea(window_, &margins));
    win10Fallback_ = !cornerOk_ || !backdropOk_ || !extendOk_;
    shadowMarginDip_ = win10Fallback_ ? kWin10ShadowMarginDip : 0;

    DiagLog(L"dwm build22621=" + std::to_wstring(backdropBuildOk_ ? 1 : 0) + L" corner=" +
            std::to_wstring(cornerOk_ ? 1 : 0) + L" backdropMica=" +
            std::to_wstring(backdropOk_ ? 1 : 0) + L" darkHr=" +
            ToHex(static_cast<DWORD>(darkHr)) + L" extend=" + std::to_wstring(extendOk_ ? 1 : 0) +
            L" dark=0 win10fallback=" +
            std::to_wstring(win10Fallback_ ? 1 : 0));
}

void InstallerWindow::UpdateWindowTitle() {
    // T13：标题唯一映射仍在 TitleForMode()；本函数只负责把同一字符串同时写入
    // 自绘标题栏数据源与原生窗口（任务栏/Alt+Tab）。窗口未创建时仅更新字符串。
    windowTitle_ = TitleForMode(mode_);
    if (window_) SetWindowTextW(window_, windowTitle_.c_str());
}

void InstallerWindow::Layout() {
    // §6：shell 几何唯一来源 = spk::ComputeShellLayout（纯 DIP 计算，不依赖 DPI）。
    // 新版只有一个外壳形状：标题栏 56 + 整页内容（设计稿没有步骤带/底部条）。
    shellLayout_ = spk::ComputeShellLayout(spk::IsHeroPage(state_.page) ||
                                           state_.operation != Operation::Install);
    if (pagesReady_) LayoutPages();
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
    const double nowMs = spk::SteadyNowMs();
    // 先同步解压进度，再推进动画。
    AdvanceInitProgress(nowMs);
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
    const spk::Theme theme = spk::LightTheme();  // §13：唯一 token 表
    const float m = static_cast<float>(shadowMarginDip_);
    ctx->SetTransform(D2D1::Matrix3x2F::Translation(m, m));

    // 入场动画进度（减少动画/无入场动画时为 1）：乘入各层/文字 alpha，构成淡入。
    introAlpha_ = introAnim_ ? introAnim_->Value() : 1.0f;

    DrawWindowCard(ctx, theme, introAlpha_);

    ctx->SetTransform(D2D1::Matrix3x2F::Identity());
    const auto card = PageRect();
    ctx->PushAxisAlignedClip(card, D2D1_ANTIALIAS_MODE_PER_PRIMITIVE);
    const auto drawPage = [&](int page, float opacity, float offset) {
        if (opacity <= 0.0f) return;
        ctx->SetTransform(D2D1::Matrix3x2F::Identity());
        const bool translucent = opacity < 1.0f;
        if (translucent) {
            auto layer = D2D1::LayerParameters1(card);
            layer.opacity = opacity;
            ctx->PushLayer(layer, nullptr);
        }
        ctx->SetTransform(D2D1::Matrix3x2F::Translation(offset, 0.0f));
        RenderPage(ctx, theme, page);
        ctx->SetTransform(D2D1::Matrix3x2F::Identity());
        if (translucent) ctx->PopLayer();
    };
    const float progress = pageTransition_ ? pageTransition_->Value() : 1.0f;
    constexpr float slideDip = 18.0f;
    if (progress < 1.0f && previousPage_ >= 0) {
        drawPage(previousPage_, introAlpha_ * (1.0f - progress), -pageDirection_ * slideDip * progress);
    }
    drawPage(state_.page, introAlpha_ * progress, pageDirection_ * slideDip * (1.0f - progress));
    ctx->PopAxisAlignedClip();


    ctx->SetTransform(D2D1::Matrix3x2F::Translation(m, m));
    DrawTitleBar(ctx, theme, introAlpha_);

    if (!errorText_.empty()) {
        const spk::ShellLayout& s = shellLayout_;
        const float cardW = s.contentCard.right - s.contentCard.left;
        DrawTextLine(ctx, errorText_, s.contentCard.left + spk::spacing::M,
                     s.contentCard.top + spk::spacing::M, cardW - 2.0f * spk::spacing::M,
                     spk::fontsize::Body16 + spk::spacing::S, spk::fontsize::Body16,
                     D2D1::ColorF(0.85f, 0.20f, 0.20f, introAlpha_));
    }

    ctx->SetTransform(D2D1::Matrix3x2F::Identity());
}

void InstallerWindow::DrawWindowCard(ID2D1DeviceContext* ctx, const spk::Theme& theme,
                                     float alpha) {
    const float W = spk::layout::kCanvasWidth;
    const float H = spk::layout::kCanvasHeight;
    const float m = static_cast<float>(shadowMarginDip_);

    // 交换链已经清为透明。支持 Mica 时将客户区底色与圆角交给 DWM。
    // 无 Mica 时，使用自绘阴影与浅灰渐变圆角卡片。
    if (win10Fallback_) {
        if (m > 0.0f) {
            spk::ComPtr<ID2D1SolidColorBrush> shadow;
            if (SUCCEEDED(ctx->CreateSolidColorBrush(D2D1::ColorF(0, 0, 0, 0.10f * alpha),
                                                     shadow.GetAddressOf()))) {
                const int steps = 5;
                for (int i = steps - 1; i >= 0; --i) {
                    const float grow =
                        (static_cast<float>(i) + 1.0f) * (m / static_cast<float>(steps)) * 0.6f;
                    const float r = spk::radius::Window + grow;
                    ctx->FillRoundedRectangle(
                        D2D1::RoundedRect(D2D1::RectF(-grow, -grow, W + grow, H + grow), r, r),
                        shadow.Get());
                }
            }
        }

        // 不透明 Mica 风格渐变底（兜底路径必须不透明，否则透出桌面）。
        const D2D1_GRADIENT_STOP stops[2] = {
            {0.0f, D2D1::ColorF(0.980f, 0.980f, 0.980f, alpha)},
            {1.0f, D2D1::ColorF(0.925f, 0.925f, 0.925f, alpha)},
        };
        spk::ComPtr<ID2D1GradientStopCollection> coll;
        if (SUCCEEDED(ctx->CreateGradientStopCollection(stops, 2, coll.GetAddressOf()))) {
            spk::ComPtr<ID2D1LinearGradientBrush> base;
            if (SUCCEEDED(ctx->CreateLinearGradientBrush(
                    D2D1::LinearGradientBrushProperties(D2D1::Point2F(0, 0), D2D1::Point2F(0, H)),
                    coll.Get(), base.GetAddressOf()))) {
                ctx->FillRoundedRectangle(D2D1::RoundedRect(D2D1::RectF(0, 0, W, H),
                                                            spk::radius::Window,
                                                            spk::radius::Window),
                                          base.Get());
            }
        }
    }

    // 1px 玻璃描边：跟随 DWM 的圆角半径（Win11 8 DIP；兜底路径用设计稿的 13）。
    const float radius = win10Fallback_ ? spk::radius::Window : spk::radius::Medium;
    D2D1_COLOR_F stroke = theme.windowStroke;
    stroke.a *= alpha;
    spk::ComPtr<ID2D1SolidColorBrush> strokeBrush;
    if (SUCCEEDED(ctx->CreateSolidColorBrush(stroke, strokeBrush.GetAddressOf()))) {
        const D2D1_ROUNDED_RECT inner =
            D2D1::RoundedRect(D2D1::RectF(0.5f, 0.5f, W - 0.5f, H - 0.5f), radius - 0.5f,
                              radius - 0.5f);
        ctx->DrawRoundedRectangle(inner, strokeBrush.Get(), 1.0f);
    }
}
void InstallerWindow::DrawTitleBar(ID2D1DeviceContext* ctx, const spk::Theme& theme, float alpha) {
    const spk::ShellLayout& s = shellLayout_;

    auto tint = [alpha](D2D1_COLOR_F c) {
        c.a *= alpha;
        return c;
    };

    // 标题栏直接延续 Mica。以系统按钮中心为共同纵向基准。
    const float centerY = (s.minButton.top + s.minButton.bottom) * 0.5f;
    const float logoLeft = spk::design::kTitleLogoLeft;
    const float logoSize = spk::design::kTitleLogoSize;
    if (logoBitmap_.IsLoaded()) {
        const float top = centerY - logoSize * 0.5f;
        ctx->DrawBitmap(logoBitmap_.Bitmap(), D2D1::RectF(logoLeft, top, logoLeft + logoSize, top + logoSize),
                        alpha, D2D1_BITMAP_INTERPOLATION_MODE_LINEAR);
    }
    const float textLeft = logoLeft + logoSize + spk::spacing::S;
    const float textHeight = 28.0f;
    DrawTextLine(ctx, windowTitle_, textLeft, centerY - textHeight * 0.5f,
                 s.minButton.left - spk::spacing::M - textLeft, textHeight,
                 spk::fontsize::Body, tint(theme.textPrimary), spk::weight::SemiBold,
                 DWRITE_TEXT_ALIGNMENT_LEADING);

    // 窗口按钮悬停底（最小化：中性叠加；关闭：Windows 标准红）。
    const bool minHot = hoverButton_ == WindowButton::Minimize;
    const bool minArmed = minHot && armedButton_ == WindowButton::Minimize;
    const bool closeHot = hoverButton_ == WindowButton::Close;
    const bool closeArmed = closeHot && armedButton_ == WindowButton::Close;

    if (minHot) {
        D2D1_COLOR_F fill = minArmed ? theme.pressed : theme.hover;
        fill.a *= alpha;
        spk::ComPtr<ID2D1SolidColorBrush> bg;
        if (SUCCEEDED(ctx->CreateSolidColorBrush(fill, bg.GetAddressOf()))) {
            ctx->FillRoundedRectangle(
                D2D1::RoundedRect(s.minButton, spk::radius::Small + 2.0f,
                                  spk::radius::Small + 2.0f),
                bg.Get());
        }
    }
    if (closeHot) {
        D2D1_COLOR_F fill = closeArmed ? CloseArmedRed() : CloseHoverRed();
        fill.a *= alpha;
        spk::ComPtr<ID2D1SolidColorBrush> bg;
        if (SUCCEEDED(ctx->CreateSolidColorBrush(fill, bg.GetAddressOf()))) {
            ctx->FillRoundedRectangle(
                D2D1::RoundedRect(s.closeButton, spk::radius::Small + 2.0f,
                                  spk::radius::Small + 2.0f),
                bg.Get());
        }
    }

    // 最小化「—」：设计稿 12.5x2 @ 中心 (583.7,29)。
    const float mcx = (s.minButton.left + s.minButton.right) * 0.5f;
    const float mcy = (s.minButton.top + s.minButton.bottom) * 0.5f;
    const auto ink = tint(theme.chromeInk);
    spk::ComPtr<ID2D1SolidColorBrush> stroke;
    if (SUCCEEDED(ctx->CreateSolidColorBrush(ink, stroke.GetAddressOf()))) {
        ctx->DrawLine(D2D1::Point2F(mcx - 6.25f, mcy), D2D1::Point2F(mcx + 6.25f, mcy),
                      stroke.Get(), 1.5f);
    }

    // 关闭「✕」：设计稿 14x15 @ 中心 (614.5,29)；悬停时转白（红底对比）。
    const float ccx = (s.closeButton.left + s.closeButton.right) * 0.5f;
    const float ccy = (s.closeButton.top + s.closeButton.bottom) * 0.5f;
    spk::ComPtr<ID2D1SolidColorBrush> closeStroke;
    if (SUCCEEDED(ctx->CreateSolidColorBrush(closeHot ? D2D1::ColorF(1, 1, 1, alpha) : ink,
                                              closeStroke.GetAddressOf()))) {
        ctx->DrawLine(D2D1::Point2F(ccx - 7.0f, ccy - 7.0f), D2D1::Point2F(ccx + 7.0f, ccy + 7.0f),
                      closeStroke.Get(), 1.5f);
        ctx->DrawLine(D2D1::Point2F(ccx - 7.0f, ccy + 7.0f), D2D1::Point2F(ccx + 7.0f, ccy - 7.0f),
                      closeStroke.Get(), 1.5f);
    }
}

void InstallerWindow::DrawTextLine(ID2D1DeviceContext* ctx, const std::wstring& text, float x, float y,
                                   float width, float height, float sizeDip,
                                   const D2D1_COLOR_F& color, DWRITE_FONT_WEIGHT weight,
                                   DWRITE_TEXT_ALIGNMENT align) {
    IDWriteFactory* dwrite = render_.WriteFactory();
    if (!dwrite) return;
    // 族名与页内文字同源（设计稿 = Microsoft YaHei；TextFactory 负责探测与回退）。
    const std::wstring family = textFactory_.IsReady() ? textFactory_.Family() : std::wstring(L"Segoe UI");
    spk::ComPtr<IDWriteTextFormat> format;
    if (FAILED(dwrite->CreateTextFormat(family.c_str(), nullptr, weight,
                                        DWRITE_FONT_STYLE_NORMAL, DWRITE_FONT_STRETCH_NORMAL, sizeDip,
                                        L"zh-cn", format.GetAddressOf()))) {
        return;
    }
    format->SetTextAlignment(align);
    format->SetParagraphAlignment(DWRITE_PARAGRAPH_ALIGNMENT_CENTER);
    spk::ComPtr<ID2D1SolidColorBrush> brush;
    if (FAILED(ctx->CreateSolidColorBrush(color, brush.GetAddressOf()))) return;
    ctx->DrawText(text.c_str(), static_cast<UINT32>(text.size()), format.Get(),
                  D2D1::RectF(x, y, x + width, y + height), brush.Get());
}

void InstallerWindow::ClientPointToDip(POINT p, float* dx, float* dy) const {
    const float m = static_cast<float>(MarginPx());
    // §6：客户端物理像素 → DIP 的换算比例 = 96 / SafeDpi(dpi_)。dpi_ 为 0 时
    // ClientPxToDipScale 守卫回退 96，绝不出现 96/0 除零（见 layout.h::SafeDpi）。
    const float scale = spk::ClientPxToDipScale(dpi_);
    *dx = (static_cast<float>(p.x) - m) * scale;
    *dy = (static_cast<float>(p.y) - m) * scale;
}

void InstallerWindow::EndLicensePan() {
    if (!licensePanActive_) return;
    licensePanActive_ = false;
    licenseSheet_.Box().OnInput({spk::InputEvent::Up, -1.0f, -1.0f});
    RequestAnimTick();
}

bool InstallerWindow::HandleLicensePan(const GESTUREINFO& gesture) {
    if (!pagesReady_ || state_.page != License || gesture.dwID != GID_PAN) return false;

    POINT point{gesture.ptsLocation.x, gesture.ptsLocation.y};
    if (!ScreenToClient(window_, &point)) {
        EndLicensePan();
        return false;
    }
    float dx = 0.0f, dy = 0.0f;
    ClientPointToDip(point, &dx, &dy);
    if (pageTransition_) dx -= pageDirection_ * 18.0f * (1.0f - pageTransition_->Value());

    auto& box = licenseSheet_.Box();
    const auto& bounds = box.Bounds();
    // 手势命中整个正文，交给正文中轴的拖动路径，避开浮动滚动条的鼠标热区。
    const float dragX = (bounds.left + bounds.right) * 0.5f;
    if (gesture.dwFlags & GF_BEGIN) {
        EndLicensePan();
        if (!box.HitTest(dx, dy) || box.MaxScroll() <= 0.0f) return false;
        auto& host = ActivePageHost();
        host.CancelPointer();
        if (GetCapture() == window_) ReleaseCapture();
        host.FocusWidget(&box);
        licensePanActive_ = box.OnInput({spk::InputEvent::Down, dragX, dy});
    } else if (licensePanActive_) {
        // Windows 连续投递惯性阶段的坐标，沿用同一拖动直到 GF_END。
        box.OnInput({spk::InputEvent::Move, dragX, dy});
    }
    if (!licensePanActive_) return false;
    if (gesture.dwFlags & GF_END) EndLicensePan();
    RequestAnimTick();
    return true;
}

// --- 自绘标题栏窗口按钮（最小化/关闭）状态机 ---------------------------------
InstallerWindow::WindowButton InstallerWindow::HitTestWindowButton(float dipX, float dipY) const {
    const D2D1_POINT_2F pt = D2D1::Point2F(dipX, dipY);
    // 关闭优先（右边缘），其次最小化；命中区来自 layout（纯 DIP，不重新缩放）。
    if (spk::HitTest(shellLayout_.closeButton, pt)) return WindowButton::Close;
    if (spk::HitTest(shellLayout_.minButton, pt)) return WindowButton::Minimize;
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

// Explorer 重启后的一小段时间里，系统会停在「没有前台窗口」或「前台停在新 shell 的
// 任务栏/桌面窗口上」的状态：此时任何进程的 SetForegroundWindow 都会被前台锁拒绝，
// 用户看到的现象就是「所有窗口都点不动，必须点一下任务栏才能恢复」。
// 这两个小工具用于判定该状态并解锁。
bool IsShellPlaceholderForeground(HWND foreground) {
    if (foreground == nullptr) return true;  // 空前台正是锁死态
    wchar_t cls[64] = {};
    if (GetClassNameW(foreground, cls, ARRAYSIZE(cls)) == 0) return false;
    return wcscmp(cls, L"Shell_TrayWnd") == 0 || wcscmp(cls, L"Shell_SecondaryTrayWnd") == 0 ||
           wcscmp(cls, L"Progman") == 0 || wcscmp(cls, L"WorkerW") == 0;
}

// 合成一次最小键盘输入（Alt 按下并抬起）。Windows 的前台激活规则里有一条
// 「进程收到过最后一次输入事件」，合成输入正好满足它，从而在不碰用户其它窗口的
// 前提下解除前台锁——等价于用户「点了一下」，但不会真的切换用户正在用的程序。
void PulseTrustedInput() {
    INPUT inputs[2] = {};
    inputs[0].type = INPUT_KEYBOARD;
    inputs[0].ki.wVk = VK_MENU;
    inputs[1].type = INPUT_KEYBOARD;
    inputs[1].ki.wVk = VK_MENU;
    inputs[1].ki.dwFlags = KEYEVENTF_KEYUP;
    SendInput(ARRAYSIZE(inputs), inputs, sizeof(INPUT));
}

bool InstallerWindow::RestoreForeground() {
    HWND hwnd = window_;
    if (hwnd == nullptr || !IsWindow(hwnd)) {
        DiagLog(L"restore foreground skipped: window gone");
        return false;
    }

    // Explorer 重建期间窗口可能被最小化/隐藏：先恢复可见，否则任何置前调用都无效。
    if (IsIconic(hwnd)) ShowWindow(hwnd, SW_RESTORE);
    if (!IsWindowVisible(hwnd)) ShowWindow(hwnd, SW_SHOWNORMAL);

    // 已经是前台：重复请求直接成功返回，避免 setup 多次投递时反复折腾窗口。
    if (GetForegroundWindow() == hwnd) {
        DiagLog(L"restore foreground already active");
        SetFocus(hwnd);
        return true;
    }

    // SetForegroundWindow 在 Windows 上有「前台锁」：只要系统里还有别的进程持有前台，
    // 跨进程置前就会被拒绝；taskkill explorer.exe 之后前台窗口为空，直接调用通常可成，
    // 但 Explorer 重建过程中前台可能又被新 shell 抢走，所以这里做有限次重试。
    const HWND foregroundBefore = GetForegroundWindow();
    bool restored = false;
    int otherAppStreak = 0;
    for (int attempt = 1; attempt <= kForegroundRestoreRetries && !restored; ++attempt) {
        const HWND foregroundNow = GetForegroundWindow();
        if (foregroundNow == hwnd) {
            restored = true;
            DiagLog(L"restore foreground ok=preexisting attempt=" + std::to_wstring(attempt));
            break;
        }

        // 用户已经开始操作别的程序（shell 占位窗口之外的真实应用窗口）：停止争抢，
        // 否则每次安装结束都会把用户从正在做的事情里拽出来。
        if (!IsShellPlaceholderForeground(foregroundNow)) {
            if (++otherAppStreak >= kForegroundOtherAppStreakStop) {
                DiagLog(L"restore foreground stop=user-active attempt=" + std::to_wstring(attempt));
                break;
            }
        } else {
            otherAppStreak = 0;
            // shell 占位（含空前台）时合成一次输入来解除前台锁：前 10 次必做，
            // 之后每 5 次补一次，避免长时间空转反复注入按键。
            if (attempt <= 10 || (attempt % 5) == 0) PulseTrustedInput();
        }

        SetForegroundWindow(hwnd);
        if (GetForegroundWindow() == hwnd) {
            restored = true;
            DiagLog(L"restore foreground ok=direct attempt=" + std::to_wstring(attempt));
            break;
        }

        // 前台锁拒绝：临时附加到当前前台线程的输入队列，再置前（与
        // single_instance.cpp 的 ActivateExistingWindow 同一手法）。
        const HWND foreground = GetForegroundWindow();
        const DWORD foregroundThread =
            foreground != nullptr ? GetWindowThreadProcessId(foreground, nullptr) : 0;
        const DWORD currentThread = GetCurrentThreadId();
        if (foregroundThread != 0 && foregroundThread != currentThread &&
            AttachThreadInput(currentThread, foregroundThread, TRUE)) {
            BringWindowToTop(hwnd);
            SetForegroundWindow(hwnd);
            SetActiveWindow(hwnd);
            AttachThreadInput(currentThread, foregroundThread, FALSE);
        }
        if (GetForegroundWindow() == hwnd) {
            restored = true;
            DiagLog(L"restore foreground ok=attach attempt=" + std::to_wstring(attempt));
            break;
        }

        // 最后一条兼容路径：SwitchToThisWindow 会绕开前台锁（系统用它实现任务栏切换），
        // 在 Explorer 刚重建、前台仍为空时最有效。
        SwitchToThisWindow(hwnd, TRUE);
        if (GetForegroundWindow() == hwnd) {
            restored = true;
            DiagLog(L"restore foreground ok=switch attempt=" + std::to_wstring(attempt));
            break;
        }

        // 置顶脉冲只按间隔做：它能让窗口在视觉上立刻浮出，但对前台激活没有帮助，
        // 每次都做会明显闪烁，所以约每 12 次尝试（≈1.8s）补一次。
        if ((attempt % kForegroundTopmostEveryAttempts) == 0) {
            SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                         SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW);
            SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                         SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW);
            SetForegroundWindow(hwnd);
            if (GetForegroundWindow() == hwnd) {
                restored = true;
                DiagLog(L"restore foreground ok=topmost attempt=" + std::to_wstring(attempt));
                break;
            }
        }

        Sleep(kForegroundRestoreRetryMs);
    }

    // 即使激活仍被系统拒绝，也要保证窗口浮在最上层：置顶脉冲让用户一眼能看到它，
    // 之后的普通点击即可正常接管（否则窗口可能停在别的窗口后面，看起来「点不动」）。
    if (!restored) {
        SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                     SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW);
        SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                     SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW);
        SetForegroundWindow(hwnd);
        restored = GetForegroundWindow() == hwnd;
        DiagLog(std::wstring(L"restore foreground fallback topmost ok=") +
                std::to_wstring(restored ? 1 : 0) + L" foreground_before=" +
                ToHex(static_cast<DWORD>(reinterpret_cast<std::uintptr_t>(foregroundBefore))) +
                L" foreground_now=" +
                ToHex(static_cast<DWORD>(reinterpret_cast<std::uintptr_t>(GetForegroundWindow()))));
    }

    // 焦点落在窗口内，键盘操作（Tab/Enter/Esc）才能直接生效。
    SetFocus(hwnd);
    return restored;
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

    // setup 重启 Explorer 之后发来的「抢回前台」请求（见 RestoreForeground）。
    if (restoreForegroundMessage_ != 0 && msg == restoreForegroundMessage_) {
        RestoreForeground();
        return 0;
    }

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
            if (spk::HitTest(shellLayout_.minButton, pt) ||
                spk::HitTest(shellLayout_.closeButton, pt))
                return HTCLIENT;
            return HTCAPTION;  // §4 标题栏可拖
        }
        return HTCLIENT;
    }

    if (msg == WM_GESTURENOTIFY) {
        const auto* notify = reinterpret_cast<const GESTURENOTIFYSTRUCT*>(lp);
        bool inBody = false;
        if (pagesReady_ && state_.page == License && notify &&
            notify->cbSize >= sizeof(GESTURENOTIFYSTRUCT)) {
            POINT point{notify->ptsLocation.x, notify->ptsLocation.y};
            if (ScreenToClient(hwnd, &point)) {
                float dx = 0.0f, dy = 0.0f;
                ClientPointToDip(point, &dx, &dy);
                if (pageTransition_) dx -= pageDirection_ * 18.0f * (1.0f - pageTransition_->Value());
                auto& box = licenseSheet_.Box();
                inBody = box.HitTest(dx, dy) && box.MaxScroll() > 0.0f;
            }
        }
        constexpr DWORD vertical = GC_PAN_WITH_SINGLE_FINGER_VERTICALLY;
        GESTURECONFIG config{GID_PAN, GC_PAN | GC_PAN_WITH_INERTIA | (inBody ? vertical : 0),
                             inBody ? GC_PAN_WITH_SINGLE_FINGER_HORIZONTALLY : vertical};
        SetGestureConfig(hwnd, 0, 1, &config, sizeof(config));
        return DefWindowProcW(hwnd, msg, wp, lp);
    }
    if (msg == WM_GESTURE) {
        const auto handle = reinterpret_cast<HGESTUREINFO>(lp);
        GESTUREINFO gesture{};
        gesture.cbSize = sizeof(gesture);
        if (GetGestureInfo(handle, &gesture)) {
            if (gesture.dwID == GID_BEGIN || gesture.dwID == GID_END) EndLicensePan();
            if (HandleLicensePan(gesture)) {
                CloseGestureInfoHandle(handle);
                return 0;
            }
        }
        return DefWindowProcW(hwnd, msg, wp, lp);
    }

    if (msg == WM_LBUTTONDOWN) {
        EndLicensePan();  // 新的单击可立即中断手势惯性，返回按钮照常响应。
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
        spk::InputEvent ev{};
        ev.kind = spk::InputEvent::Down;
        ev.x = dx;
        ev.y = dy;
        DispatchPageInput(ev);
        if (ActivePageHost().HasPointerPress())
            SetCapture(hwnd);
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
        spk::InputEvent ev{};
        ev.kind = spk::InputEvent::Up;
        ev.x = dx;
        ev.y = dy;
        DispatchPageInput(ev);
        if (GetCapture() == hwnd) ReleaseCapture();
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
        spk::InputEvent ev{};
        ev.kind = spk::InputEvent::Move;
        ev.x = dx;
        ev.y = dy;
        if (!licensePanActive_) DispatchPageInput(ev);
        return 0;
    }

    // 光标离开窗口/客户区：复位悬停填充，并允许下次移动重新注册 TME_LEAVE。
    if (msg == WM_MOUSELEAVE) {
        trackingLeave_ = false;
        if (GetCapture() != hwnd && !licensePanActive_)
            DispatchPageInput({spk::InputEvent::Move, -1.0f, -1.0f});
        if (hoverButton_ != WindowButton::None) {
            hoverButton_ = WindowButton::None;
            RequestAnimTick();
        }
        return 0;
    }

    // 捕获丢失（被其它窗口抢走 / 显式释放）→ 清 armed，避免按钮停在按下红态。
    if (msg == WM_KILLFOCUS) EndLicensePan();
    if (msg == WM_CAPTURECHANGED || msg == WM_CANCELMODE) {
        EndLicensePan();
        auto& host = ActivePageHost();
        if (host.HasPointerPress()) {
            host.CancelPointer();
            RequestAnimTick();
        }
        if (msg == WM_CANCELMODE && GetCapture() == hwnd) ReleaseCapture();
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
            spk::InputEvent ev{};
            ev.kind = spk::InputEvent::Wheel;
            ev.x = dx;
            ev.y = dy;
            ev.key = GET_WHEEL_DELTA_WPARAM(wp);
            DispatchPageInput(ev);
        }
        return 0;
    }

    // Todo 12：键盘——ESC 关闭（安装中禁止）；Tab 走当前页 Tab 顺序；其余交给当前页。
    if (msg == WM_KEYDOWN) {
        const int vk = static_cast<int>(wp);
        const bool shift = (GetKeyState(VK_SHIFT) & 0x8000) != 0;
        // 长按激活键或 ESC 时，一次物理按键只触发一个页面动作。
        if ((lp & (1L << 30)) && (vk == VK_SPACE || vk == VK_RETURN || vk == VK_ESCAPE)) return 0;
        if (vk == VK_ESCAPE) {
            if (state_.page == License) {
                GoBack();
                return 0;
            }
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
            spk::InputEvent ev{};
            ev.kind = spk::InputEvent::Key;
            ev.key = vk;
            ev.shift = shift;
            DispatchPageInput(ev);
        }
        return 0;
    }

    if (msg == WM_TIMER) {
        if (wp == kTickTimerId) {
            Tick();
            return 0;
        }
        // UI-fix（进度 UX）：成功收尾的 100% 停留结束 → 切完成页（一次性定时器）。
        if (wp == kCompletionHoldTimerId) {
            KillTimer(window_, kCompletionHoldTimerId);
            if (!completionHold_) return 0;  // 已回退/重置的陈旧定时器：绝不切页
            completionHold_ = false;
            keepTickAlive_ = false;
            SetPage(Finish);
            DiagLog(L"completion hold finish");
            return 0;
        }
#ifdef SPK_TESTMODE
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
    if (msg == WM_SETTINGCHANGE && lp != 0 &&
        lstrcmpiW(reinterpret_cast<LPCWSTR>(lp), L"ImmersiveColorSet") == 0) {
        const BOOL dark = FALSE;
        DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, &dark, sizeof(dark));
        RequestAnimTick();
        return 0;
    }
    // §5 DWM 颜色化变化（强调色 / 明暗）→ 置脏重绘（让 Mica 色调同步）。
    if (msg == WM_DWMCOLORIZATIONCOLORCHANGED) {
        dirty_ = true;
        Render();
        return 0;
    }
    // T10：第二实例请求恢复并置前（T13 的 SingleInstanceGuard 发出）。
    if (msg == WM_SPK_ACTIVATE) {
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
        if (awaitingSetupExit_) return 0;  // 结果已提交，不能再取消 NSIS 收尾。
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
    if (msg == WM_INSTALL_PROGRESS) {
        if (!installing_) return 0;
        // 首条复制消息也能确认解压结束，处理消息早于目录轮询的情况。
        const int raw = std::clamp(static_cast<int>(wp), 0, 1000);
        if (initProgressActive_) EndInitProgress();
        // 写入结果、NSIS 收尾均在复制之后。只有成功确认才能显示 100%。
        const int mapped = kExtractionEndPermille +
            raw * (kUnconfirmedMaxPermille - kExtractionEndPermille) / 1000;
        if (mapped > progressPermille_) {
            progressPermille_ = mapped;
            if (progressPage_) progressPage_->SetProgressPermille(mapped);
            if (raw == 1000) DiagLog(L"copy progress raw=1000 mapped=" + std::to_wstring(mapped));
        }
        RequestAnimTick();
        return 0;
    }
    if (msg == WM_INSTALL_DONE) {  // wParam：1 = 成功；0 = 取消/超时/失败（引擎已写 §1 INI）
        // 结束解压目录扫描，成功路径随后进入 100% 停留。
        initProgressActive_ = false;
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
        const bool repair = state_.operation == Operation::Repair || state_.operation == Operation::Update;
        const std::wstring action = ApplyOperationLabel(state_.operation);
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

        if (ok && setupPid_ != 0) {
            // 引擎成功只表示复制已完成。NSIS 消费结果后还要部署卸载器、注册表与快捷方式。
            if (!resultWritten_) {
                ShowError(action + L"失败", L"无法将文件复制结果提交给安装程序。", L"关闭", L"");
                return 0;
            }
            awaitingSetupExit_ = true;
            keepTickAlive_ = true;
            if (progressPage_) {
                progressPage_->SetCancellable(false);
                progressPage_->SetStageText(L"正在完成安装配置");
                progressPage_->SetNotice(L"正在等待安装程序确认结果，请稍候。");
            }
            CheckSetupWatchdog();  // setup 可能在 WM_INSTALL_DONE 入队前已经退出。
            RequestAnimTick();
            return 0;
        }
        // 裸 GUI 的独立运行与截图路径继续使用引擎终态。
        if (ok && closePending_) {
            KillTickTimer();
            DestroyWindow(hwnd);
            return 0;
        }
        if (repair) {
            // T11：修复终点。成功 → 先在 100% 停留再 Finish(Repair)；失败/取消 → Message，
            // 窗口保持打开（修复不回滚，绝不能自动关闭或伪造成功）。
            if (ok) {
                BeginCompletionHold();
                return 0;
            }
            if (setupExited) {
                ShowError(action + L"已终止", L"安装程序已退出，操作已终止", L"关闭", L"");
            } else if (cancelled) {
                ShowError(action + L"已取消", action + L"未完成，已写入的程序文件保持原样。", L"关闭", L"");
            } else {
                ShowError(action + L"失败",
                          error.empty() ? action + L"过程中出现未知错误。" : (action + L"失败：" + error),
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
            // UI-fix（进度 UX）：不立即切页——先 SetProgressPermille(1000) 并停留
            // ~300ms，让 220ms 填充动画可见，再由 WM_TIMER(id=3) 进入完成页。
            BeginCompletionHold();
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
        std::wstring friendlyError = error;
        if (error == L"payload-release-failed" || error == L"repair-payload-release-failed") {
            friendlyError = L"安装文件解压失败。请检查磁盘空间，或暂时关闭杀毒软件后重试。";
        } else if (error == L"payload-timeout" || error == L"repair-payload-timeout") {
            friendlyError = L"等待安装文件解压超时。请检查磁盘空间后重新运行安装包。";
        } else if (error == L"payload-missing" || error == L"repair-payload-missing") {
            friendlyError = L"找不到安装文件。请重新运行安装包。";
        }
        ShowError(L"安装失败", friendlyError.empty() ? L"安装失败" : (L"安装失败：" + friendlyError),
                  L"关闭", L"");
        return 0;
    }

    return DefWindowProcW(hwnd, msg, wp, lp);
}

void InstallerWindow::SetPage(int page) {
    EndLicensePan();
    // §12：页面唯一来源 = AppState::page；进入页面统一走 ApplyPageEntry（Synced + Layout）。
    ActivePageHost().CancelPointer();
    ActivePageHost().FocusWidget(nullptr);
    const int from = state_.page;
    if (page != from && !reduceMotion_) {
        previousPage_ = from;
        // 进度和完成页也用于维护流程，其枚举号不能用于判断前进方向。
        pageDirection_ = (page == Welcome || (page == Maintenance && (from == UninstallConfirm || from == Configure || from == Message)) ||
                          (page == UninstallConfirm && from == UninstallChecklist) ||
                          (page == Configure && from == License))
                             ? -1.0f : 1.0f;
        pageTransition_ = &animator_.Animate("pageTransition", 0.0f, 1.0f, 245.0f,
                                             spk::easing::Entrance);
        DiagLog(L"page transition " + std::to_wstring(from) + L"->" + std::to_wstring(page));
    }
    state_.page = page;
    // 追加需求：英雄页（欢迎/完成）⇄ 向导页切换时 shell 几何不同（有无步骤带/底部条），
    // 必须在布局页面之前重算，否则页/步骤带/导航按钮会沿用旧几何。
    // T10：Repair/Uninstall（operation != Install）复用 Progress/Finish 时也按英雄页布局。
    shellLayout_ = spk::ComputeShellLayout(spk::IsHeroPage(page) ||
                                           state_.operation != Operation::Install);
    ApplyPageEntry();
    RequestAnimTick();  // 置脏 + 确保 tick 定时器在跑（页面切换动画 + 步骤栏高亮）
}

DWORD WINAPI InstallerWindow::InstallThreadProc(LPVOID p) {
    static_cast<InstallerWindow*>(p)->InstallThread();
    return 0;
}

void InstallerWindow::WriteAbortResult(const std::wstring& error) {
    // §1：唯一结果写入器（spk::WriteInstallResultIni）的中止包装（abort=1 + error）。
    // resultWritten_ 守卫：引擎已写成功时此处为 no-op（同一进程最多写一次结果）。
    if (resultWritten_) return;
    spk::InstallOptions options;
    options.desktop = state_.optDesktop;
    options.startmenu = state_.optStartmenu;
    options.autostart = state_.optAutostart;
    options.ctxmenu = state_.optContextMenu;
    if (spk::WriteInstallResultIni(resultPath_, state_.installDir, /*abort=*/true, error, options)) {
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
    // T11/Acceptance：Finish(Repair) —— 仅当用户勾选「立即启动 Sopeek」时启动
    // （复选框直接绑定 state_.optLaunchAfterRepair，默认 false），随后关窗；未勾选只关窗。
    if (state_.operation == Operation::Repair) {
        if (!state_.optLaunchAfterRepair) {
            DiagLog(L"repair finish without launch");
            PostMessageW(window_, WM_CLOSE, 0, 0);
            return;
        }
        const spk::LaunchOutcome repairOutcome =
            spk::LaunchInstalledAppDeElevated(state_.installDir, window_);
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
    const spk::LaunchOutcome outcome =
        spk::LaunchInstalledAppDeElevated(state_.installDir, window_);
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
    spk::InstallOptions options;
    options.desktop = state_.optDesktop;
    options.startmenu = state_.optStartmenu;
    options.autostart = state_.optAutostart;
    options.ctxmenu = state_.optContextMenu;

    // Todo 13：真实引擎 = §11 哨兵等待 → 预扫描 → 逐文件复制（permille 上报）→
    // §3 取消清理 → §1 结果 INI。引擎内无 HWND/COM，结果 INI 由其唯一写入器完成。
    // T11：installMode_ 在创建线程前由 UI 线程写入，worker 只读（无并发写）。
    spk::InstallEngine engine(payload_, state_.installDir, resultPath_);
    const spk::InstallResult result =
        engine.Run(options, installMode_, cancel_, [this](int permille) {
            // §10：PostMessage 节流 ~30fps；终值 1000 恒发（节流不得吞掉终值）。
            const ULONGLONG now = GetTickCount64();
            if (permille == 0 || permille >= 1000 || now - lastProgressPostTick_ >= kProgressPostIntervalMs) {
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

void InstallerWindow::StartInstall(spk::InstallMode mode) {
    if (installing_) return;  // 防重入（导航已门控，此处为最后防线）
    installMode_ = mode;
    // 每次安装重置取消/结果/错误/进度状态（含失败后重装路径）。
    cancel_ = false;
    closePending_ = false;
    resultWritten_ = false;
    installCancelled_ = false;
    installTimedOut_ = false;
    progressPermille_ = 0;
    lastProgressPostTick_ = 0;
    // 重置解压与完成停留状态（含失败后重装路径）。
    initProgressActive_ = false;
    lastInitProgressUpdateMs_ = 0.0;
    completionHold_ = false;
    if (window_) KillTimer(window_, kCompletionHoldTimerId);
    errorText_.clear();
    {
        std::lock_guard<std::mutex> lock(errorMutex_);
        installError_.clear();
    }
    installing_ = true;
    // T11：修复期间保持 tick 定时器（setup 退出 watchdog 依赖它；无动画时也不停表）。
    keepTickAlive_ = true;
    if (mode == spk::InstallMode::Repair) {
        // T11：repair 复用 Progress 页 —— operation 是唯一来源（SetPage/布局/步骤栏均读它）。
        if (state_.operation != Operation::Update) state_.operation = Operation::Repair;
    } else {
        state_.operation = Operation::Install;
    }
    SetPage(Progress);
    if (mode == spk::InstallMode::Repair && progressPage_) {
        progressPage_->SetKind(state_.operation);
        progressPage_->SetCancellable(false);  // 修复中不允许取消/ESC/X
        progressPage_->SetNotice(std::wstring(ApplyOperationLabel(state_.operation)) + L"过程中请勿关闭窗口");
    }
    // 解压进度由暂存目录中实际释放的字节驱动。
    BeginInitProgress();
    DiagLog(std::wstring(L"install start dir=") + state_.installDir + L" mode=" +
            std::to_wstring(mode == spk::InstallMode::Repair ? 1 : 0));
    installThread_ = CreateThread(nullptr, 0, InstallThreadProc, this, 0, nullptr);
    if (!installThread_) {
        installing_ = false;
        keepTickAlive_ = false;
        initProgressActive_ = false;
        completionHold_ = false;
        WriteAbortResult(L"thread-create-failed");  // §1：失败必须写 error=
        if (mode == spk::InstallMode::Repair) {
            const std::wstring action = ApplyOperationLabel(state_.operation);
            ShowError(L"无法开始" + action, action + L"线程创建失败，程序文件未改动。", L"关闭", L"");
        } else {
            ShowError(L"无法开始安装", L"安装线程创建失败，程序文件未改动。", L"关闭", L"");
        }
    }
}

// 解压阶段按 NSIS 已释放的字节推进，payload.ready 是切换阶段的边界。
void InstallerWindow::BeginInitProgress() {
    initProgressActive_ = true;
    completionHold_ = false;
    lastInitProgressUpdateMs_ = spk::SteadyNowMs() - static_cast<double>(kPreparePollMs);
    prepareLastBytes_ = 0;
    prepareStallStartMs_ = spk::SteadyNowMs();
    prepareStallWarned_ = false;
    prepareLastDiagBucket_ = 0;
    progressPermille_ = 0;
    if (progressPage_) {
        progressPage_->SetProgressPermille(0);
        const std::wstring action = ApplyOperationLabel(state_.operation);
        progressPage_->SetStageText(L"正在准备" + action + L"文件");
        progressPage_->SetNotice(L"正在解压" + action + L"文件，请稍候…");
    }
    DiagLog(L"init progress start");
}

// 仅 UI 侧推进：等待 payload.ready 期间按 NSIS 实际写出的 payload 字节数推进。
// 扫描节流 500ms，只允许前进。总大小未知时显示已解压字节数。
void InstallerWindow::AdvanceInitProgress(double now_ms) {
    if (!installing_ || !initProgressActive_) return;
    if (now_ms - lastInitProgressUpdateMs_ < static_cast<double>(kPreparePollMs)) return;
    lastInitProgressUpdateMs_ = now_ms;

    std::error_code sentinelError;
    if (std::filesystem::exists(spk::PayloadSentinelPath(payload_), sentinelError)) {
        EndInitProgress();
        return;
    }

    const std::uint64_t bytes = static_cast<std::uint64_t>(spk::PayloadTotalBytes(payload_));
    if (bytes != prepareLastBytes_) {
        prepareLastBytes_ = bytes;
        prepareStallStartMs_ = now_ms;
        prepareStallWarned_ = false;
    }

    int target = progressPermille_;
    if (payloadBytes_ > 0) {
        const auto fraction = static_cast<long double>(std::min(bytes, payloadBytes_)) / payloadBytes_;
        target = std::max(target, static_cast<int>(fraction * kExtractionEndPermille));
    }

    if (target > progressPermille_) {
        progressPermille_ = target;
        if (progressPage_) progressPage_->SetProgressPermille(target);
    }

    const bool waitingForExtraction = (payloadBytes_ == 0 || bytes < payloadBytes_);
    const bool stalled = waitingForExtraction &&
        (now_ms - prepareStallStartMs_ >= static_cast<double>(kPrepareStallWarnMs));
    if (progressPage_) {
        if (stalled) {
            // 停顿提示必须持续显示；不能下一轮又被字节计数文案覆盖。
            progressPage_->SetStageText(L"正在等待安装文件解压");
            progressPage_->SetNotice(L"如果长时间没有变化，请检查磁盘空间或杀毒软件。");
        } else if (payloadBytes_ > 0 && bytes >= payloadBytes_) {
            progressPage_->SetStageText(L"正在完成安装文件解压");
            progressPage_->SetNotice(L"正在等待解压完成确认…");
        } else if (payloadBytes_ > 0) {
            progressPage_->SetStageText(L"正在解压安装文件");
            progressPage_->SetNotice(spk::FormatBytes(bytes) + L" / " +
                                     spk::FormatBytes(payloadBytes_));
        } else {
            progressPage_->SetStageText(L"正在解压安装文件");
            if (bytes > 0) {
                progressPage_->SetNotice(spk::FormatBytes(bytes) + L" 已读取，请稍候…");
            } else {
                progressPage_->SetNotice(L"正在读取安装文件，请稍候…");
            }
        }
    }
    if (stalled && !prepareStallWarned_) {
        prepareStallWarned_ = true;
        DiagLog(L"prepare stalled bytes=" + std::to_wstring(bytes) + L" total=" +
                std::to_wstring(payloadBytes_));
    }

    const int diagBucket = progressPermille_ / 100;
    if (diagBucket > prepareLastDiagBucket_) {
        prepareLastDiagBucket_ = diagBucket;
        DiagLog(L"prepare progress bytes=" + std::to_wstring(bytes) + L" total=" +
                std::to_wstring(payloadBytes_) + L" permille=" +
                std::to_wstring(progressPermille_));
    }
}

void InstallerWindow::EndInitProgress() {
    if (!initProgressActive_) return;
    initProgressActive_ = false;
    progressPermille_ = kExtractionEndPermille;
    if (progressPage_) {
        progressPage_->SetProgressPermille(progressPermille_);
        progressPage_->SetStageText(L"正在复制文件");
        progressPage_->SetNotice(L"");
    }
    DiagLog(L"extraction complete permille=" + std::to_wstring(progressPermille_));
}

// 成功收尾：先把进度条置满并停留 ~300ms（让 220ms 填充动画可见），再由 WM_TIMER(id=3)
// 切到完成页。保持 tick 存活以便该帧被绘制。
void InstallerWindow::BeginCompletionHold() {
    progressPermille_ = 1000;
    if (progressPage_) {
        progressPage_->SetProgressPermille(1000);
        progressPage_->SetStageText(L"完成");
        progressPage_->SetNotice(std::wstring(ApplyOperationLabel(state_.operation)) + L"完成，正在进入完成页…");
    }
    keepTickAlive_ = true;
    RequestAnimTick();
    completionHold_ = true;
    const UINT_PTR timer =
        window_ ? SetTimer(window_, kCompletionHoldTimerId, kCompletionHoldMs, nullptr) : 0;
    if (timer == 0) {
        // UI-fix：SetTimer 失败不得把窗口卡在 Progress——立即回退切完成页。
        completionHold_ = false;
        keepTickAlive_ = false;
        DiagLog(L"completion hold timer failed -> immediate Finish");
        SetPage(Finish);
        return;
    }
    DiagLog(L"completion hold start");
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
    // UI-fix（进度 UX）：卸载路径不受初始化斜坡/映射/完成停留影响（行为不变），
    // 但完整复位相关状态并与 StartInstall 对称（含杀掉可能陈旧的停留定时器）。
    initProgressActive_ = false;
    lastInitProgressUpdateMs_ = 0.0;
    completionHold_ = false;
    if (window_) KillTimer(window_, kCompletionHoldTimerId);
    SetPage(Progress);
    if (progressPage_) {
        progressPage_->SetKind(spk::ProgressPage::Kind::Uninstall);
        progressPage_->SetCancellable(false);  // 卸载中不允许取消/ESC/X
        progressPage_->SetNotice(L"卸载过程中请勿关闭窗口");
        progressPage_->SetStageText(UninstallStageLabel(spk::UninstallStage::Started));
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
        if (!spk::WaitForDecisionAck(decisionPath_, spk::protocol::kAckTimeoutMs)) {
            ShowError(L"无法开始卸载",
                      L"安装程序未在限定时间内确认卸载请求，卸载未开始。", L"关闭", L"");
            return;
        }
    }

    // helperPid_==0 时由协调器先写 request 再启动 helper；非 0 时只附着，不二次启动。
    uninstallCoordinator_ = std::make_shared<spk::UninstallCoordinator>(
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

    // 设计稿用 Microsoft YaHei（Latin 与 CJK 同一族）；TextFactory 会在缺失时回退。
    textFactory_.Initialize(dwrite, L"Microsoft YaHei", L"Segoe UI");
    glyphFont_.Initialize(dwrite);
    logoBitmap_.Load(dc);            // 标题栏 26x26 图标（IDR_LOGO）
    heroBgBitmap_.Load(dc, 106);     // 英雄页背景图（IDR_HERO_BG，透明底）
    heroArt_.Initialize(render_.D2DFactory());  // 品牌图形（矢量，一次构建）
    if (!spk::ReadUtf8Resource(104, userAgreementText_)) {  // IDR_USERAGREEMENT
        userAgreementText_ = L"（用户协议资源缺失：IDR_USERAGREEMENT 104 未编入安装器）";
    }
    if (!spk::ReadUtf8Resource(102, licenseText_)) {  // IDR_LICENSE
        licenseText_ = L"（许可协议资源缺失：IDR_LICENSE 102 未编入安装器）";
    }

    welcomePage_ = std::make_unique<spk::WelcomePage>(state_);
    welcomePage_->BindAnimator(&animator_);
    welcomePage_->BindText(&textFactory_);
    welcomePage_->BindGlyphs(&glyphFont_);
    welcomePage_->SetHeroArt(&heroArt_);
    welcomePage_->SetBackground(&heroBgBitmap_);
    // 欢迎页为英雄页——页内大按钮「下一步」承担前进（设计稿无许可页，直达配置页）。
    welcomePage_->SetOnNextIntent([this]() { GoNext(); });

    configurePage_ = std::make_unique<spk::ConfigurePage>(state_);
    configurePage_->SetPayloadDir(payload_, payloadBytes_);
    configurePage_->SetOwner(window_);
    configurePage_->BindAnimator(&animator_);
    configurePage_->BindText(&textFactory_);
    configurePage_->BindGlyphs(&glyphFont_);
    configurePage_->SetOnNext([this]() { GoNext(); });
    configurePage_->SetOnBack([this]() { GoBack(); });
    configurePage_->SetOnOpenDocument([this](bool userAgreement) {
        OpenLicensePage(userAgreement);
    });
    // Todo 15 证据：Configure 页 PathField 的实际持值（= /installdir 预填结果）。
    DiagLog(L"configure prefill field=" + configurePage_->Field().Path());

    progressPage_ = std::make_unique<spk::ProgressPage>(state_);
    progressPage_->BindAnimator(&animator_);
    progressPage_->BindText(&textFactory_);
    progressPage_->BindGlyphs(&glyphFont_);
    progressPage_->SetOnCancel([this]() { RaiseCancelIntent(); });

    finishPage_ = std::make_unique<spk::FinishPage>(state_);
    finishPage_->BindAnimator(&animator_);
    finishPage_->BindText(&textFactory_);
    finishPage_->BindGlyphs(&glyphFont_);
    finishPage_->SetHeroArt(&heroArt_);
    finishPage_->SetBackground(&heroBgBitmap_);
    // 完成页：「立即体验」= 去提权启动 + 关窗；「退出」= 直接关窗。
    finishPage_->SetOnFinishIntent([this]() { OnFinishIntent(); });
    finishPage_->SetOnExitIntent([this]() { PostMessageW(window_, WM_CLOSE, 0, 0); });

    // T10：三个英雄页（T7）。回调仅接到本类的占位接缝；T11/T12/T13 替换为真实业务。
    maintenancePage_ = std::make_unique<spk::MaintenancePage>(state_);
    maintenancePage_->BindAnimator(&animator_);
    maintenancePage_->BindText(&textFactory_);
    maintenancePage_->BindGlyphs(&glyphFont_);
    maintenancePage_->SetBackground(&heroBgBitmap_);
    maintenancePage_->SetOnUpdate([this]() { ConfigureMaintenance(Operation::Update); });
    maintenancePage_->SetOnRepair([this]() { OnMaintenanceRepairIntent(); });
    maintenancePage_->SetOnUninstall([this]() { OnMaintenanceUninstallIntent(); });
    maintenancePage_->SetOnCancel([this]() { OnMaintenanceCancelIntent(); });

    uninstallHeroPage_ = std::make_unique<spk::UninstallConfirmPage>(state_);
    uninstallHeroPage_->SetChecklist(false);
    uninstallHeroPage_->SetBackground(&heroBgBitmap_);
    uninstallHeroPage_->BindAnimator(&animator_);
    uninstallHeroPage_->BindText(&textFactory_);
    uninstallHeroPage_->BindGlyphs(&glyphFont_);
    uninstallHeroPage_->SetOnConfirm([this]() { SetPage(UninstallChecklist); });
    uninstallHeroPage_->SetOnCancel([this]() { OnUninstallCancelIntent(); });

    uninstallConfirmPage_ = std::make_unique<spk::UninstallConfirmPage>(state_);
    uninstallConfirmPage_->BindAnimator(&animator_);
    uninstallConfirmPage_->BindText(&textFactory_);
    uninstallConfirmPage_->BindGlyphs(&glyphFont_);
    uninstallConfirmPage_->SetOnConfirm([this]() { OnUninstallConfirmIntent(); });
    uninstallConfirmPage_->SetOnCancel([this]() { OnUninstallCancelIntent(); });

    messagePage_ = std::make_unique<spk::MessagePage>(state_);
    messagePage_->BindAnimator(&animator_);
    messagePage_->BindText(&textFactory_);
    messagePage_->BindGlyphs(&glyphFont_);
    messagePage_->SetOnPrimary([this]() { OnMessagePrimaryIntent(); });
    messagePage_->SetOnSecondary([this]() { OnMessageSecondaryIntent(); });

    licenseSheet_.BindText(&textFactory_);
    licenseSheet_.BindWriteFactory(dwrite);
    licenseSheet_.BindAnimator(&animator_);
    licenseSheet_.BackButton().SetOnClick([this]() { GoBack(); });

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
            shellLayout_ = spk::ComputeShellLayout(
                spk::IsHeroPage(state_.page) || state_.operation != Operation::Install);
        }
        ApplyPageEntry();
    }
    RequestAnimTick();
    DiagLog(L"pages ready count=7");
}


D2D1_RECT_F InstallerWindow::PageRect() const {
    // 页内容矩形 = 内容卡片 + Win10 兜底外扩边距（页布局与命中坐标同偏移）。
    const float m = static_cast<float>(shadowMarginDip_);
    const D2D1_RECT_F& c = shellLayout_.contentCard;
    return D2D1::RectF(c.left + m, c.top + m, c.right + m, c.bottom + m);
}

void InstallerWindow::LayoutPages() {
    if (!pagesReady_) return;
    const D2D1_RECT_F card = PageRect();
    switch (state_.page) {
        case Welcome: welcomePage_->Layout(card); break;
        case Configure: configurePage_->Layout(card); break;
        case License: licenseSheet_.Layout(card); break;
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
        case UninstallConfirm: uninstallHeroPage_->Layout(card); break;
        case UninstallChecklist: uninstallConfirmPage_->Layout(card); break;
        case Message: messagePage_->Layout(card); break;
        default: break;
    }
}

void InstallerWindow::ApplyPageEntry() {
    if (!pagesReady_) return;
    const D2D1_RECT_F card = PageRect();
    switch (state_.page) {
        case Welcome:
            welcomePage_->SyncFromState();
            welcomePage_->Layout(card);
            break;
        case License:
            licenseSheet_.Layout(card);
            licenseSheet_.Enter();
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
            uninstallHeroPage_->Layout(card);
            break;
        case UninstallChecklist:
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
}

void InstallerWindow::GoNext() {
    if (installing_) return;
    switch (state_.page) {
        case Welcome:
            SetPage(Configure);  // 设计稿没有许可协议页：欢迎页直达配置页
            break;
        case Configure:
            if (!configurePage_ || !configurePage_->CanProceed()) return;  // 不可写/空间不足/未同意
            configurePage_->SyncToState();  // 三个选项 + 同意写回 AppState
            if (mode_ == AppMode::Maintenance) StartRepair();
            else StartInstall();
            break;
        default:
            return;  // Progress/Finish 无下一步
    }
}

void InstallerWindow::GoBack() {
    if (installing_) return;  // 「安装中不可返回」
    switch (state_.page) {
        case License:
            SetPage(Configure);
            break;
        case Configure:
            SetPage(mode_ == AppMode::Maintenance ? Maintenance : Welcome);
            break;
        default:
            return;  // Welcome/Progress/Finish 无上一步
    }
}

void InstallerWindow::RaiseCancelIntent() {
    DiagLog(L"cancel intent raised installing=" + std::to_wstring(installing_ ? 1 : 0));
    // Todo 13：安装中同时置引擎取消信号（§3：安全停止 + 清理本次写入 + abort=1）。
    if (installing_) {
        cancel_ = true;
        initProgressActive_ = false;  // UI-fix（进度 UX）：取消即停止初始化斜坡
    }
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

void InstallerWindow::SetMaintenanceOffer(MaintenanceOffer offer, std::wstring installedVersion) {
    maintenanceOffer_ = offer;
    installedPackageVersion_ = std::move(installedVersion);
}

void InstallerWindow::EnterMaintenanceMode() {
    if (!maintenancePage_) return;
    // T11：Detect 是唯一的安装判定来源（exe 或 _internal 存在）；版本/选项一并读取。
    maintenanceInfo_ = spk::Detect(state_.installDir);
    if (!maintenanceInfo_.installDir.empty()) {
        state_.installDir = maintenanceInfo_.installDir;  // 归一化后的路径（D10）
    }
    state_.installedVersion = installedPackageVersion_.empty() ? maintenanceInfo_.version : installedPackageVersion_;
    maintenancePage_->SetOffer(maintenanceOffer_);
    DiagLog(L"maintenance offer=" + std::to_wstring(static_cast<int>(maintenanceOffer_)));
    state_.installDetected = maintenanceInfo_.detected;
    maintenancePage_->SetInfo(maintenanceInfo_.installDir, state_.installedVersion,
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
        ShowError(L"未找到已安装的 Sopeek",
                  L"在 " + state_.installDir +
                      L" 未检测到 Sopeek 的程序文件，无法执行修复。",
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
        return fail(L"未检测到已安装的 Sopeek，无法修复。");
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
    const std::wstring probe = dir + L"\\.spk-repair-probe-" +
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
    const bool ok = spk::WriteMaintenanceDecision(decisionPath_, action, GetCurrentProcessId());
    if (ok) maintenanceDecisionWritten_ = true;
    DiagLog(L"maintenance decision action=" + std::to_wstring(actionValue) + L" ok=" +
            std::to_wstring(ok ? 1 : 0) + L" path=" + decisionPath_);
    return ok;
}

void InstallerWindow::ConfigureMaintenance(Operation operation) {
    if (mode_ != AppMode::Maintenance || !maintenanceInfo_.detected || installing_ || closingApp_) return;
    if (maintenanceOffer_ == MaintenanceOffer::UninstallOnly) return;
    if (operation == Operation::Update && maintenanceOffer_ != MaintenanceOffer::Update) return;
    if (operation == Operation::Repair && maintenanceOffer_ == MaintenanceOffer::Update) {
        DiagLog(L"repair requires matching package");
        ShowError(L"需要同版本安装包",
                  L"要修复当前版本，请运行与已安装的 Sopeek 版本相同的安装包：" + state_.installedVersion,
                  L"返回", MessageAction::ReturnToMaintenance, L"", MessageAction::None);
        return;
    }
    state_.operation = operation;
    state_.optDesktop = maintenanceInfo_.optDesktop;
    state_.optStartmenu = maintenanceInfo_.optStartmenu;
    state_.optAutostart = maintenanceInfo_.optAutostart;
    state_.optContextMenu = maintenanceInfo_.optContextMenu;
    state_.optLaunchAfterRepair = false;
    state_.agreed = false;
    configurePage_->SetMaintenanceMode(operation);
    SetPage(Configure);
}

void InstallerWindow::StartRepair() {
    if (mode_ != AppMode::Maintenance) {
        DiagLog(L"repair intent ignored outside maintenance mode");
        return;
    }
    if (installing_ || closingApp_ || !state_.agreed) return;
    const bool updating = state_.operation == Operation::Update;
    if (maintenanceOffer_ != (updating ? MaintenanceOffer::Update : MaintenanceOffer::Repair)) return;

    std::wstring error;
    if (!RepairPreflight(&error)) {
        // 预检失败：不写 decision、不启动引擎（空间检查留给引擎预扫描）。
        // suppress 必须在展示前置位：X/ESC 走 OnMaintenanceCloseIntent 也不得补写 cancel。
        maintenanceSuppressDecision_ = true;
        DiagLog(L"repair preflight failed: " + error);
        ShowError(updating ? L"无法更新" : L"无法修复", error, L"关闭", L"");
        return;
    }

    if (!IsInstalledAppRunning(state_.installDir)) {
        // 未运行：直接写 decision 并开始修复。
        BeginRepairInstall();
        return;
    }

    // 运行中：先异步关闭（spk::CloseInstalledApp 按完整路径匹配，最长 5s 优雅 + 2s 强制），
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
    messagePage_->SetContent(L"正在关闭 Sopeek",
                             updating ? L"更新前需要先关闭正在运行的 Sopeek，请稍候。"
                                      : L"修复前需要先关闭正在运行的 Sopeek，请稍候。", L"", L"",
                             false);
    messagePage_->SetBusy(true, L"正在关闭…");
    SetPage(Message);
    RequestAnimTick();

    closeThread_ = CreateThread(nullptr, 0, CloseThreadProc, this, 0, nullptr);
    if (!closeThread_) {
        closingApp_ = false;
        keepTickAlive_ = false;
        // T13：保留 T11 的「重试 / 取消」决策语义（取消 = 写一次 maintenance cancel）。
        ShowError(L"无法关闭 Sopeek",
                  L"无法创建关闭线程，请手动退出 Sopeek 后重试。", L"重试",
                  MessageAction::RetryRepair, L"取消", MessageAction::CancelMaintenance);
    }
}

void InstallerWindow::BeginRepairInstall() {
    if (state_.setupExited) {
        // setup 已退出：不再开始任何写操作（避免无主修复）。
        ShowError(std::wstring(ApplyOperationLabel(state_.operation)) + L"已终止",
                  L"安装程序已退出，操作已终止", L"关闭", L"");
        return;
    }
    const bool updating = state_.operation == Operation::Update;
    if (!WriteMaintenanceDecisionOnce(updating ? MaintenanceAction::Update : MaintenanceAction::Repair)) {
        // decision 写不进去就不能开始修复：setup 无法获知 repair 意图。
        // 同样在展示前置 suppress —— 关闭（X/ESC）也不得再补写 cancel。
        maintenanceSuppressDecision_ = true;
        ShowError(updating ? L"无法开始更新" : L"无法开始修复", L"无法写入维护决定文件，操作未开始。", L"关闭", L"");
        return;
    }
    StartInstall(spk::InstallMode::Repair);
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
        case MessageAction::ReturnToMaintenance:
            SetPage(Maintenance);
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
    const spk::ProcessCloseResult result =
        spk::CloseInstalledApp(closeTargetDir_, /*gracefulTimeoutMs=*/5000,
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
    if (!setupProcess_) return;
    if (awaitingSetupExit_) {
        const DWORD wait = WaitForSingleObject(setupProcess_, 0);
        if (wait == WAIT_TIMEOUT) return;
        awaitingSetupExit_ = false;
        keepTickAlive_ = false;
        DWORD code = 0;
        const bool known = wait == WAIT_OBJECT_0 && GetExitCodeProcess(setupProcess_, &code);
        DiagLog(L"setup final exit=" + (known ? std::to_wstring(code) : std::wstring(L"unknown")));
        if (known && code == 0 && !state_.setupExited) {
            if (closePending_) {
                DestroyWindow(window_);
            } else {
                BeginCompletionHold();
            }
        } else {
            ShowError(std::wstring(ApplyOperationLabel(state_.operation)) + L"失败",
                      !known ? L"无法确认安装程序的最终结果。" : state_.setupExited && !code
                          ? L"安装程序提前退出，操作已终止。"
                          : L"安装程序未能完成配置，退出码为 " + std::to_wstring(code) + L"。",
                      L"关闭", L"");
        }
        return;
    }
    if (state_.setupExited) return;
    // T12：维护卸载在 setup ack 后，setup 主动退出属于正常收尾（D15 C2），
    // 不得按“setup 提前退出”中止卸载。
    if (uninstallRunning_) return;
    // 仅在操作进行中监视：维护页/完成页停留时 setup 退出属于正常收尾，不应中止。
    if (!installing_ && !closingApp_) return;
    if (WaitForSingleObject(setupProcess_, 0) != WAIT_OBJECT_0) return;
    // NSIS 可在 worker 提交结果后、WM_INSTALL_DONE 到达之前退出。此时让
    // WM_INSTALL_DONE 消费引擎结果，再按原进程的退出码收尾。
    if (installing_ && (resultWritten_ || GetPrivateProfileIntW(
            L"install", L"abort", -1, resultPath_.c_str()) == 0)) return;
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
    ConfigureMaintenance(Operation::Repair);
}

void InstallerWindow::OnMaintenanceUninstallIntent() {
    // T11：只导航到卸载确认页（页 6）；request/helper/进程收尾全部归 T12。
    // 导航本身不写 decision（只有用户最终选择 uninstall 时才由 T12 写）。
    if (maintenanceOffer_ == MaintenanceOffer::Update) return;
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
    messagePage_->SetContent(L"正在关闭 Sopeek",
                             L"卸载前需要先关闭正在运行的 Sopeek，请稍候。", L"",
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
        ShowError(L"无法关闭 Sopeek",
                  L"无法创建关闭线程，请手动退出 Sopeek 后重试。", L"重试",
                  MessageAction::RetryUninstall, L"取消", secondary);
    }
}

void InstallerWindow::OnUninstallCancelIntent() {
    // T12：维护模式的确认页取消 → 返回维护页（不关窗、不写 decision）；
    // /uninstall 模式：helper 启动的 UI 先写 cancelled=1 再退出，直接启动则直接退出。
    if (installing_ || closingApp_ || uninstallRunning_) return;
    if (state_.page == UninstallChecklist) {
        SetPage(UninstallConfirm);
        return;
    }
    if (mode_ == AppMode::Maintenance) {
        DiagLog(L"uninstall cancel -> Maintenance");
        SetPage(Maintenance);
        return;
    }
    if (mode_ == AppMode::Uninstall) {
        if (helperPid_ != 0) {
            const bool ok = spk::WriteUninstallCancel(uninstallRequestPath_);
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
        L"关闭已安装的 Sopeek 失败（" +
        (error.empty() ? std::wstring(L"未知错误") : error) +
        L"）。请手动退出程序后重试。";
    if (forUninstall) {
        const MessageAction secondary = mode_ == AppMode::Maintenance
                                            ? MessageAction::CancelMaintenance
                                            : MessageAction::Close;
        ShowError(L"无法关闭 Sopeek", body, L"重试",
                  MessageAction::RetryUninstall, L"取消", secondary);
        return;
    }
    ShowError(L"无法关闭 Sopeek", body, L"重试", MessageAction::RetryRepair,
              L"取消", MessageAction::CancelMaintenance);
}

void InstallerWindow::OnUninstallProgressMessage(WPARAM wp, LPARAM lp) {
    // T12：wParam=permille 0..1000，lParam=protocol::UninstallStage（中文文案在此映射）。
    if (state_.operation != Operation::Uninstall) return;
    if (uninstallTerminal_) return;          // 终态后忽略陈旧进度
    if (state_.page != Progress) return;     // 仅进度页消费
    const int stageValue = static_cast<int>(static_cast<long long>(lp));
    if (!IsKnownUninstallStage(stageValue)) return;
    const auto stage = static_cast<spk::UninstallStage>(stageValue);
    const unsigned long long rawPermille = static_cast<unsigned long long>(wp);
    const int permille = rawPermille > 1000ull ? 1000 : static_cast<int>(rawPermille);
    progressPermille_ = permille;
    if (progressPage_) {
        progressPage_->SetProgressPermille(permille);
        progressPage_->SetStageText(UninstallStageLabel(stage));
        // D15 C3：未勾选删除用户数据时，helper 跳过用户数据阶段并保留全部数据。
        if (stage == spk::UninstallStage::RemovingUserData && !state_.deleteUserData) {
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
    const auto stage = static_cast<spk::UninstallStage>(stageValue);
    DiagLog(L"uninstall-done stage=" + std::to_wstring(stageValue));

    switch (stage) {
        case spk::UninstallStage::Done:
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
        case spk::UninstallStage::Failed: {
            const std::wstring error =
                uninstallCoordinator_ ? uninstallCoordinator_->Error() : std::wstring();
            // T13：终态失败页。关闭走统一 WM_CLOSE；operation==Uninstall 且 page==Message
            // 时绝不会补写 cancel，因此不会覆盖 helper 已落盘的 failed 终态。
            ShowError(L"卸载未完成",
                      error.empty() ? L"卸载过程中出现未知错误。" : error, L"关闭", L"");
            break;
        }
        case spk::UninstallStage::Cancelled:
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
        } else if ((state_.page == UninstallConfirm || state_.page == UninstallChecklist)) {
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

bool InstallerWindow::DispatchPageInput(const spk::InputEvent& event) {
    if (!pagesReady_) return false;
    // 控件命中区均为画布 DIP；ClientPointToDip 已扣除 Win10 阴影外扩边距。
    auto local = event;
    if (pageTransition_) local.x -= pageDirection_ * 18.0f * (1.0f - pageTransition_->Value());
    const bool consumed = state_.page == Configure && configurePage_
        ? configurePage_->OnInput(local)
        : ActivePageHost().Dispatch(local);
    if (consumed) RequestAnimTick();
    return consumed;
}

spk::WidgetHost& InstallerWindow::ActivePageHost() {
    static spk::WidgetHost empty;
    if (!pagesReady_) return empty;
    switch (state_.page) {
        case Welcome: return welcomePage_->Host();
        case License: return licenseSheet_.Host();
        case Configure: return configurePage_->Host();
        case Progress: return progressPage_->Host();
        case Finish: return finishPage_->Host();
        case Maintenance: return maintenancePage_->Host();
        case UninstallConfirm: return uninstallHeroPage_->Host();
        case UninstallChecklist: return uninstallConfirmPage_->Host();
        case Message: return messagePage_->Host();
        default: return empty;
    }
}

void InstallerWindow::RenderPage(ID2D1DeviceContext* ctx, const spk::Theme& theme, int page) {
    if (!pagesReady_ || !ctx) return;
    switch (page) {
        case Welcome: spk::RenderWelcome(ctx, theme, *welcomePage_); break;
        case License: licenseSheet_.Render(ctx, theme); break;
        case Configure: spk::RenderConfigure(ctx, theme, *configurePage_); break;
        // T10：页 3/4 的 Kind 已在 ApplyPageEntry/LayoutPages 中按 state_.operation
        // 同步（SetKind 会重建 Tab 顺序，禁止在逐帧渲染路径重复调用）。
        case Progress: spk::RenderProgress(ctx, theme, *progressPage_); break;
        case Finish: spk::RenderFinish(ctx, theme, *finishPage_); break;
        case Maintenance: spk::RenderMaintenance(ctx, theme, *maintenancePage_); break;
        case UninstallConfirm: spk::RenderUninstallConfirm(ctx, theme, *uninstallHeroPage_); break;
        case UninstallChecklist: spk::RenderUninstallConfirm(ctx, theme, *uninstallConfirmPage_); break;
        case Message: spk::RenderMessage(ctx, theme, *messagePage_); break;
        default: break;
    }
}

void InstallerWindow::OpenLicensePage(bool userAgreement) {
    if (!pagesReady_ || state_.page != Configure) return;
    if (userAgreement) {
        licenseSheet_.SetContent(L"用户协议", userAgreementText_);
    } else {
        licenseSheet_.SetContent(L"开源协议（GNU AGPL-3.0）", licenseText_);
    }
    SetPage(License);
    DiagLog(L"license page open user_agreement=" + std::to_wstring(userAgreement ? 1 : 0));
}

// ==================== Todo 19（§17）：/auto 无人值守测试驱动 ====================
// 仅 SPK_TESTMODE 构建有驱动行为（宏由 cmake/test_mode.cmake 在 -DSPK_TESTMODE=ON
// 时定义）。生产构建保留的只有 EnableAutoDrive 的 no-op 定义；驱动成员/定时器/
// 推进逻辑全部被预处理器剔除——/auto 开关在生产中解析后即丢弃，无任何效果。

void InstallerWindow::EnableAutoDrive(AutoDriveOptions options) {
#ifdef SPK_TESTMODE
    autoDriveEnabled_ = true;
    autoProfile_ = std::move(options.profile);  // 空串 = 全默认档
    // T14/D15 H6：合法 stopPage 扩展到 Welcome..Message（0..7）；越界/负值 = 不停。
    autoStopPage_ = (options.stopPage >= Welcome && options.stopPage <= UninstallChecklist)
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

#ifdef SPK_TESTMODE

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
    if (autoStopPage_ == page) {
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
        if (actionIs(L"update") && maintenanceOffer_ == MaintenanceOffer::Update) {
            ConfigureMaintenance(Operation::Update);
            return;
        }
        if (actionIs(L"repair") && maintenanceOffer_ != MaintenanceOffer::UninstallOnly) {
            DiagLog(L"auto maintenance action=repair");
            OnMaintenanceRepairIntent();
            return;
        }
        if (actionIs(L"uninstall") && maintenanceOffer_ != MaintenanceOffer::Update) {
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
    if (page == UninstallConfirm || page == UninstallChecklist) {
        if (actionIs(L"uninstall")) {
            if (page == UninstallConfirm) {
                SetPage(UninstallChecklist);
                return;
            }
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
        if (messagePrimaryAction_ != MessageAction::None &&
            messagePrimaryAction_ != MessageAction::ReturnToMaintenance) {
            DiagLog(L"auto message action=" +
                    std::to_wstring(static_cast<int>(messagePrimaryAction_)));
            OnMessagePrimaryIntent();
            return;
        }
        // busy 态（正在关闭 app / 正在收尾）是瞬时等待：定时器必须继续跑，
        // 否则卸载收尾后切到 Finish 页再也不会被推进，QA 等不到
        // 'auto drive complete page=4'。只记一次，避免每个 tick 刷屏。
        if (!autoMessageWaitLogged_) {
            autoMessageWaitLogged_ = true;
            DiagLog(L"auto message waiting action=" + autoAction_);
        }
        return;
    }
    autoMessageWaitLogged_ = false;

    DiagLog(L"auto advance page=" + std::to_wstring(page));
    switch (page) {
        case Welcome:
            GoNext();  // 设计稿没有许可页：直达配置页
            break;
        case License:
            GoBack();
            break;
        case Configure:
            if (autoStopPage_ == License) {
                wchar_t document[16] = {};
                GetEnvironmentVariableW(L"SPK_TEST_OPEN_SHEET", document, ARRAYSIZE(document));
                OpenLicensePage(_wcsicmp(document, L"eula") == 0);
                break;
            }
            // 门控 = 目录可写 + 空间足够 + 已勾选同意；/auto 场景自动置同意。
            state_.agreed = true;
            if (configurePage_) configurePage_->SyncFromState();
            // GoNext → ConfigurePage::SyncToState() + StartInstall()（进入进度页）。
            GoNext();
            break;
        default:
            break;
    }
}

#endif  // SPK_TESTMODE
