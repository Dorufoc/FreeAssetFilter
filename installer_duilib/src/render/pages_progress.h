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

// permille → 步骤索引：0 初始化 / 1 复制文件 / 2 写入快捷方式 / 3 完成。
// 阈值：<250 初始化、<750 复制文件、<1000 写入快捷方式、==1000 完成。纯函数，便于断言。
int ProgressStepIndex(int permille);

// permille → 步骤中文文案（「初始化」/「复制文件」/「写入快捷方式」/「完成」）。
std::wstring ProgressStepText(int permille);

// permille → 百分比文案（`permille/10.0`，保留一位小数，如 500 ⇒ L"50.0%"）。
// §10：**不做** 0..100 反推，直接以 permille 语义换算。
std::wstring ProgressPercentText(int permille);

// ============================== 页面⑤ 安装进度 =============================

// Progress 页：determinate 进度条（§10 permille）+ 步骤文字 + 实时百分比 + 「取消」。
class ProgressPage {
public:
    // 取消态：Running（安装中）→ Cancelling（已抬高取消意图，等引擎安全停止）→
    // Cancelled（引擎确认已按 §3 清理完成，由 Todo 13 调用 MarkCancelled）。
    enum class State { Running, Cancelling, Cancelled };

    explicit ProgressPage(AppState& state);

    // 依赖注入（宿主构造后绑定；均可为空——为空时退化为无动画 / 无文字）。
    void BindAnimator(Animator* animator);
    void BindText(const TextFactory* text);
    void BindGlyphs(const GlyphFont* glyphs);

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
    std::wstring StepText() const { return ProgressStepText(permille_); }

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
    explicit FinishPage(AppState& state);

    // 依赖注入（宿主构造后绑定；均可为空）。
    void BindAnimator(Animator* animator);
    void BindText(const TextFactory* text);
    void BindGlyphs(const GlyphFont* glyphs);
    void SetLogo(const LogoBitmap* logo) { logo_ = logo; }

    void Layout(const D2D1_RECT_F& contentCard);
    void Render(ID2D1DeviceContext* dc, const Theme& theme);

    // 进入完成页时启动对勾描边动画（由宿主在 SetPage(Finish) 后调用；无动画器时即时终值）。
    void StartCheckAnim();
    // 0..1 对勾描边进度（未注入 Animator 时为 1——即完成态）。
    float CheckProgress() const;

    WidgetHost& Host() noexcept { return host_; }

    // ---------------------------------------------------------------------
    // 意图钩子（Intent hooks）—— 本 todo 绝不 ShellExecute / 不启动进程：
    //   * onFinishIntent_()： 「立即启动」点击时抬高（完成意图 = 启动 + 关窗）。
    // 实际启动进程（§15）由 Todo 15 读取 AppState 执行（英雄页按钮 = 无条件启动）。
    // ---------------------------------------------------------------------
    void SetOnFinishIntent(std::function<void()> cb) { onFinishIntent_ = std::move(cb); }

    // 抬高完成意图（不启动进程）。
    void EmitFinishIntent();

    bool FinishIntentEmitted() const noexcept { return finishIntentEmitted_; }

    Button& FinishButton() noexcept { return finishButton_; }
    const std::wstring& ProductName() const noexcept { return productName_; }
    const std::wstring& Version() const noexcept { return version_; }
    const std::wstring& Tagline() const noexcept { return tagline_; }

private:
    AppState& state_;  // 借用（§12 共享状态）
    std::wstring productName_ = L"FreeAssetFilter";
    std::wstring version_;
    // 标语：与欢迎页完全一致的字符串（需求：完成页内容 = 欢迎页内容，仅按钮文案/图标不同）。
    std::wstring tagline_ = L"让文件浏览如丝般高效顺滑";

    Button finishButton_;
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
    D2D1_RECT_F buttonRect_{};
};

// ============================== Todo 12 接线入口 ===========================

// 页面⑤渲染入口（薄包装，供 Todo 12 调用）。
void RenderProgress(ID2D1DeviceContext* dc, const Theme& theme, ProgressPage& page);

// 页面⑥渲染入口（薄包装，供 Todo 12 调用）。
void RenderFinish(ID2D1DeviceContext* dc, const Theme& theme, FinishPage& page);

}  // namespace faf
