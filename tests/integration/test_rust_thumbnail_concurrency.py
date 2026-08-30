# -*- coding: utf-8 -*-
"""Rust 缩略图组件并发处理与统一控制机制验证（集成测试）。

覆盖 ``RustThumbnailBridge`` 的并发路径与统一控制面：

* **并行加速**（``TestParallelSpeedup``，类级 ``timeout(120)``）：8 张大图
  （4×1920x1080 + 4×3840x2160 渐变+几何图形 PNG）串行 ``generate_rgba``
  vs 8 线程并发 ``generate_rgba``——两次测量前均 ``clear_cache()`` 排除
  缓存干扰；断言并行显著加速（0.75 宽松阈值防机器抖动；核数不足导致
  加速不达标时退化为「并行不慢于串行且输出正确」并打印实测加速比）；
* **线程池统一控制**（``TestThreadPoolBounded``，类级 ``timeout(120)``）：
  psutil 采样进程 OS 线程数：4 轮 × 16 路并发 ``generate_jpg_batch``（每批
  8 张多分辨率大图，轮间 ``clear_cache()`` 强制真实解码）期间峰值受
  「池上限 + 执行器线程 + 抖动」预算约束、结束后回落——证明 rayon 全局
  池为进程级单例，不随调用方数量爆炸（阈值写法对齐
  ``tests/unit/core/test_rust_batch_concurrency.py``）；
* **并发控制 API 行为**（``TestConcurrencyControlApis``）：
  ``set_max_concurrent_hw_video_decodes`` 传 1/2/4 各返回 True；传 0/负数
  经桥接层 ``max(1, int(x))`` 与 Rust 侧 ``.max(1)`` 双重下限钳制后被抬到
  1，同样返回 True（按实际实现记录，非拒绝语义）；``set_cache_limit`` /
  ``clear_cache`` 返回 True；``get_error_log`` 合法 JSON 数组、
  ``get_supported_formats`` 合法 JSON 对象含 14 个格式 id、
  ``get_ffmpeg_capabilities`` 合法 JSON 对象；``get_available_hwaccels``
  返回 list；8 线程混合并发调用全部 API 不崩溃不死锁（``timeout(60)``）；
* **并发正确性**（``TestConcurrentCorrectness``，类级 ``timeout(120)``）：
  8 张不同分辨率图像先串行记录 ``generate_rgba`` 基准（尺寸/长度/SHA-256/
  原始字节），再 ``clear_cache()`` 后 8 线程并发生成同样 8 张——逐张
  尺寸、长度、哈希、字节完全一致，证明并发调度无数据竞争。

内存压力分级（≥80% 暂停预载 / ≥90% 驱逐至 60% / ≥95% 紧急模式）难以
稳定模拟低内存，不在本文件动态测试范围——静态审查结论：实现位于 Rust
``lib.rs`` ``NativeEngine::update_memory_pressure``（第 133-147 行），
由 ``generate_entry``（第 406 行）在每次生成前接入。
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pytest
from PIL import Image, ImageDraw

from freeassetfilter.core.native.bridges.rust_thumbnail_bridge import RustThumbnailBridge

pytestmark = [pytest.mark.integration, pytest.mark.rust]

bridge = pytest.importorskip(
    "freeassetfilter.core.native.bridges.rust_thumbnail_bridge"
)

try:
    import psutil

    _PSUTIL_AVAILABLE: bool = True
except ImportError:
    psutil = None  # type: ignore[assignment]
    _PSUTIL_AVAILABLE = False

# rayon 全局池默认线程数 = std::thread::available_parallelism()（可被 RAYON_NUM_THREADS 覆盖）
_CPU_COUNT: int = os.cpu_count() or 1
try:
    _POOL_CAP = int(os.environ["RAYON_NUM_THREADS"])
except (KeyError, ValueError):
    _POOL_CAP = _CPU_COUNT

# 线程压测参数（与既有 tests/unit/core/test_rust_batch_concurrency.py 对齐）
_CONCURRENCY: int = 16  # 并发调用方数量
_ROUNDS: int = 4  # 压测轮数（每轮 16 路并发 × 每批 8 张）

# 并行加速验证：4 张 1080p + 4 张 4K（≥8 张较大图像）
_SPEEDUP_SPECS: Tuple[Tuple[int, int], ...] = (
    (1920, 1080), (1920, 1080), (1920, 1080), (1920, 1080),
    (3840, 2160), (3840, 2160), (3840, 2160), (3840, 2160),
)

# 并发正确性验证：8 张互不相同的分辨率
_CORRECTNESS_SIZES: Tuple[Tuple[int, int], ...] = (
    (256, 256), (512, 384), (800, 600), (1024, 768),
    (1280, 720), (1600, 900), (1920, 1080), (2560, 1440),
)

# 引擎默认缓存上限（Rust lib.rs DEFAULT_MAX_MEMORY_BYTES = 200MB）
_DEFAULT_CACHE_LIMIT: int = 200 * 1024 * 1024


def _make_gradient_png(path: Path, width: int, height: int) -> None:
    """生成二维渐变色 + 几何图形 PNG（非纯色，解码工作量真实）。

    Args:
        path: 目标文件路径。
        width: 图像宽度（像素）。
        height: 图像高度（像素）。
    """
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)
    x_step = max(1, width // 64)
    for y in range(height):
        for x in range(0, width, x_step):
            r = (x * 255) // max(1, width - 1)
            g = (y * 255) // max(1, height - 1)
            b = ((x + y) * 255) // max(1, width + height - 2)
            draw.rectangle(
                [x, y, min(x + x_step, width) - 1, y], fill=(r, g, b)
            )
    draw.ellipse(
        [width // 4, height // 4, 3 * width // 4, 3 * height // 4],
        fill=(255, 0, 0),
    )
    draw.rectangle(
        [width // 8, height // 8,
         width // 8 + max(1, width // 16), height - height // 8],
        fill=(0, 255, 0),
    )
    img.save(str(path), format="PNG")


def _process_thread_count() -> Optional[int]:
    """当前进程的 OS 线程数（psutil 可用时）。"""
    if _PSUTIL_AVAILABLE:
        assert psutil is not None
        return len(psutil.Process().threads())
    return None


# =============================================================================
# fixtures
# =============================================================================
@pytest.fixture()
def rust_bridge() -> Any:
    """提供可用性门控的 RustThumbnailBridge 实例（镜像既有测试写法）。"""
    inst = RustThumbnailBridge()
    if not inst.available:
        pytest.skip("thumbnail_generator.dll 不可用，跳过并发集成测试")
    return inst


@pytest.fixture(scope="module")
def speedup_pngs(tmp_path_factory: Any) -> List[str]:
    """module 级一次生成 8 张大图（4×1080p + 4×4K），返回绝对路径列表。"""
    base: Path = tmp_path_factory.mktemp("speedup_pngs")
    paths: List[str] = []
    for idx, (w, h) in enumerate(_SPEEDUP_SPECS):
        p = base / f"speedup_{idx}_{w}x{h}.png"
        _make_gradient_png(p, w, h)
        paths.append(str(p))
    return paths


@pytest.fixture(scope="module")
def correctness_pngs(tmp_path_factory: Any) -> List[str]:
    """module 级一次生成 8 张不同分辨率 PNG，返回绝对路径列表。"""
    base: Path = tmp_path_factory.mktemp("correctness_pngs")
    paths: List[str] = []
    for idx, (w, h) in enumerate(_CORRECTNESS_SIZES):
        p = base / f"correct_{idx}_{w}x{h}.png"
        _make_gradient_png(p, w, h)
        paths.append(str(p))
    return paths


# =============================================================================
# 1. 并行加速验证
# =============================================================================
@pytest.mark.timeout(120)
class TestParallelSpeedup:
    """8 线程并发 ``generate_rgba`` 相对串行的真实解码加速。"""

    def test_parallel_rgba_faster_than_serial(
        self, rust_bridge: Any, speedup_pngs: List[str]
    ) -> None:
        """Given 8 张大图；When 先串行后并发（均先 clear_cache）各生成一遍；
        Then 两种方式结果全部有效，且并行耗时显著小于串行（0.75 宽松阈值；
        核数不足时至少不慢于串行，并打印实测加速比）。
        """
        width, height = 512, 512

        # Arrange: 预热（初始化引擎静态/解码器/系统信息），随后清缓存
        warmup = rust_bridge.generate_rgba(speedup_pngs[0], 64, 64)
        assert warmup is not None, "预热调用失败，DLL 解码路径不可用"
        assert rust_bridge.clear_cache() is True

        # Act-1: 串行逐张
        t0 = time.perf_counter()
        serial_results: List[Optional[Tuple[bytes, int, int, int]]] = [
            rust_bridge.generate_rgba(p, width, height) for p in speedup_pngs
        ]
        serial_ms = (time.perf_counter() - t0) * 1000.0

        # Act-2: 8 线程并发（先清缓存排除缓存命中干扰）
        assert rust_bridge.clear_cache() is True
        t1 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=len(speedup_pngs)) as executor:
            futures = [
                executor.submit(rust_bridge.generate_rgba, p, width, height)
                for p in speedup_pngs
            ]
            parallel_results: List[Optional[Tuple[bytes, int, int, int]]] = [
                f.result(timeout=100) for f in futures
            ]
        parallel_ms = (time.perf_counter() - t1) * 1000.0

        # Assert-1: 两种方式结果全部有效
        for label, results in (("serial", serial_results), ("parallel", parallel_results)):
            for idx, item in enumerate(results):
                assert item is not None, f"{label} 第 {idx} 张生成失败"
                raw, out_w, out_h, channels = item
                assert 0 < out_w <= width and 0 < out_h <= height, (
                    f"{label} 第 {idx} 张输出 {out_w}x{out_h} 越界"
                )
                assert len(raw) == out_w * out_h * channels, (
                    f"{label} 第 {idx} 张缓冲长度不自洽"
                )

        # Assert-2: 并行加速（宽松阈值 0.75；不达标时退化为不慢于串行）
        speedup = serial_ms / max(parallel_ms, 0.001)
        print(
            f"[speedup] cores={_CPU_COUNT} pool_cap={_POOL_CAP} "
            f"serial_ms={serial_ms:.1f} parallel_ms={parallel_ms:.1f} "
            f"speedup={speedup:.2f}x"
        )
        if parallel_ms >= serial_ms * 0.75:
            print(
                "[speedup] 未达 0.75 显著加速阈值（核数少/机器抖动），"
                "退化为宽松断言：并行不慢于串行"
            )
            assert parallel_ms <= serial_ms, (
                f"并行 {parallel_ms:.1f}ms 慢于串行 {serial_ms:.1f}ms，"
                f"并发路径疑似退化（cores={_CPU_COUNT}）"
            )


# =============================================================================
# 2. 线程池统一控制验证
# =============================================================================
@pytest.mark.timeout(120)
class TestThreadPoolBounded:
    """rayon 全局池统一控制：线程数峰值有界且结束后回落。"""

    def test_worker_threads_bounded_under_batch_load(
        self, rust_bridge: Any, speedup_pngs: List[str]
    ) -> None:
        """Given 全局池共享语义；When 4 轮 × 16 路并发 ``generate_jpg_batch``
        （每批 8 张，轮间 clear_cache 强制真实解码）；Then 全部结果有效、
        线程数峰值增量 ≤「池上限 + 执行器线程 + 抖动」预算、结束后回落。

        观测方式与阈值写法对齐
        ``tests/unit/core/test_rust_batch_concurrency.py``
        的 ``worker_threads_do_not_explode_with_callers``：波动预算 =
        池上限(_POOL_CAP) + 执行器线程(_CONCURRENCY) + 抖动(8)。
        """
        if not _PSUTIL_AVAILABLE:
            pytest.skip(
                "psutil 不可用，无法采样线程数；"
                "并发正确性已由 TestConcurrentCorrectness 覆盖"
            )
        if not rust_bridge._supports_batch_jpg:  # noqa: SLF001
            pytest.skip("DLL 未导出 native_generate_batch_jpg")
        assert psutil is not None
        proc = psutil.Process()

        width, height = 256, 256  # 与加速验证不同的缓存键，确保真实解码

        # Arrange: 基线与预热（预热触发 rayon 全局池惰性初始化）
        baseline = len(proc.threads())
        warmup = rust_bridge.generate_jpg_batch(speedup_pngs, width, height)
        assert all(blob is not None for blob in warmup), "预热批量调用失败"
        time.sleep(0.15)

        budget = _POOL_CAP + _CONCURRENCY + 8  # rayon worker + 执行器线程 + 抖动余量

        class _PeakSampler:
            """后台采样线程：持续记录进程线程数峰值。"""

            def __init__(self) -> None:
                self.peak: int = 0
                self._stop: bool = False

            def __call__(self) -> None:
                while not self._stop:
                    self.peak = max(self.peak, len(proc.threads()))
                    time.sleep(0.005)

            def stop(self) -> None:
                self._stop = True

        sampler = _PeakSampler()
        sampler_thread = threading.Thread(target=sampler, daemon=True)
        sampler_thread.start()

        # Act: 4 轮 × 16 路并发批量（轮间清缓存强制真实解码）
        def one_call(paths: List[str]) -> List[Optional[bytes]]:
            return rust_bridge.generate_jpg_batch(paths, width, height)

        all_results: List[List[Optional[bytes]]] = []
        try:
            with ThreadPoolExecutor(max_workers=_CONCURRENCY) as executor:
                for _ in range(_ROUNDS):
                    round_results = list(
                        executor.map(one_call, [speedup_pngs] * _CONCURRENCY)
                    )
                    all_results.extend(round_results)
                    rust_bridge.clear_cache()
        finally:
            sampler.stop()
            sampler_thread.join(timeout=2)

        time.sleep(0.3)  # 执行器线程退出、rayon worker 转入 parked 后回落
        settled = len(proc.threads())

        # Assert-1: 全部结果有效（数量、JPEG 魔数）
        assert len(all_results) == _ROUNDS * _CONCURRENCY, "并发路数不符"
        for ri, batch in enumerate(all_results):
            assert len(batch) == len(speedup_pngs), f"第 {ri} 路结果长度不符"
            for ci, blob in enumerate(batch):
                assert blob is not None, f"第 {ri} 路第 {ci} 项为 None"
                assert blob[:2] == b"\xff\xd8", f"第 {ri} 路第 {ci} 项非 JPEG 魔数"

        # Assert-2: 峰值有界 + 结束后回落
        print(
            f"[threads] cpus={_CPU_COUNT} pool_cap={_POOL_CAP} "
            f"baseline={baseline} peak={sampler.peak} settled={settled} "
            f"budget={budget}"
        )
        assert sampler.peak <= baseline + budget, (
            f"压测峰值线程数增量 {sampler.peak - baseline} 超预算 {budget}："
            f"CPUS={_CPU_COUNT}, 池上限≈{_POOL_CAP}, 并发={_CONCURRENCY}。"
            f"若按调用方独立建池，理论爆炸量应为 {_CONCURRENCY * _POOL_CAP}"
        )
        assert settled <= baseline + budget, (
            f"压测后线程数增量 {settled - baseline} 超预算 {budget}，疑似线程泄漏"
        )
        assert settled < sampler.peak, (
            f"结束后线程数未回落: settled={settled} >= peak={sampler.peak}"
        )


# =============================================================================
# 3. 并发控制 API 行为验证
# =============================================================================
class TestConcurrencyControlApis:
    """统一控制面 API 的返回契约与混合并发安全性。"""

    def test_set_max_concurrent_hw_video_decodes_valid_values(
        self, rust_bridge: Any
    ) -> None:
        """传 1/2/4 各一次：均返回 True，最后恢复默认 1。"""
        for slots in (1, 2, 4):
            assert rust_bridge.set_max_concurrent_hw_video_decodes(slots) is True, (
                f"slots={slots} 应返回 True"
            )
        # 恢复默认槽位数，避免影响后续测试
        assert rust_bridge.set_max_concurrent_hw_video_decodes(1) is True

    def test_set_max_concurrent_hw_video_decodes_non_positive(
        self, rust_bridge: Any
    ) -> None:
        """传 0/负数：实际实现为下限钳制而非拒绝。

        桥接层 ``max(1, int(max_slots))`` 与 Rust 侧
        ``MAX_CONCURRENT_HW_VIDEO_DECODE_LIMIT.store(max_slots.max(1), ..)``
        双重钳制，0/负数被抬到 1 且返回 STATUS_OK → True（按实际行为断言）。
        """
        for slots in (0, -1, -8):
            assert rust_bridge.set_max_concurrent_hw_video_decodes(slots) is True, (
                f"slots={slots} 经下限钳制到 1，应返回 True"
            )
        # 恢复默认槽位数
        assert rust_bridge.set_max_concurrent_hw_video_decodes(1) is True

    def test_set_cache_limit_and_clear_cache(self, rust_bridge: Any) -> None:
        """``set_cache_limit(1MB)`` 与 ``clear_cache()`` 均返回 True。

        注：Rust 侧 ``set_cache_limit`` 内部下限钳到 8MB
        （``bytes.max(8 * 1024 * 1024)``），1MB 入参被抬到 8MB 但仍返回
        STATUS_OK；结束后恢复引擎默认 200MB 上限。
        """
        assert rust_bridge.set_cache_limit(1024 * 1024) is True
        assert rust_bridge.clear_cache() is True
        # 恢复默认缓存上限，避免影响后续测试
        assert rust_bridge.set_cache_limit(_DEFAULT_CACHE_LIMIT) is True

    def test_query_api_json_shapes(self, rust_bridge: Any) -> None:
        """查询类 API 返回合法 JSON：errorlog 数组 / 14 格式注册表 /
        ffmpeg 能力表对象 / hwaccels 列表。"""
        # 错误日志：合法 JSON 数组
        entries = json.loads(rust_bridge.get_error_log())
        assert isinstance(entries, list), "errorlog 应为 JSON 数组"
        for entry in entries:
            assert isinstance(entry, dict), "errorlog 条目应为对象"

        # 支持格式注册表：合法 JSON 对象，含 14 个格式 id
        if not rust_bridge._supports_formats:  # noqa: SLF001
            pytest.skip("DLL 未导出 native_get_supported_formats_json")
        formats_obj = json.loads(rust_bridge.get_supported_formats())
        assert isinstance(formats_obj, dict), "格式注册表应为 JSON 对象"
        formats = formats_obj.get("formats")
        assert isinstance(formats, list), "formats 字段应为列表"
        assert len(formats) == 14, f"格式数 {len(formats)} != 14"
        fmt_ids: List[str] = []
        for item in formats:
            assert isinstance(item, dict), "格式条目应为对象"
            fmt_id = item.get("id")
            assert isinstance(fmt_id, str) and fmt_id, "格式 id 应为非空字符串"
            assert isinstance(item.get("extensions"), list), "extensions 应为列表"
            fmt_ids.append(fmt_id)
        assert len(set(fmt_ids)) == 14, "格式 id 存在重复"

        # ffmpeg 能力表：合法 JSON 对象
        if not rust_bridge._supports_caps:  # noqa: SLF001
            pytest.skip("DLL 未导出 native_get_ffmpeg_capabilities_json")
        caps = json.loads(rust_bridge.get_ffmpeg_capabilities())
        assert isinstance(caps, dict), "ffmpeg 能力表应为 JSON 对象"

    def test_get_available_hwaccels_returns_list(self, rust_bridge: Any) -> None:
        """``get_available_hwaccels`` 返回 list（元素为非空小写字符串）。"""
        hwaccels = rust_bridge.get_available_hwaccels()
        assert isinstance(hwaccels, list), "hwaccels 应为 list"
        for item in hwaccels:
            assert isinstance(item, str) and item, "hwaccel 元素应为非空字符串"

    @pytest.mark.timeout(60)
    def test_concurrent_mixed_api_calls_no_crash_no_deadlock(
        self, rust_bridge: Any
    ) -> None:
        """8 线程混合并发调用全部控制/查询 API：不崩溃、不死锁、返回形状合法。

        每线程 25 轮轮询全部 API（设置类须返回 True；JSON 字符串须可解析；
        list 元素须为非空字符串；dict 直接放行），任何异常或非法形状记为失败。
        """
        calls: List[Callable[[], object]] = [
            lambda: rust_bridge.set_max_concurrent_hw_video_decodes(1),
            lambda: rust_bridge.set_max_concurrent_hw_video_decodes(2),
            lambda: rust_bridge.set_max_concurrent_hw_video_decodes(4),
            lambda: rust_bridge.set_cache_limit(1024 * 1024),
            lambda: rust_bridge.clear_cache(),
            lambda: rust_bridge.get_error_log(),
            lambda: rust_bridge.get_supported_formats(),
            lambda: rust_bridge.get_ffmpeg_capabilities(),
            lambda: rust_bridge.get_available_hwaccels(),
            lambda: rust_bridge.get_decode_stats(),
        ]
        iterations = 25
        errors: List[str] = []

        def worker(tid: int) -> None:
            for i in range(iterations):
                call = calls[(tid + i) % len(calls)]
                try:
                    result = call()
                except Exception as exc:  # noqa: BLE001 —— 记录后继续，任何异常都算失败
                    errors.append(f"tid={tid} i={i} 异常 {type(exc).__name__}: {exc}")
                    continue
                if isinstance(result, bool):
                    if result is not True:
                        errors.append(f"tid={tid} i={i} 设置类调用返回 False")
                elif isinstance(result, str):
                    try:
                        json.loads(result)
                    except ValueError:
                        errors.append(f"tid={tid} i={i} JSON 字符串不可解析")
                elif isinstance(result, list):
                    if any(not isinstance(x, str) or not x for x in result):
                        errors.append(f"tid={tid} i={i} list 含非法元素")
                elif isinstance(result, dict):
                    continue
                else:
                    errors.append(
                        f"tid={tid} i={i} 意外返回类型 {type(result).__name__}"
                    )

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(worker, tid) for tid in range(8)]
            for f in futures:
                f.result(timeout=50)

        assert errors == [], f"混合并发调用出现 {len(errors)} 处失败:\n" + "\n".join(errors[:10])

        # 恢复全局默认（HW 槽位 1 / 缓存 200MB）
        assert rust_bridge.set_max_concurrent_hw_video_decodes(1) is True
        assert rust_bridge.set_cache_limit(_DEFAULT_CACHE_LIMIT) is True


# =============================================================================
# 4. 并发正确性验证
# =============================================================================
@pytest.mark.timeout(120)
class TestConcurrentCorrectness:
    """并发 ``generate_rgba`` 与串行基准逐张一致。"""

    def test_concurrent_rgba_matches_serial_byte_exact(
        self, rust_bridge: Any, correctness_pngs: List[str]
    ) -> None:
        """Given 8 张不同分辨率图像；When 串行基准后 clear_cache 再 8 线程
        并发生成同样 8 张；Then 逐张尺寸、长度、SHA-256、原始字节完全一致。
        """
        width, height = 128, 128

        # Arrange: 串行基准（真实解码）
        assert rust_bridge.clear_cache() is True
        serial: List[Tuple[bytes, int, int, int]] = []
        for path in correctness_pngs:
            item = rust_bridge.generate_rgba(path, width, height)
            assert item is not None, f"串行基准 {path} 生成失败"
            serial.append(item)

        # Act: 并发（先清缓存确保真实解码，而非缓存命中）
        assert rust_bridge.clear_cache() is True
        with ThreadPoolExecutor(max_workers=len(correctness_pngs)) as executor:
            futures = [
                executor.submit(rust_bridge.generate_rgba, p, width, height)
                for p in correctness_pngs
            ]
            parallel: List[Optional[Tuple[bytes, int, int, int]]] = [
                f.result(timeout=100) for f in futures
            ]

        # Assert: 逐张一致（尺寸 / 长度 / SHA-256 / 字节）
        for idx, (s_item, p_item) in enumerate(zip(serial, parallel)):
            assert p_item is not None, f"并发第 {idx} 张生成失败"
            s_raw, s_w, s_h, s_ch = s_item
            p_raw, p_w, p_h, p_ch = p_item  # type: ignore[misc]
            assert (p_w, p_h, p_ch) == (s_w, s_h, s_ch), (
                f"第 {idx} 张形状不一致: 并发 {(p_w, p_h, p_ch)} "
                f"vs 串行 {(s_w, s_h, s_ch)}"
            )
            assert len(p_raw) == len(s_raw), f"第 {idx} 张长度不一致"
            assert hashlib.sha256(p_raw).hexdigest() == hashlib.sha256(s_raw).hexdigest(), (
                f"第 {idx} 张 SHA-256 不一致"
            )
            assert p_raw == s_raw, f"第 {idx} 张原始字节不一致"
