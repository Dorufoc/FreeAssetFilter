"""构建 ``mica_render.dll``（Mica GPU 渲染原生库）。

用法::

    python build.py               # Release 构建并安装到 core/native/bin/
    python build.py --debug       # 带调试符号、不优化
    python build.py --no-install  # 只构建，不拷贝到 bin/

设计要点
--------
* **不调用 vcvars64.bat**：该脚本内部通过 ``reg.exe`` 查询 Windows SDK 安装
  位置，在受限执行环境（沙箱 / CI 白名单）下会静默失败，只注入 MSVC 路径而
  漏掉 SDK，表现为 ``fatal error C1083: Cannot open include file: 'windows.h'``。
  这里改为直接扫描文件系统推导 ``INCLUDE`` / ``LIB`` / ``PATH``，行为确定且
  可复现。
* 使用 **静态 CRT**（``/MT``）：产物不依赖 ``Microsoft C++ Redistributable``，
  避免用户机器缺少运行库时整个 Mica 模块加载失败。
* ``/utf-8``：源码为 UTF-8 无 BOM，中文注释在 GBK 代码页下会触发 C4819。
* ``d3dcompiler_47.dll`` 在 ``mica_device.cpp`` 中动态加载，因此**不**链接
  ``d3dcompiler.lib``——即使该 DLL 缺失也只是降级到 CPU 管线。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SOURCES: List[str] = [
    "mica_api.cpp",
    "mica_device.cpp",
    "mica_capture.cpp",
    "mica_pipeline.cpp",
]

LIBS: List[str] = [
    "d3d11.lib",
    "d2d1.lib",
    "dxgi.lib",
    "windowscodecs.lib",
    "ole32.lib",
]

TARGET_NAME = "mica_render.dll"

VS_ROOTS: List[str] = [
    r"C:\Program Files (x86)\Microsoft Visual Studio",
    r"C:\Program Files\Microsoft Visual Studio",
]

SDK_ROOTS: List[str] = [
    r"C:\Program Files (x86)\Windows Kits\10",
    r"C:\Program Files\Windows Kits\10",
]

SDK_INCLUDE_SUBDIRS: List[str] = ["ucrt", "um", "shared", "winrt", "cppwinrt"]
SDK_LIB_SUBDIRS: List[str] = ["ucrt", "um"]


def _version_key(name: str) -> Tuple[int, ...]:
    """把 ``14.44.35207`` / ``10.0.26100.0`` 这类版本号解析为可比较的元组。

    Args:
        name: 目录名。

    Returns:
        整数元组；非数字段按 0 处理，保证排序不抛异常。
    """
    parts: List[int] = []
    for chunk in name.split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def find_msvc_toolset() -> Optional[Path]:
    """定位版本最高的 MSVC 工具集目录（``.../VC/Tools/MSVC/<ver>``）。

    Returns:
        工具集根目录；找不到时返回 ``None``。
    """
    candidates: List[Path] = []
    for root_text in VS_ROOTS:
        root = Path(root_text)
        if not root.exists():
            continue
        for year in root.iterdir():
            if not year.is_dir():
                continue
            for edition in year.iterdir():
                msvc = edition / "VC" / "Tools" / "MSVC"
                if not msvc.is_dir():
                    continue
                for toolset in msvc.iterdir():
                    if (toolset / "bin" / "Hostx64" / "x64" / "cl.exe").exists():
                        candidates.append(toolset)
    if not candidates:
        return None
    return max(candidates, key=lambda p: _version_key(p.name))


def find_windows_sdk() -> Optional[Tuple[Path, str]]:
    """定位版本最高的 Windows SDK。

    Returns:
        ``(sdk_root, version)``；找不到时返回 ``None``。
    """
    best: Optional[Tuple[Path, str]] = None
    for root_text in SDK_ROOTS:
        root = Path(root_text)
        include = root / "Include"
        lib = root / "Lib"
        if not include.is_dir() or not lib.is_dir():
            continue
        for entry in include.iterdir():
            if not (entry / "um" / "windows.h").exists():
                continue
            if not (lib / entry.name / "um" / "x64").is_dir():
                continue
            if best is None or _version_key(entry.name) > _version_key(best[1]):
                best = (root, entry.name)
    return best


def build_env() -> Tuple[Optional[Dict[str, str]], Optional[Path], str]:
    """构造 MSVC 编译所需的环境变量。

    Returns:
        ``(env, cl_path, message)``。失败时 ``env`` 与 ``cl_path`` 为 ``None``，
        ``message`` 说明原因；成功时 ``message`` 为工具链摘要。
    """
    toolset = find_msvc_toolset()
    if toolset is None:
        return None, None, "未找到 MSVC 工具集，请安装 Visual Studio Build Tools（C++ 工作负载）。"
    sdk = find_windows_sdk()
    if sdk is None:
        return None, None, "未找到 Windows SDK（需含 um/windows.h 与 Lib/<ver>/um/x64）。"
    sdk_root, sdk_ver = sdk

    includes = [str(toolset / "include")]
    includes += [str(sdk_root / "Include" / sdk_ver / sub) for sub in SDK_INCLUDE_SUBDIRS]
    includes = [p for p in includes if Path(p).is_dir()]

    libs = [str(toolset / "lib" / "x64")]
    libs += [str(sdk_root / "Lib" / sdk_ver / sub / "x64") for sub in SDK_LIB_SUBDIRS]
    libs = [p for p in libs if Path(p).is_dir()]

    bin_dir = toolset / "bin" / "Hostx64" / "x64"
    sdk_bin = sdk_root / "bin" / sdk_ver / "x64"

    env = dict(os.environ)
    env["INCLUDE"] = os.pathsep.join(includes)
    env["LIB"] = os.pathsep.join(libs)
    paths = [str(bin_dir)]
    if sdk_bin.is_dir():
        paths.append(str(sdk_bin))
    env["PATH"] = os.pathsep.join(paths + [env.get("PATH", "")])
    # 关闭遥测与增量 PDB 服务，避免在受限环境下额外拉起子进程。
    env["VSCMD_SKIP_SENDTELEMETRY"] = "1"

    cl_path = bin_dir / "cl.exe"
    message = f"MSVC {toolset.name} + Windows SDK {sdk_ver}"
    return env, cl_path, message


def build(debug: bool, install: bool) -> int:
    """执行构建。

    Args:
        debug: 是否生成调试构建（``/Od /Zi``）。
        install: 构建成功后是否安装到 ``core/native/bin/``。

    Returns:
        进程退出码，0 表示成功。
    """
    here = Path(__file__).resolve().parent
    # src/cpp_mica_render -> src -> native
    native_dir = here.parent.parent
    bin_dir = native_dir / "bin"

    env, cl_path, message = build_env()
    if env is None or cl_path is None:
        print(f"错误：{message}")
        return 1
    print(f"使用工具链：{message}")

    obj_dir = here / "build"
    obj_dir.mkdir(exist_ok=True)

    args: List[str] = [
        str(cl_path),
        "/nologo",
        "/std:c++17",
        "/utf-8",  # 源码为 UTF-8，避免 GBK 代码页下的 C4819
        "/EHsc",
        "/W4",
        "/wd4100",  # 未引用的形参（Win32 风格签名中常见）
        "/DMICA_RENDER_BUILD",
        "/DUNICODE",
        "/D_UNICODE",
        "/MT",  # 静态 CRT：产物不依赖 VC++ 运行库
        f"/Fo{obj_dir}\\",
    ]
    if debug:
        args += ["/Od", "/Zi", "/D_DEBUG", f"/Fd{obj_dir}\\mica_render.pdb"]
    else:
        args += ["/O2", "/DNDEBUG"]

    args += [str(here / src) for src in SOURCES]
    args += ["/link", "/DLL", f"/OUT:{here / TARGET_NAME}", "/INCREMENTAL:NO"]
    if debug:
        args.append("/DEBUG")
    args += LIBS

    print("开始编译 ...")
    proc = subprocess.run(
        args,
        cwd=str(here),
        env=env,
        capture_output=True,
        text=True,
        errors="replace",
    )
    sys.stdout.write(proc.stdout)
    if proc.stderr.strip():
        sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        print(f"编译失败，退出码 {proc.returncode}")
        return proc.returncode

    dll = here / TARGET_NAME
    if not dll.exists():
        print("编译似乎成功但未找到产物 DLL。")
        return 1
    size_kb = dll.stat().st_size / 1024.0
    print(f"构建成功：{dll} ({size_kb:.1f} KB)")

    if install:
        bin_dir.mkdir(parents=True, exist_ok=True)
        target = bin_dir / TARGET_NAME
        shutil.copy2(dll, target)
        print(f"已安装到：{target}")
        # 清理链接期副产物，避免污染源码目录
        for ext in (".exp", ".lib"):
            stray = here / (Path(TARGET_NAME).stem + ext)
            if stray.exists():
                os.remove(stray)
    return 0


def main() -> int:
    """命令行入口。

    Returns:
        进程退出码。
    """
    parser = argparse.ArgumentParser(description="构建 mica_render.dll")
    parser.add_argument("--debug", action="store_true", help="生成调试构建")
    parser.add_argument("--no-install", action="store_true", help="不安装到 core/native/bin/")
    args = parser.parse_args()
    if os.name != "nt":
        print("错误：本库仅支持 Windows。")
        return 1
    return build(debug=args.debug, install=not args.no_install)


if __name__ == "__main__":
    raise SystemExit(main())
