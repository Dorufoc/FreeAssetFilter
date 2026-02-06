#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试 Markdown 渲染修复"""

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

print("=== 原始 Markdown ===")
print(test_content)
print("\n" + "="*50)

# 旧的渲染方式（带 nl2br）
md_old = markdown.Markdown(
    extensions=['fenced_code', 'codehilite', 'tables', 'nl2br'],
    extension_configs={
        'codehilite': {'noclasses': True, 'guess_lang': False}
    }
)
html_old = md_old.convert(test_content)

print("\n=== 旧方式渲染 (带 nl2br) ===")
print(html_old)

# 新的渲染方式（不带 nl2br）
md_new = markdown.Markdown(
    extensions=['fenced_code', 'codehilite', 'tables'],
    extension_configs={
        'codehilite': {'noclasses': True, 'guess_lang': False}
    }
)
html_new = md_new.convert(test_content)

print("\n=== 新方式渲染 (无 nl2br) ===")
print(html_new)

# 检查列表项数量
import re
old_list_items = len(re.findall(r'<li[^>]*>', html_old))
new_list_items = len(re.findall(r'<li[^>]*>', html_new))

print(f"\n旧方式列表项数: {old_list_items}")
print(f"新方式列表项数: {new_list_items}")

if new_list_items < old_list_items:
    print("✓ 修复成功：列表结构更合理")
else:
    print("需要进一步检查")
