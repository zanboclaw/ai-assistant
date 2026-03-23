from __future__ import annotations

import hashlib
import json
import re
from typing import Any


TOKEN_RE = re.compile(r"[A-Za-z0-9_\-\u4e00-\u9fff]{2,}")


def normalize_memory_keywords(*parts: Any) -> list[str]:
    seen: set[str] = set()
    keywords: list[str] = []
    for part in parts:
        for token in TOKEN_RE.findall(str(part or "").lower()):
            token = token.strip()
            if not token or token in seen:
                continue
            seen.add(token)
            keywords.append(token[:48])
            if len(keywords) >= 32:
                return keywords
    return keywords


def build_long_term_memory_key(memory_kind: str, title: str, content: str) -> str:
    payload = f"{memory_kind.strip().lower()}::{title.strip()}::{content.strip()}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def serialize_long_term_memory_row(row: dict[str, Any]) -> dict[str, Any]:
    def parse_jsonish(value: Any, default: Any):
        if value is None:
            return default
        if isinstance(value, (dict, list)):
            return value
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return default
            try:
                return json.loads(text)
            except Exception:
                return default
        return default

    return {
        "id": row.get("id"),
        "memory_key": row.get("memory_key"),
        "memory_kind": row.get("memory_kind"),
        "source_session_id": row.get("source_session_id"),
        "source_task_id": row.get("source_task_id"),
        "actor_name": row.get("actor_name") or "",
        "title": row.get("title") or "",
        "content": row.get("content") or "",
        "keywords": parse_jsonish(row.get("keywords_json"), []),
        "metadata": parse_jsonish(row.get("metadata_json"), {}),
        "hit_count": int(row.get("hit_count") or 0),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def ensure_long_term_memory_table(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS long_term_memories (
            id SERIAL PRIMARY KEY,
            memory_key TEXT NOT NULL UNIQUE,
            memory_kind TEXT NOT NULL,
            source_session_id INTEGER,
            source_task_id INTEGER,
            actor_name TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL,
            keywords_json TEXT NOT NULL DEFAULT '[]',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            hit_count INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )


def upsert_long_term_memory(
    cur,
    *,
    memory_kind: str,
    title: str,
    content: str,
    source_session_id: int | None = None,
    source_task_id: int | None = None,
    actor_name: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    normalized_content = str(content or "").strip()
    if not normalized_content:
        return None

    ensure_long_term_memory_table(cur)
    normalized_title = str(title or "").strip()[:240]
    normalized_kind = str(memory_kind or "task_memory").strip().lower() or "task_memory"
    memory_key = build_long_term_memory_key(normalized_kind, normalized_title, normalized_content)
    keywords = normalize_memory_keywords(normalized_title, normalized_content)
    cur.execute(
        """
        INSERT INTO long_term_memories (
            memory_key,
            memory_kind,
            source_session_id,
            source_task_id,
            actor_name,
            title,
            content,
            keywords_json,
            metadata_json,
            hit_count
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
        ON CONFLICT (memory_key) DO UPDATE
        SET source_session_id = COALESCE(EXCLUDED.source_session_id, long_term_memories.source_session_id),
            source_task_id = COALESCE(EXCLUDED.source_task_id, long_term_memories.source_task_id),
            actor_name = CASE
                WHEN EXCLUDED.actor_name <> '' THEN EXCLUDED.actor_name
                ELSE long_term_memories.actor_name
            END,
            title = CASE
                WHEN EXCLUDED.title <> '' THEN EXCLUDED.title
                ELSE long_term_memories.title
            END,
            content = EXCLUDED.content,
            keywords_json = EXCLUDED.keywords_json,
            metadata_json = EXCLUDED.metadata_json,
            hit_count = long_term_memories.hit_count + 1,
            updated_at = CURRENT_TIMESTAMP
        RETURNING
            id,
            memory_key,
            memory_kind,
            source_session_id,
            source_task_id,
            actor_name,
            title,
            content,
            keywords_json,
            metadata_json,
            hit_count,
            created_at,
            updated_at;
        """,
        (
            memory_key,
            normalized_kind,
            source_session_id,
            source_task_id,
            str(actor_name or "").strip(),
            normalized_title,
            normalized_content,
            json.dumps(keywords, ensure_ascii=False),
            json.dumps(metadata or {}, ensure_ascii=False),
        ),
    )
    row = cur.fetchone()
    return serialize_long_term_memory_row(row) if row else None


def search_long_term_memories(
    cur,
    query: str,
    *,
    memory_kind: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    normalized_query = str(query or "").strip()
    if not normalized_query:
        return []

    ensure_long_term_memory_table(cur)
    params: list[Any] = []
    query_sql = """
        SELECT
            id,
            memory_key,
            memory_kind,
            source_session_id,
            source_task_id,
            actor_name,
            title,
            content,
            keywords_json,
            metadata_json,
            hit_count,
            created_at,
            updated_at
        FROM long_term_memories
    """
    if memory_kind:
        query_sql += " WHERE memory_kind = %s"
        params.append(memory_kind)
    query_sql += " ORDER BY updated_at DESC, id DESC LIMIT 200;"
    cur.execute(query_sql, tuple(params))
    rows = [serialize_long_term_memory_row(row) for row in cur.fetchall()]
    if not rows:
        return []

    query_tokens = set(normalize_memory_keywords(normalized_query))

    def score_row(row: dict[str, Any]) -> tuple[int, int, int]:
        title = str(row.get("title") or "")
        content = str(row.get("content") or "")
        keywords = {str(item).strip().lower() for item in (row.get("keywords") or []) if str(item).strip()}
        overlap = len(query_tokens & keywords)
        substring_bonus = 2 if normalized_query.lower() in content.lower() or normalized_query.lower() in title.lower() else 0
        hit_count = int(row.get("hit_count") or 0)
        freshness = int(row.get("id") or 0)
        return overlap + substring_bonus, hit_count, freshness

    scored = [row for row in rows if score_row(row)[0] > 0]
    if not scored:
        scored = rows[: max(5, limit * 2)]
    scored.sort(key=score_row, reverse=True)
    return scored[: max(1, limit)]
