from __future__ import annotations

import logging
from pathlib import Path


def ensure_runtime_directory(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    return True


def attach_optional_file_handler(
    logger: logging.Logger,
    *,
    logger_name: str,
    log_path: Path,
    formatter: logging.Formatter,
) -> bool:
    try:
        ensure_runtime_directory(log_path.parent)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
    except OSError as exc:
        logger.warning("%s file logger disabled because %s is unavailable: %s", logger_name, log_path, exc)
        return False
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return True
