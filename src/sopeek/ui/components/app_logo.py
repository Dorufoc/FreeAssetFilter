# -*- coding: utf-8 -*-
"""应用 logo 加载（主窗口标题栏 / 设置页「关于」页共用）。

``SPK-main.png`` 为多尺寸品牌图：按逻辑尺寸 × ``devicePixelRatio`` 缩放到
物理像素后回写 DPR，避免高分屏下模糊。资源缺失或加载失败时返回空
``QPixmap``，调用方据此跳过图标显示（标题栏与关于页均有降级路径）。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication


def app_logo_pixmap(size: int) -> QPixmap:
    """加载应用 logo（``SPK-main.png``）并按设备像素比缩放。

    Args:
        size: 逻辑像素边长（正方形目标尺寸）。

    Returns:
        QPixmap: 已按 DPR 缩放并回写 DPR 的 logo；资源缺失时为空 pixmap。
    """
    # 资源路径统一由 sopeek._paths 解析（含冻结态的 _MEIPASS 分支）。
    candidates: list[str] = []
    try:
        from sopeek._paths import icons_dir

        candidates.append(str(icons_dir() / "SPK-main.png"))
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
    scaled = pixmap.scaled(
        target, target, Qt.KeepAspectRatio, Qt.SmoothTransformation
    )
    scaled.setDevicePixelRatio(dpr)
    return scaled
