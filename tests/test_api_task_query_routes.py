from __future__ import annotations

import json
from copy import deepcopy

from fastapi import FastAPI
from fastapi.testclient import TestClient

import task_query_routes


class TaskQueryFakeCursor:
    def __init__(self, checkpoint_path: str):
        self.checkpoint_path = checkpoint_path
        self._fetchone = None
        self._fetchall = []

    def execute(self, sql, params=None):
        normalized = " ".join(str(sql).split())

        if "FROM task_runs WHERE id =" in normalized and "task_intent_json" in normalized:
            task_id = int(params[0])
            if task_id != 88:
                self._fetchone = None
                return
            self._fetchone = {
                "id": 88,
                "session_id": 12,
                "created_by_actor": "local_admin",
                "user_input": "整理发布回滚方案",
                "status": "completed",
                "result": "已生成方案",
                "error_message": "",
                "current_step": 3,
                "checkpoint_path": self.checkpoint_path,
                "runtime_overrides": json.dumps({"skill_invocation": {"skill_id": "demo_skill"}}),
                "task_intent_json": json.dumps({"task_type": "research"}),
                "deliverable_spec_json": json.dumps({"deliverable_type": "research_summary"}),
                "validation_report_json": json.dumps({"passed": True}),
                "recovery_action_json": json.dumps({"action": "none"}),
                "created_at": "2026-03-24T00:00:00+00:00",
                "updated_at": "2026-03-24T00:05:00+00:00",
            }
            return

        if "SELECT id FROM task_runs WHERE id =" in normalized:
            task_id = int(params[0])
            self._fetchone = {"id": task_id} if task_id == 88 else None
            return

        if "FROM task_runs WHERE id =" in normalized and "checkpoint_path" in normalized and "task_intent_json" not in normalized:
            task_id = int(params[0])
            if task_id != 88:
                self._fetchone = None
                return
            self._fetchone = {
                "id": 88,
                "session_id": 12,
                "created_by_actor": "local_admin",
                "user_input": "整理发布回滚方案",
                "status": "completed",
                "result": "已生成方案",
                "error_message": "",
                "current_step": 3,
                "checkpoint_path": self.checkpoint_path,
                "runtime_overrides": json.dumps({"skill_invocation": {"skill_id": "demo_skill"}}),
                "created_at": "2026-03-24T00:00:00+00:00",
                "updated_at": "2026-03-24T00:05:00+00:00",
            }
            return

        if "FROM task_steps WHERE task_id =" in normalized and "ORDER BY step_order ASC" in normalized:
            self._fetchall = [
                {
                    "id": 501,
                    "task_id": 88,
                    "step_order": 1,
                    "step_name": "调研参考信息",
                    "tool_name": "web_search",
                    "status": "completed",
                    "input_payload": json.dumps({"query": "发布 回滚"}),
                    "output_payload": "搜索完成",
                    "output_data": json.dumps({"query": "发布 回滚"}),
                    "error_message": "",
                    "run_if": None,
                    "skip_if": None,
                    "retry_count": 0,
                    "max_retries": 1,
                    "error_strategy": "fail",
                    "created_at": "2026-03-24T00:00:00+00:00",
                    "updated_at": "2026-03-24T00:01:00+00:00",
                },
                {
                    "id": 502,
                    "task_id": 88,
                    "step_order": 2,
                    "step_name": "生成交付",
                    "tool_name": "generate_text",
                    "status": "completed",
                    "input_payload": json.dumps({"prompt": "生成最终方案"}),
                    "output_payload": "结果完成",
                    "output_data": json.dumps({"text": "最终方案"}),
                    "error_message": "",
                    "run_if": None,
                    "skip_if": None,
                    "retry_count": 0,
                    "max_retries": 1,
                    "error_strategy": "fail",
                    "created_at": "2026-03-24T00:01:00+00:00",
                    "updated_at": "2026-03-24T00:02:00+00:00",
                },
            ]
            return

        if "FROM task_steps WHERE id =" in normalized and "task_id =" in normalized:
            step_id = int(params[0])
            task_id = int(params[1])
            self._fetchone = (
                {
                    "id": 501,
                    "task_id": task_id,
                    "step_order": 1,
                    "step_name": "调研参考信息",
                    "tool_name": "web_search",
                    "status": "completed",
                }
                if task_id == 88 and step_id == 501
                else None
            )
            return

        if "FROM task_traces" in normalized and "LIMIT 1" in normalized:
            self._fetchone = {"id": 901, "task_run_id": 88, "plan_source": "deliverable_policy"}
            return

        if "FROM step_traces" in normalized and "task_step_id =" in normalized:
            self._fetchall = [{"id": 1001, "task_run_id": 88, "task_step_id": 501, "step_order": 1}]
            return

        if "FROM step_traces" in normalized:
            self._fetchall = [{"id": 1001, "task_run_id": 88, "task_step_id": 501, "step_order": 1}]
            return

        if "FROM model_traces" in normalized and "task_step_id =" in normalized:
            self._fetchall = [{"id": 1101, "task_run_id": 88, "task_step_id": 501}]
            return

        if "FROM model_traces" in normalized:
            self._fetchall = [{"id": 1101, "task_run_id": 88, "task_step_id": 501}]
            return

        if "FROM tool_traces" in normalized and "task_step_id =" in normalized:
            self._fetchall = [{"id": 1201, "task_run_id": 88, "task_step_id": 501}]
            return

        if "FROM tool_traces" in normalized:
            self._fetchall = [{"id": 1201, "task_run_id": 88, "task_step_id": 501}]
            return

        if "FROM skill_traces" in normalized and "task_step_id =" in normalized:
            self._fetchall = [{"id": 1301, "task_run_id": 88, "task_step_id": 501}]
            return

        if "FROM skill_traces" in normalized:
            self._fetchall = [{"id": 1301, "task_run_id": 88, "task_step_id": 501}]
            return

        if "FROM retrieval_traces" in normalized and "task_step_id =" in normalized:
            self._fetchall = [{"id": 1401, "task_run_id": 88, "task_step_id": 501}]
            return

        if "FROM retrieval_traces" in normalized:
            self._fetchall = [{"id": 1401, "task_run_id": 88, "task_step_id": 501}]
            return

        if "FROM approvals WHERE task_id =" in normalized:
            self._fetchall = [
                {
                    "id": 1501,
                    "task_id": 88,
                    "step_order": 2,
                    "step_name": "生成交付",
                    "tool_name": "generate_text",
                    "input_payload": json.dumps({"prompt": "生成最终方案"}),
                    "reason": "需要人工确认",
                    "status": "approved",
                    "decision_note": "ok",
                    "created_at": "2026-03-24T00:01:00+00:00",
                    "updated_at": "2026-03-24T00:02:00+00:00",
                    "decided_at": "2026-03-24T00:02:30+00:00",
                }
            ]
            return

        self._fetchone = None
        self._fetchall = []

    def fetchone(self):
        return deepcopy(self._fetchone)

    def fetchall(self):
        return deepcopy(self._fetchall)

    def close(self):
        return None


class TaskQueryFakeConn:
    def __init__(self, cursor: TaskQueryFakeCursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def close(self):
        return None


def build_test_client(tmp_path):
    checkpoint_path = tmp_path / "task_88_checkpoint.json"
    checkpoint_path.write_text(json.dumps({"task_id": 88, "status": "completed"}, ensure_ascii=False), encoding="utf-8")
    cursor = TaskQueryFakeCursor(str(checkpoint_path))

    app = FastAPI()
    app.include_router(
        task_query_routes.register_task_query_routes(
            get_conn=lambda: TaskQueryFakeConn(cursor),
            require_actor_permission=lambda _cur, actor_name, permission: {
                "actor_name": actor_name or "local_admin",
                "role": "admin",
                "permission": permission,
            },
            ensure_agent_tables=lambda _cur: None,
            ensure_evaluator_tables=lambda _cur: None,
            ensure_trace_tables=lambda _cur: None,
            attach_task_display_fields=lambda row: row.update({"display_user_input": row.get("user_input"), "result_excerpt": "已生成方案"}) or row,
            parse_maybe_json=lambda value: json.loads(value) if isinstance(value, str) else value,
            fetch_latest_evaluator_for_task=lambda _cur, task_id: {"task_id": task_id, "workflow_proposal": {"action_key": "noop"}},
            fetch_task_agent_summary=lambda _cur, task_id: {"task_id": task_id, "recommended_action": "none"},
        )
    )
    return TestClient(app)


def test_task_query_routes_cover_task_detail_steps_traces_replay_and_checkpoint(tmp_path):
    client = build_test_client(tmp_path)

    task_response = client.get("/tasks/88", headers={"X-Actor-Name": "local_admin"})
    assert task_response.status_code == 200
    task_payload = task_response.json()
    assert task_payload["display_user_input"] == "整理发布回滚方案"
    assert task_payload["stage5"]["recommended_action"] == "none"
    assert task_payload["latest_workflow_proposal"]["action_key"] == "noop"

    steps_response = client.get("/tasks/88/steps", headers={"X-Actor-Name": "local_admin"})
    assert steps_response.status_code == 200
    assert len(steps_response.json()) == 2

    traces_response = client.get("/tasks/88/traces", headers={"X-Actor-Name": "local_admin"})
    assert traces_response.status_code == 200
    traces_payload = traces_response.json()
    assert traces_payload["task_trace"]["plan_source"] == "deliverable_policy"
    assert len(traces_payload["step_traces"]) == 1

    replay_response = client.get("/tasks/88/replay", headers={"X-Actor-Name": "local_admin"})
    assert replay_response.status_code == 200
    replay_payload = replay_response.json()
    assert replay_payload["summary"]["step_count"] == 2
    assert replay_payload["steps"][0]["trace_counts"]["model"] == 1
    assert replay_payload["steps"][0]["replay_hints"]["uses_skill"] is True

    step_trace_response = client.get("/tasks/88/steps/501/traces", headers={"X-Actor-Name": "local_admin"})
    assert step_trace_response.status_code == 200
    assert step_trace_response.json()["step"]["tool_name"] == "web_search"

    checkpoint_response = client.get("/tasks/88/checkpoint", headers={"X-Actor-Name": "local_admin"})
    assert checkpoint_response.status_code == 200
    assert checkpoint_response.json()["task_id"] == 88
