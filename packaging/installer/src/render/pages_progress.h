#pragma once
//
// pages_progress.h - 安装向导页面「正在安装」与「安装完成」。
//
// 视觉唯一依据：
//   `install_design/安装完成.svg` —— 品牌图形 + 「安装完成」32px bold 基线 354；
//                                    黑色胶囊「立即体验」152x36 (244,427)；「退出」16px 基线 503。
//
// 设计稿的「正在安装」页**没有取消按钮**（经用户确认）：取消由标题栏 ✕ 触发
// （走既有 RaiseCancelIntent → 引擎安全停止）。设计稿同样没有进度条右侧的按钮。
//
// Frozen contracts：
//  - §10：进度值一律为 **permille 0..1000**（messages.h 的 WM_INSTALL_PROGRESS 语义），
//    显示百分比 = permille/10（整数，设计稿只有整数）。
//  - §12：页面/选项状态读写 AppState。
//  - §13：视觉只消费 theme.h token；文字经 text.h。
//  - §6：坐标全程 DIP（不乘 DPI）。
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

namespace spk {

class HeroArt;      // render/hero_art.h
class LogoBitmap;   // render/logo.h（完成页背景图）

// ============================== 纯函数辅助 =================================

// 操作类型（T8）：安装 / 修复 / 卸载。ProgressPage / FinishPage 各自以
// `using Kind = ProgressKind;` 暴露 `ProgressPage::Kind` / `FinishPage::Kind`。
enum class ProgressKind { Install, Repair, Uninstall, Update };

// permille → 步骤索引：0 初始化 / 1 复制文件 / 2 写入快捷方式 / 3 完成。
int ProgressStepIndex(int permille);

// 旧签名（Install，保留以兼容既有调用/测试）
std::wstring ProgressStepText(int permille);

// 新签名：按 kind 返回步骤中文文案。纯函数，便于断言。
std::wstring ProgressStepText(ProgressKind kind, int permille);

// permille → 百分比文案（`permille/10.0`，保留一位小数，如 500 ⇒ L"50.0%"）。
std::wstring ProgressPercentText(int permille);

// permille → 设计稿口径的整数百分比（如 300 ⇒ L"30%"）。
std::wstring ProgressPercentTextCompact(int permille);

// ============================== 页面「正在安装」 ===========================

class ProgressPage {
public:
    using Kind = ProgressKind;

    enum class State { Running, Cancelling, Cancelled };

    explicit ProgressPage(AppState& state);

    void BindAnimator(Animator* animator);
    void BindText(const TextFactory* text);
    void BindGlyphs(const GlyphFont* glyphs);
    void SetKind(Kind kind);
    void SetKind(Operation operation);
    Kind GetKind() const noexcept { return kind_; }

    // 设计稿没有取消按钮：本开关只控制「✕ / ESC 是否允许取消」，不再影响任何控件。
    void SetCancellable(bool cancellable) { cancellable_ = cancellable; }
    bool Cancellable() const noexcept { return cancellable_; }

    void SetNotice(std::wstring text) { notice_ = std::move(text); }
    const std::wstring& Notice() const noexcept { return notice_; }

    void SetStageText(std::wstring text) { stageText_ = std::move(text); }
    const std::wstring& StageText() const noexcept { return stageText_; }

    std::wstring HeadingText() const;

    void Layout(const D2D1_RECT_F& contentCard);
    void Render(ID2D1DeviceContext* dc, const Theme& theme);

    WidgetHost& Host() noexcept { return host_; }

    void SetProgressPermille(int permille);
    int Permille() const noexcept { return permille_; }
    float Percent() const noexcept { return static_cast<float>(permille_) / 10.0f; }
    std::wstring PercentText() const { return ProgressPercentText(permille_); }
    std::wstring StepText() const {
        return stageText_.empty() ? ProgressStepText(kind_, permille_) : stageText_;
    }

    void SetOnCancel(std::function<void()> cb) { onCancel_ = std::move(cb); }
    void RequestCancel();
    void MarkCancelled();

    bool CancelRequested() const noexcept { return cancelRequested_; }
    State Current() const noexcept { return phase_; }

    ProgressBar& Bar() noexcept { return bar_; }

private:
    AppState& state_;  // 借用（§12 共享状态）
    ProgressBar bar_;
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
    D2D1_RECT_F barRect_{};
    D2D1_RECT_F stageRect_{};
    D2D1_RECT_F percentRect_{};
    D2D1_RECT_F noticeRect_{};
};

// ============================== 页面「安装完成」 ===========================

// 完成页（英雄页）：品牌图形 + 「安装完成」+ 黑色胶囊「立即体验」+「退出」。
class FinishPage {
public:
    using Kind = ProgressKind;

    explicit FinishPage(AppState& state);

    void BindAnimator(Animator* animator);
    void BindText(const TextFactory* text);
    void BindGlyphs(const GlyphFont* glyphs);
    void SetHeroArt(const HeroArt* art) { art_ = art; }
    // 英雄页背景图（IDR_HERO_BG，与欢迎页同一张）；为空或深色主题时退回矢量图形。
    void SetBackground(const LogoBitmap* background) { background_ = background; }

    // Install：安装完成 / 立即体验 / 退出
    // Repair ：修复完成 / 完成 / 退出
    // Uninstall：卸载完成 / 关闭 / 退出（无退出链接，按钮即关闭）
    void SetKind(Kind kind);
    void SetKind(Operation operation);
    Kind GetKind() const noexcept { return kind_; }

    void SetNotice(std::wstring notice) { notice_ = std::move(notice); }
    const std::wstring& Notice() const noexcept { return notice_; }

    void Layout(const D2D1_RECT_F& contentCard);
    void Render(ID2D1DeviceContext* dc, const Theme& theme);

    void StartCheckAnim();
    float CheckProgress() const;

    WidgetHost& Host() noexcept { return host_; }

    void SetOnFinishIntent(std::function<void()> cb) { onFinishIntent_ = std::move(cb); }
    // 「退出」链接：直接关窗（不启动应用）。
    void SetOnExitIntent(std::function<void()> cb) { onExitIntent_ = std::move(cb); }
    void EmitFinishIntent();

    bool FinishIntentEmitted() const noexcept { return finishIntentEmitted_; }

    Button& FinishButton() noexcept { return finishButton_; }
    Button& ExitButton() noexcept { return exitButton_; }
    // 修复完成页专用（设计稿未覆盖）：勾选后「完成」会去提权启动 Sopeek，默认不勾选。
    CheckBox& LaunchAfterRepairBox() noexcept { return launchBox_; }
    bool LaunchAfterRepair() const noexcept { return launchBox_.Checked(); }

    const std::wstring& ProductName() const noexcept { return productName_; }
    const std::wstring& Version() const noexcept { return version_; }
    const std::wstring& Tagline() const noexcept { return tagline_; }
    const std::wstring& Title() const noexcept { return title_; }

private:
    void RebuildHost();

    AppState& state_;  // 借用（§12 共享状态）
    std::wstring productName_ = L"Sopeek";
    std::wstring version_;
    std::wstring tagline_ = L"全能 · 高效 · 开源";
    std::wstring title_ = L"安装完成";
    std::wstring notice_;
    Kind kind_ = Kind::Install;

    Button finishButton_;
    Button exitButton_;
    CheckBox launchBox_;
    WidgetHost host_;

    const HeroArt* art_ = nullptr;
    const LogoBitmap* background_ = nullptr;
    const TextFactory* text_ = nullptr;
    const GlyphFont* glyphs_ = nullptr;

    Animator* animator_ = nullptr;
    AnimValue* checkAnim_ = nullptr;
    float checkFallback_ = 1.0f;
    std::string checkName_;

    std::function<void()> onFinishIntent_;
    std::function<void()> onExitIntent_;
    bool finishIntentEmitted_ = false;

    D2D1_RECT_F card_{};
    D2D1_RECT_F titleRect_{};
    D2D1_RECT_F launchBoxRect_{};
    D2D1_RECT_F noticeRect_{};
};

// ============================== 接线入口 ===================================

void RenderProgress(ID2D1DeviceContext* dc, const Theme& theme, ProgressPage& page);
void RenderFinish(ID2D1DeviceContext* dc, const Theme& theme, FinishPage& page);

}  // namespace spk
