#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
简单测试视频缩略图生成功能
"""

import os
import sys
import hashlib
import tempfile

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# 直接导入所需的模块
import cv2

def test_video_thumbnail():
    """
    测试视频缩略图生成功能
    """
    # 使用日志中看到的MP4文件作为测试
    test_file_path = r"E:1c8dbcbe4e800de42b755605b5c75924.mp4"
    
    if not os.path.exists(test_file_path):
        print(f"测试文件不存在: {test_file_path}")
        return
    
    print(f"开始测试视频缩略图生成: {test_file_path}")
    
    # 生成缩略图路径
    def get_thumbnail_path(file_path):
        """
        获取文件的缩略图路径
        """
        # 缩略图存储在临时目录
        thumb_dir = os.path.join(os.path.dirname(__file__), "data", "thumbnails")
        os.makedirs(thumb_dir, exist_ok=True)
        
        # 使用更简单的文件名格式，避免可能的问题
        file_name = os.path.basename(file_path)
        # 替换文件名中的特殊字符
        file_name = file_name.replace(' ', '_').replace('.', '_').replace(':', '_').replace('\\', '_').replace('/', '_')
        # 使用文件名前10个字符加上随机数作为文件名
        import random
        random_num = random.randint(1000, 9999)
        file_hash = f"{file_name[:10]}_{random_num}"
        
        return os.path.join(thumb_dir, f"{file_hash}.png")
    
    # 生成缩略图
    def create_thumbnail(file_path):
        """
        为单个文件创建缩略图
        """
        try:
            suffix = os.path.splitext(file_path)[1].lower()
            thumbnail_path = get_thumbnail_path(file_path)
            
            print(f"生成缩略图到: {thumbnail_path}")
            
            # 处理视频文件
            print(f"开始生成视频缩略图: {file_path}")
            cap = cv2.VideoCapture(file_path)
            if cap.isOpened():
                try:
                    # 获取视频总帧数
                    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                    print(f"视频总帧数: {total_frames}")
                    
                    # 计算有效的帧位置，确保不使用第0帧
                    min_valid_frame = 1  # 最小有效帧（不使用第0帧）
                    max_valid_frame = max(min_valid_frame, total_frames - 1) if total_frames > 1 else min_valid_frame
                    
                    # 优先使用中间帧
                    middle_frame = total_frames // 2
                    
                    # 定义尝试的帧位置列表
                    frame_positions = []
                    frame_positions.append(middle_frame)  # 中间帧
                    frame_positions.append(middle_frame - 10)  # 中间帧前10帧
                    frame_positions.append(middle_frame + 10)  # 中间帧后10帧
                    frame_positions.append(total_frames // 3)  # 1/3处
                    frame_positions.append(total_frames // 4)  # 1/4处
                    frame_positions.append(1)  # 第1帧
                    frame_positions.append(5)  # 第5帧
                    frame_positions.append(10)  # 第10帧
                    
                    # 过滤无效帧位置，确保只尝试有效的帧
                    valid_frame_positions = []
                    for pos in frame_positions:
                        # 确保帧位置在有效范围内
                        if pos >= min_valid_frame and pos <= max_valid_frame:
                            valid_frame_positions.append(pos)
                    
                    # 去重
                    valid_frame_positions = list(set(valid_frame_positions))
                    
                    # 优先使用中间帧，将中间帧放在列表开头
                    if middle_frame in valid_frame_positions:
                        # 移除中间帧并将其放在列表开头
                        valid_frame_positions.remove(middle_frame)
                        valid_frame_positions.insert(0, middle_frame)
                    
                    print(f"尝试的有效帧位置: {valid_frame_positions}")
                    
                    # 尝试从不同位置读取帧
                    success = False
                    for frame_pos in valid_frame_positions:
                        # 设置帧位置
                        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_pos)
                        
                        # 读取帧
                        ret, frame = cap.read()
                        if ret and frame is not None and frame.shape[0] > 0 and frame.shape[1] > 0:
                            # 调整大小为128x128
                            thumbnail = cv2.resize(frame, (128, 128), interpolation=cv2.INTER_AREA)
                            
                            # 尝试使用PIL库保存缩略图，这是一个更可靠的方法
                            try:
                                from PIL import Image
                                
                                # 将OpenCV图像转换为PIL图像
                                # OpenCV图像是BGR格式，需要转换为RGB格式
                                thumbnail_pil = Image.fromarray(cv2.cvtColor(thumbnail, cv2.COLOR_BGR2RGB))
                                
                                # 保存缩略图
                                thumbnail_pil.save(thumbnail_path, format='PNG', quality=85)
                                print(f"✓ 使用PIL保存缩略图成功")
                                print(f"✓ 已生成视频缩略图: {file_path}, 使用第 {frame_pos} 帧")
                                print(f"✓ 缩略图文件已保存到: {thumbnail_path}")
                                success = True
                            except Exception as pil_e:
                                print(f"✗ 使用PIL保存缩略图失败: {pil_e}")
                                
                                # 尝试使用cv2.imwrite()作为fallback
                                write_result = cv2.imwrite(thumbnail_path, thumbnail)
                                print(f"cv2.imwrite返回值: {write_result}")
                                if write_result:
                                    print(f"✓ 已生成视频缩略图: {file_path}, 使用第 {frame_pos} 帧")
                                    success = True
                                else:
                                    print(f"✗ cv2.imwrite也失败，无法保存缩略图")
                            break
                    
                    if not success:
                        print(f"✗ 无法读取视频任何有效帧")
                except Exception as e:
                    print(f"✗ 处理视频时出错: {e}")
                finally:
                    # 确保释放资源
                    cap.release()
            else:
                print(f"✗ 无法打开视频文件: {file_path}")
        except ImportError:
            # 如果没有安装OpenCV，跳过缩略图生成
            print("OpenCV is not installed")
        except Exception as e:
            # 处理其他可能的错误
            print(f"生成缩略图失败: {file_path}, 错误: {e}")
    
    # 调用create_thumbnail函数生成缩略图
    create_thumbnail(test_file_path)
    
    # 检查缩略图是否生成成功
    thumbnail_path = get_thumbnail_path(test_file_path)
    if os.path.exists(thumbnail_path):
        print(f"✓ 缩略图生成成功: {thumbnail_path}")
        print(f"  缩略图大小: {os.path.getsize(thumbnail_path)} bytes")
    else:
        print(f"✗ 缩略图生成失败")
        
        # 列出缩略图目录中的所有文件
        thumb_dir = os.path.join(os.path.dirname(__file__), "data", "thumbnails")
        if os.path.exists(thumb_dir):
            print(f"缩略图目录中的文件:")
            for f in os.listdir(thumb_dir):
                print(f"  - {f}")

if __name__ == "__main__":
    test_video_thumbnail()
