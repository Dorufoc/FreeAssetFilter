# -*- coding: utf-8 -*-
"""文本预览器高亮器生命周期测试（P1.0）。

锁定两条不变量：

1. **实例复用**：同一控件生命周期内只创建一个 ``_TextHighlighter``；
   连续加载文件、切换语言、切换主题都不得新建。
2. **可释放**：``cleanup()`` / 切到 ``"text"`` 语言时必须 ``dispose()``
   把实例从 ``QTextDocument`` 上摘除（否则同一文档会累积多个高亮器，
   每次 rehighlight 重复 setFormat）。

验证命令：
    python -m pytest tests/unit/ui/layout/preview/test_text_previewer_highlighter.py -v
"""

from __future__ import annotations

import time
from typing import Any, Dict, Iterator, List

import pytest
from PySide6.QtWidgets import QApplication

from freeassetfilter.ui.layout.preview import text_previewer_layout as _tpl
from freeassetfilter.ui.layout.preview.text_previewer_layout import (
    TextPreviewerLayout,
)
from tests.support.qt_helpers import safe_teardown

pytestmark = pytest.mark.unit

_CODE_A = "def func_a(x):\n    # comment\n    return x + 1\n"
_CODE_B = "def func_b(y):\n    return y * 2\n"


def _pump(app: QApplication, ms: int = 40) -> None:
    """驱动事件循环 ms 毫秒（offscreen 下等待布局/重绘落定）。"""
    deadline = time.monotonic() + ms / 1000.0
    while time.monotonic() < deadline:
        app.processEvents()


@pytest.fixture()
def layout(qapp: QApplication) -> Iterator[TextPreviewerLayout]:
    """构造并显示文本预览器，测试结束后安全销毁。"""
    previewer = TextPreviewerLayout()
    previewer.resize(900, 600)
    previewer.show()
    _pump(qapp, 60)
    yield previewer
    safe_teardown(previewer)


@pytest.fixture()
def created_highlighters(monkeypatch: Any) -> List[Any]:
    """记录 ``_TextHighlighter`` 的实例化次数（不改变行为）。"""
    created: List[Any] = []
    original_init = _tpl._TextHighlighter.__init__

    def counting_init(self: Any, *args: Any, **kwargs: Any) -> None:
        created.append(self)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(_tpl._TextHighlighter, "__init__", counting_init)
    return created


def test_highlighter_instance_reused_across_loads(
    qapp: QApplication,
    layout: TextPreviewerLayout,
    created_highlighters: List[Any],
) -> None:
    """连续加载两个代码文件 + 切主题 + 切语言，只应创建一个实例。"""
    layout.set_text_content(_CODE_A, "a.py")
    first = layout._highlighter
    assert first is not None, "代码文件应创建高亮器"
    assert len(created_highlighters) == 1

    # 换文件：复用同一实例（语言相同）
    layout.set_text_content(_CODE_B, "b.py")
    _pump(qapp)
    assert layout._highlighter is first
    assert len(created_highlighters) == 1

    # 切主题：只重设配色，不重建
    layout.update_theme()
    _pump(qapp)
    assert layout._highlighter is first
    assert len(created_highlighters) == 1

    # 切语言：复用实例 + rehighlight
    layout._apply_highlighter("javascript")
    assert layout._highlighter is first
    assert len(created_highlighters) == 1


def test_cleanup_disposes_highlighter(
    qapp: QApplication, layout: TextPreviewerLayout
) -> None:
    """``cleanup()`` 必须把实例从文档上摘除，而非仅置空引用。"""
    layout.set_text_content(_CODE_A, "a.py")
    highlighter = layout._highlighter
    assert highlighter is not None
    assert highlighter.document() is not None

    layout.cleanup()
    _pump(qapp)

    assert layout._highlighter is None
    assert highlighter._disposed is True
    assert highlighter.document() is None, "dispose() 后应已脱离 QTextDocument"


def test_text_language_disposes_highlighter(
    qapp: QApplication, layout: TextPreviewerLayout
) -> None:
    """切到 ``"text"`` 语言（非代码文件）时释放实例。"""
    layout.set_text_content(_CODE_A, "a.py")
    highlighter = layout._highlighter
    assert highlighter is not None

    layout._apply_highlighter("text")
    _pump(qapp)

    assert layout._highlighter is None
    assert highlighter._disposed is True
    assert highlighter.document() is None


def test_dispose_is_idempotent(
    qapp: QApplication, layout: TextPreviewerLayout
) -> None:
    """重复 dispose() 不得抛异常。"""
    layout.set_text_content(_CODE_A, "a.py")
    highlighter = layout._highlighter
    assert highlighter is not None
    highlighter.dispose()
    highlighter.dispose()
    assert highlighter.document() is None


def test_highlighter_survives_document_clear(
    qapp: QApplication, layout: TextPreviewerLayout
) -> None:
    """``setPlainText`` 清空文档后，高亮器仍挂在同一文档上（可复用）。"""
    layout.set_text_content(_CODE_A, "a.py")
    highlighter = layout._highlighter
    assert highlighter is not None
    document = highlighter.document()

    layout._source_view._text_edit.setPlainText("")
    _pump(qapp)

    assert highlighter.document() is document, "清空文本不得导致高亮器脱挂"
