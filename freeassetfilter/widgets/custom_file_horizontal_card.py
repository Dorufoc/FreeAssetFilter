#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0
Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>
协议说明：本软件基于 MIT 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；
项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE
自定义文件横向卡片组件
采用左右结构布局，左侧为缩略图/图标，右侧为文字信息
"""
import os
import sys
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QSizePolicy, QStackedLayout
)
from .button_widgets import CustomButton
from PyQt5.QtCore import (
    Qt, pyqtSignal, QFileInfo, QEvent, QPropertyAnimation, QEasingCurve
)
from PyQt5.QtGui import (
    QFont, QFontMetrics, QPixmap
)
# 导入悬浮详细信息组件
from .hover_tooltip import HoverTooltip
# 添加项目根目录到Python路径
sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
)
from freeassetfilter.core.svg_renderer import SvgRenderer  # noqa: E402 模块级别的导入不在文件顶部（需要先添加路径）


class CustomFileHorizontalCard(QWidget):
    """
    自定义文件横向卡片组件
    
    信号：
        clicked (str): 鼠标单击事件，传递文件路径
        doubleClicked (str): 鼠标双击事件，传递文件路径
        selectionChanged (bool, str): 选中状态改变事件，传递选中状态和文件路径
    
    属性：
        file_path (str): 文件路径
        is_selected (bool): 是否选中
        thumbnail_mode (str): 缩略图显示模式，可选值：'icon' 或 'custom'
        dpi_scale (float): DPI缩放因子
        enable_multiselect (bool): 是否开启多选功能
    
    方法：
        set_file_path(file_path): 设置文件路径
        set_selected(selected): 设置选中状态
        set_thumbnail_mode(mode): 设置缩略图显示模式
        set_enable_multiselect(enable): 设置是否开启多选功能
    
    参数：
        file_path (str): 文件路径
        parent (QWidget): 父部件
        enable_multiselect (bool): 是否开启多选功能，默认值为True
    """
    # 信号定义
    clicked = pyqtSignal(str)
    doubleClicked = pyqtSignal(str)
    selectionChanged = pyqtSignal(bool, str)
    renameRequested = pyqtSignal(str)  # 重命名请求信号，传递文件路径
    deleteRequested = pyqtSignal(str)  # 删除请求信号，传递文件路径

    def __init__(self, file_path=None, parent=None, enable_multiselect=True, display_name=None):
        super().__init__(parent)
        
        # 获取应用实例和DPI缩放因子
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        # 获取全局字体
        self.global_font = getattr(app, 'global_font', QFont())
        
        # 设置组件字体
        self.setFont(self.global_font)
        
        # 初始化属性
        self._file_path = file_path
        self._is_selected = False
        self._thumbnail_mode = 'icon'  # 默认使用icon模式
        self._enable_multiselect = enable_multiselect  # 是否开启多选功能
        self._display_name = display_name  # 显示名称，优先于文件系统中的文件名
        
        # 鼠标悬停标志，用于跟踪鼠标是否在卡片区域内
        self._is_mouse_over = False
        
        # 初始化UI
        self.init_ui()
        
        # 初始化悬浮详细信息组件
        self.hover_tooltip = HoverTooltip(self)
        self.hover_tooltip.set_target_widget(self.card_container)
        
        # 如果提供了文件路径，加载文件信息
        if file_path:
            self.set_file_path(file_path, display_name)

    def init_ui(self):
        """初始化用户界面"""
        # 设置组件大小策略，允许自由调整宽度和高度，确保能随窗口缩小
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumWidth(0)  # 移除最小宽度限制
        # 创建主布局（垂直布局）
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 创建卡片容器（底层白色圆角矩形）
        self.card_container = QWidget()
        # 设置卡片容器大小策略，确保能随窗口缩小
        self.card_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.card_container.setMinimumWidth(0)  # 移除最小宽度限制
        self.card_container.setStyleSheet("background: transparent; border: none;")
        
        # 创建卡片内容布局
        card_content_layout = QHBoxLayout(self.card_container)
        card_content_layout.setSpacing(int(7.5 * self.dpi_scale))
        # 增加上下高度尺寸，设置为更大的数值
        min_height_margin = int(6.25 * self.dpi_scale)
        card_content_layout.setContentsMargins(
            int(7.5 * self.dpi_scale),
            min_height_margin,
            int(7.5 * self.dpi_scale),
            min_height_margin
        )
        card_content_layout.setAlignment(Qt.AlignVCenter)
        
        # 缩略图/图标显示组件
        self.icon_display = QLabel()
        self.icon_display.setAlignment(Qt.AlignCenter)
        self.icon_display.setFixedSize(int(20 * self.dpi_scale), int(20 * self.dpi_scale))
        self.icon_display.setStyleSheet('background: transparent; border: none;')
        card_content_layout.addWidget(self.icon_display, alignment=Qt.AlignVCenter)
        
        # 文字信息区
        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(int(4 * self.dpi_scale))
        text_layout.setAlignment(Qt.AlignVCenter)
        
        # 文件名标签
        self.name_label = QLabel()
        self.name_label.setAlignment(Qt.AlignLeft)
        self.name_label.setWordWrap(False)
        # 设置最小宽度为0，允许自由收缩
        self.name_label.setMinimumWidth(0)
        # 忽略文字自然长度，允许自由收缩
        self.name_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        # 设置字体大小和粗细
        name_font = QFont(self.global_font)
        name_font.setBold(True)  # 字重600
        scaled_font_size = int(4 * self.dpi_scale)
        name_font.setPointSize(scaled_font_size)
        self.name_label.setFont(name_font)
        self.name_label.setStyleSheet("background: transparent; border: none; color: #333333;")
        text_layout.addWidget(self.name_label)
        
        # 文件信息标签
        self.info_label = QLabel()
        self.info_label.setAlignment(Qt.AlignLeft)
        self.info_label.setWordWrap(False)
        # 设置最小宽度为0，允许自由收缩
        self.info_label.setMinimumWidth(0)
        # 忽略文字自然长度，允许自由收缩
        self.info_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        # 设置字体大小
        info_font = QFont(self.global_font)
        scaled_info_font_size = int(3 * self.dpi_scale)
        info_font.setPointSize(scaled_info_font_size)
        self.info_label.setFont(info_font)
        self.info_label.setStyleSheet("background: transparent; border: none; color: #666666;")
        text_layout.addWidget(self.info_label)
        
        card_content_layout.addLayout(text_layout, 1)
        
        # 创建覆盖层布局（用于放置功能按钮）
        self.overlay_widget = QWidget(self.card_container)
        self.overlay_widget.setStyleSheet("background: transparent; border: none;")
        # 确保覆盖层大小始终与卡片容器一致
        self.overlay_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.overlay_widget.setGeometry(self.card_container.rect())
        
        # 设置覆盖层布局
        overlay_layout = QHBoxLayout(self.overlay_widget)
        # 使用与卡片内容布局相同的上下边距
        min_height_margin = int(6.25 * self.dpi_scale)
        overlay_layout.setContentsMargins(
            int(2.5 * self.dpi_scale),
            min_height_margin,
            int(2.5 * self.dpi_scale),
            min_height_margin
        )
        overlay_layout.setSpacing(int(2.5 * self.dpi_scale))
        # 右对齐，确保按钮始终在右侧
        overlay_layout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        
        # 创建两个功能按钮，使用默认大小
        self.button1 = CustomButton(
            "重命名",
            parent=self.overlay_widget,
            button_type="primary",
            display_mode="text"
        )
        self.button2 = CustomButton(
            "删除",
            parent=self.overlay_widget,
            button_type="warning",
            display_mode="text"
        )
        
        # 确保按钮不会超出显示区域
        self.button1.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.button2.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        
        # 在按钮左侧添加伸展因子，确保按钮始终靠右显示，不会超出显示区域
        overlay_layout.addStretch(1)
        
        # 添加按钮到覆盖层布局
        overlay_layout.addWidget(self.button1)
        overlay_layout.addWidget(self.button2)
        
        # 连接按钮信号
        self.button1.clicked.connect(lambda: self.renameRequested.emit(self._file_path))
        self.button2.clicked.connect(lambda: self.deleteRequested.emit(self._file_path))
        
        # 添加卡片容器到主布局
        main_layout.addWidget(self.card_container)
        
        # 初始隐藏覆盖层（完全隐藏，不显示）
        self.overlay_widget.setWindowOpacity(0.0)
        self.overlay_widget.hide()
        
        # 连接resizeEvent，确保覆盖层始终覆盖整个卡片容器
        self.card_container.resizeEvent = self.on_card_container_resize
        # 初始化卡片样式
        self.update_card_style()
        
        # 为卡片容器和覆盖层添加事件过滤器，用于处理鼠标悬停事件
        self.card_container.installEventFilter(self)
        self.overlay_widget.installEventFilter(self)

    def set_file_path(self, file_path, display_name=None):
        """
        设置文件路径并更新显示
        参数：
            file_path (str): 文件路径
            display_name (str, optional): 显示名称，优先于文件系统中的文件名
        """
        self._file_path = file_path
        if display_name is not None:
            self._display_name = display_name
        self._load_file_info()
        self._set_file_icon()

    def set_selected(self, selected):
        """
        设置选中状态
        
        参数：
            selected (bool): 是否选中
        """
        if self._enable_multiselect:
            # 只有开启多选功能时，才处理选中状态的变化
            self._is_selected = selected
            self.update_card_style()
            self.selectionChanged.emit(selected, self._file_path)

    def set_thumbnail_mode(self, mode):
        """
        设置缩略图显示模式
        参数：
            mode (str): 显示模式，可选值：'icon' 或 'custom'
        """
        if mode in ['icon', 'custom']:
            self._thumbnail_mode = mode
            self._set_file_icon()

    def _load_file_info(self):
        """
        加载文件信息
        """
        if not self._file_path:
            return
        
        try:
            file_info = QFileInfo(self._file_path)
            
            # 优先使用_display_name，否则从文件系统获取文件名
            if hasattr(self, '_display_name') and self._display_name:
                file_name = self._display_name
            else:
                file_name = file_info.fileName()
            
            # 获取文件路径
            file_path = file_info.absoluteFilePath()
            
            # 获取文件大小
            if file_info.isDir():
                file_size = "文件夹"
            else:
                file_size = self._format_size(file_info.size())
            
            # 计算文本宽度，设置自动截断
            # 获取当前组件宽度作为参考（减去图标和边距）
            component_width = self.width()
            # 调试信息：打印组件宽度
            print(f"_load_file_info called, component_width: {component_width}")
            if component_width <= 0:
                # 如果组件宽度还未计算，使用一个默认值
                component_width = int(87.5 * self.dpi_scale)
                print(f"Using default component_width: {component_width}")
            
            # 文件名截断处理
            name_font_metrics = QFontMetrics(self.name_label.font())
            # 留一些边距和图标的宽度
            icon_margin = int(10 * self.dpi_scale)
            available_width = component_width - icon_margin  # 图标宽度 + 边距
            # 调试信息：打印可用宽度计算
            print(f"icon_margin: {icon_margin}, available_width: {available_width}")
            if available_width < 0:
                available_width = 0
                print(f"available_width < 0, setting to 0")
            
            # 调试信息：打印文字截断前的完整文本
            print(f"Original file name: '{file_name}'")
            
            elided_file_name = name_font_metrics.elidedText(file_name, Qt.ElideRight, available_width)
            
            # 文件信息截断处理
            info_text = f"{file_path}  {file_size}"
            
            # 调试信息：打印文字截断前的完整文本
            print(f"Original info text: '{info_text}'")
            info_font_metrics = QFontMetrics(self.info_label.font())
            elided_info_text = info_font_metrics.elidedText(info_text, Qt.ElideRight, available_width)
            
            # 调试信息：打印截断后的文本
            print(f"Elided file name: '{elided_file_name}'")
            print(f"Elided info text: '{elided_info_text}'")
            
            # 更新标签文本
            self.name_label.setText(elided_file_name)
            self.info_label.setText(elided_info_text)
            
        except Exception as e:
            print(f"加载文件信息失败: {e}")

    def _set_file_icon(self):
        """设置文件图标或缩略图"""
        if not self._file_path:
            return
        try:
            file_info = QFileInfo(self._file_path)
            # 根据文件类型设置图标
            suffix = file_info.suffix().lower()
            
            # 首先处理lnk和exe文件，使用它们自身的图标
            if suffix in ["lnk", "exe"]:
                # 应用DPI缩放因子到图标大小，然后将lnk和exe图标大小调整为现在的0.8倍
                base_icon_size = int(10 * self.dpi_scale)
                scaled_icon_size = int(base_icon_size * 0.8)
                
                # 使用QFileIconProvider来获取文件图标，这在Windows上更可靠
                from PyQt5.QtWidgets import QFileIconProvider
                icon_provider = QFileIconProvider()
                icon = icon_provider.icon(file_info)
                pixmap = icon.pixmap(scaled_icon_size, scaled_icon_size)
                
                # 检查是否获取到有效图标
                if not pixmap.isNull():
                    self.icon_display.setPixmap(pixmap)
                    return
            
            # 检查是否存在已生成的缩略图
            import hashlib
            import os
            # 缩略图存储路径与CustomFileSelector保持一致
            # CustomFileSelector中使用的是：os.path.join(os.path.dirname(__file__), "..", "..", "data", "thumbnails")
            # 这里需要调整路径计算，确保指向相同的data目录
            thumb_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data", "thumbnails")
            # 计算文件路径的MD5哈希值，并使用前16位作为文件名
            md5_hash = hashlib.md5(self._file_path.encode('utf-8'))
            file_hash = md5_hash.hexdigest()[:16]  # 使用前16位十六进制字符串
            thumbnail_path = os.path.join(thumb_dir, f"{file_hash}.png")
            
            # 检查是否是照片或视频类型，这些类型可以使用缩略图
            is_photo = suffix in ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'tiff', 'avif', 'cr2', 'cr3', 'nef', 'arw', 'dng', 'orf']
            is_video = suffix in ['mp4', 'mov', 'avi', 'mkv', 'wmv', 'flv', 'webm', 'm4v', 'mpeg', 'mpg', 'mxf']
            
            # 只有照片和视频类型才使用缩略图，其余类型直接使用SVG图标
            use_thumbnail = False
            if (is_photo or is_video) and os.path.exists(thumbnail_path):
                use_thumbnail = True
            
            if use_thumbnail:
                scaled_icon_size = int(20 * self.dpi_scale)
                pixmap = QPixmap(thumbnail_path)
                # 调整缩略图大小以适应图标显示区域
                pixmap = pixmap.scaled(scaled_icon_size, scaled_icon_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.icon_display.setPixmap(pixmap)
                return
            
            # 对于其他文件类型，使用图标处理逻辑
            icon_path = self._get_file_icon_path(suffix, file_info.isDir())
            if icon_path and os.path.exists(icon_path):
                # 应用DPI缩放因子到图标大小
                scaled_icon_size = int(40 * self.dpi_scale)
                
                # 使用SvgRenderer.render_svg_to_widget直接渲染SVG图标，返回QSvgWidget对象
                svg_widget = SvgRenderer.render_svg_to_widget(icon_path, 40, self.dpi_scale)
                svg_widget.setFixedSize(scaled_icon_size, scaled_icon_size)
                # 确保QSvgWidget完全透明，没有任何可见样式
                svg_widget.setStyleSheet("background: transparent; border: none; padding: 0; margin: 0;")
                svg_widget.setAttribute(Qt.WA_TranslucentBackground, True)
                
                # 如果是未知文件类型或压缩文件类型，需要在图标上显示后缀名
                if icon_path.endswith("未知底板.svg") or icon_path.endswith("压缩文件.svg"):
                    # 获取后缀名，压缩文件显示带点的后缀名（如".zip"），未知文件显示大写后缀名
                    if icon_path.endswith("压缩文件.svg"):
                        display_suffix = "." + file_info.suffix()
                    else:
                        display_suffix = file_info.suffix().upper()
                        
                        # 限制未知文件后缀名长度，最多5个字符
                        if len(display_suffix) > 5:
                            display_suffix = "FILE"
                    
                    # 创建文字标签
                    from PyQt5.QtWidgets import QLabel
                    from PyQt5.QtGui import QFont, QFontMetrics, QFontDatabase
                    
                    text_label = QLabel(display_suffix)
                    text_label.setAlignment(Qt.AlignCenter)
                    # 确保文字标签完全透明，没有任何可见样式
                    text_label.setStyleSheet('background: transparent; border: none; padding: 0; margin: 0;')
                    text_label.setAttribute(Qt.WA_TranslucentBackground, True)
                    
                    # 设置字体
                    font_path = os.path.join(os.path.dirname(__file__), "..", "icons", "庞门正道标题体.ttf")
                    font = QFont()
                    
                    # 尝试加载字体文件，如果失败则使用默认字体
                    if os.path.exists(font_path):
                        font_id = QFontDatabase.addApplicationFont(font_path)
                        if font_id != -1:
                            font_family = QFontDatabase.applicationFontFamilies(font_id)[0]
                            font.setFamily(font_family)
                    
                    # 设置字体大小，应用DPI缩放
                    font_size = int(4 * self.dpi_scale)
                    font.setPointSize(font_size)
                    font.setBold(True)
                    
                    # 自适应调整字体大小，确保文字不超出图标边界
                    font_metrics = QFontMetrics(font)
                    text_width = font_metrics.width(display_suffix)
                    
                    # 应用DPI缩放因子到最大文本宽度和最小字体大小
                    max_text_width = int(7.5 * self.dpi_scale)
                    min_font_size = int(4 * self.dpi_scale)
                    
                    while text_width > max_text_width and font_size > min_font_size:
                        font_size -= 1
                        font.setPointSize(font_size)
                        font_metrics = QFontMetrics(font)
                        text_width = font_metrics.width(display_suffix)
                    
                    text_label.setFont(font)
                    
                    # 设置文字颜色：压缩文件使用白色，未知文件使用黑色
                    if icon_path.endswith("压缩文件.svg"):
                        text_label.setStyleSheet('background: transparent; border: none; color: white; padding: 0; margin: 0;')
                    else:
                        text_label.setStyleSheet('background: transparent; border: none; color: black; padding: 0; margin: 0;')
                    
                    # 将文字标签添加到svg_widget上方
                    text_label.setGeometry(0, 0, scaled_icon_size, scaled_icon_size)
                    text_label.setParent(svg_widget)
                
                # 替换QLabel为我们的QSvgWidget
                # 首先移除原有的QLabel
                self.card_container.layout().removeWidget(self.icon_display)
                self.icon_display.deleteLater()
                
                # 保存新的图标显示组件
                self.icon_display = svg_widget
                
                # 将新的QSvgWidget添加回卡片布局
                self.card_container.layout().insertWidget(0, self.icon_display, alignment=Qt.AlignVCenter)
            else:
                # 设置默认图标
                self.icon_display.setText("📄")
                font = QFont()
                font.setPointSize(int(12 * self.dpi_scale))
                self.icon_display.setFont(font)
        except Exception as e:
            print(f"设置文件图标失败: {e}")

    def _get_file_icon_path(self, suffix, is_dir=False):
        """获取文件图标路径"""
        icon_dir = os.path.join(os.path.dirname(__file__), '..', 'icons')
        if is_dir:
            return os.path.join(icon_dir, "文件夹.svg")
        # 根据文件后缀返回对应的图标路径
        icon_map = {
            # 视频格式
            'mp4': '视频.svg', 'mov': '视频.svg', 'avi': '视频.svg',
            'mkv': '视频.svg', 'wmv': '视频.svg', 'flv': '视频.svg',
            'webm': '视频.svg', 'm4v': '视频.svg', 'mpeg': '视频.svg',
            'mpg': '视频.svg', 'mxf': '视频.svg',
            # 图片格式
            'jpg': '图像.svg', 'jpeg': '图像.svg', 'png': '图像.svg',
            'gif': '图像.svg', 'bmp': '图像.svg', 'webp': '图像.svg',
            'tiff': '图像.svg', 'svg': '图像.svg', 'avif': '图像.svg',
            'cr2': '图像.svg', 'cr3': '图像.svg', 'nef': '图像.svg',
            'arw': '图像.svg', 'dng': '图像.svg', 'orf': '图像.svg',
            # 文档格式
            'pdf': 'PDF.svg', 'ppt': 'PPT.svg', 'pptx': 'PPT.svg',
            'xls': '表格.svg', 'xlsx': '表格.svg',
            'doc': 'Word文档.svg', 'docx': 'Word文档.svg',
            'txt': '文档.svg', 'md': '文档.svg', 'rtf': '文档.svg',
            # 字体格式
            'ttf': '字体.svg', 'otf': '字体.svg', 'woff': '字体.svg',
            'woff2': '字体.svg', 'eot': '字体.svg',
            # 音频格式
            'mp3': '音乐.svg', 'wav': '音乐.svg', 'flac': '音乐.svg',
            'aac': '音乐.svg', 'ogg': '音乐.svg', 'm4a': '音乐.svg',
            # 压缩文件格式
            'zip': '压缩文件.svg', 'rar': '压缩文件.svg', '7z': '压缩文件.svg',
            'tar': '压缩文件.svg', 'gz': '压缩文件.svg', 'bz2': '压缩文件.svg',
        }
        return os.path.join(icon_dir, icon_map.get(suffix, "未知底板.svg"))

    def _format_size(self, size):
        """格式化文件大小"""
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.2f} KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.2f} MB"
        else:
            return f"{size / (1024 * 1024 * 1024):.2f} GB"

    def update_card_style(self):
        """更新卡片样式"""
        scaled_border_width = int(1 * self.dpi_scale)
        scaled_border_radius = int(1.5 * self.dpi_scale)
        # 设置组件本身的样式（透明背景）
        self.setStyleSheet("""
            QWidget {
                background: transparent;
                border: none;
            }
        """)
        # 设置卡片容器的样式
        if self._enable_multiselect and self._is_selected:
            # 开启多选功能且被选中：背景色变为蓝色
            card_style = ""
            card_style += "QWidget {"
            card_style += "background-color: #1890ff;"
            card_style += f"border: {scaled_border_width}px solid #1890ff;"
            card_style += f"border-radius: {scaled_border_radius}px;"
            card_style += "}"
            self.card_container.setStyleSheet(card_style)
            # 设置文字颜色
            self.name_label.setStyleSheet("background: transparent; border: none; color: #ffffff;")
            self.info_label.setStyleSheet("background: transparent; border: none; color: #ffffff;")
        else:
            # 默认状态：纯白色圆角矩形
            # 如果未开启多选功能，始终显示默认样式，不考虑选中状态
            card_style = ""
            card_style += "QWidget {"
            card_style += "background-color: #ffffff;"
            card_style += f"border: {scaled_border_width}px solid #e0e0e0;"
            card_style += f"border-radius: {scaled_border_radius}px;"
            card_style += "}"
            card_style += "QWidget:hover {"
            card_style += "border-color: #4a7abc;"
            card_style += "background-color: #f0f8ff;"
            card_style += "}"
            self.card_container.setStyleSheet(card_style)
            # 设置文字颜色
            self.name_label.setStyleSheet("background: transparent; border: none; color: #333333;")
            self.info_label.setStyleSheet("background: transparent; border: none; color: #666666;")

    def mousePressEvent(self, event):
        """处理鼠标按下事件"""
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._file_path)
            super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        """处理鼠标双击事件"""
        if event.button() == Qt.LeftButton:
            self.doubleClicked.emit(self._file_path)
            super().mouseDoubleClickEvent(event)
    
    def resizeEvent(self, event):
        """处理大小变化事件，重新计算文字截断"""
        super().resizeEvent(event)
        # 调试信息：打印卡片宽度
        print(f"resizeEvent triggered, card width: {self.width()}")
        # 当卡片尺寸改变时，重新计算文字的截断显示
        if self._file_path:
            self._load_file_info()

    def eventFilter(self, obj, event):
        """事件过滤器，用于处理鼠标悬停事件"""
        from PyQt5.QtCore import QEvent
        
        if event.type() == QEvent.Enter:
            # 鼠标进入卡片容器或覆盖层，直接显示按钮
            if not self._is_mouse_over:
                self._is_mouse_over = True
                # 确保覆盖层大小与卡片容器一致
                self.on_card_container_resize(None)
                # 强制刷新布局，确保按钮位置正确
                self.overlay_widget.layout().invalidate()
                self.overlay_widget.layout().activate()
                self.overlay_widget.setWindowOpacity(1.0)
                self.overlay_widget.show()
        elif event.type() == QEvent.Leave:
            # 鼠标离开卡片容器或覆盖层，直接隐藏按钮
            if self._is_mouse_over:
                self._is_mouse_over = False
                self.overlay_widget.hide()
                self.overlay_widget.setWindowOpacity(0.0)
        
        return super().eventFilter(obj, event)
    
    def on_card_container_resize(self, event):
        """当卡片容器大小改变时，调整覆盖层的大小"""
        # 调用原有的resizeEvent方法
        QWidget.resizeEvent(self.card_container, event)
        # 确保覆盖层的大小始终与卡片容器一致
        self.overlay_widget.setGeometry(self.card_container.rect())
        # 确保覆盖层的宽度不超过卡片容器的宽度
        self.overlay_widget.setMaximumWidth(self.card_container.width())
        # 确保覆盖层的高度不超过卡片容器的高度
        self.overlay_widget.setMaximumHeight(self.card_container.height())

    @property
    def file_path(self):
        return self._file_path

    @file_path.setter
    def file_path(self, value):
        self.set_file_path(value)

    @property
    def is_selected(self):
        return self._is_selected

    @is_selected.setter
    def is_selected(self, value):
        self.set_selected(value)

    @property
    def thumbnail_mode(self):
        return self._thumbnail_mode

    @thumbnail_mode.setter
    def thumbnail_mode(self, value):
        self.set_thumbnail_mode(value)

    @property
    def enable_multiselect(self):
        """获取是否开启多选功能"""
        return self._enable_multiselect

    @enable_multiselect.setter
    def enable_multiselect(self, value):
        """设置是否开启多选功能
        
        参数：
            value (bool): 是否开启多选功能
        """
        self._enable_multiselect = value
        # 更新卡片样式，确保样式正确反映当前的多选功能状态
        self.update_card_style()

    def set_enable_multiselect(self, enable):
        """设置是否开启多选功能
        
        参数：
            enable (bool): 是否开启多选功能
        """
        self.enable_multiselect = enable