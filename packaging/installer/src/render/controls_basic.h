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

namespace spk {

// 设计稿按钮：主按钮 = 黑色胶囊（152x36, r8, 白字 18px，可选尾部「>」）；
// 次要按钮 = 纯文字链接（16px，无底色无描边，hover 减淡）。禁用态整体降到 40%。
// 状态过渡（hover/pressed）沿用 AnimValue；按下仍有 0.98 轻微缩放。
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
    // 主按钮标签右侧的「>」箭头（设计稿：仅「下一步」有，「立即体验」没有）。
    void SetTrailingChevron(bool on) { trailingChevron_ = on; }
    // 标签字号覆盖（0 = 用设计稿默认：主按钮 18 / 文字链接 16）。
    void SetLabelSize(float sizeDip) { labelSize_ = sizeDip; }
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
    bool trailingChevron_ = false;
    float labelSize_ = 0.0f;
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

// 设计稿复选框：盒子 29x29 DIP、圆角 8、1px #8F8F8F 描边（未勾）。
// 勾选态 = 3px 黑环 + 2px 白缝 + 19x19 黑块（r3）+ 白色对勾（设计稿叠层）。
// 切换约 150ms 动画（checkAnim）。文字标签在盒右侧 8 DIP，16px。
class CheckBox : public Widget {
public:
    void SetBounds(const D2D1_RECT_F& rect) { bounds_ = rect; }
    const D2D1_RECT_F& Bounds() const noexcept { return bounds_; }

    void SetLabel(std::wstring label) { label_ = std::move(label); }
    const std::wstring& Label() const noexcept { return label_; }
    // 盒子边长（DIP）。0 = 设计稿默认 29。
    void SetBoxSize(float size) { boxSize_ = size; }
    float BoxSize() const noexcept { return boxSize_; }
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
    float boxSize_ = 29.0f;
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

// 设计稿路径框：564x36、圆角 8、#EEEEEE 填充 + #E9E9E9 描边、18px #878787 文字。
// 右侧内嵌一个「浏览」文字动作（设计稿没有独立按钮，用户选择内嵌方案）。
// 文本中间省略（保留盘符/根与末段）；点击框内任意位置 = 触发浏览。
class PathField : public Widget {
public:
    void SetBounds(const D2D1_RECT_F& rect) { bounds_ = rect; }
    const D2D1_RECT_F& Bounds() const noexcept { return bounds_; }

    void SetPath(std::wstring path) { path_ = std::move(path); }
    const std::wstring& Path() const noexcept { return path_; }
    // 右侧内嵌动作文案（空 = 不绘制、不占位）。
    void SetActionLabel(std::wstring label) { actionLabel_ = std::move(label); }
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
    // 取出并清除「已点击」闩锁（宿主在分发后检查，避免重复打开对话框）。
    bool TakeActivated() {
        const bool value = activated_;
        activated_ = false;
        return value;
    }

    // 中间省略：保留头 head 个与尾 tail 个字符，以 U+2026 连接。
    static std::wstring MiddleEllipsize(const std::wstring& path, std::size_t head, std::size_t tail);

private:
    D2D1_RECT_F bounds_{};
    std::wstring path_;
    std::wstring actionLabel_;
    bool enabled_ = true;
    bool hovered_ = false;
    bool focused_ = false;
    bool activated_ = false;
    const TextFactory* text_ = nullptr;
};

}  // namespace spk
