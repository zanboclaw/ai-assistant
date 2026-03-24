from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Header, HTTPException

from schemas import SkillImportRequest


def register_skill_routes(
    *,
    get_conn: Callable[[], Any],
    require_actor_permission: Callable[[Any, str | None, str], dict[str, Any]],
    ensure_skill_registry_tables: Callable[[Any], None],
    read_skill_package_from_source: Callable[[str], dict[str, Any]],
    serialize_skill_row: Callable[[dict[str, Any]], dict[str, Any]],
    serialize_skill_version_row: Callable[[dict[str, Any]], dict[str, Any]],
    insert_audit_log: Callable[[Any, str, str, int | None, Any | None], None],
    json_wrapper: Callable[[Any], Any],
):
    router = APIRouter()

    @router.get("/skills")
    def list_skills(x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
        conn = get_conn()
        cur = conn.cursor()
        require_actor_permission(cur, x_actor_name, "read")
        ensure_skill_registry_tables(cur)
        conn.commit()
        cur.execute(
            """
            SELECT skill_id, display_name, description, status, latest_version, entrypoint_kind, created_at, updated_at
            FROM skills
            ORDER BY skill_id ASC;
            """
        )
        rows = [serialize_skill_row(row) for row in cur.fetchall()]
        cur.close()
        conn.close()
        return rows

    @router.get("/skills/{skill_id}")
    def get_skill(skill_id: str, version: str | None = None, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
        conn = get_conn()
        cur = conn.cursor()
        require_actor_permission(cur, x_actor_name, "read")
        ensure_skill_registry_tables(cur)
        cur.execute(
            """
            SELECT skill_id, display_name, description, status, latest_version, entrypoint_kind, created_at, updated_at
            FROM skills
            WHERE skill_id = %s;
            """,
            (skill_id.strip(),),
        )
        skill_row = cur.fetchone()
        if not skill_row:
            cur.close()
            conn.close()
            raise HTTPException(status_code=404, detail="Skill not found")
        resolved_version = version.strip() if version else str(skill_row.get("latest_version") or "").strip()
        cur.execute(
            """
            SELECT skill_id, version, package_format, package_source, description, package_body, created_at
            FROM skill_versions
            WHERE skill_id = %s AND version = %s;
            """,
            (skill_id.strip(), resolved_version),
        )
        version_row = cur.fetchone()
        cur.close()
        conn.close()
        return {
            "skill": serialize_skill_row(skill_row),
            "version": serialize_skill_version_row(version_row) if version_row else None,
        }

    @router.post("/skills/import")
    def import_skill(request: SkillImportRequest, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
        conn = get_conn()
        cur = conn.cursor()
        actor = require_actor_permission(cur, x_actor_name, "admin")
        ensure_skill_registry_tables(cur)
        payload = read_skill_package_from_source(request.source_path)
        cur.execute(
            """
            INSERT INTO skills (skill_id, display_name, description, status, latest_version, entrypoint_kind)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (skill_id) DO UPDATE
            SET display_name = EXCLUDED.display_name,
                description = EXCLUDED.description,
                status = CASE WHEN %s THEN 'active' ELSE skills.status END,
                latest_version = CASE WHEN %s THEN EXCLUDED.latest_version ELSE skills.latest_version END,
                entrypoint_kind = EXCLUDED.entrypoint_kind,
                updated_at = CURRENT_TIMESTAMP;
            """,
            (
                payload["skill_id"],
                payload["display_name"],
                payload["description"],
                "active" if request.activate else "draft",
                payload["version"],
                payload["entrypoint_kind"],
                bool(request.activate),
                bool(request.activate),
            ),
        )
        cur.execute(
            """
            INSERT INTO skill_versions (skill_id, version, package_format, package_source, description, package_body)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (skill_id, version) DO UPDATE
            SET package_format = EXCLUDED.package_format,
                package_source = EXCLUDED.package_source,
                description = EXCLUDED.description,
                package_body = EXCLUDED.package_body;
            """,
            (
                payload["skill_id"],
                payload["version"],
                payload["package_format"],
                payload["package_source"],
                payload["description"],
                json_wrapper(payload["package_body"]),
            ),
        )
        insert_audit_log(
            cur,
            "skill.import",
            actor["actor_name"],
            None,
            {
                "skill_id": payload["skill_id"],
                "version": payload["version"],
                "source_path": payload["package_source"],
                "activate": bool(request.activate),
            },
        )
        conn.commit()
        cur.execute(
            """
            SELECT skill_id, display_name, description, status, latest_version, entrypoint_kind, created_at, updated_at
            FROM skills
            WHERE skill_id = %s;
            """,
            (payload["skill_id"],),
        )
        skill_row = cur.fetchone()
        cur.execute(
            """
            SELECT skill_id, version, package_format, package_source, description, package_body, created_at
            FROM skill_versions
            WHERE skill_id = %s AND version = %s;
            """,
            (payload["skill_id"], payload["version"]),
        )
        version_row = cur.fetchone()
        cur.close()
        conn.close()
        return {
            "skill": serialize_skill_row(skill_row),
            "version": serialize_skill_version_row(version_row),
        }

    return router
