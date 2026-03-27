CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_session_id ON tasks(session_id);
CREATE INDEX IF NOT EXISTS idx_task_steps_task_id ON task_steps(task_id, step_order);
CREATE INDEX IF NOT EXISTS idx_long_term_memories_task_id ON long_term_memories(task_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_task_id ON audit_logs(task_id);

