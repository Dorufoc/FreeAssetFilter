#pragma once
//
// theme.h - WinUI3 设计 token（本安装器唯一的 token 表，Frozen contracts §13）。
//
// 颜色为 D2D1_COLOR_F（直观 RGBA，各分量 0..1，非预乘）。透明度由使用方按需
// 决定——Win11 走 Mica 合成、Win10 走不透明兜底，见 Frozen contracts §5。
// 任何后续 todo 不得另立 token 表；本文件是唯一权威。
//
#include <d2d1.h>
#include <dwrite.h>

namespace faf {

// 一套完整配色 token。浅/深各一份，见 LightTheme()/DarkTheme()。
struct Theme {
    D2D1_COLOR_F card;           // 卡片/面板底色
    D2D1_COLOR_F cardStroke;     // 卡片描边
    D2D1_COLOR_F textPrimary;    // 主文本
    D2D1_COLOR_F textSecondary;  // 次级文本
    D2D1_COLOR_F accent;         // 强调色（浅 #005FB8 / 深 #60CDFF）
    D2D1_COLOR_F hover;          // 交互悬停叠加色
    D2D1_COLOR_F pressed;        // 交互按下叠加色
    D2D1_COLOR_F divider;        // 分隔线
    bool isDark = false;         // 是否深色主题
};

// 圆角半径阶梯（DIP）。
namespace radius {
constexpr float Small = 4.0f;   // 控件
constexpr float Medium = 8.0f;  // 卡片
constexpr float Large = 12.0f;  // 大面板 / Logo
}  // namespace radius

// 间距阶梯（DIP）。
namespace spacing {
constexpr float XS = 4.0f;
constexpr float S = 8.0f;
constexpr float M = 16.0f;
constexpr float L = 24.0f;
}  // namespace spacing

// WinUI3 字号阶梯（DIP）。
namespace fontsize {
constexpr float Caption = 12.0f;
constexpr float Body = 14.0f;
constexpr float Subtitle = 20.0f;
constexpr float Title = 28.0f;
constexpr float Display = 40.0f;
}  // namespace fontsize

// 字重（取值与 DWRITE_FONT_WEIGHT 一致，便于直接传给排版接口）。
namespace weight {
constexpr DWRITE_FONT_WEIGHT Regular = DWRITE_FONT_WEIGHT_REGULAR;     // 400
constexpr DWRITE_FONT_WEIGHT SemiBold = DWRITE_FONT_WEIGHT_SEMI_BOLD;  // 600
}  // namespace weight

// 浅色主题。
Theme LightTheme();

// 深色主题。
Theme DarkTheme();

// 按 isDark 选择主题。
Theme GetTheme(bool isDark);

}  // namespace faf
