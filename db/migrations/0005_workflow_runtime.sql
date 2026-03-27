CREATE TABLE IF NOT EXISTS change_requests (
    id BIGSERIAL PRIMARY KEY,
    target_type TEXT NOT NULL,
    target_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS workflow_proposals (
    id BIGSERIAL PRIMARY KEY,
    task_id BIGINT,
    title TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    proposal_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

