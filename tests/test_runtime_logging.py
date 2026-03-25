from __future__ import annotations

import logging
from pathlib import Path

from core.runtime_logging import attach_optional_file_handler, ensure_runtime_directory


def test_ensure_runtime_directory_returns_false_on_oserror(monkeypatch, tmp_path):
    target = tmp_path / "logs"

    def raise_oserror(self, parents=False, exist_ok=False):
        raise OSError("read-only")

    monkeypatch.setattr(Path, "mkdir", raise_oserror)

    assert ensure_runtime_directory(target) is False


def test_attach_optional_file_handler_warns_and_keeps_logger_usable(monkeypatch, tmp_path):
    logger = logging.getLogger("test.runtime.logging")
    logger.handlers = []
    logger.setLevel(logging.INFO)
    logger.propagate = False

    messages: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record):
            messages.append(record.getMessage())

    logger.addHandler(Capture())
    formatter = logging.Formatter("%(message)s")

    def raise_file_handler(*args, **kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(logging, "FileHandler", raise_file_handler)

    attached = attach_optional_file_handler(
        logger,
        logger_name="api",
        log_path=tmp_path / "logs" / "api.log",
        formatter=formatter,
    )

    assert attached is False
    assert any("api file logger disabled" in message for message in messages)

    logger.handlers = []
