"""
统一预览器布局 — 两个可拖拽调整比例的内容区（默认 1:1）+ 底栏
"""

import inspect
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSplitter, QVBoxLayout, QWidget

from components.styled_button import StyledButton
from freeassetfilter.services.previewer_registry import PreviewerRegistry
from theme import tm


# 音频扩展名集合（用于区分音频文件调用 VideoPlayer 的音频模式）
_AUDIO_EXTS = {
    ".mp3", ".wav", ".flac", ".ogg", ".wma", ".m4a",
    ".aiff", ".ape", ".opus", ".aac", ".ac3", ".mka",
}


class UnifiedPreviewerLayout(QWidget):
    """统一预览器布局（右侧栏）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 预览器管理属性
        self._current_preview_widget: Optional[QWidget] = None
        self._current_preview_type: Optional[type] = None
        self._current_file_info: Optional[dict] = None
        self._placeholder_label: Optional[QLabel] = None
        self._content_layout: Optional[QVBoxLayout] = None
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # 可拖拽分割的两个内容区
        self._splitter = QSplitter(Qt.Vertical)
        self._splitter.setHandleWidth(10)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: transparent;
                height: 6px;
            }
        """)

        # 内容区 1（上方）
        self._content_top = QFrame()
        self._content_top.setObjectName("PreviewerTop")
        self._splitter.addWidget(self._content_top)

        # 内容区 2（下方）
        self._content_bottom = QFrame()
        self._content_bottom.setObjectName("PreviewerBottom")
        self._splitter.addWidget(self._content_bottom)

        # 默认 1:1 比例
        self._splitter.setSizes([1, 1])

        layout.addWidget(self._splitter, stretch=1)

        # 底栏（固定高度）
        self._bottom_bar = QFrame()
        self._bottom_bar.setObjectName("PreviewerBottomBar")
        self._bottom_bar.setFixedHeight(48)
        self._build_bottom_bar()
        layout.addWidget(self._bottom_bar)

        self.setLayout(layout)
        
        # 初始化占位符
        self._show_placeholder()

        # 主题切换时刷新颜色
        tm.theme_changed.connect(self._on_theme_changed)

    def _build_bottom_bar(self) -> None:
        """构建底栏：share + 打开方式 + 定位目录 + close"""
        icons_dir = Path(__file__).resolve().parent.parent.parent / "icons"
        bottom_layout = QHBoxLayout(self._bottom_bar)
        bottom_layout.setContentsMargins(10, 6, 10, 6)
        bottom_layout.setSpacing(6)

        # 图标按钮 — share.svg
        share_icon = str(icons_dir / "share.svg")
        self._share_btn = StyledButton("", variant="ghost", size="sm", icon=share_icon)
        self._share_btn.setFixedSize(32, 32)
        bottom_layout.addWidget(self._share_btn)

        # 次选按钮 — 使用系统默认方式打开
        self._open_default_btn = StyledButton(
            "使用系统默认方式打开", variant="secondary", size="sm"
        )
        bottom_layout.addWidget(self._open_default_btn)

        # 强调按钮 — 定位到所在目录
        self._locate_btn = StyledButton(
            "定位到所在目录", variant="primary", size="sm"
        )
        bottom_layout.addWidget(self._locate_btn)

        # 图标按钮 — close.svg
        close_icon = str(icons_dir / "close.svg")
        self._close_btn = StyledButton("", variant="ghost", size="sm", icon=close_icon)
        self._close_btn.setFixedSize(32, 32)
        bottom_layout.addWidget(self._close_btn)

    def set_section_styles(self, fill_color: str, border_color: str) -> None:
        """应用面板样式到内容区、底栏（主题切换时由 MainWindow 调用）"""
        section_style = f"""
            background-color: {fill_color};
            border: 1px solid {border_color};
            border-radius: 8px;
        """
        self._content_top.setStyleSheet(section_style)
        self._content_bottom.setStyleSheet(section_style)
        self._bottom_bar.setStyleSheet(section_style)

    def _on_theme_changed(self, theme: str) -> None:
        """主题切换时占位（样式由 MainWindow 统一刷新）"""
    
    # ── 公共 API ──
    
    def set_file(self, file_info: Optional[dict]) -> None:
        """设置要预览的文件信息，自动选择并显示对应的预览器。
        
        Args:
            file_info: 文件信息字典，包含 'path', 'suffix', 'is_dir' 等字段。
                       传入 None 时清空预览区。
        """
        # 无效输入：清空预览
        if not file_info:
            self.clear_preview()
            return
        
        # 文件夹：清空预览（文件夹预览器未来实现）
        if file_info.get("is_dir", False):
            self.clear_preview()
            return
        
        # 缺少必要字段：清空预览
        if "path" not in file_info or "suffix" not in file_info:
            self.clear_preview()
            return
        
        # 更新当前文件信息
        self._current_file_info = file_info
        self._load_preview(file_info)
    
    def clear_preview(self) -> None:
        """清空预览区，显示占位符。"""
        self._cleanup_current_preview()
        self._current_file_info = None
        self._show_placeholder()
    
    # ── 内部方法 ──
    
    def _get_previewer_class(self, file_info: dict) -> Optional[type]:
        """根据文件信息获取对应的预览器类。
        
        Args:
            file_info: 文件信息字典
            
        Returns:
            预览器类，如无匹配则返回 None
        """
        return PreviewerRegistry.get_previewer_class(file_info)
    
    def _get_preview_type(self, file_info: dict) -> Optional[type]:
        """获取文件对应的预览器类型（与 _get_previewer_class 相同）。
        
        Args:
            file_info: 文件信息字典
            
        Returns:
            预览器类，如无匹配则返回 None
        """
        return self._get_previewer_class(file_info)
    
    def _is_audio_file(self, file_info: dict) -> bool:
        """判断文件是否为音频文件。
        
        Args:
            file_info: 文件信息字典
            
        Returns:
            是否为音频文件
        """
        suffix = file_info.get("suffix", "")
        if not suffix:
            return False
        suffix = suffix.lower()
        return suffix in _AUDIO_EXTS
    
    def _show_placeholder(self) -> None:
        """在 _content_top 显示占位符标签。"""
        # 确保布局存在
        self._ensure_content_layout()
        
        # 清理当前预览器
        self._cleanup_current_preview()
        
        # 创建占位符标签
        if self._placeholder_label is None:
            self._placeholder_label = QLabel("选择文件以预览")
            self._placeholder_label.setAlignment(Qt.AlignCenter)
            self._placeholder_label.setStyleSheet(
                f"color: {tm.mid.name()}; font-size: 14px; background: transparent;"
            )
        
        # 添加到布局
        if self._content_layout is not None:
            self._content_layout.addWidget(self._placeholder_label)
    
    def _ensure_content_layout(self) -> None:
        """确保 _content_top 有且仅有一个 QVBoxLayout，避免布局泄漏。"""
        # 如果已存在布局，检查是否为 QVBoxLayout
        existing_layout = self._content_top.layout()
        if existing_layout is not None:
            # 已存在布局，直接复用
            self._content_layout = existing_layout
            return
        
        # 创建新布局
        self._content_layout = QVBoxLayout(self._content_top)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(0)
    
    def _cleanup_current_preview(self) -> None:
        """清理当前预览器控件。"""
        # 隐藏并移除占位符
        if self._placeholder_label is not None:
            self._placeholder_label.hide()
            if self._content_layout is not None:
                self._content_layout.removeWidget(self._placeholder_label)
        
        # 清理当前预览器
        if self._current_preview_widget is not None:
            # 如果预览器有 stop_playback 方法，调用它（视频/音频预览器）
            if hasattr(self._current_preview_widget, "stop_playback"):
                try:
                    self._current_preview_widget.stop_playback()
                except (RuntimeError, AttributeError):
                    pass
            
            # 如果预览器有 cleanup 方法，调用它
            if hasattr(self._current_preview_widget, "cleanup"):
                try:
                    self._current_preview_widget.cleanup()
                except (RuntimeError, AttributeError):
                    pass
            
            # 从布局中移除
            if self._content_layout is not None:
                self._content_layout.removeWidget(self._current_preview_widget)
            
            # 设置父对象为 None 并标记删除
            self._current_preview_widget.setParent(None)
            self._current_preview_widget.deleteLater()
            self._current_preview_widget = None
            self._current_preview_type = None
    
    def _load_preview(self, file_info: dict) -> None:
        """加载文件预览。
        
        Args:
            file_info: 文件信息字典
        """
        # 获取预览器类
        previewer_class = self._get_previewer_class(file_info)
        if previewer_class is None:
            # 无对应预览器，显示占位符
            self._show_placeholder()
            return
        
        # 确保布局存在
        self._ensure_content_layout()
        
        # 获取文件路径
        file_path = file_info.get("path", "")
        
        # 判断是否需要切换预览器
        same_type = (self._current_preview_type == previewer_class)
        
        if same_type and self._current_preview_widget is not None:
            # 同类型，复用预览器
            # 先停止当前播放（视频/音频）
            if hasattr(self._current_preview_widget, "stop_playback"):
                try:
                    self._current_preview_widget.stop_playback()
                except (RuntimeError, AttributeError):
                    pass
        else:
            # 不同类型或无当前预览器，清理并创建新的
            self._cleanup_current_preview()
            
            # 创建新预览器实例
            try:
                self._current_preview_widget = previewer_class(self._content_top)
                self._current_preview_type = previewer_class
                
                # 添加到布局
                if self._content_layout is not None:
                    self._content_layout.addWidget(self._current_preview_widget)
            except Exception:  # noqa: BLE001
                # 创建失败，显示占位符
                self._show_placeholder()
                return
        
        # 隐藏占位符
        if self._placeholder_label is not None:
            self._placeholder_label.hide()
            if self._content_layout is not None:
                self._content_layout.removeWidget(self._placeholder_label)
        
        # 调用预览器的 set_file 方法
        try:
            # 判断是否为音频文件
            is_audio = self._is_audio_file(file_info)
            
            # 根据预览器类型调用不同的 set_file 签名
            if is_audio and hasattr(self._current_preview_widget, "set_file"):
                # 音频文件：调用 set_file(file_path, is_audio=True)
                # 检查 set_file 是否接受 is_audio 参数
                sig = inspect.signature(self._current_preview_widget.set_file)
                if "is_audio" in sig.parameters:
                    self._current_preview_widget.set_file(file_path, is_audio=True)
                else:
                    # 不支持 is_audio 参数，直接调用
                    self._current_preview_widget.set_file(file_path)
            elif hasattr(self._current_preview_widget, "set_file"):
                # 其他文件：调用 set_file(file_path)
                self._current_preview_widget.set_file(file_path)
        except (RuntimeError, AttributeError, TypeError):
            # 加载失败，清理并显示占位符
            self._cleanup_current_preview()
            self._show_placeholder()
