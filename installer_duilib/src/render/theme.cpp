//
// theme.cpp - WinUI3 设计 token 实现。
//
// 数值取自 WinUI3 / Fluent 设计 token（浅色 CardBackgroundFillColorDefault 等），
// 强调色按 Frozen contracts §3 固定为 #005FB8（浅）/ #60CDFF（深）。
//
#include "render/theme.h"

namespace faf {

namespace {

// 由 8 位 RGB 与 0..1 alpha 构造 D2D1_COLOR_F。
constexpr D2D1_COLOR_F Rgba(unsigned int r, unsigned int g, unsigned int b, float a) {
    return D2D1_COLOR_F{static_cast<float>(r) / 255.0f, static_cast<float>(g) / 255.0f,
                        static_cast<float>(b) / 255.0f, a};
}

}  // namespace

Theme LightTheme() {
    Theme t;
    t.isDark = false;
    t.card = Rgba(255, 255, 255, 0.70f);         // CardBackgroundFillColorDefault
    t.cardStroke = Rgba(0, 0, 0, 0.06f);         // CardStrokeColorDefault
    t.textPrimary = Rgba(0, 0, 0, 0.89f);        // TextFillColorPrimary
    t.textSecondary = Rgba(0, 0, 0, 0.62f);      // TextFillColorSecondary
    t.accent = Rgba(0x00, 0x5F, 0xB8, 1.00f);    // AccentFillColorDefault #005FB8
    t.hover = Rgba(0, 0, 0, 0.06f);              // ControlFillColorSecondary
    t.pressed = Rgba(0, 0, 0, 0.04f);            // ControlFillColorTertiary
    t.divider = Rgba(0, 0, 0, 0.06f);            // DividerStrokeColorDefault
    return t;
}

Theme DarkTheme() {
    Theme t;
    t.isDark = true;
    t.card = Rgba(255, 255, 255, 0.06f);
    t.cardStroke = Rgba(255, 255, 255, 0.09f);
    t.textPrimary = Rgba(255, 255, 255, 1.00f);
    t.textSecondary = Rgba(255, 255, 255, 0.77f);
    t.accent = Rgba(0x60, 0xCD, 0xFF, 1.00f);    // AccentFillColorDefault (dark) #60CDFF
    t.hover = Rgba(255, 255, 255, 0.08f);
    t.pressed = Rgba(255, 255, 255, 0.04f);
    t.divider = Rgba(255, 255, 255, 0.08f);
    return t;
}

Theme GetTheme(bool isDark) { return isDark ? DarkTheme() : LightTheme(); }

}  // namespace faf
