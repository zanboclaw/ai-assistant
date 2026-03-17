from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor

app = FastAPI(title="AI Assistant API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_CONFIG = {
    "host": "postgres",
    "dbname": "assistant",
    "user": "assistant",
    "password": "assistant123",
}


class TaskCreate(BaseModel):
    user_input: str


def get_conn():
    return psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)


@app.get("/")
def root():
    return {"message": "ai assistant api is running"}


@app.post("/init-db")
def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS task_runs (
        id SERIAL PRIMARY KEY,
        user_input TEXT NOT NULL,
        status VARCHAR(50) NOT NULL DEFAULT 'pending',
        result TEXT,
        error_message TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS task_steps (
        id SERIAL PRIMARY KEY,
        task_id INTEGER NOT NULL REFERENCES task_runs(id) ON DELETE CASCADE,
        step_order INTEGER NOT NULL,
        step_name VARCHAR(255) NOT NULL,
        status VARCHAR(50) NOT NULL DEFAULT 'pending',
        input_payload TEXT,
        output_payload TEXT,
        error_message TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    cur.execute("""
    ALTER TABLE task_steps
    ADD COLUMN IF NOT EXISTS tool_name TEXT;
    """)

    cur.execute("""
    ALTER TABLE task_steps
    ADD COLUMN IF NOT EXISTS output_data TEXT;
    """)

    cur.execute("""
    ALTER TABLE task_steps
    ADD COLUMN IF NOT EXISTS error_strategy TEXT DEFAULT 'fail';
    """)

    conn.commit()
    cur.close()
    conn.close()

    return {"message": "database initialized"}


@app.post("/tasks")
def create_task(task: TaskCreate):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO task_runs (user_input, status)
        VALUES (%s, 'pending')
        RETURNING id, user_input, status, created_at;
        """,
        (task.user_input,),
    )
    row = cur.fetchone()
    conn.commit()

    cur.close()
    conn.close()

    return row


@app.get("/tasks")
def list_tasks():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            user_input,
            status,
            result,
            error_message,
            created_at,
            updated_at
        FROM task_runs
        ORDER BY id DESC;
    """)
    rows = cur.fetchall()

    cur.close()
    conn.close()

    return rows


@app.get("/tasks/{task_id}")
def get_task(task_id: int):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            id,
            user_input,
            status,
            result,
            error_message,
            created_at,
            updated_at
        FROM task_runs
        WHERE id = %s;
    """,
        (task_id,),
    )
    row = cur.fetchone()

    cur.close()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Task not found")

    return row


@app.get("/tasks/{task_id}/steps")
def get_task_steps(task_id: int):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id FROM task_runs WHERE id = %s;", (task_id,))
    task_exists = cur.fetchone()
    if not task_exists:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Task not found")

    cur.execute(
        """
        SELECT
            id,
            task_id,
            step_order,
            step_name,
            tool_name,
            status,
            input_payload,
            output_payload,
            output_data,
            error_message,
            error_strategy,
            created_at,
            updated_at
        FROM task_steps
        WHERE task_id = %s
        ORDER BY step_order ASC;
    """,
        (task_id,),
    )
    rows = cur.fetchall()

    cur.close()
    conn.close()

    return rows
