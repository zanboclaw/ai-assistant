from __future__ import annotations

from typing import Any


def apply_sandbox_file_payload(
    target_key: str,
    normalized_payload: dict[str, Any],
    *,
    resolve_sandbox_change_path_fn,
    file_encoding: str,
    http_exception_cls,
) -> None:
    path = resolve_sandbox_change_path_fn(target_key)
    if normalized_payload["exists"]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(normalized_payload["content"], encoding=file_encoding)
    elif path.exists():
        if path.is_dir():
            raise http_exception_cls(status_code=400, detail=f"sandbox_file target points to a directory: {target_key}")
        path.unlink()


def apply_risk_policy_payload(
    cur,
    target_key: str,
    payload: dict[str, Any],
    *,
    seed_default_risk_policies_fn,
    risk_policy_map: dict[str, Any],
    safe_json_dumps_fn,
    http_exception_cls,
) -> None:
    seed_default_risk_policies_fn(cur)
    policy = risk_policy_map.get(target_key)
    if not policy:
        raise http_exception_cls(status_code=404, detail=f"Risk policy not found: {target_key}")
    value = payload.get("policy_value")
    cur.execute(
        """
        UPDATE risk_policies
        SET policy_value = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE policy_key = %s;
        """,
        (safe_json_dumps_fn(value), target_key),
    )


def apply_tool_registry_payload(
    cur,
    target_key: str,
    payload: dict[str, Any],
    *,
    seed_default_tool_registry_fn,
    safe_json_dumps_fn,
    http_exception_cls,
) -> None:
    seed_default_tool_registry_fn(cur)
    risk_level = str(payload.get("risk_level") or "").strip().lower()
    if risk_level not in {"low", "medium", "high"}:
        raise http_exception_cls(status_code=400, detail=f"Unsupported risk level: {risk_level}")
    provider_type = str(payload.get("provider_type") or "builtin").strip().lower()
    if provider_type not in {"builtin", "mcp_stdio", "mcp_http"}:
        raise http_exception_cls(status_code=400, detail=f"Unsupported provider_type: {provider_type}")
    transport = str(payload.get("transport") or ("local" if provider_type == "builtin" else "")).strip().lower()
    if transport not in {"", "local", "stdio", "http"}:
        raise http_exception_cls(status_code=400, detail=f"Unsupported transport: {transport}")
    cur.execute(
        """
        INSERT INTO tool_registry_entries (
            tool_name,
            enabled,
            provider_type,
            transport,
            server_name,
            provider_config,
            risk_level,
            approval_required,
            description
        )
        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
        ON CONFLICT (tool_name) DO UPDATE
        SET enabled = EXCLUDED.enabled,
            provider_type = EXCLUDED.provider_type,
            transport = EXCLUDED.transport,
            server_name = EXCLUDED.server_name,
            provider_config = EXCLUDED.provider_config,
            risk_level = EXCLUDED.risk_level,
            approval_required = EXCLUDED.approval_required,
            description = EXCLUDED.description,
            updated_at = CURRENT_TIMESTAMP;
        """,
        (
            target_key,
            bool(payload.get("enabled")),
            provider_type,
            transport,
            str(payload.get("server_name") or "").strip(),
            safe_json_dumps_fn(payload.get("provider_config") or {}),
            risk_level,
            bool(payload.get("approval_required")),
            str(payload.get("description") or "").strip(),
        ),
    )


def apply_model_route_payload(
    cur,
    target_key: str,
    payload: dict[str, Any],
    *,
    seed_default_model_providers_fn,
    seed_default_model_routes_fn,
    http_exception_cls,
) -> None:
    seed_default_model_providers_fn(cur)
    seed_default_model_routes_fn(cur)
    provider = str(payload.get("provider") or "").strip()
    if not provider:
        raise http_exception_cls(status_code=400, detail="provider is required")
    cur.execute("SELECT provider_name FROM model_providers WHERE provider_name = %s;", (provider,))
    if not cur.fetchone():
        raise http_exception_cls(status_code=404, detail=f"Model provider not found: {provider}")
    model_name = str(payload.get("model_name") or "").strip()
    if not model_name:
        raise http_exception_cls(status_code=400, detail="model_name is required")
    max_tokens = int(payload.get("max_tokens") or 0)
    if max_tokens <= 0:
        raise http_exception_cls(status_code=400, detail="max_tokens must be positive")
    cur.execute(
        """
        UPDATE model_routes
        SET provider = %s,
            model_name = %s,
            temperature = %s,
            max_tokens = %s,
            enabled = %s,
            description = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE route_name = %s;
        """,
        (
            provider,
            model_name,
            float(payload.get("temperature") or 0.2),
            max_tokens,
            bool(payload.get("enabled")),
            str(payload.get("description") or "").strip(),
            target_key,
        ),
    )
    if cur.rowcount == 0:
        raise http_exception_cls(status_code=404, detail=f"Model route not found: {target_key}")


def apply_model_provider_payload(
    cur,
    target_key: str,
    payload: dict[str, Any],
    *,
    seed_default_model_providers_fn,
    http_exception_cls,
) -> None:
    seed_default_model_providers_fn(cur)
    driver = str(payload.get("driver") or "").strip()
    if driver not in {"openai_compatible"}:
        raise http_exception_cls(status_code=400, detail=f"Unsupported provider driver: {driver}")
    base_url = str(payload.get("base_url") or "").strip()
    api_key_env = str(payload.get("api_key_env") or "").strip()
    if not base_url:
        raise http_exception_cls(status_code=400, detail="base_url is required")
    if not api_key_env:
        raise http_exception_cls(status_code=400, detail="api_key_env is required")
    cur.execute(
        """
        INSERT INTO model_providers (provider_name, driver, base_url, api_key_env, enabled, description)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (provider_name)
        DO UPDATE SET driver = EXCLUDED.driver,
                      base_url = EXCLUDED.base_url,
                      api_key_env = EXCLUDED.api_key_env,
                      enabled = EXCLUDED.enabled,
                      description = EXCLUDED.description,
                      updated_at = CURRENT_TIMESTAMP;
        """,
        (
            target_key,
            driver,
            base_url,
            api_key_env,
            bool(payload.get("enabled")),
            str(payload.get("description") or "").strip(),
        ),
    )


def apply_access_quota_payload(cur, target_key: str, payload: dict[str, Any], *, seed_default_access_quotas_fn, http_exception_cls) -> None:
    seed_default_access_quotas_fn(cur)
    cur.execute(
        """
        UPDATE access_quotas
        SET daily_task_limit = %s,
            active_task_limit = %s,
            daily_token_limit = %s,
            max_parallel_agents = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE actor_name = %s;
        """,
        (
            int(payload.get("daily_task_limit") or 0),
            int(payload.get("active_task_limit") or 0),
            int(payload.get("daily_token_limit") or 0),
            int(payload.get("max_parallel_agents") or 0),
            target_key,
        ),
    )
    if cur.rowcount == 0:
        raise http_exception_cls(status_code=404, detail=f"Quota not found for actor: {target_key}")


def apply_access_actor_payload(
    cur,
    target_key: str,
    payload: dict[str, Any],
    *,
    seed_default_access_actors_fn,
    access_role_permissions: dict[str, Any],
    safe_json_dumps_fn,
    upsert_default_access_quota_fn,
    http_exception_cls,
) -> None:
    seed_default_access_actors_fn(cur)
    role = str(payload.get("role") or "").strip()
    if role not in access_role_permissions:
        raise http_exception_cls(status_code=400, detail=f"Unsupported role: {role}")
    permission_overrides = [
        str(item).strip().lower()
        for item in (payload.get("permission_overrides") or [])
        if str(item).strip()
    ]
    cur.execute(
        """
        INSERT INTO access_actors (actor_name, role, description, tenant_key, permission_overrides)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (actor_name)
        DO UPDATE SET role = EXCLUDED.role,
                      description = EXCLUDED.description,
                      tenant_key = EXCLUDED.tenant_key,
                      permission_overrides = EXCLUDED.permission_overrides,
                      updated_at = CURRENT_TIMESTAMP;
        """,
        (
            target_key,
            role,
            str(payload.get("description") or "").strip(),
            str(payload.get("tenant_key") or "default").strip() or "default",
            safe_json_dumps_fn(permission_overrides),
        ),
    )
    upsert_default_access_quota_fn(cur, target_key, role)


def apply_change_request_payload_with_context(
    cur,
    target_type: str,
    target_key: str,
    payload: dict[str, Any],
    *,
    apply_change_request_payload_fn,
    normalize_sandbox_file_payload_fn,
    apply_sandbox_file_payload_fn,
    apply_risk_policy_payload_fn,
    apply_tool_registry_payload_fn,
    apply_model_route_payload_fn,
    apply_model_provider_payload_fn,
    apply_access_quota_payload_fn,
    apply_access_actor_payload_fn,
) -> None:
    return apply_change_request_payload_fn(
        target_type=target_type,
        target_key=target_key,
        payload=payload,
        normalize_sandbox_file_payload_fn=normalize_sandbox_file_payload_fn,
        apply_sandbox_file_payload_fn=lambda current_target_key, normalized_payload: (
            apply_sandbox_file_payload_fn(current_target_key, normalized_payload)
        ),
        apply_risk_policy_fn=lambda current_target_key, current_payload: (
            apply_risk_policy_payload_fn(cur, current_target_key, current_payload)
        ),
        apply_tool_registry_fn=lambda current_target_key, current_payload: (
            apply_tool_registry_payload_fn(cur, current_target_key, current_payload)
        ),
        apply_model_route_fn=lambda current_target_key, current_payload: (
            apply_model_route_payload_fn(cur, current_target_key, current_payload)
        ),
        apply_model_provider_fn=lambda current_target_key, current_payload: (
            apply_model_provider_payload_fn(cur, current_target_key, current_payload)
        ),
        apply_access_quota_fn=lambda current_target_key, current_payload: (
            apply_access_quota_payload_fn(cur, current_target_key, current_payload)
        ),
        apply_access_actor_fn=lambda current_target_key, current_payload: (
            apply_access_actor_payload_fn(cur, current_target_key, current_payload)
        ),
    )


def create_and_apply_automatic_rollback_change_request(
    cur,
    *,
    source_change_request: dict[str, Any],
    actor_name: str,
    reason: str,
    build_change_request_rollback_draft_fn,
    create_change_request_row_fn,
    serialize_change_request_row_fn,
    insert_audit_log_fn,
    fetch_change_target_state_for_rollback_with_context_fn,
    apply_change_request_payload_with_context_fn,
    safe_json_dumps_fn,
    change_request_select_fields: str,
    http_exception_cls,
) -> dict[str, Any]:
    draft = build_change_request_rollback_draft_fn(source_change_request)
    if not draft["rollback_ready"]:
        raise http_exception_cls(status_code=409, detail=draft["rollback_note"] or "Rollback draft is not ready")

    row = create_change_request_row_fn(
        cur,
        target_type=draft["target_type"],
        target_key=draft["target_key"],
        proposed_payload=draft["proposed_payload"],
        rationale=draft["rationale"],
        requested_by_actor=actor_name,
        proposal_kind="rollback",
        source_change_request_id=int(source_change_request["id"]),
        source_workflow_proposal_id=source_change_request.get("source_workflow_proposal_id"),
    )
    rollback_change_request_id = int(row["id"])
    serialized_created_row = serialize_change_request_row_fn(row)
    insert_audit_log_fn(
        cur,
        "change_request.rollback_create",
        actor_name,
        None,
        {
            "source_change_request_id": int(source_change_request["id"]),
            "rollback_change_request_id": rollback_change_request_id,
            "target_type": source_change_request["target_type"],
            "target_key": source_change_request["target_key"],
            "patch_summary": serialized_created_row["patch_summary"],
            "auto_created": True,
            "reason": reason,
        },
    )

    rollback_payload = fetch_change_target_state_for_rollback_with_context_fn(
        cur,
        target_type=draft["target_type"],
        target_key=draft["target_key"],
    )
    rollback_ready = isinstance(rollback_payload, dict) and bool(rollback_payload)
    rollback_note = (
        "Captured pre-change baseline for rollback."
        if rollback_ready
        else "No baseline target state found before apply; rollback draft requires manual recovery."
    )
    apply_change_request_payload_with_context_fn(
        cur,
        draft["target_type"],
        draft["target_key"],
        draft["proposed_payload"] or {},
    )
    cur.execute(
        f"""
        UPDATE change_requests
        SET status = 'applied',
            reviewed_by_actor = %s,
            decision_note = %s,
            reviewed_at = CURRENT_TIMESTAMP,
            applied_by_actor = %s,
            applied_at = CURRENT_TIMESTAMP,
            rollback_payload = %s,
            rollback_ready = %s,
            rollback_note = %s
        WHERE id = %s
        RETURNING {change_request_select_fields};
        """,
        (
            actor_name,
            reason,
            actor_name,
            safe_json_dumps_fn(rollback_payload) if rollback_payload is not None else None,
            rollback_ready,
            rollback_note,
            rollback_change_request_id,
        ),
    )
    applied_row = cur.fetchone()
    serialized_applied_row = serialize_change_request_row_fn(applied_row)
    insert_audit_log_fn(
        cur,
        "change_request.apply",
        actor_name,
        None,
        {
            "change_request_id": rollback_change_request_id,
            "target_type": draft["target_type"],
            "target_key": draft["target_key"],
            "proposal_kind": "rollback",
            "patch_summary": serialized_applied_row["patch_summary"],
            "rollback_ready": rollback_ready,
            "auto_created": True,
            "reason": reason,
        },
    )
    insert_audit_log_fn(
        cur,
        "change_request.auto_rollback_apply",
        actor_name,
        None,
        {
            "source_change_request_id": int(source_change_request["id"]),
            "rollback_change_request_id": rollback_change_request_id,
            "target_type": draft["target_type"],
            "target_key": draft["target_key"],
            "reason": reason,
        },
    )
    return serialized_applied_row


def process_change_request_post_apply_with_context(
    cur,
    *,
    change_request_id: int,
    change_request: dict[str, Any],
    normalized_proposed_payload: dict[str, Any],
    rollback_payload: dict[str, Any] | None,
    rollback_ready: bool,
    rollback_note: str,
    actor_name: str,
    process_change_request_post_apply_fn,
    execute_sandbox_file_acceptance_fn,
    make_json_compatible_fn,
    insert_audit_log_fn,
    create_and_apply_automatic_rollback_change_request_fn,
) -> dict[str, Any]:
    return process_change_request_post_apply_fn(
        change_request_id=change_request_id,
        change_request=change_request,
        normalized_proposed_payload=normalized_proposed_payload,
        rollback_payload=rollback_payload,
        rollback_ready=rollback_ready,
        rollback_note=rollback_note,
        actor_name=actor_name,
        execute_sandbox_file_acceptance_fn=execute_sandbox_file_acceptance_fn,
        make_json_compatible_fn=make_json_compatible_fn,
        insert_audit_log_fn=lambda event_type, current_actor_name, task_id, details: (
            insert_audit_log_fn(cur, event_type, current_actor_name, task_id, details)
        ),
        create_and_apply_automatic_rollback_change_request_fn=lambda **kwargs: (
            create_and_apply_automatic_rollback_change_request_fn(cur, **kwargs)
        ),
    )


def update_reviewed_change_request_row(
    cur,
    *,
    change_request_id: int,
    actor_name: str,
    note: str,
    next_status: str,
    change_request_select_fields: str,
):
    cur.execute(
        f"""
        UPDATE change_requests
        SET status = %s,
            reviewed_by_actor = %s,
            decision_note = %s,
            reviewed_at = CURRENT_TIMESTAMP
        WHERE id = %s
        RETURNING {change_request_select_fields};
        """,
        (next_status, actor_name, note, change_request_id),
    )
    return cur.fetchone()


def update_applied_change_request_row(
    cur,
    *,
    change_request_id: int,
    actor_name: str,
    rollback_payload: dict[str, Any] | None,
    rollback_ready: bool,
    rollback_note: str,
    acceptance_status: str,
    acceptance_report: str | None,
    acceptance_at,
    auto_rollback_change_request_id: int | None,
    auto_rollback_at,
    safe_json_dumps_fn,
    change_request_select_fields: str,
):
    cur.execute(
        f"""
        UPDATE change_requests
        SET status = 'applied',
            applied_by_actor = %s,
            applied_at = CURRENT_TIMESTAMP,
            rollback_payload = %s,
            rollback_ready = %s,
            rollback_note = %s,
            acceptance_status = %s,
            acceptance_report = %s,
            acceptance_at = %s,
            auto_rollback_change_request_id = %s,
            auto_rollback_at = %s
        WHERE id = %s
        RETURNING {change_request_select_fields};
        """,
        (
            actor_name,
            safe_json_dumps_fn(rollback_payload) if rollback_payload is not None else None,
            rollback_ready,
            rollback_note,
            acceptance_status,
            acceptance_report,
            acceptance_at,
            auto_rollback_change_request_id,
            auto_rollback_at,
            change_request_id,
        ),
    )
    return cur.fetchone()
