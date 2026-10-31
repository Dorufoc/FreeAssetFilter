#pragma once
//
// pages_welcome.h - 安装向导页面①「欢迎」与页面②「许可协议」（Todo 9）。
//
// 独立页文件：与 Todo 10（pages_setup）和 Todo 11（pages_progress）互不触碰，
// 页接线归 Todo 12。两页均实现 controls_base.h 的 Widget 接口（Render / HitTest /
// OnInput / IsFocusable / OnFocus），并各自持有一个 WidgetHost 统一分发指针/键盘
// 事件给子控件。供 Todo 12 经 RenderWelcome(...) / RenderLicense(...) 接入外壳。
//
// 页面状态一律读写 AppState（Frozen contracts §12）：许可页的同意勾选直接写
// `state.agreed`，「下一步」按钮的可用性只由 `state.agreed` 决定（未勾选禁用）。
//
// 版本字符串只取根 `SPKVERSION`（Frozen contracts §18）：经 IDR_SPKVERSION RCDATA
// 运行时 UTF-8 读取首行、去掉前导 'v'——绝不硬编码。许可全文经 IDR_LICENSE RCDATA
// 指向根 `LICENSE` 运行时读取（不复制副本，§13 append-only 资源行；BOM 兜底）。
//
// 坐标与绘制全程 DIP（§6）：本文件不乘 DPI。视觉只消费 theme.h 的 token（§13，
// 不另立 token 表）；文字经 text.h 的 TextFactory，图标只取 glyphs.h 的码点。
// 页面切换动效 = 淡入 + 轻微上移，经 animation.h 的 AnimValue 实现——AnimValue 由
// 宿主经 BindAnimator 注入（页面不自持帧时钟，无 Animator 时退回终值）。
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
#include "render/controls_feedback.h"
#include "render/glyphs.h"
#include "render/logo.h"
#include "render/text.h"
#include "render/theme.h"

namespace spk {

// RCDATA 资源 ID。必须与 installer_duilib/resources/app.rc 中的定义一致；既有
// IDR_LOGO=101 与 `1 VERSIONINFO` 不重编号（§13 append-only）。102/103 为新号。
#ifndef IDR_LICENSE
#define IDR_LICENSE 102
#endif
#ifndef IDR_SPKVERSION
#define IDR_SPKVERSION 103
#endif

// 从本模块的 RCDATA 资源按 UTF-8 解码为宽串（BOM 兜底）。资源缺失、为空或解码
// 失败时返回 false（out 清空）。
bool ReadUtf8Resource(UINT resourceId, std::wstring& out);

// 版本字符串：读取 IDR_SPKVERSION 首行（UTF-8，BOM 兜底），去掉首尾空白与前导
// 'v'/'V'。失败（资源缺失）返回空串——调用方决定回退展示，绝不硬编码版本。
std::wstring ReadVersionString();

// 许可协议 3 行中文摘要（纯函数，便于断言与复用）。
std::vector<std::wstring> LicenseSummaryLines();

// ============================== 页面① 欢迎 =================================

// 欢迎页（英雄页，追加需求 2026-10-18）：Logo + 产品名 + 版本 + 标语 + 大按钮「下一步」。
// 无顶部步骤区、无底部导航（前进由本页大按钮承担，外壳不再渲染底部按钮）。
class WelcomePage : public Widget {
public:
    explicit WelcomePage(AppState& state);

    // 依赖注入（宿主构造后绑定；均可为空——为空时退化为无动画/无文字/无 Logo）。
    void BindAnimator(Animator* animator);
    void BindText(const TextFactory* text);
    void BindGlyphs(const GlyphFont* glyphs);
    void SetLogo(const LogoBitmap* logo) { logo_ = logo; }

    // 英雄页大按钮「下一步」的点击意图（由外壳注入 GoNext 路径）。
    void SetOnNextIntent(std::function<void()> cb) { onNextIntent_ = std::move(cb); }

    // 依内容卡片矩形（DIP）布局静态元素与大按钮。
    void Layout(const D2D1_RECT_F& contentCard);
    // 从 AppState 同步（欢迎页无输入字段，仅保证接口对称/供 Todo 12 调用）。
    void SyncFromState();

    // 页面切换动效：进入本页时调用以(重)播「淡入 + 轻微上移」。无 Animator 时终值。
    void ResetIntro();
    float EnterProgress() const;   // 0..1（无 Animator / 未动画时为 1）
    float EnterAlpha() const { return EnterProgress(); }
    float EnterOffsetDip() const;  // 当前上移偏移（DIP，>=0）

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
    void StartIntro();

    AppState& state_;  // 借用（§12 共享状态）
    std::wstring productName_ = L"Sopeek";
    std::wstring version_;
    std::wstring tagline_;

    Button nextButton_;
    WidgetHost host_;

    const LogoBitmap* logo_ = nullptr;
    const TextFactory* text_ = nullptr;
    const GlyphFont* glyphs_ = nullptr;

    Animator* animator_ = nullptr;
    AnimValue* enterAnim_ = nullptr;
    std::string enterName_;

    std::function<void()> onNextIntent_;

    D2D1_RECT_F card_{};
    D2D1_RECT_F logoRect_{};
    D2D1_RECT_F nameRect_{};
    D2D1_RECT_F versionRect_{};
    D2D1_RECT_F taglineRect_{};
    D2D1_RECT_F buttonRect_{};
};

// ============================== 页面② 许可协议 =============================

// 许可协议页：标题 + 3 行中文摘要 + LicenseBox（AGPL 全文）+ 同意 CheckBox；
// 未勾选时「下一步」禁用（只由 AppState.agreed 决定）。
class LicensePage : public Widget {
public:
    explicit LicensePage(AppState& state);

    void BindAnimator(Animator* animator);
    void BindText(const TextFactory* text);
    void BindGlyphs(const GlyphFont* glyphs);
    void BindWriteFactory(IDWriteFactory* factory);  // LicenseBox 折行度量

    void Layout(const D2D1_RECT_F& contentCard);
    // AppState.agreed → CheckBox 勾选态 + 「下一步」门控。
    void SyncFromState();

    void ResetIntro();
    float EnterProgress() const;
    float EnterOffsetDip() const;

    // ---- Widget 接口 ----
    void Render(ID2D1DeviceContext* dc, const Theme& theme) override;
    bool HitTest(float x, float y) const override;
    bool OnInput(const InputEvent& event) override;
    bool IsFocusable() const override { return false; }
    void OnFocus(bool focused) override { (void)focused; }

    WidgetHost& Host() noexcept { return host_; }
    LicenseBox& Box() noexcept { return box_; }
    CheckBox& AgreeBox() noexcept { return agree_; }

    bool Agreed() const noexcept { return state_.agreed; }
    bool LicenseLoaded() const noexcept { return licenseLoaded_; }
    bool HasLicenseError() const noexcept { return !licenseError_.empty(); }
    const std::wstring& LicenseError() const noexcept { return licenseError_; }
    const std::vector<std::wstring>& SummaryLines() const noexcept { return summary_; }

private:
    void StartIntro();

    AppState& state_;  // 借用（§12 共享状态）
    std::wstring licenseError_;
    bool licenseLoaded_ = false;
    std::vector<std::wstring> summary_;

    LicenseBox box_;
    CheckBox agree_;
    WidgetHost host_;

    const TextFactory* text_ = nullptr;
    const GlyphFont* glyphs_ = nullptr;

    Animator* animator_ = nullptr;
    AnimValue* enterAnim_ = nullptr;
    std::string enterName_;

    D2D1_RECT_F card_{};
    D2D1_RECT_F titleRect_{};
    std::vector<D2D1_RECT_F> summaryRects_;
    D2D1_RECT_F errorRect_{};
};

// ============================== Todo 12 接线入口 ===========================

// 页面①渲染入口（薄包装，供 Todo 12 调用）。
void RenderWelcome(ID2D1DeviceContext* dc, const Theme& theme, WelcomePage& page);

// 页面②渲染入口（薄包装，供 Todo 12 调用）。
void RenderLicense(ID2D1DeviceContext* dc, const Theme& theme, LicensePage& page);

}  // namespace spk
