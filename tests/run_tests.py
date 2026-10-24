#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FreeAssetFilter 统一测试运行器（tests/run_tests.py）。

五个 argparse 子命令（``python tests/run_tests.py <子命令>``）：

* **all**（默认）—— 全量非 GUI 套件，追加
  ``-m "not benchmark and not gui"``（同时保留 pytest.ini ``addopts`` 中
  ``-m "not gui"`` 的排除语义——CLI ``-m`` 会整体覆盖 ini 的 ``-m``，
  故必须在这里**合并**两个排除）；
* **unit / integration** —— 按目录范围运行对应分层；
  骨架期自动追加 ``tests/.omo_qa_smoke/``（探针）保证 collected ≥ 1，
  规避零收集退出码 5；
* **gui** —— 隐式 ``-m gui`` + ``FAF_VISUAL=1``，并**取消**默认 offscreen
  （真实显示器环境）；
* **coverage** —— 同 ``all`` 范围并附加 ``--cov=freeassetfilter
  --cov-report=term``；``--strict`` 时再运行 ``coverage_manifest``。

公共行为：

* 启动即 ``log_setup.prepare_log_dir()``（清空旧 ``run-*.log``）并打印当前
  日志路径（幂等：pytest 侧的 ``log_setup.pytest_configure`` 复用同一文件，
  不会二次清理）；
* 默认 ``QT_QPA_PLATFORM=offscreen``（``--visual`` 时取消；``gui`` 子命令
  无条件取消）；
* 默认 ``--timeout 30``（``--timeout N`` 可覆盖）。超时三级优先级的完整语义
  见 ``tests.support.timeout_policy``：显式 marker 最高、自动打标次之、
  这里透传的 CLI ``--timeout`` 仅兜底两者均缺失的测试——**CLI 永不覆盖
  marker**；
* 始终 ``-v`` 流式进度 + 挂载 progress / log_setup 两个 support 插件
  （60s 周期小结 + 结束 top-5 最慢）；
* 透传 ``-k`` / ``--tb`` / ``-x`` / ``--co``（收集模式可直接用于验收）；
* 退出码透传 pytest（若子命令是子流程，则聚合）。

用法示例：:

    python tests/run_tests.py unit --co          # 收集模式验收（exit 0）
    python tests/run_tests.py all                # 默认套件
    python tests/run_tests.py gui                # 视觉测试（真实显示器）
    python tests/run_tests.py coverage --strict  # 覆盖率 + manifest 严格门
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

#: 仓库根（本文件位于 tests/ 下，上溯一级即根目录）。
ROOT_DIR: Path = Path(__file__).resolve().parents[1]

#: 全部子命令清单（--help 展示、argparse choices）。
SUBCOMMANDS: Tuple[str, ...] = (
    "all", "unit", "integration", "gui", "coverage",
)

#: 默认超时（秒）。
DEFAULT_TIMEOUT: int = 30

#: 运行器挂载的 support 插件（progress 周期小结 / log_setup 双写日志）。
_PROGRESS_PLUGIN: str = "tests.support.progress"
_LOG_PLUGIN: str = "tests.support.log_setup"


def _ensure_sys_path() -> None:
    """把仓库根插入 sys.path 首位，保证 ``tests.support.*`` 可导入。

    直接以 ``python tests/run_tests.py`` 运行时，Python 会把脚本所在目录
    （``tests/``）放进 sys.path[0]，此时 ``import tests.support...`` 找不到
    包；根目录在前才可解析。
    """
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))


def _resolve_timeout(command: str, args: argparse.Namespace) -> int:
    """计算本次子命令生效的 CLI 超时秒数。

    优先级：用户显式 ``--timeout N`` > 默认 30。注意这里的取值只影响
    CLI 兜底层——任何显式 timeout marker 或 timeout_policy 自动打标仍优先
    （见 tests/support/timeout_policy.py）。

    Args:
        command: 当前子命令名。
        args: 解析后的参数命名空间。

    Returns:
        int: 应透传给 pytest 的 ``--timeout`` 秒数。
    """
    if args.timeout is not None:
        return args.timeout
    return DEFAULT_TIMEOUT


def _configure_platform(command: str, visual: bool) -> None:
    """按子命令调整显示相关环境变量。

    默认 ``QT_QPA_PLATFORM=offscreen``（``--visual`` 时取消）；
    ``gui`` 子命令无条件取消 offscreen（真实显示器）并设置
    ``FAF_VISUAL=1``（供 gui 套件判断断言层/截图层深浅模式）。

    Args:
        command: 当前子命令名。
        visual: 用户是否显式传入 ``--visual``。
    """
    if visual:
        os.environ.pop("QT_QPA_PLATFORM", None)
    else:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if command == "gui":
        os.environ.pop("QT_QPA_PLATFORM", None)
        os.environ["FAF_VISUAL"] = "1"
    else:
        os.environ.pop("FAF_VISUAL", None)


def _scope_paths(command: str) -> List[str]:
    """计算子命令的 pytest 收集路径参数。

    按分层目录划定范围；unit/integration 在骨架期
    （``tests/.omo_qa_smoke/`` 存在时）追加探针目录，保证每个子命令
    collected ≥ 1，规避零收集退出码 5——这是 todo-5 验收的前提。

    Args:
        command: 当前子命令名。

    Returns:
        list[str]: 传给 pytest 的路径参数列表。
    """
    tests_root: Path = ROOT_DIR / "tests"
    smoke_dir: Path = tests_root / ".omo_qa_smoke"
    layered: Tuple[str, ...] = ("unit", "integration")
    if command == "all":
        return [str(tests_root)]
    if command in layered:
        paths: List[str] = [str(tests_root / command)]
        if smoke_dir.is_dir():
            paths.append(str(smoke_dir))
        return paths
    if command == "gui":
        return [str(tests_root / "gui")]
    if command == "coverage":
        return [str(tests_root)]
    raise ValueError(f"未知子命令: {command}")


def _marker_args(command: str) -> List[str]:
    """计算子命令需要覆盖或补充的 ``-m`` 参数。

    ``all``/``coverage`` 必须合并两个排除（not benchmark and not gui）——
    因为 CLI ``-m`` 整体覆盖 pytest.ini addopts 里的 ``-m "not gui"``，
    只传 ``-m "not benchmark"`` 会导致 gui 用例被纳入默认套件。
    gui 子命令则用 ``-m gui`` 反选对应 marker（覆盖 addopts 的默认排除）。
    其余分层子命令不传 ``-m``，沿用 ini 的 ``-m "not gui"``。

    Args:
        command: 当前子命令名。

    Returns:
        list[str]: 需追加的 ``-m <expr>`` 参数（空则不改写）。
    """
    if command in ("all", "coverage"):
        return ["-m", "not benchmark and not gui"]
    if command == "gui":
        return ["-m", "gui"]
    return []


def build_pytest_args(command: str, args: argparse.Namespace) -> List[str]:
    """组装本次子命令的完整 pytest 参数列表。

    公共基底：挂载 progress + log_setup 插件、``-v``、``--timeout``、
    ``-k``/``--tb``/``-x``/``--co`` 透传、收集路径、子命令专属 ``-m``。

    Args:
        command: 当前子命令名。
        args: 解析后的参数命名空间。

    Returns:
        list[str]: 可直接交给 ``pytest.main`` 的参数列表。
    """
    pytest_args: List[str] = [
        "-p", _PROGRESS_PLUGIN,
        "-p", _LOG_PLUGIN,
        "-v",
        "--timeout", str(_resolve_timeout(command, args)),
    ]
    if args.k:
        pytest_args.extend(["-k", args.k])
    if args.tb:
        pytest_args.extend(["--tb", args.tb])
    if args.exitfirst:
        pytest_args.append("-x")
    if args.co:
        pytest_args.append("--collect-only")
    pytest_args.extend(_scope_paths(command))
    pytest_args.extend(_marker_args(command))
    return pytest_args


def _prepare_log_dir() -> Path:
    """调用 log_setup 准备本次运行日志目录并返回日志文件路径。

    幂等：再次调用会清掉上一个会话的 ``run-*.log`` 并重新命名；pytest 侧
    ``log_setup.pytest_configure`` 检测到 ``_log_path`` 已设置后复用同一文件。

    Returns:
        Path: 本次运行的 ``run-<timestamp>.log`` 绝对路径。
    """
    from tests.support.log_setup import prepare_log_dir
    return prepare_log_dir()


def _run_pytest(pytest_args: List[str]) -> int:
    """在同进程内以 pytest.main 执行并返回退出码。

    Args:
        pytest_args: 完整 pytest 参数列表。

    Returns:
        int: pytest 退出码（透传，不作翻译）。
    """
    import pytest
    print("[run_tests] pytest " + " ".join(pytest_args), flush=True)
    return pytest.main(pytest_args)


def _run_coverage(args: argparse.Namespace) -> int:
    """执行 coverage：同 all 范围 + 覆盖率选项；``--strict`` 再跑 manifest。

    Args:
        args: 解析后的参数命名空间。

    Returns:
        int: pytest 退出码；``--strict`` 时若 pytest 通过则返回 manifest 结果。
    """
    pytest_args: List[str] = build_pytest_args("coverage", args)
    pytest_args.extend(["--cov=freeassetfilter", "--cov-report=term"])
    code: int = _run_pytest(pytest_args)
    if code != 0 or not args.strict:
        return code
    from tests.support import coverage_manifest
    print("[run_tests] [coverage] --strict: 运行 coverage_manifest", flush=True)
    return coverage_manifest.main(["--strict"])


def _run_layered(command: str, args: argparse.Namespace) -> int:
    """执行分层 / all / gui 子命令（单一 pytest 进程）。

    Args:
        command: 当前子命令名。
        args: 解析后的参数命名空间。

    Returns:
        int: pytest 退出码（原样透传）。
    """
    return _run_pytest(build_pytest_args(command, args))


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """解析命令行参数。

    Args:
        argv: 命令行参数；None 时取 sys.argv[1:]。

    Returns:
        argparse.Namespace: 解析结果。
    """
    parser = argparse.ArgumentParser(
        prog="run_tests",
        description="FreeAssetFilter 统一测试运行器：分层 / 全量 / 覆盖率。",
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="all",
        choices=SUBCOMMANDS,
        help="子命令（默认 all）：all | unit | integration | gui | coverage",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        metavar="N",
        help="CLI 兜底超时秒数（仅对无 marker 测试生效；marker 优先；默认 30）",
    )
    parser.add_argument(
        "-k",
        dest="k",
        metavar="EXPR",
        help="按表达式过滤测试（原样透传 pytest -k）",
    )
    parser.add_argument(
        "--tb",
        choices=["auto", "long", "short", "no", "line", "native"],
        default=None,
        help="回溯格式（默认继承 pytest.ini 的 --tb=short）",
    )
    parser.add_argument(
        "-x",
        "--exitfirst",
        action="store_true",
        help="首个失败即停止（透传 pytest -x）",
    )
    parser.add_argument(
        "--co",
        "--collect-only",
        action="store_true",
        dest="co",
        help="仅收集不执行（透传 pytest --collect-only，验收用）",
    )
    parser.add_argument(
        "--visual",
        action="store_true",
        help="取消默认 QT_QPA_PLATFORM=offscreen（真实显示器场景）",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="仅 coverage 子命令有效：额外以 --strict 运行 coverage_manifest",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """统一运行器入口。

    Args:
        argv: 命令行参数；None 时取 sys.argv[1:]。

    Returns:
        int: 透传的 pytest / manifest 退出码。
    """
    _ensure_sys_path()
    args: argparse.Namespace = _parse_args(argv)

    if args.strict and args.command != "coverage":
        print(f"[run_tests] 警告: --strict 仅对 coverage 子命令有意义，"
              f"本次 {args.command} 忽略该选项", file=sys.stderr, flush=True)

    log_path: Path = _prepare_log_dir()
    print(f"[run_tests] 子命令={args.command} | 测试日志: {log_path}", flush=True)
    _configure_platform(args.command, args.visual)

    if args.command == "coverage":
        return _run_coverage(args)
    return _run_layered(args.command, args)


if __name__ == "__main__":
    sys.exit(main())