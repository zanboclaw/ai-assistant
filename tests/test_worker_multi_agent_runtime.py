import json

from multi_agent_runtime import (
    augment_user_input_with_runtime_feedback,
    build_mainline_specialist_specs,
    build_specialist_execution_request,
    build_workflow_proposal,
    maybe_dispatch_task_runtime_specialists,
    maybe_initialize_task_runtime_agent_records,
    resolve_specialist_fanout_strategy,
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


class FakeConnWithCursor:
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


def test_build_mainline_specialist_specs_adds_restricted_probe_when_needed():
    step_outline, specs, step_status_counts = build_mainline_specialist_specs(
        step_rows=[
            {
                "step_order": 1,
                "step_name": "scan",
                "status": "completed",
                "tool_name": "web_search",
                "input_payload": "query",
                "output_payload": "result",
                "error_message": "",
            },
            {
                "step_order": 2,
                "step_name": "patch",
                "status": "running",
                "tool_name": "file_write",
                "input_payload": "file",
                "output_payload": "",
                "error_message": "",
            },
        ],
        task_row={"status": "running", "result": "", "error_message": ""},
        auto_stage5_specialist_count=2,
        restricted_specialist_subtask_type="restricted_shell_probe",
        restricted_specialist_tool_names={"file_write", "write_json"},
        build_task_display_input_excerpt=lambda _task: "input",
        build_task_result_excerpt=lambda _task: "result",
    )

    assert len(step_outline) == 2
    assert len(specs) == 3
    assert specs[-1]["tool_profile"] == "specialist-restricted"
    assert specs[-1]["source"]["command"] == "ls /workspace"
    assert step_status_counts == {"completed": 1, "running": 1}


def test_build_specialist_execution_request_marks_restricted_probe_constraints():
    request = build_specialist_execution_request(
        slot=3,
        manager_objective="排查执行风险",
        assigned_steps=[{"step_order": 4}],
        execution_mode="task_runtime_worker_v1",
        tool_profile="specialist-restricted",
        subtask_type="restricted_shell_probe",
        source={"command": "pwd"},
        restricted_specialist_subtask_type="restricted_shell_probe",
    )

    assert request["scope"] == "restricted_tool_probe"
    assert request["deliverable"] == "restricted shell probe"
    assert "shell-whitelist-only" in request["constraints"]
    assert request["assigned_step_orders"] == [4]


def test_build_workflow_proposal_maps_failed_step_to_repair_action():
    proposal = build_workflow_proposal(
        task_id=99,
        reviewer_decision="rejected",
        failure_profile={
            "failure_reason": "task_failed_step",
            "failure_stage": "execution",
            "recommendation": "先修复失败步骤",
        },
        quality_bundle={"score": 58},
        next_strategy="resume_task",
    )

    assert proposal["priority"] == "high"
    assert proposal["action_key"] == "repair_failed_steps"
    assert proposal["target_surface"] == "task_runtime"


def test_augment_user_input_with_runtime_feedback_appends_context():
    augmented = augment_user_input_with_runtime_feedback(
        "请继续执行",
        {
            "decision": "rework_required",
            "recommendation": "补齐缺失输出",
            "proposal": {"action_key": "queue_specialists"},
        },
    )

    assert "请继续执行" in augmented
    assert "decision: rework_required" in augmented
    assert "workflow proposal: queue_specialists" in augmented


def test_resolve_specialist_fanout_strategy_expands_after_evaluator_feedback():
    strategy = resolve_specialist_fanout_strategy(
        {
            "task_intent_json": {},
            "deliverable_spec_json": {"deliverable_type": "research_summary"},
        },
        {
            "decision": "rejected",
            "failure_stage": "execution",
            "proposal": {"action_key": "expand_specialist_scope"},
        },
        extract_task_intent=lambda row: row["task_intent_json"],
        extract_deliverable_spec=lambda row: row["deliverable_spec_json"],
        auto_stage5_specialist_count=2,
    )

    assert strategy["enabled"] is True
    assert strategy["specialist_count"] == 3
    assert strategy["use_restricted_probe"] is True


def test_maybe_initialize_task_runtime_agent_records_creates_mainline_records():
    cursor = FakeCursor(
        fetchone_results=[
            {
                "id": 42,
                "status": "running",
                "result": "done",
                "error_message": "",
            }
        ],
        fetchall_results=[
            [],
            [
                {
                    "step_order": 1,
                    "step_name": "plan",
                    "status": "completed",
                    "tool_name": "generate_text",
                    "input_payload": "a",
                    "output_payload": "b",
                    "error_message": "",
                }
            ],
        ],
    )
    artifact_calls = []
    run_calls = []
    message_calls = []
    audit_calls = []
    next_id = {"value": 100}

    def take_id():
        next_id["value"] += 1
        return next_id["value"]

    maybe_initialize_task_runtime_agent_records(
        cursor,
        42,
        "帮我整理方案",
        auto_stage5_postrun_enabled=True,
        auto_stage5_specialist_count=2,
        auto_stage5_execution_mode="task_postrun_readonly_v1",
        auto_stage5_runtime_execution_mode="task_runtime_worker_v1",
        multi_agent_protocol_version="multi-agent-v1",
        mainline_specialist_tool_profiles={"specialist-readonly", "specialist-restricted"},
        restricted_specialist_subtask_type="restricted_shell_probe",
        restricted_specialist_tool_names={"file_write", "write_json"},
        ensure_agent_tables=lambda _cur: None,
        ensure_evaluator_tables=lambda _cur: None,
        ensure_task_steps_columns=lambda _cur: None,
        ensure_audit_logs_table=lambda _cur: None,
        build_task_display_input=lambda _task: "任务目标",
        build_task_display_input_excerpt=lambda _task: "任务输入摘要",
        build_task_result_excerpt=lambda _task: "任务结果摘要",
        safe_json_dumps=lambda value: json.dumps(value, ensure_ascii=False),
        insert_audit_log=lambda _cur, event_type, actor, task_id, details: audit_calls.append((event_type, actor, task_id, details)),
        create_agent_artifact_fn=lambda _cur, task_run_id, agent_run_id, artifact_type, summary, content, **_kwargs: artifact_calls.append(
            (task_run_id, agent_run_id, artifact_type, summary, content)
        ) or take_id(),
        create_agent_message_fn=lambda _cur, task_run_id, agent_run_id, sender_role, recipient_role, message_type, payload, **_kwargs: message_calls.append(
            (task_run_id, agent_run_id, sender_role, recipient_role, message_type, payload)
        ) or take_id(),
        create_agent_run_fn=lambda _cur, task_run_id, role, status, **kwargs: run_calls.append(
            (task_run_id, role, status, kwargs)
        ) or take_id(),
        build_mainline_specialist_specs_fn=lambda **_kwargs: (
            [{"step_order": 1, "step_name": "plan", "status": "completed", "tool_name": "generate_text"}],
            [
                {
                    "slot": 1,
                    "assigned_steps": [{"step_order": 1, "status": "completed"}],
                    "subtask_type": "readonly_task_snapshot",
                    "tool_profile": "specialist-readonly",
                    "scope": "task_snapshot",
                    "source": {},
                },
                {
                    "slot": 2,
                    "assigned_steps": [{"step_order": 2, "status": "running"}],
                    "subtask_type": "readonly_step_digest",
                    "tool_profile": "specialist-readonly",
                    "scope": "risk_result_digest",
                    "source": {},
                },
            ],
            {"completed": 1},
        ),
        build_specialist_execution_request_fn=lambda **kwargs: {
            "slot": kwargs["slot"],
            "assigned_step_orders": [step.get("step_order", 0) for step in kwargs.get("assigned_steps") or [] if step.get("step_order")],
            "tool_profile": kwargs["tool_profile"],
        },
    )

    assert [item[2] for item in artifact_calls] == ["plan", "brief", "brief"]
    assert [item[1] for item in run_calls] == ["manager", "specialist", "specialist", "reviewer"]
    assert len(message_calls) == 2
    assert audit_calls[0][0] == "agent.postrun_initialized"
    assert cursor.connection.commit_called == 1


def test_maybe_dispatch_task_runtime_specialists_queues_runtime_specialists():
    cursor = FakeCursor(
        fetchone_results=[
            {"id": 77, "status": "waiting_approval", "user_input": "排查任务"},
            {"id": 901},
        ],
        fetchall_results=[
            [
                {
                    "id": 101,
                    "role": "manager",
                    "status": "running",
                    "brief_artifact_id": 11,
                    "output_artifact_id": 12,
                    "execution_mode": "",
                    "execution_request_json": "",
                    "source_task_run_id": 77,
                    "assigned_step_orders_json": "[]",
                    "assigned_model": "planner-postrun",
                    "assigned_tool_profile": "manager-mainline",
                },
                {
                    "id": 202,
                    "role": "specialist",
                    "status": "planned",
                    "brief_artifact_id": 21,
                    "output_artifact_id": None,
                    "execution_mode": "task_postrun_readonly_v1",
                    "execution_request_json": "",
                    "source_task_run_id": 77,
                    "assigned_step_orders_json": "[]",
                    "assigned_model": "specialist-postrun-1",
                    "assigned_tool_profile": "specialist-readonly",
                },
                {
                    "id": 303,
                    "role": "reviewer",
                    "status": "planned",
                    "brief_artifact_id": None,
                    "output_artifact_id": None,
                    "execution_mode": "",
                    "execution_request_json": "",
                    "source_task_run_id": 77,
                    "assigned_step_orders_json": "[]",
                    "assigned_model": "review-postrun",
                    "assigned_tool_profile": "review-readonly",
                },
            ],
            [
                {
                    "step_order": 1,
                    "step_name": "inspect",
                    "status": "completed",
                    "tool_name": "web_search",
                    "input_payload": "q",
                    "output_payload": "r",
                    "error_message": "",
                }
            ],
        ],
    )
    conn = FakeConnWithCursor(cursor)
    audit_calls = []
    enqueued = []
    processed = []
    released = []

    maybe_dispatch_task_runtime_specialists(
        77,
        "waiting_approval",
        auto_stage5_postrun_enabled=True,
        auto_stage5_execution_mode="task_postrun_readonly_v1",
        auto_stage5_runtime_execution_mode="task_runtime_worker_v1",
        multi_agent_protocol_version="multi-agent-v1",
        mainline_specialist_tool_profiles={"specialist-readonly", "specialist-restricted"},
        restricted_specialist_subtask_type="restricted_shell_probe",
        auto_stage5_specialist_count=1,
        restricted_specialist_tool_names={"file_write", "write_json"},
        get_conn=lambda: conn,
        ensure_agent_tables=lambda _cur: None,
        ensure_task_steps_columns=lambda _cur: None,
        ensure_audit_logs_table=lambda _cur: None,
        fetch_latest_evaluator_feedback=lambda _cur, _task_id: {},
        resolve_specialist_fanout_strategy=lambda _task_row, _latest: {"enabled": True, "specialist_count": 1, "use_restricted_probe": False},
        build_task_display_input=lambda _task_row: "任务目标",
        build_task_display_input_excerpt=lambda _task_row: "摘要",
        build_task_result_excerpt=lambda _task_row: "结果摘要",
        build_mainline_specialist_specs_fn=lambda **_kwargs: (
            [],
            [
                {
                    "assigned_steps": [{"step_order": 1, "status": "completed"}],
                    "subtask_type": "readonly_step_digest",
                    "tool_profile": "specialist-readonly",
                    "source": {},
                }
            ],
            {"completed": 1},
        ),
        build_specialist_execution_request_fn=lambda **kwargs: {
            "assigned_step_orders": [1],
            "subtask_type": kwargs["subtask_type"],
            "execution_mode": kwargs["execution_mode"],
        },
        insert_audit_log=lambda _cur, event_type, actor, task_id, details: audit_calls.append((event_type, actor, task_id, details)),
        safe_json_dumps=lambda value: json.dumps(value, ensure_ascii=False),
        enqueue_agent_run=lambda agent_run_id: enqueued.append(agent_run_id),
        acquire_agent_run_claim=lambda _agent_run_id, _claim_token: True,
        release_agent_run_claim=lambda agent_run_id, claim_token: released.append((agent_run_id, claim_token)),
        fetch_agent_run_by_id=lambda agent_run_id: {"id": agent_run_id, "status": "queued"},
        process_agent_run=lambda agent_run: processed.append(agent_run["id"]),
        worker_id="worker-x",
        uuid_module=type("UUIDModule", (), {"uuid4": staticmethod(lambda: type("UUIDValue", (), {"hex": "abc123"})())}),
    )

    assert enqueued == [202]
    assert processed == [202]
    assert released and released[0][0] == 202
    assert audit_calls[0][0] == "agent.mainline_runtime_fanout"
    assert conn.commit_called == 1
    assert conn.closed is True
    assert cursor.closed is True
