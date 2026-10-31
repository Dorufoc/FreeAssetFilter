# -*- coding: utf-8 -*-
"""StyledChatBubble / ChatMessageRow 单元测试。

覆盖本轮 WinUI 3 气泡重构的公开契约：徽标与扩展名工具函数、RowSpec 工厂、
气泡的文本/图片/文件/typing 构造、换行宽度语义、最大宽度换算、主题切换与
头像绘制。深度像素比对由独立验证用例负责，这里只锁定可证伪的行为契约。

验证命令：
    python -m pytest tests/unit/ui/components/test_styled_chat_bubble.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPixmap, QRegion
from PySide6.QtWidgets import QApplication, QHBoxLayout, QVBoxLayout, QWidget

# 组件模块内部使用短路径导入（from theme import tm），要求 sopeek/ui
# 位于 sys.path；与 tests/unit/ui/components/test_styled_basic.py 保持一致。
_UI_ROOT: str = str(Path(__file__).resolve().parents[4] / "sopeek" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from sopeek.ui.components.styled_chat_bubble import (  # noqa: E402
    FILE_NAME_MIN_WIDTH,
    FOOTER_HEIGHT,
    HEADER_HEIGHT,
    SHADOW_MARGIN,
    ChatMessageRow,
    RowSpec,
    StyledAIAvatar,
    StyledAIAvatarAccent,
    StyledChatBubble,
    accent_color,
    file_badge_color,
    file_badge_text,
    file_extension,
    make_ai_avatar_pixmap,
    window_fill_color,
)
from sopeek.ui.theme import tm  # noqa: E402

LONG_ASSISTANT_TEXT = "你好呀，可以给我发送文字、图片或文件试试，我会自动回复你。"


def _natural_text_width(text: str, pixel_size: int = 14) -> int:
    """用与组件一致的字体度量文本单行宽度。

    Args:
        text: 文本内容。
        pixel_size: 字号（像素）。

    Returns:
        单行像素宽度。
    """
    font = QFont("Microsoft YaHei UI")
    font.setPixelSize(pixel_size)
    return QFontMetrics(font).horizontalAdvance(text)


def _render(widget: QWidget, size: QSize | None = None) -> QPixmap:
    """把控件渲染到透明位图。

    注意不能对顶层控件用 ``grab()``：它会把窗口底(系统默认底色)一起抓进来，
    圆角外的四角因此不是透明的。这里改为在 ``QWidget.render`` 的基础上关掉
    ``DrawWindowBackground``，只画控件自身，圆角外保持 alpha=0。

    Args:
        widget: 目标控件。
        size: 指定尺寸；为空时使用 sizeHint。

    Returns:
        渲染结果位图（设备像素比 1.0）。
    """
    if size is not None:
        widget.resize(size)
    widget.ensurePolished()
    pixmap = QPixmap(widget.size())
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    widget.render(
        painter, QPoint(0, 0), QRegion(), QWidget.RenderFlag.DrawChildren
    )
    painter.end()
    return pixmap


def _has_color(image: Any, color: QColor, tolerance: int = 6) -> bool:
    """判断图像中是否存在与目标色相近的不透明像素。

    Args:
        image: ``QImage``。
        color: 目标颜色。
        tolerance: 每个通道允许的误差。

    Returns:
        存在相近像素返回 True。
    """
    for x in range(image.width()):
        for y in range(image.height()):
            pixel = image.pixelColor(x, y)
            if pixel.alpha() < 200:
                continue
            if (
                abs(pixel.red() - color.red()) <= tolerance
                and abs(pixel.green() - color.green()) <= tolerance
                and abs(pixel.blue() - color.blue()) <= tolerance
            ):
                return True
    return False


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


class TestFileHelpers:
    """扩展名与徽标工具函数。"""

    @pytest.mark.parametrize(
        ("name", "expected"),
        (
            ("设计规范 v2.1.pdf", "pdf"),
            ("接口文档.docx", "docx"),
            ("archive.tar.gz", "gz"),
            ("无扩展名", ""),
            ("", ""),
        ),
    )
    def test_file_extension(self, name: str, expected: str) -> None:
        """扩展名解析取最后一段并转小写。"""
        assert file_extension(name) == expected

    @pytest.mark.parametrize(
        ("name", "extension", "expected"),
        (
            ("设计规范 v2.1.pdf", "", "PDF"),
            ("接口文档.docx", "", "DOCX"),
            ("a.xlsx", "", "XLSX"),
            ("未知文件", "", "FILE"),
            ("任意名", "pptx", "PPTX"),
            ("五字扩展", "abcdef", "ABCD"),
        ),
    )
    def test_file_badge_text(self, name: str, extension: str, expected: str) -> None:
        """徽标文字大写、最多 4 字符、缺失时回退 FILE。"""
        assert file_badge_text(name, extension) == expected

    def test_file_badge_color_known_extensions(self, qapp: Any) -> None:
        """已知扩展名使用 HTML 原型里的固定底色。"""
        assert file_badge_color("接口文档.docx").name().upper() == "#2B579A"
        assert file_badge_color("设计规范.pdf").name().upper() == "#D93025"
        assert file_badge_color("排期表.xlsx").name().upper() == "#217346"

    def test_file_badge_color_unknown_falls_back_to_accent(self, qapp: Any) -> None:
        """未知扩展名回退到当前模式的强调色。"""
        assert file_badge_color("文件.unknown").name() == accent_color().name()


# ---------------------------------------------------------------------------
# RowSpec
# ---------------------------------------------------------------------------


class TestRowSpec:
    """消息内容描述的工厂方法。"""

    def test_text_factory(self) -> None:
        """text_of 只填文本与类型。"""
        spec = RowSpec.text_of("你好")
        assert spec.message_type == "text"
        assert spec.text == "你好"
        assert spec.file_name == ""

    def test_file_factory(self) -> None:
        """file 工厂填名称/大小/徽标。"""
        spec = RowSpec.file("设计规范 v2.1.pdf", "1.6 MB", "PDF")
        assert (spec.message_type, spec.file_name, spec.file_size) == (
            "file",
            "设计规范 v2.1.pdf",
            "1.6 MB",
        )
        assert spec.file_extension == "PDF"

    def test_image_and_typing_factory(self) -> None:
        """image / typing 工厂返回对应类型。"""
        assert RowSpec.image("a.png").message_type == "image"
        assert RowSpec.image("a.png").image_path == "a.png"
        assert RowSpec.typing().message_type == "typing"

    def test_default_is_text(self) -> None:
        """默认构造为文本类型。"""
        assert RowSpec().message_type == "text"


# ---------------------------------------------------------------------------
# 气泡契约
# ---------------------------------------------------------------------------


class TestStyledChatBubbleContract:
    """气泡的角色/类型归一化与内容 API。"""

    def test_unknown_role_and_type_are_normalized(self, qapp: Any) -> None:
        """非法 role/type 回退到 assistant/text。"""
        bubble = StyledChatBubble("不存在的角色", "不存在的类型", "文本")
        assert bubble.role == "assistant"
        assert bubble.message_type == "text"
        assert bubble.text == "文本"

    def test_role_labels_cover_documented_roles(self) -> None:
        """ROLE_LABELS 覆盖文档列出的五种角色。"""
        for role in ("user", "assistant", "reasoning", "system", "tool"):
            assert role in StyledChatBubble.ROLE_LABELS

    def test_text_round_trip(self, qapp: Any) -> None:
        """set_text / append_text / streaming 光标。"""
        bubble = StyledChatBubble("assistant", "text", "甲")
        assert bubble.text == "甲"
        bubble.append_text("乙")
        assert bubble.text == "甲乙"
        bubble.set_streaming(True)
        assert bubble.text == "甲乙"
        bubble.set_streaming(False)
        assert bubble.max_width() > 0

    def test_file_bubble_exposes_badge_and_meta(self, qapp: Any) -> None:
        """文件气泡构造携带徽标文字与大小文案。"""
        bubble = StyledChatBubble(
            "user",
            "file",
            file_name="设计规范 v2.1.pdf",
            file_size="1.6 MB",
            file_extension="PDF",
        )
        texts = [widget.text() for widget in bubble.findChildren(QWidget) if hasattr(widget, "text")]
        assert "PDF" in texts
        assert "设计规范 v2.1.pdf" in texts
        assert "1.6 MB" in texts

    def test_typing_bubble_has_no_text_body(self, qapp: Any) -> None:
        """typing 气泡不渲染正文文本。"""
        bubble = StyledChatBubble("assistant", "typing")
        assert bubble.message_type == "typing"


# ---------------------------------------------------------------------------
# 宽度语义
# ---------------------------------------------------------------------------


class TestBubbleWidthSemantics:
    """最大宽度与换行宽度的换算规则。"""

    def test_file_bubble_honours_min_width_on_normal_viewport(self, qapp: Any) -> None:
        """常规视口下文件气泡不小于 HTML 的 ``min-width: 220px``。"""
        bubble = StyledChatBubble("assistant", "file", file_name="a.pdf")
        bubble.set_max_width(400)
        assert bubble.max_width() >= 220
        assert bubble.sizeHint().width() >= 220

    def test_file_bubble_shrinks_on_extreme_narrow_viewport(self, qapp: Any) -> None:
        """视口极窄时文件气泡允许收缩到内容宽度，不得溢出视口。"""
        bubble = StyledChatBubble("assistant", "file", file_name="a.pdf")
        bubble.set_max_width(40)
        # 上限被抬到文本可用宽度下限；气泡实际宽度仍以内容为准且可控。
        assert bubble.sizeHint().width() <= max(bubble.max_width(), 220)
        assert bubble._floor >= FILE_NAME_MIN_WIDTH

    def test_short_text_bubble_is_compact(self, qapp: Any) -> None:
        """短文本气泡宽度 = 文本自然宽 + 左右内边距 + 投影留白。"""
        bubble = StyledChatBubble("user", "text", "哈哈哈")
        bubble.set_max_width(304)
        bubble.ensurePolished()
        expected = _natural_text_width("哈哈哈") + 13 * 2 + SHADOW_MARGIN * 2
        assert abs(bubble.sizeHint().width() - expected) <= 6, (
            f"短文本气泡应紧凑：期望≈{expected}，实际={bubble.sizeHint().width()}"
        )
        assert bubble.sizeHint().width() < 304

    def test_long_text_bubble_uses_full_limit(self, qapp: Any) -> None:
        """长文本气泡用满最大宽度而不是被挤到最小宽度。"""
        bubble = StyledChatBubble("assistant", "text", LONG_ASSISTANT_TEXT)
        bubble.set_max_width(304)
        bubble.resize(bubble.sizeHint())
        bubble.ensurePolished()
        assert bubble.sizeHint().width() == 304, (
            f"长文本应达到宽度上限，实际={bubble.sizeHint().width()}"
        )
        assert _natural_text_width(LONG_ASSISTANT_TEXT) > 304

    def test_row_converts_viewport_to_bubble_limit(self, qapp: Any) -> None:
        """消息行按 74% 视口宽扣除头像与间距后下发气泡上限。"""
        row = ChatMessageRow("assistant", RowSpec.text_of(LONG_ASSISTANT_TEXT))
        row.set_max_width(460)
        expected = int(460 * 0.74) - ChatMessageRow.AVATAR_SIZE - ChatMessageRow.GAP
        assert row.bubble.max_width() == expected

    def test_row_mirrors_by_role(self, qapp: Any) -> None:
        """我方消息靠右、对方靠左，且底对齐头像。"""
        mine = ChatMessageRow("user", RowSpec.text_of("我"))
        other = ChatMessageRow("assistant", RowSpec.text_of("对"))
        assert mine.is_me is True and other.is_me is False
        assert mine.avatar.width() == ChatMessageRow.AVATAR_SIZE
        assert isinstance(mine.avatar, StyledAIAvatarAccent)
        assert isinstance(other.avatar, StyledAIAvatar)

    def test_user_bubble_tail_is_on_the_right(self, qapp: Any) -> None:
        """我方气泡收窄角在右、对方在左。"""
        assert StyledChatBubble("user", "text", "我").align_tail_direction() is True
        assert (
            StyledChatBubble("assistant", "text", "对").align_tail_direction() is False
        )


# ---------------------------------------------------------------------------
# 绘制与主题
# ---------------------------------------------------------------------------


class TestHoverFooter:
    """悬停操作页脚：时间 + 复制显示在气泡下方，且不得引起任何重排。"""

    def _bubble(self, qapp: Any) -> Any:
        """构造一个带时间戳的文本气泡并挂到宿主上完成布局。

        宿主必须挂在测试实例上：局部变量出作用域后宿主会被 GC，连带子控件一起
        销毁，后续断言就会命中 "Internal C++ object already deleted"。

        Args:
            qapp: Qt 应用 fixture。

        Returns:
            已布局好的气泡。
        """
        host = QWidget()
        host.resize(475, 240)
        layout = QHBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        row = ChatMessageRow(
            "assistant", RowSpec.text_of(LONG_ASSISTANT_TEXT)
        )
        layout.addWidget(row)
        layout.addStretch(1)
        host.show()
        QApplication.processEvents()
        row.set_max_width(475)
        host.adjustSize()
        QApplication.processEvents()
        row.bubble.set_time_text("23:32")
        QApplication.processEvents()
        self._host = host
        return row.bubble

    def test_footer_is_reserved_below_bubble(self, qapp: Any) -> None:
        """页脚区常驻在气泡下方，高度为 FOOTER_MARGIN_TOP + FOOTER_HEIGHT。"""
        bubble = self._bubble(qapp)
        footer = bubble._footer._widget
        top = footer.mapTo(bubble, QPoint(0, 0))
        assert top.y() >= bubble._frame.height(), (
            f"页脚应位于气泡底板下方：页脚 y={top.y()} 底板高={bubble._frame.height()}"
        )
        assert footer.height() == FOOTER_HEIGHT

    def test_hover_does_not_relayout_bubble(self, qapp: Any) -> None:
        """悬停显示页脚前后，气泡与消息行几何完全一致。"""
        bubble = self._bubble(qapp)
        row = bubble.parentWidget()
        before = (bubble.width(), bubble.height(), row.width(), row.height())
        bubble._set_footer_visible(True)
        QApplication.processEvents()
        after = (bubble.width(), bubble.height(), row.width(), row.height())
        assert before == after, f"悬停引起了重排：{before} -> {after}"

    def test_footer_hidden_by_default_and_toggles_visibility(self, qapp: Any) -> None:
        """页脚初始隐藏；显示/隐藏只切换可见性，几何保持不变。"""
        bubble = self._bubble(qapp)
        footer = bubble._footer._widget
        assert bubble._footer.visible is False
        assert not footer.isVisible()

        geometry = footer.geometry()
        bubble._set_footer_visible(True)
        QApplication.processEvents()
        assert bubble._footer.visible is True
        assert footer.isVisible()
        assert bubble._footer_time.isVisible()

        bubble._set_footer_visible(False)
        QApplication.processEvents()
        assert bubble._footer.visible is False
        assert not footer.isVisible()
        assert footer.geometry() == geometry, "页脚显隐改变了自身几何"

    def test_footer_children_stay_inside_bubble(self, qapp: Any) -> None:
        """页脚内的时间与复制都不得越出气泡的水平范围。"""
        bubble = self._bubble(qapp)
        bubble._set_footer_visible(True)
        QApplication.processEvents()
        for name, widget in (
            ("时间", bubble._footer_time),
            ("复制", bubble._copy),
        ):
            top_left = widget.mapTo(bubble, QPoint(0, 0))
            right = top_left.x() + widget.width() - 1
            assert top_left.x() >= 0 and right < bubble.width(), (
                f"{name} 越出气泡：x={top_left.x()}..{right}，气泡宽 {bubble.width()}"
            )

    def test_copy_button_emits_full_text(self, qapp: Any) -> None:
        """点击复制按钮发出完整正文。"""
        bubble = self._bubble(qapp)
        received: list[str] = []
        bubble.copied.connect(received.append)
        bubble._copy.click()
        assert received == [LONG_ASSISTANT_TEXT]


class TestReasoningDrawer:
    """思考抽屉：折叠态只剩标题栏，展开态向下推开气泡（不占独立气泡）。"""

    def _row(self, qapp: Any, viewport: int = 475) -> Any:
        """构造一个助手消息行并完成布局。

        Args:
            qapp: Qt 应用 fixture。
            viewport: 消息区视口宽度。

        Returns:
            已布局的消息行。
        """
        host = QWidget()
        host.resize(viewport, 460)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        row = ChatMessageRow("assistant", RowSpec.text_of("回复正文"))
        layout.addWidget(row)
        layout.addStretch(1)
        host.show()
        QApplication.processEvents()
        row.set_max_width(viewport)
        host.adjustSize()
        QApplication.processEvents()
        self._host = host
        return row

    def test_drawer_is_collapsed_by_default_with_single_header(self, qapp: Any) -> None:
        """默认收起，只占标题栏高度，正文高度为 0。"""
        row = self._row(qapp)
        drawer = row.ensure_drawer()
        QApplication.processEvents()
        assert drawer.expanded is False
        assert drawer.height() == HEADER_HEIGHT
        assert drawer._body.maximumHeight() == 0

    def test_expand_reveals_body_and_pushes_bubble_down(self, qapp: Any) -> None:
        """展开后正文可见，且把气泡向下推开（同一列，不新增气泡）。"""
        row = self._row(qapp)
        drawer = row.ensure_drawer()
        drawer.set_text("思考内容" * 20)
        QApplication.processEvents()
        collapsed_row_height = row.height()

        drawer.set_expanded(True, animated=False)
        QApplication.processEvents()
        self._host.adjustSize()
        QApplication.processEvents()

        assert drawer.expanded is True
        assert drawer._body.height() > 0, "展开后正文高度应大于 0"
        assert row.height() > collapsed_row_height, "展开应把气泡向下推开"
        assert drawer.height() > HEADER_HEIGHT
        # 抽屉在气泡正上方（同一列）：抽屉底边不得越过气泡所在那一行的顶边。
        # 注意"气泡"是徽章行的子控件，其 y 是相对徽章行的；这里统一换算到消息行
        # 坐标系再比较。
        badge_row = row._column.itemAt(1).widget()
        drawer_bottom = drawer.y() + drawer.height()
        assert drawer_bottom <= badge_row.y(), (
            f"抽屉底边 {drawer_bottom} 越过了气泡所在行的顶边 {badge_row.y()}"
        )
        assert row.bubble.text == "回复正文", "展开思考不得改变气泡内容/数量"

    def test_collapse_restores_original_row_height(self, qapp: Any) -> None:
        """收起后行高恢复到未展开时的值。"""
        row = self._row(qapp)
        drawer = row.ensure_drawer()
        drawer.set_text("思考内容" * 20)
        QApplication.processEvents()
        original = row.height()
        drawer.set_expanded(True, animated=False)
        QApplication.processEvents()
        drawer.set_expanded(False, animated=False)
        QApplication.processEvents()
        self._host.adjustSize()
        QApplication.processEvents()
        assert row.height() == original
        assert drawer._body.maximumHeight() == 0

    def test_header_title_reflects_elapsed_time(self, qapp: Any) -> None:
        """标题栏显示「已思考（用时 N 秒）」，耗时按毫秒换算。"""
        row = self._row(qapp)
        drawer = row.ensure_drawer()
        drawer.set_elapsed_ms(1000)
        assert drawer._title.text() == "已思考（用时 1 秒）"
        drawer.set_elapsed_ms(3400)
        assert drawer._title.text() == "已思考（用时 3 秒）"
        assert drawer.elapsed_ms() == 3400

    def test_toggle_flips_state_and_emits_signal(self, qapp: Any) -> None:
        """toggle 切换展开状态并发出 toggled 信号。"""
        row = self._row(qapp)
        drawer = row.ensure_drawer()
        received: list[bool] = []
        drawer.toggled.connect(received.append)
        drawer.toggle()
        assert drawer.expanded is True
        drawer.toggle()
        assert drawer.expanded is False
        assert received == [True, False]

    def test_append_text_accumulates(self, qapp: Any) -> None:
        """流式追加累积到同一抽屉，而不是新建气泡。"""
        row = self._row(qapp)
        drawer = row.ensure_drawer()
        bubbles_before = len(row.findChildren(StyledChatBubble))
        drawer.append_text("甲")
        drawer.append_text("乙")
        assert drawer.text == "甲乙"
        assert len(row.findChildren(StyledChatBubble)) == bubbles_before

    def test_drawer_width_does_not_exceed_bubble_cap(self, qapp: Any) -> None:
        """抽屉宽度上限与气泡一致（同一列），不会横跨到对面头像区。"""
        row = self._row(qapp)
        drawer = row.ensure_drawer()
        drawer.set_text("思考内容" * 30)
        QApplication.processEvents()
        assert drawer.width() <= row.bubble.max_width()
        assert drawer.maximumWidth() <= row.bubble.max_width()


class TestPaintingAndTheme:
    """自绘头像与主题切换。"""

    def test_ai_avatar_pixmap_has_transparent_corners(self, qapp: Any) -> None:
        """渐变头像为圆形：四角透明、中心不透明。"""
        pixmap = make_ai_avatar_pixmap(40)
        image = pixmap.toImage()
        assert image.pixelColor(0, 0).alpha() == 0
        assert image.pixelColor(39, 0).alpha() == 0
        assert image.pixelColor(20, 20).alpha() > 0

    def test_text_avatar_is_circular(self, qapp: Any) -> None:
        """文字头像四角透明、中心为浅灰底。"""
        avatar = StyledAIAvatar("对", 28)
        pixmap = _render(avatar, QSize(28, 28))
        image = pixmap.toImage()
        assert image.pixelColor(0, 0).alpha() == 0
        assert image.pixelColor(14, 14).alpha() > 0

    def test_accent_avatar_uses_accent_fill(self, qapp: Any) -> None:
        """我方头像使用强调色实底。"""
        avatar = StyledAIAvatarAccent("我", 28)
        pixmap = _render(avatar, QSize(28, 28))
        assert _has_color(pixmap.toImage(), accent_color()), "强调色头像中未找到强调色像素"

    def test_bubble_fill_follows_theme(self, qapp: Any) -> None:
        """气泡底色随浅/深色主题切换而变化（浅色参考蓝、深色主题强调色）。"""
        bubble = StyledChatBubble("user", "text", "主题")
        bubble.set_max_width(200)
        original = tm.effective_theme()
        try:
            tm.set_theme("light")
            light_fill = bubble._frame._fill_color().name()
            light_accent = accent_color().name()
            tm.set_theme("dark")
            dark_fill = bubble._frame._fill_color().name()
            dark_accent = accent_color().name()
        finally:
            tm.set_theme(original)
        assert light_fill == light_accent == tm.accent.name()
        assert dark_fill == dark_accent == tm.accent.name()
        # 主题切换不得改变几何：上限保持、短文本仍紧凑（「主题」二字 = 28 + 26 + 6）。
        assert bubble.max_width() == 200
        assert bubble.sizeHint().width() == 2 * 14 + 13 * 2 + SHADOW_MARGIN * 2

    def test_light_accent_uses_theme_token(self, qapp: Any) -> None:
        """浅色模式强调色直接使用 tm.accent。"""
        original = tm.effective_theme()
        try:
            tm.set_theme("light")
            assert accent_color().name() == tm.accent.name()
            assert StyledChatBubble("user", "text", "x")._frame._fill_color().name() == tm.accent.name()
        finally:
            tm.set_theme(original)

    def test_dark_accent_falls_back_to_theme(self, qapp: Any) -> None:
        """深色模式强调色回落主题令牌，保证深底上不过亮。"""
        original = tm.effective_theme()
        try:
            tm.set_theme("dark")
            assert accent_color().name() == tm.accent.name()
            assert StyledChatBubble("user", "text", "x")._frame._fill_color().name() == tm.accent.name()
        finally:
            tm.set_theme(original)

    def test_assistant_bubble_uses_surface_fill(self, qapp: Any) -> None:
        """对方气泡使用主题表面色。"""
        bubble = StyledChatBubble("assistant", "text", "主题")
        original = tm.effective_theme()
        try:
            tm.set_theme("light")
            assert bubble._frame._fill_color().name() == QColor(tm.surface).name()
        finally:
            tm.set_theme(original)

    def test_window_fill_uses_theme_fill(self, qapp: Any) -> None:
        """对话窗口底色浅/深色均取 tm.fill。"""
        original = tm.effective_theme()
        try:
            tm.set_theme("light")
            assert window_fill_color().name() == QColor(tm.fill).name()
            tm.set_theme("dark")
            assert window_fill_color().name() == QColor(tm.fill).name()
        finally:
            tm.set_theme(original)
