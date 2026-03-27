import json

from apps.worker.runtime.execution.checkpoint import (
    build_checkpoint_payload,
    checkpoint_file_for_task,
    write_checkpoint,
)


def test_build_checkpoint_payload_preserves_state():
    payload = build_checkpoint_payload(status="running", current_step=2, error="")

    assert payload == {"status": "running", "current_step": 2, "error": ""}


def test_build_checkpoint_payload_can_include_runtime_snapshot():
    payload = build_checkpoint_payload(
        task_id=7,
        user_input="整理发布说明",
        status="running",
        current_step=3,
        error="",
        step_context={3: {"output_payload": "done"}},
        var_context={"region": "cn"},
        step_outputs=["done"],
        updated_at="2026-03-26T00:00:00+00:00",
    )

    assert payload["task_id"] == 7
    assert payload["user_input"] == "整理发布说明"
    assert payload["step_context"][3]["output_payload"] == "done"
    assert payload["var_context"] == {"region": "cn"}
    assert payload["step_outputs"] == ["done"]
    assert payload["updated_at"] == "2026-03-26T00:00:00+00:00"


def test_checkpoint_file_for_task_uses_checkpoint_dir(tmp_path):
    path = checkpoint_file_for_task(18, checkpoint_dir=tmp_path)

    assert path == tmp_path / "task_18.json"


def test_write_checkpoint_persists_snapshot_and_updates_task_progress(tmp_path):
    calls = []

    class DummyCursor:
        pass

    path_str = write_checkpoint(
        DummyCursor(),
        11,
        "继续补测试",
        "running",
        2,
        {2: {"output_payload": "ok"}},
        {"branch": "main"},
        ["ok"],
        "",
        checkpoint_dir=tmp_path,
        update_task_progress=lambda _cur, task_id, **kwargs: calls.append((task_id, kwargs)),
    )

    payload = json.loads((tmp_path / "task_11.json").read_text(encoding="utf-8"))
    assert path_str == str(tmp_path / "task_11.json")
    assert payload["task_id"] == 11
    assert payload["step_outputs"] == ["ok"]
    assert calls == [(11, {"current_step": 2, "checkpoint_path": str(tmp_path / "task_11.json")})]
