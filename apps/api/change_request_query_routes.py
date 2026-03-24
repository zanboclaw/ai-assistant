from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Header


def register_change_request_query_routes(
    *,
    get_conn: Callable[[], Any],
    require_actor_permission: Callable[[Any, str | None, str], dict[str, Any]],
    ensure_change_requests_table: Callable[[Any], None],
    normalize_change_request_proposal_kind: Callable[[str | None], str],
    change_request_select_fields: str,
    serialize_change_request_row: Callable[[dict[str, Any]], dict[str, Any]],
    serialize_change_request_list_row: Callable[[dict[str, Any]], dict[str, Any]],
    get_change_request_or_404: Callable[[Any, Callable[[Any], None], int], dict[str, Any]],
    collect_change_request_shadow_validation_context: Callable[..., dict[str, Any]],
    parse_optional_int: Callable[[Any], int | None],
    build_workflow_proposal_shadow_validation_status_with_context: Callable[..., dict[str, Any]],
    fetch_latest_workflow_proposal_shadow_validation_with_context: Callable[..., dict[str, Any] | None],
    fetch_task_run_brief_with_context: Callable[..., dict[str, Any] | None],
    build_change_request_shadow_validation_response: Callable[..., dict[str, Any]],
    prepare_change_request_rollback_context: Callable[..., dict[str, Any]],
    build_change_request_rollback_draft: Callable[[dict[str, Any]], dict[str, Any]],
    find_open_rollback_change_request: Callable[[Any, int, Callable[[Any], None]], dict[str, Any] | None],
    attach_patch_artifacts_to_change_request_draft_with_context: Callable[[Any, dict[str, Any]], dict[str, Any]],
    attach_shadow_validation_state_to_change_request_draft_with_context: Callable[[Any, dict[str, Any]], dict[str, Any]],
):
    router = APIRouter()

    @router.get("/change-requests")
    def list_change_requests(
        status: str | None = None,
        target_type: str | None = None,
        proposal_kind: str | None = None,
        limit: int = 20,
        offset: int = 0,
        include_payloads: bool = False,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        normalized_limit = max(1, min(int(limit), 100))
        normalized_offset = max(0, int(offset))
        conn = get_conn()
        cur = conn.cursor()
        require_actor_permission(cur, x_actor_name, "read")
        ensure_change_requests_table(cur)
        where = []
        params: list[Any] = []
        if status:
            where.append("status = %s")
            params.append(status)
        if target_type:
            where.append("target_type = %s")
            params.append(target_type)
        if proposal_kind:
            where.append("proposal_kind = %s")
            params.append(normalize_change_request_proposal_kind(proposal_kind))
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        cur.execute(
            f"""
            SELECT {change_request_select_fields}
            FROM change_requests
            {where_sql}
            ORDER BY id DESC
            LIMIT %s
            OFFSET %s;
            """,
            [*params, normalized_limit, normalized_offset],
        )
        serialize_row = serialize_change_request_row if include_payloads else serialize_change_request_list_row
        rows = [serialize_row(row) for row in cur.fetchall()]
        cur.close()
        conn.close()
        return rows

    @router.get("/change-requests/{change_request_id}")
    def get_change_request(
        change_request_id: int,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = get_conn()
        cur = conn.cursor()
        try:
            require_actor_permission(cur, x_actor_name, "read")
            return get_change_request_or_404(cur, ensure_change_requests_table, change_request_id)
        finally:
            cur.close()
            conn.close()

    @router.get("/change-requests/{change_request_id}/shadow-validation")
    def get_change_request_shadow_validation(
        change_request_id: int,
        history_limit: int = 10,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = get_conn()
        cur = conn.cursor()
        try:
            require_actor_permission(cur, x_actor_name, "read")
            change_request = get_change_request_or_404(cur, ensure_change_requests_table, change_request_id)
            shadow_validation_context = collect_change_request_shadow_validation_context(
                change_request=change_request,
                history_limit=history_limit,
                parse_optional_int_fn=parse_optional_int,
                build_workflow_proposal_shadow_validation_status_fn=lambda proposal_id, **kwargs: (
                    build_workflow_proposal_shadow_validation_status_with_context(cur, proposal_id, **kwargs)
                ),
                fetch_latest_workflow_proposal_shadow_validation_fn=lambda proposal_id, **kwargs: (
                    fetch_latest_workflow_proposal_shadow_validation_with_context(cur, proposal_id, **kwargs)
                ),
                fetch_task_run_brief_fn=lambda task_id: fetch_task_run_brief_with_context(cur, task_id),
            )
            return build_change_request_shadow_validation_response(
                change_request=change_request,
                proposal_shadow_validation=shadow_validation_context["proposal_shadow_validation"],
                latest_matching_validation=shadow_validation_context["latest_matching_validation"],
                latest_proposal_validation=shadow_validation_context["latest_proposal_validation"],
                latest_shadow_task=shadow_validation_context["latest_shadow_task"],
                parse_optional_int_fn=parse_optional_int,
            )
        finally:
            cur.close()
            conn.close()

    @router.get("/change-requests/{change_request_id}/rollback-draft")
    def preview_change_request_rollback_draft(
        change_request_id: int,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = get_conn()
        cur = conn.cursor()
        try:
            require_actor_permission(cur, x_actor_name, "read")
            rollback_context = prepare_change_request_rollback_context(
                change_request_id=change_request_id,
                get_change_request_fn=lambda current_change_request_id: get_change_request_or_404(
                    cur,
                    ensure_change_requests_table,
                    current_change_request_id,
                ),
                build_change_request_rollback_draft_fn=build_change_request_rollback_draft,
                find_open_rollback_change_request_fn=lambda current_change_request_id: find_open_rollback_change_request(
                    cur,
                    current_change_request_id,
                    ensure_change_requests_table,
                ),
            )
            draft = rollback_context["draft"]
            draft = attach_patch_artifacts_to_change_request_draft_with_context(cur, draft)
            draft = attach_shadow_validation_state_to_change_request_draft_with_context(cur, draft)
            existing = rollback_context["existing_rollback_change_request"]
            draft["existing_rollback_change_request"] = serialize_change_request_row(existing) if existing else None
            return draft
        finally:
            cur.close()
            conn.close()

    return router
