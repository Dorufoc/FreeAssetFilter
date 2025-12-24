#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Python集成示例：调用缩略图生成器

这个脚本展示了如何在Python中调用C++编写的缩略图生成器，
并解析其输出结果。
"""

import subprocess
import json
import tempfile
import os
import sys

def generate_thumbnails(
    input_dir, 
    max_width=256, 
    max_height=256, 
    threads=4, 
    quality=85,
    output_format="jpg",
    output_dir=None
):
    """
    调用缩略图生成器生成指定目录下所有图片的缩略图
    
    Args:
        input_dir (str): 输入目录路径，包含要处理的图片文件
        max_width (int): 缩略图的最大宽度（像素）
        max_height (int): 缩略图的最大高度（像素）
        threads (int): 并发处理线程数
        quality (int): 输出图片质量（0-100）
        output_format (str): 输出图片格式（jpg, png, webp等）
        output_dir (str, optional): 输出目录路径，默认为系统缓存目录
        
    Returns:
        list: 包含缩略图生成结果的字典列表，每个字典包含：
            - original_filename: 原始文件名
            - thumbnail_filename: 缩略图文件名
            - thumbnail_path: 缩略图完整路径
            - success: 处理是否成功（bool）
            - error_message: 错误信息（仅当success为False时）
    """
    
    # 确保输入目录存在
    if not os.path.exists(input_dir):
        raise ValueError(f"Input directory does not exist: {input_dir}")
    
    # 获取当前脚本所在目录，假设thumbnail_generator与该脚本在同一目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 构建缩略图生成器的路径
    generator_path = None
    
    if sys.platform == "win32":
        # 首先检查MinGW-w64构建路径
        mingw_path = os.path.join(script_dir, "build", "thumbnail_generator.exe")
        if os.path.exists(mingw_path):
            generator_path = mingw_path
        else:
            # 然后检查Visual Studio构建路径
            vs_path = os.path.join(script_dir, "build", "Release", "thumbnail_generator.exe")
            if os.path.exists(vs_path):
                generator_path = vs_path
            else:
                # 两个路径都不存在，抛出错误
                raise FileNotFoundError(
                    f"Thumbnail generator not found at either {mingw_path} or {vs_path}. "
                    f"Please build the project first using build.sh, build.bat, or build.ps1.")
    else:
        # Linux/macOS路径
        generator_path = os.path.join(script_dir, "build", "thumbnail_generator")
        if not os.path.exists(generator_path):
            raise FileNotFoundError(
                f"Thumbnail generator not found at {generator_path}. "
                f"Please build the project first using build.sh.")
    
    # 构建命令行参数
    cmd = [
        generator_path,
        "--input", input_dir,
        "--max-width", str(max_width),
        "--max-height", str(max_height),
        "--threads", str(threads),
        "--quality", str(quality),
        "--format", output_format,
        "--return-format", "json"
    ]
    
    # 如果指定了输出目录，添加到命令中
    if output_dir:
        cmd.extend(["--output", output_dir])
    
    try:
        # 执行命令
        print(f"执行命令: {' '.join(cmd)}")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True  # 如果命令返回非零退出码，将抛出CalledProcessError
        )
        
        # 解析JSON结果
        output_data = json.loads(result.stdout)
        
        # 返回结果列表
        return output_data.get("results", [])
        
    except subprocess.CalledProcessError as e:
        # 命令执行失败
        print(f"命令执行失败，退出码: {e.returncode}")
        print(f"错误输出: {e.stderr}")
        raise RuntimeError(f"Thumbnail generation failed: {e.stderr}") from e
        
    except json.JSONDecodeError as e:
        # JSON解析失败
        print(f"无法解析输出结果: {e}")
        print(f"原始输出: {result.stdout}")
        raise RuntimeError(f"Failed to parse JSON result: {e}") from e
        
    except Exception as e:
        # 其他异常
        print(f"发生未知错误: {e}")
        raise


def main():
    """
    示例主函数
    """
    print("=== 缩略图生成器Python集成示例 ===")
    
    # 示例输入目录（需要替换为实际存在的目录）
    input_dir = "./test_images"  # 请替换为实际的图片目录
    
    # 检查输入目录是否存在
    if not os.path.exists(input_dir):
        print(f"错误：输入目录不存在: {input_dir}")
        print("请创建一个包含图片的目录，并修改脚本中的input_dir变量")
        print("例如：input_dir = 'path/to/your/images'")
        sys.exit(1)
    
    # 使用临时目录作为输出目录
    output_dir = tempfile.mkdtemp(prefix="thumbnails_")
    print(f"使用临时输出目录: {output_dir}")
    
    try:
        # 调用缩略图生成函数
        results = generate_thumbnails(
            input_dir=input_dir,
            max_width=512,
            max_height=512,
            threads=8,
            quality=85,
            output_format="jpg",
            output_dir=output_dir
        )
        
        # 打印结果统计
        total = len(results)
        success = sum(1 for r in results if r["success"])
        failed = total - success
        
        print(f"\n处理完成：")
        print(f"  总文件数: {total}")
        print(f"  成功: {success}")
        print(f"  失败: {failed}")
        
        # 打印详细结果
        print(f"\n详细结果：")
        for result in results:
            status = "✓ 成功" if result["success"] else "✗ 失败"
            print(f"  {result['original_filename']} -> {status}")
            if not result["success"]:
                print(f"    错误原因: {result['error_message']}")
            else:
                print(f"    缩略图: {result['thumbnail_filename']}")
        
        print(f"\n所有缩略图已保存到: {output_dir}")
        
    except Exception as e:
        print(f"\n执行失败: {e}")
        sys.exit(1)
    
    finally:
        # 询问是否删除临时目录
        cleanup = input(f"\n是否删除临时目录 {output_dir}？(y/n): ").strip().lower()
        if cleanup == 'y':
            try:
                import shutil
                shutil.rmtree(output_dir)
                print(f"临时目录已删除: {output_dir}")
            except Exception as e:
                print(f"删除临时目录失败: {e}")


if __name__ == "__main__":
    main()
