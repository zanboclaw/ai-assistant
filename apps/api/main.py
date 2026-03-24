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
from intake_task_routes import (
    build_intake_preview_payload,
    build_memory_context,
    register_intake_task_routes,
    resolve_intake_route_mode,
)
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
    extract_review_note_from_highlights,
    insert_session_review_row,
    load_session_health_context,
    load_session_review_context,
    merge_memory_into_session_state,
    refresh_session_review_context,
    refresh_session_reviews,
    refresh_session_task_summary_memories,
    upsert_computed_session_state,
)
from task_intent_helpers import infer_deliverable_spec, infer_task_intent
from monitor_overview_store import fetch_monitor_overview_snapshot
from monitor_stage_metrics_store import fetch_stage56_overview_metrics
from monitor_stage7_store import fetch_stage7_overview_metrics
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
    get_latest_task_evaluator_run_response,
    get_latest_task_workflow_proposal_response,
    get_workflow_proposal_change_request_draft_response,
    get_workflow_proposal_or_404,
    get_workflow_proposal_response,
    launch_workflow_proposal_shadow_validation,
    list_evaluator_runs_response,
    list_task_workflow_proposals_or_404,
    list_workflow_proposals_response,
    prepare_workflow_proposal_shadow_validation_context,
    resolve_change_request_shadow_validation_target,
    task_exists,
)
from schemas import (
    AccessActorUpdate,
    AccessQuotaUpdate,
    AgentBootstrapRequest,
    AgentExecuteRequest,
    AgentFinalizeRequest,
    ApprovalDecision,
    ChangeRequestCreate,
    ChangeRequestDecision,
    DailyReviewRunRequest,
    IntakeRouteRequest,
    ModelProviderUpdate,
    ModelRouteUpdate,
    RiskPolicyUpdate,
    SessionCreate,
    SessionMemoryCreate,
    SessionReviewCreate,
    SessionStateUpdate,
    TaskClarifyRequest,
    TaskDraftConfirmRequest,
    SkillImportRequest,
    TaskCreate,
    TaskInterruptRequest,
    TaskResumeRequest,
    ToolRegistryUpdate,
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


@app.get("/risk-policies")
def list_risk_policies(x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
    conn = get_conn()
    cur = conn.cursor()
    require_actor_permission(cur, x_actor_name, "read")
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
        SELECT tool_name, enabled, provider_type, transport, server_name, provider_config, risk_level, approval_required, description, created_at, updated_at
        FROM tool_registry_entries
        ORDER BY tool_name ASC;
        """
    )
    rows = [serialize_tool_registry_row(row) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


@app.get("/skills")
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


@app.get("/skills/{skill_id}")
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


@app.post("/skills/import")
def import_skill(request: SkillImportRequest, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
    conn = get_conn()
    cur = conn.cursor()
    actor = require_actor_permission(cur, x_actor_name, "admin")
    ensure_skill_registry_tables(cur)
    payload = _read_skill_package_from_source(request.source_path)
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
            Json(payload["package_body"]),
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
    normalized_provider_type = request.provider_type.strip().lower()
    if normalized_provider_type not in {"builtin", "mcp_stdio", "mcp_http"}:
        raise HTTPException(status_code=400, detail=f"Unsupported provider_type: {request.provider_type}")
    normalized_transport = request.transport.strip().lower()
    if normalized_transport not in {"", "local", "stdio", "http"}:
        raise HTTPException(status_code=400, detail=f"Unsupported transport: {request.transport}")

    conn = get_conn()
    cur = conn.cursor()
    actor = require_actor_permission(cur, x_actor_name, "admin")
    enforce_change_gate_for_direct_update("tool_registry")
    serialized_row = update_tool_registry_entry(
        cur,
        tool_name=normalized_tool_name,
        enabled=bool(request.enabled),
        provider_type=normalized_provider_type,
        transport=normalized_transport or ("local" if normalized_provider_type == "builtin" else ""),
        server_name=request.server_name.strip(),
        provider_config=dict(request.provider_config or {}),
        risk_level=normalized_risk_level,
        approval_required=bool(request.approval_required),
        description=request.description.strip(),
        actor_name=actor["actor_name"],
        seed_default_tool_registry_fn=seed_default_tool_registry,
        insert_audit_log_fn=insert_audit_log,
        serialize_tool_registry_row_fn=serialize_tool_registry_row,
    )
    conn.commit()
    cur.close()
    conn.close()
    logger.info(
        "tool registry updated tool_name=%s enabled=%s provider_type=%s risk_level=%s actor=%s",
        normalized_tool_name,
        bool(request.enabled),
        normalized_provider_type,
        normalized_risk_level,
        actor["actor_name"],
    )
    return serialized_row


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
    serialized_row = update_model_route_entry(
        cur,
        route_name=normalized_route_name,
        provider=normalized_provider,
        model_name=normalized_model_name,
        temperature=float(request.temperature),
        max_tokens=int(request.max_tokens),
        enabled=bool(request.enabled),
        description=request.description.strip(),
        actor_name=actor["actor_name"],
        seed_default_model_providers_fn=seed_default_model_providers,
        seed_default_model_routes_fn=seed_default_model_routes,
        insert_audit_log_fn=insert_audit_log,
        serialize_model_route_row_fn=serialize_model_route_row,
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
    return serialized_row


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
    serialized_row = upsert_model_provider_entry(
        cur,
        provider_name=normalized_provider_name,
        driver=normalized_driver,
        base_url=normalized_base_url,
        api_key_env=normalized_api_key_env,
        enabled=bool(request.enabled),
        description=request.description.strip(),
        actor_name=actor["actor_name"],
        seed_default_model_providers_fn=seed_default_model_providers,
        insert_audit_log_fn=insert_audit_log,
        serialize_model_provider_row_fn=serialize_model_provider_row,
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
    return serialized_row


@app.get("/change-requests")
def list_change_requests(
    status: str | None = None,
    target_type: str | None = None,
    proposal_kind: str | None = None,
    limit: int = 20,
    offset: int = 0,
    include_payloads: bool = False,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    normalized_limit = max(1, min(int(limit), 100))
    normalized_offset = max(0, int(offset))
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
    if proposal_kind:
        where.append("proposal_kind = %s")
        params.append(normalize_change_request_proposal_kind(proposal_kind))
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    cur.execute(
        f"""
        SELECT {CHANGE_REQUEST_SELECT_FIELDS}
        FROM change_requests
        {where_sql}
        ORDER BY id DESC
        LIMIT %s
        OFFSET %s;
        """,
        [*params, normalized_limit, normalized_offset],
    )
    serialize_row = serialize_change_request_row if include_payloads else serialize_change_request_list_row
    rows = [serialize_row(row) for row in cur.fetchall()]
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
    try:
        actor = require_actor_permission(cur, x_actor_name, "operate")
        serialized_row = create_change_request_with_audit(
            cur=cur,
            target_type=target_type,
            target_key=target_key,
            proposed_payload=request.proposed_payload,
            rationale=request.rationale,
            requested_by_actor=actor["actor_name"],
            create_change_request_row_fn=create_change_request_row,
            serialize_change_request_row_fn=serialize_change_request_row,
            insert_audit_log_fn=insert_audit_log,
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()
    return serialized_row


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


@app.get("/change-requests/{change_request_id}")
def get_change_request(
    change_request_id: int,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    conn = get_conn()
    cur = conn.cursor()
    try:
        require_actor_permission(cur, x_actor_name, "read")
        return get_change_request_or_404(cur, ensure_change_requests_table, change_request_id)
    finally:
        cur.close()
        conn.close()


@app.get("/change-requests/{change_request_id}/shadow-validation")
def get_change_request_shadow_validation(
    change_request_id: int,
    history_limit: int = 10,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    conn = get_conn()
    cur = conn.cursor()
    try:
        require_actor_permission(cur, x_actor_name, "read")
        change_request = get_change_request_or_404(cur, ensure_change_requests_table, change_request_id)
        shadow_validation_context = collect_change_request_shadow_validation_context(
            change_request=change_request,
            history_limit=history_limit,
            parse_optional_int_fn=parse_optional_int,
            build_workflow_proposal_shadow_validation_status_fn=lambda proposal_id, **kwargs: (
                build_workflow_proposal_shadow_validation_status_with_context(cur, proposal_id, **kwargs)
            ),
            fetch_latest_workflow_proposal_shadow_validation_fn=lambda proposal_id, **kwargs: (
                fetch_latest_workflow_proposal_shadow_validation_with_context(cur, proposal_id, **kwargs)
            ),
            fetch_task_run_brief_fn=lambda task_id: fetch_task_run_brief_with_context(cur, task_id),
        )
        return build_change_request_shadow_validation_response(
            change_request=change_request,
            proposal_shadow_validation=shadow_validation_context["proposal_shadow_validation"],
            latest_matching_validation=shadow_validation_context["latest_matching_validation"],
            latest_proposal_validation=shadow_validation_context["latest_proposal_validation"],
            latest_shadow_task=shadow_validation_context["latest_shadow_task"],
            parse_optional_int_fn=parse_optional_int,
        )
    finally:
        cur.close()
        conn.close()


@app.post("/change-requests/{change_request_id}/approve")
def approve_change_request(
    change_request_id: int,
    request: ChangeRequestDecision,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    conn = get_conn()
    cur = conn.cursor()
    try:
        actor = require_actor_permission(cur, x_actor_name, "admin")
        serialized_row = review_change_request(
            cur=cur,
            change_request_id=change_request_id,
            actor_name=actor["actor_name"],
            note=request.note.strip(),
            next_status="approved",
            audit_event="change_request.approve",
            get_change_request_fn=lambda current_change_request_id: get_change_request_or_404(
                cur,
                ensure_change_requests_table,
                current_change_request_id,
            ),
            update_change_request_review_fn=lambda **kwargs: _update_reviewed_change_request_row(
                cur,
                change_request_id=change_request_id,
                **kwargs,
            ),
            serialize_change_request_row_fn=serialize_change_request_row,
            insert_audit_log_fn=insert_audit_log,
        )
        conn.commit()
        return serialized_row
    finally:
        cur.close()
        conn.close()


@app.post("/change-requests/{change_request_id}/reject")
def reject_change_request(
    change_request_id: int,
    request: ChangeRequestDecision,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    conn = get_conn()
    cur = conn.cursor()
    try:
        actor = require_actor_permission(cur, x_actor_name, "admin")
        serialized_row = review_change_request(
            cur=cur,
            change_request_id=change_request_id,
            actor_name=actor["actor_name"],
            note=request.note.strip(),
            next_status="rejected",
            audit_event="change_request.reject",
            get_change_request_fn=lambda current_change_request_id: get_change_request_or_404(
                cur,
                ensure_change_requests_table,
                current_change_request_id,
            ),
            update_change_request_review_fn=lambda **kwargs: _update_reviewed_change_request_row(
                cur,
                change_request_id=change_request_id,
                **kwargs,
            ),
            serialize_change_request_row_fn=serialize_change_request_row,
            insert_audit_log_fn=insert_audit_log,
        )
        conn.commit()
        return serialized_row
    finally:
        cur.close()
        conn.close()


@app.post("/change-requests/{change_request_id}/apply")
def apply_change_request(
    change_request_id: int,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    conn = get_conn()
    cur = conn.cursor()
    try:
        actor = require_actor_permission(cur, x_actor_name, "admin")
        change_request = get_change_request_or_404(cur, ensure_change_requests_table, change_request_id)
        serialized_row = execute_change_request_apply(
            cur=cur,
            change_request_id=change_request_id,
            actor_name=actor["actor_name"],
            change_request=change_request,
            normalize_change_request_payload_fn=normalize_change_request_payload,
            fetch_change_target_state_for_rollback_fn=lambda **kwargs: (
                fetch_change_target_state_for_rollback_with_context(cur, **kwargs)
            ),
            apply_change_request_payload_fn=lambda target_type, target_key, payload: (
                apply_change_request_payload_with_context(cur, target_type, target_key, payload)
            ),
            process_change_request_post_apply_fn=lambda **kwargs: (
                process_change_request_post_apply_with_context(cur, **kwargs)
            ),
            safe_json_dumps_fn=safe_json_dumps,
            update_change_request_fn=lambda **kwargs: _update_applied_change_request_row(
                cur,
                change_request_id=change_request_id,
                **kwargs,
            ),
            serialize_change_request_row_fn=serialize_change_request_row,
            insert_audit_log_fn=lambda event_type, current_actor_name, task_id, details: insert_audit_log(
                cur,
                event_type,
                current_actor_name,
                task_id,
                details,
            ),
        )
        conn.commit()
        return serialized_row
    finally:
        cur.close()
        conn.close()


@app.get("/change-requests/{change_request_id}/rollback-draft")
def preview_change_request_rollback_draft(
    change_request_id: int,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    conn = get_conn()
    cur = conn.cursor()
    try:
        require_actor_permission(cur, x_actor_name, "read")
        rollback_context = prepare_change_request_rollback_context(
            change_request_id=change_request_id,
            get_change_request_fn=lambda current_change_request_id: get_change_request_or_404(
                cur,
                ensure_change_requests_table,
                current_change_request_id,
            ),
            build_change_request_rollback_draft_fn=build_change_request_rollback_draft,
            find_open_rollback_change_request_fn=lambda current_change_request_id: find_open_rollback_change_request(
                cur,
                current_change_request_id,
                ensure_change_requests_table,
            ),
        )
        draft = rollback_context["draft"]
        draft = attach_patch_artifacts_to_change_request_draft_with_context(cur, draft)
        draft = attach_shadow_validation_state_to_change_request_draft_with_context(cur, draft)
        existing = rollback_context["existing_rollback_change_request"]
        draft["existing_rollback_change_request"] = serialize_change_request_row(existing) if existing else None
        return draft
    finally:
        cur.close()
        conn.close()


@app.post("/change-requests/{change_request_id}/rollback")
def create_rollback_change_request(
    change_request_id: int,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    conn = get_conn()
    cur = conn.cursor()
    try:
        actor = require_actor_permission(cur, x_actor_name, "operate")
        rollback_context = prepare_change_request_rollback_context(
            change_request_id=change_request_id,
            get_change_request_fn=lambda current_change_request_id: get_change_request_or_404(
                cur,
                ensure_change_requests_table,
                current_change_request_id,
            ),
            build_change_request_rollback_draft_fn=build_change_request_rollback_draft,
            find_open_rollback_change_request_fn=lambda current_change_request_id: find_open_rollback_change_request(
                cur,
                current_change_request_id,
                ensure_change_requests_table,
            ),
        )
        change_request = rollback_context["change_request"]
        draft = rollback_context["draft"]
        if not draft["rollback_ready"]:
            raise HTTPException(status_code=409, detail=draft["rollback_note"] or "Rollback draft is not ready")

        existing = rollback_context["existing_rollback_change_request"]
        if existing:
            return {
                "created": False,
                "change_request": serialize_change_request_row(existing),
                "source_change_request": change_request,
            }

        row = create_change_request_row(
            cur,
            target_type=draft["target_type"],
            target_key=draft["target_key"],
            proposed_payload=draft["proposed_payload"],
            rationale=draft["rationale"],
            requested_by_actor=actor["actor_name"],
            proposal_kind="rollback",
            source_change_request_id=change_request_id,
            source_workflow_proposal_id=change_request.get("source_workflow_proposal_id"),
        )
        insert_audit_log(
            cur,
            "change_request.rollback_create",
            actor["actor_name"],
            None,
            {
                "source_change_request_id": change_request_id,
                "rollback_change_request_id": row["id"],
                "target_type": change_request["target_type"],
                "target_key": change_request["target_key"],
                "patch_summary": serialize_change_request_row(row)["patch_summary"],
            },
        )
        conn.commit()
        return {
            "created": True,
            "change_request": serialize_change_request_row(row),
            "source_change_request": change_request,
        }
    finally:
        cur.close()
        conn.close()


@app.get("/access/actors")
def list_access_actors(x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
    conn = get_conn()
    cur = conn.cursor()
    require_actor_permission(cur, x_actor_name, "read")
    seed_default_access_actors(cur)
    conn.commit()
    cur.execute(
        """
        SELECT actor_name, role, description, tenant_key, permission_overrides, created_at, updated_at
        FROM access_actors
        ORDER BY actor_name ASC;
        """
    )
    rows = []
    for row in cur.fetchall():
        permission_overrides = parse_maybe_json(row.get("permission_overrides")) or []
        row["permissions"] = set(ACCESS_ROLE_PERMISSIONS.get(str(row.get("role") or ""), set())) | {
            str(item).strip().lower() for item in permission_overrides if str(item).strip()
        }
        rows.append(serialize_access_actor_row(row))
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
        SELECT actor_name, daily_task_limit, active_task_limit, daily_token_limit, max_parallel_agents, created_at, updated_at
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
            q.daily_token_limit,
            q.max_parallel_agents,
            COALESCE(d.daily_task_count, 0) AS daily_task_count,
            COALESCE(ac.active_task_count, 0) AS active_task_count,
            COALESCE(tok.daily_token_count, 0) AS daily_token_count
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
        LEFT JOIN (
            SELECT tr.created_by_actor, COALESCE(SUM(COALESCE(ar.cost_tokens_in, 0) + COALESCE(ar.cost_tokens_out, 0)), 0) AS daily_token_count
            FROM task_runs tr
            JOIN agent_runs ar ON ar.task_run_id = tr.id
            WHERE tr.created_by_actor IS NOT NULL
              AND DATE(ar.created_at) = CURRENT_DATE
            GROUP BY tr.created_by_actor
        ) tok ON tok.created_by_actor = a.actor_name
        ORDER BY a.actor_name ASC;
        """
    )
    rows = []
    for row in cur.fetchall():
        daily_limit = int(row["daily_task_limit"])
        active_limit = int(row["active_task_limit"])
        daily_token_limit = int(row["daily_token_limit"] or 0)
        max_parallel_agents = int(row["max_parallel_agents"] or 0)
        daily_count = int(row["daily_task_count"])
        active_count = int(row["active_task_count"])
        daily_token_count = int(row["daily_token_count"] or 0)
        rows.append(
            {
                "actor_name": row["actor_name"],
                "role": row["role"],
                "daily_task_limit": daily_limit,
                "active_task_limit": active_limit,
                "daily_token_limit": daily_token_limit,
                "max_parallel_agents": max_parallel_agents,
                "daily_task_count": daily_count,
                "active_task_count": active_count,
                "daily_remaining": max(daily_limit - daily_count, 0),
                "active_remaining": max(active_limit - active_count, 0),
                "daily_token_count": daily_token_count,
                "daily_token_remaining": max(daily_token_limit - daily_token_count, 0),
            }
        )
    cur.close()
    conn.close()
    return rows


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
    serialized_row = upsert_access_actor(
        cur,
        actor_name=normalized_actor_name,
        role=normalized_role,
        description=request.description.strip(),
        tenant_key=request.tenant_key.strip() or "default",
        permission_overrides=[str(item).strip().lower() for item in request.permission_overrides if str(item).strip()],
        admin_actor_name=actor["actor_name"],
        upsert_default_access_quota_fn=upsert_default_access_quota,
        insert_audit_log_fn=insert_audit_log,
    )
    conn.commit()
    cur.close()
    conn.close()
    logger.info("access actor updated actor_name=%s role=%s by=%s", normalized_actor_name, normalized_role, actor["actor_name"])
    return serialized_row


@app.put("/access/quotas/{actor_name}")
def update_access_quota(
    actor_name: str,
    request: AccessQuotaUpdate,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    normalized_actor_name = actor_name.strip()
    if not normalized_actor_name:
        raise HTTPException(status_code=400, detail="Actor name cannot be empty")
    if request.daily_task_limit < 0 or request.active_task_limit < 0 or request.daily_token_limit < 0 or request.max_parallel_agents < 0:
        raise HTTPException(status_code=400, detail="Quota values must be non-negative")

    conn = get_conn()
    cur = conn.cursor()
    actor = require_actor_permission(cur, x_actor_name, "admin")
    enforce_change_gate_for_direct_update("access_quota")
    serialized_row = upsert_access_quota(
        cur,
        actor_name=normalized_actor_name,
        daily_task_limit=int(request.daily_task_limit),
        active_task_limit=int(request.active_task_limit),
        daily_token_limit=int(request.daily_token_limit),
        max_parallel_agents=int(request.max_parallel_agents),
        admin_actor_name=actor["actor_name"],
        seed_default_access_quotas_fn=seed_default_access_quotas,
        insert_audit_log_fn=insert_audit_log,
    )
    conn.commit()
    cur.close()
    conn.close()
    logger.info(
        "access quota updated actor_name=%s daily_task_limit=%s active_task_limit=%s daily_token_limit=%s max_parallel_agents=%s by=%s",
        normalized_actor_name,
        request.daily_task_limit,
        request.active_task_limit,
        request.daily_token_limit,
        request.max_parallel_agents,
        actor["actor_name"],
    )
    return serialized_row


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
    serialized_row = update_risk_policy_entry(
        cur,
        policy_key=policy_key,
        value_type=value_type,
        serialized_value=serialized_value,
        policy_value=request.policy_value,
        actor_name=actor["actor_name"],
        actor_role=actor["role"],
        seed_default_risk_policies_fn=seed_default_risk_policies,
        insert_audit_log_fn=insert_audit_log,
        deserialize_policy_row_fn=deserialize_policy_row,
    )
    conn.commit()
    cur.close()
    conn.close()

    logger.info("risk policy updated policy_key=%s actor=%s", policy_key, actor["actor_name"])
    return serialized_row


@app.get("/audit-logs")
def list_audit_logs(
    task_id: int | None = None,
    event_type: str | None = None,
    limit: int | None = 50,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    conn = get_conn()
    cur = conn.cursor()
    require_actor_permission(cur, x_actor_name, "read")
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
def get_runtime_metadata(x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
    conn = get_conn()
    cur = conn.cursor()
    require_actor_permission(cur, x_actor_name, "read")
    cur.close()
    conn.close()
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
def list_agent_runs(
    task_id: int | None = None,
    role: str | None = None,
    status: str | None = None,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    conn = get_conn()
    cur = conn.cursor()
    require_actor_permission(cur, x_actor_name, "read")
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
def list_task_agent_runs(task_id: int, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
    return list_agent_runs(task_id=task_id, x_actor_name=x_actor_name)


@app.get("/tasks/{task_id}/agent-runs/summary")
def get_task_agent_run_summary(task_id: int, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
    conn = get_conn()
    cur = conn.cursor()
    require_actor_permission(cur, x_actor_name, "read")
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
def get_agent_run(agent_run_id: int, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
    conn = get_conn()
    cur = conn.cursor()
    require_actor_permission(cur, x_actor_name, "read")
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
def list_agent_run_messages(
    agent_run_id: int,
    limit: int | None = 50,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    conn = get_conn()
    cur = conn.cursor()
    require_actor_permission(cur, x_actor_name, "read")
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
def list_agent_run_artifacts(
    agent_run_id: int,
    limit: int | None = 50,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    conn = get_conn()
    cur = conn.cursor()
    require_actor_permission(cur, x_actor_name, "read")
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


def fetch_evaluator_runs(
    cur,
    *,
    task_id: int | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
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
    return [serialize_evaluator_run_row(row) for row in cur.fetchall()]


@app.get("/evaluator-runs")
def list_evaluator_runs(
    task_id: int | None = None,
    limit: int = 20,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    conn = get_conn()
    cur = conn.cursor()
    try:
        require_actor_permission(cur, x_actor_name, "read")
        return list_evaluator_runs_response(
            cur,
            task_id=task_id,
            limit=limit,
            serialize_evaluator_run_row_fn=serialize_evaluator_run_row,
        )
    finally:
        cur.close()
        conn.close()


@app.get("/tasks/{task_id}/evaluator-runs")
def list_task_evaluator_runs(
    task_id: int,
    limit: int = 20,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    return list_evaluator_runs(task_id=task_id, limit=limit, x_actor_name=x_actor_name)


@app.get("/tasks/{task_id}/evaluator-runs/latest")
def get_latest_task_evaluator_run(task_id: int, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
    conn = get_conn()
    cur = conn.cursor()
    try:
        require_actor_permission(cur, x_actor_name, "read")
        return get_latest_task_evaluator_run_response(
            cur,
            task_id=task_id,
            task_exists_fn=task_exists,
            fetch_latest_evaluator_for_task_fn=fetch_latest_evaluator_for_task,
        )
    finally:
        cur.close()
        conn.close()


@app.get("/tasks/{task_id}/workflow-proposals/latest")
def get_latest_task_workflow_proposal(
    task_id: int,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    conn = get_conn()
    cur = conn.cursor()
    try:
        require_actor_permission(cur, x_actor_name, "read")
        return get_latest_task_workflow_proposal_response(
            cur,
            task_id=task_id,
            task_exists_fn=task_exists,
            fetch_latest_evaluator_for_task_fn=fetch_latest_evaluator_for_task,
            serialize_workflow_proposal_fn=serialize_workflow_proposal,
        )
    finally:
        cur.close()
        conn.close()


@app.get("/workflow-proposals")
def list_workflow_proposals(
    task_id: int | None = None,
    action_key: str | None = None,
    priority: str | None = None,
    limit: int = 20,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    conn = get_conn()
    cur = conn.cursor()
    try:
        require_actor_permission(cur, x_actor_name, "read")
        return list_workflow_proposals_response(
            cur,
            task_id=task_id,
            action_key=action_key,
            priority=priority,
            limit=limit,
            list_workflow_proposals_rows_fn=list_workflow_proposals_rows,
        )
    finally:
        cur.close()
        conn.close()


@app.get("/tasks/{task_id}/workflow-proposals")
def list_task_workflow_proposals(
    task_id: int,
    limit: int = 20,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    conn = get_conn()
    cur = conn.cursor()
    try:
        require_actor_permission(cur, x_actor_name, "read")
        return list_task_workflow_proposals_or_404(
            cur,
            task_id=task_id,
            limit=limit,
            task_exists_fn=task_exists,
            list_workflow_proposals_rows_fn=list_workflow_proposals_rows,
        )
    finally:
        cur.close()
        conn.close()


@app.get("/workflow-proposals/{proposal_id}")
def get_workflow_proposal(proposal_id: int, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
    conn = get_conn()
    cur = conn.cursor()
    try:
        require_actor_permission(cur, x_actor_name, "read")
        return get_workflow_proposal_response(
            cur,
            proposal_id=proposal_id,
            get_workflow_proposal_or_404_fn=get_workflow_proposal_or_404,
            serialize_evaluator_run_row_fn=serialize_evaluator_run_row,
            serialize_workflow_proposal_fn=serialize_workflow_proposal,
        )
    finally:
        cur.close()
        conn.close()


@app.get("/workflow-proposals/{proposal_id}/shadow-validation")
def get_workflow_proposal_shadow_validation(
    proposal_id: int,
    history_limit: int = 10,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    workflow_proposal = get_workflow_proposal(proposal_id, x_actor_name=x_actor_name)
    conn = get_conn()
    cur = conn.cursor()
    try:
        require_actor_permission(cur, x_actor_name, "read")
        return build_workflow_proposal_shadow_validation_response(
            cur,
            workflow_proposal=workflow_proposal,
            proposal_id=proposal_id,
            history_limit=history_limit,
            build_workflow_proposal_shadow_status_fn=lambda current_cur, **kwargs: build_workflow_proposal_shadow_status(
                current_cur,
                build_workflow_proposal_shadow_validation_status_fn=build_workflow_proposal_shadow_validation_status_with_context,
                **kwargs,
            ),
        )
    finally:
        cur.close()
        conn.close()


@app.get("/workflow-proposals/{proposal_id}/change-request-draft")
def preview_workflow_proposal_change_request_draft(
    proposal_id: int,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    conn = get_conn()
    cur = conn.cursor()
    try:
        require_actor_permission(cur, x_actor_name, "read")
        workflow_proposal = get_workflow_proposal(proposal_id, x_actor_name=x_actor_name)
        return get_workflow_proposal_change_request_draft_response(
            cur,
            workflow_proposal=workflow_proposal,
            suggest_change_request_draft_from_workflow_proposal_fn=suggest_change_request_draft_from_workflow_proposal_with_context,
            attach_patch_artifacts_to_change_request_draft_fn=attach_patch_artifacts_to_change_request_draft_with_context,
            attach_shadow_validation_state_to_change_request_draft_fn=attach_shadow_validation_state_to_change_request_draft_with_context,
        )
    finally:
        cur.close()
        conn.close()


@app.post("/workflow-proposals/{proposal_id}/change-request-draft")
def create_change_request_from_workflow_proposal(
    proposal_id: int,
    request: WorkflowProposalBridgeRequest,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    workflow_proposal = get_workflow_proposal(proposal_id, x_actor_name=x_actor_name)
    conn = get_conn()
    cur = conn.cursor()
    try:
        result = create_change_request_from_workflow_proposal_draft(
            cur,
            proposal_id=proposal_id,
            workflow_proposal=workflow_proposal,
            request=request,
            x_actor_name=x_actor_name,
            supported_change_target_types=SUPPORTED_CHANGE_TARGET_TYPES,
            require_actor_permission_fn=require_actor_permission,
            build_change_request_draft_from_workflow_proposal_fn=build_change_request_draft_from_workflow_proposal,
            create_change_request_row_fn=create_change_request_row,
            serialize_change_request_row_fn=serialize_change_request_row,
            record_audit_event_fn=record_audit_event,
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()
    return result


def execute_workflow_proposal_shadow_validation(
    *,
    workflow_proposal: dict[str, Any],
    request: WorkflowProposalShadowValidationRequest,
    x_actor_name: str | None,
    source_change_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    conn = get_conn()
    cur = conn.cursor()
    try:
        launch_result = launch_workflow_proposal_shadow_validation(
            cur,
            workflow_proposal=workflow_proposal,
            request=request,
            x_actor_name=x_actor_name,
            source_change_request=source_change_request,
            require_actor_permission_fn=require_actor_permission,
            enforce_task_quota_fn=enforce_task_quota,
            prepare_shadow_validation_baseline_fn=prepare_shadow_validation_baseline,
            resolve_shadow_validation_candidate_overlay_fn=resolve_shadow_validation_candidate_overlay_with_context,
            build_shadow_validation_runtime_overrides_fn=build_shadow_validation_runtime_overrides,
            build_shadow_validation_execution_payload_fn=build_shadow_validation_execution_payload_with_context,
            parse_optional_int_fn=parse_optional_int,
            safe_json_dumps_fn=safe_json_dumps,
            insert_audit_log_fn=insert_audit_log,
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()

    shadow_context = launch_result["shadow_context"]
    shadow_task = launch_result["shadow_task"]
    return complete_workflow_proposal_shadow_validation(
        workflow_proposal=workflow_proposal,
        request=request,
        source_change_request=source_change_request,
        shadow_context=shadow_context,
        shadow_task=shadow_task,
        enqueue_task_fn=enqueue_task,
        finalize_shadow_validation_response_fn=finalize_shadow_validation_response_with_context,
    )


@app.post("/workflow-proposals/{proposal_id}/shadow-validate")
def shadow_validate_workflow_proposal(
    proposal_id: int,
    request: WorkflowProposalShadowValidationRequest,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    workflow_proposal = get_workflow_proposal(proposal_id, x_actor_name=x_actor_name)
    return execute_workflow_proposal_shadow_validation(
        workflow_proposal=workflow_proposal,
        request=request,
        x_actor_name=x_actor_name,
    )


@app.post("/change-requests/{change_request_id}/shadow-validate")
def shadow_validate_change_request(
    change_request_id: int,
    request: WorkflowProposalShadowValidationRequest,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    conn = get_conn()
    cur = conn.cursor()
    try:
        shadow_target = resolve_change_request_shadow_validation_target(
            cur,
            change_request_id=change_request_id,
            x_actor_name=x_actor_name,
            require_actor_permission_fn=require_actor_permission,
            get_change_request_or_404_fn=get_change_request_or_404,
            ensure_change_requests_table_fn=ensure_change_requests_table,
            ensure_change_request_shadow_validation_eligible_fn=ensure_change_request_shadow_validation_eligible,
            parse_optional_int_fn=parse_optional_int,
            get_workflow_proposal_fn=get_workflow_proposal,
        )
    finally:
        cur.close()
        conn.close()
    return execute_workflow_proposal_shadow_validation(
        workflow_proposal=shadow_target["workflow_proposal"],
        request=request,
        x_actor_name=x_actor_name,
        source_change_request=shadow_target["change_request"],
    )


@app.get("/evaluator-runs/{evaluator_run_id}")
def get_evaluator_run(evaluator_run_id: int, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
    conn = get_conn()
    cur = conn.cursor()
    try:
        require_actor_permission(cur, x_actor_name, "read")
        return get_evaluator_run_or_404(
            cur,
            evaluator_run_id,
            fetch_evaluator_run_row_fn=fetch_evaluator_run_row,
            serialize_evaluator_run_row_fn=serialize_evaluator_run_row,
        )
    finally:
        cur.close()
        conn.close()


@app.get("/monitor/overview")
def get_monitor_overview(x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
    conn = get_conn()
    cur = conn.cursor()
    require_actor_permission(cur, x_actor_name, "read")
    ensure_risk_policies_table(cur)
    ensure_access_actors_table(cur)
    ensure_access_quotas_table(cur)
    ensure_tool_registry_table(cur)
    ensure_model_providers_table(cur)
    ensure_model_routes_table(cur)
    ensure_change_requests_table(cur)
    ensure_agent_tables(cur)
    conn.commit()
    overview_snapshot = fetch_monitor_overview_snapshot(
        cur,
        build_task_display_user_input_fn=build_task_display_user_input,
        extract_task_clarification_state_fn=extract_task_clarification_state,
        parse_maybe_json_fn=parse_maybe_json,
        serialize_session_review_row_fn=serialize_session_review_row,
        serialize_agent_run_row_fn=serialize_agent_run_row,
        serialize_evaluator_run_row_fn=serialize_evaluator_run_row,
        list_workflow_proposals_rows_fn=list_workflow_proposals_rows,
    )
    tasks_by_status = overview_snapshot["tasks_by_status"]
    total_tasks = overview_snapshot["total_tasks"]
    total_sessions = overview_snapshot["total_sessions"]
    total_memories = overview_snapshot["total_memories"]
    total_session_states = overview_snapshot["total_session_states"]
    total_session_reviews = overview_snapshot["total_session_reviews"]
    sessions_missing_state_count = overview_snapshot["sessions_missing_state_count"]
    sessions_missing_review_count = overview_snapshot["sessions_missing_review_count"]
    active_session_count = overview_snapshot["active_session_count"]
    sessions_needing_review_count = overview_snapshot["sessions_needing_review_count"]
    sessions_with_duplicate_memories_count = overview_snapshot["sessions_with_duplicate_memories_count"]
    sessions_with_open_loops_count = overview_snapshot["sessions_with_open_loops_count"]
    daily_reviews_today = overview_snapshot["daily_reviews_today"]
    pending_approvals = overview_snapshot["pending_approvals"]
    risk_policy_count = overview_snapshot["risk_policy_count"]
    tool_registry_count = overview_snapshot["tool_registry_count"]
    disabled_tool_count = overview_snapshot["disabled_tool_count"]
    model_route_count = overview_snapshot["model_route_count"]
    disabled_model_route_count = overview_snapshot["disabled_model_route_count"]
    model_provider_count = overview_snapshot["model_provider_count"]
    disabled_model_provider_count = overview_snapshot["disabled_model_provider_count"]
    total_change_requests = overview_snapshot["total_change_requests"]
    pending_change_requests = overview_snapshot["pending_change_requests"]
    approved_change_requests = overview_snapshot["approved_change_requests"]
    rejected_change_requests = overview_snapshot["rejected_change_requests"]
    applied_change_requests = overview_snapshot["applied_change_requests"]
    closed_change_requests = overview_snapshot["closed_change_requests"]
    change_request_closure_ratio = overview_snapshot["change_request_closure_ratio"]
    access_actor_count = overview_snapshot["access_actor_count"]
    access_quota_count = overview_snapshot["access_quota_count"]
    quota_pressure_count = overview_snapshot["quota_pressure_count"]
    actors_by_role = overview_snapshot["actors_by_role"]
    checkpointed_tasks = overview_snapshot["checkpointed_tasks"]
    recent_audit_logs = overview_snapshot["recent_audit_logs"]
    recent_tasks = overview_snapshot["recent_tasks"]
    total_agent_runs = overview_snapshot["total_agent_runs"]
    agent_runs_by_status = overview_snapshot["agent_runs_by_status"]
    agent_runs_by_role = overview_snapshot["agent_runs_by_role"]
    blocked_agent_runs = int(agent_runs_by_status.get("blocked", 0))
    running_agent_runs = int(agent_runs_by_status.get("running", 0))
    total_agent_messages = overview_snapshot["total_agent_messages"]
    total_agent_artifacts = overview_snapshot["total_agent_artifacts"]

    stage56_metrics = fetch_stage56_overview_metrics(
        cur,
        fetch_task_agent_summary_fn=fetch_task_agent_summary,
        specialist_execution_modes=list(MAINLINE_SPECIALIST_EXECUTION_MODES),
        specialist_tool_profiles=list(MAINLINE_SPECIALIST_TOOL_PROFILES),
    )
    stage5_summary_rows = stage56_metrics["stage5_summary_rows"]
    tasks_requiring_execute = stage56_metrics["tasks_requiring_execute"]
    tasks_requiring_finalize = stage56_metrics["tasks_requiring_finalize"]
    tasks_requiring_retry = stage56_metrics["tasks_requiring_retry"]
    tasks_requiring_operator_escalation = stage56_metrics["tasks_requiring_operator_escalation"]
    stage5_mainline_task_count = stage56_metrics["stage5_mainline_task_count"]
    stage5_runtime_fanout_task_count = stage56_metrics["stage5_runtime_fanout_task_count"]
    stage5_role_skeleton_ready_count = stage56_metrics["stage5_role_skeleton_ready_count"]
    stage5_terminal_mainline_task_count = stage56_metrics["stage5_terminal_mainline_task_count"]
    stage5_terminal_ready_count = stage56_metrics["stage5_terminal_ready_count"]
    stage5_non_readonly_specialist_task_count = stage56_metrics["stage5_non_readonly_specialist_task_count"]
    specialist_subtasks_by_type = stage56_metrics["specialist_subtasks_by_type"]

    recent_reviews = overview_snapshot["recent_reviews"]
    recent_agent_runs = overview_snapshot["recent_agent_runs"]
    total_evaluator_runs = overview_snapshot["total_evaluator_runs"]
    evaluator_runs_by_decision = overview_snapshot["evaluator_runs_by_decision"]
    evaluator_runs_by_reason = overview_snapshot["evaluator_runs_by_reason"]
    avg_evaluator_score = overview_snapshot["avg_evaluator_score"]
    recent_evaluator_runs = overview_snapshot["recent_evaluator_runs"]
    workflow_proposal_rows = overview_snapshot["workflow_proposal_rows"]
    workflow_proposals_by_action = overview_snapshot["workflow_proposals_by_action"]
    workflow_proposals_by_priority = overview_snapshot["workflow_proposals_by_priority"]
    total_workflow_proposals = overview_snapshot["total_workflow_proposals"]

    stage6_mainline_evaluator_run_count = stage56_metrics["stage6_mainline_evaluator_run_count"]
    stage6_mainline_workflow_proposal_count = stage56_metrics["stage6_mainline_workflow_proposal_count"]
    stage6_auto_mapped_proposal_count = stage56_metrics["stage6_auto_mapped_proposal_count"]
    stage6_mainline_bridged_change_request_count = stage56_metrics["stage6_mainline_bridged_change_request_count"]
    stage5_runtime_fanout_event_count = stage56_metrics["stage5_runtime_fanout_event_count"]
    stage5_runtime_fanin_event_count = stage56_metrics["stage5_runtime_fanin_event_count"]
    stage5_runtime_execute_event_count = stage56_metrics["stage5_runtime_execute_event_count"]
    stage6_shadow_validation_count = stage56_metrics["stage6_shadow_validation_count"]
    stage6_failure_taxonomy_count = stage56_metrics["stage6_failure_taxonomy_count"]
    stage7_metrics = fetch_stage7_overview_metrics(cur)
    stage7_workflow_improvement_change_request_count = stage7_metrics["stage7_workflow_improvement_change_request_count"]
    stage7_shadow_required_change_request_count = stage7_metrics["stage7_shadow_required_change_request_count"]
    stage7_shadow_completed_change_request_count = stage7_metrics["stage7_shadow_completed_change_request_count"]
    stage7_candidate_overlay_validation_count = stage7_metrics["stage7_candidate_overlay_validation_count"]
    stage7_candidate_match_change_request_count = stage7_metrics["stage7_candidate_match_change_request_count"]
    stage7_patch_artifact_ready_count = stage7_metrics["stage7_patch_artifact_ready_count"]
    stage7_rollback_ready_count = stage7_metrics["stage7_rollback_ready_count"]
    stage7_rollback_change_request_count = stage7_metrics["stage7_rollback_change_request_count"]
    stage7_rollback_applied_count = stage7_metrics["stage7_rollback_applied_count"]
    stage7_sandbox_file_applied_count = stage7_metrics["stage7_sandbox_file_applied_count"]
    stage7_sandbox_source_copy_applied_count = stage7_metrics["stage7_sandbox_source_copy_applied_count"]
    stage7_sandbox_source_patch_applied_count = stage7_metrics["stage7_sandbox_source_patch_applied_count"]
    stage7_sandbox_acceptance_passed_count = stage7_metrics["stage7_sandbox_acceptance_passed_count"]
    stage7_sandbox_acceptance_failed_count = stage7_metrics["stage7_sandbox_acceptance_failed_count"]
    stage7_sandbox_auto_rollback_applied_count = stage7_metrics["stage7_sandbox_auto_rollback_applied_count"]

    last_daily_review_at = overview_snapshot["last_daily_review_at"]

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
        stage7_workflow_improvement_change_request_count=stage7_workflow_improvement_change_request_count,
        stage7_shadow_required_change_request_count=stage7_shadow_required_change_request_count,
        stage7_shadow_completed_change_request_count=stage7_shadow_completed_change_request_count,
        stage7_candidate_overlay_validation_count=stage7_candidate_overlay_validation_count,
        stage7_candidate_match_change_request_count=stage7_candidate_match_change_request_count,
        stage7_patch_artifact_ready_count=stage7_patch_artifact_ready_count,
        stage7_rollback_ready_count=stage7_rollback_ready_count,
        stage7_rollback_change_request_count=stage7_rollback_change_request_count,
        stage7_rollback_applied_count=stage7_rollback_applied_count,
        stage7_sandbox_file_applied_count=stage7_sandbox_file_applied_count,
        stage7_sandbox_source_copy_applied_count=stage7_sandbox_source_copy_applied_count,
        stage7_sandbox_source_patch_applied_count=stage7_sandbox_source_patch_applied_count,
        stage7_sandbox_acceptance_passed_count=stage7_sandbox_acceptance_passed_count,
        stage7_sandbox_acceptance_failed_count=stage7_sandbox_acceptance_failed_count,
        stage7_sandbox_auto_rollback_applied_count=stage7_sandbox_auto_rollback_applied_count,
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
def list_sessions(x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
    conn = get_conn()
    cur = conn.cursor()
    require_actor_permission(cur, x_actor_name, "read")
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
def get_session(session_id: int, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
    conn = get_conn()
    cur = conn.cursor()
    require_actor_permission(cur, x_actor_name, "read")
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
def list_session_tasks(session_id: int, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
    conn = get_conn()
    cur = conn.cursor()
    require_actor_permission(cur, x_actor_name, "read")
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
def get_session_summary(session_id: int, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
    conn = get_conn()
    cur = conn.cursor()
    require_actor_permission(cur, x_actor_name, "read")
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
    for row in recent_tasks:
        attach_task_display_fields(row)
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
def get_session_health(session_id: int, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
    conn = get_conn()
    cur = conn.cursor()
    require_actor_permission(cur, x_actor_name, "read")
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
    session_row, task_rows, memory_rows, session_state_row = refresh_session_review_context(cur, session_id)

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

        session_row, task_rows, memory_rows, session_state_row = refresh_session_review_context(cur, session_id)
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
def list_session_reviews(
    session_id: int,
    limit: int | None = 20,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    conn = get_conn()
    cur = conn.cursor()
    require_actor_permission(cur, x_actor_name, "read")
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
def get_session_state(session_id: int, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
    conn = get_conn()
    cur = conn.cursor()
    require_actor_permission(cur, x_actor_name, "read")
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
        SELECT id, session_id, user_input, status, result, updated_at, runtime_overrides
        FROM task_runs
        WHERE session_id = %s
        ORDER BY updated_at DESC, id DESC;
        """,
        (session_id,),
    )
    task_rows = list(cur.fetchall())
    refresh_session_task_summary_memories(cur, task_rows)

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
    refreshed_state = upsert_computed_session_state(cur, session_id, computed_state)
    refresh_session_reviews(
        cur,
        session_row=session_row,
        task_rows=task_rows,
        memory_rows=memory_rows,
        session_state_row=refreshed_state,
    )
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
    return refreshed_state


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
def list_session_memories(
    session_id: int,
    category: str | None = None,
    limit: int | None = 50,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    conn = get_conn()
    cur = conn.cursor()
    require_actor_permission(cur, x_actor_name, "read")
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


@app.get("/tasks/{task_id}")
def get_task(task_id: int, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
    conn = get_conn()
    cur = conn.cursor()
    require_actor_permission(cur, x_actor_name, "read")
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
            runtime_overrides,
            task_intent_json,
            deliverable_spec_json,
            validation_report_json,
            recovery_action_json,
            created_at,
            updated_at
        FROM task_runs
        WHERE id = %s;
    """,
        (task_id,),
    )
    row = cur.fetchone()

    if row:
        attach_task_display_fields(row)
        row["task_intent"] = parse_maybe_json(row.get("task_intent_json")) or {}
        row["deliverable_spec"] = parse_maybe_json(row.get("deliverable_spec_json")) or {}
        row["validation_report"] = parse_maybe_json(row.get("validation_report_json")) or {}
        row["recovery_action"] = parse_maybe_json(row.get("recovery_action_json")) or {}
        row.pop("task_intent_json", None)
        row.pop("deliverable_spec_json", None)
        row.pop("validation_report_json", None)
        row.pop("recovery_action_json", None)
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
        SELECT id, user_input, status, session_id, runtime_overrides, created_at, updated_at
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

    manager_objective = objective or build_task_display_user_input(
        str(task_row.get("user_input") or ""),
        parse_maybe_json(task_row.get("runtime_overrides")) or {},
    )
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
        SELECT id, user_input, status, result, error_message, runtime_overrides, created_at, updated_at
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

    manager_objective = build_task_display_user_input(
        str(task_row.get("user_input") or ""),
        parse_maybe_json(task_row.get("runtime_overrides")) or {},
    )
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

    cur.execute(
        "SELECT id, user_input, status, runtime_overrides FROM task_runs WHERE id = %s;",
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
    manager_objective = build_task_display_user_input(
        str(task_row.get("user_input") or ""),
        parse_maybe_json(task_row.get("runtime_overrides")) or {},
    )
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
        SELECT id, user_input, status, result, error_message, runtime_overrides, created_at, updated_at
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

    manager_objective = summary or build_task_display_user_input(
        str(task_row.get("user_input") or ""),
        parse_maybe_json(task_row.get("runtime_overrides")) or {},
    )
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
def get_task_steps(task_id: int, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
    conn = get_conn()
    cur = conn.cursor()
    require_actor_permission(cur, x_actor_name, "read")

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


@app.get("/tasks/{task_id}/traces")
def get_task_traces(task_id: int, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
    conn = get_conn()
    cur = conn.cursor()
    require_actor_permission(cur, x_actor_name, "read")
    ensure_trace_tables(cur)

    cur.execute("SELECT id FROM task_runs WHERE id = %s;", (task_id,))
    if not cur.fetchone():
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Task not found")

    cur.execute(
        """
        SELECT *
        FROM task_traces
        WHERE task_run_id = %s
        ORDER BY id DESC
        LIMIT 1;
        """,
        (task_id,),
    )
    task_trace = cur.fetchone()

    cur.execute(
        """
        SELECT *
        FROM step_traces
        WHERE task_run_id = %s
        ORDER BY step_order ASC, id ASC;
        """,
        (task_id,),
    )
    step_traces = list(cur.fetchall())

    cur.execute(
        """
        SELECT *
        FROM model_traces
        WHERE task_run_id = %s
        ORDER BY id ASC;
        """,
        (task_id,),
    )
    model_traces = list(cur.fetchall())

    cur.execute(
        """
        SELECT *
        FROM tool_traces
        WHERE task_run_id = %s
        ORDER BY id ASC;
        """,
        (task_id,),
    )
    tool_traces = list(cur.fetchall())

    cur.execute(
        """
        SELECT *
        FROM skill_traces
        WHERE task_run_id = %s
        ORDER BY id ASC;
        """,
        (task_id,),
    )
    skill_traces = list(cur.fetchall())

    cur.execute(
        """
        SELECT *
        FROM retrieval_traces
        WHERE task_run_id = %s
        ORDER BY id ASC;
        """,
        (task_id,),
    )
    retrieval_traces = list(cur.fetchall())

    cur.close()
    conn.close()

    return {
        "task_id": task_id,
        "task_trace": task_trace,
        "step_traces": step_traces,
        "model_traces": model_traces,
        "tool_traces": tool_traces,
        "skill_traces": skill_traces,
        "retrieval_traces": retrieval_traces,
    }


def build_task_replay_payload(cur, task_id: int) -> dict[str, Any]:
    ensure_trace_tables(cur)
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
            runtime_overrides,
            created_at,
            updated_at
        FROM task_runs
        WHERE id = %s;
        """,
        (task_id,),
    )
    task_row = cur.fetchone()
    if not task_row:
        raise HTTPException(status_code=404, detail="Task not found")
    task_row["runtime_overrides"] = parse_maybe_json(task_row.get("runtime_overrides")) or {}

    cur.execute(
        """
        SELECT *
        FROM task_traces
        WHERE task_run_id = %s
        ORDER BY id DESC
        LIMIT 1;
        """,
        (task_id,),
    )
    task_trace = cur.fetchone()

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
    step_rows = list(cur.fetchall())

    cur.execute(
        """
        SELECT *
        FROM step_traces
        WHERE task_run_id = %s
        ORDER BY step_order ASC, id ASC;
        """,
        (task_id,),
    )
    step_traces = list(cur.fetchall())

    cur.execute(
        """
        SELECT *
        FROM model_traces
        WHERE task_run_id = %s
        ORDER BY id ASC;
        """,
        (task_id,),
    )
    model_traces = list(cur.fetchall())

    cur.execute(
        """
        SELECT *
        FROM tool_traces
        WHERE task_run_id = %s
        ORDER BY id ASC;
        """,
        (task_id,),
    )
    tool_traces = list(cur.fetchall())

    cur.execute(
        """
        SELECT *
        FROM skill_traces
        WHERE task_run_id = %s
        ORDER BY id ASC;
        """,
        (task_id,),
    )
    skill_traces = list(cur.fetchall())

    cur.execute(
        """
        SELECT *
        FROM retrieval_traces
        WHERE task_run_id = %s
        ORDER BY id ASC;
        """,
        (task_id,),
    )
    retrieval_traces = list(cur.fetchall())

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
        ORDER BY id ASC;
        """,
        (task_id,),
    )
    approvals = list(cur.fetchall())

    step_trace_map: dict[int, list[dict[str, Any]]] = {}
    model_trace_map: dict[int, list[dict[str, Any]]] = {}
    tool_trace_map: dict[int, list[dict[str, Any]]] = {}
    skill_trace_map: dict[int, list[dict[str, Any]]] = {}
    retrieval_trace_map: dict[int, list[dict[str, Any]]] = {}
    approval_map: dict[int, list[dict[str, Any]]] = {}

    for item in step_traces:
        step_trace_map.setdefault(int(item.get("task_step_id") or 0), []).append(item)
    for item in model_traces:
        model_trace_map.setdefault(int(item.get("task_step_id") or 0), []).append(item)
    for item in tool_traces:
        tool_trace_map.setdefault(int(item.get("task_step_id") or 0), []).append(item)
    for item in skill_traces:
        skill_trace_map.setdefault(int(item.get("task_step_id") or 0), []).append(item)
    for item in retrieval_traces:
        retrieval_trace_map.setdefault(int(item.get("task_step_id") or 0), []).append(item)
    for item in approvals:
        approval_map.setdefault(int(item.get("step_order") or 0), []).append(
            {
                **item,
                "input_payload": parse_maybe_json(item.get("input_payload")),
            }
        )

    replay_steps: list[dict[str, Any]] = []
    for step in step_rows:
        step_id = int(step["id"])
        step_order = int(step.get("step_order") or 0)
        parsed_input = parse_maybe_json(step.get("input_payload"))
        parsed_output_data = parse_maybe_json(step.get("output_data"))
        parsed_run_if = parse_maybe_json(step.get("run_if"))
        parsed_skip_if = parse_maybe_json(step.get("skip_if"))
        step_skill_traces = skill_trace_map.get(step_id, [])
        uses_skill = bool(step_skill_traces) or bool((task_row["runtime_overrides"] or {}).get("skill_invocation"))
        replay_steps.append(
            {
                "task_step_id": step_id,
                "step_order": step_order,
                "step_name": step.get("step_name") or f"步骤 {step_order}",
                "tool_name": step.get("tool_name") or "",
                "status": step.get("status") or "",
                "input_payload": parsed_input,
                "output_payload": step.get("output_payload"),
                "output_data": parsed_output_data,
                "error_message": step.get("error_message") or "",
                "run_if": parsed_run_if,
                "skip_if": parsed_skip_if,
                "retry_count": int(step.get("retry_count") or 0),
                "max_retries": int(step.get("max_retries") or 0),
                "error_strategy": step.get("error_strategy") or "fail",
                "created_at": step.get("created_at"),
                "updated_at": step.get("updated_at"),
                "approvals": approval_map.get(step_order, []),
                "traces": {
                    "step_traces": step_trace_map.get(step_id, []),
                    "model_traces": model_trace_map.get(step_id, []),
                    "tool_traces": tool_trace_map.get(step_id, []),
                    "skill_traces": step_skill_traces,
                    "retrieval_traces": retrieval_trace_map.get(step_id, []),
                },
                "trace_counts": {
                    "step": len(step_trace_map.get(step_id, [])),
                    "model": len(model_trace_map.get(step_id, [])),
                    "tool": len(tool_trace_map.get(step_id, [])),
                    "skill": len(step_skill_traces),
                    "retrieval": len(retrieval_trace_map.get(step_id, [])),
                },
                "replay_hints": {
                    "uses_skill": uses_skill,
                    "has_input_payload": parsed_input is not None,
                    "has_output_payload": bool(step.get("output_payload")),
                    "has_output_data": parsed_output_data is not None,
                    "approval_blocked": any(item.get("status") == "pending" for item in approval_map.get(step_order, [])),
                },
            }
        )

    return {
        "task": task_row,
        "task_trace": task_trace,
        "summary": {
            "mode": "read_only_trace_replay_v1",
            "plan_source": (task_trace or {}).get("plan_source") or "",
            "task_status": task_row.get("status") or "",
            "step_count": len(replay_steps),
            "completed_step_count": sum(1 for item in replay_steps if item.get("status") == "completed"),
            "failed_step_count": sum(1 for item in replay_steps if item.get("status") == "failed"),
            "waiting_approval_count": sum(1 for item in replay_steps if item.get("status") == "waiting_approval"),
            "model_trace_count": len(model_traces),
            "tool_trace_count": len(tool_traces),
            "skill_trace_count": len(skill_traces),
            "retrieval_trace_count": len(retrieval_traces),
            "has_explicit_skill": bool((task_row["runtime_overrides"] or {}).get("skill_invocation")),
        },
        "steps": replay_steps,
    }


@app.get("/tasks/{task_id}/replay")
def get_task_replay(task_id: int, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
    conn = get_conn()
    cur = conn.cursor()
    require_actor_permission(cur, x_actor_name, "read")
    payload = build_task_replay_payload(cur, task_id)
    cur.close()
    conn.close()
    return payload


@app.get("/tasks/{task_id}/steps/{step_id}/traces")
def get_task_step_traces(
    task_id: int,
    step_id: int,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    conn = get_conn()
    cur = conn.cursor()
    require_actor_permission(cur, x_actor_name, "read")
    ensure_trace_tables(cur)

    cur.execute("SELECT id FROM task_runs WHERE id = %s;", (task_id,))
    if not cur.fetchone():
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Task not found")

    cur.execute(
        """
        SELECT id, task_id, step_order, step_name, tool_name, status
        FROM task_steps
        WHERE id = %s AND task_id = %s;
        """,
        (step_id, task_id),
    )
    step_row = cur.fetchone()
    if not step_row:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Task step not found")

    cur.execute(
        """
        SELECT *
        FROM step_traces
        WHERE task_run_id = %s AND task_step_id = %s
        ORDER BY id ASC;
        """,
        (task_id, step_id),
    )
    step_traces = list(cur.fetchall())

    cur.execute(
        """
        SELECT *
        FROM model_traces
        WHERE task_run_id = %s AND task_step_id = %s
        ORDER BY id ASC;
        """,
        (task_id, step_id),
    )
    model_traces = list(cur.fetchall())

    cur.execute(
        """
        SELECT *
        FROM tool_traces
        WHERE task_run_id = %s AND task_step_id = %s
        ORDER BY id ASC;
        """,
        (task_id, step_id),
    )
    tool_traces = list(cur.fetchall())

    cur.execute(
        """
        SELECT *
        FROM skill_traces
        WHERE task_run_id = %s AND task_step_id = %s
        ORDER BY id ASC;
        """,
        (task_id, step_id),
    )
    skill_traces = list(cur.fetchall())

    cur.execute(
        """
        SELECT *
        FROM retrieval_traces
        WHERE task_run_id = %s AND task_step_id = %s
        ORDER BY id ASC;
        """,
        (task_id, step_id),
    )
    retrieval_traces = list(cur.fetchall())

    cur.close()
    conn.close()

    return {
        "task_id": task_id,
        "step": step_row,
        "step_traces": step_traces,
        "model_traces": model_traces,
        "tool_traces": tool_traces,
        "skill_traces": skill_traces,
        "retrieval_traces": retrieval_traces,
    }


@app.get("/approvals")
def list_approvals(status: str | None = None, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
    conn = get_conn()
    cur = conn.cursor()
    require_actor_permission(cur, x_actor_name, "read")

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
def get_task_checkpoint(task_id: int, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
    conn = get_conn()
    cur = conn.cursor()
    require_actor_permission(cur, x_actor_name, "read")
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


def resolve_recovery_action_resume_step(cur, task_id: int, task: dict[str, Any], action: str) -> int:
    action_key = str(action or "").strip()
    if action_key == "retry_generate":
        cur.execute(
            """
            SELECT step_order
            FROM task_steps
            WHERE task_id = %s AND tool_name = 'generate_text'
            ORDER BY step_order ASC
            LIMIT 1;
            """,
            (task_id,),
        )
        row = cur.fetchone()
        return int((row or {}).get("step_order") or task.get("current_step") or 1)
    if action_key == "retry":
        return resolve_resume_from_step(cur, task_id, task.get("current_step"))
    if action_key == "replan":
        return 1
    raise HTTPException(status_code=400, detail=f"Recovery action {action_key or '(empty)'} is not directly executable")


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

    resume_from = resolve_resume_from_step(cur, task_id, request.from_step or task.get("current_step"))
    reset_task_for_resume(
        cur,
        task_id=task_id,
        task=task,
        resume_from=resume_from,
        actor=actor,
        note=request.note.strip(),
        event_type="task.resume",
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


@app.post("/tasks/{task_id}/apply-recovery-action")
def apply_recovery_action(
    task_id: int,
    request: TaskResumeRequest,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    conn = get_conn()
    cur = conn.cursor()
    actor = require_actor_permission(cur, x_actor_name, "operate")

    task = get_task_or_404(cur, task_id)
    if task["status"] not in {"failed", "paused"}:
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Only failed or paused tasks can apply recovery action")

    cur.execute(
        """
        SELECT recovery_action_json
        FROM task_runs
        WHERE id = %s;
        """,
        (task_id,),
    )
    action_row = cur.fetchone() or {}
    recovery_action = parse_maybe_json(action_row.get("recovery_action_json")) or {}
    action_key = str(recovery_action.get("action") or "").strip()
    if not action_key or action_key == "none":
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Task has no actionable recovery action")

    cur.execute(
        """
        SELECT id
        FROM approvals
        WHERE task_id = %s AND status = 'pending'
        ORDER BY id DESC;
        """,
        (task_id,),
    )
    if cur.fetchall():
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Task has pending approvals; approve or reject them first")

    resume_from = resolve_recovery_action_resume_step(cur, task_id, task, action_key)
    if request.from_step is not None:
        resume_from = int(request.from_step)

    reset_task_for_resume(
        cur,
        task_id=task_id,
        task=task,
        resume_from=resume_from,
        actor=actor,
        note=request.note.strip() or f"apply recovery action: {action_key}",
        event_type="task.apply_recovery_action",
        details={
            "recovery_action": action_key,
        },
    )

    conn.commit()
    cur.close()
    conn.close()

    enqueue_task(task_id)
    update_checkpoint_status(task.get("checkpoint_path"), "pending", request.note.strip() or f"apply recovery action: {action_key}")
    logger.info(
        "task recovery action applied id=%s actor=%s action=%s from_step=%s previous_status=%s",
        task_id,
        actor["actor_name"],
        action_key,
        resume_from,
        task["status"],
    )
    return {
        "message": "task recovery action applied",
        "task_id": task_id,
        "action": action_key,
        "from_step": resume_from,
    }


@app.post("/tasks/{task_id}/clarify")
def clarify_task(
    task_id: int,
    request: TaskClarifyRequest,
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
):
    clarification = request.clarification.strip()
    if not clarification:
        raise HTTPException(status_code=400, detail="Clarification cannot be empty")

    conn = get_conn()
    cur = conn.cursor()
    actor = require_actor_permission(cur, x_actor_name, "operate")

    cur.execute(
        """
        SELECT
            id,
            status,
            current_step,
            checkpoint_path,
            error_message,
            user_input,
            runtime_overrides,
            recovery_action_json
        FROM task_runs
        WHERE id = %s;
        """,
        (task_id,),
    )
    task = cur.fetchone()
    if not task:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Task not found")

    if task["status"] not in {"failed", "paused"}:
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Only failed or paused tasks can be clarified")

    recovery_action = parse_maybe_json(task.get("recovery_action_json")) or {}
    action_key = str(recovery_action.get("action") or "").strip()
    if action_key != "clarify":
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Task does not require clarify action")

    cur.execute(
        """
        SELECT id
        FROM approvals
        WHERE task_id = %s AND status = 'pending'
        ORDER BY id DESC;
        """,
        (task_id,),
    )
    if cur.fetchall():
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Task has pending approvals; approve or reject them first")

    runtime_overrides = parse_maybe_json(task.get("runtime_overrides")) or {}
    skill_invocation = runtime_overrides.get("skill_invocation") or {}
    skill_id = str(skill_invocation.get("skill_id") or "").strip() or None
    original_input, clarification_history = extract_task_clarification_state(
        runtime_overrides,
        fallback_user_input=str(task.get("user_input") or ""),
    )
    clarification_entry = {
        "clarification": clarification[:4000],
        "note": request.note.strip()[:400],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    new_history = [*clarification_history, clarification_entry]
    effective_runtime_overrides = dict(runtime_overrides)
    effective_runtime_overrides["clarification_state"] = {
        "original_user_input": original_input,
        "history": new_history,
    }
    new_user_input = build_clarified_user_input(original_input, new_history)
    task_intent = infer_task_intent(new_user_input, skill_id=skill_id)
    task_intent["goal_summary"] = build_task_display_user_input(new_user_input, effective_runtime_overrides)[:160]
    deliverable_spec = infer_deliverable_spec(new_user_input, task_intent)

    reset_task_for_clarification(
        cur,
        task_id=task_id,
        task=task,
        actor=actor,
        new_user_input=new_user_input,
        task_intent=task_intent,
        deliverable_spec=deliverable_spec,
        runtime_overrides=effective_runtime_overrides,
        note=request.note.strip() or "clarify task and replan",
        details={
            "clarification": clarification[:1000],
            "recovery_action": action_key,
            "clarification_count": len(new_history),
        },
    )

    conn.commit()
    cur.close()
    conn.close()

    enqueue_task(task_id)
    update_checkpoint_status(task.get("checkpoint_path"), "pending", request.note.strip() or "clarify task and replan")
    logger.info(
        "task clarified id=%s actor=%s previous_status=%s clarification=%s",
        task_id,
        actor["actor_name"],
        task["status"],
        clarification[:200],
    )
    return {
        "message": "task clarified and resumed",
        "task_id": task_id,
        "action": "clarify",
        "from_step": 1,
    }


@app.get("/tasks/{task_id}/approvals")
def list_task_approvals(task_id: int, x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
    conn = get_conn()
    cur = conn.cursor()
    require_actor_permission(cur, x_actor_name, "read")

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
