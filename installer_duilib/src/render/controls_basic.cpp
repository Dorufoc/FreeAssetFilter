//
// controls_basic.cpp - WinUI3 可复用控件 A：Button / CheckBox / PathField（Todo 7）。
//
// 实现 controls_base.h 的 Widget 接口。坐标/DIP、token、动画均按头文件契约。
// 控件不自持帧时钟：动画值经 BindAnimator 注入的 Animator 推进，宿主负责在输入后
// 请求 tick（RequestAnimTick）。
//
#include "render/controls_basic.h"

#include <d2d1_1helper.h>

#include "render/render_context.h"  // faf::ComPtr（最小 COM RAII 指针）

#include <algorithm>
#include <atomic>
#include <cmath>

namespace faf {

namespace {

// 每实例唯一名（Animator 按名称复用 AnimValue，故控件间必须唯一）。
std::atomic<unsigned> g_controlSerial{0};

std::string SerialName(const char* kind, unsigned serial, const char* prop) {
    return std::string(kind) + std::to_string(serial) + "." + prop;
}

ComPtr<ID2D1SolidColorBrush> MakeBrush(ID2D1DeviceContext* dc, const D2D1_COLOR_F& color) {
    ComPtr<ID2D1SolidColorBrush> brush;
    if (!dc) return brush;
    dc->CreateSolidColorBrush(color, brush.GetAddressOf());
    return brush;
}

// 把颜色按 t (0..1) 缩放其 alpha（用作 hover/pressed 叠加）。
D2D1_COLOR_F ScaleAlpha(const D2D1_COLOR_F& c, float t) {
    D2D1_COLOR_F out = c;
    out.a *= std::clamp(t, 0.0f, 1.0f);
    return out;
}

// 居中/任意对齐绘制一行文字（NoWrap）。text 为空则跳过。
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

// 居中绘制单个 Fluent 字形。
void DrawGlyph(ID2D1DeviceContext* dc, const GlyphFont* glyphs, wchar_t codepoint,
               const D2D1_RECT_F& rect, float size, const D2D1_COLOR_F& color) {
    if (!glyphs || !glyphs->IsReady()) return;
    ComPtr<IDWriteTextFormat> fmt;
    if (FAILED(glyphs->CreateFormat(size, fmt.GetAddressOf()))) return;
    fmt->SetTextAlignment(DWRITE_TEXT_ALIGNMENT_CENTER);
    fmt->SetParagraphAlignment(DWRITE_PARAGRAPH_ALIGNMENT_CENTER);
    ComPtr<ID2D1SolidColorBrush> brush = MakeBrush(dc, color);
    if (!brush) return;
    const wchar_t buf[2] = {codepoint, 0};
    dc->DrawText(buf, 1, fmt.Get(), rect, brush.Get());
}

}  // namespace

// ============================== Button =====================================

void Button::SetEnabled(bool enabled) {
    enabled_ = enabled;
    if (!enabled_) {
        hovered_ = false;
        pressed_ = false;
        hoverFallback_ = 0.0f;
        pressFallback_ = 0.0f;
    }
}

void Button::BindAnimator(Animator* animator) {
    animator_ = animator;
    if (!animator_) return;
    const unsigned serial = g_controlSerial.fetch_add(1, std::memory_order_relaxed);
    hoverName_ = SerialName("button", serial, "hover");
    pressName_ = SerialName("button", serial, "press");
}

void Button::StartHoverAnim(float target) {
    if (!animator_) {
        hoverFallback_ = target;
        return;
    }
    const float from = hoverAnim_ ? hoverAnim_->Value() : hoverFallback_;
    hoverFallback_ = target;
    if (from == target) return;
    hoverAnim_ = &animator_->Animate(hoverName_, from, target, 120.0f, easing::Standard);
}

void Button::StartPressAnim(float target) {
    if (!animator_) {
        pressFallback_ = target;
        return;
    }
    const float from = pressAnim_ ? pressAnim_->Value() : pressFallback_;
    pressFallback_ = target;
    if (from == target) return;
    pressAnim_ = &animator_->Animate(pressName_, from, target, 90.0f, easing::Standard);
}

float Button::HoverT() const { return hoverAnim_ ? hoverAnim_->Value() : hoverFallback_; }
float Button::PressT() const { return pressAnim_ ? pressAnim_->Value() : pressFallback_; }

D2D1_RECT_F Button::VisualRect() const {
    const float t = enabled_ ? PressT() : 0.0f;
    const float s = 1.0f - 0.02f * t;  // 按下轻微缩放
    const float cx = (bounds_.left + bounds_.right) * 0.5f;
    const float cy = (bounds_.top + bounds_.bottom) * 0.5f;
    const float hw = (bounds_.right - bounds_.left) * 0.5f * s;
    const float hh = (bounds_.bottom - bounds_.top) * 0.5f * s;
    return D2D1::RectF(cx - hw, cy - hh, cx + hw, cy + hh);
}

bool Button::HitTest(float x, float y) const {
    return x >= bounds_.left && x <= bounds_.right && y >= bounds_.top && y <= bounds_.bottom;
}

bool Button::OnInput(const InputEvent& event) {
    if (!enabled_) return false;
    switch (event.kind) {
        case InputEvent::Move: {
            const bool inside = HitTest(event.x, event.y);
            if (inside != hovered_) {
                hovered_ = inside;
                StartHoverAnim(inside ? 1.0f : 0.0f);
            }
            if (!inside && pressed_) {  // 拖出取消按压视觉
                pressed_ = false;
                StartPressAnim(0.0f);
            }
            return inside;
        }
        case InputEvent::Down:
            if (HitTest(event.x, event.y)) {
                pressed_ = true;
                StartPressAnim(1.0f);
                return true;
            }
            return false;
        case InputEvent::Up:
            if (pressed_) {
                pressed_ = false;
                StartPressAnim(0.0f);
                const bool inside = HitTest(event.x, event.y);
                if (inside) {
                    ++clicks_;
                    if (onClick_) onClick_();
                }
                return inside;
            }
            return false;
        case InputEvent::Key:
            if (event.key == VK_SPACE || event.key == VK_RETURN) {
                ++clicks_;
                if (onClick_) onClick_();
                return true;
            }
            return false;
        default:
            return false;
    }
}

void Button::OnFocus(bool focused) { focused_ = focused; }

void Button::Render(ID2D1DeviceContext* dc, const Theme& theme) {
    if (!dc) return;
    const D2D1_RECT_F r = VisualRect();
    const D2D1_ROUNDED_RECT rr = D2D1::RoundedRect(r, radius::Small, radius::Small);

    const float mul = enabled_ ? 1.0f : 0.4f;
    const float hoverT = enabled_ ? HoverT() : 0.0f;
    const float pressT = enabled_ ? PressT() : 0.0f;

    // focus 外描边（accent，绘制在按钮外 2 DIP）。
    if (focused_ && enabled_) {
        ComPtr<ID2D1SolidColorBrush> fb = MakeBrush(dc, theme.accent);
        if (fb) {
            const float o = 2.0f;
            const D2D1_ROUNDED_RECT rrO =
                D2D1::RoundedRect(D2D1::RectF(r.left - o, r.top - o, r.right + o, r.bottom + o),
                                  radius::Small + o, radius::Small + o);
            dc->DrawRoundedRectangle(rrO, fb.Get(), 2.0f);
        }
    }

    // 底色：强调 = accent 填充，次要 = card 填充 + cardStroke 描边。
    D2D1_COLOR_F base = (style_ == Accent) ? theme.accent : theme.card;
    base.a *= mul;
    ComPtr<ID2D1SolidColorBrush> baseBrush = MakeBrush(dc, base);
    if (baseBrush) dc->FillRoundedRectangle(rr, baseBrush.Get());

    if (style_ == Secondary) {
        ComPtr<ID2D1SolidColorBrush> sb = MakeBrush(dc, ScaleAlpha(theme.cardStroke, mul));
        if (sb) dc->DrawRoundedRectangle(rr, sb.Get(), 1.0f);
    }

    if (hoverT > 0.0f) {
        ComPtr<ID2D1SolidColorBrush> hb = MakeBrush(dc, ScaleAlpha(theme.hover, hoverT * mul));
        if (hb) dc->FillRoundedRectangle(rr, hb.Get());
    }
    if (pressT > 0.0f) {
        ComPtr<ID2D1SolidColorBrush> pb = MakeBrush(dc, ScaleAlpha(theme.pressed, pressT * mul));
        if (pb) dc->FillRoundedRectangle(rr, pb.Get());
    }

    // 前景：强调按钮用白字，次要按钮用 textPrimary。
    D2D1_COLOR_F fg = (style_ == Accent) ? D2D1::ColorF(1.0f, 1.0f, 1.0f, 1.0f) : theme.textPrimary;
    fg.a *= mul;

    const float cy = (r.top + r.bottom) * 0.5f;
    const float pad = spacing::M;
    D2D1_RECT_F textRect = r;
    if (hasGlyph_) {
        const float gsize = 16.0f;
        D2D1_RECT_F gRect = D2D1::RectF(r.left + pad, cy - gsize, r.left + pad + gsize, cy + gsize);
        DrawGlyph(dc, glyphs_, glyph_, gRect, gsize, fg);
        textRect.left += pad + gsize + spacing::S;
    }
    textRect.right -= pad;
    DrawLine(dc, text_, label_, textRect, fontsize::Body, weight::SemiBold,
             DWRITE_TEXT_ALIGNMENT_CENTER, fg);
}

// ============================= CheckBox ===================================

void CheckBox::SetChecked(bool checked) {
    if (checked_ == checked) return;
    checked_ = checked;
    StartCheckAnim(checked ? 1.0f : 0.0f);
    if (onToggle_) onToggle_(checked_);
}

void CheckBox::SetEnabled(bool enabled) {
    enabled_ = enabled;
    if (!enabled_) {
        hovered_ = false;
        pressed_ = false;
    }
}

void CheckBox::BindAnimator(Animator* animator) {
    animator_ = animator;
    if (animator_) checkName_ = SerialName("checkbox", g_controlSerial.fetch_add(1), "check");
}

float CheckBox::CheckProgress() const {
    if (checkAnim_) return std::clamp(checkAnim_->Value(), 0.0f, 1.0f);
    return checked_ ? 1.0f : 0.0f;
}

void CheckBox::StartCheckAnim(float target) {
    if (!animator_) return;  // 无动画器：CheckProgress 按 checked_ 立即取值
    const float from = checkAnim_ ? checkAnim_->Value() : (1.0f - target);
    if (from == target) return;
    checkAnim_ = &animator_->Animate(checkName_, from, target, 150.0f, easing::Standard);
}

void CheckBox::Toggle() {
    ++toggles_;
    SetChecked(!checked_);
}

bool CheckBox::HitTest(float x, float y) const {
    return x >= bounds_.left && x <= bounds_.right && y >= bounds_.top && y <= bounds_.bottom;
}

bool CheckBox::OnInput(const InputEvent& event) {
    if (!enabled_) return false;
    switch (event.kind) {
        case InputEvent::Move: {
            const bool inside = HitTest(event.x, event.y);
            hovered_ = inside;
            if (!inside) pressed_ = false;
            return inside;
        }
        case InputEvent::Down:
            if (HitTest(event.x, event.y)) {
                pressed_ = true;
                return true;
            }
            return false;
        case InputEvent::Up:
            if (pressed_) {
                pressed_ = false;
                const bool inside = HitTest(event.x, event.y);
                if (inside) Toggle();
                return inside;
            }
            return false;
        case InputEvent::Key:
            if (event.key == VK_SPACE || event.key == VK_RETURN) {
                Toggle();
                return true;
            }
            return false;
        default:
            return false;
    }
}

void CheckBox::OnFocus(bool focused) { focused_ = focused; }

void CheckBox::Render(ID2D1DeviceContext* dc, const Theme& theme) {
    if (!dc) return;
    const float mul = enabled_ ? 1.0f : 0.4f;
    const float p = CheckProgress();  // 0..1 切换进度
    const float boxSize = 20.0f;
    const float cy = (bounds_.top + bounds_.bottom) * 0.5f;
    const D2D1_RECT_F box =
        D2D1::RectF(bounds_.left, cy - boxSize * 0.5f, bounds_.left + boxSize, cy + boxSize * 0.5f);
    const D2D1_ROUNDED_RECT rrBox = D2D1::RoundedRect(box, radius::Small, radius::Small);

    // focus 外描边。
    if (focused_ && enabled_) {
        ComPtr<ID2D1SolidColorBrush> fb = MakeBrush(dc, theme.accent);
        if (fb) {
            const float o = 2.0f;
            const D2D1_ROUNDED_RECT rrO =
                D2D1::RoundedRect(D2D1::RectF(box.left - o, box.top - o, box.right + o, box.bottom + o),
                                  radius::Small + o, radius::Small + o);
            dc->DrawRoundedRectangle(rrO, fb.Get(), 2.0f);
        }
    }

    // 底色：未勾 = card 填充 + cardStroke 描边；已勾 = accent（按 p 交叉淡化）。
    D2D1_COLOR_F fill = theme.card;
    fill.a *= mul;
    if (p > 0.0f) {
        const D2D1_COLOR_F accent = ScaleAlpha(theme.accent, p * mul);
        ComPtr<ID2D1SolidColorBrush> ab = MakeBrush(dc, accent);
        if (ab) dc->FillRoundedRectangle(rrBox, ab.Get());
    }
    ComPtr<ID2D1SolidColorBrush> baseBrush = MakeBrush(dc, fill);
    if (baseBrush) dc->FillRoundedRectangle(rrBox, baseBrush.Get());

    // 描边：未勾时 cardStroke；勾选过程中逐渐被 accent 填充覆盖。
    if (p < 1.0f) {
        ComPtr<ID2D1SolidColorBrush> sb = MakeBrush(dc, ScaleAlpha(theme.cardStroke, (1.0f - p) * mul));
        if (sb) dc->DrawRoundedRectangle(rrBox, sb.Get(), 1.0f);
    }

    // 勾选字形：随进度淡入。
    if (p > 0.0f) {
        D2D1_COLOR_F checkColor = D2D1::ColorF(1.0f, 1.0f, 1.0f, p * mul);
        // 深色主题下单选框底也是深色的 accent 亮色，勾仍用近黑以保证对比（WinUI3 暗色 accent 为亮青）。
        if (theme.isDark) checkColor = D2D1::ColorF(0.0f, 0.0f, 0.0f, p * mul);
        DrawGlyph(dc, glyphs_, glyph::Check, box, boxSize - 4.0f, checkColor);
    }

    // hover / pressed 叠加（作用于盒子）。
    if (enabled_ && hovered_) {
        ComPtr<ID2D1SolidColorBrush> hb = MakeBrush(dc, ScaleAlpha(theme.hover, mul));
        if (hb) dc->FillRoundedRectangle(rrBox, hb.Get());
    }
    if (enabled_ && pressed_) {
        ComPtr<ID2D1SolidColorBrush> pb = MakeBrush(dc, ScaleAlpha(theme.pressed, mul));
        if (pb) dc->FillRoundedRectangle(rrBox, pb.Get());
    }

    // 标签文字（盒子右侧）。
    D2D1_COLOR_F fg = theme.textPrimary;
    fg.a *= mul;
    D2D1_RECT_F textRect = bounds_;
    textRect.left = box.right + spacing::S;
    DrawLine(dc, text_, label_, textRect, fontsize::Body, weight::Regular,
             DWRITE_TEXT_ALIGNMENT_LEADING, fg);
}

// ============================= PathField ==================================

void PathField::OnFocus(bool focused) {
    focused_ = focused;
    if (focused) hovered_ = false;
}

bool PathField::HitTest(float x, float y) const {
    return x >= bounds_.left && x <= bounds_.right && y >= bounds_.top && y <= bounds_.bottom;
}

bool PathField::OnInput(const InputEvent& event) {
    if (!enabled_) return false;
    switch (event.kind) {
        case InputEvent::Move:
            hovered_ = HitTest(event.x, event.y);
            return hovered_;
        case InputEvent::Down:
        case InputEvent::Up:
            if (HitTest(event.x, event.y)) {
                if (event.kind == InputEvent::Up) activated_ = true;
                return true;
            }
            return false;
        default:
            return false;
    }
}

std::wstring PathField::MiddleEllipsize(const std::wstring& path, std::size_t head,
                                        std::size_t tail) {
    if (path.size() <= head + tail + 1) return path;
    return path.substr(0, head) + L"\u2026" + path.substr(path.size() - tail);
}

void PathField::Render(ID2D1DeviceContext* dc, const Theme& theme) {
    if (!dc) return;
    const float mul = enabled_ ? 1.0f : 0.4f;
    const D2D1_ROUNDED_RECT rr =
        D2D1::RoundedRect(bounds_, radius::Small, radius::Small);

    // 底色（card）+ 描边（focus = accent，hover = 加亮 cardStroke，否则 cardStroke）。
    ComPtr<ID2D1SolidColorBrush> base = MakeBrush(dc, ScaleAlpha(theme.card, mul));
    if (base) dc->FillRoundedRectangle(rr, base.Get());

    D2D1_COLOR_F stroke = focused_ ? theme.accent : theme.cardStroke;
    if (enabled_ && hovered_ && !focused_) stroke.a = std::min(1.0f, stroke.a + 0.06f);
    ComPtr<ID2D1SolidColorBrush> sb = MakeBrush(dc, ScaleAlpha(stroke, mul));
    if (sb) dc->DrawRoundedRectangle(rr, sb.Get(), focused_ ? 1.6f : 1.0f);

    // 中间省略（按可用宽度估算字符预算）。
    const float pad = spacing::S + spacing::XS;
    const float avail = (bounds_.right - bounds_.left) - 2.0f * pad;
    int maxChars = static_cast<int>(avail / (fontsize::Body * 0.58f));
    if (maxChars < 4) maxChars = 4;
    std::wstring display = path_;
    if (static_cast<int>(path_.size()) > maxChars) {
        const std::size_t head = static_cast<std::size_t>(maxChars) * 3 / 5;
        const std::size_t tail = static_cast<std::size_t>(maxChars) - head - 1;
        display = MiddleEllipsize(path_, head, tail);
    }

    D2D1_COLOR_F fg = theme.textPrimary;
    fg.a *= mul;
    const D2D1_RECT_F textRect = D2D1::RectF(bounds_.left + pad, bounds_.top, bounds_.right - pad,
                                             bounds_.bottom);
    DrawLine(dc, text_, display, textRect, fontsize::Body, weight::Regular,
             DWRITE_TEXT_ALIGNMENT_LEADING, fg);
}

}  // namespace faf
