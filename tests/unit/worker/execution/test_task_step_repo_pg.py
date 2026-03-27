from apps.worker.infrastructure.db.task_step_repo_pg import (
    create_legacy_steps,
    create_structured_steps,
    set_step_result,
)


class FakeCursor:
    def __init__(self):
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((" ".join(str(sql).split()), params))


def test_create_structured_steps_persists_runtime_fields():
    cursor = FakeCursor()
    calls = []

    create_structured_steps(
        cursor,
        12,
        [
            {
                "step_order": 2,
                "title": "检索资料",
                "tool": "web_search",
                "input": {"query": "发布回滚 checklist"},
                "run_if": {"operator": "exists"},
                "skip_if": {"operator": "eq"},
                "error_strategy": "continue",
            }
        ],
        ensure_task_steps_columns=lambda _cur: calls.append("ensure_steps"),
        ensure_approvals_table=lambda _cur: calls.append("ensure_approvals"),
        safe_json_dumps=lambda value: f"json:{value}",
        default_max_retries_for_tool=lambda tool_name: 3 if tool_name == "web_search" else 0,
    )

    assert calls == ["ensure_steps", "ensure_approvals"]
    sql, params = cursor.executed[0]
    assert "INSERT INTO task_steps" in sql
    assert params[0] == 12
    assert params[1] == 2
    assert params[3] == "web_search"
    assert params[4] == "json:{'query': '发布回滚 checklist'}"
    assert params[8] == "json:{'operator': 'exists'}"
    assert params[9] == "json:{'operator': 'eq'}"
    assert params[10] == 3
    assert params[11] == "continue"


def test_create_legacy_steps_uses_default_fail_strategy():
    cursor = FakeCursor()

    create_legacy_steps(
        cursor,
        21,
        ["读取文件", "整理结果"],
        ensure_task_steps_columns=lambda _cur: None,
        ensure_approvals_table=lambda _cur: None,
    )

    assert len(cursor.executed) == 2
    assert cursor.executed[0][1][1] == 1
    assert cursor.executed[1][1][1] == 2
    assert cursor.executed[0][1][-1] == "fail"


def test_set_step_result_serializes_input_and_output_payloads():
    cursor = FakeCursor()

    set_step_result(
        cursor,
        55,
        3,
        status="completed",
        tool_name="generate_text",
        input_payload={"prompt": "hello"},
        output_payload="done",
        output_data={"text": "done"},
        error_message="",
        error_strategy="continue",
        safe_json_dumps=lambda value: f"json:{value}",
    )

    sql, params = cursor.executed[0]
    assert "UPDATE task_steps" in sql
    assert params[0] == "completed"
    assert params[2] == "json:{'prompt': 'hello'}"
    assert params[4] == "json:{'text': 'done'}"
    assert params[-2:] == (55, 3)
