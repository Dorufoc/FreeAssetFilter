#pragma once
//
// controls_feedback.h - WinUI3 可复用控件 B：ProgressBar / LicenseBox / StepItem（Todo 8）。
//
// 实现 controls_base.h 的 Widget 接口（Frozen contracts §13；本文件不另建共享
// controls.h/.cpp，亦不触碰 Todo 7 的 controls_basic.*）。坐标与绘制一律 DIP
// （§6 全程 DIP，绝不乘 DPI）。视觉只消费 theme.h 的 token；过渡只消费 animation.h
// 的 AnimValue——AnimValue 由宿主经 BindAnimator 注入，控件**不自持帧时钟**（避免
// 与 installer_window 的 tick 双重推进）。文字/字形经 text.h/glyphs.h。
//
// 进度语义：ProgressBar 只接受 **permille 0..1000**（Frozen contracts §10，
// 即 WM_INSTALL_PROGRESS 的 wParam 语义），UI 显示百分比 = permille/10.0，
// 填充比例 = permille/1000.0。禁止 0..100 语义。
//
#include <windows.h>

#include <d2d1_1.h>
#include <dwrite.h>

#include <string>

#include "render/animation.h"
#include "render/controls_base.h"
#include "render/glyphs.h"
#include "render/text.h"
#include "render/theme.h"

namespace faf {

// WinUI3 进度条。圆角 4（radius::Small）。
//  - determinate：填充比例平滑插值到新的 permille（无视觉跳变）。
//  - indeterminate：跑马（marquee）由注入的 Animator 驱动循环。
// 非交互控件（不参与 Tab）。
class ProgressBar : public Widget {
public:
    void SetBounds(const D2D1_RECT_F& rect) { bounds_ = rect; }
    const D2D1_RECT_F& Bounds() const noexcept { return bounds_; }

    // §10：接受 permille 0..1000（越界钳制）。设置新目标后平滑插值。
    void SetProgressPermille(int permille);
    // 便捷：0..1 比例 → permille（四舍五入）。
    void SetProgressFraction(float fraction);
    int Permille() const noexcept { return permille_; }

    void SetIndeterminate(bool indeterminate);
    bool Indeterminate() const noexcept { return indeterminate_; }

    // 依赖注入（宿主构造后绑定；为空时退化为即时取值 / 静态跑马）。
    void BindAnimator(Animator* animator);

    void Render(ID2D1DeviceContext* dc, const Theme& theme) override;
    bool HitTest(float x, float y) const override;
    bool OnInput(const InputEvent& event) override;
    bool IsFocusable() const override { return false; }
    void OnFocus(bool focused) override { (void)focused; }

    // 可观测状态（供 harness / 验收断言）。
    float FillFraction() const;   // 0..1 当前填充（无动画器时按 permille 立即取值）
    float MarqueePhase() const;   // 0..1 跑马相位（无动画器时为 0）

private:
    void StartFillAnim(float target);
    void EnsureMarquee();

    D2D1_RECT_F bounds_{};
    int permille_ = 0;
    bool indeterminate_ = false;

    Animator* animator_ = nullptr;
    AnimValue* fillAnim_ = nullptr;
    AnimValue* marqueeAnim_ = nullptr;
    float fillFallback_ = 0.0f;
    std::string fillName_;
    std::string marqueeName_;
};

// WinUI3 可滚动许可框：圆角面板 + 细滚动条 + 滚轮 + 拖拽滚动，顶/底边缘淡出遮罩。
// 长文本（AGPL 全文）由调用方经 SetText 提供；渲染用 IDWriteTextLayout 自动换行。
// 滚动仅做状态/数值运算，**不阻塞 UI 线程**（无同步等待、无复制）。
class LicenseBox : public Widget {
public:
    LicenseBox() = default;
    ~LicenseBox() override;

    LicenseBox(const LicenseBox&) = delete;
    LicenseBox& operator=(const LicenseBox&) = delete;

    void SetBounds(const D2D1_RECT_F& rect);
    const D2D1_RECT_F& Bounds() const noexcept { return bounds_; }

    // AGPL 全文由调用方提供（空文本须安全渲染、不崩）。
    void SetText(std::wstring text);
    const std::wstring& Text() const noexcept { return text_; }

    // 依赖注入。TextFactory 提供文字排版；WriteFactory 供 IDWriteTextLayout 度量
    // （TextFactory 不暴露其工厂，度量换行高度必须用原始 IDWriteFactory）。
    void BindText(const TextFactory* text);
    void BindWriteFactory(IDWriteFactory* factory);
    void BindAnimator(Animator* animator);

    void Render(ID2D1DeviceContext* dc, const Theme& theme) override;
    bool HitTest(float x, float y) const override;
    bool OnInput(const InputEvent& event) override;
    bool IsFocusable() const override { return true; }
    void OnFocus(bool focused) override;

    // 滚动查询/控制（供 harness 断言与宿主接线）。
    float ScrollOffset() const;               // 当前显示偏移（DIP，0 为顶部）
    float MaxScroll() const;                  // 最大偏移（内容高度 - 视口高度，>=0）
    float ContentHeight() const;              // 内容总高（DIP，懒计算）
    void SetScrollOffset(float offset);       // 立即设偏移（钳制）
    void ScrollToBottom();                    // 平滑滚动到底
    bool AtBottom() const;                    // 是否已滚到底

    bool Dragging() const noexcept { return dragging_; }
    bool Focused() const noexcept { return focused_; }

private:
    void EnsureLayout() const;
    void SetTargetOffset(float target, bool animate);
    D2D1_RECT_F PanelRect() const;
    D2D1_RECT_F ContentRect() const;    // 去掉内边距 + 右侧滚动条
    float ViewportHeight() const;

    D2D1_RECT_F bounds_{};
    std::wstring text_;

    const TextFactory* textFactory_ = nullptr;
    IDWriteFactory* writeFactory_ = nullptr;
    Animator* animator_ = nullptr;
    AnimValue* scrollAnim_ = nullptr;

    mutable IDWriteTextLayout* layout_ = nullptr;  // owned；布局失效时重建
    mutable bool layoutDirty_ = true;
    mutable float contentHeight_ = 0.0f;

    float targetOffset_ = 0.0f;   // 期望偏移（动画终点）
    bool dragging_ = false;
    float dragStartY_ = 0.0f;
    float dragStartOffset_ = 0.0f;
    bool focused_ = false;

    std::string scrollName_;
};

// WinUI3 步骤指示器单项：步骤点 + 连接线 + 标签。
//  - Completed：实心 accent 点 + 白/黑自绘圆角矢量对勾（DrawCheckMark；原 glyph::Check 光栅化断口、glyph::Success 为圆圈对勾，均已弃用）；连接线 accent。
//  - Current：accent 强调环 + 内点（强调动画）；标签 semiBold。
//  - Future：次级描边环，无填充；标签次级色。
// 状态切换经 AnimValue 动画过渡（未注入 Animator 时即时取态）。
class StepItem : public Widget {
public:
    enum State { Future, Current, Completed };

    // 追加需求（2026-10-18）：排布方向。
    //  - Vertical（默认）：左栏竖向（标签在节点右侧，连接线竖直穿过节点）——保留不变。
    //  - Horizontal：顶部横向（标签在节点上方，连接线横向穿过节点）。
    enum class Orientation { Vertical, Horizontal };

    void SetBounds(const D2D1_RECT_F& rect) { bounds_ = rect; }
    const D2D1_RECT_F& Bounds() const noexcept { return bounds_; }

    void SetIndex(int index) { index_ = index; }
    int Index() const noexcept { return index_; }
    void SetLabel(std::wstring label) { label_ = std::move(label); }
    const std::wstring& Label() const noexcept { return label_; }

    void SetOrientation(Orientation orientation) { orientation_ = orientation; }
    Orientation GetOrientation() const noexcept { return orientation_; }

    void SetState(State state);
    State CurrentState() const noexcept { return state_; }
    // 便捷：按「全局当前步」推导本项状态（index < current ⇒ Completed；== ⇒ Current）。
    void SetStep(int index, int currentStep);
    // 最后一项不画向下的连接线残段。
    void SetLast(bool last) { last_ = last; }

    // 依赖注入。
    void BindAnimator(Animator* animator);
    void BindText(const TextFactory* text) { text_ = text; }
    void BindGlyphs(const GlyphFont* glyphs) { glyphs_ = glyphs; }

    void Render(ID2D1DeviceContext* dc, const Theme& theme) override;
    bool HitTest(float x, float y) const override;
    bool OnInput(const InputEvent& event) override;
    bool IsFocusable() const override { return false; }
    void OnFocus(bool focused) override { (void)focused; }

    // 可观测状态（供 harness 断言动画完整）。
    float Emphasis() const;      // 0..1 当前步强调
    float CheckProgress() const; // 0..1 完成对勾

private:
    void StartAnims();

    D2D1_RECT_F bounds_{};
    int index_ = 0;
    bool last_ = false;
    Orientation orientation_ = Orientation::Vertical;  // 默认竖向（保留既有行为）
    std::wstring label_;
    State state_ = Future;

    Animator* animator_ = nullptr;
    AnimValue* emphAnim_ = nullptr;
    AnimValue* checkAnim_ = nullptr;
    float emphFallback_ = 0.0f;
    float checkFallback_ = 0.0f;
    std::string emphName_;
    std::string checkName_;

    const TextFactory* text_ = nullptr;
    const GlyphFont* glyphs_ = nullptr;
};

}  // namespace faf
