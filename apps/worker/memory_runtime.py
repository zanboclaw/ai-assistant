from __future__ import annotations

from typing import Any


def build_task_result_excerpt(task_row: dict[str, Any], limit: int = 220, *, strip_artifact_suffix) -> str:
    return strip_artifact_suffix(str(task_row.get("result") or ""))[:limit]


def build_task_summary_memory_content(task_display_input: str, final_result: str, *, strip_artifact_suffix) -> str:
    normalized_result = strip_artifact_suffix(final_result)
    if len(normalized_result) > 1200:
        normalized_result = normalized_result[:1200].rstrip() + "..."
    return f"任务：{task_display_input.strip()}\n\n结果摘要：\n{normalized_result}"


def extract_marked_clauses(text: str, markers: tuple[str, ...], max_length: int = 240) -> list[str]:
    normalized = " ".join((text or "").split())
    if not normalized:
        return []

    normalized = (
        normalized.replace("。", "|")
        .replace("！", "|")
        .replace("？", "|")
        .replace("；", "|")
        .replace(";", "|")
        .replace("\n", "|")
    )
    clauses = [part.strip(" ,|") for part in normalized.split("|") if part.strip(" ,|")]

    matched: list[str] = []
    seen: set[str] = set()
    for clause in clauses:
        if not any(marker in clause for marker in markers):
            continue
        compact = clause[:max_length].strip()
        if compact and compact not in seen:
            seen.add(compact)
            matched.append(compact)
    return matched


def infer_task_memories(user_input: str, final_result: str, *, strip_artifact_suffix, extract_marked_clauses_fn) -> list[dict[str, Any]]:
    inferred: list[dict[str, Any]] = []
    normalized_input = " ".join((user_input or "").split())
    normalized_result = " ".join(strip_artifact_suffix(final_result).split())

    if normalized_input:
        if (
            "以后请" in normalized_input
            or "之后请" in normalized_input
            or "偏好" in normalized_input
            or "请用" in normalized_input
        ):
            preference_clauses: list[str] = []
            for keyword in ("简洁", "分点", "中文", "英文", "表格", "步骤", "要点"):
                if keyword in normalized_input:
                    preference_clauses.append(keyword)
            if preference_clauses:
                inferred.append(
                    {
                        "category": "preference",
                        "content": "偏好" + "、".join(preference_clauses) + "回答",
                        "importance": 4,
                    }
                )

        open_loop_markers = ("后续", "下一步", "待办", "TODO", "todo", "follow-up", "follow up", "继续")
        for clause in extract_marked_clauses_fn(normalized_input, open_loop_markers):
            inferred.append(
                {
                    "category": "follow_up",
                    "content": clause,
                    "importance": 3,
                }
            )

    if normalized_result:
        result_open_loop_markers = ("后续", "下一步", "待办", "TODO", "todo", "需要继续", "尚未完成", "继续处理")
        for clause in extract_marked_clauses_fn(normalized_result, result_open_loop_markers):
            inferred.append(
                {
                    "category": "follow_up",
                    "content": clause,
                    "importance": 3,
                }
            )

        summary_excerpt = normalized_result[:300].strip()
        if summary_excerpt:
            inferred.append(
                {
                    "category": "fact",
                    "content": summary_excerpt,
                    "importance": 2,
                }
            )

    deduped: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for item in inferred:
        key = (str(item["category"]).strip().lower(), str(item["content"]).strip())
        if not key[1] or key in seen_pairs:
            continue
        seen_pairs.add(key)
        deduped.append(item)
    return deduped


def rebuild_session_state_from_worker(
    cur,
    session_id: int,
    *,
    build_task_display_user_input,
    normalize_runtime_overrides,
    safe_json_dumps,
):
    cur.execute("SELECT id, name FROM sessions WHERE id = %s;", (session_id,))
    session_row = cur.fetchone()
    if not session_row:
        return

    cur.execute(
        """
        SELECT id, user_input, status, runtime_overrides
        FROM task_runs
        WHERE session_id = %s
        ORDER BY updated_at DESC, id DESC;
        """,
        (session_id,),
    )
    task_rows = list(cur.fetchall())
    tasks_by_status: dict[str, int] = {}
    for row in task_rows:
        status = str(row.get("status") or "unknown")
        tasks_by_status[status] = tasks_by_status.get(status, 0) + 1

    cur.execute(
        """
        SELECT category, content, importance
        FROM session_memories
        WHERE session_id = %s
        ORDER BY importance DESC, id DESC;
        """,
        (session_id,),
    )
    memory_rows = list(cur.fetchall())

    preferences: list[str] = []
    open_loops: list[str] = []
    seen_preferences: set[str] = set()
    seen_open_loops: set[str] = set()
    for row in memory_rows:
        category = str(row.get("category") or "").strip().lower()
        content = str(row.get("content") or "").strip()
        if not content:
            continue
        if category == "preference" and content not in seen_preferences:
            seen_preferences.add(content)
            preferences.append(content)
        if category in {"open_loop", "todo", "follow_up"} and content not in seen_open_loops:
            seen_open_loops.add(content)
            open_loops.append(content)

    for row in task_rows:
        status = str(row.get("status") or "")
        user_input = build_task_display_user_input(
            str(row.get("user_input") or ""),
            normalize_runtime_overrides(row.get("runtime_overrides")),
        ).strip()
        if (
            status in {"pending", "running", "waiting_approval", "waiting_clarification", "paused", "interrupt_requested"}
            and user_input
            and user_input not in seen_open_loops
        ):
            seen_open_loops.add(user_input)
            open_loops.append(user_input)

    summary_parts = [f"Session: {session_row.get('name') or session_id}", f"tasks={len(task_rows)}"]
    if tasks_by_status:
        summary_parts.append(
            "statuses=" + ", ".join(f"{key}:{value}" for key, value in sorted(tasks_by_status.items()))
        )
    if preferences:
        summary_parts.append(f"preferences={len(preferences)}")
    if open_loops:
        summary_parts.append(f"open_loops={len(open_loops)}")
    summary_text = " | ".join(summary_parts)

    cur.execute(
        """
        INSERT INTO session_states (session_id, summary_text, preferences, open_loops)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (session_id) DO UPDATE
        SET summary_text = EXCLUDED.summary_text,
            preferences = EXCLUDED.preferences,
            open_loops = EXCLUDED.open_loops,
            updated_at = CURRENT_TIMESTAMP;
        """,
        (
            session_id,
            summary_text,
            safe_json_dumps(preferences),
            safe_json_dumps(open_loops),
        ),
    )


def capture_session_memory_for_completed_task(
    cur,
    task_id: int,
    user_input: str,
    final_result: str,
    *,
    ensure_sessions_tables,
    ensure_audit_logs_table,
    ensure_long_term_memory_table,
    build_task_display_user_input,
    normalize_runtime_overrides,
    build_task_summary_memory_content_fn,
    infer_task_memories_fn,
    upsert_long_term_memory,
    strip_artifact_suffix,
    rebuild_session_state_from_worker_fn,
    insert_audit_log,
):
    ensure_sessions_tables(cur)
    ensure_audit_logs_table(cur)
    ensure_long_term_memory_table(cur)
    cur.execute(
        """
        SELECT session_id, runtime_overrides, created_by_actor
        FROM task_runs
        WHERE id = %s;
        """,
        (task_id,),
    )
    row = cur.fetchone()
    session_id = row.get("session_id") if row else None
    actor_name = str((row or {}).get("created_by_actor") or "").strip()

    memory_ids: list[int] = []
    task_display_input = build_task_display_user_input(
        str(user_input or ""),
        normalize_runtime_overrides((row or {}).get("runtime_overrides")),
    )
    content = build_task_summary_memory_content_fn(task_display_input, final_result)
    upsert_long_term_memory(
        cur,
        memory_kind="task_memory",
        source_session_id=int(session_id) if session_id else None,
        source_task_id=task_id,
        actor_name=actor_name,
        title=task_display_input[:180],
        content=content,
        metadata={"deliverable_kind": "task_summary"},
    )
    upsert_long_term_memory(
        cur,
        memory_kind="conversation_memory",
        source_session_id=int(session_id) if session_id else None,
        source_task_id=task_id,
        actor_name=actor_name,
        title=task_display_input[:180],
        content=f"输入：{str(user_input or '').strip()[:1200]}\n\n输出：{strip_artifact_suffix(final_result)[:1600]}",
        metadata={"memory_scope": "conversation"},
    )
    if not session_id:
        cur.connection.commit()
        return
    cur.execute(
        """
        SELECT id
        FROM session_memories
        WHERE session_id = %s AND source_task_id = %s AND category = 'task_summary'
        ORDER BY id DESC
        LIMIT 1;
        """,
        (session_id, task_id),
    )
    existing = cur.fetchone()
    if existing:
        cur.execute(
            """
            UPDATE session_memories
            SET content = %s,
                importance = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s;
            """,
            (content, 2, existing["id"]),
        )
        memory_ids.append(int(existing["id"]))
    else:
        cur.execute(
            """
            INSERT INTO session_memories (session_id, category, content, importance, source_task_id)
            VALUES (%s, 'task_summary', %s, %s, %s)
            RETURNING id;
            """,
            (session_id, content, 2, task_id),
        )
        memory_ids.append(int(cur.fetchone()["id"]))

    inferred_memories = infer_task_memories_fn(task_display_input, final_result)
    for item in inferred_memories:
        category = str(item["category"]).strip().lower()
        inferred_content = str(item["content"]).strip()
        importance = int(item.get("importance", 3))
        if not inferred_content:
            continue
        upsert_long_term_memory(
            cur,
            memory_kind="pattern_memory" if category in {"preference", "follow_up"} else "task_memory",
            source_session_id=int(session_id),
            source_task_id=task_id,
            actor_name=actor_name,
            title=f"{category}:{task_display_input[:80]}",
            content=inferred_content,
            metadata={"category": category, "importance": importance},
        )

        cur.execute(
            """
            SELECT id
            FROM session_memories
            WHERE session_id = %s AND category = %s AND content = %s
            ORDER BY id DESC
            LIMIT 1;
            """,
            (session_id, category, inferred_content),
        )
        inferred_existing = cur.fetchone()
        if inferred_existing:
            cur.execute(
                """
                UPDATE session_memories
                SET importance = GREATEST(importance, %s),
                    source_task_id = COALESCE(source_task_id, %s),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s;
                """,
                (importance, task_id, inferred_existing["id"]),
            )
            memory_ids.append(int(inferred_existing["id"]))
        else:
            cur.execute(
                """
                INSERT INTO session_memories (session_id, category, content, importance, source_task_id)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id;
                """,
                (session_id, category, inferred_content, importance, task_id),
            )
            memory_ids.append(int(cur.fetchone()["id"]))

    rebuild_session_state_from_worker_fn(cur, int(session_id))
    insert_audit_log(
        cur,
        "session.memory_auto_capture",
        "worker",
        task_id,
        {
            "session_id": int(session_id),
            "memory_ids": memory_ids,
            "category": "task_summary",
            "inferred_categories": [str(item["category"]).strip().lower() for item in inferred_memories],
        },
    )
    cur.connection.commit()
