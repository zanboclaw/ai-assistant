from __future__ import annotations

from collections.abc import Mapping
from importlib import import_module
import sys
from typing import Any

from apps.api.bootstrap.container_exports import API_CONTAINER_EXPORTS
from apps.api.bootstrap.config import load_api_settings


class APIContainer(Mapping[str, Any]):
    def __init__(self) -> None:
        self._context = sys.modules.get("api_app_context") or import_module("apps.api.api_app_context")
        missing = [name for name in API_CONTAINER_EXPORTS if not hasattr(self._context, name)]
        if missing:
            formatted = ", ".join(missing)
            raise AttributeError(f"apps.api.api_app_context is missing required container exports: {formatted}")
        self._context_keys = API_CONTAINER_EXPORTS
        self.settings = load_api_settings()

    def __getitem__(self, key: str) -> Any:
        if key not in self._context_keys:
            raise KeyError(key)
        return getattr(self._context, key)

    def __iter__(self):
        return iter(self._context_keys)

    def __len__(self) -> int:
        return len(self._context_keys)

    def get(self, key: str, default: Any = None) -> Any:
        if key not in self._context_keys:
            return default
        return getattr(self._context, key, default)


def build_container() -> APIContainer:
    return APIContainer()
