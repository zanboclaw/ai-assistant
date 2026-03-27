CREATE TABLE IF NOT EXISTS sessions (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS name VARCHAR(255) NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT '';

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'sessions'
          AND column_name = 'title'
    ) THEN
        UPDATE sessions
        SET name = COALESCE(NULLIF(name, ''), NULLIF(title, ''), CONCAT('session-', id::text))
        WHERE name IS NULL OR name = '';
    ELSE
        UPDATE sessions
        SET name = COALESCE(NULLIF(name, ''), CONCAT('session-', id::text))
        WHERE name IS NULL OR name = '';
    END IF;
END $$;

UPDATE sessions
SET description = COALESCE(description, '')
WHERE description IS NULL;

CREATE TABLE IF NOT EXISTS task_runs (
    id SERIAL PRIMARY KEY,
    user_input TEXT NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    result TEXT,
    error_message TEXT,
    current_step INTEGER,
    checkpoint_path TEXT,
    session_id INTEGER REFERENCES sessions(id) ON DELETE SET NULL,
    created_by_actor TEXT,
    runtime_overrides JSONB,
    task_intent_json JSONB,
    deliverable_spec_json JSONB,
    validation_report_json JSONB,
    recovery_action_json JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE task_runs
    ADD COLUMN IF NOT EXISTS result TEXT,
    ADD COLUMN IF NOT EXISTS error_message TEXT,
    ADD COLUMN IF NOT EXISTS current_step INTEGER,
    ADD COLUMN IF NOT EXISTS checkpoint_path TEXT,
    ADD COLUMN IF NOT EXISTS session_id INTEGER REFERENCES sessions(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS created_by_actor TEXT,
    ADD COLUMN IF NOT EXISTS runtime_overrides JSONB,
    ADD COLUMN IF NOT EXISTS task_intent_json JSONB,
    ADD COLUMN IF NOT EXISTS deliverable_spec_json JSONB,
    ADD COLUMN IF NOT EXISTS validation_report_json JSONB,
    ADD COLUMN IF NOT EXISTS recovery_action_json JSONB,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;

DO $$
BEGIN
    IF to_regclass('public.tasks') IS NOT NULL THEN
        INSERT INTO task_runs (
            id,
            user_input,
            status,
            result,
            session_id,
            runtime_overrides,
            task_intent_json,
            deliverable_spec_json,
            validation_report_json,
            recovery_action_json,
            created_at,
            updated_at
        )
        SELECT
            t.id,
            t.user_input,
            t.status,
            NULLIF(t.result, ''),
            t.session_id,
            t.runtime_overrides,
            t.task_intent_json,
            t.deliverable_spec_json,
            t.validation_report_json,
            t.recovery_action_json,
            t.created_at,
            t.updated_at
        FROM tasks t
        WHERE NOT EXISTS (
            SELECT 1
            FROM task_runs tr
            WHERE tr.id = t.id
        );
    END IF;
END $$;

SELECT setval(
    pg_get_serial_sequence('task_runs', 'id'),
    GREATEST(COALESCE((SELECT MAX(id) FROM task_runs), 1), 1),
    true
);

CREATE TABLE IF NOT EXISTS task_steps (
    id SERIAL PRIMARY KEY,
    task_id INTEGER NOT NULL REFERENCES task_runs(id) ON DELETE CASCADE,
    step_order INTEGER NOT NULL,
    step_name VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    input_payload TEXT,
    output_payload TEXT,
    error_message TEXT,
    tool_name TEXT,
    output_data TEXT,
    error_strategy TEXT DEFAULT 'fail',
    run_if TEXT,
    skip_if TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE task_steps
    ADD COLUMN IF NOT EXISTS input_payload TEXT,
    ADD COLUMN IF NOT EXISTS output_payload TEXT,
    ADD COLUMN IF NOT EXISTS error_message TEXT,
    ADD COLUMN IF NOT EXISTS tool_name TEXT,
    ADD COLUMN IF NOT EXISTS output_data TEXT,
    ADD COLUMN IF NOT EXISTS error_strategy TEXT DEFAULT 'fail',
    ADD COLUMN IF NOT EXISTS run_if TEXT,
    ADD COLUMN IF NOT EXISTS skip_if TEXT,
    ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS max_retries INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'task_steps'
          AND column_name = 'output'
    ) THEN
        UPDATE task_steps
        SET output_payload = COALESCE(output_payload, output)
        WHERE output_payload IS NULL;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS approvals (
    id SERIAL PRIMARY KEY,
    task_id INTEGER NOT NULL REFERENCES task_runs(id) ON DELETE CASCADE,
    step_order INTEGER NOT NULL DEFAULT 0,
    step_name VARCHAR(255) NOT NULL DEFAULT '',
    tool_name TEXT NOT NULL DEFAULT '',
    input_payload TEXT,
    reason TEXT NOT NULL DEFAULT '',
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    decision_note TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    decided_at TIMESTAMP
);

ALTER TABLE approvals
    ADD COLUMN IF NOT EXISTS step_order INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS step_name VARCHAR(255) NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS tool_name TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS input_payload TEXT,
    ADD COLUMN IF NOT EXISTS reason TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS decision_note TEXT,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ADD COLUMN IF NOT EXISTS decided_at TIMESTAMP;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'approvals'
          AND column_name = 'payload_json'
    ) THEN
        UPDATE approvals
        SET input_payload = COALESCE(input_payload, payload_json::text)
        WHERE input_payload IS NULL;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS audit_logs (
    id SERIAL PRIMARY KEY,
    task_id INTEGER REFERENCES task_runs(id),
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    details JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

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

CREATE TABLE IF NOT EXISTS agent_runs (
    id SERIAL PRIMARY KEY,
    task_run_id INTEGER REFERENCES task_runs(id) ON DELETE CASCADE,
    parent_agent_run_id INTEGER REFERENCES agent_runs(id) ON DELETE SET NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'specialist',
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

ALTER TABLE agent_runs
    ADD COLUMN IF NOT EXISTS task_run_id INTEGER REFERENCES task_runs(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS parent_agent_run_id INTEGER REFERENCES agent_runs(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS role VARCHAR(50) NOT NULL DEFAULT 'specialist',
    ADD COLUMN IF NOT EXISTS attempt INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS brief_artifact_id INTEGER,
    ADD COLUMN IF NOT EXISTS output_artifact_id INTEGER,
    ADD COLUMN IF NOT EXISTS review_artifact_id INTEGER,
    ADD COLUMN IF NOT EXISTS execution_mode TEXT,
    ADD COLUMN IF NOT EXISTS execution_request_json TEXT,
    ADD COLUMN IF NOT EXISTS source_task_run_id INTEGER REFERENCES task_runs(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS assigned_step_orders_json TEXT,
    ADD COLUMN IF NOT EXISTS assigned_model TEXT,
    ADD COLUMN IF NOT EXISTS assigned_tool_profile TEXT,
    ADD COLUMN IF NOT EXISTS error_summary TEXT,
    ADD COLUMN IF NOT EXISTS cost_tokens_in INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS cost_tokens_out INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS cost_usd_estimate NUMERIC(12, 6) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ADD COLUMN IF NOT EXISTS started_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'agent_runs'
          AND column_name = 'task_id'
    ) THEN
        UPDATE agent_runs
        SET task_run_id = COALESCE(task_run_id, task_id)
        WHERE task_run_id IS NULL;
    END IF;
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'agent_runs'
          AND column_name = 'role_name'
    ) THEN
        UPDATE agent_runs
        SET role = COALESCE(NULLIF(role_name, ''), NULLIF(role, ''), 'specialist')
        WHERE role IS NULL OR role = '' OR role = 'specialist';
    END IF;
END $$;

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

CREATE TABLE IF NOT EXISTS evaluator_runs (
    id SERIAL PRIMARY KEY,
    task_run_id INTEGER REFERENCES task_runs(id) ON DELETE CASCADE,
    manager_agent_run_id INTEGER REFERENCES agent_runs(id) ON DELETE SET NULL,
    reviewer_agent_run_id INTEGER REFERENCES agent_runs(id) ON DELETE SET NULL,
    final_artifact_id INTEGER REFERENCES agent_artifacts(id) ON DELETE SET NULL,
    review_artifact_id INTEGER REFERENCES agent_artifacts(id) ON DELETE SET NULL,
    evaluator_kind VARCHAR(50) NOT NULL DEFAULT 'stage6_quality_gate',
    status VARCHAR(50) NOT NULL DEFAULT 'completed',
    decision VARCHAR(50) NOT NULL DEFAULT 'pending',
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

ALTER TABLE evaluator_runs
    ADD COLUMN IF NOT EXISTS task_run_id INTEGER REFERENCES task_runs(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS manager_agent_run_id INTEGER REFERENCES agent_runs(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS reviewer_agent_run_id INTEGER REFERENCES agent_runs(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS final_artifact_id INTEGER REFERENCES agent_artifacts(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS review_artifact_id INTEGER REFERENCES agent_artifacts(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS evaluator_kind VARCHAR(50) NOT NULL DEFAULT 'stage6_quality_gate',
    ADD COLUMN IF NOT EXISTS decision VARCHAR(50) NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS score INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS failure_reason TEXT NOT NULL DEFAULT 'none',
    ADD COLUMN IF NOT EXISTS failure_stage TEXT NOT NULL DEFAULT 'none',
    ADD COLUMN IF NOT EXISTS criteria_json TEXT,
    ADD COLUMN IF NOT EXISTS step_stats_json TEXT,
    ADD COLUMN IF NOT EXISTS proposal_json TEXT,
    ADD COLUMN IF NOT EXISTS summary TEXT,
    ADD COLUMN IF NOT EXISTS recommendation TEXT,
    ADD COLUMN IF NOT EXISTS source TEXT;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'evaluator_runs'
          AND column_name = 'task_id'
    ) THEN
        UPDATE evaluator_runs
        SET task_run_id = COALESCE(task_run_id, task_id)
        WHERE task_run_id IS NULL;
    END IF;
END $$;

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

CREATE TABLE IF NOT EXISTS session_states (
    session_id INTEGER PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    summary_text TEXT NOT NULL DEFAULT '',
    preferences JSONB NOT NULL DEFAULT '[]'::jsonb,
    open_loops JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE session_states
    ADD COLUMN IF NOT EXISTS summary_text TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS preferences JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS open_loops JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'session_states'
          AND column_name = 'state_json'
    ) THEN
        UPDATE session_states
        SET summary_text = COALESCE(NULLIF(summary_text, ''), COALESCE(state_json->>'summary_text', '')),
            preferences = CASE
                WHEN preferences IS NULL OR preferences = '[]'::jsonb THEN COALESCE(state_json->'preferences', '[]'::jsonb)
                ELSE preferences
            END,
            open_loops = CASE
                WHEN open_loops IS NULL OR open_loops = '[]'::jsonb THEN COALESCE(state_json->'open_loops', '[]'::jsonb)
                ELSE open_loops
            END
        WHERE summary_text IS NULL
           OR summary_text = ''
           OR preferences IS NULL
           OR preferences = '[]'::jsonb
           OR open_loops IS NULL
           OR open_loops = '[]'::jsonb;
    END IF;
END $$;

DELETE FROM session_states a
USING session_states b
WHERE a.ctid < b.ctid
  AND a.session_id = b.session_id;

CREATE UNIQUE INDEX IF NOT EXISTS idx_session_states_session_id_unique
    ON session_states(session_id);

CREATE TABLE IF NOT EXISTS session_reviews (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    review_kind VARCHAR(100) NOT NULL DEFAULT 'manual',
    summary_text TEXT NOT NULL DEFAULT '',
    highlights JSONB NOT NULL DEFAULT '[]'::jsonb,
    open_loops JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE session_reviews
    ADD COLUMN IF NOT EXISTS review_kind VARCHAR(100) NOT NULL DEFAULT 'manual',
    ADD COLUMN IF NOT EXISTS summary_text TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS highlights JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS open_loops JSONB NOT NULL DEFAULT '[]'::jsonb;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'session_reviews'
          AND column_name = 'review_json'
    ) THEN
        UPDATE session_reviews
        SET summary_text = COALESCE(NULLIF(summary_text, ''), COALESCE(review_json->>'summary_text', '')),
            review_kind = COALESCE(NULLIF(review_kind, ''), COALESCE(review_json->>'review_kind', 'manual')),
            highlights = CASE
                WHEN highlights IS NULL OR highlights = '[]'::jsonb THEN COALESCE(review_json->'highlights', '[]'::jsonb)
                ELSE highlights
            END,
            open_loops = CASE
                WHEN open_loops IS NULL OR open_loops = '[]'::jsonb THEN COALESCE(review_json->'open_loops', '[]'::jsonb)
                ELSE open_loops
            END
        WHERE summary_text IS NULL
           OR summary_text = ''
           OR review_kind IS NULL
           OR review_kind = ''
           OR highlights IS NULL
           OR highlights = '[]'::jsonb
           OR open_loops IS NULL
           OR open_loops = '[]'::jsonb;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS change_requests (
    id SERIAL PRIMARY KEY,
    target_type TEXT NOT NULL,
    target_key TEXT NOT NULL DEFAULT '',
    proposed_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    rationale TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    requested_by_actor TEXT NOT NULL DEFAULT 'system',
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

ALTER TABLE change_requests
    ADD COLUMN IF NOT EXISTS target_key TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS proposed_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS rationale TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS requested_by_actor TEXT NOT NULL DEFAULT 'system',
    ADD COLUMN IF NOT EXISTS reviewed_by_actor TEXT,
    ADD COLUMN IF NOT EXISTS decision_note TEXT,
    ADD COLUMN IF NOT EXISTS applied_by_actor TEXT,
    ADD COLUMN IF NOT EXISTS proposal_kind TEXT NOT NULL DEFAULT 'manual_change',
    ADD COLUMN IF NOT EXISTS source_change_request_id INTEGER REFERENCES change_requests(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS source_workflow_proposal_id INTEGER,
    ADD COLUMN IF NOT EXISTS shadow_validation_status TEXT NOT NULL DEFAULT 'not_required',
    ADD COLUMN IF NOT EXISTS shadow_validation_report JSONB,
    ADD COLUMN IF NOT EXISTS shadow_validation_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS baseline_payload JSONB,
    ADD COLUMN IF NOT EXISTS payload_patch JSONB,
    ADD COLUMN IF NOT EXISTS patch_summary TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS rollback_payload JSONB,
    ADD COLUMN IF NOT EXISTS rollback_ready BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS rollback_note TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS acceptance_status TEXT NOT NULL DEFAULT 'not_configured',
    ADD COLUMN IF NOT EXISTS acceptance_report JSONB,
    ADD COLUMN IF NOT EXISTS acceptance_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS auto_rollback_change_request_id INTEGER REFERENCES change_requests(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS auto_rollback_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS applied_at TIMESTAMP;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'change_requests'
          AND column_name = 'target_name'
    ) THEN
        UPDATE change_requests
        SET target_key = COALESCE(NULLIF(target_key, ''), target_name)
        WHERE target_key IS NULL OR target_key = '';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'change_requests'
          AND column_name = 'payload_json'
    ) THEN
        UPDATE change_requests
        SET proposed_payload = CASE
            WHEN proposed_payload IS NULL OR proposed_payload = '{}'::jsonb THEN payload_json
            ELSE proposed_payload
        END
        WHERE proposed_payload IS NULL OR proposed_payload = '{}'::jsonb;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_task_runs_status ON task_runs(status);
CREATE INDEX IF NOT EXISTS idx_task_runs_session_id ON task_runs(session_id);
CREATE INDEX IF NOT EXISTS idx_task_runs_created_by_actor ON task_runs(created_by_actor);
CREATE INDEX IF NOT EXISTS idx_task_steps_task_id_step_order ON task_steps(task_id, step_order);
CREATE INDEX IF NOT EXISTS idx_approvals_task_id_status ON approvals(task_id, status);
CREATE INDEX IF NOT EXISTS idx_agent_runs_task_run_id ON agent_runs(task_run_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_status ON agent_runs(status);
CREATE INDEX IF NOT EXISTS idx_evaluator_runs_task_run_id ON evaluator_runs(task_run_id);
CREATE INDEX IF NOT EXISTS idx_change_requests_status ON change_requests(status);
CREATE INDEX IF NOT EXISTS idx_change_requests_source_workflow_proposal_id ON change_requests(source_workflow_proposal_id);
