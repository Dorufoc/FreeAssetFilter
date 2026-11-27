"""``--open-path`` 参数解析的单元测试。

资源管理器右键菜单通过 ``--open-path`` 传入目标；安装器注册的命令行必须是
「文件→目录 + 定位文件」「目录→目录」，两个解析函数的分工在这里固化，避免
后续改动只导航不选中文件。
"""

from __future__ import annotations

import os

import pytest

from sopeek.app.main import _resolve_initial_locate_path, _resolve_initial_navigate_path

pytestmark = pytest.mark.unit


def _argv(path: str) -> list[str]:
    return ["Sopeek.exe", "--open-path", path]


def test_folder_argument_navigates_to_itself(tmp_path) -> None:
    """目录：导航路径就是目录本身，没有需要定位的文件。"""
    folder = tmp_path / "assets"
    folder.mkdir()

    assert _resolve_initial_navigate_path(_argv(str(folder))) == str(folder)
    assert _resolve_initial_locate_path(_argv(str(folder))) is None


def test_file_argument_navigates_to_parent_and_locates_file(tmp_path) -> None:
    """文件：导航到所在目录，同时把它交给文件选择器定位选中。"""
    target = tmp_path / "photo.png"
    target.write_bytes(b"x")

    assert _resolve_initial_navigate_path(_argv(str(target))) == str(tmp_path)
    assert _resolve_initial_locate_path(_argv(str(target))) == str(target)


def test_missing_argument_returns_none() -> None:
    """没有 --open-path（普通启动）时两个解析都返回 None。"""
    assert _resolve_initial_navigate_path(["Sopeek.exe"]) is None
    assert _resolve_initial_locate_path(["Sopeek.exe"]) is None


def test_trailing_flag_without_value_is_ignored() -> None:
    """--open-path 后没有值（异常调用）时不得抛 IndexError。"""
    assert _resolve_initial_navigate_path(["Sopeek.exe", "--open-path"]) is None
    assert _resolve_initial_locate_path(["Sopeek.exe", "--open-path"]) is None


def test_nonexistent_path_returns_none(tmp_path) -> None:
    """不存在的路径两者都不认（避免导航到不存在的目录而弹错）。"""
    ghost = os.path.join(str(tmp_path), "nope.bin")
    assert _resolve_initial_navigate_path(_argv(ghost)) is None
    assert _resolve_initial_locate_path(_argv(ghost)) is None
