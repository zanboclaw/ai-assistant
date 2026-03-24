from __future__ import annotations

import json
from copy import deepcopy

from fastapi import FastAPI
from fastapi.testclient import TestClient

import skill_routes


class SkillCursor:
    def __init__(self, scenario: dict):
        self.scenario = scenario
        self._fetchone = None
        self._fetchall = []

    def execute(self, sql, params=None):
        normalized = " ".join(str(sql).split())

        if "FROM skills ORDER BY skill_id ASC" in normalized:
            self._fetchall = deepcopy(self.scenario.get("skill_rows", []))
            return

        if "FROM skills WHERE skill_id =" in normalized:
            skill_id = params[0]
            row = self.scenario.get("skill_row")
            self._fetchone = deepcopy(row) if row and row.get("skill_id") == skill_id else None
            return

        if "FROM skill_versions WHERE skill_id =" in normalized:
            self._fetchone = deepcopy(self.scenario.get("skill_version_row"))
            return

        self._fetchone = None
        self._fetchall = []

    def fetchone(self):
        return deepcopy(self._fetchone)

    def fetchall(self):
        return deepcopy(self._fetchall)

    def close(self):
        return None


class SkillConn:
    def __init__(self, cursor: SkillCursor):
        self._cursor = cursor
        self.commit_called = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commit_called += 1

    def close(self):
        return None


def build_client(scenario: dict):
    cursor = SkillCursor(scenario)
    conn = SkillConn(cursor)
    scenario["audit_logs"] = []

    app = FastAPI()
    app.include_router(
        skill_routes.register_skill_routes(
            get_conn=lambda: conn,
            require_actor_permission=lambda _cur, actor_name, permission: {
                "actor_name": actor_name or "local_admin",
                "role": "admin",
                "permission": permission,
            },
            ensure_skill_registry_tables=lambda _cur: None,
            read_skill_package_from_source=lambda source_path: json.loads(scenario["package_source_map"][source_path]),
            serialize_skill_row=lambda row: dict(row),
            serialize_skill_version_row=lambda row: dict(row),
            insert_audit_log=lambda _cur, event_type, actor, task_id, details: scenario["audit_logs"].append(
                (event_type, actor, task_id, details)
            ),
            json_wrapper=lambda value: value,
        )
    )
    return TestClient(app), conn


def test_skill_routes_list_and_get_skill():
    scenario = {
        "skill_rows": [
            {
                "skill_id": "demo_skill",
                "display_name": "Demo Skill",
                "description": "desc",
                "status": "active",
                "latest_version": "1.0.0",
                "entrypoint_kind": "structured_steps",
            }
        ],
        "skill_row": {
            "skill_id": "demo_skill",
            "display_name": "Demo Skill",
            "description": "desc",
            "status": "active",
            "latest_version": "1.0.0",
            "entrypoint_kind": "structured_steps",
        },
        "skill_version_row": {
            "skill_id": "demo_skill",
            "version": "1.0.0",
            "package_format": "json",
            "package_source": "/tmp/demo-skill.json",
            "description": "desc",
            "package_body": {"name": "demo"},
        },
        "package_source_map": {},
    }
    client, conn = build_client(scenario)

    list_response = client.get("/skills", headers={"X-Actor-Name": "local_admin"})
    get_response = client.get("/skills/demo_skill", headers={"X-Actor-Name": "local_admin"})

    assert list_response.status_code == 200
    assert get_response.status_code == 200
    assert list_response.json()[0]["skill_id"] == "demo_skill"
    assert get_response.json()["version"]["version"] == "1.0.0"
    assert conn.commit_called == 1


def test_skill_routes_import_skill_persists_version_and_audits(tmp_path):
    package_path = tmp_path / "demo_skill.json"
    package_payload = {
        "skill_id": "demo_skill",
        "display_name": "Demo Skill",
        "description": "desc",
        "version": "1.0.1",
        "entrypoint_kind": "structured_steps",
        "package_format": "json",
        "package_source": str(package_path),
        "package_body": {"steps": []},
    }
    package_path.write_text(json.dumps(package_payload), encoding="utf-8")
    scenario = {
        "skill_row": {
            "skill_id": "demo_skill",
            "display_name": "Demo Skill",
            "description": "desc",
            "status": "active",
            "latest_version": "1.0.1",
            "entrypoint_kind": "structured_steps",
        },
        "skill_version_row": {
            "skill_id": "demo_skill",
            "version": "1.0.1",
            "package_format": "json",
            "package_source": str(package_path),
            "description": "desc",
            "package_body": {"steps": []},
        },
        "package_source_map": {str(package_path): json.dumps(package_payload)},
    }
    client, conn = build_client(scenario)

    response = client.post(
        "/skills/import",
        headers={"X-Actor-Name": "local_admin"},
        json={"source_path": str(package_path), "activate": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["skill"]["latest_version"] == "1.0.1"
    assert payload["version"]["package_source"] == str(package_path)
    assert conn.commit_called == 1
    assert scenario["audit_logs"][0][0] == "skill.import"
