"""Styled InfoCard component - matches web info-card exactly."""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSizePolicy, QGraphicsOpacityEffect,
)
from PySide6.QtCore import (
    Qt, Signal, QRectF, QPropertyAnimation, QEasingCurve, QTimer,
    Property, QPoint, QEvent, QParallelAnimationGroup,
)
from PySide6.QtGui import (
    QPainter, QColor, QPaintEvent, QFont, QFontMetrics,
    QPen, QBrush, QMouseEvent, QActionEvent, QConicalGradient,
    QLinearGradient, QPainterPath,
)

from theme import tm
from components.styled_button import StyledButton


# 图标相对 media 区域的放大系数：>1 时图标超出 media 区域边界绘制，视觉更大。
# 当前试探值 1.10 = 放大 10%，后续可按需调整。
_MEDIA_ICON_SCALE: float = 1.10

# hover 图标缩放动画总开关：暂时禁用（False），恢复动画时改为 True。
_HOVER_MEDIA_ANIM_ENABLED: bool = False

# 绘制热路径缓存：配色只依赖主题（dark/light），切换时以 is_dark_theme 为 key 失效；
# 配置缓存按 (layout_mode, size_overrides) 失效。
_INFO_CARD_COLORS_CACHE: dict = {}
_CARD_CONFIG_CACHE: dict = {}


def _clear_info_card_color_cache(*_args) -> None:
    """主题变化时清空配色缓存（兜底覆盖同主题重设/热更新）。"""
    _INFO_CARD_COLORS_CACHE.clear()


tm.theme_changed.connect(_clear_info_card_color_cache)


class StyledInfoCard(QWidget):
    """A styled info card matching the web component exactly.

    Layout modes:
    - horizontal: media left, text body right
    - vertical: media top, text body bottom

    Features: hover scale on media, press scale on card,
    hover overlay with action buttons, disabled state.
    """

    clicked = Signal(str)  # emitted on left-button release, passes file_path
    right_clicked = Signal(str)  # emitted on right-button release, passes file_path
    selection_changed = Signal(bool, str)  # (selected, file_path) - state first, path second
    preview_state_changed = Signal(bool, str)  # (previewing, file_path) - state first, path second

    LAYOUT_MODES = ["horizontal", "vertical"]

    SIZE_CONFIG = {
        "horizontal": {
            "padding": 16,
            "gap": 14,
            "radius": 6,
            "media_size": 52,
            "icon_size": 24,
            "title_size": 14,
            "title_weight": 600,
            "subtitle_size": 13,
            "subtitle_weight": 500,
            "desc_size": 12,
            "desc_weight": 400,
        },
        "vertical": {
            "padding": 20,
            "gap": 12,
            "radius": 6,
            "media_size": 64,
            "icon_size": 28,
            "title_size": 14,
            "title_weight": 600,
            "subtitle_size": 13,
            "subtitle_weight": 500,
            "desc_size": 12,
            "desc_weight": 400,
        },
    }

    def __init__(
        self,
        layout_mode: str = "horizontal",
        title: str = "",
        subtitle: str = "",
        desc: str = "",
        disabled: bool = False,
        media_icon: str = "",
        overlay_enabled: bool = False,
        size_overrides: dict | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._layout_mode = layout_mode if layout_mode in self.LAYOUT_MODES else "horizontal"
        self._title = title
        self._subtitle = subtitle
        self._desc = desc
        self._disabled = disabled
        self._media_icon = media_icon
        self._media_pixmap = None  # optional QPixmap override for media area
        self._overlay_enabled = overlay_enabled
        self._file_path = ""  # identifier for clicked signal
        self._size_overrides = size_overrides or {}
        self._actions = []  # list of (text, icon, callback)

        # Animation states
        self._hovered = False
        self._pressed = False
        self._overlay_opacity = 0.0
        self._overlay_slide = 0.0  # 0=遮罩完全在卡片右侧外，1=完全就位（从右侧滑入）
        self._card_opacity = 1.0
        self._card_scale = 1.0
        self._media_scale = 1.0
        self._x_offset = 0
        self._y_offset = 0

        # Selection and preview states
        self._is_selected = False
        self._is_previewing = False
        self._anim_bg_color = QColor(tm.surface)
        self._anim_border_color = QColor(tm.mid)
        self._border_width = 1
        self._style_colors: dict = {}

        # Shadow offset for depth
        self._shadow_offset = 0.0

        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setMouseTracking(False)

        # Hover animation (media scale + overlay fade)
        self._hover_anim = QPropertyAnimation(self, b"overlay_opacity")
        self._hover_anim.setDuration(400)
        self._hover_anim.setEasingCurve(QEasingCurve.OutCubic)

        # Overlay slide animation — 遮罩整体从右侧平移进入/滑出
        self._slide_anim = QPropertyAnimation(self, b"overlay_slide")
        self._slide_anim.setDuration(400)
        self._slide_anim.setEasingCurve(QEasingCurve.OutCubic)

        # Media scale animation — OutBack gives a subtle spring overshoot (non-linear)
        self._media_scale_anim = QPropertyAnimation(self, b"media_scale")
        self._media_scale_anim.setDuration(300)
        self._media_scale_anim.setEasingCurve(QEasingCurve.OutBack)

        # Card press scale animation
        self._card_scale_anim = QPropertyAnimation(self, b"card_scale")
        self._card_scale_anim.setDuration(120)
        self._card_scale_anim.setEasingCurve(QEasingCurve.OutBack)

        # 预览态渐变边框旋转动画：焦点绕卡片中心旋转（16ms/帧，循环）
        self._preview_angle: float = 0.0
        self._preview_anim_timer = QTimer(self)
        self._preview_anim_timer.setInterval(16)
        self._preview_anim_timer.timeout.connect(self._advance_preview_gradient)

        # Overlay buttons (created as child widgets, hidden by default)
        self._overlay_widget = None
        self._overlay_buttons = []

        self._apply_size()
        self._init_style_colors()
        self.update()

        # Repaint automatically when the global theme changes.
        tm.colors_updated.connect(self._on_theme_changed)

    # ── Properties ────────────────────────────────────────────

    @Property(float)
    def overlay_opacity(self):
        return self._overlay_opacity

    @overlay_opacity.setter
    def overlay_opacity(self, value: float):
        self._overlay_opacity = value
        self._update_overlay_visibility()
        self.update()

    @Property(float)
    def overlay_slide(self):
        return self._overlay_slide

    @overlay_slide.setter
    def overlay_slide(self, value: float):
        self._overlay_slide = value
        self._update_overlay_geometry()
        self.update()

    @Property(float)
    def media_scale(self):
        return self._media_scale

    @media_scale.setter
    def media_scale(self, value: float):
        self._media_scale = value
        self.update()

    @Property(float)
    def card_scale(self):
        return self._card_scale

    @card_scale.setter
    def card_scale(self, value: float):
        self._card_scale = value
        self.update()

    @Property(QColor)
    def anim_bg_color(self):
        return self._anim_bg_color

    @anim_bg_color.setter
    def anim_bg_color(self, color: QColor):
        if self._anim_bg_color != color:
            self._anim_bg_color = QColor(color)
            self.update()

    @Property(QColor)
    def anim_border_color(self):
        return self._anim_border_color

    @anim_border_color.setter
    def anim_border_color(self, color: QColor):
        if self._anim_border_color != color:
            self._anim_border_color = QColor(color)
            self.update()

    @Property(float)
    def card_opacity(self):
        """卡片整体绘制透明度，供 layout 动画使用（不影响子 overlay 控件）。"""
        return self._card_opacity

    @card_opacity.setter
    def card_opacity(self, value: float):
        self._card_opacity = max(0.0, min(1.0, float(value)))
        self.update()

    @Property(int)
    def x_offset(self):
        """卡片水平绘制偏移（px），供移除动画向左滑出使用。"""
        return self._x_offset

    @x_offset.setter
    def x_offset(self, value: int):
        self._x_offset = int(value)
        self._update_overlay_geometry()
        self.update()

    @Property(int)
    def y_offset(self):
        """卡片垂直绘制偏移（px），供移除时下方卡片整体向上位移动画使用。"""
        return self._y_offset

    @y_offset.setter
    def y_offset(self, value: int):
        self._y_offset = int(value)
        self._update_overlay_geometry()
        self.update()

    def _on_theme_changed(self, _colors: dict) -> None:
        """Slot for ThemeManager.colors_updated: repaint with new theme colors."""
        self._init_style_colors()
        # 如果当前处于选中/预览态，重新应用状态样式
        if self._is_selected:
            self._anim_bg_color = self._style_colors["selected_bg"]
            self._anim_border_color = self._style_colors["selected_border"]
        elif not self._is_previewing:
            self._anim_bg_color = self._style_colors["normal_bg"]
            self._anim_border_color = self._style_colors["normal_border"]
        # 主题切换后刷新 overlay 渐变背景（G 色随深色/亮色模式变化，保留当前 slide）
        if self._overlay_widget:
            self._overlay_widget.setStyleSheet(
                self._overlay_background_stylesheet(
                    self._get_config()["radius"], self._overlay_slide
                )
            )
        self.update()

    # ── Config ────────────────────────────────────────────────

    def _get_config(self) -> dict:
        """获取当前布局配置，合并 size_overrides 覆盖项（结果缓存）。"""
        key = (self._layout_mode, tuple(sorted(self._size_overrides.items())) if self._size_overrides else None)
        cached = _CARD_CONFIG_CACHE.get(key)
        if cached is not None:
            return cached
        base = dict(self.SIZE_CONFIG[self._layout_mode])
        if self._size_overrides:
            base.update(self._size_overrides)
        _CARD_CONFIG_CACHE[key] = base
        return base

    def _get_colors(self) -> dict:
        """获取当前主题颜色（按主题缓存，切换时以 is_dark_theme 为 key 失效）。"""
        key = tm.is_dark_theme()
        cached = _INFO_CARD_COLORS_CACHE.get(key)
        if cached is not None:
            return cached
        colors = {
            "bg": tm.alpha_of(tm.surface, 85),
            "border": tm.alpha_of(tm.mid, 30),
            "title": tm.text,
            "subtitle": tm.mid,
            "desc": tm.alpha_of(tm.mid, 60),
            "icon": tm.mid,
            # hover 反馈遮罩：infocard 背景 G 色（surface/g1 token），左端全透明 → 右端 G 色 90% 不透明度
            "hover_overlay": tm.alpha_of(tm.surface, 90),
        }
        _INFO_CARD_COLORS_CACHE[key] = colors
        return colors

    def _init_style_colors(self) -> None:
        """从全局主题（tm）获取卡片状态颜色，与 FileCardDelegate 保持一致。

        背景/边框/选中态颜色全部取自 V2 主题令牌（surface/mid/accent/text），
        保证深色/浅色模式下卡片颜色始终跟随全局主题切换，而不是旧的
        SettingsManager V1 颜色配置（V1 的 base_color 等是旧 UI 的浅色默认值，
        在深色模式下会导致卡片背景错误地呈现为白色）。
        """
        # 与 FileCardDelegate._get_colors() 的取值一致：
        # - 正常/选中态背景：surface 85% 透明度
        # - hover 背景：surface 90% 透明度
        # - 边框：mid 30% / 40% 透明度
        # - 选中态：accent 40% 填充（alpha≈102）+ accent 完整边框
        # - 预览态边框：text 色（对应 FileBlockCard 的 secondary_color 语义）
        normal_bg = tm.alpha_of(tm.surface, 85)
        normal_border = tm.alpha_of(tm.mid, 30)
        hover_bg = tm.alpha_of(tm.surface, 90)
        hover_border = tm.alpha_of(tm.mid, 40)
        selected_bg = tm.alpha_of(tm.accent, 40)
        selected_border = QColor(tm.accent)

        self._style_colors = {
            "normal_bg": normal_bg,
            "normal_border": normal_border,
            "hover_bg": hover_bg,
            "hover_border": hover_border,
            "selected_bg": selected_bg,
            "selected_border": selected_border,
        }

        # 无条件初始化动画颜色属性（确保从全局主题正确加载）
        self._anim_bg_color = QColor(normal_bg)
        self._anim_border_color = QColor(normal_border)

        self._secondary_color = tm.text.name()

    def _get_secondary_color(self) -> QColor:
        """获取预览态边框颜色（主题 text 色，取自全局主题 tm）。"""
        return QColor(self._secondary_color)

    def _advance_preview_gradient(self) -> None:
        """推进预览态边框渐变焦点旋转（循环动画，16ms/帧）。"""
        self._preview_angle = (self._preview_angle + 1.0) % 360.0
        self.update()

    def _make_preview_gradient(self, rect: QRectF, angle_deg: float) -> QConicalGradient:
        """构建预览态边框流光渐变（角锥渐变，光斑沿圆周旋转）。

        角锥渐变颜色只与角度相关：沿边框一周颜色从主题色 30% 透明度 →
        峰值色 → 主题色 30% 透明度平滑过渡，两道光斑位于对侧并随
        start_angle 递增沿边框流动。峰值色主题感知：深色模式为白色，
        浅色模式为黑色（与背景形成对比）；谷值为主题色 30% 透明度。

        Args:
            rect: 卡片矩形（逻辑坐标）。
            angle_deg: 渐变起始角度（度），动画每帧递增实现旋转。

        Returns:
            可用于 QPen 笔刷的角锥渐变。
        """
        cx = rect.center().x()
        cy = rect.center().y()

        accent_30 = tm.alpha_of(tm.accent, 30)  # 主题色 30% 透明度
        peak = QColor(tm.white) if tm.is_dark_theme() else QColor(tm.black)

        gradient = QConicalGradient(cx, cy, angle_deg)
        gradient.setColorAt(0.0, accent_30)
        gradient.setColorAt(0.25, peak)         # 光斑 1 峰值（深色=白/浅色=黑）
        gradient.setColorAt(0.5, accent_30)
        gradient.setColorAt(0.75, peak)         # 光斑 2 峰值（对侧）
        gradient.setColorAt(1.0, accent_30)
        return gradient

    def set_selected(self, selected: bool) -> None:
        """设置选中状态。

        Args:
            selected: True 表示选中，False 表示取消选中。
        """
        if self._is_selected != selected:
            self._is_selected = selected
            if selected:
                # 保留当前 hover 状态：新规范下选中态 hover 仍叠加 25% 主题色覆盖层
                self._trigger_select_animation()
            else:
                self._trigger_deselect_animation()
            self.selection_changed.emit(selected, self._file_path)

    def set_previewing(self, previewing: bool) -> None:
        """设置预览状态。

        Args:
            previewing: True 表示预览中，False 表示取消预览。
        """
        if self._is_previewing != previewing:
            self._is_previewing = previewing
            if previewing:
                # 保留当前 hover 状态：新规范下预览态 hover 仍叠加 25% 主题色覆盖层
                self._trigger_preview_animation()
                # 预览态启动渐变边框旋转动画（循环，退出预览时停止）
                if not self._preview_anim_timer.isActive():
                    self._preview_anim_timer.start()
            else:
                self._preview_anim_timer.stop()
                self._preview_angle = 0.0
                self._trigger_unpreview_animation()
            self.preview_state_changed.emit(previewing, self._file_path)

    def _trigger_select_animation(self) -> None:
        """触发选中动画：背景和边框过渡到选中态颜色。"""
        if not self._style_colors:
            self._init_style_colors()
            return

        colors = self._style_colors
        self._hover_anim.stop()
        self._media_scale_anim.stop()

        # 创建并行动画组
        if not hasattr(self, "_select_anim_group"):
            self._anim_select_bg = QPropertyAnimation(self, b"anim_bg_color")
            self._anim_select_border = QPropertyAnimation(self, b"anim_border_color")
            self._select_anim_group = QParallelAnimationGroup()
            self._select_anim_group.addAnimation(self._anim_select_bg)
            self._select_anim_group.addAnimation(self._anim_select_border)
        else:
            self._select_anim_group.stop()

        self._anim_select_bg.setDuration(180)
        self._anim_select_bg.setEasingCurve(QEasingCurve.OutCubic)
        self._anim_select_bg.setStartValue(self._anim_bg_color)
        self._anim_select_bg.setEndValue(colors["selected_bg"])

        self._anim_select_border.setDuration(180)
        self._anim_select_border.setEasingCurve(QEasingCurve.OutCubic)
        self._anim_select_border.setStartValue(self._anim_border_color)
        self._anim_select_border.setEndValue(colors["selected_border"])

        self._select_anim_group.start()

    def _trigger_deselect_animation(self) -> None:
        """触发取消选中动画：背景和边框恢复到正常态颜色。"""
        if not self._style_colors:
            self._init_style_colors()
            return

        colors = self._style_colors

        if hasattr(self, "_select_anim_group"):
            self._select_anim_group.stop()

        # 创建并行动画组
        if not hasattr(self, "_deselect_anim_group"):
            self._anim_deselect_bg = QPropertyAnimation(self, b"anim_bg_color")
            self._anim_deselect_border = QPropertyAnimation(self, b"anim_border_color")
            self._deselect_anim_group = QParallelAnimationGroup()
            self._deselect_anim_group.addAnimation(self._anim_deselect_bg)
            self._deselect_anim_group.addAnimation(self._anim_deselect_border)
        else:
            self._deselect_anim_group.stop()

        self._anim_deselect_bg.setDuration(200)
        self._anim_deselect_bg.setEasingCurve(QEasingCurve.InOutQuad)
        self._anim_deselect_bg.setStartValue(self._anim_bg_color)
        self._anim_deselect_bg.setEndValue(colors["normal_bg"])

        self._anim_deselect_border.setDuration(200)
        self._anim_deselect_border.setEasingCurve(QEasingCurve.InOutQuad)
        self._anim_deselect_border.setStartValue(self._anim_border_color)
        self._anim_deselect_border.setEndValue(colors["normal_border"])

        self._deselect_anim_group.start()

    def _trigger_preview_animation(self) -> None:
        """触发预览动画：保持背景，边框过渡到 secondary_color，宽度翻倍。"""
        if not self._style_colors:
            self._init_style_colors()
            return

        self._hover_anim.stop()
        self._media_scale_anim.stop()
        if hasattr(self, "_select_anim_group"):
            self._select_anim_group.stop()
        if hasattr(self, "_deselect_anim_group"):
            self._deselect_anim_group.stop()

        secondary_qcolor = self._get_secondary_color()
        colors = self._style_colors

        # 目标背景：保持选中态或正常态
        target_bg = colors["selected_bg"] if self._is_selected else colors["normal_bg"]

        # 创建并行动画组
        if not hasattr(self, "_preview_anim_group"):
            self._anim_preview_bg = QPropertyAnimation(self, b"anim_bg_color")
            self._anim_preview_border = QPropertyAnimation(self, b"anim_border_color")
            self._preview_anim_group = QParallelAnimationGroup()
            self._preview_anim_group.addAnimation(self._anim_preview_bg)
            self._preview_anim_group.addAnimation(self._anim_preview_border)
        else:
            self._preview_anim_group.stop()

        self._anim_preview_bg.setDuration(180)
        self._anim_preview_bg.setEasingCurve(QEasingCurve.OutCubic)
        self._anim_preview_bg.setStartValue(self._anim_bg_color)
        self._anim_preview_bg.setEndValue(target_bg)

        self._anim_preview_border.setDuration(180)
        self._anim_preview_border.setEasingCurve(QEasingCurve.OutCubic)
        self._anim_preview_border.setStartValue(self._anim_border_color)
        self._anim_preview_border.setEndValue(secondary_qcolor)

        self._preview_anim_group.start()

    def _trigger_unpreview_animation(self) -> None:
        """触发取消预览动画：根据选中态恢复对应颜色。"""
        if not self._style_colors:
            self._init_style_colors()
            return

        colors = self._style_colors

        if hasattr(self, "_preview_anim_group"):
            self._preview_anim_group.stop()

        # 根据选中态决定目标颜色
        if self._is_selected:
            target_bg = colors["selected_bg"]
            target_border = colors["selected_border"]
        else:
            target_bg = colors["normal_bg"]
            target_border = colors["normal_border"]

        # 创建并行动画组
        if not hasattr(self, "_unpreview_anim_group"):
            self._anim_unpreview_bg = QPropertyAnimation(self, b"anim_bg_color")
            self._anim_unpreview_border = QPropertyAnimation(self, b"anim_border_color")
            self._unpreview_anim_group = QParallelAnimationGroup()
            self._unpreview_anim_group.addAnimation(self._anim_unpreview_bg)
            self._unpreview_anim_group.addAnimation(self._anim_unpreview_border)
        else:
            self._unpreview_anim_group.stop()

        self._anim_unpreview_bg.setDuration(200)
        self._anim_unpreview_bg.setEasingCurve(QEasingCurve.InOutQuad)
        self._anim_unpreview_bg.setStartValue(self._anim_bg_color)
        self._anim_unpreview_bg.setEndValue(target_bg)

        self._anim_unpreview_border.setDuration(200)
        self._anim_unpreview_border.setEasingCurve(QEasingCurve.InOutQuad)
        self._anim_unpreview_border.setStartValue(self._anim_border_color)
        self._anim_unpreview_border.setEndValue(target_border)

        self._unpreview_anim_group.start()

    # ── Public API ────────────────────────────────────────────

    def add_action(
        self,
        text: str,
        icon: str = "",
        variant: str = "secondary",
        size: str = "sm",
        callback=None,
    ):
        """Add an action button to the hover overlay.

        Args:
            text: 按钮文本。
            icon: 图标（文本字符或 SVG 文件路径）。
            variant: 按钮变体（primary/secondary/ghost/danger/info），传给 StyledButton。
            size: 按钮尺寸（sm/default/lg），传给 StyledButton。
            callback: 点击回调。
        """
        self._actions.append((text, icon, variant, size, callback))
        self._rebuild_overlay()

    def clear_actions(self):
        """Remove all action buttons from the overlay."""
        self._actions.clear()
        self._rebuild_overlay()

    def set_title(self, text: str):
        self._title = text
        self.update()

    def set_subtitle(self, text: str):
        self._subtitle = text
        self.update()

    def set_desc(self, text: str):
        self._desc = text
        self.update()

    def set_media_icon(self, icon: str):
        self._media_icon = icon
        self._media_pixmap = None
        self.update()

    def set_media_pixmap(self, pixmap):
        """Set a QPixmap to draw in the media area (overrides text icon)."""
        self._media_pixmap = pixmap
        self.update()

    def set_file_path(self, path: str):
        """Set identifier string emitted with the clicked signal."""
        self._file_path = path

    def set_overlay_enabled(self, enabled: bool):
        self._overlay_enabled = enabled
        self._rebuild_overlay()
        self.update()

    # 仅布局尺寸键参与缩放；文字字号（title/subtitle/desc）必须原样保留，
    # 与 FileCardDelegate._get_scaled_config 行为一致——Ctrl+滚轮缩放卡片
    # 时文字大小不跟随变化。weight/radius 等键同样原样保留，
    # 避免 title_weight=700 被放大为非法字重或在缩放后回落为默认值。
    _SCALABLE_SIZE_KEYS = ("padding", "gap", "media_size", "icon_size")

    def set_scale(self, scale: float, base_overrides: dict | None = None) -> None:
        """动态缩放卡片所有尺寸因子（0.5 ~ 2.0），匹配文件选择器 Ctrl+滚轮行为。

        Args:
            scale: 缩放系数。
            base_overrides: 缩放基准字典。传入时，尺寸键从该字典的 base 值乘以 scale
                计算新尺寸，非尺寸键（weight/radius 等）原样保留；缺省时使用
                ``SIZE_CONFIG`` 的默认值。这让调用方可以在缩放时保留自己的
                "设计值"（如紧凑型标题 10px），保证已存在卡片与新增卡片尺寸一致。
        """
        scale = max(0.5, min(2.0, scale))
        source = base_overrides if base_overrides else self.SIZE_CONFIG[self._layout_mode]
        overrides = {}
        for key, value in source.items():
            if key in self._SCALABLE_SIZE_KEYS:
                overrides[key] = max(1, int(value * scale))
            else:
                overrides[key] = value
        self._size_overrides = overrides
        self._apply_size()
        self.update()

    def update_overlay(self) -> None:
        """强制 overlay 子控件重绘（修复 QGraphicsEffect 缓存导致的不同步问题）。

        原理：overlay 使用了 QGraphicsOpacityEffect，Qt 内部会缓存 sourcePixmap。
        当父容器（QScrollArea）滚动时，子 widget 的几何位置已经跟随父容器更新，
        但 graphics effect 的缓存 pixmap 仍是滚动前的版本，导致 overlay 视觉上
        "跟不上"滚动。手动调用 update() 触发重新 grab pixmap 即可解决。
        """
        if self._overlay_widget is not None and self._overlay_widget.isVisible():
            self._overlay_widget.update()

    # ── Internal ──────────────────────────────────────────────

    def _calc_text_height(self, config: dict) -> int:
        """计算文字块（标题+副标题+描述）的实际总高度。

        供 _apply_size（卡片定高）与 paintEvent（文字块垂直居中）共用，
        保证两处对文字高度的度量一致。
        """
        # Calculate text height for sizing
        font_title = QFont("Microsoft YaHei UI", config["title_size"], config["title_weight"])
        fm = QFontMetrics(font_title)
        title_h = fm.height()

        subtitle_h = 0
        if self._subtitle:
            font_sub = QFont("Microsoft YaHei UI", config["subtitle_size"], config["subtitle_weight"])
            fm2 = QFontMetrics(font_sub)
            subtitle_h = fm2.height()

        desc_h = 0
        if self._desc:
            font_desc = QFont("Microsoft YaHei UI", config["desc_size"], config["desc_weight"])
            fm3 = QFontMetrics(font_desc)
            desc_h = fm3.height()

        text_gap = 4  # gap between text lines
        text_lines = 1 + (1 if self._subtitle else 0) + (1 if self._desc else 0)
        return title_h + subtitle_h + desc_h + text_gap * (text_lines - 1)

    def _apply_size(self):
        config = self._get_config()
        padding = config["padding"]

        text_height = self._calc_text_height(config)

        if self._layout_mode == "horizontal":
            media_size = config["media_size"]
            total_height = padding * 2 + max(media_size, text_height)
            total_width = padding * 2 + media_size + config["gap"] + 200
        else:
            media_size = config["media_size"]
            total_height = padding * 2 + media_size + config["gap"] + text_height
            total_width = padding * 2 + max(media_size, 200)

        self.setFixedHeight(total_height)
        self.setMinimumWidth(total_width)
        self.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Fixed)

    def _rebuild_overlay(self):
        """Create or update the overlay widget and its action buttons.

        Uses QGraphicsOpacityEffect so the entire overlay (background + buttons)
        fades in/out synchronously.
        """
        # Remove old overlay
        if self._overlay_widget:
            self._overlay_widget.deleteLater()
            self._overlay_widget = None
            self._overlay_buttons.clear()

        if not self._overlay_enabled or not self._actions:
            return

        # Create overlay widget
        self._overlay_widget = QWidget(self)
        self._overlay_widget.setAttribute(Qt.WA_StyledBackground, False)
        self._overlay_widget.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self._overlay_widget.raise_()
        self._overlay_widget.setGeometry(self.rect())

        config = self._get_config()
        radius = config["radius"]

        # QGraphicsOpacityEffect — whole widget (bg + buttons) fades together
        self._opacity_effect = QGraphicsOpacityEffect()
        self._opacity_effect.setOpacity(0.0)
        self._overlay_widget.setGraphicsEffect(self._opacity_effect)

        # G 色水平渐变背景：左端全透明 → 右端 G 色低透明度；整体淡入淡出交给 opacity effect
        # slide 传入当前值，避免重建后渐变窗口跳回全宽
        self._overlay_widget.setStyleSheet(
            self._overlay_background_stylesheet(radius, self._overlay_slide)
        )

        if self._layout_mode == "horizontal":
            # Horizontal row — buttons right-aligned
            layout = QHBoxLayout(self._overlay_widget)
            layout.setContentsMargins(16, 0, 16, 0)
            layout.setSpacing(8)
            layout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        else:
            # Vertical: 2x2 grid
            layout = QVBoxLayout(self._overlay_widget)
            layout.setContentsMargins(16, 16, 16, 16)
            layout.setSpacing(8)

            top_row = QHBoxLayout()
            top_row.setSpacing(8)
            bottom_row = QHBoxLayout()
            bottom_row.setSpacing(8)

            for i, (text, icon, variant, size, callback) in enumerate(self._actions):
                btn = StyledButton(text, variant=variant, size=size, icon=icon)
                if callback:
                    # QPushButton.clicked 携带 bool 参数，连接到一个丢弃多余参数的 lambda，
                    # 避免 bool 被透传给仅接受 file_path 字符串的回调函数。
                    btn.clicked.connect(lambda *args, cb=callback: cb())
                self._overlay_buttons.append(btn)
                if i < 2:
                    top_row.addWidget(btn, stretch=1)
                else:
                    bottom_row.addWidget(btn, stretch=1)

            layout.addLayout(top_row)
            if self._actions and len(self._actions) > 2:
                layout.addLayout(bottom_row)
            layout.addStretch()
            return

        for text, icon, variant, size, callback in self._actions:
            btn = StyledButton(text, variant=variant, size=size, icon=icon)
            if callback:
                # QPushButton.clicked 携带 bool 参数，连接到一个丢弃多余参数的 lambda，
                # 避免 bool 被透传给仅接受 file_path 字符串的回调函数。
                btn.clicked.connect(lambda *args, cb=callback: cb())
            self._overlay_buttons.append(btn)
            layout.addWidget(btn)

        # Initially hidden (opacity effect = 0, but we must keep visible so the
        # effect can animate from 0 → 1 on hover)
        self._overlay_widget.setVisible(False)

    def _overlay_background_stylesheet(self, radius: int, slide: float = 1.0) -> str:
        """生成 overlay 背景的 G 色水平渐变 QSS（左端透明 → 右端 G 色低透明度）。

        G 色取自 surface token（gray.g1 / gray_light.g1，即 infocard 背景色），
        随主题切换；右端不透明度取 90%。

        slide 控制渐变窗口起点 x1（0~1 比例）：slide=1 时窗口为整卡宽度
        [0,1]，slide<1 时窗口右移为 [1-slide, 1]——右缘始终固定于卡片右缘，
        widget 保持整卡几何不出界，四角由 border-radius 圆角约束，
        滑入/滑出动画期间不会以矩形边缘遮挡卡片圆角。
        """
        g = tm.surface
        base = f"rgba({g.red()},{g.green()},{g.blue()}"
        alpha = int(255 * 0.9)
        x1 = max(0.0, min(1.0, 1.0 - slide))
        return (
            "background: qlineargradient(x1:"
            f"{x1:.3f}, y1:0, x2:1, y2:0, "
            f"stop:0 {base},0), stop:0.2 {base},0), "
            f"stop:0.8 {base},{alpha}), stop:1 {base},{alpha}));"
            f"border-radius: {radius}px;"
        )

    def _update_overlay_visibility(self):
        """Sync the overlay widget's opacity effect + visibility with _overlay_opacity."""
        if not self._overlay_widget or not self._opacity_effect:
            return
        visible = self._overlay_opacity > 0.01 and not self._disabled
        self._overlay_widget.setVisible(visible)
        if visible:
            self._opacity_effect.setOpacity(min(1.0, self._overlay_opacity))

    def _update_overlay_geometry(self):
        """保持 hover overlay 与绘制内容同步，支持 x/y_offset 位移动画。

        滑入/滑出动画通过动态重建背景渐变 QSS（x1 随 slide 变化）实现，
        widget 始终占满整卡几何、右缘固定于卡片右缘，四角由 border-radius
        圆角约束——动画期间不会以矩形边缘遮挡卡片圆角。
        """
        if not self._overlay_widget:
            return
        rect = self.rect()
        if self._x_offset or self._y_offset:
            rect.translate(self._x_offset, self._y_offset)
        self._overlay_widget.setGeometry(rect)
        # 渐变窗口起点随 slide 变化（右缘固定于卡片右缘），重建背景 QSS
        if self._overlay_enabled and self._actions:
            self._overlay_widget.setStyleSheet(
                self._overlay_background_stylesheet(
                    self._get_config()["radius"], self._overlay_slide
                )
            )

    # ── Event handling ────────────────────────────────────────

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_overlay_geometry()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and not self._disabled:
            self._pressed = True
            self._animate_card_scale(0.97, 80, QEasingCurve.OutBack)
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._pressed = False
            self._animate_card_scale(1.0, 120, QEasingCurve.OutCubic)
            self.update()
            if self.rect().contains(event.position().toPoint()) and not self._disabled:
                self.clicked.emit(self._file_path)
        elif event.button() == Qt.RightButton:
            if self.rect().contains(event.position().toPoint()) and not self._disabled:
                self.right_clicked.emit(self._file_path)
        super().mouseReleaseEvent(event)

    def enterEvent(self, event):
        # 选中/预览态同样维护 _hovered（用于背景遮罩反馈），
        # 但不显示操作按钮 overlay（保留原设计：状态卡片不浮出按钮层）
        self._hovered = True
        if not self._disabled:
            if not (self._is_selected or self._is_previewing):
                self._animate_overlay(1.0)
            if _HOVER_MEDIA_ANIM_ENABLED:
                self._animate_media_scale(1.05)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._pressed = False
        if not (self._is_selected or self._is_previewing):
            self._animate_overlay(0.0)
        if _HOVER_MEDIA_ANIM_ENABLED:
            self._animate_media_scale(1.0)
        self._animate_card_scale(1.0)
        super().leaveEvent(event)

    # ── Animations ────────────────────────────────────────────

    def _animate_overlay(self, target: float):
        """同时驱动遮罩淡入淡出与从右侧滑入/滑出（opacity + slide 同步）。"""
        self._hover_anim.stop()
        self._slide_anim.stop()
        d = abs(target - self._overlay_opacity)
        duration = max(50, int(400 * d))
        self._hover_anim.setDuration(duration)
        self._hover_anim.setStartValue(self._overlay_opacity)
        self._hover_anim.setEndValue(target)
        self._hover_anim.start()
        self._slide_anim.setDuration(duration)
        self._slide_anim.setStartValue(self._overlay_slide)
        self._slide_anim.setEndValue(target)
        self._slide_anim.start()

    def _animate_media_scale(self, target: float):
        """动画过渡图标缩放（非线性缓动 OutBack）。

        固定时长保证缓动可见：原实现按位移比例计算时长，hover 目标位移仅
        0.05 时被 max(50) 压缩成 50ms 瞬移，OutBack 缓动几乎不可见。
        220ms 与 overlay 淡入（250ms OutCubic）节奏协调，hover 进入时
        图标轻微回弹放大，离开时平滑复位。
        """
        self._media_scale_anim.stop()
        self._media_scale_anim.setDuration(220)
        self._media_scale_anim.setStartValue(self._media_scale)
        self._media_scale_anim.setEndValue(target)
        self._media_scale_anim.start()

    def _animate_card_scale(self, target: float, duration: int = 120, easing=QEasingCurve.OutCubic):
        self._card_scale_anim.stop()
        self._card_scale_anim.setDuration(duration)
        self._card_scale_anim.setEasingCurve(easing)
        self._card_scale_anim.setStartValue(self._card_scale)
        self._card_scale_anim.setEndValue(target)
        self._card_scale_anim.start()

    # ── Paint ─────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        if not painter.isActive():
            return

        try:
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setRenderHint(QPainter.TextAntialiasing)
            painter.setPen(Qt.NoPen)

            config = self._get_config()
            colors = self._get_colors()
            padding = config["padding"]
            radius = config["radius"]
            gap = config["gap"]

            w = self.width()
            h = self.height()

            opacity = (0.5 if self._disabled else 1.0) * self._card_opacity
            painter.setOpacity(opacity)
            # 不使用 painter.translate()，避免边框和背景渲染问题
            # 所有绘制坐标直接使用控件坐标系统

            # Card background and border - 考虑选中态和预览态
            # 边框宽度：预览态 2px，其他状态 1px
            border_width = 2 if self._is_previewing else 1

            # 背景：选中态 = accent 40% 覆盖层，其余 = 默认背景
            bg_color = (
                self._anim_bg_color
                if self._is_selected
                else colors["bg"]
            )

            # 边框：预览态 = 主题色→G1 径向渐变（焦点旋转动画）；其余按状态
            if self._is_previewing:
                border_brush = QBrush(
                    self._make_preview_gradient(QRectF(0, 0, w, h), self._preview_angle)
                )
            elif self._is_selected:
                # 选中态使用动画边框色
                border_brush = QBrush(self._anim_border_color)
            elif self._hovered and not self._disabled:
                border_brush = QBrush(colors["border"])
            else:
                border_brush = QBrush(self._anim_border_color)

            # 使用内缩绘制方式，确保边框不被裁切（参考 file_horizontal_card._paint_card_surface）
            # drawRect 从 (0,0) 开始绘制，边框宽度的一半会超出控件边界被裁切
            # 解决方法：使用 adjusted 将矩形向内收缩 border_width/2
            # 注意：translate 后坐标原点已偏移，draw_rect 从 (0,0) 开始是相对于偏移后的原点
            draw_rect = QRectF(0, 0, w, h).adjusted(
                border_width / 2.0,
                border_width / 2.0,
                -border_width / 2.0,
                -border_width / 2.0,
            )

            # 同时设置画笔和画刷，一次调用绘制背景和边框
            painter.setPen(QPen(border_brush, border_width))
            painter.setBrush(bg_color)
            painter.drawRoundedRect(draw_rect, radius, radius)

            painter.setPen(Qt.NoPen)

            # hover 反馈（所有状态统一）：infocard 背景 G 色（surface）水平渐变遮罩，整体从右侧滑入 + 淡入淡出
            # 渐变映射（相对卡片宽度）：0–0.2 全透明，0.2–0.8 渐变到 G 色，0.8–1.0 保持 G 色
            # 绘制条件含动画进行中：鼠标移出（_hovered=False）时动画仍反向滑出/淡出，不会直接消失
            if (self._hovered or self._overlay_slide > 0.01 or self._overlay_opacity > 0.01) and not self._disabled:
                x_shift = w * (1.0 - self._overlay_slide)
                painter.save()
                # 遮罩受整卡圆角裁切：clip 用整卡 (0,0,w,h) 圆角，
                # 滑入过程中遮罩右缘轮廓与卡片圆角完全重合，不会遮盖卡片圆角
                clip_path = QPainterPath()
                clip_path.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
                painter.setClipPath(clip_path)
                # 透明度随动画进度缩放（拷贝共享缓存色，不修改缓存对象）
                overlay_color = QColor(colors["hover_overlay"])
                overlay_color.setAlpha(
                    int(colors["hover_overlay"].alpha() * self._overlay_opacity)
                )
                hover_grad = QLinearGradient(0, 0, w, 0)
                hover_grad.setColorAt(0.0, tm.transparent)
                hover_grad.setColorAt(0.2, tm.transparent)
                hover_grad.setColorAt(0.8, overlay_color)
                hover_grad.setColorAt(1.0, overlay_color)
                painter.setBrush(QBrush(hover_grad))
                # 面板尺寸与卡片同轮廓（整卡 (0,0,w,h)），随 slide 平移；
                # 无论滑入滑出，右缘轮廓始终由整卡圆角 clip 决定，与卡片圆角完全重合
                panel_rect = QRectF(x_shift, 0, w, h)
                painter.drawRoundedRect(panel_rect, radius, radius)
                painter.restore()

            # ── Media Area ──
            media_size = config["media_size"]
            icon_size = config["icon_size"]

            # 应用 x/y_offset 偏移到媒体布局
            if self._layout_mode == "horizontal":
                media_x = padding + self._x_offset
                media_y = (h - media_size) / 2.0 + self._y_offset
            else:
                media_x = (w - media_size) / 2.0 + self._x_offset
                media_y = padding + self._y_offset

            # Scale media on hover
            current_media_scale = self._media_scale
            if current_media_scale != 1.0:
                painter.save()
                cx = media_x + media_size / 2.0
                cy = media_y + media_size / 2.0
                painter.translate(cx, cy)
                painter.scale(current_media_scale, current_media_scale)
                painter.translate(-cx, -cy)

            media_rect = QRectF(media_x, media_y, media_size, media_size)

            # Media content — 无灰色背景填充，图标直接绘制，尺寸为 media 区域 × _MEDIA_ICON_SCALE
            # （与 FileCardDelegate._draw_icon_pixmap 一致，参考 FileBlockCard._draw_scaled_pixmap）
            if self._media_pixmap and not self._media_pixmap.isNull():
                # DPR 感知：QPixmap.width() 返回物理像素，除以 DPR 得逻辑尺寸
                pix = self._media_pixmap
                dpr = pix.devicePixelRatio()
                lw = pix.width() / dpr if dpr > 0 else pix.width()
                lh = pix.height() / dpr if dpr > 0 else pix.height()
                if lw > 0 and lh > 0:
                    display_size = int(media_size * _MEDIA_ICON_SCALE)
                    # 等比缩放至填满显示尺寸。注意 scaled() 保留原 DPR：目标尺寸必须用
                    # 物理像素（display_size × dpr），否则高 DPI 下逻辑尺寸会缩小 dpr 倍
                    #（恰好同尺寸时跳过缩放，避免无谓拷贝）
                    if lw != display_size or lh != display_size:
                        target_phys = max(1, int(display_size * dpr))
                        pix = pix.scaled(target_phys, target_phys,
                                         Qt.KeepAspectRatio, Qt.SmoothTransformation)
                        dpr = pix.devicePixelRatio()
                        lw = pix.width() / dpr
                        lh = pix.height() / dpr
                    # 以 media 区域中心为基准居中
                    offset_x = int(media_rect.center().x() - lw / 2.0)
                    offset_y = int(media_rect.center().y() - lh / 2.0)
                    painter.drawPixmap(offset_x, offset_y, pix)
            elif self._media_icon:
                # 字号按放大后的图标尺寸比例计算，视觉占比与填满的图标一致
                icon_font = QFont(
                    "Segoe UI Symbol",
                    max(icon_size, int(media_size * 0.6 * _MEDIA_ICON_SCALE)),
                    QFont.Normal,
                )
                painter.setFont(icon_font)
                if self._disabled:
                    painter.setPen(tm.alpha_of(tm.mid, 60))
                else:
                    painter.setPen(colors["icon"])
                painter.drawText(
                    media_rect,
                    Qt.AlignCenter,
                    self._media_icon,
                )

            if current_media_scale != 1.0:
                painter.restore()

            # ── Text Area ──
            # 应用 x/y_offset 偏移到文字布局
            if self._layout_mode == "horizontal":
                text_x = media_x + media_size + gap + self._x_offset
                # 文字块整体垂直居中，与文件选择器 list 模式卡片排列一致
                text_block_h = self._calc_text_height(config)
                text_y = (h - text_block_h) / 2.0 + self._y_offset
                text_w = w - text_x - padding
                text_h = text_block_h
            else:
                text_x = padding + self._x_offset
                text_y = media_y + media_size + gap + self._y_offset
                text_w = w - padding * 2
                text_h = h - text_y - padding

            text_rect = QRectF(text_x, text_y, text_w, text_h)
            self._draw_text(painter, text_rect, config, colors)

            # Grayscale filter for disabled
            if self._disabled:
                painter.setOpacity(0.5)

        finally:
            if painter.isActive():
                painter.end()

    def _draw_text(self, painter: QPainter, rect: QRectF, config: dict, colors: dict):
        """Draw title, subtitle, and description text lines."""
        y = rect.y()
        x = rect.x()
        max_w = rect.width()
        line_gap = 4

        # Title
        if self._title:
            font = QFont("Microsoft YaHei UI", config["title_size"], config["title_weight"])
            painter.setFont(font)
            if self._disabled:
                painter.setPen(tm.alpha_of(tm.mid, 60))
            else:
                painter.setPen(colors["title"])
            fm = QFontMetrics(font)
            elided = fm.elidedText(self._title, Qt.ElideRight, int(max_w))
            painter.drawText(QRectF(x, y, max_w, fm.height()), Qt.AlignLeft | Qt.AlignTop, elided)
            y += fm.height() + line_gap

        # Subtitle
        if self._subtitle:
            font = QFont("Microsoft YaHei UI", config["subtitle_size"], config["subtitle_weight"])
            painter.setFont(font)
            if self._disabled:
                painter.setPen(tm.alpha_of(tm.mid, 60))
            else:
                painter.setPen(colors["subtitle"])
            fm = QFontMetrics(font)
            elided = fm.elidedText(self._subtitle, Qt.ElideRight, int(max_w))
            painter.drawText(QRectF(x, y, max_w, fm.height()), Qt.AlignLeft | Qt.AlignTop, elided)
            y += fm.height() + line_gap

        # Description
        if self._desc:
            font = QFont("Microsoft YaHei UI", config["desc_size"], config["desc_weight"])
            painter.setFont(font)
            if self._disabled:
                painter.setPen(tm.alpha_of(tm.mid, 60))
            else:
                painter.setPen(colors["desc"])
            fm = QFontMetrics(font)
            # Word wrap the description
            text_rect = QRectF(x, y, max_w, rect.bottom() - y)
            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, self._desc)
