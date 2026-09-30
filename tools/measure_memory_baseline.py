"""Measure the real Windows application without importing its GUI into the sampler."""
from __future__ import annotations

import argparse
import csv
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
from typing import Any

import psutil

ROOT = Path(__file__).resolve().parents[1]
USER32 = ctypes.WinDLL("user32", use_last_error=True)
CALLBACK = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
USER32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
USER32.IsWindowVisible.argtypes = [wintypes.HWND]
USER32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
USER32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
USER32.EnumWindows.argtypes = [CALLBACK, wintypes.LPARAM]


def windows(pid: int) -> list[dict[str, Any]]:
    """Return visible top-level windows owned by the specified process."""
    result: list[dict[str, Any]] = []

    @CALLBACK
    def visit(hwnd: int, _: int) -> bool:
        owner = wintypes.DWORD()
        USER32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and USER32.IsWindowVisible(hwnd):
            rect = wintypes.RECT()
            USER32.GetWindowRect(hwnd, ctypes.byref(rect))
            result.append({"hwnd": int(hwnd), "rect": [rect.left, rect.top, rect.right, rect.bottom]})
        return True

    USER32.EnumWindows(visit, 0)
    return result


def guard() -> None:
    """Refuse to start when a live application instance already exists."""
    path = ROOT / "data/runtime_instance.json"
    if path.exists():
        try:
            pid = int(json.loads(path.read_text(encoding="utf-8"))["pid"])
            if psutil.pid_exists(pid):
                raise RuntimeError(f"Existing application PID {pid}; refusing duplicate startup")
        except (ValueError, KeyError, json.JSONDecodeError):
            pass
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            args = proc.info["cmdline"] or []
            if "freeassetfilter.app.main" in args:
                raise RuntimeError(f"Existing application PID {proc.pid}")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


def summarize(rows: list[dict[str, Any]], start: float, end: float) -> dict[str, Any]:
    """Summarize actual samples within a specified elapsed-time interval."""
    selected = [r for r in rows if start <= r["elapsed_s"] < end]
    result: dict[str, Any] = {"sample_count": len(selected)}
    for key in ("rss_mib", "private_mib", "tree_rss_mib", "tree_private_mib", "cpu_pct", "threads", "handles"):
        values = sorted(float(r[key]) for r in selected)
        if values:
            result[key] = {"median": statistics.median(values), "p95": values[min(len(values)-1, int(len(values)*.95))], "min": min(values), "max": max(values), "last": selected[-1][key]}
    return result


def run(output: Path, index: int, duration: float) -> dict[str, Any]:
    """Launch, externally sample and gracefully close one application run."""
    guard()
    prefix = output / f"run-{index}"
    rows: list[dict[str, Any]] = []
    seen_children: dict[int, list[str]] = {}
    started = time.perf_counter()
    env = os.environ.copy()
    env.pop("QT_QPA_PLATFORM", None)
    with prefix.with_suffix(".log").open("wb") as log:
        child = subprocess.Popen([sys.executable, "-m", "freeassetfilter.app.main"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        proc = psutil.Process(child.pid)
        proc.cpu_percent(None)
        visible_at: float | None = None
        window_state: list[dict[str, Any]] = []
        try:
            with prefix.with_suffix(".csv").open("w", newline="", encoding="utf-8") as fh:
                writer = None
                while time.perf_counter() - started < duration and child.poll() is None:
                    elapsed = time.perf_counter() - started
                    mem = proc.memory_info()
                    descendants = proc.children(recursive=True)
                    tree_rss, tree_private = mem.rss, mem.private
                    for item in descendants:
                        try:
                            imem = item.memory_info()
                            tree_rss += imem.rss
                            tree_private += imem.private
                            seen_children[item.pid] = item.cmdline()
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                    if visible_at is None or not window_state:
                        window_state = windows(child.pid)
                        if window_state and visible_at is None:
                            visible_at = elapsed
                    try:
                        cpu_pct = proc.cpu_percent(None)
                        threads = proc.num_threads()
                        handles = proc.num_handles()
                    except psutil.NoSuchProcess:
                        break
                    row = {"elapsed_s": round(elapsed, 3), "pid": child.pid, "rss_mib": mem.rss / 1048576, "private_mib": mem.private / 1048576, "peak_rss_mib": mem.peak_wset / 1048576, "tree_rss_mib": tree_rss / 1048576, "tree_private_mib": tree_private / 1048576, "children": len(descendants), "cpu_pct": cpu_pct, "threads": threads, "handles": handles}
                    rows.append(row)
                    if writer is None:
                        writer = csv.DictWriter(fh, fieldnames=list(row))
                        writer.writeheader()
                    writer.writerow(row)
                    fh.flush()
                    time.sleep(.5)
        finally:
            for win in windows(child.pid):
                USER32.PostMessageW(win["hwnd"], 0x0010, 0, 0)
            try:
                child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                pass
        result = {"run": index, "pid": child.pid, "exit_code": child.poll(), "exit_timeout": child.poll() is None, "visible_at_s": visible_at, "windows": window_state, "children_seen": seen_children, "sample_count": len(rows), "sampled_peak_rss_mib": max((r["rss_mib"] for r in rows), default=None), "windows_peak_rss_mib": max((r["peak_rss_mib"] for r in rows), default=None), "startup": summarize(rows, 0, 30), "early_idle": summarize(rows, 30, 60), "stable_idle": summarize(rows, 120, duration)}
        prefix.with_suffix(".json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result


def main() -> None:
    """Run sequential baseline rounds and persist environmental metadata."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--duration", type=float, default=180)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    from PySide6 import __version__
    config = ROOT / "data/settings_v2.json"
    raw = config.read_bytes()
    settings = json.loads(raw)
    metadata = {"python": sys.version, "executable": sys.executable, "pyside6": __version__, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "config_sha256": hashlib.sha256(raw).hexdigest(), "appearance": settings.get("appearance", {}), "performance": settings.get("performance", {}), "desktop_width": USER32.GetSystemMetrics(78), "desktop_height": USER32.GetSystemMetrics(79), "monitors": USER32.GetSystemMetrics(80), "duration_s": args.duration, "rounds": args.rounds, "notes": ["External sampling; no injected imports, GC or working-set trimming", "Process-tree working sets may double-count shared pages", "First launch and subsequent launches share existing disk caches"]}
    (output / "environment.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    results = []
    for index in range(1, args.rounds + 1):
        result = run(output, index, args.duration)
        results.append(result)
        (output / "summary.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(json.dumps(result), flush=True)
        if result["exit_timeout"] or result["exit_code"] != 0 or result["stable_idle"]["sample_count"] == 0:
            raise RuntimeError("Invalid run or exit timeout; stopping rather than launching a conflicting instance")


if __name__ == "__main__":
    main()
