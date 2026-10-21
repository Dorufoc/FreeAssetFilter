"""WinUI 3 风格的聊天气泡原子组件。

设计基线来自一份 WinUI 3 HTML 原型（对话 Demo · 多类型消息），本模块把它
翻译成 PySide6 控件：

* :class:`StyledChatBubble` —— 气泡本体（文本 / 图片 / 文件 / 正在输入）。
  背景、描边、非对称圆角与投影全部在 ``paintEvent`` 里绘制：Qt 的 QSS
  ``border-radius`` 不会裁剪普通 ``QWidget`` 子类的背景（实测四角仍为实心），
  且 QSS 无法表达"仅靠近头像一侧收窄为 4px"的圆角，因此必须自绘。
* :class:`ChatMessageRow` —— 一行消息（圆形头像 + 气泡），负责左右镜像布局。
* :class:`StyledAIAvatar` / :class:`StyledAIAvatarAccent` / :func:`make_ai_avatar_pixmap`
  —— 圆形文字头像（对方浅灰、我方强调色实底）与渐变 AI 头像。
* :class:`RowSpec` —— 消息内容描述，供消息列表按类型批量构建。

颜色全部来自 :mod:`theme` 的 ``tm`` 令牌，因此浅色/深色主题都自动适配；
子控件样式片段统一走 :func:`register_widget_qss` 注册（项目禁止组件内直接
``setStyleSheet``，有 fail-closed 单测扫描全包调用点）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from PySide6.QtCore import (
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Property,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QImageReader,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPixmap,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from freeassetfilter.ui.theme.app_stylesheet import register_widget_qss
from theme import tm

# ---------------------------------------------------------------------------
# 设计常量（对齐 HTML 原型）
# ---------------------------------------------------------------------------

#: 容器圆角（HTML ``--radius-overlay``）。
RADIUS_BUBBLE = 8
#: 靠近头像一侧收窄后的圆角（HTML ``--radius-ctrl``）。
RADIUS_TAIL = 4
#: 文本气泡内边距（HTML ``padding: 9px 13px``）。
PADDING_TEXT = (13, 9, 13, 9)
#: 图片气泡内边距（HTML ``padding: 4px``）。
PADDING_IMAGE = (4, 4, 4, 4)
#: 文件气泡内边距（HTML ``padding: 10px 14px 10px 10px``）。
PADDING_FILE = (10, 10, 14, 10)
#: "正在输入"气泡内边距（HTML ``padding: 13px 15px``）。
PADDING_TYPING = (15, 13, 15, 13)
#: 投影预留边距：自绘投影向外扩散约 2~3px，留白保证相邻气泡不被裁切。
SHADOW_MARGIN = 3
#: 图片气泡内图片的最大宽度（HTML ``width: 224px``）。
IMAGE_WIDTH = 224
#: 图片气泡内图片的最大高度。
IMAGE_MAX_HEIGHT = 240
#: 文件气泡最小宽度（HTML ``min-width: 220px``）。
FILE_MIN_WIDTH = 220
#: 文件气泡内文件名的最小可读宽度（超出部分裁切，避免把气泡撑过上限）。
FILE_NAME_MIN_WIDTH = 80
#: 气泡下方"操作页脚预留区"的高度：时间戳与复制按钮显示在这里。
#: 该区域**始终占据布局高度**（默认透明），因此悬停显示按钮时气泡不会被挤动，
#: 也不会发生任何重排。
FOOTER_HEIGHT = 20
#: 气泡底边与页脚之间的固定留白。
FOOTER_MARGIN_TOP = 2
#: 思考抽屉标题栏高度。
HEADER_HEIGHT = 22
#: 思考抽屉正文相对标题的缩进（参考设计里正文比标题更靠内）。
DRAWER_INDENT = 26
#: 思考抽屉图标尺寸。
DRAWER_ICON_SIZE = 14


class _ReasoningIcon(QWidget):
    """思考抽屉的"点阵"图标（2×2 小方点，等价参考设计的思考标记）。

    Args:
        parent: 父控件。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(DRAWER_ICON_SIZE, DRAWER_ICON_SIZE)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        # 用绑定方法而不是 lambda：``tm`` 是长生命周期单例，lambda 捕获 self 后
        # 控件销毁仍可能被调用（实测报 "Internal C++ object already deleted"）；
        # 绑定方法让 PySide6 能识别接收者并在销毁时自动断开。
        tm.theme_changed.connect(self._on_theme_changed)
        tm.colors_updated.connect(self._on_theme_changed)

    def _on_theme_changed(self, _theme: str = "") -> None:
        """主题切换后重绘。

        Args:
            _theme: 新主题名（未使用）。
        """
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        """绘制 2×2 圆点。

        Args:
            event: Qt 绘制事件。
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        color = QColor(accent_color())
        painter.setBrush(color)
        dot = 4.0
        gap = 2.0
        left = (self.width() - (dot * 2 + gap)) / 2.0
        top = (self.height() - (dot * 2 + gap)) / 2.0
        for row in range(2):
            for column in range(2):
                painter.drawEllipse(
                    QRectF(
                        left + column * (dot + gap),
                        top + row * (dot + gap),
                        dot,
                        dot,
                    )
                )
        painter.end()


class _ChevronIcon(QWidget):
    """抽屉展开箭头（收起时朝下、展开时朝上，带旋转动画）。

    Args:
        parent: 父控件。
    """

    #: 旋转动画时长（毫秒）。
    DURATION_MS = 160

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(DRAWER_ICON_SIZE, DRAWER_ICON_SIZE)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._angle = 0.0
        self._animation = QPropertyAnimation(self, b"angle", self)
        self._animation.setDuration(self.DURATION_MS)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        tm.theme_changed.connect(self._on_theme_changed)
        tm.colors_updated.connect(self._on_theme_changed)

    def _on_theme_changed(self, _theme: str = "") -> None:
        """主题切换后重绘（绑定方法便于自动断开）。

        Args:
            _theme: 新主题名（未使用）。
        """
        self.update()

    def _get_angle(self) -> float:
        """当前旋转角度。

        Returns:
            角度（度）。
        """
        return self._angle

    def _set_angle(self, value: float) -> None:
        """设置旋转角度并重绘。

        Args:
            value: 角度（度）。
        """
        self._angle = float(value)
        self.update()

    angle = Property(float, _get_angle, _set_angle)

    def set_expanded(self, expanded: bool) -> None:
        """按展开状态旋转箭头（展开朝上）。

        Args:
            expanded: 是否展开。
        """
        target = 0.0 if expanded else 180.0
        self._animation.stop()
        self._animation.setStartValue(self._angle)
        self._animation.setEndValue(target)
        self._animation.start()

    def paintEvent(self, event: QPaintEvent) -> None:
        """绘制旋转后的 V 形箭头。

        Args:
            event: Qt 绘制事件。
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.translate(self.width() / 2.0, self.height() / 2.0)
        painter.rotate(self._angle)
        pen = painter.pen()
        pen.setColor(tm.text_secondary)
        pen.setWidthF(1.3)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        half = 3.4
        painter.drawLine(QPointF(-half, -half / 2.0), QPointF(0.0, half / 2.0))
        painter.drawLine(QPointF(0.0, half / 2.0), QPointF(half, -half / 2.0))
        painter.end()
#: 气泡最大宽度占消息区视口的比例（HTML ``max-width: 74%``）。
MAX_WIDTH_RATIO = 0.74
#: 正文 14px / 行高 20px（HTML ``font-size: 14px; line-height: 20px``）。
BODY_FONT_SIZE = 14
BODY_LINE_HEIGHT = 20
#: 气泡内正文可用宽度的下限。
MIN_TEXT_WIDTH = 120

#: 文件扩展名 → 徽标底色（HTML ``EXT_COLORS``）。
EXT_COLORS = {
    "pdf": "#D93025",
    "doc": "#2B579A",
    "docx": "#2B579A",
    "xls": "#217346",
    "xlsx": "#217346",
    "ppt": "#D24726",
    "pptx": "#D24726",
    "zip": "#F0A400",
    "rar": "#F0A400",
    "png": "#7C4DFF",
    "jpg": "#7C4DFF",
    "jpeg": "#7C4DFF",
    "gif": "#7C4DFF",
    "txt": "#5D5D5D",
}


def accent_color() -> QColor:
    """当前主题的强调色（我方气泡 / 头像 / 在线圆点）。

    颜色统一来自 :attr:`ThemeManager.accent`，深浅主题与用户自定义强调色
    都会即时生效，不再在浅色模式下覆写为固定色值。

    Returns:
        强调色（QColor）。
    """
    return QColor(tm.accent)


def window_fill_color() -> QColor:
    """聊天窗口的底面颜色（标题栏 / 会话头 / 消息区 / 页脚）。

    Returns:
        :attr:`ThemeManager.fill` 对应的底色（QColor）。
    """
    return QColor(tm.fill)


def surface_fill_color() -> QColor:
    """聊天控件（输入框 / 附件按钮）的浅色白底。

    对应 HTML ``--card-trans: rgba(255,255,255,0.70)``；叠加在 Mica 上合成后
    与目标截图输入框实测的白几乎一致，浅色模式直接返回不透明白以避免
    QSS 半透明底与窗口底叠加出偏灰的观感，深色模式回落 ``tm.card_fill``。

    Returns:
        控件底色（QColor）。
    """
    if tm.is_dark_theme():
        return QColor(tm.card_fill)
    return QColor(tm.white)

#: 我方角色集合（靠右、强调蓝气泡）。
ME_ROLES = frozenset({"user"})
#: 角色 → 缺省头像文案。
ROLE_AVATARS = {
    "user": "我",
    "assistant": "对",
    "reasoning": "思",
    "system": "系",
    "tool": "工",
}


def file_extension(name: str) -> str:
    """从文件名中取出小写扩展名。

    Args:
        name: 文件名，例如 ``设计规范 v2.1.pdf``。

    Returns:
        小写扩展名；没有扩展名时返回空字符串。
    """
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[-1].strip().lower()


def file_badge_text(name: str, extension: str = "") -> str:
    """计算文件徽标文字（最多 4 个大写字符）。

    Args:
        name: 文件名。
        extension: 显式扩展名，为空时从 ``name`` 推断。

    Returns:
        徽标文字，例如 ``PDF`` / ``DOCX``。
    """
    ext = (extension or file_extension(name)).strip()
    return (ext.upper() or "FILE")[:4]


def file_badge_color(name: str, extension: str = "") -> QColor:
    """按扩展名给出对方文件徽标底色（HTML ``EXT_COLORS`` 映射）。

    Args:
        name: 文件名。
        extension: 显式扩展名，为空时从 ``name`` 推断。

    Returns:
        徽标底色，未收录的扩展名回退到强调色。
    """
    ext = (extension or file_extension(name)).strip().lower()
    return QColor(EXT_COLORS.get(ext, accent_color().name()))


def make_ai_avatar_pixmap(size: int = 40) -> QPixmap:
    """生成 AI 头像位图（强调色渐变 + 高光 + ``AI`` 字样）。

    对应 HTML ``.chat-header__avatar`` 的
    ``linear-gradient(135deg, #4CC2FF 0%, #0078D4 100%)``：这里用主题强调色的
    亮/暗两端表达，浅色与深色主题都能自然融入。

    Args:
        size: 头像边长（像素）。

    Returns:
        带透明通道的方形位图。
    """
    pixmap = QPixmap(int(size), int(size))
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    rect = QRectF(0.0, 0.0, float(size), float(size))
    path = QPainterPath()
    path.addEllipse(rect)

    painter.setClipPath(path)
    base = accent_color()
    gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
    gradient.setColorAt(0.0, base.lighter(135))
    gradient.setColorAt(1.0, base)
    painter.fillPath(path, gradient)

    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(255, 255, 255, 40))
    painter.drawEllipse(QRectF(size * 0.42, -size * 0.28, size * 0.86, size * 0.86))

    font = QFont("Microsoft YaHei UI")
    font.setPixelSize(max(9, int(round(size * 0.36))))
    font.setWeight(QFont.Weight.DemiBold)
    painter.setFont(font)
    painter.setPen(QColor(255, 255, 255))
    painter.drawText(rect, Qt.AlignCenter, "AI")
    painter.end()
    return pixmap


class StyledAIAvatar(QWidget):
    """圆形文字头像（对方浅灰底 + 深色文字）。

    Args:
        text: 头像文字。
        size: 直径（像素）。
        gradient: 是否绘制 AI 渐变头像（忽略 ``text``）。
        parent: 父控件。
    """

    def __init__(
        self,
        text: str = "",
        size: int = 28,
        gradient: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._text = text
        self._gradient = bool(gradient)
        self._pixmap: Optional[QPixmap] = None
        self.setFixedSize(int(size), int(size))
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        tm.theme_changed.connect(self._on_theme_changed)
        tm.colors_updated.connect(self._on_theme_changed)
        self._rebuild_pixmap()

    def _rebuild_pixmap(self) -> None:
        """按当前主题重建渐变头像位图（仅渐变模式）。"""
        if self._gradient:
            self._pixmap = make_ai_avatar_pixmap(self.width())

    def _on_theme_changed(self, _theme: str = "") -> None:
        """主题切换后重建位图并重绘。

        Args:
            _theme: 新主题名（未使用）。
        """
        self._rebuild_pixmap()
        self.update()

    def _font(self) -> QFont:
        """头像文字字体。

        Returns:
            与直径成比例的半粗字体。
        """
        font = QFont("Microsoft YaHei UI")
        font.setPixelSize(max(9, int(round(self.height() * 0.4))))
        font.setWeight(QFont.Weight.DemiBold)
        return font

    def _fill(self) -> QColor:
        """头像底色。

        参考设计为固定浅灰 ``#E8E8E8``（目标截图实测），深色模式使用 12%
        文字色（浅色叠层），两种模式都能与气泡形成区分。

        Returns:
            头像底色。
        """
        if tm.is_dark_theme():
            return tm.alpha_of(tm.text, 12)
        return QColor("#E8E8E8")

    def _foreground(self) -> QColor:
        """头像文字颜色。

        Returns:
            与底色对比度足够的文字色。
        """
        return tm.readable_on(self._fill())

    def paintEvent(self, event: QPaintEvent) -> None:
        """绘制圆形头像。

        Args:
            event: Qt 绘制事件。
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect())
        if self._gradient:
            if self._pixmap is None or self._pixmap.width() != self.width():
                self._rebuild_pixmap()
            if self._pixmap is not None:
                painter.drawPixmap(0, 0, self._pixmap)
            painter.end()
            return

        path = QPainterPath()
        path.addEllipse(rect)
        painter.setPen(Qt.NoPen)
        painter.fillPath(path, self._fill())
        painter.setFont(self._font())
        painter.setPen(self._foreground())
        painter.drawText(rect, Qt.AlignCenter, self._text)
        painter.end()


class StyledAIAvatarAccent(StyledAIAvatar):
    """强调色实底头像（HTML ``.msg--me .msg__avatar``）。

    Args:
        text: 头像文字。
        size: 直径（像素）。
        parent: 父控件。
    """

    def __init__(
        self, text: str = "我", size: int = 28, parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(text=text, size=size, gradient=False, parent=parent)

    def _fill(self) -> QColor:
        """强调色实底。

        Returns:
            当前模式的强调色（浅色为参考设计蓝）。
        """
        return accent_color()

    def _foreground(self) -> QColor:
        """强调色上的可读文字色。

        Returns:
            白或近黑（由 ``tm.readable_on`` 判定）。
        """
        return tm.readable_on(accent_color())


@dataclass
class RowSpec:
    """一条消息的内容描述（气泡类型 + 载荷）。

    Args:
        message_type: ``text`` / ``image`` / ``file`` / ``typing``。
        text: 文本内容。
        image_path: 图片本地路径。
        file_name: 文件名。
        file_size: 文件大小文案，例如 ``1.6 MB``。
        file_extension: 徽标文字，留空时从 ``file_name`` 推断。
    """

    message_type: str = "text"
    text: str = ""
    image_path: str = ""
    file_name: str = ""
    file_size: str = ""
    file_extension: str = ""

    @classmethod
    def text_of(cls, text: str) -> "RowSpec":
        """构建文本消息。

        Args:
            text: 文本内容。

        Returns:
            文本类型的内容描述。
        """
        return cls(message_type="text", text=text)

    @classmethod
    def image(cls, image_path: str) -> "RowSpec":
        """构建图片消息。

        Args:
            image_path: 图片本地路径。

        Returns:
            图片类型的内容描述。
        """
        return cls(message_type="image", image_path=image_path)

    @classmethod
    def file(
        cls, file_name: str, file_size: str = "", file_extension: str = ""
    ) -> "RowSpec":
        """构建文件消息。

        Args:
            file_name: 文件名。
            file_size: 大小文案。
            file_extension: 徽标文字，留空时从 ``file_name`` 推断。

        Returns:
            文件类型的内容描述。
        """
        return cls(
            message_type="file",
            file_name=file_name,
            file_size=file_size,
            file_extension=file_extension,
        )

    @classmethod
    def typing(cls) -> "RowSpec":
        """构建"正在输入"消息。

        Returns:
            typing 类型的内容描述。
        """
        return cls(message_type="typing")


class _TypingDots(QWidget):
    """三点跳动指示器（HTML ``.bubble--typing`` 的等价实现）。"""

    #: 单点动画周期（毫秒），对齐 HTML ``1.3s``。
    CYCLE_MS = 1300
    #: 三点相位差（毫秒），对应 HTML ``0.16s`` 错峰。
    OFFSET_MS = 160
    #: 点直径与点间距。
    DOT_SIZE = 5
    SPACING = 4
    #: 上浮幅度（像素）。
    LIFT = 3

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._phase = 0
        self.setFixedSize(
            self.DOT_SIZE * 3 + self.SPACING * 2,
            self.DOT_SIZE + 6,
        )
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self) -> None:
        """推进动画相位并重绘。"""
        self._phase = (self._phase + 33) % self.CYCLE_MS
        self.update()

    def _keyframe(self, offset_index: int) -> float:
        """计算某个点在当前相位下的亮度权重。

        关键帧（对齐 HTML ``typingBlink``）：0%~60% 与 100% 暗且复位，
        30% 最亮并上浮。

        Args:
            offset_index: 点的序号（0/1/2），用于错峰。

        Returns:
            0.0（最暗）~ 1.0（最亮）的权重。
        """
        progress = (
            (self._phase + offset_index * self.OFFSET_MS) % self.CYCLE_MS
        ) / self.CYCLE_MS
        if progress < 0.30:
            return progress / 0.30
        if progress < 0.60:
            return 1.0 - (progress - 0.30) / 0.30
        return 0.0

    def paintEvent(self, event: QPaintEvent) -> None:
        """按相位绘制三个不同透明度/纵向偏移的圆点。

        Args:
            event: Qt 绘制事件。
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        base = tm.mid
        for index in range(3):
            ratio = self._keyframe(index)
            color = QColor(base)
            color.setAlpha(max(0, min(255, int(round(77 + (255 - 77) * ratio)))))
            painter.setBrush(color)
            y = (self.height() - self.DOT_SIZE) / 2.0 - self.LIFT * ratio
            x = index * (self.DOT_SIZE + self.SPACING)
            painter.drawEllipse(QRectF(x, y, self.DOT_SIZE, self.DOT_SIZE))
        painter.end()


class _FadeGroup:
    """气泡下方"操作页脚"的显隐包装。

    这里刻意**不用** ``QGraphicsOpacityEffect``：实测该效果在控件 ``render``/
    ``grab`` 路径下不参与绘制（截图里页脚整块消失），跨环境不可靠。由于外层
    布局已经为页脚**常驻预留了固定高度**，直接显隐子控件不会引起任何重排——
    这也正是需求要的"不要挤开气泡"，因此普通显隐即可，且行为完全可预期。

    Args:
        widget: 承载该组控件的容器。
    """

    def __init__(self, widget: QWidget) -> None:
        self._widget = widget
        self._visible = False
        # 初始不可见：占位但不可见、也不接收鼠标（避免挡住下方消息的悬停）。
        widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        widget.hide()

    @property
    def visible(self) -> bool:
        """当前是否处于显示态。

        Returns:
            True 表示正在显示。
        """
        return self._visible

    def show(self) -> None:
        """显示页脚内容（同时放行鼠标事件）。"""
        if self._visible:
            return
        self._visible = True
        self._widget.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self._widget.show()
        # 子控件构造时父控件尚未显示，Qt 会让它们保持隐藏；父控件 show() 不会
        # 自动带上它们，必须显式 show（否则显示后仍是一片空白）。
        for child in self._widget.findChildren(QWidget):
            child.show()

    def hide(self) -> None:
        """隐藏页脚内容（同时让鼠标事件穿透）。"""
        if not self._visible:
            return
        self._visible = False
        self._widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._widget.hide()


class _WrapBodyLabel(QLabel):
    """按宽度换行的正文标签（气泡高度按 HTML 行高口径计算）。

    两件事必须自定义：

    1. ``QLabel`` 打开 ``setWordWrap(True)`` 后 ``sizeHint()`` 会退化成"能塞进
       多窄就多窄"，气泡因此永远贴着最小宽度（实测：可用 272px 时气泡只有
       158px，文字被挤成每行 7 字）。这里改为"宽度偏好 = 单行文本真实宽度，
       上限由外部下发"的语义，短文本得到紧凑气泡。
    2. 行框按 HTML 的 ``line-height: 20px`` 计算高度，而不是 ``QLabel`` 自己
       （``QFontMetrics.height()``，微软雅黑 14px 只有 18px）。这样气泡高度
       与设计稿一致（助手两行气泡 = 9 + 20 + 20 + 9 + 6 = 64px）。

    说明：绘制仍交给 ``QLabel``。曾尝试用 ``QTextLayout`` 自绘以获得 20px 的
    真实行距，但 PySide6 6.10 未导出 ``QTextLine.setLineHeight``，手工叠放
    行位置时第二行会被静默丢弃（实测只画出第一行）——那种"为 2px 牺牲正确性"
    的做法不可接受，故保留 ``QLabel`` 绘制（行距 18px，行高按 20px 计）。

    Args:
        parent: 父控件。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._max_text_width = 0
        self.setWordWrap(True)
        self.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)

    def set_max_text_width(self, width: int) -> None:
        """设置文本可用宽度上限（由气泡按自身最大宽度下发）。

        Args:
            width: 文本可用宽度（像素）。
        """
        self._max_text_width = max(0, int(width))
        self._sync_min_height()
        self.updateGeometry()

    def _sync_min_height(self) -> None:
        """把最小高度顶到 ``line-height`` 口径，避免布局把气泡压矮。

        ``sizeHint`` 给出 2×20=40px，但 ``QLabel`` 自己的 ``minimumSizeHint``
        只有 2×18=36px，``QHBoxLayout`` 会取下界 → 气泡比设计稿矮 4px。
        这里显式抬高最小高度（幂等，值不变时不触发重排）。
        """
        target = self._wrapped_height(self._measure_width())
        if self.minimumHeight() != target:
            self.setMinimumHeight(target)

    def _measure_width(self) -> int:
        """度量换行用的宽度。

        Returns:
            优先用外部下发的可用宽度，尚未下发时退回当前控件宽度。
        """
        if self._max_text_width:
            return self._max_text_width
        return max(1, self.width())

    def _natural_width(self) -> int:
        """不换行渲染整段文本所需宽度。

        Returns:
            单行宽度（像素）。
        """
        text = self.text()
        if not text:
            return 0
        flags = int(Qt.TextSingleLine | Qt.TextExpandTabs)
        return int(
            self.fontMetrics().boundingRect(0, 0, 100000, 100000, flags, text).width()
        )

    def _line_count(self, width: int) -> int:
        """估算给定宽度下的换行行数。

        逐字符累加宽度并换行（与 Qt 对 CJK 的逐字换行一致）；仅用于把
        ``line-height`` 口径换算成高度，绘制仍由 ``QLabel`` 负责，因此这里
        多算一行只会让气泡略高一点，不会裁字。

        Args:
            width: 可用宽度（像素）。

        Returns:
            行数（至少 1）。
        """
        text = self.text()
        if not text:
            return 1
        metrics = self.fontMetrics()
        lines = 1
        current = 0
        for char in text:
            if char == "\n":
                lines += 1
                current = 0
                continue
            advance = metrics.horizontalAdvance(char)
            if current > 0 and current + advance > width:
                lines += 1
                current = advance
            else:
                current += advance
        return lines

    def _wrapped_height(self, width: int) -> int:
        """给定宽度下按 ``BODY_LINE_HEIGHT`` 行框计算的高度。

        Args:
            width: 可用宽度（像素）。

        Returns:
            文本高度（像素）。
        """
        if width <= 0:
            return BODY_LINE_HEIGHT
        return max(1, self._line_count(width)) * BODY_LINE_HEIGHT

    def _effective_width(self) -> int:
        """当前生效的文本宽度。

        Qt 自身也会给控件下发 ``maximumWidth``（``QLayout`` / 样式 polish 都会
        调用），它与本控件记录的 ``_max_text_width`` 取更小者，避免任一侧的
        陈旧上限把建议宽度压在旧值上。

        Returns:
            自然宽度与两侧上限中的较小者。
        """
        natural = self._natural_width()
        limits = [limit for limit in (self._max_text_width, self.maximumWidth()) if limit]
        if limits:
            return min(natural, min(limits))
        return natural

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        """宽度取单行文本宽度（受上限约束），高度取该宽度下的固定行框高度。

        Returns:
            标签的建议尺寸。
        """
        width = self._effective_width()
        return QSize(width, self._wrapped_height(width))

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt API
        """允许被压到比自然宽度更窄（从而触发换行）。

        Returns:
            最小建议尺寸。
        """
        return QSize(1, BODY_LINE_HEIGHT)

    def resizeEvent(self, event: object) -> None:
        """宽度变化时同步最小高度并通知布局重算。

        Args:
            event: Qt 尺寸变化事件。
        """
        self._sync_min_height()
        self.updateGeometry()
        super().resizeEvent(event)  # type: ignore[arg-type]

    def setText(self, text: str) -> None:  # noqa: N802 - Qt API
        """设置文本并同步最小高度。

        Args:
            text: 新文本内容。
        """
        super().setText(text)
        self._sync_min_height()


class _ChatBubbleFrame(QWidget):
    """气泡背景层：自绘非对称圆角、描边与投影。

    Args:
        role: 角色（决定配色、圆角收窄方向与投影色）。
        parent: 父控件。
    """

    def __init__(self, role: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._role = role
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)

    @property
    def is_me(self) -> bool:
        """是否为我方（靠右、强调蓝）气泡。"""
        return self._role in ME_ROLES

    def _fill_color(self) -> QColor:
        """气泡底色。

        Returns:
            当前角色与主题下的底色。
        """
        if self._role == "user":
            return accent_color()
        if self._role == "reasoning":
            return tm.alpha_of(tm.warning, 12)
        if self._role == "tool":
            return tm.alpha_of(tm.info, 12)
        if self._role == "system":
            return tm.panel_fill
        return QColor(tm.surface)

    def _stroke_color(self) -> QColor:
        """气泡描边色（HTML ``rgba(0,0,0,0.0578)`` 一类的极浅描边）。

        Returns:
            当前角色与主题下的描边色。
        """
        if self._role == "user":
            return tm.alpha_of(tm.black, 6)
        if self._role == "reasoning":
            return tm.alpha_of(tm.warning, 40)
        if self._role == "tool":
            return tm.alpha_of(tm.info, 40)
        if self._role == "system":
            return tm.alpha_of(tm.mid, 40)
        return tm.alpha_of(tm.black, 6)

    def _shape_path(self, rect: QRectF) -> QPainterPath:
        """构建气泡圆角路径（靠近头像的底角收窄为 4px）。

        Args:
            rect: 气泡矩形（不含投影留白）。

        Returns:
            圆角矩形路径。
        """
        path = QPainterPath()
        big = float(RADIUS_BUBBLE)
        small = float(RADIUS_TAIL)
        if self.is_me:
            path.moveTo(rect.left() + big, rect.top())
            path.lineTo(rect.right() - big, rect.top())
            path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + big)
            path.lineTo(rect.right(), rect.bottom() - small)
            path.quadTo(rect.right(), rect.bottom(), rect.right() - small, rect.bottom())
            path.lineTo(rect.left() + big, rect.bottom())
            path.quadTo(rect.left(), rect.bottom(), rect.left(), rect.bottom() - big)
            path.lineTo(rect.left(), rect.top() + big)
            path.quadTo(rect.left(), rect.top(), rect.left() + big, rect.top())
        else:
            path.moveTo(rect.left() + big, rect.top())
            path.lineTo(rect.right() - big, rect.top())
            path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + big)
            path.lineTo(rect.right(), rect.bottom() - big)
            path.quadTo(rect.right(), rect.bottom(), rect.right() - big, rect.bottom())
            path.lineTo(rect.left() + small, rect.bottom())
            path.quadTo(rect.left(), rect.bottom(), rect.left(), rect.bottom() - small)
            path.lineTo(rect.left(), rect.top() + big)
            path.quadTo(rect.left(), rect.top(), rect.left() + big, rect.top())
        path.closeSubpath()
        return path

    def paintEvent(self, event: QPaintEvent) -> None:
        """绘制投影 + 圆角底 + 描边。

        投影按 HTML 的两层阴影近似：对方为 ``0 2px 4px rgba(0,0,0,0.045)``，
        我方为强调色晕染 ``0 2px 6px rgba(0,120,212,0.28)`` 的主题等价物。

        Args:
            event: Qt 绘制事件。
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        margin = float(SHADOW_MARGIN)
        rect = QRectF(self.rect()).adjusted(margin, margin, -margin, -margin)
        if rect.width() <= 0 or rect.height() <= 0:
            painter.end()
            return

        painter.setPen(Qt.NoPen)
        for spread, alpha, dy in ((2.0, 18.0, 2.0), (0.0, 10.0, 1.0)):
            glow = self._shape_path(
                rect.adjusted(-spread, -spread + dy, spread, spread + dy)
            )
            color = QColor(accent_color() if self.is_me else tm.black)
            color.setAlpha(int(alpha))
            painter.setBrush(color)
            painter.drawPath(glow)

        path = self._shape_path(rect)
        painter.setBrush(self._fill_color())
        painter.drawPath(path)

        pen = painter.pen()
        pen.setColor(self._stroke_color())
        pen.setWidth(1)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(self._shape_path(rect.adjusted(0.5, 0.5, -0.5, -0.5)))
        painter.end()


class StyledChatBubble(QFrame):
    """WinUI 3 风格消息气泡。

    通过 ``role`` 与 ``message_type`` 组合表达文本、图片、文件与"正在输入"
    四种内容；配色来自 :mod:`theme`，主题切换后自动刷新。气泡宽度由
    :meth:`set_max_width` 控制（默认按消息区视口宽度的 74% 换算）。

    Args:
        role: ``user`` / ``assistant`` / ``reasoning`` / ``system`` / ``tool``。
        message_type: ``text`` / ``image`` / ``file`` / ``typing``。
        text: 文本内容（文本、思考、流式消息）。
        image_path: 图片气泡的本地图片路径。
        file_name: 文件气泡的文件名。
        file_size: 文件气泡的大小文案。
        file_extension: 文件气泡徽标文字，留空时从 ``file_name`` 推断。
        parent: 父控件。

    Signals:
        copied: 用户点击"复制"时发出，携带完整文本。
    """

    copied = Signal(str)
    #: 角色 → 头像文案。
    ROLE_LABELS = dict(ROLE_AVATARS)
    #: 支持的消息类型。
    MESSAGE_TYPES = {"text", "image", "file", "typing"}

    def __init__(
        self,
        role: str = "assistant",
        message_type: str = "text",
        text: str = "",
        *,
        image_path: str = "",
        file_name: str = "",
        file_size: str = "",
        file_extension: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.role = role if role in self.ROLE_LABELS else "assistant"
        self.message_type = (
            message_type if message_type in self.MESSAGE_TYPES else "text"
        )
        self._text = text
        self._time_text = ""
        self._streaming = False
        self._max_width = 480
        #: 硬下限（内容 minimumSizeHint），避免气泡被压得比内容还窄。
        self._floor = 0
        self._styled: List[Tuple[QWidget, Callable[[], str], str]] = []
        self._file_name = file_name
        self._file_extension = file_extension
        self._body: Optional[_WrapBodyLabel] = None
        self._image_label: Optional[QLabel] = None
        self._typing: Optional[_TypingDots] = None
        self._copy: Optional[QPushButton] = None
        self._footer: Optional[_FadeGroup] = None
        self._footer_time: Optional[QLabel] = None

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._frame = _ChatBubbleFrame(self.role, self)
        outer.addWidget(self._frame)

        padding = {
            "image": PADDING_IMAGE,
            "file": PADDING_FILE,
            "typing": PADDING_TYPING,
        }.get(self.message_type, PADDING_TEXT)
        #: 页脚左右内边距：与气泡正文内边距对齐，使时间/复制贴着气泡外侧边缘。
        self._footer_padding = max(4, padding[0])
        margin = SHADOW_MARGIN
        self._frame_layout = QVBoxLayout(self._frame)
        self._frame_layout.setContentsMargins(
            padding[0] + margin,
            padding[1] + margin,
            padding[2] + margin,
            padding[3] + margin,
        )
        self._frame_layout.setSpacing(0)
        self._build_content(image_path, file_name, file_size, file_extension)
        # 气泡下方的常驻操作页脚：只在悬停时淡入，绝不参与气泡尺寸计算。
        # 页脚用**显式定位**放在气泡下方，而不是交给布局：短气泡时页脚比气泡宽
        # （要放下"时间 + 复制"），若让它参与布局会把气泡撑宽并破坏收窄角的像素
        # 探针，因此这里只让外层布局为它预留固定高度，水平位置在
        # ``_position_footer`` 里按气泡宽度算。
        self._footer_spacer = QWidget(self)
        self._footer_spacer.setFixedHeight(FOOTER_MARGIN_TOP + FOOTER_HEIGHT)
        self._footer_spacer.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        outer.addWidget(self._footer_spacer)
        self._build_footer(padding)

        self.setAttribute(Qt.WA_Hover, True)
        tm.theme_changed.connect(self._on_theme_changed)
        tm.colors_updated.connect(self._on_theme_changed)
        self._refresh_styles()
        self.set_max_width(self._max_width)

    # ------------------------------------------------------------------
    # 内容构建
    # ------------------------------------------------------------------

    def _build_content(
        self,
        image_path: str,
        file_name: str,
        file_size: str,
        file_extension: str,
    ) -> None:
        """按消息类型装配气泡内容。

        Args:
            image_path: 图片路径。
            file_name: 文件名。
            file_size: 大小文案。
            file_extension: 徽标文字。
        """
        self._content: Optional[QWidget] = None
        if self.message_type == "file":
            self._content = self._build_file_content(file_name, file_size, file_extension)
            self._frame_layout.addWidget(self._content)
        elif self.message_type == "image":
            self._content = self._build_image_content(image_path)
            self._frame_layout.addWidget(self._content)
        elif self.message_type == "typing":
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(0)
            self._typing = _TypingDots(self._frame)
            row.addStretch(1)
            row.addWidget(self._typing)
            row.addStretch(1)
            self._frame_layout.addLayout(row)
        else:
            self._content = self._build_text_content()
            self._frame_layout.addWidget(self._content)

    def _build_text_content(self) -> QWidget:
        """构建文本内容区（自动换行）。

        复制按钮不在这里，而是在气泡下方的常驻页脚预留区（见
        :meth:`_build_footer`），避免它参与气泡高度计算。

        Returns:
            内容区控件。
        """
        host = QWidget(self._frame)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._body = _WrapBodyLabel(host)
        self._body.setText(self._display_text())
        self._body.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self._body.setFont(self._body_font())
        layout.addWidget(self._body)
        return host

    def _build_footer(self, padding: Tuple[int, int, int, int]) -> QWidget:
        """构建气泡下方的操作页脚（时间 + 复制）。

        设计要求：鼠标移到气泡区域时，复制按钮显示在**气泡下方**，且不能让
        气泡发生任何重排。做法是页脚区**常驻**并固定高度（内容初始透明），
        悬停只切换透明度，因此几何自始至终不变。

        页脚宽度与气泡等宽、水平位置由 :meth:`_position_footer` 显式指定，
        因此它不参与气泡的尺寸计算，也不会把气泡撑宽。

        Args:
            padding: 气泡内容内边距，用于让页脚与气泡正文左右对齐。

        Returns:
            页脚控件。
        """
        wrapper = QWidget(self)
        wrapper.setFixedHeight(FOOTER_HEIGHT)
        inner = QHBoxLayout(wrapper)
        inner.setContentsMargins(
            self._footer_padding, 0, self._footer_padding, 0
        )
        inner.setSpacing(6)

        self._footer_time = QLabel("", wrapper)
        self._footer_time.setFont(self._footer_font())
        self._footer_time.setAlignment(Qt.AlignVCenter)
        self._footer_time.setFixedHeight(FOOTER_HEIGHT - 2)
        # 时间文本可长可短，宽度跟着内容走但不可被 stretch 压缩。
        self._footer_time.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._footer_time.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self._copy = QPushButton("复制", wrapper)
        self._copy.setCursor(Qt.PointingHandCursor)
        self._copy.setFixedHeight(FOOTER_HEIGHT - 2)
        self._copy.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self._copy.clicked.connect(lambda: self.copied.emit(self._text))

        # 时间戳在前、复制按钮在后（与参考截图一致：图标落在最外侧）。
        # stretch 必须放在最前：尾部若留 stretch，会把时间标签压成几像素
        # （实测 29px 被挤到 6px）。
        inner.addStretch(1)
        inner.addWidget(self._footer_time)
        inner.addWidget(self._copy)

        self._footer = _FadeGroup(wrapper)
        self._styled.extend(
            (
                (self._footer_time, self._footer_time_qss, ""),
                (self._copy, self._copy_qss, ""),
            )
        )
        return wrapper

    def _position_footer(self) -> None:
        """把页脚摆到气泡正下方（与气泡等宽，不超出气泡水平范围）。

        页脚宽度、水平位置全部显式指定：它不参与气泡的尺寸计算，因此不会把
        气泡撑宽，也不会侵入对面头像区。
        """
        footer = self._footer
        if footer is None:
            return
        wrapper = footer._widget
        width = max(self.width(), 1)
        wrapper.setFixedSize(width, FOOTER_HEIGHT)
        wrapper.move(0, max(0, self._frame.height() + FOOTER_MARGIN_TOP))
        # 页脚是子控件且宽度由外部钉死，必须显式激活其布局，否则内部的时间/
        # 复制仍保持构造时的默认几何（实测停留在 100×30，并被判为越界）。
        layout = wrapper.layout()
        if layout is not None:
            layout.activate()
        wrapper.raise_()

    def _build_file_content(
        self, file_name: str, file_size: str, file_extension: str
    ) -> QWidget:
        """构建文件内容区（扩展名徽标 + 名称 + 大小）。

        Args:
            file_name: 文件名。
            file_size: 大小文案。
            file_extension: 徽标文字。

        Returns:
            内容区控件。
        """
        host = QWidget(self._frame)
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(11)

        badge = QLabel(file_badge_text(file_name, file_extension), host)
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedSize(42, 42)
        badge.setFont(self._badge_font())

        info = QWidget(host)
        column = QVBoxLayout(info)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(3)
        name = QLabel(file_name or "未命名文件", info)
        name.setFont(self._file_name_font())
        # 文件名必须可压缩：QLabel 的 minimumSizeHint 会取整段文本宽度，若不限死
        # 就会把气泡撑到比上限还宽（实测长文件名时气泡 449px > 上限 304px），
        # 从而越出消息区。这里给出最小可读宽度交给省略号/裁切处理。
        name.setMinimumWidth(FILE_NAME_MIN_WIDTH)
        name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        meta = QLabel(file_size, info)
        meta.setFont(self._meta_font())
        column.addWidget(name)
        column.addWidget(meta)

        row.addWidget(badge)
        row.addWidget(info, 1)
        self._styled.extend(
            (
                (badge, self._badge_qss, ""),
                (name, self._file_name_qss, ""),
                (meta, self._file_meta_qss, ""),
            )
        )
        return host

    def _build_image_content(self, image_path: str) -> QWidget:
        """构建图片内容区（按 224px 宽等比缩放）。

        Args:
            image_path: 图片路径。

        Returns:
            内容区控件。
        """
        host = QWidget(self._frame)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._image_label = QLabel(host)
        self._image_label.setAlignment(Qt.AlignCenter)
        self._image_label.setFixedSize(IMAGE_WIDTH, 150)
        self._load_image(image_path)
        layout.addWidget(self._image_label)
        self._styled.append((self._image_label, self._image_qss, ""))
        return host

    def _load_image(self, image_path: str) -> None:
        """加载并按 224px 宽度等比缩放图片（自动应用 EXIF 方向）。

        Args:
            image_path: 图片路径；为空或不可读时显示占位块。
        """
        label = self._image_label
        if label is None:
            return
        pixmap = QPixmap()
        if image_path:
            reader = QImageReader(image_path)
            reader.setAutoTransform(True)
            image = reader.read()
            if not image.isNull():
                pixmap = QPixmap.fromImage(image)
        if pixmap.isNull():
            # 缺图兜底：浅强调色块，避免气泡塌陷成一条线。
            pixmap = QPixmap(IMAGE_WIDTH, 120)
            pixmap.fill(tm.alpha_of(accent_color(), 40))
        scaled = pixmap.scaled(
            IMAGE_WIDTH,
            IMAGE_MAX_HEIGHT,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        label.setFixedSize(scaled.size())
        label.setPixmap(scaled)

    # ------------------------------------------------------------------
    # 字体
    # ------------------------------------------------------------------

    @staticmethod
    def _ui_font() -> QFont:
        """基础 UI 字体。

        Returns:
            微软雅黑字体对象。
        """
        return QFont("Microsoft YaHei UI")

    def _body_font(self) -> QFont:
        """正文 14px 字体。

        Returns:
            字体对象。
        """
        font = self._ui_font()
        font.setPixelSize(BODY_FONT_SIZE)
        return font

    def _badge_font(self) -> QFont:
        """文件徽标字体（10px / 粗体 / 加字距）。

        Returns:
            字体对象。
        """
        font = self._ui_font()
        font.setPixelSize(10)
        font.setWeight(QFont.Weight.Bold)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.4)
        return font

    def _file_name_font(self) -> QFont:
        """文件名 13.5px 字体。

        Returns:
            字体对象。
        """
        font = self._ui_font()
        font.setPixelSize(14)
        font.setWeight(QFont.Weight.DemiBold)
        return font

    def _meta_font(self) -> QFont:
        """文件大小 11.5px 字体。

        Returns:
            字体对象。
        """
        font = self._ui_font()
        font.setPixelSize(11)
        return font

    def _footer_font(self) -> QFont:
        """页脚时间戳字体（11px，与参考截图的时间字号一致）。

        Returns:
            字体对象。
        """
        font = self._ui_font()
        font.setPixelSize(11)
        return font

    # ------------------------------------------------------------------
    # 主题与样式片段
    # ------------------------------------------------------------------

    def _text_color(self) -> QColor:
        """正文颜色（我方用强调色上的可读色，其余用主题正文色）。

        Returns:
            正文颜色。
        """
        if self.role == "user":
            return tm.readable_on(accent_color())
        return tm.text

    def _meta_color(self) -> QColor:
        """次要文字颜色（我方为 78% 透明白）。

        Returns:
            次要文字颜色。
        """
        if self.role == "user":
            return tm.alpha_of(tm.white, 78)
        return tm.text_secondary

    def _body_qss(self) -> str:
        """正文标签样式片段。

        Returns:
            QSS 文本。
        """
        return (
            f"QLabel {{ background: transparent;"
            f" color: {tm.qss_color(self._text_color())}; }}"
        )

    def _footer_time_qss(self) -> str:
        """页脚时间戳样式片段（次要文字色、11px）。

        Returns:
            QSS 文本。
        """
        return (
            f"QLabel {{ background: transparent;"
            f" color: {tm.qss_color(tm.text_secondary)}; font-size: 11px; }}"
        )

    def _copy_qss(self) -> str:
        """悬停复制按钮样式片段。

        Returns:
            QSS 文本。
        """
        if self.role == "user":
            background = tm.qss_color(tm.alpha_of(tm.white, 22))
            color = tm.white.name()
            hover = tm.qss_color(tm.alpha_of(tm.white, 34))
        else:
            background = tm.qss_color(tm.alpha_of(tm.text, 6))
            color = tm.text_secondary.name()
            hover = tm.qss_color(tm.alpha_of(tm.text, 12))
        return (
            f"QPushButton {{ background: {background}; color: {color};"
            f" border: none; border-radius: 4px; padding: 0 6px;"
            f" font-size: 10px; }}"
            f"QPushButton:hover {{ background: {hover}; }}"
        )

    def _badge_qss(self) -> str:
        """文件徽标样式片段（我方半透明白块，对方按扩展名着色）。

        Returns:
            QSS 文本。
        """
        if self.role == "user":
            background = tm.qss_color(tm.alpha_of(tm.white, 22))
            color = tm.white.name()
        else:
            badge = file_badge_color(self._file_name, self._file_extension)
            background = badge.name()
            color = tm.readable_on(badge).name()
        return (
            f"QLabel {{ background: {background}; color: {color};"
            f" border-radius: {RADIUS_TAIL}px; }}"
        )

    def _file_name_qss(self) -> str:
        """文件名样式片段。

        Returns:
            QSS 文本。
        """
        return (
            f"QLabel {{ background: transparent;"
            f" color: {self._text_color().name()}; }}"
        )

    def _file_meta_qss(self) -> str:
        """文件大小样式片段。

        Returns:
            QSS 文本。
        """
        return (
            f"QLabel {{ background: transparent;"
            f" color: {tm.qss_color(self._meta_color())}; }}"
        )

    def _image_qss(self) -> str:
        """图片圆角样式片段（HTML ``border-radius: 5px``）。

        Returns:
            QSS 文本。
        """
        return "QLabel { background: transparent; }"

    def _refresh_styles(self) -> None:
        """把子控件样式片段（重新）注册到应用级样式表。

        每个片段由回调渲染，因此主题切换后重新调用本方法即可拿到新配色；
        项目禁止组件内直接 ``setStyleSheet``，一律走注册中心。
        """
        styled: List[Tuple[QWidget, Callable[[], str], str]] = []
        if self._body is not None:
            styled.append((self._body, self._body_qss, ""))
        styled.extend(self._styled)
        refreshed: List[Tuple[QWidget, Callable[[], str], str]] = []
        for widget, renderer, old_id in styled:
            if old_id:
                register_widget_qss(widget, "")
            refreshed.append(
                (widget, renderer, register_widget_qss(widget, renderer()))
            )
        self._styled = refreshed

    def _on_theme_changed(self, _theme: str = "") -> None:
        """主题切换：刷新子控件样式并重绘自绘部分。

        Args:
            _theme: 新主题名（未使用）。
        """
        self._refresh_styles()
        self.update()
        self._frame.update()

    # ------------------------------------------------------------------
    # 公开 API（与既有调用方保持兼容）
    # ------------------------------------------------------------------

    @property
    def text(self) -> str:
        """当前文本内容。"""
        return self._text

    def _display_text(self) -> str:
        """正文显示文本（流式时追加光标）。

        Returns:
            显示文本。
        """
        return self._text + ("▌" if self._streaming else "")

    def set_text(self, text: str) -> None:
        """替换文本内容。

        Args:
            text: 新的文本内容。
        """
        self._text = text
        if self._body is not None:
            self._body.setText(self._display_text())
        self.updateGeometry()

    def append_text(self, text: str) -> None:
        """在现有文本后追加内容（流式输出）。

        Args:
            text: 追加的文本片段。
        """
        self.set_text(self._text + text)

    def set_streaming(self, streaming: bool) -> None:
        """切换流式光标显示。

        Args:
            streaming: 是否处于流式输出中。
        """
        self._streaming = bool(streaming)
        if self._body is not None:
            self._body.setText(self._display_text())

    def _body_available_width(self, outer_width: int) -> int:
        """给定气泡总宽时正文可用的宽度。

        Args:
            outer_width: 气泡总宽（含投影留白，像素）。

        Returns:
            正文可用宽度（像素）。
        """
        margins = self._frame_layout.contentsMargins()
        return max(MIN_TEXT_WIDTH, int(outer_width) - margins.left() - margins.right())

    def set_max_width(self, width: int) -> None:
        """设置气泡（含投影留白）的最大宽度。

        同时把可用宽度下发给正文标签，使文字达到上限后正确换行，而不是把
        气泡继续撑宽。改上限后本控件会自行失效尺寸缓存（见 :meth:`sizeHint`）。

        Args:
            width: 最大宽度（像素）；文件气泡不会小于 ``FILE_MIN_WIDTH``。
        """
        outer = max(MIN_TEXT_WIDTH + SHADOW_MARGIN * 2, int(width))
        self._max_width = outer
        # 顺序很重要：必须先下发正文换行上限，再据此收敛自身宽度；反过来的话
        # _desired_width() 会读到旧的换行宽度，把气泡钉在旧尺寸上（实测「宽→窄→宽」
        # 之后不再长大）。
        if self._body is not None:
            self._body.set_max_text_width(self._body_available_width(outer))
        if self.message_type == "file":
            self._frame.setMinimumWidth(min(FILE_MIN_WIDTH, outer - SHADOW_MARGIN * 2))
        # 下限 = 内容真实最小宽度；文件气泡另按 HTML ``min-width: 220px`` 兜底。
        # 不能把下限等同于上限，否则短消息会被拉满。
        self._floor = self._content_min_width()
        if self.message_type == "file":
            self._floor = max(self._floor, min(FILE_MIN_WIDTH, outer))
        self._sync_fixed_width()
        self._position_footer()
        self.updateGeometry()

    def _content_min_width(self) -> int:
        """气泡在"内容完整可见"前提下的最小宽度。

        优先用 ``QLayout.minimumSize()``：它汇总了每个子控件的
        ``minimumSizeHint``/``sizeHint``/``minimumWidth``，比自己逐项相加可靠
        （实测三点指示器的 ``sizeHint`` 为无效的 ``-1``，逐项相加会算出过小的值，
        导致指示器越出气泡边界）。

        Returns:
            最小宽度（像素）。
        """
        layout = self._frame.layout()
        if layout is not None:
            minimum = layout.minimumSize().width()
            if minimum > 0:
                return minimum
        marges = self._frame_layout.contentsMargins()
        return MIN_TEXT_WIDTH + marges.left() + marges.right()

    def _sync_fixed_width(self) -> None:
        """把气泡宽度钉死在"内容自然宽（受上限约束）"上。

        只下发 ``maximumWidth`` 不够：``QLabel`` 的换行宽度变化不会可靠地
        逐级刷新父布局，实测「宽→窄→宽」后气泡会卡在窄值不再长大。这里把
        期望宽度算出来直接设为固定宽度（同时保留 ``maximumWidth`` 语义），
        让几何不再依赖 Qt 的滞后传播。
        """
        desired = self._desired_width()
        if self.width() != desired or self.minimumWidth() != desired:
            self.setFixedWidth(desired)

    def _desired_width(self) -> int:
        """气泡期望宽度（含投影留白与内边距，已受上限约束）。

        Returns:
            期望宽度（像素）。
        """
        margins = self._frame_layout.contentsMargins()
        chrome = margins.left() + margins.right()
        interior = 0
        if self._body is not None:
            interior = self._body.sizeHint().width()
        elif self._content is not None:
            interior = self._content.sizeHint().width()
        if self.message_type == "file" and interior > 0:
            interior = max(interior, min(FILE_MIN_WIDTH, self._max_width - chrome))
        desired = min(self._max_width, interior + chrome)
        return max(desired, getattr(self, "_floor", 0))

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        """返回权威的建议尺寸（宽=期望宽度，高=内容高 + 内边距）。

        覆盖 ``QLabel``/``QLayout`` 的滞后缓存：高度同样按"内容自然高 + 上下
        内边距"直接给出，避免沿用旧的布局估算导致气泡高度不跟随宽度变化。

        Returns:
            建议尺寸。
        """
        inner = super().sizeHint()
        return QSize(self._desired_width(), inner.height())

    def max_width(self) -> int:
        """当前最大宽度（含投影留白）。

        Returns:
            最大宽度像素值。
        """
        return self._max_width

    def setMaximumWidth(self, width: int) -> None:  # noqa: N802 - Qt API
        """把宽度上限同步到正文标签（Qt/样式引擎会在 polish 时调用）。

        Qt 在应用样式表等时机通过 ``setMaximumWidth`` 下发宽度上限，若此处
        不同步正文的换行宽度，气泡会失去正确的换行信息。

        Args:
            width: 最大宽度（像素）。
        """
        if self._body is not None:
            self._body.set_max_text_width(self._body_available_width(width))
        super().setMaximumWidth(int(width))

    def align_tail_direction(self) -> bool:
        """气泡收窄角是否在右侧（我方）。

        Returns:
            True 表示右下角收窄。
        """
        return self.role in ME_ROLES

    def set_time_text(self, text: str) -> None:
        """设置页脚时间戳文案（留空则不显示时间）。

        Args:
            text: 时间文案，例如 ``23:32``。
        """
        self._time_text = text
        if self._footer_time is not None:
            self._footer_time.setText(text)
            self._footer_time.setFixedWidth(
                max(
                    0,
                    self._footer_time.fontMetrics().horizontalAdvance(text),
                )
            )
            self._position_footer()

    @property
    def time_text(self) -> str:
        """页脚时间戳文案。"""
        return self._time_text

    def _set_footer_visible(self, visible: bool) -> None:
        """切换页脚（时间 + 复制）的显示状态。

        只改变透明度，不改变任何几何：页脚区始终占据
        ``FOOTER_MARGIN_TOP + FOOTER_HEIGHT`` 的高度。

        Args:
            visible: True 淡入，False 淡出。
        """
        if self._footer is None:
            return
        if visible and not self._text:
            return
        self._position_footer()
        if visible:
            self._footer.show()
        else:
            self._footer.hide()

    def resizeEvent(self, event: object) -> None:
        """几何变化后重新摆放页脚。

        Args:
            event: Qt 尺寸变化事件。
        """
        self._position_footer()
        super().resizeEvent(event)  # type: ignore[arg-type]

    def _cursor_inside(self) -> bool:
        """鼠标是否仍停留在气泡（含页脚）范围内。

        Returns:
            True 表示在范围内。
        """
        cursor = self.mapFromGlobal(self.cursor().pos())
        return self.rect().contains(cursor)

    def enterEvent(self, event: object) -> None:
        """悬停时淡入气泡下方的操作页脚（时间 + 复制）。

        Args:
            event: Qt 进入事件。
        """
        self._set_footer_visible(True)
        super().enterEvent(event)  # type: ignore[arg-type]

    def leaveEvent(self, event: object) -> None:
        """离开气泡时淡出页脚。

        进入页脚内的按钮同样会触发本事件，因此这里用光标实际位置判断，避免
        鼠标移到复制按钮上时页脚被误隐藏。

        Args:
            event: Qt 离开事件。
        """
        if not self._cursor_inside():
            self._set_footer_visible(False)
        super().leaveEvent(event)  # type: ignore[arg-type]


class ChatMessageRow(QWidget):
    """一行消息：圆形头像 + 气泡（我方靠右镜像，底对齐）。

    Args:
        role: ``user`` / ``assistant`` / ``reasoning`` / ``system`` / ``tool``。
        spec: 内容描述；为 None 时退化为纯文本消息。
        text: 便捷文本参数（``spec`` 为空时使用）。
        avatar: 自定义头像控件；缺省时按角色生成。
        parent: 父控件。
    """

    #: 头像直径（HTML ``.msg__avatar`` 28px）。
    AVATAR_SIZE = 28
    #: 头像与气泡间距（HTML ``gap: 8px``）。
    GAP = 8
    #: 消息区左右内边距（HTML ``.chat-body`` padding 18px）。
    SIDE_PADDING = 18

    def __init__(
        self,
        role: str = "assistant",
        spec: Optional[RowSpec] = None,
        text: str = "",
        *,
        avatar: Optional[QWidget] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.role = role if role in ROLE_AVATARS else "assistant"
        data = spec if spec is not None else RowSpec.text_of(text)

        self._drawer: Optional[StyledReasoningDrawer] = None

        # 消息行是纵向两段："思考抽屉（可选）" + "头像 + 气泡"。抽屉因此与气泡
        # 处于同一列，展开时向下推开气泡，而不是另起一个气泡占位。
        self._column = QVBoxLayout(self)
        self._column.setContentsMargins(0, 0, 0, 0)
        self._column.setSpacing(2)

        self._avatar = avatar or self._default_avatar()
        # 气泡下方常驻一段不可见的操作页脚（``FOOTER_MARGIN_TOP + FOOTER_HEIGHT``），
        # 若头像直接与气泡底对齐会被这段页脚顶低 22px，看起来像浮在气泡下方。
        # 这里用带底部内边距的容器托住头像，让头像底边与**可见气泡**底边齐平。
        self._avatar_holder = QWidget(self)
        avatar_layout = QVBoxLayout(self._avatar_holder)
        avatar_layout.setContentsMargins(
            0, 0, 0, FOOTER_MARGIN_TOP + FOOTER_HEIGHT
        )
        avatar_layout.setSpacing(0)
        avatar_layout.addWidget(self._avatar)
        self._avatar_holder.setSizePolicy(
            QSizePolicy.Fixed, QSizePolicy.Maximum
        )
        self._bubble = StyledChatBubble(
            self.role,
            data.message_type,
            data.text if data.text else text,
            image_path=data.image_path,
            file_name=data.file_name,
            file_size=data.file_size,
            file_extension=data.file_extension,
            parent=self,
        )

        badge_row = QWidget(self)
        layout = QHBoxLayout(badge_row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(self.GAP)
        # 关键的左右分工：**对侧放自适应空白，头像紧贴气泡**。若两侧都用
        # stretch（早期实现），剩余空间会被对等分给左右，气泡只能长到半宽、
        # 永远伸不到对面区域；头像侧的固定空档已由 ``layout.setSpacing(GAP)``
        # 表达，不能再额外 ``addSpacing``（否则头像与气泡之间会多出一整段
        # 头像宽度的空隙）。
        if self.is_me:
            layout.addStretch(1)
            layout.addWidget(self._bubble, 0, Qt.AlignBottom)
            layout.addWidget(self._avatar_holder, 0, Qt.AlignBottom)
        else:
            layout.addWidget(self._avatar_holder, 0, Qt.AlignBottom)
            layout.addWidget(self._bubble, 0, Qt.AlignBottom)
            layout.addStretch(1)
        self._column.addWidget(badge_row)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

    @property
    def is_me(self) -> bool:
        """是否为我方（靠右）消息行。"""
        return self.role in ME_ROLES

    @property
    def bubble(self) -> StyledChatBubble:
        """本行气泡控件。"""
        return self._bubble

    @property
    def avatar(self) -> QWidget:
        """本行头像控件。"""
        return self._avatar

    def _default_avatar(self) -> QWidget:
        """按角色生成缺省头像。

        Returns:
            我方为强调色实底头像，其余为浅灰文字头像。
        """
        label = ROLE_AVATARS.get(self.role, "对")
        if self.is_me:
            return StyledAIAvatarAccent(label, self.AVATAR_SIZE)
        return StyledAIAvatar(label, self.AVATAR_SIZE)

    def set_max_width(self, viewport_width: int) -> None:
        """按消息区视口宽度设置气泡最大宽度。

        换算规则对齐 HTML：气泡上限 = 视口宽 × 74%，再扣除头像直径与间距
        （头像侧固定空档），因此气泡可以往对侧一直延伸，但不会压到对面头像。

        必须显式通知三层几何失效：``QHBoxLayout`` 的 stretch 不会因为子控件
        ``maximumWidth`` 变大就自动把气泡放大（实测：宽→窄→宽 后气泡卡在窄值），
        所以气泡、本行、以及本行的父布局都要重新走一遍尺寸协商。

        Args:
            viewport_width: 消息区视口宽度（像素）。
        """
        available = int(int(viewport_width) * MAX_WIDTH_RATIO)
        inner = available - self.AVATAR_SIZE - self.GAP
        # 下限取"可用空间"与硬下限中的较小者：视口极窄时宁可让气泡被裁，也不要
        # 让它比视口还宽而溢出（硬下限 226 只在视口 < 约 340px 时才触及）。
        floor = min(FILE_MIN_WIDTH, max(MIN_TEXT_WIDTH, inner))
        self._bubble.set_max_width(max(floor, inner))
        self._bubble.updateGeometry()
        if self._drawer is not None:
            self._drawer.setMaximumWidth(max(floor, inner) - SHADOW_MARGIN * 2)
        self.updateGeometry()
        parent = self.parentWidget()
        if parent is not None and parent.layout() is not None:
            parent.layout().invalidate()
            parent.layout().activate()

    # ------------------------------------------------------------------
    # 思考抽屉
    # ------------------------------------------------------------------

    @property
    def drawer(self) -> Optional["StyledReasoningDrawer"]:
        """本行的思考抽屉；未创建时为 None。"""
        return self._drawer

    def ensure_drawer(self) -> "StyledReasoningDrawer":
        """按需创建并返回本行的思考抽屉（位于气泡上方）。

        思考内容不占用独立气泡：抽屉挂在气泡**同一列**的上方，展开时向下推开
        气泡，收起时只剩标题栏；宽度上限与气泡一致（同一列），因此不会横跨到
        对面头像区域。

        Returns:
            本行的思考抽屉。
        """
        if self._drawer is not None:
            return self._drawer
        drawer = StyledReasoningDrawer(self)
        drawer.setMaximumWidth(max(120, self._bubble.max_width() - SHADOW_MARGIN * 2))
        if self.is_me:
            self._column.insertWidget(0, drawer, 0, Qt.AlignRight)
        else:
            self._column.insertWidget(0, drawer, 0, Qt.AlignLeft)
        self._drawer = drawer
        self.updateGeometry()
        return drawer


class _SlideBody:
    """可折叠内容区的展开/收起动画（驱动 ``maximumHeight``）。

    折叠态高度为 0、展开态为内容建议高度，中间用 ``QPropertyAnimation`` 平滑
    过渡，因此抽屉展开时不会"啪"地跳一下。

    Args:
        widget: 被折叠的内容容器（其 ``maximumHeight`` 会被驱动）。
    """

    #: 动画时长（毫秒）。
    DURATION_MS = 180

    def __init__(self, widget: QWidget) -> None:
        self._widget = widget
        self._animation = QPropertyAnimation(widget, b"maximumHeight", widget)
        self._animation.setDuration(self.DURATION_MS)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._expanded = False
        widget.setMaximumHeight(0)

    @property
    def expanded(self) -> bool:
        """当前是否为展开态。

        Returns:
            True 表示展开。
        """
        return self._expanded

    def content_height(self) -> int:
        """内容区展开后需要的高度。

        Returns:
            高度（像素）。
        """
        widget = self._widget
        inner = widget.layout()
        if inner is not None:
            return inner.sizeHint().height()
        return widget.sizeHint().height()

    def set_expanded(self, expanded: bool, animated: bool = True) -> None:
        """展开或收起内容区。

        展开时同时抬起 ``minimumHeight`` 与 ``maximumHeight``：只改上限的话，
        内容控件自己的 ``sizeHint`` 会继续把它压在"折叠时的高度"上（实测展开后
        抽屉只长到 124px，而内容需要 175px，正文被裁掉）。收起时把下限留到动画
        结束再归零，避免动画中途被布局反向撑开。

        Args:
            expanded: True 展开，False 收起。
            animated: 是否播放动画（初始同步设置时可传 False）。
        """
        self._expanded = bool(expanded)
        widget = self._widget
        target = self.content_height() if self._expanded else 0
        self._animation.stop()

        if not animated:
            widget.setMinimumHeight(0 if not self._expanded else target)
            widget.setMaximumHeight(target)
            return

        if self._expanded:
            widget.setMinimumHeight(target)
            self._animation.setStartValue(widget.maximumHeight())
            self._animation.setEndValue(target)
        else:
            widget.setMinimumHeight(0)
            self._animation.setStartValue(widget.height())
            self._animation.setEndValue(0)
        self._animation.start()


class StyledReasoningDrawer(QWidget):
    """AI 思考内容抽屉（可折叠）。

    与"思考气泡"的区别：思考内容不再占用一个消息气泡，而是收纳进这个可伸缩的
    抽屉——标题栏常驻显示「已思考（用时 N 秒）」+ 展开箭头，正文按需展开。
    参考设计里抽屉是**整列宽**的（不跟随气泡的 74% 上限），正文相对标题缩进。

    Args:
        parent: 父控件。

    Signals:
        toggled: 展开状态变化时发出，携带新的展开状态。
    """

    toggled = Signal(bool)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._text = ""
        self._streaming = False
        self._elapsed_ms = 0
        self._expanded = False
        self._styled: List[Tuple[QWidget, Callable[[], str], str]] = []

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- 标题栏（常驻，可点击展开/收起）----
        self._header = QPushButton(self)
        self._header.setCursor(Qt.PointingHandCursor)
        self._header.setFlat(True)
        self._header.setFixedHeight(HEADER_HEIGHT)
        self._header.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self._header.clicked.connect(self.toggle)
        header_row = QHBoxLayout(self._header)
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(6)
        self._icon = _ReasoningIcon(self._header)
        self._title = QLabel("已思考", self._header)
        self._title.setFont(self._header_font())
        self._title.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._chevron = _ChevronIcon(self._header)
        header_row.addWidget(self._icon)
        header_row.addWidget(self._title)
        header_row.addWidget(self._chevron)
        header_row.addStretch(1)
        root.addWidget(self._header)

        # ---- 正文（可折叠）----
        self._body = QWidget(self)
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(DRAWER_INDENT, 0, 0, 0)
        body_layout.setSpacing(0)
        self._label = QLabel("", self._body)
        self._label.setWordWrap(True)
        self._label.setFont(self._body_font())
        self._label.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )
        self._label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        body_layout.addWidget(self._label)
        root.addWidget(self._body)
        self._slide = _SlideBody(self._body)

        self._styled.append(
            (self._label, self._body_qss, "")
        )
        self._styled.append((self._title, self._title_qss, ""))
        tm.theme_changed.connect(self._on_theme_changed)
        tm.colors_updated.connect(self._on_theme_changed)
        self._refresh_styles()
        self._sync_header_text()
        self._chevron.set_expanded(False)

    # ------------------------------------------------------------------
    # 字体与样式
    # ------------------------------------------------------------------

    @staticmethod
    def _ui_font() -> QFont:
        """基础 UI 字体。

        Returns:
            微软雅黑字体对象。
        """
        return QFont("Microsoft YaHei UI")

    def _header_font(self) -> QFont:
        """标题栏字体（12px）。

        Returns:
            字体对象。
        """
        font = self._ui_font()
        font.setPixelSize(12)
        return font

    def _body_font(self) -> QFont:
        """思考正文字体（13px，比正式回复小一号以弱化层级）。

        Returns:
            字体对象。
        """
        font = self._ui_font()
        font.setPixelSize(13)
        return font

    def _header_qss(self) -> str:
        """标题栏样式片段（透明底、次要文字色、悬停淡色）。

        Returns:
            QSS 文本。
        """
        hover = tm.qss_color(tm.alpha_of(tm.text, 6))
        return (
            f"QPushButton {{ background: transparent; border: none;"
            f" padding: 0px; text-align: left; }}"
            f"QPushButton:hover {{ background: {hover}; border-radius: 4px; }}"
        )

    def _title_qss(self) -> str:
        """标题文字样式片段。

        Returns:
            QSS 文本。
        """
        return (
            f"QLabel {{ background: transparent;"
            f" color: {tm.qss_color(tm.text_secondary)}; font-size: 12px; }}"
        )

    def _body_qss(self) -> str:
        """思考正文样式片段（次要文字色，比正式回复低一档但保证可读）。

        Returns:
            QSS 文本。
        """
        return (
            f"QLabel {{ background: transparent;"
            f" color: {tm.qss_color(tm.text_secondary)};"
            f" font-size: 13px; }}"
        )

    def _refresh_styles(self) -> None:
        """把子控件样式片段（重新）注册到应用级样式表。"""
        refreshed: List[Tuple[QWidget, Callable[[], str], str]] = []
        for widget, renderer, old_id in self._styled:
            if old_id:
                register_widget_qss(widget, "")
            refreshed.append(
                (widget, renderer, register_widget_qss(widget, renderer()))
            )
        self._styled = refreshed

    def _on_theme_changed(self, _theme: str = "") -> None:
        """主题切换后刷新样式。

        Args:
            _theme: 新主题名（未使用）。
        """
        self._refresh_styles()
        self.update()

    # ------------------------------------------------------------------
    # 内容
    # ------------------------------------------------------------------

    def _sync_header_text(self) -> None:
        """按计时更新标题栏文案（``已思考（用时 N 秒）``）。"""
        seconds = max(0, int(round(self._elapsed_ms / 1000.0)))
        if self._elapsed_ms <= 0 and not self._text:
            self._title.setText("思考中")
        elif self._elapsed_ms <= 0:
            self._title.setText("已思考")
        else:
            self._title.setText(f"已思考（用时 {seconds} 秒）")

    def _sync_geometry(self) -> None:
        """宽度变化后把折叠态高度同步到新内容高度。"""
        if self._slide.expanded:
            self._body.setMaximumHeight(self._slide.content_height())

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        """抽屉建议尺寸（宽度跟随可用宽度，高度为标题 + 正文）。

        Returns:
            建议尺寸。
        """
        width = max(self._header.sizeHint().width(), self._body.sizeHint().width())
        height = HEADER_HEIGHT + (
            self._slide.content_height() if self._slide.expanded else 0
        )
        return QSize(width, height)

    def resizeEvent(self, event: object) -> None:
        """宽度变化时重算折叠态高度。

        Args:
            event: Qt 尺寸变化事件。
        """
        self._sync_geometry()
        super().resizeEvent(event)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    @property
    def text(self) -> str:
        """当前思考内容。"""
        return self._text

    @property
    def expanded(self) -> bool:
        """当前是否展开。"""
        return self._expand_state()

    def _expand_state(self) -> bool:
        """读取折叠动画包装的展开状态。

        Returns:
            True 表示展开。
        """
        return self._slide.expanded

    def set_text(self, text: str) -> None:
        """替换思考内容。

        Args:
            text: 思考正文。
        """
        self._text = text
        self._label.setText(text)
        self._sync_geometry()
        self.updateGeometry()

    def append_text(self, text: str) -> None:
        """追加思考内容（流式输出）。

        Args:
            text: 追加片段。
        """
        self.set_text(self._text + text)

    def set_streaming(self, streaming: bool) -> None:
        """标记思考是否仍在流式输出（仅影响标题文案）。

        Args:
            streaming: 是否进行中。
        """
        self._streaming = bool(streaming)
        self._sync_header_text()

    def set_elapsed_ms(self, elapsed_ms: int) -> None:
        """设置思考耗时（用于标题栏「用时 N 秒」）。

        Args:
            elapsed_ms: 耗时毫秒数。
        """
        self._elapsed_ms = max(0, int(elapsed_ms))
        self._sync_header_text()

    def elapsed_ms(self) -> int:
        """当前记录的思考耗时。

        Returns:
            毫秒数。
        """
        return self._elapsed_ms

    def set_expanded(self, expanded: bool, animated: bool = True) -> None:
        """展开或收起抽屉。

        Args:
            expanded: True 展开，False 收起。
            animated: 是否播放动画。
        """
        self._slide.set_expanded(expanded, animated=animated)
        self._chevron.set_expanded(bool(expanded))
        self.updateGeometry()
        self.toggled.emit(bool(expanded))

    def toggle(self) -> None:
        """在展开/收起之间切换（标题栏点击入口）。"""
        self.set_expanded(not self._expand_state())


__all__ = [
    "ChatMessageRow",
    "RowSpec",
    "StyledAIAvatar",
    "StyledAIAvatarAccent",
    "StyledChatBubble",
    "StyledReasoningDrawer",
    "accent_color",
    "file_badge_text",
    "file_badge_color",
    "file_extension",
    "make_ai_avatar_pixmap",
    "surface_fill_color",
    "window_fill_color",
]
