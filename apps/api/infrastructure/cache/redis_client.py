from __future__ import annotations

import os

try:
    import redis
except ImportError:  # pragma: no cover
    redis = None


def get_redis_client():
    if redis is None:
        return None
    return redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379/0"), decode_responses=True)

