#pragma once
//
// controls_basic.h - WinUI3 可复用控件 A：Button / CheckBox / PathField（Todo 7）。
//
// 实现 controls_base.h 的 Widget 接口（Frozen contracts §13，本文件不另建共享
// controls.h/.cpp）。所有坐标与绘制均为 DIP（§6 全程 DIP，绝不乘 DPI）。视觉消费
// theme.h 的 token；过渡消费 animation.h 的 AnimValue——AnimValue 由宿主经
// BindAnimator 注入（控件不自持帧时钟，避免与 installer_window 的 tick 双重推进）。
//
// 键盘可达性：三者均实现 IsFocusable()/OnInput()，空格或回车激活（Button/CheckBox），
// Tab 顺序由 controls_base.h 的 WidgetHost 管理（接线归 Todo 12）。
//
#include <windows.h>

#include <d2d1_1.h>
#include <dwrite.h>

#include <functional>
#include <string>

#include "render/animation.h"
#include "render/controls_base.h"
#include "render/glyphs.h"
#include "render/text.h"
#include "render/theme.h"

namespace faf {

// 强调/次要按钮。圆角 4；hover = hover token 叠加，pressed = pressed token 叠加 +
// 轻微缩放（按下时缩到 0.98 并整体微移），focus = accent 外描边；支持纯文字或
// 「字形 + 文字」。禁用态不响应输入、不参与 Tab、降低整体不透明度。
class Button : public Widget {
public:
    enum Style { Accent, Secondary };

    void SetBounds(const D2D1_RECT_F& rect) { bounds_ = rect; }
    const D2D1_RECT_F& Bounds() const noexcept { return bounds_; }

    void SetLabel(std::wstring label) { label_ = std::move(label); }
    void SetGlyph(wchar_t codepoint) {
        glyph_ = codepoint;
        hasGlyph_ = true;
    }
    void SetStyle(Style style) { style_ = style; }
    void SetEnabled(bool enabled);
    void SetOnClick(std::function<void()> cb) { onClick_ = std::move(cb); }

    // 依赖注入（宿主构造后绑定；均可为空——为空时退化为无动画 / 无文字）。
    void BindAnimator(Animator* animator);
    void BindText(const TextFactory* text) { text_ = text; }
    void BindGlyphs(const GlyphFont* glyphs) { glyphs_ = glyphs; }

    void Render(ID2D1DeviceContext* dc, const Theme& theme) override;
    bool HitTest(float x, float y) const override;
    bool OnInput(const InputEvent& event) override;
    bool IsFocusable() const override { return enabled_; }
    void OnFocus(bool focused) override;

    // 可观测状态（供 harness / 验收断言）。
    bool Enabled() const noexcept { return enabled_; }
    bool Hovered() const noexcept { return hovered_; }
    bool Pressed() const noexcept { return pressed_; }
    bool Focused() const noexcept { return focused_; }
    int ClickCount() const noexcept { return clicks_; }

    // 供 harness 在无输入事件时直接设定视觉态（不影响交互逻辑）。
    void SetHoveredForTest(bool hovered) { hovered_ = hovered; StartHoverAnim(hovered ? 1.0f : 0.0f); }
    void SetPressedForTest(bool pressed) { pressed_ = pressed; StartPressAnim(pressed ? 1.0f : 0.0f); }

private:
    void StartHoverAnim(float target);
    void StartPressAnim(float target);
    float HoverT() const;
    float PressT() const;
    D2D1_RECT_F VisualRect() const;  // 施加按下缩放后的绘制矩形

    D2D1_RECT_F bounds_{};
    std::wstring label_;
    wchar_t glyph_ = 0;
    bool hasGlyph_ = false;
    Style style_ = Secondary;
    bool enabled_ = true;
    bool hovered_ = false;
    bool pressed_ = false;
    bool focused_ = false;
    int clicks_ = 0;
    std::function<void()> onClick_;

    Animator* animator_ = nullptr;
    AnimValue* hoverAnim_ = nullptr;
    AnimValue* pressAnim_ = nullptr;
    float hoverFallback_ = 0.0f;
    float pressFallback_ = 0.0f;
    std::string hoverName_;
    std::string pressName_;

    const TextFactory* text_ = nullptr;
    const GlyphFont* glyphs_ = nullptr;
};

// WinUI3 方形复选框。盒子 20x20 DIP、圆角 4；勾选为 Fluent Check 字形；切换约
// 150ms 动画（checkAnim）。未勾/已勾/悬停/按压四态。文字标签在盒右侧。
class CheckBox : public Widget {
public:
    void SetBounds(const D2D1_RECT_F& rect) { bounds_ = rect; }
    const D2D1_RECT_F& Bounds() const noexcept { return bounds_; }

    void SetLabel(std::wstring label) { label_ = std::move(label); }
    void SetChecked(bool checked);
    bool Checked() const noexcept { return checked_; }
    void SetEnabled(bool enabled);
    bool Enabled() const noexcept { return enabled_; }
    void SetOnToggle(std::function<void(bool)> cb) { onToggle_ = std::move(cb); }

    void BindAnimator(Animator* animator);
    void BindText(const TextFactory* text) { text_ = text; }
    void BindGlyphs(const GlyphFont* glyphs) { glyphs_ = glyphs; }

    void Render(ID2D1DeviceContext* dc, const Theme& theme) override;
    bool HitTest(float x, float y) const override;
    bool OnInput(const InputEvent& event) override;
    bool IsFocusable() const override { return enabled_; }
    void OnFocus(bool focused) override;

    bool Hovered() const noexcept { return hovered_; }
    bool Pressed() const noexcept { return pressed_; }
    bool Focused() const noexcept { return focused_; }
    int ToggleCount() const noexcept { return toggles_; }
    // 当前切换进度 0..1（无动画器时按 checked 立即取值）。供 harness 断言动画完整。
    float CheckProgress() const;

private:
    void Toggle();
    void StartCheckAnim(float target);

    D2D1_RECT_F bounds_{};
    std::wstring label_;
    bool checked_ = false;
    bool enabled_ = true;
    bool hovered_ = false;
    bool pressed_ = false;
    bool focused_ = false;
    int toggles_ = 0;
    std::function<void(bool)> onToggle_;

    Animator* animator_ = nullptr;
    AnimValue* checkAnim_ = nullptr;
    std::string checkName_;

    const TextFactory* text_ = nullptr;
    const GlyphFont* glyphs_ = nullptr;
};

// 只读路径输入框。圆角 4；cardStroke 描边，hover 加亮，focus = accent 描边。
// 文本中间省略（保留盘符/根与末段）。
class PathField : public Widget {
public:
    void SetBounds(const D2D1_RECT_F& rect) { bounds_ = rect; }
    const D2D1_RECT_F& Bounds() const noexcept { return bounds_; }

    void SetPath(std::wstring path) { path_ = std::move(path); }
    const std::wstring& Path() const noexcept { return path_; }
    void SetEnabled(bool enabled) {
        enabled_ = enabled;
        if (!enabled_) {
            hovered_ = false;
            focused_ = false;
        }
    }
    bool Enabled() const noexcept { return enabled_; }

    void BindText(const TextFactory* text) { text_ = text; }

    void Render(ID2D1DeviceContext* dc, const Theme& theme) override;
    bool HitTest(float x, float y) const override;
    bool OnInput(const InputEvent& event) override;
    bool IsFocusable() const override { return enabled_; }
    void OnFocus(bool focused) override;

    bool Hovered() const noexcept { return hovered_; }
    bool Focused() const noexcept { return focused_; }
    bool Activated() const noexcept { return activated_; }

    // 中间省略：保留头 head 个与尾 tail 个字符，以 U+2026 连接。
    static std::wstring MiddleEllipsize(const std::wstring& path, std::size_t head, std::size_t tail);

private:
    D2D1_RECT_F bounds_{};
    std::wstring path_;
    bool enabled_ = true;
    bool hovered_ = false;
    bool focused_ = false;
    bool activated_ = false;
    const TextFactory* text_ = nullptr;
};

}  // namespace faf
