"""``sopeek._import_compat``：短路径与规范路径必须收敛到同一模块对象。

这是本项目最容易“静默坏掉”的机制：两条导入路径各执行一次会让
``theme.tm`` 变成两个不同单例，界面配色随之分裂。
"""

from __future__ import annotations

import importlib
import sys

import pytest


pytestmark = pytest.mark.unit


def test_install_is_idempotent() -> None:
    """重复调用不叠加 finder（``sopeek/__init__.py`` 可能被多次初始化）。"""
    import sopeek._import_compat as compat

    before = [f for f in sys.meta_path if type(f).__name__ == "_ShortPathAliasFinder"]
    compat.install()
    compat.install()
    after = [f for f in sys.meta_path if type(f).__name__ == "_ShortPathAliasFinder"]
    assert len(after) == len(before) == 1


@pytest.mark.parametrize(
    ("short_name", "canonical_name"),
    [
        ("theme", "sopeek.ui.theme"),
        ("components", "sopeek.ui.components"),
    ],
)
def test_short_and_canonical_names_share_one_module(short_name: str, canonical_name: str) -> None:
    short = importlib.import_module(short_name)
    canonical = importlib.import_module(canonical_name)
    assert short is canonical


def test_short_path_submodule_shares_object() -> None:
    """子模块（``theme.theme_manager`` ↔ ``sopeek.ui.theme.theme_manager``）同样收敛。"""
    short = importlib.import_module("theme.theme_manager")
    canonical = importlib.import_module("sopeek.ui.theme.theme_manager")
    assert short is canonical


def test_theme_singleton_is_unique() -> None:
    """短名与规范名取到的 ``tm`` 必须是同一个对象。"""
    from sopeek.ui import theme as canonical_theme
    from theme import tm as short_tm

    assert short_tm is canonical_theme.tm


def test_unknown_top_level_name_is_not_intercepted() -> None:
    """finder 只处理两对别名，其它名称照常抛 ``ModuleNotFoundError``。"""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("definitely_not_a_sopeek_alias")
