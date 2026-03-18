from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import psycopg2
from psycopg2.extras import RealDictCursor
try:
    import redis
except ImportError:  # pragma: no cover - optional in local non-container runs
    redis = None

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

LOG_DIR = Path(os.environ.get("LOG_DIR", "/opt/ai-assistant/logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)
CHECKPOINT_DIR = Path(os.environ.get("CHECKPOINT_DIR", "/checkpoints"))
CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

DEFAULT_RISK_POLICIES = [
    {
        "policy_key": "approval_low_risk_write_extensions",
        "value_type": "json",
        "policy_value": [".txt", ".md", ".csv", ".log"],
        "description": "新建这些扩展名的文件时可直接写入，无需审批。",
    },
    {
        "policy_key": "approval_sensitive_write_extensions",
        "value_type": "json",
        "policy_value": [".py", ".sh", ".bash", ".zsh", ".env", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".sql"],
        "description": "写入这些脚本/配置类扩展名时必须审批。",
    },
    {
        "policy_key": "approval_sensitive_write_basenames",
        "value_type": "json",
        "policy_value": ["dockerfile", "makefile", ".env", ".gitignore"],
        "description": "写入这些特定文件名时必须审批。",
    },
    {
        "policy_key": "approval_require_for_existing_file_overwrite",
        "value_type": "bool",
        "policy_value": True,
        "description": "覆盖已有文件时是否要求审批。",
    },
    {
        "policy_key": "approval_require_for_hidden_files",
        "value_type": "bool",
        "policy_value": True,
        "description": "写入隐藏文件时是否要求审批。",
    },
    {
        "policy_key": "approval_allowed_http_methods",
        "value_type": "json",
        "policy_value": ["GET"],
        "description": "这些 HTTP 方法默认允许直通，其余方法要求审批。",
    },
    {
        "policy_key": "approval_http_get_requires_approval_suffixes",
        "value_type": "json",
        "policy_value": [".local"],
        "description": "GET 请求命中这些域名后缀时仍要求审批。",
    },
]
RISK_POLICY_MAP = {item["policy_key"]: item for item in DEFAULT_RISK_POLICIES}


def build_logger() -> logging.Logger:
    logger = logging.getLogger("ai_assistant.api")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("[%(asctime)s] %(levelname)s %(message)s")

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    file_handler = logging.FileHandler(LOG_DIR / "api.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


logger = build_logger()


def get_redis_client():
    if redis is None:
        return None
    try:
        return redis.Redis.from_url(REDIS_URL, decode_responses=True)
    except Exception as exc:
        logger.warning("redis client init failed: %s", exc)
        return None


def enqueue_task(task_id: int):
    client = get_redis_client()
    if client is None:
        logger.warning("redis unavailable, skip enqueue task_id=%s", task_id)
        return
    try:
        client.rpush("task_queue", str(task_id))
    except Exception as exc:
        logger.warning("enqueue task failed task_id=%s error=%s", task_id, exc)


class TaskCreate(BaseModel):
    user_input: str


class ApprovalDecision(BaseModel):
    note: str = ""


class TaskResumeRequest(BaseModel):
    note: str = ""
    from_step: int | None = None


class TaskInterruptRequest(BaseModel):
    note: str = ""


class RiskPolicyUpdate(BaseModel):
    policy_value: Any


def get_conn():
    return psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)


def safe_json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def ensure_risk_policies_table(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS risk_policies (
            id SERIAL PRIMARY KEY,
            policy_key TEXT NOT NULL UNIQUE,
            value_type TEXT NOT NULL,
            policy_value TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )


def seed_default_risk_policies(cur):
    ensure_risk_policies_table(cur)
    for item in DEFAULT_RISK_POLICIES:
        cur.execute(
            """
            INSERT INTO risk_policies (policy_key, value_type, policy_value, description)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (policy_key) DO NOTHING;
            """,
            (
                item["policy_key"],
                item["value_type"],
                safe_json_dumps(item["policy_value"]),
                item["description"],
            ),
        )


def deserialize_policy_row(row: dict) -> dict:
    try:
        parsed_value = json.loads(row["policy_value"])
    except Exception:
        parsed_value = row["policy_value"]
    return {
        "policy_key": row["policy_key"],
        "value_type": row["value_type"],
        "policy_value": parsed_value,
        "description": row["description"],
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def validate_policy_value(policy_key: str, value: Any) -> tuple[str, str]:
    item = RISK_POLICY_MAP.get(policy_key)
    if not item:
        raise HTTPException(status_code=404, detail="Risk policy not found")

    value_type = item["value_type"]
    if value_type == "bool":
        if not isinstance(value, bool):
            raise HTTPException(status_code=400, detail="policy_value must be boolean")
    elif value_type == "json":
        if not isinstance(value, list) or not all(isinstance(part, str) and part.strip() for part in value):
            raise HTTPException(status_code=400, detail="policy_value must be a non-empty string list")
        value = [part.strip() for part in value]
    else:
        raise HTTPException(status_code=500, detail="Unsupported policy type")

    return value_type, safe_json_dumps(value)


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
    ALTER TABLE task_runs
    ADD COLUMN IF NOT EXISTS current_step INTEGER;
    """)

    cur.execute("""
    ALTER TABLE task_runs
    ADD COLUMN IF NOT EXISTS checkpoint_path TEXT;
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

    cur.execute("""
    ALTER TABLE task_steps
    ADD COLUMN IF NOT EXISTS run_if TEXT;
    """)

    cur.execute("""
    ALTER TABLE task_steps
    ADD COLUMN IF NOT EXISTS skip_if TEXT;
    """)

    cur.execute("""
    ALTER TABLE task_steps
    ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0;
    """)

    cur.execute("""
    ALTER TABLE task_steps
    ADD COLUMN IF NOT EXISTS max_retries INTEGER NOT NULL DEFAULT 0;
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS approvals (
        id SERIAL PRIMARY KEY,
        task_id INTEGER NOT NULL REFERENCES task_runs(id) ON DELETE CASCADE,
        step_order INTEGER NOT NULL,
        step_name VARCHAR(255) NOT NULL,
        tool_name TEXT NOT NULL,
        input_payload TEXT,
        reason TEXT NOT NULL,
        status VARCHAR(50) NOT NULL DEFAULT 'pending',
        decision_note TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        decided_at TIMESTAMP
    );
    """)

    seed_default_risk_policies(cur)

    conn.commit()
    cur.close()
    conn.close()

    logger.info("database initialized")

    return {"message": "database initialized"}


@app.get("/risk-policies")
def list_risk_policies():
    conn = get_conn()
    cur = conn.cursor()
    seed_default_risk_policies(cur)
    conn.commit()

    cur.execute(
        """
        SELECT policy_key, value_type, policy_value, description, created_at, updated_at
        FROM risk_policies
        ORDER BY policy_key ASC;
        """
    )
    rows = [deserialize_policy_row(row) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


@app.put("/risk-policies/{policy_key}")
def update_risk_policy(policy_key: str, request: RiskPolicyUpdate):
    value_type, serialized_value = validate_policy_value(policy_key, request.policy_value)

    conn = get_conn()
    cur = conn.cursor()
    seed_default_risk_policies(cur)
    cur.execute(
        """
        UPDATE risk_policies
        SET value_type = %s,
            policy_value = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE policy_key = %s
        RETURNING policy_key, value_type, policy_value, description, created_at, updated_at;
        """,
        (value_type, serialized_value, policy_key),
    )
    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Risk policy not found")

    logger.info("risk policy updated policy_key=%s", policy_key)
    return deserialize_policy_row(row)


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
    enqueue_task(int(row["id"]))

    logger.info("task created id=%s user_input=%s", row["id"], task.user_input[:200])

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
            current_step,
            checkpoint_path,
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
            current_step,
            checkpoint_path,
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
            run_if,
            skip_if,
            retry_count,
            max_retries,
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


@app.get("/approvals")
def list_approvals(status: str | None = None):
    conn = get_conn()
    cur = conn.cursor()

    if status:
        cur.execute(
            """
            SELECT
                id,
                task_id,
                step_order,
                step_name,
                tool_name,
                input_payload,
                reason,
                status,
                decision_note,
                created_at,
                updated_at,
                decided_at
            FROM approvals
            WHERE status = %s
            ORDER BY id DESC;
            """,
            (status,),
        )
    else:
        cur.execute(
            """
            SELECT
                id,
                task_id,
                step_order,
                step_name,
                tool_name,
                input_payload,
                reason,
                status,
                decision_note,
                created_at,
                updated_at,
                decided_at
            FROM approvals
            ORDER BY id DESC;
            """
        )

    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


@app.get("/tasks/{task_id}/checkpoint")
def get_task_checkpoint(task_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, checkpoint_path
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

    checkpoint_path = (row.get("checkpoint_path") or "").strip()
    if not checkpoint_path:
        raise HTTPException(status_code=404, detail="Checkpoint not found")

    path = Path(checkpoint_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Checkpoint file missing")

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Checkpoint unreadable: {exc}")


def get_task_or_404(cur, task_id: int):
    cur.execute(
        """
        SELECT id, status, current_step, checkpoint_path, error_message
        FROM task_runs
        WHERE id = %s;
        """,
        (task_id,),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    return row


def update_checkpoint_status(checkpoint_path_str: str | None, status: str, note: str = ""):
    checkpoint_path = (checkpoint_path_str or "").strip()
    if not checkpoint_path:
        return

    path = Path(checkpoint_path)
    if not path.exists():
        return

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return

    data["status"] = status
    if note:
        data["last_error"] = note
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@app.post("/tasks/{task_id}/interrupt")
def interrupt_task(task_id: int, request: TaskInterruptRequest):
    conn = get_conn()
    cur = conn.cursor()

    task = get_task_or_404(cur, task_id)
    current_status = str(task["status"] or "")
    if current_status in {"completed", "failed"}:
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Completed or failed tasks cannot be interrupted")

    if current_status in {"paused", "interrupt_requested"}:
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Task is already paused or interrupt requested")

    note = request.note.strip() or "manual interrupt requested"
    next_status = "interrupt_requested" if current_status == "running" else "paused"

    cur.execute(
        """
        UPDATE task_runs
        SET status = %s,
            error_message = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s;
        """,
        (next_status, note, task_id),
    )

    update_checkpoint_status(task.get("checkpoint_path"), next_status if next_status != "interrupt_requested" else "running", note)

    conn.commit()
    cur.close()
    conn.close()

    logger.info(
        "task interrupt requested id=%s previous_status=%s next_status=%s note=%s",
        task_id,
        current_status,
        next_status,
        note[:200],
    )
    return {"message": "task interrupt requested", "task_id": task_id, "status": next_status}


@app.post("/tasks/{task_id}/resume")
def resume_task(task_id: int, request: TaskResumeRequest):
    conn = get_conn()
    cur = conn.cursor()

    task = get_task_or_404(cur, task_id)
    if task["status"] not in {"failed", "waiting_approval", "paused", "interrupt_requested"}:
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Only failed, paused, interrupt_requested, or waiting_approval tasks can be resumed")

    cur.execute(
        """
        SELECT id
        FROM approvals
        WHERE task_id = %s AND status = 'pending'
        ORDER BY id DESC;
        """,
        (task_id,),
    )
    pending_approvals = cur.fetchall()
    if pending_approvals:
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Task has pending approvals; approve or reject them first")

    resume_from = request.from_step or task.get("current_step")
    if not resume_from:
        cur.execute(
            """
            SELECT step_order
            FROM task_steps
            WHERE task_id = %s AND status != 'completed'
            ORDER BY step_order ASC
            LIMIT 1;
            """,
            (task_id,),
        )
        row = cur.fetchone()
        resume_from = row["step_order"] if row else 1

    cur.execute(
        """
        UPDATE task_steps
        SET status = 'pending',
            output_payload = NULL,
            output_data = NULL,
            error_message = '',
            retry_count = 0,
            updated_at = CURRENT_TIMESTAMP
        WHERE task_id = %s
          AND step_order >= %s;
        """,
        (task_id, resume_from),
    )

    cur.execute(
        """
        UPDATE task_runs
        SET status = 'pending',
            result = NULL,
            error_message = NULL,
            current_step = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s;
        """,
        (resume_from, task_id),
    )

    conn.commit()
    cur.close()
    conn.close()

    enqueue_task(task_id)
    update_checkpoint_status(task.get("checkpoint_path"), "pending", request.note.strip() or "task resumed")
    logger.info(
        "task resumed id=%s from_step=%s note=%s previous_status=%s",
        task_id,
        resume_from,
        request.note[:200],
        task["status"],
    )
    return {"message": "task resumed", "task_id": task_id, "from_step": resume_from}


@app.get("/tasks/{task_id}/approvals")
def list_task_approvals(task_id: int):
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
            input_payload,
            reason,
            status,
            decision_note,
            created_at,
            updated_at,
            decided_at
        FROM approvals
        WHERE task_id = %s
        ORDER BY id DESC;
        """,
        (task_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def get_approval_or_404(cur, approval_id: int):
    cur.execute(
        """
        SELECT id, task_id, step_order, status
        FROM approvals
        WHERE id = %s;
        """,
        (approval_id,),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Approval not found")
    return row


@app.post("/approvals/{approval_id}/approve")
def approve_approval(approval_id: int, decision: ApprovalDecision):
    conn = get_conn()
    cur = conn.cursor()

    approval = get_approval_or_404(cur, approval_id)
    if approval["status"] != "pending":
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Approval is not pending")

    cur.execute(
        """
        UPDATE approvals
        SET status = 'approved',
            decision_note = %s,
            updated_at = CURRENT_TIMESTAMP,
            decided_at = CURRENT_TIMESTAMP
        WHERE id = %s;
        """,
        (decision.note, approval_id),
    )

    cur.execute(
        """
        UPDATE task_steps
        SET status = 'pending',
            error_message = '',
            updated_at = CURRENT_TIMESTAMP
        WHERE task_id = %s AND step_order = %s;
        """,
        (approval["task_id"], approval["step_order"]),
    )

    cur.execute(
        """
        UPDATE task_runs
        SET status = 'pending',
            error_message = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s;
        """,
        (approval["task_id"],),
    )

    conn.commit()
    cur.close()
    conn.close()
    enqueue_task(int(approval["task_id"]))
    logger.info(
        "approval approved approval_id=%s task_id=%s step_order=%s note=%s",
        approval_id,
        approval["task_id"],
        approval["step_order"],
        decision.note[:200],
    )
    return {"message": "approval approved", "approval_id": approval_id}


@app.post("/approvals/{approval_id}/reject")
def reject_approval(approval_id: int, decision: ApprovalDecision):
    conn = get_conn()
    cur = conn.cursor()

    approval = get_approval_or_404(cur, approval_id)
    if approval["status"] != "pending":
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Approval is not pending")

    note = decision.note.strip() or "审批拒绝"

    cur.execute(
        """
        UPDATE approvals
        SET status = 'rejected',
            decision_note = %s,
            updated_at = CURRENT_TIMESTAMP,
            decided_at = CURRENT_TIMESTAMP
        WHERE id = %s;
        """,
        (note, approval_id),
    )

    cur.execute(
        """
        UPDATE task_steps
        SET status = 'failed',
            output_payload = %s,
            error_message = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE task_id = %s AND step_order = %s;
        """,
        (f"审批拒绝：{note}", f"审批拒绝：{note}", approval["task_id"], approval["step_order"]),
    )

    cur.execute(
        """
        UPDATE task_runs
        SET status = 'failed',
            error_message = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s;
        """,
        (f"审批拒绝：{note}", approval["task_id"]),
    )

    conn.commit()
    cur.close()
    conn.close()
    logger.info(
        "approval rejected approval_id=%s task_id=%s step_order=%s note=%s",
        approval_id,
        approval["task_id"],
        approval["step_order"],
        note[:200],
    )
    return {"message": "approval rejected", "approval_id": approval_id}
