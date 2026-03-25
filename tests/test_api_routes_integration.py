from __future__ import annotations

from copy import deepcopy

from fastapi.testclient import TestClient

import api_app_context
import main


class MainFakeCursor:
    def __init__(self):
        self._fetchone = None
        self._fetchall = []

    def execute(self, sql, params=None):
        normalized = " ".join(str(sql).split())
        if "FROM access_actors" in normalized and "ORDER BY actor_name ASC" in normalized and "JOIN access_quotas" not in normalized:
            self._fetchall = [
                {
                    "actor_name": "local_admin",
                    "role": "admin",
                    "description": "Admin",
                    "tenant_key": "default",
                    "permission_overrides": [],
                    "created_at": "2026-03-24T00:00:00+00:00",
                    "updated_at": "2026-03-24T00:00:00+00:00",
                }
            ]
            return
        if "JOIN access_quotas q ON q.actor_name = a.actor_name" in normalized:
            self._fetchall = [
                {
                    "actor_name": "local_admin",
                    "role": "admin",
                    "daily_task_limit": 20,
                    "active_task_limit": 5,
                    "daily_token_limit": 100000,
                    "max_parallel_agents": 8,
                    "daily_task_count": 3,
                    "active_task_count": 1,
                    "daily_token_count": 1200,
                }
            ]
            return
        if "FROM approvals" in normalized and "task_id IN" in normalized:
            self._fetchone = {"count": 2}
            return
        if "FROM change_requests" in normalized and "ORDER BY id DESC" in normalized:
            self._fetchall = [
                {
                    "id": 7,
                    "target_type": "access_quota",
                    "target_key": "local_operator",
                    "status": "pending",
                    "proposal_kind": "manual_change",
                    "requested_by_actor": "local_admin",
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


class MainFakeConn:
    def __init__(self):
        self.cursor_instance = MainFakeCursor()

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        return None

    def close(self):
        return None


def test_access_session_and_change_request_routes(monkeypatch):
    monkeypatch.setattr(main, "get_conn", lambda: MainFakeConn())
    monkeypatch.setattr(api_app_context, "get_conn", lambda: MainFakeConn())
    monkeypatch.setattr(
        main,
        "require_actor_permission",
        lambda _cur, actor_name, permission: {"actor_name": actor_name or "local_admin", "role": "admin", "permission": permission},
    )
    monkeypatch.setattr(
        api_app_context,
        "require_actor_permission",
        lambda _cur, actor_name, permission: {"actor_name": actor_name or "local_admin", "role": "admin", "permission": permission},
    )
    monkeypatch.setattr(main, "seed_default_access_actors", lambda _cur: None)
    monkeypatch.setattr(api_app_context, "seed_default_access_actors", lambda _cur: None)
    monkeypatch.setattr(main, "seed_default_access_quotas", lambda _cur: None)
    monkeypatch.setattr(api_app_context, "seed_default_access_quotas", lambda _cur: None)
    monkeypatch.setattr(main, "ensure_change_requests_table", lambda _cur: None)
    monkeypatch.setattr(api_app_context, "ensure_change_requests_table", lambda _cur: None)
    monkeypatch.setattr(main, "serialize_change_request_list_row", lambda row: row)
    monkeypatch.setattr(api_app_context, "serialize_change_request_list_row", lambda row: row)
    monkeypatch.setattr(main, "serialize_session_row", lambda row: row)
    monkeypatch.setattr(api_app_context, "serialize_session_row", lambda row: row)
    monkeypatch.setattr(main, "attach_task_display_fields", lambda row: row.update({"display_user_input": row.get("user_input", "")}))
    monkeypatch.setattr(api_app_context, "attach_task_display_fields", lambda row: row.update({"display_user_input": row.get("user_input", "")}))
    monkeypatch.setattr(
        main,
        "load_session_health_context",
        lambda _cur, session_id: (
            {"id": session_id, "name": "demo"},
            [
                {"id": 11, "status": "completed", "user_input": "整理发布说明", "updated_at": "2026-03-24T00:00:00+00:00"},
                {"id": 12, "status": "running", "user_input": "检查回滚脚本", "updated_at": "2026-03-24T00:05:00+00:00"},
            ],
            [
                {"category": "preference", "content": "偏好中文"},
                {"category": "task_summary", "content": "发布总结"},
            ],
            {"summary_text": "demo state", "preferences": ["偏好中文"], "open_loops": ["补齐文档"], "updated_at": "2026-03-24T00:06:00+00:00"},
            [{"id": 1, "review_kind": "daily", "created_at": main.datetime.now(main.timezone.utc)}],
        ),
    )
    monkeypatch.setattr(
        api_app_context,
        "load_session_health_context",
        lambda _cur, session_id: (
            {"id": session_id, "name": "demo"},
            [
                {"id": 11, "status": "completed", "user_input": "整理发布说明", "updated_at": "2026-03-24T00:00:00+00:00"},
                {"id": 12, "status": "running", "user_input": "检查回滚脚本", "updated_at": "2026-03-24T00:05:00+00:00"},
            ],
            [
                {"category": "preference", "content": "偏好中文"},
                {"category": "task_summary", "content": "发布总结"},
            ],
            {"summary_text": "demo state", "preferences": ["偏好中文"], "open_loops": ["补齐文档"], "updated_at": "2026-03-24T00:06:00+00:00"},
            [{"id": 1, "review_kind": "daily", "created_at": main.datetime.now(main.timezone.utc)}],
        ),
    )

    client = TestClient(main.app)

    access_response = client.get("/access/actors", headers={"X-Actor-Name": "local_admin"})
    assert access_response.status_code == 200
    assert access_response.json()[0]["actor_name"] == "local_admin"

    quota_response = client.get("/access/quota-usage", headers={"X-Actor-Name": "local_admin"})
    assert quota_response.status_code == 200
    assert quota_response.json()[0]["daily_remaining"] == 17

    session_response = client.get("/sessions/5/summary", headers={"X-Actor-Name": "local_admin"})
    assert session_response.status_code == 200
    session_payload = session_response.json()
    assert session_payload["task_metrics"]["total_tasks"] == 2
    assert session_payload["approval_metrics"]["pending_approvals"] == 2

    change_response = client.get("/change-requests", headers={"X-Actor-Name": "local_admin"})
    assert change_response.status_code == 200
    assert change_response.json()[0]["target_type"] == "access_quota"
