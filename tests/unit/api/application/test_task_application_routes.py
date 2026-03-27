from __future__ import annotations

from copy import deepcopy

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from apps.api.routes.intake_routes import register_intake_routes
from apps.api.routes.task_routes import register_task_routes


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
        if "SELECT skill_id, latest_version FROM skills" in normalized:
            self._fetchone = {"skill_id": "workspace_file_summary", "latest_version": "1.0.0"}
            return
        if "INSERT INTO task_runs" in normalized:
            row = {
                "id": 301 + len(self.inserted_tasks),
                "session_id": params[1],
                "user_input": params[0],
                "created_by_actor": params[2],
                "status": "pending",
                "runtime_overrides": params[3].adapted if params[3] is not None else {},
                "task_intent_json": params[4].adapted,
                "deliverable_spec_json": params[5].adapted,
                "validation_report_json": {},
                "recovery_action_json": {},
                "created_at": "2026-03-26T00:00:00+00:00",
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
        self.commits = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commits += 1

    def close(self):
        return None


def build_container():
    cursor = FakeCursor()
    conn = FakeConn(cursor)
    audit_logs: list[tuple] = []
    enqueued: list[int] = []

    container = {
        "get_conn": lambda: conn,
        "ensure_skill_registry_tables": lambda _cur: None,
        "attach_task_display_fields": lambda row: row.update({"display_user_input": row.get("user_input")}),
        "insert_audit_log": lambda _cur, event_type, actor, task_id, details: audit_logs.append(
            (event_type, actor, task_id, details)
        ),
        "enqueue_task": lambda task_id: enqueued.append(task_id),
        "fetch_task_agent_summary": lambda _cur, task_id: {"task_id": task_id, "recommended_action": "finalize"},
        "build_memory_context": lambda _cur, user_input: {
            "retrieval_query": user_input,
            "retrieved_memories": [{"id": 1, "title": "memory"}],
        },
        "infer_task_intent": lambda user_input, skill_id=None: {
            "task_type": "question_answer" if "如何" in user_input else "research",
            "goal_summary": user_input[:80],
            "needs_clarification": False,
            "skill_id": skill_id or "",
        },
        "infer_deliverable_spec": lambda user_input, _task_intent: {
            "deliverable_type": "direct_answer" if "如何" in user_input else "research_summary",
            "acceptance_hints": ["包含结论"],
            "clarify": {"blocking": False, "questions": []},
        },
        "analyze_input": lambda _cur, user_input, session_id=None, skill_id=None: {
            "route_mode": "fast_path" if "如何" in user_input else "draft_task",
            "route_reason": "mock",
            "confirmation_required": True,
            "task_intent": {"task_type": "question_answer"},
            "deliverable_spec": {"deliverable_type": "direct_answer"},
            "draft_preview": {
                "goal_summary": user_input[:80],
                "task_type": "question_answer",
                "deliverable_type": "direct_answer",
                "session_id": session_id,
                "skill_id": skill_id or "",
                "needs_clarification": False,
                "clarification_questions": [],
                "acceptance_hints": ["包含结论"],
            },
            "memory_context": {"retrieval_query": user_input, "retrieved_memories": [], "retrieved_count": 0},
        },
        "fast_path_chat": lambda _cur, user_input, actor_name="": {
            "mode": "fast_path",
            "answer": f"fast-path:{user_input}:{actor_name}",
        },
        "search_memory": lambda _cur, query, memory_kind=None, limit=5: [
            {"id": 1, "memory_kind": memory_kind or "task_memory", "title": f"memory {query}"}
        ][:limit],
        "build_task_display_user_input": lambda user_input, _overrides=None: user_input,
        "make_json_compatible": lambda value: value,
        "parse_maybe_json": lambda value: value,
        "register_task_query_routes": lambda **_kwargs: APIRouter(),
        "register_task_control_routes": lambda **_kwargs: APIRouter(),
        "require_actor_permission": lambda _cur, actor_name, permission: {
            "actor_name": actor_name or "local_admin",
            "role": "admin",
            "permission": permission,
        },
        "enforce_task_quota": lambda _cur, _actor_name: {"daily_remaining": 10},
        "ensure_agent_tables": lambda _cur: None,
        "ensure_evaluator_tables": lambda _cur: None,
        "ensure_trace_tables": lambda _cur: None,
        "fetch_latest_evaluator_for_task": lambda _cur, _task_id: None,
        "get_task_or_404": lambda _cur, _task_id: None,
        "update_checkpoint_status": lambda *_args, **_kwargs: None,
        "resolve_resume_from_step": lambda _cur, _task_id, from_step: int(from_step or 1),
        "reset_task_for_resume": lambda *_args, **_kwargs: None,
        "reset_task_for_clarification": lambda *_args, **_kwargs: None,
        "extract_task_clarification_state": lambda *_args, **_kwargs: ("", []),
        "build_clarified_user_input": lambda original_input, _history: original_input,
        "logger": type("Logger", (), {"info": lambda self, *_args, **_kwargs: None})(),
    }
    return container, cursor, conn, enqueued, audit_logs


def test_refactor_routes_confirm_then_list_tasks():
    container, cursor, conn, enqueued, audit_logs = build_container()
    app = FastAPI()
    register_intake_routes(app=app, container=container)
    register_task_routes(app=app, container=container)
    client = TestClient(app)

    confirm_response = client.post(
        "/intake/confirm",
        headers={"X-Actor-Name": "local_admin"},
        json={"user_input": "整理发布窗口说明", "session_id": 9, "route": "draft_task"},
    )
    assert confirm_response.status_code == 200
    assert confirm_response.json()["display_user_input"] == "整理发布窗口说明"
    assert conn.commits == 1
    assert enqueued == [301]
    assert audit_logs[0][0] == "task.create"
    assert cursor.inserted_tasks

    list_response = client.get("/tasks", headers={"X-Actor-Name": "local_admin"})
    assert list_response.status_code == 200
    assert list_response.json()[0]["display_user_input"] == "整理发布窗口说明"


def test_refactor_routes_route_fast_path_and_create_task():
    container, _cursor, conn, enqueued, _audit_logs = build_container()
    app = FastAPI()
    register_intake_routes(app=app, container=container)
    register_task_routes(app=app, container=container)
    client = TestClient(app)

    route_response = client.post(
        "/intake/route",
        headers={"X-Actor-Name": "local_admin"},
        json={"user_input": "如何整理发布回滚 checklist？"},
    )
    assert route_response.status_code == 200
    assert route_response.json()["route_mode"] == "fast_path"

    fast_path_response = client.post(
        "/chat/fast-path",
        headers={"X-Actor-Name": "local_admin"},
        json={"user_input": "如何整理发布回滚 checklist？"},
    )
    assert fast_path_response.status_code == 200
    assert fast_path_response.json()["mode"] == "fast_path"

    create_response = client.post(
        "/tasks",
        headers={"X-Actor-Name": "local_admin"},
        json={"user_input": "整理变更说明", "session_id": 9},
    )
    assert create_response.status_code == 200
    assert create_response.json()["display_user_input"] == "整理变更说明"
    assert conn.commits == 1
    assert enqueued == [301]
