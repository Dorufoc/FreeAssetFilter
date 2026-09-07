# -*- coding: utf-8 -*-
# targets: freeassetfilter.ui.layout.preview.native_pdf_renderer
"""NativePdfRenderer 单元测试（任务 4 补充）。

旧版该组件的测试随 tests/components/test_previewers.py（旧组件测试资产）
一并删除；本文件为迁移至 ``ui/layout/preview/`` 后的冒烟级重覆盖：

* 载入有效 PDF：页数/缩放/跳页/适应页宽接口可用；
* 载入缺失文件：不抛异常并优雅返回；
* 关闭事件（closeEvent）安全。

完整交互面（选区/手势/上下文菜单）的全覆盖登记在重构执行日志
任务 4 的基建债清单，待后续迭代补足。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

# ui 短路径导入引导（styled 组件内部使用 ``from theme/components import ...``）
_UI_ROOT: str = str(Path(__file__).resolve().parents[5] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from freeassetfilter.ui.layout.preview.native_pdf_renderer import NativePdfRenderer

pytestmark = pytest.mark.unit


class TestNativePdfRendererSmoke:
    """载入与基础导航接口的冒烟覆盖。"""

    def test_load_valid_pdf(self, qapp: Any, sample_pdf_file: str) -> None:
        renderer = NativePdfRenderer()
        try:
            ok = renderer.load_document(sample_pdf_file)
            assert ok is True
            assert renderer.page_count() == 1
        finally:
            renderer.close()

    def test_load_missing_file_graceful(self, qapp: Any, tmp_path: Any) -> None:
        renderer = NativePdfRenderer()
        try:
            ok = renderer.load_document(str(tmp_path / "missing.pdf"))
            assert ok is False
        finally:
            renderer.close()

    def test_navigation_after_load(self, qapp: Any, sample_pdf_file: str) -> None:
        renderer = NativePdfRenderer()
        try:
            assert renderer.load_document(sample_pdf_file) is True
            renderer.go_to_page(1)
            renderer.set_zoom(1.5)
            renderer.fit_to_page()
        finally:
            renderer.close()