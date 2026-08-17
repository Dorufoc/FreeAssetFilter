# -*- coding: utf-8 -*-
"""GUI 视觉测试配置（tests-comprehensive-refactor todo-26 重写）。

复用根 ``tests/conftest.py`` 的 session 级 ``qapp``（附带
dpi_scale_factor / global_font / settings_manager / theme_manager 属性）
与 autouse ``reset_singletons``（核心管理器重置，**不**覆盖
ui/theme 的 ThemeManager 单例——见 conftest.py:112-116 约定）。

本文件只补充两件事：

* ``screenshots_dir``（function）：截图输出目录 ``tests/gui/screenshots/``，
  自动创建。todo-26 约定截图只写入此目录（已 gitignore）。
* autouse ``_flush_qt_events_after_test``（function）：每个测试之后冲刷
  一轮 Qt 事件队列，防止 deleteLater / 重绘残留影响下一个测试。

约定（todo-26）：每个测试函数必须显式依赖 ``qapp``（缺实例会在 C++ 层
abort，0xC0000409）；文件级 ``pytestmark = pytest.mark.gui``（仅
``python tests/run_tests.py gui`` 以 ``-m gui`` 收集执行）。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterator

import pytest

_GUI_DIR: Path = Path(__file__).resolve().parent
SCREENSHOTS_DIR: Path = _GUI_DIR / "screenshots"


@pytest.fixture
def screenshots_dir() -> str:
    """返回截图输出目录的绝对路径（自动创建目录）。

    Returns:
        str: ``tests/gui/screenshots/`` 的绝对路径字符串。
    """
    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
    return str(SCREENSHOTS_DIR)


@pytest.fixture(autouse=True)
def _flush_qt_events_after_test(qapp: Any) -> Iterator[None]:
    """每个测试后冲刷一轮 Qt 事件队列（autouse, function）。

    Args:
        qapp: 会话级 QApplication（根 conftest 提供）。

    Returns:
        None。
    """
    yield
    qapp.processEvents()