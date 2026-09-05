#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端日志完整性验证脚本（fix-log-truncation Todo 6）。

在 offscreen QApplication 中逐字复刻 ``freeassetfilter/app/main.py`` 的接线
（fd_capture → console_capture → 控制台 handler 重指 → Qt handler →
excepthook），依次产生六类带唯一 marker 的错误场景，最后重读真实日志文件
自检。

六类场景：
    1. Python 主线程未捕获链式异常（``sys.excepthook`` 路径）。
    2. 子线程未捕获异常（``threading.excepthook`` 路径，真线程抛错）。
    3. ``qWarning`` / ``qCritical``（Qt handler 路径，断言 ``[Qt]`` 前缀）。
    4. ``os.write(2, ...)`` 原生 fd 写入（转发线程路径，断言
       ``[native-stderr]`` 前缀）。
    5. ``sys.stderr.write`` 连续 3 行相同 Traceback 帧（走 TeeStream 管线，
       验证 dedup 豁免；禁止用 ``os.write``，后者无 dedup 逻辑）。
    6. mock 当前 stderr TeeStream 的 ``_log_stream.write`` 抛 OSError，
       验证一次性 bootstrap 告警（文件侧 ``[native-stderr]`` 前缀行）。

用法:
    python scripts/verify_logging.py --self-check

只消费 Todo 1-5 的产物，不修改任何产品代码；日志只写入 data/logs。
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import argparse
import logging
import threading
import time
from types import TracebackType
from typing import Dict, List, Optional

# 产品模块只读引用（不修改其行为）。
from freeassetfilter.utils import app_logger as _app_logger_module
from freeassetfilter.utils.app_logger import (
    TeeStream,
    get_logger,
    install_console_capture,
    log_exception,
)
from freeassetfilter.utils.fd_capture import install_fd_capture, uninstall_fd_capture
from freeassetfilter.utils.qt_message_handler import install_qt_message_handler

MARK_PY = "faf-e2e-py"
MARK_CAUSE = "faf-e2e-cause"
MARK_THREAD = "faf-e2e-thread"
MARK_QT_WARN = "faf-e2e-qtwarning"
MARK_QT_CRIT = "faf-e2e-qtcritical"
MARK_NATIVE = "faf-e2e-native"
MARK_DEDUP_FRAME = 'File "faf_e2e_dedup.py", line 4242, in faf_e2e_dedup_func'
MARK_WRITE_FAIL_TRIGGER = "faf-e2e-write-fail-trigger"
MARK_AFTER_RESTORE = "faf-e2e-after-restore"
ALERT_TEXT = "日志文件写入失败"
NATIVE_STDERR_PREFIX = "[native-stderr]"
QT_PREFIX = "[Qt]"

# Python logger 侧 marker：这些内容绝不允许出现在 [native-*] 双写副本行中。
_PYTHON_MARKERS = (
    MARK_PY,
    MARK_CAUSE,
    MARK_THREAD,
    MARK_QT_WARN,
    MARK_QT_CRIT,
    "faf_e2e_dedup",
)
# 原生通道的合法内容：允许带 [native-stderr] 前缀。
_NATIVE_OK_SUBSTRINGS = (MARK_NATIVE, ALERT_TEXT)


def _handle_exception(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_traceback: Optional[TracebackType],
) -> None:
    """主线程未捕获异常钩子（与 main.py handle_exception 等价内联实现）。

    注：未从 ``freeassetfilter.app.main`` 直接导入——导入该模块会执行其顶层
    日志/单例初始化副作用（fd 接管、faulthandler 等），与本脚本自主管线冲突；
    此处内联等价逻辑（KeyboardInterrupt 守卫 + 路由到 log_exception）。

    Args:
        exc_type: 异常类型。
        exc_value: 异常值。
        exc_traceback: 异常回溯信息。
    """
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    log_exception(exc_type, exc_value, exc_traceback)


def _handle_thread_exception(args: threading.ExceptHookArgs) -> None:
    """子线程未捕获异常钩子（与 main.py handle_thread_exception 等价内联实现）。

    Args:
        args: threading.ExceptHookArgs。
    """
    try:
        if issubclass(args.exc_type, KeyboardInterrupt):
            return
    except TypeError:
        pass
    log_exception(args.exc_type, args.exc_value, args.exc_traceback)


def _normalize_console_encoding() -> None:
    """把控制台流统一为 UTF-8（验证脚本 harness 侧区域设置归一化）。

    ``_write_bootstrap_fallback`` 经 ``sys.__stderr__`` 写出的字节会进入 fd
    管道，再由转发线程按 UTF-8 解码落盘；若控制台编码为 GBK（如中文
    Windows 默认），中文告警在文件中会变成 mojibake，导致自检的中文断言
    恒失败。本函数在管线安装前把四路控制台流重配为 UTF-8，使落盘文件为
    干净 UTF-8。不触碰任何产品代码。

    Returns:
        None。
    """
    for stream in (sys.stdout, sys.stderr, sys.__stdout__, sys.__stderr__):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (OSError, ValueError, AttributeError, TypeError):
            pass


def _install_logging() -> tuple[str, Dict[int, object]]:
    """按 main.py 接线逐字复刻安装日志管线。

    顺序：``install_fd_capture`` → ``install_console_capture(saved…)`` →
    控制台 handler 重指（``type(h) is`` 精确匹配）。

    Returns:
        tuple: (真实日志文件路径, fd_capture 返回的 saved streams 字典)。
    """
    logger = get_logger()
    log_path = logger.get_log_file_path()

    # (a) fd 级原生输出捕获必须先于 console capture 安装。
    fd_saved: Dict[int, object] = {}
    try:
        fd_saved = install_fd_capture(log_path)
    except (OSError, IOError, PermissionError, FileNotFoundError):
        pass
    except (ValueError, TypeError):
        pass

    # (b) 把备份的控制台流交给 TeeStream，否则输出进已接管的 fd 造成双写/死锁。
    try:
        install_console_capture(
            log_path,
            saved_stdout=fd_saved.get(1),
            saved_stderr=fd_saved.get(2),
        )
    except (OSError, IOError, PermissionError, FileNotFoundError):
        pass
    except (ValueError, TypeError):
        pass

    # (c) 重指 AppLogger 控制台 handler 到备份的控制台流（防双写）。
    # 必须用 type(h) is 精确匹配：FileHandler 是 StreamHandler 子类，
    # isinstance 会误伤文件 handler。
    try:
        saved_stdout = fd_saved.get(1)
        if saved_stdout is not None:
            for handler in list(getattr(logger, "logger", None).handlers or []):
                if type(handler) is logging.StreamHandler and handler.stream is sys.__stdout__:
                    handler.stream = saved_stdout  # type: ignore[attr-defined]
    except (OSError, ValueError, AttributeError, TypeError):
        pass

    return log_path, fd_saved


def _scenario_chained_exception() -> None:
    """场景 1：主线程未捕获链式异常（sys.excepthook 路径）。"""
    try:
        try:
            raise TypeError(MARK_CAUSE)
        except TypeError as cause:
            raise ValueError(MARK_PY) from cause
    except ValueError:
        sys.excepthook(*sys.exc_info())


def _scenario_thread_exception() -> None:
    """场景 2：子线程未捕获异常（threading.excepthook 路径，真线程抛错）。"""
    def _boom() -> None:
        raise RuntimeError(MARK_THREAD)

    worker = threading.Thread(target=_boom, name="faf-e2e-thread-worker", daemon=True)
    worker.start()
    worker.join(timeout=10.0)


def _scenario_qt_messages() -> None:
    """场景 3：qWarning / qCritical（Qt handler 路径）。"""
    from PySide6.QtCore import qCritical, qWarning

    qWarning(MARK_QT_WARN)
    qCritical(MARK_QT_CRIT)
    time.sleep(0.5)


def _scenario_native_fd_write() -> None:
    """场景 4：os.write(2, …) 原生 fd 写入（转发线程路径）。"""
    os.write(2, f"{MARK_NATIVE}\n".encode("utf-8"))
    time.sleep(1.5)


def _scenario_dedup_exemption() -> None:
    """场景 5：sys.stderr.write 连写 3 行相同 Traceback 帧（dedup 豁免）。

    必须走 TeeStream 管线；禁止用 os.write(2, …)，后者走转发线程（无 dedup
    逻辑），断言“未折叠”恒为真，测不到 Todo 2 的豁免。
    """
    frame_line = f"  {MARK_DEDUP_FRAME}\n"
    sys.stderr.write(frame_line)
    sys.stderr.write(frame_line)
    sys.stderr.write(frame_line)
    sys.stderr.flush()


class _FailingLogStream:
    """模拟磁盘满/权限失败的日志底层流（write 恒抛 OSError）。"""

    def write(self, _s: str) -> int:
        """恒抛 OSError，模拟日志文件写入失败。

        Args:
            _s: 待写内容（忽略）。

        Raises:
            OSError: 恒定抛出，模拟写入失败。
        """
        raise OSError("faf-e2e-boom-disk-full")

    def flush(self) -> None:
        """空实现（满足流协议）。"""
        return None


def _scenario_write_failure_fallback() -> None:
    """场景 6：触发一次 TeeStream 写失败降级（一次性 bootstrap 告警）。

    mock 用完即恢复，不污染后续场景。
    """
    tee = sys.stderr
    if not isinstance(tee, TeeStream):
        return
    original_log_stream = tee._log_stream
    tee._log_stream = _FailingLogStream()  # type: ignore[assignment]
    try:
        sys.stderr.write(f"{MARK_WRITE_FAIL_TRIGGER}\n")
    finally:
        tee._log_stream = original_log_stream
    # 结束 scenario 6 遗留的 dedup 计数态（先补齐断行，再落一个完整行），
    # 随后用空行把新一轮计数态冲刷干净，避免悬挂半行。
    sys.stderr.write(f"{MARK_AFTER_RESTORE}\n")
    sys.stderr.write("\n")
    sys.stderr.flush()
    time.sleep(1.0)


def _flush_all_streams() -> None:
    """刷新 TeeStream 与全部 logger handler（uninstall 前调用）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (OSError, IOError, ValueError, TypeError):
            pass
    try:
        logger = get_logger()
        for handler in list(getattr(logger, "logger", None).handlers or []):
            try:
                handler.flush()
            except (OSError, IOError, ValueError, TypeError, AttributeError):
                pass
    except (OSError, ValueError, AttributeError, TypeError):
        pass


def _self_check(log_path: str) -> List[str]:
    """重读日志文件，断言六类场景全部落盘且无双写。

    Args:
        log_path: 真实日志文件路径（get_logger 的文件）。

    Returns:
        缺失项描述列表；为空表示全部通过。
    """
    missing: List[str] = []
    try:
        text = Path(log_path).read_text(encoding="utf-8", errors="replace")
    except (OSError, IOError, ValueError) as exc:
        return [f"日志文件不可读: {log_path} ({exc})"]
    lines = text.splitlines()

    for marker in (
        MARK_PY,
        MARK_CAUSE,
        MARK_THREAD,
        MARK_QT_WARN,
        MARK_QT_CRIT,
        MARK_NATIVE,
        "faf_e2e_dedup",
        ALERT_TEXT,
    ):
        if marker not in text:
            missing.append(f"marker 缺失: {marker}")

    for token in ("ValueError", "TypeError", "direct cause"):
        if token not in text:
            missing.append(f"异常完整性缺失: {token}")

    if not any(QT_PREFIX in line and MARK_QT_WARN in line for line in lines):
        missing.append("Qt 前缀缺失: [Qt] faf-e2e-qtwarning")
    if not any(QT_PREFIX in line and MARK_QT_CRIT in line for line in lines):
        missing.append("Qt 前缀缺失: [Qt] faf-e2e-qtcritical")
    if not any(NATIVE_STDERR_PREFIX in line and MARK_NATIVE in line for line in lines):
        missing.append("原生前缀缺失: [native-stderr] faf-e2e-native")

    frame_count = sum(1 for line in lines if MARK_DEDUP_FRAME in line)
    if frame_count != 3:
        missing.append(f"dedup 豁免行数异常: 期望 3 行, 实际 {frame_count} 行")
    if any("【x" in line and MARK_DEDUP_FRAME in line for line in lines):
        missing.append("dedup 豁免被折叠: 帧行出现 【xN】 计数标签")

    if not any(
        NATIVE_STDERR_PREFIX in line and ALERT_TEXT in line for line in lines
    ):
        missing.append("写失败告警缺失: 带 [native-stderr] 前缀的 [警告] 日志文件写入失败")

    double_written = [
        line
        for line in lines
        if ("[native-stdout]" in line or NATIVE_STDERR_PREFIX in line)
        and any(marker in line for marker in _PYTHON_MARKERS)
        and not any(ok in line for ok in _NATIVE_OK_SUBSTRINGS)
    ]
    if double_written:
        preview = double_written[0][:160]
        missing.append(f"发现双写副本: {len(double_written)} 行含 [native-*] 前缀的 Python 日志 (如: {preview})")

    return missing


def run_verification() -> int:
    """执行六类场景产生 + 落盘 + 自检。

    Returns:
        int: 全过返回 0；任一缺失返回 1。
    """
    # GBK 控制台下 bootstrap 中文告警经管道会变 mojibake，先归一化为 UTF-8。
    _normalize_console_encoding()
    log_path, _fd_saved = _install_logging()

    sys.excepthook = _handle_exception
    threading.excepthook = _handle_thread_exception

    from PySide6.QtWidgets import QApplication

    app = QApplication([sys.argv[0]])
    try:
        install_qt_message_handler()
    except (OSError, ValueError, TypeError):
        pass

    print(f"[verify] 日志文件: {log_path}")
    print("[verify] 场景 1: 主线程链式异常")
    _scenario_chained_exception()
    print("[verify] 场景 2: 子线程未捕获异常")
    _scenario_thread_exception()
    print("[verify] 场景 3: Qt qWarning/qCritical")
    _scenario_qt_messages()
    print("[verify] 场景 4: 原生 fd 写入")
    _scenario_native_fd_write()
    print("[verify] 场景 5: dedup 豁免（3 行相同 Traceback 帧）")
    _scenario_dedup_exemption()
    print("[verify] 场景 6: 写失败降级（一次性 bootstrap 告警）")
    _scenario_write_failure_fallback()

    # 退出前顺序：flush 各流 → uninstall_fd_capture（排空+join）→ 再读文件自检。
    _flush_all_streams()
    try:
        uninstall_fd_capture()
    except (OSError, ValueError):
        pass

    try:
        from PySide6.QtCore import qInstallMessageHandler

        qInstallMessageHandler(None)
    except (OSError, ValueError, TypeError, ImportError, RuntimeError):
        pass
    app.quit()

    missing = _self_check(log_path)
    if not missing:
        print("ALL CHECKS PASSED")
        return 0
    for item in missing:
        print(f"MISSING: {item}")
    return 1


def main() -> int:
    """脚本入口（参考 scripts/startup_profiler.py 的 main 范式）。

    Returns:
        int: 自检全过返回 0，否则返回 1。
    """
    parser = argparse.ArgumentParser(description="FreeAssetFilter 日志完整性端到端验证")
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="产生六类错误场景并自检日志文件完整性",
    )
    args = parser.parse_args()
    _ = args
    return run_verification()


if __name__ == "__main__":
    sys.exit(main())
