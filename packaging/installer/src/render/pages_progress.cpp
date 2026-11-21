//
// pages_progress.cpp - 页面「正在安装」与「安装完成」实现。
//
// 视觉依据：src/sopeek/resources/icons/install_design/{正在安装,安装完成}.svg。
// 坐标全程 DIP（§6）；进度语义为 permille 0..1000（§10）。
//
#include "render/pages_progress.h"

#include <d2d1_1helper.h>

#include <algorithm>
#include <cstdio>

#include "render/hero_art.h"
#include "render/layout.h"          // layout::* / PageOffsetDip
#include "render/logo.h"
#include "render/pages_welcome.h"   // design::* / BaselineRect
#include "render/render_context.h"  // spk::ComPtr

namespace spk {

namespace {

constexpr float kEnterMs = 260.0f;
constexpr float kSlideDip = 16.0f;

void DrawText(ID2D1DeviceContext* dc, const TextFactory* tf, const std::wstring& s,
              const D2D1_RECT_F& rect, float size, DWRITE_FONT_WEIGHT weight,
              DWRITE_TEXT_ALIGNMENT align, const D2D1_COLOR_F& color) {
    if (!dc || !tf || !tf->IsReady() || s.empty()) return;
    ComPtr<IDWriteTextFormat> fmt;
    if (FAILED(tf->CreateFormat(size, weight, align, DWRITE_PARAGRAPH_ALIGNMENT_CENTER,
                                fmt.GetAddressOf()))) {
        return;
    }
    fmt->SetWordWrapping(DWRITE_WORD_WRAPPING_NO_WRAP);
    ComPtr<ID2D1SolidColorBrush> brush;
    if (FAILED(dc->CreateSolidColorBrush(color, brush.GetAddressOf()))) return;
    dc->DrawText(s.c_str(), static_cast<UINT32>(s.size()), fmt.Get(), rect, brush.Get());
}

}  // namespace

// ============================== 纯函数辅助 =================================

int ProgressStepIndex(int permille) {
    if (permille < 250) return 0;
    if (permille < 750) return 1;
    if (permille < 1000) return 2;
    return 3;
}

std::wstring ProgressStepText(int permille) { return ProgressStepText(ProgressKind::Install, permille); }

std::wstring ProgressStepText(ProgressKind kind, int permille) {
    const int step = ProgressStepIndex(permille);
    switch (kind) {
        case ProgressKind::Install: {
            static const wchar_t* kInstall[] = {L"初始化", L"复制文件", L"写入快捷方式", L"完成"};
            return kInstall[step];
        }
        case ProgressKind::Update:
        case ProgressKind::Repair: {
            static const wchar_t* kRepair[] = {L"准备文件", L"复制文件", L"写入快捷方式", L"完成"};
            return kRepair[step];
        }
        case ProgressKind::Uninstall: {
            if (permille < 200) return L"清理快捷方式";
            if (permille < 400) return L"清理注册表";
            if (permille < 800) return L"删除程序文件";
            if (permille < 1000) return L"清理用户数据";
            return L"完成";
        }
    }
    return L"";
}

std::wstring ProgressPercentText(int permille) {
    const int clamped = std::clamp(permille, 0, 1000);
    wchar_t buf[32] = {};
    swprintf(buf, 32, L"%.1f%%", static_cast<double>(clamped) / 10.0);
    return buf;
}

std::wstring ProgressPercentTextCompact(int permille) {
    const int clamped = std::clamp(permille, 0, 1000);
    wchar_t buf[32] = {};
    swprintf(buf, 32, L"%d%%", clamped / 10);  // 设计稿只显示整数百分比（如 30%）
    return buf;
}

// ============================== 页面「正在安装」 ===========================

ProgressPage::ProgressPage(AppState& state) : state_(state) {
    bar_.SetBounds(D2D1::RectF(layout::kContentLeft, design::kTrackTop,
                               layout::kContentLeft + layout::kContentWidth,
                               design::kTrackTop + design::kTrackHeight));
}

void ProgressPage::BindAnimator(Animator* animator) { bar_.BindAnimator(animator); }

void ProgressPage::BindText(const TextFactory* text) { text_ = text; }

void ProgressPage::BindGlyphs(const GlyphFont* glyphs) { glyphs_ = glyphs; }

void ProgressPage::SetKind(Kind kind) {
    if (kind_ == kind) return;
    kind_ = kind;
    stageText_.clear();
}

void ProgressPage::SetKind(Operation operation) {
    switch (operation) {
        case Operation::Install: SetKind(Kind::Install); break;
        case Operation::Repair: SetKind(Kind::Repair); break;
        case Operation::Update: SetKind(Kind::Update); break;
        case Operation::Uninstall: SetKind(Kind::Uninstall); break;
    }
}

std::wstring ProgressPage::HeadingText() const {
    switch (kind_) {
        case Kind::Install: return L"正在安装";
        case Kind::Repair: return L"正在修复";
        case Kind::Update: return L"正在更新";
        case Kind::Uninstall: return L"正在卸载";
    }
    return L"正在安装";
}

void ProgressPage::SetProgressPermille(int permille) {
    permille_ = std::clamp(permille, 0, 1000);
    bar_.SetProgressPermille(permille_);
}

void ProgressPage::RequestCancel() {
    // 设计稿没有取消按钮：本方法只负责抬高取消意图 + 切到 Cancelling 视觉态
    //（阶段文案由宿主经 SetStageText 决定）。引擎安全停止由宿主/引擎负责。
    if (phase_ == State::Cancelled) return;
    cancelRequested_ = true;
    phase_ = State::Cancelling;
    if (onCancel_) onCancel_();
}

void ProgressPage::MarkCancelled() { phase_ = State::Cancelled; }

void ProgressPage::Layout(const D2D1_RECT_F& contentCard) {
    card_ = contentCard;
    // 底部排列进度与状态，保留标题和进度区之间的留白。
    headingRect_ = CenteredBaselineRect(design::kPageTitleCenterX, design::kPageTitleBaselineY,
                                        fontsize::PageTitle);
    barRect_ = D2D1::RectF(layout::kContentLeft, design::kTrackTop,
                           layout::kContentLeft + layout::kContentWidth,
                           design::kTrackTop + design::kTrackHeight);
    bar_.SetBounds(barRect_);
    stageRect_ = BaselineRect(design::kStageLeft, design::kPercentCenterX - 48.0f,
                              design::kStageBaselineY, fontsize::Body16);
    percentRect_ = CenteredBaselineRect(design::kPercentCenterX, design::kStageBaselineY,
                                        fontsize::Body16, 120.0f);
    noticeRect_ = BaselineRect(stageRect_.left, barRect_.right,
                               design::kStageBaselineY + 20.0f, fontsize::Body);
}

void ProgressPage::Render(ID2D1DeviceContext* dc, const Theme& theme) {
    if (!dc) return;
    const D2D1_POINT_2F o = PageOffsetDip(card_);
    D2D1_MATRIX_3X2_F parent{};
    dc->GetTransform(&parent);
    dc->SetTransform(D2D1::Matrix3x2F::Translation(o.x, o.y) * parent);

    // 标题（正在安装 / 正在修复 / 正在卸载）
    DrawText(dc, text_, HeadingText(), headingRect_, fontsize::PageTitle, weight::Bold,
             DWRITE_TEXT_ALIGNMENT_CENTER, theme.textPrimary);

    bar_.Render(dc, theme);

    DrawText(dc, text_, StepText(), stageRect_, fontsize::Body16, weight::Regular,
             DWRITE_TEXT_ALIGNMENT_LEADING, theme.textPrimary);
    DrawText(dc, text_, ProgressPercentTextCompact(permille_), percentRect_, fontsize::Body16,
             weight::Regular, DWRITE_TEXT_ALIGNMENT_CENTER, theme.textPrimary);

    if (!notice_.empty()) {
        DrawText(dc, text_, notice_, noticeRect_, fontsize::Body, weight::Regular,
                 DWRITE_TEXT_ALIGNMENT_LEADING, theme.muted);
    }
}

// ============================== 页面「安装完成」 ===========================

FinishPage::FinishPage(AppState& state) : state_(state) {
    checkName_ = "page-finish-check";
    version_ = ReadVersionString();

    finishButton_.SetStyle(Button::Accent);
    finishButton_.SetLabel(L"立即体验");
    finishButton_.SetOnClick([this]() { EmitFinishIntent(); });

    exitButton_.SetStyle(Button::Secondary);
    exitButton_.SetLabel(L"退出");
    exitButton_.SetOnClick([this]() {
        if (onExitIntent_) onExitIntent_();
    });

    // 修复完成页的可选启动项（设计稿未覆盖该页；保持与旧实现等价的功能）。
    launchBox_.SetLabel(L"立即启动 Sopeek");
    launchBox_.SetOnToggle([this](bool v) { state_.optLaunchAfterRepair = v; });

    RebuildHost();
}

void FinishPage::RebuildHost() {
    host_.Clear();
    host_.Add(&finishButton_);
    // 卸载完成页只有一个「关闭」按钮（设计稿的「退出」在此页是重复入口，不渲染）。
    if (kind_ != Kind::Uninstall) host_.Add(&exitButton_);
    if (kind_ == Kind::Repair) host_.Add(&launchBox_);
}

void FinishPage::SetKind(Kind kind) {
    kind_ = kind;
    switch (kind) {
        case Kind::Install:
            title_ = L"安装完成";
            finishButton_.SetLabel(L"立即体验");
            exitButton_.SetLabel(L"退出");
            break;
        case Kind::Update:
            title_ = L"更新完成";
            finishButton_.SetLabel(L"立即体验");
            exitButton_.SetLabel(L"退出");
            break;
        case Kind::Repair:
            title_ = L"修复完成";
            finishButton_.SetLabel(L"完成");
            exitButton_.SetLabel(L"退出");
            break;
        case Kind::Uninstall:
            title_ = L"卸载完成";
            finishButton_.SetLabel(L"再见");
            exitButton_.SetLabel(L"退出");
            break;
    }
    finishButton_.SetTrailingChevron(false);
    RebuildHost();
}

void FinishPage::SetKind(Operation operation) {
    switch (operation) {
        case Operation::Install: SetKind(Kind::Install); break;
        case Operation::Repair: SetKind(Kind::Repair); break;
        case Operation::Update: SetKind(Kind::Update); break;
        case Operation::Uninstall: SetKind(Kind::Uninstall); break;
    }
}

void FinishPage::BindAnimator(Animator* animator) {
    animator_ = animator;
    finishButton_.BindAnimator(animator);
    exitButton_.BindAnimator(animator);
    launchBox_.BindAnimator(animator);
    if (animator_) {
        checkAnim_ = &animator_->Animate(checkName_, 0.0f, 1.0f, 320.0f, easing::Entrance);
    }
}

void FinishPage::BindText(const TextFactory* text) {
    text_ = text;
    finishButton_.BindText(text);
    exitButton_.BindText(text);
    launchBox_.BindText(text);
}

void FinishPage::BindGlyphs(const GlyphFont* glyphs) {
    glyphs_ = glyphs;
    finishButton_.BindGlyphs(glyphs);
    exitButton_.BindGlyphs(glyphs);
    launchBox_.BindGlyphs(glyphs);
}

void FinishPage::StartCheckAnim() {
    checkFallback_ = 1.0f;
    if (!animator_) return;
    checkAnim_ = &animator_->Animate(checkName_, 0.0f, 1.0f, 320.0f, easing::Entrance);
}

float FinishPage::CheckProgress() const {
    if (checkAnim_) return std::clamp(checkAnim_->Value(), 0.0f, 1.0f);
    return checkFallback_;
}

void FinishPage::EmitFinishIntent() {
    finishIntentEmitted_ = true;
    if (onFinishIntent_) onFinishIntent_();
}

void FinishPage::Layout(const D2D1_RECT_F& contentCard) {
    card_ = contentCard;
    titleRect_ = BaselineRect(0.0f, layout::kCanvasWidth, design::kFinishTitleBaselineY,
                              fontsize::PageTitle);

    finishButton_.SetBounds(D2D1::RectF(design::kButtonLeft, design::kButtonTop,
                                        design::kButtonLeft + design::kButtonWidth,
                                        design::kButtonTop + design::kButtonHeight));
    exitButton_.SetBounds(CenteredBaselineRect(design::kActionCenterX, design::kLinkBaselineY,
                                               fontsize::Body16, 30.0f));
    // 修复页勾选项：按钮上方居中（该页无设计稿，沿用同一视觉语言）。
    {
        const float boxW = 29.0f + 8.0f + 120.0f;
        const float cx = layout::kCanvasWidth * 0.5f;
        launchBoxRect_ = D2D1::RectF(cx - boxW * 0.5f, design::kButtonTop - 52.0f,
                                    cx + boxW * 0.5f, design::kButtonTop - 23.0f);
        launchBox_.SetBounds(launchBoxRect_);
        launchBox_.SetChecked(state_.optLaunchAfterRepair);
    }
    noticeRect_ = BaselineRect(layout::kContentLeft, layout::kContentLeft + layout::kContentWidth,
                               design::kLinkBaselineY + 24.0f, fontsize::Body);
}

void FinishPage::Render(ID2D1DeviceContext* dc, const Theme& theme) {
    if (!dc) return;
    const float p = CheckProgress();
    Theme t = theme;
    t.textPrimary.a *= (0.35f + 0.65f * p);
    t.muted.a *= p;

    const D2D1_POINT_2F o = PageOffsetDip(card_);
    D2D1_MATRIX_3X2_F parent{};
    dc->GetTransform(&parent);
    dc->SetTransform(D2D1::Matrix3x2F::Translation(o.x, o.y) * parent);

    if (!DrawHeroBackground(dc, background_, p)) {
        DrawHeroArtwork(dc, art_, nullptr, t, p);
    }

    DrawText(dc, text_, title_, titleRect_, fontsize::PageTitle, weight::Bold,
             DWRITE_TEXT_ALIGNMENT_CENTER, t.textPrimary);
    if (kind_ == Kind::Repair) launchBox_.Render(dc, t);
    finishButton_.Render(dc, t);
    if (kind_ != Kind::Uninstall) exitButton_.Render(dc, t);

    if (!notice_.empty()) {
        DrawText(dc, text_, notice_, noticeRect_, fontsize::Body, weight::Regular,
                 DWRITE_TEXT_ALIGNMENT_CENTER, t.muted);
    }
}

// ============================== 接线入口 ===================================

void RenderProgress(ID2D1DeviceContext* dc, const Theme& theme, ProgressPage& page) {
    page.Render(dc, theme);
}

void RenderFinish(ID2D1DeviceContext* dc, const Theme& theme, FinishPage& page) {
    page.Render(dc, theme);
}

}  // namespace spk
