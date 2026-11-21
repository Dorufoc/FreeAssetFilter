"""Check the version helper used by the maintenance entry point."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
GUI = Path(os.environ.get('SPK_TEST_GUI', ROOT / 'build/test-installer/SopeekInstaller.exe'))


@unittest.skipUnless(os.name == 'nt' and GUI.is_file(), 'requires Windows installer GUI')
class MaintenanceVersions(unittest.TestCase):
    def test_version_relationships(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            internal = root / '_internal'
            internal.mkdir()
            version = internal / 'SPKVERSION'
            for installed, package, expected in [
                ('2.0.0', '2.0.1', 10),
                ('v2.0.1', '2.0.1', 0),
                ('2.0.2', '2.0.1', 11),
                ('unknown', '2.0.1', 12),
                ('2.0.0-alpha.10', '2.0.0-alpha.9', 11),
                ('2.0.0-rc.1', '2.0.0', 10),
                ('v2.0.0.nightly-20261114', '2.0.0', 11),
                ('2.0.0', '', 12),
            ]:
                with self.subTest(installed=installed, package=package):
                    version.write_text(installed, encoding='utf-8-sig')
                    result = subprocess.run([str(GUI), '/version-decision', '/installdir', str(root),
                                             '/package-version', package], timeout=5)
                    self.assertEqual(result.returncode, expected)


if __name__ == '__main__':
    unittest.main()
