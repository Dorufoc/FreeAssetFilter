#pragma once
//
// controls_base.h - 本安装器唯一的控件基接口（Frozen contracts §13）。
//
// Todo 7/8 实现 Widget 派生控件；Todo 12（页面状态机）通过 WidgetHost 做 Tab
// 顺序管理与输入分发。所有派生控件必须实现本头文件的虚接口。控件坐标一律为
// DIP（Frozen contracts §6）。
//
#include <windows.h>

#include <d2d1_1.h>

#include <cstddef>
#include <vector>

#include "render/theme.h"

namespace spk {

// 归一化输入事件。一次只描述一件事（kind 决定其余字段的语义）。
struct InputEvent {
    enum Kind {
        Move,   // 指针移动（x,y 为 DIP 光标位置）
        Down,   // 指针按下（x,y）
        Up,     // 指针抬起（x,y）
        Wheel,  // 滚轮（x,y 为光标位置，key 为带符号滚动量）
        Key,    // 键盘（key 为 VK_* 虚拟键码，shift 为 Shift 修饰）
        Focus,  // 焦点变化（保留给宿主，控件不经 OnInput 处理）
    };

    Kind kind = Move;
    float x = 0.0f;
    float y = 0.0f;
    int key = 0;
    bool shift = false;
};

// 控件基类。
class Widget {
public:
    virtual ~Widget() = default;

    // 绘制自身（dc/theme 由宿主提供）。
    virtual void Render(ID2D1DeviceContext* dc, const Theme& theme) = 0;

    // 命中测试（DIP 坐标）。
    virtual bool HitTest(float x, float y) const = 0;

    // 处理输入；返回 true 表示已消费。
    virtual bool OnInput(const InputEvent& event) = 0;

    // 是否可获取键盘焦点（参与 Tab 顺序）。
    virtual bool IsFocusable() const { return false; }

    // 焦点变化回调。
    virtual void OnFocus(bool focused) { (void)focused; }
};

// Tab 顺序 + 输入分发宿主（Todo 12 使用）。注册顺序即 Tab 顺序。
class WidgetHost {
public:
    void Add(Widget* widget) {
        if (widget) widgets_.push_back(widget);
    }

    void Clear() {
        widgets_.clear();
        focused_ = nullptr;
    }

    const std::vector<Widget*>& Widgets() const noexcept { return widgets_; }

    // 指针/键盘事件分发：键盘事件送给焦点控件；指针事件先命中测试。
    // 命中可聚焦控件且为按下事件时，焦点随之转移。
    bool Dispatch(const InputEvent& event) {
        if (event.kind == InputEvent::Key) {
            return focused_ ? focused_->OnInput(event) : false;
        }
        for (std::size_t i = 0; i < widgets_.size(); ++i) {
            Widget* widget = widgets_[i];
            if (widget->HitTest(event.x, event.y)) {
                if (event.kind == InputEvent::Down && widget->IsFocusable()) FocusWidget(widget);
                return widget->OnInput(event);
            }
        }
        return false;
    }

    void FocusWidget(Widget* widget) {
        if (widget == focused_) return;
        if (focused_) focused_->OnFocus(false);
        focused_ = widget;
        if (focused_) focused_->OnFocus(true);
    }

    Widget* Focused() const noexcept { return focused_; }

    // Tab / Shift+Tab 在可聚焦控件间循环（backward=true 为 Shift+Tab）。
    void FocusNext(bool backward = false) {
        const int count = static_cast<int>(widgets_.size());
        if (count == 0) return;

        int start = -1;
        for (int i = 0; i < count; ++i) {
            if (widgets_[i] == focused_) {
                start = i;
                break;
            }
        }

        for (int step = 1; step <= count; ++step) {
            int index;
            if (start < 0) {
                index = backward ? (count - step) : (step - 1);
            } else if (backward) {
                index = ((start - step) % count + count) % count;
            } else {
                index = (start + step) % count;
            }
            if (widgets_[index]->IsFocusable()) {
                FocusWidget(widgets_[index]);
                return;
            }
        }
    }

private:
    std::vector<Widget*> widgets_;
    Widget* focused_ = nullptr;
};

}  // namespace spk
