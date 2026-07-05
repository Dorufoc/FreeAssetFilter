import gc
import unittest
from unittest.mock import MagicMock

from freeassetfilter.utils.async_icon_loader import AsyncIconLoader


class AsyncIconLoaderCallbackLifetimeTests(unittest.TestCase):
    def setUp(self):
        AsyncIconLoader._instance = None

    def tearDown(self):
        AsyncIconLoader._instance = None

    def test_load_icon_keeps_short_lived_callback_alive_until_finish(self):
        loader = AsyncIconLoader()
        loader._pool = MagicMock()
        received = []

        def register_callback():
            def _on_loaded(file_path, pixmap):
                received.append((file_path, pixmap))

            loader.load_icon("C:/demo.exe", _on_loaded, icon_size=64)

        register_callback()
        gc.collect()

        self.assertIn("C:/demo.exe", loader._callbacks)

        loader._on_finished("C:/demo.exe", "pixmap")

        self.assertEqual(received, [("C:/demo.exe", "pixmap")])
        self.assertNotIn("C:/demo.exe", loader._callbacks)


if __name__ == "__main__":
    unittest.main()
