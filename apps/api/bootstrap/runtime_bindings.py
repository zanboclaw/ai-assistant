from __future__ import annotations

import os
import re
from functools import partial
from pathlib import Path

import psycopg2
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from psycopg2.extras import RealDictCursor

from apps.api.app_runtime import (
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
from apps.api.schema_runtime import ApiSchemaRuntime
from core.runtime_logging import ensure_runtime_directory

try:
    import redis
except ImportError:  # pragma: no cover
    redis = None


def build_api_runtime_bindings(
    *,
    safe_json_dumps,
    make_json_compatible,
    build_task_display_user_input,
    extract_task_clarification_state,
    strip_artifact_suffix,
    get_runtime_version_metadata,
):
    app = FastAPI(title="AI Assistant API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    db_config = {
        "host": os.environ.get("POSTGRES_HOST", "postgres"),
        "dbname": os.environ.get("POSTGRES_DB", "assistant"),
        "user": os.environ.get("POSTGRES_USER", "assistant"),
        "password": os.environ.get("POSTGRES_PASSWORD", "change_me_for_local_dev"),
    }

    api_app_dir = Path(__file__).resolve().parents[1]
    workspace_root = Path(os.environ.get("WORKSPACE_ROOT", str(api_app_dir.parent.parent))).resolve()
    log_dir = Path(os.environ.get("LOG_DIR", str(workspace_root / "logs"))).resolve()
    ensure_runtime_directory(log_dir)
    checkpoint_dir = Path(os.environ.get("CHECKPOINT_DIR", str(workspace_root / "data" / "checkpoints"))).resolve()
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    sandbox_change_root = Path(os.environ.get("SANDBOX_CHANGE_ROOT", str(api_app_dir / "stage7_sandbox"))).resolve()
    sandbox_change_root.mkdir(parents=True, exist_ok=True)
    sandbox_acceptance_scripts_root = (workspace_root / "scripts").resolve()

    sandbox_file_encoding = "utf-8"
    sandbox_file_content_limit_bytes = int(os.environ.get("SANDBOX_FILE_CONTENT_LIMIT_BYTES", "65536"))
    sandbox_file_acceptance_default_timeout_seconds = int(os.environ.get("SANDBOX_FILE_ACCEPTANCE_DEFAULT_TIMEOUT_SECONDS", "30"))
    sandbox_file_acceptance_max_timeout_seconds = int(os.environ.get("SANDBOX_FILE_ACCEPTANCE_MAX_TIMEOUT_SECONDS", "300"))
    sandbox_file_acceptance_max_env_vars = int(os.environ.get("SANDBOX_FILE_ACCEPTANCE_MAX_ENV_VARS", "16"))
    sandbox_file_acceptance_max_env_bytes = int(os.environ.get("SANDBOX_FILE_ACCEPTANCE_MAX_ENV_BYTES", "4096"))
    sandbox_file_acceptance_output_limit = int(os.environ.get("SANDBOX_FILE_ACCEPTANCE_OUTPUT_LIMIT", "4000"))
    sandbox_file_acceptance_env_key_re = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
    sandbox_file_unified_hunk_re = re.compile(
        r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? \+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@"
    )
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    auto_stage5_postrun_enabled = os.environ.get("AUTO_STAGE5_POSTRUN_ENABLED", "1").lower() in {"1", "true", "yes"}
    mainline_specialist_execution_modes = {"task_postrun_readonly_v1", "task_runtime_worker_v1"}
    mainline_specialist_tool_profiles = {"specialist-readonly", "specialist-restricted"}
    step_request_protocol_version = "stage2-v1"
    multi_agent_protocol_version = "multi-agent-v1"
    step_execution_request_fields = [
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
    enriched_step_execution_request_extra_fields = [
        "should_run",
        "skip_reason",
        "resolved_input",
        "approval_required",
        "approval_reason",
        "effective_retry_count",
        "effective_max_retries",
        "result",
    ]
    active_session_task_statuses = {
        "pending",
        "running",
        "waiting_approval",
        "waiting_clarification",
        "paused",
        "interrupt_requested",
    }

    build_logger = partial(build_logger_impl, log_dir)
    logger = build_logger()
    get_redis_client = partial(get_redis_client_impl, redis_module=redis, redis_url=redis_url, logger=logger)
    enqueue_task = partial(enqueue_task_impl, get_redis_client_fn=get_redis_client, logger=logger)
    enqueue_agent_run = partial(enqueue_agent_run_impl, get_redis_client_fn=get_redis_client, logger=logger)
    get_conn = partial(get_conn_impl, psycopg2_module=psycopg2, db_config=db_config, cursor_factory=RealDictCursor)

    api_schema_runtime = ApiSchemaRuntime(get_conn=get_conn)
    read_skill_package_from_source = partial(
        read_skill_package_from_source_impl,
        workspace_root=workspace_root,
        api_app_dir=api_app_dir,
        http_exception_cls=HTTPException,
    )
    insert_audit_log = partial(insert_audit_log_impl, safe_json_dumps=safe_json_dumps)
    record_audit_event = partial(
        record_audit_event_impl,
        get_conn_fn=get_conn,
        ensure_audit_logs_table_fn=api_schema_runtime.ensure_audit_logs_table,
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

    return {
        "app": app,
        "DB_CONFIG": db_config,
        "API_APP_DIR": api_app_dir,
        "WORKSPACE_ROOT": workspace_root,
        "LOG_DIR": log_dir,
        "CHECKPOINT_DIR": checkpoint_dir,
        "SANDBOX_CHANGE_ROOT": sandbox_change_root,
        "SANDBOX_ACCEPTANCE_SCRIPTS_ROOT": sandbox_acceptance_scripts_root,
        "SANDBOX_FILE_ENCODING": sandbox_file_encoding,
        "SANDBOX_FILE_CONTENT_LIMIT_BYTES": sandbox_file_content_limit_bytes,
        "SANDBOX_FILE_ACCEPTANCE_DEFAULT_TIMEOUT_SECONDS": sandbox_file_acceptance_default_timeout_seconds,
        "SANDBOX_FILE_ACCEPTANCE_MAX_TIMEOUT_SECONDS": sandbox_file_acceptance_max_timeout_seconds,
        "SANDBOX_FILE_ACCEPTANCE_MAX_ENV_VARS": sandbox_file_acceptance_max_env_vars,
        "SANDBOX_FILE_ACCEPTANCE_MAX_ENV_BYTES": sandbox_file_acceptance_max_env_bytes,
        "SANDBOX_FILE_ACCEPTANCE_OUTPUT_LIMIT": sandbox_file_acceptance_output_limit,
        "SANDBOX_FILE_ACCEPTANCE_ENV_KEY_RE": sandbox_file_acceptance_env_key_re,
        "SANDBOX_FILE_UNIFIED_HUNK_RE": sandbox_file_unified_hunk_re,
        "REDIS_URL": redis_url,
        "AUTO_STAGE5_POSTRUN_ENABLED": auto_stage5_postrun_enabled,
        "MAINLINE_SPECIALIST_EXECUTION_MODES": mainline_specialist_execution_modes,
        "MAINLINE_SPECIALIST_TOOL_PROFILES": mainline_specialist_tool_profiles,
        "STEP_REQUEST_PROTOCOL_VERSION": step_request_protocol_version,
        "MULTI_AGENT_PROTOCOL_VERSION": multi_agent_protocol_version,
        "STEP_EXECUTION_REQUEST_FIELDS": step_execution_request_fields,
        "ENRICHED_STEP_EXECUTION_REQUEST_EXTRA_FIELDS": enriched_step_execution_request_extra_fields,
        "ACTIVE_SESSION_TASK_STATUSES": active_session_task_statuses,
        "build_logger": build_logger,
        "logger": logger,
        "get_redis_client": get_redis_client,
        "enqueue_task": enqueue_task,
        "enqueue_agent_run": enqueue_agent_run,
        "get_conn": get_conn,
        "api_schema_runtime": api_schema_runtime,
        "ensure_change_requests_table": api_schema_runtime.ensure_change_requests_table,
        "ensure_stage56_schema_bootstrapped": api_schema_runtime.ensure_stage56_schema_bootstrapped,
        "ensure_runtime_core_schema_bootstrapped": api_schema_runtime.ensure_runtime_core_schema_bootstrapped,
        "ensure_runtime_core_tables": api_schema_runtime.ensure_runtime_core_tables,
        "ensure_audit_logs_table": api_schema_runtime.ensure_audit_logs_table,
        "ensure_trace_tables": api_schema_runtime.ensure_trace_tables,
        "ensure_skill_registry_tables": api_schema_runtime.ensure_skill_registry_tables,
        "ensure_agent_tables": api_schema_runtime.ensure_agent_tables,
        "ensure_evaluator_tables": api_schema_runtime.ensure_evaluator_tables,
        "ensure_sessions_base_table": api_schema_runtime.ensure_sessions_base_table,
        "ensure_sessions_tables": api_schema_runtime.ensure_sessions_tables,
        "_table_exists": api_schema_runtime._table_exists,
        "_column_exists": api_schema_runtime._column_exists,
        "_change_requests_schema_ready": api_schema_runtime._change_requests_schema_ready,
        "_stage56_schema_ready": api_schema_runtime._stage56_schema_ready,
        "_read_skill_package_from_source": read_skill_package_from_source,
        "insert_audit_log": insert_audit_log,
        "record_audit_event": record_audit_event,
        "parse_maybe_json": parse_maybe_json,
        "build_task_display_input_excerpt": build_task_display_input_excerpt,
        "build_task_result_excerpt": build_task_result_excerpt,
        "attach_task_display_fields": attach_task_display_fields,
        "make_json_compatible": make_json_compatible,
        "safe_json_dumps": safe_json_dumps,
        "get_runtime_version_metadata": get_runtime_version_metadata,
    }
