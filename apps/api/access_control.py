import json
from typing import Any

from fastapi import HTTPException

from core.schema_migration_runtime import is_runtime_schema_finalized
from serializers import serialize_access_actor_row, serialize_access_quota_row


ACCESS_ROLE_PERMISSIONS = {
    "viewer": {"read"},
    "operator": {"read", "operate"},
    "admin": {"read", "operate", "admin"},
}

DEFAULT_ACTORS = [
    {"actor_name": "local_admin", "role": "admin", "description": "默认本地管理员", "tenant_key": "default", "permission_overrides": []},
    {"actor_name": "local_operator", "role": "operator", "description": "默认本地操作员", "tenant_key": "default", "permission_overrides": []},
    {"actor_name": "local_viewer", "role": "viewer", "description": "默认本地只读用户", "tenant_key": "default", "permission_overrides": []},
]

DEFAULT_ROLE_QUOTAS = {
    "admin": {"daily_task_limit": 1000, "active_task_limit": 200, "daily_token_limit": 2000000, "max_parallel_agents": 64},
    "operator": {"daily_task_limit": 50, "active_task_limit": 20, "daily_token_limit": 300000, "max_parallel_agents": 16},
    "viewer": {"daily_task_limit": 0, "active_task_limit": 0, "daily_token_limit": 0, "max_parallel_agents": 0},
}


def _normalize_permission_overrides(value: Any) -> list[str]:
    raw = value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raw = []
        else:
            try:
                raw = json.loads(text)
            except Exception:
                raw = []
    if not isinstance(raw, list):
        return []
    seen: set[str] = set()
    normalized: list[str] = []
    for item in raw:
        permission = str(item or "").strip().lower()
        if not permission or permission in seen:
            continue
        seen.add(permission)
        normalized.append(permission)
    return normalized


def ensure_access_actors_table(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS access_actors (
            actor_name TEXT PRIMARY KEY,
            role TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            tenant_key TEXT NOT NULL DEFAULT 'default',
            permission_overrides TEXT NOT NULL DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    if not is_runtime_schema_finalized(cur):
        cur.execute("ALTER TABLE access_actors ADD COLUMN IF NOT EXISTS tenant_key TEXT NOT NULL DEFAULT 'default';")
        cur.execute("ALTER TABLE access_actors ADD COLUMN IF NOT EXISTS permission_overrides TEXT NOT NULL DEFAULT '[]';")


def ensure_access_quotas_table(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS access_quotas (
            actor_name TEXT PRIMARY KEY REFERENCES access_actors(actor_name) ON DELETE CASCADE,
            daily_task_limit INTEGER NOT NULL,
            active_task_limit INTEGER NOT NULL,
            daily_token_limit INTEGER NOT NULL DEFAULT 0,
            max_parallel_agents INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    if not is_runtime_schema_finalized(cur):
        cur.execute("ALTER TABLE access_quotas ADD COLUMN IF NOT EXISTS daily_token_limit INTEGER NOT NULL DEFAULT 0;")
        cur.execute("ALTER TABLE access_quotas ADD COLUMN IF NOT EXISTS max_parallel_agents INTEGER NOT NULL DEFAULT 0;")


def upsert_default_access_quota(cur, actor_name: str, role: str):
    quota = DEFAULT_ROLE_QUOTAS.get(role, DEFAULT_ROLE_QUOTAS["viewer"])
    cur.execute(
        """
        INSERT INTO access_quotas (actor_name, daily_task_limit, active_task_limit, daily_token_limit, max_parallel_agents)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (actor_name) DO NOTHING;
        """,
        (
            actor_name,
            int(quota["daily_task_limit"]),
            int(quota["active_task_limit"]),
            int(quota["daily_token_limit"]),
            int(quota["max_parallel_agents"]),
        ),
    )


def seed_default_access_actors(cur):
    ensure_access_actors_table(cur)
    for actor in DEFAULT_ACTORS:
        cur.execute(
            """
            INSERT INTO access_actors (actor_name, role, description, tenant_key, permission_overrides)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (actor_name) DO NOTHING;
            """,
            (
                actor["actor_name"],
                actor["role"],
                actor["description"],
                actor.get("tenant_key") or "default",
                json.dumps(actor.get("permission_overrides") or [], ensure_ascii=False),
            ),
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
        SELECT actor_name, role, description, tenant_key, permission_overrides, created_at, updated_at
        FROM access_actors
        WHERE actor_name = %s;
        """,
        (actor_name,),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=403, detail=f"Unknown actor: {actor_name}")
    permissions = set(ACCESS_ROLE_PERMISSIONS.get(str(row.get("role") or ""), set()))
    permissions.update(_normalize_permission_overrides(row.get("permission_overrides")))
    row["permissions"] = permissions
    row["permission_overrides"] = _normalize_permission_overrides(row.get("permission_overrides"))
    return serialize_access_actor_row(row)


def require_actor_permission(cur, x_actor_name: str | None, required_permission: str) -> dict[str, Any]:
    actor = resolve_actor_context(cur, x_actor_name)
    permissions = set(actor.get("permissions") or ACCESS_ROLE_PERMISSIONS.get(actor["role"], set()))
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
        SELECT actor_name, daily_task_limit, active_task_limit, daily_token_limit, max_parallel_agents, created_at, updated_at
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
    max_parallel_agents = int(quota.get("max_parallel_agents") or 0)
    if max_parallel_agents > 0 and active_count >= max_parallel_agents:
        raise HTTPException(
            status_code=429,
            detail=f"Actor {actor_name} exceeded max parallel task budget ({max_parallel_agents})",
        )

    daily_token_limit = int(quota.get("daily_token_limit") or 0)
    daily_token_count = 0
    if daily_token_limit > 0:
        try:
            cur.execute("SELECT to_regclass('public.agent_runs') AS regclass;")
            if cur.fetchone().get("regclass"):
                cur.execute(
                    """
                    SELECT COALESCE(SUM(COALESCE(ar.cost_tokens_in, 0) + COALESCE(ar.cost_tokens_out, 0)), 0) AS count
                    FROM agent_runs ar
                    JOIN task_runs tr ON tr.id = ar.task_run_id
                    WHERE tr.created_by_actor = %s
                      AND DATE(ar.created_at) = CURRENT_DATE;
                    """,
                    (actor_name,),
                )
                daily_token_count = int(cur.fetchone()["count"])
        except Exception:
            daily_token_count = 0
        if daily_token_count >= daily_token_limit:
            raise HTTPException(
                status_code=429,
                detail=f"Actor {actor_name} exceeded daily token limit ({daily_token_limit})",
            )
    return {
        "daily_task_limit": int(quota["daily_task_limit"]),
        "active_task_limit": int(quota["active_task_limit"]),
        "daily_token_limit": daily_token_limit,
        "max_parallel_agents": max_parallel_agents,
        "daily_task_count": daily_count,
        "active_task_count": active_count,
        "daily_token_count": daily_token_count,
    }


def upsert_access_actor(
    cur,
    *,
    actor_name: str,
    role: str,
    description: str,
    tenant_key: str,
    permission_overrides: list[str],
    admin_actor_name: str,
    upsert_default_access_quota_fn,
    insert_audit_log_fn,
) -> dict[str, Any]:
    cur.execute(
        """
        INSERT INTO access_actors (actor_name, role, description, tenant_key, permission_overrides)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (actor_name) DO UPDATE
        SET role = EXCLUDED.role,
            description = EXCLUDED.description,
            tenant_key = EXCLUDED.tenant_key,
            permission_overrides = EXCLUDED.permission_overrides,
            updated_at = CURRENT_TIMESTAMP
        RETURNING actor_name, role, description, tenant_key, permission_overrides, created_at, updated_at;
        """,
        (
            actor_name,
            role,
            description,
            tenant_key or "default",
            json.dumps(permission_overrides or [], ensure_ascii=False),
        ),
    )
    row = cur.fetchone()
    row["permissions"] = set(ACCESS_ROLE_PERMISSIONS.get(role, set())) | set(permission_overrides or [])
    upsert_default_access_quota_fn(cur, actor_name, role)
    insert_audit_log_fn(
        cur,
        "access.actor_update",
        admin_actor_name,
        None,
        {
            "target_actor_name": actor_name,
            "role": role,
            "description": description,
            "tenant_key": tenant_key or "default",
            "permission_overrides": permission_overrides or [],
        },
    )
    return serialize_access_actor_row(row)


def upsert_access_quota(
    cur,
    *,
    actor_name: str,
    daily_task_limit: int,
    active_task_limit: int,
    daily_token_limit: int,
    max_parallel_agents: int,
    admin_actor_name: str,
    seed_default_access_quotas_fn,
    insert_audit_log_fn,
) -> dict[str, Any]:
    seed_default_access_quotas_fn(cur)
    cur.execute("SELECT actor_name FROM access_actors WHERE actor_name = %s;", (actor_name,))
    if not cur.fetchone():
        raise HTTPException(status_code=404, detail=f"Actor not found: {actor_name}")
    cur.execute(
        """
        INSERT INTO access_quotas (actor_name, daily_task_limit, active_task_limit, daily_token_limit, max_parallel_agents)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (actor_name) DO UPDATE
        SET daily_task_limit = EXCLUDED.daily_task_limit,
            active_task_limit = EXCLUDED.active_task_limit,
            daily_token_limit = EXCLUDED.daily_token_limit,
            max_parallel_agents = EXCLUDED.max_parallel_agents,
            updated_at = CURRENT_TIMESTAMP
        RETURNING actor_name, daily_task_limit, active_task_limit, daily_token_limit, max_parallel_agents, created_at, updated_at;
        """,
        (actor_name, daily_task_limit, active_task_limit, daily_token_limit, max_parallel_agents),
    )
    row = cur.fetchone()
    insert_audit_log_fn(
        cur,
        "access.quota_update",
        admin_actor_name,
        None,
        {
            "target_actor_name": actor_name,
            "daily_task_limit": daily_task_limit,
            "active_task_limit": active_task_limit,
            "daily_token_limit": daily_token_limit,
            "max_parallel_agents": max_parallel_agents,
        },
    )
    return serialize_access_quota_row(row)
