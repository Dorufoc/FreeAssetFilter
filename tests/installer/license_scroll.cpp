#include "render/controls_feedback.h"
#include <cstdio>

int main() {
    spk::LicenseBox box;
    spk::Animator animator;
    box.SetBounds({0, 0, 400, 240});
    box.SetText(std::wstring(8000, L'x'));
    box.BindAnimator(&animator);
    box.OnInput({spk::InputEvent::Wheel, 100, 100, -120});
    if (!animator.IsActive() || box.ScrollOffset() != 0) {
        std::puts("Wheel must animate from the displayed offset");
        return 1;
    }
    animator.Tick(0); animator.Tick(200);
    if (box.ScrollOffset() <= 0) return 2;
    box.SetScrollOffset(0);
    box.OnInput({spk::InputEvent::Down, 390, 18});
    box.OnInput({spk::InputEvent::Move, 390, 225});
    box.OnInput({spk::InputEvent::Up, 390, 225});
    if (!box.AtBottom() || box.Dragging()) {
        std::puts("Moving the thumb down must scroll to the document end");
        return 3;
    }
    return 0;
}
