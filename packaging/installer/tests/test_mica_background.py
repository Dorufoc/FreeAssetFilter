"""Verify the compositor leaves the native backdrop exposed behind page content."""
from pathlib import Path
import unittest


WINDOW = Path(__file__).resolve().parents[1] / 'src' / 'installer_window.cpp'


class MicaBackgroundTests(unittest.TestCase):
    def test_backdrop_uses_light_mica_alt(self) -> None:
        source = WINDOW.read_text(encoding='utf-8')
        setup = source.split('void InstallerWindow::InstallDwmEffects()', 1)[1].split(
            'void InstallerWindow::UpdateWindowTitle()', 1
        )[0]
        self.assertIn('backdrop = DWMSBT_TABBEDWINDOW', setup)
        self.assertIn('const BOOL dark = FALSE', setup)
    def test_native_mica_path_has_no_client_area_fill(self) -> None:
        source = WINDOW.read_text(encoding='utf-8')
        _, body = source.split('void InstallerWindow::DrawWindowCard(', 1)
        body = body.split('void InstallerWindow::DrawTitleBar(', 1)[0]
        self.assertIn('if (win10Fallback_)', body)
        self.assertIn('FillRoundedRectangle', body)
        self.assertNotIn('FillRectangle(', body, 'A client-area wash makes native Mica look white')
        self.assertNotIn('theme.card', body, 'The panel fill token must not tint the Mica backdrop')


if __name__ == '__main__':
    unittest.main()
