#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

LUT工具模块
提供CUBE格式LUT文件的解析、验证和管理功能
"""

import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any
from dataclasses import dataclass


@dataclass
class LUTInfo:
    """LUT信息数据类"""
    id: str
    name: str
    path: str
    preview_path: str
    size: int  # LUT尺寸 (如 33 表示 33x33x33)
    is_3d: bool  # 是否为3D LUT


class CubeLUTParser:
    """
    CUBE格式LUT文件解析器
    支持1D和3D LUT解析
    """
    
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.title = ""
        self.lut_size = 0
        self.is_3d = True
        self.data = []
        
    def parse(self) -> bool:
        """
        解析CUBE文件
        
        Returns:
            bool: 解析是否成功
        """
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            # 解析头部信息
            data_start = 0
            for i, line in enumerate(lines):
                line = line.strip()
                
                # 跳过空行和注释
                if not line or line.startswith('#'):
                    continue
                
                # 解析TITLE
                if line.startswith('TITLE'):
                    match = re.search(r'"([^"]*)"', line)
                    if match:
                        self.title = match.group(1)
                    continue
                
                # 解析LUT大小
                if line.startswith('LUT_3D_SIZE'):
                    self.is_3d = True
                    self.lut_size = int(line.split()[-1])
                    continue
                elif line.startswith('LUT_1D_SIZE'):
                    self.is_3d = False
                    self.lut_size = int(line.split()[-1])
                    continue
                
                # 解析数据
                if self._is_data_line(line):
                    data_start = i
                    break
            
            # 解析数据部分
            self.data = []
            for line in lines[data_start:]:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                values = line.split()
                if len(values) >= 3:
                    try:
                        r, g, b = float(values[0]), float(values[1]), float(values[2])
                        self.data.append((r, g, b))
                    except ValueError:
                        continue
            
            # 验证数据完整性
            expected_size = self.lut_size ** (3 if self.is_3d else 1)
            if len(self.data) < expected_size:
                return False
            
            return True
            
        except Exception as e:
            print(f"解析LUT文件失败: {e}")
            return False
    
    def _is_data_line(self, line: str) -> bool:
        """检查是否为数据行"""
        # 数据行应该是三个数字
        parts = line.split()
        if len(parts) >= 3:
            try:
                float(parts[0])
                float(parts[1])
                float(parts[2])
                return True
            except ValueError:
                return False
        return False
    
    def get_info(self) -> Dict[str, Any]:
        """获取LUT信息"""
        return {
            'title': self.title,
            'size': self.lut_size,
            'is_3d': self.is_3d,
            'data_count': len(self.data)
        }
    
    def apply_to_pixel(self, r: float, g: float, b: float) -> Tuple[float, float, float]:
        """
        将LUT应用到单个像素
        
        Args:
            r, g, b: 输入RGB值 (0-1范围)
            
        Returns:
            Tuple[float, float, float]: 输出RGB值
        """
        if not self.data:
            return r, g, b
        
        if self.is_3d:
            return self._apply_3d_lut(r, g, b)
        else:
            return self._apply_1d_lut(r, g, b)
    
    def _apply_3d_lut(self, r: float, g: float, b: float) -> Tuple[float, float, float]:
        """应用3D LUT"""
        size = self.lut_size
        
        # 将输入值映射到LUT坐标
        r = max(0, min(1, r)) * (size - 1)
        g = max(0, min(1, g)) * (size - 1)
        b = max(0, min(1, b)) * (size - 1)
        
        # 三线性插值
        r0, g0, b0 = int(r), int(g), int(b)
        r1, g1, b1 = min(r0 + 1, size - 1), min(g0 + 1, size - 1), min(b0 + 1, size - 1)
        
        fr, fg, fb = r - r0, g - g0, b - b0
        
        # 获取8个相邻点
        def get_lut_value(x, y, z):
            idx = (z * size + y) * size + x
            if idx < len(self.data):
                return self.data[idx]
            return (0, 0, 0)
        
        c000 = get_lut_value(r0, g0, b0)
        c001 = get_lut_value(r0, g0, b1)
        c010 = get_lut_value(r0, g1, b0)
        c011 = get_lut_value(r0, g1, b1)
        c100 = get_lut_value(r1, g0, b0)
        c101 = get_lut_value(r1, g0, b1)
        c110 = get_lut_value(r1, g1, b0)
        c111 = get_lut_value(r1, g1, b1)
        
        # 三线性插值计算
        out_r = (
            c000[0] * (1 - fr) * (1 - fg) * (1 - fb) +
            c001[0] * (1 - fr) * (1 - fg) * fb +
            c010[0] * (1 - fr) * fg * (1 - fb) +
            c011[0] * (1 - fr) * fg * fb +
            c100[0] * fr * (1 - fg) * (1 - fb) +
            c101[0] * fr * (1 - fg) * fb +
            c110[0] * fr * fg * (1 - fb) +
            c111[0] * fr * fg * fb
        )
        
        out_g = (
            c000[1] * (1 - fr) * (1 - fg) * (1 - fb) +
            c001[1] * (1 - fr) * (1 - fg) * fb +
            c010[1] * (1 - fr) * fg * (1 - fb) +
            c011[1] * (1 - fr) * fg * fb +
            c100[1] * fr * (1 - fg) * (1 - fb) +
            c101[1] * fr * (1 - fg) * fb +
            c110[1] * fr * fg * (1 - fb) +
            c111[1] * fr * fg * fb
        )
        
        out_b = (
            c000[2] * (1 - fr) * (1 - fg) * (1 - fb) +
            c001[2] * (1 - fr) * (1 - fg) * fb +
            c010[2] * (1 - fr) * fg * (1 - fb) +
            c011[2] * (1 - fr) * fg * fb +
            c100[2] * fr * (1 - fg) * (1 - fb) +
            c101[2] * fr * (1 - fg) * fb +
            c110[2] * fr * fg * (1 - fb) +
            c111[2] * fr * fg * fb
        )
        
        return out_r, out_g, out_b
    
    def _apply_1d_lut(self, r: float, g: float, b: float) -> Tuple[float, float, float]:
        """应用1D LUT"""
        size = self.lut_size
        
        def interpolate(channel_value: float, offset: int) -> float:
            idx = channel_value * (size - 1)
            idx0 = int(idx)
            idx1 = min(idx0 + 1, size - 1)
            t = idx - idx0
            
            if idx0 + offset < len(self.data):
                v0 = self.data[idx0 + offset][0]
            else:
                v0 = channel_value
            
            if idx1 + offset < len(self.data):
                v1 = self.data[idx1 + offset][0]
            else:
                v1 = channel_value
            
            return v0 * (1 - t) + v1 * t
        
        out_r = interpolate(r, 0)
        out_g = interpolate(g, size)
        out_b = interpolate(b, size * 2)
        
        return out_r, out_g, out_b


def validate_lut_file(file_path: str) -> Tuple[bool, str]:
    """
    验证LUT文件是否有效
    
    Args:
        file_path: LUT文件路径
        
    Returns:
        Tuple[bool, str]: (是否有效, 错误信息)
    """
    # 检查文件是否存在
    if not os.path.exists(file_path):
        return False, "文件不存在"
    
    # 检查文件扩展名
    if not file_path.lower().endswith('.cube'):
        return False, "文件格式错误，仅支持.cube格式"
    
    # 检查文件大小
    file_size = os.path.getsize(file_path)
    if file_size == 0:
        return False, "文件为空"
    
    if file_size > 100 * 1024 * 1024:  # 100MB
        return False, "文件过大"
    
    # 尝试解析文件
    parser = CubeLUTParser(file_path)
    if not parser.parse():
        return False, "LUT文件解析失败，文件可能已损坏"
    
    info = parser.get_info()
    if info['size'] == 0:
        return False, "LUT大小无效"
    
    return True, ""


def get_lut_storage_dir() -> str:
    """获取LUT存储目录"""
    base_dir = Path(__file__).parent.parent.parent
    lut_dir = base_dir / "data" / "luts"
    lut_dir.mkdir(parents=True, exist_ok=True)
    return str(lut_dir)


def get_lut_preview_dir() -> str:
    """获取LUT预览图存储目录"""
    base_dir = Path(__file__).parent.parent.parent
    preview_dir = base_dir / "data" / "lut_previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    return str(preview_dir)


def copy_lut_file(source_path: str, lut_id: Optional[str] = None) -> Tuple[bool, str]:
    """
    复制LUT文件到应用数据目录
    
    Args:
        source_path: 源文件路径
        lut_id: LUT唯一标识，如不提供则自动生成
        
    Returns:
        Tuple[bool, str]: (是否成功, 目标路径或错误信息)
    """
    try:
        # 验证文件
        is_valid, error_msg = validate_lut_file(source_path)
        if not is_valid:
            return False, error_msg
        
        # 生成LUT ID
        if lut_id is None:
            lut_id = str(uuid.uuid4())
        
        # 获取存储目录
        lut_dir = get_lut_storage_dir()
        
        # 生成目标文件名
        original_name = Path(source_path).stem
        target_name = f"{lut_id}_{original_name}.cube"
        target_path = os.path.join(lut_dir, target_name)
        
        # 复制文件
        shutil.copy2(source_path, target_path)
        
        return True, target_path
        
    except Exception as e:
        return False, f"复制文件失败: {str(e)}"


def remove_lut_file(file_path: str) -> bool:
    """
    删除LUT文件
    
    Args:
        file_path: LUT文件路径
        
    Returns:
        bool: 是否成功
    """
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
        return True
    except Exception as e:
        print(f"删除LUT文件失败: {e}")
        return False


def get_lut_display_name(file_path: str) -> str:
    """
    从LUT文件路径获取显示名称
    
    Args:
        file_path: LUT文件路径
        
    Returns:
        str: 显示名称
    """
    try:
        # 尝试从文件名解析
        file_name = Path(file_path).stem
        
        # 如果文件名包含UUID前缀，移除它
        parts = file_name.split('_', 1)
        if len(parts) > 1 and len(parts[0]) == 36:  # UUID长度为36
            return parts[1]
        
        return file_name
    except:
        return "Unknown LUT"


def load_lut_from_settings(settings_manager) -> List[LUTInfo]:
    """
    从设置加载LUT列表
    
    Args:
        settings_manager: 设置管理器实例
        
    Returns:
        List[LUTInfo]: LUT信息列表
    """
    lut_files = settings_manager.get_setting("video.lut_files", [])
    lut_list = []
    
    for lut_data in lut_files:
        try:
            lut_info = LUTInfo(
                id=lut_data.get('id', ''),
                name=lut_data.get('name', ''),
                path=lut_data.get('path', ''),
                preview_path=lut_data.get('preview_path', ''),
                size=lut_data.get('size', 0),
                is_3d=lut_data.get('is_3d', True)
            )
            lut_list.append(lut_info)
        except Exception as e:
            print(f"加载LUT信息失败: {e}")
            continue
    
    return lut_list


def save_lut_to_settings(settings_manager, lut_info: LUTInfo):
    """
    保存LUT信息到设置
    
    Args:
        settings_manager: 设置管理器实例
        lut_info: LUT信息
    """
    lut_files = settings_manager.get_setting("video.lut_files", [])
    
    # 检查是否已存在
    for i, lut_data in enumerate(lut_files):
        if lut_data.get('id') == lut_info.id:
            # 更新现有项
            lut_files[i] = {
                'id': lut_info.id,
                'name': lut_info.name,
                'path': lut_info.path,
                'preview_path': lut_info.preview_path,
                'size': lut_info.size,
                'is_3d': lut_info.is_3d
            }
            break
    else:
        # 添加新项
        lut_files.append({
            'id': lut_info.id,
            'name': lut_info.name,
            'path': lut_info.path,
            'preview_path': lut_info.preview_path,
            'size': lut_info.size,
            'is_3d': lut_info.is_3d
        })
    
    settings_manager.set_setting("video.lut_files", lut_files)
    settings_manager.save_settings()


def remove_lut_from_settings(settings_manager, lut_id: str):
    """
    从设置中移除LUT
    
    Args:
        settings_manager: 设置管理器实例
        lut_id: LUT ID
    """
    lut_files = settings_manager.get_setting("video.lut_files", [])
    lut_files = [lut for lut in lut_files if lut.get('id') != lut_id]
    settings_manager.set_setting("video.lut_files", lut_files)
    
    # 如果删除的是当前激活的LUT，清除激活状态
    active_id = settings_manager.get_setting("video.active_lut_id", None)
    if active_id == lut_id:
        settings_manager.set_setting("video.active_lut_id", None)
    
    settings_manager.save_settings()
