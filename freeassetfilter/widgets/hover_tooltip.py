#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 悬浮详细信息组件
当鼠标放到控件上时，显示当前鼠标指针所指向的文本内容
鼠标静止3秒才会显示，鼠标移动则立即隐藏
"""

import weakref
from PyQt5.QtWidgets import QWidget, QLabel, QApplication
from PyQt5.QtCore import Qt, QPoint, QTimer, QRect, pyqtSignal, QEvent
from PyQt5.QtGui import QFont, QColor, QPainter, QBrush, QPen, QFontDatabase


class HoverTooltip(QWidget):
    """
    悬浮详细信息组件
    特点：
    - 鼠标静止3秒后显示
    - 鼠标移动则立即隐藏
    - 白色圆角卡片样式
    - 灰色400字重文字
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 设置窗口标志
        self.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # 创建标签显示文本内容
        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        
        # 获取应用实例，使用main中定义的全局字体
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
        
        # 获取DPI缩放因子
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        # 设置字体样式：创建一个新的字体实例，确保不受调用组件字体影响
        # 使用全局字体作为基础，大小为全局字体的0.8倍
        font = QFont()
        
        # 优先使用应用的全局字体配置
        if hasattr(app, 'global_font'):
            global_font = app.global_font
            # 复制全局字体的所有属性
            font.setFamily(global_font.family())
            font.setStyle(global_font.style())
            font.setWeight(global_font.weight())
            
            # 获取全局字体的原始大小
            global_size = global_font.pointSizeF()
        else:
            # 如果没有全局字体，使用默认大小10
            global_size = 10.0
        
        # 计算新的字体大小：全局大小 * 0.8 并取整
        new_size = int(global_size * 0.8)
        font.setPointSize(new_size)
        
        self.label.setFont(font)
        
        # 应用初始样式
        self.update_style()
        
        # 定时器
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(1000)  # 1秒延迟
        self.timer.timeout.connect(self.show_tooltip)
        
        # 鼠标位置跟踪
        self.last_mouse_pos = QPoint()
        self.target_widgets = []  # 存储目标控件的弱引用列表
        
        # 初始化隐藏
        self.hide()
    
    def update_style(self):
        """
        更新组件样式
        """
        # 获取应用实例和设置管理器
        app = QApplication.instance()
        if hasattr(app, 'settings_manager'):
            settings_manager = app.settings_manager
        else:
            # 回退方案：如果应用实例中没有settings_manager，再创建新实例
            from freeassetfilter.core.settings_manager import SettingsManager
            settings_manager = SettingsManager()
        
        # 获取颜色设置
        current_colors = settings_manager.get_setting("appearance.colors", {})
        secondary_color = current_colors.get("secondary_color", "#333333")
        
        # 设置样式表
        self.setStyleSheet(f"""
            QWidget {{
                background: transparent;
                border: none;
            }}
            QLabel {{
                color: {secondary_color};
                background: transparent;
                padding: 4px;
                font-weight: 400;
            }}
        """)
        
        # 重新绘制组件
        self.update()
    
    def set_target_widget(self, widget):
        """设置要监听的目标控件"""
        # 检查控件是否已经在列表中（通过比较弱引用的目标）
        for ref in self.target_widgets:
            if ref() == widget:
                return  # 已经存在，不需要重复添加
        
        # 添加弱引用
        ref = weakref.ref(widget)
        self.target_widgets.append(ref)
        widget.installEventFilter(self)
    
    def eventFilter(self, obj, event):
        """事件过滤器，监听鼠标事件"""
        # 检查obj是否是我们目标控件列表中的一个
        is_target = False
        for ref in self.target_widgets:
            target = ref()
            if target is obj:
                is_target = True
                break
        
        if is_target:
            event_type = event.type()
            
            if event_type == QEvent.MouseMove:
                # 鼠标移动时更新位置并重置定时器
                self.last_mouse_pos = event.globalPos()
                self.timer.start()
                self.hide()
            elif event_type == QEvent.Enter:
                # 鼠标进入时启动定时器
                self.last_mouse_pos = event.globalPos()
                self.timer.start()
            elif event_type == QEvent.Leave:
                # 鼠标离开时隐藏并停止定时器
                self.hide()
                self.timer.stop()
            elif event_type == QEvent.MouseButtonPress or event_type == QEvent.MouseButtonRelease:
                # 点击时隐藏并停止定时器，不影响控件的点击事件
                self.hide()
                self.timer.stop()
            elif event_type == QEvent.MouseButtonDblClick:
                # 双击时隐藏并停止定时器，不影响控件的双击事件
                self.hide()
                self.timer.stop()
        
        # 返回False确保事件继续传播到目标控件
        return False
    
    def show_tooltip(self):
        """显示悬浮提示框"""
        # 清理已失效的弱引用
        self.target_widgets = [ref for ref in self.target_widgets if ref() is not None]
        
        # 检查是否有可见的目标控件
        visible_widgets = []
        for ref in self.target_widgets:
            target = ref()
            if target and target.isVisible():
                visible_widgets.append(target)
        print(f"可见的目标控件: {[w.__class__.__name__ for w in visible_widgets]}")
        if not visible_widgets:
            return
        
        # 获取当前鼠标位置的控件
        widget = QApplication.widgetAt(self.last_mouse_pos)
        print(f"鼠标位置的控件: {widget.__class__.__name__ if widget else 'None'}")
        if not widget:
            return
        
        # 检查鼠标是否在我们的目标控件上
        current_widget = None
        for ref in self.target_widgets:
            target = ref()
            if target and (widget == target or target.isAncestorOf(widget)):
                current_widget = target
                break
        
        print(f"找到的目标控件: {current_widget.__class__.__name__ if current_widget else 'None'}")
        if not current_widget:
            return
        
        # 获取鼠标位置的文本内容
        text = self.get_text_at_position()
        print(f"获取到的文本: '{text}'")
        if not text:
            return
        
        # 设置文本内容
        self.label.setText(text)
        
        # 调整大小
        self.label.adjustSize()
        margin = int(4 * self.dpi_scale)
        self.resize(self.label.width() + margin, self.label.height() + margin)
        
        # 将文本标签在主容器中居中放置
        label_x = (self.width() - self.label.width()) // 2
        label_y = (self.height() - self.label.height()) // 2
        self.label.move(label_x, label_y)
        
        # 设置位置（鼠标指针下方）
        pos = self.last_mouse_pos
        pos.setY(pos.y() + int(5 * self.dpi_scale))
        
        # 确保提示框在屏幕内
        screen_rect = QApplication.desktop().screenGeometry()
        margin = int(2.5 * self.dpi_scale)
        if pos.x() + self.width() > screen_rect.width():
            pos.setX(screen_rect.width() - self.width() - margin)
        if pos.y() + self.height() > screen_rect.height():
            pos.setY(screen_rect.height() - self.height() - margin)
        
        self.move(pos)
        self.show()
    
    def get_text_at_position(self, widget=None):
        """获取鼠标位置的文本内容"""
        # 首先直接获取鼠标位置的控件，无论是否被布局覆盖
        direct_widget = QApplication.widgetAt(self.last_mouse_pos)
        if direct_widget:
            # 导入CustomButton类
            from .button_widgets import CustomButton
            
            # 检查是否是CustomButton
            if isinstance(direct_widget, CustomButton):
                # 如果有自定义的悬浮信息文本，优先使用
                if direct_widget._tooltip_text:
                    return direct_widget._tooltip_text
                # 如果是文本模式，直接返回文本
                elif direct_widget._display_mode == "text" and direct_widget.text():
                    return direct_widget.text()
                # 如果是图标模式，返回图标描述
                elif direct_widget._display_mode == "icon" and direct_widget._icon_path:
                    # SVG路径到文字描述的映射字典
                    svg_tooltip_map = {
                        "favorites.svg": "收藏夹",
                        "back.svg": "返回上一次退出程序时的目录",
                        "forward.svg": "前进到下一次目录",
                        "refresh.svg": "刷新",
                        "search.svg": "搜索",
                        "close.svg": "关闭",
                        "folder.svg": "文件夹",
                        "file.svg": "文件",
                        "add.svg": "添加",
                        "remove.svg": "移除",
                        "edit.svg": "编辑",
                        "settings.svg": "设置",
                        "help.svg": "帮助",
                        "info.svg": "信息",
                        "trash.svg": "清空所有项目"
                    }
                    
                    # 提取SVG文件名
                    import os
                    svg_filename = os.path.basename(direct_widget._icon_path)
                    
                    # 返回对应的文字描述
                    return svg_tooltip_map.get(svg_filename, svg_filename)
            # 特殊处理CustomFileHorizontalCard组件
            from .file_horizontal_card import CustomFileHorizontalCard
            if isinstance(direct_widget, CustomFileHorizontalCard) or isinstance(direct_widget.parent(), CustomFileHorizontalCard):
                card = direct_widget if isinstance(direct_widget, CustomFileHorizontalCard) else direct_widget.parent()
                file_path = card.file_path
                if card._display_name:
                    file_name = card._display_name
                else:
                    import os
                    file_name = os.path.basename(file_path)
                
                # 获取文件信息
                import os
                from PyQt5.QtCore import QFileInfo
                file_info = QFileInfo(file_path)
                
                # 文件大小
                if file_info.isDir():
                    size_str = "文件夹"
                else:
                    file_size = file_info.size()
                    if file_size < 1024:
                        size_str = f"{file_size} B"
                    elif file_size < 1024 * 1024:
                        size_str = f"{file_size / 1024:.2f} KB"
                    elif file_size < 1024 * 1024 * 1024:
                        size_str = f"{file_size / (1024 * 1024):.2f} MB"
                    else:
                        size_str = f"{file_size / (1024 * 1024 * 1024):.2f} GB"
                
                # 文件类型
                if file_info.isDir():
                    file_type = "文件夹"
                else:
                    file_type = f".{file_info.suffix()}"
                
                # 路径
                file_path = file_info.absoluteFilePath()
                
                # 日期格式化
                if file_info.exists():
                    if file_info.isFile():
                        # 对于文件，尝试获取创建和修改日期
                        created_time = file_info.birthTime().toString("yyyy-MM-dd HH:mm:ss") if file_info.birthTime().isValid() else "未知"
                        modified_time = file_info.lastModified().toString("yyyy-MM-dd HH:mm:ss") if file_info.lastModified().isValid() else "未知"
                    else:  # 对于文件夹
                        created_time = "文件夹"
                        modified_time = file_info.lastModified().toString("yyyy-MM-dd HH:mm:ss") if file_info.lastModified().isValid() else "未知"
                else:
                    # 如果文件不存在，显示默认信息
                    created_time = "文件不存在"
                    modified_time = "文件不存在"
                
                # 构建悬浮信息文本
                tooltip_text = f"文件名: {file_name}\n"
                if not file_info.isDir():
                    tooltip_text += f"文件大小: {size_str}\n"
                tooltip_text += f"文件类型: {file_type}\n"
                tooltip_text += f"路径: {file_path}\n"
                if file_info.isDir():
                    tooltip_text += f"修改日期: {modified_time}"
                else:
                    tooltip_text += f"创建日期: {created_time}\n"
                    tooltip_text += f"修改日期: {modified_time}"
                
                return tooltip_text
            
            # 特殊处理文件选择器中的文件卡片（QWidget#FileBlockCard）
            if direct_widget.objectName() == "FileBlockCard" or (hasattr(direct_widget.parent(), "objectName") and direct_widget.parent().objectName() == "FileBlockCard"):
                card = direct_widget if direct_widget.objectName() == "FileBlockCard" else direct_widget.parent()
                if hasattr(card, "file_info"):
                    file_info = card.file_info
                    file_name = file_info["name"]
                    file_path = file_info["path"]
                    file_size = file_info["size"]
                    file_type = "文件夹" if file_info["is_dir"] else f".{file_info['suffix']}"
                    
                    # 格式化文件大小
                    if file_info["is_dir"]:
                        size_str = "文件夹"
                    else:
                        if file_size < 1024:
                            size_str = f"{file_size} B"
                        elif file_size < 1024 * 1024:
                            size_str = f"{file_size / 1024:.2f} KB"
                        elif file_size < 1024 * 1024 * 1024:
                            size_str = f"{file_size / (1024 * 1024):.2f} MB"
                        else:
                            size_str = f"{file_size / (1024 * 1024 * 1024):.2f} GB"
                    
                    # 使用QFileInfo获取更准确的文件信息，特别是日期
                    from PyQt5.QtCore import QFileInfo, QDateTime
                    qfile_info = QFileInfo(file_path)
                    
                    # 日期格式化
                    if qfile_info.exists():
                        if qfile_info.isFile():
                            # 对于文件，尝试获取创建和修改日期
                            created_time = qfile_info.birthTime().toString("yyyy-MM-dd HH:mm:ss") if qfile_info.birthTime().isValid() else "未知"
                            modified_time = qfile_info.lastModified().toString("yyyy-MM-dd HH:mm:ss") if qfile_info.lastModified().isValid() else "未知"
                        else:  # 对于文件夹
                            created_time = "文件夹"
                            modified_time = qfile_info.lastModified().toString("yyyy-MM-dd HH:mm:ss") if qfile_info.lastModified().isValid() else "未知"
                    else:
                        # 如果文件不存在，显示默认信息
                        created_time = "文件不存在"
                        modified_time = "文件不存在"
                    
                    # 构建悬浮信息文本
                    tooltip_text = f"文件名: {file_name}\n"
                    if not file_info["is_dir"]:
                        tooltip_text += f"文件大小: {size_str}\n"
                    tooltip_text += f"文件类型: {file_type}\n"
                    tooltip_text += f"路径: {file_path}\n"
                    if file_info["is_dir"]:
                        tooltip_text += f"修改日期: {modified_time}"
                    else:
                        tooltip_text += f"创建日期: {created_time}\n"
                        tooltip_text += f"修改日期: {modified_time}"
                    
                    return tooltip_text
            
            # 检查直接控件是否有文本
            if hasattr(direct_widget, "text") and direct_widget.text():
                return direct_widget.text()
        
        # 如果没有指定控件，使用直接获取的控件
        if not widget:
            widget = direct_widget
            if not widget:
                return ""
        
        # 递归查找有文本的子控件
        def find_text_in_children(w):
            # 检查当前控件是否有文本
            if hasattr(w, "text") and w.text():
                return w.text()
            
            # 特殊处理文件选择器中的文件卡片（QWidget#FileCard）
            if hasattr(w, "objectName") and w.objectName() == "FileCard":
                if hasattr(w, "file_info"):
                    file_info = w.file_info
                    file_name = file_info["name"]
                    file_path = file_info["path"]
                    return f"{file_name}\n{file_path}"
            
            # 检查是否有itemAt方法（如QListWidget、QTreeWidget等）
            if hasattr(w, "itemAt"):
                pos = w.mapFromGlobal(self.last_mouse_pos)
                item = w.itemAt(pos)
                if item and hasattr(item, "text"):
                    return item.text()
            
            # 递归检查所有子控件和布局
            from PyQt5.QtWidgets import QWidget, QLayout
            
            # 检查所有直接子控件
            for child in w.children():
                if isinstance(child, QWidget):
                    # 检查子控件是否可见且鼠标在其范围内
                    if child.isVisible():
                        child_rect = child.rect()
                        child_global_pos = child.mapToGlobal(QPoint(0, 0))
                        mouse_in_child = QRect(child_global_pos, child_rect.size()).contains(self.last_mouse_pos)
                        
                        if mouse_in_child:
                            text = find_text_in_children(child)
                            if text:
                                return text
                elif isinstance(child, QLayout):
                    # 检查布局中的所有控件
                    for i in range(child.count()):
                        layout_item = child.itemAt(i)
                        if layout_item:
                            if layout_item.widget():
                                layout_widget = layout_item.widget()
                                if layout_widget.isVisible():
                                    # 检查鼠标是否在布局控件范围内
                                    layout_widget_rect = layout_widget.rect()
                                    layout_widget_global_pos = layout_widget.mapToGlobal(QPoint(0, 0))
                                    mouse_in_layout_widget = QRect(layout_widget_global_pos, layout_widget_rect.size()).contains(self.last_mouse_pos)
                                    
                                    if mouse_in_layout_widget:
                                        # 递归查找布局控件的文本
                                        text = find_text_in_children(layout_widget)
                                        if text:
                                            return text
                            elif layout_item.layout():
                                # 递归检查子布局
                                text = find_text_in_children(layout_item.layout())
                                if text:
                                    return text
            
            return ""
        
        # 检查目标控件是否有文本
        if hasattr(widget, "text") and widget.text():
            return widget.text()
        
        # 递归检查子控件
        text = find_text_in_children(widget)
        if text:
            return text
        
        # 如果没有找到文本，尝试检查直接控件的父控件
        if direct_widget:
            parent = direct_widget.parent()
            while parent:
                from .file_horizontal_card import CustomFileHorizontalCard
                if isinstance(parent, CustomFileHorizontalCard):
                    file_path = parent.file_path
                    if parent._display_name:
                        file_name = parent._display_name
                    else:
                        import os
                        file_name = os.path.basename(file_path)
                    return f"{file_name}\n{file_path}"
                
                if hasattr(parent, "text") and parent.text():
                    return parent.text()
                parent = parent.parent()
        
        return ""
    
    def paintEvent(self, event):
        """绘制圆角卡片"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 获取颜色设置
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
        
        # 从应用实例获取设置管理器，而不是创建新实例
        if hasattr(app, 'settings_manager'):
            settings_manager = app.settings_manager
        else:
            # 回退方案：如果应用实例中没有settings_manager，再创建新实例
            from freeassetfilter.core.settings_manager import SettingsManager
            settings_manager = SettingsManager()
        
        current_colors = settings_manager.get_setting("appearance.colors", {})
        base_color = current_colors.get("base_color", "#ffffff")
        
        # 绘制背景
        brush = QBrush(QColor(base_color))
        painter.setBrush(brush)
        
        # 移除边框
        painter.setPen(QPen(Qt.transparent))
        
        # 绘制圆角矩形
        rect = QRect(0, 0, self.width() - 1, self.height() - 1)
        radius = 4
        painter.drawRoundedRect(rect, radius, radius)
