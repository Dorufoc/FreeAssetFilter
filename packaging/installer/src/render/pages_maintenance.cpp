//
// pages_maintenance.cpp - 维护 / 卸载确认 / 通用消息三个英雄页实现（T7）。
//
// 契约要点：
//   * 全程 DIP（§6）：不乘 DPI，坐标全部由宿主传入的 contentCard 推导；
//   * 视觉复用配置页的主题、标题和操作规格；
//   * 文字一律经 TextFactory（族探测），不硬编码字体族；
//   * 控件只复用 Button / CheckBox，输入与 Tab 走 WidgetHost（注册顺序 = Tab 顺序）；
//   * 页面不写文件系统 / 注册表，只抬高回调意图（实际动作归 T11/T12/T13）。
//
#include "render/pages_maintenance.h"

#include <d2d1_1helper.h>

#include <algorithm>
#include <utility>

#include "render/layout.h"
#include "render/pages_welcome.h"  // design::kButton*
#include "render/render_context.h"  // spk::ComPtr

namespace spk {

namespace {

// 维护流程延续配置页的左对齐页标题、内容边距与 152×36 主操作。
constexpr float kActionY = design::kButtonTop;
constexpr float kPrimaryW = design::kButtonWidth;
constexpr float kLinkW = 112.0f;
constexpr float kCenter = layout::kCanvasWidth * 0.5f;

D2D1_RECT_F ContentBand(float top, float bottom) {
    return D2D1::RectF(layout::kContentLeft, top,
                       layout::kContentLeft + layout::kContentWidth, bottom);
}

void DrawPageText(ID2D1DeviceContext* dc, const TextFactory* tf, const std::wstring& s,
                  const D2D1_RECT_F& rect, float size, DWRITE_FONT_WEIGHT weight,
                  const D2D1_COLOR_F& color, bool wrap = false,
                   DWRITE_TEXT_ALIGNMENT align = DWRITE_TEXT_ALIGNMENT_LEADING) {
    if (!dc || !tf || !tf->IsReady() || s.empty()) return;
    ComPtr<IDWriteTextFormat> fmt;
    if (FAILED(tf->CreateFormat(size, weight, align,
                                wrap ? DWRITE_PARAGRAPH_ALIGNMENT_NEAR : DWRITE_PARAGRAPH_ALIGNMENT_CENTER,
                                fmt.GetAddressOf()))) return;
    fmt->SetWordWrapping(wrap ? DWRITE_WORD_WRAPPING_WRAP : DWRITE_WORD_WRAPPING_NO_WRAP);
    // 按实际字形宽度省略，D2D 硬裁剪作为工厂失败的兜底。
    ComPtr<IDWriteInlineObject> ellipsis;
    if (SUCCEEDED(tf->Factory()->CreateEllipsisTrimmingSign(fmt.Get(), ellipsis.GetAddressOf()))) {
        DWRITE_TRIMMING trim{DWRITE_TRIMMING_GRANULARITY_CHARACTER, 0, 0};
        fmt->SetTrimming(&trim, ellipsis.Get());
    }
    ComPtr<ID2D1SolidColorBrush> brush;
    if (FAILED(dc->CreateSolidColorBrush(color, brush.GetAddressOf()))) return;
    dc->DrawText(s.c_str(), static_cast<UINT32>(s.size()), fmt.Get(), rect, brush.Get(),
                 D2D1_DRAW_TEXT_OPTIONS_CLIP);
}

// Button 复用其原有焦点环、命中和点击动画，仅在内容变化时适配动态标签。
std::wstring FitActionLabel(const TextFactory* tf, const std::wstring& label, float width, float size) {
    if (!tf || !tf->IsReady() || label.empty()) return label;
    ComPtr<IDWriteTextFormat> fmt;
    if (FAILED(tf->CreateFormat(size, weight::Regular, fmt.GetAddressOf()))) return label;
    fmt->SetWordWrapping(DWRITE_WORD_WRAPPING_NO_WRAP);
    ComPtr<IDWriteTextLayout> line;
    if (FAILED(tf->Factory()->CreateTextLayout(label.c_str(), static_cast<UINT32>(label.size()),
               fmt.Get(), width, design::kButtonHeight, line.GetAddressOf()))) return label;
    DWRITE_TEXT_METRICS metrics{};
    if (FAILED(line->GetMetrics(&metrics)) || metrics.width <= width - 2 * spacing::S) return label;
    BOOL trailing{}, inside{};
    DWRITE_HIT_TEST_METRICS hit{};
    if (FAILED(line->HitTestPoint(width - 2 * spacing::S - size, size * 0.5f,
                                  &trailing, &inside, &hit))) return L"…";
    return label.substr(0, hit.textPosition) + L"…";
}

// 内容卡片是否已完成过一次 Layout（用于 SetInfo / SetContent / SetBusy 后即时重排）。
bool HasCard(const D2D1_RECT_F& card) {
    return card.right > card.left && card.bottom > card.top;
}

D2D1_RECT_F PrimaryAction() {
    return D2D1::RectF(design::kButtonLeft, kActionY,
                        design::kButtonLeft + kPrimaryW, kActionY + design::kButtonHeight);
}

D2D1_RECT_F SecondaryAction() {
    return CenteredBaselineRect(design::kActionCenterX, design::kLinkBaselineY,
                                fontsize::Body16, kLinkW * 0.5f);
}

// 三个按钮在内容卡片底部居中的几何。out 顺序 = 视觉/Tab 顺序。
void LayoutButtonRow(float cx, float y, const float* widths, int count, float gap,
                     D2D1_RECT_F* out) {
    float total = 0.0f;
    for (int i = 0; i < count; ++i) total += widths[i];
    total += gap * static_cast<float>(count - 1);

    float x = cx - total * 0.5f;
    for (int i = 0; i < count; ++i) {
        out[i] = D2D1::RectF(x, y, x + widths[i], y + design::kButtonHeight);
        x += widths[i] + gap;
    }
}

}  // namespace

// ============================== Maintenance 页（Page=5） ====================

MaintenancePage::MaintenancePage(AppState& state)
    : installDir_(state.installDir), version_(state.installedVersion), detected_(state.installDetected) {
    updateButton_.SetLabel(L"更新");
    updateButton_.SetStyle(Button::Accent);
    updateButton_.SetOnClick([this]() { if (onUpdate_) onUpdate_(); });

    repairButton_.SetLabel(L"修复");
    repairButton_.SetOnClick([this]() { if (onRepair_) onRepair_(); });

    uninstallButton_.SetLabel(L"卸载");
    uninstallButton_.SetOnClick([this]() { if (onUninstall_) onUninstall_(); });

    cancelButton_.SetEnabled(false);
    UpdateActions();
}

void MaintenancePage::BindAnimator(Animator* animator) {
    updateButton_.BindAnimator(animator);
    repairButton_.BindAnimator(animator);
    uninstallButton_.BindAnimator(animator);
}

void MaintenancePage::BindText(const TextFactory* text) {
    text_ = text;
    updateButton_.BindText(text);
    repairButton_.BindText(text);
    uninstallButton_.BindText(text);
}

void MaintenancePage::BindGlyphs(const GlyphFont* glyphs) {
    updateButton_.BindGlyphs(glyphs);
    repairButton_.BindGlyphs(glyphs);
    uninstallButton_.BindGlyphs(glyphs);
}

void MaintenancePage::SetInfo(std::wstring installDir, std::wstring version, bool detected,
                              bool complete) {
    installDir_ = std::move(installDir);
    version_ = std::move(version);
    detected_ = detected;
    complete_ = complete;
    UpdateActions();
    RelayoutIfReady();
}

void MaintenancePage::SetOffer(MaintenanceOffer offer) {
    if (offer_ == offer) return;
    offer_ = offer;
    UpdateActions();
    RelayoutIfReady();
}

void MaintenancePage::SetOnUpdate(std::function<void()> cb) { onUpdate_ = std::move(cb); }
void MaintenancePage::SetOnRepair(std::function<void()> cb) { onRepair_ = std::move(cb); }
void MaintenancePage::SetOnUninstall(std::function<void()> cb) { onUninstall_ = std::move(cb); }
void MaintenancePage::SetOnCancel(std::function<void()> cb) { onCancel_ = std::move(cb); }

void MaintenancePage::UpdateActions() {
    const bool update = offer_ == MaintenanceOffer::Update;
    const bool uninstallOnly = offer_ == MaintenanceOffer::UninstallOnly;
    host_.Clear();
    updateButton_.SetEnabled(update && detected_);
    repairButton_.SetStyle(update ? Button::Secondary : Button::Accent);
    repairButton_.SetEnabled(!uninstallOnly && detected_);
    uninstallButton_.SetStyle(uninstallOnly ? Button::Accent : Button::Secondary);
    uninstallButton_.SetEnabled(!update);
    if (update) host_.Add(&updateButton_);
    if (!uninstallOnly) host_.Add(&repairButton_);
    if (!update) host_.Add(&uninstallButton_);
}

void MaintenancePage::RelayoutIfReady() {
    if (HasCard(card_)) Layout(card_);
}

void MaintenancePage::Layout(const D2D1_RECT_F& contentCard) {
    card_ = contentCard;
    titleRect_ = CenteredBaselineRect(kCenter, design::kHeroTitleBaselineY, fontsize::PageTitle);
    detailRect_ = ContentBand(382, 410);
    updateButton_.SetBounds(PrimaryAction());
    repairButton_.SetBounds(offer_ == MaintenanceOffer::Update ? SecondaryAction() : PrimaryAction());
    uninstallButton_.SetBounds(offer_ == MaintenanceOffer::UninstallOnly ? PrimaryAction() : SecondaryAction());
}

void MaintenancePage::Render(ID2D1DeviceContext* dc, const Theme& theme) {
    if (!dc) return;
    const auto o = PageOffsetDip(card_);
    D2D1_MATRIX_3X2_F parent{};
    dc->GetTransform(&parent);
    dc->SetTransform(D2D1::Matrix3x2F::Translation(o.x, o.y) * parent);
    DrawHeroBackground(dc, background_);
    const bool update = offer_ == MaintenanceOffer::Update;
    const bool uninstallOnly = offer_ == MaintenanceOffer::UninstallOnly;
    const wchar_t* title = update ? L"发现新版本" : uninstallOnly ? L"卸载 Sopeek" : L"修复 Sopeek";
    DrawPageText(dc, text_, title, titleRect_, fontsize::PageTitle, weight::Bold,
                  theme.textPrimary, false, DWRITE_TEXT_ALIGNMENT_CENTER);
    if (!version_.empty() && !uninstallOnly) {
        DrawPageText(dc, text_, L"已安装版本：" + version_, detailRect_, fontsize::Body16, weight::Regular,
                      theme.textSecondary, false, DWRITE_TEXT_ALIGNMENT_CENTER);
    }
    if (update) updateButton_.Render(dc, theme);
    if (!uninstallOnly) repairButton_.Render(dc, theme);
    if (!update) uninstallButton_.Render(dc, theme);
    dc->SetTransform(parent);
}

// ============================== UninstallConfirm 页（Page=6） ==============

UninstallConfirmPage::UninstallConfirmPage(AppState& state) : state_(state) {
    deleteUserData_.SetLabel(L"同时删除用户数据（设置、缓存、日志）");
    deleteUserData_.SetChecked(state_.deleteUserData);  // 默认 false
    deleteUserData_.SetOnToggle([this](bool value) {
        // 即时写回 AppState（§12），保证 Layout/SyncFromState 不回退用户选择。
        state_.deleteUserData = value;
    });

    confirmButton_.SetLabel(L"下一步");
    confirmButton_.SetTrailingChevron(true);
    confirmButton_.SetStyle(Button::Accent);
    confirmButton_.SetOnClick([this]() {
        if (onConfirm_) onConfirm_();
    });

    cancelButton_.SetLabel(L"取消");
    cancelButton_.SetStyle(Button::Secondary);
    cancelButton_.SetOnClick([this]() {
        if (onCancel_) onCancel_();
    });

    SetChecklist(true);
}

void UninstallConfirmPage::BindAnimator(Animator* animator) {
    deleteUserData_.BindAnimator(animator);
    confirmButton_.BindAnimator(animator);
    cancelButton_.BindAnimator(animator);
}

void UninstallConfirmPage::BindText(const TextFactory* text) {
    text_ = text;
    deleteUserData_.BindText(text);
    confirmButton_.BindText(text);
    cancelButton_.BindText(text);
}

void UninstallConfirmPage::BindGlyphs(const GlyphFont* glyphs) {
    deleteUserData_.BindGlyphs(glyphs);
    confirmButton_.BindGlyphs(glyphs);
    cancelButton_.BindGlyphs(glyphs);
}

void UninstallConfirmPage::SetOnConfirm(std::function<void()> cb) {
    onConfirm_ = std::move(cb);
}

void UninstallConfirmPage::SetOnCancel(std::function<void()> cb) { onCancel_ = std::move(cb); }

void UninstallConfirmPage::SyncFromState() {
    deleteUserData_.SetChecked(state_.deleteUserData);
}

void UninstallConfirmPage::SyncToState() {
    state_.deleteUserData = deleteUserData_.Checked();
}

bool UninstallConfirmPage::DeleteUserData() const { return deleteUserData_.Checked(); }

void UninstallConfirmPage::Layout(const D2D1_RECT_F& contentCard) {
    card_ = contentCard;
    if (checklist_) {
        titleRect_ = BaselineRect(layout::kContentLeft, layout::kContentLeft + layout::kContentWidth,
                                  design::kPageTitleBaselineY, fontsize::PageTitle);
        const float left = design::kOptionAutostartLeft;
        deleteUserData_.SetBounds(D2D1::RectF(left, design::kFieldTop, left + 292.0f,
                                             design::kFieldTop + 29.0f));
    } else {
        titleRect_ = CenteredBaselineRect(kCenter, design::kHeroTitleBaselineY, fontsize::PageTitle);
    }
    confirmButton_.SetBounds(PrimaryAction());
    cancelButton_.SetBounds(SecondaryAction());
    SyncFromState();
}

void UninstallConfirmPage::SetChecklist(bool checklist) {
    checklist_ = checklist;
    cancelButton_.SetLabel(checklist_ ? L"返回" : L"取消");
    if (HasCard(card_)) Layout(card_);
    host_.Clear();
    if (checklist_) host_.Add(&deleteUserData_);
    host_.Add(&confirmButton_);
    host_.Add(&cancelButton_);
}

void UninstallConfirmPage::Render(ID2D1DeviceContext* dc, const Theme& theme) {
    if (!dc) return;
    const auto o = PageOffsetDip(card_);
    D2D1_MATRIX_3X2_F parent{};
    dc->GetTransform(&parent);
    dc->SetTransform(D2D1::Matrix3x2F::Translation(o.x, o.y) * parent);
    if (checklist_) {
        DrawPageText(dc, text_, L"卸载选项", titleRect_, fontsize::PageTitle,
                     weight::Bold, theme.textPrimary);
        deleteUserData_.Render(dc, theme);
    } else {
        DrawHeroBackground(dc, background_);
        DrawPageText(dc, text_, L"卸载 Sopeek", titleRect_, fontsize::PageTitle, weight::Bold,
                     theme.textPrimary, false, DWRITE_TEXT_ALIGNMENT_CENTER);
    }
    confirmButton_.Render(dc, theme);
    cancelButton_.Render(dc, theme);
    dc->SetTransform(parent);
}

// ============================== Message 页（Page=7） =======================

MessagePage::MessagePage() {
    primaryButton_.SetStyle(Button::Accent);
    primaryButton_.SetOnClick([this]() {
        if (onPrimary_) onPrimary_();
    });

    secondaryButton_.SetStyle(Button::Secondary);
    secondaryButton_.SetOnClick([this]() {
        if (onSecondary_) onSecondary_();
    });

    // 操作区从左到右：次按钮 → 主按钮。
    host_.Add(&secondaryButton_);
    host_.Add(&primaryButton_);
    UpdateButtonStates();
}

MessagePage::MessagePage(AppState& state) : MessagePage() {
    (void)state;  // 本页不读写 AppState
}

void MessagePage::BindAnimator(Animator* animator) {
    primaryButton_.BindAnimator(animator);
    secondaryButton_.BindAnimator(animator);
}

void MessagePage::BindText(const TextFactory* text) {
    text_ = text;
    primaryButton_.BindText(text);
    secondaryButton_.BindText(text);
    primaryButton_.SetLabel(FitActionLabel(text_, primaryLabel_, kPrimaryW, fontsize::ButtonText));
    secondaryButton_.SetLabel(FitActionLabel(text_, secondaryLabel_, kLinkW, fontsize::Body16));
}

void MessagePage::BindGlyphs(const GlyphFont* glyphs) {
    primaryButton_.BindGlyphs(glyphs);
    secondaryButton_.BindGlyphs(glyphs);
}

void MessagePage::SetContent(std::wstring title, std::wstring body, std::wstring primaryLabel,
                             std::wstring secondaryLabel, bool showSecondary) {
    title_ = std::move(title);
    body_ = std::move(body);
    primaryLabel_ = std::move(primaryLabel);
    secondaryLabel_ = std::move(secondaryLabel);
    showSecondary_ = showSecondary && !secondaryLabel_.empty();

    BindText(text_);  // 用当前字体重新适配两个动态标签。

    UpdateButtonStates();
    RelayoutIfReady();
}

void MessagePage::SetOnPrimary(std::function<void()> cb) { onPrimary_ = std::move(cb); }
void MessagePage::SetOnSecondary(std::function<void()> cb) { onSecondary_ = std::move(cb); }

void MessagePage::SetBusy(bool busy, std::wstring text) {
    busy_ = busy;
    busyText_.clear();
    if (busy_) busyText_ = std::move(text);
    UpdateButtonStates();
    RelayoutIfReady();
}

bool MessagePage::PrimaryVisible() const { return !busy_ && !primaryLabel_.empty(); }

bool MessagePage::SecondaryVisible() const {
    return !busy_ && showSecondary_ && !secondaryLabel_.empty();
}

void MessagePage::UpdateButtonStates() {
    // busy / 空标签时按钮隐藏（不渲染）且禁用（不参与 Tab）。
    primaryButton_.SetEnabled(PrimaryVisible());
    secondaryButton_.SetEnabled(SecondaryVisible());
    if (host_.Focused() && !host_.Focused()->IsFocusable()) host_.FocusWidget(nullptr);
}

void MessagePage::RelayoutIfReady() {
    if (HasCard(card_)) Layout(card_);
}

void MessagePage::Layout(const D2D1_RECT_F& contentCard) {
    card_ = contentCard;
    titleRect_ = ContentBand(74, 124);
    bodyRect_ = ContentBand(152, kActionY - spacing::L);
    busyRect_ = ContentBand(kActionY, kActionY + design::kButtonHeight);
    const bool primary = PrimaryVisible();
    const bool secondary = SecondaryVisible();
    primaryRect_ = secondaryRect_ = D2D1::RectF();
    if (primary && secondary) {
        const float widths[] = {kLinkW, kPrimaryW};
        D2D1_RECT_F row[2];
        LayoutButtonRow(kCenter, kActionY, widths, 2, spacing::M, row);
        secondaryRect_ = row[0];
        primaryRect_ = row[1];
    } else if (primary || secondary) {
        const float width = primary ? kPrimaryW : kLinkW;
        LayoutButtonRow(kCenter, kActionY, &width, 1, 0, primary ? &primaryRect_ : &secondaryRect_);
    }
    primaryButton_.SetBounds(primaryRect_);
    secondaryButton_.SetBounds(secondaryRect_);
}

void MessagePage::Render(ID2D1DeviceContext* dc, const Theme& theme) {
    if (!dc) return;
    const auto o = PageOffsetDip(card_);
    D2D1_MATRIX_3X2_F parent{};
    dc->GetTransform(&parent);
    dc->SetTransform(D2D1::Matrix3x2F::Translation(o.x, o.y) * parent);
    DrawPageText(dc, text_, title_, titleRect_, fontsize::PageTitle, weight::Bold, theme.textPrimary);
    DrawPageText(dc, text_, body_, bodyRect_, fontsize::Body16, weight::Regular, theme.textSecondary, true);
    if (busy_) {
        DrawPageText(dc, text_, busyText_, busyRect_, fontsize::Body16, weight::SemiBold, theme.textPrimary);
    } else {
        if (PrimaryVisible()) primaryButton_.Render(dc, theme);
        if (SecondaryVisible()) secondaryButton_.Render(dc, theme);
    }

    dc->SetTransform(parent);
}

// ============================== T10 接线入口 ===============================

void RenderMaintenance(ID2D1DeviceContext* dc, const Theme& theme, MaintenancePage& page) {
    page.Render(dc, theme);
}

void RenderUninstallConfirm(ID2D1DeviceContext* dc, const Theme& theme,
                            UninstallConfirmPage& page) {
    page.Render(dc, theme);
}

void RenderMessage(ID2D1DeviceContext* dc, const Theme& theme, MessagePage& page) {
    page.Render(dc, theme);
}

}  // namespace spk
