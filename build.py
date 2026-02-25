#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter Nuitka 编译脚本

使用MinGW编译器将FreeAssetFilter打包为Windows可执行程序

使用方法:
    python build.py
    python build.py --clean  # 清理后重新编译
    python build.py --skip-build  # 仅执行清理和验证

环境要求:
    - Python 3.9+
    - Nuitka (pip install nuitka)
    - MinGW64 (C:\mingw64)
"""

import os
import sys
import shutil
import subprocess
import argparse
import glob
from pathlib import Path
from typing import List, Dict, Set, Tuple

# 配置
PROJECT_NAME = "FreeAssetFilter"
ENTRY_POINT = "freeassetfilter/app/main.py"
OUTPUT_DIR = "build/nuitka"
# 使用MSVC编译器（Windows上Nuitka默认使用MSVC）
USE_MSVC = True
# UPX压缩选项
USE_UPX = True
UPX_PATH = r"C:\upx\upx.exe"  # UPX可执行文件路径

# Qt6 DLL白名单（必须保留）
QT6_KEEP_DLLS = {
    "Qt6Core.dll",
    "Qt6Gui.dll",
    "Qt6Widgets.dll",
    "Qt6Svg.dll",
    "Qt6SvgWidgets.dll",
    "Qt6Network.dll",
    "Qt6WebEngineCore.dll",
    "Qt6WebEngineWidgets.dll",
    "Qt6WebChannel.dll",
    "Qt6Qml.dll",
    "Qt6Quick.dll",
    "Qt6QuickWidgets.dll",
    "Qt6OpenGL.dll",
    "Qt6OpenGLWidgets.dll",
    "Qt6Multimedia.dll",
    "Qt6MultimediaWidgets.dll",
    "Qt6Pdf.dll",
    "Qt6PdfWidgets.dll",
    "Qt6PrintSupport.dll",
    "Qt6DBus.dll",
    "Qt6Xml.dll",
}

# Qt6 DLL黑名单（可以排除）
QT6_REMOVE_DLLS = {
    "Qt6Bluetooth.dll",
    "Qt6Charts.dll",
    "Qt6ChartsQml.dll",
    "Qt6DataVisualization.dll",
    "Qt6DataVisualizationQml.dll",
    "Qt6Graphs.dll",
    "Qt6GraphsWidgets.dll",
    "Qt6HttpServer.dll",
    "Qt6Location.dll",
    "Qt6Nfc.dll",
    "Qt6NetworkAuth.dll",
    "Qt6Positioning.dll",
    "Qt6PositioningQuick.dll",
    "Qt6RemoteObjects.dll",
    "Qt6RemoteObjectsQml.dll",
    "Qt6Scxml.dll",
    "Qt6ScxmlQml.dll",
    "Qt6Sensors.dll",
    "Qt6SensorsQuick.dll",
    "Qt6SerialBus.dll",
    "Qt6SerialPort.dll",
    "Qt6ShaderTools.dll",
    "Qt6SpatialAudio.dll",
    "Qt6StateMachine.dll",
    "Qt6StateMachineQml.dll",
    "Qt6TextToSpeech.dll",
    "Qt6WebSockets.dll",
    "Qt6WebView.dll",
    "Qt6WebViewQuick.dll",
    "Qt6Test.dll",
    "Qt6Sql.dll",
    "Qt6Help.dll",
    "Qt6Designer.dll",
    "Qt6DesignerComponents.dll",
    "Qt6UiTools.dll",
    "Qt6Concurrent.dll",
    "Qt6AxContainer.dll",
}

# Quick3D相关DLL（通配匹配）
QT6_QUICK3D_PATTERNS = ["Qt6Quick3D", "Qt63D"]


def print_header(text: str):
    """打印标题"""
    print("\n" + "=" * 60)
    print(f"  {text}")
    print("=" * 60)


def print_info(text: str):
    """打印信息"""
    print(f"[INFO] {text}")


def print_warning(text: str):
    """打印警告"""
    print(f"[WARN] {text}")


def print_error(text: str):
    """打印错误"""
    print(f"[ERROR] {text}")


def print_success(text: str):
    """打印成功信息"""
    print(f"[SUCCESS] {text}")


def check_msvc() -> bool:
    """检查MSVC编译器是否可用"""
    print_header("检查MSVC编译器")
    
    # 尝试找到MSVC的cl.exe
    msvc_paths = [
        r"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC",
        r"C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Tools\MSVC",
        r"C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Tools\MSVC",
        r"C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\VC\Tools\MSVC",
        r"C:\Program Files (x86)\Microsoft Visual Studio\2019\Professional\VC\Tools\MSVC",
        r"C:\Program Files (x86)\Microsoft Visual Studio\2019\Enterprise\VC\Tools\MSVC",
    ]
    
    msvc_found = False
    for base_path in msvc_paths:
        if os.path.exists(base_path):
            # 查找最新版本
            versions = [d for d in os.listdir(base_path) if os.path.isdir(os.path.join(base_path, d))]
            if versions:
                versions.sort(reverse=True)
                latest_version = versions[0]
                cl_exe = os.path.join(base_path, latest_version, "bin", "Hostx64", "x64", "cl.exe")
                if os.path.exists(cl_exe):
                    print_success(f"MSVC编译器已找到: {cl_exe}")
                    msvc_found = True
                    break
    
    if not msvc_found:
        # 尝试从环境变量中找到cl.exe
        try:
            result = subprocess.run(
                ["where", "cl"],
                capture_output=True,
                text=True,
                check=True
            )
            if result.stdout.strip():
                print_success(f"MSVC编译器已找到: {result.stdout.strip()}")
                msvc_found = True
        except:
            pass
    
    if not msvc_found:
        print_warning("未找到MSVC编译器，但Nuitka可能会自动下载或使用其他编译器")
        # 不返回False，因为Nuitka可以自动处理
        return True
    
    return True


def setup_msvc_env():
    """设置MSVC环境变量"""
    print_header("设置MSVC环境")
    
    # 尝试运行vcvarsall.bat来设置环境
    vcvarsall_paths = [
        r"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat",
        r"C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvarsall.bat",
        r"C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvarsall.bat",
        r"C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\VC\Auxiliary\Build\vcvarsall.bat",
        r"C:\Program Files (x86)\Microsoft Visual Studio\2019\Professional\VC\Auxiliary\Build\vcvarsall.bat",
        r"C:\Program Files (x86)\Microsoft Visual Studio\2019\Enterprise\VC\Auxiliary\Build\vcvarsall.bat",
    ]
    
    for vcvarsall in vcvarsall_paths:
        if os.path.exists(vcvarsall):
            print_info(f"找到vcvarsall.bat: {vcvarsall}")
            print_info("Nuitka会自动处理MSVC环境")
            break
    
    print_success("MSVC环境设置完成")


def check_nuitka() -> bool:
    """检查Nuitka是否已安装"""
    print_header("检查Nuitka")
    
    try:
        import nuitka
        # 尝试获取版本信息
        version = getattr(nuitka, '__version__', None)
        if version:
            print_success(f"Nuitka已安装，版本: {version}")
        else:
            print_success("Nuitka已安装")
        return True
    except ImportError:
        print_error("Nuitka未安装，请先运行: pip install nuitka")
        return False


def check_virtual_env() -> bool:
    """检查是否在虚拟环境中"""
    print_header("检查虚拟环境")
    
    if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
        print_success(f"虚拟环境已激活: {sys.prefix}")
        return True
    else:
        print_warning("未检测到虚拟环境，建议在虚拟环境中运行")
        return True  # 不强制要求虚拟环境


def get_project_root() -> Path:
    """获取项目根目录"""
    return Path(__file__).parent.absolute()


def collect_data_files() -> List[Tuple[str, str]]:
    """
    收集需要包含的数据文件
    返回: [(源路径, 目标路径), ...]
    """
    print_header("收集数据文件")
    
    project_root = get_project_root()
    data_files = []
    
    # 1. 收集图标文件
    icons_dir = project_root / "freeassetfilter" / "icons"
    if icons_dir.exists():
        for file in icons_dir.rglob("*"):
            if file.is_file():
                rel_path = file.relative_to(project_root)
                data_files.append((str(file), str(rel_path)))
        print_info(f"收集到 {len(list(icons_dir.rglob('*')))} 个图标文件")
    
    # 2. 收集语法高亮JSON文件
    syntax_dir = project_root / "freeassetfilter" / "utils" / "syntax"
    if syntax_dir.exists():
        for file in syntax_dir.glob("*.json"):
            rel_path = file.relative_to(project_root)
            data_files.append((str(file), str(rel_path)))
        print_info(f"收集到 {len(list(syntax_dir.glob('*.json')))} 个语法文件")
    
    # 3. 收集color_schemes.json
    color_schemes = project_root / "freeassetfilter" / "utils" / "color_schemes.json"
    if color_schemes.exists():
        data_files.append((str(color_schemes), "freeassetfilter/utils/color_schemes.json"))
        print_info("收集到 color_schemes.json")
    
    # 4. 收集MPV头文件
    mpv_include_dir = project_root / "freeassetfilter" / "core" / "include" / "mpv"
    if mpv_include_dir.exists():
        for file in mpv_include_dir.glob("*.h"):
            rel_path = file.relative_to(project_root)
            data_files.append((str(file), str(rel_path)))
        print_info(f"收集到 {len(list(mpv_include_dir.glob('*.h')))} 个MPV头文件")
    
    print_success(f"共收集到 {len(data_files)} 个数据文件")
    return data_files


def collect_dll_files() -> List[Tuple[str, str]]:
    """
    收集需要包含的DLL文件
    返回: [(源路径, 目标路径), ...]
    """
    print_header("收集DLL文件")
    
    project_root = get_project_root()
    dll_files = []
    
    # 1. libmpv-2.dll
    libmpv_dll = project_root / "freeassetfilter" / "core" / "libmpv-2.dll"
    if libmpv_dll.exists():
        dll_files.append((str(libmpv_dll), "freeassetfilter/core/libmpv-2.dll"))
        print_info("收集到 libmpv-2.dll")
    else:
        print_warning("未找到 libmpv-2.dll")
    
    # 2. cpp_color_extractor DLLs
    cpp_color_dir = project_root / "freeassetfilter" / "core" / "cpp_color_extractor"
    if cpp_color_dir.exists():
        for dll_name in ["libgcc_s_seh-1.dll", "libgomp-1.dll", "libstdc++-6.dll", "libwinpthread-1.dll"]:
            dll_path = cpp_color_dir / dll_name
            if dll_path.exists():
                dll_files.append((str(dll_path), f"freeassetfilter/core/cpp_color_extractor/{dll_name}"))
        print_info(f"收集到 cpp_color_extractor DLLs")
    
    # 3. cpp_lut_preview DLLs
    cpp_lut_dir = project_root / "freeassetfilter" / "core" / "cpp_lut_preview"
    if cpp_lut_dir.exists():
        for dll_name in ["libgcc_s_seh-1.dll", "libgomp-1.dll", "libstdc++-6.dll", "libwinpthread-1.dll"]:
            dll_path = cpp_lut_dir / dll_name
            if dll_path.exists():
                dll_files.append((str(dll_path), f"freeassetfilter/core/cpp_lut_preview/{dll_name}"))
        print_info(f"收集到 cpp_lut_preview DLLs")
    
    print_success(f"共收集到 {len(dll_files)} 个DLL文件")
    return dll_files


def collect_pyd_files() -> List[Tuple[str, str]]:
    """
    收集Python扩展模块(.pyd文件)
    返回: [(源路径, 目标路径), ...]
    """
    print_header("收集Python扩展模块")
    
    project_root = get_project_root()
    pyd_files = []
    
    # 1. color_extractor_cpp
    cpp_color_dir = project_root / "freeassetfilter" / "core" / "cpp_color_extractor"
    if cpp_color_dir.exists():
        for pyd_file in cpp_color_dir.glob("*.pyd"):
            pyd_files.append((str(pyd_file), f"freeassetfilter/core/cpp_color_extractor/{pyd_file.name}"))
            print_info(f"收集到 {pyd_file.name}")
    
    # 2. lut_preview_cpp
    cpp_lut_dir = project_root / "freeassetfilter" / "core" / "cpp_lut_preview"
    if cpp_lut_dir.exists():
        for pyd_file in cpp_lut_dir.glob("*.pyd"):
            pyd_files.append((str(pyd_file), f"freeassetfilter/core/cpp_lut_preview/{pyd_file.name}"))
            print_info(f"收集到 {pyd_file.name}")
    
    print_success(f"共收集到 {len(pyd_files)} 个Python扩展模块")
    return pyd_files


def build_nuitka_command(data_files: List[Tuple[str, str]], 
                         dll_files: List[Tuple[str, str]],
                         pyd_files: List[Tuple[str, str]]) -> List[str]:
    """构建Nuitka编译命令"""
    print_header("构建Nuitka编译命令")
    
    project_root = get_project_root()
    entry_point = project_root / ENTRY_POINT
    output_dir = project_root / OUTPUT_DIR
    
    # 图标路径
    icon_path = project_root / "freeassetfilter" / "icons" / "FAF-main.ico"
    
    cmd = [
        sys.executable,
        "-m", "nuitka",
        "--standalone",
        # 使用follow-imports，但排除freeassetfilter包的编译
        "--follow-imports",
        # 使用MSVC编译器（Windows上Nuitka默认使用MSVC，不需要额外参数）
        f"--output-dir={output_dir}",
        f"--output-filename={PROJECT_NAME}",
        "--enable-plugin=pyside6",
        "--enable-plugin=multiprocessing",
        # 设置图标
        f"--windows-icon-from-ico={icon_path}",
        # 优化选项：减小体积
        "--lto=yes",  # 启用链接时优化
        "--remove-output",  # 移除中间输出文件
        "--no-pyi-file",  # 不生成.pyi文件
        "--no-deployment-flag=self-execution",  # 不添加自执行标志
    ]
    
    # 包含数据文件
    for src, dst in data_files:
        cmd.append(f"--include-data-files={src}={dst}")
    
    # 包含DLL文件
    for src, dst in dll_files:
        cmd.append(f"--include-data-files={src}={dst}")
    
    # 包含PYD文件（C++扩展模块）
    for src, dst in pyd_files:
        cmd.append(f"--include-data-files={src}={dst}")
    
    # 注意：我们使用--follow-imports，但不再使用--include-package=freeassetfilter
    # 这样freeassetfilter包的代码会以.pyc字节码形式放在外部目录
    # 不会编译进exe，主exe只包含Python解释器和启动代码
    
    # 添加入口文件
    cmd.append(str(entry_point))
    
    print_info(f"编译命令包含 {len(cmd)} 个参数")
    print_success("Nuitka编译命令构建完成")
    
    return cmd


def run_nuitka_build(cmd: List[str]) -> bool:
    """运行Nuitka编译"""
    print_header("开始Nuitka编译")
    print_info("这可能需要几分钟时间，请耐心等待...")
    
    try:
        result = subprocess.run(cmd, check=True)
        print_success("Nuitka编译完成")
        return True
    except subprocess.CalledProcessError as e:
        print_error(f"Nuitka编译失败: {e}")
        return False
    except KeyboardInterrupt:
        print_warning("编译被用户中断")
        return False


def should_remove_dll(dll_name: str) -> bool:
    """判断是否应该移除某个Qt6 DLL"""
    # 如果在白名单中，不移除
    if dll_name in QT6_KEEP_DLLS:
        return False
    
    # 如果在黑名单中，移除
    if dll_name in QT6_REMOVE_DLLS:
        return True
    
    # 检查Quick3D模式
    for pattern in QT6_QUICK3D_PATTERNS:
        if dll_name.startswith(pattern):
            return True
    
    return False


def clean_qt6_dlls() -> Tuple[int, int]:
    """
    清理不必要的Qt6 DLL文件
    返回: (移除的文件数, 节省的空间字节)
    """
    print_header("清理不必要的Qt6 DLL")
    
    project_root = get_project_root()
    output_dir = project_root / OUTPUT_DIR / f"{PROJECT_NAME}.dist"
    
    if not output_dir.exists():
        print_warning(f"输出目录不存在: {output_dir}")
        return 0, 0
    
    removed_count = 0
    saved_space = 0
    
    for dll_file in output_dir.glob("Qt6*.dll"):
        dll_name = dll_file.name
        
        if should_remove_dll(dll_name):
            file_size = dll_file.stat().st_size
            try:
                dll_file.unlink()
                removed_count += 1
                saved_space += file_size
                print_info(f"移除: {dll_name} ({file_size / 1024 / 1024:.2f} MB)")
            except Exception as e:
                print_warning(f"无法移除 {dll_name}: {e}")
    
    print_success(f"共移除 {removed_count} 个Qt6 DLL，节省 {saved_space / 1024 / 1024:.2f} MB")
    return removed_count, saved_space


def verify_output() -> bool:
    """验证输出目录结构"""
    print_header("验证输出目录")
    
    project_root = get_project_root()
    output_dir = project_root / OUTPUT_DIR / f"{PROJECT_NAME}.dist"
    
    if not output_dir.exists():
        print_error(f"输出目录不存在: {output_dir}")
        return False
    
    # 检查关键文件
    key_files = [
        f"{PROJECT_NAME}.exe",
        "python39.dll",
    ]
    
    all_exist = True
    for file_name in key_files:
        file_path = output_dir / file_name
        if file_path.exists():
            size = file_path.stat().st_size
            print_success(f"存在: {file_name} ({size / 1024 / 1024:.2f} MB)")
        else:
            print_error(f"缺失: {file_name}")
            all_exist = False
    
    # 检查资源文件
    resources_to_check = [
        "freeassetfilter/icons/FAF-main.ico",
        "freeassetfilter/utils/color_schemes.json",
    ]
    
    for resource in resources_to_check:
        resource_path = output_dir / resource
        if resource_path.exists():
            print_success(f"资源存在: {resource}")
        else:
            print_warning(f"资源缺失: {resource}")
    
    # 统计目录大小
    total_size = sum(f.stat().st_size for f in output_dir.rglob('*') if f.is_file())
    print_info(f"输出目录总大小: {total_size / 1024 / 1024:.2f} MB")
    
    return all_exist


def analyze_output_size():
    """分析输出目录的大小分布"""
    print_header("分析输出目录大小")
    
    project_root = get_project_root()
    output_dir = project_root / OUTPUT_DIR / f"{PROJECT_NAME}.dist"
    
    if not output_dir.exists():
        print_warning(f"输出目录不存在: {output_dir}")
        return
    
    # 获取所有文件并按大小排序
    files = []
    for f in output_dir.rglob('*'):
        if f.is_file():
            try:
                size = f.stat().st_size
                rel_path = f.relative_to(output_dir)
                files.append((str(rel_path), size))
            except:
                pass
    
    # 按大小降序排序
    files.sort(key=lambda x: x[1], reverse=True)
    
    # 显示最大的20个文件
    print_info("最大的20个文件:")
    for i, (path, size) in enumerate(files[:20], 1):
        print(f"  {i}. {path}: {size / 1024 / 1024:.2f} MB")
    
    # 按类型统计
    type_sizes = {}
    for path, size in files:
        ext = os.path.splitext(path)[1].lower()
        if ext not in type_sizes:
            type_sizes[ext] = 0
        type_sizes[ext] += size
    
    print_info("\n按文件类型统计:")
    sorted_types = sorted(type_sizes.items(), key=lambda x: x[1], reverse=True)
    for ext, size in sorted_types[:10]:
        print(f"  {ext or '(no ext)'}: {size / 1024 / 1024:.2f} MB")
    
    # 统计特定目录
    dir_sizes = {}
    for path, size in files:
        parts = path.split(os.sep)
        if len(parts) > 0:
            top_dir = parts[0]
            if top_dir not in dir_sizes:
                dir_sizes[top_dir] = 0
            dir_sizes[top_dir] += size
    
    print_info("\n按顶级目录统计:")
    sorted_dirs = sorted(dir_sizes.items(), key=lambda x: x[1], reverse=True)
    for dir_name, size in sorted_dirs[:10]:
        print(f"  {dir_name}/: {size / 1024 / 1024:.2f} MB")


def generate_report(removed_dlls: int, saved_space: int):
    """生成编译报告"""
    print_header("编译报告")
    
    project_root = get_project_root()
    output_dir = project_root / OUTPUT_DIR / f"{PROJECT_NAME}.dist"
    
    if output_dir.exists():
        total_size = sum(f.stat().st_size for f in output_dir.rglob('*') if f.is_file())
        file_count = len(list(output_dir.rglob('*')))
        
        print(f"输出目录: {output_dir}")
        print(f"可执行文件: {PROJECT_NAME}.exe")
        print(f"总文件数: {file_count}")
        print(f"总大小: {total_size / 1024 / 1024:.2f} MB")
        print(f"移除Qt6 DLL: {removed_dlls} 个")
        print(f"节省空间: {saved_space / 1024 / 1024:.2f} MB")
        
        # 分析大小
        analyze_output_size()
        
        # 保存报告到文件
        report_path = project_root / OUTPUT_DIR / "build_report.txt"
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(f"FreeAssetFilter 编译报告\n")
            f.write(f"========================\n\n")
            f.write(f"输出目录: {output_dir}\n")
            f.write(f"可执行文件: {PROJECT_NAME}.exe\n")
            f.write(f"总文件数: {file_count}\n")
            f.write(f"总大小: {total_size / 1024 / 1024:.2f} MB\n")
            f.write(f"移除Qt6 DLL: {removed_dlls} 个\n")
            f.write(f"节省空间: {saved_space / 1024 / 1024:.2f} MB\n")
        
        print_info(f"报告已保存: {report_path}")


def check_upx() -> bool:
    """检查UPX是否可用"""
    print_header("检查UPX")
    
    # 首先检查配置的UPX路径
    if os.path.exists(UPX_PATH):
        print_success(f"UPX已找到: {UPX_PATH}")
        return True
    
    # 尝试从PATH中查找
    try:
        result = subprocess.run(
            ["where", "upx"],
            capture_output=True,
            text=True,
            check=True
        )
        if result.stdout.strip():
            print_success(f"UPX已找到: {result.stdout.strip()}")
            return True
    except:
        pass
    
    print_warning("未找到UPX，跳过压缩步骤")
    print_info(r"如需使用UPX压缩，请下载并安装UPX到 C:\upx\ 或添加到PATH")
    return False


def compress_with_upx():
    """使用UPX压缩可执行文件和DLL"""
    print_header("使用UPX压缩")
    
    project_root = get_project_root()
    output_dir = project_root / OUTPUT_DIR / f"{PROJECT_NAME}.dist"
    
    if not output_dir.exists():
        print_warning(f"输出目录不存在: {output_dir}")
        return 0, 0
    
    # 确定UPX路径
    upx_exe = UPX_PATH if os.path.exists(UPX_PATH) else "upx"
    
    # 压缩前的总大小
    total_size_before = sum(f.stat().st_size for f in output_dir.rglob('*') if f.is_file())
    
    # 需要压缩的文件类型
    compressible_extensions = {'.exe', '.dll', '.pyd'}
    
    compressed_count = 0
    skipped_count = 0
    
    # 收集所有可压缩文件
    files_to_compress = []
    for ext in compressible_extensions:
        files_to_compress.extend(output_dir.rglob(f"*{ext}"))
    
    print_info(f"找到 {len(files_to_compress)} 个可压缩文件")
    
    for file_path in files_to_compress:
        try:
            # 跳过已经压缩的文件
            result = subprocess.run(
                [upx_exe, "-t", str(file_path)],
                capture_output=True,
                text=True
            )
            if "already packed" in result.stdout.lower() or result.returncode == 0:
                skipped_count += 1
                continue
            
            # 压缩文件
            result = subprocess.run(
                [upx_exe, "-9", "--lzma", str(file_path)],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                compressed_count += 1
                print_info(f"压缩: {file_path.name}")
            else:
                print_warning(f"无法压缩 {file_path.name}: {result.stderr}")
                
        except Exception as e:
            print_warning(f"压缩 {file_path.name} 时出错: {e}")
    
    # 压缩后的总大小
    total_size_after = sum(f.stat().st_size for f in output_dir.rglob('*') if f.is_file())
    saved_space = total_size_before - total_size_after
    
    print_success(f"UPX压缩完成: {compressed_count} 个文件被压缩, {skipped_count} 个文件跳过")
    print_success(f"节省空间: {saved_space / 1024 / 1024:.2f} MB")
    
    return compressed_count, saved_space


def clean_build():
    """清理编译输出"""
    print_header("清理编译输出")
    
    project_root = get_project_root()
    output_dir = project_root / OUTPUT_DIR
    
    if output_dir.exists():
        try:
            shutil.rmtree(output_dir)
            print_success(f"已删除: {output_dir}")
        except Exception as e:
            print_error(f"无法删除 {output_dir}: {e}")
    else:
        print_info("输出目录不存在，无需清理")
    
    # 清理Nuitka缓存
    nuitka_cache = project_root / ".nuitka"
    if nuitka_cache.exists():
        try:
            shutil.rmtree(nuitka_cache)
            print_success(f"已删除Nuitka缓存: {nuitka_cache}")
        except Exception as e:
            print_warning(f"无法删除Nuitka缓存: {e}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="FreeAssetFilter Nuitka编译脚本")
    parser.add_argument("--clean", action="store_true", help="清理后重新编译")
    parser.add_argument("--skip-build", action="store_true", help="仅执行清理和验证，不编译")
    parser.add_argument("--no-clean-qt", action="store_true", help="不清理Qt6 DLL")
    parser.add_argument("--no-upx", action="store_true", help="不使用UPX压缩")
    parser.add_argument("--upx-only", action="store_true", help="仅执行UPX压缩（用于已编译的程序）")
    args = parser.parse_args()
    
    print_header("FreeAssetFilter Nuitka编译脚本")
    print(f"项目: {PROJECT_NAME}")
    print(f"入口: {ENTRY_POINT}")
    print(f"输出: {OUTPUT_DIR}")
    print(f"编译器: MSVC")
    print(f"UPX压缩: {'禁用' if args.no_upx else '启用'}")
    
    # 仅执行UPX压缩
    if args.upx_only:
        print_info("仅执行UPX压缩")
        if check_upx():
            upx_compressed, upx_saved = compress_with_upx()
            print_header("UPX压缩完成")
            print_success(f"压缩了 {upx_compressed} 个文件，节省 {upx_saved / 1024 / 1024:.2f} MB")
        return 0
    
    # 清理
    if args.clean:
        clean_build()
    
    if args.skip_build:
        print_info("跳过编译，仅执行验证")
        verify_output()
        analyze_output_size()
        return 0
    
    # 检查环境
    if not check_virtual_env():
        return 1
    
    if not check_nuitka():
        return 1
    
    if not check_msvc():
        return 1
    
    # 设置MSVC环境
    setup_msvc_env()
    
    # 收集文件
    data_files = collect_data_files()
    dll_files = collect_dll_files()
    pyd_files = collect_pyd_files()
    
    # 构建编译命令
    cmd = build_nuitka_command(data_files, dll_files, pyd_files)
    
    # 运行编译
    if not run_nuitka_build(cmd):
        return 1
    
    # 清理Qt6 DLL
    removed_dlls = 0
    saved_space = 0
    if not args.no_clean_qt:
        removed_dlls, saved_space = clean_qt6_dlls()
    
    # UPX压缩
    upx_compressed = 0
    upx_saved = 0
    if not args.no_upx:
        if check_upx():
            upx_compressed, upx_saved = compress_with_upx()
    
    # 验证输出
    if not verify_output():
        print_warning("输出验证未通过，但编译可能仍然可用")
    
    # 生成报告
    generate_report(removed_dlls, saved_space)
    
    print_header("编译完成")
    print_success(f"可执行文件位于: {OUTPUT_DIR}/{PROJECT_NAME}.dist/{PROJECT_NAME}.exe")
    if upx_saved > 0:
        print_success(f"UPX压缩节省: {upx_saved / 1024 / 1024:.2f} MB")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
