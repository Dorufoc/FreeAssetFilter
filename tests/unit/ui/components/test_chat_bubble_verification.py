# -*- coding: utf-8 -*-
"""独立验证（task-3）：WinUI 3 聊天气泡的几何 / 主题 / 样式合规。

角色定位：**验证者**。本文件只写断言，不修改任何产品代码；所有数字先经
独立探针实测（真实 Windows 平台 + 微软雅黑字体度量），再固化为可证伪断言。

覆盖的 8 个验证点：

1. 换行几何：对方长文本气泡在 304px 上限下必须撑满上限、正文标签宽度 =
   气泡宽 - 内边距、标签高度 >= 2 行（历史回归症状是被挤成最小宽度/裁行）；
2. 短文本自适应：我方「哈哈哈」气泡宽度 = 正文自然宽 + 左右内边距 +
   2×投影留白（±6px），且显著小于上限；
3. 不溢出：text/image/file/typing 四类气泡内任意子控件不得越界；
4. 非对称圆角：像素探针（哨兵底色法）证明 user 收窄角在右下、assistant 在左下；
5. 文件徽标：PDF/DOCX 文案、42×42、对方 DOCX 底色 #2B579A、我方为半透明白；
6. 主题切换：深/浅色下底色分别等于 tm.accent / tm.surface，几何不回退；
7. 样式注册合规：组件自身与其子树不得直写 ``setStyleSheet``（走注册中心）；
8. 回归：见交付报告（``tests/unit`` 全量 + ``test_app_stylesheet.py``）。

验证命令::

    .venv\\Scripts\\python.exe -m pytest tests/unit/ui/components/test_chat_bubble_verification.py -q
    .venv\\Scripts\\python.exe -m pytest tests/unit/ui/theme/test_app_stylesheet.py -q

注意：宿主布局必须用「横向 + stretch」的行式布局（与 ``ChatMessageRow`` 一致），
否则 QVBox 会把气泡拉宽或让高度停在过期 sizeHint 上，得到的是宿主假象而非产品行为。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

import pytest
from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFontDatabase,
    QFontMetrics,
    QImage,
    QPainter,
    QRegion,
)
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QWidget,
)

# 组件模块内部使用短路径导入（from theme import tm），要求 ui 目录在 sys.path。
_UI_ROOT: str = str(Path(__file__).resolve().parents[4] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from freeassetfilter.ui.components.styled_chat_bubble import (  # noqa: E402
    BODY_FONT_SIZE,
    IMAGE_MAX_HEIGHT,
    IMAGE_WIDTH,
    MAX_WIDTH_RATIO,
    PADDING_TEXT,
    RADIUS_BUBBLE,
    RADIUS_TAIL,
    SHADOW_MARGIN,
    ChatMessageRow,
    RowSpec,
    StyledChatBubble,
    accent_color,
    file_badge_color,
    file_badge_text,
)
from freeassetfilter.ui.theme.app_stylesheet import (  # noqa: E402
    apply_app_stylesheet,
    registered_widget_count,
    stylesheet_mode,
)
from theme import tm  # noqa: E402

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# 设计基线与固定载荷（数字来自任务冻结口径与独立探针实测）
# ---------------------------------------------------------------------------

#: 对方问候语（换行几何验证载荷，14px 下自然宽 406px）。
LONG_TEXT = "你好呀，可以给我发送文字、图片或文件试试，我会自动回复你。"
#: 我方短文本（自适应验证载荷，14px 下自然宽 42px）。
SHORT_TEXT = "哈哈哈"
#: 本轮验证下发的气泡宽度上限。
BUBBLE_CAP = 304
#: 投影留白（气泡外沿到卡片边缘）。
SHADOW = SHADOW_MARGIN
#: 正文气泡左右内边距。
PAD_X = PADDING_TEXT[0]
#: 圆角测试文本。
CORNER_TEXT = "圆角测试"
#: 哨兵底色：未绘制的像素保持该色，用于判断"填充是否覆盖某像素"。
SENTINEL = QColor(255, 0, 255)
#: 徽标边长（设计基线 42×42）。
BADGE_SIZE = 42
#: 对方 DOCX 徽标底色（HTML EXT_COLORS）。
DOCX_BLUE = (0x2B, 0x57, 0x9A)
#: 真实字体族（本机 Windows 必有；offscreen 无字体时用 real_fonts 跳过）。
REQUIRED_FONT = "Microsoft YaHei UI"


# ---------------------------------------------------------------------------
# 基础设施
# ---------------------------------------------------------------------------
def _pump(qapp: QApplication, rounds: int = 6, ms: int = 15) -> None:
    """泵事件循环若干轮，等待布局收敛与样式表重建落地。

    Args:
        qapp: 当前 QApplication。
        rounds: 轮数（每轮一次 processEvents + 一次定时器等待）。
        ms: 每轮等待毫秒数。
    """
    for _ in range(max(1, rounds)):
        qapp.processEvents(QEventLoop.AllEvents, 50)
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()


def _fonts_ready() -> bool:
    """判断当前平台是否提供真实字体（offscreen 下字体库为空）。

    Returns:
        True 表示可以做文字换行度量断言。
    """
    try:
        families = QFontDatabase.families()
    except Exception:
        return False
    return bool(families) and REQUIRED_FONT in families


class _Workspace:
    """测试宿主集合：行式布局挂载 + 布局收敛 + 应用级样式表下发。"""

    def __init__(self, qapp: QApplication) -> None:
        """初始化。

        Args:
            qapp: 会话级 QApplication。
        """
        self.qapp = qapp
        self.boxes: List[QWidget] = []

    def mount(self, widget: QWidget, width: int = 640, height: int = 260) -> QWidget:
        """把控件挂进「横向 + stretch」宿主并跑完布局与样式。

        宿主布局刻意与 ``ChatMessageRow`` 一致：stretch 吸收多余宽度，气泡只拿
        自己的 sizeHint（上限由 ``set_max_width`` 决定），垂直方向 AlignTop。

        Args:
            widget: 待挂载控件（气泡 / 消息行）。
            width: 宿主宽度。
            height: 宿主高度。

        Returns:
            宿主控件（引用由本对象持有，避免 C++ 对象被 GC）。
        """
        box = QWidget()
        box.setAttribute(Qt.WA_DontShowOnScreen, True)
        layout = QHBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(widget, 0, Qt.AlignTop)
        layout.addStretch(1)
        self.boxes.append(box)
        box.resize(width, height)
        box.show()
        self.pump()
        apply_app_stylesheet()
        self.pump(3)
        return box

    def pump(self, rounds: int = 6, ms: int = 15) -> None:
        """泵事件循环。

        Args:
            rounds: 轮数。
            ms: 每轮等待毫秒数。
        """
        _pump(self.qapp, rounds, ms)

    def dispose(self) -> None:
        """销毁全部宿主控件并泵一轮事件，避免跨用例残留。"""
        for box in self.boxes:
            box.close()
            box.deleteLater()
        self.boxes.clear()
        _pump(self.qapp, 2, 5)


@pytest.fixture
def workspace(qapp: QApplication) -> Iterator[_Workspace]:
    """提供宿主管理器，并在结束时恢复主题（tm 是进程级单例 + 全局信号）。

    Args:
        qapp: 会话级 QApplication（tests/conftest.py 提供）。

    Yields:
        _Workspace: 宿主管理器。
    """
    original_mode = tm.get_theme_mode()
    original_effective = tm.effective_theme()
    space = _Workspace(qapp)
    try:
        yield space
    finally:
        space.dispose()
        try:
            tm.set_theme_mode(original_mode)
            if tm.effective_theme() != original_effective:
                tm.set_theme(original_effective)
            _pump(qapp, 2, 5)
        except Exception:  # 主题恢复失败不掩盖真实断言结果
            pass


@pytest.fixture
def real_fonts(qapp: QApplication) -> None:
    """要求真实字体度量（offscreen 平台无字体，中文换行不可信）。

    Args:
        qapp: 会话级 QApplication。
    """
    if not _fonts_ready():
        pytest.skip("当前 Qt 平台没有可用字体（例如 offscreen），跳过字体度量相关断言")


def _body_label(bubble: StyledChatBubble) -> QLabel:
    """取出文本气泡的正文标签（唯一 QLabel 子控件）。

    Args:
        bubble: 文本气泡。

    Returns:
        正文 QLabel。
    """
    label = bubble.findChild(QLabel)
    assert label is not None, (
        f"气泡内找不到正文 QLabel（role={bubble.role}, type={bubble.message_type}）"
    )
    return label


def _find_badge(bubble: StyledChatBubble) -> QLabel:
    """取出文件气泡的 42×42 扩展名徽标。

    Args:
        bubble: 文件气泡。

    Returns:
        徽标 QLabel。
    """
    badges = [
        label
        for label in bubble.findChildren(QLabel)
        if label.width() == BADGE_SIZE and label.height() == BADGE_SIZE
    ]
    assert len(badges) == 1, (
        f"文件气泡应有且仅有 1 个 {BADGE_SIZE}×{BADGE_SIZE} 徽标，实测 {len(badges)} 个"
    )
    return badges[0]


def _render(bubble: StyledChatBubble, sentinel: QColor = SENTINEL) -> QImage:
    """把气泡及其子控件渲染到 QImage（底色置为哨兵色）。

    说明：``QWidget.render`` 在未绘制区域会落地不透明黑，直接看 alpha 不可靠；
    因此统一用哨兵底色 + RGB 距离判断"该像素是否被气泡覆盖"。

    Args:
        bubble: 目标气泡。
        sentinel: 哨兵底色。

    Returns:
        与气泡同尺寸的 QImage。
    """
    image = QImage(bubble.size(), QImage.Format_ARGB32)
    image.fill(sentinel)
    painter = QPainter(image)
    bubble.render(painter, QPoint(0, 0), QRegion(), QWidget.RenderFlag.DrawChildren)
    painter.end()
    return image


def _rgb(image: QImage, x: int, y: int) -> Tuple[int, int, int]:
    """读取像素 RGB（忽略 alpha，见 :func:`_render` 说明）。

    Args:
        image: 目标图像。
        x: 横坐标。
        y: 纵坐标。

    Returns:
        ``(r, g, b)``。
    """
    color = QColor(image.pixel(x, y))
    return color.red(), color.green(), color.blue()


def _channel_delta(first: Tuple[int, int, int], second: Tuple[int, int, int]) -> int:
    """两个 RGB 三元组的最大通道差。

    Args:
        first: 颜色 A。
        second: 颜色 B。

    Returns:
        最大通道差（0-255）。
    """
    return max(abs(first[i] - second[i]) for i in range(3))


def _corner_uncovered(
    image: QImage,
    corner: str,
    fill: QColor,
    box: int = 10,
    tolerance: int = 60,
) -> int:
    """统计四角 ``box×box`` 区域内「未被气泡填充覆盖」的像素数。

    未覆盖像素 = 与气泡底色通道差 > ``tolerance`` 的像素（哨兵底色 + 投影混色）。
    半径 8px 的圆角切掉约 12 个像素，半径 4px 的收窄角只切掉约 3 个，判别显著。

    Args:
        image: 哨兵底色渲染图。
        corner: ``"TL"`` / ``"TR"`` / ``"BL"`` / ``"BR"``。
        fill: 气泡填充色（user 为 :func:`accent_color`，其余为 tm.surface）。
        box: 角落取样边长。
        tolerance: 判定为"未覆盖"的通道差阈值。

    Returns:
        未覆盖像素数。
    """
    width, height = image.width(), image.height()
    left, top = SHADOW, SHADOW
    right, bottom = width - 1 - SHADOW, height - 1 - SHADOW
    # 起点取"填充矩形最外一圈像素"（QRectF.adjusted(-3) 后 right/bottom = w-3，
    # 对应像素索引 w-4），四角向内扫描，避免单边偏移导致计数不对称。
    starts = {
        "TL": (left, top, 1, 1),
        "TR": (right, top, -1, 1),
        "BL": (left, bottom, 1, -1),
        "BR": (right, bottom, -1, -1),
    }
    assert corner in starts, f"未知角落名：{corner}"
    start_x, start_y, step_x, step_y = starts[corner]
    fill_rgb = (fill.red(), fill.green(), fill.blue())
    uncovered = 0
    for index_x in range(box):
        for index_y in range(box):
            x = start_x + step_x * index_x
            y = start_y + step_y * index_y
            if not (0 <= x < width and 0 <= y < height):
                continue
            if _channel_delta(_rgb(image, x, y), fill_rgb) > tolerance:
                uncovered += 1
    return uncovered


def _fill_pixel(bubble: StyledChatBubble) -> Tuple[int, int, int]:
    """取气泡右侧内边距处（无文字遮挡）的填充色。

    Args:
        bubble: 目标气泡。

    Returns:
        填充色 RGB。
    """
    image = _render(bubble)
    return _rgb(image, image.width() - 7, max(0, image.height() // 2))


def _registered_rule(widget: QWidget) -> str:
    """取回该控件已注册的 QSS 片段文本（对两种下发模式均成立）。

    ``widget`` 模式（当前默认）片段原文直接落在控件自身，控件同时带
    ``fafQssId`` 注册标记；``app`` 模式片段经作用域改写后进入应用级
    样式表，需按 ``fafQssId`` 标记取回对应规则行。

    Args:
        widget: 已注册 QSS 片段的控件。

    Returns:
        片段/规则文本；未注册时返回空串。
    """
    if stylesheet_mode() == "widget":
        return widget.styleSheet() or ""
    scope = widget.property("fafQssId")
    if not scope:
        return ""
    sheet = QApplication.instance().styleSheet() or ""
    marker = f'fafQssId="{scope}"'
    return "\n".join(line for line in sheet.splitlines() if marker in line)


def _make_image_file(directory: Path) -> str:
    """生成一张临时 PNG，供图片气泡使用。

    Args:
        directory: 输出目录。

    Returns:
        PNG 绝对路径。
    """
    path = directory / "chat_bubble_probe.png"
    image = QImage(400, 300, QImage.Format_ARGB32)
    image.fill(QColor("#3366CC"))
    assert image.save(str(path), "PNG"), "临时探针图片写入失败"
    return str(path)


def _expected_body_width(bubble_cap: int) -> int:
    """气泡总宽 → 正文可用宽度。

    Args:
        bubble_cap: 气泡总宽（含投影留白）。

    Returns:
        正文可用宽度。
    """
    return bubble_cap - 2 * (PAD_X + SHADOW)


# ---------------------------------------------------------------------------
# 验证点 1：换行几何
# ---------------------------------------------------------------------------
def test_long_text_bubble_fills_cap_and_wraps_two_lines(
    workspace: _Workspace, real_fonts: None
) -> None:
    """对方长文本气泡：撑满 304px 上限、正文宽 = 上限 - 内边距、高度 ≥ 2 行。"""
    bubble = StyledChatBubble("assistant", "text", LONG_TEXT)
    workspace.mount(bubble)
    # 产品顺序：先入容器（add_row），再由容器按视口 74% 下发上限。
    bubble.set_max_width(BUBBLE_CAP)
    workspace.pump()

    assert bubble.width() == BUBBLE_CAP, (
        f"对方长文本气泡未撑到上限：实际 {bubble.width()}px，期望 {BUBBLE_CAP}px；"
        "被挤到最小宽度（历史症状 158px）即为回归"
    )

    body = _body_label(bubble)
    expected_body = _expected_body_width(BUBBLE_CAP)
    assert body.width() == expected_body, (
        f"正文标签宽度应等于气泡宽 - 左右内边距+投影（{BUBBLE_CAP}-2×{PAD_X + SHADOW}"
        f"={expected_body}px），实际 {body.width()}px"
    )

    metrics = QFontMetrics(body.font())
    line_height = metrics.lineSpacing()
    assert body.height() >= 2 * line_height - 2, (
        f"正文标签高度 {body.height()}px 不足 2 行（每行 {line_height}px），第二行会被裁掉"
    )
    wrapped_height = metrics.boundingRect(
        0,
        0,
        expected_body,
        100000,
        int(Qt.TextWordWrap | Qt.TextExpandTabs),
        LONG_TEXT,
    ).height()
    assert body.height() >= wrapped_height - 1, (
        f"正文标签高度 {body.height()}px < 换行所需 {wrapped_height}px（宽度 {expected_body}px）"
    )
    assert bubble.height() >= body.height() + 2 * (PADDING_TEXT[1] + SHADOW) - 1, (
        f"气泡高度 {bubble.height()}px 未容纳正文 {body.height()}px + 上下内边距"
        f" {2 * (PADDING_TEXT[1] + SHADOW)}px"
    )


def test_row_viewport_maps_to_74_percent_cap(
    workspace: _Workspace, real_fonts: None
) -> None:
    """容器换算：消息区视口宽 × 74% - 头像 28 - 间距 8 = 气泡上限。"""
    row = ChatMessageRow("assistant", RowSpec.text_of(LONG_TEXT))
    workspace.mount(row)
    row.set_max_width(460)
    workspace.pump()

    expected = max(
        220,
        int(460 * MAX_WIDTH_RATIO) - ChatMessageRow.AVATAR_SIZE - ChatMessageRow.GAP,
    )
    assert row.bubble.max_width() == expected, (
        f"视口 460px 时气泡上限应为 {expected}px，实际 {row.bubble.max_width()}px"
    )
    assert row.bubble.width() == expected, (
        f"长文本气泡未撑到换算上限：实际 {row.bubble.width()}px，期望 {expected}px"
    )


# ---------------------------------------------------------------------------
# 验证点 2：短文本自适应
# ---------------------------------------------------------------------------
def test_short_user_bubble_is_compact_and_matches_formula(
    workspace: _Workspace, real_fonts: None
) -> None:
    """我方「哈哈哈」气泡 = 自然宽 + 左右内边距 + 2×投影留白（±6px），且不拉满。"""
    bubble = StyledChatBubble("user", "text", SHORT_TEXT)
    workspace.mount(bubble)
    bubble.set_max_width(BUBBLE_CAP)
    workspace.pump()

    body = _body_label(bubble)
    natural = QFontMetrics(body.font()).boundingRect(
        0,
        0,
        100000,
        100000,
        int(Qt.TextSingleLine | Qt.TextExpandTabs),
        SHORT_TEXT,
    ).width()
    expected = natural + 2 * PAD_X + 2 * SHADOW
    assert bubble.width() == pytest.approx(expected, abs=6), (
        f"短文本气泡宽度应为 自然宽{natural} + 内边距{2 * PAD_X} + 投影{2 * SHADOW}"
        f" = {expected}px（±6px），实际 {bubble.width()}px"
    )
    assert bubble.width() <= BUBBLE_CAP * 0.5, (
        f"短文本气泡被拉满：实际 {bubble.width()}px / 上限 {BUBBLE_CAP}px"
    )
    assert bubble.max_width() == BUBBLE_CAP, (
        f"上限未按下发值保留：实际 {bubble.max_width()}px，期望 {BUBBLE_CAP}px"
    )


# ---------------------------------------------------------------------------
# 验证点 3：不溢出
# ---------------------------------------------------------------------------
def _overflow_case(case: str, directory: Path) -> StyledChatBubble:
    """按用例名构造待测气泡。

    Args:
        case: 用例标识。
        directory: 临时目录（图片用例用）。

    Returns:
        待测气泡。
    """
    if case == "text_long":
        return StyledChatBubble("assistant", "text", LONG_TEXT)
    if case == "text_short":
        return StyledChatBubble("user", "text", SHORT_TEXT)
    if case == "image_file":
        return StyledChatBubble("assistant", "image", image_path=_make_image_file(directory))
    if case == "image_missing":
        return StyledChatBubble("assistant", "image", image_path="")
    if case == "file_short":
        return StyledChatBubble(
            "user", "file", file_name="设计规范 v2.1.pdf", file_size="1.6 MB"
        )
    if case == "file_long":
        return StyledChatBubble(
            "assistant",
            "file",
            file_name="很长的文件名称需要截断测试非常非常长的名字 v1.0.docx",
            file_size="12.3 MB",
        )
    if case == "typing":
        return StyledChatBubble("assistant", "typing")
    raise AssertionError(f"未知用例：{case}")


@pytest.mark.parametrize(
    "case",
    ["text_long", "text_short", "image_file", "image_missing", "file_short", "file_long", "typing"],
)
def test_no_child_overflows_bubble(
    workspace: _Workspace, real_fonts: None, case: str, tmp_path: Path
) -> None:
    """任意消息类型的子控件都必须完整落在气泡矩形内（mapTo 相对坐标断言）。"""
    bubble = _overflow_case(case, tmp_path)
    workspace.mount(bubble)
    bubble.set_max_width(BUBBLE_CAP)
    workspace.pump()

    violations = []
    for child in bubble.findChildren(QWidget):
        if child.isHidden():
            continue  # 悬停复制按钮默认隐藏，不参与布局
        top_left = child.mapTo(bubble, QPoint(0, 0))
        bottom_right = child.mapTo(bubble, QPoint(child.width() - 1, child.height() - 1))
        if (
            top_left.x() < 0
            or top_left.y() < 0
            or bottom_right.x() >= bubble.width()
            or bottom_right.y() >= bubble.height()
        ):
            violations.append(
                f"{type(child).__name__} 相对矩形 "
                f"({top_left.x()},{top_left.y()})-({bottom_right.x()},{bottom_right.y()})"
            )
    assert not violations, (
        f"[{case}] 气泡 {bubble.width()}×{bubble.height()} 内出现越界子控件：{violations}"
    )
    assert bubble.width() <= BUBBLE_CAP, (
        f"[{case}] 气泡宽度 {bubble.width()}px 超过下发上限 {BUBBLE_CAP}px"
    )

    if case == "image_file":
        image_label = bubble.findChildren(QLabel)[0]
        assert image_label.width() == IMAGE_WIDTH, (
            f"图片气泡内图片宽度应为设计基线 {IMAGE_WIDTH}px，实际 {image_label.width()}px"
        )
        assert image_label.height() <= IMAGE_MAX_HEIGHT, (
            f"图片高度 {image_label.height()}px 超过上限 {IMAGE_MAX_HEIGHT}px"
        )


# ---------------------------------------------------------------------------
# 验证点 4：非对称圆角
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("role, tail", [("user", "BR"), ("assistant", "BL")])
def test_tail_corner_is_the_narrow_one(
    workspace: _Workspace, real_fonts: None, role: str, tail: str
) -> None:
    """user 收窄角在右下、assistant 在左下（像素探针：该角落被切掉的面积最小）。"""
    bubble = StyledChatBubble(role, "text", CORNER_TEXT)
    workspace.mount(bubble)
    bubble.set_max_width(BUBBLE_CAP)
    workspace.pump()
    apply_app_stylesheet()
    workspace.pump(3)

    fill = accent_color() if role == "user" else QColor(tm.surface)
    # 圆角与收窄角画在气泡底板上；气泡下方还有常驻的操作页脚（时间 + 复制），
    # 它不属于气泡矩形，探针必须只针对底板，否则底角会被下方的页脚像素覆盖。
    image = _render(bubble._frame)
    counts = {
        corner: _corner_uncovered(image, corner, fill)
        for corner in ("TL", "TR", "BL", "BR")
    }
    big_corners = [corner for corner in counts if corner != tail]

    assert counts[tail] <= 6, (
        f"[{role}] 收窄角 {tail} 的圆角切面积应接近 4px 半径（实测 ≤6 像素），"
        f"实际 {counts[tail]} 像素；四角计数 {counts}"
    )
    assert min(counts[corner] for corner in big_corners) >= 10, (
        f"[{role}] 非收窄角应为 8px 半径（切面积实测 ≥10 像素），"
        f"实际 {counts}（收窄角 {tail}）"
    )
    for corner in big_corners:
        assert counts[corner] >= counts[tail] + 5, (
            f"[{role}] 收窄角 {tail} 与 {corner} 圆角无显著差异："
            f"{counts[tail]} vs {counts[corner]}，四角计数 {counts}"
        )
    assert bubble.align_tail_direction() is (role == "user"), (
        f"[{role}] align_tail_direction() 方向错误："
        f"{bubble.align_tail_direction()}（user 应为 True）"
    )


# ---------------------------------------------------------------------------
# 验证点 5：文件徽标
# ---------------------------------------------------------------------------
def test_file_badge_text_and_docx_color(workspace: _Workspace, real_fonts: None) -> None:
    """徽标文案（PDF/DOCX，≤4 大写字）与对方 DOCX 底色 == #2B579A。"""
    assert file_badge_text("设计规范 v2.1.pdf") == "PDF", (
        f"PDF 徽标文案错误：{file_badge_text('设计规范 v2.1.pdf')!r}"
    )
    assert file_badge_text("接口文档.docx") == "DOCX", (
        f"DOCX 徽标文案错误：{file_badge_text('接口文档.docx')!r}"
    )
    assert file_badge_text("无扩展名文件") == "FILE", (
        f"无扩展名回退文案错误：{file_badge_text('无扩展名文件')!r}"
    )
    long_badge = file_badge_text("归档.verylongext")
    assert len(long_badge) <= 4 and long_badge == long_badge.upper(), (
        f"徽标文案应截断为 ≤4 个大写字符，实际 {long_badge!r}"
    )
    assert file_badge_color("接口文档.docx").name().lower() == "#2b579a", (
        f"对方 DOCX 徽标底色应为 #2B579A，实际 {file_badge_color('接口文档.docx').name()}"
    )

    bubble = StyledChatBubble(
        "assistant", "file", file_name="接口文档.docx", file_size="892 KB"
    )
    workspace.mount(bubble)
    bubble.set_max_width(BUBBLE_CAP)
    workspace.pump()
    apply_app_stylesheet()
    workspace.pump(3)

    badge = _find_badge(bubble)
    assert badge.text() == "DOCX", f"气泡内徽标文案应为 DOCX，实际 {badge.text()!r}"
    rule = _registered_rule(badge)
    assert "#2b579a" in rule.lower(), (
        f"徽标未通过注册中心拿到 #2B579A 底色，实际规则：{rule!r}"
    )
    assert f"border-radius: {RADIUS_TAIL}px" in rule, (
        f"徽标圆角应为 {RADIUS_TAIL}px，实际规则：{rule!r}"
    )

    origin = badge.mapTo(bubble, QPoint(0, 0))
    pixel = _rgb(_render(bubble), origin.x() + 21, origin.y() + 4)
    assert pixel == DOCX_BLUE, (
        f"对方 DOCX 徽标实际像素应为 {DOCX_BLUE}，实际 {pixel}"
        f"（徽标左上角 {origin.x()},{origin.y()}）"
    )


def test_user_file_badge_is_translucent_white(
    workspace: _Workspace, real_fonts: None
) -> None:
    """我方文件徽标为半透明白（QSS alpha < 1），且像素上比强调色更亮。"""
    bubble = StyledChatBubble(
        "user", "file", file_name="设计规范 v2.1.pdf", file_size="1.6 MB"
    )
    workspace.mount(bubble)
    bubble.set_max_width(BUBBLE_CAP)
    workspace.pump()
    apply_app_stylesheet()
    workspace.pump(3)

    badge = _find_badge(bubble)
    assert badge.text() == "PDF", f"我方 PDF 徽标文案应为 PDF，实际 {badge.text()!r}"
    rule = _registered_rule(badge)
    match = re.search(
        r"rgba\(\s*255\s*,\s*255\s*,\s*255\s*,\s*([0-9.]+)\s*\)", rule
    )
    assert match is not None, (
        f"我方文件徽标应为半透明白底 rgba(255,255,255,a<1)，实际规则：{rule!r}"
    )
    alpha = float(match.group(1))
    assert 0.0 < alpha < 1.0, f"我方文件徽标白色 alpha 应 <1，实际 {alpha}"

    origin = badge.mapTo(bubble, QPoint(0, 0))
    pixel = _rgb(_render(bubble), origin.x() + 21, origin.y() + 4)
    accent = accent_color().getRgb()[:3]
    assert all(pixel[index] > accent[index] for index in range(3)), (
        f"我方徽标像素 {pixel} 未比强调色 {accent} 更亮（半透明白纱未生效）"
    )


# ---------------------------------------------------------------------------
# 验证点 6：主题切换
# ---------------------------------------------------------------------------
def test_theme_switch_updates_fill_and_keeps_geometry(
    workspace: _Workspace, real_fonts: None
) -> None:
    """深浅主题下 user 气泡 = :func:`accent_color`、assistant = tm.surface，几何不回退。

    注意（验证记录）：``accent_color()`` 浅色返回参考设计蓝 ``#0078D4``（不再等于
    ``tm.accent``），与 task-3 口述基线「user 气泡 = tm.accent」不一致——该偏离已随
    报告提交给 Lead；深色模式仍严格等于 ``tm.accent``。
    """
    tm.set_theme("dark")
    workspace.pump()

    user = StyledChatBubble("user", "text", SHORT_TEXT)
    assistant = StyledChatBubble("assistant", "text", SHORT_TEXT)
    long_bubble = StyledChatBubble("assistant", "text", LONG_TEXT)
    for bubble in (user, assistant, long_bubble):
        workspace.mount(bubble)
        bubble.set_max_width(BUBBLE_CAP)
    workspace.pump()

    dark_user = _fill_pixel(user)
    dark_assistant = _fill_pixel(assistant)
    assert dark_user == tm.accent.getRgb()[:3], (
        f"深色下我方气泡底色应为 tm.accent {tm.accent.getRgb()[:3]}，实际 {dark_user}"
    )
    assert dark_user == accent_color().getRgb()[:3], (
        f"深色下 accent_color() 应回落 tm.accent {tm.accent.getRgb()[:3]}，"
        f"实际 {accent_color().getRgb()[:3]}"
    )
    assert dark_assistant == tm.surface.getRgb()[:3], (
        f"深色下对方气泡底色应为 tm.surface {tm.surface.getRgb()[:3]}，实际 {dark_assistant}"
    )
    user_width_dark = user.width()
    long_width_dark = long_bubble.width()

    tm.set_theme("light")  # 切换本身不得抛异常
    workspace.pump()
    assert tm.effective_theme() == "light", (
        f"tm.set_theme('light') 后生效主题应为 light，实际 {tm.effective_theme()}"
    )

    expected_light_user = accent_color().getRgb()[:3]
    light_user = _fill_pixel(user)
    light_assistant = _fill_pixel(assistant)
    assert light_user == expected_light_user, (
        f"浅色下我方气泡底色应为 accent_color() {expected_light_user}，实际 {light_user}"
    )
    assert light_assistant == tm.surface.getRgb()[:3], (
        f"浅色下对方气泡底色应为 tm.surface {tm.surface.getRgb()[:3]}，实际 {light_assistant}"
    )
    assert light_assistant != dark_assistant, (
        f"对方气泡底色未随主题变化（深浅都是 {dark_assistant}），主题令牌未生效"
    )
    assert light_user != dark_user, (
        f"我方气泡底色未随主题变化（深浅都是 {dark_user}），浅色参考蓝未生效"
    )

    assert long_bubble.width() == long_width_dark == BUBBLE_CAP, (
        f"主题切换后长文本气泡宽度回退：{long_width_dark} → {long_bubble.width()}，"
        f"期望 {BUBBLE_CAP}px"
    )
    assert user.width() == user_width_dark, (
        f"主题切换后短文本气泡宽度变化：{user_width_dark} → {user.width()}"
    )
    body = _body_label(long_bubble)
    metrics = QFontMetrics(body.font())
    assert body.width() == _expected_body_width(BUBBLE_CAP), (
        f"浅色下正文宽度 {body.width()}px 不等于 {_expected_body_width(BUBBLE_CAP)}px"
    )
    assert body.height() >= 2 * metrics.lineSpacing() - 2, (
        f"浅色下正文高度 {body.height()}px 不足 2 行（每行 {metrics.lineSpacing()}px）"
    )

    tm.set_theme("dark")
    workspace.pump()
    assert _fill_pixel(assistant) == dark_assistant, (
        "切回深色后对方气泡底色未还原"
    )


# ---------------------------------------------------------------------------
# 设计基线与样式注册合规
# ---------------------------------------------------------------------------
def test_design_baseline_tokens_and_font(
    workspace: _Workspace, real_fonts: None
) -> None:
    """设计基线常量与正文 14px / 图片 224px 宽度口径。"""
    assert RADIUS_BUBBLE == 8, f"气泡圆角应为 8px，实际 {RADIUS_BUBBLE}"
    assert RADIUS_TAIL == 4, f"收窄角圆角应为 4px，实际 {RADIUS_TAIL}"
    assert abs(MAX_WIDTH_RATIO - 0.74) < 1e-9, (
        f"气泡最大宽度占比应为 0.74，实际 {MAX_WIDTH_RATIO}"
    )
    assert IMAGE_WIDTH == 224, f"图片气泡内图片宽度应为 224px，实际 {IMAGE_WIDTH}"
    assert BODY_FONT_SIZE == 14, f"正文应为 14px，实际 {BODY_FONT_SIZE}"

    bubble = StyledChatBubble("assistant", "text", LONG_TEXT)
    workspace.mount(bubble)
    bubble.set_max_width(BUBBLE_CAP)
    workspace.pump()
    body = _body_label(bubble)
    assert body.font().pixelSize() == BODY_FONT_SIZE, (
        f"正文标签实际字号 {body.font().pixelSize()}px，设计基线 {BODY_FONT_SIZE}px"
    )


def test_bubble_styles_go_through_registry(
    workspace: _Workspace, real_fonts: None
) -> None:
    """组件与其子树不得直写 setStyleSheet（必须走 register_widget_qss）。"""
    before = registered_widget_count()
    bubble = StyledChatBubble(
        "assistant", "file", file_name="接口文档.docx", file_size="892 KB"
    )
    workspace.mount(bubble)
    bubble.set_max_width(BUBBLE_CAP)
    workspace.pump()
    apply_app_stylesheet()
    workspace.pump(3)

    assert registered_widget_count() > before, (
        f"构造气泡后注册表计数未增加（{before} → {registered_widget_count()}），"
        "说明样式片段没有经注册中心下发"
    )
    if stylesheet_mode() == "widget":
        # 逐控件下发：片段原文落在控件自身，控件必须带 fafQssId 注册标记，
        # 且不得出现 app 模式的作用域改写痕迹（参见 test_layouts.py 同款口径）。
        for widget in [bubble, *bubble.findChildren(QWidget)]:
            text: Optional[str] = widget.styleSheet()
            if not text:
                continue
            assert widget.property("fafQssId"), (
                f"{type(widget).__name__} 存在非注册来源的直写样式表：{text[:60]!r}"
            )
            assert "fafQssId" not in text, (
                f"{type(widget).__name__} 的片段被误按 app 模式作用域改写：{text[:60]!r}"
            )
    else:
        direct: List[str] = []
        for widget in [bubble, *bubble.findChildren(QWidget)]:
            text: Optional[str] = widget.styleSheet()
            if text:
                direct.append(f"{type(widget).__name__}: {text[:60]!r}")
        assert not direct, f"气泡子树存在直写样式表（违反 QSS 单例化约定）：{direct}"

    badge = _find_badge(bubble)
    assert _registered_rule(badge), (
        "徽标未出现在注册中心下发内容中（fafQssId 作用域规则缺失）"
    )


# ---------------------------------------------------------------------------
# 集成冒烟：聊天容器 + Demo 窗口（被测对象清单里的另两个模块）
# ---------------------------------------------------------------------------
def test_chat_shell_and_demo_render_all_message_types(
    workspace: _Workspace, real_fonts: None
) -> None:
    """Demo 整窗可构造、四类消息齐全、每条气泡上限都按视口 74% 下发。"""
    from freeassetfilter.ui.demos.styled_ai_chat_demo import (  # 局部导入：避免拖慢收集
        GREETING_TEXT,
        DemoWindow,
    )

    window = DemoWindow()
    window.setAttribute(Qt.WA_DontShowOnScreen, True)
    window.resize(520, 780)
    window.show()
    workspace.pump(12, 20)
    apply_app_stylesheet()
    workspace.pump(6, 20)

    rows = window.chat.messages.findChildren(ChatMessageRow)
    assert len(rows) >= 6, f"Demo 静态消息应有 ≥6 行，实际 {len(rows)} 行"

    viewport = window.chat.messages.viewport().width()
    expected_cap = max(
        220,
        int(viewport * MAX_WIDTH_RATIO) - ChatMessageRow.AVATAR_SIZE - ChatMessageRow.GAP,
    )
    for row in rows:
        assert row.bubble.max_width() == expected_cap, (
            f"视口 {viewport}px 时气泡上限应为 {expected_cap}px，"
            f"实际 {row.bubble.max_width()}px（role={row.role}, type={row.bubble.message_type}）"
        )

    types = {row.bubble.message_type for row in rows}
    assert {"text", "image", "file"} <= types, f"Demo 缺少消息类型：实际 {types}"

    greeting_rows = [row for row in rows if row.bubble.text == GREETING_TEXT]
    assert greeting_rows, "Demo 静态清单里找不到问候语气泡"
    greeting = greeting_rows[0].bubble
    assert greeting.width() == expected_cap, (
        f"问候语气泡未撑到上限：{greeting.width()}px / {expected_cap}px"
    )
    greeting_body = _body_label(greeting)
    greeting_metrics = QFontMetrics(greeting_body.font())
    assert greeting_body.height() >= 2 * greeting_metrics.lineSpacing() - 2, (
        f"问候语正文高度 {greeting_body.height()}px 不足 2 行"
        f"（每行 {greeting_metrics.lineSpacing()}px）"
    )

    window.close()
