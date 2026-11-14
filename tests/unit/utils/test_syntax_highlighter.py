"""``sopeek.utils.syntax_highlighter``：语言推断与高亮器工厂。"""

from __future__ import annotations


import pytest

from sopeek.utils import syntax_highlighter as sh


pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("filename", "language"),
    [
        ("a.py", "python"),
        ("A.PY", "python"),
        ("main.cpp", "cpp"),
        ("header.h", "c"),
        ("app.ts", "typescript"),
        ("lib.rs", "rust"),
        ("q.go", "go"),
    ],
)
def test_guess_language_from_filename(filename: str, language: str) -> None:
    assert sh.guess_language_from_filename(filename) == language


@pytest.mark.parametrize("filename", ["noext", "unknown.zzz", ""])
def test_guess_language_returns_none_for_unknown(filename: str) -> None:
    assert sh.guess_language_from_filename(filename) is None


def test_syntax_dir_contains_grammars() -> None:
    """随包语法目录必须存在且非空（重构把 ``utils/syntax`` 挪到了 resources）。"""
    from sopeek._paths import syntax_dir

    assert sh.SyntaxHighlighter.DEFAULT_SYNTAX_DIR == syntax_dir()
    assert syntax_dir().is_dir()
    assert list(syntax_dir().glob("*.json"))


def test_create_highlighter_returns_highlighter() -> None:
    highlighter = sh.create_highlighter("github_dark")
    assert highlighter is not None
    source = "def f():\n    return 1"
    lines = highlighter.highlight_text(source, "python")
    assert len(lines) == 2
    # 引擎（native/Pygments/syntect）对 "def" 归类不同，只要求首行非默认色。
    assert any(token.token_type is not sh.TokenType.DEFAULT for token in lines[0])


def test_supported_languages_is_non_empty() -> None:
    languages = sh.get_supported_languages()
    assert languages
    assert all(isinstance(name, str) and name for name in languages)


def test_auto_theme_scheme_matches_dark_flag() -> None:
    dark = sh.get_auto_theme_scheme(dark_mode=True)
    light = sh.get_auto_theme_scheme(dark_mode=False)
    assert dark is not light
    assert dark.background != light.background


def test_spk_core_highlight_availability_is_boolean() -> None:
    """原生高亮可用性探测不得抛异常（DLL 缺失时返回 False）。"""
    assert isinstance(sh.spk_core_highlight_available(), bool)


def test_token_types_are_stable_enum() -> None:
    """``TokenType`` 的成员是 native span 索引映射的锚点，不允许随意改名。"""
    names = {member.name for member in sh.TokenType}
    assert {"KEYWORD", "STRING", "COMMENT", "NUMBER"} <= names
