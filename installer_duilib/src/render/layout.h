#pragma once
//
// layout.h - 900x600 DIP 布局外壳（Frozen contract §6：全程 DIP）。
//
// 本文件是 shell 矩形几何的**唯一来源**：installer_window.cpp 不再内联硬编码
// 左栏宽 / 底部条高 / 内容卡片矩形。所有布局与绘制坐标一律为 DIP（96 基准逻辑
// 单位），由 ID2D1DeviceContext::SetDpi 负责放大——此处**绝不**乘 DPI（§6 严格
// 禁止对绘制坐标乘 DPI，否则 HiDPI 下双重缩放并裁切）。
//
// 绘制顺序遵循契约 §5：Win11 仅按 alpha 绘制左栏 / 内容卡片 / 底部条，其余区域
// 保持透明让 DWM Mica 透出；本模块只负责几何，不决定是否铺不透明底。
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
constexpr float kRailWidth = 240.0f;          // 左步骤栏宽
constexpr float kBrandHeaderHeight = 96.0f;   // 左栏品牌头高（rail 顶部）
constexpr float kBottomBarHeight = 72.0f;     // 底部按钮条高
constexpr float kWindowButtonWidth = 46.0f;   // 标题栏最小化/关闭命中区宽

// DPI 探测失败（返回 0）时的回退值；SafeDpi 用之避免 96/dpi 除零。
constexpr UINT kFallbackDpi = 96;

}  // namespace layout

// shell 的冻结几何（全部为 DIP 坐标）。由 ComputeShellLayout() 产出。
struct ShellLayout {
    D2D1_RECT_F titleBar;     // 自绘标题栏（含窗口按钮命中区）
    D2D1_RECT_F rail;         // 左步骤栏（标题栏之下到底部）
    D2D1_RECT_F brandHeader;  // 左栏品牌头（rail 顶部 ~96 DIP）
    D2D1_RECT_F stepList;     // 左栏步骤列表区（brandHeader 之下）
    D2D1_RECT_F rightArea;    // 右区外框（rail 右侧）
    D2D1_RECT_F contentCard;  // 内容卡片（圆角；top = 标题栏下沿 + spacing::L = 56）
    D2D1_RECT_F bottomBar;    // 底部按钮条
    D2D1_RECT_F minButton;    // 标题栏最小化命中区
    D2D1_RECT_F closeButton;  // 标题栏关闭命中区
};

// 依据冻结的 900x600 DIP 逻辑画布计算 shell 几何。
// 纯函数、无副作用、不依赖 DPI；同样输入永远产出同样输出（DIP 不变）。
ShellLayout ComputeShellLayout();

// 命中测试：DIP 点对 DIP 矩形（左闭右闭）。**不**做任何 DPI 重新缩放（§6）。
bool HitTest(const D2D1_RECT_F& rectDip, const D2D1_POINT_2F& pointDip);

// §6 DPI 守卫：窗口/系统 DPI 探测为 0 时回退 96，避免后续 96/dpi 除零。
UINT SafeDpi(UINT dpi);

// §6 输入坐标换算比例：客户端物理像素 → DIP（= kFallbackDpi / SafeDpi(dpi)）。
// 仅用于把鼠标命中点换算回 DIP；**绘制/布局本身绝不乘 DPI**。
float ClientPxToDipScale(UINT dpi);

}  // namespace faf
