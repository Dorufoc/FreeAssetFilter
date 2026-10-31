"""Settings Card component - matches web settings card exactly."""

from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QSizePolicy,
    QGraphicsOpacityEffect,
)
from PySide6.QtCore import (
    Qt, QEasingCurve, QPointF, QPropertyAnimation, Signal,
)
from PySide6.QtGui import QPainter, QPainterPath, QPaintEvent, QPen
from theme import tm
from sopeek.ui.theme.app_stylesheet import register_widget_qss
from sopeek.utils.animation_settings import is_animation_enabled


# ── 设置项排版统一 token（外观 / 通用 / 关于三页共用） ──────────────
# 三页的行标题、描述、读数只允许引用这里的字号与间距，禁止页面内各自
# 硬编码（历史缺陷：标题 13 / 13.5 / 14px 并存、行距 12 / 20px 并存、
# 描述被通刷成标题样式）。全部字号使用 px。
SETTINGS_TITLE_CSS = "font-size: 13px; font-weight: 500;"
SETTINGS_DESC_CSS = "font-size: 12px;"
SETTINGS_VALUE_CSS = "font-size: 12px;"

SETTINGS_ROW_PAD_V = 10          # 行内上/下内边距（compact 行见 _COMPACT 值）
SETTINGS_ROW_PAD_V_COMPACT = 6   # compact 行的上/下内边距
SETTINGS_ROW_GAP = 8             # 行与行之间的间距（分组内布局）
SETTINGS_GROUP_GAP = 20          # 分组与分组之间的间距（页面主布局）
SETTINGS_TITLE_DESC_GAP = 4      # 行标题与描述的间距
SETTINGS_BODY_GAP = 10           # 整行内容型设置项：标题块与内容区的间距
SETTINGS_LABEL_GAP = 16          # 左侧文字与右侧控件/参数列的间距
SETTINGS_FIELD_LABEL_WIDTH = 64  # 行内字段名列宽（如滑动条左侧参数名）
SETTINGS_VALUE_LABEL_WIDTH = 44  # 行内读数列宽（如滑动条右侧数值，右对齐）

# ── 子选项排版与展开动画（「显示受保护的系统文件」「贴边吸附」等） ──
SETTINGS_SUB_INDENT = 4           # 子选项行整体右缩进（相对父行标题左缘）
SETTINGS_SUB_BRANCH_WIDTH = 14    # 竖折向右箭头占位宽度
SETTINGS_SUB_BRANCH_HEIGHT = 14   # 竖折向右箭头绘制高度（与标题行同高）
SETTINGS_SUB_BRANCH_GAP = 6       # 箭头与标题、描述之间的间距
SETTINGS_SUB_REVEAL_MS = 220      # 插入（展开）动画时长
SETTINGS_SUB_COLLAPSE_MS = 160    # 收起动画时长（比展开略快，符合折叠惯例）
SETTINGS_SUB_ANIMATION_KEY = "settings_sub_option"  # appearance.animations.<key>
#: QWidget 默认最大高度（Qt 的 QWIDGETSIZE_MAX；PySide6 未导出该常量）。
_WIDGET_SIZE_MAX = 16777215


def apply_settings_title_style(label: QLabel) -> None:
    """为设置项标题标签应用统一样式（13px / 500 / tm.text）。

    Args:
        label: 目标标题标签。
    """
    register_widget_qss(label, (
        f"background: transparent; border: none; {SETTINGS_TITLE_CSS}"
        f" color: {tm.text.name()};"
    ))


def apply_settings_desc_style(label: QLabel) -> None:
    """为设置项描述标签应用统一样式（12px / tm.text_hint）。

    Args:
        label: 目标描述标签（调用方需自行 setWordWrap）。
    """
    register_widget_qss(label, (
        f"background: transparent; border: none; {SETTINGS_DESC_CSS}"
        f" color: {tm.qss_color(tm.text_hint)};"
    ))


def apply_settings_field_style(label: QLabel) -> None:
    """为设置项内部字段名标签应用统一样式（12px / tm.text）。

    Args:
        label: 目标字段名标签（如滑动条左侧的参数名）。
    """
    register_widget_qss(label, (
        f"background: transparent; border: none; {SETTINGS_DESC_CSS}"
        f" color: {tm.text.name()};"
    ))


def apply_settings_value_style(label: QLabel) -> None:
    """为设置项读数标签应用统一样式（12px / tm.text_secondary）。

    Args:
        label: 目标读数标签（如滑动条右侧的数值）。
    """
    register_widget_qss(label, (
        f"background: transparent; border: none; {SETTINGS_VALUE_CSS}"
        f" color: {tm.qss_color(tm.text_secondary)};"
    ))


class SettingsCard(QWidget):
    """A settings card matching the web component exactly."""

    _instance_count = 0

    def __init__(
        self,
        variant: str = "default",  # default, danger, info
        compact: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        SettingsCard._instance_count += 1
        self._instance_id = SettingsCard._instance_count
        self._variant = variant
        self._compact = compact

        # Enable QSS background rendering (CRITICAL: without this, setStyleSheet is ignored)
        self.setAttribute(Qt.WA_StyledBackground, True)

        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(18, 0, 18, 18)
        self._main_layout.setSpacing(0)
        self._apply_style()

    def _apply_style(self):
        if self._variant == "danger":
            c = tm.danger
            border_color = tm.qss_rgba(c, 30)
        elif self._variant == "info":
            c = tm.info
            border_color = tm.qss_rgba(c, 30)
        else:
            border_color = tm.qss_color(tm.control_border_strong)

        # Set style on self only via unique objectName to prevent inheritance
        self.setObjectName(f"SettingsCard_{self._instance_id}")
        bg_color = tm.surface.name()
        register_widget_qss(self,(f"""
            #SettingsCard_{self._instance_id} {{
                background-color: {bg_color};
                border-radius: 10px;
            }}
        """))

    def add_header(self, title: str, action_widget: QWidget = None):
        """Add a card header with title and optional action widget."""
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 16, 20, 8)
        layout.setSpacing(16)

        title_label = QLabel(title)
        if self._variant == "danger":
            register_widget_qss(title_label,(f'font-size: 14px; font-weight: 600; color: {tm.danger.name()}; letter-spacing: 0.3px;'))
        elif self._variant == "info":
            register_widget_qss(title_label,(f'font-size: 14px; font-weight: 600; color: {tm.info.name()}; letter-spacing: 0.3px;'))
        else:
            register_widget_qss(title_label,(f'font-size: 14px; font-weight: 600; color: {tm.text.name()}; letter-spacing: 0.3px;'))
        layout.addWidget(title_label, stretch=1)

        if action_widget:
            layout.addWidget(action_widget)

        self._main_layout.addWidget(header)
        return header

    def add_body(self) -> QVBoxLayout:
        """Add a card body container and return its layout."""
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 4, 0, 4)  # Web CSS: .card-body { padding: 4px 0; }
        body_layout.setSpacing(0)
        self._main_layout.addWidget(body)
        return body_layout

    def add_footer(self) -> QHBoxLayout:
        """Add a card footer container and return its layout."""
        footer = QWidget()
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(20, 12, 20, 12)
        footer_layout.setSpacing(16)

        # Add top border via a separator widget
        sep = QFrame()
        sep.setObjectName(f"SettingsCardSep_{self._instance_id}")
        sep.setFixedHeight(1)
        register_widget_qss(sep,(f"""
            #SettingsCardSep_{self._instance_id} {{
                background-color: {tm.qss_color(tm.alpha_of(tm.mid if tm.is_dark_theme() else tm.text, 30))};
            }}
        """))
        footer_layout_parent = QVBoxLayout()
        footer_layout_parent.setContentsMargins(0, 0, 0, 0)
        footer_layout_parent.setSpacing(0)
        footer_layout_parent.addWidget(sep)
        footer_layout_parent.addWidget(footer)

        self._main_layout.addLayout(footer_layout_parent)
        return footer_layout


class _SubOptionBranch(QWidget):
    """子选项前缀图形：竖折向右的箭头（└→），表达「从属于上一项」。

    只负责绘制，不参与交互；颜色取主题 ``tm.text_hint``，主题切换时由
    :class:`SettingsRow` 触发 ``update()`` 重绘。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(SETTINGS_SUB_BRANCH_WIDTH, SETTINGS_SUB_BRANCH_HEIGHT)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(
            tm.text_hint, 1.3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin,
        ))
        width = float(self.width())
        mid = float(self.height()) / 2.0
        x = 1.5
        tip = max(x + 2.0, width - 1.5)
        radius = min(3.0, (tip - x) / 3.0)

        # 竖线向下，经圆角折向右侧，再画箭头两翼。
        path = QPainterPath()
        path.moveTo(QPointF(x, 0.0))
        path.lineTo(QPointF(x, mid - radius))
        path.quadTo(QPointF(x, mid), QPointF(x + radius, mid))
        path.lineTo(QPointF(tip, mid))
        painter.drawPath(path)

        head = 4.0
        painter.drawLine(QPointF(tip - head, mid - head), QPointF(tip, mid))
        painter.drawLine(QPointF(tip - head, mid + head), QPointF(tip, mid))


class SettingsRow(QWidget):
    """统一的设置项行：左侧标题（+描述），右侧控件，整体垂直居中。

    排版规格（三页共用，见模块级 ``SETTINGS_*`` token）：
    行内上/下内边距 ``SETTINGS_ROW_PAD_V``、标题与描述间距
    ``SETTINGS_TITLE_DESC_GAP``、文字与控件间距 ``SETTINGS_LABEL_GAP``；
    垂直尺寸策略为 ``Maximum``（高度恒等于内容高度，绝不被父布局拉伸——
    历史缺陷：关于页行被拉高到整页一半，右侧按钮悬浮在行中间）。

    ``sub_option=True`` 时按子选项排版：整行右缩进 ``SETTINGS_SUB_INDENT``，
    标题前绘制「竖折向右」箭头；配合 :meth:`set_revealed` 播放高度 +
    透明度插入/收起动画，由父选项的开关控制显隐。

    控件经 :meth:`set_control` 放置；``title_label`` / ``desc_label``
    仅在对应文案非空时存在（保持历史 API）。
    """

    _instance_count = 0

    #: 子选项展开/收起完成时发出（True 展开完成，False 收起完成）。宿主可据此
    #: 做「按需滚动」：仅当新插入的子选项被挤出视口时才滚动到可见。
    reveal_finished = Signal(bool)

    def __init__(
        self,
        title: str = "",
        description: str = "",
        compact: bool = False,
        sub_option: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        SettingsRow._instance_count += 1
        self._instance_id = SettingsRow._instance_count
        self._compact = compact
        self._sub_option = bool(sub_option)
        self._sub_branch: Optional[_SubOptionBranch] = None

        # 子选项展开状态与动画（非子选项始终为 True/可见）。
        self._revealed = True
        self._height_anim: Optional[QPropertyAnimation] = None
        self._opacity_anim: Optional[QPropertyAnimation] = None
        self._opacity_effect: Optional[QGraphicsOpacityEffect] = None

        self.setObjectName(f"SettingsRow_{self._instance_id}")
        # Use unique objectName to scope styles to this widget only (prevent inheritance)
        register_widget_qss(self,(f"#SettingsRow_{self._instance_id} {{ background: transparent; }}"))
        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        # 高度 = 内容高度：行不被父布局拉伸（横向仍可铺满）
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        pad_v = SETTINGS_ROW_PAD_V_COMPACT if compact else SETTINGS_ROW_PAD_V
        left_pad = SETTINGS_SUB_INDENT if self._sub_option else 0
        layout = QHBoxLayout(self)
        layout.setContentsMargins(left_pad, pad_v, 0, pad_v)
        layout.setSpacing(SETTINGS_LABEL_GAP)

        # Left: title + description（整体在行内垂直居中）
        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(SETTINGS_TITLE_DESC_GAP)

        if title:
            self.title_label = QLabel(title)
            apply_settings_title_style(self.title_label)
            if self._sub_option:
                # 箭头与标题同处一行：箭头垂直对齐标题，而不是整个
                # 标题+描述块的中心（否则会落在两行描述之间，观感突兀）。
                self._sub_branch = _SubOptionBranch()
                title_row = QHBoxLayout()
                title_row.setContentsMargins(0, 0, 0, 0)
                title_row.setSpacing(SETTINGS_SUB_BRANCH_GAP)
                title_row.addWidget(self._sub_branch, 0, Qt.AlignVCenter)
                title_row.addWidget(self.title_label, 1, Qt.AlignVCenter)
                content.addLayout(title_row)
            else:
                content.addWidget(self.title_label)

        if description:
            self.desc_label = QLabel(description)
            apply_settings_desc_style(self.desc_label)
            self.desc_label.setWordWrap(True)
            if self._sub_option:
                # 描述与标题文字左对齐（让开箭头占位），不跟箭头抢位置。
                desc_row = QHBoxLayout()
                desc_row.setContentsMargins(
                    SETTINGS_SUB_BRANCH_WIDTH + SETTINGS_SUB_BRANCH_GAP, 0, 0, 0
                )
                desc_row.addWidget(self.desc_label, 1)
                content.addLayout(desc_row)
            else:
                content.addWidget(self.desc_label)

        content_widget = QWidget()
        content_widget.setLayout(content)
        layout.addWidget(content_widget, stretch=1, alignment=Qt.AlignVCenter)

        # Right: control area（垂直居中，横向保持自身尺寸）
        self.control_widget = QWidget()
        self.control_layout = QHBoxLayout(self.control_widget)
        self.control_layout.setContentsMargins(0, 0, 0, 0)
        self.control_layout.setSpacing(0)
        layout.addWidget(self.control_widget, alignment=Qt.AlignVCenter)

    def set_control(self, widget: QWidget):
        """Set the right-side control widget."""
        while self.control_layout.count():
            item = self.control_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.control_layout.addWidget(widget)

    # ── 子选项展开 / 收起 ──────────────────────────────────────────

    @property
    def is_sub_option(self) -> bool:
        """是否按子选项排版（右缩进 + 竖折右箭头）。"""
        return self._sub_option

    @property
    def is_revealed(self) -> bool:
        """子选项当前是否处于展开（期望可见）状态。"""
        return self._revealed

    def set_revealed(self, revealed: bool, animated: bool = True) -> None:
        """设置子选项展开状态（True 插入显示 / False 收起隐藏）。

        动画为「高度展开 + 透明度淡入」的组合（参考 Material Collapse /
        Web 折叠面板的展开方式），收起时略快于展开以避免拖沓。主机页面
        不可见（初始化、后台刷新）或全局关闭动画时自动退化为立即切换，
        保证 ``refresh_from_staging`` 不会在窗口未显示时播动画。

        Args:
            revealed: True 显示子选项，False 隐藏。
            animated: 是否允许播放过渡动画。
        """
        revealed = bool(revealed)
        visibility_matches = self.isHidden() if not revealed else not self.isHidden()
        if revealed == self._revealed and visibility_matches:
            return
        self._revealed = revealed
        if self._should_animate_reveal(animated):
            self._start_reveal_animation()
        else:
            self._apply_reveal_state()

    def _should_animate_reveal(self, animated: bool) -> bool:
        """返回是否应播放展开动画（仅子选项、宿主可见、动画未全局关闭）。"""
        if not animated or not self._sub_option:
            return False
        host = self.parentWidget()
        if host is None or not host.isVisible():
            return False
        return is_animation_enabled(SETTINGS_SUB_ANIMATION_KEY, default=True)

    def _stop_reveal_animation(self) -> None:
        """停止并回收在途的展开/收起动画。"""
        for anim in (self._height_anim, self._opacity_anim):
            if anim is not None:
                anim.stop()
                anim.deleteLater()
        self._height_anim = None
        self._opacity_anim = None

    def _ensure_opacity_effect(self) -> QGraphicsOpacityEffect:
        """按需创建行级透明度效果（动画结束后立即移除，恢复原生绘制）。"""
        if self._opacity_effect is None:
            effect = QGraphicsOpacityEffect(self)
            effect.setOpacity(1.0)
            self.setGraphicsEffect(effect)
            self._opacity_effect = effect
        return self._opacity_effect

    def _clear_opacity_effect(self) -> None:
        """移除行级透明度效果（Qt 接管所有权并销毁效果对象）。"""
        if self._opacity_effect is not None:
            self.setGraphicsEffect(None)
            self._opacity_effect = None

    def _apply_reveal_state(self) -> None:
        """立即应用展开/收起状态（不播动画）。"""
        self._stop_reveal_animation()
        if self._revealed:
            self.setMaximumHeight(_WIDGET_SIZE_MAX)
            self.setVisible(True)
            self._clear_opacity_effect()
        else:
            self.setVisible(False)
            self._clear_opacity_effect()
            self.setMaximumHeight(0)
        self.reveal_finished.emit(self._revealed)

    def _start_reveal_animation(self) -> None:
        """启动高度 + 透明度动画；动画完成后解除高度约束。"""
        self._stop_reveal_animation()
        if self._revealed:
            start_height = 0 if self.isHidden() else max(0, self.height())
            self.setVisible(True)
            self.setMaximumHeight(start_height)
            self.ensurePolished()
            if self.layout() is not None:
                self.layout().activate()
            target_height = max(1, self.sizeHint().height())
            duration = SETTINGS_SUB_REVEAL_MS
            easing = QEasingCurve.OutCubic

            had_effect = self._opacity_effect is not None
            effect = self._ensure_opacity_effect()
            # 反向打断收起动画时从当前透明度接着淡入，避免跳回全透明。
            start_opacity = effect.opacity() if had_effect else 0.0
            effect.setOpacity(start_opacity)

            self._height_anim = QPropertyAnimation(self, b"maximumHeight", self)
            self._height_anim.setDuration(duration)
            self._height_anim.setEasingCurve(easing)
            self._height_anim.setStartValue(start_height)
            self._height_anim.setEndValue(target_height)
            self._height_anim.finished.connect(self._on_reveal_finished)

            self._opacity_anim = QPropertyAnimation(effect, b"opacity", self)
            self._opacity_anim.setDuration(duration)
            self._opacity_anim.setEasingCurve(easing)
            self._opacity_anim.setStartValue(start_opacity)
            self._opacity_anim.setEndValue(1.0)

            self._height_anim.start()
            self._opacity_anim.start()
            return

        start_height = max(0, self.height())
        if start_height <= 0:
            self._apply_reveal_state()
            return
        duration = SETTINGS_SUB_COLLAPSE_MS
        easing = QEasingCurve.InCubic

        had_effect = self._opacity_effect is not None
        effect = self._ensure_opacity_effect()
        # 反向打断展开动画时从当前透明度接着淡出，避免跳回完全不透明。
        start_opacity = effect.opacity() if had_effect else 1.0
        effect.setOpacity(start_opacity)

        self._height_anim = QPropertyAnimation(self, b"maximumHeight", self)
        self._height_anim.setDuration(duration)
        self._height_anim.setEasingCurve(easing)
        self._height_anim.setStartValue(start_height)
        self._height_anim.setEndValue(0)
        self._height_anim.finished.connect(self._on_reveal_finished)

        self._opacity_anim = QPropertyAnimation(effect, b"opacity", self)
        self._opacity_anim.setDuration(duration)
        self._opacity_anim.setEasingCurve(easing)
        self._opacity_anim.setStartValue(start_opacity)
        self._opacity_anim.setEndValue(0.0)

        self._height_anim.start()
        self._opacity_anim.start()

    def _on_reveal_finished(self) -> None:
        """动画结束：展开后解除高度上限，收起后隐藏并归零高度。"""
        height_anim = self._height_anim
        opacity_anim = self._opacity_anim
        self._height_anim = None
        self._opacity_anim = None
        if height_anim is not None:
            height_anim.deleteLater()
        if opacity_anim is not None:
            opacity_anim.deleteLater()

        if self._revealed:
            self.setMaximumHeight(_WIDGET_SIZE_MAX)
            self._clear_opacity_effect()
        else:
            self.setVisible(False)
            self.setMaximumHeight(0)
            self._clear_opacity_effect()
        self.reveal_finished.emit(self._revealed)


class SettingsBlock(QWidget):
    """整行内容型设置项：标题（+描述）在上，内容区整行铺满下方。

    用于控件无法塞进标题右侧行的条目（主题色色板、图像参数滑动条等），
    与 :class:`SettingsRow` 共用同一套字号与间距 token；无标题/描述时
    内容区直接使用行内边距，作为纯内容分组容器（如滑动条组）。

    内容经 :meth:`add_content` / :meth:`set_content_layout` 放置；
    ``title_label`` / ``desc_label`` 仅在对应文案非空时存在。
    """

    _instance_count = 0

    def __init__(
        self,
        title: str = "",
        description: str = "",
        compact: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        SettingsBlock._instance_count += 1
        self._instance_id = SettingsBlock._instance_count
        self._compact = compact

        self.setObjectName(f"SettingsBlock_{self._instance_id}")
        register_widget_qss(self,(f"#SettingsBlock_{self._instance_id} {{ background: transparent; }}"))
        self.setAttribute(Qt.WA_StyledBackground, True)
        # 高度 = 内容高度：块不被父布局拉伸
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        pad_v = SETTINGS_ROW_PAD_V_COMPACT if compact else SETTINGS_ROW_PAD_V
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, pad_v, 0, pad_v)
        layout.setSpacing(SETTINGS_BODY_GAP)

        # 标题块（标题 + 描述）与内容区之间的间距用 SETTINGS_BODY_GAP，
        # 标题与描述之间用 SETTINGS_TITLE_DESC_GAP。
        if title or description:
            header = QVBoxLayout()
            header.setContentsMargins(0, 0, 0, 0)
            header.setSpacing(SETTINGS_TITLE_DESC_GAP)

            if title:
                self.title_label = QLabel(title)
                apply_settings_title_style(self.title_label)
                header.addWidget(self.title_label)

            if description:
                self.desc_label = QLabel(description)
                apply_settings_desc_style(self.desc_label)
                self.desc_label.setWordWrap(True)
                header.addWidget(self.desc_label)

            layout.addLayout(header)

        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(SETTINGS_ROW_GAP)
        layout.addWidget(self.body)

    def add_content(self, widget: QWidget) -> None:
        """把控件加入内容区（整行铺满）。"""
        self.body_layout.addWidget(widget)

    def set_content_layout(self, layout) -> None:
        """把布局（如一行色板按钮）加入内容区。"""
        self.body_layout.addLayout(layout)


class NotificationRow(QWidget):
    """A notification row with a dot indicator."""

    _instance_count = 0

    def __init__(
        self,
        title: str = "",
        description: str = "",
        active: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        NotificationRow._instance_count += 1
        self._instance_id = NotificationRow._instance_count

        self.setObjectName(f"NotificationRow_{self._instance_id}")
        # Use unique objectName to scope styles to this widget only (prevent inheritance)
        register_widget_qss(self,(f"#NotificationRow_{self._instance_id} {{ background: transparent; }}"))
        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_StyledBackground, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)  # Web CSS: padding: 8px 20px
        layout.setSpacing(12)  # Web CSS: gap: 12px

        # Dot indicator
        dot = QFrame()
        dot.setObjectName(f"NotificationDot_{self._instance_id}")
        dot.setFixedSize(8, 8)
        self._dot = dot
        self._active = bool(active)
        self._apply_dot_style()
        layout.addWidget(dot)

        # Content
        content = QVBoxLayout()
        content.setSpacing(2)

        if title:
            title_label = QLabel(title)
            register_widget_qss(title_label,(f'font-size: 13.5px; font-weight: 500; color: {tm.text.name()};'))
            content.addWidget(title_label)

        if description:
            desc_label = QLabel(description)
            register_widget_qss(desc_label,(f'font-size: 12px; color: {tm.qss_color(tm.text_hint)};'))
            content.addWidget(desc_label)

        content_widget = QWidget()
        content_widget.setLayout(content)
        layout.addWidget(content_widget, stretch=1)

        # Control
        self.control_widget = QWidget()
        self.control_layout = QHBoxLayout(self.control_widget)
        self.control_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.control_widget)

        # 主题/配色变化：圆点激活色取自 accent，需重注册（其余文字样式由
        # 设置页 refresh_theme 统一处理）。
        tm.theme_changed.connect(self._on_theme_changed)
        tm.colors_updated.connect(self._on_theme_changed)

    def _on_theme_changed(self, *_args) -> None:
        """主题/配色变化时重注册圆点颜色。

        Args:
            *_args: 主题信号附带参数（未使用）。
        """
        self._apply_dot_style()

    def _apply_dot_style(self) -> None:
        """按当前主题与激活态重注册圆点样式（激活=accent）。"""
        dot_color = (
            tm.accent.name() if self._active
            else tm.qss_color(tm.text_hint if tm.is_dark_theme() else tm.text_secondary)
        )
        register_widget_qss(self._dot,(f"""
            #NotificationDot_{self._instance_id} {{
                background-color: {dot_color};
                border-radius: 4px;
            }}
        """))

    def set_control(self, widget: QWidget):
        while self.control_layout.count():
            item = self.control_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.control_layout.addWidget(widget)


class PluginItem(QWidget):
    """A plugin item with icon, info, and toggle."""

    _instance_count = 0

    def __init__(
        self,
        name: str = "",
        description: str = "",
        icon_gradient: tuple = ("#07c160", "#059a4c"),
        parent=None,
    ):
        super().__init__(parent)
        PluginItem._instance_count += 1
        self._instance_id = PluginItem._instance_count

        self.setObjectName(f"PluginItem_{self._instance_id}")
        # Use unique objectName to scope styles to this widget only (prevent inheritance)
        register_widget_qss(self,(f"#PluginItem_{self._instance_id} {{ background: transparent; }}"))
        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_StyledBackground, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)  # Web CSS: padding: 8px 20px
        layout.setSpacing(14)  # Web CSS: gap: 14px

        # Icon
        icon = QFrame()
        icon.setObjectName(f"PluginIcon_{self._instance_id}")
        icon.setFixedSize(40, 40)
        register_widget_qss(icon,(f"""
            #PluginIcon_{self._instance_id} {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {icon_gradient[0]}, stop:1 {icon_gradient[1]});
                border-radius: 6px;
            }}
        """))
        layout.addWidget(icon)

        # Info
        info = QVBoxLayout()
        info.setSpacing(2)

        if name:
            name_label = QLabel(name)
            register_widget_qss(name_label,(f'font-size: 13px; font-weight: 500; color: {tm.text.name()};'))
            info.addWidget(name_label)

        if description:
            desc_label = QLabel(description)
            register_widget_qss(desc_label,(f'font-size: 11.5px; color: {tm.qss_color(tm.text_hint)};'))
            info.addWidget(desc_label)

        info_widget = QWidget()
        info_widget.setLayout(info)
        layout.addWidget(info_widget, stretch=1)

        # Control
        self.control_widget = QWidget()
        self.control_layout = QHBoxLayout(self.control_widget)
        self.control_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.control_widget)

    def set_control(self, widget: QWidget):
        while self.control_layout.count():
            item = self.control_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.control_layout.addWidget(widget)
