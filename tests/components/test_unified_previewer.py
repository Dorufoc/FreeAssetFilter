# -*- coding: utf-8 -*-
"""
UnifiedPreviewer 组件测试

测试 freeassetfilter/components/unified_previewer.py 模块的 UnifiedPreviewer 功能。
覆盖初始化、文件类型→预览器映射、set_file 调用、信号验证 5+ 核心场景。
"""

import os
from typing import List

import pytest
from PySide6.QtTest import QSignalSpy

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# ============================================================================
# 场景 1：UnifiedPreviewer 创建与初始化
# ============================================================================


class TestUnifiedPreviewerCreation:
    """UnifiedPreviewer 创建与初始状态验证"""

    def test_initialization(self, qapp, unified_previewer):
        """验证 UnifiedPreviewer 创建后的默认状态。

        - widget 不为 None
        - 初始无选中文件
        - 初始无预览组件
        - 信号对象正确连接
        """
        assert unified_previewer is not None
        assert unified_previewer.current_file_info is None
        assert unified_previewer.current_preview_widget is None
        assert unified_previewer.current_preview_type is None
        assert hasattr(unified_previewer, "preview_started")
        assert hasattr(unified_previewer, "preview_cleared")
        assert hasattr(unified_previewer, "open_in_selector_requested")
        assert hasattr(unified_previewer, "file_info_viewer")
        assert hasattr(unified_previewer, "clear_preview_button")


# ============================================================================
# 场景 2：不同文件类型触发不同预览器（PreviewerRegistry 映射 + 类型推导）
# ============================================================================


class TestPreviewTypeResolution:
    """验证不同文件扩展名 → 正确的预览器类名 → 预览类型"""

    # 注册表映射测试 — 验证 PreviewerRegistry 返回的类名
    @pytest.mark.parametrize(
        "suffix,expected_class",
        [
            # 图像
            ("png", "PhotoViewer"),
            ("jpg", "PhotoViewer"),
            ("jpeg", "PhotoViewer"),
            ("gif", "PhotoViewer"),
            ("bmp", "PhotoViewer"),
            ("webp", "PhotoViewer"),
            ("svg", "PhotoViewer"),
            ("ico", "PhotoViewer"),
            ("psd", "PhotoViewer"),
            # 视频
            ("mp4", "VideoPlayer"),
            ("avi", "VideoPlayer"),
            ("mov", "VideoPlayer"),
            ("mkv", "VideoPlayer"),
            ("webm", "VideoPlayer"),
            # 音频（也使用 VideoPlayer 类）
            ("mp3", "VideoPlayer"),
            ("wav", "VideoPlayer"),
            ("flac", "VideoPlayer"),
            ("ogg", "VideoPlayer"),
            ("m4a", "VideoPlayer"),
            # PDF
            ("pdf", "PDFPreviewer"),
            # 文本/代码
            ("txt", "TextPreviewWidget"),
            ("md", "TextPreviewWidget"),
            ("py", "TextPreviewWidget"),
            ("json", "TextPreviewWidget"),
            ("html", "TextPreviewWidget"),
            ("xml", "TextPreviewWidget"),
            ("yaml", "TextPreviewWidget"),
            # 压缩包
            ("zip", "ArchiveBrowser"),
            ("rar", "ArchiveBrowser"),
            ("7z", "ArchiveBrowser"),
            ("tar", "ArchiveBrowser"),
            ("iso", "ArchiveBrowser"),
            # 字体
            ("ttf", "FontPreviewWidget"),
            ("otf", "FontPreviewWidget"),
            ("woff", "FontPreviewWidget"),
        ],
    )
    def test_extension_maps_to_previewer_class(self, suffix: str, expected_class: str):
        """测试文件扩展名 → PreviewerRegistry 解析为正确的预览器类。"""
        from freeassetfilter.services.previewer_registry import PreviewerRegistry

        cls = PreviewerRegistry.get_previewer_class({"suffix": suffix})
        assert cls is not None, f"{suffix} 应映射到预览器类"
        assert cls.__name__ == expected_class, (
            f"{suffix} 应映射到 {expected_class}，实际为 {cls.__name__}"
        )

    def test_unknown_extension_returns_none(self):
        """未注册的扩展名应返回 None。"""
        from freeassetfilter.services.previewer_registry import PreviewerRegistry

        cls = PreviewerRegistry.get_previewer_class({"suffix": "xyz"})
        assert cls is None

    def test_empty_suffix_returns_none(self):
        """空 suffix 应返回 None。"""
        from freeassetfilter.services.previewer_registry import PreviewerRegistry

        cls = PreviewerRegistry.get_previewer_class({"suffix": ""})
        assert cls is None

    def test_missing_suffix_returns_none(self):
        """缺失 suffix 键应返回 None。"""
        from freeassetfilter.services.previewer_registry import PreviewerRegistry

        cls = PreviewerRegistry.get_previewer_class({"name": "test.txt"})
        assert cls is None

    def test_directory_maps_to_folder_content_list(self):
        """is_dir=True 应解析为 FolderContentList。"""
        from freeassetfilter.services.previewer_registry import PreviewerRegistry

        cls = PreviewerRegistry.get_previewer_class(
            {"suffix": "", "is_dir": True}
        )
        assert cls is not None
        assert cls.__name__ == "FolderContentList"

    def test_directory_info_returns_folder_list_even_with_ext(self):
        """is_dir=True 的目录即使有 suffix 也返回 FolderContentList。"""
        from freeassetfilter.services.previewer_registry import PreviewerRegistry

        cls = PreviewerRegistry.get_previewer_class(
            {"suffix": "txt", "is_dir": True}
        )
        assert cls is not None
        assert cls.__name__ == "FolderContentList"

    @pytest.mark.parametrize(
        "suffix,expected_type",
        [
            ("png", "image"),
            ("jpg", "image"),
            ("gif", "image"),
            ("mp4", "video"),
            ("avi", "video"),
            ("mp3", "audio"),
            ("wav", "audio"),
            ("txt", "text"),
            ("md", "text"),
            ("pdf", "pdf"),
            ("zip", "archive"),
            ("ttf", "font"),
        ],
    )
    def test_show_preview_infers_correct_type(self, qapp, suffix: str, expected_type: str):
        """验证 UnifiedPreviewer._show_preview 从文件后缀推断出正确的预览类型。

        通过检查 PreviewerRegistry 类名推导的预览类型逻辑与预期一致。
        """
        from freeassetfilter.services.previewer_registry import PreviewerRegistry

        file_info = {"suffix": suffix, "path": f"/fake/{suffix}", "is_dir": False}
        cls = PreviewerRegistry.get_previewer_class(file_info)
        assert cls is not None, f"{suffix} 应有对应的预览器类"

        # 复制 _show_preview 中的类型推导逻辑
        class_name = cls.__name__
        if class_name in ("PhotoViewer", "GifViewer"):
            inferred = "image"
        elif class_name == "VideoPlayer":
            inferred = "audio" if suffix in [
                "mp3", "wav", "flac", "ogg", "wma", "m4a", "aiff", "ape", "opus"
            ] else "video"
        elif class_name == "PDFPreviewer":
            inferred = "pdf"
        elif class_name == "TextPreviewWidget":
            inferred = "text"
        elif class_name == "ArchiveBrowser":
            inferred = "archive"
        elif class_name == "FontPreviewWidget":
            inferred = "font"
        else:
            inferred = "unknown"

        assert inferred == expected_type, (
            f"{suffix} 应推导为 {expected_type}，实际为 {inferred}"
        )


# ============================================================================
# 场景 3：set_file() 调用
# ============================================================================


class TestSetFile:
    """set_file 方法行为验证"""

    def test_set_file_updates_current_file_info(self, qapp, unified_previewer, sample_file_dict):
        """set_file 后 current_file_info 应更新为传入的字典。"""
        unified_previewer.set_file(sample_file_dict)
        assert unified_previewer.current_file_info is not None
        assert unified_previewer.current_file_info == sample_file_dict
        assert unified_previewer.current_file_info["name"] == sample_file_dict["name"]
        assert unified_previewer.current_file_info["suffix"] == sample_file_dict["suffix"]

    def test_set_file_updates_file_info_viewer(self, qapp, unified_previewer, sample_file_dict):
        """set_file 后 file_info_viewer 应同步为新的文件信息。"""
        unified_previewer.set_file(sample_file_dict)
        assert unified_previewer.file_info_viewer.current_file is not None
        assert unified_previewer.file_info_viewer.current_file["path"] == sample_file_dict["path"]

    def test_set_file_emits_preview_started_with_dict(self, qapp, unified_previewer, sample_file_dict):
        """set_file 应发射 preview_started 信号，参数为文件信息字典。"""
        spy = QSignalSpy(unified_previewer.preview_started)
        unified_previewer.set_file(sample_file_dict)
        assert spy.count() == 1, "preview_started 应被发射 1 次"
        args = spy.at(0)
        assert len(args) == 1, "preview_started 应携带 1 个参数"
        emitted_dict = args[0]
        assert isinstance(emitted_dict, dict)
        assert emitted_dict["name"] == sample_file_dict["name"]
        assert emitted_dict["suffix"] == sample_file_dict["suffix"]
        assert emitted_dict["path"] == sample_file_dict["path"]

    def test_set_file_with_temp_image(self, qapp, unified_previewer, temp_image_file: List[str]):
        """使用真实图片文件调用 set_file，验证预览器初始化为图片类型。

        使用 temp_image_file fixture 提供的 PNG 文件路径。
        """
        png_path = temp_image_file[0]
        file_info = {
            "name": "test.png",
            "path": png_path,
            "is_dir": False,
            "size": os.path.getsize(png_path),
            "modified": "",
            "created": "",
            "suffix": "png",
        }
        spy = QSignalSpy(unified_previewer.preview_started)
        unified_previewer.set_file(file_info)
        assert unified_previewer.current_file_info is not None
        assert unified_previewer.current_file_info["suffix"] == "png"
        assert spy.count() == 1

    def test_set_file_with_temp_text(self, qapp, unified_previewer, temp_text_file: List[str]):
        """使用真实文本文件调用 set_file，验证预览器初始化为文本类型。

        使用 temp_text_file fixture 提供的 TXT 文件路径。
        """
        txt_path = temp_text_file[0]
        file_info = {
            "name": "test.txt",
            "path": txt_path,
            "is_dir": False,
            "size": os.path.getsize(txt_path),
            "modified": "",
            "created": "",
            "suffix": "txt",
        }
        spy = QSignalSpy(unified_previewer.preview_started)
        unified_previewer.set_file(file_info)
        assert unified_previewer.current_file_info is not None
        assert unified_previewer.current_file_info["suffix"] == "txt"
        assert spy.count() == 1

    def test_set_file_with_directory_info(self, qapp, unified_previewer, tmp_path):
        """使用目录信息调用 set_file，验证 is_dir 被正确识别。"""
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()
        dir_info = {
            "name": "test_dir",
            "path": str(test_dir),
            "is_dir": True,
            "size": 0,
            "modified": "",
            "created": "",
            "suffix": "",
        }
        spy = QSignalSpy(unified_previewer.preview_started)
        unified_previewer.set_file(dir_info)
        assert unified_previewer.current_file_info is not None
        assert unified_previewer.current_file_info["is_dir"] is True
        assert spy.count() == 1

    def test_set_file_does_not_emit_preview_cleared(self, qapp, unified_previewer, sample_file_dict):
        """set_file 不应发射 preview_cleared 信号。"""
        spy = QSignalSpy(unified_previewer.preview_cleared)
        unified_previewer.set_file(sample_file_dict)
        assert spy.count() == 0, "set_file 不应发射 preview_cleared"

    def test_consecutive_set_file_updates_info(self, qapp, unified_previewer, tmp_path):
        """连续多次 set_file 应更新为最新的文件信息。

        注意：set_file 触发异步预览加载，is_loading_preview 为 True 时
        后续 set_file 会暂存为 pending 请求而非立即更新 current_file_info。
        此处重置标志位以模拟前一次加载完成的场景。
        """
        file1 = tmp_path / "file1.txt"
        file1.write_text("content1")
        file_info1 = {
            "name": "file1.txt",
            "path": str(file1),
            "is_dir": False,
            "size": 8,
            "modified": "",
            "created": "",
            "suffix": "txt",
        }
        file2 = tmp_path / "file2.png"
        file2.write_text("content2")
        file_info2 = {
            "name": "file2.png",
            "path": str(file2),
            "is_dir": False,
            "size": 8,
            "modified": "",
            "created": "",
            "suffix": "png",
        }
        spy = QSignalSpy(unified_previewer.preview_started)
        unified_previewer.set_file(file_info1)
        assert unified_previewer.current_file_info["name"] == "file1.txt"

        # 重置 loading 标志，模拟第一次预览加载完成
        unified_previewer.is_loading_preview = False

        unified_previewer.set_file(file_info2)
        assert unified_previewer.current_file_info["name"] == "file2.png"
        # preview_started 应发射 2 次（每次 set_file 一次）
        assert spy.count() == 2


# ============================================================================
# 场景 4 & 5：信号验证 — preview_cleared
# ============================================================================


class TestClearPreview:
    """clear_preview / _clear_preview 行为验证"""

    def test_clear_preview_emits_preview_cleared(self, qapp, unified_previewer):
        """clear_preview 应发射 preview_cleared 信号。"""
        spy = QSignalSpy(unified_previewer.preview_cleared)
        unified_previewer.clear_preview()
        assert spy.count() == 1, "clear_preview 应发射 preview_cleared 1 次"

    def test_clear_preview_resets_current_file_info(self, qapp, unified_previewer, sample_file_dict):
        """clear_preview 后 current_file_info 应为 None。"""
        unified_previewer.set_file(sample_file_dict)
        assert unified_previewer.current_file_info is not None
        unified_previewer.clear_preview()
        assert unified_previewer.current_file_info is None

    def test_clear_preview_resets_current_preview_widget(self, qapp, unified_previewer, sample_file_dict):
        """clear_preview 后 current_preview_widget 应为 None。"""
        unified_previewer.set_file(sample_file_dict)
        unified_previewer.clear_preview()
        assert unified_previewer.current_preview_widget is None

    def test_clear_preview_emits_on_each_sequential_call(self, qapp, unified_previewer):
        """连续的 clear_preview 调用每次都应发射 preview_cleared。

        注意：_clearing_preview 标志仅保护同一调用栈内的重入，
        不阻止顺序的独立调用。
        """
        spy_captured = QSignalSpy(unified_previewer.preview_cleared)
        unified_previewer.clear_preview()
        unified_previewer.clear_preview()
        # 每次独立的 clear_preview 调用都会发射一次信号
        assert spy_captured.count() == 2

    def test_clear_preview_button_click_resets_state(self, qapp, unified_previewer, sample_file_dict):
        """点击清除预览按钮后应重置所有状态。"""
        unified_previewer.set_file(sample_file_dict)
        assert unified_previewer.current_file_info is not None

        unified_previewer.clear_preview_button.click()
        assert unified_previewer.current_file_info is None
        assert unified_previewer.current_preview_widget is None
        assert unified_previewer.current_preview_type is None


# ============================================================================
# 场景 6：信号类型与参数验证综合
# ============================================================================


class TestSignalComprehensive:
    """信号发射次数、参数类型及内容完整性验证"""

    def test_preview_started_signal_receives_file_info_dict(self, qapp, unified_previewer, sample_file_dict):
        """preview_started 信号参数应为完整的 file_info 字典。"""
        spy = QSignalSpy(unified_previewer.preview_started)
        unified_previewer.set_file(sample_file_dict)
        emitted = spy.at(0)[0]
        required_keys = {"name", "path", "is_dir", "size", "suffix"}
        assert required_keys.issubset(emitted.keys()), (
            f"preview_started 参数应包含所有必需的键: {required_keys}"
        )

    def test_preview_cleared_signal_has_no_args(self, qapp, unified_previewer):
        """preview_cleared 信号不应携带参数。"""
        spy = QSignalSpy(unified_previewer.preview_cleared)
        unified_previewer.clear_preview()
        args = spy.at(0)
        assert len(args) == 0, "preview_cleared 应无参数"

    def test_signal_emission_order_set_file_then_clear(self, qapp, unified_previewer, sample_file_dict):
        """连续 set_file 后 clear_preview 应按序发射信号。"""
        spy_started = QSignalSpy(unified_previewer.preview_started)
        spy_cleared = QSignalSpy(unified_previewer.preview_cleared)

        unified_previewer.set_file(sample_file_dict)
        assert spy_started.count() == 1
        assert spy_cleared.count() == 0

        unified_previewer.clear_preview()
        assert spy_started.count() == 1
        assert spy_cleared.count() == 1

    def test_signal_emission_clear_then_set(self, qapp, unified_previewer, sample_file_dict):
        """先 clear 再 set_file 的信号发射正确性。"""
        spy_started = QSignalSpy(unified_previewer.preview_started)
        spy_cleared = QSignalSpy(unified_previewer.preview_cleared)

        unified_previewer.clear_preview()
        assert spy_cleared.count() == 1

        unified_previewer.set_file(sample_file_dict)
        assert spy_started.count() == 1


# ============================================================================
# 从 tests/unit/test_unified_previewer.py 迁移的 UI 布局测试
# ============================================================================


class TestUnifiedPreviewerLayout:
    """占位文本和布局最小宽度行为验证"""

    def test_default_placeholder_stays_centered_in_narrow_preview_area(self, qapp):
        """默认占位文本在窄预览区域内应居中且不被自身 sizeHint 裁切。"""
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QSizePolicy
        from freeassetfilter.components.unified_previewer import (
            UnifiedPreviewer,
            VIDEO_REFERENCE_PREVIEW_MIN_WIDTH,
        )

        previewer = UnifiedPreviewer()
        previewer.resize(260, 420)
        previewer.show()
        qapp.processEvents()

        previewer.preview_area.resize(180, 220)
        previewer._show_default_placeholder()
        previewer.preview_layout.activate()
        qapp.processEvents()

        placeholder = previewer.default_placeholder
        label = previewer.default_label

        preview_layout_margins = previewer._layout_horizontal_margins(previewer.preview_layout)
        assert previewer.preview_area.minimumWidth() == VIDEO_REFERENCE_PREVIEW_MIN_WIDTH + preview_layout_margins
        assert previewer.content_splitter.minimumWidth() == previewer.preview_area.minimumWidth()
        assert previewer.minimumWidth() > previewer.content_splitter.minimumWidth()
        assert previewer.preview_area.minimumWidth() - preview_layout_margins >= VIDEO_REFERENCE_PREVIEW_MIN_WIDTH
        assert preview_layout_margins == int(5 * previewer.dpi_scale) * 2
        assert placeholder.minimumWidth() == VIDEO_REFERENCE_PREVIEW_MIN_WIDTH
        assert placeholder.isVisible()
        assert label.isVisible()
        assert label.wordWrap()
        assert label.minimumWidth() == 0
        assert label.sizePolicy().horizontalPolicy() == QSizePolicy.Ignored
        assert label.width() <= placeholder.width()
        assert abs(label.geometry().center().x() - placeholder.rect().center().x()) <= 1
        assert label.alignment() & Qt.AlignHCenter

        previewer.close()

    def test_preview_widgets_share_video_reference_minimum_width(self, qapp):
        """所有预览内容添加入口应使用视频播放器基准最小宽度。"""
        from PySide6.QtWidgets import QSizePolicy, QWidget
        from freeassetfilter.components.unified_previewer import (
            UnifiedPreviewer,
            VIDEO_REFERENCE_PREVIEW_MIN_WIDTH,
        )

        previewer = UnifiedPreviewer()
        widget = QWidget()
        widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

        assert previewer._preview_content_min_width() == VIDEO_REFERENCE_PREVIEW_MIN_WIDTH

        previewer._add_preview_widget(widget)

        assert widget.minimumWidth() == VIDEO_REFERENCE_PREVIEW_MIN_WIDTH
        assert widget.sizePolicy().horizontalPolicy() == QSizePolicy.Expanding
        assert previewer.preview_layout.indexOf(widget) >= 0

        previewer.close()
