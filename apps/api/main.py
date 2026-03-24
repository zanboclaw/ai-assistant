from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from functools import partial
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
API_MODULE_ROOT = Path(__file__).resolve().parent
if str(API_MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(API_MODULE_ROOT))

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
from app_runtime import (
    attach_task_display_fields as attach_task_display_fields_impl,
    build_logger as build_logger_impl,
    build_task_display_input_excerpt as build_task_display_input_excerpt_impl,
    build_task_result_excerpt as build_task_result_excerpt_impl,
    enqueue_agent_run as enqueue_agent_run_impl,
    enqueue_task as enqueue_task_impl,
    get_conn as get_conn_impl,
    get_redis_client as get_redis_client_impl,
    insert_audit_log as insert_audit_log_impl,
    parse_maybe_json as parse_maybe_json_impl,
    read_skill_package_from_source as read_skill_package_from_source_impl,
    record_audit_event as record_audit_event_impl,
)
from api_sandbox_runtime import (
    apply_unified_patch_to_text as apply_unified_patch_to_text_impl,
    build_shadow_validation_runtime_overrides as build_shadow_validation_runtime_overrides_impl,
    clip_sandbox_file_acceptance_output as clip_sandbox_file_acceptance_output_impl,
    execute_sandbox_file_acceptance as execute_sandbox_file_acceptance_impl,
    fetch_sandbox_file_state as fetch_sandbox_file_state_impl,
    get_redis_monitor_stats as get_redis_monitor_stats_impl,
    normalize_change_request_payload as normalize_change_request_payload_impl,
    normalize_sandbox_file_acceptance_payload as normalize_sandbox_file_acceptance_payload_impl,
    normalize_sandbox_file_acceptance_payload_with_context as normalize_sandbox_file_acceptance_payload_with_context_impl,
    normalize_sandbox_file_payload as normalize_sandbox_file_payload_impl,
    read_workspace_source_file_snapshot as read_workspace_source_file_snapshot_impl,
    resolve_sandbox_change_path as resolve_sandbox_change_path_impl,
    resolve_workspace_acceptance_script_path as resolve_workspace_acceptance_script_path_impl,
    resolve_workspace_source_path as resolve_workspace_source_path_impl,
)
from api_change_request_runtime import (
    attach_patch_artifacts_to_change_request_draft_with_context as attach_patch_artifacts_to_change_request_draft_with_context_impl,
    attach_shadow_validation_state_to_change_request_draft_with_context as attach_shadow_validation_state_to_change_request_draft_with_context_impl,
    build_change_request_patch_artifacts_with_context as build_change_request_patch_artifacts_with_context_impl,
    create_change_request_row as create_change_request_row_impl,
    fetch_change_target_state_for_rollback_with_context as fetch_change_target_state_for_rollback_with_context_impl,
    resolve_shadow_validation_candidate_overlay_with_context as resolve_shadow_validation_candidate_overlay_with_context_impl,
    suggest_change_request_draft_from_workflow_proposal_with_context as suggest_change_request_draft_from_workflow_proposal_with_context_impl,
)
from api_route_registry import register_all_routes as register_all_routes_impl
from api_bootstrap_runtime import (
    enforce_change_gate_for_direct_update as enforce_change_gate_for_direct_update_impl,
    fetch_planner_route as fetch_planner_route_impl,
    init_db_with_context as init_db_with_context_impl,
    is_change_gate_enforced as is_change_gate_enforced_impl,
)
from api_change_apply_runtime import (
    apply_access_actor_payload as apply_access_actor_payload_impl,
    apply_access_quota_payload as apply_access_quota_payload_impl,
    apply_change_request_payload_with_context as apply_change_request_payload_with_context_impl,
    apply_model_provider_payload as apply_model_provider_payload_impl,
    apply_model_route_payload as apply_model_route_payload_impl,
    apply_risk_policy_payload as apply_risk_policy_payload_impl,
    apply_sandbox_file_payload as apply_sandbox_file_payload_impl,
    apply_tool_registry_payload as apply_tool_registry_payload_impl,
    create_and_apply_automatic_rollback_change_request as create_and_apply_automatic_rollback_change_request_impl,
    process_change_request_post_apply_with_context as process_change_request_post_apply_with_context_impl,
    update_applied_change_request_row as update_applied_change_request_row_impl,
    update_reviewed_change_request_row as update_reviewed_change_request_row_impl,
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
from task_control_runtime import (
    get_task_or_404 as get_task_or_404_impl,
    reset_task_for_clarification as reset_task_for_clarification_impl,
    reset_task_for_resume as reset_task_for_resume_impl,
    resolve_resume_from_step as resolve_resume_from_step_impl,
    update_checkpoint_status as update_checkpoint_status_impl,
)
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
from api_shadow_validation_runtime import (
    build_change_request_shadow_validation_state_with_context as build_change_request_shadow_validation_state_with_context_impl,
    build_shadow_validation_execution_payload_with_context as build_shadow_validation_execution_payload_with_context_impl,
    fetch_shadow_task_and_evaluator_with_context as fetch_shadow_task_and_evaluator_with_context_impl,
    build_workflow_proposal_shadow_validation_status_with_context as build_workflow_proposal_shadow_validation_status_with_context_impl,
    fetch_latest_workflow_proposal_shadow_validation_with_context as fetch_latest_workflow_proposal_shadow_validation_with_context_impl,
    fetch_task_run_brief_with_context as fetch_task_run_brief_with_context_impl,
    finalize_shadow_validation_response_with_context as finalize_shadow_validation_response_with_context_impl,
    record_shadow_validation_result_with_context as record_shadow_validation_result_with_context_impl,
    fetch_workflow_proposal_shadow_validation_history_with_context as fetch_workflow_proposal_shadow_validation_history_with_context_impl,
    serialize_shadow_validation_audit_row_with_context as serialize_shadow_validation_audit_row_with_context_impl,
    start_shadow_validation_completion_worker as start_shadow_validation_completion_worker_impl,
    sync_change_requests_shadow_validation_with_context as sync_change_requests_shadow_validation_with_context_impl,
    wait_for_shadow_validation_completion_with_context as wait_for_shadow_validation_completion_with_context_impl,
)
from schema_runtime import ApiSchemaRuntime
from task_intent_helpers import infer_deliverable_spec, infer_task_intent
from monitor_overview_store import fetch_monitor_overview_snapshot
from monitor_routes import register_monitor_routes
from monitor_stage_metrics_store import fetch_stage56_overview_metrics
from monitor_stage7_store import fetch_stage7_overview_metrics
from multi_agent_demo_routes import register_multi_agent_demo_routes
from api_multi_agent_runtime import (
    build_demo_review_criteria as build_demo_review_criteria_impl,
    build_specialist_draft_payload as build_specialist_draft_payload_impl,
    build_specialist_execution_request as build_specialist_execution_request_impl,
    build_specialist_step_partitions as build_specialist_step_partitions_impl,
    build_task_agent_summary_payload as build_task_agent_summary_payload_impl,
    build_workflow_proposal as build_workflow_proposal_impl,
    create_agent_artifact as create_agent_artifact_impl,
    create_agent_message as create_agent_message_impl,
    create_agent_run as create_agent_run_impl,
    create_evaluator_run as create_evaluator_run_impl,
    derive_evaluator_failure_profile as derive_evaluator_failure_profile_impl,
    fetch_latest_evaluator_for_task as fetch_latest_evaluator_for_task_impl,
    fetch_task_agent_summary as fetch_task_agent_summary_impl,
    list_workflow_proposals_rows as list_workflow_proposals_rows_impl,
    resolve_reviewer_decision as resolve_reviewer_decision_impl,
)
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

build_logger = partial(build_logger_impl, LOG_DIR)


logger = build_logger()


get_redis_client = partial(get_redis_client_impl, redis_module=redis, redis_url=REDIS_URL, logger=logger)
enqueue_task = partial(enqueue_task_impl, get_redis_client_fn=get_redis_client, logger=logger)
enqueue_agent_run = partial(enqueue_agent_run_impl, get_redis_client_fn=get_redis_client, logger=logger)
get_conn = partial(get_conn_impl, psycopg2_module=psycopg2, db_config=DB_CONFIG, cursor_factory=RealDictCursor)


api_schema_runtime = ApiSchemaRuntime(get_conn=get_conn)
_table_exists = api_schema_runtime._table_exists
_column_exists = api_schema_runtime._column_exists
_change_requests_schema_ready = api_schema_runtime._change_requests_schema_ready
_stage56_schema_ready = api_schema_runtime._stage56_schema_ready
ensure_change_requests_table = api_schema_runtime.ensure_change_requests_table
ensure_stage56_schema_bootstrapped = api_schema_runtime.ensure_stage56_schema_bootstrapped
ensure_runtime_core_schema_bootstrapped = api_schema_runtime.ensure_runtime_core_schema_bootstrapped
ensure_runtime_core_tables = api_schema_runtime.ensure_runtime_core_tables
ensure_audit_logs_table = api_schema_runtime.ensure_audit_logs_table
ensure_trace_tables = api_schema_runtime.ensure_trace_tables
ensure_skill_registry_tables = api_schema_runtime.ensure_skill_registry_tables
ensure_agent_tables = api_schema_runtime.ensure_agent_tables
ensure_evaluator_tables = api_schema_runtime.ensure_evaluator_tables
_read_skill_package_from_source = partial(
    read_skill_package_from_source_impl,
    workspace_root=WORKSPACE_ROOT,
    api_app_dir=API_APP_DIR,
    http_exception_cls=HTTPException,
)
insert_audit_log = partial(insert_audit_log_impl, safe_json_dumps=safe_json_dumps)
record_audit_event = partial(
    record_audit_event_impl,
    get_conn_fn=get_conn,
    ensure_audit_logs_table_fn=ensure_audit_logs_table,
    insert_audit_log_fn=insert_audit_log,
)
parse_maybe_json = parse_maybe_json_impl
build_task_display_input_excerpt = partial(
    build_task_display_input_excerpt_impl,
    build_task_display_user_input=build_task_display_user_input,
    parse_maybe_json_fn=parse_maybe_json,
)
build_task_result_excerpt = partial(build_task_result_excerpt_impl, strip_artifact_suffix=strip_artifact_suffix)
attach_task_display_fields = partial(
    attach_task_display_fields_impl,
    parse_maybe_json_fn=parse_maybe_json,
    extract_task_clarification_state=extract_task_clarification_state,
    build_task_display_user_input=build_task_display_user_input,
    build_task_result_excerpt_fn=build_task_result_excerpt,
)


build_shadow_validation_runtime_overrides = partial(
    build_shadow_validation_runtime_overrides_impl,
    make_json_compatible_fn=make_json_compatible,
)


SUPPORTED_CHANGE_TARGET_TYPES = {
    "risk_policy",
    "tool_registry",
    "model_route",
    "model_provider",
    "access_quota",
    "access_actor",
    "sandbox_file",
}
resolve_sandbox_change_path = partial(
    resolve_sandbox_change_path_impl,
    sandbox_change_root=SANDBOX_CHANGE_ROOT,
    http_exception_cls=HTTPException,
)
resolve_workspace_source_path = partial(
    resolve_workspace_source_path_impl,
    workspace_root=WORKSPACE_ROOT,
    sandbox_change_root=SANDBOX_CHANGE_ROOT,
    http_exception_cls=HTTPException,
)
read_workspace_source_file_snapshot = partial(
    read_workspace_source_file_snapshot_impl,
    resolve_workspace_source_path_fn=resolve_workspace_source_path,
    workspace_root=WORKSPACE_ROOT,
    file_encoding=SANDBOX_FILE_ENCODING,
    content_limit_bytes=SANDBOX_FILE_CONTENT_LIMIT_BYTES,
    http_exception_cls=HTTPException,
)
resolve_workspace_acceptance_script_path = partial(
    resolve_workspace_acceptance_script_path_impl,
    workspace_root=WORKSPACE_ROOT,
    scripts_root=SANDBOX_ACCEPTANCE_SCRIPTS_ROOT,
    http_exception_cls=HTTPException,
)

normalize_sandbox_file_acceptance_payload = partial(
    normalize_sandbox_file_acceptance_payload_with_context_impl,
    normalize_sandbox_file_acceptance_payload_fn=partial(
        normalize_sandbox_file_acceptance_payload_impl,
        resolve_workspace_acceptance_script_path_fn=resolve_workspace_acceptance_script_path,
        file_encoding=SANDBOX_FILE_ENCODING,
        default_timeout_seconds=SANDBOX_FILE_ACCEPTANCE_DEFAULT_TIMEOUT_SECONDS,
        max_timeout_seconds=SANDBOX_FILE_ACCEPTANCE_MAX_TIMEOUT_SECONDS,
        max_env_vars=SANDBOX_FILE_ACCEPTANCE_MAX_ENV_VARS,
        max_env_bytes=SANDBOX_FILE_ACCEPTANCE_MAX_ENV_BYTES,
        env_key_re=SANDBOX_FILE_ACCEPTANCE_ENV_KEY_RE,
        http_exception_cls=HTTPException,
    ),
    workspace_root=WORKSPACE_ROOT,
)


clip_sandbox_file_acceptance_output = partial(
    clip_sandbox_file_acceptance_output_impl,
    output_limit=SANDBOX_FILE_ACCEPTANCE_OUTPUT_LIMIT,
)
execute_sandbox_file_acceptance = partial(
    execute_sandbox_file_acceptance_impl,
    resolve_workspace_acceptance_script_path_fn=resolve_workspace_acceptance_script_path,
    resolve_sandbox_change_path_fn=resolve_sandbox_change_path,
    clip_sandbox_file_acceptance_output_fn=clip_sandbox_file_acceptance_output,
    workspace_root=WORKSPACE_ROOT,
    sandbox_change_root=SANDBOX_CHANGE_ROOT,
    default_timeout_seconds=SANDBOX_FILE_ACCEPTANCE_DEFAULT_TIMEOUT_SECONDS,
    logger=logger,
)
apply_unified_patch_to_text = partial(
    apply_unified_patch_to_text_impl,
    unified_hunk_re=SANDBOX_FILE_UNIFIED_HUNK_RE,
    http_exception_cls=HTTPException,
)
normalize_sandbox_file_payload = partial(
    normalize_sandbox_file_payload_impl,
    file_encoding=SANDBOX_FILE_ENCODING,
    content_limit_bytes=SANDBOX_FILE_CONTENT_LIMIT_BYTES,
    normalize_sandbox_file_acceptance_payload_fn=normalize_sandbox_file_acceptance_payload,
    read_workspace_source_file_snapshot_fn=read_workspace_source_file_snapshot,
    apply_unified_patch_to_text_fn=apply_unified_patch_to_text,
    http_exception_cls=HTTPException,
)
normalize_change_request_payload = partial(
    normalize_change_request_payload_impl,
    normalize_sandbox_file_payload_fn=normalize_sandbox_file_payload,
    make_json_compatible_fn=make_json_compatible,
    http_exception_cls=HTTPException,
)
fetch_sandbox_file_state = partial(
    fetch_sandbox_file_state_impl,
    resolve_sandbox_change_path_fn=resolve_sandbox_change_path,
    file_encoding=SANDBOX_FILE_ENCODING,
    content_limit_bytes=SANDBOX_FILE_CONTENT_LIMIT_BYTES,
    http_exception_cls=HTTPException,
)

serialize_shadow_validation_audit_row_with_context = partial(
    serialize_shadow_validation_audit_row_with_context_impl,
    serialize_shadow_validation_audit_row_fn=serialize_shadow_validation_audit_row,
    make_json_compatible_fn=make_json_compatible,
    parse_maybe_json_fn=parse_maybe_json,
    parse_optional_int_fn=parse_optional_int,
)
fetch_workflow_proposal_shadow_validation_history_with_context = partial(
    fetch_workflow_proposal_shadow_validation_history_with_context_impl,
    fetch_workflow_proposal_shadow_validation_history_fn=fetch_workflow_proposal_shadow_validation_history,
    ensure_audit_logs_table_fn=ensure_audit_logs_table,
    request_event=WORKFLOW_PROPOSAL_SHADOW_VALIDATION_REQUEST_EVENT,
    result_event=WORKFLOW_PROPOSAL_SHADOW_VALIDATION_RESULT_EVENT,
    serialize_shadow_validation_audit_row_with_context_fn=serialize_shadow_validation_audit_row_with_context,
)
fetch_task_run_brief_with_context = partial(
    fetch_task_run_brief_with_context_impl,
    fetch_task_run_brief_fn=fetch_task_run_brief,
    parse_optional_int_fn=parse_optional_int,
    parse_maybe_json_fn=parse_maybe_json,
)
fetch_latest_workflow_proposal_shadow_validation_with_context = partial(
    fetch_latest_workflow_proposal_shadow_validation_with_context_impl,
    fetch_latest_workflow_proposal_shadow_validation_fn=fetch_latest_workflow_proposal_shadow_validation,
    fetch_workflow_proposal_shadow_validation_history_with_context_fn=fetch_workflow_proposal_shadow_validation_history_with_context,
    shadow_validation_candidate_matches_fn=shadow_validation_candidate_matches,
    result_event=WORKFLOW_PROPOSAL_SHADOW_VALIDATION_RESULT_EVENT,
)
build_workflow_proposal_shadow_validation_status_with_context = partial(
    build_workflow_proposal_shadow_validation_status_with_context_impl,
    build_workflow_proposal_shadow_validation_status_fn=build_workflow_proposal_shadow_validation_status,
    fetch_workflow_proposal_shadow_validation_history_with_context_fn=fetch_workflow_proposal_shadow_validation_history_with_context,
    fetch_task_run_brief_with_context_fn=fetch_task_run_brief_with_context,
    parse_optional_int_fn=parse_optional_int,
    request_event=WORKFLOW_PROPOSAL_SHADOW_VALIDATION_REQUEST_EVENT,
    result_event=WORKFLOW_PROPOSAL_SHADOW_VALIDATION_RESULT_EVENT,
)
build_change_request_shadow_validation_state_with_context = partial(
    build_change_request_shadow_validation_state_with_context_impl,
    build_change_request_shadow_validation_state_fn=build_change_request_shadow_validation_state,
    normalize_change_request_proposal_kind_fn=normalize_change_request_proposal_kind,
    change_request_requires_shadow_validation_fn=change_request_requires_shadow_validation,
    fetch_latest_workflow_proposal_shadow_validation_with_context_fn=fetch_latest_workflow_proposal_shadow_validation_with_context,
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
sync_change_requests_shadow_validation_with_context = partial(
    sync_change_requests_shadow_validation_with_context_impl,
    sync_change_requests_shadow_validation_fn=sync_change_requests_shadow_validation,
    ensure_change_requests_table_fn=ensure_change_requests_table,
    parse_maybe_json_fn=parse_maybe_json,
    parse_optional_int_fn=parse_optional_int,
    build_change_request_shadow_validation_state_with_context_fn=build_change_request_shadow_validation_state_with_context,
    safe_json_dumps_fn=safe_json_dumps,
)
create_change_request_row = partial(
    create_change_request_row_impl,
    ensure_change_requests_table_fn=ensure_change_requests_table,
    normalize_change_request_proposal_kind_fn=normalize_change_request_proposal_kind,
    build_change_request_create_payload_fn=build_change_request_create_payload,
    normalize_change_request_payload_fn=normalize_change_request_payload,
    build_change_request_patch_artifacts_with_context_fn=lambda cur, **kwargs: build_change_request_patch_artifacts_with_context(cur, **kwargs),
    build_change_request_shadow_validation_state_with_context_fn=lambda cur, **kwargs: build_change_request_shadow_validation_state_with_context(cur, **kwargs),
    insert_change_request_row_fn=insert_change_request_row,
    safe_json_dumps_fn=safe_json_dumps,
)
fetch_change_target_state_for_rollback_with_context = partial(
    fetch_change_target_state_for_rollback_with_context_impl,
    fetch_change_target_state_for_rollback_fn=fetch_change_target_state_for_rollback,
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
build_change_request_patch_artifacts_with_context = partial(
    build_change_request_patch_artifacts_with_context_impl,
    build_change_request_patch_artifacts_fn=build_change_request_patch_artifacts,
    normalize_change_request_payload_fn=normalize_change_request_payload,
    fetch_change_target_state_for_rollback_with_context_fn=lambda cur, **kwargs: fetch_change_target_state_for_rollback_with_context(cur, **kwargs),
    compute_change_payload_patch_fn=compute_change_payload_patch,
)
attach_patch_artifacts_to_change_request_draft_with_context = partial(
    attach_patch_artifacts_to_change_request_draft_with_context_impl,
    attach_patch_artifacts_to_change_request_draft_fn=attach_patch_artifacts_to_change_request_draft,
    normalize_change_request_payload_fn=normalize_change_request_payload,
    build_change_request_patch_artifacts_with_context_fn=lambda cur, **kwargs: build_change_request_patch_artifacts_with_context(cur, **kwargs),
)
attach_shadow_validation_state_to_change_request_draft_with_context = partial(
    attach_shadow_validation_state_to_change_request_draft_with_context_impl,
    attach_shadow_validation_state_to_change_request_draft_fn=attach_shadow_validation_state_to_change_request_draft,
    normalize_change_request_payload_fn=normalize_change_request_payload,
    change_request_requires_shadow_validation_fn=change_request_requires_shadow_validation,
    build_change_request_shadow_validation_state_with_context_fn=lambda cur, **kwargs: build_change_request_shadow_validation_state_with_context(cur, **kwargs),
)


is_change_gate_enforced = partial(
    is_change_gate_enforced_impl,
    default_enforced_change_target_types=DEFAULT_ENFORCED_CHANGE_TARGET_TYPES,
)
enforce_change_gate_for_direct_update = partial(
    enforce_change_gate_for_direct_update_impl,
    is_change_gate_enforced_fn=is_change_gate_enforced,
    http_exception_cls=HTTPException,
)


_apply_sandbox_file_payload = partial(
    apply_sandbox_file_payload_impl,
    resolve_sandbox_change_path_fn=resolve_sandbox_change_path,
    file_encoding=SANDBOX_FILE_ENCODING,
    http_exception_cls=HTTPException,
)
_apply_risk_policy_payload = partial(
    apply_risk_policy_payload_impl,
    seed_default_risk_policies_fn=seed_default_risk_policies,
    risk_policy_map=RISK_POLICY_MAP,
    safe_json_dumps_fn=safe_json_dumps,
    http_exception_cls=HTTPException,
)
_apply_tool_registry_payload = partial(
    apply_tool_registry_payload_impl,
    seed_default_tool_registry_fn=seed_default_tool_registry,
    safe_json_dumps_fn=safe_json_dumps,
    http_exception_cls=HTTPException,
)
_apply_model_route_payload = partial(
    apply_model_route_payload_impl,
    seed_default_model_providers_fn=seed_default_model_providers,
    seed_default_model_routes_fn=seed_default_model_routes,
    http_exception_cls=HTTPException,
)
_apply_model_provider_payload = partial(
    apply_model_provider_payload_impl,
    seed_default_model_providers_fn=seed_default_model_providers,
    http_exception_cls=HTTPException,
)
_apply_access_quota_payload = partial(
    apply_access_quota_payload_impl,
    seed_default_access_quotas_fn=seed_default_access_quotas,
    http_exception_cls=HTTPException,
)
_apply_access_actor_payload = partial(
    apply_access_actor_payload_impl,
    seed_default_access_actors_fn=seed_default_access_actors,
    access_role_permissions=ACCESS_ROLE_PERMISSIONS,
    safe_json_dumps_fn=safe_json_dumps,
    upsert_default_access_quota_fn=upsert_default_access_quota,
    http_exception_cls=HTTPException,
)
apply_change_request_payload_with_context = partial(
    apply_change_request_payload_with_context_impl,
    apply_change_request_payload_fn=apply_change_request_payload,
    normalize_sandbox_file_payload_fn=normalize_sandbox_file_payload,
    apply_sandbox_file_payload_fn=_apply_sandbox_file_payload,
    apply_risk_policy_payload_fn=_apply_risk_policy_payload,
    apply_tool_registry_payload_fn=_apply_tool_registry_payload,
    apply_model_route_payload_fn=_apply_model_route_payload,
    apply_model_provider_payload_fn=_apply_model_provider_payload,
    apply_access_quota_payload_fn=_apply_access_quota_payload,
    apply_access_actor_payload_fn=_apply_access_actor_payload,
)
create_and_apply_automatic_rollback_change_request = partial(
    create_and_apply_automatic_rollback_change_request_impl,
    build_change_request_rollback_draft_fn=build_change_request_rollback_draft,
    create_change_request_row_fn=create_change_request_row,
    serialize_change_request_row_fn=serialize_change_request_row,
    insert_audit_log_fn=insert_audit_log,
    fetch_change_target_state_for_rollback_with_context_fn=lambda cur, **kwargs: fetch_change_target_state_for_rollback_with_context(cur, **kwargs),
    apply_change_request_payload_with_context_fn=apply_change_request_payload_with_context,
    safe_json_dumps_fn=safe_json_dumps,
    change_request_select_fields=CHANGE_REQUEST_SELECT_FIELDS,
    http_exception_cls=HTTPException,
)
get_redis_monitor_stats = partial(get_redis_monitor_stats_impl, get_redis_client_fn=get_redis_client)
suggest_change_request_draft_from_workflow_proposal_with_context = partial(
    suggest_change_request_draft_from_workflow_proposal_with_context_impl,
    suggest_change_request_draft_from_workflow_proposal_fn=suggest_change_request_draft_from_workflow_proposal,
    supported_change_target_types=list(SUPPORTED_CHANGE_TARGET_TYPES),
    fetch_planner_route_fn=lambda cur=None: fetch_planner_route_impl(
        cur,
        seed_default_model_providers_fn=seed_default_model_providers,
        seed_default_model_routes_fn=seed_default_model_routes,
    ),
    serialize_model_route_row_fn=serialize_model_route_row,
    build_change_request_draft_from_workflow_proposal_fn=build_change_request_draft_from_workflow_proposal,
)
resolve_shadow_validation_candidate_overlay_with_context = partial(
    resolve_shadow_validation_candidate_overlay_with_context_impl,
    resolve_shadow_validation_candidate_overlay_fn=resolve_shadow_validation_candidate_overlay,
    build_shadow_validation_candidate_overlay_fn=build_shadow_validation_candidate_overlay,
    parse_optional_int_fn=parse_optional_int,
    build_change_request_patch_artifacts_with_context_fn=lambda cur, **kwargs: build_change_request_patch_artifacts_with_context(cur, **kwargs),
    suggest_change_request_draft_from_workflow_proposal_with_context_fn=lambda cur, **kwargs: (
        suggest_change_request_draft_from_workflow_proposal_with_context(cur, **kwargs)
    ),
    attach_patch_artifacts_to_change_request_draft_with_context_fn=lambda cur, draft: (
        attach_patch_artifacts_to_change_request_draft_with_context(cur, draft)
    ),
)
_fetch_shadow_task_and_evaluator = lambda shadow_task_id: fetch_shadow_task_and_evaluator_with_context_impl(
    shadow_task_id,
    get_conn_fn=get_conn,
    fetch_latest_evaluator_for_task_fn=fetch_latest_evaluator_for_task,
)
_record_shadow_validation_result = partial(
    record_shadow_validation_result_with_context_impl,
    get_conn_fn=get_conn,
    insert_audit_log_fn=insert_audit_log,
    sync_change_requests_shadow_validation_with_context_fn=sync_change_requests_shadow_validation_with_context,
)
wait_for_shadow_validation_completion_with_context = partial(
    wait_for_shadow_validation_completion_with_context_impl,
    wait_for_shadow_validation_completion_fn=wait_for_shadow_validation_completion,
    fetch_shadow_task_and_evaluator_with_context_fn=_fetch_shadow_task_and_evaluator,
    build_shadow_validation_result_fn=build_shadow_validation_result,
    record_shadow_validation_result_with_context_fn=_record_shadow_validation_result,
)
start_shadow_validation_completion_worker = partial(
    start_shadow_validation_completion_worker_impl,
    wait_for_shadow_validation_completion_with_context_fn=wait_for_shadow_validation_completion_with_context,
    thread_cls=threading.Thread,
    logger=logger,
)


create_agent_artifact = partial(create_agent_artifact_impl, safe_json_dumps=safe_json_dumps)
create_evaluator_run = partial(
    create_evaluator_run_impl,
    ensure_evaluator_tables=ensure_evaluator_tables,
    safe_json_dumps=safe_json_dumps,
)
fetch_latest_evaluator_for_task = partial(
    fetch_latest_evaluator_for_task_impl,
    ensure_evaluator_tables=ensure_evaluator_tables,
    serialize_evaluator_run_row=serialize_evaluator_run_row,
)
list_workflow_proposals_rows = partial(
    list_workflow_proposals_rows_impl,
    ensure_evaluator_tables=ensure_evaluator_tables,
    serialize_evaluator_run_row=serialize_evaluator_run_row,
    serialize_workflow_proposal=serialize_workflow_proposal,
)
create_agent_message = partial(create_agent_message_impl, safe_json_dumps=safe_json_dumps)
create_agent_run = partial(create_agent_run_impl, safe_json_dumps=safe_json_dumps)
build_task_agent_summary_payload = partial(
    build_task_agent_summary_payload_impl,
    serialize_agent_run_row=serialize_agent_run_row,
    multi_agent_protocol_version=MULTI_AGENT_PROTOCOL_VERSION,
    mainline_specialist_execution_modes=MAINLINE_SPECIALIST_EXECUTION_MODES,
)
fetch_task_agent_summary = partial(
    fetch_task_agent_summary_impl,
    serialize_agent_run_row=serialize_agent_run_row,
    serialize_agent_artifact_row=serialize_agent_artifact_row,
    fetch_latest_evaluator_for_task_fn=fetch_latest_evaluator_for_task,
    build_task_agent_summary_payload_fn=build_task_agent_summary_payload,
    parse_maybe_json=parse_maybe_json,
)
build_demo_review_criteria = build_demo_review_criteria_impl
derive_evaluator_failure_profile = derive_evaluator_failure_profile_impl
build_workflow_proposal = build_workflow_proposal_impl
resolve_reviewer_decision = resolve_reviewer_decision_impl
build_specialist_execution_request = build_specialist_execution_request_impl
build_specialist_step_partitions = partial(
    build_specialist_step_partitions_impl,
    build_task_display_input_excerpt=build_task_display_input_excerpt,
    build_task_result_excerpt=build_task_result_excerpt,
)
build_specialist_draft_payload = partial(
    build_specialist_draft_payload_impl,
    multi_agent_protocol_version=MULTI_AGENT_PROTOCOL_VERSION,
)
ensure_sessions_base_table = api_schema_runtime.ensure_sessions_base_table
ensure_sessions_tables = api_schema_runtime.ensure_sessions_tables


@app.get("/")
def root():
    return {"message": "ai assistant api is running"}


@app.post("/init-db")
def init_db(x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")):
    return init_db_with_context_impl(
        x_actor_name,
        get_conn_fn=get_conn,
        require_actor_permission_fn=require_actor_permission,
        ensure_runtime_core_tables_fn=ensure_runtime_core_tables,
        seed_default_risk_policies_fn=seed_default_risk_policies,
        ensure_audit_logs_table_fn=ensure_audit_logs_table,
        seed_default_access_actors_fn=seed_default_access_actors,
        seed_default_access_quotas_fn=seed_default_access_quotas,
        seed_default_tool_registry_fn=seed_default_tool_registry,
        seed_default_model_providers_fn=seed_default_model_providers,
        seed_default_model_routes_fn=seed_default_model_routes,
        ensure_change_requests_table_fn=ensure_change_requests_table,
        ensure_agent_tables_fn=ensure_agent_tables,
        logger=logger,
    )


process_change_request_post_apply_with_context = partial(
    process_change_request_post_apply_with_context_impl,
    process_change_request_post_apply_fn=process_change_request_post_apply,
    execute_sandbox_file_acceptance_fn=execute_sandbox_file_acceptance,
    make_json_compatible_fn=make_json_compatible,
    insert_audit_log_fn=insert_audit_log,
    create_and_apply_automatic_rollback_change_request_fn=create_and_apply_automatic_rollback_change_request,
)
_update_reviewed_change_request_row = partial(
    update_reviewed_change_request_row_impl,
    change_request_select_fields=CHANGE_REQUEST_SELECT_FIELDS,
)
_update_applied_change_request_row = partial(
    update_applied_change_request_row_impl,
    safe_json_dumps_fn=safe_json_dumps,
    change_request_select_fields=CHANGE_REQUEST_SELECT_FIELDS,
)
build_shadow_validation_execution_payload_with_context = partial(
    build_shadow_validation_execution_payload_with_context_impl,
    build_shadow_validation_execution_payload_fn=build_shadow_validation_execution_payload,
    parse_optional_int_fn=parse_optional_int,
    make_json_compatible_fn=make_json_compatible,
)
finalize_shadow_validation_response_with_context = partial(
    finalize_shadow_validation_response_with_context_impl,
    finalize_shadow_validation_response_fn=finalize_shadow_validation_response,
    make_json_compatible_fn=make_json_compatible,
    wait_for_shadow_validation_completion_with_context_fn=wait_for_shadow_validation_completion_with_context,
    start_shadow_validation_completion_worker_fn=start_shadow_validation_completion_worker,
)


register_all_routes = partial(register_all_routes_impl, app=app, context=globals())


get_task_or_404 = partial(get_task_or_404_impl, http_exception_cls=HTTPException)
update_checkpoint_status = update_checkpoint_status_impl
resolve_resume_from_step = resolve_resume_from_step_impl
reset_task_for_resume = partial(reset_task_for_resume_impl, insert_audit_log_fn=insert_audit_log)
reset_task_for_clarification = partial(
    reset_task_for_clarification_impl,
    json_wrapper=Json,
    make_json_compatible=make_json_compatible,
    insert_audit_log_fn=insert_audit_log,
)


register_all_routes()
