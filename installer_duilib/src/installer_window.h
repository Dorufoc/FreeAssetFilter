#pragma once
//
// installer_window.h - 无边框 DirectComposition 安装器窗口外壳（Todo 2）。
//
// 窗口类名冻结为 "FreeAssetFilterInstaller"（§4），NSIS 的 FindWindow 与取证脚本
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
#include <memory>
#include <mutex>
#include <string>

#include "render/animation.h"  // §16：帧时钟 / 缓动 / 可动画值 / 可观测性
#include "render/app_state.h"
#include "render/controls_base.h"      // §13/Todo 3：Widget / WidgetHost / InputEvent
#include "render/controls_basic.h"     // Todo 7：Button（底部导航按钮）
#include "render/controls_feedback.h"  // Todo 8：StepItem（左栏步骤栏）
#include "render/glyphs.h"             // Todo 3：GlyphFont
#include "render/layout.h"  // §6：shell 矩形几何唯一来源（纯 DIP）
#include "render/logo.h"    // Todo 3：LogoBitmap（欢迎页）
#include "render/render_context.h"
#include "render/text.h"    // Todo 3：TextFactory
#include "render/theme.h"  // §5/§13：唯一 token 表（LightTheme/DarkTheme/GetTheme）

// Todo 9/10/11 的页文件只在此前向声明；完整头仅在 installer_window.cpp 中包含
// （页面对象以 std::unique_ptr 持有，析构在 cpp 内完成——见 Todo 12 接线）。
namespace faf {
class WelcomePage;
class LicensePage;
class ConfigurePage;
class ProgressPage;
class FinishPage;
}  // namespace faf

class InstallerWindow {
public:
    // `installDir`：§15 重装预填（/installdir，由 NSIS 生产 Exec 行传入；空 ⇒ 默认
    // `C:\Program Files\FreeAssetFilter`）。owner 次序：Todo 2 → 15 → 19（§13）。
    InstallerWindow(HINSTANCE instance, std::wstring payload, std::wstring resultPath,
                    std::wstring installDir = {});
    ~InstallerWindow();

    InstallerWindow(const InstallerWindow&) = delete;
    InstallerWindow& operator=(const InstallerWindow&) = delete;

    int Run();

    // --- Todo 19（§17）：/auto 无人值守测试驱动入口（仅 FAF_TESTMODE 构建有行为）---
    // 由 main.cpp 在 FAF_TESTMODE 构建中调用（生产构建解析 /auto 后直接丢弃、
    // 不会调用此处；即便调用亦为 no-op，交互行为保持不变）。
    // `profile`：`/auto:opts=` 的原始四位 0/1 串（空/缺位 ⇒ §2 默认 1,1,0,1）。
    // `stopPage`：`/auto:page=N`（0..4，停在该页不再前进；越界/缺省 = 不停，走完）。
    // 驱动时序：窗口/页面就绪后固定间隔自动 欢迎→许可→配置→部署→完成
    //（或停在第 stopPage 页），全程只经既有 GoNext/SetPage 路径。
    void EnableAutoDrive(std::wstring profile, int stopPage);

private:
    static LRESULT CALLBACK WindowProc(HWND, UINT, WPARAM, LPARAM);
    LRESULT HandleMessage(UINT, WPARAM, LPARAM);

    // --- window shell ---
    bool CreateAppWindow();
    void InstallDwmEffects();      // 圆角 / Mica backdrop（build<22621 关闭）/ 深色模式 / 帧扩展（候选）
    void ApplyDarkMode(bool dark); // §5：重设 DWMWA_USE_IMMERSIVE_DARK_MODE + 置脏
    void RefreshSystemTheme();     // §5 实时切换：重读注册表 → 应用 → 重绘
    void Layout();                 // 刷新 shell 几何（唯一来源 = faf::ComputeShellLayout，纯 DIP）
    void OnSizeChanged(UINT widthPx, UINT heightPx);
    void OnDpiChanged(UINT newDpi, const RECT* suggested);

    // --- rendering (placeholder shell; 页面/布局归后续 todo) ---
    void Render();
    void Tick();
    void DrawContent(ID2D1DeviceContext* ctx);
    void DrawMicaFallbackBase(ID2D1DeviceContext* ctx, const faf::Theme& theme,
                              float alpha);                                  // §5 Win10 不透明渐变底
    void DrawShellLayers(ID2D1DeviceContext* ctx, const faf::Theme& theme,
                         float alpha);                                       // §5 左栏/内容卡/底部条
    void DrawTitleBar(ID2D1DeviceContext* ctx, const faf::Theme& theme, float alpha);

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
    void OnEscape();         // ESC：非安装中 = WM_CLOSE；安装中 no-op（「安装中禁止」）
    D2D1_RECT_F PageRect() const;  // 页内容矩形 = contentCard + Win10 兜底外扩边距
    faf::WidgetHost& ActivePageHost();  // 当前页的输入/Tab 宿主
    void RenderActivePage(ID2D1DeviceContext* ctx, const faf::Theme& theme);
    bool DispatchPointer(const faf::InputEvent& event);  // 外壳导航按钮 + 当前页分发
    void LayoutStepBar();
    // UI-fix：总布局页脚——外壳导航按钮（画布坐标）+ 页托管按钮（取消/打开目录/完成，
    // 页坐标 = 画布 + shadowMarginDip_）。每次页面 Layout 之后必须调用。
    void LayoutFooterButtons();

    // --- install engine（Todo 13：真实引擎 = render/install_engine.h） ---
    void SetPage(int page);
    void StartInstall();
    // §15（唯一 owner = Todo 15）：完成页「完成」意图 —— 仅当 `state_.optLaunch`
    // 为真时经 `render/launch_forward.h` 去提权启动；未勾选绝不启动。目标缺失/
    // 转发失败 ⇒ 窗口内提示且不关闭（不崩溃）。
    void OnFinishIntent();
    static DWORD WINAPI InstallThreadProc(LPVOID);
    void InstallThread();
    void WriteCancelResult();  // 保留名（Todo 15 兼容）；内部统一走 §1 唯一写入器
    void WriteAbortResult(const std::wstring& error);  // §1：abort=1 + error 写入包装

    HINSTANCE instance_{};
    HWND window_{};
    std::wstring payload_;
    std::wstring resultPath_;
    std::wstring errorText_;

    faf::RenderContext render_;
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

    faf::ShellLayout shellLayout_{};  // §6：900x600 DIP shell 几何（唯一来源 = layout.h）

    UINT_PTR tickTimer_{0};
    HANDLE installThread_{};
    int progressPermille_{0};

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
    faf::Animator animator_;
    faf::AnimValue* introAnim_{nullptr};  // 外壳入场动画（0→1，减少动画时不创建）
    float introAlpha_{1.0f};              // 入场进度 → shell 层全局不透明度
    bool reduceMotion_{false};            // SPI_GETCLIENTAREAANIMATION 关闭动画时为 true

    // --- Todo 12：页面对象 + 左栏步骤栏 + 底部导航按钮 ---
    // 依赖注入对象须先于页面声明/构造（页面借用其地址），销毁序相反 → 页面先析构。
    faf::TextFactory textFactory_;
    faf::GlyphFont glyphFont_;
    faf::LogoBitmap logoBitmap_;
    bool pagesReady_{false};

    std::unique_ptr<faf::WelcomePage> welcomePage_;
    std::unique_ptr<faf::LicensePage> licensePage_;
    std::unique_ptr<faf::ConfigurePage> configurePage_;  // 追加需求：Location+Options 合并为 Configure
    std::unique_ptr<faf::ProgressPage> progressPage_;
    std::unique_ptr<faf::FinishPage> finishPage_;

    faf::Button backButton_;
    faf::Button nextButton_;
    // UI-fix：按页面控制导航按钮可见性（Welcome 隐藏「上一步」；Progress/Finish 全隐藏），
    // 由 UpdateNavButtons() 随页面切换更新、DrawContent() 据此跳过绘制。
    bool navBackVisible_{false};
    bool navNextVisible_{false};
    faf::WidgetHost shellHost_;
    std::array<faf::StepItem, 3> stepItems_{};  // 追加需求：3 节点【协议】【配置】【部署】

    // --- Todo 19：/auto 测试驱动内部状态（仅 FAF_TESTMODE 构建编入；生产零残留）---
#ifdef FAF_TESTMODE
    void ArmAutoDrive();                              // 窗口就绪后：应用档位 + 武装定时器
    void AutoDriveTick();                             // 固定时序推进一页（WM_TIMER 分发）
    void StopAutoDrive();                             // 停表（到站/走完/销毁时）
    void ApplyAutoProfile(const std::wstring& bits);  // §17 四位 → AppState 四选项

    bool autoDriveEnabled_{false};
    int autoStopPage_{-1};           // -1 = 不停；0..4 = 抵达该页后停
    std::wstring autoProfile_;       // /auto:opts= 原始串（空 = 全默认）
    UINT_PTR autoTimer_{0};          // 驱动专用定时器（与动画 tick 定时器独立）
    bool autoHalted_{false};         // 到站/完成后不再推进（防重复标记）
#endif
};
