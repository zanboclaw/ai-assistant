from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar


T = TypeVar("T")


@dataclass(slots=True)
class Result(Generic[T]):
    ok: bool
    value: T | None = None
    errors: list[str] = field(default_factory=list)

    @classmethod
    def success(cls, value: T | None = None) -> "Result[T]":
        return cls(ok=True, value=value)

    @classmethod
    def failure(cls, *errors: str) -> "Result[T]":
        return cls(ok=False, errors=[str(item) for item in errors if str(item).strip()])

