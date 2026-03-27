from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class MemoryRecordEntity:
    memory_id: int | None
    title: str
    content: str
    memory_kind: str

