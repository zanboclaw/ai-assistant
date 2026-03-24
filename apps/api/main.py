from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import psycopg2
from psycopg2.extras import Json, RealDictCursor

RUNTIME_DEFAULTS_IMPORT_ROOT = Path(
    os.environ.get("WORKSPACE_ROOT", str(Path(__file__).resolve().parent.parent.parent))
).resolve()
if str(RUNTIME_DEFAULTS_IMPORT_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DEFAULTS_IMPORT_ROOT))

from access_control import (
    ACCESS_ROLE_PERMISSIONS,
    ensure_access_actors_table,
    ensure_access_quotas_table,
    enforce_task_quota,
    require_actor_permission,
    seed_default_access_actors,
    seed_default_access_quotas,
    upsert_access_actor,
    upsert_access_quota,
    upsert_default_access_quota,
)
from change_request_helpers import (
    CHANGE_GATE_REQUIRED_TARGET_TYPES,
    CHANGE_REQUEST_SELECT_FIELDS,
    DEFAULT_ENFORCED_CHANGE_TARGET_TYPES,
    WORKFLOW_PROPOSAL_SHADOW_VALIDATION_REQUEST_EVENT,
    WORKFLOW_PROPOSAL_SHADOW_VALIDATION_RESULT_EVENT,
    change_request_requires_shadow_validation,
    normalize_change_request_proposal_kind,
)
from change_request_control_routes import register_change_request_control_routes
from change_request_query_routes import register_change_request_query_routes
from change_request_business import (
    apply_change_request_payload,
    annotate_shadow_validation_report_for_change_request,
    attach_patch_artifacts_to_change_request_draft,
    attach_shadow_validation_state_to_change_request_draft,
    collect_change_request_shadow_validation_context,
    create_change_request_with_audit,
    execute_change_request_apply,
    prepare_change_request_rollback_context,
    review_change_request,
    build_shadow_validation_execution_payload,
    build_change_request_create_payload,
    build_change_request_patch_artifacts,
    build_change_request_rollback_draft,
    build_change_request_shadow_validation_state,
    build_change_request_shadow_validation_response,
    build_change_request_draft_from_workflow_proposal,
    build_shadow_validation_result,
    finalize_shadow_validation_response,
    prepare_shadow_validation_baseline,
    process_change_request_post_apply,
    resolve_shadow_validation_candidate_overlay,
    suggest_change_request_draft_from_workflow_proposal,
    wait_for_shadow_validation_completion,
)
from change_request_serializers import (
    build_shadow_validation_candidate_overlay,
    serialize_change_request_list_row,
    serialize_change_request_row,
    shadow_validation_candidate_matches,
)
from change_request_store import (
    compute_change_payload_patch,
    build_workflow_proposal_shadow_validation_status,
    fetch_change_request_row,
    fetch_change_target_state_for_rollback,
    fetch_latest_workflow_proposal_shadow_validation,
    fetch_task_run_brief,
    fetch_workflow_proposal_shadow_validation_history,
    find_open_rollback_change_request,
    get_change_request_or_404,
    insert_change_request_row,
    serialize_shadow_validation_audit_row,
    sync_change_requests_shadow_validation,
)
from governance_helpers import (
    ensure_model_providers_table,
    ensure_model_routes_table,
    ensure_tool_registry_table,
    seed_default_model_providers,
    seed_default_model_routes,
    seed_default_tool_registry,
    update_model_route_entry,
    update_tool_registry_entry,
    upsert_model_provider_entry,
)
from governance_routes import register_governance_routes
from intake_task_routes import (
    build_intake_preview_payload,
    build_memory_context,
    register_intake_task_routes,
    resolve_intake_route_mode,
)
from multi_agent_query_routes import register_multi_agent_query_routes
from skill_routes import register_skill_routes
from session_routes import register_session_routes
from task_control_routes import register_task_control_routes
from task_query_routes import register_task_query_routes
from json_utils import (
    compute_stable_payload_hash,
    make_json_compatible,
    parse_optional_int,
    safe_json_dumps,
)
from core.task_runtime import (
    build_clarified_user_input,
    build_task_display_user_input,
    build_task_fact_memory_content,
    build_task_summary_memory_content,
    extract_task_clarification_state,
    normalize_task_clarification_history,
    strip_artifact_suffix,
    strip_legacy_clarification_suffix,
)
from core.long_term_memory import (
    ensure_long_term_memory_table,
    search_long_term_memories,
    upsert_long_term_memory,
)
from session_runtime import (
    compute_session_health,
    compute_stage_readiness_metrics,
    compute_session_state_from_rows,
    build_session_review,
    insert_session_review_row,
    load_session_health_context,
    merge_memory_into_session_state,
    refresh_session_review_context,
    refresh_session_reviews,
    refresh_session_task_summary_memories,
    upsert_computed_session_state,
)
from task_intent_helpers import infer_deliverable_spec, infer_task_intent
from monitor_overview_store import fetch_monitor_overview_snapshot
from monitor_routes import register_monitor_routes
from monitor_stage_metrics_store import fetch_stage56_overview_metrics
from monitor_stage7_store import fetch_stage7_overview_metrics
from multi_agent_demo_routes import register_multi_agent_demo_routes
from risk_policy_helpers import (
    DEFAULT_RISK_POLICIES,
    RISK_POLICY_MAP,
    deserialize_policy_row,
    ensure_risk_policies_table,
    seed_default_risk_policies,
    update_risk_policy_entry,
    validate_policy_value,
)
from workflow_proposal_store import (
    build_workflow_proposal_shadow_validation_response,
    build_workflow_proposal_change_request_draft,
    complete_workflow_proposal_shadow_validation,
    create_change_request_from_workflow_proposal_draft,
    build_workflow_proposal_shadow_status,
    create_shadow_validation_task,
    ensure_change_request_shadow_validation_eligible,
    ensure_workflow_proposal_shadow_validation_supported,
    fetch_evaluator_run_row,
    get_evaluator_run_or_404,
    get_workflow_proposal_change_request_draft_response,
    get_workflow_proposal_or_404,
    launch_workflow_proposal_shadow_validation,
    prepare_workflow_proposal_shadow_validation_context,
    resolve_change_request_shadow_validation_target,
    task_exists,
)
from schemas import (
    AgentBootstrapRequest,
    AgentExecuteRequest,
    AgentFinalizeRequest,
    ApprovalDecision,
    ChangeRequestCreate,
    ChangeRequestDecision,
    IntakeRouteRequest,
    TaskClarifyRequest,
    TaskDraftConfirmRequest,
    TaskCreate,
    TaskInterruptRequest,
    TaskResumeRequest,
    WorkflowProposalBridgeRequest,
    WorkflowProposalShadowValidationRequest,
)
from serializers import (
    serialize_access_actor_row,
    serialize_access_quota_row,
    serialize_agent_artifact_row,
    serialize_agent_message_row,
    serialize_agent_run_row,
    serialize_evaluator_run_row,
    serialize_model_provider_row,
    serialize_model_route_row,
    serialize_session_memory_row,
    serialize_session_review_row,
    serialize_session_row,
    serialize_session_state_row,
    serialize_skill_row,
    serialize_skill_version_row,
    serialize_tool_registry_row,
    serialize_workflow_proposal,
)
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
    "host": os.environ.get("POSTGRES_HOST", "postgres"),
    "dbname": os.environ.get("POSTGRES_DB", "assistant"),
    "user": os.environ.get("POSTGRES_USER", "assistant"),
    "password": os.environ.get("POSTGRES_PASSWORD", "change_me_for_local_dev"),
}

API_APP_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = Path(
    os.environ.get("WORKSPACE_ROOT", str(API_APP_DIR.parent.parent))
).resolve()
LOG_DIR = Path(os.environ.get("LOG_DIR", str(WORKSPACE_ROOT / "logs"))).resolve()
LOG_DIR.mkdir(parents=True, exist_ok=True)
CHECKPOINT_DIR = Path(os.environ.get("CHECKPOINT_DIR", str(WORKSPACE_ROOT / "data" / "checkpoints"))).resolve()
CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
SANDBOX_CHANGE_ROOT = Path(
    os.environ.get("SANDBOX_CHANGE_ROOT", str(API_APP_DIR / "stage7_sandbox"))
).resolve()
SANDBOX_CHANGE_ROOT.mkdir(parents=True, exist_ok=True)
SANDBOX_ACCEPTANCE_SCRIPTS_ROOT = (WORKSPACE_ROOT / "scripts").resolve()
SANDBOX_FILE_ENCODING = "utf-8"
SANDBOX_FILE_CONTENT_LIMIT_BYTES = int(os.environ.get("SANDBOX_FILE_CONTENT_LIMIT_BYTES", "65536"))
SANDBOX_FILE_ACCEPTANCE_DEFAULT_TIMEOUT_SECONDS = int(
    os.environ.get("SANDBOX_FILE_ACCEPTANCE_DEFAULT_TIMEOUT_SECONDS", "30")
)
SANDBOX_FILE_ACCEPTANCE_MAX_TIMEOUT_SECONDS = int(
    os.environ.get("SANDBOX_FILE_ACCEPTANCE_MAX_TIMEOUT_SECONDS", "300")
)
SANDBOX_FILE_ACCEPTANCE_MAX_ENV_VARS = int(
    os.environ.get("SANDBOX_FILE_ACCEPTANCE_MAX_ENV_VARS", "16")
)
SANDBOX_FILE_ACCEPTANCE_MAX_ENV_BYTES = int(
    os.environ.get("SANDBOX_FILE_ACCEPTANCE_MAX_ENV_BYTES", "4096")
)
SANDBOX_FILE_ACCEPTANCE_OUTPUT_LIMIT = int(
    os.environ.get("SANDBOX_FILE_ACCEPTANCE_OUTPUT_LIMIT", "4000")
)
SANDBOX_FILE_ACCEPTANCE_ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
SANDBOX_FILE_UNIFIED_HUNK_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? \+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@"
)
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
AUTO_STAGE5_POSTRUN_ENABLED = os.environ.get("AUTO_STAGE5_POSTRUN_ENABLED", "1").lower() in {"1", "true", "yes"}
MAINLINE_SPECIALIST_EXECUTION_MODES = {"task_postrun_readonly_v1", "task_runtime_worker_v1"}
MAINLINE_SPECIALIST_TOOL_PROFILES = {"specialist-readonly", "specialist-restricted"}

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
_runtime_core_schema_bootstrap_lock = threading.Lock()
_runtime_core_schema_bootstrap_active = False
_runtime_core_schema_bootstrapped = False
_change_requests_schema_bootstrap_lock = threading.Lock()
_change_requests_schema_bootstrapped = False


def _table_exists(cur, table_name: str) -> bool:
    cur.execute("SELECT to_regclass(%s) AS regclass;", (f"public.{table_name}",))
    return bool(cur.fetchone()["regclass"])


def _column_exists(cur, table_name: str, column_name: str) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = %s
          AND column_name = %s
        LIMIT 1;
        """,
        (table_name, column_name),
    )
    return cur.fetchone() is not None


def _change_requests_schema_ready(cur) -> bool:
    if not _table_exists(cur, "change_requests"):
        return False
    required_columns = (
        "proposal_kind",
        "source_change_request_id",
        "source_workflow_proposal_id",
        "shadow_validation_status",
        "shadow_validation_report",
        "shadow_validation_at",
        "baseline_payload",
        "payload_patch",
        "patch_summary",
        "rollback_payload",
        "rollback_ready",
        "rollback_note",
        "acceptance_status",
        "acceptance_report",
        "acceptance_at",
        "auto_rollback_change_request_id",
        "auto_rollback_at",
    )
    return all(_column_exists(cur, "change_requests", column_name) for column_name in required_columns)


def _stage56_schema_ready(cur) -> bool:
    required_tables = ("agent_runs", "agent_messages", "agent_artifacts", "evaluator_runs")
    if not all(_table_exists(cur, table_name) for table_name in required_tables):
        return False
    required_agent_run_columns = (
        "execution_mode",
        "execution_request_json",
        "source_task_run_id",
        "assigned_step_orders_json",
    )
    if not all(_column_exists(cur, "agent_runs", column_name) for column_name in required_agent_run_columns):
        return False
    required_evaluator_columns = ("failure_reason", "failure_stage", "proposal_json")
    return all(_column_exists(cur, "evaluator_runs", column_name) for column_name in required_evaluator_columns)


def build_logger() -> logging.Logger:
    logger = logging.getLogger("ai_assistant.api")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("[%(asctime)s] %(levelname)s %(message)s")

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    try:
        file_handler = logging.FileHandler(LOG_DIR / "api.log", encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except PermissionError:
        logger.warning("api file logger disabled because %s is not writable", LOG_DIR / "api.log")

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


def get_conn():
    return psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)


def ensure_change_requests_table(cur):
    global _change_requests_schema_bootstrapped

    if _change_requests_schema_bootstrapped:
        return

    if _change_requests_schema_ready(cur):
        _change_requests_schema_bootstrapped = True
        return

    with _change_requests_schema_bootstrap_lock:
        if _change_requests_schema_bootstrapped:
            return
        if _change_requests_schema_ready(cur):
            _change_requests_schema_bootstrapped = True
            return

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
                proposal_kind TEXT NOT NULL DEFAULT 'manual_change',
                source_change_request_id INTEGER REFERENCES change_requests(id) ON DELETE SET NULL,
                source_workflow_proposal_id INTEGER,
                shadow_validation_status TEXT NOT NULL DEFAULT 'not_required',
                shadow_validation_report JSONB,
                shadow_validation_at TIMESTAMP,
                baseline_payload JSONB,
                payload_patch JSONB,
                patch_summary TEXT NOT NULL DEFAULT '',
                rollback_payload JSONB,
                rollback_ready BOOLEAN NOT NULL DEFAULT FALSE,
                rollback_note TEXT NOT NULL DEFAULT '',
                acceptance_status TEXT NOT NULL DEFAULT 'not_configured',
                acceptance_report JSONB,
                acceptance_at TIMESTAMP,
                auto_rollback_change_request_id INTEGER REFERENCES change_requests(id) ON DELETE SET NULL,
                auto_rollback_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TIMESTAMP,
                applied_at TIMESTAMP
            );
            """
        )
        cur.execute("ALTER TABLE change_requests ADD COLUMN IF NOT EXISTS proposal_kind TEXT NOT NULL DEFAULT 'manual_change';")
        cur.execute("ALTER TABLE change_requests ADD COLUMN IF NOT EXISTS source_change_request_id INTEGER REFERENCES change_requests(id) ON DELETE SET NULL;")
        cur.execute("ALTER TABLE change_requests ADD COLUMN IF NOT EXISTS source_workflow_proposal_id INTEGER;")
        cur.execute("ALTER TABLE change_requests ADD COLUMN IF NOT EXISTS shadow_validation_status TEXT NOT NULL DEFAULT 'not_required';")
        cur.execute("ALTER TABLE change_requests ADD COLUMN IF NOT EXISTS shadow_validation_report JSONB;")
        cur.execute("ALTER TABLE change_requests ADD COLUMN IF NOT EXISTS shadow_validation_at TIMESTAMP;")
        cur.execute("ALTER TABLE change_requests ADD COLUMN IF NOT EXISTS baseline_payload JSONB;")
        cur.execute("ALTER TABLE change_requests ADD COLUMN IF NOT EXISTS payload_patch JSONB;")
        cur.execute("ALTER TABLE change_requests ADD COLUMN IF NOT EXISTS patch_summary TEXT NOT NULL DEFAULT '';")
        cur.execute("ALTER TABLE change_requests ADD COLUMN IF NOT EXISTS rollback_payload JSONB;")
        cur.execute("ALTER TABLE change_requests ADD COLUMN IF NOT EXISTS rollback_ready BOOLEAN NOT NULL DEFAULT FALSE;")
        cur.execute("ALTER TABLE change_requests ADD COLUMN IF NOT EXISTS rollback_note TEXT NOT NULL DEFAULT '';")
        cur.execute("ALTER TABLE change_requests ADD COLUMN IF NOT EXISTS acceptance_status TEXT NOT NULL DEFAULT 'not_configured';")
        cur.execute("ALTER TABLE change_requests ADD COLUMN IF NOT EXISTS acceptance_report JSONB;")
        cur.execute("ALTER TABLE change_requests ADD COLUMN IF NOT EXISTS acceptance_at TIMESTAMP;")
        cur.execute("ALTER TABLE change_requests ADD COLUMN IF NOT EXISTS auto_rollback_change_request_id INTEGER REFERENCES change_requests(id) ON DELETE SET NULL;")
        cur.execute("ALTER TABLE change_requests ADD COLUMN IF NOT EXISTS auto_rollback_at TIMESTAMP;")
        _change_requests_schema_bootstrapped = True


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
            if _stage56_schema_ready(cur):
                _stage56_schema_bootstrapped = True
                conn.commit()
                return
            ensure_audit_logs_table(cur)
            ensure_agent_tables(cur)
            ensure_evaluator_tables(cur)
            conn.commit()
            _stage56_schema_bootstrapped = True
        finally:
            _stage56_schema_bootstrap_active = False
            cur.close()
            conn.close()


def ensure_runtime_core_schema_bootstrapped():
    global _runtime_core_schema_bootstrap_active, _runtime_core_schema_bootstrapped

    if _runtime_core_schema_bootstrapped:
        return

    with _runtime_core_schema_bootstrap_lock:
        if _runtime_core_schema_bootstrapped:
            return

        conn = get_conn()
        cur = conn.cursor()
        _runtime_core_schema_bootstrap_active = True
        try:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext('runtime_core_schema_bootstrap'));")
            ensure_runtime_core_tables(cur)
            conn.commit()
            _runtime_core_schema_bootstrapped = True
        finally:
            _runtime_core_schema_bootstrap_active = False
            cur.close()
            conn.close()


def ensure_runtime_core_tables(cur):
    if not _runtime_core_schema_bootstrap_active:
        ensure_runtime_core_schema_bootstrapped()
        return

    ensure_sessions_base_table(cur)

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS task_runs (
            id SERIAL PRIMARY KEY,
            user_input TEXT NOT NULL,
            status VARCHAR(50) NOT NULL DEFAULT 'pending',
            result TEXT,
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    cur.execute("ALTER TABLE task_runs ADD COLUMN IF NOT EXISTS current_step INTEGER;")
    cur.execute("ALTER TABLE task_runs ADD COLUMN IF NOT EXISTS checkpoint_path TEXT;")
    cur.execute("ALTER TABLE task_runs ADD COLUMN IF NOT EXISTS session_id INTEGER REFERENCES sessions(id) ON DELETE SET NULL;")
    cur.execute("ALTER TABLE task_runs ADD COLUMN IF NOT EXISTS created_by_actor TEXT;")
    cur.execute("ALTER TABLE task_runs ADD COLUMN IF NOT EXISTS runtime_overrides JSONB;")
    cur.execute("ALTER TABLE task_runs ADD COLUMN IF NOT EXISTS task_intent_json JSONB;")
    cur.execute("ALTER TABLE task_runs ADD COLUMN IF NOT EXISTS deliverable_spec_json JSONB;")
    cur.execute("ALTER TABLE task_runs ADD COLUMN IF NOT EXISTS validation_report_json JSONB;")
    cur.execute("ALTER TABLE task_runs ADD COLUMN IF NOT EXISTS recovery_action_json JSONB;")

    cur.execute(
        """
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
        """
    )
    cur.execute("ALTER TABLE task_steps ADD COLUMN IF NOT EXISTS tool_name TEXT;")
    cur.execute("ALTER TABLE task_steps ADD COLUMN IF NOT EXISTS output_data TEXT;")
    cur.execute("ALTER TABLE task_steps ADD COLUMN IF NOT EXISTS error_strategy TEXT DEFAULT 'fail';")
    cur.execute("ALTER TABLE task_steps ADD COLUMN IF NOT EXISTS run_if TEXT;")
    cur.execute("ALTER TABLE task_steps ADD COLUMN IF NOT EXISTS skip_if TEXT;")
    cur.execute("ALTER TABLE task_steps ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0;")
    cur.execute("ALTER TABLE task_steps ADD COLUMN IF NOT EXISTS max_retries INTEGER NOT NULL DEFAULT 0;")

    ensure_sessions_tables(cur)

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
    ensure_trace_tables(cur)


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


def ensure_trace_tables(cur):
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


def _read_skill_package_from_source(source_path: str) -> dict[str, Any]:
    normalized_path = str(source_path or "").strip()
    if not normalized_path:
        raise HTTPException(status_code=400, detail="source_path is required")
    candidate = (WORKSPACE_ROOT / normalized_path).resolve() if not normalized_path.startswith("/") else Path(normalized_path).resolve()
    roots = [WORKSPACE_ROOT.resolve(), API_APP_DIR.parent.resolve()]
    if not any(str(candidate).startswith(str(root)) for root in roots):
        raise HTTPException(status_code=400, detail="skill package path must stay inside repo")
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="skill package source not found")
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid skill package json: {exc}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="skill package must be a json object")
    skill_id = str(payload.get("skill_id") or "").strip()
    version = str(payload.get("version") or "").strip()
    steps_template = payload.get("steps_template")
    if not skill_id or not version:
        raise HTTPException(status_code=400, detail="skill package requires skill_id and version")
    if not isinstance(steps_template, list) or not steps_template:
        raise HTTPException(status_code=400, detail="skill package requires non-empty steps_template")
    return {
        "skill_id": skill_id,
        "display_name": str(payload.get("display_name") or skill_id),
        "description": str(payload.get("description") or ""),
        "entrypoint_kind": str(payload.get("entrypoint_kind") or "structured_steps"),
        "version": version,
        "package_format": "json",
        "package_source": str(candidate),
        "package_body": payload,
    }


def ensure_agent_tables(cur):
    global _stage56_schema_bootstrapped

    if _stage56_schema_bootstrapped:
        return
    if _stage56_schema_ready(cur):
        _stage56_schema_bootstrapped = True
        return
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
    _stage56_schema_bootstrapped = _stage56_schema_ready(cur)


def ensure_evaluator_tables(cur):
    global _stage56_schema_bootstrapped

    if _stage56_schema_bootstrapped:
        return
    if _stage56_schema_ready(cur):
        _stage56_schema_bootstrapped = True
        return
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
    _stage56_schema_bootstrapped = _stage56_schema_ready(cur)


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


def build_task_display_input_excerpt(task_row: dict[str, Any], limit: int = 180) -> str:
    runtime_overrides = parse_maybe_json(task_row.get("runtime_overrides")) or {}
    return build_task_display_user_input(
        str(task_row.get("user_input") or ""),
        runtime_overrides,
    )[:limit]


def build_task_result_excerpt(task_row: dict[str, Any], limit: int = 220) -> str:
    return strip_artifact_suffix(str(task_row.get("result") or ""))[:limit]


def attach_task_display_fields(task_row: dict[str, Any]) -> dict[str, Any]:
    runtime_overrides = parse_maybe_json(task_row.get("runtime_overrides")) or {}
    original_user_input, clarification_history = extract_task_clarification_state(
        runtime_overrides,
        fallback_user_input=str(task_row.get("user_input") or ""),
    )
    task_row["display_user_input"] = build_task_display_user_input(
        str(task_row.get("user_input") or ""),
        runtime_overrides,
    )
    task_row["original_user_input"] = original_user_input
    task_row["clarification_count"] = len(clarification_history)
    task_row["result_excerpt"] = build_task_result_excerpt(task_row)
    return task_row


def build_shadow_validation_runtime_overrides(
    *,
    proposal_id: int,
    validation_mode: str,
    candidate_overlay: dict[str, Any] | None = None,
    source_change_request_id: int | None = None,
) -> dict[str, Any]:
    overlay = candidate_overlay or {}
    runtime_overrides: dict[str, Any] = {
        "shadow_validation": {
            "proposal_id": int(proposal_id),
            "validation_mode": validation_mode,
        }
    }
    if source_change_request_id is not None:
        runtime_overrides["shadow_validation"]["source_change_request_id"] = int(source_change_request_id)
    if overlay:
        runtime_overrides["shadow_validation"]["candidate_overlay"] = make_json_compatible(overlay)
    if (
        str(overlay.get("target_type") or "").strip() == "model_route"
        and str(overlay.get("target_key") or "").strip()
        and isinstance(overlay.get("proposed_payload"), dict)
    ):
        runtime_overrides["model_route_overrides"] = {
            str(overlay["target_key"]).strip(): make_json_compatible(overlay.get("proposed_payload") or {})
        }
    return runtime_overrides


SUPPORTED_CHANGE_TARGET_TYPES = {
    "risk_policy",
    "tool_registry",
    "model_route",
    "model_provider",
    "access_quota",
    "access_actor",
    "sandbox_file",
}
def resolve_sandbox_change_path(target_key: str) -> Path:
    raw_target_key = str(target_key or "").strip()
    if not raw_target_key:
        raise HTTPException(status_code=400, detail="sandbox_file target_key is required")
    if raw_target_key.startswith(("/", "\\")):
        raise HTTPException(status_code=400, detail="sandbox_file target_key must be a relative path")
    candidate = (SANDBOX_CHANGE_ROOT / raw_target_key).resolve()
    try:
        candidate.relative_to(SANDBOX_CHANGE_ROOT)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="sandbox_file target_key must stay within sandbox root") from exc
    if candidate == SANDBOX_CHANGE_ROOT:
        raise HTTPException(status_code=400, detail="sandbox_file target_key must point to a file")
    return candidate


def resolve_workspace_source_path(source_path: str) -> Path:
    raw_source_path = str(source_path or "").strip()
    if not raw_source_path:
        raise HTTPException(status_code=400, detail="sandbox_file source_path must be a non-empty string")
    candidate = Path(raw_source_path)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (WORKSPACE_ROOT / candidate).resolve()
    try:
        resolved.relative_to(WORKSPACE_ROOT)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="sandbox_file source_path must stay within workspace root") from exc
    try:
        resolved.relative_to(SANDBOX_CHANGE_ROOT)
    except ValueError:
        pass
    else:
        raise HTTPException(status_code=400, detail="sandbox_file source_path must point outside sandbox root")
    if resolved == WORKSPACE_ROOT:
        raise HTTPException(status_code=400, detail="sandbox_file source_path must point to a file")
    if not resolved.exists():
        raise HTTPException(status_code=404, detail=f"sandbox_file source_path not found: {raw_source_path}")
    if resolved.is_dir():
        raise HTTPException(status_code=400, detail=f"sandbox_file source_path points to a directory: {raw_source_path}")
    return resolved


def read_workspace_source_file_snapshot(source_path: str) -> tuple[str, dict[str, Any]]:
    path = resolve_workspace_source_path(source_path)
    size_bytes = path.stat().st_size
    if size_bytes > SANDBOX_FILE_CONTENT_LIMIT_BYTES:
        raise HTTPException(
            status_code=400,
            detail=(
                "sandbox_file source_path exceeds "
                f"{SANDBOX_FILE_CONTENT_LIMIT_BYTES} bytes: {source_path}"
            ),
        )
    try:
        content = path.read_text(encoding=SANDBOX_FILE_ENCODING)
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"sandbox_file source_path is not valid {SANDBOX_FILE_ENCODING}: {source_path}",
        ) from exc
    encoded_content = content.encode(SANDBOX_FILE_ENCODING)
    return content, {
        "source_kind": "workspace_file",
        "source_path": path.relative_to(WORKSPACE_ROOT).as_posix(),
        "source_hash": hashlib.sha256(encoded_content).hexdigest(),
        "source_size_bytes": len(encoded_content),
    }


def resolve_workspace_acceptance_script_path(script_path: str) -> Path:
    raw_script_path = str(script_path or "").strip()
    if not raw_script_path:
        raise HTTPException(status_code=400, detail="sandbox_file acceptance script_path must be a non-empty string")
    candidate = Path(raw_script_path)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (WORKSPACE_ROOT / candidate).resolve()
    try:
        resolved.relative_to(WORKSPACE_ROOT)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="sandbox_file acceptance script_path must stay within workspace root",
        ) from exc
    try:
        resolved.relative_to(SANDBOX_ACCEPTANCE_SCRIPTS_ROOT)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="sandbox_file acceptance script_path must stay within workspace scripts/",
        ) from exc
    if resolved == WORKSPACE_ROOT or resolved == SANDBOX_ACCEPTANCE_SCRIPTS_ROOT:
        raise HTTPException(status_code=400, detail="sandbox_file acceptance script_path must point to a file")
    if not resolved.exists():
        raise HTTPException(
            status_code=404,
            detail=f"sandbox_file acceptance script_path not found: {raw_script_path}",
        )
    if resolved.is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"sandbox_file acceptance script_path points to a directory: {raw_script_path}",
        )
    return resolved


def normalize_sandbox_file_acceptance_payload(acceptance_payload: Any) -> dict[str, Any]:
    if acceptance_payload is None:
        return {}
    if not isinstance(acceptance_payload, dict):
        raise HTTPException(status_code=400, detail="sandbox_file acceptance must be a JSON object")
    script_path_value = acceptance_payload.get("script_path")
    if not isinstance(script_path_value, str) or not script_path_value.strip():
        raise HTTPException(
            status_code=400,
            detail="sandbox_file acceptance script_path must be a non-empty string",
        )
    timeout_raw = acceptance_payload.get("timeout_seconds", SANDBOX_FILE_ACCEPTANCE_DEFAULT_TIMEOUT_SECONDS)
    try:
        timeout_seconds = int(timeout_raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="sandbox_file acceptance timeout_seconds must be an integer") from exc
    if timeout_seconds <= 0 or timeout_seconds > SANDBOX_FILE_ACCEPTANCE_MAX_TIMEOUT_SECONDS:
        raise HTTPException(
            status_code=400,
            detail=(
                "sandbox_file acceptance timeout_seconds must be between 1 and "
                f"{SANDBOX_FILE_ACCEPTANCE_MAX_TIMEOUT_SECONDS}"
            ),
        )
    env_payload = acceptance_payload.get("env") or {}
    if not isinstance(env_payload, dict):
        raise HTTPException(status_code=400, detail="sandbox_file acceptance env must be a JSON object when provided")
    if len(env_payload) > SANDBOX_FILE_ACCEPTANCE_MAX_ENV_VARS:
        raise HTTPException(
            status_code=400,
            detail=(
                "sandbox_file acceptance env exceeds "
                f"{SANDBOX_FILE_ACCEPTANCE_MAX_ENV_VARS} entries"
            ),
        )
    normalized_env: dict[str, str] = {}
    env_bytes = 0
    for raw_key in sorted(env_payload.keys()):
        key = str(raw_key or "").strip()
        if not SANDBOX_FILE_ACCEPTANCE_ENV_KEY_RE.fullmatch(key):
            raise HTTPException(
                status_code=400,
                detail=f"sandbox_file acceptance env key is invalid: {raw_key}",
            )
        raw_value = env_payload.get(raw_key)
        if raw_value is None:
            value = ""
        elif isinstance(raw_value, (str, int, float, bool)):
            value = str(raw_value)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"sandbox_file acceptance env value must be scalar: {key}",
            )
        env_bytes += len(key.encode("utf-8")) + len(value.encode("utf-8"))
        if env_bytes > SANDBOX_FILE_ACCEPTANCE_MAX_ENV_BYTES:
            raise HTTPException(
                status_code=400,
                detail=(
                    "sandbox_file acceptance env exceeds "
                    f"{SANDBOX_FILE_ACCEPTANCE_MAX_ENV_BYTES} bytes"
                ),
            )
        normalized_env[key] = value
    script_path = resolve_workspace_acceptance_script_path(script_path_value)
    script_bytes = script_path.read_bytes()
    return {
        "script_path": script_path.relative_to(WORKSPACE_ROOT).as_posix(),
        "timeout_seconds": timeout_seconds,
        "env": normalized_env,
        "script_hash": hashlib.sha256(script_bytes).hexdigest(),
        "script_size_bytes": len(script_bytes),
    }


def clip_sandbox_file_acceptance_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = str(value)
    if len(text) <= SANDBOX_FILE_ACCEPTANCE_OUTPUT_LIMIT:
        return text
    return text[:SANDBOX_FILE_ACCEPTANCE_OUTPUT_LIMIT] + "\n...[truncated]"


def execute_sandbox_file_acceptance(
    *,
    change_request_id: int,
    target_key: str,
    normalized_payload: dict[str, Any],
) -> tuple[str, dict[str, Any], datetime]:
    acceptance = normalized_payload.get("acceptance") or {}
    if not isinstance(acceptance, dict) or not acceptance:
        finished_at = datetime.now(timezone.utc)
        return "not_configured", {}, finished_at

    script_path = resolve_workspace_acceptance_script_path(acceptance.get("script_path") or "")
    timeout_seconds = int(acceptance.get("timeout_seconds") or SANDBOX_FILE_ACCEPTANCE_DEFAULT_TIMEOUT_SECONDS)
    started_at = datetime.now(timezone.utc)
    start = time.perf_counter()
    sandbox_path = resolve_sandbox_change_path(target_key)
    environment = os.environ.copy()
    environment.update({
        "STAGE7_CHANGE_REQUEST_ID": str(change_request_id),
        "STAGE7_TARGET_TYPE": "sandbox_file",
        "STAGE7_SANDBOX_TARGET_KEY": target_key,
        "STAGE7_SANDBOX_ROOT": str(SANDBOX_CHANGE_ROOT),
        "STAGE7_SANDBOX_FILE": str(sandbox_path),
        "STAGE7_WORKSPACE_ROOT": str(WORKSPACE_ROOT),
    })
    source_copy = normalized_payload.get("source_copy") or {}
    if isinstance(source_copy.get("source_path"), str) and source_copy.get("source_path"):
        environment["STAGE7_SOURCE_PATH"] = str(source_copy.get("source_path"))
    environment.update({
        str(key): str(value)
        for key, value in (acceptance.get("env") or {}).items()
    })

    report: dict[str, Any] = {
        "script_path": script_path.relative_to(WORKSPACE_ROOT).as_posix(),
        "timeout_seconds": timeout_seconds,
        "env_keys": sorted((acceptance.get("env") or {}).keys()),
        "started_at": started_at.isoformat(),
    }
    try:
        completed = subprocess.run(
            ["/bin/bash", str(script_path)],
            cwd=str(WORKSPACE_ROOT),
            env=environment,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        finished_at = datetime.now(timezone.utc)
        duration_ms = int(max(time.perf_counter() - start, 0.0) * 1000)
        status = "passed" if completed.returncode == 0 else "failed"
        report.update({
            "status": status,
            "passed": completed.returncode == 0,
            "exit_code": int(completed.returncode),
            "duration_ms": duration_ms,
            "stdout": clip_sandbox_file_acceptance_output(completed.stdout),
            "stderr": clip_sandbox_file_acceptance_output(completed.stderr),
            "timed_out": False,
        })
        return status, report, finished_at
    except subprocess.TimeoutExpired as exc:
        finished_at = datetime.now(timezone.utc)
        duration_ms = int(max(time.perf_counter() - start, 0.0) * 1000)
        report.update({
            "status": "timed_out",
            "passed": False,
            "exit_code": None,
            "duration_ms": duration_ms,
            "stdout": clip_sandbox_file_acceptance_output(exc.stdout),
            "stderr": clip_sandbox_file_acceptance_output(exc.stderr),
            "timed_out": True,
        })
        return "timed_out", report, finished_at
    except Exception as exc:
        finished_at = datetime.now(timezone.utc)
        duration_ms = int(max(time.perf_counter() - start, 0.0) * 1000)
        logger.exception("sandbox_file acceptance execution failed change_request_id=%s", change_request_id)
        report.update({
            "status": "error",
            "passed": False,
            "exit_code": None,
            "duration_ms": duration_ms,
            "stdout": "",
            "stderr": clip_sandbox_file_acceptance_output(str(exc)),
            "timed_out": False,
            "error_type": type(exc).__name__,
        })
        return "error", report, finished_at


def apply_unified_patch_to_text(source_content: str, patch_text: str) -> tuple[str, dict[str, Any]]:
    patch_value = str(patch_text or "")
    if not patch_value.strip():
        raise HTTPException(status_code=400, detail="sandbox_file patch must be a non-empty string when provided")

    source_lines = source_content.splitlines(keepends=True)
    patch_lines = patch_value.splitlines(keepends=True)
    output_lines: list[str] = []
    source_index = 0
    line_index = 0
    hunk_count = 0
    added_line_count = 0
    removed_line_count = 0
    allowed_header_prefixes = ("diff --git ", "index ", "--- ", "+++ ")

    while line_index < len(patch_lines):
        header_line = patch_lines[line_index]
        if header_line.startswith("@@"):
            break
        if header_line.startswith(allowed_header_prefixes) or not header_line.strip():
            line_index += 1
            continue
        raise HTTPException(status_code=400, detail="sandbox_file patch must be a unified diff with at least one hunk")

    while line_index < len(patch_lines):
        raw_header = patch_lines[line_index].rstrip("\n")
        match = SANDBOX_FILE_UNIFIED_HUNK_RE.match(raw_header)
        if not match:
            raise HTTPException(status_code=400, detail=f"sandbox_file patch has invalid hunk header: {raw_header}")

        old_start = int(match.group("old_start"))
        old_count = int(match.group("old_count") or "1")
        new_count = int(match.group("new_count") or "1")
        hunk_source_index = old_start if old_count == 0 else max(old_start - 1, 0)
        if hunk_source_index < source_index or hunk_source_index > len(source_lines):
            raise HTTPException(status_code=400, detail=f"sandbox_file patch hunk points outside source content: {raw_header}")

        output_lines.extend(source_lines[source_index:hunk_source_index])
        source_index = hunk_source_index
        line_index += 1
        hunk_count += 1
        consumed_old = 0
        consumed_new = 0

        while line_index < len(patch_lines):
            patch_line = patch_lines[line_index]
            if patch_line.startswith("@@"):
                break
            if patch_line.startswith("\\"):
                line_index += 1
                continue
            if not patch_line:
                raise HTTPException(status_code=400, detail="sandbox_file patch contains an empty diff line")

            prefix = patch_line[0]
            diff_content = patch_line[1:]
            source_line = source_lines[source_index] if source_index < len(source_lines) else None

            if prefix == " ":
                if source_line != diff_content:
                    raise HTTPException(
                        status_code=400,
                        detail=f"sandbox_file patch context mismatch near source line {source_index + 1}",
                    )
                output_lines.append(source_line)
                source_index += 1
                consumed_old += 1
                consumed_new += 1
            elif prefix == "-":
                if source_line != diff_content:
                    raise HTTPException(
                        status_code=400,
                        detail=f"sandbox_file patch removal mismatch near source line {source_index + 1}",
                    )
                source_index += 1
                consumed_old += 1
                removed_line_count += 1
            elif prefix == "+":
                output_lines.append(diff_content)
                consumed_new += 1
                added_line_count += 1
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"sandbox_file patch has invalid diff line prefix: {prefix!r}",
                )
            line_index += 1

        if consumed_old != old_count or consumed_new != new_count:
            raise HTTPException(
                status_code=400,
                detail=(
                    "sandbox_file patch hunk length mismatch: "
                    f"expected -{old_count}/+{new_count}, got -{consumed_old}/+{consumed_new}"
                ),
            )

    if hunk_count == 0:
        raise HTTPException(status_code=400, detail="sandbox_file patch must include at least one hunk")

    output_lines.extend(source_lines[source_index:])
    patched_content = "".join(output_lines)
    return patched_content, {
        "format": "unified_diff",
        "hunk_count": hunk_count,
        "added_line_count": added_line_count,
        "removed_line_count": removed_line_count,
        "line_count": len(patch_value.splitlines()),
    }


def normalize_sandbox_file_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="sandbox_file proposed_payload must be a JSON object")
    encoding = str(payload.get("encoding") or SANDBOX_FILE_ENCODING).strip().lower() or SANDBOX_FILE_ENCODING
    if encoding != SANDBOX_FILE_ENCODING:
        raise HTTPException(status_code=400, detail=f"sandbox_file only supports {SANDBOX_FILE_ENCODING} encoding")
    acceptance = normalize_sandbox_file_acceptance_payload(payload.get("acceptance"))
    exists_value = payload.get("exists")
    if exists_value is None:
        exists = True
    elif isinstance(exists_value, bool):
        exists = exists_value
    else:
        raise HTTPException(status_code=400, detail="sandbox_file exists must be a boolean when provided")
    source_content = ""
    source_copy: dict[str, Any] = {}
    if "source_path" in payload:
        if not exists:
            raise HTTPException(status_code=400, detail="sandbox_file source_path cannot be used when exists=false")
        source_path_value = payload.get("source_path")
        if not isinstance(source_path_value, str) or not source_path_value.strip():
            raise HTTPException(status_code=400, detail="sandbox_file source_path must be a non-empty string when provided")
        source_content, source_copy = read_workspace_source_file_snapshot(source_path_value)
    content_value = payload.get("content")
    patch_input: dict[str, Any] = {}
    patch_applied: dict[str, Any] = {}
    patch_value = payload.get("patch")
    if patch_value is not None:
        if not exists:
            raise HTTPException(status_code=400, detail="sandbox_file patch cannot be used when exists=false")
        if isinstance(content_value, str):
            raise HTTPException(status_code=400, detail="sandbox_file content and patch cannot be provided together")
        if not source_copy:
            raise HTTPException(status_code=400, detail="sandbox_file patch requires source_path")
        if not isinstance(patch_value, str) or not patch_value.strip():
            raise HTTPException(status_code=400, detail="sandbox_file patch must be a non-empty string when provided")
        content, patch_stats = apply_unified_patch_to_text(source_content, patch_value)
        patch_bytes = patch_value.encode(SANDBOX_FILE_ENCODING)
        patch_input = {
            "format": "unified_diff",
            "input_hash": hashlib.sha256(patch_bytes).hexdigest(),
            "input_size_bytes": len(patch_bytes),
            "line_count": patch_stats["line_count"],
        }
        patch_applied = {
            "format": "unified_diff",
            "base_kind": "source_copy",
            "base_source_path": source_copy.get("source_path"),
            "base_source_hash": source_copy.get("source_hash"),
            "hunk_count": patch_stats["hunk_count"],
            "added_line_count": patch_stats["added_line_count"],
            "removed_line_count": patch_stats["removed_line_count"],
            "content_changed": content != source_content,
        }
    if exists:
        if patch_value is not None:
            pass
        elif isinstance(content_value, str):
            content = content_value
        elif source_copy:
            content = source_content
        else:
            raise HTTPException(status_code=400, detail="sandbox_file content is required when exists=true")
    else:
        content = ""
    if len(content.encode(SANDBOX_FILE_ENCODING)) > SANDBOX_FILE_CONTENT_LIMIT_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"sandbox_file content exceeds {SANDBOX_FILE_CONTENT_LIMIT_BYTES} bytes",
        )
    normalized_payload = {
        "exists": exists,
        "content": content,
        "encoding": SANDBOX_FILE_ENCODING,
    }
    if source_copy:
        normalized_payload["source_copy"] = {
            **source_copy,
            "content_matches_source": content == source_content,
        }
    if patch_input:
        normalized_payload["patch_input"] = patch_input
    if patch_applied:
        normalized_payload["patch_applied"] = patch_applied
    if acceptance:
        normalized_payload["acceptance"] = acceptance
    return normalized_payload


def normalize_change_request_payload(target_type: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="proposed_payload must be a JSON object")
    if target_type == "sandbox_file":
        return normalize_sandbox_file_payload(payload)
    return make_json_compatible(payload)


def fetch_sandbox_file_state(target_key: str) -> dict[str, Any]:
    path = resolve_sandbox_change_path(target_key)
    if path.exists() and path.is_dir():
        raise HTTPException(status_code=400, detail=f"sandbox_file target points to a directory: {target_key}")
    if not path.exists():
        return {
            "exists": False,
            "content": "",
            "encoding": SANDBOX_FILE_ENCODING,
        }
    if path.stat().st_size > SANDBOX_FILE_CONTENT_LIMIT_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"sandbox_file target exceeds {SANDBOX_FILE_CONTENT_LIMIT_BYTES} bytes: {target_key}",
        )
    try:
        content = path.read_text(encoding=SANDBOX_FILE_ENCODING)
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"sandbox_file target is not valid {SANDBOX_FILE_ENCODING}: {target_key}",
        ) from exc
    return {
        "exists": True,
        "content": content,
        "encoding": SANDBOX_FILE_ENCODING,
    }


def serialize_shadow_validation_audit_row_with_context(row: dict[str, Any]) -> dict[str, Any]:
    return serialize_shadow_validation_audit_row(
        row,
        make_json_compatible_fn=make_json_compatible,
        parse_maybe_json_fn=parse_maybe_json,
        parse_optional_int_fn=parse_optional_int,
    )


def fetch_workflow_proposal_shadow_validation_history_with_context(
    cur,
    proposal_id: int,
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    return fetch_workflow_proposal_shadow_validation_history(
        cur,
        proposal_id,
        limit=limit,
        ensure_audit_logs_table_fn=ensure_audit_logs_table,
        request_event=WORKFLOW_PROPOSAL_SHADOW_VALIDATION_REQUEST_EVENT,
        result_event=WORKFLOW_PROPOSAL_SHADOW_VALIDATION_RESULT_EVENT,
        serialize_shadow_validation_audit_row_fn=serialize_shadow_validation_audit_row_with_context,
    )


def fetch_task_run_brief_with_context(cur, task_id: int | None) -> dict[str, Any] | None:
    return fetch_task_run_brief(
        cur,
        task_id,
        parse_optional_int_fn=parse_optional_int,
        parse_maybe_json_fn=parse_maybe_json,
    )


def fetch_latest_workflow_proposal_shadow_validation_with_context(
    cur,
    proposal_id: int,
    *,
    target_type: str = "",
    target_key: str = "",
    proposed_payload: dict[str, Any] | None = None,
    history_limit: int = 50,
) -> dict[str, Any] | None:
    return fetch_latest_workflow_proposal_shadow_validation(
        cur,
        proposal_id,
        target_type=target_type,
        target_key=target_key,
        proposed_payload=proposed_payload,
        history_limit=history_limit,
        fetch_workflow_proposal_shadow_validation_history_fn=fetch_workflow_proposal_shadow_validation_history_with_context,
        result_event=WORKFLOW_PROPOSAL_SHADOW_VALIDATION_RESULT_EVENT,
        shadow_validation_candidate_matches_fn=shadow_validation_candidate_matches,
    )


def build_workflow_proposal_shadow_validation_status_with_context(
    cur,
    proposal_id: int,
    *,
    history_limit: int = 10,
    supported: bool = True,
) -> dict[str, Any]:
    return build_workflow_proposal_shadow_validation_status(
        cur,
        proposal_id,
        history_limit=history_limit,
        supported=supported,
        fetch_workflow_proposal_shadow_validation_history_fn=fetch_workflow_proposal_shadow_validation_history_with_context,
        fetch_task_run_brief_fn=fetch_task_run_brief_with_context,
        parse_optional_int_fn=parse_optional_int,
        request_event=WORKFLOW_PROPOSAL_SHADOW_VALIDATION_REQUEST_EVENT,
        result_event=WORKFLOW_PROPOSAL_SHADOW_VALIDATION_RESULT_EVENT,
    )


def build_change_request_shadow_validation_state_with_context(
    cur,
    *,
    proposal_kind: str | None,
    source_workflow_proposal_id: int | None,
    target_type: str = "",
    target_key: str = "",
    proposed_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_change_request_shadow_validation_state(
        proposal_kind=proposal_kind,
        source_workflow_proposal_id=source_workflow_proposal_id,
        target_type=target_type,
        target_key=target_key,
        proposed_payload=proposed_payload,
        normalize_change_request_proposal_kind_fn=normalize_change_request_proposal_kind,
        change_request_requires_shadow_validation_fn=change_request_requires_shadow_validation,
        fetch_latest_workflow_proposal_shadow_validation_fn=lambda proposal_id, **kwargs: (
            fetch_latest_workflow_proposal_shadow_validation_with_context(cur, proposal_id, **kwargs)
        ),
        annotate_shadow_validation_report_for_change_request_fn=lambda validation_report, **kwargs: (
            annotate_shadow_validation_report_for_change_request(
                validation_report,
                make_json_compatible_fn=make_json_compatible,
                shadow_validation_candidate_matches_fn=shadow_validation_candidate_matches,
                compute_stable_payload_hash_fn=compute_stable_payload_hash,
                **kwargs,
            )
        ),
    )


def sync_change_requests_shadow_validation_with_context(cur, proposal_id: int) -> int:
    return sync_change_requests_shadow_validation(
        cur,
        proposal_id,
        ensure_change_requests_table_fn=ensure_change_requests_table,
        parse_maybe_json_fn=parse_maybe_json,
        parse_optional_int_fn=parse_optional_int,
        build_change_request_shadow_validation_state_fn=lambda **kwargs: (
            build_change_request_shadow_validation_state_with_context(cur, **kwargs)
        ),
        safe_json_dumps_fn=safe_json_dumps,
    )


def create_change_request_row(
    cur,
    *,
    target_type: str,
    target_key: str,
    proposed_payload: dict[str, Any],
    rationale: str,
    requested_by_actor: str,
    proposal_kind: str = "manual_change",
    source_change_request_id: int | None = None,
    source_workflow_proposal_id: int | None = None,
) -> dict[str, Any]:
    ensure_change_requests_table(cur)
    normalized_proposal_kind = normalize_change_request_proposal_kind(proposal_kind)
    change_request_payload = build_change_request_create_payload(
        target_type=target_type,
        target_key=target_key,
        proposed_payload=proposed_payload,
        rationale=rationale,
        requested_by_actor=requested_by_actor,
        proposal_kind=normalized_proposal_kind,
        source_change_request_id=source_change_request_id,
        source_workflow_proposal_id=source_workflow_proposal_id,
        normalize_change_request_payload_fn=normalize_change_request_payload,
        build_change_request_patch_artifacts_fn=lambda **kwargs: build_change_request_patch_artifacts_with_context(cur, **kwargs),
        build_change_request_shadow_validation_state_fn=lambda **kwargs: (
            build_change_request_shadow_validation_state_with_context(cur, **kwargs)
        ),
    )
    return insert_change_request_row(
        cur,
        change_request_payload=change_request_payload,
        safe_json_dumps_fn=safe_json_dumps,
    )


def fetch_change_target_state_for_rollback_with_context(
    cur,
    *,
    target_type: str,
    target_key: str,
) -> dict[str, Any] | None:
    return fetch_change_target_state_for_rollback(
        cur,
        target_type=target_type,
        target_key=target_key,
        fetch_sandbox_file_state_fn=fetch_sandbox_file_state,
        seed_default_risk_policies_fn=seed_default_risk_policies,
        deserialize_policy_row_fn=deserialize_policy_row,
        seed_default_tool_registry_fn=seed_default_tool_registry,
        serialize_tool_registry_row_fn=serialize_tool_registry_row,
        seed_default_model_providers_fn=seed_default_model_providers,
        seed_default_model_routes_fn=seed_default_model_routes,
        serialize_model_route_row_fn=serialize_model_route_row,
        serialize_model_provider_row_fn=serialize_model_provider_row,
        seed_default_access_quotas_fn=seed_default_access_quotas,
        serialize_access_quota_row_fn=serialize_access_quota_row,
        seed_default_access_actors_fn=seed_default_access_actors,
        serialize_access_actor_row_fn=serialize_access_actor_row,
    )


def build_change_request_patch_artifacts_with_context(
    cur,
    *,
    target_type: str,
    target_key: str,
    proposed_payload: dict[str, Any],
    baseline_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_change_request_patch_artifacts(
        target_type=target_type,
        target_key=target_key,
        proposed_payload=proposed_payload,
        baseline_payload=baseline_payload,
        normalize_change_request_payload_fn=normalize_change_request_payload,
        fetch_change_target_state_for_rollback_fn=lambda **kwargs: (
            fetch_change_target_state_for_rollback_with_context(cur, **kwargs)
        ),
        compute_change_payload_patch_fn=compute_change_payload_patch,
    )


def attach_patch_artifacts_to_change_request_draft_with_context(cur, draft: dict[str, Any]) -> dict[str, Any]:
    return attach_patch_artifacts_to_change_request_draft(
        draft=draft,
        normalize_change_request_payload_fn=normalize_change_request_payload,
        build_change_request_patch_artifacts_fn=lambda **kwargs: (
            build_change_request_patch_artifacts_with_context(cur, **kwargs)
        ),
    )


def attach_shadow_validation_state_to_change_request_draft_with_context(cur, draft: dict[str, Any]) -> dict[str, Any]:
    return attach_shadow_validation_state_to_change_request_draft(
        draft=draft,
        normalize_change_request_payload_fn=normalize_change_request_payload,
        change_request_requires_shadow_validation_fn=change_request_requires_shadow_validation,
        build_change_request_shadow_validation_state_fn=lambda **kwargs: (
            build_change_request_shadow_validation_state_with_context(cur, **kwargs)
        ),
    )


def is_change_gate_enforced(target_type: str) -> bool:
    return target_type in DEFAULT_ENFORCED_CHANGE_TARGET_TYPES


def enforce_change_gate_for_direct_update(target_type: str):
    if is_change_gate_enforced(target_type):
        raise HTTPException(
            status_code=409,
            detail=f"Direct update disabled for {target_type}; submit and apply a change request instead",
        )


def _apply_sandbox_file_payload(target_key: str, normalized_payload: dict[str, Any]):
    path = resolve_sandbox_change_path(target_key)
    if normalized_payload["exists"]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(normalized_payload["content"], encoding=SANDBOX_FILE_ENCODING)
    elif path.exists():
        if path.is_dir():
            raise HTTPException(status_code=400, detail=f"sandbox_file target points to a directory: {target_key}")
        path.unlink()


def _apply_risk_policy_payload(cur, target_key: str, payload: dict[str, Any]):
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


def _apply_tool_registry_payload(cur, target_key: str, payload: dict[str, Any]):
    seed_default_tool_registry(cur)
    risk_level = str(payload.get("risk_level") or "").strip().lower()
    if risk_level not in {"low", "medium", "high"}:
        raise HTTPException(status_code=400, detail=f"Unsupported risk level: {risk_level}")
    provider_type = str(payload.get("provider_type") or "builtin").strip().lower()
    if provider_type not in {"builtin", "mcp_stdio", "mcp_http"}:
        raise HTTPException(status_code=400, detail=f"Unsupported provider_type: {provider_type}")
    transport = str(payload.get("transport") or ("local" if provider_type == "builtin" else "")).strip().lower()
    if transport not in {"", "local", "stdio", "http"}:
        raise HTTPException(status_code=400, detail=f"Unsupported transport: {transport}")
    cur.execute(
        """
        INSERT INTO tool_registry_entries (
            tool_name,
            enabled,
            provider_type,
            transport,
            server_name,
            provider_config,
            risk_level,
            approval_required,
            description
        )
        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
        ON CONFLICT (tool_name) DO UPDATE
        SET enabled = EXCLUDED.enabled,
            provider_type = EXCLUDED.provider_type,
            transport = EXCLUDED.transport,
            server_name = EXCLUDED.server_name,
            provider_config = EXCLUDED.provider_config,
            risk_level = EXCLUDED.risk_level,
            approval_required = EXCLUDED.approval_required,
            description = EXCLUDED.description,
            updated_at = CURRENT_TIMESTAMP;
        """,
        (
            target_key,
            bool(payload.get("enabled")),
            provider_type,
            transport,
            str(payload.get("server_name") or "").strip(),
            safe_json_dumps(payload.get("provider_config") or {}),
            risk_level,
            bool(payload.get("approval_required")),
            str(payload.get("description") or "").strip(),
        ),
    )


def _apply_model_route_payload(cur, target_key: str, payload: dict[str, Any]):
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


def _apply_model_provider_payload(cur, target_key: str, payload: dict[str, Any]):
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


def _apply_access_quota_payload(cur, target_key: str, payload: dict[str, Any]):
    seed_default_access_quotas(cur)
    cur.execute(
        """
        UPDATE access_quotas
        SET daily_task_limit = %s,
            active_task_limit = %s,
            daily_token_limit = %s,
            max_parallel_agents = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE actor_name = %s;
        """,
        (
            int(payload.get("daily_task_limit") or 0),
            int(payload.get("active_task_limit") or 0),
            int(payload.get("daily_token_limit") or 0),
            int(payload.get("max_parallel_agents") or 0),
            target_key,
        ),
    )
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail=f"Quota not found for actor: {target_key}")


def _apply_access_actor_payload(cur, target_key: str, payload: dict[str, Any]):
    seed_default_access_actors(cur)
    role = str(payload.get("role") or "").strip()
    if role not in ACCESS_ROLE_PERMISSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported role: {role}")
    permission_overrides = [
        str(item).strip().lower()
        for item in (payload.get("permission_overrides") or [])
        if str(item).strip()
    ]
    cur.execute(
        """
        INSERT INTO access_actors (actor_name, role, description, tenant_key, permission_overrides)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (actor_name)
        DO UPDATE SET role = EXCLUDED.role,
                      description = EXCLUDED.description,
                      tenant_key = EXCLUDED.tenant_key,
                      permission_overrides = EXCLUDED.permission_overrides,
                      updated_at = CURRENT_TIMESTAMP;
        """,
        (
            target_key,
            role,
            str(payload.get("description") or "").strip(),
            str(payload.get("tenant_key") or "default").strip() or "default",
            safe_json_dumps(permission_overrides),
        ),
    )
    upsert_default_access_quota(cur, target_key, role)


def apply_change_request_payload_with_context(cur, target_type: str, target_key: str, payload: dict[str, Any]):
    return apply_change_request_payload(
        target_type=target_type,
        target_key=target_key,
        payload=payload,
        normalize_sandbox_file_payload_fn=normalize_sandbox_file_payload,
        apply_sandbox_file_payload_fn=lambda current_target_key, normalized_payload: _apply_sandbox_file_payload(
            current_target_key,
            normalized_payload,
        ),
        apply_risk_policy_fn=lambda current_target_key, current_payload: _apply_risk_policy_payload(
            cur,
            current_target_key,
            current_payload,
        ),
        apply_tool_registry_fn=lambda current_target_key, current_payload: _apply_tool_registry_payload(
            cur,
            current_target_key,
            current_payload,
        ),
        apply_model_route_fn=lambda current_target_key, current_payload: _apply_model_route_payload(
            cur,
            current_target_key,
            current_payload,
        ),
        apply_model_provider_fn=lambda current_target_key, current_payload: _apply_model_provider_payload(
            cur,
            current_target_key,
            current_payload,
        ),
        apply_access_quota_fn=lambda current_target_key, current_payload: _apply_access_quota_payload(
            cur,
            current_target_key,
            current_payload,
        ),
        apply_access_actor_fn=lambda current_target_key, current_payload: _apply_access_actor_payload(
            cur,
            current_target_key,
            current_payload,
        ),
    )


def create_and_apply_automatic_rollback_change_request(
    cur,
    *,
    source_change_request: dict[str, Any],
    actor_name: str,
    reason: str,
) -> dict[str, Any]:
    draft = build_change_request_rollback_draft(source_change_request)
    if not draft["rollback_ready"]:
        raise HTTPException(status_code=409, detail=draft["rollback_note"] or "Rollback draft is not ready")

    row = create_change_request_row(
        cur,
        target_type=draft["target_type"],
        target_key=draft["target_key"],
        proposed_payload=draft["proposed_payload"],
        rationale=draft["rationale"],
        requested_by_actor=actor_name,
        proposal_kind="rollback",
        source_change_request_id=int(source_change_request["id"]),
        source_workflow_proposal_id=source_change_request.get("source_workflow_proposal_id"),
    )
    rollback_change_request_id = int(row["id"])
    serialized_created_row = serialize_change_request_row(row)
    insert_audit_log(
        cur,
        "change_request.rollback_create",
        actor_name,
        None,
        {
            "source_change_request_id": int(source_change_request["id"]),
            "rollback_change_request_id": rollback_change_request_id,
            "target_type": source_change_request["target_type"],
            "target_key": source_change_request["target_key"],
            "patch_summary": serialized_created_row["patch_summary"],
            "auto_created": True,
            "reason": reason,
        },
    )

    rollback_payload = fetch_change_target_state_for_rollback_with_context(
        cur,
        target_type=draft["target_type"],
        target_key=draft["target_key"],
    )
    rollback_ready = isinstance(rollback_payload, dict) and bool(rollback_payload)
    rollback_note = (
        "Captured pre-change baseline for rollback."
        if rollback_ready
        else "No baseline target state found before apply; rollback draft requires manual recovery."
    )
    apply_change_request_payload_with_context(
        cur,
        draft["target_type"],
        draft["target_key"],
        draft["proposed_payload"] or {},
    )
    cur.execute(
        f"""
        UPDATE change_requests
        SET status = 'applied',
            reviewed_by_actor = %s,
            decision_note = %s,
            reviewed_at = CURRENT_TIMESTAMP,
            applied_by_actor = %s,
            applied_at = CURRENT_TIMESTAMP,
            rollback_payload = %s,
            rollback_ready = %s,
            rollback_note = %s
        WHERE id = %s
        RETURNING {CHANGE_REQUEST_SELECT_FIELDS};
        """,
        (
            actor_name,
            reason,
            actor_name,
            safe_json_dumps(rollback_payload) if rollback_payload is not None else None,
            rollback_ready,
            rollback_note,
            rollback_change_request_id,
        ),
    )
    applied_row = cur.fetchone()
    serialized_applied_row = serialize_change_request_row(applied_row)
    insert_audit_log(
        cur,
        "change_request.apply",
        actor_name,
        None,
        {
            "change_request_id": rollback_change_request_id,
            "target_type": draft["target_type"],
            "target_key": draft["target_key"],
            "proposal_kind": "rollback",
            "patch_summary": serialized_applied_row["patch_summary"],
            "rollback_ready": rollback_ready,
            "auto_created": True,
            "reason": reason,
        },
    )
    insert_audit_log(
        cur,
        "change_request.auto_rollback_apply",
        actor_name,
        None,
        {
            "source_change_request_id": int(source_change_request["id"]),
            "rollback_change_request_id": rollback_change_request_id,
            "target_type": draft["target_type"],
            "target_key": draft["target_key"],
            "reason": reason,
        },
    )
    return serialized_applied_row


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


def suggest_change_request_draft_from_workflow_proposal_with_context(cur, workflow_proposal: dict[str, Any]) -> dict[str, Any]:
    return suggest_change_request_draft_from_workflow_proposal(
        workflow_proposal=workflow_proposal,
        supported_change_target_types=list(SUPPORTED_CHANGE_TARGET_TYPES),
        fetch_planner_route_fn=lambda: _fetch_planner_route(cur),
        serialize_model_route_row_fn=serialize_model_route_row,
        build_change_request_draft_from_workflow_proposal_fn=build_change_request_draft_from_workflow_proposal,
    )


def resolve_shadow_validation_candidate_overlay_with_context(
    cur,
    *,
    workflow_proposal: dict[str, Any],
    request: WorkflowProposalShadowValidationRequest,
    source_change_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return resolve_shadow_validation_candidate_overlay(
        workflow_proposal=workflow_proposal,
        request=request,
        source_change_request=source_change_request,
        build_shadow_validation_candidate_overlay_fn=build_shadow_validation_candidate_overlay,
        parse_optional_int_fn=parse_optional_int,
        build_change_request_patch_artifacts_fn=lambda **kwargs: (
            build_change_request_patch_artifacts_with_context(cur, **kwargs)
        ),
        suggest_change_request_draft_from_workflow_proposal_fn=lambda **kwargs: (
            suggest_change_request_draft_from_workflow_proposal_with_context(cur, **kwargs)
        ),
        attach_patch_artifacts_to_change_request_draft_fn=lambda **kwargs: (
            attach_patch_artifacts_to_change_request_draft_with_context(cur, kwargs["draft"])
        ),
    )


def _fetch_planner_route(cur):
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
    return cur.fetchone()


def _fetch_shadow_task_and_evaluator(shadow_task_id: int):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT id, session_id, user_input, created_by_actor, status, runtime_overrides, created_at
            FROM task_runs
            WHERE id = %s;
            """,
            (shadow_task_id,),
        )
        shadow_task = cur.fetchone()
        shadow_evaluator = fetch_latest_evaluator_for_task(cur, shadow_task_id)
        return shadow_task, shadow_evaluator
    finally:
        cur.close()
        conn.close()


def _record_shadow_validation_result(
    *,
    workflow_proposal: dict[str, Any],
    baseline_task_id: int,
    actor_name: str,
    validation: dict[str, Any],
) -> None:
    conn = get_conn()
    cur = conn.cursor()
    try:
        insert_audit_log(
            cur,
            "workflow_proposal.shadow_validated",
            actor_name,
            baseline_task_id,
            validation,
        )
        sync_change_requests_shadow_validation_with_context(cur, int(workflow_proposal.get("id") or 0))
        conn.commit()
    finally:
        cur.close()
        conn.close()


def wait_for_shadow_validation_completion_with_context(
    *,
    workflow_proposal: dict[str, Any],
    baseline_task_id: int,
    shadow_task_id: int,
    actor_name: str,
    timeout_seconds: int,
    poll_interval_seconds: float,
    candidate_overlay: dict[str, Any] | None = None,
    runtime_overrides: dict[str, Any] | None = None,
    validation_mode: str = "task_replay_compare",
) -> dict[str, Any] | None:
    return wait_for_shadow_validation_completion(
        workflow_proposal=workflow_proposal,
        baseline_task_id=baseline_task_id,
        shadow_task_id=shadow_task_id,
        actor_name=actor_name,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        candidate_overlay=candidate_overlay,
        runtime_overrides=runtime_overrides,
        validation_mode=validation_mode,
        fetch_shadow_task_and_evaluator_fn=_fetch_shadow_task_and_evaluator,
        build_shadow_validation_result_fn=build_shadow_validation_result,
        record_shadow_validation_result_fn=_record_shadow_validation_result,
    )


def start_shadow_validation_completion_worker(
    *,
    workflow_proposal: dict[str, Any],
    baseline_task_id: int,
    shadow_task_id: int,
    actor_name: str,
    timeout_seconds: int,
    poll_interval_seconds: float,
    candidate_overlay: dict[str, Any] | None = None,
    runtime_overrides: dict[str, Any] | None = None,
    validation_mode: str = "task_replay_compare",
) -> None:
    def _run() -> None:
        try:
            wait_for_shadow_validation_completion_with_context(
                workflow_proposal=workflow_proposal,
                baseline_task_id=baseline_task_id,
                shadow_task_id=shadow_task_id,
                actor_name=actor_name,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
                candidate_overlay=candidate_overlay,
                runtime_overrides=runtime_overrides,
                validation_mode=validation_mode,
            )
        except Exception:
            logger.exception(
                "shadow validation async completion failed proposal_id=%s shadow_task_id=%s",
                workflow_proposal.get("id"),
                shadow_task_id,
            )

    thread = threading.Thread(
        target=_run,
        name=f"shadow-validation-{shadow_task_id}",
        daemon=True,
    )
    thread.start()


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
    validation_report: dict[str, Any] | None = None,
    recovery_action: dict[str, Any] | None = None,
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
    latest_validation_report = validation_report or {}
    latest_recovery_action = recovery_action or {}
    validation_passed = latest_validation_report.get("passed")
    validation_summary = str(latest_validation_report.get("summary") or "").strip()
    recovery_action_key = str(latest_recovery_action.get("action") or "").strip()
    recovery_summary = str(latest_recovery_action.get("summary") or "").strip()
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

    if recovery_action_key and recovery_action_key != "none":
        recommended_action = recovery_action_key
        if not awaiting_role:
            awaiting_role = "operator"
        if not blocking_reason:
            blocking_reason = recovery_summary or validation_summary or "任务级交付校验未通过"

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
        "latest_validation_report": latest_validation_report,
        "latest_recovery_action": latest_recovery_action,
        "validation_passed": validation_passed,
        "validation_summary": validation_summary,
        "recovery_action_key": recovery_action_key,
        "recovery_summary": recovery_summary,
        "latest_workflow_proposal_action": str(latest_workflow_proposal.get("action_key") or ""),
        "latest_workflow_proposal_priority": str(latest_workflow_proposal.get("priority") or ""),
        "latest_recommendation": (latest_evaluator or {}).get("recommendation") or "",
        "latest_failure_reason": (
            "deliverable_validation_failed"
            if validation_passed is False
            else ((latest_evaluator or {}).get("failure_reason") or "none")
        ),
        "latest_failure_stage": (
            "deliverable_validation"
            if validation_passed is False
            else ((latest_evaluator or {}).get("failure_stage") or "none")
        ),
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
        SELECT validation_report_json, recovery_action_json
        FROM task_runs
        WHERE id = %s;
        """,
        (task_id,),
    )
    task_row = cur.fetchone() or {}
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
        validation_report=parse_maybe_json(task_row.get("validation_report_json")) or {},
        recovery_action=parse_maybe_json(task_row.get("recovery_action_json")) or {},
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
                    "input_excerpt": build_task_display_input_excerpt(task_row),
                    "output_excerpt": build_task_result_excerpt(task_row),
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


def ensure_sessions_base_table(cur):
    cur.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)


def ensure_sessions_tables(cur):
    ensure_sessions_base_table(cur)

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

    ensure_runtime_core_tables(cur)

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


def process_change_request_post_apply_with_context(
    cur,
    *,
    change_request_id: int,
    change_request: dict[str, Any],
    normalized_proposed_payload: dict[str, Any],
    rollback_payload: dict[str, Any] | None,
    rollback_ready: bool,
    rollback_note: str,
    actor_name: str,
) -> dict[str, Any]:
    return process_change_request_post_apply(
        change_request_id=change_request_id,
        change_request=change_request,
        normalized_proposed_payload=normalized_proposed_payload,
        rollback_payload=rollback_payload,
        rollback_ready=rollback_ready,
        rollback_note=rollback_note,
        actor_name=actor_name,
        execute_sandbox_file_acceptance_fn=execute_sandbox_file_acceptance,
        make_json_compatible_fn=make_json_compatible,
        insert_audit_log_fn=lambda event_type, current_actor_name, task_id, details: insert_audit_log(
            cur,
            event_type,
            current_actor_name,
            task_id,
            details,
        ),
        create_and_apply_automatic_rollback_change_request_fn=lambda **kwargs: (
            create_and_apply_automatic_rollback_change_request(cur, **kwargs)
        ),
    )


def _update_reviewed_change_request_row(
    cur,
    *,
    change_request_id: int,
    actor_name: str,
    note: str,
    next_status: str,
):
    cur.execute(
        f"""
        UPDATE change_requests
        SET status = %s,
            reviewed_by_actor = %s,
            decision_note = %s,
            reviewed_at = CURRENT_TIMESTAMP
        WHERE id = %s
        RETURNING {CHANGE_REQUEST_SELECT_FIELDS};
        """,
        (next_status, actor_name, note, change_request_id),
    )
    return cur.fetchone()


def _update_applied_change_request_row(
    cur,
    *,
    change_request_id: int,
    actor_name: str,
    rollback_payload: dict[str, Any] | None,
    rollback_ready: bool,
    rollback_note: str,
    acceptance_status: str,
    acceptance_report: str | None,
    acceptance_at,
    auto_rollback_change_request_id: int | None,
    auto_rollback_at,
):
    cur.execute(
        f"""
        UPDATE change_requests
        SET status = 'applied',
            applied_by_actor = %s,
            applied_at = CURRENT_TIMESTAMP,
            rollback_payload = %s,
            rollback_ready = %s,
            rollback_note = %s,
            acceptance_status = %s,
            acceptance_report = %s,
            acceptance_at = %s,
            auto_rollback_change_request_id = %s,
            auto_rollback_at = %s
        WHERE id = %s
        RETURNING {CHANGE_REQUEST_SELECT_FIELDS};
        """,
        (
            actor_name,
            safe_json_dumps(rollback_payload) if rollback_payload is not None else None,
            rollback_ready,
            rollback_note,
            acceptance_status,
            acceptance_report,
            acceptance_at,
            auto_rollback_change_request_id,
            auto_rollback_at,
            change_request_id,
        ),
    )
    return cur.fetchone()


def build_shadow_validation_execution_payload_with_context(
    *,
    workflow_proposal: dict[str, Any],
    baseline_task: dict[str, Any],
    request: WorkflowProposalShadowValidationRequest,
    actor: dict[str, Any],
    quota_snapshot: dict[str, Any],
    candidate_overlay: dict[str, Any] | None,
    runtime_overrides: dict[str, Any] | None,
    shadow_task: dict[str, Any],
) -> dict[str, Any]:
    return build_shadow_validation_execution_payload(
        workflow_proposal=workflow_proposal,
        baseline_task=baseline_task,
        request=request,
        actor=actor,
        quota_snapshot=quota_snapshot,
        candidate_overlay=candidate_overlay,
        runtime_overrides=runtime_overrides,
        shadow_task=shadow_task,
        parse_optional_int_fn=parse_optional_int,
        make_json_compatible_fn=make_json_compatible,
    )


def finalize_shadow_validation_response_with_context(
    *,
    workflow_proposal: dict[str, Any],
    baseline_task: dict[str, Any],
    shadow_task: dict[str, Any],
    validation_request: dict[str, Any],
    candidate_overlay: dict[str, Any] | None,
    validation_mode: str,
    source_change_request: dict[str, Any] | None,
    await_completion: bool,
    actor_name: str,
    timeout_seconds: int,
    poll_interval_seconds: float,
    runtime_overrides: dict[str, Any] | None,
) -> dict[str, Any]:
    return finalize_shadow_validation_response(
        workflow_proposal=workflow_proposal,
        baseline_task=baseline_task,
        shadow_task=shadow_task,
        validation_request=validation_request,
        candidate_overlay=make_json_compatible(candidate_overlay),
        validation_mode=validation_mode,
        source_change_request=source_change_request,
        await_completion=await_completion,
        actor_name=actor_name,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        runtime_overrides=runtime_overrides,
        wait_for_shadow_validation_completion_fn=wait_for_shadow_validation_completion_with_context,
        start_shadow_validation_completion_worker_fn=start_shadow_validation_completion_worker,
    )


app.include_router(
    register_intake_task_routes(
        ensure_skill_registry_tables=ensure_skill_registry_tables,
        get_conn=get_conn,
        attach_task_display_fields=attach_task_display_fields,
        insert_audit_log=insert_audit_log,
        enqueue_task=enqueue_task,
        fetch_task_agent_summary=fetch_task_agent_summary,
    )
)

app.include_router(
    register_task_query_routes(
        get_conn=get_conn,
        require_actor_permission=require_actor_permission,
        ensure_agent_tables=ensure_agent_tables,
        ensure_evaluator_tables=ensure_evaluator_tables,
        ensure_trace_tables=ensure_trace_tables,
        attach_task_display_fields=attach_task_display_fields,
        parse_maybe_json=parse_maybe_json,
        fetch_latest_evaluator_for_task=fetch_latest_evaluator_for_task,
        fetch_task_agent_summary=fetch_task_agent_summary,
    )
)

app.include_router(
    register_multi_agent_query_routes(
        get_conn=get_conn,
        require_actor_permission=require_actor_permission,
        serialize_agent_run_row=serialize_agent_run_row,
        serialize_agent_message_row=serialize_agent_message_row,
        serialize_agent_artifact_row=serialize_agent_artifact_row,
        fetch_task_agent_summary=fetch_task_agent_summary,
        serialize_evaluator_run_row=serialize_evaluator_run_row,
        serialize_workflow_proposal=serialize_workflow_proposal,
        fetch_latest_evaluator_for_task=fetch_latest_evaluator_for_task,
        list_workflow_proposals_rows=list_workflow_proposals_rows,
        task_exists=task_exists,
        get_workflow_proposal_or_404=get_workflow_proposal_or_404,
        build_workflow_proposal_shadow_validation_response=build_workflow_proposal_shadow_validation_response,
        build_workflow_proposal_shadow_status=build_workflow_proposal_shadow_status,
        build_workflow_proposal_shadow_validation_status_with_context=build_workflow_proposal_shadow_validation_status_with_context,
        get_workflow_proposal_change_request_draft_response=get_workflow_proposal_change_request_draft_response,
        suggest_change_request_draft_from_workflow_proposal_with_context=suggest_change_request_draft_from_workflow_proposal_with_context,
        attach_patch_artifacts_to_change_request_draft_with_context=attach_patch_artifacts_to_change_request_draft_with_context,
        attach_shadow_validation_state_to_change_request_draft_with_context=attach_shadow_validation_state_to_change_request_draft_with_context,
        fetch_evaluator_run_row=fetch_evaluator_run_row,
        get_evaluator_run_or_404=get_evaluator_run_or_404,
    )
)

app.include_router(
    register_task_control_routes(
        get_conn=get_conn,
        require_actor_permission=require_actor_permission,
        get_task_or_404=get_task_or_404,
        update_checkpoint_status=update_checkpoint_status,
        insert_audit_log=insert_audit_log,
        resolve_resume_from_step=resolve_resume_from_step,
        reset_task_for_resume=reset_task_for_resume,
        reset_task_for_clarification=reset_task_for_clarification,
        enqueue_task=enqueue_task,
        parse_maybe_json=parse_maybe_json,
        extract_task_clarification_state=extract_task_clarification_state,
        build_clarified_user_input=build_clarified_user_input,
        infer_task_intent=infer_task_intent,
        build_task_display_user_input=build_task_display_user_input,
        infer_deliverable_spec=infer_deliverable_spec,
        logger=logger,
    )
)

app.include_router(
    register_multi_agent_demo_routes(
        get_conn=get_conn,
        require_actor_permission=require_actor_permission,
        ensure_agent_tables=ensure_agent_tables,
        build_task_display_user_input=build_task_display_user_input,
        parse_maybe_json=parse_maybe_json,
        multi_agent_protocol_version=MULTI_AGENT_PROTOCOL_VERSION,
        create_agent_artifact=create_agent_artifact,
        create_agent_run=create_agent_run,
        create_agent_message=create_agent_message,
        build_specialist_execution_request=build_specialist_execution_request,
        insert_audit_log=insert_audit_log,
        logger=logger,
        safe_json_dumps=safe_json_dumps,
        serialize_agent_artifact_row=serialize_agent_artifact_row,
        build_specialist_step_partitions=build_specialist_step_partitions,
        build_specialist_draft_payload=build_specialist_draft_payload,
        enqueue_agent_run=enqueue_agent_run,
        resolve_reviewer_decision=resolve_reviewer_decision,
        build_demo_review_criteria=build_demo_review_criteria,
        derive_evaluator_failure_profile=derive_evaluator_failure_profile,
        build_workflow_proposal=build_workflow_proposal,
        create_evaluator_run=create_evaluator_run,
        serialize_workflow_proposal=serialize_workflow_proposal,
    )
)

app.include_router(
    register_change_request_query_routes(
        get_conn=get_conn,
        require_actor_permission=require_actor_permission,
        ensure_change_requests_table=ensure_change_requests_table,
        normalize_change_request_proposal_kind=normalize_change_request_proposal_kind,
        change_request_select_fields=CHANGE_REQUEST_SELECT_FIELDS,
        serialize_change_request_row=serialize_change_request_row,
        serialize_change_request_list_row=serialize_change_request_list_row,
        get_change_request_or_404=get_change_request_or_404,
        collect_change_request_shadow_validation_context=collect_change_request_shadow_validation_context,
        parse_optional_int=parse_optional_int,
        build_workflow_proposal_shadow_validation_status_with_context=build_workflow_proposal_shadow_validation_status_with_context,
        fetch_latest_workflow_proposal_shadow_validation_with_context=fetch_latest_workflow_proposal_shadow_validation_with_context,
        fetch_task_run_brief_with_context=fetch_task_run_brief_with_context,
        build_change_request_shadow_validation_response=build_change_request_shadow_validation_response,
        prepare_change_request_rollback_context=prepare_change_request_rollback_context,
        build_change_request_rollback_draft=build_change_request_rollback_draft,
        find_open_rollback_change_request=find_open_rollback_change_request,
        attach_patch_artifacts_to_change_request_draft_with_context=attach_patch_artifacts_to_change_request_draft_with_context,
        attach_shadow_validation_state_to_change_request_draft_with_context=attach_shadow_validation_state_to_change_request_draft_with_context,
    )
)

app.include_router(
    register_change_request_control_routes(
        get_conn=get_conn,
        require_actor_permission=require_actor_permission,
        supported_change_target_types=SUPPORTED_CHANGE_TARGET_TYPES,
        create_change_request_with_audit=create_change_request_with_audit,
        create_change_request_row=create_change_request_row,
        serialize_change_request_row=serialize_change_request_row,
        insert_audit_log=insert_audit_log,
        ensure_change_requests_table=ensure_change_requests_table,
        get_change_request_or_404=get_change_request_or_404,
        review_change_request=review_change_request,
        update_reviewed_change_request_row=_update_reviewed_change_request_row,
        execute_change_request_apply=execute_change_request_apply,
        normalize_change_request_payload=normalize_change_request_payload,
        fetch_change_target_state_for_rollback_with_context=fetch_change_target_state_for_rollback_with_context,
        apply_change_request_payload_with_context=apply_change_request_payload_with_context,
        process_change_request_post_apply_with_context=process_change_request_post_apply_with_context,
        safe_json_dumps=safe_json_dumps,
        update_applied_change_request_row=_update_applied_change_request_row,
        prepare_change_request_rollback_context=prepare_change_request_rollback_context,
        build_change_request_rollback_draft=build_change_request_rollback_draft,
        find_open_rollback_change_request=find_open_rollback_change_request,
        get_workflow_proposal_or_404=get_workflow_proposal_or_404,
        serialize_evaluator_run_row=serialize_evaluator_run_row,
        serialize_workflow_proposal=serialize_workflow_proposal,
        create_change_request_from_workflow_proposal_draft=create_change_request_from_workflow_proposal_draft,
        build_change_request_draft_from_workflow_proposal=build_change_request_draft_from_workflow_proposal,
        record_audit_event=record_audit_event,
        launch_workflow_proposal_shadow_validation=launch_workflow_proposal_shadow_validation,
        enforce_task_quota=enforce_task_quota,
        prepare_shadow_validation_baseline=prepare_shadow_validation_baseline,
        resolve_shadow_validation_candidate_overlay_with_context=resolve_shadow_validation_candidate_overlay_with_context,
        build_shadow_validation_runtime_overrides=build_shadow_validation_runtime_overrides,
        build_shadow_validation_execution_payload_with_context=build_shadow_validation_execution_payload_with_context,
        parse_optional_int=parse_optional_int,
        complete_workflow_proposal_shadow_validation=complete_workflow_proposal_shadow_validation,
        enqueue_task=enqueue_task,
        finalize_shadow_validation_response_with_context=finalize_shadow_validation_response_with_context,
        resolve_change_request_shadow_validation_target=resolve_change_request_shadow_validation_target,
        ensure_change_request_shadow_validation_eligible=ensure_change_request_shadow_validation_eligible,
    )
)

app.include_router(
    register_session_routes(
        get_conn=get_conn,
        require_actor_permission=require_actor_permission,
        record_audit_event=record_audit_event,
        insert_audit_log=insert_audit_log,
        attach_task_display_fields=attach_task_display_fields,
        serialize_session_row=serialize_session_row,
        serialize_session_memory_row=serialize_session_memory_row,
        serialize_session_state_row=serialize_session_state_row,
        serialize_session_review_row=serialize_session_review_row,
        compute_session_health=compute_session_health,
        load_session_health_context=load_session_health_context,
        refresh_session_review_context=refresh_session_review_context,
        build_session_review=build_session_review,
        insert_session_review_row=insert_session_review_row,
        safe_json_dumps=safe_json_dumps,
        compute_session_state_from_rows=compute_session_state_from_rows,
        upsert_computed_session_state=upsert_computed_session_state,
        refresh_session_reviews=refresh_session_reviews,
        refresh_session_task_summary_memories=refresh_session_task_summary_memories,
        merge_memory_into_session_state=merge_memory_into_session_state,
        logger=logger,
    )
)

app.include_router(
    register_monitor_routes(
        get_conn=get_conn,
        require_actor_permission=require_actor_permission,
        ensure_risk_policies_table=ensure_risk_policies_table,
        ensure_access_actors_table=ensure_access_actors_table,
        ensure_access_quotas_table=ensure_access_quotas_table,
        ensure_tool_registry_table=ensure_tool_registry_table,
        ensure_model_providers_table=ensure_model_providers_table,
        ensure_model_routes_table=ensure_model_routes_table,
        ensure_change_requests_table=ensure_change_requests_table,
        ensure_agent_tables=ensure_agent_tables,
        fetch_monitor_overview_snapshot=fetch_monitor_overview_snapshot,
        build_task_display_user_input=build_task_display_user_input,
        extract_task_clarification_state=extract_task_clarification_state,
        parse_maybe_json=parse_maybe_json,
        serialize_session_review_row=serialize_session_review_row,
        serialize_agent_run_row=serialize_agent_run_row,
        serialize_evaluator_run_row=serialize_evaluator_run_row,
        list_workflow_proposals_rows=list_workflow_proposals_rows,
        fetch_stage56_overview_metrics=fetch_stage56_overview_metrics,
        fetch_task_agent_summary=fetch_task_agent_summary,
        mainline_specialist_execution_modes=list(MAINLINE_SPECIALIST_EXECUTION_MODES),
        mainline_specialist_tool_profiles=list(MAINLINE_SPECIALIST_TOOL_PROFILES),
        fetch_stage7_overview_metrics=fetch_stage7_overview_metrics,
        get_redis_monitor_stats=get_redis_monitor_stats,
        compute_stage_readiness_metrics=compute_stage_readiness_metrics,
        default_enforced_change_target_types=DEFAULT_ENFORCED_CHANGE_TARGET_TYPES,
        change_gate_required_target_types=CHANGE_GATE_REQUIRED_TARGET_TYPES,
        step_request_protocol_version=STEP_REQUEST_PROTOCOL_VERSION,
        multi_agent_protocol_version=MULTI_AGENT_PROTOCOL_VERSION,
    )
)

app.include_router(
    register_governance_routes(
        get_conn=get_conn,
        require_actor_permission=require_actor_permission,
        seed_default_risk_policies=seed_default_risk_policies,
        deserialize_policy_row=deserialize_policy_row,
        seed_default_tool_registry=seed_default_tool_registry,
        serialize_tool_registry_row=serialize_tool_registry_row,
        seed_default_model_providers=seed_default_model_providers,
        seed_default_model_routes=seed_default_model_routes,
        serialize_model_route_row=serialize_model_route_row,
        serialize_model_provider_row=serialize_model_provider_row,
        seed_default_access_actors=seed_default_access_actors,
        seed_default_access_quotas=seed_default_access_quotas,
        serialize_access_actor_row=serialize_access_actor_row,
        serialize_access_quota_row=serialize_access_quota_row,
        parse_maybe_json=parse_maybe_json,
        validate_policy_value=validate_policy_value,
        update_risk_policy_entry=update_risk_policy_entry,
        update_tool_registry_entry=update_tool_registry_entry,
        update_model_route_entry=update_model_route_entry,
        upsert_model_provider_entry=upsert_model_provider_entry,
        upsert_access_actor=upsert_access_actor,
        upsert_access_quota=upsert_access_quota,
        upsert_default_access_quota=upsert_default_access_quota,
        insert_audit_log=insert_audit_log,
        enforce_change_gate_for_direct_update=enforce_change_gate_for_direct_update,
        ensure_audit_logs_table=ensure_audit_logs_table,
        access_role_permissions=ACCESS_ROLE_PERMISSIONS,
        step_request_protocol_version=STEP_REQUEST_PROTOCOL_VERSION,
        step_execution_request_fields=STEP_EXECUTION_REQUEST_FIELDS,
        enriched_step_execution_request_extra_fields=ENRICHED_STEP_EXECUTION_REQUEST_EXTRA_FIELDS,
        multi_agent_protocol_version=MULTI_AGENT_PROTOCOL_VERSION,
        auto_stage5_postrun_enabled=AUTO_STAGE5_POSTRUN_ENABLED,
        logger=logger,
    )
)

app.include_router(
    register_skill_routes(
        get_conn=get_conn,
        require_actor_permission=require_actor_permission,
        ensure_skill_registry_tables=ensure_skill_registry_tables,
        read_skill_package_from_source=_read_skill_package_from_source,
        serialize_skill_row=serialize_skill_row,
        serialize_skill_version_row=serialize_skill_version_row,
        insert_audit_log=insert_audit_log,
        json_wrapper=Json,
    )
)


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


def resolve_resume_from_step(cur, task_id: int, preferred_from_step: int | None) -> int:
    resume_from = preferred_from_step
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
    return int(resume_from or 1)


def reset_task_for_resume(
    cur,
    *,
    task_id: int,
    task: dict[str, Any],
    resume_from: int,
    actor: dict[str, Any],
    note: str,
    event_type: str,
    details: dict[str, Any] | None = None,
):
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
            validation_report_json = NULL,
            recovery_action_json = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s;
        """,
        (resume_from, task_id),
    )

    payload = {
        "from_step": resume_from,
        "note": note,
        "previous_status": task["status"],
        "role": actor["role"],
    }
    if details:
        payload.update(details)
    insert_audit_log(cur, event_type, actor["actor_name"], task_id, payload)


def reset_task_for_clarification(
    cur,
    *,
    task_id: int,
    task: dict[str, Any],
    actor: dict[str, Any],
    new_user_input: str,
    task_intent: dict[str, Any],
    deliverable_spec: dict[str, Any],
    runtime_overrides: dict[str, Any] | None,
    note: str,
    details: dict[str, Any] | None = None,
):
    cur.execute(
        """
        DELETE FROM task_steps
        WHERE task_id = %s;
        """,
        (task_id,),
    )
    cur.execute(
        """
        UPDATE task_runs
        SET user_input = %s,
            status = 'pending',
            result = NULL,
            error_message = NULL,
            current_step = 1,
            runtime_overrides = %s,
            task_intent_json = %s,
            deliverable_spec_json = %s,
            validation_report_json = NULL,
            recovery_action_json = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s;
        """,
        (
            new_user_input,
            Json(make_json_compatible(runtime_overrides)) if runtime_overrides else None,
            Json(make_json_compatible(task_intent)),
            Json(make_json_compatible(deliverable_spec)),
            task_id,
        ),
    )
    payload = {
        "from_step": 1,
        "note": note,
        "previous_status": task["status"],
        "role": actor["role"],
        "task_intent_type": task_intent.get("task_type"),
        "deliverable_type": deliverable_spec.get("deliverable_type"),
    }
    if details:
        payload.update(details)
    insert_audit_log(cur, "task.clarify_resume", actor["actor_name"], task_id, payload)
