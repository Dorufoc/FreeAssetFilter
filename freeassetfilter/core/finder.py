#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
依赖管理模块
负责检查和安装项目依赖以及VLC播放器
"""

import sys
import os

# 尝试导入依赖检查所需的模块
importlib_metadata_available = False

# 尝试使用importlib.metadata（Python 3.8+内置）
try:
    import importlib.metadata
    importlib_metadata_available = True
except ImportError:
    # 如果内置的不可用，尝试使用importlib_metadata包（Python 3.7及以下需要）
    try:
        import importlib_metadata
        # 动态创建importlib.metadata别名
        sys.modules['importlib.metadata'] = importlib_metadata
        importlib_metadata_available = True
    except ImportError:
        # 如果所有方法都失败，依赖检查将无法正常工作
        importlib_metadata_available = False

# 尝试导入版本解析模块
try:
    from packaging.version import parse
except ImportError:
    # 如果packaging不可用，使用简单的版本比较
    def parse(version_str):
        return tuple(map(int, version_str.split('.')[:3]))


def parse_dependency(dep_str):
    """
    解析单个依赖字符串，支持多种版本约束格式

    Args:
        dep_str: str - 依赖字符串，如 "library>=version"

    Returns:
        tuple: (lib_name, operator, required_version)
            lib_name: str - 依赖包名称
            operator: str - 版本比较运算符 (>, >=, <, <=, ==, None)
            required_version: str - 要求的版本号，无版本要求时为None
    """
    # 移除依赖项后面的注释（如：library>=version # comment）
    if '#' in dep_str:
        dep_str = dep_str.split('#', 1)[0].strip()
    
    # 解析依赖项，支持格式如：library>=version
    if '>=' in dep_str:
        lib_name, required_version = dep_str.split('>=', 1)
        return lib_name.strip(), '>=', required_version.strip()
    elif '>' in dep_str:
        lib_name, required_version = dep_str.split('>', 1)
        return lib_name.strip(), '>', required_version.strip()
    elif '<=' in dep_str:
        lib_name, required_version = dep_str.split('<=', 1)
        return lib_name.strip(), '<=', required_version.strip()
    elif '<' in dep_str:
        lib_name, required_version = dep_str.split('<', 1)
        return lib_name.strip(), '<', required_version.strip()
    elif '==' in dep_str:
        lib_name, required_version = dep_str.split('==', 1)
        return lib_name.strip(), '==', required_version.strip()
    else:
        # 没有版本要求
        return dep_str.strip(), None, None


def check_dependencies():
    """
    检查项目依赖是否已安装，根据requirements.txt文件

    Returns:
        tuple: (success, missing_deps, version_issues)
            success: bool - 是否所有依赖都满足
            missing_deps: list - 缺失的依赖列表，每个元素为依赖字符串
            version_issues: list - 版本不符合要求的依赖列表
    """
    requirements_file = os.path.join(os.path.dirname(__file__), 'requirements.txt')
    missing_deps = []
    version_issues = []

    try:
        with open(requirements_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        for line in lines:
            # 跳过注释行和空行
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            # 解析依赖项
            lib_name, operator, required_version = parse_dependency(line)

            # 检查依赖是否已安装
            try:
                if not importlib_metadata_available:
                    # 如果importlib.metadata不可用，使用简单的尝试导入方式
                    __import__(lib_name)
                    # 无法检查版本，假设版本符合要求
                else:
                    installed_version = importlib.metadata.version(lib_name)
                    # 检查版本是否符合要求
                    if required_version:
                        installed = parse(installed_version)
                        required = parse(required_version)
                        version_ok = True
                        
                        # 根据运算符检查版本
                        if operator == '>':
                            version_ok = installed > required
                        elif operator == '>=':
                            version_ok = installed >= required
                        elif operator == '<':
                            version_ok = installed < required
                        elif operator == '<=':
                            version_ok = installed <= required
                        elif operator == '==':
                            version_ok = installed == required
                        
                        if not version_ok:
                            version_issues.append((lib_name, installed_version, required_version))
                            missing_deps.append(line)  # 将版本问题也视为需要安装的依赖
            except (ImportError, NameError):
                missing_deps.append(line)  # 直接添加完整依赖字符串
            except Exception:
                missing_deps.append(line)  # 其他错误也视为缺失

        success = len(missing_deps) == 0 and len(version_issues) == 0
        return success, missing_deps, version_issues

    except Exception as e:
        print(f"读取requirements.txt文件时出错: {e}")
        return False, [], []


def install_missing_dependencies(missing_deps):
    """
    使用清华源自动安装缺失的依赖

    Args:
        missing_deps: list - 缺失的依赖列表，每个元素为依赖字符串

    Returns:
        bool: 安装是否成功
    """
    if not missing_deps:
        return True

    print(f"开始安装缺失的依赖: {missing_deps}")

    # 构建pip install命令，使用清华源
    import subprocess

    # 构造完整的依赖字符串列表
    cmd = [
        sys.executable, "-m", "pip", "install",
        "-i", "https://pypi.tuna.tsinghua.edu.cn/simple/",
        "--upgrade"] + missing_deps

    try:
        print(f"执行命令: {' '.join(cmd)}")
        # 使用shell=True和timeout来避免某些环境下的问题
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, shell=False, timeout=300)
        print(f"依赖安装成功:\n{result.stdout}")
        if result.stderr:
            print(f"安装警告:\n{result.stderr}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"依赖安装失败:\n{e.stderr}")
        # 尝试单独安装每个依赖，以便找出具体哪个依赖安装失败
        print("\n尝试单独安装每个依赖...")
        all_success = True
        for dep in missing_deps:
            try:
                single_cmd = [
                    sys.executable, "-m", "pip", "install",
                    "-i", "https://pypi.tuna.tsinghua.edu.cn/simple/",
                    "--upgrade", dep]
                print(f"执行命令: {' '.join(single_cmd)}")
                single_result = subprocess.run(single_cmd, check=True, capture_output=True, text=True, shell=False, timeout=120)
                print(f"依赖 {dep} 安装成功")
            except subprocess.CalledProcessError as se:
                print(f"依赖 {dep} 安装失败:\n{se.stderr}")
                all_success = False
            except Exception as se:
                print(f"安装依赖 {dep} 时发生未知错误: {se}")
                all_success = False
        return all_success
    except subprocess.TimeoutExpired:
        print("依赖安装超时，请手动安装依赖")
        return False
    except Exception as e:
        print(f"安装过程中发生未知错误: {e}")
        return False


def check_vlc_installed():
    """
    检查VLC是否已安装

    Returns:
        bool: VLC是否已安装
    """
    try:
        import vlc
        vlc.Instance()
        return True
    except ImportError:
        return False
    except Exception:
        return False


# VLC相关常量
VLC_VERSION = "3.0.21"
VLC_INSTALLER_NAME = f"vlc-{VLC_VERSION}-win64.exe"
VLC_DOWNLOAD_URL = f"https://mirrors.tuna.tsinghua.edu.cn/videolan-ftp/vlc/{VLC_VERSION}/win64/{VLC_INSTALLER_NAME}"


def install_vlc_windows():
    """
    在Windows平台自动下载并安装VLC到程序所在目录

    Returns:
        bool: 安装是否成功
    """
    import subprocess
    import time

    # 获取程序所在目录
    program_dir = os.path.dirname(os.path.abspath(__file__))
    vlc_installer_path = os.path.join(program_dir, VLC_INSTALLER_NAME)
    vlc_install_path = os.path.join(program_dir, "vlc")

    # 检查VLC是否已安装在程序目录
    vlc_exe_path = os.path.join(vlc_install_path, "vlc.exe")
    if os.path.exists(vlc_install_path) and os.path.exists(vlc_exe_path):
        print(f"VLC已安装在: {vlc_install_path}")
        return True

    # 下载VLC安装包
    print("正在下载VLC安装包...")
    try:
        import requests
        response = requests.get(VLC_DOWNLOAD_URL, stream=True)
        response.raise_for_status()

        with open(vlc_installer_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        print(f"VLC安装包下载成功: {vlc_installer_path}")
    except Exception as e:
        print(f"VLC安装包下载失败: {e}")
        return False

    # 静默安装VLC到程序目录
    print("正在安装VLC...")
    try:
        # 静默安装命令，/D指定安装目录
        cmd = [vlc_installer_path, "/S", f"/D={vlc_install_path}"]
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(f"VLC安装成功:\n{result.stdout}")

        # 清理安装包
        if os.path.exists(vlc_installer_path):
            os.remove(vlc_installer_path)
            print(f"已清理安装包: {vlc_installer_path}")

        # 等待VLC安装完成
        time.sleep(2)

        # 验证安装
        if os.path.exists(vlc_exe_path):
            print(f"VLC已成功安装到: {vlc_install_path}")
            return True
        else:
            print("VLC安装失败，未找到vlc.exe")
            return False
    except subprocess.CalledProcessError as e:
        print(f"VLC安装失败:\n{e.stderr}")
        return False
    except Exception as e:
        print(f"VLC安装过程中发生未知错误: {e}")
        return False


def restart_program():
    """
    重启当前程序
    """
    print("环境修复完成，正在重启程序...")
    python = sys.executable
    os.execl(python, python, *sys.argv)


def show_dependency_error(missing_deps, version_issues):
    """
    显示依赖错误信息，提示用户安装缺失的依赖

    Args:
        missing_deps: list - 缺失的依赖列表，每个元素为完整依赖字符串
        version_issues: list - 版本不符合要求的依赖列表
    """
    message = "检测到项目依赖问题，请安装或更新以下依赖：\n\n"

    if missing_deps:
        message += "缺失的依赖：\n"
        for dep in missing_deps:
            message += f"  - {dep}\n"
        message += "\n"

    if version_issues:
        message += "版本不符合要求的依赖：\n"
        for lib, installed, required in version_issues:
            message += f"  - {lib}: 已安装 {installed}, 要求 >= {required}\n"

    message += "\n安装命令：\npip install -r requirements.txt"

    # 使用简单的print输出，避免依赖PyQt5
    print("\n" + "="*50)
    print("依赖错误")
    print("="*50)
    print(message)
    print("="*50 + "\n")

    # 尝试使用自定义消息框显示错误
    try:
        from PyQt5.QtWidgets import QApplication
        from freeassetfilter.widgets.custom_widgets import CustomMessageBox
        app = QApplication.instance()
        if app:
            msg_box = CustomMessageBox(None)
            msg_box.set_title("依赖警告")
            msg_box.set_text(message)
            msg_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
            msg_box.exec_()
    except Exception:
        # 如果PyQt5或自定义消息框不可用，只使用print输出
        pass

    # 不要强制退出，让应用程序继续运行
    print("[警告] 依赖检查失败，但应用程序将继续运行，某些功能可能不可用。")


# 主程序入口
if __name__ == "__main__":
    print("=== FreeAssetFilter 环境检查与修复工具 ===")
    # 标记是否需要重启程序
    need_restart = False
    
    # 1. 检查并安装缺失的Python依赖
    print("\n1. 正在检查Python依赖...")
    success, missing_deps, version_issues = check_dependencies()
    if not success:
        print(f"   检测到缺失的依赖: {missing_deps}")
        install_success = install_missing_dependencies(missing_deps)
        if install_success:
            need_restart = True
            print("   依赖安装成功，需要重启程序。")
        else:
            print("   依赖安装失败，请手动安装依赖后重试。")
    else:
        print("   所有Python依赖已安装完成。")
    
    # 2. 检查并安装VLC
    print("\n2. 正在检查VLC安装情况...")
    if not check_vlc_installed():
        print("   VLC未安装。")
        if sys.platform == "win32":
            # 在Windows平台自动安装VLC
            vlc_install_success = install_vlc_windows()
            if vlc_install_success:
                need_restart = True
                print("   VLC安装成功，需要重启程序。")
            else:
                print("   VLC安装失败，请手动安装VLC后重试。")
        else:
            # 非Windows平台提示用户自行安装
            print("   非Windows平台，请手动安装VLC后重试。")
    else:
        print("   VLC已安装完成。")
    
    # 3. 如果需要重启，执行重启
    if need_restart:
        print("\n3. 正在重启程序...")
        python = sys.executable
        os.execl(python, python, *sys.argv)
    else:
        # 4. 环境检查通过，启动主程序
        print("\n4. 环境检查通过，正在启动主程序...")
        import subprocess
        # 启动实际的主程序
        subprocess.Popen([sys.executable, "-m", "freeassetfilter.app.main"])
