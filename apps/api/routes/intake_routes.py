from __future__ import annotations

from fastapi import APIRouter, FastAPI, Header

from apps.api.application.intake.analyze_input import analyze_input
from apps.api.application.intake.confirm_draft import confirm_draft
from apps.api.application.intake.fast_path_chat import fast_path_chat
from apps.api.application.memory.search_memory import search_long_term_memories
from apps.api.application.task.create_task import create_task_record, ensure_active_skill_exists, ensure_session_exists
from apps.api.policy.permission_guard import require_actor_permission
from apps.api.policy.quota_policy import enforce_task_quota
from apps.api.schemas import IntakeRouteRequest, TaskDraftConfirmRequest


def _build_router(container) -> APIRouter:
    router = APIRouter()
    analyze_input_fn = container.get("analyze_input", analyze_input)
    confirm_draft_fn = container.get("confirm_draft", confirm_draft)
    fast_path_chat_fn = container.get("fast_path_chat", fast_path_chat)
    search_memory_fn = container.get("search_memory", search_long_term_memories)
    require_actor_permission_fn = container.get("require_actor_permission", require_actor_permission)
    enforce_task_quota_fn = container.get("enforce_task_quota", enforce_task_quota)

    @router.post("/intake/route")
    def route_input_intake(
        request: IntakeRouteRequest,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = container["get_conn"]()
        cur = conn.cursor()
        try:
            require_actor_permission_fn(cur, x_actor_name, "read")
            ensure_session_exists(cur, request.session_id)
            ensure_active_skill_exists(
                cur,
                request.skill_id,
                ensure_skill_registry_tables=container["ensure_skill_registry_tables"],
            )
            return analyze_input_fn(
                cur,
                request.user_input,
                session_id=request.session_id,
                skill_id=request.skill_id,
            )
        finally:
            cur.close()
            conn.close()

    @router.post("/intake/confirm")
    def confirm_task_draft(
        request: TaskDraftConfirmRequest,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = container["get_conn"]()
        cur = conn.cursor()
        try:
            actor = require_actor_permission_fn(cur, x_actor_name, "operate")
            quota_snapshot = enforce_task_quota_fn(cur, actor["actor_name"])
            task_payload = confirm_draft_fn(
                user_input=request.user_input,
                route=request.route,
                session_id=request.session_id,
                skill_id=request.skill_id,
                skill_version=request.skill_version,
                skill_args=request.skill_args,
                memory_context=container["build_memory_context"](cur, request.user_input),
            )
            created_row = create_task_record(
                cur,
                task=task_payload,
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

    @router.post("/chat/fast-path")
    def run_fast_path_chat(
        request: IntakeRouteRequest,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = container["get_conn"]()
        cur = conn.cursor()
        try:
            actor = require_actor_permission_fn(cur, x_actor_name, "read")
            return fast_path_chat_fn(cur, request.user_input, actor_name=str(actor.get("actor_name") or ""))
        finally:
            cur.close()
            conn.close()

    @router.get("/memories/search")
    def search_memories(
        query: str,
        limit: int = 5,
        memory_kind: str | None = None,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = container["get_conn"]()
        cur = conn.cursor()
        try:
            require_actor_permission_fn(cur, x_actor_name, "read")
            return search_memory_fn(
                cur,
                query,
                memory_kind=memory_kind,
                limit=max(1, min(limit, 10)),
            )
        finally:
            cur.close()
            conn.close()

    return router


def register_intake_routes(*, app: FastAPI, container) -> None:
    app.include_router(_build_router(container))
