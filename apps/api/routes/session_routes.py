from __future__ import annotations

from fastapi import FastAPI


def register_session_routes(*, app: FastAPI, container) -> None:
    app.include_router(
        container["register_session_routes"](
            get_conn=lambda: container["get_conn"](),
            require_actor_permission=lambda cur, actor_name, permission: container["require_actor_permission"](cur, actor_name, permission),
            record_audit_event=lambda event_type, actor, task_id=None, details=None: container["record_audit_event"](
                event_type,
                actor,
                task_id=task_id,
                details=details,
            ),
            insert_audit_log=lambda cur, event_type, actor, task_id=None, details=None: container["insert_audit_log"](
                cur,
                event_type,
                actor,
                task_id=task_id,
                details=details,
            ),
            attach_task_display_fields=lambda row: container["attach_task_display_fields"](row),
            serialize_session_row=lambda row: container["serialize_session_row"](row),
            serialize_session_memory_row=container["serialize_session_memory_row"],
            serialize_session_state_row=container["serialize_session_state_row"],
            serialize_session_review_row=container["serialize_session_review_row"],
            compute_session_health=container["compute_session_health"],
            load_session_health_context=lambda cur, session_id: container["load_session_health_context"](cur, session_id),
            refresh_session_review_context=container["refresh_session_review_context"],
            build_session_review=container["build_session_review"],
            insert_session_review_row=container["insert_session_review_row"],
            safe_json_dumps=container["safe_json_dumps"],
            compute_session_state_from_rows=container["compute_session_state_from_rows"],
            upsert_computed_session_state=container["upsert_computed_session_state"],
            refresh_session_reviews=container["refresh_session_reviews"],
            refresh_session_task_summary_memories=container["refresh_session_task_summary_memories"],
            merge_memory_into_session_state=container["merge_memory_into_session_state"],
            logger=container["logger"],
        )
    )

