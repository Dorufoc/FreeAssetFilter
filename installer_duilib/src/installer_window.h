#pragma once
//
// installer_window.h - 无边框 DirectComposition 安装器窗口外壳（Todo 2）。
//
// 窗口类名冻结为 "SopeekInstaller"（§4），NSIS 的 FindWindow 与取证脚本
// 均按此名定位，重写时不得改名。
//
// 窗口配方（§4，Todo 2 实测选定）：WS_OVERLAPPEDWINDOW & ~WS_MAXIMIZEBOX
// + WS_EX_NOREDIRECTIONBITMAP + 自绘非客户区（WM_NCCALCSIZE wParam=TRUE 返回 0）
// + DComp 合成 + DWMWA_WINDOW_CORNER_PREFERENCE=DWMWCP_ROUND。固定 900x600 DIP，
// 由 WM_GETMINMAXINFO 钳制 + 移除 WS_MAXIMIZEBOX + 吞掉双击/SC_MAXIMIZE/SC_SIZE。
//
#include <windows.h>

#include <array>
#include <atomic>
#include <cstdint>
#include <memory>
#include <mutex>
#include <string>

#include "maintenance_detector.h"  // T10：maintenanceInfo_（T2 只读探测结果）
#include "render/animation.h"      // §16：帧时钟 / 缓动 / 可动画值 / 可观测性
#include "render/app_state.h"
#include "render/controls_base.h"      // §13/Todo 3：Widget / WidgetHost / InputEvent
#include "render/controls_basic.h"     // Todo 7：Button（底部导航按钮）
#include "render/controls_feedback.h"  // Todo 8：StepItem（左栏步骤栏）
#include "render/glyphs.h"             // Todo 3：GlyphFont
#include "render/install_engine.h"     // T11：InstallMode（StartInstall 的模式参数）
#include "render/layout.h"  // §6：shell 矩形几何唯一来源（纯 DIP）
#include "render/logo.h"    // Todo 3：LogoBitmap（欢迎页）
#include "render/render_context.h"
#include "render/text.h"    // Todo 3：TextFactory
#include "render/theme.h"  // §5/§13：唯一 token 表（LightTheme/DarkTheme/GetTheme）

// Todo 9/10/11 的页文件只在此前向声明；完整头仅在 installer_window.cpp 中包含
// （页面对象以 std::unique_ptr 持有，析构在 cpp 内完成——见 Todo 12 接线）。
// T10：维护 / 卸载确认 / 通用消息页同样只前向声明；T12 的卸载协调器仅以
// std::shared_ptr 持有时无需完整类型（析构器类型擦除），实现由 T12 提供。
namespace spk {
class WelcomePage;
class LicensePage;
class ConfigurePage;
class ProgressPage;
class FinishPage;
class MaintenancePage;
class UninstallConfirmPage;
class MessagePage;
class UninstallCoordinator;  // T12：卸载协调器（前向声明，T10 只保留接缝）
}  // namespace spk

class InstallerWindow {
public:
    // `installDir`：§15 重装预填（/installdir，由 NSIS 生产 Exec 行传入；空 ⇒ 默认
    // `C:\Program Files\Sopeek`）。owner 次序：Todo 2 → 15 → 19（§13）。
    // T10：`mode`/`decisionPath`/`setupPid`/`payloadTimeoutMs` 为维护/卸载模式入口；
    // T12：`helperPid`/`uninstallRequestPath`/`uninstallResultPath` 为卸载模式入口
    // （helper 先启动时传 /helper-pid；路径为空时按 installDir 推导）。
    // 末尾全部带缺省值，保证既有 main.cpp（4 参数）继续编译。T14 负责 CLI 解析传参。
    InstallerWindow(HINSTANCE instance, std::wstring payload, std::wstring resultPath,
                    std::wstring installDir = {}, AppMode mode = AppMode::Install,
                    std::wstring decisionPath = {}, DWORD setupPid = 0,
                    std::uint64_t payloadTimeoutMs = 0, DWORD helperPid = 0,
                    std::wstring uninstallRequestPath = {},
                    std::wstring uninstallResultPath = {});
    ~InstallerWindow();

    InstallerWindow(const InstallerWindow&) = delete;
    InstallerWindow& operator=(const InstallerWindow&) = delete;

    int Run();

    // T14/D12：提权前/helper 身份校验失败时必须显示可见错误页，而不是 MessageBox。
    // 必须在 Run() 之前调用；窗口就绪后会直接进入 Message 页并跳过对应模式的
    // 初始化流程，关闭时只销毁窗口（不写 decision/request/result/注册表）。
    void SetStartupError(std::wstring title, std::wstring body);

    // --- Todo 19（§17）/T14：/auto 无人值守测试驱动入口（仅 SPK_TESTMODE 有行为）---
    // 由 main.cpp 在 SPK_TESTMODE 构建中调用（生产构建解析 /auto 后直接丢弃、
    // 不会调用此处；即便调用亦为 no-op，交互行为保持不变）。
    // 驱动时序：窗口/页面就绪后固定间隔自动 欢迎→许可→配置→部署→完成
    //（或停在第 stopPage 页），全程只经既有 GoNext/SetPage 路径。
    struct AutoDriveOptions {
        // `/auto:opts=` 的原始四位 0/1 串（空/缺位 ⇒ §2 默认 1,1,0,1）。
        std::wstring profile;
        // `/auto:page=N`（0..7 = Welcome..Message；越界/缺省 = 不停，走完）。
        int stopPage = -1;
        // `/auto:mode=maintenance|uninstall`（仅测试驱动提示；实际模式仍由
        // `/maintenance` / `/uninstall` 决定）。
        AppMode mode = AppMode::Install;
        // `/auto:action=repair|uninstall|cancel`（Maintenance/UninstallConfirm/
        // Message 页的自动推进动作；空 = 未指定）。
        std::wstring action;
        // `/auto:delete-user-data=0|1`（空 = 未指定；仅 UninstallConfirm 消费）。
        std::wstring deleteUserData;
    };
    void EnableAutoDrive(AutoDriveOptions options);

private:
    static LRESULT CALLBACK WindowProc(HWND, UINT, WPARAM, LPARAM);
    LRESULT HandleMessage(UINT, WPARAM, LPARAM);

    // --- window shell ---
    bool CreateAppWindow();
    void InstallDwmEffects();      // 圆角 / Mica backdrop（build<22621 关闭）/ 深色模式 / 帧扩展（候选）
    void ApplyDarkMode(bool dark); // §5：重设 DWMWA_USE_IMMERSIVE_DARK_MODE + 置脏
    void RefreshSystemTheme();     // §5 实时切换：重读注册表 → 应用 → 重绘
    // T13：标题唯一同步点——windowTitle_ 是自绘标题栏文字，SetWindowTextW 同步
    // 原生窗口标题（任务栏/Alt+Tab）。构造期与窗口创建后各调用一次。
    void UpdateWindowTitle();
    void Layout();                 // 刷新 shell 几何（唯一来源 = spk::ComputeShellLayout，纯 DIP）
    void OnSizeChanged(UINT widthPx, UINT heightPx);
    void OnDpiChanged(UINT newDpi, const RECT* suggested);

    // --- rendering (placeholder shell; 页面/布局归后续 todo) ---
    void Render();
    void Tick();
    void DrawContent(ID2D1DeviceContext* ctx);
    void DrawMicaFallbackBase(ID2D1DeviceContext* ctx, const spk::Theme& theme,
                              float alpha);                                  // §5 Win10 不透明渐变底
    void DrawShellLayers(ID2D1DeviceContext* ctx, const spk::Theme& theme,
                         float alpha);                                       // §5 左栏/内容卡/底部条
    void DrawTitleBar(ID2D1DeviceContext* ctx, const spk::Theme& theme, float alpha);

    // --- 自绘标题栏窗口按钮（最小化/关闭）悬停与按下状态机 ---
    // 按下不立即激活：仅当「同一按钮上按下并在其上松开」才执行动作；移出后松开即取消
    //（Win32 push-button 语义）。悬停命中区来自 ShellLayout（纯 DIP）。
    enum class WindowButton { None, Minimize, Close };
    WindowButton HitTestWindowButton(float dipX, float dipY) const;  // DIP 点 → 命中的窗口按钮
    void UpdateTitleBarHover(float dipX, float dipY);                // WM_MOUSEMOVE：刷新悬停并重绘
    void PerformWindowButtonAction(WindowButton button);             // 在同一按钮上松开 → 最小化/关闭

    // --- animation tick wiring（本 todo 唯一拥有：§16 + WM_TIMER 接线）---
    // 「WM_TIMER(~16ms) → 推进所有活动动画 → 若 dirty 或动画中则 PresentFrame → Commit」。
    void RequestAnimTick();  // 置脏 + 确保 tick 定时器在跑（闲置 KillTimer 后的重新武装路径）
    void EnsureTickTimer();  // tick 定时器未跑则 SetTimer（~16ms）
    void KillTickTimer();    // 停表（无动画且无 dirty 时调用）
    void ApplyReduceMotion();  // 读 SPI_GETCLIENTAREAANIMATION → animator_.SetReduceMotion
    // UI-fix：新增可选 weight 形参（品牌头产品名需要 SemiBold；缺省 Regular 行为不变）。
    void DrawTextLine(ID2D1DeviceContext* ctx, const std::wstring& text, float x, float y,
                      float width, float height, float sizeDip, const D2D1_COLOR_F& color,
                      DWRITE_FONT_WEIGHT weight = DWRITE_FONT_WEIGHT_NORMAL);

    // --- input helpers (DIP) ---
    void ClientPointToDip(POINT p, float* dx, float* dy) const;
    int MarginPx() const;

    // --- page state machine wiring（Todo 12：把 9/10/11 页文件接入外壳）---
    // 页面唯一来源 = AppState::page（§12）；本组方法只做接线，不改页内部实现。
    void EnsurePages();      // render 就绪后惰性构造/绑定 5 页 + 步骤区 + 导航按钮
    void ApplyPageEntry();   // 进入/切换页面：入场动效 + SyncFromState + Layout + 步骤栏/按钮刷新
    void LayoutPages();      // 仅按当前 shell 几何重排当前页（不含入场重置）
    void SyncStepBar();      // 把 state_.page 推入 StepItem 状态（映射到 3 节点）
    void UpdateNavButtons(); // 依页面/安装态/门控启用或禁用 上一步/下一步
    void GoNext();           // 下一步（安装中无效；Configure→Progress 触发安装）
    void GoBack();           // 上一步（安装中无效；Welcome/Finish/Progress 无效）
    void RaiseCancelIntent();// 抬高取消意图（Progress 页 RequestCancel）；不写结果文件
    // T13：ESC 与 WM_CLOSE 完全同义——安装中由 WM_CLOSE 置 closePending_ 并取消，
    // Repair/Uninstall Progress 则由各自 CloseIntent 忽略；此处不再提前拦截。
    void OnEscape();
    D2D1_RECT_F PageRect() const;  // 页内容矩形 = contentCard + Win10 兜底外扩边距
    spk::WidgetHost& ActivePageHost();  // 当前页的输入/Tab 宿主
    void RenderActivePage(ID2D1DeviceContext* ctx, const spk::Theme& theme);
    bool DispatchPointer(const spk::InputEvent& event);  // 外壳导航按钮 + 当前页分发
    void LayoutStepBar();
    // UI-fix：总布局页脚——外壳导航按钮（画布坐标）+ 页托管按钮（取消/打开目录/完成，
    // 页坐标 = 画布 + shadowMarginDip_）。每次页面 Layout 之后必须调用。
    void LayoutFooterButtons();

    // --- install engine（Todo 13：真实引擎 = render/install_engine.h） ---
    void SetPage(int page);
    // T11：安装/修复共用同一引擎启动路径。缺省 Fresh 保持安装 0..4 的既有行为；
    // 维护修复传 InstallMode::Repair（失败/取消不回滚，由 T6 引擎语义保证）。
    void StartInstall(spk::InstallMode mode = spk::InstallMode::Fresh);
    // UI-fix（进度 UX）：安装/修复初始化阶段的 UI 侧合成进度斜坡。引擎等待
    // payload.ready 与递归预扫描期间没有进度回调，故由窗口在 0..500 间匀速推进；
    // 首个真实 permille>0 到达即停止，并按当前值作为 base 映射后续真实进度。
    // 仅 UI 状态，不改变引擎 permille 契约，也不伪造安装成功。
    void BeginInitProgress();
    void AdvanceInitProgress(double now_ms);
    void EndInitProgress(int raw_permille);
    // UI-fix：成功收尾时先在 100% 停留一个短定时器（让 220ms 填充动画可见），
    // 再由 WM_TIMER(id=3) 切到完成页；避免 SetPage(Finish) 抢在绘制之前。
    void BeginCompletionHold();
    // §15（唯一 owner = Todo 15）：完成页「完成」意图 —— 仅当 `state_.optLaunch`
    // 为真时经 `render/launch_forward.h` 去提权启动；未勾选绝不启动。目标缺失/
    // 转发失败 ⇒ 窗口内提示且不关闭（不崩溃）。
    void OnFinishIntent();
    static DWORD WINAPI InstallThreadProc(LPVOID);
    void InstallThread();
    void WriteCancelResult();  // 保留名（Todo 15 兼容）；内部统一走 §1 唯一写入器
    void WriteAbortResult(const std::wstring& error);  // §1：abort=1 + error 写入包装

    // --- T10/T11：维护/卸载模式接线 ---
    // 维护/修复入口与流程由 T11 实现；卸载（T12）与通用消息/关闭架构（T13）仍是接缝。
    void OnMaintenanceRepairIntent();
    void OnMaintenanceUninstallIntent();
    void OnMaintenanceCancelIntent();
    void OnUninstallConfirmIntent();
    void OnUninstallCancelIntent();
    void OnMessagePrimaryIntent();
    void OnMessageSecondaryIntent();
    // 跨线程消息分发。
    void OnCloseDoneMessage(WPARAM wp);
    void OnUninstallProgressMessage(WPARAM wp, LPARAM lp);
    void OnUninstallDoneMessage(WPARAM wp, LPARAM lp);
    // WM_CLOSE / ESC 的模式分支（T11 填维护/修复决策写入；T12 仍待实现）。
    void OnMaintenanceCloseIntent();
    void OnUninstallCloseIntent();

    // --- T11：维护 / 修复流程 ---
    // Message 页按钮语义。T11 只覆盖维护/修复所需分支，T13 的通用消息/关闭架构不在此实现。
    enum class MessageAction {
        None,               // 无动作（按钮隐藏或无效）
        Close,              // 走统一 WM_CLOSE 路径（维护模式尚未写决策时补 cancel）
        CloseNoDecision,    // 明确禁止写 decision（未检测到安装 / 修复预检失败）
        CancelMaintenance,  // 写 maintenance cancel（一次性守卫）后关窗
        RetryRepair,        // 重新执行 StartRepair（关闭已安装应用失败后的重试）
        RetryUninstall,     // 重新执行卸载确认检查（关闭已安装应用失败后的重试）
    };
    // 进入维护模式：Detect + MaintenancePage::SetInfo + 页 5；未检测到安装 → Message。
    void EnterMaintenanceMode();
    // 修复意图：预检 →（已安装应用运行中则异步关闭）→ 写 decision → Progress + 引擎。
    void StartRepair();
    // T12：卸载意图（维护模式先 decision+ack；/uninstall 只写 request 并按 helperPid
    // 决定是否启动 helper）→ Progress + 协调器。
    void StartUninstall();
    // decision 写成功之后的 Progress 页 + repair 引擎启动（关闭应用成功/未运行时共用）。
    void BeginRepairInstall();
    bool RepairPreflight(std::wstring* error) const;
    // action 是终端键，同一进程只允许写一次（防 WM_CLOSE/ESC 二次覆盖）。
    bool WriteMaintenanceDecisionOnce(MaintenanceAction action);
    // T11 的消息页封装：内容 + 按钮语义一起设置后再切页（避免首帧旧内容）。
    void ShowMessagePage(std::wstring title, std::wstring body, std::wstring primaryLabel,
                         MessageAction primary, std::wstring secondaryLabel,
                         MessageAction secondary);
    // T13：统一错误页入口（Message 页薄封装）。默认主/次按钮都走统一 WM_CLOSE
    // 路径：维护模式按 T11/T12 的 suppress/terminal 规则决定是否补 cancel，
    // /uninstall 模式直接退出，Install 模式保持既有 resultWritten_ 守卫。
    void ShowError(std::wstring title, std::wstring body, std::wstring primaryLabel,
                   std::wstring secondaryLabel);
    // T13：需要保留 T11/T12「重试/取消」语义的关闭失败路径使用带 action 的重载；
    // 其余错误页一律使用上面的 4 参数版本。
    void ShowError(std::wstring title, std::wstring body, std::wstring primaryLabel,
                   MessageAction primary, std::wstring secondaryLabel,
                   MessageAction secondary);
    void HandleMessageAction(MessageAction action);
    static DWORD WINAPI CloseThreadProc(LPVOID);
    void CloseAppThread();     // 工作线程：spk::CloseInstalledApp（完整路径匹配）
    void FinishCloseThread();  // 等待并关闭关闭线程句柄（析构/完成时，防悬空 this）
    // T13：异常销毁路径下安装 worker 可能仍存活；取消并显式 join，避免 this 释放后
    // 继续被 worker 访问（正常流程 WM_INSTALL_DONE 已先关闭句柄）。
    void FinishInstallThread();
    void CheckSetupWatchdog(); // setup 提前退出 → setupExited / cancel / installTimedOut

    HINSTANCE instance_{};
    HWND window_{};
    std::wstring payload_;
    std::wstring resultPath_;
    std::wstring errorText_;

    // --- T10：模式 / 跨进程生命周期状态（T11-T13 消费）---
    AppMode mode_{AppMode::Install};      // 启动模式（标题栏与关闭语义分流）
    std::wstring decisionPath_;           // maintenance-decision.ini（D3）
    DWORD helperPid_{0};                  // T12：/helper-pid（非 0 = helper 已启动 UI）
    std::wstring uninstallRequestPath_;   // T12：uninstall-request.ini
    std::wstring uninstallResultPath_;    // T12：uninstall-result.ini
    HANDLE setupProcess_{};               // T11：setup 退出 watchdog（OpenProcess(SYNCHRONIZE)）
    DWORD setupPid_{0};                   // T10：保存 setup 进程 PID，T11 据此打开 setupProcess_
    std::uint64_t payloadTimeoutMs_{0};   // T6：引擎 payload 哨兵超时（0 = 环境/内置默认）
    spk::MaintenanceInfo maintenanceInfo_{};  // T11：Detect() 结果
    HANDLE closeThread_{};                // T11/T12：关闭已安装应用的工作线程
    std::shared_ptr<spk::UninstallCoordinator> uninstallCoordinator_;  // T12 注入
    std::wstring windowTitle_;            // 按 mode 设置的自绘标题栏文字
    // T14：启动期致命错误（helper 非管理员 / 原用户身份不一致 / 缺 /decision）。
    // 非空时 EnsurePages 在模式初始化之前显示 Message 页；WM_CLOSE 直接销毁，
    // 不写任何协议 INI，Run() 以 exitCode_=1 返回。
    std::wstring startupErrorTitle_;
    std::wstring startupErrorBody_;
    int exitCode_{0};

    // --- T11：维护/修复状态（除标注外均由 UI 线程独占）---
    bool maintenanceDecisionWritten_{false};   // action 终端键已写 → 禁止二次覆盖
    bool maintenanceSuppressDecision_{false};  // 未检测到安装/预检失败：连 cancel 也不写
    bool closingApp_{false};                   // 关闭已安装应用的工作线程进行中
    bool pendingUninstallClose_{false};        // T12：本次关闭是卸载前置（用于区分 T11 修复）
    bool uninstallRunning_{false};             // T12：协调器已启动、等待 done=1（独立于 installing_）
    bool uninstallTerminal_{false};            // T12：已收到 WM_UNINSTALL_DONE，忽略后续陈旧消息
    bool keepTickAlive_{false};                // 修复/安装期间保持 tick（setup 退出 watchdog）
    spk::InstallMode installMode_{spk::InstallMode::Fresh};  // 本次引擎运行模式（worker 只读）
    std::wstring closeTargetDir_;              // 关闭线程用的安装目录快照（不跨线程读 state_）
    std::mutex closeMutex_;                    // 保护 closeError_/closeForced_（worker 写 / UI 读）
    std::wstring closeError_;
    bool closeForced_{false};
    MessageAction messagePrimaryAction_{MessageAction::None};
    MessageAction messageSecondaryAction_{MessageAction::None};

    spk::RenderContext render_;
    AppState state_{};
    bool renderReady_{false};
    bool dirty_{true};
    bool installing_{false};
    bool darkMode_{false};

    // window metrics / recipe decision
    UINT dpi_{96};
    int shadowMarginDip_{0};   // Win10 兜底时的透明外扩边距（Win11 为 0）
    bool cornerOk_{false};
    bool backdropOk_{false};
    bool backdropBuildOk_{false};  // OS build >= 22621（DWMWA_SYSTEMBACKDROP_TYPE 可尝试）
    bool extendOk_{false};
    bool win10Fallback_{false};

    spk::ShellLayout shellLayout_{};  // §6：900x600 DIP shell 几何（唯一来源 = layout.h）

    // --- 自绘标题栏窗口按钮（最小化/关闭）状态 ---
    WindowButton hoverButton_{WindowButton::None};  // 当前光标悬停的窗口按钮（驱动填充）
    WindowButton armedButton_{WindowButton::None};  // 已按下并 SetCapture 的按钮（松开命中才激活）
    bool trackingLeave_{false};                     // TrackMouseEvent(TME_LEAVE) 是否已注册

    UINT_PTR tickTimer_{0};
    HANDLE installThread_{};
    int progressPermille_{0};

    // UI-fix（进度 UX）：初始化合成斜坡 / 真实进度映射 / 完成前停留状态（UI 线程独占）。
    bool initProgressActive_{false};        // 斜坡进行中（首个真实进度前）
    bool progressMappingActive_{false};     // 后续真实 permille 走 base 映射
    int progressMappingBasePermille_{0};    // 映射 base = 斜坡结束时的当前进度
    double initProgressStartMs_{0.0};       // 斜坡起点（spk::SteadyNowMs 口径）
    double lastInitProgressUpdateMs_{0.0};  // ~80ms 节流
    bool completionHold_{false};            // 100% 停留中（等待完成页切换定时器）

    // --- Todo 13：安装引擎接线状态（worker 写 / UI 读；跨线程一律 atomic 或 mutex）---
    std::atomic<bool> cancel_{false};            // §3：取消信号（哨兵等待与复制循环轮询）
    std::atomic<bool> resultWritten_{false};     // §1：结果 INI 已写守卫（防重复写）
    std::atomic<bool> installCancelled_{false};  // WM_INSTALL_DONE 分流：取消 → 关闭窗口
    std::atomic<bool> installTimedOut_{false};   // WM_INSTALL_DONE 分流：超时 → 关闭窗口
    bool closePending_{false};                   // 安装中收到关闭 → 延迟到 WM_INSTALL_DONE 销毁
    ULONGLONG lastProgressPostTick_{0};          // §10：~30fps 节流（终值 1000 恒发，不丢）
    std::mutex errorMutex_;                      // 保护 installError_（worker 写 / UI 读）
    std::wstring installError_;                  // 引擎失败原因（error= 原样回显）

    // §16 动画：帧时钟 + 可动画值 + 采样日志 sink（生产接 DiagLog）。
    spk::Animator animator_;
    spk::AnimValue* introAnim_{nullptr};  // 外壳入场动画（0→1，减少动画时不创建）
    float introAlpha_{1.0f};              // 入场进度 → shell 层全局不透明度
    bool reduceMotion_{false};            // SPI_GETCLIENTAREAANIMATION 关闭动画时为 true

    // --- Todo 12：页面对象 + 左栏步骤栏 + 底部导航按钮 ---
    // 依赖注入对象须先于页面声明/构造（页面借用其地址），销毁序相反 → 页面先析构。
    spk::TextFactory textFactory_;
    spk::GlyphFont glyphFont_;
    spk::LogoBitmap logoBitmap_;
    bool pagesReady_{false};

    std::unique_ptr<spk::WelcomePage> welcomePage_;
    std::unique_ptr<spk::LicensePage> licensePage_;
    std::unique_ptr<spk::ConfigurePage> configurePage_;  // 追加需求：Location+Options 合并为 Configure
    std::unique_ptr<spk::ProgressPage> progressPage_;
    std::unique_ptr<spk::FinishPage> finishPage_;
    // T10：维护 / 卸载确认 / 通用消息页（T7 实现；均为英雄页）。
    std::unique_ptr<spk::MaintenancePage> maintenancePage_;
    std::unique_ptr<spk::UninstallConfirmPage> uninstallConfirmPage_;
    std::unique_ptr<spk::MessagePage> messagePage_;

    spk::Button backButton_;
    spk::Button nextButton_;
    // UI-fix：按页面控制导航按钮可见性（Welcome 隐藏「上一步」；Progress/Finish 全隐藏），
    // 由 UpdateNavButtons() 随页面切换更新、DrawContent() 据此跳过绘制。
    bool navBackVisible_{false};
    bool navNextVisible_{false};
    spk::WidgetHost shellHost_;
    std::array<spk::StepItem, 3> stepItems_{};  // 追加需求：3 节点【协议】【配置】【部署】

    // --- Todo 19：/auto 测试驱动内部状态（仅 SPK_TESTMODE 构建编入；生产零残留）---
#ifdef SPK_TESTMODE
    void ArmAutoDrive();                              // 窗口就绪后：应用档位 + 武装定时器
    void AutoDriveTick();                             // 固定时序推进一页（WM_TIMER 分发）
    void StopAutoDrive();                             // 停表（到站/走完/销毁时）
    void ApplyAutoProfile(const std::wstring& bits);  // §17 四位 → AppState 四选项

    bool autoDriveEnabled_{false};
    int autoStopPage_{-1};           // -1 = 不停；0..7 = 抵达该页后停
    std::wstring autoProfile_;       // /auto:opts= 原始串（空 = 全默认）
    // T14：/auto:mode= / /auto:action= / /auto:delete-user-data=（仅测试构建存储）。
    AppMode autoMode_{AppMode::Install};
    std::wstring autoAction_;
    std::wstring autoDeleteUserData_;
    UINT_PTR autoTimer_{0};          // 驱动专用定时器（与动画 tick 定时器独立）
    bool autoHalted_{false};         // 到站/完成后不再推进（防重复标记）
#endif
};
