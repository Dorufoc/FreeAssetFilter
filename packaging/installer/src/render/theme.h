#pragma once
//
// theme.h - 设计 token（本安装器唯一的 token 表，Frozen contracts §13）。
//
// 颜色为 D2D1_COLOR_F（直观 RGBA，各分量 0..1，非预乘）。透明度由使用方按需
// 决定——窗口不透明卡片由 DrawContent 统一铺底，见 Frozen contracts §5。
// 任何后续 todo 不得另立 token 表；本文件是唯一权威。
//
// 2026-11 改版：安装器视觉改由仓库 `src/sopeek/resources/icons/install_design/`
// 下的四张设计稿（英雄页 / 安装配置 / 正在安装 / 安装完成）唯一裁定。旧 WinUI3
// 字段（card/cardStroke/accent/hover/pressed/divider）保留——维护/卸载/消息页与
// 若干控件仍消费它们；新增字段一律命名为设计稿语义（windowStroke / fieldFill /
// solidFill ...），数值取自设计稿的实测像素（见各字段行内注释）。
//
#include <d2d1.h>
#include <dwrite.h>

namespace spk {

// 一套完整配色 token。浅/深各一份，见 LightTheme()/DarkTheme()。
//
// 浅色 = 设计稿实测值；深色 = 设计稿未覆盖、按同色系反推（2026-11 用户确认
// 「跟随系统深浅色」后由实现方推导，不得反过来影响浅色数值）。
struct Theme {
    // ---- 旧 WinUI3 token（保留：维护/卸载/消息页与控件过渡仍在用）----
    D2D1_COLOR_F card;           // 卡片/面板底色（改版后 = 不透明窗口底 #FFFFFF / #1F1F1F）
    D2D1_COLOR_F cardStroke;     // 卡片描边
    D2D1_COLOR_F textPrimary;    // 主文本（改版后 = 纯黑 #000000 / 纯白 #FFFFFF）
    D2D1_COLOR_F textSecondary;  // 次级文本
    D2D1_COLOR_F accent;         // 强调色（旧值，仅兼容保留）
    D2D1_COLOR_F hover;          // 交互悬停叠加色
    D2D1_COLOR_F pressed;        // 交互按下叠加色
    D2D1_COLOR_F divider;        // 分隔线
    bool isDark = false;         // 是否深色主题

    // ---- 设计稿 token（install_design/*.svg 实测）----
    D2D1_COLOR_F windowStroke;   // 窗口 1px 描边：cls-3 #F1F1F1 / 深色 #2E2E2E
    D2D1_COLOR_F chromeInk;      // 标题栏最小化/关闭图标：#707070 / #B4B4B4
    D2D1_COLOR_F fieldFill;      // 输入框 / 进度轨道 / 占位块填充：#EEEEEE / #2A2A2A
    D2D1_COLOR_F fieldStroke;    // 同上的 1px 描边：#E9E9E9 / #343434
    D2D1_COLOR_F errorText;      // 配置页路径或容量错误
    D2D1_COLOR_F fieldText;      // 输入框内文字：#878787 / #8E8E8E
    D2D1_COLOR_F controlStroke;  // 未勾选复选框描边：#8F8F8F / #9A9A9A
    D2D1_COLOR_F solidFill;      // 主按钮底（黑色胶囊）：#000000 / #F5F5F5
    D2D1_COLOR_F onSolid;        // 主按钮文字 / 勾选对勾：#FFFFFF / #111111
    D2D1_COLOR_F muted;          // 「全能 · 高效 · 开源」：黑 39% / 白 39%
    D2D1_COLOR_F trackProgress;  // 进度填充：黑 80%（叠在 fieldFill 上 = #313131）
    D2D1_COLOR_F heroWordmark;   // Sopeek 词标：cls-9 #091935 / 深色 #EAF2FF
    D2D1_COLOR_F heroTeal;       // 品牌圆（左）：cls-4 #52DAC4
    D2D1_COLOR_F heroBlue;       // 品牌圆（右）：cls-5 #70B5EA
    D2D1_COLOR_F heroGlowTeal;   // 淡青圆：cls-7 #00FFD6 @18%
    D2D1_COLOR_F heroGlowBlue;   // 淡蓝圆：cls-8 #008FFF @22%
    D2D1_COLOR_F heroRing;       // 品牌圆高光描边：cls-6 rgba(255,255,255,0.16)
};

// 圆角半径阶梯（DIP）。
namespace radius {
constexpr float Small = 4.0f;    // 控件
constexpr float Medium = 8.0f;   // 卡片
constexpr float Large = 12.0f;   // 大面板 / Logo
// 设计稿（install_design）
constexpr float Window = 13.0f;     // 窗口卡片外圆角（矩形_4 rx=13）
constexpr float Field = 8.0f;       // 输入框 / 黑色按钮 / 复选框（rx=8）
constexpr float Track = 6.0f;       // 进度轨道 12px 高胶囊（rx=6）
constexpr float TrackFill = 4.0f;   // 进度填充 8px 高胶囊（rx=4）
constexpr float CheckInner = 3.0f;  // 勾选态内部黑块（矩形_151 rx=3）
}  // namespace radius

// 间距阶梯（DIP）。
namespace spacing {
constexpr float XS = 4.0f;
constexpr float S = 8.0f;
constexpr float M = 16.0f;
constexpr float L = 24.0f;
}  // namespace spacing

// 字号阶梯（DIP）。
namespace fontsize {
constexpr float Caption = 12.0f;
constexpr float Body = 14.0f;
constexpr float Subtitle = 20.0f;
constexpr float Title = 28.0f;
constexpr float Display = 40.0f;
// 设计稿（install_design）
constexpr float PageTitle = 32.0f;  // 安装配置 / 正在安装 / 文件管理器 / 安装完成 / 概念宣传图
constexpr float Body16 = 16.0f;     // 标签、正文、返回/退出、标题栏标题
constexpr float ButtonText = 18.0f; // 黑色胶囊按钮文字、输入框文字、按钮内箭头
constexpr float Tagline = 24.0f;    // 全能 · 高效 · 开源
}  // namespace fontsize

// 字重（取值与 DWRITE_FONT_WEIGHT 一致，便于直接传给排版接口）。
namespace weight {
constexpr DWRITE_FONT_WEIGHT Regular = DWRITE_FONT_WEIGHT_REGULAR;     // 400
constexpr DWRITE_FONT_WEIGHT SemiBold = DWRITE_FONT_WEIGHT_SEMI_BOLD;  // 600
constexpr DWRITE_FONT_WEIGHT Bold = DWRITE_FONT_WEIGHT_BOLD;           // 700（设计稿标题）
}  // namespace weight

// 浅色主题（= 设计稿实测值）。
Theme LightTheme();

// 深色主题（设计稿未覆盖，按同色系反推）。
Theme DarkTheme();

// 按 isDark 选择主题。
Theme GetTheme(bool isDark);

}  // namespace spk
