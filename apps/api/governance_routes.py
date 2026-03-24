from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import APIRouter, Header, HTTPException

from schemas import AccessActorUpdate, AccessQuotaUpdate, ModelProviderUpdate, ModelRouteUpdate, RiskPolicyUpdate, ToolRegistryUpdate


def register_governance_routes(
    *,
    get_conn: Callable[[], Any],
    require_actor_permission: Callable[[Any, str | None, str], dict[str, Any]],
    seed_default_risk_policies: Callable[[Any], None],
    deserialize_policy_row: Callable[[dict[str, Any]], dict[str, Any]],
    seed_default_tool_registry: Callable[[Any], None],
    serialize_tool_registry_row: Callable[[dict[str, Any]], dict[str, Any]],
    seed_default_model_providers: Callable[[Any], None],
    seed_default_model_routes: Callable[[Any], None],
    serialize_model_route_row: Callable[[dict[str, Any]], dict[str, Any]],
    serialize_model_provider_row: Callable[[dict[str, Any]], dict[str, Any]],
    seed_default_access_actors: Callable[[Any], None],
    seed_default_access_quotas: Callable[[Any], None],
    serialize_access_actor_row: Callable[[dict[str, Any]], dict[str, Any]],
    serialize_access_quota_row: Callable[[dict[str, Any]], dict[str, Any]],
    parse_maybe_json: Callable[[Any], Any],
    validate_policy_value: Callable[[str, Any], tuple[str, Any]],
    update_risk_policy_entry: Callable[..., dict[str, Any]],
    update_tool_registry_entry: Callable[..., dict[str, Any]],
    update_model_route_entry: Callable[..., dict[str, Any]],
    upsert_model_provider_entry: Callable[..., dict[str, Any]],
    upsert_access_actor: Callable[..., dict[str, Any]],
    upsert_access_quota: Callable[..., dict[str, Any]],
    upsert_default_access_quota: Callable[[Any, str], None],
    insert_audit_log: Callable[[Any, str, str, int | None, Any | None], None],
    enforce_change_gate_for_direct_update: Callable[[str], None],
    ensure_audit_logs_table: Callable[[Any], None],
    access_role_permissions: dict[str, set[str]],
    step_request_protocol_version: str,
    step_execution_request_fields: list[str],
    enriched_step_execution_request_extra_fields: list[str],
    multi_agent_protocol_version: str,
    auto_stage5_postrun_enabled: bool,
    logger: Any,
):
    router = APIRouter()

    @router.get("/risk-policies")
    def list_risk_policies(x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
        conn = get_conn()
        cur = conn.cursor()
        require_actor_permission(cur, x_actor_name, "read")
        seed_default_risk_policies(cur)
        seed_default_access_actors(cur)
        conn.commit()

        cur.execute(
            """
            SELECT policy_key, value_type, policy_value, description, created_at, updated_at
            FROM risk_policies
            ORDER BY policy_key ASC;
            """
        )
        rows = [deserialize_policy_row(row) for row in cur.fetchall()]
        cur.close()
        conn.close()
        return rows

    @router.get("/tools")
    def list_tool_registry(x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
        conn = get_conn()
        cur = conn.cursor()
        require_actor_permission(cur, x_actor_name, "read")
        seed_default_tool_registry(cur)
        conn.commit()
        cur.execute(
            """
            SELECT tool_name, enabled, provider_type, transport, server_name, provider_config, risk_level, approval_required, description, created_at, updated_at
            FROM tool_registry_entries
            ORDER BY tool_name ASC;
            """
        )
        rows = [serialize_tool_registry_row(row) for row in cur.fetchall()]
        cur.close()
        conn.close()
        return rows

    @router.put("/tools/{tool_name}")
    def update_tool_registry(
        tool_name: str,
        request: ToolRegistryUpdate,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        normalized_tool_name = tool_name.strip()
        normalized_risk_level = request.risk_level.strip().lower()
        if normalized_risk_level not in {"low", "medium", "high"}:
            raise HTTPException(status_code=400, detail=f"Unsupported risk level: {request.risk_level}")
        normalized_provider_type = request.provider_type.strip().lower()
        if normalized_provider_type not in {"builtin", "mcp_stdio", "mcp_http"}:
            raise HTTPException(status_code=400, detail=f"Unsupported provider_type: {request.provider_type}")
        normalized_transport = request.transport.strip().lower()
        if normalized_transport not in {"", "local", "stdio", "http"}:
            raise HTTPException(status_code=400, detail=f"Unsupported transport: {request.transport}")

        conn = get_conn()
        cur = conn.cursor()
        actor = require_actor_permission(cur, x_actor_name, "admin")
        enforce_change_gate_for_direct_update("tool_registry")
        serialized_row = update_tool_registry_entry(
            cur,
            tool_name=normalized_tool_name,
            enabled=bool(request.enabled),
            provider_type=normalized_provider_type,
            transport=normalized_transport or ("local" if normalized_provider_type == "builtin" else ""),
            server_name=request.server_name.strip(),
            provider_config=dict(request.provider_config or {}),
            risk_level=normalized_risk_level,
            approval_required=bool(request.approval_required),
            description=request.description.strip(),
            actor_name=actor["actor_name"],
            seed_default_tool_registry_fn=seed_default_tool_registry,
            insert_audit_log_fn=insert_audit_log,
            serialize_tool_registry_row_fn=serialize_tool_registry_row,
        )
        conn.commit()
        cur.close()
        conn.close()
        logger.info(
            "tool registry updated tool_name=%s enabled=%s provider_type=%s risk_level=%s actor=%s",
            normalized_tool_name,
            bool(request.enabled),
            normalized_provider_type,
            normalized_risk_level,
            actor["actor_name"],
        )
        return serialized_row

    @router.get("/model-routes")
    def list_model_routes(x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
        conn = get_conn()
        cur = conn.cursor()
        require_actor_permission(cur, x_actor_name, "read")
        seed_default_model_providers(cur)
        seed_default_model_routes(cur)
        conn.commit()
        cur.execute(
            """
            SELECT route_name, provider, model_name, temperature, max_tokens, enabled, description, created_at, updated_at
            FROM model_routes
            ORDER BY route_name ASC;
            """
        )
        rows = [serialize_model_route_row(row) for row in cur.fetchall()]
        cur.close()
        conn.close()
        return rows

    @router.get("/model-providers")
    def list_model_providers(x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
        conn = get_conn()
        cur = conn.cursor()
        require_actor_permission(cur, x_actor_name, "read")
        seed_default_model_providers(cur)
        conn.commit()
        cur.execute(
            """
            SELECT provider_name, driver, base_url, api_key_env, enabled, description, created_at, updated_at
            FROM model_providers
            ORDER BY provider_name ASC;
            """
        )
        rows = [serialize_model_provider_row(row) for row in cur.fetchall()]
        cur.close()
        conn.close()
        return rows

    @router.put("/model-routes/{route_name}")
    def update_model_route(
        route_name: str,
        request: ModelRouteUpdate,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        normalized_route_name = route_name.strip()
        normalized_provider = request.provider.strip()
        normalized_model_name = request.model_name.strip()
        if not normalized_provider:
            raise HTTPException(status_code=400, detail="provider is required")
        if not normalized_model_name:
            raise HTTPException(status_code=400, detail="model_name is required")
        if request.max_tokens <= 0:
            raise HTTPException(status_code=400, detail="max_tokens must be positive")

        conn = get_conn()
        cur = conn.cursor()
        actor = require_actor_permission(cur, x_actor_name, "admin")
        enforce_change_gate_for_direct_update("model_route")
        serialized_row = update_model_route_entry(
            cur,
            route_name=normalized_route_name,
            provider=normalized_provider,
            model_name=normalized_model_name,
            temperature=float(request.temperature),
            max_tokens=int(request.max_tokens),
            enabled=bool(request.enabled),
            description=request.description.strip(),
            actor_name=actor["actor_name"],
            seed_default_model_providers_fn=seed_default_model_providers,
            seed_default_model_routes_fn=seed_default_model_routes,
            insert_audit_log_fn=insert_audit_log,
            serialize_model_route_row_fn=serialize_model_route_row,
        )
        conn.commit()
        cur.close()
        conn.close()
        logger.info(
            "model route updated route_name=%s provider=%s model_name=%s enabled=%s actor=%s",
            normalized_route_name,
            normalized_provider,
            normalized_model_name,
            bool(request.enabled),
            actor["actor_name"],
        )
        return serialized_row

    @router.put("/model-providers/{provider_name}")
    def update_model_provider(
        provider_name: str,
        request: ModelProviderUpdate,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        normalized_provider_name = provider_name.strip()
        normalized_driver = request.driver.strip()
        normalized_base_url = request.base_url.strip()
        normalized_api_key_env = request.api_key_env.strip()
        if not normalized_provider_name:
            raise HTTPException(status_code=400, detail="provider_name is required")
        if normalized_driver not in {"openai_compatible"}:
            raise HTTPException(status_code=400, detail=f"Unsupported provider driver: {normalized_driver}")
        if not normalized_base_url:
            raise HTTPException(status_code=400, detail="base_url is required")
        if not normalized_api_key_env:
            raise HTTPException(status_code=400, detail="api_key_env is required")

        conn = get_conn()
        cur = conn.cursor()
        actor = require_actor_permission(cur, x_actor_name, "admin")
        enforce_change_gate_for_direct_update("model_provider")
        serialized_row = upsert_model_provider_entry(
            cur,
            provider_name=normalized_provider_name,
            driver=normalized_driver,
            base_url=normalized_base_url,
            api_key_env=normalized_api_key_env,
            enabled=bool(request.enabled),
            description=request.description.strip(),
            actor_name=actor["actor_name"],
            seed_default_model_providers_fn=seed_default_model_providers,
            insert_audit_log_fn=insert_audit_log,
            serialize_model_provider_row_fn=serialize_model_provider_row,
        )
        conn.commit()
        cur.close()
        conn.close()
        logger.info(
            "model provider updated provider_name=%s driver=%s enabled=%s actor=%s",
            normalized_provider_name,
            normalized_driver,
            bool(request.enabled),
            actor["actor_name"],
        )
        return serialized_row

    @router.get("/access/actors")
    def list_access_actors(x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
        conn = get_conn()
        cur = conn.cursor()
        require_actor_permission(cur, x_actor_name, "read")
        seed_default_access_actors(cur)
        conn.commit()
        cur.execute(
            """
            SELECT actor_name, role, description, tenant_key, permission_overrides, created_at, updated_at
            FROM access_actors
            ORDER BY actor_name ASC;
            """
        )
        rows = []
        for row in cur.fetchall():
            permission_overrides = parse_maybe_json(row.get("permission_overrides")) or []
            row["permissions"] = set(access_role_permissions.get(str(row.get("role") or ""), set())) | {
                str(item).strip().lower() for item in permission_overrides if str(item).strip()
            }
            rows.append(serialize_access_actor_row(row))
        cur.close()
        conn.close()
        return rows

    @router.get("/access/quotas")
    def list_access_quotas(x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
        conn = get_conn()
        cur = conn.cursor()
        require_actor_permission(cur, x_actor_name, "read")
        seed_default_access_quotas(cur)
        conn.commit()
        cur.execute(
            """
            SELECT actor_name, daily_task_limit, active_task_limit, daily_token_limit, max_parallel_agents, created_at, updated_at
            FROM access_quotas
            ORDER BY actor_name ASC;
            """
        )
        rows = [serialize_access_quota_row(row) for row in cur.fetchall()]
        cur.close()
        conn.close()
        return rows

    @router.get("/access/quota-usage")
    def list_access_quota_usage(x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
        conn = get_conn()
        cur = conn.cursor()
        require_actor_permission(cur, x_actor_name, "read")
        seed_default_access_quotas(cur)
        conn.commit()
        cur.execute(
            """
            SELECT
                a.actor_name,
                a.role,
                q.daily_task_limit,
                q.active_task_limit,
                q.daily_token_limit,
                q.max_parallel_agents,
                COALESCE(d.daily_task_count, 0) AS daily_task_count,
                COALESCE(ac.active_task_count, 0) AS active_task_count,
                COALESCE(tok.daily_token_count, 0) AS daily_token_count
            FROM access_actors a
            JOIN access_quotas q ON q.actor_name = a.actor_name
            LEFT JOIN (
                SELECT created_by_actor, COUNT(*) AS daily_task_count
                FROM task_runs
                WHERE created_by_actor IS NOT NULL
                  AND DATE(created_at) = CURRENT_DATE
                GROUP BY created_by_actor
            ) d ON d.created_by_actor = a.actor_name
            LEFT JOIN (
                SELECT created_by_actor, COUNT(*) AS active_task_count
                FROM task_runs
                WHERE created_by_actor IS NOT NULL
                  AND status NOT IN ('completed', 'failed')
                GROUP BY created_by_actor
            ) ac ON ac.created_by_actor = a.actor_name
            LEFT JOIN (
                SELECT tr.created_by_actor, COALESCE(SUM(COALESCE(ar.cost_tokens_in, 0) + COALESCE(ar.cost_tokens_out, 0)), 0) AS daily_token_count
                FROM task_runs tr
                JOIN agent_runs ar ON ar.task_run_id = tr.id
                WHERE tr.created_by_actor IS NOT NULL
                  AND DATE(ar.created_at) = CURRENT_DATE
                GROUP BY tr.created_by_actor
            ) tok ON tok.created_by_actor = a.actor_name
            ORDER BY a.actor_name ASC;
            """
        )
        rows = []
        for row in cur.fetchall():
            daily_limit = int(row["daily_task_limit"])
            active_limit = int(row["active_task_limit"])
            daily_token_limit = int(row["daily_token_limit"] or 0)
            max_parallel_agents = int(row["max_parallel_agents"] or 0)
            daily_count = int(row["daily_task_count"])
            active_count = int(row["active_task_count"])
            daily_token_count = int(row["daily_token_count"] or 0)
            rows.append(
                {
                    "actor_name": row["actor_name"],
                    "role": row["role"],
                    "daily_task_limit": daily_limit,
                    "active_task_limit": active_limit,
                    "daily_token_limit": daily_token_limit,
                    "max_parallel_agents": max_parallel_agents,
                    "daily_task_count": daily_count,
                    "active_task_count": active_count,
                    "daily_remaining": max(daily_limit - daily_count, 0),
                    "active_remaining": max(active_limit - active_count, 0),
                    "daily_token_count": daily_token_count,
                    "daily_token_remaining": max(daily_token_limit - daily_token_count, 0),
                }
            )
        cur.close()
        conn.close()
        return rows

    @router.put("/access/actors/{actor_name}")
    def update_access_actor(
        actor_name: str,
        request: AccessActorUpdate,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        normalized_role = request.role.strip().lower()
        if normalized_role not in access_role_permissions:
            raise HTTPException(status_code=400, detail=f"Unsupported role: {request.role}")

        normalized_actor_name = actor_name.strip()
        if not normalized_actor_name:
            raise HTTPException(status_code=400, detail="Actor name cannot be empty")

        conn = get_conn()
        cur = conn.cursor()
        actor = require_actor_permission(cur, x_actor_name, "admin")
        enforce_change_gate_for_direct_update("access_actor")
        seed_default_access_actors(cur)
        serialized_row = upsert_access_actor(
            cur,
            actor_name=normalized_actor_name,
            role=normalized_role,
            description=request.description.strip(),
            tenant_key=request.tenant_key.strip() or "default",
            permission_overrides=[str(item).strip().lower() for item in request.permission_overrides if str(item).strip()],
            admin_actor_name=actor["actor_name"],
            upsert_default_access_quota_fn=upsert_default_access_quota,
            insert_audit_log_fn=insert_audit_log,
        )
        conn.commit()
        cur.close()
        conn.close()
        logger.info("access actor updated actor_name=%s role=%s by=%s", normalized_actor_name, normalized_role, actor["actor_name"])
        return serialized_row

    @router.put("/access/quotas/{actor_name}")
    def update_access_quota(
        actor_name: str,
        request: AccessQuotaUpdate,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        normalized_actor_name = actor_name.strip()
        if not normalized_actor_name:
            raise HTTPException(status_code=400, detail="Actor name cannot be empty")
        if request.daily_task_limit < 0 or request.active_task_limit < 0 or request.daily_token_limit < 0 or request.max_parallel_agents < 0:
            raise HTTPException(status_code=400, detail="Quota values must be non-negative")

        conn = get_conn()
        cur = conn.cursor()
        actor = require_actor_permission(cur, x_actor_name, "admin")
        enforce_change_gate_for_direct_update("access_quota")
        serialized_row = upsert_access_quota(
            cur,
            actor_name=normalized_actor_name,
            daily_task_limit=int(request.daily_task_limit),
            active_task_limit=int(request.active_task_limit),
            daily_token_limit=int(request.daily_token_limit),
            max_parallel_agents=int(request.max_parallel_agents),
            admin_actor_name=actor["actor_name"],
            seed_default_access_quotas_fn=seed_default_access_quotas,
            insert_audit_log_fn=insert_audit_log,
        )
        conn.commit()
        cur.close()
        conn.close()
        logger.info(
            "access quota updated actor_name=%s daily_task_limit=%s active_task_limit=%s daily_token_limit=%s max_parallel_agents=%s by=%s",
            normalized_actor_name,
            request.daily_task_limit,
            request.active_task_limit,
            request.daily_token_limit,
            request.max_parallel_agents,
            actor["actor_name"],
        )
        return serialized_row

    @router.put("/risk-policies/{policy_key}")
    def update_risk_policy(
        policy_key: str,
        request: RiskPolicyUpdate,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        value_type, serialized_value = validate_policy_value(policy_key, request.policy_value)

        conn = get_conn()
        cur = conn.cursor()
        actor = require_actor_permission(cur, x_actor_name, "admin")
        enforce_change_gate_for_direct_update("risk_policy")
        serialized_row = update_risk_policy_entry(
            cur,
            policy_key=policy_key,
            value_type=value_type,
            serialized_value=serialized_value,
            policy_value=request.policy_value,
            actor_name=actor["actor_name"],
            actor_role=actor["role"],
            seed_default_risk_policies_fn=seed_default_risk_policies,
            insert_audit_log_fn=insert_audit_log,
            deserialize_policy_row_fn=deserialize_policy_row,
        )
        conn.commit()
        cur.close()
        conn.close()

        logger.info("risk policy updated policy_key=%s actor=%s", policy_key, actor["actor_name"])
        return serialized_row

    @router.get("/audit-logs")
    def list_audit_logs(
        task_id: int | None = None,
        event_type: str | None = None,
        limit: int | None = 50,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = get_conn()
        cur = conn.cursor()
        require_actor_permission(cur, x_actor_name, "read")
        ensure_audit_logs_table(cur)

        where_clauses = []
        params = []
        if task_id:
            where_clauses.append("task_id = %s")
            params.append(task_id)
        if event_type:
            where_clauses.append("event_type = %s")
            params.append(event_type)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        cur.execute(
            f"""
            SELECT id, task_id, event_type, actor, details, created_at
            FROM audit_logs
            {where_sql}
            ORDER BY id DESC
            LIMIT %s;
            """,
            (*params, limit),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        for row in rows:
            row["details"] = parse_maybe_json(row.get("details"))
        return rows

    @router.get("/runtime-metadata")
    def get_runtime_metadata(x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
        conn = get_conn()
        cur = conn.cursor()
        require_actor_permission(cur, x_actor_name, "read")
        cur.close()
        conn.close()
        multi_agent_status = "task_runtime_postrun_v1" if auto_stage5_postrun_enabled else "manager_worker_execute_demo"
        evaluator_status = "task_runtime_postrun_v1" if auto_stage5_postrun_enabled else "proposal_seed_demo"
        evaluator_source = "task_runtime_postrun_v1" if auto_stage5_postrun_enabled else "stage5_finalize_demo"
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "runtime_stage": "stage2",
            "step_request_protocol": {
                "version": step_request_protocol_version,
                "base_type": "StepExecutionRequest",
                "base_fields": step_execution_request_fields,
                "enriched_type": "EnrichedStepExecutionRequest",
                "enriched_extra_fields": enriched_step_execution_request_extra_fields,
            },
            "multi_agent_protocol": {
                "version": multi_agent_protocol_version,
                "roles": ["manager", "specialist", "reviewer", "operator"],
                "artifact_types": ["brief", "plan", "draft", "evidence", "review", "final"],
                "message_types": ["brief", "progress", "request_clarification", "result", "review_decision", "handoff", "escalation"],
                "implementation_status": multi_agent_status,
            },
            "evaluator_protocol": {
                "version": "stage6-evaluator-v1",
                "evaluator_kind": "stage6_quality_gate",
                "source": evaluator_source,
                "implementation_status": evaluator_status,
            },
        }

    return router
