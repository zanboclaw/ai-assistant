from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import json
import logging
import os
import threading
import time
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
AUTO_STAGE5_POSTRUN_ENABLED = os.environ.get("AUTO_STAGE5_POSTRUN_ENABLED", "1").lower() in {"1", "true", "yes"}
MAINLINE_SPECIALIST_EXECUTION_MODES = {"task_postrun_readonly_v1", "task_runtime_worker_v1"}

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
MULTI_AGENT_PROTOCOL_VERSION = "multi-agent-v1"
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
ACTIVE_SESSION_TASK_STATUSES = {"pending", "running", "waiting_approval", "paused", "interrupt_requested"}
_stage56_schema_bootstrap_lock = threading.Lock()
_stage56_schema_bootstrap_active = False
_stage56_schema_bootstrapped = False


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


def enqueue_agent_run(agent_run_id: int):
    client = get_redis_client()
    if client is None:
        logger.warning("redis unavailable, skip enqueue agent_run_id=%s", agent_run_id)
        return
    try:
        client.rpush("agent_run_queue", str(agent_run_id))
    except Exception as exc:
        logger.warning("enqueue agent run failed agent_run_id=%s error=%s", agent_run_id, exc)


class TaskCreate(BaseModel):
    user_input: str
    session_id: int | None = None


class AgentBootstrapRequest(BaseModel):
    objective: str = ""
    specialist_count: int = 2
    include_reviewer: bool = True
    note: str = ""


class AgentFinalizeRequest(BaseModel):
    summary: str = ""
    note: str = ""
    reviewer_decision: str = "auto"
    allow_retry: bool = False


class AgentExecuteRequest(BaseModel):
    note: str = ""
    force_rerun: bool = False
    subtask_type: str = "readonly_step_digest"
    source_kind: str = ""
    source_path: str = ""
    source_json_path: str = ""
    dir_limit: int = 20


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


class WorkflowProposalBridgeRequest(BaseModel):
    target_type: str
    target_key: str
    proposed_payload: dict[str, Any]
    rationale: str = ""


class WorkflowProposalShadowValidationRequest(BaseModel):
    note: str = ""
    shadow_user_input: str = ""
    await_completion: bool = False
    timeout_seconds: int = 45
    poll_interval_seconds: float = 1.0


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


def ensure_stage56_schema_bootstrapped():
    global _stage56_schema_bootstrap_active, _stage56_schema_bootstrapped

    if _stage56_schema_bootstrapped:
        return

    with _stage56_schema_bootstrap_lock:
        if _stage56_schema_bootstrapped:
            return

        conn = get_conn()
        cur = conn.cursor()
        _stage56_schema_bootstrap_active = True
        try:
            ensure_audit_logs_table(cur)
            ensure_agent_tables(cur)
            ensure_evaluator_tables(cur)
            conn.commit()
            _stage56_schema_bootstrapped = True
        finally:
            _stage56_schema_bootstrap_active = False
            cur.close()
            conn.close()


def ensure_audit_logs_table(cur):
    if not _stage56_schema_bootstrap_active:
        ensure_stage56_schema_bootstrapped()
        return
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


def ensure_agent_tables(cur):
    if not _stage56_schema_bootstrap_active:
        ensure_stage56_schema_bootstrapped()
        return
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_runs (
            id SERIAL PRIMARY KEY,
            task_run_id INTEGER NOT NULL REFERENCES task_runs(id) ON DELETE CASCADE,
            parent_agent_run_id INTEGER REFERENCES agent_runs(id) ON DELETE SET NULL,
            role VARCHAR(50) NOT NULL,
            status VARCHAR(50) NOT NULL DEFAULT 'planned',
            attempt INTEGER NOT NULL DEFAULT 1,
            brief_artifact_id INTEGER,
            output_artifact_id INTEGER,
            review_artifact_id INTEGER,
            execution_mode TEXT,
            execution_request_json TEXT,
            source_task_run_id INTEGER REFERENCES task_runs(id) ON DELETE CASCADE,
            assigned_step_orders_json TEXT,
            assigned_model TEXT,
            assigned_tool_profile TEXT,
            error_summary TEXT,
            cost_tokens_in INTEGER NOT NULL DEFAULT 0,
            cost_tokens_out INTEGER NOT NULL DEFAULT 0,
            cost_usd_estimate NUMERIC(12, 6) NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            started_at TIMESTAMP,
            completed_at TIMESTAMP
        );
        """
    )
    cur.execute("ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS execution_mode TEXT;")
    cur.execute("ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS execution_request_json TEXT;")
    cur.execute("ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS source_task_run_id INTEGER REFERENCES task_runs(id) ON DELETE CASCADE;")
    cur.execute("ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS assigned_step_orders_json TEXT;")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_messages (
            id SERIAL PRIMARY KEY,
            task_run_id INTEGER NOT NULL REFERENCES task_runs(id) ON DELETE CASCADE,
            agent_run_id INTEGER REFERENCES agent_runs(id) ON DELETE CASCADE,
            sender_role VARCHAR(50) NOT NULL,
            recipient_role VARCHAR(50) NOT NULL,
            message_type VARCHAR(50) NOT NULL,
            payload_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_artifacts (
            id SERIAL PRIMARY KEY,
            task_run_id INTEGER NOT NULL REFERENCES task_runs(id) ON DELETE CASCADE,
            agent_run_id INTEGER REFERENCES agent_runs(id) ON DELETE CASCADE,
            artifact_type VARCHAR(50) NOT NULL,
            summary TEXT,
            content_json TEXT,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )


def ensure_evaluator_tables(cur):
    if not _stage56_schema_bootstrap_active:
        ensure_stage56_schema_bootstrapped()
        return
    ensure_agent_tables(cur)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS evaluator_runs (
            id SERIAL PRIMARY KEY,
            task_run_id INTEGER NOT NULL REFERENCES task_runs(id) ON DELETE CASCADE,
            manager_agent_run_id INTEGER REFERENCES agent_runs(id) ON DELETE SET NULL,
            reviewer_agent_run_id INTEGER REFERENCES agent_runs(id) ON DELETE SET NULL,
            final_artifact_id INTEGER REFERENCES agent_artifacts(id) ON DELETE SET NULL,
            review_artifact_id INTEGER REFERENCES agent_artifacts(id) ON DELETE SET NULL,
            evaluator_kind VARCHAR(50) NOT NULL DEFAULT 'stage6_quality_gate',
            status VARCHAR(50) NOT NULL DEFAULT 'completed',
            decision VARCHAR(50) NOT NULL,
            score INTEGER NOT NULL DEFAULT 0,
            failure_reason TEXT NOT NULL DEFAULT 'none',
            failure_stage TEXT NOT NULL DEFAULT 'none',
            criteria_json TEXT,
            step_stats_json TEXT,
            proposal_json TEXT,
            summary TEXT,
            recommendation TEXT,
            source TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    cur.execute("ALTER TABLE evaluator_runs ADD COLUMN IF NOT EXISTS failure_reason TEXT NOT NULL DEFAULT 'none';")
    cur.execute("ALTER TABLE evaluator_runs ADD COLUMN IF NOT EXISTS failure_stage TEXT NOT NULL DEFAULT 'none';")
    cur.execute("ALTER TABLE evaluator_runs ADD COLUMN IF NOT EXISTS proposal_json TEXT;")


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
CHANGE_GATE_REQUIRED_TARGET_TYPES = {
    "risk_policy",
    "tool_registry",
    "model_route",
    "model_provider",
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


def serialize_agent_run_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "task_run_id": row.get("task_run_id"),
        "parent_agent_run_id": row.get("parent_agent_run_id"),
        "role": row.get("role"),
        "status": row.get("status"),
        "attempt": int(row.get("attempt") or 1),
        "brief_artifact_id": row.get("brief_artifact_id"),
        "output_artifact_id": row.get("output_artifact_id"),
        "review_artifact_id": row.get("review_artifact_id"),
        "execution_mode": row.get("execution_mode") or "",
        "execution_request": parse_maybe_json(row.get("execution_request_json")),
        "source_task_run_id": row.get("source_task_run_id"),
        "assigned_step_orders": parse_maybe_json(row.get("assigned_step_orders_json")) or [],
        "assigned_model": row.get("assigned_model") or "",
        "assigned_tool_profile": row.get("assigned_tool_profile") or "",
        "error_summary": row.get("error_summary") or "",
        "cost_tokens_in": int(row.get("cost_tokens_in") or 0),
        "cost_tokens_out": int(row.get("cost_tokens_out") or 0),
        "cost_usd_estimate": float(row.get("cost_usd_estimate") or 0),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "started_at": row.get("started_at"),
        "completed_at": row.get("completed_at"),
    }


def serialize_agent_message_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "task_run_id": row.get("task_run_id"),
        "agent_run_id": row.get("agent_run_id"),
        "sender_role": row.get("sender_role"),
        "recipient_role": row.get("recipient_role"),
        "message_type": row.get("message_type"),
        "payload": parse_maybe_json(row.get("payload_json")),
        "created_at": row.get("created_at"),
    }


def serialize_agent_artifact_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "task_run_id": row.get("task_run_id"),
        "agent_run_id": row.get("agent_run_id"),
        "artifact_type": row.get("artifact_type"),
        "summary": row.get("summary") or "",
        "content": parse_maybe_json(row.get("content_json")),
        "version": int(row.get("version") or 1),
        "created_at": row.get("created_at"),
    }


def serialize_evaluator_run_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "task_run_id": row.get("task_run_id"),
        "manager_agent_run_id": row.get("manager_agent_run_id"),
        "reviewer_agent_run_id": row.get("reviewer_agent_run_id"),
        "final_artifact_id": row.get("final_artifact_id"),
        "review_artifact_id": row.get("review_artifact_id"),
        "evaluator_kind": row.get("evaluator_kind") or "",
        "status": row.get("status") or "",
        "decision": row.get("decision") or "",
        "score": int(row.get("score") or 0),
        "failure_reason": row.get("failure_reason") or "none",
        "failure_stage": row.get("failure_stage") or "none",
        "criteria": parse_maybe_json(row.get("criteria_json")) or [],
        "step_stats": parse_maybe_json(row.get("step_stats_json")) or {},
        "workflow_proposal": parse_maybe_json(row.get("proposal_json")) or {},
        "summary": row.get("summary") or "",
        "recommendation": row.get("recommendation") or "",
        "source": row.get("source") or "",
        "created_at": row.get("created_at"),
    }


def serialize_workflow_proposal(
    *,
    evaluator_run: dict[str, Any],
    proposal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    proposal = proposal or dict((evaluator_run or {}).get("workflow_proposal") or {})
    return {
        "id": int((evaluator_run or {}).get("id") or 0),
        "evaluator_run_id": (evaluator_run or {}).get("id"),
        "task_run_id": (evaluator_run or {}).get("task_run_id"),
        "decision": (evaluator_run or {}).get("decision") or "",
        "score": int((evaluator_run or {}).get("score") or 0),
        "failure_reason": (evaluator_run or {}).get("failure_reason") or "none",
        "failure_stage": (evaluator_run or {}).get("failure_stage") or "none",
        "status": proposal.get("status") or "suggested",
        "priority": proposal.get("priority") or "",
        "target_surface": proposal.get("target_surface") or "",
        "action_key": proposal.get("action_key") or "",
        "title": proposal.get("title") or "",
        "rationale": proposal.get("rationale") or ((evaluator_run or {}).get("recommendation") or ""),
        "action_payload": proposal.get("action_payload") or {},
        "next_strategy": proposal.get("next_strategy") or "",
        "auto_apply_eligible": bool(proposal.get("auto_apply_eligible")),
        "source": (evaluator_run or {}).get("source") or "",
        "created_at": (evaluator_run or {}).get("created_at"),
        "proposal": proposal,
    }


def build_change_request_draft_from_workflow_proposal(
    *,
    workflow_proposal: dict[str, Any],
    target_type: str = "",
    target_key: str = "",
    proposed_payload: dict[str, Any] | None = None,
    rationale: str = "",
) -> dict[str, Any]:
    normalized_target_type = target_type.strip()
    normalized_target_key = target_key.strip()
    proposal_id = int(workflow_proposal.get("id") or 0)
    base_rationale = rationale.strip() or str(workflow_proposal.get("rationale") or "").strip()
    metadata_suffix = (
        f"workflow proposal #{proposal_id} "
        f"action={workflow_proposal.get('action_key') or 'unknown'} "
        f"priority={workflow_proposal.get('priority') or 'unknown'} "
        f"task_id={workflow_proposal.get('task_run_id') or ''}"
    ).strip()
    composed_rationale = metadata_suffix if not base_rationale else f"{base_rationale}\n\n来源：{metadata_suffix}"
    payload = proposed_payload or {}
    return {
        "bridge_ready": bool(normalized_target_type and normalized_target_key and isinstance(payload, dict)),
        "target_type": normalized_target_type,
        "target_key": normalized_target_key,
        "proposed_payload": payload,
        "rationale": composed_rationale,
        "source_workflow_proposal": workflow_proposal,
        "supported_target_types": sorted(SUPPORTED_CHANGE_TARGET_TYPES),
    }


def suggest_change_request_draft_from_workflow_proposal(cur, workflow_proposal: dict[str, Any]) -> dict[str, Any]:
    action_key = str(workflow_proposal.get("action_key") or "")
    if action_key != "expand_specialist_scope":
        return build_change_request_draft_from_workflow_proposal(workflow_proposal=workflow_proposal)

    seed_default_model_providers(cur)
    seed_default_model_routes(cur)
    cur.execute(
        """
        SELECT route_name, provider, model_name, temperature, max_tokens, enabled, description, created_at, updated_at
        FROM model_routes
        WHERE route_name = 'planner'
        LIMIT 1;
        """
    )
    row = cur.fetchone()
    if not row:
        return build_change_request_draft_from_workflow_proposal(workflow_proposal=workflow_proposal)

    current_route = serialize_model_route_row(row)
    suggested_payload = {
        "provider": current_route["provider"],
        "model_name": current_route["model_name"],
        "temperature": current_route["temperature"],
        "max_tokens": max(int(current_route["max_tokens"]), 1800),
        "enabled": True,
        "description": (
            (current_route.get("description") or "").strip() + " | support readonly specialist expansion"
        ).strip(" |"),
    }
    draft = build_change_request_draft_from_workflow_proposal(
        workflow_proposal=workflow_proposal,
        target_type="model_route",
        target_key="planner",
        proposed_payload=suggested_payload,
    )
    draft["suggestion_source"] = "auto_action_mapping"
    draft["suggested_from"] = {
        "target_type": "model_route",
        "target_key": "planner",
        "current_route": current_route,
    }
    return draft


def build_shadow_validation_result(
    *,
    workflow_proposal: dict[str, Any],
    baseline_task_id: int,
    shadow_task: dict[str, Any],
    shadow_evaluator: dict[str, Any],
) -> dict[str, Any]:
    baseline_score = int(workflow_proposal.get("score") or 0)
    shadow_score = int((shadow_evaluator or {}).get("score") or 0)
    baseline_decision = str(workflow_proposal.get("decision") or "")
    shadow_decision = str((shadow_evaluator or {}).get("decision") or "")
    if shadow_score > baseline_score:
        validation_result = "improved"
    elif shadow_score < baseline_score:
        validation_result = "regressed"
    elif shadow_decision != baseline_decision:
        validation_result = "changed"
    else:
        validation_result = "matched"

    return {
        "proposal_id": int(workflow_proposal.get("id") or 0),
        "baseline_task_id": baseline_task_id,
        "baseline_evaluator_run_id": int(workflow_proposal.get("evaluator_run_id") or 0) or None,
        "baseline_score": baseline_score,
        "baseline_decision": baseline_decision,
        "shadow_task_id": int((shadow_task or {}).get("id") or 0) or None,
        "shadow_task_status": str((shadow_task or {}).get("status") or ""),
        "shadow_evaluator_run_id": int((shadow_evaluator or {}).get("id") or 0) or None,
        "shadow_score": shadow_score,
        "shadow_decision": shadow_decision,
        "score_delta": shadow_score - baseline_score,
        "validation_result": validation_result,
        "validation_mode": "task_replay_compare",
    }


def wait_for_shadow_validation_completion(
    *,
    workflow_proposal: dict[str, Any],
    baseline_task_id: int,
    shadow_task_id: int,
    actor_name: str,
    timeout_seconds: int,
    poll_interval_seconds: float,
) -> dict[str, Any] | None:
    deadline = time.time() + timeout_seconds
    terminal_statuses = {"completed", "failed"}

    while time.time() <= deadline:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, session_id, user_input, created_by_actor, status, created_at
            FROM task_runs
            WHERE id = %s;
            """,
            (shadow_task_id,),
        )
        shadow_task = cur.fetchone()
        shadow_evaluator = fetch_latest_evaluator_for_task(cur, shadow_task_id)
        shadow_status = str((shadow_task or {}).get("status") or "")

        if shadow_task and shadow_evaluator and shadow_status in terminal_statuses:
            validation = build_shadow_validation_result(
                workflow_proposal=workflow_proposal,
                baseline_task_id=baseline_task_id,
                shadow_task=shadow_task,
                shadow_evaluator=shadow_evaluator,
            )
            insert_audit_log(
                cur,
                "workflow_proposal.shadow_validated",
                actor_name,
                baseline_task_id,
                validation,
            )
            conn.commit()
            cur.close()
            conn.close()
            return {
                "shadow_task": shadow_task,
                "shadow_evaluator": shadow_evaluator,
                "validation": validation,
            }

        cur.close()
        conn.close()
        time.sleep(poll_interval_seconds)

    return None


def create_agent_artifact(
    cur,
    task_run_id: int,
    agent_run_id: int | None,
    artifact_type: str,
    summary: str,
    content: Any,
    version: int = 1,
) -> int:
    cur.execute(
        """
        INSERT INTO agent_artifacts (task_run_id, agent_run_id, artifact_type, summary, content_json, version)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id;
        """,
        (task_run_id, agent_run_id, artifact_type, summary, safe_json_dumps(content), int(version)),
    )
    return int(cur.fetchone()["id"])


def create_evaluator_run(
    cur,
    *,
    task_run_id: int,
    manager_agent_run_id: int | None,
    reviewer_agent_run_id: int | None,
    final_artifact_id: int | None,
    review_artifact_id: int | None,
    decision: str,
    score: int,
    failure_reason: str,
    failure_stage: str,
    criteria: Any,
    step_stats: Any,
    workflow_proposal: Any,
    summary: str,
    recommendation: str,
    source: str = "stage5_finalize_demo",
    evaluator_kind: str = "stage6_quality_gate",
    status: str = "completed",
) -> int:
    ensure_evaluator_tables(cur)
    cur.execute(
        """
        INSERT INTO evaluator_runs (
            task_run_id, manager_agent_run_id, reviewer_agent_run_id, final_artifact_id, review_artifact_id,
            evaluator_kind, status, decision, score, failure_reason, failure_stage,
            criteria_json, step_stats_json, proposal_json, summary, recommendation, source
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id;
        """,
        (
            task_run_id,
            manager_agent_run_id,
            reviewer_agent_run_id,
            final_artifact_id,
            review_artifact_id,
            evaluator_kind,
            status,
            decision,
            int(score),
            failure_reason,
            failure_stage,
            safe_json_dumps(criteria),
            safe_json_dumps(step_stats),
            safe_json_dumps(workflow_proposal),
            summary,
            recommendation,
            source,
        ),
    )
    return int(cur.fetchone()["id"])


def fetch_latest_evaluator_for_task(cur, task_id: int) -> dict[str, Any] | None:
    ensure_evaluator_tables(cur)
    cur.execute(
        """
        SELECT id, task_run_id, manager_agent_run_id, reviewer_agent_run_id, final_artifact_id, review_artifact_id,
               evaluator_kind, status, decision, score, failure_reason, failure_stage,
               criteria_json, step_stats_json, proposal_json, summary, recommendation,
               source, created_at
        FROM evaluator_runs
        WHERE task_run_id = %s
        ORDER BY id DESC
        LIMIT 1;
        """,
        (task_id,),
    )
    row = cur.fetchone()
    return serialize_evaluator_run_row(row) if row else None


def list_workflow_proposals_rows(
    cur,
    *,
    task_id: int | None = None,
    action_key: str | None = None,
    priority: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    ensure_evaluator_tables(cur)
    clauses: list[str] = ["proposal_json IS NOT NULL", "proposal_json != ''"]
    params: list[Any] = []
    if task_id is not None:
        clauses.append("task_run_id = %s")
        params.append(int(task_id))
    if action_key:
        clauses.append("proposal_json::jsonb ->> 'action_key' = %s")
        params.append(action_key.strip())
    if priority:
        clauses.append("proposal_json::jsonb ->> 'priority' = %s")
        params.append(priority.strip())
    row_limit = max(1, min(int(limit or 20), 200))
    where_sql = f"WHERE {' AND '.join(clauses)}"
    cur.execute(
        f"""
        SELECT id, task_run_id, manager_agent_run_id, reviewer_agent_run_id, final_artifact_id, review_artifact_id,
               evaluator_kind, status, decision, score, failure_reason, failure_stage,
               criteria_json, step_stats_json, proposal_json, summary, recommendation,
               source, created_at
        FROM evaluator_runs
        {where_sql}
        ORDER BY id DESC
        LIMIT %s;
        """,
        (*params, row_limit),
    )
    rows = [serialize_evaluator_run_row(row) for row in cur.fetchall()]
    return [serialize_workflow_proposal(evaluator_run=row) for row in rows]


def create_agent_message(
    cur,
    task_run_id: int,
    agent_run_id: int | None,
    sender_role: str,
    recipient_role: str,
    message_type: str,
    payload: Any,
) -> int:
    cur.execute(
        """
        INSERT INTO agent_messages (task_run_id, agent_run_id, sender_role, recipient_role, message_type, payload_json)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id;
        """,
        (task_run_id, agent_run_id, sender_role, recipient_role, message_type, safe_json_dumps(payload)),
    )
    return int(cur.fetchone()["id"])


def create_agent_run(
    cur,
    task_run_id: int,
    role: str,
    status: str,
    *,
    parent_agent_run_id: int | None = None,
    attempt: int = 1,
    brief_artifact_id: int | None = None,
    output_artifact_id: int | None = None,
    review_artifact_id: int | None = None,
    execution_mode: str = "",
    execution_request: Any | None = None,
    source_task_run_id: int | None = None,
    assigned_step_orders: list[int] | None = None,
    assigned_model: str = "",
    assigned_tool_profile: str = "",
    error_summary: str = "",
    started: bool = False,
    completed: bool = False,
) -> int:
    started_at = datetime.now(timezone.utc) if started else None
    completed_at = datetime.now(timezone.utc) if completed else None
    cur.execute(
        """
        INSERT INTO agent_runs (
            task_run_id, parent_agent_run_id, role, status, attempt, brief_artifact_id,
            output_artifact_id, review_artifact_id, execution_mode, execution_request_json,
            source_task_run_id, assigned_step_orders_json, assigned_model, assigned_tool_profile,
            error_summary, created_at, updated_at, started_at, completed_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, %s, %s)
        RETURNING id;
        """,
        (
            task_run_id,
            parent_agent_run_id,
            role,
            status,
            int(attempt),
            brief_artifact_id,
            output_artifact_id,
            review_artifact_id,
            execution_mode,
            safe_json_dumps(execution_request) if execution_request is not None else None,
            source_task_run_id,
            safe_json_dumps(assigned_step_orders or []),
            assigned_model,
            assigned_tool_profile,
            error_summary,
            started_at,
            completed_at,
        ),
    )
    return int(cur.fetchone()["id"])


def build_task_agent_summary_payload(
    *,
    task_id: int,
    agent_rows: list[dict[str, Any]],
    artifact_rows: list[dict[str, Any]],
    latest_evaluator: dict[str, Any] | None = None,
) -> dict[str, Any]:
    role_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    specialist_runs: list[dict[str, Any]] = []
    manager_run = None
    reviewer_run = None

    for row in agent_rows:
        role = str(row.get("role") or "unknown")
        status = str(row.get("status") or "unknown")
        role_counts[role] = int(role_counts.get(role, 0)) + 1
        status_counts[status] = int(status_counts.get(status, 0)) + 1
        if role == "manager" and manager_run is None:
            manager_run = row
        elif role == "reviewer" and reviewer_run is None:
            reviewer_run = row
        elif role == "specialist":
            specialist_runs.append(row)

    final_artifacts = [item for item in artifact_rows if item.get("artifact_type") == "final"]
    review_artifacts = [item for item in artifact_rows if item.get("artifact_type") == "review"]
    latest_final = max(final_artifacts, key=lambda item: (int(item.get("version") or 0), int(item.get("id") or 0)), default=None)
    latest_review = max(review_artifacts, key=lambda item: (int(item.get("version") or 0), int(item.get("id") or 0)), default=None)

    latest_final_content = (latest_final or {}).get("content") or {}
    latest_review_content = (latest_review or {}).get("content") or {}
    latest_reviewer_decision = str(latest_review_content.get("decision") or latest_final_content.get("review_status") or "")
    latest_decision_source = str(latest_review_content.get("decision_source") or latest_final_content.get("decision_source") or "")
    latest_next_strategy = str(latest_final_content.get("next_strategy") or "")

    specialists_completed = all(str(item.get("status") or "") == "completed" for item in specialist_runs) if specialist_runs else False
    can_execute = bool(specialist_runs) and any(not item.get("output_artifact_id") for item in specialist_runs)
    can_force_rerun = bool(specialist_runs)
    can_finalize = bool(manager_run) and bool(specialist_runs) and specialists_completed
    can_allow_retry = (
        bool(manager_run)
        and str(manager_run.get("status") or "") == "blocked"
        and latest_reviewer_decision == "rework_required"
        and specialists_completed
    )

    awaiting_role = ""
    blocking_reason = ""

    recommended_action = "none"
    if not agent_rows:
        recommended_action = "bootstrap"
        awaiting_role = "operator"
        blocking_reason = "task 还没有 Stage 5 agent runs"
    elif can_allow_retry:
        recommended_action = "finalize_retry"
        awaiting_role = "manager"
        blocking_reason = "reviewer requested rework，等待 manager 重新汇总"
    elif can_execute:
        recommended_action = "execute"
        awaiting_role = "specialist"
        blocking_reason = "specialist outputs 尚未生成"
    elif can_finalize and not latest_final:
        recommended_action = "finalize"
        awaiting_role = "manager"
        blocking_reason = "specialist 已完成，等待 manager 汇总 final artifact"
    elif latest_reviewer_decision == "rejected":
        recommended_action = "escalate_operator"
        awaiting_role = "operator"
        blocking_reason = "reviewer rejected final candidate"
    elif can_force_rerun and latest_reviewer_decision == "rework_required":
        recommended_action = "rerun_specialists"
        awaiting_role = "specialist"
        blocking_reason = "reviewer requested rework，等待 specialist 重跑"

    if not awaiting_role and reviewer_run and str(reviewer_run.get("status") or "") in {"queued", "running"}:
        awaiting_role = "reviewer"
        blocking_reason = "specialist inputs 已就绪，等待 reviewer"
    if not awaiting_role and manager_run and str(manager_run.get("status") or "") == "failed":
        awaiting_role = "operator"
        blocking_reason = str(manager_run.get("error_summary") or "manager failed")

    specialist_summaries = [
        {
            "id": int(item["id"]),
            "status": str(item.get("status") or "unknown"),
            "attempt": int(item.get("attempt") or 1),
            "output_artifact_id": item.get("output_artifact_id"),
            "review_artifact_id": item.get("review_artifact_id"),
            "execution_mode": item.get("execution_mode") or "",
            "subtask_type": str((item.get("execution_request") or {}).get("subtask_type") or "readonly_step_digest"),
            "assigned_step_orders": item.get("assigned_step_orders") or [],
            "has_execution_request": bool(item.get("execution_request")),
            "assigned_model": item.get("assigned_model") or "",
            "assigned_tool_profile": item.get("assigned_tool_profile") or "",
        }
        for item in specialist_runs
    ]
    specialist_execution_modes = sorted({str(item.get("execution_mode") or "") for item in specialist_runs if str(item.get("execution_mode") or "").strip()})
    specialist_subtask_types = sorted({str((item.get("execution_request") or {}).get("subtask_type") or "readonly_step_digest") for item in specialist_runs})
    execution_backend = "none"
    implementation_status = "manager_worker_execute_demo"
    record_origin = "uninitialized"
    control_mode = "demo_operate"
    latest_evaluator_source = str((latest_evaluator or {}).get("source") or "")
    latest_workflow_proposal = (latest_evaluator or {}).get("workflow_proposal") or {}
    runtime_fanout_active = any(mode == "task_runtime_worker_v1" for mode in specialist_execution_modes)
    postrun_observed = any(mode == "task_postrun_readonly_v1" for mode in specialist_execution_modes)
    if (latest_evaluator or {}).get("source") == "task_runtime_postrun_v1" or any(mode in MAINLINE_SPECIALIST_EXECUTION_MODES for mode in specialist_execution_modes):
        execution_backend = "mainline"
        implementation_status = "task_runtime_postrun_v1"
        record_origin = "mainline_postrun" if (latest_evaluator or {}).get("source") == "task_runtime_postrun_v1" or postrun_observed else "mainline_runtime"
        control_mode = "observe_only"
    elif any(mode == "worker_readonly_v1" for mode in specialist_execution_modes):
        execution_backend = "worker"
        implementation_status = "manager_worker_execute_demo"
        record_origin = "worker_demo"
        control_mode = "demo_operate"
    elif specialist_execution_modes:
        execution_backend = "api"
        record_origin = "api_demo"
        control_mode = "demo_operate"

    return {
        "protocol_version": MULTI_AGENT_PROTOCOL_VERSION,
        "implementation_status": implementation_status,
        "record_origin": record_origin,
        "control_mode": control_mode,
        "task_id": task_id,
        "role_counts": role_counts,
        "status_counts": status_counts,
        "manager": serialize_agent_run_row(manager_run) if manager_run else None,
        "reviewer": serialize_agent_run_row(reviewer_run) if reviewer_run else None,
        "specialists": specialist_summaries,
        "specialist_execution_modes": specialist_execution_modes,
        "specialist_subtask_types": specialist_subtask_types,
        "execution_backend": execution_backend,
        "runtime_fanout_active": runtime_fanout_active,
        "postrun_observed": postrun_observed,
        "latest_final_artifact": {
            "id": latest_final.get("id"),
            "version": int(latest_final.get("version") or 1),
            "review_status": latest_final_content.get("review_status") or "",
            "next_strategy": latest_final_content.get("next_strategy") or "",
            "quality_score": latest_final_content.get("quality_score"),
        } if latest_final else None,
        "latest_review_artifact": {
            "id": latest_review.get("id"),
            "version": int(latest_review.get("version") or 1),
            "decision": latest_review_content.get("decision") or "",
            "quality_score": latest_review_content.get("quality_score"),
            "decision_source": latest_review_content.get("decision_source") or "",
        } if latest_review else None,
        "latest_evaluator": latest_evaluator,
        "latest_evaluator_source": latest_evaluator_source,
        "latest_workflow_proposal": latest_workflow_proposal,
        "latest_workflow_proposal_action": str(latest_workflow_proposal.get("action_key") or ""),
        "latest_workflow_proposal_priority": str(latest_workflow_proposal.get("priority") or ""),
        "latest_recommendation": (latest_evaluator or {}).get("recommendation") or "",
        "latest_failure_reason": (latest_evaluator or {}).get("failure_reason") or "none",
        "latest_failure_stage": (latest_evaluator or {}).get("failure_stage") or "none",
        "history": {
            "final_artifact_versions": len(final_artifacts),
            "review_artifact_versions": len(review_artifacts),
        },
        "capabilities": {
            "can_execute": can_execute,
            "can_force_rerun": can_force_rerun,
            "can_finalize": can_finalize,
            "can_allow_retry": can_allow_retry,
            "can_bootstrap_demo": not agent_rows,
            "demo_actions_recommended": implementation_status != "task_runtime_postrun_v1",
            "runtime_fanout_active": runtime_fanout_active,
        },
        "recommended_action": recommended_action,
        "latest_reviewer_decision": latest_reviewer_decision,
        "latest_decision_source": latest_decision_source,
        "latest_next_strategy": latest_next_strategy,
        "awaiting_role": awaiting_role,
        "blocking_reason": blocking_reason,
    }


def fetch_task_agent_summary(cur, task_id: int) -> dict[str, Any]:
    cur.execute(
        """
        SELECT id, task_run_id, parent_agent_run_id, role, status, attempt, brief_artifact_id,
               output_artifact_id, review_artifact_id, execution_mode, execution_request_json,
               source_task_run_id, assigned_step_orders_json, assigned_model, assigned_tool_profile,
               error_summary, cost_tokens_in, cost_tokens_out, cost_usd_estimate,
               created_at, updated_at, started_at, completed_at
        FROM agent_runs
        WHERE task_run_id = %s
        ORDER BY id ASC;
        """,
        (task_id,),
    )
    agent_rows = [serialize_agent_run_row(row) for row in cur.fetchall()]
    cur.execute(
        """
        SELECT id, task_run_id, agent_run_id, artifact_type, summary, content_json, version, created_at
        FROM agent_artifacts
        WHERE task_run_id = %s
        ORDER BY id ASC;
        """,
        (task_id,),
    )
    artifact_rows = [serialize_agent_artifact_row(row) for row in cur.fetchall()]
    latest_evaluator = fetch_latest_evaluator_for_task(cur, task_id)
    return build_task_agent_summary_payload(
        task_id=task_id,
        agent_rows=agent_rows,
        artifact_rows=artifact_rows,
        latest_evaluator=latest_evaluator,
    )


def build_demo_review_criteria(
    *,
    task_status: str,
    step_rows: list[dict[str, Any]],
    specialist_draft_count: int,
    reviewer_decision: str,
) -> dict[str, Any]:
    total_steps = len(step_rows)
    completed_steps = sum(1 for row in step_rows if row.get("status") == "completed")
    failed_steps = sum(1 for row in step_rows if row.get("status") == "failed")
    pending_steps = max(0, total_steps - completed_steps - failed_steps)
    criteria = [
        {
            "criterion": "specialist_drafts_present",
            "passed": specialist_draft_count > 0,
            "actual": specialist_draft_count,
        },
        {
            "criterion": "task_step_coverage_available",
            "passed": total_steps > 0 or task_status in {"completed", "failed", "waiting_approval"},
            "actual": total_steps,
        },
        {
            "criterion": "reviewer_decision_recorded",
            "passed": reviewer_decision in {"approved", "rework_required", "rejected"},
            "actual": reviewer_decision,
        },
    ]
    score = 100
    if failed_steps:
        score -= min(30, failed_steps * 10)
    if reviewer_decision == "rework_required":
        score -= 25
    elif reviewer_decision == "rejected":
        score -= 45
    if specialist_draft_count == 0:
        score -= 40
    score = max(0, min(100, score))
    return {
        "criteria": criteria,
        "score": score,
        "step_stats": {
            "total_steps": total_steps,
            "completed_steps": completed_steps,
            "failed_steps": failed_steps,
            "pending_steps": pending_steps,
        },
    }


def derive_evaluator_failure_profile(
    *,
    task_status: str,
    step_rows: list[dict[str, Any]],
    specialist_draft_count: int,
    reviewer_decision: str,
) -> dict[str, str]:
    total_steps = len(step_rows)
    completed_steps = sum(1 for row in step_rows if row.get("status") == "completed")
    failed_steps = sum(1 for row in step_rows if row.get("status") == "failed")

    if reviewer_decision == "approved":
        return {
            "failure_reason": "none",
            "failure_stage": "none",
            "recommendation": "当前质量门通过，可以继续推进下一阶段或扩展 evaluator 自动反馈。",
            "summary": "evaluator 判定当前结果健康，可继续推进。",
        }
    if failed_steps > 0 or task_status == "failed":
        return {
            "failure_reason": "task_failed_step",
            "failure_stage": "execution",
            "recommendation": "优先检查 failed steps 的错误摘要，修复输入或步骤依赖后再执行。",
            "summary": "evaluator 发现任务执行阶段存在 failed step。",
        }
    if specialist_draft_count == 0:
        return {
            "failure_reason": "missing_specialist_outputs",
            "failure_stage": "specialist",
            "recommendation": "需要先补齐 specialist outputs，再让 manager/reviewer 继续收敛。",
            "summary": "evaluator 发现 specialist outputs 缺失，无法形成有效汇总。",
        }
    if total_steps > 0 and completed_steps < total_steps:
        return {
            "failure_reason": "incomplete_execution",
            "failure_stage": "execution",
            "recommendation": "补齐 pending/running steps 后重新生成 drafts 并再次评估。",
            "summary": "evaluator 发现任务执行尚未完成，结果需要返工。",
        }
    if reviewer_decision == "rejected":
        return {
            "failure_reason": "reviewer_rejected",
            "failure_stage": "review",
            "recommendation": "需要 operator 接管并重新规划，再决定是否继续拆解执行。",
            "summary": "evaluator 根据 reviewer 拒绝结果要求人工接管。",
        }
    if reviewer_decision == "rework_required":
        return {
            "failure_reason": "reviewer_requested_rework",
            "failure_stage": "review",
            "recommendation": "按 reviewer 建议返工 specialists 或允许 manager retry 后重新评估。",
            "summary": "evaluator 根据 reviewer 返工结果要求继续补强输出。",
        }
    return {
        "failure_reason": "unknown",
        "failure_stage": "unknown",
        "recommendation": "需要人工检查当前 evaluator 输出与任务上下文。",
        "summary": "evaluator 无法归类当前失败原因。",
    }


def build_workflow_proposal(
    *,
    task_id: int,
    reviewer_decision: str,
    failure_profile: dict[str, str],
    quality_bundle: dict[str, Any],
    next_strategy: str,
) -> dict[str, Any]:
    failure_reason = str(failure_profile.get("failure_reason") or "unknown")
    failure_stage = str(failure_profile.get("failure_stage") or "unknown")
    recommendation = str(failure_profile.get("recommendation") or "").strip()
    score = int((quality_bundle.get("score") or 0))

    priority = "medium"
    target_surface = "stage5_orchestration"
    action_key = "inspect_manually"
    title = "人工检查当前闭环"
    action_payload: dict[str, Any] = {"recommended_action": "inspect_manually"}

    if failure_reason == "none":
        priority = "low"
        target_surface = "stage6_evaluator"
        action_key = "expand_specialist_scope"
        title = "扩展 specialist 子任务覆盖面"
        action_payload = {
            "recommended_action": "expand_specialist_scope",
            "candidate_subtasks": ["readonly_source_snapshot"],
            "trigger": "quality_gate_passed",
        }
    elif failure_reason == "task_failed_step":
        priority = "high"
        target_surface = "task_runtime"
        action_key = "repair_failed_steps"
        title = "修复 failed steps 后重跑主任务"
        action_payload = {
            "recommended_action": "repair_failed_steps",
            "retry_scope": "task_steps",
            "expected_next_strategy": "resume_task",
        }
    elif failure_reason == "missing_specialist_outputs":
        priority = "high"
        target_surface = "stage5_specialists"
        action_key = "queue_specialists"
        title = "补齐 specialist outputs"
        action_payload = {
            "recommended_action": "queue_specialists",
            "dispatch": "execute_worker_demo",
            "expected_next_strategy": "generate_drafts",
        }
    elif failure_reason == "incomplete_execution":
        priority = "high"
        target_surface = "stage5_specialists"
        action_key = "rerun_incomplete_specialists"
        title = "重跑未完成 specialist"
        action_payload = {
            "recommended_action": "rerun_incomplete_specialists",
            "dispatch": "execute_worker_demo",
            "force_rerun": True,
        }
    elif failure_reason == "reviewer_rejected":
        priority = "high"
        target_surface = "operator_escalation"
        action_key = "escalate_to_operator"
        title = "升级 operator 重新规划"
        action_payload = {
            "recommended_action": "escalate_to_operator",
            "expected_next_strategy": "replan_task",
        }
    elif failure_reason == "reviewer_requested_rework":
        priority = "medium"
        target_surface = "stage5_manager_retry"
        action_key = "rerun_specialists_then_finalize"
        title = "重跑 specialists 后再次 finalize"
        action_payload = {
            "recommended_action": "rerun_specialists_then_finalize",
            "dispatch": "execute_worker_demo",
            "followed_by": "finalize_demo_allow_retry",
        }

    return {
        "version": "stage6-workflow-proposal-v1",
        "task_id": task_id,
        "status": "suggested",
        "decision": reviewer_decision,
        "score": score,
        "failure_reason": failure_reason,
        "failure_stage": failure_stage,
        "next_strategy": next_strategy,
        "priority": priority,
        "target_surface": target_surface,
        "action_key": action_key,
        "title": title,
        "rationale": recommendation,
        "action_payload": action_payload,
        "auto_apply_eligible": False,
    }


def resolve_reviewer_decision(
    *,
    requested_decision: str,
    task_status: str,
    step_rows: list[dict[str, Any]],
    specialist_draft_count: int,
) -> tuple[str, str]:
    normalized = str(requested_decision or "").strip().lower() or "auto"
    if normalized != "auto":
        return normalized, "manual"

    total_steps = len(step_rows)
    completed_steps = sum(1 for row in step_rows if row.get("status") == "completed")
    failed_steps = sum(1 for row in step_rows if row.get("status") == "failed")

    if failed_steps > 0 or task_status == "failed":
        return "rejected", "auto"
    if specialist_draft_count == 0:
        return "rework_required", "auto"
    if total_steps > 0 and completed_steps < total_steps:
        return "rework_required", "auto"
    return "approved", "auto"


def build_specialist_execution_request(
    *,
    slot: int,
    manager_objective: str,
    assigned_steps: list[dict[str, Any]] | None = None,
    brief_artifact_id: int | None = None,
    plan_artifact_id: int | None = None,
    note: str = "",
    execution_mode: str = "api_readonly_subtask_v1",
    subtask_type: str = "readonly_step_digest",
    source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assigned_steps = assigned_steps or []
    assigned_step_orders = [int(step.get("step_order") or 0) for step in assigned_steps if int(step.get("step_order") or 0) > 0]
    source = source or {}
    focus_questions = [
        "这个子问题最关键的信息是什么",
        "有哪些明显缺口、风险或需要继续跟进的点",
    ]
    deliverable = f"specialist-{slot} readonly digest"
    scope = "plan_boundary_digest" if slot == 1 else "risk_result_digest"
    success_criteria = [
        "summarize assigned steps",
        "highlight risks and gaps",
        "produce manager-consumable digest",
    ]
    if subtask_type == "readonly_source_snapshot":
        deliverable = "readonly source snapshot"
        scope = "source_snapshot"
        success_criteria = [
            "return source metadata",
            "return a bounded excerpt or selected fields",
            "highlight gaps and risks",
        ]
    elif subtask_type == "readonly_task_snapshot":
        deliverable = "readonly task snapshot"
        scope = "task_snapshot"
        success_criteria = [
            "return bounded task-level status snapshot",
            "include latest evaluation and review signals",
            "highlight next operator or manager action",
        ]
    return {
        "execution_mode": execution_mode,
        "tool_profile": "specialist-readonly",
        "subtask_type": subtask_type,
        "slot": slot,
        "objective": manager_objective,
        "scope": scope,
        "deliverable": deliverable,
        "assigned_step_orders": assigned_step_orders,
        "source": source,
        "focus_questions": focus_questions,
        "evidence_refs": [
            {"artifact_id": artifact_id, "label": label}
            for artifact_id, label in [
                (brief_artifact_id, "specialist_brief"),
                (plan_artifact_id, "manager_plan"),
            ]
            if artifact_id
        ],
        "constraints": ["readonly-only", "do-not-write-files", "do-not-emit-final-answer"],
        "success_criteria": success_criteria,
        "note": note,
    }


def build_specialist_step_partitions(
    *,
    step_rows: list[dict[str, Any]],
    specialist_count: int,
    task_row: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[list[dict[str, Any]]], dict[str, int]]:
    step_outline = [
        {
            "step_order": int(row["step_order"]),
            "step_name": row["step_name"],
            "status": row["status"],
            "tool_name": row.get("tool_name") or "",
        }
        for row in step_rows[:6]
    ]
    specialist_step_partitions: list[list[dict[str, Any]]] = [[] for _ in range(max(1, specialist_count))]
    if step_rows:
        for index, step_row in enumerate(step_rows):
            specialist_step_partitions[index % len(specialist_step_partitions)].append(
                {
                    "step_order": int(step_row["step_order"]),
                    "step_name": step_row["step_name"],
                    "status": step_row["status"],
                    "tool_name": step_row.get("tool_name") or "",
                    "input_excerpt": str(step_row.get("input_payload") or "")[:180],
                    "output_excerpt": str(step_row.get("output_payload") or "")[:220],
                    "error_excerpt": str(step_row.get("error_message") or "")[:160],
                }
            )
    else:
        specialist_step_partitions = [
            [
                {
                    "step_order": 0,
                    "step_name": "task-result-fallback",
                    "status": task_row["status"],
                    "tool_name": "",
                    "input_excerpt": str(task_row.get("user_input") or "")[:180],
                    "output_excerpt": str(task_row.get("result") or "")[:220],
                    "error_excerpt": str(task_row.get("error_message") or "")[:160],
                }
            ]
            for _ in specialist_step_partitions
        ]
    step_status_counts: dict[str, int] = {}
    for row in step_rows:
        status_key = str(row.get("status") or "unknown")
        step_status_counts[status_key] = int(step_status_counts.get(status_key, 0)) + 1
    return step_outline, specialist_step_partitions, step_status_counts


def build_specialist_draft_payload(
    *,
    slot: int,
    task_id: int,
    agent_run_id: int,
    manager_objective: str,
    task_row: dict[str, Any],
    step_outline: list[dict[str, Any]],
    assigned_steps: list[dict[str, Any]],
    plan_artifact_id: int | None,
    note: str,
    step_status_counts: dict[str, int],
    execution_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assigned_completed_steps = sum(1 for step in assigned_steps if step.get("status") == "completed")
    assigned_failed_steps = sum(1 for step in assigned_steps if step.get("status") == "failed")
    assigned_pending_steps = max(0, len(assigned_steps) - assigned_completed_steps - assigned_failed_steps)
    assigned_step_orders = [int(step.get("step_order") or 0) for step in assigned_steps if int(step.get("step_order") or 0) > 0]
    completed_names = [str(step.get("step_name") or "") for step in assigned_steps if step.get("status") == "completed"]
    failed_names = [str(step.get("step_name") or "") for step in assigned_steps if step.get("status") == "failed"]
    pending_names = [
        str(step.get("step_name") or "")
        for step in assigned_steps
        if step.get("status") not in {"completed", "failed"}
    ]
    output_digest = [
        {
            "step_order": int(step.get("step_order") or 0),
            "step_name": step.get("step_name") or "",
            "status": step.get("status") or "unknown",
            "tool_name": step.get("tool_name") or "",
            "output_excerpt": step.get("output_excerpt") or "",
        }
        for step in assigned_steps[:3]
        if step.get("output_excerpt")
    ]
    risk_digest = [
        {
            "step_order": int(step.get("step_order") or 0),
            "step_name": step.get("step_name") or "",
            "status": step.get("status") or "unknown",
            "error_excerpt": step.get("error_excerpt") or "",
        }
        for step in assigned_steps
        if step.get("status") == "failed" or step.get("error_excerpt")
    ][:3]
    observations = [
        f"step#{int(step.get('step_order') or 0)} {step.get('step_name') or ''} -> {step.get('status') or 'unknown'}"
        for step in assigned_steps[:4]
    ]
    recommended_followups: list[str] = []
    if assigned_failed_steps:
        recommended_followups.append("优先检查 failed steps 的错误摘要并决定是否重试")
    if assigned_pending_steps:
        recommended_followups.append("补齐 pending/running steps 后再重新汇总")
    if not recommended_followups:
        recommended_followups.append("基于当前已完成步骤继续汇总为 manager final candidate")
    execution_result = {
        "execution_mode": "api_readonly_subtask_v1",
        "subtask_type": "readonly_step_digest",
        "status": "completed",
        "request_snapshot": execution_request or {},
        "assigned_step_orders": assigned_step_orders,
        "completed_step_names": completed_names[:6],
        "failed_step_names": failed_names[:6],
        "pending_step_names": pending_names[:6],
        "observations": observations,
        "output_digest": output_digest,
        "risk_digest": risk_digest,
        "recommended_followups": recommended_followups,
    }
    return {
        "protocol_version": MULTI_AGENT_PROTOCOL_VERSION,
        "task_id": task_id,
        "agent_run_id": agent_run_id,
        "summary": f"子问题 {slot} 完成只读 specialist 子任务并生成结构化 draft",
        "output": {
            "slot": slot,
            "deliverable": f"Draft for subtask {slot}",
            "objective": manager_objective,
            "task_status": task_row["status"],
            "task_result_excerpt": str(task_row.get("result") or "")[:280],
            "task_error_excerpt": str(task_row.get("error_message") or "")[:200],
            "step_outline": step_outline,
            "assigned_steps": assigned_steps,
            "subtask": {
                "type": "readonly_step_digest",
                "execution_mode": "api_readonly_subtask_v1",
                "assigned_step_orders": assigned_step_orders,
            },
            "execution_request": execution_request or {},
            "execution_result": execution_result,
            "execution_summary": {
                "assigned_step_count": len(assigned_steps),
                "assigned_completed_steps": assigned_completed_steps,
                "assigned_failed_steps": assigned_failed_steps,
                "assigned_pending_steps": assigned_pending_steps,
                "step_status_counts": {
                    "completed": assigned_completed_steps,
                    "failed": assigned_failed_steps,
                    "other": assigned_pending_steps,
                },
            },
            "focus": "梳理计划与任务边界" if slot == 1 else "汇总执行结果与剩余风险",
        },
        "evidence_refs": [{"artifact_id": plan_artifact_id, "label": "manager_plan"}] if plan_artifact_id else [],
        "known_gaps": [] if task_row["status"] == "completed" else [f"task 当前状态为 {task_row['status']}"],
        "quality_signals": {
            "task_status": task_row["status"],
            "global_step_status_counts": step_status_counts,
            "specialist_execution_mode": "api_readonly_subtask_v1",
            "assigned_step_count": len(assigned_steps),
        },
        "note": note,
    }


def normalize_memory_key(category: Any, content: Any) -> tuple[str, str]:
    normalized_category = str(category or "").strip().lower()
    normalized_content = " ".join(str(content or "").strip().lower().split())
    return normalized_category, normalized_content


def compute_session_health(
    task_rows: list[dict[str, Any]],
    memory_rows: list[dict[str, Any]],
    session_state_row: dict[str, Any] | None,
    review_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    active_task_count = 0
    latest_task_updated_at = None
    for row in task_rows:
        status = str(row.get("status") or "").strip()
        updated_at = row.get("updated_at")
        if status in ACTIVE_SESSION_TASK_STATUSES:
            active_task_count += 1
        if updated_at and (latest_task_updated_at is None or updated_at > latest_task_updated_at):
            latest_task_updated_at = updated_at

    duplicate_memory_count = 0
    high_importance_memory_count = 0
    seen_memory_keys: set[tuple[str, str]] = set()
    for row in memory_rows:
        importance = int(row.get("importance") or 0)
        if importance >= 4:
            high_importance_memory_count += 1
        memory_key = normalize_memory_key(row.get("category"), row.get("content"))
        if memory_key[1]:
            if memory_key in seen_memory_keys:
                duplicate_memory_count += 1
            else:
                seen_memory_keys.add(memory_key)

    state = serialize_session_state_row(session_state_row) if session_state_row else {
        "summary_text": "",
        "preferences": [],
        "open_loops": [],
        "updated_at": None,
    }
    preferences = [str(item).strip() for item in state.get("preferences", []) if str(item).strip()]
    open_loops = [str(item).strip() for item in state.get("open_loops", []) if str(item).strip()]
    state_updated_at = state.get("updated_at")
    state_is_stale = bool(latest_task_updated_at and (not state_updated_at or latest_task_updated_at > state_updated_at))

    total_reviews = len(review_rows)
    latest_review_at = review_rows[0].get("created_at") if review_rows else None
    daily_review_today = any(
        str(row.get("review_kind") or "").strip() == "daily"
        and row.get("created_at")
        and row["created_at"].date() == datetime.now(timezone.utc).date()
        for row in review_rows
    )
    needs_review = bool(active_task_count > 0 and not daily_review_today)

    recommended_actions: list[dict[str, str]] = []
    if not session_state_row:
        recommended_actions.append({"action": "rebuild_state", "reason": "session 还没有 working memory state"})
    elif state_is_stale:
        recommended_actions.append({"action": "rebuild_state", "reason": "session state 落后于最近任务更新时间"})
    if total_reviews == 0:
        recommended_actions.append({"action": "create_review", "reason": "session 还没有任何 review"})
    elif needs_review:
        recommended_actions.append({"action": "run_daily_review", "reason": "session 仍有活跃任务且今天还没有 daily review"})
    if duplicate_memory_count > 0:
        recommended_actions.append({"action": "dedupe_memories", "reason": "存在重复 memory，可先做去重再进入更深阶段"})
    if open_loops and active_task_count == 0:
        recommended_actions.append({"action": "review_open_loops", "reason": "当前没有活跃任务，但还保留 open loops 需要整理"})

    return {
        "active_task_count": active_task_count,
        "high_importance_memory_count": high_importance_memory_count,
        "duplicate_memory_count": duplicate_memory_count,
        "preference_count": len(preferences),
        "open_loop_count": len(open_loops),
        "total_reviews": total_reviews,
        "latest_review_at": latest_review_at,
        "daily_review_today": daily_review_today,
        "needs_review": needs_review,
        "state_is_stale": state_is_stale,
        "recommended_actions": recommended_actions,
    }


def compute_stage_readiness_metrics(
    total_sessions: int,
    total_session_states: int,
    total_session_reviews: int,
    active_session_count: int,
    sessions_missing_state_count: int,
    sessions_missing_review_count: int,
    sessions_needing_review_count: int,
    sessions_with_duplicate_memories_count: int,
    sessions_with_open_loops_count: int,
    access_actor_count: int,
    access_quota_count: int,
    quota_pressure_count: int,
    change_request_total_count: int,
    change_request_pending_count: int,
    change_request_approved_count: int,
    change_request_rejected_count: int,
    change_request_applied_count: int,
    stage5_mainline_task_count: int,
    stage5_runtime_fanout_task_count: int,
    stage5_role_skeleton_ready_count: int,
    stage5_terminal_mainline_task_count: int,
    stage5_terminal_ready_count: int,
    stage6_mainline_evaluator_run_count: int,
    stage6_mainline_workflow_proposal_count: int,
    stage6_auto_mapped_proposal_count: int,
    stage6_mainline_bridged_change_request_count: int,
    stage5_non_readonly_specialist_task_count: int,
    stage5_runtime_fanout_event_count: int,
    stage5_runtime_fanin_event_count: int,
    stage5_runtime_execute_event_count: int,
    stage6_failure_taxonomy_count: int,
    stage6_shadow_validation_count: int,
) -> dict[str, Any]:
    def build_completion_progress(gates: list[tuple[str, bool]]) -> dict[str, Any]:
        met = [name for name, is_met in gates if is_met]
        missing = [name for name, is_met in gates if not is_met]
        completion_ratio = round(len(met) / len(gates), 3) if gates else 1.0
        return {
            "completion_ratio": completion_ratio,
            "completed": not missing,
            "met_completion_gates": met,
            "missing_completion_gates": missing,
        }

    total_sessions = max(total_sessions, 0)
    supported_change_target_count = len(SUPPORTED_CHANGE_TARGET_TYPES)
    required_change_gate_target_count = len(CHANGE_GATE_REQUIRED_TARGET_TYPES)
    enforced_change_target_count = len(DEFAULT_ENFORCED_CHANGE_TARGET_TYPES & CHANGE_GATE_REQUIRED_TARGET_TYPES)
    missing_change_gate_targets = sorted(CHANGE_GATE_REQUIRED_TARGET_TYPES - DEFAULT_ENFORCED_CHANGE_TARGET_TYPES)
    active_session_baseline = active_session_count or total_sessions
    stage3_ready_session_count = max(
        0,
        active_session_baseline - sessions_missing_state_count - sessions_missing_review_count - sessions_with_duplicate_memories_count,
    )
    stage3_readiness_ratio = round(stage3_ready_session_count / active_session_baseline, 3) if active_session_baseline else 1.0
    stage4_governance_ratio = round(
        enforced_change_target_count / required_change_gate_target_count,
        3,
    ) if required_change_gate_target_count else 1.0
    change_request_closed_count = change_request_rejected_count + change_request_applied_count
    change_request_closure_ratio = round(change_request_closed_count / change_request_total_count, 3) if change_request_total_count else 0.0
    change_request_apply_ratio = round(change_request_applied_count / change_request_total_count, 3) if change_request_total_count else 0.0
    actor_quota_alignment_ok = access_actor_count == access_quota_count
    stage5_runtime_fanout_ratio = (
        round(stage5_runtime_fanout_task_count / stage5_mainline_task_count, 3)
        if stage5_mainline_task_count
        else 0.0
    )
    stage5_role_skeleton_ratio = (
        round(stage5_role_skeleton_ready_count / stage5_mainline_task_count, 3)
        if stage5_mainline_task_count
        else 0.0
    )
    stage5_terminal_readiness_ratio = (
        round(stage5_terminal_ready_count / stage5_terminal_mainline_task_count, 3)
        if stage5_terminal_mainline_task_count
        else 0.0
    )
    stage6_workflow_proposal_coverage_ratio = (
        round(stage6_mainline_workflow_proposal_count / stage6_mainline_evaluator_run_count, 3)
        if stage6_mainline_evaluator_run_count
        else 0.0
    )
    stage6_bridge_activation_ratio = (
        round(stage6_mainline_bridged_change_request_count / stage6_auto_mapped_proposal_count, 3)
        if stage6_auto_mapped_proposal_count
        else 0.0
    )
    stage5_completion_progress = build_completion_progress([
        ("mainline_runtime_postrun", stage5_terminal_mainline_task_count > 0 and stage5_terminal_ready_count > 0),
        (
            "runtime_fanout_audited",
            stage5_runtime_fanout_event_count > 0
            and stage5_runtime_execute_event_count > 0,
        ),
        ("manager_fanin_audited", stage5_runtime_fanin_event_count > 0),
        ("reviewer_lane_ready", stage5_role_skeleton_ready_count == stage5_mainline_task_count and stage5_mainline_task_count > 0),
        ("restricted_tool_specialist_ready", stage5_non_readonly_specialist_task_count > 0),
    ])
    stage6_completion_progress = build_completion_progress([
        ("mainline_evaluator_ready", stage6_mainline_evaluator_run_count > 0),
        ("failure_taxonomy_ready", stage6_failure_taxonomy_count > 0),
        (
            "workflow_proposal_ready",
            stage6_mainline_workflow_proposal_count == stage6_mainline_evaluator_run_count
            and stage6_mainline_workflow_proposal_count > 0,
        ),
        ("change_request_bridge_ready", stage6_mainline_bridged_change_request_count > 0),
        ("shadow_validation_ready", stage6_shadow_validation_count > 0),
    ])
    stage3_operational = (
        sessions_missing_state_count == 0
        and sessions_missing_review_count == 0
        and sessions_with_duplicate_memories_count == 0
    )
    stage4_operational = (
        not missing_change_gate_targets
        and change_request_applied_count >= 1
        and actor_quota_alignment_ok
        and access_actor_count > 0
        and access_quota_count > 0
    )
    stage5_operational = (
        stage5_mainline_task_count > 0
        and stage5_runtime_fanout_event_count > 0
        and stage5_runtime_execute_event_count > 0
        and stage5_runtime_fanin_event_count > 0
        and stage5_role_skeleton_ready_count == stage5_mainline_task_count
        and stage5_terminal_ready_count > 0
    )
    stage6_operational = (
        stage6_mainline_evaluator_run_count > 0
        and stage6_mainline_workflow_proposal_count == stage6_mainline_evaluator_run_count
        and stage6_auto_mapped_proposal_count > 0
        and stage6_mainline_bridged_change_request_count > 0
    )

    return {
        "stage3": {
            "total_sessions": total_sessions,
            "active_sessions": active_session_count,
            "sessions_with_state": total_session_states,
            "sessions_with_review": total_session_reviews,
            "sessions_missing_state": sessions_missing_state_count,
            "sessions_missing_review": sessions_missing_review_count,
            "sessions_needing_review": sessions_needing_review_count,
            "sessions_with_duplicate_memories": sessions_with_duplicate_memories_count,
            "sessions_with_open_loops": sessions_with_open_loops_count,
            "ready_session_count": stage3_ready_session_count,
            "readiness_ratio": stage3_readiness_ratio,
            "operational": stage3_operational,
        },
        "stage4": {
            "supported_change_target_count": supported_change_target_count,
            "change_gate_required_target_count": required_change_gate_target_count,
            "enforced_change_target_count": enforced_change_target_count,
            "change_gate_coverage_ratio": stage4_governance_ratio,
            "change_gate_missing_target_types": missing_change_gate_targets,
            "access_actor_count": access_actor_count,
            "access_quota_count": access_quota_count,
            "quota_pressure_count": quota_pressure_count,
            "actor_quota_alignment_ok": actor_quota_alignment_ok,
            "change_request_total_count": change_request_total_count,
            "change_request_pending_count": change_request_pending_count,
            "change_request_approved_count": change_request_approved_count,
            "change_request_rejected_count": change_request_rejected_count,
            "change_request_applied_count": change_request_applied_count,
            "change_request_closed_count": change_request_closed_count,
            "change_request_closure_ratio": change_request_closure_ratio,
            "change_request_apply_ratio": change_request_apply_ratio,
            "operational": stage4_operational,
            "pending_changes_require_attention": change_request_pending_count > 0,
        },
        "stage5": {
            "mainline_task_count": stage5_mainline_task_count,
            "runtime_fanout_task_count": stage5_runtime_fanout_task_count,
            "role_skeleton_ready_count": stage5_role_skeleton_ready_count,
            "runtime_fanout_ratio": stage5_runtime_fanout_ratio,
            "role_skeleton_ratio": stage5_role_skeleton_ratio,
            "terminal_mainline_task_count": stage5_terminal_mainline_task_count,
            "terminal_ready_count": stage5_terminal_ready_count,
            "terminal_readiness_ratio": stage5_terminal_readiness_ratio,
            "tasks_missing_runtime_fanout": max(0, stage5_mainline_task_count - stage5_runtime_fanout_task_count),
            "tasks_missing_role_skeleton": max(0, stage5_mainline_task_count - stage5_role_skeleton_ready_count),
            "terminal_tasks_missing_postrun": max(0, stage5_terminal_mainline_task_count - stage5_terminal_ready_count),
            "non_readonly_specialist_task_count": stage5_non_readonly_specialist_task_count,
            "runtime_fanout_event_count": stage5_runtime_fanout_event_count,
            "runtime_fanin_event_count": stage5_runtime_fanin_event_count,
            "runtime_execute_event_count": stage5_runtime_execute_event_count,
            "completion_ratio": stage5_completion_progress["completion_ratio"],
            "completed": stage5_completion_progress["completed"],
            "met_completion_gates": stage5_completion_progress["met_completion_gates"],
            "missing_completion_gates": stage5_completion_progress["missing_completion_gates"],
            "operational": stage5_operational,
        },
        "stage6": {
            "mainline_evaluator_run_count": stage6_mainline_evaluator_run_count,
            "mainline_workflow_proposal_count": stage6_mainline_workflow_proposal_count,
            "workflow_proposal_coverage_ratio": stage6_workflow_proposal_coverage_ratio,
            "auto_mapped_proposal_count": stage6_auto_mapped_proposal_count,
            "mainline_bridged_change_request_count": stage6_mainline_bridged_change_request_count,
            "bridge_activation_ratio": stage6_bridge_activation_ratio,
            "failure_taxonomy_count": stage6_failure_taxonomy_count,
            "shadow_validation_count": stage6_shadow_validation_count,
            "completion_ratio": stage6_completion_progress["completion_ratio"],
            "completed": stage6_completion_progress["completed"],
            "met_completion_gates": stage6_completion_progress["met_completion_gates"],
            "missing_completion_gates": stage6_completion_progress["missing_completion_gates"],
            "operational": stage6_operational,
        },
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


def load_session_health_context(
    cur,
    session_id: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None, list[dict[str, Any]]]:
    session_row, task_rows, memory_rows, session_state_row = load_session_review_context(cur, session_id)
    cur.execute(
        """
        SELECT id, session_id, review_kind, summary_text, highlights, open_loops, created_at
        FROM session_reviews
        WHERE session_id = %s
        ORDER BY created_at DESC, id DESC;
        """,
        (session_id,),
    )
    review_rows = list(cur.fetchall())
    return session_row, task_rows, memory_rows, session_state_row, review_rows


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
    ensure_agent_tables(cur)

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
    multi_agent_status = "task_runtime_postrun_v1" if AUTO_STAGE5_POSTRUN_ENABLED else "manager_worker_execute_demo"
    evaluator_status = "task_runtime_postrun_v1" if AUTO_STAGE5_POSTRUN_ENABLED else "proposal_seed_demo"
    evaluator_source = "task_runtime_postrun_v1" if AUTO_STAGE5_POSTRUN_ENABLED else "stage5_finalize_demo"
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
        "multi_agent_protocol": {
            "version": MULTI_AGENT_PROTOCOL_VERSION,
            "roles": ["manager", "specialist", "reviewer", "operator"],
            "artifact_types": ["brief", "plan", "draft", "evidence", "review", "final"],
            "message_types": ["brief", "progress", "request_clarification", "result", "review_decision", "handoff", "escalation"],
            "implementation_status": multi_agent_status,
        },
        "evaluator_protocol": {
            "version": "stage6-evaluator-v1",
            "evaluator_kind": "stage6_quality_gate",
            "source": evaluator_source,
            "implementation_status": evaluator_status,
        },
    }


@app.get("/agent-runs")
def list_agent_runs(task_id: int | None = None, role: str | None = None, status: str | None = None):
    conn = get_conn()
    cur = conn.cursor()
    clauses: list[str] = []
    params: list[Any] = []
    if task_id is not None:
        clauses.append("task_run_id = %s")
        params.append(int(task_id))
    if role:
        clauses.append("role = %s")
        params.append(role.strip())
    if status:
        clauses.append("status = %s")
        params.append(status.strip())
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cur.execute(
        f"""
        SELECT id, task_run_id, parent_agent_run_id, role, status, attempt, brief_artifact_id,
               output_artifact_id, review_artifact_id, execution_mode, execution_request_json,
               source_task_run_id, assigned_step_orders_json, assigned_model, assigned_tool_profile,
               error_summary, cost_tokens_in, cost_tokens_out, cost_usd_estimate,
               created_at, updated_at, started_at, completed_at
        FROM agent_runs
        {where_sql}
        ORDER BY id DESC;
        """,
        tuple(params),
    )
    rows = [serialize_agent_run_row(row) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


@app.get("/tasks/{task_id}/agent-runs")
def list_task_agent_runs(task_id: int):
    return list_agent_runs(task_id=task_id)


@app.get("/tasks/{task_id}/agent-runs/summary")
def get_task_agent_run_summary(task_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM task_runs WHERE id = %s;", (task_id,))
    task_row = cur.fetchone()
    if not task_row:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Task not found")

    result = fetch_task_agent_summary(cur, task_id)
    cur.close()
    conn.close()
    return result


@app.get("/agent-runs/{agent_run_id}")
def get_agent_run(agent_run_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, task_run_id, parent_agent_run_id, role, status, attempt, brief_artifact_id,
               output_artifact_id, review_artifact_id, execution_mode, execution_request_json,
               source_task_run_id, assigned_step_orders_json, assigned_model, assigned_tool_profile,
               error_summary, cost_tokens_in, cost_tokens_out, cost_usd_estimate,
               created_at, updated_at, started_at, completed_at
        FROM agent_runs
        WHERE id = %s;
        """,
        (agent_run_id,),
    )
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Agent run not found")
    result = serialize_agent_run_row(row)
    cur.close()
    conn.close()
    return result


@app.get("/agent-runs/{agent_run_id}/messages")
def list_agent_run_messages(agent_run_id: int, limit: int | None = 50):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM agent_runs WHERE id = %s;", (agent_run_id,))
    if not cur.fetchone():
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Agent run not found")
    row_limit = max(1, min(int(limit or 50), 200))
    cur.execute(
        """
        SELECT id, task_run_id, agent_run_id, sender_role, recipient_role, message_type, payload_json, created_at
        FROM agent_messages
        WHERE agent_run_id = %s
        ORDER BY id DESC
        LIMIT %s;
        """,
        (agent_run_id, row_limit),
    )
    rows = [serialize_agent_message_row(row) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


@app.get("/agent-runs/{agent_run_id}/artifacts")
def list_agent_run_artifacts(agent_run_id: int, limit: int | None = 50):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, brief_artifact_id, output_artifact_id, review_artifact_id
        FROM agent_runs
        WHERE id = %s;
        """,
        (agent_run_id,),
    )
    agent_run = cur.fetchone()
    if not agent_run:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Agent run not found")
    row_limit = max(1, min(int(limit or 50), 200))
    referenced_artifact_ids = [
        artifact_id
        for artifact_id in [
            agent_run.get("brief_artifact_id"),
            agent_run.get("output_artifact_id"),
            agent_run.get("review_artifact_id"),
        ]
        if artifact_id is not None
    ]
    cur.execute(
        """
        SELECT id, task_run_id, agent_run_id, artifact_type, summary, content_json, version, created_at
        FROM agent_artifacts
        WHERE agent_run_id = %s
           OR id = ANY(%s)
        ORDER BY id DESC
        LIMIT %s;
        """,
        (agent_run_id, referenced_artifact_ids, row_limit),
    )
    rows = [serialize_agent_artifact_row(row) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


@app.get("/evaluator-runs")
def list_evaluator_runs(task_id: int | None = None, limit: int = 20):
    conn = get_conn()
    cur = conn.cursor()
    clauses: list[str] = []
    params: list[Any] = []
    if task_id is not None:
        clauses.append("task_run_id = %s")
        params.append(int(task_id))
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    row_limit = max(1, min(int(limit or 20), 200))
    cur.execute(
        f"""
        SELECT id, task_run_id, manager_agent_run_id, reviewer_agent_run_id, final_artifact_id, review_artifact_id,
               evaluator_kind, status, decision, score, failure_reason, failure_stage,
               criteria_json, step_stats_json, proposal_json, summary, recommendation,
               source, created_at
        FROM evaluator_runs
        {where_sql}
        ORDER BY id DESC
        LIMIT %s;
        """,
        (*params, row_limit),
    )
    rows = [serialize_evaluator_run_row(row) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


@app.get("/tasks/{task_id}/evaluator-runs")
def list_task_evaluator_runs(task_id: int, limit: int = 20):
    return list_evaluator_runs(task_id=task_id, limit=limit)


@app.get("/tasks/{task_id}/evaluator-runs/latest")
def get_latest_task_evaluator_run(task_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM task_runs WHERE id = %s;", (task_id,))
    task_row = cur.fetchone()
    if not task_row:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Task not found")
    latest = fetch_latest_evaluator_for_task(cur, task_id)
    cur.close()
    conn.close()
    if not latest:
        raise HTTPException(status_code=404, detail="No evaluator runs found for this task")
    return latest


@app.get("/tasks/{task_id}/workflow-proposals/latest")
def get_latest_task_workflow_proposal(task_id: int):
    latest = get_latest_task_evaluator_run(task_id)
    proposal = (latest or {}).get("workflow_proposal") or {}
    if not proposal:
        raise HTTPException(status_code=404, detail="No workflow proposal found for this task")
    return serialize_workflow_proposal(evaluator_run=latest, proposal=proposal)


@app.get("/workflow-proposals")
def list_workflow_proposals(
    task_id: int | None = None,
    action_key: str | None = None,
    priority: str | None = None,
    limit: int = 20,
):
    conn = get_conn()
    cur = conn.cursor()
    rows = list_workflow_proposals_rows(
        cur,
        task_id=task_id,
        action_key=action_key,
        priority=priority,
        limit=limit,
    )
    cur.close()
    conn.close()
    return rows


@app.get("/tasks/{task_id}/workflow-proposals")
def list_task_workflow_proposals(task_id: int, limit: int = 20):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM task_runs WHERE id = %s;", (task_id,))
    if not cur.fetchone():
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Task not found")
    rows = list_workflow_proposals_rows(cur, task_id=task_id, limit=limit)
    cur.close()
    conn.close()
    return rows


@app.get("/workflow-proposals/{proposal_id}")
def get_workflow_proposal(proposal_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, task_run_id, manager_agent_run_id, reviewer_agent_run_id, final_artifact_id, review_artifact_id,
               evaluator_kind, status, decision, score, failure_reason, failure_stage,
               criteria_json, step_stats_json, proposal_json, summary, recommendation,
               source, created_at
        FROM evaluator_runs
        WHERE id = %s;
        """,
        (proposal_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Workflow proposal not found")
    evaluator_run = serialize_evaluator_run_row(row)
    proposal = (evaluator_run or {}).get("workflow_proposal") or {}
    if not proposal:
        raise HTTPException(status_code=404, detail="Workflow proposal not found")
    return serialize_workflow_proposal(evaluator_run=evaluator_run, proposal=proposal)


@app.get("/workflow-proposals/{proposal_id}/change-request-draft")
def preview_workflow_proposal_change_request_draft(proposal_id: int):
    conn = get_conn()
    cur = conn.cursor()
    workflow_proposal = get_workflow_proposal(proposal_id)
    result = suggest_change_request_draft_from_workflow_proposal(cur, workflow_proposal)
    cur.close()
    conn.close()
    return result


@app.post("/workflow-proposals/{proposal_id}/change-request-draft")
def create_change_request_from_workflow_proposal(
    proposal_id: int,
    request: WorkflowProposalBridgeRequest,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    workflow_proposal = get_workflow_proposal(proposal_id)
    draft = build_change_request_draft_from_workflow_proposal(
        workflow_proposal=workflow_proposal,
        target_type=request.target_type,
        target_key=request.target_key,
        proposed_payload=request.proposed_payload,
        rationale=request.rationale,
    )
    target_type = str(draft.get("target_type") or "")
    target_key = str(draft.get("target_key") or "")
    proposed_payload = draft.get("proposed_payload") or {}
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
            safe_json_dumps(proposed_payload),
            str(draft.get("rationale") or ""),
            actor["actor_name"],
        ),
    )
    row = cur.fetchone()
    insert_audit_log(
        cur,
        "workflow_proposal.change_request_create",
        actor["actor_name"],
        int(workflow_proposal.get("task_run_id") or 0) or None,
        {
            "proposal_id": proposal_id,
            "change_request_id": row["id"],
            "target_type": target_type,
            "target_key": target_key,
        },
    )
    conn.commit()
    cur.close()
    conn.close()
    return {
        "change_request": serialize_change_request_row(row),
        "workflow_proposal": workflow_proposal,
    }


@app.post("/workflow-proposals/{proposal_id}/shadow-validate")
def shadow_validate_workflow_proposal(
    proposal_id: int,
    request: WorkflowProposalShadowValidationRequest,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    workflow_proposal = get_workflow_proposal(proposal_id)
    if str(workflow_proposal.get("source") or "") != "task_runtime_postrun_v1":
        raise HTTPException(status_code=400, detail="Shadow validation currently only supports mainline workflow proposals")

    baseline_task_id = int(workflow_proposal.get("task_run_id") or 0)
    if baseline_task_id <= 0:
        raise HTTPException(status_code=400, detail="Workflow proposal is missing baseline task context")

    conn = get_conn()
    cur = conn.cursor()
    actor = require_actor_permission(cur, x_actor_name, "operate")
    quota_snapshot = enforce_task_quota(cur, actor["actor_name"])
    cur.execute(
        """
        SELECT id, session_id, user_input, created_by_actor, status, created_at
        FROM task_runs
        WHERE id = %s;
        """,
        (baseline_task_id,),
    )
    baseline_task = cur.fetchone()
    if not baseline_task:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Baseline task not found")
    if str(baseline_task.get("status") or "") not in {"completed", "failed"}:
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Baseline task must be terminal before shadow validation")

    shadow_user_input = (request.shadow_user_input or "").strip() or str(baseline_task.get("user_input") or "").strip()
    if not shadow_user_input:
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="shadow_user_input is empty")

    cur.execute(
        """
        INSERT INTO task_runs (user_input, session_id, created_by_actor, status)
        VALUES (%s, %s, %s, 'pending')
        RETURNING id, session_id, user_input, created_by_actor, status, created_at;
        """,
        (shadow_user_input, baseline_task.get("session_id"), actor["actor_name"]),
    )
    shadow_task = cur.fetchone()
    insert_audit_log(
        cur,
        "task.create",
        actor["actor_name"],
        int(shadow_task["id"]),
        {
            "session_id": shadow_task.get("session_id"),
            "role": actor["role"],
            "quota": quota_snapshot,
            "source": "workflow_proposal.shadow_validation",
            "baseline_task_id": baseline_task_id,
            "proposal_id": proposal_id,
        },
    )
    validation_request = {
        "proposal_id": proposal_id,
        "action_key": str(workflow_proposal.get("action_key") or ""),
        "baseline_task_id": baseline_task_id,
        "baseline_evaluator_run_id": int(workflow_proposal.get("evaluator_run_id") or 0) or None,
        "baseline_score": int(workflow_proposal.get("score") or 0),
        "baseline_decision": str(workflow_proposal.get("decision") or ""),
        "shadow_task_id": int(shadow_task["id"]),
        "shadow_user_input": shadow_user_input,
        "validation_mode": "task_replay_compare",
        "note": request.note.strip(),
    }
    insert_audit_log(
        cur,
        "workflow_proposal.shadow_validation",
        actor["actor_name"],
        baseline_task_id,
        validation_request,
    )
    conn.commit()
    cur.close()
    conn.close()

    enqueue_task(int(shadow_task["id"]))

    response: dict[str, Any] = {
        "completed": False,
        "workflow_proposal": workflow_proposal,
        "baseline_task": baseline_task,
        "shadow_task": shadow_task,
        "validation_request": validation_request,
    }

    if request.await_completion:
        timeout_seconds = max(5, min(int(request.timeout_seconds or 45), 180))
        poll_interval_seconds = max(0.5, min(float(request.poll_interval_seconds or 1.0), 5.0))
        completed = wait_for_shadow_validation_completion(
            workflow_proposal=workflow_proposal,
            baseline_task_id=baseline_task_id,
            shadow_task_id=int(shadow_task["id"]),
            actor_name=actor["actor_name"],
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
        if completed:
            response["completed"] = True
            response["shadow_task"] = completed["shadow_task"]
            response["shadow_evaluator"] = completed["shadow_evaluator"]
            response["validation"] = completed["validation"]

    return response


@app.get("/evaluator-runs/{evaluator_run_id}")
def get_evaluator_run(evaluator_run_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, task_run_id, manager_agent_run_id, reviewer_agent_run_id, final_artifact_id, review_artifact_id,
               evaluator_kind, status, decision, score, failure_reason, failure_stage,
               criteria_json, step_stats_json, proposal_json, summary, recommendation,
               source, created_at
        FROM evaluator_runs
        WHERE id = %s;
        """,
        (evaluator_run_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Evaluator run not found")
    return serialize_evaluator_run_row(row)


@app.get("/monitor/overview")
def get_monitor_overview():
    conn = get_conn()
    cur = conn.cursor()
    ensure_risk_policies_table(cur)
    ensure_access_actors_table(cur)
    ensure_access_quotas_table(cur)
    ensure_tool_registry_table(cur)
    ensure_model_providers_table(cur)
    ensure_model_routes_table(cur)
    ensure_change_requests_table(cur)
    ensure_agent_tables(cur)
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
        FROM sessions s
        LEFT JOIN session_states st ON st.session_id = s.id
        WHERE st.session_id IS NULL;
        """
    )
    sessions_missing_state_count = int(cur.fetchone()["count"])

    cur.execute(
        """
        SELECT COUNT(*) AS count
        FROM sessions s
        LEFT JOIN (
            SELECT DISTINCT session_id
            FROM session_reviews
        ) sr ON sr.session_id = s.id
        WHERE sr.session_id IS NULL;
        """
    )
    sessions_missing_review_count = int(cur.fetchone()["count"])

    cur.execute(
        """
        SELECT COUNT(DISTINCT session_id) AS count
        FROM task_runs
        WHERE session_id IS NOT NULL
          AND status IN ('pending', 'running', 'waiting_approval', 'paused', 'interrupt_requested');
        """
    )
    active_session_count = int(cur.fetchone()["count"])

    cur.execute(
        """
        SELECT COUNT(*) AS count
        FROM (
            SELECT DISTINCT t.session_id
            FROM task_runs t
            LEFT JOIN (
                SELECT session_id, MAX(created_at) AS last_daily_review_at
                FROM session_reviews
                WHERE review_kind = 'daily'
                  AND DATE(created_at) = CURRENT_DATE
                GROUP BY session_id
            ) dr ON dr.session_id = t.session_id
            WHERE t.session_id IS NOT NULL
              AND t.status IN ('pending', 'running', 'waiting_approval', 'paused', 'interrupt_requested')
              AND dr.session_id IS NULL
        ) session_review_gap;
        """
    )
    sessions_needing_review_count = int(cur.fetchone()["count"])

    cur.execute(
        """
        SELECT COUNT(*) AS count
        FROM (
            SELECT session_id
            FROM session_memories
            GROUP BY session_id, LOWER(TRIM(category)), LOWER(TRIM(content))
            HAVING COUNT(*) > 1
        ) duplicate_memories;
        """
    )
    sessions_with_duplicate_memories_count = int(cur.fetchone()["count"])

    cur.execute(
        """
        SELECT COUNT(*) AS count
        FROM session_states
        WHERE jsonb_array_length(COALESCE(open_loops::jsonb, '[]'::jsonb)) > 0;
        """
    )
    sessions_with_open_loops_count = int(cur.fetchone()["count"])

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

    cur.execute("SELECT COUNT(*) AS count FROM agent_runs;")
    total_agent_runs = int(cur.fetchone()["count"])

    cur.execute(
        """
        SELECT status, COUNT(*) AS count
        FROM agent_runs
        GROUP BY status
        ORDER BY status ASC;
        """
    )
    agent_runs_by_status = {str(row["status"]): int(row["count"]) for row in cur.fetchall()}

    cur.execute(
        """
        SELECT role, COUNT(*) AS count
        FROM agent_runs
        GROUP BY role
        ORDER BY role ASC;
        """
    )
    agent_runs_by_role = {str(row["role"]): int(row["count"]) for row in cur.fetchall()}

    blocked_agent_runs = int(agent_runs_by_status.get("blocked", 0))
    running_agent_runs = int(agent_runs_by_status.get("running", 0))

    cur.execute("SELECT COUNT(*) AS count FROM agent_messages;")
    total_agent_messages = int(cur.fetchone()["count"])

    cur.execute("SELECT COUNT(*) AS count FROM agent_artifacts;")
    total_agent_artifacts = int(cur.fetchone()["count"])

    cur.execute(
        """
        SELECT status, COUNT(*) AS count
        FROM change_requests
        GROUP BY status;
        """
    )
    change_request_status_counts = {str(row["status"]): int(row["count"]) for row in cur.fetchall()}
    pending_change_requests = int(change_request_status_counts.get("pending", 0))
    approved_change_requests = int(change_request_status_counts.get("approved", 0))
    rejected_change_requests = int(change_request_status_counts.get("rejected", 0))
    applied_change_requests = int(change_request_status_counts.get("applied", 0))
    closed_change_requests = rejected_change_requests + applied_change_requests
    change_request_closure_ratio = round(closed_change_requests / total_change_requests, 3) if total_change_requests else 0.0

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
        SELECT DISTINCT task_run_id
        FROM agent_runs
        ORDER BY task_run_id DESC
        LIMIT 120;
        """
    )
    stage5_task_ids = [int(row["task_run_id"]) for row in cur.fetchall() if row.get("task_run_id") is not None]
    stage5_summary_rows = [fetch_task_agent_summary(cur, task_id) for task_id in stage5_task_ids]
    tasks_requiring_execute = sum(1 for item in stage5_summary_rows if item.get("recommended_action") == "execute")
    tasks_requiring_finalize = sum(1 for item in stage5_summary_rows if item.get("recommended_action") == "finalize")
    tasks_requiring_retry = sum(1 for item in stage5_summary_rows if item.get("recommended_action") in {"rerun_specialists", "finalize_retry"})
    tasks_requiring_operator_escalation = sum(1 for item in stage5_summary_rows if item.get("recommended_action") == "escalate_operator")
    mainline_stage5_summary_rows = [
        item
        for item in stage5_summary_rows
        if item.get("implementation_status") == "task_runtime_postrun_v1"
        and item.get("execution_backend") == "mainline"
    ]
    stage5_mainline_task_count = len(mainline_stage5_summary_rows)
    stage5_runtime_fanout_task_count = sum(1 for item in mainline_stage5_summary_rows if bool(item.get("runtime_fanout_active")))
    stage5_role_skeleton_ready_count = sum(
        1
        for item in mainline_stage5_summary_rows
        if int(((item.get("role_counts") or {}).get("manager") or 0)) >= 1
        and int(((item.get("role_counts") or {}).get("specialist") or 0)) >= 1
        and int(((item.get("role_counts") or {}).get("reviewer") or 0)) >= 1
    )
    terminal_mainline_stage5_rows = [
        item for item in mainline_stage5_summary_rows if item.get("latest_evaluator_source") == "task_runtime_postrun_v1"
    ]
    stage5_terminal_mainline_task_count = len(terminal_mainline_stage5_rows)
    stage5_terminal_ready_count = sum(
        1
        for item in terminal_mainline_stage5_rows
        if bool(item.get("runtime_fanout_active"))
        and int(((item.get("role_counts") or {}).get("manager") or 0)) >= 1
        and int(((item.get("role_counts") or {}).get("specialist") or 0)) >= 1
        and int(((item.get("role_counts") or {}).get("reviewer") or 0)) >= 1
        and bool((item.get("latest_final_artifact") or {}).get("id"))
        and bool(item.get("latest_workflow_proposal_action"))
    )
    stage5_non_readonly_specialist_task_count = sum(
        1
        for item in mainline_stage5_summary_rows
        if any(
            not str(subtask_type or "").startswith("readonly_")
            for subtask_type in (item.get("specialist_subtask_types") or [])
        )
    )
    specialist_subtasks_by_type: dict[str, int] = {}
    for item in stage5_summary_rows:
        for specialist in item.get("specialists") or []:
            subtask_type = str(specialist.get("subtask_type") or "readonly_step_digest")
            specialist_subtasks_by_type[subtask_type] = int(specialist_subtasks_by_type.get(subtask_type, 0)) + 1

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
        SELECT id, task_run_id, parent_agent_run_id, role, status, attempt, assigned_model,
               execution_mode, execution_request_json, source_task_run_id, assigned_step_orders_json,
               assigned_tool_profile, error_summary, cost_tokens_in, cost_tokens_out,
               cost_usd_estimate, created_at, updated_at, started_at, completed_at
        FROM agent_runs
        ORDER BY id DESC
        LIMIT 6;
        """
    )
    recent_agent_runs = [serialize_agent_run_row(row) for row in cur.fetchall()]

    cur.execute("SELECT COUNT(*) AS count FROM evaluator_runs;")
    total_evaluator_runs = int(cur.fetchone()["count"])
    cur.execute(
        """
        SELECT decision, COUNT(*) AS count
        FROM evaluator_runs
        GROUP BY decision
        ORDER BY decision ASC;
        """
    )
    evaluator_runs_by_decision = {str(row["decision"]): int(row["count"]) for row in cur.fetchall()}
    cur.execute(
        """
        SELECT failure_reason, COUNT(*) AS count
        FROM evaluator_runs
        GROUP BY failure_reason
        ORDER BY failure_reason ASC;
        """
    )
    evaluator_runs_by_reason = {str(row["failure_reason"]): int(row["count"]) for row in cur.fetchall()}
    cur.execute(
        """
        SELECT AVG(score) AS avg_score
        FROM evaluator_runs;
        """
    )
    avg_evaluator_score_row = cur.fetchone()
    avg_evaluator_score = float(avg_evaluator_score_row["avg_score"]) if avg_evaluator_score_row and avg_evaluator_score_row["avg_score"] is not None else None
    cur.execute(
        """
        SELECT id, task_run_id, manager_agent_run_id, reviewer_agent_run_id, final_artifact_id, review_artifact_id,
               evaluator_kind, status, decision, score, failure_reason, failure_stage,
               criteria_json, step_stats_json, proposal_json, summary, recommendation,
               source, created_at
        FROM evaluator_runs
        ORDER BY id DESC
        LIMIT 6;
        """
    )
    recent_evaluator_runs = [serialize_evaluator_run_row(row) for row in cur.fetchall()]
    workflow_proposal_rows = list_workflow_proposals_rows(cur, limit=6)
    workflow_proposals_by_action: dict[str, int] = {}
    workflow_proposals_by_priority: dict[str, int] = {}
    for proposal in workflow_proposal_rows:
        action_key = str(proposal.get("action_key") or "unknown")
        priority_key = str(proposal.get("priority") or "unknown")
        workflow_proposals_by_action[action_key] = int(workflow_proposals_by_action.get(action_key, 0)) + 1
        workflow_proposals_by_priority[priority_key] = int(workflow_proposals_by_priority.get(priority_key, 0)) + 1

    cur.execute(
        """
        SELECT COUNT(*) AS count
        FROM evaluator_runs
        WHERE proposal_json IS NOT NULL
          AND proposal_json != '';
        """
    )
    total_workflow_proposals = int(cur.fetchone()["count"])

    cur.execute(
        """
        SELECT COUNT(*) AS count
        FROM evaluator_runs
        WHERE source = 'task_runtime_postrun_v1';
        """
    )
    stage6_mainline_evaluator_run_count = int(cur.fetchone()["count"])
    cur.execute(
        """
        SELECT COUNT(*) AS count
        FROM evaluator_runs
        WHERE source = 'task_runtime_postrun_v1'
          AND proposal_json IS NOT NULL
          AND proposal_json != '';
        """
    )
    stage6_mainline_workflow_proposal_count = int(cur.fetchone()["count"])
    cur.execute(
        """
        SELECT COUNT(*) AS count
        FROM evaluator_runs
        WHERE source = 'task_runtime_postrun_v1'
          AND proposal_json IS NOT NULL
          AND proposal_json != ''
          AND proposal_json::jsonb ->> 'action_key' = 'expand_specialist_scope';
        """
    )
    stage6_auto_mapped_proposal_count = int(cur.fetchone()["count"])
    cur.execute(
        """
        SELECT COUNT(*) AS count
        FROM audit_logs
        WHERE event_type = 'workflow_proposal.change_request_create'
          AND EXISTS (
              SELECT 1
              FROM evaluator_runs
              WHERE evaluator_runs.id = NULLIF(audit_logs.details ->> 'proposal_id', '')::int
                AND evaluator_runs.source = 'task_runtime_postrun_v1'
          );
        """
    )
    stage6_mainline_bridged_change_request_count = int(cur.fetchone()["count"])
    cur.execute(
        """
        SELECT event_type, COUNT(*) AS count
        FROM audit_logs
        WHERE event_type IN (
            'agent.mainline_runtime_fanout',
            'agent.mainline_runtime_fanin',
            'agent.mainline_runtime_execute',
            'workflow_proposal.shadow_validation',
            'workflow_proposal.shadow_validated'
        )
        GROUP BY event_type;
        """
    )
    stage56_audit_counts = {str(row["event_type"]): int(row["count"]) for row in cur.fetchall()}
    stage5_runtime_fanout_event_count = int(stage56_audit_counts.get("agent.mainline_runtime_fanout", 0))
    stage5_runtime_fanin_event_count = int(stage56_audit_counts.get("agent.mainline_runtime_fanin", 0))
    stage5_runtime_execute_event_count = int(stage56_audit_counts.get("agent.mainline_runtime_execute", 0))
    stage6_shadow_validation_count = int(stage56_audit_counts.get("workflow_proposal.shadow_validation", 0)) + int(stage56_audit_counts.get("workflow_proposal.shadow_validated", 0))
    cur.execute(
        """
        SELECT DISTINCT task_id, event_type
        FROM audit_logs
        WHERE task_id IS NOT NULL
          AND event_type IN (
              'agent.mainline_runtime_fanout',
              'agent.mainline_runtime_fanin',
              'agent.mainline_runtime_execute'
          );
        """
    )
    stage56_audit_task_rows = cur.fetchall()
    stage5_runtime_fanout_task_ids = {
        int(row["task_id"])
        for row in stage56_audit_task_rows
        if row.get("task_id") is not None and row.get("event_type") == "agent.mainline_runtime_fanout"
    }
    stage5_runtime_fanin_task_ids = {
        int(row["task_id"])
        for row in stage56_audit_task_rows
        if row.get("task_id") is not None and row.get("event_type") == "agent.mainline_runtime_fanin"
    }
    stage5_runtime_execute_task_ids = {
        int(row["task_id"])
        for row in stage56_audit_task_rows
        if row.get("task_id") is not None and row.get("event_type") == "agent.mainline_runtime_execute"
    }
    stage5_runtime_fanout_task_count = sum(
        1
        for item in mainline_stage5_summary_rows
        if bool(item.get("runtime_fanout_active")) or int(item.get("task_id") or 0) in stage5_runtime_fanout_task_ids
    )
    stage5_terminal_ready_count = sum(
        1
        for item in terminal_mainline_stage5_rows
        if int(((item.get("role_counts") or {}).get("manager") or 0)) >= 1
        and int(((item.get("role_counts") or {}).get("specialist") or 0)) >= 1
        and int(((item.get("role_counts") or {}).get("reviewer") or 0)) >= 1
        and bool((item.get("latest_final_artifact") or {}).get("id"))
        and bool(item.get("latest_workflow_proposal_action"))
        and int(item.get("task_id") or 0) in stage5_runtime_fanout_task_ids
        and int(item.get("task_id") or 0) in stage5_runtime_fanin_task_ids
        and int(item.get("task_id") or 0) in stage5_runtime_execute_task_ids
    )
    cur.execute(
        """
        SELECT COUNT(*) AS count
        FROM evaluator_runs
        WHERE source = 'task_runtime_postrun_v1'
          AND COALESCE(failure_reason, '') != ''
          AND COALESCE(failure_stage, '') != '';
        """
    )
    stage6_failure_taxonomy_count = int(cur.fetchone()["count"])

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
    readiness_metrics = compute_stage_readiness_metrics(
        total_sessions=total_sessions,
        total_session_states=total_session_states,
        total_session_reviews=total_session_reviews,
        active_session_count=active_session_count,
        sessions_missing_state_count=sessions_missing_state_count,
        sessions_missing_review_count=sessions_missing_review_count,
        sessions_needing_review_count=sessions_needing_review_count,
        sessions_with_duplicate_memories_count=sessions_with_duplicate_memories_count,
        sessions_with_open_loops_count=sessions_with_open_loops_count,
        access_actor_count=access_actor_count,
        access_quota_count=access_quota_count,
        quota_pressure_count=quota_pressure_count,
        change_request_total_count=total_change_requests,
        change_request_pending_count=pending_change_requests,
        change_request_approved_count=approved_change_requests,
        change_request_rejected_count=rejected_change_requests,
        change_request_applied_count=applied_change_requests,
        stage5_mainline_task_count=stage5_mainline_task_count,
        stage5_runtime_fanout_task_count=stage5_runtime_fanout_task_count,
        stage5_role_skeleton_ready_count=stage5_role_skeleton_ready_count,
        stage5_terminal_mainline_task_count=stage5_terminal_mainline_task_count,
        stage5_terminal_ready_count=stage5_terminal_ready_count,
        stage6_mainline_evaluator_run_count=stage6_mainline_evaluator_run_count,
        stage6_mainline_workflow_proposal_count=stage6_mainline_workflow_proposal_count,
        stage6_auto_mapped_proposal_count=stage6_auto_mapped_proposal_count,
        stage6_mainline_bridged_change_request_count=stage6_mainline_bridged_change_request_count,
        stage5_non_readonly_specialist_task_count=stage5_non_readonly_specialist_task_count,
        stage5_runtime_fanout_event_count=stage5_runtime_fanout_event_count,
        stage5_runtime_fanin_event_count=stage5_runtime_fanin_event_count,
        stage5_runtime_execute_event_count=stage5_runtime_execute_event_count,
        stage6_failure_taxonomy_count=stage6_failure_taxonomy_count,
        stage6_shadow_validation_count=stage6_shadow_validation_count,
    )
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
            "approved_change_requests": approved_change_requests,
            "rejected_change_requests": rejected_change_requests,
            "applied_change_requests": applied_change_requests,
            "closed_change_requests": closed_change_requests,
            "change_request_closure_ratio": change_request_closure_ratio,
            "enforced_target_types": sorted(DEFAULT_ENFORCED_CHANGE_TARGET_TYPES),
            "enforced_target_count": len(DEFAULT_ENFORCED_CHANGE_TARGET_TYPES),
            "required_gate_target_types": sorted(CHANGE_GATE_REQUIRED_TARGET_TYPES),
            "required_gate_target_count": len(CHANGE_GATE_REQUIRED_TARGET_TYPES),
        },
        "access_metrics": {
            "actor_count": access_actor_count,
            "quota_count": access_quota_count,
            "quota_pressure_count": quota_pressure_count,
            "actors_by_role": actors_by_role,
        },
        "runtime_metadata": {
            "step_request_protocol_version": STEP_REQUEST_PROTOCOL_VERSION,
            "multi_agent_protocol_version": MULTI_AGENT_PROTOCOL_VERSION,
        },
        "agent_metrics": {
            "total_agent_runs": total_agent_runs,
            "running_agent_runs": running_agent_runs,
            "blocked_agent_runs": blocked_agent_runs,
            "agent_runs_by_status": agent_runs_by_status,
            "agent_runs_by_role": agent_runs_by_role,
            "total_agent_messages": total_agent_messages,
            "total_agent_artifacts": total_agent_artifacts,
            "stage5_task_count": len(stage5_summary_rows),
            "specialist_subtasks_by_type": specialist_subtasks_by_type,
            "tasks_requiring_execute": tasks_requiring_execute,
            "tasks_requiring_finalize": tasks_requiring_finalize,
            "tasks_requiring_retry": tasks_requiring_retry,
            "tasks_requiring_operator_escalation": tasks_requiring_operator_escalation,
        },
        "evaluator_metrics": {
            "total_evaluator_runs": total_evaluator_runs,
            "avg_score": avg_evaluator_score,
            "runs_by_decision": evaluator_runs_by_decision,
            "runs_by_reason": evaluator_runs_by_reason,
            "total_workflow_proposals": total_workflow_proposals,
            "workflow_proposals_by_action": workflow_proposals_by_action,
            "workflow_proposals_by_priority": workflow_proposals_by_priority,
        },
        "readiness_metrics": readiness_metrics,
        "recent_audit_logs": recent_audit_logs,
        "recent_tasks": recent_tasks,
        "recent_reviews": recent_reviews,
        "recent_agent_runs": recent_agent_runs,
        "recent_evaluator_runs": recent_evaluator_runs,
        "recent_workflow_proposals": workflow_proposal_rows,
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
    session_row, task_rows, memory_rows, session_state_row, review_rows = load_session_health_context(cur, session_id)
    tasks_by_status: dict[str, int] = {}
    for row in task_rows:
        status = str(row.get("status") or "unknown")
        tasks_by_status[status] = tasks_by_status.get(status, 0) + 1

    total_tasks = len(task_rows)
    total_memories = len(memory_rows)
    memories_by_category: dict[str, int] = {}
    for row in memory_rows:
        category = str(row.get("category") or "unknown")
        memories_by_category[category] = memories_by_category.get(category, 0) + 1

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

    recent_tasks = task_rows[:5]
    last_task_updated_at = recent_tasks[0]["updated_at"] if recent_tasks else None
    session_health = compute_session_health(task_rows, memory_rows, session_state_row, review_rows)

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
        "health": session_health,
        "approval_metrics": {
            "pending_approvals": pending_approvals,
        },
        "recent_tasks": recent_tasks,
    }


@app.get("/sessions/{session_id}/health")
def get_session_health(session_id: int):
    conn = get_conn()
    cur = conn.cursor()
    _session_row, task_rows, memory_rows, session_state_row, review_rows = load_session_health_context(cur, session_id)
    health = compute_session_health(task_rows, memory_rows, session_state_row, review_rows)
    cur.close()
    conn.close()
    return {
        "session_id": session_id,
        "health": health,
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
def list_tasks(session_id: int | None = None, include_stage5_summary: bool = False, limit: int | None = None):
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

    row_limit = max(1, min(int(limit or 60), 200))

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
    rows = cur.fetchall()[:row_limit]

    if include_stage5_summary:
        for row in rows:
            row["stage5"] = fetch_task_agent_summary(cur, int(row["id"]))

    cur.close()
    conn.close()

    return rows


@app.get("/tasks/{task_id}")
def get_task(task_id: int):
    conn = get_conn()
    cur = conn.cursor()
    ensure_agent_tables(cur)
    ensure_evaluator_tables(cur)

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

    if row:
        latest_evaluator = fetch_latest_evaluator_for_task(cur, task_id)
        row["stage5"] = fetch_task_agent_summary(cur, task_id)
        row["latest_evaluator"] = latest_evaluator
        row["latest_workflow_proposal"] = (latest_evaluator or {}).get("workflow_proposal") or {}

    cur.close()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Task not found")

    return row


@app.post("/tasks/{task_id}/agent-runs/bootstrap-demo")
def bootstrap_task_agent_runs(
    task_id: int,
    request: AgentBootstrapRequest,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    specialist_count = max(1, min(int(request.specialist_count or 2), 4))
    objective = request.objective.strip()
    note = request.note.strip()

    conn = get_conn()
    cur = conn.cursor()
    actor = require_actor_permission(cur, x_actor_name, "operate")
    ensure_agent_tables(cur)

    cur.execute(
        """
        SELECT id, user_input, status, session_id, created_at, updated_at
        FROM task_runs
        WHERE id = %s;
        """,
        (task_id,),
    )
    task_row = cur.fetchone()
    if not task_row:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Task not found")

    cur.execute("SELECT COUNT(*) AS count FROM agent_runs WHERE task_run_id = %s;", (task_id,))
    existing_count = int(cur.fetchone()["count"])
    if existing_count > 0:
        cur.close()
        conn.close()
        raise HTTPException(status_code=409, detail="Task already has agent runs; bootstrap-demo is single-use per task")

    manager_objective = objective or str(task_row["user_input"] or "").strip()
    plan_payload = {
        "protocol_version": MULTI_AGENT_PROTOCOL_VERSION,
        "task_id": task_id,
        "task_status": task_row["status"],
        "objective": manager_objective,
        "fan_out_strategy": f"manager + {specialist_count} specialist" + (" + reviewer" if request.include_reviewer else ""),
        "fallback_strategy": "degrade_to_single_agent_or_escalate",
        "note": note,
    }
    manager_plan_artifact_id = create_agent_artifact(
        cur,
        task_id,
        None,
        "plan",
        "bootstrap demo manager plan",
        {
            **plan_payload,
            "subtasks": [
                {
                    "role": "specialist",
                    "slot": index + 1,
                    "scope": f"子问题 {index + 1}",
                }
                for index in range(specialist_count)
            ],
        },
    )
    manager_run_id = create_agent_run(
        cur,
        task_id,
        "manager",
        "completed",
        brief_artifact_id=manager_plan_artifact_id,
        output_artifact_id=manager_plan_artifact_id,
        assigned_model="planning-default",
        assigned_tool_profile="manager-only",
        started=True,
        completed=True,
    )

    created_agent_run_ids = [manager_run_id]
    created_message_ids: list[int] = []
    created_artifact_ids = [manager_plan_artifact_id]
    specialist_run_ids: list[int] = []

    for index in range(specialist_count):
        slot = index + 1
        execution_request = build_specialist_execution_request(
            slot=slot,
            manager_objective=manager_objective,
            assigned_steps=[],
            plan_artifact_id=manager_plan_artifact_id,
            note=request.note.strip(),
        )
        brief_artifact_id = create_agent_artifact(
            cur,
            task_id,
            None,
            "brief",
            f"specialist-{slot} brief",
            {
                "protocol_version": MULTI_AGENT_PROTOCOL_VERSION,
                "objective": manager_objective,
                "scope": f"子问题 {slot}",
                "constraints": ["遵守当前 task scope", "不要直接给最终结论"],
                "success_criteria": [f"完成子问题 {slot} 的可交付草稿"],
                "input_refs": [{"artifact_id": manager_plan_artifact_id, "label": "manager_plan"}],
                "execution_request": execution_request,
            },
        )
        specialist_run_id = create_agent_run(
            cur,
            task_id,
            "specialist",
            "queued",
            parent_agent_run_id=manager_run_id,
            brief_artifact_id=brief_artifact_id,
            execution_mode="api_readonly_subtask_v1",
            execution_request={
                **execution_request,
                "evidence_refs": execution_request["evidence_refs"] + [{"artifact_id": brief_artifact_id, "label": "specialist_brief"}],
            },
            source_task_run_id=task_id,
            assigned_step_orders=[],
            assigned_model=f"specialist-default-{slot}",
            assigned_tool_profile="specialist-readonly",
        )
        specialist_run_ids.append(specialist_run_id)
        created_agent_run_ids.append(specialist_run_id)
        created_artifact_ids.append(brief_artifact_id)
        created_message_ids.append(
            create_agent_message(
                cur,
                task_id,
                specialist_run_id,
                "manager",
                "specialist",
                "brief",
                {
                    "protocol_version": MULTI_AGENT_PROTOCOL_VERSION,
                    "task_run_id": task_id,
                    "agent_run_id": specialist_run_id,
                    "sender_role": "manager",
                    "recipient_role": "specialist",
                    "slot": slot,
                    "brief_artifact_id": brief_artifact_id,
                    "execution_request": {
                        **execution_request,
                        "evidence_refs": execution_request["evidence_refs"] + [{"artifact_id": brief_artifact_id, "label": "specialist_brief"}],
                    },
                },
            )
        )

    reviewer_run_id = None
    if request.include_reviewer:
        review_artifact_id = create_agent_artifact(
            cur,
            task_id,
            None,
            "review",
            "reviewer handoff placeholder",
            {
                "protocol_version": MULTI_AGENT_PROTOCOL_VERSION,
                "objective": "在 specialist 草稿完成后独立审查 manager 汇总",
                "decision": "pending",
                "blocking_issues": [],
                "follow_up_actions": ["等待 specialist draft", "等待 manager final candidate"],
            },
        )
        reviewer_run_id = create_agent_run(
            cur,
            task_id,
            "reviewer",
            "planned",
            parent_agent_run_id=manager_run_id,
            review_artifact_id=review_artifact_id,
            source_task_run_id=task_id,
            assigned_model="review-default",
            assigned_tool_profile="review-readonly",
        )
        created_agent_run_ids.append(reviewer_run_id)
        created_artifact_ids.append(review_artifact_id)
        created_message_ids.append(
            create_agent_message(
                cur,
                task_id,
                reviewer_run_id,
                "manager",
                "reviewer",
                "handoff",
                {
                    "protocol_version": MULTI_AGENT_PROTOCOL_VERSION,
                    "task_run_id": task_id,
                    "agent_run_id": reviewer_run_id,
                    "sender_role": "manager",
                    "recipient_role": "reviewer",
                    "depends_on_agent_run_ids": specialist_run_ids,
                    "review_status": "pending_inputs",
                },
            )
        )

    insert_audit_log(
        cur,
        "agent.bootstrap_demo",
        actor["actor_name"],
        task_id,
        {
            "task_id": task_id,
            "manager_run_id": manager_run_id,
            "specialist_run_ids": specialist_run_ids,
            "reviewer_run_id": reviewer_run_id,
            "specialist_count": specialist_count,
            "include_reviewer": bool(request.include_reviewer),
            "objective": manager_objective,
        },
    )
    conn.commit()
    cur.close()
    conn.close()
    logger.info(
        "agent bootstrap demo created task_id=%s manager_run_id=%s specialist_count=%s reviewer=%s actor=%s",
        task_id,
        manager_run_id,
        specialist_count,
        bool(request.include_reviewer),
        actor["actor_name"],
    )
    return {
        "message": "agent bootstrap demo created",
        "task_id": task_id,
        "manager_run_id": manager_run_id,
        "specialist_run_ids": specialist_run_ids,
        "reviewer_run_id": reviewer_run_id,
        "created_agent_run_count": len(created_agent_run_ids),
        "created_message_count": len(created_message_ids),
        "created_artifact_count": len(created_artifact_ids),
    }


@app.post("/tasks/{task_id}/agent-runs/execute-demo")
def execute_task_agent_runs(
    task_id: int,
    request: AgentExecuteRequest,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    note = request.note.strip()
    force_rerun = bool(request.force_rerun)

    conn = get_conn()
    cur = conn.cursor()
    actor = require_actor_permission(cur, x_actor_name, "operate")
    ensure_agent_tables(cur)

    cur.execute(
        """
        SELECT id, user_input, status, result, error_message, created_at, updated_at
        FROM task_runs
        WHERE id = %s;
        """,
        (task_id,),
    )
    task_row = cur.fetchone()
    if not task_row:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Task not found")

    cur.execute(
        """
        SELECT id, task_run_id, parent_agent_run_id, role, status, attempt, brief_artifact_id,
               output_artifact_id, review_artifact_id, execution_mode, execution_request_json,
               source_task_run_id, assigned_step_orders_json, assigned_model, assigned_tool_profile,
               error_summary, cost_tokens_in, cost_tokens_out, cost_usd_estimate,
               created_at, updated_at, started_at, completed_at
        FROM agent_runs
        WHERE task_run_id = %s
        ORDER BY id ASC;
        """,
        (task_id,),
    )
    agent_rows = cur.fetchall()
    if not agent_rows:
        cur.close()
        conn.close()
        raise HTTPException(status_code=409, detail="Task has no agent runs; bootstrap-demo first")

    manager_row = next((row for row in agent_rows if row["role"] == "manager"), None)
    specialist_rows = [row for row in agent_rows if row["role"] == "specialist"]
    if not manager_row or not specialist_rows:
        cur.close()
        conn.close()
        raise HTTPException(status_code=409, detail="Task is missing manager or specialist agent runs")

    cur.execute(
        """
        SELECT step_order, step_name, status, tool_name, input_payload, output_payload, error_message
        FROM task_steps
        WHERE task_id = %s
        ORDER BY step_order ASC;
        """,
        (task_id,),
    )
    step_rows = cur.fetchall()
    cur.execute(
        """
        SELECT id, agent_run_id, artifact_type, summary, content_json, version, created_at
        FROM agent_artifacts
        WHERE task_run_id = %s
        ORDER BY id ASC;
        """,
        (task_id,),
    )
    artifact_rows = [serialize_agent_artifact_row(row) for row in cur.fetchall()]
    artifact_by_id = {int(item["id"]): item for item in artifact_rows}
    plan_artifact = next((item for item in artifact_rows if item["artifact_type"] == "plan"), None)

    manager_objective = str(task_row["user_input"] or "").strip()
    step_outline, specialist_step_partitions, step_status_counts = build_specialist_step_partitions(
        step_rows=step_rows,
        specialist_count=len(specialist_rows),
        task_row=task_row,
    )

    created_artifact_ids: list[int] = []
    created_message_ids: list[int] = []
    executed_specialist_ids: list[int] = []
    skipped_specialist_ids: list[int] = []
    retried_specialist_ids: list[int] = []

    for index, specialist_row in enumerate(specialist_rows, start=1):
        existing_output_artifact_id = specialist_row.get("output_artifact_id")
        if existing_output_artifact_id and not force_rerun:
            skipped_specialist_ids.append(int(specialist_row["id"]))
            continue
        artifact_version = 1
        next_attempt = int(specialist_row.get("attempt") or 1)
        if existing_output_artifact_id:
            existing_output_artifact = artifact_by_id.get(int(existing_output_artifact_id))
            artifact_version = int((existing_output_artifact or {}).get("version") or 1) + 1
            next_attempt += 1
            retried_specialist_ids.append(int(specialist_row["id"]))
        assigned_steps = specialist_step_partitions[index - 1]
        execution_request = build_specialist_execution_request(
            slot=index,
            manager_objective=manager_objective,
            assigned_steps=assigned_steps,
            brief_artifact_id=specialist_row.get("brief_artifact_id"),
            plan_artifact_id=plan_artifact["id"] if plan_artifact else None,
            note=note,
            execution_mode="worker_readonly_v1",
        )
        cur.execute(
            """
            UPDATE agent_runs
            SET status = 'running',
                execution_mode = %s,
                execution_request_json = %s,
                source_task_run_id = %s,
                assigned_step_orders_json = %s,
                started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                completed_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s;
            """,
            (
                "api_readonly_subtask_v1",
                safe_json_dumps(execution_request),
                task_id,
                safe_json_dumps(execution_request.get("assigned_step_orders") or []),
                specialist_row["id"],
            ),
        )
        created_message_ids.append(
            create_agent_message(
                cur,
                task_id,
                specialist_row["id"],
                "manager",
                "specialist",
                "handoff",
                {
                    "protocol_version": MULTI_AGENT_PROTOCOL_VERSION,
                    "task_run_id": task_id,
                    "subtask_type": "readonly_step_digest",
                    "execution_mode": "api_readonly_subtask_v1",
                    "assigned_step_orders": [int(step.get("step_order") or 0) for step in assigned_steps if int(step.get("step_order") or 0) > 0],
                    "manager_objective": manager_objective,
                    "note": note,
                    "force_rerun": force_rerun,
                    "execution_request": execution_request,
                },
            )
        )
        created_message_ids.append(
            create_agent_message(
                cur,
                task_id,
                specialist_row["id"],
                "specialist",
                "manager",
                "progress",
                {
                    "protocol_version": MULTI_AGENT_PROTOCOL_VERSION,
                    "status": "running",
                    "execution_mode": "api_readonly_subtask_v1",
                    "subtask_type": "readonly_step_digest",
                    "assigned_step_orders": [int(step.get("step_order") or 0) for step in assigned_steps if int(step.get("step_order") or 0) > 0],
                    "summary": f"specialist-{index} started readonly subtask",
                },
            )
        )
        draft_payload = build_specialist_draft_payload(
            slot=index,
            task_id=task_id,
            agent_run_id=int(specialist_row["id"]),
            manager_objective=manager_objective,
            task_row=task_row,
            step_outline=step_outline,
            assigned_steps=assigned_steps,
            plan_artifact_id=plan_artifact["id"] if plan_artifact else None,
            note=note,
            step_status_counts=step_status_counts,
            execution_request=execution_request,
        )
        draft_artifact_id = create_agent_artifact(
            cur,
            task_id,
            specialist_row["id"],
            "draft",
            f"specialist-{index} draft",
            draft_payload,
            version=artifact_version,
        )
        created_artifact_ids.append(draft_artifact_id)
        executed_specialist_ids.append(int(specialist_row["id"]))
        cur.execute(
            """
            UPDATE agent_runs
            SET status = 'completed',
                attempt = %s,
                output_artifact_id = %s,
                execution_mode = %s,
                execution_request_json = %s,
                source_task_run_id = %s,
                assigned_step_orders_json = %s,
                error_summary = '',
                started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                completed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s;
            """,
            (
                next_attempt,
                draft_artifact_id,
                "api_readonly_subtask_v1",
                safe_json_dumps(execution_request),
                task_id,
                safe_json_dumps(execution_request.get("assigned_step_orders") or []),
                specialist_row["id"],
            ),
        )
        created_message_ids.append(
            create_agent_message(
                cur,
                task_id,
                specialist_row["id"],
                "specialist",
                "manager",
                "result",
                {
                    "protocol_version": MULTI_AGENT_PROTOCOL_VERSION,
                    "status": "completed",
                    "artifact_ids": [draft_artifact_id],
                    "summary": f"specialist-{index} draft",
                    "needs_human_review": False,
                },
            )
        )

    reviewer_row = next((row for row in agent_rows if row["role"] == "reviewer"), None)
    if reviewer_row and executed_specialist_ids:
        cur.execute(
            """
            UPDATE agent_runs
            SET status = CASE
                    WHEN status IN ('planned', 'queued') THEN 'queued'
                    ELSE status
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s;
            """,
            (reviewer_row["id"],),
        )
        created_message_ids.append(
            create_agent_message(
                cur,
                task_id,
                reviewer_row["id"],
                "manager",
                "reviewer",
                "handoff",
                {
                    "protocol_version": MULTI_AGENT_PROTOCOL_VERSION,
                    "task_run_id": task_id,
                    "review_status": "ready_for_review",
                    "depends_on_specialist_ids": executed_specialist_ids,
                    "summary": "specialist outputs ready for reviewer",
                },
            )
        )

    insert_audit_log(
        cur,
        "agent.execute_demo",
        actor["actor_name"],
        task_id,
        {
            "task_id": task_id,
            "manager_run_id": int(manager_row["id"]),
            "executed_specialist_ids": executed_specialist_ids,
            "skipped_specialist_ids": skipped_specialist_ids,
            "retried_specialist_ids": retried_specialist_ids,
            "created_artifact_count": len(created_artifact_ids),
            "force_rerun": force_rerun,
        },
    )
    conn.commit()
    cur.close()
    conn.close()
    logger.info(
        "agent execute demo completed task_id=%s executed_specialists=%s skipped_specialists=%s actor=%s",
        task_id,
        len(executed_specialist_ids),
        len(skipped_specialist_ids),
        actor["actor_name"],
    )
    return {
        "message": "agent execute demo completed",
        "task_id": task_id,
        "executed_specialist_ids": executed_specialist_ids,
        "skipped_specialist_ids": skipped_specialist_ids,
        "retried_specialist_ids": retried_specialist_ids,
        "created_message_count": len(created_message_ids),
        "created_artifact_count": len(created_artifact_ids),
        "execution_mode": "api_readonly_subtask_v1",
        "force_rerun": force_rerun,
    }


@app.post("/tasks/{task_id}/agent-runs/execute-worker-demo")
def execute_task_agent_runs_via_worker(
    task_id: int,
    request: AgentExecuteRequest,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    note = request.note.strip()
    force_rerun = bool(request.force_rerun)
    subtask_type = (request.subtask_type or "readonly_step_digest").strip() or "readonly_step_digest"
    if subtask_type not in {"readonly_step_digest", "readonly_source_snapshot", "readonly_task_snapshot"}:
        raise HTTPException(status_code=400, detail="subtask_type must be readonly_step_digest, readonly_source_snapshot, or readonly_task_snapshot")
    source_payload = {
        "kind": (request.source_kind or "").strip(),
        "path": (request.source_path or "").strip(),
        "json_path": (request.source_json_path or "").strip(),
        "dir_limit": max(1, min(int(request.dir_limit or 20), 200)),
    }
    if subtask_type == "readonly_source_snapshot":
        if source_payload["kind"] not in {"text_file", "json_file", "directory"}:
            raise HTTPException(status_code=400, detail="readonly_source_snapshot requires source_kind=text_file|json_file|directory")
        if not source_payload["path"]:
            raise HTTPException(status_code=400, detail="readonly_source_snapshot requires source_path")

    conn = get_conn()
    cur = conn.cursor()
    actor = require_actor_permission(cur, x_actor_name, "operate")
    ensure_agent_tables(cur)

    cur.execute("SELECT id, user_input, status FROM task_runs WHERE id = %s;", (task_id,))
    task_row = cur.fetchone()
    if not task_row:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Task not found")

    cur.execute(
        """
        SELECT id, task_run_id, parent_agent_run_id, role, status, attempt, brief_artifact_id,
               output_artifact_id, review_artifact_id, execution_mode, execution_request_json,
               source_task_run_id, assigned_step_orders_json, assigned_model, assigned_tool_profile,
               error_summary, cost_tokens_in, cost_tokens_out, cost_usd_estimate,
               created_at, updated_at, started_at, completed_at
        FROM agent_runs
        WHERE task_run_id = %s
        ORDER BY id ASC;
        """,
        (task_id,),
    )
    agent_rows = cur.fetchall()
    manager_row = next((row for row in agent_rows if row["role"] == "manager"), None)
    specialist_rows = [row for row in agent_rows if row["role"] == "specialist"]
    if not manager_row or not specialist_rows:
        cur.close()
        conn.close()
        raise HTTPException(status_code=409, detail="Task is missing manager or specialist agent runs")

    cur.execute(
        """
        SELECT step_order, step_name, status, tool_name, input_payload, output_payload, error_message
        FROM task_steps
        WHERE task_id = %s
        ORDER BY step_order ASC;
        """,
        (task_id,),
    )
    step_rows = cur.fetchall()
    cur.execute(
        """
        SELECT id, agent_run_id, artifact_type, summary, content_json, version, created_at
        FROM agent_artifacts
        WHERE task_run_id = %s
        ORDER BY id ASC;
        """,
        (task_id,),
    )
    artifact_rows = [serialize_agent_artifact_row(row) for row in cur.fetchall()]
    plan_artifact = next((item for item in artifact_rows if item["artifact_type"] == "plan"), None)
    manager_objective = str(task_row["user_input"] or "").strip()
    _, specialist_step_partitions, _ = build_specialist_step_partitions(
        step_rows=step_rows,
        specialist_count=len(specialist_rows),
        task_row=task_row,
    )

    queued_specialist_ids: list[int] = []
    skipped_specialist_ids: list[int] = []
    created_message_ids: list[int] = []
    retried_specialist_ids: list[int] = []
    for index, specialist_row in enumerate(specialist_rows, start=1):
        existing_output_artifact_id = specialist_row.get("output_artifact_id")
        if existing_output_artifact_id and not force_rerun:
            skipped_specialist_ids.append(int(specialist_row["id"]))
            continue
        if existing_output_artifact_id:
            retried_specialist_ids.append(int(specialist_row["id"]))
        assigned_steps = specialist_step_partitions[index - 1]
        execution_request = build_specialist_execution_request(
            slot=index,
            manager_objective=manager_objective,
            assigned_steps=assigned_steps,
            brief_artifact_id=specialist_row.get("brief_artifact_id"),
            plan_artifact_id=plan_artifact["id"] if plan_artifact else None,
            note=note,
            execution_mode="worker_readonly_v1",
            subtask_type=subtask_type,
            source=source_payload if subtask_type == "readonly_source_snapshot" else None,
        )
        cur.execute(
            """
            UPDATE agent_runs
            SET status = 'queued',
                execution_mode = %s,
                execution_request_json = %s,
                source_task_run_id = %s,
                assigned_step_orders_json = %s,
                updated_at = CURRENT_TIMESTAMP,
                completed_at = NULL
            WHERE id = %s;
            """,
            (
                "worker_readonly_v1",
                safe_json_dumps(execution_request),
                task_id,
                safe_json_dumps(execution_request.get("assigned_step_orders") or []),
                specialist_row["id"],
            ),
        )
        created_message_ids.append(
            create_agent_message(
                cur,
                task_id,
                specialist_row["id"],
                "manager",
                "specialist",
                "handoff",
                {
                    "protocol_version": MULTI_AGENT_PROTOCOL_VERSION,
                    "task_run_id": task_id,
                    "execution_mode": "worker_readonly_v1",
                    "subtask_type": subtask_type,
                    "execution_request": execution_request,
                    "force_rerun": force_rerun,
                },
            )
        )
        queued_specialist_ids.append(int(specialist_row["id"]))
        enqueue_agent_run(int(specialist_row["id"]))

    insert_audit_log(
        cur,
        "agent.execute_worker_demo",
        actor["actor_name"],
        task_id,
        {
            "task_id": task_id,
            "manager_run_id": int(manager_row["id"]),
            "queued_specialist_ids": queued_specialist_ids,
            "skipped_specialist_ids": skipped_specialist_ids,
            "retried_specialist_ids": retried_specialist_ids,
            "force_rerun": force_rerun,
        },
    )
    conn.commit()
    cur.close()
    conn.close()
    return {
        "message": "agent worker execute demo queued",
        "task_id": task_id,
        "queued_specialist_ids": queued_specialist_ids,
        "skipped_specialist_ids": skipped_specialist_ids,
        "retried_specialist_ids": retried_specialist_ids,
        "created_message_count": len(created_message_ids),
        "execution_mode": "worker_readonly_v1",
        "subtask_type": subtask_type,
        "execution_backend": "worker",
        "dispatch_mode": "worker_queue",
    }


@app.post("/tasks/{task_id}/agent-runs/finalize-demo")
def finalize_task_agent_runs(
    task_id: int,
    request: AgentFinalizeRequest,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    summary = request.summary.strip()
    note = request.note.strip()
    requested_reviewer_decision = request.reviewer_decision.strip().lower() or "auto"
    allow_retry = bool(request.allow_retry)
    if requested_reviewer_decision not in {"auto", "approved", "rework_required", "rejected"}:
        raise HTTPException(status_code=400, detail="reviewer_decision must be auto, approved, rework_required, or rejected")

    conn = get_conn()
    cur = conn.cursor()
    actor = require_actor_permission(cur, x_actor_name, "operate")
    ensure_agent_tables(cur)

    cur.execute(
        """
        SELECT id, user_input, status, result, error_message, created_at, updated_at
        FROM task_runs
        WHERE id = %s;
        """,
        (task_id,),
    )
    task_row = cur.fetchone()
    if not task_row:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Task not found")

    cur.execute(
        """
        SELECT id, task_run_id, parent_agent_run_id, role, status, attempt, brief_artifact_id,
               output_artifact_id, review_artifact_id, execution_mode, execution_request_json,
               source_task_run_id, assigned_step_orders_json, assigned_model, assigned_tool_profile,
               error_summary, cost_tokens_in, cost_tokens_out, cost_usd_estimate,
               created_at, updated_at, started_at, completed_at
        FROM agent_runs
        WHERE task_run_id = %s
        ORDER BY id ASC;
        """,
        (task_id,),
    )
    agent_rows = cur.fetchall()
    if not agent_rows:
        cur.close()
        conn.close()
        raise HTTPException(status_code=409, detail="Task has no agent runs; bootstrap-demo first")

    manager_row = next((row for row in agent_rows if row["role"] == "manager"), None)
    specialist_rows = [row for row in agent_rows if row["role"] == "specialist"]
    reviewer_row = next((row for row in agent_rows if row["role"] == "reviewer"), None)
    if not manager_row or not specialist_rows:
        cur.close()
        conn.close()
        raise HTTPException(status_code=409, detail="Task is missing manager or specialist agent runs")

    cur.execute(
        """
        SELECT step_order, step_name, status, tool_name, input_payload, output_payload, error_message
        FROM task_steps
        WHERE task_id = %s
        ORDER BY step_order ASC;
        """,
        (task_id,),
    )
    step_rows = cur.fetchall()

    cur.execute(
        """
        SELECT id, agent_run_id, artifact_type, summary, content_json, version, created_at
        FROM agent_artifacts
        WHERE task_run_id = %s
        ORDER BY id ASC;
        """,
        (task_id,),
    )
    artifact_rows = [serialize_agent_artifact_row(row) for row in cur.fetchall()]
    artifact_by_id = {int(item["id"]): item for item in artifact_rows}
    final_artifacts = [item for item in artifact_rows if item["artifact_type"] == "final"]
    review_artifacts = [item for item in artifact_rows if item["artifact_type"] == "review"]
    existing_final = final_artifacts[-1] if final_artifacts else None
    if existing_final and not allow_retry:
        cur.close()
        conn.close()
        raise HTTPException(status_code=409, detail="Task already has a final artifact; finalize-demo is single-use per task")
    if existing_final and allow_retry and str(manager_row.get("status") or "") != "blocked":
        cur.close()
        conn.close()
        raise HTTPException(status_code=409, detail="allow_retry 仅支持 blocked manager 的返工重汇总")

    plan_artifact = next((item for item in artifact_rows if item["artifact_type"] == "plan"), None)
    next_final_version = max((int(item.get("version") or 1) for item in final_artifacts), default=0) + 1
    next_review_version = max((int(item.get("version") or 1) for item in review_artifacts), default=0) + 1
    created_artifact_ids: list[int] = []
    created_message_ids: list[int] = []
    specialist_draft_ids: list[int] = []

    manager_objective = summary or str(task_row["user_input"] or "").strip()
    step_outline, specialist_step_partitions, step_status_counts = build_specialist_step_partitions(
        step_rows=step_rows,
        specialist_count=len(specialist_rows),
        task_row=task_row,
    )

    for index, specialist_row in enumerate(specialist_rows, start=1):
        existing_output_artifact_id = specialist_row.get("output_artifact_id")
        if existing_output_artifact_id:
            specialist_draft_ids.append(int(existing_output_artifact_id))
            continue
        draft_summary = f"specialist-{index} draft"
        assigned_steps = specialist_step_partitions[index - 1]
        execution_request = build_specialist_execution_request(
            slot=index,
            manager_objective=manager_objective,
            assigned_steps=assigned_steps,
            brief_artifact_id=specialist_row.get("brief_artifact_id"),
            plan_artifact_id=plan_artifact["id"] if plan_artifact else None,
            note=note,
        )
        existing_output_artifact = artifact_by_id.get(int(existing_output_artifact_id)) if existing_output_artifact_id else None
        draft_version = int((existing_output_artifact or {}).get("version") or 0) + 1
        created_message_ids.append(
            create_agent_message(
                cur,
                task_id,
                specialist_row["id"],
                "manager",
                "specialist",
                "handoff",
                {
                    "protocol_version": MULTI_AGENT_PROTOCOL_VERSION,
                    "task_run_id": task_id,
                    "subtask_type": "readonly_step_digest",
                    "execution_mode": "api_readonly_subtask_v1",
                    "assigned_step_orders": [int(step.get("step_order") or 0) for step in assigned_steps if int(step.get("step_order") or 0) > 0],
                    "manager_objective": manager_objective,
                    "note": note,
                    "force_rerun": False,
                    "execution_request": execution_request,
                },
            )
        )
        draft_payload = build_specialist_draft_payload(
            slot=index,
            task_id=task_id,
            agent_run_id=int(specialist_row["id"]),
            manager_objective=manager_objective,
            task_row=task_row,
            step_outline=step_outline,
            assigned_steps=assigned_steps,
            plan_artifact_id=plan_artifact["id"] if plan_artifact else None,
            note=note,
            step_status_counts=step_status_counts,
            execution_request=execution_request,
        )
        draft_artifact_id = create_agent_artifact(
            cur,
            task_id,
            specialist_row["id"],
            "draft",
            draft_summary,
            draft_payload,
            version=draft_version,
        )
        specialist_draft_ids.append(draft_artifact_id)
        created_artifact_ids.append(draft_artifact_id)
        cur.execute(
            """
            UPDATE agent_runs
            SET status = 'completed',
                attempt = attempt + 1,
                output_artifact_id = %s,
                execution_mode = %s,
                execution_request_json = %s,
                source_task_run_id = %s,
                assigned_step_orders_json = %s,
                error_summary = '',
                started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                completed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s;
            """,
            (
                draft_artifact_id,
                "api_readonly_subtask_v1",
                safe_json_dumps(execution_request),
                task_id,
                safe_json_dumps(execution_request.get("assigned_step_orders") or []),
                specialist_row["id"],
            ),
        )
        created_message_ids.append(
            create_agent_message(
                cur,
                task_id,
                specialist_row["id"],
                "specialist",
                "manager",
                "result",
                {
                    "protocol_version": MULTI_AGENT_PROTOCOL_VERSION,
                    "status": "completed",
                    "artifact_ids": [draft_artifact_id],
                    "summary": draft_summary,
                    "needs_human_review": False,
                },
            )
        )

    review_artifact_id = None
    evaluator_run_id = None
    review_status = "not_requested"
    manager_status = "completed"
    manager_error_summary = ""
    next_strategy = "complete"
    reviewer_decision, decision_source = resolve_reviewer_decision(
        requested_decision=requested_reviewer_decision,
        task_status=str(task_row["status"]),
        step_rows=step_rows,
        specialist_draft_count=len(specialist_rows),
    )
    quality_bundle = build_demo_review_criteria(
        task_status=str(task_row["status"]),
        step_rows=step_rows,
        specialist_draft_count=len(specialist_rows),
        reviewer_decision=reviewer_decision,
    )
    failure_profile = derive_evaluator_failure_profile(
        task_status=str(task_row["status"]),
        step_rows=step_rows,
        specialist_draft_count=len(specialist_rows),
        reviewer_decision=reviewer_decision,
    )
    if reviewer_row:
        review_status = reviewer_decision
        blocking_issues = []
        follow_up_actions = []
        reasoning_summary = "bootstrap finalize demo 自动汇总后通过 reviewer 占位校验"
        if reviewer_decision == "rework_required":
            blocking_issues = ["reviewer 要求 manager 根据 specialist drafts 再做一轮返工"]
            follow_up_actions = ["补充 specialist draft 细节", "重新汇总 final candidate"]
            reasoning_summary = "reviewer 认为当前 drafts 已形成基础结果，但还需要返工后再提交"
            manager_status = "blocked"
            manager_error_summary = "reviewer requested rework"
            next_strategy = "retry_specialists"
        elif reviewer_decision == "rejected":
            blocking_issues = ["reviewer 拒绝当前 manager final candidate"]
            follow_up_actions = ["回退到 specialist 重新拆解", "必要时升级人工审批"]
            reasoning_summary = "reviewer 拒绝当前汇总结果，需要停止并重新规划"
            manager_status = "failed"
            manager_error_summary = "reviewer rejected final candidate"
            next_strategy = "escalate_to_operator"
        review_payload = {
            "protocol_version": MULTI_AGENT_PROTOCOL_VERSION,
            "decision": reviewer_decision,
            "reasoning_summary": reasoning_summary,
            "blocking_issues": blocking_issues,
            "follow_up_actions": follow_up_actions,
            "source_artifact_refs": specialist_draft_ids,
            "quality_criteria": quality_bundle["criteria"],
            "quality_score": quality_bundle["score"],
            "step_stats": quality_bundle["step_stats"],
            "failure_reason": failure_profile["failure_reason"],
            "failure_stage": failure_profile["failure_stage"],
            "decision_source": decision_source,
            "requested_decision": requested_reviewer_decision,
            "note": note,
        }
        review_artifact_id = create_agent_artifact(
            cur,
            task_id,
            reviewer_row["id"],
            "review",
            "reviewer decision",
            review_payload,
            version=next_review_version,
        )
        created_artifact_ids.append(review_artifact_id)
        cur.execute(
            """
            UPDATE agent_runs
            SET status = 'completed',
                review_artifact_id = %s,
                started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                completed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s;
            """,
            (review_artifact_id, reviewer_row["id"]),
        )
        created_message_ids.append(
            create_agent_message(
                cur,
                task_id,
                reviewer_row["id"],
                "reviewer",
                "manager",
                "review_decision",
                {
                    "protocol_version": MULTI_AGENT_PROTOCOL_VERSION,
                    "decision": reviewer_decision,
                    "reasoning_summary": reasoning_summary,
                    "blocking_issues": blocking_issues,
                    "follow_up_actions": follow_up_actions,
                    "quality_score": quality_bundle["score"],
                    "quality_criteria": quality_bundle["criteria"],
                    "failure_reason": failure_profile["failure_reason"],
                    "failure_stage": failure_profile["failure_stage"],
                    "decision_source": decision_source,
                    "requested_decision": requested_reviewer_decision,
                },
            )
        )
        if reviewer_decision == "rework_required":
            for specialist_row in specialist_rows:
                created_message_ids.append(
                    create_agent_message(
                        cur,
                        task_id,
                        specialist_row["id"],
                        "manager",
                        "specialist",
                        "handoff",
                        {
                            "protocol_version": MULTI_AGENT_PROTOCOL_VERSION,
                            "task_run_id": task_id,
                            "reviewer_decision": reviewer_decision,
                            "follow_up_actions": follow_up_actions,
                            "manager_next_strategy": next_strategy,
                        },
                    )
                )

    final_artifact_payload = {
        "protocol_version": MULTI_AGENT_PROTOCOL_VERSION,
        "summary": summary or "manager 汇总了 specialist drafts 并生成 final artifact",
        "final_output": {
            "task_id": task_id,
            "objective": manager_objective,
            "specialist_draft_count": len(specialist_draft_ids),
            "review_status": review_status,
            "note": note,
            "task_status": task_row["status"],
            "step_count": len(step_rows),
            "next_strategy": next_strategy,
            "quality_score": quality_bundle["score"],
            "failure_reason": failure_profile["failure_reason"],
            "failure_stage": failure_profile["failure_stage"],
            "decision_source": decision_source,
        },
        "source_artifact_refs": specialist_draft_ids,
        "review_status": review_status,
        "next_strategy": next_strategy,
        "quality_criteria": quality_bundle["criteria"],
        "quality_score": quality_bundle["score"],
        "step_stats": quality_bundle["step_stats"],
        "failure_reason": failure_profile["failure_reason"],
        "failure_stage": failure_profile["failure_stage"],
        "decision_source": decision_source,
        "requested_decision": requested_reviewer_decision,
    }
    final_artifact_id = create_agent_artifact(
        cur,
        task_id,
        manager_row["id"],
        "final",
        "manager final artifact",
        final_artifact_payload,
        version=next_final_version,
    )
    created_artifact_ids.append(final_artifact_id)
    cur.execute(
        """
        UPDATE agent_runs
        SET status = %s,
            output_artifact_id = %s,
            error_summary = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s;
        """,
        (manager_status, final_artifact_id, manager_error_summary, manager_row["id"]),
    )
    created_message_ids.append(
        create_agent_message(
            cur,
            task_id,
            manager_row["id"],
            "manager",
            "operator",
            "result",
            {
                "protocol_version": MULTI_AGENT_PROTOCOL_VERSION,
                "status": manager_status,
                "artifact_ids": [final_artifact_id],
                "summary": final_artifact_payload["summary"],
                "needs_human_review": reviewer_decision != "approved",
                "next_strategy": next_strategy,
                "quality_score": quality_bundle["score"],
                "failure_reason": failure_profile["failure_reason"],
                "failure_stage": failure_profile["failure_stage"],
                "final_artifact_version": next_final_version,
                "decision_source": decision_source,
            },
        )
    )
    if reviewer_decision == "rejected":
        created_message_ids.append(
            create_agent_message(
                cur,
                task_id,
                manager_row["id"],
                "manager",
                "operator",
                "escalation",
                {
                    "protocol_version": MULTI_AGENT_PROTOCOL_VERSION,
                    "task_run_id": task_id,
                    "reviewer_decision": reviewer_decision,
                    "review_artifact_id": review_artifact_id,
                    "final_artifact_id": final_artifact_id,
                    "next_strategy": next_strategy,
                },
            )
        )

    evaluator_summary = f"{failure_profile['summary']} score={quality_bundle['score']} decision={reviewer_decision}"
    evaluator_recommendation = failure_profile["recommendation"]
    workflow_proposal = build_workflow_proposal(
        task_id=task_id,
        reviewer_decision=reviewer_decision,
        failure_profile=failure_profile,
        quality_bundle=quality_bundle,
        next_strategy=next_strategy,
    )
    evaluator_run_id = create_evaluator_run(
        cur,
        task_run_id=task_id,
        manager_agent_run_id=int(manager_row["id"]),
        reviewer_agent_run_id=int(reviewer_row["id"]) if reviewer_row else None,
        final_artifact_id=final_artifact_id,
        review_artifact_id=review_artifact_id,
        decision=reviewer_decision,
        score=int(quality_bundle["score"]),
        failure_reason=failure_profile["failure_reason"],
        failure_stage=failure_profile["failure_stage"],
        criteria=quality_bundle["criteria"],
        step_stats=quality_bundle["step_stats"],
        workflow_proposal=workflow_proposal,
        summary=evaluator_summary,
        recommendation=evaluator_recommendation,
    )
    serialized_workflow_proposal = serialize_workflow_proposal(
        evaluator_run={
            "id": evaluator_run_id,
            "task_run_id": task_id,
            "decision": reviewer_decision,
            "score": int(quality_bundle["score"]),
            "failure_reason": failure_profile["failure_reason"],
            "failure_stage": failure_profile["failure_stage"],
            "source": "stage5_finalize_demo",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "workflow_proposal": workflow_proposal,
        },
        proposal=workflow_proposal,
    )
    insert_audit_log(
        cur,
        "evaluator.recorded",
        actor["actor_name"],
        task_id,
        {
            "task_id": task_id,
            "evaluator_run_id": evaluator_run_id,
            "manager_run_id": manager_row["id"],
            "reviewer_run_id": reviewer_row["id"] if reviewer_row else None,
            "decision": reviewer_decision,
            "score": quality_bundle["score"],
            "failure_reason": failure_profile["failure_reason"],
            "failure_stage": failure_profile["failure_stage"],
            "source": "stage5_finalize_demo",
            "workflow_proposal": serialized_workflow_proposal,
        },
    )

    insert_audit_log(
        cur,
        "agent.finalize_demo",
        actor["actor_name"],
        task_id,
        {
            "task_id": task_id,
            "manager_run_id": manager_row["id"],
            "specialist_count": len(specialist_rows),
            "reviewer_run_id": reviewer_row["id"] if reviewer_row else None,
            "final_artifact_id": final_artifact_id,
            "reviewer_decision": reviewer_decision,
            "decision_source": decision_source,
            "requested_decision": requested_reviewer_decision,
            "next_strategy": next_strategy,
            "quality_score": quality_bundle["score"],
            "allow_retry": allow_retry,
            "final_artifact_version": next_final_version,
        },
    )
    conn.commit()
    cur.close()
    conn.close()
    logger.info(
        "agent finalize demo completed task_id=%s manager_run_id=%s specialists=%s reviewer=%s actor=%s",
        task_id,
        manager_row["id"],
        len(specialist_rows),
        reviewer_row["id"] if reviewer_row else None,
        actor["actor_name"],
    )
    return {
        "message": "agent finalize demo completed",
        "task_id": task_id,
        "manager_run_id": manager_row["id"],
        "final_artifact_id": final_artifact_id,
        "review_artifact_id": review_artifact_id,
        "specialist_draft_artifact_ids": specialist_draft_ids,
        "reviewer_decision": reviewer_decision,
        "decision_source": decision_source,
        "requested_decision": requested_reviewer_decision,
        "manager_status": manager_status,
        "next_strategy": next_strategy,
        "quality_score": quality_bundle["score"],
        "quality_criteria": quality_bundle["criteria"],
        "failure_reason": failure_profile["failure_reason"],
        "failure_stage": failure_profile["failure_stage"],
        "workflow_proposal": serialized_workflow_proposal,
        "created_message_count": len(created_message_ids),
        "created_artifact_count": len(created_artifact_ids),
        "allow_retry": allow_retry,
        "final_artifact_version": next_final_version,
        "evaluator_run_id": evaluator_run_id,
    }


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
