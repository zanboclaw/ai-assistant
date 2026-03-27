from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.bootstrap.dependencies import get_api_container
from apps.api.routes.governance_routes import register_governance_routes
from apps.api.routes.health_routes import register_health_routes
from apps.api.routes.intake_routes import register_intake_routes
from apps.api.routes.monitor_routes import register_monitor_routes
from apps.api.routes.multi_agent_routes import register_multi_agent_routes
from apps.api.routes.session_routes import register_session_routes
from apps.api.routes.skill_routes import register_skill_routes
from apps.api.routes.task_routes import register_task_routes
from apps.api.routes.workflow_routes import register_workflow_routes


def create_app() -> FastAPI:
    container = get_api_container()
    cached_app = getattr(container, "_refactor_app", None)
    if cached_app is not None:
        return cached_app

    app = FastAPI(title=container.settings.title)
    if getattr(app.state, "refactor_bootstrap_ready", False):
        return app

    settings = container.settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_health_routes(app=app, container=container)
    register_intake_routes(app=app, container=container)
    register_task_routes(app=app, container=container)
    register_session_routes(app=app, container=container)
    register_governance_routes(app=app, container=container)
    register_workflow_routes(app=app, container=container)
    register_monitor_routes(app=app, container=container)
    register_skill_routes(app=app, container=container)
    register_multi_agent_routes(app=app, container=container)
    app.state.refactor_bootstrap_ready = True
    app.state.container = container
    app.state.settings = settings
    container._refactor_app = app
    return app


app = create_app()
