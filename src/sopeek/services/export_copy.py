"""Copy selected originals to a private directory on the target volume, then publish each complete item."""
from __future__ import annotations

import ctypes
import errno
import os
import shutil
import sys
import tempfile
from functools import lru_cache
from itertools import groupby, islice
from pathlib import Path

from sopeek.utils.app_logger import warning


@lru_cache(maxsize=1)
def _exclusive_rename():
    """Return the host's atomic no-replace rename operation for both files and directories."""
    if os.name == "nt":
        # On Windows os.rename raises FileExistsError for an existing destination.
        return os.rename
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        rename = libc.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]

        def call(src, dst):
            return rename(src, dst, 0x00000004)  # <stdio.h>: RENAME_EXCL
    elif sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        rename = libc.renameat2
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]

        def call(src, dst):
            return rename(-100, src, -100, dst, 1)  # AT_FDCWD, RENAME_NOREPLACE
    else:
        raise OSError(errno.ENOTSUP, "目标平台不支持防覆盖重命名")

    def move(src, dst):
        if call(os.fsencode(src), os.fsencode(dst)) != 0:
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code), str(dst))

    return move


def _publish(staged: Path, directory: Path, name: str) -> None:
    move = _exclusive_rename()
    stem, suffix = os.path.splitext(name)
    index = 0
    while True:
        dst = directory / (name if index == 0 else f"{stem}_{index}{suffix}")
        try:
            move(staged, dst)
            return
        except OSError as exc:
            if exc.errno not in (errno.EEXIST, errno.ENOTEMPTY):
                raise
            index += 1


def _stage_native(batch, staging, native_copy):
    """Select unique source names using the volume's own name comparison rules."""
    native_items = {}
    if native_copy is None:
        return native_items, None
    claims = staging / "names"
    claims.mkdir()
    native_dir = staging / "native"
    native_dir.mkdir()
    for index, info in enumerate(batch):
        src = str(info.get("path", ""))
        basename = Path(src).name
        if not basename:
            continue
        try:
            # Native derives its output name from src. This separate claim prevents
            # collisions inside native_dir without creating a placeholder in the payload.
            with (claims / basename).open("xb"):
                pass
        except FileExistsError:
            continue
        except OSError:
            # Let the per-item Python copy return a useful error for this source.
            continue
        native_items[index] = src
    if native_items:
        try:
            receipt = native_copy(list(native_items.values()), str(native_dir))
            if receipt is not None:
                return native_items, receipt
        except Exception:  # noqa: BLE001 - the bridge can fail after partially writing.
            warning("native 复制失败，回退 Python 复制路径")
    return {}, None


def copy_exports(files, target_dir, categorized, should_stop, progress, native_copy, batch_size):
    success = 0
    errors = []

    def destination(info):
        src = Path(str(info.get("path", "")))
        directory = Path(target_dir)
        if categorized:
            category = src.parent.name or "未分类"
            if category == "..":
                return directory, "分类目录名称无效"
            directory /= category
        # Check before creating even a category folder or a temporary directory
        # under the selected original. Pool metadata may predate a file type change.
        try:
            resolved = directory.resolve()
            if categorized and not resolved.is_relative_to(Path(target_dir).resolve()):
                return directory, "分类目录位于所选目标以外"
            if resolved.is_relative_to(src.resolve()):
                return directory, "无法将文件夹复制到它自身或其子目录"
        except (OSError, RuntimeError, ValueError) as exc:
            return directory, str(exc)
        return directory, None

    for (directory, path_error), group in groupby(files, destination):
        while batch := list(islice(group, batch_size)):
            if should_stop is not None and should_stop():
                return success, len(errors), errors
            if path_error:
                for info in batch:
                    if should_stop is not None and should_stop():
                        return success, len(errors), errors
                    errors.append(f"{info.get('path', '')}: {path_error}")
                    progress(success + len(errors))
                continue
            completed = 0
            try:
                if categorized:
                    directory.mkdir(exist_ok=True)
                with tempfile.TemporaryDirectory(prefix=".sopeek-export-", dir=directory) as tmp:
                    staging = Path(tmp)
                    native_items, receipt = _stage_native(batch, staging, native_copy)
                    receipt = receipt or {}
                    copied = {item.get("src") for item in receipt.get("copied", [])}
                    failed = {
                        item.get("src"): item.get("error", "复制失败")
                        for item in receipt.get("failed", [])
                    }
                    for i, info in enumerate(batch):
                        if should_stop is not None and should_stop():
                            return success, len(errors), errors
                        src = str(info.get("path", ""))
                        name = info.get("display_name") or os.path.basename(src)
                        try:
                            if not name or name in (".", "..") or os.path.basename(name) != name:
                                raise ValueError("导出名称必须是单个文件名")
                            if i in native_items:
                                if src not in copied:
                                    raise OSError(failed.get(src, "native 未返回该源的复制结果"))
                                staged = staging / "native" / Path(src).name
                            else:
                                # The native bridge may have returned None after writing
                                # some bytes. Retry into a completely fresh path.
                                staged = staging / str(i)
                                if info.get("is_dir"):
                                    shutil.copytree(src, staged)
                                else:
                                    shutil.copy2(src, staged)
                            _publish(staged, directory, name)
                        except (OSError, ValueError, shutil.Error) as exc:
                            errors.append(f"{src}: {exc}")
                        else:
                            success += 1
                        completed += 1
                        progress(success + len(errors))
            except OSError as exc:
                # A staging setup failure applies to the as-yet-unprocessed members.
                # Cleanup errors after publication cannot turn delivered items into failures.
                warning(f"导出暂存目录: {exc}")
                for info in batch[completed:]:
                    if should_stop is not None and should_stop():
                        return success, len(errors), errors
                    errors.append(f"{info.get('path', '')}: {exc}")
                    progress(success + len(errors))
    return success, len(errors), errors
