UPDATE tasks
SET runtime_overrides = '{}'::jsonb
WHERE runtime_overrides IS NULL;

UPDATE tasks
SET task_intent_json = '{}'::jsonb
WHERE task_intent_json IS NULL;

UPDATE tasks
SET deliverable_spec_json = '{}'::jsonb
WHERE deliverable_spec_json IS NULL;

