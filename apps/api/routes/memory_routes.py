from __future__ import annotations

from fastapi import FastAPI

from apps.api.routes.intake_routes import register_intake_routes


def register_memory_routes(*, app: FastAPI, container) -> None:
    # Memory search currently shares the intake router; this adapter keeps the new layout stable.
    register_intake_routes(app=app, container=container)

