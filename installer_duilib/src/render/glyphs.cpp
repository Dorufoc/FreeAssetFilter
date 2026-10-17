//
// glyphs.cpp - Fluent 字形封装实现。
//
#include "render/glyphs.h"

namespace faf {

bool GlyphFont::FamilyExists(IDWriteFactory* factory, const wchar_t* family) {
    if (!factory || !family || !*family) return false;
    IDWriteFontCollection* collection = nullptr;
    if (FAILED(factory->GetSystemFontCollection(&collection, FALSE)) || !collection) return false;
    UINT32 index = 0;
    BOOL found = FALSE;
    const HRESULT hr = collection->FindFamilyName(family, &index, &found);
    collection->Release();
    return SUCCEEDED(hr) && found;
}

bool GlyphFont::FamilyHasCodepoint(IDWriteFactory* factory, const wchar_t* family,
                                   wchar_t codepoint) {
    if (!factory || !family || !*family) return false;

    IDWriteFontCollection* collection = nullptr;
    if (FAILED(factory->GetSystemFontCollection(&collection, FALSE)) || !collection) return false;

    bool result = false;
    UINT32 index = 0;
    BOOL found = FALSE;
    if (SUCCEEDED(collection->FindFamilyName(family, &index, &found)) && found) {
        IDWriteFontFamily* fontFamily = nullptr;
        if (SUCCEEDED(collection->GetFontFamily(index, &fontFamily)) && fontFamily) {
            IDWriteFont* font = nullptr;
            if (SUCCEEDED(fontFamily->GetFirstMatchingFont(
                    DWRITE_FONT_WEIGHT_NORMAL, DWRITE_FONT_STRETCH_NORMAL, DWRITE_FONT_STYLE_NORMAL,
                    &font)) &&
                font) {
                IDWriteFontFace* face = nullptr;
                if (SUCCEEDED(font->CreateFontFace(&face)) && face) {
                    const UINT32 codePoint = static_cast<UINT32>(codepoint);
                    UINT16 glyphIndex = 0;
                    if (SUCCEEDED(face->GetGlyphIndices(&codePoint, 1, &glyphIndex))) {
                        result = glyphIndex != 0;  // 0 ⇒ 该字体无此码点字形
                    }
                    face->Release();
                }
                font->Release();
            }
            fontFamily->Release();
        }
    }

    collection->Release();
    return result;
}

HRESULT GlyphFont::Initialize(IDWriteFactory* factory, const wchar_t* preferred,
                              const wchar_t* fallback) {
    factory_ = factory;
    family_.clear();
    if (!factory_) return E_POINTER;

    if (FamilyExists(factory, preferred)) {
        family_ = preferred;
    } else if (fallback && *fallback) {
        // 即便 fallback 也不存在，仍采用其名；DWrite 会回退到默认族，不会失败。
        family_ = fallback;
    } else {
        family_ = L"Segoe MDL2 Assets";  // 最终兜底
    }
    return S_OK;
}

bool GlyphFont::HasCodepoint(wchar_t codepoint) const {
    return FamilyHasCodepoint(factory_, family_.c_str(), codepoint);
}

HRESULT GlyphFont::CreateFormat(float sizeDip, IDWriteTextFormat** out) const {
    if (!factory_ || !out) return E_POINTER;
    *out = nullptr;
    return factory_->CreateTextFormat(family_.c_str(), nullptr, DWRITE_FONT_WEIGHT_NORMAL,
                                      DWRITE_FONT_STYLE_NORMAL, DWRITE_FONT_STRETCH_NORMAL, sizeDip,
                                      L"en-US", out);
}

}  // namespace faf
