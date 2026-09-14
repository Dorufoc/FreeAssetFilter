"""HTML 归一化器（todo 15 交付实现，替代 todo 5 占位）。

用途：对拍探针（native `faf_render_markdown` vs python-markdown 现状输出）
在 diff 前对两侧 HTML 做结构归一化，**只忽略结构无关差异**：

1. **忽略 `id`/`class` 属性差异**（引擎生成的锚点 id / 样式 class 不同，
   例如 python 的 `<h1 id="...">`、Pygments 的 `class="c1"` 与 syntect 的
   `class="tok-COMMENT"`）；
2. **归一化空白**：所有空白（含换行/缩进/多空格/``&nbsp;``/`\u00A0`）折叠为
   单个空格并去除文本节点两端空白（两引擎的换行位置/缩进差异被消除）；
3. **元素属性排序**（`alt`/`src` 等属性顺序差异不影响等价性）；
4. **删除空元素**（归一化后无内容的叶元素，如 Pygments 行首 `<span></span>`、
   `class="w"` 纯空白 span——内容为零，不参与结构比较）。

**不做**：重排/展开嵌套结构、合并兄弟元素、忽略元素类型或文本内容差异。
因此"相同结构不同 id/class → 相等"、"结构不同 → 不等"两个方向都能判定。

依赖：仅标准库 ``html.parser`` + ``re``（**不新增依赖**）。
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any, List, Optional, Sequence, Tuple

# HTML 空元素（自闭合/无子内容）。`<br />`/`<hr />`/`<img ... />` 等即使
# 无子节点也**不得**被当作"空元素"删除——它们是结构的一部分。
_VOID_ELEMENTS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)

# 归一化忽略的属性（引擎生成，不承载内容语义）。
_IGNORED_ATTRS = frozenset({"id", "class"})

# 空白折叠：任意空白序列（含 \n \t \u00A0）→ 单个空格。
_WS_RE = re.compile(r"\s+")

# 归一化后的节点表示：
# - 文本节点：``str``（已折叠空白、已 strip，非空）；
# - 元素节点：``(tag, attrs, children)``，``attrs`` 为已排序的
#   ``[(key, value), ...]``（不含 id/class），``children`` 为子节点列表；
# - 空元素（``<br />`` 等）：``(tag, attrs, None)``。


def _norm_text(data: str) -> str:
    """折叠空白序列为单空格并 strip 两端。纯空白返回空串。"""
    return _WS_RE.sub(" ", data).strip()


def _norm_attrs(attrs: Sequence[Tuple[str, Optional[str]]]) -> List[Tuple[str, Optional[str]]]:
    """过滤 id/class 并按 key 排序（消除属性顺序差异）。"""
    kept = [(k.lower(), v) for k, v in attrs if k.lower() not in _IGNORED_ATTRS]
    kept.sort(key=lambda kv: kv[0])
    return kept


def _escape_attr(value: Optional[str]) -> str:
    """属性值 HTML 转义（序列化回 HTML 时保证可再解析且值文本一致）。"""
    if value is None:
        return ""
    return (
        value.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


class _TreeBuilder(HTMLParser):
    """把 HTML 解析为归一化节点树（文本即时折叠、属性即时过滤排序）。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._root: List[Any] = []
        # 栈元素为 ``(tag, children)``：children 是待填充的当前开元素子列表。
        self._stack: List[Tuple[str, List[Any]]] = []

    def _append(self, node: Any) -> None:
        if self._stack:
            self._stack[-1][1].append(node)
        else:
            self._root.append(node)

    def handle_starttag(self, tag: str, attrs: Sequence[Tuple[str, Optional[str]]]) -> None:
        children: List[Any] = []
        self._append((tag.lower(), _norm_attrs(attrs), children))
        if tag.lower() not in _VOID_ELEMENTS:
            self._stack.append((tag.lower(), children))

    def handle_startendtag(self, tag: str, attrs: Sequence[Tuple[str, Optional[str]]]) -> None:
        # 自闭合标签：children=None 标记为"永不删除的空元素"。
        self._append((tag.lower(), _norm_attrs(attrs), None))

    def handle_endtag(self, tag: str) -> None:
        target = tag.lower()
        # 弹出到最近匹配的开元素；不匹配的闭合标签（畸形 HTML）忽略。
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == target:
                del self._stack[i:]
                break

    def handle_data(self, data: str) -> None:
        text = _norm_text(data)
        if text:
            self._append(text)

    def handle_comment(self, data: str) -> None:
        # 注释不参与内容比较。
        return None


def _prune(node: Any) -> Optional[Any]:
    """自底向上删除归一化后无内容的元素。返回删除后的节点；None 表示空。"""
    if isinstance(node, str):
        return node  # 文本节点已在解析时折叠且非空
    tag, attrs, children = node
    if children is None:
        return node  # 空元素（<br />/<hr />/<img />）永不删除
    kept: List[Any] = []
    for child in children:
        pruned = _prune(child)
        if pruned is not None:
            kept.append(pruned)
    if not kept:
        return None
    return (tag, attrs, kept)


def _serialize(node: Any) -> str:
    """归一化节点 → 单行 HTML 文本。"""
    if isinstance(node, str):
        return node
    tag, attrs, children = node
    attr_str = "".join(f' {k}="{_escape_attr(v)}"' for k, v in attrs)
    if children is None:
        return f"<{tag}{attr_str}>"
    inner = "".join(_serialize(child) for child in children)
    return f"<{tag}{attr_str}>{inner}</{tag}>"


def normalize_html_for_parity(html: str) -> str:
    """归一化 HTML 供 parity diff（忽略 id/class、折叠空白、排序属性、删空元素）。

    Args:
        html: 待归一化的 HTML 文本（可以是 body 片段或完整文档）。

    Returns:
        str: 单行归一化文本；两侧经此函数后相同 ⟺ 结构等价（忽略 id/class）。
    """
    parser = _TreeBuilder()
    parser.feed(html)
    parser.close()
    pruned = [_prune(child) for child in parser._root]
    pruned = [child for child in pruned if child is not None]
    return "".join(_serialize(child) for child in pruned)


def selftest() -> List[str]:
    """自测用例：相同结构不同 id/class → 相等；结构不同 → 不等。

    Returns:
        list[str]: 失败信息列表；为空即全部通过。
    """
    failures: List[str] = []

    # 1. 相同结构，id/class 不同 → 相等（heading id + token class）。
    a = (
        '<h1 id="一级标题 Heading" class="toc">一级标题 Heading</h1>'
        '<pre><code class="highlight"><span class="c1"># COMMENT</span>\n'
        '<span class="n">ANSWER</span></code></pre>'
    )
    b = (
        '<h1 id="other">一级标题 Heading</h1>'
        '<pre><code class="highlight"><span class="tok-COMMENT"># COMMENT</span>'
        '<span class="tok-VARIABLE">ANSWER</span></code></pre>'
    )
    if normalize_html_for_parity(a) != normalize_html_for_parity(b):
        failures.append("相同结构不同 id/class 应相等")

    # 2. 结构不同（元素类型不同）→ 不等。
    c = "<h1>标题</h1><p>正文</p>"
    d = "<h2>标题</h2><p>正文</p>"
    if normalize_html_for_parity(c) == normalize_html_for_parity(d):
        failures.append("不同元素类型（h1 vs h2）应不等")

    # 3. 结构不同（子节点缺失）→ 不等；空白差异 → 相等。
    e = "<ul><li>a</li><li>b</li></ul>"
    f = "<ul><li>a</li></ul>"
    if normalize_html_for_parity(e) == normalize_html_for_parity(f):
        failures.append("缺失子元素应不等")
    g = "<p>a\n  b</p>"
    h = "<p>a b</p>"
    if normalize_html_for_parity(g) != normalize_html_for_parity(h):
        failures.append("空白差异应相等")

    return failures


if __name__ == "__main__":
    failures = selftest()
    if failures:
        raise SystemExit("normalize_html selftest FAILED:\n" + "\n".join(failures))
    print("normalize_html selftest OK")
