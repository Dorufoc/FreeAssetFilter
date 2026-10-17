//
// installer_window.cpp - 无边框 DirectComposition 窗口外壳实现（Todo 2）。
//
// Frozen contracts（不得另行发明）：§4 窗口配方 / §5 Mica 透明度 / §6 DPI /
// §10 消息与进度 / §12 app_state.h / §13 资源所有权。
//
#include "installer_window.h"

#include <d2d1_1helper.h>
#include <shlobj.h>
#include <uxtheme.h>  // MARGINS（须先于 dwmapi.h）
#include <dwmapi.h>

#include <algorithm>
#include <filesystem>

#include "render/messages.h"  // §10：WM_INSTALL_PROGRESS/DONE + WM_UI_TICK
#include "render/install_engine.h"  // Todo 13：真实安装引擎（§1/§3/§10/§11 唯一实现）
#include "render/launch_forward.h"  // Todo 15：§15 去提权启动（唯一 owner）
// Todo 12：把 Todo 9/10/11 的页文件接入外壳（仅接线，不改页内部实现）。
#include "render/pages_progress.h"  // Progress/Finish 页
#include "render/pages_setup.h"     // Location/Options 页
#include "render/pages_welcome.h"   // Welcome/License 页

namespace fs = std::filesystem;

namespace {

// Todo 12：左栏步骤栏 6 步文案（向导步骤，非 pages_progress 的 4 段安装进度语义）。
constexpr const wchar_t* kStepLabels[6] = {L"欢迎",     L"许可协议", L"安装位置",
                                           L"安装选项", L"安装进度", L"完成"};
// Todo 12：底部导航按钮尺寸（DIP）。中心落在 bottomBar 垂直中线。
constexpr float kNavButtonW = 112.0f;
constexpr float kNavButtonH = 36.0f;
constexpr float kNavBackCenterX = 680.0f;  // 上一步按钮中心 X（DIP）
constexpr float kNavNextCenterX = 816.0f;  // 下一步按钮中心 X（DIP）
// UI-fix：页托管底部条按钮（取消 / 打开安装目录 / 完成）的统一几何（画布 DIP）。
// 页坐标 = 画布 + shadowMarginDip_（Win10 兜底外扩边距；页 Render 用 Identity 变换）。
constexpr float kFooterRightEdgeX = 872.0f;  // 页操作按钮右缘（画布）
constexpr float kCancelButtonW = 96.0f;      // 「取消」宽度
constexpr float kFinishButtonW = 96.0f;      // 「完成」宽度
constexpr float kOpenDirButtonW = 128.0f;    // 「打开安装目录」宽度
constexpr int kStepCount = 6;
}  // namespace

namespace {

constexpr wchar_t kWindowClass[] = L"FreeAssetFilterInstaller";  // §4 冻结类名
constexpr wchar_t kWindowTitle[] = L"FreeAssetFilter 安装程序";
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
                                 std::wstring installDir)
    : instance_(instance), payload_(std::move(payload)), resultPath_(std::move(resultPath)) {
    // §15/Todo 15：/installdir（重装预填）优先；缺省为产品默认安装目录。
    state_.installDir = installDir.empty() ? std::wstring(L"C:\\Program Files\\FreeAssetFilter")
                                           : std::move(installDir);
    // §16：生产动画采样 sink = 既有 DiagLog（env 门控，未设置时 no-op）。
    animator_.SetSink([](const std::string& line) { DiagLogRaw(line); });
}

InstallerWindow::~InstallerWindow() {
    // Todo 12：页面持 COM 对象（LicenseBox 的 IDWriteTextLayout 等），必须在
    // render_.Shutdown()（含 CoUninitialize）之前析构，避免在失效 COM 单元上 Release。
    welcomePage_.reset();
    licensePage_.reset();
    locationPage_.reset();
    optionsPage_.reset();
    progressPage_.reset();
    finishPage_.reset();
    render_.Shutdown();
}

int InstallerWindow::Run() {
    if (!CreateAppWindow()) return 1;
    MSG msg{};
    while (GetMessageW(&msg, nullptr, 0, 0) > 0) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }
    return static_cast<int>(msg.wParam);
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
    window_ = CreateWindowExW(exStyle, kWindowClass, kWindowTitle, style, left, top, widthPx,
                              heightPx, nullptr, nullptr, instance_, this);
    if (!window_) return false;

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

void InstallerWindow::Layout() {
    // §6：shell 几何唯一来源 = faf::ComputeShellLayout()（纯 DIP 计算，不依赖 DPI）。
    // 标题栏最小化/关闭命中区、左栏、内容卡片、底部条均由该结果提供。
    shellLayout_ = faf::ComputeShellLayout();
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
    const double nowMs = faf::SteadyNowMs();
    const bool worked = animator_.Tick(nowMs);  // 推进 + §16 每 tick 采样/边界行
    if (dirty_ || worked) {
        DiagLog(L"frame present t=" + std::to_wstring(static_cast<long long>(nowMs)) +
                L" anim=" + std::to_wstring(worked ? 1 : 0) +
                L" dirty=" + std::to_wstring(dirty_ ? 1 : 0));
        Render();  // 内部 PresentFrame() 已含 dcomp->Commit()
    }
    if (!animator_.IsActive() && !dirty_) {
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
        for (int i = 0; i < kStepCount; ++i) stepItems_[i].Render(ctx, faded);
        // 页内 Render 自行 SetTransform（会覆盖 shell 平移），渲染后再恢复边距平移。
        RenderActivePage(ctx, faded);
        ctx->SetTransform(D2D1::Matrix3x2F::Translation(m, m));
        // UI-fix：导航按钮按页面可见性绘制（Welcome 隐藏「上一步」；Progress/Finish 全隐藏，
        // 页内操作按钮已由外壳底部条托管，避免重复按钮）。
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
    faf::ComPtr<ID2D1SolidColorBrush> stroke;
    ctx->CreateSolidColorBrush(faded(theme.cardStroke), stroke.GetAddressOf());

    // 左栏（半透明层）。
    ctx->FillRectangle(s.rail, card.Get());

    // 内容卡片（圆角 + 描边）。
    const D2D1_ROUNDED_RECT cardRect =
        D2D1::RoundedRect(s.contentCard, faf::radius::Medium, faf::radius::Medium);
    ctx->FillRoundedRectangle(cardRect, card.Get());
    if (stroke) ctx->DrawRoundedRectangle(cardRect, stroke.Get(), 1.0f);

    // 底部条。
    ctx->FillRectangle(s.bottomBar, card.Get());

    // UI-fix：真实品牌头（产品名 SemiBold + 副标题）——此前 brandHeader 只画下方分隔线、
    // 从不绘制任何文字，是「标题栏与内容区间 ~120 DIP 空带」的观感来源之一。
    {
        const float bx = s.brandHeader.left + faf::spacing::M;
        const float by = s.brandHeader.top + faf::spacing::L;
        const float bw = (s.brandHeader.right - s.brandHeader.left) - 2.0f * faf::spacing::M;
        const float nameH = faf::fontsize::Subtitle + faf::spacing::S;
        const D2D1_COLOR_F nameColor = faded(theme.textPrimary);
        const D2D1_COLOR_F subColor = faded(theme.textSecondary);
        DrawTextLine(ctx, L"FreeAssetFilter", bx, by, bw, nameH, faf::fontsize::Subtitle,
                     nameColor, DWRITE_FONT_WEIGHT_SEMI_BOLD);
        DrawTextLine(ctx, L"文件浏览与管理工具", bx, by + nameH, bw,
                     faf::fontsize::Caption + faf::spacing::S, faf::fontsize::Caption, subColor);
    }

    // 左栏品牌头与步骤列表之间的分隔线（可视化 layout 的 brandHeader 边界）。
    faf::ComPtr<ID2D1SolidColorBrush> divider;
    if (SUCCEEDED(ctx->CreateSolidColorBrush(faded(theme.divider), divider.GetAddressOf()))) {
        ctx->DrawLine(D2D1::Point2F(s.brandHeader.left, s.brandHeader.bottom),
                      D2D1::Point2F(s.brandHeader.right, s.brandHeader.bottom), divider.Get(),
                      1.0f);
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
    DrawTextLine(ctx, kWindowTitle, faf::spacing::M, 0, titleW, titleH, faf::fontsize::Caption,
                 primary);

    faf::ComPtr<ID2D1SolidColorBrush> stroke;
    if (SUCCEEDED(ctx->CreateSolidColorBrush(primary, stroke.GetAddressOf()))) {
        const float mcx = (s.minButton.left + s.minButton.right) * 0.5f;
        const float mcy = (s.minButton.top + s.minButton.bottom) * 0.5f;
        ctx->DrawLine(D2D1::Point2F(mcx - 6, mcy), D2D1::Point2F(mcx + 6, mcy), stroke.Get(), 1.0f);
        const float ccx = (s.closeButton.left + s.closeButton.right) * 0.5f;
        const float ccy = (s.closeButton.top + s.closeButton.bottom) * 0.5f;
        ctx->DrawLine(D2D1::Point2F(ccx - 5, ccy - 5), D2D1::Point2F(ccx + 5, ccy + 5), stroke.Get(), 1.0f);
        ctx->DrawLine(D2D1::Point2F(ccx - 5, ccy + 5), D2D1::Point2F(ccx + 5, ccy - 5), stroke.Get(), 1.0f);
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
        const D2D1_POINT_2F pt = D2D1::Point2F(dx, dy);
        if (faf::HitTest(shellLayout_.closeButton, pt)) {
            PostMessageW(hwnd, WM_CLOSE, 0, 0);
            return 0;
        }
        if (faf::HitTest(shellLayout_.minButton, pt)) {
            ShowWindow(hwnd, SW_MINIMIZE);
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
        faf::InputEvent ev{};
        ev.kind = faf::InputEvent::Move;
        ev.x = dx;
        ev.y = dy;
        DispatchPointer(ev);
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
    if (msg == WM_CLOSE) {
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
        KillTickTimer();
        PostQuitMessage(0);
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
        if (installThread_) {
            CloseHandle(installThread_);
            installThread_ = nullptr;
        }
        const bool ok = wp != 0;
        const bool cancelled = installCancelled_.load();
        const bool timedOut = installTimedOut_.load();
        std::wstring error;
        {
            std::lock_guard<std::mutex> lock(errorMutex_);
            error = installError_;
        }
        DiagLog(L"install done ok=" + std::to_wstring(ok ? 1 : 0) + L" cancelled=" +
                std::to_wstring(cancelled ? 1 : 0) + L" timeout=" +
                std::to_wstring(timedOut ? 1 : 0) + L" error=" + error);
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
        if (cancelled) {
            if (progressPage_) progressPage_->MarkCancelled();  // §3：引擎确认已清理完成
            PostMessageW(hwnd, WM_CLOSE, 0, 0);  // 统一关闭路径（resultWritten_ 守卫防二次写）
            return 0;
        }
        // 超时/失败：引擎已写 abort=1 + error=；窗口内展示原因并保持打开（与载荷缺失
        // 启动错误同一展示路径）。
        errorText_ = error.empty() ? L"安装失败" : (L"安装失败：" + error);
        RequestAnimTick();
        return 0;
    }

    return DefWindowProcW(hwnd, msg, wp, lp);
}

void InstallerWindow::SetPage(int page) {
    // §12：页面唯一来源 = AppState::page；进入页面统一走 ApplyPageEntry（Synced + Layout）。
    state_.page = page;
    ApplyPageEntry();
    RequestAnimTick();  // 置脏 + 确保 tick 定时器在跑（页面切换动画 + 步骤栏高亮）
}

void InstallerWindow::Browse() {
    BROWSEINFOW bi{};
    bi.hwndOwner = window_;
    bi.lpszTitle = L"选择 FreeAssetFilter 安装目录";
    LPITEMIDLIST id = SHBrowseForFolderW(&bi);
    if (id) {
        wchar_t path[MAX_PATH] = {};
        if (SHGetPathFromIDListW(id, path)) state_.installDir = path;
        CoTaskMemFree(id);
        RequestAnimTick();  // 置脏 + 确保 tick 定时器在跑
    }
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
    // §15（唯一 owner = Todo 15）：完成后启动。
    //   * 仅当 `state_.optLaunch` 为真才启动（未勾选 → 绝不启动，直接关闭）。
    //   * 去提权：经 render/launch_forward.h 的 explorer 转发（绝不直接
    //     ShellExecuteW(exe)——会以管理员令牌运行）。
    if (state_.optLaunch) {
        const faf::LaunchOutcome outcome =
            faf::LaunchInstalledAppDeElevated(state_.installDir, window_);
        DiagLog(L"launch attempted opted=1 dir=" + state_.installDir + L" launched=" +
                std::to_wstring(outcome.launched ? 1 : 0) + L" missing=" +
                std::to_wstring(outcome.missingExe ? 1 : 0) + L" error=" + outcome.error);
        if (!outcome.launched) {
            // 目标缺失/转发失败：不崩溃、不关闭 —— 窗口内提示（与载荷缺失同一展示路径），
            // 用户可自行关闭（WM_CLOSE → 非安装中即销毁）。
            errorText_ = outcome.error.empty() ? L"启动失败" : (L"启动失败：" + outcome.error);
            RequestAnimTick();
            return;
        }
    } else {
        DiagLog(L"launch skipped opted=0");
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
    faf::InstallEngine engine(payload_, state_.installDir, resultPath_);
    const faf::InstallResult result = engine.Run(options, cancel_, [this](int permille) {
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

void InstallerWindow::StartInstall() {
    if (installing_) return;  // 防重入（导航已门控，此处为最后防线）
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
    SetPage(Progress);
    DiagLog(L"install start dir=" + state_.installDir);
    installThread_ = CreateThread(nullptr, 0, InstallThreadProc, this, 0, nullptr);
    if (!installThread_) {
        installing_ = false;
        WriteAbortResult(L"thread-create-failed");  // §1：失败必须写 error=
        errorText_ = L"安装线程创建失败";
        RequestAnimTick();
    }
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
    // UI-fix：欢迎页页内「开始」按钮已移除——前进统一走外壳底部条「下一步」（避免重复按钮）。

    licensePage_ = std::make_unique<faf::LicensePage>(state_);
    licensePage_->BindAnimator(&animator_);
    licensePage_->BindText(&textFactory_);
    licensePage_->BindGlyphs(&glyphFont_);
    licensePage_->BindWriteFactory(dwrite);
    // UI-fix：许可页页内「下一步」按钮已移除——门控由 UpdateNavButtons() 读 state_.agreed。

    locationPage_ = std::make_unique<faf::LocationPage>(state_);
    locationPage_->SetPayloadDir(payload_);
    locationPage_->SetOwner(window_);
    locationPage_->BindAnimator(&animator_);
    locationPage_->BindText(&textFactory_);
    locationPage_->BindGlyphs(&glyphFont_);
    // Todo 15 证据：Location 页 PathField 的实际持值（= /installdir 预填结果；页面进入
    // 时 ApplyPageEntry → SyncFromState 会再次从此值同步）。
    DiagLog(L"location prefill field=" + locationPage_->Field().Path());

    optionsPage_ = std::make_unique<faf::OptionsPage>(state_);
    optionsPage_->BindAnimator(&animator_);
    optionsPage_->BindText(&textFactory_);
    optionsPage_->BindGlyphs(&glyphFont_);

    progressPage_ = std::make_unique<faf::ProgressPage>(state_);
    progressPage_->BindAnimator(&animator_);
    progressPage_->BindText(&textFactory_);
    progressPage_->BindGlyphs(&glyphFont_);
    progressPage_->SetOnCancel([this]() { RaiseCancelIntent(); });

    finishPage_ = std::make_unique<faf::FinishPage>(state_);
    finishPage_->BindAnimator(&animator_);
    finishPage_->BindText(&textFactory_);
    finishPage_->BindGlyphs(&glyphFont_);
    // Todo 15 接线（§15）：勾选变化只记录意图（真实启动时点 = 完成按钮）；完成意图
    // → OnFinishIntent()：仅当 optLaunch 为真时才去提权启动，然后关闭窗口。
    finishPage_->SetOnLaunchIntent([this](bool optedIn) {
        DiagLog(L"launch intent opted=" + std::to_wstring(optedIn ? 1 : 0));
    });
    finishPage_->SetOnFinishIntent([this]() { OnFinishIntent(); });

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
    LayoutStepBar();
    LayoutFooterButtons();
    ApplyPageEntry();
    RequestAnimTick();
    DiagLog(L"pages ready count=6");
}

D2D1_RECT_F InstallerWindow::PageRect() const {
    // 页内容矩形 = 内容卡片 + Win10 兜底外扩边距（页布局与命中坐标同偏移）。
    const float m = static_cast<float>(shadowMarginDip_);
    const D2D1_RECT_F& c = shellLayout_.contentCard;
    return D2D1::RectF(c.left + m, c.top + m, c.right + m, c.bottom + m);
}

void InstallerWindow::LayoutStepBar() {
    const D2D1_RECT_F& list = shellLayout_.stepList;
    const float rowH = (list.bottom - list.top) / static_cast<float>(kStepCount);
    for (int i = 0; i < kStepCount; ++i) {
        const float top = list.top + rowH * static_cast<float>(i);
        stepItems_[i].SetBounds(D2D1::RectF(list.left + faf::spacing::M, top,
                                            list.right - faf::spacing::M, top + rowH));
    }
}

// UI-fix：底部按钮条统一布局——外壳导航按钮（画布坐标）+ 页托管按钮（取消/打开目录/完成，
// 页坐标 = 画布 + shadowMarginDip_）。页面自身 Layout 不再摆放这些按钮；本函数在每次页面
// Layout（Layout/EnsurePages/LayoutPages/ApplyPageEntry）之后调用，保持按钮与 shell 几何同步。
void InstallerWindow::LayoutFooterButtons() {
    const D2D1_RECT_F& bar = shellLayout_.bottomBar;
    const float cy = (bar.top + bar.bottom) * 0.5f;
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
    if (progressPage_) {
        progressPage_->CancelButton().SetBounds(D2D1::RectF(
            kFooterRightEdgeX - kCancelButtonW + m, rowTop, kFooterRightEdgeX + m, rowBottom));
    }
    if (finishPage_) {
        const float finishRight = kFooterRightEdgeX + m;
        const float finishLeft = finishRight - kFinishButtonW;
        finishPage_->FinishButton().SetBounds(
            D2D1::RectF(finishLeft, rowTop, finishRight, rowBottom));
        const float openRight = finishLeft - faf::spacing::S;
        finishPage_->OpenDirButton().SetBounds(
            D2D1::RectF(openRight - kOpenDirButtonW, rowTop, openRight, rowBottom));
    }
}

void InstallerWindow::LayoutPages() {
    if (!pagesReady_) return;
    const D2D1_RECT_F card = PageRect();
    switch (state_.page) {
        case Welcome: welcomePage_->Layout(card); break;
        case License: licensePage_->Layout(card); break;
        case Location: locationPage_->Layout(card); break;
        case Options: optionsPage_->Layout(card); break;
        case Progress: progressPage_->Layout(card); break;
        case Finish: finishPage_->Layout(card); break;
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
        case Location:
            locationPage_->SyncFromState();
            locationPage_->Layout(card);
            break;
        case Options:
            optionsPage_->SyncFromState();
            optionsPage_->Layout(card);
            break;
        case Progress:
            progressPage_->Layout(card);
            progressPage_->SetProgressPermille(progressPermille_);
            break;
        case Finish:
            finishPage_->Layout(card);
            finishPage_->StartCheckAnim();
            break;
        default:
            break;
    }
    SyncStepBar();
    UpdateNavButtons();
    // UI-fix：页面切换后重摆底部条（含页托管的取消/打开目录/完成按钮）。
    LayoutFooterButtons();
}

void InstallerWindow::SyncStepBar() {
    for (int i = 0; i < kStepCount; ++i) stepItems_[i].SetStep(i, state_.page);
}

void InstallerWindow::UpdateNavButtons() {
    if (!pagesReady_) return;
    bool canBack = false;
    bool canNext = false;
    // UI-fix：按页面决定外壳导航按钮的可见性（期间始终禁用，见下方门控）。
    switch (state_.page) {
        case Welcome:
            navBackVisible_ = false;  // 欢迎页无「上一步」
            navNextVisible_ = true;
            canNext = true;
            break;
        case License:
            navBackVisible_ = true;
            navNextVisible_ = true;
            canNext = state_.agreed;
            canBack = true;
            break;
        case Location:
            navBackVisible_ = true;
            navNextVisible_ = true;
            canNext = locationPage_ && locationPage_->CanProceed();
            canBack = true;
            break;
        case Options:
            navBackVisible_ = true;
            navNextVisible_ = true;
            canNext = true;
            canBack = true;
            break;
        case Progress:  // 安装进度页：无导航（取消按钮由页托管到底部条）
        case Finish:    // 完成页：无导航（打开目录/完成按钮由页托管到底部条）
        default:
            navBackVisible_ = false;
            navNextVisible_ = false;
            break;
    }
    if (installing_) {  // 「安装中不可返回/前进」
        canBack = false;
        canNext = false;
    }
    // UI-fix：下一步按钮文案随页面切换（安装选项页 = 「安装」）。
    nextButton_.SetLabel(state_.page == Options ? L"安装" : L"下一步");
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
            SetPage(Location);
            break;
        case Location:
            if (!locationPage_ || !locationPage_->CanProceed()) return;  // 不可写/空间不足
            SetPage(Options);
            break;
        case Options:
            if (optionsPage_) optionsPage_->SyncToState();  // 四选项写回 AppState
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
        case Location:
            SetPage(License);
            break;
        case Options:
            SetPage(Location);
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
    if (installing_) {
        DiagLog(L"esc ignored while installing");
        return;  // 「ESC 关闭（等同取消，安装中禁止）」
    }
    PostMessageW(window_, WM_CLOSE, 0, 0);
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
        case Location: return locationPage_->Host();
        case Options: return optionsPage_->Host();
        case Progress: return progressPage_->Host();
        case Finish: return finishPage_->Host();
        default: return empty;
    }
}

void InstallerWindow::RenderActivePage(ID2D1DeviceContext* ctx, const faf::Theme& theme) {
    if (!pagesReady_ || !ctx) return;
    switch (state_.page) {
        case Welcome: faf::RenderWelcome(ctx, theme, *welcomePage_); break;
        case License: faf::RenderLicense(ctx, theme, *licensePage_); break;
        case Location: faf::RenderLocation(ctx, theme, *locationPage_); break;
        case Options: faf::RenderOptions(ctx, theme, *optionsPage_); break;
        case Progress: faf::RenderProgress(ctx, theme, *progressPage_); break;
        case Finish: faf::RenderFinish(ctx, theme, *finishPage_); break;
        default: break;
    }
}

// ==================== Todo 19（§17）：/auto 无人值守测试驱动 ====================
// 仅 FAF_TESTMODE 构建有驱动行为（宏由 cmake/test_mode.cmake 在 -DFAF_TESTMODE=ON
// 时定义）。生产构建保留的只有 EnableAutoDrive 的 no-op 定义；驱动成员/定时器/
// 推进逻辑全部被预处理器剔除——/auto 开关在生产中解析后即丢弃，无任何效果。

void InstallerWindow::EnableAutoDrive(std::wstring profile, int stopPage) {
#ifdef FAF_TESTMODE
    autoDriveEnabled_ = true;
    autoProfile_ = profile;  // 空串 = 全默认档
    // 越界/负值 → 不停（走完全程）；0..5 合法则到站即停。
    autoStopPage_ = (stopPage >= Welcome && stopPage <= Finish) ? stopPage : -1;
#else
    // 生产构建保底 no-op：交互行为不受 /auto 影响（规格 §17）。
    (void)profile;
    (void)stopPage;
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
        case Location:
            // 门控 = 目录可写 + 空间足够（LocationPage::CanProceed）；默认预填即可过。
            GoNext();
            break;
        case Options:
            // GoNext → OptionsPage::SyncToState() + StartInstall()（进入进度页）。
            GoNext();
            break;
        default:
            break;
    }
}

#endif  // FAF_TESTMODE
