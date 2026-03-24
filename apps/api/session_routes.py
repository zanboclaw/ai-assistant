from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import APIRouter, Header, HTTPException

from schemas import DailyReviewRunRequest, SessionCreate, SessionMemoryCreate, SessionReviewCreate, SessionStateUpdate


def register_session_routes(
    *,
    get_conn: Callable[[], Any],
    require_actor_permission: Callable[[Any, str | None, str], dict[str, Any]],
    record_audit_event: Callable[[str, str, int | None, Any | None], None],
    insert_audit_log: Callable[[Any, str, str, int | None, Any | None], None],
    attach_task_display_fields: Callable[[dict[str, Any]], dict[str, Any]],
    serialize_session_row: Callable[[dict[str, Any]], dict[str, Any]],
    serialize_session_memory_row: Callable[[dict[str, Any]], dict[str, Any]],
    serialize_session_state_row: Callable[[dict[str, Any]], dict[str, Any]],
    serialize_session_review_row: Callable[[dict[str, Any]], dict[str, Any]],
    compute_session_health: Callable[[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None, list[dict[str, Any]]], dict[str, Any]],
    load_session_health_context: Callable[[Any, int], tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None, list[dict[str, Any]]]],
    refresh_session_review_context: Callable[[Any, int], tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]],
    build_session_review: Callable[[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None, str], dict[str, Any]],
    insert_session_review_row: Callable[[Any, int, str, dict[str, Any]], dict[str, Any]],
    safe_json_dumps: Callable[[Any], str],
    compute_session_state_from_rows: Callable[[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]], dict[str, Any]],
    upsert_computed_session_state: Callable[[Any, int, dict[str, Any]], dict[str, Any]],
    refresh_session_reviews: Callable[..., None],
    refresh_session_task_summary_memories: Callable[[Any, list[dict[str, Any]]], None],
    merge_memory_into_session_state: Callable[[Any, int, str, str], dict[str, Any] | None],
    logger: Any,
):
    router = APIRouter()

    @router.post("/sessions")
    def create_session(session: SessionCreate, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
        name = session.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Session name cannot be empty")

        conn = get_conn()
        cur = conn.cursor()
        actor = require_actor_permission(cur, x_actor_name, "operate")
        cur.execute(
            """
            INSERT INTO sessions (name, description)
            VALUES (%s, %s)
            RETURNING id, name, description, created_at, updated_at;
            """,
            (name, session.description.strip()),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        record_audit_event(
            "session.create",
            actor["actor_name"],
            None,
            {"session_id": row["id"], "name": row["name"], "role": actor["role"]},
        )
        logger.info("session created id=%s name=%s actor=%s", row["id"], row["name"], actor["actor_name"])
        return serialize_session_row(row)

    @router.get("/sessions")
    def list_sessions(x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
        conn = get_conn()
        cur = conn.cursor()
        require_actor_permission(cur, x_actor_name, "read")
        cur.execute(
            """
            SELECT id, name, description, created_at, updated_at
            FROM sessions
            ORDER BY id DESC;
            """
        )
        rows = [serialize_session_row(row) for row in cur.fetchall()]
        cur.close()
        conn.close()
        return rows

    @router.get("/sessions/{session_id}")
    def get_session(session_id: int, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
        conn = get_conn()
        cur = conn.cursor()
        require_actor_permission(cur, x_actor_name, "read")
        cur.execute(
            """
            SELECT id, name, description, created_at, updated_at
            FROM sessions
            WHERE id = %s;
            """,
            (session_id,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Session not found")
        return serialize_session_row(row)

    @router.get("/sessions/{session_id}/tasks")
    def list_session_tasks(session_id: int, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
        conn = get_conn()
        cur = conn.cursor()
        require_actor_permission(cur, x_actor_name, "read")
        cur.execute("SELECT id FROM sessions WHERE id = %s;", (session_id,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            raise HTTPException(status_code=404, detail="Session not found")

        cur.execute(
            """
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
                created_at,
                updated_at
            FROM task_runs
            WHERE session_id = %s
            ORDER BY id DESC;
            """,
            (session_id,),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return rows

    @router.get("/sessions/{session_id}/summary")
    def get_session_summary(session_id: int, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
        conn = get_conn()
        cur = conn.cursor()
        require_actor_permission(cur, x_actor_name, "read")
        session_row, task_rows, memory_rows, session_state_row, review_rows = load_session_health_context(cur, session_id)
        tasks_by_status: dict[str, int] = {}
        for row in task_rows:
            status = str(row.get("status") or "unknown")
            tasks_by_status[status] = tasks_by_status.get(status, 0) + 1

        total_tasks = len(task_rows)
        total_memories = len(memory_rows)
        memories_by_category: dict[str, int] = {}
        for row in memory_rows:
            category = str(row.get("category") or "unknown")
            memories_by_category[category] = memories_by_category.get(category, 0) + 1

        cur.execute(
            """
            SELECT COUNT(*) AS count
            FROM approvals
            WHERE status = 'pending'
              AND task_id IN (
                  SELECT id FROM task_runs WHERE session_id = %s
              );
            """,
            (session_id,),
        )
        pending_approvals = int(cur.fetchone()["count"])

        recent_tasks = task_rows[:5]
        for row in recent_tasks:
            attach_task_display_fields(row)
        last_task_updated_at = recent_tasks[0]["updated_at"] if recent_tasks else None
        session_health = compute_session_health(task_rows, memory_rows, session_state_row, review_rows)

        cur.close()
        conn.close()

        return {
            "session": serialize_session_row(session_row),
            "task_metrics": {
                "total_tasks": total_tasks,
                "tasks_by_status": tasks_by_status,
                "last_task_updated_at": last_task_updated_at,
            },
            "memory_metrics": {
                "total_memories": total_memories,
                "by_category": memories_by_category,
            },
            "session_state": serialize_session_state_row(session_state_row) if session_state_row else None,
            "health": session_health,
            "approval_metrics": {
                "pending_approvals": pending_approvals,
            },
            "recent_tasks": recent_tasks,
        }

    @router.get("/sessions/{session_id}/health")
    def get_session_health(session_id: int, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
        conn = get_conn()
        cur = conn.cursor()
        require_actor_permission(cur, x_actor_name, "read")
        _session_row, task_rows, memory_rows, session_state_row, review_rows = load_session_health_context(cur, session_id)
        health = compute_session_health(task_rows, memory_rows, session_state_row, review_rows)
        cur.close()
        conn.close()
        return {
            "session_id": session_id,
            "health": health,
        }

    @router.post("/sessions/{session_id}/reviews")
    def create_session_review(
        session_id: int,
        review: SessionReviewCreate,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = get_conn()
        cur = conn.cursor()
        actor = require_actor_permission(cur, x_actor_name, "operate")
        session_row, task_rows, memory_rows, session_state_row = refresh_session_review_context(cur, session_id)

        built_review = build_session_review(session_row, task_rows, memory_rows, session_state_row, review.note)
        review_kind = review.review_kind.strip() or "manual"
        row = insert_session_review_row(cur, session_id, review_kind, built_review)
        insert_audit_log(
            cur,
            "session.review_create",
            actor["actor_name"],
            None,
            {
                "session_id": session_id,
                "review_id": row["id"],
                "review_kind": review_kind,
                "role": actor["role"],
            },
        )
        conn.commit()
        cur.close()
        conn.close()
        logger.info(
            "session review created session_id=%s review_id=%s kind=%s actor=%s",
            session_id,
            row["id"],
            review_kind,
            actor["actor_name"],
        )
        return serialize_session_review_row(row)

    @router.post("/reviews/daily-run")
    def run_daily_reviews(
        request: DailyReviewRunRequest,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = get_conn()
        cur = conn.cursor()
        actor = require_actor_permission(cur, x_actor_name, "admin")

        review_kind = request.review_kind.strip() or "daily"
        session_limit = max(1, min(int(request.session_limit), 100))
        active_within_hours = max(1, min(int(request.active_within_hours), 168))

        cur.execute(
            """
            SELECT DISTINCT s.id
            FROM sessions s
            JOIN task_runs t ON t.session_id = s.id
            WHERE t.updated_at >= CURRENT_TIMESTAMP - (%s * INTERVAL '1 hour')
            ORDER BY s.id DESC
            LIMIT %s;
            """,
            (active_within_hours, session_limit),
        )
        session_ids = [int(row["id"]) for row in cur.fetchall()]

        created: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        review_day_key = datetime.now(timezone.utc).date().isoformat()
        for session_id in session_ids:
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s));",
                (f"daily-review:{review_kind}:{session_id}:{review_day_key}",),
            )
            if not request.force:
                cur.execute(
                    """
                    SELECT id
                    FROM session_reviews
                    WHERE session_id = %s
                      AND review_kind = %s
                      AND DATE(created_at) = CURRENT_DATE
                    ORDER BY id DESC
                    LIMIT 1;
                    """,
                    (session_id, review_kind),
                )
                existing = cur.fetchone()
                if existing:
                    skipped.append(
                        {
                            "session_id": session_id,
                            "reason": "already_reviewed_today",
                            "review_id": int(existing["id"]),
                        }
                    )
                    continue

            session_row, task_rows, memory_rows, session_state_row = refresh_session_review_context(cur, session_id)
            built_review = build_session_review(session_row, task_rows, memory_rows, session_state_row, request.note)
            row = insert_session_review_row(cur, session_id, review_kind, built_review)
            insert_audit_log(
                cur,
                "session.review_create",
                "api",
                None,
                {
                    "session_id": session_id,
                    "review_id": row["id"],
                    "review_kind": review_kind,
                    "source": "daily-run",
                    "actor_role": actor["role"],
                },
            )
            created.append(
                {
                    "session_id": session_id,
                    "review_id": int(row["id"]),
                    "review_kind": review_kind,
                }
            )

        conn.commit()
        cur.close()
        conn.close()
        logger.info(
            "daily reviews executed review_kind=%s created=%s skipped=%s actor=%s",
            review_kind,
            len(created),
            len(skipped),
            actor["actor_name"],
        )
        return {
            "review_kind": review_kind,
            "active_within_hours": active_within_hours,
            "session_limit": session_limit,
            "created": created,
            "skipped": skipped,
        }

    @router.get("/sessions/{session_id}/reviews")
    def list_session_reviews(
        session_id: int,
        limit: int | None = 20,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = get_conn()
        cur = conn.cursor()
        require_actor_permission(cur, x_actor_name, "read")
        cur.execute("SELECT id FROM sessions WHERE id = %s;", (session_id,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            raise HTTPException(status_code=404, detail="Session not found")

        cur.execute(
            """
            SELECT id, session_id, review_kind, summary_text, highlights, open_loops, created_at
            FROM session_reviews
            WHERE session_id = %s
            ORDER BY id DESC
            LIMIT %s;
            """,
            (session_id, limit or 20),
        )
        rows = [serialize_session_review_row(row) for row in cur.fetchall()]
        cur.close()
        conn.close()
        return rows

    @router.get("/sessions/{session_id}/state")
    def get_session_state(session_id: int, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
        conn = get_conn()
        cur = conn.cursor()
        require_actor_permission(cur, x_actor_name, "read")
        cur.execute("SELECT id FROM sessions WHERE id = %s;", (session_id,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            raise HTTPException(status_code=404, detail="Session not found")

        cur.execute(
            """
            SELECT session_id, summary_text, preferences, open_loops, created_at, updated_at
            FROM session_states
            WHERE session_id = %s;
            """,
            (session_id,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return {
                "session_id": session_id,
                "summary_text": "",
                "preferences": [],
                "open_loops": [],
                "created_at": None,
                "updated_at": None,
            }
        return serialize_session_state_row(row)

    @router.put("/sessions/{session_id}/state")
    def update_session_state(
        session_id: int,
        state: SessionStateUpdate,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        preferences = [str(item).strip() for item in state.preferences if str(item).strip()]
        open_loops = [str(item).strip() for item in state.open_loops if str(item).strip()]
        summary_text = state.summary_text.strip()

        conn = get_conn()
        cur = conn.cursor()
        actor = require_actor_permission(cur, x_actor_name, "operate")
        cur.execute("SELECT id FROM sessions WHERE id = %s;", (session_id,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            raise HTTPException(status_code=404, detail="Session not found")

        cur.execute(
            """
            INSERT INTO session_states (session_id, summary_text, preferences, open_loops)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (session_id) DO UPDATE
            SET summary_text = EXCLUDED.summary_text,
                preferences = EXCLUDED.preferences,
                open_loops = EXCLUDED.open_loops,
                updated_at = CURRENT_TIMESTAMP
            RETURNING session_id, summary_text, preferences, open_loops, created_at, updated_at;
            """,
            (
                session_id,
                summary_text,
                safe_json_dumps(preferences),
                safe_json_dumps(open_loops),
            ),
        )
        row = cur.fetchone()
        insert_audit_log(
            cur,
            "session.state_update",
            actor["actor_name"],
            None,
            {
                "session_id": session_id,
                "preferences_count": len(preferences),
                "open_loops_count": len(open_loops),
                "role": actor["role"],
            },
        )
        conn.commit()
        cur.close()
        conn.close()
        logger.info("session state updated session_id=%s actor=%s", session_id, actor["actor_name"])
        return serialize_session_state_row(row)

    @router.post("/sessions/{session_id}/state/rebuild")
    def rebuild_session_state(session_id: int, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
        conn = get_conn()
        cur = conn.cursor()
        actor = require_actor_permission(cur, x_actor_name, "operate")
        cur.execute(
            """
            SELECT id, name, description, created_at, updated_at
            FROM sessions
            WHERE id = %s;
            """,
            (session_id,),
        )
        session_row = cur.fetchone()
        if not session_row:
            cur.close()
            conn.close()
            raise HTTPException(status_code=404, detail="Session not found")

        cur.execute(
            """
            SELECT id, session_id, user_input, status, result, updated_at, runtime_overrides
            FROM task_runs
            WHERE session_id = %s
            ORDER BY updated_at DESC, id DESC;
            """,
            (session_id,),
        )
        task_rows = list(cur.fetchall())
        refresh_session_task_summary_memories(cur, task_rows)

        cur.execute(
            """
            SELECT id, session_id, category, content, importance, source_task_id, created_at, updated_at
            FROM session_memories
            WHERE session_id = %s
            ORDER BY importance DESC, id DESC;
            """,
            (session_id,),
        )
        memory_rows = list(cur.fetchall())

        computed_state = compute_session_state_from_rows(session_row, task_rows, memory_rows)
        refreshed_state = upsert_computed_session_state(cur, session_id, computed_state)
        refresh_session_reviews(
            cur,
            session_row=session_row,
            task_rows=task_rows,
            memory_rows=memory_rows,
            session_state_row=refreshed_state,
        )
        insert_audit_log(
            cur,
            "session.state_rebuild",
            actor["actor_name"],
            None,
            {
                "session_id": session_id,
                "task_count": len(task_rows),
                "memory_count": len(memory_rows),
                "role": actor["role"],
            },
        )
        conn.commit()
        cur.close()
        conn.close()
        logger.info("session state rebuilt session_id=%s actor=%s", session_id, actor["actor_name"])
        return refreshed_state

    @router.post("/sessions/{session_id}/memories")
    def create_session_memory(
        session_id: int,
        memory: SessionMemoryCreate,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        category = memory.category.strip()
        content = memory.content.strip()
        if not category:
            raise HTTPException(status_code=400, detail="Memory category cannot be empty")
        if not content:
            raise HTTPException(status_code=400, detail="Memory content cannot be empty")
        if memory.importance < 1 or memory.importance > 5:
            raise HTTPException(status_code=400, detail="Memory importance must be between 1 and 5")

        conn = get_conn()
        cur = conn.cursor()
        actor = require_actor_permission(cur, x_actor_name, "operate")
        cur.execute("SELECT id FROM sessions WHERE id = %s;", (session_id,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            raise HTTPException(status_code=404, detail="Session not found")

        if memory.source_task_id is not None:
            cur.execute("SELECT id FROM task_runs WHERE id = %s;", (memory.source_task_id,))
            if not cur.fetchone():
                cur.close()
                conn.close()
                raise HTTPException(status_code=404, detail="Source task not found")

        cur.execute(
            """
            INSERT INTO session_memories (session_id, category, content, importance, source_task_id)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, session_id, category, content, importance, source_task_id, created_at, updated_at;
            """,
            (session_id, category, content, int(memory.importance), memory.source_task_id),
        )
        row = cur.fetchone()
        updated_state = merge_memory_into_session_state(cur, session_id, category, content)
        insert_audit_log(
            cur,
            "session.memory_create",
            actor["actor_name"],
            memory.source_task_id,
            {
                "session_id": session_id,
                "memory_id": row["id"],
                "category": category,
                "importance": int(memory.importance),
                "state_updated": bool(updated_state),
                "role": actor["role"],
            },
        )
        conn.commit()
        cur.close()
        conn.close()
        logger.info(
            "session memory created session_id=%s memory_id=%s category=%s actor=%s",
            session_id,
            row["id"],
            category,
            actor["actor_name"],
        )
        return serialize_session_memory_row(row)

    @router.get("/sessions/{session_id}/memories")
    def list_session_memories(
        session_id: int,
        category: str | None = None,
        limit: int | None = 50,
        x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
    ):
        conn = get_conn()
        cur = conn.cursor()
        require_actor_permission(cur, x_actor_name, "read")
        cur.execute("SELECT id FROM sessions WHERE id = %s;", (session_id,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            raise HTTPException(status_code=404, detail="Session not found")

        params: list[Any] = [session_id]
        where_sql = "WHERE session_id = %s"
        if category:
            where_sql += " AND category = %s"
            params.append(category)
        params.append(limit)

        cur.execute(
            f"""
            SELECT id, session_id, category, content, importance, source_task_id, created_at, updated_at
            FROM session_memories
            {where_sql}
            ORDER BY importance DESC, id DESC
            LIMIT %s;
            """,
            tuple(params),
        )
        rows = [serialize_session_memory_row(row) for row in cur.fetchall()]
        cur.close()
        conn.close()
        return rows

    return router
