from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def fetch_task_by_id(task_id: int, *, get_conn) -> Optional[dict]:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT *
            FROM task_runs
            WHERE id = %s;
            """,
            (task_id,),
        )
        return cur.fetchone()
    finally:
        cur.close()
        conn.close()


def fetch_next_pending_task(*, get_conn):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT *
            FROM task_runs
            WHERE status = 'pending'
            ORDER BY id ASC
            LIMIT 1;
            """
        )
        return cur.fetchone()
    finally:
        cur.close()
        conn.close()


def task_claim_key(task_id: int) -> str:
    return f"task_claim:{task_id}"


def agent_run_claim_key(agent_run_id: int) -> str:
    return f"agent_run_claim:{agent_run_id}"


def enqueue_task(task_id: int, *, get_redis_client, logger):
    client = get_redis_client()
    if client is None:
        return
    try:
        client.rpush("task_queue", str(task_id))
    except Exception as exc:
        logger.warning("enqueue task failed task_id=%s error=%s", task_id, exc)


def enqueue_agent_run(agent_run_id: int, *, get_redis_client, logger):
    client = get_redis_client()
    if client is None:
        return
    try:
        client.rpush("agent_run_queue", str(agent_run_id))
    except Exception as exc:
        logger.warning("enqueue agent run failed agent_run_id=%s error=%s", agent_run_id, exc)


def acquire_task_claim(task_id: int, claim_token: str, *, get_redis_client, logger, task_lock_ttl_seconds: int) -> bool:
    client = get_redis_client()
    if client is None:
        return True
    try:
        return bool(client.set(task_claim_key(task_id), claim_token, nx=True, ex=task_lock_ttl_seconds))
    except Exception as exc:
        logger.warning("task claim failed task_id=%s error=%s", task_id, exc)
        return True


def renew_task_claim(task_id: int, claim_token: str, *, get_redis_client, logger, task_lock_ttl_seconds: int) -> bool:
    client = get_redis_client()
    if client is None:
        return True
    try:
        result = client.eval(
            """
            if redis.call('GET', KEYS[1]) == ARGV[1] then
                return redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
            end
            return 0
            """,
            1,
            task_claim_key(task_id),
            claim_token,
            str(task_lock_ttl_seconds),
        )
        return bool(result)
    except Exception as exc:
        logger.warning("renew task claim failed task_id=%s error=%s", task_id, exc)
        return False


def release_task_claim(task_id: int, claim_token: str, *, get_redis_client, logger):
    client = get_redis_client()
    if client is None:
        return
    try:
        client.eval(
            """
            if redis.call('GET', KEYS[1]) == ARGV[1] then
                return redis.call('DEL', KEYS[1])
            end
            return 0
            """,
            1,
            task_claim_key(task_id),
            claim_token,
        )
    except Exception as exc:
        logger.warning("release task claim failed task_id=%s error=%s", task_id, exc)


def has_live_task_claim(task_id: int, *, get_redis_client, logger) -> bool:
    client = get_redis_client()
    if client is None:
        return False
    try:
        return bool(client.exists(task_claim_key(task_id)))
    except Exception as exc:
        logger.warning("check task claim failed task_id=%s error=%s", task_id, exc)
        return False


def acquire_agent_run_claim(agent_run_id: int, claim_token: str, *, get_redis_client, logger, task_lock_ttl_seconds: int) -> bool:
    client = get_redis_client()
    if client is None:
        return True
    try:
        return bool(client.set(agent_run_claim_key(agent_run_id), claim_token, nx=True, ex=task_lock_ttl_seconds))
    except Exception as exc:
        logger.warning("agent run claim failed agent_run_id=%s error=%s", agent_run_id, exc)
        return True


def release_agent_run_claim(agent_run_id: int, claim_token: str, *, get_redis_client, logger):
    client = get_redis_client()
    if client is None:
        return
    try:
        client.eval(
            """
            if redis.call('GET', KEYS[1]) == ARGV[1] then
                return redis.call('DEL', KEYS[1])
            end
            return 0
            """,
            1,
            agent_run_claim_key(agent_run_id),
            claim_token,
        )
    except Exception as exc:
        logger.warning("release agent run claim failed agent_run_id=%s error=%s", agent_run_id, exc)


def dequeue_task(timeout_seconds: int = 2, *, get_redis_client, logger, fetch_task_by_id_fn) -> Optional[dict]:
    client = get_redis_client()
    if client is None:
        return None
    try:
        item = client.blpop("task_queue", timeout=timeout_seconds)
    except Exception as exc:
        logger.warning("redis dequeue failed: %s", exc)
        return None

    if not item:
        return None

    _, raw_task_id = item
    try:
        task_id = int(raw_task_id)
    except Exception:
        return None

    task = fetch_task_by_id_fn(task_id)
    if not task or task.get("status") != "pending":
        return None
    return task


def dequeue_agent_run(timeout_seconds: int = 1, *, get_redis_client, logger, fetch_agent_run_by_id_fn) -> Optional[dict]:
    client = get_redis_client()
    if client is None:
        return None
    try:
        item = client.blpop("agent_run_queue", timeout=timeout_seconds)
    except Exception as exc:
        logger.warning("redis agent run dequeue failed: %s", exc)
        return None
    if not item:
        return None
    _, raw_agent_run_id = item
    try:
        agent_run_id = int(raw_agent_run_id)
    except Exception:
        return None
    agent_run = fetch_agent_run_by_id_fn(agent_run_id)
    if not agent_run or str(agent_run.get("status") or "") not in {"queued", "running"}:
        return None
    return agent_run


def requeue_stale_running_tasks(
    *,
    get_conn,
    logger,
    task_stale_requeue_seconds: int,
    has_live_task_claim_fn,
    update_task_status,
    enqueue_task_fn,
    record_worker_audit_event,
):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT id, status, updated_at
            FROM task_runs
            WHERE status IN ('running', 'interrupt_requested')
            ORDER BY id ASC;
            """
        )
        rows = list(cur.fetchall())
        now = datetime.now(timezone.utc)
        for row in rows:
            updated_at = row.get("updated_at")
            if updated_at is None:
                continue
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            age_seconds = (now - updated_at).total_seconds()
            if age_seconds < task_stale_requeue_seconds:
                continue
            task_id = int(row["id"])
            if has_live_task_claim_fn(task_id):
                continue

            update_task_status(cur, task_id, "pending", None, "stale running task requeued")
            conn.commit()
            enqueue_task_fn(task_id)
            logger.warning(
                "stale task requeued task_id=%s previous_status=%s age_seconds=%s",
                task_id,
                row.get("status"),
                int(age_seconds),
            )
            record_worker_audit_event(
                "task.stale_requeue",
                task_id,
                {
                    "previous_status": row.get("status"),
                    "age_seconds": int(age_seconds),
                },
            )
    finally:
        cur.close()
        conn.close()
