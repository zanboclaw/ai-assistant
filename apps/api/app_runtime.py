from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from core.runtime_logging import attach_optional_file_handler


def build_logger(log_dir: Path) -> logging.Logger:
    logger = logging.getLogger("ai_assistant.api")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("[%(asctime)s] %(levelname)s %(message)s")

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    logger.propagate = False

    attach_optional_file_handler(
        logger,
        logger_name="api",
        log_path=log_dir / "api.log",
        formatter=formatter,
    )

    return logger


def get_redis_client(*, redis_module, redis_url: str, logger):
    if redis_module is None:
        return None
    try:
        return redis_module.Redis.from_url(redis_url, decode_responses=True)
    except Exception as exc:
        logger.warning("redis client init failed: %s", exc)
        return None


def enqueue_task(task_id: int, *, get_redis_client_fn, logger):
    client = get_redis_client_fn()
    if client is None:
        logger.warning("redis unavailable, skip enqueue task_id=%s", task_id)
        return
    try:
        client.rpush("task_queue", str(task_id))
    except Exception as exc:
        logger.warning("enqueue task failed task_id=%s error=%s", task_id, exc)


def enqueue_agent_run(agent_run_id: int, *, get_redis_client_fn, logger):
    client = get_redis_client_fn()
    if client is None:
        logger.warning("redis unavailable, skip enqueue agent_run_id=%s", agent_run_id)
        return
    try:
        client.rpush("agent_run_queue", str(agent_run_id))
    except Exception as exc:
        logger.warning("enqueue agent run failed agent_run_id=%s error=%s", agent_run_id, exc)


def get_conn(*, psycopg2_module, db_config: dict[str, Any], cursor_factory):
    return psycopg2_module.connect(**db_config, cursor_factory=cursor_factory)


def insert_audit_log(
    cur,
    event_type: str,
    actor: str,
    *,
    safe_json_dumps,
    task_id: int | None = None,
    details: Any | None = None,
):
    cur.execute(
        """
        INSERT INTO audit_logs (task_id, event_type, actor, details)
        VALUES (%s, %s, %s, %s);
        """,
        (task_id, event_type, actor, safe_json_dumps(details) if details is not None else None),
    )


def record_audit_event(
    event_type: str,
    actor: str,
    *,
    get_conn_fn,
    ensure_audit_logs_table_fn,
    insert_audit_log_fn,
    task_id: int | None = None,
    details: Any | None = None,
):
    conn = get_conn_fn()
    cur = conn.cursor()
    try:
        ensure_audit_logs_table_fn(cur)
        insert_audit_log_fn(cur, event_type, actor, task_id=task_id, details=details)
        conn.commit()
    finally:
        cur.close()
        conn.close()


def parse_maybe_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except Exception:
        return value


def build_task_display_input_excerpt(
    task_row: dict[str, Any],
    *,
    build_task_display_user_input,
    parse_maybe_json_fn,
    limit: int = 180,
) -> str:
    runtime_overrides = parse_maybe_json_fn(task_row.get("runtime_overrides")) or {}
    return build_task_display_user_input(
        str(task_row.get("user_input") or ""),
        runtime_overrides,
    )[:limit]


def build_task_result_excerpt(task_row: dict[str, Any], *, strip_artifact_suffix, limit: int = 220) -> str:
    return strip_artifact_suffix(str(task_row.get("result") or ""))[:limit]


def attach_task_display_fields(
    task_row: dict[str, Any],
    *,
    parse_maybe_json_fn,
    extract_task_clarification_state,
    build_task_display_user_input,
    build_task_result_excerpt_fn,
) -> dict[str, Any]:
    runtime_overrides = parse_maybe_json_fn(task_row.get("runtime_overrides")) or {}
    original_user_input, clarification_history = extract_task_clarification_state(
        runtime_overrides,
        fallback_user_input=str(task_row.get("user_input") or ""),
    )
    task_row["display_user_input"] = build_task_display_user_input(
        str(task_row.get("user_input") or ""),
        runtime_overrides,
    )
    task_row["original_user_input"] = original_user_input
    task_row["clarification_count"] = len(clarification_history)
    task_row["result_excerpt"] = build_task_result_excerpt_fn(task_row)
    return task_row


def read_skill_package_from_source(
    source_path: str,
    *,
    workspace_root: Path,
    api_app_dir: Path,
    http_exception_cls,
) -> dict[str, Any]:
    normalized_path = str(source_path or "").strip()
    if not normalized_path:
        raise http_exception_cls(status_code=400, detail="source_path is required")
    candidate = (workspace_root / normalized_path).resolve() if not normalized_path.startswith("/") else Path(normalized_path).resolve()
    roots = [workspace_root.resolve(), api_app_dir.parent.resolve()]
    if not any(str(candidate).startswith(str(root)) for root in roots):
        raise http_exception_cls(status_code=400, detail="skill package path must stay inside repo")
    if not candidate.exists() or not candidate.is_file():
        raise http_exception_cls(status_code=404, detail="skill package source not found")
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except Exception as exc:
        raise http_exception_cls(status_code=400, detail=f"invalid skill package json: {exc}") from exc
    if not isinstance(payload, dict):
        raise http_exception_cls(status_code=400, detail="skill package must be a json object")
    skill_id = str(payload.get("skill_id") or "").strip()
    version = str(payload.get("version") or "").strip()
    steps_template = payload.get("steps_template")
    if not skill_id or not version:
        raise http_exception_cls(status_code=400, detail="skill package requires skill_id and version")
    if not isinstance(steps_template, list) or not steps_template:
        raise http_exception_cls(status_code=400, detail="skill package requires non-empty steps_template")
    return {
        "skill_id": skill_id,
        "display_name": str(payload.get("display_name") or skill_id),
        "description": str(payload.get("description") or ""),
        "entrypoint_kind": str(payload.get("entrypoint_kind") or "structured_steps"),
        "version": version,
        "package_format": "json",
        "package_source": str(candidate),
        "package_body": payload,
    }
