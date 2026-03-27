#!/usr/bin/env python3
# -*- coding: utf-8 -*-

r"""
实际测试 Rust 视频缩略图链路是否启用硬件加速。

功能：
1. 递归扫描目标目录中的视频文件
2. 直接调用 RustThumbnailBridge.generate_jpg()
3. 统计每个文件的处理耗时与成功情况
4. 若系统存在 nvidia-smi，则采样 GPU 利用率供参考

默认测试目录：
E:\DFTP\飞院空镜头\素材拷贝
"""

from __future__ import annotations

import argparse
import ctypes
import os
import shutil
import statistics
import subprocess
import sys
import threading
import time
from ctypes import POINTER, Structure, c_char_p, c_int, c_size_t, c_uint8, c_uint32
from pathlib import Path
from typing import List, Dict, Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class NativeThumbnailResult(Structure):
    _fields_ = [
        ("status", c_int),
        ("width", c_uint32),
        ("height", c_uint32),
        ("channels", c_uint8),
        ("len", c_size_t),
        ("data", POINTER(c_uint8)),
        ("message", c_char_p),
    ]


class LocalRustThumbnailBridge:
    def __init__(self):
        self._dll = None
        self._available = False
        self._supports_jpg = False
        self._dll_directory_handle = None
        self._preloaded_runtime_dlls = []
        self._load()

    @property
    def available(self) -> bool:
        return self._available and self._dll is not None

    def _native_runtime_dir(self) -> Path:
        return PROJECT_ROOT / "freeassetfilter" / "core" / "native"

    def _candidate_paths(self) -> List[Path]:
        core_dir = PROJECT_ROOT / "freeassetfilter" / "core"
        return [
            core_dir / "native" / "thumbnail_generator.dll",
            core_dir / "native" / "thumbnail_rust" / "target" / "release" / "thumbnail_generator.dll",
        ]

    def _prepare_local_runtime(self):
        runtime_dir = self._native_runtime_dir()
        if not runtime_dir.exists():
            return

        if os.name == "nt" and hasattr(os, "add_dll_directory"):
            try:
                self._dll_directory_handle = os.add_dll_directory(str(runtime_dir))
            except Exception:
                pass

        for name in ["opencv_world4120.dll", "opencv_videoio_ffmpeg4130_64.dll"]:
            dll_path = runtime_dir / name
            if not dll_path.exists():
                continue
            try:
                loaded = ctypes.WinDLL(str(dll_path)) if os.name == "nt" else ctypes.CDLL(str(dll_path))
                self._preloaded_runtime_dlls.append(loaded)
            except Exception:
                pass

    def _load(self):
        self._prepare_local_runtime()
        for path in self._candidate_paths():
            if not path.exists():
                continue
            try:
                dll = ctypes.CDLL(str(path))
                self._bind(dll)
                self._dll = dll
                self._available = True
                return
            except Exception:
                continue
        self._available = False
        self._dll = None

    def _bind(self, dll):
        dll.native_generate_thumbnail_jpg.argtypes = [c_char_p, c_int, c_int]
        dll.native_generate_thumbnail_jpg.restype = NativeThumbnailResult

        dll.native_set_cache_limit.argtypes = [c_size_t]
        dll.native_set_cache_limit.restype = c_int

        dll.native_free_buffer.argtypes = [POINTER(c_uint8), c_size_t]
        dll.native_free_buffer.restype = None

        self._supports_jpg = True

    def set_cache_limit(self, max_bytes: int) -> bool:
        if not self.available:
            return False
        try:
            return self._dll.native_set_cache_limit(max(1, int(max_bytes))) == 0
        except Exception:
            return False

    def generate_jpg(self, file_path: str, width: int, height: int) -> bytes | None:
        if not self.available or not self._supports_jpg:
            return None
        if not file_path or not os.path.exists(file_path):
            return None
        try:
            result = self._dll.native_generate_thumbnail_jpg(file_path.encode("utf-8"), int(width), int(height))
            if result.status != 0 or not result.data or result.len <= 0:
                return None
            jpg_bytes = ctypes.string_at(result.data, result.len)
            self._dll.native_free_buffer(result.data, result.len)
            return jpg_bytes
        except Exception:
            return None


RustThumbnailBridge = LocalRustThumbnailBridge

VIDEO_EXTS = {
    ".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".webm",
    ".m4v", ".mpeg", ".mpg", ".mxf", ".3gp"
}


def find_video_files(root: Path) -> List[Path]:
    files: List[Path] = []
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            path = Path(dirpath) / name
            if path.suffix.lower() in VIDEO_EXTS:
                files.append(path)
    return files


class NvidiaSampler:
    def __init__(self, interval: float = 0.5):
        self.interval = interval
        self.samples: List[Dict[str, int]] = []
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.available = shutil.which("nvidia-smi") is not None

    def _query_once(self) -> None:
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu,utilization.memory",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                check=False,
            )
            if result.returncode != 0:
                return

            lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            for line in lines:
                parts = [p.strip() for p in line.split(",")]
                if len(parts) < 2:
                    continue
                gpu_util = int(parts[0]) if parts[0].isdigit() else 0
                mem_util = int(parts[1]) if parts[1].isdigit() else 0
                self.samples.append(
                    {
                        "ts": int(time.time() * 1000),
                        "gpu_util": gpu_util,
                        "mem_util": mem_util,
                    }
                )
        except Exception:
            pass

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._query_once()
            self._stop_event.wait(self.interval)

    def start(self) -> None:
        if not self.available:
            return
        self._thread = threading.Thread(target=self._run, name="nvidia-sampler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self.available:
            return
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)

    def summary(self) -> Dict[str, Any]:
        if not self.samples:
            return {
                "available": self.available,
                "sample_count": 0,
                "avg_gpu_util": 0,
                "peak_gpu_util": 0,
                "avg_mem_util": 0,
                "peak_mem_util": 0,
            }

        gpu_values = [s["gpu_util"] for s in self.samples]
        mem_values = [s["mem_util"] for s in self.samples]
        return {
            "available": self.available,
            "sample_count": len(self.samples),
            "avg_gpu_util": round(sum(gpu_values) / len(gpu_values), 2),
            "peak_gpu_util": max(gpu_values),
            "avg_mem_util": round(sum(mem_values) / len(mem_values), 2),
            "peak_mem_util": max(mem_values),
        }


def run_test(target_dir: Path, limit: int | None, width: int, height: int) -> int:
    bridge = RustThumbnailBridge()
    if not bridge.available:
        print("RustThumbnailBridge 不可用，测试终止")
        return 2

    files = find_video_files(target_dir)
    if not files:
        print(f"未在目录中找到视频文件: {target_dir}")
        return 1

    files.sort()
    if limit is not None and limit > 0:
        files = files[:limit]

    print(f"目标目录: {target_dir}")
    print(f"视频数量: {len(files)}")
    print(f"缩略图尺寸: {width}x{height}")
    print("-" * 80)

    sampler = NvidiaSampler(interval=0.5)
    if sampler.available:
        print("检测到 nvidia-smi，将采样 GPU 利用率")
    else:
        print("未检测到 nvidia-smi，仅执行耗时测试")

    bridge.set_cache_limit(200 * 1024 * 1024)
    sampler.start()

    results: List[Dict[str, Any]] = []
    batch_start = time.perf_counter()

    try:
        for index, file_path in enumerate(files, start=1):
            start = time.perf_counter()
            ok = False
            error_msg = ""

            try:
                jpg_bytes = bridge.generate_jpg(str(file_path), width, height)
                ok = bool(jpg_bytes)
                if not ok:
                    error_msg = "generate_jpg 返回空结果"
            except Exception as exc:
                error_msg = repr(exc)

            elapsed = time.perf_counter() - start
            results.append(
                {
                    "index": index,
                    "path": str(file_path),
                    "ok": ok,
                    "elapsed": elapsed,
                    "size_mb": round(file_path.stat().st_size / (1024 * 1024), 2),
                    "error": error_msg,
                }
            )

            status = "OK" if ok else "FAIL"
            print(f"[{index:03d}/{len(files):03d}] {status:<4} {elapsed:>7.3f}s  {file_path}")
            if error_msg:
                print(f"      错误: {error_msg}")
    finally:
        sampler.stop()

    total_elapsed = time.perf_counter() - batch_start
    success_results = [r for r in results if r["ok"]]
    failed_results = [r for r in results if not r["ok"]]
    elapsed_values = [r["elapsed"] for r in success_results] or [0.0]
    gpu_summary = sampler.summary()

    print("-" * 80)
    print("测试汇总")
    print(f"总耗时: {total_elapsed:.3f}s")
    print(f"成功数: {len(success_results)}")
    print(f"失败数: {len(failed_results)}")
    print(f"平均单文件耗时: {statistics.mean(elapsed_values):.3f}s")
    print(f"中位数耗时: {statistics.median(elapsed_values):.3f}s")
    print(f"最大耗时: {max(elapsed_values):.3f}s")
    print(f"最小耗时: {min(elapsed_values):.3f}s")

    if gpu_summary["available"]:
        print("GPU 采样汇总（nvidia-smi）")
        print(f"采样点数: {gpu_summary['sample_count']}")
        print(f"平均 GPU 利用率: {gpu_summary['avg_gpu_util']}%")
        print(f"峰值 GPU 利用率: {gpu_summary['peak_gpu_util']}%")
        print(f"平均显存控制器利用率: {gpu_summary['avg_mem_util']}%")
        print(f"峰值显存控制器利用率: {gpu_summary['peak_mem_util']}%")
    else:
        print("GPU 采样汇总：不可用（未检测到 nvidia-smi）")

    if failed_results:
        print("-" * 80)
        print("失败样本（最多前 10 条）")
        for item in failed_results[:10]:
            print(f"- {item['path']}")
            if item["error"]:
                print(f"  {item['error']}")

    return 0 if success_results else 3


def main() -> int:
    parser = argparse.ArgumentParser(description="测试 Rust 视频缩略图链路与 GPU 利用率")
    parser.add_argument(
        "target_dir",
        nargs="?",
        default=r"E:\DFTP\飞院空镜头\素材拷贝",
        help="目标目录，默认使用实际测试目录",
    )
    parser.add_argument("--limit", type=int, default=20, help="最多测试多少个视频，默认 20")
    parser.add_argument("--width", type=int, default=128, help="缩略图宽度")
    parser.add_argument("--height", type=int, default=128, help="缩略图高度")
    args = parser.parse_args()

    target_dir = Path(args.target_dir)
    if not target_dir.exists():
        print(f"目录不存在: {target_dir}")
        return 1

    return run_test(target_dir, args.limit, args.width, args.height)


if __name__ == "__main__":
    raise SystemExit(main())
