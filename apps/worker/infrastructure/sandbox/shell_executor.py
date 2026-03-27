from __future__ import annotations

import subprocess


def run_shell(command: list[str], *, cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)

