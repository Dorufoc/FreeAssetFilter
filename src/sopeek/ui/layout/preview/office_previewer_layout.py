"""
Office 预览器布局 — 统一预览 6 种 Office 格式（doc/docx/xls/xlsx/ppt/pptx）

通过 ``OfficeConverterWorker``（T9）在后台线程执行转换，并按信号负载路由到
对应视图：

- PDF 负载（纯路径字符串）→ 懒内嵌 ``PdfPreviewerLayout`` 渲染（xlsx 与
  doc/docx/ppt/pptx 一致，统一 PDF 视图）；
- 降级视图：HTML（``QTextBrowser.setHtml``）、大纲（纯文本）、错误提示。

同实例重分派（Metis B5）：6 个后缀映射到同一个类，docx→xlsx 点击复用同一实例。
每次 ``set_file`` 取消+等待在途 worker、清空旧视图，并用 generation counter
守卫过期异步结果（迟到的 ``converted``/``failed`` 一律丢弃）。

统一操作按钮宿主（``unified_action_host`` 协议）：PDF 视图接管内容区时返回
内嵌 ``PdfPreviewerLayout`` 的顶栏，其余视图返回 ``None``；宿主容器据此在
「自建统一工具栏 / 预览器顶栏」之间迁移图标按钮。视图栈切换会发射
``unified_action_host_changed`` 信号（转换完成、切换文件等时机），
宿主容器收到后重新迁移按钮，保证功能栏始终单层。

``cleanup()`` 契约（Metis B4）：(a) cancel+wait 在途 worker，(b) 调用内嵌
``pdf.cleanup()``（退出全屏，避免 dangling pointer），(c) 然后才允许 deleteLater。
镜像 ``video_player_layout.cleanup()``（仓库金标准），且可安全调用两次。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

# 短路径导入（components.* / theme.*）的 sys.path 由 sopeek.ui 包统一注入，
# 见 sopeek/ui/__init__.py；此处不再按目录层级手工计算。
import sopeek.ui  # noqa: F401  (副作用：把 sopeek/ui 加入 sys.path)

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QStackedLayout,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from theme import tm
from components.styled_button import StyledButton
from components.styled_loading import StyledLoading
from sopeek.services.office_converter_worker import OfficeConverterWorker
from sopeek.services.office_error_report import build_office_error_report
from sopeek.ui.theme.app_stylesheet import register_widget_qss
from sopeek.utils.app_logger import error


class OfficePreviewerLayout(QWidget):
    """Office 统一预览器布局。

    无独立顶栏；内容区使用 ``QStackedLayout`` 切换 PDF / HTML / 大纲 /
    错误 / 覆盖层视图，PDF 视图懒内嵌 ``PdfPreviewerLayout`` 并由其自带
    顶栏（页码/缩放/最大化/AI/索引）接管顶部。

    宿主以 ``OfficePreviewerLayout(parent)`` 单参数构造（``unified_previewer_layout._load_preview``）；
    ``set_file(file_info: dict | str)`` 是宿主调用的唯一入口。

    Signals:
        close_requested: 关闭预览请求信号
        unified_action_host_changed: 统一操作按钮宿主可用性变化
            （PDF 视图接管 / 释放顶部时发射；宿主容器据此迁移图标按钮，
            保证功能栏单层）
    """

    close_requested = Signal()
    #: 统一操作按钮宿主可用性变化（``unified_action_host`` 返回值变化时发射）
    unified_action_host_changed = Signal()

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        dpi_scale: Optional[float] = None,
        global_font: Optional[Any] = None,
        settings_manager: Optional[Any] = None,
    ) -> None:
        """初始化布局与视图栈。

        Parameters
        ----------
        parent : Optional[QWidget]
            父控件（可选）。
        dpi_scale : Optional[float]
            DPI 缩放系数（透传给内嵌 PdfPreviewerLayout）。
        global_font : Optional[Any]
            全局字体（透传给内嵌 PdfPreviewerLayout）。
        settings_manager : Optional[Any]
            注入的设置管理器；``None`` 时仅在需要时懒解析（Metis B9）。
        """
        super().__init__(parent)
        self._dpi_scale: Optional[float] = dpi_scale
        self._global_font: Optional[Any] = global_font
        # 不立即解析：仅在懒内嵌 PdfPreviewerLayout 时才需要（镜像 hover_tooltip）。
        self._settings_manager: Optional[Any] = settings_manager

        self._generation: int = 0
        self._current_worker: Optional[OfficeConverterWorker] = None
        # 已请求取消、仍在收尾的 worker 强引用（finished 时移除）。
        # 见 ``_cancel_worker``：避免 Python 侧引用消失导致运行中的 QThread
        # 被回收而 abort 进程。
        self._retiring_workers: set = set()
        self._current_suffix: str = ""
        self._current_path: str = ""
        self._cleaned_up: bool = False
        self._pdf: Optional[Any] = None
        self._pdf_holder_layout: Optional[QVBoxLayout] = None
        self._last_error_message: str = ""
        self._last_error_report: str = ""

        self._init_ui()

        # 复制按钮的“已复制”短暂反馈
        self._copy_reset_timer = QTimer(self)
        self._copy_reset_timer.setSingleShot(True)
        self._copy_reset_timer.timeout.connect(self._reset_copy_button)

        # 主题切换：占位/错误提示色随主题刷新
        tm.theme_changed.connect(self._on_theme_changed)

    def _on_theme_changed(self, _theme: str) -> None:
        """主题切换：重注册占位/错误提示色并重绘内容视图。"""
        register_widget_qss(self._placeholder,(
            f"color: {tm.qss_color(tm.text_hint)}; font-size: 14px; background: transparent;"
        ))
        self._apply_error_styles()
        self._html_view.viewport().update()
        self._outline_view.viewport().update()
        self.update()

    def _apply_error_styles(self) -> None:
        """应用错误视图的主题色（标题 / 消息 / 指引）。"""
        register_widget_qss(
            self._error_title,
            (
                f"color: {tm.qss_color(tm.text)}; font-size: 18px; "
                "font-weight: 600; background: transparent;"
            ),
        )
        register_widget_qss(
            self._error_message,
            (
                f"color: {tm.qss_color(tm.text_secondary)}; font-size: 14px; "
                "background: transparent;"
            ),
        )
        register_widget_qss(
            self._error_hint,
            (
                f"color: {tm.qss_color(tm.text_hint)}; font-size: 12px; "
                "background: transparent;"
            ),
        )

    # ── UI 初始化 ─────────────────────────────────────────────────────────

    def _init_ui(self) -> None:
        """构建内容视图栈（无独立顶栏，PDF 视图由内嵌 PdfPreviewerLayout 自带顶栏接管）。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 内容区（自适应拉伸）
        self._content_area = QFrame()
        self._content_area.setObjectName("OfficePreviewerContent")
        self._content_stack = QStackedLayout(self._content_area)
        self._content_stack.setContentsMargins(0, 0, 0, 0)

        # index 0：覆盖层（加载中占位）
        self._overlay = QWidget()
        self._overlay.setObjectName("OfficePreviewerOverlay")
        overlay_layout = QVBoxLayout(self._overlay)
        overlay_layout.setAlignment(Qt.AlignCenter)
        overlay_layout.setSpacing(16)

        # 转换期间显示圆形加载动画（与提示文本组成「圆环 + 状态」）
        self._loading_spinner = StyledLoading(size="lg")
        self._loading_spinner.setVisible(False)
        overlay_layout.addWidget(self._loading_spinner, 0, Qt.AlignCenter)

        self._placeholder = QLabel("正在转换 Office 文档…")
        self._placeholder.setAlignment(Qt.AlignCenter)
        register_widget_qss(self._placeholder,(
            f"color: {tm.qss_color(tm.text_hint)}; font-size: 14px; background: transparent;"
        ))
        overlay_layout.addWidget(self._placeholder)
        self._content_stack.addWidget(self._overlay)

        # index 1：HTML 降级视图
        self._html_view = QTextBrowser()
        self._html_view.setObjectName("OfficePreviewerHtmlView")
        self._html_view.setOpenExternalLinks(False)
        self._html_view.setOpenLinks(False)
        self._content_stack.addWidget(self._html_view)

        # index 2：大纲降级视图（纯文本）
        self._outline_view = QTextBrowser()
        self._outline_view.setObjectName("OfficePreviewerOutlineView")
        self._content_stack.addWidget(self._outline_view)

        # index 3：错误视图（标题 + 可选中消息 + 复制按钮）
        self._error_view = QWidget()
        self._error_view.setObjectName("OfficePreviewerErrorView")
        error_layout = QVBoxLayout(self._error_view)
        error_layout.setContentsMargins(32, 32, 32, 32)
        error_layout.setSpacing(12)
        error_layout.addStretch(1)

        self._error_title = QLabel("Office 文档预览失败")
        self._error_title.setObjectName("OfficePreviewerErrorTitle")
        self._error_title.setAlignment(Qt.AlignCenter)
        self._error_title.setWordWrap(True)
        error_layout.addWidget(self._error_title)

        self._error_message = QLabel("")
        self._error_message.setObjectName("OfficePreviewerErrorMessage")
        self._error_message.setAlignment(Qt.AlignCenter)
        self._error_message.setWordWrap(True)
        self._error_message.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )
        # 长错误消息不应撑出预览区
        self._error_message.setMaximumWidth(760)
        error_layout.addWidget(self._error_message, 0, Qt.AlignHCenter)

        self._error_hint = QLabel(
            "可尝试安装 LibreOffice 作为备用转换引擎；"
            "若问题持续，请复制错误信息反馈。"
        )
        self._error_hint.setObjectName("OfficePreviewerErrorHint")
        self._error_hint.setAlignment(Qt.AlignCenter)
        self._error_hint.setWordWrap(True)
        self._error_hint.setMaximumWidth(760)
        error_layout.addWidget(self._error_hint, 0, Qt.AlignHCenter)

        self._error_actions = QHBoxLayout()
        self._error_actions.setContentsMargins(0, 8, 0, 0)
        self._error_actions.setSpacing(8)
        self._error_actions.setAlignment(Qt.AlignCenter)
        self._copy_error_btn = StyledButton(
            "复制错误信息", variant="secondary", size="sm"
        )
        self._copy_error_btn.setObjectName("OfficePreviewerCopyError")
        self._copy_error_btn.setToolTip(
            "复制完整错误信息（含技术详情与日志路径）"
        )
        self._copy_error_btn.clicked.connect(self._copy_error_report)
        # 固定为默认文案宽度，避免“已复制”反馈时按钮宽度跳动。
        self._copy_error_btn.setMinimumWidth(
            self._copy_error_btn.sizeHint().width()
        )
        self._error_actions.addWidget(self._copy_error_btn)
        error_layout.addLayout(self._error_actions)
        error_layout.addStretch(1)

        self._apply_error_styles()
        self._content_stack.addWidget(self._error_view)

        # index 4：PDF 视图（懒内嵌 PdfPreviewerLayout）
        self._pdf_holder = QWidget()
        self._pdf_holder_layout = QVBoxLayout(self._pdf_holder)
        self._pdf_holder_layout.setContentsMargins(0, 0, 0, 0)
        self._pdf_holder_layout.setSpacing(0)
        self._content_stack.addWidget(self._pdf_holder)

        self._content_stack.setCurrentWidget(self._overlay)
        layout.addWidget(self._content_area, stretch=1)

    # ── 宿主入口 ───────────────────────────────────────────────────────────

    def set_file(self, file_info: dict | str) -> None:
        """为指定 Office 文件启动后台转换并准备预览视图。

        宿主 ``unified_previewer_layout._load_preview`` 对非音频分支以
        ``set_file(file_path)`` 调用（file_path 为纯路径字符串）；本方法对
        dict / str 双容归一化：str 形态以路径推导 suffix 转为符合 worker
        契约的 dict。其它类型（None）走安全路径：suffix 为空、worker 收
        空 dict——不给宿主留下再抛异常的机会（宿主仅捕获
        RuntimeError/AttributeError/TypeError）。

        同实例重分派（Metis B5）：先取消+等待在途 worker、清空旧视图，再用
        generation counter 守卫本轮的异步结果；上一轮迟到的信号一律丢弃。

        Parameters
        ----------
        file_info : dict | str
            ``{"path": str, "suffix": str}`` 字典，或纯文件路径字符串
            （suffix 由路径扩展名推导，小写）。
        """
        if isinstance(file_info, dict):
            normalized: dict = dict(file_info or {})
        elif isinstance(file_info, str):
            path = str(file_info)
            normalized = {
                "path": path,
                "suffix": str(Path(path).suffix.lstrip(".")).lower(),
            }
        else:
            normalized = {}

        self._generation += 1
        gen = self._generation
        self._cancel_worker()
        self._reset_views()

        suffix = str(normalized.get("suffix", "") or "").lower().lstrip(".")
        self._current_suffix = suffix
        self._current_path = str(normalized.get("path", "") or "")

        worker = OfficeConverterWorker(dict(normalized or {}))
        worker.converted.connect(
            lambda payload, g=gen: self._on_converted(payload, g)
        )
        # 新 worker 同时提供 failed_with_report；旧测试替身只有 failed。
        failed_with_report = getattr(worker, "failed_with_report", None)
        if failed_with_report is not None:
            failed_with_report.connect(
                lambda message, report, g=gen: self._on_failed(
                    message, report, g
                )
            )
        else:
            worker.failed.connect(
                lambda message, g=gen: self._on_failed(message, "", g)
            )
        self._current_worker = worker
        worker.start()

    def unified_action_host(self):
        """统一操作按钮宿主（``unified_action_host`` 协议，New 布局注入用）。

        PDF 视图（懒内嵌 ``PdfPreviewerLayout``）接管内容区时返回其顶栏，
        使统一图标按钮并入该顶栏；覆盖层 / HTML / 大纲 / 错误视图没有顶栏，
        返回 ``None``——宿主容器据此改用自己的统一工具栏（转换期间等场景
        仍可操作复制 / 打开 / 定位 / 清除）。

        Returns:
            Optional[QWidget]: 内嵌 PDF 预览器顶栏（PDF 视图当前时）；
            其余情况返回 ``None``。
        """
        if self._pdf is None:
            return None
        if self._content_stack.currentWidget() is not self._pdf_holder:
            return None
        getter = getattr(self._pdf, "unified_action_host", None)
        if not callable(getter):
            return None
        host = getter()
        return host if isinstance(host, QWidget) else None

    def cleanup(self) -> None:
        """清理资源（Metis B4）：cancel+wait 在途 worker → 内嵌 pdf.cleanup()。

        可安全调用两次：首次后置 ``_cleaned_up``，二次直接返回。镜像
        ``video_player_layout.cleanup()`` 金标准——先停工作线程再回收内嵌
        全屏组件，避免 dangling pointer 与「信号发射到已销毁对象」。
        """
        if self._cleaned_up:
            return
        self._cleaned_up = True
        # 使在途 worker 的信号全部过期（即使它们仍被排队投递）
        self._generation += 1
        self._cancel_worker()
        # 退出内嵌 PdfPreviewerLayout 的全屏状态，避免 dangling pointer
        if self._pdf is not None:
            try:
                self._pdf.cleanup()
            except (RuntimeError, TypeError):
                pass

    # ── 内部：worker 生命周期 ───────────────────────────────────────────────

    def _cancel_worker(self) -> None:
        """取消并回收在途 worker（非阻塞，不在 UI 线程 wait）。

        优先使用 worker 的 ``retire()``（request_cancel + finished 后
        deleteLater）；测试替身没有 ``retire`` 时回退 ``cleanup()``。
        连接在回收前断开，避免迟到信号进入已切换/已销毁的视图。
        """
        worker = self._current_worker
        self._current_worker = None
        if worker is None:
            return
        for signal_name in ("converted", "failed", "failed_with_report"):
            try:
                getattr(worker, signal_name).disconnect()
            except (RuntimeError, TypeError, AttributeError):
                pass
        # 线程仍在运行时不立即销毁：QThread 在运行中被销毁会打印
        # 「QThread: Destroyed while thread is still running」并直接 abort。
        # 只挂 finished → deleteLater，让线程自然收尾后再回收。
        try:
            if worker.isRunning():
                worker.request_cancel()
                # 强引用托管到回收集合：`finished` 是 Qt 信号，deleteLater
                # 只保证 C++ 侧延后析构；若 Python 侧最后一个引用随本方法
                # 返回而消失，PySide 会立即回收 QThread 包装对象，仍可能
                # 命中「运行中销毁」。集合在 finished 时移除条目，引用自然释放。
                self._retiring_workers.add(worker)
                worker.finished.connect(
                    lambda w=worker: self._release_retired_worker(w)
                )
                worker.finished.connect(worker.deleteLater)
                return
        except (RuntimeError, AttributeError):
            pass
        retire = getattr(worker, "retire", None)
        try:
            if callable(retire):
                retire()
            else:
                worker.cleanup()
        except (RuntimeError, TypeError):
            pass

    def _release_retired_worker(self, worker: Any) -> None:
        """线程结束：从回收集合移除（幂等，控件已销毁时静默）。"""
        try:
            self._retiring_workers.discard(worker)
        except (RuntimeError, AttributeError):
            pass

    def _reset_views(self) -> None:
        """清空旧视图内容，回到覆盖层（同实例重分派时调用）。"""
        self._html_view.clear()
        self._outline_view.clear()
        self._last_error_message = ""
        self._last_error_report = ""
        self._error_title.setText("Office 文档预览失败")
        self._error_message.clear()
        self._error_hint.setVisible(True)
        self._reset_copy_button()
        self._placeholder.setText("正在转换 Office 文档…")
        self._loading_spinner.setVisible(True)
        self._content_stack.setCurrentWidget(self._overlay)
        # 覆盖层无顶栏：通知宿主迁移统一按钮（若此前在 PDF 顶栏内）
        self.unified_action_host_changed.emit()

    # ── 内部：信号路由 ─────────────────────────────────────────────────────

    def _on_converted(self, payload: str, gen: int) -> None:
        """``converted`` 负载路由：PDF 路径 / html / outline。

        Parameters
        ----------
        payload : str
            PDF 路径字符串，或 ``"{content_type}:{content}"`` 标记。
        gen : int
            信号发射时捕获的 generation；与当前不符即过期，直接丢弃。
        """
        if gen != self._generation:
            return
        if payload.startswith("html:"):
            self._show_html(payload[len("html:") :])
        elif payload.startswith("outline:"):
            self._show_outline(payload[len("outline:") :])
        else:
            self._route_pdf(payload)

    def _on_failed(self, message: str, report: str, gen: int) -> None:
        """``failed_with_report`` 路由：显示错误视图并保存完整报告。

        Parameters
        ----------
        message : str
            错误 / 取消 / 超时提示文案。
        report : str
            完整错误报告（含技术详情、版本、日志路径）；用于一键复制。
        gen : int
            信号发射时捕获的 generation；与当前不符即过期，直接丢弃。
        """
        if gen != self._generation:
            return
        self._show_error(message, report)

    # ── 内部：视图切换 ─────────────────────────────────────────────────────

    def _show_html(self, content: str) -> None:
        """显示 HTML 降级视图。"""
        self._loading_spinner.setVisible(False)
        self._html_view.setHtml(content)
        self._content_stack.setCurrentWidget(self._html_view)

    def _show_outline(self, content: str) -> None:
        """显示大纲（纯文本）降级视图。"""
        self._loading_spinner.setVisible(False)
        self._outline_view.setPlainText(content)
        self._content_stack.setCurrentWidget(self._outline_view)

    def _show_error(self, message: str, report: str = "") -> None:
        """显示错误提示视图，并保存可一键复制的完整报告。"""
        self._loading_spinner.setVisible(False)
        self._last_error_message = str(message or "")
        self._last_error_report = str(report or "")
        self._error_title.setText(self._error_title_for(self._last_error_message))
        self._error_message.setText(self._last_error_message or "未知错误")
        # 取消属于用户主动操作，不展示“安装 LibreOffice”之类排障指引。
        self._error_hint.setVisible(
            "取消" not in self._last_error_message
            and "损坏" not in self._last_error_message
            and "无法处理" not in self._last_error_message
        )
        self._reset_copy_button()
        self._content_stack.setCurrentWidget(self._error_view)

    @staticmethod
    def _error_title_for(message: str) -> str:
        """按失败类型返回错误视图标题。"""
        if "损坏" in message or "无法处理" in message:
            return "文件已损坏或无法处理"
        if "取消" in message:
            return "Office 转换已取消"
        if "超时" in message:
            return "Office 转换超时"
        return "Office 文档预览失败"

    def _reset_copy_button(self) -> None:
        """恢复复制按钮的默认文案与可用状态。"""
        timer = getattr(self, "_copy_reset_timer", None)
        if timer is not None:
            timer.stop()
        self._copy_error_btn.setText("复制错误信息")
        self._copy_error_btn.setEnabled(
            bool(self._last_error_report or self._last_error_message)
        )

    def _copy_error_report(self) -> None:
        """复制完整错误报告（无报告时用当前上下文兜底生成）。"""
        report = self._last_error_report
        if not report:
            try:
                report = build_office_error_report(
                    self._last_error_message or "未知错误",
                    file_path=self._current_path,
                    suffix=self._current_suffix,
                )
            except Exception:  # noqa: BLE001 - 兜底报告失败则退回短消息
                report = self._last_error_message or "未知错误"
        try:
            QApplication.clipboard().setText(report)
        except Exception as exc:  # noqa: BLE001 - 剪贴板不可用时仅记日志
            error(f"[OfficePreviewerLayout] 复制错误信息失败: {exc}")
            return
        self._copy_error_btn.setText("已复制")
        self._copy_reset_timer.start(1500)

    def _route_pdf(self, path: str) -> None:
        """PDF 负载路由：懒内嵌 PdfPreviewerLayout 渲染并切换到 PDF 视图。

        Parameters
        ----------
        path : str
            转换产物 PDF 文件路径。
        """
        pdf = self._ensure_pdf()
        self._loading_spinner.setVisible(False)
        pdf.set_file(path)
        self._content_stack.setCurrentWidget(self._pdf_holder)
        # PDF 视图接管顶部：通知宿主把统一按钮迁入内嵌 PDF 顶栏（功能栏单层）
        self.unified_action_host_changed.emit()

    def _ensure_pdf(self) -> Any:
        """懒创建 ``PdfPreviewerLayout`` 实例（首次调用时创建）。

        Returns
        -------
        Any
            内嵌的 PdfPreviewerLayout（首次调用时创建）。
        """
        if self._pdf is None:
            from sopeek.ui.layout.preview.pdf_previewer_layout import PdfPreviewerLayout
            self._pdf = PdfPreviewerLayout(
                self._pdf_holder,
                dpi_scale=self._dpi_scale,
                global_font=self._global_font,
                settings_manager=self._settings_manager,
            )
            self._pdf_holder_layout.addWidget(self._pdf)  # type: ignore[union-attr]
        return self._pdf


__all__ = [
    "OfficePreviewerLayout",
]
