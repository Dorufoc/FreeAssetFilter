"""Sopeek UI 层。

本包在导入时把 ``sopeek/ui/`` 加入 ``sys.path``，使 ``ui/`` 下的模块可以使用
短路径导入（``from theme import tm``、``from components.styled_button import ...``）。
短名与规范名（``sopeek.ui.theme`` / ``sopeek.ui.components``）由
:mod:`sopeek._import_compat` 的导入重定向 finder 收敛为同一模块对象，
因此两种写法不会产生两份单例。

历史上每个预览器布局文件都各自计算 ``parents[N]`` 再注入 ``sys.path``；
目录层级一变（``sopeek/`` → ``src/sopeek/``）这类代码就会静默失效，现已统一
收敛到本模块。模块内如需仓库根等路径，请用 :mod:`sopeek._paths`。
"""

from __future__ import annotations

import sys
from pathlib import Path

#: 本包目录（``sopeek/ui``）——短路径导入的搜索根。
UI_ROOT: Path = Path(__file__).resolve().parent

if str(UI_ROOT) not in sys.path:
    sys.path.insert(0, str(UI_ROOT))

__all__ = ["UI_ROOT"]

# ---------------------------------------------------------------------------
# 动画节拍对齐面板刷新率
# ---------------------------------------------------------------------------
# Qt 的动画定时器固定约 16 ms，与显示器刷新率无关：在 120/144/240Hz 面板上
# 所有 QPropertyAnimation / QVariantAnimation 只有约 63fps。这里在本包**任何
# 子模块导入之前**把这两个类名替换成"每帧用墙钟补帧"的子类（实现见
# :mod:`sopeek.ui.frame_pacing`）。补丁只加帧、不改动画时长与缓动；失败时
# 静默回退原生节拍，可用 ``SPK_REFRESH_ANIMATIONS=0`` 关闭。
try:  # pragma: no cover - 导入期副作用，逐平台在启动日志中验证
    from sopeek.ui.frame_pacing import install_frame_pacing as _install_frame_pacing

    _install_frame_pacing()
except Exception:  # noqa: BLE001 - 节拍优化绝不能阻断 UI 导入
    pass
