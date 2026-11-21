//
// layout.cpp - 640x540 DIP 布局外壳实现（Frozen contract §6：全程 DIP）。
//
// 唯一职责：把冻结的 640x540 DIP 逻辑画布切成「自绘标题栏 + 页面内容区域」，
// 并提供 DIP 命中测试与 DPI 守卫。所有坐标均为 DIP，绝不乘 DPI。
//
#include "render/layout.h"

#include "render/app_state.h"

namespace spk {

namespace {

// 便利构造：以左/上/右/下 4 边 DIP 值建矩形。
D2D1_RECT_F Rect(float left, float top, float right, float bottom) {
    return D2D1_RECT_F{left, top, right, bottom};
}

// 空矩形（新版外壳不再有步骤带/底部条）。
D2D1_RECT_F EmptyRect() { return Rect(0.0f, 0.0f, 0.0f, 0.0f); }

// 标题栏窗口按钮的图标中心（设计稿实测：最小化 1218.5..1229.985 → 中心 583.7；
// 关闭 ✕ 中心 614.5；两者中心 y ≈ 29）。命中区 30x30 居中于图标。
constexpr float kMinButtonCenterX = 583.7f;
constexpr float kCloseButtonCenterX = 614.5f;
constexpr float kWindowButtonCenterY = 29.0f;
constexpr float kWindowButtonHalf = 15.0f;

}  // namespace

bool IsHeroPage(int page) {
    // Welcome=0 / Finish=4，以及只追加到末尾的维护页(5)/卸载确认(6)/消息(7)。
    return page == Welcome || page == Finish || page >= Maintenance;
}

ShellLayout ComputeShellLayout(bool hero) {
    (void)hero;  // 新版外壳只有一种形状（设计稿无步骤带、无底部条）
    const float W = layout::kCanvasWidth;
    const float H = layout::kCanvasHeight;
    const float titleH = layout::kTitleBarHeight;

    ShellLayout s{};

    // --- 标题栏（自绘；含最小化/关闭命中区）---
    s.titleBar = Rect(0.0f, 0.0f, W, titleH);
    s.stepper = EmptyRect();
    s.bottomBar = EmptyRect();
    s.closeButton = Rect(kCloseButtonCenterX - kWindowButtonHalf, kWindowButtonCenterY - kWindowButtonHalf,
                         kCloseButtonCenterX + kWindowButtonHalf, kWindowButtonCenterY + kWindowButtonHalf);
    s.minButton = Rect(kMinButtonCenterX - kWindowButtonHalf, kWindowButtonCenterY - kWindowButtonHalf,
                       kMinButtonCenterX + kWindowButtonHalf, kWindowButtonCenterY + kWindowButtonHalf);

    // 页面内容区域 = 标题栏以下整块。英雄页/向导页不再有几何差异；页内控件坐标
    // 由各 pages_*.cpp 按设计稿绝对坐标裁定（维护/卸载/消息页仍以此为居中基准）。
    s.contentCard = Rect(0.0f, titleH, W, H);

    return s;
}

bool HitTest(const D2D1_RECT_F& rectDip, const D2D1_POINT_2F& pointDip) {
    return pointDip.x >= rectDip.left && pointDip.x <= rectDip.right &&
           pointDip.y >= rectDip.top && pointDip.y <= rectDip.bottom;
}

D2D1_POINT_2F PageOffsetDip(const D2D1_RECT_F& contentCard) {
    // contentCard = (0 + m, titleH + m, W + m, H + m)，故偏移直接由此反推，不重复传参。
    return D2D1::Point2F(contentCard.left, contentCard.top - layout::kTitleBarHeight);
}

UINT SafeDpi(UINT dpi) { return dpi != 0 ? dpi : layout::kFallbackDpi; }

float ClientPxToDipScale(UINT dpi) { return 96.0f / static_cast<float>(SafeDpi(dpi)); }

}  // namespace spk
