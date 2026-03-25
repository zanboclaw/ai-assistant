from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PytestCompatibilityTest(unittest.TestCase):
    def test_pytest_suite(self):
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "--ignore=tests/test_unittest_compat.py",
                "--ignore=tests/test_000_path_bootstrap.py",
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=300,
        )
        if completed.returncode != 0:
            message = "\n".join(
                part
                for part in (
                    completed.stdout.strip(),
                    completed.stderr.strip(),
                )
                if part
            )
            self.fail(message or "pytest -q failed")
