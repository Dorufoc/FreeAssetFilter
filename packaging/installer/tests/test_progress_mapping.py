"""Exercise extraction and copy range boundaries with real payload files."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest


GUI = Path(os.environ.get('SPK_TEST_GUI', 'build/installer-qa-verified/SopeekInstaller.exe')).resolve()


@unittest.skipUnless(os.name == 'nt' and GUI.is_file(), 'requires the Windows test GUI')
class ProgressMappingTests(unittest.TestCase):
    def test_ready_boundary_and_success_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payload = root / 'payload'
            payload.mkdir()
            (payload / 'half').write_bytes(b'x' * 500)
            diag = root / 'progress.log'
            with subprocess.Popen([sys.executable, '-c', 'import sys; sys.exit(int(input()))'],
                                  stdin=subprocess.PIPE, text=True) as setup:
                try:
                    args = [str(GUI), '/auto:page=4', '/payload', str(payload), '/payload-bytes', '1000',
                            '/installdir', str(root / 'install'), '/result', str(root / 'result.ini'),
                            '/setup-pid', str(setup.pid)]
                    with subprocess.Popen(args, env=dict(os.environ, SPK_DIAG_PATH=str(diag))) as gui:
                        try:
                            def wait_for(pattern: str) -> str:
                                deadline = time.monotonic() + 8
                                while time.monotonic() < deadline:
                                    text = diag.read_text('utf-8', errors='replace') if diag.exists() else ''
                                    if re.search(pattern, text, re.MULTILINE):
                                        return text
                                    time.sleep(.05)
                                self.fail(f'Missing {pattern!r}: {text[-2000:]}')

                            wait_for(r'prepare progress bytes=500 total=1000 permille=400\b')
                            (payload / 'rest').write_bytes(b'x' * 500)
                            wait_for(r'prepare progress bytes=1000 total=1000 permille=800\b')
                            (root / 'payload.ready').touch()
                            pending = wait_for(r'install done ok=1\b')
                            self.assertRegex(pending, r'extraction complete permille=800')
                            self.assertRegex(pending, r'copy progress raw=1000 mapped=999')
                            self.assertNotIn('completion hold start', pending)
                            setup.communicate('0\n', timeout=3)
                            wait_for(r'completion hold start')
                            wait_for(r'auto stop reached page=4')
                        finally:
                            gui.kill()
                finally:
                    setup.kill()


if __name__ == '__main__':
    unittest.main()
