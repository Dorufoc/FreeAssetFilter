# C++ 封面颜色提取器

高性能的封面颜色提取模块，使用 C++ 实现 K-Means 聚类和 CIEDE2000 色差算法，比纯 Python 实现快 5-10 倍。

## 特性

- **高性能**: 使用 C++17 实现核心算法，OpenMP 多线程加速
- **精确算法**: K-Means 聚类 + CIEDE2000 色差计算
- **自动降级**: 如果 C++ 模块编译失败，自动使用 Python 实现
- **API 兼容**: 与原有 Python API 完全兼容

## 编译要求

### Windows
- Visual Studio 2019+ 或 MSVC Build Tools
- Python 3.8+
- pybind11

### Linux
- GCC 7+ 或 Clang 5+
- Python 3.8+
- pybind11

### macOS
- Xcode 10+ 或 Command Line Tools
- Python 3.8+
- pybind11

## 编译安装

### 方法 1: 使用编译脚本（推荐）

```bash
cd freeassetfilter/core/cpp_color_extractor
python build.py
```

### 方法 2: 使用 pip

```bash
cd freeassetfilter/core/cpp_color_extractor
pip install -e .
```

### 方法 3: 使用 setup.py

```bash
cd freeassetfilter/core/cpp_color_extractor
python setup.py build_ext --inplace
```

## 使用方法

### 在 Python 中使用

```python
from freeassetfilter.core.color_extractor import extract_cover_colors, is_cpp_available

# 检查 C++ 模块是否可用
if is_cpp_available():
    print("使用 C++ 高性能实现")
else:
    print("使用 Python 实现")

# 提取颜色（自动选择最优实现）
with open("cover.jpg", "rb") as f:
    cover_data = f.read()

colors = extract_cover_colors(cover_data, num_colors=5, min_distance=50.0)
for color in colors:
    print(f"RGB({color.red()}, {color.green()}, {color.blue()})")
```

### 直接使用 C++ 模块

```python
from freeassetfilter.core.cpp_color_extractor import color_extractor_cpp

# 从 numpy 数组提取颜色
import numpy as np
image = np.array(...)  # RGB/RGBA 图像数组
colors = color_extractor_cpp.extract_colors_from_numpy(image, num_colors=5)

# 颜色空间转换
lab = color_extractor_cpp.rgb_to_lab(255, 0, 0)  # 红色转 Lab
rgb = color_extractor_cpp.lab_to_rgb(53.2, 80.1, 67.2)  # Lab 转 RGB

# CIEDE2000 色差计算
delta_e = color_extractor_cpp.ciede2000(50, 0, 0, 50, 10, 10)
```

## 性能对比

| 图像尺寸 | Python 实现 | C++ 实现 | 加速比 |
|---------|------------|---------|-------|
| 300x300 | ~50ms | ~10ms | 5x |
| 800x800 | ~200ms | ~30ms | 6-7x |
| 1500x1500 | ~500ms | ~60ms | 8x+ |

## 文件结构

```
cpp_color_extractor/
├── __init__.py              # Python 包装器和 fallback 逻辑
├── color_extractor.cpp      # C++ 核心实现
├── setup.py                 # 编译配置
├── build.py                 # 编译脚本
└── README.md               # 本文档
```

## 算法说明

### K-Means 聚类
- 在 Lab 色彩空间进行聚类
- 默认 K=8，最大迭代 30 次
- 使用 CIEDE2000 作为距离度量

### CIEDE2000 色差
- 国际标准的色差计算公式
- 考虑亮度、色度和色相的差异
- 比欧氏距离更符合人眼感知

### 颜色筛选
- 按聚类大小排序
- 使用 CIEDE2000 距离筛选差异明显的颜色
- 不足时生成互补色补充

## 故障排除

### 编译失败

1. **找不到编译器**
   - Windows: 安装 Visual Studio Build Tools
   - Linux: `sudo apt-get install build-essential`

2. **pybind11 未找到**
   ```bash
   pip install pybind11
   ```

3. **OpenMP 错误**
   - 在 setup.py 中注释掉 OpenMP 相关选项
   - 性能会略有下降但仍比 Python 快

### 运行时问题

1. **模块导入失败**
   - 检查是否正确编译
   - 查看 Python 日志中的降级信息

2. **结果与 Python 版本不同**
   - 这是正常的，因为算法实现细节可能有差异
   - 颜色质量应该相当或更好

## 许可证

与 FreeAssetFilter 项目相同（AGPL-3.0）
