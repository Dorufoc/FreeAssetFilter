# -*- coding: utf-8 -*-
"""
无边框窗口方案对比 Demo（迁移验证用，实验脚本）

在不依赖 qframelesswindow 的前提下，实时对比 5 种窗口标志组合在
PySide6 6.11.1 / Windows 上的真实原生行为：

  M1 传统 FramelessWindowHint                    （当前 pip 包的做法）
  M2 Qt.Window | ExpandedClientAreaHint | NoTitleBarBackgroundHint（Qt 6.9+ 现代方案）
  M3 现代方案 + CustomizeWindowHint（去掉 Qt 自绘系统按钮）
  M4 纯 Qt.Window（系统完整标题栏，对照基准）
  M5 现代方案 + 显式保留全部系统按钮 hint

运行：
    python _frameless_modern_demo.py

人工测试要点：
  1. 拖拽标题栏移动窗口——观察是否"露出系统自带最小化/最大化/关闭按钮"
  2. 拖到屏幕边缘/顶部——观察 Aero Snap 贴靠是否生效
  3. 鼠标移到窗口边缘——观察原生边框缩放是否可用
  4. 切换 M2/M3 观察右上角 Qt 自绘系统按钮的显示差异
  5. 勾选"原生 Mica"观察 DWM 云母背景（Win11）
  6. 看左下角实时诊断：GWL_STYLE 各样式位 + 非客户区高度
"""

import ctypes
import ctypes.wintypes as wt
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel,
    QMainWindow, QPushButton, QVBoxLayout, QWidget,
)

WS_CAPTION = 0x00C00000
WS_SYSMENU = 0x00080000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000

# 5 种模式：名称 -> windowFlags
MODES = {
    "M1 传统 FramelessWindowHint（当前 pip 包做法）": (
        Qt.Window | Qt.FramelessWindowHint
    ),
    "M2 现代 ExpandedClientAreaHint 组合": (
        Qt.Window | Qt.ExpandedClientAreaHint | Qt.NoTitleBarBackgroundHint
    ),
    "M3 现代组合 + CustomizeWindowHint（去系统按钮，去 WindowTitleHint 防双重标题）": (
        Qt.Window
        | Qt.ExpandedClientAreaHint | Qt.NoTitleBarBackgroundHint
        | Qt.CustomizeWindowHint
    ),
    "M4 纯 Qt.Window（系统完整标题栏，对照）": (
        Qt.Window
    ),
    "M5 现代组合 + 显式保留全部系统按钮": (
        Qt.Window | Qt.WindowTitleHint | Qt.WindowSystemMenuHint
        | Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint
        | Qt.WindowCloseButtonHint
        | Qt.ExpandedClientAreaHint | Qt.NoTitleBarBackgroundHint
    ),
    "M6 现代组合 M2 样式位 + 运行时隐藏 Qt 标题栏子窗口": (
        Qt.Window | Qt.ExpandedClientAreaHint | Qt.NoTitleBarBackgroundHint
    ),
}


class TitleBar(QWidget):
    """自绘标题栏：拖拽移动 + 双击最大化 + 三按钮。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(40)
        self.setObjectName("TitleBar")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 6, 0)
        lay.setSpacing(4)

        self.title_label = QLabel("无边框方案对比 Demo")
        self.title_label.setStyleSheet("font-size: 14px; font-weight: 600;")
        lay.addWidget(self.title_label)
        lay.addStretch(1)

        self.min_btn = self._make_btn("—", "min")
        self.max_btn = self._make_btn("□", "max")
        self.close_btn = self._make_btn("✕", "close")
        for b in (self.min_btn, self.max_btn, self.close_btn):
            lay.addWidget(b)

        self.min_btn.clicked.connect(self.window().showMinimized)
        self.max_btn.clicked.connect(self._toggle_max)
        self.close_btn.clicked.connect(self.window().close)

    def _make_btn(self, text: str, name: str) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName(name)
        b.setFixedSize(34, 30)
        b.setStyleSheet(
            "QPushButton{background:transparent;border:none;border-radius:4px;"
            "font-size:13px;color:#444}"
            "QPushButton:hover{background:rgba(0,0,0,0.08)}"
            f"QPushButton#{name}:hover{{background:#c42c1e;color:#fff}}"
        )
        b.setFocusPolicy(Qt.NoFocus)
        return b

    def _toggle_max(self):
        w = self.window()
        if w.isMaximized():
            w.showNormal()
        else:
            w.showMaximized()

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._toggle_max()
            e.accept()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.windowHandle():
            self.windowHandle().startSystemMove()
            e.accept()


class DemoWindow(QMainWindow):
    """测试窗口：模式切换 + 诊断面板 + 自绘标题栏 + 可选 Mica。"""

    def __init__(self):
        super().__init__()
        self._mode_name = list(MODES.keys())[1]  # 默认 M2
        self._block_system_buttons = False       # M6: 拦截 WM_NCHITTEST 禁用系统按钮命中
        self.setMinimumSize(680, 460)
        self.resize(760, 520)

        # 关键：ExpandedClientAreaHint 会让 Qt 平台层返回 safeAreaMargins=(0,标题栏高,0,0)，
        # 顶层窗口默认自动开启 WA_ContentsMarginsRespectsSafeArea 把内容整体下推一个标题栏
        # 高度（实测 21px）。这里显式关闭（显式调用会阻止 Qt 的默认自动开启），让内容
        # 真正顶到窗口顶部，自绘标题栏不再偏下。
        self.setAttribute(Qt.WidgetAttribute.WA_ContentsMarginsRespectsSafeArea, False)

        self._build_ui()
        self._apply_mode(self._mode_name)

        # 实时诊断刷新（拖拽/缩放时样式位可能变化，便于观察）
        self._diag_timer = QTimer(self)
        self._diag_timer.timeout.connect(self._refresh_diag)
        self._diag_timer.start(300)

    # ---- UI ----
    def _build_ui(self):
        root = QWidget(self)
        self.setCentralWidget(root)
        root_lay = QVBoxLayout(root)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)

        # 自绘标题栏
        self._titlebar = TitleBar(self)
        root_lay.addWidget(self._titlebar)

        body = QWidget(root)
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(16, 14, 16, 14)
        body_lay.setSpacing(10)
        root_lay.addWidget(body, 1)

        # 模式选择
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("窗口模式："))
        self._mode_box = QComboBox()
        self._mode_box.addItems(list(MODES.keys()))
        self._mode_box.currentTextChanged.connect(self._apply_mode)
        row1.addWidget(self._mode_box, 1)
        self._mica_check = QCheckBox("原生 DWM Mica（Win11）")
        self._mica_check.toggled.connect(self._toggle_mica)
        row1.addWidget(self._mica_check)
        body_lay.addLayout(row1)

        # 测试说明
        hint = QLabel(
            "测试清单：\n"
            "① 按住标题栏空白处拖拽 → 观察是否露出系统自带最小化/最大化/关闭按钮\n"
            "② 拖到屏幕顶部/左右边缘 → 观察 Aero Snap 贴靠提示是否出现\n"
            "③ 鼠标移到窗口四边/四角 → 观察原生缩放光标与拖拽缩放是否可用\n"
            "④ 双击标题栏 → 最大化/还原\n"
            "⑤ 切换 M2/M3/M5 对比右上角系统按钮显示差异\n"
        )
        hint.setStyleSheet(
            "background:rgba(0,0,0,0.05);border-radius:6px;padding:10px;"
            "font-size:13px;line-height:1.6;"
        )
        hint.setWordWrap(True)
        body_lay.addWidget(hint, 1)

        # 诊断信息
        self._diag_label = QLabel("诊断：")
        self._diag_label.setStyleSheet(
            "font-family:Consolas,monospace;font-size:12px;background:#f5f5f5;"
            "border:1px solid #ddd;border-radius:6px;padding:8px;"
        )
        body_lay.addWidget(self._diag_label)

        self.setWindowTitle("无边框方案对比 Demo")

    # ---- 模式应用 ----
    def _apply_mode(self, name: str):
        self._mode_name = name
        flags = MODES[name]
        self.setWindowFlags(flags)
        self.show()  # setWindowFlags 会隐藏窗口，需重新显示
        self._block_system_buttons = name.startswith("M6")
        if name.startswith("M6"):
            # M6: 保留 M2 全部样式位（WS_CAPTION → 动画/边框/Aero Snap 俱在），
            # 但把 Qt 6.9+ 自带的 hwndTitlebar 绘制层（类名 `_q_titlebar`）
            # 按 Qt 官方隐藏逻辑（SetParent→HWND_MESSAGE + SW_HIDE）撤下。
            # 该子窗口画的是 Qt 的"系统标题栏"（标题文本+按钮），隐藏后
            # 由自绘 TitleBar 独占，同时样式位不受影响。
            self._hide_qt_titlebar()
            # 由于主窗口仍带 WS_CAPTION|WS_SYSMENU|MIN|MAX 样式位，DWM 玻璃
            # 模式下的标题栏命中（HTMINBUTTON/HTMAXBUTTON/HTCLOSE）可能仍
            # 存在——_block_system_buttons=True 后 nativeEvent 会把除边缘
            # 缩放带外的全部命中改为 HTCLIENT，系统按钮点击彻底失效。
        self._refresh_diag()

    def nativeEvent(self, eventType, message) -> tuple:
        """M6 下拦截 WM_NCHITTEST：边缘缩放带保留原生码，其余一律 HTCLIENT。"""
        if not self._block_system_buttons:
            return super().nativeEvent(eventType, message)
        if eventType != b"windows_generic_MSG":
            return super().nativeEvent(eventType, message)
        try:
            msg = wt.MSG.from_address(int(message))
        except Exception:
            return super().nativeEvent(eventType, message)
        if msg.message != 0x0084:  # WM_NCHITTEST
            return super().nativeEvent(eventType, message)

        # lParam 高 16 位屏幕 Y，低 16 位屏幕 X
        lp = int(msg.lParam)
        x = ctypes.c_short(lp & 0xFFFF).value
        y = ctypes.c_short((lp >> 16) & 0xFFFF).value
        rect = wt.RECT()
        ctypes.windll.user32.GetWindowRect(ctypes.c_void_p(int(self.winId())), ctypes.byref(rect))
        border = 0 if self.isMaximized() else 8  # 与 WS_THICKFRAME 边框一致
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        lx = x - rect.left < border
        rx = rect.right - x < border
        ty = y - rect.top < border
        by = rect.bottom - y < border
        if lx and ty:
            return True, 13  # HTTOPLEFT
        if rx and by:
            return True, 17  # HTBOTTOMRIGHT
        if rx and ty:
            return True, 14  # HTTOPRIGHT
        if lx and by:
            return True, 16  # HTBOTTOMLEFT
        if ty:
            return True, 12  # HTTOP
        if by:
            return True, 15  # HTBOTTOM
        if lx:
            return True, 10  # HTLEFT
        if rx:
            return True, 11  # HTRIGHT
        # 其余（含顶部标题栏区域）一律 HTCLIENT → 系统按钮命中失效
        return True, 1  # HTCLIENT

    def _hide_qt_titlebar(self) -> None:
        """隐藏 Qt 的 `_q_titlebar` 独立标题栏子窗口（Qt 内部实现名）。

        对应 Qt 源码 qwindowswindow.cpp:
          - 创建: CreateWindowEx(WS_EX_LAYERED|WS_EX_TRANSPARENT|WS_EX_NOACTIVATE, "_q_titlebar", ...)
          - 隐藏: SetParent(hwndTitlebar, HWND_MESSAGE) + ShowWindow(SW_HIDE)
        """
        user32 = ctypes.windll.user32
        main_hwnd = int(self.winId())
        hwnd = ctypes.c_void_p()
        # FindWindowEx 遍历子窗口，匹配类名 "_q_titlebar"
        hwnd = user32.FindWindowExW(
            ctypes.c_void_p(main_hwnd), None, "_q_titlebar", None
        )
        if not hwnd:
            self._diag_label.setText("诊断：未找到 _q_titlebar 子窗口")
            return
        hwnd = int(hwnd)
        # 官方隐藏逻辑（同 setWindowFlags_sys）。注意 HWND_MESSAGE = (HWND)-3，
        # 不能用 0xFFFFFFFF（那是 0x00000000FFFFFFFF，SetParent 会以
        # ERROR_INVALID_WINDOW_HANDLE=1400 失败）。
        user32.SetParent(ctypes.c_void_p(hwnd), ctypes.c_void_p(-3))  # HWND_MESSAGE
        user32.ShowWindow(ctypes.c_void_p(hwnd), 0)  # SW_HIDE


    def _toggle_mica(self, on: bool):
        try:
            from freeassetfilter.ui.mica import winapi as mica_winapi
        except Exception:
            self._diag_label.setText(
                "诊断：无法导入 freeassetfilter.ui.mica.winapi（请在项目根目录运行）"
            )
            return
        ok = mica_winapi.set_native_mica(int(self.winId()), on)
        self._mica_check.blockSignals(True)
        self._mica_check.setChecked(ok and on)
        self._mica_check.blockSignals(False)
        self._refresh_diag()

    # ---- 诊断 ----
    def _refresh_diag(self):
        try:
            hwnd = int(self.winId())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, -16)  # GWL_STYLE
            wr = wt.RECT(); cr = wt.RECT()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(wr))
            ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(cr))
            nc_h = (wr.bottom - wr.top) - (cr.bottom - cr.top)
            tb = ctypes.windll.user32.FindWindowExW(
                ctypes.c_void_p(hwnd), None, "_q_titlebar", None)
            qt_tb = "无"
            if tb:
                vis = ctypes.windll.user32.IsWindowVisible(ctypes.c_void_p(int(tb)))
                parent = int(ctypes.windll.user32.GetParent(ctypes.c_void_p(int(tb)))) & 0xFFFFFFFF
                qt_tb = f"存在 visible={bool(vis)} parent=0x{parent:08X}"
            tb_geo = "-"
            if self._titlebar is not None:
                tg = self._titlebar.geometry()
                tb_geo = f"({tg.x()},{tg.y()},{tg.width()}x{tg.height()})"
            lines = [
                f"模式: {self._mode_name}",
                f"GWL_STYLE: 0x{style & 0xFFFFFFFF:08X}",
                f"  WS_CAPTION={bool(style & WS_CAPTION)}  WS_SYSMENU={bool(style & WS_SYSMENU)}"
                f"  WS_THICKFRAME={bool(style & WS_THICKFRAME)}",
                f"  WS_MINIMIZEBOX={bool(style & WS_MINIMIZEBOX)}  WS_MAXIMIZEBOX={bool(style & WS_MAXIMIZEBOX)}",
                f"非客户区高度(winH-clientH): {nc_h} px  (0=完全无边框 / 8≈仅边框 / 56≈标题栏实占)",
                f"窗口状态: {'最大化' if self.isMaximized() else '普通'}  AeroSnap能力(WS_THICKFRAME): "
                f"{'✓ 有' if style & WS_THICKFRAME else '✗ 无'}",
                f"_q_titlebar: {qt_tb}   自绘TitleBar几何: {tb_geo}",
            ]
            self._diag_label.setText("\n".join(lines))
        except Exception as ex:
            self._diag_label.setText(f"诊断失败: {ex}")


def main():
    app = QApplication(sys.argv)
    w = DemoWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
