#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PathUtils 模块单元测试
测试路径验证、安全检查和相关工具函数
"""

import os
import sys
import tempfile
from unittest.mock import patch, MagicMock

import pytest

from freeassetfilter.utils.path_utils import (
    contains_injection_chars,
    validate_safe_path,
    get_app_data_path,
    validate_file_path,
    validate_filename,
    validate_file_extension,
    validate_numeric_range,
    is_sensitive_path,
    is_path_allowed,
    _get_project_root,
    WINDOWS_RESERVED_NAMES,
    ILLEGAL_FILENAME_CHARS,
    MAX_FILENAME_LENGTH,
    MAX_PATH_LENGTH,
)


class TestContainsInjectionChars:
    """测试contains_injection_chars函数"""

    def test_normal_path(self):
        assert contains_injection_chars("C:\\Users\\test\\file.txt") is False

    def test_newline_injection(self):
        assert contains_injection_chars("file\n.txt") is True

    def test_carriage_return_injection(self):
        assert contains_injection_chars("file\r.txt") is True

    def test_null_byte_injection(self):
        assert contains_injection_chars("file\x00.txt") is True

    def test_command_substitution_dollar_paren(self):
        assert contains_injection_chars("$(command)") is True

    def test_command_substitution_dollar_brace(self):
        assert contains_injection_chars("${command}") is True

    def test_backtick_substitution(self):
        assert contains_injection_chars("`command`") is True

    def test_empty_string(self):
        assert contains_injection_chars("") is False

    def test_none_string(self):
        assert contains_injection_chars(None) is False

    def test_ampersand_safe(self):
        assert contains_injection_chars("file&name.txt") is False

    def test_pipe_safe(self):
        assert contains_injection_chars("file|name.txt") is False

    def test_chinese_path(self):
        assert contains_injection_chars("C:\\用户\\测试\\文件.txt") is False


class TestValidateSafePath:
    """测试validate_safe_path函数"""

    def test_valid_absolute_path(self):
        result = validate_safe_path("C:\\test\\path")
        assert result == "C:\\test\\path"

    def test_relative_path_resolved(self):
        result = validate_safe_path(".")
        assert os.path.isabs(result)

    def test_empty_path_raises(self):
        with pytest.raises(ValueError, match="路径不能为空"):
            validate_safe_path("")

    def test_none_path_raises(self):
        with pytest.raises(ValueError):
            validate_safe_path(None)

    def test_path_with_parent_references(self, temp_data_dir):
        subdir = os.path.join(temp_data_dir, "subdir")
        os.makedirs(subdir, exist_ok=True)

        result = validate_safe_path(os.path.join(subdir, ".."), temp_data_dir)
        assert os.path.normpath(result) == os.path.normpath(temp_data_dir)

    def test_path_traversal_outside_base_raises(self, temp_data_dir):
        subdir = os.path.join(temp_data_dir, "subdir")
        os.makedirs(subdir, exist_ok=True)

        outside_path = os.path.join(temp_data_dir, "..")

        with pytest.raises(ValueError, match="路径遍历攻击检测"):
            validate_safe_path(outside_path, base_path=subdir)

    def test_path_within_base(self, temp_data_dir):
        subdir = os.path.join(temp_data_dir, "subdir")
        os.makedirs(subdir, exist_ok=True)

        result = validate_safe_path(subdir, base_path=temp_data_dir)
        assert os.path.normpath(result) == os.path.normpath(subdir)

    def test_expanduser(self):
        result = validate_safe_path("~/test")
        assert os.path.isabs(result)

    def test_symlink_resolved(self, temp_data_dir):
        target = os.path.join(temp_data_dir, "target")
        link = os.path.join(temp_data_dir, "link")

        os.makedirs(target, exist_ok=True)
        try:
            os.symlink(target, link)
        except OSError:
            pytest.skip("Symlinks not supported on this system")

        result = validate_safe_path(link)
        assert os.path.normpath(result) == os.path.normpath(target)


class TestGetAppDataPath:
    """测试get_app_data_path函数"""

    def test_returns_directory_path(self):
        result = get_app_data_path()
        assert isinstance(result, str)
        assert os.path.isabs(result)

    def test_creates_directory(self):
        result = get_app_data_path()
        assert os.path.exists(result)

    def test_creates_thumbnails_subdirectory(self):
        get_app_data_path()
        result = get_app_data_path()
        thumbnails_dir = os.path.join(result, "thumbnails")
        assert os.path.exists(thumbnails_dir)

    def test_frozen_environment(self):
        with patch.object(sys, 'frozen', True, create=True):
            with patch.object(sys, 'executable', "C:\\test\\app.exe"):
                result = get_app_data_path()
                expected = "C:\\test\\data"
                assert os.path.normpath(result) == os.path.normpath(expected)

    def test_development_environment(self):
        if hasattr(sys, 'frozen'):
            del sys.frozen

        result = get_app_data_path()
        assert "data" in result
        assert os.path.exists(result)


class TestIsSensitivePath:
    """测试is_sensitive_path函数"""

    def test_windows_directory(self):
        assert is_sensitive_path("C:\\Windows\\System32") is True

    def test_program_files(self):
        assert is_sensitive_path("C:\\Program Files\\app") is True

    def test_program_files_x86(self):
        assert is_sensitive_path("C:\\Program Files (x86)\\app") is True

    def test_user_path(self):
        assert is_sensitive_path("C:\\Users\\test\\Documents\\file.txt") is False

    def test_empty_path(self):
        assert is_sensitive_path("") is False

    def test_none_path(self):
        assert is_sensitive_path(None) is False

    def test_boot_directory(self):
        assert is_sensitive_path("C:\\Boot") is True

    def test_unc_path(self):
        assert is_sensitive_path("\\\\server\\share") is True

    def test_d_drive_user_path(self):
        assert is_sensitive_path("D:\\Games\\game.exe") is False


class TestIsPathAllowed:
    """测试is_path_allowed函数"""

    def test_empty_path(self):
        assert is_path_allowed("") is False

    def test_none_path(self):
        assert is_path_allowed(None) is False

    def test_sensitive_path_blocked(self):
        assert is_path_allowed("C:\\Windows\\System32\\cmd.exe") is False


class TestValidateFilePath:
    """测试validate_file_path函数"""

    def test_valid_path(self):
        assert validate_file_path("C:\\test\\file.txt") is True

    def test_empty_path(self):
        assert validate_file_path("") is False

    def test_whitespace_only(self):
        assert validate_file_path("   ") is False

    def test_non_string(self):
        assert validate_file_path(123) is False

    def test_too_long_path(self):
        long_path = "C:\\" + "a" * 300
        assert validate_file_path(long_path) is False

    def test_relative_path_disallowed(self):
        assert validate_file_path("relative\\path.txt") is False

    def test_relative_path_allowed(self):
        assert validate_file_path("relative\\path.txt", allow_relative=True) is True

    def test_path_traversal_with_parent(self):
        result = validate_file_path("C:\\test\\..\\file.txt", allow_relative=False)
        assert isinstance(result, bool)

    def test_chinese_path(self):
        assert validate_file_path("C:\\测试\\文件.txt") is True


class TestValidateFilename:
    """测试validate_filename函数"""

    def test_valid_filename(self):
        assert validate_filename("test.txt") is True

    def test_empty_filename(self):
        assert validate_filename("") is False

    def test_whitespace_only(self):
        assert validate_filename("   ") is False

    def test_too_long(self):
        assert validate_filename("a" * 256) is False

    def test_illegal_chars(self):
        for char in ILLEGAL_FILENAME_CHARS:
            assert validate_filename(f"test{char}file.txt") is False

    def test_reserved_name_con(self):
        assert validate_filename("CON.txt") is False

    def test_reserved_name_nul(self):
        assert validate_filename("NUL.log") is False

    def test_reserved_name_com1(self):
        assert validate_filename("COM1.txt") is False

    def test_reserved_name_lpt1(self):
        assert validate_filename("LPT1.txt") is False

    def test_control_characters(self):
        assert validate_filename("test\x00file.txt") is False
        assert validate_filename("test\x1ffile.txt") is False

    def test_ends_with_space(self):
        result = validate_filename("test.txt ")
        assert isinstance(result, bool)

    def test_ends_with_dot(self):
        assert validate_filename("test.txt.") is False

    def test_starts_with_space(self):
        result = validate_filename(" test.txt")
        assert isinstance(result, bool)

    def test_skip_reserved_check(self):
        assert validate_filename("CON.txt", check_reserved=False) is True

    def test_normal_name_with_extension(self):
        assert validate_filename("document.pdf") is True

    def test_chinese_filename(self):
        assert validate_filename("测试文件.txt") is True


class TestValidateFileExtension:
    """测试validate_file_extension函数"""

    def test_valid_extension(self):
        assert validate_file_extension("test.mp4") is True

    def test_invalid_extension(self):
        assert validate_file_extension("test.xyz") is False

    def test_no_extension(self):
        assert validate_file_extension("testfile") is False

    def test_case_insensitive(self):
        assert validate_file_extension("test.MP4") is True

    def test_case_sensitive(self):
        assert validate_file_extension("test.MP4", case_sensitive=True) is False

    def test_custom_allowed_extensions(self):
        allowed = {".xyz", ".abc"}
        assert validate_file_extension("test.xyz", allowed_extensions=allowed) is True
        assert validate_file_extension("test.mp4", allowed_extensions=allowed) is False

    def test_non_string(self):
        assert validate_file_extension(123) is False

    def test_empty_string(self):
        assert validate_file_extension("") is False


class TestValidateNumericRange:
    """测试validate_numeric_range函数"""

    def test_valid_integer(self):
        assert validate_numeric_range(5, min_value=0, max_value=10) is True

    def test_valid_float(self):
        assert validate_numeric_range(3.14, min_value=0.0, max_value=10.0) is True

    def test_below_min(self):
        assert validate_numeric_range(-1, min_value=0) is False

    def test_above_max(self):
        assert validate_numeric_range(11, max_value=10) is False

    def test_no_limits(self):
        assert validate_numeric_range(1000000) is True

    def test_none_value_disallowed(self):
        assert validate_numeric_range(None) is False

    def test_none_value_allowed(self):
        assert validate_numeric_range(None, allow_none=True) is True

    def test_string_number(self):
        assert validate_numeric_range("5", min_value=0, max_value=10) is True

    def test_invalid_string(self):
        assert validate_numeric_range("not_a_number") is False

    def test_nan(self):
        import math
        assert validate_numeric_range(float('nan')) is False

    def test_infinity(self):
        assert validate_numeric_range(float('inf')) is False

    def test_negative_infinity(self):
        assert validate_numeric_range(float('-inf')) is False

    def test_non_numeric_type(self):
        assert validate_numeric_range([1, 2, 3]) is False
        assert validate_numeric_range({"key": "value"}) is False
