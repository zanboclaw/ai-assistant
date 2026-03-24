from __future__ import annotations

from typing import Any, Callable


def serialize_shadow_validation_audit_row_with_context(
    row: dict[str, Any],
    *,
    serialize_shadow_validation_audit_row_fn: Callable[..., dict[str, Any]],
    make_json_compatible_fn: Callable[[Any], Any],
    parse_maybe_json_fn: Callable[[Any], Any],
    parse_optional_int_fn: Callable[[Any], int | None],
) -> dict[str, Any]:
    return serialize_shadow_validation_audit_row_fn(
        row,
        make_json_compatible_fn=make_json_compatible_fn,
        parse_maybe_json_fn=parse_maybe_json_fn,
        parse_optional_int_fn=parse_optional_int_fn,
    )


def fetch_workflow_proposal_shadow_validation_history_with_context(
    cur,
    proposal_id: int,
    *,
    fetch_workflow_proposal_shadow_validation_history_fn: Callable[..., list[dict[str, Any]]],
    ensure_audit_logs_table_fn: Callable[[Any], None],
    request_event: str,
    result_event: str,
    serialize_shadow_validation_audit_row_with_context_fn: Callable[[dict[str, Any]], dict[str, Any]],
    limit: int = 10,
) -> list[dict[str, Any]]:
    return fetch_workflow_proposal_shadow_validation_history_fn(
        cur,
        proposal_id,
        limit=limit,
        ensure_audit_logs_table_fn=ensure_audit_logs_table_fn,
        request_event=request_event,
        result_event=result_event,
        serialize_shadow_validation_audit_row_fn=serialize_shadow_validation_audit_row_with_context_fn,
    )


def fetch_task_run_brief_with_context(
    cur,
    task_id: int | None,
    *,
    fetch_task_run_brief_fn: Callable[..., dict[str, Any] | None],
    parse_optional_int_fn: Callable[[Any], int | None],
    parse_maybe_json_fn: Callable[[Any], Any],
) -> dict[str, Any] | None:
    return fetch_task_run_brief_fn(
        cur,
        task_id,
        parse_optional_int_fn=parse_optional_int_fn,
        parse_maybe_json_fn=parse_maybe_json_fn,
    )


def fetch_latest_workflow_proposal_shadow_validation_with_context(
    cur,
    proposal_id: int,
    *,
    fetch_latest_workflow_proposal_shadow_validation_fn: Callable[..., dict[str, Any] | None],
    fetch_workflow_proposal_shadow_validation_history_with_context_fn: Callable[..., list[dict[str, Any]]],
    shadow_validation_candidate_matches_fn: Callable[..., bool],
    result_event: str,
    target_type: str = "",
    target_key: str = "",
    proposed_payload: dict[str, Any] | None = None,
    history_limit: int = 50,
) -> dict[str, Any] | None:
    return fetch_latest_workflow_proposal_shadow_validation_fn(
        cur,
        proposal_id,
        target_type=target_type,
        target_key=target_key,
        proposed_payload=proposed_payload,
        history_limit=history_limit,
        fetch_workflow_proposal_shadow_validation_history_fn=fetch_workflow_proposal_shadow_validation_history_with_context_fn,
        result_event=result_event,
        shadow_validation_candidate_matches_fn=shadow_validation_candidate_matches_fn,
    )


def build_workflow_proposal_shadow_validation_status_with_context(
    cur,
    proposal_id: int,
    *,
    build_workflow_proposal_shadow_validation_status_fn: Callable[..., dict[str, Any]],
    fetch_workflow_proposal_shadow_validation_history_with_context_fn: Callable[..., list[dict[str, Any]]],
    fetch_task_run_brief_with_context_fn: Callable[..., dict[str, Any] | None],
    parse_optional_int_fn: Callable[[Any], int | None],
    request_event: str,
    result_event: str,
    history_limit: int = 10,
    supported: bool = True,
) -> dict[str, Any]:
    return build_workflow_proposal_shadow_validation_status_fn(
        cur,
        proposal_id,
        history_limit=history_limit,
        supported=supported,
        fetch_workflow_proposal_shadow_validation_history_fn=fetch_workflow_proposal_shadow_validation_history_with_context_fn,
        fetch_task_run_brief_fn=fetch_task_run_brief_with_context_fn,
        parse_optional_int_fn=parse_optional_int_fn,
        request_event=request_event,
        result_event=result_event,
    )


def build_change_request_shadow_validation_state_with_context(
    cur,
    *,
    build_change_request_shadow_validation_state_fn: Callable[..., dict[str, Any]],
    normalize_change_request_proposal_kind_fn: Callable[[str | None], str],
    change_request_requires_shadow_validation_fn: Callable[[str | None], bool],
    fetch_latest_workflow_proposal_shadow_validation_with_context_fn: Callable[..., dict[str, Any] | None],
    annotate_shadow_validation_report_for_change_request_fn: Callable[..., dict[str, Any]],
    proposal_kind: str | None,
    source_workflow_proposal_id: int | None,
    target_type: str = "",
    target_key: str = "",
    proposed_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_change_request_shadow_validation_state_fn(
        proposal_kind=proposal_kind,
        source_workflow_proposal_id=source_workflow_proposal_id,
        target_type=target_type,
        target_key=target_key,
        proposed_payload=proposed_payload,
        normalize_change_request_proposal_kind_fn=normalize_change_request_proposal_kind_fn,
        change_request_requires_shadow_validation_fn=change_request_requires_shadow_validation_fn,
        fetch_latest_workflow_proposal_shadow_validation_fn=lambda proposal_id, **kwargs: (
            fetch_latest_workflow_proposal_shadow_validation_with_context_fn(cur, proposal_id, **kwargs)
        ),
        annotate_shadow_validation_report_for_change_request_fn=annotate_shadow_validation_report_for_change_request_fn,
    )


def sync_change_requests_shadow_validation_with_context(
    cur,
    proposal_id: int,
    *,
    sync_change_requests_shadow_validation_fn: Callable[..., int],
    ensure_change_requests_table_fn: Callable[[Any], None],
    parse_maybe_json_fn: Callable[[Any], Any],
    parse_optional_int_fn: Callable[[Any], int | None],
    build_change_request_shadow_validation_state_with_context_fn: Callable[..., dict[str, Any]],
    safe_json_dumps_fn: Callable[[Any], str],
) -> int:
    return sync_change_requests_shadow_validation_fn(
        cur,
        proposal_id,
        ensure_change_requests_table_fn=ensure_change_requests_table_fn,
        parse_maybe_json_fn=parse_maybe_json_fn,
        parse_optional_int_fn=parse_optional_int_fn,
        build_change_request_shadow_validation_state_fn=lambda **kwargs: (
            build_change_request_shadow_validation_state_with_context_fn(cur, **kwargs)
        ),
        safe_json_dumps_fn=safe_json_dumps_fn,
    )


def fetch_shadow_task_and_evaluator_with_context(
    shadow_task_id: int,
    *,
    get_conn_fn: Callable[[], Any],
    fetch_latest_evaluator_for_task_fn: Callable[[Any, int], dict[str, Any] | None],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    conn = get_conn_fn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT id, session_id, user_input, created_by_actor, status, runtime_overrides, created_at
            FROM task_runs
            WHERE id = %s;
            """,
            (shadow_task_id,),
        )
        shadow_task = cur.fetchone()
        shadow_evaluator = fetch_latest_evaluator_for_task_fn(cur, shadow_task_id)
        return shadow_task, shadow_evaluator
    finally:
        cur.close()
        conn.close()


def record_shadow_validation_result_with_context(
    *,
    workflow_proposal: dict[str, Any],
    baseline_task_id: int,
    actor_name: str,
    validation: dict[str, Any],
    get_conn_fn: Callable[[], Any],
    insert_audit_log_fn: Callable[[Any, str, str, int | None, Any | None], None],
    sync_change_requests_shadow_validation_with_context_fn: Callable[[Any, int], int],
) -> None:
    conn = get_conn_fn()
    cur = conn.cursor()
    try:
        insert_audit_log_fn(
            cur,
            "workflow_proposal.shadow_validated",
            actor_name,
            baseline_task_id,
            validation,
        )
        sync_change_requests_shadow_validation_with_context_fn(cur, int(workflow_proposal.get("id") or 0))
        conn.commit()
    finally:
        cur.close()
        conn.close()


def wait_for_shadow_validation_completion_with_context(
    *,
    workflow_proposal: dict[str, Any],
    baseline_task_id: int,
    shadow_task_id: int,
    actor_name: str,
    timeout_seconds: int,
    poll_interval_seconds: float,
    candidate_overlay: dict[str, Any] | None = None,
    runtime_overrides: dict[str, Any] | None = None,
    validation_mode: str = "task_replay_compare",
    wait_for_shadow_validation_completion_fn: Callable[..., dict[str, Any] | None],
    fetch_shadow_task_and_evaluator_with_context_fn: Callable[[int], tuple[dict[str, Any] | None, dict[str, Any] | None]],
    build_shadow_validation_result_fn: Callable[..., dict[str, Any]],
    record_shadow_validation_result_with_context_fn: Callable[..., None],
) -> dict[str, Any] | None:
    return wait_for_shadow_validation_completion_fn(
        workflow_proposal=workflow_proposal,
        baseline_task_id=baseline_task_id,
        shadow_task_id=shadow_task_id,
        actor_name=actor_name,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        candidate_overlay=candidate_overlay,
        runtime_overrides=runtime_overrides,
        validation_mode=validation_mode,
        fetch_shadow_task_and_evaluator_fn=fetch_shadow_task_and_evaluator_with_context_fn,
        build_shadow_validation_result_fn=build_shadow_validation_result_fn,
        record_shadow_validation_result_fn=record_shadow_validation_result_with_context_fn,
    )


def start_shadow_validation_completion_worker(
    *,
    workflow_proposal: dict[str, Any],
    baseline_task_id: int,
    shadow_task_id: int,
    actor_name: str,
    timeout_seconds: int,
    poll_interval_seconds: float,
    candidate_overlay: dict[str, Any] | None = None,
    runtime_overrides: dict[str, Any] | None = None,
    validation_mode: str = "task_replay_compare",
    wait_for_shadow_validation_completion_with_context_fn: Callable[..., dict[str, Any] | None],
    thread_cls,
    logger,
) -> None:
    def _run() -> None:
        try:
            wait_for_shadow_validation_completion_with_context_fn(
                workflow_proposal=workflow_proposal,
                baseline_task_id=baseline_task_id,
                shadow_task_id=shadow_task_id,
                actor_name=actor_name,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
                candidate_overlay=candidate_overlay,
                runtime_overrides=runtime_overrides,
                validation_mode=validation_mode,
            )
        except Exception:
            logger.exception(
                "shadow validation async completion failed proposal_id=%s shadow_task_id=%s",
                workflow_proposal.get("id"),
                shadow_task_id,
            )

    thread = thread_cls(
        target=_run,
        name=f"shadow-validation-{shadow_task_id}",
        daemon=True,
    )
    thread.start()


def build_shadow_validation_execution_payload_with_context(
    *,
    workflow_proposal: dict[str, Any],
    baseline_task: dict[str, Any],
    request,
    actor: dict[str, Any],
    quota_snapshot: dict[str, Any],
    candidate_overlay: dict[str, Any] | None,
    runtime_overrides: dict[str, Any] | None,
    shadow_task: dict[str, Any],
    build_shadow_validation_execution_payload_fn: Callable[..., dict[str, Any]],
    parse_optional_int_fn: Callable[[Any], int | None],
    make_json_compatible_fn: Callable[[Any], Any],
) -> dict[str, Any]:
    return build_shadow_validation_execution_payload_fn(
        workflow_proposal=workflow_proposal,
        baseline_task=baseline_task,
        request=request,
        actor=actor,
        quota_snapshot=quota_snapshot,
        candidate_overlay=candidate_overlay,
        runtime_overrides=runtime_overrides,
        shadow_task=shadow_task,
        parse_optional_int_fn=parse_optional_int_fn,
        make_json_compatible_fn=make_json_compatible_fn,
    )


def finalize_shadow_validation_response_with_context(
    *,
    workflow_proposal: dict[str, Any],
    baseline_task: dict[str, Any],
    shadow_task: dict[str, Any],
    validation_request: dict[str, Any],
    candidate_overlay: dict[str, Any] | None,
    validation_mode: str,
    source_change_request: dict[str, Any] | None,
    await_completion: bool,
    actor_name: str,
    timeout_seconds: int,
    poll_interval_seconds: float,
    runtime_overrides: dict[str, Any] | None,
    finalize_shadow_validation_response_fn: Callable[..., dict[str, Any]],
    make_json_compatible_fn: Callable[[Any], Any],
    wait_for_shadow_validation_completion_with_context_fn: Callable[..., dict[str, Any] | None],
    start_shadow_validation_completion_worker_fn: Callable[..., None],
) -> dict[str, Any]:
    return finalize_shadow_validation_response_fn(
        workflow_proposal=workflow_proposal,
        baseline_task=baseline_task,
        shadow_task=shadow_task,
        validation_request=validation_request,
        candidate_overlay=make_json_compatible_fn(candidate_overlay),
        validation_mode=validation_mode,
        source_change_request=source_change_request,
        await_completion=await_completion,
        actor_name=actor_name,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        runtime_overrides=runtime_overrides,
        wait_for_shadow_validation_completion_fn=wait_for_shadow_validation_completion_with_context_fn,
        start_shadow_validation_completion_worker_fn=start_shadow_validation_completion_worker_fn,
    )
