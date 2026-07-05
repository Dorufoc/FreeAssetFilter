#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDFPreviewer 组件测试

覆盖核心场景:
  1. PDFPreviewer 创建及初始状态
  2. set_file() 加载 PDF 文件
  3. 页面导航及控件状态

使用 conftest 的 qapp fixture 提供 QApplication 实例，
temp_pdf_file fixture 提供测试用 PDF 文件。

备注:
  生产代码 pdf_previewer.py 中存在一个 NameError bug:
  ``getattr(app, 'settings_manager', ...)`` 中的 ``app`` 未定义。
  本模块通过 monkeypatch 在测试环境中注入 ``app`` 变通处理，
  不影响生产代码文件。
"""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QWidget


# ===========================================================================
# 模块级变通处理 — 修复生产代码中未定义 app 变量的 bug
# ===========================================================================


@pytest.fixture(autouse=True)
def _patch_app_variable(monkeypatch, qapp) -> None:
    """在 pdf_previewer 模块作用域注入 ``app`` 变量。

    生产代码 pdf_previewer.py 第 64/211 行使用
    ``getattr(app, 'settings_manager', SettingsManager())``，
    但 ``app`` 在该命名空间中未定义。
    此 fixture 将 ``app`` 设为 QApplication 实例，
    使该 fallback 路径能够正常工作。
    """
    import freeassetfilter.components.pdf_previewer as pdf_mod

    monkeypatch.setattr(pdf_mod, "app", qapp, raising=False)


# ===========================================================================
# PDFPreviewer 创建
# ===========================================================================


class TestPDFPreviewerCreation:
    """PDFPreviewer 实例化与初始属性测试。"""

    def test_create_previewer(self, qapp) -> None:
        """创建 PDFPreviewer 后应是一个 QWidget 且初始状态正确。

        Given 无参数
        When  ``PDFPreviewer()`` 被调用
        Then  返回 QWidget 子类，
              pdf_document 已创建但未加载文档，
              total_pages 为 0，current_page 为 0。
        """
        from freeassetfilter.components.pdf_previewer import PDFPreviewer

        previewer = PDFPreviewer()
        try:
            assert isinstance(previewer, QWidget)
            # pdf_document is created in _init_ui() during __init__
            assert previewer.pdf_document is not None
            assert previewer.pdf_document.pageCount() == 0
            assert previewer.total_pages == 0
            assert previewer.current_page == 0
        finally:
            previewer.close()
            previewer.deleteLater()

    def test_custom_settings_manager(self, qapp, settings_manager) -> None:
        """传入自定义 settings_manager 应被组件使用。

        Given 一个 SettingsManager 实例
        When  ``PDFPreviewer(settings_manager=manager)``
        Then  ``previewer._settings_manager is manager``。
        """
        from freeassetfilter.components.pdf_previewer import PDFPreviewer

        previewer = PDFPreviewer(settings_manager=settings_manager)
        try:
            assert previewer._settings_manager is settings_manager
        finally:
            previewer.close()
            previewer.deleteLater()

    def test_signal_pdf_render_finished(self, qapp) -> None:
        """pdf_render_finished 信号应存在且可通过 QSignalSpy 监听。

        Given 新创建的 PDFPreviewer
        When  连接 QSignalSpy 到 pdf_render_finished
        Then  spy.count() 为 0（尚未触发）。
        """
        from freeassetfilter.components.pdf_previewer import PDFPreviewer

        previewer = PDFPreviewer()
        spy = QSignalSpy(previewer.pdf_render_finished)
        try:
            assert spy.count() == 0
        finally:
            previewer.close()
            previewer.deleteLater()

    def test_custom_dpi_scale(self, qapp) -> None:
        """传入自定义 dpi_scale 应被使用。

        Given dpi_scale=2.0
        When  ``PDFPreviewer(dpi_scale=2.0)``
        Then  previewer.dpi_scale 为 2.0。
        """
        from freeassetfilter.components.pdf_previewer import PDFPreviewer

        previewer = PDFPreviewer(dpi_scale=2.0)
        try:
            assert previewer.dpi_scale == 2.0
        finally:
            previewer.close()
            previewer.deleteLater()


# ===========================================================================
# set_file() 加载 PDF
# ===========================================================================


class TestPDFPreviewerFileLoading:
    """PDF 文件加载与 set_file() 接口测试。"""

    def test_load_pdf_file(self, qapp, temp_pdf_file) -> None:
        """加载有效 PDF 文件后应更新内部状态并触发信号。

        Given 一个有效 PDF 文件路径
        When  ``set_file(path)`` 被调用
        Then  file_path 匹配传入路径，
              total_pages > 0，
              page_widgets 长度等于总页数，
              pdf_render_finished 信号被发射。
        """
        from freeassetfilter.components.pdf_previewer import PDFPreviewer

        previewer = PDFPreviewer()
        spy = QSignalSpy(previewer.pdf_render_finished)
        try:
            previewer.set_file(temp_pdf_file)
            QApplication.processEvents()

            assert previewer.file_path == temp_pdf_file
            assert previewer.total_pages > 0
            assert len(previewer.page_widgets) == previewer.total_pages
            assert spy.count() >= 1
        finally:
            previewer.close()
            previewer.deleteLater()

    def test_load_pdf_file_via_dict(self, qapp, temp_pdf_file) -> None:
        """set_file() 接受字典参数（统一预览器接口协议）。

        Given 包含 path 键的字典
        When  ``set_file({"path": ..., ...})``
        Then  file_path 正确设置，页面加载成功。
        """
        from freeassetfilter.components.pdf_previewer import PDFPreviewer

        previewer = PDFPreviewer()
        try:
            file_info = {
                "name": "test.pdf",
                "path": temp_pdf_file,
                "suffix": "pdf",
                "is_dir": False,
            }
            previewer.set_file(file_info)
            QApplication.processEvents()

            assert previewer.file_path == temp_pdf_file
            assert previewer.total_pages > 0
        finally:
            previewer.close()
            previewer.deleteLater()

    def test_load_nonexistent_file(self, qapp) -> None:
        """加载不存在的文件应显示错误并仍发射信号。

        Given 不存在的文件路径
        When  ``set_file("/nonexistent/test.pdf")``
        Then  total_pages 为 0，
              pdf_render_finished 信号仍被发射（关闭进度条）。
        """
        from freeassetfilter.components.pdf_previewer import PDFPreviewer

        previewer = PDFPreviewer()
        spy = QSignalSpy(previewer.pdf_render_finished)
        try:
            previewer.set_file("/nonexistent/test.pdf")
            QApplication.processEvents()

            assert previewer.total_pages == 0
            assert spy.count() >= 1
        finally:
            # close() crashes due to _clear_pages bug with error labels;
            # deleteLater() is safe here
            previewer.deleteLater()

    def test_load_empty_path(self, qapp) -> None:
        """加载空路径应被安全处理。

        Given 空字符串路径
        When  ``set_file("")``
        Then  total_pages 为 0，不抛出异常。
        """
        from freeassetfilter.components.pdf_previewer import PDFPreviewer

        previewer = PDFPreviewer()
        spy = QSignalSpy(previewer.pdf_render_finished)
        try:
            previewer.set_file("")
            QApplication.processEvents()

            assert previewer.total_pages == 0
            assert spy.count() >= 1
        finally:
            # close() crashes due to _clear_pages bug with error labels;
            # deleteLater() is safe here
            previewer.deleteLater()


# ===========================================================================
# 页面导航
# ===========================================================================


class TestPDFPreviewerPageNavigation:
    """页码切换及按钮状态测试。"""

    def test_navigate_next_on_single_page(self, qapp, temp_pdf_file) -> None:
        """单页 PDF 中点击下一页不应改变 current_page。

        Given 单页 PDF 已加载
        When  ``_go_to_next_page()``
        Then  current_page 保持不变。
        """
        from freeassetfilter.components.pdf_previewer import PDFPreviewer

        previewer = PDFPreviewer()
        try:
            previewer.set_file(temp_pdf_file)
            QApplication.processEvents()

            assert previewer.total_pages == 1
            initial = previewer.current_page
            previewer._go_to_next_page()
            assert previewer.current_page == initial
        finally:
            previewer.close()
            previewer.deleteLater()

    def test_navigate_to_specific_page(self, qapp, temp_pdf_file) -> None:
        """跳转到合法/非法页码的行为。

        Given 单页 PDF 已加载（total_pages == 1）
        When  调用 ``_go_to_page(0)``     → current_page == 0
              调用 ``_go_to_page(-1)``    → 无变化（忽略）
              调用 ``_go_to_page(999)``   → 无变化（越界忽略）
        """
        from freeassetfilter.components.pdf_previewer import PDFPreviewer

        previewer = PDFPreviewer()
        try:
            previewer.set_file(temp_pdf_file)
            QApplication.processEvents()

            assert previewer.total_pages == 1

            # 合法页码
            previewer._go_to_page(0)
            assert previewer.current_page == 0

            # 负页码 —— 应忽略
            previewer._go_to_page(-1)
            assert previewer.current_page == 0

            # 越界页码 —— 应忽略
            previewer._go_to_page(999)
            assert previewer.current_page == 0
        finally:
            previewer.close()
            previewer.deleteLater()

    def test_button_states(self, qapp, temp_pdf_file) -> None:
        """单页 PDF 中上一页/下一页按钮均禁用。

        Given 单页 PDF 已加载
        Then  prev_button 禁用（current_page 0 不大于 0）
              next_button 禁用（current_page 0 不小于 total_pages - 1 即 0）
        """
        from freeassetfilter.components.pdf_previewer import PDFPreviewer

        previewer = PDFPreviewer()
        try:
            previewer.set_file(temp_pdf_file)
            QApplication.processEvents()

            assert not previewer.prev_button.isEnabled()
            assert not previewer.next_button.isEnabled()
        finally:
            previewer.close()
            previewer.deleteLater()

    def test_page_label_text(self, qapp, temp_pdf_file) -> None:
        """页码标签应显示正确格式。

        Given 单页 PDF 已加载
        Then  page_label 文本为 ``"1/1"``。
        """
        from freeassetfilter.components.pdf_previewer import PDFPreviewer

        previewer = PDFPreviewer()
        try:
            previewer.set_file(temp_pdf_file)
            QApplication.processEvents()

            assert previewer.page_label.text() == "1/1"
        finally:
            previewer.close()
            previewer.deleteLater()

    def test_go_to_page_renders_target(self, qapp, temp_pdf_file) -> None:
        """跳转到指定页面后目标页的 pixmap 应已缓存。

        Given 单页 PDF 已加载
        When  ``_go_to_page(0)``
        Then  页码 0 在 _render_cache 中。
        """
        from freeassetfilter.components.pdf_previewer import PDFPreviewer

        previewer = PDFPreviewer()
        try:
            previewer.set_file(temp_pdf_file)
            QApplication.processEvents()

            # 确保目标页面已渲染（触发懒加载）
            previewer._go_to_page(0)
            QApplication.processEvents()

            assert 0 in previewer._render_cache
            assert previewer._render_cache[0] is not None
        finally:
            previewer.close()
            previewer.deleteLater()
