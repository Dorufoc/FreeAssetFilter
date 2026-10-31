//
// pages_maintenance.cpp - 维护 / 卸载确认 / 通用消息三个英雄页实现（T7）。
//
// 契约要点：
//   * 全程 DIP（§6）：不乘 DPI，坐标全部由宿主传入的 contentCard 推导；
//   * 视觉只消费 theme.h 既有 token；红警示沿用 pages_welcome / pages_progress 的
//     (0.85, 0.20, 0.20) 既有警示色，不新增 token；
//   * 文字一律经 TextFactory（族探测），不硬编码字体族；
//   * 控件只复用 Button / CheckBox，输入与 Tab 走 WidgetHost（注册顺序 = Tab 顺序）；
//   * 页面不写文件系统 / 注册表，只抬高回调意图（实际动作归 T11/T12/T13）。
//
#include "render/pages_maintenance.h"

#include <d2d1_1helper.h>

#include <algorithm>
#include <utility>

#include "render/render_context.h"  // spk::ComPtr

namespace spk {

namespace {

// 按钮尺寸（DIP）。英雄页按钮由页面自己摆放，不走外壳底部条。
constexpr float kButtonH = 40.0f;
constexpr float kMaintenanceButtonW = 120.0f;
constexpr float kConfirmButtonW = 120.0f;
constexpr float kCancelButtonW = 100.0f;
constexpr float kMessagePrimaryW = 140.0f;
constexpr float kMessageSecondaryW = 120.0f;

// 既有警示红（与 pages_welcome.cpp / pages_progress.cpp 中的内联红一致）。
D2D1_COLOR_F DangerColor() { return D2D1::ColorF(0.85f, 0.20f, 0.20f, 1.0f); }

// 单行文字（NoWrap）。paragraph 居中，行内按 align 对齐。
void DrawLineText(ID2D1DeviceContext* dc, const TextFactory* tf, const std::wstring& s,
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

// 多行文字（自动换行、顶部段落对齐）。用于 Message 正文与 UninstallConfirm 说明。
void DrawBlockText(ID2D1DeviceContext* dc, const TextFactory* tf, const std::wstring& s,
                   const D2D1_RECT_F& rect, float size, DWRITE_FONT_WEIGHT weight,
                   DWRITE_TEXT_ALIGNMENT align, const D2D1_COLOR_F& color) {
    if (!dc || !tf || !tf->IsReady() || s.empty()) return;
    ComPtr<IDWriteTextFormat> fmt;
    if (FAILED(tf->CreateFormat(size, weight, align, DWRITE_PARAGRAPH_ALIGNMENT_NEAR,
                                fmt.GetAddressOf()))) {
        return;
    }
    fmt->SetWordWrapping(DWRITE_WORD_WRAPPING_WRAP);
    ComPtr<ID2D1SolidColorBrush> brush;
    if (FAILED(dc->CreateSolidColorBrush(color, brush.GetAddressOf()))) return;
    dc->DrawText(s.c_str(), static_cast<UINT32>(s.size()), fmt.Get(), rect, brush.Get());
}

// 内容卡片是否已完成过一次 Layout（用于 SetInfo / SetContent / SetBusy 后即时重排）。
bool HasCard(const D2D1_RECT_F& card) {
    return card.right > card.left && card.bottom > card.top;
}

// 卸载删除范围说明（D15 C3 唯一模型；Layout / Render 共用同一份文案）。
const std::vector<std::wstring>& ScopeLines() {
    static const std::vector<std::wstring> kScope = {
        L"未勾选时，用户数据全部保留；勾选后将删除以下已知用户数据：",
        L"· %LOCALAPPDATA%\\Sopeek（设置、缓存、日志）",
        L"· 安装目录\\data（$INSTDIR\\data）",
        L"· 安装目录\\_internal\\data（$INSTDIR\\_internal\\data）",
        L"· 环境变量 SPK_DATA_DIR 指定的自定义目录永不删除。",
        L"· 安装目录下的未知用户文件与你导出的文件不会被删除。",
    };
    return kScope;
}

// 三个按钮在内容卡片底部居中的几何。out 顺序 = 视觉/Tab 顺序。
void LayoutButtonRow(float cx, float y, const float* widths, int count, float gap,
                     D2D1_RECT_F* out) {
    float total = 0.0f;
    for (int i = 0; i < count; ++i) total += widths[i];
    total += gap * static_cast<float>(count - 1);

    float x = cx - total * 0.5f;
    for (int i = 0; i < count; ++i) {
        out[i] = D2D1::RectF(x, y, x + widths[i], y + kButtonH);
        x += widths[i] + gap;
    }
}

}  // namespace

// ============================== Maintenance 页（Page=5） ====================

MaintenancePage::MaintenancePage(AppState& state) : state_(state) {
    // 初值来自 AppState；T11 在 Detect() 后以 SetInfo 覆盖。
    installDir_ = state_.installDir;
    version_ = state_.installedVersion;
    detected_ = state_.installDetected;

    repairButton_.SetLabel(L"修复");
    repairButton_.SetStyle(Button::Accent);
    repairButton_.SetOnClick([this]() {
        if (onRepair_) onRepair_();
    });

    uninstallButton_.SetLabel(L"卸载");
    uninstallButton_.SetStyle(Button::Secondary);
    uninstallButton_.SetOnClick([this]() {
        if (onUninstall_) onUninstall_();
    });

    cancelButton_.SetLabel(L"取消");
    cancelButton_.SetStyle(Button::Secondary);
    cancelButton_.SetOnClick([this]() {
        if (onCancel_) onCancel_();
    });

    // Tab 顺序 = 视觉顺序：修复 → 卸载 → 取消。
    host_.Add(&repairButton_);
    host_.Add(&uninstallButton_);
    host_.Add(&cancelButton_);

    UpdateButtonStates();
}

void MaintenancePage::BindAnimator(Animator* animator) {
    repairButton_.BindAnimator(animator);
    uninstallButton_.BindAnimator(animator);
    cancelButton_.BindAnimator(animator);
}

void MaintenancePage::BindText(const TextFactory* text) {
    text_ = text;
    repairButton_.BindText(text);
    uninstallButton_.BindText(text);
    cancelButton_.BindText(text);
}

void MaintenancePage::BindGlyphs(const GlyphFont* glyphs) {
    repairButton_.BindGlyphs(glyphs);
    uninstallButton_.BindGlyphs(glyphs);
    cancelButton_.BindGlyphs(glyphs);
}

void MaintenancePage::SetInfo(std::wstring installDir, std::wstring version, bool detected,
                              bool complete) {
    installDir_ = std::move(installDir);
    version_ = std::move(version);
    detected_ = detected;
    complete_ = complete;
    UpdateButtonStates();
    RelayoutIfReady();
}

void MaintenancePage::SetOnRepair(std::function<void()> cb) { onRepair_ = std::move(cb); }
void MaintenancePage::SetOnUninstall(std::function<void()> cb) { onUninstall_ = std::move(cb); }
void MaintenancePage::SetOnCancel(std::function<void()> cb) { onCancel_ = std::move(cb); }

void MaintenancePage::UpdateButtonStates() {
    // 未检测到安装时不允许修复（T11 通常已改用 Message 页，此处为兜底）。
    repairButton_.SetEnabled(detected_);
    uninstallButton_.SetEnabled(true);  // 部分安装的残留也应可清理
    cancelButton_.SetEnabled(true);
}

void MaintenancePage::RelayoutIfReady() {
    if (HasCard(card_)) Layout(card_);
}

void MaintenancePage::Layout(const D2D1_RECT_F& contentCard) {
    card_ = contentCard;
    const float pad = spacing::L;
    const float x0 = contentCard.left + pad;
    const float contentW = (contentCard.right - contentCard.left) - 2.0f * pad;
    const float cx = (contentCard.left + contentCard.right) * 0.5f;

    // 内容块总高：标题 + 副标题 + 路径 + 版本 + 状态 + 警示 + 按钮行。
    const float titleH = fontsize::Title + spacing::S;
    const float subtitleH = fontsize::Body + spacing::L;
    const float lineH = fontsize::Body + spacing::XS;
    const float statusH = fontsize::Caption + spacing::M;
    const float warningH = fontsize::Caption + spacing::S;
    const float blockH = titleH + subtitleH + lineH + lineH + statusH + warningH + kButtonH;

    const float cardH = contentCard.bottom - contentCard.top;
    float y = contentCard.top + std::max(pad, (cardH - blockH) * 0.5f);

    titleRect_ = D2D1::RectF(x0, y, x0 + contentW, y + titleH);
    y += titleH;

    subtitleRect_ = D2D1::RectF(x0, y, x0 + contentW, y + subtitleH);
    y += subtitleH;

    pathRect_ = D2D1::RectF(x0, y, x0 + contentW, y + lineH);
    y += lineH;

    versionRect_ = D2D1::RectF(x0, y, x0 + contentW, y + lineH);
    y += lineH;

    statusRect_ = D2D1::RectF(x0, y, x0 + contentW, y + statusH);
    y += statusH;

    warningRect_ = D2D1::RectF(x0, y, x0 + contentW, y + warningH);
    y += warningH;

    const float widths[3] = {kMaintenanceButtonW, kMaintenanceButtonW, kCancelButtonW};
    D2D1_RECT_F row[3];
    LayoutButtonRow(cx, y, widths, 3, spacing::M, row);
    repairRect_ = row[0];
    uninstallRect_ = row[1];
    cancelRect_ = row[2];

    repairButton_.SetBounds(repairRect_);
    uninstallButton_.SetBounds(uninstallRect_);
    cancelButton_.SetBounds(cancelRect_);
}

void MaintenancePage::Render(ID2D1DeviceContext* dc, const Theme& theme) {
    if (!dc) return;
    // 页坐标已是绝对值：恢复单位变换，避免叠加外壳 Translation(m, m)。
    dc->SetTransform(D2D1::Matrix3x2F::Identity());

    // 标题 / 副标题（T7 固定文案）。
    DrawLineText(dc, text_, L"Sopeek 维护", titleRect_, fontsize::Title,
                 weight::SemiBold, DWRITE_TEXT_ALIGNMENT_CENTER, theme.textPrimary);
    DrawLineText(dc, text_, L"修复程序文件，或卸载应用。你的文档和导出文件不会被删除。",
                 subtitleRect_, fontsize::Body, weight::Regular, DWRITE_TEXT_ALIGNMENT_CENTER,
                 theme.textSecondary);

    // 安装路径 / 版本（空值给稳定回退文案，绝不显示空白行）。
    const std::wstring pathText =
        installDir_.empty() ? L"安装位置：未检测到"
                            : (L"安装位置：" + PathField::MiddleEllipsize(installDir_, 20, 24));
    const std::wstring versionText =
        version_.empty() ? L"版本：未知" : (L"版本：" + version_);
    DrawLineText(dc, text_, pathText, pathRect_, fontsize::Body, weight::Regular,
                 DWRITE_TEXT_ALIGNMENT_LEADING, theme.textPrimary);
    DrawLineText(dc, text_, versionText, versionRect_, fontsize::Body, weight::Regular,
                 DWRITE_TEXT_ALIGNMENT_LEADING, theme.textSecondary);

    // 完整性状态：未检测到 / 不完整用警示色，完整用次级色。
    std::wstring statusText;
    bool statusWarn = false;
    if (!detected_) {
        statusText = L"未检测到已安装的 Sopeek，无法执行修复。";
        statusWarn = true;
    } else if (!complete_) {
        statusText = L"程序文件不完整，建议执行修复。";
        statusWarn = true;
    } else {
        statusText = L"已检测到完整的安装。";
    }
    DrawLineText(dc, text_, statusText, statusRect_, fontsize::Caption, weight::Regular,
                 DWRITE_TEXT_ALIGNMENT_LEADING,
                 statusWarn ? DangerColor() : theme.textSecondary);

    // 卸载警示（T7：卸载 = Secondary + 红色警示文字）。
    DrawLineText(dc, text_, L"卸载将移除程序文件与注册表项；用户数据默认保留，可在下一步选择删除。",
                 warningRect_, fontsize::Caption, weight::Regular, DWRITE_TEXT_ALIGNMENT_CENTER,
                 DangerColor());

    repairButton_.Render(dc, theme);
    uninstallButton_.Render(dc, theme);
    cancelButton_.Render(dc, theme);

    dc->SetTransform(D2D1::Matrix3x2F::Identity());
}

// ============================== UninstallConfirm 页（Page=6） ==============

UninstallConfirmPage::UninstallConfirmPage(AppState& state) : state_(state) {
    deleteUserData_.SetLabel(L"同时删除用户数据（设置、缓存、日志）");
    deleteUserData_.SetChecked(state_.deleteUserData);  // 默认 false
    deleteUserData_.SetOnToggle([this](bool value) {
        // 即时写回 AppState（§12），保证 Layout/SyncFromState 不回退用户选择。
        state_.deleteUserData = value;
    });

    confirmButton_.SetLabel(L"卸载");
    confirmButton_.SetStyle(Button::Accent);
    confirmButton_.SetOnClick([this]() {
        if (onConfirm_) onConfirm_();
    });

    cancelButton_.SetLabel(L"取消");
    cancelButton_.SetStyle(Button::Secondary);
    cancelButton_.SetOnClick([this]() {
        if (onCancel_) onCancel_();
    });

    // Tab 顺序 = 视觉顺序：复选框 → 卸载 → 取消。
    host_.Add(&deleteUserData_);
    host_.Add(&confirmButton_);
    host_.Add(&cancelButton_);
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
    const float pad = spacing::L;
    const float x0 = contentCard.left + pad;
    const float contentW = (contentCard.right - contentCard.left) - 2.0f * pad;
    const float cx = (contentCard.left + contentCard.right) * 0.5f;

    // 删除范围行（D15 C3 唯一模型）。
    const std::vector<std::wstring>& scope = ScopeLines();

    const float titleH = fontsize::Title + spacing::S;
    const float introH = fontsize::Body + spacing::M;
    const float headingH = fontsize::Subtitle + spacing::S;
    const float lineH = fontsize::Caption + spacing::XS;
    const float checkboxH = 28.0f;
    const float blockH = titleH + introH + headingH + lineH * static_cast<float>(scope.size()) +
                         spacing::M + checkboxH + spacing::M + kButtonH;

    const float cardH = contentCard.bottom - contentCard.top;
    float y = contentCard.top + std::max(pad, (cardH - blockH) * 0.5f);

    titleRect_ = D2D1::RectF(x0, y, x0 + contentW, y + titleH);
    y += titleH;

    introRect_ = D2D1::RectF(x0, y, x0 + contentW, y + introH);
    y += introH;

    headingRect_ = D2D1::RectF(x0, y, x0 + contentW, y + headingH);
    y += headingH;

    scopeRects_.clear();
    scopeRects_.reserve(scope.size());
    for (std::size_t i = 0; i < scope.size(); ++i) {
        scopeRects_.push_back(D2D1::RectF(x0, y, x0 + contentW, y + lineH));
        y += lineH;
    }
    y += spacing::M;

    checkboxRect_ = D2D1::RectF(x0, y, x0 + contentW, y + checkboxH);
    deleteUserData_.SetBounds(checkboxRect_);
    y += checkboxH + spacing::M;

    const float widths[2] = {kConfirmButtonW, kCancelButtonW};
    D2D1_RECT_F row[2];
    LayoutButtonRow(cx, y, widths, 2, spacing::M, row);
    confirmRect_ = row[0];
    cancelRect_ = row[1];
    confirmButton_.SetBounds(confirmRect_);
    cancelButton_.SetBounds(cancelRect_);

    SyncFromState();
}

void UninstallConfirmPage::Render(ID2D1DeviceContext* dc, const Theme& theme) {
    if (!dc) return;
    dc->SetTransform(D2D1::Matrix3x2F::Identity());

    DrawLineText(dc, text_, L"卸载 Sopeek", titleRect_, fontsize::Title,
                 weight::SemiBold, DWRITE_TEXT_ALIGNMENT_CENTER, theme.textPrimary);
    DrawLineText(dc, text_, L"将删除程序文件、快捷方式、注册表项。", introRect_,
                 fontsize::Body, weight::Regular, DWRITE_TEXT_ALIGNMENT_CENTER,
                 theme.textSecondary);
    DrawLineText(dc, text_, L"删除范围", headingRect_, fontsize::Subtitle, weight::SemiBold,
                 DWRITE_TEXT_ALIGNMENT_LEADING, theme.textPrimary);

    const std::vector<std::wstring>& scope = ScopeLines();
    for (std::size_t i = 0; i < scopeRects_.size() && i < scope.size(); ++i) {
        DrawLineText(dc, text_, scope[i], scopeRects_[i], fontsize::Caption, weight::Regular,
                     DWRITE_TEXT_ALIGNMENT_LEADING,
                     i == 0 ? theme.textPrimary : theme.textSecondary);
    }

    deleteUserData_.Render(dc, theme);
    confirmButton_.Render(dc, theme);
    cancelButton_.Render(dc, theme);

    dc->SetTransform(D2D1::Matrix3x2F::Identity());
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

    // Tab 顺序：主按钮 → 次按钮（空标签/ busy 时禁用，自动跳过）。
    host_.Add(&primaryButton_);
    host_.Add(&secondaryButton_);
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

    primaryButton_.SetLabel(primaryLabel_);
    secondaryButton_.SetLabel(secondaryLabel_);

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
}

void MessagePage::RelayoutIfReady() {
    if (HasCard(card_)) Layout(card_);
}

void MessagePage::Layout(const D2D1_RECT_F& contentCard) {
    card_ = contentCard;
    const float pad = spacing::L;
    const float x0 = contentCard.left + pad;
    const float contentW = (contentCard.right - contentCard.left) - 2.0f * pad;
    const float cx = (contentCard.left + contentCard.right) * 0.5f;

    const float titleH = fontsize::Title + spacing::S;
    const float bodyH = 96.0f;  // 正文区约 5 行（Body 14 DIP），超出部分由布局裁剪
    const float busyH = busy_ ? (fontsize::Body + spacing::M) : 0.0f;
    const float tailH = busy_ ? busyH : kButtonH;
    const float blockH = titleH + bodyH + spacing::M + tailH;

    const float cardH = contentCard.bottom - contentCard.top;
    float y = contentCard.top + std::max(pad, (cardH - blockH) * 0.5f);

    titleRect_ = D2D1::RectF(x0, y, x0 + contentW, y + titleH);
    y += titleH;

    bodyRect_ = D2D1::RectF(x0, y, x0 + contentW, y + bodyH);
    y += bodyH + spacing::M;

    busyRect_ = D2D1::RectF(x0, y, x0 + contentW, y + busyH);

    const bool showPrimary = PrimaryVisible();
    const bool showSecondary = SecondaryVisible();
    primaryRect_ = D2D1::RectF();
    secondaryRect_ = D2D1::RectF();

    if (showPrimary && showSecondary) {
        const float widths[2] = {kMessageSecondaryW, kMessagePrimaryW};
        D2D1_RECT_F row[2];
        LayoutButtonRow(cx, y, widths, 2, spacing::M, row);
        secondaryRect_ = row[0];
        primaryRect_ = row[1];
    } else if (showPrimary) {
        primaryRect_ = D2D1::RectF(cx - kMessagePrimaryW * 0.5f, y,
                                   cx + kMessagePrimaryW * 0.5f, y + kButtonH);
    } else if (showSecondary) {
        secondaryRect_ = D2D1::RectF(cx - kMessageSecondaryW * 0.5f, y,
                                     cx + kMessageSecondaryW * 0.5f, y + kButtonH);
    }

    primaryButton_.SetBounds(primaryRect_);
    secondaryButton_.SetBounds(secondaryRect_);
}

void MessagePage::Render(ID2D1DeviceContext* dc, const Theme& theme) {
    if (!dc) return;
    dc->SetTransform(D2D1::Matrix3x2F::Identity());

    DrawLineText(dc, text_, title_, titleRect_, fontsize::Title, weight::SemiBold,
                 DWRITE_TEXT_ALIGNMENT_CENTER, theme.textPrimary);
    DrawBlockText(dc, text_, body_, bodyRect_, fontsize::Body, weight::Regular,
                  DWRITE_TEXT_ALIGNMENT_LEADING, theme.textSecondary);

    // busy：只显示正文 + 状态行，按钮隐藏（不渲染）。
    if (busy_) {
        DrawLineText(dc, text_, busyText_, busyRect_, fontsize::Body, weight::Regular,
                     DWRITE_TEXT_ALIGNMENT_CENTER, theme.accent);
    } else {
        if (PrimaryVisible()) primaryButton_.Render(dc, theme);
        if (SecondaryVisible()) secondaryButton_.Render(dc, theme);
    }

    dc->SetTransform(D2D1::Matrix3x2F::Identity());
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
