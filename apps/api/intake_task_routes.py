from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import APIRouter, Header, HTTPException
from psycopg2.extras import Json

from access_control import enforce_task_quota, require_actor_permission
from core.fast_path_runtime import build_fast_path_response
from core.long_term_memory import ensure_long_term_memory_table, search_long_term_memories
from core.task_runtime import build_task_display_user_input
from json_utils import make_json_compatible
from schemas import IntakeRouteRequest, TaskCreate, TaskDraftConfirmRequest
from serializers import parse_maybe_json
from task_intent_helpers import infer_deliverable_spec, infer_task_intent


def resolve_intake_route_mode(
    *,
    task_intent: dict[str, Any],
    deliverable_spec: dict[str, Any],
    skill_id: str | None = None,
) -> tuple[str, str]:
    if bool(task_intent.get("needs_clarification")) or bool(((deliverable_spec.get("clarify") or {}).get("blocking"))):
        return "clarify_first", "系统识别到关键输入缺口，建议先确认理解并准备进入 clarify 主链。"
    if str(skill_id or "").strip():
        return "draft_task", "当前输入绑定了显式 skill，建议先确认草稿理解后再创建正式任务。"

    task_type = str(task_intent.get("task_type") or "").strip()
    deliverable_type = str(deliverable_spec.get("deliverable_type") or "").strip()
    if task_type in {"qa", "question_answer", "direct_answer"} and deliverable_type == "direct_answer":
        return "fast_path", "这是简单问答型输入，可走快速路径；如仍需审计与回放，再转正式任务。"
    return "draft_task", "该输入更适合先以草稿态确认系统理解，再进入正式执行。"


def build_memory_context(cur, user_input: str, *, limit: int = 4) -> dict[str, Any]:
    ensure_long_term_memory_table(cur)
    retrieved_memories = search_long_term_memories(cur, user_input, limit=limit)
    return {
        "retrieved_memories": retrieved_memories,
        "retrieval_query": str(user_input or "").strip()[:240],
    }


def build_intake_preview_payload(
    *,
    user_input: str,
    session_id: int | None,
    skill_id: str | None,
    task_intent: dict[str, Any],
    deliverable_spec: dict[str, Any],
    memory_context: dict[str, Any],
) -> dict[str, Any]:
    route_mode, route_reason = resolve_intake_route_mode(
        task_intent=task_intent,
        deliverable_spec=deliverable_spec,
        skill_id=skill_id,
    )
    retrieved_memories = list(memory_context.get("retrieved_memories") or [])
    return {
        "route_mode": route_mode,
        "route_reason": route_reason,
        "confirmation_required": True,
        "task_intent": task_intent,
        "deliverable_spec": deliverable_spec,
        "draft_preview": {
            "goal_summary": str(task_intent.get("goal_summary") or build_task_display_user_input(user_input, {}))[:160],
            "task_type": str(task_intent.get("task_type") or "unknown"),
            "deliverable_type": str(deliverable_spec.get("deliverable_type") or "unknown"),
            "session_id": session_id,
            "skill_id": skill_id or "",
            "needs_clarification": bool(task_intent.get("needs_clarification")),
            "clarification_questions": list(((deliverable_spec.get("clarify") or {}).get("questions")) or []),
            "acceptance_hints": list(deliverable_spec.get("acceptance_hints") or []),
        },
        "memory_context": {
            "retrieval_query": memory_context.get("retrieval_query") or "",
            "retrieved_memories": retrieved_memories,
            "retrieved_count": len(retrieved_memories),
        },
    }


def register_intake_task_routes(
    *,
    ensure_skill_registry_tables: Callable[[Any], None],
    get_conn: Callable[[], Any],
    attach_task_display_fields: Callable[[dict[str, Any]], None],
    insert_audit_log: Callable[[Any, str, str, int | None, Any | None], None],
    enqueue_task: Callable[[int], None],
    fetch_task_agent_summary: Callable[[Any, int], dict[str, Any]],
):
    router = APIRouter()

    @router.post("/intake/route")
    def route_input_intake(
        request: IntakeRouteRequest,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = get_conn()
        cur = conn.cursor()
        require_actor_permission(cur, x_actor_name, "read")

        if request.session_id is not None:
            cur.execute("SELECT id FROM sessions WHERE id = %s;", (request.session_id,))
            if not cur.fetchone():
                cur.close()
                conn.close()
                raise HTTPException(status_code=404, detail="Session not found")

        if request.skill_id:
            ensure_skill_registry_tables(cur)
            cur.execute(
                """
                SELECT skill_id
                FROM skills
                WHERE skill_id = %s AND status = 'active';
                """,
                (request.skill_id.strip(),),
            )
            if not cur.fetchone():
                cur.close()
                conn.close()
                raise HTTPException(status_code=404, detail="Skill not found")

        task_intent = infer_task_intent(request.user_input, skill_id=request.skill_id)
        task_intent["goal_summary"] = build_task_display_user_input(request.user_input, {})[:160]
        deliverable_spec = infer_deliverable_spec(request.user_input, task_intent)
        memory_context = build_memory_context(cur, request.user_input)
        preview = build_intake_preview_payload(
            user_input=request.user_input,
            session_id=request.session_id,
            skill_id=request.skill_id,
            task_intent=task_intent,
            deliverable_spec=deliverable_spec,
            memory_context=memory_context,
        )
        cur.close()
        conn.close()
        return preview

    @router.post("/intake/confirm")
    def confirm_task_draft(
        request: TaskDraftConfirmRequest,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = get_conn()
        cur = conn.cursor()
        require_actor_permission(cur, x_actor_name, "operate")
        memory_context = build_memory_context(cur, request.user_input)
        cur.close()
        conn.close()
        return create_task(
            TaskCreate(
                user_input=request.user_input,
                session_id=request.session_id,
                skill_id=request.skill_id,
                skill_version=request.skill_version,
                skill_args=request.skill_args,
                intake_mode=request.route,
                draft_route=request.route,
                memory_context=memory_context,
            ),
            x_actor_name=x_actor_name,
        )

    @router.post("/chat/fast-path")
    def run_fast_path_chat(
        request: IntakeRouteRequest,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = get_conn()
        cur = conn.cursor()
        actor = require_actor_permission(cur, x_actor_name, "read")
        response = build_fast_path_response(
            cur,
            user_input=request.user_input,
            actor_name=str(actor.get("actor_name") or ""),
        )
        cur.close()
        conn.close()
        return response

    @router.get("/memories/search")
    def search_memories(
        query: str,
        limit: int = 5,
        memory_kind: str | None = None,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = get_conn()
        cur = conn.cursor()
        require_actor_permission(cur, x_actor_name, "read")
        rows = search_long_term_memories(cur, query, memory_kind=memory_kind, limit=max(1, min(limit, 10)))
        cur.close()
        conn.close()
        return rows

    @router.post("/tasks")
    def create_task(task: TaskCreate, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
        conn = get_conn()
        cur = conn.cursor()
        actor = require_actor_permission(cur, x_actor_name, "operate")
        quota_snapshot = enforce_task_quota(cur, actor["actor_name"])

        if task.session_id is not None:
            cur.execute("SELECT id FROM sessions WHERE id = %s;", (task.session_id,))
            if not cur.fetchone():
                cur.close()
                conn.close()
                raise HTTPException(status_code=404, detail="Session not found")

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
        if task.intake_mode or task.draft_route:
            runtime_overrides["intake"] = {
                "mode": str(task.intake_mode or task.draft_route or "draft_task"),
                "route": str(task.draft_route or task.intake_mode or "draft_task"),
                "confirmed_at": datetime.now(timezone.utc).isoformat(),
            }
        if task.skill_id:
            ensure_skill_registry_tables(cur)
            cur.execute(
                """
                SELECT skill_id, latest_version
                FROM skills
                WHERE skill_id = %s AND status = 'active';
                """,
                (task.skill_id.strip(),),
            )
            skill_row = cur.fetchone()
            if not skill_row:
                cur.close()
                conn.close()
                raise HTTPException(status_code=404, detail="Skill not found")
            resolved_skill_version = task.skill_version.strip() if task.skill_version else str(skill_row.get("latest_version") or "").strip()
            if not resolved_skill_version:
                cur.close()
                conn.close()
                raise HTTPException(status_code=400, detail="Skill has no active version")
            runtime_overrides = {
                **runtime_overrides,
                "skill_invocation": {
                    "skill_id": task.skill_id.strip(),
                    "skill_version": resolved_skill_version,
                    "skill_args": dict(task.skill_args or {}),
                }
            }

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
        row = cur.fetchone()
        attach_task_display_fields(row)
        row["task_intent"] = parse_maybe_json(row.get("task_intent_json")) or {}
        row["deliverable_spec"] = parse_maybe_json(row.get("deliverable_spec_json")) or {}
        row["validation_report"] = parse_maybe_json(row.get("validation_report_json")) or {}
        row["recovery_action"] = parse_maybe_json(row.get("recovery_action_json")) or {}
        row.pop("task_intent_json", None)
        row.pop("deliverable_spec_json", None)
        row.pop("validation_report_json", None)
        row.pop("recovery_action_json", None)
        insert_audit_log(
            cur,
            "task.create",
            actor["actor_name"],
            int(row["id"]),
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
        conn.commit()

        cur.close()
        conn.close()
        enqueue_task(int(row["id"]))
        return row

    @router.get("/tasks")
    def list_tasks(
        session_id: int | None = None,
        include_stage5_summary: bool = False,
        limit: int | None = None,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = get_conn()
        cur = conn.cursor()
        require_actor_permission(cur, x_actor_name, "read")

        where_sql = ""
        params: tuple[Any, ...] = ()
        if session_id is not None:
            cur.execute("SELECT id FROM sessions WHERE id = %s;", (session_id,))
            if not cur.fetchone():
                cur.close()
                conn.close()
                raise HTTPException(status_code=404, detail="Session not found")
            where_sql = "WHERE session_id = %s"
            params = (session_id,)

        row_limit = max(1, min(int(limit or 60), 200))

        cur.execute(
            f"""
            SELECT
                id,
                session_id,
                created_by_actor,
                user_input,
                status,
                result,
                error_message,
                current_step,
                checkpoint_path,
                runtime_overrides,
                task_intent_json,
                deliverable_spec_json,
                validation_report_json,
                recovery_action_json,
                created_at,
                updated_at
            FROM task_runs
            {where_sql}
            ORDER BY id DESC;
            """,
            params,
        )
        rows = cur.fetchall()[:row_limit]

        for row in rows:
            attach_task_display_fields(row)
            row["task_intent"] = parse_maybe_json(row.get("task_intent_json")) or {}
            row["deliverable_spec"] = parse_maybe_json(row.get("deliverable_spec_json")) or {}
            row["validation_report"] = parse_maybe_json(row.get("validation_report_json")) or {}
            row["recovery_action"] = parse_maybe_json(row.get("recovery_action_json")) or {}
            row.pop("task_intent_json", None)
            row.pop("deliverable_spec_json", None)
            row.pop("validation_report_json", None)
            row.pop("recovery_action_json", None)
            if include_stage5_summary:
                row["stage5"] = fetch_task_agent_summary(cur, int(row["id"]))

        cur.close()
        conn.close()
        return rows

    return router
