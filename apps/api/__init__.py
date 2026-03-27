from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

API_DIR = Path(__file__).resolve().parent
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

__all__ = ["app", "create_app"]


def __getattr__(name: str) -> Any:
    if name == "app":
        from .bootstrap.app_factory import app

        return app
    if name == "create_app":
        from .bootstrap.app_factory import create_app

        return create_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
