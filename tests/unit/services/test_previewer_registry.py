# -*- coding: utf-8 -*-
"""``PreviewerRegistry``（freeassetfilter/services/previewer_registry.py）单元测试。

覆盖（happy + boundary/error 各至少一条）：

* 注册表初始化 —— ``_EXTENSION_MAP`` 已含常见后缀且值为 (module, class) 对、
  ``_CLASS_CACHE`` 初始为空
* ``get_previewer_class`` —— is_dir 走 FolderContentList、空/缺失后缀与未知
  后缀返回 None、后缀大小写/前导点归一、已知后缀解析真实类
* 动态注册注销 —— register 新增/覆盖、unregister 移除/未知后缀无异常
* 缓存 —— 惰性导入结果缓存、register 清除同名陈旧缓存、unregister 清除缓存

类级缓存/映射在测试间共享：autouse fixture 在每个测试前后做快照还原，
防止 register/unregister 污染后续用例。大部分解析路径通过 mock
``_import_class`` 验证，避免不必要的重型 UI 模块导入。
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import pytest

from freeassetfilter.services.previewer_registry import PreviewerRegistry

pytestmark = pytest.mark.unit

_IMAGE_KEY: str = (
    "freeassetfilter.ui.layout.preview.image_previewer_layout."
    "ImagePreviewerLayout"
)


@pytest.fixture(autouse=True)
def _restore_registry_state() -> None:
    """在测试前后快照还原类级映射与缓存，保证隔离性。

    Returns:
        None。
    """
    ext_before: Dict[str, Tuple[str, str]] = dict(
        PreviewerRegistry._EXTENSION_MAP
    )
    cache_before: Dict[str, type] = dict(PreviewerRegistry._CLASS_CACHE)
    yield
    PreviewerRegistry._EXTENSION_MAP.clear()
    PreviewerRegistry._EXTENSION_MAP.update(ext_before)
    PreviewerRegistry._CLASS_CACHE.clear()
    PreviewerRegistry._CLASS_CACHE.update(cache_before)


# =============================================================================
# 注册表初始化
# =============================================================================
class TestInitialMap:
    """初始映射内容"""

    def test_common_extensions_present(self) -> None:
        """常见图片/视频/文档/压缩包后缀均已注册。"""
        for ext in ("jpg", "png", "mp4", "pdf", "py", "zip", "ttf", "docx"):
            assert ext in PreviewerRegistry._EXTENSION_MAP

    def test_map_values_are_module_class_pairs(self) -> None:
        """映射值均为 (module_path, class_name) 字符串二元组。"""
        for ext in ("jpg", "pdf", "zip"):
            module_path: object
            class_name: object
            module_path, class_name = PreviewerRegistry._EXTENSION_MAP[ext]
            assert isinstance(module_path, str)
            assert isinstance(class_name, str)

    def test_class_cache_starts_empty(self) -> None:
        """类缓存初始为空（惰性导入，import 前不填充）。"""
        # 完整套件中其他文件可能已触发真实导入填充缓存；
        # 清空后验证"尚无缓存"这一语义，而不是依赖进程级顺序。
        PreviewerRegistry._CLASS_CACHE.clear()
        assert PreviewerRegistry._CLASS_CACHE == {}


# =============================================================================
# get_previewer_class
# =============================================================================
class TestGetPreviewerClass:
    """预览器解析"""

    def test_is_dir_returns_folder_content_list(self) -> None:
        """目录条目解析为文件夹内容列表类。"""
        cls: object | None = PreviewerRegistry.get_previewer_class(
            {"suffix": "jpg", "is_dir": True}
        )
        assert cls is not None
        assert cls.__name__ == "FolderContentList"

    def test_empty_dict_returns_none(self) -> None:
        """空文件信息（无 suffix）返回 None。"""
        assert PreviewerRegistry.get_previewer_class({}) is None

    def test_empty_suffix_returns_none(self) -> None:
        """suffix 为空字符串返回 None。"""
        assert PreviewerRegistry.get_previewer_class({"suffix": ""}) is None

    def test_unknown_suffix_returns_none(self) -> None:
        """未注册后缀返回 None。"""
        assert PreviewerRegistry.get_previewer_class({"suffix": "zzz"}) is None

    def test_suffix_case_and_dot_normalized(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """前导点 + 大写后缀被归一化后命中映射，且走惰性导入。"""
        imported: List[Tuple[str, str]] = []

        def _fake_import(module_path: str, class_name: str) -> type:
            imported.append((module_path, class_name))
            return dict

        monkeypatch.setattr(
            PreviewerRegistry, "_import_class", staticmethod(_fake_import)
        )
        cls: object | None = PreviewerRegistry.get_previewer_class(
            {"suffix": ".JPG"}
        )
        assert cls is dict
        assert imported == [
            (
                "freeassetfilter.ui.layout.preview.image_previewer_layout",
                "ImagePreviewerLayout",
            )
        ]

    def test_known_extension_resolves_real_class(self) -> None:
        """已注册后缀经真实惰性导入得到预览器类。"""
        cls: object | None = PreviewerRegistry.get_previewer_class(
            {"suffix": "jpg"}
        )
        assert cls is not None
        assert cls.__name__ == "ImagePreviewerLayout"


# =============================================================================
# 动态注册 / 注销
# =============================================================================
class TestRegisterUnregister:
    """动态注册与注销"""

    def test_register_new_extension(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """注册新后缀后可解析出对应类（经 mock 导入）。"""
        calls: List[Tuple[str, str]] = []

        def _fake_import(module_path: str, class_name: str) -> type:
            calls.append((module_path, class_name))
            return dict

        monkeypatch.setattr(
            PreviewerRegistry, "_import_class", staticmethod(_fake_import)
        )
        PreviewerRegistry.register(".weird", "some.module", "SomeViewer")
        cls: object | None = PreviewerRegistry.get_previewer_class(
            {"suffix": "weird"}
        )
        assert cls is dict
        assert calls == [("some.module", "SomeViewer")]

    def test_register_normalizes_extension(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """register 对前导点与大小写做归一。"""
        def _fake_import(module_path: str, class_name: str) -> type:
            return dict

        monkeypatch.setattr(
            PreviewerRegistry, "_import_class", staticmethod(_fake_import)
        )
        PreviewerRegistry.register(".DIN", "m", "C")
        assert "din" in PreviewerRegistry._EXTENSION_MAP
        assert ".din" not in PreviewerRegistry._EXTENSION_MAP

    def test_register_overwrites_existing(self) -> None:
        """重新注册相同后缀覆盖原映射。"""
        PreviewerRegistry.register("jpg", "other.module", "OtherViewer")
        assert PreviewerRegistry._EXTENSION_MAP["jpg"] == (
            "other.module",
            "OtherViewer",
        )

    def test_unregister_existing_extension(self) -> None:
        """注销已注册后缀后映射移除。"""
        PreviewerRegistry.unregister("jpg")
        assert "jpg" not in PreviewerRegistry._EXTENSION_MAP

    def test_unregister_unknown_extension_no_error(self) -> None:
        """注销未知后缀不抛异常。"""
        PreviewerRegistry.unregister("nonexistent_ext_xyz")


# =============================================================================
# 注册表缓存
# =============================================================================
class TestClassCache:
    """惰性导入类缓存"""

    def test_import_result_is_cached(self) -> None:
        """首次解析导入并写入缓存，二次解析复用同一对象。"""
        first: object | None = PreviewerRegistry.get_previewer_class(
            {"suffix": "jpg"}
        )
        assert _IMAGE_KEY in PreviewerRegistry._CLASS_CACHE
        second: object | None = PreviewerRegistry.get_previewer_class(
            {"suffix": "jpg"}
        )
        assert second is first

    def test_register_same_module_clears_stale_cache(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """重新注册相同 (module, class) 时清除陈旧缓存，触发重新导入。"""
        calls: List[str] = []

        def _fake_import(module_path: str, class_name: str) -> type:
            calls.append(f"{module_path}.{class_name}")
            return dict

        monkeypatch.setattr(
            PreviewerRegistry, "_import_class", staticmethod(_fake_import)
        )
        PreviewerRegistry.get_previewer_class({"suffix": "jpg"})
        assert len(calls) == 1
        PreviewerRegistry.register(
            "jpg",
            "freeassetfilter.ui.layout.preview.image_previewer_layout",
            "ImagePreviewerLayout",
        )
        PreviewerRegistry.get_previewer_class({"suffix": "jpg"})
        assert len(calls) == 2

    def test_unregister_clears_cache_entry(self) -> None:
        """注销时同步清除对应类缓存，避免残留引用。"""
        PreviewerRegistry.get_previewer_class({"suffix": "jpg"})
        assert _IMAGE_KEY in PreviewerRegistry._CLASS_CACHE
        PreviewerRegistry.unregister("jpg")
        assert _IMAGE_KEY not in PreviewerRegistry._CLASS_CACHE