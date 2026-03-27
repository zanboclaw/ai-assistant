INSERT INTO model_routes (route_name, provider_name, config_json)
VALUES
    ('planner', 'default', '{}'::jsonb),
    ('executor', 'default', '{}'::jsonb)
ON CONFLICT (route_name) DO NOTHING;

