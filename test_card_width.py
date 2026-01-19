#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试卡片动态宽度计算
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QGridLayout, QLabel, QScrollArea
from PyQt5.QtCore import Qt, QSize

class CardTestWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("卡片动态宽度测试")
        self.resize(800, 600)
        
        self.dpi_scale = 1.0
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        layout.addWidget(scroll_area)
        
        self.files_container = QWidget()
        self.files_layout = QGridLayout(self.files_container)
        self.files_layout.setSpacing(int(5 * self.dpi_scale))
        self.files_layout.setContentsMargins(
            int(5 * self.dpi_scale), int(5 * self.dpi_scale),
            int(5 * self.dpi_scale), int(5 * self.dpi_scale)
        )
        self.files_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        
        scroll_area.setWidget(self.files_container)
        
        self.scroll_area = scroll_area
        
        for i in range(12):
            card = QLabel(f"卡片 {i+1}")
            card.setStyleSheet(f"""
                background-color: #3D3D3D;
                border: 1px solid #717171;
                border-radius: 6px;
                color: white;
                padding: 10px;
            """)
            self.files_layout.addWidget(card, i // 4, i % 4)
        
        self.files_container.installEventFilter(self)
    
    def _calculate_max_columns(self):
        """根据当前视口宽度计算每行卡片数量"""
        viewport_width = self.scroll_area.viewport().width()
        print(f"视口宽度: {viewport_width}")
        
        card_width = 70
        spacing = 5
        margin = 10
        
        available_width = viewport_width - margin
        print(f"可用宽度: {available_width}")
        
        columns = 1
        while True:
            total_width = columns * card_width + (columns - 1) * spacing
            print(f"  尝试 {columns} 列: 总宽度 {total_width}")
            if total_width <= available_width:
                columns += 1
            else:
                break
        
        max_cols = max(1, columns - 1)
        print(f"计算得到最大列数: {max_cols}")
        return max_cols
    
    def eventFilter(self, obj, event):
        from PyQt5.QtCore import QEvent
        if event.type() == QEvent.Resize:
            print(f"\n=== 检测到大小变化 ===")
            container_width = self.files_container.width()
            print(f"容器宽度: {container_width}")
            max_cols = self._calculate_max_columns()
            print(f"最终列数: {max_cols}")
            
            if container_width > 0 and max_cols > 0:
                spacing = self.files_layout.spacing()
                margins = self.files_layout.contentsMargins()
                total_margin = margins.left() + margins.right()
                
                card_width = (container_width - (max_cols + 1) * spacing - total_margin) // max_cols
                print(f"卡片宽度: {card_width}")
                
                for i in range(self.files_layout.count()):
                    item = self.files_layout.itemAt(i)
                    if item and item.widget():
                        item.widget().setFixedWidth(card_width)
                        item.widget().setStyleSheet(f"""
                            background-color: #3D3D3D;
                            border: 1px solid #717171;
                            border-radius: 6px;
                            color: white;
                            padding: 10px;
                            min-width: 35px; max-width: 50px;
                        """)
        
        return super().eventFilter(obj, event)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = CardTestWidget()
    window.show()
    sys.exit(app.exec_())
