from __future__ import annotations

import os
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor


DB_CONFIG = {
    "host": os.environ.get("POSTGRES_HOST", "postgres"),
    "dbname": os.environ.get("POSTGRES_DB", "assistant"),
    "user": os.environ.get("POSTGRES_USER", "assistant"),
    "password": os.environ.get("POSTGRES_PASSWORD", "change_me_for_local_dev"),
}


def get_conn(**overrides: Any):
    config = {**DB_CONFIG, **overrides}
    return psycopg2.connect(cursor_factory=RealDictCursor, **config)

