from __future__ import annotations

from copy import deepcopy

from fastapi import FastAPI
from fastapi.testclient import TestClient

import session_routes


class SessionRouteCursor:
    def __init__(self, scenario: dict):
        self.scenario = scenario
        self._fetchone = None
        self._fetchall = []

    def execute(self, sql, params=None):
        normalized = " ".join(str(sql).split())

        if "INSERT INTO sessions" in normalized:
            self._fetchone = deepcopy(self.scenario.get("created_session"))
            return

        if "SELECT id, name, description, created_at, updated_at FROM sessions WHERE id =" in normalized:
            session_id = int(params[0])
            session = self.scenario.get("session_row")
            self._fetchone = deepcopy(session) if session and int(session["id"]) == session_id else None
            return

        if "SELECT id, name, description, created_at, updated_at FROM sessions ORDER BY id DESC" in normalized:
            self._fetchall = deepcopy(self.scenario.get("session_rows", []))
            return

        if "SELECT id FROM sessions WHERE id =" in normalized:
            session_id = int(params[0])
            exists = self.scenario.get("session_exists", True)
            self._fetchone = {"id": session_id} if exists else None
            return

        if "SELECT COUNT(*) AS count FROM approvals" in normalized:
            self._fetchone = {"count": self.scenario.get("pending_approvals", 0)}
            return

        if "INSERT INTO session_states" in normalized:
            self._fetchone = deepcopy(self.scenario.get("state_row"))
            return

        if "SELECT session_id, summary_text, preferences, open_loops, created_at, updated_at FROM session_states WHERE session_id =" in normalized:
            self._fetchone = deepcopy(self.scenario.get("state_row"))
            return

        if "SELECT id FROM task_runs WHERE id =" in normalized:
            task_id = params[0]
            if self.scenario.get("source_task_exists", True):
                self._fetchone = {"id": task_id}
            else:
                self._fetchone = None
            return

        if "INSERT INTO session_memories" in normalized:
            self._fetchone = deepcopy(self.scenario.get("memory_row"))
            return

        if "SELECT id, session_id, category, content, importance, source_task_id, created_at, updated_at FROM session_memories" in normalized:
            self._fetchall = deepcopy(self.scenario.get("memory_rows", []))
            return

        if "SELECT DISTINCT s.id FROM sessions s JOIN task_runs t ON t.session_id = s.id" in normalized:
            self._fetchall = deepcopy(self.scenario.get("daily_session_ids", []))
            return

        if "SELECT pg_advisory_xact_lock" in normalized:
            self._fetchone = {"pg_advisory_xact_lock": 1}
            return

        if "SELECT id FROM session_reviews" in normalized and "DATE(created_at) = CURRENT_DATE" in normalized:
            review_map = self.scenario.get("existing_daily_reviews", {})
            session_id = int(params[0])
            existing_id = review_map.get(session_id)
            self._fetchone = {"id": existing_id} if existing_id else None
            return

        if "SELECT id, session_id, review_kind, summary_text, highlights, open_loops, created_at FROM session_reviews" in normalized:
            self._fetchall = deepcopy(self.scenario.get("review_rows", []))
            return

        if "SELECT id, session_id, created_by_actor, user_input, status, result, error_message, current_step, checkpoint_path, created_at, updated_at FROM task_runs" in normalized:
            self._fetchall = deepcopy(self.scenario.get("task_rows", []))
            return

        self._fetchone = None
        self._fetchall = []

    def fetchone(self):
        return deepcopy(self._fetchone)

    def fetchall(self):
        return deepcopy(self._fetchall)

    def close(self):
        return None


class SessionRouteConn:
    def __init__(self, cursor: SessionRouteCursor):
        self._cursor = cursor
        self.commit_called = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commit_called += 1

    def close(self):
        return None


class FakeLogger:
    def __init__(self):
        self.messages = []

    def info(self, message, *args):
        self.messages.append(message % args if args else message)


def build_client(scenario: dict, require_actor_permission=None):
    cursor = SessionRouteCursor(scenario)
    conn = SessionRouteConn(cursor)
    logger = FakeLogger()
    scenario["audit_events"] = []
    scenario["audit_logs"] = []

    app = FastAPI()
    app.include_router(
        session_routes.register_session_routes(
            get_conn=lambda: conn,
            require_actor_permission=require_actor_permission
            or (lambda _cur, actor_name, permission: {
                "actor_name": actor_name or "local_admin",
                "role": "admin",
                "permission": permission,
            }),
            record_audit_event=lambda event_type, actor, task_id, details: scenario["audit_events"].append(
                (event_type, actor, task_id, details)
            ),
            insert_audit_log=lambda _cur, event_type, actor, task_id, details: scenario["audit_logs"].append(
                (event_type, actor, task_id, details)
            ),
            attach_task_display_fields=lambda row: row.update({"display_user_input": row.get("user_input")}) or row,
            serialize_session_row=lambda row: dict(row),
            serialize_session_memory_row=lambda row: dict(row),
            serialize_session_state_row=lambda row: {
                "session_id": row.get("session_id"),
                "summary_text": row.get("summary_text") or "",
                "preferences": row.get("preferences") if isinstance(row.get("preferences"), list) else [],
                "open_loops": row.get("open_loops") if isinstance(row.get("open_loops"), list) else [],
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
            },
            serialize_session_review_row=lambda row: {
                "id": row.get("id"),
                "session_id": row.get("session_id"),
                "review_kind": row.get("review_kind"),
                "summary_text": row.get("summary_text") or "",
                "highlights": row.get("highlights") if isinstance(row.get("highlights"), list) else [],
                "open_loops": row.get("open_loops") if isinstance(row.get("open_loops"), list) else [],
                "created_at": row.get("created_at"),
            },
            compute_session_health=lambda task_rows, memory_rows, session_state_row, review_rows: {
                "active_task_count": len(task_rows),
                "memory_count": len(memory_rows),
                "has_state": bool(session_state_row),
                "review_count": len(review_rows),
            },
            load_session_health_context=lambda _cur, _session_id: (
                deepcopy(scenario["session_row"]),
                deepcopy(scenario.get("summary_task_rows", [])),
                deepcopy(scenario.get("summary_memory_rows", [])),
                deepcopy(scenario.get("summary_state_row")),
                deepcopy(scenario.get("summary_review_rows", [])),
            ),
            refresh_session_review_context=lambda _cur, session_id: (
                {"id": session_id, "name": "Session A", "description": "", "created_at": "now", "updated_at": "now"},
                deepcopy(scenario.get("review_task_rows", [])),
                deepcopy(scenario.get("review_memory_rows", [])),
                deepcopy(scenario.get("review_state_row", {"session_id": session_id, "summary_text": "state"})),
            ),
            build_session_review=lambda _session_row, task_rows, memory_rows, session_state_row, note: {
                "summary_text": f"tasks={len(task_rows)} memories={len(memory_rows)} note={note}",
                "highlights": [session_state_row.get("summary_text") if session_state_row else "", note],
                "open_loops": ["follow up"],
            },
            insert_session_review_row=lambda _cur, session_id, review_kind, built_review: {
                "id": scenario.get("inserted_review_id", 701),
                "session_id": session_id,
                "review_kind": review_kind,
                "summary_text": built_review["summary_text"],
                "highlights": built_review["highlights"],
                "open_loops": built_review["open_loops"],
                "created_at": "2026-03-24T00:00:00+00:00",
            },
            safe_json_dumps=lambda value: value,
            compute_session_state_from_rows=lambda session_row, task_rows, memory_rows: {
                "summary_text": f"{session_row['name']} tasks={len(task_rows)} memories={len(memory_rows)}",
                "preferences": ["pref-a"],
                "open_loops": ["loop-a"],
            },
            upsert_computed_session_state=lambda _cur, session_id, computed_state: {
                "session_id": session_id,
                **computed_state,
                "created_at": "2026-03-24T00:00:00+00:00",
                "updated_at": "2026-03-24T00:00:00+00:00",
            },
            refresh_session_reviews=lambda _cur, **kwargs: scenario.setdefault("refreshed_reviews", []).append(kwargs),
            refresh_session_task_summary_memories=lambda _cur, task_rows: scenario.setdefault("refreshed_memories", []).append(task_rows),
            merge_memory_into_session_state=lambda _cur, session_id, category, content: {
                "session_id": session_id,
                "category": category,
                "content": content,
            },
            logger=logger,
        )
    )
    return TestClient(app), conn, logger


def test_session_routes_create_session_and_record_audit():
    scenario = {
        "created_session": {
            "id": 11,
            "name": "Session A",
            "description": "demo",
            "created_at": "2026-03-24T00:00:00+00:00",
            "updated_at": "2026-03-24T00:00:00+00:00",
        },
    }
    client, conn, logger = build_client(scenario)

    response = client.post("/sessions", headers={"X-Actor-Name": "local_admin"}, json={"name": "Session A", "description": "demo"})

    assert response.status_code == 200
    assert response.json()["name"] == "Session A"
    assert conn.commit_called == 1
    assert scenario["audit_events"][0][0] == "session.create"
    assert "session created" in logger.messages[0]


def test_session_routes_summary_returns_metrics_and_recent_tasks():
    scenario = {
        "session_row": {"id": 21, "name": "Ops", "description": "", "created_at": "now", "updated_at": "now"},
        "summary_task_rows": [
            {"id": 1, "user_input": "task one", "status": "completed", "updated_at": "2026-03-24T01:00:00+00:00"},
            {"id": 2, "user_input": "task two", "status": "failed", "updated_at": "2026-03-24T00:00:00+00:00"},
        ],
        "summary_memory_rows": [
            {"id": 10, "category": "preference", "content": "A"},
            {"id": 11, "category": "open_loop", "content": "B"},
        ],
        "summary_state_row": {"session_id": 21, "summary_text": "state", "preferences": ["A"], "open_loops": ["B"]},
        "summary_review_rows": [{"id": 90}],
        "pending_approvals": 3,
    }
    client, _conn, _logger = build_client(scenario)

    response = client.get("/sessions/21/summary", headers={"X-Actor-Name": "local_admin"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["task_metrics"]["total_tasks"] == 2
    assert payload["approval_metrics"]["pending_approvals"] == 3
    assert payload["recent_tasks"][0]["display_user_input"] == "task one"


def test_session_routes_update_state_persists_and_audits():
    scenario = {
        "session_exists": True,
        "state_row": {
            "session_id": 21,
            "summary_text": "summary",
            "preferences": ["pref-a"],
            "open_loops": ["loop-a"],
            "created_at": "2026-03-24T00:00:00+00:00",
            "updated_at": "2026-03-24T00:00:00+00:00",
        },
    }
    client, conn, logger = build_client(scenario)

    response = client.put(
        "/sessions/21/state",
        headers={"X-Actor-Name": "local_admin"},
        json={"summary_text": "summary", "preferences": ["pref-a"], "open_loops": ["loop-a"]},
    )

    assert response.status_code == 200
    assert response.json()["session_id"] == 21
    assert conn.commit_called == 1
    assert scenario["audit_logs"][0][0] == "session.state_update"
    assert "session state updated" in logger.messages[0]


def test_session_routes_create_memory_updates_state_and_lists_memories():
    scenario = {
        "session_exists": True,
        "source_task_exists": True,
        "memory_row": {
            "id": 501,
            "session_id": 21,
            "category": "preference",
            "content": "以后默认中文",
            "importance": 5,
            "source_task_id": 91,
            "created_at": "2026-03-24T00:00:00+00:00",
            "updated_at": "2026-03-24T00:00:00+00:00",
        },
        "memory_rows": [
            {
                "id": 501,
                "session_id": 21,
                "category": "preference",
                "content": "以后默认中文",
                "importance": 5,
                "source_task_id": 91,
                "created_at": "2026-03-24T00:00:00+00:00",
                "updated_at": "2026-03-24T00:00:00+00:00",
            }
        ],
    }
    client, conn, logger = build_client(scenario)

    create_response = client.post(
        "/sessions/21/memories",
        headers={"X-Actor-Name": "local_admin"},
        json={"category": "preference", "content": "以后默认中文", "importance": 5, "source_task_id": 91},
    )
    list_response = client.get("/sessions/21/memories", headers={"X-Actor-Name": "local_admin"})

    assert create_response.status_code == 200
    assert create_response.json()["content"] == "以后默认中文"
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1
    assert conn.commit_called == 1
    assert scenario["audit_logs"][0][0] == "session.memory_create"
    assert "session memory created" in logger.messages[0]


def test_session_routes_create_review_and_daily_run_share_review_pipeline():
    scenario = {
        "review_task_rows": [{"id": 1, "status": "completed"}],
        "review_memory_rows": [{"id": 2, "category": "fact"}],
        "review_state_row": {"session_id": 21, "summary_text": "state"},
        "inserted_review_id": 801,
        "daily_session_ids": [{"id": 21}, {"id": 22}],
        "existing_daily_reviews": {22: 902},
    }
    client, conn, logger = build_client(scenario)

    create_response = client.post(
        "/sessions/21/reviews",
        headers={"X-Actor-Name": "local_admin"},
        json={"review_kind": "manual", "note": "check"},
    )
    daily_response = client.post(
        "/reviews/daily-run",
        headers={"X-Actor-Name": "local_admin"},
        json={"review_kind": "daily", "note": "cron", "session_limit": 10, "active_within_hours": 24, "force": False},
    )

    assert create_response.status_code == 200
    assert create_response.json()["id"] == 801
    assert daily_response.status_code == 200
    payload = daily_response.json()
    assert payload["created"][0]["session_id"] == 21
    assert payload["skipped"][0]["session_id"] == 22
    assert conn.commit_called == 2
    assert scenario["audit_logs"][0][0] == "session.review_create"
    assert "daily reviews executed" in logger.messages[-1]


def test_session_routes_daily_run_rejects_operator_without_admin_permission():
    scenario = {
        "daily_session_ids": [{"id": 21}],
    }
    client, conn, _logger = build_client(
        scenario,
        require_actor_permission=lambda _cur, actor_name, permission: (
            (_ for _ in ()).throw(session_routes.HTTPException(status_code=403, detail="forbidden"))
            if permission == "admin"
            else {"actor_name": actor_name or "local_operator", "role": "operator", "permission": permission}
        ),
    )

    response = client.post(
        "/reviews/daily-run",
        headers={"X-Actor-Name": "local_operator"},
        json={"review_kind": "daily", "note": "cron", "session_limit": 10, "active_within_hours": 24, "force": False},
    )

    assert response.status_code == 403
    assert conn.commit_called == 0
