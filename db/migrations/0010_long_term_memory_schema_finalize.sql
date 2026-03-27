ALTER TABLE long_term_memories
    ADD COLUMN IF NOT EXISTS memory_key TEXT,
    ADD COLUMN IF NOT EXISTS source_session_id BIGINT,
    ADD COLUMN IF NOT EXISTS source_task_id BIGINT,
    ADD COLUMN IF NOT EXISTS actor_name TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS keywords_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS hit_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE long_term_memories
SET source_session_id = COALESCE(source_session_id, session_id)
WHERE source_session_id IS NULL;

UPDATE long_term_memories
SET source_task_id = COALESCE(source_task_id, task_id)
WHERE source_task_id IS NULL;

UPDATE long_term_memories
SET title = COALESCE(title, '')
WHERE title IS NULL;

UPDATE long_term_memories
SET content = COALESCE(content, '')
WHERE content IS NULL;

UPDATE long_term_memories
SET memory_key = md5(
    concat_ws(
        '::',
        lower(COALESCE(memory_kind, 'fact')),
        COALESCE(title, ''),
        COALESCE(content, ''),
        COALESCE(id::text, '')
    )
)
WHERE memory_key IS NULL OR memory_key = '';

CREATE UNIQUE INDEX IF NOT EXISTS idx_long_term_memories_memory_key
    ON long_term_memories(memory_key);

CREATE INDEX IF NOT EXISTS idx_long_term_memories_source_session_id
    ON long_term_memories(source_session_id);

CREATE INDEX IF NOT EXISTS idx_long_term_memories_source_task_id
    ON long_term_memories(source_task_id);

CREATE INDEX IF NOT EXISTS idx_long_term_memories_actor_name
    ON long_term_memories(actor_name);
