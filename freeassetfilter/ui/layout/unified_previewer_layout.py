"""
统一预览器布局 — 预览内容区 + 操作底栏 / 预览器顶栏（文件信息面板已外置）

历史版本内置的「文件信息预览」下半区已拆分为独立组件（``FileInfoPanel``），
由主布局装配层（``MainLayout`` 的 info 区域）承载；本组件只负责预览内容
与统一操作（复制到剪切板 / 系统打开 / 定位目录 / 清除预览）。

统一操作按钮有两种承载方式（由主窗口按布局模式下发
:meth:`UnifiedPreviewerLayout.set_actions_mode`）：

- 经典布局：底部操作栏（历史行为，逐像素不变）；
- New 布局：底部操作栏隐藏，图标按钮注入「预览器统一的顶部工具栏」——
  预览器自带顶栏时注入其顶栏（``unified_action_host`` 协议），
  无顶栏的预览器（视频 / 音频 / Office）由本容器在内容区顶部提供一条统一工具栏。
"""

import inspect
import os
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QMimeData, QUrl, Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QSizePolicy,
    QVBoxLayout, QWidget,
)

from components.styled_button import StyledButton
from components.styled_dialog import ask_custom_dialog
from freeassetfilter.services.previewer_registry import PreviewerRegistry
from freeassetfilter.core._paths import icons_dir as get_icons_dir
from freeassetfilter.ui.theme.app_stylesheet import register_widget_qss
from freeassetfilter.utils.app_logger import warning
from layout.preview.preview_toolbar import PreviewToolbarFrame
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
    """同步提示弹窗（委托公共同步助手 ``styled_dialog.ask_custom_dialog``）。

    预览器内的提示类弹窗只关心提示本身，不关心返回值；统一不显示
    右上角关闭按钮（都有"确定"作为退出路径）。

    Args:
        title: 弹窗标题。
        message: 主体文本。
        buttons: 按钮文案列表。
        variants: 与 buttons 一一对应的变体名。
        dialog_type: 弹窗类型（default/danger 等）。
    """
    ask_custom_dialog(
        title=title,
        message=message,
        buttons=list(buttons),
        variants=list(variants) if variants else None,
        dialog_type=dialog_type,
        show_close=False,
    )


class UnifiedPreviewerLayout(QWidget):
    """统一预览器布局（预览内容区 + 操作底栏）。"""

    # 定位到当前预览文件所在目录（请求文件选择器导航并高亮该文件）
    locate_requested = Signal(dict)
    # 清除预览（清空内容区 + 两侧面板的预览态）
    clear_requested = Signal()
    # 预览器内层条目选中（文件夹预览器选中变化时转发；None 表示取消选中）
    entry_selected = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 预览器管理属性
        self._current_preview_widget: Optional[QWidget] = None
        self._current_preview_type: Optional[type] = None
        self._current_file_info: Optional[dict] = None
        # AI 功能入口开关（由主窗口下发；仅 PDF/文本预览器消费，默认关闭）
        self._ai_entry_enabled: bool = False
        self._placeholder_label: Optional[QLabel] = None
        self._content_layout: Optional[QVBoxLayout] = None

        # 统一操作按钮的承载方式（由主窗口下发）：
        # False = 经典布局（底部操作栏）；True = New 布局（注入预览器顶栏）
        self._actions_top: bool = False
        #: 顶栏模式的图标按钮组（复制 / 打开 / 定位 / 清除），无宿主时不显示
        self._top_buttons: list[StyledButton] = []
        #: 当前注入的宿主控件（用于迁移时先摘除）
        self._top_host: Optional[QWidget] = None
        #: 无顶栏预览器时由本容器提供的统一工具栏（懒创建）
        self._own_toolbar: Optional[PreviewToolbarFrame] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # 内容区（自适应拉伸）
        self._content_top = QFrame()
        self._content_top.setObjectName("PreviewerTop")
        layout.addWidget(self._content_top, stretch=1)

        # 顶栏模式的图标按钮（先于底栏创建：底栏末尾的状态同步会一并更新它们）
        self._build_top_action_buttons()

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
        icons_dir = get_icons_dir()
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

    def _build_top_action_buttons(self) -> None:
        """构建顶栏模式的图标按钮组（New 布局注入预览器顶栏用）。

        与底栏按钮功能一致（同一处理器），形态为 ghost 32×32 图标按钮；
        默认无父级、不显示，注入宿主（预览器顶栏 / 本容器统一工具栏）后显示。
        图标：share.svg（复制）/ open_with.svg（系统打开）/
        locate.svg（定位目录）/ close.svg（清除预览）。
        """
        icons_dir = get_icons_dir()
        specs = (
            ("share.svg", "复制到剪切板", self._on_copy_to_clipboard_clicked),
            ("open_with.svg", "使用系统默认方式打开", self._on_open_with_system_clicked),
            ("locate.svg", "定位到所在目录", self._on_locate_requested),
            ("close.svg", "清除预览", self._on_clear_preview_clicked),
        )
        self._top_buttons = []
        for icon_name, tip, handler in specs:
            icon_path = icons_dir / icon_name
            btn = StyledButton(
                "", variant="ghost", size="sm",
                icon=str(icon_path) if icon_path.exists() else "",
            )
            btn.setFixedSize(32, 32)
            btn.setToolTip(tip)
            btn.clicked.connect(handler)
            self._top_buttons.append(btn)

    def _update_bottom_buttons(self) -> None:
        """按当前是否有预览文件启停底栏与顶栏按钮（无文件时全部禁用）。"""
        has_file = self._current_file_info is not None
        for btn in (self._share_btn, self._open_default_btn,
                    self._locate_btn, self._close_btn):
            btn.setEnabled(has_file)
        for btn in self._top_buttons:
            btn.setEnabled(has_file)

    # ── 统一操作按钮：承载方式（顶栏 / 底栏） ─────────────────────────

    def set_bottom_bar_host(self, host: Optional[QWidget]) -> None:
        """把底部操作栏挂载到外部宿主（经典布局：文件信息面板下方）。

        经典布局下底栏应与左/中两栏的底栏一样位于整列最底部，故挂到主布局
        提供的外部槽位；New 布局或布局切换前传 ``None`` 归位到本容器内部
        （避免底部栏随旧布局/宿主一并销毁）。

        Args:
            host: 外部宿主控件（自带布局或由本方法补建）；``None`` 表示归位。
        """
        bar = self._bottom_bar
        current = bar.parentWidget()
        if host is None:
            if current is self:
                return
            if current is not None and current.layout() is not None:
                current.layout().removeWidget(bar)
            layout = self.layout()
            if layout is not None:
                layout.addWidget(bar)
            return

        if current is host:
            return
        if current is not None and current.layout() is not None:
            current.layout().removeWidget(bar)
        bar.setParent(host)
        host_layout = host.layout()
        if host_layout is None:
            host_layout = QVBoxLayout(host)
            host_layout.setContentsMargins(0, 0, 0, 0)
            host_layout.setSpacing(0)
        host_layout.addWidget(bar)

    def set_actions_mode(self, top: bool) -> None:
        """切换统一操作按钮的承载方式（主窗口按布局模式下发）。

        Args:
            top: True = New 布局：隐藏底部操作栏，图标按钮注入预览器顶栏
                （无顶栏预览器由本容器提供统一工具栏）；
                False = 经典布局：底部操作栏（与历史行为逐像素一致）。
        """
        top = bool(top)
        if top == self._actions_top:
            return
        self._actions_top = top
        self._bottom_bar.setVisible(not top)
        self._sync_action_host()

    def _previewer_action_host(self) -> Optional[QWidget]:
        """当前预览器提供的操作按钮宿主（``unified_action_host`` 协议）。"""
        widget = self._current_preview_widget
        if widget is None:
            return None
        getter = getattr(widget, "unified_action_host", None)
        if not callable(getter):
            return None
        try:
            host = getter()
        except Exception:  # noqa: BLE001 - 宿主探测失败按无顶栏处理
            return None
        return host if isinstance(host, QWidget) else None

    def _ensure_own_toolbar(self) -> PreviewToolbarFrame:
        """无顶栏预览器时由本容器提供的统一工具栏（内容区顶部，懒创建）。"""
        if self._own_toolbar is None:
            toolbar = PreviewToolbarFrame(self._content_top)
            toolbar.setObjectName("UnifiedPreviewerToolbar")
            toolbar.setFixedHeight(48)
            toolbar.setVisible(False)
            self._ensure_content_layout()
            if self._content_layout is not None:
                self._content_layout.insertWidget(0, toolbar)
            self._own_toolbar = toolbar
        return self._own_toolbar

    def _detach_top_buttons(self) -> None:
        """仅从当前宿主摘除顶栏按钮（不重新注入）。"""
        host = self._top_host
        if host is None:
            return
        for btn in self._top_buttons:
            self._release_top_button(btn, host)
        self._top_host = None

    def _sync_action_host(self) -> None:
        """把顶栏图标按钮迁移到当前应处的位置（幂等，可反复调用）。"""
        # 1) 先摘除旧宿主；本容器统一工具栏先隐藏，按需再显示
        self._detach_top_buttons()
        if self._own_toolbar is not None:
            self._own_toolbar.setVisible(False)

        # 经典布局：底部操作栏常驻，顶栏按钮无宿主即隐藏
        if not self._actions_top:
            return

        target = self._previewer_action_host()
        if target is None:
            # 无顶栏预览器：用本容器统一工具栏；无预览器（占位态）则不显示
            if self._current_preview_widget is None:
                return
            target = self._ensure_own_toolbar()
            target.setVisible(True)
        self._inject_top_buttons(target)
        self._top_host = target

    def _inject_top_buttons(self, host: QWidget) -> None:
        """把四个图标按钮注入宿主：统一工具栏按锚定分区，自绘顶栏右侧追加。"""
        copy_btn, open_btn, locate_btn, close_btn = self._top_buttons
        add_left = getattr(host, "add_left", None)
        add_trailing = getattr(host, "add_trailing", None)
        add_right = getattr(host, "add_right", None)
        if callable(add_left) and callable(add_trailing) and callable(add_right):
            # PreviewToolbarFrame 宿主：定位左锚定；复制/打开中部；清除右锚定
            add_left(locate_btn)
            add_trailing(copy_btn)
            add_trailing(open_btn)
            add_right(close_btn)
            return
        # 自绘顶栏宿主：右端依次追加（与底栏顺序一致）
        layout = host.layout()
        if layout is None:
            return
        for btn in (copy_btn, open_btn, locate_btn, close_btn):
            btn.setParent(host)
            layout.addWidget(btn)
            btn.show()

    @staticmethod
    def _release_top_button(button: StyledButton, host: QWidget) -> None:
        """把按钮从宿主摘除（PreviewToolbarFrame 走专用移除；否则从布局摘除）。"""
        remover = getattr(host, "remove_widget", None)
        if callable(remover):
            remover(button)
            return
        layout = host.layout()
        if layout is not None:
            layout.removeWidget(button)
        try:
            button.setParent(None)
        except RuntimeError:
            pass

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
        """应用面板样式到内容区与底栏（主题切换时由 MainWindow 调用）。

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
            QFrame#PreviewerBottomBar {{
                background-color: {fill_color};
                border: 1px solid {border_color};
                border-radius: 8px;
            }}
        """
        register_widget_qss(self._content_top,(section_style))
        # 强制已显示控件重新套用样式（延迟构建场景下必须，否则边框/填充不重绘）
        self._content_top.style().unpolish(self._content_top)
        self._content_top.style().polish(self._content_top)
        register_widget_qss(self._bottom_bar,(section_style))
        self._bottom_bar.style().unpolish(self._bottom_bar)
        self._bottom_bar.style().polish(self._bottom_bar)
    
    def _on_theme_changed(self, theme: str) -> None:
        """主题切换时占位（样式由 MainWindow 统一刷新）"""
    
    def cleanup(self) -> None:
        """释放当前预览器的后台资源（主窗口关闭时调用）。

        文件信息面板已外置，其采集线程由持有方（MainWindow）单独停止。
        """
        self._cleanup_current_preview()

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
        self._load_preview(file_info)
    
    def clear_preview(self) -> None:
        """清空预览区并显示占位符（文件信息面板的清理由持有方负责）。"""
        self._cleanup_current_preview()
        self._current_file_info = None
        self._update_bottom_buttons()
        self._show_placeholder()

    def set_ai_entry_enabled(self, enabled: bool) -> None:
        """运行时切换 AI 功能入口（幂等；主窗口设置提交路径调用）。

        开启后 PDF / 文本预览器显示 AI 按钮与侧边抽屉；关闭时移除按钮并
        关闭抽屉。尚未创建预览器时仅记录开关，创建时再下发。AI 实际能力
        为长期规划（见各预览器代码内 TODO）。

        Args:
            enabled: True 显示入口；False 完全隐藏。
        """
        self._ai_entry_enabled = bool(enabled)
        if self._current_preview_widget is not None:
            self._apply_ai_entry_flag(self._current_preview_widget)

    def current_file_info(self) -> Optional[dict]:
        """返回当前预览文件信息（无预览时为 None；信息面板联动用）。"""
        return self._current_file_info

    # ── 内部方法 ──

    def _apply_ai_entry_flag(self, widget: QWidget) -> None:
        """将 AI 入口开关下发给支持的预览器（不支持则静默跳过）。"""
        if not hasattr(widget, "set_ai_entry_enabled"):
            return
        try:
            widget.set_ai_entry_enabled(self._ai_entry_enabled)
        except Exception as exc:  # noqa: BLE001 - 开关下发失败不影响预览
            warning(f"AI 入口开关下发失败: {exc}")
    
    
    def _get_previewer_class(self, file_info: dict) -> Optional[type]:
        """根据文件信息获取对应的预览器类。
        
        Args:
            file_info: 文件信息字典
            
        Returns:
            预览器类，如无匹配则返回 None
        """
        return PreviewerRegistry.get_previewer_class(file_info)
    
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
        return ("." + suffix.lstrip(".")).lower() in _AUDIO_EXTS
    
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
            register_widget_qss(self._placeholder_label,(
                f"color: {tm.mid.name()}; font-size: 14px; background: transparent;"
            ))
        
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
            # 顶栏按钮先于预览器销毁摘除（按钮宿主可能位于预览器顶栏内部）
            self._detach_top_buttons()
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
            # 无预览器（占位态）：顶栏按钮无宿主，统一工具栏隐藏
            self._sync_action_host()
    
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
                # AI 入口开关下发（仅支持的预览器；关闭时不创建相关控件）
                self._apply_ai_entry_flag(self._current_preview_widget)
                # 内层条目选中信号转发（文件夹预览器等；主窗口据此联动信息面板）
                if hasattr(self._current_preview_widget, "entry_selected"):
                    try:
                        self._current_preview_widget.entry_selected.connect(
                            self.entry_selected.emit
                        )
                    except (RuntimeError, AttributeError):
                        pass
                
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

        # 预览器就绪（或加载失败后已占位）：同步顶栏按钮宿主
        self._sync_action_host()
