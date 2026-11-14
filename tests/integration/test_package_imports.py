"""全量导入集成测试：``src/sopeek`` 下每个模块都必须能被导入。

这是删除旧测试后最主要的回归网——重构造成的路径/依赖断裂会在这里暴露。
入口模块 ``sopeek.app.main`` 与原生构建脚本（``setup.py`` / ``build.py``）
跳过：前者在模块级解析命令行并安装进程级设施，后者导入即触发编译。
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "src" / "sopeek"

#: 导入即产生进程级副作用 / 触发原生构建的模块。
_SKIP = {"sopeek.app.main"}
_SKIP_PREFIXES = ("sopeek.core.native.bin.",)


def _module_names() -> list[str]:
    names: list[str] = []
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        parts = list(path.relative_to(PACKAGE_DIR.parent).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        name = ".".join(parts)
        if name in _SKIP or name.startswith(_SKIP_PREFIXES):
            continue
        names.append(name)
    return names


@pytest.mark.integration
@pytest.mark.parametrize("module_name", _module_names())
def test_module_imports(module_name: str) -> None:
    importlib.import_module(module_name)


@pytest.mark.integration
def test_every_python_package_dir_has_init() -> None:
    """含 ``.py`` 的子目录都必须是正规包（缺 ``__init__.py`` 会让打包漏文件）。

    纯数据目录（``resources/{icons,syntax,shaders,docs}``）不算包，无需
    ``__init__.py``。
    """
    #: 现存命名空间目录（无 ``__init__.py``）。它们同时被短路径
    #: （``layout.main_layout``）与规范路径（``sopeek.ui.layout.*``）导入；
    #: 补 ``__init__.py`` 只是把它们变成正规包，双份加载的风险要靠
    #: ``_import_compat`` 扩展别名才能消除——那是独立议题，此处只做登记，
    #: 不把重构范围扩大。新增目录仍必须带 ``__init__.py``。
    namespace_dirs = {"ui\\layout", "ui\\layout\\preview"}

    missing = [
        str(directory.relative_to(PACKAGE_DIR))
        for directory in PACKAGE_DIR.rglob("*")
        if directory.is_dir()
        and "__pycache__" not in directory.parts
        and any(directory.glob("*.py"))
        and str(directory.relative_to(PACKAGE_DIR)) not in namespace_dirs
        and not (directory / "__init__.py").is_file()
    ]
    assert missing == []


@pytest.mark.integration
def test_no_module_computes_repo_depth_arithmetic() -> None:
    """回归锁：禁止再出现 ``parents[3]`` 之类的层级算术（src 迁移的根因）。"""
    offenders: list[str] = []
    for path in PACKAGE_DIR.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for needle in ("parents[2]", "parents[3]", "parents[4]", "parents[5]"):
            if needle in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {needle}")
    assert offenders == [], "\n".join(offenders)
