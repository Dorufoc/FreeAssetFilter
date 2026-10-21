//
// layout.cpp - 900x600 DIP 布局外壳实现（Frozen contract §6：全程 DIP）。
//
// 唯一职责：把冻结的 900x600 DIP 逻辑画布切成标题栏与内容区（向导页另加顶部横向
// 步骤区与底部按钮条），并提供 DIP 命中测试与 DPI 守卫。所有坐标均为 DIP，绝不乘 DPI。
//
#include "render/layout.h"

#include "render/app_state.h"

namespace faf {

namespace {

// 便利构造：以左/上/右/下 4 边 DIP 值建矩形。
D2D1_RECT_F Rect(float left, float top, float right, float bottom) {
    return D2D1_RECT_F{left, top, right, bottom};
}

// 空矩形（英雄页无步骤区/无底部条）。
D2D1_RECT_F EmptyRect() { return Rect(0.0f, 0.0f, 0.0f, 0.0f); }

}  // namespace

bool IsHeroPage(int page) {
    // Welcome=0 / Finish=4，以及只追加到末尾的维护页(5)/卸载确认(6)/消息(7)。
    return page == Welcome || page == Finish || page >= Maintenance;
}

ShellLayout ComputeShellLayout(bool hero) {
    const float W = layout::kCanvasWidth;
    const float H = layout::kCanvasHeight;
    const float titleH = layout::kTitleBarHeight;
    const float stepperH = layout::kStepperHeight;
    const float bottomH = layout::kBottomBarHeight;
    const float margin = spacing::L;  // 24：卡片外留白（token，无魔法数）

    ShellLayout s{};

    // --- 标题栏（自绘；含最小化/关闭命中区）---
    s.titleBar = Rect(0.0f, 0.0f, W, titleH);
    const float btnW = layout::kWindowButtonWidth;
    s.closeButton = Rect(W - btnW, 0.0f, W, titleH);
    s.minButton = Rect(W - 2.0f * btnW, 0.0f, W - btnW, titleH);

    if (hero) {
        // 英雄页：无顶部步骤区、无底部条；内容卡片占满标题栏以下（仅留 margin）。
        s.stepper = EmptyRect();
        s.bottomBar = EmptyRect();
        s.contentCard = Rect(margin, titleH + margin, W - margin, H - margin);
        return s;
    }

    // --- 向导页：顶部横向步骤区 + 内容卡片 + 底部按钮条（全宽）---
    s.stepper = Rect(0.0f, titleH, W, titleH + stepperH);
    s.contentCard = Rect(margin, s.stepper.bottom + margin, W - margin, H - bottomH - margin);
    s.bottomBar = Rect(0.0f, H - bottomH, W, H);

    return s;
}

bool HitTest(const D2D1_RECT_F& rectDip, const D2D1_POINT_2F& pointDip) {
    return pointDip.x >= rectDip.left && pointDip.x <= rectDip.right &&
           pointDip.y >= rectDip.top && pointDip.y <= rectDip.bottom;
}

UINT SafeDpi(UINT dpi) { return dpi != 0 ? dpi : layout::kFallbackDpi; }

float ClientPxToDipScale(UINT dpi) { return 96.0f / static_cast<float>(SafeDpi(dpi)); }

}  // namespace faf
