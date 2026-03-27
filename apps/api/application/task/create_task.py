from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from psycopg2.extras import Json

from apps.api.schemas import TaskCreate


def build_task_create_payload(**kwargs) -> TaskCreate:
    return TaskCreate(**kwargs)


def ensure_session_exists(cur, session_id: int | None) -> None:
    if session_id is None:
        return
    cur.execute("SELECT id FROM sessions WHERE id = %s;", (session_id,))
    if not cur.fetchone():
        raise HTTPException(status_code=404, detail="Session not found")


def ensure_active_skill_exists(cur, skill_id: str | None, *, ensure_skill_registry_tables) -> dict[str, Any] | None:
    normalized_skill_id = str(skill_id or "").strip()
    if not normalized_skill_id:
        return None
    ensure_skill_registry_tables(cur)
    cur.execute(
        """
        SELECT skill_id, latest_version
        FROM skills
        WHERE skill_id = %s AND status = 'active';
        """,
        (normalized_skill_id,),
    )
    skill_row = cur.fetchone()
    if not skill_row:
        raise HTTPException(status_code=404, detail="Skill not found")
    return dict(skill_row)


def hydrate_task_creation_context(
    cur,
    *,
    task: TaskCreate,
    ensure_skill_registry_tables,
    infer_task_intent,
    infer_deliverable_spec,
    build_memory_context,
    build_task_display_user_input,
    make_json_compatible,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    runtime_overrides: dict[str, Any] = {}
    task_intent = infer_task_intent(task.user_input, skill_id=task.skill_id)
    memory_context = dict(task.memory_context or {})
    if not memory_context:
        memory_context = build_memory_context(cur, task.user_input)
    retrieved_memories = list(memory_context.get("retrieved_memories") or [])
    if retrieved_memories:
        runtime_overrides["memory_context"] = make_json_compatible(memory_context)
        task_intent["memory_context_used"] = True
        task_intent["memory_context_count"] = len(retrieved_memories)

    task_intent["goal_summary"] = build_task_display_user_input(task.user_input, runtime_overrides or None)[:160]
    deliverable_spec = infer_deliverable_spec(task.user_input, task_intent)

    intake_mode = str(task.intake_mode or task.draft_route or "").strip()
    if intake_mode:
        runtime_overrides["intake"] = {
            "mode": intake_mode,
            "route": str(task.draft_route or task.intake_mode or intake_mode).strip(),
            "confirmed_at": datetime.now(timezone.utc).isoformat(),
        }

    skill_row = ensure_active_skill_exists(
        cur,
        task.skill_id,
        ensure_skill_registry_tables=ensure_skill_registry_tables,
    )
    if skill_row:
        resolved_skill_version = str(task.skill_version or skill_row.get("latest_version") or "").strip()
        if not resolved_skill_version:
            raise HTTPException(status_code=400, detail="Skill has no active version")
        runtime_overrides["skill_invocation"] = {
            "skill_id": str(task.skill_id or "").strip(),
            "skill_version": resolved_skill_version,
            "skill_args": dict(task.skill_args or {}),
        }

    return task_intent, deliverable_spec, memory_context, runtime_overrides, retrieved_memories


def serialize_created_task_row(row: dict[str, Any], *, attach_task_display_fields, parse_maybe_json) -> dict[str, Any]:
    task_row = dict(row)
    attach_task_display_fields(task_row)
    task_row["task_intent"] = parse_maybe_json(task_row.get("task_intent_json")) or {}
    task_row["deliverable_spec"] = parse_maybe_json(task_row.get("deliverable_spec_json")) or {}
    task_row["validation_report"] = parse_maybe_json(task_row.get("validation_report_json")) or {}
    task_row["recovery_action"] = parse_maybe_json(task_row.get("recovery_action_json")) or {}
    task_row.pop("task_intent_json", None)
    task_row.pop("deliverable_spec_json", None)
    task_row.pop("validation_report_json", None)
    task_row.pop("recovery_action_json", None)
    return task_row


def create_task_record(
    cur,
    *,
    task: TaskCreate,
    actor: dict[str, Any],
    quota_snapshot: dict[str, Any],
    ensure_skill_registry_tables,
    infer_task_intent,
    infer_deliverable_spec,
    build_memory_context,
    build_task_display_user_input,
    make_json_compatible,
    attach_task_display_fields,
    parse_maybe_json,
    insert_audit_log,
) -> dict[str, Any]:
    ensure_session_exists(cur, task.session_id)
    task_intent, deliverable_spec, _memory_context, runtime_overrides, retrieved_memories = hydrate_task_creation_context(
        cur,
        task=task,
        ensure_skill_registry_tables=ensure_skill_registry_tables,
        infer_task_intent=infer_task_intent,
        infer_deliverable_spec=infer_deliverable_spec,
        build_memory_context=build_memory_context,
        build_task_display_user_input=build_task_display_user_input,
        make_json_compatible=make_json_compatible,
    )

    cur.execute(
        """
        INSERT INTO task_runs (
            user_input,
            session_id,
            created_by_actor,
            status,
            runtime_overrides,
            task_intent_json,
            deliverable_spec_json
        )
        VALUES (%s, %s, %s, 'pending', %s, %s, %s)
        RETURNING
            id,
            session_id,
            user_input,
            created_by_actor,
            status,
            runtime_overrides,
            task_intent_json,
            deliverable_spec_json,
            validation_report_json,
            recovery_action_json,
            created_at;
        """,
        (
            task.user_input,
            task.session_id,
            actor["actor_name"],
            Json(runtime_overrides) if runtime_overrides else None,
            Json(make_json_compatible(task_intent)),
            Json(make_json_compatible(deliverable_spec)),
        ),
    )
    created_row = serialize_created_task_row(
        cur.fetchone(),
        attach_task_display_fields=attach_task_display_fields,
        parse_maybe_json=parse_maybe_json,
    )
    insert_audit_log(
        cur,
        "task.create",
        actor["actor_name"],
        int(created_row["id"]),
        {
            "session_id": task.session_id,
            "role": actor["role"],
            "quota": quota_snapshot,
            "task_intent_type": (task_intent or {}).get("task_type"),
            "deliverable_type": (deliverable_spec or {}).get("deliverable_type"),
            "intake_mode": str(task.intake_mode or task.draft_route or ""),
            "memory_context_count": len(retrieved_memories),
        },
    )
    return created_row
