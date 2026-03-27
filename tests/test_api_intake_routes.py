from __future__ import annotations

from copy import deepcopy

from fastapi import FastAPI
from fastapi.testclient import TestClient

import intake_task_routes


class FakeCursor:
    def __init__(self):
        self.inserted_tasks: list[dict] = []
        self._fetchone = None
        self._fetchall = []

    def execute(self, sql, params=None):
        normalized = " ".join(str(sql).split())
        if "SELECT id FROM sessions" in normalized:
            session_id = params[0]
            self._fetchone = {"id": session_id} if session_id == 9 else None
            return
        if "SELECT skill_id FROM skills" in normalized and "latest_version" not in normalized:
            self._fetchone = {"skill_id": "workspace_file_summary"}
            return
        if "SELECT skill_id, latest_version FROM skills" in normalized:
            self._fetchone = {"skill_id": "workspace_file_summary", "latest_version": "1.0.0"}
            return
        if "INSERT INTO task_runs" in normalized:
            user_input = params[0]
            session_id = params[1]
            actor_name = params[2]
            row = {
                "id": 101 + len(self.inserted_tasks),
                "session_id": session_id,
                "user_input": user_input,
                "created_by_actor": actor_name,
                "status": "pending",
                "runtime_overrides": params[3].adapted if params[3] is not None else {},
                "task_intent_json": params[4].adapted,
                "deliverable_spec_json": params[5].adapted,
                "validation_report_json": {},
                "recovery_action_json": {},
                "created_at": "2026-03-24T00:00:00+00:00",
            }
            self.inserted_tasks.append(deepcopy(row))
            self._fetchone = row
            return
        if "FROM task_runs" in normalized and "ORDER BY id DESC" in normalized:
            self._fetchall = [deepcopy(row) for row in reversed(self.inserted_tasks)]
            return
        self._fetchone = None
        self._fetchall = []

    def fetchone(self):
        return deepcopy(self._fetchone)

    def fetchall(self):
        return deepcopy(self._fetchall)

    def close(self):
        return None


class FakeConn:
    def __init__(self, cursor: FakeCursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def commit(self):
        return None

    def close(self):
        return None


def build_test_client(monkeypatch):
    cursor = FakeCursor()

    monkeypatch.setattr(
        intake_task_routes,
        "require_actor_permission",
        lambda _cur, actor_name, permission: {"actor_name": actor_name or "local_admin", "role": "admin", "permission": permission},
    )
    monkeypatch.setattr(intake_task_routes, "enforce_task_quota", lambda _cur, _actor_name: {"daily_remaining": 10})
    monkeypatch.setattr(
        intake_task_routes,
        "infer_task_intent",
        lambda user_input, skill_id=None: {
            "task_type": "question_answer" if "如何" in user_input else "research",
            "goal_summary": user_input[:80],
            "needs_clarification": False,
            "skill_id": skill_id or "",
        },
    )
    monkeypatch.setattr(
        intake_task_routes,
        "infer_deliverable_spec",
        lambda user_input, _task_intent: {
            "deliverable_type": "direct_answer" if "如何" in user_input else "research_summary",
            "acceptance_hints": ["包含结论", "给出下一步"],
            "clarify": {"blocking": False, "questions": []},
        },
    )
    monkeypatch.setattr(
        intake_task_routes,
        "build_fast_path_response",
        lambda _cur, user_input, actor_name="", limit=3: {
            "mode": "fast_path",
            "answer": f"fast-path:{user_input}:{actor_name}:{limit}",
            "memory_context": {"retrieved_memories": [], "retrieved_count": 0, "retrieval_query": user_input},
            "promote_to_task": {"recommended": True, "reason": "upgrade"},
        },
    )
    monkeypatch.setattr(
        intake_task_routes,
        "search_long_term_memories",
        lambda _cur, query, memory_kind=None, limit=5, actor_name=None, source_session_id=None: [
            {
                "id": 1,
                "memory_kind": memory_kind or "task_memory",
                "title": f"memory for {query}",
                "content": "historical context",
                "metadata": {"matched_keywords": ["query"], "match_explanation": "hit"},
            }
        ][:limit],
    )
    monkeypatch.setattr(intake_task_routes, "ensure_long_term_memory_table", lambda _cur: None)

    app = FastAPI()
    app.include_router(
        intake_task_routes.register_intake_task_routes(
            ensure_skill_registry_tables=lambda _cur: None,
            get_conn=lambda: FakeConn(cursor),
            attach_task_display_fields=lambda row: row.update({"display_user_input": row.get("user_input")}),
            insert_audit_log=lambda *args, **kwargs: None,
            enqueue_task=lambda _task_id: None,
            fetch_task_agent_summary=lambda _cur, task_id: {"task_id": task_id, "recommended_action": "finalize"},
        )
    )
    return TestClient(app), cursor


def test_route_and_fast_path_chat(monkeypatch):
    client, _cursor = build_test_client(monkeypatch)

    response = client.post("/intake/route", headers={"X-Actor-Name": "local_admin"}, json={"user_input": "如何整理发布回滚 checklist？"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["route_mode"] == "fast_path"
    assert payload["memory_context"]["retrieved_count"] == 1

    fast_path_response = client.post("/chat/fast-path", headers={"X-Actor-Name": "local_admin"}, json={"user_input": "如何整理发布回滚 checklist？"})
    assert fast_path_response.status_code == 200
    assert fast_path_response.json()["answer"].startswith("fast-path:")


def test_confirm_and_list_tasks(monkeypatch):
    client, cursor = build_test_client(monkeypatch)

    confirm_response = client.post(
        "/intake/confirm",
        headers={"X-Actor-Name": "local_admin"},
        json={"user_input": "整理发布窗口说明", "session_id": 9, "route": "draft_task"},
    )
    assert confirm_response.status_code == 200
    created = confirm_response.json()
    assert created["display_user_input"] == "整理发布窗口说明"
    assert cursor.inserted_tasks

    list_response = client.get("/tasks", headers={"X-Actor-Name": "local_admin"})
    assert list_response.status_code == 200
    rows = list_response.json()
    assert rows[0]["display_user_input"] == "整理发布窗口说明"

    memory_response = client.get("/memories/search?query=发布", headers={"X-Actor-Name": "local_admin"})
    assert memory_response.status_code == 200
    assert memory_response.json()[0]["metadata"]["match_explanation"] == "hit"
