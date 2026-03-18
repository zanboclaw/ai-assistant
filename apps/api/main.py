from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import psycopg2
from psycopg2.extras import RealDictCursor
try:
    import redis
except ImportError:  # pragma: no cover - optional in local non-container runs
    redis = None

app = FastAPI(title="AI Assistant API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_CONFIG = {
    "host": "postgres",
    "dbname": "assistant",
    "user": "assistant",
    "password": "assistant123",
}

LOG_DIR = Path(os.environ.get("LOG_DIR", "/opt/ai-assistant/logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)
CHECKPOINT_DIR = Path(os.environ.get("CHECKPOINT_DIR", "/checkpoints"))
CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

DEFAULT_RISK_POLICIES = [
    {
        "policy_key": "approval_low_risk_write_extensions",
        "value_type": "json",
        "policy_value": [".txt", ".md", ".csv", ".log"],
        "description": "新建这些扩展名的文件时可直接写入，无需审批。",
    },
    {
        "policy_key": "approval_sensitive_write_extensions",
        "value_type": "json",
        "policy_value": [".py", ".sh", ".bash", ".zsh", ".env", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".sql"],
        "description": "写入这些脚本/配置类扩展名时必须审批。",
    },
    {
        "policy_key": "approval_sensitive_write_basenames",
        "value_type": "json",
        "policy_value": ["dockerfile", "makefile", ".env", ".gitignore"],
        "description": "写入这些特定文件名时必须审批。",
    },
    {
        "policy_key": "approval_require_for_existing_file_overwrite",
        "value_type": "bool",
        "policy_value": True,
        "description": "覆盖已有文件时是否要求审批。",
    },
    {
        "policy_key": "approval_require_for_hidden_files",
        "value_type": "bool",
        "policy_value": True,
        "description": "写入隐藏文件时是否要求审批。",
    },
    {
        "policy_key": "approval_allowed_http_methods",
        "value_type": "json",
        "policy_value": ["GET"],
        "description": "这些 HTTP 方法默认允许直通，其余方法要求审批。",
    },
    {
        "policy_key": "approval_http_get_requires_approval_suffixes",
        "value_type": "json",
        "policy_value": [".local"],
        "description": "GET 请求命中这些域名后缀时仍要求审批。",
    },
]
RISK_POLICY_MAP = {item["policy_key"]: item for item in DEFAULT_RISK_POLICIES}
STEP_REQUEST_PROTOCOL_VERSION = "stage2-v1"
STEP_EXECUTION_REQUEST_FIELDS = [
    "step_order",
    "current_status",
    "tool_name",
    "raw_input",
    "run_if",
    "skip_if",
    "error_strategy",
    "max_retries",
    "retry_count",
]
ENRICHED_STEP_EXECUTION_REQUEST_EXTRA_FIELDS = [
    "should_run",
    "skip_reason",
    "resolved_input",
    "approval_required",
    "approval_reason",
    "effective_retry_count",
    "effective_max_retries",
    "result",
]


def build_logger() -> logging.Logger:
    logger = logging.getLogger("ai_assistant.api")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("[%(asctime)s] %(levelname)s %(message)s")

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    file_handler = logging.FileHandler(LOG_DIR / "api.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


logger = build_logger()


def get_redis_client():
    if redis is None:
        return None
    try:
        return redis.Redis.from_url(REDIS_URL, decode_responses=True)
    except Exception as exc:
        logger.warning("redis client init failed: %s", exc)
        return None


def enqueue_task(task_id: int):
    client = get_redis_client()
    if client is None:
        logger.warning("redis unavailable, skip enqueue task_id=%s", task_id)
        return
    try:
        client.rpush("task_queue", str(task_id))
    except Exception as exc:
        logger.warning("enqueue task failed task_id=%s error=%s", task_id, exc)


class TaskCreate(BaseModel):
    user_input: str
    session_id: int | None = None


class SessionCreate(BaseModel):
    name: str
    description: str = ""


class SessionMemoryCreate(BaseModel):
    category: str
    content: str
    importance: int = 3
    source_task_id: int | None = None


class SessionStateUpdate(BaseModel):
    summary_text: str = ""
    preferences: list[str] = []
    open_loops: list[str] = []


class SessionReviewCreate(BaseModel):
    review_kind: str = "manual"
    note: str = ""


class DailyReviewRunRequest(BaseModel):
    review_kind: str = "daily"
    note: str = ""
    session_limit: int = 20
    active_within_hours: int = 24
    force: bool = False


class ApprovalDecision(BaseModel):
    note: str = ""


class TaskResumeRequest(BaseModel):
    note: str = ""
    from_step: int | None = None


class TaskInterruptRequest(BaseModel):
    note: str = ""


class RiskPolicyUpdate(BaseModel):
    policy_value: Any


class AccessQuotaUpdate(BaseModel):
    daily_task_limit: int
    active_task_limit: int


class ToolRegistryUpdate(BaseModel):
    enabled: bool
    risk_level: str
    description: str = ""


class ModelRouteUpdate(BaseModel):
    provider: str
    enabled: bool
    model_name: str
    temperature: float
    max_tokens: int
    description: str = ""


class ModelProviderUpdate(BaseModel):
    driver: str
    base_url: str
    api_key_env: str
    enabled: bool
    description: str = ""


class ChangeRequestCreate(BaseModel):
    target_type: str
    target_key: str
    proposed_payload: dict[str, Any]
    rationale: str = ""


class ChangeRequestDecision(BaseModel):
    note: str = ""


def get_conn():
    return psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)


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
DEFAULT_TOOL_REGISTRY = [
    {"tool_name": "file_read", "enabled": True, "risk_level": "low", "description": "读取文本文件。"},
    {"tool_name": "file_write", "enabled": True, "risk_level": "high", "description": "写入文本文件。"},
    {"tool_name": "list_dir", "enabled": True, "risk_level": "low", "description": "列出目录内容。"},
    {"tool_name": "shell_exec", "enabled": True, "risk_level": "high", "description": "执行受限 shell 命令。"},
    {"tool_name": "summarize_text", "enabled": True, "risk_level": "low", "description": "整理文本摘要。"},
    {"tool_name": "web_search", "enabled": True, "risk_level": "low", "description": "执行联网搜索。"},
    {"tool_name": "read_json", "enabled": True, "risk_level": "low", "description": "读取 JSON 文件。"},
    {"tool_name": "write_json", "enabled": True, "risk_level": "high", "description": "写入 JSON 文件。"},
    {"tool_name": "http_request", "enabled": True, "risk_level": "medium", "description": "执行 HTTP 请求。"},
    {"tool_name": "json_extract", "enabled": True, "risk_level": "low", "description": "从 JSON 中提取字段。"},
    {"tool_name": "if_condition", "enabled": True, "risk_level": "low", "description": "执行条件判断。"},
    {"tool_name": "set_var", "enabled": True, "risk_level": "low", "description": "写入运行时变量。"},
    {"tool_name": "template_render", "enabled": True, "risk_level": "low", "description": "渲染文本模板。"},
]
DEFAULT_MODEL_ROUTES = [
    {
        "route_name": "planner",
        "provider": "deepseek_default",
        "model_name": os.environ.get("DEEPSEEK_PLANNER_MODEL", os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")),
        "temperature": 0.2,
        "max_tokens": 1500,
        "enabled": True,
        "description": "任务规划模型路由。",
    },
    {
        "route_name": "summarize_text",
        "provider": "deepseek_default",
        "model_name": os.environ.get("DEEPSEEK_SUMMARY_MODEL", os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")),
        "temperature": 0.2,
        "max_tokens": 800,
        "enabled": True,
        "description": "文本摘要模型路由。",
    },
    {
        "route_name": "web_search_summary",
        "provider": "deepseek_default",
        "model_name": os.environ.get("DEEPSEEK_SEARCH_SUMMARY_MODEL", os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")),
        "temperature": 0.2,
        "max_tokens": 1200,
        "enabled": True,
        "description": "搜索结果整理模型路由。",
    },
]
DEFAULT_MODEL_PROVIDERS = [
    {
        "provider_name": "deepseek_default",
        "driver": "openai_compatible",
        "base_url": os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        "api_key_env": "DEEPSEEK_API_KEY",
        "enabled": True,
        "description": "默认 DeepSeek OpenAI-compatible provider。",
    },
    {
        "provider_name": "openai_compatible",
        "driver": "openai_compatible",
        "base_url": os.environ.get("OPENAI_COMPATIBLE_BASE_URL", os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")),
        "api_key_env": os.environ.get("OPENAI_COMPATIBLE_API_KEY_ENV", "DEEPSEEK_API_KEY"),
        "enabled": True,
        "description": "兼容历史 route.provider 的默认 OpenAI-compatible provider。",
    },
]


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


def ensure_tool_registry_table(cur):
    cur.execute("SELECT pg_advisory_xact_lock(hashtext('tool_registry_entries_schema'));")
    cur.execute("SELECT to_regclass('public.tool_registry_entries') AS regclass;")
    if cur.fetchone()["regclass"]:
        return
    cur.execute(
        """
        CREATE TABLE tool_registry_entries (
            tool_name TEXT PRIMARY KEY,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            risk_level TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )


def ensure_model_routes_table(cur):
    cur.execute("SELECT pg_advisory_xact_lock(hashtext('model_routes_schema'));")
    cur.execute("SELECT to_regclass('public.model_routes') AS regclass;")
    if cur.fetchone()["regclass"]:
        return
    cur.execute(
        """
        CREATE TABLE model_routes (
            route_name TEXT PRIMARY KEY,
            provider TEXT NOT NULL DEFAULT 'openai_compatible',
            model_name TEXT NOT NULL,
            temperature DOUBLE PRECISION NOT NULL,
            max_tokens INTEGER NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            description TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )


def ensure_model_providers_table(cur):
    cur.execute("SELECT pg_advisory_xact_lock(hashtext('model_providers_schema'));")
    cur.execute("SELECT to_regclass('public.model_providers') AS regclass;")
    if cur.fetchone()["regclass"]:
        return
    cur.execute(
        """
        CREATE TABLE model_providers (
            provider_name TEXT PRIMARY KEY,
            driver TEXT NOT NULL DEFAULT 'openai_compatible',
            base_url TEXT NOT NULL,
            api_key_env TEXT NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            description TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )


def ensure_change_requests_table(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS change_requests (
            id SERIAL PRIMARY KEY,
            target_type TEXT NOT NULL,
            target_key TEXT NOT NULL,
            proposed_payload JSONB NOT NULL,
            rationale TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            requested_by_actor TEXT NOT NULL,
            reviewed_by_actor TEXT,
            decision_note TEXT,
            applied_by_actor TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reviewed_at TIMESTAMP,
            applied_at TIMESTAMP
        );
        """
    )


def seed_default_tool_registry(cur):
    ensure_tool_registry_table(cur)
    for tool in DEFAULT_TOOL_REGISTRY:
        cur.execute(
            """
            INSERT INTO tool_registry_entries (tool_name, enabled, risk_level, description)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (tool_name) DO NOTHING;
            """,
            (tool["tool_name"], tool["enabled"], tool["risk_level"], tool["description"]),
        )


def seed_default_model_routes(cur):
    ensure_model_routes_table(cur)
    for route in DEFAULT_MODEL_ROUTES:
        cur.execute(
            """
            INSERT INTO model_routes (
                route_name, provider, model_name, temperature, max_tokens, enabled, description
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (route_name) DO NOTHING;
            """,
            (
                route["route_name"],
                route["provider"],
                route["model_name"],
                route["temperature"],
                route["max_tokens"],
                route["enabled"],
                route["description"],
            ),
        )


def seed_default_model_providers(cur):
    ensure_model_providers_table(cur)
    for provider in DEFAULT_MODEL_PROVIDERS:
        cur.execute(
            """
            INSERT INTO model_providers (
                provider_name, driver, base_url, api_key_env, enabled, description
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (provider_name) DO NOTHING;
            """,
            (
                provider["provider_name"],
                provider["driver"],
                provider["base_url"],
                provider["api_key_env"],
                provider["enabled"],
                provider["description"],
            ),
        )


def serialize_tool_registry_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "tool_name": row["tool_name"],
        "enabled": bool(row["enabled"]),
        "risk_level": row["risk_level"],
        "description": row["description"] or "",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def serialize_model_route_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "route_name": row["route_name"],
        "provider": row["provider"],
        "model_name": row["model_name"],
        "temperature": float(row["temperature"]),
        "max_tokens": int(row["max_tokens"]),
        "enabled": bool(row["enabled"]),
        "description": row["description"] or "",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def serialize_model_provider_row(row: dict[str, Any]) -> dict[str, Any]:
    api_key_env = str(row["api_key_env"])
    return {
        "provider_name": row["provider_name"],
        "driver": row["driver"],
        "base_url": row["base_url"],
        "api_key_env": api_key_env,
        "configured": bool(os.environ.get(api_key_env)),
        "enabled": bool(row["enabled"]),
        "description": row.get("description") or "",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def serialize_change_request_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "target_type": row["target_type"],
        "target_key": row["target_key"],
        "proposed_payload": parse_maybe_json(row.get("proposed_payload")),
        "rationale": row.get("rationale") or "",
        "status": row["status"],
        "requested_by_actor": row["requested_by_actor"],
        "reviewed_by_actor": row.get("reviewed_by_actor"),
        "decision_note": row.get("decision_note") or "",
        "applied_by_actor": row.get("applied_by_actor"),
        "created_at": row.get("created_at"),
        "reviewed_at": row.get("reviewed_at"),
        "applied_at": row.get("applied_at"),
    }


def serialize_access_quota_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "actor_name": row["actor_name"],
        "daily_task_limit": int(row["daily_task_limit"]),
        "active_task_limit": int(row["active_task_limit"]),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


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


def seed_default_access_quotas(cur):
    ensure_access_actors_table(cur)
    ensure_access_quotas_table(cur)
    seed_default_access_actors(cur)
    cur.execute("SELECT actor_name, role FROM access_actors;")
    for row in cur.fetchall():
        upsert_default_access_quota(cur, str(row["actor_name"]), str(row["role"]))


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


def serialize_access_actor_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "actor_name": row["actor_name"],
        "role": row["role"],
        "description": row["description"] or "",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


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


def safe_json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return json.dumps({"repr": repr(value)}, ensure_ascii=False)


def ensure_audit_logs_table(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_logs (
            id SERIAL PRIMARY KEY,
            task_id INTEGER REFERENCES task_runs(id),
            event_type TEXT NOT NULL,
            actor TEXT NOT NULL,
            details JSONB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )


def insert_audit_log(cur, event_type: str, actor: str, task_id: int | None = None, details: Any | None = None):
    cur.execute(
        """
        INSERT INTO audit_logs (task_id, event_type, actor, details)
        VALUES (%s, %s, %s, %s);
        """,
        (task_id, event_type, actor, safe_json_dumps(details) if details is not None else None),
    )


def record_audit_event(event_type: str, actor: str, task_id: int | None = None, details: Any | None = None):
    conn = get_conn()
    cur = conn.cursor()
    try:
        ensure_audit_logs_table(cur)
        insert_audit_log(cur, event_type, actor, task_id, details)
        conn.commit()
    finally:
        cur.close()
        conn.close()


def parse_maybe_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except Exception:
        return value


SUPPORTED_CHANGE_TARGET_TYPES = {
    "risk_policy",
    "tool_registry",
    "model_route",
    "model_provider",
    "access_quota",
    "access_actor",
}
DEFAULT_ENFORCED_CHANGE_TARGET_TYPES = {
    item.strip()
    for item in os.environ.get("CHANGE_GATE_ENFORCED_TARGET_TYPES", "").split(",")
    if item.strip()
}


def get_change_request_or_404(cur, change_request_id: int) -> dict[str, Any]:
    ensure_change_requests_table(cur)
    cur.execute(
        """
        SELECT id, target_type, target_key, proposed_payload, rationale, status,
               requested_by_actor, reviewed_by_actor, decision_note, applied_by_actor,
               created_at, reviewed_at, applied_at
        FROM change_requests
        WHERE id = %s;
        """,
        (change_request_id,),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Change request not found: {change_request_id}")
    return serialize_change_request_row(row)


def is_change_gate_enforced(target_type: str) -> bool:
    return target_type in DEFAULT_ENFORCED_CHANGE_TARGET_TYPES


def enforce_change_gate_for_direct_update(target_type: str):
    if is_change_gate_enforced(target_type):
        raise HTTPException(
            status_code=409,
            detail=f"Direct update disabled for {target_type}; submit and apply a change request instead",
        )


def apply_change_request_payload(cur, target_type: str, target_key: str, payload: dict[str, Any]):
    if target_type == "risk_policy":
        seed_default_risk_policies(cur)
        policy = RISK_POLICY_MAP.get(target_key)
        if not policy:
            raise HTTPException(status_code=404, detail=f"Risk policy not found: {target_key}")
        value = payload.get("policy_value")
        cur.execute(
            """
            UPDATE risk_policies
            SET policy_value = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE policy_key = %s;
            """,
            (safe_json_dumps(value), target_key),
        )
        return

    if target_type == "tool_registry":
        seed_default_tool_registry(cur)
        risk_level = str(payload.get("risk_level") or "").strip().lower()
        if risk_level not in {"low", "medium", "high"}:
            raise HTTPException(status_code=400, detail=f"Unsupported risk level: {risk_level}")
        cur.execute(
            """
            UPDATE tool_registry_entries
            SET enabled = %s,
                risk_level = %s,
                description = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE tool_name = %s;
            """,
            (
                bool(payload.get("enabled")),
                risk_level,
                str(payload.get("description") or "").strip(),
                target_key,
            ),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Tool not found: {target_key}")
        return

    if target_type == "model_route":
        seed_default_model_providers(cur)
        seed_default_model_routes(cur)
        provider = str(payload.get("provider") or "").strip()
        if not provider:
            raise HTTPException(status_code=400, detail="provider is required")
        cur.execute("SELECT provider_name FROM model_providers WHERE provider_name = %s;", (provider,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail=f"Model provider not found: {provider}")
        model_name = str(payload.get("model_name") or "").strip()
        if not model_name:
            raise HTTPException(status_code=400, detail="model_name is required")
        max_tokens = int(payload.get("max_tokens") or 0)
        if max_tokens <= 0:
            raise HTTPException(status_code=400, detail="max_tokens must be positive")
        cur.execute(
            """
            UPDATE model_routes
            SET provider = %s,
                model_name = %s,
                temperature = %s,
                max_tokens = %s,
                enabled = %s,
                description = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE route_name = %s;
            """,
            (
                provider,
                model_name,
                float(payload.get("temperature") or 0.2),
                max_tokens,
                bool(payload.get("enabled")),
                str(payload.get("description") or "").strip(),
                target_key,
            ),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Model route not found: {target_key}")
        return

    if target_type == "model_provider":
        seed_default_model_providers(cur)
        driver = str(payload.get("driver") or "").strip()
        if driver not in {"openai_compatible"}:
            raise HTTPException(status_code=400, detail=f"Unsupported provider driver: {driver}")
        base_url = str(payload.get("base_url") or "").strip()
        api_key_env = str(payload.get("api_key_env") or "").strip()
        if not base_url:
            raise HTTPException(status_code=400, detail="base_url is required")
        if not api_key_env:
            raise HTTPException(status_code=400, detail="api_key_env is required")
        cur.execute(
            """
            INSERT INTO model_providers (provider_name, driver, base_url, api_key_env, enabled, description)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (provider_name)
            DO UPDATE SET driver = EXCLUDED.driver,
                          base_url = EXCLUDED.base_url,
                          api_key_env = EXCLUDED.api_key_env,
                          enabled = EXCLUDED.enabled,
                          description = EXCLUDED.description,
                          updated_at = CURRENT_TIMESTAMP;
            """,
            (
                target_key,
                driver,
                base_url,
                api_key_env,
                bool(payload.get("enabled")),
                str(payload.get("description") or "").strip(),
            ),
        )
        return

    if target_type == "access_quota":
        seed_default_access_quotas(cur)
        cur.execute(
            """
            UPDATE access_quotas
            SET daily_task_limit = %s,
                active_task_limit = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE actor_name = %s;
            """,
            (
                int(payload.get("daily_task_limit") or 0),
                int(payload.get("active_task_limit") or 0),
                target_key,
            ),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Quota not found for actor: {target_key}")
        return

    if target_type == "access_actor":
        seed_default_access_actors(cur)
        role = str(payload.get("role") or "").strip()
        if role not in ACCESS_ROLE_PERMISSIONS:
            raise HTTPException(status_code=400, detail=f"Unsupported role: {role}")
        cur.execute(
            """
            INSERT INTO access_actors (actor_name, role, description)
            VALUES (%s, %s, %s)
            ON CONFLICT (actor_name)
            DO UPDATE SET role = EXCLUDED.role,
                          description = EXCLUDED.description,
                          updated_at = CURRENT_TIMESTAMP;
            """,
            (target_key, role, str(payload.get("description") or "").strip()),
        )
        upsert_default_access_quota(cur, target_key, role)
        return

    raise HTTPException(status_code=400, detail=f"Unsupported change target type: {target_type}")


def get_redis_monitor_stats() -> dict[str, int]:
    client = get_redis_client()
    if client is None:
        return {
            "queue_depth": 0,
            "active_claims": 0,
        }

    try:
        queue_depth = int(client.llen("task_queue"))
    except Exception:
        queue_depth = 0

    active_claims = 0
    try:
        for _ in client.scan_iter(match="task_claim:*", count=100):
            active_claims += 1
    except Exception:
        active_claims = 0

    return {
        "queue_depth": queue_depth,
        "active_claims": active_claims,
    }


def ensure_risk_policies_table(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS risk_policies (
            id SERIAL PRIMARY KEY,
            policy_key TEXT NOT NULL UNIQUE,
            value_type TEXT NOT NULL,
            policy_value TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )


def seed_default_risk_policies(cur):
    ensure_risk_policies_table(cur)
    for item in DEFAULT_RISK_POLICIES:
        cur.execute(
            """
            INSERT INTO risk_policies (policy_key, value_type, policy_value, description)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (policy_key) DO NOTHING;
            """,
            (
                item["policy_key"],
                item["value_type"],
                safe_json_dumps(item["policy_value"]),
                item["description"],
            ),
        )


def deserialize_policy_row(row: dict) -> dict:
    try:
        parsed_value = json.loads(row["policy_value"])
    except Exception:
        parsed_value = row["policy_value"]
    return {
        "policy_key": row["policy_key"],
        "value_type": row["value_type"],
        "policy_value": parsed_value,
        "description": row["description"],
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def validate_policy_value(policy_key: str, value: Any) -> tuple[str, str]:
    item = RISK_POLICY_MAP.get(policy_key)
    if not item:
        raise HTTPException(status_code=404, detail="Risk policy not found")

    value_type = item["value_type"]
    if value_type == "bool":
        if not isinstance(value, bool):
            raise HTTPException(status_code=400, detail="policy_value must be boolean")
    elif value_type == "json":
        if not isinstance(value, list) or not all(isinstance(part, str) and part.strip() for part in value):
            raise HTTPException(status_code=400, detail="policy_value must be a non-empty string list")
        value = [part.strip() for part in value]
    else:
        raise HTTPException(status_code=500, detail="Unsupported policy type")

    return value_type, safe_json_dumps(value)


def serialize_session_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "description": row.get("description"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def serialize_session_memory_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "session_id": row.get("session_id"),
        "category": row.get("category"),
        "content": row.get("content"),
        "importance": row.get("importance"),
        "source_task_id": row.get("source_task_id"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def serialize_session_state_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": row.get("session_id"),
        "summary_text": row.get("summary_text") or "",
        "preferences": parse_maybe_json(row.get("preferences")) or [],
        "open_loops": parse_maybe_json(row.get("open_loops")) or [],
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def serialize_session_review_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "session_id": row.get("session_id"),
        "review_kind": row.get("review_kind"),
        "summary_text": row.get("summary_text") or "",
        "highlights": parse_maybe_json(row.get("highlights")) or [],
        "open_loops": parse_maybe_json(row.get("open_loops")) or [],
        "created_at": row.get("created_at"),
    }


def compute_session_state_from_rows(
    session_row: dict[str, Any],
    task_rows: list[dict[str, Any]],
    memory_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    tasks_by_status: dict[str, int] = {}
    for row in task_rows:
        status = str(row.get("status") or "unknown")
        tasks_by_status[status] = tasks_by_status.get(status, 0) + 1

    preferences: list[str] = []
    open_loops: list[str] = []
    seen_preferences: set[str] = set()
    seen_open_loops: set[str] = set()

    for row in memory_rows:
        category = str(row.get("category") or "").strip().lower()
        content = str(row.get("content") or "").strip()
        if not content:
            continue
        if category == "preference" and content not in seen_preferences:
            seen_preferences.add(content)
            preferences.append(content)
        if category in {"open_loop", "todo", "follow_up"} and content not in seen_open_loops:
            seen_open_loops.add(content)
            open_loops.append(content)

    for row in task_rows:
        status = str(row.get("status") or "")
        user_input = str(row.get("user_input") or "").strip()
        if status in {"pending", "running", "waiting_approval", "paused", "interrupt_requested"} and user_input and user_input not in seen_open_loops:
            seen_open_loops.add(user_input)
            open_loops.append(user_input)

    summary_parts = [
        f"Session: {session_row.get('name') or session_row.get('id')}",
        f"tasks={len(task_rows)}",
    ]
    if tasks_by_status:
        summary_parts.append(
            "statuses=" + ", ".join(f"{key}:{value}" for key, value in sorted(tasks_by_status.items()))
        )
    if preferences:
        summary_parts.append(f"preferences={len(preferences)}")
    if open_loops:
        summary_parts.append(f"open_loops={len(open_loops)}")

    return {
        "summary_text": " | ".join(summary_parts),
        "preferences": preferences,
        "open_loops": open_loops,
    }


def build_session_review(
    session_row: dict[str, Any],
    task_rows: list[dict[str, Any]],
    memory_rows: list[dict[str, Any]],
    session_state_row: dict[str, Any] | None,
    note: str = "",
) -> dict[str, Any]:
    tasks_by_status: dict[str, int] = {}
    for row in task_rows:
        status = str(row.get("status") or "unknown")
        tasks_by_status[status] = tasks_by_status.get(status, 0) + 1

    memory_counts: dict[str, int] = {}
    for row in memory_rows:
        category = str(row.get("category") or "unknown")
        memory_counts[category] = memory_counts.get(category, 0) + 1

    state = serialize_session_state_row(session_state_row) if session_state_row else {
        "summary_text": "",
        "preferences": [],
        "open_loops": [],
    }
    recent_completed = [
        str(row.get("user_input") or "").strip()
        for row in task_rows
        if str(row.get("status") or "") == "completed" and str(row.get("user_input") or "").strip()
    ][:3]

    highlights: list[str] = []
    highlights.append(f"任务总数 {len(task_rows)}，状态分布：{', '.join(f'{k}:{v}' for k, v in sorted(tasks_by_status.items())) or '无'}")
    if memory_counts:
        highlights.append("记忆分类：" + ", ".join(f"{k}:{v}" for k, v in sorted(memory_counts.items())))
    preferences = [str(item).strip() for item in state.get("preferences", []) if str(item).strip()]
    if preferences:
        highlights.append("当前偏好：" + "；".join(preferences[:3]))
    if recent_completed:
        highlights.append("最近完成：" + "；".join(recent_completed))
    if note.strip():
        highlights.append("备注：" + note.strip())

    open_loops = [str(item).strip() for item in state.get("open_loops", []) if str(item).strip()]
    summary_parts = [
        f"Session Review: {session_row.get('name') or session_row.get('id')}",
        f"tasks={len(task_rows)}",
        f"memories={len(memory_rows)}",
    ]
    if preferences:
        summary_parts.append(f"preferences={len(preferences)}")
    if open_loops:
        summary_parts.append(f"open_loops={len(open_loops)}")

    return {
        "summary_text": " | ".join(summary_parts),
        "highlights": highlights,
        "open_loops": open_loops[:10],
    }


def load_session_review_context(cur, session_id: int) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
    cur.execute(
        """
        SELECT id, name, description, created_at, updated_at
        FROM sessions
        WHERE id = %s;
        """,
        (session_id,),
    )
    session_row = cur.fetchone()
    if not session_row:
        raise HTTPException(status_code=404, detail="Session not found")

    cur.execute(
        """
        SELECT id, session_id, user_input, status, updated_at
        FROM task_runs
        WHERE session_id = %s
        ORDER BY updated_at DESC, id DESC;
        """,
        (session_id,),
    )
    task_rows = list(cur.fetchall())
    cur.execute(
        """
        SELECT id, session_id, category, content, importance, source_task_id, created_at, updated_at
        FROM session_memories
        WHERE session_id = %s
        ORDER BY importance DESC, id DESC;
        """,
        (session_id,),
    )
    memory_rows = list(cur.fetchall())
    cur.execute(
        """
        SELECT session_id, summary_text, preferences, open_loops, created_at, updated_at
        FROM session_states
        WHERE session_id = %s;
        """,
        (session_id,),
    )
    session_state_row = cur.fetchone()
    return session_row, task_rows, memory_rows, session_state_row


def insert_session_review_row(
    cur,
    session_id: int,
    review_kind: str,
    built_review: dict[str, Any],
) -> dict[str, Any]:
    cur.execute(
        """
        INSERT INTO session_reviews (session_id, review_kind, summary_text, highlights, open_loops)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id, session_id, review_kind, summary_text, highlights, open_loops, created_at;
        """,
        (
            session_id,
            review_kind,
            built_review["summary_text"],
            safe_json_dumps(built_review["highlights"]),
            safe_json_dumps(built_review["open_loops"]),
        ),
    )
    return cur.fetchone()


def merge_memory_into_session_state(
    cur,
    session_id: int,
    category: str,
    content: str,
) -> dict[str, Any] | None:
    normalized_category = category.strip().lower()
    normalized_content = content.strip()
    if not normalized_content:
        return None
    if normalized_category not in {"preference", "open_loop", "todo", "follow_up"}:
        return None

    cur.execute(
        """
        SELECT session_id, summary_text, preferences, open_loops, created_at, updated_at
        FROM session_states
        WHERE session_id = %s;
        """,
        (session_id,),
    )
    row = cur.fetchone()
    if row:
        state = serialize_session_state_row(row)
    else:
        state = {
            "session_id": session_id,
            "summary_text": "",
            "preferences": [],
            "open_loops": [],
            "created_at": None,
            "updated_at": None,
        }

    preferences = [str(item).strip() for item in state["preferences"] if str(item).strip()]
    open_loops = [str(item).strip() for item in state["open_loops"] if str(item).strip()]

    if normalized_category == "preference":
        if normalized_content not in preferences:
            preferences.append(normalized_content)
    else:
        if normalized_content not in open_loops:
            open_loops.append(normalized_content)

    cur.execute(
        """
        SELECT status, COUNT(*) AS count
        FROM task_runs
        WHERE session_id = %s
        GROUP BY status
        ORDER BY status ASC;
        """,
        (session_id,),
    )
    tasks_by_status = {str(row["status"]): int(row["count"]) for row in cur.fetchall()}
    total_tasks = sum(tasks_by_status.values())

    session_name = ""
    cur.execute("SELECT name FROM sessions WHERE id = %s;", (session_id,))
    session_row = cur.fetchone()
    if session_row:
        session_name = str(session_row.get("name") or "").strip()

    summary_parts = [f"Session: {session_name or session_id}", f"tasks={total_tasks}"]
    if tasks_by_status:
        summary_parts.append(
            "statuses=" + ", ".join(f"{key}:{value}" for key, value in sorted(tasks_by_status.items()))
        )
    if preferences:
        summary_parts.append(f"preferences={len(preferences)}")
    if open_loops:
        summary_parts.append(f"open_loops={len(open_loops)}")
    summary_text = " | ".join(summary_parts)

    cur.execute(
        """
        INSERT INTO session_states (session_id, summary_text, preferences, open_loops)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (session_id) DO UPDATE
        SET summary_text = EXCLUDED.summary_text,
            preferences = EXCLUDED.preferences,
            open_loops = EXCLUDED.open_loops,
            updated_at = CURRENT_TIMESTAMP
        RETURNING session_id, summary_text, preferences, open_loops, created_at, updated_at;
        """,
        (
            session_id,
            summary_text,
            safe_json_dumps(preferences),
            safe_json_dumps(open_loops),
        ),
    )
    return serialize_session_state_row(cur.fetchone())


def ensure_sessions_tables(cur):
    cur.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS session_memories (
        id SERIAL PRIMARY KEY,
        session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        category VARCHAR(100) NOT NULL,
        content TEXT NOT NULL,
        importance INTEGER NOT NULL DEFAULT 3,
        source_task_id INTEGER REFERENCES task_runs(id) ON DELETE SET NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS session_states (
        session_id INTEGER PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
        summary_text TEXT NOT NULL DEFAULT '',
        preferences JSONB NOT NULL DEFAULT '[]'::jsonb,
        open_loops JSONB NOT NULL DEFAULT '[]'::jsonb,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS session_reviews (
        id SERIAL PRIMARY KEY,
        session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        review_kind VARCHAR(100) NOT NULL DEFAULT 'manual',
        summary_text TEXT NOT NULL,
        highlights JSONB NOT NULL DEFAULT '[]'::jsonb,
        open_loops JSONB NOT NULL DEFAULT '[]'::jsonb,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)


@app.get("/")
def root():
    return {"message": "ai assistant api is running"}


@app.post("/init-db")
def init_db(x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
    conn = get_conn()
    cur = conn.cursor()
    actor = require_actor_permission(cur, x_actor_name, "admin")

    ensure_sessions_tables(cur)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS task_runs (
        id SERIAL PRIMARY KEY,
        user_input TEXT NOT NULL,
        status VARCHAR(50) NOT NULL DEFAULT 'pending',
        result TEXT,
        error_message TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    cur.execute("""
    ALTER TABLE task_runs
    ADD COLUMN IF NOT EXISTS current_step INTEGER;
    """)

    cur.execute("""
    ALTER TABLE task_runs
    ADD COLUMN IF NOT EXISTS checkpoint_path TEXT;
    """)

    cur.execute("""
    ALTER TABLE task_runs
    ADD COLUMN IF NOT EXISTS session_id INTEGER REFERENCES sessions(id) ON DELETE SET NULL;
    """)

    cur.execute("""
    ALTER TABLE task_runs
    ADD COLUMN IF NOT EXISTS created_by_actor TEXT;
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS task_steps (
        id SERIAL PRIMARY KEY,
        task_id INTEGER NOT NULL REFERENCES task_runs(id) ON DELETE CASCADE,
        step_order INTEGER NOT NULL,
        step_name VARCHAR(255) NOT NULL,
        status VARCHAR(50) NOT NULL DEFAULT 'pending',
        input_payload TEXT,
        output_payload TEXT,
        error_message TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    cur.execute("""
    ALTER TABLE task_steps
    ADD COLUMN IF NOT EXISTS tool_name TEXT;
    """)

    cur.execute("""
    ALTER TABLE task_steps
    ADD COLUMN IF NOT EXISTS output_data TEXT;
    """)

    cur.execute("""
    ALTER TABLE task_steps
    ADD COLUMN IF NOT EXISTS error_strategy TEXT DEFAULT 'fail';
    """)

    cur.execute("""
    ALTER TABLE task_steps
    ADD COLUMN IF NOT EXISTS run_if TEXT;
    """)

    cur.execute("""
    ALTER TABLE task_steps
    ADD COLUMN IF NOT EXISTS skip_if TEXT;
    """)

    cur.execute("""
    ALTER TABLE task_steps
    ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0;
    """)

    cur.execute("""
    ALTER TABLE task_steps
    ADD COLUMN IF NOT EXISTS max_retries INTEGER NOT NULL DEFAULT 0;
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS approvals (
        id SERIAL PRIMARY KEY,
        task_id INTEGER NOT NULL REFERENCES task_runs(id) ON DELETE CASCADE,
        step_order INTEGER NOT NULL,
        step_name VARCHAR(255) NOT NULL,
        tool_name TEXT NOT NULL,
        input_payload TEXT,
        reason TEXT NOT NULL,
        status VARCHAR(50) NOT NULL DEFAULT 'pending',
        decision_note TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        decided_at TIMESTAMP
    );
    """)

    seed_default_risk_policies(cur)
    ensure_audit_logs_table(cur)
    seed_default_access_actors(cur)
    seed_default_access_quotas(cur)
    seed_default_tool_registry(cur)
    seed_default_model_providers(cur)
    seed_default_model_routes(cur)
    ensure_change_requests_table(cur)

    conn.commit()
    cur.close()
    conn.close()

    logger.info("database initialized actor=%s", actor["actor_name"])

    return {"message": "database initialized"}


@app.get("/risk-policies")
def list_risk_policies():
    conn = get_conn()
    cur = conn.cursor()
    seed_default_risk_policies(cur)
    seed_default_access_actors(cur)
    conn.commit()

    cur.execute(
        """
        SELECT policy_key, value_type, policy_value, description, created_at, updated_at
        FROM risk_policies
        ORDER BY policy_key ASC;
        """
    )
    rows = [deserialize_policy_row(row) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


@app.get("/tools")
def list_tool_registry(x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
    conn = get_conn()
    cur = conn.cursor()
    require_actor_permission(cur, x_actor_name, "read")
    seed_default_tool_registry(cur)
    conn.commit()
    cur.execute(
        """
        SELECT tool_name, enabled, risk_level, description, created_at, updated_at
        FROM tool_registry_entries
        ORDER BY tool_name ASC;
        """
    )
    rows = [serialize_tool_registry_row(row) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


@app.put("/tools/{tool_name}")
def update_tool_registry(
    tool_name: str,
    request: ToolRegistryUpdate,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    normalized_tool_name = tool_name.strip()
    normalized_risk_level = request.risk_level.strip().lower()
    if normalized_risk_level not in {"low", "medium", "high"}:
        raise HTTPException(status_code=400, detail=f"Unsupported risk level: {request.risk_level}")

    conn = get_conn()
    cur = conn.cursor()
    actor = require_actor_permission(cur, x_actor_name, "admin")
    enforce_change_gate_for_direct_update("tool_registry")
    seed_default_tool_registry(cur)
    cur.execute(
        """
        UPDATE tool_registry_entries
        SET enabled = %s,
            risk_level = %s,
            description = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE tool_name = %s
        RETURNING tool_name, enabled, risk_level, description, created_at, updated_at;
        """,
        (bool(request.enabled), normalized_risk_level, request.description.strip(), normalized_tool_name),
    )
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail=f"Tool not found: {normalized_tool_name}")
    insert_audit_log(
        cur,
        "tool_registry.update",
        actor["actor_name"],
        None,
        {
            "tool_name": normalized_tool_name,
            "enabled": bool(request.enabled),
            "risk_level": normalized_risk_level,
        },
    )
    conn.commit()
    cur.close()
    conn.close()
    logger.info(
        "tool registry updated tool_name=%s enabled=%s risk_level=%s actor=%s",
        normalized_tool_name,
        bool(request.enabled),
        normalized_risk_level,
        actor["actor_name"],
    )
    return serialize_tool_registry_row(row)


@app.get("/model-routes")
def list_model_routes(x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
    conn = get_conn()
    cur = conn.cursor()
    require_actor_permission(cur, x_actor_name, "read")
    seed_default_model_providers(cur)
    seed_default_model_routes(cur)
    conn.commit()
    cur.execute(
        """
        SELECT route_name, provider, model_name, temperature, max_tokens, enabled, description, created_at, updated_at
        FROM model_routes
        ORDER BY route_name ASC;
        """
    )
    rows = [serialize_model_route_row(row) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


@app.get("/model-providers")
def list_model_providers(x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
    conn = get_conn()
    cur = conn.cursor()
    require_actor_permission(cur, x_actor_name, "read")
    seed_default_model_providers(cur)
    conn.commit()
    cur.execute(
        """
        SELECT provider_name, driver, base_url, api_key_env, enabled, description, created_at, updated_at
        FROM model_providers
        ORDER BY provider_name ASC;
        """
    )
    rows = [serialize_model_provider_row(row) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


@app.put("/model-routes/{route_name}")
def update_model_route(
    route_name: str,
    request: ModelRouteUpdate,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    normalized_route_name = route_name.strip()
    normalized_provider = request.provider.strip()
    normalized_model_name = request.model_name.strip()
    if not normalized_provider:
        raise HTTPException(status_code=400, detail="provider is required")
    if not normalized_model_name:
        raise HTTPException(status_code=400, detail="model_name is required")
    if request.max_tokens <= 0:
        raise HTTPException(status_code=400, detail="max_tokens must be positive")

    conn = get_conn()
    cur = conn.cursor()
    actor = require_actor_permission(cur, x_actor_name, "admin")
    enforce_change_gate_for_direct_update("model_route")
    seed_default_model_providers(cur)
    seed_default_model_routes(cur)
    cur.execute("SELECT provider_name FROM model_providers WHERE provider_name = %s;", (normalized_provider,))
    if not cur.fetchone():
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail=f"Model provider not found: {normalized_provider}")
    cur.execute(
        """
        UPDATE model_routes
        SET provider = %s,
            model_name = %s,
            temperature = %s,
            max_tokens = %s,
            enabled = %s,
            description = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE route_name = %s
        RETURNING route_name, provider, model_name, temperature, max_tokens, enabled, description, created_at, updated_at;
        """,
        (
            normalized_provider,
            normalized_model_name,
            float(request.temperature),
            int(request.max_tokens),
            bool(request.enabled),
            request.description.strip(),
            normalized_route_name,
        ),
    )
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail=f"Model route not found: {normalized_route_name}")
    insert_audit_log(
        cur,
        "model_route.update",
        actor["actor_name"],
        None,
        {
            "route_name": normalized_route_name,
            "provider": normalized_provider,
            "model_name": normalized_model_name,
            "temperature": float(request.temperature),
            "max_tokens": int(request.max_tokens),
            "enabled": bool(request.enabled),
        },
    )
    conn.commit()
    cur.close()
    conn.close()
    logger.info(
        "model route updated route_name=%s provider=%s model_name=%s enabled=%s actor=%s",
        normalized_route_name,
        normalized_provider,
        normalized_model_name,
        bool(request.enabled),
        actor["actor_name"],
    )
    return serialize_model_route_row(row)


@app.put("/model-providers/{provider_name}")
def update_model_provider(
    provider_name: str,
    request: ModelProviderUpdate,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    normalized_provider_name = provider_name.strip()
    normalized_driver = request.driver.strip()
    normalized_base_url = request.base_url.strip()
    normalized_api_key_env = request.api_key_env.strip()
    if not normalized_provider_name:
        raise HTTPException(status_code=400, detail="provider_name is required")
    if normalized_driver not in {"openai_compatible"}:
        raise HTTPException(status_code=400, detail=f"Unsupported provider driver: {normalized_driver}")
    if not normalized_base_url:
        raise HTTPException(status_code=400, detail="base_url is required")
    if not normalized_api_key_env:
        raise HTTPException(status_code=400, detail="api_key_env is required")

    conn = get_conn()
    cur = conn.cursor()
    actor = require_actor_permission(cur, x_actor_name, "admin")
    enforce_change_gate_for_direct_update("model_provider")
    seed_default_model_providers(cur)
    cur.execute(
        """
        INSERT INTO model_providers (provider_name, driver, base_url, api_key_env, enabled, description)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (provider_name)
        DO UPDATE SET driver = EXCLUDED.driver,
                      base_url = EXCLUDED.base_url,
                      api_key_env = EXCLUDED.api_key_env,
                      enabled = EXCLUDED.enabled,
                      description = EXCLUDED.description,
                      updated_at = CURRENT_TIMESTAMP
        RETURNING provider_name, driver, base_url, api_key_env, enabled, description, created_at, updated_at;
        """,
        (
            normalized_provider_name,
            normalized_driver,
            normalized_base_url,
            normalized_api_key_env,
            bool(request.enabled),
            request.description.strip(),
        ),
    )
    row = cur.fetchone()
    insert_audit_log(
        cur,
        "model_provider.update",
        actor["actor_name"],
        None,
        {
            "provider_name": normalized_provider_name,
            "driver": normalized_driver,
            "base_url": normalized_base_url,
            "api_key_env": normalized_api_key_env,
            "enabled": bool(request.enabled),
        },
    )
    conn.commit()
    cur.close()
    conn.close()
    logger.info(
        "model provider updated provider_name=%s driver=%s enabled=%s actor=%s",
        normalized_provider_name,
        normalized_driver,
        bool(request.enabled),
        actor["actor_name"],
    )
    return serialize_model_provider_row(row)


@app.get("/change-requests")
def list_change_requests(
    status: str | None = None,
    target_type: str | None = None,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    conn = get_conn()
    cur = conn.cursor()
    require_actor_permission(cur, x_actor_name, "read")
    ensure_change_requests_table(cur)
    where = []
    params: list[Any] = []
    if status:
        where.append("status = %s")
        params.append(status)
    if target_type:
        where.append("target_type = %s")
        params.append(target_type)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    cur.execute(
        f"""
        SELECT id, target_type, target_key, proposed_payload, rationale, status,
               requested_by_actor, reviewed_by_actor, decision_note, applied_by_actor,
               created_at, reviewed_at, applied_at
        FROM change_requests
        {where_sql}
        ORDER BY id DESC;
        """,
        params,
    )
    rows = [serialize_change_request_row(row) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


@app.post("/change-requests")
def create_change_request(
    request: ChangeRequestCreate,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    target_type = request.target_type.strip()
    target_key = request.target_key.strip()
    if target_type not in SUPPORTED_CHANGE_TARGET_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported change target type: {target_type}")
    if not target_key:
        raise HTTPException(status_code=400, detail="target_key is required")

    conn = get_conn()
    cur = conn.cursor()
    actor = require_actor_permission(cur, x_actor_name, "operate")
    ensure_change_requests_table(cur)
    cur.execute(
        """
        INSERT INTO change_requests (
            target_type, target_key, proposed_payload, rationale, status, requested_by_actor
        )
        VALUES (%s, %s, %s, %s, 'pending', %s)
        RETURNING id, target_type, target_key, proposed_payload, rationale, status,
                  requested_by_actor, reviewed_by_actor, decision_note, applied_by_actor,
                  created_at, reviewed_at, applied_at;
        """,
        (
            target_type,
            target_key,
            safe_json_dumps(request.proposed_payload),
            request.rationale.strip(),
            actor["actor_name"],
        ),
    )
    row = cur.fetchone()
    insert_audit_log(
        cur,
        "change_request.create",
        actor["actor_name"],
        None,
        {"change_request_id": row["id"], "target_type": target_type, "target_key": target_key},
    )
    conn.commit()
    cur.close()
    conn.close()
    return serialize_change_request_row(row)


@app.post("/change-requests/{change_request_id}/approve")
def approve_change_request(
    change_request_id: int,
    request: ChangeRequestDecision,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    conn = get_conn()
    cur = conn.cursor()
    actor = require_actor_permission(cur, x_actor_name, "admin")
    change_request = get_change_request_or_404(cur, change_request_id)
    if change_request["status"] != "pending":
        raise HTTPException(status_code=400, detail=f"Change request is not pending: {change_request['status']}")
    cur.execute(
        """
        UPDATE change_requests
        SET status = 'approved',
            reviewed_by_actor = %s,
            decision_note = %s,
            reviewed_at = CURRENT_TIMESTAMP
        WHERE id = %s
        RETURNING id, target_type, target_key, proposed_payload, rationale, status,
                  requested_by_actor, reviewed_by_actor, decision_note, applied_by_actor,
                  created_at, reviewed_at, applied_at;
        """,
        (actor["actor_name"], request.note.strip(), change_request_id),
    )
    row = cur.fetchone()
    insert_audit_log(cur, "change_request.approve", actor["actor_name"], None, {"change_request_id": change_request_id})
    conn.commit()
    cur.close()
    conn.close()
    return serialize_change_request_row(row)


@app.post("/change-requests/{change_request_id}/reject")
def reject_change_request(
    change_request_id: int,
    request: ChangeRequestDecision,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    conn = get_conn()
    cur = conn.cursor()
    actor = require_actor_permission(cur, x_actor_name, "admin")
    change_request = get_change_request_or_404(cur, change_request_id)
    if change_request["status"] != "pending":
        raise HTTPException(status_code=400, detail=f"Change request is not pending: {change_request['status']}")
    cur.execute(
        """
        UPDATE change_requests
        SET status = 'rejected',
            reviewed_by_actor = %s,
            decision_note = %s,
            reviewed_at = CURRENT_TIMESTAMP
        WHERE id = %s
        RETURNING id, target_type, target_key, proposed_payload, rationale, status,
                  requested_by_actor, reviewed_by_actor, decision_note, applied_by_actor,
                  created_at, reviewed_at, applied_at;
        """,
        (actor["actor_name"], request.note.strip(), change_request_id),
    )
    row = cur.fetchone()
    insert_audit_log(cur, "change_request.reject", actor["actor_name"], None, {"change_request_id": change_request_id})
    conn.commit()
    cur.close()
    conn.close()
    return serialize_change_request_row(row)


@app.post("/change-requests/{change_request_id}/apply")
def apply_change_request(
    change_request_id: int,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    conn = get_conn()
    cur = conn.cursor()
    actor = require_actor_permission(cur, x_actor_name, "admin")
    change_request = get_change_request_or_404(cur, change_request_id)
    if change_request["status"] != "approved":
        raise HTTPException(status_code=400, detail=f"Change request is not approved: {change_request['status']}")
    apply_change_request_payload(
        cur,
        change_request["target_type"],
        change_request["target_key"],
        change_request["proposed_payload"] or {},
    )
    cur.execute(
        """
        UPDATE change_requests
        SET status = 'applied',
            applied_by_actor = %s,
            applied_at = CURRENT_TIMESTAMP
        WHERE id = %s
        RETURNING id, target_type, target_key, proposed_payload, rationale, status,
                  requested_by_actor, reviewed_by_actor, decision_note, applied_by_actor,
                  created_at, reviewed_at, applied_at;
        """,
        (actor["actor_name"], change_request_id),
    )
    row = cur.fetchone()
    insert_audit_log(
        cur,
        "change_request.apply",
        actor["actor_name"],
        None,
        {"change_request_id": change_request_id, "target_type": change_request["target_type"], "target_key": change_request["target_key"]},
    )
    conn.commit()
    cur.close()
    conn.close()
    return serialize_change_request_row(row)


@app.get("/access/actors")
def list_access_actors(x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
    conn = get_conn()
    cur = conn.cursor()
    require_actor_permission(cur, x_actor_name, "read")
    seed_default_access_actors(cur)
    conn.commit()
    cur.execute(
        """
        SELECT actor_name, role, description, created_at, updated_at
        FROM access_actors
        ORDER BY actor_name ASC;
        """
    )
    rows = [serialize_access_actor_row(row) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


@app.get("/access/quotas")
def list_access_quotas(x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
    conn = get_conn()
    cur = conn.cursor()
    require_actor_permission(cur, x_actor_name, "read")
    seed_default_access_quotas(cur)
    conn.commit()
    cur.execute(
        """
        SELECT actor_name, daily_task_limit, active_task_limit, created_at, updated_at
        FROM access_quotas
        ORDER BY actor_name ASC;
        """
    )
    rows = [serialize_access_quota_row(row) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


@app.get("/access/quota-usage")
def list_access_quota_usage(x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
    conn = get_conn()
    cur = conn.cursor()
    require_actor_permission(cur, x_actor_name, "read")
    seed_default_access_quotas(cur)
    conn.commit()
    cur.execute(
        """
        SELECT
            a.actor_name,
            a.role,
            q.daily_task_limit,
            q.active_task_limit,
            COALESCE(d.daily_task_count, 0) AS daily_task_count,
            COALESCE(ac.active_task_count, 0) AS active_task_count
        FROM access_actors a
        JOIN access_quotas q ON q.actor_name = a.actor_name
        LEFT JOIN (
            SELECT created_by_actor, COUNT(*) AS daily_task_count
            FROM task_runs
            WHERE created_by_actor IS NOT NULL
              AND DATE(created_at) = CURRENT_DATE
            GROUP BY created_by_actor
        ) d ON d.created_by_actor = a.actor_name
        LEFT JOIN (
            SELECT created_by_actor, COUNT(*) AS active_task_count
            FROM task_runs
            WHERE created_by_actor IS NOT NULL
              AND status NOT IN ('completed', 'failed')
            GROUP BY created_by_actor
        ) ac ON ac.created_by_actor = a.actor_name
        ORDER BY a.actor_name ASC;
        """
    )
    rows = []
    for row in cur.fetchall():
        daily_limit = int(row["daily_task_limit"])
        active_limit = int(row["active_task_limit"])
        daily_count = int(row["daily_task_count"])
        active_count = int(row["active_task_count"])
        rows.append(
            {
                "actor_name": row["actor_name"],
                "role": row["role"],
                "daily_task_limit": daily_limit,
                "active_task_limit": active_limit,
                "daily_task_count": daily_count,
                "active_task_count": active_count,
                "daily_remaining": max(daily_limit - daily_count, 0),
                "active_remaining": max(active_limit - active_count, 0),
            }
        )
    cur.close()
    conn.close()
    return rows


class AccessActorUpdate(BaseModel):
    role: str
    description: str = ""


@app.put("/access/actors/{actor_name}")
def update_access_actor(
    actor_name: str,
    request: AccessActorUpdate,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    normalized_role = request.role.strip().lower()
    if normalized_role not in ACCESS_ROLE_PERMISSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported role: {request.role}")

    normalized_actor_name = actor_name.strip()
    if not normalized_actor_name:
        raise HTTPException(status_code=400, detail="Actor name cannot be empty")

    conn = get_conn()
    cur = conn.cursor()
    actor = require_actor_permission(cur, x_actor_name, "admin")
    enforce_change_gate_for_direct_update("access_actor")
    seed_default_access_actors(cur)
    cur.execute(
        """
        INSERT INTO access_actors (actor_name, role, description)
        VALUES (%s, %s, %s)
        ON CONFLICT (actor_name) DO UPDATE
        SET role = EXCLUDED.role,
            description = EXCLUDED.description,
            updated_at = CURRENT_TIMESTAMP
        RETURNING actor_name, role, description, created_at, updated_at;
        """,
        (normalized_actor_name, normalized_role, request.description.strip()),
    )
    row = cur.fetchone()
    upsert_default_access_quota(cur, normalized_actor_name, normalized_role)
    insert_audit_log(
        cur,
        "access.actor_update",
        actor["actor_name"],
        None,
        {
            "target_actor_name": normalized_actor_name,
            "role": normalized_role,
            "description": request.description.strip(),
        },
    )
    conn.commit()
    cur.close()
    conn.close()
    logger.info("access actor updated actor_name=%s role=%s by=%s", normalized_actor_name, normalized_role, actor["actor_name"])
    return serialize_access_actor_row(row)


@app.put("/access/quotas/{actor_name}")
def update_access_quota(
    actor_name: str,
    request: AccessQuotaUpdate,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    normalized_actor_name = actor_name.strip()
    if not normalized_actor_name:
        raise HTTPException(status_code=400, detail="Actor name cannot be empty")
    if request.daily_task_limit < 0 or request.active_task_limit < 0:
        raise HTTPException(status_code=400, detail="Quota values must be non-negative")

    conn = get_conn()
    cur = conn.cursor()
    actor = require_actor_permission(cur, x_actor_name, "admin")
    enforce_change_gate_for_direct_update("access_quota")
    seed_default_access_quotas(cur)
    cur.execute("SELECT actor_name FROM access_actors WHERE actor_name = %s;", (normalized_actor_name,))
    if not cur.fetchone():
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail=f"Actor not found: {normalized_actor_name}")

    cur.execute(
        """
        INSERT INTO access_quotas (actor_name, daily_task_limit, active_task_limit)
        VALUES (%s, %s, %s)
        ON CONFLICT (actor_name) DO UPDATE
        SET daily_task_limit = EXCLUDED.daily_task_limit,
            active_task_limit = EXCLUDED.active_task_limit,
            updated_at = CURRENT_TIMESTAMP
        RETURNING actor_name, daily_task_limit, active_task_limit, created_at, updated_at;
        """,
        (normalized_actor_name, int(request.daily_task_limit), int(request.active_task_limit)),
    )
    row = cur.fetchone()
    insert_audit_log(
        cur,
        "access.quota_update",
        actor["actor_name"],
        None,
        {
            "target_actor_name": normalized_actor_name,
            "daily_task_limit": int(request.daily_task_limit),
            "active_task_limit": int(request.active_task_limit),
        },
    )
    conn.commit()
    cur.close()
    conn.close()
    logger.info(
        "access quota updated actor_name=%s daily_task_limit=%s active_task_limit=%s by=%s",
        normalized_actor_name,
        request.daily_task_limit,
        request.active_task_limit,
        actor["actor_name"],
    )
    return serialize_access_quota_row(row)


@app.put("/risk-policies/{policy_key}")
def update_risk_policy(
    policy_key: str,
    request: RiskPolicyUpdate,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    value_type, serialized_value = validate_policy_value(policy_key, request.policy_value)

    conn = get_conn()
    cur = conn.cursor()
    actor = require_actor_permission(cur, x_actor_name, "admin")
    enforce_change_gate_for_direct_update("risk_policy")
    seed_default_risk_policies(cur)
    cur.execute(
        """
        UPDATE risk_policies
        SET value_type = %s,
            policy_value = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE policy_key = %s
        RETURNING policy_key, value_type, policy_value, description, created_at, updated_at;
        """,
        (value_type, serialized_value, policy_key),
    )
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Risk policy not found")

    insert_audit_log(
        cur,
        "risk.update",
        actor["actor_name"],
        None,
        {
            "policy_key": policy_key,
            "policy_value": request.policy_value,
            "role": actor["role"],
        },
    )
    conn.commit()
    cur.close()
    conn.close()

    logger.info("risk policy updated policy_key=%s actor=%s", policy_key, actor["actor_name"])
    return deserialize_policy_row(row)


@app.get("/audit-logs")
def list_audit_logs(task_id: int | None = None, event_type: str | None = None, limit: int | None = 50):
    conn = get_conn()
    cur = conn.cursor()
    ensure_audit_logs_table(cur)

    where_clauses = []
    params = []
    if task_id:
        where_clauses.append("task_id = %s")
        params.append(task_id)
    if event_type:
        where_clauses.append("event_type = %s")
        params.append(event_type)

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    cur.execute(
        f"""
        SELECT id, task_id, event_type, actor, details, created_at
        FROM audit_logs
        {where_sql}
        ORDER BY id DESC
        LIMIT %s;
        """,
        (*params, limit),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    for row in rows:
        row["details"] = parse_maybe_json(row.get("details"))
    return rows


@app.get("/runtime-metadata")
def get_runtime_metadata():
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runtime_stage": "stage2",
        "step_request_protocol": {
            "version": STEP_REQUEST_PROTOCOL_VERSION,
            "base_type": "StepExecutionRequest",
            "base_fields": STEP_EXECUTION_REQUEST_FIELDS,
            "enriched_type": "EnrichedStepExecutionRequest",
            "enriched_extra_fields": ENRICHED_STEP_EXECUTION_REQUEST_EXTRA_FIELDS,
        },
    }


@app.get("/monitor/overview")
def get_monitor_overview():
    conn = get_conn()
    cur = conn.cursor()
    ensure_audit_logs_table(cur)
    seed_default_risk_policies(cur)
    seed_default_access_actors(cur)
    seed_default_access_quotas(cur)
    seed_default_tool_registry(cur)
    seed_default_model_providers(cur)
    seed_default_model_routes(cur)
    ensure_change_requests_table(cur)
    conn.commit()

    cur.execute(
        """
        SELECT status, COUNT(*) AS count
        FROM task_runs
        GROUP BY status
        ORDER BY status ASC;
        """
    )
    task_rows = cur.fetchall()
    tasks_by_status = {str(row["status"]): int(row["count"]) for row in task_rows}

    cur.execute("SELECT COUNT(*) AS count FROM task_runs;")
    total_tasks = int(cur.fetchone()["count"])

    cur.execute("SELECT COUNT(*) AS count FROM sessions;")
    total_sessions = int(cur.fetchone()["count"])

    cur.execute("SELECT COUNT(*) AS count FROM session_memories;")
    total_memories = int(cur.fetchone()["count"])

    cur.execute("SELECT COUNT(*) AS count FROM session_states;")
    total_session_states = int(cur.fetchone()["count"])

    cur.execute("SELECT COUNT(*) AS count FROM session_reviews;")
    total_session_reviews = int(cur.fetchone()["count"])

    cur.execute(
        """
        SELECT COUNT(*) AS count
        FROM session_reviews
        WHERE review_kind = 'daily'
          AND DATE(created_at) = CURRENT_DATE;
        """
    )
    daily_reviews_today = int(cur.fetchone()["count"])

    cur.execute("SELECT COUNT(*) AS count FROM approvals WHERE status = 'pending';")
    pending_approvals = int(cur.fetchone()["count"])

    cur.execute("SELECT COUNT(*) AS count FROM risk_policies;")
    risk_policy_count = int(cur.fetchone()["count"])

    cur.execute("SELECT COUNT(*) AS count FROM tool_registry_entries;")
    tool_registry_count = int(cur.fetchone()["count"])

    cur.execute("SELECT COUNT(*) AS count FROM tool_registry_entries WHERE enabled = FALSE;")
    disabled_tool_count = int(cur.fetchone()["count"])

    cur.execute("SELECT COUNT(*) AS count FROM model_routes;")
    model_route_count = int(cur.fetchone()["count"])

    cur.execute("SELECT COUNT(*) AS count FROM model_routes WHERE enabled = FALSE;")
    disabled_model_route_count = int(cur.fetchone()["count"])

    cur.execute("SELECT COUNT(*) AS count FROM model_providers;")
    model_provider_count = int(cur.fetchone()["count"])

    cur.execute("SELECT COUNT(*) AS count FROM model_providers WHERE enabled = FALSE;")
    disabled_model_provider_count = int(cur.fetchone()["count"])

    cur.execute("SELECT COUNT(*) AS count FROM change_requests;")
    total_change_requests = int(cur.fetchone()["count"])

    cur.execute("SELECT COUNT(*) AS count FROM change_requests WHERE status = 'pending';")
    pending_change_requests = int(cur.fetchone()["count"])

    cur.execute("SELECT COUNT(*) AS count FROM access_actors;")
    access_actor_count = int(cur.fetchone()["count"])

    cur.execute("SELECT COUNT(*) AS count FROM access_quotas;")
    access_quota_count = int(cur.fetchone()["count"])

    cur.execute(
        """
        SELECT COUNT(*) AS count
        FROM (
            SELECT a.actor_name
            FROM access_actors a
            JOIN access_quotas q ON q.actor_name = a.actor_name
            LEFT JOIN (
                SELECT created_by_actor, COUNT(*) AS daily_task_count
                FROM task_runs
                WHERE created_by_actor IS NOT NULL
                  AND DATE(created_at) = CURRENT_DATE
                GROUP BY created_by_actor
            ) d ON d.created_by_actor = a.actor_name
            LEFT JOIN (
                SELECT created_by_actor, COUNT(*) AS active_task_count
                FROM task_runs
                WHERE created_by_actor IS NOT NULL
                  AND status NOT IN ('completed', 'failed')
                GROUP BY created_by_actor
            ) ac ON ac.created_by_actor = a.actor_name
            WHERE COALESCE(d.daily_task_count, 0) >= q.daily_task_limit
               OR COALESCE(ac.active_task_count, 0) >= q.active_task_limit
        ) quota_pressure;
        """
    )
    quota_pressure_count = int(cur.fetchone()["count"])

    cur.execute(
        """
        SELECT role, COUNT(*) AS count
        FROM access_actors
        GROUP BY role
        ORDER BY role ASC;
        """
    )
    actors_by_role = {str(row["role"]): int(row["count"]) for row in cur.fetchall()}

    cur.execute(
        """
        SELECT COUNT(*) AS count
        FROM task_runs
        WHERE checkpoint_path IS NOT NULL AND checkpoint_path != '';
        """
    )
    checkpointed_tasks = int(cur.fetchone()["count"])

    cur.execute(
        """
        SELECT id, task_id, event_type, actor, details, created_at
        FROM audit_logs
        ORDER BY id DESC
        LIMIT 8;
        """
    )
    recent_audit_logs = list(cur.fetchall())
    for row in recent_audit_logs:
        row["details"] = parse_maybe_json(row.get("details"))

    cur.execute(
        """
        SELECT id, user_input, status, updated_at
        FROM task_runs
        ORDER BY updated_at DESC, id DESC
        LIMIT 8;
        """
    )
    recent_tasks = list(cur.fetchall())

    cur.execute(
        """
        SELECT id, session_id, review_kind, summary_text, highlights, open_loops, created_at
        FROM session_reviews
        ORDER BY id DESC
        LIMIT 5;
        """
    )
    recent_reviews = [serialize_session_review_row(row) for row in cur.fetchall()]

    cur.execute(
        """
        SELECT MAX(created_at) AS last_daily_review_at
        FROM session_reviews
        WHERE review_kind = 'daily';
        """
    )
    last_daily_review_at_row = cur.fetchone()
    last_daily_review_at = last_daily_review_at_row["last_daily_review_at"] if last_daily_review_at_row else None

    cur.close()
    conn.close()

    redis_stats = get_redis_monitor_stats()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "task_metrics": {
            "total_tasks": total_tasks,
            "checkpointed_tasks": checkpointed_tasks,
            "tasks_by_status": tasks_by_status,
        },
        "session_metrics": {
            "total_sessions": total_sessions,
            "total_memories": total_memories,
            "total_session_states": total_session_states,
            "total_session_reviews": total_session_reviews,
        },
        "review_metrics": {
            "daily_reviews_today": daily_reviews_today,
            "last_daily_review_at": last_daily_review_at,
        },
        "approval_metrics": {
            "pending_approvals": pending_approvals,
        },
        "queue_metrics": redis_stats,
        "risk_metrics": {
            "risk_policy_count": risk_policy_count,
        },
        "tool_metrics": {
            "tool_registry_count": tool_registry_count,
            "disabled_tool_count": disabled_tool_count,
        },
        "model_metrics": {
            "model_provider_count": model_provider_count,
            "disabled_model_provider_count": disabled_model_provider_count,
            "model_route_count": model_route_count,
            "disabled_model_route_count": disabled_model_route_count,
        },
        "change_metrics": {
            "total_change_requests": total_change_requests,
            "pending_change_requests": pending_change_requests,
            "enforced_target_types": sorted(DEFAULT_ENFORCED_CHANGE_TARGET_TYPES),
            "enforced_target_count": len(DEFAULT_ENFORCED_CHANGE_TARGET_TYPES),
        },
        "access_metrics": {
            "actor_count": access_actor_count,
            "quota_count": access_quota_count,
            "quota_pressure_count": quota_pressure_count,
            "actors_by_role": actors_by_role,
        },
        "runtime_metadata": {
            "step_request_protocol_version": STEP_REQUEST_PROTOCOL_VERSION,
        },
        "recent_audit_logs": recent_audit_logs,
        "recent_tasks": recent_tasks,
        "recent_reviews": recent_reviews,
    }


@app.post("/sessions")
def create_session(session: SessionCreate, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
    name = session.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Session name cannot be empty")

    conn = get_conn()
    cur = conn.cursor()
    actor = require_actor_permission(cur, x_actor_name, "operate")
    cur.execute(
        """
        INSERT INTO sessions (name, description)
        VALUES (%s, %s)
        RETURNING id, name, description, created_at, updated_at;
        """,
        (name, session.description.strip()),
    )
    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()

    record_audit_event("session.create", actor["actor_name"], None, {"session_id": row["id"], "name": row["name"], "role": actor["role"]})
    logger.info("session created id=%s name=%s actor=%s", row["id"], row["name"], actor["actor_name"])
    return serialize_session_row(row)


@app.get("/sessions")
def list_sessions():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, name, description, created_at, updated_at
        FROM sessions
        ORDER BY id DESC;
        """
    )
    rows = [serialize_session_row(row) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


@app.get("/sessions/{session_id}")
def get_session(session_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, name, description, created_at, updated_at
        FROM sessions
        WHERE id = %s;
        """,
        (session_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    return serialize_session_row(row)


@app.get("/sessions/{session_id}/tasks")
def list_session_tasks(session_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM sessions WHERE id = %s;", (session_id,))
    if not cur.fetchone():
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Session not found")

    cur.execute(
        """
        SELECT
            id,
            session_id,
            created_by_actor,
            user_input,
            status,
            result,
            error_message,
            current_step,
            checkpoint_path,
            created_at,
            updated_at
        FROM task_runs
        WHERE session_id = %s
        ORDER BY id DESC;
        """,
        (session_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


@app.get("/sessions/{session_id}/summary")
def get_session_summary(session_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, name, description, created_at, updated_at
        FROM sessions
        WHERE id = %s;
        """,
        (session_id,),
    )
    session_row = cur.fetchone()
    if not session_row:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Session not found")

    cur.execute(
        """
        SELECT status, COUNT(*) AS count
        FROM task_runs
        WHERE session_id = %s
        GROUP BY status
        ORDER BY status ASC;
        """,
        (session_id,),
    )
    tasks_by_status = {str(row["status"]): int(row["count"]) for row in cur.fetchall()}

    cur.execute("SELECT COUNT(*) AS count FROM task_runs WHERE session_id = %s;", (session_id,))
    total_tasks = int(cur.fetchone()["count"])

    cur.execute("SELECT COUNT(*) AS count FROM session_memories WHERE session_id = %s;", (session_id,))
    total_memories = int(cur.fetchone()["count"])

    cur.execute(
        """
        SELECT category, COUNT(*) AS count
        FROM session_memories
        WHERE session_id = %s
        GROUP BY category
        ORDER BY category ASC;
        """,
        (session_id,),
    )
    memories_by_category = {str(row["category"]): int(row["count"]) for row in cur.fetchall()}

    cur.execute(
        """
        SELECT session_id, summary_text, preferences, open_loops, created_at, updated_at
        FROM session_states
        WHERE session_id = %s;
        """,
        (session_id,),
    )
    session_state_row = cur.fetchone()

    cur.execute(
        """
        SELECT COUNT(*) AS count
        FROM approvals
        WHERE status = 'pending'
          AND task_id IN (
              SELECT id FROM task_runs WHERE session_id = %s
          );
        """,
        (session_id,),
    )
    pending_approvals = int(cur.fetchone()["count"])

    cur.execute(
        """
        SELECT
            id,
            session_id,
            created_by_actor,
            user_input,
            status,
            result,
            error_message,
            current_step,
            checkpoint_path,
            created_at,
            updated_at
        FROM task_runs
        WHERE session_id = %s
        ORDER BY updated_at DESC, id DESC
        LIMIT 5;
        """,
        (session_id,),
    )
    recent_tasks = cur.fetchall()
    last_task_updated_at = recent_tasks[0]["updated_at"] if recent_tasks else None

    cur.close()
    conn.close()

    return {
        "session": serialize_session_row(session_row),
        "task_metrics": {
            "total_tasks": total_tasks,
            "tasks_by_status": tasks_by_status,
            "last_task_updated_at": last_task_updated_at,
        },
        "memory_metrics": {
            "total_memories": total_memories,
            "by_category": memories_by_category,
        },
        "session_state": serialize_session_state_row(session_state_row) if session_state_row else None,
        "approval_metrics": {
            "pending_approvals": pending_approvals,
        },
        "recent_tasks": recent_tasks,
    }


@app.post("/sessions/{session_id}/reviews")
def create_session_review(
    session_id: int,
    review: SessionReviewCreate,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    conn = get_conn()
    cur = conn.cursor()
    actor = require_actor_permission(cur, x_actor_name, "operate")
    session_row, task_rows, memory_rows, session_state_row = load_session_review_context(cur, session_id)

    built_review = build_session_review(session_row, task_rows, memory_rows, session_state_row, review.note)
    review_kind = review.review_kind.strip() or "manual"
    row = insert_session_review_row(cur, session_id, review_kind, built_review)
    insert_audit_log(
        cur,
        "session.review_create",
        actor["actor_name"],
        None,
        {
            "session_id": session_id,
            "review_id": row["id"],
            "review_kind": review_kind,
            "role": actor["role"],
        },
    )
    conn.commit()
    cur.close()
    conn.close()
    logger.info("session review created session_id=%s review_id=%s kind=%s actor=%s", session_id, row["id"], review_kind, actor["actor_name"])
    return serialize_session_review_row(row)


@app.post("/reviews/daily-run")
def run_daily_reviews(
    request: DailyReviewRunRequest,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    conn = get_conn()
    cur = conn.cursor()
    actor = require_actor_permission(cur, x_actor_name, "admin")

    review_kind = request.review_kind.strip() or "daily"
    session_limit = max(1, min(int(request.session_limit), 100))
    active_within_hours = max(1, min(int(request.active_within_hours), 168))

    cur.execute(
        """
        SELECT DISTINCT s.id
        FROM sessions s
        JOIN task_runs t ON t.session_id = s.id
        WHERE t.updated_at >= CURRENT_TIMESTAMP - (%s * INTERVAL '1 hour')
        ORDER BY s.id DESC
        LIMIT %s;
        """,
        (active_within_hours, session_limit),
    )
    session_ids = [int(row["id"]) for row in cur.fetchall()]

    created: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    review_day_key = datetime.now(timezone.utc).date().isoformat()
    for session_id in session_ids:
        cur.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s));",
            (f"daily-review:{review_kind}:{session_id}:{review_day_key}",),
        )
        if not request.force:
            cur.execute(
                """
                SELECT id
                FROM session_reviews
                WHERE session_id = %s
                  AND review_kind = %s
                  AND DATE(created_at) = CURRENT_DATE
                ORDER BY id DESC
                LIMIT 1;
                """,
                (session_id, review_kind),
            )
            existing = cur.fetchone()
            if existing:
                skipped.append(
                    {
                        "session_id": session_id,
                        "reason": "already_reviewed_today",
                        "review_id": int(existing["id"]),
                    }
                )
                continue

        session_row, task_rows, memory_rows, session_state_row = load_session_review_context(cur, session_id)
        built_review = build_session_review(session_row, task_rows, memory_rows, session_state_row, request.note)
        row = insert_session_review_row(cur, session_id, review_kind, built_review)
        insert_audit_log(
            cur,
            "session.review_create",
            "api",
            None,
            {
                "session_id": session_id,
                "review_id": row["id"],
                "review_kind": review_kind,
                "source": "daily-run",
                "actor_role": actor["role"],
            },
        )
        created.append(
            {
                "session_id": session_id,
                "review_id": int(row["id"]),
                "review_kind": review_kind,
            }
        )

    conn.commit()
    cur.close()
    conn.close()
    logger.info(
        "daily reviews executed review_kind=%s created=%s skipped=%s actor=%s",
        review_kind,
        len(created),
        len(skipped),
        actor["actor_name"],
    )
    return {
        "review_kind": review_kind,
        "active_within_hours": active_within_hours,
        "session_limit": session_limit,
        "created": created,
        "skipped": skipped,
    }


@app.get("/sessions/{session_id}/reviews")
def list_session_reviews(session_id: int, limit: int | None = 20):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM sessions WHERE id = %s;", (session_id,))
    if not cur.fetchone():
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Session not found")

    cur.execute(
        """
        SELECT id, session_id, review_kind, summary_text, highlights, open_loops, created_at
        FROM session_reviews
        WHERE session_id = %s
        ORDER BY id DESC
        LIMIT %s;
        """,
        (session_id, limit or 20),
    )
    rows = [serialize_session_review_row(row) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


@app.get("/sessions/{session_id}/state")
def get_session_state(session_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM sessions WHERE id = %s;", (session_id,))
    if not cur.fetchone():
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Session not found")

    cur.execute(
        """
        SELECT session_id, summary_text, preferences, open_loops, created_at, updated_at
        FROM session_states
        WHERE session_id = %s;
        """,
        (session_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return {
            "session_id": session_id,
            "summary_text": "",
            "preferences": [],
            "open_loops": [],
            "created_at": None,
            "updated_at": None,
        }
    return serialize_session_state_row(row)


@app.put("/sessions/{session_id}/state")
def update_session_state(
    session_id: int,
    state: SessionStateUpdate,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    preferences = [str(item).strip() for item in state.preferences if str(item).strip()]
    open_loops = [str(item).strip() for item in state.open_loops if str(item).strip()]
    summary_text = state.summary_text.strip()

    conn = get_conn()
    cur = conn.cursor()
    actor = require_actor_permission(cur, x_actor_name, "operate")
    cur.execute("SELECT id FROM sessions WHERE id = %s;", (session_id,))
    if not cur.fetchone():
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Session not found")

    cur.execute(
        """
        INSERT INTO session_states (session_id, summary_text, preferences, open_loops)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (session_id) DO UPDATE
        SET summary_text = EXCLUDED.summary_text,
            preferences = EXCLUDED.preferences,
            open_loops = EXCLUDED.open_loops,
            updated_at = CURRENT_TIMESTAMP
        RETURNING session_id, summary_text, preferences, open_loops, created_at, updated_at;
        """,
        (
            session_id,
            summary_text,
            safe_json_dumps(preferences),
            safe_json_dumps(open_loops),
        ),
    )
    row = cur.fetchone()
    insert_audit_log(
        cur,
        "session.state_update",
        actor["actor_name"],
        None,
        {
            "session_id": session_id,
            "preferences_count": len(preferences),
            "open_loops_count": len(open_loops),
            "role": actor["role"],
        },
    )
    conn.commit()
    cur.close()
    conn.close()
    logger.info("session state updated session_id=%s actor=%s", session_id, actor["actor_name"])
    return serialize_session_state_row(row)


@app.post("/sessions/{session_id}/state/rebuild")
def rebuild_session_state(session_id: int, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
    conn = get_conn()
    cur = conn.cursor()
    actor = require_actor_permission(cur, x_actor_name, "operate")
    cur.execute(
        """
        SELECT id, name, description, created_at, updated_at
        FROM sessions
        WHERE id = %s;
        """,
        (session_id,),
    )
    session_row = cur.fetchone()
    if not session_row:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Session not found")

    cur.execute(
        """
        SELECT id, session_id, user_input, status, updated_at
        FROM task_runs
        WHERE session_id = %s
        ORDER BY updated_at DESC, id DESC;
        """,
        (session_id,),
    )
    task_rows = list(cur.fetchall())

    cur.execute(
        """
        SELECT id, session_id, category, content, importance, source_task_id, created_at, updated_at
        FROM session_memories
        WHERE session_id = %s
        ORDER BY importance DESC, id DESC;
        """,
        (session_id,),
    )
    memory_rows = list(cur.fetchall())

    computed_state = compute_session_state_from_rows(session_row, task_rows, memory_rows)
    cur.execute(
        """
        INSERT INTO session_states (session_id, summary_text, preferences, open_loops)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (session_id) DO UPDATE
        SET summary_text = EXCLUDED.summary_text,
            preferences = EXCLUDED.preferences,
            open_loops = EXCLUDED.open_loops,
            updated_at = CURRENT_TIMESTAMP
        RETURNING session_id, summary_text, preferences, open_loops, created_at, updated_at;
        """,
        (
            session_id,
            computed_state["summary_text"],
            safe_json_dumps(computed_state["preferences"]),
            safe_json_dumps(computed_state["open_loops"]),
        ),
    )
    row = cur.fetchone()
    insert_audit_log(
        cur,
        "session.state_rebuild",
        actor["actor_name"],
        None,
        {
            "session_id": session_id,
            "task_count": len(task_rows),
            "memory_count": len(memory_rows),
            "role": actor["role"],
        },
    )
    conn.commit()
    cur.close()
    conn.close()
    logger.info("session state rebuilt session_id=%s actor=%s", session_id, actor["actor_name"])
    return serialize_session_state_row(row)


@app.post("/sessions/{session_id}/memories")
def create_session_memory(
    session_id: int,
    memory: SessionMemoryCreate,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    category = memory.category.strip()
    content = memory.content.strip()
    if not category:
        raise HTTPException(status_code=400, detail="Memory category cannot be empty")
    if not content:
        raise HTTPException(status_code=400, detail="Memory content cannot be empty")
    if memory.importance < 1 or memory.importance > 5:
        raise HTTPException(status_code=400, detail="Memory importance must be between 1 and 5")

    conn = get_conn()
    cur = conn.cursor()
    actor = require_actor_permission(cur, x_actor_name, "operate")
    cur.execute("SELECT id FROM sessions WHERE id = %s;", (session_id,))
    if not cur.fetchone():
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Session not found")

    if memory.source_task_id is not None:
        cur.execute("SELECT id FROM task_runs WHERE id = %s;", (memory.source_task_id,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            raise HTTPException(status_code=404, detail="Source task not found")

    cur.execute(
        """
        INSERT INTO session_memories (session_id, category, content, importance, source_task_id)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id, session_id, category, content, importance, source_task_id, created_at, updated_at;
        """,
        (session_id, category, content, int(memory.importance), memory.source_task_id),
    )
    row = cur.fetchone()
    updated_state = merge_memory_into_session_state(cur, session_id, category, content)
    insert_audit_log(
        cur,
        "session.memory_create",
        actor["actor_name"],
        memory.source_task_id,
        {
            "session_id": session_id,
            "memory_id": row["id"],
            "category": category,
            "importance": int(memory.importance),
            "state_updated": bool(updated_state),
            "role": actor["role"],
        },
    )
    conn.commit()
    cur.close()
    conn.close()
    logger.info("session memory created session_id=%s memory_id=%s category=%s actor=%s", session_id, row["id"], category, actor["actor_name"])
    return serialize_session_memory_row(row)


@app.get("/sessions/{session_id}/memories")
def list_session_memories(session_id: int, category: str | None = None, limit: int | None = 50):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM sessions WHERE id = %s;", (session_id,))
    if not cur.fetchone():
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Session not found")

    params: list[Any] = [session_id]
    where_sql = "WHERE session_id = %s"
    if category:
        where_sql += " AND category = %s"
        params.append(category)
    params.append(limit)

    cur.execute(
        f"""
        SELECT id, session_id, category, content, importance, source_task_id, created_at, updated_at
        FROM session_memories
        {where_sql}
        ORDER BY importance DESC, id DESC
        LIMIT %s;
        """,
        tuple(params),
    )
    rows = [serialize_session_memory_row(row) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


@app.post("/tasks")
def create_task(task: TaskCreate, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
    conn = get_conn()
    cur = conn.cursor()
    actor = require_actor_permission(cur, x_actor_name, "operate")
    quota_snapshot = enforce_task_quota(cur, actor["actor_name"])

    if task.session_id is not None:
        cur.execute("SELECT id FROM sessions WHERE id = %s;", (task.session_id,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            raise HTTPException(status_code=404, detail="Session not found")

    cur.execute(
        """
        INSERT INTO task_runs (user_input, session_id, created_by_actor, status)
        VALUES (%s, %s, %s, 'pending')
        RETURNING id, session_id, user_input, created_by_actor, status, created_at;
        """,
        (task.user_input, task.session_id, actor["actor_name"]),
    )
    row = cur.fetchone()
    insert_audit_log(
        cur,
        "task.create",
        actor["actor_name"],
        int(row["id"]),
        {
            "session_id": task.session_id,
            "role": actor["role"],
            "quota": quota_snapshot,
        },
    )
    conn.commit()

    cur.close()
    conn.close()
    enqueue_task(int(row["id"]))

    logger.info("task created id=%s actor=%s user_input=%s", row["id"], actor["actor_name"], task.user_input[:200])

    return row


@app.get("/tasks")
def list_tasks(session_id: int | None = None):
    conn = get_conn()
    cur = conn.cursor()

    where_sql = ""
    params: tuple[Any, ...] = ()
    if session_id is not None:
        cur.execute("SELECT id FROM sessions WHERE id = %s;", (session_id,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            raise HTTPException(status_code=404, detail="Session not found")
        where_sql = "WHERE session_id = %s"
        params = (session_id,)

    cur.execute(f"""
        SELECT
            id,
            session_id,
            created_by_actor,
            user_input,
            status,
            result,
            error_message,
            current_step,
            checkpoint_path,
            created_at,
            updated_at
        FROM task_runs
        {where_sql}
        ORDER BY id DESC;
    """, params)
    rows = cur.fetchall()

    cur.close()
    conn.close()

    return rows


@app.get("/tasks/{task_id}")
def get_task(task_id: int):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            id,
            session_id,
            created_by_actor,
            user_input,
            status,
            result,
            error_message,
            current_step,
            checkpoint_path,
            created_at,
            updated_at
        FROM task_runs
        WHERE id = %s;
    """,
        (task_id,),
    )
    row = cur.fetchone()

    cur.close()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Task not found")

    return row


@app.get("/tasks/{task_id}/steps")
def get_task_steps(task_id: int):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id FROM task_runs WHERE id = %s;", (task_id,))
    task_exists = cur.fetchone()
    if not task_exists:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Task not found")

    cur.execute(
        """
        SELECT
            id,
            task_id,
            step_order,
            step_name,
            tool_name,
            status,
            input_payload,
            output_payload,
            output_data,
            error_message,
            run_if,
            skip_if,
            retry_count,
            max_retries,
            error_strategy,
            created_at,
            updated_at
        FROM task_steps
        WHERE task_id = %s
        ORDER BY step_order ASC;
    """,
        (task_id,),
    )
    rows = cur.fetchall()

    cur.close()
    conn.close()

    return rows


@app.get("/approvals")
def list_approvals(status: str | None = None):
    conn = get_conn()
    cur = conn.cursor()

    if status:
        cur.execute(
            """
            SELECT
                id,
                task_id,
                step_order,
                step_name,
                tool_name,
                input_payload,
                reason,
                status,
                decision_note,
                created_at,
                updated_at,
                decided_at
            FROM approvals
            WHERE status = %s
            ORDER BY id DESC;
            """,
            (status,),
        )
    else:
        cur.execute(
            """
            SELECT
                id,
                task_id,
                step_order,
                step_name,
                tool_name,
                input_payload,
                reason,
                status,
                decision_note,
                created_at,
                updated_at,
                decided_at
            FROM approvals
            ORDER BY id DESC;
            """
        )

    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


@app.get("/tasks/{task_id}/checkpoint")
def get_task_checkpoint(task_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, checkpoint_path
        FROM task_runs
        WHERE id = %s;
        """,
        (task_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Task not found")

    checkpoint_path = (row.get("checkpoint_path") or "").strip()
    if not checkpoint_path:
        raise HTTPException(status_code=404, detail="Checkpoint not found")

    path = Path(checkpoint_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Checkpoint file missing")

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Checkpoint unreadable: {exc}")


def get_task_or_404(cur, task_id: int):
    cur.execute(
        """
        SELECT id, status, current_step, checkpoint_path, error_message
        FROM task_runs
        WHERE id = %s;
        """,
        (task_id,),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    return row


def update_checkpoint_status(checkpoint_path_str: str | None, status: str, note: str = ""):
    checkpoint_path = (checkpoint_path_str or "").strip()
    if not checkpoint_path:
        return

    path = Path(checkpoint_path)
    if not path.exists():
        return

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return

    data["status"] = status
    if note:
        data["last_error"] = note
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@app.post("/tasks/{task_id}/interrupt")
def interrupt_task(
    task_id: int,
    request: TaskInterruptRequest,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    conn = get_conn()
    cur = conn.cursor()
    actor = require_actor_permission(cur, x_actor_name, "operate")

    task = get_task_or_404(cur, task_id)
    current_status = str(task["status"] or "")
    if current_status in {"completed", "failed"}:
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Completed or failed tasks cannot be interrupted")

    if current_status in {"paused", "interrupt_requested"}:
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Task is already paused or interrupt requested")

    note = request.note.strip() or "manual interrupt requested"
    next_status = "interrupt_requested" if current_status == "running" else "paused"

    cur.execute(
        """
        UPDATE task_runs
        SET status = %s,
            error_message = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s;
        """,
        (next_status, note, task_id),
    )

    update_checkpoint_status(task.get("checkpoint_path"), next_status if next_status != "interrupt_requested" else "running", note)

    insert_audit_log(
        cur,
        "task.interrupt",
        actor["actor_name"],
        task_id,
        {
            "previous_status": current_status,
            "next_status": next_status,
            "note": note,
            "role": actor["role"],
        },
    )

    conn.commit()
    cur.close()
    conn.close()

    logger.info(
        "task interrupt requested id=%s actor=%s previous_status=%s next_status=%s note=%s",
        task_id,
        actor["actor_name"],
        current_status,
        next_status,
        note[:200],
    )
    return {"message": "task interrupt requested", "task_id": task_id, "status": next_status}


@app.post("/tasks/{task_id}/resume")
def resume_task(
    task_id: int,
    request: TaskResumeRequest,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    conn = get_conn()
    cur = conn.cursor()
    actor = require_actor_permission(cur, x_actor_name, "operate")

    task = get_task_or_404(cur, task_id)
    if task["status"] not in {"failed", "waiting_approval", "paused", "interrupt_requested"}:
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Only failed, paused, interrupt_requested, or waiting_approval tasks can be resumed")

    cur.execute(
        """
        SELECT id
        FROM approvals
        WHERE task_id = %s AND status = 'pending'
        ORDER BY id DESC;
        """,
        (task_id,),
    )
    pending_approvals = cur.fetchall()
    if pending_approvals:
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Task has pending approvals; approve or reject them first")

    resume_from = request.from_step or task.get("current_step")
    if not resume_from:
        cur.execute(
            """
            SELECT step_order
            FROM task_steps
            WHERE task_id = %s AND status != 'completed'
            ORDER BY step_order ASC
            LIMIT 1;
            """,
            (task_id,),
        )
        row = cur.fetchone()
        resume_from = row["step_order"] if row else 1

    cur.execute(
        """
        UPDATE task_steps
        SET status = 'pending',
            output_payload = NULL,
            output_data = NULL,
            error_message = '',
            retry_count = 0,
            updated_at = CURRENT_TIMESTAMP
        WHERE task_id = %s
          AND step_order >= %s;
        """,
        (task_id, resume_from),
    )

    cur.execute(
        """
        UPDATE task_runs
        SET status = 'pending',
            result = NULL,
            error_message = NULL,
            current_step = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s;
        """,
        (resume_from, task_id),
    )

    insert_audit_log(
        cur,
        "task.resume",
        actor["actor_name"],
        task_id,
        {
            "from_step": resume_from,
            "note": request.note.strip(),
            "previous_status": task["status"],
            "role": actor["role"],
        },
    )

    conn.commit()
    cur.close()
    conn.close()

    enqueue_task(task_id)
    update_checkpoint_status(task.get("checkpoint_path"), "pending", request.note.strip() or "task resumed")
    logger.info(
        "task resumed id=%s actor=%s from_step=%s note=%s previous_status=%s",
        task_id,
        actor["actor_name"],
        resume_from,
        request.note[:200],
        task["status"],
    )
    return {"message": "task resumed", "task_id": task_id, "from_step": resume_from}


@app.get("/tasks/{task_id}/approvals")
def list_task_approvals(task_id: int):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id FROM task_runs WHERE id = %s;", (task_id,))
    task_exists = cur.fetchone()
    if not task_exists:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Task not found")

    cur.execute(
        """
        SELECT
            id,
            task_id,
            step_order,
            step_name,
            tool_name,
            input_payload,
            reason,
            status,
            decision_note,
            created_at,
            updated_at,
            decided_at
        FROM approvals
        WHERE task_id = %s
        ORDER BY id DESC;
        """,
        (task_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def get_approval_or_404(cur, approval_id: int):
    cur.execute(
        """
        SELECT id, task_id, step_order, status
        FROM approvals
        WHERE id = %s;
        """,
        (approval_id,),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Approval not found")
    return row


@app.post("/approvals/{approval_id}/approve")
def approve_approval(
    approval_id: int,
    decision: ApprovalDecision,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    conn = get_conn()
    cur = conn.cursor()
    actor = require_actor_permission(cur, x_actor_name, "operate")

    approval = get_approval_or_404(cur, approval_id)
    if approval["status"] != "pending":
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Approval is not pending")

    cur.execute(
        """
        UPDATE approvals
        SET status = 'approved',
            decision_note = %s,
            updated_at = CURRENT_TIMESTAMP,
            decided_at = CURRENT_TIMESTAMP
        WHERE id = %s;
        """,
        (decision.note, approval_id),
    )

    cur.execute(
        """
        UPDATE task_steps
        SET status = 'pending',
            error_message = '',
            updated_at = CURRENT_TIMESTAMP
        WHERE task_id = %s AND step_order = %s;
        """,
        (approval["task_id"], approval["step_order"]),
    )

    cur.execute(
        """
        UPDATE task_runs
        SET status = 'pending',
            error_message = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s;
        """,
        (approval["task_id"],),
    )

    insert_audit_log(
        cur,
        "approval.approve",
        actor["actor_name"],
        approval["task_id"],
        {
            "approval_id": approval_id,
            "step_order": approval["step_order"],
            "decision_note": decision.note,
            "role": actor["role"],
        },
    )

    conn.commit()
    cur.close()
    conn.close()
    enqueue_task(int(approval["task_id"]))
    logger.info(
        "approval approved approval_id=%s task_id=%s step_order=%s actor=%s note=%s",
        approval_id,
        approval["task_id"],
        approval["step_order"],
        actor["actor_name"],
        decision.note[:200],
    )
    return {"message": "approval approved", "approval_id": approval_id}


@app.post("/approvals/{approval_id}/reject")
def reject_approval(
    approval_id: int,
    decision: ApprovalDecision,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    conn = get_conn()
    cur = conn.cursor()
    actor = require_actor_permission(cur, x_actor_name, "operate")

    approval = get_approval_or_404(cur, approval_id)
    if approval["status"] != "pending":
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Approval is not pending")

    note = decision.note.strip() or "审批拒绝"

    cur.execute(
        """
        UPDATE approvals
        SET status = 'rejected',
            decision_note = %s,
            updated_at = CURRENT_TIMESTAMP,
            decided_at = CURRENT_TIMESTAMP
        WHERE id = %s;
        """,
        (note, approval_id),
    )

    cur.execute(
        """
        UPDATE task_steps
        SET status = 'failed',
            output_payload = %s,
            error_message = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE task_id = %s AND step_order = %s;
        """,
        (f"审批拒绝：{note}", f"审批拒绝：{note}", approval["task_id"], approval["step_order"]),
    )

    cur.execute(
        """
        UPDATE task_runs
        SET status = 'failed',
            error_message = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s;
        """,
        (f"审批拒绝：{note}", approval["task_id"]),
    )

    insert_audit_log(
        cur,
        "approval.reject",
        actor["actor_name"],
        approval["task_id"],
        {
            "approval_id": approval_id,
            "step_order": approval["step_order"],
            "decision_note": note,
            "role": actor["role"],
        },
    )

    conn.commit()
    cur.close()
    conn.close()
    logger.info(
        "approval rejected approval_id=%s task_id=%s step_order=%s actor=%s note=%s",
        approval_id,
        approval["task_id"],
        approval["step_order"],
        actor["actor_name"],
        note[:200],
    )
    return {"message": "approval rejected", "approval_id": approval_id}
