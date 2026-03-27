INSERT INTO access_actors (actor_name, role_name)
VALUES
    ('local_admin', 'admin'),
    ('local_operator', 'operator'),
    ('local_viewer', 'viewer')
ON CONFLICT (actor_name) DO NOTHING;

