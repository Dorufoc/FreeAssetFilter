# -*- coding: utf-8 -*-
"""syntax_highlighter.py（freeassetfilter/utils/syntax_highlighter.py）单元测试。

覆盖 Python / JSON / 未知语言片段的 highlight 结果非空且文本保真、
highlight_text 的行块结构、文件扩展名→语言推测（含 TextMate 映射优先级
与内置 EXTENSION_TO_LANGUAGE 兜底）、QTextCharFormat 生成，以及把 Token
格式应用到 QTextDocument（offscreen 模式）的集成验证。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional

import pytest
from PySide6.QtGui import QTextCharFormat, QTextCursor, QTextDocument

from freeassetfilter.utils.syntax_highlighter import (
    ColorScheme,
    ColorSchemes,
    FafCoreHighlighter,
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
    faf_core_highlight_available,
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


class _FakeBridge:
    """最小 fake faf_core 桥：按需返回预置 span / None。"""

    def __init__(self, spans: Optional[List[Any]] = None,
                 result: Optional[Any] = None) -> None:
        self._spans = spans
        self._result = result

    def highlight_text(self, language: str, text: str) -> Optional[list]:  # noqa: ARG002
        if self._result is not None:
            return self._result
        return self._spans


class TestFafCoreEngineSelection:
    """FafCoreHighlighter 引擎优先级与回退（todo 13）。"""

    def test_auto_selects_fafcore_when_available(
        self, monkeypatch: Any
    ) -> None:
        """faf_core 可用 → auto 引擎选中 FafCoreHighlighter（最高优先级）。"""
        import freeassetfilter.utils.syntax_highlighter as sh

        monkeypatch.setattr(sh, "faf_core_highlight_available", lambda: True)
        hl = SyntaxHighlighter(ColorSchemes.github_dark())
        assert isinstance(hl._engine, FafCoreHighlighter)  # noqa: SLF001

    def test_auto_falls_back_to_pygments_when_unavailable(
        self, monkeypatch: Any
    ) -> None:
        """faf_core 不可用 → auto 引擎回退 PygmentsHighlighter。"""
        import freeassetfilter.utils.syntax_highlighter as sh

        monkeypatch.setattr(sh, "faf_core_highlight_available", lambda: False)
        hl = SyntaxHighlighter(ColorSchemes.github_dark())
        assert isinstance(hl._engine, PygmentsHighlighter)  # noqa: SLF001

    def test_auto_uses_real_dll_when_present(self) -> None:
        """真实环境：DLL 存在 → FafCore；否则回退（恒拿到引擎不崩）。"""
        import freeassetfilter.utils.syntax_highlighter as sh

        hl = SyntaxHighlighter(ColorSchemes.github_dark())
        assert hl._engine is not None  # noqa: SLF001
        if sh.faf_core_highlight_available():
            assert isinstance(hl._engine, FafCoreHighlighter)  # noqa: SLF001

    def test_explicit_pygments_overrides(self) -> None:
        """显式 'pygments' 请求 → Pygments（不理会 auto 优先级）。"""
        hl = SyntaxHighlighter(ColorSchemes.github_dark(), engine="pygments")
        assert isinstance(hl._engine, PygmentsHighlighter)  # noqa: SLF001


class TestFafCoreHighlighter:
    """FafCoreHighlighter：tokenize / highlight_line / highlight_text 结构与回退。"""

    FAF_PY_LINE_SPANS = [
        {"start": 0, "len": 1, "token_type": 15},   # DEFAULT 'x'
        {"start": 1, "len": 1, "token_type": 16},   # WHITESPACE ' '
        {"start": 2, "len": 1, "token_type": 7},    # OPERATOR '='
        {"start": 3, "len": 1, "token_type": 16},   # WHITESPACE ' '
        {"start": 4, "len": 1, "token_type": 3},    # NUMBER '1'
        {"start": 5, "len": 2, "token_type": 16},   # WHITESPACE '  '
        {"start": 7, "len": 1, "token_type": 4},    # COMMENT '#'
        {"start": 8, "len": 8, "token_type": 4},    # COMMENT ' comment'
    ]

    def _make(self, bridge: Optional[_FakeBridge] = None) -> FafCoreHighlighter:
        hl = FafCoreHighlighter()
        if bridge is not None:
            hl._bridge = bridge  # noqa: SLF001
        return hl

    def test_tokenize_structure_with_fake_bridge(self) -> None:
        """tokenize：text 拼接==原文、token_type 是枚举成员、字符偏移连续。"""
        line = "x = 1  # comment"
        bridge = _FakeBridge(spans=self.FAF_PY_LINE_SPANS)
        tokens = self._make(bridge).tokenize(line, "python")
        assert len(tokens) == len(self.FAF_PY_LINE_SPANS)
        assert all(isinstance(t, Token) for t in tokens)
        assert all(isinstance(t.token_type, TokenType) for t in tokens)
        assert "".join(t.text for t in tokens) == line
        assert tokens[0].start_pos == 0
        assert tokens[-1].end_pos == len(line)
        for prev, cur in zip(tokens, tokens[1:]):
            assert prev.end_pos == cur.start_pos, "span 应连续覆盖"
        assert tokens[2].token_type is TokenType.OPERATOR
        assert tokens[4].token_type is TokenType.NUMBER
        assert tokens[7].token_type is TokenType.COMMENT

    def test_tokenize_unknown_language_default_token(self) -> None:
        """native 空 span（未知语言）→ 单 DEFAULT token 覆盖整行。"""
        line = "plain unknown text 42"
        bridge = _FakeBridge(spans=[])
        tokens = self._make(bridge).tokenize(line, "not_a_real_language")
        assert len(tokens) == 1
        assert tokens[0].text == line
        assert tokens[0].token_type is TokenType.DEFAULT
        assert (tokens[0].start_pos, tokens[0].end_pos) == (0, len(line))

    def test_highlight_line_falls_back_on_native_none(self) -> None:
        """native 返回 None（-6 逐语言回退）→ Pygments 兜底不崩、文本保真。"""
        line = "$x = 1"
        bridge = _FakeBridge(result=None)
        tokens = self._make(bridge).highlight_line(line, "powershell")
        assert len(tokens) >= 1
        assert all(isinstance(t, Token) for t in tokens)
        assert "".join(t.text for t in tokens).rstrip("\n") == line.rstrip("\n")

    def test_highlight_text_slices_spans_to_lines(self) -> None:
        """整块高亮：跨 '\n' 的 span 被正确裁剪为每行 token 块。"""
        text = "abc\ndef()\n"
        # span0 覆盖 'abc\n'（含换行），span1/span2 覆盖第二行
        bridge = _FakeBridge(spans=[
            {"start": 0, "len": 4, "token_type": 15},  # DEFAULT 'abc\n'
            {"start": 4, "len": 3, "token_type": 5},   # FUNCTION 'def'
            {"start": 7, "len": 2, "token_type": 8},   # PUNCTUATION '()'
        ])
        blocks = self._make(bridge).highlight_text(text, "python")
        assert len(blocks) == 3  # '' 尾行：split('\n') 语义
        assert "".join(t.text for t in blocks[0]) == "abc"
        assert "".join(t.text for t in blocks[1]) == "def()"
        assert blocks[1][0].token_type is TokenType.FUNCTION
        # 行内字符偏移（不含换行符）
        t0, t1 = blocks[1]
        assert (t0.start_pos, t0.end_pos) == (0, 3)
        assert (t1.start_pos, t1.end_pos) == (3, 5)

    def test_get_qtextformat(self) -> None:
        """get_qtextformat 走 Python color_scheme 侧（theme 不跨界）。"""
        hl = self._make()
        fmt = hl.get_qtextformat(TokenType.KEYWORD)
        assert isinstance(fmt, QTextCharFormat)
        assert fmt.foreground().color().isValid()

    def test_real_bridge_happy_path(self) -> None:
        """真实桥可用时：tokenize 输出文本保真且含预期类型。"""
        hl = FafCoreHighlighter()
        if not faf_core_highlight_available():
            pytest.skip("faf_core.dll 不含 highlight 导出，跳过真实桥测试")
        line = "x = 1  # comment"
        tokens = hl.tokenize(line, "python")
        assert "".join(t.text for t in tokens) == line
        types = {t.token_type for t in tokens}
        assert TokenType.NUMBER in types
        assert TokenType.COMMENT in types


class TestFafCoreParity:
    """对拍：6 语言样本经 native 高亮的 token 文本拼接 == 原文 + 关键类型断言。

    样本取自 ``tests/support/faf_core_fixtures/code_samples/``，逐行校验
    ``"".join(t.text) == line``（字符偏移连续覆盖 [0, len(line)]）并断言各
    语言的关键 token 类型出现。**仅在 ``faf_core_available``（conftest
    session fixture）且 ``faf_core_highlight_available()``（DLL 含
    ``faf_highlight_text`` 导出）时启用，任一不可用即 skip**，保证无 DLL
    环境下回归不受影响。
    """

    SAMPLE_DIR = (
        Path(__file__).resolve().parents[2]
        / "support"
        / "faf_core_fixtures"
        / "code_samples"
    )

    # (样本文件, 应用语言名, 预期出现的关键类型)
    PARITY_CASES: List[tuple] = [
        (
            "sample_python.py",
            "python",
            {TokenType.KEYWORD, TokenType.STRING, TokenType.NUMBER, TokenType.COMMENT},
        ),
        (
            "sample_javascript.js",
            "javascript",
            {TokenType.KEYWORD, TokenType.STRING, TokenType.NUMBER, TokenType.COMMENT},
        ),
        (
            "sample_go.go",
            "go",
            {TokenType.KEYWORD, TokenType.STRING, TokenType.NUMBER, TokenType.COMMENT},
        ),
        (
            "sample_rust.rs",
            "rust",
            {TokenType.KEYWORD, TokenType.STRING, TokenType.NUMBER, TokenType.COMMENT},
        ),
        (
            "sample_config.json",
            "json",
            # syntect JSON 语法不产出 KEYWORD（键/值走 STRING/VALUE/NUMBER）
            {TokenType.STRING, TokenType.NUMBER, TokenType.COMMENT},
        ),
        (
            "sample_doc.md",
            "markdown",
            # syntect markdown 语法不产出代码类 token，仅校验文本保真
            set(),
        ),
    ]

    @pytest.fixture()
    def _native_parity_enabled(self, faf_core_available: bool) -> None:
        """native 不可用时跳过整个对拍测试。"""
        if not faf_core_available or not faf_core_highlight_available():
            pytest.skip(
                "faf_core 不可用（DLL 缺失或不含 highlight 导出），对拍测试跳过"
            )

    def _read_sample(self, fname: str) -> str:
        return (self.SAMPLE_DIR / fname).read_text(encoding="utf-8")

    @pytest.mark.parametrize(
        "fname,language,expected_types",
        PARITY_CASES,
        ids=[case[0] for case in PARITY_CASES],
    )
    def test_highlight_text_fidelity_and_types(
        self,
        _native_parity_enabled: None,
        fname: str,
        language: str,
        expected_types: set,
    ) -> None:
        """整块 native 高亮：逐行 token 拼接 == 原文（字符偏移）+ 关键类型。"""
        text = self._read_sample(fname)
        hl = FafCoreHighlighter()
        blocks = hl.highlight_text(text, language)
        lines = text.split("\n")
        assert len(blocks) == len(lines)

        for idx, (line, block) in enumerate(zip(lines, blocks)):
            if line == "":
                continue  # 空行：span 不覆盖，block 为空属预期
            assert block, f"{language} 第 {idx} 行不应为空 token 块"
            assert "".join(t.text for t in block) == line, (
                f"{language} 第 {idx} 行 token 拼接 != 原文"
            )
            # 行内字符偏移连续覆盖 [0, len(line)]
            assert block[0].start_pos == 0, f"{language} 第 {idx} 行首 token 起点"
            assert block[-1].end_pos == len(line), f"{language} 第 {idx} 行尾 token 终点"
            for prev, cur in zip(block, block[1:]):
                assert prev.end_pos == cur.start_pos, (
                    f"{language} 第 {idx} 行 span 不连续"
                )

        if expected_types:
            seen = {t.token_type for blk in blocks for t in blk}
            missing = expected_types - seen
            assert not missing, (
                f"{language} 缺失关键 token 类型: {sorted(m.name for m in missing)}"
            )

    @pytest.mark.parametrize(
        "fname,language,_expected_types",
        PARITY_CASES,
        ids=[case[0] for case in PARITY_CASES],
    )
    def test_highlight_line_fidelity(
        self,
        _native_parity_enabled: None,
        fname: str,
        language: str,
        _expected_types: set,
    ) -> None:
        """逐行 native 高亮（适配层 highlightBlock 同款路径）：文本保真。"""
        text = self._read_sample(fname)
        hl = FafCoreHighlighter()
        for idx, line in enumerate(text.split("\n")):
            tokens = hl.highlight_line(line, language)
            assert len(tokens) >= 1, f"{language} 第 {idx} 行应有 token"
            assert "".join(t.text for t in tokens).rstrip("\n") == line.rstrip("\n"), (
                f"{language} 第 {idx} 行逐行拼接 != 原文"
            )
            assert tokens[0].start_pos == 0
            assert tokens[-1].end_pos == len(line.rstrip("\n"))

    def test_create_highlighter_auto_routes_native(
        self, _native_parity_enabled: None
    ) -> None:
        """create_highlighter('auto') 选中 FafCoreHighlighter（预览器路由依据）。"""
        wrapper = create_highlighter("auto", dark_mode=True)
        assert isinstance(wrapper._engine, FafCoreHighlighter)  # noqa: SLF001


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