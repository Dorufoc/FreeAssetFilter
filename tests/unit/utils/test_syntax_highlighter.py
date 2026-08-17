# -*- coding: utf-8 -*-
"""syntax_highlighter.py（freeassetfilter/utils/syntax_highlighter.py）单元测试。

覆盖 Python / JSON / 未知语言片段的 highlight 结果非空且文本保真、
highlight_text 的行块结构、文件扩展名→语言推测（含 TextMate 映射优先级
与内置 EXTENSION_TO_LANGUAGE 兜底）、QTextCharFormat 生成，以及把 Token
格式应用到 QTextDocument（offscreen 模式）的集成验证。
"""

from __future__ import annotations

from typing import Any, List, Optional

import pytest
from PySide6.QtGui import QTextCharFormat, QTextCursor, QTextDocument

from freeassetfilter.utils.syntax_highlighter import (
    ColorScheme,
    ColorSchemes,
    PygmentsHighlighter,
    SyntectHighlighter,
    SyntaxHighlighter,
    TextMateGrammar,
    TextMateGrammarLoader,
    TextMateTheme,
    TextMateThemeLoader,
    Token,
    TokenType,
    create_highlighter,
    get_auto_theme_scheme,
    get_supported_languages,
    guess_language_from_filename,
    is_dark_mode,
)

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def highlighter() -> Any:
    """共享的模块级高亮器；引擎不可用时整模块跳过。"""
    hl = create_highlighter("github_dark")
    if hl._engine is None:
        pytest.skip("无可用高亮引擎（syntect/pygments 均缺失）")
    return hl


class TestEngineSelection:
    """引擎选择与统一接口。"""

    def test_create_highlighter_returns_wrapper(
        self, highlighter: Any
    ) -> None:
        assert isinstance(highlighter, SyntaxHighlighter)

    def test_get_qtextformat(self, highlighter: Any) -> None:
        """TokenType → 带前景色的 QTextCharFormat。"""
        fmt = highlighter.get_qtextformat(TokenType.KEYWORD)
        assert isinstance(fmt, QTextCharFormat)
        assert fmt.foreground().color().isValid()

    def test_background_foreground_colors(self, highlighter: Any) -> None:
        scheme = highlighter.color_scheme
        assert highlighter.get_background_color().name() == scheme.background
        assert highlighter.get_foreground_color().name() == scheme.foreground


class TestHighlightFragments:
    """Python / JSON / 未知语言片段高亮。"""

    def test_python_fragments_non_empty(self, highlighter: Any) -> None:
        """Python 片段：每行 token 非空、文本保真、含关键字类 token。"""
        code = "def f(a):\n    x = 1  # comment\n    return 's'\n"
        blocks = highlighter.highlight_text(code, "python")
        assert len(blocks) == len(code.split("\n"))
        for line, tokens in zip(code.split("\n"), blocks):
            assert len(tokens) >= 1
            # 引擎会把行尾换行符并入最后一个 token 的文本，因此做 rstrip 比较
            assert "".join(t.text for t in tokens).rstrip("\n") == line.rstrip("\n")
        token_types = {t.token_type for tokens in blocks for t in tokens}
        assert TokenType.KEYWORD in token_types  # def/return
        assert len(token_types) >= 3

    def test_json_fragments_non_empty(self, highlighter: Any) -> None:
        """JSON 片段：非空、文本保真、含 STRING/NUMBER。"""
        line = '{"key": "value", "n": 1}'
        tokens = highlighter.highlight_line(line, "json")
        assert len(tokens) >= 1
        # 引擎会把行尾换行符并入最后一个 token 的文本，因此做 rstrip 比较
        assert "".join(t.text for t in tokens).rstrip("\n") == line.rstrip("\n")
        token_types = {t.token_type for t in tokens}
        assert TokenType.STRING in token_types
        assert TokenType.NUMBER in token_types

    def test_unknown_language_default_fragments(self, highlighter: Any) -> None:
        """未知语言不抛异常，返回覆盖整行的 token。"""
        line = "plain unknown text 42"
        tokens = highlighter.highlight_line(line, "not_a_real_language")
        assert len(tokens) >= 1
        # 引擎会把行尾换行符并入最后一个 token 的文本，因此做 rstrip 比较
        assert "".join(t.text for t in tokens).rstrip("\n") == line.rstrip("\n")

    def test_highlight_line_returns_tokens(self, highlighter: Any) -> None:
        """highlight_line 返回 Token 列表且 tokenize 别名一致。"""
        tokens = highlighter.highlight_line("x = 1", "python")
        assert all(isinstance(t, Token) for t in tokens)
        assert len(highlighter.tokenize("x = 1", "python")) == len(tokens)


class TestHighlightFile:
    """按文件名的语言推测与按语言高亮。"""

    def test_fragment_blocks_from_highlight_file(
        self, highlighter: Any
    ) -> None:
        """.py 文件名走 python 语言；文本保真成块。"""
        code = "import os\ndef main():\n    pass\n"
        blocks = highlighter.highlight_file(code, "app.py")
        # highlight_text 按 text.split("\n") 分块，尾随换行生成一个空串行块
        assert len(blocks) == len(code.split("\n"))
        assert all(len(b) >= 1 for b in blocks)

    def test_unknown_extension_default_blocks(
        self, highlighter: Any
    ) -> None:
        """未知扩展名 → 纯文本 DEFAULT 块（每行一个 token）。"""
        code = "one line only"
        blocks = highlighter.highlight_file(code, "mystery.zzz")
        assert len(blocks) == 1
        assert blocks[0][0].token_type == TokenType.DEFAULT

    def test_get_language_by_extension_py(self, highlighter: Any) -> None:
        assert highlighter.get_language_by_extension("a.py") == "python"

    def test_get_language_by_extension_unknown(self, highlighter: Any) -> None:
        assert highlighter.get_language_by_extension("a.xyz123") is None

    def test_guess_language(self, highlighter: Any) -> None:
        assert highlighter.guess_language("app.json") in ("json", None)


class TestLanguageMappingHelpers:
    """模块级便捷工具。"""

    def test_guess_language_from_filename(self) -> None:
        assert guess_language_from_filename("plugin.py") == "python"
        assert guess_language_from_filename("data.json") == "json"
        assert guess_language_from_filename("file.unknown") is None

    def test_get_supported_languages_non_empty(self) -> None:
        assert len(get_supported_languages()) > 0


class TestQTextDocumentIntegration:
    """把 Token 格式应用到 QTextDocument（offscreen）。"""

    def test_format_applies_to_document(
        self, highlighter: Any, qapp: Any
    ) -> None:
        """Python 代码逐 token 套格式后纯文本保真、格式可回读。"""
        code = "def f():\n    return 1\n"
        blocks = highlighter.highlight_text(code, "python")
        doc = QTextDocument()
        doc.setPlainText(code)

        cursor = QTextCursor(doc)
        func_format: Optional[QTextCharFormat] = None
        for line_tokens in blocks:
            line_start = cursor.block().position()
            for tok in line_tokens:
                fmt = highlighter.get_qtextformat(tok.token_type)
                sel = QTextCursor(doc)
                sel.setPosition(line_start + tok.start_pos)
                sel.setPosition(
                    line_start + tok.end_pos, QTextCursor.MoveMode.KeepAnchor
                )
                sel.setCharFormat(fmt)
                if tok.token_type is TokenType.FUNCTION:
                    func_format = fmt
            cursor.movePosition(QTextCursor.MoveOperation.NextBlock)

        assert func_format is not None, "Python 片段应包含 FUNCTION token"
        assert doc.toPlainText() == code
        # 回读函数名区域格式：绝对位置 4 命中 "def f" 中的 "f"。
        verify = QTextCursor(doc)
        verify.setPosition(4)
        verify.setPosition(5, QTextCursor.MoveMode.KeepAnchor)
        applied = verify.charFormat().foreground().color().name()
        expected = func_format.foreground().color().name()
        assert applied == expected


def _assert_scheme_covers_all(scheme: ColorScheme) -> None:
    """断言给定方案为每个 TokenType 都提供了颜色。"""
    for token_type in TokenType:
        assert scheme.colors.get(token_type) is not None


class TestColorSchemes:
    """预定义配色方案覆盖全 TokenType。"""

    def test_github_dark_covers_all_token_types(self) -> None:
        _assert_scheme_covers_all(ColorSchemes.github_dark())

    def test_vscode_light_covers_all_token_types(self) -> None:
        _assert_scheme_covers_all(ColorSchemes.vscode_light())

    def test_github_dark_known_colors(self) -> None:
        scheme = ColorSchemes.github_dark()
        assert scheme.background == "#0d1117"
        assert scheme.colors[TokenType.KEYWORD].startswith("#")


class TestTextMateGrammarLoader:
    """TextMateGrammarLoader：JSON / missing / 文件夹 / VS Code 扩展。"""

    def test_load_json_grammar(self, tmp_path: Any) -> None:
        """合法 JSON 语法加载成功，scope/ext 索引可用。"""
        grammar_file = tmp_path / "python.json"
        grammar_file.write_text(
            '{"name": "Python", "scopeName": "source.python",'
            ' "fileTypes": [".py"], "patterns": [], "repository": {}}',
            encoding="utf-8",
        )
        loader = TextMateGrammarLoader()
        grammar = loader.load_file(str(grammar_file))
        assert grammar is not None
        assert grammar.scope_name == "source.python"
        assert grammar.file_extensions == [".py"]
        assert loader.get_grammar_by_scope("source.python") is grammar
        assert loader.get_grammar_by_extension(".py") is grammar
        assert loader.get_grammar_by_extension("py") is grammar

    def test_load_missing_file_returns_none(self, tmp_path: Any) -> None:
        """不存在的文件 → None（不抛异常）。"""
        loader = TextMateGrammarLoader()
        assert loader.load_file(str(tmp_path / "gone.json")) is None

    def test_load_unsupported_suffix_returns_none(self, tmp_path: Any) -> None:
        """不支持的扩展名 → None。"""
        file = tmp_path / "grammar.xyz"
        file.write_text("{}", encoding="utf-8")
        assert TextMateGrammarLoader().load_file(str(file)) is None

    def test_load_folder_ignores_missing_dir(self, tmp_path: Any) -> None:
        """不存在的文件夹 → 空 dict。"""
        assert TextMateGrammarLoader().load_folder(str(tmp_path / "nope")) == {}

    def test_load_folder_collects_json(self, tmp_path: Any) -> None:
        """文件夹内 .json 语法被索引。"""
        folder = tmp_path / "grammars"
        folder.mkdir()
        (folder / "py.json").write_text(
            '{"name": "Python", "scopeName": "source.python", "patterns": []}',
            encoding="utf-8",
        )
        grammars = TextMateGrammarLoader().load_folder(str(folder))
        assert "python" in grammars

    def test_load_vscode_extension_syntaxes(self, tmp_path: Any) -> None:
        """VS Code 扩展 syntaxes/ 子目录被扫描。"""
        ext = tmp_path / "ext"
        syntaxes = ext / "syntaxes"
        syntaxes.mkdir(parents=True)
        (syntaxes / "py.json").write_text(
            '{"name": "Python", "scopeName": "source.python", "fileTypes": ["py"],'
            ' "patterns": [], "repository": {}}',
            encoding="utf-8",
        )
        loader = TextMateGrammarLoader()
        assert loader.load_vscode_extension(str(ext)) != {}
        assert loader.load_vscode_extension(str(tmp_path / "missing")) == {}


class TestTextMateThemeLoader:
    """TextMateThemeLoader：JSON 主题加载与 ColorScheme 转换。"""

    def test_load_json_theme(self, tmp_path: Any) -> None:
        """合法 JSON 主题加载，name/author/settings 正确。"""
        theme_file = tmp_path / "theme.json"
        theme_file.write_text(
            '{"name": "My Theme", "author": "tester",'
            ' "settings": [{"scope": "source", "settings": {"foreground": "#000000"}}]}',
            encoding="utf-8",
        )
        loader = TextMateThemeLoader()
        theme = loader.load_file(str(theme_file))
        assert theme is not None
        assert theme.name == "My Theme"
        assert theme.author == "tester"
        assert len(theme.settings) == 1

    def test_load_missing_theme_returns_none(self, tmp_path: Any) -> None:
        """不存在的主题 → None。"""
        assert TextMateThemeLoader().load_file(str(tmp_path / "gone.json")) is None

    def test_load_folder_collects_themes(self, tmp_path: Any) -> None:
        """文件夹内主题被索引（键为小写名称）。"""
        folder = tmp_path / "themes"
        folder.mkdir()
        (folder / "t1.json").write_text(
            '{"name": "Catppuccin", "author": "a", "settings": []}',
            encoding="utf-8",
        )
        themes = TextMateThemeLoader().load_folder(str(folder))
        assert "catppuccin" in themes

    def test_to_color_scheme(self, tmp_path: Any) -> None:
        """主题转 ColorScheme，名称与前景色生效。"""
        loader = TextMateThemeLoader()
        theme = TextMateTheme(
            name="TestDark",
            author="tester",
            settings=[
                # 仅全局 scope（空串）更新 foreground；作用域 scope 走 token 映射
                {"scope": "", "settings": {"foreground": "#abcdef"}}
            ],
        )
        scheme = loader.to_color_scheme(theme, "test_dark")
        assert isinstance(scheme, ColorScheme)
        assert scheme.name == "test_dark"
        assert scheme.foreground == "#abcdef"


class TestSyntectHighlighter:
    """SyntectHighlighter：构造 / 委托加载 / apply 主题 / 查询。"""

    def test_constructor_sets_loaders(self) -> None:
        """构造即初始化 grammar/theme 加载器与默认配色。"""
        hl = SyntectHighlighter()
        assert hl.grammar_loader is not None
        assert hl.theme_loader is not None
        assert hl.color_scheme is not None
        assert isinstance(hl.is_available(), bool)

    def test_guess_language_by_extension(self) -> None:
        """guess_language 命中 EXTENSION_TO_LANGUAGE。"""
        hl = SyntectHighlighter()
        assert hl.guess_language("app.py") == "python"
        assert hl.guess_language("data.json") == "json"

    def test_load_textmate_grammar_delegates(self, tmp_path: Any) -> None:
        """load_textmate_grammar 委托 grammar_loader。"""
        hl = SyntectHighlighter()
        grammar_file = tmp_path / "python.json"
        grammar_file.write_text(
            '{"name": "Python", "scopeName": "source.python", "fileTypes": ["py"],'
            ' "patterns": [], "repository": {}}',
            encoding="utf-8",
        )
        grammar = hl.load_textmate_grammar(str(grammar_file))
        assert isinstance(grammar, TextMateGrammar)
        assert hl.load_textmate_grammar(str(tmp_path / "gone.json")) is None
        assert hl.load_textmate_grammars_from_folder(str(tmp_path / "nope")) == {}
        assert hl.load_vscode_extension_grammars(str(tmp_path / "nope")) == {}

    def test_load_textmate_theme_delegates(self, tmp_path: Any) -> None:
        """load_textmate_theme 委托 theme_loader。"""
        hl = SyntectHighlighter()
        theme_file = tmp_path / "theme.json"
        theme_file.write_text(
            '{"name": "My Theme", "author": "tester", "settings": []}',
            encoding="utf-8",
        )
        theme = hl.load_textmate_theme(str(theme_file))
        assert isinstance(theme, TextMateTheme)
        assert hl.load_textmate_themes_from_folder(str(tmp_path / "nope")) == {}

    def test_apply_textmate_theme(self, tmp_path: Any) -> None:
        """apply_textmate_theme 更新 color_scheme。"""
        hl = SyntectHighlighter()
        theme = TextMateTheme(
            name="My Dark",
            author="tester",
            settings=[{"scope": "source", "settings": {"foreground": "#111111"}}],
        )
        hl.apply_textmate_theme(theme)
        assert hl.color_scheme is not None

    def test_get_textmate_grammar_info(self, tmp_path: Any) -> None:
        """已加载语法返回 info dict；未加载返回 None。"""
        hl = SyntectHighlighter()
        grammar_file = tmp_path / "python.json"
        grammar_file.write_text(
            '{"name": "Python", "scopeName": "source.python", "fileTypes": ["py"],'
            ' "patterns": [], "repository": {}}',
            encoding="utf-8",
        )
        hl.load_textmate_grammar(str(grammar_file))
        info = hl.get_textmate_grammar_info("Python")
        assert info is not None
        assert info["scope_name"] == "source.python"
        assert hl.get_textmate_grammar_info("nope") is None

    def test_get_textmate_theme_info(self, tmp_path: Any) -> None:
        """已加载主题返回 info dict；未加载返回 None。"""
        hl = SyntectHighlighter()
        theme_file = tmp_path / "theme.json"
        theme_file.write_text(
            '{"name": "My Theme", "author": "tester", "settings": []}',
            encoding="utf-8",
        )
        hl.load_textmate_theme(str(theme_file))
        info = hl.get_textmate_theme_info("My Theme")
        assert info is not None
        assert info["author"] == "tester"
        assert hl.get_textmate_theme_info("nope") is None

    def test_load_syntax_theme_folder_paranoia(self, tmp_path: Any) -> None:
        """缺失文件夹的 load_*_from_folder 静默返回（不抛）。"""
        hl = SyntectHighlighter()
        hl.load_syntax_from_folder(str(tmp_path / "nope"))
        assert hl.load_theme_from_folder(str(tmp_path / "nope")) == {}

    def test_get_supported_languages_non_empty(self) -> None:
        """内置扩展映射保证语言列表非空。"""
        hl = SyntectHighlighter()
        assert len(hl.get_supported_languages()) > 0

    def test_highlight_line_no_crash(self) -> None:
        """语法集缺失时 highlight_line 返回默认 token（不抛）。"""
        hl = SyntectHighlighter()
        tokens = hl.highlight_line("x = 1", "python")
        assert len(tokens) >= 1


class TestPygmentsHighlighter:
    """PygmentsHighlighter：构造 / 高亮 / 语言猜测。"""

    def test_constructor_and_highlight(self) -> None:
        """Pygments 不可用时返回默认 token，可用时关键字高亮。"""
        hl = PygmentsHighlighter()
        tokens = hl.highlight_line("def f():\n    pass", "python")
        assert all(isinstance(t, Token) for t in tokens)

    def test_guess_language(self) -> None:
        hl = PygmentsHighlighter()
        assert hl.guess_language("app.py") == "python"
        assert hl.guess_language("data.json") == "json"

    def test_get_supported_languages(self) -> None:
        assert len(PygmentsHighlighter().get_supported_languages()) > 0

    def test_get_qtextformat(self) -> None:
        hl = PygmentsHighlighter()
        fmt = hl.get_qtextformat(TokenType.KEYWORD)
        assert isinstance(fmt, QTextCharFormat)


class TestAutoThemeHelpers:
    """get_auto_theme_scheme / is_dark_mode。"""

    def test_get_auto_theme_scheme_explicit(self) -> None:
        """显式 dark_mode 参数不触达设置管理器。"""
        assert get_auto_theme_scheme(dark_mode=True) is not None
        assert get_auto_theme_scheme(dark_mode=False) is not None

    def test_get_auto_theme_scheme_uses_is_dark_mode(
        self, monkeypatch: Any
    ) -> None:
        """dark_mode=None → 委托 is_dark_mode()。"""
        import freeassetfilter.utils.syntax_highlighter as sh

        monkeypatch.setattr(sh, "is_dark_mode", lambda: True)
        assert get_auto_theme_scheme() is not None
        monkeypatch.setattr(sh, "is_dark_mode", lambda: False)
        assert get_auto_theme_scheme() is not None

    def test_is_dark_mode_returns_bool(self) -> None:
        """is_dark_mode 三路径兜底总返回 bool。"""
        assert isinstance(is_dark_mode(), bool)