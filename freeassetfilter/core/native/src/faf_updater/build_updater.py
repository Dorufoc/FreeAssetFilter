"""Build ``faf_updater.exe`` and install it into ``core/native/bin/``.

Usage::

    python build_updater.py               # Release build + install
    python build_updater.py --debug       # Debug build + install
    python build_updater.py --no-install  # Build only

The binary is a console-subsystem sidecar started by the Python bridge with
``CREATE_NO_WINDOW``. It is always rebuilt from source here; the checked-in
artifact only exists so a clone can run without a Rust toolchain.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

TARGET_NAME = "faf_updater.exe"


def build(debug: bool, install: bool) -> int:
    """Builds the updater binary.

    Args:
        debug: Build the unoptimized debug profile instead of release.
        install: Copy the produced executable into ``core/native/bin/``.

    Returns:
        Process exit code, 0 on success.
    """
    here = Path(__file__).resolve().parent
    # src/faf_updater -> src -> native
    native_dir = here.parent.parent
    bin_dir = native_dir / "bin"

    command: list[str] = ["cargo", "build", "--manifest-path", str(here / "Cargo.toml")]
    if not debug:
        command.append("--release")

    print(f"开始构建：{' '.join(command)}")
    process = subprocess.run(command, cwd=str(here))
    if process.returncode != 0:
        print(f"构建失败，cargo 退出码 {process.returncode}")
        return process.returncode or 1

    profile = "debug" if debug else "release"
    executable = here / "target" / profile / TARGET_NAME
    if not executable.exists():
        print(f"构建似乎成功但未找到产物：{executable}")
        return 1

    size = executable.stat().st_size
    print(f"构建成功：{executable} ({size} bytes / {size / (1024 * 1024):.2f} MiB)")

    if install:
        bin_dir.mkdir(parents=True, exist_ok=True)
        target = bin_dir / TARGET_NAME
        shutil.copy2(executable, target)
        print(f"已安装到：{target} ({target.stat().st_size} bytes)")

    return 0


def main() -> int:
    """Command-line entry point.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description="构建 faf_updater.exe")
    parser.add_argument("--debug", action="store_true", help="使用 debug profile 构建")
    parser.add_argument("--no-install", action="store_true", help="不复制到 core/native/bin/")
    args = parser.parse_args()

    if os.name != "nt":
        print("错误：faf_updater 仅支持 Windows。")
        return 1
    return build(debug=args.debug, install=not args.no_install)


if __name__ == "__main__":
    raise SystemExit(main())
