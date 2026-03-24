from datetime import datetime, timedelta, timezone

from queue_runtime import (
    acquire_task_claim,
    dequeue_task,
    enqueue_task,
    requeue_stale_running_tasks,
)


class FakeLogger:
    def __init__(self):
        self.messages = []

    def warning(self, message, *args):
        self.messages.append(("warning", message % args if args else message))


class FakeRedis:
    def __init__(self, *, blpop_result=None, set_result=True):
        self.blpop_result = blpop_result
        self.set_result = set_result
        self.calls = []

    def rpush(self, queue_name, value):
        self.calls.append(("rpush", queue_name, value))

    def set(self, key, value, nx=None, ex=None):
        self.calls.append(("set", key, value, nx, ex))
        return self.set_result

    def blpop(self, queue_name, timeout=None):
        self.calls.append(("blpop", queue_name, timeout))
        return self.blpop_result


class FakeCursor:
    def __init__(self, *, fetchall_results=None):
        self.fetchall_results = list(fetchall_results or [])
        self.executed = []
        self.closed = False

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchall(self):
        if self.fetchall_results:
            return self.fetchall_results.pop(0)
        return []

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, cursor):
        self.cursor_instance = cursor
        self.commit_called = 0
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commit_called += 1

    def close(self):
        self.closed = True


def test_enqueue_and_acquire_task_claim_use_expected_redis_keys():
    logger = FakeLogger()
    redis_client = FakeRedis()

    enqueue_task(17, get_redis_client=lambda: redis_client, logger=logger)
    acquired = acquire_task_claim(
        17,
        "token-1",
        get_redis_client=lambda: redis_client,
        logger=logger,
        task_lock_ttl_seconds=300,
    )

    assert acquired is True
    assert redis_client.calls[0] == ("rpush", "task_queue", "17")
    assert redis_client.calls[1] == ("set", "task_claim:17", "token-1", True, 300)


def test_dequeue_task_returns_pending_task_only():
    logger = FakeLogger()
    redis_client = FakeRedis(blpop_result=("task_queue", "23"))

    task = dequeue_task(
        2,
        get_redis_client=lambda: redis_client,
        logger=logger,
        fetch_task_by_id_fn=lambda task_id: {"id": task_id, "status": "pending"},
    )

    assert task == {"id": 23, "status": "pending"}


def test_requeue_stale_running_tasks_updates_status_and_emits_audit():
    stale_time = datetime.now(timezone.utc) - timedelta(seconds=600)
    cursor = FakeCursor(
        fetchall_results=[
            [
                {"id": 31, "status": "running", "updated_at": stale_time},
                {"id": 32, "status": "running", "updated_at": datetime.now(timezone.utc)},
            ]
        ]
    )
    conn = FakeConnection(cursor)
    logger = FakeLogger()
    status_calls = []
    enqueue_calls = []
    audit_calls = []

    requeue_stale_running_tasks(
        get_conn=lambda: conn,
        logger=logger,
        task_stale_requeue_seconds=120,
        has_live_task_claim_fn=lambda task_id: False,
        update_task_status=lambda _cur, task_id, status, error_message, note: status_calls.append(
            (task_id, status, error_message, note)
        ),
        enqueue_task_fn=lambda task_id: enqueue_calls.append(task_id),
        record_worker_audit_event=lambda event_type, task_id, details: audit_calls.append((event_type, task_id, details)),
    )

    assert status_calls == [(31, "pending", None, "stale running task requeued")]
    assert enqueue_calls == [31]
    assert audit_calls[0][0] == "task.stale_requeue"
    assert conn.commit_called == 1
    assert conn.closed is True
    assert cursor.closed is True
