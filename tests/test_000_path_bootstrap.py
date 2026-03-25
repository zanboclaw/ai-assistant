from __future__ import annotations

import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKER_DIR = ROOT / "apps" / "worker"
API_DIR = ROOT / "apps" / "api"

for path in reversed((ROOT, WORKER_DIR, API_DIR)):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


class PathBootstrapTest(unittest.TestCase):
    def test_import_paths_bootstrapped(self):
        self.assertIn(str(WORKER_DIR), sys.path)
        self.assertIn(str(API_DIR), sys.path)
