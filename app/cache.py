from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis

from app import settings

_memory: dict[str, str] = {}
_redis: Redis | None = None


async def init() -> None:
    global _redis
    if not settings.REDIS_URL:
        _redis = None
        return
    _redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    await _redis.ping()


async def close() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


async def ping() -> bool:
    if settings.REDIS_URL and _redis is None:
        return False
    if _redis is None:
        return True
    try:
        return bool(await _redis.ping())
    except Exception:
        return False


def backend() -> str:
    return "redis" if _redis is not None else "memory"


async def get_json(key: str) -> Any | None:
    raw = await _get(key)
    if raw is None:
        return None
    return json.loads(raw)


async def set_json(key: str, value: Any, ttl: int | None = None) -> None:
    payload = json.dumps(value)
    if ttl is None:
        await _set(key, payload, None)
        return
    await _set(key, payload, ttl)


async def delete_prefix(prefix: str) -> int:
    if _redis is not None:
        removed = 0
        async for key in _redis.scan_iter(match=f"{prefix}*"):
            await _redis.delete(key)
            removed += 1
        return removed
    keys = [key for key in list(_memory) if key.startswith(prefix)]
    for key in keys:
        del _memory[key]
    return len(keys)


async def acquire_lock(name: str, ttl: int = 180) -> bool:
    if _redis is None:
        return True
    return bool(await _redis.set(name, "1", nx=True, ex=ttl))


async def release_lock(name: str) -> None:
    if _redis is not None:
        await _redis.delete(name)


async def _get(key: str) -> str | None:
    if _redis is not None:
        return await _redis.get(key)
    return _memory.get(key)


async def _set(key: str, value: str, ttl: int | None) -> None:
    if _redis is not None:
        if ttl:
            await _redis.set(key, value, ex=ttl)
        else:
            await _redis.set(key, value)
        return
    _memory[key] = value
