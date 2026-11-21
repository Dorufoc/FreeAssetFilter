#include "render/license_sheet.h"

#include <d2d1_1helper.h>
#include <utility>

#include "render/layout.h"
#include "render/pages_welcome.h"
#include "render/render_context.h"

namespace spk {

LicenseSheet::LicenseSheet() {
    backButton_.SetLabel(L"返回");
    backButton_.SetStyle(Button::Accent);
    host_.Add(&box_);
    host_.Add(&backButton_);
}

void LicenseSheet::BindText(const TextFactory* text) {
    text_ = text;
    box_.BindText(text);
    backButton_.BindText(text);
}

void LicenseSheet::BindAnimator(Animator* animator) {
    box_.BindAnimator(animator);
    backButton_.BindAnimator(animator);
}

void LicenseSheet::SetContent(std::wstring title, std::wstring body) {
    title_ = std::move(title);
    box_.SetText(std::move(body));
}

void LicenseSheet::Layout(const D2D1_RECT_F& contentCard) {
    card_ = contentCard;
    const float left = layout::kContentLeft;
    const float right = left + layout::kContentWidth;
    titleRect_ = BaselineRect(left, right, design::kPageTitleBaselineY, fontsize::PageTitle);
    box_.SetBounds(D2D1::RectF(left, titleRect_.bottom + spacing::M, right,
                              design::kButtonTop - spacing::L));
    backButton_.SetBounds(D2D1::RectF(design::kButtonLeft, design::kButtonTop,
                                     design::kButtonLeft + design::kButtonWidth,
                                     design::kButtonTop + design::kButtonHeight));
}

void LicenseSheet::Enter() {
    host_.CancelPointer();
    box_.SetScrollOffset(0.0f);
    host_.FocusWidget(&box_);
}

void LicenseSheet::Render(ID2D1DeviceContext* dc, const Theme& theme) {
    if (!dc) return;
    const auto offset = PageOffsetDip(card_);
    D2D1_MATRIX_3X2_F parent{};
    dc->GetTransform(&parent);
    dc->SetTransform(D2D1::Matrix3x2F::Translation(offset.x, offset.y) * parent);

    if (text_ && text_->IsReady() && !title_.empty()) {
        ComPtr<IDWriteTextFormat> format;
        ComPtr<ID2D1SolidColorBrush> ink;
        if (SUCCEEDED(text_->CreateFormat(fontsize::PageTitle, weight::Bold,
                                          DWRITE_TEXT_ALIGNMENT_LEADING,
                                          DWRITE_PARAGRAPH_ALIGNMENT_CENTER,
                                          format.GetAddressOf())) &&
            SUCCEEDED(dc->CreateSolidColorBrush(theme.textPrimary, ink.GetAddressOf()))) {
            format->SetWordWrapping(DWRITE_WORD_WRAPPING_NO_WRAP);
            dc->DrawText(title_.c_str(), static_cast<UINT32>(title_.size()), format.Get(),
                         titleRect_, ink.Get(), D2D1_DRAW_TEXT_OPTIONS_CLIP);
        }
    }
    box_.Render(dc, theme);
    backButton_.Render(dc, theme);
    dc->SetTransform(parent);
}

}  // namespace spk
