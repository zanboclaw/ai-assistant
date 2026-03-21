import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any


def safe_json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return json.dumps({"repr": repr(value)}, ensure_ascii=False)


def make_json_compatible(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): make_json_compatible(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [make_json_compatible(item) for item in value]
    return value


def compute_stable_payload_hash(payload: Any) -> str:
    normalized_payload = make_json_compatible(payload if payload is not None else {})
    try:
        serialized = json.dumps(normalized_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except Exception:
        serialized = safe_json_dumps(normalized_payload)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def parse_optional_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None
