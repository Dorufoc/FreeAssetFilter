#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PreviewerRegistry 模块单元测试

测试扩展名到预览器类的映射逻辑、注册/注销、缓存机制。

覆盖方法:
    - get_previewer_class()
    - register()
    - unregister()
    - _import_class()
"""

from typing import Any, Dict
from unittest.mock import MagicMock, call, patch

import pytest

from freeassetfilter.services.previewer_registry import PreviewerRegistry

# ---------------------------------------------------------------------------
# 测试辅助
# ---------------------------------------------------------------------------

# Capture the pristine initial state of _EXTENSION_MAP at import time.
# This runs before any test, so it reflects the original class definition.
_ORIGINAL_EXTENSION_MAP: Dict[str, tuple[str, str]] = dict(
    PreviewerRegistry._EXTENSION_MAP
)


def _reset_registry() -> None:
    """Restore PreviewerRegistry class variables to pristine initial state.

    Clears ``_CLASS_CACHE`` and resets ``_EXTENSION_MAP`` to the original
    extension mappings captured at module import time.  Call this in every
    ``setup_method`` to guarantee test isolation.
    """
    PreviewerRegistry._CLASS_CACHE.clear()
    PreviewerRegistry._EXTENSION_MAP.clear()
    PreviewerRegistry._EXTENSION_MAP.update(_ORIGINAL_EXTENSION_MAP)


# ===========================================================================
# get_previewer_class
# ===========================================================================


class TestGetPreviewerClass:
    """Tests for :meth:`PreviewerRegistry.get_previewer_class`."""

    def setup_method(self) -> None:
        _reset_registry()

    # ── 1-6: 已知扩展名返回正确类 ──────────────────────────────────────

    @pytest.mark.parametrize(
        "suffix, expected_module, expected_class",
        [
            ("jpg", "freeassetfilter.components.photo_viewer", "PhotoViewer"),
            ("pdf", "freeassetfilter.components.pdf_previewer", "PDFPreviewer"),
            ("mp4", "freeassetfilter.components.video_player", "VideoPlayer"),
            ("zip", "freeassetfilter.components.archive_browser", "ArchiveBrowser"),
            ("ttf", "freeassetfilter.components.font_previewer", "FontPreviewWidget"),
            ("txt", "freeassetfilter.components.text_previewer", "TextPreviewWidget"),
        ],
    )
    def test_known_extension_returns_correct_class(
        self, suffix: str, expected_module: str, expected_class: str
    ) -> None:
        """已知扩展名应委托 ``_import_class`` 并返回对应类。

        Given a registered extension
        When  ``get_previewer_class`` is called
        Then  it delegates to ``_import_class`` with the correct
              ``(module_path, class_name)`` pair and returns its result.
        """
        with patch.object(PreviewerRegistry, "_import_class") as mock_import:
            fake_cls = MagicMock(spec=type)
            mock_import.return_value = fake_cls

            result = PreviewerRegistry.get_previewer_class({"suffix": suffix})

            assert result is fake_cls
            mock_import.assert_called_once_with(expected_module, expected_class)

    # ── 7: 未知扩展名 ──────────────────────────────────────────────────

    def test_unknown_extension_returns_none(self) -> None:
        """未知扩展名应返回 ``None``。

        Given an extension that is not in ``_EXTENSION_MAP``
        When  ``get_previewer_class`` is called
        Then  it returns ``None``.
        """
        result = PreviewerRegistry.get_previewer_class({"suffix": "xyq"})
        assert result is None

    # ── 8: 空 suffix ───────────────────────────────────────────────────

    def test_empty_suffix_returns_none(self) -> None:
        """空 suffix 字符串应返回 ``None``。

        Given ``file_info`` with ``suffix=""``
        When  ``get_previewer_class`` is called
        Then  it returns ``None``.
        """
        result = PreviewerRegistry.get_previewer_class({"suffix": ""})
        assert result is None

    # ── 9: suffix 为 None / 缺少 suffix ────────────────────────────────

    def test_none_suffix_returns_none(self) -> None:
        """``suffix=None`` 应返回 ``None``。

        Given ``file_info`` with ``suffix=None``
        When  ``get_previewer_class`` is called
        Then  it returns ``None``.
        """
        result = PreviewerRegistry.get_previewer_class({"suffix": None})
        assert result is None

    def test_missing_suffix_returns_none(self) -> None:
        """缺少 ``suffix`` 键应返回 ``None``。

        Given ``file_info`` without a ``suffix`` key
        When  ``get_previewer_class`` is called
        Then  it returns ``None``.
        """
        result = PreviewerRegistry.get_previewer_class({"foo": "bar"})
        assert result is None

    # ── 10: 目录（is_dir） ─────────────────────────────────────────────

    def test_directory_returns_folder_content_list(self) -> None:
        """``is_dir=True`` 应返回 ``FolderContentList``。

        Given ``file_info`` with ``is_dir=True``
        When  ``get_previewer_class`` is called
        Then  it delegates to ``_import_class`` with the folder-content
              module path.
        """
        with patch.object(PreviewerRegistry, "_import_class") as mock_import:
            fake_cls = MagicMock(spec=type)
            mock_import.return_value = fake_cls

            result = PreviewerRegistry.get_previewer_class({"is_dir": True})

            assert result is fake_cls
            mock_import.assert_called_once_with(
                "freeassetfilter.components.folder_content_list",
                "FolderContentList",
            )

    # ── 边界: 大小写 / 前导点 ──────────────────────────────────────────

    def test_upper_case_suffix(self) -> None:
        """后缀大小写不敏感 —— ``JPG`` 应匹配 ``jpg``。

        Given a suffix in upper case
        When  ``get_previewer_class`` is called
        Then  it still resolves to ``PhotoViewer``.
        """
        with patch.object(PreviewerRegistry, "_import_class") as mock_import:
            mock_import.return_value = MagicMock(spec=type)
            result = PreviewerRegistry.get_previewer_class({"suffix": "JPG"})
            assert result is mock_import.return_value
            mock_import.assert_called_once_with(
                "freeassetfilter.components.photo_viewer", "PhotoViewer"
            )

    def test_leading_dot_is_stripped(self) -> None:
        """前导点 ``.jpg`` 应被自动剥离后匹配 ``jpg``。

        Given a suffix with a leading dot
        When  ``get_previewer_class`` is called
        Then  the dot is stripped and the extension is resolved normally.
        """
        with patch.object(PreviewerRegistry, "_import_class") as mock_import:
            mock_import.return_value = MagicMock(spec=type)
            result = PreviewerRegistry.get_previewer_class({"suffix": ".jpg"})
            assert result is mock_import.return_value
            mock_import.assert_called_once_with(
                "freeassetfilter.components.photo_viewer", "PhotoViewer"
            )

    def test_is_dir_takes_priority_over_suffix(self) -> None:
        """``is_dir=True`` 优先于 ``suffix`` —— 即使后缀存在也返回文件夹预览器。

        Given ``file_info`` with both ``is_dir=True`` and a known suffix
        When  ``get_previewer_class`` is called
        Then  it returns ``FolderContentList`` (not the suffix-based class).
        """
        with patch.object(PreviewerRegistry, "_import_class") as mock_import:
            mock_import.return_value = MagicMock(spec=type)
            result = PreviewerRegistry.get_previewer_class(
                {"is_dir": True, "suffix": "jpg"}
            )
            mock_import.assert_called_once_with(
                "freeassetfilter.components.folder_content_list",
                "FolderContentList",
            )


# ===========================================================================
# register
# ===========================================================================


class TestRegister:
    """Tests for :meth:`PreviewerRegistry.register`."""

    def setup_method(self) -> None:
        _reset_registry()

    # ── 11 ──────────────────────────────────────────────────────────────

    def test_register_new_extension(self) -> None:
        """注册新扩展名后可通过 ``get_previewer_class`` 获取。

        Given a newly registered extension
        When  ``get_previewer_class`` is called with that suffix
        Then  it returns the registered previewer class.
        """
        PreviewerRegistry.register("newfmt", "some.module", "SomeClass")

        with patch.object(PreviewerRegistry, "_import_class") as mock_import:
            fake_cls = MagicMock(spec=type)
            mock_import.return_value = fake_cls

            result = PreviewerRegistry.get_previewer_class({"suffix": "newfmt"})

            assert result is fake_cls
            mock_import.assert_called_once_with("some.module", "SomeClass")

    def test_register_strips_leading_dot(self) -> None:
        """``register`` 应自动清理扩展名中的前导点。

        Given an extension with a leading dot
        When  it is registered
        Then  the dot is stripped before storage.
        """
        PreviewerRegistry.register(".newfmt", "some.module", "SomeClass")

        with patch.object(PreviewerRegistry, "_import_class") as mock_import:
            mock_import.return_value = MagicMock(spec=type)
            result = PreviewerRegistry.get_previewer_class({"suffix": "newfmt"})
            assert result is mock_import.return_value

    def test_register_overwrites_existing(self) -> None:
        """为已有扩展名注册新映射应覆盖旧的映射。

        Given an already registered extension
        When  ``register`` is called with a different module/class
        Then  subsequent ``get_previewer_class`` uses the new mapping.
        """
        PreviewerRegistry.register("jpg", "other.module", "OtherViewer")

        with patch.object(PreviewerRegistry, "_import_class") as mock_import:
            mock_import.return_value = MagicMock(spec=type)
            PreviewerRegistry.get_previewer_class({"suffix": "jpg"})
            mock_import.assert_called_once_with("other.module", "OtherViewer")

    def test_register_lowercases_extension(self) -> None:
        """``register`` 应将扩展名转为小写。

        Given an extension in mixed case
        When  it is registered
        Then  the stored key is lowercase.
        """
        PreviewerRegistry.register("MxF", "some.module", "SomeClass")

        with patch.object(PreviewerRegistry, "_import_class") as mock_import:
            mock_import.return_value = MagicMock(spec=type)
            # Query with various cases
            PreviewerRegistry.get_previewer_class({"suffix": "mxf"})
            PreviewerRegistry.get_previewer_class({"suffix": "MXF"})
            PreviewerRegistry.get_previewer_class({"suffix": "Mxf"})
            assert mock_import.call_count == 3  # cache hit → no reimports
            # Second and third calls should be cache hits
            mock_import.assert_has_calls(
                [call("some.module", "SomeClass")] * 3
            )


# ===========================================================================
# unregister
# ===========================================================================


class TestUnregister:
    """Tests for :meth:`PreviewerRegistry.unregister`."""

    def setup_method(self) -> None:
        _reset_registry()

    # ── 12 ──────────────────────────────────────────────────────────────

    def test_unregister_existing_extension_returns_none(self) -> None:
        """注销已有扩展名后 ``get_previewer_class`` 应返回 ``None``。

        Given a registered extension
        When  it is unregistered
        Then  subsequent ``get_previewer_class`` returns ``None``.
        """
        PreviewerRegistry.unregister("jpg")
        result = PreviewerRegistry.get_previewer_class({"suffix": "jpg"})
        assert result is None

    def test_unregister_nonexistent_does_not_raise(self) -> None:
        """注销不存在的扩展名不应抛出异常。

        Given an extension that is not in the map
        When  ``unregister`` is called
        Then  no exception is raised and other entries are unaffected.
        """
        PreviewerRegistry.unregister("nonexistent")  # must not raise

        # Verify other extensions still work
        with patch.object(PreviewerRegistry, "_import_class") as mock_import:
            mock_import.return_value = MagicMock(spec=type)
            result = PreviewerRegistry.get_previewer_class({"suffix": "jpg"})
            assert result is mock_import.return_value

    def test_unregister_strips_leading_dot(self) -> None:
        """``unregister`` 应自动清理前导点。

        Given an extension with a leading dot
        When  it is unregistered
        Then  the same extension without dot is also removed.
        """
        PreviewerRegistry.unregister(".jpg")
        result = PreviewerRegistry.get_previewer_class({"suffix": "jpg"})
        assert result is None

    def test_unregister_lowercases_extension(self) -> None:
        """``unregister`` 应将扩展名转为小写。

        Given an extension in upper case
        When  it is unregistered
        Then  the lowercase version is removed from the map.
        """
        PreviewerRegistry.unregister("JPG")
        result = PreviewerRegistry.get_previewer_class({"suffix": "jpg"})
        assert result is None

    def test_unregister_clears_class_cache(self) -> None:
        """注销时应同时清除类缓存中对应的条目。

        Given a cached previewer class
        When  its extension is unregistered
        Then  the cache entry is removed.
        """
        # Directly populate the cache since _import_class is not being
        # tested here — we only verify unregister's side-effect on _CLASS_CACHE.
        cache_key = "freeassetfilter.components.photo_viewer.PhotoViewer"
        PreviewerRegistry._CLASS_CACHE[cache_key] = MagicMock(spec=type)
        assert cache_key in PreviewerRegistry._CLASS_CACHE

        PreviewerRegistry.unregister("jpg")
        assert cache_key not in PreviewerRegistry._CLASS_CACHE


# ===========================================================================
# 缓存机制
# ===========================================================================


class TestCache:
    """Tests for the ``_CLASS_CACHE`` caching behavior.

    Verifies that the lazy-import cache avoids redundant imports when
    the same module/class pair is requested multiple times.
    """

    def setup_method(self) -> None:
        _reset_registry()

    # ── 13 ──────────────────────────────────────────────────────────────

    def test_second_call_uses_cache(self) -> None:
        """第二次调用 ``get_previewer_class`` 不应再次 import。

        Given the same extension called twice
        When  ``get_previewer_class`` returns
        Then  the second call retrieves from cache without calling
              ``importlib.import_module`` again.
        """
        with patch(
            "freeassetfilter.services.previewer_registry.importlib.import_module"
        ) as mock_import:
            mock_module = MagicMock()
            mock_module.PhotoViewer = MagicMock(spec=type)
            mock_import.return_value = mock_module

            cls1 = PreviewerRegistry.get_previewer_class({"suffix": "jpg"})
            cls2 = PreviewerRegistry.get_previewer_class({"suffix": "jpg"})

            # Same object from cache
            assert cls1 is cls2
            # Only one import call
            mock_import.assert_called_once()

    def test_different_extensions_same_class_share_cache(self) -> None:
        """不同扩展名映射到同一类时共享缓存。

        Given ``jpg`` and ``jpeg`` both map to ``PhotoViewer``
        When  both are queried
        Then  only one import is performed.
        """
        with patch(
            "freeassetfilter.services.previewer_registry.importlib.import_module"
        ) as mock_import:
            mock_module = MagicMock()
            mock_module.PhotoViewer = MagicMock(spec=type)
            mock_import.return_value = mock_module

            cls1 = PreviewerRegistry.get_previewer_class({"suffix": "jpg"})
            cls2 = PreviewerRegistry.get_previewer_class({"suffix": "jpeg"})

            assert cls1 is cls2
            # Only one import because both share the same cache key
            # (photo_viewer.PhotoViewer)
            mock_import.assert_called_once()

    def test_cache_key_is_module_dot_class(self) -> None:
        """缓存键格式为 ``module_path.ClassName``。

        Given a successfully imported class
        When  the cache is populated
        Then  the cache key matches ``{module_path}.{class_name}``.
        """
        with patch(
            "freeassetfilter.services.previewer_registry.importlib.import_module"
        ) as mock_import:
            mock_module = MagicMock()
            mock_module.PhotoViewer = MagicMock(spec=type)
            mock_import.return_value = mock_module

            PreviewerRegistry.get_previewer_class({"suffix": "jpg"})

            assert (
                "freeassetfilter.components.photo_viewer.PhotoViewer"
                in PreviewerRegistry._CLASS_CACHE
            )


# ===========================================================================
# _import_class
# ===========================================================================


class TestImportClass:
    """Tests for :meth:`PreviewerRegistry._import_class`."""

    def setup_method(self) -> None:
        _reset_registry()

    # ── 14 ──────────────────────────────────────────────────────────────

    def test_import_class_raises_on_bad_module(self) -> None:
        """模块不存在时 ``_import_class`` 应抛出 ``ImportError``。

        Given a non-existent module path
        When  ``_import_class`` is called
        Then  it raises ``ImportError``.
        """
        with patch(
            "freeassetfilter.services.previewer_registry.importlib.import_module",
            side_effect=ImportError("No module named 'nonexistent'"),
        ):
            with pytest.raises(ImportError, match="No module named"):
                PreviewerRegistry._import_class("nonexistent", "SomeClass")

    def test_import_class_successful_import(self) -> None:
        """正常导入应缓存并返回正确的类对象。

        Given an existing module with the requested class
        When  ``_import_class`` is called
        Then  it returns the class and populates the cache.
        """
        with patch(
            "freeassetfilter.services.previewer_registry.importlib.import_module"
        ) as mock_import:
            mock_module = MagicMock()
            mock_class = MagicMock(spec=type)
            mock_module.SomeWidget = mock_class
            mock_import.return_value = mock_module

            result = PreviewerRegistry._import_class("mock.module", "SomeWidget")

            assert result is mock_class
            mock_import.assert_called_once_with("mock.module")
            assert (
                "mock.module.SomeWidget" in PreviewerRegistry._CLASS_CACHE
            )

    def test_import_class_raises_on_missing_attr(self) -> None:
        """模块存在但类不存在时应抛出 ``AttributeError``。

        Given an existing module without the requested class
        When  ``_import_class`` is called
        Then  it raises ``AttributeError``.
        """
        with patch(
            "freeassetfilter.services.previewer_registry.importlib.import_module"
        ) as mock_import:
            mock_module = MagicMock(spec=[])  # no attributes
            mock_import.return_value = mock_module

            with pytest.raises(AttributeError):
                PreviewerRegistry._import_class("mock.module", "NonExistent")

    def test_import_class_cache_hit(self) -> None:
        """缓存命中时直接返回，不重新 import。

        Given a previously imported class is still in the cache
        When  ``_import_class`` is called again with the same key
        Then  it returns the cached class without calling
              ``importlib.import_module``.
        """
        with patch(
            "freeassetfilter.services.previewer_registry.importlib.import_module"
        ) as mock_import:
            mock_module = MagicMock()
            mock_class = MagicMock(spec=type)
            mock_module.MyClass = mock_class
            mock_import.return_value = mock_module

            # First call — imports
            result1 = PreviewerRegistry._import_class("mock.module", "MyClass")

            # Second call — should hit cache
            result2 = PreviewerRegistry._import_class("mock.module", "MyClass")

            assert result1 is result2
            mock_import.assert_called_once()


# ===========================================================================
# 完整流程集成
# ===========================================================================


class TestIntegration:
    """跨方法协作的集成测试。"""

    def setup_method(self) -> None:
        _reset_registry()

    def test_register_then_unregister_then_register_again(self) -> None:
        """注册 → 注销 → 再注册同一扩展名，最终获取应成功。

        Given a full lifecycle of register / unregister / register
        When  ``get_previewer_class`` is called
        Then  the final registration takes effect.
        """
        PreviewerRegistry.register("custom", "first.module", "FirstClass")
        PreviewerRegistry.unregister("custom")
        PreviewerRegistry.register("custom", "second.module", "SecondClass")

        with patch.object(PreviewerRegistry, "_import_class") as mock_import:
            mock_import.return_value = MagicMock(spec=type)
            result = PreviewerRegistry.get_previewer_class({"suffix": "custom"})
            assert result is mock_import.return_value
            mock_import.assert_called_once_with("second.module", "SecondClass")

    def test_all_image_extensions_map_to_photo_viewer(self) -> None:
        """所有图像扩展名都映射到 ``PhotoViewer``。

        Given all image extensions listed in ``_EXTENSION_MAP``
        When  ``get_previewer_class`` is called
        Then  each one delegates to ``_import_class`` with ``photo_viewer``.
        """
        image_extensions = [
            ext
            for ext, (mod, _) in PreviewerRegistry._EXTENSION_MAP.items()
            if mod == "freeassetfilter.components.photo_viewer"
        ]

        with patch.object(PreviewerRegistry, "_import_class") as mock_import:
            mock_import.return_value = MagicMock(spec=type)
            for ext in image_extensions:
                PreviewerRegistry.get_previewer_class({"suffix": ext})
            for ext in image_extensions:
                mock_import.assert_any_call(
                    "freeassetfilter.components.photo_viewer", "PhotoViewer"
                )

    def test_unregister_only_affects_specified_extension(self) -> None:
        """注销一个扩展名不影响其他映射。

        Given one extension is unregistered
        When  other extensions are queried
        Then  they still resolve correctly.
        """
        PreviewerRegistry.unregister("jpg")

        with patch.object(PreviewerRegistry, "_import_class") as mock_import:
            mock_import.return_value = MagicMock(spec=type)
            assert (
                PreviewerRegistry.get_previewer_class({"suffix": "png"})
                is mock_import.return_value
            )
            assert (
                PreviewerRegistry.get_previewer_class({"suffix": "mp4"})
                is mock_import.return_value
            )
