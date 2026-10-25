"""
设置布局 — 设置窗口的内容区域（使用 StyledSidebar）
"""

from __future__ import annotations

import copy
import os
import time
import weakref
from typing import Any, Callable

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QFrame, QLabel, QStackedWidget,
    QApplication, QScrollArea, QFileDialog,
)
from PySide6.QtCore import (
    Qt, Signal, QRectF, QPropertyAnimation, QEasingCurve, Property, QPoint,
    QEvent, QObject, QTimer, QUrl,
)
from PySide6.QtGui import (
    QPainter, QColor, QPaintEvent, QPen, QFont, QHideEvent, QCloseEvent,
    QConicalGradient, QBrush, QPixmap, QDesktopServices,
)

from theme import tm
from theme.system_accent import get_system_accent_color
from components.styled_sidebar import StyledSidebar
from components.styled_toggle import StyledToggle
from components.styled_button import StyledButton
from components.styled_scroll_area import StyledScrollBar, StyledScrollArea
from components.styled_segmented import StyledSegmented
from components.styled_slider import StyledSlider
from components.settings_card import (
    SETTINGS_FIELD_LABEL_WIDTH,
    SETTINGS_GROUP_GAP,
    SETTINGS_LABEL_GAP,
    SETTINGS_ROW_GAP,
    SETTINGS_VALUE_LABEL_WIDTH,
    SettingsBlock,
    SettingsRow,
    apply_settings_desc_style,
    apply_settings_field_style,
    apply_settings_title_style,
    apply_settings_value_style,
)
from components.styled_dialog import create_basic_dialog, create_danger_dialog
from components.styled_color_picker import _ColorPanel
from components.custom_background import (
    BACKGROUND_DIR_NAME,
    import_custom_background_image,
)
from components.theme_transition_overlay import ThemeTransitionOverlay
from freeassetfilter.core.managers.settings_manager_v2 import (
    DEFAULT_SETTINGS_V2,
    SettingsManagerV2,
)
from freeassetfilter.core.native.platform_gpu import apply_gpu_profile
from freeassetfilter.core.native.platform_threads import apply_process_power_policy
from freeassetfilter.core.native.platform_timing import (
    get_active_profile as _get_timing_active_profile,
    set_active_profile as _set_timing_active_profile,
)
from freeassetfilter.services.update_service import (
    UpdateError,
    UpdateInfo,
    get_update_service,
)
from freeassetfilter.ui.layout import update_dialogs
from freeassetfilter.ui.layout.settings_staging_cache import SettingsStagingCache
from freeassetfilter.utils.app_logger import debug, warning
from freeassetfilter.utils.animation_settings import is_animation_enabled
from freeassetfilter.utils.path_utils import get_app_data_path
from freeassetfilter.ui.theme.app_stylesheet import register_widget_qss


# ── 自定义图像背景可调参数（与 components/custom_background 对齐） ──
# 模糊半径 px（整数 0-200，默认 0 不模糊），透明度 %（0-100，默认 80% 很透明）。
IMAGE_BG_BLUR_MAX = 200
IMAGE_BG_BLUR_DEFAULT = 0
IMAGE_BG_TRANSPARENCY_DEFAULT = 80

#: 设置窗口明暗过渡时长（ms）：整窗交叉淡入淡出（旧外观渐隐露出新主题）。
#: 比主窗口的径向扩散（450ms）略短，观感更轻快；时长即「点击后开始淡化
#: 到结束」的一段，不含点击到动画起钟的同步段（见 _start_settings_overlay）。
SETTINGS_THEME_FADE_MS = 300

#: 外观预览去抖窗口（ms）：连点 / 滑动条与色板拖动在此窗口内合并为一次
#: 下发。首击仍立即生效（见 ``SettingsLayout._request_appearance_preview``），
#: 因此单击零额外延迟、连点最多只多一次补发。
APPEARANCE_PREVIEW_DEBOUNCE_MS = 120

#: 子选项展开后的「最小必要滚动」参数：只在子项被视口裁掉时补滚，且
#: 只补到完整可见 + 少量留白；子项本来就可见时完全不滚动（中间选项不会
#: 因父开关变化而跳动）。
SETTINGS_SUB_SCROLL_MARGIN = 10  # 子项与视口上/下边缘的最小留白（px）
SETTINGS_SUB_SCROLL_MS = 180     # 最小必要滚动的缓动时长（ms）


def _normalize_bg_blur(value: object) -> int:
    """归一化图像背景模糊半径到 0~200px（整数）。

    Args:
        value: 待归一化值（非法输入回退默认值）。

    Returns:
        int: 钳制后的模糊半径。
    """
    try:
        blur = int(round(float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return IMAGE_BG_BLUR_DEFAULT
    return max(0, min(IMAGE_BG_BLUR_MAX, blur))


def _normalize_bg_transparency(value: object) -> int:
    """归一化图像背景透明度到 0~100。

    Args:
        value: 待归一化值（非法输入回退默认值）。

    Returns:
        int: 钳制后的透明度百分比。
    """
    try:
        transparency = int(round(float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return IMAGE_BG_TRANSPARENCY_DEFAULT
    return max(0, min(100, transparency))


def _refresh_settings_item_text(item: QWidget | None) -> None:
    """按统一 token 重注册设置项（行/块）的标题与描述样式，并重绘子选项箭头。

    主题切换时各页自行调用（替代历史上宿主通刷所有 QLabel 的做法——
    通刷会把描述文字与读数一并覆盖成标题字号/字重/颜色）。

    Args:
        item: ``SettingsRow`` / ``SettingsBlock`` 实例；None 时跳过。
    """
    if item is None:
        return
    title_label = getattr(item, "title_label", None)
    if title_label is not None:
        apply_settings_title_style(title_label)
    desc_label = getattr(item, "desc_label", None)
    if desc_label is not None:
        apply_settings_desc_style(desc_label)
    # 子选项箭头用 QPainter 直接取 tm 颜色，主题切换时需主动重绘。
    sub_branch = getattr(item, "_sub_branch", None)
    if sub_branch is not None:
        sub_branch.update()


# ── 关于页应用信息（logo + 名称 + 简介 + 版本行 + 链接行） ──
ABOUT_APP_NAME = "FreeAssetFilter"
ABOUT_APP_TAGLINE = "一款强大的多功能文件预览与管理工具，让文件浏览如丝般高效顺滑"
ABOUT_APP_LOGO_SIZE = 96
ABOUT_REPO_URL = "https://github.com/Dorufoc/FreeAssetFilter"
ABOUT_LICENSE_URL = "https://github.com/Dorufoc/FreeAssetFilter/blob/master/LICENSE"
#: 版本号与「检查更新」按钮之间的间隔（约一个制表位宽度）
ABOUT_VERSION_TAB_GAP = 40
#: 「联系我们」点击后在下方展开的联系信息
ABOUT_CONTACT_NAME = "Dorufoc"
ABOUT_CONTACT_EMAIL = "dorufoc@outlook.com"
#: 「联系我们」锚点伪协议（非外链：仅用于切换联系信息框显示）
ABOUT_CONTACT_SCHEME = "contact:"


def _app_version() -> str:
    """读取应用版本号（``FAFVERSION`` 首行，去前导 ``v``）；失败返回空串。"""
    try:
        from freeassetfilter.utils.path_utils import get_resource_path

        with open(get_resource_path("FAFVERSION"), "r", encoding="utf-8") as fh:
            line = fh.readline().strip()
    except Exception as exc:  # noqa: BLE001 - 读取失败不展示版本号，不阻断设置页
        debug(f"读取版本号失败：{exc}")
        return ""
    return line[1:].strip() if line[:1] in ("v", "V") else line


def _app_logo_pixmap(size: int) -> QPixmap:
    """加载应用 logo（``FAF-main.png``）并按设备像素比缩放。

    缩放目标为物理像素（逻辑尺寸 × devicePixelRatio），避免高分屏下模糊。
    资源缺失或加载失败时返回空 ``QPixmap``（调用方据此跳过图标显示）。
    """
    # 候选路径：打包感知的资源路径优先，失败时回退 icons 目录。
    candidates: list[str] = []
    try:
        from freeassetfilter.utils.path_utils import get_resource_path

        candidates.append(get_resource_path("freeassetfilter/icons/FAF-main.png"))
    except Exception:  # noqa: BLE001 - 路径工具异常时仅跳过该候选
        pass
    try:
        from freeassetfilter.core._paths import icons_dir

        candidates.append(str(icons_dir() / "FAF-main.png"))
    except Exception:  # noqa: BLE001 - 目录解析异常时仅跳过该候选
        pass

    pixmap = QPixmap()
    for path in candidates:
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            break
    if pixmap.isNull():
        return pixmap

    try:
        app = QApplication.instance()
        screen = app.primaryScreen() if app is not None else None
        dpr = float(screen.devicePixelRatio()) if screen is not None else 1.0
    except (RuntimeError, AttributeError, TypeError, ValueError):
        dpr = 1.0
    if dpr <= 0:
        dpr = 1.0
    target = max(1, int(round(size * dpr)))
    scaled = pixmap.scaled(target, target, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    scaled.setDevicePixelRatio(dpr)
    return scaled


# ── 预设主题色（参考旧 theme_editor.py） ──────────────────────────────
# "auto" 表示跟随 Windows 系统强调色（DWM ColorizationColor）。
PRESET_ACCENT_COLORS = [
    {"name": "自动", "color": "auto"},
    {"name": "活力蓝", "color": "#007AFF"},
    {"name": "热情红", "color": "#DD5940"},
    {"name": "蜂蜜黄", "color": "#EAB348"},
    {"name": "清新绿", "color": "#78B86C"},
    {"name": "魅力紫", "color": "#9554CF"},
    {"name": "清雅墨", "color": "#5A6C8B"},
]


class _FloatingScrollArea(QScrollArea):
    """设置页滚动区 — 浮动 StyledScrollBar + 丝滑滚动（参考文件选择器模式）。

    - 隐藏 QScrollArea 原生滚动条，由浮动 ``StyledScrollBar`` 接管
      （自绘圆角胶囊 + hover 展开 + 拖拽）。
    - 通过 ``attach_floating_bar_region`` 将浮动条锚定到所在外观卡片
      （#SettingsCard）右侧边框内侧——与文件选择器/文件池浮动滚动条的
      间距约定一致：右缘水平贴边（间隙 0）、上/下内缩 10*dpi。
    - 通过 ``StyledScrollArea.apply_to`` 施加平滑滚轮/触摸手势
      （QScroller 丝滑减速 + 边界弹性回弹），与文件选择器一致。
    - 背景保持透明，透出设置卡片底色；滚动条仅在内容溢出时可见。

    注意：本类不得重写 ``eventFilter``——PySide6 下 QScrollArea 子类一旦
    覆盖该虚函数，其构造期样式表 polish 路径会触发原生访问冲突（构造阶段
    虚表分发到尚未就绪的 Python 对象）。区域尺寸变化必然传导为滚动区自身
    的 resizeEvent，因此浮动条重定位挂接现有事件链即可，无需事件过滤器。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        register_widget_qss(self,("QScrollArea { background: transparent; border: none; }"))
        self.viewport().setAutoFillBackground(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # 浮动条相对所在区域内容矩形（边框内侧）的上/下内缩：与文件选择器/
        # 文件池浮动滚动条几何约定一致（10*dpi）；右缘水平贴边（间隙 0）
        self._edge_padding = int(10 * 1.0)
        # 锚定区域（外观卡片 #SettingsCard）；未锚定时回退为滚动区自身
        self._region: QWidget | None = None

        # 浮动滚动条：默认先挂在滚动区自身，attach_floating_bar_region
        # 会将父级改挂到锚定卡片上，使其贴卡片右缘悬浮（内容之上）
        self._floating_bar = StyledScrollBar(self)
        self._floating_bar.setFixedWidth(max(6, int(8 * 1.0)))
        self._floating_bar.raise_()

        # 与隐藏的原生垂直滚动条双向同步（value 相同不重发，无递归风险）
        vbar = self.verticalScrollBar()
        self._floating_bar.setRange(vbar.minimum(), vbar.maximum())
        self._floating_bar.setSingleStep(1)  # 平滑滚动的细粒度步进
        self._floating_bar.setPageStep(vbar.pageStep())
        vbar.rangeChanged.connect(self._on_range_changed)
        self._floating_bar.valueChanged.connect(vbar.setValue)
        vbar.valueChanged.connect(self._floating_bar.setValue)
        self._floating_bar.setVisible(vbar.maximum() > vbar.minimum())

        self._scroller_ready = False

    def attach_floating_bar_region(self, region: QWidget) -> None:
        """把浮动滚动条挂到所在区域（外观卡片 #SettingsCard）上并贴其右缘。

        文件选择器/文件池的浮动条均以各自内容区边框内侧为参照（右缘水平
        间隙 0、上/下内缩 edge_padding），这里把卡片内容矩形作为同等参照，
        使设置页滚动条与主窗口两侧滚动条的边缘间距逐像素一致。
        卡片缩放必然传导为滚动区 resizeEvent，由既有事件链触发重定位。
        """
        if region is self._region:
            return
        self._region = region
        self._floating_bar.setParent(region)
        self._floating_bar.raise_()
        self._reposition_bar()

    # ── 原生滚动条 → 浮动滚动条 同步 ─────────────────────────────────

    def _on_range_changed(self, minimum: int, maximum: int) -> None:
        """内容滚动范围变化：同步范围/步进并按需显隐浮动滚动条。"""
        vbar = self.verticalScrollBar()
        self._floating_bar.setRange(minimum, maximum)
        self._floating_bar.setPageStep(vbar.pageStep())
        self._floating_bar.setValue(vbar.value())
        self._floating_bar.setVisible(maximum > minimum)
        self._reposition_bar()

    # ── 几何：浮动滚动条贴所在区域右缘 ───────────────────────────────

    def _reposition_bar(self) -> None:
        """把浮动滚动条贴到所在区域（默认滚动区自身）右缘。

        内容不足时保持隐藏。几何以区域内容矩形（边框内侧）为参照：
        右缘水平贴边（间隙 0）、上/下内缩 edge_padding，
        与文件选择器/文件池浮动滚动条的间距约定逐像素一致。
        """
        bar = self._floating_bar
        if bar.parent() is None:
            return
        region = self._region if self._region is not None else self
        if region.width() <= 0 or region.height() <= 0:
            return
        pad = self._edge_padding
        cr = region.contentsRect()
        bar.setGeometry(
            cr.x() + cr.width() - bar.width(),
            cr.y() + pad,
            bar.width(),
            max(0, cr.height() - 2 * pad),
        )
        bar.raise_()

    # ── 事件：尺寸变化重摆滚动条；首次显示施加丝滑滚动 ────────────────

    def setWidget(self, widget: QWidget) -> None:
        super().setWidget(widget)
        # 新内容装载后立即同步范围（等待 rangeChanged 可能有帧延迟）
        vbar = self.verticalScrollBar()
        self._on_range_changed(vbar.minimum(), vbar.maximum())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._scroller_ready:
            self._scroller_ready = True
            # 平滑滚轮 + 触摸手势（与文件选择器同一套 QScroller 配置）
            StyledScrollArea.apply_to(self, enable_mouse_drag=False)
        self._reposition_bar()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # viewport 高度变化会改变 pageStep，一并同步
        self._floating_bar.setPageStep(self.verticalScrollBar().pageStep())
        self._reposition_bar()


class AccentColorButton(QWidget):
    """主题色选择圆形按钮 — 自绘圆形 + 选中描边。"""

    clicked = Signal(str)  # 发送颜色 hex 字符串

    def __init__(
        self,
        color_hex: str,
        name: str = "",
        center_text: str = "",
        value: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._color_hex = color_hex
        self._value = value if value else color_hex
        self._name = name
        self._center_text = center_text
        self._selected = False
        self._hovered = False
        self._hover_progress = 0.0
        self.setFixedSize(40, 40)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_StyledBackground, False)

        self._hover_anim = QPropertyAnimation(self, b"hover_progress")
        self._hover_anim.setDuration(180)
        self._hover_anim.setEasingCurve(QEasingCurve.InOutCubic)

    @Property(float)
    def hover_progress(self):
        return self._hover_progress

    @hover_progress.setter
    def hover_progress(self, value: float):
        self._hover_progress = value
        self.update()

    @property
    def color_hex(self) -> str:
        """Return the logical value (may be "auto" or a concrete #RRGGBB)."""
        return self._value

    @property
    def selected(self) -> bool:
        return self._selected

    @selected.setter
    def selected(self, value: bool):
        self._selected = value
        self.update()

    def enterEvent(self, event):
        self._hovered = True
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_progress)
        self._hover_anim.setEndValue(1.0)
        self._hover_anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_progress)
        self._hover_anim.setEndValue(0.0)
        self._hover_anim.start()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._color_hex)
            event.accept()
        else:
            super().mousePressEvent(event)

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setClipRect(self.rect())
        rect = QRectF(6, 6, self.width() - 12, self.height() - 12)

        # hover 时缩放
        scale = 1.0 + 0.1 * self._hover_progress
        cx = rect.center().x()
        cy = rect.center().y()
        sw = rect.width() * scale
        sh = rect.height() * scale
        scaled_rect = QRectF(cx - sw / 2, cy - sh / 2, sw, sh)

        # 外圈描边（选中时）
        if self._selected:
            pen = QPen(tm.accent, 3)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(scaled_rect.adjusted(-3, -3, 3, 3))

        # 主色圆
        painter.setPen(Qt.NoPen)
        bg_color = QColor(self._color_hex)
        painter.setBrush(bg_color)
        painter.drawEllipse(scaled_rect)

        # 中央文字（例如自动模式的 "A"）
        if self._center_text:
            text_color = self._contrast_text_color(bg_color)
            font = QFont("Microsoft YaHei UI", 14, QFont.Bold)
            painter.setFont(font)
            painter.setPen(text_color)
            painter.drawText(scaled_rect, Qt.AlignCenter, self._center_text)
        elif self._selected:
            # 选中对勾
            painter.setPen(
                QPen(QColor("#FFFFFF"), 2.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            )
            painter.setBrush(Qt.NoBrush)
            cx = scaled_rect.center().x()
            cy = scaled_rect.center().y()
            painter.drawLine(cx - 5, cy, cx - 1, cy + 4)
            painter.drawLine(cx - 1, cy + 4, cx + 6, cy - 4)
        painter.end()

    @staticmethod
    def _contrast_text_color(bg: QColor) -> QColor:
        """Return white or black text color depending on background luminance."""
        luminance = 0.299 * bg.red() + 0.587 * bg.green() + 0.114 * bg.blue()
        return QColor("#FFFFFF") if luminance < 128 else QColor("#000000")


class CustomAccentButton(QWidget):
    """自定义主题色按钮 — 360° 全色谱渐变圆 + 选中描边。"""

    clicked = Signal()

    def __init__(self, selected: bool = False, parent=None):
        super().__init__(parent)
        self._selected = selected
        self.setFixedSize(40, 40)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_StyledBackground, False)

    @property
    def selected(self) -> bool:
        return self._selected

    @selected.setter
    def selected(self, value: bool):
        self._selected = value
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
        else:
            super().mousePressEvent(event)

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setClipRect(self.rect())
        rect = QRectF(6, 6, self.width() - 12, self.height() - 12)

        # 360° 全色谱锥形渐变：红 → 黄 → 绿 → 青 → 蓝 → 紫 → 红
        gradient = QConicalGradient(rect.center(), 0)
        gradient.setColorAt(0.0 / 6, QColor("#FF0000"))
        gradient.setColorAt(1.0 / 6, QColor("#FFFF00"))
        gradient.setColorAt(2.0 / 6, QColor("#00FF00"))
        gradient.setColorAt(3.0 / 6, QColor("#00FFFF"))
        gradient.setColorAt(4.0 / 6, QColor("#0000FF"))
        gradient.setColorAt(5.0 / 6, QColor("#FF00FF"))
        gradient.setColorAt(6.0 / 6, QColor("#FF0000"))

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(gradient))
        painter.drawEllipse(rect)

        # 选中描边
        if self._selected:
            pen = QPen(tm.accent, 3)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(rect.adjusted(-3, -3, 3, 3))
        painter.end()


class _DarkToggleCompat(QObject):
    """旧深色开关的兼容垫片（非界面组件，仅保存量调用方）。

    新版设置已改用「白天 / 夜晚 / 跟随系统」三段控件，本类仅保留
    ``checked`` 读写与 ``toggled`` 信号，使 ``page._dark_toggle`` 与
    ``page._on_dark_toggle`` 的存量访问继续有效。读返回当前实际生效
    值（跟随模式下为系统解析结果），写等价于暂存夜晚/白天偏好
    （点击确定才生效）。
    """

    toggled = Signal(bool)

    def __init__(self, page: AppearanceSettingsPage) -> None:
        """初始化垫片。

        Args:
            page: 所属外观设置页（读写时代理到其主题方法）。
        """
        super().__init__(page)
        self._page = page

    @property
    def checked(self) -> bool:
        """当前实际是否为深色。

        Returns:
            深色返回 True，否则返回 False。
        """
        return tm.is_dark_theme()

    @checked.setter
    def checked(self, value: bool) -> None:
        self._page.apply_theme_mode("dark" if value else "light")
        self._page.sync_theme_segment()
        try:
            self.toggled.emit(bool(value))
        except Exception as exc:
            debug(f"主题切换信号转发失败：{exc}")


class AppearanceSettingsPage(QWidget):
    """外观设置页面 — 深色模式三段选择 + 主题色选择（暂存缓存优先）。

    深色模式为「白天 / 夜晚 / 跟随系统」三态分段控件（与「窗口背景」
    分段同款 ``StyledSegmented`` pill 样式）。暂存隔离铁律：所有控件
    修改只写入 ``SettingsStagingCache``，未提交前不触碰 ``tm``、主窗口
    与 ``SettingsManagerV2`` 磁盘状态；点击确定才全局应用并落盘。
    控件展示以缓存为准。
    """

    # 深色模式三态与分段索引的双向映射（顺序与 _build_ui 添加顺序一致）。
    THEME_MODES: tuple[str, ...] = ("light", "dark", "system")
    THEME_LABELS: tuple[str, ...] = ("白天", "夜晚", "跟随")
    THEME_INDEX: dict[str, int] = {"light": 0, "dark": 1, "system": 2}

    # 性能档位三态与分段索引的双向映射（顺序与 _build_ui 添加顺序一致）。
    # 取值与 SettingsManagerV2 PERFORMANCE_PROFILES / 三钩子对齐：
    # performance（性能） | balanced（均衡） | powersave（省电）。
    PROFILE_MODES: tuple[str, ...] = ("performance", "balanced", "powersave")
    PROFILE_LABELS: tuple[str, ...] = ("性能", "均衡", "省电")
    PROFILE_INDEX: dict[str, int] = {
        "performance": 0,
        "balanced": 1,
        "powersave": 2,
    }

    #: 外观类设置（深色模式 / 主题色 / 窗口背景模式与弥散开关）发生用户改动时发出。
    #: 宿主 ``SettingsLayout`` 据此做实时预览：立即下发 ``tm`` 与主窗口（带过渡），
    #: 设置窗口保持打开并以平滑过渡遮罩换肤。
    appearance_changed = Signal()
    #: 窗口背景可调参数（模糊度 / 透明度滑动条、自定义色板拖动）发生用户改动时发出。
    #: 与 :attr:`appearance_changed` 区分：宿主经去抖定时器合并连续改动后再预览一次，
    #: 避免拖动过程每帧重下发背景层。
    appearance_params_changed = Signal()
    #: 非外观项（性能档位）发生用户改动时发出，宿主据此刷新「有更改未保存」提示。
    staged_changed = Signal()

    def __init__(self, parent=None, staging_cache: SettingsStagingCache | None = None):
        super().__init__(parent)
        if staging_cache is None:
            staging_cache = SettingsStagingCache()
            v2 = SettingsManagerV2()
            snapshot = copy.deepcopy(v2.load())
            staging_cache.begin(snapshot)
        elif not staging_cache.is_active():
            v2 = SettingsManagerV2()
            staging_cache.begin(copy.deepcopy(v2.load()))
        self._staging_cache = staging_cache
        self._color_buttons: list[AccentColorButton] = []
        self._custom_btn: CustomAccentButton | None = None
        self._custom_panel: _ColorPanel | None = None
        self._current_accent: str = ""  # tracked for save
        self._event_filter_installed: bool = False  # track event filter state
        self._event_filter_targets: list[QObject] = []
        # 窗口背景状态（初值在 _build_ui 中从 V2 覆盖）
        self._bg_mode: str = "mica"        # "mica"（云母） / "image"（图像） / "minimalist"（简约）
        self._bg_image_name: str = ""      # 持久化目录中的背景图片文件名
        # 背景图片导入修订号：每次成功导入 +1。持久化目录是固定单槽位
        # （同名覆盖），故文件名不足以标识"内容已更换"，靠此修订号区分
        # 同一文件名的连续导入（否则第二次选图会被下发链路判为"无变化"跳过）。
        self._bg_image_rev: int = 0
        self._bg_ambient: bool = True      # 弥散氛围开关（简约模式下将主题色作为背景氛围层）
        self._ambient_toggle: StyledToggle | None = None  # 弥散氛围开关控件
        self._ambient_row: QWidget | None = None          # 弥散氛围行容器（仅简约模式可见）
        self._bg_updating: bool = False    # 编程式切换分段控件的守卫标志
        # 图像背景可调参数（初值在 _build_ui 中从暂存缓存覆盖）
        self._bg_blur: int = IMAGE_BG_BLUR_DEFAULT  # 模糊半径 px（整数 0-200）
        self._bg_transparency: int = IMAGE_BG_TRANSPARENCY_DEFAULT  # 透明度 %（0-100）
        self._bg_params_updating: bool = False  # 编程式设置滑动条的守卫标志
        self._bg_params_row: QWidget | None = None  # 参数区容器（仅图像模式可见）
        self._blur_slider: StyledSlider | None = None
        self._transparency_slider: StyledSlider | None = None
        self._blur_name_label: QLabel | None = None
        self._opacity_name_label: QLabel | None = None
        self._blur_value_label: QLabel | None = None
        self._transparency_value_label: QLabel | None = None
        # 统一排版条目（_build_ui 构建；标题/描述样式经 token 重注册）
        self._theme_row: SettingsRow | None = None
        self._accent_block: SettingsBlock | None = None
        self._bg_row: SettingsRow | None = None
        self._perf_row: SettingsRow | None = None
        # 深色模式三态状态（初值在 _build_ui 中从暂存缓存覆盖）
        self._theme_mode: str = "dark"   # "light"（白天） / "dark"（夜晚） / "system"（跟随系统）
        self._theme_updating: bool = False  # 编程式切换主题分段控件的守卫标志
        self._theme_segmented: StyledSegmented | None = None
        # 性能档位三态状态（初值在 _build_ui 中从暂存缓存覆盖）
        self._perf_profile: str = "balanced"  # "performance"（性能） / "balanced"（均衡） / "powersave"（省电）
        self._perf_updating: bool = False  # 编程式切换性能分段控件的守卫标志
        self._perf_segmented: StyledSegmented | None = None
        self._build_ui()
        self._load_v2_settings()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # 分组之间用 SETTINGS_GROUP_GAP；分组内部行距用 SETTINGS_ROW_GAP。
        layout.setSpacing(SETTINGS_GROUP_GAP)

        # 从暂存缓存读取初始偏好（缓存已在 __init__ 中以 V2 快照开启）；
        # 旧快照缺 theme_mode 时由 appearance.theme 迁移。
        saved_accent = self._staging_cache.get("appearance.accent_color", "#007AFF")
        self._theme_mode = self._resolve_staged_theme_mode()

        # ── 分组 1：主题（主题色 + 深色模式） ──
        theme_group = QVBoxLayout()
        theme_group.setContentsMargins(0, 0, 0, 0)
        theme_group.setSpacing(SETTINGS_ROW_GAP)

        # 深色模式三段选择（白天 / 夜晚 / 跟随系统）：
        # 与「窗口背景」分段同款 StyledSegmented（pill/sm），视觉与交互一致。
        self._theme_row = SettingsRow(title="深色模式")

        self._theme_segmented = StyledSegmented(variant="pill", size="sm")
        for label in self.THEME_LABELS:
            self._theme_segmented.add_segment(label)
        self._theme_segmented.current_changed.connect(
            self._on_theme_segment_changed
        )
        # 守卫内编程式切换，避免初始化期间触发应用/持久化逻辑。
        self._theme_updating = True
        try:
            self._theme_segmented.set_current_index(
                self.THEME_INDEX.get(self._theme_mode, 1), animate=False
            )
        finally:
            self._theme_updating = False
        self._theme_row.set_control(self._theme_segmented)

        # 存量兼容：保留 _dark_toggle 属性（非界面垫片，不加入布局），
        # 供旧测试/外部调用以 checked/toggled 方式读写实际生效值。
        self._dark_toggle = _DarkToggleCompat(self)

        # ── 主题色（标题下方整行排列色板，SettingsBlock） ──
        self._accent_block = SettingsBlock(title="主题色")

        # 单行布局：所有配色按钮放在同一行
        color_row = QHBoxLayout()
        color_row.setContentsMargins(0, 0, 0, 0)
        color_row.setSpacing(8)

        self._current_accent = saved_accent

        for preset in PRESET_ACCENT_COLORS:
            is_auto = preset["color"].lower() == "auto"
            display_color = get_system_accent_color() if is_auto else preset["color"]
            center_text = "A" if is_auto else ""
            btn = AccentColorButton(
                display_color,
                preset["name"],
                center_text=center_text,
                value=preset["color"],
            )
            btn.clicked.connect(self._on_color_clicked)
            if preset["color"].upper() == saved_accent.upper():
                btn.selected = True
            color_row.addWidget(btn)
            self._color_buttons.append(btn)

        # 自定义颜色按钮（360° 全色谱渐变）
        self._custom_btn = CustomAccentButton(selected=False)
        self._custom_btn.clicked.connect(self._on_custom_color_clicked)
        color_row.addWidget(self._custom_btn)

        color_row.addStretch()  # 右侧弹性空间
        self._accent_block.set_content_layout(color_row)
        # 主题色为该分组第一项，深色模式排在主题色之后。
        theme_group.addWidget(self._accent_block)
        theme_group.addWidget(self._theme_row)
        layout.addLayout(theme_group)

        # 窗口背景初值：云母参数为按主题固定的产品定值（见
        # main_window.FIXED_MICA_PARAMS），设置页不再提供滑动条配置。
        # 初值来自暂存缓存（隔离层唯一数据源）。
        saved_bg = self._staging_cache.get("appearance.background", {}) or {}
        saved_bg_mode = saved_bg.get("mode", "mica")
        self._bg_mode = saved_bg_mode if saved_bg_mode in ("mica", "image", "minimalist") else "mica"
        self._bg_image_name = str(saved_bg.get("image", "") or "")
        _raw_ambient = saved_bg.get("ambient", True)
        self._bg_ambient = _raw_ambient if isinstance(_raw_ambient, bool) else bool(_raw_ambient)
        self._bg_blur = _normalize_bg_blur(saved_bg.get("blur", IMAGE_BG_BLUR_DEFAULT))
        self._bg_transparency = _normalize_bg_transparency(
            saved_bg.get("transparency", IMAGE_BG_TRANSPARENCY_DEFAULT)
        )

        # ── 分组 2：窗口背景（简约 / 云母 / 图像） ──
        bg_group = QVBoxLayout()
        bg_group.setContentsMargins(0, 0, 0, 0)
        bg_group.setSpacing(SETTINGS_ROW_GAP)

        self._bg_row = SettingsRow(title="窗口背景")
        self._bg_label = self._bg_row.title_label

        self._bg_segmented = StyledSegmented(variant="pill", size="sm")
        self._bg_segmented.add_segment("简约")
        self._bg_segmented.add_segment("云母")
        self._bg_segmented.add_segment("图像")
        self._bg_segmented.current_changed.connect(self._on_bg_segment_changed)
        # 初始选中项来自 V2：简约 → 索引 0（默认选中，无需切换），
        # 云母 → 索引 1，图像 → 索引 2。守卫内编程式切换，避免初始化期间
        # 触发 _on_bg_segment_changed 的应用/持久化逻辑。
        self._bg_updating = True
        try:
            if self._bg_mode == "mica":
                self._bg_segmented.set_current_index(1, animate=False)
            elif self._bg_mode == "image":
                self._bg_segmented.set_current_index(2, animate=False)
        finally:
            self._bg_updating = False
        self._bg_row.set_control(self._bg_segmented)
        bg_group.addWidget(self._bg_row)

        # 图片行（仅 image 模式可见）：当前文件名（描述位）+「选择图片…」按钮
        self._bg_image_row = SettingsRow(
            title="背景图片",
            description=(self._bg_image_name if self._bg_image_name else "未设置"),
        )
        # 描述标签即文件名展示位（_update_bg_ui_state 负责回写文本）
        self._bg_file_label = self._bg_image_row.desc_label

        self._bg_choose_btn = StyledButton("选择图片…", variant="secondary", size="sm")
        self._bg_choose_btn.clicked.connect(self._on_choose_bg_image_clicked)
        self._bg_image_row.set_control(self._bg_choose_btn)
        bg_group.addWidget(self._bg_image_row)

        # 图像参数区（仅 image 模式可见）：模糊度 / 透明度可拖动滑动条。
        # 默认模糊度 0（不模糊）、透明度 80%（很透明）。
        # SettingsBlock（无标题）作为纯内容分组：字段名列宽 / 读数列宽
        # 全部引用统一 token，与三页其余条目同字号同间距。
        self._bg_params_row = SettingsBlock()

        blur_row = QHBoxLayout()
        blur_row.setContentsMargins(0, 0, 0, 0)
        blur_row.setSpacing(SETTINGS_LABEL_GAP)
        self._blur_name_label = QLabel("模糊度")
        apply_settings_field_style(self._blur_name_label)
        self._blur_name_label.setFixedWidth(SETTINGS_FIELD_LABEL_WIDTH)
        blur_row.addWidget(self._blur_name_label)
        self._blur_slider = StyledSlider(
            value=self._bg_blur / IMAGE_BG_BLUR_MAX, size="sm"
        )
        self._blur_slider.value_changed.connect(self._on_blur_changed)
        blur_row.addWidget(self._blur_slider, stretch=1)
        self._blur_value_label = QLabel(f"{self._bg_blur:g}")
        apply_settings_value_style(self._blur_value_label)
        self._blur_value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._blur_value_label.setFixedWidth(SETTINGS_VALUE_LABEL_WIDTH)
        blur_row.addWidget(self._blur_value_label)
        self._bg_params_row.set_content_layout(blur_row)

        opacity_row = QHBoxLayout()
        opacity_row.setContentsMargins(0, 0, 0, 0)
        opacity_row.setSpacing(SETTINGS_LABEL_GAP)
        self._opacity_name_label = QLabel("透明度")
        apply_settings_field_style(self._opacity_name_label)
        self._opacity_name_label.setFixedWidth(SETTINGS_FIELD_LABEL_WIDTH)
        opacity_row.addWidget(self._opacity_name_label)
        self._transparency_slider = StyledSlider(
            value=self._bg_transparency / 100.0, size="sm"
        )
        self._transparency_slider.value_changed.connect(
            self._on_transparency_changed
        )
        opacity_row.addWidget(self._transparency_slider, stretch=1)
        self._transparency_value_label = QLabel(f"{self._bg_transparency}%")
        apply_settings_value_style(self._transparency_value_label)
        self._transparency_value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._transparency_value_label.setFixedWidth(SETTINGS_VALUE_LABEL_WIDTH)
        opacity_row.addWidget(self._transparency_value_label)
        self._bg_params_row.set_content_layout(opacity_row)

        bg_group.addWidget(self._bg_params_row)

        # 弥散氛围行（仅简约模式可见）：开关实时生效并持久化
        self._ambient_row = SettingsRow(
            title="弥散氛围",
            description="启用后,将选取主题色作为背景氛围层提升质感",
        )
        self._ambient_toggle = StyledToggle(checked=self._bg_ambient, size="default")
        self._ambient_toggle.toggled.connect(self._on_ambient_toggled)
        self._ambient_row.set_control(self._ambient_toggle)
        bg_group.addWidget(self._ambient_row)

        layout.addLayout(bg_group)

        # 初始按模式设置图片行与弥散氛围行的可见性（不触发应用逻辑）
        self._update_bg_ui_state()

        # ── 分组 3：性能档位（性能 / 均衡 / 省电） ──
        # 与「深色模式」分段同款 StyledSegmented（pill/sm），视觉与交互一致。
        # 暂存隔离铁律：切换只写入 SettingsStagingCache（performance.profile），
        # 不触碰三钩子、tm、主窗口与磁盘；应用与落盘统一由
        # SettingsLayout._submit_settings 在点击确定时执行。
        perf_group = QVBoxLayout()
        perf_group.setContentsMargins(0, 0, 0, 0)
        perf_group.setSpacing(SETTINGS_ROW_GAP)

        self._perf_row = SettingsRow(title="性能档位")
        self._perf_label = self._perf_row.title_label
        self._perf_profile = self._resolve_staged_perf_profile()

        self._perf_segmented = StyledSegmented(variant="pill", size="sm")
        for label in self.PROFILE_LABELS:
            self._perf_segmented.add_segment(label)
        self._perf_segmented.current_changed.connect(
            self._on_perf_segment_changed
        )
        # 守卫内编程式切换，避免初始化期间触发应用/持久化逻辑。
        self._perf_updating = True
        try:
            self._perf_segmented.set_current_index(
                self.PROFILE_INDEX.get(self._perf_profile, 1), animate=False
            )
        finally:
            self._perf_updating = False
        self._perf_row.set_control(self._perf_segmented)
        perf_group.addWidget(self._perf_row)
        layout.addLayout(perf_group)

        layout.addStretch(1)

    # ── 窗口背景：模式切换与图片导入 ─────────────────────────────────

    @property
    def color_buttons(self) -> list[AccentColorButton]:
        """页内强调色按钮列表（供宿主刷新按钮选中态）。"""
        return self._color_buttons

    def find_main_window(self) -> QWidget | None:
        """定位主窗口（``_mica_background`` + ``get_background_mode`` 鸭子类型）。

        设置窗口是主窗口的 owned 子窗口后，self.window() 直接就是主窗口
        （QWidget.window() 返回顶层祖先），因此优先直接判定；遍历
        topLevelWidgets 仅作为回退路径（例如设置窗口未被挂载到主窗口的场景）。
        设置窗口自身虽然保留 ``_mica_background = None`` 的防御属性，但增加
        背景模式 API 判据可确保任何未来变化下都不会被误判为主窗口。
        """
        def _is_main_window_candidate(widget) -> bool:
            # 主窗口同时具备 Mica 背景属性和背景模式 API；设置窗口虽然也有
            # ``_mica_background = None`` 的鸭子类型防御，但绝不能被误判为主窗。
            return (
                widget is not None
                and getattr(widget, "_mica_background", None) is not None
                and callable(getattr(widget, "get_background_mode", None))
            )

        w = self.window()
        if _is_main_window_candidate(w):
            return w
        for w in QApplication.topLevelWidgets():
            if _is_main_window_candidate(w):
                return w
        return None

    # ── 窗口背景：模式切换与图片导入 ─────────────────────────────────

    def _on_bg_segment_changed(self, index: int) -> None:
        """窗口背景分段控件切换处理（暂存优先，未提交不影响主窗口）。

        Args:
            index: 新选中的分段索引（0 = 简约，1 = 云母，2 = 图像）。
        """
        if self._bg_updating:
            return
        if index == 2:
            # 已有持久化图片且文件存在 → 直接暂存；否则强制走选择流程
            if self._bg_image_name and os.path.exists(self._bg_image_path()):
                self._stage_background_settings("image")
                self.appearance_changed.emit()
            else:
                self._choose_bg_image(force=True)
        elif index == 0:
            self._stage_background_settings("minimalist")
            self.appearance_changed.emit()
        else:
            self._stage_background_settings("mica")
            self.appearance_changed.emit()

    def _on_ambient_toggled(self, checked: bool) -> None:
        """弥散氛围开关切换处理：仅写入暂存缓存，点击应用/确定才生效。

        Args:
            checked: 开关新状态；True 表示启用弥散氛围。
        """
        self._bg_ambient = bool(checked)
        if self._bg_mode != "minimalist":
            self._stage_background_settings("minimalist")
            self.appearance_changed.emit()
            return
        self._staging_cache.set("appearance.background", {
            "mode": self._bg_mode,
            "image": self._bg_image_name,
            "ambient": self._bg_ambient,
            "blur": self._bg_blur,
            "transparency": self._bg_transparency,
        })
        self._update_bg_ui_state()
        self.appearance_changed.emit()

    def _on_blur_changed(self, value: float) -> None:
        """图像模糊度滑动条 — 仅写入暂存，点击确定才全局生效。

        Args:
            value: 滑动条归一化值 0~1，映射为 0~200px。
        """
        if self._bg_params_updating:
            return
        self._bg_blur = _normalize_bg_blur(
            max(0.0, min(1.0, value)) * IMAGE_BG_BLUR_MAX
        )
        if self._blur_value_label is not None:
            self._blur_value_label.setText(f"{self._bg_blur}")
        self._stage_background_settings(self._bg_mode)
        self.appearance_params_changed.emit()

    def _on_transparency_changed(self, value: float) -> None:
        """图像透明度滑动条 — 仅写入暂存，点击确定才全局生效。

        Args:
            value: 滑动条归一化值 0~1，映射为 0~100%（80% 为很透明）。
        """
        if self._bg_params_updating:
            return
        self._bg_transparency = _normalize_bg_transparency(
            max(0.0, min(1.0, value)) * 100.0
        )
        if self._transparency_value_label is not None:
            self._transparency_value_label.setText(f"{self._bg_transparency}%")
        self._stage_background_settings(self._bg_mode)
        self.appearance_params_changed.emit()

    def _sync_bg_param_sliders(self) -> None:
        """按当前参数同步两条滑动条与数值标签（守卫内设置，不触发处理器）。"""
        if self._blur_slider is None or self._transparency_slider is None:
            return
        self._bg_params_updating = True
        try:
            self._blur_slider.value = self._bg_blur / IMAGE_BG_BLUR_MAX
            self._transparency_slider.value = self._bg_transparency / 100.0
        finally:
            self._bg_params_updating = False
        if self._blur_value_label is not None:
            self._blur_value_label.setText(f"{self._bg_blur}")
        if self._transparency_value_label is not None:
            self._transparency_value_label.setText(f"{self._bg_transparency}%")

    def _on_choose_bg_image_clicked(self) -> None:
        """「选择图片…」按钮点击入口（非强制场景：取消/失败不回退分段）。"""
        self._choose_bg_image(force=False)

    def _choose_bg_image(self, force: bool = False) -> bool:
        """打开文件对话框选择并导入背景图片。

        Args:
            force: True 表示由分段控件首次切入「图像」触发的强制
                选择场景——用户取消或导入失败时把分段控件编程式回退到
                「云母」；False 表示「选择图片…」按钮触发，取消或
                失败时保持现状（不回退、不改设置）。

        Returns:
            bool: 成功导入并应用图片背景返回 True；用户取消或导入失败
            返回 False。
        """
        path, _ = QFileDialog.getOpenFileName(
            self, "选择背景图片", "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp *.gif);;所有文件 (*)",
        )
        if not path:
            if force:
                self._revert_bg_segment()
            return False

        dest = import_custom_background_image(path)
        if dest is None:
            create_danger_dialog(
                title="导入失败",
                message="背景图片导入失败，请确认所选文件为受支持的有效图片"
                        "（PNG / JPG / JPEG / BMP / WEBP / GIF）。",
            )
            if force:
                self._revert_bg_segment()
            return False

        self._bg_image_name = os.path.basename(dest)
        # 修订号 +1：即便文件名与上次相同（单槽位同名覆盖），也告知下发
        # 链路"图片内容已更换"，从而重新下发并触发背景层交叉淡入。
        self._bg_image_rev += 1
        self._stage_background_settings("image")
        self.appearance_changed.emit()
        return True

    def _revert_bg_segment(self) -> None:
        """把分段控件编程式回退到「云母」（索引 1，守卫内切换不触发处理器）。"""
        self._bg_updating = True
        try:
            self._bg_segmented.set_current_index(1)
        finally:
            self._bg_updating = False

    def _bg_image_path(self) -> str:
        """当前背景图片在持久化目录中的绝对路径。

        Returns:
            str: ``get_app_data_path()/backgrounds/<文件名>`` 拼接结果；
            未设置文件名时返回目录路径（调用方需先判空）。
        """
        return os.path.join(
            get_app_data_path(), BACKGROUND_DIR_NAME, self._bg_image_name
        )

    def background_image_revision(self) -> int:
        """当前背景图片的导入修订号（每次成功导入 +1）。

        供宿主下发链路判断"图片内容是否已更换"：持久化目录为固定单槽位
        同名覆盖，文件名恒定，仅靠文件名无法感知连续选图带来的内容更新。

        Returns:
            int: 本页打开以来的累计成功导入次数。
        """
        return self._bg_image_rev

    def _stage_background_settings(self, mode: str) -> None:
        """暂存窗口背景：仅写入暂存缓存并刷新本页 UI，不触碰主窗口与磁盘。

        提交时由 ``SettingsLayout._submit_settings`` 统一应用到主窗口并持久化。

        Args:
            mode: 目标背景模式："mica"（云母）、"image"（图像）或
                "minimalist"（简约，附带当前弥散氛围开关状态）。
        """
        self._bg_mode = mode
        self._staging_cache.set("appearance.background", {
            "mode": self._bg_mode,
            "image": self._bg_image_name,
            "ambient": self._bg_ambient,
            "blur": self._bg_blur,
            "transparency": self._bg_transparency,
        })
        self._update_bg_ui_state()

    def _apply_background_settings(self, mode: str) -> None:
        """兼容旧直接调用：转入暂存（不再直写主窗口/磁盘）。

        保留方法名以兼容存量测试与外部调用，语义已改为暂存优先。

        Args:
            mode: 目标背景模式。
        """
        self._stage_background_settings(mode)

    def _save_background_settings(self) -> None:
        """将窗口背景设置持久化到 SettingsManagerV2（重启后恢复）。"""
        try:
            v2 = SettingsManagerV2()
            v2.load()
            v2.set("appearance.background", {
                "mode": self._bg_mode,
                "image": self._bg_image_name,
                "ambient": self._bg_ambient,
                "blur": self._bg_blur,
                "transparency": self._bg_transparency,
            })
            v2.save()
        except Exception as exc:
            warning(f"窗口背景设置保存失败（重启后可能回退）：{exc}")

    def _update_bg_ui_state(self) -> None:
        """按当前背景模式刷新图片行、参数区与弥散氛围行的可见性。

        图片行与参数区（模糊度/透明度滑动条）仅图像模式可见；
        弥散氛围行仅简约模式可见。
        """
        is_image = (self._bg_mode == "image")
        is_minimalist = (self._bg_mode == "minimalist")
        self._bg_image_row.setVisible(is_image)
        self._bg_file_label.setText(
            self._bg_image_name if self._bg_image_name else "未设置"
        )
        if self._bg_params_row is not None:
            self._bg_params_row.setVisible(is_image)
        if self._ambient_row is not None:
            self._ambient_row.setVisible(is_minimalist)

    def _resolve_staged_theme_mode(self) -> str:
        """从暂存缓存解析主题偏好三态。

        优先读 ``appearance.theme_mode``；旧快照缺失时由
        ``appearance.theme``（dark/light）迁移；非法值回退为当前
        ``tm`` 实际值对应的手动偏好。

        Returns:
            偏好值："light" | "dark" | "system"。
        """
        staged_mode = self._staging_cache.get("appearance.theme_mode", None)
        if staged_mode in ("light", "dark", "system"):
            return staged_mode
        staged_theme = self._staging_cache.get("appearance.theme", None)
        if staged_theme in ("light", "dark"):
            return staged_theme
        try:
            return tm.get_theme_mode()
        except Exception:
            return "dark" if tm.is_dark_theme() else "light"

    def _on_theme_segment_changed(self, index: int) -> None:
        """深色模式分段切换 — 仅写入暂存，点击确定才全局生效。

        与「窗口背景」分段同语义：切换只进 ``SettingsStagingCache``，
        不触碰 ``tm``、主窗口与磁盘；应用与落盘统一由
        ``SettingsLayout._submit_settings`` 在点击确定时执行。

        Args:
            index: 新选中的分段索引（0 = 白天，1 = 夜晚，2 = 跟随系统）。
        """
        if self._theme_updating:
            return
        if index < 0 or index >= len(self.THEME_MODES):
            return
        self.apply_theme_mode(self.THEME_MODES[index])

    def apply_theme_mode(self, mode: str) -> None:
        """暂存主题偏好（不生效、不落盘，点击确定才全局应用）。

        遵循设置页暂存隔离铁律：仅写入暂存缓存并同步分段选中；
        应用到 ``tm`` 与 V2 落盘统一由 ``SettingsLayout._submit_settings``
        执行。跟随系统模式的暂存生效值按当前系统主题只读推导（不触碰 ``tm``）。

        Args:
            mode: 偏好值，"light" | "dark" | "system"，非法值直接忽略。
        """
        if mode not in ("light", "dark", "system"):
            return
        self._theme_mode = mode
        self._staging_cache.set("appearance.theme_mode", mode)
        if mode == "system":
            try:
                from freeassetfilter.ui.theme.system_theme import (
                    get_windows_system_theme,
                )

                effective = get_windows_system_theme()
            except Exception:
                effective = "dark" if tm.is_dark_theme() else "light"
            if effective not in ("light", "dark"):
                effective = "dark" if tm.is_dark_theme() else "light"
        else:
            effective = mode
        self._staging_cache.set("appearance.theme", effective)
        self.sync_theme_segment()
        self.appearance_changed.emit()

    def sync_theme_segment(self) -> None:
        """按当前偏好同步分段控件选中项（守卫内切换，不触发处理器）。"""
        if self._theme_segmented is None:
            return
        target = self.THEME_INDEX.get(self._theme_mode, 1)
        self._theme_updating = True
        try:
            self._theme_segmented.set_current_index(target, animate=False)
        finally:
            self._theme_updating = False

    def _resolve_staged_perf_profile(self) -> str:
        """从暂存缓存解析性能档位。

        只接受 ``performance`` / ``balanced`` / ``powersave``；
        缺失或非法值回退 ``balanced``（与 V2 合并口径一致）。

        Returns:
            档位值："performance" | "balanced" | "powersave"。
        """
        staged = self._staging_cache.get("performance.profile", None)
        if staged in ("performance", "balanced", "powersave"):
            return staged
        return "balanced"

    def _on_perf_segment_changed(self, index: int) -> None:
        """性能档位分段切换 — 仅写入暂存，点击确定才全局生效。

        与「深色模式」分段同语义：切换只进 ``SettingsStagingCache``
        （``performance.profile``），不触碰三钩子、``tm``、主窗口与磁盘；
        应用与落盘统一由 ``SettingsLayout._submit_settings`` 在点击确定时
        执行。

        Args:
            index: 新选中的分段索引（0 = 性能，1 = 均衡，2 = 省电）。
        """
        if self._perf_updating:
            return
        if index < 0 or index >= len(self.PROFILE_MODES):
            return
        self._apply_perf_profile(self.PROFILE_MODES[index])

    def _apply_perf_profile(self, mode: str) -> None:
        """暂存性能档位（不生效、不落盘，点击确定才全局应用）。

        遵循设置页暂存隔离铁律：仅写入暂存缓存并同步分段选中；
        三钩子应用与 V2 落盘统一由 ``SettingsLayout._submit_settings``
        执行。

        Args:
            mode: 档位值，"performance" | "balanced" | "powersave"，
                非法值直接忽略。
        """
        if mode not in ("performance", "balanced", "powersave"):
            return
        self._perf_profile = mode
        self._staging_cache.set("performance.profile", mode)
        self._sync_perf_segment()
        self.staged_changed.emit()

    def _sync_perf_segment(self) -> None:
        """按当前档位同步性能分段控件选中项（守卫内切换，不触发处理器）。"""
        if self._perf_segmented is None:
            return
        target = self.PROFILE_INDEX.get(self._perf_profile, 1)
        self._perf_updating = True
        try:
            self._perf_segmented.set_current_index(target, animate=False)
        finally:
            self._perf_updating = False

    def _on_dark_toggle(self, checked: bool) -> None:
        """兼容旧深色开关调用：等价于暂存夜晚/白天偏好（点击确定才生效）。

        保留方法名以兼容存量测试与外部调用，语义为纯暂存
        （与分段控件一致）。

        Args:
            checked: True 暂存为夜晚（深色），False 暂存为白天（浅色）。
        """
        self.apply_theme_mode("dark" if checked else "light")
        self.sync_theme_segment()

    def _on_color_clicked(self, color_hex: str) -> None:
        """主题色选择 — 写入暂存缓存，点击「应用」/「确定」才全局生效。"""
        self._current_accent = color_hex
        self._staging_cache.set("appearance.accent_color", color_hex)
        for btn in self._color_buttons:
            btn.selected = (btn.color_hex.upper() == color_hex.upper())
        if self._custom_btn is not None:
            self._custom_btn.selected = False
        # 选择预设色时关闭浮动选择面板
        if self._custom_panel is not None:
            self._custom_panel.close_animated()
        self.appearance_changed.emit()

    def _on_custom_color_clicked(self) -> None:
        """自定义颜色按钮 — 展开/折叠浮动颜色选择面板。
        
        严格的切换行为：
        - 第一张点击：打开面板
        - 面板可见时的点击：关闭面板
        - 关闭动画进行中的点击：取消关闭并重新打开
        - 打开动画进行中的点击：关闭面板
        
        面板引用在页面生命周期内持久存在，不因关闭而丢失。
        """
        # 确保面板存在（只创建一次）
        if self._custom_panel is None:
            self._custom_panel = _ColorPanel(parent=self)
            self._custom_panel.color_selected.connect(self._on_panel_color_changed)
            self._custom_panel.closed.connect(self._on_panel_closed)
        
        panel = self._custom_panel
        
        # 严格切换逻辑：先检查关闭中状态（isVisible 在淡出时仍为 True）
        if panel.is_closing:
            # 面板正在关闭中 → 取消关闭并重新打开
            panel.reopen()
            
            # 更新按钮状态
            for btn in self._color_buttons:
                btn.selected = False
            self._custom_btn.selected = True
        elif panel.isVisible():
            # 面板可见且未在关闭中 → 关闭
            panel.close_animated()
        else:
            # 面板隐藏 → 打开
            btn_pos = self._custom_btn.mapToGlobal(
                QPoint(self._custom_btn.width() + 4, 0)
            )
            
            initial = self._current_accent
            if initial.lower() == "auto" or not initial.startswith("#"):
                initial = tm.accent.name().upper()
            panel.set_color(initial)
            
            # 更新按钮状态
            for btn in self._color_buttons:
                btn.selected = False
            self._custom_btn.selected = True
            
            panel.show_animated(btn_pos)
            # 安装外部点击事件过滤器（在面板显示后安装）
            self._install_outside_click_filter()

    def _install_outside_click_filter(self) -> None:
        """在设置窗口顶层祖先上安装事件过滤器，用于点击外部区域关闭面板。

        设置窗口是主窗口的 owned 子窗口，self.window() 返回主窗口，
        因此过滤器会同时覆盖设置页自身及其子控件与主窗口——面板显示期间
        点击主窗口任何区域同样会关闭面板。

        Safe when no top-level window exists yet (no-op).
        Idempotent: repeated calls have no effect.
        """
        if self._event_filter_installed:
            return
        
        top_window = self.window()
        if top_window is None:
            return
        
        targets: list[QObject] = [top_window, self]
        targets.extend(self.findChildren(QWidget))
        unique_targets = list(dict.fromkeys(targets))
        for target in unique_targets:
            target.installEventFilter(self)
        self._event_filter_targets = unique_targets
        self._event_filter_installed = True

    def _remove_outside_click_filter(self) -> None:
        """Remove event filter from the top-level SettingsWindow.
        
        Idempotent: repeated calls have no effect.
        Safe when no top-level window exists or filter was not installed.
        """
        if not self._event_filter_installed:
            return
        
        for target in self._event_filter_targets:
            target.removeEventFilter(self)
        self._event_filter_targets.clear()
        self._event_filter_installed = False

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Event filter for outside-click dismissal of _ColorPanel.
        
        Intercepts MouseButtonPress on the top-level SettingsWindow.
        - If click is inside the panel's global rect → ignore (let panel handle it)
        - If click is inside the custom button's global rect → ignore (let button handle toggle)
        - Otherwise → close panel with fade animation
        
        Returns False always to let the original event continue propagation.
        """
        if event.type() == QEvent.Type.MouseButtonPress:
            global_pos = event.globalPosition().toPoint()
            
            # Check if panel exists and is visible
            if self._custom_panel is None or not self._custom_panel.isVisible():
                return False
            
            # Check if click is inside the panel
            panel_global_rect = QRectF(
                self._custom_panel.mapToGlobal(QPoint(0, 0)),
                self._custom_panel.size(),
            )
            if panel_global_rect.contains(global_pos):
                # Click inside panel → ignore, let panel handle it
                return False
            
            # Check if click is inside the custom button
            if self._custom_btn is not None:
                btn_global_rect = QRectF(
                    self._custom_btn.mapToGlobal(QPoint(0, 0)),
                    self._custom_btn.size(),
                )
                if btn_global_rect.contains(global_pos):
                    # Click inside button → ignore, let button handler toggle
                    return False
            
            # Click outside panel and button → close panel
            self._custom_panel.close_animated()
        
        return False

    def _on_panel_color_changed(self, hex_color: str) -> None:
        """浮动颜色选择面板值变化 — 写入暂存缓存（提交前不全局生效）。"""
        self._current_accent = hex_color
        self._staging_cache.set("appearance.accent_color", hex_color)
        for btn in self._color_buttons:
            btn.selected = False
        if self._custom_btn is not None:
            self._custom_btn.selected = True
        # 色板拖动会连续触发：走去抖通道，避免每帧重下发主窗口。
        self.appearance_params_changed.emit()

    def _on_panel_closed(self) -> None:
        """浮动面板关闭后的处理。
        
        注意：不将 _custom_panel 设为 None，保持面板引用。
        页面销毁时 Qt 父子关系会自动清理面板。
        """
        # 仅重置按钮状态，不丢弃面板引用
        # 移除外部点击事件过滤器
        self._remove_outside_click_filter()

    def hideEvent(self, event: QHideEvent) -> None:
        """宿主页面隐藏时同步关闭浮动面板并移除事件过滤器。"""
        if self._custom_panel is not None:
            self._custom_panel.close_animated()
        self._remove_outside_click_filter()
        super().hideEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        """宿主页面关闭时同步关闭浮动面板并移除事件过滤器。"""
        if self._custom_panel is not None:
            self._custom_panel.close_animated()
        self._remove_outside_click_filter()
        super().closeEvent(event)

    def refresh_theme(self) -> None:
        """主题切换时刷新页面内文字颜色并同步三段控件。

        暂存隔离铁律：本页的任何修改都不触碰 ``tm``；此处仅处理反方向
        （顶栏按钮 / 系统跟随导致的 ``tm`` 变化）的单向镜像——以 ``tm``
        当前偏好为准回写暂存并同步分段选中，保证设置面板与顶栏按钮一致；
        守卫内编程式切换，不触发提交。
        """
        # 外部主题变化优先同步暂存（主题为实时项，不存在未提交覆盖问题）。
        try:
            external_mode = tm.get_theme_mode()
        except Exception:
            external_mode = "dark" if tm.is_dark_theme() else "light"
        if external_mode in ("light", "dark", "system"):
            if self._staging_cache.get("appearance.theme_mode", None) != external_mode:
                self._staging_cache.set("appearance.theme_mode", external_mode)
            try:
                external_effective = tm.effective_theme()
            except Exception:
                external_effective = "dark" if tm.is_dark_theme() else "light"
            if self._staging_cache.get("appearance.theme", None) != external_effective:
                self._staging_cache.set("appearance.theme", external_effective)
            self._theme_mode = external_mode
        else:
            self._theme_mode = self._resolve_staged_theme_mode()
        self.sync_theme_segment()
        # 本页文字样式按统一 token 重注册（替代宿主通刷 QLabel）。
        for item in (
            self._theme_row,
            self._accent_block,
            self._bg_row,
            self._bg_image_row,
            self._perf_row,
            self._ambient_row,
        ):
            _refresh_settings_item_text(item)
        # 图像参数区：字段名与读数按 token 重注册
        apply_settings_field_style(self._blur_name_label)
        apply_settings_field_style(self._opacity_name_label)
        apply_settings_value_style(self._blur_value_label)
        apply_settings_value_style(self._transparency_value_label)
        # 弥散氛围开关：同步状态（避免信号循环：暂时断开）
        if self._ambient_toggle is not None:
            self._ambient_toggle.toggled.disconnect(self._on_ambient_toggled)
            self._ambient_toggle.checked = self._bg_ambient
            self._ambient_toggle.toggled.connect(self._on_ambient_toggled)
        # 重新应用背景模式相关的可见性/置灰状态
        self._update_bg_ui_state()

    def _load_v2_settings(self) -> None:
        """确保 UI 控件与暂存缓存一致（不修改 tm，不读盘）。

        历史语义为从 V2 重载，现改为从隔离层同步，保证取消/关闭未提交时
        界面可恢复至原始状态。保留方法名以兼容存量调用。
        """
        self.refresh_from_staging()

    def refresh_from_staging(self) -> None:
        """从暂存缓存刷新全部控件展示（实时更新机制的核心）。

        所有开关、输入框、滑动条展示与暂存内容一致；编程式赋值全程守卫，
        不回写缓存、不触发提交、不触碰主窗口与磁盘。
        """
        self._theme_mode = self._resolve_staged_theme_mode()
        self.sync_theme_segment()

        saved_accent = self._staging_cache.get("appearance.accent_color", "#007AFF")
        self._current_accent = saved_accent
        preset_values = {btn.color_hex.upper() for btn in self._color_buttons}
        is_preset = isinstance(saved_accent, str) and saved_accent.upper() in preset_values
        for btn in self._color_buttons:
            btn.selected = (
                isinstance(saved_accent, str)
                and btn.color_hex.upper() == saved_accent.upper()
            )
        if self._custom_btn is not None:
            self._custom_btn.selected = (
                isinstance(saved_accent, str)
                and not is_preset
                and saved_accent.upper() != "AUTO"
            )

        saved_bg = self._staging_cache.get("appearance.background", {}) or {}
        saved_bg_mode = saved_bg.get("mode", "mica")
        if saved_bg_mode in ("mica", "image", "minimalist"):
            self._bg_mode = saved_bg_mode
        self._bg_image_name = str(saved_bg.get("image", "") or "")
        _raw_ambient = saved_bg.get("ambient", True)
        self._bg_ambient = _raw_ambient if isinstance(_raw_ambient, bool) else bool(_raw_ambient)
        self._bg_blur = _normalize_bg_blur(
            saved_bg.get("blur", IMAGE_BG_BLUR_DEFAULT)
        )
        self._bg_transparency = _normalize_bg_transparency(
            saved_bg.get("transparency", IMAGE_BG_TRANSPARENCY_DEFAULT)
        )
        if self._ambient_toggle is not None:
            try:
                self._ambient_toggle.toggled.disconnect(self._on_ambient_toggled)
            except Exception as exc:
                debug(f"氛围开关信号断开失败（按未连接处理）：{exc}")
            self._ambient_toggle.checked = self._bg_ambient
            self._ambient_toggle.toggled.connect(self._on_ambient_toggled)
        self._sync_bg_segment()
        self._sync_bg_param_sliders()
        self._update_bg_ui_state()

        # 性能档位：从暂存恢复展示（取消/关闭未提交时恢复原始值）。
        self._perf_profile = self._resolve_staged_perf_profile()
        self._sync_perf_segment()

    def _sync_bg_segment(self) -> None:
        """按暂存背景模式同步分段控件选中项（守卫内切换，不触发处理器）。"""
        target = {"minimalist": 0, "mica": 1, "image": 2}.get(self._bg_mode, 1)
        self._bg_updating = True
        try:
            self._bg_segmented.set_current_index(target, animate=False)
        finally:
            self._bg_updating = False

    def get_staging_cache(self) -> SettingsStagingCache:
        """返回本页绑定的暂存缓存（调试与提交链路使用）。

        Returns:
            SettingsStagingCache: 隔离层实例。
        """
        return self._staging_cache

    def get_cache_debug_info(self) -> dict:
        """返回暂存缓存调试摘要。

        Returns:
            dict: 见 :meth:`SettingsStagingCache.debug_info`。
        """
        return self._staging_cache.debug_info()

    def collect_settings(self) -> dict:
        """收集暂存区的 V2 设置值（提交事务的数据源）。

        Returns:
            dict: V2 分类树格式的设置字典（含主题、强调色、窗口背景与
                性能档位）。
        """
        return {
            "appearance": {
                "theme_mode": self._staging_cache.get(
                    "appearance.theme_mode", self._theme_mode
                ),
                "theme": self._staging_cache.get(
                    "appearance.theme",
                    "dark" if tm.is_dark_theme() else "light",
                ),
                "accent_color": self._staging_cache.get(
                    "appearance.accent_color", self._current_accent
                ),
                "background": self._staging_cache.get(
                    "appearance.background",
                    {
                        "mode": self._bg_mode,
                        "image": self._bg_image_name,
                        "ambient": self._bg_ambient,
                    },
                ),
            },
            "performance": {
                "profile": self._staging_cache.get(
                    "performance.profile", self._perf_profile
                ),
            },
        }


class GeneralSettingsPage(QWidget):
    """通用设置页面 — 主界面布局切换（暂存缓存优先）。

    布局切换项：经典 / New（预览优先）。暂存隔离铁律：切换只写入
    ``SettingsStagingCache``（``general.layout_mode``），未提交前不触碰主窗口
    与磁盘；点击「确定」才经 ``SettingsLayout._submit_settings`` 下发
    ``MainWindow.set_layout_mode`` 并落盘。控件展示以缓存为准。

    介绍文字随当前选中布局即时切换（仅显示当前布局介绍 + 换行提示）。
    """

    # 布局模式与分段索引的双向映射（顺序与 _build_ui 添加顺序一致）。
    LAYOUT_MODES: tuple[str, ...] = ("classic", "workspace")
    LAYOUT_LABELS: tuple[str, ...] = ("经典", "New")
    LAYOUT_INDEX: dict[str, int] = {"classic": 0, "workspace": 1}

    #: 通用页任一设置项发生用户改动时发出，宿主据此刷新「有更改未保存」提示。
    #: 通用页设置属「非外观项」，不实时生效、只能经「保存」按钮提交。
    staged_changed = Signal()

    #: 切换提示行（所有布局介绍后统一换行追加）
    _LAYOUT_HINT = "切换在点击「确定」后立即生效。"
    #: 各布局介绍（不含提示行）
    _LAYOUT_DESCRIPTIONS: dict[str, str] = {
        "classic": "经典布局：文件选择、文件储存、文件预览三栏并列，信息面板位于预览区下方。",
        "workspace": "New 布局：预览优先，文件选择独占左栏，文件储存与文件信息并排位于预览区下方。",
    }

    def __init__(self, parent=None, staging_cache: SettingsStagingCache | None = None):
        super().__init__(parent)
        if staging_cache is None:
            staging_cache = SettingsStagingCache()
            v2 = SettingsManagerV2()
            staging_cache.begin(copy.deepcopy(v2.load()))
        elif not staging_cache.is_active():
            v2 = SettingsManagerV2()
            staging_cache.begin(copy.deepcopy(v2.load()))
        self._staging_cache = staging_cache
        # 布局模式状态（初值由 refresh_from_staging 从暂存缓存读取）
        self._layout_mode: str = "workspace"
        self._layout_updating: bool = False  # 编程式切换分段控件的守卫标志
        self._layout_segmented: StyledSegmented | None = None
        self._layout_row: SettingsRow | None = None
        # 通用功能开关状态（初值由 refresh_from_staging 从暂存缓存读取）
        self._ai_entry: bool = False
        self._include_remote_drives: bool = False
        self._blank_right_click_go_back: bool = False
        # 全局浮窗开关状态（默认开启；控件在 _build_ui 挂载，刷新时经
        # None 守卫同步展示）
        self._floating_pool_enabled: bool = True
        # 全局浮窗贴边吸附开关状态（默认开启；作为全局浮窗的子选项，
        # 仅在浮窗开启时显示）
        self._floating_pool_snap_enabled: bool = True
        self._general_updating: bool = False  # 编程式同步开关的守卫标志
        self._ai_row: SettingsRow | None = None
        self._ai_toggle: StyledToggle | None = None
        self._drives_row: SettingsRow | None = None
        self._drives_toggle: StyledToggle | None = None
        self._blank_back_row: SettingsRow | None = None
        self._blank_back_toggle: StyledToggle | None = None
        # 隐藏文件 / 受保护系统文件开关状态（默认关闭；系统文件行仅在显示
        # 隐藏文件开启时可见，初值由 refresh_from_staging 从暂存缓存读取）
        self._show_hidden_files: bool = False
        self._show_system_files: bool = False
        self._hidden_row: SettingsRow | None = None
        self._hidden_toggle: StyledToggle | None = None
        self._system_row: SettingsRow | None = None
        self._system_toggle: StyledToggle | None = None
        self._floating_pool_row: SettingsRow | None = None
        self._floating_pool_toggle: StyledToggle | None = None
        self._floating_pool_snap_row: SettingsRow | None = None
        self._floating_pool_snap_toggle: StyledToggle | None = None
        # 启动时检查更新开关状态（默认开启；普通行，非子选项）
        self._check_updates: bool = True
        self._check_updates_row: SettingsRow | None = None
        self._check_updates_toggle: StyledToggle | None = None
        # 子选项展开后的按需滚动：仅在用户打开父开关、且新子项被视口裁掉时
        # 生效；_pending 标记本次展开是否需要检查，避免刷新/初始化误滚动。
        self._pending_sub_option_scroll: SettingsRow | None = None
        self._sub_option_scroll_anim: QPropertyAnimation | None = None
        self._build_ui()
        self.refresh_from_staging()

    def _build_ui(self) -> None:
        """构建页面：界面布局行（分段控件 + 动态介绍文字）。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # 行距与外观/关于页统一（SETTINGS_ROW_GAP），不再单独使用 12px。
        layout.setSpacing(SETTINGS_ROW_GAP)

        # ── 界面布局：经典 / New（预览优先）──
        # 与「深色模式」「窗口背景」分段同款 StyledSegmented（pill/sm）。
        self._layout_row = SettingsRow(
            title="界面布局",
            description=self._layout_description_text(),
        )
        self._layout_segmented = StyledSegmented(variant="pill", size="sm")
        for label in self.LAYOUT_LABELS:
            self._layout_segmented.add_segment(label)
        self._layout_segmented.current_changed.connect(
            self._on_layout_segment_changed
        )
        self._layout_row.set_control(self._layout_segmented)
        layout.addWidget(self._layout_row)

        # ── AI 功能入口（默认关闭，长期规划）──
        # 暂存隔离铁律：开关只写入 SettingsStagingCache（general.enable_ai_entry），
        # 点击「确定」才经 _submit_settings 下发主窗口并落盘。
        self._ai_row = SettingsRow(
            title="AI功能入口",
            description="在PDF/文本预览器中显示AI侧边入口",
        )
        self._ai_toggle = StyledToggle(checked=False, size="default")
        self._ai_toggle.toggled.connect(self._on_ai_entry_toggled)
        self._ai_row.set_control(self._ai_toggle)
        layout.addWidget(self._ai_row)

        # ── 网络/映射盘与光驱（默认关闭）──
        self._drives_row = SettingsRow(
            title="显示网络盘与光驱",
            description="「All」磁盘视图中额外列出映射网络盘与光驱",
        )
        self._drives_toggle = StyledToggle(checked=False, size="default")
        self._drives_toggle.toggled.connect(self._on_remote_drives_toggled)
        self._drives_row.set_control(self._drives_toggle)
        layout.addWidget(self._drives_row)

        # ── 显示隐藏文件（默认关闭）──
        # 暂存隔离铁律：开关只写入 SettingsStagingCache（general.show_hidden_files），
        # 点击「确定」才经 _submit_settings 下发主窗口并落盘。
        self._hidden_row = SettingsRow(
            title="显示隐藏文件",
            description="在文件选择器中显示带「隐藏」属性的文件或文件夹",
        )
        self._hidden_toggle = StyledToggle(checked=False, size="default")
        self._hidden_toggle.toggled.connect(self._on_show_hidden_files_toggled)
        self._hidden_row.set_control(self._hidden_toggle)
        layout.addWidget(self._hidden_row)

        # ── 显示受保护的系统文件（默认关闭，仅在开启隐藏文件后可见）──
        # 子选项排版：右缩进 + 竖折右箭头，显隐走 SettingsRow.set_revealed
        # 的高度/透明度插入动画（宿主不可见时立即切换）。
        self._system_row = SettingsRow(
            title="显示受保护的系统文件",
            description="额外显示同时带「隐藏」「系统」属性的文件或文件夹",
            sub_option=True,
        )
        self._system_toggle = StyledToggle(checked=False, size="default")
        self._system_toggle.toggled.connect(self._on_show_system_files_toggled)
        self._system_row.set_control(self._system_toggle)
        self._system_row.set_revealed(False, animated=False)
        layout.addWidget(self._system_row)

        # ── 空白区右键返回上一级（默认关闭）──
        self._blank_back_row = SettingsRow(
            title="便捷返回",
            description="页面无需滚动时，选择区域右键空白区返回上一级",
        )
        self._blank_back_toggle = StyledToggle(checked=False, size="default")
        self._blank_back_toggle.toggled.connect(self._on_blank_right_click_go_back_toggled)
        self._blank_back_row.set_control(self._blank_back_toggle)
        layout.addWidget(self._blank_back_row)

        # ── 全局浮窗（默认开启）──
        # 暂存隔离铁律：开关只写入 SettingsStagingCache
        # （general.floating_pool_enabled），点击「确定」才经 _submit_settings
        # 由主窗口 set_floating_pool_enabled 生效。
        self._floating_pool_row = SettingsRow(
            title="全局浮窗",
            description="在桌面显示可拖入/拖出文件的悬浮窗",
        )
        self._floating_pool_toggle = StyledToggle(checked=True, size="default")
        self._floating_pool_toggle.toggled.connect(self._on_floating_pool_toggled)
        self._floating_pool_row.set_control(self._floating_pool_toggle)
        layout.addWidget(self._floating_pool_row)

        # ── 贴边吸附（默认开启；全局浮窗的子选项）──
        # 暂存隔离铁律：开关只写入 SettingsStagingCache
        # （general.floating_pool_snap_enabled），点击「确定」才经
        # _submit_settings 由主窗口 set_floating_pool_snap_enabled 生效。
        # 仅当「全局浮窗」开启时显示，显隐同样走子选项插入动画。
        self._floating_pool_snap_row = SettingsRow(
            title="贴边吸附",
            description="拖动浮窗靠近屏幕边缘时自动吸附",
            sub_option=True,
        )
        self._floating_pool_snap_toggle = StyledToggle(checked=True, size="default")
        self._floating_pool_snap_toggle.toggled.connect(
            self._on_floating_pool_snap_toggled
        )
        self._floating_pool_snap_row.set_control(self._floating_pool_snap_toggle)
        layout.addWidget(self._floating_pool_snap_row)

        # ── 启动时检查更新（默认开启；普通行，不是子选项）──
        # 暂存隔离铁律：开关只写入 SettingsStagingCache
        # （general.check_updates_on_startup），点击「确定」才经
        # _submit_settings 落盘；启动策略每次直读该设置。
        self._check_updates_row = SettingsRow(
            title="启动时检查更新",
            description="启动后静默检查新版本（每 24 小时最多一次）",
        )
        self._check_updates_toggle = StyledToggle(checked=True, size="default")
        self._check_updates_toggle.toggled.connect(self._on_check_updates_toggled)
        self._check_updates_row.set_control(self._check_updates_toggle)
        layout.addWidget(self._check_updates_row)

        # 子选项展开完成 → 仅在必要时做最小滚动，避免底部开关打开后
        # 新子项藏在视口下方；中间选项本来可见时不会产生滚动。
        self._system_row.reveal_finished.connect(
            lambda revealed, row=self._system_row: self._on_sub_option_reveal_finished(
                row, revealed
            )
        )
        self._floating_pool_snap_row.reveal_finished.connect(
            lambda revealed, row=self._floating_pool_snap_row: (
                self._on_sub_option_reveal_finished(row, revealed)
            )
        )
        layout.addStretch(1)

    # ── 交互 ──────────────────────────────────────────────────────────

    def _on_layout_segment_changed(self, index: int) -> None:
        """分段控件切换：只写入暂存缓存，并刷新介绍文字（不触碰主窗口与磁盘）。"""
        if self._layout_updating:
            return
        if 0 <= index < len(self.LAYOUT_MODES):
            self._layout_mode = self.LAYOUT_MODES[index]
            self._staging_cache.set("general.layout_mode", self._layout_mode)
            self._sync_description_text()
            self.staged_changed.emit()

    def _on_ai_entry_toggled(self, checked: bool) -> None:
        """AI 功能入口开关：只写入暂存缓存，点击「确定」才生效。"""
        if self._general_updating:
            return
        self._ai_entry = bool(checked)
        self._staging_cache.set("general.enable_ai_entry", self._ai_entry)
        self.staged_changed.emit()

    def _on_remote_drives_toggled(self, checked: bool) -> None:
        """网络盘/光驱开关：只写入暂存缓存，点击「确定」才生效。"""
        if self._general_updating:
            return
        self._include_remote_drives = bool(checked)
        self._staging_cache.set(
            "general.include_remote_drives", self._include_remote_drives
        )
        self.staged_changed.emit()

    def _on_blank_right_click_go_back_toggled(self, checked: bool) -> None:
        """空白区右键返回开关：只写入暂存缓存，点击「确定」才生效。"""
        if self._general_updating:
            return
        self._blank_right_click_go_back = bool(checked)
        self._staging_cache.set(
            "general.blank_right_click_go_back", self._blank_right_click_go_back
        )
        self.staged_changed.emit()

    def _on_show_hidden_files_toggled(self, checked: bool) -> None:
        """显示隐藏文件开关：只写入暂存缓存，点击「确定」才生效。

        关闭时联动强制关闭「显示受保护的系统文件」并收起其行——系统文件
        仅在开启隐藏文件浏览时才有意义。``_sync_general_toggles`` 传入
        ``animated=True``，让子选项以插入动画淡入/收起。
        """
        if self._general_updating:
            return
        self._show_hidden_files = bool(checked)
        self._staging_cache.set(
            "general.show_hidden_files", self._show_hidden_files
        )
        if not self._show_hidden_files:
            self._show_system_files = False
            self._staging_cache.set("general.show_system_files", False)
        self._request_sub_option_scroll(
            self._system_row if self._show_hidden_files else None
        )
        self._sync_general_toggles(animated=True)
        self.staged_changed.emit()

    def _on_show_system_files_toggled(self, checked: bool) -> None:
        """显示受保护系统文件开关：只写入暂存缓存，点击「确定」才生效。"""
        if self._general_updating:
            return
        self._show_system_files = bool(checked)
        self._staging_cache.set(
            "general.show_system_files", self._show_system_files
        )
        self._sync_general_toggles(animated=True)
        self.staged_changed.emit()

    def _on_floating_pool_toggled(self, checked: bool) -> None:
        """全局浮窗开关：只写入暂存缓存，点击「确定」才生效。

        「贴边吸附」是全局浮窗的子选项：浮窗关闭时收起该行（保留其开关
        偏好，重新开启浮窗后按原值展开），显隐走子选项插入动画。
        """
        if self._general_updating:
            return
        self._floating_pool_enabled = bool(checked)
        self._staging_cache.set(
            "general.floating_pool_enabled", self._floating_pool_enabled
        )
        self._request_sub_option_scroll(
            self._floating_pool_snap_row if self._floating_pool_enabled else None
        )
        self._sync_general_toggles(animated=True)
        self.staged_changed.emit()

    def _on_floating_pool_snap_toggled(self, checked: bool) -> None:
        """贴边吸附开关：只写入暂存缓存，点击「确定」才生效。"""
        if self._general_updating:
            return
        self._floating_pool_snap_enabled = bool(checked)
        self._staging_cache.set(
            "general.floating_pool_snap_enabled", self._floating_pool_snap_enabled
        )
        self.staged_changed.emit()

    def _on_check_updates_toggled(self, checked: bool) -> None:
        """启动时检查更新开关：只写入暂存缓存，点击「确定」才落盘。"""
        if self._general_updating:
            return
        self._check_updates = bool(checked)
        self._staging_cache.set(
            "general.check_updates_on_startup", self._check_updates
        )
        self.staged_changed.emit()

    def _layout_description_text(self) -> str:
        """返回当前布局的介绍文字 + 换行提示行。"""
        desc = self._LAYOUT_DESCRIPTIONS.get(
            self._layout_mode, self._LAYOUT_DESCRIPTIONS["workspace"]
        )
        return f"{desc}\n{self._LAYOUT_HINT}"

    def _sync_description_text(self) -> None:
        """把介绍文字同步到介绍标签（仅显示当前布局的介绍）。"""
        if self._layout_row is None:
            return
        label = getattr(self._layout_row, "desc_label", None)
        if label is not None:
            label.setText(self._layout_description_text())

    # ── 同步/刷新 ─────────────────────────────────────────────────────

    def _sync_layout_segment(self) -> None:
        """按当前布局模式同步分段选中项（守卫内切换，不触发处理器）。"""
        target = self.LAYOUT_INDEX.get(self._layout_mode, 1)
        self._layout_updating = True
        try:
            self._layout_segmented.set_current_index(target, animate=False)
        finally:
            self._layout_updating = False

    def _sync_general_toggles(self, animated: bool = False) -> None:
        """按当前状态同步八个开关与两个子选项的显隐（守卫内赋值，不写暂存）。

        各开关控件均带 ``None`` 守卫：缺位时仅跳过控件同步，状态值仍已由
        :meth:`refresh_from_staging` 更新。子选项显隐经
        :meth:`SettingsRow.set_revealed`：``animated=True`` 时播放插入/
        收起动画，初始化与刷新路径保持 ``False`` 以免后台播动画。

        Args:
            animated: 是否允许子选项显隐播放过渡动画。
        """
        self._general_updating = True
        try:
            if self._ai_toggle is not None:
                self._ai_toggle.checked = self._ai_entry
            if self._drives_toggle is not None:
                self._drives_toggle.checked = self._include_remote_drives
            if self._blank_back_toggle is not None:
                self._blank_back_toggle.checked = self._blank_right_click_go_back
            if self._hidden_toggle is not None:
                self._hidden_toggle.checked = self._show_hidden_files
            if self._system_toggle is not None:
                self._system_toggle.checked = self._show_system_files
            if self._system_row is not None:
                self._system_row.set_revealed(
                    self._show_hidden_files, animated=animated
                )
            if self._floating_pool_toggle is not None:
                self._floating_pool_toggle.checked = self._floating_pool_enabled
            if self._floating_pool_snap_toggle is not None:
                self._floating_pool_snap_toggle.checked = (
                    self._floating_pool_snap_enabled
                )
            if self._check_updates_toggle is not None:
                self._check_updates_toggle.checked = self._check_updates
            if self._floating_pool_snap_row is not None:
                # 贴边吸附是全局浮窗的子选项：仅在浮窗开启时显示。
                self._floating_pool_snap_row.set_revealed(
                    self._floating_pool_enabled, animated=animated
                )
        finally:
            self._general_updating = False

    def _request_sub_option_scroll(self, row: SettingsRow | None) -> None:
        """记录本次用户展开的子选项；仅当它当前未完整展开时才需要检查滚动。"""
        if row is None:
            self._pending_sub_option_scroll = None
            return
        self._pending_sub_option_scroll = (
            row if row.isHidden() or not row.is_revealed else None
        )

    def _on_sub_option_reveal_finished(
        self, row: SettingsRow, revealed: bool
    ) -> None:
        """子选项展开/收起完成：用户触发展开时，等布局稳定后按需滚动。

        只处理「本次由父开关打开」的那一行；初始化、刷新、收起都不滚动。
        """
        if row is not self._pending_sub_option_scroll:
            return
        self._pending_sub_option_scroll = None
        if not revealed or not self.isVisible():
            return
        QTimer.singleShot(0, lambda r=row: self._scroll_sub_option_into_view(r))

    def _find_ancestor_scroll_area(self) -> QScrollArea | None:
        """返回页面所在的滚动区（设置页由 ``_FloatingScrollArea`` 包裹）。"""
        parent = self.parentWidget()
        while parent is not None:
            if isinstance(parent, QScrollArea):
                return parent
            parent = parent.parentWidget()
        return None

    def _scroll_sub_option_into_view(self, row: SettingsRow) -> None:
        """仅当子选项被视口裁切时，补滚到「完整可见 + 少量留白」。

        Qt 中对应 Web 的 ``scrollIntoView({ block: 'nearest' })``：
        - 子项本来就完整可见：不滚动（中间选项不会因父开关变化而跳动）；
        - 子项被下/上边缘裁掉：只补缺失的像素数，并留出
          ``SETTINGS_SUB_SCROLL_MARGIN`` 的呼吸空间。
        """
        scroll = self._find_ancestor_scroll_area()
        if scroll is None or not scroll.isVisible():
            return
        viewport = scroll.viewport()
        if viewport.height() <= 0 or row.height() <= 0:
            return
        # 展开动画结束后 maxHeight 才解除；先让页面布局落地再取最终行高。
        self.layout().activate()
        top = row.mapTo(viewport, QPoint(0, 0)).y()
        bottom = top + row.height()
        viewport_h = viewport.height()
        if top >= 0 and bottom <= viewport_h:
            return  # 已完整可见：绝不滚动

        margin = SETTINGS_SUB_SCROLL_MARGIN
        if row.height() + 2 * margin >= viewport_h:
            # 子项高于视口：优先对齐顶部，保证标题先进入视野。
            delta = top - margin
        elif bottom > viewport_h - margin:
            delta = bottom - (viewport_h - margin)
        else:
            delta = top - margin
        if delta == 0:
            return

        vbar = scroll.verticalScrollBar()
        target = max(vbar.minimum(), min(vbar.maximum(), vbar.value() + delta))
        if target == vbar.value():
            return
        if not is_animation_enabled("settings_sub_option", default=True):
            vbar.setValue(target)
            return

        if self._sub_option_scroll_anim is not None:
            old = self._sub_option_scroll_anim
            self._sub_option_scroll_anim = None
            old.stop()
            old.deleteLater()
        anim = QPropertyAnimation(vbar, b"value", self)
        anim.setDuration(SETTINGS_SUB_SCROLL_MS)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.setStartValue(vbar.value())
        anim.setEndValue(target)
        anim.finished.connect(lambda a=anim: self._on_sub_option_scroll_finished(a))
        self._sub_option_scroll_anim = anim
        anim.start()

    def _on_sub_option_scroll_finished(self, anim: QPropertyAnimation) -> None:
        """滚动动画结束：清理引用（滚动动画不阻塞后续展开）。"""
        if self._sub_option_scroll_anim is anim:
            self._sub_option_scroll_anim = None
        anim.deleteLater()

    def refresh_from_staging(self) -> None:
        """从暂存缓存刷新控件展示（取消/重置未提交时恢复原始状态）。"""
        # 刷新/重置不属于用户展开动作：清掉待滚动标记，避免初始化时滚动。
        self._pending_sub_option_scroll = None
        saved = self._staging_cache.get("general.layout_mode", "workspace")
        self._layout_mode = saved if saved in self.LAYOUT_MODES else "workspace"
        saved_ai = self._staging_cache.get("general.enable_ai_entry", False)
        self._ai_entry = saved_ai if isinstance(saved_ai, bool) else False
        saved_remote = self._staging_cache.get(
            "general.include_remote_drives", False
        )
        self._include_remote_drives = (
            saved_remote if isinstance(saved_remote, bool) else False
        )
        saved_blank_back = self._staging_cache.get(
            "general.blank_right_click_go_back", False
        )
        self._blank_right_click_go_back = (
            saved_blank_back if isinstance(saved_blank_back, bool) else False
        )
        saved_hidden = self._staging_cache.get("general.show_hidden_files", False)
        self._show_hidden_files = (
            saved_hidden if isinstance(saved_hidden, bool) else False
        )
        saved_system = self._staging_cache.get("general.show_system_files", False)
        self._show_system_files = (
            saved_system if isinstance(saved_system, bool) else False
        )
        # 全局浮窗默认开启：缺键/非法值一律回退 True（general 下首个
        # 默认开启布尔）。
        saved_floating_pool = self._staging_cache.get(
            "general.floating_pool_enabled", True
        )
        self._floating_pool_enabled = (
            saved_floating_pool if isinstance(saved_floating_pool, bool) else True
        )
        # 贴边吸附默认开启：缺键/非法值一律回退 True（与浮窗开关同口径）。
        saved_floating_pool_snap = self._staging_cache.get(
            "general.floating_pool_snap_enabled", True
        )
        self._floating_pool_snap_enabled = (
            saved_floating_pool_snap
            if isinstance(saved_floating_pool_snap, bool)
            else True
        )
        # 启动时检查更新默认开启：缺键/非法值一律回退 True（与浮窗同口径）。
        saved_check_updates = self._staging_cache.get(
            "general.check_updates_on_startup", True
        )
        self._check_updates = (
            saved_check_updates if isinstance(saved_check_updates, bool) else True
        )
        self._sync_layout_segment()
        self._sync_general_toggles()
        self._sync_description_text()

    def refresh_theme(self) -> None:
        """主题切换时刷新页面内文字样式（按统一 token 重注册）。"""
        for row in (
            self._layout_row,
            self._ai_row,
            self._drives_row,
            self._hidden_row,
            self._system_row,
            self._blank_back_row,
            self._floating_pool_row,
            self._floating_pool_snap_row,
            self._check_updates_row,
        ):
            _refresh_settings_item_text(row)

    def get_staging_cache(self) -> SettingsStagingCache:
        """返回本页绑定的暂存缓存（调试链路使用）。"""
        return self._staging_cache


class AboutSettingsPage(QWidget):
    """关于页面 — 应用信息（logo + 名称 + 简介 + 版本行 + 链接行）。

    竖向居中排布，全部居中显示：应用 logo、「FreeAssetFilter」名称、一句话
    简介（与名称同字体同颜色）、版本行（``Version <版本号>`` + 制表位间隔 +
    「检查更新」按钮），以及「仓库页面 · 联系我们 · 开源许可」链接行——其中
    「仓库页面」「开源许可」为超链接，点击经系统默认浏览器打开。
    不写入 ``SettingsStagingCache``、不触碰主窗口 / 磁盘——本页无任何可提交
    设置项，天然遵循暂存隔离铁律。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._logo_label: QLabel | None = None
        self._app_name_label: QLabel | None = None
        self._tagline_label: QLabel | None = None
        self._version_label: QLabel | None = None
        self._check_update_btn: StyledButton | None = None
        self._links_label: QLabel | None = None
        self._contact_box: QFrame | None = None
        self._contact_name_label: QLabel | None = None
        self._contact_email_label: QLabel | None = None
        #: 联系信息框显隐状态（默认隐藏）
        self._contact_visible: bool = False
        #: 当前手动检查请求 id（仅同 id + manual 的结果驱动本页 UI）
        self._request_id: str | None = None
        #: 本页是否正在检查（连点/重试重入守卫）
        self._check_active: bool = False
        self._update_service: Any | None = None
        # 构造期一次性订阅；Qt 不会对 connect 去重，点击时不得重复连接。
        self._connect_update_service()
        self._build_ui()
        self.refresh_theme()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SETTINGS_ROW_GAP)

        # 应用信息整体竖向居中：上下各留伸展空间
        layout.addStretch(1)

        # ── 应用信息块：logo + 名称 + 简介 + 版本行 + 链接行（均居中） ──
        header = QVBoxLayout()
        header.setContentsMargins(0, 8, 0, 12)
        header.setSpacing(6)

        self._logo_label = QLabel()
        self._logo_label.setObjectName("AboutAppLogo")
        self._logo_label.setAlignment(Qt.AlignCenter)
        self._logo_label.setFixedSize(ABOUT_APP_LOGO_SIZE, ABOUT_APP_LOGO_SIZE)
        logo = _app_logo_pixmap(ABOUT_APP_LOGO_SIZE)
        if not logo.isNull():
            self._logo_label.setPixmap(logo)
        header.addWidget(self._logo_label, alignment=Qt.AlignHCenter)

        # 名称 / 简介 / 链接行标签铺满整行，由标签自身 setAlignment(AlignCenter)
        # 居中。注意：不可在此再传 alignment=AlignHCenter——对齐项只按 sizeHint
        # 宽度布局，而换行标签的 sizeHint 宽度为「未换行的整行宽度」，导致
        # 高度按错误宽度计算、多行文字被纵向裁切（历史缺陷）。
        self._app_name_label = QLabel(ABOUT_APP_NAME)
        self._app_name_label.setAlignment(Qt.AlignCenter)
        header.addWidget(self._app_name_label)

        self._tagline_label = QLabel(ABOUT_APP_TAGLINE)
        self._tagline_label.setAlignment(Qt.AlignCenter)
        self._tagline_label.setWordWrap(True)
        header.addWidget(self._tagline_label)

        # 版本行：Version <版本号> + 制表位间隔 + 「检查更新」按钮（整行居中）
        version_row = QHBoxLayout()
        version_row.setContentsMargins(0, 0, 0, 0)
        version_row.setSpacing(0)
        version_row.addStretch(1)

        self._version_label = QLabel(f"Version {_app_version()}".strip())
        version_row.addWidget(self._version_label)

        version_row.addSpacing(ABOUT_VERSION_TAB_GAP)

        self._check_update_btn = StyledButton("检查更新", variant="secondary", size="sm")
        self._check_update_btn.setCursor(Qt.PointingHandCursor)
        self._check_update_btn.clicked.connect(self._check_update)
        version_row.addWidget(self._check_update_btn)

        version_row.addStretch(1)
        header.addLayout(version_row)

        # 链接行：仓库页面 · 联系我们 · 开源许可（均为可点击链接，
        # 「联系我们」为内置伪协议，点击在下方展开联系信息框）
        self._links_label = QLabel()
        self._links_label.setObjectName("AboutLinksLabel")
        self._links_label.setAlignment(Qt.AlignCenter)
        self._links_label.setTextFormat(Qt.RichText)
        # 仅鼠标可点：不含键盘链接焦点（LinksAccessibleByKeyboard），且不接受
        # 焦点——否则点击后标签会保留键盘焦点、绘制出白色虚线焦点框（残留）。
        self._links_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse
        )
        self._links_label.setFocusPolicy(Qt.NoFocus)
        self._links_label.setCursor(Qt.PointingHandCursor)
        self._links_label.setOpenExternalLinks(False)
        self._links_label.linkActivated.connect(self._on_link_activated)
        header.addWidget(self._links_label)

        # 联系信息框：默认隐藏，点击「联系我们」后在链接行下方展开（矩形，双行）
        self._contact_box = QFrame()
        self._contact_box.setObjectName("AboutContactBox")
        self._contact_box.setFrameShape(QFrame.NoFrame)
        contact_layout = QVBoxLayout(self._contact_box)
        contact_layout.setContentsMargins(16, 10, 16, 10)
        contact_layout.setSpacing(2)

        self._contact_name_label = QLabel(ABOUT_CONTACT_NAME)
        self._contact_name_label.setAlignment(Qt.AlignCenter)
        contact_layout.addWidget(self._contact_name_label)

        self._contact_email_label = QLabel(ABOUT_CONTACT_EMAIL)
        self._contact_email_label.setAlignment(Qt.AlignCenter)
        contact_layout.addWidget(self._contact_email_label)

        self._contact_box.setVisible(False)
        contact_row = QHBoxLayout()
        contact_row.setContentsMargins(0, 0, 0, 0)
        contact_row.addStretch(1)
        contact_row.addWidget(self._contact_box)
        contact_row.addStretch(1)
        header.addLayout(contact_row)

        layout.addLayout(header)

        layout.addStretch(1)

    @staticmethod
    def _open_link(url: str) -> None:
        """经系统默认浏览器打开链接（失败仅告警，不阻断设置页）。"""
        try:
            QDesktopServices.openUrl(QUrl(url))
        except Exception as exc:  # noqa: BLE001 - 打开失败不影响设置页其余功能
            debug(f"打开链接失败：{exc}")

    def _on_link_activated(self, url: str) -> None:
        """链接激活分发：内置伪协议切换联系信息框，其余交系统浏览器打开。"""
        if url == ABOUT_CONTACT_SCHEME:
            self._toggle_contact_box()
            return
        self._open_link(url)

    def _toggle_contact_box(self) -> None:
        """切换联系信息框显隐（点击「联系我们」）。"""
        if self._contact_box is None:
            return
        # 用显式状态位而非 isVisible()：父级不可见时 isVisible() 恒为 False，
        # 会与真实显隐状态不一致。
        self._contact_visible = not self._contact_visible
        self._contact_box.setVisible(self._contact_visible)

    def _connect_update_service(self) -> None:
        """构造期一次性订阅更新服务信号。

        Qt 不会对同一 receiver/slot 的 ``connect`` 去重，若每次点击都连接，
        同一个结果会弹出多个对话框。因此只在此处连接一次；接收者是本页，
        页面销毁时 Qt 自动断开，禁止手动 ``disconnect``，也不要把
        ``destroyed`` 连到访问 ``self`` 的槽。
        """
        try:
            service = get_update_service()
        except Exception as exc:  # noqa: BLE001 - 服务异常不应拖垮设置页
            warning(f"初始化更新服务失败：{exc}")
            return
        self._update_service = service
        service.check_started.connect(self._on_check_started)
        service.check_finished.connect(self._on_check_finished)

    def _on_check_started(self, request_id: str, manual: bool) -> None:
        """记录当前手动检查 id（重试时也必须更新，否则结果被同 id 过滤）。

        Args:
            request_id: 服务分配的检查请求 id。
            manual: 是否手动检查；启动检查不触碰关于页。
        """
        if not manual:
            return
        self._request_id = request_id

    def _on_check_finished(
        self,
        request_id: str,
        manual: bool,
        info: object,
        error: object,
    ) -> None:
        """处理手动检查结果：只接受同 ``request_id`` 且 ``manual=True``。

        Args:
            request_id: 服务回传的请求 id。
            manual: 是否手动检查。
            info: ``UpdateInfo`` 或 ``None``。
            error: ``UpdateError`` 或 ``None``。
        """
        if not manual:
            return
        if self._request_id is None or request_id != self._request_id:
            return
        self._request_id = None
        self._check_active = False
        try:
            retry = self._make_retry_callback()
            typed_error = error if isinstance(error, UpdateError) else None
            typed_info = info if isinstance(info, UpdateInfo) else None
            if typed_error is not None:
                update_dialogs.show_check_error(typed_error, retry)
            elif typed_info is None:
                update_dialogs.show_check_error(UpdateError("internal"), retry)
            elif typed_info.update_available:
                update_dialogs.show_update_available(
                    typed_info,
                    self._make_download_callback(typed_info),
                )
            else:
                update_dialogs.show_no_update(typed_info)
        except NotImplementedError:
            debug("更新结果对话框尚未实现（Todo 16）")
        finally:
            self._set_checking_state(False)

    def _make_retry_callback(self) -> Callable[[], None]:
        """返回弱引用重试回调；禁止强引用关于页实例。

        Returns:
            Callable[[], None]: 页面仍存活时重新发起手动检查，否则静默 no-op。
        """
        weak_retry = weakref.WeakMethod(self._retry_check)

        def _retry() -> None:
            callback = weak_retry()
            if callback is not None:
                callback()

        return _retry

    def _make_download_callback(
        self, info: UpdateInfo
    ) -> Callable[[], None]:
        """返回弱引用下载回调；详情对话框关闭后不得延长页面生命周期。

        Args:
            info: 本次可更新版本的元数据，回调触发时原样交给下载入口。

        Returns:
            Callable[[], None]: 页面仍存活时开始下载，否则静默 no-op。
        """
        weak_download = weakref.WeakMethod(self._start_download)

        def _download() -> None:
            callback = weak_download()
            if callback is not None:
                callback(info)

        return _download

    def _start_download(self, info: UpdateInfo) -> None:
        """打开下载进度对话框并交由服务启动下载。

        Args:
            info: 本次可更新版本的元数据。
        """
        service = self._update_service
        if service is None:
            self._show_update_unavailable()
            return
        try:
            update_dialogs.show_download_progress(info, service)
        except Exception as exc:  # noqa: BLE001 - 下载入口失败不应拖垮设置页
            warning(f"打开下载进度对话框失败：{exc}")

    def _retry_check(self) -> None:
        """错误弹窗的重试入口：再次发起手动检查。"""
        self._begin_manual_check()

    def _set_checking_state(self, checking: bool) -> None:
        """切换按钮的检查中/空闲视觉状态。

        Args:
            checking: True 进入 0.0 进度并禁用；False 退出进度并恢复按钮。
        """
        if self._check_update_btn is None:
            return
        self._check_update_btn.setEnabled(not checking)
        self._check_update_btn.set_progress(0.0 if checking else None)

    def _show_update_unavailable(self) -> None:
        """提示更新组件不可用（仅 exe 缺失时使用）。"""
        try:
            create_basic_dialog(
                title="更新组件不可用",
                message=UpdateError("unavailable").message,
                cancel_text="",
                confirm_text="知道了",
            )
        except Exception as exc:  # noqa: BLE001 - 提示失败不影响设置页
            warning(f"显示更新组件不可用提示失败：{exc}")

    def _begin_manual_check(self) -> None:
        """校验可用性并发起手动检查；连点/重试进行中时直接忽略。"""
        if self._check_active:
            return
        service = self._update_service
        if service is None:
            self._show_update_unavailable()
            return
        try:
            available = bool(service.is_available())
        except Exception as exc:  # noqa: BLE001 - 探测失败按不可用处理
            warning(f"探测更新组件可用性失败：{exc}")
            available = False
        if not available:
            self._show_update_unavailable()
            return

        self._check_active = True
        self._set_checking_state(True)
        try:
            request_id = service.check(manual=True)
        except Exception as exc:  # noqa: BLE001 - 检查派发失败给出重试
            warning(f"发起更新检查失败：{exc}")
            self._check_active = False
            self._request_id = None
            self._set_checking_state(False)
            try:
                update_dialogs.show_check_error(
                    UpdateError("internal"), self._make_retry_callback()
                )
            except NotImplementedError:
                debug("更新错误对话框尚未实现（Todo 16）")
            return
        # 同步 check_started 已写入 id；启动检查在途（无 check_started）
        # 时用 check() 返回的既有 id 补齐，结果才能通过同 id 过滤。
        if self._check_active and self._request_id is None:
            self._request_id = request_id

    def _check_update(self) -> None:
        """检查更新：真实查询 GitHub 发布并展示检查中/无更新/错误三态。

        可用性、请求 id、同 id 过滤与重试全部由本方法链路处理；不再打开
        浏览器。发布页链接仍由链接行与详情对话框保留。
        """
        self._begin_manual_check()

    def _apply_header_styles(self) -> None:
        """按当前主题重注册应用信息块样式并重建链接行富文本。"""
        if self._app_name_label is not None:
            register_widget_qss(self._app_name_label, (
                f"background: transparent; border: none; color: {tm.text.name()};"
                " font-size: 22px; font-weight: 600;"
            ))
        if self._tagline_label is not None:
            # 与软件名称同字体、同颜色（仅字号更小）
            register_widget_qss(self._tagline_label, (
                f"background: transparent; border: none; color: {tm.text.name()};"
                " font-size: 12px;"
            ))
        if self._version_label is not None:
            register_widget_qss(self._version_label, (
                f"background: transparent; border: none; "
                f"color: {tm.qss_color(tm.text_hint)}; font-size: 12px;"
            ))
        if self._links_label is not None:
            register_widget_qss(self._links_label, (
                f"background: transparent; border: none; color: {tm.text.name()};"
                " font-size: 12px;"
            ))
            self._refresh_links_text()
        if self._contact_box is not None:
            register_widget_qss(self._contact_box, (
                f"#AboutContactBox {{ background: {tm.qss_color(tm.alpha_of(tm.fill, 30))};"
                f" border: 1px solid {tm.qss_color(tm.mid)}; border-radius: 6px; }}"
            ))
        for label in (self._contact_name_label, self._contact_email_label):
            if label is not None:
                register_widget_qss(label, (
                    f"background: transparent; border: none; color: {tm.text.name()};"
                    " font-size: 12px;"
                ))

    def _refresh_links_text(self) -> None:
        """重建链接行富文本（链接色随主题变化，linkActivated 统一分发）。"""
        if self._links_label is None:
            return
        accent = tm.qss_color(tm.accent)
        separator = tm.qss_color(tm.mid)
        link_style = f"color:{accent};text-decoration:none;"
        self._links_label.setText(
            f'<a href="{ABOUT_REPO_URL}" style="{link_style}">仓库页面</a>'
            f'<span style="color:{separator};">&nbsp;·&nbsp;</span>'
            f'<a href="{ABOUT_CONTACT_SCHEME}" style="{link_style}">联系我们</a>'
            f'<span style="color:{separator};">&nbsp;·&nbsp;</span>'
            f'<a href="{ABOUT_LICENSE_URL}" style="{link_style}">开源许可</a>'
        )

    def refresh_theme(self) -> None:
        """主题切换刷新：重注册应用信息块样式与链接行颜色。"""
        self._apply_header_styles()


class SettingsLayout(QWidget):
    """设置布局（暂存隔离 + 统一提交）。

    底部按钮语义：``重置``（警告 ``danger``，回默认值但不落盘，居左）、
    ``取消``（次选 ``secondary``，丢弃暂存并关闭）、``确定``（强调
    ``primary``，提交并关闭）。仅「确定」绑定提交事件（无「应用」按钮）。
    """

    def __init__(self, parent=None, host_window: QWidget | None = None):
        """初始化设置布局。

        Args:
            parent: 父控件。
            host_window: 宿主设置窗口（SettingsWindow）。设置窗口作为主窗口的
                owned 子窗口时，QWidget.window() 返回的是主窗口而非设置窗口
                本身，因此由创建方显式传入，供“应用”等需要整窗快照的逻辑使用。
        """
        super().__init__(parent)
        self._host_window = host_window
        # 暂存隔离层：快照 V2 全量，与主状态严格隔离
        self._staging_cache = SettingsStagingCache()
        _v2_boot = SettingsManagerV2()
        self._staging_cache.begin(copy.deepcopy(_v2_boot.load()))
        self._submitted: bool = False
        self._last_submit_ms: float = 0.0
        # 外观实时预览：记录打开设置窗口时的 tm 外观基线（取消回滚用）。
        self._appearance_baseline: dict = self._capture_appearance_baseline()
        # 背景图层最近一次已下发的图片文件名：滑块拖动预览时据此跳过图片重载。
        self._last_applied_bg_image: str = ""
        # 最近一次已下发图片的导入修订号：与文件名共同标识图片身份。单槽位
        # 同名覆盖时文件名不变，仅靠修订号才能识别"内容已更换、需重新下发"。
        self._last_applied_bg_rev: int = -1
        # 背景三项+参数最近一次已下发的完整状态：与目标一致时整段跳过
        # （主题切换/其它改动引发的重复下发不再触碰背景层）。
        self._last_applied_bg_state: tuple | None = None
        # 设置窗口预览过渡遮罩单实例（连续预览/回滚时先收尾上一张，避免叠加）。
        self._settings_preview_overlay = None
        # 外观预览去抖：首击立即下发，连点/拖动在窗口内合并为末尾一次补发。
        self._appearance_preview_burst_dirty: bool = False
        self._appearance_preview_timer = QTimer(self)
        self._appearance_preview_timer.setSingleShot(True)
        self._appearance_preview_timer.setInterval(APPEARANCE_PREVIEW_DEBOUNCE_MS)
        self._appearance_preview_timer.timeout.connect(
            self._on_appearance_preview_timer
        )
        # 底栏「有更改未保存」提示标签（_create_bottom_buttons 创建）。
        self._dirty_hint: QLabel | None = None
        # 底部按钮栏（关于页隐藏）与关于页在内容栈中的索引
        self._bottom_bar: QFrame | None = None
        self._about_page_index: int = -1

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── 侧边栏（使用 StyledSidebar 组件，透明背景以显示 Mica） ──
        self._sidebar = StyledSidebar(
            title="",
            width=220,
            compact=False,
            transparent=True,  # 透明背景以显示 Mica 效果
            parent=self,
        )
        # 侧边栏列表顺序 = 页面顺序：通用（第一项）→ 外观 → 关于
        self._sidebar.add_item("通用", icon_svg="gear")
        self._sidebar.add_item("外观", icon_svg="sun")
        self._sidebar.add_item("关于", icon_svg="info")
        self._sidebar.item_selected.connect(self._on_item_selected)
        main_layout.addWidget(self._sidebar)

        # ── 内容区（右侧） ──
        self._content_area = QFrame()
        self._content_area.setObjectName("SettingsContentArea")
        content_layout = QVBoxLayout(self._content_area)
        # 右/下 24px 与卡片、底栏按钮统一对齐；顶部留 12px 呼吸（标题栏下沿）。
        content_layout.setContentsMargins(0, 12, 24, 24)
        content_layout.setSpacing(0)

        # 使用 QStackedWidget 实现多页面切换
        self._stack = QStackedWidget()
        register_widget_qss(self._stack,("background: transparent; border: none;"))

        # 页面 0：通用（列表第一项；包进透明滚动区域，小窗口下可滚动访问）
        self._general_page = GeneralSettingsPage(
            staging_cache=self._staging_cache
        )
        general_scroll = self._wrap_page_in_scroll(self._general_page)
        general_card = self._create_page_card(general_scroll)
        general_scroll.attach_floating_bar_region(general_card)
        self._stack.addWidget(general_card)

        # 页面 1：外观（包进透明滚动区域，小窗口尺寸下内容可滚动访问）
        self._appearance_page = AppearanceSettingsPage(staging_cache=self._staging_cache)
        appearance_scroll = self._wrap_page_in_scroll(self._appearance_page)
        appearance_card = self._create_page_card(appearance_scroll)
        # 浮动滚动条锚定到外观卡片（#SettingsCard）右缘：右缘水平贴边、
        # 上下内缩 10*dpi，与文件选择器/文件池浮动滚动条间距一致
        appearance_scroll.attach_floating_bar_region(appearance_card)
        self._stack.addWidget(appearance_card)

        # 页面 2：关于（应用信息竖向居中，无长内容，无需外包滚动区）
        self._about_page = AboutSettingsPage()
        about_card = self._create_page_card(self._about_page)
        self._about_page_index = self._stack.addWidget(about_card)

        content_layout.addWidget(self._stack, stretch=1)

        # ── 底部按钮栏（关于页无可提交项，选中该页时隐藏） ──
        self._bottom_bar = self._create_bottom_buttons()
        content_layout.addWidget(self._bottom_bar)

        # 应用初始样式
        self._refresh_styles()

        main_layout.addWidget(self._content_area, stretch=1)

        self.setLayout(main_layout)

        # 默认选中第一项（通用）
        self._stack.setCurrentIndex(0)
        self._sync_bottom_bar(0)

        # 主题切换时刷新内容区背景（生效值变化 + 偏好变化均需刷新，
        # 后者覆盖生效值不变但分段需切换的场景，如 白天→跟随系统且系统正为浅色）。
        tm.theme_changed.connect(self._on_theme_changed)
        # 强调色（主题色）单独变化只发 colors_updated：设置页内嵌强调色的
        # 样式片段（输入框、卡片、侧栏）与生效值均需即时重注册。
        tm.colors_updated.connect(self._on_theme_changed)
        try:
            tm.theme_mode_changed.connect(self._on_theme_changed)
        except Exception as exc:
            debug(f"主题模式信号连接失败（设置页可能不随系统主题刷新）：{exc}")

        # 外观实时预览 + 「有更改未保存」提示连线（失败仅告警，不影响可用性）。
        try:
            # 即时项（深色模式 / 主题色 / 背景模式）：首击立即预览，
            # 连点由去抖定时器合并成一次补发。
            self._appearance_page.appearance_changed.connect(
                self._request_appearance_preview
            )
            # 拖动类（模糊度 / 透明度滑块、色板拖动）：纯末尾合并，
            # 拖动过程不逐帧重下发背景层。
            self._appearance_page.appearance_params_changed.connect(
                self._request_appearance_params_preview
            )
            self._appearance_page.staged_changed.connect(self._update_dirty_hint)
            self._general_page.staged_changed.connect(self._update_dirty_hint)
        except Exception as exc:
            debug(f"设置页实时预览信号连接失败：{exc}")

    def _wrap_page_in_scroll(self, page: QWidget) -> _FloatingScrollArea:
        """将设置页包进浮动滚动条滚动区（styled 滚动条 + 丝滑滚动）。"""
        scroll = _FloatingScrollArea()
        scroll.setWidget(page)
        return scroll

    def _create_page_card(self, inner_widget: QWidget | None) -> QFrame:
        """创建圆角卡片容器，内部放置给定 widget。

        内容以 ``stretch=1`` 铺满卡片内容区（与文件选择器/文件池滚动区同
        规约）：页面滚动区（``_FloatingScrollArea``）若依赖其（缓存的）
        ``sizeHint`` 定高，会停在首次布局时的内容高度——切换「窗口背景」
        等操作使页面内容变高后，新增行会被从中间裁断，且缩放窗口不恢复。
        无内容时保留旧行为的弹性空白（历史占位卡片场景）。
        """
        card = QFrame()
        card.setObjectName("SettingsCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 20, 20, 20)
        card_layout.setSpacing(12)

        if inner_widget is not None:
            card_layout.addWidget(inner_widget, stretch=1)
        else:
            card_layout.addStretch()
        return card

    def _refresh_styles(self) -> None:
        """刷新卡片样式与三页文字样式。

        卡片/内容区颜色在这里统一重注册；页面内文字样式一律由各页
        ``refresh_theme()`` 按统一 token 处理——禁止在这里遍历卡片下的
        所有 ``QLabel`` 通刷（历史缺陷：描述文字与滑动条读数被一并覆盖
        成标题字号/字重/颜色）。
        """
        # 语义 token：浅深模式 alpha 一致，仅按主题反转颜色亮度。
        fill_color = tm.qss_color(tm.panel_fill)
        border_color = tm.qss_color(tm.panel_border)

        register_widget_qss(self._stack,(f"""
            #SettingsCard {{
                background-color: {fill_color};
                border: 1px solid {border_color};
                border-radius: 8px;
            }}
        """))
        register_widget_qss(self._content_area,("background-color: transparent; border: none;"))

        # 底栏「有更改未保存」提示按语义 warning 色重注册（随主题变化）。
        if self._dirty_hint is not None:
            register_widget_qss(
                self._dirty_hint,
                (f"color: {tm.qss_color(tm.warning)}; font-size: 12px;"),
            )

        # 三页各自刷新（外观页含自绘色块重绘）
        appearance_page = getattr(self, "_appearance_page", None)
        if appearance_page is not None:
            appearance_page.refresh_theme()
            for btn in appearance_page.color_buttons:
                btn.update()
        general_page = getattr(self, "_general_page", None)
        if general_page is not None:
            general_page.refresh_theme()
        about_page = getattr(self, "_about_page", None)
        if about_page is not None:
            about_page.refresh_theme()

    def _on_item_selected(self, index: int, label: str) -> None:
        """侧边栏导航项选中回调"""
        if 0 <= index < self._stack.count():
            self._stack.setCurrentIndex(index)
        self._sync_bottom_bar(index)

    def _sync_bottom_bar(self, index: int) -> None:
        """按当前页同步底部按钮栏显隐：关于页无可提交项，隐藏「重置/取消/保存」。"""
        if self._bottom_bar is not None:
            self._bottom_bar.setVisible(index != self._about_page_index)

    def _on_theme_changed(self, _theme: str) -> None:
        """主题切换时刷新样式"""
        self.refresh_theme()

    # ── 底部按钮 ──────────────────────────────────────────────

    def _create_bottom_buttons(self) -> QFrame:
        """创建底部按钮栏（重置 + 未保存提示 + 取消 + 保存）。

        样式映射（仅复用 ``StyledButton``，不自绘）：
        保存 = ``primary``（强调，主题色）、取消 = ``secondary``（次选）、
        重置 = ``danger``（警告）。
        布局：左 ``重置``，中 ``有更改未保存``（仅非外观项改动时显示），
        右 ``取消`` + ``保存``（无「应用」按钮）。

        Returns:
            QFrame: 底部按钮栏容器。
        """
        bar = QFrame()
        bar.setObjectName("SettingsBottomBar")
        register_widget_qss(bar,("background: transparent; border: none;"))
        layout = QHBoxLayout(bar)
        # 与卡片间距统一：顶部 12px（SETTINGS_ROW_GAP 之上再留一档），按钮间距 12px。
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(12)

        self._reset_btn = StyledButton("重置", variant="danger", size="sm")
        self._reset_btn.clicked.connect(self._on_reset_clicked)
        layout.addWidget(self._reset_btn)

        layout.addStretch()

        # 「有更改未保存」提示：仅在存在非外观项改动时显示（见 _update_dirty_hint），
        # 位于重置与取消之间（水平居中）。
        self._dirty_hint = QLabel("有更改未保存")
        self._dirty_hint.setVisible(False)
        register_widget_qss(
            self._dirty_hint,
            (f"color: {tm.qss_color(tm.warning)}; font-size: 12px;"),
        )
        layout.addWidget(self._dirty_hint)

        layout.addStretch()

        self._cancel_btn = StyledButton("取消", variant="secondary", size="sm")
        self._cancel_btn.clicked.connect(self._on_cancel_clicked)
        layout.addWidget(self._cancel_btn)

        self._confirm_btn = StyledButton("保存", variant="primary", size="sm")
        self._confirm_btn.clicked.connect(self._on_confirm_clicked)
        layout.addWidget(self._confirm_btn)

        # 兼容残留：历史「应用」按钮已移除，不再创建 _apply_btn；
        # _on_apply_clicked 保留为内部别名，仅供旧调用方兼容。
        self._apply_btn = None  # type: ignore[assignment]

        return bar

    def _on_reset_clicked(self) -> None:
        """重置按钮 — 暂存区回默认值并刷新界面，不直接落盘（需确定提交）。

        外观项为实时项：重置后同步做一次实时预览，保持 ``tm`` 与暂存默认值
        一致（否则关闭时自动保存会把默认值写入磁盘而运行态仍是旧外观）。
        """
        self._staging_cache.reset_to_defaults(copy.deepcopy(DEFAULT_SETTINGS_V2))
        self._appearance_page.refresh_from_staging()
        self._general_page.refresh_from_staging()
        try:
            dirty = set(self._staging_cache.dirty_keys())
        except Exception:
            dirty = set()
        self._update_dirty_hint()
        # 仅当外观默认值确有变化时才重新预览（避免无谓过渡动画）。
        if dirty & self._AUTO_SAVE_APPEARANCE_KEYS:
            self._on_appearance_preview()

    def _on_cancel_clicked(self) -> None:
        """取消按钮 — 回滚实时预览的外观至打开时状态，丢弃暂存并关闭。"""
        self._flush_appearance_preview()
        try:
            dirty = set(self._staging_cache.dirty_keys())
            if dirty & self._AUTO_SAVE_APPEARANCE_KEYS:
                self._revert_appearance_to_baseline()
        except Exception as exc:
            debug(f"取消回滚外观失败（按无改动处理）：{exc}")
        self._staging_cache.discard()
        self._appearance_page.refresh_from_staging()
        self._general_page.refresh_from_staging()
        self._update_dirty_hint()
        self._close_host_window()

    def _on_apply_clicked(self) -> None:
        """兼容旧「应用」调用：等价于提交但不关闭（按钮已移除）。"""
        self._submit_settings(close_after=False)

    def _on_confirm_clicked(self) -> None:
        """确定按钮 — 提交事件（立即应用并关闭设置窗口）。"""
        if self._submit_settings(close_after=False):
            self._submitted = True
            self._close_host_window()

    # ── 外观实时预览 / 回滚 / 关闭自动保存 ────────────────────────────

    #: 外观类「自动保存」键：点 ✕ 关闭时自动落盘；且不计入「有更改未保存」提示。
    #: 其余键（``general.*``、``performance.profile``）属「非外观项」，只能经
    #: 「保存」按钮提交，✕ 关闭时静默丢弃。
    _AUTO_SAVE_APPEARANCE_KEYS: frozenset = frozenset({
        "appearance.theme_mode",
        "appearance.theme",
        "appearance.colors",
        "appearance.accent_color",
        "appearance.background",
    })

    def _capture_appearance_baseline(self) -> dict:
        """记录打开设置窗口时 tm 的外观（深色模式 / 配色 / 背景），供取消回滚。

        Returns:
            dict: ``{"theme_mode": str, "colors": dict, "background": dict}``。
                读取失败时对应字段退化为空/默认，不影响后续流程。
        """
        try:
            try:
                mode = tm.get_theme_mode()
            except Exception:
                mode = "dark" if tm.is_dark_theme() else "light"
            try:
                colors = tm.snapshot_colors()
            except Exception:
                colors = {}
            try:
                staged = self._staging_cache.snapshot_staged()
                bg = (staged.get("appearance", {}) or {}).get("background", {})
                background = copy.deepcopy(bg) if isinstance(bg, dict) else {}
            except Exception:
                background = {}
            return {"theme_mode": mode, "colors": colors, "background": background}
        except Exception as exc:  # noqa: BLE001 - 基线抓取失败不阻塞窗口打开
            debug(f"外观基线抓取失败：{exc}")
            return {"theme_mode": "dark", "colors": {}, "background": {}}

    def _resolve_appearance_values(self, appearance: dict) -> "tuple[str, str, dict]":
        """从外观字典解析出规范的 ``(theme_mode, accent, background)``。

        缺失/非法值按与提交路径一致的口径回退（主题偏好缺失时由生效值推导）。

        Args:
            appearance: ``staged["appearance"]`` 子字典。

        Returns:
            tuple[str, str, dict]: ``(偏好值, 强调色, 背景字典)``。
        """
        appearance = appearance if isinstance(appearance, dict) else {}
        theme_mode = appearance.get("theme_mode", None)
        if theme_mode not in ("light", "dark", "system"):
            legacy = appearance.get("theme", "light")
            theme_mode = "dark" if legacy == "dark" else "light"
        accent = appearance.get("accent_color", "#007AFF")
        if not isinstance(accent, str) or not accent:
            accent = "#007AFF"
        bg = appearance.get("background", {}) or {}
        if not isinstance(bg, dict):
            bg = {}
        return theme_mode, accent, bg

    def _start_settings_overlay(self) -> None:
        """给设置窗口起整窗交叉淡入淡出过渡（单实例去重；与提交路径同款）。

        不传 ``origin`` —— 遮罩走透明度淡出模式：旧外观快照按 1→0 渐隐，
        透出下方已切换的新主题（时长 ``SETTINGS_THEME_FADE_MS``）。相比径向
        揭示（主窗口从主题按钮向外扩散），整窗淡化没有扩散硬边、观感更平滑。
        """
        settings_window = (
            self._host_window if self._host_window is not None else self.window()
        )
        if settings_window is None:
            return
        prev = self._settings_preview_overlay
        if prev is not None:
            try:
                from shiboken6 import isValid

                if isValid(prev):
                    prev.finish_now()
            except Exception:  # noqa: BLE001 - 已销毁引用按无需收尾处理
                pass
            self._settings_preview_overlay = None
        try:
            overlay = ThemeTransitionOverlay.from_widget(
                settings_window, duration_ms=SETTINGS_THEME_FADE_MS
            )
            overlay.start()
            self._settings_preview_overlay = overlay
        except Exception as exc:  # noqa: BLE001 - 遮罩失败不阻塞实时预览
            debug(f"设置窗口预览过渡遮罩启动失败：{exc}")

    def _request_appearance_preview(self) -> None:
        """外观即时项改动入口：首击立即下发，连点合并为一次补发。

        ``appearance_changed`` 的槽。去抖窗口未开启（单击）时直接同步
        预览一次，保证「点了就换」；窗口内再次改动只记脏，由单发定时器
        在窗口末尾补发一次——连点不会堆叠多次全量下发（历史缺陷：
        每次点击都跑整套主题链路 + 两轮全表重刷，连点叠加成卡死）。
        """
        if not self._appearance_preview_timer.isActive():
            self._on_appearance_preview()
        else:
            self._appearance_preview_burst_dirty = True
        self._appearance_preview_timer.start()

    def _request_appearance_params_preview(self) -> None:
        """外观拖动项改动入口：纯末尾合并（拖动过程不逐帧下发）。"""
        self._appearance_preview_burst_dirty = True
        self._appearance_preview_timer.start()

    def _on_appearance_preview_timer(self) -> None:
        """去抖窗口到期：窗口内确有积压改动才补发一次。"""
        if not self._appearance_preview_burst_dirty:
            return
        self._appearance_preview_burst_dirty = False
        self._on_appearance_preview()

    def _flush_appearance_preview(self) -> None:
        """立即补发挂起的外观预览（提交 / 回滚 / 关窗 / 取消前调用）。

        保证落盘与运行态一致：去抖窗口内尚未下发的最后状态在此补上，
        否则重启后会与磁盘记录不符（外观项为「点 ✕ 也保存」语义）。
        """
        self._appearance_preview_timer.stop()
        if not self._appearance_preview_burst_dirty:
            return
        self._appearance_preview_burst_dirty = False
        self._on_appearance_preview()

    @staticmethod
    def _target_effective_theme(mode: str) -> str:
        """把主题偏好解析为将要生效的明暗值（只读，不触碰 ``tm``）。

        Args:
            mode: 偏好值 ``"light"`` | ``"dark"`` | ``"system"``。

        Returns:
            ``"light"`` 或 ``"dark"``；跟随系统读取失败时回退当前生效值。
        """
        if mode == "system":
            try:
                from freeassetfilter.ui.theme.system_theme import (
                    get_windows_system_theme,
                )

                resolved = get_windows_system_theme()
            except Exception:
                resolved = ""
            if resolved in ("light", "dark"):
                return resolved
            return "dark" if tm.is_dark_theme() else "light"
        return "light" if mode == "light" else "dark"

    @staticmethod
    def _accent_differs(color: str) -> bool:
        """目标强调色与 ``tm`` 当前值是否不同（QColor 归一化比较）。

        Args:
            color: 目标颜色（``#RRGGBB`` / ``#RRGGBBAA``）。

        Returns:
            True 表示需要下发；取值失败按需要下发处理。
        """
        try:
            from PySide6.QtGui import QColor

            target = QColor(color)
            if not target.isValid():
                return False
            return QColor(tm.accent).rgba() != target.rgba()
        except Exception:
            return True

    def _on_appearance_preview(self) -> None:
        """实时预览外观改动：下发 ``tm`` + 主窗口并起过渡，不落盘。

        由 :meth:`_request_appearance_preview`（首击立即 + 连点补发）与
        :meth:`_request_appearance_params_preview`（拖动末尾合并）触发。
        落盘统一留到「保存」按钮或点 ✕ 关闭时的 :meth:`_persist_appearance_only`。

        短路原则（性能关键）：目标与当前一致的部分整段跳过——背景模式
        切换不再重设主题/主题色；明暗未真正翻转时不抓整窗快照、不建过渡
        遮罩（抓拍是同步大头，纯背景改动零抓拍、零主题广播）。
        """
        staged = self._staging_cache.snapshot_staged()
        appearance = staged.get("appearance", {}) if isinstance(staged, dict) else {}
        theme_mode, accent, bg = self._resolve_appearance_values(appearance)
        resolved_accent = (
            get_system_accent_color() if accent.lower() == "auto" else accent
        )

        try:
            mode_changed = theme_mode != tm.get_theme_mode()
        except Exception:
            mode_changed = True
        try:
            effective_changed = (
                self._target_effective_theme(theme_mode) != tm.effective_theme()
            )
        except Exception:
            effective_changed = True
        accent_changed = self._accent_differs(resolved_accent)

        if effective_changed:
            # 主窗口过渡预抓拍（内容层径向扩散 + 背景层交叉淡入，复用现有链路）。
            try:
                main_window = self._appearance_page.find_main_window()
                if main_window is not None and hasattr(main_window, "begin_theme_transition"):
                    main_window.begin_theme_transition()
            except Exception:  # noqa: BLE001 - 预抓拍失败不阻塞预览
                pass
            # 设置窗口平滑过渡遮罩（明暗真正翻转才需要）。
            self._start_settings_overlay()

        try:
            if mode_changed:
                tm.set_theme_mode(theme_mode)
            if accent_changed:
                tm.set_color("accent.primary", resolved_accent)
        except Exception as exc:  # noqa: BLE001 - 预览下发失败仅告警
            debug(f"外观预览下发主题失败：{exc}")
        self._apply_staged_background_to_main_window(bg)

    def _revert_appearance_to_baseline(self) -> None:
        """取消时把 ``tm`` 外观回滚到打开设置窗口时的基线（带过渡）。"""
        base = self._appearance_baseline if isinstance(self._appearance_baseline, dict) else {}
        try:
            main_window = self._appearance_page.find_main_window()
            if main_window is not None and hasattr(main_window, "begin_theme_transition"):
                main_window.begin_theme_transition()
        except Exception:  # noqa: BLE001 - 预抓拍失败不阻塞回滚
            pass
        self._start_settings_overlay()
        mode = base.get("theme_mode", "dark")
        if mode not in ("light", "dark", "system"):
            mode = "dark"
        colors = base.get("colors", {}) or {}
        try:
            tm.set_theme_mode(mode)
            if colors:
                tm.replace_colors(copy.deepcopy(colors))
        except Exception as exc:  # noqa: BLE001 - 回滚失败仅告警
            debug(f"外观回滚恢复 tm 失败：{exc}")
        # 强制下次重新下发背景（模式/图片/参数可能已变）。
        self._last_applied_bg_image = ""
        self._last_applied_bg_rev = -1
        self._last_applied_bg_state = None
        self._apply_staged_background_to_main_window(base.get("background", {}) or {})

    def _persist_appearance_only(self) -> None:
        """把暂存的外观三项落盘（点 ✕ 关闭自动保存；不触碰非外观项）。

        外观在改动时已实时生效，此处只补磁盘写入，使重启后恢复。
        """
        staged = self._staging_cache.snapshot_staged()
        appearance = staged.get("appearance", {}) if isinstance(staged, dict) else {}
        theme_mode, _resolved, bg = self._resolve_appearance_values(appearance)
        saved_accent = appearance.get("accent_color", "#007AFF")
        if not isinstance(saved_accent, str) or not saved_accent:
            saved_accent = "#007AFF"
        try:
            theme = tm.effective_theme()
        except Exception:
            theme = "dark" if tm.is_dark_theme() else "light"
        bg_mode = bg.get("mode", "mica")
        if bg_mode not in ("mica", "image", "minimalist"):
            bg_mode = "mica"
        bg_blur = _normalize_bg_blur(bg.get("blur", IMAGE_BG_BLUR_DEFAULT))
        bg_transparency = _normalize_bg_transparency(
            bg.get("transparency", IMAGE_BG_TRANSPARENCY_DEFAULT)
        )
        colors_dict = tm.snapshot_colors()
        try:
            colors_dict["accent"]["primary"] = saved_accent
        except Exception:  # noqa: BLE001 - 配色结构异常时保持原值
            pass
        v2 = SettingsManagerV2()
        v2.load()
        v2.set("appearance.theme_mode", theme_mode)
        v2.set("appearance.theme", theme)
        v2.set("appearance.accent_color", saved_accent)
        v2.set("appearance.colors", colors_dict)
        v2.set("appearance.background", {
            "mode": bg_mode,
            "image": str(bg.get("image", "") or ""),
            "ambient": bool(bg.get("ambient", True)),
            "blur": bg_blur,
            "transparency": bg_transparency,
        })
        v2.save()

    def _update_dirty_hint(self) -> None:
        """按暂存脏键刷新底栏「有更改未保存」提示可见性。

        仅当存在**非外观键**（``general.*`` / ``performance.profile``）时显示——
        外观项是即时项（点 ✕ 自动保存），无需提示。
        """
        if self._dirty_hint is None:
            return
        try:
            has_other = any(
                key not in self._AUTO_SAVE_APPEARANCE_KEYS
                for key in self._staging_cache.dirty_keys()
            )
        except Exception:
            has_other = False
        self._dirty_hint.setVisible(has_other)

    def _submit_settings(self, close_after: bool = False) -> bool:
        """设置提交事件处理函数（确定按钮绑定，事务性提交）。

        流程：暂存快照 → 校验 → 主题过渡遮罩 → 应用到 ``tm`` → 应用背景到
        主窗口 → 应用性能档位到三钩子 → 持久化到 ``SettingsManagerV2`` →
        基线前移。任一步失败则回滚 ``tm`` 与定时器档位并返回 False，
        不污染磁盘与运行时。

        Args:
            close_after: 预留关闭标志（关闭统一由调用方执行，便于测试断言）。

        Returns:
            bool: 提交成功返回 True，失败返回 False。
        """
        t0 = time.perf_counter()
        # 提交前先补发去抖窗口内未下发的最后外观状态，保证运行态 = 待落盘态。
        self._flush_appearance_preview()
        staged = self._staging_cache.commit_snapshot()
        appearance = staged.get("appearance", {}) if isinstance(staged, dict) else {}
        theme_mode = appearance.get("theme_mode", None)
        if theme_mode not in ("light", "dark", "system"):
            # 旧快照迁移：由生效值推导偏好。
            legacy_theme = appearance.get("theme", "light")
            theme_mode = "dark" if legacy_theme == "dark" else "light"
        accent = appearance.get("accent_color", "#007AFF")
        staged_bg = appearance.get("background", {}) or {}
        bg_mode = staged_bg.get("mode", "mica")
        if bg_mode not in ("mica", "image", "minimalist"):
            bg_mode = "mica"
        bg_blur = _normalize_bg_blur(
            staged_bg.get("blur", IMAGE_BG_BLUR_DEFAULT)
        )
        bg_transparency = _normalize_bg_transparency(
            staged_bg.get("transparency", IMAGE_BG_TRANSPARENCY_DEFAULT)
        )

        # 通用页：主界面布局（classic 经典三栏 / workspace 新布局）。
        staged_general = staged.get("general", {}) if isinstance(staged, dict) else {}
        if isinstance(staged_general, dict):
            layout_mode = staged_general.get("layout_mode", "workspace")
        else:
            layout_mode = "workspace"
        if layout_mode not in ("classic", "workspace"):
            layout_mode = "workspace"
        # 通用页：AI 入口 / 网络盘与光驱 / 空白区右键返回 / 显示隐藏文件 /
        # 显示受保护系统文件开关（缺失/非法一律回退 False）；全局浮窗与
        # 贴边吸附默认开启（缺失/非法回退 True）。
        if isinstance(staged_general, dict):
            ai_entry = staged_general.get("enable_ai_entry", False)
            include_remote = staged_general.get("include_remote_drives", False)
            blank_back = staged_general.get("blank_right_click_go_back", False)
            show_hidden = staged_general.get("show_hidden_files", False)
            show_system = staged_general.get("show_system_files", False)
            floating_pool = staged_general.get("floating_pool_enabled", True)
            floating_pool_snap = staged_general.get(
                "floating_pool_snap_enabled", True
            )
        else:
            ai_entry = False
            include_remote = False
            blank_back = False
            show_hidden = False
            show_system = False
            floating_pool = True
            floating_pool_snap = True
        if not isinstance(ai_entry, bool):
            ai_entry = False
        if not isinstance(include_remote, bool):
            include_remote = False
        if not isinstance(blank_back, bool):
            blank_back = False
        if not isinstance(show_hidden, bool):
            show_hidden = False
        if not isinstance(show_system, bool):
            show_system = False
        # 未开启隐藏文件浏览时，系统文件开关强制关闭（联动语义与页面一致）。
        if not show_hidden:
            show_system = False
        if not isinstance(floating_pool, bool):
            floating_pool = True
        if not isinstance(floating_pool_snap, bool):
            floating_pool_snap = True
        # 启动时检查更新：仅接受真实 bool（缺失/非法一律回退 True，与
        # V2 合并口径一致）；本键只落盘，不触发网络或更新服务。
        if isinstance(staged_general, dict):
            check_updates_on_startup = staged_general.get(
                "check_updates_on_startup", True
            )
        else:
            check_updates_on_startup = True
        if not isinstance(check_updates_on_startup, bool):
            check_updates_on_startup = True

        # 性能档位：只接受三档合法值，缺失/非法回退 balanced（与 V2 合并口径一致）。
        staged_perf = staged.get("performance", {}) if isinstance(staged, dict) else {}
        if isinstance(staged_perf, dict):
            perf_profile = staged_perf.get("profile", "balanced")
        else:
            perf_profile = "balanced"
        if perf_profile not in ("performance", "balanced", "powersave"):
            perf_profile = "balanced"

        saved_accent = accent
        if isinstance(accent, str) and accent.lower() == "auto":
            accent = get_system_accent_color()

        # V2 持久化回滚上下文：save() 或后续步骤失败时把本键内存值还原到
        # 提交前快照。哨兵保证「尚未走到快照点」时不会误回滚。
        v2: SettingsManagerV2 | None = None
        _unset_value = object()
        prev_check_updates_on_startup: object = _unset_value

        # 设置窗口过渡：与实时预览同款整窗交叉淡入淡出（单实例去重）；
        # 遮罩创建失败仅告警，不阻塞提交本身。
        self._start_settings_overlay()

        prev_mode = tm.get_theme_mode()
        prev_theme = "dark" if tm.is_dark_theme() else "light"
        prev_colors = tm.snapshot_colors()
        try:
            prev_perf_profile = _get_timing_active_profile()
        except Exception:
            prev_perf_profile = "balanced"
        # 主窗口过渡预抓拍：本次改布局走平滑渐变（无扩散圆洞），其余维持主题
        # 径向链路——布局切换不再自主题按钮向外扩散；tm 翻转后主窗槽内各背景
        # 层 sync 才能以旧帧为底做 450ms 交叉淡入，否则退化为裸 update 露出
        # _root 形成闪现。
        try:
            main_window = self._appearance_page.find_main_window()
            if main_window is not None:
                method = "begin_theme_transition"
                if self._layout_mode_will_change(main_window, layout_mode):
                    method = "begin_layout_transition"
                starter = getattr(main_window, method, None)
                if starter is None:
                    # 测试替身/旧接口缺新方法：退回主题链路（不阻塞布局切换）
                    starter = getattr(main_window, "begin_theme_transition", None)
                if starter is not None:
                    starter()
        except Exception:  # noqa: BLE001 - 预抓拍失败不阻塞提交本身
            pass
        try:
            tm.set_theme_mode(theme_mode)
            try:
                theme = tm.effective_theme()
            except Exception:
                theme = "dark" if tm.is_dark_theme() else "light"
            tm.set_color("accent.primary", accent)

            self._apply_staged_background_to_main_window(staged_bg)

            # 通用页：主界面布局下发（失败仅警告，不阻断整体提交）
            self._apply_staged_layout_mode_to_main_window(layout_mode)

            # 通用页：AI 入口 / 网络盘与光驱 / 空白区右键返回 / 显示隐藏文件 /
            # 显示受保护系统文件 / 全局浮窗 / 贴边吸附下发（失败仅警告，不阻断提交）
            self._apply_staged_general_toggles_to_main_window(
                ai_entry,
                include_remote,
                blank_back,
                show_hidden,
                show_system,
                floating_pool,
                floating_pool_snap,
            )

            # 性能档位应用（仅提交路径调用；顺序：定时器档位 → 进程电源策略
            # → GPU 路由；工作线程钩子在线程入口注册，只影响新建/下轮会话，
            # 不追溯已在跑的线程）。
            # apply_gpu_profile 返回 False（启动器未构建）仅为降级警告，
            # 不视为提交失败；只有抛异常才触发回滚。
            self._apply_staged_perf_profile(perf_profile)

            colors_dict = tm.snapshot_colors()
            colors_dict["accent"]["primary"] = saved_accent

            v2 = SettingsManagerV2()
            v2.load()
            prev_check_updates_on_startup = v2.get(
                "general.check_updates_on_startup", True
            )
            v2.set("appearance.theme_mode", theme_mode)
            v2.set("appearance.theme", theme)
            v2.set("appearance.accent_color", saved_accent)
            v2.set("appearance.colors", colors_dict)
            v2.set("appearance.background", {
                "mode": bg_mode,
                "image": str(staged_bg.get("image", "") or ""),
                "ambient": bool(staged_bg.get("ambient", True)),
                "blur": bg_blur,
                "transparency": bg_transparency,
            })
            v2.set("general.layout_mode", layout_mode)
            v2.set("general.enable_ai_entry", ai_entry)
            v2.set("general.include_remote_drives", include_remote)
            v2.set("general.blank_right_click_go_back", blank_back)
            v2.set("general.show_hidden_files", show_hidden)
            v2.set("general.show_system_files", show_system)
            v2.set("general.floating_pool_enabled", floating_pool)
            v2.set("general.floating_pool_snap_enabled", floating_pool_snap)
            v2.set(
                "general.check_updates_on_startup", check_updates_on_startup
            )
            v2.set("performance.profile", perf_profile)
            v2.save()
        except Exception as exc:
            try:
                tm.set_theme_mode(prev_mode)
                tm.set_theme(prev_theme)
                tm.replace_colors(prev_colors)
            except Exception as rollback_exc:
                debug(f"回滚主题设置失败：{rollback_exc}")
            try:
                _set_timing_active_profile(prev_perf_profile)
            except Exception as rollback_exc:
                debug(f"回滚性能档位失败：{rollback_exc}")
            if (
                v2 is not None
                and prev_check_updates_on_startup is not _unset_value
            ):
                try:
                    v2.set(
                        "general.check_updates_on_startup",
                        prev_check_updates_on_startup,
                    )
                except Exception as rollback_exc:
                    debug(f"回滚启动检查更新设置失败：{rollback_exc}")
            self._notify_save_failure(exc)
            return False

        self._staging_cache.mark_committed(staged)
        self._last_submit_ms = (time.perf_counter() - t0) * 1000.0
        if close_after:
            self._submitted = True
            self._close_host_window()
        return True

    def _notify_save_failure(self, error: Exception) -> None:
        """保存失败提示（非阻塞）：告知用户本次修改已回滚、未写入磁盘。

        写盘失败（数据目录无写入权限、磁盘占用等）此前仅返回 False，
        设置窗口不关闭但毫无提示；此处统一弹出 danger 提示，正文附带
        失败原因与排查提示。弹窗自身失败只记日志，不影响回滚结果。

        Args:
            error: 触发提交失败的异常（取字符串作为失败原因）。
        """
        try:
            detail = str(error) or type(error).__name__
            create_danger_dialog(
                title="保存失败",
                message=(
                    "设置保存失败，本次修改已回滚，未写入磁盘。\n\n"
                    f"原因：{detail}\n\n"
                    "请检查程序数据目录是否可写，或稍后重试。"
                ),
                cancel_text="",
                confirm_text="知道了",
            )
        except Exception as exc:  # noqa: BLE001 - 提示失败不影响提交回滚结果
            debug(f"保存失败提示弹窗显示失败：{exc}")

    def _apply_staged_background_to_main_window(self, staged_bg: dict) -> None:
        """将暂存背景应用到主窗口（仅提交路径调用）。

        Args:
            staged_bg: 暂存的 ``appearance.background`` 字典。
        """
        mode = staged_bg.get("mode", "mica")
        if mode not in ("mica", "image", "minimalist"):
            mode = "mica"
        image_name = str(staged_bg.get("image", "") or "")
        ambient = staged_bg.get("ambient", True)
        ambient = ambient if isinstance(ambient, bool) else bool(ambient)
        bg_blur = _normalize_bg_blur(
            staged_bg.get("blur", IMAGE_BG_BLUR_DEFAULT)
        )
        bg_transparency = _normalize_bg_transparency(
            staged_bg.get("transparency", IMAGE_BG_TRANSPARENCY_DEFAULT)
        )
        # 背景图片身份 = (文件名, 导入修订号)。单槽位同名覆盖时文件名恒定，
        # 必须并入修订号才能识别"再次选图内容已更换"（否则整段被跳过）。
        try:
            image_rev = int(self._appearance_page.background_image_revision())
        except Exception:  # noqa: BLE001 - 取修订号失败按无变化处理
            image_rev = 0
        # 与上次已下发状态完全一致 → 整段跳过（主题切换、色板/其它改动
        # 引发的重复预览不再触碰背景层）。
        state = (
            mode,
            (image_name, image_rev) if mode == "image" else "",
            ambient,
            bg_blur,
            bg_transparency,
        )
        if state == self._last_applied_bg_state:
            return
        try:
            mw = self._appearance_page.find_main_window()
            if mw is None:
                return
            if mode == "image" and image_name:
                image_path = os.path.join(
                    get_app_data_path(), BACKGROUND_DIR_NAME, image_name
                )
                # 图片只在切换/更换时下发一次；滑块拖动预览（同一图片）仅更新
                # 参数，避免每帧重载图片造成卡顿与闪烁。同名覆盖的新图片靠
                # 修订号变化识别，仍会重新下发并触发交叉淡入。
                if (image_name, image_rev) != (
                    self._last_applied_bg_image,
                    self._last_applied_bg_rev,
                ):
                    if hasattr(mw, "set_custom_background_image"):
                        mw.set_custom_background_image(image_path)
                    self._last_applied_bg_image = image_name
                    self._last_applied_bg_rev = image_rev
                if hasattr(mw, "set_image_background_params"):
                    # 透明度换算为不透明度后下发给图像层。
                    mw.set_image_background_params(
                        bg_blur, 1.0 - bg_transparency / 100.0
                    )
                if hasattr(mw, "set_background_mode"):
                    mw.set_background_mode("image")
            elif mode == "minimalist":
                self._last_applied_bg_image = ""
                self._last_applied_bg_rev = -1
                if hasattr(mw, "set_ambient_enabled"):
                    mw.set_ambient_enabled(ambient)
                if hasattr(mw, "set_background_mode"):
                    mw.set_background_mode("minimalist")
            else:
                self._last_applied_bg_image = ""
                self._last_applied_bg_rev = -1
                if hasattr(mw, "set_background_mode"):
                    mw.set_background_mode("mica")
            self._last_applied_bg_state = state
        except Exception as exc:
            debug(f"下发背景模式到主窗口失败：{exc}")

    @staticmethod
    def _layout_mode_will_change(main_window: QWidget, layout_mode: str) -> bool:
        """本次提交是否真正改变主窗口布局模式（供过渡方式选择）。

        ``get_layout_mode`` 缺失（测试替身/旧接口）或取值异常时按「不变化」
        处理，过渡退回主题链路——布局相同再重挂载是 no-op，不应更换过渡
        类型改变观感。

        Args:
            main_window: 主窗口（或具备同名契约的实现）。
            layout_mode: 本次提交的目标布局模式。

        Returns:
            bool: True 表示布局将发生变化。
        """
        getter = getattr(main_window, "get_layout_mode", None)
        if getter is None:
            return False
        try:
            return getter() != layout_mode
        except Exception:  # noqa: BLE001 - 取值失败按无变化处理
            return False

    def _apply_staged_layout_mode_to_main_window(self, layout_mode: str) -> None:
        """将暂存的界面布局模式应用到主窗口（仅提交路径调用）。

        布局切换属即时重组（叶子组件重新挂载、不销毁），失败时记录 warning
        并保留旧布局——不视为提交失败，其余设置照常生效。

        Args:
            layout_mode: 目标布局模式（"classic" 或 "workspace"，调用方已校验）。
        """
        try:
            mw = self._appearance_page.find_main_window()
            if mw is None:
                return
            setter = getattr(mw, "set_layout_mode", None)
            if setter is None:
                return
            setter(layout_mode)
        except Exception as exc:  # noqa: BLE001 - 布局切换失败不阻断提交
            from freeassetfilter.utils.app_logger import warning

            warning(f"界面布局切换失败（{layout_mode}）: {exc}")

    def _apply_staged_general_toggles_to_main_window(
        self,
        ai_entry: bool,
        include_remote: bool,
        blank_back: bool,
        show_hidden_files: bool,
        show_system_files: bool,
        floating_pool: bool,
        floating_pool_snap: bool,
    ) -> None:
        """将暂存的通用页开关应用到主窗口（仅提交路径调用）。

        七个开关均为即时项：AI 入口控制预览器工具栏按钮与抽屉，
        网络盘/光驱控制文件选择器「All」视图的盘符过滤，空白区右键
        返回控制文件选择器空白位右键的返回上级行为，显示隐藏文件与
        显示受保护系统文件控制文件选择器的可见性过滤，全局浮窗控制
        桌面浮窗的存在（``set_floating_pool_enabled`` 建/拆窗），贴边
        吸附控制浮窗拖动靠边时的自动吸附（``set_floating_pool_snap_enabled``）。
        失败仅记录 warning，不阻断整体提交。

        Args:
            ai_entry: 是否启用 AI 入口。
            include_remote: 是否包含网络/映射盘与光驱。
            blank_back: 是否启用空白区右键返回上一级。
            show_hidden_files: 是否显示带「隐藏」属性的文件/文件夹。
            show_system_files: 是否额外显示受保护系统文件/文件夹。
            floating_pool: 是否启用全局存储池浮窗。
            floating_pool_snap: 是否启用浮窗贴边吸附。
        """
        try:
            mw = self._appearance_page.find_main_window()
            if mw is None:
                return
            ai_setter = getattr(mw, "set_ai_entry_enabled", None)
            if ai_setter is not None:
                ai_setter(ai_entry)
            drives_setter = getattr(mw, "set_include_remote_drives", None)
            if drives_setter is not None:
                drives_setter(include_remote)
            blank_back_setter = getattr(mw, "set_blank_right_click_go_back", None)
            if blank_back_setter is not None:
                blank_back_setter(blank_back)
            hidden_setter = getattr(mw, "set_show_hidden_files", None)
            if hidden_setter is not None:
                hidden_setter(show_hidden_files)
            system_setter = getattr(mw, "set_show_system_files", None)
            if system_setter is not None:
                system_setter(show_system_files)
            floating_pool_setter = getattr(mw, "set_floating_pool_enabled", None)
            if floating_pool_setter is not None:
                floating_pool_setter(floating_pool)
            floating_pool_snap_setter = getattr(
                mw, "set_floating_pool_snap_enabled", None
            )
            if floating_pool_snap_setter is not None:
                floating_pool_snap_setter(floating_pool_snap)
        except Exception as exc:  # noqa: BLE001 - 开关下发失败不阻断提交
            from freeassetfilter.utils.app_logger import warning

            warning(
                "通用功能开关下发失败"
                f"（AI={ai_entry}, 远程盘={include_remote}, 空白右键返回={blank_back},"
                f" 隐藏文件={show_hidden_files}, 系统文件={show_system_files},"
                f" 全局浮窗={floating_pool}, 贴边吸附={floating_pool_snap}）: {exc}"
            )

    def _apply_staged_perf_profile(self, profile: str) -> None:
        """将暂存性能档位应用到三钩子（仅提交路径调用）。

        顺序：定时器档位（``platform_timing.set_active_profile``，内存态，
        永不抛异常）→ 进程电源策略（``platform_threads
        .apply_process_power_policy``）→ GPU 路由（``platform_gpu
        .apply_gpu_profile``）。调用方（:meth:`_submit_settings`）负责
        try/except 回滚；``apply_gpu_profile`` 返回 False（启动器未构建）
        仅为降级警告，不抛异常、不视为失败。

        语义注意：工作线程钩子（MMCSS/钉核）在线程入口注册，只影响
        新建/下轮工作线程会话，不追溯已在跑的线程。

        Args:
            profile: 已校验的档位值，"performance" | "balanced" |
                "powersave"。

        Raises:
            Exception: 任一钩子抛异常时向上传播，触发提交回滚。
        """
        from freeassetfilter.utils.app_logger import debug, warning

        _set_timing_active_profile(profile)
        try:
            power_ok = apply_process_power_policy(profile)  # type: ignore[arg-type]
        except Exception:
            raise
        if not power_ok:
            warning(f"性能档位 {profile}：进程电源策略未生效（权限或平台限制）")
        try:
            gpu_ok = apply_gpu_profile(profile)
        except Exception:
            raise
        if not gpu_ok:
            warning(
                f"性能档位 {profile}：GPU 启动器不可用，直启回退 "
                f"（run launcher/build_launcher.ps1 构建）"
            )
        debug(f"性能档位已应用: {profile}")

    def _close_host_window(self) -> None:
        """关闭宿主设置窗口（确定/取消路径）。"""
        host = self._host_window if self._host_window is not None else self.window()
        try:
            if host is not None and hasattr(host, "close"):
                host.close()
        except Exception as exc:
            debug(f"关闭设置宿主窗口失败：{exc}")

    def on_host_closing(self) -> None:
        """宿主窗口关闭生命周期：落盘外观三项，其余未保存改动静默丢弃。

        由 ``SettingsWindow.closeEvent`` 调用（右上角 ✕ 与主窗口退出连带关闭
        均走此路径）：

        - 外观三项（深色模式 / 主题色 / 窗口背景）在改动时已实时预览生效，
          此处仅补磁盘写入（``_persist_appearance_only``），满足「点 ✕ 也保存
          外观设置」；
        - 非外观项（通用页开关、性能档位）从未实时生效，只能经「保存」按钮
          提交，关闭时静默丢弃、不落盘；
        - 未提交时清空暂存缓存，保证下次打开为原始状态。
        """
        if self._submitted:
            return
        # 关闭前补发挂起的外观预览：外观项「点 ✕ 也保存」，运行态必须
        # 与即将写入磁盘的暂存值一致（否则重启后与本次会话不符）。
        self._flush_appearance_preview()
        try:
            dirty = set(self._staging_cache.dirty_keys())
        except Exception:
            dirty = set()
        if dirty & self._AUTO_SAVE_APPEARANCE_KEYS:
            try:
                self._persist_appearance_only()
            except Exception as exc:  # noqa: BLE001 - 落盘失败仅告警
                warning(f"关闭时保存外观设置失败（重启后可能回退）：{exc}")
        if dirty:
            self._staging_cache.discard()
            try:
                self._appearance_page.refresh_from_staging()
                self._general_page.refresh_from_staging()
            except Exception as exc:
                debug(f"关闭钩子刷新页面失败：{exc}")

    def get_cache_debug_info(self) -> dict:
        """返回暂存缓存调试摘要（含最近提交耗时）。

        Returns:
            dict: 调试信息字典。
        """
        info = self._staging_cache.debug_info()
        info["last_submit_ms"] = round(self._last_submit_ms, 3)
        info["submitted"] = self._submitted
        return info

    def refresh_theme(self) -> None:
        """公共方法：强制刷新当前主题下的所有样式"""
        self._refresh_styles()
        # 侧边栏导航项与折叠按钮样式由组件自身刷新（审查 3.1#23）
        self._sidebar.refresh_visuals()
