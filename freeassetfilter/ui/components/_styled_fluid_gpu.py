"""QRhi renderer for the styled fluid background.

FreeAssetFilter - 多功能文件预览与管理工具
Copyright (c) 2026 Dorufoc <dorofoc@outlook.com>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

为什么是 QRhiWidget 而不是 QOpenGLWidget
----------------------------------------
窗口内只要出现 ``QOpenGLWidget``，Qt 就会把**顶层窗口**切换到 OwnDC 窗口类；
该类窗口拖拽缩放时无法只重绘新暴露条带，每个 WM_SIZE 都要整窗重绘——实测
鼠标-窗口边缘滞后中位 96px / 峰值 258px（raster 类窗口仅 6px），窗口边缘
完全跟不上鼠标。``QRhiWidget`` 走纹理合成路径，不会触发该切换，实测拖拽
滞后保持 6px，同时仍能与普通控件正确叠放（信息面板浮在流体之上）。

着色器以 Qt Shader Baker 编译产物 ``shaders/fluid.vert.qsb`` 与
``shaders/fluid.frag.qsb`` 加载（同时含 GLSL 与 HLSL 变体，由 QRhi 按当前
后端选择）；uniform 通过 std140 uniform block 上传，布局见
``shaders/fluid.frag`` 顶部注释与 :meth:`_pack_uniforms`。

渲染尺寸一律取 ``colorTexture().pixelSize()``，绝不用「逻辑尺寸 × DPR」自行
换算：Qt 用 ``qRound()``（0.5 远离零）创建纹理，Python ``round()`` 是银行家
舍入，150% DPI 下两者会差 1 像素，令纹理最右/最下一列永不写入（alpha=0），
合成时露出下层背景（浅色主题白边、深色主题异色细线）。

为什么绝不能强制原生化（不设 WA_NativeWindow）
---------------------------------------------
``WA_NativeWindow`` 会让本控件变成独立 HWND：Windows 在窗口缩放时**立刻**
改变该 HWND 的位置与尺寸并拉伸上一帧的交换链内容，而顶层窗口的其余客户区
内容要等 Qt 下一次重绘才更新。两者响应同一次拖拽的时机不同，视觉上就是流
体渲染区域相对窗口边缘**错位闪烁**、并在缩放过程中出现拉伸撕裂。参与宿主
合成（不原生化）后，流体纹理与其余控件内容在同一次合成里按同一套几何摆
放，时机完全一致。

代价是：非原生 QRhiWidget 的 QRhi 来自顶层窗口的合成后端，而顶层窗口**只有
在 QWindow 创建之前其层级里已经存在 QRhiWidget** 才会启用 RHI 合成。本项目
主窗口在 ``MainWindow.__init__`` 早期就访问了 ``winId()``，而音频页的预览器
是窗口显示后才惰性构建的，因此必须在建窗之前先挂一个不可见的预热控件——
见 ``styled_fluid_background.prewarm_top_level_rhi``。

为什么颜色缓冲尺寸必须与控件尺寸完全一致
----------------------------------------
``QRhiWidget`` 默认令颜色缓冲尺寸跟随控件尺寸（``控件尺寸 × DPR``）。窗口
缩放时纹理每一步都要重建，Qt 会因纹理重建而再次回调
:meth:`_FluidGPUShaderWidget.initialize`；该函数已做成幂等（见其文档），
尺寸变化不重建管线、缓冲区与着色器，实测每步仅约 0.04ms，原本每步约 4ms
的瓶颈（重新读盘并反序列化 ``.qsb``、重建 D3D11 管线）已经消除。

曾尝试用 ``setFixedColorBufferSize`` 把缓冲尺寸量化固定（每 256 设备像素一
档）来进一步减少重建次数。但顶层合成器是把固定尺寸的纹理**拉伸**铺满控件
区域的：纹理与控件宽高比不一致时，流体图案会被沿单轴拉伸。实测控件
570x180（比例 3.17）被固定为 1024x512（比例 2.00），横向拉长约 58%，而且
该拉伸比例随窗口尺寸连续变化、跨档时突变——正是要消除的错位闪烁。它换来
的收益却只有约 0.04ms/步。因此不再固定缓冲尺寸：颜色缓冲始终等于控件设备
像素尺寸，纹理与控件宽高比一致，渲染区域与控件区域逐像素对齐，不滞后。
"""

from __future__ import annotations

import logging
import struct
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QColor,
    QRhiBuffer,
    QRhiDepthStencilClearValue,
    QRhiGraphicsPipeline,
    QRhiShaderResourceBinding,
    QRhiShaderStage,
    QRhiVertexInputAttribute,
    QRhiVertexInputBinding,
    QRhiVertexInputLayout,
    QRhiViewport,
    QShader,
)
from PySide6.QtWidgets import QRhiWidget, QWidget

__all__ = ["_FluidGPUShaderWidget"]

logger = logging.getLogger(__name__)

#: 全屏两个三角形（归一化设备坐标），每顶点 3 个 float。
_VERTEX_DATA = struct.pack(
    "18f",
    -1.0, 1.0, 0.0,
    -1.0, -1.0, 0.0,
    1.0, -1.0, 0.0,
    -1.0, 1.0, 0.0,
    1.0, -1.0, 0.0,
    1.0, 1.0, 0.0,
)

#: 顶点着色器输入：location 0 = vec3 位置，步长 12 字节。
_VERTEX_STRIDE = 12

#: 编译后的着色器文件名（``qsb`` 每次只处理一个输入文件，故顶点/片元分开）。
_QSB_VERT_NAME = "fluid.vert.qsb"
_QSB_FRAG_NAME = "fluid.frag.qsb"

_DEFAULT_BLOB_CENTERS = (
    (0.16, 0.20),
    (0.84, 0.24),
    (0.30, 0.80),
    (0.78, 0.72),
)

_DEFAULT_BLOB_RADII = (0.58, 0.50, 0.53, 0.45)

_DEFAULT_BLOB_COLORS = (0, 1, 2, 3)


def _qsb_path(name: str) -> Path:
    """返回编译后的着色器路径（兼容 PyInstaller 冻结环境）。"""
    local = Path(__file__).resolve().parent / "shaders" / name
    if local.exists():
        return local
    try:
        from freeassetfilter.utils.path_utils import get_resource_path

        return Path(
            get_resource_path(f"freeassetfilter/ui/components/shaders/{name}")
        )
    except Exception:  # noqa: BLE001 - 路径解析失败时返回本地路径（随后报错回退 CPU）
        return local


class _FluidGPUShaderWidget(QRhiWidget):
    """GPU 流体背景渲染器（QRhiWidget + .qsb 着色器）。

    渲染一屏全屏四边形：片元着色器绘制四个软 SDF 团块，用伪 simplex 噪声做
    域扭曲，再做 9 抽样软模糊近似与主题叠加。运行时通过
    :meth:`update_uniforms` 更新 uniform（不重新编译着色器）驱动动画。

    :meth:`initialize` 中任何失败都抛 :class:`RuntimeError`，由调用方回退到
    CPU 静态烘焙路径。
    """

    _PALETTE_SIZE = 5
    _BLOB_COUNT = 4
    #: std140 uniform block 大小（字节），与 shaders/fluid.frag 布局一致。
    _UNIFORM_BLOCK_SIZE = 256

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # 保持非原生（参与宿主合成）：原生化会让本控件的 HWND 与顶层窗口其余
        # 内容响应同一次拖拽的时机不同，造成流体区域错位闪烁（见模块头注释）。
        # 非原生路径需要顶层窗口在建窗时即启用 RHI 合成，由
        # ``styled_fluid_background.prewarm_top_level_rhi`` 负责。
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)

        self._time = 0.0
        self._palette = [QColor(0, 0, 0, 255)] * self._PALETTE_SIZE
        self._blob_centers = list(_DEFAULT_BLOB_CENTERS)
        self._blob_radii = list(_DEFAULT_BLOB_RADII)
        self._blob_colors = list(_DEFAULT_BLOB_COLORS)
        self._noise_offset = (0.0, 0.0)
        self._overlay_color = QColor(0, 0, 0, 0)

        self._vbuf: QRhiBuffer | None = None
        self._ubuf: QRhiBuffer | None = None
        self._srb: QRhiShaderResourceBindings | None = None
        self._pipeline: QRhiGraphicsPipeline | None = None
        self._initialized = False
        #: 资源所属的 QRhi 与渲染通道描述符。二者任一变化都必须重建资源
        #: （例如顶层窗口重建 RHI、颜色缓冲格式变化），仅尺寸变化不必。
        self._rhi = None
        self._render_pass = None
        #: uniform 版本号，每次 :meth:`update_uniforms` 自增；与渲染目标
        #: 尺寸一起构成「已绘制内容」的标识，用于跳过重复绘制。
        self._uniform_version = 0
        self._drawn_key: tuple[int, int, int] | None = None

    # -- 初始化 -------------------------------------------------------------

    def is_ready(self) -> bool:
        """渲染管线是否已成功创建（未就绪时调用方应回退 CPU 路径）。"""
        return self._initialized

    def initialize(self, cb) -> None:  # noqa: ANN001 - QRhiCommandBuffer
        """构建缓冲区、资源绑定与渲染管线（幂等）。

        Qt 在颜色缓冲被创建或重建后都会回调本函数（首次初始化、尺寸/格式/
        采样数变化），因此窗口缩放时它会被反复调用。缓冲区、资源绑定与管线
        只依赖 QRhi 与渲染通道描述符，尺寸变化不影响其可用性（渲染尺寸由
        :meth:`render` 每帧读取 ``colorTexture().pixelSize()`` 设置），所以
        只有这两者真正变化时才重建；否则每步缩放都要重新读盘加载着色器并
        重建 D3D11 管线，渲染跟不上窗口尺寸变化。

        Raises:
            RuntimeError: 着色器缺失 / QRhi 不可用 / 管线创建失败。
        """
        rhi = self.rhi()
        if rhi is None:
            raise RuntimeError("QRhi is not available")

        render_target = self.renderTarget()
        if render_target is None:
            raise RuntimeError("QRhi 渲染目标不可用")
        render_pass = render_target.renderPassDescriptor()

        if self._initialized and self._rhi is rhi and self._render_pass is render_pass:
            # 颜色缓冲刚被重建，内容未定义：下一帧必须重绘。
            self._drawn_key = None
            return

        # 资源要么属于旧的 QRhi，要么是为旧渲染通道描述符创建的，都不能
        # 再用（QRhi 会在切换时先调用 releaseResources，这里再防一次幂等）。
        self.releaseResources()

        vert_shader = self._load_shader(_QSB_VERT_NAME)
        frag_shader = self._load_shader(_QSB_FRAG_NAME)

        vbuf = rhi.newBuffer(
            QRhiBuffer.Type.Immutable, QRhiBuffer.UsageFlag.VertexBuffer, len(_VERTEX_DATA)
        )
        if not vbuf.create():
            raise RuntimeError("顶点缓冲区创建失败")
        rub = rhi.nextResourceUpdateBatch()
        rub.uploadStaticBuffer(vbuf, _VERTEX_DATA)
        cb.resourceUpdate(rub)

        ubuf = rhi.newBuffer(
            QRhiBuffer.Type.Dynamic,
            QRhiBuffer.UsageFlag.UniformBuffer,
            self._UNIFORM_BLOCK_SIZE,
        )
        if not ubuf.create():
            raise RuntimeError("uniform 缓冲区创建失败")

        srb = rhi.newShaderResourceBindings()
        srb.setBindings(
            [
                QRhiShaderResourceBinding.uniformBuffer(
                    0, QRhiShaderResourceBinding.StageFlag.FragmentStage, ubuf
                )
            ]
        )
        if not srb.create():
            raise RuntimeError("着色器资源绑定创建失败")

        layout = QRhiVertexInputLayout()
        layout.setBindings([QRhiVertexInputBinding(_VERTEX_STRIDE)])
        layout.setAttributes(
            [
                QRhiVertexInputAttribute(
                    0, 0, QRhiVertexInputAttribute.Format.Float3, 0
                )
            ]
        )

        pipeline = rhi.newGraphicsPipeline()
        pipeline.setShaderStages(
            [
                QRhiShaderStage(QRhiShaderStage.Type.Vertex, vert_shader),
                QRhiShaderStage(QRhiShaderStage.Type.Fragment, frag_shader),
            ]
        )
        pipeline.setVertexInputLayout(layout)
        pipeline.setShaderResourceBindings(srb)
        pipeline.setTopology(QRhiGraphicsPipeline.Topology.Triangles)
        pipeline.setSampleCount(1)
        # 单个颜色附件必须显式给出 target blend（默认不透明混合）。
        pipeline.setTargetBlends([QRhiGraphicsPipeline.TargetBlend()])
        pipeline.setRenderPassDescriptor(render_pass)
        if not pipeline.create():
            raise RuntimeError("渲染管线创建失败")

        self._vbuf = vbuf
        self._ubuf = ubuf
        self._srb = srb
        self._pipeline = pipeline
        self._rhi = rhi
        self._render_pass = render_pass
        self._initialized = True
        self._drawn_key = None

    @staticmethod
    def _load_shader(name: str) -> QShader:
        """加载并校验一个 ``.qsb`` 着色器。

        Args:
            name: 着色器文件名（如 ``fluid.vert.qsb``）。

        Returns:
            反序列化后的 :class:`QShader`。

        Raises:
            RuntimeError: 文件缺失或反序列化失败。
        """
        path = _qsb_path(name)
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise RuntimeError(f"着色器文件读取失败：{path}") from exc
        shader = QShader.fromSerialized(data)
        if not shader.isValid():
            raise RuntimeError(f"着色器反序列化失败：{path}")
        return shader

    def releaseResources(self) -> None:
        """释放 QRhi 资源（后端重建时 Qt 会再次调用 :meth:`initialize`）。"""
        self._initialized = False
        for resource in (self._pipeline, self._srb, self._ubuf, self._vbuf):
            if resource is not None:
                try:
                    resource.destroy()
                except Exception:  # noqa: BLE001 - 销毁失败不影响后续重建
                    pass
        self._pipeline = None
        self._srb = None
        self._ubuf = None
        self._vbuf = None
        # 置空归属信息，令下一次 initialize() 必定重新创建资源。
        self._rhi = None
        self._render_pass = None
        self._drawn_key = None

    # -- 渲染 ---------------------------------------------------------------

    def render(self, cb) -> None:  # noqa: ANN001 - QRhiCommandBuffer
        """把流体背景绘制到 QRhi 渲染目标。"""
        if not self._initialized or self._pipeline is None or self._ubuf is None:
            return
        if self.width() <= 0 or self.height() <= 0:
            return

        rhi = self.rhi()
        render_target = self.renderTarget()
        color_texture = self.colorTexture()
        if rhi is None or render_target is None or color_texture is None:
            return

        # 渲染目标尺寸必须取纹理的真实像素尺寸，不能用「逻辑尺寸 × DPR」自行
        # 换算：Qt 用 qRound()（0.5 远离零）创建纹理，而 Python round() 是
        # 银行家舍入（0.5 取偶）。150% DPI 下 403 逻辑像素会得到 604 与 605
        # 的差异，最右/最下一列因此永不写入（alpha=0），合成时露出下层背景——
        # 浅色主题下是白边、深色主题下是异色细线。
        size = color_texture.pixelSize()
        physical_width = max(1, int(size.width()))
        physical_height = max(1, int(size.height()))

        # 控件每步缩放都会同步触发一次绘制，但颜色缓冲尺寸已按量化步长固定，
        # 单纯的尺寸变化并不改变画面内容；uniform 未更新时整屏输出与上一帧
        # 完全一致，直接跳过重绘，避免缩放期间做无谓的全屏计算而拖慢渲染。
        key = (physical_width, physical_height, self._uniform_version)
        if key == self._drawn_key:
            return

        rub = rhi.nextResourceUpdateBatch()
        rub.updateDynamicBuffer(
            self._ubuf, 0, self._pack_uniforms(physical_width, physical_height)
        )

        cb.beginPass(
            render_target,
            QColor(0, 0, 0, 0),
            QRhiDepthStencilClearValue(1.0, 0),
            rub,
        )
        try:
            cb.setGraphicsPipeline(self._pipeline)
            cb.setViewport(QRhiViewport(0, 0, physical_width, physical_height))
            cb.setShaderResources()
            cb.setVertexInput(0, [(self._vbuf, 0)])
            cb.draw(6)
        finally:
            cb.endPass()
        self._drawn_key = key

    def _pack_uniforms(self, width: int, height: int) -> bytes:
        """按 std140 布局打包 uniform block（256 字节）。

        Args:
            width: 渲染目标物理宽度（像素）。
            height: 渲染目标物理高度（像素）。

        Returns:
            可直接上传的 256 字节数据。
        """
        values: list[float] = []
        # vec4 u_resolution_time（xy 分辨率、z 时间）
        values.extend((float(width), float(height), float(self._time), 0.0))
        # vec4 u_noise_offset
        values.extend(
            (float(self._noise_offset[0]), float(self._noise_offset[1]), 0.0, 0.0)
        )
        # vec4 u_overlay_color
        overlay = self._overlay_color
        values.extend(
            (overlay.redF(), overlay.greenF(), overlay.blueF(), overlay.alphaF())
        )
        # vec4 u_palette[5]
        for color in self._palette[: self._PALETTE_SIZE]:
            values.extend((color.redF(), color.greenF(), color.blueF(), 0.0))
        # vec4 u_blob_centers[4]
        for x, y in self._blob_centers[: self._BLOB_COUNT]:
            values.extend((float(x), float(y), 0.0, 0.0))
        # vec4 u_blob_radii_colors[4]
        for radius, index in zip(
            self._blob_radii[: self._BLOB_COUNT],
            self._blob_colors[: self._BLOB_COUNT],
        ):
            values.extend((float(radius), float(index), 0.0, 0.0))
        return struct.pack(f"{len(values)}f", *values)

    # -- 运行时 uniform 更新 -------------------------------------------------

    def update_uniforms(
        self,
        *,
        time: float | None = None,
        palette: Sequence[QColor] | None = None,
        blob_centers: Sequence[tuple[float, float]] | None = None,
        blob_radii: Sequence[float] | None = None,
        blob_colors: Sequence[int] | None = None,
        noise_offset: tuple[float, float] | None = None,
        overlay_color: QColor | None = None,
    ) -> None:
        """更新着色器 uniform 并请求重绘。

        所有参数均为关键字参数；``None`` 表示保持原值。

        Args:
            time: 动画时间（秒）。
            palette: 最多 5 个 :class:`QColor`。
            blob_centers: 四个归一化 ``(x, y)`` 位置。
            blob_radii: 四个归一化半径。
            blob_colors: 四个调色板索引。
            noise_offset: ``(x, y)`` 噪声漂移。
            overlay_color: 含 alpha 的叠加色。
        """
        if time is not None:
            self._time = float(time)
        if palette is not None:
            self._palette = self._normalize_palette(list(palette))
        if blob_centers is not None:
            self._blob_centers = self._normalize_centers(list(blob_centers))
        if blob_radii is not None:
            self._blob_radii = self._normalize_radii(list(blob_radii))
        if blob_colors is not None:
            self._blob_colors = self._normalize_color_indices(list(blob_colors))
        if noise_offset is not None:
            self._noise_offset = (float(noise_offset[0]), float(noise_offset[1]))
        if overlay_color is not None:
            self._overlay_color = QColor(overlay_color)

        self._uniform_version += 1
        self.update()

    def _normalize_palette(self, palette: list[QColor]) -> list[QColor]:
        """返回恰好 ``_PALETTE_SIZE`` 个颜色，保持位置不变。

        无效项由前一个有效色就地替换（而非过滤掉）：过滤会使其后所有调色板
        索引整体前移，导致该帧整个场景改色。
        """
        normalized: list[QColor] = []
        last_valid = QColor(0, 0, 0, 255)
        for c in palette[: self._PALETTE_SIZE]:
            if isinstance(c, QColor) and c.isValid():
                last_valid = QColor(c)
                normalized.append(QColor(c))
            else:
                normalized.append(QColor(last_valid))
        while len(normalized) < self._PALETTE_SIZE:
            normalized.append(QColor(last_valid))
        return normalized

    def _normalize_centers(
        self, centers: list[tuple[float, float]]
    ) -> list[tuple[float, float]]:
        """返回恰好 ``_BLOB_COUNT`` 个中心点。"""
        while len(centers) < self._BLOB_COUNT:
            centers.append((0.0, 0.0))
        return centers[: self._BLOB_COUNT]

    def _normalize_radii(self, radii: list[float]) -> list[float]:
        """返回恰好 ``_BLOB_COUNT`` 个半径。"""
        while len(radii) < self._BLOB_COUNT:
            radii.append(0.25)
        return radii[: self._BLOB_COUNT]

    def _normalize_color_indices(self, indices: list[int]) -> list[int]:
        """返回恰好 ``_BLOB_COUNT`` 个调色板索引。"""
        while len(indices) < self._BLOB_COUNT:
            indices.append(0)
        return [max(0, int(i)) % self._PALETTE_SIZE for i in indices[: self._BLOB_COUNT]]
