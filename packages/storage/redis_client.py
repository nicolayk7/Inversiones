"""Redis client. Used for caching/rate-limiting starting Phase 1 — Phase 0 only proves
connectivity via the health endpoint."""

import redis.asyncio as redis

from packages.shared.config import settings

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(settings.redis_url, decode_responses=True)
    return _client


async def check_connection() -> bool:
    return bool(await get_redis().ping())
