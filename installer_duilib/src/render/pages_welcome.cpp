//
// pages_welcome.cpp - 安装向导页面①「欢迎」与页面②「许可协议」实现（Todo 9）。
//
// 关键点（Frozen contracts）：
//   §12 页面状态一律读写 AppState（许可同意直接写 state_.agreed；「下一步」仅由此门控）。
//   §13 视觉只消费 theme.h token；RCDATA 资源行 append-only（app.rc 由本 todo 追加）。
//   §18 版本字符串只取根 FAFVERSION 首行、去掉前导 'v'——绝不硬编码。
//   §6  坐标全程 DIP（不乘 DPI）。
// 页面切换动效 = 淡入 + 轻微上移：由注入的 Animator 的 AnimValue 驱动（页面不自持
// 帧时钟；无 Animator 时 EnterProgress() 退回终值 1）。
//
#include "render/pages_welcome.h"

#include <d2d1_1helper.h>

#include <algorithm>
#include <cstddef>

#include "render/render_context.h"  // faf::ComPtr

namespace faf {

namespace {

// 页面切换动效：时长（ms）与最大上移偏移（DIP）。
constexpr float kEnterMs = 260.0f;
constexpr float kSlideDip = 16.0f;

constexpr float kLogoSize = 96.0f;
// UI-fix：kButtonW 已删除（页内「开始」/「下一步」按钮移除后无引用）；kButtonH 仍用于许可行高。
constexpr float kButtonH = 36.0f;

// 按比例缩放主题全部颜色的 alpha（页面淡入用；不改其它通道）。
Theme ScaleAlpha(const Theme& t, float a) {
    Theme out = t;
    out.card.a = t.card.a * a;
    out.cardStroke.a = t.cardStroke.a * a;
    out.textPrimary.a = t.textPrimary.a * a;
    out.textSecondary.a = t.textSecondary.a * a;
    out.accent.a = t.accent.a * a;
    out.hover.a = t.hover.a * a;
    out.pressed.a = t.pressed.a * a;
    out.divider.a = t.divider.a * a;
    return out;
}

// 单行文字（NoWrap）。走 TextFactory 的族探测（非硬编码族名）。
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

// 单个 Fluent 字形（码点只允许来自 glyphs.h）。
void DrawGlyph(ID2D1DeviceContext* dc, const GlyphFont* gf, wchar_t codepoint,
               const D2D1_RECT_F& rect, float size, const D2D1_COLOR_F& color) {
    if (!dc || !gf || !gf->IsReady()) return;
    ComPtr<IDWriteTextFormat> fmt;
    if (FAILED(gf->CreateFormat(size, fmt.GetAddressOf()))) return;
    fmt->SetTextAlignment(DWRITE_TEXT_ALIGNMENT_CENTER);
    fmt->SetParagraphAlignment(DWRITE_PARAGRAPH_ALIGNMENT_CENTER);
    ComPtr<ID2D1SolidColorBrush> brush;
    if (FAILED(dc->CreateSolidColorBrush(color, brush.GetAddressOf()))) return;
    const wchar_t s[2] = {codepoint, 0};
    dc->DrawText(s, 1, fmt.Get(), rect, brush.Get());
}

}  // namespace

// ============================== 资源读取 ===================================

bool ReadUtf8Resource(UINT resourceId, std::wstring& out) {
    out.clear();
    // RT_RCDATA 是 MAKEINTRESOURCE(10)，非 UNICODE 编译单元里是窄宏；显式转宽。
    const HRSRC res = FindResourceW(nullptr, MAKEINTRESOURCEW(resourceId),
                                    reinterpret_cast<LPCWSTR>(RT_RCDATA));
    if (!res) return false;
    const DWORD size = SizeofResource(nullptr, res);
    if (size == 0) return false;
    HGLOBAL handle = LoadResource(nullptr, res);
    if (!handle) return false;
    const BYTE* bytes = static_cast<const BYTE*>(LockResource(handle));
    if (!bytes) return false;

    DWORD offset = 0;
    if (size >= 3 && bytes[0] == 0xEF && bytes[1] == 0xBB && bytes[2] == 0xBF) offset = 3;
    const int len = static_cast<int>(size - offset);
    if (len <= 0) return false;

    const int wlen = MultiByteToWideChar(CP_UTF8, 0, reinterpret_cast<const char*>(bytes + offset),
                                         len, nullptr, 0);
    if (wlen <= 0) return false;
    out.resize(static_cast<std::size_t>(wlen));
    MultiByteToWideChar(CP_UTF8, 0, reinterpret_cast<const char*>(bytes + offset), len, out.data(),
                        wlen);
    return true;
}

std::wstring ReadVersionString() {
    std::wstring text;
    if (!ReadUtf8Resource(IDR_FAFVERSION, text)) return std::wstring();
    const std::size_t nl = text.find_first_of(L"\r\n");
    std::wstring line = (nl == std::wstring::npos) ? text : text.substr(0, nl);
    const wchar_t* ws = L" \t\r\n";
    const std::size_t b = line.find_first_not_of(ws);
    if (b == std::wstring::npos) return std::wstring();
    const std::size_t e = line.find_last_not_of(ws);
    line = line.substr(b, e - b + 1);
    if (!line.empty() && (line[0] == L'v' || line[0] == L'V')) line.erase(0, 1);
    return line;
}

std::vector<std::wstring> LicenseSummaryLines() {
    return {
        L"本程序是自由软件，可依据 AGPL-3.0（或任何更新版本）条款自由使用、修改与再分发。",
        L"本程序按「现状」分发，不提供任何明示或默示担保（含适销性与特定用途适用性）。",
        L"你应已收到 AGPL-3.0 副本；如未收到，请访问 https://www.gnu.org/licenses/ 。",
    };
}

// ============================== 页面① 欢迎 =================================

WelcomePage::WelcomePage(AppState& state) : state_(state) {
    enterName_ = "page-welcome-enter";
    version_ = ReadVersionString();  // §18：只取 FAFVERSION 首行去 'v'，不硬编码
    tagline_ = L"让文件浏览如丝般高效顺滑";
    highlights_ = {
        L"支持 100+ 种文件格式预览",
        L"三栏布局，高效工作流",
        L"深色 / 浅色主题随意切换",
        L"高性能原生扩展，流畅不卡顿",
    };

    // UI-fix：页内「开始」按钮已移除——前进统一走外壳底部条「下一步」（避免重复按钮）。
}

void WelcomePage::BindAnimator(Animator* animator) {
    animator_ = animator;
    StartIntro();
}

void WelcomePage::BindText(const TextFactory* text) {
    text_ = text;
}

void WelcomePage::BindGlyphs(const GlyphFont* glyphs) {
    glyphs_ = glyphs;
}

void WelcomePage::StartIntro() {
    if (!animator_) {
        enterAnim_ = nullptr;
        return;
    }
    enterAnim_ = &animator_->Animate(enterName_, 0.0f, 1.0f, kEnterMs, easing::Entrance);
}

void WelcomePage::ResetIntro() { StartIntro(); }

float WelcomePage::EnterProgress() const {
    if (!enterAnim_) return 1.0f;
    return std::clamp(enterAnim_->Value(), 0.0f, 1.0f);
}

float WelcomePage::EnterOffsetDip() const { return (1.0f - EnterProgress()) * kSlideDip; }

void WelcomePage::SyncFromState() { (void)state_; }  // 欢迎页无输入字段，接口保持对称

void WelcomePage::Layout(const D2D1_RECT_F& contentCard) {
    card_ = contentCard;
    const float pad = spacing::L;
    const float x0 = contentCard.left + pad;
    const float contentW = (contentCard.right - contentCard.left) - 2.0f * pad;
    const float cx = contentCard.left + (contentCard.right - contentCard.left) * 0.5f;

    // UI-fix：内容块垂直居中（原先固定贴顶 contentCard.top + pad，短内容在卡内显得下坠）。
    // 块高 = Logo + 名称 + 版本号 + 标语 + 亮点行数（末行之后不计间距）。
    const float blockH = kLogoSize + spacing::L + (fontsize::Title + spacing::S) +
                         (fontsize::Body + spacing::XS) + (fontsize::Body + spacing::L) +
                         highlights_.size() * (fontsize::Body + spacing::S);
    const float cardH = contentCard.bottom - contentCard.top;
    float y = contentCard.top + std::max(spacing::L, (cardH - blockH) * 0.5f);

    logoRect_ = D2D1::RectF(cx - kLogoSize * 0.5f, y, cx + kLogoSize * 0.5f, y + kLogoSize);
    y += kLogoSize + spacing::L;

    nameRect_ = D2D1::RectF(x0, y, x0 + contentW, y + fontsize::Title + spacing::S);
    y += fontsize::Title + spacing::S;

    versionRect_ = D2D1::RectF(x0, y, x0 + contentW, y + fontsize::Body + spacing::XS);
    y += fontsize::Body + spacing::XS;

    taglineRect_ = D2D1::RectF(x0, y, x0 + contentW, y + fontsize::Body + spacing::L);
    y += fontsize::Body + spacing::L;

    highlightRects_.clear();
    for (std::size_t i = 0; i < highlights_.size(); ++i) {
        highlightRects_.push_back(D2D1::RectF(x0, y, x0 + contentW, y + fontsize::Body));
        y += fontsize::Body + spacing::S;
    }

    // UI-fix：页内「开始」按钮已删除——前进由外壳底部条「下一步」承担（避免重复按钮）。
}

void WelcomePage::Render(ID2D1DeviceContext* dc, const Theme& theme) {
    if (!dc) return;
    const float p = EnterProgress();
    const float alpha = p;
    const float dy = EnterOffsetDip();
    const Theme t = ScaleAlpha(theme, alpha);

    // 页面切换动效：整体上移 dy（起步时更低、渐入到位）。
    dc->SetTransform(D2D1::Matrix3x2F::Translation(0.0f, -dy));

    if (logo_ && logo_->IsLoaded()) {
        dc->DrawBitmap(logo_->Bitmap(), logoRect_, alpha, D2D1_BITMAP_INTERPOLATION_MODE_LINEAR);
    } else {
        ComPtr<ID2D1SolidColorBrush> b;
        if (SUCCEEDED(dc->CreateSolidColorBrush(t.accent, b.GetAddressOf()))) {
            dc->FillRoundedRectangle(D2D1::RoundedRect(logoRect_, radius::Large, radius::Large),
                                     b.Get());
        }
        DrawGlyph(dc, glyphs_, glyph::Download, logoRect_, 40.0f, t.textPrimary);
    }

    DrawText(dc, text_, productName_, nameRect_, fontsize::Title, weight::SemiBold,
             DWRITE_TEXT_ALIGNMENT_CENTER, t.textPrimary);

    const std::wstring verText =
        version_.empty() ? L"版本：未知（FAFVERSION 资源缺失）" : (L"版本 " + version_);
    DrawText(dc, text_, verText, versionRect_, fontsize::Body, weight::Regular,
             DWRITE_TEXT_ALIGNMENT_CENTER, t.textSecondary);
    DrawText(dc, text_, tagline_, taglineRect_, fontsize::Body, weight::Regular,
             DWRITE_TEXT_ALIGNMENT_CENTER, t.textSecondary);

    for (std::size_t i = 0; i < highlightRects_.size() && i < highlights_.size(); ++i) {
        const D2D1_RECT_F& r = highlightRects_[i];
        const float gh = r.bottom - r.top;
        const D2D1_RECT_F glyphRect = D2D1::RectF(r.left, r.top, r.left + gh, r.bottom);
        DrawGlyph(dc, glyphs_, glyph::Check, glyphRect, fontsize::Body, t.accent);
        const D2D1_RECT_F textRect =
            D2D1::RectF(r.left + gh + spacing::S, r.top, r.right, r.bottom);
        DrawText(dc, text_, highlights_[i], textRect, fontsize::Body, weight::Regular,
                 DWRITE_TEXT_ALIGNMENT_LEADING, t.textSecondary);
    }

    // UI-fix：页内「开始」按钮已删除（外壳底部条承担前进）。
    dc->SetTransform(D2D1::Matrix3x2F::Identity());
}

bool WelcomePage::HitTest(float x, float y) const {
    return x >= card_.left && x <= card_.right && y >= card_.top && y <= card_.bottom;
}

bool WelcomePage::OnInput(const InputEvent& event) { return host_.Dispatch(event); }

// ============================== 页面② 许可协议 =============================

LicensePage::LicensePage(AppState& state) : state_(state) {
    enterName_ = "page-license-enter";
    summary_ = LicenseSummaryLines();

    std::wstring license;
    if (ReadUtf8Resource(IDR_LICENSE, license) && !license.empty()) {
        box_.SetText(std::move(license));
        licenseLoaded_ = true;
    } else {
        // 资源缺失/为空：内联错误 + 空文本（LicenseBox::SetText 空文本安全，不崩）。
        licenseError_ = L"无法加载许可协议内容（LICENSE 资源缺失或为空）。";
        box_.SetText(std::wstring());
        licenseLoaded_ = false;
    }

    agree_.SetLabel(L"我已阅读并同意《GNU Affero 通用公共许可证》条款");
    agree_.SetOnToggle([this](bool v) {
        state_.agreed = v;  // §12：直接写 AppState（「下一步」门控由外壳 UpdateNavButtons 读取）
    });

    // UI-fix：页内「下一步」按钮已移除——门控（state_.agreed）由外壳底部条统一处理。
    host_.Add(&box_);  // 许可框（滚轮/拖拽/键盘滚动）
    host_.Add(&agree_);

    SyncFromState();
}

// UI-fix：页内「下一步」门控辅助函数已随按钮移除而删除（门控改由外壳导航统一处理）。
void LicensePage::BindAnimator(Animator* animator) {
    animator_ = animator;
    box_.BindAnimator(animator);
    agree_.BindAnimator(animator);
    StartIntro();
}

void LicensePage::BindText(const TextFactory* text) {
    text_ = text;
    box_.BindText(text);
    agree_.BindText(text);
}

void LicensePage::BindGlyphs(const GlyphFont* glyphs) {
    glyphs_ = glyphs;
    agree_.BindGlyphs(glyphs);
}

void LicensePage::BindWriteFactory(IDWriteFactory* factory) { box_.BindWriteFactory(factory); }

void LicensePage::StartIntro() {
    if (!animator_) {
        enterAnim_ = nullptr;
        return;
    }
    enterAnim_ = &animator_->Animate(enterName_, 0.0f, 1.0f, kEnterMs, easing::Entrance);
}

void LicensePage::ResetIntro() { StartIntro(); }

float LicensePage::EnterProgress() const {
    if (!enterAnim_) return 1.0f;
    return std::clamp(enterAnim_->Value(), 0.0f, 1.0f);
}

float LicensePage::EnterOffsetDip() const { return (1.0f - EnterProgress()) * kSlideDip; }

void LicensePage::SyncFromState() {
    agree_.SetChecked(state_.agreed);
}

void LicensePage::Layout(const D2D1_RECT_F& contentCard) {
    card_ = contentCard;
    const float pad = spacing::L;
    const float x0 = contentCard.left + pad;
    const float contentW = (contentCard.right - contentCard.left) - 2.0f * pad;

    float y = contentCard.top + pad;
    titleRect_ = D2D1::RectF(x0, y, x0 + contentW, y + fontsize::Subtitle + spacing::S);
    y += fontsize::Subtitle + spacing::S;

    summaryRects_.clear();
    for (std::size_t i = 0; i < summary_.size(); ++i) {
        summaryRects_.push_back(D2D1::RectF(x0, y, x0 + contentW, y + fontsize::Caption + spacing::XS));
        y += fontsize::Caption + spacing::XS;
    }
    y += spacing::S;

    const float rowH = kButtonH;
    const float bottom = contentCard.bottom - pad;
    const float boxTop = y;
    const float boxBottom = bottom - rowH - spacing::M;
    box_.SetBounds(D2D1::RectF(x0, boxTop, x0 + contentW, boxBottom));

    // UI-fix：勾选项横跨整行（页内「下一步」按钮已删除，不再预留按钮槽）。
    agree_.SetBounds(D2D1::RectF(x0, bottom - rowH, x0 + contentW, bottom));

    errorRect_ = D2D1::RectF(x0 + spacing::S, boxTop + spacing::S, x0 + contentW - spacing::S,
                             boxTop + fontsize::Body + 2.0f * spacing::S);

    SyncFromState();
}

void LicensePage::Render(ID2D1DeviceContext* dc, const Theme& theme) {
    if (!dc) return;
    const float p = EnterProgress();
    const float alpha = p;
    const float dy = EnterOffsetDip();
    const Theme t = ScaleAlpha(theme, alpha);

    dc->SetTransform(D2D1::Matrix3x2F::Translation(0.0f, -dy));

    DrawText(dc, text_, L"许可协议", titleRect_, fontsize::Subtitle, weight::SemiBold,
             DWRITE_TEXT_ALIGNMENT_LEADING, t.textPrimary);

    for (std::size_t i = 0; i < summaryRects_.size() && i < summary_.size(); ++i) {
        DrawText(dc, text_, summary_[i], summaryRects_[i], fontsize::Caption, weight::Regular,
                 DWRITE_TEXT_ALIGNMENT_LEADING, t.textSecondary);
    }

    box_.Render(dc, t);

    if (!licenseError_.empty()) {
        const D2D1_COLOR_F red = D2D1::ColorF(0.85f, 0.20f, 0.20f, alpha);
        DrawText(dc, text_, licenseError_, errorRect_, fontsize::Body, weight::Regular,
                 DWRITE_TEXT_ALIGNMENT_LEADING, red);
    }

    agree_.Render(dc, t);
    // UI-fix：页内「下一步」按钮已删除（外壳底部条承担）。
    dc->SetTransform(D2D1::Matrix3x2F::Identity());
}

bool LicensePage::HitTest(float x, float y) const {
    return x >= card_.left && x <= card_.right && y >= card_.top && y <= card_.bottom;
}

bool LicensePage::OnInput(const InputEvent& event) { return host_.Dispatch(event); }

// ============================== Todo 12 接线入口 ===========================

void RenderWelcome(ID2D1DeviceContext* dc, const Theme& theme, WelcomePage& page) {
    page.Render(dc, theme);
}

void RenderLicense(ID2D1DeviceContext* dc, const Theme& theme, LicensePage& page) {
    page.Render(dc, theme);
}

}  // namespace faf
