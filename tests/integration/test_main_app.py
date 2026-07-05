# -*- coding: utf-8 -*-
"""
Integration tests for main app startup flow.

Tests module-level constants, function existence, and startup configuration
without actually starting the GUI event loop (main() is never called).
"""

import os
import sys
import types

import pytest


class TestMainAppImport:
    """Tests for module importability."""

    def test_import_succeeds(self):
        """Module can be imported without errors."""
        try:
            import freeassetfilter.app.main as m
            assert isinstance(m, types.ModuleType)
        except ImportError as e:
            pytest.fail(f"Failed to import freeassetfilter.app.main: {e}")

    def test_clean_reimport(self):
        """Clean reimport works -- no circular import issues."""
        faf_keys = [k for k in sys.modules if k.startswith("freeassetfilter")]
        saved = {k: sys.modules.pop(k) for k in faf_keys}
        try:
            import freeassetfilter.app.main
            assert hasattr(freeassetfilter.app.main, "main")
        except ImportError as e:
            pytest.fail(f"Clean reimport failed: {e}")
        finally:
            sys.modules.update(saved)


class TestMainAppSymbols:
    """Test that expected symbols exist in the module."""

    def test_main_function_exists(self):
        """main() exists and is callable."""
        from freeassetfilter.app.main import main
        assert callable(main)

    def test_main_block_present(self):
        """Module has if __name__ == '__main__' block that calls main()."""
        import freeassetfilter.app.main as mod
        with open(mod.__file__, encoding="utf-8") as f:
            source = f.read()
        assert 'if __name__ == "__main__":' in source
        # Verify main() is called inside the block
        lines = source.splitlines()
        in_block = False
        main_called = False
        for line in lines:
            if 'if __name__ == "__main__":' in line:
                in_block = True
                continue
            if in_block:
                if "main()" in line:
                    main_called = True
                    break
                # Dedent or blank line after indented block resets
                if line.strip() and not line.startswith((" ", "\t")):
                    break
        assert main_called, "main() should be called from __main__ block"

    def test_handle_exception_exists(self):
        """handle_exception is defined and callable."""
        from freeassetfilter.app.main import handle_exception
        assert callable(handle_exception)

    def test_cleanup_faulthandler_exists(self):
        """cleanup_faulthandler is defined and callable."""
        from freeassetfilter.app.main import cleanup_faulthandler
        assert callable(cleanup_faulthandler)


class TestMainAppStartupSetup:
    """Test startup configuration elements are present."""

    def test_faulthandler_setup(self):
        """faulthandler is imported and module-level flags exist."""
        import freeassetfilter.app.main
        assert hasattr(freeassetfilter.app.main, "faulthandler")
        assert hasattr(freeassetfilter.app.main, "_fault_handler_file")
        assert hasattr(freeassetfilter.app.main, "_fault_handler_enabled")

    def test_console_capture_imported(self):
        """install_console_capture is imported in main module."""
        import freeassetfilter.app.main
        assert hasattr(freeassetfilter.app.main, "install_console_capture")
        assert callable(freeassetfilter.app.main.install_console_capture)

    def test_logger_created(self):
        """logger is created at module level."""
        import freeassetfilter.app.main
        assert hasattr(freeassetfilter.app.main, "logger")
        assert freeassetfilter.app.main.logger is not None

    def test_excepthook_replaced(self):
        """sys.excepthook is set to custom handler after import."""
        import freeassetfilter.app.main
        assert sys.excepthook is not sys.__excepthook__


class TestMainAppVersion:
    """Test version information."""

    def test_package_version(self):
        """freeassetfilter.__version__ is a non-empty string."""
        from freeassetfilter import __version__
        assert isinstance(__version__, str)
        assert len(__version__) > 0

    def test_fafversion_file_exists(self):
        """FAFVERSION file at project root exists and is readable."""
        test_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(os.path.dirname(test_dir))
        fafversion_path = os.path.join(project_root, "FAFVERSION")
        assert os.path.isfile(fafversion_path)
        with open(fafversion_path, encoding="utf-8") as f:
            content = f.read().strip()
        assert len(content) > 0
        assert content.startswith("v")
