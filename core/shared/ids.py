from __future__ import annotations

import uuid


def generate_public_id(prefix: str) -> str:
    normalized_prefix = str(prefix or "").strip().lower() or "id"
    return f"{normalized_prefix}_{uuid.uuid4().hex[:12]}"

