#pragma once
//
// layout.h - 640x540 DIP 布局外壳（Frozen contract §6：全程 DIP）。
//
// 本文件是 shell 矩形几何的**唯一来源**：installer_window.cpp 不再内联硬编码
// 顶部步骤区高 / 底部条高 / 内容卡片矩形。所有布局与绘制坐标一律为 DIP（96 基准
// 逻辑单位），由 ID2D1DeviceContext::SetDpi 负责放大——此处**绝不**乘 DPI（§6 严格
// 禁止对绘制坐标乘 DPI，否则 HiDPI 下双重缩放并裁切）。
//
// 2026-11 改版（install_design 四张设计稿）：画布由 900x600 改为 **640x540**，
// 去掉顶部步骤带与底部按钮条——设计稿只有「自绘标题栏（56 DIP）+ 整页内容」，
// 每个页面自带自己的主按钮/返回链接。因此 stepper 与 bottomBar 恒为空矩形，
// ComputeShellLayout(bool hero) 的 hero 形参保留仅为兼容既有调用点。
//
// 页内几何（标题/输入框/复选框/进度条等）的唯一来源是 pages_*.cpp；本模块只负责
// 外壳级矩形（标题栏、窗口按钮命中区、页面内容区域）。
//
#include <windows.h>

#include <d2d1.h>

#include "render/theme.h"  // 唯一 token 表：spacing/radius/fontsize

namespace spk {

// shell 布局的冻结度量（全部 DIP）。
namespace layout {

constexpr float kCanvasWidth = 640.0f;
constexpr float kCanvasHeight = 540.0f;
constexpr float kTitleBarHeight = 56.0f;  // 自绘标题栏高（Logo 26px @ y16，图标中心 y≈29）
constexpr float kWindowButtonWidth = 32.0f;      // 标题栏最小化/关闭命中区宽（图标中心间距 30.8）
constexpr float kWindowButtonHeight = 32.0f;     // 命中区高（图标中心 y≈29）
constexpr float kWindowButtonRightInset = 10.5f; // 关闭命中区右缘到窗口右缘

// 设计稿页内常量（供页面模块复用，避免各自写魔法数）。
constexpr float kContentLeft = 38.0f;     // 控件左缘（设计稿 678-640）
constexpr float kContentWidth = 564.0f;   // 控件宽（678..1242）
constexpr float kPageTitleLeft = 102.0f;  // 页标题左缘（设计稿 742-640）
constexpr float kLabelLeft = 37.0f;       // 控件内文字左缩进（715-678 / 721-684 / 715-678）

// 旧字段（兼容保留）：新版设计稿没有步骤带与底部条，两者恒为 0。
constexpr float kStepperHeight = 0.0f;
constexpr float kBottomBarHeight = 0.0f;

// DPI 探测失败（返回 0）时的回退值；SafeDpi 用之避免 96/dpi 除零。
constexpr UINT kFallbackDpi = 96;

}  // namespace layout

// shell 的冻结几何（全部为 DIP 坐标）。由 ComputeShellLayout() 产出。
// 新版只有一个外壳形状：stepper 与 bottomBar 恒为空矩形（{0,0,0,0}）。
struct ShellLayout {
    D2D1_RECT_F titleBar;     // 自绘标题栏（含窗口按钮命中区）
    D2D1_RECT_F stepper;      // 恒为空（保留字段：旧步骤带已删除）
    D2D1_RECT_F contentCard;  // 页面内容区域（标题栏以下整块）
    D2D1_RECT_F bottomBar;    // 恒为空（保留字段：旧底部条已删除）
    D2D1_RECT_F minButton;    // 标题栏最小化命中区
    D2D1_RECT_F closeButton;  // 标题栏关闭命中区
};

// 英雄页判定（无外壳导航的页面：欢迎页(0)、完成页(4)，以及维护/卸载追加页 5/6/7）。
// 新版所有页面都没有外壳导航，本函数仅保留给既有调用点（不参与几何计算）。
// 页面枚举（app_state.h::Page）为**只追加**：0..4（Welcome, License, Configure,
// Progress, Finish）顺序冻结，维护页/卸载确认页/消息页一律追加到末尾，禁止重排或插入。
bool IsHeroPage(int page);

// 依据冻结的 640x540 DIP 逻辑画布计算 shell 几何（纯函数、无副作用、不依赖 DPI）。
// `hero` 已不影响结果（新版无步骤带/无底部条），保留形参兼容既有调用。
ShellLayout ComputeShellLayout(bool hero);

// 命中测试：DIP 点对 DIP 矩形（左闭右闭）。**不**做任何 DPI 重新缩放（§6）。
bool HitTest(const D2D1_RECT_F& rectDip, const D2D1_POINT_2F& pointDip);

// 页面绘制/命中的坐标原点偏移（DIP）：页内常量写的是「画布坐标」，而页面拿到的
// contentCard 含 Win10 兜底的外扩边距 —— 偏移 = (contentCard.left,
// contentCard.top - kTitleBarHeight)。Win11（无边距）时为 (0,0)。
D2D1_POINT_2F PageOffsetDip(const D2D1_RECT_F& contentCard);

// §6 DPI 守卫：窗口/系统 DPI 探测为 0 时回退 96，避免后续 96/dpi 除零。
UINT SafeDpi(UINT dpi);

// §6 输入坐标换算比例：客户端物理像素 → DIP（= kFallbackDpi / SafeDpi(dpi)）。
// 仅用于把鼠标命中点换算回 DIP；**绘制/布局本身绝不乘 DPI**。
float ClientPxToDipScale(UINT dpi);

}  // namespace spk
