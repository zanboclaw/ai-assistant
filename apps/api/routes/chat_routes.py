from __future__ import annotations

from fastapi import FastAPI

from apps.api.routes.intake_routes import register_intake_routes


def register_chat_routes(*, app: FastAPI, container) -> None:
    # Fast Path currently lives in the intake router and is kept compatible here.
    register_intake_routes(app=app, container=container)

