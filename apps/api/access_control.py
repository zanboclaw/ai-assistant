from typing import Any

from fastapi import HTTPException

from serializers import serialize_access_actor_row, serialize_access_quota_row


ACCESS_ROLE_PERMISSIONS = {
    "viewer": {"read"},
    "operator": {"read", "operate"},
    "admin": {"read", "operate", "admin"},
}

DEFAULT_ACTORS = [
    {"actor_name": "local_admin", "role": "admin", "description": "默认本地管理员"},
    {"actor_name": "local_operator", "role": "operator", "description": "默认本地操作员"},
    {"actor_name": "local_viewer", "role": "viewer", "description": "默认本地只读用户"},
]

DEFAULT_ROLE_QUOTAS = {
    "admin": {"daily_task_limit": 1000, "active_task_limit": 200},
    "operator": {"daily_task_limit": 50, "active_task_limit": 20},
    "viewer": {"daily_task_limit": 0, "active_task_limit": 0},
}


def ensure_access_actors_table(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS access_actors (
            actor_name TEXT PRIMARY KEY,
            role TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )


def ensure_access_quotas_table(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS access_quotas (
            actor_name TEXT PRIMARY KEY REFERENCES access_actors(actor_name) ON DELETE CASCADE,
            daily_task_limit INTEGER NOT NULL,
            active_task_limit INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )


def upsert_default_access_quota(cur, actor_name: str, role: str):
    quota = DEFAULT_ROLE_QUOTAS.get(role, DEFAULT_ROLE_QUOTAS["viewer"])
    cur.execute(
        """
        INSERT INTO access_quotas (actor_name, daily_task_limit, active_task_limit)
        VALUES (%s, %s, %s)
        ON CONFLICT (actor_name) DO NOTHING;
        """,
        (actor_name, int(quota["daily_task_limit"]), int(quota["active_task_limit"])),
    )


def seed_default_access_actors(cur):
    ensure_access_actors_table(cur)
    for actor in DEFAULT_ACTORS:
        cur.execute(
            """
            INSERT INTO access_actors (actor_name, role, description)
            VALUES (%s, %s, %s)
            ON CONFLICT (actor_name) DO NOTHING;
            """,
            (actor["actor_name"], actor["role"], actor["description"]),
        )


def seed_default_access_quotas(cur):
    ensure_access_actors_table(cur)
    ensure_access_quotas_table(cur)
    seed_default_access_actors(cur)
    cur.execute("SELECT actor_name, role FROM access_actors;")
    for row in cur.fetchall():
        upsert_default_access_quota(cur, str(row["actor_name"]), str(row["role"]))


def resolve_actor_context(cur, x_actor_name: str | None) -> dict[str, Any]:
    seed_default_access_actors(cur)
    actor_name = (x_actor_name or "").strip() or "local_admin"
    cur.execute(
        """
        SELECT actor_name, role, description, created_at, updated_at
        FROM access_actors
        WHERE actor_name = %s;
        """,
        (actor_name,),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=403, detail=f"Unknown actor: {actor_name}")
    return serialize_access_actor_row(row)


def require_actor_permission(cur, x_actor_name: str | None, required_permission: str) -> dict[str, Any]:
    actor = resolve_actor_context(cur, x_actor_name)
    permissions = ACCESS_ROLE_PERMISSIONS.get(actor["role"], set())
    if required_permission not in permissions:
        raise HTTPException(
            status_code=403,
            detail=f"Actor {actor['actor_name']} with role {actor['role']} lacks permission: {required_permission}",
        )
    return actor


def get_actor_quota_or_404(cur, actor_name: str) -> dict[str, Any]:
    seed_default_access_quotas(cur)
    cur.execute(
        """
        SELECT actor_name, daily_task_limit, active_task_limit, created_at, updated_at
        FROM access_quotas
        WHERE actor_name = %s;
        """,
        (actor_name,),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Quota not found for actor: {actor_name}")
    return serialize_access_quota_row(row)


def enforce_task_quota(cur, actor_name: str):
    quota = get_actor_quota_or_404(cur, actor_name)
    cur.execute(
        """
        SELECT COUNT(*) AS count
        FROM task_runs
        WHERE created_by_actor = %s
          AND DATE(created_at) = CURRENT_DATE;
        """,
        (actor_name,),
    )
    daily_count = int(cur.fetchone()["count"])
    if daily_count >= int(quota["daily_task_limit"]):
        raise HTTPException(
            status_code=429,
            detail=f"Actor {actor_name} exceeded daily task limit ({quota['daily_task_limit']})",
        )

    cur.execute(
        """
        SELECT COUNT(*) AS count
        FROM task_runs
        WHERE created_by_actor = %s
          AND status NOT IN ('completed', 'failed');
        """,
        (actor_name,),
    )
    active_count = int(cur.fetchone()["count"])
    if active_count >= int(quota["active_task_limit"]):
        raise HTTPException(
            status_code=429,
            detail=f"Actor {actor_name} exceeded active task limit ({quota['active_task_limit']})",
        )
    return {
        "daily_task_limit": int(quota["daily_task_limit"]),
        "active_task_limit": int(quota["active_task_limit"]),
        "daily_task_count": daily_count,
        "active_task_count": active_count,
    }
