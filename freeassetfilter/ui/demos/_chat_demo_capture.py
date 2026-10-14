# -*- coding: utf-8 -*-
"""WinUI 3 对话 Demo 的离屏截图辅助脚本。

用途（供 Lead 与目标图逐像素比对）：

    $env:QT_QPA_PLATFORM="offscreen"
    python -m freeassetfilter.ui.demos._chat_demo_capture --out .\\.demo_out\\chat_demo.png

也可以直接执行：

    python freeassetfilter/ui/demos/_chat_demo_capture.py --out out.png

实现要点：

1. 作为入口运行时先把 ``QT_QPA_PLATFORM`` 默认设为 ``offscreen``，再导入
   任何 QtWidgets 模块；
2. 构造 :class:`DemoWindow`（内含完整静态消息清单），``show()`` 后多次
   ``processEvents`` 等待布局、样式表重建与定时器收敛；
3. ``window.grab().save(path)`` 输出整窗 PNG（含标题栏与输入栏）；
4. 两条自动兜底路径（实测环境确认必需）：
   * **字体缺失**：offscreen 平台在本机没有任何字体（``QFontDatabase``
     为空），中文会渲染成方块，此时自动以 ``QT_QPA_PLATFORM=windows``
     重启子进程重试；
   * **尺寸/缩放异常**：顶层窗口被布局最小尺寸顶住、或 HiDPI 让 grab 变成
     1.5 倍像素时，先放开最小尺寸约束重排，再按设备像素比归一化到目标尺寸。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Union

# 仓库根目录（本文件位于 freeassetfilter/ui/demos/ 下，向上三级）
_REPO_ROOT = Path(__file__).resolve().parents[3]

# 直接以脚本方式执行时把仓库根目录加入 sys.path，保证绝对导入可用
if __package__ in (None, ""):
    sys.path.insert(0, str(_REPO_ROOT))

# 关键顺序：先落 offscreen 平台默认值，再导入 QtWidgets。
# 仅在作为入口运行时设置，避免被 import 时污染宿主进程的平台选择。
if __name__ == "__main__":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QPoint, QSize, Qt
from PySide6.QtGui import QFontDatabase, QImage, QPixmap, QRegion
from PySide6.QtWidgets import QApplication, QLayout, QWidget

from freeassetfilter.ui.theme import tm

from freeassetfilter.ui.demos.styled_ai_chat_demo import WINDOW_SIZE, DemoWindow

#: 默认输出路径（相对仓库根目录的 .demo_out 目录）。
DEFAULT_OUT = Path(".demo_out") / "chat_demo.png"

#: 默认窗口尺寸：与 DemoWindow 初始尺寸保持一致。
DEFAULT_SIZE = (int(WINDOW_SIZE[0]), int(WINDOW_SIZE[1]))

#: 截图默认强制浅色主题（对齐 WinUI 3 HTML 原型；``keep`` 表示不改主题）。
DEFAULT_THEME = "light"


def _pump_events(app: QApplication, rounds: int, interval_ms: int) -> None:
    """反复泵事件循环，等待布局、样式表重建与零延时定时器收敛。

    Args:
        app: 当前 QApplication。
        rounds: 泵事件轮数（每轮含两次 processEvents 与一次短睡眠）。
        interval_ms: 每轮之间的睡眠毫秒数。
    """
    for _ in range(max(1, rounds)):
        app.processEvents(QEventLoop.AllEvents, 50)
        time.sleep(max(0, interval_ms) / 1000.0)
        app.processEvents(QEventLoop.AllEvents, 50)


def _coerce_size(size: object) -> QSize:
    """把 ``(w, h)`` / ``QSize`` / ``"520x780"`` 统一为 QSize。

    Args:
        size: 尺寸描述，支持元组、QSize 或 ``"宽x高"`` 字符串。

    Returns:
        归一化后的 QSize。

    Raises:
        ValueError: 尺寸描述无法解析或数值非正。
    """
    if isinstance(size, QSize):
        result = QSize(size)
    elif isinstance(size, (tuple, list)) and len(size) == 2:
        result = QSize(int(size[0]), int(size[1]))
    elif isinstance(size, str):
        parts = size.lower().replace("*", "x").split("x")
        if len(parts) != 2:
            raise ValueError(
                f"cannot parse size {size!r} (expected e.g. '520x780')"
            )
        result = QSize(int(parts[0].strip()), int(parts[1].strip()))
    else:
        raise ValueError(f"unsupported size type: {type(size).__name__}")
    if result.width() <= 0 or result.height() <= 0:
        raise ValueError(
            f"size must be positive: {result.width()}x{result.height()}"
        )
    return result


def font_database_ready() -> bool:
    """判断当前平台是否真的提供了字体（offscreen 平台通常为空）。

    Returns:
        True 表示字体数据库非空，中文可以正常渲染。
    """
    try:
        return len(QFontDatabase.families()) > 0
    except Exception:
        return True


def _relax_minimum_size(window: QWidget) -> None:
    """放开窗口/布局的最小尺寸约束，使其能被压到目标尺寸。

    顶层窗口的最小尺寸来自其根布局（``SetDefaultConstraint`` 会把布局
    ``minimumSize`` 写进控件），仅改布局约束还不够，必须同时把控件自身的
    最小尺寸归零，否则窗口仍会被顶住。

    Args:
        window: 目标顶层窗口。
    """
    window.setMinimumSize(0, 0)
    layout = window.layout()
    if layout is not None:
        layout.setSizeConstraint(QLayout.SetNoConstraint)


def _render_exact(window: QWidget, size: QSize) -> QPixmap:
    """把窗口按目标尺寸离屏渲染（grab 尺寸异常时的兜底路径）。

    Args:
        window: 待渲染的顶层窗口。
        size: 目标像素尺寸。

    Returns:
        目标尺寸的 QPixmap。
    """
    pixmap = QPixmap(size)
    pixmap.fill(Qt.transparent)
    window.render(pixmap, QPoint(0, 0), QRegion(0, 0, size.width(), size.height()))
    return pixmap


def _normalize_pixmap(pixmap: QPixmap, target: QSize) -> QPixmap:
    """把 grab 结果归一化到目标像素尺寸。

    HiDPI 屏幕上 ``grab()`` 返回的是设备像素（顶层窗口 1.5 倍缩放时是
    目标尺寸的 1.5 倍），这里先复位设备像素比再等比缩回目标尺寸。

    Args:
        pixmap: ``window.grab()`` 的结果。
        target: 目标像素尺寸。

    Returns:
        目标尺寸的 QPixmap。
    """
    if float(pixmap.devicePixelRatio() or 1.0) != 1.0:
        pixmap.setDevicePixelRatio(1.0)
    if pixmap.size() != target:
        pixmap = pixmap.scaled(
            target, Qt.IgnoreAspectRatio, Qt.SmoothTransformation
        )
    return pixmap


def capture(
    app_or_window: Union[QApplication, QWidget],
    path: Union[str, os.PathLike],
    size: object = DEFAULT_SIZE,
    *,
    theme: str = DEFAULT_THEME,
    settle_rounds: int = 12,
    interval_ms: int = 20,
) -> str:
    """构造/复用 Demo 窗口并抓图落盘。

    Args:
        app_or_window: QApplication（自动新建 DemoWindow）或已有的窗口控件。
        path: 输出 PNG 路径（父目录会自动创建）。
        size: 目标尺寸，支持 ``(w, h)`` / ``QSize`` / ``"520x780"``。
        theme: ``"light"`` / ``"dark"`` 强制主题，``"keep"`` 保持当前主题。
        settle_rounds: 布局收敛泵事件轮数。
        interval_ms: 每轮泵事件之间的睡眠毫秒数。

    Returns:
        实际写出的 PNG 路径。

    Raises:
        TypeError: ``app_or_window`` 既不是 QApplication 也不是 QWidget。
        RuntimeError: grab 失败、无法取得 QApplication 或 PNG 写入失败。
    """
    target = _coerce_size(size)
    if isinstance(app_or_window, QApplication):
        app = app_or_window
        window = DemoWindow()
    elif isinstance(app_or_window, QWidget):
        window = app_or_window
        instance = QApplication.instance()
        if instance is None:
            raise RuntimeError(
                "a QApplication instance is required when passing a QWidget"
            )
        app = instance
    else:
        raise TypeError("capture() accepts only a QApplication or a QWidget")

    if theme in ("light", "dark"):
        tm.set_theme(theme)

    if not font_database_ready():
        # 控制台日志保持 ASCII：Windows 控制台默认 GBK，中文诊断信息在
        # 重定向/捕获场景下会变成乱码，影响验收证据的可读性。
        print(
            "[capture] warning: font database is empty on this platform, "
            "CJK text renders as boxes; rerun with QT_QPA_PLATFORM=windows",
            file=sys.stderr,
        )

    window.resize(target)
    if not window.isVisible():
        window.show()
    _pump_events(app, settle_rounds, interval_ms)

    # 布局稳定后再校正一次尺寸，确保 grab 覆盖完整窗口内容
    window.resize(target)
    _pump_events(app, max(2, settle_rounds // 2), interval_ms)
    if window.size() != target:
        # 顶层窗口被布局最小尺寸顶住：放开约束后再校正一次
        _relax_minimum_size(window)
        window.resize(target)
        _pump_events(app, max(2, settle_rounds // 2), interval_ms)

    pixmap = window.grab()
    if pixmap.isNull():
        raise RuntimeError("window.grab() returned a null pixmap")
    if window.size() == target:
        pixmap = _normalize_pixmap(pixmap, target)
    else:
        print(
            f"[capture] warning: window size {window.width()}x{window.height()} "
            f"cannot shrink to {target.width()}x{target.height()}; "
            f"falling back to offscreen render",
            file=sys.stderr,
        )
        pixmap = _render_exact(window, target)

    out_path = Path(path)
    if out_path.parent and not out_path.parent.exists():
        out_path.parent.mkdir(parents=True, exist_ok=True)
    if not pixmap.save(str(out_path), "PNG"):
        raise RuntimeError(f"failed to write PNG: {out_path}")
    return str(out_path)


def _rerun_with_real_window(args: argparse.Namespace) -> int:
    """以真实窗口平台 + 1:1 像素比重启本模块重试截图（兜底路径）。

    Args:
        args: 已解析的命令行参数。

    Returns:
        子进程退出码。
    """
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "windows"
    # 关闭 HiDPI 缩放：HTML 原型是 1x 像素，截图必须同口径才能逐像素比对
    env["QT_ENABLE_HIGHDPI_SCALING"] = "0"
    command = [
        sys.executable,
        "-m",
        "freeassetfilter.ui.demos._chat_demo_capture",
        "--out",
        str(args.out),
        "--size",
        args.size,
        "--theme",
        args.theme,
        "--platform",
        "windows",
        "--no-fallback",
    ]
    completed = subprocess.run(command, cwd=str(_REPO_ROOT), env=env)
    return int(completed.returncode)


def main(argv: Optional[list[str]] = None) -> int:
    """命令行入口：截图并校验输出 PNG 的尺寸。

    Args:
        argv: 参数列表；``None`` 时取 ``sys.argv[1:]``。

    Returns:
        进程退出码（0 表示截图成功且尺寸符合预期）。
    """
    parser = argparse.ArgumentParser(
        description="WinUI 3 对话 Demo 截图（默认使用 offscreen 平台）"
    )
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="输出 PNG 路径")
    parser.add_argument(
        "--size",
        default=f"{DEFAULT_SIZE[0]}x{DEFAULT_SIZE[1]}",
        help="窗口尺寸，形如 520x780",
    )
    parser.add_argument(
        "--theme",
        default=DEFAULT_THEME,
        choices=("light", "dark", "keep"),
        help="截图前强制主题（默认 light，对齐 HTML 原型）",
    )
    parser.add_argument(
        "--platform",
        default="",
        help="强制指定 Qt 平台插件（如 windows / offscreen）",
    )
    parser.add_argument(
        "--no-fallback",
        action="store_true",
        help="离屏字体/尺寸异常时禁止改用真实窗口重试",
    )
    args = parser.parse_args(argv)

    if args.platform:
        os.environ["QT_QPA_PLATFORM"] = args.platform
    platform_name = os.environ.get("QT_QPA_PLATFORM", "") or "default"
    target = _coerce_size(args.size)

    app = QApplication.instance() or QApplication(sys.argv[:1])

    if (
        not args.no_fallback
        and platform_name == "offscreen"
        and not font_database_ready()
    ):
        print(
            "[capture] offscreen platform has no fonts (CJK text renders as "
            "boxes), retrying with the real window platform (windows, 1:1 px)",
            file=sys.stderr,
        )
        return _rerun_with_real_window(args)

    out_path = capture(app, args.out, target, theme=args.theme)

    saved = QImage(out_path)
    matches = saved.width() == target.width() and saved.height() == target.height()
    print(
        f"[capture] platform={platform_name} theme={tm.effective_theme()} "
        f"out={out_path} size={saved.width()}x{saved.height()} "
        f"expected={target.width()}x{target.height()} ok={matches}"
    )

    if not matches and platform_name == "offscreen" and not args.no_fallback:
        print(
            "[capture] offscreen screenshot size mismatch, retrying with the "
            "real window platform (windows)",
            file=sys.stderr,
        )
        return _rerun_with_real_window(args)
    return 0 if matches else 1


if __name__ == "__main__":
    raise SystemExit(main())
