from __future__ import annotations

from fastapi import APIRouter, FastAPI, Header


def _fetch_schema_version(container) -> str:
    try:
        conn = container["get_conn"]()
        cur = conn.cursor()
        cur.execute("SELECT to_regclass('public.schema_migrations') AS regclass;")
        row = cur.fetchone() or {}
        if not row.get("regclass"):
            return "uninitialized"
        cur.execute("SELECT migration_id FROM schema_migrations ORDER BY applied_at DESC, migration_id DESC LIMIT 1;")
        migration_row = cur.fetchone() or {}
        return str(migration_row.get("migration_id") or "unknown")
    except Exception:
        return "unknown"
    finally:
        if "cur" in locals():
            cur.close()
        if "conn" in locals():
            conn.close()


def register_health_routes(*, app: FastAPI, container) -> None:
    router = APIRouter()

    @router.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @router.get("/")
    def root():
        return {"message": "ai assistant api is running"}

    @router.post("/init-db")
    def init_db(x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
        return container["init_db_with_context_impl"](
            x_actor_name,
            get_conn_fn=container["get_conn"],
            require_actor_permission_fn=container["require_actor_permission"],
            ensure_runtime_core_tables_fn=container["ensure_runtime_core_tables"],
            seed_default_risk_policies_fn=container["seed_default_risk_policies"],
            ensure_audit_logs_table_fn=container["ensure_audit_logs_table"],
            seed_default_access_actors_fn=container["seed_default_access_actors"],
            seed_default_access_quotas_fn=container["seed_default_access_quotas"],
            seed_default_tool_registry_fn=container["seed_default_tool_registry"],
            seed_default_model_providers_fn=container["seed_default_model_providers"],
            seed_default_model_routes_fn=container["seed_default_model_routes"],
            ensure_change_requests_table_fn=container["ensure_change_requests_table"],
            ensure_agent_tables_fn=container["ensure_agent_tables"],
            logger=container["logger"],
        )

    @router.get("/readyz")
    def readyz():
        return {"status": "ready", "schema_version": _fetch_schema_version(container)}

    @router.get("/version")
    def version():
        metadata = container["get_runtime_version_metadata"]()
        metadata["schema_version"] = _fetch_schema_version(container)
        return metadata

    app.include_router(router)
