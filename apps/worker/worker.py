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
from functools import partial
from typing import Any, Optional, TypedDict

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
from task_lifecycle_runtime import (
    finalize_task_failure as finalize_task_failure_impl,
    finalize_task_success as finalize_task_success_impl,
    persist_task_runtime_state as persist_task_runtime_state_impl,
    persist_legacy_step_runtime_state as persist_legacy_step_runtime_state_impl,
    record_legacy_step_result as record_legacy_step_result_impl,
    start_step_execution as start_step_execution_impl,
    start_task_execution as start_task_execution_impl,
)
from task_processing_runtime import process_task as process_task_impl
from structured_step_runtime import (
    begin_structured_step_execution as begin_structured_step_execution_impl,
    complete_structured_step_execution as complete_structured_step_execution_impl,
    execute_prepared_step_request as execute_prepared_step_request_impl,
    finalize_structured_step_continue as finalize_structured_step_continue_impl,
    finalize_structured_step_success as finalize_structured_step_success_impl,
    persist_structured_step_outcome as persist_structured_step_outcome_impl,
    persist_structured_step_runtime_state as persist_structured_step_runtime_state_impl,
    process_structured_step_request as process_structured_step_request_impl,
    record_skipped_step as record_skipped_step_impl,
    record_structured_step_exception as record_structured_step_exception_impl,
    route_structured_step_outcome as route_structured_step_outcome_impl,
    run_structured_step as run_structured_step_impl,
)
from multi_agent_runtime import (
    augment_user_input_with_runtime_feedback as augment_user_input_with_runtime_feedback_impl,
    build_mainline_specialist_specs as build_mainline_specialist_specs_impl,
    build_review_criteria as build_review_criteria_impl,
    build_runtime_feedback_context_text as build_runtime_feedback_context_text_impl,
    build_specialist_draft_payload as build_specialist_draft_payload_impl,
    build_specialist_execution_request as build_specialist_execution_request_impl,
    build_specialist_step_partitions as build_specialist_step_partitions_impl,
    build_workflow_proposal as build_workflow_proposal_impl,
    create_agent_artifact as create_agent_artifact_impl,
    create_agent_message as create_agent_message_impl,
    create_agent_run as create_agent_run_impl,
    create_evaluator_run as create_evaluator_run_impl,
    derive_evaluator_failure_profile as derive_evaluator_failure_profile_impl,
    is_mainline_specialist_execution_mode as is_mainline_specialist_execution_mode_impl,
    is_mainline_specialist_tool_profile as is_mainline_specialist_tool_profile_impl,
    maybe_create_task_postrun_agent_records as maybe_create_task_postrun_agent_records_impl,
    maybe_dispatch_task_runtime_specialists as maybe_dispatch_task_runtime_specialists_impl,
    maybe_initialize_task_runtime_agent_records as maybe_initialize_task_runtime_agent_records_impl,
    maybe_refresh_task_runtime_manager_rollup as maybe_refresh_task_runtime_manager_rollup_impl,
    resolve_specialist_fanout_strategy as resolve_specialist_fanout_strategy_impl,
    resolve_reviewer_decision as resolve_reviewer_decision_impl,
)
from planner_runtime import (
    fallback_legacy_steps as fallback_legacy_steps_impl,
    call_deepseek_planner as call_deepseek_planner_impl,
    call_planner_with_retries as call_planner_with_retries_impl,
    plan_task as plan_task_impl,
    resolve_task_plan_source as resolve_task_plan_source_impl2,
)
from governance_runtime import (
    ensure_model_providers_table as ensure_model_providers_table_impl,
    ensure_model_routes_table as ensure_model_routes_table_impl,
    ensure_risk_policies_table as ensure_risk_policies_table_impl,
    ensure_tool_enabled as ensure_tool_enabled_impl,
    ensure_tool_registry_table as ensure_tool_registry_table_impl,
    get_model_provider_client as get_model_provider_client_impl,
    get_model_provider_config as get_model_provider_config_impl,
    get_model_route_config as get_model_route_config_impl,
    get_tool_registry_entry as get_tool_registry_entry_impl,
    load_model_provider_settings as load_model_provider_settings_impl,
    load_model_route_settings as load_model_route_settings_impl,
    load_risk_policy_settings as load_risk_policy_settings_impl,
    load_tool_registry_settings as load_tool_registry_settings_impl,
    seed_default_model_providers as seed_default_model_providers_impl,
    seed_default_model_routes as seed_default_model_routes_impl,
    seed_default_risk_policies as seed_default_risk_policies_impl,
    seed_default_tool_registry as seed_default_tool_registry_impl,
    serialize_model_route_runtime_info as serialize_model_route_runtime_info_impl,
    snapshot_model_route_config as snapshot_model_route_config_impl,
)
from trace_runtime import (
    clear_current_trace_context as clear_current_trace_context_impl,
    complete_skill_trace as complete_skill_trace_impl,
    complete_step_and_tool_trace as complete_step_and_tool_trace_impl,
    create_skill_trace as create_skill_trace_impl,
    create_step_and_tool_trace as create_step_and_tool_trace_impl,
    ensure_task_trace as ensure_task_trace_impl,
    get_current_trace_context as get_current_trace_context_impl,
    record_model_trace as record_model_trace_impl,
    set_current_trace_context as set_current_trace_context_impl,
    update_task_trace_status as update_task_trace_status_impl,
)
from memory_runtime import (
    build_task_result_excerpt as build_task_result_excerpt_impl,
    build_task_summary_memory_content as build_task_summary_memory_content_impl,
    capture_session_memory_for_completed_task as capture_session_memory_for_completed_task_impl,
    extract_marked_clauses as extract_marked_clauses_impl,
    infer_task_memories as infer_task_memories_impl,
    rebuild_session_state_from_worker as rebuild_session_state_from_worker_impl,
)
from heuristic_planner_runtime import (
    infer_structured_steps_from_user_input as infer_structured_steps_from_user_input_impl,
)
from approval_runtime import (
    create_step_approval as create_step_approval_impl,
    get_step_approval as get_step_approval_impl,
    set_step_waiting_approval as set_step_waiting_approval_impl,
    should_require_approval as should_require_approval_impl,
)
from tool_runtime import (
    dedupe_search_results as dedupe_search_results_impl,
    execute_mcp_tool as execute_mcp_tool_impl,
    execute_tool as execute_tool_impl,
    resolve_hostname_ips as resolve_hostname_ips_impl,
    summarize_search_results as summarize_search_results_impl,
    tool_http_request as tool_http_request_impl,
    tool_web_search as tool_web_search_impl,
    validate_http_url as validate_http_url_impl,
    validate_shell_command as validate_shell_command_impl,
    web_search_duckduckgo as web_search_duckduckgo_impl,
    web_search_tavily as web_search_tavily_impl,
)
from local_tool_runtime import (
    build_group_output_text as build_group_output_text_impl,
    evaluate_single_condition_payload as evaluate_single_condition_payload_impl,
    tool_file_read as tool_file_read_impl,
    tool_file_write as tool_file_write_impl,
    tool_if_condition as tool_if_condition_impl,
    tool_if_condition_group as tool_if_condition_group_impl,
    tool_json_extract as tool_json_extract_impl,
    tool_list_dir as tool_list_dir_impl,
    tool_read_json as tool_read_json_impl,
    tool_set_var as tool_set_var_impl,
    tool_template_render as tool_template_render_impl,
    tool_write_json as tool_write_json_impl,
)
from agent_run_runtime import process_agent_run as process_agent_run_impl
from queue_runtime import (
    acquire_agent_run_claim as acquire_agent_run_claim_impl,
    acquire_task_claim as acquire_task_claim_impl,
    dequeue_agent_run as dequeue_agent_run_impl,
    dequeue_task as dequeue_task_impl,
    enqueue_agent_run as enqueue_agent_run_impl,
    enqueue_task as enqueue_task_impl,
    fetch_next_pending_task as fetch_next_pending_task_impl,
    fetch_task_by_id as fetch_task_by_id_impl,
    has_live_task_claim as has_live_task_claim_impl,
    release_agent_run_claim as release_agent_run_claim_impl,
    release_task_claim as release_task_claim_impl,
    renew_task_claim as renew_task_claim_impl,
    requeue_stale_running_tasks as requeue_stale_running_tasks_impl,
    task_claim_key as task_claim_key_impl,
    agent_run_claim_key as agent_run_claim_key_impl,
)
from step_request_runtime import (
    ENRICHED_STEP_EXECUTION_REQUEST_EXTRA_FIELDS,
    STEP_EXECUTION_REQUEST_FIELDS,
    EnrichedStepExecutionRequest,
    StepExecutionRequest,
    enrich_step_execution_request as enrich_step_execution_request_impl,
    normalize_http_request_input as normalize_http_request_input_impl,
    normalize_step_execution_request as normalize_step_execution_request_impl,
    normalize_web_search_input as normalize_web_search_input_impl,
    should_run_step as should_run_step_impl,
    validate_input_value as validate_input_value_impl,
    validate_planned_steps as validate_planned_steps_impl,
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
DEFAULT_TOOL_REGISTRY = get_default_tool_registry_settings()
TOOL_REGISTRY_CACHE_TTL_SECONDS = int(os.environ.get("TOOL_REGISTRY_CACHE_TTL_SECONDS", "15"))
DEFAULT_MODEL_ROUTES = get_default_model_route_settings()
DEFAULT_MODEL_PROVIDERS = get_default_model_provider_settings()
MODEL_PROVIDER_CACHE_TTL_SECONDS = int(os.environ.get("MODEL_PROVIDER_CACHE_TTL_SECONDS", "15"))
MODEL_ROUTE_CACHE_TTL_SECONDS = int(os.environ.get("MODEL_ROUTE_CACHE_TTL_SECONDS", "15"))
_runtime_schema_bootstrap_lock = threading.Lock()
_runtime_schema_bootstrap_active = False
_runtime_schema_bootstrapped = False


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
    return build_runtime_feedback_context_text_impl(latest_evaluator)


def augment_user_input_with_runtime_feedback(user_input: str, latest_evaluator: dict[str, Any] | None) -> str:
    return augment_user_input_with_runtime_feedback_impl(user_input, latest_evaluator)


def resolve_specialist_fanout_strategy(
    task_row: dict[str, Any],
    latest_evaluator: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return resolve_specialist_fanout_strategy_impl(
        task_row,
        latest_evaluator,
        extract_task_intent=extract_task_intent,
        extract_deliverable_spec=extract_deliverable_spec,
        auto_stage5_specialist_count=AUTO_STAGE5_SPECIALIST_COUNT,
    )


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


set_current_trace_context = set_current_trace_context_impl
clear_current_trace_context = clear_current_trace_context_impl
get_current_trace_context = get_current_trace_context_impl
ensure_task_trace = partial(
    ensure_task_trace_impl,
    ensure_trace_tables=ensure_trace_tables,
    trim_text=_trim_text,
    safe_json_dumps=safe_json_dumps,
)
update_task_trace_status = partial(
    update_task_trace_status_impl,
    ensure_trace_tables=ensure_trace_tables,
)
create_step_and_tool_trace = partial(
    create_step_and_tool_trace_impl,
    ensure_task_trace_fn=ensure_task_trace,
    safe_json_dumps=safe_json_dumps,
    json_hash=_json_hash,
)
complete_step_and_tool_trace = partial(
    complete_step_and_tool_trace_impl,
    safe_json_dumps=safe_json_dumps,
    trim_text=_trim_text,
)
record_model_trace = partial(
    record_model_trace_impl,
    get_current_trace_context_fn=get_current_trace_context,
    get_conn=get_conn,
    ensure_trace_tables=ensure_trace_tables,
    safe_json_dumps=safe_json_dumps,
    trim_text=_trim_text,
)
create_skill_trace = partial(
    create_skill_trace_impl,
    ensure_trace_tables=ensure_trace_tables,
    safe_json_dumps=safe_json_dumps,
)
complete_skill_trace = partial(
    complete_skill_trace_impl,
    safe_json_dumps=safe_json_dumps,
)

def insert_audit_log(cur, event_type: str, actor: str, task_id: int | None = None, details: Any | None = None):
    cur.execute(
        """
        INSERT INTO audit_logs (task_id, event_type, actor, details)
        VALUES (%s, %s, %s, %s);
        """,
        (task_id, event_type, actor, safe_json_dumps(details) if details is not None else None),
    )


build_task_result_excerpt = lambda task_row, limit=220: build_task_result_excerpt_impl(
    task_row,
    limit=limit,
    strip_artifact_suffix=strip_artifact_suffix,
)


create_agent_artifact = partial(
    create_agent_artifact_impl,
    safe_json_dumps=safe_json_dumps,
)
create_agent_message = partial(
    create_agent_message_impl,
    safe_json_dumps=safe_json_dumps,
)
create_agent_run = partial(
    create_agent_run_impl,
    safe_json_dumps=safe_json_dumps,
)
create_evaluator_run = partial(
    create_evaluator_run_impl,
    ensure_evaluator_tables=ensure_evaluator_tables,
    safe_json_dumps=safe_json_dumps,
)
build_review_criteria = build_review_criteria_impl
derive_evaluator_failure_profile = derive_evaluator_failure_profile_impl
build_workflow_proposal = build_workflow_proposal_impl
resolve_reviewer_decision = resolve_reviewer_decision_impl
build_specialist_step_partitions = partial(
    build_specialist_step_partitions_impl,
    build_task_display_input_excerpt=build_task_display_input_excerpt,
    build_task_result_excerpt=build_task_result_excerpt,
)
build_specialist_execution_request = partial(
    build_specialist_execution_request_impl,
    restricted_specialist_subtask_type=RESTRICTED_SPECIALIST_SUBTASK_TYPE,
)
is_mainline_specialist_tool_profile = partial(
    is_mainline_specialist_tool_profile_impl,
    mainline_specialist_tool_profiles=MAINLINE_SPECIALIST_TOOL_PROFILES,
)
is_mainline_specialist_execution_mode = partial(
    is_mainline_specialist_execution_mode_impl,
    auto_stage5_execution_mode=AUTO_STAGE5_EXECUTION_MODE,
    auto_stage5_runtime_execution_mode=AUTO_STAGE5_RUNTIME_EXECUTION_MODE,
)
build_mainline_specialist_specs = partial(
    build_mainline_specialist_specs_impl,
    auto_stage5_specialist_count=AUTO_STAGE5_SPECIALIST_COUNT,
    restricted_specialist_subtask_type=RESTRICTED_SPECIALIST_SUBTASK_TYPE,
    restricted_specialist_tool_names=RESTRICTED_SPECIALIST_TOOL_NAMES,
    build_task_display_input_excerpt=build_task_display_input_excerpt,
    build_task_result_excerpt=build_task_result_excerpt,
)
build_specialist_draft_payload = partial(
    build_specialist_draft_payload_impl,
    multi_agent_protocol_version=MULTI_AGENT_PROTOCOL_VERSION,
    auto_stage5_execution_mode=AUTO_STAGE5_EXECUTION_MODE,
)


def maybe_refresh_task_runtime_manager_rollup(cur, task_id: int):
    return maybe_refresh_task_runtime_manager_rollup_impl(
        cur,
        task_id,
        ensure_agent_tables=ensure_agent_tables,
        ensure_task_steps_columns=ensure_task_steps_columns,
        parse_jsonish=parse_jsonish,
        create_agent_artifact_fn=create_agent_artifact_impl,
        create_agent_message_fn=create_agent_message_impl,
        insert_audit_log=insert_audit_log,
        safe_json_dumps=safe_json_dumps,
        multi_agent_protocol_version=MULTI_AGENT_PROTOCOL_VERSION,
        auto_stage5_runtime_execution_mode=AUTO_STAGE5_RUNTIME_EXECUTION_MODE,
    )


def maybe_dispatch_task_runtime_specialists(task_id: int, reason: str):
    return maybe_dispatch_task_runtime_specialists_impl(
        task_id,
        reason,
        auto_stage5_postrun_enabled=AUTO_STAGE5_POSTRUN_ENABLED,
        auto_stage5_execution_mode=AUTO_STAGE5_EXECUTION_MODE,
        auto_stage5_runtime_execution_mode=AUTO_STAGE5_RUNTIME_EXECUTION_MODE,
        multi_agent_protocol_version=MULTI_AGENT_PROTOCOL_VERSION,
        mainline_specialist_tool_profiles=MAINLINE_SPECIALIST_TOOL_PROFILES,
        restricted_specialist_subtask_type=RESTRICTED_SPECIALIST_SUBTASK_TYPE,
        auto_stage5_specialist_count=AUTO_STAGE5_SPECIALIST_COUNT,
        restricted_specialist_tool_names=RESTRICTED_SPECIALIST_TOOL_NAMES,
        get_conn=get_conn,
        ensure_agent_tables=ensure_agent_tables,
        ensure_task_steps_columns=ensure_task_steps_columns,
        ensure_audit_logs_table=ensure_audit_logs_table,
        fetch_latest_evaluator_feedback=fetch_latest_evaluator_feedback,
        resolve_specialist_fanout_strategy=resolve_specialist_fanout_strategy,
        build_task_display_input=build_task_display_input,
        build_task_display_input_excerpt=build_task_display_input_excerpt,
        build_task_result_excerpt=build_task_result_excerpt,
        build_mainline_specialist_specs_fn=build_mainline_specialist_specs_impl,
        build_specialist_execution_request_fn=build_specialist_execution_request_impl,
        insert_audit_log=insert_audit_log,
        safe_json_dumps=safe_json_dumps,
        enqueue_agent_run=enqueue_agent_run,
        acquire_agent_run_claim=acquire_agent_run_claim,
        release_agent_run_claim=release_agent_run_claim,
        fetch_agent_run_by_id=fetch_agent_run_by_id,
        process_agent_run=process_agent_run,
        worker_id=WORKER_ID,
        uuid_module=uuid,
    )


def maybe_create_task_postrun_agent_records(cur, task_id: int, user_input: str):
    return maybe_create_task_postrun_agent_records_impl(
        cur,
        task_id,
        user_input,
        auto_stage5_postrun_enabled=AUTO_STAGE5_POSTRUN_ENABLED,
        auto_stage5_specialist_count=AUTO_STAGE5_SPECIALIST_COUNT,
        auto_stage5_execution_mode=AUTO_STAGE5_EXECUTION_MODE,
        auto_stage5_runtime_execution_mode=AUTO_STAGE5_RUNTIME_EXECUTION_MODE,
        auto_stage5_evaluator_source=AUTO_STAGE5_EVALUATOR_SOURCE,
        multi_agent_protocol_version=MULTI_AGENT_PROTOCOL_VERSION,
        mainline_specialist_tool_profiles=MAINLINE_SPECIALIST_TOOL_PROFILES,
        restricted_specialist_subtask_type=RESTRICTED_SPECIALIST_SUBTASK_TYPE,
        restricted_specialist_tool_names=RESTRICTED_SPECIALIST_TOOL_NAMES,
        ensure_agent_tables=ensure_agent_tables,
        ensure_evaluator_tables=ensure_evaluator_tables,
        ensure_task_steps_columns=ensure_task_steps_columns,
        ensure_audit_logs_table=ensure_audit_logs_table,
        build_task_display_input=build_task_display_input,
        build_task_display_input_excerpt=build_task_display_input_excerpt,
        build_task_result_excerpt=build_task_result_excerpt,
        fetch_latest_evaluator_feedback=fetch_latest_evaluator_feedback,
        resolve_specialist_fanout_strategy=resolve_specialist_fanout_strategy,
        parse_jsonish=parse_jsonish,
        safe_json_dumps=safe_json_dumps,
        insert_audit_log=insert_audit_log,
        create_agent_artifact_fn=create_agent_artifact_impl,
        create_agent_message_fn=create_agent_message_impl,
        create_agent_run_fn=create_agent_run_impl,
        create_evaluator_run_fn=create_evaluator_run_impl,
        build_mainline_specialist_specs_fn=build_mainline_specialist_specs_impl,
        build_specialist_execution_request_fn=build_specialist_execution_request_impl,
        build_specialist_draft_payload_fn=build_specialist_draft_payload_impl,
        resolve_reviewer_decision_fn=resolve_reviewer_decision_impl,
        build_review_criteria_fn=build_review_criteria_impl,
        derive_evaluator_failure_profile_fn=derive_evaluator_failure_profile_impl,
        build_workflow_proposal_fn=build_workflow_proposal_impl,
    )


def maybe_initialize_task_runtime_agent_records(cur, task_id: int, user_input: str):
    return maybe_initialize_task_runtime_agent_records_impl(
        cur,
        task_id,
        user_input,
        auto_stage5_postrun_enabled=AUTO_STAGE5_POSTRUN_ENABLED,
        auto_stage5_specialist_count=AUTO_STAGE5_SPECIALIST_COUNT,
        auto_stage5_execution_mode=AUTO_STAGE5_EXECUTION_MODE,
        auto_stage5_runtime_execution_mode=AUTO_STAGE5_RUNTIME_EXECUTION_MODE,
        multi_agent_protocol_version=MULTI_AGENT_PROTOCOL_VERSION,
        mainline_specialist_tool_profiles=MAINLINE_SPECIALIST_TOOL_PROFILES,
        restricted_specialist_subtask_type=RESTRICTED_SPECIALIST_SUBTASK_TYPE,
        restricted_specialist_tool_names=RESTRICTED_SPECIALIST_TOOL_NAMES,
        ensure_agent_tables=ensure_agent_tables,
        ensure_evaluator_tables=ensure_evaluator_tables,
        ensure_task_steps_columns=ensure_task_steps_columns,
        ensure_audit_logs_table=ensure_audit_logs_table,
        build_task_display_input=build_task_display_input,
        build_task_display_input_excerpt=build_task_display_input_excerpt,
        build_task_result_excerpt=build_task_result_excerpt,
        safe_json_dumps=safe_json_dumps,
        insert_audit_log=insert_audit_log,
        create_agent_artifact_fn=create_agent_artifact_impl,
        create_agent_message_fn=create_agent_message_impl,
        create_agent_run_fn=create_agent_run_impl,
        build_mainline_specialist_specs_fn=build_mainline_specialist_specs_impl,
        build_specialist_execution_request_fn=build_specialist_execution_request_impl,
    )


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


ensure_risk_policies_table = ensure_risk_policies_table_impl
ensure_tool_registry_table = lambda cur: ensure_tool_registry_table_impl(
    cur,
    runtime_schema_bootstrap_active=_runtime_schema_bootstrap_active,
    ensure_runtime_schema_bootstrapped=ensure_runtime_schema_bootstrapped,
)
ensure_model_routes_table = lambda cur: ensure_model_routes_table_impl(
    cur,
    runtime_schema_bootstrap_active=_runtime_schema_bootstrap_active,
    ensure_runtime_schema_bootstrapped=ensure_runtime_schema_bootstrapped,
)
ensure_model_providers_table = lambda cur: ensure_model_providers_table_impl(
    cur,
    runtime_schema_bootstrap_active=_runtime_schema_bootstrap_active,
    ensure_runtime_schema_bootstrapped=ensure_runtime_schema_bootstrapped,
)
seed_default_tool_registry = lambda cur: seed_default_tool_registry_impl(
    cur,
    runtime_schema_bootstrap_active=_runtime_schema_bootstrap_active,
    ensure_runtime_schema_bootstrapped=ensure_runtime_schema_bootstrapped,
    ensure_tool_registry_table_fn=ensure_tool_registry_table,
    default_tool_registry=DEFAULT_TOOL_REGISTRY,
    safe_json_dumps=safe_json_dumps,
)
seed_default_model_routes = lambda cur: seed_default_model_routes_impl(
    cur,
    runtime_schema_bootstrap_active=_runtime_schema_bootstrap_active,
    ensure_runtime_schema_bootstrapped=ensure_runtime_schema_bootstrapped,
    ensure_model_routes_table_fn=ensure_model_routes_table,
    default_model_routes=DEFAULT_MODEL_ROUTES,
)
seed_default_model_providers = lambda cur: seed_default_model_providers_impl(
    cur,
    runtime_schema_bootstrap_active=_runtime_schema_bootstrap_active,
    ensure_runtime_schema_bootstrapped=ensure_runtime_schema_bootstrapped,
    ensure_model_providers_table_fn=ensure_model_providers_table,
    default_model_providers=DEFAULT_MODEL_PROVIDERS,
)
seed_default_risk_policies = partial(
    seed_default_risk_policies_impl,
    default_risk_policies=DEFAULT_RISK_POLICIES,
    safe_json_dumps=safe_json_dumps,
)
load_risk_policy_settings = partial(
    load_risk_policy_settings_impl,
    default_risk_policies=DEFAULT_RISK_POLICIES,
    cache_ttl_seconds=RISK_POLICY_CACHE_TTL_SECONDS,
    get_conn=get_conn,
    seed_default_risk_policies_fn=seed_default_risk_policies,
)
load_tool_registry_settings = partial(
    load_tool_registry_settings_impl,
    default_tool_registry=DEFAULT_TOOL_REGISTRY,
    cache_ttl_seconds=TOOL_REGISTRY_CACHE_TTL_SECONDS,
    get_conn=get_conn,
    seed_default_tool_registry_fn=seed_default_tool_registry,
    parse_jsonish=parse_jsonish,
)
load_model_route_settings = partial(
    load_model_route_settings_impl,
    default_model_routes=DEFAULT_MODEL_ROUTES,
    cache_ttl_seconds=MODEL_ROUTE_CACHE_TTL_SECONDS,
    get_conn=get_conn,
    seed_default_model_routes_fn=seed_default_model_routes,
)
load_model_provider_settings = partial(
    load_model_provider_settings_impl,
    default_model_providers=DEFAULT_MODEL_PROVIDERS,
    cache_ttl_seconds=MODEL_PROVIDER_CACHE_TTL_SECONDS,
    get_conn=get_conn,
    seed_default_model_providers_fn=seed_default_model_providers,
)
get_model_provider_config = partial(
    get_model_provider_config_impl,
    load_model_provider_settings_fn=load_model_provider_settings,
)
get_model_provider_client = partial(
    get_model_provider_client_impl,
    get_model_provider_config_fn=get_model_provider_config,
    openai_cls=OpenAI,
)
get_model_route_config = partial(
    get_model_route_config_impl,
    load_model_route_settings_fn=load_model_route_settings,
    get_model_provider_config_fn=get_model_provider_config,
)
snapshot_model_route_config = partial(
    snapshot_model_route_config_impl,
    get_model_route_config_fn=get_model_route_config,
)
serialize_model_route_runtime_info = serialize_model_route_runtime_info_impl
ensure_tool_enabled = partial(
    ensure_tool_enabled_impl,
    load_tool_registry_settings_fn=load_tool_registry_settings,
)
get_tool_registry_entry = partial(
    get_tool_registry_entry_impl,
    load_tool_registry_settings_fn=load_tool_registry_settings,
)


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
    return get_step_approval_impl(
        cur,
        task_id,
        step_order,
        ensure_approvals_table=ensure_approvals_table,
    )


def create_step_approval(
    cur,
    task_id: int,
    step_order: int,
    step_name: str,
    tool_name: str,
    input_payload: Any,
    reason: str,
):
    return create_step_approval_impl(
        cur,
        task_id,
        step_order,
        step_name,
        tool_name,
        input_payload,
        reason,
        ensure_approvals_table=ensure_approvals_table,
        safe_json_dumps=safe_json_dumps,
    )


def set_step_waiting_approval(cur, task_id: int, step_order: int, tool_name: str, input_payload: Any, reason: str):
    return set_step_waiting_approval_impl(
        cur,
        task_id,
        step_order,
        tool_name,
        input_payload,
        reason,
        set_step_result=set_step_result,
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
    return should_require_approval_impl(
        tool_name,
        payload,
        load_risk_policy_settings=load_risk_policy_settings,
        get_tool_registry_entry=get_tool_registry_entry,
        low_risk_write_extensions=LOW_RISK_WRITE_EXTENSIONS,
        sensitive_write_extensions=SENSITIVE_WRITE_EXTENSIONS,
        sensitive_write_basenames=SENSITIVE_WRITE_BASENAMES,
    )


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


should_run_step = partial(
    should_run_step_impl,
    resolve_input_payload=resolve_input_payload,
)
normalize_http_request_input = normalize_http_request_input_impl
normalize_web_search_input = partial(
    normalize_web_search_input_impl,
    sanitize_web_search_query=sanitize_web_search_query,
)
validate_planned_steps = partial(
    validate_planned_steps_impl,
    normalize_web_search_input_fn=normalize_web_search_input,
)
validate_input_value = partial(
    validate_input_value_impl,
    tool_input_rules=TOOL_INPUT_RULES,
    get_tool_registry_entry=get_tool_registry_entry,
    supported_operators=SUPPORTED_OPERATORS,
    supported_logics=SUPPORTED_LOGICS,
)


# =========================
# Planning
# =========================
fallback_legacy_steps = fallback_legacy_steps_impl
infer_structured_steps_from_user_input = partial(
    infer_structured_steps_from_user_input_impl,
    extract_path_from_text=extract_path_from_text,
)
call_deepseek_planner = partial(
    call_deepseek_planner_impl,
    get_model_route_config=get_model_route_config,
    get_model_provider_client=get_model_provider_client,
    record_model_trace=record_model_trace,
    serialize_model_route_runtime_info=serialize_model_route_runtime_info,
    normalize_step_name=normalize_step_name,
    default_max_retries_for_tool=default_max_retries_for_tool,
    validate_planned_steps=validate_planned_steps,
    step_request_protocol_version=STEP_REQUEST_PROTOCOL_VERSION,
)
call_planner_with_retries = partial(
    call_planner_with_retries_impl,
    call_deepseek_planner_fn=call_deepseek_planner,
)
resolve_task_plan_source = partial(
    resolve_task_plan_source_impl2,
    infer_structured_steps_from_user_input=infer_structured_steps_from_user_input,
    call_planner_with_retries_fn=call_planner_with_retries,
    fallback_legacy_steps=fallback_legacy_steps,
    logger=logger,
)
plan_task = partial(
    plan_task_impl,
    resolve_task_plan_source_fn=resolve_task_plan_source,
)


# =========================
# Tool implementations
# =========================
tool_file_read = partial(
    tool_file_read_impl,
    ensure_readable_file=ensure_readable_file,
)
tool_file_write = partial(
    tool_file_write_impl,
    ensure_writable_file=ensure_writable_file,
)
tool_list_dir = partial(
    tool_list_dir_impl,
    ensure_readable_dir=ensure_readable_dir,
)


validate_shell_command = partial(
    validate_shell_command_impl,
    shlex_module=shlex,
    safe_commands=SAFE_COMMANDS,
    disallowed_tokens=DISALLOWED_TOKENS,
)


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


dedupe_search_results = dedupe_search_results_impl
summarize_search_results = partial(
    summarize_search_results_impl,
    get_model_route_config=get_model_route_config,
    serialize_model_route_runtime_info=serialize_model_route_runtime_info,
    get_model_provider_client=get_model_provider_client,
    record_model_trace=record_model_trace,
    safe_json_dumps=safe_json_dumps,
)
web_search_duckduckgo = partial(
    web_search_duckduckgo_impl,
    requests_module=requests,
    beautiful_soup_cls=BeautifulSoup,
    summarize_search_results_fn=summarize_search_results,
)
web_search_tavily = partial(
    web_search_tavily_impl,
    requests_module=requests,
    tavily_api_key=TAVILY_API_KEY,
    summarize_search_results_fn=summarize_search_results,
)
tool_web_search = partial(
    tool_web_search_impl,
    web_search_duckduckgo_fn=web_search_duckduckgo,
    web_search_tavily_fn=web_search_tavily,
)


tool_read_json = partial(
    tool_read_json_impl,
    ensure_readable_file=ensure_readable_file,
)
tool_write_json = partial(
    tool_write_json_impl,
    ensure_writable_file=ensure_writable_file,
)
tool_json_extract = partial(
    tool_json_extract_impl,
    get_nested_value=get_nested_value,
)


def execute_mcp_tool(tool_name: str, payload: dict, registry_entry: dict[str, Any]) -> dict:
    return execute_mcp_tool_impl(
        tool_name,
        payload,
        registry_entry,
        shlex_module=shlex,
        subprocess_module=subprocess,
        requests_module=requests,
        safe_json_dumps=safe_json_dumps,
        env=dict(os.environ),
    )


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
    return resolve_hostname_ips_impl(hostname, socket_module=socket)


def validate_http_url(url: str):
    return validate_http_url_impl(
        url,
        urlparse_fn=urlparse,
        ipaddress_module=ipaddress,
        resolve_hostname_ips_fn=resolve_hostname_ips,
        blocked_hosts={
            "localhost",
            "127.0.0.1",
            "0.0.0.0",
            "::1",
            "postgres",
            "api",
            "worker",
            "web",
        },
    )


def tool_http_request(
    url: str,
    method: str,
    params: Optional[dict] = None,
    json_body: Optional[dict] = None,
    timeout: int = 15,
) -> dict:
    return tool_http_request_impl(
        url,
        method,
        validate_http_url_fn=validate_http_url,
        requests_module=requests,
        params=params,
        json_body=json_body,
        timeout=timeout,
    )


evaluate_single_condition_payload = partial(
    evaluate_single_condition_payload_impl,
    compare_values=compare_values,
)
tool_set_var = tool_set_var_impl
tool_template_render = partial(
    tool_template_render_impl,
    render_template_text=render_template_text,
)
build_group_output_text = build_group_output_text_impl
tool_if_condition_group = partial(
    tool_if_condition_group_impl,
    supported_logics=SUPPORTED_LOGICS,
    evaluate_single_condition_payload_fn=evaluate_single_condition_payload,
    build_group_output_text_fn=build_group_output_text,
)
tool_if_condition = partial(
    tool_if_condition_impl,
    supported_operators=SUPPORTED_OPERATORS,
    tool_if_condition_group_fn=tool_if_condition_group,
    compare_values=compare_values,
)


def execute_tool(
    tool_name: str,
    payload: dict,
    step_context: Optional[dict[int, dict]] = None,
    var_context: Optional[dict[str, Any]] = None,
    model_route_overrides: dict[str, dict[str, Any]] | None = None,
) -> dict:
    return execute_tool_impl(
        tool_name,
        payload,
        get_tool_registry_entry=get_tool_registry_entry,
        execute_mcp_tool_fn=execute_mcp_tool,
        tool_file_read_fn=tool_file_read,
        tool_file_write_fn=tool_file_write,
        tool_list_dir_fn=tool_list_dir,
        tool_shell_exec_fn=tool_shell_exec,
        tool_generate_text_fn=tool_generate_text,
        tool_summarize_text_fn=tool_summarize_text,
        tool_web_search_fn=tool_web_search,
        tool_read_json_fn=tool_read_json,
        tool_write_json_fn=tool_write_json,
        tool_http_request_fn=tool_http_request,
        tool_json_extract_fn=tool_json_extract,
        tool_set_var_fn=tool_set_var,
        tool_template_render_fn=tool_template_render,
        tool_if_condition_fn=tool_if_condition,
        step_context=step_context,
        var_context=var_context,
        model_route_overrides=model_route_overrides,
    )


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
    return finalize_structured_step_success_impl(
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
        persist_structured_step_outcome_fn=persist_structured_step_outcome,
        complete_step_and_tool_trace=complete_step_and_tool_trace,
        step_trace_id=step_trace_id,
        tool_trace_id=tool_trace_id,
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
    return finalize_structured_step_continue_impl(
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
        persist_structured_step_outcome_fn=persist_structured_step_outcome,
        complete_step_and_tool_trace=complete_step_and_tool_trace,
        step_trace_id=step_trace_id,
        tool_trace_id=tool_trace_id,
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
    return record_structured_step_exception_impl(
        cur,
        task_id,
        step_order,
        tool_name,
        input_payload,
        error_strategy,
        user_input,
        step_context,
        var_context,
        step_outputs,
        err,
        persist_structured_step_outcome_fn=persist_structured_step_outcome,
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
    return persist_structured_step_runtime_state_impl(
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
        write_checkpoint=write_checkpoint,
    )


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
    return persist_task_runtime_state_impl(
        cur,
        task_id,
        user_input,
        status,
        current_step,
        step_context,
        var_context,
        step_outputs,
        task_error_message,
        checkpoint_error,
        update_task_status=update_task_status,
        write_checkpoint=write_checkpoint,
        result=result,
        update_status_row=update_status_row,
    )


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
    return persist_structured_step_outcome_impl(
        cur,
        task_id,
        step_order,
        tool_name,
        input_payload,
        step_status,
        output_payload,
        output_data,
        error_message,
        error_strategy,
        user_input,
        step_context,
        var_context,
        step_outputs,
        checkpoint_error,
        update_var,
        set_step_result=set_step_result,
        set_step_retry_count=set_step_retry_count,
        persist_structured_step_runtime_state_fn=persist_structured_step_runtime_state,
        runtime_status=runtime_status,
        retry_count=retry_count,
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
    return record_skipped_step_impl(
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
        persist_structured_step_outcome_fn=persist_structured_step_outcome,
        complete_step_and_tool_trace=complete_step_and_tool_trace,
        step_trace_id=step_trace_id,
        tool_trace_id=tool_trace_id,
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
    return build_task_result_excerpt_impl(task_row, limit=limit, strip_artifact_suffix=strip_artifact_suffix)


def build_task_summary_memory_content(task_display_input: str, final_result: str) -> str:
    return build_task_summary_memory_content_impl(
        task_display_input,
        final_result,
        strip_artifact_suffix=strip_artifact_suffix,
    )


def extract_marked_clauses(text: str, markers: tuple[str, ...], max_length: int = 240) -> list[str]:
    return extract_marked_clauses_impl(text, markers, max_length=max_length)


def infer_task_memories(user_input: str, final_result: str) -> list[dict[str, Any]]:
    return infer_task_memories_impl(
        user_input,
        final_result,
        strip_artifact_suffix=strip_artifact_suffix,
        extract_marked_clauses_fn=extract_marked_clauses,
    )


def rebuild_session_state_from_worker(cur, session_id: int):
    return rebuild_session_state_from_worker_impl(
        cur,
        session_id,
        build_task_display_user_input=build_task_display_user_input,
        normalize_runtime_overrides=normalize_runtime_overrides,
        safe_json_dumps=safe_json_dumps,
    )


def capture_session_memory_for_completed_task(cur, task_id: int, user_input: str, final_result: str):
    return capture_session_memory_for_completed_task_impl(
        cur,
        task_id,
        user_input,
        final_result,
        ensure_sessions_tables=ensure_sessions_tables,
        ensure_audit_logs_table=ensure_audit_logs_table,
        ensure_long_term_memory_table=ensure_long_term_memory_table,
        build_task_display_user_input=build_task_display_user_input,
        normalize_runtime_overrides=normalize_runtime_overrides,
        build_task_summary_memory_content_fn=build_task_summary_memory_content,
        infer_task_memories_fn=infer_task_memories,
        upsert_long_term_memory=upsert_long_term_memory,
        strip_artifact_suffix=strip_artifact_suffix,
        rebuild_session_state_from_worker_fn=rebuild_session_state_from_worker,
        insert_audit_log=insert_audit_log,
    )


def finalize_task_success(
    cur,
    task_id: int,
    user_input: str,
    step_outputs: list[str],
    step_context: dict[int, dict],
    var_context: dict[str, Any],
) -> str:
    return finalize_task_success_impl(
        cur,
        task_id,
        user_input,
        step_outputs,
        step_context,
        var_context,
        assemble_task_success_result=assemble_task_success_result,
        validate_task_deliverable=validate_task_deliverable,
        update_task_delivery_records=update_task_delivery_records,
        insert_audit_log=insert_audit_log,
        count_task_audit_events=count_task_audit_events,
        find_first_step_order_by_tool=find_first_step_order_by_tool,
        reset_task_for_auto_recovery=reset_task_for_auto_recovery,
        auto_recovery_scheduled_exc_type=AutoRecoveryScheduled,
        persist_task_runtime_state=persist_task_runtime_state,
        update_task_trace_status=update_task_trace_status,
        maybe_create_task_postrun_agent_records=maybe_create_task_postrun_agent_records,
        capture_session_memory_for_completed_task=capture_session_memory_for_completed_task,
        logger=logger,
    )


def finalize_task_failure(
    cur,
    task_id: int,
    user_input: str,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
    step_outputs: list[str],
    err: str,
):
    return finalize_task_failure_impl(
        cur,
        task_id,
        user_input,
        step_context,
        var_context,
        step_outputs,
        err,
        build_runtime_failure_validation_report=build_runtime_failure_validation_report,
        build_runtime_failure_recovery_action=build_runtime_failure_recovery_action,
        update_task_delivery_records=update_task_delivery_records,
        persist_task_runtime_state=persist_task_runtime_state,
        update_task_trace_status=update_task_trace_status,
        insert_audit_log=insert_audit_log,
        maybe_create_task_postrun_agent_records=maybe_create_task_postrun_agent_records,
        logger=logger,
    )


def start_task_execution(cur, task_id: int, user_input: str):
    return start_task_execution_impl(
        cur,
        task_id,
        user_input,
        ensure_task_trace=ensure_task_trace,
        persist_task_runtime_state=persist_task_runtime_state,
        update_task_trace_status=update_task_trace_status,
    )


def start_step_execution(cur, task_id: int, step_order: int):
    return start_step_execution_impl(
        cur,
        task_id,
        step_order,
        set_step_running=set_step_running,
        update_task_progress=update_task_progress,
    )


def record_legacy_step_result(
    cur,
    task_id: int,
    step_order: int,
    output_text: str,
    ok: bool,
):
    return record_legacy_step_result_impl(
        cur,
        task_id,
        step_order,
        output_text,
        ok,
        set_step_result=set_step_result,
    )


def persist_legacy_step_runtime_state(
    cur,
    task_id: int,
    user_input: str,
    step_order: int,
    output_text: str,
    step_outputs: list[str],
):
    return persist_legacy_step_runtime_state_impl(
        cur,
        task_id,
        user_input,
        step_order,
        output_text,
        step_outputs,
        persist_task_runtime_state=persist_task_runtime_state,
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
    return normalize_step_execution_request_impl(
        step,
        default_max_retries_for_tool=default_max_retries_for_tool,
    )


def enrich_step_execution_request(
    execution_request: StepExecutionRequest,
    step: dict,
    step_context: dict[int, dict],
    var_context: dict[str, Any],
) -> EnrichedStepExecutionRequest:
    return enrich_step_execution_request_impl(
        execution_request,
        step,
        step_context,
        var_context,
        resolve_input_payload=resolve_input_payload,
        resolve_structured_step_input=resolve_structured_step_input,
        normalize_web_search_input_fn=normalize_web_search_input,
        normalize_http_request_input_fn=normalize_http_request_input,
        validate_input_value_fn=validate_input_value,
        should_require_approval=should_require_approval,
    )


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
    return execute_prepared_step_request_impl(
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
        record_skipped_step=record_skipped_step,
        enforce_step_approval=enforce_step_approval,
        execute_step_with_retries=execute_step_with_retries,
        step_trace_id=step_trace_id,
        tool_trace_id=tool_trace_id,
    )


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
    return route_structured_step_outcome_impl(
        cur,
        task_id,
        user_input,
        execution_request,
        result,
        retry_count,
        step_context,
        var_context,
        step_outputs,
        logger=logger,
        finalize_structured_step_success=finalize_structured_step_success,
        finalize_structured_step_continue=finalize_structured_step_continue,
        step_trace_id=step_trace_id,
        tool_trace_id=tool_trace_id,
    )


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
    return begin_structured_step_execution_impl(
        cur,
        task_id,
        user_input,
        step,
        execution_request,
        step_context,
        var_context,
        step_outputs,
        claim_heartbeat,
        logger=logger,
        get_task_control_status=get_task_control_status,
        interrupt_task_if_requested=interrupt_task_if_requested,
        start_step_execution=start_step_execution,
        create_step_and_tool_trace=create_step_and_tool_trace,
        set_current_trace_context=set_current_trace_context,
    )


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
    return process_structured_step_request_impl(
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
        supported_tools=SUPPORTED_TOOLS,
        ensure_tool_enabled=ensure_tool_enabled,
        enrich_step_execution_request=enrich_step_execution_request,
        execute_prepared_step_request_fn=execute_prepared_step_request,
        step_trace_id=step_trace_id,
        tool_trace_id=tool_trace_id,
    )


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
    return complete_structured_step_execution_impl(
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
        process_structured_step_request_fn=process_structured_step_request,
        route_structured_step_outcome_fn=route_structured_step_outcome,
        record_structured_step_exception=record_structured_step_exception,
        complete_step_and_tool_trace=complete_step_and_tool_trace,
        approval_required_exc_type=ApprovalRequired,
        step_trace_id=step_trace_id,
        tool_trace_id=tool_trace_id,
    )


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
    return run_structured_step_impl(
        cur,
        task_id,
        user_input,
        step,
        step_context,
        var_context,
        step_outputs,
        claim_heartbeat,
        model_route_overrides,
        normalize_step_execution_request=normalize_step_execution_request,
        begin_structured_step_execution_fn=begin_structured_step_execution,
        clear_current_trace_context=clear_current_trace_context,
        set_current_trace_context=set_current_trace_context,
        complete_structured_step_execution=complete_structured_step_execution,
    )


def process_task(task: dict, claim_heartbeat: Optional[TaskClaimHeartbeat] = None):
    return process_task_impl(
        task,
        claim_heartbeat,
        get_conn=get_conn,
        logger=logger,
        augment_user_input_with_memory_context=augment_user_input_with_memory_context,
        extract_task_model_route_overrides=extract_task_model_route_overrides,
        extract_task_skill_invocation=extract_task_skill_invocation,
        extract_task_intent=extract_task_intent,
        extract_deliverable_spec=extract_deliverable_spec,
        ensure_task_steps_columns=ensure_task_steps_columns,
        ensure_approvals_table=ensure_approvals_table,
        seed_default_tool_registry=seed_default_tool_registry,
        seed_default_model_providers=seed_default_model_providers,
        seed_default_model_routes=seed_default_model_routes,
        fetch_latest_evaluator_feedback=fetch_latest_evaluator_feedback,
        augment_user_input_with_runtime_feedback=augment_user_input_with_runtime_feedback,
        fail_task_for_missing_clarification=fail_task_for_missing_clarification,
        start_task_execution=start_task_execution,
        set_current_trace_context=set_current_trace_context,
        clear_current_trace_context=clear_current_trace_context,
        select_task_plan_source=select_task_plan_source,
        run_planned_execution=run_planned_execution,
        finalize_task_success=finalize_task_success,
        finalize_task_failure=finalize_task_failure,
        maybe_dispatch_task_runtime_specialists=maybe_dispatch_task_runtime_specialists,
        approval_required_exc_type=ApprovalRequired,
        interrupt_requested_exc_type=InterruptRequested,
        auto_recovery_scheduled_exc_type=AutoRecoveryScheduled,
        claim_lost_exc_type=ClaimLostError,
    )


def fetch_task_by_id(task_id: int) -> Optional[dict]:
    return fetch_task_by_id_impl(task_id, get_conn=get_conn)


def fetch_next_pending_task():
    return fetch_next_pending_task_impl(get_conn=get_conn)


def process_agent_run(agent_run: dict):
    return process_agent_run_impl(
        agent_run,
        logger=logger,
        get_conn=get_conn,
        ensure_agent_tables=ensure_agent_tables,
        ensure_evaluator_tables=ensure_evaluator_tables,
        ensure_task_steps_columns=ensure_task_steps_columns,
        ensure_audit_logs_table=ensure_audit_logs_table,
        parse_jsonish=parse_jsonish,
        build_task_display_input_excerpt=build_task_display_input_excerpt,
        build_task_result_excerpt=build_task_result_excerpt,
        tool_shell_exec=tool_shell_exec,
        tool_file_read=tool_file_read,
        tool_read_json=tool_read_json,
        tool_json_extract=tool_json_extract,
        tool_list_dir=tool_list_dir,
        create_agent_artifact=create_agent_artifact,
        create_agent_message=create_agent_message,
        insert_audit_log=insert_audit_log,
        maybe_refresh_task_runtime_manager_rollup=maybe_refresh_task_runtime_manager_rollup,
        auto_stage5_runtime_execution_mode=AUTO_STAGE5_RUNTIME_EXECUTION_MODE,
        mainline_specialist_tool_profiles=MAINLINE_SPECIALIST_TOOL_PROFILES,
        restricted_specialist_subtask_type=RESTRICTED_SPECIALIST_SUBTASK_TYPE,
    )


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
    return task_claim_key_impl(task_id)


def agent_run_claim_key(agent_run_id: int) -> str:
    return agent_run_claim_key_impl(agent_run_id)


def enqueue_task(task_id: int):
    return enqueue_task_impl(task_id, get_redis_client=get_redis_client, logger=logger)


def enqueue_agent_run(agent_run_id: int):
    return enqueue_agent_run_impl(agent_run_id, get_redis_client=get_redis_client, logger=logger)


def acquire_task_claim(task_id: int, claim_token: str) -> bool:
    return acquire_task_claim_impl(
        task_id,
        claim_token,
        get_redis_client=get_redis_client,
        logger=logger,
        task_lock_ttl_seconds=TASK_LOCK_TTL_SECONDS,
    )


def renew_task_claim(task_id: int, claim_token: str) -> bool:
    return renew_task_claim_impl(
        task_id,
        claim_token,
        get_redis_client=get_redis_client,
        logger=logger,
        task_lock_ttl_seconds=TASK_LOCK_TTL_SECONDS,
    )


def release_task_claim(task_id: int, claim_token: str):
    return release_task_claim_impl(task_id, claim_token, get_redis_client=get_redis_client, logger=logger)


def has_live_task_claim(task_id: int) -> bool:
    return has_live_task_claim_impl(task_id, get_redis_client=get_redis_client, logger=logger)


def acquire_agent_run_claim(agent_run_id: int, claim_token: str) -> bool:
    return acquire_agent_run_claim_impl(
        agent_run_id,
        claim_token,
        get_redis_client=get_redis_client,
        logger=logger,
        task_lock_ttl_seconds=TASK_LOCK_TTL_SECONDS,
    )


def release_agent_run_claim(agent_run_id: int, claim_token: str):
    return release_agent_run_claim_impl(agent_run_id, claim_token, get_redis_client=get_redis_client, logger=logger)


def dequeue_task(timeout_seconds: int = 2) -> Optional[dict]:
    return dequeue_task_impl(
        timeout_seconds,
        get_redis_client=get_redis_client,
        logger=logger,
        fetch_task_by_id_fn=fetch_task_by_id,
    )


def dequeue_agent_run(timeout_seconds: int = 1) -> Optional[dict]:
    return dequeue_agent_run_impl(
        timeout_seconds,
        get_redis_client=get_redis_client,
        logger=logger,
        fetch_agent_run_by_id_fn=fetch_agent_run_by_id,
    )


def requeue_stale_running_tasks():
    return requeue_stale_running_tasks_impl(
        get_conn=get_conn,
        logger=logger,
        task_stale_requeue_seconds=TASK_STALE_REQUEUE_SECONDS,
        has_live_task_claim_fn=has_live_task_claim,
        update_task_status=update_task_status,
        enqueue_task_fn=enqueue_task,
        record_worker_audit_event=record_worker_audit_event,
    )


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
