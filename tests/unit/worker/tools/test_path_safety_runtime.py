from pathlib import Path

import pytest

from apps.worker.runtime.tools.path_safety import (
    ensure_readable_dir,
    ensure_readable_file,
    ensure_writable_file,
    extract_path_from_text,
    is_path_in_allowed_dirs,
)


def test_path_safety_checks_allowed_dirs(tmp_path):
    allowed = tmp_path / "workspace"
    allowed.mkdir()
    target = allowed / "demo.txt"
    target.write_text("ok", encoding="utf-8")

    assert is_path_in_allowed_dirs(str(target), [allowed]) is True
    assert ensure_readable_file(str(target), allowed_dirs=[allowed]) == target.resolve()


def test_ensure_writable_file_rejects_outside_allowed_dirs(tmp_path):
    allowed = tmp_path / "workspace"
    allowed.mkdir()
    outside = tmp_path / "outside.txt"

    with pytest.raises(ValueError):
        ensure_writable_file(str(outside), allowed_dirs=[allowed])


def test_ensure_readable_dir_requires_existing_dir(tmp_path):
    allowed = tmp_path / "workspace"
    allowed.mkdir()

    with pytest.raises(ValueError):
        ensure_readable_dir(str(allowed / "missing"), allowed_dirs=[allowed])


def test_extract_path_from_text_returns_first_path():
    assert extract_path_from_text("请读取 /tmp/demo.txt 然后总结") == "/tmp/demo.txt"
