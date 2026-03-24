from __future__ import annotations

from typing import Any


def fetch_planner_route(
    cur,
    *,
    seed_default_model_providers_fn,
    seed_default_model_routes_fn,
):
    seed_default_model_providers_fn(cur)
    seed_default_model_routes_fn(cur)
    cur.execute(
        """
        SELECT route_name, provider, model_name, temperature, max_tokens, enabled, description, created_at, updated_at
        FROM model_routes
        WHERE route_name = 'planner'
        LIMIT 1;
        """
    )
    return cur.fetchone()


def is_change_gate_enforced(
    target_type: str,
    *,
    default_enforced_change_target_types: set[str],
) -> bool:
    return target_type in default_enforced_change_target_types


def enforce_change_gate_for_direct_update(
    target_type: str,
    *,
    is_change_gate_enforced_fn,
    http_exception_cls,
):
    if is_change_gate_enforced_fn(target_type):
        raise http_exception_cls(
            status_code=409,
            detail=f"Direct update disabled for {target_type}; submit and apply a change request instead",
        )


def init_db_with_context(
    x_actor_name: str | None,
    *,
    get_conn_fn,
    require_actor_permission_fn,
    ensure_runtime_core_tables_fn,
    seed_default_risk_policies_fn,
    ensure_audit_logs_table_fn,
    seed_default_access_actors_fn,
    seed_default_access_quotas_fn,
    seed_default_tool_registry_fn,
    seed_default_model_providers_fn,
    seed_default_model_routes_fn,
    ensure_change_requests_table_fn,
    ensure_agent_tables_fn,
    logger,
) -> dict[str, Any]:
    conn = get_conn_fn()
    cur = conn.cursor()
    try:
        actor = require_actor_permission_fn(cur, x_actor_name, "admin")
        ensure_runtime_core_tables_fn(cur)
        seed_default_risk_policies_fn(cur)
        ensure_audit_logs_table_fn(cur)
        seed_default_access_actors_fn(cur)
        seed_default_access_quotas_fn(cur)
        seed_default_tool_registry_fn(cur)
        seed_default_model_providers_fn(cur)
        seed_default_model_routes_fn(cur)
        ensure_change_requests_table_fn(cur)
        ensure_agent_tables_fn(cur)
        conn.commit()
    finally:
        cur.close()
        conn.close()

    logger.info("database initialized actor=%s", actor["actor_name"])
    return {"message": "database initialized"}
