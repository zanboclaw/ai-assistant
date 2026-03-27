DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'task_steps_task_fk'
    ) THEN
        ALTER TABLE task_steps
            ADD CONSTRAINT task_steps_task_fk
            FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE;
    END IF;
END $$;

