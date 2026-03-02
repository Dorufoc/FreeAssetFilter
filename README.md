<div align="center">

<img src="freeassetfilter/icons/FAF-main.png" alt="FreeAssetFilter Logo" width="128" height="128">

# FreeAssetFilter

**一款强大的多功能文件预览与管理工具，让文件浏览如丝般高效顺滑**

[![GitHub Release](https://img.shields.io/github/v/release/Dorufoc/FreeAssetFilter?style=flat-square&logo=github&color=blue)](https://github.com/Dorufoc/FreeAssetFilter/releases)
[![Python Version](https://img.shields.io/badge/Python-3.9%2B-blue?style=flat-square&logo=python)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/PySide6-6.4%2B-green?style=flat-square&logo=qt)](https://wiki.qt.io/Qt_for_Python)  
[![License](https://img.shields.io/badge/License-AGPL--3.0-orange?style=flat-square)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows-purple?style=flat-square&logo=windows)](https://www.microsoft.com/windows)

[English](README_EN.md) • [功能预览](#-功能预览) • [快速开始](#-快速开始) • [功能特性](#-功能特性) • [安装指南](#-安装指南) • [使用说明](#-使用说明) • [技术架构](#-技术架构) • [开发指南](#-开发指南) • [贡献指南](#-贡献指南)

<img src="freeassetfilter/icons/example1.png" alt="FreeAssetFilter Screenshot" width="800">

</div>

---

## 功能预览

### 核心亮点

- **极速启动** - 优化的预加载机制，秒级启动体验
- **专业预览** - 支持 100+ 种文件格式，覆盖图像、视频、音频、文档
- **三栏布局** - 文件浏览、筛选、预览一气呵成的高效工作流
- **深色模式** - 支持深色/浅色主题切换，呵护您的眼睛
- **高性能** - C++ 核心算法 + 异步加载，流畅不卡顿

---

## 快速开始

### 环境要求

| 项目               | 要求                               |
| ------------------ | ---------------------------------- |
| **操作系统** | Windows 10/11 (64位)               |
| **Python**   | 3.9 或更高版本                     |
| **内存**     | 建议 4GB 以上                      |
| **显卡**     | 支持 OpenGL 的显卡（用于视频播放） |

### 一键安装

```bash
# 克隆仓库
git clone https://github.com/Dorufoc/FreeAssetFilter.git
cd FreeAssetFilter

# 创建虚拟环境（推荐）
python -m venv venv
venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 运行应用
python -m freeassetfilter.app.main
```

### 常见问题

<details>
<summary><b>启动时提示缺少 DLL 文件？</b></summary>

请安装 [Visual C++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe) 后重试。

</details>

<details>
<summary><b>视频无法播放？</b></summary>

请确保显卡驱动已更新，并支持 OpenGL 3.0 以上版本。

</details>

<details>
<summary><b>安装依赖时报错，提示需要编译工具？</b></summary>

部分依赖包（如 `rawpy`、`numpy` 等）需要在本地编译，请确保已安装以下工具之一：

**方案一：安装 Microsoft C++ 生成工具（推荐）**

1. 下载 [Microsoft C++ 生成工具](https://visualstudio.microsoft.com/visual-cpp-build-tools/)
2. 安装"使用 C++ 的桌面开发"工作负载
3. 重新运行 `pip install -r requirements.txt`

**方案二：使用预编译 wheel 包**

```bash
# 先升级 pip
python -m pip install --upgrade pip

# 如果在特殊网络环境下，使用镜像加速下载预编译包
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

**方案三：安装 Visual Studio（完整版）**

- 安装 [Visual Studio Community](https://visualstudio.microsoft.com/downloads/)
- 选择"使用 C++ 的桌面开发"组件

</details>

---

## 功能特性

### 文件管理

| 功能                     | 描述                                 |
| ------------------------ | ------------------------------------ |
| **智能文件浏览器** | 卡片式布局，支持缩略图显示，直观高效 |
| **文件临时存储池** | 快速收藏和整理选中文件，支持批量导出 |
| **多选与拖拽**     | 支持多文件选择、长按拖拽操作         |
| **路径导航**       | 快速跳转、历史记录、路径收藏         |
| **智能筛选**       | 按文件类型、日期、大小快速筛选       |

### 文件预览

| 类型             | 支持格式                                 | 特色功能               |
| ---------------- | ---------------------------------------- | ---------------------- |
| **图像**   | JPG, PNG, GIF, RAW, PSD, HEIC, AVIF, SVG | 便捷查看、色彩分析     |
| **视频**   | MP4, MOV, AVI, MKV, MXF                  | MPV 内核、LUT 实时预览 |
| **音频**   | MP3, WAV, FLAC, OGG, AAC                 | 元数据显示、高效播放   |
| **文档**   | PDF, DOCX, XLSX, PPTX, TXT, MD           | 完整预览、代码语法高亮 |
| **压缩包** | ZIP, RAR, 7Z, TAR                        | 无需解压即可查看内容   |
| **字体**   | TTF, OTF, WOFF                           | 实时渲染预览           |

### 个性化设置

- **主题系统** - 深色/浅色模式，支持自定义配色方案
- **DPI 自适应** - 完美支持 4K/8K 高分辨率屏幕
- **字体设置** - 可自定义界面字体和大小
- **缩略图缓存** - 智能缓存机制，提升浏览速度

### 性能优化

- **异步加载** - 缩略图后台生成，不阻塞主线程
- **C++ 扩展** - 核心算法使用 C++ 实现，性能卓越
- **内存管理** - 智能缓存清理，优化内存占用
- **启动加速** - 预加载机制，快速启动应用

### 功能对比

| 功能     | FreeAssetFilter | QuickLook   | Seer        | Explorer  |
| -------- | --------------- | ----------- | ----------- | --------- |
| 图像预览 | ✅ 100+ 格式    | ✅ 常见格式 | ✅ 常见格式 | ⚠️ 有限 |
| 视频播放 | ✅ 内置播放器   | ⚠️ 需插件 | ⚠️ 需插件 | ❌        |
| RAW 支持 | ✅ 完整支持     | ⚠️ 部分   | ⚠️ 部分   | ❌        |
| PSD 预览 | ✅ 图层支持     | ❌          | ❌          | ❌        |
| LUT 还原 | ✅ 实时预览     | ❌          | ❌          | ❌        |
| 操作布局 | ✅ 三栏布局     | ❌          | ❌          | ✅        |
| 开源免费 | ✅ AGPL-3.0     | ✅ GPL      | ❌ 付费     | ✅        |

---

## 支持的格式

### 图像格式 (30+)

| 类别               | 格式                                             |
| ------------------ | ------------------------------------------------ |
| **常见格式** | JPG, JPEG, PNG, GIF, BMP, WEBP, TIFF, SVG        |
| **现代格式** | AVIF, HEIC, HEIF, JP2, JXR                       |
| **RAW 格式** | CR2, CR3, NEF, ARW, DNG, ORF, RAF, RW2, PEF, X3F |
| **专业格式** | PSD, PSB, XCF, TGA, ICO, ICNS, DDS               |

### 视频格式 (20+)

| 类别               | 格式                                     |
| ------------------ | ---------------------------------------- |
| **常见格式** | MP4, MOV, AVI, MKV, WMV, FLV, WEBM       |
| **专业格式** | MXF, VOB, M2TS, TS, MTS, M2T, DV, ProRes |
| **移动设备** | 3GP, M4V, MPEG, MPG, HEVC, H.264         |

**视频功能**：

- 基于 MPV 的高性能播放
- 支持 LUT (.cube) 实时调色
- 速度控制
- 音量控制

### 音频格式 (10+)

MP3, WAV, FLAC, OGG, WMA, AAC, M4A, OPUS, AIFF, APE, MKA, AC3

**音频功能**：

- 元数据显示（ID3、专辑封面）
- 背景样式现代化

### 文档格式 (50+)

| 类别                               | 格式                                                |
| ---------------------------------- | --------------------------------------------------- |
| **PDF**                      | PDF（完整预览、缩放）                               |
| **Office（需单独安装插件）** | DOC, DOCX, XLS, XLSX, PPT, PPTX                     |
| **文本**                     | TXT, MD, RST, RTF, CSV, JSON, XML, YAML             |
| **代码**                     | Python, JavaScript, C++, Java, Go, Rust 等 50+ 语言 |

### 压缩包格式 (10+)

ZIP, RAR, 7Z, TAR, GZ, BZ2, XZ, LZMA, ISO, CAB, ARJ

### 字体格式 (5+)

TTF, OTF, WOFF, WOFF2, EOT

---

## 安装指南

### 方法一：预编译版本（推荐）

下载最新的预编译版本：

- [📦 下载 Windows 安装包](https://github.com/Dorufoc/FreeAssetFilter/releases)

### 方法二：从源码安装

#### 1. 克隆仓库

```bash
git clone https://github.com/Dorufoc/FreeAssetFilter.git
cd FreeAssetFilter
```

#### 2. 创建虚拟环境

```bash
python -m venv venv
venv\Scripts\activate  # Windows
```

#### 3. 安装依赖

```bash
pip install -r requirements.txt
```

#### 4. 构建 C++ 扩展（可选，用于 LUT 调色功能，源代码中已包含cp39-x64编译版本）

```bash
# 构建颜色提取模块
cd freeassetfilter/core/cpp_color_extractor
python setup.py build_ext --inplace

# 构建 LUT 预览模块
cd ../cpp_lut_preview
python setup.py build_ext --inplace
```

#### 5. 运行应用

```bash
python -m freeassetfilter.app.main
```

### 系统要求详情

| 组件               | 最低要求                    | 推荐配置                    |
| ------------------ | --------------------------- | --------------------------- |
| **操作系统** | Windows 10                  | Windows 11                  |
| **处理器**   | Intel Core i3 / AMD Ryzen 3 | Intel Core i5 / AMD Ryzen 5 |
| **内存**     | 4 GB RAM                    | 8 GB RAM                    |
| **存储**     | 900MB 可用空间              | 1 GB 可用空间               |
| **显卡**     | 具有视频加速的现代集成显卡  | Nvidia/AMD现代独立显卡      |

---

## 使用说明

### 界面布局

```
┌─────────────────┬─────────────────┬─────────────────┐
│                 │                 │                 │
│   文件选择器    │   文件存储池    │    文件预览器   │
│    (30%)        │    (30%)        │    (40%)        │
│                 │                 │                 │
│  • 浏览文件夹   │  • 收藏文件     │  • 实时预览     │
│  • 缩略图显示   │  • 批量管理     │  • 详细信息     │
│  • 快速筛选     │  • 导出功能     │  • 全屏查看     │
│                 │                 │                 │
└─────────────────┴─────────────────┴─────────────────┘
```

### 基本操作

| 默认操作           | 说明             |
| ------------------ | ---------------- |
| **左键单击** | 选中文件并预览   |
| **右键单击** | 打开上下文菜单   |
| **长按拖拽** | 将文件拖到存储池 |

### 文件选择器

- **导航栏**：快速切换目录、返回上级、刷新列表
- **筛选器**：按文件类型快速筛选（图像/视频/音频/文档/全部）
- **排序**：按名称、日期、大小、类型排序
- **视图模式**：缩略图/列表模式切换

### 文件存储池

- **添加文件**：从选择器拖拽或点击添加按钮
- **清空池子**：一键清空所有文件
- **导出/导入数据**：将选中文件的路径数据文件进行存取
- **导出文件**：将选中文件导出到指定目录

### 文件预览器

- **自适应布局**：根据内容类型自动调整
- **详细信息**：显示文件元数据
- **操作按钮**：打开、复制文件、在文件夹中显示

## 技术架构

### 核心技术栈

```
FreeAssetFilter
├── GUI 框架: PySide6 (Qt6) - 跨平台图形界面
├── 图像处理: Pillow + OpenCV + rawpy - 图像解码与处理
├── 视频播放: MPV (libmpv) - 高性能视频播放
├── 文档解析: PyMuPDF + python-docx - 文档渲染
├── 音频处理: mutagen - 元数据读取
├── 压缩包: rarfile + py7zr - 归档文件处理
├── 科学计算: NumPy + SciPy + scikit-image - 图像算法
└── 扩展模块: C++ (颜色提取、LUT 处理) - 性能关键算法
```

### 项目结构

```
FreeAssetFilter/
├── freeassetfilter/
│   ├── app/                    # 应用程序入口
│   │   └── main.py            # 主程序
│   ├── components/            # UI 组件
│   │   ├── file_selector.py   # 文件选择器
│   │   ├── unified_previewer.py # 统一预览器
│   │   ├── file_staging_pool.py # 文件存储池
│   │   ├── video_player.py    # 视频播放器
│   │   ├── photo_viewer.py    # 图像查看器
│   │   ├── pdf_previewer.py   # PDF 预览器
│   │   └── ...                # 其他组件
│   ├── core/                  # 核心模块
│   │   ├── settings_manager.py    # 设置管理
│   │   ├── thumbnail_manager.py   # 缩略图管理
│   │   ├── theme_manager.py       # 主题管理
│   │   ├── mpv_player_core.py     # MPV 播放核心
│   │   ├── svg_renderer.py        # SVG 渲染
│   │   ├── cpp_color_extractor/   # C++ 颜色提取
│   │   └── cpp_lut_preview/       # C++ LUT 预览
│   ├── icons/                 # 图标资源
│   ├── utils/                 # 工具函数
│   │   ├── path_utils.py      # 路径处理
│   │   ├── icon_utils.py      # 图标处理
│   │   └── syntax/            # 语法高亮定义
│   └── widgets/               # 自定义控件库
├── data/                      # 数据目录
│   ├── settings.json          # 用户设置
│   └── thumbnails/            # 缩略图缓存
├── requirements.txt           # Python 依赖
├── README.md                  # 项目说明
└── LICENSE                    # 许可证
```

### 架构特点

- **MVC 模式**：清晰的模型-视图-控制器分离
- **单例模式**：核心管理器（设置、缩略图、播放器）
- **信号-槽机制**：组件间松耦合通信
- **多线程设计**：后台处理不阻塞 UI
- **插件化组件**：易于扩展新的文件类型支持

---

## 开发指南

### 开发环境搭建

#### 1. 克隆仓库并创建分支

```bash
git clone https://github.com/Dorufoc/FreeAssetFilter.git
cd FreeAssetFilter
git checkout -b feature/your-feature-name
```

#### 2. 安装开发依赖

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

#### 3. 配置 IDE

推荐使用 VS Code 或 PyCharm，配置以下插件：

- Python 扩展
- Qt for Python 扩展
- Black 格式化工具

### 构建 C++ 扩展

```bash
# 构建颜色提取模块
cd freeassetfilter/core/cpp_color_extractor
python setup.py build_ext --inplace

# 构建 LUT 预览模块
cd ../cpp_lut_preview
python setup.py build_ext --inplace
```

### 代码规范

- **类型注解**：所有函数添加类型注解
- **文档字符串**：使用 Google Style Docstrings
- **命名规范**：
  - 类名：PascalCase
  - 函数/变量：snake_case
  - 常量：UPPER_SNAKE_CASE

### 打包应用

```bash
# 使用 PyInstaller（推荐，稳定性更好）
python Pyinstall_build.py

# 使用 Nuitka
python Nuitka_build.py
```

### 添加新的文件预览支持

1. **创建预览器组件** 在 `components/` 目录创建新的预览器类：

```python
from PySide6.QtWidgets import QWidget

class NewFormatPreviewer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
  
    def init_ui(self):
        # 初始化 UI
        pass
  
    def set_file(self, file_info: dict):
        """设置要预览的文件"""
        file_path = file_info['path']
        # 实现文件加载逻辑
        pass
```

2. **注册文件类型** 在 `components/unified_previewer.py` 中注册：

```python
self.previewers = {
    # ... 现有预览器
    '.newext': NewFormatPreviewer,
}
```

3. **添加图标** 在 `icons/` 目录添加文件类型图标

---

## 贡献指南

我们欢迎所有形式的贡献！无论是 Bug 修复、新功能、文档改进还是问题反馈。

### 贡献流程

1. **Fork 仓库** - 点击右上角的 Fork 按钮
2. **克隆仓库** - `git clone https://github.com/your-username/FreeAssetFilter.git`
3. **创建分支** - `git checkout -b feature/AmazingFeature`
4. **提交更改** - `git commit -m 'Add some AmazingFeature'`
5. **推送分支** - `git push origin feature/AmazingFeature`
6. **创建 Pull Request** - 在 GitHub 上提交 PR

### 代码规范

- ✅ 遵循 PEP 8 代码风格
- ✅ 添加类型注解
- ✅ 编写清晰的提交信息
- ✅ 更新相关文档
- ✅ 添加必要的测试

### PR 提交流程

1. 确保代码通过所有测试
2. 更新 README.md 中的相关文档
3. 在 PR 描述中说明更改内容
4. 关联相关的 Issue（如有）
5. 等待代码审查

### Issue 提交规范

- **Bug 报告**：描述问题、复现步骤、期望行为、实际行为
- **功能请求**：描述功能、使用场景、预期效果
- **问题咨询**：提供详细的环境信息和操作步骤

---

## 路线图

### 已完成功能

- [X] 基础文件浏览和预览
- [X] 图像格式支持（30+ 格式）
- [X] 视频播放功能（基于 MPV）
- [X] 音频播放和波形显示
- [X] PDF 和 Office 文档预览
- [X] 压缩包浏览
- [X] 字体预览
- [X] 深色/浅色主题切换
- [X] 文件存储池功能
- [X] 缩略图缓存系统

### 正在进行

- [ ] 文件导出智能化分类
- [ ] 时间线等智能化筛选分类工具
- [ ] ISO文件稳定预览
- [ ] 插件系统架构

### 可能会实现的功能

- [ ] macOS 和 Linux 支持
- [ ] 网络文件系统支持（SMB/NFS）
- [ ] AI 智能标签和分类
- [ ] 协作和分享功能
- [ ] 移动端&网页端配套应用

### 长期愿景

成为开源社区最强大的文件预览和管理工具，为创意工作者提供高效的数字资产管理解决方案。

---

## 安全说明

### 依赖安全

- 所有依赖库均来自官方 PyPI 仓库
- 定期更新依赖以修复安全漏洞
- 使用 `pip-audit` 进行依赖安全检查

### 漏洞报告

如果您发现了安全漏洞，请不要在公开 Issue 中披露，请发送邮件至：

dorufoc@outlook.com

我们会在 48 小时内回复，并尽快修复漏洞。

---

## 许可证

本项目基于 [AGPL-3.0](LICENSE) 许可证开源。

```
FreeAssetFilter - 多功能文件预览与管理工具
Copyright (C) 2025 Dorufoc <qpdrfc123@gmail.com>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published
by the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.
```

---

## 致谢

### 核心依赖

感谢以下开源项目的贡献：

#### GUI 框架

- [Qt for Python (PySide6)](https://wiki.qt.io/Qt_for_Python) - 跨平台 GUI 框架

#### 图像处理

- [Pillow](https://python-pillow.org/) - Python 图像处理库
- [pillow-heif](https://github.com/bigcat88/pillow_heif) - HEIF/HEIC 格式支持
- [rawpy](https://github.com/letmaik/rawpy) - RAW 图像处理
- [psd-tools](https://github.com/psd-tools/psd-tools) - PSD 文件解析
- [OpenCV](https://opencv.org/) - 计算机视觉库
- [scikit-image](https://scikit-image.org/) - 图像处理算法库
- [imageio](https://imageio.readthedocs.io/) - 图像 I/O 库
- [tifffile](https://github.com/cgohlke/tifffile) - TIFF 文件处理
- [aggdraw](https://github.com/pytillers/aggdraw) - 抗锯齿图形绘制

#### 视频与音频

- [MPV](https://mpv.io/) - 高性能视频播放器
- [mutagen](https://mutagen.readthedocs.io/) - 音频元数据处理

#### 文档处理

- [PyMuPDF](https://github.com/pymupdf/PyMuPDF) - PDF 处理库
- [Pygments](https://pygments.org/) - 代码语法高亮
- [Markdown](https://python-markdown.github.io/) - Markdown 解析

#### 压缩包处理

- [rarfile](https://github.com/markokr/rarfile) - RAR 文件解压
- [py7zr](https://github.com/miurahr/py7zr) - 7Z 文件解压
- [pycdlib](https://github.com/clalancette/pycdlib) - ISO 文件处理
- [pycryptodomex](https://www.pycryptodome.org/) - 加密算法库

#### 科学计算

- [NumPy](https://numpy.org/) - 科学计算库
- [SciPy](https://scipy.org/) - 科学计算工具集
- [networkx](https://networkx.org/) - 图论算法库

#### 文本与编码

- [chardet](https://github.com/chardet/chardet) - 字符编码检测
- [ExifRead](https://github.com/ianare/exif-py) - EXIF 数据读取
- [texttable](https://github.com/bufordtaylor/python-texttable) - 文本表格生成

#### 系统与工具

- [psutil](https://github.com/giampaolo/psutil) - 系统信息获取
- [packaging](https://packaging.pypa.io/) - 版本解析工具

### 资源致谢

- 字体：使用 [Fira Code](https://github.com/tonsky/FiraCode) 作为代码字体
- 中文字体：使用庞门正道标题体

### 特别贡献者

感谢所有为项目做出贡献的开发者：

- [@Dorufoc](https://github.com/Dorufoc) - 项目创始人 & 核心开发者
- [@renmoren](https://github.com/renmoren) - 核心开发者

### 相关项目

- [mpv](https://github.com/mpv-player/mpv) - 命令行视频播放器
- [vscode-textmate](https://github.com/microsoft/vscode-textmate) - TextMate 语法解析库

---

<div align="center">

**⭐ 如果这个项目对您有帮助，请给我们一个 Star！**

[🐛 提交 Bug](https://github.com/Dorufoc/FreeAssetFilter/issues) • [💡 功能建议](https://github.com/Dorufoc/FreeAssetFilter/issues) • [🤝 参与贡献](https://github.com/Dorufoc/FreeAssetFilter/pulls)

Made with ❤️ by [Dorufoc](https://github.com/Dorufoc) & [renmoren](https://github.com/renmoren)

</div>
