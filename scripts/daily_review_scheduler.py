#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


API_BASE = os.environ.get("API_BASE", "http://api:8000").rstrip("/")
LOG_DIR = Path(os.environ.get("LOG_DIR", "/opt/ai-assistant/logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)
INTERVAL_SECONDS = max(60, int(os.environ.get("DAILY_REVIEW_INTERVAL_SECONDS", "3600")))
STARTUP_DELAY_SECONDS = max(0, int(os.environ.get("DAILY_REVIEW_STARTUP_DELAY_SECONDS", "15")))
REVIEW_KIND = os.environ.get("DAILY_REVIEW_KIND", "daily")
SESSION_LIMIT = max(1, int(os.environ.get("DAILY_REVIEW_SESSION_LIMIT", "20")))
ACTIVE_WITHIN_HOURS = max(1, int(os.environ.get("DAILY_REVIEW_ACTIVE_WITHIN_HOURS", "24")))
FORCE = os.environ.get("DAILY_REVIEW_FORCE", "0").lower() in {"1", "true", "yes"}
NOTE = os.environ.get("DAILY_REVIEW_NOTE", "")
RUN_ONCE = os.environ.get("RUN_ONCE", "0").lower() in {"1", "true", "yes"}


logger = logging.getLogger("daily_review_scheduler")
logger.setLevel(logging.INFO)
logger.handlers.clear()
formatter = logging.Formatter("[%(asctime)s] %(levelname)s %(message)s")

stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(formatter)
logger.addHandler(stream_handler)

file_handler = logging.FileHandler(LOG_DIR / "scheduler.log", encoding="utf-8")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)


def trigger_daily_reviews() -> dict:
    payload = {
        "review_kind": REVIEW_KIND,
        "note": NOTE,
        "session_limit": SESSION_LIMIT,
        "active_within_hours": ACTIVE_WITHIN_HOURS,
        "force": FORCE,
    }
    req = urllib.request.Request(
        f"{API_BASE}/reviews/daily-run",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def main() -> None:
    logger.info(
        "scheduler started api_base=%s interval_seconds=%s review_kind=%s session_limit=%s active_within_hours=%s run_once=%s",
        API_BASE,
        INTERVAL_SECONDS,
        REVIEW_KIND,
        SESSION_LIMIT,
        ACTIVE_WITHIN_HOURS,
        RUN_ONCE,
    )

    if STARTUP_DELAY_SECONDS:
        time.sleep(STARTUP_DELAY_SECONDS)

    while True:
        try:
            result = trigger_daily_reviews()
            logger.info(
                "daily review run completed created=%s skipped=%s review_kind=%s",
                len(result.get("created", [])),
                len(result.get("skipped", [])),
                result.get("review_kind", REVIEW_KIND),
            )
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            logger.warning("daily review run failed status=%s body=%s", exc.code, body)
        except Exception as exc:  # pragma: no cover - runtime safety
            logger.warning("daily review run failed error=%s", exc)

        if RUN_ONCE:
            return
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
