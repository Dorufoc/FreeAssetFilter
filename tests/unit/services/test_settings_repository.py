#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SettingsRepository 单元测试

测试 Settings JSON 数据访问层的三种核心方法：
- load()
- save()
- atomic_save()

所有测试均使用 tmp_path 隔离文件操作，不依赖外部状态。
"""

from __future__ import annotations

import json
import os

import pytest

from freeassetfilter.services.settings_repository import SettingsRepository

# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def repo(tmp_path) -> SettingsRepository:
    """提供指向临时路径的 SettingsRepository 实例。"""
    file_path = os.path.join(str(tmp_path), "settings.json")
    return SettingsRepository(file_path)


@pytest.fixture
def sample_settings() -> dict:
    """返回一个简单的非空设置字典。"""
    return {
        "appearance": {
            "theme": "dark",
            "colors": {
                "accent_color": "#007AFF",
                "base_color": "#FFFFFF",
            },
        },
        "font": {
            "size": 10,
            "style": "Microsoft YaHei",
        },
    }


# ── load() — 正常路径 ─────────────────────────────────────────────────


class TestLoad:
    """load() 方法测试：读取 JSON 文件的各种场景。"""

    def test_load_existing_file(self, repo: SettingsRepository,
                                 sample_settings: dict) -> None:
        """Given 一个有效 JSON 文件
           When  load()
           Then  返回解析后的设置字典。"""
        with open(repo.file_path, "w", encoding="utf-8") as f:
            json.dump(sample_settings, f)

        result = repo.load()

        assert result == sample_settings

    def test_load_empty_object(self, repo: SettingsRepository) -> None:
        """Given 一个包含空 JSON 对象的文件
           When  load()
           Then  返回空字典。"""
        with open(repo.file_path, "w", encoding="utf-8") as f:
            f.write("{}")

        result = repo.load()

        assert result == {}

    def test_load_with_unicode(self, repo: SettingsRepository) -> None:
        """Given 包含 Unicode（中文）的 JSON 文件
           When  load()
           Then  正确解码。"""
        settings = {"name": "设置", "description": "这是中文描述"}
        with open(repo.file_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False)

        result = repo.load()

        assert result == settings

    # ── load() — 错误路径 ───────────────────────────────────────────

    def test_load_file_not_exists(self, repo: SettingsRepository) -> None:
        """Given 文件不存在
           When  load()
           Then  返回空字典而不抛出异常。"""
        result = repo.load()

        assert result == {}

    def test_load_corrupted_json(self, repo: SettingsRepository) -> None:
        """Given 文件内容不是合法 JSON
           When  load()
           Then  返回空字典而不抛出异常。"""
        with open(repo.file_path, "w", encoding="utf-8") as f:
            f.write("{invalid json content}")

        result = repo.load()

        assert result == {}

    def test_load_empty_file(self, repo: SettingsRepository) -> None:
        """Given JSON 文件为空
           When  load()
           Then  返回空字典而不抛出异常。"""
        with open(repo.file_path, "w", encoding="utf-8") as f:
            f.write("")

        result = repo.load()

        assert result == {}

    def test_load_oversized_file(self, repo: SettingsRepository) -> None:
        """Given JSON 文件超过 MAX_JSON_SIZE
           When  load()
           Then  返回空字典。"""
        with open(repo.file_path, "w", encoding="utf-8") as f:
            f.write("{")
            f.write(" " * (SettingsRepository.MAX_JSON_SIZE + 1))
            f.write("}")

        result = repo.load()

        assert result == {}

    def test_load_non_utf8_encoding(self, repo: SettingsRepository) -> None:
        """Given JSON 文件编码不是 UTF-8
           When  load()
           Then  返回空字典而不抛出异常。"""
        with open(repo.file_path, "w", encoding="utf-16") as f:
            json.dump({"key": "value"}, f)

        result = repo.load()

        assert result == {}

    def test_load_returns_empty_dict_type(self, repo: SettingsRepository
                                          ) -> None:
        """Given 任何错误场景
           When  load() 返回空字典
           Then  返回值类型为 dict。"""
        result = repo.load()

        assert isinstance(result, dict)

    def test_load_twice_returns_same(self, repo: SettingsRepository,
                                     sample_settings: dict) -> None:
        """Given 一个有效 JSON 文件
           When  连续调用两次 load()
           Then  两次返回内容相同。"""
        with open(repo.file_path, "w", encoding="utf-8") as f:
            json.dump(sample_settings, f)

        first = repo.load()
        second = repo.load()

        assert first == second


# ── save() — 正常路径 ─────────────────────────────────────────────────


class TestSave:
    """save() 方法测试：直接写入 JSON 文件。"""

    def test_save_creates_file(self, repo: SettingsRepository,
                               sample_settings: dict) -> None:
        """Given 一个设置字典
           When  save()
           Then  文件被创建且内容正确。"""
        repo.save(sample_settings)

        assert os.path.exists(repo.file_path)
        with open(repo.file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data == sample_settings

    def test_save_produces_indented_json(self, repo: SettingsRepository,
                                         sample_settings: dict) -> None:
        """Given 一个设置字典
           When  save()
           Then  生成的 JSON 包含缩进（indent=4）。"""
        repo.save(sample_settings)

        with open(repo.file_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "    " in content  # 4-space indentation

    def test_save_ensure_ascii_false(self, repo: SettingsRepository) -> None:
        """Given 包含非 ASCII 字符的设置
           When  save()
           Then  写入的 JSON 包含原始 Unicode，而非 \\u 转义。"""
        settings = {"name": "设置"}
        repo.save(settings)

        with open(repo.file_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "\\u" not in content
        assert "设置" in content

    def test_save_creates_parent_directory(self, tmp_path) -> None:
        """Given 一个深层嵌套的路径
           When  save()
           Then  自动创建父目录。"""
        nested_path = os.path.join(str(tmp_path), "a", "b", "c", "settings.json")
        repo = SettingsRepository(nested_path)
        repo.save({"key": "value"})

        assert os.path.exists(nested_path)
        with open(nested_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data == {"key": "value"}

    def test_save_overwrites_existing(self, repo: SettingsRepository) -> None:
        """Given 一个已有内容的 JSON 文件
           When  save() 写入不同内容
           Then  文件内容被完全覆盖。"""
        with open(repo.file_path, "w", encoding="utf-8") as f:
            json.dump({"old": "data"}, f)

        repo.save({"new": "data"})

        with open(repo.file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data == {"new": "data"}

    # ── save() — 错误路径 ───────────────────────────────────────────

    def test_save_invalid_path(self) -> None:
        """Given 一个不可写入的路径（如根目录下的非法文件名）
           When  save()
           Then  抛出 OSError。"""

        bad_path = os.path.join(
            os.environ.get("SystemRoot", "C:\\Windows"),
            "invalid_dir_that_does_not_exist_12345",
            "settings.json",
        )
        repo = SettingsRepository(bad_path)

        with pytest.raises(OSError):
            repo.save({"key": "value"})

    def test_save_non_serializable_value(self, repo: SettingsRepository
                                         ) -> None:
        """Given 包含不可序列化类型的设置字典
           When  save()
           Then  抛出 TypeError。"""

        class Unserializable:
            pass

        with pytest.raises(TypeError):
            repo.save({"key": Unserializable()})

    def test_save_empty_dict(self, repo: SettingsRepository) -> None:
        """Given 空设置字典
           When  save()
           Then  写入空 JSON 对象 {}。"""
        repo.save({})

        with open(repo.file_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        assert content == "{}"

    def test_save_none_value(self, repo: SettingsRepository) -> None:
        """Given 包含 None 值的设置字典
           When  save()
           Then  None 被序列化为 null。"""
        repo.save({"key": None})

        with open(repo.file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data == {"key": None}


# ── atomic_save() — 正常路径 ─────────────────────────────────────────


class TestAtomicSave:
    """atomic_save() 方法测试：原子性写入 JSON 文件。"""

    def test_atomic_save_creates_file(self, repo: SettingsRepository,
                                      sample_settings: dict) -> None:
        """Given 一个设置字典
           When  atomic_save()
           Then  文件被创建且内容正确。"""
        repo.atomic_save(sample_settings)

        assert os.path.exists(repo.file_path)
        with open(repo.file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data == sample_settings

    def test_atomic_save_produces_indented_json(
        self, repo: SettingsRepository, sample_settings: dict
    ) -> None:
        """Given 一个设置字典
           When  atomic_save()
           Then  生成的 JSON 包含缩进。"""
        repo.atomic_save(sample_settings)

        with open(repo.file_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "    " in content

    def test_atomic_save_no_temp_file_left(self, repo: SettingsRepository,
                                           sample_settings: dict) -> None:
        """Given 一个设置字典
           When  atomic_save() 成功完成
           Then  没有 .tmp 残留文件。"""
        repo.atomic_save(sample_settings)

        tmp_files = [f for f in os.listdir(os.path.dirname(repo.file_path))
                     if f.endswith(".tmp")]
        assert len(tmp_files) == 0

    def test_atomic_save_overwrites_atomically(
        self, repo: SettingsRepository
    ) -> None:
        """Given 一个已有内容的文件
           When  atomic_save()
           Then  文件被完全替换，无中间状态。"""
        with open(repo.file_path, "w", encoding="utf-8") as f:
            json.dump({"old": "data"}, f)

        repo.atomic_save({"new": "data"})

        with open(repo.file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data == {"new": "data"}

    def test_atomic_save_creates_parent_directory(self, tmp_path) -> None:
        """Given 一个深层嵌套的路径
           When  atomic_save()
           Then  自动创建父目录。"""
        nested_path = os.path.join(str(tmp_path), "x", "y", "z", "settings.json")
        repo = SettingsRepository(nested_path)
        repo.atomic_save({"key": "value"})

        assert os.path.exists(nested_path)
        with open(nested_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data == {"key": "value"}

    # ── atomic_save() — 错误路径 ────────────────────────────────────

    def test_atomic_save_non_serializable_value(
        self, repo: SettingsRepository
    ) -> None:
        """Given 包含不可序列化类型的设置字典
           When  atomic_save()
           Then  抛出 TypeError，且无 .tmp 残留。"""

        class Unserializable:
            pass

        with pytest.raises(TypeError):
            repo.atomic_save({"key": Unserializable()})

        tmp_files = [f for f in os.listdir(os.path.dirname(repo.file_path))
                     if f.endswith(".tmp")]
        assert len(tmp_files) == 0

    def test_atomic_save_temp_file_cleaned_on_error(
        self, repo: SettingsRepository
    ) -> None:
        """Given 一个会导致写入失败的场景
           When  atomic_save()
           Then  临时文件被清理。"""
        with pytest.raises(TypeError):
            repo.atomic_save({"key": object()})

        tmp_files = [f for f in os.listdir(os.path.dirname(repo.file_path))
                     if f.endswith(".tmp")]
        assert len(tmp_files) == 0


# ── 路径与默认值 ──────────────────────────────────────────────────────


class TestPathResolution:
    """SettingsRepository 路径相关行为测试。"""

    def test_default_path_is_absolute(self) -> None:
        """Given 默认路径
           Then  路径以 data/settings.json 结尾且为绝对路径。"""
        repo = SettingsRepository()

        path = repo.file_path
        assert path.endswith("data\\settings.json") or path.endswith("data/settings.json")
        assert os.path.isabs(path)

    def test_custom_path(self, tmp_path) -> None:
        """Given 自定义文件路径
           Then  file_path 返回该路径。"""
        custom = os.path.join(str(tmp_path), "custom.json")
        repo = SettingsRepository(custom)

        assert repo.file_path == custom

    def test_custom_path_none_uses_default(self) -> None:
        """Given file_path=None
           Then  使用默认的 data/settings.json 路径。"""
        repo_default = SettingsRepository()
        repo_explicit_none = SettingsRepository(None)

        assert repo_explicit_none.file_path == repo_default.file_path

    def test_file_path_property(self, tmp_path) -> None:
        """Given SettingsRepository 实例
           When  访问 file_path 属性
           Then  返回构造函数传入的路径。"""
        custom = os.path.join(str(tmp_path), "my_settings.json")
        repo = SettingsRepository(custom)

        assert repo.file_path == custom
