#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""去提权重启诊断 spike（floating-pool-window 任务 12 配套；非生产代码）。

仿 `_frameless_modern_demo.py` 先例：仓库根一次性实验脚本，用于在真机上
验证 `freeassetfilter.utils.elevation` 的行为。

用法
----
    python _deelevate_spike.py            # 诊断模式：打印状态块；已提权时确认后
                                          # 以普通用户令牌重启本脚本自身
    python _deelevate_spike.py --child    # 被重启出的子进程入口：打印状态块后退出

`--child` 子进程会打印与父进程相同的状态块（elevated / integrity / shell pid /
argv / cwd），用于**自证**去提权重启后 argv 与 CWD 是否被正确传递：应看到
argv 含 `--child`、cwd 为仓库根目录、elevated 为 False（Medium 完整性级别）。

注意：子进程的标准输出去向取决于启动方式（真实控制台中会回到同一窗口；
管道/无控制台环境下可能不可见）。自动化证据可用 `cmd /c` 包一层重定向捕获。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from freeassetfilter.utils import elevation  # noqa: E402

_INTEGRITY_NAMES = {
    elevation.INTEGRITY_LEVEL_LOW: "Low",
    elevation.INTEGRITY_LEVEL_MEDIUM: "Medium",
    elevation.INTEGRITY_LEVEL_HIGH: "High",
    elevation.INTEGRITY_LEVEL_SYSTEM: "System",
}


def _print_status_block(tag: str) -> None:
    """打印状态块（elevated / integrity / shell pid / argv / cwd）。"""
    integrity = elevation.get_integrity_level()
    integrity_text = "None"
    if integrity is not None:
        name = _INTEGRITY_NAMES.get(integrity, "unknown")
        integrity_text = f"{hex(integrity)} ({name})"
    # 诊断脚本可接受访问模块内部：shell pid 没有公开 API，仅此处展示用。
    print(f"----- {tag} -----")
    print(f"elevated              : {elevation.is_process_elevated()}")
    print(f"integrity             : {integrity_text}")
    print(f"deelevation available : {elevation.deelevation_available()}")
    print(f"shell pid             : {elevation._get_shell_pid()}")
    print(f"sys.executable        : {sys.executable}")
    print(f"argv                  : {sys.argv!r}")
    print(f"cwd                   : {os.getcwd()}")
    print(flush=True)


def main() -> int:
    """spike 入口：`--child` 自证模式 / 父进程诊断与交互式 relaunch。"""
    if "--child" in sys.argv[1:]:
        _print_status_block("child (de-elevated relaunch)")
        print("自证点：argv 应含 '--child'、cwd 应为仓库根、elevated 应为 False。", flush=True)
        return 0

    _print_status_block("parent (current process)")
    target = [sys.executable, str(Path(__file__).resolve()), "--child"]

    if not elevation.is_process_elevated():
        print("当前进程未提权，去提权无必要；演示 restart_de_elevated 的未提权契约：", flush=True)
        result = elevation.restart_de_elevated(target)
        print(f"restart_de_elevated -> {result!r}", flush=True)
        return 0

    print("当前进程已提权。将以普通用户令牌重启本脚本自身：", flush=True)
    print(f"  目标 argv : {target!r}", flush=True)
    print(f"  目标 cwd  : {str(_REPO_ROOT)!r}", flush=True)
    print("输入 y 继续（其他任意输入 / 输入流结束 = 取消）: ", end="", flush=True)
    try:
        answer = input().strip().lower()
    except EOFError:
        print(flush=True)
        print("标准输入已结束，视为取消，未启动任何进程。", flush=True)
        return 0
    if answer != "y":
        print("已取消，未启动任何进程。", flush=True)
        return 0

    result = elevation.restart_de_elevated(target, cwd=str(_REPO_ROOT))
    print(f"restart_de_elevated -> {result!r}", flush=True)
    if result[0]:
        print("restart 已发起：子进程将打印同样的状态块（自证 argv / CWD / elevated）。", flush=True)
        return 0
    print("restart 失败：上方失败细节即为两机制的真实返回（未粉饰）。", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
