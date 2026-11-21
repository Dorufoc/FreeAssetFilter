//
// controls_feedback.cpp - WinUI3 可复用控件 B：ProgressBar / LicenseBox / StepItem（Todo 8）。
//
// 实现 controls_base.h 的 Widget 接口。坐标/DIP、token、动画均按头文件契约。
// 控件不自持帧时钟：过渡经 BindAnimator 注入的 Animator 推进（宿主负责 tick 后
// 请求重绘）。LicenseBox 的滚动仅做数值/状态运算，绝不阻塞 UI 线程。
//
#include "render/controls_feedback.h"

#include <d2d1_1helper.h>

#include "render/render_context.h"  // spk::ComPtr（最小 COM RAII 指针）

#include <algorithm>
#include <atomic>
#include <cmath>

namespace spk {

namespace {

// 每实例唯一名（Animator 按名称复用 AnimValue，故控件间必须唯一）。
std::atomic<unsigned> g_feedbackSerial{0};

std::string SerialName(const char* kind, unsigned serial, const char* prop) {
    return std::string(kind) + std::to_string(serial) + "." + prop;
}

ComPtr<ID2D1SolidColorBrush> MakeBrush(ID2D1DeviceContext* dc, const D2D1_COLOR_F& color) {
    ComPtr<ID2D1SolidColorBrush> brush;
    if (!dc) return brush;
    dc->CreateSolidColorBrush(color, brush.GetAddressOf());
    return brush;
}

// 按 t (0..1) 缩放 alpha（用作叠加/淡出）。
D2D1_COLOR_F ScaleAlpha(const D2D1_COLOR_F& c, float t) {
    D2D1_COLOR_F out = c;
    out.a *= std::clamp(t, 0.0f, 1.0f);
    return out;
}

// 直线 alpha 混合（分量插值；用于状态色过渡）。
D2D1_COLOR_F Mix(const D2D1_COLOR_F& a, const D2D1_COLOR_F& b, float t) {
    const float u = std::clamp(t, 0.0f, 1.0f);
    D2D1_COLOR_F out;
    out.r = a.r + (b.r - a.r) * u;
    out.g = a.g + (b.g - a.g) * u;
    out.b = a.b + (b.b - a.b) * u;
    out.a = a.a + (b.a - a.a) * u;
    return out;
}

// 绘制一行文字（竖直居中；text 为空则跳过）。
void DrawLine(ID2D1DeviceContext* dc, const TextFactory* text, const std::wstring& s,
              const D2D1_RECT_F& rect, float size, DWRITE_FONT_WEIGHT weight,
              DWRITE_TEXT_ALIGNMENT align, const D2D1_COLOR_F& color) {
    if (!text || !text->IsReady() || s.empty()) return;
    ComPtr<IDWriteTextFormat> fmt;
    if (FAILED(text->CreateFormat(size, weight, align, DWRITE_PARAGRAPH_ALIGNMENT_CENTER,
                                  fmt.GetAddressOf()))) {
        return;
    }
    fmt->SetWordWrapping(DWRITE_WORD_WRAPPING_NO_WRAP);
    ComPtr<ID2D1SolidColorBrush> brush = MakeBrush(dc, color);
    if (!brush) return;
    dc->DrawText(s.c_str(), static_cast<UINT32>(s.size()), fmt.Get(), rect, brush.Get());
}

// 完成对勾：D2D 自绘圆角矢量勾（两段折线 + 圆头端点 / 圆角连接）。
// 取代图标字体字形（原 glyph::Check(U+E73E)，该字形本尺寸下笔画中位宽仅 2px）。
// 注：历史观测到的「对勾断口」真正成因并非字形光栅化——是「下一节点」的横向连接线自
// 上一节点中心起画（宽 2.0 DIP、位于 cy），覆盖了上一节点圆盘内的对勾（仅换字形仍断，
// 位置一致，见证据 stepper-check-path）。修复 = 本自绘矢量勾（笔画连续、宽度可控，不受
// 字形 hinting / 光栅化影响）+ 连接线起点退到上一节点圆盘右缘，二者缺一不可。
// 范式来源 pages_progress.cpp::DrawSuccessCheck。
void DrawCheckMark(ID2D1DeviceContext* dc, float cx, float cy, float r,
                   const D2D1_COLOR_F& color) {
    if (!dc || r <= 0.0f) return;
    ComPtr<ID2D1SolidColorBrush> brush = MakeBrush(dc, color);
    if (!brush) return;

    // 勾外接尺寸略大于半径；P0=左下起点，P1=折点（拐角），P2=右上终点。
    const float s = r * 1.15f;
    const D2D1_POINT_2F p0 = D2D1::Point2F(cx - 0.32f * s, cy + 0.02f * s);
    const D2D1_POINT_2F p1 = D2D1::Point2F(cx - 0.10f * s, cy + 0.24f * s);
    const D2D1_POINT_2F p2 = D2D1::Point2F(cx + 0.34f * s, cy - 0.28f * s);

    // 圆头端点 + 圆角连接：ID2D1DeviceContext 无 CreateStrokeStyle，经 GetFactory 走 ID2D1Factory。
    ComPtr<ID2D1StrokeStyle> stroke;
    {
        ComPtr<ID2D1Factory> factory;
        dc->GetFactory(factory.GetAddressOf());
        if (factory) {
            const D2D1_STROKE_STYLE_PROPERTIES ssp = D2D1::StrokeStyleProperties(
                D2D1_CAP_STYLE_ROUND, D2D1_CAP_STYLE_ROUND, D2D1_CAP_STYLE_ROUND,
                D2D1_LINE_JOIN_ROUND);
            factory->CreateStrokeStyle(ssp, nullptr, 0, stroke.GetAddressOf());
        }
    }

    // 笔画宽度 ≥2 DIP（144 DPI 下 ≥3px，远大于 1.5px 阈值）；随半径略增。
    const float strokeWidth = std::max(2.0f, 0.22f * r);
    dc->DrawLine(p0, p1, brush.Get(), strokeWidth, stroke.Get());
    dc->DrawLine(p1, p2, brush.Get(), strokeWidth, stroke.Get());
}

// Match the application's StyledScrollBar dimensions and OutCubic timing.
constexpr float kScrollbarRestWidth = 4.0f;
constexpr float kScrollbarHotWidth = 6.0f;
constexpr float kScrollbarInset = 2.0f;
constexpr float kScrollbarHitWidth = 12.0f;
constexpr CubicBezier kScrollbarEase{1.0f / 3.0f, 1.0f, 2.0f / 3.0f, 1.0f};

}  // namespace

// ============================= ProgressBar =================================

void ProgressBar::BindAnimator(Animator* animator) {
    animator_ = animator;
    if (!animator_) return;
    const unsigned serial = g_feedbackSerial.fetch_add(1, std::memory_order_relaxed);
    fillName_ = SerialName("progress", serial, "fill");
    marqueeName_ = SerialName("progress", serial, "marquee");
}

void ProgressBar::SetProgressPermille(int permille) {
    const int clamped = std::clamp(permille, 0, 1000);
    permille_ = clamped;
    StartFillAnim(static_cast<float>(clamped) / 1000.0f);
}

void ProgressBar::SetProgressFraction(float fraction) {
    const float f = std::clamp(fraction, 0.0f, 1.0f);
    SetProgressPermille(static_cast<int>(f * 1000.0f + 0.5f));
}

void ProgressBar::SetIndeterminate(bool indeterminate) {
    indeterminate_ = indeterminate;
    if (indeterminate_) EnsureMarquee();
}

void ProgressBar::StartFillAnim(float target) {
    if (!animator_) {
        fillFallback_ = target;
        return;
    }
    const float from = FillFraction();
    fillFallback_ = target;
    if (from == target) return;
    // 高频进度更新（~30fps）命中活动动画时只重定向终值：重启会清零轨迹推进，
    // 导致填充永远追不上目标（可见为长时间停在 50%~54%）。
    if (fillAnim_ && fillAnim_->IsActive()) {
        fillAnim_->Retarget(target);
        return;
    }
    // 220ms 标准缓动：新 permille 平滑插值，无视觉跳变。
    fillAnim_ = &animator_->Animate(fillName_, from, target, 220.0f, easing::Standard);
}

void ProgressBar::EnsureMarquee() {
    if (!indeterminate_ || !animator_) return;
    if (marqueeAnim_ && marqueeAnim_->IsActive()) return;
    // 循环跑马：终结后（下一次 Render）按同名重臂。Linear 保证匀速。
    marqueeAnim_ = &animator_->Animate(marqueeName_, 0.0f, 1.0f, 1300.0f, easing::Linear);
}

float ProgressBar::FillFraction() const {
    if (fillAnim_) return std::clamp(fillAnim_->Value(), 0.0f, 1.0f);
    return fillFallback_;
}

float ProgressBar::MarqueePhase() const {
    if (marqueeAnim_) return std::clamp(marqueeAnim_->Value(), 0.0f, 1.0f);
    return 0.0f;
}

bool ProgressBar::HitTest(float /*x*/, float /*y*/) const { return false; }  // 非交互

bool ProgressBar::OnInput(const InputEvent& /*event*/) { return false; }

void ProgressBar::Render(ID2D1DeviceContext* dc, const Theme& theme) {
    if (!dc) return;
    const float w = bounds_.right - bounds_.left;
    const float h = bounds_.bottom - bounds_.top;
    if (w <= 0.0f || h <= 0.0f) return;

    // 设计稿「矩形_146」：12 高胶囊轨道（r6）#EEEEEE + 1px #E9E9E9 描边，
    // 内部 8 高胶囊填充（r4，黑色 80%），四周各留 2 DIP 内边距。
    const float r = std::min(radius::Track, h * 0.5f);
    const D2D1_ROUNDED_RECT track = D2D1::RoundedRect(bounds_, r, r);

    ComPtr<ID2D1SolidColorBrush> trackBrush = MakeBrush(dc, theme.fieldFill);
    if (trackBrush) dc->FillRoundedRectangle(track, trackBrush.Get());
    ComPtr<ID2D1SolidColorBrush> strokeBrush = MakeBrush(dc, theme.fieldStroke);
    if (strokeBrush) dc->DrawRoundedRectangle(track, strokeBrush.Get(), 1.0f);

    ComPtr<ID2D1SolidColorBrush> fillBrush = MakeBrush(dc, theme.trackProgress);
    if (!fillBrush) return;

    const float pad = std::min(2.0f, h * 0.25f);
    const float fillH = std::max(1.0f, h - 2.0f * pad);
    const float fillR = std::min(radius::TrackFill, fillH * 0.5f);
    const float innerLeft = bounds_.left + pad;
    const float innerW = std::max(0.0f, w - 2.0f * pad);
    const D2D1_RECT_F inner =
        D2D1::RectF(innerLeft, bounds_.top + pad, innerLeft + innerW, bounds_.top + pad + fillH);

    if (indeterminate_) {
        EnsureMarquee();
        const float phase = MarqueePhase();
        const float barW = innerW * 0.35f;
        const float barLeft = innerLeft - barW + phase * (innerW + barW);
        const D2D1_RECT_F bar = D2D1::RectF(barLeft, inner.top, barLeft + barW, inner.bottom);
        dc->PushAxisAlignedClip(inner, D2D1_ANTIALIAS_MODE_PER_PRIMITIVE);
        dc->FillRoundedRectangle(D2D1::RoundedRect(bar, fillR, fillR), fillBrush.Get());
        dc->PopAxisAlignedClip();
        return;
    }

    const float frac = FillFraction();
    if (frac <= 0.0f) return;
    const float fillWidth = innerW * frac;
    const float capRadius = std::min(fillR, fillWidth * 0.5f);
    const auto fill = D2D1::RectF(inner.left, inner.top, inner.left + fillWidth, inner.bottom);
    dc->FillRoundedRectangle(D2D1::RoundedRect(fill, capRadius, fillR), fillBrush.Get());
}

// ============================== LicenseBox ==================================

LicenseBox::~LicenseBox() {
    if (layout_) {
        layout_->Release();
        layout_ = nullptr;
    }
}

void LicenseBox::SetBounds(const D2D1_RECT_F& rect) {
    bounds_ = rect;
    layoutDirty_ = true;
}

void LicenseBox::SetText(std::wstring text) {
    text_ = std::move(text);
    layoutDirty_ = true;
}

void LicenseBox::BindText(const TextFactory* text) {
    textFactory_ = text;
    layoutDirty_ = true;
}

void LicenseBox::BindWriteFactory(IDWriteFactory* factory) {
    writeFactory_ = factory;
    layoutDirty_ = true;
}

void LicenseBox::BindAnimator(Animator* animator) {
    scrollAnim_ = nullptr;
    scrollbarAnim_ = nullptr;
    animator_ = animator;
    if (animator_) {
        const unsigned serial = g_feedbackSerial.fetch_add(1, std::memory_order_relaxed);
        scrollName_ = SerialName("license", serial, "scroll");
        scrollbarName_ = SerialName("license", serial, "scrollbar");
    }
}

D2D1_RECT_F LicenseBox::ContentRect() const {
    return D2D1::RectF(bounds_.left + spacing::M, bounds_.top + spacing::M,
                       bounds_.right - spacing::M, bounds_.bottom - spacing::M);
}

bool LicenseBox::HitsScrollbar(float x, float y) const {
    const auto content = ContentRect();
    return x >= bounds_.right - kScrollbarHitWidth && x <= bounds_.right &&
           y >= content.top && y <= content.bottom && MaxScroll() > 0.0f;
}

void LicenseBox::UpdateScrollbarHover(bool hovered) {
    if (hovered == scrollbarHovered_) return;
    const float from = scrollbarAnim_ ? scrollbarAnim_->Value() : (scrollbarHovered_ ? 1.0f : 0.0f);
    scrollbarHovered_ = hovered;
    scrollbarAnim_ = animator_ && !animator_->ReduceMotion()
        ? &animator_->Animate(scrollbarName_, from, hovered ? 1.0f : 0.0f,
                             120.0f, kScrollbarEase)
        : nullptr;
}

float LicenseBox::ViewportHeight() const {
    const D2D1_RECT_F c = ContentRect();
    return std::max(0.0f, c.bottom - c.top);
}

void LicenseBox::EnsureLayout() const {
    if (!layoutDirty_) return;
    layoutDirty_ = false;
    if (layout_) {
        layout_->Release();
        layout_ = nullptr;
    }
    contentHeight_ = 0.0f;
    if (text_.empty()) return;  // 空文本：安全（无布局、无滚动）。

    const D2D1_RECT_F c = ContentRect();
    const float w = c.right - c.left;
    if (w <= 1.0f) return;

    if (!writeFactory_ || !textFactory_ || !textFactory_->IsReady()) {
        // 无排版工厂：按字号估算行数，保证滚动仍可用且不崩。
        const float lineH = fontsize::Body * 1.35f;
        float cpl = w / (fontsize::Body * 0.55f);
        if (cpl < 1.0f) cpl = 1.0f;
        const float lines = std::ceil(static_cast<float>(text_.size()) / cpl);
        contentHeight_ = lines * lineH;
        return;
    }

    ComPtr<IDWriteTextFormat> fmt;
    if (FAILED(textFactory_->CreateFormat(fontsize::Body, weight::Regular, fmt.GetAddressOf()))) {
        return;
    }
    fmt->SetWordWrapping(DWRITE_WORD_WRAPPING_WRAP);
    IDWriteTextLayout* layout = nullptr;
    if (FAILED(writeFactory_->CreateTextLayout(text_.c_str(), static_cast<UINT32>(text_.size()),
                                               fmt.Get(), w, 1.0e6f, &layout))) {
        return;
    }
    layout_ = layout;
    DWRITE_TEXT_METRICS metrics{};
    if (SUCCEEDED(layout_->GetMetrics(&metrics))) contentHeight_ = metrics.height;
}

float LicenseBox::ContentHeight() const {
    EnsureLayout();
    return contentHeight_;
}

float LicenseBox::MaxScroll() const {
    EnsureLayout();
    return std::max(0.0f, contentHeight_ - ViewportHeight());
}

float LicenseBox::ScrollOffset() const {
    const float raw = scrollAnim_ ? scrollAnim_->Value() : targetOffset_;
    return std::clamp(raw, 0.0f, MaxScroll());
}

void LicenseBox::SetTargetOffset(float target, bool animate) {
    const float clamped = std::clamp(target, 0.0f, MaxScroll());
    const float from = ScrollOffset();
    targetOffset_ = clamped;
    if (!animate || !animator_) {
        scrollAnim_ = nullptr;  // 立即到位
        return;
    }
    if (from == clamped) {
        scrollAnim_ = nullptr;
        return;
    }
    scrollAnim_ = &animator_->Animate(scrollName_, from, clamped, 160.0f, easing::Standard);
}

void LicenseBox::SetScrollOffset(float offset) { SetTargetOffset(offset, false); }

void LicenseBox::ScrollToBottom() { SetTargetOffset(MaxScroll(), true); }

bool LicenseBox::AtBottom() const {
    const float maxScroll = MaxScroll();
    if (maxScroll <= 0.0f) return true;
    return ScrollOffset() >= maxScroll - 0.5f;
}

float LicenseBox::ThumbHeight() const {
    const float h = ViewportHeight();
    return std::clamp(h * h / std::max(ContentHeight(), 1.0f), std::min(24.0f, h), h);
}

bool LicenseBox::HitTest(float x, float y) const {
    return x >= bounds_.left && x <= bounds_.right && y >= bounds_.top && y <= bounds_.bottom;
}

bool LicenseBox::OnInput(const InputEvent& event) {
    switch (event.kind) {
        case InputEvent::Wheel: {
            // key 为带符号滚动量（WHEEL_DELTA 单位）；正 = 向上滚。
            const float notches = static_cast<float>(event.key) / static_cast<float>(WHEEL_DELTA);
            const float step = fontsize::Body * 3.0f;
            // Sub-notch deltas arrive in quick succession; preserve each fractional DIP
            // without starting another easing curve before the previous frame is visible.
            const bool discrete = event.key % WHEEL_DELTA == 0;
            SetTargetOffset(std::clamp(targetOffset_, 0.0f, MaxScroll()) - notches * step, discrete);
            return true;
        }
        case InputEvent::Down:
            if (HitTest(event.x, event.y)) {
                dragging_ = true;
                dragStartY_ = event.y;
                dragStartOffset_ = ScrollOffset();
                SetScrollOffset(dragStartOffset_);
                const auto content = ContentRect();
                const float max = MaxScroll();
                draggingThumb_ = HitsScrollbar(event.x, event.y);
                UpdateScrollbarHover(draggingThumb_);
                if (draggingThumb_) {
                    const float thumbH = ThumbHeight();
                    const float top = content.top + (ViewportHeight() - thumbH) * dragStartOffset_ / max;
                    if (event.y < top || event.y > top + thumbH) {
                        dragging_ = draggingThumb_ = false;
                        SetTargetOffset(dragStartOffset_ + (event.y < top ? -1 : 1) * ViewportHeight(), true);
                    }
                }
                return true;
            }
            return false;
        case InputEvent::Move:
            if (dragging_) {
                const float ratio = draggingThumb_ ? MaxScroll() / std::max(1.0f, ViewportHeight() - ThumbHeight()) : -1.0f;
                SetTargetOffset(dragStartOffset_ + ratio * (event.y - dragStartY_), false);
                return true;
            }
            UpdateScrollbarHover(HitsScrollbar(event.x, event.y));
            return HitTest(event.x, event.y);
        case InputEvent::Up: {
            const bool wasDragging = dragging_;
            dragging_ = false;
            draggingThumb_ = false;
            UpdateScrollbarHover(HitsScrollbar(event.x, event.y));
            return wasDragging;
        }
        case InputEvent::Key: {
            const float step = fontsize::Body * 3.0f;
            const float page = std::max(1.0f, ViewportHeight() * 0.9f);
            switch (event.key) {
                case VK_UP:    SetTargetOffset(targetOffset_ - step, true); return true;
                case VK_DOWN:  SetTargetOffset(targetOffset_ + step, true); return true;
                case VK_PRIOR: SetTargetOffset(targetOffset_ - page, true); return true;
                case VK_NEXT:  SetTargetOffset(targetOffset_ + page, true); return true;
                case VK_HOME:  SetTargetOffset(0.0f, true); return true;
                case VK_END:   ScrollToBottom(); return true;
                default: return false;
            }
        }
        default:
            return false;
    }
}

void LicenseBox::OnFocus(bool focused) { focused_ = focused; }

void LicenseBox::Render(ID2D1DeviceContext* dc, const Theme& theme) {
    if (!dc) return;
    EnsureLayout();
    const D2D1_RECT_F c = ContentRect();
    if (c.right <= c.left || c.bottom <= c.top) return;
    const float offset = ScrollOffset();
    if (auto background = MakeBrush(dc, theme.card)) dc->FillRectangle(bounds_, background.Get());

    // 文本裁剪：滚动的唯一体现是 DrawTextLayout 原点上移 offset。
    dc->PushAxisAlignedClip(c, D2D1_ANTIALIAS_MODE_PER_PRIMITIVE);
    if (layout_) {
        ComPtr<ID2D1SolidColorBrush> textBrush = MakeBrush(dc, theme.textPrimary);
        if (textBrush) {
            dc->DrawTextLayout(D2D1::Point2F(c.left, c.top - offset), layout_, textBrush.Get(),
                               D2D1_DRAW_TEXT_OPTIONS_CLIP);
        }
    }
    dc->PopAxisAlignedClip();

    const float maxScroll = MaxScroll();
    if (maxScroll <= 0.0f) return;

    const float hover = scrollbarAnim_ ? scrollbarAnim_->Value() : (scrollbarHovered_ ? 1.0f : 0.0f);
    const float width = kScrollbarRestWidth + (kScrollbarHotWidth - kScrollbarRestWidth) * hover;
    const float right = bounds_.right - kScrollbarInset;
    const float left = std::max(bounds_.left, right - width);
    if (hover > 0.0f) {
        auto track = MakeBrush(dc, ScaleAlpha(theme.textSecondary, hover * 0.18f));
        if (track) {
            dc->FillRoundedRectangle(D2D1::RoundedRect(
                D2D1::RectF(left, c.top, right, c.bottom), width * 0.5f, width * 0.5f), track.Get());
        }
    }
    const float thumbHeight = ThumbHeight();
    const float thumbY = c.top + (ViewportHeight() - thumbHeight) * offset / maxScroll;
    auto thumb = MakeBrush(dc, ScaleAlpha(theme.textSecondary, 0.7f + 0.3f * hover));
    if (thumb) {
        dc->FillRoundedRectangle(D2D1::RoundedRect(
            D2D1::RectF(left, thumbY, right, thumbY + thumbHeight), width * 0.5f, width * 0.5f), thumb.Get());
    }
}

// =============================== StepItem ==================================

void StepItem::BindAnimator(Animator* animator) {
    animator_ = animator;
    if (!animator_) return;
    const unsigned serial = g_feedbackSerial.fetch_add(1, std::memory_order_relaxed);
    emphName_ = SerialName("step", serial, "emph");
    checkName_ = SerialName("step", serial, "check");
}

void StepItem::StartAnims() {
    const float eTarget = (state_ == Current) ? 1.0f : 0.0f;
    const float cTarget = (state_ == Completed) ? 1.0f : 0.0f;
    if (!animator_) {
        emphFallback_ = eTarget;
        checkFallback_ = cTarget;
        return;
    }
    const float eFrom = emphAnim_ ? emphAnim_->Value() : emphFallback_;
    emphFallback_ = eTarget;
    if (eFrom != eTarget) {
        emphAnim_ = &animator_->Animate(emphName_, eFrom, eTarget, 180.0f, easing::Standard);
    }
    const float cFrom = checkAnim_ ? checkAnim_->Value() : checkFallback_;
    checkFallback_ = cTarget;
    if (cFrom != cTarget) {
        checkAnim_ = &animator_->Animate(checkName_, cFrom, cTarget, 200.0f, easing::Standard);
    }
}

void StepItem::SetState(State state) {
    if (state_ == state) return;
    state_ = state;
    StartAnims();
}

void StepItem::SetStep(int index, int currentStep) {
    index_ = index;
    SetState(index < currentStep ? Completed : (index == currentStep ? Current : Future));
}

float StepItem::Emphasis() const {
    if (emphAnim_) return std::clamp(emphAnim_->Value(), 0.0f, 1.0f);
    return emphFallback_;
}

float StepItem::CheckProgress() const {
    if (checkAnim_) return std::clamp(checkAnim_->Value(), 0.0f, 1.0f);
    return checkFallback_;
}

bool StepItem::HitTest(float /*x*/, float /*y*/) const { return false; }  // 非交互

bool StepItem::OnInput(const InputEvent& /*event*/) { return false; }

void StepItem::Render(ID2D1DeviceContext* dc, const Theme& theme) {
    if (!dc) return;
    const float h = bounds_.bottom - bounds_.top;
    const float w = bounds_.right - bounds_.left;
    if (h <= 0.0f || w <= 0.0f) return;

    const float e = Emphasis();
    const float c = CheckProgress();
    const bool horizontal = (orientation_ == Orientation::Horizontal);

    // 节点中心：竖向 = 左内边距 + 垂直中线；横向 = 水平中心 + 底边上抬 spacing::L。
    const float cx = horizontal ? (bounds_.left + bounds_.right) * 0.5f : bounds_.left + 12.0f;
    const float cy = horizontal ? (bounds_.bottom - spacing::L) : (bounds_.top + bounds_.bottom) * 0.5f;
    const float rBase = 9.0f;
    const float r = rBase + 2.0f * e;  // 当前步略微放大

    if (horizontal) {
        // 横向连接线：自**上一节点圆盘右缘**水平进入本节点左缘；「已完成或当前」时为 accent，
        // 保证蓝色进度线连续进入当前节点。双色规则沿用竖向（此处仅「进入段」）。
        // 注意：本列 bounds_ 是等宽列（左缘 = 列边界，不是上一节点中心），故起点须回退一个
        // 列宽（列宽 == 相邻节点中心间距）到上一节点中心，再加 rBase 退到其圆盘右缘——
        // 若直接自上一节点中心起画，accent 连接线会覆盖上一节点圆盘内的对勾，把它切成断口
        // （见证据 stepper-check-path：断口的真正成因是本连接线覆盖，而非字形光栅化）。
        // 上一节点恒为「已完成」(rBase) 或「当前」(rBase+2)：用 rBase 起画，前者恰好齐平、
        // 后者内缩 2px（同色不可见），两种情况均不会产生可见缝隙。
        if (index_ > 0) {
            const D2D1_COLOR_F lineColor = Mix(theme.divider, theme.accent, std::max(c, e));
            ComPtr<ID2D1SolidColorBrush> lineBrush = MakeBrush(dc, lineColor);
            if (lineBrush) {
                const float colW = bounds_.right - bounds_.left;  // 本列宽 = 相邻节点中心间距
                dc->DrawLine(D2D1::Point2F(cx - colW + rBase, cy), D2D1::Point2F(cx - r, cy),
                             lineBrush.Get(), 2.0f);
            }
        }
    } else {
        // 连接线：上半段（自上一节点进入）在「已完成或当前」时为 accent，保证蓝色进度线连续
        // 到当前节点；下半段（去往下一节点）仅「已完成」时 accent。
        const D2D1_COLOR_F upperColor = Mix(theme.divider, theme.accent, std::max(c, e));
        ComPtr<ID2D1SolidColorBrush> upperBrush = MakeBrush(dc, upperColor);
        if (upperBrush) {
            if (index_ > 0) dc->DrawLine(D2D1::Point2F(cx, bounds_.top), D2D1::Point2F(cx, cy - r),
                                         upperBrush.Get(), 2.0f);
        }
        const D2D1_COLOR_F lowerColor = Mix(theme.divider, theme.accent, c);
        ComPtr<ID2D1SolidColorBrush> lowerBrush = MakeBrush(dc, lowerColor);
        if (lowerBrush) {
            if (!last_) dc->DrawLine(D2D1::Point2F(cx, cy + r), D2D1::Point2F(cx, bounds_.bottom),
                                     lowerBrush.Get(), 2.0f);
        }
    }

    // 已完成：实心 accent 圆。
    if (c > 0.0f) {
        ComPtr<ID2D1SolidColorBrush> fb = MakeBrush(dc, ScaleAlpha(theme.accent, c));
        if (fb) dc->FillEllipse(D2D1::Ellipse(D2D1::Point2F(cx, cy), r, r), fb.Get());
    }
    // 当前：内点（强调）。
    if (e > 0.0f) {
        ComPtr<ID2D1SolidColorBrush> eb = MakeBrush(dc, ScaleAlpha(theme.accent, e));
        if (eb) dc->FillEllipse(D2D1::Ellipse(D2D1::Point2F(cx, cy), r - 4.0f, r - 4.0f), eb.Get());
    }
    // 环：未来=次级灰描边，完成/当前=accent。
    const D2D1_COLOR_F ringColor =
        Mix(ScaleAlpha(theme.textSecondary, 0.55f), theme.accent, std::max(c, e));
    ComPtr<ID2D1SolidColorBrush> ringBrush = MakeBrush(dc, ringColor);
    if (ringBrush) {
        dc->DrawEllipse(D2D1::Ellipse(D2D1::Point2F(cx, cy), r, r), ringBrush.Get(), 2.0f + e);
    }
    // 完成对勾（深色主题 accent 亮 → 用黑勾；浅色主题 → 白勾）。
    // 前端设计师修订：改为 D2D 自绘圆角矢量勾（DrawCheckMark）。glyph::Success(U+E930) 是
    // "圆圈内对勾"字形，叠在实心 accent 圆盘上会形成双圆（✅ 套娃）→ 弃用；glyph::Check
    // (U+E73E) 弃用原因是该字形在本尺寸下笔画偏细（中位宽仅 2px），且步骤点的「断口」
    // 与字形无关（真正成因是下一节点连接线覆盖上一节点圆盘内的对勾，已随连接线起点
    // 回退到上一节点圆盘右缘一并修复，见证据 stepper-check-path）。两常量在 glyphs.h
    // 中保留不动（复选框仍在用）。
    if (c > 0.0f) {
        const D2D1_COLOR_F checkColor = theme.isDark ? D2D1::ColorF(0.0f, 0.0f, 0.0f, c)
                                                     : D2D1::ColorF(1.0f, 1.0f, 1.0f, c);
        DrawCheckMark(dc, cx, cy, r, checkColor);
    }

    // 标签：当前=semiBold + 主文本；完成/未来按进度在次级↔主文本间过渡。
    //  - 竖向：节点右侧，左对齐。
    //  - 横向：节点上方，水平居中。
    const DWRITE_FONT_WEIGHT weight =
        (state_ == Current) ? weight::SemiBold : weight::Regular;
    const D2D1_COLOR_F labelColor = Mix(theme.textSecondary, theme.textPrimary, std::max(c, e));
    if (horizontal) {
        const D2D1_RECT_F labelRect =
            D2D1::RectF(bounds_.left, bounds_.top, bounds_.right, cy - r - spacing::S);
        DrawLine(dc, text_, label_, labelRect, fontsize::Body, weight, DWRITE_TEXT_ALIGNMENT_CENTER,
                 labelColor);
    } else {
        const D2D1_RECT_F labelRect =
            D2D1::RectF(cx + r + spacing::S, bounds_.top, bounds_.right, bounds_.bottom);
        DrawLine(dc, text_, label_, labelRect, fontsize::Body, weight, DWRITE_TEXT_ALIGNMENT_LEADING,
                 labelColor);
    }
}


}  // namespace spk
