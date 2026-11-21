#pragma once
//
// hero_art.h - 设计稿「英雄页 / 安装完成」的品牌图形（唯一实现）。
//
// 英雄页与完成页共用的图形：两枚品牌圆（青 #52DAC4 / 蓝 #70B5EA）、两枚淡色圆
// （#00FFD6 @18% / #008FFF @22%）、以及 Sopeek 词标（9 条 SVG 路径，fill #091935）。
//
// 坐标来源：`src/sopeek/resources/icons/install_design/英雄页.svg`（1920x1080 artboard，
// 窗口矩形 translate(640 268)）。本文件里的常量已换算为**窗口局部 DIP**（减 640/268）。
// 词标的路径数据由 `tools/gen_hero_art.py` 从同一 SVG 生成到 `hero_art_paths.inc`
// （组_48 的 9 条 path，已把弧线转成三次贝塞尔），运行期只做 MoveTo/CubicTo/Close。
//
// 矢量绘制（非位图）：任何 DPI 下都清晰，且不需要额外资源文件。
//
#include <windows.h>

#include <d2d1_1.h>
#include <d2d1_1helper.h>

#include "render/render_context.h"  // spk::ComPtr
#include "render/theme.h"

namespace spk {

// 设计稿换算后的几何常量（窗口局部 DIP；窗口宽 640、高 540）。
namespace hero {
// 两枚品牌圆（cls-4 / cls-5），半径同为 70。
constexpr float kCircleRadius = 70.0f;
constexpr float kTealCenterX = 275.197f;  // translate(845.197 376.111) + 70 - 640
constexpr float kTealCenterY = 178.111f;  // 376.111 + 70 - 268
constexpr float kBlueCenterX = 363.866f;  // translate(933.866 404.111) + 70 - 640
constexpr float kBlueCenterY = 206.111f;
// 两枚淡色圆（cls-7 / cls-8）。
constexpr float kGlowTealCenterX = 258.063f;  // translate(828.063 559.996) + 70 - 640
constexpr float kGlowTealCenterY = 361.996f;
constexpr float kGlowBlueCenterX = 381.933f;  // translate(951.933 549) + 70 - 640
constexpr float kGlowBlueCenterY = 351.000f;
// 词标（组_48 translate(827.297 426.181) - (640,268)）。
constexpr float kWordmarkLeft = 187.297f;
constexpr float kWordmarkTop = 158.181f;
constexpr float kWordmarkWidth = 266.906f;   // 生成器报告的组局部 ink 宽度
constexpr float kWordmarkHeight = 75.754f;   // 生成器报告的组局部 ink 高度
// 整组图形的 ink 包围盒（词标 + 四圆），用于任意矩形内等比居中铺放。
constexpr float kArtLeft = 185.797f;
constexpr float kArtTop = 108.111f;
constexpr float kArtRight = 452.703f;
constexpr float kArtBottom = 432.000f;
}  // namespace hero

// 词标路径命令（由 tools/gen_hero_art.py 生成；verb 0=Move 1=Cubic 2=Close）。
struct HeroArtCmd {
    unsigned char verb;
    float x1, y1, x2, y2, x3, y3;
};

class HeroArt {
public:
    HeroArt() = default;

    // 建一次路径几何（需要 D2D 工厂，生命周期须长于本对象）。可重复调用（幂等重建）。
    HRESULT Initialize(ID2D1Factory1* factory);
    bool IsReady() const noexcept { return wordmark_.Get() != nullptr; }

    // 按设计稿 1:1 绝对坐标绘制英雄页图形（原点 = 窗口左上角，含四圆 + 词标）。
    void RenderHeroArt(ID2D1DeviceContext* dc, const Theme& theme, float alpha) const;

    // 把同一组图形等比居中铺进任意矩形（「正在安装」页宣传图的兜底画面）。
    void RenderHeroArtIn(ID2D1DeviceContext* dc, const Theme& theme, const D2D1_RECT_F& rect,
                         float alpha) const;

private:
    // scale/offset 把设计稿坐标映射到目标位置；alpha 乘入全部颜色。
    void DrawArt(ID2D1DeviceContext* dc, const Theme& theme, float alpha, float scale, float dx,
                 float dy) const;

    ComPtr<ID2D1PathGeometry> wordmark_;
};

}  // namespace spk
