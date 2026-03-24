from trace_runtime import (
    clear_current_trace_context,
    complete_step_and_tool_trace,
    get_current_trace_context,
    record_model_trace,
    set_current_trace_context,
)


class FakeConnection:
    def __init__(self):
        self.commit_called = 0
        self.closed = False

    def commit(self):
        self.commit_called += 1

    def close(self):
        self.closed = True


class FakeCursor:
    def __init__(self, connection=None):
        self.connection = connection or FakeConnection()
        self.executed = []
        self.closed = False

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def close(self):
        self.closed = True


def test_trace_context_round_trip():
    set_current_trace_context(task_id=12, step_id=34, step_trace_id=56)

    assert get_current_trace_context() == {"task_id": 12, "step_id": 34, "step_trace_id": 56}

    clear_current_trace_context()
    assert get_current_trace_context() == {"task_id": None, "step_id": None, "step_trace_id": None}


def test_complete_step_and_tool_trace_updates_both_rows():
    conn = FakeConnection()
    cur = FakeCursor(connection=conn)

    complete_step_and_tool_trace(
        cur,
        step_trace_id=11,
        tool_trace_id=22,
        status="completed",
        safe_json_dumps=lambda value: str(value),
        trim_text=lambda value, limit=2000: str(value or "")[:limit],
        output_payload="done",
        output_data={"ok": True},
        error_summary="",
        retry_count=1,
    )

    assert len(cur.executed) == 2
    assert conn.commit_called == 1


def test_record_model_trace_uses_current_context_and_commits():
    conn = FakeConnection()
    cursor = FakeCursor(connection=conn)
    set_current_trace_context(task_id=7, step_id=8, step_trace_id=9)

    record_model_trace(
        route_name="planner",
        provider="deepseek",
        model_name="deepseek-chat",
        prompt_version="stage2-v1",
        prompt_text="hello",
        response_text="world",
        get_current_trace_context_fn=get_current_trace_context,
        get_conn=lambda: type("ConnWrapper", (), {"cursor": lambda self: cursor, "commit": conn.commit, "close": conn.close})(),
        ensure_trace_tables=lambda _cur: None,
        safe_json_dumps=lambda value: str(value),
        trim_text=lambda value, limit=1200: str(value or "")[:limit],
    )

    assert len(cursor.executed) == 1
    assert "INSERT INTO model_traces" in cursor.executed[0][0]
    assert conn.commit_called == 1
    assert cursor.closed is True
    assert conn.closed is True

    clear_current_trace_context()
