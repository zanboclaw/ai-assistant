from typing import Any

from fastapi import HTTPException

from change_request_helpers import CHANGE_REQUEST_SELECT_FIELDS
from change_request_serializers import serialize_change_request_row


def compute_change_payload_patch(
    baseline_payload: dict[str, Any] | None,
    proposed_payload: dict[str, Any] | None,
) -> tuple[dict[str, Any], str]:
    baseline = baseline_payload or {}
    proposed = proposed_payload or {}
    if not isinstance(baseline, dict) or not isinstance(proposed, dict):
        return {}, ""

    added: dict[str, Any] = {}
    removed: dict[str, Any] = {}
    changed: dict[str, dict[str, Any]] = {}

    for key in sorted(proposed.keys()):
        if key not in baseline:
            added[key] = proposed[key]
        elif baseline[key] != proposed[key]:
            changed[key] = {
                "from": baseline[key],
                "to": proposed[key],
            }

    for key in sorted(baseline.keys()):
        if key not in proposed:
            removed[key] = baseline[key]

    patch = {
        "format": "json_object_diff_v1",
        "added": added,
        "removed": removed,
        "changed": changed,
        "changed_key_count": len(added) + len(removed) + len(changed),
    }

    summary_parts: list[str] = []
    if added:
        summary_parts.append("add " + ", ".join(sorted(added.keys())))
    if changed:
        summary_parts.append("change " + ", ".join(sorted(changed.keys())))
    if removed:
        summary_parts.append("remove " + ", ".join(sorted(removed.keys())))
    return patch, "; ".join(summary_parts)


def fetch_change_request_row(cur, ensure_change_requests_table_fn=None, change_request_id: int = 0) -> dict[str, Any] | None:
    if ensure_change_requests_table_fn is not None:
        ensure_change_requests_table_fn(cur)
    cur.execute(
        f"""
        SELECT {CHANGE_REQUEST_SELECT_FIELDS}
        FROM change_requests
        WHERE id = %s;
        """,
        (change_request_id,),
    )
    return cur.fetchone()


def get_change_request_or_404(cur, ensure_change_requests_table_fn=None, change_request_id: int = 0) -> dict[str, Any]:
    row = fetch_change_request_row(cur, ensure_change_requests_table_fn, change_request_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"Change request not found: {change_request_id}")
    return serialize_change_request_row(row)


def find_open_rollback_change_request(
    cur,
    source_change_request_id: int,
    ensure_change_requests_table_fn=None,
) -> dict[str, Any] | None:
    if ensure_change_requests_table_fn is not None:
        ensure_change_requests_table_fn(cur)
    cur.execute(
        f"""
        SELECT {CHANGE_REQUEST_SELECT_FIELDS}
        FROM change_requests
        WHERE proposal_kind = 'rollback'
          AND source_change_request_id = %s
          AND status IN ('pending', 'approved', 'applied')
        ORDER BY id DESC
        LIMIT 1;
        """,
        (source_change_request_id,),
    )
    return cur.fetchone()


def serialize_shadow_validation_audit_row(
    row: dict[str, Any],
    *,
    make_json_compatible_fn,
    parse_maybe_json_fn,
    parse_optional_int_fn,
) -> dict[str, Any]:
    details = make_json_compatible_fn(parse_maybe_json_fn(row.get("details")) or {})
    event_type = str(row.get("event_type") or "")
    serialized = {
        "audit_log_id": int(row["id"]),
        "event_type": event_type,
        "task_id": parse_optional_int_fn(row.get("task_id")),
        "proposal_id": parse_optional_int_fn(details.get("proposal_id")),
        "baseline_task_id": parse_optional_int_fn(details.get("baseline_task_id") or row.get("task_id")),
        "shadow_task_id": parse_optional_int_fn(details.get("shadow_task_id")),
        "actor": row.get("actor") or "",
        "created_at": make_json_compatible_fn(row.get("created_at")),
        "details": details,
    }
    if event_type.endswith("shadow_validation"):
        serialized["request"] = details
    elif event_type.endswith("shadow_validated"):
        serialized["validation"] = details
        serialized["validated_at"] = make_json_compatible_fn(row.get("created_at"))
        serialized["validated_at_timestamp"] = row.get("created_at")
        serialized["validated_by_actor"] = row.get("actor") or ""
    return serialized


def fetch_workflow_proposal_shadow_validation_history(
    cur,
    proposal_id: int,
    *,
    limit: int = 10,
    ensure_audit_logs_table_fn=None,
    request_event: str,
    result_event: str,
    serialize_shadow_validation_audit_row_fn,
) -> list[dict[str, Any]]:
    if proposal_id <= 0:
        return []
    if ensure_audit_logs_table_fn is not None:
        ensure_audit_logs_table_fn(cur)
    normalized_limit = max(1, min(int(limit or 10), 50))
    cur.execute(
        """
        SELECT id, task_id, event_type, actor, details, created_at
        FROM audit_logs
        WHERE event_type IN (%s, %s)
          AND COALESCE(details ->> 'proposal_id', '') = %s
        ORDER BY id DESC
        LIMIT %s;
        """,
        (
            request_event,
            result_event,
            str(proposal_id),
            normalized_limit,
        ),
    )
    return [serialize_shadow_validation_audit_row_fn(row) for row in cur.fetchall()]


def fetch_task_run_brief(
    cur,
    task_id: int | None,
    *,
    parse_optional_int_fn,
    parse_maybe_json_fn,
) -> dict[str, Any] | None:
    normalized_task_id = parse_optional_int_fn(task_id)
    if normalized_task_id is None or normalized_task_id <= 0:
        return None
    cur.execute(
        """
        SELECT id, session_id, user_input, created_by_actor, status, runtime_overrides, created_at, updated_at
        FROM task_runs
        WHERE id = %s;
        """,
        (normalized_task_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return {
        "id": int(row["id"]),
        "session_id": parse_optional_int_fn(row.get("session_id")),
        "user_input": row.get("user_input") or "",
        "created_by_actor": row.get("created_by_actor") or "",
        "status": row.get("status") or "",
        "runtime_overrides": parse_maybe_json_fn(row.get("runtime_overrides")) or {},
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def fetch_latest_workflow_proposal_shadow_validation(
    cur,
    proposal_id: int,
    *,
    target_type: str = "",
    target_key: str = "",
    proposed_payload: dict[str, Any] | None = None,
    history_limit: int = 50,
    fetch_workflow_proposal_shadow_validation_history_fn,
    result_event: str,
    shadow_validation_candidate_matches_fn,
) -> dict[str, Any] | None:
    history = fetch_workflow_proposal_shadow_validation_history_fn(cur, proposal_id, limit=history_limit)
    validation_rows = [entry for entry in history if entry.get("event_type") == result_event]
    if not target_type and not target_key and proposed_payload is None:
        return validation_rows[0] if validation_rows else None
    for entry in validation_rows:
        if shadow_validation_candidate_matches_fn(
            entry,
            target_type=target_type,
            target_key=target_key,
            proposed_payload=proposed_payload,
        ):
            return entry
    return None


def build_workflow_proposal_shadow_validation_status(
    cur,
    proposal_id: int,
    *,
    history_limit: int = 10,
    supported: bool = True,
    fetch_workflow_proposal_shadow_validation_history_fn,
    fetch_task_run_brief_fn,
    parse_optional_int_fn,
    request_event: str,
    result_event: str,
) -> dict[str, Any]:
    history = fetch_workflow_proposal_shadow_validation_history_fn(cur, proposal_id, limit=history_limit)
    latest_request = next((entry for entry in history if entry.get("event_type") == request_event), None)
    latest_validation = next((entry for entry in history if entry.get("event_type") == result_event), None)
    latest_shadow_task_id = parse_optional_int_fn(
        (latest_request or {}).get("shadow_task_id") or (latest_validation or {}).get("shadow_task_id")
    )
    if not supported:
        status = "not_supported"
    elif latest_request and (
        not latest_validation or int(latest_request["audit_log_id"]) > int(latest_validation["audit_log_id"])
    ):
        status = "requested"
    elif latest_validation:
        status = "completed"
    else:
        status = "not_started"

    return {
        "proposal_id": proposal_id,
        "supported": bool(supported),
        "status": status,
        "history_count": len(history),
        "request_count": sum(1 for entry in history if entry.get("event_type") == request_event),
        "validation_count": sum(1 for entry in history if entry.get("event_type") == result_event),
        "latest_request": latest_request,
        "latest_validation": latest_validation,
        "latest_shadow_task": fetch_task_run_brief_fn(cur, latest_shadow_task_id),
        "history": history,
    }


def sync_change_requests_shadow_validation(
    cur,
    proposal_id: int,
    *,
    ensure_change_requests_table_fn=None,
    parse_maybe_json_fn,
    parse_optional_int_fn,
    build_change_request_shadow_validation_state_fn,
    safe_json_dumps_fn,
) -> int:
    if ensure_change_requests_table_fn is not None:
        ensure_change_requests_table_fn(cur)
    cur.execute(
        f"""
        SELECT {CHANGE_REQUEST_SELECT_FIELDS}
        FROM change_requests
        WHERE proposal_kind = 'workflow_improvement'
          AND source_workflow_proposal_id = %s
          AND status IN ('pending', 'approved');
        """,
        (proposal_id,),
    )
    rows = cur.fetchall()
    updated_count = 0
    for row in rows:
        proposed_payload = parse_maybe_json_fn(row.get("proposed_payload")) or {}
        shadow_validation_state = build_change_request_shadow_validation_state_fn(
            proposal_kind=row.get("proposal_kind"),
            source_workflow_proposal_id=parse_optional_int_fn(row.get("source_workflow_proposal_id")),
            target_type=str(row.get("target_type") or "").strip(),
            target_key=str(row.get("target_key") or "").strip(),
            proposed_payload=proposed_payload,
        )
        cur.execute(
            """
            UPDATE change_requests
            SET shadow_validation_status = %s,
                shadow_validation_report = %s,
                shadow_validation_at = %s
            WHERE id = %s;
            """,
            (
                shadow_validation_state["shadow_validation_status"],
                safe_json_dumps_fn(shadow_validation_state["shadow_validation_report"])
                if shadow_validation_state["shadow_validation_report"]
                else None,
                shadow_validation_state["shadow_validation_at"],
                int(row["id"]),
            ),
        )
        updated_count += cur.rowcount
    return updated_count


def insert_change_request_row(
    cur,
    *,
    change_request_payload: dict[str, Any],
    safe_json_dumps_fn,
) -> dict[str, Any]:
    cur.execute(
        f"""
        INSERT INTO change_requests (
            target_type, target_key, proposed_payload, rationale, status, requested_by_actor,
            proposal_kind, source_change_request_id, source_workflow_proposal_id,
            shadow_validation_status, shadow_validation_report, shadow_validation_at,
            baseline_payload, payload_patch, patch_summary
        )
        VALUES (%s, %s, %s, %s, 'pending', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING {CHANGE_REQUEST_SELECT_FIELDS};
        """,
        (
            change_request_payload["target_type"],
            change_request_payload["target_key"],
            safe_json_dumps_fn(change_request_payload["proposed_payload"]),
            change_request_payload["rationale"],
            change_request_payload["requested_by_actor"],
            change_request_payload["proposal_kind"],
            change_request_payload["source_change_request_id"],
            change_request_payload["source_workflow_proposal_id"],
            change_request_payload["shadow_validation_status"],
            safe_json_dumps_fn(change_request_payload["shadow_validation_report"])
            if change_request_payload["shadow_validation_report"]
            else None,
            change_request_payload["shadow_validation_at"],
            safe_json_dumps_fn(change_request_payload["baseline_payload"])
            if change_request_payload["baseline_payload"]
            else None,
            safe_json_dumps_fn(change_request_payload["payload_patch"])
            if change_request_payload["payload_patch"]
            else None,
            change_request_payload["patch_summary"],
        ),
    )
    return cur.fetchone()


def fetch_change_target_state_for_rollback(
    cur,
    *,
    target_type: str,
    target_key: str,
    fetch_sandbox_file_state_fn,
    seed_default_risk_policies_fn,
    deserialize_policy_row_fn,
    seed_default_tool_registry_fn,
    serialize_tool_registry_row_fn,
    seed_default_model_providers_fn,
    seed_default_model_routes_fn,
    serialize_model_route_row_fn,
    serialize_model_provider_row_fn,
    seed_default_access_quotas_fn,
    serialize_access_quota_row_fn,
    seed_default_access_actors_fn,
    serialize_access_actor_row_fn,
) -> dict[str, Any] | None:
    if target_type == "sandbox_file":
        return fetch_sandbox_file_state_fn(target_key)

    if target_type == "risk_policy":
        seed_default_risk_policies_fn(cur)
        cur.execute(
            """
            SELECT policy_key, value_type, policy_value, description, created_at, updated_at
            FROM risk_policies
            WHERE policy_key = %s;
            """,
            (target_key,),
        )
        row = cur.fetchone()
        if not row:
            return None
        policy = deserialize_policy_row_fn(row)
        return {"policy_value": policy.get("policy_value")}

    if target_type == "tool_registry":
        seed_default_tool_registry_fn(cur)
        cur.execute(
            """
            SELECT tool_name, enabled, risk_level, description, created_at, updated_at
            FROM tool_registry_entries
            WHERE tool_name = %s;
            """,
            (target_key,),
        )
        row = cur.fetchone()
        if not row:
            return None
        item = serialize_tool_registry_row_fn(row)
        return {
            "enabled": item.get("enabled"),
            "risk_level": item.get("risk_level"),
            "description": item.get("description") or "",
        }

    if target_type == "model_route":
        seed_default_model_providers_fn(cur)
        seed_default_model_routes_fn(cur)
        cur.execute(
            """
            SELECT route_name, provider, model_name, temperature, max_tokens, enabled, description, created_at, updated_at
            FROM model_routes
            WHERE route_name = %s;
            """,
            (target_key,),
        )
        row = cur.fetchone()
        if not row:
            return None
        route = serialize_model_route_row_fn(row)
        return {
            "provider": route.get("provider"),
            "model_name": route.get("model_name"),
            "temperature": route.get("temperature"),
            "max_tokens": route.get("max_tokens"),
            "enabled": route.get("enabled"),
            "description": route.get("description") or "",
        }

    if target_type == "model_provider":
        seed_default_model_providers_fn(cur)
        cur.execute(
            """
            SELECT provider_name, driver, base_url, api_key_env, enabled, description, created_at, updated_at
            FROM model_providers
            WHERE provider_name = %s;
            """,
            (target_key,),
        )
        row = cur.fetchone()
        if not row:
            return None
        provider = serialize_model_provider_row_fn(row)
        return {
            "driver": provider.get("driver"),
            "base_url": provider.get("base_url"),
            "api_key_env": provider.get("api_key_env"),
            "enabled": provider.get("enabled"),
            "description": provider.get("description") or "",
        }

    if target_type == "access_quota":
        seed_default_access_quotas_fn(cur)
        cur.execute(
            """
            SELECT actor_name, daily_task_limit, active_task_limit, created_at, updated_at
            FROM access_quotas
            WHERE actor_name = %s;
            """,
            (target_key,),
        )
        row = cur.fetchone()
        if not row:
            return None
        quota = serialize_access_quota_row_fn(row)
        return {
            "daily_task_limit": quota.get("daily_task_limit"),
            "active_task_limit": quota.get("active_task_limit"),
        }

    if target_type == "access_actor":
        seed_default_access_actors_fn(cur)
        cur.execute(
            """
            SELECT actor_name, role, description, created_at, updated_at
            FROM access_actors
            WHERE actor_name = %s;
            """,
            (target_key,),
        )
        row = cur.fetchone()
        if not row:
            return None
        actor = serialize_access_actor_row_fn(row)
        return {
            "role": actor.get("role"),
            "description": actor.get("description") or "",
        }

    raise HTTPException(status_code=400, detail=f"Unsupported change target type: {target_type}")
