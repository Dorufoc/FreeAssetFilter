#pragma once

// Minimal duilib-compatible rendering surface used by the installer shell.
// The public surface deliberately mirrors the controls needed by the XML layout.
#include <windows.h>
#include <string>
#include <vector>

namespace duilib {

struct Color {
    COLORREF value;
};

class Control {
public:
    virtual ~Control() = default;
    virtual void Paint(HDC dc) = 0;
    RECT bounds{};
    bool visible{true};
};

class Label final : public Control {
public:
    std::wstring text;
    int fontSize{12};
    bool bold{false};
    COLORREF color{RGB(32, 32, 32)};
    void Paint(HDC dc) override;
};

class Button final : public Control {
public:
    std::wstring text;
    bool primary{false};
    bool enabled{true};
    void Paint(HDC dc) override;
    bool Hit(POINT point) const;
};

class ProgressBar final : public Control {
public:
    int percent{0};
    void Paint(HDC dc) override;
};

class XmlLayout {
public:
    static std::vector<Control*> BuildDefaultControls();
};

} // namespace duilib
