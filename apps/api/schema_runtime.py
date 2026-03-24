from __future__ import annotations

import threading
from typing import Any


class ApiSchemaRuntime:
    def __init__(self, *, get_conn):
        self._get_conn = get_conn
        self._stage56_schema_bootstrap_lock = threading.Lock()
        self._stage56_schema_bootstrap_active = False
        self._stage56_schema_bootstrapped = False
        self._runtime_core_schema_bootstrap_lock = threading.Lock()
        self._runtime_core_schema_bootstrap_active = False
        self._runtime_core_schema_bootstrapped = False
        self._change_requests_schema_bootstrap_lock = threading.Lock()
        self._change_requests_schema_bootstrapped = False

    def _table_exists(self, cur, table_name: str) -> bool:
        cur.execute("SELECT to_regclass(%s) AS regclass;", (f"public.{table_name}",))
        return bool(cur.fetchone()["regclass"])

    def _column_exists(self, cur, table_name: str, column_name: str) -> bool:
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

    def _change_requests_schema_ready(self, cur) -> bool:
        if not self._table_exists(cur, "change_requests"):
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
        return all(self._column_exists(cur, "change_requests", column_name) for column_name in required_columns)

    def _stage56_schema_ready(self, cur) -> bool:
        required_tables = ("agent_runs", "agent_messages", "agent_artifacts", "evaluator_runs")
        if not all(self._table_exists(cur, table_name) for table_name in required_tables):
            return False
        required_agent_run_columns = (
            "execution_mode",
            "execution_request_json",
            "source_task_run_id",
            "assigned_step_orders_json",
        )
        if not all(self._column_exists(cur, "agent_runs", column_name) for column_name in required_agent_run_columns):
            return False
        required_evaluator_columns = ("failure_reason", "failure_stage", "proposal_json")
        return all(self._column_exists(cur, "evaluator_runs", column_name) for column_name in required_evaluator_columns)

    def ensure_change_requests_table(self, cur):
        if self._change_requests_schema_bootstrapped:
            return

        if self._change_requests_schema_ready(cur):
            self._change_requests_schema_bootstrapped = True
            return

        with self._change_requests_schema_bootstrap_lock:
            if self._change_requests_schema_bootstrapped:
                return
            if self._change_requests_schema_ready(cur):
                self._change_requests_schema_bootstrapped = True
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
            self._change_requests_schema_bootstrapped = True

    def ensure_stage56_schema_bootstrapped(self):
        if self._stage56_schema_bootstrapped:
            return

        with self._stage56_schema_bootstrap_lock:
            if self._stage56_schema_bootstrapped:
                return

            conn = self._get_conn()
            cur = conn.cursor()
            self._stage56_schema_bootstrap_active = True
            try:
                if self._stage56_schema_ready(cur):
                    self._stage56_schema_bootstrapped = True
                    conn.commit()
                    return
                self.ensure_audit_logs_table(cur)
                self.ensure_agent_tables(cur)
                self.ensure_evaluator_tables(cur)
                conn.commit()
                self._stage56_schema_bootstrapped = True
            finally:
                self._stage56_schema_bootstrap_active = False
                cur.close()
                conn.close()

    def ensure_runtime_core_schema_bootstrapped(self):
        if self._runtime_core_schema_bootstrapped:
            return

        with self._runtime_core_schema_bootstrap_lock:
            if self._runtime_core_schema_bootstrapped:
                return

            conn = self._get_conn()
            cur = conn.cursor()
            self._runtime_core_schema_bootstrap_active = True
            try:
                cur.execute("SELECT pg_advisory_xact_lock(hashtext('runtime_core_schema_bootstrap'));")
                self.ensure_runtime_core_tables(cur)
                conn.commit()
                self._runtime_core_schema_bootstrapped = True
            finally:
                self._runtime_core_schema_bootstrap_active = False
                cur.close()
                conn.close()

    def ensure_runtime_core_tables(self, cur):
        if not self._runtime_core_schema_bootstrap_active:
            self.ensure_runtime_core_schema_bootstrapped()
            return

        self.ensure_sessions_base_table(cur)

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

        self.ensure_sessions_tables(cur)

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
        self.ensure_trace_tables(cur)

    def ensure_audit_logs_table(self, cur):
        if not self._stage56_schema_bootstrap_active:
            self.ensure_stage56_schema_bootstrapped()
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

    def ensure_trace_tables(self, cur):
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

    def ensure_skill_registry_tables(self, cur):
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

    def ensure_agent_tables(self, cur):
        if self._stage56_schema_bootstrapped:
            return
        if self._stage56_schema_ready(cur):
            self._stage56_schema_bootstrapped = True
            return
        if not self._stage56_schema_bootstrap_active:
            self.ensure_stage56_schema_bootstrapped()
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
        self._stage56_schema_bootstrapped = self._stage56_schema_ready(cur)

    def ensure_evaluator_tables(self, cur):
        if self._stage56_schema_bootstrapped:
            return
        if self._stage56_schema_ready(cur):
            self._stage56_schema_bootstrapped = True
            return
        if not self._stage56_schema_bootstrap_active:
            self.ensure_stage56_schema_bootstrapped()
            return
        self.ensure_agent_tables(cur)
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
        self._stage56_schema_bootstrapped = self._stage56_schema_ready(cur)

    def ensure_sessions_base_table(self, cur):
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

    def ensure_sessions_tables(self, cur):
        self.ensure_sessions_base_table(cur)

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

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS session_reviews (
                id SERIAL PRIMARY KEY,
                session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                review_kind VARCHAR(100) NOT NULL DEFAULT 'manual',
                summary_text TEXT NOT NULL,
                highlights JSONB NOT NULL DEFAULT '[]'::jsonb,
                open_loops JSONB NOT NULL DEFAULT '[]'::jsonb,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
