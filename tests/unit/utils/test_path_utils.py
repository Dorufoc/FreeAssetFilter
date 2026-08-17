# -*- coding: utf-8 -*-
"""test_path_utils: path_utils.py 覆盖测试（todo-10, unit/utils 批 1）。

覆盖：get_resource_path 存在/缺失/路径规范化（含 CWD 缺失时向上查找），
另附纯函数校验逻辑（is_sensitive_path / contains_injection_chars /
validate_filename / validate_file_extension / validate_numeric_range /
validate_file_path / validate_dll_path 缺失场景），减少 utils 覆盖盲区。
"""

from __future__ import annotations

import os

import pytest

from freeassetfilter.utils import path_utils
from freeassetfilter.utils.path_utils import (
    contains_injection_chars,
    get_resource_path,
    is_sensitive_path,
    validate_dll_path,
    validate_file_extension,
    validate_file_path,
    validate_filename,
    validate_numeric_range,
)


class TestGetResourcePath:
    """get_resource_path 资源解析。"""

    def test_existing_root_resource(self) -> None:
        """项目根资源存在时返回可解析路径。"""
        result = get_resource_path("FAFVERSION")
        assert isinstance(result, str)
        assert os.path.exists(result)
        assert os.path.isfile(result)

    def test_existing_nested_resource(self) -> None:
        """嵌套路径资源存在时返回可解析路径。"""
        result = get_resource_path("freeassetfilter/icons/FAF-main.png")
        assert os.path.exists(result)
        assert os.path.isfile(result)

    def test_missing_resource_graceful(self) -> None:
        """缺失资源返回路径字符串且不抛异常。"""
        result = get_resource_path("no_such_dir/no_such_file.bin")
        assert isinstance(result, str)
        assert not os.path.exists(result)

    def test_result_is_absolute(self) -> None:
        """返回路径为绝对路径。"""
        result = get_resource_path("FAFVERSION")
        assert os.path.isabs(result)

    def test_dev_branch_joins_cwd(self) -> None:
        """开发环境优先拼接 CWD。"""
        result = get_resource_path("FAFVERSION")
        assert result == os.path.join(os.path.abspath("."), "FAFVERSION")

    def test_walks_up_when_cwd_missing(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        """CWD 不含资源时向上回溯到项目根目录。"""
        monkeypatch.chdir(tmp_path)
        result = get_resource_path("FAFVERSION")
        assert os.path.exists(result)
        assert result == os.path.join(path_utils._get_project_root(), "FAFVERSION")


class TestIsSensitivePath:
    """is_sensitive_path 敏感路径判定。"""

    @pytest.mark.parametrize(
        ("candidate", "expected"),
        [
            (r"C:\Windows\System32", True),
            (r"C:\Program Files\SomeApp", True),
            (r"C:\Program Files (x86)\App", True),
            (r"\\server\share\file.txt", True),  # UNC
            ("", False),
            ("relative/path.txt", False),
            (r"D:\Projects\SafeDir\file.txt", False),
        ],
        ids=["windows", "program-files", "program-files-x86", "unc", "empty", "relative", "safe-drive"],
    )
    def test_sensitive_matrix(self, candidate: str, expected: bool) -> None:
        """敏感路径判定矩阵。

        Args:
            candidate: 待判定路径。
            expected: 期望结果。
        """
        assert is_sensitive_path(candidate) is expected


class TestInjectionChars:
    """contains_injection_chars 命令注入字符检测。"""

    def test_safe_path_false(self) -> None:
        """安全路径返回 False。"""
        assert contains_injection_chars("safe/path.txt") is False

    @pytest.mark.parametrize(
        "candidate",
        ["a\nb", "a\rb", "a\x00b", "$(cmd)", "${cmd}", "`cmd`"],
        ids=["newline", "carriage-return", "null-byte", "dollar-paren", "dollar-brace", "backtick"],
    )
    def test_dangerous_patterns_true(self, candidate: str) -> None:
        """危险控制字符与命令替换模式返回 True。

        Args:
            candidate: 路径字符串。
        """
        assert contains_injection_chars(candidate) is True

    def test_empty_false(self) -> None:
        """空路径返回 False。"""
        assert contains_injection_chars("") is False


class TestValidateFilename:
    """validate_filename 文件名校验。"""

    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            ("photo.png", True),
            ("my file (1).txt", True),
            ("中文文件名.png", True),
            ("", False),
            ("   ", False),
            ("bad:name.txt", False),
            ("bad?name.txt", False),
            ("bad*name.txt", False),
            ("CON", False),
            ("nul.txt", False),
            ("trailing. ", False),
            ("internal  space.txt", True),  # 内部空格合法（strip 已移除首尾空格）
            ("a" * 256, False),
            ("ok" * 100, True),  # 200 字符在 255 以内
        ],
        ids=["valid", "valid-space", "valid-unicode", "empty", "spaces", "colon", "question", "star",
             "reserved-con", "reserved-nul", "trailing", "internal-space", "too-long", "long-ok"],
    )
    def test_filename_matrix(self, filename: str, expected: bool) -> None:
        """文件名校验矩阵。

        Args:
            filename: 候选文件名。
            expected: 期望结果。
        """
        assert validate_filename(filename) is expected


class TestValidateFileExtension:
    """validate_file_extension 扩展名校验。"""

    def test_default_whitelist(self) -> None:
        """默认白名单大小写不敏感。"""
        assert validate_file_extension("photo.png") is True
        assert validate_file_extension("photo.PNG") is True

    def test_denied_extension(self) -> None:
        """不在白名单的扩展名被拒绝。"""
        assert validate_file_extension("archive.zip") is False

    def test_custom_whitelist(self) -> None:
        """自定义白名单生效。"""
        assert validate_file_extension("archive.zip", allowed_extensions={".zip"}) is True
        assert validate_file_extension("photo.png", allowed_extensions={".zip"}) is False

    def test_no_extension_rejected(self) -> None:
        """无扩展名被拒绝。"""
        assert validate_file_extension("no_ext") is False

    def test_case_sensitive_mode(self) -> None:
        """case_sensitive=True 时区分大小写。"""
        assert validate_file_extension("photo.PNG", case_sensitive=True) is False
        assert validate_file_extension("photo.png", case_sensitive=True) is True


class TestValidateNumericRange:
    """validate_numeric_range 数值范围校验。"""

    @pytest.mark.parametrize(
        ("value", "min_value", "max_value", "allow_none", "expected"),
        [
            (5, 0, 10, False, True),
            (0, 1, 10, False, False),
            (11, 1, 10, False, False),
            (None, 0, 10, False, False),
            (None, 0, 10, True, True),
            ("42", 0, 100, False, True),
            ("abc", None, None, False, False),
            (float("nan"), None, None, False, False),
            (float("inf"), None, None, False, False),
            (5, None, None, False, True),
        ],
        ids=["in-range", "below-min", "above-max", "none-not-allowed", "none-allowed",
             "numeric-string", "non-numeric", "nan", "inf", "unbounded"],
    )
    def test_numeric_matrix(self, value: object, min_value: object, max_value: object,
                            allow_none: bool, expected: bool) -> None:
        """数值范围校验矩阵。

        Args:
            value: 待校验数值。
            min_value: 最小值（None 无限制）。
            max_value: 最大值（None 无限制）。
            allow_none: 是否允许 None。
            expected: 期望结果。
        """
        assert validate_numeric_range(value, min_value, max_value, allow_none) is expected


class TestValidateFilePath:
    """validate_file_path 路径校验。"""

    @pytest.mark.parametrize(
        ("candidate", "expected"),
        [
            (r"D:\dir\file.txt", True),
            (r"C:\Windows\file.txt", False),  # 敏感路径
            ("relative.txt", False),  # 非绝对路径
            ("", False),
            (r"D:\dir" + "\\a" * 200 + r"\file.txt", False),  # 超长
        ],
        ids=["absolute", "sensitive", "relative", "empty", "too-long"],
    )
    def test_path_matrix(self, candidate: str, expected: bool) -> None:
        """路径校验矩阵。

        Args:
            candidate: 候选路径。
            expected: 期望结果。
        """
        assert validate_file_path(candidate) is expected


class TestValidateDllPath:
    """validate_dll_path 缺失场景。"""

    def test_missing_file_returns_false(self) -> None:
        """不存在的 DLL 返回 False。"""
        assert validate_dll_path(r"D:\definitely_missing_dir\no.dll") is False

    def test_non_dll_extension_returns_false(self) -> None:
        """非 .dll 扩展名返回 False。"""
        assert validate_dll_path(__file__) is False


# =============================================================================
# 应用数据 / 配置目录（避免真实文件系统副作用）
# =============================================================================
class TestAppDataAndConfigDirs:
    """``get_app_data_path`` / ``get_config_path`` 目录定位与缓存。"""

    def test_get_app_data_path_caches_and_creates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """首次调用后结果被缓存；返回路径以 data 结尾。"""
        from freeassetfilter.utils import path_utils

        created: list = []
        monkeypatch.setattr(path_utils, "_APP_DATA_PATH_CACHE", None)
        monkeypatch.setattr(
            "freeassetfilter.utils.path_utils.os.makedirs",
            lambda *a, **k: created.append(a),
        )
        data_dir = path_utils.get_app_data_path()
        assert data_dir.endswith(("data", "data\\"))
        assert created, "应调用 makedirs"
        assert path_utils._APP_DATA_PATH_CACHE == data_dir
        # 缓存命中：再次调用不再触发副作用
        created.clear()
        assert path_utils.get_app_data_path() == data_dir
        assert not created

    def test_get_config_path_creates_and_returns(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``get_config_path`` 返回 config 目录。"""
        from freeassetfilter.utils import path_utils

        created: list = []
        monkeypatch.setattr(
            "freeassetfilter.utils.path_utils.os.makedirs",
            lambda *a, **k: created.append(a),
        )
        config_dir = path_utils.get_config_path()
        assert config_dir.endswith(("config", "config\\"))
        assert created, "应调用 makedirs"


# =============================================================================
# 路径安全策略（白名单 / 基目录约束 / DLL 搜索）
# =============================================================================
class TestPathSafetyStrategy:
    """``is_path_allowed`` / ``is_path_within_base`` / ``validate_safe_path``。"""

    def test_is_path_allowed_empty_false(self) -> None:
        """空路径直接拒绝。"""
        from freeassetfilter.utils import path_utils

        assert path_utils.is_path_allowed("") is False
        assert path_utils.is_path_allowed(None) is False

    def test_is_path_allowed_whitelist_hit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """白名单内路径放行（monkeypatch 白名单避免真实目录探测）。"""
        from freeassetfilter.utils import path_utils

        monkeypatch.setattr(
            path_utils, "_ALLOWED_BASE_PATHS", [str(monkeypatch) or "/"]
        )
        # 用 tmp 语义：白名单设为真实存在的目录
        import tempfile

        with tempfile.TemporaryDirectory() as base:
            monkeypatch.setattr(path_utils, "_ALLOWED_BASE_PATHS", [base])
            allowed = path_utils.is_path_allowed(
                os.path.join(base, "sub", "file.txt"), strict=True
            )
            assert allowed is True

    def test_is_path_allowed_free_file_non_strict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """非严格模式：带扩展名的普通文件路径放行。"""
        from freeassetfilter.utils import path_utils

        monkeypatch.setattr(path_utils, "_ALLOWED_BASE_PATHS", [])
        monkeypatch.setattr(path_utils, "_init_allowed_paths", lambda: None)
        monkeypatch.setattr(path_utils, "is_sensitive_path", lambda p: False)
        assert path_utils.is_path_allowed(r"C:\Temp\fake-notes-v1.txt") is True
        # 严格模式：同一路径被拒绝
        assert (
            path_utils.is_path_allowed(
                r"C:\Temp\fake-notes-v1.txt", strict=True
            )
            is False
        )

    def test_is_path_within_base(self, tmp_path: object) -> None:
        """子路径在基目录内返回 True；兄弟路径返回 False。"""
        from freeassetfilter.utils import path_utils

        base = str(tmp_path)
        child = str(tmp_path / "sub" / "file.txt")
        sibling = str(tmp_path).replace("\\", "/") + "-x"
        assert path_utils.is_path_within_base(child, base) is True
        assert path_utils.is_path_within_base(base, base) is True
        assert path_utils.is_path_within_base(sibling, base) is False

    def test_validate_safe_path_empty_raises(self) -> None:
        """空路径抛 ``ValueError``。"""
        from freeassetfilter.utils import path_utils

        with pytest.raises(ValueError):
            path_utils.validate_safe_path("")

    def test_validate_safe_path_returns_absolute_without_base(
        self, tmp_path: object
    ) -> None:
        """未指定 base 时返回真实绝对路径。"""
        from freeassetfilter.utils import path_utils

        target = str(tmp_path / "a.txt")
        result = path_utils.validate_safe_path(target)
        assert result == os.path.realpath(os.path.abspath(target))

    def test_validate_safe_path_base_normalization(self, tmp_path: object) -> None:
        """base 内路径返回规范化路径；base 外抛 ``ValueError``。"""
        from freeassetfilter.utils import path_utils

        inside = str(tmp_path / "ok" / "file.txt")
        assert path_utils.validate_safe_path(
            inside, base_path=str(tmp_path)
        ) == os.path.realpath(os.path.abspath(inside))
        assert path_utils.validate_safe_path(
            str(tmp_path), base_path=str(tmp_path)
        ) == os.path.realpath(os.path.abspath(str(tmp_path)))
        with pytest.raises(ValueError):
            path_utils.validate_safe_path(
                str(tmp_path) + "-escaped", base_path=str(tmp_path)
            )

    def test_get_safe_dll_paths_prefers_core_and_root(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DLL 搜索路径优先 core 与项目根。"""
        from freeassetfilter.utils import path_utils

        monkeypatch.setattr(path_utils, "validate_dll_path", lambda p: True)
        paths = path_utils.get_safe_dll_paths("libmpv-2.dll")
        root = path_utils._get_project_root()
        assert os.path.join(root, "freeassetfilter", "core", "libmpv-2.dll") in paths
        assert os.path.join(root, "libmpv-2.dll") in paths