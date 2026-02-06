#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试颜色处理是否破坏 HTML 结构"""

import re

def _is_grayscale(r, g, b):
    """判断颜色是否为灰度"""
    max_val = max(r, g, b)
    min_val = min(r, g, b)
    return (max_val - min_val) < 15

def _invert_grayscale(r, g, b):
    """反转灰度颜色"""
    return 255 - r, 255 - g, 255 - b

def _adjust_brightness(r, g, b):
    """调整彩色亮度"""
    import colorsys
    h, l, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
    new_l = 1.0 - l
    new_r, new_g, new_b = colorsys.hls_to_rgb(h, new_l, s)
    return int(new_r * 255), int(new_g * 255), int(new_b * 255)

def _invert_color(hex_color):
    """反转颜色"""
    if not hex_color or not hex_color.startswith('#') or len(hex_color) != 7:
        return hex_color
    
    try:
        r = int(hex_color[1:3], 16)
        g = int(hex_color[3:5], 16)
        b = int(hex_color[5:7], 16)
        
        if _is_grayscale(r, g, b):
            r, g, b = _invert_grayscale(r, g, b)
        else:
            r, g, b = _adjust_brightness(r, g, b)
        
        return f'#{r:02x}{g:02x}{b:02x}'
    except (ValueError, IndexError):
        return hex_color

def _process_html_colors(html, is_dark):
    """处理HTML中的颜色值"""
    if not is_dark:
        return html
    
    color_pattern = re.compile(r'color:\s*(#[0-9A-Fa-f]{6})')
    
    def replace_color(match):
        return f'color: {_invert_color(match.group(1))}'
    
    html = color_pattern.sub(replace_color, html)
    
    background_pattern = re.compile(r'background(-color)?:\s*(#[0-9A-Fa-f]{6})')
    
    def replace_bg(match):
        return f'background-color: {_invert_color(match.group(2))}'
    
    html = background_pattern.sub(replace_bg, html)
    
    border_color_pattern = re.compile(r'border(-color)?:\s*(#[0-9A-Fa-f]{6})')
    
    def replace_border(match):
        return f'border-color: {_invert_color(match.group(2))}'
    
    html = border_color_pattern.sub(replace_border, html)
    
    return html

# 测试 HTML
test_html = """<h3>性能优化</h3>
<ol>
<li><strong>多线程并发处理</strong></li>
<li>自动检测CPU核心数</li>
<li>可配置线程数量（1-8线程）</li>
<li>
<p>线程池管理和任务调度</p>
</li>
<li>
<p><strong>视频解码优化</strong></p>
</li>
</ol>"""

print("=== 原始 HTML ===")
print(test_html)

processed = _process_html_colors(test_html, True)

print("\n=== 处理后 HTML ===")
print(processed)

# 检查结构是否保持
import re

# 检查标签是否完整
original_tags = re.findall(r'<[^>]+>', test_html)
processed_tags = re.findall(r'<[^>]+>', processed)

print(f"\n原始标签数: {len(original_tags)}")
print(f"处理后标签数: {len(processed_tags)}")

if original_tags == processed_tags:
    print("✓ HTML 标签结构保持完整")
else:
    print("✗ HTML 标签结构被破坏")
    print("\n原始标签:", original_tags[:10])
    print("处理后标签:", processed_tags[:10])
