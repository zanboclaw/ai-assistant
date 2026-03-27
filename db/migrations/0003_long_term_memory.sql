CREATE TABLE IF NOT EXISTS long_term_memories (
    id BIGSERIAL PRIMARY KEY,
    task_id BIGINT,
    session_id BIGINT,
    memory_kind TEXT NOT NULL DEFAULT 'fact',
    title TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

