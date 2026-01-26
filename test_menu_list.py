#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 菜单列表控件测试
演示D_MenuList和D_MenuListItem的使用
"""

import sys
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QMainWindow
from PyQt5.QtCore import Qt, QPoint
from PyQt5.QtGui import QFont

from freeassetfilter.widgets.menu_list import D_MenuList, D_MenuListItem
from freeassetfilter.widgets.button_widgets import CustomButton


class MenuListTestWindow(QMainWindow):
    """菜单列表控件测试窗口"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("菜单列表控件测试")
        self.setGeometry(100, 100, 800, 600)

        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)

        self._init_ui()

    def _init_ui(self):
        """初始化UI"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)

        title_label = QLabel("菜单列表控件测试")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #333;")
        main_layout.addWidget(title_label)

        test_section1 = self._create_d_menu_list_test()
        main_layout.addLayout(test_section1)

        test_section2 = self._create_d_menu_list_item_test()
        main_layout.addLayout(test_section2)

        main_layout.addStretch()

    def _create_d_menu_list_test(self):
        """创建D_MenuList测试区域"""
        layout = QVBoxLayout()
        layout.setSpacing(10)

        label = QLabel("D_MenuList 测试（带滚动条）")
        label.setStyleSheet("font-weight: bold; color: #555;")
        layout.addWidget(label)

        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)

        self.menu_list_btn = CustomButton(
            text="打开菜单列表",
            button_type="normal",
            display_mode="text"
        )
        self.menu_list_btn.clicked.connect(self._toggle_menu_list)
        button_layout.addWidget(self.menu_list_btn)

        show_at_btn = CustomButton(
            text="在指定位置显示",
            button_type="normal",
            display_mode="text"
        )
        show_at_btn.clicked.connect(self._show_menu_list_at)
        button_layout.addWidget(show_at_btn)

        add_items_btn = CustomButton(
            text="添加项目",
            button_type="normal",
            display_mode="text"
        )
        add_items_btn.clicked.connect(self._add_items_to_menu_list)
        button_layout.addWidget(add_items_btn)

        clear_btn = CustomButton(
            text="清空项目",
            button_type="normal",
            display_mode="text"
        )
        clear_btn.clicked.connect(self._clear_menu_list)
        button_layout.addWidget(clear_btn)

        layout.addLayout(button_layout)

        self.menu_list = D_MenuList(parent=self, position="bottom", selection_mode="single")
        self.menu_list.set_target_widget(self.menu_list_btn)
        self.menu_list.set_offset(0, int(5 * self.dpi_scale))
        self.menu_list.set_list_height(150)
        self.menu_list.set_min_width(80)
        self.menu_list.set_max_width(250)
        self.menu_list.set_timeout_enabled(True)
        self.menu_list.set_timeout_duration(5000)

        self.menu_list.add_items([
            "项目 1",
            "项目 2",
            {"text": "项目 3（这是一个较长的文本）", "icon_path": ""},
            "项目 4",
            "项目 5"
        ])

        self.menu_list.itemClicked.connect(self._on_menu_list_item_clicked)
        self.menu_list.selectionChanged.connect(self._on_menu_list_selection_changed)

        return layout

    def _create_d_menu_list_item_test(self):
        """创建D_MenuListItem测试区域"""
        layout = QVBoxLayout()
        layout.setSpacing(10)

        label = QLabel("D_MenuListItem 测试（轻量级，无滚动条）")
        label.setStyleSheet("font-weight: bold; color: #555;")
        layout.addWidget(label)

        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)

        self.menu_list_item_btn = CustomButton(
            text="打开轻量菜单",
            button_type="normal",
            display_mode="text"
        )
        self.menu_list_item_btn.clicked.connect(self._toggle_menu_list_item)
        button_layout.addWidget(self.menu_list_item_btn)

        change_pos_btn = CustomButton(
            text="切换位置",
            button_type="normal",
            display_mode="text"
        )
        change_pos_btn.clicked.connect(self._change_menu_list_item_position)
        button_layout.addWidget(change_pos_btn)

        layout.addLayout(button_layout)

        self.menu_list_item = D_MenuListItem(parent=self, position="bottom")
        self.menu_list_item.set_target_widget(self.menu_list_item_btn)
        self.menu_list_item.add_items([
            "选项 A",
            "选项 B",
            "选项 C",
            "选项 D"
        ])

        self.menu_list_item.clicked.connect(self._on_menu_list_item_clicked)
        self.menu_list_item.doubleClicked.connect(self._on_menu_list_item_double_clicked)

        return layout

    def _toggle_menu_list(self):
        """切换菜单列表显示"""
        self.menu_list.toggle()

    def _show_menu_list_at(self):
        """在指定位置显示菜单列表"""
        self.menu_list.show_at(400, 300)

    def _add_items_to_menu_list(self):
        """添加项目到菜单列表"""
        import random
        for i in range(3):
            self.menu_list.add_item(f"新项目 {random.randint(100, 999)}")

    def _clear_menu_list(self):
        """清空菜单列表"""
        self.menu_list.clear_items()

    def _toggle_menu_list_item(self):
        """切换轻量菜单显示"""
        self.menu_list_item.toggle()

    def _change_menu_list_item_position(self):
        """切换轻量菜单位置"""
        current_pos = self.menu_list_item._position
        positions = ["bottom", "top", "left", "right"]
        try:
            idx = positions.index(current_pos)
            next_pos = positions[(idx + 1) % len(positions)]
            self.menu_list_item.set_position(next_pos)
        except (ValueError, IndexError):
            self.menu_list_item.set_position("bottom")

    def _on_menu_list_item_clicked(self, index):
        """菜单列表项点击事件"""
        print(f"点击项目: {index}")

    def _on_menu_list_selection_changed(self, indices):
        """菜单列表选择变化事件"""
        print(f"选择变化: {indices}")

    def _on_menu_list_item_double_clicked(self, index):
        """菜单列表项双击事件"""
        print(f"双击项目: {index}")
        self.menu_list_item.hide()


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    font = QFont()
    app.setFont(font)

    window = MenuListTestWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
