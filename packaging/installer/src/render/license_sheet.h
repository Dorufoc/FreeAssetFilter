#pragma once
// 安装配置页链接进入的独立协议阅读页。
// 复用 LicenseBox 的滚动视口，由安装器页面宿主管理切换和输入路由。

#include <string>

#include "render/controls_basic.h"
#include "render/controls_feedback.h"

namespace spk {

class LicenseSheet {
public:
    LicenseSheet();

    void BindText(const TextFactory* text);
    void BindWriteFactory(IDWriteFactory* factory) { box_.BindWriteFactory(factory); }
    void BindAnimator(Animator* animator);

    void SetContent(std::wstring title, std::wstring body);
    void Layout(const D2D1_RECT_F& contentCard);
    void Enter();
    void Render(ID2D1DeviceContext* dc, const Theme& theme);

    LicenseBox& Box() noexcept { return box_; }
    Button& BackButton() noexcept { return backButton_; }
    WidgetHost& Host() noexcept { return host_; }

private:
    const TextFactory* text_ = nullptr;
    LicenseBox box_;
    Button backButton_;
    WidgetHost host_;
    std::wstring title_;

    D2D1_RECT_F card_{};
    D2D1_RECT_F titleRect_{};
};

}  // namespace spk
