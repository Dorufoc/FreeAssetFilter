#pragma once
//
// pages_progress.h - 安装向导页面⑤「安装进度」与页面⑥「完成」（新增页）(Todo 11)。
//
// 独立页文件：与 Todo 9（pages_welcome）与 Todo 10（pages_setup）互不触碰。供 Todo 12
// （步骤状态机 / 导航接线）经 RenderProgress(...) / RenderFinish(...) 接入外壳。
//
// Frozen contracts：
//  - §10：进度值一律为 **permille 0..1000**（即 messages.h 的 WM_INSTALL_PROGRESS
//    wParam 语义），页面显示百分比 = `permille / 10.0`（如 500 ⇒ 50.0）。真实进度由
//    Todo 13 的安装引擎产出；本页只消费 permille，**不制造任何假进度**。
//  - §3：取消只抬高「取消意图」并切换到取消态；引擎安全停止 + 清理本次写入 +
//    写 `abort=1` 由 Todo 13 负责，本 todo 不实现（见 CancelIntent 注释）。
//  - §12：页面/选项状态读写 AppState。Finish 页「立即启动」抬高高完成意图。
//  - §15：「立即启动」的真实进程启动由 Todo 15 执行；本文件**绝不 ShellExecute**。
//  - §13：视觉只消费 theme.h 的 token；文字/字形经 text.h / glyphs.h。
//
// 追加需求（2026-10-18）：Finish 页改为英雄页（与欢迎页同构）——图标（成功对勾）+
// 软件名称 + 版本 + 大按钮「立即启动」；删除「打开安装目录」与「立即启动」勾选框。
//
// 坐标与绘制全程 DIP（§6）。控件复用 Todo 7 的 Button / CheckBox 与 Todo 8 的
// ProgressBar，不重复实现；动画经 animation.h 的 AnimValue（由宿主经 BindAnimator
// 注入，页面不自持帧时钟；未注入时退化为终值，可在无窗口 harness 中运行）。
//
#include <windows.h>

#include <d2d1_1.h>

#include <functional>
#include <string>

#include "render/animation.h"
#include "render/app_state.h"
#include "render/controls_base.h"
#include "render/controls_basic.h"
#include "render/controls_feedback.h"
#include "render/glyphs.h"
#include "render/text.h"
#include "render/theme.h"

namespace faf {

class LogoBitmap;  // render/logo.h（Finish 英雄页图标，前向声明避免额外 include）

// ============================== 纯函数辅助 =================================

// 操作类型（T8）：安装 / 修复 / 卸载。ProgressPage / FinishPage 各自以
// `using Kind = ProgressKind;` 暴露 `ProgressPage::Kind` / `FinishPage::Kind`，
// 因此调用方既可用 `ProgressPage::Kind::Repair`，也可直接使用本类型。
enum class ProgressKind { Install, Repair, Uninstall };

// permille → 步骤索引：0 初始化 / 1 复制文件 / 2 写入快捷方式 / 3 完成。
// 阈值：<250 初始化、<750 复制文件、<1000 写入快捷方式、==1000 完成。纯函数，便于断言。
// 仅描述 Install（旧契约），行为保持不变。
int ProgressStepIndex(int permille);

// 旧签名（Install，保留以兼容既有调用/测试）：
// permille → 步骤中文文案（「初始化」/「复制文件」/「写入快捷方式」/「完成」）。
std::wstring ProgressStepText(int permille);

// 新签名：按 kind 返回步骤中文文案。纯函数，便于断言。
//  - Install  ：初始化 / 复制文件 / 写入快捷方式 / 完成（与旧签名完全一致）。
//  - Repair   ：准备文件 / 复制文件 / 写入快捷方式 / 完成（与安装同构）。
//  - Uninstall：清理快捷方式 / 清理注册表 / 删除程序文件 / 清理用户数据 / 完成
//    （按 helper 的真实 stage→permille 映射；不制造字节级假进度）。
std::wstring ProgressStepText(ProgressKind kind, int permille);

// permille → 百分比文案（`permille/10.0`，保留一位小数，如 500 ⇒ L"50.0%"）。
// §10：**不做** 0..100 反推，直接以 permille 语义换算。
std::wstring ProgressPercentText(int permille);

// ============================== 页面⑤ 安装进度 =============================

// Progress 页：determinate 进度条（§10 permille）+ 步骤文字 + 实时百分比 + 「取消」。
class ProgressPage {
public:
    // T8：操作类型（Install / Repair / Uninstall）；与 ProgressKind 同型。
    using Kind = ProgressKind;

    // 取消态：Running（安装中）→ Cancelling（已抬高取消意图，等引擎安全停止）→
    // Cancelled（引擎确认已按 §3 清理完成，由 Todo 13 调用 MarkCancelled）。
    enum class State { Running, Cancelling, Cancelled };

    explicit ProgressPage(AppState& state);

    // 依赖注入（宿主构造后绑定；均可为空——为空时退化为无动画 / 无文字）。
    void BindAnimator(Animator* animator);
    void BindText(const TextFactory* text);
    void BindGlyphs(const GlyphFont* glyphs);

    // T8：按操作类型切换标题 / 步骤文案 / 默认提示 / 取消可用性。
    //  - Install：保持原有 4 段文案与「取消」按钮（视觉/行为不变）。
    //  - Repair / Uninstall：隐藏「取消」，并写入“请勿关闭窗口”默认提示。
    // 仅在 kind 实际变化时重置提示与 stage 文案，便于宿主逐帧调用。
    void SetKind(Kind kind);
    // 便捷重载：T10 可直接传 AppState.operation。
    void SetKind(Operation operation);
    Kind GetKind() const noexcept { return kind_; }

    // T8：repair/uninstall 隐藏「取消」按钮（同时移出 Tab 顺序）；Install 保持。
    void SetCancellable(bool cancellable);
    bool Cancellable() const noexcept { return cancellable_; }

    // T8：提示行。与 SetStageText 分离，避免阶段文案覆盖警告/提示。
    void SetNotice(std::wstring text);
    const std::wstring& Notice() const noexcept { return notice_; }

    // T8：当前卸载阶段中文名（T12 按 UninstallStage 传入）。设置后 StepText()
    // 优先返回它；未设置时退回 ProgressStepText(kind, permille) 纯函数映射。
    void SetStageText(std::wstring text);
    const std::wstring& StageText() const noexcept { return stageText_; }

    // 标题（正在安装/修复/卸载 FreeAssetFilter），供渲染与测试断言。
    std::wstring HeadingText() const;

    // 依内容卡片矩形（DIP）布局控件。
    void Layout(const D2D1_RECT_F& contentCard);
    void Render(ID2D1DeviceContext* dc, const Theme& theme);

    // 输入/Tab 分发宿主（Todo 12 负责事件翻译）。
    WidgetHost& Host() noexcept { return host_; }

    // §10：消费 WM_INSTALL_PROGRESS 的 wParam（permille 0..1000，越界钳制）。
    // 同步更新 ProgressBar、百分比文案与步骤文字。
    void SetProgressPermille(int permille);
    int Permille() const noexcept { return permille_; }
    float Percent() const noexcept { return static_cast<float>(permille_) / 10.0f; }
    std::wstring PercentText() const { return ProgressPercentText(permille_); }
    std::wstring StepText() const {
        return stageText_.empty() ? ProgressStepText(kind_, permille_) : stageText_;
    }

    // ---------------------------------------------------------------------
    // 取消意图（CancelIntent）—— 本 todo 的唯一职责边界：
    //   * onCancel_ 回调：宿主可设置（Todo 12/13 用它通知引擎请求安全停止）。
    //   * cancelRequested_ 标志：无回调宿主的轮询兜底。
    //   * RequestCancel() 抬高意图并把页面切到 Cancelling 视觉态。
    // ⚠️ 引擎安全停止 + §3 清理本次写入 + 写 `abort=1` INI **由 Todo 13 负责**；
    //    本页不触碰文件系统、不写 INI、不阻塞 UI 线程。
    // ---------------------------------------------------------------------
    void SetOnCancel(std::function<void()> cb) { onCancel_ = std::move(cb); }
    void RequestCancel();
    // Todo 13 引擎确认已安全停止且完成 §3 清理后调用 → 进入 Cancelled 态。
    void MarkCancelled();

    bool CancelRequested() const noexcept { return cancelRequested_; }
    State Current() const noexcept { return phase_; }

    ProgressBar& Bar() noexcept { return bar_; }
    Button& CancelButton() noexcept { return cancelButton_; }

private:
    AppState& state_;  // 借用（§12 共享状态）
    ProgressBar bar_;
    Button cancelButton_;
    WidgetHost host_;

    const TextFactory* text_ = nullptr;
    const GlyphFont* glyphs_ = nullptr;

    int permille_ = 0;
    State phase_ = State::Running;
    bool cancelRequested_ = false;
    Kind kind_ = Kind::Install;
    bool cancellable_ = true;
    std::wstring notice_;
    std::wstring stageText_;
    std::function<void()> onCancel_;

    D2D1_RECT_F card_{};
    D2D1_RECT_F headingRect_{};
    D2D1_RECT_F stepRect_{};
    D2D1_RECT_F barRect_{};
    D2D1_RECT_F percentRect_{};
    D2D1_RECT_F noticeRect_{};
};

// ============================== 页面⑥ 完成 ================================

// Finish 页（英雄页，追加需求 2026-10-18）：成功对勾描边动画（AnimValue）作为图标 +
// 软件名称 + 版本 + 标语 + 大按钮「立即启动」。无顶部步骤区、无底部导航。
// 与欢迎页**内容一致**（图标 + 名称 + 版本 + 标语 + 大按钮；仅按钮文案与图标不同）。
class FinishPage {
public:
    // T8：操作类型（Install / Repair / Uninstall）；与 ProgressKind 同型。
    using Kind = ProgressKind;

    explicit FinishPage(AppState& state);

    // 依赖注入（宿主构造后绑定；均可为空）。
    void BindAnimator(Animator* animator);
    void BindText(const TextFactory* text);
    void BindGlyphs(const GlyphFont* glyphs);
    void SetLogo(const LogoBitmap* logo) { logo_ = logo; }

    // T8：按操作类型切换完成页形态。
    //  - Install  ：原样（产品名 + 版本 + 标语 + 大按钮「立即启动」；无复选框）。
    //  - Repair   ：标题「修复完成」+ 复选框「立即启动 FreeAssetFilter」
    //               （绑定 state_.optLaunchAfterRepair，默认 false）+ 按钮「完成」。
    //  - Uninstall：标题「卸载完成」+ 按钮「关闭」；无复选框。
    void SetKind(Kind kind);
    // 便捷重载：T10 可直接传 AppState.operation。
    void SetKind(Operation operation);
    Kind GetKind() const noexcept { return kind_; }

    // 非终端提示（例如卸载完成后的清理 warning）；仅 Uninstall 页渲染，不改变终态。
    void SetNotice(std::wstring notice);

    void Layout(const D2D1_RECT_F& contentCard);
    void Render(ID2D1DeviceContext* dc, const Theme& theme);

    // 进入完成页时启动对勾描边动画（由宿主在 SetPage(Finish) 后调用；无动画器时即时终值）。
    void StartCheckAnim();
    // 0..1 对勾描边进度（未注入 Animator 时为 1——即完成态）。
    float CheckProgress() const;

    WidgetHost& Host() noexcept { return host_; }

    // ---------------------------------------------------------------------
    // 意图钩子（Intent hooks）—— 本 todo 绝不 ShellExecute / 不启动进程：
    //   * onFinishIntent_()： 「立即启动」/「完成」/「关闭」点击时抬高完成意图。
    // 实际启动/关窗由宿主读取 AppState 执行（§15 由 Todo 15 负责）。
    // ---------------------------------------------------------------------
    void SetOnFinishIntent(std::function<void()> cb) { onFinishIntent_ = std::move(cb); }

    // 抬高完成意图（不启动进程）。
    void EmitFinishIntent();

    bool FinishIntentEmitted() const noexcept { return finishIntentEmitted_; }

    Button& FinishButton() noexcept { return finishButton_; }
    CheckBox& LaunchAfterRepairBox() noexcept { return launchBox_; }
    bool LaunchAfterRepair() const noexcept { return launchBox_.Checked(); }

    const std::wstring& ProductName() const noexcept { return productName_; }
    const std::wstring& Version() const noexcept { return version_; }
    const std::wstring& Tagline() const noexcept { return tagline_; }
    // 当前标题（Install = 产品名；Repair = 修复完成；Uninstall = 卸载完成）。
    const std::wstring& Title() const noexcept { return title_; }

private:
    void RebuildHost();  // 按 kind 重建 Tab 顺序（Repair 追加复选框）

    AppState& state_;  // 借用（§12 共享状态）
    std::wstring productName_ = L"FreeAssetFilter";
    std::wstring version_;
    // 标语：与欢迎页完全一致的字符串（需求：完成页内容 = 欢迎页内容，仅按钮文案/图标不同）。
    std::wstring tagline_ = L"让文件浏览如丝般高效顺滑";
    // 标题：Install = 产品名；Repair/Uninstall = 状态文案。
    std::wstring title_ = L"FreeAssetFilter";
    // 卸载完成后的 warning（非终端提示；仅 Uninstall 页渲染）。
    std::wstring notice_;

    Kind kind_ = Kind::Install;

    Button finishButton_;
    CheckBox launchBox_;  // Repair 专用；Install/Uninstall 不渲染、不参与 Tab
    WidgetHost host_;

    const LogoBitmap* logo_ = nullptr;
    const TextFactory* text_ = nullptr;
    const GlyphFont* glyphs_ = nullptr;

    Animator* animator_ = nullptr;
    AnimValue* checkAnim_ = nullptr;
    float checkFallback_ = 1.0f;  // 无动画器 → 完成态（终值）
    std::string checkName_;

    std::function<void()> onFinishIntent_;
    bool finishIntentEmitted_ = false;

    D2D1_RECT_F card_{};
    D2D1_RECT_F checkRect_{};
    D2D1_RECT_F nameRect_{};
    D2D1_RECT_F versionRect_{};
    D2D1_RECT_F taglineRect_{};
    D2D1_RECT_F checkboxRect_{};
    D2D1_RECT_F noticeRect_{};
    D2D1_RECT_F buttonRect_{};
};

// ============================== Todo 12 接线入口 ===========================

// 页面⑤渲染入口（薄包装，供 Todo 12 调用）。
void RenderProgress(ID2D1DeviceContext* dc, const Theme& theme, ProgressPage& page);

// 页面⑥渲染入口（薄包装，供 Todo 12 调用）。
void RenderFinish(ID2D1DeviceContext* dc, const Theme& theme, FinishPage& page);

}  // namespace faf
