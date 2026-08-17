# -*- coding: utf-8 -*-
"""styled 流体背景与文件列表组件单元测试（todo-22 批 2 / task-22 续）。

覆盖 ui/components 下 7 个模块：纯函数流体数学、CPU 渲染器、GPU shader
源码常量、StyledFluidBackground 复合组件，以及 AnimatedFileListView /
FileListModel / FileCardDelegate 文件列表三件套。约束与 test_styled_complex
一致：全部离屏、显式依赖 session qapp、只断言源码与离屏探针确认过的
API surface；GPU 相关深层行为用 shader 源码常量断言而非真实 OpenGL 上下文。

验证命令：
    python -m pytest tests/unit/ui/ -k "test_styled_fluid" --timeout 30 -q
"""

# targets: ui.components._styled_fluid_math, ui.components._styled_fluid_cpu,
#          ui.components._styled_fluid_gpu, ui.components.styled_fluid_background,
#          ui.components.animated_file_list_view, ui.components.file_list_model,
#          ui.components.file_card_delegate

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QModelIndex, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QListView, QWidget

# 组件模块内部使用短路径导入（from theme import tm / components.*），
# 要求 freeassetfilter/ui 位于 sys.path；与 test_styled_basic.py 一致。
_UI_ROOT: str = str(Path(__file__).resolve().parents[4] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from tests.support.qt_helpers import assert_pixmap_nonempty, safe_teardown  # noqa: E402

import freeassetfilter.ui.components._styled_fluid_cpu as _fluid_cpu  # noqa: E402
import freeassetfilter.ui.components._styled_fluid_gpu as _fluid_gpu  # noqa: E402
import freeassetfilter.ui.components._styled_fluid_math as _fluid_math  # noqa: E402
from freeassetfilter.ui.components.animated_file_list_view import (  # noqa: E402
    AnimatedFileListView,
)
from freeassetfilter.ui.components.file_card_delegate import FileCardDelegate  # noqa: E402
from freeassetfilter.ui.components.file_list_model import (  # noqa: E402
    FileListModel,
    FileNameRole,
    FilePathRole,
    IsDirRole,
)
from freeassetfilter.ui.components.styled_fluid_background import (  # noqa: E402
    StyledFluidBackground,
)

pytestmark = pytest.mark.unit


# =============================================================================
# ui.components._styled_fluid_math
# =============================================================================
class TestFluidMath:
    """_styled_fluid_math：纯函数缓动/噪声/色彩工具。"""

    def test_module_all(self) -> None:
        """__all__ 精确暴露公开 API。"""
        expected = {
            "ease_in_out_cubic",
            "hsv_shift",
            "mix_rgb",
            "sdf_soft_blob",
            "simplex_noise_2d",
            "wrap_phase",
        }
        assert set(_fluid_math.__all__) == expected

    def test_ease_in_out_cubic_endpoints(self) -> None:
        """t=0/1 映射到 0/1，t=0.5 映射到 0.5。"""
        assert _fluid_math.ease_in_out_cubic(0.0) == 0.0
        assert _fluid_math.ease_in_out_cubic(1.0) == 1.0
        assert _fluid_math.ease_in_out_cubic(0.5) == pytest.approx(0.5)

    def test_ease_in_out_cubic_clamps(self) -> None:
        """越界输入被钳制到 [0,1]。"""
        assert _fluid_math.ease_in_out_cubic(-0.5) == 0.0
        assert _fluid_math.ease_in_out_cubic(1.5) == 1.0
        # nan 输入透传（实现未做 nan 特判）——避免断言破坏确定性
        assert _fluid_math.ease_in_out_cubic(float("nan")) != 0.0  # type: ignore[arg-type]

    def test_wrap_phase(self) -> None:
        """wrap_phase 把任意实数折叠进 [0,1)。"""
        assert _fluid_math.wrap_phase(2.75) == pytest.approx(0.75)
        assert _fluid_math.wrap_phase(-0.25) == pytest.approx(0.75)  # floor 折叠
        assert _fluid_math.wrap_phase(0.0) == pytest.approx(0.0)
        assert _fluid_math.wrap_phase(float("inf")) == 0.0

    def test_simplex_noise_2d_range_and_determinism(self) -> None:
        """同 seed 结果确定且落在 [-1,1]。"""
        v1 = _fluid_math.simplex_noise_2d(1.25, 2.5, seed=7)
        v2 = _fluid_math.simplex_noise_2d(1.25, 2.5, seed=7)
        assert v1 == pytest.approx(v2)
        assert -1.0 <= v1 <= 1.0

    def test_simplex_noise_2d_seed_changes_result(self) -> None:
        """不同 seed 通常产生不同值。"""
        samples = {_fluid_math.simplex_noise_2d(3.14, 2.71, seed=s) for s in range(8)}
        assert len(samples) > 1

    def test_simplex_noise_2d_non_finite(self) -> None:
        """非有限坐标返回 0.0。"""
        assert _fluid_math.simplex_noise_2d(float("nan"), 0.0, seed=1) == 0.0

    def test_sdf_soft_blob_center_and_far(self) -> None:
        """中心为 1.0，远距衰减到 0.0，falloff=0 硬边界。"""
        assert _fluid_math.sdf_soft_blob(5.0, 5.0, 5.0, 5.0, radius=3.0) == 1.0
        # falloff=0.0：hard step，中心（dist=0 <= radius=1）仍为 1.0
        assert _fluid_math.sdf_soft_blob(5.0, 5.0, 5.0, 5.0, radius=1.0, falloff=0.0) == 1.0
        # dist=1.6 > radius*(1+falloff)=1.5 → 0.0
        assert _fluid_math.sdf_soft_blob(6.6, 5.0, 5.0, 5.0, radius=1.0, falloff=0.5) == 0.0

    def test_sdf_soft_blob_monotonic(self) -> None:
        """随距离增大，场值单调不增。"""
        values = [
            _fluid_math.sdf_soft_blob(5.0 + d, 5.0, 5.0, 5.0, radius=2.0, falloff=1.0)
            for d in (0.0, 1.0, 2.0, 3.5)
        ]
        assert all(v2 <= v1 for v1, v2 in zip(values, values[1:]))

    def test_hsv_shift(self) -> None:
        """hsv_shift 保持 alpha 并返回有效色。"""
        base = QColor(255, 0, 0, 128)  # hue 0
        shifted = _fluid_math.hsv_shift(base, 120.0, 0.0, 0.0)
        assert shifted.isValid() is True
        assert shifted.alpha() == 128

    def test_hsv_shift_invalid_color(self) -> None:
        """无效颜色返回不透明黑色。"""
        out = _fluid_math.hsv_shift(QColor(), 10.0, 0.0, 0.0)
        assert out == QColor(0, 0, 0, 255)

    def test_mix_rgb_endpoints(self) -> None:
        """t=0/1 分别返回 a/b。"""
        a = QColor(10, 20, 30, 40)
        b = QColor(200, 180, 160, 140)
        assert _fluid_math.mix_rgb(a, b, 0.0) == a
        assert _fluid_math.mix_rgb(a, b, 1.0) == b
        assert _fluid_math.mix_rgb(a, b, 0.5) == QColor(105, 100, 95, 90)

    def test_mix_rgb_invalid(self) -> None:
        """非 QColor 输入返回不透明黑色。"""
        assert _fluid_math.mix_rgb(None, QColor(1, 2, 3), 0.5) == QColor(0, 0, 0, 255)  # type: ignore[arg-type]


# =============================================================================
# ui.components._styled_fluid_cpu
# =============================================================================
class TestFluidCpu:
    """_styled_fluid_cpu：render_static_frame 确定性 CPU 渲染。"""

    _PALETTE = [
        QColor("#1a1a2e"),
        QColor("#16213e"),
        QColor("#0f3460"),
        QColor("#e94560"),
        QColor("#533483"),
    ]

    def test_render_static_frame_size(self, qapp: QApplication) -> None:
        """返回精确 (width, height) 的 QPixmap。"""
        pm = _fluid_cpu.render_static_frame(
            120, 80, self._PALETTE, noise_seed=42, time=0.5, overlay_color=QColor(0, 0, 0, 60),
        )
        assert isinstance(pm, QPixmap)
        assert not pm.isNull()
        assert pm.width() == 120
        assert pm.height() == 80

    def test_render_static_frame_deterministic(self, qapp: QApplication) -> None:
        """同 seed+time 两次渲染逐像素一致。"""
        pm1 = _fluid_cpu.render_static_frame(
            64, 48, self._PALETTE, noise_seed=99, time=1.0, overlay_color=QColor(0, 0, 0, 60),
        )
        pm2 = _fluid_cpu.render_static_frame(
            64, 48, self._PALETTE, noise_seed=99, time=1.0, overlay_color=QColor(0, 0, 0, 60),
        )
        assert pm1.toImage() == pm2.toImage()

    def test_render_static_frame_seed_changes_pixels(self, qapp: QApplication) -> None:
        """不同 seed 产生不同像素内容。"""
        pm1 = _fluid_cpu.render_static_frame(
            64, 48, self._PALETTE, noise_seed=1, time=0.5, overlay_color=QColor(0, 0, 0, 60),
        )
        pm2 = _fluid_cpu.render_static_frame(
            64, 48, self._PALETTE, noise_seed=2, time=0.5, overlay_color=QColor(0, 0, 0, 60),
        )
        assert pm1.toImage() != pm2.toImage()

    def test_render_static_frame_palette_variation(self, qapp: QApplication) -> None:
        """不同调色板产生不同像素。"""
        other = [QColor(c).darker(150) for c in self._PALETTE]
        pm1 = _fluid_cpu.render_static_frame(
            64, 48, self._PALETTE, noise_seed=3, time=0.5, overlay_color=QColor(0, 0, 0, 60),
        )
        pm2 = _fluid_cpu.render_static_frame(
            64, 48, other, noise_seed=3, time=0.5, overlay_color=QColor(0, 0, 0, 60),
        )
        assert pm1.toImage() != pm2.toImage()

    def test_render_static_frame_non_positive_size(self, qapp: QApplication) -> None:
        """非正尺寸返回 null pixmap。"""
        pm = _fluid_cpu.render_static_frame(
            0, 48, self._PALETTE, noise_seed=1, time=0.5, overlay_color=QColor(0, 0, 0, 60),
        )
        assert pm.isNull()


# =============================================================================
# ui.components._styled_fluid_gpu
# =============================================================================
class TestFluidGpu:
    """_styled_fluid_gpu：shader 源码常量与公开导出（不建真实 GL 上下文）。"""

    def test_module_all(self) -> None:
        """__all__ 暴露 _FluidGPUShaderWidget。"""
        assert _fluid_gpu.__all__ == ["_FluidGPUShaderWidget"]

    def test_vertex_shader_version(self) -> None:
        """顶点着色器声明 #version 330。"""
        assert "#version 330" in _fluid_gpu._VERTEX_SHADER

    def test_fragment_shader_version_and_uniforms(self) -> None:
        """片段着色器含关键 uniform 声明。"""
        frag = _fluid_gpu._FRAGMENT_SHADER
        assert "#version 330" in frag
        for uniform in (
            "u_resolution",
            "u_time",
            "u_palette[5]",
            "u_blob_centers[4]",
            "u_blob_radii[4]",
            "u_blob_colors[4]",
            "u_noise_offset",
            "u_overlay_color",
        ):
            assert uniform in frag

    def test_shader_widget_class_exposed(self) -> None:
        """_FluidGPUShaderWidget 类可从模块导出。"""
        assert hasattr(_fluid_gpu, "_FluidGPUShaderWidget")
        assert callable(_fluid_gpu._FluidGPUShaderWidget)


# =============================================================================
# ui.components.styled_fluid_background
# =============================================================================
class TestStyledFluidBackground:
    """StyledFluidBackground：调色板生命周期与 CPU 渲染分支。"""

    def test_construct_and_colors(self, qapp: QApplication) -> None:
        """默认构造即从 accent 推导 5 色调色板。"""
        bg = StyledFluidBackground()
        colors = bg.colors()
        assert len(colors) == 5
        assert all(isinstance(c, QColor) and c.isValid() for c in colors)
        safe_teardown(bg)

    def test_set_custom_colors_five(self, qapp: QApplication) -> None:
        """5 色自定义调色板原样保留。"""
        bg = StyledFluidBackground()
        custom = [QColor(f"#{i:02x}{i:02x}{i:02x}") for i in (10, 60, 120, 180, 240)]
        bg.set_custom_colors(custom)
        assert len(bg.colors()) == 5
        assert bg.colors()[0] == custom[0]
        safe_teardown(bg)

    def test_set_custom_colors_two_expands(self, qapp: QApplication) -> None:
        """2 色自定义调色板扩展为 5 档渐变。"""
        bg = StyledFluidBackground()
        bg.set_custom_colors([QColor("#000000"), QColor("#ffffff")])
        assert len(bg.colors()) == 5
        safe_teardown(bg)

    def test_set_custom_colors_invalid_falls_back(self, qapp: QApplication) -> None:
        """空/非法列表回退 accent 主题。"""
        bg = StyledFluidBackground()
        accent_colors = bg.colors()
        bg.set_custom_colors([])
        assert len(bg.colors()) == 5
        assert bg.colors()[0] == accent_colors[0]
        safe_teardown(bg)

    def test_renderer_none_before_load(self, qapp: QApplication) -> None:
        """load 之前 renderer() 为 None。"""
        bg = StyledFluidBackground()
        assert bg.renderer() is None
        safe_teardown(bg)

    def test_cpu_load_and_unload(self, qapp: QApplication, monkeypatch: Any) -> None:
        """FAF_FORCE_FLUID_CPU=1 时 load 选 CPU 渲染器，unload 复位。"""
        monkeypatch.setenv("FAF_FORCE_FLUID_CPU", "1")
        bg = StyledFluidBackground()
        bg.resize(160, 90)
        bg.load()
        assert bg.renderer() == "cpu"
        bg.unload()
        assert bg.renderer() is None
        # unload 调用了 deleteLater，不再主动 teardown

    def test_bake_static_frame_smoke(self, qapp: QApplication, monkeypatch: Any) -> None:
        """CPU 路径生成静态 pixmap。"""
        monkeypatch.setenv("FAF_FORCE_FLUID_CPU", "1")
        bg = StyledFluidBackground()
        bg.resize(160, 90)
        bg.load()
        assert bg._static_pixmap is not None
        assert not bg._static_pixmap.isNull()
        bg._static_pixmap = None
        safe_teardown(bg)


# =============================================================================
# ui.components.animated_file_list_view
# =============================================================================
class TestAnimatedFileListView:
    """AnimatedFileListView：构造与路径过渡 API。"""

    def test_construct(self, qapp: QApplication) -> None:
        """默认构造为 QListView 子类。"""
        view = AnimatedFileListView()
        assert isinstance(view, QListView)
        safe_teardown(view)

    def test_begin_path_transition_hidden_returns_false(self, qapp: QApplication) -> None:
        """未显示时 begin_path_transition 返回 False。"""
        view = AnimatedFileListView()
        view.setFixedSize(200, 150)
        assert view.begin_path_transition(1) is False
        safe_teardown(view)

    def test_cancel_path_transition_safe(self, qapp: QApplication) -> None:
        """cancel_path_transition 幂等不抛异常。"""
        view = AnimatedFileListView()
        view.cancel_path_transition()
        view.cancel_path_transition(update=True)
        safe_teardown(view)

    def test_finish_path_transition_idle(self, qapp: QApplication) -> None:
        """未 start 时 finish 返回 bool（enabled 时尝试启动快照过渡），不抛异常。"""
        view = AnimatedFileListView()
        result = view.finish_path_transition()
        assert isinstance(result, bool)
        view.cancel_path_transition()  # 清理 finish 启动的过渡
        safe_teardown(view)


# =============================================================================
# ui.components.file_list_model
# =============================================================================
class TestFileListModel:
    """FileListModel：角色常量、文件集设置与选中状态。"""

    def _files(self) -> list[dict[str, Any]]:
        """构造两个符合 FileInfo 契约的文件信息字典。

        Returns:
            list[dict[str, Any]]: 文件信息列表。
        """
        return [
            {
                "path": r"C:\demo\a.png",
                "name": "a.png",
                "type": "file",
                "extension": "png",
                "size": 100,
                "modified": 0,
            },
            {
                "path": r"C:\demo\b.txt",
                "name": "b.txt",
                "type": "file",
                "extension": "txt",
                "size": 200,
                "modified": 0,
            },
        ]

    def test_roles_are_user_plus_int(self, qapp: QApplication) -> None:
        """角色值为 Qt.UserRole 递增偏移。"""
        assert FileNameRole == Qt.UserRole + 1
        assert FilePathRole == Qt.UserRole + 2
        assert IsDirRole == Qt.UserRole + 3

    def test_set_files_and_row_count(self, qapp: QApplication) -> None:
        """set_files 后 rowCount 对应，get_row 命中路径。"""
        model = FileListModel()
        model.set_files(self._files())
        assert model.rowCount() == 2
        assert model.get_row(r"C:\demo\a.png") == 0
        assert model.get_row(r"C:\demo\missing.png") == -1
        safe_teardown(model)

    def test_data_roles(self, qapp: QApplication) -> None:
        """data() 按角色返回文件名/路径/目录标志。"""
        model = FileListModel()
        model.set_files(self._files())
        index = model.index(0, 0)
        assert model.data(index, FileNameRole) == "a.png"
        assert model.data(index, FilePathRole) == r"C:\demo\a.png"
        assert model.data(index, IsDirRole) is False
        safe_teardown(model)

    def test_selection_roundtrip(self, qapp: QApplication) -> None:
        """set_selected / get_selected_files / toggle 往返。"""
        model = FileListModel()
        model.set_files(self._files())
        assert model.set_selected(r"C:\demo\a.png", True) is True
        assert model.get_selected_files() == [r"C:\demo\a.png"]
        # toggle_selected 返回切换后的新选中状态
        assert model.toggle_selected(r"C:\demo\a.png") is False
        assert model.get_selected_files() == []
        assert model.toggle_selected(r"C:\demo\a.png") is True
        assert model.get_selected_files() == [r"C:\demo\a.png"]
        safe_teardown(model)

    def test_clear(self, qapp: QApplication) -> None:
        """clear 清空数据与选择。"""
        model = FileListModel()
        model.set_files(self._files())
        model.set_selected(r"C:\demo\a.png", True)
        model.clear()
        assert model.rowCount() == 0
        assert model.get_selected_files() == []
        safe_teardown(model)

    def test_geometry_helpers(self, qapp: QApplication) -> None:
        """set_card_width / set_grid_offset_x / update_theme 不抛异常。"""
        model = FileListModel()
        model.set_files(self._files())
        model.set_card_width(240, 120)
        model.set_grid_offset_x(12)
        model.update_geometry(240, 120)
        model.update_theme()
        safe_teardown(model)


# =============================================================================
# ui.components.file_card_delegate
# =============================================================================
class TestFileCardDelegate:
    """FileCardDelegate：模式切换、缩放与离屏绘制冒烟。"""

    def test_construct_and_modes(self, qapp: QApplication) -> None:
        """构造 + set_card_mode/set_list_mode/set_card_scale 不抛异常。"""
        delegate = FileCardDelegate()
        delegate.set_card_mode()
        delegate.set_list_mode()
        delegate.set_card_scale(1.25)
        delegate.set_pool_files([r"C:\demo\a.png"])
        safe_teardown(delegate)

    def test_set_view(self, qapp: QApplication) -> None:
        """set_view 接受 QListView。"""
        delegate = FileCardDelegate()
        view = QListView()
        delegate.set_view(view)
        safe_teardown(delegate)
        safe_teardown(view)

    def test_media_scale_property(self, qapp: QApplication) -> None:
        """media_scale Property 可读写（QPropertyAnimation 目标）。"""
        delegate = FileCardDelegate()
        assert delegate.media_scale == 0.0
        delegate.media_scale = 0.5
        assert delegate.media_scale == 0.5
        safe_teardown(delegate)

    def test_paint_smoke(self, qapp: QApplication) -> None:
        """离屏绘制一个列表项产生非空像素。"""
        delegate = FileCardDelegate()
        delegate.set_list_mode()
        view = QListView()
        delegate.set_view(view)

        model = FileListModel()
        model.set_files([
            {
                "path": r"C:\demo\a.png",
                "name": "a.png",
                "type": "file",
                "extension": "png",
                "size": 100,
                "modified": 0,
            }
        ])
        view.setModel(model)
        view.resize(200, 120)

        from PySide6.QtWidgets import QStyleOptionViewItem

        option = QStyleOptionViewItem()
        option.rect = view.rect().adjusted(4, 4, -4, -4)
        index = model.index(0, 0)

        pm = QPixmap(200, 120)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        try:
            delegate.paint(painter, option, index)
        finally:
            painter.end()
        assert_pixmap_nonempty(pm)
        view.setModel(None)
        safe_teardown(delegate)
        safe_teardown(model)
        safe_teardown(view)