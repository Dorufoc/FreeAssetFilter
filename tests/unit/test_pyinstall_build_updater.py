# -*- coding: utf-8 -*-
"""Pyinstall_build 的 faf_updater 打包接线与验证契约。

覆盖：
- ``collect_binaries`` 的 ``required`` 仍为 3 元组、返回仍为 2 元组且包含更新器；
- ``verify_output`` 的 ``faf_updater.exe`` 必需资源分支与 ``dist_root`` 参数；
- ``main`` 在 ``--skip-build`` 与正常路径上验证失败时均返回 1。
"""

from __future__ import annotations

import ast
from pathlib import Path
import sys

import pytest

import Pyinstall_build as pb


UPDATER_RESOURCE = "freeassetfilter/core/native/bin/faf_updater.exe"


def _prepare_dist(root: Path, *, with_updater: bool) -> None:
    """构造最小发布目录，仅保留关键文件与可选更新器。"""
    (root / f"{pb.PROJECT_NAME}.exe").write_bytes(b"MZ")
    internal = root / "_internal"
    internal.mkdir(parents=True)
    (internal / "FAFVERSION").write_text(
        "v1.0.0-alpha.5\n2026-05-22\n",
        encoding="utf-8",
    )
    if with_updater:
        updater = internal / UPDATER_RESOURCE
        updater.parent.mkdir(parents=True)
        updater.write_bytes(b"MZ")


def _collect_required_tuple() -> ast.Tuple:
    """返回 ``collect_binaries`` 内 ``required`` 的 AST 元组节点。"""
    tree = ast.parse(Path(pb.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "collect_binaries":
            for statement in node.body:
                if (
                    isinstance(statement, ast.Assign)
                    and len(statement.targets) == 1
                    and isinstance(statement.targets[0], ast.Name)
                    and statement.targets[0].id == "required"
                    and isinstance(statement.value, ast.Tuple)
                ):
                    return statement.value
    raise AssertionError("collect_binaries 中未找到 required 元组")


def test_required_entries_are_three_tuples_and_include_updater() -> None:
    """required 保持 3 元组，并登记 faf_updater.exe。"""
    required = _collect_required_tuple()
    assert required.elts, "required 不应为空"
    assert all(
        isinstance(element, ast.Tuple) and len(element.elts) == 3
        for element in required.elts
    )
    named_entries = {
        element.elts[0].value: element
        for element in required.elts
        if isinstance(element.elts[0], ast.Constant)
    }
    assert "faf_updater.exe" in named_entries
    destination = named_entries["faf_updater.exe"].elts[2]
    assert isinstance(destination, ast.Constant)
    assert destination.value == "freeassetfilter/core/native/bin"


def test_collect_binaries_returns_two_tuples_with_updater() -> None:
    """实际收集结果仍为 2 元组，且包含更新器源路径。"""
    binaries = pb.collect_binaries()
    assert binaries
    assert all(isinstance(item, tuple) and len(item) == 2 for item in binaries)
    assert any(
        Path(source).name == "faf_updater.exe"
        and destination == "freeassetfilter/core/native/bin"
        for source, destination in binaries
    )


def test_verify_output_accepts_dist_root_and_requires_updater(tmp_path: Path) -> None:
    """dist_root 命中临时目录；缺少更新器时返回 False。"""
    _prepare_dist(tmp_path, with_updater=True)
    assert pb.verify_output(dist_root=tmp_path) is True

    (tmp_path / "_internal" / UPDATER_RESOURCE).unlink()
    assert pb.verify_output(dist_root=tmp_path) is False


def test_verify_output_missing_optional_resource_is_only_warning(
    tmp_path: Path,
) -> None:
    """更新器存在时，其它资源缺失不影响验证结果。"""
    _prepare_dist(tmp_path, with_updater=True)
    # 未创建 color_schemes.json / libmpv 等可选资源，仍应通过。
    assert pb.verify_output(dist_root=tmp_path) is True


def test_main_skip_build_returns_one_on_verification_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--skip-build 路径把验证失败传播为退出码 1。"""
    monkeypatch.setattr(sys, "argv", ["Pyinstall_build.py", "--skip-build", "--no-clean"])
    monkeypatch.setattr(pb, "verify_output", lambda: False)
    monkeypatch.setattr(pb, "analyze_output_size", lambda: None)
    assert pb.main() == 1


def test_main_normal_path_returns_one_on_verification_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """正常打包路径同样在验证失败时返回 1。"""
    monkeypatch.setattr(sys, "argv", ["Pyinstall_build.py", "--no-clean"])
    monkeypatch.setattr(pb, "clean_build", lambda: None)
    monkeypatch.setattr(pb, "check_virtual_env", lambda: True)
    monkeypatch.setattr(pb, "check_pyinstaller", lambda: True)
    monkeypatch.setattr(pb, "collect_data_files", lambda: [])
    monkeypatch.setattr(pb, "collect_binaries", lambda: [])
    monkeypatch.setattr(pb, "collect_hidden_imports", lambda: [])
    monkeypatch.setattr(pb, "build_pyinstaller_command", lambda *args: [])
    monkeypatch.setattr(pb, "run_pyinstaller_build", lambda cmd: True)
    monkeypatch.setattr(pb, "clean_qt6_dlls", lambda: (0, 0))
    monkeypatch.setattr(pb, "clean_native_sources_from_dist", lambda: None)
    monkeypatch.setattr(pb, "verify_output", lambda: False)
    monkeypatch.setattr(pb, "generate_report", lambda *args: None)
    assert pb.main() == 1
