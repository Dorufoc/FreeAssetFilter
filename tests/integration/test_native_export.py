"""在 Windows 上以随仓 DLL 核对储存池导出的真实复制回执和落盘内容。"""

import os
from pathlib import Path

import pytest

from sopeek._paths import native_bin_dir
from sopeek.core.native import api as native_api
from sopeek.services.export_copy import copy_exports


@pytest.mark.integration
@pytest.mark.skipif(os.name != "nt", reason="spk_core.dll 仅支持 Windows")
def test_bundled_dll_exports_same_named_originals(tmp_path):
    assert native_api.supports("copy")
    assert Path(native_api.bridge()._dll._name).samefile(native_bin_dir() / "spk_core.dll")

    sources = [tmp_path / folder / "封面.txt" for folder in ("素材 A", "素材 B")]
    contents = [b"first original", b"second original"]
    for src, content in zip(sources, contents):
        src.parent.mkdir()
        src.write_bytes(content)
    destination = tmp_path / "交付"
    destination.mkdir()
    (destination / "封面.txt").write_bytes(b"existing")

    receipts = []

    def record_native_copy(paths, staging):
        receipt = native_api.copy_files(paths, staging)
        receipts.append(receipt)
        return receipt

    progress = []
    result = copy_exports(
        [{"path": str(path)} for path in sources], str(destination),
        categorized=False, should_stop=None, progress=progress.append,
        native_copy=record_native_copy, batch_size=32,
    )
    assert result == (2, 0, [])
    assert progress == [1, 2]
    # 第二个同名原件由服务单独暂存，不能让原生后端覆盖第一份。
    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt is not None and receipt["failed"] == []
    assert [(row["src"], row["size"]) for row in receipt["copied"]] == [
        (str(sources[0]), len(contents[0]))
    ]
    assert {f.name: f.read_bytes() for f in destination.iterdir()} == {
        "封面.txt": b"existing", "封面_1.txt": contents[0], "封面_2.txt": contents[1],
    }
    assert [src.read_bytes() for src in sources] == contents
