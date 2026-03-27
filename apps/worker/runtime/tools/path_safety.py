from __future__ import annotations

import re
from pathlib import Path


def is_path_in_allowed_dirs(path_str: str, allowed_dirs: list[Path]) -> bool:
    try:
        target = Path(path_str).resolve()
        for base in allowed_dirs:
            try:
                target.relative_to(base.resolve())
                return True
            except ValueError:
                continue
        return False
    except Exception:
        return False


def ensure_readable_file(path_str: str, *, allowed_dirs: list[Path]) -> Path:
    if not path_str:
        raise ValueError("缺少文件路径")
    if not is_path_in_allowed_dirs(path_str, allowed_dirs):
        raise ValueError(f"路径不在允许范围内 -> {path_str}")

    path = Path(path_str).resolve()
    if not path.exists():
        raise ValueError(f"文件不存在 -> {path_str}")
    if not path.is_file():
        raise ValueError(f"目标不是文件 -> {path_str}")
    return path


def ensure_writable_file(path_str: str, *, allowed_dirs: list[Path]) -> Path:
    if not path_str:
        raise ValueError("缺少文件路径")
    if not is_path_in_allowed_dirs(path_str, allowed_dirs):
        raise ValueError(f"路径不在允许范围内 -> {path_str}")

    path = Path(path_str).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.is_dir():
        raise ValueError(f"目标是目录，不是文件 -> {path_str}")
    return path


def ensure_readable_dir(path_str: str, *, allowed_dirs: list[Path]) -> Path:
    if not path_str:
        raise ValueError("缺少目录路径")
    if not is_path_in_allowed_dirs(path_str, allowed_dirs):
        raise ValueError(f"路径不在允许范围内 -> {path_str}")

    path = Path(path_str).resolve()
    if not path.exists():
        raise ValueError(f"目录不存在 -> {path_str}")
    if not path.is_dir():
        raise ValueError(f"目标不是目录 -> {path_str}")
    return path


def extract_path_from_text(text: str) -> str | None:
    if not text:
        return None
    match = re.search(r"(/[^ \n\r\t'\"，。；：]+)", text)
    if match:
        return match.group(1)
    return None


__all__ = [
    "ensure_readable_dir",
    "ensure_readable_file",
    "ensure_writable_file",
    "extract_path_from_text",
    "is_path_in_allowed_dirs",
]
