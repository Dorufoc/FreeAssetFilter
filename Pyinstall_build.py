#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter PyInstaller 打包脚本

使用PyInstaller将FreeAssetFilter打包为Windows可执行程序

使用方法:
    python Pyinstall_build.py
    python Pyinstall_build.py --clean  # 清理后重新打包
    python Pyinstall_build.py --skip-build  # 仅执行清理和验证

环境要求:
    - Python 3.9+
    - PyInstaller (pip install pyinstaller)
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
OUTPUT_DIR = "build/pyinstall"
WORK_PATH = "build/pyinstall/work"
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
    # WebEngine 相关（体积太大，项目不需要）
    "Qt6WebEngineCore.dll",
    "Qt6WebEngineWidgets.dll",
    "Qt6WebEngineQuick.dll",
    "Qt6WebChannel.dll",
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


def check_pyinstaller() -> bool:
    """检查PyInstaller是否已安装"""
    print_header("检查PyInstaller")
    
    try:
        import PyInstaller
        # 尝试获取版本信息
        version = getattr(PyInstaller, '__version__', None)
        if version:
            print_success(f"PyInstaller已安装，版本: {version}")
        else:
            print_success("PyInstaller已安装")
        return True
    except ImportError:
        print_error("PyInstaller未安装，请先运行: pip install pyinstaller")
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
    返回: [(源路径, 目标目录), ...]
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
                data_files.append((str(file), str(rel_path.parent)))
        print_info(f"收集到 {len(list(icons_dir.rglob('*')))} 个图标文件")
    
    # 2. 收集语法高亮JSON文件
    syntax_dir = project_root / "freeassetfilter" / "utils" / "syntax"
    if syntax_dir.exists():
        for file in syntax_dir.glob("*.json"):
            rel_path = file.relative_to(project_root)
            data_files.append((str(file), str(rel_path.parent)))
        print_info(f"收集到 {len(list(syntax_dir.glob('*.json')))} 个语法文件")
    
    # 3. 收集color_schemes.json
    color_schemes = project_root / "freeassetfilter" / "utils" / "color_schemes.json"
    if color_schemes.exists():
        data_files.append((str(color_schemes), "freeassetfilter/utils"))
        print_info("收集到 color_schemes.json")
    
    # 4. 收集MPV头文件
    mpv_include_dir = project_root / "freeassetfilter" / "core" / "include" / "mpv"
    if mpv_include_dir.exists():
        for file in mpv_include_dir.glob("*.h"):
            rel_path = file.relative_to(project_root)
            data_files.append((str(file), str(rel_path.parent)))
        print_info(f"收集到 {len(list(mpv_include_dir.glob('*.h')))} 个MPV头文件")
    
    print_success(f"共收集到 {len(data_files)} 个数据文件")
    return data_files


def collect_binaries() -> List[Tuple[str, str]]:
    """
    收集需要包含的二进制文件(DLL等)
    返回: [(源路径, 目标目录), ...]
    """
    print_header("收集二进制文件")
    
    project_root = get_project_root()
    binaries = []
    
    # 1. libmpv-2.dll
    libmpv_dll = project_root / "freeassetfilter" / "core" / "libmpv-2.dll"
    if libmpv_dll.exists():
        binaries.append((str(libmpv_dll), "freeassetfilter/core"))
        print_info("收集到 libmpv-2.dll")
    else:
        print_warning("未找到 libmpv-2.dll")
    
    # 2. cpp_color_extractor DLLs
    cpp_color_dir = project_root / "freeassetfilter" / "core" / "cpp_color_extractor"
    if cpp_color_dir.exists():
        for dll_name in ["libgcc_s_seh-1.dll", "libgomp-1.dll", "libstdc++-6.dll", "libwinpthread-1.dll"]:
            dll_path = cpp_color_dir / dll_name
            if dll_path.exists():
                binaries.append((str(dll_path), "freeassetfilter/core/cpp_color_extractor"))
        print_info(f"收集到 cpp_color_extractor DLLs")
    
    # 3. cpp_lut_preview DLLs
    cpp_lut_dir = project_root / "freeassetfilter" / "core" / "cpp_lut_preview"
    if cpp_lut_dir.exists():
        for dll_name in ["libgcc_s_seh-1.dll", "libgomp-1.dll", "libstdc++-6.dll", "libwinpthread-1.dll"]:
            dll_path = cpp_lut_dir / dll_name
            if dll_path.exists():
                binaries.append((str(dll_path), "freeassetfilter/core/cpp_lut_preview"))
        print_info(f"收集到 cpp_lut_preview DLLs")
    
    # 4. 收集Python扩展模块(.pyd文件)
    # cpp_color_extractor
    if cpp_color_dir.exists():
        for pyd_file in cpp_color_dir.glob("*.pyd"):
            binaries.append((str(pyd_file), "freeassetfilter/core/cpp_color_extractor"))
            print_info(f"收集到 {pyd_file.name}")
    
    # cpp_lut_preview
    if cpp_lut_dir.exists():
        for pyd_file in cpp_lut_dir.glob("*.pyd"):
            binaries.append((str(pyd_file), "freeassetfilter/core/cpp_lut_preview"))
            print_info(f"收集到 {pyd_file.name}")
    
    print_success(f"共收集到 {len(binaries)} 个二进制文件")
    return binaries


def collect_hidden_imports() -> List[str]:
    """收集需要显式导入的隐藏模块"""
    print_header("收集隐藏导入")
    
    hidden_imports = [
        # C++扩展模块
        "freeassetfilter.core.cpp_color_extractor",
        "freeassetfilter.core.cpp_lut_preview",
        # 重要包
        "PIL",
        "PIL._imagingtk",
        "PIL._tkinter_finder",
        "numpy",
        "cv2",
        "skimage",
        "scipy",
        "psd_tools",
        "rawpy",
        "pymupdf",
        "fitz",
        "mutagen",
        "rarfile",
        "py7zr",
        "pygments",
        "markdown",
        "exifread",
        "pillow_heif",
        "aggdraw",
        "imageio",
        "psutil",
        # PySide6相关
        "PySide6",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "PySide6.QtSvg",
        "PySide6.QtNetwork",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtMultimedia",
        "PySide6.QtOpenGL",
        "shiboken6",
    ]
    
    print_success(f"共收集到 {len(hidden_imports)} 个隐藏导入")
    return hidden_imports


def build_pyinstaller_command(data_files: List[Tuple[str, str]], 
                               binaries: List[Tuple[str, str]],
                               hidden_imports: List[str]) -> List[str]:
    """构建PyInstaller打包命令"""
    print_header("构建PyInstaller打包命令")
    
    project_root = get_project_root()
    entry_point = project_root / ENTRY_POINT
    output_dir = project_root / OUTPUT_DIR
    work_path = project_root / WORK_PATH
    
    # 图标路径
    icon_path = project_root / "freeassetfilter" / "icons" / "FAF-main.ico"
    if icon_path.exists():
        print_info(f"使用图标: {icon_path}")
    else:
        print_warning(f"图标文件不存在: {icon_path}")
    
    cmd = [
        sys.executable,
        "-m", "PyInstaller",
        "--noconfirm",  # 不询问确认，直接覆盖
        "--distpath", str(output_dir),
        "--workpath", str(work_path),
        "--name", PROJECT_NAME,
        "--windowed",  # Windows GUI应用程序，不显示控制台
        "--clean",  # 清理PyInstaller缓存
    ]
    
    # 设置图标（使用绝对路径）
    if icon_path.exists():
        cmd.extend(["--icon", str(icon_path.resolve())])
    
    cmd.extend([
        # 排除不需要的模块
        "--exclude-module", "PyInstaller",
        "--exclude-module", "nuitka",
        "--exclude-module", "pip",
        "--exclude-module", "setuptools",
        "--exclude-module", "wheel",
        "--exclude-module", "pytest",
        "--exclude-module", "_pytest",
        "--exclude-module", "unittest",
        "--exclude-module", "test",
        "--exclude-module", "tests",
        # 排除 Qt WebEngine（体积太大，项目不需要）
        "--exclude-module", "PySide6.QtWebEngineCore",
        "--exclude-module", "PySide6.QtWebEngineWidgets",
        "--exclude-module", "PySide6.QtWebEngineQuick",
        "--exclude-module", "PySide6.QtWebChannel",
        # 排除 numpy/scipy 的测试和可选依赖模块
        "--exclude-module", "numpy.f2py.tests",
        "--exclude-module", "numpy._pytesttester",
        "--exclude-module", "scipy._lib.array_api_compat.torch",
        "--exclude-module", "torch",
    ])
    
    # 添加数据文件
    for src, dst in data_files:
        cmd.extend(["--add-data", f"{src}{os.pathsep}{dst}"])
    
    # 添加二进制文件
    for src, dst in binaries:
        cmd.extend(["--add-binary", f"{src}{os.pathsep}{dst}"])
    
    # 添加隐藏导入
    for imp in hidden_imports:
        cmd.extend(["--hidden-import", imp])
    
    # 包含所有子包（只对有子模块的包使用 --collect-all）
    cmd.extend([
        "--collect-all", "freeassetfilter",
        "--collect-all", "PIL",
        "--collect-all", "numpy",
        "--collect-all", "cv2",
        "--collect-all", "skimage",
        "--collect-all", "scipy",
        "--collect-all", "psd_tools",
        "--collect-all", "rawpy",
        "--collect-all", "pymupdf",
        "--collect-all", "mutagen",
        "--collect-all", "py7zr",
        "--collect-all", "pygments",
        "--collect-all", "markdown",
        "--collect-all", "exifread",
        "--collect-all", "pillow_heif",
        "--collect-all", "imageio",
        "--collect-all", "psutil",
    ])
    
    # 添加入口文件
    cmd.append(str(entry_point))
    
    print_info(f"打包命令包含 {len(cmd)} 个参数")
    print_success("PyInstaller打包命令构建完成")
    
    return cmd


def run_pyinstaller_build(cmd: List[str]) -> bool:
    """运行PyInstaller打包"""
    print_header("开始PyInstaller打包")
    print_info("这可能需要几分钟时间，请耐心等待...")
    
    try:
        result = subprocess.run(cmd, check=True)
        print_success("PyInstaller打包完成")
        return True
    except subprocess.CalledProcessError as e:
        print_error(f"PyInstaller打包失败: {e}")
        return False
    except KeyboardInterrupt:
        print_warning("打包被用户中断")
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
    清理不必要的Qt6 DLL文件和资源
    返回: (移除的文件数, 节省的空间字节)
    """
    print_header("清理不必要的Qt6 DLL和资源")
    
    project_root = get_project_root()
    output_dir = project_root / OUTPUT_DIR / PROJECT_NAME
    internal_dir = output_dir / "_internal"
    
    if not output_dir.exists():
        print_warning(f"输出目录不存在: {output_dir}")
        return 0, 0
    
    removed_count = 0
    saved_space = 0
    
    # 1. 清理 Qt6 DLL
    search_dirs = [output_dir]
    if internal_dir.exists():
        search_dirs.append(internal_dir)
    
    for search_dir in search_dirs:
        for dll_file in search_dir.glob("Qt6*.dll"):
            dll_name = dll_file.name
            
            if should_remove_dll(dll_name):
                file_size = dll_file.stat().st_size
                try:
                    dll_file.unlink()
                    removed_count += 1
                    saved_space += file_size
                    print_info(f"移除 DLL: {dll_name} ({file_size / 1024 / 1024:.2f} MB)")
                except Exception as e:
                    print_warning(f"无法移除 {dll_name}: {e}")
    
    # 2. 清理 WebEngine 资源文件
    webengine_patterns = [
        "*webengine*",
        "*WebEngine*",
        "qtwebengine*",
    ]
    
    for search_dir in search_dirs:
        for pattern in webengine_patterns:
            for file_path in search_dir.rglob(pattern):
                if file_path.is_file():
                    file_size = file_path.stat().st_size
                    try:
                        file_path.unlink()
                        removed_count += 1
                        saved_space += file_size
                        print_info(f"移除 WebEngine 资源: {file_path.name} ({file_size / 1024 / 1024:.2f} MB)")
                    except Exception as e:
                        print_warning(f"无法移除 {file_path.name}: {e}")
    
    # 3. 清理 QtWebEngineProcess.exe
    for search_dir in search_dirs:
        for exe_file in search_dir.rglob("QtWebEngineProcess.exe"):
            file_size = exe_file.stat().st_size
            try:
                exe_file.unlink()
                removed_count += 1
                saved_space += file_size
                print_info(f"移除: {exe_file.name} ({file_size / 1024 / 1024:.2f} MB)")
            except Exception as e:
                print_warning(f"无法移除 {exe_file.name}: {e}")
    
    # 4. 清理 PySide6/resources 目录中的 WebEngine 资源
    pyside6_resources_dirs = list(search_dirs[0].rglob("PySide6/resources")) if search_dirs else []
    if internal_dir.exists():
        pyside6_resources_dirs.extend(list(internal_dir.rglob("PySide6/resources")))
    
    for resources_dir in pyside6_resources_dirs:
        if resources_dir.exists():
            for file_path in resources_dir.glob("*webengine*"):
                if file_path.is_file():
                    file_size = file_path.stat().st_size
                    try:
                        file_path.unlink()
                        removed_count += 1
                        saved_space += file_size
                        print_info(f"移除资源: {file_path.name} ({file_size / 1024 / 1024:.2f} MB)")
                    except Exception as e:
                        print_warning(f"无法移除 {file_path.name}: {e}")
    
    # 5. 清理 translations 目录（多语言翻译文件，如不需要可节省空间）
    translations_dirs = []
    for search_dir in search_dirs:
        translations_dirs.extend(list(search_dir.rglob("translations")))
        # 也查找 PySide6/translations
        pyside6_dir = search_dir / "PySide6"
        if pyside6_dir.exists():
            pyside6_translations = pyside6_dir / "translations"
            if pyside6_translations.exists():
                translations_dirs.append(pyside6_translations)
    
    for trans_dir in translations_dirs:
        if trans_dir.exists() and trans_dir.is_dir():
            dir_size = sum(f.stat().st_size for f in trans_dir.rglob('*') if f.is_file())
            try:
                shutil.rmtree(trans_dir)
                removed_count += 1
                saved_space += dir_size
                print_info(f"移除翻译目录: {trans_dir.name} ({dir_size / 1024 / 1024:.2f} MB)")
            except Exception as e:
                print_warning(f"无法移除翻译目录 {trans_dir}: {e}")
    
    print_success(f"共移除 {removed_count} 个文件/目录，节省 {saved_space / 1024 / 1024:.2f} MB")
    return removed_count, saved_space


def verify_output() -> bool:
    """验证输出目录结构"""
    print_header("验证输出目录")
    
    project_root = get_project_root()
    output_dir = project_root / OUTPUT_DIR / PROJECT_NAME
    
    if not output_dir.exists():
        print_error(f"输出目录不存在: {output_dir}")
        return False
    
    # 检查关键文件
    key_files = [
        f"{PROJECT_NAME}.exe",
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
    output_dir = project_root / OUTPUT_DIR / PROJECT_NAME
    
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
    """生成打包报告"""
    print_header("打包报告")
    
    project_root = get_project_root()
    output_dir = project_root / OUTPUT_DIR / PROJECT_NAME
    
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
            f.write(f"FreeAssetFilter PyInstaller 打包报告\n")
            f.write(f"=====================================\n\n")
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
    output_dir = project_root / OUTPUT_DIR / PROJECT_NAME
    
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
    """清理打包输出"""
    print_header("清理打包输出")
    
    project_root = get_project_root()
    output_dir = project_root / OUTPUT_DIR
    work_path = project_root / WORK_PATH
    
    if output_dir.exists():
        try:
            shutil.rmtree(output_dir)
            print_success(f"已删除: {output_dir}")
        except Exception as e:
            print_error(f"无法删除 {output_dir}: {e}")
    else:
        print_info("输出目录不存在，无需清理")
    
    if work_path.exists():
        try:
            shutil.rmtree(work_path)
            print_success(f"已删除工作目录: {work_path}")
        except Exception as e:
            print_warning(f"无法删除工作目录: {e}")
    
    # 清理PyInstaller缓存
    pyinstaller_cache = project_root / "__pycache__"
    if pyinstaller_cache.exists():
        try:
            shutil.rmtree(pyinstaller_cache)
            print_success(f"已删除PyInstaller缓存: {pyinstaller_cache}")
        except Exception as e:
            print_warning(f"无法删除PyInstaller缓存: {e}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="FreeAssetFilter PyInstaller打包脚本")
    parser.add_argument("--clean", action="store_true", help="清理后重新打包")
    parser.add_argument("--skip-build", action="store_true", help="仅执行清理和验证，不打包")
    parser.add_argument("--no-clean-qt", action="store_true", help="不清理Qt6 DLL")
    parser.add_argument("--no-upx", action="store_true", help="不使用UPX压缩")
    parser.add_argument("--upx-only", action="store_true", help="仅执行UPX压缩（用于已打包的程序）")
    args = parser.parse_args()
    
    print_header("FreeAssetFilter PyInstaller打包脚本")
    print(f"项目: {PROJECT_NAME}")
    print(f"入口: {ENTRY_POINT}")
    print(f"输出: {OUTPUT_DIR}")
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
        print_info("跳打包，仅执行验证")
        verify_output()
        analyze_output_size()
        return 0
    
    # 检查环境
    if not check_virtual_env():
        return 1
    
    if not check_pyinstaller():
        return 1
    
    # 收集文件
    data_files = collect_data_files()
    binaries = collect_binaries()
    hidden_imports = collect_hidden_imports()
    
    # 构建打包命令
    cmd = build_pyinstaller_command(data_files, binaries, hidden_imports)
    
    # 运行打包
    if not run_pyinstaller_build(cmd):
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
        print_warning("输出验证未通过，但打包可能仍然可用")
    
    # 生成报告
    generate_report(removed_dlls, saved_space)
    
    print_header("打包完成")
    print_success(f"可执行文件位于: {OUTPUT_DIR}/{PROJECT_NAME}/{PROJECT_NAME}.exe")
    if upx_saved > 0:
        print_success(f"UPX压缩节省: {upx_saved / 1024 / 1024:.2f} MB")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
