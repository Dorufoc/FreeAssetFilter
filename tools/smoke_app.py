#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sopeek 冒烟检查（重构期回归网）。

两项检查，任一失败即非零退出：

1. **导入冒烟**：遍历 ``src/sopeek`` 下全部模块逐个 ``import``，汇总失败项。
2. **离屏启动**：``QT_QPA_PLATFORM=offscreen`` 下创建 QApplication 与主窗口，
   跑 2 秒事件循环后退出，验证 UI 构造链与资源路径可用。

用法::

    python tools/smoke_app.py              # 两项都跑
    python tools/smoke_app.py --imports    # 只跑导入冒烟（不需要 Qt 显示）
    python tools/smoke_app.py --app        # 只跑离屏启动

说明：导入冒烟会跳过 ``sopeek.app.main``（其模块级代码会解析命令行并安装进程级设施），
主窗口通过离屏启动单独覆盖。
"""

from __future__ import annotations

import argparse
import importlib
import os
import sys
import traceback
from pathlib import Path
from typing import List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent

#: 仓库采用 src 布局：唯一的可导入根是 ``src/``。
SRC_DIR = REPO_ROOT / "src"
PACKAGE_DIR = SRC_DIR / "sopeek"

#: 导入冒烟跳过：入口模块自带进程级副作用（参数解析、faulthandler、信号钩子）。
_IMPORT_SKIP = {"sopeek.app.main"}


def _ensure_importable() -> None:
    """把 ``src/`` 放到 ``sys.path`` 首位（无需 pip install -e .）。"""
    src = str(SRC_DIR)
    if src not in sys.path:
        sys.path.insert(0, src)


def _module_name(path: Path) -> str:
    """把包内文件路径转成模块名；``__init__.py`` 归到包本身。"""
    rel = path.relative_to(SRC_DIR).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _iter_modules() -> List[str]:
    """列出全部可导入模块（跳过 ``__pycache__`` 与私有构建目录）。"""
    names: List[str] = []
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        name = _module_name(path)
        if name and name not in _IMPORT_SKIP:
            names.append(name)
    return names


def run_import_smoke() -> Tuple[int, List[Tuple[str, str]]]:
    """逐个导入全部模块。

    Returns:
        tuple[int, list[tuple[str, str]]]: ``(总数, [(模块名, 失败原因), ...])``。
    """
    _ensure_importable()
    modules = _iter_modules()
    failures: List[Tuple[str, str]] = []
    for name in modules:
        try:
            importlib.import_module(name)
        except Exception:  # noqa: BLE001 - 冒烟检查需汇总全部失败而非首错即停
            failures.append((name, traceback.format_exc(limit=3)))
    return len(modules), failures


def run_app_smoke(seconds: float = 2.0) -> int:
    """离屏启动主窗口并跑一小段事件循环。

    Args:
        seconds: 事件循环时长（秒）。

    Returns:
        int: 0 表示窗口创建与事件循环均正常。
    """
    _ensure_importable()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from sopeek.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = MainWindow()
    window.show()

    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(app.quit)
    timer.start(int(seconds * 1000))
    app.exec()

    window.close()
    window.deleteLater()
    app.processEvents()
    return 0


def main(argv: List[str] | None = None) -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="Sopeek 冒烟检查")
    parser.add_argument("--imports", action="store_true", help="只跑导入冒烟")
    parser.add_argument("--app", action="store_true", help="只跑离屏启动")
    parser.add_argument(
        "--seconds", type=float, default=2.0, help="离屏启动事件循环时长（秒）"
    )
    args = parser.parse_args(argv)

    run_both = not (args.imports or args.app)
    failed = False

    if run_both or args.imports:
        total, failures = run_import_smoke()
        print(f"[imports] {total - len(failures)}/{total} 个模块导入成功")
        for name, reason in failures:
            failed = True
            print(f"[imports] 失败: {name}\n{reason}")

    if run_both or args.app:
        try:
            run_app_smoke(args.seconds)
            print("[app] 离屏启动正常")
        except Exception:  # noqa: BLE001 - 冒烟检查需打印完整堆栈后判定失败
            failed = True
            print("[app] 离屏启动失败")
            traceback.print_exc()

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
