from memory_runtime import (
    build_task_summary_memory_content,
    capture_session_memory_for_completed_task,
    extract_marked_clauses,
    infer_task_memories,
    rebuild_session_state_from_worker,
)


class FakeConnection:
    def __init__(self):
        self.commit_called = 0

    def commit(self):
        self.commit_called += 1


class FakeCursor:
    def __init__(self, *, fetchone_results=None, fetchall_results=None):
        self.connection = FakeConnection()
        self.fetchone_results = list(fetchone_results or [])
        self.fetchall_results = list(fetchall_results or [])
        self.executed = []

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


def test_extract_marked_clauses_and_infer_task_memories():
    clauses = extract_marked_clauses("下一步继续处理；这里先暂停。", ("下一步", "继续"))
    memories = infer_task_memories(
        "以后请用中文分点回答，下一步继续处理。",
        "当前任务已完成，但后续需要继续跟进。",
        strip_artifact_suffix=lambda text: text,
        extract_marked_clauses_fn=extract_marked_clauses,
    )

    assert clauses == ["下一步继续处理"]
    assert any(item["category"] == "preference" for item in memories)
    assert any(item["category"] == "follow_up" for item in memories)
    assert any(item["category"] == "fact" for item in memories)


def test_build_task_summary_memory_content_trims_result():
    content = build_task_summary_memory_content(
        "整理执行结果",
        "A" * 1400,
        strip_artifact_suffix=lambda text: text,
    )

    assert content.startswith("任务：整理执行结果")
    assert content.endswith("...")


def test_rebuild_session_state_from_worker_collects_open_loops():
    cur = FakeCursor(
        fetchone_results=[{"id": 1, "name": "session-a"}],
        fetchall_results=[
            [
                {"id": 11, "user_input": "继续完善方案", "status": "running", "runtime_overrides": {}},
                {"id": 12, "user_input": "已完成任务", "status": "completed", "runtime_overrides": {}},
            ],
            [
                {"category": "preference", "content": "偏好中文回答", "importance": 4},
                {"category": "follow_up", "content": "下一步补测试", "importance": 3},
            ],
        ],
    )

    rebuild_session_state_from_worker(
        cur,
        1,
        build_task_display_user_input=lambda user_input, _overrides: user_input,
        normalize_runtime_overrides=lambda value: value or {},
        safe_json_dumps=lambda value: str(value),
    )

    assert "INSERT INTO session_states" in cur.executed[-1][0]


def test_capture_session_memory_for_completed_task_records_summary_and_audit():
    cur = FakeCursor(
        fetchone_results=[
            {"session_id": 8, "runtime_overrides": {}, "created_by_actor": "alice"},
            None,
            {"id": 81},
            None,
            {"id": 82},
        ]
    )
    long_term_calls = []
    audit_calls = []

    capture_session_memory_for_completed_task(
        cur,
        99,
        "请用中文总结",
        "任务完成，下一步继续补测试。",
        ensure_sessions_tables=lambda _cur: None,
        ensure_audit_logs_table=lambda _cur: None,
        ensure_long_term_memory_table=lambda _cur: None,
        build_task_display_user_input=lambda user_input, _overrides: user_input,
        normalize_runtime_overrides=lambda value: value or {},
        build_task_summary_memory_content_fn=lambda task_display_input, final_result: f"{task_display_input}:{final_result}",
        infer_task_memories_fn=lambda _user_input, _final_result: [{"category": "follow_up", "content": "下一步继续补测试", "importance": 3}],
        upsert_long_term_memory=lambda _cur, **kwargs: long_term_calls.append(kwargs),
        strip_artifact_suffix=lambda text: text,
        rebuild_session_state_from_worker_fn=lambda _cur, _session_id: audit_calls.append(("rebuild", _session_id)),
        insert_audit_log=lambda _cur, event_type, actor, task_id, details: audit_calls.append((event_type, actor, task_id, details)),
    )

    assert len(long_term_calls) == 3
    assert audit_calls[0] == ("rebuild", 8)
    assert audit_calls[1][0] == "session.memory_auto_capture"
    assert cur.connection.commit_called == 1
