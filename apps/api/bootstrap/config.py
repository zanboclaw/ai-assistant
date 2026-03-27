from __future__ import annotations

import os
from dataclasses import dataclass


def _parse_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


@dataclass(slots=True)
class ApiSettings:
    title: str = os.environ.get("API_TITLE", "AI Assistant API")
    cors_origins: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        raw = os.environ.get("API_CORS_ORIGINS", "*")
        self.cors_origins = _parse_csv(raw) or ["*"]


def load_api_settings() -> ApiSettings:
    return ApiSettings()

