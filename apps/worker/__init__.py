from __future__ import annotations

import sys
from pathlib import Path

WORKER_DIR = Path(__file__).resolve().parent
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

from .bootstrap.worker_factory import main, process_task

__all__ = ["main", "process_task"]
