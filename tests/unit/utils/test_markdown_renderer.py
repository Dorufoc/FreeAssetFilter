# -*- coding: utf-8 -*-
"""markdown_renderer.py（freeassetfilter/utils/markdown_renderer.py）单元测试。

覆盖标题（含 id 重写）、粗斜体、fenced code 代码块（Pygments 高亮 span）、
表格、任务列表（task-item / task-checkbox）、字号设置（含异常）与完整 HTML
文档结构；并验证渲染结果可注入 QTextDocument 且纯文本无损。

todo-17 新增 native 高优先级路径覆盖：faf_core 桥可用时 ``render()`` 走
原生引擎（strikethrough ``<del>``、代码块包装归一、md_in_html 标记剥离、
task-item 类吸收），并对核心元素做 normalize 结构等价对拍；桥不可用 /
降级时回退 python-markdown 现状路径。

todo-19 补完整 6 样本（``markdown_samples/``）两路径关键元素断言：除既有
normalize 结构对拍（01/03/05 EQUAL、02/04/06 引擎固有差异）外，另断言
每个样本的核心 HTML 元素 / ASCII 锚点在 native 与 python 两路径下都存在。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtGui import QTextDocument

from freeassetfilter.utils.markdown_renderer import (
    MARKDOWN_AVAILABLE,
    MarkdownRenderer,
)

pytestmark = pytest.mark.unit

_SAMPLE_DIR = (
    Path(__file__).resolve().parents[2]
    / "support"
    / "faf_core_fixtures"
    / "markdown_samples"
)

# 6 样本关键元素断言表（todo-19）：native 与 python-markdown 两路径渲染输出
# 都必须包含的核心 HTML 元素 / ASCII 锚点文本。样本源为 GBK 编码，测试按
# ``utf-8, errors="replace"`` 读入后中文为 U+FFFD，故断言只用 ASCII 结构 /
# 英文锚点（避免编码依赖）。04 代码样本用 token 级锚点（如 ``ANSWER``、
# ``fn``、``main``）：syntect 分词会过滤纯空白 span，源码 token 间空白在
# native 输出中丢失（todo-15 已接受的引擎固有差异），连续源码文本不可断言。
_SAMPLE_KEY_ELEMENTS: dict[str, list[str]] = {
    "01_headings_paragraphs.md": [
        "<h1", "<h2", "<h3", "<strong>", "<em>", "<code>",
        "Heading", "Sub", "Deep", "plain text ending.",
    ],
    "02_lists_tasks.md": [
        "<ul>", "<ol>", "<li>",
        'class="task-item"', 'class="task-checkbox',
        "alpha", "beta", "nested", "first", "second", "Task list",
    ],
    "03_table.md": [
        "<table>", "<th>", "<td>", "Name", "Size", "alpha", "after table.",
    ],
    "04_code_blocks.md": [
        "<pre>", "<code>", '<span class="',
        "ANSWER", "print", "fn", "main", "plain fence without language",
    ],
    "05_footnotes_blockquotes.md": [
        "<blockquote>", "<a ", "footnote one.", "quote two",
    ],
    "06_links_images_admonition.md": [
        "<a ", 'href="https://example.com"', "<img ",
        'src="https://example.com/img.png"', "admonition note.",
    ],
}


@pytest.fixture(scope="module")
def renderer() -> Any:
    """提供已完成可用性检查的渲染器实例。"""
    if not MARKDOWN_AVAILABLE:
        pytest.skip("markdown / pygments 依赖缺失，无法测试渲染")
    return MarkdownRenderer()


class TestAvailability:
    """依赖可用性与基础属性。"""

    def test_is_available(self) -> None:
        """依赖齐备时 is_available/available 返回 True。"""
        if not MARKDOWN_AVAILABLE:
            pytest.skip("markdown / pygments 依赖缺失")
        assert MarkdownRenderer.is_available() is True
        assert MarkdownRenderer.available() is True

    def test_set_font_size(self, renderer: Any) -> None:
        """字号设置会反映到 CSS。"""
        renderer.set_font_size(20)
        html = renderer.render("# 标题")
        assert "font-size: 20px" in html

    def test_set_font_size_non_int_raises(self, renderer: Any) -> None:
        """非整数字号 → TypeError。"""
        with pytest.raises(TypeError):
            renderer.set_font_size("18")  # type: ignore[arg-type]


class TestRendering:
    """Markdown 各语法片段渲染结果。"""

    def test_render_heading(self, renderer: Any) -> None:
        """标题带文档 id（与标题文本一致）并嵌入 h1。"""
        html = renderer.render("# 一级标题")
        assert html.startswith("<!DOCTYPE html>")
        assert "<html>" in html
        assert "<style>" in html
        assert '<h1 id="一级标题">一级标题</h1>' in html

    def test_render_bold_italic(self, renderer: Any) -> None:
        """粗体/斜体转成 strong/em 标签。"""
        html = renderer.render("**加粗**与*斜体*")
        assert "<strong>加粗</strong>" in html
        assert "<em>斜体</em>" in html

    def test_render_code_block(self, renderer: Any) -> None:
        """fenced code + codehilite → highlight/pre/code + Pygments span。"""
        html = renderer.render("```python\nprint('hello')\n```")
        assert 'class="highlight"' in html
        assert "<pre>" in html
        assert "<code>" in html
        assert "<span" in html  # Pygments 高亮片段非空

    def test_render_table(self, renderer: Any) -> None:
        """表格语法 → <table>/<th>/<td>。"""
        html = renderer.render("| a | b |\n|---|---|\n| 1 | 2 |")
        assert "<table>" in html
        assert "<th>a</th>" in html

    def test_render_task_list(self, renderer: Any) -> None:
        """任务列表 → task-item 与 checked/unchecked 复选框标记。"""
        html = renderer.render("- [x] 已完成\n- [ ] 待办")
        assert 'class="task-item"' in html
        assert 'class="task-checkbox checked"' in html
        assert 'class="task-checkbox unchecked"' in html
        assert "\u2611" in html  # ☑
        assert "\u2610" in html  # ☐

    def test_render_empty_text(self, renderer: Any) -> None:
        """空文本也能渲染出完整文档骨架。"""
        html = renderer.render("")
        assert html.startswith("<!DOCTYPE html>")
        assert "<body>" in html

    def test_render_accepts_file_path(self, renderer: Any) -> None:
        """file_path 参数不被拒绝（预留参数）。"""
        html = renderer.render("# X", file_path="sample.md")
        assert "<h1" in html


class TestQTextDocument:
    """渲染结果注入 QTextDocument。"""

    def test_html_loads_into_qtextdocument(self, renderer: Any, qapp: Any) -> None:
        """标题与代码块文本在 QTextDocument 中保留。"""
        html = renderer.render("# 一级标题\n\n```python\nprint('hi')\n```")
        doc = QTextDocument()
        doc.setHtml(html)
        plain = doc.toPlainText()
        assert "一级标题" in plain
        assert "print('hi')" in plain


# =============================================================================
# todo-17：faf_core native 高优先级路径（桥可用时优先；缺省回退 python）
# =============================================================================
class TestNativePath:
    """``render()`` 的 native 高优先级路径与 python-markdown 回退路径。

    native 引擎（bridge``render_markdown``）可用时逐项验证共享后处理生效
    （strikethrough / 代码块包装 / md_in_html 标记剥离 / task-item 吸收 /
    heading-id 与锚点重写），并对核心元素做 normalize 结构等价对拍；不可用
    时验证回退路径仍按现状渲染。
    """

    @staticmethod
    def _native_ready() -> bool:
        """faf_core 桥可加载且含 ``faf_render_markdown`` 导出。"""
        try:
            from freeassetfilter.core.native.bridges.faf_core_bridge import (
                get_faf_core_bridge,
            )

            bridge = get_faf_core_bridge()
        except Exception:  # noqa: BLE001  # 导入链异常视为不可用
            return False
        return bool(
            bridge is not None
            and bridge.available
            and getattr(bridge, "_supports_render_markdown", False)
        )

    @staticmethod
    def _force_python_path(monkeypatch: pytest.MonkeyPatch) -> None:
        """把桥降级为不可用，强制 ``render()`` 走 python-markdown。"""

        class _DegradedBridge:  # noqa: D401 - 降级占位对象，仅提供 available 属性
            available = False

        import freeassetfilter.core.native.bridges.faf_core_bridge as bridge_mod

        monkeypatch.setattr(
            bridge_mod, "get_faf_core_bridge", lambda: _DegradedBridge()
        )

    def test_native_preferred_when_available(self, renderer: Any) -> None:
        """桥可用时 render() 走 native：strikethrough 输出 ``<del>``。

        python-markdown 未加载 strikethrough 扩展（``~~删除线~~`` 按原文
        保留），native 的 ``<del>`` 是引擎归属的强判别信号。
        """
        if not self._native_ready():
            pytest.skip("faf_core 不可用，跳过 native 路径测试")
        html = renderer.render("~~删除线~~")
        assert "<del>删除线</del>" in html

    def test_native_code_block_wrapper_normalized(self, renderer: Any) -> None:
        """native ``<pre><code class="highlight">`` 归一为 codehilite 包装形态。"""
        if not self._native_ready():
            pytest.skip("faf_core 不可用，跳过 native 路径测试")
        html = renderer.render("```python\nprint('hi')\n```")
        # 共享后处理把 native 的裸 pre/code 包裹成 `.highlight pre` 可着色形态。
        assert '<div class="highlight"><pre><code>' in html
        assert '<span class="tok-' in html
        assert "print" in html

    def test_md_in_html_marker_stripped_and_content_parsed(self, renderer: Any) -> None:
        """details/div 容器：markdown=\"1\" 标记被剥离且容器内内容被解析。"""
        html = renderer.render(
            "<details>\n<summary>标题</summary>\n\n**加粗内容**\n</details>\n\n"
            '<div align="center">\n居中内容\n</div>'
        )
        assert 'markdown="1"' not in html
        assert "<details>" in html
        assert "<strong>加粗内容</strong>" in html
        # align → inline style（QTextBrowser 不识别 align 属性）。
        assert '<div style="text-align: center;">' in html

    def test_task_list_task_item_class(self, renderer: Any) -> None:
        """native 任务列表经共享后处理吸收 ``task-item`` 类（CSS 契约）。"""
        if not self._native_ready():
            pytest.skip("faf_core 不可用，跳过 native 路径测试")
        html = renderer.render("- [x] 已完成\n- [ ] 待办")
        assert 'class="task-item"' in html
        assert 'class="task-checkbox checked"' in html
        assert 'class="task-checkbox unchecked"' in html

    def test_native_vs_python_normalized_equivalent(self, renderer: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """核心元素 native 路径输出与强制 python 路径 normalize 后结构等价。"""
        if not self._native_ready():
            pytest.skip("faf_core 不可用，跳过 native 路径测试")
        from tests.support.parity.normalize_html import normalize_html_for_parity

        samples = [
            "# 一级标题\n\n**加粗** 与 *斜体*\n\n- [x] 任务\n- [ ] 待办",
            "| a | b |\n|---|---|\n| 1 | 2 |",
            "正文引用[^1]。\n\n[^1]: 脚注一 one.",
        ]
        render = renderer.render
        # 先取 native 输出，再降级桥强制 python 输出。
        native_outs = [render(text) for text in samples]
        self._force_python_path(monkeypatch)
        python_outs = [render(text) for text in samples]
        for i, (n, p) in enumerate(zip(native_outs, python_outs)):
            assert normalize_html_for_parity(n) == normalize_html_for_parity(
                p
            ), f"样本 {i} native 与 python 结构应等价"

    def test_fallback_to_python_when_bridge_unavailable(self, renderer: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """桥不可用时 render() 回退 python-markdown 现状（不变语义）。"""
        self._force_python_path(monkeypatch)
        html = renderer.render("~~删除线~~\n\n# 标题")
        # python-markdown 无 strikethrough 扩展 → `~~` 按原文保留。
        assert "<del>" not in html
        assert "~~删除线~~" in html
        # 共享后处理仍生效（heading-id 重写）。
        assert '<h1 id="标题">标题</h1>' in html

    def test_heading_id_and_anchor_normalization(self, renderer: Any) -> None:
        """heading-id 重写与 ``#-`` 锚点归一化在任一路径下都生效。"""
        html = renderer.render("# 一级标题\n\n[跳转](#-一级标题)")
        assert '<h1 id="一级标题">一级标题</h1>' in html
        assert 'href="#一级标题"' in html

    def test_markdown_samples_normalized_consistency(self, renderer: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """6 个 markdown_samples 接线后 native 与 python 的 normalized 关系不变。

        todo-15 已证 3 等价 + 3 引擎固有差异（不 FAIL，根因如下）：
        - ``02_lists_tasks.md`` 嵌套列表缩进：pulldown-cmark 遵循 CommonMark
          （2 空格即缩进 → 嵌套）；python-markdown 需 4 空格缩进（2 空格 →
          同级扁平）。两引擎各自按规范行为，非缺陷。
        - ``04_code_blocks.md`` 代码块包装 + token 粒度：native 按 todo-15
          约定输出裸 ``<pre><code class="highlight">``，python codehilite 包
          ``<div class="highlight">`` 外层（共享后处理对 native 补包装归一）；
          syntect 合并相邻同类型 span、Pygments 分词边界不同（class 已被
          normalize 忽略，剩 span 边界差）。
        - ``06_links_images_admonition.md`` blockquote 合并：python-markdown
          把相邻 ``>`` 块合并进同一 blockquote（非 CommonMark）；pulldown-cmark
          按 CommonMark 逐块独立；admonition ``[!NOTE]`` 在 native 按普通
          blockquote 精确回退（扩展降级映射）。
        """
        if not self._native_ready():
            pytest.skip("faf_core 不可用，跳过 native 路径测试")
        from tests.support.parity.normalize_html import normalize_html_for_parity

        render = renderer.render
        # 先取 native 输出，再降级桥强制 python 输出。
        native_outs = {}
        for sample_path in sorted(_SAMPLE_DIR.glob("*.md")):
            text = sample_path.read_text(encoding="utf-8", errors="replace")
            native_outs[sample_path.name] = normalize_html_for_parity(
                render(text)
            )
        self._force_python_path(monkeypatch)
        python_outs = {}
        for sample_path in sorted(_SAMPLE_DIR.glob("*.md")):
            text = sample_path.read_text(encoding="utf-8", errors="replace")
            python_outs[sample_path.name] = normalize_html_for_parity(
                render(text)
            )
        results = {
            name: native_outs[name] == python_outs[name]
            for name in native_outs
        }
        # todo-15 结论：01/03/05 EQUAL，02/04/06 引擎固有差异。
        assert results["01_headings_paragraphs.md"] is True
        assert results["03_table.md"] is True
        assert results["05_footnotes_blockquotes.md"] is True
        assert results["02_lists_tasks.md"] is False
        assert results["04_code_blocks.md"] is False
        assert results["06_links_images_admonition.md"] is False

    @staticmethod
    def _missing_key_elements(html: str, needles: list[str]) -> list[str]:
        """返回 ``html`` 中缺失的关键元素子串列表（空即全命中）。

        代码样本经语法高亮会被切成带 ``<span class="tok-*">`` 的 token，
        连续的源码文本被标签打断（如 ``ANSWER = 42`` → ``ANSWER</span><span
        ...> = </span>...），故同时用剥离标签后的纯文本做匹配。
        """
        stripped = re.sub(r"<[^>]+>", "", html)
        return [needle for needle in needles if needle not in html and needle not in stripped]

    def test_markdown_samples_key_elements_both_paths(self, renderer: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """6 个样本的关键元素在 native 与 python 两路径下都存在。

        todo-19：在既有 normalize 结构对拍（01/03/05 EQUAL、02/04/06 差异）
        之外，对每个样本断言核心 HTML 元素 / ASCII 锚点在**两条路径**的最终
        ``render()`` 输出中都存在——防止引擎回归丢失基础结构（如 heading、
        task-item 类、table、pre/code、blockquote、a/img）。native 不可用时
        跳过 native 侧（对拍在 ``faf_core_available`` 时启用），python 侧恒验。
        """
        render = renderer.render

        if self._native_ready():
            for sample_path in sorted(_SAMPLE_DIR.glob("*.md")):
                text = sample_path.read_text(encoding="utf-8", errors="replace")
                missing = self._missing_key_elements(
                    render(text), _SAMPLE_KEY_ELEMENTS[sample_path.name]
                )
                assert not missing, (
                    f"{sample_path.name} native 输出缺关键元素: {missing}"
                )

        # python 路径（强制降级）——两引擎都必须含核心元素。
        self._force_python_path(monkeypatch)
        for sample_path in sorted(_SAMPLE_DIR.glob("*.md")):
            text = sample_path.read_text(encoding="utf-8", errors="replace")
            missing = self._missing_key_elements(
                render(text), _SAMPLE_KEY_ELEMENTS[sample_path.name]
            )
            assert not missing, (
                f"{sample_path.name} python 输出缺关键元素: {missing}"
            )