"""
统一预览器布局 — 两个可拖拽调整比例的内容区（默认 1:1）+ 底栏
"""

import inspect
import os
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QMimeData, QUrl, Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QSizePolicy, QSplitter,
    QVBoxLayout, QWidget,
)

from components.styled_button import StyledButton
from components.styled_dialog import create_custom_dialog
from freeassetfilter.services.previewer_registry import PreviewerRegistry
from layout.preview.file_info_panel import FileInfoPanel
from theme import tm


# 音频扩展名集合（用于区分音频文件调用 VideoPlayer 的音频模式）
_AUDIO_EXTS = {
    ".mp3", ".wav", ".flac", ".ogg", ".wma", ".m4a",
    ".aiff", ".ape", ".opus", ".aac", ".ac3", ".mka",
}


def _show_custom_dialog(
    title: str,
    message: str,
    buttons: list,
    variants: Optional[list] = None,
    dialog_type: str = "default",
) -> None:
    """Styled 弹窗包装（同步阻塞），替代旧版 CustomMessageBox。

    Args:
        title: 弹窗标题。
        message: 主体文本。
        buttons: 按钮文案列表。
        variants: 与 buttons 一一对应的变体名。
        dialog_type: 弹窗类型（default/danger 等）。
    """
    from PySide6.QtCore import QEventLoop

    dlg = create_custom_dialog(
        title=title,
        message=message,
        buttons=list(buttons),
        variants=list(variants) if variants else None,
        dialog_type=dialog_type,
        show_close=False,
    )
    loop = QEventLoop()

    def _on_finished(_result: int) -> None:
        loop.quit()

    dlg.finished.connect(_on_finished)
    dlg.destroyed.connect(loop.quit)
    loop.exec()


class UnifiedPreviewerLayout(QWidget):
    """统一预览器布局（右侧栏）"""

    # 定位到当前预览文件所在目录（请求文件选择器导航并高亮该文件）
    locate_requested = Signal(dict)
    # 清除预览（清空内容区 + 两侧面板的预览态）
    clear_requested = Signal()

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

        # 内容区 2（下方）— 文件信息预览面板
        self._content_bottom = QFrame()
        self._content_bottom.setObjectName("PreviewerBottom")
        self._splitter.addWidget(self._content_bottom)

        # 文件信息面板（占满内容区 2；背景透明，透出 PreviewerBottom 样式）
        self._content_bottom_layout = QVBoxLayout(self._content_bottom)
        self._content_bottom_layout.setContentsMargins(0, 0, 0, 0)
        self._content_bottom_layout.setSpacing(0)
        self._info_panel = FileInfoPanel(self._content_bottom)
        self._content_bottom_layout.addWidget(self._info_panel)

        # 默认 1:1 比例（可见后由 _apply_default_split 精确等分）
        self._splitter.setSizes([1, 1])
        self._default_split_applied = False
        self._splitter.splitterMoved.connect(self._on_splitter_moved)

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

        # 图标按钮 — share.svg（复制到剪切板）
        share_icon = str(icons_dir / "share.svg")
        self._share_btn = StyledButton("", variant="ghost", size="sm", icon=share_icon)
        self._share_btn.setFixedSize(32, 32)
        self._share_btn.setToolTip("复制到剪切板")
        self._share_btn.clicked.connect(self._on_copy_to_clipboard_clicked)
        bottom_layout.addWidget(self._share_btn)

        # 次选按钮 — 使用系统默认方式打开
        self._open_default_btn = StyledButton(
            "使用系统默认方式打开", variant="secondary", size="sm"
        )
        self._open_default_btn.clicked.connect(self._on_open_with_system_clicked)

        # 强调按钮 — 定位到所在目录
        self._locate_btn = StyledButton(
            "定位到所在目录", variant="primary", size="sm"
        )
        self._locate_btn.clicked.connect(self._on_locate_requested)

        # 两个文字按钮等宽且随功能区宽度同步增/减：
        # Ignored 水平策略（忽略各自文本宽度差异）+ 最小宽 0 + 等 stretch=1，
        # 布局把可分配宽度二等分给两者，避免用固定宽度撑大布局最小宽度。
        for btn in (self._open_default_btn, self._locate_btn):
            btn.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            btn.setMinimumWidth(0)
            bottom_layout.addWidget(btn, 1)

        # 图标按钮 — close.svg（清除预览）
        close_icon = str(icons_dir / "close.svg")
        self._close_btn = StyledButton("", variant="ghost", size="sm", icon=close_icon)
        self._close_btn.setFixedSize(32, 32)
        self._close_btn.setToolTip("清除预览")
        self._close_btn.clicked.connect(self._on_clear_preview_clicked)
        bottom_layout.addWidget(self._close_btn)

        # 初始无预览文件：禁用底栏按钮（占位符状态）
        self._update_bottom_buttons()

    def _update_bottom_buttons(self) -> None:
        """按当前是否有预览文件启停底栏按钮（无文件时全部禁用）。"""
        has_file = self._current_file_info is not None
        self._share_btn.setEnabled(has_file)
        self._open_default_btn.setEnabled(has_file)
        self._locate_btn.setEnabled(has_file)
        self._close_btn.setEnabled(has_file)

    def _on_copy_to_clipboard_clicked(self) -> None:
        """复制当前预览文件到系统剪切板（文件引用），并提示成功。

        与旧版统一预览器 copy_to_clipboard_button 行为一致。
        """
        if not self._current_file_info:
            return

        file_path = self._current_file_info.get("path", "")
        if not file_path or not os.path.exists(file_path):
            return

        try:
            clipboard = QApplication.clipboard()
            mime_data = QMimeData()
            url = QUrl.fromLocalFile(os.path.abspath(file_path))
            mime_data.setUrls([url])
            clipboard.setMimeData(mime_data)

            _show_custom_dialog(
                "复制成功",
                "文件已复制到剪切板\n现在您可以将剪切板内的文件进行分享",
                ["确定"],
                ["primary"],
                dialog_type="success",
            )
        except Exception as exc:  # noqa: BLE001
            from freeassetfilter.utils.app_logger import error

            error(f"[UnifiedPreviewerLayout] 复制文件到剪切板失败: {exc}")

    def _on_open_with_system_clicked(self) -> None:
        """使用系统默认方式打开当前预览文件。"""
        if not self._current_file_info:
            return

        file_path = self._current_file_info.get("path", "")
        if not file_path:
            return

        # 确保文件路径是绝对路径
        file_path = os.path.abspath(file_path)

        # 检查文件是否存在
        if not os.path.exists(file_path):
            _show_custom_dialog(
                "错误",
                f"文件不存在: {file_path}",
                ["确定"],
                ["primary"],
                dialog_type="danger",
            )
            return

        try:
            if sys.platform == "win32":
                os.startfile(file_path)  # noqa: S606
            elif sys.platform == "darwin":
                os.system(f'open "{file_path}"')  # noqa: S605
            else:
                os.system(f'xdg-open "{file_path}"')  # noqa: S605
        except Exception as exc:  # noqa: BLE001
            _show_custom_dialog(
                "错误",
                f"无法打开文件: {exc}",
                ["确定"],
                ["primary"],
                dialog_type="danger",
            )

    def _on_locate_requested(self) -> None:
        """请求在左侧文件选择器中定位当前预览文件（导航 + 高亮滚动）。"""
        if not self._current_file_info:
            return
        self.locate_requested.emit(self._current_file_info)

    def _on_clear_preview_clicked(self) -> None:
        """请求清除预览（两侧面板的卡片预览态 + 预览内容）。"""
        self.clear_requested.emit()

    def set_section_styles(self, fill_color: str, border_color: str) -> None:
        """应用面板样式到内容区、底栏（主题切换时由 MainWindow 调用）。

        注意：规则必须用 objectName 选择器限定到各 QFrame 自身——
        无选择器的裸规则等价于 `*`，会级联到 _content_top 的所有后代，
        导致内嵌的 preview 子控件错误继承边框/圆角/背景。

        Args:
            fill_color: 填充色。
            border_color: 边框色。
        """
        section_style = f"""
            QFrame#PreviewerTop {{
                background-color: {fill_color};
                border: 1px solid {border_color};
                border-radius: 8px;
            }}
            QFrame#PreviewerBottom {{
                background-color: {fill_color};
                border: 1px solid {border_color};
                border-radius: 8px;
            }}
            QFrame#PreviewerBottomBar {{
                background-color: {fill_color};
                border: 1px solid {border_color};
                border-radius: 8px;
            }}
        """
        self._content_top.setStyleSheet(section_style)
        self._content_bottom.setStyleSheet(section_style)
        # 强制已显示控件重新套用样式（延迟构建场景下必须，否则边框/填充不重绘）
        self._content_top.style().unpolish(self._content_top)
        self._content_top.style().polish(self._content_top)
        self._content_bottom.style().unpolish(self._content_bottom)
        self._content_bottom.style().polish(self._content_bottom)
        self._bottom_bar.setStyleSheet(section_style)

    def _on_theme_changed(self, theme: str) -> None:
        """主题切换时占位（样式由 MainWindow 统一刷新）"""
    
    def cleanup(self) -> None:
        """释放后台资源（主窗口关闭时调用）：停止文件信息面板的采集线程。"""
        try:
            self._info_panel.stop()
        except (RuntimeError, AttributeError):
            pass
    
    # ── 分割区高度规则 ──
    # 规则：
    # 1) 默认起始状态与「取消预览」后，上下两区各占可用高度的一半；
    # 2) 文件信息预览器（下方）的最高高度被限制为可用高度的一半，
    #    因此预览内容区始终至少占一半；把手只能把信息区在下限以上、
    #    半高以内拖动，无法越过半高。

    def _splitter_available_height(self) -> int:
        """分割区内可用于两个内容区的总高度（不含把手）。"""
        return max(0, self._splitter.height() - self._splitter.handleWidth())

    def _apply_default_split(self) -> None:
        """恢复默认等分：上下各占可用高度的一半。

        分割区尚未布局（高度未知）时退回等比例 [1, 1]，
        布局后 Qt 会按比例自然实现 50/50。
        """
        available = self._splitter_available_height()
        if available <= 0:
            self._splitter.setSizes([1, 1])
            return
        half = available // 2
        self._splitter.setSizes([available - half, half])

    def _ensure_split_rules(self) -> None:
        """把信息面板最高高度限制为可用高度的一半，并对超限状态兜底钳制。

        窗口尺寸变化 / 把手移动 / 程序化 setSizes 后都应调用（幂等）。
        """
        available = self._splitter_available_height()
        if available <= 0:
            return
        half = available // 2
        # QSplitter 拖动与 setSizes 均遵循该最大高度，信息区无法越过半高
        self._content_bottom.setMaximumHeight(half)
        if self._content_bottom.height() > half:
            self._splitter.setSizes([available - half, half])

    def _on_splitter_moved(self, _pos: int, _index: int) -> None:
        """把手移动后：确保信息区不越过半高；首次获得尺寸时应用默认等分。"""
        if not self._default_split_applied and self._splitter.height() > 0:
            self._default_split_applied = True
            if self._current_file_info is None:
                self._apply_default_split()
        self._ensure_split_rules()

    def resizeEvent(self, event) -> None:  # noqa: N802
        """窗口缩放：重算信息区半高上限；首次可见时精确应用默认等分。"""
        super().resizeEvent(event)
        if not self._default_split_applied and self._splitter.height() > 0:
            self._default_split_applied = True
            if self._current_file_info is None:
                self._apply_default_split()
        self._ensure_split_rules()
    
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
        
        # 文件夹：路由到文件夹预览器（仅文件池文件夹卡片点击触发，
        # 与文件选择器的常规文件夹导航相独立）。
        is_dir = bool(file_info.get("is_dir", False))
        if is_dir:
            if not file_info.get("path"):
                self.clear_preview()
                return
        elif "path" not in file_info or "suffix" not in file_info:
            # 缺少必要字段：清空预览
            self.clear_preview()
            return
        
        # 更新当前文件信息
        self._current_file_info = file_info
        self._update_bottom_buttons()
        self._info_panel.set_file(file_info)
        self._load_preview(file_info)
    
    def clear_preview(self) -> None:
        """清空预览区，显示占位符，并恢复默认等分（上下各半）。"""
        self._cleanup_current_preview()
        self._current_file_info = None
        self._update_bottom_buttons()
        self._show_placeholder()
        self._info_panel.clear()
        # 取消文件预览后恢复默认高度：两区各占一半
        self._apply_default_split()
        self._ensure_split_rules()
    
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
            self._placeholder_label = QLabel("选择文件以预览内容")
            self._placeholder_label.setAlignment(Qt.AlignCenter)
            self._placeholder_label.setStyleSheet(
                f"color: {tm.mid.name()}; font-size: 14px; background: transparent;"
            )
        
        # 添加到布局并确保可见（_cleanup_current_preview 会 hide 它）
        if self._content_layout is not None:
            self._content_layout.addWidget(self._placeholder_label)
            self._placeholder_label.show()
    
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
            # 同类型，复用预览器。
            # 注意：不在此处调用 stop_playback()——mpv 的 loadfile 命令会直接替换
            # 当前播放项；先 stop 反而会清空播放列表，使 mpv（idle=no 默认行为）
            # 触发 SHUTDOWN 退出核心，导致同实例后续所有加载失败。
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
