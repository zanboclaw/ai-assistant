from __future__ import annotations

from functools import lru_cache

from apps.api.bootstrap.container import APIContainer, build_container


@lru_cache(maxsize=1)
def get_api_container() -> APIContainer:
    return build_container()

