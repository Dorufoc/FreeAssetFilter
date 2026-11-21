#pragma once
//
// pages_welcome.h - 安装向导页面①「英雄页 / 欢迎」。
//
// 视觉唯一依据：`src/sopeek/resources/icons/install_design/英雄页.svg`。
// 画布 640x540 DIP（design 坐标减 translate(640 268)）：
//   品牌图形（两圆 + 词标）   —— 由 render/hero_art.h 矢量绘制
//   「全能 · 高效 · 开源」    24px / 39% 黑 / 基线 y=326 / 水平居中
//   「文件管理器」            32px / bold / 基线 y=369 / 水平居中
//   黑色胶囊「下一步 >」      152x36 / r8 / (244,427)
//
// 设计稿的文字对象全部以 x=960（窗口水平中心）作为「左边缘」摆放，导致标题与按钮
// 文字整体右偏；经用户确认按「真正居中」实现（几何/字号/字重不变）。
//
// 页面状态一律读写 AppState（Frozen contracts §12）。版本字符串只取根 `SPKVERSION`
// （§18），绝不硬编码。坐标与绘制全程 DIP（§6）。
//
#include <windows.h>

#include <d2d1_1.h>
#include <dwrite.h>

#include <functional>
#include <string>
#include <vector>

#include "render/animation.h"
#include "render/app_state.h"
#include "render/controls_base.h"
#include "render/controls_basic.h"
#include "render/glyphs.h"
#include "render/text.h"
#include "render/theme.h"

namespace spk {

class HeroArt;      // render/hero_art.h（词标 + 品牌圆，矢量）
class LogoBitmap;   // render/logo.h（PNG 解码器：英雄页背景图 / 宣传图）

// 英雄页背景图（`install_design/bg.png`，透明底：柔化双圆 + 词标）。1570x2160，
// 词标墨迹位于 (166,558)-(1400,904)。绘制时按「词标与设计稿同尺寸」等比缩放并平移，
// 因此与设计稿英雄页的构图逐像素对齐（词标 185.797,156.599 / 266.906x75.754）。
bool DrawHeroBackground(ID2D1DeviceContext* dc, const LogoBitmap* background, float alpha = 1.0f);

namespace hero_bg {
constexpr float kWidth = 1570.0f;
constexpr float kHeight = 2160.0f;
constexpr float kInkLeft = 166.0f;
constexpr float kInkTop = 558.0f;
constexpr float kInkWidth = 1234.0f;
// 缩放 = 设计稿词标宽 / 背景图词标宽。
constexpr float kScale = 266.906f / kInkWidth;
// 平移：让背景图的词标墨迹落在设计稿的词标位置上。
constexpr float kOffsetX = 185.797f - kInkLeft * kScale;
constexpr float kOffsetY = 156.599f - kInkTop * kScale;
constexpr float kDrawWidth = kWidth * kScale;
constexpr float kDrawHeight = kHeight * kScale;
}  // namespace hero_bg

// 完成页的品牌图形：优先重放 SVG 矢量图形；可用柔化位图兜底。
void DrawHeroArtwork(ID2D1DeviceContext* dc, const HeroArt* art, const LogoBitmap* background,
                     const Theme& theme, float alpha);

// RCDATA 资源 ID。必须与 packaging/installer/resources/app.rc 中的定义一致；既有
// IDR_LOGO=101 与 `1 VERSIONINFO` 不重编号（§13 append-only）。102/103/104 为新号。
#ifndef IDR_LICENSE
#define IDR_LICENSE 102
#endif
#ifndef IDR_SPKVERSION
#define IDR_SPKVERSION 103
#endif
#ifndef IDR_USERAGREEMENT
#define IDR_USERAGREEMENT 104
#endif
#ifndef IDR_HERO_BG
#define IDR_HERO_BG 106
#endif

// 从本模块的 RCDATA 资源按 UTF-8 解码为宽串（BOM 兜底）。资源缺失、为空或解码
// 失败时返回 false（out 清空）。
bool ReadUtf8Resource(UINT resourceId, std::wstring& out);

// 版本字符串：读取 IDR_SPKVERSION 首行（UTF-8，BOM 兜底），去掉首尾空白与前导
// 'v'/'V'。失败（资源缺失）返回空串——调用方决定回退展示，绝不硬编码版本。
std::wstring ReadVersionString();

// 许可协议摘要（纯函数，保留给诊断/测试；页面不再渲染摘要行）。
std::vector<std::wstring> LicenseSummaryLines();

// ============================== 设计稿几何（DIP）===========================
// 全部取自设计稿，减去窗口原点 (640,268)。页面与 LicenseSheet 共用。
namespace design {
// 通用：黑色胶囊按钮 152x36（所有页面同一列，左缘 244 = 窗口水平居中）
constexpr float kButtonLeft = 244.0f;
constexpr float kActionCenterX = 320.0f;
constexpr float kButtonTop = 427.0f;
constexpr float kButtonWidth = 152.0f;
constexpr float kButtonHeight = 36.0f;
// 英雄页
constexpr float kTaglineBaselineY = 326.0f;      // 全能 · 高效 · 开源（24px）
constexpr float kHeroTitleBaselineY = 369.0f;    // 文件管理器（32px bold）
constexpr float kLinkBaselineY = 503.0f;         // 返回 / 退出 / 关闭（16px，水平居中）
// 完成页
constexpr float kFinishTitleBaselineY = 354.0f;  // 安装完成（32px bold）
// 标题栏（所有页面共用）：Logo 26x26 @ (17,16)，标题文字中心 x=111（设计稿 tspan x=-60.246
// 说明该文本以 translate.x 为**中心**），基线 35。
constexpr float kTitleLogoLeft = 17.0f;
constexpr float kTitleLogoTop = 16.0f;
constexpr float kTitleLogoSize = 26.0f;
constexpr float kTitleTextCenterX = 111.0f;
constexpr float kTitleTextBaselineY = 35.0f;
// 主按钮尾部「>」（Sitka Display 18px 的 > 字形，左缘 = 1016.32-640）。
constexpr float kChevronLeft = 376.32f;
// 安装配置页（所有文字都以设计稿 translate.x 为**中心**，见 tspan x 偏移）
constexpr float kPageTitleCenterX = 102.0f;      // 页标题中心（design 742-640）
constexpr float kPageTitleBaselineY = 114.0f;    // 页标题（32px bold）
constexpr float kFieldLabelCenterX = 75.0f;      // 「安装路径」中心（基线 169）
constexpr float kFieldLabelBaselineY = 169.0f;
constexpr float kFieldTop = 180.0f;              // 路径框 564x36（左缘 38）
constexpr float kFieldHeight = 36.0f;
constexpr float kSpaceLeft = 43.0f;              // 「可用空间：… 预计所需 …」（左缘，基线 223）
constexpr float kSpaceBaselineY = 240.0f;  // 设计稿 tspan y=17 → 491+17-268
constexpr float kOptionBoxTop = 267.0f;          // 三个复选框（29x29）
constexpr float kOptionLabelBaselineY = 287.0f;  // 复选框标签（16px）
constexpr float kOptionAutostartLeft = 44.0f;    // 开机自启动
constexpr float kOptionCtxMenuLeft = 223.0f;     // 添加到右键菜单
constexpr float kOptionDesktopLeft = 415.0f;     // 在桌面创建快捷方式
constexpr float kAgreeBoxLeft = 167.0f;          // 同意复选框
constexpr float kAgreeBoxTop = 375.0f;
constexpr float kAgreeBaselineY = 395.0f;        // 同意文字（16px，左缘 204）
// 正在安装页
constexpr float kTrackTop = 464.0f;                 // 原稿底部进度轨道，保留中部留白
constexpr float kTrackHeight = 12.0f;
constexpr float kStageLeft = 43.0f;                // 正在解压：715 - 32 - 640
constexpr float kStageBaselineY = kTrackTop + 38.0f;
constexpr float kPercentCenterX = 578.0f;          // 30%（16px，与阶段文案基线对齐）
}  // namespace design

// 设计稿「文字基线 → DWrite 段落矩形」换算用的近似系数：Microsoft YaHei 在
// DWRITE_PARAGRAPH_ALIGNMENT_CENTER 下，基线距段落框顶部约 1.275 em（按 1.75em 行高与
// YaHei ascent 1.06 / descent 0.26 推导，并用真机截图回归校准）。
constexpr float kBaselineToBoxTop = 1.275f;

// 构造「基线对齐」的单行文字矩形：垂直方向让基线正好落在 baselineY。
// 宽度取 [x0, x1]；居中/左对齐由调用方传给 DWrite。
inline D2D1_RECT_F BaselineRect(float x0, float x1, float baselineY, float sizeDip) {
    const float top = baselineY - kBaselineToBoxTop * sizeDip;
    return D2D1_RECT_F{x0, top, x1, top + sizeDip * 1.75f};
}

// 构造「以 centerX 为中心、基线对齐」的单行文字矩形（设计稿绝大多数文本都是这种锚点：
// 元素的 translate.x 就是文字中心，tspan 的负 x 偏移等于半个字宽）。
inline D2D1_RECT_F CenteredBaselineRect(float centerX, float baselineY, float sizeDip,
                                         float halfWidth = 400.0f) {
    return BaselineRect(centerX - halfWidth, centerX + halfWidth, baselineY, sizeDip);
}

// ============================== 页面① 英雄页 / 欢迎 ========================

// 欢迎页：品牌图形 + 标语 + 产品定位 + 黑色胶囊「下一步」。
// 无顶部步骤区、无底部导航（新版设计稿没有），前进由页内按钮承担。
class WelcomePage : public Widget {
public:
    explicit WelcomePage(AppState& state);

    // 依赖注入（宿主构造后绑定；均可为空——为空时退化为无动画/无文字/无图形）。
    void BindAnimator(Animator* animator);
    void BindText(const TextFactory* text);
    void BindGlyphs(const GlyphFont* glyphs);
    void SetHeroArt(const HeroArt* art) { art_ = art; }
    // 英雄页背景图（IDR_HERO_BG）；不可用时退回矢量图形。
    void SetBackground(const LogoBitmap* background) { background_ = background; }

    // 英雄页大按钮「下一步」的点击意图（由外壳注入 GoNext 路径）。
    void SetOnNextIntent(std::function<void()> cb) { onNextIntent_ = std::move(cb); }

    // 设计稿坐标是绝对的；contentCard 只用于命中测试范围。
    void Layout(const D2D1_RECT_F& contentCard);
    void SyncFromState();

    // ---- Widget 接口 ----
    void Render(ID2D1DeviceContext* dc, const Theme& theme) override;
    bool HitTest(float x, float y) const override;
    bool OnInput(const InputEvent& event) override;
    bool IsFocusable() const override { return false; }
    void OnFocus(bool focused) override { (void)focused; }

    WidgetHost& Host() noexcept { return host_; }

    const std::wstring& ProductName() const noexcept { return productName_; }
    const std::wstring& Version() const noexcept { return version_; }
    const std::wstring& Tagline() const noexcept { return tagline_; }
    Button& NextButton() noexcept { return nextButton_; }

private:
    AppState& state_;  // 借用（§12 共享状态）
    std::wstring productName_ = L"Sopeek";
    std::wstring version_;
    std::wstring tagline_;

    Button nextButton_;
    WidgetHost host_;

    const HeroArt* art_ = nullptr;
    const LogoBitmap* background_ = nullptr;
    const TextFactory* text_ = nullptr;
    const GlyphFont* glyphs_ = nullptr;

    std::function<void()> onNextIntent_;

    D2D1_RECT_F card_{};
    D2D1_RECT_F taglineRect_{};
    D2D1_RECT_F titleRect_{};
};

// ============================== 接线入口 ===================================

// 页面①渲染入口（薄包装，供 installer_window 调用）。
void RenderWelcome(ID2D1DeviceContext* dc, const Theme& theme, WelcomePage& page);

}  // namespace spk
