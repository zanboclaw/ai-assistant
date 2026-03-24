from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def get_task_or_404(cur, task_id: int, *, http_exception_cls):
    cur.execute(
        """
        SELECT id, status, current_step, checkpoint_path, error_message
        FROM task_runs
        WHERE id = %s;
        """,
        (task_id,),
    )
    row = cur.fetchone()
    if not row:
        raise http_exception_cls(status_code=404, detail="Task not found")
    return row


def update_checkpoint_status(checkpoint_path_str: str | None, status: str, note: str = ""):
    checkpoint_path = (checkpoint_path_str or "").strip()
    if not checkpoint_path:
        return

    path = Path(checkpoint_path)
    if not path.exists():
        return

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return

    data["status"] = status
    if note:
        data["last_error"] = note
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_resume_from_step(cur, task_id: int, preferred_from_step: int | None) -> int:
    resume_from = preferred_from_step
    if not resume_from:
        cur.execute(
            """
            SELECT step_order
            FROM task_steps
            WHERE task_id = %s AND status != 'completed'
            ORDER BY step_order ASC
            LIMIT 1;
            """,
            (task_id,),
        )
        row = cur.fetchone()
        resume_from = row["step_order"] if row else 1
    return int(resume_from or 1)


def reset_task_for_resume(
    cur,
    *,
    task_id: int,
    task: dict[str, Any],
    resume_from: int,
    actor: dict[str, Any],
    note: str,
    event_type: str,
    insert_audit_log_fn,
    details: dict[str, Any] | None = None,
):
    cur.execute(
        """
        UPDATE task_steps
        SET status = 'pending',
            output_payload = NULL,
            output_data = NULL,
            error_message = '',
            retry_count = 0,
            updated_at = CURRENT_TIMESTAMP
        WHERE task_id = %s
          AND step_order >= %s;
        """,
        (task_id, resume_from),
    )

    cur.execute(
        """
        UPDATE task_runs
        SET status = 'pending',
            result = NULL,
            error_message = NULL,
            current_step = %s,
            validation_report_json = NULL,
            recovery_action_json = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s;
        """,
        (resume_from, task_id),
    )

    payload = {
        "from_step": resume_from,
        "note": note,
        "previous_status": task["status"],
        "role": actor["role"],
    }
    if details:
        payload.update(details)
    insert_audit_log_fn(cur, event_type, actor["actor_name"], task_id, payload)


def reset_task_for_clarification(
    cur,
    *,
    task_id: int,
    task: dict[str, Any],
    actor: dict[str, Any],
    new_user_input: str,
    task_intent: dict[str, Any],
    deliverable_spec: dict[str, Any],
    runtime_overrides: dict[str, Any] | None,
    note: str,
    json_wrapper,
    make_json_compatible,
    insert_audit_log_fn,
    details: dict[str, Any] | None = None,
):
    cur.execute(
        """
        DELETE FROM task_steps
        WHERE task_id = %s;
        """,
        (task_id,),
    )
    cur.execute(
        """
        UPDATE task_runs
        SET user_input = %s,
            status = 'pending',
            result = NULL,
            error_message = NULL,
            current_step = 1,
            runtime_overrides = %s,
            task_intent_json = %s,
            deliverable_spec_json = %s,
            validation_report_json = NULL,
            recovery_action_json = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s;
        """,
        (
            new_user_input,
            json_wrapper(make_json_compatible(runtime_overrides)) if runtime_overrides else None,
            json_wrapper(make_json_compatible(task_intent)),
            json_wrapper(make_json_compatible(deliverable_spec)),
            task_id,
        ),
    )
    payload = {
        "from_step": 1,
        "note": note,
        "previous_status": task["status"],
        "role": actor["role"],
        "task_intent_type": task_intent.get("task_type"),
        "deliverable_type": deliverable_spec.get("deliverable_type"),
    }
    if details:
        payload.update(details)
    insert_audit_log_fn(cur, "task.clarify_resume", actor["actor_name"], task_id, payload)
