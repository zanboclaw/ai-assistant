import os
import json
import time
import hashlib
import sys
from datetime import datetime, timezone
import re
import shlex
import subprocess
import logging
import threading
import ipaddress
import socket
import uuid
from urllib.parse import urlparse
from pathlib import Path
from typing import Any, Optional, TypedDict
try:
    from typing import NotRequired
except ImportError:  # pragma: no cover - python<3.11 compatibility
    from typing_extensions import NotRequired

WORKSPACE_REPO = os.environ.get("WORKSPACE_ROOT", "/workspace_repo")
if WORKSPACE_REPO and WORKSPACE_REPO not in sys.path:
    sys.path.insert(0, WORKSPACE_REPO)

import psycopg2
from psycopg2.extras import Json, RealDictCursor
import requests
from bs4 import BeautifulSoup
from openai import OpenAI
from core.runtime_defaults import (
    APPROVAL_REQUIRED_TOOLS as DEFAULT_APPROVAL_REQUIRED_TOOLS,
    SUPPORTED_TOOLS as DEFAULT_SUPPORTED_TOOLS,
    get_default_model_provider_settings,
    get_default_model_route_settings,
    get_default_risk_policy_settings,
    get_default_tool_registry_settings,
)
from core.task_runtime import (
    build_task_display_user_input,
    build_task_fact_memory_content,
    build_task_summary_memory_content,
    extract_task_clarification_state,
    strip_artifact_suffix,
    strip_legacy_clarification_suffix,
)
from core.long_term_memory import ensure_long_term_memory_table, upsert_long_term_memory
from deliverable_runtime import (
    append_execution_result_closure_steps,
    build_clarification_required_message,
    build_clarification_required_recovery_action,
    build_clarification_required_validation_report,
    build_deliverable_first_plan,
    build_failed_recovery_action,
    build_runtime_failure_recovery_action,
    build_runtime_failure_validation_report,
    evaluate_task_deliverable,
)
from task_execution_runtime import (
    prepare_executor_context as prepare_executor_context_impl,
    run_legacy_plan as run_legacy_plan_impl,
    run_planned_execution as run_planned_execution_impl,
    select_task_plan_source as select_task_plan_source_impl,
)
from task_payloads import (
    augment_user_input_with_memory_context,
    build_planner_memory_context_text,
    build_task_display_input,
    build_task_display_input_excerpt,
    extract_deliverable_spec,
    extract_memory_context,
    extract_recovery_action,
    extract_task_intent,
    extract_task_model_route_overrides,
    extract_task_skill_invocation,
    extract_validation_report,
    normalize_runtime_overrides,
    parse_jsonish,
    sanitize_web_search_query,
)
try:
    import redis
except ImportError:  # pragma: no cover - optional in local non-container runs
    redis = None


DB_CONFIG = {
    "host": os.environ.get("POSTGRES_HOST", "postgres"),
    "dbname": os.environ.get("POSTGRES_DB", "assistant"),
    "user": os.environ.get("POSTGRES_USER", "assistant"),
    "password": os.environ.get("POSTGRES_PASSWORD", "change_me_for_local_dev"),
}

WORKER_APP_DIR = Path(__file__).resolve().parent
LOCAL_WORKER_ROOT = Path(WORKSPACE_REPO if Path(WORKSPACE_REPO).exists() else WORKER_APP_DIR.parent.parent).resolve()

ARTIFACT_DIR = Path(os.environ.get("ARTIFACT_DIR", str(LOCAL_WORKER_ROOT / "data" / "artifacts"))).resolve()
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

WORKSPACE_DIR = Path(os.environ.get("WORKSPACE_DIR", str(LOCAL_WORKER_ROOT / "data" / "workspace"))).resolve()
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

LOG_DIR = Path(os.environ.get("LOG_DIR", str(LOCAL_WORKER_ROOT / "logs"))).resolve()
LOG_DIR.mkdir(parents=True, exist_ok=True)

CHECKPOINT_DIR = Path(os.environ.get("CHECKPOINT_DIR", str(LOCAL_WORKER_ROOT / "data" / "checkpoints"))).resolve()
CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
WORKER_ID = os.environ.get("WORKER_ID", "worker-default")
TASK_LOCK_TTL_SECONDS = int(os.environ.get("TASK_LOCK_TTL_SECONDS", "300"))
TASK_STALE_REQUEUE_SECONDS = int(os.environ.get("TASK_STALE_REQUEUE_SECONDS", str(TASK_LOCK_TTL_SECONDS + 30)))

ALLOWED_READ_DIRS = [ARTIFACT_DIR, WORKSPACE_DIR]
ALLOWED_WRITE_DIRS = [WORKSPACE_DIR]

SAFE_COMMANDS = {
    "pwd",
    "ls",
    "cat",
    "head",
    "tail",
    "wc",
    "find",
    "git",
    "python",
    "python3",
}

DISALLOWED_TOKENS = {
    "sudo",
    "rm",
    "mv",
    "chmod",
    "chown",
    "apt",
    "apt-get",
    "dnf",
    "yum",
    "docker",
    "systemctl",
    "reboot",
    "shutdown",
    "curl",
    "wget",
}

SUPPORTED_TOOLS = set(DEFAULT_SUPPORTED_TOOLS)

TOOL_INPUT_RULES = {
    "file_read": {
        "required": {"path"},
        "optional": set(),
    },
    "file_write": {
        "required": {"path", "content"},
        "optional": set(),
    },
    "list_dir": {
        "required": {"path"},
        "optional": set(),
    },
    "shell_exec": {
        "required": {"command"},
        "optional": set(),
    },
    "generate_text": {
        "required": {"prompt"},
        "optional": {"system_prompt"},
    },
    "summarize_text": {
        "required": {"text"},
        "optional": set(),
    },
    "web_search": {
        "required": {"query"},
        "optional": set(),
    },
    "read_json": {
        "required": {"path"},
        "optional": set(),
    },
    "write_json": {
        "required": {"path", "data"},
        "optional": set(),
    },
    "http_request": {
        "required": {"url", "method"},
        "optional": {"params", "json", "timeout"},
    },
    "json_extract": {
        "required": {"data", "path"},
        "optional": set(),
    },
    "if_condition": {
        "required": set(),
        "optional": {"left", "operator", "right", "logic", "conditions"},
    },
    "set_var": {
        "required": {"name", "value"},
        "optional": set(),
    },
    "template_render": {
        "required": {"template"},
        "optional": {"strict"},
    },
}

REFERENCE_PATTERN = re.compile(r"^step:(\d+)\.(data|output)(?:\.(.+))?$")
SUPPORTED_OPERATORS = {
    "eq", "ne", "gt", "lt", "gte", "lte",
    "contains", "exists", "not_exists"
}
SUPPORTED_LOGICS = {"and", "or", "not"}
VAR_REFERENCE_PREFIX = "var:"
TEMPLATE_PATTERN = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")

TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")

APPROVAL_REQUIRED_TOOLS = set(DEFAULT_APPROVAL_REQUIRED_TOOLS)
LOW_RISK_WRITE_EXTENSIONS = {".txt", ".md", ".csv", ".log"}
SENSITIVE_WRITE_EXTENSIONS = {
    ".py",
    ".sh",
    ".bash",
    ".zsh",
    ".env",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".sql",
}
SENSITIVE_WRITE_BASENAMES = {
    "dockerfile",
    "makefile",
    ".env",
    ".gitignore",
}
DEFAULT_RISK_POLICIES = get_default_risk_policy_settings()
RISK_POLICY_CACHE_TTL_SECONDS = int(os.environ.get("RISK_POLICY_CACHE_TTL_SECONDS", "15"))
_risk_policy_cache_value: dict[str, Any] | None = None
_risk_policy_cache_expires_at = 0.0
DEFAULT_TOOL_REGISTRY = get_default_tool_registry_settings()
TOOL_REGISTRY_CACHE_TTL_SECONDS = int(os.environ.get("TOOL_REGISTRY_CACHE_TTL_SECONDS", "15"))
_tool_registry_cache_value: dict[str, dict[str, Any]] | None = None
_tool_registry_cache_expires_at = 0.0
DEFAULT_MODEL_ROUTES = get_default_model_route_settings()
DEFAULT_MODEL_PROVIDERS = get_default_model_provider_settings()
MODEL_PROVIDER_CACHE_TTL_SECONDS = int(os.environ.get("MODEL_PROVIDER_CACHE_TTL_SECONDS", "15"))
_model_provider_cache_value: dict[str, dict[str, Any]] | None = None
_model_provider_cache_expires_at = 0.0
_model_provider_client_cache: dict[tuple[str, str, str], OpenAI] = {}
MODEL_ROUTE_CACHE_TTL_SECONDS = int(os.environ.get("MODEL_ROUTE_CACHE_TTL_SECONDS", "15"))
_model_route_cache_value: dict[str, dict[str, Any]] | None = None
_model_route_cache_expires_at = 0.0
_runtime_schema_bootstrap_lock = threading.Lock()
_runtime_schema_bootstrap_active = False
_runtime_schema_bootstrapped = False
_trace_runtime_context = threading.local()


class ApprovalRequired(Exception):
    pass


class InterruptRequested(Exception):
    pass


class ClaimLostError(Exception):
    pass


class AutoRecoveryScheduled(Exception):
    pass


STEP_REQUEST_PROTOCOL_VERSION = "stage2-v1"
MULTI_AGENT_PROTOCOL_VERSION = "multi-agent-v1"
EVALUATOR_PROTOCOL_VERSION = "stage6-evaluator-v1"
AUTO_STAGE5_POSTRUN_ENABLED = os.environ.get("AUTO_STAGE5_POSTRUN_ENABLED", "1").lower() in {"1", "true", "yes"}
AUTO_STAGE5_SPECIALIST_COUNT = max(1, min(int(os.environ.get("AUTO_STAGE5_SPECIALIST_COUNT", "2")), 4))
AUTO_STAGE5_EXECUTION_MODE = "task_postrun_readonly_v1"
AUTO_STAGE5_RUNTIME_EXECUTION_MODE = "task_runtime_worker_v1"
AUTO_STAGE5_EVALUATOR_SOURCE = "task_runtime_postrun_v1"
MAINLINE_SPECIALIST_TOOL_PROFILES = {"specialist-readonly", "specialist-restricted"}
RESTRICTED_SPECIALIST_TOOL_NAMES = {"shell_exec", "file_write", "write_json"}
RESTRICTED_SPECIALIST_SUBTASK_TYPE = "restricted_shell_probe"
STEP_EXECUTION_REQUEST_FIELDS = (
    "step_order",
    "current_status",
    "tool_name",
    "raw_input",
    "run_if",
    "skip_if",
    "error_strategy",
    "max_retries",
    "retry_count",
)
ENRICHED_STEP_EXECUTION_REQUEST_EXTRA_FIELDS = (
    "should_run",
    "skip_reason",
    "resolved_input",
    "approval_required",
    "approval_reason",
    "effective_retry_count",
    "effective_max_retries",
    "result",
)


class StepExecutionRequest(TypedDict):
    step_order: int
    current_status: str
    tool_name: str
    raw_input: Any
    run_if: Any
    skip_if: Any
    error_strategy: str
    max_retries: int
    retry_count: int


class EnrichedStepExecutionRequest(StepExecutionRequest):
    should_run: bool
    skip_reason: str
    resolved_input: Any
    approval_required: bool
    approval_reason: str
    effective_retry_count: int
    effective_max_retries: int
    result: NotRequired[dict]


class StructuredStepExecutionState(TypedDict):
    execution_request: StepExecutionRequest | EnrichedStepExecutionRequest
    retry_count: int
    max_retries: int
    step_trace_id: NotRequired[int | None]
    tool_trace_id: NotRequired[int | None]


class TaskPlanSelection(TypedDict):
    existing_rows: list[dict]
    planned: list[dict] | list[str]
    plan_source: str
    execution_mode: str


def build_logger() -> logging.Logger:
    logger = logging.getLogger("ai_assistant.worker")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("[%(asctime)s] %(levelname)s %(message)s")

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    try:
        file_handler = logging.FileHandler(LOG_DIR / "worker.log", encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except PermissionError:
        logger.warning("worker file logger disabled because %s is not writable", LOG_DIR / "worker.log")

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


def get_task_control_status(task_id: int) -> str:
    task = fetch_task_by_id(task_id)
    if not task:
        return ""
    return str(task.get("status") or "")


class TaskClaimHeartbeat:
    def __init__(self, task_id: int, claim_token: str):
        self.task_id = task_id
        self.claim_token = claim_token
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lost = False

    def start(self):
        client = get_redis_client()
        if client is None:
            return
        interval = max(1, TASK_LOCK_TTL_SECONDS // 3)

        def runner():
            while not self._stop.wait(interval):
                if not renew_task_claim(self.task_id, self.claim_token):
                    self._lost = True
                    logger.error("task claim lost task_id=%s worker_id=%s", self.task_id, WORKER_ID)
                    record_worker_audit_event(
                        "task.claim_lost",
                        self.task_id,
                        {
                            "worker_id": WORKER_ID,
                        },
                    )
                    return

        self._thread = threading.Thread(target=runner, name=f"task-claim-{self.task_id}", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)

    def assert_owned(self):
        if self._lost:
            raise ClaimLostError(f"task claim lost: {self.task_id}")


# =========================
# DB
# =========================
def get_conn():
    return psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)


def safe_json_dumps(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return json.dumps({"repr": repr(obj)}, ensure_ascii=False)


def parse_json_text(text: Optional[str], default=None):
    if text is None:
        return default
    text = text.strip()
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        return default


def fetch_latest_evaluator_feedback(cur, task_id: int) -> dict[str, Any]:
    cur.execute(
        """
        SELECT decision, summary, recommendation, failure_reason, failure_stage, proposal_json, source
        FROM evaluator_runs
        WHERE task_run_id = %s
        ORDER BY id DESC
        LIMIT 1;
        """,
        (task_id,),
    )
    row = cur.fetchone() or {}
    return {
        "decision": str(row.get("decision") or "").strip(),
        "summary": str(row.get("summary") or "").strip(),
        "recommendation": str(row.get("recommendation") or "").strip(),
        "failure_reason": str(row.get("failure_reason") or "").strip(),
        "failure_stage": str(row.get("failure_stage") or "").strip(),
        "proposal": parse_jsonish(row.get("proposal_json"), {}) or {},
        "source": str(row.get("source") or "").strip(),
    }


def build_runtime_feedback_context_text(latest_evaluator: dict[str, Any] | None) -> str:
    feedback = dict(latest_evaluator or {})
    if not feedback:
        return ""
    decision = str(feedback.get("decision") or "").strip()
    recommendation = str(feedback.get("recommendation") or "").strip()
    proposal = feedback.get("proposal") if isinstance(feedback.get("proposal"), dict) else {}
    proposal_action = str(proposal.get("action_key") or "").strip()
    if not any((decision, recommendation, proposal_action)):
        return ""

    lines = ["最近 evaluator 反馈："]
    if decision:
        lines.append(f"- decision: {decision}")
    if recommendation:
        lines.append(f"- recommendation: {recommendation[:280]}")
    if proposal_action:
        lines.append(f"- workflow proposal: {proposal_action}")
    return "\n".join(lines)


def augment_user_input_with_runtime_feedback(user_input: str, latest_evaluator: dict[str, Any] | None) -> str:
    feedback_text = build_runtime_feedback_context_text(latest_evaluator)
    normalized_user_input = str(user_input or "").strip()
    if not feedback_text:
        return normalized_user_input
    if not normalized_user_input:
        return feedback_text
    return f"{normalized_user_input}\n\n{feedback_text}"


def resolve_specialist_fanout_strategy(
    task_row: dict[str, Any],
    latest_evaluator: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task_intent = extract_task_intent(task_row)
    deliverable_spec = extract_deliverable_spec(task_row)
    deliverable_type = str(deliverable_spec.get("deliverable_type") or "").strip()
    proposal = latest_evaluator.get("proposal") if isinstance(latest_evaluator, dict) else {}
    proposal_action = str((proposal or {}).get("action_key") or "").strip()
    evaluator_decision = str((latest_evaluator or {}).get("decision") or "").strip()
    evaluator_failure_stage = str((latest_evaluator or {}).get("failure_stage") or "").strip()
    needs_clarification = bool(task_intent.get("needs_clarification"))
    breadth_first = deliverable_type in {"research_summary", "research_then_generate_bundle", "execution_result"}
    needs_expansion = evaluator_decision in {"rework_required", "rejected"} or proposal_action == "expand_specialist_scope"

    if needs_clarification:
        return {
            "enabled": False,
            "specialist_count": 0,
            "use_restricted_probe": False,
            "reason": "clarification_pending",
        }

    specialist_count = 1
    if breadth_first:
        specialist_count = max(2, AUTO_STAGE5_SPECIALIST_COUNT)
    if needs_expansion:
        specialist_count = min(4, max(specialist_count + 1, 2))

    enabled = breadth_first or needs_expansion
    return {
        "enabled": enabled,
        "specialist_count": specialist_count if enabled else 0,
        "use_restricted_probe": bool(enabled and needs_expansion and evaluator_failure_stage in {"execution", "review"}),
        "reason": "evaluator_feedback" if needs_expansion else ("deliverable_breadth" if breadth_first else "not_needed"),
    }


def ensure_runtime_schema_bootstrapped():
    global _runtime_schema_bootstrap_active, _runtime_schema_bootstrapped

    if _runtime_schema_bootstrapped:
        return

    with _runtime_schema_bootstrap_lock:
        if _runtime_schema_bootstrapped:
            return

        conn = get_conn()
        cur = conn.cursor()
        _runtime_schema_bootstrap_active = True
        try:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext('runtime_core_schema_bootstrap'));")
            ensure_task_steps_columns(cur)
            ensure_approvals_table(cur)
            ensure_audit_logs_table(cur)
            ensure_trace_tables(cur)
            ensure_skill_registry_tables(cur)
            seed_default_tool_registry(cur)
            seed_default_model_providers(cur)
            seed_default_model_routes(cur)
            ensure_agent_tables(cur)
            ensure_evaluator_tables(cur)
            conn.commit()
            _runtime_schema_bootstrapped = True
        finally:
            _runtime_schema_bootstrap_active = False
            cur.close()
            conn.close()


def ensure_task_steps_columns(cur):
    if not _runtime_schema_bootstrap_active:
        ensure_runtime_schema_bootstrapped()
        return
    cur.execute("ALTER TABLE task_runs ADD COLUMN IF NOT EXISTS runtime_overrides JSONB;")
    cur.execute("ALTER TABLE task_runs ADD COLUMN IF NOT EXISTS task_intent_json JSONB;")
    cur.execute("ALTER TABLE task_runs ADD COLUMN IF NOT EXISTS deliverable_spec_json JSONB;")
    cur.execute("ALTER TABLE task_runs ADD COLUMN IF NOT EXISTS validation_report_json JSONB;")
    cur.execute("ALTER TABLE task_runs ADD COLUMN IF NOT EXISTS recovery_action_json JSONB;")
    cur.execute("ALTER TABLE task_steps ADD COLUMN IF NOT EXISTS tool_name TEXT;")
    cur.execute("ALTER TABLE task_steps ADD COLUMN IF NOT EXISTS output_data TEXT;")
    cur.execute("ALTER TABLE task_steps ADD COLUMN IF NOT EXISTS error_strategy TEXT DEFAULT 'fail';")
    cur.execute("ALTER TABLE task_steps ADD COLUMN IF NOT EXISTS run_if TEXT;")
    cur.execute("ALTER TABLE task_steps ADD COLUMN IF NOT EXISTS skip_if TEXT;")
    cur.execute("ALTER TABLE task_steps ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0;")
    cur.execute("ALTER TABLE task_steps ADD COLUMN IF NOT EXISTS max_retries INTEGER NOT NULL DEFAULT 0;")


def ensure_approvals_table(cur):
    if not _runtime_schema_bootstrap_active:
        ensure_runtime_schema_bootstrapped()
        return
    cur.execute(
        """
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
        """
    )


def ensure_audit_logs_table(cur):
    if not _runtime_schema_bootstrap_active:
        ensure_runtime_schema_bootstrapped()
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


def ensure_trace_tables(cur):
    if not _runtime_schema_bootstrap_active:
        ensure_runtime_schema_bootstrapped()
        return
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS task_traces (
            id SERIAL PRIMARY KEY,
            trace_id TEXT NOT NULL UNIQUE,
            task_run_id INTEGER NOT NULL UNIQUE REFERENCES task_runs(id) ON DELETE CASCADE,
            status TEXT NOT NULL DEFAULT 'running',
            plan_source TEXT,
            error_summary TEXT,
            input_summary TEXT,
            metadata_json JSONB,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ended_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS step_traces (
            id SERIAL PRIMARY KEY,
            trace_id TEXT NOT NULL UNIQUE,
            task_trace_id INTEGER REFERENCES task_traces(id) ON DELETE SET NULL,
            task_run_id INTEGER NOT NULL REFERENCES task_runs(id) ON DELETE CASCADE,
            task_step_id INTEGER REFERENCES task_steps(id) ON DELETE SET NULL,
            step_order INTEGER,
            step_name TEXT,
            tool_name TEXT,
            status TEXT NOT NULL DEFAULT 'running',
            input_snapshot JSONB,
            output_snapshot JSONB,
            error_summary TEXT,
            retry_count INTEGER NOT NULL DEFAULT 0,
            max_retries INTEGER NOT NULL DEFAULT 0,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ended_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS model_traces (
            id SERIAL PRIMARY KEY,
            trace_id TEXT NOT NULL UNIQUE,
            task_run_id INTEGER NOT NULL REFERENCES task_runs(id) ON DELETE CASCADE,
            task_step_id INTEGER REFERENCES task_steps(id) ON DELETE SET NULL,
            step_trace_id INTEGER REFERENCES step_traces(id) ON DELETE SET NULL,
            route_name TEXT,
            provider TEXT,
            model_name TEXT,
            prompt_version TEXT,
            prompt_hash TEXT,
            status TEXT NOT NULL DEFAULT 'running',
            request_excerpt TEXT,
            response_excerpt TEXT,
            error_summary TEXT,
            metadata_json JSONB,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ended_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS tool_traces (
            id SERIAL PRIMARY KEY,
            trace_id TEXT NOT NULL UNIQUE,
            task_run_id INTEGER NOT NULL REFERENCES task_runs(id) ON DELETE CASCADE,
            task_step_id INTEGER REFERENCES task_steps(id) ON DELETE SET NULL,
            step_trace_id INTEGER REFERENCES step_traces(id) ON DELETE SET NULL,
            tool_name TEXT,
            tool_args_hash TEXT,
            status TEXT NOT NULL DEFAULT 'running',
            input_snapshot JSONB,
            output_snapshot JSONB,
            error_summary TEXT,
            metadata_json JSONB,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ended_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS skill_traces (
            id SERIAL PRIMARY KEY,
            trace_id TEXT NOT NULL UNIQUE,
            task_run_id INTEGER NOT NULL REFERENCES task_runs(id) ON DELETE CASCADE,
            task_step_id INTEGER REFERENCES task_steps(id) ON DELETE SET NULL,
            skill_id TEXT,
            skill_version TEXT,
            status TEXT NOT NULL DEFAULT 'planned',
            input_snapshot JSONB,
            output_snapshot JSONB,
            error_summary TEXT,
            metadata_json JSONB,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ended_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS retrieval_traces (
            id SERIAL PRIMARY KEY,
            trace_id TEXT NOT NULL UNIQUE,
            task_run_id INTEGER NOT NULL REFERENCES task_runs(id) ON DELETE CASCADE,
            task_step_id INTEGER REFERENCES task_steps(id) ON DELETE SET NULL,
            retrieval_scope TEXT,
            status TEXT NOT NULL DEFAULT 'planned',
            query_text TEXT,
            result_count INTEGER NOT NULL DEFAULT 0,
            error_summary TEXT,
            metadata_json JSONB,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ended_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )


def ensure_skill_registry_tables(cur):
    if not _runtime_schema_bootstrap_active:
        ensure_runtime_schema_bootstrapped()
        return
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS skills (
            skill_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            latest_version TEXT NOT NULL DEFAULT '',
            entrypoint_kind TEXT NOT NULL DEFAULT 'structured_steps',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS skill_versions (
            id SERIAL PRIMARY KEY,
            skill_id TEXT NOT NULL REFERENCES skills(skill_id) ON DELETE CASCADE,
            version TEXT NOT NULL,
            package_format TEXT NOT NULL DEFAULT 'json',
            package_source TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            package_body JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(skill_id, version)
        );
        """
    )


def ensure_agent_tables(cur):
    if not _runtime_schema_bootstrap_active:
        ensure_runtime_schema_bootstrapped()
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
    if not _runtime_schema_bootstrap_active:
        ensure_runtime_schema_bootstrapped()
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


def ensure_sessions_base_table(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )


def ensure_sessions_tables(cur):
    ensure_sessions_base_table(cur)
    cur.execute(
        """
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
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS session_states (
            session_id INTEGER PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
            summary_text TEXT NOT NULL DEFAULT '',
            preferences JSONB NOT NULL DEFAULT '[]'::jsonb,
            open_loops JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_hash(value: Any) -> str:
    payload = safe_json_dumps(value) if value is not None else "null"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _trim_text(value: Any, limit: int = 1200) -> str:
    text = str(value or "")
    return text[:limit]


def set_current_trace_context(
    *,
    task_id: int | None = None,
    step_id: int | None = None,
    step_trace_id: int | None = None,
):
    _trace_runtime_context.task_id = task_id
    _trace_runtime_context.step_id = step_id
    _trace_runtime_context.step_trace_id = step_trace_id


def clear_current_trace_context():
    set_current_trace_context(task_id=None, step_id=None, step_trace_id=None)


def get_current_trace_context() -> dict[str, Any]:
    return {
        "task_id": getattr(_trace_runtime_context, "task_id", None),
        "step_id": getattr(_trace_runtime_context, "step_id", None),
        "step_trace_id": getattr(_trace_runtime_context, "step_trace_id", None),
    }


def ensure_task_trace(cur, task_id: int, user_input: str) -> int:
    ensure_trace_tables(cur)
    cur.execute("SELECT id FROM task_traces WHERE task_run_id = %s;", (task_id,))
    row = cur.fetchone()
    if row:
        cur.execute(
            """
            UPDATE task_traces
            SET updated_at = CURRENT_TIMESTAMP,
                input_summary = COALESCE(input_summary, %s)
            WHERE task_run_id = %s;
            """,
            (_trim_text(user_input, 500), task_id),
        )
        return int(row["id"])
    trace_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO task_traces (
            trace_id, task_run_id, status, input_summary, metadata_json, started_at, updated_at
        )
        VALUES (%s, %s, 'running', %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        RETURNING id;
        """,
        (
            trace_id,
            task_id,
            _trim_text(user_input, 500),
            safe_json_dumps({"trace_version": "p0-v1"}),
        ),
    )
    row = cur.fetchone()
    return int(row["id"])


def update_task_trace_status(
    cur,
    task_id: int,
    *,
    status: str,
    error_summary: str = "",
    plan_source: str | None = None,
):
    ensure_trace_tables(cur)
    if plan_source is None:
        cur.execute(
            """
            UPDATE task_traces
            SET status = %s,
                error_summary = %s,
                ended_at = CASE WHEN %s IN ('completed', 'failed', 'paused', 'waiting_approval') THEN CURRENT_TIMESTAMP ELSE ended_at END,
                updated_at = CURRENT_TIMESTAMP
            WHERE task_run_id = %s;
            """,
            (status, error_summary or "", status, task_id),
        )
    else:
        cur.execute(
            """
            UPDATE task_traces
            SET status = %s,
                error_summary = %s,
                plan_source = %s,
                ended_at = CASE WHEN %s IN ('completed', 'failed', 'paused', 'waiting_approval') THEN CURRENT_TIMESTAMP ELSE ended_at END,
                updated_at = CURRENT_TIMESTAMP
            WHERE task_run_id = %s;
            """,
            (status, error_summary or "", plan_source, status, task_id),
        )


def create_step_and_tool_trace(
    cur,
    *,
    task_id: int,
    task_step_id: int | None,
    step_order: int,
    step_name: str,
    tool_name: str,
    input_payload: Any,
    retry_count: int,
    max_retries: int,
) -> tuple[int, int]:
    task_trace_id = ensure_task_trace(cur, task_id, "")
    step_trace_id = str(uuid.uuid4())
    tool_trace_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO step_traces (
            trace_id, task_trace_id, task_run_id, task_step_id, step_order, step_name, tool_name,
            status, input_snapshot, retry_count, max_retries, started_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'running', %s, %s, %s, CURRENT_TIMESTAMP)
        RETURNING id;
        """,
        (
            step_trace_id,
            task_trace_id,
            task_id,
            task_step_id,
            step_order,
            step_name,
            tool_name,
            safe_json_dumps(input_payload),
            retry_count,
            max_retries,
        ),
    )
    step_row = cur.fetchone()
    cur.execute(
        """
        INSERT INTO tool_traces (
            trace_id, task_run_id, task_step_id, step_trace_id, tool_name, tool_args_hash,
            status, input_snapshot, started_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, 'running', %s, CURRENT_TIMESTAMP)
        RETURNING id;
        """,
        (
            tool_trace_id,
            task_id,
            task_step_id,
            int(step_row["id"]),
            tool_name,
            _json_hash(input_payload),
            safe_json_dumps(input_payload),
        ),
    )
    tool_row = cur.fetchone()
    cur.connection.commit()
    return int(step_row["id"]), int(tool_row["id"])


def complete_step_and_tool_trace(
    cur,
    *,
    step_trace_id: int | None,
    tool_trace_id: int | None,
    status: str,
    output_payload: Any = None,
    output_data: Any = None,
    error_summary: str = "",
    retry_count: int = 0,
):
    output_snapshot = {
        "output_payload": _trim_text(output_payload, 2000),
        "output_data": output_data,
    }
    if step_trace_id:
        cur.execute(
            """
            UPDATE step_traces
            SET status = %s,
                output_snapshot = %s,
                error_summary = %s,
                retry_count = %s,
                ended_at = CURRENT_TIMESTAMP
            WHERE id = %s;
            """,
            (status, safe_json_dumps(output_snapshot), error_summary or "", retry_count, step_trace_id),
        )
    if tool_trace_id:
        cur.execute(
            """
            UPDATE tool_traces
            SET status = %s,
                output_snapshot = %s,
                error_summary = %s,
                ended_at = CURRENT_TIMESTAMP
            WHERE id = %s;
            """,
            (status, safe_json_dumps(output_snapshot), error_summary or "", tool_trace_id),
        )
    cur.connection.commit()


def record_model_trace(
    *,
    route_name: str,
    provider: str,
    model_name: str,
    prompt_version: str,
    prompt_text: str,
    response_text: str = "",
    status: str = "completed",
    error_summary: str = "",
    metadata: dict[str, Any] | None = None,
):
    context = get_current_trace_context()
    task_id = context.get("task_id")
    if not task_id:
        return
    conn = get_conn()
    cur = conn.cursor()
    try:
        ensure_trace_tables(cur)
        cur.execute(
            """
            INSERT INTO model_traces (
                trace_id, task_run_id, task_step_id, step_trace_id, route_name, provider, model_name,
                prompt_version, prompt_hash, status, request_excerpt, response_excerpt, error_summary,
                metadata_json, started_at, ended_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
            """,
            (
                str(uuid.uuid4()),
                task_id,
                context.get("step_id"),
                context.get("step_trace_id"),
                route_name,
                provider,
                model_name,
                prompt_version,
                hashlib.sha256((prompt_text or "").encode("utf-8")).hexdigest(),
                status,
                _trim_text(prompt_text, 1200),
                _trim_text(response_text, 1500),
                error_summary or "",
                safe_json_dumps(metadata or {}),
            ),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def create_skill_trace(
    cur,
    *,
    task_id: int,
    skill_id: str,
    skill_version: str,
    input_snapshot: Any,
    metadata: dict[str, Any] | None = None,
) -> int:
    ensure_trace_tables(cur)
    cur.execute(
        """
        INSERT INTO skill_traces (
            trace_id, task_run_id, skill_id, skill_version, status, input_snapshot, metadata_json, started_at
        )
        VALUES (%s, %s, %s, %s, 'running', %s, %s, CURRENT_TIMESTAMP)
        RETURNING id;
        """,
        (
            str(uuid.uuid4()),
            task_id,
            skill_id,
            skill_version,
            safe_json_dumps(input_snapshot),
            safe_json_dumps(metadata or {}),
        ),
    )
    row = cur.fetchone()
    cur.connection.commit()
    return int(row["id"])


def complete_skill_trace(
    cur,
    *,
    skill_trace_id: int | None,
    status: str,
    output_snapshot: Any = None,
    error_summary: str = "",
):
    if not skill_trace_id:
        return
    cur.execute(
        """
        UPDATE skill_traces
        SET status = %s,
            output_snapshot = %s,
            error_summary = %s,
            ended_at = CURRENT_TIMESTAMP
        WHERE id = %s;
        """,
        (status, safe_json_dumps(output_snapshot), error_summary or "", skill_trace_id),
    )
    cur.connection.commit()

def insert_audit_log(cur, event_type: str, actor: str, task_id: int | None = None, details: Any | None = None):
    cur.execute(
        """
        INSERT INTO audit_logs (task_id, event_type, actor, details)
        VALUES (%s, %s, %s, %s);
        """,
        (task_id, event_type, actor, safe_json_dumps(details) if details is not None else None),
    )


def create_agent_artifact(cur, task_run_id: int, agent_run_id: int | None, artifact_type: str, summary: str, content: Any, version: int = 1) -> int:
    cur.execute(
        """
        INSERT INTO agent_artifacts (task_run_id, agent_run_id, artifact_type, summary, content_json, version)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id;
        """,
        (task_run_id, agent_run_id, artifact_type, summary, safe_json_dumps(content), int(version)),
    )
    return int(cur.fetchone()["id"])


def create_agent_message(cur, task_run_id: int, agent_run_id: int | None, sender_role: str, recipient_role: str, message_type: str, payload: Any) -> int:
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
    source: str = AUTO_STAGE5_EVALUATOR_SOURCE,
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


def build_review_criteria(
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
            "recommendation": "当前质量门通过，可以继续推进主链，或把 workflow proposal 作为后续优化输入。",
            "summary": "evaluator 判定当前主链结果健康，可继续推进。",
        }
    if failed_steps > 0 or task_status == "failed":
        return {
            "failure_reason": "task_failed_step",
            "failure_stage": "execution",
            "recommendation": "优先检查 failed steps 的错误摘要，修复输入或步骤依赖后再执行。",
            "summary": "evaluator 发现主链执行阶段存在 failed step。",
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
            "recommendation": "按 reviewer 建议返工 specialists 或重新汇总后再次评估。",
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
            "dispatch": "task_runtime_postrun",
            "expected_next_strategy": "generate_drafts",
        }
    elif failure_reason == "incomplete_execution":
        priority = "high"
        target_surface = "stage5_specialists"
        action_key = "rerun_incomplete_specialists"
        title = "重跑未完成 specialist"
        action_payload = {
            "recommended_action": "rerun_incomplete_specialists",
            "dispatch": "task_runtime_postrun",
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
        title = "重跑 specialists 后再次汇总"
        action_payload = {
            "recommended_action": "rerun_specialists_then_finalize",
            "dispatch": "task_runtime_postrun",
            "followed_by": "mainline_finalize",
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
    task_status: str,
    step_rows: list[dict[str, Any]],
    specialist_draft_count: int,
) -> tuple[str, str]:
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
    partitions: list[list[dict[str, Any]]] = [[] for _ in range(max(1, specialist_count))]
    if step_rows:
        for index, step_row in enumerate(step_rows):
            partitions[index % len(partitions)].append(
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
        fallback_step = {
            "step_order": 0,
            "step_name": "task-result-fallback",
            "status": task_row.get("status") or "unknown",
            "tool_name": "",
            "input_excerpt": build_task_display_input_excerpt(task_row),
            "output_excerpt": build_task_result_excerpt(task_row),
            "error_excerpt": str(task_row.get("error_message") or "")[:160],
        }
        partitions = [[dict(fallback_step)] for _ in partitions]

    step_status_counts: dict[str, int] = {}
    for row in step_rows:
        status_key = str(row.get("status") or "unknown")
        step_status_counts[status_key] = int(step_status_counts.get(status_key, 0)) + 1
    if not step_status_counts:
        fallback_status = str(task_row.get("status") or "unknown")
        step_status_counts[fallback_status] = 1
    return step_outline, partitions, step_status_counts


def build_specialist_execution_request(
    *,
    slot: int,
    manager_objective: str,
    assigned_steps: list[dict[str, Any]] | None = None,
    brief_artifact_id: int | None = None,
    plan_artifact_id: int | None = None,
    note: str = "",
    execution_mode: str = AUTO_STAGE5_EXECUTION_MODE,
    tool_profile: str = "specialist-readonly",
    subtask_type: str = "readonly_step_digest",
    source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assigned_steps = assigned_steps or []
    assigned_step_orders = [int(step.get("step_order") or 0) for step in assigned_steps if int(step.get("step_order") or 0) > 0]
    source = source or {}
    deliverable = f"specialist-{slot} readonly digest"
    scope = "plan_boundary_digest" if slot == 1 else "risk_result_digest"
    constraints = ["readonly-only", "do-not-write-files", "do-not-emit-final-answer"]
    success_criteria = [
        "summarize assigned steps",
        "highlight risks and gaps",
        "produce manager-consumable digest",
    ]
    if subtask_type == "readonly_task_snapshot":
        deliverable = "readonly task snapshot"
        scope = "task_snapshot"
        success_criteria = [
            "return bounded task-level status snapshot",
            "include latest execution and review signals",
            "highlight next operator or manager action",
        ]
    elif subtask_type == RESTRICTED_SPECIALIST_SUBTASK_TYPE:
        deliverable = "restricted shell probe"
        scope = "restricted_tool_probe"
        constraints = ["shell-whitelist-only", "no-destructive-commands", "do-not-emit-final-answer"]
        success_criteria = [
            "run a bounded restricted-tool probe",
            "summarize restricted-tool observations for manager",
            "highlight approval or execution-time risks",
        ]
    return {
        "execution_mode": execution_mode,
        "tool_profile": tool_profile,
        "subtask_type": subtask_type,
        "slot": slot,
        "objective": manager_objective,
        "scope": scope,
        "deliverable": deliverable,
        "assigned_step_orders": assigned_step_orders,
        "source": source,
        "focus_questions": [
            "这个子问题最关键的信息是什么",
            "有哪些明显缺口、风险或需要继续跟进的点",
        ],
        "evidence_refs": [
            {"artifact_id": artifact_id, "label": label}
            for artifact_id, label in [
                (brief_artifact_id, "specialist_brief"),
                (plan_artifact_id, "manager_plan"),
            ]
            if artifact_id
        ],
        "constraints": constraints,
        "success_criteria": success_criteria,
        "note": note,
    }


def is_mainline_specialist_tool_profile(value: Any) -> bool:
    return str(value or "").strip() in MAINLINE_SPECIALIST_TOOL_PROFILES


def is_mainline_specialist_execution_mode(value: Any) -> bool:
    return str(value or "").strip() in {AUTO_STAGE5_EXECUTION_MODE, AUTO_STAGE5_RUNTIME_EXECUTION_MODE}


def choose_runtime_specialist_subtask_type(slot: int) -> str:
    return "readonly_task_snapshot" if int(slot) == 1 else "readonly_step_digest"


def build_restricted_specialist_source(
    *,
    task_row: dict[str, Any],
    assigned_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    restricted_tools = sorted(
        {
            str(step.get("tool_name") or "").strip()
            for step in assigned_steps
            if str(step.get("tool_name") or "").strip()
        }
    )
    command = "ls /workspace" if any(tool_name in {"file_write", "write_json"} for tool_name in restricted_tools) else "pwd"
    return {
        "command": command,
        "restricted_tools": restricted_tools,
        "task_status": str(task_row.get("status") or "unknown"),
    }


def build_mainline_specialist_specs(
    *,
    step_rows: list[dict[str, Any]],
    task_row: dict[str, Any],
    fanout_strategy: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    strategy = dict(fanout_strategy or {})
    base_specialist_count = int(strategy.get("specialist_count") or AUTO_STAGE5_SPECIALIST_COUNT)
    base_specialist_count = max(1, min(base_specialist_count, 4))
    step_outline, specialist_partitions, step_status_counts = build_specialist_step_partitions(
        step_rows=step_rows,
        specialist_count=base_specialist_count,
        task_row=task_row,
    )
    specs: list[dict[str, Any]] = []
    for index in range(base_specialist_count):
        slot = index + 1
        use_restricted_probe = bool(strategy.get("use_restricted_probe")) and slot == base_specialist_count
        subtask_type = "readonly_task_snapshot" if slot == 1 else "readonly_step_digest"
        tool_profile = "specialist-readonly"
        source = {}
        if use_restricted_probe:
            subtask_type = RESTRICTED_SPECIALIST_SUBTASK_TYPE
            tool_profile = "specialist-restricted"
            source = build_restricted_specialist_source(
                task_row=task_row,
                assigned_steps=specialist_partitions[index],
            )
        specs.append(
            {
                "slot": slot,
                "subtask_type": subtask_type,
                "tool_profile": tool_profile,
                "scope": "task_snapshot" if slot == 1 else "risk_result_digest",
                "assigned_steps": specialist_partitions[index],
                "source": source,
            }
        )

    restricted_assigned_steps = [
        {
            "step_order": int(step_row["step_order"]),
            "step_name": step_row["step_name"],
            "status": step_row["status"],
            "tool_name": step_row.get("tool_name") or "",
            "input_excerpt": str(step_row.get("input_payload") or "")[:180],
            "output_excerpt": str(step_row.get("output_payload") or "")[:220],
            "error_excerpt": str(step_row.get("error_message") or "")[:160],
        }
        for step_row in step_rows
        if str(step_row.get("tool_name") or "").strip() in RESTRICTED_SPECIALIST_TOOL_NAMES
    ]
    if restricted_assigned_steps and len(specs) < 4 and not bool(strategy.get("use_restricted_probe")):
        specs.append(
            {
                "slot": len(specs) + 1,
                "subtask_type": RESTRICTED_SPECIALIST_SUBTASK_TYPE,
                "tool_profile": "specialist-restricted",
                "scope": "restricted_tool_probe",
                "assigned_steps": restricted_assigned_steps,
                "source": build_restricted_specialist_source(
                    task_row=task_row,
                    assigned_steps=restricted_assigned_steps,
                ),
            }
        )
    return step_outline, specs, step_status_counts


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
    execution_request: dict[str, Any],
) -> dict[str, Any]:
    execution_mode = str(execution_request.get("execution_mode") or AUTO_STAGE5_EXECUTION_MODE).strip() or AUTO_STAGE5_EXECUTION_MODE
    subtask_type = str(execution_request.get("subtask_type") or "readonly_step_digest").strip() or "readonly_step_digest"
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
        "execution_mode": execution_mode,
        "subtask_type": subtask_type,
        "status": "completed",
        "request_snapshot": execution_request,
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
        "summary": f"子问题 {slot} 基于主链执行结果生成结构化 specialist draft",
        "output": {
            "slot": slot,
            "deliverable": f"Draft for subtask {slot}",
            "objective": manager_objective,
            "task_status": task_row.get("status") or "unknown",
            "task_result_excerpt": str(task_row.get("result") or "")[:280],
            "task_error_excerpt": str(task_row.get("error_message") or "")[:200],
            "step_outline": step_outline,
            "assigned_steps": assigned_steps,
            "subtask": {
                "type": subtask_type,
                "execution_mode": execution_mode,
                "assigned_step_orders": assigned_step_orders,
            },
            "execution_request": execution_request,
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
        "known_gaps": [] if task_row.get("status") == "completed" else [f"task 当前状态为 {task_row.get('status') or 'unknown'}"],
        "quality_signals": {
            "task_status": task_row.get("status") or "unknown",
            "global_step_status_counts": step_status_counts,
            "specialist_execution_mode": execution_mode,
            "assigned_step_count": len(assigned_steps),
        },
        "note": note,
    }


def maybe_refresh_task_runtime_manager_rollup(cur, task_id: int):
    ensure_agent_tables(cur)
    ensure_task_steps_columns(cur)
    cur.execute(
        """
        SELECT id, status, user_input, result, error_message
        FROM task_runs
        WHERE id = %s;
        """,
        (task_id,),
    )
    task_row = cur.fetchone()
    if not task_row:
        return

    cur.execute(
        """
        SELECT id, status, assigned_tool_profile
        FROM agent_runs
        WHERE task_run_id = %s AND role = 'manager'
        ORDER BY id ASC
        LIMIT 1;
        """,
        (task_id,),
    )
    manager_row = cur.fetchone()
    if not manager_row or str(manager_row.get("assigned_tool_profile") or "") != "manager-mainline":
        return

    cur.execute(
        """
        SELECT id, status, output_artifact_id, execution_mode, execution_request_json, completed_at
        FROM agent_runs
        WHERE task_run_id = %s AND role = 'specialist'
        ORDER BY id ASC;
        """,
        (task_id,),
    )
    specialist_rows = list(cur.fetchall())
    completed_specialists = [row for row in specialist_rows if row.get("output_artifact_id")]
    if not completed_specialists:
        return

    output_artifact_ids = [int(row["output_artifact_id"]) for row in completed_specialists if row.get("output_artifact_id")]
    cur.execute(
        """
        SELECT id, agent_run_id, artifact_type, summary, content_json, version
        FROM agent_artifacts
        WHERE id = ANY(%s)
        ORDER BY id ASC;
        """,
        (output_artifact_ids,),
    )
    artifact_rows = {int(row["agent_run_id"]): row for row in cur.fetchall()}

    cur.execute(
        """
        SELECT step_order, status
        FROM task_steps
        WHERE task_id = %s
        ORDER BY step_order ASC;
        """,
        (task_id,),
    )
    step_rows = list(cur.fetchall())
    step_status_counts: dict[str, int] = {}
    for row in step_rows:
        status_key = str(row.get("status") or "unknown")
        step_status_counts[status_key] = int(step_status_counts.get(status_key, 0)) + 1

    rollup_items: list[dict[str, Any]] = []
    for specialist_row in completed_specialists:
        execution_request = parse_jsonish(specialist_row.get("execution_request_json"), {})
        artifact_row = artifact_rows.get(int(specialist_row["id"]))
        artifact_content = parse_jsonish((artifact_row or {}).get("content_json"), {})
        rollup_items.append(
            {
                "agent_run_id": int(specialist_row["id"]),
                "status": str(specialist_row.get("status") or "unknown"),
                "execution_mode": str(specialist_row.get("execution_mode") or ""),
                "subtask_type": str(execution_request.get("subtask_type") or "readonly_step_digest"),
                "output_artifact_id": specialist_row.get("output_artifact_id"),
                "draft_version": int((artifact_row or {}).get("version") or 1),
                "draft_summary": (artifact_row or {}).get("summary") or "",
                "completed_at": specialist_row.get("completed_at").isoformat() if specialist_row.get("completed_at") else None,
                "result_summary": str((artifact_content.get("summary") if isinstance(artifact_content, dict) else "") or ""),
            }
        )

    next_action = "observe_task"
    task_status = str(task_row.get("status") or "unknown")
    if task_status == "waiting_approval":
        next_action = "await_task_approval"
    elif task_status == "running":
        next_action = "continue_task_execution"
    elif task_status in {"completed", "failed"}:
        next_action = "ready_for_postrun_finalize"

    cur.execute(
        """
        SELECT COALESCE(MAX(version), 0) AS max_version
        FROM agent_artifacts
        WHERE task_run_id = %s AND agent_run_id = %s AND artifact_type = 'draft';
        """,
        (task_id, int(manager_row["id"])),
    )
    draft_version = int((cur.fetchone() or {}).get("max_version") or 0) + 1
    draft_artifact_id = create_agent_artifact(
        cur,
        task_id,
        int(manager_row["id"]),
        "draft",
        "task runtime manager rollup",
        {
            "protocol_version": MULTI_AGENT_PROTOCOL_VERSION,
            "task_id": task_id,
            "summary": "manager 在终态前汇总 specialist drafts，形成 execution-time fan-in 视图",
            "rollup_stage": "execution_time_fanin",
            "source": AUTO_STAGE5_RUNTIME_EXECUTION_MODE,
            "task_status": task_status,
            "task_result_excerpt": str(task_row.get("result") or "")[:240],
            "task_error_excerpt": str(task_row.get("error_message") or "")[:180],
            "completed_specialist_count": len(completed_specialists),
            "total_specialist_count": len(specialist_rows),
            "specialist_outputs": rollup_items,
            "step_status_counts": step_status_counts,
            "next_action": next_action,
        },
        version=draft_version,
    )
    cur.execute(
        """
        UPDATE agent_runs
        SET output_artifact_id = %s,
            status = CASE WHEN status = 'planned' THEN 'running' ELSE status END,
            started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s;
        """,
        (draft_artifact_id, int(manager_row["id"])),
    )
    create_agent_message(
        cur,
        task_id,
        int(manager_row["id"]),
        "manager",
        "reviewer",
        "progress",
        {
            "protocol_version": MULTI_AGENT_PROTOCOL_VERSION,
            "phase": "execution_time_fanin",
            "task_status": task_status,
            "completed_specialist_count": len(completed_specialists),
            "total_specialist_count": len(specialist_rows),
            "draft_artifact_id": draft_artifact_id,
            "next_action": next_action,
        },
    )
    insert_audit_log(
        cur,
        "agent.mainline_runtime_fanin",
        "worker",
        task_id,
        {
            "task_id": task_id,
            "manager_run_id": int(manager_row["id"]),
            "draft_artifact_id": draft_artifact_id,
            "completed_specialist_count": len(completed_specialists),
            "total_specialist_count": len(specialist_rows),
            "next_action": next_action,
        },
    )


def maybe_dispatch_task_runtime_specialists(task_id: int, reason: str):
    if not AUTO_STAGE5_POSTRUN_ENABLED:
        return

    conn = get_conn()
    cur = conn.cursor()
    queued_specialist_ids: list[int] = []
    try:
        ensure_agent_tables(cur)
        ensure_task_steps_columns(cur)
        ensure_audit_logs_table(cur)

        cur.execute(
            """
            SELECT id, status, user_input
            FROM task_runs
            WHERE id = %s;
            """,
            (task_id,),
        )
        task_row = cur.fetchone()
        if not task_row:
            return
        task_status = str(task_row.get("status") or "unknown")
        if task_status not in {"running", "waiting_approval"}:
            return

        cur.execute(
            """
            SELECT id, role, status, brief_artifact_id, output_artifact_id, execution_mode, execution_request_json,
                   source_task_run_id, assigned_step_orders_json, assigned_model, assigned_tool_profile
            FROM agent_runs
            WHERE task_run_id = %s
            ORDER BY id ASC;
            """,
            (task_id,),
        )
        agent_rows = list(cur.fetchall())
        if not agent_rows:
            return

        def is_mainline_row(row: dict[str, Any]) -> bool:
            role = str(row.get("role") or "")
            if role == "manager":
                return str(row.get("assigned_tool_profile") or "") == "manager-mainline"
            if role == "specialist":
                return (
                    is_mainline_specialist_execution_mode(row.get("execution_mode"))
                    and is_mainline_specialist_tool_profile(row.get("assigned_tool_profile"))
                )
            if role == "reviewer":
                return (
                    str(row.get("assigned_model") or "") == "review-postrun"
                    and str(row.get("assigned_tool_profile") or "") == "review-readonly"
                )
            return False

        if any(not is_mainline_row(row) for row in agent_rows):
            return

        manager_row = next((row for row in agent_rows if str(row.get("role") or "") == "manager"), None)
        specialist_rows = [row for row in agent_rows if str(row.get("role") or "") == "specialist"]
        if not manager_row or not specialist_rows:
            return

        cur.execute(
            """
            SELECT step_order, step_name, status, tool_name, input_payload, output_payload, error_message
            FROM task_steps
            WHERE task_id = %s
            ORDER BY step_order ASC;
            """,
            (task_id,),
        )
        step_rows = list(cur.fetchall())
        if not step_rows and task_status != "waiting_approval":
            return

        latest_evaluator = fetch_latest_evaluator_feedback(cur, task_id)
        fanout_strategy = resolve_specialist_fanout_strategy(task_row, latest_evaluator)
        if not bool(fanout_strategy.get("enabled")):
            return

        manager_objective = build_task_display_input(task_row)
        _, specialist_specs, _ = build_mainline_specialist_specs(
            step_rows=step_rows,
            task_row=task_row,
            fanout_strategy=fanout_strategy,
        )
        plan_artifact_id = manager_row.get("brief_artifact_id") or manager_row.get("output_artifact_id")

        for index, specialist_row in enumerate(specialist_rows, start=1):
            specialist_status = str(specialist_row.get("status") or "unknown")
            runtime_refresh = (
                specialist_row.get("output_artifact_id")
                and str(specialist_row.get("execution_mode") or "") == AUTO_STAGE5_RUNTIME_EXECUTION_MODE
            )
            if specialist_status in {"queued", "running"}:
                continue
            if specialist_row.get("output_artifact_id") and not runtime_refresh:
                continue
            if specialist_status == "completed" and not runtime_refresh:
                continue
            spec = specialist_specs[index - 1] if index - 1 < len(specialist_specs) else {
                "assigned_steps": [],
                "subtask_type": "readonly_step_digest",
                "tool_profile": "specialist-readonly",
                "source": {},
            }
            assigned_steps = list(spec.get("assigned_steps") or [])
            subtask_type = str(spec.get("subtask_type") or "readonly_step_digest")
            tool_profile = str(spec.get("tool_profile") or "specialist-readonly")
            source_payload = spec.get("source") or {}
            execution_request = build_specialist_execution_request(
                slot=index,
                manager_objective=manager_objective,
                assigned_steps=assigned_steps,
                brief_artifact_id=specialist_row.get("brief_artifact_id"),
                plan_artifact_id=plan_artifact_id,
                note=f"task runtime execution-time fanout ({reason})",
                execution_mode=AUTO_STAGE5_RUNTIME_EXECUTION_MODE,
                tool_profile=tool_profile,
                subtask_type=subtask_type,
                source=source_payload,
            )
            cur.execute(
                """
                UPDATE agent_runs
                SET status = 'queued',
                    execution_mode = %s,
                    execution_request_json = %s,
                    source_task_run_id = %s,
                    assigned_step_orders_json = %s,
                    assigned_model = %s,
                    assigned_tool_profile = %s,
                    updated_at = CURRENT_TIMESTAMP,
                    completed_at = NULL,
                    error_summary = ''
                WHERE id = %s;
                """,
                (
                    AUTO_STAGE5_RUNTIME_EXECUTION_MODE,
                    safe_json_dumps(execution_request),
                    task_id,
                    safe_json_dumps(execution_request.get("assigned_step_orders") or []),
                    f"specialist-mainline-runtime-{index}",
                    tool_profile,
                    specialist_row["id"],
                ),
            )
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
                    "execution_mode": AUTO_STAGE5_RUNTIME_EXECUTION_MODE,
                    "subtask_type": subtask_type,
                    "execution_request": execution_request,
                    "reason": reason,
                    "source": "task_runtime_mainline",
                },
            )
            queued_specialist_ids.append(int(specialist_row["id"]))

        if not queued_specialist_ids:
            return

        insert_audit_log(
            cur,
            "agent.mainline_runtime_fanout",
            "worker",
            task_id,
            {
                "task_id": task_id,
                "manager_run_id": int(manager_row["id"]),
                "queued_specialist_ids": queued_specialist_ids,
                "reason": reason,
                "task_status": task_status,
                "fanout_strategy": fanout_strategy,
            },
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()

    for specialist_run_id in queued_specialist_ids:
        enqueue_agent_run(specialist_run_id)
        claim_token = f"{WORKER_ID}:inline_agent_run:{specialist_run_id}:{uuid.uuid4().hex}"
        if not acquire_agent_run_claim(specialist_run_id, claim_token):
            continue
        try:
            agent_run = fetch_agent_run_by_id(specialist_run_id)
            if agent_run and str(agent_run.get("status") or "") in {"queued", "running"}:
                process_agent_run(agent_run)
        finally:
            release_agent_run_claim(specialist_run_id, claim_token)


def maybe_create_task_postrun_agent_records(cur, task_id: int, user_input: str):
    if not AUTO_STAGE5_POSTRUN_ENABLED:
        return

    ensure_agent_tables(cur)
    ensure_evaluator_tables(cur)
    ensure_task_steps_columns(cur)
    ensure_audit_logs_table(cur)

    cur.execute(
        """
        SELECT id, session_id, created_by_actor, user_input, status, result, error_message,
               runtime_overrides,
               current_step, checkpoint_path, created_at, updated_at
        FROM task_runs
        WHERE id = %s;
        """,
        (task_id,),
    )
    task_row = cur.fetchone()
    if not task_row:
        return

    cur.execute(
        """
        SELECT step_order, step_name, status, tool_name, input_payload, output_payload, error_message
        FROM task_steps
        WHERE task_id = %s
        ORDER BY step_order ASC;
        """,
        (task_id,),
    )
    step_rows = list(cur.fetchall())

    manager_objective = build_task_display_input(task_row) or str(user_input or "").strip()
    latest_evaluator = fetch_latest_evaluator_feedback(cur, task_id)
    fanout_strategy = resolve_specialist_fanout_strategy(task_row, latest_evaluator)
    if not bool(fanout_strategy.get("enabled")):
        insert_audit_log(
            cur,
            "agent.postrun_skip_strategy",
            "worker",
            task_id,
            {"task_id": task_id, "fanout_strategy": fanout_strategy},
        )
        return
    step_outline, specialist_specs, step_status_counts = build_mainline_specialist_specs(
        step_rows=step_rows,
        task_row=task_row,
        fanout_strategy=fanout_strategy,
    )
    specialist_count = len(specialist_specs)

    cur.execute(
        """
        SELECT id, parent_agent_run_id, role, status, attempt, brief_artifact_id,
               output_artifact_id, review_artifact_id, execution_mode, execution_request_json,
               source_task_run_id, assigned_step_orders_json, assigned_model, assigned_tool_profile
        FROM agent_runs
        WHERE task_run_id = %s
        ORDER BY id ASC;
        """,
        (task_id,),
    )
    existing_agent_rows = list(cur.fetchall())

    def is_mainline_row(row: dict[str, Any]) -> bool:
        role = str(row.get("role") or "")
        if role == "manager":
            return str(row.get("assigned_tool_profile") or "") == "manager-mainline"
        if role == "specialist":
            return (
                is_mainline_specialist_execution_mode(row.get("execution_mode"))
                and is_mainline_specialist_tool_profile(row.get("assigned_tool_profile"))
            )
        if role == "reviewer":
            return (
                str(row.get("assigned_model") or "") == "review-postrun"
                and str(row.get("assigned_tool_profile") or "") == "review-readonly"
            )
        return False

    if existing_agent_rows and any(not is_mainline_row(row) for row in existing_agent_rows):
        insert_audit_log(
            cur,
            "agent.postrun_skip_existing",
            "worker",
            task_id,
            {"task_id": task_id, "existing_agent_run_count": len(existing_agent_rows)},
        )
        cur.connection.commit()
        return

    existing_manager_row = next((row for row in existing_agent_rows if str(row.get("role") or "") == "manager"), None)
    existing_reviewer_row = next((row for row in existing_agent_rows if str(row.get("role") or "") == "reviewer"), None)
    existing_specialist_rows = [row for row in existing_agent_rows if str(row.get("role") or "") == "specialist"]

    cur.execute(
        """
        SELECT id, agent_run_id, artifact_type, summary, content_json, version
        FROM agent_artifacts
        WHERE task_run_id = %s
        ORDER BY id ASC;
        """,
        (task_id,),
    )
    artifact_rows = list(cur.fetchall())
    plan_artifact_row = next((row for row in artifact_rows if str(row.get("artifact_type") or "") == "plan"), None)
    final_artifact_row = next((row for row in artifact_rows if str(row.get("artifact_type") or "") == "final"), None)
    review_artifact_row = next((row for row in artifact_rows if str(row.get("artifact_type") or "") == "review"), None)
    if final_artifact_row and review_artifact_row:
        insert_audit_log(
            cur,
            "agent.postrun_skip_finalized",
            "worker",
            task_id,
            {"task_id": task_id, "manager_run_id": existing_manager_row.get("id") if existing_manager_row else None},
        )
        cur.connection.commit()
        return

    manager_plan_artifact_id = int(plan_artifact_row["id"]) if plan_artifact_row else create_agent_artifact(
        cur,
        task_id,
        None,
        "plan",
        "task runtime postrun manager plan",
        {
            "protocol_version": MULTI_AGENT_PROTOCOL_VERSION,
            "task_id": task_id,
            "objective": manager_objective,
            "task_status": task_row.get("status") or "unknown",
            "plan_source": AUTO_STAGE5_EVALUATOR_SOURCE,
            "step_outline": step_outline,
            "step_status_counts": step_status_counts,
            "subtasks": [
                {
                    "role": "specialist",
                    "slot": int(spec.get("slot") or index + 1),
                    "scope": str(spec.get("scope") or "risk_result_digest"),
                }
                for index, spec in enumerate(specialist_specs)
            ],
        },
    )
    manager_run_id = int(existing_manager_row["id"]) if existing_manager_row else create_agent_run(
        cur,
        task_id,
        "manager",
        "running",
        brief_artifact_id=manager_plan_artifact_id,
        output_artifact_id=manager_plan_artifact_id,
        assigned_model="planner-postrun",
        assigned_tool_profile="manager-mainline",
        started=True,
    )

    specialist_run_ids: list[int] = []
    specialist_draft_ids: list[int] = []
    created_message_ids: list[int] = []

    while len(existing_specialist_rows) < specialist_count:
        slot = len(existing_specialist_rows) + 1
        spec = specialist_specs[slot - 1]
        assigned_steps = list(spec.get("assigned_steps") or [])
        subtask_type = str(spec.get("subtask_type") or "readonly_step_digest")
        tool_profile = str(spec.get("tool_profile") or "specialist-readonly")
        source_payload = spec.get("source") or {}
        brief_artifact_id = create_agent_artifact(
            cur,
            task_id,
            None,
            "brief",
            f"postrun specialist-{slot} brief",
            {
                "protocol_version": MULTI_AGENT_PROTOCOL_VERSION,
                "objective": manager_objective,
                "scope": f"子问题 {slot}",
                "constraints": ["遵守当前 task scope", "不要直接给最终结论"],
                "success_criteria": [f"完成子问题 {slot} 的可交付草稿"],
                "input_refs": [{"artifact_id": manager_plan_artifact_id, "label": "manager_plan"}],
            },
        )
        execution_request = build_specialist_execution_request(
            slot=slot,
            manager_objective=manager_objective,
            assigned_steps=assigned_steps,
            brief_artifact_id=brief_artifact_id,
            plan_artifact_id=manager_plan_artifact_id,
            note="task runtime postrun",
            tool_profile=tool_profile,
            subtask_type=subtask_type,
            source=source_payload,
        )
        specialist_run_id = create_agent_run(
            cur,
            task_id,
            "specialist",
            "planned",
            parent_agent_run_id=manager_run_id,
            brief_artifact_id=brief_artifact_id,
            execution_mode=AUTO_STAGE5_EXECUTION_MODE,
            execution_request=execution_request,
            source_task_run_id=task_id,
            assigned_step_orders=execution_request.get("assigned_step_orders") or [],
            assigned_model=f"specialist-postrun-{slot}",
            assigned_tool_profile=tool_profile,
        )
        existing_specialist_rows.append(
            {
                "id": specialist_run_id,
                "role": "specialist",
                "brief_artifact_id": brief_artifact_id,
                "output_artifact_id": None,
                "execution_mode": AUTO_STAGE5_EXECUTION_MODE,
                "execution_request_json": safe_json_dumps(execution_request),
                "assigned_tool_profile": tool_profile,
            }
        )
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
                    "execution_request": execution_request,
                },
            )
        )

    existing_specialist_rows = existing_specialist_rows[:specialist_count]
    if not existing_reviewer_row:
        reviewer_run_id = create_agent_run(
            cur,
            task_id,
            "reviewer",
            "planned",
            parent_agent_run_id=manager_run_id,
            source_task_run_id=task_id,
            assigned_model="review-postrun",
            assigned_tool_profile="review-readonly",
        )
    else:
        reviewer_run_id = int(existing_reviewer_row["id"])

    for index, specialist_row in enumerate(existing_specialist_rows, start=1):
        slot = index
        specialist_run_id = int(specialist_row["id"])
        specialist_run_ids.append(specialist_run_id)
        existing_output_artifact_id = specialist_row.get("output_artifact_id")
        specialist_execution_mode = str(specialist_row.get("execution_mode") or "")
        refresh_runtime_output = bool(existing_output_artifact_id) and specialist_execution_mode == AUTO_STAGE5_RUNTIME_EXECUTION_MODE
        if existing_output_artifact_id and not refresh_runtime_output:
            specialist_draft_ids.append(int(existing_output_artifact_id))
            continue
        spec = specialist_specs[index - 1] if index - 1 < len(specialist_specs) else {
            "assigned_steps": [],
            "tool_profile": "specialist-readonly",
            "subtask_type": "readonly_step_digest",
            "source": {},
        }
        assigned_steps = list(spec.get("assigned_steps") or [])
        brief_artifact_id = specialist_row.get("brief_artifact_id")
        execution_request = parse_jsonish(specialist_row.get("execution_request_json"), {})
        if not execution_request:
            execution_request = build_specialist_execution_request(
                slot=slot,
                manager_objective=manager_objective,
                assigned_steps=assigned_steps,
                brief_artifact_id=brief_artifact_id,
                plan_artifact_id=manager_plan_artifact_id,
                note="task runtime postrun",
                tool_profile=str(spec.get("tool_profile") or "specialist-readonly"),
                subtask_type=str(spec.get("subtask_type") or "readonly_step_digest"),
                source=spec.get("source") or {},
            )
        draft_version = 1
        if existing_output_artifact_id:
            cur.execute(
                """
                SELECT version
                FROM agent_artifacts
                WHERE id = %s;
                """,
                (existing_output_artifact_id,),
            )
            existing_output_row = cur.fetchone()
            draft_version = int((existing_output_row or {}).get("version") or 1) + 1
        draft_artifact_id = create_agent_artifact(
            cur,
            task_id,
            specialist_run_id,
            "draft",
            f"postrun specialist-{slot} draft",
            build_specialist_draft_payload(
                slot=slot,
                task_id=task_id,
                agent_run_id=specialist_run_id,
                manager_objective=manager_objective,
                task_row=task_row,
                step_outline=step_outline,
                assigned_steps=assigned_steps,
                plan_artifact_id=manager_plan_artifact_id,
                note="task runtime postrun",
                step_status_counts=step_status_counts,
                execution_request=execution_request,
            ),
            version=draft_version,
        )
        specialist_draft_ids.append(draft_artifact_id)
        cur.execute(
            """
            UPDATE agent_runs
            SET status = 'completed',
                output_artifact_id = %s,
                execution_mode = %s,
                execution_request_json = %s,
                source_task_run_id = %s,
                assigned_step_orders_json = %s,
                started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                completed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP,
                error_summary = ''
            WHERE id = %s;
            """,
            (
                draft_artifact_id,
                AUTO_STAGE5_EXECUTION_MODE,
                safe_json_dumps(execution_request),
                task_id,
                safe_json_dumps(execution_request.get("assigned_step_orders") or []),
                specialist_run_id,
            ),
        )
        created_message_ids.append(
            create_agent_message(
                cur,
                task_id,
                specialist_run_id,
                "specialist",
                "manager",
                "result",
                {
                    "protocol_version": MULTI_AGENT_PROTOCOL_VERSION,
                    "status": "completed",
                    "artifact_ids": [draft_artifact_id],
                    "summary": f"specialist-{slot} mainline draft {'refreshed' if refresh_runtime_output else 'completed'}",
                },
            )
        )
    reviewer_decision, decision_source = resolve_reviewer_decision(
        task_status=str(task_row.get("status") or "unknown"),
        step_rows=step_rows,
        specialist_draft_count=len(specialist_draft_ids),
    )
    quality_bundle = build_review_criteria(
        task_status=str(task_row.get("status") or "unknown"),
        step_rows=step_rows,
        specialist_draft_count=len(specialist_draft_ids),
        reviewer_decision=reviewer_decision,
    )
    failure_profile = derive_evaluator_failure_profile(
        task_status=str(task_row.get("status") or "unknown"),
        step_rows=step_rows,
        specialist_draft_count=len(specialist_draft_ids),
        reviewer_decision=reviewer_decision,
    )

    blocking_issues: list[str] = []
    follow_up_actions: list[str] = []
    reasoning_summary = "基于主链 task runtime 自动生成的 reviewer 结论"
    manager_status = "completed"
    manager_error_summary = ""
    next_strategy = "complete"
    if reviewer_decision == "rework_required":
        blocking_issues = ["reviewer 要求基于主链结果继续补强 specialist outputs"]
        follow_up_actions = ["补齐 pending/running steps", "重新汇总 final candidate"]
        manager_status = "blocked"
        manager_error_summary = "reviewer requested rework"
        next_strategy = "retry_specialists"
    elif reviewer_decision == "rejected":
        blocking_issues = ["reviewer 拒绝当前 manager final candidate"]
        follow_up_actions = ["检查 failed steps", "必要时升级人工处理"]
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
        "note": "task runtime postrun",
    }
    review_artifact_id = create_agent_artifact(
        cur,
        task_id,
        reviewer_run_id,
        "review",
        "task runtime reviewer decision",
        review_payload,
        version=1,
    )
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
        (review_artifact_id, reviewer_run_id),
    )
    created_message_ids.append(
        create_agent_message(
            cur,
            task_id,
            reviewer_run_id,
            "reviewer",
            "manager",
            "review_decision",
            {
                "protocol_version": MULTI_AGENT_PROTOCOL_VERSION,
                "decision": reviewer_decision,
                "quality_score": quality_bundle["score"],
                "failure_reason": failure_profile["failure_reason"],
                "failure_stage": failure_profile["failure_stage"],
                "decision_source": decision_source,
            },
        )
    )

    final_artifact_payload = {
        "protocol_version": MULTI_AGENT_PROTOCOL_VERSION,
        "summary": "manager 汇总主链执行结果并生成 final artifact",
        "final_output": {
            "task_id": task_id,
            "objective": manager_objective,
            "specialist_draft_count": len(specialist_draft_ids),
            "review_status": reviewer_decision,
            "task_status": task_row.get("status") or "unknown",
            "step_count": len(step_rows),
            "next_strategy": next_strategy,
            "quality_score": quality_bundle["score"],
            "failure_reason": failure_profile["failure_reason"],
            "failure_stage": failure_profile["failure_stage"],
            "decision_source": decision_source,
            "source": AUTO_STAGE5_EVALUATOR_SOURCE,
        },
        "source_artifact_refs": specialist_draft_ids,
        "review_status": reviewer_decision,
        "next_strategy": next_strategy,
        "quality_criteria": quality_bundle["criteria"],
        "quality_score": quality_bundle["score"],
        "step_stats": quality_bundle["step_stats"],
        "failure_reason": failure_profile["failure_reason"],
        "failure_stage": failure_profile["failure_stage"],
        "decision_source": decision_source,
    }
    final_artifact_id = create_agent_artifact(
        cur,
        task_id,
        manager_run_id,
        "final",
        "task runtime manager final artifact",
        final_artifact_payload,
        version=1,
    )
    cur.execute(
        """
        UPDATE agent_runs
        SET status = %s,
            output_artifact_id = %s,
            error_summary = %s,
            started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
            completed_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s;
        """,
        (manager_status, final_artifact_id, manager_error_summary, manager_run_id),
    )
    created_message_ids.append(
        create_agent_message(
            cur,
            task_id,
            manager_run_id,
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
                "decision_source": decision_source,
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
        manager_agent_run_id=manager_run_id,
        reviewer_agent_run_id=reviewer_run_id,
        final_artifact_id=final_artifact_id,
        review_artifact_id=review_artifact_id,
        decision=reviewer_decision,
        score=quality_bundle["score"],
        failure_reason=failure_profile["failure_reason"],
        failure_stage=failure_profile["failure_stage"],
        criteria=quality_bundle["criteria"],
        step_stats=quality_bundle["step_stats"],
        workflow_proposal=workflow_proposal,
        summary=evaluator_summary,
        recommendation=evaluator_recommendation,
        source=AUTO_STAGE5_EVALUATOR_SOURCE,
    )
    insert_audit_log(
        cur,
        "agent.postrun_auto",
        "worker",
        task_id,
        {
            "task_id": task_id,
            "manager_run_id": manager_run_id,
            "specialist_run_ids": specialist_run_ids,
            "reviewer_run_id": reviewer_run_id,
            "specialist_count": specialist_count,
            "execution_mode": AUTO_STAGE5_EXECUTION_MODE,
            "task_status": task_row.get("status") or "unknown",
        },
    )
    insert_audit_log(
        cur,
        "evaluator.recorded",
        "worker",
        task_id,
        {
            "task_id": task_id,
            "evaluator_run_id": evaluator_run_id,
            "manager_run_id": manager_run_id,
            "reviewer_run_id": reviewer_run_id,
            "decision": reviewer_decision,
            "score": quality_bundle["score"],
            "failure_reason": failure_profile["failure_reason"],
            "failure_stage": failure_profile["failure_stage"],
            "source": AUTO_STAGE5_EVALUATOR_SOURCE,
            "workflow_proposal": workflow_proposal,
        },
    )
    cur.connection.commit()


def maybe_initialize_task_runtime_agent_records(cur, task_id: int, user_input: str):
    if not AUTO_STAGE5_POSTRUN_ENABLED:
        return

    ensure_agent_tables(cur)
    ensure_evaluator_tables(cur)
    ensure_task_steps_columns(cur)
    ensure_audit_logs_table(cur)

    cur.execute(
        """
        SELECT id, role, execution_mode, assigned_model, assigned_tool_profile
        FROM agent_runs
        WHERE task_run_id = %s
        ORDER BY id ASC;
        """,
        (task_id,),
    )
    agent_rows = list(cur.fetchall())

    def is_mainline_row(row: dict[str, Any]) -> bool:
        role = str(row.get("role") or "")
        if role == "manager":
            return str(row.get("assigned_tool_profile") or "") == "manager-mainline"
        if role == "specialist":
            return (
                is_mainline_specialist_execution_mode(row.get("execution_mode"))
                and is_mainline_specialist_tool_profile(row.get("assigned_tool_profile"))
            )
        if role == "reviewer":
            return (
                str(row.get("assigned_model") or "") == "review-postrun"
                and str(row.get("assigned_tool_profile") or "") == "review-readonly"
            )
        return False

    if agent_rows:
        if any(not is_mainline_row(row) for row in agent_rows):
            return
        return

    cur.execute(
        """
        SELECT id, session_id, created_by_actor, user_input, status, result, error_message,
               runtime_overrides,
               current_step, checkpoint_path, created_at, updated_at
        FROM task_runs
        WHERE id = %s;
        """,
        (task_id,),
    )
    task_row = cur.fetchone()
    if not task_row:
        return

    cur.execute(
        """
        SELECT step_order, step_name, status, tool_name, input_payload, output_payload, error_message
        FROM task_steps
        WHERE task_id = %s
        ORDER BY step_order ASC;
        """,
        (task_id,),
    )
    step_rows = list(cur.fetchall())
    if not step_rows:
        return

    manager_objective = build_task_display_input(task_row) or str(user_input or "").strip()
    step_outline, specialist_specs, step_status_counts = build_mainline_specialist_specs(
        step_rows=step_rows,
        task_row=task_row,
    )
    specialist_count = len(specialist_specs)

    plan_artifact_id = create_agent_artifact(
        cur,
        task_id,
        None,
        "plan",
        "task runtime mainline manager plan",
        {
            "protocol_version": MULTI_AGENT_PROTOCOL_VERSION,
            "task_id": task_id,
            "objective": manager_objective,
            "task_status": task_row.get("status") or "unknown",
            "plan_source": "task_runtime_init_v1",
            "step_outline": step_outline,
            "step_status_counts": step_status_counts,
            "subtasks": [
                {
                    "role": "specialist",
                    "slot": int(spec.get("slot") or index + 1),
                    "scope": str(spec.get("scope") or "risk_result_digest"),
                }
                for index, spec in enumerate(specialist_specs)
            ],
        },
    )
    manager_run_id = create_agent_run(
        cur,
        task_id,
        "manager",
        "running",
        brief_artifact_id=plan_artifact_id,
        output_artifact_id=plan_artifact_id,
        assigned_model="planner-postrun",
        assigned_tool_profile="manager-mainline",
        started=True,
    )

    specialist_run_ids: list[int] = []
    for index, spec in enumerate(specialist_specs):
        slot = int(spec.get("slot") or index + 1)
        assigned_steps = list(spec.get("assigned_steps") or [])
        subtask_type = str(spec.get("subtask_type") or "readonly_step_digest")
        tool_profile = str(spec.get("tool_profile") or "specialist-readonly")
        source_payload = spec.get("source") or {}
        brief_artifact_id = create_agent_artifact(
            cur,
            task_id,
            None,
            "brief",
            f"task runtime specialist-{slot} brief",
            {
                "protocol_version": MULTI_AGENT_PROTOCOL_VERSION,
                "objective": manager_objective,
                "scope": f"子问题 {slot}",
                "constraints": ["遵守当前 task scope", "不要直接给最终结论"],
                "success_criteria": [f"完成子问题 {slot} 的可交付草稿"],
                "input_refs": [{"artifact_id": plan_artifact_id, "label": "manager_plan"}],
            },
        )
        execution_request = build_specialist_execution_request(
            slot=slot,
            manager_objective=manager_objective,
            assigned_steps=assigned_steps,
            brief_artifact_id=brief_artifact_id,
            plan_artifact_id=plan_artifact_id,
            note="task runtime init",
            tool_profile=tool_profile,
            subtask_type=subtask_type,
            source=source_payload,
        )
        specialist_run_id = create_agent_run(
            cur,
            task_id,
            "specialist",
            "planned",
            parent_agent_run_id=manager_run_id,
            brief_artifact_id=brief_artifact_id,
            execution_mode=AUTO_STAGE5_EXECUTION_MODE,
            execution_request=execution_request,
            source_task_run_id=task_id,
            assigned_step_orders=execution_request.get("assigned_step_orders") or [],
            assigned_model=f"specialist-postrun-{slot}",
            assigned_tool_profile=tool_profile,
        )
        specialist_run_ids.append(specialist_run_id)
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
                "execution_request": execution_request,
            },
        )

    reviewer_run_id = create_agent_run(
        cur,
        task_id,
        "reviewer",
        "planned",
        parent_agent_run_id=manager_run_id,
        source_task_run_id=task_id,
        assigned_model="review-postrun",
        assigned_tool_profile="review-readonly",
    )
    insert_audit_log(
        cur,
        "agent.postrun_initialized",
        "worker",
        task_id,
        {
            "task_id": task_id,
            "manager_run_id": manager_run_id,
            "specialist_run_ids": specialist_run_ids,
            "reviewer_run_id": reviewer_run_id,
            "specialist_count": specialist_count,
            "execution_mode": AUTO_STAGE5_EXECUTION_MODE,
        },
    )
    cur.connection.commit()


def record_worker_audit_event(event_type: str, task_id: int | None = None, details: Any | None = None):
    conn = get_conn()
    cur = conn.cursor()
    try:
        ensure_audit_logs_table(cur)
        insert_audit_log(cur, event_type, "worker", task_id, details)
        conn.commit()
    finally:
        cur.close()
        conn.close()


def parse_jsonish(value: Any, default: Any):
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default
    return value


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


def ensure_tool_registry_table(cur):
    if not _runtime_schema_bootstrap_active:
        ensure_runtime_schema_bootstrapped()
        return
    cur.execute("SELECT pg_advisory_xact_lock(hashtext('tool_registry_entries_schema'));")
    cur.execute("SELECT to_regclass('public.tool_registry_entries') AS regclass;")
    if not cur.fetchone()["regclass"]:
        cur.execute(
            """
            CREATE TABLE tool_registry_entries (
                tool_name TEXT PRIMARY KEY,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                provider_type TEXT NOT NULL DEFAULT 'builtin',
                transport TEXT NOT NULL DEFAULT 'local',
                server_name TEXT NOT NULL DEFAULT '',
                provider_config JSONB NOT NULL DEFAULT '{}'::jsonb,
                risk_level TEXT NOT NULL,
                approval_required BOOLEAN NOT NULL DEFAULT FALSE,
                description TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
    cur.execute("ALTER TABLE tool_registry_entries ADD COLUMN IF NOT EXISTS provider_type TEXT NOT NULL DEFAULT 'builtin';")
    cur.execute("ALTER TABLE tool_registry_entries ADD COLUMN IF NOT EXISTS transport TEXT NOT NULL DEFAULT 'local';")
    cur.execute("ALTER TABLE tool_registry_entries ADD COLUMN IF NOT EXISTS server_name TEXT NOT NULL DEFAULT '';")
    cur.execute("ALTER TABLE tool_registry_entries ADD COLUMN IF NOT EXISTS provider_config JSONB NOT NULL DEFAULT '{}'::jsonb;")
    cur.execute("ALTER TABLE tool_registry_entries ADD COLUMN IF NOT EXISTS approval_required BOOLEAN NOT NULL DEFAULT FALSE;")


def ensure_model_routes_table(cur):
    if not _runtime_schema_bootstrap_active:
        ensure_runtime_schema_bootstrapped()
        return
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
    if not _runtime_schema_bootstrap_active:
        ensure_runtime_schema_bootstrapped()
        return
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


def seed_default_tool_registry(cur):
    if not _runtime_schema_bootstrap_active:
        ensure_runtime_schema_bootstrapped()
        return
    ensure_tool_registry_table(cur)
    for tool_name, config in DEFAULT_TOOL_REGISTRY.items():
        cur.execute(
            """
            INSERT INTO tool_registry_entries (
                tool_name, enabled, provider_type, transport, server_name, provider_config, risk_level, approval_required, description
            )
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
            ON CONFLICT (tool_name) DO NOTHING;
            """,
            (
                tool_name,
                bool(config["enabled"]),
                str(config.get("provider_type") or "builtin"),
                str(config.get("transport") or "local"),
                str(config.get("server_name") or ""),
                safe_json_dumps(config.get("provider_config") or {}),
                str(config["risk_level"]),
                bool(config.get("approval_required", False)),
                str(config["description"]),
            ),
        )


def seed_default_model_routes(cur):
    if not _runtime_schema_bootstrap_active:
        ensure_runtime_schema_bootstrapped()
        return
    ensure_model_routes_table(cur)
    for route_name, config in DEFAULT_MODEL_ROUTES.items():
        cur.execute(
            """
            INSERT INTO model_routes (route_name, provider, model_name, temperature, max_tokens, enabled, description)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (route_name) DO NOTHING;
            """,
            (
                route_name,
                str(config["provider"]),
                str(config["model_name"]),
                float(config["temperature"]),
                int(config["max_tokens"]),
                bool(config["enabled"]),
                "",
            ),
        )


def seed_default_model_providers(cur):
    if not _runtime_schema_bootstrap_active:
        ensure_runtime_schema_bootstrapped()
        return
    ensure_model_providers_table(cur)
    for provider_name, config in DEFAULT_MODEL_PROVIDERS.items():
        cur.execute(
            """
            INSERT INTO model_providers (provider_name, driver, base_url, api_key_env, enabled, description)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (provider_name) DO NOTHING;
            """,
            (
                provider_name,
                str(config["driver"]),
                str(config["base_url"]),
                str(config["api_key_env"]),
                bool(config["enabled"]),
                "",
            ),
        )


def seed_default_risk_policies(cur):
    ensure_risk_policies_table(cur)
    descriptions = {
        "approval_low_risk_write_extensions": "新建这些扩展名的文件时可直接写入，无需审批。",
        "approval_sensitive_write_extensions": "写入这些脚本/配置类扩展名时必须审批。",
        "approval_sensitive_write_basenames": "写入这些特定文件名时必须审批。",
        "approval_require_for_existing_file_overwrite": "覆盖已有文件时是否要求审批。",
        "approval_require_for_hidden_files": "写入隐藏文件时是否要求审批。",
        "approval_allowed_http_methods": "这些 HTTP 方法默认允许直通，其余方法要求审批。",
        "approval_http_get_requires_approval_suffixes": "GET 请求命中这些域名后缀时仍要求审批。",
    }
    for policy_key, policy_value in DEFAULT_RISK_POLICIES.items():
        cur.execute(
            """
            INSERT INTO risk_policies (policy_key, value_type, policy_value, description)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (policy_key) DO NOTHING;
            """,
            (
                policy_key,
                "bool" if isinstance(policy_value, bool) else "json",
                safe_json_dumps(policy_value),
                descriptions.get(policy_key, ""),
            ),
        )


def load_risk_policy_settings(force_refresh: bool = False) -> dict[str, Any]:
    global _risk_policy_cache_value, _risk_policy_cache_expires_at

    now = time.time()
    if not force_refresh and _risk_policy_cache_value is not None and now < _risk_policy_cache_expires_at:
        return _risk_policy_cache_value

    settings = dict(DEFAULT_RISK_POLICIES)
    conn = get_conn()
    cur = conn.cursor()
    try:
        seed_default_risk_policies(cur)
        conn.commit()
        cur.execute(
            """
            SELECT policy_key, policy_value
            FROM risk_policies;
            """
        )
        for row in cur.fetchall():
            policy_key = str(row.get("policy_key") or "").strip()
            if not policy_key:
                continue
            try:
                settings[policy_key] = json.loads(row.get("policy_value") or "")
            except Exception:
                continue
    finally:
        cur.close()
        conn.close()

    _risk_policy_cache_value = settings
    _risk_policy_cache_expires_at = now + RISK_POLICY_CACHE_TTL_SECONDS
    return settings


def load_tool_registry_settings(force_refresh: bool = False) -> dict[str, dict[str, Any]]:
    global _tool_registry_cache_value, _tool_registry_cache_expires_at

    now = time.time()
    if not force_refresh and _tool_registry_cache_value is not None and now < _tool_registry_cache_expires_at:
        return _tool_registry_cache_value

    settings = {name: dict(config) for name, config in DEFAULT_TOOL_REGISTRY.items()}
    conn = get_conn()
    cur = conn.cursor()
    try:
        seed_default_tool_registry(cur)
        conn.commit()
        cur.execute(
            """
            SELECT tool_name, enabled, provider_type, transport, server_name, provider_config, risk_level, approval_required, description
            FROM tool_registry_entries;
            """
        )
        for row in cur.fetchall():
            tool_name = str(row.get("tool_name") or "").strip()
            if not tool_name:
                continue
            settings[tool_name] = {
                "enabled": bool(row.get("enabled")),
                "provider_type": str(row.get("provider_type") or "builtin"),
                "transport": str(row.get("transport") or "local"),
                "server_name": str(row.get("server_name") or ""),
                "provider_config": parse_jsonish(row.get("provider_config"), {}) or {},
                "risk_level": str(row.get("risk_level") or "low"),
                "approval_required": bool(row.get("approval_required")),
                "description": str(row.get("description") or ""),
            }
    finally:
        cur.close()
        conn.close()

    _tool_registry_cache_value = settings
    _tool_registry_cache_expires_at = now + TOOL_REGISTRY_CACHE_TTL_SECONDS
    return settings


def load_model_route_settings(force_refresh: bool = False) -> dict[str, dict[str, Any]]:
    global _model_route_cache_value, _model_route_cache_expires_at

    now = time.time()
    if not force_refresh and _model_route_cache_value is not None and now < _model_route_cache_expires_at:
        return _model_route_cache_value

    settings = {name: dict(config) for name, config in DEFAULT_MODEL_ROUTES.items()}
    conn = get_conn()
    cur = conn.cursor()
    try:
        seed_default_model_routes(cur)
        conn.commit()
        cur.execute(
            """
            SELECT route_name, provider, model_name, temperature, max_tokens, enabled
            FROM model_routes;
            """
        )
        for row in cur.fetchall():
            route_name = str(row.get("route_name") or "").strip()
            if not route_name:
                continue
            settings[route_name] = {
                "provider": str(row.get("provider") or "openai_compatible"),
                "model_name": str(row.get("model_name") or ""),
                "temperature": float(row.get("temperature") or 0.2),
                "max_tokens": int(row.get("max_tokens") or 800),
                "enabled": bool(row.get("enabled")),
            }
    finally:
        cur.close()
        conn.close()

    _model_route_cache_value = settings
    _model_route_cache_expires_at = now + MODEL_ROUTE_CACHE_TTL_SECONDS
    return settings


def load_model_provider_settings(force_refresh: bool = False) -> dict[str, dict[str, Any]]:
    global _model_provider_cache_value, _model_provider_cache_expires_at

    now = time.time()
    if not force_refresh and _model_provider_cache_value is not None and now < _model_provider_cache_expires_at:
        return _model_provider_cache_value

    settings = {name: dict(config) for name, config in DEFAULT_MODEL_PROVIDERS.items()}
    conn = get_conn()
    cur = conn.cursor()
    try:
        seed_default_model_providers(cur)
        conn.commit()
        cur.execute(
            """
            SELECT provider_name, driver, base_url, api_key_env, enabled
            FROM model_providers;
            """
        )
        for row in cur.fetchall():
            provider_name = str(row.get("provider_name") or "").strip()
            if not provider_name:
                continue
            settings[provider_name] = {
                "driver": str(row.get("driver") or "openai_compatible"),
                "base_url": str(row.get("base_url") or "").strip(),
                "api_key_env": str(row.get("api_key_env") or "").strip(),
                "enabled": bool(row.get("enabled")),
            }
    finally:
        cur.close()
        conn.close()

    _model_provider_cache_value = settings
    _model_provider_cache_expires_at = now + MODEL_PROVIDER_CACHE_TTL_SECONDS
    return settings


def get_model_provider_config(provider_name: str) -> dict[str, Any]:
    providers = load_model_provider_settings()
    config = providers.get(provider_name)
    if config is None:
        raise ValueError(f"模型 provider 未注册: {provider_name}")
    if not bool(config.get("enabled", True)):
        raise ValueError(f"模型 provider 已禁用: {provider_name}")
    return config


def get_model_provider_client(provider_name: str) -> OpenAI:
    config = get_model_provider_config(provider_name)
    driver = str(config.get("driver") or "openai_compatible")
    if driver != "openai_compatible":
        raise ValueError(f"不支持的模型 provider driver: {driver}")

    base_url = str(config.get("base_url") or "").strip()
    api_key_env = str(config.get("api_key_env") or "").strip()
    if not base_url:
        raise ValueError(f"模型 provider 缺少 base_url: {provider_name}")
    if not api_key_env:
        raise ValueError(f"模型 provider 缺少 api_key_env: {provider_name}")

    api_key = os.environ.get(api_key_env, "")
    cache_key = (provider_name, base_url, api_key_env)
    client = _model_provider_client_cache.get(cache_key)
    if client is None:
        client = OpenAI(api_key=api_key, base_url=base_url)
        _model_provider_client_cache[cache_key] = client
    return client


def get_model_route_config(
    route_name: str,
    route_overrides: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    routes = load_model_route_settings()
    config = routes.get(route_name)
    if config is None:
        raise ValueError(f"模型路由未注册: {route_name}")
    merged_config = dict(config)
    override_config = (route_overrides or {}).get(route_name)
    if isinstance(override_config, dict):
        merged_config.update(override_config)
    merged_config = {
        "provider": str(merged_config.get("provider") or "openai_compatible"),
        "model_name": str(merged_config.get("model_name") or ""),
        "temperature": float(merged_config.get("temperature") or 0.2),
        "max_tokens": int(merged_config.get("max_tokens") or 800),
        "enabled": bool(merged_config.get("enabled", True)),
    }
    if not bool(merged_config.get("enabled", True)):
        raise ValueError(f"模型路由已禁用: {route_name}")
    provider_name = str(merged_config.get("provider") or "").strip()
    if not provider_name:
        raise ValueError(f"模型路由缺少 provider: {route_name}")
    get_model_provider_config(provider_name)
    return merged_config


def snapshot_model_route_config(
    route_name: str,
    route_overrides: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    route = get_model_route_config(route_name, route_overrides=route_overrides)
    return {
        "route_name": route_name,
        "provider": str(route.get("provider") or ""),
        "model_name": str(route.get("model_name") or ""),
        "temperature": float(route.get("temperature") or 0.0),
        "max_tokens": int(route.get("max_tokens") or 0),
        "enabled": bool(route.get("enabled", True)),
    }


def serialize_model_route_runtime_info(route_name: str, route: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(route, dict):
        return {}
    return {
        "route_name": str(route_name or "").strip(),
        "provider": str(route.get("provider") or "").strip(),
        "model_name": str(route.get("model_name") or "").strip(),
        "temperature": float(route.get("temperature") or 0.0),
        "max_tokens": int(route.get("max_tokens") or 0),
        "enabled": bool(route.get("enabled", True)),
    }


def ensure_tool_enabled(tool_name: str):
    registry = load_tool_registry_settings()
    config = registry.get(tool_name)
    if config is None:
        raise ValueError(f"工具未注册: {tool_name}")
    if not bool(config.get("enabled", True)):
        raise ValueError(f"工具已禁用: {tool_name}")


def get_tool_registry_entry(tool_name: str) -> dict[str, Any] | None:
    registry = load_tool_registry_settings()
    config = registry.get(tool_name)
    return dict(config) if isinstance(config, dict) else None


def update_task_status(cur, task_id: int, status: str, result: Optional[str] = None, error_message: Optional[str] = None):
    cur.execute(
        """
        UPDATE task_runs
        SET status = %s,
            result = %s,
            error_message = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s;
        """,
        (status, result, error_message, task_id),
    )


def update_task_progress(
    cur,
    task_id: int,
    *,
    current_step: Optional[int] = None,
    checkpoint_path: Optional[str] = None,
):
    cur.execute(
        """
        UPDATE task_runs
        SET current_step = COALESCE(%s, current_step),
            checkpoint_path = COALESCE(%s, checkpoint_path),
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s;
        """,
        (current_step, checkpoint_path, task_id),
    )


def create_structured_steps(cur, task_id: int, steps: list[dict]):
    ensure_task_steps_columns(cur)
    ensure_approvals_table(cur)

    for idx, step in enumerate(steps, start=1):
        step_order = int(step.get("step_order") or idx)
        title = str(step.get("title") or f"步骤 {step_order}")
        tool_name = str(step.get("tool") or "").strip()
        input_payload = safe_json_dumps(step.get("input", {}))
        run_if = safe_json_dumps(step.get("run_if")) if step.get("run_if") is not None else None
        skip_if = safe_json_dumps(step.get("skip_if")) if step.get("skip_if") is not None else None
        error_strategy = str(step.get("error_strategy") or "fail").strip() or "fail"
        max_retries = int(step.get("max_retries") or default_max_retries_for_tool(tool_name))

        cur.execute(
            """
            INSERT INTO task_steps (
                task_id, step_order, step_name, tool_name, status,
                input_payload, output_payload, output_data, error_message, run_if, skip_if, retry_count, max_retries, error_strategy
            )
            VALUES (%s, %s, %s, %s, 'pending', %s, %s, %s, %s, %s, %s, 0, %s, %s);
            """,
            (
                task_id,
                step_order,
                title,
                tool_name,
                input_payload,
                None,
                None,
                "",
                run_if,
                skip_if,
                max_retries,
                error_strategy,
            ),
        )


def create_legacy_steps(cur, task_id: int, step_names: list[str]):
    ensure_task_steps_columns(cur)
    ensure_approvals_table(cur)

    for idx, step_name in enumerate(step_names, start=1):
        cur.execute(
            """
            INSERT INTO task_steps (
                task_id, step_order, step_name, tool_name, status,
                input_payload, output_payload, output_data, error_message, run_if, skip_if, retry_count, max_retries, error_strategy
            )
            VALUES (%s, %s, %s, %s, 'pending', %s, %s, %s, %s, %s, %s, 0, %s, %s);
            """,
            (
                task_id,
                idx,
                step_name,
                None,
                None,
                None,
                None,
                "",
                None,
                None,
                0,
                "fail",
            ),
        )


def set_step_running(cur, task_id: int, step_order: int):
    cur.execute(
        """
        UPDATE task_steps
        SET status = 'running',
            updated_at = CURRENT_TIMESTAMP
        WHERE task_id = %s AND step_order = %s;
        """,
        (task_id, step_order),
    )


def set_step_retry_count(cur, task_id: int, step_order: int, retry_count: int):
    cur.execute(
        """
        UPDATE task_steps
        SET retry_count = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE task_id = %s AND step_order = %s;
        """,
        (retry_count, task_id, step_order),
    )


def set_step_result(
    cur,
    task_id: int,
    step_order: int,
    status: str,
    tool_name: Optional[str],
    input_payload: Any,
    output_payload: Optional[str],
    output_data: Any,
    error_message: str,
    error_strategy: str,
):
    cur.execute(
        """
        UPDATE task_steps
        SET status = %s,
            tool_name = %s,
            input_payload = %s,
            output_payload = %s,
            output_data = %s,
            error_message = %s,
            error_strategy = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE task_id = %s AND step_order = %s;
        """,
        (
            status,
            tool_name,
            safe_json_dumps(input_payload) if input_payload is not None else None,
            output_payload,
            safe_json_dumps(output_data) if output_data is not None else None,
            error_message or "",
            error_strategy or "fail",
            task_id,
            step_order,
        ),
    )


def get_task_steps(cur, task_id: int) -> list[dict]:
    cur.execute(
        """
        SELECT id, task_id, step_order, step_name, tool_name, status,
               input_payload, output_payload, output_data, error_message, run_if, skip_if, retry_count, max_retries, error_strategy,
               created_at, updated_at
        FROM task_steps
        WHERE task_id = %s
        ORDER BY step_order ASC;
        """,
        (task_id,),
    )
    return list(cur.fetchall())


def get_step_approval(cur, task_id: int, step_order: int) -> Optional[dict]:
    ensure_approvals_table(cur)
    cur.execute(
        """
        SELECT id, task_id, step_order, step_name, tool_name, input_payload, reason, status, decision_note
        FROM approvals
        WHERE task_id = %s AND step_order = %s
        ORDER BY id DESC
        LIMIT 1;
        """,
        (task_id, step_order),
    )
    return cur.fetchone()


def create_step_approval(
    cur,
    task_id: int,
    step_order: int,
    step_name: str,
    tool_name: str,
    input_payload: Any,
    reason: str,
):
    ensure_approvals_table(cur)
    cur.execute(
        """
        INSERT INTO approvals (
            task_id, step_order, step_name, tool_name, input_payload, reason, status
        )
        VALUES (%s, %s, %s, %s, %s, %s, 'pending');
        """,
        (task_id, step_order, step_name, tool_name, safe_json_dumps(input_payload), reason),
    )


def set_step_waiting_approval(cur, task_id: int, step_order: int, tool_name: str, input_payload: Any, reason: str):
    set_step_result(
        cur,
        task_id,
        step_order,
        status="waiting_approval",
        tool_name=tool_name,
        input_payload=input_payload,
        output_payload=f"等待审批：{reason}",
        output_data={"approval_required": True, "reason": reason},
        error_message="",
        error_strategy="fail",
    )


def build_structured_steps_from_rows(rows: list[dict]) -> list[dict]:
    planned = []
    for row in rows:
        planned.append(
            {
                "id": int(row["id"]),
                "step_order": int(row["step_order"]),
                "title": str(row.get("step_name") or f"步骤 {row['step_order']}"),
                "tool": str(row.get("tool_name") or "").strip(),
                "input": parse_json_text(row.get("input_payload"), {}),
                "run_if": parse_json_text(row.get("run_if")),
                "skip_if": parse_json_text(row.get("skip_if")),
                "retry_count": int(row.get("retry_count") or 0),
                "max_retries": int(row.get("max_retries") or 0),
                "error_strategy": str(row.get("error_strategy") or "fail"),
                "status": str(row.get("status") or "pending"),
                "output_payload": row.get("output_payload"),
                "output_data": parse_json_text(row.get("output_data")),
            }
        )
    return planned


def hydrate_contexts_from_steps(steps: list[dict]) -> tuple[dict[int, dict], dict[str, Any], list[str]]:
    step_context: dict[int, dict] = {}
    var_context: dict[str, Any] = {}
    step_outputs: list[str] = []

    for step in steps:
        if step.get("status") != "completed":
            continue

        step_order = int(step["step_order"])
        output_payload = step.get("output_payload")
        output_data = step.get("output_data")
        step_context[step_order] = {
            "output_payload": output_payload,
            "output_data": output_data,
        }
        if isinstance(output_payload, str) and output_payload.strip():
            step_outputs.append(output_payload)

        if step.get("tool") == "set_var" and isinstance(output_data, dict):
            var_name = output_data.get("name")
            if isinstance(var_name, str) and var_name.strip():
                var_context[var_name.strip()] = output_data.get("value")

    return step_context, var_context, step_outputs


def should_require_approval(tool_name: str, payload: dict) -> tuple[bool, str]:
    settings = load_risk_policy_settings()
    registry_entry = get_tool_registry_entry(tool_name)
    if registry_entry and bool(registry_entry.get("approval_required")):
        provider_type = str(registry_entry.get("provider_type") or "builtin")
        return True, f"{tool_name} 已配置 approval_required=true，需要人工审批（provider_type={provider_type}）"

    if tool_name == "shell_exec":
        command = str(payload.get("command") or "").strip()
        return True, f"shell_exec 属于高风险执行工具: {command or '(empty)'}"

    if tool_name in {"file_write", "write_json"}:
        low_risk_write_extensions = {str(item).lower() for item in settings.get("approval_low_risk_write_extensions", LOW_RISK_WRITE_EXTENSIONS) if str(item).strip()}
        sensitive_write_extensions = {str(item).lower() for item in settings.get("approval_sensitive_write_extensions", SENSITIVE_WRITE_EXTENSIONS) if str(item).strip()}
        sensitive_write_basenames = {str(item).lower() for item in settings.get("approval_sensitive_write_basenames", SENSITIVE_WRITE_BASENAMES) if str(item).strip()}
        require_existing_file_overwrite = bool(settings.get("approval_require_for_existing_file_overwrite", True))
        require_hidden_files = bool(settings.get("approval_require_for_hidden_files", True))

        path_str = str(payload.get("path") or "").strip()
        if not path_str:
            return True, f"{tool_name} 缺少有效 path，需要人工审批"

        path = Path(path_str)
        suffix = path.suffix.lower()
        basename = path.name.lower()

        if basename in sensitive_write_basenames or suffix in sensitive_write_extensions:
            return True, f"{tool_name} 将写入脚本/配置文件: {path_str}"

        if require_existing_file_overwrite and path.exists():
            return True, f"{tool_name} 将覆盖现有文件: {path_str}"

        if require_hidden_files and basename.startswith("."):
            return True, f"{tool_name} 将写入隐藏文件: {path_str}"

        if suffix and suffix not in low_risk_write_extensions:
            return True, f"{tool_name} 将写入未列入低风险清单的文件类型: {path_str}"

        return False, ""

    if tool_name == "http_request":
        method = str(payload.get("method", "")).upper().strip()
        url = str(payload.get("url") or "").strip()
        allowed_http_methods = {str(item).upper() for item in settings.get("approval_allowed_http_methods", ["GET"]) if str(item).strip()}
        if method not in allowed_http_methods:
            return True, f"http_request {method or 'UNKNOWN'} 需要人工审批"

        parsed = urlparse(url)
        hostname = (parsed.hostname or "").strip().lower()
        approval_suffixes = tuple(
            str(item).lower()
            for item in settings.get("approval_http_get_requires_approval_suffixes", [".local"])
            if str(item).strip()
        )
        if approval_suffixes and hostname.endswith(approval_suffixes):
            return True, f"http_request GET 目标域名需要人工审批: {hostname}"

    return False, ""


def default_max_retries_for_tool(tool_name: str) -> int:
    if tool_name in {"web_search", "http_request", "summarize_text", "generate_text"}:
        return 1
    registry_entry = get_tool_registry_entry(tool_name)
    if registry_entry and str(registry_entry.get("provider_type") or "builtin") in {"mcp_stdio", "mcp_http"}:
        return 1
    return 0


def load_skill_definition(skill_id: str, version: str | None = None) -> dict[str, Any]:
    conn = get_conn()
    cur = conn.cursor()
    try:
        ensure_skill_registry_tables(cur)
        cur.execute(
            """
            SELECT skill_id, display_name, description, status, latest_version, entrypoint_kind
            FROM skills
            WHERE skill_id = %s;
            """,
            (skill_id,),
        )
        skill_row = cur.fetchone()
        if not skill_row:
            raise ValueError(f"Skill not found: {skill_id}")
        resolved_version = str(version or skill_row.get("latest_version") or "").strip()
        if not resolved_version:
            raise ValueError(f"Skill has no version: {skill_id}")
        cur.execute(
            """
            SELECT skill_id, version, package_body
            FROM skill_versions
            WHERE skill_id = %s AND version = %s;
            """,
            (skill_id, resolved_version),
        )
        version_row = cur.fetchone()
        if not version_row:
            raise ValueError(f"Skill version not found: {skill_id}@{resolved_version}")
        package_body = parse_jsonish(version_row.get("package_body"), {})
        if not isinstance(package_body, dict):
            raise ValueError(f"Skill package invalid: {skill_id}@{resolved_version}")
        return {
            "skill_id": skill_id,
            "version": resolved_version,
            "display_name": str(skill_row.get("display_name") or skill_id),
            "description": str(skill_row.get("description") or ""),
            "entrypoint_kind": str(skill_row.get("entrypoint_kind") or "structured_steps"),
            "package_body": package_body,
        }
    finally:
        cur.close()
        conn.close()


def _render_skill_template_value(value: Any, skill_args: dict[str, Any], user_input: str) -> Any:
    if isinstance(value, str):
        rendered = value.replace("{{USER_INPUT}}", user_input)
        for key, arg_value in skill_args.items():
            rendered = rendered.replace(f"{{{{args.{key}}}}}", str(arg_value))
        if rendered.startswith("__ARG__:"):
            arg_key = rendered.split(":", 1)[1]
            return skill_args.get(arg_key)
        return rendered
    if isinstance(value, list):
        return [_render_skill_template_value(item, skill_args, user_input) for item in value]
    if isinstance(value, dict):
        return {key: _render_skill_template_value(item, skill_args, user_input) for key, item in value.items()}
    return value


def build_skill_plan(skill_definition: dict[str, Any], *, user_input: str, skill_args: dict[str, Any] | None = None) -> list[dict]:
    package_body = skill_definition.get("package_body") or {}
    steps_template = package_body.get("steps_template") or []
    if not isinstance(steps_template, list) or not steps_template:
        raise ValueError(f"Skill steps_template invalid: {skill_definition.get('skill_id')}")
    rendered = _render_skill_template_value(steps_template, dict(skill_args or {}), user_input)
    if not isinstance(rendered, list) or not rendered:
        raise ValueError(f"Skill rendered no steps: {skill_definition.get('skill_id')}")
    return validate_planned_steps(rendered)


def extract_skill_arg_keys(skill_definition: dict[str, Any]) -> list[str]:
    package_body = skill_definition.get("package_body") or {}
    serialized = safe_json_dumps(package_body)
    keys = {match.group(1) for match in re.finditer(r"\{\{args\.([a-zA-Z0-9_]+)\}\}", serialized)}
    return sorted(key for key in keys if key)


def checkpoint_file_for_task(task_id: int) -> Path:
    return CHECKPOINT_DIR / f"task_{task_id}.json"


def write_checkpoint(
    cur,
    task_id: int,
    user_input: str,
    status: str,
    current_step: Optional[int],
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
    last_error: str = "",
):
    checkpoint_path = checkpoint_file_for_task(task_id)
    payload = {
        "task_id": task_id,
        "user_input": user_input,
        "status": status,
        "current_step": current_step,
        "step_context": step_context,
        "var_context": var_context,
        "step_outputs": step_outputs,
        "last_error": last_error,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    checkpoint_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    update_task_progress(cur, task_id, current_step=current_step, checkpoint_path=str(checkpoint_path))


# =========================
# Path / safety helpers
# =========================
def is_path_in_allowed_dirs(path_str: str, allowed_dirs: list[Path]) -> bool:
    try:
        target = Path(path_str).resolve()
        for base in allowed_dirs:
            try:
                target.relative_to(base.resolve())
                return True
            except ValueError:
                continue
        return False
    except Exception:
        return False


def ensure_readable_file(path_str: str) -> Path:
    if not path_str:
        raise ValueError("缺少文件路径")
    if not is_path_in_allowed_dirs(path_str, ALLOWED_READ_DIRS):
        raise ValueError(f"路径不在允许范围内 -> {path_str}")

    path = Path(path_str).resolve()
    if not path.exists():
        raise ValueError(f"文件不存在 -> {path_str}")
    if not path.is_file():
        raise ValueError(f"目标不是文件 -> {path_str}")
    return path


def ensure_writable_file(path_str: str) -> Path:
    if not path_str:
        raise ValueError("缺少文件路径")
    if not is_path_in_allowed_dirs(path_str, ALLOWED_WRITE_DIRS):
        raise ValueError(f"路径不在允许范围内 -> {path_str}")

    path = Path(path_str).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists() and path.is_dir():
        raise ValueError(f"目标是目录，不是文件 -> {path_str}")
    return path


def ensure_readable_dir(path_str: str) -> Path:
    if not path_str:
        raise ValueError("缺少目录路径")
    if not is_path_in_allowed_dirs(path_str, ALLOWED_READ_DIRS):
        raise ValueError(f"路径不在允许范围内 -> {path_str}")

    path = Path(path_str).resolve()
    if not path.exists():
        raise ValueError(f"目录不存在 -> {path_str}")
    if not path.is_dir():
        raise ValueError(f"目标不是目录 -> {path_str}")
    return path


# =========================
# Generic helpers
# =========================
def extract_path_from_text(text: str) -> Optional[str]:
    if not text:
        return None
    match = re.search(r"(/[^ \n\r\t'\"，。；：]+)", text)
    if match:
        return match.group(1)
    return None


def normalize_step_name(step: str) -> str:
    step = (step or "").strip()
    step = re.sub(r"^\s*\d+[\.\)、:：-]\s*", "", step)
    step = re.sub(r"^\s*第\s*\d+\s*步[\s:：\-]*", "", step)
    return step.strip()


def get_nested_value(data: Any, path_str: Optional[str]) -> Any:
    if path_str is None or path_str == "":
        return data

    current = data
    for part in path_str.split("."):
        if isinstance(current, dict):
            if part not in current:
                raise ValueError(f"引用路径不存在: {path_str}")
            current = current[part]
        elif isinstance(current, list):
            if not part.isdigit():
                raise ValueError(f"列表索引非法: {part}")
            idx = int(part)
            if idx < 0 or idx >= len(current):
                raise ValueError(f"列表索引越界: {part}")
            current = current[idx]
        else:
            raise ValueError(f"引用路径无法继续解析: {path_str}")
    return current


def resolve_reference_value(raw_value: Any, step_context: dict[int, dict], var_context: Optional[dict[str, Any]] = None) -> Any:
    if not isinstance(raw_value, str):
        return raw_value

    raw_value = raw_value.strip()

    if raw_value.startswith(VAR_REFERENCE_PREFIX):
        var_name = raw_value[len(VAR_REFERENCE_PREFIX):].strip()
        if not var_name:
            raise ValueError("变量引用不能为空")
        if var_context is None or var_name not in var_context:
            raise ValueError(f"引用变量不存在: {raw_value}")
        return var_context[var_name]

    m = REFERENCE_PATTERN.match(raw_value)
    if not m:
        return raw_value

    ref_step_order = int(m.group(1))
    ref_scope = m.group(2)
    ref_path = m.group(3)

    if ref_step_order not in step_context:
        raise ValueError(f"引用步骤不存在: {raw_value}")

    ref_step = step_context[ref_step_order]

    if ref_scope == "data":
        base = ref_step.get("output_data")
    else:
        base = ref_step.get("output_payload")

    return get_nested_value(base, ref_path)


def resolve_input_payload(payload: Any, step_context: dict[int, dict], var_context: Optional[dict[str, Any]] = None) -> Any:
    if isinstance(payload, dict):
        return {k: resolve_input_payload(v, step_context, var_context) for k, v in payload.items()}
    if isinstance(payload, list):
        return [resolve_input_payload(v, step_context, var_context) for v in payload]
    return resolve_reference_value(payload, step_context, var_context)


def try_resolve_reference(value: Any, step_context: dict[int, dict], var_context: Optional[dict[str, Any]] = None) -> Any:
    try:
        return resolve_input_payload(value, step_context, var_context)
    except Exception:
        return None


def resolve_template_expr(expr: str, step_context: dict[int, dict], var_context: Optional[dict[str, Any]] = None) -> Any:
    expr = (expr or "").strip()
    if not expr:
        raise ValueError("模板表达式不能为空")

    if expr.startswith("var."):
        var_name = expr[4:].strip()
        if not var_name:
            raise ValueError("模板变量名不能为空")
        if var_context is None or var_name not in var_context:
            raise ValueError(f"模板变量不存在: {expr}")
        return var_context[var_name]

    if expr.startswith("step."):
        parts = expr.split(".")
        if len(parts) < 3:
            raise ValueError(f"非法模板步骤引用: {expr}")
        step_order = parts[1]
        scope = parts[2]
        tail = ".".join(parts[3:]) if len(parts) > 3 else ""
        return resolve_reference_value(f"step:{step_order}.{scope}" + (f".{tail}" if tail else ""), step_context, var_context)

    return expr


def render_template_text(template: str, step_context: dict[int, dict], var_context: Optional[dict[str, Any]] = None, strict: bool = True) -> str:
    def repl(match: re.Match) -> str:
        expr = match.group(1)
        try:
            value = resolve_template_expr(expr, step_context, var_context)
        except Exception:
            if strict:
                raise
            return match.group(0)
        if value is None:
            return ""
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    return TEMPLATE_PATTERN.sub(repl, template)


def compare_values(left: Any, operator: str, right: Any) -> bool:
    if operator == "eq":
        return left == right
    if operator == "ne":
        return left != right
    if operator == "gt":
        return left > right
    if operator == "lt":
        return left < right
    if operator == "gte":
        return left >= right
    if operator == "lte":
        return left <= right
    if operator == "contains":
        if isinstance(left, str):
            return str(right) in left
        if isinstance(left, list):
            return right in left
        if isinstance(left, dict):
            return str(right) in left
        raise ValueError(f"contains 不支持的 left 类型: {type(left).__name__}")
    if operator == "exists":
        return left is not None
    if operator == "not_exists":
        return left is None
    raise ValueError(f"不支持的 operator: {operator}")


def should_run_step(step: dict, step_context: dict[int, dict], var_context: Optional[dict[str, Any]] = None) -> tuple[bool, str]:
    run_if = step.get("run_if")
    skip_if = step.get("skip_if")

    if run_if is not None:
        value = resolve_input_payload(run_if, step_context, var_context)
        if not isinstance(value, bool):
            raise ValueError(f"run_if 解析结果不是布尔值: {value}")
        if not value:
            return False, "run_if 条件不满足"

    if skip_if is not None:
        value = resolve_input_payload(skip_if, step_context, var_context)
        if not isinstance(value, bool):
            raise ValueError(f"skip_if 解析结果不是布尔值: {value}")
        if value:
            return False, "skip_if 条件满足，跳过"

    return True, ""


def normalize_http_request_input(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return payload

    normalized = dict(payload)

    if "data" in normalized and "json" not in normalized:
        normalized["json"] = normalized.pop("data")

    timeout = normalized.get("timeout", 15)
    if not isinstance(timeout, int):
        timeout = 15
    if timeout < 1:
        timeout = 1
    if timeout > 20:
        timeout = 20
    normalized["timeout"] = timeout

    return normalized


def normalize_web_search_input(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return payload

    normalized = dict(payload)
    if "query" not in normalized and isinstance(normalized.get("q"), str):
        normalized["query"] = normalized.pop("q")
    if isinstance(normalized.get("query"), str):
        normalized["query"] = sanitize_web_search_query(normalized.get("query") or "")
    return normalized


def iter_reference_strings(value: Any):
    if isinstance(value, str) and value.startswith("step:"):
        yield value
        return
    if isinstance(value, dict):
        for nested in value.values():
            yield from iter_reference_strings(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from iter_reference_strings(nested)


def validate_planned_steps(steps: list[dict]) -> list[dict]:
    normalized_steps: list[dict] = []
    tool_by_order: dict[int, str] = {}

    for step in steps:
        normalized_step = dict(step)
        tool_name = str(normalized_step.get("tool") or "").strip()
        step_order = int(normalized_step.get("step_order") or len(normalized_steps) + 1)
        raw_input = normalized_step.get("input") or {}

        if tool_name == "web_search":
            raw_input = normalize_web_search_input(raw_input)
            normalized_step["input"] = raw_input

        for ref in iter_reference_strings(raw_input):
            match = re.match(r"step:(\d+)\.(.+)", ref)
            if not match:
                continue
            ref_step_order = int(match.group(1))
            ref_path = match.group(2)
            producer_tool = tool_by_order.get(ref_step_order, "")
            if producer_tool == "web_search":
                if ref_path.startswith("data.json") or ref_path.startswith("data.results"):
                    raise ValueError(
                        f"planner 非法引用 web_search 输出: {ref}。"
                        "web_search 只允许引用 step:N.data.text、step:N.data.query 或 step:N.output"
                    )
                if tool_name == "json_extract" and str(normalized_step.get("input", {}).get("data")) == ref:
                    raise ValueError(
                        f"planner 非法地把 web_search 结果当作 json_extract 输入: {ref}"
                    )

        normalized_steps.append(normalized_step)
        tool_by_order[step_order] = tool_name

    return normalized_steps


def validate_input_value(tool_name: str, payload: dict):
    rules = TOOL_INPUT_RULES.get(tool_name)
    if not rules:
        config = get_tool_registry_entry(tool_name)
        if not config:
            raise ValueError(f"未知工具: {tool_name}")
        if str(config.get("provider_type") or "builtin").strip().lower() not in {"mcp_stdio", "mcp_http"}:
            raise ValueError(f"未知工具: {tool_name}")
        if not isinstance(payload, dict):
            raise ValueError(f"{tool_name} 的 input 必须是对象")
        return

    keys = set(payload.keys())
    missing = rules["required"] - keys
    if missing:
        raise ValueError(f"{tool_name} 缺少必填字段: {sorted(missing)}")

    unknown = keys - rules["required"] - rules["optional"]
    if unknown:
        raise ValueError(f"{tool_name} 存在非法字段: {sorted(unknown)}")

    if tool_name in {"file_read", "file_write", "list_dir", "read_json", "write_json"}:
        path_val = payload.get("path")
        if not isinstance(path_val, str) or not path_val.strip():
            raise ValueError(f"{tool_name} 的 path 非法")

    if tool_name == "file_write":
        if not isinstance(payload.get("content"), str):
            raise ValueError("file_write 的 content 必须是字符串")

    if tool_name == "shell_exec":
        if not isinstance(payload.get("command"), str) or not payload["command"].strip():
            raise ValueError("shell_exec 的 command 非法")

    if tool_name == "summarize_text":
        if not isinstance(payload.get("text"), str):
            raise ValueError("summarize_text 的 text 必须是字符串")

    if tool_name == "generate_text":
        if not isinstance(payload.get("prompt"), str) or not payload["prompt"].strip():
            raise ValueError("generate_text 的 prompt 必须是非空字符串")
        if "system_prompt" in payload and not isinstance(payload.get("system_prompt"), str):
            raise ValueError("generate_text 的 system_prompt 必须是字符串")

    if tool_name == "web_search":
        if not isinstance(payload.get("query"), str) or not payload["query"].strip():
            raise ValueError("web_search 的 query 非法")

    if tool_name == "write_json":
        data = payload.get("data")
        if not isinstance(data, (dict, list)):
            raise ValueError("write_json 的 data 必须是对象或数组")

    if tool_name == "http_request":
        url = payload.get("url")
        method = payload.get("method")
        timeout = payload.get("timeout", 15)

        if not isinstance(url, str) or not url.strip():
            raise ValueError("http_request 的 url 非法")

        if not isinstance(method, str) or method.upper().strip() not in {"GET", "POST"}:
            raise ValueError("http_request 的 method 仅支持 GET/POST")

        if not isinstance(timeout, int):
            raise ValueError("http_request 的 timeout 必须是整数")
        if timeout < 1 or timeout > 20:
            raise ValueError("http_request 的 timeout 必须在 1 到 20 之间")

        if "params" in payload and not isinstance(payload["params"], dict):
            raise ValueError("http_request 的 params 必须是对象")

        if "json" in payload and not isinstance(payload["json"], dict):
            raise ValueError("http_request 的 json 必须是对象")

    if tool_name == "json_extract":
        if not isinstance(payload.get("data"), (dict, list)):
            raise ValueError("json_extract 的 data 必须是对象或数组")
        if not isinstance(payload.get("path"), str) or not payload["path"].strip():
            raise ValueError("json_extract 的 path 必须是非空字符串")

    if tool_name == "if_condition":
        if not isinstance(payload, dict):
            raise ValueError("if_condition 的 input 必须是对象")

        has_single = all(k in payload for k in ["left", "operator", "right"])
        has_group = ("logic" in payload and "conditions" in payload)

        if has_single and has_group:
            raise ValueError("if_condition 不能同时使用单条件和组合条件格式")
        if not has_single and not has_group:
            raise ValueError("if_condition 必须提供 left/operator/right 或 logic/conditions")

        if has_single:
            operator = payload.get("operator")
            if not isinstance(operator, str) or operator not in SUPPORTED_OPERATORS:
                raise ValueError(f"if_condition 的 operator 非法: {operator}")

        if has_group:
            logic = payload.get("logic")
            conditions = payload.get("conditions")
            if not isinstance(logic, str) or logic not in SUPPORTED_LOGICS:
                raise ValueError(f"if_condition 的 logic 非法: {logic}")
            if not isinstance(conditions, list) or not conditions:
                raise ValueError("if_condition 的 conditions 必须是非空数组")
            if logic == "not" and len(conditions) != 1:
                raise ValueError("logic=not 时 conditions 必须只有 1 条")
            for idx, condition in enumerate(conditions, start=1):
                if not isinstance(condition, dict):
                    raise ValueError(f"if_condition.conditions[{idx}] 必须是对象")
                if not all(k in condition for k in ["left", "operator", "right"]):
                    raise ValueError(f"if_condition.conditions[{idx}] 缺少 left/operator/right")
                operator = condition.get("operator")
                if not isinstance(operator, str) or operator not in SUPPORTED_OPERATORS:
                    raise ValueError(f"if_condition.conditions[{idx}] 的 operator 非法: {operator}")


# =========================
# Planning
# =========================
def fallback_legacy_steps(user_input: str) -> list[str]:
    if "写入" in user_input and "/workspace/" in user_input:
        return ["读取文件内容", "整理文件要点", "写入摘要到文件"]
    if "读取文件" in user_input:
        return ["读取文件内容", "分析文件内容", "整理并输出结果"]
    if "列出目录" in user_input:
        return ["列出目录内容", "查看目录文件的关键信息", "整理关键内容并总结"]
    if "执行命令" in user_input or "shell" in user_input or "终端" in user_input:
        return ["执行命令", "读取命令输出内容", "整理输出内容"]
    if "调研" in user_input or "搜索" in user_input or "请求" in user_input or "接口" in user_input:
        return ["搜索资料", "整理方案", "对比分析", "制定可执行步骤"]
    return ["明确任务目标", "整理关键信息", "输出结果"]


def infer_structured_steps_from_user_input(user_input: str) -> list[dict]:
    src_path = extract_path_from_text(user_input)
    matches = re.findall(r"(/[^ \n\r\t'\"，。；：]+)", user_input)
    target_path = matches[-1] if len(matches) >= 2 else None

    # 提取“xxx 字段”
    extract_match = re.search(r"提取\s+([A-Za-z0-9_.]+)\s+字段", user_input)
    extract_path = extract_match.group(1).strip() if extract_match else None

    # JSON -> 变量 -> 写文件
    if (
        src_path
        and src_path.endswith(".json")
        and target_path
        and ("保存为变量" in user_input or "保存变量" in user_input)
        and ("planner" in user_input)
        and ("写入" in user_input)
    ):
        return [
            {
                "step_order": 1,
                "title": "读取 JSON 文件",
                "tool": "read_json",
                "input": {"path": src_path},
                "error_strategy": "fail",
            },
            {
                "step_order": 2,
                "title": "保存 planner 变量",
                "tool": "set_var",
                "input": {
                    "name": "planner_name",
                    "value": "step:1.data.json.planner",
                },
                "error_strategy": "fail",
            },
            {
                "step_order": 3,
                "title": "写入变量值",
                "tool": "file_write",
                "input": {
                    "path": target_path,
                    "content": "var:planner_name",
                },
                "error_strategy": "fail",
            },
        ]

    # JSON -> 模板渲染报告
    if (
        src_path
        and src_path.endswith(".json")
        and target_path
        and ("渲染成报告" in user_input or "渲染报告" in user_input)
        and ("planner" in user_input)
        and ("version" in user_input)
    ):
        return [
            {
                "step_order": 1,
                "title": "读取 JSON 文件",
                "tool": "read_json",
                "input": {"path": src_path},
                "error_strategy": "fail",
            },
            {
                "step_order": 2,
                "title": "保存 planner 变量",
                "tool": "set_var",
                "input": {
                    "name": "planner_name",
                    "value": "step:1.data.json.planner",
                },
                "error_strategy": "fail",
            },
            {
                "step_order": 3,
                "title": "保存 version 变量",
                "tool": "set_var",
                "input": {
                    "name": "version_text",
                    "value": "step:1.data.json.version",
                },
                "error_strategy": "fail",
            },
            {
                "step_order": 4,
                "title": "渲染 JSON 报告",
                "tool": "template_render",
                "input": {
                    "template": "# JSON 报告\n\nPlanner: {{var.planner_name}}\nVersion: {{var.version_text}}\n",
                    "strict": True,
                },
                "error_strategy": "fail",
            },
            {
                "step_order": 5,
                "title": "写入 JSON 报告",
                "tool": "file_write",
                "input": {
                    "path": target_path,
                    "content": "step:4.data.rendered_text",
                },
                "error_strategy": "fail",
            },
        ]

    # HTTP -> 模板渲染报告
    if (
        target_path
        and ("http" in user_input.lower())
        and ("渲染成结果文件" in user_input or "渲染成结果" in user_input or "渲染成报告" in user_input)
        and ("状态码" in user_input)
    ):
        url_match = re.search(r"(https?://[^\s'\"，。；：]+)", user_input)
        if url_match:
            url = url_match.group(1).strip()
            method = "POST" if ("post" in user_input.lower() or "提交" in user_input) else "GET"
            return [
                {
                    "step_order": 1,
                    "title": "请求接口",
                    "tool": "http_request",
                    "input": {
                        "url": url,
                        "method": method,
                        "timeout": 15,
                    },
                    "error_strategy": "fail",
                },
                {
                    "step_order": 2,
                    "title": "渲染 HTTP 报告",
                    "tool": "template_render",
                    "input": {
                        "template": "# HTTP 报告\n\nStatus Code: {{step.1.data.status_code}}\nBody: {{step.1.data.text}}\n",
                        "strict": True,
                    },
                    "error_strategy": "fail",
                },
                {
                    "step_order": 3,
                    "title": "写入 HTTP 报告",
                    "tool": "file_write",
                    "input": {
                        "path": target_path,
                        "content": "step:2.data.rendered_text",
                    },
                    "error_strategy": "fail",
                },
            ]

    # 条件 + 模板渲染报告
    if (
        src_path
        and src_path.endswith(".json")
        and target_path
        and ("如果" in user_input or "若" in user_input)
        and ("planner" in user_input)
        and ("等于 DeepSeek" in user_input or "等于DeepSeek" in user_input)
        and ("渲染成成功报告" in user_input or "渲染成功报告" in user_input)
    ):
        return [
            {
                "step_order": 1,
                "title": "读取 JSON 文件",
                "tool": "read_json",
                "input": {"path": src_path},
                "error_strategy": "fail",
            },
            {
                "step_order": 2,
                "title": "判断 planner 条件",
                "tool": "if_condition",
                "input": {
                    "left": "step:1.data.json.planner",
                    "operator": "eq",
                    "right": "DeepSeek",
                },
                "error_strategy": "fail",
            },
            {
                "step_order": 3,
                "title": "渲染成功报告",
                "tool": "template_render",
                "input": {
                    "template": "# 成功报告\n\nPlanner: {{step.1.data.json.planner}}\nVersion: {{step.1.data.json.version}}\n",
                    "strict": True,
                },
                "run_if": "step:2.data.matched",
                "error_strategy": "fail",
            },
            {
                "step_order": 4,
                "title": "写入成功报告",
                "tool": "file_write",
                "input": {
                    "path": target_path,
                    "content": "step:3.data.rendered_text",
                },
                "run_if": "step:2.data.matched",
                "error_strategy": "fail",
            },
        ]

    # JSON 条件判断：true/false 双分支写文件
    if (
        src_path
        and src_path.endswith(".json")
        and len(matches) >= 3
        and ("如果" in user_input or "若" in user_input)
        and ("planner" in user_input)
        and ("否则" in user_input)
        and ("等于" in user_input or "不等于" in user_input)
    ):
        true_path = matches[-2]
        false_path = matches[-1]
        if "不等于" in user_input:
            operator = "ne"
            right_value = user_input.split("不等于", 1)[1]
        else:
            operator = "eq"
            right_value = user_input.split("等于", 1)[1]
        right_value = re.split(r"[；;，,。\n]", right_value)[0].strip()
        right_value = re.sub(r"^(就|则|那就)?(写入|输出到?)", "", right_value).strip()
        right_value = right_value.strip("`'\"“”‘’ ")
        return [
            {"step_order": 1, "title": "读取 JSON 文件", "tool": "read_json", "input": {"path": src_path}, "error_strategy": "fail"},
            {"step_order": 2, "title": "判断 planner 条件", "tool": "if_condition", "input": {"left": "step:1.data.json.planner", "operator": operator, "right": right_value}, "error_strategy": "fail"},
            {"step_order": 3, "title": "写入条件成立结果", "tool": "file_write", "input": {"path": true_path, "content": "matched"}, "run_if": "step:2.data.matched", "error_strategy": "fail"},
            {"step_order": 4, "title": "写入条件不成立结果", "tool": "file_write", "input": {"path": false_path, "content": "not matched"}, "skip_if": "step:2.data.matched", "error_strategy": "fail"},
        ]

    # HTTP 组合条件 and 判断
    if (
        "http" in user_input.lower() and target_path
        and "状态码" in user_input and "包含" in user_input and "且" in user_input
        and "ai" in user_input.lower() and "写入" in user_input
    ):
        url_match = re.search(r"(https?://[^\s'\"，。；：]+)", user_input)
        if url_match:
            url = url_match.group(1).strip()
            code_match = re.search(r"状态码\s*等于\s*(\d+)", user_input)
            expected_code = int(code_match.group(1)) if code_match else 200
            method = "POST" if ("post" in user_input.lower() or "提交" in user_input) else "GET"
            return [
                {"step_order": 1, "title": "请求接口", "tool": "http_request", "input": {"url": url, "method": method, "timeout": 15}, "error_strategy": "fail"},
                {"step_order": 2, "title": "判断 HTTP 组合条件", "tool": "if_condition", "input": {"logic": "and", "conditions": [
                    {"left": "step:1.data.status_code", "operator": "eq", "right": expected_code},
                    {"left": "step:1.data.text", "operator": "contains", "right": "ai"}
                ]}, "error_strategy": "fail"},
                {"step_order": 3, "title": "写入组合条件成立结果", "tool": "file_write", "input": {"path": target_path, "content": "http and ok"}, "run_if": "step:2.data.matched", "error_strategy": "fail"},
            ]

    # JSON 组合条件 and 判断
    if (
        src_path and src_path.endswith(".json") and target_path
        and "存在" in user_input and "planner" in user_input and "modules" in user_input and "包含" in user_input and "worker" in user_input and "且" in user_input and "写入" in user_input
    ):
        return [
            {"step_order": 1, "title": "读取 JSON 文件", "tool": "read_json", "input": {"path": src_path}, "error_strategy": "fail"},
            {"step_order": 2, "title": "判断 JSON 组合条件", "tool": "if_condition", "input": {"logic": "and", "conditions": [
                {"left": "step:1.data.json.planner", "operator": "exists", "right": True},
                {"left": "step:1.data.json.modules", "operator": "contains", "right": "worker"}
            ]}, "error_strategy": "fail"},
            {"step_order": 3, "title": "写入组合条件成立结果", "tool": "file_write", "input": {"path": target_path, "content": "json and ok"}, "run_if": "step:2.data.matched", "error_strategy": "fail"},
        ]

    # JSON 组合条件 or 判断
    if (
        src_path and src_path.endswith(".json") and target_path
        and "planner" in user_input and ("或" in user_input or "或者" in user_input) and "写入" in user_input
    ):
        return [
            {"step_order": 1, "title": "读取 JSON 文件", "tool": "read_json", "input": {"path": src_path}, "error_strategy": "fail"},
            {"step_order": 2, "title": "判断 JSON 或条件", "tool": "if_condition", "input": {"logic": "or", "conditions": [
                {"left": "step:1.data.json.error", "operator": "exists", "right": True},
                {"left": "step:1.data.json.planner", "operator": "eq", "right": "DeepSeek"}
            ]}, "error_strategy": "fail"},
            {"step_order": 3, "title": "写入或条件成立结果", "tool": "file_write", "input": {"path": target_path, "content": "json or ok"}, "run_if": "step:2.data.matched", "error_strategy": "fail"},
        ]

    # JSON 组合条件 not 判断
    if (
        src_path and src_path.endswith(".json") and target_path
        and "不是" in user_input and "error" in user_input and "存在" in user_input and "写入" in user_input
    ):
        return [
            {"step_order": 1, "title": "读取 JSON 文件", "tool": "read_json", "input": {"path": src_path}, "error_strategy": "fail"},
            {"step_order": 2, "title": "判断 JSON 非条件", "tool": "if_condition", "input": {"logic": "not", "conditions": [
                {"left": "step:1.data.json.error", "operator": "exists", "right": True}
            ]}, "error_strategy": "fail"},
            {"step_order": 3, "title": "写入非条件成立结果", "tool": "file_write", "input": {"path": target_path, "content": "json not ok"}, "run_if": "step:2.data.matched", "error_strategy": "fail"},
        ]

    # JSON 条件判断：单分支写文件
    if (
        src_path
        and src_path.endswith(".json")
        and target_path
        and ("如果" in user_input or "若" in user_input)
        and ("planner" in user_input)
        and ("等于" in user_input or "不等于" in user_input)
        and "写入" in user_input
    ):
        if "不等于" in user_input:
            operator = "ne"
            right_value = user_input.split("不等于", 1)[1]
        else:
            operator = "eq"
            right_value = user_input.split("等于", 1)[1]
        right_value = re.split(r"[；;，,。\n]", right_value)[0].strip()
        right_value = re.sub(r"^(就|则|那就)?(写入|输出到?)", "", right_value).strip()
        right_value = right_value.strip("`'\"“”‘’ ")
        return [
            {"step_order": 1, "title": "读取 JSON 文件", "tool": "read_json", "input": {"path": src_path}, "error_strategy": "fail"},
            {"step_order": 2, "title": "判断 planner 条件", "tool": "if_condition", "input": {"left": "step:1.data.json.planner", "operator": operator, "right": right_value}, "error_strategy": "fail"},
            {"step_order": 3, "title": "写入条件成立结果", "tool": "file_write", "input": {"path": target_path, "content": "matched"}, "run_if": "step:2.data.matched", "error_strategy": "fail"},
        ]

    # HTTP 状态码条件判断：单分支写文件
    if (
        "http" in user_input.lower()
        and target_path
        and ("如果" in user_input or "若" in user_input)
        and ("状态码" in user_input)
        and ("等于" in user_input or "不等于" in user_input)
        and "写入" in user_input
    ):
        url_match = re.search(r"(https?://[^\s'\"，。；：]+)", user_input)
        if url_match:
            url = url_match.group(1).strip()
            if "不等于" in user_input:
                operator = "ne"
                code_match = re.search(r"状态码\s*不等于\s*(\d+)", user_input)
            else:
                operator = "eq"
                code_match = re.search(r"状态码\s*等于\s*(\d+)", user_input)
            expected_code = int(code_match.group(1)) if code_match else 200
            method = "POST" if ("post" in user_input.lower() or "提交" in user_input) else "GET"
            return [
                {"step_order": 1, "title": "请求接口", "tool": "http_request", "input": {"url": url, "method": method, "timeout": 15}, "error_strategy": "fail"},
                {"step_order": 2, "title": "判断状态码条件", "tool": "if_condition", "input": {"left": "step:1.data.status_code", "operator": operator, "right": expected_code}, "error_strategy": "fail"},
                {"step_order": 3, "title": "写入条件成立结果", "tool": "file_write", "input": {"path": target_path, "content": "http ok"}, "run_if": "step:2.data.matched", "error_strategy": "fail"},
            ]

    # JSON 字段存在判断
    if (
        src_path and src_path.endswith(".json") and target_path
        and "存在" in user_input and "planner" in user_input and "字段" in user_input and "写入" in user_input
    ):
        return [
            {"step_order": 1, "title": "读取 JSON 文件", "tool": "read_json", "input": {"path": src_path}, "error_strategy": "fail"},
            {"step_order": 2, "title": "判断 planner 字段是否存在", "tool": "if_condition", "input": {"left": "step:1.data.json.planner", "operator": "exists", "right": True}, "error_strategy": "fail"},
            {"step_order": 3, "title": "写入字段存在结果", "tool": "file_write", "input": {"path": target_path, "content": "planner exists"}, "run_if": "step:2.data.matched", "error_strategy": "fail"},
        ]

    # JSON 字段不存在判断
    if (
        src_path and src_path.endswith(".json") and target_path
        and "不存在" in user_input and "error" in user_input and "字段" in user_input and "写入" in user_input
    ):
        return [
            {"step_order": 1, "title": "读取 JSON 文件", "tool": "read_json", "input": {"path": src_path}, "error_strategy": "fail"},
            {"step_order": 2, "title": "判断 error 字段是否不存在", "tool": "if_condition", "input": {"left": "step:1.data.json.error", "operator": "not_exists", "right": True}, "error_strategy": "fail"},
            {"step_order": 3, "title": "写入字段不存在结果", "tool": "file_write", "input": {"path": target_path, "content": "error not exists"}, "run_if": "step:2.data.matched", "error_strategy": "fail"},
        ]

    # JSON 列表包含判断
    if (
        src_path and src_path.endswith(".json") and target_path
        and "modules" in user_input and "包含" in user_input and "worker" in user_input and "写入" in user_input
    ):
        return [
            {"step_order": 1, "title": "读取 JSON 文件", "tool": "read_json", "input": {"path": src_path}, "error_strategy": "fail"},
            {"step_order": 2, "title": "判断 modules 是否包含 worker", "tool": "if_condition", "input": {"left": "step:1.data.json.modules", "operator": "contains", "right": "worker"}, "error_strategy": "fail"},
            {"step_order": 3, "title": "写入包含结果", "tool": "file_write", "input": {"path": target_path, "content": "module worker exists"}, "run_if": "step:2.data.matched", "error_strategy": "fail"},
        ]

    # HTTP body contains 判断
    if (
        "http" in user_input.lower() and target_path
        and "包含" in user_input and "ai" in user_input.lower()
        and ("返回内容" in user_input or "响应内容" in user_input or "返回结果" in user_input)
        and "写入" in user_input
    ):
        url_match = re.search(r"(https?://[^\s'\"，。；：]+)", user_input)
        if url_match:
            url = url_match.group(1).strip()
            method = "POST" if ("post" in user_input.lower() or "提交" in user_input) else "GET"
            return [
                {"step_order": 1, "title": "请求接口", "tool": "http_request", "input": {"url": url, "method": method, "timeout": 15}, "error_strategy": "fail"},
                {"step_order": 2, "title": "判断返回内容是否包含 ai", "tool": "if_condition", "input": {"left": "step:1.data.text", "operator": "contains", "right": "ai"}, "error_strategy": "fail"},
                {"step_order": 3, "title": "写入包含结果", "tool": "file_write", "input": {"path": target_path, "content": "http contains ai"}, "run_if": "step:2.data.matched", "error_strategy": "fail"},
            ]

    # 提取 JSON 文件字段并写入文件
    if (
        src_path
        and target_path
        and src_path.endswith(".json")
        and extract_path
        and "写入" in user_input
    ):
        return [
            {
                "step_order": 1,
                "title": "读取 JSON 文件",
                "tool": "read_json",
                "input": {"path": src_path},
                "error_strategy": "fail",
            },
            {
                "step_order": 2,
                "title": "提取 JSON 字段",
                "tool": "json_extract",
                "input": {
                    "data": "step:1.data.json",
                    "path": extract_path,
                },
                "error_strategy": "fail",
            },
            {
                "step_order": 3,
                "title": "写入提取结果",
                "tool": "file_write",
                "input": {
                    "path": target_path,
                    "content": "step:2.data.value",
                },
                "error_strategy": "fail",
            },
        ]

    # HTTP POST/请求 -> 整理返回结果（避免被提取字段规则误命中）
    if (
        "http" in user_input.lower()
        and ("整理结果" in user_input or "整理返回结果" in user_input or "整理接口返回结果" in user_input)
        and ("请求" in user_input or "提交" in user_input or "post" in user_input.lower())
        and "提取" not in user_input
        and "字段" not in user_input
        and "如果" not in user_input
    ):
        url_match = re.search(r"(https?://[^\s'\"，。；：]+)", user_input)
        if url_match:
            url = url_match.group(1).strip()
            method = "POST" if ("post" in user_input.lower() or "提交" in user_input) else "GET"
            return [
                {
                    "step_order": 1,
                    "title": "请求接口",
                    "tool": "http_request",
                    "input": {
                        "url": url,
                        "method": method,
                        "timeout": 15,
                    },
                    "error_strategy": "fail",
                },
                {
                    "step_order": 2,
                    "title": "整理接口返回结果",
                    "tool": "summarize_text",
                    "input": {"text": "step:1.output"},
                    "error_strategy": "fail",
                },
            ]

    # HTTP 请求 + 提取字段 + 写入文件
    if (
        "http" in user_input.lower()
        and extract_path
        and "写入" in user_input
    ):
        url_match = re.search(r"(https?://[^\s'\"，。；：]+)", user_input)
        if url_match and target_path:
            url = url_match.group(1).strip()
            method = "POST" if ("post" in user_input.lower() or "提交" in user_input) else "GET"
            return [
                {
                    "step_order": 1,
                    "title": "请求接口",
                    "tool": "http_request",
                    "input": {
                        "url": url,
                        "method": method,
                        "timeout": 15,
                    },
                    "error_strategy": "fail",
                },
                {
                    "step_order": 2,
                    "title": "提取返回字段",
                    "tool": "json_extract",
                    "input": {
                        "data": "step:1.data.json",
                        "path": extract_path,
                    },
                    "error_strategy": "fail",
                },
                {
                    "step_order": 3,
                    "title": "写入提取结果",
                    "tool": "file_write",
                    "input": {
                        "path": target_path,
                        "content": "step:2.data.value",
                    },
                    "error_strategy": "fail",
                },
            ]

    # JSON -> JSON 写入
    if (
        src_path
        and target_path
        and src_path.endswith(".json")
        and target_path.endswith(".json")
        and (
            "写入 json 文件" in user_input
            or "写入json文件" in user_input
            or "原样写入" in user_input
            or "写入文件" in user_input
            or "保存到" in user_input
            or "另存为" in user_input
            or "复制到" in user_input
        )
    ):
        return [
            {
                "step_order": 1,
                "title": "读取 JSON 文件",
                "tool": "read_json",
                "input": {"path": src_path},
                "error_strategy": "fail",
            },
            {
                "step_order": 2,
                "title": "写入 JSON 文件",
                "tool": "write_json",
                "input": {"path": target_path, "data": "step:1.data.json"},
                "error_strategy": "fail",
            },
        ]

    # JSON 摘要
    if (
        src_path
        and src_path.endswith(".json")
        and (
            "整理要点" in user_input
            or "总结" in user_input
            or "摘要" in user_input
            or "分析" in user_input
        )
    ):
        return [
            {
                "step_order": 1,
                "title": "读取 JSON 文件",
                "tool": "read_json",
                "input": {"path": src_path},
                "error_strategy": "fail",
            },
            {
                "step_order": 2,
                "title": "整理 JSON 要点",
                "tool": "summarize_text",
                "input": {"text": "step:1.output"},
                "error_strategy": "fail",
            },
        ]

    # 文本文件读取+摘要+写入
    if src_path and target_path and "整理要点" in user_input:
        return [
            {
                "step_order": 1,
                "title": "读取文件内容",
                "tool": "file_read",
                "input": {"path": src_path},
                "error_strategy": "fail",
            },
            {
                "step_order": 2,
                "title": "整理文件要点",
                "tool": "summarize_text",
                "input": {"text": "step:1.data.content"},
                "error_strategy": "fail",
            },
            {
                "step_order": 3,
                "title": "写入摘要到文件",
                "tool": "file_write",
                "input": {
                    "path": target_path,
                    "content": "step:2.data.text",
                },
                "error_strategy": "fail",
            },
        ]

    # 普通文件复制
    if src_path and target_path:
        return [
            {
                "step_order": 1,
                "title": "读取文件内容",
                "tool": "file_read",
                "input": {"path": src_path},
                "error_strategy": "fail",
            },
            {
                "step_order": 2,
                "title": "写入文件",
                "tool": "file_write",
                "input": {
                    "path": target_path,
                    "content": "step:1.data.content",
                },
                "error_strategy": "fail",
            },
        ]

    # 执行命令
    if "执行命令" in user_input:
        command_match = re.search(r"[`‘“\"]([^`’”\"]+)[`’”\"]", user_input)
        if command_match:
            cmd = command_match.group(1).strip()
            return [
                {
                    "step_order": 1,
                    "title": "执行命令",
                    "tool": "shell_exec",
                    "input": {"command": cmd},
                    "error_strategy": "fail",
                },
                {
                    "step_order": 2,
                    "title": "整理输出内容",
                    "tool": "summarize_text",
                    "input": {"text": "step:1.data.stdout_text"},
                    "error_strategy": "fail",
                },
            ]

    # 普通 HTTP 请求
    if "http" in user_input and ("请求" in user_input or "接口" in user_input or "api" in user_input.lower()):
        url_match = re.search(r"(https?://[^\s'\"，。；：]+)", user_input)
        if url_match:
            url = url_match.group(1).strip()
            method = "POST" if ("post" in user_input.lower() or "提交" in user_input) else "GET"
            return [
                {
                    "step_order": 1,
                    "title": "请求接口",
                    "tool": "http_request",
                    "input": {
                        "url": url,
                        "method": method,
                        "timeout": 15,
                    },
                    "error_strategy": "fail",
                },
                {
                    "step_order": 2,
                    "title": "整理接口返回结果",
                    "tool": "summarize_text",
                    "input": {"text": "step:1.output"},
                    "error_strategy": "fail",
                },
            ]

    return []

def call_deepseek_planner(
    user_input: str,
    *,
    model_route_overrides: dict[str, dict[str, Any]] | None = None,
) -> list[dict] | list[str]:
    route = get_model_route_config("planner", route_overrides=model_route_overrides)
    client = get_model_provider_client(str(route["provider"]))
    system_prompt = """
你是一个任务规划器。
你必须优先返回结构化 JSON 协议，不要输出解释文字。

返回格式必须是以下两种之一：

1. 推荐格式（结构化协议）：
{
  "steps": [
    {
      "step_order": 1,
      "title": "步骤标题",
      "tool": "file_read",
      "input": {"path": "/workspace/test.txt"},
      "error_strategy": "fail"
    }
  ]
}

2. 兼容格式（仅当你实在无法结构化时）：
{
  "steps": ["步骤1", "步骤2", "步骤3"]
}

支持工具只有：
- file_read
- file_write
- list_dir
- shell_exec
- generate_text
- summarize_text
- web_search
- read_json
- write_json
- http_request
- json_extract
- if_condition
- set_var
- template_render

规则：
- 读取文本文件用 file_read
- 写文本文件用 file_write
- 列目录用 list_dir
- 执行命令用 shell_exec
- 生成最终成品文本用 generate_text
- 整理总结文本用 summarize_text
- 网络搜索用 web_search
- 读取 JSON 文件用 read_json
- 写 JSON 文件用 write_json
- 请求 HTTP 接口用 http_request
- 从 JSON 对象中提取字段用 json_extract
- 条件判断用 if_condition
- 保存变量用 set_var
- 模板渲染用 template_render

http_request.input 只允许这些字段：
- url
- method
- params
- json
- timeout

如果是 POST 提交 JSON 数据，必须使用 json 字段。
绝对不要使用 data 字段。
http_request.timeout 必须是 1 到 20 之间的整数，如无必要统一使用 15。

json_extract.input 只允许这些字段：
- data
- path

json_extract.path 使用点路径格式，例如：
- planner
- modules.0
- args.q

web_search.input 只允许这些字段：
- query

web_search 必须使用 query 字段。
绝对不要使用 q 字段。

generate_text.input 只允许这些字段：
- prompt
- system_prompt

if_condition.input 支持两种格式：
- 单条件：left / operator / right
- 组合条件：logic / conditions

if_condition.logic 只支持：
- and
- or
- not

if_condition.conditions 是条件数组，数组里的每一项都必须是 left / operator / right。

if_condition.operator 只支持：
- eq
- ne
- gt
- lt
- gte
- lte
- contains
- exists
- not_exists

步骤可选控制字段：
- run_if
- skip_if

run_if / skip_if 使用布尔引用，例如：
- step:2.data.matched

set_var.input 只允许这些字段：
- name
- value

变量引用规则：
- 可使用 var:name 引用变量值

template_render.input 只允许这些字段：
- template
- strict

template_render 模板占位符只支持：
- {{step.N.data.xxx}}
- {{step.N.output}}
- {{var.name}}

引用规则：
- 可以在后续 step.input 中引用前面步骤输出
- 引用格式为：step:N.data.xxx
- 文本摘要常用：step:N.data.content 或 step:N.data.text
- JSON 常用：step:N.data.json
- HTTP 返回常用：step:N.data.json / step:N.data.text / step:N.data.status_code
- json_extract 结果常用：step:N.data.value
- web_search 结果只允许引用：
  - step:N.data.text
  - step:N.data.query
  - step:N.output
- 不允许把 web_search 输出当成 JSON 继续引用
- 不允许出现 step:N.data.json 或 step:N.data.results.* 指向 web_search 步骤

强约束：
- 只返回 JSON
- 不要 Markdown
- 不要代码块
- 不要额外解释
"""

    prompt_text = f"[system]\n{system_prompt}\n\n[user]\n{user_input}"
    content = ""
    try:
        completion = client.chat.completions.create(
            model=str(route["model_name"]),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input},
            ],
            response_format={"type": "json_object"},
            temperature=float(route["temperature"]),
            max_tokens=int(route["max_tokens"]),
        )

        content = (completion.choices[0].message.content or "").strip()
        if not content:
            raise ValueError("DeepSeek 返回空内容")
        record_model_trace(
            route_name="planner",
            provider=str(route["provider"]),
            model_name=str(route["model_name"]),
            prompt_version=STEP_REQUEST_PROTOCOL_VERSION,
            prompt_text=prompt_text,
            response_text=content,
            status="completed",
            metadata=serialize_model_route_runtime_info("planner", route),
        )
    except Exception as exc:
        record_model_trace(
            route_name="planner",
            provider=str(route["provider"]),
            model_name=str(route["model_name"]),
            prompt_version=STEP_REQUEST_PROTOCOL_VERSION,
            prompt_text=prompt_text,
            response_text=content,
            status="failed",
            error_summary=str(exc),
            metadata=serialize_model_route_runtime_info("planner", route),
        )
        raise

    data = json.loads(content)
    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("planner 返回 steps 非法")

    if all(isinstance(x, str) for x in steps):
        return [normalize_step_name(x) for x in steps if str(x).strip()]

    normalized = []
    for i, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            continue
        normalized.append(
            {
                "step_order": int(step.get("step_order") or i),
                "title": str(step.get("title") or f"步骤 {i}"),
                "tool": str(step.get("tool") or "").strip(),
                "input": step.get("input") or {},
                "run_if": step.get("run_if"),
                "skip_if": step.get("skip_if"),
                "max_retries": int(step.get("max_retries") or default_max_retries_for_tool(str(step.get("tool") or "").strip())),
                "error_strategy": str(step.get("error_strategy") or "fail"),
            }
        )

    if not normalized:
        raise ValueError("planner 返回的结构化步骤为空")

    return validate_planned_steps(normalized)


def call_planner_with_retries(
    user_input: str,
    attempts: int = 2,
    *,
    model_route_overrides: dict[str, dict[str, Any]] | None = None,
) -> list[dict] | list[str]:
    last_error = None
    for _ in range(attempts):
        try:
            return call_deepseek_planner(user_input, model_route_overrides=model_route_overrides)
        except Exception as e:
            last_error = e
            time.sleep(1)
    raise RuntimeError(f"planner failed after {attempts} attempts: {last_error}")


def resolve_task_plan_source(
    user_input: str,
    *,
    model_route_overrides: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict] | list[str], str]:
    inferred = infer_structured_steps_from_user_input(user_input)
    if inferred:
        return inferred, "inference"

    try:
        return call_planner_with_retries(user_input, model_route_overrides=model_route_overrides), "model"
    except Exception as e:
        logger.warning("planner fallback due to: %s", e)
        return fallback_legacy_steps(user_input), "fallback_legacy"


def plan_task(
    user_input: str,
    *,
    model_route_overrides: dict[str, dict[str, Any]] | None = None,
) -> list[dict] | list[str]:
    planned, _source = resolve_task_plan_source(user_input, model_route_overrides=model_route_overrides)
    return planned


# =========================
# Tool implementations
# =========================
def tool_file_read(path_str: str) -> dict:
    try:
        path = ensure_readable_file(path_str)
        content = path.read_text(encoding="utf-8")
        output_text = f"file_read 结果（{path_str}）：\n{content}"
        return {
            "ok": True,
            "output_text": output_text,
            "output_data": {
                "path": path_str,
                "content": output_text,
                "raw_text": content,
            },
            "error": "",
        }
    except Exception as e:
        return {
            "ok": False,
            "output_text": f"file_read 执行失败：{e}",
            "output_data": None,
            "error": f"file_read 执行失败：{e}",
        }


def tool_file_write(path_str: str, content: str) -> dict:
    try:
        path = ensure_writable_file(path_str)
        path.write_text(content, encoding="utf-8")
        output_text = f"file_write 成功：已写入文件 -> {path_str}"
        return {
            "ok": True,
            "output_text": output_text,
            "output_data": {"path": path_str},
            "error": "",
        }
    except Exception as e:
        return {
            "ok": False,
            "output_text": f"file_write 执行失败：{e}",
            "output_data": None,
            "error": f"file_write 执行失败：{e}",
        }


def tool_list_dir(path_str: str) -> dict:
    try:
        path = ensure_readable_dir(path_str)
        items = []
        for p in sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            prefix = "[DIR]" if p.is_dir() else "[FILE]"
            items.append(f"{prefix} {p.name}")

        output_text = f"list_dir 结果（{path_str}）：\n" + "\n".join(items)
        return {
            "ok": True,
            "output_text": output_text,
            "output_data": {
                "path": path_str,
                "entries": items,
            },
            "error": "",
        }
    except Exception as e:
        return {
            "ok": False,
            "output_text": f"list_dir 执行失败：{e}",
            "output_data": None,
            "error": f"list_dir 执行失败：{e}",
        }


def validate_shell_command(command: str):
    stripped = command.strip()
    if not stripped:
        raise ValueError("缺少命令")

    tokens = shlex.split(stripped)
    if not tokens:
        raise ValueError("命令解析失败")

    first = tokens[0]
    if first not in SAFE_COMMANDS:
        raise ValueError(f"命令不在白名单中 -> {first}")

    for token in tokens:
        if token in DISALLOWED_TOKENS:
            raise ValueError(f"命令包含禁用词 -> {token}")

    return tokens


def tool_shell_exec(command: str) -> dict:
    try:
        validate_shell_command(command)

        completed = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=str(WORKSPACE_DIR),
            timeout=15,
        )

        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
        rc = completed.returncode

        output_text = (
            f"shell_exec 命令：{command}\n"
            f"退出码：{rc}\n"
            f"标准输出：\n{stdout if stdout else '(空)'}"
        )

        if stderr:
            output_text += f"\n标准错误：\n{stderr}"

        return {
            "ok": rc == 0,
            "output_text": output_text,
            "output_data": {
                "command": command,
                "returncode": rc,
                "stdout": stdout,
                "stderr": stderr,
                "stdout_text": output_text,
            },
            "error": "" if rc == 0 else f"shell_exec 执行失败：退出码 {rc}",
        }
    except Exception as e:
        return {
            "ok": False,
            "output_text": f"shell_exec 执行失败：{e}",
            "output_data": None,
            "error": f"shell_exec 执行失败：{e}",
        }


def tool_summarize_text(
    text: str,
    model_route_overrides: dict[str, dict[str, Any]] | None = None,
) -> dict:
    route_info: dict[str, Any] = {}
    try:
        route = get_model_route_config("summarize_text", route_overrides=model_route_overrides)
        route_info = serialize_model_route_runtime_info("summarize_text", route)
        client = get_model_provider_client(str(route["provider"]))
        prompt = (
            "请将下面内容整理为简明中文摘要。\n"
            "要求：\n"
            "1. 标题固定为“摘要结果：”\n"
            "2. 输出 3 到 6 条 bullet\n"
            "3. 优先提炼关键步骤、编号项、结论\n"
            "4. 不要编造\n\n"
            f"{text}"
        )

        prompt_version = "summarize_text-v1"
        completion = client.chat.completions.create(
            model=str(route["model_name"]),
            messages=[
                {"role": "system", "content": "你是一个文本整理助手。"},
                {"role": "user", "content": prompt},
            ],
            temperature=float(route["temperature"]),
            max_tokens=int(route["max_tokens"]),
        )
        summary = (completion.choices[0].message.content or "").strip()
        if not summary:
            raise ValueError("DeepSeek 返回空内容")
        record_model_trace(
            route_name="summarize_text",
            provider=str(route["provider"]),
            model_name=str(route["model_name"]),
            prompt_version=prompt_version,
            prompt_text=prompt,
            response_text=summary,
            status="completed",
            metadata=route_info,
        )

        return {
            "ok": True,
            "output_text": summary,
            "output_data": {
                "text": summary,
                "model_route": route_info,
                "summary_backend": "model",
            },
            "error": "",
        }

    except Exception as exc:
        if route_info:
            record_model_trace(
                route_name="summarize_text",
                provider=str(route_info.get("provider") or ""),
                model_name=str(route_info.get("model_name") or ""),
                prompt_version="summarize_text-v1",
                prompt_text=text,
                status="failed",
                error_summary=str(exc),
                metadata=route_info,
            )
        raw = text or ""

        cleaned_lines = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue

            # 去掉工具输出头
            if line.startswith("file_read 结果（"):
                continue
            if line.startswith("shell_exec 命令："):
                continue
            if line.startswith("退出码："):
                continue
            if line.startswith("标准输出："):
                continue
            if line.startswith("标准错误："):
                continue
            if line.startswith("http_request 成功："):
                continue
            if line.startswith("状态码："):
                continue
            if line.startswith("Content-Type："):
                continue
            if line.startswith("响应预览："):
                continue
            if line.startswith("read_json 成功："):
                continue
            if line.startswith("JSON 类型："):
                continue

            cleaned_lines.append(line)

        bullets = []

        # 1. 优先提取编号项
        numbered = [x for x in cleaned_lines if re.match(r"^\d+\.", x)]
        if numbered:
            bullets.extend(numbered[:5])

        # 2. 提取常见关键句
        if len(bullets) < 4:
            for line in cleaned_lines:
                if any(k in line for k in ["DeepSeek", "planner", "web_search", "file_read", "worker", "postgres", "api"]):
                    if line not in bullets:
                        bullets.append(line)
                if len(bullets) >= 5:
                    break

        # 3. 不够再补前几条普通句子
        if len(bullets) < 4:
            for line in cleaned_lines:
                if line not in bullets:
                    bullets.append(line)
                if len(bullets) >= 5:
                    break

        if not bullets:
            bullets = ["未识别到可摘要内容。"]

        summary = "摘要结果：\n" + "\n".join(f"- {x}" for x in bullets[:5])

        return {
            "ok": True,
            "output_text": summary,
            "output_data": {
                "text": summary,
                "model_route": route_info,
                "summary_backend": "fallback_heuristic",
            },
            "error": "",
        }


def tool_generate_text(
    prompt: str,
    *,
    system_prompt: str = "",
    model_route_overrides: dict[str, dict[str, Any]] | None = None,
) -> dict:
    route_info: dict[str, Any] = {}
    effective_system_prompt = (
        system_prompt.strip()
        or "你是一个交付导向的中文助手。请直接输出可直接使用的最终成品，不要解释思考过程。"
    )
    try:
        route = get_model_route_config("generate_text", route_overrides=model_route_overrides)
        route_info = serialize_model_route_runtime_info("generate_text", route)
        client = get_model_provider_client(str(route["provider"]))
        completion = client.chat.completions.create(
            model=str(route["model_name"]),
            messages=[
                {"role": "system", "content": effective_system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=float(route["temperature"]),
            max_tokens=int(route["max_tokens"]),
        )
        generated = (completion.choices[0].message.content or "").strip()
        if not generated:
            raise ValueError("DeepSeek 返回空内容")
        record_model_trace(
            route_name="generate_text",
            provider=str(route["provider"]),
            model_name=str(route["model_name"]),
            prompt_version="generate_text-v1",
            prompt_text=prompt,
            response_text=generated,
            status="completed",
            metadata=route_info,
        )
        return {
            "ok": True,
            "output_text": generated,
            "output_data": {
                "text": generated,
                "model_route": route_info,
                "generation_backend": "model",
            },
            "error": "",
        }
    except Exception as exc:
        if route_info:
            record_model_trace(
                route_name="generate_text",
                provider=str(route_info.get("provider") or ""),
                model_name=str(route_info.get("model_name") or ""),
                prompt_version="generate_text-v1",
                prompt_text=prompt,
                status="failed",
                error_summary=str(exc),
                metadata=route_info,
            )
        return {
            "ok": False,
            "output_text": f"generate_text 执行失败：{exc}",
            "output_data": None,
            "error": f"generate_text 执行失败：{exc}",
        }


def dedupe_search_results(results: list[dict]) -> list[dict]:
    seen = set()
    deduped = []

    for item in results:
        url = (item.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        deduped.append(item)
    return deduped


def summarize_search_results(
    query: str,
    results: list[dict],
    model_route_overrides: dict[str, dict[str, Any]] | None = None,
) -> tuple[str, dict[str, Any]]:
    if not results:
        return f"未找到可摘要的搜索结果。查询词：{query}", {
            "summary_backend": "no_results",
            "summary_model_route": {},
        }

    simplified_results = []
    for item in results[:5]:
        simplified_results.append(
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "content": (item.get("content", "") or "")[:300],
            }
        )

    route_info: dict[str, Any] = {}
    try:
        route = get_model_route_config("web_search_summary", route_overrides=model_route_overrides)
        route_info = serialize_model_route_runtime_info("web_search_summary", route)
        client = get_model_provider_client(str(route["provider"]))
        prompt_version = "web_search_summary-v1"
        request_payload = json.dumps(
            {"query": query, "results": simplified_results},
            ensure_ascii=False,
        )
        completion = client.chat.completions.create(
            model=str(route["model_name"]),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是一个搜索结果整理助手。"
                        "请根据给定搜索结果输出简明中文摘要。"
                        "先输出“### 结论摘要”，再输出“### 关键来源”。"
                    ),
                },
                {
                    "role": "user",
                    "content": request_payload,
                },
            ],
            temperature=float(route["temperature"]),
            max_tokens=int(route["max_tokens"]),
        )
        text = (completion.choices[0].message.content or "").strip()
        if text:
            record_model_trace(
                route_name="web_search_summary",
                provider=str(route["provider"]),
                model_name=str(route["model_name"]),
                prompt_version=prompt_version,
                prompt_text=request_payload,
                response_text=text,
                status="completed",
                metadata=route_info,
            )
            return text, {
                "summary_backend": "model",
                "summary_model_route": route_info,
            }
    except Exception as exc:
        if route_info:
            record_model_trace(
                route_name="web_search_summary",
                provider=str(route_info.get("provider") or ""),
                model_name=str(route_info.get("model_name") or ""),
                prompt_version="web_search_summary-v1",
                prompt_text=query,
                status="failed",
                error_summary=str(exc),
                metadata=route_info,
            )

    lines = ["### 结论摘要"]
    lines.append(f"- 针对查询“{query}”获取到 {len(results[:5])} 条候选结果。")
    lines.append("")
    lines.append("### 关键来源")
    for item in results[:5]:
        lines.append(f"- {item.get('title', '')}")
        lines.append(f"  {item.get('url', '')}")
    return "\n".join(lines), {
        "summary_backend": "fallback_heuristic",
        "summary_model_route": route_info,
    }


def web_search_duckduckgo(
    query: str,
    model_route_overrides: dict[str, dict[str, Any]] | None = None,
) -> tuple[str, dict[str, Any]]:
    url = "https://html.duckduckgo.com/html/"
    headers = {"User-Agent": "Mozilla/5.0"}

    resp = requests.post(
        url,
        data={"q": query},
        headers=headers,
        timeout=8,
    )
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    parsed_results = []

    for a in soup.select(".result__title a")[:8]:
        title = a.get_text(" ", strip=True)
        href = a.get("href", "")
        if title and href:
            parsed_results.append(
                {
                    "title": title,
                    "url": href,
                    "content": "",
                }
            )

    parsed_results = dedupe_search_results(parsed_results)[:5]

    if not parsed_results:
        return f"web_search 已执行，但没有找到明显结果。查询词：{query}", {
            "search_provider": "duckduckgo",
            "result_count": 0,
            "summary_backend": "no_results",
            "summary_model_route": {},
        }

    summary, summary_metadata = summarize_search_results(
        query,
        parsed_results,
        model_route_overrides=model_route_overrides,
    )

    raw_refs = []
    for item in parsed_results:
        raw_refs.append(f"- {item['title']}\n  {item['url']}")

    return (
        "web_search 结果（DuckDuckGo）\n\n"
        f"{summary}\n\n"
        "原始来源：\n" + "\n".join(raw_refs)
    ), {
        "search_provider": "duckduckgo",
        "result_count": len(parsed_results),
        **summary_metadata,
    }


def web_search_tavily(
    query: str,
    model_route_overrides: dict[str, dict[str, Any]] | None = None,
) -> tuple[str, dict[str, Any]]:
    if not TAVILY_API_KEY:
        raise ValueError("DuckDuckGo 不可用，且缺少 TAVILY_API_KEY")

    url = "https://api.tavily.com/search"
    headers = {"Content-Type": "application/json"}
    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "search_depth": "basic",
        "max_results": 8,
        "include_answer": False,
        "include_raw_content": False,
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    parsed_results = []
    for item in data.get("results", []):
        parsed_results.append(
            {
                "title": (item.get("title") or "").strip(),
                "url": (item.get("url") or "").strip(),
                "content": (item.get("content") or "").strip(),
            }
        )

    parsed_results = dedupe_search_results(parsed_results)[:5]

    if not parsed_results:
        return f"web_search 已执行，但没有找到明显结果。查询词：{query}", {
            "search_provider": "tavily",
            "result_count": 0,
            "summary_backend": "no_results",
            "summary_model_route": {},
        }

    summary, summary_metadata = summarize_search_results(
        query,
        parsed_results,
        model_route_overrides=model_route_overrides,
    )

    raw_refs = []
    for item in parsed_results:
        block = [f"- {item['title']}", f"  {item['url']}"]
        if item["content"]:
            block.append(f"  摘要片段：{item['content'][:180]}")
        raw_refs.append("\n".join(block))

    return (
        "web_search 结果（Tavily）\n\n"
        f"{summary}\n\n"
        "原始来源：\n" + "\n".join(raw_refs)
    ), {
        "search_provider": "tavily",
        "result_count": len(parsed_results),
        **summary_metadata,
    }


def tool_web_search(
    query: str,
    model_route_overrides: dict[str, dict[str, Any]] | None = None,
) -> dict:
    try:
        try:
            text, search_metadata = web_search_duckduckgo(
                query,
                model_route_overrides=model_route_overrides,
            )
        except Exception:
            text, search_metadata = web_search_tavily(
                query,
                model_route_overrides=model_route_overrides,
            )

        return {
            "ok": True,
            "output_text": text,
            "output_data": {
                "query": query,
                "text": text,
                **search_metadata,
            },
            "error": "",
        }
    except Exception as e:
        msg = f"web_search 执行失败：{e}"
        return {
            "ok": False,
            "output_text": msg,
            "output_data": None,
            "error": msg,
        }


def tool_read_json(path_str: str) -> dict:
    try:
        path = ensure_readable_file(path_str)
        raw_text = path.read_text(encoding="utf-8")
        parsed = json.loads(raw_text)

        output_text = (
            f"read_json 成功：已读取 JSON 文件 -> {path_str}\n"
            f"JSON 类型：{'object' if isinstance(parsed, dict) else 'array' if isinstance(parsed, list) else type(parsed).__name__}"
        )

        return {
            "ok": True,
            "output_text": output_text,
            "output_data": {
                "path": path_str,
                "json": parsed,
                "raw_text": raw_text,
            },
            "error": "",
        }
    except Exception as e:
        msg = f"read_json 执行失败：{e}"
        return {
            "ok": False,
            "output_text": msg,
            "output_data": None,
            "error": msg,
        }


def tool_write_json(path_str: str, data: Any) -> dict:
    try:
        path = ensure_writable_file(path_str)
        text = json.dumps(data, ensure_ascii=False, indent=2)
        path.write_text(text, encoding="utf-8")

        output_text = f"write_json 成功：已写入 JSON 文件 -> {path_str}"
        return {
            "ok": True,
            "output_text": output_text,
            "output_data": {"path": path_str},
            "error": "",
        }
    except Exception as e:
        msg = f"write_json 执行失败：{e}"
        return {
            "ok": False,
            "output_text": msg,
            "output_data": None,
            "error": msg,
        }


def tool_json_extract(data: Any, path: str) -> dict:
    try:
        value = get_nested_value(data, path)

        if isinstance(value, (dict, list)):
            preview = json.dumps(value, ensure_ascii=False)
        else:
            preview = str(value)

        output_text = f"json_extract 成功：path={path}\n提取结果：{preview}"

        return {
            "ok": True,
            "output_text": output_text,
            "output_data": {
                "path": path,
                "value": value,
            },
            "error": "",
        }
    except Exception as e:
        msg = f"json_extract 执行失败：{e}"
        return {
            "ok": False,
            "output_text": msg,
            "output_data": None,
            "error": msg,
        }


def _normalize_mcp_tool_result(tool_name: str, response_data: Any) -> dict:
    if isinstance(response_data, dict):
        ok = bool(response_data.get("ok", True))
        output_text = str(
            response_data.get("output_text")
            or response_data.get("text")
            or response_data.get("content")
            or ""
        )
        output_data = response_data.get("output_data")
        if output_data is None:
            output_data = response_data.get("data")
        error_text = str(response_data.get("error") or "")
        if not output_text:
            output_text = safe_json_dumps(response_data)
        return {
            "ok": ok,
            "output_text": output_text,
            "output_data": output_data,
            "error": error_text if not ok else "",
        }

    if isinstance(response_data, str):
        return {
            "ok": True,
            "output_text": response_data,
            "output_data": {"text": response_data},
            "error": "",
        }

    return {
        "ok": True,
        "output_text": safe_json_dumps(response_data),
        "output_data": response_data,
        "error": "",
    }


def execute_mcp_tool(tool_name: str, payload: dict, registry_entry: dict[str, Any]) -> dict:
    provider_type = str(registry_entry.get("provider_type") or "").strip().lower()
    provider_config = registry_entry.get("provider_config") or {}
    timeout_seconds = int(provider_config.get("timeout") or 15)
    request_payload = {
        "tool_name": tool_name,
        "arguments": payload,
        "server_name": str(registry_entry.get("server_name") or ""),
    }

    try:
        if provider_type == "mcp_stdio":
            command = provider_config.get("command")
            if isinstance(command, str):
                command = shlex.split(command)
            if not isinstance(command, list) or not command or not all(isinstance(item, str) and item.strip() for item in command):
                raise ValueError(f"{tool_name} 的 mcp_stdio command 非法")

            env = os.environ.copy()
            extra_env = provider_config.get("env") or {}
            if isinstance(extra_env, dict):
                env.update({str(key): str(value) for key, value in extra_env.items()})

            proc = subprocess.run(
                command,
                input=safe_json_dumps(request_payload),
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                env=env,
            )
            if proc.returncode != 0:
                stderr = (proc.stderr or proc.stdout or "").strip()
                raise RuntimeError(stderr or f"mcp_stdio exited with code {proc.returncode}")
            response_text = (proc.stdout or "").strip()
            if not response_text:
                raise RuntimeError("mcp_stdio returned empty stdout")
            try:
                response_data = json.loads(response_text)
            except Exception:
                response_data = {"ok": True, "output_text": response_text, "output_data": {"raw_stdout": response_text}}
            return _normalize_mcp_tool_result(tool_name, response_data)

        if provider_type == "mcp_http":
            url = str(provider_config.get("url") or "").strip()
            if not url:
                raise ValueError(f"{tool_name} 的 mcp_http url 不能为空")
            method = str(provider_config.get("method") or "POST").upper().strip()
            headers = provider_config.get("headers") if isinstance(provider_config.get("headers"), dict) else {}
            if method == "GET":
                response = requests.get(url, params=request_payload, headers=headers, timeout=timeout_seconds)
            else:
                response = requests.post(url, json=request_payload, headers=headers, timeout=timeout_seconds)
            response.raise_for_status()
            content_type = str(response.headers.get("Content-Type") or "").lower()
            if "application/json" in content_type:
                response_data = response.json()
            else:
                response_data = {"ok": True, "output_text": response.text, "output_data": {"text": response.text}}
            return _normalize_mcp_tool_result(tool_name, response_data)

        raise ValueError(f"不支持的 MCP provider_type: {provider_type or '(empty)'}")
    except Exception as exc:
        message = f"{tool_name} MCP 执行失败：{exc}"
        return {
            "ok": False,
            "output_text": message,
            "output_data": None,
            "error": message,
        }


# =========================
# HTTP helpers / SSRF protection
# =========================
def is_private_ip(ip_str: str) -> bool:
    ip = ipaddress.ip_address(ip_str)
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def resolve_hostname_ips(hostname: str) -> list[str]:
    ips = []
    try:
        infos = socket.getaddrinfo(hostname, None)
        for info in infos:
            sockaddr = info[4]
            if sockaddr:
                ip = sockaddr[0]
                if ip not in ips:
                    ips.append(ip)
    except Exception:
        pass
    return ips


def validate_http_url(url: str):
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"不支持的 URL 协议 -> {parsed.scheme}")

    if not parsed.netloc:
        raise ValueError("URL 非法，缺少 host")

    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        raise ValueError("URL 非法，缺少 hostname")

    blocked_hosts = {
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "::1",
        "postgres",
        "api",
        "worker",
        "web",
    }
    if hostname in blocked_hosts:
        raise ValueError(f"禁止访问内网或本机地址 -> {hostname}")

    try:
        ip = ipaddress.ip_address(hostname)
        if is_private_ip(str(ip)):
            raise ValueError(f"禁止访问内网或本机地址 -> {hostname}")
    except ValueError:
        pass

    ips = resolve_hostname_ips(hostname)
    if not ips:
        raise ValueError(f"无法解析域名 -> {hostname}")

    for ip_str in ips:
        if is_private_ip(ip_str):
            raise ValueError(f"禁止访问内网或本机地址 -> {hostname} -> {ip_str}")


def tool_http_request(
    url: str,
    method: str,
    params: Optional[dict] = None,
    json_body: Optional[dict] = None,
    timeout: int = 15,
) -> dict:
    try:
        validate_http_url(url)

        method = method.upper().strip()
        if method not in {"GET", "POST"}:
            raise ValueError(f"不支持的 method -> {method}")

        if timeout <= 0 or timeout > 20:
            raise ValueError("timeout 必须在 1 到 20 秒之间")

        headers = {
            "User-Agent": "AI-Assistant-Worker/1.0"
        }

        if method == "GET":
            resp = requests.get(
                url,
                params=params or {},
                headers=headers,
                timeout=timeout,
                allow_redirects=True,
            )
        else:
            resp = requests.post(
                url,
                json=json_body or {},
                headers=headers,
                timeout=timeout,
                allow_redirects=True,
            )

        content_type = resp.headers.get("Content-Type", "")
        text = resp.text[:5000]

        parsed_json = None
        if "application/json" in content_type.lower():
            try:
                parsed_json = resp.json()
            except Exception:
                parsed_json = None

        preview = text[:1000]
        output_text = (
            f"http_request 成功：{method} {resp.url}\n"
            f"状态码：{resp.status_code}\n"
            f"Content-Type：{content_type}\n"
            f"响应预览：\n{preview if preview else '(空)'}"
        )

        return {
            "ok": True,
            "output_text": output_text,
            "output_data": {
                "url": str(resp.url),
                "method": method,
                "status_code": resp.status_code,
                "content_type": content_type,
                "text": text,
                "json": parsed_json,
            },
            "error": "",
        }

    except Exception as e:
        msg = f"http_request 执行失败：{e}"
        return {
            "ok": False,
            "output_text": msg,
            "output_data": None,
            "error": msg,
        }


def evaluate_single_condition_payload(payload: dict) -> dict:
    operator = payload["operator"]
    left = payload.get("left")
    right = payload.get("right")
    matched = compare_values(left, operator, right)
    return {
        "matched": matched,
        "left": left,
        "operator": operator,
        "right": right,
    }


def tool_set_var(name: str, value: Any) -> dict:
    output_text = f"set_var 成功：{name}={value}"
    return {
        "ok": True,
        "output_text": output_text,
        "output_data": {
            "name": name,
            "value": value,
        },
        "error": "",
    }


def tool_template_render(template: str, step_context: dict[int, dict], var_context: Optional[dict[str, Any]] = None, strict: bool = True) -> dict:
    try:
        rendered = render_template_text(template, step_context, var_context, strict)
        return {
            "ok": True,
            "output_text": f"template_render 成功：已渲染模板，长度={len(rendered)}",
            "output_data": {
                "rendered_text": rendered,
            },
            "error": "",
        }
    except Exception as e:
        msg = f"template_render 执行失败：{e}"
        return {
            "ok": False,
            "output_text": msg,
            "output_data": None,
            "error": msg,
        }


def build_group_output_text(logic: str, matched: bool, results: list[dict]) -> str:
    detail_parts = []
    for idx, result in enumerate(results, start=1):
        detail_parts.append(
            f"{idx}:{'true' if result['matched'] else 'false'}({result['operator']})"
        )
    details = ",".join(detail_parts)
    return (
        f"if_condition 成功：logic={logic} "
        f"result={'true' if matched else 'false'} "
        f"details=[{details}]"
    )


def tool_if_condition_group(logic: str, conditions: list[dict]) -> dict:
    try:
        if logic not in SUPPORTED_LOGICS:
            raise ValueError(f"不支持的 logic: {logic}")
        if not isinstance(conditions, list) or not conditions:
            raise ValueError("conditions 必须是非空数组")
        if logic == "not" and len(conditions) != 1:
            raise ValueError("logic=not 时 conditions 必须只有 1 条")

        results = [evaluate_single_condition_payload(cond) for cond in conditions]

        if logic == "and":
            matched = all(item["matched"] for item in results)
        elif logic == "or":
            matched = any(item["matched"] for item in results)
        elif logic == "not":
            matched = not results[0]["matched"]
        else:
            raise ValueError(f"不支持的 logic: {logic}")

        return {
            "ok": True,
            "output_text": build_group_output_text(logic, matched, results),
            "output_data": {
                "matched": matched,
                "logic": logic,
                "results": results,
            },
            "error": "",
        }
    except Exception as e:
        msg = f"if_condition 执行失败：{e}"
        return {
            "ok": False,
            "output_text": msg,
            "output_data": None,
            "error": msg,
        }


def tool_if_condition(left: Any = None, operator: Optional[str] = None, right: Any = None, logic: Optional[str] = None, conditions: Optional[list[dict]] = None) -> dict:
    if logic is not None or conditions is not None:
        return tool_if_condition_group(logic=logic or "", conditions=conditions or [])

    try:
        if operator not in SUPPORTED_OPERATORS:
            raise ValueError(f"不支持的 operator: {operator}")

        matched = compare_values(left, operator, right)
        output_text = (
            f"if_condition 成功：left={left} "
            f"operator={operator} right={right} "
            f"result={'true' if matched else 'false'}"
        )

        return {
            "ok": True,
            "output_text": output_text,
            "output_data": {
                "matched": matched,
                "left": left,
                "operator": operator,
                "right": right,
            },
            "error": "",
        }
    except Exception as e:
        msg = f"if_condition 执行失败：{e}"
        return {
            "ok": False,
            "output_text": msg,
            "output_data": None,
            "error": msg,
        }


def execute_tool(
    tool_name: str,
    payload: dict,
    step_context: Optional[dict[int, dict]] = None,
    var_context: Optional[dict[str, Any]] = None,
    model_route_overrides: dict[str, dict[str, Any]] | None = None,
) -> dict:
    registry_entry = get_tool_registry_entry(tool_name)
    if registry_entry and str(registry_entry.get("provider_type") or "builtin").strip().lower() in {"mcp_stdio", "mcp_http"}:
        return execute_mcp_tool(tool_name, payload, registry_entry)
    if tool_name == "file_read":
        return tool_file_read(payload["path"])
    if tool_name == "file_write":
        return tool_file_write(payload["path"], payload["content"])
    if tool_name == "list_dir":
        return tool_list_dir(payload["path"])
    if tool_name == "shell_exec":
        return tool_shell_exec(payload["command"])
    if tool_name == "generate_text":
        return tool_generate_text(
            payload["prompt"],
            system_prompt=str(payload.get("system_prompt") or ""),
            model_route_overrides=model_route_overrides,
        )
    if tool_name == "summarize_text":
        return tool_summarize_text(
            payload["text"],
            model_route_overrides=model_route_overrides,
        )
    if tool_name == "web_search":
        return tool_web_search(
            payload["query"],
            model_route_overrides=model_route_overrides,
        )
    if tool_name == "read_json":
        return tool_read_json(payload["path"])
    if tool_name == "write_json":
        return tool_write_json(payload["path"], payload["data"])
    if tool_name == "http_request":
        return tool_http_request(
            url=payload["url"],
            method=payload["method"],
            params=payload.get("params"),
            json_body=payload.get("json"),
            timeout=payload.get("timeout", 15),
        )
    if tool_name == "json_extract":
        return tool_json_extract(
            data=payload["data"],
            path=payload["path"],
        )
    if tool_name == "set_var":
        return tool_set_var(payload["name"], payload.get("value"))
    if tool_name == "template_render":
        return tool_template_render(
            template=payload["template"],
            step_context=step_context or {},
            var_context=var_context or {},
            strict=payload.get("strict", True),
        )
    if tool_name == "if_condition":
        if "logic" in payload or "conditions" in payload:
            return tool_if_condition(
                logic=payload.get("logic"),
                conditions=payload.get("conditions"),
            )
        return tool_if_condition(
            left=payload["left"],
            operator=payload["operator"],
            right=payload["right"],
        )

    return {
        "ok": False,
        "output_text": f"未知工具：{tool_name}",
        "output_data": None,
        "error": f"未知工具：{tool_name}",
    }


# =========================
# Legacy compatibility
# =========================
def run_legacy_step(
    step_name: str,
    user_input: str,
    previous_outputs: list[str],
    model_route_overrides: dict[str, dict[str, Any]] | None = None,
) -> tuple[str, bool]:
    step_name = step_name or ""

    if "读取文件" in step_name:
        path = extract_path_from_text(user_input)
        if not path:
            return "file_read 执行失败：缺少文件路径", False
        result = tool_file_read(path)
        return result["output_text"], result["ok"]

    if "写入" in step_name:
        matches = re.findall(r"(/[^ \n\r\t'\"，。；：]+)", user_input)
        target_path = matches[-1] if matches else None
        content = previous_outputs[-1] if previous_outputs else ""
        if not target_path:
            return "file_write 执行失败：缺少文件路径", False
        result = tool_file_write(target_path, content)
        return result["output_text"], result["ok"]

    if "列出目录" in step_name:
        path = extract_path_from_text(user_input)
        if not path:
            return "list_dir 执行失败：缺少目录路径", False
        result = tool_list_dir(path)
        return result["output_text"], result["ok"]

    if "执行命令" in step_name:
        command_match = re.search(r"[`‘“\"]([^`’”\"]+)[`’”\"]", user_input)
        command = command_match.group(1).strip() if command_match else ""
        if not command:
            return "shell_exec 执行失败：缺少命令", False
        result = tool_shell_exec(command)
        return result["output_text"], result["ok"]

    if "搜索" in step_name or "调研" in step_name:
        result = tool_web_search(user_input, model_route_overrides=model_route_overrides)
        return result["output_text"], result["ok"]

    if "整理" in step_name or "分析" in step_name or "摘要" in step_name:
        text = previous_outputs[-1] if previous_outputs else user_input
        result = tool_summarize_text(text, model_route_overrides=model_route_overrides)
        return result["output_text"], result["ok"]

    if "生成" in step_name or "改写" in step_name or "写" in step_name:
        prompt = previous_outputs[-1] if previous_outputs else user_input
        result = tool_generate_text(prompt, model_route_overrides=model_route_overrides)
        return result["output_text"], result["ok"]

    return f"已执行步骤：{step_name}", True


# =========================
# Artifact
# =========================
def write_artifact(task_id: int, user_input: str, step_outputs: list[str]) -> str:
    file_path = ARTIFACT_DIR / f"task_{task_id}.md"
    sections = []
    for idx, output in enumerate(step_outputs, start=1):
        sections.append(f"### 步骤 {idx}\n{output}")

    content = f"""# 任务结果

## 原始任务
{user_input}

## 执行步骤结果

{chr(10).join(sections)}
"""
    file_path.write_text(content, encoding="utf-8")
    return str(file_path)


# =========================
# Main worker loop
# =========================
def interrupt_task_if_requested(
    cur,
    task_id: int,
    user_input: str,
    step_order: Optional[int],
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
):
    note = "manual interrupt requested"
    persist_task_runtime_state(
        cur,
        task_id,
        user_input,
        status="paused",
        current_step=step_order,
        step_context=step_context,
        var_context=var_context,
        step_outputs=step_outputs,
        task_error_message=note,
        checkpoint_error=note,
    )
    update_task_trace_status(cur, task_id, status="paused", error_summary=note)
    raise InterruptRequested(note)


def resolve_structured_step_input(tool_name: str, raw_input: Any, step_context: dict[int, dict], var_context: dict[str, Any]) -> dict:
    if tool_name == "if_condition":
        if isinstance(raw_input, dict) and "logic" in raw_input and "conditions" in raw_input:
            resolved_input = {
                "logic": raw_input.get("logic"),
                "conditions": [],
            }
            for condition in raw_input.get("conditions") or []:
                cond_operator = condition.get("operator") if isinstance(condition, dict) else None
                if cond_operator in {"exists", "not_exists"}:
                    resolved_condition = dict(condition)
                    resolved_condition["left"] = try_resolve_reference(condition.get("left"), step_context, var_context)
                    resolved_condition["right"] = try_resolve_reference(condition.get("right"), step_context, var_context)
                else:
                    resolved_condition = resolve_input_payload(condition, step_context, var_context)
                resolved_input["conditions"].append(resolved_condition)
        else:
            raw_operator = raw_input.get("operator") if isinstance(raw_input, dict) else None
            if raw_operator in {"exists", "not_exists"}:
                resolved_input = dict(raw_input)
                resolved_input["left"] = try_resolve_reference(raw_input.get("left"), step_context, var_context)
                resolved_input["right"] = try_resolve_reference(raw_input.get("right"), step_context, var_context)
            else:
                resolved_input = resolve_input_payload(raw_input, step_context)
    elif tool_name == "template_render":
        resolved_input = {
            "template": raw_input.get("template", "") if isinstance(raw_input, dict) else "",
            "strict": (raw_input.get("strict", True) if isinstance(raw_input, dict) else True),
        }
    else:
        resolved_input = resolve_input_payload(raw_input, step_context, var_context)

    if tool_name == "http_request":
        resolved_input = normalize_http_request_input(resolved_input)

    if tool_name == "file_write" and not isinstance(resolved_input.get("content"), str):
        resolved_input = dict(resolved_input)
        content_value = resolved_input.get("content")
        if isinstance(content_value, (dict, list)):
            resolved_input["content"] = json.dumps(content_value, ensure_ascii=False)
        else:
            resolved_input["content"] = str(content_value)

    return resolved_input


def enforce_step_approval(
    cur,
    task_id: int,
    step_order: int,
    step: dict,
    tool_name: str,
    resolved_input: dict,
    user_input: str,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
    step_trace_id: int | None = None,
    tool_trace_id: int | None = None,
    approval_required: Optional[bool] = None,
    approval_reason: Optional[str] = None,
):
    if approval_required is None or approval_reason is None:
        approval_required, approval_reason = should_require_approval(tool_name, resolved_input)
    if not approval_required:
        return

    approval = get_step_approval(cur, task_id, step_order)
    if approval and approval.get("status") == "approved":
        return
    if approval and approval.get("status") == "rejected":
        raise RuntimeError(f"审批拒绝：{approval.get('decision_note') or approval_reason}")

    if not approval:
        create_step_approval(
            cur,
            task_id,
            step_order,
            str(step.get("title") or f"步骤 {step_order}"),
            tool_name,
            resolved_input,
            approval_reason,
        )
        logger.info(
            "approval created task_id=%s step_order=%s tool=%s reason=%s",
            task_id,
            step_order,
            tool_name,
            approval_reason,
        )
    set_step_waiting_approval(cur, task_id, step_order, tool_name, resolved_input, approval_reason)
    persist_task_runtime_state(
        cur,
        task_id,
        user_input,
        status="waiting_approval",
        current_step=step_order,
        step_context=step_context,
        var_context=var_context,
        step_outputs=step_outputs,
        task_error_message=None,
        checkpoint_error=approval_reason,
    )
    update_task_trace_status(cur, task_id, status="waiting_approval", error_summary="")
    complete_step_and_tool_trace(
        cur,
        step_trace_id=step_trace_id,
        tool_trace_id=tool_trace_id,
        status="waiting_approval",
        output_payload=f"等待审批：{approval_reason}",
        output_data={"approval_required": True, "reason": approval_reason},
        error_summary="",
    )
    raise ApprovalRequired(approval_reason)


def execute_step_with_retries(
    cur,
    task_id: int,
    step_order: int,
    tool_name: str,
    resolved_input: dict,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    max_retries: int,
    retry_count: int,
    claim_heartbeat: Optional[TaskClaimHeartbeat],
    user_input: str,
    step_outputs: list[str],
    model_route_overrides: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict, int]:
    result = None
    ok = False
    last_error = ""

    while True:
        if claim_heartbeat is not None:
            claim_heartbeat.assert_owned()
        if get_task_control_status(task_id) == "interrupt_requested":
            interrupt_task_if_requested(
                cur,
                task_id,
                user_input,
                step_order,
                step_context,
                var_context,
                step_outputs,
            )

        result = execute_tool(
            tool_name,
            resolved_input,
            step_context,
            var_context,
            model_route_overrides=model_route_overrides,
        )
        ok = bool(result["ok"])
        if ok:
            break

        last_error = result["error"] or result["output_text"] or "step failed"
        if retry_count >= max_retries:
            break

        retry_count += 1
        logger.warning(
            "step retry task_id=%s step_order=%s tool=%s retry_count=%s max_retries=%s error=%s",
            task_id,
            step_order,
            tool_name,
            retry_count,
            max_retries,
            last_error[:300],
        )
        set_step_retry_count(cur, task_id, step_order, retry_count)
        cur.connection.commit()
        time.sleep(1)

    if not ok and retry_count:
        result["output_text"] = f"{result['output_text']}\n已重试次数：{retry_count}/{max_retries}"
        if last_error:
            result["error"] = f"{last_error}（已重试 {retry_count}/{max_retries} 次）"

    return result, retry_count


def finalize_structured_step_success(
    cur,
    task_id: int,
    step_order: int,
    tool_name: str,
    resolved_input: Any,
    error_strategy: str,
    result: dict,
    retry_count: int,
    user_input: str,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
    step_trace_id: int | None = None,
    tool_trace_id: int | None = None,
):
    persist_structured_step_outcome(
        cur,
        task_id,
        step_order,
        tool_name,
        resolved_input,
        "completed",
        result["output_text"],
        result["output_data"],
        "",
        error_strategy,
        user_input,
        step_context,
        var_context,
        step_outputs,
        checkpoint_error="",
        update_var=(tool_name == "set_var"),
        retry_count=retry_count,
    )
    complete_step_and_tool_trace(
        cur,
        step_trace_id=step_trace_id,
        tool_trace_id=tool_trace_id,
        status="completed",
        output_payload=result["output_text"],
        output_data=result["output_data"],
        retry_count=retry_count,
    )


def finalize_structured_step_continue(
    cur,
    task_id: int,
    step_order: int,
    tool_name: str,
    resolved_input: Any,
    error_strategy: str,
    result: dict,
    user_input: str,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
    step_trace_id: int | None = None,
    tool_trace_id: int | None = None,
):
    persist_structured_step_outcome(
        cur,
        task_id,
        step_order,
        tool_name,
        resolved_input,
        "failed",
        result["output_text"],
        result["output_data"],
        result["error"],
        error_strategy,
        user_input,
        step_context,
        var_context,
        step_outputs,
        checkpoint_error=result["error"],
        update_var=False,
    )
    complete_step_and_tool_trace(
        cur,
        step_trace_id=step_trace_id,
        tool_trace_id=tool_trace_id,
        status="failed",
        output_payload=result["output_text"],
        output_data=result["output_data"],
        error_summary=result["error"],
    )


def record_structured_step_exception(
    cur,
    task_id: int,
    step_order: int,
    tool_name: str,
    input_payload: Any,
    error_strategy: str,
    user_input: str,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
    err: str,
):
    persist_structured_step_outcome(
        cur,
        task_id,
        step_order,
        tool_name,
        input_payload,
        "failed",
        err,
        None,
        err,
        error_strategy,
        user_input,
        step_context,
        var_context,
        step_outputs,
        checkpoint_error=err,
        update_var=False,
        runtime_status="failed",
    )


def handle_structured_step_exception(
    cur,
    task_id: int,
    user_input: str,
    execution_state: StructuredStepExecutionState,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
    err: str,
    step_trace_id: int | None = None,
    tool_trace_id: int | None = None,
):
    execution_request = execution_state["execution_request"]
    retry_count = int(execution_state["retry_count"])
    max_retries = int(execution_state["max_retries"])
    if retry_count:
        err = f"{err}（已重试 {retry_count}/{max_retries} 次）"
    record_structured_step_exception(
        cur,
        task_id,
        int(execution_request["step_order"]),
        str(execution_request["tool_name"]),
        execution_request["raw_input"],
        str(execution_request["error_strategy"]),
        user_input,
        step_context,
        var_context,
        step_outputs,
        err,
    )
    complete_step_and_tool_trace(
        cur,
        step_trace_id=step_trace_id,
        tool_trace_id=tool_trace_id,
        status="failed",
        output_payload=err,
        output_data=None,
        error_summary=err,
        retry_count=retry_count,
    )


def build_structured_step_execution_state(
    execution_request: StepExecutionRequest | EnrichedStepExecutionRequest,
) -> StructuredStepExecutionState:
    max_retries = execution_request.get("effective_max_retries", execution_request["max_retries"])
    retry_count = execution_request.get("effective_retry_count", execution_request["retry_count"])
    return {
        "execution_request": execution_request,
        "retry_count": int(retry_count),
        "max_retries": int(max_retries),
        "step_trace_id": None,
        "tool_trace_id": None,
    }


def update_structured_step_execution_state(
    execution_state: StructuredStepExecutionState,
    execution_request: StepExecutionRequest | EnrichedStepExecutionRequest,
    retry_count: int,
) -> StructuredStepExecutionState:
    execution_state["execution_request"] = execution_request
    execution_state["retry_count"] = int(retry_count)
    execution_state["max_retries"] = int(
        execution_request.get("effective_max_retries", execution_request["max_retries"])
    )
    return execution_state


def perform_structured_step_execution(
    cur,
    task_id: int,
    user_input: str,
    step: dict,
    execution_state: StructuredStepExecutionState,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
    claim_heartbeat: Optional[TaskClaimHeartbeat],
    model_route_overrides: dict[str, dict[str, Any]] | None = None,
) -> Optional[dict]:
    execution_request = execution_state["execution_request"]
    execution_request, result, retry_count = process_structured_step_request(
        cur,
        task_id,
        user_input,
        step,
        execution_request,
        step_context,
        var_context,
        step_outputs,
        claim_heartbeat,
        model_route_overrides,
        step_trace_id=execution_state.get("step_trace_id"),
        tool_trace_id=execution_state.get("tool_trace_id"),
    )
    update_structured_step_execution_state(execution_state, execution_request, retry_count)
    return result


def complete_structured_step_execution(
    cur,
    task_id: int,
    user_input: str,
    step: dict,
    execution_request: StepExecutionRequest,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
    claim_heartbeat: Optional[TaskClaimHeartbeat],
    model_route_overrides: dict[str, dict[str, Any]] | None = None,
    step_trace_id: int | None = None,
    tool_trace_id: int | None = None,
):
    execution_state = build_structured_step_execution_state(execution_request)
    execution_state["step_trace_id"] = step_trace_id
    execution_state["tool_trace_id"] = tool_trace_id

    try:
        result = perform_structured_step_execution(
            cur,
            task_id,
            user_input,
            step,
            execution_state,
            step_context,
            var_context,
            step_outputs,
            claim_heartbeat,
            model_route_overrides,
        )
        if result is None:
            return
    except ApprovalRequired:
        raise
    except Exception as e:
        handle_structured_step_exception(
            cur,
            task_id,
            user_input,
            execution_state,
            step_context,
            var_context,
            step_outputs,
            str(e),
            step_trace_id=step_trace_id,
            tool_trace_id=tool_trace_id,
        )
        raise
    else:
        if result is not None:
            route_structured_step_outcome(
                cur,
                task_id,
                user_input,
                execution_state["execution_request"],
                result,
                int(execution_state["retry_count"]),
                step_context,
                var_context,
                step_outputs,
                step_trace_id=step_trace_id,
                tool_trace_id=tool_trace_id,
            )


def persist_structured_step_runtime_state(
    cur,
    task_id: int,
    user_input: str,
    step_order: int,
    runtime_status: str,
    output_payload: str,
    output_data: Any,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
    checkpoint_error: str,
    update_var: bool,
):
    step_context[step_order] = {
        "output_payload": output_payload,
        "output_data": output_data,
    }
    if update_var and isinstance(output_data, dict):
        var_name = output_data.get("name")
        if isinstance(var_name, str) and var_name.strip():
            var_context[var_name.strip()] = output_data.get("value")
    step_outputs.append(output_payload)
    write_checkpoint(
        cur,
        task_id,
        user_input,
        runtime_status,
        step_order,
        step_context,
        var_context,
        step_outputs,
        checkpoint_error,
    )
    cur.connection.commit()


def persist_task_runtime_state(
    cur,
    task_id: int,
    user_input: str,
    status: str,
    current_step: Optional[int],
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
    task_error_message: Optional[str],
    checkpoint_error: str,
    result: Optional[str] = None,
    update_status_row: bool = True,
):
    if update_status_row:
        update_task_status(cur, task_id, status, result, task_error_message)
    write_checkpoint(
        cur,
        task_id,
        user_input,
        status,
        current_step,
        step_context,
        var_context,
        step_outputs,
        checkpoint_error,
    )
    cur.connection.commit()


def persist_structured_step_outcome(
    cur,
    task_id: int,
    step_order: int,
    tool_name: Optional[str],
    input_payload: Any,
    step_status: str,
    output_payload: str,
    output_data: Any,
    error_message: str,
    error_strategy: str,
    user_input: str,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
    checkpoint_error: str,
    update_var: bool,
    runtime_status: str = "running",
    retry_count: Optional[int] = None,
):
    set_step_result(
        cur,
        task_id,
        step_order,
        status=step_status,
        tool_name=tool_name,
        input_payload=input_payload,
        output_payload=output_payload,
        output_data=output_data,
        error_message=error_message,
        error_strategy=error_strategy,
    )
    cur.connection.commit()

    if retry_count:
        set_step_retry_count(cur, task_id, step_order, retry_count)
        cur.connection.commit()

    persist_structured_step_runtime_state(
        cur,
        task_id,
        user_input,
        step_order,
        runtime_status,
        output_payload,
        output_data,
        step_context,
        var_context,
        step_outputs,
        checkpoint_error,
        update_var,
    )


def record_skipped_step(
    cur,
    task_id: int,
    step_order: int,
    tool_name: str,
    raw_input: Any,
    run_if: Any,
    skip_if: Any,
    skip_reason: str,
    error_strategy: str,
    user_input: str,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
    step_trace_id: int | None = None,
    tool_trace_id: int | None = None,
):
    skipped_output = f"步骤跳过：{skip_reason}"
    skipped_data = {
        "skipped": True,
        "reason": skip_reason,
        "run_if": run_if,
        "skip_if": skip_if,
    }
    persist_structured_step_outcome(
        cur,
        task_id,
        step_order,
        tool_name,
        raw_input,
        "completed",
        skipped_output,
        skipped_data,
        "",
        error_strategy,
        user_input,
        step_context,
        var_context,
        step_outputs,
        checkpoint_error="",
        update_var=False,
    )
    complete_step_and_tool_trace(
        cur,
        step_trace_id=step_trace_id,
        tool_trace_id=tool_trace_id,
        status="completed",
        output_payload=skipped_output,
        output_data=skipped_data,
    )


def select_final_outputs_for_task(cur, task_id: int, fallback_outputs: list[str]) -> list[str]:
    cur.execute(
        """
        SELECT deliverable_spec_json
        FROM task_runs
        WHERE id = %s;
        """,
        (task_id,),
    )
    task_row = cur.fetchone() or {}
    deliverable_spec = parse_jsonish(task_row.get("deliverable_spec_json"), {})
    deliverable_type = str((deliverable_spec or {}).get("deliverable_type") or "").strip()
    if deliverable_type not in {
        "copywriting_bundle",
        "direct_answer",
        "execution_result",
        "generated_content",
        "research_summary",
        "rewritten_text",
        "research_then_generate_bundle",
    }:
        return fallback_outputs

    generated_outputs = [
        str(row.get("output_payload") or "").strip()
        for row in get_task_steps(cur, task_id)
        if str(row.get("status") or "") == "completed"
        and str(row.get("tool_name") or "") == "generate_text"
        and str(row.get("output_payload") or "").strip()
    ]
    if generated_outputs:
        return [generated_outputs[-1]]
    return fallback_outputs


def update_task_delivery_records(
    cur,
    task_id: int,
    *,
    validation_report: dict[str, Any] | None = None,
    recovery_action: dict[str, Any] | None = None,
):
    cur.execute(
        """
        UPDATE task_runs
        SET validation_report_json = COALESCE(%s, validation_report_json),
            recovery_action_json = COALESCE(%s, recovery_action_json),
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s;
        """,
        (
            Json(validation_report) if validation_report is not None else None,
            Json(recovery_action) if recovery_action is not None else None,
            task_id,
        ),
    )
    cur.connection.commit()


def count_task_audit_events(cur, task_id: int, event_type: str) -> int:
    cur.execute(
        """
        SELECT COUNT(*) AS count
        FROM audit_logs
        WHERE task_id = %s AND event_type = %s;
        """,
        (task_id, event_type),
    )
    row = cur.fetchone() or {}
    return int(row.get("count") or 0)


def find_first_step_order_by_tool(cur, task_id: int, tool_name: str) -> int | None:
    cur.execute(
        """
        SELECT step_order
        FROM task_steps
        WHERE task_id = %s AND tool_name = %s
        ORDER BY step_order ASC
        LIMIT 1;
        """,
        (task_id, tool_name),
    )
    row = cur.fetchone()
    return int(row["step_order"]) if row and row.get("step_order") is not None else None


def trim_runtime_state_for_resume(
    *,
    resume_from: int,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
) -> tuple[dict[int, dict], dict[str, Any], list[str]]:
    trimmed_step_context = {
        int(step_order): value
        for step_order, value in step_context.items()
        if int(step_order) < int(resume_from)
    }
    trimmed_outputs = list(step_outputs[: max(0, int(resume_from) - 1)])
    return trimmed_step_context, dict(var_context), trimmed_outputs


def reset_task_for_auto_recovery(
    cur,
    *,
    task_id: int,
    user_input: str,
    resume_from: int,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
    note: str,
    recovery_action: dict[str, Any],
):
    trimmed_step_context, trimmed_var_context, trimmed_outputs = trim_runtime_state_for_resume(
        resume_from=resume_from,
        step_context=step_context,
        var_context=var_context,
        step_outputs=step_outputs,
    )
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
    persist_task_runtime_state(
        cur,
        task_id,
        user_input,
        status="pending",
        current_step=resume_from,
        step_context=trimmed_step_context,
        var_context=trimmed_var_context,
        step_outputs=trimmed_outputs,
        task_error_message=None,
        checkpoint_error=note,
        result=None,
    )
    cur.execute(
        """
        UPDATE task_runs
        SET validation_report_json = NULL,
            recovery_action_json = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s;
        """,
        (task_id,),
    )
    update_task_trace_status(cur, task_id, status="pending", error_summary=note)
    insert_audit_log(
        cur,
        "task.auto_recovery_applied",
        "worker",
        task_id,
        {
            "resume_from": resume_from,
            "note": note,
            "recovery_action": recovery_action,
        },
    )
    cur.connection.commit()
    enqueue_task(task_id)


def fail_task_for_missing_clarification(
    cur,
    task_id: int,
    user_input: str,
    *,
    task_intent: dict[str, Any],
    deliverable_spec: dict[str, Any],
):
    ensure_task_trace(cur, task_id, user_input)
    validation_report = build_clarification_required_validation_report(
        user_input,
        task_intent=task_intent,
        deliverable_spec=deliverable_spec,
    )
    recovery_action = build_clarification_required_recovery_action(
        task_intent=task_intent,
        deliverable_spec=deliverable_spec,
    )
    result_message = build_clarification_required_message(
        task_intent=task_intent,
        deliverable_spec=deliverable_spec,
    )
    update_task_delivery_records(
        cur,
        task_id,
        validation_report=validation_report,
        recovery_action=recovery_action,
    )
    persist_task_runtime_state(
        cur,
        task_id,
        user_input,
        status="failed",
        current_step=None,
        step_context={},
        var_context={},
        step_outputs=[],
        task_error_message=str(recovery_action.get("summary") or "").strip(),
        checkpoint_error=str(recovery_action.get("summary") or "").strip(),
        result=result_message,
    )
    update_task_trace_status(cur, task_id, status="failed", error_summary=str(recovery_action.get("summary") or "").strip())
    insert_audit_log(
        cur,
        "task.clarification_required",
        "worker",
        task_id,
        {
            "task_intent": task_intent,
            "deliverable_spec": deliverable_spec,
            "recovery_action": recovery_action,
        },
    )
    cur.connection.commit()


def validate_task_deliverable(
    cur,
    task_id: int,
    *,
    user_input: str,
    final_result: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    cur.execute(
        """
        SELECT task_intent_json, deliverable_spec_json, runtime_overrides
        FROM task_runs
        WHERE id = %s;
        """,
        (task_id,),
    )
    task_row = cur.fetchone() or {}
    task_intent = parse_jsonish(task_row.get("task_intent_json"), {}) or {}
    deliverable_spec = parse_jsonish(task_row.get("deliverable_spec_json"), {}) or {}
    runtime_overrides = normalize_runtime_overrides(task_row.get("runtime_overrides"))
    return evaluate_task_deliverable(
        task_intent=task_intent if isinstance(task_intent, dict) else {},
        deliverable_spec=deliverable_spec if isinstance(deliverable_spec, dict) else {},
        runtime_overrides=runtime_overrides,
        user_input=user_input,
        final_result=final_result,
    )


def assemble_task_success_result(cur, task_id: int, user_input: str, step_outputs: list[str]) -> tuple[str, str]:
    final_outputs = select_final_outputs_for_task(cur, task_id, step_outputs)
    artifact_path = write_artifact(task_id, user_input, final_outputs)
    final_result = "\n\n".join(final_outputs) + f"\n\n产出文件：{artifact_path}"
    return artifact_path, final_result


def strip_artifact_suffix(text: str) -> str:
    return str(text or "").split("\n\n产出文件：", 1)[0].strip()


def build_task_result_excerpt(task_row: dict[str, Any], limit: int = 220) -> str:
    return strip_artifact_suffix(str(task_row.get("result") or ""))[:limit]


def build_task_summary_memory_content(task_display_input: str, final_result: str) -> str:
    normalized_result = strip_artifact_suffix(final_result)
    if len(normalized_result) > 1200:
        normalized_result = normalized_result[:1200].rstrip() + "..."
    return f"任务：{task_display_input.strip()}\n\n结果摘要：\n{normalized_result}"


def extract_marked_clauses(text: str, markers: tuple[str, ...], max_length: int = 240) -> list[str]:
    normalized = " ".join((text or "").split())
    if not normalized:
        return []

    normalized = (
        normalized.replace("。", "|")
        .replace("！", "|")
        .replace("？", "|")
        .replace("；", "|")
        .replace(";", "|")
        .replace("\n", "|")
    )
    clauses = [part.strip(" ,|") for part in normalized.split("|") if part.strip(" ,|")]

    matched: list[str] = []
    seen: set[str] = set()
    for clause in clauses:
        if not any(marker in clause for marker in markers):
            continue
        compact = clause[:max_length].strip()
        if compact and compact not in seen:
            seen.add(compact)
            matched.append(compact)
    return matched


def infer_task_memories(user_input: str, final_result: str) -> list[dict[str, Any]]:
    inferred: list[dict[str, Any]] = []
    normalized_input = " ".join((user_input or "").split())
    normalized_result = " ".join(strip_artifact_suffix(final_result).split())

    if normalized_input:
        if (
            "以后请" in normalized_input
            or "之后请" in normalized_input
            or "偏好" in normalized_input
            or "请用" in normalized_input
        ):
            preference_clauses: list[str] = []
            for keyword in ("简洁", "分点", "中文", "英文", "表格", "步骤", "要点"):
                if keyword in normalized_input:
                    preference_clauses.append(keyword)
            if preference_clauses:
                inferred.append(
                    {
                        "category": "preference",
                        "content": "偏好" + "、".join(preference_clauses) + "回答",
                        "importance": 4,
                    }
                )

        open_loop_markers = ("后续", "下一步", "待办", "TODO", "todo", "follow-up", "follow up", "继续")
        for clause in extract_marked_clauses(normalized_input, open_loop_markers):
            inferred.append(
                {
                    "category": "follow_up",
                    "content": clause,
                    "importance": 3,
                }
            )

    if normalized_result:
        result_open_loop_markers = ("后续", "下一步", "待办", "TODO", "todo", "需要继续", "尚未完成", "继续处理")
        for clause in extract_marked_clauses(normalized_result, result_open_loop_markers):
            inferred.append(
                {
                    "category": "follow_up",
                    "content": clause,
                    "importance": 3,
                }
            )

        summary_excerpt = normalized_result[:300].strip()
        if summary_excerpt:
            inferred.append(
                {
                    "category": "fact",
                    "content": summary_excerpt,
                    "importance": 2,
                }
            )

    deduped: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for item in inferred:
        key = (str(item["category"]).strip().lower(), str(item["content"]).strip())
        if not key[1] or key in seen_pairs:
            continue
        seen_pairs.add(key)
        deduped.append(item)
    return deduped


def rebuild_session_state_from_worker(cur, session_id: int):
    cur.execute("SELECT id, name FROM sessions WHERE id = %s;", (session_id,))
    session_row = cur.fetchone()
    if not session_row:
        return

    cur.execute(
        """
        SELECT id, user_input, status, runtime_overrides
        FROM task_runs
        WHERE session_id = %s
        ORDER BY updated_at DESC, id DESC;
        """,
        (session_id,),
    )
    task_rows = list(cur.fetchall())
    tasks_by_status: dict[str, int] = {}
    for row in task_rows:
        status = str(row.get("status") or "unknown")
        tasks_by_status[status] = tasks_by_status.get(status, 0) + 1

    cur.execute(
        """
        SELECT category, content, importance
        FROM session_memories
        WHERE session_id = %s
        ORDER BY importance DESC, id DESC;
        """,
        (session_id,),
    )
    memory_rows = list(cur.fetchall())

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
        user_input = build_task_display_user_input(
            str(row.get("user_input") or ""),
            normalize_runtime_overrides(row.get("runtime_overrides")),
        ).strip()
        if status in {"pending", "running", "waiting_approval", "paused", "interrupt_requested"} and user_input and user_input not in seen_open_loops:
            seen_open_loops.add(user_input)
            open_loops.append(user_input)

    summary_parts = [f"Session: {session_row.get('name') or session_id}", f"tasks={len(task_rows)}"]
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
            updated_at = CURRENT_TIMESTAMP;
        """,
        (
            session_id,
            summary_text,
            safe_json_dumps(preferences),
            safe_json_dumps(open_loops),
        ),
    )


def capture_session_memory_for_completed_task(cur, task_id: int, user_input: str, final_result: str):
    ensure_sessions_tables(cur)
    ensure_audit_logs_table(cur)
    ensure_long_term_memory_table(cur)
    cur.execute(
        """
        SELECT session_id, runtime_overrides, created_by_actor
        FROM task_runs
        WHERE id = %s;
        """,
        (task_id,),
    )
    row = cur.fetchone()
    session_id = row.get("session_id") if row else None
    actor_name = str((row or {}).get("created_by_actor") or "").strip()

    memory_ids: list[int] = []
    task_display_input = build_task_display_user_input(
        str(user_input or ""),
        normalize_runtime_overrides((row or {}).get("runtime_overrides")),
    )
    content = build_task_summary_memory_content(task_display_input, final_result)
    upsert_long_term_memory(
        cur,
        memory_kind="task_memory",
        source_session_id=int(session_id) if session_id else None,
        source_task_id=task_id,
        actor_name=actor_name,
        title=task_display_input[:180],
        content=content,
        metadata={"deliverable_kind": "task_summary"},
    )
    upsert_long_term_memory(
        cur,
        memory_kind="conversation_memory",
        source_session_id=int(session_id) if session_id else None,
        source_task_id=task_id,
        actor_name=actor_name,
        title=task_display_input[:180],
        content=f"输入：{str(user_input or '').strip()[:1200]}\n\n输出：{strip_artifact_suffix(final_result)[:1600]}",
        metadata={"memory_scope": "conversation"},
    )
    if not session_id:
        cur.connection.commit()
        return
    cur.execute(
        """
        SELECT id
        FROM session_memories
        WHERE session_id = %s AND source_task_id = %s AND category = 'task_summary'
        ORDER BY id DESC
        LIMIT 1;
        """,
        (session_id, task_id),
    )
    existing = cur.fetchone()
    if existing:
        cur.execute(
            """
            UPDATE session_memories
            SET content = %s,
                importance = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s;
            """,
            (content, 2, existing["id"]),
        )
        memory_ids.append(int(existing["id"]))
    else:
        cur.execute(
            """
            INSERT INTO session_memories (session_id, category, content, importance, source_task_id)
            VALUES (%s, 'task_summary', %s, %s, %s)
            RETURNING id;
            """,
            (session_id, content, 2, task_id),
        )
        memory_ids.append(int(cur.fetchone()["id"]))

    inferred_memories = infer_task_memories(task_display_input, final_result)
    for item in inferred_memories:
        category = str(item["category"]).strip().lower()
        inferred_content = str(item["content"]).strip()
        importance = int(item.get("importance", 3))
        if not inferred_content:
            continue
        upsert_long_term_memory(
            cur,
            memory_kind="pattern_memory" if category in {"preference", "follow_up"} else "task_memory",
            source_session_id=int(session_id),
            source_task_id=task_id,
            actor_name=actor_name,
            title=f"{category}:{task_display_input[:80]}",
            content=inferred_content,
            metadata={"category": category, "importance": importance},
        )

        cur.execute(
            """
            SELECT id
            FROM session_memories
            WHERE session_id = %s AND category = %s AND content = %s
            ORDER BY id DESC
            LIMIT 1;
            """,
            (session_id, category, inferred_content),
        )
        inferred_existing = cur.fetchone()
        if inferred_existing:
            cur.execute(
                """
                UPDATE session_memories
                SET importance = GREATEST(importance, %s),
                    source_task_id = COALESCE(source_task_id, %s),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s;
                """,
                (importance, task_id, inferred_existing["id"]),
            )
            memory_ids.append(int(inferred_existing["id"]))
        else:
            cur.execute(
                """
                INSERT INTO session_memories (session_id, category, content, importance, source_task_id)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id;
                """,
                (session_id, category, inferred_content, importance, task_id),
            )
            memory_ids.append(int(cur.fetchone()["id"]))

    rebuild_session_state_from_worker(cur, int(session_id))
    insert_audit_log(
        cur,
        "session.memory_auto_capture",
        "worker",
        task_id,
        {
            "session_id": int(session_id),
            "memory_ids": memory_ids,
            "category": "task_summary",
            "inferred_categories": [str(item["category"]).strip().lower() for item in inferred_memories],
        },
    )
    cur.connection.commit()


def finalize_task_success(
    cur,
    task_id: int,
    user_input: str,
    step_outputs: list[str],
    step_context: dict[int, dict],
    var_context: dict[str, Any],
) -> str:
    artifact_path, final_result = assemble_task_success_result(cur, task_id, user_input, step_outputs)
    validation_report, recovery_action = validate_task_deliverable(
        cur,
        task_id,
        user_input=user_input,
        final_result=final_result,
    )
    update_task_delivery_records(
        cur,
        task_id,
        validation_report=validation_report,
        recovery_action=recovery_action,
    )
    insert_audit_log(
        cur,
        "task.validation_recorded",
        "worker",
        task_id,
        {
            "passed": bool(validation_report.get("passed")),
            "deliverable_type": validation_report.get("deliverable_type"),
            "recovery_action": recovery_action.get("action"),
        },
    )
    cur.connection.commit()

    if not bool(validation_report.get("passed")):
        validation_message = str(recovery_action.get("summary") or validation_report.get("summary") or "交付物校验失败").strip()
        action_key = str(recovery_action.get("action") or "").strip()
        auto_recovery_count = count_task_audit_events(cur, task_id, "task.auto_recovery_applied")
        if action_key == "retry_generate" and auto_recovery_count < 1:
            resume_from = find_first_step_order_by_tool(cur, task_id, "generate_text") or max(1, len(step_outputs))
            auto_note = f"auto recovery scheduled: {action_key}"
            reset_task_for_auto_recovery(
                cur,
                task_id=task_id,
                user_input=user_input,
                resume_from=resume_from,
                step_context=step_context,
                var_context=var_context,
                step_outputs=step_outputs,
                note=auto_note,
                recovery_action=recovery_action,
            )
            logger.info(
                "task auto recovery scheduled id=%s action=%s resume_from=%s",
                task_id,
                action_key,
                resume_from,
            )
            raise AutoRecoveryScheduled(auto_note)

        persist_task_runtime_state(
            cur,
            task_id,
            user_input,
            status="failed",
            current_step=None,
            step_context=step_context,
            var_context=var_context,
            step_outputs=step_outputs,
            task_error_message=validation_message,
            checkpoint_error=validation_message,
            result=final_result,
        )
        update_task_trace_status(cur, task_id, status="failed", error_summary=validation_message)
        insert_audit_log(
            cur,
            "task.validation_failed",
            "worker",
            task_id,
            {
                "failed_checks": [
                    item.get("name")
                    for item in list(validation_report.get("checks") or [])
                    if not bool((item or {}).get("passed"))
                ],
                "recovery_action": recovery_action,
            },
        )
        cur.connection.commit()
        try:
            postrun_cur = cur.connection.cursor()
            try:
                maybe_create_task_postrun_agent_records(postrun_cur, task_id, user_input)
            finally:
                postrun_cur.close()
        except Exception as exc:
            try:
                cur.connection.rollback()
            except Exception:
                pass
            logger.warning("task postrun agent capture failed task_id=%s error=%s", task_id, exc)
        logger.warning("task validation failed id=%s artifact=%s", task_id, artifact_path)
        return artifact_path

    persist_task_runtime_state(
        cur,
        task_id,
        user_input,
        status="completed",
        current_step=None,
        step_context=step_context,
        var_context=var_context,
        step_outputs=step_outputs,
        task_error_message=None,
        checkpoint_error="",
        result=final_result,
    )
    update_task_trace_status(cur, task_id, status="completed", error_summary="")
    try:
        capture_session_memory_for_completed_task(cur, task_id, user_input, final_result)
    except Exception as exc:
        try:
            cur.connection.rollback()
        except Exception:
            pass
        logger.warning("session memory auto capture failed task_id=%s error=%s", task_id, exc)
    try:
        postrun_cur = cur.connection.cursor()
        try:
            maybe_create_task_postrun_agent_records(postrun_cur, task_id, user_input)
        finally:
            postrun_cur.close()
    except Exception as exc:
        try:
            cur.connection.rollback()
        except Exception:
            pass
        logger.warning("task postrun agent capture failed task_id=%s error=%s", task_id, exc)
    logger.info("task completed id=%s artifact=%s", task_id, artifact_path)
    return artifact_path


def finalize_task_failure(
    cur,
    task_id: int,
    user_input: str,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
    err: str,
):
    # Recover from aborted transactions (e.g. deadlock/serialization failures) before
    # attempting to persist terminal failure state.
    try:
        cur.connection.rollback()
    except Exception:
        pass

    recovery_cur = cur.connection.cursor()
    try:
        validation_report = build_runtime_failure_validation_report(err)
        recovery_action = build_runtime_failure_recovery_action(err)
        update_task_delivery_records(
            recovery_cur,
            task_id,
            validation_report=validation_report,
            recovery_action=recovery_action,
        )
        persist_task_runtime_state(
            recovery_cur,
            task_id,
            user_input,
            status="failed",
            current_step=None,
            step_context=step_context,
            var_context=var_context,
            step_outputs=step_outputs,
            task_error_message=err,
            checkpoint_error=err,
        )
        update_task_trace_status(recovery_cur, task_id, status="failed", error_summary=err)
        insert_audit_log(
            recovery_cur,
            "task.runtime_failed",
            "worker",
            task_id,
            {
                "error": err[:300],
                "recovery_action": recovery_action,
            },
        )
        recovery_cur.connection.commit()
    finally:
        recovery_cur.close()

    try:
        postrun_cur = cur.connection.cursor()
        try:
            maybe_create_task_postrun_agent_records(postrun_cur, task_id, user_input)
        finally:
            postrun_cur.close()
    except Exception as exc:
        try:
            cur.connection.rollback()
        except Exception:
            pass
        logger.warning("task postrun agent capture failed task_id=%s error=%s", task_id, exc)


def start_task_execution(cur, task_id: int, user_input: str):
    ensure_task_trace(cur, task_id, user_input)
    persist_task_runtime_state(
        cur,
        task_id,
        user_input,
        status="running",
        current_step=None,
        step_context={},
        var_context={},
        step_outputs=[],
        task_error_message=None,
        checkpoint_error="",
    )
    update_task_trace_status(cur, task_id, status="running", error_summary="")


def start_step_execution(cur, task_id: int, step_order: int):
    set_step_running(cur, task_id, step_order)
    update_task_progress(cur, task_id, current_step=step_order)
    cur.connection.commit()


def record_legacy_step_result(
    cur,
    task_id: int,
    step_order: int,
    output_text: str,
    ok: bool,
):
    set_step_result(
        cur,
        task_id,
        step_order,
        status="completed" if ok else "failed",
        tool_name=None,
        input_payload=None,
        output_payload=output_text,
        output_data=None,
        error_message="" if ok else output_text,
        error_strategy="fail",
    )
    cur.connection.commit()


def persist_legacy_step_runtime_state(
    cur,
    task_id: int,
    user_input: str,
    step_order: int,
    output_text: str,
    step_outputs: list[str],
):
    step_outputs.append(output_text)
    persist_task_runtime_state(
        cur,
        task_id,
        user_input,
        status="running",
        current_step=step_order,
        step_context={},
        var_context={},
        step_outputs=step_outputs,
        task_error_message=None,
        checkpoint_error="",
        update_status_row=False,
    )


def run_legacy_plan(
    cur,
    task_id: int,
    user_input: str,
    step_names: list[str],
    existing_rows: list[dict],
    model_route_overrides: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[str], dict[int, dict], dict[str, Any]]:
    return run_legacy_plan_impl(
        cur=cur,
        task_id=task_id,
        user_input=user_input,
        step_names=step_names,
        existing_rows=existing_rows,
        model_route_overrides=model_route_overrides,
        create_legacy_steps=create_legacy_steps,
        maybe_initialize_task_runtime_agent_records=maybe_initialize_task_runtime_agent_records,
        start_step_execution=start_step_execution,
        run_legacy_step=run_legacy_step,
        record_legacy_step_result=record_legacy_step_result,
        persist_legacy_step_runtime_state=persist_legacy_step_runtime_state,
        maybe_dispatch_task_runtime_specialists=maybe_dispatch_task_runtime_specialists,
    )


def select_task_plan_source(
    cur,
    task_id: int,
    user_input: str,
    *,
    skill_invocation: dict[str, Any] | None = None,
    task_intent: dict[str, Any] | None = None,
    deliverable_spec: dict[str, Any] | None = None,
    model_route_overrides: dict[str, dict[str, Any]] | None = None,
) -> TaskPlanSelection:
    return select_task_plan_source_impl(
        cur=cur,
        task_id=task_id,
        user_input=user_input,
        skill_invocation=skill_invocation,
        task_intent=task_intent,
        deliverable_spec=deliverable_spec,
        model_route_overrides=model_route_overrides,
        get_task_steps=get_task_steps,
        build_structured_steps_from_rows=build_structured_steps_from_rows,
        update_task_trace_status=update_task_trace_status,
        load_skill_definition=load_skill_definition,
        extract_skill_arg_keys=extract_skill_arg_keys,
        create_skill_trace=create_skill_trace,
        build_skill_plan=build_skill_plan,
        complete_skill_trace=complete_skill_trace,
        build_deliverable_first_plan=build_deliverable_first_plan,
        resolve_task_plan_source=resolve_task_plan_source,
        append_execution_result_closure_steps=append_execution_result_closure_steps,
    )


def prepare_executor_context(
    cur,
    task_id: int,
    user_input: str,
    plan_selection: TaskPlanSelection,
) -> tuple[dict[int, dict], dict[str, Any], list[str], str]:
    return prepare_executor_context_impl(
        cur=cur,
        task_id=task_id,
        user_input=user_input,
        plan_selection=plan_selection,
        create_structured_steps=create_structured_steps,
        get_task_steps=get_task_steps,
        build_structured_steps_from_rows=build_structured_steps_from_rows,
        hydrate_contexts_from_steps=hydrate_contexts_from_steps,
        persist_task_runtime_state=persist_task_runtime_state,
        maybe_initialize_task_runtime_agent_records=maybe_initialize_task_runtime_agent_records,
    )


def run_planned_execution(
    cur,
    task_id: int,
    user_input: str,
    plan_selection: TaskPlanSelection,
    claim_heartbeat: Optional[TaskClaimHeartbeat],
    model_route_overrides: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[str], dict[int, dict], dict[str, Any]]:
    return run_planned_execution_impl(
        cur=cur,
        task_id=task_id,
        user_input=user_input,
        plan_selection=plan_selection,
        claim_heartbeat=claim_heartbeat,
        model_route_overrides=model_route_overrides,
        prepare_executor_context_fn=prepare_executor_context,
        get_task_steps=get_task_steps,
        build_structured_steps_from_rows=build_structured_steps_from_rows,
        run_structured_step=run_structured_step,
        maybe_dispatch_task_runtime_specialists=maybe_dispatch_task_runtime_specialists,
        fallback_legacy_steps=fallback_legacy_steps,
        run_legacy_plan_fn=run_legacy_plan,
    )


def normalize_step_execution_request(step: dict) -> StepExecutionRequest:
    tool_name = str(step.get("tool") or "").strip()
    return {
        "step_order": int(step.get("step_order")),
        "current_status": str(step.get("status") or "pending"),
        "tool_name": tool_name,
        "raw_input": step.get("input") or {},
        "run_if": step.get("run_if"),
        "skip_if": step.get("skip_if"),
        "error_strategy": str(step.get("error_strategy") or "fail"),
        "max_retries": int(step.get("max_retries") or default_max_retries_for_tool(tool_name)),
        "retry_count": int(step.get("retry_count") or 0),
    }


def enrich_step_execution_request(
    execution_request: StepExecutionRequest,
    step: dict,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
) -> EnrichedStepExecutionRequest:
    enriched = dict(execution_request)
    tool_name = str(enriched["tool_name"])
    raw_input = enriched["raw_input"]
    enriched["effective_retry_count"] = int(enriched["retry_count"])
    enriched["effective_max_retries"] = int(enriched["max_retries"])

    should_run, skip_reason = should_run_step(step, step_context, var_context)
    enriched["should_run"] = should_run
    enriched["skip_reason"] = skip_reason

    if should_run:
        resolved_input = resolve_structured_step_input(tool_name, raw_input, step_context, var_context)
        if tool_name == "web_search":
            resolved_input = normalize_web_search_input(resolved_input)
        if tool_name == "http_request":
            resolved_input = normalize_http_request_input(resolved_input)
        validate_input_value(tool_name, resolved_input)
        enriched["resolved_input"] = resolved_input
        approval_required, approval_reason = should_require_approval(tool_name, resolved_input)
        enriched["approval_required"] = approval_required
        enriched["approval_reason"] = approval_reason
    else:
        enriched["resolved_input"] = None
        enriched["approval_required"] = False
        enriched["approval_reason"] = ""

    return enriched


def execute_prepared_step_request(
    cur,
    task_id: int,
    user_input: str,
    step: dict,
    execution_request: EnrichedStepExecutionRequest,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
    claim_heartbeat: Optional[TaskClaimHeartbeat],
    model_route_overrides: dict[str, dict[str, Any]] | None = None,
    step_trace_id: int | None = None,
    tool_trace_id: int | None = None,
) -> tuple[Optional[dict], int]:
    step_order = int(execution_request["step_order"])
    tool_name = str(execution_request["tool_name"])
    raw_input = execution_request["raw_input"]
    run_if = execution_request["run_if"]
    skip_if = execution_request["skip_if"]
    error_strategy = str(execution_request["error_strategy"])
    should_run = bool(execution_request["should_run"])
    skip_reason = str(execution_request["skip_reason"])
    max_retries = int(execution_request["effective_max_retries"])
    retry_count = int(execution_request["effective_retry_count"])

    if not should_run:
        record_skipped_step(
            cur,
            task_id,
            step_order,
            tool_name,
            raw_input,
            run_if,
            skip_if,
            skip_reason,
            error_strategy,
            user_input,
            step_context,
            var_context,
            step_outputs,
            step_trace_id=step_trace_id,
            tool_trace_id=tool_trace_id,
        )
        return None, retry_count

    resolved_input = execution_request["resolved_input"]
    enforce_step_approval(
        cur,
        task_id,
        step_order,
        step,
        tool_name,
        resolved_input,
        user_input,
        step_context,
        var_context,
        step_outputs,
        step_trace_id=step_trace_id,
        tool_trace_id=tool_trace_id,
        approval_required=bool(execution_request["approval_required"]),
        approval_reason=str(execution_request["approval_reason"]),
    )
    result, retry_count = execute_step_with_retries(
        cur,
        task_id,
        step_order,
        tool_name,
        resolved_input,
        step_context,
        var_context,
        max_retries,
        retry_count,
        claim_heartbeat,
        user_input,
        step_outputs,
        model_route_overrides,
    )
    return result, retry_count


def route_structured_step_outcome(
    cur,
    task_id: int,
    user_input: str,
    execution_request: EnrichedStepExecutionRequest,
    result: dict,
    retry_count: int,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
    step_trace_id: int | None = None,
    tool_trace_id: int | None = None,
):
    step_order = int(execution_request["step_order"])
    tool_name = str(execution_request["tool_name"])
    error_strategy = str(execution_request["error_strategy"])
    resolved_input = execution_request["resolved_input"]
    ok = bool(result["ok"])
    status = "completed" if ok else "failed"

    logger.info(
        "step finished task_id=%s step_order=%s tool=%s status=%s retry_count=%s",
        task_id,
        step_order,
        tool_name,
        status,
        retry_count,
    )

    if ok:
        finalize_structured_step_success(
            cur,
            task_id,
            step_order,
            tool_name,
            resolved_input,
            error_strategy,
            result,
            retry_count,
            user_input,
            step_context,
            var_context,
            step_outputs,
            step_trace_id=step_trace_id,
            tool_trace_id=tool_trace_id,
        )
        return

    if error_strategy == "continue":
        finalize_structured_step_continue(
            cur,
            task_id,
            step_order,
            tool_name,
            resolved_input,
            error_strategy,
            result,
            user_input,
            step_context,
            var_context,
            step_outputs,
            step_trace_id=step_trace_id,
            tool_trace_id=tool_trace_id,
        )
        return

    raise RuntimeError(f"Step {step_order} failed: {result['error']}")


def begin_structured_step_execution(
    cur,
    task_id: int,
    user_input: str,
    step: dict,
    execution_request: StepExecutionRequest,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
    claim_heartbeat: Optional[TaskClaimHeartbeat],
) -> tuple[bool, int | None, int | None]:
    step_order = int(execution_request["step_order"])
    if claim_heartbeat is not None:
        claim_heartbeat.assert_owned()

    if get_task_control_status(task_id) == "interrupt_requested":
        interrupt_task_if_requested(cur, task_id, user_input, step_order, step_context, var_context, step_outputs)

    current_status = str(execution_request["current_status"])
    if current_status == "completed":
        return False, None, None
    if current_status == "failed":
        raise RuntimeError(f"Step {step_order} already failed")

    tool_name = str(execution_request["tool_name"])
    retry_count = int(execution_request["retry_count"])
    max_retries = int(execution_request["max_retries"])
    logger.info(
        "step starting task_id=%s step_order=%s tool=%s retry_count=%s max_retries=%s",
        task_id,
        step_order,
        tool_name,
        retry_count,
        max_retries,
    )
    start_step_execution(cur, task_id, step_order)
    step_trace_id, tool_trace_id = create_step_and_tool_trace(
        cur,
        task_id=task_id,
        task_step_id=int(step.get("id") or 0) or None,
        step_order=step_order,
        step_name=str(step.get("title") or f"步骤 {step_order}"),
        tool_name=tool_name,
        input_payload=execution_request["raw_input"],
        retry_count=retry_count,
        max_retries=max_retries,
    )
    set_current_trace_context(task_id=task_id, step_id=int(step.get("id") or 0) or None, step_trace_id=step_trace_id)
    return True, step_trace_id, tool_trace_id


def process_structured_step_request(
    cur,
    task_id: int,
    user_input: str,
    step: dict,
    execution_request: StepExecutionRequest,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
    claim_heartbeat: Optional[TaskClaimHeartbeat],
    model_route_overrides: dict[str, dict[str, Any]] | None = None,
    step_trace_id: int | None = None,
    tool_trace_id: int | None = None,
) -> tuple[EnrichedStepExecutionRequest, Optional[dict], int]:
    tool_name = str(execution_request["tool_name"])
    if tool_name not in SUPPORTED_TOOLS:
        raise ValueError(f"不支持的工具: {tool_name}")
    ensure_tool_enabled(tool_name)

    execution_request = enrich_step_execution_request(execution_request, step, step_context, var_context)
    result, retry_count = execute_prepared_step_request(
        cur,
        task_id,
        user_input,
        step,
        execution_request,
        step_context,
        var_context,
        step_outputs,
        claim_heartbeat,
        model_route_overrides,
    )
    if result is None:
        return execution_request, None, int(execution_request["effective_retry_count"])
    return execution_request, result, retry_count


def run_structured_step(
    cur,
    task_id: int,
    user_input: str,
    step: dict,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
    claim_heartbeat: Optional[TaskClaimHeartbeat],
    model_route_overrides: dict[str, dict[str, Any]] | None = None,
) -> bool:
    execution_request = normalize_step_execution_request(step)
    should_run, step_trace_id, tool_trace_id = begin_structured_step_execution(
        cur,
        task_id,
        user_input,
        step,
        execution_request,
        step_context,
        var_context,
        step_outputs,
        claim_heartbeat,
    )
    if not should_run:
        return False

    clear_current_trace_context()
    set_current_trace_context(task_id=task_id, step_id=int(step.get("id") or 0) or None, step_trace_id=step_trace_id)
    try:
        complete_structured_step_execution(
            cur,
            task_id,
            user_input,
            step,
            execution_request,
            step_context,
            var_context,
            step_outputs,
            claim_heartbeat,
            model_route_overrides,
            step_trace_id=step_trace_id,
            tool_trace_id=tool_trace_id,
        )
    finally:
        clear_current_trace_context()
    return True


def process_task(task: dict, claim_heartbeat: Optional[TaskClaimHeartbeat] = None):
    task_id = task["id"]
    user_input = task["user_input"]
    planner_user_input = augment_user_input_with_memory_context(user_input, task)
    task_model_route_overrides = extract_task_model_route_overrides(task)
    task_skill_invocation = extract_task_skill_invocation(task)
    task_intent = extract_task_intent(task)
    task_deliverable_spec = extract_deliverable_spec(task)

    conn = get_conn()
    cur = conn.cursor()

    try:
        logger.info("task started id=%s user_input=%s", task_id, str(user_input)[:200])
        ensure_task_steps_columns(cur)
        ensure_approvals_table(cur)
        seed_default_tool_registry(cur)
        seed_default_model_providers(cur)
        seed_default_model_routes(cur)
        latest_evaluator = fetch_latest_evaluator_feedback(cur, task_id)
        planner_user_input = augment_user_input_with_runtime_feedback(planner_user_input, latest_evaluator)
        if bool(task_intent.get("needs_clarification")) or bool(((task_deliverable_spec.get("clarify") or {}).get("blocking"))):
            fail_task_for_missing_clarification(
                cur,
                task_id,
                planner_user_input,
                task_intent=task_intent,
                deliverable_spec=task_deliverable_spec,
            )
            logger.info("task blocked pending clarification id=%s", task_id)
            return
        start_task_execution(cur, task_id, planner_user_input)

        set_current_trace_context(task_id=task_id)
        try:
            plan_selection = select_task_plan_source(
                cur,
                task_id,
                planner_user_input,
                skill_invocation=task_skill_invocation,
                task_intent=task_intent,
                deliverable_spec=task_deliverable_spec,
                model_route_overrides=task_model_route_overrides,
            )
        finally:
            clear_current_trace_context()
        step_outputs, step_context, var_context = run_planned_execution(
            cur,
            task_id,
            planner_user_input,
            plan_selection,
            claim_heartbeat,
            task_model_route_overrides,
        )

        finalize_task_success(
            cur,
            task_id,
            planner_user_input,
            step_outputs,
            step_context if 'step_context' in locals() else {},
            var_context if 'var_context' in locals() else {},
        )

    except ApprovalRequired as e:
        conn.commit()
        maybe_dispatch_task_runtime_specialists(task_id, reason="waiting_approval")
        logger.info("task paused for approval id=%s reason=%s", task_id, str(e))
    except InterruptRequested as e:
        conn.commit()
        maybe_dispatch_task_runtime_specialists(task_id, reason="interrupt_requested")
        logger.info("task paused by interrupt id=%s reason=%s", task_id, str(e))
    except AutoRecoveryScheduled as e:
        conn.commit()
        logger.info("task auto recovery queued id=%s reason=%s", task_id, str(e))
    except ClaimLostError as e:
        logger.warning("task stopped because claim was lost id=%s reason=%s", task_id, str(e))
    except Exception as e:
        finalize_task_failure(
            cur,
            task_id,
            planner_user_input,
            step_context if 'step_context' in locals() else {},
            var_context if 'var_context' in locals() else {},
            step_outputs if 'step_outputs' in locals() else [],
            str(e),
        )
        logger.exception("task failed id=%s error=%s", task_id, e)
    finally:
        cur.close()
        conn.close()


def fetch_task_by_id(task_id: int) -> Optional[dict]:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT *
            FROM task_runs
            WHERE id = %s;
            """,
            (task_id,),
        )
        return cur.fetchone()
    finally:
        cur.close()
        conn.close()


def fetch_next_pending_task():
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT *
            FROM task_runs
            WHERE status = 'pending'
            ORDER BY id ASC
            LIMIT 1;
            """
        )
        row = cur.fetchone()
        return row
    finally:
        cur.close()
        conn.close()


def process_agent_run(agent_run: dict):
    agent_run_id = int(agent_run["id"])
    task_id = int(agent_run["task_run_id"])
    execution_mode = str(agent_run.get("execution_mode") or "").strip()
    tool_profile = str(agent_run.get("assigned_tool_profile") or "").strip()
    execution_request = parse_jsonish(agent_run.get("execution_request_json"), {})
    assigned_step_orders = parse_jsonish(agent_run.get("assigned_step_orders_json"), [])

    if agent_run.get("role") != "specialist":
        logger.info("skip non-specialist agent run id=%s", agent_run_id)
        return
    if execution_mode not in {"worker_readonly_v1", AUTO_STAGE5_RUNTIME_EXECUTION_MODE} or tool_profile not in MAINLINE_SPECIALIST_TOOL_PROFILES:
        logger.info("skip unsupported agent run id=%s mode=%s tool_profile=%s", agent_run_id, execution_mode, tool_profile)
        return

    conn = get_conn()
    cur = conn.cursor()
    try:
        ensure_agent_tables(cur)
        ensure_evaluator_tables(cur)
        ensure_task_steps_columns(cur)
        ensure_audit_logs_table(cur)

        cur.execute("SELECT * FROM task_runs WHERE id = %s;", (task_id,))
        task_row = cur.fetchone()
        if not task_row:
            raise RuntimeError(f"task not found for agent run {agent_run_id}")
        checkpoint_path = str(task_row.get("checkpoint_path") or "").strip()

        cur.execute(
            """
            SELECT step_order, step_name, status, tool_name, input_payload, output_payload, error_message
            FROM task_steps
            WHERE task_id = %s
            ORDER BY step_order ASC;
            """,
            (task_id,),
        )
        step_rows = list(cur.fetchall())

        subtask_type = str(execution_request.get("subtask_type") or "readonly_step_digest").strip() or "readonly_step_digest"
        selected_steps = [
            {
                "step_order": int(row["step_order"]),
                "step_name": row["step_name"],
                "status": row["status"],
                "tool_name": row.get("tool_name") or "",
                "input_excerpt": str(row.get("input_payload") or "")[:180],
                "output_excerpt": str(row.get("output_payload") or "")[:220],
                "error_excerpt": str(row.get("error_message") or "")[:160],
            }
            for row in step_rows
            if not assigned_step_orders or int(row["step_order"]) in {int(item) for item in assigned_step_orders}
        ]
        if not selected_steps:
            selected_steps = [
                {
                    "step_order": 0,
                    "step_name": "task-result-fallback",
                    "status": task_row.get("status") or "unknown",
                    "tool_name": "",
                    "input_excerpt": build_task_display_input_excerpt(task_row),
                    "output_excerpt": build_task_result_excerpt(task_row),
                    "error_excerpt": str(task_row.get("error_message") or "")[:160],
                }
            ]

        completed_names = [str(item.get("step_name") or "") for item in selected_steps if item.get("status") == "completed"]
        failed_names = [str(item.get("step_name") or "") for item in selected_steps if item.get("status") == "failed"]
        pending_names = [str(item.get("step_name") or "") for item in selected_steps if item.get("status") not in {"completed", "failed"}]

        cur.execute(
            """
            UPDATE agent_runs
            SET status = 'running',
                started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                completed_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s;
            """,
            (agent_run_id,),
        )
        create_agent_message(
            cur,
            task_id,
            agent_run_id,
            "specialist",
            "manager",
            "progress",
            {
                "execution_mode": execution_mode,
                "status": "running",
                "summary": "worker started specialist execution",
                "assigned_step_orders": assigned_step_orders,
            },
        )

        cur.execute("SELECT id, version FROM agent_artifacts WHERE id = %s;", (agent_run.get("output_artifact_id"),))
        existing_output = cur.fetchone()
        next_version = int(existing_output.get("version") or 1) + 1 if existing_output else 1

        if subtask_type == RESTRICTED_SPECIALIST_SUBTASK_TYPE:
            source = execution_request.get("source") or {}
            command = str(source.get("command") or "pwd").strip() or "pwd"
            restricted_tools = list(source.get("restricted_tools") or [])
            result = tool_shell_exec(command)
            if not result.get("ok"):
                raise RuntimeError(result.get("error") or "restricted shell probe failed")
            command_output = (result.get("output_data") or {}).get("stdout") or ""
            execution_result = {
                "execution_mode": execution_mode,
                "subtask_type": subtask_type,
                "status": "completed",
                "request_snapshot": execution_request,
                "restricted_tool_profile": tool_profile,
                "restricted_tools": restricted_tools,
                "probe_command": command,
                "probe_result": {
                    "returncode": int(((result.get("output_data") or {}).get("returncode")) or 0),
                    "stdout_excerpt": str(command_output)[:400],
                },
                "observations": [
                    f"restricted_tools={','.join(restricted_tools) if restricted_tools else '(none)'}",
                    f"probe_command={command}",
                ],
            }
            draft_payload = {
                "protocol_version": "multi-agent-v1",
                "task_id": task_id,
                "agent_run_id": agent_run_id,
                "summary": "worker executed restricted shell probe",
                "output": {
                    "slot": execution_request.get("slot"),
                    "objective": execution_request.get("objective") or "",
                    "subtask": {
                        "type": subtask_type,
                        "execution_mode": execution_mode,
                        "assigned_step_orders": assigned_step_orders,
                    },
                    "execution_request": execution_request,
                    "execution_result": execution_result,
                },
            }
            result_summary = "worker specialist restricted shell probe completed"
        elif subtask_type == "readonly_source_snapshot":
            source = execution_request.get("source") or {}
            source_kind = str(source.get("kind") or "").strip()
            source_path = str(source.get("path") or "").strip()
            source_json_path = str(source.get("json_path") or "").strip()
            dir_limit = max(1, min(int(source.get("dir_limit") or 20), 200))
            source_result: dict[str, Any]
            if source_kind == "text_file":
                result = tool_file_read(source_path)
                if not result.get("ok"):
                    raise RuntimeError(result.get("error") or "text_file snapshot failed")
                raw_text = str(((result.get("output_data") or {}).get("raw_text")) or "")
                excerpt = raw_text[:400]
                source_result = {
                    "kind": source_kind,
                    "path": source_path,
                    "excerpt": excerpt,
                    "char_count": len(raw_text),
                }
                observations = [
                    f"text_file chars={len(raw_text)}",
                    f"excerpt={excerpt[:120]}",
                ]
            elif source_kind == "json_file":
                result = tool_read_json(source_path)
                if not result.get("ok"):
                    raise RuntimeError(result.get("error") or "json_file snapshot failed")
                parsed_json = ((result.get("output_data") or {}).get("json"))
                extracted_value = parsed_json
                if source_json_path:
                    extract_result = tool_json_extract(parsed_json, source_json_path)
                    if not extract_result.get("ok"):
                        raise RuntimeError(extract_result.get("error") or "json_extract failed")
                    extracted_value = (extract_result.get("output_data") or {}).get("value")
                source_result = {
                    "kind": source_kind,
                    "path": source_path,
                    "json_path": source_json_path,
                    "selected_value": extracted_value,
                }
                observations = [
                    f"json_file path={source_path}",
                    f"json_path={source_json_path or '(root)'}",
                ]
            elif source_kind == "directory":
                result = tool_list_dir(source_path)
                if not result.get("ok"):
                    raise RuntimeError(result.get("error") or "directory snapshot failed")
                entries = list(((result.get("output_data") or {}).get("entries")) or [])[:dir_limit]
                source_result = {
                    "kind": source_kind,
                    "path": source_path,
                    "entries": entries,
                    "entry_count": len(entries),
                }
                observations = [
                    f"directory entries={len(entries)}",
                    *(entries[:3]),
                ]
            else:
                raise RuntimeError(f"unsupported readonly_source_snapshot kind: {source_kind}")

            execution_result = {
                "execution_mode": execution_mode,
                "subtask_type": subtask_type,
                "status": "completed",
                "request_snapshot": execution_request,
                "source": source_result,
                "observations": observations,
            }
            draft_payload = {
                "protocol_version": "multi-agent-v1",
                "task_id": task_id,
                "agent_run_id": agent_run_id,
                "summary": "worker executed readonly source snapshot",
                "output": {
                    "slot": execution_request.get("slot"),
                    "objective": execution_request.get("objective") or "",
                    "subtask": {
                        "type": subtask_type,
                        "execution_mode": execution_mode,
                        "assigned_step_orders": assigned_step_orders,
                    },
                    "execution_request": execution_request,
                    "execution_result": execution_result,
                },
            }
            result_summary = "worker specialist readonly source snapshot completed"
        elif subtask_type == "readonly_task_snapshot":
            latest_evaluator = {}
            cur.execute(
                """
                SELECT decision, score, failure_reason, failure_stage, recommendation, proposal_json, created_at
                FROM evaluator_runs
                WHERE task_run_id = %s
                ORDER BY id DESC
                LIMIT 1;
                """,
                (task_id,),
            )
            evaluator_row = cur.fetchone()
            if evaluator_row:
                latest_evaluator = {
                    "decision": evaluator_row.get("decision") or "",
                    "score": int(evaluator_row.get("score") or 0),
                    "failure_reason": evaluator_row.get("failure_reason") or "none",
                    "failure_stage": evaluator_row.get("failure_stage") or "none",
                    "recommendation": evaluator_row.get("recommendation") or "",
                    "workflow_proposal": parse_jsonish(evaluator_row.get("proposal_json"), {}),
                    "created_at": evaluator_row.get("created_at").isoformat() if evaluator_row.get("created_at") else None,
                }

            latest_review = {}
            cur.execute(
                """
                SELECT content_json, version, created_at
                FROM agent_artifacts
                WHERE task_run_id = %s AND artifact_type = 'review'
                ORDER BY id DESC
                LIMIT 1;
                """,
                (task_id,),
            )
            review_row = cur.fetchone()
            if review_row:
                review_content = parse_jsonish(review_row.get("content_json"), {})
                latest_review = {
                    "decision": review_content.get("decision") or "",
                    "quality_score": review_content.get("quality_score"),
                    "failure_reason": review_content.get("failure_reason") or "none",
                    "failure_stage": review_content.get("failure_stage") or "none",
                    "version": int(review_row.get("version") or 1),
                    "created_at": review_row.get("created_at").isoformat() if review_row.get("created_at") else None,
                }

            checkpoint_summary = {
                "exists": bool(checkpoint_path),
                "path": checkpoint_path,
            }
            if checkpoint_path:
                checkpoint_summary["label"] = Path(checkpoint_path).name

            execution_result = {
                "execution_mode": execution_mode,
                "subtask_type": subtask_type,
                "status": "completed",
                "request_snapshot": execution_request,
                "task_snapshot": {
                    "task_status": task_row.get("status") or "unknown",
                    "result_excerpt": str(task_row.get("result") or "")[:280],
                    "error_excerpt": str(task_row.get("error_message") or "")[:200],
                    "checkpoint": checkpoint_summary,
                    "step_status_counts": {
                        "completed": len(completed_names),
                        "failed": len(failed_names),
                        "other": len(pending_names),
                    },
                },
                "latest_evaluator": latest_evaluator,
                "latest_review": latest_review,
                "observations": [
                    f"task status={task_row.get('status') or 'unknown'}",
                    f"checkpoint={'yes' if checkpoint_path else 'no'}",
                    f"completed_steps={len(completed_names)} failed_steps={len(failed_names)}",
                ],
            }
            draft_payload = {
                "protocol_version": "multi-agent-v1",
                "task_id": task_id,
                "agent_run_id": agent_run_id,
                "summary": "worker executed readonly task snapshot",
                "output": {
                    "slot": execution_request.get("slot"),
                    "objective": execution_request.get("objective") or "",
                    "subtask": {
                        "type": subtask_type,
                        "execution_mode": execution_mode,
                        "assigned_step_orders": assigned_step_orders,
                    },
                    "execution_request": execution_request,
                    "execution_result": execution_result,
                },
            }
            result_summary = "worker specialist readonly task snapshot completed"
        else:
            draft_payload = {
                "protocol_version": "multi-agent-v1",
                "task_id": task_id,
                "agent_run_id": agent_run_id,
                "summary": "worker executed readonly specialist subtask",
                "output": {
                    "slot": execution_request.get("slot"),
                    "objective": execution_request.get("objective") or "",
                    "subtask": {
                        "type": subtask_type,
                        "execution_mode": execution_mode,
                        "assigned_step_orders": assigned_step_orders,
                    },
                    "execution_request": execution_request,
                    "execution_result": {
                        "execution_mode": execution_mode,
                        "subtask_type": subtask_type,
                        "status": "completed",
                        "request_snapshot": execution_request,
                        "assigned_step_orders": assigned_step_orders,
                        "completed_step_names": completed_names[:6],
                        "failed_step_names": failed_names[:6],
                        "pending_step_names": pending_names[:6],
                        "observations": [
                            f"step#{int(item.get('step_order') or 0)} {item.get('step_name') or ''} -> {item.get('status') or 'unknown'}"
                            for item in selected_steps[:4]
                        ],
                    },
                },
            }
            result_summary = "worker specialist readonly digest completed"
        draft_artifact_id = create_agent_artifact(
            cur,
            task_id,
            agent_run_id,
            "draft",
            "worker specialist draft",
            draft_payload,
            version=next_version,
        )
        create_agent_message(
            cur,
            task_id,
            agent_run_id,
            "specialist",
            "manager",
            "result",
            {
                "execution_mode": execution_mode,
                "status": "completed",
                "artifact_ids": [draft_artifact_id],
                "summary": result_summary,
            },
        )
        cur.execute(
            """
            UPDATE agent_runs
            SET status = 'completed',
                output_artifact_id = %s,
                completed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP,
                error_summary = ''
            WHERE id = %s;
            """,
            (draft_artifact_id, agent_run_id),
        )
        audit_event_type = "agent.worker_execute_demo"
        if execution_mode == AUTO_STAGE5_RUNTIME_EXECUTION_MODE:
            audit_event_type = "agent.mainline_runtime_execute"
        insert_audit_log(
            cur,
            audit_event_type,
            "worker",
            task_id,
            {
                "agent_run_id": agent_run_id,
                "execution_mode": execution_mode,
                "assigned_step_orders": assigned_step_orders,
            },
        )
        if execution_mode == AUTO_STAGE5_RUNTIME_EXECUTION_MODE:
            maybe_refresh_task_runtime_manager_rollup(cur, task_id)
        conn.commit()
        logger.info("worker processed agent run id=%s task_id=%s", agent_run_id, task_id)
    except Exception as exc:
        conn.rollback()
        try:
            cur.execute(
                """
                UPDATE agent_runs
                SET status = 'failed',
                    error_summary = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s;
                """,
                (str(exc), agent_run_id),
            )
            audit_event_type = "agent.worker_execute_failed"
            if execution_mode == AUTO_STAGE5_RUNTIME_EXECUTION_MODE:
                audit_event_type = "agent.mainline_runtime_execute_failed"
            insert_audit_log(
                cur,
                audit_event_type,
                "worker",
                task_id,
                {"agent_run_id": agent_run_id, "error": str(exc)},
            )
            conn.commit()
        except Exception:
            conn.rollback()
        logger.exception("agent run failed id=%s error=%s", agent_run_id, exc)
    finally:
        cur.close()
        conn.close()


def fetch_agent_run_by_id(agent_run_id: int) -> Optional[dict]:
    conn = get_conn()
    cur = conn.cursor()
    try:
        ensure_agent_tables(cur)
        cur.execute(
            """
            SELECT *
            FROM agent_runs
            WHERE id = %s;
            """,
            (agent_run_id,),
        )
        return cur.fetchone()
    finally:
        cur.close()
        conn.close()


def task_claim_key(task_id: int) -> str:
    return f"task_claim:{task_id}"


def agent_run_claim_key(agent_run_id: int) -> str:
    return f"agent_run_claim:{agent_run_id}"


def enqueue_task(task_id: int):
    client = get_redis_client()
    if client is None:
        return
    try:
        client.rpush("task_queue", str(task_id))
    except Exception as exc:
        logger.warning("enqueue task failed task_id=%s error=%s", task_id, exc)


def enqueue_agent_run(agent_run_id: int):
    client = get_redis_client()
    if client is None:
        return
    try:
        client.rpush("agent_run_queue", str(agent_run_id))
    except Exception as exc:
        logger.warning("enqueue agent run failed agent_run_id=%s error=%s", agent_run_id, exc)


def acquire_task_claim(task_id: int, claim_token: str) -> bool:
    client = get_redis_client()
    if client is None:
        return True
    try:
        return bool(client.set(task_claim_key(task_id), claim_token, nx=True, ex=TASK_LOCK_TTL_SECONDS))
    except Exception as exc:
        logger.warning("task claim failed task_id=%s error=%s", task_id, exc)
        return True


def renew_task_claim(task_id: int, claim_token: str) -> bool:
    client = get_redis_client()
    if client is None:
        return True
    try:
        result = client.eval(
            """
            if redis.call('GET', KEYS[1]) == ARGV[1] then
                return redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
            end
            return 0
            """,
            1,
            task_claim_key(task_id),
            claim_token,
            str(TASK_LOCK_TTL_SECONDS),
        )
        return bool(result)
    except Exception as exc:
        logger.warning("renew task claim failed task_id=%s error=%s", task_id, exc)
        return False


def release_task_claim(task_id: int, claim_token: str):
    client = get_redis_client()
    if client is None:
        return
    try:
        client.eval(
            """
            if redis.call('GET', KEYS[1]) == ARGV[1] then
                return redis.call('DEL', KEYS[1])
            end
            return 0
            """,
            1,
            task_claim_key(task_id),
            claim_token,
        )
    except Exception as exc:
        logger.warning("release task claim failed task_id=%s error=%s", task_id, exc)


def has_live_task_claim(task_id: int) -> bool:
    client = get_redis_client()
    if client is None:
        return False
    try:
        return bool(client.exists(task_claim_key(task_id)))
    except Exception as exc:
        logger.warning("check task claim failed task_id=%s error=%s", task_id, exc)
        return False


def acquire_agent_run_claim(agent_run_id: int, claim_token: str) -> bool:
    client = get_redis_client()
    if client is None:
        return True
    try:
        return bool(client.set(agent_run_claim_key(agent_run_id), claim_token, nx=True, ex=TASK_LOCK_TTL_SECONDS))
    except Exception as exc:
        logger.warning("agent run claim failed agent_run_id=%s error=%s", agent_run_id, exc)
        return True


def release_agent_run_claim(agent_run_id: int, claim_token: str):
    client = get_redis_client()
    if client is None:
        return
    try:
        client.eval(
            """
            if redis.call('GET', KEYS[1]) == ARGV[1] then
                return redis.call('DEL', KEYS[1])
            end
            return 0
            """,
            1,
            agent_run_claim_key(agent_run_id),
            claim_token,
        )
    except Exception as exc:
        logger.warning("release agent run claim failed agent_run_id=%s error=%s", agent_run_id, exc)


def dequeue_task(timeout_seconds: int = 2) -> Optional[dict]:
    client = get_redis_client()
    if client is None:
        return None
    try:
        item = client.blpop("task_queue", timeout=timeout_seconds)
    except Exception as exc:
        logger.warning("redis dequeue failed: %s", exc)
        return None

    if not item:
        return None

    _, raw_task_id = item
    try:
        task_id = int(raw_task_id)
    except Exception:
        return None

    task = fetch_task_by_id(task_id)
    if not task or task.get("status") != "pending":
        return None
    return task


def dequeue_agent_run(timeout_seconds: int = 1) -> Optional[dict]:
    client = get_redis_client()
    if client is None:
        return None
    try:
        item = client.blpop("agent_run_queue", timeout=timeout_seconds)
    except Exception as exc:
        logger.warning("redis agent run dequeue failed: %s", exc)
        return None
    if not item:
        return None
    _, raw_agent_run_id = item
    try:
        agent_run_id = int(raw_agent_run_id)
    except Exception:
        return None
    agent_run = fetch_agent_run_by_id(agent_run_id)
    if not agent_run or str(agent_run.get("status") or "") not in {"queued", "running"}:
        return None
    return agent_run


def requeue_stale_running_tasks():
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT id, status, updated_at
            FROM task_runs
            WHERE status IN ('running', 'interrupt_requested')
            ORDER BY id ASC;
            """
        )
        rows = list(cur.fetchall())
        now = datetime.now(timezone.utc)
        for row in rows:
            updated_at = row.get("updated_at")
            if updated_at is None:
                continue
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            age_seconds = (now - updated_at).total_seconds()
            if age_seconds < TASK_STALE_REQUEUE_SECONDS:
                continue
            task_id = int(row["id"])
            if has_live_task_claim(task_id):
                continue

            update_task_status(cur, task_id, "pending", None, "stale running task requeued")
            conn.commit()
            enqueue_task(task_id)
            logger.warning(
                "stale task requeued task_id=%s previous_status=%s age_seconds=%s",
                task_id,
                row.get("status"),
                int(age_seconds),
            )
            record_worker_audit_event(
                "task.stale_requeue",
                task_id,
                {
                    "previous_status": row.get("status"),
                    "age_seconds": int(age_seconds),
                },
            )
    finally:
        cur.close()
        conn.close()


def main():
    logger.info("worker started")
    ensure_runtime_schema_bootstrapped()
    last_stale_check_at = 0.0
    while True:
        try:
            now = time.time()
            if now - last_stale_check_at >= 10:
                requeue_stale_running_tasks()
                last_stale_check_at = now

            agent_run = dequeue_agent_run(timeout_seconds=1)
            if agent_run:
                agent_run_id = int(agent_run["id"])
                claim_token = f"{WORKER_ID}:agent_run:{agent_run_id}:{uuid.uuid4().hex}"
                if not acquire_agent_run_claim(agent_run_id, claim_token):
                    logger.info("agent run already claimed agent_run_id=%s", agent_run_id)
                    continue
                try:
                    process_agent_run(agent_run)
                finally:
                    release_agent_run_claim(agent_run_id, claim_token)
                continue

            task = dequeue_task(timeout_seconds=2)
            if not task:
                task = fetch_next_pending_task()
            if not task:
                continue

            claim_token = f"{WORKER_ID}:{task['id']}:{uuid.uuid4().hex}"
            if not acquire_task_claim(int(task["id"]), claim_token):
                logger.info("task already claimed task_id=%s", task["id"])
                continue

            logger.info("worker picked task id=%s user_input=%s", task["id"], str(task["user_input"])[:200])
            heartbeat = TaskClaimHeartbeat(int(task["id"]), claim_token)
            heartbeat.start()
            try:
                process_task(task, claim_heartbeat=heartbeat)
            finally:
                heartbeat.stop()
                release_task_claim(int(task["id"]), claim_token)

        except Exception as e:
            logger.exception("worker loop error: %s", e)
            time.sleep(2)


if __name__ == "__main__":
    main()
