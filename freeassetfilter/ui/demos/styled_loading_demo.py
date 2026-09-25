# -*- coding: utf-8 -*-
"""StyledLoading 加载动画组件 —— 独立演示脚本。

运行（仓库根目录）：
    python -m freeassetfilter.ui.demos.styled_loading_demo

也可直接执行：
    python freeassetfilter/ui/demos/styled_loading_demo.py

演示内容：
  1. 三档尺寸：sm / default / lg
  2. 四种颜色变体：default / success / warning / danger
  3. start() / stop() 运行控制
  4. overlay 遮罩覆盖层 + fit_to_parent()，并验证遮罩会挡住下层点击
  5. tm.toggle_theme() 主题切换，验证组件配色在绘制期现取
"""

from __future__ import annotations

import sys
from pathlib import Path

# 直接以脚本方式执行时，把仓库根目录加入 sys.path，保证绝对导入可用
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPaintEvent
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget

# 必须先导入 freeassetfilter.ui.theme：它会把 `theme` 短路径别名注入 sys.modules，
# 供 styled 组件内部的 `from theme import tm` 使用（与 app 内其它入口的导入顺序一致）
from freeassetfilter.ui.theme import tm
from freeassetfilter.ui.theme.app_stylesheet import register_widget_qss

from freeassetfilter.ui.components.settings_card import SettingsCard
from freeassetfilter.ui.components.styled_button import StyledButton
from freeassetfilter.ui.components.styled_loading import StyledLoading


class DemoWindow(QWidget):
    """StyledLoading 组件演示窗口。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        """搭建演示界面并订阅主题切换。

        Args:
            parent: 父控件。
        """
        super().__init__(parent)
        self._colored_labels: list[tuple[QLabel, str]] = []
        self._control_loading: StyledLoading | None = None
        self._control_button: StyledButton | None = None
        self._state_label: QLabel | None = None
        self._overlay_host: QWidget | None = None
        self._overlay: StyledLoading | None = None
        self._click_button: StyledButton | None = None
        self._click_label: QLabel | None = None
        self._click_count = 0
        self._theme_button: StyledButton | None = None

        self.setWindowTitle("StyledLoading 加载动画 Demo")
        self.resize(780, 700)
        self._setup_ui()
        self._sync_theme_button_text()

        tm.theme_changed.connect(self._on_theme_changed)

    # ------------------------------------------------------------------
    # 窗口背景与文本配色
    # ------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        """用主题填充色绘制窗口背景。"""
        painter = QPainter(self)
        painter.fillRect(self.rect(), tm.fill)
        painter.end()

    def _make_label(self, text: str, kind: str = "normal") -> QLabel:
        """创建随主题刷新配色的标签。

        Args:
            text: 标签文本。
            kind: ``"title"``（标题）/ ``"hint"``（说明）/ ``"normal"``（正文）。

        Returns:
            已登记主题刷新队列的 QLabel。
        """
        label = QLabel(text)
        self._colored_labels.append((label, kind))
        self._apply_label_style(label, kind)
        return label

    def _apply_label_style(self, label: QLabel, kind: str) -> None:
        """按标签用途写入当前主题下的字号与颜色。"""
        if kind == "title":
            qss = f"font-size: 13px; font-weight: 600; color: {tm.text.name()};"
        elif kind == "hint":
            qss = f"font-size: 12px; color: {tm.alpha_of(tm.mid, 60).name()};"
        else:
            qss = f"font-size: 12px; color: {tm.mid.name()};"
        register_widget_qss(label, qss)

    def _on_theme_changed(self, _theme: str = "") -> None:
        """主题切换后刷新窗口背景、文本配色与主题按钮文案。"""
        self.update()
        for label, kind in self._colored_labels:
            self._apply_label_style(label, kind)
        self._sync_theme_button_text()

    def _sync_theme_button_text(self) -> None:
        """按当前生效主题刷新「切换主题」按钮文案。"""
        if self._theme_button is None:
            return
        target = "浅色" if tm.is_dark_theme() else "深色"
        self._theme_button.setText(f"切换到{target}模式")

    # ------------------------------------------------------------------
    # 界面搭建
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """按卡片分组搭建全部演示区块。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        layout.addWidget(self._build_size_card())
        layout.addWidget(self._build_variant_card())
        layout.addWidget(self._build_control_card())
        layout.addWidget(self._build_overlay_card())
        layout.addWidget(self._build_theme_card())
        layout.addStretch(1)

    def _build_size_card(self) -> SettingsCard:
        """构建「尺寸」演示卡片。"""
        card = SettingsCard()
        body = card.add_body()
        body.addWidget(self._make_label("尺寸", "title"))
        body.addWidget(self._make_label("三档等比尺寸：sm 16px / default 24px / lg 32px", "hint"))

        row = QHBoxLayout()
        row.setContentsMargins(0, 10, 0, 0)
        row.setSpacing(36)
        for size_key, caption in (("sm", "sm"), ("default", "default"), ("lg", "lg")):
            body_col = QVBoxLayout()
            body_col.setSpacing(8)
            body_col.addWidget(StyledLoading(size=size_key), 0, Qt.AlignHCenter)
            caption_label = self._make_label(caption, "hint")
            caption_label.setAlignment(Qt.AlignCenter)
            body_col.addWidget(caption_label)
            row.addLayout(body_col)
        row.addStretch(1)
        body.addLayout(row)
        return card

    def _build_variant_card(self) -> SettingsCard:
        """构建「颜色变体」演示卡片。"""
        card = SettingsCard()
        body = card.add_body()
        body.addWidget(self._make_label("颜色变体", "title"))
        body.addWidget(self._make_label("success 与 default 同取强调色，跟随主题与强调色实时取色", "hint"))

        row = QHBoxLayout()
        row.setContentsMargins(0, 10, 0, 0)
        row.setSpacing(36)
        for variant_key in StyledLoading.VARIANTS:
            body_col = QVBoxLayout()
            body_col.setSpacing(8)
            body_col.addWidget(
                StyledLoading(size="lg", variant=variant_key), 0, Qt.AlignHCenter
            )
            caption_label = self._make_label(variant_key, "hint")
            caption_label.setAlignment(Qt.AlignCenter)
            body_col.addWidget(caption_label)
            row.addLayout(body_col)
        row.addStretch(1)
        body.addLayout(row)
        return card

    def _build_control_card(self) -> SettingsCard:
        """构建「运行控制」演示卡片。"""
        card = SettingsCard()
        body = card.add_body()
        body.addWidget(self._make_label("运行控制", "title"))
        body.addWidget(self._make_label("start() / stop()：停止后停留在当前形态，角度与弧长都不再变化", "hint"))

        row = QHBoxLayout()
        row.setContentsMargins(0, 10, 0, 0)
        row.setSpacing(20)

        self._control_loading = StyledLoading(size="lg")
        row.addWidget(self._control_loading, 0, Qt.AlignVCenter)

        self._control_button = StyledButton("暂停", variant="secondary", size="sm")
        self._control_button.clicked.connect(
            lambda *args: self._on_toggle_running()
        )
        row.addWidget(self._control_button, 0, Qt.AlignVCenter)

        self._state_label = self._make_label("运行中", "hint")
        row.addWidget(self._state_label, 0, Qt.AlignVCenter)
        row.addStretch(1)
        body.addLayout(row)
        return card

    def _build_overlay_card(self) -> SettingsCard:
        """构建「遮罩覆盖层」演示卡片。"""
        card = SettingsCard()
        body = card.add_body()
        body.addWidget(self._make_label("遮罩覆盖层", "title"))
        body.addWidget(
            self._make_label(
                'overlay=True + fit_to_parent() 铺满宿主；opaque 为实色启动屏',
                "hint",
            )
        )

        row = QHBoxLayout()
        row.setContentsMargins(0, 10, 0, 0)
        row.setSpacing(20)

        # 遮罩宿主区域：遮罩会覆盖它，使其下层按钮不可点击
        host = QWidget()
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(8)
        host_layout.addWidget(self._make_label("遮罩宿主区域", "title"))
        self._click_button = StyledButton("下层按钮（点击测试）", variant="ghost", size="sm")
        self._click_button.clicked.connect(lambda *args: self._on_lower_clicked())
        host_layout.addWidget(self._click_button, 0, Qt.AlignLeft)
        self._click_label = self._make_label("下层按钮点击次数：0", "hint")
        host_layout.addWidget(self._click_label)
        host_layout.addStretch(1)
        self._overlay_host = host
        row.addWidget(host, stretch=1)

        # 遮罩控制按钮（位于宿主之外，遮罩显示时仍可点击）
        button_col = QVBoxLayout()
        button_col.setSpacing(8)
        show_button = StyledButton("显示加载遮罩", variant="primary", size="sm")
        show_button.clicked.connect(lambda *args: self._on_show_overlay())
        opaque_button = StyledButton("显示不透明遮罩", variant="secondary", size="sm")
        opaque_button.clicked.connect(lambda *args: self._on_show_overlay("opaque"))
        hide_button = StyledButton("隐藏加载遮罩", variant="secondary", size="sm")
        hide_button.clicked.connect(lambda *args: self._on_hide_overlay())
        button_col.addWidget(show_button)
        button_col.addWidget(opaque_button)
        button_col.addWidget(hide_button)
        button_col.addStretch(1)
        row.addLayout(button_col)

        body.addLayout(row)
        return card

    def _build_theme_card(self) -> SettingsCard:
        """构建「主题切换」演示卡片。"""
        card = SettingsCard()
        body = card.add_body()
        body.addWidget(self._make_label("主题与强调色", "title"))
        body.addWidget(
            self._make_label("切换主题后，圆环与遮罩配色均由 tm 在绘制期现取", "hint")
        )

        row = QHBoxLayout()
        row.setContentsMargins(0, 10, 0, 0)
        row.setSpacing(20)
        self._theme_button = StyledButton("切换到浅色模式", variant="primary", size="sm")
        self._theme_button.clicked.connect(lambda *args: self._on_toggle_theme())
        row.addWidget(self._theme_button, 0, Qt.AlignVCenter)
        row.addStretch(1)
        body.addLayout(row)
        return card

    # ------------------------------------------------------------------
    # 交互回调
    # ------------------------------------------------------------------

    def _on_toggle_running(self) -> None:
        """暂停 / 恢复演示用加载动画，并同步按钮与状态文案。"""
        loading = self._control_loading
        if loading is None or self._control_button is None or self._state_label is None:
            return
        loading.set_running(not loading.is_running)
        running = loading.is_running
        self._control_button.setText("暂停" if running else "继续")
        self._state_label.setText("运行中" if running else "已停止")

    def _on_lower_clicked(self) -> None:
        """统计下层按钮点击次数（遮罩显示时不可点击）。"""
        self._click_count += 1
        if self._click_label is not None:
            self._click_label.setText(f"下层按钮点击次数：{self._click_count}")

    def _on_show_overlay(self, backdrop: str = "dim") -> None:
        """按指定遮罩样式铺满宿主区域（dim 半透明压暗 / opaque 不透明启动屏）。"""
        if self._overlay_host is None:
            return
        self._on_hide_overlay()
        self._overlay = StyledLoading(
            size="lg", overlay=True, backdrop=backdrop, parent=self._overlay_host
        )
        self._overlay.fit_to_parent()
        self._overlay.show()

    def _on_hide_overlay(self) -> None:
        """停止并销毁遮罩加载层。"""
        if self._overlay is None:
            return
        self._overlay.stop()
        self._overlay.hide()
        self._overlay.deleteLater()
        self._overlay = None

    def _on_toggle_theme(self) -> None:
        """切换深浅主题（tm 会广播 theme_changed）。"""
        tm.toggle_theme()


def main() -> None:
    """演示入口。"""
    app = QApplication(sys.argv)
    app.setApplicationName("StyledLoading Demo")
    window = DemoWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()