#pragma once
//
// glyphs.h - Fluent 字形封装（本安装器唯一的图标码点表，Frozen contracts §13）。
//
// 优先 "Segoe Fluent Icons"，缺失回退 "Segoe MDL2 Assets"。按 Frozen contracts §8，
// 每个选用码点必须在两族各自验证可显示——不能只因一族有就假定另一族有。实测矩阵
// 见证据 glyphs-matrix.txt。
//
// 不拥有传入的 IDWriteFactory；复用 RenderContext 的共享 DWrite 工厂。
//
#include <windows.h>

#include <dwrite.h>

#include <string>

namespace faf {

// 安装器用到的图标码点。命名语义 → BMP 码点（已对两族逐一验证）。
namespace glyph {
constexpr wchar_t Check = L'\uE73E';     // 勾选/复选
constexpr wchar_t Folder = L'\uE8B7';    // 文件夹（安装位置）
constexpr wchar_t Download = L'\uE896';  // 下载/安装
constexpr wchar_t Settings = L'\uE713';  // 设置
constexpr wchar_t Info = L'\uE946';      // 信息
constexpr wchar_t Location = L'\uE707';  // 位置
constexpr wchar_t Close = L'\uE8BB';     // 关闭
constexpr wchar_t Minimize = L'\uE921';  // 最小化
// 成功：plan 建议的 U+EA52 经双族实测渲染为「后退/前进箭头」，非成功语义；
// 实测替换为 U+E930（Completed，圆圈内对勾），两族均存在。见证据 glyphs-matrix.txt / probe。
constexpr wchar_t Success = L'\uE930';   // 成功（已完成）
}  // namespace glyph

class GlyphFont {
public:
    // 绑定 DWrite 工厂并解析图标字体族。preferred/fallback 可覆盖，供回退验证使用。
    HRESULT Initialize(IDWriteFactory* factory,
                       const wchar_t* preferred = L"Segoe Fluent Icons",
                       const wchar_t* fallback = L"Segoe MDL2 Assets");

    bool IsReady() const noexcept { return factory_ != nullptr; }

    // 实际选定的图标族名。
    const std::wstring& Family() const noexcept { return family_; }

    // 指定族是否在该码点有字形（glyphIndex != 0）。用于双族验证与回退判定。
    static bool FamilyHasCodepoint(IDWriteFactory* factory, const wchar_t* family,
                                   wchar_t codepoint);

    // 指定族名是否存在于系统字体集合。
    static bool FamilyExists(IDWriteFactory* factory, const wchar_t* family);

    // 当前选定族是否包含该码点。
    bool HasCodepoint(wchar_t codepoint) const;

    // 以选定图标族创建 IDWriteTextFormat（用于绘制单个字形）。
    HRESULT CreateFormat(float sizeDip, IDWriteTextFormat** out) const;

private:
    IDWriteFactory* factory_ = nullptr;  // 非拥有
    std::wstring family_;
};

}  // namespace faf
