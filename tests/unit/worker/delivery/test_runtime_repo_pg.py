from apps.worker.infrastructure.db.runtime_repo_pg import (
    count_task_audit_events,
    find_first_step_order_by_tool,
    get_task_steps,
    select_final_outputs_for_task,
    update_task_delivery_records,
)


class FakeConnection:
    def __init__(self):
        self.commit_called = 0

    def commit(self):
        self.commit_called += 1


class FakeCursor:
    def __init__(self, *, fetchone_result=None, fetchall_result=None):
        self.connection = FakeConnection()
        self.fetchone_result = fetchone_result
        self.fetchall_result = fetchall_result or []
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((" ".join(str(sql).split()), params))

    def fetchone(self):
        return self.fetchone_result

    def fetchall(self):
        return self.fetchall_result


def test_get_task_steps_returns_rows_in_order():
    cur = FakeCursor(fetchall_result=[{"step_order": 1}, {"step_order": 2}])

    rows = get_task_steps(cur, 7)

    assert rows[0]["step_order"] == 1
    assert "FROM task_steps" in cur.executed[0][0]


def test_select_final_outputs_prefers_latest_generate_text():
    cur = FakeCursor(fetchone_result={"deliverable_spec_json": {"deliverable_type": "research_summary"}})

    result = select_final_outputs_for_task(
        cur,
        9,
        ["fallback"],
        parse_jsonish=lambda value, _default: value,
        get_task_steps_fn=lambda _cur, _task_id: [
            {"status": "completed", "tool_name": "search_query", "output_payload": "search"},
            {"status": "completed", "tool_name": "generate_text", "output_payload": "draft v1"},
            {"status": "completed", "tool_name": "generate_text", "output_payload": "draft v2"},
        ],
    )

    assert result == ["draft v2"]


def test_update_task_delivery_records_commits():
    cur = FakeCursor()

    update_task_delivery_records(cur, 11, validation_report={"passed": True}, recovery_action={"action": "none"})

    assert "UPDATE task_runs" in cur.executed[0][0]
    assert cur.connection.commit_called == 1


def test_count_task_audit_events_and_find_first_step():
    audit_cur = FakeCursor(fetchone_result={"count": 3})
    step_cur = FakeCursor(fetchone_result={"step_order": 2})

    assert count_task_audit_events(audit_cur, 12, "task.auto_recovery_applied") == 3
    assert find_first_step_order_by_tool(step_cur, 12, "generate_text") == 2
