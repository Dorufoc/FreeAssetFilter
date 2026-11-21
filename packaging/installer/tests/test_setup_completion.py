"""Windows integration regression; run after building the SPK_TESTMODE GUI."""
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[3]
GUI = Path(os.environ.get('SPK_TEST_GUI', ROOT / 'build/test-installer/SopeekInstaller.exe'))


@unittest.skipUnless(os.name == 'nt' and GUI.is_file(), 'requires Windows test GUI')
class SetupCompletionTests(unittest.TestCase):
    def run_install(self, exit_code: int | None, repair: bool = False, update: bool = False) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payload, install, diag = root / 'payload', root / 'install', root / 'diag.txt'
            payload.mkdir()
            (payload / 'probe').write_text('test')
            (root / 'payload.ready').touch()
            args = [str(GUI), f'/auto:page={7 if exit_code else 4}', '/payload', str(payload), '/installdir', str(install),
                    '/result', str(root / 'result.ini')]
            if repair or update:
                install.mkdir()
                (install / 'Sopeek.exe').touch()
                (install / '_internal').mkdir()
                decision = install / 'maintenance-decision.ini'
                (install / '_internal' / 'SPKVERSION').write_text('1.0.0')
                action = 'update' if update else 'repair'
                args.extend(['/maintenance', f'/auto:action={action}', '/decision', str(decision),
                             '/package-version', '2.0.0' if update else '1.0.0'])
            setup = subprocess.Popen([sys.executable, '-c', 'import sys; sys.exit(int(input()))'],
                                     stdin=subprocess.PIPE, text=True)
            self.addCleanup(setup.stdin.close)
            try:
                if exit_code is not None:
                    args.extend(['/setup-pid', str(setup.pid)])
                gui = subprocess.Popen(args, env=dict(os.environ, SPK_DIAG_PATH=str(diag)))
                try:
                    def logs() -> str:
                        return diag.read_text('utf-8', errors='replace') if diag.exists() else ''

                    def expect(marker: str) -> None:
                        until = time.monotonic() + 12
                        while time.monotonic() < until:
                            if marker in logs():
                                return
                            time.sleep(.05)
                        self.fail(f'Missing {marker!r}: {logs()[-2400:]}')

                    expect('install done ok=1')
                    if update or repair:
                        self.assertIn(f'action={action}', decision.read_text('utf-16'))
                    if exit_code is not None:
                        time.sleep(.6)  # longer than the completion animation
                        self.assertNotIn('completion hold start', logs())
                        user32 = ctypes.windll.user32
                        user32.FindWindowW.restype = ctypes.c_void_p
                        hwnd = user32.FindWindowW('SopeekInstaller', None)
                        owner = ctypes.c_ulong()
                        user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(owner))
                        self.assertEqual(owner.value, gui.pid)
                        user32.PostMessageW(ctypes.c_void_p(hwnd), 0x0010, 0, 0)  # WM_CLOSE
                        time.sleep(.15)
                        self.assertIsNone(gui.poll())
                        setup.communicate(f'{exit_code}\n', timeout=3)
                    if exit_code:
                        expect('auto stop reached page=7')
                        self.assertNotIn('completion hold start', logs())
                    else:
                        expect('completion hold start')
                        expect('auto stop reached page=4')
                finally:
                    gui.kill()
                    gui.wait()
            finally:
                setup.kill()
                setup.wait()

    def test_nsis_finalization_failures_return_nonzero(self) -> None:
        script = (ROOT / 'packaging/installer/installer.nsi').read_text('utf-8-sig')
        for label in ('uninstallHelperFailed:', 'uninstallPayloadFailed:'):
            failure = script.split('\n' + label, 1)[1].split('Abort', 1)[0]
            self.assertRegex(failure, r'SetErrorLevel [1-9]')

    def test_setup_success(self) -> None:
        self.run_install(0)

    def test_setup_failure(self) -> None:
        self.run_install(2)

    def test_standalone_finish(self) -> None:
        self.run_install(None)

    def test_repair_success(self) -> None:
        self.run_install(0, repair=True)

    def test_repair_failure(self) -> None:
        self.run_install(2, repair=True)

    def test_update_success(self) -> None:
        self.run_install(0, update=True)

    def test_nsis_launches_with_setup_pid(self) -> None:
        script = (ROOT / 'packaging/installer/installer.nsi').read_text('utf-8-sig')
        launches = [line for line in script.splitlines() if 'Exec ' in line and ' /payload ' in line]
        self.assertTrue(launches)
        for command in launches:
            self.assertIn('/setup-pid $SetupPid', command)


if __name__ == '__main__':
    unittest.main()
