#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试 Markdown 渲染 - 逐步排除扩展"""

import markdown

# 原始 Markdown 内容（带空行）
test_content = """### 性能优化

1. **多线程并发处理**
   - 自动检测CPU核心数
   - 可配置线程数量（1-8线程）
   - 线程池管理和任务调度

2. **视频解码优化**
   - 每线程独立mpv实例
   - 避免重复创建/销毁开销
   - 线程安全的资源管理

3. **内存管理**
   - 流式处理大文件
   - 自动内存释放
   - 异常安全的资源清理
"""

print("=== 测试 1: 无任何扩展 ===")
md1 = markdown.Markdown()
html1 = md1.convert(test_content)
print(html1)

print("\n=== 测试 2: 仅 tables ===")
md2 = markdown.Markdown(extensions=['tables'])
html2 = md2.convert(test_content)
print(html2)

print("\n=== 测试 3: fenced_code + tables ===")
md3 = markdown.Markdown(extensions=['fenced_code', 'tables'])
html3 = md3.convert(test_content)
print(html3)

print("\n=== 测试 4: 使用 sane_lists 扩展 ===")
try:
    md4 = markdown.Markdown(extensions=['sane_lists'])
    html4 = md4.convert(test_content)
    print(html4)
except Exception as e:
    print(f"sane_lists 扩展不可用: {e}")
