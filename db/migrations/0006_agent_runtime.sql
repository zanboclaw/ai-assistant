CREATE TABLE IF NOT EXISTS agent_runs (
    id BIGSERIAL PRIMARY KEY,
    task_id BIGINT NOT NULL,
    role_name TEXT NOT NULL DEFAULT 'specialist',
    status TEXT NOT NULL DEFAULT 'pending',
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS evaluator_runs (
    id BIGSERIAL PRIMARY KEY,
    task_id BIGINT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

