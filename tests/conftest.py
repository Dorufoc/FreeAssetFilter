"""pytest 全局配置：路径注入、数据目录隔离、Qt 应用与单例重置。

目录约定
--------
``tests/`` 镜像 ``src/sopeek/`` 的层级：

- ``tests/unit/utils/…``   → ``src/sopeek/utils/…``
- ``tests/unit/core/…``    → ``src/sopeek/core/…``
- ``tests/unit/services/…``→ ``src/sopeek/services/…``
- ``tests/integration/``   → 跨模块流程（导入全量、注册表 → 预览器类）
- ``tests/fixtures/``      → 不可再生的二进制夹具（媒体、图像、编码样本）

隔离原则
--------
测试绝不触碰用户真实的 ``%LOCALAPPDATA%\\Sopeek\\data``：每个测试会话把
``SPK_DATA_DIR`` 指向临时目录，退出时清理。``src/`` 通过 ``sys.path`` 注入，
因此无需先 ``pip install -e .`` 即可跑测试。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Iterator

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"

#: 在导入任何 Qt 模块之前固定离屏后端，避免 CI/无桌面环境建窗口失败。
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
#: 关掉 Qt 的硬件渲染要求（离屏后端下无用且可能刷警告）。
os.environ.setdefault("QT_OPENGL", "software")
#: 单测固定走 QTimer 帧节拍：vsync 时钟泵会起后台线程等 vblank，离屏环境下
#: 既无意义又会让时序断言变得不确定。时钟路径有自己的用例（显式打开）。
os.environ.setdefault("SPK_FRAME_CLOCK", "0")

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


@pytest.fixture(scope="session", autouse=True)
def _isolated_data_dir() -> Iterator[Path]:
    """把应用数据目录重定向到临时目录（整个会话共用一个）。"""
    data_dir = Path(tempfile.mkdtemp(prefix="sopeek-test-data-"))
    previous = os.environ.get("SPK_DATA_DIR")
    os.environ["SPK_DATA_DIR"] = str(data_dir)
    try:
        yield data_dir
    finally:
        if previous is None:
            os.environ.pop("SPK_DATA_DIR", None)
        else:
            os.environ["SPK_DATA_DIR"] = previous
        shutil.rmtree(data_dir, ignore_errors=True)


@pytest.fixture(scope="session")
def qapp():
    """会话级 ``QApplication``（离屏）。Qt 组件测试用。"""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def fixtures_dir() -> Path:
    """二进制夹具根目录。"""
    return Path(__file__).resolve().parent / "fixtures"
