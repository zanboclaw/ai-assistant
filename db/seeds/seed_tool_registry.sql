INSERT INTO tool_registry (tool_name, enabled)
VALUES
    ('web_search', TRUE),
    ('shell_command', TRUE),
    ('file_read', TRUE)
ON CONFLICT (tool_name) DO NOTHING;

