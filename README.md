# FreeAssetFilter v1.0

基于PyQt5的多功能文件预览和管理工具，支持多种文件类型的快速预览和筛选。

## 🌟 功能特性

### 📁 文件管理
- 直观的文件浏览界面
- 支持多目录文件选择
- 文件临时存储池，便于批量管理
- 支持文件拖拽操作

### 🎨 多种文件预览
- **图片预览**：支持JPG、PNG、GIF等多种图片格式
- **视频播放**：集成VLC播放器，支持多种视频格式
- **音频播放**：支持MP3、WAV等音频格式，显示音频信息
- **PDF预览**：支持PDF文件的快速预览
- **文档查看**：支持TXT、MD等文本文件
- **字体预览**：支持字体文件的实时预览

### 🎯 高效筛选
- 基于文件类型的快速筛选
- 支持文件名称搜索
- 多条件组合筛选

### 🎨 美观界面
- 现代化的UI设计
- 支持主题切换
- 响应式布局，适配不同屏幕尺寸

## 🚀 安装指南

### 环境要求
- Python 3.7+
- PyQt5 5.15.0+

### 安装步骤

1. **克隆项目**
   ```bash
   git clone https://github.com/Dorufoc/FreeAssetFilter.git
   cd FreeAssetFilter
   ```

2. **安装依赖**
   ```bash
   pip install -r requirements.txt
   ```

3. **运行程序**
   ```bash
   python main.py
   ```

## 📖 使用说明

### 基本操作

1. **文件浏览**
   - 在左侧面板浏览文件系统
   - 点击文件或文件夹进行导航
   - 支持快捷键操作

2. **文件选择**
   - 单击文件进行预览
   - 右键点击文件进行更多操作
   - 按住Ctrl键可多选文件

3. **文件预览**
   - 右侧面板会自动显示选中文件的预览
   - 支持多种文件类型的实时预览
   - 部分文件类型支持编辑功能

4. **临时存储池**
   - 选中的文件会自动添加到中间的临时存储池
   - 可以在临时存储池中管理选中的文件
   - 支持从存储池中移除文件

## 📁 项目结构

```
FreeAssetFilter/
├── src/
│   ├── Icon/              # 应用程序图标
│   ├── components/        # 核心组件
│   │   ├── file_selector_ui/  # 文件选择器UI
│   │   ├── archive_browser.py  # 压缩包浏览器
│   │   ├── custom_file_selector.py  # 自定义文件选择器
│   │   ├── file_selector.py  # 文件选择器
│   │   ├── file_staging_pool.py  # 文件临时存储池
│   │   ├── folder_content_list.py  # 文件夹内容列表
│   │   ├── font_previewer.py  # 字体预览器
│   │   ├── native_file_selector.py  # 原生文件选择器
│   │   ├── native_file_selector_widget.py  # 原生文件选择器组件
│   │   ├── pdf_previewer.py  # PDF预览器
│   │   ├── photo_viewer.py  # 图片查看器
│   │   ├── text_previewer.py  # 文本预览器
│   │   ├── unified_previewer.py  # 统一预览器
│   │   └── video_player.py  # 视频播放器
│   ├── core/              # 核心功能
│   │   ├── file_info_viewer.py  # 文件信息查看器
│   │   └── player_core.py  # 播放器核心
│   ├── ui/                # UI组件
│   │   └── file_info_panel.py  # 文件信息面板
│   └── utils/             # 工具函数
│       ├── svg_renderer.py  # SVG渲染器
│       └── thumbnail_manager.py  # 缩略图管理器
├── component_launcher.py  # 组件启动器
├── fix_encoding.py        # 编码修复工具
├── main.py                # 主程序入口
├── requirements.txt       # 项目依赖
├── LICENSE                # 许可证文件
└── README.md              # 项目说明文档
```

## 🛠️ 技术栈

- **GUI框架**：PyQt5 5.15.0+
- **媒体播放**：python-vlc 3.0.16120+
- **音频处理**：mutagen 1.45.0+
- **图像处理**：Pillow 8.0.0+
- **PDF处理**：PyMuPDF 1.18.0+
- **文本处理**：markdown 3.3.0+, Pygments 2.8.0+
- **EXIF处理**：exifread 2.3.0+

## 📄 许可证

本项目基于 MIT 协议开源，请参考 [LICENSE](LICENSE) 文件获取详细信息。

## 🤝 贡献指南

欢迎提交Issue和Pull Request来帮助改进这个项目！

### 提交Issue
1. 确保Issue描述清晰，包含复现步骤（如果是Bug）
2. 提供相关截图或日志（如果适用）
3. 标明使用的操作系统和Python版本

### 提交Pull Request
1. Fork本项目
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 打开Pull Request

## 📞 联系方式

- 作者：Dorufoc
- 邮箱：qpdrfc123@gmail.com
- 项目地址：https://github.com/Dorufoc/FreeAssetFilter

## 📊 项目统计

![GitHub stars](https://img.shields.io/github/stars/Dorufoc/FreeAssetFilter?style=social)
![GitHub forks](https://img.shields.io/github/forks/Dorufoc/FreeAssetFilter?style=social)
![GitHub issues](https://img.shields.io/github/issues/Dorufoc/FreeAssetFilter)
![GitHub license](https://img.shields.io/github/license/Dorufoc/FreeAssetFilter)



**FreeAssetFilter** - 让文件管理更高效，让资源筛选更简单！ 🎉