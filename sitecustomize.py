from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
WORKER_DIR = ROOT / "apps" / "worker"
API_DIR = ROOT / "apps" / "api"

for path in reversed((ROOT, WORKER_DIR, API_DIR)):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)
