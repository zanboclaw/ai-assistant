from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(slots=True)
class WorkerSettings:
    workspace_root: str = os.environ.get("WORKSPACE_ROOT", "/workspace_repo")
    redis_url: str = os.environ.get("REDIS_URL", "redis://redis:6379/0")


def load_worker_settings() -> WorkerSettings:
    return WorkerSettings()

