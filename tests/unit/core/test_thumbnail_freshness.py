"""Exercise disk, UI, and decoder cache hits using regenerated source material."""

import hashlib
import os
from pathlib import Path

import pytest
from PIL import Image


@pytest.fixture
def manager(tmp_path, monkeypatch):
    from sopeek.core.managers.thumbnail_manager import get_thumbnail_manager

    manager = get_thumbnail_manager()
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr(manager, "_thumb_dir", str(cache))
    return manager


def rgb(path):
    with Image.open(path) as image:
        return image.convert("RGB").getpixel((0, 0))


def test_replacement_refreshes_disk_batch_and_qt_icon(manager, tmp_path, qapp):
    from sopeek.services.file_icon_manager import FileIconManager

    source = tmp_path / "样 本.bmp"
    other = tmp_path / "第二目录" / source.name
    other.parent.mkdir()
    Image.new("RGB", (48, 48), "black").save(source)
    Image.new("RGB", (48, 48), "blue").save(other)
    original = source.stat()
    first = manager.create_thumbnail(str(source))
    assert rgb(first) == (0, 0, 0)
    blue = manager.create_thumbnail(str(other))
    assert rgb(blue)[2] > 245
    assert manager.filter_pending_media([str(source), str(other)]) == []

    icons = FileIconManager()
    info = {"is_dir": False, "suffix": "bmp", "path": str(source)}

    def icon_color():
        return icons.get_icon_pixmap(info, 48, 1).toImage().pixelColor(0, 0)

    assert icon_color().red() == 0
    replacement = source.with_name("replacement.bmp")
    Image.new("RGB", (48, 48), "red").save(replacement)
    os.utime(replacement, ns=(original.st_atime_ns, original.st_mtime_ns))
    os.replace(replacement, source)
    assert source.stat().st_size == original.st_size

    assert manager.get_existing_thumbnail_path(str(source)) is None
    assert manager.filter_pending_media([str(source), str(other)]) == [str(source)]
    assert manager.create_thumbnails_batch([str(source)]) == (1, 1)
    current = manager.get_existing_thumbnail_path(str(source))
    assert current != first
    assert rgb(current)[0] > 245
    assert icon_color().red() > 245
    assert manager.get_existing_thumbnail_path(str(other)) == blue


def test_old_path_only_cache_and_missing_source(manager, tmp_path):
    source = tmp_path / "original.bmp"
    Image.new("RGB", (48, 48), "red").save(source)
    old = hashlib.md5(str(source).encode("utf-8")).hexdigest()[:16] + ".png"
    Image.new("RGB", (48, 48), "blue").save(Path(manager.get_thumbnail_dir()) / old)
    assert manager.get_existing_thumbnail_path(str(source)) is None
    assert rgb(manager.create_thumbnail(str(source)))[0] > 245
    source.unlink()
    assert manager.get_existing_thumbnail_path(str(source)) is None


@pytest.mark.parametrize("batch", [False, True])
def test_changed_during_decode_is_not_published(manager, tmp_path, monkeypatch, batch):
    source = tmp_path / "editing.bmp"
    Image.new("RGB", (48, 48), "black").save(source)
    create_image = manager._create_image_thumbnail
    monkeypatch.setattr(manager, "_is_native_available", lambda: False)

    def replace_after_decode(path, destination):
        result = create_image(path, destination)
        Image.new("RGB", (32, 32), "blue").save(path)
        return result

    monkeypatch.setattr(manager, "_create_image_thumbnail", replace_after_decode)
    if batch:
        assert manager.create_thumbnails_batch([str(source)]) == (0, 1)
    else:
        assert manager.create_thumbnail(str(source)) is None
    assert manager.get_existing_thumbnail_path(str(source)) is None


def test_svg_in_memory_render_observes_immediate_edit(manager, tmp_path, qapp):
    source = tmp_path / "swatch.svg"
    template = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><rect width="20" height="20" fill="{}"/></svg>'
    source.write_text(template.format("#000000"))
    assert rgb(manager.create_thumbnail(str(source))) == (0, 0, 0)
    source.write_text(template.format("#ff0000"))
    assert rgb(manager.create_thumbnail(str(source)))[0] > 245


def test_native_cache_is_cleared_before_decoding_replacement():
    from unittest.mock import Mock

    from sopeek.core.managers.thumbnail_manager import _native_source_versions

    bridge = Mock()
    bridge.clear_cache.return_value = True
    for key in ["first", "first", "second"]:
        with _native_source_versions(bridge, {"native-fixture": key}):
            assert bridge.clear_cache.call_count == (1 if key == "second" else 0)


def test_pool_card_refreshes_when_new_thumbnail_is_ready(manager, tmp_path, qapp):
    from sopeek.services.file_icon_manager import FileIconManager
    from sopeek.ui.layout.file_pool_layout import FilePoolLayout

    source = tmp_path / "pooled.bmp"
    Image.new("RGB", (40, 40), "black").save(source)
    assert manager.create_thumbnail(str(source))
    pool = FilePoolLayout()
    try:
        pool.add_file({"name": source.name, "path": str(source), "suffix": "bmp", "is_dir": False})
        card = pool._card_widgets[str(source)]
        assert card._media_pixmap.toImage().pixelColor(0, 0).red() == 0
        Image.new("RGB", (45, 45), "red").save(source)
        assert manager.create_thumbnail(str(source))
        FileIconManager().thumbnails_changed.emit([str(source)])
        assert card._media_pixmap.toImage().pixelColor(0, 0).red() > 245
    finally:
        pool.close()
        pool.deleteLater()
