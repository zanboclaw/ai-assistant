from __future__ import annotations

from typing import Any


class TaskRepository:
    def __init__(self, *, get_conn):
        self._get_conn = get_conn

    def fetch_by_id(self, task_id: int) -> dict[str, Any] | None:
        conn = self._get_conn()
        cur = conn.cursor()
        try:
            cur.execute("SELECT * FROM tasks WHERE id = %s;", (task_id,))
            return cur.fetchone()
        finally:
            cur.close()
            conn.close()

