# -*- coding: utf-8 -*-
"""进度组件「强调色单独变化即时换色」回归（容量圆环 + 线性进度条）。

回归背景：``StyledProgress(Circle).COLOR_CONFIG`` 曾在导入期把
``tm.accent/warning/danger`` 的 QColor 快照进类字典，之后切换主题色
（只发 ``colors_updated``）重绘仍取旧色——All 视图的磁盘容量圆环因此
永远不跟随主题色。本文件直接离屏绘制并断言改色后弧线/填充像素立即
使用新强调色。

验证命令：
    python -m pytest tests/unit/ui/components/test_styled_progress_theme.py -q
"""

# targets: ui.components.styled_progress, ui.components.styled_progress_circle

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

# 组件模块内部使用短路径导入（from theme import tm），要求
# freeassetfilter/ui 位于 sys.path；与 test_styled_basic.py 的 bootstrap
# 方式保持一致。
_UI_ROOT: str = str(Path(__file__).resolve().parents[4] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from freeassetfilter.ui.components.styled_progress import (  # noqa: E402
    ProgressTrack,
)
from freeassetfilter.ui.components.styled_progress_circle import (  # noqa: E402
    StyledProgressCircle,
)
from freeassetfilter.ui.theme import tm  # noqa: E402

#: 探针色候选（均与内置默认强调色/相互之间差异足够大，便于像素判定）。
_PROBE_COLORS = ("#FF00AA", "#00AACC", "#FFAA00")

#: 探针色与当前强调色的最小通道距离：低于该值视为无法区分，顺延候选。
_MIN_CHANNEL_DELTA = 24


def _is_far_enough(color: str, other: QColor) -> bool:
    """判断探针色与参考色是否至少有单通道 ``_MIN_CHANNEL_DELTA`` 差距。

    Args:
        color: 候选探针色（十六进制）。
        other: 参考颜色。

    Returns:
        bool: 任一通道差值超过阈值即为 True。
    """
    candidate = QColor(color)
    return max(
        abs(candidate.red() - other.red()),
        abs(candidate.green() - other.green()),
        abs(candidate.blue() - other.blue()),
    ) > _MIN_CHANNEL_DELTA


def _next_probe_color() -> str:
    """返回一个与当前强调色差异足够大的探针色。

    Returns:
        str: 十六进制探针色。
    """
    current = QColor(tm.accent)
    for color in _PROBE_COLORS:
        if _is_far_enough(color, current):
            return color
    return "#123456"


def _count_near_color(pixmap: QPixmap, color: QColor, tolerance: int = 12) -> int:
    """统计与目标色接近的不透明像素数量。

    抗锯齿边缘像素经 alpha<200 门槛排除，仅核心笔迹参与颜色断言。

    Args:
        pixmap: 待扫描位图。
        color: 目标颜色。
        tolerance: 每通道允许的绝对误差。

    Returns:
        int: 命中像素数。
    """
    image = pixmap.toImage()
    count = 0
    for y in range(image.height()):
        for x in range(image.width()):
            pixel = image.pixelColor(x, y)
            if pixel.alpha() < 200:
                continue
            if (
                abs(pixel.red() - color.red()) <= tolerance
                and abs(pixel.green() - color.green()) <= tolerance
                and abs(pixel.blue() - color.blue()) <= tolerance
            ):
                count += 1
    return count


def _render_ring(value: float = 0.5, size: int = 64) -> QPixmap:
    """离屏绘制圆环（关闭百分比文字，避免文字像素干扰取色断言）。

    Args:
        value: 进度值（0~1）。
        size: 画布边长。

    Returns:
        QPixmap: 渲染结果。
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    StyledProgressCircle.paint_progress(
        painter,
        QRectF(0, 0, size, size),
        value,
        "default",
        show_percentage=False,
        size_variant="md",
        fit_to_rect=True,
    )
    painter.end()
    return pixmap


class TestProgressCircleAccentFollow:
    """圆环弧线颜色必须跟随当前强调色（绘制期现取）。"""

    def test_arc_uses_current_accent_after_change(self, qapp: QApplication) -> None:
        """改色后重绘即用新强调色，旧色像素消失。"""
        original = tm.accent.name()
        try:
            # tm 与组件共用同一单例的哨兵断言（短路径导入收敛）。
            assert (
                StyledProgressCircle.variant_color("default").name().lower()
                == tm.accent.name().lower()
            )

            before = _render_ring()
            assert _count_near_color(before, QColor(tm.accent)) > 0, (
                "初始弧线应存在强调色像素"
            )

            probe = _next_probe_color()
            assert tm.set_color("accent.primary", probe) is True

            after = _render_ring()
            assert _count_near_color(after, QColor(probe)) > 0, (
                "改色后弧线应为新强调色（COLOR_CONFIG 是否又冻结了旧色？）"
            )
            assert _count_near_color(after, QColor(original)) == 0, (
                "改色后不应残留旧强调色像素"
            )
        finally:
            tm.set_color("accent.primary", original)

    def test_consecutive_accent_changes_all_apply(self, qapp: QApplication) -> None:
        """连续切换多个主题色，每次都立即生效（回归「第二次卡住」）。"""
        original = tm.accent.name()
        try:
            for probe in _PROBE_COLORS:
                if not _is_far_enough(probe, QColor(tm.accent)):
                    continue
                assert tm.set_color("accent.primary", probe) is True
                ring = _render_ring()
                assert _count_near_color(ring, QColor(probe)) > 0, (
                    f"连续切换中 {probe} 未即时生效"
                )
        finally:
            tm.set_color("accent.primary", original)


class TestProgressTrackAccentFollow:
    """线性进度条填充色必须跟随当前强调色（绘制期现取）。"""

    def test_fill_uses_current_accent_after_change(self, qapp: QApplication) -> None:
        """改色后重绘的填充色即为新强调色。"""
        original = tm.accent.name()
        track = ProgressTrack(value=0.5, track_height=8)
        try:
            track.resize(120, 8)
            probe = _next_probe_color()
            assert tm.set_color("accent.primary", probe) is True

            pixmap = QPixmap(120, 8)
            pixmap.fill(Qt.transparent)
            track.render(pixmap)
            assert _count_near_color(pixmap, QColor(probe)) > 0, (
                "改色后进度条填充应为新强调色"
            )
        finally:
            tm.set_color("accent.primary", original)
            track.deleteLater()
