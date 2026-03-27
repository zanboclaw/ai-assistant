from __future__ import annotations

from collections.abc import Mapping
from importlib import import_module
from typing import Any

from apps.worker.bootstrap.config import load_worker_settings
from apps.worker.bootstrap.runtime_exports import WORKER_RUNTIME_EXPORTS


class WorkerRuntimeContainer(Mapping[str, Any]):
    def __init__(self) -> None:
        self._context = import_module("apps.worker.bootstrap.runtime_exports")
        self._context_keys = WORKER_RUNTIME_EXPORTS
        self.settings = load_worker_settings()

    def __getitem__(self, key: str) -> Any:
        if key not in self._context_keys:
            raise KeyError(key)
        return getattr(self._context, key)

    def __iter__(self):
        return iter(self._context_keys)

    def __len__(self) -> int:
        return len(self._context_keys)


def build_runtime_container() -> WorkerRuntimeContainer:
    return WorkerRuntimeContainer()
