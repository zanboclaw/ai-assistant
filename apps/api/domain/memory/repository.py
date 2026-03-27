from __future__ import annotations


class MemoryRepository:
    def __init__(self, *, search_fn):
        self._search_fn = search_fn

