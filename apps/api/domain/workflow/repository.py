from __future__ import annotations


class WorkflowRepository:
    def __init__(self, *, get_conn):
        self._get_conn = get_conn

