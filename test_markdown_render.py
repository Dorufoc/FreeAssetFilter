#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试 Markdown 渲染输出"""

import markdown

# 测试内容
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

# 渲染 Markdown
md = markdown.Markdown(
    extensions=['fenced_code', 'codehilite', 'tables', 'nl2br'],
    extension_configs={
        'codehilite': {'noclasses': True, 'guess_lang': False}
    }
)
html = md.convert(test_content)

print("=== 原始 HTML 输出 ===")
print(html)
print("\n=== 格式化后的 HTML ===")
# 添加换行便于阅读
import re
formatted = re.sub(r'(<[^>]+>)', r'\n\1', html)
print(formatted)
