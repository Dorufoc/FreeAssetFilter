"""储存池导出：核对实际写出的原件及完成/取消回执。"""
from pathlib import Path
import shutil

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QProgressDialog

import sopeek.ui.layout.file_pool_layout as pool_module


@pytest.fixture
def pool(qapp):
    widget = pool_module.FilePoolLayout()
    yield widget
    widget.close()
    widget.deleteLater()


def _item(root, parent, name, data):
    source = root / parent / name
    source.parent.mkdir(exist_ok=True)
    source.write_bytes(data)
    return {"path": str(source)}


@pytest.mark.parametrize("native_returns_result", [False, True])
@pytest.mark.parametrize("categorized", [False, True])
def test_native_batch_preserves_each_source(pool, tmp_path, monkeypatch, native_returns_result, categorized):
    """原生正常返回和回退均应保留同名/别名/已有目标的全部内容。"""
    sources = [
        _item(tmp_path, "A", "Cover.png", b"first"),
        _item(tmp_path, "B", "cover.png", b"second"),
        _item(tmp_path, "C", "Cover.png", b"third"),
        _item(tmp_path, "D", "other.png", b"alias"),
    ]
    sources[-1]["display_name"] = "Cover.png"
    dest = tmp_path / "out"
    dest.mkdir()
    (dest / "Cover_1.png").write_bytes(b"existing")
    # Native accepts only source paths and the destination directory; the copy
    # overwrites matching names just like the shipping Rust backend.
    batches = []
    def native_copy(paths, directory):
        batches.append(list(paths))
        if not native_returns_result:
            return None
        for src in paths:
            shutil.copy2(src, Path(directory) / Path(src).name)
        return {"copied": [{"src": src} for src in paths], "failed": []}

    monkeypatch.setattr(pool_module.native_api, "supports", lambda cap: True)
    monkeypatch.setattr(pool_module.native_api, "copy_files", native_copy)
    copy = pool.copy_files_categorized if categorized else pool.copy_files
    assert copy(sources, str(dest)) == (4, 0, [])
    assert batches
    assert sorted(p.read_bytes() for p in dest.rglob("*") if p.is_file()) == sorted(
        [b"first", b"second", b"third", b"alias", b"existing"]
    )
    assert (dest / "Cover_1.png").read_bytes() == b"existing"
    if categorized:
        assert sorted(p.name for p in dest.iterdir() if p.is_dir()) == ["A", "B", "C", "D"]


def test_failed_file_does_not_leave_an_empty_reservation(pool, tmp_path, monkeypatch):
    monkeypatch.setattr(pool_module.native_api, "supports", lambda cap: False)
    dest = tmp_path / "out"
    dest.mkdir()
    ok, failed, errors = pool.copy_files([{"path": str(tmp_path / "missing.jpg")}], str(dest))
    assert (ok, failed) == (0, 1)
    assert "missing.jpg" in errors[0]
    assert not list(dest.iterdir())


@pytest.mark.parametrize("cancel_at,expected_title", [(0, "导出已取消"), (2, "导出已取消"), (5, "导出完成")])
def test_cancel_receipt_matches_files_on_disk(pool, qapp, tmp_path, monkeypatch, cancel_at, expected_title):
    sources = [_item(tmp_path, "素材", f"{i}.txt", bytes([i])) for i in range(5)]
    dest = tmp_path / "out"
    dest.mkdir()
    monkeypatch.setattr(pool_module.native_api, "supports", lambda cap: False)
    messages = []
    monkeypatch.setattr(pool_module, "_show_custom_dialog",
                        lambda owner, title, message, *args, **kwargs: messages.append((title, message)))

    class WorkerPool:
        def start(self, job):
            progress = pool.findChild(QProgressDialog)
            def begin():
                if cancel_at == 0:
                    progress.canceled.emit()
                job.run()
            pool.update_progress.connect(lambda n: progress.canceled.emit() if n == cancel_at else None)
            QTimer.singleShot(0, begin)

    monkeypatch.setattr(pool_module.thread_pools, "pool", lambda _: WorkerPool())
    pool._do_export(sources, str(dest), 0)
    assert sorted(x.read_bytes() for x in dest.iterdir()) == [bytes([i]) for i in range(cancel_at)]
    assert messages[-1][0] == expected_title
    if cancel_at < len(sources):
        assert f"已复制 {cancel_at} 个，失败 0 个，未处理 {5 - cancel_at} 个" in messages[-1][1]


def test_directories_do_not_merge_and_cannot_export_into_themselves(pool, tmp_path, monkeypatch):
    monkeypatch.setattr(pool_module.native_api, "supports", lambda cap: False)
    src = tmp_path / "src" / "assets"
    src.mkdir(parents=True)
    (src / "image").write_bytes(b"chosen")
    dest = tmp_path / "dest"
    (dest / "assets").mkdir(parents=True)
    (dest / "assets" / "image").write_bytes(b"previous")
    items = [{"path": str(src), "is_dir": True}]

    assert pool.copy_files(items, str(dest)) == (1, 0, [])
    assert (dest / "assets" / "image").read_bytes() == b"previous"
    assert (dest / "assets_1" / "image").read_bytes() == b"chosen"
    ok, failed, errors = pool.copy_files(items, str(src))
    assert (ok, failed) == (0, 1)
    assert errors and [p.name for p in src.iterdir()] == ["image"]


@pytest.mark.parametrize("folder", [False, True])
def test_partial_copy_failure_is_private(pool, tmp_path, monkeypatch, folder):
    src = tmp_path / "assets"
    dest = tmp_path / "out"
    dest.mkdir()
    if folder:
        src.mkdir()
    else:
        src.write_bytes(b"original")

    def fail_copy(source, staged):
        if folder:
            staged.mkdir()
            (staged / "partial").write_bytes(b"partial")
        else:
            staged.write_bytes(b"partial")
        assert not (dest / "assets").exists()
        raise OSError("copy interrupted")

    monkeypatch.setattr(pool_module.native_api, "supports", lambda cap: False)
    monkeypatch.setattr(shutil, "copytree" if folder else "copy2", fail_copy)
    ok, failed, errors = pool.copy_files([{"path": str(src), "is_dir": folder}], str(dest))
    assert (ok, failed) == (0, 1)
    assert "copy interrupted" in errors[0]
    assert not list(dest.iterdir())


@pytest.mark.parametrize("return_failure", [False, True])
def test_partial_native_directory_is_never_merged(pool, tmp_path, monkeypatch, return_failure):
    src = tmp_path / "folder"
    dest = tmp_path / "out"
    src.mkdir()
    (src / "original").write_bytes(b"original")
    dest.mkdir()
    def native_copy(paths, staging):
        partial = Path(staging) / src.name
        partial.mkdir()
        (partial / "partial").write_bytes(b"partial")
        if return_failure:
            return {"copied": [], "failed": [{"src": paths[0], "error": "I/O error"}]}
        return None

    monkeypatch.setattr(pool_module.native_api, "supports", lambda cap: True)
    monkeypatch.setattr(pool_module.native_api, "copy_files", native_copy)
    ok, failed, errors = pool.copy_files([{"path": str(src), "is_dir": True}], str(dest))
    if return_failure:
        assert (ok, failed) == (0, 1)
        assert "I/O error" in errors[0]
        assert not list(dest.iterdir())
    else:
        assert (ok, failed, errors) == (1, 0, [])
        assert [p.name for p in (dest / src.name).iterdir()] == ["original"]


def test_concurrent_exports_claim_different_names(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from sopeek.services.export_copy import copy_exports

    sources = [_item(tmp_path, name, "original", name.encode()) for name in ("A", "B")]
    dest = tmp_path / "out"
    dest.mkdir()
    copy = shutil.copy2
    ready = Barrier(2)
    def concurrent_copy(source, staged):
        copy(source, staged)
        assert not (dest / "original").exists()
        ready.wait(timeout=5)

    monkeypatch.setattr(shutil, "copy2", concurrent_copy)
    with ThreadPoolExecutor(max_workers=2) as workers:
        jobs = [workers.submit(copy_exports, [src], dest, False, None, lambda n: None,
                               None, 32) for src in sources]
        assert [job.result() for job in jobs] == [(1, 0, [])] * 2
    assert sorted(p.read_bytes() for p in dest.iterdir()) == [b"A", b"B"]


def test_forced_exit_does_not_publish_unfinished_copy(tmp_path):
    import os
    import subprocess
    import sys
    import textwrap

    src = tmp_path / "assets.bin"
    src.write_bytes(b"complete original")
    dest = tmp_path / "out"
    dest.mkdir()
    code = textwrap.dedent("""
        import os, shutil, sys
        from sopeek.services.export_copy import copy_exports
        def interrupt(source, staged):
            staged.write_bytes(b"partial")
            os._exit(43)
        shutil.copy2 = interrupt
        copy_exports([{"path": sys.argv[1]}], sys.argv[2], False, None, print, None, 32)
    """)
    env = dict(os.environ, PYTHONPATH=str(Path(pool_module.__file__).resolve().parents[3]))
    result = subprocess.run([sys.executable, "-c", code, str(src), str(dest)], env=env, timeout=15)
    assert result.returncode == 43
    assert src.read_bytes() == b"complete original"
    assert all(p.name.startswith(".sopeek-export-") for p in dest.iterdir())
    assert not (dest / src.name).exists()


def test_categorized_copy_into_original_does_not_create_a_category(pool, tmp_path):
    src = tmp_path / "assets"
    src.mkdir()
    ok, failed, errors = pool.copy_files_categorized([{"path": str(src), "is_dir": True}], str(src))
    assert (ok, failed) == (0, 1)
    assert "子目录" in errors[0]
    assert not list(src.iterdir())
