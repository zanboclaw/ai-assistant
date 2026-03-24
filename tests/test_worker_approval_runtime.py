from approval_runtime import (
    create_step_approval,
    get_step_approval,
    set_step_waiting_approval,
    should_require_approval,
)


class FakeCursor:
    def __init__(self, *, fetchone_results=None):
        self.fetchone_results = list(fetchone_results or [])
        self.executed = []

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        if self.fetchone_results:
            return self.fetchone_results.pop(0)
        return None


def test_get_step_approval_ensures_table_and_returns_latest_row():
    cursor = FakeCursor(
        fetchone_results=[
            {
                "id": 7,
                "task_id": 21,
                "step_order": 3,
                "step_name": "审批步骤",
                "tool_name": "shell_exec",
                "status": "pending",
            }
        ]
    )
    calls = []

    row = get_step_approval(
        cursor,
        21,
        3,
        ensure_approvals_table=lambda _cur: calls.append("ensure"),
    )

    assert calls == ["ensure"]
    assert row["id"] == 7
    assert "SELECT" in cursor.executed[0][0]
    assert cursor.executed[0][1] == (21, 3)


def test_create_step_approval_persists_step_name_and_payload():
    cursor = FakeCursor()
    calls = []

    create_step_approval(
        cursor,
        9,
        2,
        "写入文档",
        "file_write",
        {"path": "docs/readme.md"},
        "需要人工审批",
        ensure_approvals_table=lambda _cur: calls.append("ensure"),
        safe_json_dumps=lambda value: f"json:{value['path']}",
    )

    assert calls == ["ensure"]
    query, params = cursor.executed[0]
    assert "INSERT INTO approvals" in query
    assert params == (9, 2, "写入文档", "file_write", "json:docs/readme.md", "需要人工审批")


def test_set_step_waiting_approval_marks_result_as_blocked():
    calls = []

    set_step_waiting_approval(
        object(),
        11,
        4,
        "http_request",
        {"url": "https://example.com"},
        "外部请求需要审批",
        set_step_result=lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    _, kwargs = calls[0]
    assert kwargs["status"] == "waiting_approval"
    assert kwargs["error_strategy"] == "fail"
    assert kwargs["output_data"]["approval_required"] is True


def test_should_require_approval_respects_registry_override():
    required, reason = should_require_approval(
        "custom_tool",
        {},
        load_risk_policy_settings=lambda: {},
        get_tool_registry_entry=lambda _tool_name: {"approval_required": True, "provider_type": "remote"},
        low_risk_write_extensions={".md"},
        sensitive_write_extensions={".sh"},
        sensitive_write_basenames={"docker-compose.yml"},
    )

    assert required is True
    assert "approval_required=true" in reason
    assert "provider_type=remote" in reason


def test_should_require_approval_allows_low_risk_new_markdown_write(tmp_path):
    target = tmp_path / "notes.md"

    required, reason = should_require_approval(
        "file_write",
        {"path": str(target)},
        load_risk_policy_settings=lambda: {},
        get_tool_registry_entry=lambda _tool_name: None,
        low_risk_write_extensions={".md", ".txt"},
        sensitive_write_extensions={".sh", ".env"},
        sensitive_write_basenames={"docker-compose.yml"},
    )

    assert required is False
    assert reason == ""


def test_should_require_approval_blocks_existing_file_overwrite(tmp_path):
    target = tmp_path / "notes.md"
    target.write_text("existing", encoding="utf-8")

    required, reason = should_require_approval(
        "file_write",
        {"path": str(target)},
        load_risk_policy_settings=lambda: {},
        get_tool_registry_entry=lambda _tool_name: None,
        low_risk_write_extensions={".md"},
        sensitive_write_extensions={".sh"},
        sensitive_write_basenames={"docker-compose.yml"},
    )

    assert required is True
    assert "覆盖现有文件" in reason


def test_should_require_approval_blocks_non_get_http_request():
    required, reason = should_require_approval(
        "http_request",
        {"method": "POST", "url": "https://api.example.com/items"},
        load_risk_policy_settings=lambda: {},
        get_tool_registry_entry=lambda _tool_name: None,
        low_risk_write_extensions={".md"},
        sensitive_write_extensions={".sh"},
        sensitive_write_basenames={"docker-compose.yml"},
    )

    assert required is True
    assert "POST" in reason


def test_should_require_approval_blocks_sensitive_http_hostname():
    required, reason = should_require_approval(
        "http_request",
        {"method": "GET", "url": "https://internal.service.local/path"},
        load_risk_policy_settings=lambda: {},
        get_tool_registry_entry=lambda _tool_name: None,
        low_risk_write_extensions={".md"},
        sensitive_write_extensions={".sh"},
        sensitive_write_basenames={"docker-compose.yml"},
    )

    assert required is True
    assert "service.local" in reason


def test_should_require_approval_always_blocks_shell_exec():
    required, reason = should_require_approval(
        "shell_exec",
        {"command": "git status"},
        load_risk_policy_settings=lambda: {},
        get_tool_registry_entry=lambda _tool_name: None,
        low_risk_write_extensions={".md"},
        sensitive_write_extensions={".sh"},
        sensitive_write_basenames={"docker-compose.yml"},
    )

    assert required is True
    assert "git status" in reason
