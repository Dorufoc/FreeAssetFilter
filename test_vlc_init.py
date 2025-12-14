#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单测试VLC库初始化
只检查VLC库是否能够成功加载和初始化
"""

import os
import sys
import ctypes

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 直接使用项目内置的libvlc.dll
vlc_core_path = os.path.join(os.path.dirname(__file__), 'freeassetfilter', 'core')
libvlc_path = os.path.join(vlc_core_path, 'libvlc.dll')

print(f"[测试] 项目根目录: {os.path.dirname(os.path.abspath(__file__))}")
print(f"[测试] VLC核心目录: {vlc_core_path}")
print(f"[测试] libvlc.dll路径: {libvlc_path}")

# 检查内置的libvlc.dll是否存在
if not os.path.exists(libvlc_path):
    print(f"[测试] 错误: 找不到内置的libvlc.dll文件")
    sys.exit(1)

print(f"[测试] 找到libvlc.dll文件: {libvlc_path}")

# 检查其他必要的VLC文件
required_files = ['libvlccore.dll', 'axvlc.dll', 'npvlc.dll']
for file in required_files:
    file_path = os.path.join(vlc_core_path, file)
    if os.path.exists(file_path):
        print(f"[测试] 找到必要文件: {file}")
    else:
        print(f"[测试] 警告: 找不到必要文件: {file}")

# 修改系统PATH，确保VLC依赖的DLL能被找到
print(f"[测试] 原始PATH长度: {len(os.environ['PATH'])}")
os.environ['PATH'] = vlc_core_path + ';' + os.environ['PATH']
print(f"[测试] 修改后PATH长度: {len(os.environ['PATH'])}")

# 尝试加载libvlccore.dll和libvlc.dll
try:
    print("[测试] 尝试加载libvlccore.dll...")
    libvlccore = ctypes.CDLL(os.path.join(vlc_core_path, 'libvlccore.dll'))
    print("[测试] libvlccore.dll加载成功")
    
    print("[测试] 尝试加载libvlc.dll...")
    libvlc = ctypes.CDLL(libvlc_path)
    print("[测试] libvlc.dll加载成功")
except Exception as e:
    print(f"[测试] 错误: 无法加载VLC DLL - {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 尝试导入vlc模块
try:
    print("[测试] 尝试导入vlc模块...")
    import vlc
    print(f"[测试] vlc模块导入成功，版本: {vlc.__version__}")
except Exception as e:
    print(f"[测试] 错误: 无法导入vlc模块 - {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 尝试创建VLC实例
try:
    print("[测试] 尝试创建VLC实例...")
    instance = vlc.Instance()
    if instance:
        print("[测试] VLC实例创建成功")
    else:
        print("[测试] 错误: VLC实例创建失败，返回None")
        sys.exit(1)
    
    # 尝试创建媒体播放器
    print("[测试] 尝试创建媒体播放器...")
    player = instance.media_player_new()
    if player:
        print("[测试] 媒体播放器创建成功")
    else:
        print("[测试] 错误: 媒体播放器创建失败，返回None")
        sys.exit(1)
    
    print("[测试] 所有测试通过！VLC库初始化成功")
except Exception as e:
    print(f"[测试] 错误: VLC初始化失败 - {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
