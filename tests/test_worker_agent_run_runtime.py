import json

from agent_run_runtime import process_agent_run


class FakeCursor:
    def __init__(self, *, fetchone_results=None, fetchall_results=None):
        self.fetchone_results = list(fetchone_results or [])
        self.fetchall_results = list(fetchall_results or [])
        self.executed = []
        self.closed = False

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        if self.fetchone_results:
            return self.fetchone_results.pop(0)
        return None

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
        self.rollback_called = 0
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commit_called += 1

    def rollback(self):
        self.rollback_called += 1

    def close(self):
        self.closed = True


class FakeLogger:
    def __init__(self):
        self.messages = []

    def info(self, message, *args):
        self.messages.append(("info", message % args if args else message))

    def exception(self, message, *args):
        self.messages.append(("exception", message % args if args else message))


def test_process_agent_run_skips_non_specialist_without_db_access():
    logger = FakeLogger()
    called = []

    process_agent_run(
        {
            "id": 1,
            "task_run_id": 9,
            "role": "manager",
            "execution_mode": "worker_readonly_v1",
            "assigned_tool_profile": "specialist-readonly",
            "execution_request_json": "{}",
            "assigned_step_orders_json": "[]",
        },
        logger=logger,
        get_conn=lambda: called.append("get_conn"),
        ensure_agent_tables=lambda _cur: None,
        ensure_evaluator_tables=lambda _cur: None,
        ensure_task_steps_columns=lambda _cur: None,
        ensure_audit_logs_table=lambda _cur: None,
        parse_jsonish=lambda value, default=None: json.loads(value) if isinstance(value, str) and value else (default if default is not None else {}),
        build_task_display_input_excerpt=lambda _task: "input",
        build_task_result_excerpt=lambda _task: "result",
        tool_shell_exec=lambda command: {"ok": True, "output_data": {"stdout": command, "returncode": 0}},
        tool_file_read=lambda path: {"ok": True, "output_data": {"raw_text": f"raw:{path}"}},
        tool_read_json=lambda path: {"ok": True, "output_data": {"json": {"path": path}}},
        tool_json_extract=lambda data, path: {"ok": True, "output_data": {"value": data.get(path)}},
        tool_list_dir=lambda path: {"ok": True, "output_data": {"entries": [path]}},
        create_agent_artifact=lambda *_args, **_kwargs: 1,
        create_agent_message=lambda *_args, **_kwargs: 1,
        insert_audit_log=lambda *_args, **_kwargs: None,
        maybe_refresh_task_runtime_manager_rollup=lambda *_args, **_kwargs: None,
        auto_stage5_runtime_execution_mode="task_runtime_worker_v1",
        mainline_specialist_tool_profiles={"specialist-readonly"},
        restricted_specialist_subtask_type="restricted_shell_probe",
    )

    assert called == []
    assert logger.messages[0][1].startswith("skip non-specialist")


def test_process_agent_run_builds_text_file_snapshot_artifact():
    cursor = FakeCursor(
        fetchone_results=[
            {"id": 8, "status": "running", "checkpoint_path": "", "result": "done", "error_message": ""},
            None,
        ],
        fetchall_results=[
            [
                {
                    "step_order": 1,
                    "step_name": "collect",
                    "status": "completed",
                    "tool_name": "file_read",
                    "input_payload": "docs/a.md",
                    "output_payload": "content",
                    "error_message": "",
                }
            ]
        ],
    )
    conn = FakeConnection(cursor)
    logger = FakeLogger()
    artifact_calls = []
    message_calls = []
    audit_calls = []

    process_agent_run(
        {
            "id": 21,
            "task_run_id": 8,
            "role": "specialist",
            "execution_mode": "worker_readonly_v1",
            "assigned_tool_profile": "specialist-readonly",
            "execution_request_json": json.dumps(
                {
                    "subtask_type": "readonly_source_snapshot",
                    "source": {"kind": "text_file", "path": "docs/api.md"},
                    "slot": 2,
                    "objective": "读取文档",
                },
                ensure_ascii=False,
            ),
            "assigned_step_orders_json": "[1]",
            "output_artifact_id": None,
        },
        logger=logger,
        get_conn=lambda: conn,
        ensure_agent_tables=lambda _cur: None,
        ensure_evaluator_tables=lambda _cur: None,
        ensure_task_steps_columns=lambda _cur: None,
        ensure_audit_logs_table=lambda _cur: None,
        parse_jsonish=lambda value, default=None: json.loads(value) if isinstance(value, str) and value else (default if default is not None else {}),
        build_task_display_input_excerpt=lambda _task: "input",
        build_task_result_excerpt=lambda _task: "result",
        tool_shell_exec=lambda command: {"ok": True, "output_data": {"stdout": command, "returncode": 0}},
        tool_file_read=lambda path: {"ok": True, "output_data": {"raw_text": f"raw:{path}"}},
        tool_read_json=lambda path: {"ok": True, "output_data": {"json": {"path": path}}},
        tool_json_extract=lambda data, path: {"ok": True, "output_data": {"value": data.get(path)}},
        tool_list_dir=lambda path: {"ok": True, "output_data": {"entries": [path]}},
        create_agent_artifact=lambda _cur, task_id, agent_run_id, artifact_type, summary, content, **kwargs: artifact_calls.append(
            (task_id, agent_run_id, artifact_type, summary, content, kwargs)
        ) or 101,
        create_agent_message=lambda _cur, task_id, agent_run_id, sender_role, recipient_role, message_type, payload, **kwargs: message_calls.append(
            (task_id, agent_run_id, sender_role, recipient_role, message_type, payload, kwargs)
        ) or 201,
        insert_audit_log=lambda _cur, event_type, actor, task_id, details: audit_calls.append((event_type, actor, task_id, details)),
        maybe_refresh_task_runtime_manager_rollup=lambda *_args, **_kwargs: None,
        auto_stage5_runtime_execution_mode="task_runtime_worker_v1",
        mainline_specialist_tool_profiles={"specialist-readonly"},
        restricted_specialist_subtask_type="restricted_shell_probe",
    )

    assert conn.commit_called == 1
    assert conn.rollback_called == 0
    assert conn.closed is True
    assert cursor.closed is True
    assert artifact_calls[0][0:4] == (8, 21, "draft", "worker specialist draft")
    artifact_payload = artifact_calls[0][4]
    assert artifact_payload["summary"] == "worker executed readonly source snapshot"
    assert artifact_payload["output"]["execution_result"]["source"]["path"] == "docs/api.md"
    assert message_calls[-1][4] == "result"
    assert audit_calls[0][0] == "agent.worker_execute_demo"
