CREATE TABLE IF NOT EXISTS schema_migrations (
    migration_id TEXT PRIMARY KEY,
    description TEXT NOT NULL DEFAULT '',
    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tasks (
    id BIGSERIAL PRIMARY KEY,
    user_input TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    result TEXT NOT NULL DEFAULT '',
    runtime_overrides JSONB NOT NULL DEFAULT '{}'::jsonb,
    task_intent_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    deliverable_spec_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    validation_report_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    recovery_action_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS task_steps (
    id BIGSERIAL PRIMARY KEY,
    task_id BIGINT NOT NULL,
    step_order INTEGER NOT NULL,
    step_name TEXT NOT NULL DEFAULT '',
    tool_name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    output TEXT NOT NULL DEFAULT '',
    runtime_state_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS approvals (
    id BIGSERIAL PRIMARY KEY,
    task_id BIGINT NOT NULL,
    step_id BIGINT,
    status TEXT NOT NULL DEFAULT 'pending',
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

