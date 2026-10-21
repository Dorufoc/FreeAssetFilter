#pragma once
//
// layout.h - 900x600 DIP 布局外壳（Frozen contract §6：全程 DIP）。
//
// 本文件是 shell 矩形几何的**唯一来源**：installer_window.cpp 不再内联硬编码
// 顶部步骤区高 / 底部条高 / 内容卡片矩形。所有布局与绘制坐标一律为 DIP（96 基准
// 逻辑单位），由 ID2D1DeviceContext::SetDpi 负责放大——此处**绝不**乘 DPI（§6 严格
// 禁止对绘制坐标乘 DPI，否则 HiDPI 下双重缩放并裁切）。
//
// 绘制顺序遵循契约 §5：Win11 仅按 alpha 绘制内容卡片（向导页另加顶部步骤区与底部条），
// 其余区域保持透明让 DWM Mica 透出；本模块只负责几何，不决定是否铺不透明底。
//
// 追加需求（2026-10-18）：左栏已删除，改为顶部横向步骤区（3 节点）；欢迎/完成页为
// 英雄页（无步骤区、无底部条，内容卡片占满标题栏以下）。
//
#include <windows.h>

#include <d2d1.h>

#include "render/theme.h"  // 唯一 token 表：spacing/radius/fontsize

namespace faf {

// shell 布局的冻结度量（全部 DIP）。禁止使用旧 720x480 常量。
namespace layout {

constexpr float kCanvasWidth = 900.0f;        // §4：逻辑画布宽（DIP）
constexpr float kCanvasHeight = 600.0f;       // §4：逻辑画布高（DIP）
constexpr float kTitleBarHeight = 32.0f;      // 自绘标题栏高
constexpr float kStepperHeight = 84.0f;       // 顶部横向步骤区高（向导页）
constexpr float kBottomBarHeight = 72.0f;     // 底部按钮条高（向导页）
constexpr float kWindowButtonWidth = 46.0f;   // 标题栏最小化/关闭命中区宽

// DPI 探测失败（返回 0）时的回退值；SafeDpi 用之避免 96/dpi 除零。
constexpr UINT kFallbackDpi = 96;

}  // namespace layout

// shell 的冻结几何（全部为 DIP 坐标）。由 ComputeShellLayout() 产出。
// 英雄页（无步骤区/无底部条）：stepper 与 bottomBar 为空矩形（{0,0,0,0}）。
struct ShellLayout {
    D2D1_RECT_F titleBar;     // 自绘标题栏（含窗口按钮命中区）
    D2D1_RECT_F stepper;      // 顶部横向步骤区（英雄页为空）
    D2D1_RECT_F contentCard;  // 内容卡片（圆角）
    D2D1_RECT_F bottomBar;    // 底部按钮条（英雄页为空）
    D2D1_RECT_F minButton;    // 标题栏最小化命中区
    D2D1_RECT_F closeButton;  // 标题栏关闭命中区
};

// 英雄页判定（无步骤区/无底部条/无外壳导航）：欢迎页(0)、完成页(4)，以及维护/卸载
// 追加页（>= Maintenance，即 5/6/7）。
// 页面枚举（app_state.h::Page）为**只追加**：0..4（Welcome, License, Configure,
// Progress, Finish）顺序冻结，维护页/卸载确认页/消息页一律追加到末尾，禁止重排或插入。
bool IsHeroPage(int page);

// 依据冻结的 900x600 DIP 逻辑画布计算 shell 几何。
// `hero = true`：英雄页几何（无步骤区、无底部条，卡片占满标题栏以下）。
// `hero = false`：向导页几何（顶部步骤区 + 内容卡片 + 底部条）。
// 纯函数、无副作用、不依赖 DPI；同样输入永远产出同样输出（DIP 不变）。
ShellLayout ComputeShellLayout(bool hero);

// 命中测试：DIP 点对 DIP 矩形（左闭右闭）。**不**做任何 DPI 重新缩放（§6）。
bool HitTest(const D2D1_RECT_F& rectDip, const D2D1_POINT_2F& pointDip);

// §6 DPI 守卫：窗口/系统 DPI 探测为 0 时回退 96，避免后续 96/dpi 除零。
UINT SafeDpi(UINT dpi);

// §6 输入坐标换算比例：客户端物理像素 → DIP（= kFallbackDpi / SafeDpi(dpi)）。
// 仅用于把鼠标命中点换算回 DIP；**绘制/布局本身绝不乘 DPI**。
float ClientPxToDipScale(UINT dpi);

}  // namespace faf
