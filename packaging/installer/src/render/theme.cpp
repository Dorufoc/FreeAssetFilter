//
// theme.cpp - 设计 token 实现。
//
// 浅色数值全部来自 `src/sopeek/resources/icons/install_design/` 四张设计稿的
// 实测像素（Chromium 渲染 + 逐像素采样），注释里的 hex 即设计稿 CSS 类色的合成值。
// 深色为设计稿未覆盖部分的反推值（同色系明度翻转），不参与浅色的任何计算。
//
#include "render/theme.h"

namespace spk {

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
    t.errorText = Rgba(0xAE, 0x28, 0x20, 1.00f);

    // ---- 旧 token（改版后仍被维护/卸载/消息页与控件过渡消费）----
    // 半透明面板填充（例如协议弹窗）。窗口背景由 DWM Mica 或兼容渐变单独提供。
    t.card = Rgba(255, 255, 255, 0.35f);
    t.cardStroke = Rgba(0xF1, 0xF1, 0xF1, 1.00f);
    t.textPrimary = Rgba(0x00, 0x00, 0x00, 1.00f);      // 设计稿正文纯黑
    t.textSecondary = Rgba(0x70, 0x70, 0x70, 1.00f);    // 标题栏图标色 #707070
    t.accent = Rgba(0x00, 0x00, 0x00, 1.00f);           // 改版后强调色 = 黑
    t.hover = Rgba(0x00, 0x00, 0x00, 0.06f);
    t.pressed = Rgba(0x00, 0x00, 0x00, 0.04f);
    t.divider = Rgba(0xF1, 0xF1, 0xF1, 1.00f);

    // ---- 设计稿 token ----
    t.windowStroke = Rgba(0xF1, 0xF1, 0xF1, 1.00f);  // cls-3 #f1f1f1
    t.chromeInk = Rgba(0x70, 0x70, 0x70, 1.00f);     // 最小化/关闭图标 #707070
    t.fieldFill = Rgba(0xEE, 0xEE, 0xEE, 1.00f);     // #838383 @14% 叠白 = #EEEEEE
    t.fieldStroke = Rgba(0xE9, 0xE9, 0xE9, 1.00f);   // #5D5D5D @14% 叠白 = #E9E9E9
    t.fieldText = Rgba(0x87, 0x87, 0x87, 1.00f);     // cls-10 #878787
    t.controlStroke = Rgba(0x8F, 0x8F, 0x8F, 1.00f); // cls-11 #8f8f8f
    t.solidFill = Rgba(0x00, 0x00, 0x00, 1.00f);     // 黑色胶囊按钮
    t.onSolid = Rgba(0xFF, 0xFF, 0xFF, 1.00f);
    t.muted = Rgba(0x00, 0x00, 0x00, 0.39f);         // cls-11 opacity 0.39
    t.trackProgress = Rgba(0x00, 0x00, 0x00, 0.80f); // cls-10 opacity 0.8
    t.heroWordmark = Rgba(0x09, 0x19, 0x35, 1.00f);  // cls-9 #091935
    t.heroTeal = Rgba(0x52, 0xDA, 0xC4, 1.00f);      // cls-4
    t.heroBlue = Rgba(0x70, 0xB5, 0xEA, 1.00f);      // cls-5
    t.heroGlowTeal = Rgba(0x00, 0xFF, 0xD6, 0.18f);  // cls-7
    t.heroGlowBlue = Rgba(0x00, 0x8F, 0xFF, 0.22f);  // cls-8
    t.heroRing = Rgba(0xFF, 0xFF, 0xFF, 0.16f);      // cls-6
    return t;
}

Theme DarkTheme() {
    Theme t;
    t.isDark = true;
    t.errorText = Rgba(0xFF, 0xAE, 0xA8, 1.00f);

    // 深色 Mica 上的薄雾层（几乎全透明，让 Mica 透出）。
    t.card = Rgba(0xFF, 0xFF, 0xFF, 0.09f);
    t.cardStroke = Rgba(0x2E, 0x2E, 0x2E, 1.00f);
    t.textPrimary = Rgba(0xFF, 0xFF, 0xFF, 1.00f);
    t.textSecondary = Rgba(0xA8, 0xA8, 0xA8, 1.00f);
    t.accent = Rgba(0xF5, 0xF5, 0xF5, 1.00f);
    t.hover = Rgba(0xFF, 0xFF, 0xFF, 0.08f);
    t.pressed = Rgba(0xFF, 0xFF, 0xFF, 0.04f);
    t.divider = Rgba(0x2E, 0x2E, 0x2E, 1.00f);

    t.windowStroke = Rgba(0x2E, 0x2E, 0x2E, 1.00f);
    t.chromeInk = Rgba(0xB4, 0xB4, 0xB4, 1.00f);
    t.fieldFill = Rgba(0x2A, 0x2A, 0x2A, 1.00f);
    t.fieldStroke = Rgba(0x34, 0x34, 0x34, 1.00f);
    t.fieldText = Rgba(0x8E, 0x8E, 0x8E, 1.00f);
    t.controlStroke = Rgba(0x9A, 0x9A, 0x9A, 1.00f);
    t.solidFill = Rgba(0xF5, 0xF5, 0xF5, 1.00f);
    t.onSolid = Rgba(0x12, 0x12, 0x12, 1.00f);
    t.muted = Rgba(0xFF, 0xFF, 0xFF, 0.39f);
    t.trackProgress = Rgba(0xFF, 0xFF, 0xFF, 0.80f);
    t.heroWordmark = Rgba(0xEA, 0xF2, 0xFF, 1.00f);
    t.heroTeal = Rgba(0x52, 0xDA, 0xC4, 1.00f);
    t.heroBlue = Rgba(0x70, 0xB5, 0xEA, 1.00f);
    t.heroGlowTeal = Rgba(0x00, 0xFF, 0xD6, 0.22f);
    t.heroGlowBlue = Rgba(0x00, 0x8F, 0xFF, 0.26f);
    t.heroRing = Rgba(0xFF, 0xFF, 0xFF, 0.16f);
    return t;
}

Theme GetTheme(bool isDark) { return isDark ? DarkTheme() : LightTheme(); }

}  // namespace spk
