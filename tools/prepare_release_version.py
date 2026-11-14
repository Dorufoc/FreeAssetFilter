#!/usr/bin/env python3
"""为 CI 发布构建准备 ``SPKVERSION``。

通道语义
--------
``nightly``
    把 ``SPKVERSION`` 第一行改写为 ``<原版本>.nightly-<YYYYMMDD>``（保留原有的
    ``v`` 前缀），第二行（构建日期）改写为构建当天的 ``YYYY-MM-DD``。
    改写只发生在工作区，CI 不会提交它。

``stable``
    保持 ``SPKVERSION`` 原样——正式版版本号由人工在文件里维护。

除改写文件外，本脚本还给出发布用的元数据（GitHub Actions 的 tag、展示版本号）。

结果写到 ``--github-output`` 指定的文件（GitHub Actions 的 ``$GITHUB_OUTPUT``）。
安装器需要的 4 段数值版本（``VIProductVersion``）由
``packaging/installer/build.ps1`` 从 ``SPKVERSION`` 统一计算，这里不重复实现。

用法::

    python tools/prepare_release_version.py --channel nightly
    python tools/prepare_release_version.py --channel stable --dry-run
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

#: 构建日期使用的时区（Asia/Shanghai，固定 UTC+8，无夏令时）。
BUILD_TZ = timezone(timedelta(hours=8))

#: 已存在的 nightly 后缀（保证重复执行幂等）。
_NIGHTLY_SUFFIX = re.compile(r"\.nightly-\d{8}$")


def strip_leading_v(value: str) -> str:
    """去掉一个前导 ``v``/``V``。"""
    return value[1:] if value[:1] in {"v", "V"} else value


def read_version_lines(path: Path) -> list[str]:
    """读取 ``SPKVERSION`` 的所有行（保留原有顺序与空行位置）。"""
    if not path.is_file():
        raise SystemExit(f"找不到版本文件：{path}")
    return path.read_text(encoding="utf-8-sig").splitlines()


def prepare(project_root: Path, channel: str, build_day: date, dry_run: bool) -> dict[str, str]:
    """改写（或保留）``SPKVERSION`` 并返回发布用的版本元数据。"""
    version_path = project_root / "SPKVERSION"
    lines = read_version_lines(version_path)
    if not lines:
        raise SystemExit(f"版本文件为空：{version_path}")

    original_version = lines[0].strip()
    if not original_version:
        raise SystemExit(f"版本文件第一行（版本号）为空：{version_path}")

    # 去掉可能已存在的 nightly 后缀，保证同一份 checkout 反复执行结果一致。
    base = _NIGHTLY_SUFFIX.sub("", strip_leading_v(original_version))
    has_v_prefix = original_version[:1] in {"v", "V"}
    prefix = original_version[:1] if has_v_prefix else ""

    build_date_iso = build_day.isoformat()
    build_date_compact = build_day.strftime("%Y%m%d")

    if channel == "nightly":
        display_version = f"{base}.nightly-{build_date_compact}"
        new_first_line = f"{prefix}{display_version}"
        changed = new_first_line != original_version or (
            len(lines) > 1 and lines[1].strip() != build_date_iso
        )
        if not dry_run:
            updated = [new_first_line, build_date_iso] + lines[2:]
            text = "\n".join(updated).rstrip("\n") + "\n"
            # 注意：Path.write_text(newline=...) 是 Python 3.10+ 才支持的参数，
            # 而打包环境固定为 Python 3.9，因此这里用 open() 显式指定换行符。
            with version_path.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
    else:
        # 正式版：版本号与日期都由人工维护，此处只读取。
        display_version = base
        changed = False

    result = {
        "channel": channel,
        "version": display_version,
        "version_tag": f"{prefix}{display_version}",
        "build_date": build_date_iso,
        "build_date_compact": build_date_compact,
        "prerelease": "true" if channel == "nightly" else "false",
        "version_file_changed": "true" if changed else "false",
    }
    return result


def write_github_output(path: Path, values: dict[str, str]) -> None:
    """把结果按 ``key=value`` 写进 GitHub Actions 的 GITHUB_OUTPUT 文件。"""
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="为 CI 发布构建准备 SPKVERSION")
    parser.add_argument("--channel", choices=("nightly", "stable"), default="nightly")
    parser.add_argument(
        "--date",
        default="",
        help="构建日期 YYYYMMDD 或 YYYY-MM-DD；缺省用 Asia/Shanghai 的当天",
    )
    parser.add_argument("--root", default="", help="项目根目录（默认为脚本上一级）")
    parser.add_argument("--github-output", default="", help="GITHUB_OUTPUT 文件路径")
    parser.add_argument("--dry-run", action="store_true", help="只计算，不改写 SPKVERSION")
    args = parser.parse_args(argv)

    project_root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent

    if args.date:
        raw = args.date.strip()
        try:
            if len(raw) == 8 and raw.isdigit():
                build_day = datetime.strptime(raw, "%Y%m%d").date()
            else:
                build_day = date.fromisoformat(raw)
        except ValueError:
            print(f"非法日期：{args.date}", file=sys.stderr)
            return 2
    else:
        build_day = datetime.now(BUILD_TZ).date()

    values = prepare(project_root, args.channel, build_day, args.dry_run)

    print(f"channel         : {values['channel']}")
    print(f"version         : {values['version']}")
    print(f"version_tag     : {values['version_tag']}")
    print(f"build_date      : {values['build_date']}")
    print(f"prerelease      : {values['prerelease']}")
    print(f"file_changed    : {values['version_file_changed']}{' (dry-run)' if args.dry_run else ''}")

    if args.github_output:
        write_github_output(Path(args.github_output), values)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
