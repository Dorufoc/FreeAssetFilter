//
// hero_art.cpp - 设计稿品牌图形（四圆 + Sopeek 词标）的 Direct2D 实现。
//
// 词标不是字体排版，也不是位图：它是设计稿里 9 条 SVG path 的精确重放（弧线已在
// 生成期转成三次贝塞尔），因此与设计稿逐像素同形，且任意 DPI 下都锐利。
//
#include "render/hero_art.h"

#include <algorithm>

namespace spk {

namespace {

const HeroArtCmd kWordmarkCommands[] = {
#include "render/hero_art_paths.inc"
};

}  // namespace

HRESULT HeroArt::Initialize(ID2D1Factory1* factory) {
    wordmark_.Reset();
    if (!factory) return E_POINTER;

    ComPtr<ID2D1PathGeometry> geometry;
    HRESULT hr = factory->CreatePathGeometry(geometry.GetAddressOf());
    if (FAILED(hr)) return hr;

    ComPtr<ID2D1GeometrySink> sink;
    hr = geometry->Open(sink.GetAddressOf());
    if (FAILED(hr)) return hr;

    // 复合路径（Illustrator「减去/联合」导出的多条轮廓）依赖非零环绕规则出洞。
    sink->SetFillMode(D2D1_FILL_MODE_WINDING);
    for (const HeroArtCmd& cmd : kWordmarkCommands) {
        switch (cmd.verb) {
            case 0:
                sink->BeginFigure(D2D1::Point2F(cmd.x1, cmd.y1), D2D1_FIGURE_BEGIN_FILLED);
                break;
            case 1:
                sink->AddBezier(D2D1::BezierSegment(D2D1::Point2F(cmd.x1, cmd.y1),
                                                   D2D1::Point2F(cmd.x2, cmd.y2),
                                                   D2D1::Point2F(cmd.x3, cmd.y3)));
                break;
            case 2:
                sink->EndFigure(D2D1_FIGURE_END_CLOSED);
                break;
            default:
                break;
        }
    }
    hr = sink->Close();
    if (FAILED(hr)) return hr;

    wordmark_ = std::move(geometry);
    return S_OK;
}

void HeroArt::DrawArt(ID2D1DeviceContext* dc, const Theme& theme, float alpha, float scale, float dx,
                      float dy) const {
    if (!dc) return;

    D2D1_MATRIX_3X2_F saved{};
    dc->GetTransform(&saved);
    dc->SetTransform(
        D2D1::Matrix3x2F::Scale(scale, scale) * D2D1::Matrix3x2F::Translation(dx, dy) * saved);

    auto tinted = [alpha](D2D1_COLOR_F c) {
        c.a *= alpha;
        return c;
    };

    // 1) 右：蓝色品牌圆（cls-5 减去_25 / 减去_27）
    ComPtr<ID2D1SolidColorBrush> blue;
    if (SUCCEEDED(dc->CreateSolidColorBrush(tinted(theme.heroBlue), blue.GetAddressOf()))) {
        dc->FillEllipse(
            D2D1::Ellipse(D2D1::Point2F(hero::kBlueCenterX, hero::kBlueCenterY), hero::kCircleRadius,
                          hero::kCircleRadius),
            blue.Get());
        // 「减去_25 - 轮廓」：贴边 1px 高光描边（rgba(255,255,255,0.16)）。
        ComPtr<ID2D1SolidColorBrush> ring;
        if (SUCCEEDED(dc->CreateSolidColorBrush(tinted(theme.heroRing), ring.GetAddressOf()))) {
            const float r = hero::kCircleRadius - 0.5f;
            dc->DrawEllipse(D2D1::Ellipse(D2D1::Point2F(hero::kBlueCenterX, hero::kBlueCenterY), r, r),
                            ring.Get(), 1.0f);
        }
    }
    // 2) 左：青色品牌圆（SVG 最后一个不透明圆为「减去_24」，覆盖蓝圆交集）
    ComPtr<ID2D1SolidColorBrush> teal;
    if (SUCCEEDED(dc->CreateSolidColorBrush(tinted(theme.heroTeal), teal.GetAddressOf()))) {
        dc->FillEllipse(
            D2D1::Ellipse(D2D1::Point2F(hero::kTealCenterX, hero::kTealCenterY), hero::kCircleRadius,
                          hero::kCircleRadius),
            teal.Get());
    }
    // 3) 两枚淡色圆（cls-7 #00FFD6 @18% / cls-8 #008FFF @22%）
    ComPtr<ID2D1SolidColorBrush> glowTeal;
    if (SUCCEEDED(dc->CreateSolidColorBrush(tinted(theme.heroGlowTeal), glowTeal.GetAddressOf()))) {
        dc->FillEllipse(D2D1::Ellipse(D2D1::Point2F(hero::kGlowTealCenterX, hero::kGlowTealCenterY),
                                      hero::kCircleRadius, hero::kCircleRadius),
                        glowTeal.Get());
    }
    ComPtr<ID2D1SolidColorBrush> glowBlue;
    if (SUCCEEDED(dc->CreateSolidColorBrush(tinted(theme.heroGlowBlue), glowBlue.GetAddressOf()))) {
        dc->FillEllipse(D2D1::Ellipse(D2D1::Point2F(hero::kGlowBlueCenterX, hero::kGlowBlueCenterY),
                                      hero::kCircleRadius, hero::kCircleRadius),
                        glowBlue.Get());
    }
    // 4) Sopeek 词标（组_48，fill #091935）
    if (wordmark_.Get()) {
        ComPtr<ID2D1SolidColorBrush> ink;
        if (SUCCEEDED(dc->CreateSolidColorBrush(tinted(theme.heroWordmark), ink.GetAddressOf()))) {
            D2D1_MATRIX_3X2_F artTransform{};
            dc->GetTransform(&artTransform);
            dc->SetTransform(D2D1::Matrix3x2F::Translation(hero::kWordmarkLeft, hero::kWordmarkTop) *
                             artTransform);
            dc->FillGeometry(wordmark_.Get(), ink.Get());
            dc->SetTransform(artTransform);
        }
    }

    dc->SetTransform(saved);
}

void HeroArt::RenderHeroArt(ID2D1DeviceContext* dc, const Theme& theme, float alpha) const {
    DrawArt(dc, theme, alpha, 1.0f, 0.0f, 0.0f);
}

void HeroArt::RenderHeroArtIn(ID2D1DeviceContext* dc, const Theme& theme, const D2D1_RECT_F& rect,
                              float alpha) const {
    if (!dc) return;
    const float artW = hero::kArtRight - hero::kArtLeft;
    const float artH = hero::kArtBottom - hero::kArtTop;
    const float rectW = rect.right - rect.left;
    const float rectH = rect.bottom - rect.top;
    if (artW <= 0.0f || artH <= 0.0f || rectW <= 0.0f || rectH <= 0.0f) return;

    const float scale = std::min(rectW / artW, rectH / artH);
    const float dx = rect.left + (rectW - artW * scale) * 0.5f - hero::kArtLeft * scale;
    const float dy = rect.top + (rectH - artH * scale) * 0.5f - hero::kArtTop * scale;
    DrawArt(dc, theme, alpha, scale, dx, dy);
}

}  // namespace spk
