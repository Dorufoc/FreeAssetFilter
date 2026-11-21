//
// pages_welcome.cpp - 安装向导页面①「英雄页 / 欢迎」实现。
//
// 视觉依据：src/sopeek/resources/icons/install_design/英雄页.svg。
// 关键点（Frozen contracts）：
//   §12 页面状态一律读写 AppState。
//   §13 视觉只消费 theme.h token；RCDATA 资源行 append-only（app.rc 已同步）。
//   §18 版本字符串只取根 SPKVERSION 首行、去掉前导 'v'——绝不硬编码。
//   §6  坐标全程 DIP（不乘 DPI）。
//
#include "render/pages_welcome.h"

#include <d2d1_1helper.h>

#include <algorithm>
#include <cstddef>

#include "render/hero_art.h"
#include "render/layout.h"          // layout::* / PageOffsetDip
#include "render/logo.h"            // LogoBitmap（英雄页背景图）
#include "render/render_context.h"  // spk::ComPtr

namespace spk {

namespace {

// 页面切换动效：时长（ms）与最大上移偏移（DIP）。设计稿未定义动效；保留原有淡入
// （减少动画时由 Animator::SetReduceMotion 直接给终值）。

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
    if (!ReadUtf8Resource(IDR_SPKVERSION, text)) return std::wstring();
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

// ============================== 页面① 英雄页 ===============================

WelcomePage::WelcomePage(AppState& state) : state_(state) {
    version_ = ReadVersionString();  // §18：只取 SPKVERSION 首行去 'v'，不硬编码
    tagline_ = L"全能 · 高效 · 开源";

    nextButton_.SetLabel(L"下一步");
    nextButton_.SetStyle(Button::Accent);
    nextButton_.SetTrailingChevron(true);  // 设计稿：主按钮文字右侧带「>」
    nextButton_.SetOnClick([this]() {
        if (onNextIntent_) onNextIntent_();
    });
    host_.Add(&nextButton_);
}

void WelcomePage::BindAnimator(Animator* animator) {
    nextButton_.BindAnimator(animator);
}

void WelcomePage::BindText(const TextFactory* text) {
    text_ = text;
    nextButton_.BindText(text);
}

void WelcomePage::BindGlyphs(const GlyphFont* glyphs) {
    glyphs_ = glyphs;
    nextButton_.BindGlyphs(glyphs);
}

void WelcomePage::SyncFromState() { (void)state_; }  // 欢迎页无输入字段

void WelcomePage::Layout(const D2D1_RECT_F& contentCard) {
    card_ = contentCard;
    // 设计稿是绝对坐标：所有文字以窗口中心 x=320 为锚点居中（tspan 负偏移 = 半字宽）。
    taglineRect_ = CenteredBaselineRect(layout::kCanvasWidth * 0.5f, design::kTaglineBaselineY,
                                        fontsize::Tagline);
    titleRect_ = CenteredBaselineRect(layout::kCanvasWidth * 0.5f, design::kHeroTitleBaselineY,
                                      fontsize::PageTitle);
    nextButton_.SetBounds(D2D1::RectF(design::kButtonLeft, design::kButtonTop,
                                      design::kButtonLeft + design::kButtonWidth,
                                      design::kButtonTop + design::kButtonHeight));
    SyncFromState();
}

bool DrawHeroBackground(ID2D1DeviceContext* dc, const LogoBitmap* background, float alpha) {
    if (!dc || !background || !background->IsLoaded()) return false;
    const auto dst = D2D1::RectF(hero_bg::kOffsetX, hero_bg::kOffsetY,
                                hero_bg::kOffsetX + hero_bg::kDrawWidth,
                                hero_bg::kOffsetY + hero_bg::kDrawHeight);
    dc->PushAxisAlignedClip(D2D1::RectF(0.0f, 0.0f, layout::kCanvasWidth, layout::kCanvasHeight),
                            D2D1_ANTIALIAS_MODE_PER_PRIMITIVE);
    dc->DrawBitmap(background->Bitmap(), dst, alpha, D2D1_BITMAP_INTERPOLATION_MODE_LINEAR);
    dc->PopAxisAlignedClip();
    return true;
}

void WelcomePage::Render(ID2D1DeviceContext* dc, const Theme& theme) {
    if (!dc) return;
    const D2D1_POINT_2F o = PageOffsetDip(card_);
    D2D1_MATRIX_3X2_F parent{};
    dc->GetTransform(&parent);
    dc->SetTransform(D2D1::Matrix3x2F::Translation(o.x, o.y) * parent);

    if (!DrawHeroBackground(dc, background_)) {
        DrawHeroArtwork(dc, art_, nullptr, theme, 1.0f);
    }

    // 「全能 · 高效 · 开源」24px / 39% 黑
    DrawText(dc, text_, tagline_, taglineRect_, fontsize::Tagline, weight::Regular,
             DWRITE_TEXT_ALIGNMENT_CENTER, theme.muted);
    // 「文件管理器」32px bold
    DrawText(dc, text_, L"文件管理器", titleRect_, fontsize::PageTitle, weight::Bold,
             DWRITE_TEXT_ALIGNMENT_CENTER, theme.textPrimary);

    nextButton_.Render(dc, theme);

    dc->SetTransform(D2D1::Matrix3x2F::Identity());
}

bool WelcomePage::HitTest(float x, float y) const {
    return x >= card_.left && x <= card_.right && y >= card_.top && y <= card_.bottom;
}

bool WelcomePage::OnInput(const InputEvent& event) { return host_.Dispatch(event); }

// ============================== 接线入口 ===================================

void DrawHeroArtwork(ID2D1DeviceContext* dc, const HeroArt* art, const LogoBitmap* background,
                     const Theme& theme, float alpha) {
    if (!dc) return;
    // 品牌位图不可用时，使用内置矢量图。
    if (art && art->IsReady()) {
        art->RenderHeroArt(dc, theme, alpha);
        return;
    }
    if (background && background->IsLoaded()) {
        DrawHeroBackground(dc, background, alpha);
    }
}

void RenderWelcome(ID2D1DeviceContext* dc, const Theme& theme, WelcomePage& page) {
    page.Render(dc, theme);
}

}  // namespace spk
