# -*- coding: utf-8 -*-
"""Rust 批量缩略图并发压测（thumbnail-rust-refactor todo 4，Design Revision 5）。

计划裁决：**保留 rayon 1.10（静态链接进 cdylib，无外部 DLL），不再自研线程池**。
本文件验证批量路径 ``native_generate_batch_jpg``（桥方法 ``generate_jpg_batch``）
下的 rayon 并发正确性与全局线程池单例语义：

* **并发正确性**：16 路由 ``ThreadPoolExecutor`` 并发发起 ``generate_jpg_batch``，
  每路 4 个真实 PNG 文件。断言每路逐项字节与串行基准**完全一致**（JPEG 编码
  确定性），证明并发调度无数据竞争 / 缓冲串改；
* **ctypes 层 status==0**：直接调用 ``native_generate_batch_jpg`` 校验 batch 级
  ``status == 0`` 且逐项 ``item.status == 0``；
* **全局单例语义（侧面观测）**：rayon-core 全局注册表由 ``THE_REGISTRY_SET``
  ``call_once`` 实现、进程内仅初始化一次，worker 线程上限 = ``available_parallelism``
  （≈ 逻辑 CPU 数，本机 24）。用 psutil 采样进程 OS 线程数观测：压测期间峰值与
  回落值均为「基线 + rayon worker(≤池上限) + 执行器线程(16) + 抖动」量级，
  远小于按调用方独立建池时的理论爆炸量「并发数 × CPU 数」（16×24≈384）。
  若 psutil 不可用则跳过线程数观测——并发正确性断言由首个用例独立覆盖。

不依赖任何外部进程；JPEG 编码走 Rust 原生内部解码，无 ffmpeg/7z 子进程调用。
"""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, List, Optional, Tuple

import pytest
from PIL import Image

from freeassetfilter.core.native.bridges.rust_thumbnail_bridge import RustThumbnailBridge

pytestmark = [pytest.mark.unit, pytest.mark.rust]

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

CONCURRENCY: int = 16  # 并发调用方数量
FILES_PER_CALL: int = 4  # 每个调用包含的路径数（3-5 区间内）
ROUNDS: int = 3  # 线程数观测的压测轮数


def _process_thread_count() -> Optional[int]:
    """当前进程的 OS 线程数（psutil 可用时）。"""
    if _PSUTIL_AVAILABLE:
        assert psutil is not None
        return len(psutil.Process().threads())
    return None


def _native_batch_statuses(
    inst: RustThumbnailBridge,
    paths: List[str],
    width: int,
    height: int,
) -> Tuple[int, List[int]]:
    """ctypes 层直调 ``native_generate_batch_jpg``，返回 ``(batch.status, 逐项 status)``。"""
    import ctypes
    from ctypes import c_char_p

    dll = inst._dll  # noqa: SLF001  —— 测试直连底层以校验 status 字段
    encoded = [(p.encode("utf-8") if p else None) for p in paths]
    arr_type = c_char_p * len(encoded)
    c_paths = arr_type(*encoded)
    batch = dll.native_generate_batch_jpg(
        c_paths, int(len(encoded)), int(width), int(height)
    )
    try:
        item_statuses = [int(batch.results[i].status) for i in range(batch.count)]
        return int(batch.status), item_statuses
    finally:
        dll.native_free_batch_result(ctypes.byref(batch))


# =============================================================================
# 数据工厂
# =============================================================================
@pytest.fixture()
def _png_batch(tmp_path: Any) -> List[str]:
    """生成 4 个不同颜色 100x80 PNG 文件，返回绝对路径列表。"""
    palette = [(128, 64, 200), (200, 64, 128), (64, 128, 200), (128, 200, 64)]
    paths: List[str] = []
    for idx, color in enumerate(palette):
        path = tmp_path / f"sample_{idx}.png"
        Image.new("RGB", (100, 80), color).save(str(path), format="PNG")
        paths.append(str(path))
    return paths


# =============================================================================
# 并发正确性（结果与串行一致）
# =============================================================================
class TestBatchConcurrencyCorrectness:
    """16 路并发 ``generate_jpg_batch`` 的正确性。"""

    def test_16_concurrent_batches_match_serial(self, _png_batch: List[str]) -> None:
        """Given 4 个真实 PNG；When 16 路并发生成 32x32 JPG；Then 全部与串行基准逐字节一致。"""
        inst = RustThumbnailBridge()
        width, height = 32, 32

        # Arrange: 串行基准
        serial: List[Optional[bytes]] = inst.generate_jpg_batch(_png_batch, width, height)
        assert all(blob is not None for blob in serial)

        # Act: 16 路并发
        with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
            futures = [
                executor.submit(inst.generate_jpg_batch, _png_batch, width, height)
                for _ in range(CONCURRENCY)
            ]
            results: List[List[Optional[bytes]]] = [
                f.result(timeout=60) for f in futures
            ]

        # Assert: 每路每项均成功且与串行一致
        for idx, batch in enumerate(results):
            assert len(batch) == len(_png_batch), f"并发路 {idx} 结果长度不符"
            for j, blob in enumerate(batch):
                assert blob is not None, f"并发路 {idx} 第 {j} 项为 None（Rust 内单项目 status!=0）"
                assert blob[:2] == b"\xff\xd8", f"并发路 {idx} 第 {j} 项非 JPEG 魔数"
                assert blob == serial[j], f"并发路 {idx} 第 {j} 项与串行基准不一致"

    def test_native_batch_status_zero_under_concurrency(self, _png_batch: List[str]) -> None:
        """Given 4 个真实 PNG；When 16 路并发直调 ``native_generate_batch_jpg``；
        Then 每路 batch.status 与逐项 status 均为 0。"""
        inst = RustThumbnailBridge()

        def call() -> Tuple[int, List[int]]:
            return _native_batch_statuses(inst, _png_batch, 32, 32)

        # Arrange: 串行基准（DLL 加载确认）
        serial_status, serial_items = call()
        assert serial_status == 0
        assert serial_items == [0] * len(_png_batch)

        # Act: 16 路并发直调
        with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
            futures = [executor.submit(call) for _ in range(CONCURRENCY)]
            outcomes = [f.result(timeout=60) for f in futures]

        # Assert: 全部 status==0
        for batch_status, item_statuses in outcomes:
            assert batch_status == 0, f"batch.status={batch_status}，预期 0"
            assert item_statuses == [0] * len(_png_batch), "存在单项目 status!=0"


# =============================================================================
# 全局线程池单例语义（侧面观测：进程线程数不随调用方数量爆炸）
# =============================================================================
class TestSharedGlobalPoolThreadBounded:
    """rayon 全局池为进程级单例：worker 线程数与 CPU 数相当，不随并发调用方线性增长。"""

    def test_worker_threads_do_not_explode_with_callers(self, _png_batch: List[str]) -> None:
        """Given 全局池共享语义；When 3 轮 × 16 路并发压测；Then 峰值与回落值均
        远小于「并发数 × 池上限」（独立建池时的理论爆炸量 384）。

        观测方式：psutil 采样当前进程（Rust DLL 经 ctypes 加载于本进程）的 OS
        线程数。波动预算 = 池上限(_POOL_CAP) + 执行器线程(CONCURRENCY) + 抖动(8)。
        """
        if not _PSUTIL_AVAILABLE:
            pytest.skip(
                "psutil 不可用，无法采样线程数；"
                "并发正确性已由 TestBatchConcurrencyCorrectness 覆盖"
            )
        assert psutil is not None
        proc = psutil.Process()

        inst = RustThumbnailBridge()
        width, height = 32, 32

        # Arrange: 基线与预热（预热触发 rayon 全局池惰性初始化）
        baseline = len(proc.threads())
        inst.generate_jpg_batch(_png_batch, width, height)
        time.sleep(0.15)

        budget = _POOL_CAP + CONCURRENCY + 8  # rayon worker + 执行器线程 + 抖动余量

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

        # Act: 3 轮 × 16 路并发压测
        def one_call(paths: List[str]) -> None:
            inst.generate_jpg_batch(paths, width, height)

        try:
            with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
                for _ in range(ROUNDS):
                    list(executor.map(one_call, [_png_batch] * CONCURRENCY))
        finally:
            sampler.stop()
            sampler_thread.join(timeout=2)

        time.sleep(0.3)  # 执行器线程退出、rayon worker 转入 parked 后回落
        settled = len(proc.threads())

        # Assert: 峰值与回落值均受预算约束
        assert sampler.peak <= baseline + budget, (
            f"压测峰值线程数增量 {sampler.peak - baseline} 超预算 {budget}："
            f"CPUS={_CPU_COUNT}, 池上限≈{_POOL_CAP}, 并发={CONCURRENCY}。"
            f"若按调用方独立建池，理论爆炸量应为 {CONCURRENCY * _POOL_CAP}"
        )
        assert settled <= baseline + budget, (
            f"压测后线程数增量 {settled - baseline} 超预算 {budget}，疑似线程泄漏"
        )