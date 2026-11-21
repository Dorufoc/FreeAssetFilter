"""Contracts for routing agreement links and the fixed installer canvas."""
from pathlib import Path
import unittest

SRC = Path(__file__).resolve().parents[2] / 'packaging/installer/src'


class InstallerLicenseNavigationTests(unittest.TestCase):
    def test_document_open_uses_the_page_router(self) -> None:
        source = (SRC / 'installer_window.cpp').read_text(encoding='utf-8')
        self.assertNotIn('licenseSheet_.Visible()', source)
        self.assertIn('case License: licenseSheet_.Render(ctx, theme); break;', source)
        opener = source.split('void InstallerWindow::OpenLicensePage(', 1)[-1].split('\n}', 1)[0]
        self.assertIn('SetPage(License);', opener)
        back = source.split('void InstallerWindow::GoBack()', 1)[1].split('\n}', 1)[0]
        self.assertIn('case License:\n            SetPage(Configure);', back)

    def test_canvas_dimensions_are_rounded_to_tens(self) -> None:
        source = (SRC / 'render/layout.h').read_text(encoding='utf-8')
        self.assertIn('kCanvasWidth = 640.0f', source)
        self.assertIn('kCanvasHeight = 540.0f', source)


if __name__ == '__main__':
    unittest.main()
