from __future__ import annotations

from fastapi import FastAPI


def register_skill_routes(*, app: FastAPI, container) -> None:
    app.include_router(
        container["register_skill_routes"](
            get_conn=container["get_conn"],
            require_actor_permission=container["require_actor_permission"],
            ensure_skill_registry_tables=container["ensure_skill_registry_tables"],
            insert_audit_log=container["insert_audit_log"],
            read_skill_package_from_source=container["_read_skill_package_from_source"],
            serialize_skill_row=container["serialize_skill_row"],
            serialize_skill_version_row=container["serialize_skill_version_row"],
            json_wrapper=container["Json"],
        )
    )
