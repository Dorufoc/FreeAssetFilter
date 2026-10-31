# -*- coding: utf-8 -*-
"""StyledTextarea 只读模式单元测试（rust-native-updater Todo 16）。

覆盖验收点：

1. ``read_only=True`` 时内部 ``QPlainTextEdit`` 不可编辑；
2. 只读时即使传入 ``max_length`` 也隐藏字符计数器；
3. 只读模式仍是纯文本控件，``text`` / ``toPlainText`` 行为不变；
4. 默认（``read_only=False``）保持可编辑并显示计数器，不破坏既有调用。

验证命令：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/unit/ui/components/test_styled_textarea.py -k read_only -v
"""

# targets: ui.components.styled_textarea

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

# 组件模块内部使用短路径导入（from theme import tm），要求 sopeek/ui
# 位于 sys.path；与 test_styled_dialog.py / test_styled_basic.py 约定一致。
_UI_ROOT: str = str(Path(__file__).resolve().parents[4] / "sopeek" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from tests.support.qt_helpers import safe_teardown  # noqa: E402

from sopeek.ui.components.styled_textarea import StyledTextarea  # noqa: E402

pytestmark = pytest.mark.unit


@pytest.fixture()
def textarea_factory(qapp: QApplication):
    """构造 StyledTextarea 并在用例后安全销毁。

    Args:
        qapp: 会话级 QApplication。

    Yields:
        Callable[..., StyledTextarea]: 转发 StyledTextarea 构造参数。
    """
    created: list[StyledTextarea] = []

    def _make(**kwargs) -> StyledTextarea:
        area = StyledTextarea(**kwargs)
        created.append(area)
        return area

    yield _make

    for area in created:
        safe_teardown(area)


class TestReadOnlyTextarea:
    """``read_only`` 公开参数：禁用编辑、隐藏计数器、保持纯文本。"""

    def test_read_only_disables_editing_and_hides_counter(
        self, textarea_factory
    ) -> None:
        """只读时不可编辑，且 max_length 计数器被隐藏。"""
        area = textarea_factory(text="只读内容", max_length=20, read_only=True)

        assert area.read_only is True
        assert area._text_edit.isReadOnly() is True
        assert area._counter_label.isHidden() is True

    def test_read_only_keeps_plain_text_behavior(self, textarea_factory) -> None:
        """只读控件仍以纯文本读写，不引入富文本格式。"""
        area = textarea_factory(text="第一行\n第二行", read_only=True)

        assert area.text == "第一行\n第二行"
        assert area._text_edit.toPlainText() == "第一行\n第二行"

        # 程序化赋值仍然生效（只读只阻止用户编辑）。
        area.text = "替换后的纯文本"
        assert area.text == "替换后的纯文本"
        assert area._text_edit.toPlainText() == "替换后的纯文本"

    def test_read_only_property_can_be_toggled(self, textarea_factory) -> None:
        """read_only 属性可切换，并同步编辑状态与计数器显隐。"""
        area = textarea_factory(text="abc", max_length=10, read_only=False)
        assert area._text_edit.isReadOnly() is False
        assert area._counter_label.isHidden() is False

        area.read_only = True
        assert area._text_edit.isReadOnly() is True
        assert area._counter_label.isHidden() is True

        area.read_only = False
        assert area._text_edit.isReadOnly() is False
        assert area._counter_label.isHidden() is False

    def test_default_textarea_stays_editable_with_counter(
        self, textarea_factory
    ) -> None:
        """默认模式不受影响：可编辑且计数器可见。"""
        area = textarea_factory(text="abc", max_length=10)

        assert area.read_only is False
        assert area._text_edit.isReadOnly() is False
        assert area._counter_label.isHidden() is False
        assert area._counter_label.text() == "3/10"
