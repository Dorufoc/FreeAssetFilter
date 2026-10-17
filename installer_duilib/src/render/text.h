#pragma once
//
// text.h - DirectWrite 排版封装（本安装器唯一的 UI 字体族解析入口）。
//
// 优先 "Segoe UI Variable Text"，缺失时回退 "Segoe UI"（经系统字体集合
// IDWriteFontCollection::FindFamilyName 探测）。CreateTextFormat 对缺失族名
// 不会失败（DWrite 内部回退到默认族），故任何情况下都不会崩。
//
// 不拥有传入的 IDWriteFactory；复用 RenderContext 的共享 DWrite 工厂。
//
#include <windows.h>

#include <dwrite.h>

#include <string>

namespace faf {

class TextFactory {
public:
    // 绑定 DWrite 工厂并解析 UI 字体族。preferred/fallback 可覆盖，供
    // 「强制探测为空 → 回退」验证使用。factory 生命周期须长于本对象。
    HRESULT Initialize(IDWriteFactory* factory,
                       const wchar_t* preferred = L"Segoe UI Variable Text",
                       const wchar_t* fallback = L"Segoe UI");

    bool IsReady() const noexcept { return factory_ != nullptr; }

    // 实际选定的族名（preferred 命中则为 preferred，否则 fallback）。
    const std::wstring& Family() const noexcept { return family_; }

    // preferred 是否在系统字体集合中命中。
    bool PreferredFound() const noexcept { return preferredFound_; }

    // 系统字体集合是否包含指定族（FindFamilyName 语义，大小写不敏感）。
    bool HasFamily(const wchar_t* family) const;

    // 以选定族创建 IDWriteTextFormat。sizeDip 为 DIP 字号。
    HRESULT CreateFormat(float sizeDip, DWRITE_FONT_WEIGHT weight, DWRITE_TEXT_ALIGNMENT align,
                         DWRITE_PARAGRAPH_ALIGNMENT paragraph, IDWriteTextFormat** out) const;

    // 左对齐 + 顶部段落对齐的便捷重载。
    HRESULT CreateFormat(float sizeDip, DWRITE_FONT_WEIGHT weight, IDWriteTextFormat** out) const;

private:
    IDWriteFactory* factory_ = nullptr;  // 非拥有（来自 RenderContext）
    std::wstring family_;                // 选定族名
    bool preferredFound_ = false;
};

}  // namespace faf
