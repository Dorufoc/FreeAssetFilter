"""Styled Button component - matches web button exactly."""

from PySide6.QtWidgets import QPushButton, QWidget, QSizePolicy
from PySide6.QtCore import Qt, QRectF, QTimer, QPropertyAnimation, QEasingCurve, Property
from PySide6.QtGui import QPainter, QColor, QPaintEvent, QFont, QPen, QFontMetrics, QIcon, QPixmap
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtSvg import QSvgRenderer
from pathlib import Path
import math
from theme import tm

class StyledButton(QPushButton):
    """A styled button matching the web component exactly.
    
    Variants: primary, secondary, ghost, danger, info
    Sizes: sm, default, lg
    Icon modes: text-only, icon-only, icon+text
    Icon position: left (default), right
    """

    @staticmethod
    def _get_color_map():
        return {
            ("primary", "bg"): tm.accent,
            ("primary", "bg_hover"): tm.accent_hover,
            ("primary", "bg_active"): tm.accent_active,
            ("primary", "text"): tm.white,
            ("primary", "shadow"): tm.accent_alpha(76),
            ("secondary", "bg"): tm.alpha_of(tm.mid, 20),
            ("secondary", "bg_hover"): tm.alpha_of(tm.mid, 50),
            ("secondary", "bg_active"): tm.alpha_of(tm.mid, 40),
            ("secondary", "text"): tm.text,
            ("secondary", "text_hover"): tm.text,
            ("secondary", "border"): tm.alpha_of(tm.mid, 40),
            ("secondary", "border_hover"): tm.alpha_of(tm.mid, 60),
            ("ghost", "bg"): tm.transparent,
            ("ghost", "bg_hover"): tm.alpha_of(tm.text, 15),
            ("ghost", "bg_active"): tm.alpha_of(tm.text, 15),
            ("ghost", "text"): tm.text,
            ("ghost", "text_hover"): tm.text,
            ("danger", "bg"): tm.transparent,
            ("danger", "bg_hover"): tm.alpha_of(tm.danger, 10),
            ("danger", "bg_active"): tm.alpha_of(tm.danger, 10),
            ("danger", "text"): tm.danger,
            ("info", "bg"): tm.transparent,
            ("info", "bg_hover"): tm.alpha_of(tm.info, 10),
            ("info", "bg_active"): tm.alpha_of(tm.info, 10),
            ("info", "text"): tm.info,
        }

    VARIANTS = ["primary", "secondary", "ghost", "danger", "info"]
    SIZES = ["sm", "default", "lg"]

    SIZE_CONFIG = {
        "sm": {"padding_h": 11, "padding_v": 4, "font_size": 10, "radius": 4, "icon_btn": (24, 24)},
        "default": {"padding_h": 16, "padding_v": 6, "font_size": 10, "radius": 5, "icon_btn": (29, 29)},
        "lg": {"padding_h": 22, "padding_v": 10, "font_size": 12, "radius": 8, "icon_btn": (35, 35)},
    }

    def __init__(
        self,
        text: str = "",
        variant: str = "primary",
        size: str = "default",
        icon: str = "",
        block: bool = False,
        loading: bool = False,
        parent=None,
        icon_position: str = "left",
    ):
        super().__init__(text, parent)
        self._variant = variant if variant in self.VARIANTS else "primary"
        self._size = size if size in self.SIZES else "default"
        self._icon = icon
        self._svg_renderer = None  # 存储 SVG 渲染器（矢量渲染）
        self._svg_icon_path = None  # 存储 SVG 文件路径
        self._svg_content_cache = {}  # 缓存不同颜色的 SVG 渲染器
        self._block = block
        self._loading = loading
        self._icon_position = icon_position if icon_position in ("left", "right") else "left"
        self._state = "normal"
        self._hovered = False
        self._pressed = False
        self._spinner_angle = 0
        self._scale = 1.0
        self._scale_anim = None

        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setFlat(True)
        self.setFocusPolicy(Qt.NoFocus)

        # 加载 SVG 图标（如果 icon 是文件路径）
        if icon and (icon.endswith('.svg') or Path(icon).exists()):
            self._load_svg_icon(icon)
        
        if self._loading:
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._spin)
            self._timer.start(30)

        self._apply_size()
        self.update()

    def _load_svg_icon(self, icon_path: str) -> None:
        """加载 SVG 图标文件（使用 QSvgRenderer 矢量渲染）"""
        try:
            path = Path(icon_path)
            if path.exists() and path.is_file():
                # 直接存储路径，在渲染时动态修改颜色
                self._svg_icon_path = icon_path
                self._icon = ""  # 清空文本图标，使用 SVG
        except Exception:
            pass  # 如果加载失败，保持原有文本图标

    def set_svg_icon(self, svg_path: str) -> None:
        """Change the SVG icon at runtime (for play/pause toggle etc.)."""
        self._icon = ""
        self._load_svg_icon(svg_path)
        self._svg_content_cache.clear()
        self.update()
    
    def _get_colored_svg_content(self, color: QColor) -> str:
        """获取带颜色的 SVG 内容（修改 SVG XML）"""
        if not self._svg_icon_path:
            return ""
        
        try:
            # 读取 SVG 文件
            with open(self._svg_icon_path, 'r', encoding='utf-8') as f:
                svg_content = f.read()
            
            # 先通过 tm.process_svg() 将 #FFF→surface, #000→text
            svg_content = tm.process_svg(svg_content)
            
            # 将颜色转换为 SVG 格式（#RRGGBB）
            color_hex = color.name()
            
            # 替换所有剩余的 fill 和 stroke 颜色（保留 transparent）
            import re
            svg_content = re.sub(
                r'(fill|stroke)="(?!transparent)[^"]*"',
                lambda m: f'{m.group(1)}="{color_hex}"',
                svg_content
            )
            
            # 对没有 fill 属性的 SVG 根元素添加默认 fill
            # 处理例如 github.svg/setting.svg 中 path 元素无 fill 属性的情况
            svg_content = re.sub(
                r'(<svg\b[^>]*)(>)',
                lambda m: f'{m.group(1)} fill="{color_hex}"{m.group(2)}'
                if 'fill=' not in m.group(1) else m.group(0),
                svg_content,
                count=1
            )
            
            return svg_content
        except Exception:
            return ""

    def _spin(self):
        self._spinner_angle = (self._spinner_angle + 6) % 360
        self.update()

    # ── Scale property for animation ─────────────────────────────

    @Property(float)
    def scale(self):
        return self._scale

    @scale.setter
    def scale(self, value: float):
        self._scale = value
        self.update()

    def _animate_scale(self, target: float, duration: int = 120, easing=QEasingCurve.OutCubic):
        """Animate scale to target value using stored animation."""
        self._scale_anim = QPropertyAnimation(self, b"scale")
        self._scale_anim.setDuration(duration)
        self._scale_anim.setEasingCurve(easing)
        self._scale_anim.setStartValue(self._scale)
        self._scale_anim.setEndValue(target)
        self._scale_anim.start()
        return self._scale_anim

    def _has_icon_and_text(self) -> bool:
        """Check if both icon and text are present."""
        return bool(self._icon and self.text())

    def _apply_size(self):
        config = self.SIZE_CONFIG[self._size]
        if (self._icon or self._svg_icon_path) and not self.text():
            # Icon-only button (text icon or SVG)
            w, h = config["icon_btn"]
            self.setFixedSize(int(w * 1.2), int(h * 1.2))
        elif self._block:
            base_h = 28 if self._size == "sm" else (40 if self._size == "lg" else 32)
            self.setMinimumHeight(int(base_h * 1.2))
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        else:
            base_h = 28 if self._size == "sm" else (40 if self._size == "lg" else 32)
            self.setMinimumHeight(int(base_h * 1.2))
            # Set minimum width based on text + padding to prevent squeezing
            text = self.text()
            if text:
                font = QFont("Microsoft YaHei UI", config["font_size"], QFont.Normal)
                fm = QFontMetrics(font)
                text_w = fm.horizontalAdvance(text)
                padding = config["padding_h"] * 2
                self.setMinimumWidth(text_w + padding)

    def _get_colors(self) -> dict:
        color_map = self._get_color_map()
        colors = {}
        for key in ("bg", "bg_hover", "bg_active", "text", "text_hover", "border", "border_hover", "shadow"):
            c = color_map.get((self._variant, key))
            if c is not None:
                colors[key] = c
        return colors

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._state = "active"
            self._pressed = True
            self._animate_scale(0.99, 80, QEasingCurve.OutBack)
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._pressed = False
            if self._hovered:
                self._state = "hover"
            else:
                self._state = "normal"
            self._animate_scale(1.0, 120, QEasingCurve.OutCubic)
            self.update()
        super().mouseReleaseEvent(event)

    def enterEvent(self, event):
        self._hovered = True
        self._state = "hover"
        self._animate_scale(1.0, 120, QEasingCurve.OutCubic)
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._pressed = False
        self._state = "normal"
        self._animate_scale(1.0, 120, QEasingCurve.OutCubic)
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event: QPaintEvent):
        colors = self._get_colors()
        config = self.SIZE_CONFIG[self._size]
        _shadow_color = tm.accent_alpha(76) or tm.alpha_of(tm.accent, 30)

        # Determine colors based on state
        if not self.isEnabled():
            bg = tm.alpha_of(tm.mid, 20) or tm.fill
            text_color = tm.alpha_of(tm.mid, 40) or tm.mid
        elif self._state == "active":
            bg = colors.get("bg_active", colors["bg"])
            text_color = colors.get("text_hover", colors["text"])
        elif self._state == "hover":
            bg = colors.get("bg_hover", colors["bg"])
            text_color = colors.get("text_hover", colors["text"])
        else:
            bg = colors["bg"]
            text_color = colors["text"]

        # Base button size (before scale)
        is_icon_only = self._icon and not self.text()
        has_icon_text = self._has_icon_and_text()

        if is_icon_only:
            btn_w = config["icon_btn"][0]
            btn_h = config["icon_btn"][1]
        elif self._block:
            btn_w = self.width()
            btn_h = 28 if self._size == "sm" else (40 if self._size == "lg" else 32)
        else:
            btn_w = self.width()
            btn_h = 28 if self._size == "sm" else (40 if self._size == "lg" else 32)

        # Center the button in the widget
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        btn_x = cx - btn_w / 2.0
        btn_y = cy - btn_h / 2.0

        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing)
            if not self.isEnabled():
                painter.setOpacity(0.4)

            # Draw press shadow (1.0 to 0.99 range, 0 offset) - before transform
            if self._variant == "primary" and self.isEnabled() and self._scale < 1.0:
                press_shadow_opacity = (1.0 - self._scale) / 0.01 * 0.3  # scale 0.99->1.0 maps to opacity 0.3->0
                painter.setOpacity(press_shadow_opacity)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(_shadow_color.red(), _shadow_color.green(), _shadow_color.blue(), int(255 * press_shadow_opacity)))
                press_shadow_rect = QRectF(btn_x, btn_y, btn_w, btn_h)
                painter.drawRoundedRect(press_shadow_rect, config["radius"], config["radius"])
                painter.setOpacity(1.0)

            # Apply scale transform around button center
            if self._scale != 1.0:
                painter.translate(cx, cy)
                painter.scale(self._scale, self._scale)
                painter.translate(-cx, -cy)

            # Draw shadow for primary button
            if self._variant == "primary" and self.isEnabled():
                shadow_opacity = 0.3
                if self._state == "hover":
                    shadow_opacity = 0.4
                elif self._state == "active":
                    shadow_opacity = 0.2
                painter.setOpacity(shadow_opacity)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(_shadow_color.red(), _shadow_color.green(), _shadow_color.blue(), int(255 * shadow_opacity)))
                shadow_rect = QRectF(btn_x, btn_y + 2, btn_w, btn_h)
                painter.drawRoundedRect(shadow_rect, config["radius"], config["radius"])
                painter.setOpacity(1.0 if self.isEnabled() else 0.4)

            # Draw background
            painter.setPen(Qt.NoPen)
            painter.setBrush(bg)
            painter.drawRoundedRect(
                QRectF(btn_x, btn_y, btn_w, btn_h),
                config["radius"],
                config["radius"],
            )

            # Draw loading spinner
            if self._loading:
                spinner_cx = cx
                spinner_cy = cy
                r = 7
                painter.setPen(QPen(tm.alpha_of(tm.text, 63), 2))
                painter.setBrush(Qt.NoBrush)
                painter.drawArc(
                    int(spinner_cx - r), int(spinner_cy - r),
                    int(r * 2), int(r * 2),
                    self._spinner_angle * 16,
                    270 * 16
                )
                return

            font_size = config["font_size"]

            # Draw icon + text combination
            if has_icon_text:
                icon_size = max(font_size, 14)
                font_icon = QFont("Segoe UI Symbol", icon_size, QFont.Normal)
                painter.setFont(font_icon)
                painter.setPen(text_color)

                # Calculate text width to adjust button sizing
                text_content = self.text()
                font_text = QFont("Microsoft YaHei UI", font_size, QFont.Normal)
                painter.setFont(font_text)
                text_metrics = painter.fontMetrics()
                text_width = text_metrics.horizontalAdvance(text_content)

                # Icon metrics
                painter.setFont(font_icon)
                icon_metrics = painter.fontMetrics()
                icon_w = icon_metrics.horizontalAdvance(self._icon)

                gap = 8  # gap between icon and text (matching web)
                content_w = icon_w + gap + text_width
                content_h = btn_h

                # Starting x position for centering content
                content_start_x = cx - content_w / 2
                content_y = btn_y

                if self._icon_position == "left":
                    # Draw icon
                    painter.setFont(font_icon)
                    painter.drawText(
                        QRectF(content_start_x, content_y, icon_w, content_h),
                        Qt.AlignCenter,
                        self._icon,
                    )
                    # Draw text
                    painter.setFont(font_text)
                    painter.drawText(
                        QRectF(content_start_x + icon_w + gap, content_y, text_width, content_h),
                        Qt.AlignLeft | Qt.AlignVCenter,
                        text_content,
                    )
                else:  # icon on right
                    # Draw text
                    painter.setFont(font_text)
                    painter.drawText(
                        QRectF(content_start_x, content_y, text_width, content_h),
                        Qt.AlignLeft | Qt.AlignVCenter,
                        text_content,
                    )
                    # Draw icon
                    painter.setFont(font_icon)
                    painter.drawText(
                        QRectF(content_start_x + text_width + gap, content_y, icon_w, content_h),
                        Qt.AlignCenter,
                        self._icon,
                    )

            elif self._icon:
                # Icon-only button (文本图标)
                icon_font_size = max(font_size, 16)
                font = QFont("Segoe UI Symbol", icon_font_size, QFont.Normal)
                painter.setFont(font)
                painter.setPen(text_color)
                painter.drawText(
                    QRectF(btn_x, btn_y, btn_w, btn_h),
                    Qt.AlignCenter,
                    self._icon,
                )
            
            elif self._svg_icon_path:
                # SVG 图标按钮（完全矢量渲染，无位图转换）
                icon_size = max(font_size, 16)
                # 计算图标绘制区域，居中显示
                icon_rect = QRectF(cx - icon_size / 2, cy - icon_size / 2, icon_size, icon_size)
                
                # 获取带颜色的 SVG 内容
                colored_svg = self._get_colored_svg_content(text_color)
                
                if colored_svg:
                    # 检查缓存中是否有该颜色的渲染器
                    color_key = text_color.name()
                    if color_key not in self._svg_content_cache:
                        # 创建新的渲染器（动态修改颜色的 SVG）
                        renderer = QSvgRenderer(colored_svg.encode('utf-8'))
                        if renderer.isValid():
                            self._svg_content_cache[color_key] = renderer
                    
                    # 使用缓存的渲染器直接渲染（矢量，无锯齿）
                    renderer = self._svg_content_cache.get(color_key)
                    if renderer:
                        renderer.render(painter, icon_rect)

            elif self.text():
                # Text-only button
                font = QFont("Microsoft YaHei UI", font_size, QFont.Normal)
                painter.setFont(font)
                painter.setPen(text_color)
                painter.drawText(
                    QRectF(btn_x, btn_y, btn_w, btn_h),
                    Qt.AlignCenter,
                    self.text(),
                )
        finally:
            painter.end()
