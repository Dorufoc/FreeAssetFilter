//
// layout.cpp - 900x600 DIP 布局外壳实现（Frozen contract §6：全程 DIP）。
//
// 唯一职责：把冻结的 900x600 DIP 逻辑画布切成左步骤栏（品牌头 + 步骤列表）与
// 右区（内容卡片 + 底部按钮条），并提供 DIP 命中测试与 DPI 守卫。
// 所有坐标均为 DIP，绝不乘 DPI。
//
#include "render/layout.h"

namespace faf {

namespace {

// 便利构造：以左/上/右/下 4 边 DIP 值建矩形。
D2D1_RECT_F Rect(float left, float top, float right, float bottom) {
    return D2D1_RECT_F{left, top, right, bottom};
}

}  // namespace

ShellLayout ComputeShellLayout() {
    const float W = layout::kCanvasWidth;
    const float H = layout::kCanvasHeight;
    const float titleH = layout::kTitleBarHeight;
    const float railW = layout::kRailWidth;
    const float bottomH = layout::kBottomBarHeight;
    const float margin = spacing::L;  // 24：卡片外留白（token，无魔法数）

    ShellLayout s{};

    // --- 标题栏（自绘；含最小化/关闭命中区）---
    s.titleBar = Rect(0.0f, 0.0f, W, titleH);
    const float btnW = layout::kWindowButtonWidth;
    s.closeButton = Rect(W - btnW, 0.0f, W, titleH);
    s.minButton = Rect(W - 2.0f * btnW, 0.0f, W - btnW, titleH);

    // --- 左步骤栏：品牌头（~96 DIP）+ 步骤列表 ---
    s.rail = Rect(0.0f, titleH, railW, H);
    s.brandHeader = Rect(0.0f, titleH, railW, titleH + layout::kBrandHeaderHeight);
    s.stepList = Rect(0.0f, s.brandHeader.bottom, railW, H);

    // --- 右区：内容卡片 + 底部按钮条（互为唯一定义）---
    // UI-fix：内容卡片顶部原先经「标题区」（titleZone 无任何绘制方）多下推 96+24 DIP，
    // 使标题栏与内容卡片之间留出 ~120 DIP 空带；现改为仅留一个 spacing::L
    //（top = titleH + 24 = 56），底边保持 H - bottomH - margin = 504。
    s.rightArea = Rect(railW, titleH, W, H);
    s.contentCard =
        Rect(railW + margin, titleH + margin, W - margin, H - bottomH - margin);
    s.bottomBar = Rect(railW, H - bottomH, W, H);

    return s;
}

bool HitTest(const D2D1_RECT_F& rectDip, const D2D1_POINT_2F& pointDip) {
    return pointDip.x >= rectDip.left && pointDip.x <= rectDip.right &&
           pointDip.y >= rectDip.top && pointDip.y <= rectDip.bottom;
}

UINT SafeDpi(UINT dpi) { return dpi != 0 ? dpi : layout::kFallbackDpi; }

float ClientPxToDipScale(UINT dpi) { return 96.0f / static_cast<float>(SafeDpi(dpi)); }

}  // namespace faf
