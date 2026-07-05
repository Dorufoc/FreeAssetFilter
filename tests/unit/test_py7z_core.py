#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

Py7zCore 模块单元测试
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from freeassetfilter.core.py7z_core import (
    Py7zCore,
    get_7z_core,
    list_archive,
    is_encrypted,
    get_archive_type,
)


class TestPy7zCoreInitialization:
    def test_find_7z_exe_project_path(self):
        with patch('os.path.exists') as mock_exists:
            def exists_side_effect(path):
                if "7z.exe" in str(path):
                    return True
                return False
            mock_exists.side_effect = exists_side_effect

            core = Py7zCore()
            assert core._7z_exe_path is not None

    def test_find_7z_exe_not_found(self):
        with patch('os.path.exists', return_value=False):
            with patch('freeassetfilter.core.py7z_core.run_with_limited_output') as mock_run:
                mock_run.side_effect = FileNotFoundError()
                with pytest.raises(FileNotFoundError, match="找不到 7z.exe"):
                    Py7zCore()

    def test_custom_timeout(self):
        with patch('os.path.exists', return_value=True):
            core = Py7zCore(command_timeout=120)
            assert core._command_timeout == 120

    def test_default_timeout(self):
        with patch('os.path.exists', return_value=True):
            core = Py7zCore()
            assert core._command_timeout == 60

    def test_get_subprocess_kwargs_windows(self):
        with patch('os.path.exists', return_value=True):
            with patch('os.name', 'nt'):
                core = Py7zCore()
                kwargs = core._get_subprocess_kwargs()
                assert 'startupinfo' in kwargs
                assert 'creationflags' in kwargs


class TestRun7zCommand:
    @pytest.fixture
    def core_instance(self):
        with patch('os.path.exists', return_value=True):
            core = Py7zCore()
            yield core

    def test_successful_command(self, core_instance):
        with patch('freeassetfilter.core.py7z_core.run_with_limited_output') as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "success output"
            mock_result.stderr = ""
            mock_result.stdout_truncated = False
            mock_result.stderr_truncated = False
            mock_run.return_value = mock_result

            returncode, stdout, stderr = core_instance._run_7z_command(["l", "test.zip"])
            assert returncode == 0
            assert stdout == "success output"
            assert stderr == ""

    def test_command_with_nonzero_exit(self, core_instance):
        with patch('freeassetfilter.core.py7z_core.run_with_limited_output') as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stdout = ""
            mock_result.stderr = "Error occurred"
            mock_result.stdout_truncated = False
            mock_result.stderr_truncated = False
            mock_run.return_value = mock_result

            returncode, stdout, stderr = core_instance._run_7z_command(["l", "test.zip"])
            assert returncode == 1
            assert stderr == "Error occurred"

    def test_command_timeout(self, core_instance):
        import subprocess
        with patch('freeassetfilter.core.py7z_core.run_with_limited_output') as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("7z", 60)
            returncode, stdout, stderr = core_instance._run_7z_command(["l", "test.zip"])
            assert returncode == -1
            assert "超时" in stderr

    def test_command_injection_blocked(self, core_instance):
        with patch('freeassetfilter.core.py7z_core.contains_injection_chars', return_value=True):
            returncode, stdout, stderr = core_instance._run_7z_command(["l", "file;rm -rf /"])
            assert returncode == -1
            assert "命令注入风险" in stderr

    def test_command_output_truncated(self, core_instance):
        with patch('freeassetfilter.core.py7z_core.run_with_limited_output') as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "output"
            mock_result.stdout_truncated = True
            mock_result.stderr_truncated = False
            mock_run.return_value = mock_result

            returncode, stdout, stderr = core_instance._run_7z_command(["l", "test.zip"])
            assert returncode == -1
            assert "超过安全限制" in stderr

    def test_utf16_encoding(self, core_instance):
        with patch('freeassetfilter.core.py7z_core.run_with_limited_output') as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "output".encode('utf-16')
            mock_result.stderr = "".encode('utf-16')
            mock_result.stdout_truncated = False
            mock_result.stderr_truncated = False
            mock_run.return_value = mock_result

            returncode, stdout, stderr = core_instance._run_7z_command(
                ["l", "test.zip"], encoding='utf-16'
            )
            assert returncode == 0

    def test_generic_exception(self, core_instance):
        with patch('freeassetfilter.core.py7z_core.run_with_limited_output') as mock_run:
            mock_run.side_effect = Exception("Unexpected error")
            returncode, stdout, stderr = core_instance._run_7z_command(["l", "test.zip"])
            assert returncode == -1
            assert "Unexpected error" in stderr


class TestParseFileBlock:
    @pytest.fixture
    def core_instance(self):
        with patch('os.path.exists', return_value=True):
            core = Py7zCore()
            yield core

    def test_parse_valid_file_block(self, core_instance):
        block = """Path = test/document.pdf
Size = 1024
Modified = 2023-01-15 10:30:00
Attributes = A
CRC = 12345678"""
        result = core_instance._parse_file_block(block)
        assert result is not None
        assert result["path"] == "test/document.pdf"
        assert result["size"] == 1024
        assert result["modified"] == "2023-01-15T10:30:00"
        assert result["is_dir"] is False
        assert result["crc"] == "12345678"

    def test_parse_directory_block(self, core_instance):
        block = """Path = test/folder
Size = 0
Modified = 2023-01-15 10:30:00
Attributes = D"""
        result = core_instance._parse_file_block(block)
        assert result is not None
        assert result["is_dir"] is True

    def test_parse_missing_path(self, core_instance):
        block = """Size = 1024
Modified = 2023-01-15 10:30:00"""
        result = core_instance._parse_file_block(block)
        assert result is None

    def test_parse_invalid_date(self, core_instance):
        block = """Path = test/file.txt
Size = 512
Modified = invalid-date"""
        result = core_instance._parse_file_block(block)
        assert result is not None
        assert result["modified"] == ""

    def test_parse_no_attributes(self, core_instance):
        block = """Path = test/file.txt
Size = 256"""
        result = core_instance._parse_file_block(block)
        assert result is not None
        assert result["is_dir"] is False

    def test_parse_directory_by_trailing_slash(self, core_instance):
        block = """Path = test/folder/
Size = 0"""
        result = core_instance._parse_file_block(block)
        assert result is not None
        assert result["is_dir"] is True

    def test_parse_zero_size(self, core_instance):
        block = """Path = test/empty.txt"""
        result = core_instance._parse_file_block(block)
        assert result is not None
        assert result["size"] == 0


class TestDetectEncoding:
    @pytest.fixture
    def core_instance(self):
        with patch('os.path.exists', return_value=True):
            core = Py7zCore()
            yield core

    def test_detect_utf8(self, core_instance):
        output = "Path = test/file.txt\nSize = 1024"
        result = core_instance._detect_encoding_from_output(output, "utf-8")
        assert result == "utf-8"

    def test_detect_gbk_due_to_replacement(self, core_instance):
        output = "Path = \ufffd\ufffd/file.txt\nSize = 1024"
        result = core_instance._detect_encoding_from_output(output, "utf-8")
        assert result == "gbk"

    def test_respect_user_encoding(self, core_instance):
        output = "Path = test/file.txt"
        result = core_instance._detect_encoding_from_output(output, "gbk")
        assert result == "gbk"


class TestListArchive:
    @pytest.fixture
    def core_instance(self):
        with patch('os.path.exists', return_value=True):
            core = Py7zCore()
            yield core

    def test_list_archive_success(self, core_instance):
        output = """Path = test\\file1.txt
Size = 1024
Modified = 2023-01-15 10:30:00
Attributes = A

Path = test\\file2.pdf
Size = 2048
Modified = 2023-01-16 11:00:00
Attributes = A"""

        with patch.object(core_instance, '_run_7z_command') as mock_run:
            mock_run.return_value = (0, output, "")
            result = core_instance.list_archive(r"E:\test\archive.zip")
            assert len(result) >= 1

    def test_list_archive_nonexistent(self, core_instance):
        with patch('os.path.exists', return_value=False):
            result = core_instance.list_archive(r"E:\nonexistent\archive.zip")
            assert result == []

    def test_list_archive_invalid_path(self, core_instance):
        with patch('freeassetfilter.core.py7z_core.validate_safe_path') as mock_validate:
            mock_validate.side_effect = ValueError("Invalid path")
            result = core_instance.list_archive(r"C:\invalid\path")
            assert result == []

    def test_list_archive_command_failure(self, core_instance):
        with patch.object(core_instance, '_run_7z_command') as mock_run:
            mock_run.return_value = (1, "", "Command failed")
            result = core_instance.list_archive(r"E:\test\archive.zip")
            assert result == []

    def test_list_archive_depth_limit(self, core_instance):
        result = core_instance.list_archive(
            r"E:\test\archive.zip",
            nested_depth=6
        )
        assert result == []

    def test_list_archive_with_current_path(self, core_instance):
        output = """Path = subdir\\file1.txt
Size = 1024
Modified = 2023-01-15 10:30:00
Attributes = A"""

        with patch.object(core_instance, '_run_7z_command') as mock_run:
            mock_run.return_value = (0, output, "")
            result = core_instance.list_archive(
                r"E:\test\archive.zip",
                current_path="subdir"
            )
            assert len(result) >= 1

    def test_list_archive_encoding_retry(self, core_instance):
        gbk_output = """Path = test/file.txt
Size = 1024
Modified = 2023-01-15 10:30:00
Attributes = A"""

        with patch.object(core_instance, '_run_7z_command') as mock_run:
            mock_run.side_effect = [
                (0, "Path = \ufffd\ufffd", ""),
                (0, gbk_output, "")
            ]
            result = core_instance.list_archive(r"E:\test\archive.zip")
            assert len(result) >= 1

    def test_list_archive_file_limit(self, core_instance):
        blocks = []
        for i in range(10001):
            blocks.append(f"""Path = file_{i}.txt
Size = 100
Modified = 2023-01-15 10:30:00
Attributes = A""")
        output = "\n".join(blocks)

        with patch.object(core_instance, '_run_7z_command') as mock_run:
            mock_run.return_value = (0, output, "")
            result = core_instance.list_archive(r"E:\test\large.zip")
            assert len(result) <= core_instance.MAX_ARCHIVE_FILES

    def test_list_archive_skips_self(self, core_instance):
        output = f"""Path = archive.zip
Size = 1024
Modified = 2023-01-15 10:30:00
Attributes = A"""

        with patch.object(core_instance, '_run_7z_command') as mock_run:
            mock_run.return_value = (0, output, "")
            result = core_instance.list_archive(r"E:\test\archive.zip")
            assert len(result) == 0

    def test_list_archive_skips_hidden(self, core_instance):
        output = """Path = .hidden_file.txt
Size = 100
Modified = 2023-01-15 10:30:00
Attributes = A"""

        with patch.object(core_instance, '_run_7z_command') as mock_run:
            mock_run.return_value = (0, output, "")
            result = core_instance.list_archive(r"E:\test\archive.zip")
            assert len(result) == 0


class TestIsEncrypted:
    @pytest.fixture
    def core_instance(self):
        with patch('os.path.exists', return_value=True):
            core = Py7zCore()
            yield core

    def test_is_encrypted_true(self, core_instance):
        with patch.object(core_instance, '_run_7z_command') as mock_run:
            mock_run.return_value = (0, "Encrypted = +", "")
            result = core_instance.is_encrypted(r"E:\test\encrypted.zip")
            assert result is True

    def test_is_encrypted_false(self, core_instance):
        with patch.object(core_instance, '_run_7z_command') as mock_run:
            mock_run.return_value = (0, "No encryption", "")
            result = core_instance.is_encrypted(r"E:\test\normal.zip")
            assert result is False

    def test_is_encrypted_nonexistent(self, core_instance):
        with patch('os.path.exists', return_value=False):
            result = core_instance.is_encrypted(r"E:\nonexistent\archive.zip")
            assert result is False

    def test_is_encrypted_password_in_stderr(self, core_instance):
        with patch.object(core_instance, '_run_7z_command') as mock_run:
            mock_run.return_value = (1, "", "Password required")
            result = core_instance.is_encrypted(r"E:\test\encrypted.zip")
            assert result is True

    def test_is_encrypted_encrypted_in_output(self, core_instance):
        with patch.object(core_instance, '_run_7z_command') as mock_run:
            mock_run.return_value = (0, "This archive is encrypted", "")
            result = core_instance.is_encrypted(r"E:\test\encrypted.zip")
            assert result is True


class TestGetArchiveType:
    @pytest.fixture
    def core_instance(self):
        with patch('os.path.exists', return_value=True):
            core = Py7zCore()
            yield core

    def test_get_type_from_output(self, core_instance):
        with patch.object(core_instance, '_run_7z_command') as mock_run:
            mock_run.return_value = (0, "Type = zip", "")
            result = core_instance.get_archive_type(r"E:\test\archive.zip")
            assert result == "zip"

    def test_get_type_from_extension(self, core_instance):
        with patch.object(core_instance, '_run_7z_command') as mock_run:
            mock_run.return_value = (0, "", "")
            result = core_instance.get_archive_type(r"E:\test\archive.rar")
            assert result == "rar"

    def test_get_type_unknown(self, core_instance):
        with patch.object(core_instance, '_run_7z_command') as mock_run:
            mock_run.return_value = (1, "", "Error")
            result = core_instance.get_archive_type(r"E:\test\unknown.xyz")
            assert result == "unknown"

    def test_get_type_nonexistent(self, core_instance):
        with patch('os.path.exists', return_value=False):
            result = core_instance.get_archive_type(r"E:\nonexistent\archive.zip")
            assert result == "unknown"

    def test_get_type_various_extensions(self, core_instance):
        with patch.object(core_instance, '_run_7z_command') as mock_run:
            mock_run.return_value = (0, "", "")
            test_cases = [
                (r"E:\test\archive.7z", "7z"),
                (r"E:\test\archive.tar", "tar"),
                (r"E:\test\archive.gz", "gzip"),
                (r"E:\test\archive.bz2", "bzip2"),
                (r"E:\test\archive.xz", "xz"),
            ]
            for path, expected in test_cases:
                result = core_instance.get_archive_type(path)
                assert result == expected


class TestConvenienceFunctions:
    def test_get_7z_core_singleton(self):
        core1 = get_7z_core()
        core2 = get_7z_core()
        assert core1 is core2

    def test_list_archive_convenience_function(self):
        with patch('freeassetfilter.core.py7z_core.get_7z_core') as mock_get_core:
            mock_core = MagicMock()
            mock_core.list_archive.return_value = []
            mock_get_core.return_value = mock_core
            result = list_archive(r"E:\test\archive.zip")
            assert result == []
            mock_core.list_archive.assert_called_once()

    def test_is_encrypted_convenience_function(self):
        with patch('freeassetfilter.core.py7z_core.get_7z_core') as mock_get_core:
            mock_core = MagicMock()
            mock_core.is_encrypted.return_value = False
            mock_get_core.return_value = mock_core
            result = is_encrypted(r"E:\test\archive.zip")
            assert result is False

    def test_get_archive_type_convenience_function(self):
        with patch('freeassetfilter.core.py7z_core.get_7z_core') as mock_get_core:
            mock_core = MagicMock()
            mock_core.get_archive_type.return_value = "zip"
            mock_get_core.return_value = mock_core
            result = get_archive_type(r"E:\test\archive.zip")
            assert result == "zip"
