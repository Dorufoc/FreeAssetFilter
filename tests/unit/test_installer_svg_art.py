"""Verify the installer uses the artwork and stacking order exported by XD."""
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / 'src/sopeek/resources/icons/install_design'
RENDER = ROOT / 'packaging/installer/src/render'


class InstallerSvgArt(unittest.TestCase):
    def test_brand_uses_exported_stacking_order(self) -> None:
        svg = ET.parse(ART / '英雄页.svg')
        colors = {'cls-4': 'heroTeal', 'cls-5': 'heroBlue', 'cls-7': 'heroGlowTeal',
                  'cls-8': 'heroGlowBlue'}
        order = [colors[n.get('class')] for n in svg.findall('.//{*}path')
                 if n.get('class') in colors]
        expected = list(dict.fromkeys(reversed(order)))[::-1]
        source = (RENDER / 'hero_art.cpp').read_text(encoding='utf-8')
        self.assertEqual(sorted(expected, key=lambda c: source.index('tinted(theme.' + c + ')')), expected)

    def test_progress_does_not_package_or_draw_a_banner(self) -> None:
        resources = (RENDER.parents[1] / 'resources/app.rc').read_text(encoding='utf-8')
        self.assertNotIn('installer-banner.png', resources)
        source = (RENDER / 'pages_progress.cpp').read_text(encoding='utf-8')
        progress = source.split('void ProgressPage::Render(', 1)[1].split('FinishPage::FinishPage(', 1)[0]
        self.assertNotIn('CreateBitmapBrush', progress)
        self.assertNotIn('概念宣传图', progress)
        self.assertNotIn('RenderHeroArtIn', progress)

    def test_stage_anchors_long_status_at_svg_left(self) -> None:
        source = (RENDER / 'pages_progress.cpp').read_text(encoding='utf-8')
        self.assertIn('stageRect_ = BaselineRect(design::kStageLeft', source)
        start = source.index('DrawText(dc, text_, StepText()')
        self.assertIn('DWRITE_TEXT_ALIGNMENT_LEADING', source[start:source.index(';', start)])

    def test_progress_description_aligns_with_stage(self) -> None:
        source = (RENDER / 'pages_progress.cpp').read_text(encoding='utf-8')
        layout = source.split('void ProgressPage::Layout(', 1)[1].split('void ProgressPage::Render(', 1)[0]
        self.assertIn('noticeRect_ = BaselineRect(stageRect_.left,', layout)

    def test_welcome_prefers_designed_bitmap(self) -> None:
        source = (RENDER / 'pages_welcome.cpp').read_text(encoding='utf-8')
        welcome = source.split('void WelcomePage::Render(', 1)[1].split('bool WelcomePage::HitTest', 1)[0]
        self.assertLess(welcome.index('DrawHeroBackground('), welcome.index('DrawHeroArtwork('))
        self.assertIn('install_design\\\\bg.png', (RENDER.parents[1] / 'resources/app.rc').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
