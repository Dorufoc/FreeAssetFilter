//
// controls_basic.cpp - 可复用控件 A：Button / CheckBox / PathField。
//
// 视觉全部按 `src/sopeek/resources/icons/install_design/` 的四张设计稿重做
// （2026-11 改版）：黑色胶囊主按钮 / 纯文字次要按钮 / 29px 复选框 / 浅灰路径框。
// 输入与焦点逻辑保持原样（Tab 顺序、空格回车激活、按下移出取消）。
//
// 控件不自持帧时钟：动画值经 BindAnimator 注入的 Animator 推进，宿主负责在输入后
// 请求 tick（RequestAnimTick）。
//
#include "render/controls_basic.h"

#include <d2d1_1helper.h>

#include "render/render_context.h"  // spk::ComPtr（最小 COM RAII 指针）

#include <algorithm>
#include <atomic>
#include <cmath>

namespace spk {

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

D2D1_RECT_F Rect(float l, float t, float r, float b) { return D2D1_RECT_F{l, t, r, b}; }

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

// 单行文字的实际排版宽度（DIP）。用于把「文字 + 尾部箭头」整体居中。
float TextWidth(const TextFactory* text, const std::wstring& s, float size,
                DWRITE_FONT_WEIGHT weight) {
    if (!text || !text->IsReady() || s.empty()) return 0.0f;
    IDWriteFactory* factory = text->Factory();
    if (!factory) return 0.0f;
    ComPtr<IDWriteTextFormat> fmt;
    if (FAILED(text->CreateFormat(size, weight, DWRITE_TEXT_ALIGNMENT_LEADING,
                                  DWRITE_PARAGRAPH_ALIGNMENT_CENTER, fmt.GetAddressOf()))) {
        return 0.0f;
    }
    fmt->SetWordWrapping(DWRITE_WORD_WRAPPING_NO_WRAP);
    ComPtr<IDWriteTextLayout> layout;
    if (FAILED(factory->CreateTextLayout(s.c_str(), static_cast<UINT32>(s.size()), fmt.Get(),
                                        4096.0f, size * 2.0f, layout.GetAddressOf()))) {
        return 0.0f;
    }
    DWRITE_TEXT_METRICS metrics{};
    if (FAILED(layout->GetMetrics(&metrics))) return 0.0f;
    return metrics.widthIncludingTrailingWhitespace;
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

// 主按钮尾部「>」箭头（设计稿：宽 7、高 12、线宽 1.5）。位置固定：按钮中心 +56.32 DIP
//（design translate(1016.32 718) 相对按钮中心 960 → 56.32）。
constexpr float kChevronWidth = 7.0f;
constexpr float kChevronHalfHeight = 6.0f;
constexpr float kChevronStroke = 1.5f;
constexpr float kChevronOffsetFromCenter = 56.32f;

void DrawTrailingChevron(ID2D1DeviceContext* dc, float x, float cy, const D2D1_COLOR_F& color) {
    ComPtr<ID2D1SolidColorBrush> brush = MakeBrush(dc, color);
    if (!brush) return;
    const D2D1_POINT_2F top = D2D1::Point2F(x, cy - kChevronHalfHeight);
    const D2D1_POINT_2F tip = D2D1::Point2F(x + kChevronWidth, cy);
    const D2D1_POINT_2F bottom = D2D1::Point2F(x, cy + kChevronHalfHeight);
    dc->DrawLine(top, tip, brush.Get(), kChevronStroke);
    dc->DrawLine(tip, bottom, brush.Get(), kChevronStroke);
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
    if (hoverAnim_ && hoverAnim_->Target() == target) return;
    hoverAnim_ = &animator_->Animate(hoverName_, from, target, 120.0f, easing::Standard);
}

void Button::StartPressAnim(float target) {
    if (!animator_) {
        pressFallback_ = target;
        return;
    }
    const float from = pressAnim_ ? pressAnim_->Value() : pressFallback_;
    pressFallback_ = target;
    if (pressAnim_ && pressAnim_->Target() == target) return;
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
    const float mul = enabled_ ? 1.0f : 0.4f;
    const float hoverT = enabled_ ? HoverT() : 0.0f;
    const float pressT = enabled_ ? PressT() : 0.0f;
    const float cx = (r.left + r.right) * 0.5f;
    const float cy = (r.top + r.bottom) * 0.5f;

    if (style_ == Accent) {
        // ---- 主按钮：黑色胶囊（152x36 / r8 / 白字 18px）----
        const D2D1_ROUNDED_RECT rr = D2D1::RoundedRect(r, radius::Field, radius::Field);

        // 焦点环（键盘 Tab）：按钮外 2 DIP 的浅色描边。
        if (focused_ && enabled_) {
            ComPtr<ID2D1SolidColorBrush> fb = MakeBrush(dc, ScaleAlpha(theme.solidFill, 0.35f));
            if (fb) {
                const float o = 2.0f;
                const D2D1_ROUNDED_RECT rrO =
                    D2D1::RoundedRect(Rect(r.left - o, r.top - o, r.right + o, r.bottom + o),
                                      radius::Field + o, radius::Field + o);
                dc->DrawRoundedRectangle(rrO, fb.Get(), 2.0f);
            }
        }

        ComPtr<ID2D1SolidColorBrush> base = MakeBrush(dc, ScaleAlpha(theme.solidFill, mul));
        if (base) dc->FillRoundedRectangle(rr, base.Get());

        // hover / pressed：在胶囊上叠加一层（浅色主题叠白提亮，深色主题叠黑压暗）。
        const float overlayA = (0.10f * hoverT + 0.08f * pressT) * mul;
        if (overlayA > 0.001f) {
            D2D1_COLOR_F oc = theme.isDark ? D2D1::ColorF(0, 0, 0, 1) : D2D1::ColorF(1, 1, 1, 1);
            oc.a = overlayA;
            ComPtr<ID2D1SolidColorBrush> ob = MakeBrush(dc, oc);
            if (ob) dc->FillRoundedRectangle(rr, ob.Get());
        }

        const float size = labelSize_ > 0.0f ? labelSize_ : fontsize::ButtonText;
        D2D1_COLOR_F fg = theme.onSolid;
        fg.a *= mul;

        // 设计稿：标签在按钮内**水平居中**（tspan x=-27 = 半字宽）；尾部「>」是独立对象，
        // 固定落在按钮中心右侧 56.32 DIP 处（design 1016.32-640-320），不是紧跟标签。
        DrawLine(dc, text_, label_, r, size, weight::Regular, DWRITE_TEXT_ALIGNMENT_CENTER, fg);
        if (trailingChevron_) DrawTrailingChevron(dc, cx + kChevronOffsetFromCenter, cy, fg);
        return;
    }

    // ---- 次要按钮：纯文字链接（16px，无底无框；hover 下划线）----
    const float size = labelSize_ > 0.0f ? labelSize_ : fontsize::Body16;
    D2D1_COLOR_F fg = theme.textPrimary;
    fg.a *= mul;
    const float textW = TextWidth(text_, label_, size, weight::Regular);
    const float x0 = cx - textW * 0.5f;
    DrawLine(dc, text_, label_, Rect(x0, r.top, x0 + textW + 2.0f, r.bottom), size, weight::Regular,
             DWRITE_TEXT_ALIGNMENT_LEADING, fg);
    if (enabled_ && (focused_ || hoverT > 0.01f)) {
        ComPtr<ID2D1SolidColorBrush> ub =
            MakeBrush(dc, ScaleAlpha(theme.textPrimary, focused_ ? 1.0f : hoverT * 0.55f));
        if (ub) {
            const float y = cy + size * 0.52f;
            dc->DrawLine(D2D1::Point2F(x0, y), D2D1::Point2F(x0 + textW, y), ub.Get(), 1.0f);
        }
    }
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
    if (checkAnim_ && checkAnim_->Target() == target) return;
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
    const float size = boxSize_ > 0.0f ? boxSize_ : 29.0f;
    const float cy = (bounds_.top + bounds_.bottom) * 0.5f;
    const D2D1_RECT_F box =
        Rect(bounds_.left, cy - size * 0.5f, bounds_.left + size, cy + size * 0.5f);
    const float boxRadius = size * (radius::Field / 29.0f);

    // 焦点环（键盘 Tab）。
    if (focused_ && enabled_) {
        ComPtr<ID2D1SolidColorBrush> fb = MakeBrush(dc, ScaleAlpha(theme.solidFill, 0.30f));
        if (fb) {
            const float o = 2.0f;
            const D2D1_ROUNDED_RECT rrO = D2D1::RoundedRect(
                Rect(box.left - o, box.top - o, box.right + o, box.bottom + o), boxRadius + o,
                boxRadius + o);
            dc->DrawRoundedRectangle(rrO, fb.Get(), 2.0f);
        }
    }

    // 未勾选：1px #8F8F8F 描边、无填充（勾选过程中淡出）。
    if (p < 1.0f) {
        ComPtr<ID2D1SolidColorBrush> sb =
            MakeBrush(dc, ScaleAlpha(theme.controlStroke, (1.0f - p) * mul));
        if (sb) {
            dc->DrawRoundedRectangle(D2D1::RoundedRect(box, boxRadius, boxRadius), sb.Get(), 1.0f);
        }
    }

    if (p > 0.0f) {
        // 勾选态（设计稿叠层）：3px 黑环 → 2px 白缝 → 19x19 黑块（r3）→ 白色对勾。
        const D2D1_COLOR_F ink = ScaleAlpha(theme.solidFill, p * mul);
        ComPtr<ID2D1SolidColorBrush> ib = MakeBrush(dc, ink);
        if (ib) {
            const float ring = 3.0f;
            const D2D1_RECT_F ringRect =
                Rect(box.left + ring * 0.5f, box.top + ring * 0.5f, box.right - ring * 0.5f,
                     box.bottom - ring * 0.5f);
            dc->DrawRoundedRectangle(
                D2D1::RoundedRect(ringRect, boxRadius - ring * 0.5f, boxRadius - ring * 0.5f),
                ib.Get(), ring);

            // 内块：设计稿 19x19（盒子 29）居中，圆角 3。
            const float inner = size * (19.0f / 29.0f);
            const float icx = (box.left + box.right) * 0.5f;
            const float ictr = (box.top + box.bottom) * 0.5f;
            const D2D1_RECT_F innerRect =
                Rect(icx - inner * 0.5f, ictr - inner * 0.5f, icx + inner * 0.5f,
                     ictr + inner * 0.5f);
            const float innerRadius = radius::CheckInner * (size / 29.0f);
            dc->FillRoundedRectangle(
                D2D1::RoundedRect(innerRect, innerRadius, innerRadius), ib.Get());
        }

        // 对勾：设计稿两条 3px 圆头线段（盒子内相对坐标 8.8,15.4 → 13.4,20.0 → 19.1,10.6）。
        D2D1_COLOR_F markColor = theme.onSolid;
        markColor.a *= p * mul;
        ComPtr<ID2D1SolidColorBrush> mb = MakeBrush(dc, markColor);
        if (mb) {
            const float k = size / 29.0f;
            const D2D1_POINT_2F a = D2D1::Point2F(box.left + 8.8f * k, box.top + 15.4f * k);
            const D2D1_POINT_2F b = D2D1::Point2F(box.left + 13.4f * k, box.top + 20.0f * k);
            const D2D1_POINT_2F c = D2D1::Point2F(box.left + 19.1f * k, box.top + 10.6f * k);
            dc->DrawLine(a, b, mb.Get(), 3.0f * k);
            dc->DrawLine(b, c, mb.Get(), 3.0f * k);
        }
    }

    // hover / pressed：盒子描边加亮（不改变勾选观感）。
    if (enabled_ && (hovered_ || pressed_)) {
        ComPtr<ID2D1SolidColorBrush> hb = MakeBrush(
            dc, ScaleAlpha(theme.controlStroke, pressed_ ? 0.55f : 0.32f));
        if (hb) {
            dc->DrawRoundedRectangle(D2D1::RoundedRect(box, boxRadius, boxRadius), hb.Get(),
                                     pressed_ ? 2.0f : 1.5f);
        }
    }

    // 标签文字（盒子右侧 8 DIP，16px）。
    D2D1_COLOR_F fg = theme.textPrimary;
    fg.a *= mul;
    D2D1_RECT_F textRect = bounds_;
    textRect.left = box.right + 8.0f;
    DrawLine(dc, text_, label_, textRect, fontsize::Body16, weight::Regular,
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
            return HitTest(event.x, event.y);
        case InputEvent::Up:
            activated_ = HitTest(event.x, event.y);
            return activated_;
        case InputEvent::Key:
            if (event.key != VK_SPACE && event.key != VK_RETURN) return false;
            activated_ = true;
            return true;
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

    // 底色 #EEEEEE + 1px #E9E9E9 描边、圆角 8（设计稿「矩形_146」）。
    ComPtr<ID2D1SolidColorBrush> base = MakeBrush(dc, ScaleAlpha(theme.fieldFill, mul));
    if (base) {
        dc->FillRoundedRectangle(D2D1::RoundedRect(bounds_, radius::Field, radius::Field),
                                 base.Get());
    }
    D2D1_COLOR_F stroke = (focused_ || hovered_) ? theme.controlStroke : theme.fieldStroke;
    ComPtr<ID2D1SolidColorBrush> sb = MakeBrush(dc, ScaleAlpha(stroke, mul));
    if (sb) {
        dc->DrawRoundedRectangle(D2D1::RoundedRect(bounds_, radius::Field, radius::Field), sb.Get(),
                                 1.0f);
    }

    // 右侧内嵌动作（「浏览」）。
    const float padX = 13.0f;
    float actionW = 0.0f;
    if (!actionLabel_.empty()) {
        actionW = TextWidth(text_, actionLabel_, fontsize::Body16, weight::Regular);
        D2D1_COLOR_F actionColor = theme.textPrimary;
        actionColor.a *= mul * ((hovered_ || focused_) ? 1.0f : 0.72f);
        const float ax = bounds_.right - padX - actionW;
        DrawLine(dc, text_, actionLabel_, Rect(ax, bounds_.top, ax + actionW + 2.0f, bounds_.bottom),
                 fontsize::Body16, weight::Regular, DWRITE_TEXT_ALIGNMENT_LEADING, actionColor);
        actionW += 12.0f;  // 与路径文字的气泡间距
    }

    // 中间省略（按可用宽度估算字符预算；18px 中文/ASCII 混排取 0.62 em 近似）。
    const float avail = (bounds_.right - bounds_.left) - 2.0f * padX - actionW;
    int maxChars = static_cast<int>(avail / (fontsize::ButtonText * 0.62f));
    if (maxChars < 4) maxChars = 4;
    std::wstring display = path_;
    if (static_cast<int>(path_.size()) > maxChars) {
        const std::size_t head = static_cast<std::size_t>(maxChars) * 3 / 5;
        const std::size_t tail = static_cast<std::size_t>(maxChars) - head - 1;
        display = MiddleEllipsize(path_, head, tail);
    }

    D2D1_COLOR_F fg = theme.fieldText;
    fg.a *= mul;
    const D2D1_RECT_F textRect =
        Rect(bounds_.left + padX, bounds_.top, bounds_.right - padX - actionW, bounds_.bottom);
    DrawLine(dc, text_, display, textRect, fontsize::ButtonText, weight::Regular,
             DWRITE_TEXT_ALIGNMENT_LEADING, fg);
}

}  // namespace spk
