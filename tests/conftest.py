from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "apps" / "api"
WORKER_DIR = ROOT / "apps" / "worker"

for path in (ROOT, API_DIR, WORKER_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
