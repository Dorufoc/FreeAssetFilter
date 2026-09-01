# -*- coding: utf-8 -*-
"""custom_background（自定义窗口背景）单元测试。

覆盖 ui/components/custom_background.py 的三部分：
1. 纯函数 compute_cover_geometry 的 cover 等比覆盖几何（覆盖性、等比性、
   居中对称、零值守卫）；
2. CustomImageBackgroundWidget 的加载/清空/绘制/交互生命周期（离屏 grab，
   不弹真实窗口）；
3. import_custom_background_image 的持久化导入（白名单、解码校验、单槽位
   覆盖；通过 monkeypatch 重定向 data 目录，绝不污染真实 data/）。

验证命令：
    python -m pytest tests/unit/ui/components/test_custom_background.py -v
"""

# targets: ui.components.custom_background

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QColor, QPaintEvent, QPixmap
from PySide6.QtWidgets import QApplication

# 组件模块内部使用短路径导入（from theme import tm），
# 要求 freeassetfilter/ui 位于 sys.path；与 test_styled_complex.py 的
# bootstrap 方式保持一致。
_UI_ROOT: str = str(Path(__file__).resolve().parents[4] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from tests.support.qt_helpers import safe_teardown  # noqa: E402

import freeassetfilter.ui.components.custom_background as custom_background  # noqa: E402
from freeassetfilter.ui.components.custom_background import (  # noqa: E402
    BACKGROUND_FILENAME_PREFIX,
    CustomImageBackgroundWidget,
    compute_cover_geometry,
    import_custom_background_image,
)

pytestmark = pytest.mark.unit


def _make_png(path: Path, width: int = 64, height: int = 32, color: str = "#336699") -> Path:
    """生成一张纯色 PNG 测试图片并返回其路径。

    Args:
        path: 目标文件路径（含 .png 扩展名）。
        width: 图像宽度（像素）。
        height: 图像高度（像素）。
        color: 填充色（十六进制字符串）。

    Returns:
        Path: 写入后的文件路径。
    """
    pm = QPixmap(width, height)
    pm.fill(QColor(color))
    assert pm.save(str(path), "PNG")
    return path


# =============================================================================
# 纯函数 compute_cover_geometry
# =============================================================================
class TestComputeCoverGeometry:
    """compute_cover_geometry：cover 等比覆盖几何。"""

    def test_exact_fit_same_ratio(self) -> None:
        """同比例图片精确贴合窗口：零裁切零空白。"""
        assert compute_cover_geometry(1920, 1080, 1920, 1080) == (0, 0, 1920, 1080)

    def test_same_ratio_upscale(self) -> None:
        """1280x720 图铺 1920x1080 窗：等比放大后精确贴合。"""
        assert compute_cover_geometry(1280, 720, 1920, 1080) == (0, 0, 1920, 1080)

    def test_square_image_landscape_window(self) -> None:
        """方形图铺横窗：最短边等于窗口最长边，垂直方向对称溢出。"""
        x, y, w, h = compute_cover_geometry(1000, 1000, 1920, 1080)
        assert (x, y, w, h) == (0, -420, 1920, 1920)
        # 缩放后图像最短边(1920) == 窗口最长边(1920)
        assert min(w, h) == max(1920, 1080)
        # 垂直方向居中：上下溢出对称
        assert -y == (y + h) - 1080

    def test_portrait_image_landscape_window(self) -> None:
        """竖图铺横窗：完全覆盖 + 等比（交叉相乘避免浮点误差）。"""
        img_w, img_h = 1000, 2000
        x, y, w, h = compute_cover_geometry(img_w, img_h, 1920, 1080)
        # 完全覆盖
        assert x <= 0
        assert y <= 0
        assert x + w >= 1920
        assert y + h >= 1080
        # 等比：w * img_h == h * img_w（交叉相乘）
        assert w * img_h == h * img_w

    def test_landscape_image_portrait_window(self) -> None:
        """横图铺竖窗：覆盖 + 等比 + 水平居中（左右溢出对称，差值 <= 1）。"""
        img_w, img_h = 2000, 1000
        x, y, w, h = compute_cover_geometry(img_w, img_h, 800, 1200)
        # 完全覆盖
        assert x <= 0
        assert y <= 0
        assert x + w >= 800
        assert y + h >= 1200
        # 等比：交叉相乘
        assert w * img_h == h * img_w
        # 居中：左侧偏移与右侧溢出对称（整除截断允许差 1）
        left_overhang = -x
        right_overhang = (x + w) - 800
        assert abs(left_overhang - right_overhang) <= 1

    def test_zero_guard(self) -> None:
        """零/负值守卫：返回 (0, 0, max(0, win_w), max(0, win_h))。"""
        assert compute_cover_geometry(0, 0, 100, 100) == (0, 0, 100, 100)
        assert compute_cover_geometry(100, 0, 100, 100) == (0, 0, 100, 100)
        assert compute_cover_geometry(0, 100, 100, 100) == (0, 0, 100, 100)
        assert compute_cover_geometry(100, 100, 0, 100) == (0, 0, 0, 100)
        assert compute_cover_geometry(100, 100, 100, 0) == (0, 0, 100, 0)
        assert compute_cover_geometry(100, 100, 0, 0) == (0, 0, 0, 0)


# =============================================================================
# CustomImageBackgroundWidget
# =============================================================================
class TestCustomImageBackgroundWidget:
    """CustomImageBackgroundWidget：加载、绘制与交互生命周期。"""

    def test_set_image_success(self, qapp: QApplication, tmp_path: Path) -> None:
        """合法 PNG 加载成功：set_image 返回 True、has_image/image_path 正确。"""
        png = _make_png(tmp_path / "bg.png")
        widget = CustomImageBackgroundWidget()
        assert widget.set_image(str(png)) is True
        assert widget.has_image() is True
        assert widget.image_path == str(png)
        safe_teardown(widget)

    def test_grab_after_resize(self, qapp: QApplication, tmp_path: Path) -> None:
        """resize 后 grab 非 null 且逻辑尺寸正确：绘制路径不崩溃。

        grab() 返回物理像素尺寸（含 devicePixelRatio），需除以 DPR 后
        与控件逻辑尺寸比较，兼容高 DPI 缩放环境。
        """
        png = _make_png(tmp_path / "bg.png")
        widget = CustomImageBackgroundWidget()
        assert widget.set_image(str(png)) is True
        widget.resize(200, 100)
        grabbed = widget.grab()
        assert grabbed.isNull() is False
        dpr = grabbed.devicePixelRatio() or 1.0
        logical = QSize(round(grabbed.width() / dpr), round(grabbed.height() / dpr))
        assert logical == QSize(200, 100)
        safe_teardown(widget)

    def test_set_image_missing_path(self, qapp: QApplication, tmp_path: Path) -> None:
        """不存在的路径：set_image 返回 False、grab 仍可用（兜底色路径）。"""
        widget = CustomImageBackgroundWidget()
        missing = str(tmp_path / "missing.png")
        assert widget.set_image(missing) is False
        assert widget.has_image() is False
        grabbed = widget.grab()
        assert grabbed.isNull() is False
        safe_teardown(widget)

    def test_set_image_corrupt_file(self, qapp: QApplication, tmp_path: Path) -> None:
        """垃圾字节的 .png：set_image 返回 False。"""
        corrupt = tmp_path / "corrupt.png"
        corrupt.write_bytes(b"\x00\x01\x02 not a real png \xff\xff")
        widget = CustomImageBackgroundWidget()
        assert widget.set_image(str(corrupt)) is False
        assert widget.has_image() is False
        safe_teardown(widget)

    def test_clear_image(self, qapp: QApplication, tmp_path: Path) -> None:
        """clear_image 后 has_image 为 False、路径清空。"""
        png = _make_png(tmp_path / "bg.png")
        widget = CustomImageBackgroundWidget()
        assert widget.set_image(str(png)) is True
        widget.clear_image()
        assert widget.has_image() is False
        assert widget.image_path == ""
        safe_teardown(widget)

    def test_interaction_and_lifecycle_calls(self, qapp: QApplication, tmp_path: Path) -> None:
        """handle_window_resize/move、sync_theme、refresh_background 调用不崩溃。"""
        png = _make_png(tmp_path / "bg.png")
        widget = CustomImageBackgroundWidget()
        assert widget.set_image(str(png)) is True

        widget.handle_window_resize()
        assert widget._interacting is True
        widget.handle_window_move()
        widget.sync_theme()
        widget.refresh_background()
        assert widget.has_image() is True

        # 模拟 settle 定时器触发
        widget._on_settle()
        assert widget._interacting is False

        # 无图状态下同样调用不崩溃
        widget.clear_image()
        widget.handle_window_resize()
        widget.handle_window_move()
        widget.sync_theme()
        widget.refresh_background()
        grabbed = widget.grab()
        assert grabbed.isNull() is False
        safe_teardown(widget)

    def test_paint_rebuilds_smooth_cache(self, qapp: QApplication, tmp_path: Path) -> None:
        """非交互期 paint 后建立平滑缩放缓存（直接驱动 paintEvent）。

        grab() 对未 show() 的控件每次都会在 native 创建阶段补发初始
        resizeEvent（oldSize 无效），使控件重新进入交互态而走快速路径；
        因此这里直接构造 QPaintEvent 驱动 paintEvent 验证平滑缓存分支。
        """
        png = _make_png(tmp_path / "bg.png", width=64, height=32)
        widget = CustomImageBackgroundWidget()
        assert widget.set_image(str(png)) is True
        widget.resize(200, 100)
        assert widget._interacting is False  # 未触发 resizeEvent，处于稳定态
        event = QPaintEvent(QRect(0, 0, 200, 100))
        widget.paintEvent(event)
        cached = widget._cached_pixmap
        assert cached is not None
        assert not cached.isNull()
        # 64x32 图铺 200x100 窗：cover 等比缩放后缓存尺寸应为 (200, 100)
        assert cached.size() == QSize(200, 100)
        safe_teardown(widget)


# =============================================================================
# import_custom_background_image
# =============================================================================
class TestImportCustomBackgroundImage:
    """import_custom_background_image：持久化导入（隔离到 tmp_path）。"""

    @pytest.fixture(autouse=True)
    def _redirect_data_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """将持久化目录重定向到 tmp_path，绝不污染真实 data/ 目录。"""
        monkeypatch.setattr(custom_background, "get_app_data_path", lambda: str(tmp_path))

    def test_import_valid_png(self, tmp_path: Path) -> None:
        """合法 PNG：返回路径存在、命名符合单槽位约定、字节与源一致。"""
        src = _make_png(tmp_path / "src.png", color="#336699")
        result = import_custom_background_image(str(src))
        assert result is not None
        result_path = Path(result)
        assert result_path.exists()
        # 目录位于重定向后的 data 根下
        assert result_path.parent == tmp_path / "backgrounds"
        # 命名约定：custom_background 前缀 + .png 后缀
        assert result_path.name.startswith(BACKGROUND_FILENAME_PREFIX)
        assert result_path.name.endswith(".png")
        # 字节与源文件一致（copy2 完整复制）
        assert result_path.read_bytes() == src.read_bytes()

    def test_import_rejects_invalid_extension(self, tmp_path: Path) -> None:
        """非白名单扩展名 .txt：返回 None 且目标目录无新文件。"""
        txt = tmp_path / "note.txt"
        txt.write_text("not an image", encoding="utf-8")
        result = import_custom_background_image(str(txt))
        assert result is None
        dest_dir = tmp_path / "backgrounds"
        assert not dest_dir.exists() or not any(dest_dir.iterdir())

    def test_import_rejects_corrupt_png(self, tmp_path: Path) -> None:
        """垃圾字节的 .png：返回 None。"""
        corrupt = tmp_path / "corrupt.png"
        corrupt.write_bytes(b"\x00\x01\x02 not a real png \xff\xff")
        result = import_custom_background_image(str(corrupt))
        assert result is None

    def test_import_rejects_missing_file(self, tmp_path: Path) -> None:
        """不存在的文件：返回 None。"""
        result = import_custom_background_image(str(tmp_path / "missing.png"))
        assert result is None

    def test_import_overwrites_single_slot(self, tmp_path: Path) -> None:
        """单槽位覆盖：两次导入后目标字节与第二个源一致。"""
        src1 = _make_png(tmp_path / "first.png", color="#112233")
        src2 = _make_png(tmp_path / "second.png", color="#445566")
        assert src1.read_bytes() != src2.read_bytes()

        result1 = import_custom_background_image(str(src1))
        assert result1 is not None
        result2 = import_custom_background_image(str(src2))
        assert result2 is not None

        result_path = Path(result2)
        assert result_path.exists()
        # 同扩展名 → 同一目标文件（单槽位）
        assert result1 == result2
        # 字节与第二个源一致（覆盖生效）
        assert result_path.read_bytes() == src2.read_bytes()
