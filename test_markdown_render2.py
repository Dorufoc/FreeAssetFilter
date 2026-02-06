#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试 Markdown 渲染输出 - 使用原始文件"""

import markdown

# 读取原始文件
with open(r'E:\Temps\Desktop\code\thumbnail_generator\COMPLETE_IMPLEMENTATION_REPORT.md', 'r', encoding='utf-8') as f:
    content = f.read()

# 提取性能优化部分
start = content.find('### 性能优化')
end = content.find('### 助老适配特性')
section = content[start:end]

print("=== 原始 Markdown 内容 ===")
print(section)
print("\n" + "="*50)

# 渲染 Markdown - 不使用 nl2br
md = markdown.Markdown(
    extensions=['fenced_code', 'codehilite', 'tables'],
    extension_configs={
        'codehilite': {'noclasses': True, 'guess_lang': False}
    }
)
html = md.convert(section)

print("\n=== 渲染后的 HTML (无 nl2br) ===")
print(html)

# 渲染 Markdown - 使用 nl2br
md2 = markdown.Markdown(
    extensions=['fenced_code', 'codehilite', 'tables', 'nl2br'],
    extension_configs={
        'codehilite': {'noclasses': True, 'guess_lang': False}
    }
)
html2 = md2.convert(section)

print("\n=== 渲染后的 HTML (有 nl2br) ===")
print(html2)
