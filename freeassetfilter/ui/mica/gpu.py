"""Mica GPU 渲染门面 —— 把原生 D3D11 渲染管线接到 :mod:`ui.mica.engine` 的契约上。

定位与职责边界
--------------
本模块是 **GPU 侧的唯一入口**，负责把「窗口矩形 + 参数 + 壁纸源」翻译成一次原生
烘焙调用，并在任何环节失败时**静默退回** :func:`ui.mica.engine.bake` 的 numpy
CPU 管线。它刻意不改动 :mod:`ui.mica.engine` 的语义：两次调用在参数相同时必须
产出统计意义上一致的色调场（实测逐像素平均绝对差 0.27 / 255，p99 = 1）。

依赖方向是**单向**的：``gpu`` → ``engine``。因此 CPU 管线保持纯粹可测（无需
D3D 设备、无需显示器），GPU 只是它的加速替身，二者共用同一套参数映射与几何
推导（:func:`ui.mica.config.bake_grid_size` / :func:`ui.mica.engine.margin_px` /
:meth:`ui.mica.config.MicaParams.to_engine`），不存在两份走样的公式。

为什么必须有一条专用工作线程
----------------------------
:class:`~freeassetfilter.core.native.bridges.mica_render.MicaRenderContext` 持有
三个非线程安全的对象：

* ``ID3D11DeviceContext``（立即上下文）——D3D11 明确规定不可并发调用；
* 单线程 ``ID2D1Factory1``；
* WIC 成像工厂。

此外 ``mica_create`` 会在**调用线程**上执行 ``CoInitializeEx(COINIT_APARTMENTTHREADED)``，
把 COM 公寓绑定到该线程。这意味着一个上下文实例必须终身只在其创建线程上使用。

因此 :class:`GpuRenderer` 在构造时启动一条常驻守护线程，上下文的创建、画布构建、
烘焙、销毁**全部**在这条线程上串行执行；调用方通过 :meth:`GpuRenderer.bake`
同步等待结果。这样：

* 调用方（Qt 主线程或 ``QThread`` worker）无需感知 COM 公寓约束；
* 多个窗口共享同一台 D3D 设备（设备创建是毫秒级开销，不该每个窗口来一次）；
* 串行队列天然消除了并发访问 GPU 的风险，无需额外加锁。

降级链（任一环节失败即向下，最终必然产出有效画布）
-------------------------------------------------
==========  ==========================================  ==========================
优先级      通道                                          触发条件
==========  ==========================================  ==========================
1           ``build_canvas_from_wallpapers``              至少一台显示器有壁纸文件
            （WIC 解码 + Direct2D 摆放）
2           ``build_canvas_from_dxgi``                    上一步失败 **且**
            （DXGI Desktop Duplication）                  ``FAF_MICA_DXGI=1``
3           ``build_canvas_from_memory``                  CPU 侧已解码成功的画布
4           ``build_canvas_solid``                        以上全部失败
==========  ==========================================  ==========================

关于 DXGI 为何不是主路径：``IDXGIOutputDuplication::AcquireNextFrame`` 只在桌面
**内容发生变化**时投递帧，静态桌面下必然返回 ``DXGI_ERROR_WAIT_TIMEOUT``（实测
连续 8 次、每次 ~165 ms 全部超时）。把它作为主路径会让每次烘焙都白等一个超时
周期。它的正确定位是「壁纸文件无法描述桌面」时的兜底——动态壁纸软件
（Wallpaper Engine 等）、幻灯片、纯色 + 第三方绘制等场景。

失败封禁策略
------------
* 连续失败 :data:`MAX_CONSECUTIVE_FAILURES` 次 → 永久停用 GPU，全量走 CPU；
* 设备丢失 / 无设备（``fatal``）→ 标记重建上下文，下一个任务前重试一次；
* 任务超时（:data:`JOB_TIMEOUT_MS`）→ 判定工作线程卡死。Python 无法安全终止
  卡在原生调用里的线程，故**只停用、不强杀**，线程作为守护线程留待进程退出。

这三条规则保证了「GPU 出问题只会退化，绝不会让窗口没有背景或让 UI 卡住」。

用法
----
绝大多数调用方只需要 :func:`gpu_bake`：::

    from freeassetfilter.ui.mica.gpu import gpu_bake
    field = gpu_bake(request, source)      # 返回 None 表示连 CPU 也失败

它等价于「先试 GPU，失败则 :func:`ui.mica.engine.bake`」。
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Optional, Tuple

import numpy as np

from . import tint
from .config import BAKE_WATCHDOG_MS, bake_grid_size
from .engine import (
    BakeRequest,
    BakedField,
    bake as cpu_bake,
    bake_with_grid as cpu_bake_with_grid,
    margin_px,
)
from .source import (
    CANVAS_MAX_LONG,
    DXGI_TIMEOUT_MS,
    DesktopInfo,
    WallpaperSource,
    dxgi_enabled,
)

try:  # pragma: no cover - 导入失败不应让整个 ui.mica 不可用
    from freeassetfilter.core.native.bridges import mica_render as _mr
except Exception as _IMPORT_EXC:  # pragma: no cover
    _mr = None  # type: ignore[assignment]
    _IMPORT_ERROR = str(_IMPORT_EXC)
else:
    _IMPORT_ERROR = ""

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

#: 单个渲染任务（画布构建 + 烘焙）的等待上限（毫秒）。
JOB_TIMEOUT_MS: float = 8000.0

#: 连续失败达到该次数后永久停用 GPU 后端。
MAX_CONSECUTIVE_FAILURES: int = 3

#: :meth:`GpuRenderer.dispose` 等待工作线程退出的上限（毫秒）。
DISPOSE_JOIN_MS: float = 2000.0

#: 工作线程名（便于在调试器 / 崩溃转储里辨认）。
WORKER_THREAD_NAME: str = "faf-mica-gpu"


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GpuStats:
    """GPU 后端的可观测量快照（诊断 / 日志 / 设置页显示用）。

    Attributes:
        available: 原生库是否可加载（构造期判定，与设备是否创建成功无关）。
        enabled: 后端是否仍在服务（``False`` 表示已封禁或卡死）。
        disabled_reason: 停用原因；仍在服务时为空串。
        adapter: 图形适配器描述；尚未创建设备时为空串。
        feature_level: 特性等级文本，如 ``"11_1"``。
        use_warp: 是否降级到 WARP 软件光栅。
        dxgi_available: DXGI 桌面复制可用性；``None`` 表示尚未探测。
        canvas_builds: 累计画布构建次数（跨烘焙复用，远小于烘焙次数）。
        bakes: 累计成功烘焙次数。
        failures: 累计失败次数（含最终成功前的重试）。
        last_canvas_ms: 最近一次画布构建耗时（毫秒）。
        last_bake_ms: 最近一次烘焙耗时（毫秒）。
        last_backend: 最近一次生效的画布来源。
    """

    available: bool
    enabled: bool
    disabled_reason: str
    adapter: str
    feature_level: str
    use_warp: bool
    dxgi_available: Optional[bool]
    canvas_builds: int
    bakes: int
    failures: int
    last_canvas_ms: float
    last_bake_ms: float
    last_backend: str


# ---------------------------------------------------------------------------
# 任务
# ---------------------------------------------------------------------------


@dataclass
class _Job:
    """投递给工作线程的一次渲染任务。

    Attributes:
        request: 烘焙输入快照（不可变，可安全跨线程传递）。
        desktop: 桌面元数据，画布重建时使用。
        fallback_rgb: 纯色兜底色（通常为主题 G1 基色）。
        fallback_pixels: CPU 侧已解码的画布；``None`` 表示不可用。
        allow_dxgi: 是否允许走 DXGI 桌面复制通道。
        event: 完成信号（每任务独占，保证结果不会串）。
        result: 成功时的产物。
        error: 失败时的异常。
        canvas_ms: 本次画布构建耗时（毫秒，0 表示命中缓存未重建）。
        canvas_backend: 本次生效的画布来源。
        info: 设备快照（仅在上下文刚创建时非空）。
    """

    request: BakeRequest
    desktop: DesktopInfo
    fallback_rgb: Tuple[int, int, int]
    fallback_pixels: Optional[np.ndarray]
    allow_dxgi: bool
    #: 显式网格尺寸；``None`` 表示由 ``request.window_rect`` 推导（常规路径）。
    grid_size: Optional[Tuple[int, int]] = None
    event: threading.Event = field(default_factory=threading.Event)
    result: Optional[BakedField] = None
    error: Optional[BaseException] = None
    canvas_ms: float = 0.0
    canvas_backend: str = ""
    info: Optional[object] = None


# ---------------------------------------------------------------------------
# 渲染器
# ---------------------------------------------------------------------------


class GpuRenderer:
    """Mica GPU 渲染器：专用工作线程 + 原生上下文 + 自动降级。

    一个进程只需一个实例（D3D 设备创建是毫秒级开销，且 GPU 资源有限），
    通过 :func:`get_gpu_renderer` 获取进程级共享实例。

    线程安全性：:meth:`bake` 可被任意线程并发调用；内部把任务串行投递给唯一
    的工作线程，结果经每任务独占的 :class:`threading.Event` 回传，不存在串扰。
    """

    def __init__(
        self,
        *,
        allow_warp: bool = True,
        job_timeout_ms: float = JOB_TIMEOUT_MS,
    ) -> None:
        """启动工作线程（上下文延迟到首个任务时创建）。

        Args:
            allow_warp: 硬件适配器不可用时是否允许降级到 WARP 软件光栅。
                WARP 可用但比硬件慢一个量级，仅作为最后手段。
            job_timeout_ms: 单个任务的等待上限（毫秒）。
        """
        self._allow_warp = bool(allow_warp)
        self._job_timeout_ms = max(500.0, float(job_timeout_ms))

        # 提交锁：保证「封禁判定 + 入队」原子，避免停用瞬间还塞进新任务。
        self._submit_lock = threading.Lock()
        # 状态锁：保护计数器与封禁标志（工作线程与调用方都会写）。
        self._state_lock = threading.Lock()

        self._queue: "queue.Queue[Optional[_Job]]" = queue.Queue()
        self._disabled_reason: str = ""
        self._stuck: bool = False
        self._invalidate_pending: bool = False
        self._failures: int = 0
        self._bakes: int = 0
        self._canvas_builds: int = 0
        self._last_bake_ms: float = 0.0
        self._last_canvas_ms: float = 0.0
        self._last_backend: str = ""
        self._info: Optional[object] = None

        # 以下三个字段**仅由工作线程访问**，无需加锁。
        self._ctx: Optional[object] = None
        self._recreate_pending: bool = False
        self._canvas_signature: Optional[str] = None

        self._thread = threading.Thread(
            target=self._loop, name=WORKER_THREAD_NAME, daemon=True
        )
        self._thread.start()

    # -- 公开 API ---------------------------------------------------------

    @property
    def alive(self) -> bool:
        """工作线程是否仍在运行。"""
        return self._thread.is_alive()

    def bake(
        self,
        request: BakeRequest,
        source: WallpaperSource,
        *,
        allow_dxgi: Optional[bool] = None,
        timeout_ms: Optional[float] = None,
        grid_size: Optional[Tuple[int, int]] = None,
    ) -> Optional[BakedField]:
        """执行一次 GPU 烘焙；失败返回 ``None``（调用方负责降级）。

        Args:
            request: 烘焙输入快照。
            source: 壁纸源画布（提供桌面元数据与 CPU 兜底像素）。
            allow_dxgi: 是否允许 DXGI 通道；``None`` 表示读取
                :data:`~ui.mica.source.ENV_DXGI` 环境变量。
            timeout_ms: 覆盖默认任务超时（毫秒）。
            grid_size: 显式网格尺寸；``None`` 表示由 ``request.window_rect``
                推导。拖动期偏移采样必须传入与常规烘焙同密度的值，见
                :func:`ui.mica.engine.bake_with_grid`。

        Returns:
            :class:`~ui.mica.engine.BakedField`；GPU 不可用时返回 ``None``。
        """
        job = _Job(
            request=request,
            desktop=source.info,
            fallback_rgb=_solid_rgb_for(source, request.dark),
            fallback_pixels=source.pixels if source.pixels.size else None,
            allow_dxgi=dxgi_enabled() if allow_dxgi is None else bool(allow_dxgi),
            grid_size=grid_size,
        )

        with self._submit_lock:
            if self._disabled_reason or self._stuck:
                return None
            self._queue.put(job)

        timeout = (self._job_timeout_ms if timeout_ms is None else float(timeout_ms)) / 1000.0
        if not job.event.wait(timeout):
            self._mark_stuck()
            return None

        if job.error is not None or job.result is None:
            self._note_failure(job.error)
            return None

        self._note_success(job)
        return job.result

    def invalidate_canvas(self) -> None:
        """强制下一个任务重建画布（壁纸或显示器布局已变化但指纹未变时使用）。"""
        with self._state_lock:
            self._invalidate_pending = True

    def stats(self) -> GpuStats:
        """读取观测快照。"""
        with self._state_lock:
            info = self._info
            return GpuStats(
                available=_mr is not None and bool(_mr.is_available()),
                enabled=not (self._disabled_reason or self._stuck),
                disabled_reason=self._disabled_reason,
                adapter=getattr(info, "adapter", "") or "",
                feature_level=getattr(info, "feature_level_text", "") or "",
                use_warp=bool(getattr(info, "use_warp", False)),
                dxgi_available=getattr(info, "dxgi_available", None),
                canvas_builds=self._canvas_builds,
                bakes=self._bakes,
                failures=self._failures,
                last_canvas_ms=self._last_canvas_ms,
                last_bake_ms=self._last_bake_ms,
                last_backend=self._last_backend,
            )

    def dispose(self) -> None:
        """停止工作线程并释放 GPU 资源（幂等）。

        线程卡在原生调用里时会在 :data:`DISPOSE_JOIN_MS` 后放弃等待 —— 守护
        线程不会阻止进程退出，但本次进程生命周期内 GPU 后端将保持停用。
        """
        with self._submit_lock:
            if not self._thread.is_alive():
                return
            self._queue.put(None)

        self._thread.join(timeout=DISPOSE_JOIN_MS / 1000.0)
        if self._thread.is_alive():
            with self._state_lock:
                self._stuck = True
                self._disabled_reason = "工作线程无响应，已放弃等待"
            _LOG.warning("Mica GPU 工作线程未能在 %.0f ms 内退出", DISPOSE_JOIN_MS)

    # -- 计数与封禁 -------------------------------------------------------

    def _note_success(self, job: _Job) -> None:
        """记录一次成功（重置连续失败计数）。"""
        with self._state_lock:
            self._failures = 0
            self._bakes += 1
            if job.canvas_ms > 0.0 or job.canvas_backend:
                self._canvas_builds += 1
                self._last_canvas_ms = job.canvas_ms
            self._last_backend = job.canvas_backend or self._last_backend
            self._last_bake_ms = float(
                getattr(job.result, "duration_ms", 0.0) or 0.0
            )
            if job.info is not None:
                self._info = job.info

    def _note_failure(self, error: Optional[BaseException]) -> None:
        """记录一次失败，达到阈值即封禁。"""
        with self._state_lock:
            self._failures += 1
            if self._failures >= MAX_CONSECUTIVE_FAILURES and not self._disabled_reason:
                self._disabled_reason = (
                    f"连续 {self._failures} 次失败，最后错误："
                    f"{type(error).__name__ if error else '未知'}: {error}"
                )
        _LOG.debug(
            "Mica GPU 烘焙失败（%d/%d）：%s",
            self._failures, MAX_CONSECUTIVE_FAILURES, error,
        )

    def _mark_stuck(self) -> None:
        """标记工作线程卡死并永久停用。"""
        with self._state_lock:
            if self._stuck:
                return
            self._stuck = True
            self._disabled_reason = (
                f"任务超过 {self._job_timeout_ms:.0f} ms 未返回，后端已停用"
            )
        _LOG.warning("Mica GPU 任务超时，后端已停用：%s", self._disabled_reason)

    # -- 工作线程 ---------------------------------------------------------

    def _loop(self) -> None:
        """工作线程主循环；``None`` 哨兵表示退出。"""
        try:
            while True:
                job = self._queue.get()
                if job is None:
                    return
                try:
                    self._run(job)
                except BaseException as exc:  # noqa: BLE001 - 必须回传给调用方
                    job.error = exc
                finally:
                    job.event.set()
        finally:
            self._close_context()

    def _run(self, job: _Job) -> None:
        """在工作线程上完成「确保上下文 → 确保画布 → 烘焙」。

        Args:
            job: 待执行任务。

        Raises:
            MicaRenderError: 任一原生调用失败。
        """
        if _mr is None:
            raise RuntimeError(f"mica_render 桥接层不可用：{_IMPORT_ERROR}")

        if self._recreate_pending or self._ctx is None:
            self._close_context()
            self._ctx = _mr.MicaRenderContext(allow_warp=self._allow_warp)
            self._recreate_pending = False
            self._canvas_signature = None
            job.info = self._ctx.device_info()
            _LOG.debug(
                "Mica GPU 上下文就绪：adapter=%s feature_level=%s warp=%s",
                job.info.adapter, job.info.feature_level_text, job.info.use_warp,
            )

        try:
            job.canvas_ms, job.canvas_backend = self._ensure_canvas(job)
            job.result = self._bake_field(job)
        except _mr.MicaRenderError as exc:
            if exc.fatal:
                # 设备丢失通常在重建后可恢复；标记后下一个任务会重建上下文。
                self._recreate_pending = True
                _LOG.warning("Mica GPU 设备失效，下次任务将重建上下文：%s", exc)
            raise

    def _ensure_canvas(self, job: _Job) -> Tuple[float, str]:
        """按需重建画布；命中缓存时零成本返回。

        Args:
            job: 当前任务。

        Returns:
            ``(耗时毫秒, 画布来源)``。命中缓存时耗时为 ``0.0``。
        """
        assert self._ctx is not None  # noqa: S101 - 由 _run 保证
        ctx = self._ctx
        info = job.desktop
        signature = job.request.source_signature

        if not self._take_invalidate() and self._canvas_signature == signature:
            return 0.0, self._last_backend

        started = time.perf_counter()
        ctx.set_virtual_desktop(info.virtual_rect, CANVAS_MAX_LONG)
        self._canvas_signature = None

        # 1) 壁纸文件：WIC 解码 + Direct2D 摆放。最快且最贴近真实 Mica 语义。
        if any(m.wallpaper_path for m in info.monitors):
            layouts = [
                _mr.MonitorLayout(
                    rect=m.rect,
                    position=info.position,
                    background_rgb=info.background_rgb,
                    wallpaper=m.wallpaper_path,
                )
                for m in info.monitors
            ]
            try:
                ctx.build_canvas_from_wallpapers(layouts, job.fallback_rgb)
                self._canvas_signature = signature
                return _elapsed_ms(started), "wallpaper"
            except _mr.MicaRenderError as exc:
                _LOG.debug("GPU 壁纸通道失败，尝试降级：%s", exc)

        # 2) DXGI 桌面复制：仅在显式开启时尝试（静态桌面必然超时，见模块文档）。
        if job.allow_dxgi:
            try:
                ctx.build_canvas_from_dxgi(DXGI_TIMEOUT_MS)
                self._canvas_signature = signature
                return _elapsed_ms(started), "dxgi"
            except _mr.MicaRenderError as exc:
                _LOG.debug("GPU DXGI 通道失败，尝试降级：%s", exc)

        # 3) 复用 CPU 侧已解码的画布：解码成功只是 GPU 摆放失败时的最优兜底。
        pixels = job.fallback_pixels
        if pixels is not None and pixels.size:
            try:
                ctx.build_canvas_from_memory(np.ascontiguousarray(pixels, dtype=np.uint8))
                self._canvas_signature = signature
                return _elapsed_ms(started), "memory"
            except _mr.MicaRenderError as exc:
                _LOG.debug("GPU 内存通道失败，尝试降级：%s", exc)

        # 4) 纯色：必然成功，保证 bake 永远有画布可用。
        ctx.build_canvas_solid(job.fallback_rgb)
        self._canvas_signature = signature
        return _elapsed_ms(started), "solid"

    def _bake_field(self, job: _Job) -> BakedField:
        """把 :class:`BakeRequest` 翻译成原生参数并执行烘焙。

        参数映射与 :func:`ui.mica.engine.bake` **逐字段共用同一套推导**
        （网格尺寸、扩边、σ、增益、色度上限、门控常量），这是两条管线结果
        一致的前提。

        Args:
            job: 当前任务。

        Returns:
            :class:`~ui.mica.engine.BakedField`。

        Raises:
            MicaRenderError: 原生调用失败或输出形状不符。
        """
        assert self._ctx is not None  # noqa: S101 - 由 _run 保证
        request = job.request
        win_w, win_h = request.size
        if job.grid_size is None:
            grid_w, grid_h = bake_grid_size(win_w, win_h)
        else:
            grid_w, grid_h = (max(1, int(v)) for v in job.grid_size)
        engine_params = request.params.to_engine(request.dark)
        margin = margin_px(grid_w, grid_h, engine_params.sigma)
        g1 = engine_params.g1()

        params = _mr.BakeParams(
            window_rect=tuple(int(v) for v in request.window_rect),  # type: ignore[arg-type]
            grid_size=(grid_w, grid_h),
            margin=margin,
            sigma=float(engine_params.sigma),
            gain=float(engine_params.gain),
            chroma_cap=float(engine_params.chroma_cap()),
            alpha=float(engine_params.alpha),
            l_ref=float(tint.g1_oklab_l(g1)),
            g1_rgb=g1,
            gate_lo=float(tint.CHROMA_LUMA_GATE_LO),
            gate_hi=float(tint.CHROMA_LUMA_GATE_HI),
            gate_feather=float(tint.CHROMA_LUMA_GATE_FEATHER),
            dither=True,
        )
        image, meta = self._ctx.bake(params)
        if image.shape[0] != grid_h or image.shape[1] != grid_w:
            raise _mr.MicaRenderError(
                _mr.MICA_ERR_INTERNAL,
                f"输出形状 {image.shape[:2]} 与期望 {(grid_h, grid_w)} 不符",
                "mica_bake",
            )

        return BakedField(
            image=image,
            request=request,
            grid_size=(grid_w, grid_h),
            sample_rect=meta.sample_rect,
            margin=margin,
            backend=f"gpu:{meta.backend}",
            duration_ms=meta.duration_ms,
            work_size=meta.pad_size,
        )

    def _take_invalidate(self) -> bool:
        """取出并清除「强制重建画布」标志（工作线程专用）。"""
        with self._state_lock:
            pending = self._invalidate_pending
            self._invalidate_pending = False
        return pending

    def _close_context(self) -> None:
        """关闭上下文（仅在工作线程调用）。"""
        ctx = self._ctx
        self._ctx = None
        self._canvas_signature = None
        if ctx is None:
            return
        try:
            ctx.close()
        except Exception as exc:  # pragma: no cover - 析构路径防御
            _LOG.debug("关闭 Mica GPU 上下文异常：%s", exc)


# ---------------------------------------------------------------------------
# 模块级辅助
# ---------------------------------------------------------------------------


def _elapsed_ms(started: float) -> float:
    """把 :func:`time.perf_counter` 起点换算为耗时毫秒。"""
    return (time.perf_counter() - started) * 1000.0


def _solid_rgb_for(source: WallpaperSource, dark: bool) -> Tuple[int, int, int]:
    """计算纯色兜底色。

    优先沿用 :class:`~ui.mica.source.DesktopInfo.background_rgb`（用户确实设置了
    纯色桌面时它的色度理应渗入 Mica），否则取主题 G1 基色。

    Args:
        source: 壁纸源画布。
        dark: 是否深色模式。

    Returns:
        ``(r, g, b)``。
    """
    from .config import G1_DARK, G1_LIGHT

    bg = tuple(int(v) & 0xFF for v in source.info.background_rgb[:3])
    if bg == (0, 0, 0):
        return G1_DARK if dark else G1_LIGHT
    return bg  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# 进程级单例
# ---------------------------------------------------------------------------

_SINGLETON_LOCK = threading.Lock()
_RENDERER: Optional[GpuRenderer] = None
_DISABLED: bool = False


def gpu_available() -> bool:
    """GPU 后端在**静态层面**是否可用（只判断原生库能否加载）。

    Returns:
        库存在且 ABI 匹配时 ``True``；不代表一定能创建 D3D11 设备。
    """
    return _mr is not None and bool(_mr.is_available())


def load_error() -> str:
    """原生库不可用的原因；可用时为空串。"""
    if _mr is None:
        return f"桥接层导入失败：{_IMPORT_ERROR}"
    return _mr.load_error()


def get_gpu_renderer() -> Optional[GpuRenderer]:
    """获取进程级共享渲染器；不可用或已封禁时返回 ``None``。

    Returns:
        :class:`GpuRenderer` 或 ``None``。
    """
    global _RENDERER, _DISABLED

    if _DISABLED:
        return None
    with _SINGLETON_LOCK:
        if _RENDERER is not None:
            return _RENDERER
        if _DISABLED:
            return None
        if not gpu_available():
            _DISABLED = True
            _LOG.info("Mica GPU 后端不可用：%s", load_error())
            return None
        try:
            _RENDERER = GpuRenderer()
        except Exception as exc:  # pragma: no cover - 线程启动失败
            _DISABLED = True
            _LOG.warning("Mica GPU 渲染器启动失败：%s", exc)
            return None
        return _RENDERER


def shutdown_gpu_renderer() -> None:
    """释放进程级共享渲染器（应用退出 / 设置关闭 Mica 时调用）。"""
    global _RENDERER, _DISABLED

    with _SINGLETON_LOCK:
        renderer = _RENDERER
        _RENDERER = None
        _DISABLED = False
    if renderer is not None:
        renderer.dispose()


def gpu_bake(
    request: BakeRequest,
    source: WallpaperSource,
    *,
    allow_dxgi: Optional[bool] = None,
    timeout_ms: Optional[float] = None,
    grid_size: Optional[Tuple[int, int]] = None,
) -> Optional[BakedField]:
    """优先 GPU 烘焙，失败自动退回 CPU 管线。

    这是 :mod:`ui.mica.material` 应当使用的唯一烘焙入口。两条管线的输入参数
    完全同源，因此降级在视觉上不可察觉（仅耗时不同）。

    Args:
        request: 烘焙输入快照。
        source: 壁纸源画布。
        allow_dxgi: 是否允许 DXGI 通道；``None`` 表示读取环境变量。
        timeout_ms: GPU 任务等待上限（毫秒）。
        grid_size: 显式网格尺寸；``None`` 表示由 ``request.window_rect`` 推导。

    Returns:
        :class:`~ui.mica.engine.BakedField`；两条管线都失败时返回 ``None``。
    """
    renderer = get_gpu_renderer()
    if renderer is not None:
        field = renderer.bake(
            request,
            source,
            allow_dxgi=allow_dxgi,
            timeout_ms=timeout_ms,
            grid_size=grid_size,
        )
        if field is not None:
            return field
        _LOG.debug("GPU 烘焙失败，降级到 CPU 管线")

    try:
        if grid_size is None:
            return cpu_bake(request, source)
        return cpu_bake_with_grid(request, source, grid_size)
    except Exception as exc:  # pragma: no cover - 防御性兜底
        _LOG.warning("Mica CPU 烘焙失败：%s", exc)
        return None


def gpu_stats() -> GpuStats:
    """读取进程级渲染器的观测快照；不存在时返回 ``available=False`` 的空快照。"""
    renderer = _RENDERER
    if renderer is None:
        return GpuStats(
            available=gpu_available(),
            enabled=False,
            disabled_reason=load_error() if not gpu_available() else "尚未初始化",
            adapter="",
            feature_level="",
            use_warp=False,
            dxgi_available=None,
            canvas_builds=0,
            bakes=0,
            failures=0,
            last_canvas_ms=0.0,
            last_bake_ms=0.0,
            last_backend="",
        )
    return renderer.stats()


__all__ = [
    "GpuRenderer",
    "GpuStats",
    "JOB_TIMEOUT_MS",
    "MAX_CONSECUTIVE_FAILURES",
    "WORKER_THREAD_NAME",
    "get_gpu_renderer",
    "gpu_available",
    "gpu_bake",
    "gpu_stats",
    "load_error",
    "shutdown_gpu_renderer",
]
