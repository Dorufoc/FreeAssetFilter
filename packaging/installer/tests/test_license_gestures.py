"""Integration contracts for the Win32 license-page gesture route."""
from pathlib import Path
import unittest


SOURCE = Path(__file__).resolve().parents[1] / 'src' / 'installer_window.cpp'


class LicenseGestureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = SOURCE.read_text(encoding='utf-8')

    def test_native_vertical_pan_uses_the_license_body_and_retains_inertia(self) -> None:
        self.assertIn('GC_PAN_WITH_SINGLE_FINGER_VERTICALLY', self.source)
        self.assertIn('GC_PAN_WITH_INERTIA', self.source)
        self.assertIn('GetGestureInfo(handle, &gesture)', self.source)
        handler = self.source.split('bool InstallerWindow::HandleLicensePan(', 1)[1].split('\n}', 1)[0]
        self.assertIn('state_.page != License', handler)
        self.assertIn('box.HitTest(dx, dy)', handler)
        self.assertIn('ScreenToClient(window_, &point)', handler)
        self.assertIn('ClientPointToDip(point, &dx, &dy)', handler)
        self.assertIn('spk::InputEvent::Down', handler)
        self.assertIn('spk::InputEvent::Move', handler)
        self.assertNotIn('GF_INERTIA', handler, 'Inertial locations use the regular pan update path')

    def test_gesture_handle_closes_once_and_page_exit_ends_pan(self) -> None:
        self.assertIn('if (msg == WM_GESTURE) {', self.source)
        route = self.source.split('if (msg == WM_GESTURE) {', 1)[1].split('if (msg == WM_LBUTTONDOWN)', 1)[0]
        self.assertIn('if (HandleLicensePan(gesture))', route)
        self.assertIn('CloseGestureInfoHandle(handle)', route)
        self.assertIn('return DefWindowProcW(hwnd, msg, wp, lp);', route)
        page_route = self.source.split('void InstallerWindow::SetPage(int page)', 1)[1].split('\n}', 1)[0]
        self.assertIn('EndLicensePan();', page_route)

    def test_wheel_retains_signed_sub_notch_delta(self) -> None:
        wheel = self.source.split('if (msg == WM_MOUSEWHEEL)', 1)[1].split('if (msg == WM_KEYDOWN)', 1)[0]
        self.assertIn('ev.key = GET_WHEEL_DELTA_WPARAM(wp);', wheel)
        self.assertIn('DispatchPageInput(ev);', wheel)


if __name__ == '__main__':
    unittest.main()
