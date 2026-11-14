//
// text.cpp - DirectWrite 排版封装实现。
//
#include "render/text.h"

namespace spk {

namespace {

// 查询系统字体集合是否包含指定族名。collection 为借出指针，不释放。
bool CollectionHasFamily(IDWriteFontCollection* collection, const wchar_t* family) {
    if (!collection || !family || !*family) return false;
    UINT32 index = 0;
    BOOL found = FALSE;
    return SUCCEEDED(collection->FindFamilyName(family, &index, &found)) && found;
}

}  // namespace

HRESULT TextFactory::Initialize(IDWriteFactory* factory, const wchar_t* preferred,
                                const wchar_t* fallback) {
    factory_ = factory;
    family_.clear();
    preferredFound_ = false;
    if (!factory_) return E_POINTER;

    IDWriteFontCollection* collection = nullptr;
    HRESULT hr = factory_->GetSystemFontCollection(&collection, FALSE);
    if (FAILED(hr) || !collection) return hr;

    if (CollectionHasFamily(collection, preferred)) {
        preferredFound_ = true;
        family_ = preferred;
    } else if (fallback && *fallback) {
        // 即便 fallback 也不存在，仍采用其名；DWrite 会回退到默认族，不会失败。
        family_ = fallback;
    } else {
        family_ = L"Segoe UI";  // 最终兜底
    }

    collection->Release();
    return S_OK;
}

bool TextFactory::HasFamily(const wchar_t* family) const {
    if (!factory_) return false;
    IDWriteFontCollection* collection = nullptr;
    if (FAILED(factory_->GetSystemFontCollection(&collection, FALSE)) || !collection) return false;
    const bool found = CollectionHasFamily(collection, family);
    collection->Release();
    return found;
}

HRESULT TextFactory::CreateFormat(float sizeDip, DWRITE_FONT_WEIGHT weight,
                                  DWRITE_TEXT_ALIGNMENT align, DWRITE_PARAGRAPH_ALIGNMENT paragraph,
                                  IDWriteTextFormat** out) const {
    if (!factory_ || !out) return E_POINTER;
    *out = nullptr;

    IDWriteTextFormat* format = nullptr;
    // locale 用 zh-CN：族缺 CJK 字形时，DWrite 的字形回退据此选择中文回退字体。
    const HRESULT hr =
        factory_->CreateTextFormat(family_.c_str(), nullptr, weight, DWRITE_FONT_STYLE_NORMAL,
                                   DWRITE_FONT_STRETCH_NORMAL, sizeDip, L"zh-CN", &format);
    if (FAILED(hr)) return hr;

    format->SetTextAlignment(align);
    format->SetParagraphAlignment(paragraph);
    format->SetWordWrapping(DWRITE_WORD_WRAPPING_WRAP);
    *out = format;
    return S_OK;
}

HRESULT TextFactory::CreateFormat(float sizeDip, DWRITE_FONT_WEIGHT weight,
                                  IDWriteTextFormat** out) const {
    return CreateFormat(sizeDip, weight, DWRITE_TEXT_ALIGNMENT_LEADING,
                        DWRITE_PARAGRAPH_ALIGNMENT_NEAR, out);
}

}  // namespace spk
