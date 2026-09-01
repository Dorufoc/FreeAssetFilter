"""
Custom Image Background Widget

以用户自选图片作为窗口背景层：
1. cover 等比覆盖算法（完全覆盖窗口、居中裁切、严禁拉伸变形）
2. 交互期快速缩放 + 稳定后平滑缓存的绘制策略（与 Mica 一致）
3. 固定单槽位持久化导入（复制到 data/backgrounds/ 下）

与 Mica 的核心差异：几何计算只与窗口尺寸相关，与窗口屏幕位置完全无关——
图像固定于窗口客户区，不随窗口移动而偏移或重新裁切。
"""

from __future__ import annotations

import math
import os
import shutil
from pathlib import Path
from typing import Optional, Tuple

from PySide6.QtCore import QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPaintEvent, QPainter, QPixmap, QResizeEvent
from PySide6.QtWidgets import QWidget

from theme import tm
from freeassetfilter.utils.app_logger import warning
from freeassetfilter.utils.path_utils import get_app_data_path

# ---------------------------------------------------------------------------
# 模块常量
# ---------------------------------------------------------------------------

# 允许导入的背景图片扩展名白名单（小写比较）。
BACKGROUND_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"})
# get_app_data_path() 下的持久化子目录名。
BACKGROUND_DIR_NAME = "backgrounds"
# 固定单槽位文件名前缀（同名覆盖，保证同一时刻仅存在一张背景图）。
BACKGROUND_FILENAME_PREFIX = "custom_background"
# 交互停止后重建平滑缓存的延时（毫秒）。
SETTLE_INTERVAL_MS = 80


# ---------------------------------------------------------------------------
# 纯函数：cover 等比覆盖几何
# ---------------------------------------------------------------------------

def compute_cover_geometry(img_w: int, img_h: int, win_w: int, win_h: int) -> Tuple[int, int, int, int]:
    """计算图片以 cover 方式铺满窗口的目标矩形 (x, y, w, h)。

    cover 等比覆盖算法：scale = max(win_w / img_w, win_h / img_h)，即完全
    覆盖窗口的最小等比缩放（严禁拉伸）。尺寸向上取整（ceil）保证舍入后
    仍完全覆盖、无 1px 空隙；负偏移表示溢出，由窗口边界自然裁切。

    几何与窗口屏幕位置完全无关——这是与 Mica 按屏幕位置裁切的核心差异：
    图像固定于窗口客户区，窗口移动不会改变绘制结果。对方形图像而言，
    本算法等价于「缩放后图像最短边 = 窗口最长边」。

    Args:
        img_w: 源图像宽度（像素）。
        img_h: 源图像高度（像素）。
        win_w: 窗口客户区宽度（像素）。
        win_h: 窗口客户区高度（像素）。

    Returns:
        Tuple[int, int, int, int]: 目标矩形 (x, y, w, h)。任一输入 <= 0 时
        返回 (0, 0, max(0, win_w), max(0, win_h)) 作为守卫兜底。
    """
    if img_w <= 0 or img_h <= 0 or win_w <= 0 or win_h <= 0:
        return (0, 0, max(0, win_w), max(0, win_h))

    scale = max(win_w / img_w, win_h / img_h)
    w = math.ceil(img_w * scale)
    h = math.ceil(img_h * scale)
    x = (win_w - w) // 2
    y = (win_h - h) // 2
    return (x, y, w, h)


# ---------------------------------------------------------------------------
# 背景组件
# ---------------------------------------------------------------------------

class CustomImageBackgroundWidget(QWidget):
    """自定义图片背景层。

    以 cover 等比覆盖方式将一张图片绘制为窗口背景。作为独立背景层控件
    使用：鼠标事件穿透（不干扰窗口边缘拖拽缩放）、始终铺满不透明绘制。
    交互期（窗口拖拽/缩放期间）走快速缩放路径保证流畅；交互停止
    SETTLE_INTERVAL_MS 毫秒后重建平滑缩放缓存。

    与 Mica 的关键差异：图像固定于窗口客户区，与窗口屏幕位置无关
    （handle_window_move 为空操作）；无图时以主题纯色兜底。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """初始化背景层。

        Args:
            parent: 父控件（通常为主窗口的内容层容器）。
        """
        super().__init__(parent)

        self._image_path: str = ""
        self._source_pixmap: Optional[QPixmap] = None
        # settle 之后按当前窗口尺寸平滑缩放的缓存（交互期清空）。
        self._cached_pixmap: Optional[QPixmap] = None
        self._interacting: bool = False

        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setInterval(SETTLE_INTERVAL_MS)
        self._settle_timer.timeout.connect(self._on_settle)

        # 背景层鼠标穿透，避免干扰窗口边缘拖拽缩放。
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        # 始终铺满不透明绘制。
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_image(self, path: str) -> bool:
        """加载并设置背景图片。

        Args:
            path: 图片文件绝对路径。

        Returns:
            bool: 加载成功返回 True；路径为空、文件不存在或图片无法
            解码时记录 warning 日志、清空现有图像并返回 False。
        """
        if not path or not Path(path).exists():
            warning(f"背景图片路径无效或文件不存在: {path!r}")
            self._clear_image_state()
            return False

        img = QImage(path)
        if img.isNull() or img.width() <= 0 or img.height() <= 0:
            warning(f"背景图片无法解码或尺寸非法: {path!r}")
            self._clear_image_state()
            return False

        self._image_path = path
        self._source_pixmap = QPixmap.fromImage(img)
        self._cached_pixmap = None
        self.update()
        return True

    def clear_image(self) -> None:
        """清空背景图片，恢复主题纯色兜底绘制。"""
        self._clear_image_state()
        self.update()

    def has_image(self) -> bool:
        """判断当前是否持有有效背景图片。

        Returns:
            bool: 源 pixmap 存在且非 null 时返回 True。
        """
        return self._source_pixmap is not None and not self._source_pixmap.isNull()

    @property
    def image_path(self) -> str:
        """当前背景图片的源路径（未设置时为空字符串）。"""
        return self._image_path

    def handle_window_resize(self) -> None:
        """窗口尺寸变化入口（由 MainWindow 的 resizeEvent 转发）。

        进入交互态：清空平滑缓存、重启 settle 定时器并重绘，
        交互期间走快速缩放路径保证拖拽流畅。
        """
        self._interacting = True
        self._cached_pixmap = None
        self._settle_timer.start()  # 每次事件都重启
        self.update()

    def handle_window_move(self) -> None:
        """窗口移动入口（由 MainWindow 的 moveEvent 转发）。

        空操作（no-op）：图像固定于窗口客户区、不随窗口屏幕位置偏移或
        重新裁切——这是与 Mica 按屏幕位置裁切行为的关键差异。保留该
        接口使 MainWindow 可用与 Mica 相同的转发模式接入。
        """

    def sync_theme(self) -> None:
        """主题切换同步入口。

        兜底色在绘制期动态读取（见 _fallback_color），图片本身与主题
        无关，因此仅需触发一次重绘。
        """
        self.update()

    def refresh_background(self) -> None:
        """按当前路径重新加载背景图片（磁盘内容变化时使用）。"""
        if self._image_path:
            self.set_image(self._image_path)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _clear_image_state(self) -> None:
        """清空路径与两级 pixmap 缓存（不触发重绘）。"""
        self._image_path = ""
        self._source_pixmap = None
        self._cached_pixmap = None

    def _fallback_color(self) -> QColor:
        """主题纯色兜底色（与 Mica 兜底一致，绘制期动态读取）。

        Returns:
            QColor: 深色主题纯黑，浅色主题纯白。
        """
        return QColor("#000000" if tm.is_dark_theme() else "#FFFFFF")

    def _on_settle(self) -> None:
        """交互停止：退出交互态并清缓存，下次 paint 重建平滑缓存。"""
        self._interacting = False
        self._cached_pixmap = None
        self.update()

    # ------------------------------------------------------------------
    # Qt 事件
    # ------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        """绘制背景：无图铺兜底色；有图按 cover 几何绘制。

        交互期关闭 SmoothPixmapTransform 直接 drawPixmap（快速缩放）；
        非交互期命中/重建平滑缩放缓存后整图 blit。

        Args:
            event: Qt 绘制事件。
        """
        painter = QPainter(self)

        if not self.has_image():
            painter.fillRect(self.rect(), self._fallback_color())
            painter.end()
            return

        assert self._source_pixmap is not None  # has_image 已保证
        x, y, w, h = compute_cover_geometry(
            self._source_pixmap.width(),
            self._source_pixmap.height(),
            self.width(),
            self.height(),
        )

        if self._interacting:
            # 快速缩放路径：一次 blit，保证拖拽流畅。
            painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
            painter.drawPixmap(QRect(x, y, w, h), self._source_pixmap)
            painter.end()
            return

        # 平滑路径：缓存缺失或尺寸不匹配时重建。
        # w/h 本身保持原图比例（cover 等比），因此 IgnoreAspectRatio
        # 等效等比缩放。
        if (
            self._cached_pixmap is None
            or self._cached_pixmap.isNull()
            or self._cached_pixmap.size() != QSize(w, h)
        ):
            self._cached_pixmap = self._source_pixmap.scaled(
                QSize(w, h), Qt.IgnoreAspectRatio, Qt.SmoothTransformation
            )
        painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
        painter.drawPixmap(x, y, self._cached_pixmap)
        painter.end()

    def resizeEvent(self, event: QResizeEvent) -> None:
        """自身尺寸变化（布局驱动）同样走交互路径重建缓存。

        Args:
            event: Qt 尺寸事件。
        """
        super().resizeEvent(event)
        self.handle_window_resize()


# ---------------------------------------------------------------------------
# 图片导入（持久化）
# ---------------------------------------------------------------------------

def import_custom_background_image(src_path: str) -> Optional[str]:
    """将外部图片导入为自定义背景（复制到持久化目录，固定单槽位）。

    校验通过后将源文件以 ``custom_background.<ext>`` 为名覆盖复制到
    ``get_app_data_path()/backgrounds/`` 下——同一时刻仅保留一张背景图。

    Args:
        src_path: 源图片文件路径。

    Returns:
        Optional[str]: 导入成功返回目标文件绝对路径；路径不存在、扩展名
        不在白名单或图片无法解码时记录 warning 日志并返回 None
        （不复制、不抛异常）。
    """
    if not src_path or not Path(src_path).exists():
        warning(f"背景图片导入失败：路径无效或文件不存在: {src_path!r}")
        return None

    ext = os.path.splitext(src_path)[1].lower()
    if ext not in BACKGROUND_IMAGE_EXTENSIONS:
        warning(f"背景图片导入失败：不支持的扩展名 {ext!r}（白名单: {sorted(BACKGROUND_IMAGE_EXTENSIONS)}）")
        return None

    img = QImage(src_path)
    if img.isNull() or img.width() <= 0 or img.height() <= 0:
        warning(f"背景图片导入失败：文件无法解码为有效图片: {src_path!r}")
        return None

    dest_dir = os.path.join(get_app_data_path(), BACKGROUND_DIR_NAME)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, BACKGROUND_FILENAME_PREFIX + ext)
    try:
        shutil.copy2(src_path, dest)
    except OSError as exc:
        warning(f"背景图片导入失败：复制文件时出错: {exc}")
        return None
    return dest
