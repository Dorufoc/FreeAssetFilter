# -*- coding: utf-8 -*-
"""屏幕可用工作区解析 —— 扣除任务栏占位后的真实可摆放区域。

背景（Windows 实测缺陷）
-----------------------
``QScreen.availableGeometry()`` 在任务栏停靠**左侧 / 上侧**时不可直接用于
窗口边界钳制：它把任务栏的占用厚度按**物理像素**直接叠加到逻辑坐标上，
而宽 / 高却做了 DPI 缩放，于是返回矩形的右缘 / 下缘会落到屏幕真实右缘 /
下缘之外（实测 2560x1600 @150%、任务栏在左 72px）::

    screen.geometry()          = QRect(0, 0, 1707, 1067)
    screen.availableGeometry() = QRect(72, 0, 1659, 1067)   # 72 未除以 1.5
                                # 右缘 1731 > 1707 → 溢出屏幕 24px

任务栏停靠在下侧时，左 / 上内缩量恰好为 0，缺陷不会显现——这也是它长期
潜伏的原因。直接拿 ``availableGeometry().right()`` 推导坐标的浮动窗口会
被摆到屏幕外（实测原生 ``GetWindowRect`` 右缘 2571 > 2560）。

本模块的处理
------------
Qt 报出的**尺寸**（宽 / 高）是 DPI 正确的，只有左上角偏移量可能夹带未缩放
的物理像素。因此「总内缩量 = 屏幕尺寸 - 可用尺寸」可信，只需按 Qt 报出的
偏移方向把总内缩量分派到正确的边，再与 ``geometry`` 求交兜底。这样无论 Qt
哪个版本、任务栏停靠在哪一侧，得到的矩形都落在物理屏幕内：

* 任务栏在左：``available.left()`` 右移 → 总水平内缩归左缘（48px）；
* 任务栏在右：``available.left()`` 不变 → 总水平内缩归右缘；
* 任务栏在下：上 / 左内缩量均为 0，结果与 Qt 原生值等价（行为不变）。

模块只依赖 ``QRect``，不含 ctypes / 平台分支，可安全在任意平台导入。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRect
from PySide6.QtGui import QScreen


def derive_work_area(geometry: QRect, available: QRect) -> QRect:
    """由 Qt 的 ``geometry`` / ``availableGeometry`` 推导真实可用工作区（纯函数）。

    算法见模块文档：总内缩量由「屏幕尺寸 - 可用尺寸」取得（该差值已按 DPI
    正确缩放），并按 ``available`` 左上角相对 ``geometry`` 的正偏移判定内缩
    归属哪条边，最后与 ``geometry`` 求交，保证结果永不越出物理显示范围。

    Args:
        geometry: 屏幕物理显示区（``QScreen.geometry()``，逻辑像素）。
        available: Qt 报告的可用区（``QScreen.availableGeometry()``，逻辑像素）。

    Returns:
        QRect: 落在 ``geometry`` 内的真实工作区；任一输入无效时返回
        ``geometry``（可用区缺失即视为无任务栏占位）。
    """
    if not geometry.isValid():
        return geometry
    if not available.isValid():
        return geometry

    width = geometry.width()
    height = geometry.height()

    # 总内缩量（已按 DPI 缩放）；上限钳到「至少留 1px」防异常值把区域吃掉。
    horizontal = min(max(0, width - available.width()), width - 1)
    vertical = min(max(0, height - available.height()), height - 1)

    # 左上角有正偏移的那一侧即被任务栏占用的边，其余内缩量归对边。
    left = horizontal if available.left() > geometry.left() else 0
    top = vertical if available.top() > geometry.top() else 0

    work = QRect(
        geometry.x() + left,
        geometry.y() + top,
        width - horizontal,
        height - vertical,
    )
    return work.intersected(geometry)


def screen_work_area(screen: Optional[QScreen]) -> QRect:
    """返回屏幕的真实可用工作区（逻辑像素，已扣除任务栏占位）。

    Args:
        screen: 目标屏幕；``None`` 时返回无效矩形（调用方按"无屏幕"处理）。

    Returns:
        QRect: 可用工作区；``screen`` 为 ``None`` 时返回 ``QRect()``。
    """
    if screen is None:
        return QRect()
    return derive_work_area(screen.geometry(), screen.availableGeometry())
