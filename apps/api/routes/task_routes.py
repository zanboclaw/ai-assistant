from __future__ import annotations

from fastapi import APIRouter, FastAPI, Header

from apps.api.application.task.create_task import create_task_record
from apps.api.application.task.list_tasks import list_tasks as list_task_rows
from apps.api.policy.permission_guard import require_actor_permission
from apps.api.policy.quota_policy import enforce_task_quota
from apps.api.schemas import TaskCreate


def _build_task_collection_router(container) -> APIRouter:
    router = APIRouter()
    require_actor_permission_fn = container.get("require_actor_permission", require_actor_permission)
    enforce_task_quota_fn = container.get("enforce_task_quota", enforce_task_quota)

    @router.post("/tasks")
    def create_task(task: TaskCreate, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
        conn = container["get_conn"]()
        cur = conn.cursor()
        try:
            actor = require_actor_permission_fn(cur, x_actor_name, "operate")
            quota_snapshot = enforce_task_quota_fn(cur, actor["actor_name"])
            created_row = create_task_record(
                cur,
                task=task,
                actor=actor,
                quota_snapshot=quota_snapshot,
                ensure_skill_registry_tables=container["ensure_skill_registry_tables"],
                infer_task_intent=container["infer_task_intent"],
                infer_deliverable_spec=container["infer_deliverable_spec"],
                build_memory_context=container["build_memory_context"],
                build_task_display_user_input=container["build_task_display_user_input"],
                make_json_compatible=container["make_json_compatible"],
                attach_task_display_fields=container["attach_task_display_fields"],
                parse_maybe_json=container["parse_maybe_json"],
                insert_audit_log=container["insert_audit_log"],
            )
            conn.commit()
        finally:
            cur.close()
            conn.close()
        container["enqueue_task"](int(created_row["id"]))
        return created_row

    @router.get("/tasks")
    def list_tasks(
        session_id: int | None = None,
        include_stage5_summary: bool = False,
        limit: int | None = None,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = container["get_conn"]()
        cur = conn.cursor()
        try:
            require_actor_permission_fn(cur, x_actor_name, "read")
            return list_task_rows(
                cur,
                session_id=session_id,
                limit=int(limit or 60),
                include_stage5_summary=include_stage5_summary,
                attach_task_display_fields=container["attach_task_display_fields"],
                parse_maybe_json=container["parse_maybe_json"],
                fetch_task_agent_summary=container["fetch_task_agent_summary"],
            )
        finally:
            cur.close()
            conn.close()

    return router


def register_task_routes(*, app: FastAPI, container) -> None:
    app.include_router(_build_task_collection_router(container))
    app.include_router(
        container["register_task_query_routes"](
            get_conn=container["get_conn"],
            require_actor_permission=container["require_actor_permission"],
            ensure_agent_tables=container["ensure_agent_tables"],
            ensure_evaluator_tables=container["ensure_evaluator_tables"],
            ensure_trace_tables=container["ensure_trace_tables"],
            attach_task_display_fields=container["attach_task_display_fields"],
            parse_maybe_json=container["parse_maybe_json"],
            fetch_latest_evaluator_for_task=container["fetch_latest_evaluator_for_task"],
            fetch_task_agent_summary=container["fetch_task_agent_summary"],
        )
    )
    app.include_router(
        container["register_task_control_routes"](
            get_conn=container["get_conn"],
            require_actor_permission=container["require_actor_permission"],
            get_task_or_404=container["get_task_or_404"],
            update_checkpoint_status=container["update_checkpoint_status"],
            insert_audit_log=container["insert_audit_log"],
            resolve_resume_from_step=container["resolve_resume_from_step"],
            reset_task_for_resume=container["reset_task_for_resume"],
            reset_task_for_clarification=container["reset_task_for_clarification"],
            enqueue_task=container["enqueue_task"],
            parse_maybe_json=container["parse_maybe_json"],
            extract_task_clarification_state=container["extract_task_clarification_state"],
            build_clarified_user_input=container["build_clarified_user_input"],
            infer_task_intent=container["infer_task_intent"],
            build_task_display_user_input=container["build_task_display_user_input"],
            infer_deliverable_spec=container["infer_deliverable_spec"],
            logger=container["logger"],
        )
    )
